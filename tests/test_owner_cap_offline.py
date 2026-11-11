"""11.11. (Jure: "u poziciji ima 0,3, htio sam kupiti 0,1 = 0,4, a piše 0,45 … promijeni maksimalnu poziciju tokenu na
1 sol"): the owner's per-token cap counts only the account the buy goes to and only what is still held, and has its
own key (owner_token_cap, ordered once to 1 SOL) apart from the Autopilot's copy cap dca_token_cap."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade import executor, settings  # noqa: E402
from ui import assistnotes, pravitrade  # noqa: E402

HOPE = "Hope111111111111111111111111111111111111pump"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tc = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        self.addCleanup(self.tc.close)
        self.lc = sqlite3.connect(os.path.join(self.tmp.name, "league.db"))
        self.addCleanup(self.lc.close)

    def pos(self, mode, sol, status="open", qty_raw=1000, qty_left=1000, token=HOPE, age=0):
        self.tc.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, sol_in, qty_raw, qty_left) "
                        "VALUES (?,?,?,?,?,?,?,?)", (token, "Hope", int(time.time()) - age, mode, status, sol, qty_raw,
                                                     qty_left))
        self.tc.commit()


class Held(Base):
    def test_only_this_account_and_only_what_is_held(self):
        self.pos("live", 0.15)
        self.pos("live", 0.15)
        self.pos("live", 0.10, qty_left=500)          # half sold: 0.05 still in
        self.pos("live", 0.10, status="pending", qty_left=0)   # not filled yet: in full
        self.pos("dry", 0.05)                          # the demo account's lot
        self.pos("live", 0.20, status="closed", qty_left=0)
        self.pos("live", 0.30, status="pending", qty_left=0, age=3600)   # never filled: holds nothing
        self.pos("live", 0.50, token="Other1111111111111111111111111111111111pump")
        self.assertAlmostEqual(pravitrade.held_sol(self.tc, HOPE, "live"), 0.45)
        self.assertAlmostEqual(pravitrade.held_sol(self.tc, HOPE, "dry"), 0.05)

    def test_the_owners_dca_passes_under_his_cap(self):
        self.pos("live", 0.15)
        self.pos("live", 0.15)
        self.pos("dry", 0.05)                          # used to be counted: 0.35 + 0.1 = 0.45 > 0.4
        settings.put(self.tc, "dca_cap_owner", True, "t")
        settings.put(self.tc, "owner_token_cap", 0.4, "t")
        settings.put(self.tc, "dca_token_cap", 0.3, "t")   # the Autopilot's copy cap is not the owner's
        with mock.patch.object(executor, "is_live", lambda cfg: True), \
                mock.patch("league.flags.mode", lambda name: "off"):
            pravitrade._owner_buy_rules(self.lc, self.tc, HOPE, 0.1)      # 0.3 + 0.1 = 0.4: passes
            with self.assertRaises(ValueError) as e:
                pravitrade._owner_buy_rules(self.lc, self.tc, HOPE, 0.15)
        self.assertIn("u tokenu bi bilo 0.450 SOL (otvoreno 0.300 + 0.15), najviše 0.4 SOL po tokenu", str(e.exception))


class GrokAuto(Base):
    def test_grok_autotrade_keeps_the_autopilot_cap(self):
        from ui import grokauto
        from league import exitplan
        self.pos("live", 0.25)
        settings.put(self.tc, "dca_cap_owner", True, "t")
        settings.put(self.tc, "owner_token_cap", 1.0, "t")
        settings.put(self.tc, "dca_token_cap", 0.3, "t")
        with mock.patch.object(executor, "is_live", lambda cfg: True), \
                mock.patch("league.flags.mode", lambda name: "off"), mock.patch("builtins.print"):
            with self.assertRaises(ValueError) as e:      # 0.25 + 0.1 > 0.3: Grok's own buy stops
                pravitrade._owner_buy_rules(self.lc, self.tc, HOPE, 0.1, src=grokauto.SRC)
            self.assertIn("Grok autotrade: strop po tokenu 0.3 SOL", str(e.exception))
            pravitrade._owner_buy_rules(self.lc, self.tc, HOPE, 0.1, src=exitplan.APPROVED_SRC)   # approved: owner's
            pravitrade._owner_buy_rules(self.lc, self.tc, HOPE, 0.5)                             # manual: owner's

    def test_the_pravila_words(self):
        settings.put(self.tc, "owner_token_cap", 1.0, "t")
        html = pravitrade._limits(pravitrade._cfg(self.tc), True)
        self.assertIn("Ne vrijedi za Grok autotrade", html)
        self.assertIn("0,1 SOL po kupnji, 0,3 SOL na dan, 3 otvorene, dnevni gubitak 0,15 SOL", html)


class Reclaim(unittest.TestCase):
    def test_reclaim_needs_plus_three_percent(self):
        from rangedca import gate
        ok, why, _ = gate.reclaim_proof_ok([0.02] * 25)
        self.assertFalse(ok)
        self.assertIn("treba barem +3 %", why)
        self.assertTrue(gate.reclaim_proof_ok([0.035] * 25)[0])
        self.assertFalse(gate.reclaim_proof_ok([0.05] * 19)[0])


class Order(Base):
    def test_the_order_sets_one_sol_once_and_keeps_the_autopilot_cap(self):
        settings.put(self.tc, "dca_token_cap", 0.3, "t")
        with mock.patch("builtins.print"):
            done = assistnotes.owner_setting_orders(self.tc)
        self.assertEqual(done, ["postavka owner_token_cap: 0.3 → 1.0"])
        raw = settings.raw(self.tc)
        self.assertEqual((raw["owner_token_cap"], raw["dca_token_cap"]), (1.0, 0.3))
        self.assertEqual(settings.merged({"size_sol": 0.1}, self.tc)["owner_token_cap"], 1.0)   # what the panel shows
        settings.put(self.tc, "owner_token_cap", 0.8, "Jure")           # the owner changes it under Pravila
        self.assertEqual(assistnotes.owner_setting_orders(self.tc), [])    # once: never back to 1
        self.assertEqual(settings.raw(self.tc)["owner_token_cap"], 0.8)


if __name__ == "__main__":
    unittest.main()
