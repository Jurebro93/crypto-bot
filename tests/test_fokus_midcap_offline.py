"""15.11. navečer (vlasnik: "Ne želim više mikrokapove uopće ... sve resurse prebaci na midcapove 2M-200M, posebno
TRENDING"; "Preskoči Good Guy ... posebno one koji su sada malo PALI; istraži ZAŠTO"): ops/fokus.py, veliki/midcap.py,
veliki/prioritet.py, offline (no network).

  - the owner switch fokus_midcap: an OWNER_SWITCH, on by his order (next to last of OWNER_FLAG_ORDERS; arhiva_mikrokapova came after it), off = old behaviour
  - switch on: the microcap jobs do not run (ops.heavy, run_sched, the runners' gate), the PumpPortal launch / migration
    subscriptions are not sent and only open positions + followed wallets are watched; switch off: as before
  - the KOL minute candles / measure only for midcap-list tokens while on
  - the midcap universe: trending lists merged and deduped by mint, the deepest pool, fake-liquidity copies, curves and
    out-of-range MC refused, GOODGUY skipped; membership grace; one compact snap row a member a pass
  - budgets: GeckoTerminal per pass and per day (sliced by the hour); the collector does nothing with the switch off
  - priority and "zašto je pao": a bad dip is skipped, market-wide / benign dips get the bonus, the order and the
    components stored with the trade

    python3 -m unittest tests.test_fokus_midcap_offline
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import fokus, heavy  # noqa: E402
from trade import settings  # noqa: E402
from veliki import midcap, prioritet, store as vstore, universe  # noqa: E402

NOW = 1_790_000_000 // 3600 * 3600


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "trade.db")
        self.con = settings.connect(self.db)
        self.addCleanup(self.con.close)
        for p in (mock.patch.object(settings, "DB", self.db), mock.patch.dict(os.environ, {}, clear=False)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("FOKUS_MIDCAP_FORCE", None)
        settings._FLAG_CACHE.clear()
        self.addCleanup(settings._FLAG_CACHE.clear)

    def switch(self, on):
        settings.put(self.con, f"flag:{fokus.SWITCH}", {"mode": "live" if on else "off", "since": 1, "who": "Jure"})
        settings._FLAG_CACHE.clear()


class Switch(Base):
    def test_registered_and_ordered_last(self):
        from ui import assistnotes
        self.assertIn(fokus.SWITCH, settings.OWNER_SWITCHES)
        self.assertIn(fokus.SWITCH, settings.FLAGS)
        self.assertIn(fokus.SWITCH, settings.OWNER_SWITCH_NOTES)
        # 15.11. navečer: the archive order (arhiva_mikrokapova, ops/arhiva.py) came after it and is the last now
        mine = tuple(o for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == fokus.SWITCH)
        self.assertEqual([o[:2] for o in mine], [(fokus.SWITCH, "live")])
        self.assertEqual(assistnotes.OWNER_FLAG_ORDERS[-2][:2], (fokus.SWITCH, "live"))
        self.assertFalse(fokus.on())   # never set: off (the old behaviour)
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", mine):
            self.assertEqual(assistnotes.owner_flag_orders(self.con), [f"zastavica {fokus.SWITCH}: off → live"])
            settings._FLAG_CACHE.clear()
            self.assertTrue(fokus.on())
            settings.set_flag(self.con, fokus.SWITCH, "off", "Jure")   # one tap undoes it
            self.assertEqual(assistnotes.owner_flag_orders(self.con), [])   # and it stays off
        settings._FLAG_CACHE.clear()
        self.assertFalse(fokus.on())

    def test_microcap_jobs_off_only_with_switch(self):
        cmds = (["python3", "run_scan.py", "once"], ["python3", "-m", "kol.precall", "incr"],
                [os.path.join(ROOT, "kol", "precall.py"), "night"], ["run_hype.py", "learn", "--auto", "5"],
                ["run_wallets.py", "score"], ["run_learn.py", "masovno"], ["run_range.py", "once"],
                ["run_events.py", "night"], ["run_oscilator.py", "once"], ["run_konsenzus.py", "night"],
                ["kol/backfill_calls.py", "--budget", "60"], ["run_momentum.py", "backtest"], ["-m", "kol.groupdisc", "incr"])
        keep = (["run_veliki.py", "list"], ["run_wallets.py", "dokazani"], ["run_events.py", "tick"],
                ["run_exits.py", "rollback"], ["run_kol.py", "loop"], ["run_critic.py", "trades"],
                ["run_report.py", "loop"], ["-m", "rugfilter.archive"], ["run_dugo.py", "once"], ["run_trade.py", "follow"])
        self.switch(False)
        self.assertTrue(all(fokus.skip_cmd(c) is None for c in cmds + keep))
        self.switch(True)
        for c in cmds:
            self.assertIsNotNone(fokus.skip_cmd(c), c)
        for c in keep:
            self.assertIsNone(fokus.skip_cmd(c), c)

    def test_heavy_and_sched_do_not_start_them(self):
        import run_sched
        self.switch(True)
        with mock.patch.object(heavy, "run") as run, mock.patch.object(heavy, "wait_for_night") as night:
            self.assertEqual(heavy.main(["--night", "run_wallets.py", "harvest", "--feeds"]), 0)
            self.assertEqual(run_sched.run("masovno", ["run_learn.py", "masovno"], light=True), 0)
            run.assert_not_called()
            night.assert_not_called()
        self.switch(False)
        with mock.patch.object(heavy, "run", return_value=types.SimpleNamespace(returncode=0)) as run, \
                mock.patch.object(heavy, "wait_for_night"):
            self.assertEqual(heavy.main(["--night", "run_wallets.py", "harvest"]), 0)
            run.assert_called_once()

    def test_gate_exits(self):
        self.switch(True)
        with self.assertRaises(SystemExit) as e:
            fokus.gate(["run_scan.py", "once"])
        self.assertEqual(e.exception.code, 0)
        fokus.gate(["run_veliki.py", "midcap"])   # not a microcap job: nothing happens

    def test_start_line(self):
        self.switch(True)
        s = fokus.start_line()
        self.assertTrue(s.startswith("fokus midcap: isključeno "))
        self.assertIn("preusmjereno", s)
        self.assertIn("2M–200M", s)
        self.switch(False)
        self.assertIn("ISKLJUČEN", fokus.start_line())


class Live(Base):
    def dbs(self):
        d = self.tmp.name
        hc = sqlite3.connect(os.path.join(d, "hype.db"))
        hc.executescript("CREATE TABLE live_launches (mint TEXT, pool TEXT, ts INTEGER);"
                         "CREATE TABLE hype_signals (token TEXT, ts INTEGER, mcap REAL);")
        hc.execute("INSERT INTO live_launches VALUES ('BONDED', 'migration', ?)", (NOW - 60,))
        hc.execute("INSERT INTO hype_signals VALUES ('MICRO', ?, 80000)", (NOW - 60,))
        hc.commit()
        hc.close()
        kc = sqlite3.connect(os.path.join(d, "kol.db"))
        kc.execute("CREATE TABLE kv (key TEXT, value TEXT)")
        kc.execute("INSERT INTO kv VALUES ('chain_hook', ?)", (json.dumps({"wallets": ["KOLW"]}),))
        kc.commit()
        kc.close()
        lc = sqlite3.connect(os.path.join(d, "league.db"))
        lc.executescript("CREATE TABLE trades (token TEXT, status TEXT, user TEXT);"
                         "CREATE TABLE exit_plans (token TEXT, status TEXT);"
                         "CREATE TABLE follows (target TEXT, kind TEXT, active INTEGER);")
        lc.execute("INSERT INTO trades VALUES ('HELD', 'open', ?)", (settings.LEAGUE_USER,))
        lc.execute("INSERT INTO follows VALUES ('FOLLOWED', 'wallet', 1)")
        lc.commit()
        lc.close()
        return {k: os.path.join(d, f"{k}.db") for k in ("hype", "kol", "league")}

    def test_wanted(self):
        from live import pumpportal
        p = self.dbs()
        kw = dict(now=NOW, paper_db=os.path.join(self.tmp.name, "none1.db"), strat_db=os.path.join(self.tmp.name, "n2.db"),
                  hype_db=p["hype"], kol_db=p["kol"], league_db=p["league"])
        t, w, o = pumpportal.wanted(fokus=False, **kw)
        self.assertEqual(set(t), {"HELD", "BONDED", "MICRO"})
        self.assertEqual(set(w), {"KOLW", "FOLLOWED"})
        t, w, o = pumpportal.wanted(fokus=True, **kw)
        self.assertEqual((t, w, o), (["HELD"], ["FOLLOWED"], {"HELD"}))

    def _subs(self, on):
        from live import pumpportal
        self.switch(on)
        sent = []

        class WS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def send(self, m):
                sent.append(json.loads(m))

            async def recv(self):
                await asyncio.sleep(0)
                return "{}"
        stops = iter([False, True, True, True])
        fake = types.SimpleNamespace(connect=lambda *a, **k: WS())
        with mock.patch.dict(sys.modules, {"websockets": fake}), \
                mock.patch.object(pumpportal, "wanted", lambda fokus=None, **k: (["HELD"], ["FOLLOWED"], {"HELD"})):
            con = sqlite3.connect(":memory:")
            from live import store as lstore
            lstore.ensure(con) if hasattr(lstore, "ensure") else None
            with mock.patch.object(lstore, "set_state", lambda *a, **k: None):
                asyncio.run(pumpportal.run(con, log=lambda s: None, new_tokens=True, migrations=True,
                                           stop=lambda: next(stops)))
        return [m.get("method") for m in sent]

    def test_launch_subscription(self):
        on = self._subs(True)
        self.assertNotIn("subscribeNewToken", on)
        self.assertNotIn("subscribeMigration", on)
        off = self._subs(False)
        self.assertIn("subscribeNewToken", off)
        self.assertIn("subscribeMigration", off)


class KolRetarget(Base):
    def test_minute_candidates(self):
        from kol import minute
        rows = [("t1", "MID", "h", NOW, 1), ("t2", "MICRO", "h", NOW, 1)]
        with mock.patch.object(minute, "_candidates", lambda k, c, n: rows):
            self.switch(False)
            self.assertEqual(minute.candidates(None, {}, NOW), rows)
            self.switch(True)
            with mock.patch.object(fokus, "midcap_mints", lambda max_age_s=60: frozenset({"MID"})):
                self.assertEqual(minute.candidates(None, {}, NOW), rows[:1])

    def test_measure_due(self):
        from kol import measure, store as kstore
        con = sqlite3.connect(":memory:")
        con.executescript(kstore.SCHEMA if hasattr(kstore, "SCHEMA") else "")
        cols = {r[1] for r in con.execute("PRAGMA table_info(calls)")}
        if "mtry" not in cols:
            con.execute("ALTER TABLE calls ADD COLUMN mtry INTEGER")
        for tid, tok in (("1", "MID"), ("2", "MICRO")):
            con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, complete) VALUES (?,?,?,?,?,0)",
                        (tid, tok, "kol", NOW - 7200, "call"))
        self.switch(False)
        self.assertEqual(set(measure.due(con, NOW, 10)), {"MID", "MICRO"})
        self.switch(True)
        with mock.patch.object(fokus, "midcap_mints", lambda max_age_s=60: frozenset({"MID"})):
            self.assertEqual(measure.due(con, NOW, 10), ["MID"])


def pair(mint, sym, liq, mcap, dex="raydium", vol=1e6, pool=None, px=1.0, created=NOW - 40 * 86400):
    return {"chainId": "solana", "baseToken": {"address": mint, "symbol": sym, "name": sym}, "dexId": dex,
            "pairAddress": pool or f"P{mint}{int(liq)}", "liquidity": {"usd": liq}, "marketCap": mcap, "fdv": mcap,
            "volume": {"m5": 1000, "h1": 20000, "h6": 100000, "h24": vol}, "priceUsd": str(px),
            "txns": {"m5": {"buys": 5, "sells": 4}, "h1": {"buys": 50, "sells": 40}, "h24": {"buys": 900, "sells": 800}},
            "priceChange": {"m5": 0.1, "h1": -1.0, "h6": -2.0, "h24": -8.0}, "pairCreatedAt": created * 1000}


class Universe(Base):
    def setUp(self):
        super().setUp()
        self.mdb = os.path.join(self.tmp.name, "midcap.db")
        p = mock.patch.dict(os.environ, {"MIDCAP_DB": self.mdb, "VELIKI_DB": os.path.join(self.tmp.name, "v.db")})
        p.start()
        self.addCleanup(p.stop)
        midcap._MEM["ts"] = 0.0
        self.pairs = [pair("A", "AAA", 400_000, 30e6), pair("A", "AAA", 90_000, 30e6, dex="meteora"),   # two pools
                      pair("FAKE", "AAA", 50e6, 60e6, vol=10),                                      # a fake copy
                      pair("TINY", "TINY", 60_000, 900_000),                                         # under 2M
                      pair("BIG", "BIG", 5e6, 900e6),                                                # over 200M
                      pair("CURVE", "CRV", 80_000, 3e6, dex="pumpfun"),                              # a curve
                      pair("GG", "GOODGUY", 800_000, 20e6),                                          # skipped
                      pair("B", "BBB", 150_000, 3e6, vol=5e6)]                                       # data only
        self.fetch = {"dex_tokens": lambda mints: [p for p in self.pairs if p["baseToken"]["address"] in mints],
                      "discover": lambda: {m: {"dex_boost_top": i + 1} for i, m in
                                           enumerate(["A", "FAKE", "TINY", "BIG", "CURVE", "GG", "B"])}}

    def test_snapshot_merge_dedupe(self):
        c = midcap.config()
        with mock.patch.dict(midcap.FETCH, self.fetch, clear=True), \
                mock.patch.object(midcap, "_archived", lambda: frozenset()):
            con = midcap.connect(self.mdb)
            r = midcap.snapshot(con, c, NOW, midcap.FETCH["discover"](), log=lambda s: None)
            self.assertEqual(r["members"], 2)
            mem = {x["mint"]: x for x in midcap.members(self.mdb)}
            self.assertEqual(set(mem), {"A", "B"})
            self.assertEqual(mem["A"]["pool"], "PA400000")   # the deepest pool
            self.assertEqual(mem["A"]["trend"], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM snap").fetchone()[0], 2)
            row = con.execute("SELECT * FROM snap WHERE id=(SELECT id FROM tokens WHERE mint='A')").fetchone()
            self.assertEqual(row[1], NOW)
            self.assertEqual(row[8], 2_000_000)   # 24 h volume summed over both pools
            self.assertEqual(row[13:15], (900, 800))
            # B falls under 2M: still measured inside the grace, out after leave_after_h
            self.pairs[-1] = pair("B", "BBB", 150_000, 1.5e6)
            midcap.snapshot(con, c, NOW + 90, None, log=lambda s: None)
            self.assertIn("B", {x["mint"] for x in midcap.members(self.mdb)})
            midcap.snapshot(con, c, NOW + 25 * 3600, None, log=lambda s: None)
            self.assertNotIn("B", {x["mint"] for x in midcap.members(self.mdb)})
            con.close()

    def test_data_judge_and_trade_range(self):
        g = universe.group([pair("B", "BBB", 150_000, 3e6)])["B"]
        self.assertIsNone(universe.data_judge(g, curve_dex=("pumpfun",)))
        self.assertIsNotNone(universe.judge(g, NOW, curve_dex=("pumpfun",)))   # 3M: data yes, trading list no
        self.assertEqual((universe.DATA_MIN_MCAP, universe.DATA_MAX_MCAP), (2e6, 2e8))
        self.assertEqual(universe.MIN_MCAP, 5e6)   # the trading floor stays the capgate's
        self.assertNotIn("GOODGUY", universe.SEEDS)

    def test_build_merges_trending(self):
        fetch = {"dex_search": lambda q: [], "gt_pools": lambda pages: {}, "jup": lambda: {},
                 "dex_trending": lambda: {"A": {"dex_boost_top": 1}}, "gt_trending": lambda pages: {"A": {"gt_trend": 3}},
                 "dex_tokens": lambda mints: [p for p in self.pairs if p["baseToken"]["address"] in mints]}
        with mock.patch.dict(vstore.FETCH, fetch, clear=True), mock.patch.object(universe, "_dugo_candidates", dict):
            rows, meta = universe.build(NOW, log=lambda s: None)
        self.assertEqual([r["mint"] for r in rows], ["A"])
        self.assertEqual(rows[0]["pool"], "PA400000")
        self.assertGreaterEqual(meta["trending_new"], 1)

    def test_switch_off_collector_does_nothing(self):
        self.switch(False)
        self.assertEqual(midcap.run_pass(NOW, log=lambda s: None), {})
        self.assertFalse(os.path.exists(self.mdb))

    def test_full_pass_and_budget(self):
        self.switch(True)
        filled = []

        def fill(con, m, pool, now, budget, tables):
            filled.append((m, tables[0]))
            return 1
        lines = []
        with mock.patch.dict(midcap.FETCH, dict(self.fetch, rugcheck=lambda m: None), clear=True), \
                mock.patch.object(midcap, "_archived", lambda: frozenset()), \
                mock.patch.object(vstore, "fill", fill), mock.patch.object(midcap, "xmom_pass", lambda *a, **k: 0.0), \
                mock.patch.object(midcap, "config", lambda path=None: dict(midcap.DEFAULTS, **{
                    "min_mcap": 2e6, "max_mcap": 2e8, "min_liq": 25_000, "max_tokens": 600, "gt_pass": 3,
                    "gt_day": 48})):
            day0 = NOW // 86400 * 86400
            t = day0 + 23 * 3600 + 5
            out = midcap.run_pass(t, log=lines.append)
            self.assertEqual(out["gt"], 3)   # gt_pass
            self.assertEqual(len(filled), 3)
            self.assertTrue(any(s.startswith("midcap: sat: 2 midcap tokena") for s in lines), lines)
            con = midcap.connect(self.mdb)
            midcap.kv_put(con, f"gt:{midcap._day(t)}", 47)
            con.commit()
            # the day cap: 48 a day, 47 used -> one more
            self.assertEqual(midcap.gt_left(con, midcap.config(), t), 1)
            self.assertEqual(midcap.gt_left(con, midcap.config(), day0 + 60), 0)   # hour 0: a slice of 2, 47 used
            con.close()


class Priority(unittest.TestCase):
    def test_classify(self):
        bad = prioritet.classify({"c24": -12, "liq_ratio": 0.5})
        self.assertEqual(bad[0], "los")
        self.assertEqual(prioritet.classify({"c24": -12, "safety": {"danger": ["Freeze"]}})[0], "los")
        self.assertEqual(prioritet.classify({"c24": -9, "sells_buys": 2.0})[0], "los")
        self.assertEqual(prioritet.classify({"c24": -9, "grok_dip": {"verdict": "preskoči", "confidence": 0.8}})[0],
                         "los")
        self.assertEqual(prioritet.classify({"c24": -9, "btc24": -4.0})[0], "trzisni")
        self.assertEqual(prioritet.classify({"c24": -9, "market_med": -6.0})[0], "trzisni")
        self.assertEqual(prioritet.classify({"c24": -9, "c7d": 40, "vol_ratio": 0.9})[0], "benigni")
        self.assertEqual(prioritet.classify({"c24": -9})[0], "nejasno")

    def test_score_order_meta(self):
        hot = {"trend": 1, "vol24": 5e6, "v1h": 4e5, "c24": -10, "vol_ratio": 0.9, "x": {"x_momentum_score": 1.0,
                                                                                       "authors15": 6},
               "grok": {"verdict": "kupi", "confidence": 0.8}, "dip": {"kind": "trzisni"}}
        s_hot, p = prioritet.score(hot)
        self.assertGreater(p["dip"], 0)
        s_bad, pb = prioritet.score(dict(hot, dip={"kind": "los"}))
        self.assertLess(s_bad, s_hot)
        s_cold, _ = prioritet.score({"vol24": 2e5})
        prio = {"H": {"mint": "H", "score": s_hot, "parts": p, "dip": hot["dip"], "facts": {}},
                "C": {"mint": "C", "score": s_cold, "parts": {}, "dip": None, "facts": {}}}
        self.assertEqual(prioritet.order(["X", "C", "H"], prio), ["H", "C", "X"])
        pj, dj = prioritet.meta("H", prio)
        self.assertEqual(json.loads(pj)["score"], s_hot)
        self.assertEqual(json.loads(dj)["kind"], "trzisni")
        self.assertEqual(prioritet.meta("X", prio), (None, None))
        self.assertIn("veliki prioritet: ", prioritet.line({"rows": [dict(prio["H"], symbol="HOT")]}))


if __name__ == "__main__":
    unittest.main()
