"""Preskočeni signali (kol/preskoceni.py + the box in ui/pravitrade.py, 10.11., Jure: "piše da je 12 redova
preskočeno; zanima me zašto i jesu li ipak dosegli 15 %"): every skipped buy of the Autopilot measured like a call
(entry = close of the minute of the skip, +15 % before -20 % within 60 min), one row per (token, minute), the pool
from kol.db first, then DexScreener, retries, the minute loop running it after its own pass without ever waiting on
a busy GeckoTerminal, and the box under the log's one-line summary (sentence, rows, owner vs invited viewer, empty
states). No network, databases in a temp dir.

    python3 -m unittest tests.test_preskoceni_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import minute, preskoceni, store as kstore  # noqa: E402
from league import copy, store  # noqa: E402
from trade import aplog, executor, settings  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "kol", "config.json")) as _f:
    CFG = json.load(_f)
NOW = int(time.time()) // 60 * 60
H = 3600
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():   # a follow wakes the copy loop: never the repo's own .copy_wake
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


def candles(m0, moves=None, before=10, after=70, price=1.0):
    """1-minute candles around the skip minute m0: flat at `price` unless moves[k] = (open, high, low, close) for the
    k-th minute after m0 (k=0 is the skip's own minute, whose close is the entry)."""
    out = []
    for k in range(-before, after):
        o, h, l, c = (moves or {}).get(k, (price, price, price, price))
        out.append((m0 + k * 60, o, h, l, c, 100.0))
    return out


def skip(token, ts, kind="preskocio", side="buy", why="signal star 4 min", short="signal star", source="KOL ansem",
         symbol=None):
    return {"ts": ts, "kind": kind, "token": token, "symbol": symbol or token[:6], "source": source, "why": why,
            "why_short": short, "mode": "dry", "stage": "pravi", "trebao": kind == "nije_proslo", "side": side,
            "id": f"x{token}{ts}"}


ROW = {"entry": 1.0, "t15": None, "sl_min": None, "hi60": 0.09, "lo60": -0.14, "r60": -0.08, "lv": "{}", "bad": None}


class Verdict(unittest.TestCase):
    TS = NOW - 3 * H

    def v(self, **kw):
        return preskoceni.verdict({**ROW, **kw}, self.TS, NOW)

    def test_target_first_is_a_miss_with_the_minute_and_the_high(self):
        v = self.v(t15=6, sl_min=31, hi60=0.42)
        self.assertEqual((v["kind"], v["word"]), ("miss", "propušteno"))
        self.assertEqual(v["detail"], "+15 % za 6 min · najviše +42 %")

    def test_stop_first_or_same_minute_was_a_good_skip(self):
        v = self.v(t15=40, sl_min=3, hi60=0.2, lo60=-0.31, r60=0.05)
        self.assertEqual((v["kind"], v["word"]), ("ok", "dobro preskočen"))
        self.assertEqual(v["detail"], "−20 % za 3 min · nakon 1 h +5 % · najniže −31 %")
        self.assertEqual(self.v(t15=5, sl_min=5)["kind"], "ok")   # the same minute: not a clean hit (kol/minute)

    def test_neither_within_the_hour_shows_the_result_and_the_low(self):
        v = self.v()
        self.assertEqual(v["kind"], "ok")
        self.assertEqual(v["detail"], "najviše +9 % · nakon 1 h −8 % · najniže −14 %")
        self.assertEqual(self.v(hi60=None, lo60=None, r60=None)["detail"], "sat vremena bez trgovanja")

    def test_young_and_not_measured_yet(self):
        v = preskoceni.verdict(None, NOW - 20 * 60, NOW)
        self.assertEqual((v["kind"], v["word"]), ("wait", "mjeri se"))
        self.assertEqual(v["detail"], "rezultat oko " + preskoceni.hm(NOW - 20 * 60 + preskoceni.WAIT_S, NOW))
        self.assertEqual(preskoceni.verdict(ROW, NOW - 20 * 60, NOW)["kind"], "wait")   # never judged before its hour
        self.assertEqual(preskoceni.verdict(None, self.TS, NOW)["detail"], "čeka mjerenje")
        self.assertEqual(preskoceni.verdict({"bad": "greska"}, self.TS, NOW)["kind"], "wait")   # retried in an hour

    def test_no_candles_or_no_pool(self):
        self.assertEqual(preskoceni.verdict({"bad": "svijeca"}, self.TS, NOW),
                         {"kind": "none", "word": "nema podataka", "detail": "nema svijeća za taj sat"})
        self.assertEqual(preskoceni.verdict({"bad": "pool"}, self.TS, NOW)["detail"], "pool nije pronađen")

    def test_other_target_from_the_stored_levels(self):
        r = {**ROW, "t15": 6, "lv": json.dumps({"u": {"5": 2, "10": 4, "15": 6}, "d": {"10": 9}})}
        self.assertTrue(preskoceni.hit(r, 15, 20))
        self.assertFalse(preskoceni.hit(r, 20, 20))     # +20 % never came
        self.assertTrue(preskoceni.hit(r, 10, 20))
        self.assertIsNone(preskoceni.hit(r, 17, 20))    # a level that is not stored: nothing claimed
        self.assertIsNone(preskoceni.hit({"bad": "pool"}, 15, 20))

    def test_sentence(self):
        k = lambda kind, n: [{"kind": kind}] * n   # noqa: E731
        self.assertEqual(preskoceni.sentence(k("miss", 3) + k("ok", 7) + k("wait", 2), []),
                         "Od 12 preskočenih: 3 bi dosegla +15 % prije −20 %, 7 nisu, 2 se još mjere.")
        self.assertEqual(preskoceni.sentence(k("ok", 2) + k("none", 1), k("miss", 1)),
                         "Od 3 preskočena: nijedan nije dosegao +15 % prije −20 % (izmjereno 2), 1 bez podataka. "
                         "Još 1 nije prošao tehnički: 1 bi dosegao +15 % prije −20 %.")
        self.assertEqual(preskoceni.sentence(k("miss", 1) + k("ok", 1) + k("wait", 1), []),
                         "Od 3 preskočena: 1 bi dosegao +15 % prije −20 %, 1 nije, 1 se još mjeri.")
        self.assertEqual(preskoceni.sentence([], k("wait", 2)), "2 nisu prošla tehnički: 2 se još mjere.")
        self.assertEqual(preskoceni.sentence([], []), "")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.kp, self.mp = os.path.join(d, "kol.db"), os.path.join(d, "minute.db")
        self.kc = kstore.connect(self.kp)
        self.mc = minute.connect(self.mp)
        preskoceni.ensure(self.mc)   # the minute loop's connection (kol/preskoceni.run ensures it there)
        self._env = mock.patch.dict(os.environ, {"MINUTE_DB": self.mp})
        self._env.start()
        preskoceni._LAST["ts"] = 0.0
        self.fetched = []

    def tearDown(self):
        self._env.stop()
        self.kc.close()
        self.mc.close()
        self.tmp.cleanup()

    def fetch(self, data):
        def f(pool, start, end):
            self.fetched.append((pool, start, end))
            v = data.get(pool, [])
            if isinstance(v, Exception):
                raise v
            return v
        return f

    def rows(self):
        return {(r[0], r[1]): r for r in self.mc.execute("SELECT token, ts, pool, entry, t15, sl_min, hi60, max_min, bad, "
                                                         "retry_ts FROM skip_path ORDER BY ts DESC")}


class Measure(Base):
    def test_path_from_the_decision_minute_and_one_row_per_token_and_minute(self):
        self.kc.execute("INSERT INTO tokens (token, pair) VALUES ('TOK', 'POOL1')")
        self.kc.commit()
        t1 = NOW - 3 * H + 20             # 20 s into its minute
        m1 = t1 - t1 % 60
        t2 = NOW - 2 * H + 5
        m2 = t2 - t2 % 60
        moves = {0: (1.0, 1.0, 1.0, 1.1),                 # entry: the close of the skip's own minute
                 6: (1.1, 1.3, 1.1, 1.2), 20: (1.2, 1.2, 0.8, 0.85),
                 (m2 - m1) // 60: (0.9, 0.9, 0.9, 1.0), (m2 - m1) // 60 + 4: (1.0, 1.0, 0.7, 0.75)}
        data = {"POOL1": candles(m1, moves, after=(m2 - m1) // 60 + 70)}
        entries = [skip("TOK", t2), skip("TOK", t1 + 30, kind="nije_proslo"), skip("TOK", t1),   # same minute twice
                   skip("TOK", NOW - 30 * 60)]                                                # too young
        n_req, n_rows, left = preskoceni.run(self.mc, self.kc, CFG, NOW, fetch=self.fetch(data), entries=entries)
        self.assertEqual((n_req, n_rows, left), (1, 2, 0))                 # one request covers both minutes
        self.assertEqual(self.fetched[0][1:], (m1 - 600, m2 + preskoceni.WAIT_S))
        r = self.rows()
        self.assertEqual(set(r), {("TOK", m1), ("TOK", m2)})
        self.assertAlmostEqual(r[("TOK", m1)][3], 1.1)                      # entry
        self.assertEqual(r[("TOK", m1)][4], 6)                              # +15 % (1.265) at minute 6: 1.3
        self.assertEqual(r[("TOK", m1)][7], 6)                              # the high of the hour was there too
        self.assertEqual(r[("TOK", m1)][5], 20)                             # 0.8 is -27 % of 1.1: the stop, after it
        self.assertIsNone(r[("TOK", m2)][4])
        self.assertEqual(r[("TOK", m2)][5], 4)                              # the second skip stopped at minute 4
        v = preskoceni.verdict(preskoceni.lookup(self.mc, [("TOK", m1)])[("TOK", m1)], t1, NOW)
        self.assertEqual(v["kind"], "miss")
        # measured once: the next pass asks for nothing
        self.assertEqual(preskoceni.run(self.mc, self.kc, CFG, NOW + 60, fetch=self.fetch(data), entries=entries)[:2], (0, 0))
        self.assertEqual(len(self.fetched), 1)

    def test_stop_row_is_written_from_the_low(self):
        self.kc.execute("INSERT INTO tokens (token, pair) VALUES ('T2', 'P2')")
        self.kc.commit()
        t = NOW - 3 * H
        preskoceni.run(self.mc, self.kc, CFG, NOW, entries=[skip("T2", t)],
                       fetch=self.fetch({"P2": candles(t, {3: (1.0, 1.0, 0.75, 0.8), 40: (0.8, 1.4, 0.8, 1.3)})}))
        r = preskoceni.lookup(self.mc, [("T2", t)])[("T2", t)]
        self.assertEqual((r["sl_min"], r["t15"]), (3, 40))
        self.assertEqual(preskoceni.verdict(r, t, NOW)["kind"], "ok")

    def test_pool_order_kol_then_earlier_then_dexscreener_deepest(self):
        self.kc.execute("INSERT INTO tokens (token, pair) VALUES ('KOLT', 'KOLPOOL')")
        self.kc.execute("INSERT INTO tokens (token, pair) VALUES ('NOPAIR', NULL)")
        self.kc.commit()
        asked = []

        def dex(toks):
            asked.append(sorted(toks))
            return [{"chainId": "solana", "baseToken": {"address": "NOPAIR"}, "pairAddress": "SHALLOW", "liquidity": {"usd": 900}},
                    {"chainId": "solana", "baseToken": {"address": "NOPAIR"}, "pairAddress": "DEEP", "liquidity": {"usd": 52000}},
                    {"chainId": "base", "baseToken": {"address": "NOPAIR"}, "pairAddress": "OTHERCHAIN", "liquidity": {"usd": 9e6}},
                    {"chainId": "solana", "baseToken": {"address": "SOMEONE"}, "pairAddress": "X", "liquidity": {"usd": 1e6}}]
        got, failed = preskoceni.pools(self.kc, self.mc, ["KOLT", "NOPAIR", "GHOST"], dex)
        self.assertEqual(got, {"KOLT": "KOLPOOL", "NOPAIR": "DEEP"})
        self.assertFalse(failed)
        self.assertEqual(asked, [["GHOST", "NOPAIR"]])                    # kol.db's token never goes to DexScreener
        self.mc.execute("INSERT INTO skip_path (token, ts, pool, bad, retry_ts, done_ts) VALUES ('GHOST', 1, 'OLD', 'svijeca', 0, 0)")
        got, _ = preskoceni.pools(self.kc, self.mc, ["GHOST"], lambda t: self.fail("DexScreener asked again"))
        self.assertEqual(got, {"GHOST": "OLD"})                           # the pool an earlier try found

    def test_no_pool_waits_a_day_dexscreener_down_an_hour(self):
        t = NOW - 3 * H
        preskoceni.run(self.mc, self.kc, CFG, NOW, entries=[skip("GHOST", t)], fetch=self.fetch({}), pairs_fn=lambda t: [])
        r = self.rows()[("GHOST", t)]
        self.assertEqual((r[8], r[9]), ("pool", NOW + preskoceni.RETRY_EMPTY_S))
        self.assertEqual(self.fetched, [])
        self.assertEqual(preskoceni.verdict(preskoceni.lookup(self.mc, [("GHOST", t)])[("GHOST", t)], t, NOW)["word"],
                         "nema podataka")

        def down(toks):
            raise OSError("DexScreener ne odgovara")
        t2 = NOW - 2 * H
        preskoceni.run(self.mc, self.kc, CFG, NOW, entries=[skip("DOWN", t2)], fetch=self.fetch({}), pairs_fn=down,
                       log=lambda *a, **k: None)
        r = self.rows()[("DOWN", t2)]
        self.assertEqual((r[8], r[9]), ("greska", NOW + preskoceni.RETRY_ERR_S))   # "mjeri se", not "nema podataka"

    def test_empty_answer_retries_after_a_day_errors_after_an_hour(self):
        self.kc.executemany("INSERT INTO tokens (token, pair) VALUES (?, ?)", [("E", "PE"), ("F", "PF"), ("G", "PG")])
        self.kc.commit()
        t = NOW - 3 * H
        err403 = OSError("HTTP Error 403")
        err404 = OSError("HTTP Error 404")
        err404.code = 404
        data = {"PE": [], "PF": err403, "PG": err404}
        preskoceni.run(self.mc, self.kc, CFG, NOW, entries=[skip(x, t) for x in "EFG"], fetch=self.fetch(data),
                       log=lambda *a, **k: None)
        r = self.rows()
        self.assertEqual((r[("E", t)][8], r[("E", t)][9]), ("svijeca", NOW + 86400))
        self.assertEqual((r[("F", t)][8], r[("F", t)][9]), ("greska", NOW + 3600))
        self.assertEqual(r[("G", t)][8], "pool")
        self.fetched.clear()
        preskoceni.run(self.mc, self.kc, CFG, NOW + 600, entries=[skip(x, t) for x in "EFG"], fetch=self.fetch(data))
        self.assertEqual(self.fetched, [])                                   # nothing is due yet
        data["PF"] = candles(t, {5: (1.0, 1.2, 1.0, 1.1)})
        preskoceni.run(self.mc, self.kc, CFG, NOW + 3601, entries=[skip(x, t) for x in "EFG"], fetch=self.fetch(data))
        self.assertEqual([f[0] for f in self.fetched], ["PF"])               # the network error, an hour later
        self.assertIsNone(self.rows()[("F", t)][8])
        self.assertEqual(self.rows()[("F", t)][4], 5)

    def test_busy_host_stops_the_pass_and_writes_nothing(self):
        self.kc.execute("INSERT INTO tokens (token, pair) VALUES ('B', 'PB')")
        self.kc.commit()
        t = NOW - 3 * H
        res = preskoceni.run(self.mc, self.kc, CFG, NOW, entries=[skip("B", t)], fetch=lambda p, s, e: None)
        self.assertEqual(res[:2], (0, 0))
        self.assertEqual(self.rows(), {})                                    # tried again on the next pass
        # the real fetch: a cooling host (after a 429, or held by another job) is not even read from trade.db
        from event_calendar import http
        with mock.patch.object(http, "cooling", lambda url: 30.0), \
                mock.patch.object(preskoceni, "decisions", side_effect=AssertionError("read while the host cools")), \
                mock.patch.object(minute, "minutes", side_effect=AssertionError("asked a busy host")):
            self.assertEqual(preskoceni.run(self.mc, self.kc, CFG, NOW), (0, 0, None))

    def test_at_most_per_run_and_fewer_while_calls_wait(self):
        self.kc.executemany("INSERT INTO tokens (token, pair) VALUES (?, ?)", [(f"T{i}", f"P{i}") for i in range(30)])
        self.kc.commit()
        entries = [skip(f"T{i}", NOW - 2 * H - i * 60) for i in range(30)]
        data = {f"P{i}": candles(NOW - 2 * H - i * 60) for i in range(30)}
        self.assertEqual(preskoceni.run(self.mc, self.kc, CFG, NOW, fetch=self.fetch(data), entries=entries, busy=True),
                         (5, 5, 0))
        self.assertEqual(preskoceni.run(self.mc, self.kc, CFG, NOW, fetch=self.fetch(data), entries=entries)[:2], (20, 20))
        self.assertEqual([f[0] for f in self.fetched[:5]], ["P0", "P1", "P2", "P3", "P4"])   # newest first

    def test_old_sell_side_and_tokenless_rows_are_not_measured(self):
        entries = [skip("OLD", NOW - 50 * H), skip("SELL", NOW - 3 * H, kind="nije_proslo", side="sell"),
                   {**skip("X", NOW - 3 * H), "token": None}, skip("KUP", NOW - 3 * H, kind="kupio")]
        self.assertEqual(preskoceni.due(self.mc, preskoceni.skipped(entries), NOW, 20), {})


class Pipeline(Base):
    """The real decision log (trade.aplog over trade.db + league.db, read-only) feeding the measurement and the box."""

    def setUp(self):
        super().setUp()
        d = self.tmp.name
        self._saved = (settings.DB, store.DB, kstore.DB)
        settings.DB, store.DB, kstore.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db"), self.kp
        self.tc = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, 0))
        self.fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "Ansem", 25, 5, "tpsl", "15%", "-20%")
        aplog._DAY.clear()

    def tearDown(self):
        settings.DB, store.DB, kstore.DB = self._saved
        self.tc.close()
        self.lg.close()
        super().tearDown()

    def position(self, token, sym, ts, status, reason, src="copy KOL ansem"):
        pid = self.tc.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in) VALUES "
                              "(?,?,?,?,?,?,?)", (token, sym, ts, "dry", status, reason,
                                                  0.05 if status in ("open", "closed") else None)).lastrowid
        self.tc.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, status, reason) VALUES "
                        "(?,?,?,?,?,?,?,?)", (ts, pid, token, "buy", "dry", 50_000_000,
                                              {"blocked": "blocked", "failed": "failed"}.get(status, "dry"), src))
        self.tc.commit()

    def demo_skip(self, token, sym, ts, note):
        self.lg.execute("INSERT INTO copy_log (follow_id, token, side, ev_ts, ts, symbol, action, note, trade_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (self.fid, token, "buy", ts - 20, ts, sym, "preskočeno", note, None))
        self.lg.commit()

    def seed(self):
        self.kc.executemany("INSERT INTO tokens (token, pair) VALUES (?, ?)",
                            [("CALLED", "PCALL"), ("SKIPA", "PA"), ("SKIPB", "PB"), ("FAIL", "PF")])
        self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('1', 'CALLED', 'ansem', ?, 'call')",
                        (NOW - 3 * H + 20,))
        self.kc.commit()
        self.position("SKIPA", "AAA", NOW - 3 * H, "blocked", "signal star 4 min: kupnja samo dok je poziv svjež (do 180 s)")
        self.position("FAIL", "FFF", NOW - 2 * H, "failed", "transakcija nije stigla u blok (Jupiter, Ultra)")
        self.position("BOUGHT", "BBB", NOW - 4 * H, "open", None)
        self.demo_skip("SKIPB", "SKB", NOW - 5 * H, "MC 21k ispod 30k")
        self.demo_skip("YOUNG", "YNG", NOW - 10 * 60, "praćenje bez dokaza u demu (zatvorenih 3 od 10)")
        return {"PCALL": candles(NOW - 3 * H, {5: (1.0, 1.2, 1.0, 1.1)}, after=80),
                "PA": candles(NOW - 3 * H, {6: (1.0, 1.3, 1.0, 1.2)}),
                "PB": candles(NOW - 5 * H, {3: (1.0, 1.0, 0.7, 0.75)}),
                "PF": candles(NOW - 2 * H, {9: (1.0, 1.5, 1.0, 1.4)})}

    def test_decisions_are_the_logs_buy_side_skips_read_only(self):
        self.seed()
        got = preskoceni.decisions(NOW)
        self.assertEqual([(e["token"], e["kind"]) for e in got],
                         [("YOUNG", "preskocio"), ("FAIL", "nije_proslo"), ("SKIPA", "preskocio"), ("SKIPB", "preskocio")])
        ro = preskoceni._ro(settings.DB)
        try:
            with self.assertRaises(sqlite3.OperationalError):   # the connection it reads through cannot write
                ro.execute("CREATE TABLE x (a)")
        finally:
            ro.close()
        self.assertIsNone(preskoceni._ro(os.path.join(self.tmp.name, "nema.db")))

    def test_minute_loop_measures_calls_first_then_the_skips(self):
        data = self.seed()
        logs = []
        minute.loop(CFG, log=lambda *a, **k: logs.append(a[0]), once=True, fetch=self.fetch(data))
        pools = [f[0] for f in self.fetched]
        self.assertEqual(pools[0], "PCALL")                                   # the call measurement went first
        self.assertEqual(sorted(pools[1:]), ["PA", "PB", "PF"])
        self.assertEqual(self.mc.execute("SELECT COUNT(*) FROM call_path WHERE bad IS NULL").fetchone()[0], 1)
        r = self.rows()
        self.assertEqual({k[0] for k in r}, {"SKIPA", "SKIPB", "FAIL"})       # YOUNG is not an hour old yet
        self.assertTrue(logs[0].startswith("minute: 1 tokena, 1 poziva"))    # the pass's own line stays first
        self.assertTrue(any(x.startswith("preskočeni: 3 zahtjeva za svijeće, 3 odluka") for x in logs))

    def test_minute_loop_with_a_busy_host_and_a_broken_skip_pass(self):
        data = self.seed()
        for p in ("PA", "PB", "PF"):
            data[p] = None                                                   # GeckoTerminal held by another job
        logs = []
        minute.loop(CFG, log=lambda *a, **k: logs.append(a[0]), once=True, fetch=self.fetch(data))
        self.assertEqual(self.rows(), {})
        self.assertEqual(self.mc.execute("SELECT COUNT(*) FROM call_path").fetchone()[0], 1)
        self.assertEqual([f[0] for f in self.fetched], ["PCALL", "PF"])       # stopped at the first None
        self.mc.execute("DELETE FROM call_path")
        self.mc.execute("DELETE FROM call_lv")
        self.mc.commit()
        preskoceni._LAST["ts"] = 0.0
        logs.clear()
        with mock.patch.object(preskoceni, "run", side_effect=sqlite3.OperationalError("database is locked")):
            minute.loop(CFG, log=lambda *a, **k: logs.append(a[0]), once=True, fetch=self.fetch(self.seed_again()))
        self.assertEqual(self.mc.execute("SELECT COUNT(*) FROM call_path").fetchone()[0], 1)
        self.assertTrue(logs[0].startswith("minute: 1 tokena"))
        self.assertIn("preskočeni: OperationalError", " ".join(logs))

    def seed_again(self):
        return {"PCALL": candles(NOW - 3 * H, {5: (1.0, 1.2, 1.0, 1.1)}, after=80)}

    def test_loop_runs_the_skip_pass_at_most_every_every_s(self):
        self.seed()
        calls = []
        with mock.patch.object(preskoceni, "run", lambda *a, **k: calls.append(k.get("busy")) or (0, 0, 0)):
            preskoceni.maybe_run(self.mc, self.kc, CFG, now=1000.0)
            preskoceni.maybe_run(self.mc, self.kc, CFG, now=1060.0)
            preskoceni.maybe_run(self.mc, self.kc, CFG, now=1121.0, busy=True)
        self.assertEqual(calls, [False, True])


class Box(Pipeline):
    """The box at the top of the open log (ui/pravitrade.skip_box via the /pravi-trade/dnevnik fragment)."""

    def setUp(self):
        super().setUp()
        from ui import pravitrade
        self.pt = pravitrade
        self._penv = mock.patch.dict(os.environ, {"TRADE_OWNER": "Jure"})
        self._penv.start()
        settings.put(self.tc, "invited", ["Ivan"])
        self._reset()

    def tearDown(self):
        self._reset()
        self._penv.stop()
        super().tearDown()

    def _reset(self):
        with self.pt._LOCK:
            self.pt._SK.update(ts=0.0, key=None, html=None)
            self.pt._DN.update(ts=0.0, key=None, rows=None)
            self.pt._DN_LINE.update(ts=0.0, key=None, line=None)

    def measured(self):
        data = self.seed()
        preskoceni.run(self.mc, self.kc, CFG, NOW, fetch=self.fetch(data), entries=preskoceni.decisions(NOW))
        self.mc.commit()

    def box(self, owner=True, now=None):
        return self.pt.skip_box(self.tc, self.pt._cfg(self.tc), now or NOW + 30, owner)

    def test_sentence_rows_and_the_same_count_as_the_line(self):
        self.measured()
        html = self.box()
        self.assertIn("Od 3 preskočena: 1 bi dosegao +15 % prije −20 %, 1 nije, 1 se još mjeri. "
                      "Još 1 nije prošao tehnički: 1 bi dosegao +15 % prije −20 %.", html)
        summ = aplog.summary_24h(self.tc, now=NOW + 30)
        self.assertEqual((summ["preskocio"], summ["nije_proslo"]), (3, 1))   # the line's "3 preskočeno · 1 nije prošlo"
        at = [html.index(s) for s in ("YNG", "FFF", "AAA", "SKB")]
        self.assertEqual(at, sorted(at))                                      # newest first
        self.assertIn('class="v miss">propušteno<', html)
        self.assertIn('class="v ok">dobro preskočen<', html)
        self.assertIn('class="v wait">mjeri se<', html)
        self.assertIn("+15 % za 6 min · najviše +30 %", html)
        self.assertIn("−20 % za 3 min", html)
        self.assertIn("nije prošlo (tehnički)", html)
        self.assertEqual(html.count("nije prošlo (tehnički)"), 1)
        self.assertIn('data-pop="/pravi-trade/token?m=SKIPA"', html)          # the token pop-up
        self.assertIn("KOL ansem", html)
        self.assertIn("Propušteni po razlogu: 1 signal star.", html)
        self.assertIn(preskoceni.hm(NOW - 3 * H, NOW + 30), html)            # Zagreb time
        self.assertNotIn("Autopilot sada izlazi", html)                       # the target is the default +15 %
        self.assertNotIn("Trebao je kupiti", html)

    def test_owner_reads_the_reason_viewer_its_short_word(self):
        self.measured()
        own, guest = self.box(True), self.box(False)
        self.assertIn("signal star 4 min: kupnja samo dok je poziv svjež (do 180 s)", own)
        self.assertIn("transakcija nije stigla u blok (Jupiter, Ultra)", own)
        self.assertNotIn("kupnja samo dok je poziv svjež", guest)
        self.assertNotIn("Jupiter, Ultra", guest)
        self.assertIn("signal star", guest)
        self.assertIn("MC ispod 30k", guest)
        frag = self.pt.dnevnik_fragment("Ivan")
        self.assertIn("id=ap-sk", frag)
        self.assertNotIn("kupnja samo dok je poziv svjež", frag)
        self.assertLess(frag.index("id=ap-sk"), frag.index("Svaki redak je jedna odluka"))   # right under the line

    def test_cached_read_only_and_no_network(self):
        self.measured()
        from event_calendar import http
        before = os.path.getmtime(self.mp)
        with mock.patch.object(http, "get_json", side_effect=AssertionError("network in a request")), \
                mock.patch.object(http, "_fetch", side_effect=AssertionError("network in a request")):
            first = self.box(True, NOW + 30)
            with mock.patch.object(self.pt, "_skip_rows", side_effect=AssertionError("read again within 30 s")):
                self.assertEqual(self.box(True, NOW + 50), first)
                self.box(False, NOW + 55)
        self.assertEqual(os.path.getmtime(self.mp), before)

    def test_more_than_fifteen_rows_and_long_reasons(self):
        for i in range(18):
            self.demo_skip(f"MANY{i:02d}", f"M{i:02d}", NOW - 2 * H - i * 120, "likvidnost $4k je samo 0.9% MC-a " * (6 if i == 0 else 1))
        html = self.box()
        self.assertIn("Od 18 preskočenih:", html)
        self.assertIn('<details class=ap-it id=ap-sk-sve><summary><span>Prikaži sve</span><span class=k>još 3</span>', html)
        shown = html.split("id=ap-sk-sve")[0]
        self.assertEqual(shown.count("class=ap-skr"), 15)
        self.assertIn("…</small>", html)                                     # the long one is cut on a word ...
        self.assertIn('title="likvidnost $4k je samo 0.9% MC-a likvidnost', html)   # ... whole in its title

    def test_empty_states(self):
        self.assertEqual(self.box(), "")                                      # no decision at all
        self._reset()
        self.position("BOUGHT", "BBB", NOW - 4 * H, "open", None)
        self.assertIn("U zadnja 24 h nijedan signal nije preskočen.", self.box())
        self._reset()
        self.demo_skip("SKIPB", "SKB", NOW - 5 * H, "MC 21k ispod 30k")
        os.remove(self.mp)                                                    # minute.db not there yet
        html = self.box()
        self.assertIn("Od 1 preskočenog: 1 se još mjeri.", html)
        self.assertIn("čeka mjerenje", html)
        self.assertIn("Mjerenje još nije pokrenuto.", html)
        self._reset()
        with mock.patch.object(self.pt, "_aplog_mod", lambda: None):
            self.assertEqual(self.box(), "")                                  # without the log module: nothing
        self._reset()
        frag = self.pt.dnevnik_fragment("Jure")                               # the fragment renders with all of it
        self.assertIn("Od 1 preskočenog", frag)
        self.assertIn("@media(max-width:700px){.ap-skr{grid-template-areas", self.pt.CSS)   # the phone layout

    def test_configured_target_is_mentioned_only_when_it_differs(self):
        self.measured()
        settings.put(self.tc, "tp_default", 20, "Jure")
        html = self.box()
        self.assertIn("Od 3 preskočena: 1 bi dosegao +15 % prije −20 %", html)   # still the +15 % he asked for
        self.assertIn("Autopilot sada izlazi na +20 %: 2 od 3 izmjerenih bi ga dosegla prije −20 %.", html)


if __name__ == "__main__":
    unittest.main()
