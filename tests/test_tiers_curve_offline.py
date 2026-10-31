"""Bonding-curve features for the live bot (tiers/curve.py) and decision-point events (tiers/store.py), no network."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hype import evaluate  # noqa: E402
from hype import store as hstore  # noqa: E402
from learn import outcomes  # noqa: E402
from tiers import curve  # noqa: E402
from tiers import store as tstore  # noqa: E402

T0 = 1_790_000_000
DEV, CURVE, PROTO = "dev", "curve", next(iter(curve.chain.PROTOCOL))


def _rows(mint="abcpump", n_buyers=40, mayhem=False, grad_after_s=3 * 3600):
    """fetch_token-shaped rows: (mint, n, ts, slot, wallet, side, tokens, sol, price, curve_sol)."""
    rows, n = [], 0
    price = 2.8e-8
    rows.append((mint, n, T0, 1000, DEV, "buy", 3e7, -1.0, price, 1.0))  # dev buy in the create tx
    n += 1
    for i in range(n_buyers):
        ts = T0 + int(grad_after_s * (i + 1) / (n_buyers + 1))
        price *= 1.04
        rows.append((mint, n, ts, 1000 + 2 * (i + 1), f"w{i}", "buy", 2e6, -0.3, price, 1.0 + 0.3 * (i + 1)))
        n += 1
    if mayhem:
        rows.append((mint, n, T0 + 10, 1010, PROTO, "buy", 5e7, -3.0, price, 5.0))
        n += 1
    return rows


def _info(complete=True, grad=T0 + 3 * 3600):
    info = {"t_create": T0, "slot_create": 1000, "creator": DEV, "uri": None, "pages": 2, "complete": int(complete)}
    if grad:
        info["t_grad"] = grad
    return info


class CurveFeatures(unittest.TestCase):
    def fetch(self, rows, info):
        with mock.patch.object(curve.collect, "fetch_token", return_value=(info, rows)), \
                mock.patch.object(curve.chain, "credits_used", side_effect=[100, 120]):
            return curve.fetch("abcpump", meta=False)

    def test_snapshot_and_features(self):
        snap = self.fetch(_rows(), _info())
        self.assertEqual(snap["credits"], 20)
        self.assertEqual(snap["flags"], {"bundle_launch": 0, "mayhem": 0, "quote_sol": 1, "grad_min": 180.0})
        raw = snap["raw"]
        self.assertAlmostEqual(raw["age_min"], 180.0)
        self.assertEqual(raw["holders"], 41)
        self.assertAlmostEqual(raw["dev_hold_pct"], 3.0)
        f = curve.hype_features(raw)
        for k, v in f.items():
            self.assertTrue(k.startswith("krivulja_") and 0.0 <= v <= 1.0, (k, v))
        self.assertEqual(f["krivulja_bez_mayhema"], 1.0)
        self.assertAlmostEqual(f["krivulja_starost"], 0.5)  # 3 h of 6
        self.assertAlmostEqual(f["krivulja_dev_drzi"], 0.6)  # 3% of 5
        self.assertNotIn("krivulja_opis", f)  # no metadata fetched

    def test_mayhem_and_bundle_launch_flags(self):
        snap = self.fetch(_rows(mayhem=True, grad_after_s=30), _info(grad=T0 + 30))
        self.assertEqual(snap["flags"]["mayhem"], 1)
        self.assertEqual(snap["flags"]["bundle_launch"], 1)
        f = curve.hype_features(snap["raw"])
        self.assertEqual(f["krivulja_bez_mayhema"], 0.0)
        self.assertLess(f["krivulja_organski_volumen"], 1.0)
        self.assertIn("mayhem", curve.describe(snap["flags"], snap["raw"]))

    def test_non_pumpfun_token_gives_none(self):
        self.assertIsNone(self.fetch([], {"pages": 1}))

    def test_meta_features(self):
        raw = {"age_min": 10, "desc_len": 100, "has_website": 1.0, "has_telegram": 1.0}
        f = curve.hype_features(raw)
        self.assertEqual((f["krivulja_opis"], f["krivulja_web"], f["krivulja_bez_telegrama"]), (1.0, 1.0, 0.0))
        self.assertEqual(curve.hype_features({}), {})

    def test_needs_fetch(self):
        self.assertTrue(curve.needs_fetch(None))
        self.assertFalse(curve.needs_fetch({"krivulja_ts": T0, "krivulja_complete": 1}, now=T0 + 10 * 86400))
        self.assertTrue(curve.needs_fetch({"krivulja_ts": T0, "krivulja_complete": 0}, now=T0 + 7 * 3600))
        self.assertFalse(curve.needs_fetch({"krivulja_ts": T0, "krivulja_complete": 0}, now=T0 + 3600))


class StoreEvents(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "hype.db")

    def tearDown(self):
        self.dir.cleanup()

    def test_migration_adds_curve_columns(self):
        import sqlite3
        old = sqlite3.connect(self.db)
        old.execute("CREATE TABLE token_tier (token TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, last_ts INTEGER, "
                    "razina INTEGER DEFAULT 0, klasa TEXT, t0 TEXT, t0_razlog TEXT, t0_ts INTEGER, mcap REAL, liquidity REAL, "
                    "age_h REAL, score REAL, put_brzina REAL, put_skokovitost REAL, put_zadrzavanje REAL, credits INTEGER DEFAULT 0, razlog TEXT)")
        old.commit()
        old.close()
        con = tstore.connect(self.db)
        tstore.upsert(con, "x", T0, krivulja=json.dumps({"age_min": 5}), krivulja_ts=T0, mayhem=1, grad_min=12.5)
        row = tstore.get(con, "x")
        self.assertEqual((row["mayhem"], row["grad_min"], json.loads(row["krivulja"])), (1, 12.5, {"age_min": 5}))
        self.assertEqual(curve.budget_left(con, now=T0 + 100), curve.PER_DAY - 1)

    def test_crossings(self):
        self.assertEqual(tstore.crossings(None, 5e4), [])
        self.assertEqual(tstore.crossings(None, 1.5e5), ["B100000"])  # first seen just above: counts
        self.assertEqual(tstore.crossings(None, 5e5), [])  # first seen far above: missed the crossing
        self.assertEqual(tstore.crossings({"mcap": 8e4}, 1.2e5), ["B100000"])
        self.assertEqual(tstore.crossings({"mcap": 1.2e5}, 1.3e5), [])
        self.assertEqual(tstore.crossings({"mcap": 9e5}, 1.1e6), ["B1000000"])

    def test_event_rows_and_second_peak(self):
        con = tstore.connect(self.db)
        hcon = hstore.connect(self.db)
        tstore.record_event(con, "x", "B100000", 1.1e5, 1.0, 50.0, {"krivulja_starost": 0.5}, now=T0)
        tstore.record_event(con, "x", "B100000", 2e5, 2.0, 60.0, {}, now=T0 + 60)  # kept once
        con.commit()
        for i, p in enumerate((1.5, 9.0, 3.0, 2.0)):  # one wick to 9x, real second peak 3x
            hstore.snapshot(hcon, "x", p, p * 1e5, 1e4, ts=T0 + 600 * (i + 1))
        hcon.commit()
        con.commit()
        rows = outcomes.event_rows(con, "B100000", {"horizon_h": 24}, now=T0 + 2 * 86400)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["price"], rows[0]["max_ret"], rows[0]["max2_ret"], rows[0]["end_ret"]), (1.0, 8.0, 2.0, 1.0))
        self.assertEqual(rows[0]["features"], {"krivulja_starost": 0.5})
        # too fresh for the horizon: not judged yet
        self.assertEqual(outcomes.event_rows(con, "B100000", {"horizon_h": 24}, now=T0 + 3600), [])

    def test_outcomes_max2(self):
        con = hstore.connect(self.db)
        row = {"token": "y", "symbol": "Y", "name": "Y", "pair": None, "url": None, "score": 50, "price": 1.0, "mcap": 1e5,
               "liquidity": 1e4, "features": {"fresh": 1.0}, "sources": set()}
        with mock.patch("time.time", return_value=T0):
            hstore.log_signal(con, row, {"fresh": 10})
        for i, p in enumerate((1.2, 5.0, 2.0)):
            hstore.snapshot(con, "y", p, p * 1e5, 1e4, ts=T0 + 600 * (i + 1))
        con.commit()
        out = evaluate.outcomes(con, 24, now=T0 + 2 * 86400)
        self.assertEqual((out[0]["max_ret"], out[0]["max2_ret"]), (4.0, 1.0))


if __name__ == "__main__":
    unittest.main()
