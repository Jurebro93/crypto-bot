"""16.11. (vlasnik, jutarnji izvještaj: "prodaj presude 0 % pogodaka na 84 mjerenja, drži 100 %"; "Kritičarove 'prodaj'
presude dosad nisu bile točne, pa ih ne treba slijepo slijediti"): critic/store's measurement.

The bug: one threshold for both sides. A sell verdict was right at r <= -2 %, a hold verdict at r > -2 %, so every
flat price (the real account's midcaps rarely move 2 % in 30-60 min) was a hold hit AND a sell miss. Now a move inside
+-HIT_BAND decides nothing (counted as "ravno"), hold is right only at r >= +2 %. The history is re-scored at read time
from the stored MCs. The horizon (+30 / +60 min after the critique), the sign and the missing price (never the
critique's own MC) are checked too. And the critic is ADVICE ONLY: nothing closes, sells or changes a position or its
exit because of a verdict.

    python3 -m unittest tests.test_kriticar_mjerenje_offline
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from critic import store as cstore  # noqa: E402
from tests.test_kriticar_offline import MINT, NOW, Base, answer, verdicts  # noqa: E402


class Scoring(Base):
    def row(self, verdict, mc0, mc30=None, mc60=None, mc_close=None, closed_ts=None, pid=1, ts=NOW, value=15.0):
        self.con.execute("INSERT INTO critic_verdicts (ts, pid, token, mode, verdict, confidence, mc0, value_usd, mc30, "
                         "mc60, mc_close, closed_ts, done) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
                         (ts, pid, MINT, "live", verdict, 0.7, mc0, value, mc30, mc60, mc_close, closed_ts))
        self.con.commit()

    def test_symmetric_band(self):
        self.assertIsNone(cstore.hit_of("prodaj", 0.0))
        self.assertIsNone(cstore.hit_of("drzi", -0.019))
        self.assertIsNone(cstore.hit_of("drzi", 0.019))
        self.assertTrue(cstore.hit_of("prodaj", -0.05))
        self.assertFalse(cstore.hit_of("drzi", -0.05))
        self.assertTrue(cstore.hit_of("drzi", 0.05))
        self.assertFalse(cstore.hit_of("prodaj", 0.05))
        self.assertTrue(cstore.hit_of("stegni_sl", -0.03))
        self.assertFalse(cstore.hit_of("prosiri_sl", -0.03))

    def test_flat_history_is_rescored_honestly(self):
        # the owner's numbers: every sell "wrong", every hold "right", the prices flat (+-1 %) on three positions
        for i in range(84):
            self.row("prodaj", 100_000.0, 100_000.0 * (1 + (i % 3 - 1) / 100), 100_000.0 * (1 + (i % 3 - 1) / 100),
                     pid=1 + i % 3, ts=NOW + i * 900)
        for i in range(20):
            self.row("drzi", 100_000.0, 100_500.0, 100_000.0, pid=4, ts=NOW + i * 900)
        d = cstore.diagnose(self.con, 7, NOW + 84 * 900)
        p, h = d["presude"]["prodaj"], d["presude"]["drzi"]
        self.assertEqual((p["n"], p["pozicija"]), (84, 3))
        self.assertEqual((p["60"]["pogodak_staro"], h["60"]["pogodak_staro"]), (0.0, 1.0))   # the reported 0 % / 100 %
        self.assertEqual((p["60"]["pogodak"], h["60"]["pogodak"]), (None, None))   # flat decided nothing
        self.assertEqual((p["60"]["ravno"], p["60"]["odluceno"]), (84, 0))
        self.assertEqual(h["60"]["isto_kao_kritika"], 20)
        s = cstore.stats(self.con, 7, NOW + 84 * 900)["presude"]
        self.assertEqual((s["prodaj"]["pogodak_60"], s["prodaj"]["ravno_60"], s["prodaj"]["pozicija"]), (None, 84, 3))
        self.assertEqual(s["drzi"]["pogodak_60"], None)
        self.assertEqual(s["prodaj"]["medijan_pomaka_60_pct"], 0.0)

    def test_moves_outside_the_band_count_both_ways(self):
        self.row("prodaj", 100_000.0, 95_000.0, 90_000.0, ts=NOW)             # it fell: the sell was right
        self.row("prodaj", 100_000.0, 104_000.0, 110_000.0, ts=NOW + 1)       # it rose: the sell was wrong
        self.row("drzi", 100_000.0, 106_000.0, 114_400.0, ts=NOW + 2)         # TROLL-like: hold right
        self.row("drzi", 100_000.0, 97_000.0, 96_000.0, ts=NOW + 3)           # hold wrong
        s = cstore.stats(self.con, 7, NOW + 10)["presude"]
        self.assertEqual((s["prodaj"]["pogodak_60"], s["prodaj"]["izmjereno_60"]), (0.5, 2))
        self.assertEqual((s["drzi"]["pogodak_60"], s["drzi"]["izmjereno_60"]), (0.5, 2))
        # $ if followed: prodaj at 100k vs the bot holding to 90k / 110k on $15: +1.50 and -1.50
        self.assertAlmostEqual(s["prodaj"]["usd_60min"], 0.0)

    def test_flat_points_still_count_in_dollars(self):
        self.row("prodaj", 100_000.0, 99_000.0, 99_000.0)
        s = cstore.stats(self.con, 7, NOW + 10)["presude"]["prodaj"]
        self.assertIsNone(s["pogodak_60"])
        self.assertAlmostEqual(s["usd_60min"], 0.15)   # sold at 100k instead of 99k: 1 % of $15

    def test_horizon_is_after_the_critique_and_no_fallback_to_its_mc(self):
        pid = self.add_pos()
        pos = {"pid": pid, "token": MINT, "sym": "TOK", "mode": "live", "strategy": "veliki", "pnl_pct": -4.2,
               "mc_now": 100_000.0, "value_usd": 15.0}
        cstore.add_verdict(self.con, 1, None, pos, {"verdict": "prodaj", "confidence": 0.7}, now=NOW)
        self.con.commit()
        asked = []

        def at(tok, ts):
            asked.append(ts - NOW)
            return {NOW + 1800: 97_000.0}.get(ts)
        cstore.evaluate(self.con, NOW + 1810, mc_at_fn=at, live_fn=lambda toks: {})
        self.assertEqual(asked, [1800])                      # +30 min from the critique, not the critique itself
        cstore.evaluate(self.con, NOW + 3610, mc_at_fn=at, live_fn=lambda toks: {})
        mc30, mc60 = self.con.execute("SELECT mc30, mc60 FROM critic_verdicts").fetchone()
        self.assertEqual((mc30, mc60), (97_000.0, None))     # no price at +60: waits, never the critique's 100k
        cstore.evaluate(self.con, NOW + 3600 + cstore.EVAL_LATE_S + 1, mc_at_fn=at, live_fn=lambda toks: {})
        self.assertEqual(self.con.execute("SELECT mc60 FROM critic_verdicts").fetchone()[0], 0.0)   # given up
        s = cstore.stats(self.con, 7, NOW + 9000)["presude"]["prodaj"]
        self.assertEqual((s["pogodak_30"], s["izmjereno_60"]), (1.0, 0))   # -3 % after a sell: right


# ---------- advice only ------------------------------------------------------------------------------------------------

# the packages and scripts that trade, mirror, exit or change a position or its exit (real or demo)
TRADING = ("trade", "league", "veliki", "exits", "izlazi", "rangedca", "momentum", "fast", "paper", "konsenzus",
           "oscilator", "proposals", "insajderi", "run_trade.py", "run_veliki.py", "run_paper.py", "run_exits.py",
           "run_izlazi.py", "run_range.py", "run_momentum.py", "run_fast.py", "run_konsenzus.py", "run_oscilator.py")
CRITIC_TABLES = ("critic_verdicts", "critic_kv", "kriticar_pozicije", "openai-kriticar")


def _py_files(rel):
    path = os.path.join(ROOT, rel)
    if path.endswith(".py"):
        yield path
        return
    for d, _dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


class AdviceOnly(Base):
    def test_no_trading_code_imports_the_critic_or_reads_its_verdicts(self):
        bad = []
        for rel in TRADING:
            for f in _py_files(rel):
                with open(f, encoding="utf-8") as fh:
                    src = fh.read()
                tree = ast.parse(src)
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        mods = [node.module or ""]
                    if any(m == "critic" or m.startswith("critic.") for m in mods):
                        bad.append(f"{os.path.relpath(f, ROOT)}: import {mods}")
                for t in CRITIC_TABLES:
                    if t in src:
                        bad.append(f"{os.path.relpath(f, ROOT)}: {t}")
        self.assertEqual(bad, [])

    def test_the_critic_writes_only_its_own_tables_and_notes(self):
        bad = []
        for f in _py_files("critic"):
            with open(f, encoding="utf-8") as fh:
                src = fh.read()
            for needle in ("UPDATE positions", "INSERT INTO positions", "INSERT INTO orders", "sell_req", "executor.sell",
                           "executor.buy", "set_auto(", "exitplan.set", "exitplan.save", "settings.put(", "set_flag(",
                           "store.sell(", "sell_part(", "UPDATE trades"):
                if needle in src:
                    bad.append(f"{os.path.relpath(f, ROOT)}: {needle}")
        self.assertEqual(bad, [])

    def test_a_sell_verdict_on_a_live_position_changes_nothing(self):
        from trade import settings
        self.key()
        pid = self.add_pos()
        before = self.con.execute("SELECT * FROM positions").fetchall()
        res, _http = self.run_trades([self.pos(pid, pnl=-4.2)], [answer(verdicts((pid, "prodaj", 0.9)))])
        self.assertEqual(res["presude"], {"prodaj": 1})
        self.assertEqual(self.con.execute("SELECT * FROM positions").fetchall(), before)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
        raw = settings.raw(self.con)
        self.assertFalse(raw.get("sell_req"))
        self.assertNotIn(str(pid), raw.get("manual_size") or {})
        import run_trade
        from trade import executor
        cfg = settings.merged(executor.load_config(), self.con)
        run_trade.sell_requests_once(self.con, cfg, now=NOW, quiet=True)   # the page's sell buttons: nothing asked
        self.assertEqual(self.con.execute("SELECT * FROM positions").fetchall(), before)


if __name__ == "__main__":
    unittest.main()
