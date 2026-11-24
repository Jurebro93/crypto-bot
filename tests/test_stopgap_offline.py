"""16.11. (vlasnik, jutarnji izvještaj: "demo pozicija zatvorena na -59,4 % dok je SL bio oko -20 %"): trade/stopgap -
every closed position's PLANNED stop against its ACTUAL exit (gap in percentage points) and why (rug, a liquidity drop,
a stale quote, a gap through the stop); the worst gaps for the report (stopgap.worst). veliki/live: a pool whose
liquidity falls 50 %+ from the last hour's high exits before the stop is gapped (demo and real rows). No network.

    python3 -m unittest tests.test_stopgap_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import auto, store  # noqa: E402
from tests.test_pravi_novac_sve_offline import PU, tok  # noqa: E402
from tests.test_veliki_dca_offline import Live as VelikiLive  # noqa: E402
from trade import executor, stopgap  # noqa: E402
from veliki import live, rule  # noqa: E402

URL = "https://dexscreener.com/solana/raydium"


class Classify(unittest.TestCase):
    def test_pcts_and_why(self):
        plan, ex, gap = stopgap.pcts(1.0, 0.8, 0.406)
        self.assertAlmostEqual(plan, -20.0)
        self.assertAlmostEqual(ex, -59.4)
        self.assertAlmostEqual(gap, -39.4)
        self.assertEqual(stopgap.classify(gap), "gap")
        self.assertEqual(stopgap.classify(gap, q_gap_s=300), "zastarjelo")
        self.assertEqual(stopgap.classify(gap, q_age_s=90), "zastarjelo")
        self.assertEqual(stopgap.classify(gap, liq_ref=2e6, liq_exit=0.9e6), "likvidnost")
        self.assertEqual(stopgap.classify(gap, reason="rug", q_gap_s=300), "rug")
        self.assertEqual(stopgap.classify(-1.5), "u_okviru")
        self.assertEqual(stopgap.classify(12.0), "iznad")
        self.assertEqual(stopgap.pcts(None, 0.8, 0.4), (None, None, None))

    def test_window_hour_high_and_quote_gap(self):
        w = stopgap.Window()
        w.note("A", 1000, 2e6)
        w.note("A", 1000, 1e6)            # the same quote again: ignored
        w.note("A", 1005, 1.5e6)          # same 10-s bucket: the bucket keeps its high
        w.note("A", 1400, 0.0)            # a read of 0 is no measurement
        self.assertEqual(w.ref("A", 1400), 2e6)
        self.assertEqual(w.gap("A"), 395)
        self.assertIsNone(w.ref("A", 1000 + 3601 + 10))   # older than the hour
        self.assertEqual(w.ref("A", 5000, extra=(4000, 3e6)), 3e6)   # the entry's liquidity inside the hour


class VelikiExits(VelikiLive):
    def q(self, px, liq):
        return lambda toks: {t: (px, liq, URL, 5e7, "USELESS", {"m5": 0.0}) for t in toks}

    def gaps(self):
        self.lg.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in self.lg.execute("SELECT * FROM stop_gaps ORDER BY id")]
        finally:
            self.lg.row_factory = None

    def test_liquidity_halved_within_the_hour_exits_before_the_stop(self):
        rid, stop, _size, entry = self.open_one()                 # liquidity $2M at the entry
        self.assertLess(stop, 0.97e-4)
        live.tick(self.lg, self.q(0.98e-4, 1_900_000.0), now=self.now + 20, force=True)
        live.tick(self.lg, self.q(0.97e-4, 800_000.0), now=self.now + 40, force=True)   # one read: not yet
        self.assertEqual(self.lg.execute("SELECT status FROM veliki_trades WHERE id=?", (rid,)).fetchone()[0], "open")
        out = live.tick(self.lg, self.q(0.97e-4, 790_000.0), now=self.now + 60, force=True)
        st = self.lg.execute("SELECT status, reason, exit_px, exit_why FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertEqual(st[:3], ("closed", "likvidnost", 0.97e-4))
        self.assertIn("od najviše u zadnjem satu", st[3])
        self.assertTrue(any("likvidnost pala 50 %+ u satu" in x for x in out), out)
        tid = self.lg.execute("SELECT trade_id FROM veliki_trades WHERE id=?", (rid,)).fetchone()[0]
        self.assertEqual(self.lg.execute("SELECT status FROM trades WHERE id=?", (tid,)).fetchone()[0], "closed")
        g = self.gaps()[-1]
        self.assertEqual((g["src"], g["ref_id"], g["why"], g["trade_id"]), ("veliki", rid, "likvidnost", tid))
        self.assertAlmostEqual(g["liq_ref"], 2_000_000.0)
        self.assertGreater(g["gap_pp"], 0)                        # out above its stop: that is the point

    def test_a_dip_with_the_pool_intact_keeps_the_owners_rules(self):
        rid = self.open_one()[0]
        for i, liq in enumerate((1_500_000.0, 1_200_000.0, 1_100_000.0)):   # -45 %: no exit
            live.tick(self.lg, self.q(0.97e-4, liq), now=self.now + 20 * (i + 1), force=True)
        self.assertEqual(self.lg.execute("SELECT status FROM veliki_trades WHERE id=?", (rid,)).fetchone()[0], "open")
        self.assertFalse(rule.OWNER_EXIT.get("time_h"))          # still no time stop (vlasnik 15.11.)

    def test_gapped_stop_is_recorded_with_its_plan(self):
        rid, stop, _size, entry = self.open_one()
        live.tick(self.lg, self.q(0.99e-4, 1_950_000.0), now=self.now + 20, force=True)
        px = entry * (1 - 0.594)
        live.tick(self.lg, self.q(px, 1_900_000.0), now=self.now + 40, force=True)
        st = self.lg.execute("SELECT status, reason FROM veliki_trades WHERE id=?", (rid,)).fetchone()
        self.assertEqual(tuple(st), ("closed", "stop"))
        g = self.gaps()[-1]
        self.assertAlmostEqual(g["plan_pct"], round((stop / entry - 1) * 100, 2), places=2)
        self.assertAlmostEqual(g["exit_pct"], -59.4, places=1)
        self.assertAlmostEqual(g["gap_pp"], round(-59.4 - (stop / entry - 1) * 100, 2), places=1)
        self.assertEqual(g["why"], "gap")                          # fresh quotes 20 s apart: it jumped through
        w = stopgap.worst(self.now + 60, 7, lcon=self.lg, tcon=self.con, pcon=None)
        self.assertEqual(w["gapova"], 1)
        self.assertEqual(w["najgori"][0]["zasto_hr"], "gap (skok kroz stop)")
        self.assertEqual(w["najgori"][0]["izvor"], "veliki demo")

    def test_no_quote_while_it_fell_is_a_stale_quote(self):
        rid, stop, _size, entry = self.open_one()
        live.tick(self.lg, self.q(0.99e-4, 1_950_000.0), now=self.now + 20, force=True)
        live.tick(self.lg, lambda toks: {}, now=self.now + 120, force=True)   # DexScreener has no pair for minutes
        live.tick(self.lg, self.q(entry * 0.5, 1_900_000.0), now=self.now + 400, force=True)
        self.assertEqual(self.lg.execute("SELECT reason FROM veliki_trades WHERE id=?", (rid,)).fetchone()[0], "stop")
        g = self.gaps()[-1]
        self.assertEqual(g["why"], "zastarjelo")
        self.assertGreater(g["q_gap_s"], stopgap.STALE_S)


# the fixture only: VelikiLive's own tests run in their own module, not again here
for _k in [k for k in dir(VelikiLive) if k.startswith("test_") and k not in VelikiExits.__dict__]:
    setattr(VelikiExits, _k, None)
del VelikiLive


class TpSl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lg = store.connect(os.path.join(self.tmp.name, "league.db"))
        self.lg.row_factory = sqlite3.Row
        auto._WIN["w"] = None

    def tearDown(self):
        self.lg.close()
        self.tmp.cleanup()

    def test_demo_stop_records_plan_against_exit(self):
        now = time.time()
        tid = store.buy(self.lg, "igrac", tok(5), "GAP", 25, 1.0, 1e6, "copy KOL x", None, 1e6)
        auto.set_auto(self.lg, "igrac", tid, "tpsl", "50%", "-20%")
        mk = {"px": 0.95, "liq": 1e6}

        def market(toks):
            return {t: (mk["px"], mk["liq"], None, mk["px"] * 1e6) for t in toks}
        auto.fast_once(self.lg, market, "igrac", now=now)
        mk.update(px=0.40, liq=0.3e6)
        auto.fast_once(self.lg, market, "igrac", now=now + 2)
        self.assertEqual(self.lg.execute("SELECT status, exit_rule FROM trades WHERE id=?", (tid,)).fetchone()[:2],
                         ("closed", "sl"))
        g = dict(self.lg.execute("SELECT * FROM stop_gaps").fetchone())
        self.assertEqual((g["src"], g["ref_id"], g["why"]), ("tpsl", tid, "likvidnost"))
        self.assertAlmostEqual(g["plan_pct"], -20.0, places=1)
        self.assertAlmostEqual(g["exit_pct"], -60.0, places=1)
        w = stopgap.worst(now + 10, 7, lcon=self.lg, tcon=None, pcon=None)
        self.assertEqual((w["gapova"], w["najgori"][0]["izvor"], w["najgori"][0]["gap_pp"]), (1, "TP/SL demo", -40.0))


class Read(unittest.TestCase):
    """History before the recording: veliki_trades, TP/SL trades, exit plans, the real fills, the paper bot."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.lg = store.connect(os.path.join(d, "league.db"))
        self.lg.row_factory = sqlite3.Row
        self.td = executor.connect(os.path.join(d, "trade.db"))
        self.td.row_factory = sqlite3.Row
        from paper import store as pstore
        self.pp = pstore.connect(os.path.join(d, "paper.db"))
        self.pp.row_factory = sqlite3.Row
        self.now = 1_790_000_000
        live.ensure(self.lg)
        from league import exitplan
        exitplan.ensure(self.lg) if hasattr(exitplan, "ensure") else self.lg.executescript(exitplan.SCHEMA)

    def tearDown(self):
        for c in (self.lg, self.td, self.pp):
            c.close()
        self.tmp.cleanup()

    def test_every_source_and_the_worst_first(self):
        n = self.now
        # veliki demo closed at -59.4 % with its stop at -20 % (before the recording: why unknown)
        self.lg.execute("INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, entry_px, stop_px, status, "
                        "closed_ts, exit_px, reason) VALUES ('demo', 'V1', 'VEL', ?, 900, 1.0, 0.8, 'closed', ?, 0.406, "
                        "'stop')", (n - 7200, n - 3600))
        # a veliki rug and a target (not a stop)
        self.lg.execute("INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, entry_px, stop_px, status, "
                        "closed_ts, exit_px, reason) VALUES ('demo', 'V2', 'RUG', ?, 901, 1.0, 0.8, 'closed', ?, 0.1, "
                        "'rug')", (n - 7200, n - 3000))
        self.lg.execute("INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, entry_px, stop_px, status, "
                        "closed_ts, exit_px, reason) VALUES ('demo', 'V3', 'WIN', ?, 902, 1.0, 0.8, 'closed', ?, 1.15, "
                        "'tp')", (n - 7200, n - 2000))
        # a TP/SL demo trade stopped within its plan, and its exit plan's stop of a real-account trade
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, "
                        "exit_px, auto, exit_rule) VALUES ('igrac', 'T1', 'TPS', ?, ?, 'closed', 25, 2.0, 1.58, ?, 'sl')",
                        (n - 5000, n - 1000, json.dumps({"mode": "tpsl", "sl_px": 1.6})))
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, "
                        "exit_px, exit_rule) VALUES ('pravi-trade', 'E1', 'PLN', ?, ?, 'closed', 25, 1.0, 0.7, "
                        "'manual')", (n - 5000, n - 900))
        self.lg.execute("INSERT INTO exit_events (ts, plan_id, user, token, trigger, price, mode, stale, level_px, "
                        "px_age_s) VALUES (?, 3, 'pravi-trade', 'E1', 'stop', 0.7, 'izvršeno', 0, 0.85, 4)", (n - 900,))
        self.lg.commit()
        # the real swap of that plan stop (trade.db exit_fills: level vs fill)
        self.td.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, league_id) VALUES "
                        "('E1', 'PLN', ?, 'live', 'closed', (SELECT 1))", (n - 5000,))
        lid = self.lg.execute("SELECT id FROM trades WHERE token='E1'").fetchone()[0]
        self.td.execute("UPDATE positions SET league_id=?", (lid,))
        self.td.execute("INSERT INTO exit_fills (ts, position_id, token, symbol, trigger, level_px, seen_px, fill_px, "
                        "px_age_s, mode) VALUES (?, 1, 'E1', 'PLN', 'stop', 0.85, 0.7, 0.66, 4, 'live')", (n - 880,))
        self.td.commit()
        # the paper bot's stop at -35 % that came out at -52 %
        self.pp.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status, exit_reason, ret, config) "
                        "VALUES ('P1', 'PAP', ?, ?, 'closed', 'stop_loss', -0.52, ?)", (n - 9000, n - 8000,
                                                                                         json.dumps({"sl": -0.35})))
        self.pp.commit()
        rs = stopgap.rows(n, 7, lcon=self.lg, tcon=self.td, pcon=self.pp)
        src = {r["izvor"] for r in rs}
        self.assertTrue({"veliki demo", "TP/SL demo", "plan izlaza pravi", "pravi izlaz (live)", "paper bot"} <= src, src)
        w = stopgap.worst(n, 7, n=10, lcon=self.lg, tcon=self.td, pcon=self.pp)
        worst = [(r["simbol"], r["gap_pp"], r["zasto"]) for r in w["najgori"]]
        self.assertEqual(worst[0], ("RUG", -70.0, "rug"))
        self.assertIn(("VEL", -39.4, "nepoznato"), worst)
        self.assertIn(("PAP", -17.0, "nepoznato"), worst)
        self.assertIn(("PLN", -15.0, "gap"), worst)                 # the plan's demo stop: 0.70 vs 0.85 from 1.0
        self.assertIn(("PLN", -19.0, "gap"), worst)                 # the real swap filled at 0.66
        self.assertNotIn("WIN", [r[0] for r in worst])             # a target is no stop
        self.assertNotIn("TPS", [r[0] for r in worst])             # within its plan (-1 point)
        self.assertEqual(w["gapova"], len(worst))
        self.assertEqual([r["gap_pp"] for r in w["najgori"]], sorted(r["gap_pp"] for r in w["najgori"]))

    def test_nothing_there_is_empty_not_an_error(self):
        empty = os.path.join(self.tmp.name, "nema")
        os.makedirs(empty)
        w = stopgap.worst(self.now, 7, db_dir=empty)
        self.assertEqual((w["zatvoreno_sa_stopom"], w["gapova"], w["najgori"]), (0, 0, []))


if __name__ == "__main__":
    unittest.main()
