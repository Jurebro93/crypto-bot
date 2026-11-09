"""Pregled: the strategy card lists only strategies in profit (9.11., Jure); the losers are a count and the link."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui import pocetna  # noqa: E402


def _s(name, ret, closed=10, value=None):
    return {"key": name, "name": name, "icon": "x", "ret": ret, "value": value if value is not None else 1000 * (1 + ret),
            "closed": closed, "open": 0, "hit": 0.3, "opis": "opis", "status": ("uči", "uči", "još uči")}


class StrategyCard(unittest.TestCase):
    def test_only_profitable_strategies_are_listed(self):
        rank = [_s("KOL pozivi", 2.94), _s("Srednji", 0.088), _s("Ekipa", 0.0, closed=0), _s("Veliki", -0.004),
                _s("Insajderi", -0.43), _s("Sumnjivi", -3.775)]
        st = {"cfg": {"bankroll_usd": 1000}, "days": 8.0, "rank": rank}
        with mock.patch.object(pocetna, "strategies", return_value=st):
            html = pocetna.strategy_html()
        self.assertIn("KOL pozivi", html)
        self.assertIn("Srednji", html)
        for name in ("Ekipa", "Veliki", "Insajderi", "Sumnjivi"):
            self.assertNotIn(name, html)
        self.assertIn("Još 4 strategija je u minusu ili bez tradeova", html)
        self.assertIn("/strategije", html)

    def test_no_list_when_only_the_leader_is_positive(self):
        rank = [_s("A", 0.1), _s("B", -0.1), _s("C", -0.2)]
        st = {"cfg": {"bankroll_usd": 1000}, "days": 8.0, "rank": rank}
        with mock.patch.object(pocetna, "strategies", return_value=st):
            html = pocetna.strategy_html()
        self.assertNotIn("<ul class=ov-rank>", html)
        self.assertIn("Još 2 strategija", html)


if __name__ == "__main__":
    unittest.main()
