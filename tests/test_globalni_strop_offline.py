"""16.11. (vlasnik, jutarnji izvještaj: "tvrdi stropovi na zadnjoj točki"): ONE global cap over EVERY automatic real buy
together (trade/executor.AUTO_HARD_CAPS): the day's realized result of every live position, fees included
(executor.day_pnl), at or under -0.5 SOL stops every automatic real buy until the next Zagreb day, whatever path or
switch (LIVE_CAPS, pravi_novac_sve, pravi_novac_izvori, pravi_novac_veliki, Grok autotrade); no automatic real stake
above 0.1 SOL; the strictest limit wins at the last check before the swap (executor.final_check); the kill switch
trade/STOP is the first check of every buy, no flag / path / override comes before it. The owner's manual buys keep
their own rules. No network: the swap, the wallet and Jupiter are fakes (tests/test_pravi_novac_sve_offline.SwitchBase).

    python3 -m unittest tests.test_globalni_strop_offline
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import SW, SwitchBase, tok  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import grokauto  # noqa: E402

LAMPORTS = executor.LAMPORTS


class Global(SwitchBase):
    def loss(self, sol):
        """Closed live positions today whose result is -sol in all (every strategy's, one global day)."""
        n = int(round(sol / 0.1))
        self.live_rows(n, reason="copy KOL x", status="closed", closed=int(self.now - 10), sol_back=0.0)

    def on(self, name):
        settings.set_flag(self.con, name, "live", settings.owner())
        settings._FLAG_CACHE.clear()

    def buy(self, reason, i, size=0.1, manual=False, cfg=None, **kw):
        return executor.buy(self.con, dict(cfg or self.cfg, mode="live"), tok(i), "T", now=self.now, reason=reason,
                            size_sol=size, manual=manual, **kw)

    # ---- the cap itself -------------------------------------------------------------------------------------------

    def test_caps_and_who_is_automatic(self):
        self.assertEqual(executor.AUTO_HARD_CAPS, {"max_sol_per_trade": 0.1, "max_loss_day": 0.5})
        self.assertTrue(executor.is_auto("copy KOL x", False))
        self.assertTrue(executor.is_auto(grokauto.SRC, True))          # Grok autotrade's manual stake: automatic
        self.assertFalse(executor.is_auto("ručno (pravi trade)", True))
        self.assertFalse(executor.is_auto("ručno: Grok odobreno (MCP)", True))   # approved by the owner's tap: his
        self.assertEqual(executor.auto_hard(self.con, 0.1, self.now), [])
        self.assertEqual([k for k, _t in executor.auto_hard(self.con, 0.11, self.now)], ["auto_stake"])

    def test_day_loss_at_half_a_sol_stops_every_automatic_path(self):
        self.loss(0.5)
        self.assertAlmostEqual(executor.day_pnl(self.con, self.now, "live"), -0.5)
        for name in (SW, settings.IZVORI, "pravi_novac_veliki"):
            self.on(name)
        paths = [("paper #7", False), ("copy KOL x", False), ("konsenzus S1", False), ("veliki: dnevni raspon", False),
                 ("oscilator: dno", False), ("momentum skok", False), (grokauto.SRC, True)]
        for i, (reason, manual) in enumerate(paths):
            r = self.buy(reason, 10 + i, manual=manual)
            self.assertEqual(r["status"], "blocked", reason)
        self.assertEqual(self.swaps, [])

    def test_grok_autotrade_is_held_where_the_owners_page_limit_is_looser(self):
        # the owner raised his own day-loss limit on the page; Grok's buy reaches the executor as a manual stake and
        # used to be held only by that (and by its own loss of Grok's positions alone)
        cfg = dict(self.cfg, max_loss_day=5.0)
        self.loss(0.6)
        why = executor.gate_buy(self.con, cfg, 0.1, self.now, True, balance=5.0, manual=True, auto=True)
        self.assertIn("globalni dnevni gubitak -0.600 SOL", why or "")
        self.assertIsNone(executor.gate_buy(self.con, cfg, 0.1, self.now, True, balance=5.0, manual=True))   # owner
        r = self.buy(grokauto.SRC, 1, manual=True, cfg=cfg)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("globalni dnevni gubitak", r["error"])
        self.assertEqual(self.swaps, [])
        r = self.buy("ručno (pravi trade)", 2, manual=True, cfg=cfg)   # the owner's own buy keeps his rules
        self.assertEqual(r["status"], "open")
        self.assertEqual(len(self.swaps), 1)

    def test_the_page_answers_grok_before_a_demo_trade_is_written(self):
        from ui import pravitrade
        self.loss(0.6)
        settings.put(self.con, "max_loss_day", 5.0, "Jure")
        with mock.patch.object(executor, "is_live", lambda cfg: True):
            self.assertIn("globalni dnevni gubitak", pravitrade._gate_now(self.con, 0.1, tok(3), src=grokauto.SRC) or "")
            self.assertIsNone(pravitrade._gate_now(self.con, 0.1, tok(3), src="ručno (pravi trade)"))

    def test_no_automatic_stake_above_a_tenth(self):
        cfg = dict(self.cfg, max_sol_per_trade=1.0, pravi_novac_veliki={"size_sol": 0.5})
        self.assertEqual(executor.veliki_caps(cfg)["size_sol"], 0.5)   # the midcap config may raise it to 0.5
        self.on("pravi_novac_veliki")
        r = self.buy("veliki: dnevni raspon", 1, size=0.5, cfg=cfg)
        self.assertEqual(r["status"], "open")
        r = self.buy(grokauto.SRC, 2, size=0.5, manual=True, cfg=cfg)   # Grok's page limit goes up to 1 SOL
        self.assertEqual(r["status"], "open")
        self.assertEqual([s["lamports"] for s in self.swaps], [int(0.1 * LAMPORTS)] * 2)
        # a direct gate call (a page, a tool) with a bigger automatic stake is a HARD refusal
        kinds = [(k, key) for k, key, _t in executor.buy_checks(self.con, cfg, 0.3, self.now, True, balance=5.0,
                                                                manual=True, auto=True)]
        self.assertIn((executor.HARD, "auto_stake"), kinds)
        # the owner's own amount is his (his limits and his confirmed override, as before)
        self.assertNotIn("auto_stake", [k for _h, k, _t in executor.buy_checks(
            self.con, cfg, 0.3, self.now, True, balance=5.0, manual=True)])

    def test_a_path_cap_stricter_than_the_global_one_still_wins(self):
        self.loss(0.3)   # veliki's own day loss is 0.3: it stops before the global 0.5
        self.on("pravi_novac_veliki")
        r = self.buy("veliki: dnevni raspon", 1)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("strop pravi_novac_veliki max_loss_day", r["error"])
        self.assertIsNone(executor.final_check(self.con, 0.1, self.now, True, True))   # the global one is not reached

    def test_the_last_check_right_before_the_swap(self):
        # a loss booked while the buy's sell check was quoting (seconds): the swap is not sent
        def slow_sell_check(*a, **k):
            self.loss(0.5)
            return None
        with mock.patch.object(executor, "sell_check", slow_sell_check):
            self.on(SW)
            r = self.buy("copy KOL x", 1)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("globalni dnevni gubitak", r["error"])
        self.assertEqual(self.swaps, [])

        def stop_appears(*a, **k):
            open(executor.STOP_FILE, "w").close()
            return None
        with mock.patch.object(executor, "sell_check", stop_appears):
            r = self.buy("ručno (pravi trade)", 2, manual=True, override="nadjačano")
        self.assertEqual((r["status"], r["error"]), ("blocked", "kill switch (trade/STOP)"))
        self.assertEqual(self.swaps, [])

    def test_next_zagreb_day_buys_again(self):
        self.loss(0.5)
        self.on(SW)
        self.assertEqual(self.buy("copy KOL x", 1)["status"], "blocked")
        tomorrow = executor._day_start(self.now) + 86400 + 60
        r = executor.buy(self.con, dict(self.cfg, mode="live"), tok(2), "T", now=tomorrow, reason="copy KOL x",
                         size_sol=0.1)
        self.assertEqual(r["status"], "open")

    # ---- the kill switch ------------------------------------------------------------------------------------------

    def test_kill_switch_is_first_for_every_path_flag_and_override(self):
        open(executor.STOP_FILE, "w").close()
        for name in (SW, settings.IZVORI, "pravi_novac_veliki"):
            self.on(name)
        cases = [("paper #7", {}), ("copy KOL x", {}), ("konsenzus S1", {}), ("veliki: dnevni raspon", {}),
                 ("oscilator: dno", {}), ("range lot 1", {"add": True}), (grokauto.SRC, {"manual": True}),
                 ("ručno (pravi trade)", {"manual": True}),
                 ("ručno (pravi trade)", {"manual": True, "override": "nadjačano", "add": True}),
                 ("copy KOL x", {"limit": {"max_px": 1.0}})]
        for i, (reason, kw) in enumerate(cases):
            r = self.buy(reason, 30 + i, **kw)
            self.assertEqual((r["status"], r["error"]), ("blocked", "kill switch (trade/STOP)"), reason)
        settings.set_flag(self.con, "pravi_novac_veliki", "off", settings.owner())   # a path's own "off" comes after
        settings._FLAG_CACHE.clear()
        r = self.buy("veliki: dnevni raspon", 50)
        self.assertEqual(r["error"], "kill switch (trade/STOP)")
        self.assertEqual(self.swaps, [])
        for live in (True, False):
            for manual in (True, False):
                for kw in ({}, {"izvori": True}, {"veliki": True}, {"auto": True}, {"override": True}):
                    first = next(executor.buy_checks(self.con, self.cfg, 0.1, self.now, live, balance=5.0,
                                                     manual=manual, **{k: v for k, v in kw.items() if k != "override"}))
                    self.assertEqual(first[:2], (executor.HARD, "stop"))
                    self.assertEqual(executor.gate_buy(self.con, self.cfg, 0.1, self.now, live, balance=5.0,
                                                       manual=manual, **kw), "kill switch (trade/STOP)")


if __name__ == "__main__":
    unittest.main()
