"""Pregled: the strategy card lists only strategies in profit (9.11., Jure); the losers are a count and the link."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui import pocetna  # noqa: E402


def _s(name, ret, closed=10, value=None, real=None, best=None):
    value = value if value is not None else 1000 * (1 + ret)
    real = real if real is not None else value
    total = value - 1000
    best = best if best is not None else max(total, 0) / 2
    return {"key": name, "name": name, "icon": "x", "ret": ret, "value": value, "closed": closed, "open": 0,
            "hit": 0.3, "p15": 0.1, "opis": "opis", "status": ("uci", "uči", "još uči"),
            "robust": {"total": total, "best": best, "no_best": total - best, "no_top5": total - best, "no_best_token": total - best,
                       "best_share": None, "concentrated": total > 0 and total - best <= 0, "n": closed},
            "portfolio": {"value": real, "cash_low": 0, "taken": closed, "skipped": 0}}


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
        self.assertIn("<dialog id=strat-info>", html)          # the explanation pop-up
        self.assertIn("Što se mjeri", html)
        self.assertIn("Zaključak za x KOL pozivi", html)

    def test_real_account_not_the_borrowing_ledger(self):
        # the research ledger says -377 % (bought below $0); a real $1,000 could at most go to ~$0: rank and show the latter
        rank = [_s("Sumnjivi", -3.775, closed=500, real=120.0), _s("KOL pozivi", 2.94, closed=104, real=3944.0, best=3524.0),
                _s("kontrola", -0.5, closed=180, real=480.0)]
        rank[2]["key"] = "kontrola"
        st = {"cfg": {"bankroll_usd": 1000}, "days": 8.0, "rank": rank}
        with mock.patch.object(pocetna, "strategies", return_value=st):
            html = pocetna.strategy_html()
        self.assertIn("KOL pozivi", html.split("<ul")[0] if "<ul" in html else html)   # leader by real value
        self.assertNotIn("-377", html)
        self.assertIn("Bez najboljeg tradea", html)                 # concentrated: one trade carries the plus
        self.assertIn("Rezultat ovisi o jednom tradeu", html)
        self.assertIn("Nasumični ulaz (kontrola)", html)
        self.assertNotIn("kontrola</span>", html)                   # the control is a yardstick, not a contender

    def test_no_list_when_only_the_leader_is_positive(self):
        rank = [_s("A", 0.1), _s("B", -0.1), _s("C", -0.2)]
        st = {"cfg": {"bankroll_usd": 1000}, "days": 8.0, "rank": rank}
        with mock.patch.object(pocetna, "strategies", return_value=st):
            html = pocetna.strategy_html()
        self.assertNotIn("<ul class=ov-rank>", html)
        self.assertIn("Još 2 strategija", html)


if __name__ == "__main__":
    unittest.main()
