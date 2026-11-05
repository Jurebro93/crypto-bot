"""5.11.: BTC/ETH makro režim (market/makro.py): states, score, as-of lookup, demo gate, hype feature."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market import makro, store  # noqa: E402

D = 86400
NOW = 1_800_000_000 // D * D + 12 * 3600


def _series(now, path):
    """[(day, usd)] 40 days ending yesterday following a relative path list (multipliers per day)."""
    out, px = [], 100.0
    for i, m in enumerate(path):
        px *= m
        out.append((now - (len(path) - i) * D, px))
    return out


class States(unittest.TestCase):
    def test_each_state(self):
        cfg = makro.DEFAULT
        up_then_flat = [1.01] * 25 + [1.0] * 15                       # +28 % over 30 d, flat 5 d, near the high
        self.assertEqual(makro._state(_series(NOW, up_then_flat), cfg)[0], "konsolidacija_rasta")
        rising = [1.0] * 30 + [1.01] * 10                              # +10 % last 7 d, above the 30 d average
        self.assertEqual(makro._state(_series(NOW, rising), cfg)[0], "raste")
        falling = [1.0] * 33 + [0.99] * 7                              # -7 % in 7 d
        self.assertEqual(makro._state(_series(NOW, falling), cfg)[0], "pada")
        down_flat = [0.99] * 25 + [1.0] * 15                           # -22 % over 30 d, flat since
        self.assertEqual(makro._state(_series(NOW, down_flat), cfg)[0], "konsolidacija_pada")
        self.assertEqual(makro._state(_series(NOW, [1.0] * 40), cfg)[0], "neutralno")
        self.assertEqual(makro._state(_series(NOW, [1.0] * 40), cfg, drop4h=-0.04)[0], "pada")   # sudden 4 h drop
        self.assertEqual(makro._state(_series(NOW, [1.0] * 10), cfg)[0], None)                     # too little history

    def test_collect_score_gate_and_feature(self):
        path = os.path.join(tempfile.mkdtemp(), "market.db")
        con = store.connect(path)
        con.executemany("INSERT INTO btc VALUES (?,?)", _series(NOW, [1.01] * 25 + [1.0] * 15))
        eth = _series(NOW, [1.0] * 33 + [0.99] * 7)
        hourly = [(NOW - h * 3600, 100.0) for h in range(5, -1, -1)]
        r = makro.collect(con, NOW, eth=eth, btc_h=hourly)
        self.assertEqual((r["btc"]["state"], r["eth"]["state"]), ("konsolidacija_rasta", "pada"))
        self.assertAlmostEqual(r["score"], 0.6 * 1.0 + 0.4 * 0.0)
        con.close()
        with mock.patch.object(store, "DB", path):
            self.assertAlmostEqual(makro.feature(NOW + 60), 0.6)
            self.assertFalse(makro.falling(NOW + 60))                      # BTC consolidating: entries allowed
            self.assertIsNone(makro.at(NOW - 2 * 3600))                    # nothing known before the first row
            self.assertIn("vrijeme za altove", makro.line(NOW + 60))
        con = store.connect(path)
        crash = [(NOW + 3600 - h * 3600, 100.0 if h else 96.0) for h in range(5, -1, -1)]
        r2 = makro.collect(con, NOW + 3600, eth=eth, btc_h=crash)
        self.assertEqual(r2["btc"]["state"], "pada")
        con.close()
        with mock.patch.object(store, "DB", path):
            self.assertTrue(makro.falling(NOW + 3600 + 60))
            from paper import rules
            why = rules.gate("T", 1.0, 50000, 200000, None, None, {"gate": {"enabled": True, "min_mcap": 30000, "min_liq": 10000, "max_liq_mcap": 0.8}})
            self.assertIn("BTC pada", why or "")


if __name__ == "__main__":
    unittest.main()
