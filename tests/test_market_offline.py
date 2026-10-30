"""Market volume: DefiLlama parsing into market.db, the regime score, no look-ahead, the hypothesis and the page."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market import collect, regime, store  # noqa: E402

D = 86400
NOW = 1793361600  # 2026-10-30 12:00 UTC
TODAY = NOW // D * D


def overview(days=130, hot_from=None):
    """Fake DefiLlama overview: pump.fun + LaunchLab in the breakdown, Axiom and StonkFun only as separate history.
    Launchpad volume triples from day hot_from (days ago) on."""
    protos = [
        {"name": "pump.fun", "slug": "pump.fun", "category": "Launchpad", "total24h": 100, "total7d": 7e6},
        {"name": "LaunchLab", "slug": "launchlab", "category": "Launchpad", "total24h": 10, "total7d": 7e5},
        {"name": "StonkFun", "slug": "stonkfun", "category": "Launchpad", "total24h": 5, "total7d": 6e5},
        {"name": "Tiny", "slug": "tiny", "category": "Launchpad", "total24h": 1, "total7d": 10},
        {"name": "Axiom", "slug": "axiom", "category": "Trading App", "total24h": 50, "total7d": 3e6},
        {"name": "Orca DEX", "slug": "orca-dex", "category": "Dexs", "total24h": 1000, "total7d": 7e7},
        {"name": "PumpSwap", "slug": "pumpswap", "category": "Dexs", "total24h": 200, "total7d": 1e7},
        {"name": "Some Bridge", "slug": "bridge", "category": "Bridge", "total24h": 9, "total7d": 9},
    ]
    chart = []
    for i in range(days, -1, -1):
        day = TODAY - i * D
        k = 3 if hot_from is not None and i <= hot_from else 1
        chart.append([day, {"pump.fun": 1e6 * k + i, "LaunchLab": 1e5 * k, "Orca DEX": 1e7 * (1 + 0.2 * k),
                            "PumpSwap": 2e6, "Some Bridge": 5}])
    return {"protocols": protos, "totalDataChartBreakdown": chart}


def fresh(ov):
    con = store.connect(os.path.join(tempfile.mkdtemp(), "market.db"))
    days = len(ov["totalDataChartBreakdown"])
    collect.daily(con, ov, now=NOW, fetch=lambda slug: [(TODAY - i * D, 1000.0) for i in range(days - 1, -1, -1)])
    collect.prices(con, [(TODAY - i * D + 300, 100.0 + i) for i in range(130)])
    regime.compute_all(con, now=NOW)
    return con


class Collect(unittest.TestCase):
    def test_groups_and_today_skipped(self):
        con = fresh(overview())
        y = TODAY - D
        v = dict(con.execute("SELECT slug, volume FROM daily WHERE day=?", (y,)))
        self.assertEqual(v["all:launchpad"], 1e6 + 1 + 1e5 + 1000)   # StonkFun came from the separate history
        self.assertEqual(v["all:terminal"], 1000)                      # Axiom too
        self.assertEqual(v["all:dex"], 1.2e7 + 2e6)
        self.assertNotIn("tiny", v)                                    # too small to fetch separately
        self.assertNotIn("bridge", v)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM daily WHERE day>=?", (TODAY,)).fetchone()[0], 0)

    def test_snapshot(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "market.db"))
        collect.snapshot(con, overview(), now=NOW)
        v = dict(con.execute("SELECT slug, vol24h FROM snap"))
        self.assertEqual(v["all:launchpad"], 116)
        self.assertEqual(v["all:dex"], 1200)


class Regime(unittest.TestCase):
    def test_flat_market_is_not_hot(self):
        r = regime.current(fresh(overview()))
        self.assertIsNotNone(r)
        self.assertNotEqual(r["label"], "vruće")

    def test_volume_jump_is_hot(self):
        r = regime.current(fresh(overview(hot_from=5)))
        self.assertEqual(r["label"], "vruće")
        self.assertGreater(r["features"]["launchpad_growth7d"], 0.5)

    def test_no_look_ahead(self):
        con = fresh(overview(hot_from=5))
        before = regime.at(TODAY - 6 * D + 3600, con)      # trade opened 6 days ago: jump not known yet
        self.assertEqual(before["day"], TODAY - 7 * D)
        self.assertNotEqual(before["label"], "vruće")

    def test_not_enough_history(self):
        self.assertIsNone(regime.current(fresh(overview(days=40))))

    def test_hypothesis_moves_together(self):
        con = fresh(overview(hot_from=5))
        h = regime.hypothesis(con)
        self.assertGreater(h["same_day"], 0.5)
        self.assertIn("zajedno", regime.verdict(h))


class Page(unittest.TestCase):
    def test_renders(self):
        con = fresh(overview(hot_from=5))
        path = con.execute("PRAGMA database_list").fetchone()[2]
        con.commit()
        con.close()
        store.DB = path
        from ui import market
        title, body = market.page({})
        self.assertIn("pump.fun (bonding curve)", body)
        self.assertIn("LaunchLab (bonk.fun / letsbonk)", body)
        self.assertIn("VRUĆE", body)
        self.assertIn("<svg", body)


if __name__ == "__main__":
    unittest.main()
