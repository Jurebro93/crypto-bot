"""11.11. (Jure: "exit_plan_live: DA, svaka live pozicija (autotrade i odobreni tradeovi) mora imati aktivan exit
plan; paper i dalje simuliran"): approved MCP buys are covered too, a live Grok position without a plan gets its own
TP / SL as a default plan, and the owner order may set an owner switch to live (only an owner switch)."""
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import auto, exitplan, store as lstore  # noqa: E402
from trade import settings  # noqa: E402
from ui import assistnotes  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base as TradeBase, MINT  # noqa: E402

LU = settings.LEAGUE_USER


class ExitLive(TradeBase):
    def setUp(self):
        super().setUp()
        exitplan._LAST.clear()
        exitplan.ensure(self.lg)
        settings.put(self.con, "sl_default", 30)
        p = mock.patch.object(exitplan, "paused", lambda: False)
        p.start()
        self.addCleanup(p.stop)
        from ui import grokauto
        self.grok = grokauto
        grokauto.set_on(self.con, False, "Jure")

    def tearDown(self):
        settings._FLAG_CACHE.clear()
        super().tearDown()

    def mode(self, m, name):
        settings.put(self.con, f"flag:{name}", {"mode": m, "since": int(time.time())})
        settings._FLAG_CACHE.clear()

    def lot(self, src):
        tid = lstore.buy(self.lg, LU, MINT, "GTA", 30, 1.0, 100_000, src, None, 50_000.0, allow_open=True)
        auto.set_auto(self.lg, LU, tid, "tpsl", "+15%", "-30%")
        return tid

    def test_approved_buys_are_covered_without_autotrade(self):
        self.mode("live", "exit_plan_live")
        self.lot(exitplan.APPROVED_SRC)
        lots = exitplan._lots(self.lg, LU, MINT)
        self.assertTrue(exitplan.grok_live(LU, lots))                      # autotrade is off: approval is enough
        self.lot("Grok auto (MCP)")                                        # mixed with an autotrade lot
        lots = exitplan._lots(self.lg, LU, MINT)
        self.assertFalse(exitplan.grok_live(LU, lots))                     # ... then the autotrade switch counts
        self.grok.set_on(self.con, True, "Jure")
        self.assertTrue(exitplan.grok_live(LU, lots))
        self.lot("ručno (pravi trade)")                                    # the owner's own buy: not Grok's
        self.assertFalse(exitplan.grok_live(LU, exitplan._lots(self.lg, LU, MINT)))

    def test_a_live_position_without_a_plan_gets_its_own_tp_sl(self):
        self.lot(exitplan.APPROVED_SRC)
        self.mode("off", "exit_plan_live")
        self.assertEqual(exitplan.ensure_live_plans(self.lg, log=lambda s: None), [])   # switch off: nothing
        self.mode("live", "exit_plan_live")
        self.assertEqual(exitplan.ensure_live_plans(self.lg, log=lambda s: None), [MINT])
        p = exitplan.active(self.lg, MINT)
        self.assertEqual(p["client"], exitplan.DEFAULT_CLIENT)
        self.assertEqual(p["plan"]["take_profits"][0]["v"], 15.0)
        self.assertEqual(p["plan"]["stop"]["v"], -30.0)
        self.assertEqual(p["plan"]["accounts"], [LU])
        self.assertEqual(exitplan.ensure_live_plans(self.lg, log=lambda s: None), [])   # once: the plan exists
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), {MINT})
        done = exitplan.run_once(self.lg, lambda toks: {t: (0.6, 100_000.0, None, 30_000.0) for t in toks}, time.time())
        self.assertEqual([(d[0], d[2]) for d in done], [(LU, "stop")])     # executes on the real account

    def test_owner_order_sets_only_an_owner_switch_live(self):
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", (("exit_plan_live", "live", "t"),
                                                                  ("momentum_scalp", "live", "t"))):
            done = assistnotes.owner_flag_orders(self.con)
        self.assertEqual(done, ["zastavica exit_plan_live: off → live"])
        self.assertEqual(settings.flag_state(self.con)["momentum_scalp"]["mode"], "off")


if __name__ == "__main__":
    unittest.main()
