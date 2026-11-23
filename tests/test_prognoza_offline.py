"""23.11. (production right after the risk-off deploy: "veliki naučeno ulaz [siroko] [makro risk-off: pravi novac bi
stajao] arc 0.1 SOL na MC $27.9M: prognoza +4071.1% neto (prag +1%)", while "siroko" pays at most +20 % net):
veliki/nauceno + veliki/ucenik, offline:

  - the model's sums take a row's result clipped to what its exit profile can pay (ret_bounds: -100 % .. the target
    net of cost); a handful of impossible results (a spiky fill quote) in a rare cell can no longer carry a forecast
  - predict_checked: the forecast never exceeds the profile's target; a raw sum outside the bounds is "izvan raspona
    učenja", with the fact that carries it; a fact value never seen adds nothing
  - the walk-forward scores clipped results too, and says how many it clipped
  - the risk-off exclusion of 23.11. leaves out of the VERDICT only: the model is fitted on exactly the same rows
  - the učenik: an entry on an out-of-range forecast is stored (veliki_ucenik.raw / izvan), said in the line, kept
    out of the verdict and never gets a real twin

    python3 -m unittest tests.test_prognoza_offline
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tests.test_ucenik_offline as _u  # noqa: E402  (the module, so its own tests are not collected here)
from tests.test_pravi_novac_sve_offline import tok  # noqa: E402
from veliki import live, nauceno, sjena, ucenik  # noqa: E402

D = 86400


def row(token, day, k, prof, ret, closed=None, **f):
    ts = day * D + 3600 + k
    r = {"token": token, "opened_ts": ts, "closed_ts": ts + 600 if closed is None else closed, "profil": prof,
         "ret": ret, "band": "dno", "calm": 1, "zone_ok": 1, "btc": "normalno", "makro": "neutral", "dip": None,
         "oprez": 0, "grok": None, "width": 0.3}
    r.update(f)
    return r


def raw_sum(rows, prof, f, shrink=nauceno.SHRINK):
    """The pre-23.11. forecast: the same sums WITHOUT clipping (what production computed)."""
    tot, cell = [0, 0.0], {}
    for r in rows:
        if r["profil"] != prof:
            continue
        tot[0] += 1
        tot[1] += r["ret"]
        for k, v in nauceno.facts(r).items():
            c = cell.setdefault((k, v), [0, 0.0])
            c[0] += 1
            c[1] += r["ret"]
    b = tot[1] / tot[0]
    return b + sum((cell[(k, v)][1] / cell[(k, v)][0] - b) * cell[(k, v)][0] / (cell[(k, v)][0] + shrink)
                   for k, v in f.items() if v != "?" and (k, v) in cell)


def poisoned():
    """2000 ordinary siroko rows (-2 %) and 30 rows in risk-off whose fill quote was wrong by ~600x (+60 000 %)."""
    rows = [row(f"T{i % 50}", 20000 + i % 20, i, "siroko", -0.02) for i in range(2000)]
    rows += [row(f"G{i}", 20020, i, "siroko", 600.0, makro="risk_off") for i in range(30)]
    return rows


class Bounds(unittest.TestCase):
    def test_ret_bounds_are_the_profiles_targets(self):
        self.assertEqual(nauceno.ret_bounds("siroko"), (-1.0, 0.20))
        self.assertEqual(nauceno.ret_bounds("pravilo"), (-1.0, 0.10))
        self.assertEqual(nauceno.ret_bounds("skalp"), (-1.0, 0.03))

    def test_a_poisoned_cell_reproduces_the_production_number_and_is_now_bounded(self):
        rows = poisoned()
        f = nauceno.facts({**rows[-1], "opened_ts": 20030 * D})
        self.assertGreater(raw_sum(rows, "siroko", f), 40.0)            # the old code: "prognoza +4000 %"
        m = nauceno.Model()
        for r in rows:
            m.add(r)
        self.assertEqual(m.clipped, 30)
        self.assertLessEqual(m.predict("siroko", f), 0.20 + 1e-12)      # the 30 impossible results no longer carry it
        pc = nauceno.predict_checked(m, f)
        self.assertLessEqual(pc["pred"], 0.20)
        self.assertIn("makro risk_off", pc["doprinos"])                 # the diagnosis names the cell that carries it

    def test_predict_checked_clips_and_marks(self):
        m = nauceno.Model(shrink=0)
        m.tot = {"siroko": [10, 10 * 0.15]}
        m.cell = {("siroko", "band", "dno"): [5, 5 * 0.90], ("siroko", "makro", "risk_off"): [5, 5 * 0.90]}
        pc = nauceno.predict_checked(m, {"band": "dno", "makro": "risk_off", "grok": "kupi"})
        self.assertEqual(pc["profil"], "siroko")
        self.assertAlmostEqual(pc["pred"], 0.20)                        # never above what the exit pays
        self.assertAlmostEqual(pc["raw"], 0.15 + 0.75 + 0.75)
        self.assertIn("iznad cilja profila +20.0%", pc["izvan"])
        self.assertIn("Grok kupi", pc["nevideno"])                      # said; it added nothing (effect 0)
        ok = nauceno.predict_checked(m, {"band": "vrh"})
        self.assertIsNone(ok["izvan"])
        self.assertAlmostEqual(ok["pred"], 0.15)
        self.assertIsNone(nauceno.predict_checked(nauceno.Model(), {"band": "dno"}))

    def test_walk_forward_scores_clipped_results(self):
        rows = [row(f"T{k}", 20000 + d, k, "siroko", 0.05) for d in range(9) for k in range(4)]
        rows += [row("X", 20008, 99, "siroko", 500.0)]
        res = nauceno.learn(rows, min_train_days=1, thr=-1.0)
        self.assertEqual(res["izvan_cilja"], 1)
        self.assertLessEqual(max(x for x in [res["picked"]["ev"], res["all"]["ev"]]), 0.20)
        self.assertIn("1 redaka s rezultatom izvan onoga što izlaz može platiti",
                      nauceno.line({**res, "ts": 1, "backfill": {}}))


class FitUnchanged(unittest.TestCase):
    def test_risk_off_rows_are_out_of_the_verdict_not_out_of_the_fit(self):
        rows = []
        for d in range(10):
            for k in range(6):
                mk = "risk_off" if k % 3 == 0 else "neutral"
                rows.append(row(f"T{k}", 20000 + d, k, "pravilo", 0.03 if mk == "neutral" else -0.05, makro=mk))
                rows.append(row(f"T{k}", 20000 + d, k + 10, "siroko", -0.01, btc="slobodan_pad" if k == 1 else "normalno"))
        m = nauceno.Model()
        nauceno.learn(rows, model=m)
        plain = nauceno.Model()
        for r in rows:                                                  # every closed row, gated or not
            plain.add(r)
        self.assertEqual(m.tot, plain.tot)
        self.assertEqual(m.cell, plain.cell)
        self.assertIn(("pravilo", "makro", "risk_off"), m.cell)


class Ucenik(_u.Fix):
    def test_out_of_range_entry_marked_stored_and_out_of_the_verdict(self):
        # a stored model whose siroko cell "band" carries an absurd mean (as production): the forecast is clipped
        m = nauceno.Model(shrink=0)
        m.tot = {"skalp": [100, -2.0], "kratko": [100, -2.0], "uski": [100, -2.0], "pravilo": [100, -2.0],
                 "siroko": [100, 100 * 0.05]}
        band = sjena.band_of(self.px, self.z)[0]
        m.cell = {("siroko", "band", band): [10, 10 * 40.0]}
        self._store(m)
        out = self.tick()
        r = self.rows()
        self.assertEqual(len(r), 1, out)
        self.assertEqual(r[0]["varijanta"], "nauceno:siroko")
        line = next(x for x in out if x.startswith("veliki naučeno ulaz [siroko]"))
        self.assertIn("[izvan raspona učenja: sirova prognoza", line)
        self.assertIn("prognoza +20.0% neto", line)                    # clipped to what siroko pays
        self.assertIn("najveći doprinos: mjesto u zoni", line)
        pred, raw, izv = self.lg.execute("SELECT pred, raw, izvan FROM veliki_ucenik WHERE id=?", (r[0]["id"],)).fetchone()
        self.assertAlmostEqual(pred, 0.20)
        self.assertGreater(raw, 30)
        self.assertTrue(izv)
        # closed with a result: never in the verdict, said apart
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=0.2, pnl_usd=3.0 WHERE id=?",
                        (int(self.now) + 60, r[0]["id"]))
        self.lg.commit()
        s = ucenik.stats(self.lg, self.now + 120)
        self.assertEqual(s["closed"]["n"], 0)
        self.assertEqual(s["izvan_ucenja"]["n"], 1)
        self.assertIn("prognoza izvan raspona učenja (izvan presude): n=1", ucenik.line(self.lg, self.now + 120))

    def test_out_of_range_forecast_never_gets_a_real_twin(self):
        out = []
        e = {"k": {"symbol": "MID", "px": 1e-4, "rt": 0.03}, "prof": "siroko", "pred": 0.2, "tp_px": 1.2e-4,
             "stop_px": 0.8e-4, "demo_id": 1, "model_ts": int(self.now), "facts": {}, "izvan": "sirova prognoza +4000%"}
        live.ensure(self.lg)
        live._ST["real_gate"] = None
        rid = ucenik._enter_real(self.lg, out, set(), tok(100), self.mk([tok(100)], self.px)[tok(100)], self.now, 150.0,
                                 self.z, {}, {"state": "normalno"}, {}, {tok(100)}, None, e)
        self.assertIsNone(rid)
        self.assertTrue(any("izvan raspona učenja" in x for x in out), out)

    def _store(self, m):
        import json
        con = nauceno.connect(self.ndb)
        con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)",
                    (nauceno.KV_MODEL, json.dumps(m.dump(int(self.now - 3600), 5000, 30))))
        con.commit()
        con.close()
        nauceno._MODEL.clear()


if __name__ == "__main__":
    unittest.main()
