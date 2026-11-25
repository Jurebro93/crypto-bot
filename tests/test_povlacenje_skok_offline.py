"""23.11. (vlasnik: "Tokeni su skočili, ali su se i povukli. Nećemo čekati danima da se napravi range"):
veliki/povlacenje.py, the pullback after a jump, measured in the DEMO only, offline:

  - the signal on synthetic 15m bars: fires, and does not fire for each condition (the leg, the give-back, the calm
    bars, the target's distance, too few bars, BTC's free fall in the history test), its levels
  - ops/brzi_raspon_bt.py uses the SAME function (the history test and the live demo cannot drift apart)
  - live: the explorer's own demo account enters it tagged "povlacenje" with the signal's own target and stop; the
    real account never gets it (switch on, the token on the veliki list); the proof (demo_stats) does not count it;
    the shadow book opens it in its own table (veliki_sjena_pov), never in veliki_sjena (which the learner reads)
  - nothing that decides real money imports the module

    python3 -m unittest tests.test_povlacenje_skok_offline
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import LU, PU, tok  # noqa: E402
import tests.test_istrazivac_offline as _ix  # noqa: E402  (the module, so its tests are not collected here)
from veliki import istrazivac, live, povlacenje, sjena  # noqa: E402

M15 = 900
NOW = 1_800_000_000 // M15 * M15


def jump(peak=1.20, r=0.45, calm=True, n_flat=40, t_end=NOW, scale=1.0, last_close_down=False):
    """Completed 15m bars ending at t_end: n_flat flat bars (low 0.99), a rise to the high `peak`, a fall to the close
    that gives back r of the leg (0.99 -> peak), then two bars that stopped falling (calm) or a lower low."""
    lo = 0.99
    target = peak - r * (peak - lo)
    b = [(1.0, 1.01, 0.99, 1.0)] * n_flat
    up = [1.0 + (peak - 1.0) * k / 4 for k in range(1, 5)]
    prev = 1.0
    for k, c in enumerate(up):
        b.append((prev, peak if k == 3 else c * 1.002, prev * 0.999, c * 0.995 if k == 3 else c))
        prev = b[-1][3]
    for k in range(1, 5):
        c = prev + (target * 1.004 - prev) * k / 4
        b.append((b[-1][3], b[-1][3] * 1.001, c * 0.995, c))
    ref_low = b[-1][2]
    if calm:
        c1 = target * 0.998
        b.append((b[-1][3], c1 * 1.003, ref_low * 1.001, c1))
        c2 = target * (0.997 if last_close_down else 1.0)
        b.append((c1, c2 * 1.003, ref_low * 1.002, c2))
    else:
        c1 = target * 0.999
        b.append((b[-1][3], c1 * 1.002, ref_low * 0.99, c1))           # a new lower low
        b.append((c1, target * 1.002, ref_low * 0.995, target))
    n = len(b)
    return [(t_end - (n - k) * M15, o * scale, h * scale, l * scale, c * scale, 0.0) for k, (o, h, l, c) in enumerate(b)]


class Signal(unittest.TestCase):
    def p(self, bars, px=None, **kw):
        return povlacenje.plan(bars, bars[-1][4] if px is None else px, **kw)

    def test_fires_on_a_pullback_after_a_jump(self):
        b = jump()
        p = self.p(b)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p["tp_px"], 1.20)                          # the leg's top
        self.assertAlmostEqual(p["zone"][0], 0.99)          # the lowest low before the top
        self.assertAlmostEqual(p["povrat"], 0.45, places=2)
        e = b[-1][4]
        self.assertGreaterEqual(p["tp_px"] / e - 1, 0.07)
        self.assertAlmostEqual(p["stop_px"], max(p["zone"][0] * 0.98, e * 0.88))
        self.assertGreaterEqual(p["stop_px"] / e - 1, -0.12 - 1e-12)      # never more than -12 %
        self.assertIn("povlačenje nakon skoka", povlacenje.text(p, e))

    def test_no_jump_of_12_pct(self):
        self.assertIsNone(self.p(jump(peak=1.10)))                        # an 11 % leg
        self.assertIsNotNone(self.p(jump(peak=1.15, r=0.55)))             # a 16 % leg, the top +8 % away: fires

    def test_give_back_outside_30_60_pct(self):
        self.assertIsNone(self.p(jump(r=0.22)))
        self.assertIsNone(self.p(jump(r=0.68)))
        self.assertIsNotNone(self.p(jump(peak=1.30, r=0.32)))
        self.assertIsNotNone(self.p(jump(r=0.58)))

    def test_bars_still_falling(self):
        self.assertIsNone(self.p(jump(calm=False)))                       # a lower low in the last two bars
        self.assertIsNone(self.p(jump(last_close_down=True)))             # the last close under the one before

    def test_target_under_7_pct(self):
        b = jump(peak=1.15, r=0.55)
        self.assertIsNotNone(self.p(b))
        self.assertIsNone(self.p(b, px=1.08))                             # the quote ran: the top only +6.5 % away
        self.assertIsNone(self.p(jump(peak=1.13, r=0.45)))                # 14 % leg, 45 % given back: +5.9 %
        self.assertIsNone(self.p(jump(r=0.32)))                           # 21 % leg, 32 % back: +5.9 %

    def test_too_few_bars_and_empty(self):
        self.assertIsNone(self.p(jump(n_flat=5)))
        self.assertIsNone(povlacenje.plan([], 1.0))
        self.assertIsNone(povlacenje.plan(jump(), 0))

    def test_only_the_last_24h_count(self):
        b = jump(n_flat=200)
        self.assertIsNotNone(self.p(b))
        # the same jump pushed 30 h back, flat after it: no leg in the window
        old = jump(n_flat=40) + [(b[-1][0] + k * M15, 1.1, 1.1, 1.1, 1.1, 0.0) for k in range(1, 121)]
        self.assertIsNone(self.p(old))

    def test_free_fall_refuses_only_when_asked(self):
        b = jump()
        self.assertIsNone(self.p(b, btc_state="slobodan_pad"))            # the history test's market gate
        self.assertIsNotNone(self.p(b, btc_state=None))                   # the live demo never asks (demo never stops)

    def test_history_test_uses_the_same_function(self):
        sys.path.insert(0, os.path.join(ROOT, "ops"))
        import brzi_raspon_bt as bt
        self.assertIs(bt.povlacenje, povlacenje)
        self.assertEqual({k: bt.VARIANTS["V6"][k] for k in povlacenje.V6}, povlacenje.V6)
        b = jump() + [(NOW, 1.10, 1.12, 1.09, 1.11, 0.0)]                  # bar i+1: its open is the fill
        i = len(b) - 2
        got = bt.pull_signal(b, i, bt.VARIANTS["V6"], None)
        want = povlacenje.plan_at(b, i, b[i + 1][1])
        self.assertEqual(got, want)
        self.assertIn(i, bt.signals(b, bt.VARIANTS["V6"], None))


class LivePullback(_ix._Base):
    def setUp(self):
        super().setUp()
        self.sig.stop()                                                   # the real intra.signal decides
        sjena.reset()
        self.addCleanup(sjena.reset)
        # 68 % of the mocked zone 0.9e-4 .. 1.2e-4: the rule refuses, no other explorer variant applies
        self.bars = None
        p = mock.patch.object(live, "bars_intra", lambda t, now: (self.bars_at(now), []))
        p.start()
        self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")

    def bars_at(self, now):
        return jump(t_end=int(now) - int(now) % M15, scale=1e-4)

    def px(self):
        return self.bars_at(self.now)[-1][4]

    def tick(self, toks=(31, 100)):
        want = {tok(i) for i in toks}
        return live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in want], self.px()), now=self.now,
                         force=True)

    def rows(self):
        return self.lg.execute("SELECT user, token, varijanta, kind, tp_px, stop_px, entry_px, why FROM veliki_trades "
                               "ORDER BY id").fetchall()

    def test_explorer_enters_tagged_with_its_own_levels_real_never(self):
        from veliki import gate
        self.switch(True)                                                 # even with the owner's switch on
        self.flag("veliki_range", "live")
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: None), self._prio():
            out = self.tick()
        rows = self.rows()
        self.assertEqual({(r[0], r[1], r[2], r[3]) for r in rows},
                         {(istrazivac.USER, tok(31), "povlacenje", "intra"),
                          (istrazivac.USER, tok(100), "povlacenje", "intra")}, out)
        self.assertNotIn(LU, {r[0] for r in rows})                        # the real account never gets it
        self.assertNotIn(PU, {r[0] for r in rows})                        # nor the rule's demo account
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user IN (?,?)", (LU, PU)).fetchone()[0], 0)
        r = rows[0]
        self.assertAlmostEqual(r[4], 1.20e-4)                             # target: the leg's top
        self.assertAlmostEqual(r[5] / r[6], max(0.99 * 0.98 * 1e-4 / r[6], 0.88), places=6)
        self.assertIn("povlačenje nakon skoka", r[7])
        line = [x for x in out if x.startswith("veliki istraživač ulaz [povlacenje] ")]
        self.assertEqual(len(line), 2, out)
        self.assertIn("samo demo, ne ulazi u dokaz", line[0])

    def test_not_in_the_proof_and_in_the_explorers_line(self):
        self.tick((100,))
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=-0.14, pnl_usd=-2.1, reason='stop' "
                        "WHERE user=?", (self.now + 60, istrazivac.USER))
        self.lg.commit()
        self.assertEqual(live.demo_stats(self.lg)["n"], 0)                # gate.demo_proof reads PAPER_USER only
        ln = istrazivac.line(self.lg, self.now + 120)
        self.assertIn("povlacenje (povlačenje nakon skoka", ln)
        self.assertIn("n=1, prosjek -14.0%", ln)

    def test_shadow_book_own_table_only(self):
        self.tick((100,))
        pov = self.lg.execute("SELECT ulaz, profil, tp_px FROM veliki_sjena_pov WHERE token=?", (tok(100),)).fetchall()
        self.assertEqual({p[1] for p in pov}, set(sjena.PROFILES) | {sjena.POV_OWN})
        self.assertEqual({p[0] for p in pov}, {"povlacenje"})
        own = [p for p in pov if p[1] == sjena.POV_OWN][0]
        self.assertAlmostEqual(own[2], 1.20e-4)
        # the ordinary book rows of the same candidate are unchanged (one per profile, no "vlastiti")
        main = {p[0] for p in self.lg.execute("SELECT profil FROM veliki_sjena WHERE token=?", (tok(100),))}
        self.assertEqual(main, set(sjena.PROFILES))
        # the exits close both: the target of "vlastiti" crossed, filled at the next quote
        n = sjena.mark(self.lg, {tok(100): (1.21e-4,)}, self.now + 60)
        n += sjena.mark(self.lg, {tok(100): (1.21e-4,)}, self.now + 90)
        st = dict(self.lg.execute("SELECT profil, reason FROM veliki_sjena_pov WHERE token=? AND status='closed'",
                                  (tok(100),)).fetchall())
        self.assertEqual(st.get(sjena.POV_OWN), "tp")
        self.assertGreater(n, 0)
        self.assertIn("povlačenje nakon skoka (vlastita tablica, samo sjena)", sjena.line(self.lg, self.now + 120))
        # the learner (which can reach real money through the owner's switch) reads veliki_sjena only
        from veliki import nauceno
        rows = nauceno.load(None, self.lg, self.now + 120)
        self.assertFalse(any(r.get("profil") == sjena.POV_OWN for r in rows))
        self.assertEqual(len([r for r in rows if r.get("token") == tok(100)]),
                         self.lg.execute("SELECT COUNT(*) FROM veliki_sjena WHERE token=? AND status='closed' AND "
                                         "ret IS NOT NULL", (tok(100),)).fetchone()[0])


class NothingRealReadsIt(unittest.TestCase):
    def test_real_money_modules_do_not_import_it(self):
        for f in ("veliki/live.py", "veliki/gate.py", "veliki/riskoff.py", "trade/settings.py", "trade/executor.py",
                  "veliki/nauceno.py", "veliki/ucenik.py", "market/trziste.py"):
            with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn("povlacenje", src, f)
            self.assertNotIn("veliki_sjena_pov", src, f)

    def test_pure_no_io(self):
        with open(os.path.join(ROOT, "veliki/povlacenje.py"), encoding="utf-8") as fh:
            src = fh.read()
        for bad in ("import urllib", "import requests", "sqlite3", "open(", "http"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
