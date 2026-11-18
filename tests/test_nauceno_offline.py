"""18.11. (vlasnik: "da program što više nauči iz tih mid-capova ... da nauči kombinirati te faktore ... želim da demo
što prije bude profitabilan"), veliki/nauceno.py, offline (synthetic candles and rows, no network):

  - history: the shadow book over 15m candles (a stop at its level less the slip, a target never above the bar's
    close, the time limit), the same facts as a live row; nothing from after the entry
  - the learner: the walk-forward never sees the day it predicts; a fact that wins is chosen on later days and the
    verdict needs enough token-days and an interval above zero; no signal = no verdict of a plus
  - run(): midcap.db veliki_sjena_h rebuilt, kv "nauceno", the line; the MCP block; the live book's cost floor

    python3 -m unittest tests.test_nauceno_offline
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tests.test_veliki_replay_offline as _rp  # noqa: E402  (the module, so its tests are not collected here)
from veliki import midcap, nauceno, replay, rule, sjena  # noqa: E402

D, H, M15 = 86400, 3600, 900
NOW = _rp.NOW
RT = 0.03


def row(tok, day, k, prof, ret, band="dno", calm=1, btc="normalno", **kw):
    d = {"token": tok, "opened_ts": day * D + 600 + k * M15, "profil": prof, "ret": ret, "band": band, "calm": calm,
         "zone_ok": 1, "zone_why": None, "width": 0.25, "btc": btc, "makro": "neutral", "dip": None, "oprez": 0,
         "grok": None}
    d.update(kw)
    return d


class History(unittest.TestCase):
    def sim(self, bars, **kw):
        h1 = rule.h1_from_15m(bars)
        return nauceno.simulate(bars, h1, RT, "TOK", "TOK", 500_000.0, **kw)

    def test_rows_carry_the_facts_and_every_profile(self):
        rows = self.sim(_rp.ou_bars(7, 6))
        self.assertGreater(len(rows), 30)
        self.assertEqual({r["profil"] for r in rows}, set(sjena.PROFILES))
        for r in rows[:50]:
            self.assertIn(r["band"], ("dno", "donja", "sredina", "vrh", "ispod", "iznad"))
            self.assertIn(r["reason"], ("tp", "stop", "vrijeme"))
            self.assertGreater(r["closed_ts"], r["opened_ts"])
            self.assertAlmostEqual(r["ret"], r["exit_px"] / r["entry_px"] * (1 - RT) - 1, places=9)
            self.assertEqual(set(nauceno.facts(r)), set(nauceno.FEATS))

    def test_a_stop_fills_under_its_level_and_a_wick_is_not_a_sale(self):
        base = _rp.ou_bars(3, 3, sigma=0.004)                     # three quiet days: a zone exists
        t, px = base[-1][0] + M15, base[-1][4]
        crash = [(t, px, px * 1.001, px * 0.80, px * 0.99, 1.0)]  # the next bar dips 20 % and closes back
        rows = [r for r in self.sim(base + crash) if r["closed_ts"] == t + M15 and r["reason"] == "stop"]
        self.assertTrue(rows)
        for r in rows:
            self.assertAlmostEqual(r["exit_px"], r["stop_px"] * (1 - nauceno.STOP_SLIP), places=12)
        spike = [(t, px, px * 1.30, px * 0.999, px * 1.001, 1.0)]  # a 30 % wick up, the bar closes flat
        rows = [r for r in self.sim(base + spike) if r["closed_ts"] == t + M15 and r["reason"] == "tp"]
        self.assertTrue(rows)
        for r in rows:
            self.assertLess(r["exit_px"], r["tp_px"])             # booked at the close, not at the target
            self.assertAlmostEqual(r["exit_px"], px * 1.001, places=12)

    def test_nothing_after_the_entry_changes_the_entry(self):
        bars = _rp.ou_bars(11, 6)
        cut = len(bars) - 96
        a = {(r["opened_ts"], r["profil"]): (r["entry_px"], r["band"], r["calm"]) for r in self.sim(bars)}
        b = {(r["opened_ts"], r["profil"]): (r["entry_px"], r["band"], r["calm"]) for r in self.sim(bars[:cut])}
        t_cut = bars[cut][0]
        early = [k for k in b if k[0] <= t_cut - 3 * D]
        self.assertTrue(early)
        for k in early:                                           # entries of the first days are the same with or
            self.assertEqual(a.get(k), b[k])                      # without the last day's bars

    def test_time_limit(self):
        rows = self.sim(_rp.ou_bars(5, 6, sigma=0.0005), max_h=2)  # almost flat: nothing reaches a level
        self.assertTrue(rows)
        self.assertEqual({r["reason"] for r in rows}, {"vrijeme"})


class Learner(unittest.TestCase):
    def book(self, days=20, win="dno", lose="vrh", per_day=6, flip_from=None):
        rows = []
        for d in range(days):
            w, lo = (lose, win) if flip_from is not None and d >= flip_from else (win, lose)
            for k in range(per_day):
                tok = f"T{k}"
                rows.append(row(tok, 20000 + d, k, "skalp", 0.04 + 0.001 * (k % 3), band=w))
                rows.append(row(tok, 20000 + d, k + 6, "skalp", -0.05 - 0.001 * (k % 3), band=lo))   # the same hours
        return sorted(rows, key=lambda r: r["opened_ts"])

    def test_a_fact_that_wins_is_chosen_on_days_it_had_not_seen(self):
        res = nauceno.learn(self.book())
        self.assertEqual(res["days"], 20)
        self.assertEqual(res["test_days"], 13)
        self.assertEqual(res["picked"]["n"], 13 * 6)              # only the winning band, only from day 8 on
        self.assertGreater(res["picked"]["lo"], 0)
        self.assertAlmostEqual(res["all"]["ev_trade"], -0.005, places=3)
        self.assertTrue(res["picked"]["lo"] <= res["picked"]["ev"] <= res["picked"]["hi"])   # one kind of mean
        self.assertEqual(res["verdict"], "kandidat")
        self.assertEqual(res["best"][0]["value"], "dno")
        self.assertEqual(res["worst"][0]["value"], "vrh")
        self.assertIn("KANDIDAT", nauceno.line({**res, "ts": 1, "backfill": {"rows": 5, "tokens": 6}}))

    def test_the_predicted_day_is_never_in_the_training(self):
        res = nauceno.learn(self.book(days=9, flip_from=7))       # the winner changes on the first test day
        # day 8 and 9 are predicted from days 1-7 (and 1-8): it still picks the OLD winner and loses, which is what
        # an honest walk-forward must show; a model that had seen the day would pick the new winner and win
        self.assertEqual(res["picked"]["n"], 6 + 6)
        self.assertLess(res["picked"]["ev"], 0)
        self.assertNotEqual(res["verdict"], "kandidat")

    def test_no_signal_no_plus_and_too_little_is_said(self):
        rows = [row(f"T{k}", 20000 + d, k, "kratko", -0.03 + (0.01 if (k + d) % 2 else -0.01)) for d in range(20)
                for k in range(8)]
        res = nauceno.learn(sorted(rows, key=lambda r: r["opened_ts"]))
        self.assertEqual(res["picked"]["n"], 0)                   # every prediction is under zero: nothing is taken
        self.assertEqual(res["verdict"], "premalo")
        few = nauceno.learn(self.book(days=9))
        self.assertEqual(few["verdict"], "premalo")               # 2 test days x 6 tokens = 12 token-days < 30

    def test_variants_look_at_the_same_unseen_days_and_say_so(self):
        rows = self.book()
        for r in rows:
            r["rt"] = RT
        rows += [row(f"T{k}", 20000 + d, k + 12, "siroko", 0.02, band="ispod", rt=RT) for d in range(20) for k in range(3)]
        rows.sort(key=lambda r: r["opened_ts"])
        res = nauceno.learn(rows)
        v = res["variants"]
        self.assertLessEqual(v["thr"]["0.01"]["n"], res["picked"]["n"])          # a stricter choice is a subset
        self.assertLessEqual(v["thr"]["0.03"]["n"], v["thr"]["0.02"]["n"])
        # a cheaper round trip: the saved cost is added to every chosen trade, the choice itself does not change
        self.assertEqual(v["rt"]["0.020"]["n"], res["picked"]["n"])
        self.assertAlmostEqual(v["rt"]["0.020"]["ev"], res["picked"]["ev"] + 0.01, places=6)
        self.assertAlmostEqual(v["rt"]["0.015"]["ev"], res["picked"]["ev"] + 0.015, places=6)
        # the plain rule: every "ispod" row under the wide exit on the unseen days only (13 days x 3 tokens)
        self.assertEqual(v["fixed"]["ispod × siroko"]["n"], 13 * 3)
        self.assertAlmostEqual(v["fixed"]["ispod × siroko"]["ev"], 0.02, places=6)
        self.assertEqual(v["fixed"]["ispod × pravilo"]["n"], 0)
        ln = nauceno.line_variants({**res, "ts": 1})
        self.assertIn("nisu dokaz", ln)
        self.assertIn("uz trošak 2.0%", ln)
        self.assertIn("ispod × siroko: +2.0%", ln)
        self.assertIsNone(nauceno.line_variants({"ts": 1}))                       # an older stored result: no line
        # a row without a booked cost is left as it is (never a made-up saving)
        res2 = nauceno.learn(self.book())
        self.assertAlmostEqual(res2["variants"]["rt"]["0.020"]["ev"], res2["picked"]["ev"], places=9)
        self.assertIn("variants", nauceno.summary({**res, "ts": 1}))

    def test_shrinkage_and_unknown_facts(self):
        m = nauceno.Model(shrink=150)
        for i in range(10):
            m.add(row("A", 1, i, "skalp", 0.10, band="dno"))
        for i in range(990):
            m.add(row("B", 1, i, "skalp", 0.0, band="vrh"))
        self.assertAlmostEqual(m.effect("skalp", "band", "dno"), (0.10 - 0.001) * 10 / 160, places=6)   # 10 rows: weak
        f = nauceno.facts(row("A", 1, 0, "skalp", 0.0, band=None, btc=None, makro=None, width=None))
        self.assertEqual((f["band"], f["btc"], f["makro"], f["sirina"], f["grok"]), ("?", "?", "?", "?", "?"))
        self.assertEqual(nauceno.facts(row("A", 1, 0, "skalp", 0.0, makro="oporavak/blago_bik"))["makro"], "oporavak")
        self.assertIsNone(m.predict("nema", f))


class Run(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "midcap.db")
        cls.hpath = os.path.join(cls.tmp.name, "nauceno.db")
        _rp.make_db(cls.path, n_tok=8, days=14)
        cls.lines = []
        with mock.patch.dict(os.environ, {"MIDCAP_DB": cls.path}):
            midcap._MEM.update(ts=0.0, rows=[])
            cls.res = nauceno.run(NOW, cls.lines.append, cls.path, os.path.join(cls.tmp.name, "nema-league.db"),
                                  btc=_rp.btc_rows())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_history_is_rebuilt_and_the_result_is_stored_and_said(self):
        r = self.res
        self.assertEqual(r["backfill"]["tokens"], 8)
        self.assertGreater(r["backfill"]["rows"], 500)
        self.assertEqual(r["rows"], r["backfill"]["rows"])
        self.assertEqual(r["live_rows"], 0)
        self.assertIn(r["verdict"], ("kandidat", "premalo", "nema_plusa"))
        self.assertTrue(self.lines[-2].startswith("veliki naučeno: "), self.lines)
        self.assertIn("provjera na zadnjih", self.lines[-2])
        self.assertTrue(self.lines[-1].startswith("veliki naučeno: varijante"), self.lines)   # the second line
        import sqlite3
        self.assertNotIn(nauceno.TABLE_H, {r[0] for r in midcap.ro(self.path).execute(
            "SELECT name FROM sqlite_master")})                   # midcap.db is only read; the history has its own file
        con = sqlite3.connect(nauceno.db_path(self.hpath))
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {nauceno.TABLE_H}").fetchone()[0]
            rts = con.execute(f"SELECT MIN(rt) FROM {nauceno.TABLE_H}").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(n, r["backfill"]["rows"])
        self.assertGreaterEqual(rts, replay.RT_FLOOR)             # the real account's cost, never under 3 %
        self.assertEqual(nauceno.latest(self.hpath)["verdict"], r["verdict"])
        s = nauceno.summary(nauceno.latest(self.hpath))
        self.assertEqual(set(s["by_profile"]), set(sjena.PROFILES))
        self.assertIn("never under 3 %", s["how"])

    def test_a_second_run_replaces_the_history_and_a_missing_db_is_a_line(self):
        lines = []
        again = nauceno.run(NOW, lines.append, self.path, os.path.join(self.tmp.name, "nema-league.db"),
                            btc=_rp.btc_rows(), save=False)
        self.assertEqual(again["backfill"]["rows"], self.res["backfill"]["rows"])      # rebuilt, not doubled
        self.assertEqual(nauceno.run(NOW, lines.append, os.path.join(self.tmp.name, "nema.db")), {})
        self.assertIn("nema podataka", lines[-1])

    def test_the_live_book_books_the_real_cost(self):
        with open(os.path.join(ROOT, "veliki", "sjena.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("replay.RT_FLOOR", src)
        self.assertIsNone(nauceno.summary({}))


if __name__ == "__main__":
    unittest.main()
