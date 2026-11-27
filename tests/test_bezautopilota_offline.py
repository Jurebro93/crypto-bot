"""27.11. (vlasnik: "Ugasi Autopilot, ne treba nam praćenje uživo ... Autopilot prestaje trošiti ikakve resurse, uklanja
se potpuno"; ops/autopilot_off.py): with AUTOPILOT_OFF (default) the Autopilot's threads and pages are gone, demo keeps
running at the learning cadence, an open real position keeps a 15-s exit watch that ends by itself, the owner keeps
his manual buy, sell buttons and the kill switch.

    python3 -m unittest tests.test_bezautopilota_offline
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
import run_ui  # noqa: E402
from league import auto  # noqa: E402
from ops import autopilot_off  # noqa: E402
from trade import executor  # noqa: E402
from ui import landing, pravitrade  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base  # noqa: E402

OFF = {"AUTOPILOT_OFF": "1"}
ON = {"AUTOPILOT_OFF": "0"}


def _trade_db(path, rows):
    con = executor.connect(path)
    for i, (mode, status) in enumerate(rows):
        con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?,?)",
                    (f"T{i}", f"S{i}", 1, mode, status, 0.1))
    con.commit()
    return con


class Switch(unittest.TestCase):
    def test_default_is_off_and_zero_brings_the_old_behaviour(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUTOPILOT_OFF", None)
            self.assertTrue(autopilot_off.on())
        with mock.patch.dict(os.environ, ON):
            self.assertFalse(autopilot_off.on())

    def test_ui_threads(self):
        with mock.patch.dict(os.environ, OFF):
            got = run_ui.background_threads()
            self.assertEqual([n for n, _t, _k in got], ["dca-nalozi"])   # no live sampler of the skips
            self.assertEqual(got[0][2], {"every": autopilot_off.DCA_S})
        with mock.patch.dict(os.environ, ON):
            self.assertEqual([n for n, _t, _k in run_ui.background_threads()], ["preskoceni-uzivo", "dca-nalozi"])

    def test_run_trade_poll(self):
        self.assertEqual(run_trade._poll_s({"poll_s": 1}, False), 1)
        self.assertEqual(run_trade._poll_s({"poll_s": 1}, True), autopilot_off.TRADE_POLL_S)


class OpenPositionGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "trade.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_watcher_cadence_follows_the_open_real_positions(self):
        self.assertEqual(autopilot_off.exit_every(path=self.db), (autopilot_off.DEMO_EXIT_S, 0))   # no trade.db
        con = _trade_db(self.db, [("live", "open"), ("dry", "open"), ("live", "closed")])
        self.assertEqual(autopilot_off.open_real(self.db), 1)
        self.assertEqual(autopilot_off.exit_every(path=self.db), (autopilot_off.REAL_EXIT_S, 1))
        con.execute("UPDATE positions SET status='pending' WHERE mode='live' AND status='open'")
        con.commit()
        self.assertEqual(autopilot_off.exit_every(path=self.db)[0], autopilot_off.REAL_EXIT_S)   # half-booked counts
        con.execute("UPDATE positions SET status='closed' WHERE mode='live'")
        con.commit()
        con.close()
        self.assertEqual(autopilot_off.exit_every(path=self.db), (autopilot_off.DEMO_EXIT_S, 0))  # ends by itself

    def test_unreadable_count_keeps_the_watcher(self):
        with open(self.db, "w") as f:
            f.write("not a database")
        self.assertIsNone(autopilot_off.open_real(self.db))
        self.assertEqual(autopilot_off.exit_every(path=self.db)[0], autopilot_off.REAL_EXIT_S)

    def test_fast_loop_runs_the_demo_at_the_learning_cadence(self):
        class Stop(Exception):
            pass
        naps, seen = [], []

        def sleep(s):
            naps.append(s)
            raise Stop

        with mock.patch.dict(os.environ, OFF), \
                mock.patch.object(auto.store, "connect", lambda *a: mock.MagicMock()), \
                mock.patch.object(auto, "fast_once", lambda con, market, user: seen.append(user) or []), \
                mock.patch.object(autopilot_off, "exit_every", lambda *a, **k: (autopilot_off.DEMO_EXIT_S, 0)), \
                mock.patch.object(auto.time, "sleep", sleep), mock.patch("builtins.print"):
            with self.assertRaises(Stop):
                auto.fast_loop(lambda toks: {})
        self.assertEqual(naps, [autopilot_off.DEMO_EXIT_S])
        self.assertEqual(len(seen), 1)   # the demo accounts' exits still ran
        naps.clear()
        with mock.patch.dict(os.environ, OFF), \
                mock.patch.object(auto.store, "connect", lambda *a: mock.MagicMock()), \
                mock.patch.object(auto, "fast_once", lambda con, market, user: []), \
                mock.patch.object(autopilot_off, "exit_every", lambda *a, **k: (autopilot_off.REAL_EXIT_S, 2)), \
                mock.patch.object(auto.time, "sleep", sleep), mock.patch("builtins.print"):
            with self.assertRaises(Stop):
                auto.fast_loop(lambda toks: {})
        self.assertEqual(naps, [autopilot_off.REAL_EXIT_S])
        naps.clear()
        with mock.patch.dict(os.environ, ON), \
                mock.patch.object(auto.store, "connect", lambda *a: mock.MagicMock()), \
                mock.patch.object(auto, "fast_once", lambda con, market, user: []), \
                mock.patch.object(auto.time, "sleep", sleep), mock.patch("builtins.print"):
            with self.assertRaises(Stop):
                auto.fast_loop(lambda toks: {})
        self.assertEqual(naps, [auto.FAST_EVERY_S])   # the old 1-s watch only with AUTOPILOT_OFF=0


class Pages(unittest.TestCase):
    def test_removed_addresses(self):
        with mock.patch.dict(os.environ, OFF):
            self.assertEqual(run_ui.autopilot_gone("/autopilot"), ("page", "en"))
            self.assertEqual(run_ui.autopilot_gone("/hr/autopilot"), ("page", "hr"))
            self.assertEqual(run_ui.autopilot_gone("/autopilot/chat")[0], "empty")
            self.assertEqual(run_ui.autopilot_gone("/autopilot/chat", post=True)[0], "empty")
            for p in ("/pravi-trade/api/stream", "/pravi-trade/api/tick", "/pravi-trade/pozicije", "/pravi-trade/log"):
                self.assertEqual(run_ui.autopilot_gone(p), ("empty", "hr"), p)
            self.assertIsNone(run_ui.autopilot_gone("/pravi-trade"))
            for p in ("/pravi-trade/buy", "/pravi-trade/sell", "/pravi-trade/sellall", "/pravi-trade/kill"):
                self.assertIsNone(run_ui.autopilot_gone(p, post=True), p)   # the owner's forms stay
            self.assertIsNone(run_ui.autopilot_gone("/wallets"))
            html = autopilot_off.gone_html("en")
            self.assertIn("noindex", html)
            self.assertNotIn("profitable", html.lower())
        with mock.patch.dict(os.environ, ON):
            self.assertIsNone(run_ui.autopilot_gone("/autopilot"))
            self.assertIsNone(run_ui.autopilot_gone("/pravi-trade/api/stream"))

    def test_robots_still_lets_crawlers_see_the_410(self):
        from ui import public   # Disallow would hide the 410 and keep a stale result; the sitemap has it no more
        self.assertIn(("/autopilot$", "/autopilot"), public.ROBOTS_ALLOW)

    def test_landing_has_no_autopilot_block(self):
        with mock.patch.dict(os.environ, OFF):
            self.assertEqual(landing.ap_block("en"), "")
            self.assertEqual(landing.ap_block("hr"), "")

    def test_sitemap_has_no_autopilot(self):
        from ui import seoindex
        with mock.patch.dict(os.environ, OFF):
            try:
                hubs = seoindex._hubs(0)
            except Exception as e:  # noqa: BLE001 - the hubs need no network; anything else is a real failure
                self.fail(f"_hubs: {e}")
        self.assertNotIn("/autopilot", [h[0] for h in hubs])

    def test_menu_has_no_public_autopilot_link(self):
        from ui import html
        if not html.AP_OFF:
            self.skipTest("ui.html imported with AUTOPILOT_OFF=0")
        hrefs = [h for _t, items in html.VISE for h, _n, _c in items]
        self.assertNotIn("/autopilot", hrefs)
        self.assertIn("/pravi-trade", hrefs)
        self.assertNotIn("Autopilot", [s for s, _i in html.SECTIONS])


class OwnerPage(Base):
    def setUp(self):
        super().setUp()
        self.stop = os.path.join(self.tmp.name, "STOP")
        p = [mock.patch.dict(os.environ, OFF), mock.patch.object(executor, "STOP_FILE", self.stop),
             mock.patch.object(pravitrade, "_balance", lambda addr: 1.2345)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def test_minimal_page(self):
        title, body = pravitrade.page({}, "Jure")
        self.assertEqual(title, "Pravi trade")
        self.assertIn("action=/pravi-trade/buy", body)       # manual buy stays
        self.assertIn("action=/pravi-trade/kill", body)      # kill switch
        self.assertIn("Nema otvorenih pozicija", body)
        self.assertIn("Prikaži stanje walleta", body)        # balance only on a tap
        self.assertNotIn("api/stream", body)
        self.assertNotIn("1,2345", body)
        with mock.patch.object(pravitrade.wallet, "address", lambda: "Addr111"):
            _t, body = pravitrade.page({"stanje": "1"}, "Jure")
        self.assertIn("1,2345", body)
        _t, other = pravitrade.page({}, "netko")
        self.assertNotIn("action=/pravi-trade/buy", other)
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, sol_in) VALUES "
                         "('Tok1','HOPE',1,'live','open',0.1)")
        self.con.commit()
        _t, body = pravitrade.page({}, "Jure")
        self.assertIn("HOPE", body)
        self.assertIn("action=/pravi-trade/sell", body)
        self.assertIn("action=/pravi-trade/sellall", body)

    def test_kill_switch_and_ring(self):
        from trade import wake
        before = wake.stamp()
        self.assertIn("ok=", self.post("/pravi-trade/kill", {"on": "1"}))
        self.assertTrue(os.path.exists(self.stop))
        self.assertIn("UKLJUČEN", pravitrade.page({}, "Jure")[1])
        self.assertIn("err=", pravitrade.post("/pravi-trade/kill", {"on": "0"}, "netko"))   # owner only
        self.assertTrue(os.path.exists(self.stop))
        self.post("/pravi-trade/kill", {"on": "0"})
        self.assertFalse(os.path.exists(self.stop))
        self.post("/pravi-trade/sellall", {})
        self.assertNotEqual(wake.stamp(), before)   # run_trade's 15-s nap ends at once


class GrokBuys(Base):
    def test_grok_autotrade_buy_refused_while_removed(self):
        from ui import grokauto, mcpapi
        self.post("/pravi-trade/grokon", {})
        with mock.patch.dict(os.environ, OFF):
            code, out = mcpapi.trade_request({"token": "So11111111111111111111111111111111111111112"[:-1] + "3",
                                              "side": "buy", "amount": 0.05, "require_approval": False})
        self.assertEqual(out["status"], "rejected")
        self.assertIn("removed", out["reason"])
        self.assertEqual(grokauto.log_rows(self.con)[0]["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
