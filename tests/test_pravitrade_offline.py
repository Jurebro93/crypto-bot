"""Real-trade page and the mirror of the "pravi-trade" competition account (fake Jupiter, temp DBs, no network).

    python3 -m unittest tests.test_pravitrade_offline
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from tests.test_trade_offline import CFG, FakeJup  # noqa: E402
from trade import executor, jupiter, settings  # noqa: E402

NOW = time.time()


class PraviTrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fake = FakeJup()
        self._saved = (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY", "TRADE_OWNER"):
            os.environ.pop(k, None)

    def tearDown(self):
        (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB) = self._saved
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def _demo_buy(self, token, opened=NOW):
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, 0))
        tid = store.buy(self.lg, settings.LEAGUE_USER, token, token, 25, 1.0, 1e6, "copy wallet X")
        self.lg.execute("UPDATE trades SET opened_ts=? WHERE id=?", (int(opened), tid))
        self.lg.commit()
        return tid

    def test_switch_off_by_default_and_needs_key(self):
        cfg = settings.merged(CFG, self.con)
        self.assertFalse(cfg["on"])
        self.assertFalse(executor.is_live(cfg))
        settings.put(self.con, "on", True)
        cfg = settings.merged(CFG, self.con)
        self.assertTrue(cfg["on"])
        self.assertFalse(executor.is_live(cfg))   # switch on, but no TRADE_LIVE/key in env -> still dry
        os.environ["TRADE_LIVE"] = "1"
        self.assertFalse(executor.is_live(cfg))   # still no key

    def test_mirror_buy_partial_and_close(self):
        cfg = settings.merged(CFG, self.con)
        tid = self._demo_buy("MINT")
        self._demo_buy("OLD", opened=NOW - 1000)
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
        rows = dict(self.con.execute("SELECT token, status FROM positions"))
        self.assertEqual(rows, {"MINT": "open", "OLD": "blocked"})
        self.assertEqual(self.con.execute("SELECT mode FROM positions WHERE token='MINT'").fetchone()[0], "dry")
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW + 5, quiet=True)   # nothing bought twice
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE side='buy'").fetchone()[0], 1)

        store.sell_part(self.lg, tid, 0.5, 2.0, 1e6)   # demo auto sell takes half
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW + 10, quiet=True)
        q, left = self.con.execute("SELECT qty_raw, qty_left FROM positions WHERE token='MINT'").fetchone()
        self.assertAlmostEqual(left / q, 0.5, places=2)

        store.sell(self.lg, settings.LEAGUE_USER, tid, 2.0, 1e6, "TP")
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW + 15, quiet=True)
        self.assertEqual(self.con.execute("SELECT status FROM positions WHERE token='MINT'").fetchone()[0], "closed")
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW + 20, quiet=True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE side='sell'").fetchone()[0], 2)

    def test_daily_loss_cap(self):
        cfg = {**settings.merged(CFG, self.con), "max_loss_day": 0.02, "max_sol_per_day": 9}
        self.con.execute("INSERT INTO positions (token, mode, status, sol_in, sol_back, opened_ts, closed_ts) "
                         "VALUES ('L','dry','closed',0.05,0.01,?,?)", (int(NOW), int(NOW)))
        r = executor.buy(self.con, cfg, "NEW", now=NOW)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("dnevni gubitak", r["error"])

    def test_sell_all(self):
        cfg = settings.merged(CFG, self.con)
        executor.buy(self.con, cfg, "A", now=NOW)
        settings.put(self.con, "sell_all", int(NOW))
        run_trade._sell_all_try["ts"] = 0
        run_trade.sell_all_once(self.con, settings.merged(CFG, self.con), now=NOW, quiet=True)
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchone()[0], "closed")
        self.assertEqual(settings.merged(CFG, self.con)["sell_all"], 0)

    def test_page_access_and_owner_only_posts(self):
        from ui import pravitrade
        os.environ["TRADE_OWNER"] = "Jure"
        title, body = pravitrade.page({}, "Ivan")
        self.assertIn("samo za pozvane", body)
        self.assertNotIn("Uključi pravi trade", body)
        loc = pravitrade.post("/pravi-trade/switch", {"on": "1"}, "Ivan")
        self.assertIn("err=", loc)
        self.assertFalse(settings.merged(CFG, self.con)["on"])

        _, body = pravitrade.page({}, "jure")
        self.assertIn("Uključi pravi trade", body)
        self.assertIn("ISKLJUČENO", body)
        loc = pravitrade.post("/pravi-trade/switch", {"on": "1"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertTrue(settings.merged(CFG, self.con)["on"])

        os.environ["UI_USERS"] = "Ivan,Jure"
        try:
            pravitrade.post("/pravi-trade/invite", {"u_list": ["ivan", "Nepoznat"]}, "Jure")
            self.assertEqual(settings.invited(self.con), ["Ivan"])
            _, body = pravitrade.page({}, "Ivan")
            self.assertIn("Pozicije", body)
            self.assertNotIn("Spremi limite", body)   # invited: look only
        finally:
            os.environ.pop("UI_USERS")

        loc = pravitrade.post("/pravi-trade/limits", {"size_sol": "99"}, "Jure")
        self.assertIn("err=", loc)
        pravitrade.post("/pravi-trade/limits", {"size_sol": "0,02", "max_loss_day": "0.1"}, "Jure")
        cfg = settings.merged(CFG, self.con)
        self.assertEqual((cfg["size_sol"], cfg["max_loss_day"]), (0.02, 0.1))

        loc = pravitrade.post("/pravi-trade/follow", {"kind": "wallet", "target": "WALLETADDR", "per_day": "3"}, "Jure")
        self.assertIn("err=", loc)   # not watched live: refused
        saved = pravitrade._live_wallets
        pravitrade._live_wallets = lambda: {"WALLETADDR"}
        try:
            loc = pravitrade.post("/pravi-trade/follow", {"kind": "wallet", "target": "WALLETADDR", "per_day": "3"}, "Jure")
        finally:
            pravitrade._live_wallets = saved
        self.assertIn("ok=", loc)
        fl = copy.follows(self.lg, settings.LEAGUE_USER)
        self.assertEqual([(f["kind"], f["target"], f["exit"]["mode"]) for f in fl], [("wallet", "WALLETADDR", "mirror")])


if __name__ == "__main__":
    unittest.main()
