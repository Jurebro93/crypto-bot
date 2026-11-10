"""Real-trade page and the mirror of the "pravi-trade" competition account (fake Jupiter, temp DBs, no network).

    python3 -m unittest tests.test_pravitrade_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from tests.test_trade_offline import CFG, FakeJup  # noqa: E402
from trade import executor, jupiter, settings  # noqa: E402

NOW = time.time()
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():   # 9.11. (review izvori): follows and buys wake the copy loop; the tests must not touch the repo's .copy_wake
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


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

    def _demo_buy(self, token, opened=NOW - 30):   # 9.11. (review novac): a copy younger than COPY_BOOK_WAIT_S without
        # follow_id / copy_log is left for the next tick (league/copy.py books them a few ms after store.buy commits)
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
        self.assertNotIn("Uključi Autopilot", body)
        loc = pravitrade.post("/pravi-trade/switch", {"on": "1"}, "Ivan")
        self.assertIn("err=", loc)
        self.assertFalse(settings.merged(CFG, self.con)["on"])

        _, body = pravitrade.page({}, "jure")
        self.assertIn("Uključi Autopilot", body)
        # 10.11. (prijedlog dizajna, maketa autopilot.html): the state is a word after a dot, no capitals
        self.assertIn("<span>Isključen</span>", body)
        self.assertIn("Samo probno, bez novca", body)
        self.assertIn("Postavljanje walleta", body)
        self.assertNotIn("Svi nalozi", body)          # 4.11.: no order log, no demo tables
        self.assertNotIn("Demo praćenja", body)
        self.assertNotIn("Prodaj sve", body)          # off and nothing open: no red button
        self.assertIn("err=", pravitrade.post("/pravi-trade/wallet", {"addr": "nije-adresa"}, "Jure"))
        self.assertIn("err=", pravitrade.post("/pravi-trade/wallet", {"addr": "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"}, "Ivan"))
        self.assertIn("ok=", pravitrade.post("/pravi-trade/wallet", {"addr": "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"}, "Jure"))
        self.assertEqual(settings.raw(self.con)["wallet_pub"], "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin")
        loc = pravitrade.post("/pravi-trade/switch", {"on": "1"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertTrue(settings.merged(CFG, self.con)["on"])

        os.environ["UI_USERS"] = "Ivan,Jure"
        try:
            pravitrade.post("/pravi-trade/invite", {"u_list": ["ivan", "Nepoznat"]}, "Jure")
            self.assertEqual(settings.invited(self.con), ["Ivan"])
            _, body = pravitrade.page({}, "Ivan")
            self.assertIn("Koga prati", body)   # 10.11. (maketa): the row's name under "Kako trguje"
            self.assertNotIn("Spremi limite", body)
            self.assertNotIn("Postavljanje walleta", body)   # invited: look only
        finally:
            os.environ.pop("UI_USERS")

        loc = pravitrade.post("/pravi-trade/limits", {"size_sol": "99"}, "Jure")
        self.assertIn("err=", loc)
        pravitrade.post("/pravi-trade/limits", {"size_sol": "0,02", "max_loss_day": "0.1"}, "Jure")
        cfg = settings.merged(CFG, self.con)
        self.assertEqual((cfg["size_sol"], cfg["max_loss_day"]), (0.02, 0.1))
        self.assertFalse(cfg["simianx"])   # SimianX off unless the owner ticks it
        self.assertFalse(settings.simianx_on(self.con))
        pravitrade.post("/pravi-trade/limits", {"simianx": "1"}, "Ivan")   # not the owner: refused
        self.assertFalse(settings.simianx_on(self.con))
        pravitrade.post("/pravi-trade/limits", {"simianx": "1"}, "Jure")
        self.assertFalse(settings.simianx_on(self.con))   # audit 4.11.: locked until it has the same proof
        self.assertFalse(settings.merged(CFG, self.con)["simianx"])

        # 9.11. (Jure): any wallet can be followed; one not in the Helius webhook yet is added to it (or, when the
        # sync cannot run, the page says it joins in the next KOL round) instead of being refused
        saved = (pravitrade._add_live_wallet, pravitrade._live_wallets)
        pravitrade._add_live_wallet = lambda w: False
        pravitrade._live_wallets = lambda: set()   # never the repo's own kol.db (a stale one made this order-dependent)
        try:
            loc = pravitrade.post("/pravi-trade/follow", {"kind": "wallet", "target": "WALLETADDR", "per_day": "3"}, "Jure")
        finally:
            pravitrade._add_live_wallet, pravitrade._live_wallets = saved
        self.assertIn("ok=", loc)
        self.assertIn("KOL%20krugu", loc)
        fl = copy.follows(self.lg, settings.LEAGUE_USER)
        self.assertEqual([(f["kind"], f["target"], f["exit"]["mode"]) for f in fl], [("wallet", "WALLETADDR", "mirror")])
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "@ansem", "per_day": "3"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual([f["target"] for f in copy.follows(self.lg, settings.LEAGUE_USER) if f["kind"] == "kol"], ["ansem"])


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


class Safety(LiveRoutes):
    """Reserve for selling, manual sell buttons, manual stake, warnings."""

    def test_reserve_left_for_selling(self):
        self.w.sol_balance = lambda addr: 0.06
        r = executor.buy(self.con, {**self.cfg, "size_sol": 0.05, "min_sol_reserve": 0.0, "max_sol_per_trade": 1}, "M",
                         now=NOW)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("rezerva za prodaju", r["error"])
        self.w.sol_balance = lambda addr: 0.07
        r = executor.buy(self.con, {**self.cfg, "size_sol": 0.05, "min_sol_reserve": 0.0, "max_sol_per_trade": 1}, "M",
                         now=NOW)
        self.assertEqual(r["status"], "open")   # 0.05 + 0.003 + 0.01 floor = 0.063 <= 0.07

    def test_sell_button_request(self):
        executor.buy(self.con, self.cfg, "MINT", now=NOW)
        self.balance["tok"] = 50_000_000_000
        settings.put(self.con, "sell_req", {"1": 0.5})
        run_trade.sell_requests_once(self.con, settings.merged(self.cfg, self.con), now=NOW + 1, quiet=True)
        q, left, st = self.con.execute("SELECT qty_raw, qty_left, status FROM positions").fetchone()
        self.assertEqual((st, round(left / q, 2)), ("open", 0.5))
        self.assertEqual(settings.merged(self.cfg, self.con)["sell_req"], {})

    def test_warnings_render(self):
        from ui import pravitrade
        lcon = store.connect(os.path.join(self.tmp.name, "league.db"))
        copy.ensure(lcon)
        self.w.sol_balance = lambda addr: 0.001
        pravitrade._BAL.clear()
        self.con.execute("INSERT INTO positions (token, mode, status, sol_in, opened_ts) VALUES ('X','live','open',0.05,?)",
                         (int(NOW),))
        for _ in range(2):
            self.con.execute("INSERT INTO orders (ts, side, status, code, prio_lamports) VALUES (?, 'buy', 'failed', "
                             "-1000, 2000000)", (int(time.time()),))
        self.con.commit()
        html = pravitrade._warnings(self.con, settings.merged({**self.cfg, "max_sol_per_day": 9}, self.con), lcon)
        for bit in ("Opasno malo SOL-a", "nije stiglo u blok", "naknada za prioritet", "nikoga ne prati",
                    "još nije javio"):
            self.assertIn(bit, html)
        lcon.close()


class ManualBuy(PraviTrade):
    def test_manual_buy_goes_through_demo_account_with_own_stake(self):
        from ui import league as uleague, pravitrade, prijedlog
        from rugfilter import collapse
        os.environ["TRADE_OWNER"] = "Jure"
        saved = (uleague.market, collapse.check, uleague._symbol, prijedlog.live_market)
        uleague.market = lambda toks: {t: (1.0, 1e6, None, 5e5) for t in toks}
        collapse.check = lambda *a, **k: None
        uleague._symbol = lambda t: "MAN"
        # 9.11.: the tap goes through the same live gate as the lists (trading now, MC 30k+, not falling)
        prijedlog.live_market = lambda toks, fetch=None: {t: {"price": 1.0, "liq": 1e6, "mcap": 5e5, "vol_h1": 20_000.0, "vol_h24": 1e5,
                                                               "txns_h1": 80, "buys_h1": 50, "txns_h24": 900, "vol_m5": 900.0, "txns_m5": 6,
                                                               "ch_m5": 1.0, "ch_h1": 3.0, "ch_h24": 10.0} for t in toks}
        mint = "So11111111111111111111111111111111111111112"[:-1] + "3"
        try:
            loc = pravitrade.post("/pravi-trade/buy", {"token": mint, "sol": "0,02", "exit": "tpsl", "tp": "100%",
                                                       "sl": "-30%"}, "Jure")
        finally:
            uleague.market, collapse.check, uleague._symbol, prijedlog.live_market = saved
        self.assertIn("ok=", loc)
        t = store.trades(self.lg, settings.LEAGUE_USER, "open")[0]
        self.assertEqual(json.loads(t["auto"])["mode"], "tpsl")
        cfg = settings.merged(CFG, self.con)
        run_trade.follow_league_once(self.con, cfg, since=0, now=time.time(), quiet=True)
        self.assertAlmostEqual(self.con.execute("SELECT sol_in FROM positions").fetchone()[0], 0.02)


class Recommendations(unittest.TestCase):
    def test_kol_window_stats(self):
        from ui import autopilot
        now = 100 * 86400
        calls = [("a", now - 3 * 86400, 1.0, 0.2, 0), ("a", now - 3 * 86400, 0.1, -0.3, 0),
                 ("a", now - 20 * 86400, 2.0, 0.5, 1), ("b", now - 2 * 86400, None, None, 0)]
        s7, s30 = autopilot.kol_stats(calls, now, 7), autopilot.kol_stats(calls, now, 30)
        self.assertEqual((s7["a"]["n"], s7["a"]["hits"], s7["a"]["rugs"]), (2, 1, 0))
        self.assertEqual((s30["a"]["n"], s30["a"]["hits"], s30["a"]["rugs"]), (3, 2, 1))
        self.assertNotIn("b", s7)   # not measured yet
        self.assertLess(s30["a"]["score"], s7["a"]["score"])   # a rug costs more than a hit gains

    def test_wallet_window_stats(self):
        from ui import autopilot
        now = 100 * 86400
        tr = [("w", "A", "buy", now - 86400, 1.0), ("w", "A", "sell", now - 80000, 3.0),
              ("w", "B", "buy", now - 86400, 1.0), ("w", "B", "sell", now - 80000, 0.5),
              ("w", "C", "buy", now - 86400, 1.0),                                    # still held: not closed
              ("w", "D", "buy", now - 20 * 86400, 1.0), ("w", "D", "sell", now - 86400, 9.0)]   # bought before 7 d
        s = autopilot.wallet_stats(tr, now, 7)["w"]
        self.assertEqual((s["bought"], s["closed"], s["wins"]), (3, 2, 1))
        self.assertAlmostEqual(s["roi"], 0.75)
        self.assertEqual(autopilot.wallet_stats(tr, now, 30)["w"]["closed"], 3)



class AutoPick(PraviTrade):
    def test_tool_picks_and_rotates_but_leaves_manual_and_stopped_alone(self):
        from ui import autopilot, pravitrade
        os.environ["TRADE_OWNER"] = "Jure"
        st = {"hit": 0.5, "n": 4, "roi": 0.3, "win": 0.6}
        recs = {"kol": [{"handle": h, "live": live, "why": "dobar", "s": st} for h, live in
                        (("a", True), ("slow", False), ("b", True), ("c", True), ("d", True))],
                "wal": [{"wallet": "W1", "name": "jedan", "why": "dobar", "s": st},
                        {"wallet": "W2", "name": "", "why": "dobar", "s": st}]}
        saved = (autopilot.kol_recs, autopilot.wallet_recs, pravitrade._live_wallets)
        autopilot.kol_recs = lambda now=None: {14: recs["kol"]}
        autopilot.wallet_recs = lambda now=None: {14: recs["wal"]}
        pravitrade._live_wallets = lambda: {"W1", "W2", "MAN"}
        try:
            pravitrade.post("/pravi-trade/follow", {"kind": "kol", "target": "b", "per_day": "3"}, "Jure")   # manual
            loc = pravitrade.post("/pravi-trade/auto", {"on": "1", "days": "14", "n": "2"}, "Jure")
            self.assertIn("ok=", loc)
            got = {(f["kind"], f["target"]) for f in copy.follows(self.lg, settings.LEAGUE_USER)}
            # live only (slow is skipped), manual b kept and not counted as the tool's
            self.assertEqual(got, {("kol", "a"), ("kol", "b"), ("wallet", "W1"), ("wallet", "W2")})
            auto = set(settings.raw(self.con)["auto_follows"])
            self.assertEqual(len(auto), 3)

            # a drops out of the top 2n -> removed; c comes in
            recs["kol"] = [{"handle": h, "live": True, "why": "dobar", "s": st} for h in ("c", "d", "e", "f", "a")]
            autopilot.sync_follows(self.lg, self.con, force=True)
            got = {f["target"] for f in copy.follows(self.lg, settings.LEAGUE_USER) if f["kind"] == "kol"}
            self.assertEqual(got, {"b", "c", "d"})

            # stopped by hand -> never brought back
            fid = next(f["id"] for f in copy.follows(self.lg, settings.LEAGUE_USER) if f["target"] == "c")
            pravitrade.post("/pravi-trade/stop", {"id": str(fid)}, "Jure")
            autopilot.sync_follows(self.lg, self.con, force=True)
            got = {f["target"] for f in copy.follows(self.lg, settings.LEAGUE_USER) if f["kind"] == "kol"}
            self.assertEqual(got, {"b", "d", "e"})

            # only the owner switches it; off = nothing changes
            self.assertIn("err=", pravitrade.post("/pravi-trade/auto", {"on": "0", "days": "14", "n": "2"}, "Ivan"))
            pravitrade.post("/pravi-trade/auto", {"on": "0", "days": "14", "n": "2"}, "Jure")
            recs["kol"] = []
            self.assertEqual(autopilot.sync_follows(self.lg, self.con, force=True), [])
            _, body = pravitrade.page({}, "Jure")
            self.assertIn("Neka alat sam bira", body)
            # 10.11. (Jure: "čista, minimalistička", no row of emojis): the tag is the words "odabrao alat" now
            self.assertIn("odabrao alat", body)
        finally:
            autopilot.kol_recs, autopilot.wallet_recs, pravitrade._live_wallets = saved


class LiveLog(PraviTrade):
    def test_log_shows_orders_newest_first_and_only_to_viewers(self):
        from ui import pravitrade
        os.environ["TRADE_OWNER"] = "Jure"
        cfg = settings.merged(CFG, self.con)
        executor.buy(self.con, cfg, "AAA", symbol="AAA", now=NOW)
        executor.buy(self.con, cfg, "BBB", symbol="BBB", now=NOW + 1)
        html = pravitrade.log_fragment("Jure")
        self.assertIn("kupnja", html)
        self.assertLess(html.index("BBB"), html.index("AAA"))   # newest first
        self.assertIn("probno", html)
        self.assertIsNone(pravitrade.log_fragment("Ivan"))      # not invited
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("/pravi-trade/log", body)
        # 10.11. (Jure: "log na klik pri vrhu"): the order list is the "Tehnički zapis naloga" pop-up of the closed
        # "Dnevnik Autopilota" (its rows come from /pravi-trade/dnevnik only when it is opened), no "Uživo: nalozi"
        self.assertIn("Tehnički zapis naloga", body)
        self.assertIn("data-src=/pravi-trade/dnevnik", body)
        # 10.11. (maketa autopilot.html): the log is the row "Dnevnik odluka", still right above the positions
        self.assertLess(body.index("Dnevnik odluka"), body.index("id=pozicije"))
