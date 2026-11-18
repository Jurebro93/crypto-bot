"""18.11. (vlasnik: "obavezno treba biti što više demo tradeova"; "analitičar Grok bot ... informacije s Twittera"),
veliki/istrazivac.py, offline:

  - variant(): what the rule refused and the explorer takes (sire / pada / grok) and what nobody takes
  - live: a refused candidate opens a trade on the explorer's OWN demo account, tagged; never on the rule's demo
    account, never on the real one; the same stop and target; its own cooldown; VEL_ISTRAZIVAC=0 switches it off
  - kept apart: the rule's cooldown ignores the explorer's exits, demo_stats (the real-money proof) and the morning
    report's rows do not see its trades; the hour's line "veliki istraživač: ..."

    python3 -m unittest tests.test_istrazivac_offline
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import LU, PU, tok  # noqa: E402
import tests.test_veliki_intra_offline as _it  # noqa: E402  (the module, so its own tests are not collected here)
from veliki import intra, istrazivac, live  # noqa: E402

M15, calm15 = _it.M15, _it.calm15


class _Base(_it.Live):
    """The fixtures of the intraday live tests without their tests (they assume a signal that always passes)."""


for _n in [n for n in dir(_it.Live) if n.startswith("test_")]:
    setattr(_Base, _n, None)

XU = istrazivac.USER
Z = {"ok": True, "lo": 0.9, "hi": 1.2, "width": 0.33}
NOW = 1_800_000_000


def falling15(t_end, px):
    """Three completed 15m bars that are still falling (a lower low, a lower close)."""
    return [(t_end - 3 * M15, px * 1.04, px * 1.05, px * 1.02, px * 1.03, 0.0),
            (t_end - 2 * M15, px * 1.03, px * 1.03, px * 1.00, px * 1.01, 0.0),
            (t_end - M15, px * 1.01, px * 1.01, px * 0.98, px * 0.99, 0.0)]


class Variant(unittest.TestCase):
    def v(self, px, bars=None, **kw):
        return istrazivac.variant(px, kw.pop("z", Z), calm15(NOW, px) if bars is None else bars, None, now=NOW, **kw)

    def test_what_the_rule_takes_the_explorer_leaves(self):
        self.assertIsNone(self.v(0.95))                                   # bottom 25 %, calm: the rule's own entry

    def test_wider_zone_and_still_falling(self):
        self.assertEqual(self.v(1.02), "sire")                            # 40 % of the zone, calm
        self.assertIsNone(self.v(1.10))                                   # 67 %: above the bottom half
        self.assertEqual(self.v(0.95, falling15(NOW, 0.95)), "pada")      # in the rule's zone, bars still falling
        self.assertIsNone(self.v(1.02, falling15(NOW, 1.02)))             # wider AND falling: two relaxations, no

    def test_groks_fresh_confident_buy(self):
        g = {"verdict": "kupi", "confidence": 0.8, "ts": NOW - 3600}
        self.assertEqual(self.v(1.10, grok=g), "grok")                    # 67 % of the zone: only his word
        self.assertEqual(self.v(0.95, falling15(NOW, 0.95), grok=g), "grok")
        self.assertIsNone(self.v(1.18, grok=g))                           # the top quarter: not even with him
        self.assertIsNone(self.v(0.95, grok=g))                           # the rule enters anyway: not his trade
        for bad in ({"verdict": "preskoči", "confidence": 0.9, "ts": NOW}, {"verdict": "kupi", "confidence": 0.4, "ts": NOW},
                    {"verdict": "kupi", "confidence": 0.9, "ts": NOW - 7 * 3600}, {"verdict": "kupi"}, {}, None):
            self.assertIsNone(self.v(1.10, grok=bad), bad)

    def test_never_outside_a_valid_zone_or_in_a_free_fall(self):
        self.assertIsNone(self.v(1.02, z={**Z, "ok": False, "why": "raspon preuzak"}))
        self.assertIsNone(self.v(1.02, z=None))
        self.assertIsNone(self.v(0.80))                                   # under the zone: breaking down
        self.assertIsNone(self.v(1.02, btc_state="slobodan_pad"))
        self.assertIsNone(self.v(0))


class LiveExplorer(_Base):
    def setUp(self):
        super().setUp()
        self.sig.stop()                                                   # the real intra.signal decides here
        self.px = 1.0e-4                                                  # 33 % of the zone 0.9e-4 .. 1.2e-4
        p = mock.patch.object(live, "bars_intra", lambda t, now: (calm15(now, self.px), []))
        p.start()
        self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")

    def tick(self, toks=(100,), now=None, px=None):
        want = {tok(i) for i in toks}
        return live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in want], px or self.px), now=now or self.now,
                         force=True)

    def rows(self):
        return self.lg.execute("SELECT user, token, varijanta, kind, size_sol, stop_px, tp_px, status FROM veliki_trades "
                               "ORDER BY id").fetchall()

    def test_a_refused_candidate_goes_to_the_explorers_own_demo_account(self):
        from veliki import gate
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: None), self._prio():
            out = self.tick((31, 100))
        rows = self.rows()
        self.assertEqual({(r[0], r[1], r[2], r[3]) for r in rows},
                         {(XU, tok(31), "sire", "intra"), (XU, tok(100), "sire", "intra")}, out)
        self.assertNotIn(PU, {r[0] for r in rows})                        # not the rule's demo account
        self.assertNotIn(LU, {r[0] for r in rows})                        # never real money, the switch on or not
        self.assertTrue(all(r[4] == live.INTRA_DEMO_SOL for r in rows))
        self.assertAlmostEqual(rows[0][5] / self.px, 0.80, places=3)      # the rule's own wide stop
        self.assertGreater(rows[0][6], self.px)
        self.assertTrue(any(x.startswith("veliki istraživač ulaz [sire] ") for x in out), out)
        self.assertFalse(any(x.startswith("veliki demo ulaz") for x in out), out)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user=? AND status='open'", (XU,)).fetchone()[0], 2)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user IN (?,?)", (PU, LU)).fetchone()[0], 0)

    def test_the_rules_own_entry_is_not_duplicated(self):
        out = self.tick(px=0.95e-4)                                       # the bottom 25 %, calm: the rule enters
        self.assertEqual([(r[0], r[2]) for r in self.rows()], [(PU, None)], out)

    def test_grok_tag_from_the_priority_row(self):
        self.px = 1.1e-4                                                  # 67 % of the zone: only Grok's word
        from veliki import prioritet
        pr = {tok(100): {"mint": tok(100), "symbol": "MID", "score": 1.0, "parts": {}, "facts": {},
                         "grok": {"verdict": "kupi", "confidence": 0.9, "ts": self.now - 600}}}
        with mock.patch.object(prioritet, "cached", lambda *a, **k: pr):
            out = self.tick()
        self.assertEqual([(r[0], r[2]) for r in self.rows()], [(XU, "grok")], out)
        self.assertTrue(any(x.startswith("veliki istraživač ulaz [grok] ") for x in out), out)
        self.lg.execute("DELETE FROM veliki_trades")
        self.lg.execute("DELETE FROM trades")
        self.lg.commit()
        live._ST["bar15"] = {}
        pr[tok(100)]["grok"]["verdict"] = "preskoči"                      # without his "kupi": nobody enters up there
        with mock.patch.object(prioritet, "cached", lambda *a, **k: pr):
            self.tick()
        self.assertEqual(self.rows(), [])

    def test_own_cooldown_and_the_rule_ignores_the_explorers_exit(self):
        self.tick()
        rid = self.lg.execute("SELECT id FROM veliki_trades WHERE user=?", (XU,)).fetchone()[0]
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=-0.05, pnl_usd=-0.7 WHERE id=?",
                        (self.now + 60, rid))
        self.lg.execute("UPDATE trades SET status='closed' WHERE user=?", (XU,))
        self.lg.commit()
        t1 = self.now + M15 + 5                                           # the next 15m bar, 15 min after the exit
        self.tick(now=t1)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=?", (XU,)).fetchone()[0], 1)
        out = self.tick(now=t1 + M15, px=0.95e-4)                         # the rule's own signal, 30 min not yet over
        self.assertIn((PU, tok(100)), {(r[0], r[1]) for r in self.rows()}, out)

    def test_switched_off_by_env(self):
        with mock.patch.dict(os.environ, {"VEL_ISTRAZIVAC": "0"}):
            self.tick()
            self.assertEqual(self.rows(), [])
            self.assertIn("isključen", istrazivac.line(self.lg, self.now))

    def test_kept_out_of_the_proof_the_reports_and_the_demo_line(self):
        from report import midcap as rmid
        self.tick()
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=0.12, pnl_usd=1.8, reason='tp' "
                        "WHERE user=?", (self.now + 60, XU))
        self.lg.commit()
        self.assertEqual(live.demo_stats(self.lg)["n"], 0)                # gate.demo_proof reads PAPER_USER only
        self.assertEqual(rmid.vrows(self.lg, closed_only=True), [])
        self.assertEqual(rmid.vrows(self.lg, since=0), [])
        self.assertIn("otvoreno 0 danas", live.report_line(self.lg, self.now + 120))
        line = istrazivac.line(self.lg, self.now + 120)
        self.assertTrue(line.startswith("veliki istraživač (demo, odbijeni kandidati): danas otvoreno 1, sada otvorenih 0"))
        self.assertIn("sire (donja polovica zone (pravilo traži donjih 25 %)): n=1, prosjek +12.0%, pogodak 100%", line)
        self.assertIn("pada (u zoni pravila, ali svijeće još padaju): još nema zatvorenih", line)
        self.assertIn("pravilo (demo, dnevni raspon) u istom razdoblju: još nema zatvorenih", line)
        live._ST["rep_h"] = 0
        out = self.tick(now=self.now + 130)
        self.assertTrue(any(x.startswith("veliki istraživač (demo") for x in out), out)

    def test_an_error_in_the_explorer_never_costs_the_rules_pass(self):
        with mock.patch.object(istrazivac, "variant", side_effect=RuntimeError("x")):
            out = self.tick()
        self.assertEqual(self.rows(), [])
        self.assertTrue(any("veliki istraživač: ulaz nije uspio (RuntimeError" in x for x in out), out)


if __name__ == "__main__":
    unittest.main()
