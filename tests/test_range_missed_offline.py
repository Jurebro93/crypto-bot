"""11.11. (Jure: "propušteni tokeni u range praćenje", flag range_missed G27, rangedca/missed.py) and the owner's new
rug rule (rugfilter/collapse): every token a skip journal labels propušteno (skipped, then >= +20 % within 60 min)
enters the range watchlist once as source missed for 72 h, passes the owner's filters (hard blocks + volume 1 h >=
$10k), is entered only by the range rules (detect's range, never the skip's price), only on the demo account until
>= 20 closed rounds of source missed pass the live proof; "rugan" = the pool pulled > 50 %, the dev / a top holder
selling or a high rug risk, a crash without that is a "dump nakon pumpe" (P x 0.7, no block); the EV report and
get_range_candidates show missed vs the other sources. No network.

    python3 -m unittest tests.test_range_missed_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import copy  # noqa: E402
from rangedca import data, detect, gate, market, missed, trade, view  # noqa: E402
from rugfilter import archive, collapse  # noqa: E402
from trade import edge, settings  # noqa: E402
from tests.test_range_dca_offline import LU, MINT, PU, TradeBase  # noqa: E402
from tests.test_range_market_offline import Net, pair, snaps  # noqa: E402

D = 86400
NOW = 1_794_400_000 - 1_794_400_000 % 60
A, B, C, OLD, LOW = ("A" * 40 + "pump", "B" * 40 + "pump", "C" * 40 + "pump", "O" * 40 + "pump", "L" * 40 + "pump")
X = "CccS" + "x" * 36 + "y1eU"   # the owner's example (CccS…y1eU)
REAL_RUGGED = copy._rugged      # the guard itself (the fixtures replace it with a stand-in)


def skip_stores(d, now=NOW):
    """minute.db / fast.db / proposals.db of the three skip journals, each with a propušteno and a not-propušteno row."""
    from fast import store as fstore
    from kol import preskoceni
    from proposals import store as pstore
    paths = {k: os.path.join(d, f"{k}.db") for k in ("minute", "fast", "proposals")}
    mc = sqlite3.connect(paths["minute"])
    preskoceni.ensure(mc)
    for tok, ts, hi in ((A, now - 3 * 3600, 0.25), (LOW, now - 3 * 3600, 0.10), (OLD, now - 80 * 3600, 0.90)):
        mc.execute("INSERT INTO skip_path (token, ts, entry, hi60, done_ts) VALUES (?,?,?,?,?)", (tok, ts, 1e-4, hi, ts + 3900))
    mc.commit()
    mc.close()
    fc = fstore.connect(paths["fast"])
    for tok, dec, mx, miss in ((B, "SKIP", 31.0, 1), (LOW, "BUY_PAPER", 40.0, 0), (LOW, "SKIP", 12.0, 0)):
        fc.execute("INSERT INTO signals (token, source_id, sig_ts, decided_ts, decision, max60, missed, status) VALUES "
                   "(?,?,?,?,?,?,?, 'done')", (tok, f"s{dec}{mx}", now - 7200, now - 7200, dec, mx, miss))
    fc.commit()
    fc.close()
    pc = pstore.connect(paths["proposals"])
    for tok, st, g in ((C, "isteklo", 26.0), (LOW, "odbijeno", 8.0), (LOW, "kupljeno", 60.0)):
        pc.execute("INSERT INTO proposals (token, created_ts, status, after) VALUES (?,?,?,?)",
                   (tok, now - 5 * 3600, st, json.dumps({"1h": {"status": "ok", "max_gain_pct": g}})))
    pc.commit()
    pc.close()
    return paths


class Env(unittest.TestCase):
    """range.db, the skip journals and the rug data of their own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.paths = skip_stores(d)
        env = {"RANGE_DB": os.path.join(d, "range.db"), "RANGE_HYPE_DB": os.path.join(d, "hype_r.db"),
               "TOPICS_DB": os.path.join(d, "topics.db"), "MINUTE_DB": self.paths["minute"],
               "FAST_DB": self.paths["fast"], "PROPOSALS_DB": self.paths["proposals"]}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("BIRDEYE_API_KEY", None)
        from topcheck import store as tstore
        for obj, name, val in ((market, "_meter", lambda *a, **k: None), (market, "from_graduates", lambda con, now: 0),
                               (market, "from_scanner", lambda con, now, scan_db=None: 0),
                               (collapse, "RUG_DB", os.path.join(d, "rug.db")), (tstore, "DB", os.path.join(d, "top.db")),
                               (archive, "HYPE_DB", os.path.join(d, "hype.db")),
                               (copy, "_rugged", lambda *a, **k: None)):
            pm = mock.patch.object(obj, name, val)
            pm.start()
            self.addCleanup(pm.stop)
        collapse._EVIDENCE.clear()
        archive.forget_cache()
        self.addCleanup(archive.forget_cache)
        self.con = data.connect()
        market.ensure(self.con)
        self.addCleanup(self.con.close)

    def rug_db(self, token, verdict, hard=(), flags=(), score=None):
        c = sqlite3.connect(collapse.RUG_DB)
        c.execute("CREATE TABLE IF NOT EXISTS rug_reports (mint TEXT, checked_at INTEGER, symbol TEXT, verdict TEXT, "
                  "score REAL, wash_score REAL, bundle_pct REAL, sniper_pct REAL, cluster_pct REAL, top10_pct REAL, "
                  "dev TEXT, data TEXT, PRIMARY KEY (mint, checked_at))")
        c.execute("INSERT INTO rug_reports (mint, checked_at, verdict, score, data) VALUES (?,?,?,?,?)",
                  (token, NOW, verdict, score, json.dumps({"hard_fails": list(hard), "flags": list(flags)})))
        c.commit()
        c.close()
        collapse._EVIDENCE.clear()

    def row(self, tok):
        cur = self.con.execute("SELECT * FROM mkt WHERE token=?", (tok,))
        r = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], r)) if r else None


# ---------------------------------------------------------------------------------------------------------------
class Universe(Env):
    def test_every_propusteno_of_the_three_journals_and_nothing_else(self):
        got = missed.labelled(NOW)
        self.assertEqual(set(got), {A, B, C})                                # +25 %, +31 %, +26 % within 60 min
        self.assertEqual(got[A]["via"], {"preskoceni"})
        self.assertEqual((got[B]["via"], got[B]["pct"]), ({"brzi_put"}, 31.0))
        self.assertEqual(got[C]["via"], {"prijedlozi"})
        self.assertNotIn(OLD, got)                                           # skipped 80 h ago: older than 72 h
        self.assertNotIn(LOW, got)                                           # +10 %, bought, rejected at +8 %

    def test_enters_once_due_at_once_with_72_h(self):
        logs = []
        self.assertEqual(missed.from_missed(self.con, NOW, logs.append), 3)
        r = self.row(A)
        self.assertEqual((r["src"], r["watched"], r["next_ts"], r["via"]), ("missed", 0, NOW, missed.VIA))
        self.assertEqual(r["missed_until"], NOW + 72 * 3600)
        self.assertEqual(r["missed_pct"], 25.0)
        self.assertTrue(any("+3 tokena" in x and "72 h" in x for x in logs))
        # read again later: the same labels change nothing, the 72 h are not renewed
        self.assertEqual(missed.from_missed(self.con, NOW + 600, logs.append), 0)
        self.assertEqual(self.row(A)["missed_until"], NOW + 72 * 3600)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM mkt").fetchone()[0], 3)
        # within EVERY_S nothing is read at all
        self.assertEqual(missed.from_missed(self.con, NOW + 601, logs.append), 0)

    def test_after_72_h_back_to_market_and_an_event_keeps_its_source(self):
        missed.from_missed(self.con, NOW, print)
        market.add(self.con, B, "event", NOW, src="event")
        self.assertEqual(self.row(B)["src"], "event")                        # event > missed
        market.add(self.con, A, "gt", NOW)
        self.assertEqual(self.row(A)["src"], "missed")                       # missed > market
        self.assertEqual(missed.expire(self.con, NOW + 72 * 3600 - 1), 0)
        self.assertEqual(missed.expire(self.con, NOW + 72 * 3600, log=lambda *_: None), 2)   # A and C
        self.assertEqual((self.row(A)["src"], self.row(C)["src"]), ("market", "market"))
        # an event token whose topic ended falls back to missed while its 72 h last
        self.con.execute(f"UPDATE mkt SET src={missed.fallback_sql()} WHERE token=?", (NOW + 3600, B))
        self.assertEqual(self.row(B)["src"], "missed")

    def test_flag_off_sends_every_missed_token_back(self):
        missed.from_missed(self.con, NOW, print)
        self.assertEqual(missed.expire(self.con, NOW, on=False), 3)


class Filters(Env):
    OK = {"price": 1e-4, "bonded": True, "mcap": 35_000, "liq": 15_000, "vol_h1": 10_000}

    def test_rule_b_numbers_without_the_market_lists_mc_or_age(self):
        self.assertTrue(market.check(self.OK, NOW - 600, "missed", NOW)[0])  # 35k MC, 10 min old: fine for missed
        self.assertFalse(market.check(self.OK, NOW - 600, "market", NOW)[0])
        for change, word in (({"mcap": 25_000}, "30k"), ({"liq": 14_000}, "likvidnost"), ({"vol_h1": 9_000}, "volumen"),
                             ({"bonded": False}, "krivulji"), ({"price": None}, "cijene")):
            res = market.check({**self.OK, **change}, NOW - 600, "missed", NOW)
            self.assertFalse(res[0], change)
            self.assertIn(word, res[1])
        self.assertTrue(market.check({**self.OK, "vol_h1": 6_000}, NOW - 600, "missed", NOW, keep=True)[0])

    def test_hard_blocks(self):
        s = dict(self.OK)
        self.assertIsNone(missed.hard_block(self.con, A, s, NOW))
        with mock.patch.object(copy, "_rugged", lambda *a: {"text": "izvučena likvidnost (70 % manje)"}):
            self.assertIn("rug: izvučena", missed.hard_block(self.con, A, s, NOW))
        self.rug_db(A, "VISOK RIZIK", score=31)
        self.assertIn("visok rizik", missed.hard_block(self.con, A, s, NOW))
        self.rug_db(B, "OPREZ", flags=["dev je prodao 60% (kupio 12% na startu)"])
        self.assertIn("dev prodaje", missed.hard_block(self.con, B, s, NOW))
        self.rug_db(C, "ODBAČEN", hard=["freeze authority nije ugašena: dev može zamrznuti tvoje tokene"])
        self.assertIn("freeze authority", missed.hard_block(self.con, C, s, NOW))
        from topcheck import store as tstore
        tc = tstore.connect(tstore.DB)
        tstore.put(tc, {"token": LOW, "ts": NOW, "safety_json": json.dumps(
            {"checks": {"honeypot": ["fail", "honeypot: na testnoj prodaji vrati se samo 10% vrijednosti"]}})})
        tc.commit()
        tc.close()
        self.assertIn("honeypot", missed.hard_block(self.con, LOW, s, NOW))
        data.kv_put(self.con, f"hold:{OLD}", {"checked": NOW - 600, "why": "holderi s prijenosom neto prodali 3 %"})
        self.assertIn("top holderi prodaju", missed.hard_block(self.con, OLD, s, NOW))
        ac = archive.connect(archive.HYPE_DB)
        ac.execute("INSERT INTO rug_archive (token, kind, peak_liq, last_liq) VALUES (?, 'likvidnost', 50000, 5000)", (X,))
        ac.commit()
        ac.close()
        archive.forget_cache()
        self.assertIn("arhivi", missed.hard_block(self.con, X, s, NOW))

    def test_the_pass_admits_the_clean_ones_and_holds_the_blocked(self):
        prs = {t: pair(t, mc=60_000, liq=30_000, vol_h1=20_000, created=NOW - 3600) for t in (A, B)}
        prs[C] = pair(C, mc=60_000, liq=30_000, vol_h1=4_000, created=NOW - 3600)   # volume 1 h $4k
        self.rug_db(B, "VISOK RIZIK", score=20)
        logs = []
        out = market.pass_once(self.con, NOW, Net(prs), logs.append, pulse=set(), market_on=False, event_on=False,
                               missed_on=True)
        self.assertEqual(out["tokens"], [A])                                 # 1 h old: no 6 h rule for missed
        self.assertEqual(out["src"], {A: "missed"})
        self.assertEqual(out["stats"]["missed"], 1)
        self.assertIn("visok rizik", self.row(B)["why"])
        self.assertEqual(self.row(B)["next_ts"], NOW + missed.HARD_WAIT_S)
        self.assertIn("volumen", self.row(C)["why"])
        # market_on off: the market part rests, a missed token stays; after its 72 h it leaves with the market part
        self.con.execute("UPDATE mkt SET missed_until=? WHERE token=?", (NOW + 60, A))
        out = market.pass_once(self.con, NOW + 120, Net(prs), logs.append, pulse=set(), market_on=False,
                               event_on=False, missed_on=True)
        self.assertEqual(out["tokens"], [])
        self.assertEqual(self.row(A)["src"], "market")


class Job(TradeBase):
    """run_range.once with only range_missed on: the range of a missed token comes from detect, source missed."""

    def setUp(self):
        super().setUp()
        self.paths = skip_stores(self.rdir.name, self.now - self.now % 60)
        env = {"MINUTE_DB": self.paths["minute"], "FAST_DB": self.paths["fast"], "PROPOSALS_DB": self.paths["proposals"],
               "TOPICS_DB": os.path.join(self.rdir.name, "topics.db")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        from topcheck import store as tstore
        for obj, name, val in ((market, "_meter", lambda *a, **k: None), (market, "from_graduates", lambda con, now: 0),
                               (market, "from_scanner", lambda con, now, scan_db=None: 0),
                               (collapse, "RUG_DB", os.path.join(self.rdir.name, "rug.db")),
                               (tstore, "DB", os.path.join(self.rdir.name, "top.db")),
                               (archive, "HYPE_DB", os.path.join(self.rdir.name, "hype.db"))):
            pm = mock.patch.object(obj, name, val)
            pm.start()
            self.addCleanup(pm.stop)
        archive.forget_cache()
        self.addCleanup(settings._FLAG_CACHE.clear)

    def test_range_and_entry_only_from_detect_source_missed_paper_only(self):
        import run_range
        now = self.now - self.now % 60
        con = data.connect()
        market.ensure(con)
        for s in snaps(now):
            data.save_snap(con, A, dict(s, pool="Pool" + A[:8], dex="pumpswap", symbol="AAA"))
        con.commit()
        con.close()
        self.mode("shadow", "range_missed")
        last = snaps(now)[-1]
        prs = {A: pair(A, px=last["price"], mc=last["mcap"], liq=50_000, created=now - 3 * D)}
        out = run_range.once(now=now, log=lambda *_: None, fetch=lambda t: self.fail("no signal pass"), net=Net(prs),
                             gt_fetch=lambda *a: None, post=lambda *a: {})
        self.assertIn("propušteni 1", out)
        con = data.connect()
        r, _st = data.load_range(con, A)
        src = con.execute("SELECT src FROM ranges WHERE token=?", (A,)).fetchone()[0]
        con.close()
        self.assertEqual((r["source"], r["sources"], src), ("missed", ["missed"], "missed"))
        self.assertEqual(r["status"], detect.ACTIVE, r["why"])
        self.assertEqual(r["ts"], now)                                       # computed now by detect (computed_ts)
        d = view.candidates(min_score=0.3, now=now)
        row = {c["token"]: c for c in d["candidates"]}[A]
        self.assertEqual((row["source"], row["paper_only"], row["computed_ts"]), ("missed", True, now))
        self.assertEqual(d["watched_by_source"]["missed"], 1)
        self.assertEqual(d["missed"]["list"]["watched"], 1)
        self.assertEqual(d["missed"]["flag_mode"], "shadow")
        self.assertIn("rangedca/detect", d["missed"]["entry"])
        self.assertIn("tek 0", d["missed"]["live_gate"])
        self.assertEqual({c["token"] for c in view.candidates(min_score=0.3, now=now, source="missed")["candidates"]}, {A})


class Money(TradeBase):
    def setUp(self):
        super().setUp()
        gate._MCACHE.update(at=0.0, path=None, val=None)
        self.addCleanup(settings._FLAG_CACHE.clear)

    def mrng(self, **kw):
        return dict(self.rng(), source="missed", sources=["missed"], **kw)

    def rounds(self, n, src="missed", ret=0.10, user=PU):
        trade.ensure(self.lg)
        for i in range(n):
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, levels, state, pnl_usd, "
                            "ret) VALUES (?,?,?,?,'closed',?,'{}',?,?)",
                            (user, f"T{src}{i}", self.now - D, self.now - 3600 + i, json.dumps({"src": src}),
                             ret * 15, ret))
        self.lg.commit()
        gate._MCACHE.update(at=0.0, path=None, val=None)

    def test_paper_on_the_demo_account_by_the_range_rules_only(self):
        self.mode("paper")
        self.assertEqual(self.enter(rng=self.mrng()), [])                    # range_missed off: no entry
        self.mode("shadow", "range_missed")
        self.assertEqual(self.enter(rng=self.mrng()), [])                    # shadow: data only
        self.mode("paper", "range_missed")
        self.assertEqual(self.enter(rng=self.mrng(active=False, status="premalo podataka")), [])   # no detect range
        self.assertEqual(self.enter(px=80.0, rng=self.mrng()), [])           # 80 % of the range: no range entry
        done = self.enter(px=52.0, rng=self.mrng())                          # the bottom zone of detect's range
        self.assertEqual([u for u, _ in done], [PU])
        self.assertEqual(self.lots(LU), [])
        lv = json.loads(self.lg.execute("SELECT levels FROM range_rounds WHERE user=?", (PU,)).fetchone()[0])
        self.assertEqual(lv["src"], "missed")
        self.assertAlmostEqual(lv["stop_px"], self.rng()["zones"]["range_low_low"] * 0.85)   # the range's stop

    def test_live_gate_refuses_under_20_rounds_of_source_missed(self):
        self.mode("live", "range_missed")
        self.assertFalse(trade.allowed(self.mrng(), LU, self.now))
        self.assertIn("tek 0", gate.missed_refusal())
        self.rounds(25, src="signal")                                        # other sources never count
        self.rounds(19)
        self.assertIn("tek 19", gate.missed_refusal())
        self.assertFalse(trade.allowed(self.mrng(), LU, self.now))
        self.rounds(1, ret=0.10)
        self.assertIsNone(gate.missed_refusal())
        self.assertTrue(trade.allowed(self.mrng(), LU, self.now))
        self.mode("paper", "range_missed")                                   # the real account needs live
        self.assertFalse(trade.allowed(self.mrng(), LU, self.now))
        self.assertTrue(trade.allowed(self.mrng(), PU, self.now))
        self.mode("live", "range_missed")                                    # a market token still never
        self.mode("live", "range_market")
        self.assertFalse(trade.allowed(dict(self.rng(), sources=["market"]), LU, self.now))

    def test_losing_missed_rounds_never_pass(self):
        self.rounds(20, ret=-0.05)
        self.assertIn("nije prošao", gate.missed_refusal())

    def test_flag_g27_off_by_default_with_its_live_gate(self):
        self.assertEqual(settings.FLAGS["range_missed"][0], "G27")
        self.assertEqual(settings.flag("range_missed", con=self.con), "off")
        self.assertEqual(settings.LIVE_GATES["range_missed"], "rangedca.gate:missed_live_refusal")
        self.assertNotIn("range_missed", settings.NEVER_LIVE)
        self.assertNotIn("range_missed", settings.DATA_FLAGS)
        self.assertEqual(market.WATCH_FLAG["missed"], "range_missed")
        settings.put(self.con, "backtest:range_missed", {"pass": True})
        settings.set_flag(self.con, "range_missed", "paper", "Jure", now=self.now - 30 * D)
        with self.assertRaisesRegex(ValueError, "tek 0 zatvorenih paper rundi izvora missed"):
            settings.set_flag(self.con, "range_missed", "live", "Jure", paper={"n": 50, "pnl": 99.0}, now=self.now)

    def test_report_and_meta_split_missed_from_the_rest(self):
        from events import evreport
        self.rounds(3, ret=0.20)
        self.rounds(2, ret=-0.10)
        self.rounds(4, src="signal", ret=0.05)
        rows = {r["part"]: r for r in evreport.range_source_rows(self.now, "paper", self.lg)}
        m, o = rows["range:missed"], rows["range:ostali"]
        self.assertEqual((m["n"], o["n"]), (5, 4))
        self.assertAlmostEqual(m["hit_rate"], 0.6)
        self.assertAlmostEqual(m["ev_pct"], 8.0)
        self.assertAlmostEqual(o["ev_pct"], 5.0)
        self.assertEqual((m["baseline_ev_pct"], m["delta_ev_pct"]), (5.0, 3.0))
        self.assertIn("PnL +6.00 $", m["note"])
        self.assertIn("tek 5", m["note"])
        parts = [r["part"] for r in evreport.range_rows(self.now, "paper", self.lg)]
        self.assertEqual(parts, ["range", "range:missed", "range:ostali"])
        self.assertIn("range:missed", evreport.md("2026-11-11", list(rows.values())))
        bs = gate.by_source()
        self.assertEqual((bs["missed"]["n"], bs["missed"]["wins"], bs["other"]["n"]), (5, 3, 4))
        self.assertAlmostEqual(bs["missed"]["pnl_usd"], 6.0)
        self.assertEqual(view.missed_meta(self.now)["rounds_by_source"]["missed"]["n"], 5)


# ---------------------------------------------------------------------------------------------------------------
class RugRule(Env):
    def test_each_branch(self):
        liq = collapse.judge(600_000, 250_000, 60_000, 25_000)               # -58 %, the pool -58 %: pulled
        self.assertEqual(liq["kind"], "rug")
        self.assertIn("izvučena likvidnost", liq["text"])
        self.assertEqual(collapse.judge(600_000, 90_000, 62_000, 20_000)["kind"], "rug")    # -85 %, pool -68 %
        dump = collapse.judge(600_000, 90_000, 62_000, 60_000)               # -85 %, the pool holds
        self.assertEqual(dump["kind"], "dump")
        self.assertTrue(dump["text"].startswith("dump nakon pumpe"))
        self.assertEqual(collapse.judge(600_000, 90_000)["kind"], "dump")   # liquidity unknown: no proof of a rug
        ev = collapse.judge(600_000, 90_000, 62_000, 60_000, evidence="dev prodaje (dev je prodao 70%)")
        self.assertEqual(ev["kind"], "rug")
        self.assertIn("dev prodaje", ev["text"])
        self.assertIsNone(collapse.judge(600_000, 250_000, 60_000, 40_000))  # -58 %, the pool -33 %: nothing
        self.assertIsNone(collapse.judge(600_000, 400_000, 60_000, 10_000))  # above half the peak: nothing
        # the archive's cleanup keeps the old rule (what it deletes does not change)
        self.assertEqual(archive.judge(600_000, 90_000, 62_000, 60_000)[0], "srusen")

    def peak_row(self, tok, rows):
        db = os.path.join(self.tmp.name, "hype_peaks.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE IF NOT EXISTS hype_signals (ts INTEGER, token TEXT, mcap REAL, liquidity REAL)")
        c.executemany("INSERT INTO hype_signals VALUES (?,?,?,?)", [(ts, tok, mc, lq) for ts, mc, lq in rows])
        c.commit()
        c.close()
        return collapse.peaks(db, [tok], now=NOW).get(tok)

    def test_evidence_from_the_rug_filter_the_dev_and_the_holders(self):
        pk = self.peak_row(A, [(NOW - 7200, 600_000, 62_000), (NOW - 60, 90_000, 60_000)])
        self.assertEqual(collapse.assess(pk, token=A)["kind"], "dump")
        self.assertIsNone(collapse.check(pk, token=A))
        self.rug_db(A, "VISOK RIZIK", score=35)
        self.assertEqual(collapse.assess(pk, token=A)["kind"], "rug")
        self.assertIn("visok rizik", collapse.check(pk, token=A)["text"])
        self.rug_db(B, "OPREZ", flags=["dev je prodao 55% (kupio 9% na startu)"])
        self.assertIn("dev prodaje", collapse.check(pk, token=B)["text"])
        data.kv_put(self.con, f"hold:{C}", {"checked": int(time.time()) - 300, "why": "neto prodali 4.0 % supplyja"})
        self.con.commit()
        self.assertIn("top holderi prodaju", collapse.check(pk, token=C)["text"])
        self.rug_db(OLD, "ODBAČEN", hard=["likvidnost samo $3,000"])           # thin liquidity is not a high risk
        self.assertIsNone(collapse.check(pk, token=OLD))

    def test_x_crash_and_recovery_is_a_dump_not_a_rug(self):
        # CccS…y1eU: called at $151.8k, peak $600k, -85 % to $90k with the pool steady, no dev sells, then $387k
        pk = self.peak_row(X, [(NOW - 20 * 3600, 151_800, 58_000), (NOW - 16 * 3600, 600_000, 62_000),
                               (NOW - 8 * 3600, 90_000, 60_000)])
        bottom = collapse.assess(pk, 90_000, 60_000, token=X)
        self.assertEqual(bottom["kind"], "dump")
        self.assertIn("dump nakon pumpe: pao 85 %", bottom["text"].replace("%", " %").replace("  ", " "))
        self.assertIsNone(collapse.check(pk, 90_000, 60_000, token=X))       # no rug label, no block
        self.assertIsNone(collapse.assess(pk, 387_000, 61_000, token=X))      # +155 % from the call: nothing at all
        self.assertAlmostEqual(387_000 / 151_800 - 1, 1.55, places=2)
        hdb = os.path.join(self.tmp.name, "hype_peaks.db")
        with mock.patch.object(copy, "_rugged", REAL_RUGGED), mock.patch("ui.data.HYPE_DB", hdb), \
                mock.patch("time.time", lambda: NOW):
            self.assertIsNone(copy._rugged(X, 90_000, 60_000))               # every trading guard: no block
            self.assertEqual(copy._collapse(X, 90_000, 60_000)["kind"], "dump")

    def test_archive_kinds_read_through_the_new_rule_and_logged(self):
        ac = archive.connect(archive.HYPE_DB)
        for tok, kind, pl, ll in ((A, "srusen", 60_000, 58_000), (B, "srusen", 60_000, 10_000), (C, "likvidnost", 50_000, 5_000),
                                  (OLD, "mehanika", None, None), (X, "srusen", None, None)):
            ac.execute("INSERT INTO rug_archive (token, kind, peak_liq, last_liq) VALUES (?,?,?,?)", (tok, kind, pl, ll))
        ac.commit()
        ac.close()
        logs = []
        k = archive.kinds(log=logs.append)
        self.assertEqual(k, {A: "dump", B: "rug", C: "rug", OLD: "rug", X: "dump"})
        self.assertEqual(len(logs), 1)
        self.assertIn("od 3 redova 'srusen' 2 je dump nakon pumpe", logs[0])
        archive.kinds(log=logs.append)
        self.assertEqual(len(logs), 1)                                       # logged once
        self.assertEqual(archive.blocked(archive.HYPE_DB), frozenset({A, B, C, OLD, X}))   # the cleanup set: unchanged


class DumpModifier(Env):
    def test_p_x_07_and_no_block(self):
        m = edge.modifiers(dump="dump nakon pumpe: pao 85 % od vrha")
        self.assertAlmostEqual(m["p_mult"], 0.7)
        self.assertEqual(m["size_mult"], 1.0)
        self.assertEqual(m["tags"][0]["key"], "dump")
        self.assertIn("nije blok", m["tags"][0]["text"])
        self.assertAlmostEqual(edge.modifiers(dump=True, shill=True)["p_mult"], 0.35)

    def src(self, col):
        class S:
            def collapse(self, token, mcap, liq):
                return col

            def concentration(self, token):
                return None, "nepoznato"
        return S()

    def test_kandidati_rug_view(self):
        from ui import kandidati
        d = {"kind": "dump", "text": "dump nakon pumpe: pao 85 % od vrha ($600.0k → $90.0k), likvidnost drži"}
        rv = kandidati.rug_view(A, 90_000, 60_000, self.src(d), ({}, {}))
        self.assertEqual((rv["level"], rv["hard"], rv["dump"]), ("oprez", [], d["text"]))
        rv = kandidati.rug_view(A, 90_000, 60_000, self.src({"kind": "rug", "text": "izvučena likvidnost"}), ({}, {}))
        self.assertEqual(rv["level"], "hard")
        rv = kandidati.rug_view(A, 90_000, 60_000, self.src({"text": "MC 85 % ispod vrha"}), ({}, {}))   # older shape
        self.assertEqual(rv["level"], "hard")
        rv = kandidati.rug_view(A, 90_000, 60_000, self.src(d), ({}, {A: {"verdict": "VISOK RIZIK", "score": 30}}))
        self.assertEqual(rv["level"], "hard")                                # a crash with a high rug risk = rug
        self.assertIn("rugan", rv["hard"][0])
        self.assertIsNone(rv["dump"])
        rv = kandidati.rug_view(A, 90_000, 60_000, self.src(None), ({}, {}), archived={A: "dump"})
        self.assertEqual((rv["level"], bool(rv["dump"])), ("oprez", True))
        rv = kandidati.rug_view(A, 90_000, 60_000, self.src(None), ({}, {}), archived={A: "rug"})
        self.assertEqual(rv["level"], "hard")
        self.assertEqual(kandidati.rug_view(A, 1, 1, self.src(None), ({}, {}), archived=frozenset({A}))["level"], "hard")

    def test_fast_and_proposals(self):
        from fast import decide
        from proposals import build
        checks = {k: {"status": "ok", "text": k, "values": {"cost_pct": 2.0} if k == "price" else {}} for k in decide.ORDER}
        q = {"kind": "wallet_follow", "hits": 9, "n": 12, "closed": 12}
        p0 = decide.decide(checks, q)["p_tp"]
        checks["rug"]["values"] = {"dump": "dump nakon pumpe: pao 80 % od vrha"}
        d = decide.decide(checks, q)
        self.assertAlmostEqual(d["p_tp"], round(p0 * 0.7, 4), places=3)
        self.assertEqual(d["modifiers"]["tags"][0]["key"], "dump")
        r = {"token": A, "rug": {"level": "oprez", "dump": "dump nakon pumpe: pao 80 % od vrha"}}
        self.assertAlmostEqual(build.modifiers_of(r, {"wash": {}})["p_mult"], 0.7)
        self.assertAlmostEqual(build.modifiers_of({"token": A, "rug": {}}, {"wash": {}})["p_mult"], 1.0)


if __name__ == "__main__":
    unittest.main()
