"""19.11. (vlasnik: "Autopilot kupovinu s pravim novcem isključi, ali želim da se na autopilot stranici dok je pravi
novac isključen radi što više demo tradeova"): the pause of every AUTOMATIC real-money buy.

His order runs once (trade/settings.pauza_order_1911): the five real-money switches go off and the pause goes on. While
it is on the mirror refuses every automatic buy of the real account (also a copy WITH a demo proof and with
pravi_novac_sve forced back on behind his back), trade/executor refuses every automatic real buy, exits and the
owner's own manual buy go on, and only his own tap of a real-money switch ends it. No network: fakes.

    python3 -m unittest tests.test_pauza_1911_offline
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_trade  # noqa: E402
from league import copy  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, SwitchBase, tok  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import assistnotes  # noqa: E402


class Order(SwitchBase):
    def test_once_five_switches_off_and_the_pause_on(self):
        for name in (settings.VEL_SWITCH, settings.SWITCH_ALL):
            settings.set_flag(self.con, name, "live", "Jure")
        self.assertIsNone(settings.pauza(self.con))
        done = settings.pauza_order_1911(self.con, now=self.now)
        self.assertEqual(len(done), 5)
        self.assertIn("pravi_novac_veliki: live → off", done)
        self.assertIn("pravi_novac_sve: live → off", done)
        self.assertIn("pravi_novac_nauceno: već off", done)
        st = settings.flag_state(self.con)
        self.assertEqual({st[n]["mode"] for n in settings.REAL_SWITCHES}, {"off"})
        self.assertTrue(settings.pauza(self.con)["on"])
        self.assertEqual(settings.pauza_order_1911(self.con), [])          # never twice
        line = settings.pauza_order_line(done)
        self.assertIn("ISKLJUČENE", line)
        self.assertIn("zadržavaju izlaze", line)

    def test_it_is_not_replayed_after_the_owner_turned_real_money_back_on(self):
        settings.pauza_order_1911(self.con, now=self.now)
        with self.assertRaises(ValueError):                                # nobody but the owner
            settings.set_flag(self.con, settings.VEL_SWITCH, "live", "grok")
        self.assertTrue(settings.pauza(self.con))
        settings.set_flag(self.con, settings.VEL_SWITCH, "live", "Jure")   # his own tap ends the pause
        self.assertIsNone(settings.pauza(self.con))
        self.assertEqual(settings.pauza_order_1911(self.con), [])
        self.assertEqual(settings.flag_state(self.con)[settings.VEL_SWITCH]["mode"], "live")
        self.assertIsNone(settings.pauza(self.con))

    def test_a_non_real_switch_does_not_end_it(self):
        settings.pauza_order_1911(self.con, now=self.now)
        settings.set_flag(self.con, settings.KRITICAR, "off", "Jure")
        settings.set_flag(self.con, settings.KRITICAR, "live", "Jure")
        self.assertTrue(settings.pauza(self.con))

    def test_the_page_process_logs_and_records_it(self):
        settings.set_flag(self.con, settings.VEL_SWITCH, "live", "Jure")
        with mock.patch("builtins.print") as pr:
            done = assistnotes.owner_pauza_1911(self.con, now=self.now)
        self.assertTrue(done)
        text = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("nalog vlasnika 19.11. izvršen", text)
        log = settings.raw(self.con).get("applied_log") or []
        self.assertTrue(any("pravi_novac_veliki" in str(x) for x in log))
        with mock.patch("builtins.print") as pr:
            self.assertEqual(assistnotes.owner_pauza_1911(self.con), [])
        pr.assert_not_called()

    def test_the_order_of_1811_is_cancelled_by_it(self):
        settings.pauza_order_1911(self.con, now=self.now)
        good = {"ts": 1, "purge": True}
        with mock.patch.object(assistnotes, "nauceno_real_test", lambda r: (True, "n=99")), \
                mock.patch.object(assistnotes, "NAUCENO_REAL_AUTO", True):
            self.assertTrue(assistnotes.owner_nauceno_real(self.con, result=good))
        self.assertEqual(settings.flag_state(self.con)[settings.NAUCENO_SWITCH]["mode"], "off")
        self.assertEqual(settings.raw(self.con)[assistnotes.NAUCENO_REAL_KEY]["ishod"], "ponisteno_pauzom_1911")
        self.assertTrue(settings.pauza(self.con))

    def test_a_database_without_settings_is_not_paused_and_never_raises(self):
        import sqlite3
        c = sqlite3.connect(":memory:")
        self.assertIsNone(settings.pauza(c))
        self.assertEqual(settings.pauza_order_1911(c), [])


class Buys(SwitchBase):
    def pause(self):
        settings.pauza_order_1911(self.con, now=self.now)
        settings._FLAG_CACHE.clear()

    def test_the_mirror_refuses_an_automatic_buy_even_with_a_switch_forced_on(self):
        self.pause()
        # the switch written behind the owner's back (not through set_flag): the pause still holds
        settings.put(self.con, f"flag:{settings.SWITCH_ALL}", {"mode": "live", "since": int(self.now), "who": "x"})
        settings._FLAG_CACHE.clear()
        fid = copy.follow(self.lg, LU, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-30%")
        self.demo(tok(40), "copy KOL ansem", follow_id=fid)
        self.demo(tok(41), "momentum scalp")
        self.mirror()
        for t in (tok(40), tok(41)):
            self.assertEqual(self.pos(t)[0], "blocked")
            self.assertIn("pravi novac je pauziran", self.pos(t)[2])
        self.assertEqual(self.swaps, [])

    def test_not_paused_the_same_copy_buys(self):
        self.switch(True)
        fid = copy.follow(self.lg, LU, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-30%")
        self.demo(tok(42), "copy KOL ansem", follow_id=fid)
        self.mirror()
        self.assertEqual(self.pos(tok(42))[:2], ("open", "live"))

    def test_the_executor_refuses_every_automatic_real_buy_and_says_why(self):
        self.pause()
        checks = list(executor.buy_checks(self.con, self.cfg, 0.1, self.now, True, balance=5.0, token=tok(43)))
        self.assertTrue(any(k == "pauza" and kind == executor.HARD for kind, k, _t in checks), checks)
        self.assertIn("pravi novac je pauziran", executor.final_check(self.con, 0.1, self.now, True, True))
        r = executor.buy(self.con, self.cfg, tok(43), "A", now=self.now, size_sol=0.1, reason="copy KOL x")
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(self.swaps, [])
        # a demo (not live) check is never held by it
        self.assertIsNone(executor.final_check(self.con, 0.1, self.now, False, True))

    def test_the_owners_manual_buy_passes(self):
        self.pause()
        self.assertEqual(list(executor.buy_checks(self.con, self.cfg, 0.1, self.now, True, balance=5.0, token=tok(44),
                                                  manual=True)), [])
        tid = self.demo(tok(45), "ručno (pravi trade)", mcap=None)
        cfg = {**self.cfg, "manual_size": {str(tid): 0.05}}
        run_trade.follow_league_once(self.con, cfg, since=0, now=self.now, quiet=True)
        self.assertEqual(self.pos(tok(45))[:2], ("open", "live"))

    def test_an_open_real_position_is_still_sold_when_its_demo_lot_closes(self):
        self.switch(True)
        fid = copy.follow(self.lg, LU, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-30%")
        tid = self.demo(tok(46), "copy KOL ansem", follow_id=fid)
        self.mirror()
        self.assertEqual(self.pos(tok(46))[:2], ("open", "live"))
        self.pause()
        sold = []
        real_sell = executor.sell

        def sell(con, cfg, pos_id, frac, **kw):
            sold.append((pos_id, frac, kw.get("close")))
            return {"status": "ok", "amount_out": 90_000_000}
        from league import store
        store.sell(self.lg, LU, tid, 1.0, 1e-4, "demo izlaz") if hasattr(store, "sell") else None
        with mock.patch.object(executor, "sell", sell):
            self.mirror()
        self.assertTrue(sold, "the exit of an open real position must go on while buying is paused")
        self.assertIs(real_sell, executor.sell)


class Shown(SwitchBase):
    def test_the_state_board_and_the_autopilot_row_say_it(self):
        from stanja import ploca
        from ui import apjed
        settings.pauza_order_1911(self.con, now=self.now)
        text = "\n".join(ploca.text(ploca.now(self.now, trade_db=settings.DB)))
        self.assertIn("pauza kupnji pravim novcem (nalog vlasnika 19.11.)", text)
        ns = apjed.novac_state(self.con, self.cfg, self.now)
        self.assertTrue(ns["pauza"])
        html = apjed._novac_row(ns, True)
        self.assertIn("Pauzirano tvojim nalogom 19.11.", html)
        settings.set_flag(self.con, settings.VEL_SWITCH, "live", "Jure")
        ns = apjed.novac_state(self.con, self.cfg, self.now)
        self.assertFalse(ns["pauza"])
        self.assertNotIn("Pauzirano", apjed._novac_row(ns, True))


if __name__ == "__main__":
    unittest.main()
