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
    """11.11. (Jure): "Grokovi zahtjevi koje odobrim tapom idu pod Grokove limite (0,1 SOL po tradeu, 0,3 SOL po tokenu
    i dnevno). Strop od 1 SOL vrijedi samo za kupnje koje sam pokrenem (Kupi, brza kupnja, DCA, nalozi na MC)." """
    def grok_pos(self, src, sol, token=HOPE, age=0):
        self.tc.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (token, "X", int(time.time()) - age, "live", "open", src, sol, 1000, 1000))
        self.tc.commit()

    def rules(self, sol, src=None, token=HOPE):
        with mock.patch.object(executor, "is_live", lambda cfg: True), \
                mock.patch("league.flags.mode", lambda name: "off"), mock.patch("builtins.print"):
            pravitrade._owner_buy_rules(self.lc, self.tc, token, sol, src=src)

    def setUp(self):
        super().setUp()
        settings.put(self.tc, "dca_cap_owner", True, "t")
        settings.put(self.tc, "owner_token_cap", 1.0, "t")
        settings.put(self.tc, "dca_token_cap", 0.3, "t")

    def test_grok_limits_for_autotrade_and_approved_the_owners_cap_only_for_his_own(self):
        from ui import grokauto
        from league import exitplan
        self.pos("live", 0.25)
        for src in (grokauto.SRC, exitplan.APPROVED_SRC):
            with self.assertRaises(ValueError) as e:      # 0.25 + 0.1 > 0.3 per token
                self.rules(0.1, src)
            self.assertIn("najviše 0.3 SOL po tokenu (Grokov limit)", str(e.exception))
        self.rules(0.5)                                     # his own buy: his 1 SOL per token
        other = "Othr111111111111111111111111111111111111pump"
        with self.assertRaises(ValueError) as e:            # approved, 0.15 > 0.1 per trade
            self.rules(0.15, exitplan.APPROVED_SRC, other)
        self.assertIn("najviše 0.1 SOL po kupnji (Grokov limit)", str(e.exception))
        self.rules(0.1, exitplan.APPROVED_SRC, other)       # within every Grok limit

    def test_the_day_limit_counts_autotrade_and_approved_together(self):
        from ui import grokauto
        from league import exitplan
        t2, t3 = "Tok2" + "1" * 40, "Tok3" + "1" * 40
        self.grok_pos(grokauto.SRC, 0.1, token=t2)
        self.grok_pos(exitplan.APPROVED_SRC, 0.1, token=t3)
        self.grok_pos("ručno (pravi trade)", 0.5, token=t3)          # the owner's own buy is not Grok's day
        self.grok_pos(exitplan.APPROVED_SRC, 0.1, token=t3, age=3 * 86400)   # an older day
        self.assertAlmostEqual(pravitrade.grok_day_spent(self.tc, mode="live"), 0.2)
        self.rules(0.1, exitplan.APPROVED_SRC, "Tok4" + "1" * 40)    # 0.2 + 0.1 = 0.3: still in
        self.grok_pos(exitplan.APPROVED_SRC, 0.1, token="Tok4" + "1" * 40)
        with self.assertRaises(ValueError) as e:
            self.rules(0.05, grokauto.SRC, "Tok5" + "1" * 40)
        self.assertIn("najviše 0.3 SOL na dan (Grokov limit)", str(e.exception))
        self.rules(0.5, None, "Tok5" + "1" * 40)                       # the owner's own buy: not Grok's limits

    def test_the_pravila_words(self):
        settings.put(self.tc, "owner_token_cap", 1.0, "t")
        html = pravitrade._limits(pravitrade._cfg(self.tc), True)
        self.assertIn("Vrijedi samo za kupnje koje sam pokreneš", html)
        self.assertIn("autotrade i zahtjevi koje odobriš ostaju na Grokovim limitima", html)
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


class SlChips(unittest.TestCase):
    def test_the_usual_chips_and_the_default(self):
        from ui import apterm
        self.assertEqual(apterm.sl_chips("-30%"), (20, 30, 40, 60))
        self.assertEqual(apterm.sl_chips(60), (20, 40, 60))
        self.assertEqual(apterm.sl_chips("x"), apterm.SL_CHIPS)
