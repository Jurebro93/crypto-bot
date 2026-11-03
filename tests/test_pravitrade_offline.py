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


class LiveRoutes(unittest.TestCase):
    """Live path with every network call faked: route fallback, fee accounting, unknown results, back-off, rent."""

    def setUp(self):
        from trade import wallet
        self.tmp = tempfile.TemporaryDirectory()
        self.w = wallet
        self.calls = []
        self.balance = {"tok": 0}
        self.v2 = {"order": None, "exec": None}
        self._saved = (jupiter.order, jupiter.execute, wallet.sign, wallet.token_raw_balance, wallet.close_empty,
                       wallet.address, wallet.can_sign, executor.STOP_FILE, wallet.sol_balance)
        wallet.sol_balance = lambda addr: 5.0
        wallet.sign = lambda tx, kp=None: "SIGNED"
        wallet.address = lambda: "ME"
        wallet.can_sign = lambda: True
        wallet.token_raw_balance = lambda owner, mint: self.balance["tok"]
        wallet.close_empty = lambda kp, mint: 2_039_280
        jupiter.order, jupiter.execute = self.order, self.execute
        executor.STOP_FILE = os.path.join(self.tmp.name, "STOP")
        os.environ["TRADE_LIVE"] = "1"
        self.con = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        self.cfg = {**CFG, "on": True, "use_pump": False, "max_loss_day": 1}

    def tearDown(self):
        (jupiter.order, jupiter.execute, self.w.sign, self.w.token_raw_balance, self.w.close_empty, self.w.address,
         self.w.can_sign, executor.STOP_FILE, self.w.sol_balance) = self._saved
        os.environ.pop("TRADE_LIVE", None)
        self.con.close()
        self.tmp.cleanup()

    def order(self, inp, out, amount, taker=None, route="v2"):
        self.calls.append(("order", route))
        if route == "v2" and self.v2["order"] == "down":
            raise OSError("down")
        rate = 1000 if inp == jupiter.SOL else 1 / 1000
        return {"inAmount": str(amount), "outAmount": str(int(amount * rate)), "requestId": route, "taker": "ME",
                "inUsdValue": 100, "outUsdValue": 99, "transaction": "dHg=", "signatureFeeLamports": 5000,
                "prioritizationFeeLamports": 100_000, "rentFeeLamports": 2_039_280 if inp == jupiter.SOL else 0}

    def execute(self, signed, rid, route="v2"):
        self.calls.append(("exec", route))
        if route == "v2" and self.v2["exec"] == "notlanded":
            return {"status": "Failed", "code": -1000, "error": "Failed to land"}
        if route == "v2" and self.v2["exec"] == "silent":
            return None
        return {"status": "Success", "signature": "SIG", "code": 0}   # amounts then come from the quote

    def test_falls_back_to_ultra_when_v2_down_and_counts_fees(self):
        self.v2["order"] = "down"
        r = executor.buy(self.con, self.cfg, "MINT", now=NOW)
        self.assertEqual((r["status"], r["mode"], r["route"]), ("open", "live", "ultra"))
        fees = self.con.execute("SELECT fees_sol FROM positions").fetchone()[0]
        self.assertAlmostEqual(fees, (5000 + 100_000 + 2_039_280) / 1e9)

    def test_not_landed_tries_next_route(self):
        self.v2["exec"] = "notlanded"
        r = executor.buy(self.con, self.cfg, "MINT", now=NOW)
        self.assertEqual(r["route"], "ultra")
        self.assertEqual([c for c in self.calls if c[0] == "exec"], [("exec", "v2"), ("exec", "ultra")])

    def test_silent_execute_checks_wallet_and_never_buys_twice(self):
        self.v2["exec"] = "silent"
        r = executor.buy(self.con, self.cfg, "MINT", now=NOW)
        self.assertEqual(r["status"], "failed")
        self.assertNotIn(("exec", "ultra"), self.calls)    # unknown result: no second route
        self.calls.clear()
        self.balance["tok"] = 0
        jupiter_exec = self.execute

        def landed(signed, rid, route="v2"):
            self.balance["tok"] = 777
            return None
        jupiter.execute = landed
        r = executor.buy(self.con, self.cfg, "MINT2", now=NOW)
        jupiter.execute = jupiter_exec
        self.assertEqual((r["status"], r["amount_out"]), ("open", 777))

    def test_close_reclaims_rent_and_sell_backoff(self):
        executor.buy(self.con, self.cfg, "MINT", now=NOW)
        self.balance["tok"] = 50_000_000_000
        self.v2["exec"] = "notlanded"

        def fail_all(signed, rid, route="v2"):
            return {"status": "Failed", "code": -1005, "error": "expired"}
        jupiter.execute = fail_all
        self.assertEqual(executor.sell(self.con, self.cfg, 1, close=True, now=NOW)["status"], "failed")
        self.assertEqual(executor.sell(self.con, self.cfg, 1, close=True, now=NOW + 2)["status"], "wait")
        jupiter.execute = self.execute
        self.v2["exec"] = None
        r = executor.sell(self.con, self.cfg, 1, close=True, now=NOW + 10)
        self.assertEqual(r["status"], "ok")
        st, fees = self.con.execute("SELECT status, fees_sol FROM positions").fetchone()
        self.assertEqual(st, "closed")
        # buy fees (incl. rent) + sell fees - rent back
        self.assertAlmostEqual(fees, (105_000 + 2_039_280 + 105_000 - 2_039_280) / 1e9)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE side='rent'").fetchone()[0], 1)

    def test_switch_off_still_sells_real_positions(self):
        executor.buy(self.con, self.cfg, "MINT", now=NOW)
        self.balance["tok"] = 10_000_000
        r = executor.sell(self.con, {**self.cfg, "on": False}, 1, close=True, now=NOW + 1)
        self.assertEqual(r["status"], "ok")
