"""11.11. (Jure, the owner's decisions 1 and 4): the range stop per account and the proposals' EV from the zone.

Decision 1 (rangedca/rules.atr_range / reclaim_*, rangedca/trade.py, rangedca/gate.reclaim_refusal, run_range.py):
the real account's range stop is the ATR stop (variant b), the demo account's the ATR stop + reclaim (a lot 1 within
30 min of a stop-out when the price is back above range_low with buys >= 60 %; not after 30 min, not with buys 50 %;
its stop under the new low by the ATR rule), an event / paper_only token never on the real account; the real account's
reclaim gate (>= 7 nights of the nightly stop comparison, >= 20 closed reclaim rounds, EV > 0 after cost); the stop log
line ("range stop SYM: pravi račun ATR MC ..."), once per change; the owner's labels never change a win rate, an EV or
a hit rate (and a label-only fixture token never reaches the range_flip gate's numbers).
Decision 4 (proposals/publish.py, build, paper, store, view): HAOBIBI proposal #2 reconstructed (made at MC ~$89k, zone
$104-112k, stop ~$88.6k): its EV comes from the zone's middle, it is NOT published ("čeka zonu" with the reason, in
get_proposals and "prikaži skoro", not in "Što kupiti"); the 20-s loop publishes it once the price is in the zone with
>= 1 ATR to the stop. No network.

    python3 -m unittest tests.test_stop_zona_offline
"""
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import copy as lcopy  # noqa: E402
from proposals import build, calib, job, paper, publish, store as pstore, strategies, view as pview  # noqa: E402
from rangedca import backtest, data, detect, gate, owner, rules, trade, view as rview  # noqa: E402
from trade import settings  # noqa: E402
from tests.test_kandidati_offline import NOW, live  # noqa: E402
from tests.test_prijedlozi_offline import PSources  # noqa: E402
from tests.test_range_dca_offline import MINT, S, TradeBase, tri  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER


class Base(TradeBase):
    def setUp(self):
        super().setUp()
        gate._RCACHE.update(at=0.0, key=None, val=None)
        trade._CACHE.pop("reclaim_gate_log", None)

    def arng(self, atr=4.0, bs=0.6, now=None, **kw):
        """The test range (MC: range_low_low 51k, range_low 52k, top 95-100k) with ATR 4k: ATR stop 45k (12 % under)."""
        r = self.rng(buy_share_5m=bs, **kw)
        r["atr"] = atr * S
        r["ts"] = r["mts"] = now or self.now
        return r

    def go(self, px, now, bs=0.6, rng=None):
        return trade.run_once(self.lg, self.mk(px), now, {MINT: rng or self.arng(bs=bs, now=now)}, self.lim, 100.0)

    def proof_rounds(self, n=20, ret=0.1, reclaim=False, user=PU):
        trade.ensure(self.lg)
        lv = json.dumps({"reclaim": True}) if reclaim else None
        for i in range(n):
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, cost_usd, pnl_usd, ret, "
                            "levels) VALUES (?,?,?,?,?,?,?,?,?)",
                            (user, f"T{'R' if reclaim else 'N'}{i}", 1, 2, "closed", 10.0, ret * 10, ret, lv))
        self.lg.commit()
        gate._CACHE.update(at=0.0)
        gate._RCACHE.update(at=0.0)

    def nights(self, n):
        con = data.connect()
        data.kv_put(con, "stop_backtest_nights", [f"2026-11-{d:02d}" for d in range(1, n + 1)])
        con.commit()
        con.close()
        gate._RCACHE.update(at=0.0)

    def round_of(self, user, status="open"):
        rs = trade.rounds(self.lg, status, user)
        return rs[-1] if rs else None


# ---------- decision 1: the stop per account ------------------------------------------------------------------------
class StopPerAccount(Base):
    def test_real_account_atr_stop_and_demo_the_same_atr_stop(self):
        self.mode("live")                                                    # range_dca live, its own proof passed
        self.proof_rounds()
        done = self.go(52.0, self.now)
        self.assertEqual(sorted(u for u, _t in done), sorted([LU, PU]))
        want = detect.vol_stop(51.0 * S, 4.0 * S)
        self.assertEqual(want[1], "atr")
        self.assertAlmostEqual(want[0], 45.0 * S)                            # 51 - 1.5 x 4, not 51 x 0.85 = 43.35
        for u in (LU, PU):
            lv = self.round_of(u)["levels"]
            self.assertAlmostEqual(lv["stop_px"], 45.0 * S)
            self.assertEqual(lv["stop_kind"], "atr")
            self.assertAlmostEqual(lv["rl"], 52.0 * S)                       # range_low: the reclaim's line
        # the real account's stop sells at the ATR stop, not at x 0.85
        out = self.exits(44.9, rng=self.arng())
        self.assertTrue(all("1,5 × ATR" in x for x in out), out)
        self.assertEqual(sorted(r["user"] for r in trade.rounds(self.lg, "closed") if r["exit_reason"] == "stop"),
                         sorted([LU, PU]))
        # ATR unknown: x 0.85 (variant b's own fallback, detect.vol_stop "fixed")
        self.assertAlmostEqual(rules.levels_of(rules.atr_range(self.rng()))["stop_px"], 51.0 * S * 0.85)
        # an old x 0.85 round tightens to the ATR stop and says so
        self.assertEqual(rules.merge_levels({"stop_px": 43.35 * S}, rules.levels_of(rules.atr_range(self.arng())))
                         ["stop_kind"], "atr")
        self.assertNotIn("stop_kind", rules.merge_levels({"stop_px": 46.0 * S}, rules.levels_of(rules.atr_range(
            self.arng()))))

    def test_demo_reclaim_within_30_min_with_buys_60(self):
        self.mode("paper")
        self.assertEqual(len(self.go(52.0, self.now)), 1)
        rid = self.round_of(PU)["id"]
        out = self.exits(44.9, rng=self.arng())
        self.assertIn("reclaim moguć do", out[0])
        st = self.round_of(PU, "closed")["state"]["reclaim"]
        self.assertEqual((st["until"], st["done"]), (self.now + 1800, None))
        self.assertAlmostEqual(st["rl"], 52.0 * S)
        self.assertEqual(self.go(44.0, self.now + 60), [])                   # under range_low: waits; the new low 44
        self.assertAlmostEqual(self.round_of(PU, "closed")["state"]["reclaim"]["low"], 44.0 * S)
        self.assertEqual(self.go(60.0, self.now + 120, bs=0.5), [])          # back above range_low, buys 50 %: no
        done = self.go(60.0, self.now + 180)                                 # buys 60 %: the reclaim
        self.assertEqual(len(done), 1, done)
        self.assertEqual(done[0][0], PU)
        self.assertIn("range reclaim RNG: lot 1", done[0][1])
        r = self.round_of(PU)
        lv = r["levels"]
        self.assertEqual((lv["reclaim"], lv["reclaim_of"], lv["stop_kind"]), (True, rid, "reclaim"))
        want = rules.reclaim_stop(44.0 * S, 4.0 * S)[0]                      # under the NEW low by the ATR rule
        self.assertAlmostEqual(want, 38.0 * S)                               # 44 - 1.5 x 4
        self.assertAlmostEqual(lv["stop_px"], want)
        self.assertAlmostEqual(lv["rhl"], 95.0 * S)                          # the same take-profit rules
        self.assertTrue(self.round_of(PU, "closed")["state"]["reclaim"]["done"])
        self.assertEqual(self.go(60.0, self.now + 200), [])                  # one reclaim per stopped round
        # the reclaim round keeps its own stop (the range's 45k does not replace it), sells at it, never re-arms
        self.assertEqual(self.exits(40.0, rng=self.arng(), now=self.now + 240), [])
        out = self.exits(37.9, rng=self.arng(), now=self.now + 260)
        self.assertIn("tvrdi stop reclaim runde", out[0])
        self.assertNotIn("reclaim moguć", out[0])
        self.assertTrue(gate.is_reclaim(json.dumps(lv)))

    def test_no_reclaim_after_30_min(self):
        self.mode("paper")
        self.go(52.0, self.now)
        self.exits(44.9, rng=self.arng())
        self.assertEqual(self.go(60.0, self.now + 1801), [])
        self.assertIsNone(self.round_of(PU))
        self.assertEqual(rules.reclaim_check({"until": 100, "rl": 1.0, "low": 0.5}, 2.0, {"buy_share_5m": 0.9}, 101),
                         "više od 30 min od stopa")

    def test_real_account_reclaim_refused_until_its_gate_passes(self):
        self.mode("live")
        self.proof_rounds()
        self.go(52.0, self.now)
        self.exits(44.9, rng=self.arng())
        done = self.go(60.0, self.now + 60)
        self.assertEqual([u for u, _t in done], [PU])                        # the demo account reclaims, the real not
        self.assertIsNone(self.round_of(LU))
        self.assertIn("noći usporedbe", gate.reclaim_refusal())
        # the gate passes (7 nights, 20 reclaim rounds with EV > 0): the real account's armed reclaim is bought
        self.nights(7)
        self.proof_rounds(20, ret=0.05, reclaim=True)
        self.assertIsNone(gate.reclaim_refusal())
        done = self.go(60.0, self.now + 120)
        self.assertEqual([u for u, _t in done], [LU])
        self.assertTrue(self.round_of(LU)["levels"]["reclaim"])

    def test_event_and_paper_only_tokens_never_on_the_real_account(self):
        self.mode("live")
        self.proof_rounds()
        self.mode("paper", "event_tokens")
        ev = self.arng()
        ev.update(source="event", sources=["event"])
        done = self.go(52.0, self.now, rng=ev)
        self.assertEqual([u for u, _t in done], [PU])                        # paper only, b + reclaim
        self.assertFalse(trade.allowed(ev, LU, self.now))
        # even with the reclaim gate passing, an armed reclaim of an event token never buys on the real account
        trade.ensure(self.lg)
        arm = {"until": self.now + 1800, "rl": 52.0 * S, "low": 44.0 * S, "atr": 4.0 * S, "levels": {}, "done": None}
        self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, levels, state) VALUES "
                        "(?,?,?,?,?,?,?)", (LU, "E" * 44, self.now - 600, self.now, "closed",
                                            json.dumps({"src": "event"}), json.dumps({"reclaim": arm})))
        self.lg.commit()
        with mock.patch.object(gate, "reclaim_refusal", lambda *a, **k: None):
            ev2 = dict(ev)
            got = trade.run_once(self.lg, self.mk(60.0), self.now + 60, {"E" * 44: ev2}, self.lim, 100.0)
        self.assertNotIn(LU, [u for u, _t in got])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM range_rounds WHERE user=? AND status='open'",
                                         (LU,)).fetchone()[0], 0)


class ReclaimGate(Base):
    def test_refused_under_7_nights_20_rounds_or_ev_not_above_zero_allowed_when_all_pass(self):
        self.assertIn("tek 0 noći", gate.reclaim_refusal())
        self.nights(6)
        self.proof_rounds(20, ret=0.05, reclaim=True)
        self.assertIn("tek 6 noći usporedbe stopova, treba 7", gate.reclaim_refusal())
        self.nights(7)
        self.assertIsNone(gate.reclaim_refusal())                           # 7 nights, 20 rounds, EV +5 %
        self.assertIsNone(gate.reclaim_live_refusal(None, now=self.now))    # trade/settings.LIVE_GATES' shape
        self.lg.execute("DELETE FROM range_rounds WHERE token='TR19'")
        self.lg.commit()
        gate._RCACHE.update(at=0.0)
        self.assertIn("zatvorenih reclaim rundi 19 od potrebnih 20", gate.reclaim_refusal())
        self.lg.execute("DELETE FROM range_rounds")
        self.lg.commit()
        self.proof_rounds(10, ret=0.02, reclaim=True)
        self.proof_rounds(10, ret=-0.02, reclaim=True)                       # EV exactly 0: refused
        self.lg.execute("UPDATE range_rounds SET token = token || 'b' WHERE ret < 0")
        self.lg.commit()
        gate._RCACHE.update(at=0.0)
        self.assertIn("treba barem +3 %", gate.reclaim_refusal())        # 11.11. (Jure): EV >= +3 % after cost
        ok, why, s = gate.reclaim_proof_ok([0.02] * 10 + [-0.019] * 10)    # EV +0,05 %: above zero, under +3 %
        self.assertEqual((ok, s["n"]), (False, 20))
        ok, why, s = gate.reclaim_proof_ok([0.08] * 10 + [-0.019] * 10)    # EV +3,05 %
        self.assertEqual((ok, why, s["n"]), (True, None, 20))

    def test_reclaim_rounds_are_counted_apart(self):
        self.proof_rounds(20, ret=0.1)
        self.proof_rounds(5, ret=-0.5, reclaim=True)
        self.assertEqual(gate.proof()["n"], 20)                              # range_dca's own proof: no reclaim rounds
        self.assertIsNone(gate.refusal())
        self.assertEqual(gate.reclaim_proof()["n"], 5)
        self.assertEqual(gate.by_source()["other"]["n"], 20)

    def test_the_nightly_run_counts_its_nights_and_keeps_label_only_tokens_out_of_the_flip_gate(self):
        from tests.test_range_haobibi_offline import load as hload
        fx, cs = hload("range_haobibi_20261111.json.gz")
        with mock.patch.object(backtest, "tokens_with_data", lambda *a, **k: []), \
                mock.patch.object(owner, "labels", lambda *a, **k: [{"token": fx["token"]}]), \
                mock.patch.object(owner, "pin_tokens", lambda *a, **k: []):
            logs = []
            backtest.run_server(now=cs[-1][0] + 60, log=logs.append)
            backtest.run_server(now=cs[-1][0] + 120, log=logs.append)          # the same night: counted once
            backtest.run_server(now=cs[-1][0] + 86400, log=logs.append)
        con = data.connect()
        sb, fb, nights = (data.kv_get(con, k) for k in ("stop_backtest", "flip_backtest", "stop_backtest_nights"))
        con.close()
        self.assertEqual(len(nights), 2)
        self.assertEqual(gate.stop_nights(), nights)
        self.assertEqual(sb["a"]["rounds"], 3)                               # the stop comparison keeps the label's token
        self.assertEqual(sb["nights"], 2)
        self.assertEqual((fb["tokens"], fb["old"]["rounds"], fb["new"]["rounds"]), (0, 0, 0))   # the gate's numbers not
        self.assertTrue(any(x.startswith("range reclaim (demo, ATR + reclaim): 0 zatvorenih rundi") for x in logs), logs)


class StopLine(Base):
    def test_the_format(self):
        self.assertEqual(rules.stop_line("RNG", self.arng()),
                         "range stop RNG: pravi račun ATR MC $45,000 (range_low_low $51,000, ATR $4,000) · demo "
                         "ATR+reclaim · staro 0,85 $43,400")
        self.assertEqual(rules.stop_line("RNG", self.rng()),
                         "range stop RNG: pravi račun ATR nepoznat, × 0,85 MC $43,400 (range_low_low $51,000) · demo "
                         "ATR+reclaim · staro 0,85 $43,400")
        self.assertIsNone(rules.stop_line("RNG", {"zones": None}))
        v = rview.stop_view(self.arng())
        self.assertEqual((v["market_cap_usd"], v["kind"], v["atr_market_cap_usd"], v["old_x085_market_cap_usd"]),
                         (45_000, "atr", 4_000, 43_350))

    def test_run_range_logs_one_line_per_active_range_only_on_change(self):
        self.mode("paper")
        import run_range
        from tests.test_range_dca_offline import DataAndJob
        pair = DataAndJob.pair(self, MINT, 0, 0, 25_000)

        def gt(pool, start, end):
            return [c[:6] for c in tri(end - 12 * 3600 + 60, hours=12)]

        def fetch(toks):
            last = tri(self.now - 12 * 3600 + 60 - self.now % 60, hours=12)[-1]
            pair.update(priceUsd=str(last[4]), marketCap=last[4] * 1e9)
            return [pair]
        logs = []
        run_range.once(now=self.now, log=logs.append, fetch=fetch, gt_fetch=gt, post=lambda *a: {}, extra=[MINT])
        lines = [x for x in logs if x.startswith("range stop ")]
        self.assertEqual(len(lines), 1, logs)
        self.assertTrue(re.match(r"range stop RNG: pravi račun ATR MC \$[\d,]+ \(range_low_low \$[\d,]+, ATR \$[\d,]+\) "
                                 r"· demo ATR\+reclaim · staro 0,85 \$[\d,]+$", lines[0]), lines[0])
        con = data.connect()
        r, _st = data.load_range(con, MINT)
        con.close()
        self.assertEqual(r["stop_line"], lines[0])
        self.assertEqual((r["stop"]["kind"], r["stop"]["mc"]), ("atr", round(rules.stop_parts(r)["stop_px"] * 1e9)))
        self.assertTrue(r["atr"] > 0)
        logs.clear()

        def again(stored_line=None):   # one more FULL detection on the same data (the 5-minute clock reset)
            c = data.connect()
            if stored_line is not None:
                r0, st0 = data.load_range(c, MINT)
                r0["stop_line"] = stored_line
                data.save_range(c, MINT, r0, st0, "RNG")
            data.kv_put(c, "last_detect", 0)
            c.commit()
            c.close()
            run_range.once(now=self.now, log=logs.append, fetch=fetch, gt_fetch=gt, extra=[MINT])
        again()                                                              # the same levels: no line
        self.assertEqual([x for x in logs if x.startswith("range stop ")], [])
        again("range stop RNG: (an older level)")                            # a level moved: logged again, once
        self.assertEqual([x for x in logs if x.startswith("range stop ")], lines)
        run_range.once(now=self.now + 60, log=logs.append, fetch=fetch, gt_fetch=gt, extra=[MINT])   # no detection
        self.assertEqual([x for x in logs if x.startswith("range stop ")], lines)
        # zonewatch's stop alarm follows the range's stop (the ATR stop), not x 0.85
        from zonewatch import store as zstore
        rows = zstore._range_rows(self.now + 60)
        self.assertEqual(len(rows[0]), 13)
        z = dict((t, lo) for t, lo, _hi in zstore.range_zones(rows[0]))
        self.assertEqual(z["stop"], r["stop"]["mc"])


# ---------- the owner's labels never change a win rate, an EV or a hit rate -----------------------------------------
class LabelsChangeNothing(Base):
    STATIC = ("rangedca/gate.py", "rangedca/rules.py", "rangedca/stops.py", "proposals/calib.py",
              "proposals/strategies.py", "proposals/build.py", "proposals/paper.py", "proposals/publish.py",
              "proposals/report.py", "proposals/outcomes.py", "trade/edge.py", "trade/cost.py", "kol/score.py",
              "kol/tpsl.py", "wallets/rang.py", "fast/sources.py", "fast/decide.py", "momentum/evgate.py",
              "rangedca/tier_compare.py", "rangedca/tier.py")

    def numbers(self):
        from events import evreport
        rows = [r for r in evreport.range_rows(self.now + 10, "paper", self.lg, log=lambda *a: None)
                if r["part"] != "range_oznake"]
        return {"proof": gate.proof(), "missed": gate.by_source(), "reclaim": gate.reclaim_proof(),
                "refusal": gate.refusal(), "missed_refusal": gate.missed_refusal(), "reclaim_refusal": gate.reclaim_refusal(),
                "evreport": [(r["part"], r["n"], r["hit_rate"], r["ev_pct"], r["avg_pnl_pct"]) for r in rows],
                "proposals_paper": paper.proof(self.lg)}

    def test_inserting_a_label_changes_none_of_the_numbers(self):
        trade.ensure(self.lg)
        rs = [(PU, "W1", 0.12, "signal"), (PU, "L1", -0.08, "signal"), (PU, "M1", 0.2, "missed"),
              (PU, owner.HAOBIBI, -0.1694, "signal")]                       # HAOBIBI's booked round: a loss
        for u, t, ret, src in rs:
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, cost_usd, pnl_usd, ret, "
                            "levels, exit_reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (u, t, owner.HAOBIBI_TS, self.now, "closed", 25.0, ret * 25, ret, json.dumps({"src": src}),
                             "stop" if ret < 0 else "top"))
        paper.ensure(self.lg)
        self.lg.execute("INSERT INTO proposal_trades (user, proposal_id, token, strategy, trade_id, opened_ts, status, "
                        "ret) VALUES (?,?,?,?,?,?,?,?)", (PU, 2, owner.HAOBIBI, "range", 1, 1, "closed", -0.011))
        self.lg.commit()
        before = self.numbers()
        self.assertEqual((before["proof"]["n"], before["proof"]["wins"]), (4, 2))
        owner.owner_once(self.con, self.lg, now=self.now)                    # the owner's HAOBIBI label (and pin)
        owner.add_label(self.lg, "W" * 44, self.now, "win", "missed_win_stop_too_early", "range", "X")
        self.assertEqual(len(owner.labels()), 2)
        self.assertEqual(self.numbers(), before)
        # where a label is read at all it is shown, counterfactual, with the booked result as booked
        lb = owner.label_view(owner.labels(token=owner.HAOBIBI)[0])
        self.assertEqual((lb["label"], lb["booked_pnl_usd"]), ("win", round(-0.1694 * 25, 2)))
        # the code that computes win rates / EV / hit rates never reads the labels
        pat = re.compile(r"owner\.(labels|wins|label_view|label_text)\(|owner_labels\b")
        for rel in self.STATIC:
            p = os.path.join(ROOT, rel)
            if not os.path.exists(p):   # tier_compare / tier: other branches
                continue
            with open(p) as f:
                self.assertIsNone(pat.search(f.read()), rel)


# ---------- decision 4: HAOBIBI proposal #2 reconstructed ------------------------------------------------------------
H = owner.HAOBIBI
SUP = 1e9
RLL, RLT, RHL, RHT, RL, ATR = 104_235, 112_000, 172_300, 183_000, 108_100, 10_412   # MC; ATR stop 88,617


def hao_range(px_mc=105_000, atr=ATR, now=NOW):
    """HAOBIBI's range as range.db had it when proposal #2 was made: the bottom zone $104-112k (its range numbers last
    read in the zone: entry-ready), ATR $10.4k, so the stop (range_low_low - 1.5 x ATR) is ~$88.6k."""
    z = {"range_low_low": RLL / SUP, "range_low_top": RLT / SUP, "range_high_low": RHL / SUP, "range_high_top": RHT / SUP,
         "range_high": (RHL + RHT) / 2 / SUP, "range_low": RL / SUP,
         "mc": {"range_low_low": RLL, "range_low_top": RLT, "range_high_low": RHL, "range_high_top": RHT}}
    m = {"ch_5m": 0.01, "buy_share_5m": 0.6, "vol_ratio": 0.8, "supply": SUP, "price": px_mc / SUP, "mcap": px_mc,
         "vol_h1": 30_000, "liq": 40_000}
    return {"ts": now, "mts": now, "active": True, "status": "aktivan", "score": 0.8, "symbol": "HAOBIBI",
            "pos_pct": round((px_mc - RLL) / (RHT - RLL) * 100, 1), "zones": z, "metrics": m, "state": {},
            "components": {}, "atr": atr / SUP}


class Haobibi2(Base):
    def setUp(self):
        super().setUp()
        self.ppath = os.path.join(self.tmp.name, "proposals.db")
        self.penv = mock.patch.dict(os.environ, {"PROPOSALS_DB": self.ppath})
        self.penv.start()
        self.addCleanup(self.penv.stop)
        rug = mock.patch.object(lcopy, "_rugged", lambda *a: None)
        rug.start()
        self.addCleanup(rug.stop)
        paper._LAST.clear()
        pview.clear()
        self.addCleanup(paper._LAST.clear)
        self.addCleanup(pview.clear)

    def built(self, mcap=89_000, atr=ATR):
        Sx = PSources()
        rc = rview.one(H, hao_range(atr=atr), NOW, None, [])
        Sx.rc = [rc]
        Sx.rrec = {"n": 10, "wins": 5}
        Sx.mk[H] = live(mcap=mcap, liq=40_000, price=mcap / SUP)
        rows, near, meta = build.build(NOW, Sx)
        return rc, {r["token"]: r for r in rows}, near

    def test_made_at_89k_under_the_zone_is_not_published_and_its_ev_comes_from_the_zone_middle(self):
        rc, rows, near = self.built()
        self.assertTrue(rc["entry_ready"], rc["entry_now"])                  # range.db's numbers said "in the zone"
        self.assertEqual(rc["stop"]["market_cap_usd"], 88_617)               # ~$88.6k: the ATR stop
        self.assertIn(H, rows, near)
        p = rows[H]
        self.assertEqual(p["strategy"], "range")
        self.assertEqual(p["exits_mcap"]["sl"], 88_617)
        # the artefact: from the market cap now, SL 0.4 % against TP +94 %
        raw = strategies.range_ev(rc, 89_000, {"n": 10, "wins": 5}, NOW)
        self.assertLess(raw["sl"], 0.005)
        self.assertGreater(raw["tp"], 0.9)
        cost = p["cost_pct"] / 100
        old = calib.ev(calib.estimate(5, 10, raw["tp"], raw["sl"], cost)["p"], raw["tp"], raw["sl"], cost)
        # the fix: TP / SL from the middle of the zone ($108,118)
        st = p["strategies"]["range"]
        mid = (RLL + RLT) / 2
        self.assertEqual(st["zone_mid_mcap"], round(mid))
        self.assertAlmostEqual(st["tp_pct"], round((RHL / mid - 1) * 100, 2))
        self.assertAlmostEqual(st["sl_pct"], round((1 - 88_617 / mid) * 100, 2))
        new = calib.ev(calib.estimate(5, 10, RHL / mid - 1, 1 - 88_617 / mid, cost)["p"], RHL / mid - 1,
                       1 - 88_617 / mid, cost)
        self.assertAlmostEqual(p["ev_pct"], round(new * 100, 2))
        self.assertGreater(old, new)                                         # the old EV was inflated
        self.assertEqual(p["ev_from"], "sredina zone ulaza $108k")
        self.assertEqual((p["atr_mc"], p["atr_from"]), (ATR, "ATR raspona (14 × 15 min)"))
        # not published: outside the zone AND 0.4 % above the stop (< 1 x ATR)
        self.assertEqual(p["wait_why"], "MC $89k izvan zone ulaza $104k–$112k; do stopa $89k samo $383 (< 1 × ATR $10k, "
                                        "ATR raspona (14 × 15 min))")
        con = pstore.connect(self.ppath)
        job.sync(con, [p], near, NOW)
        con.commit()
        sp = pstore.active(con)[H]
        con.close()
        self.assertEqual((sp["status"], sp["published_ts"], sp["wait_why"]), ("novo", None, p["wait_why"]))
        self.assertFalse(pstore.published(sp))
        d = pview.load(now=NOW, path=self.ppath)
        self.assertEqual(d["active"], [])                                    # not in "Što kupiti" / the card
        self.assertEqual([x["token"] for x in d["waiting"]], [H])
        self.assertTrue(d["last_pass"]["near"][0]["why"].startswith("čeka zonu: MC $89k izvan zone"))   # prikaži skoro
        with mock.patch.object(pview, "_mode", lambda: "shadow"):
            g = pview.mcp(now=NOW, path=self.ppath)
        row = g["proposals"][0]
        self.assertEqual((row["published"], row["entry_state"]["state"]), (False, "čeka zonu"))
        self.assertIn("< 1 × ATR", row["wait_why"])
        self.assertEqual(row["ev_from"], "sredina zone ulaza $108k")

    def test_the_20_s_loop_publishes_it_when_the_price_is_in_the_zone_with_1_atr_to_the_stop(self):
        _rc, rows, near = self.built()
        con = pstore.connect(self.ppath)
        job.sync(con, [rows[H]], near, NOW)
        con.commit()
        pid = pstore.active(con)[H]["id"]
        con.close()

        def at(mc):
            return lambda toks: {t: (mc / SUP, 40_000.0, None, float(mc)) for t in toks}

        def prop():
            c = pstore.ro(self.ppath)
            try:
                return pstore.one(c, pid)
            finally:
                c.close()
        self.mode("shadow", "proposals")                                     # shadow: publishes, never enters
        self.assertEqual(paper.run_once(self.lg, at(89_000), NOW + 20, path=self.ppath, sol=200.0), [])
        self.assertIn("izvan zone", prop()["wait_why"])
        self.assertEqual(paper.run_once(self.lg, at(100_000), NOW + 40, path=self.ppath, sol=200.0), [])
        self.assertIn("MC $100k izvan zone", prop()["wait_why"])             # under the zone: still waiting
        self.assertEqual(paper.run_once(self.lg, at(108_000), NOW + 60, path=self.ppath, sol=200.0), [])
        p = prop()
        self.assertEqual((p["wait_why"], p["published_ts"], p["published_mcap"]), (None, NOW + 60, 108_000))
        self.assertEqual([x["id"] for x in pview.load(now=NOW + 60, path=self.ppath)["active"]], [pid])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)
        # out of the zone again: waits again (shown = buyable now); back in: shown, and in paper the demo account enters
        paper.run_once(self.lg, at(120_000), NOW + 80, path=self.ppath, sol=200.0)
        self.assertIn("izvan zone", prop()["wait_why"])
        self.assertEqual(prop()["published_ts"], NOW + 60)                   # the first publication is kept
        self.mode("paper", "proposals")
        done = paper.run_once(self.lg, at(106_000), NOW + 100, path=self.ppath, sol=200.0)
        self.assertEqual([u for u, _t in done], [PU])
        self.assertIsNone(prop()["wait_why"])

    def test_inside_the_zone_but_within_1_atr_of_the_stop_waits(self):
        # a wider ATR (the stop clamps at 20 % under range_low_low, $83.4k): at $105k, inside the zone, the stop is
        # $21.6k away: more than 1 ATR of $20k (published), less than 1 ATR of $25k (waits)
        for atr, mc, pub in ((20_000, 105_000, True), (25_000, 105_000, False)):
            _rc, rows, _n = self.built(mcap=mc, atr=atr)
            p = rows[H]
            self.assertEqual(p["wait_why"] is None, pub, p["wait_why"])
            if not pub:
                self.assertIn("< 1 × ATR $25k", p["wait_why"])
        # strategies without an ATR: 5 % of the MC (a momentum row whose stop is 10 % under the entry is published)
        r = {"entry_zone": {"mcap_low": 100_000, "mcap_high": 105_000}, "exits_mcap": {"sl": 94_000}}
        self.assertIsNone(publish.check(r, 100_000))
        self.assertIn("5 % MC-a", publish.check(r, 98_500) or "")           # under the zone too
        self.assertIn("< 1 × ATR $5k, 5 % MC-a", publish.check({"exits_mcap": {"sl": 96_000}, "mcap0": 100_000},
                                                                100_000))

    def test_percent_exits_keep_their_ev_and_an_old_row_reads_as_published(self):
        ev = {"strategy": "momentum", "tp": 0.15, "sl": 0.10, "entry_zone": {"mcap_low": 100_000, "mcap_high": 105_000},
              "levels": {"tp": [{"pct": 15, "share": 0.5}], "sl": {"pct": -10}}}
        m = publish.at_mid(ev)
        self.assertEqual((m["tp"], m["sl"], m["zone_mid"]), (0.15, 0.10, 102_500))
        self.assertTrue(pstore.published({"wait_why": None}))
        self.assertFalse(pstore.published({"wait_why": "MC izvan zone"}))


if __name__ == "__main__":
    unittest.main()
