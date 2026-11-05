"""5.11.: the live PumpPortal feed (live/), its dump signal and the demo bot's exit on it (run_paper.live_exits).

    python3 -m unittest tests.test_live_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live import pulse, pumpportal, store as lstore  # noqa: E402

NOW = 1_800_000_000
MINT = "M1nt" + "x" * 40


def _buy(w, sol, toks, sig, mcap=100.0, bal=None):
    return {"signature": sig, "mint": MINT, "traderPublicKey": w, "txType": "buy", "tokenAmount": toks,
            "solAmount": sol, "marketCapSol": mcap, "pool": "pump", **({"newTokenBalance": bal} if bal is not None else {})}


def _sell(w, sol, toks, sig, mcap=80.0):
    return {**_buy(w, sol, toks, sig, mcap), "txType": "sell"}


class Parse(unittest.TestCase):
    def test_trade_and_launch(self):
        k, r = pumpportal.parse(json.dumps(_buy("W1", 1.5, 1500.0, "s1")), NOW)
        self.assertEqual(k, "trade")
        self.assertEqual((r[0], r[1], r[2], r[3], r[4], r[5], r[8], r[9]), ("s1", MINT, "W1", "buy", 1.5, 1500.0, "pump", NOW))
        self.assertAlmostEqual(r[6], 0.001)           # price in SOL per token
        k, r = pumpportal.parse({"signature": "c1", "mint": MINT, "traderPublicKey": "DEV", "txType": "create",
                                 "initialBuy": 1e6, "solAmount": 2.0, "name": "Cat", "symbol": "CAT", "pool": "pump"}, NOW)
        self.assertEqual(k, "launch")
        self.assertEqual(r[:6], (MINT, NOW, "DEV", "Cat", "CAT", 2.0))
        self.assertEqual(pumpportal.parse("not json"), (None, None))
        self.assertEqual(pumpportal.parse({"message": "Successfully subscribed"}), (None, None))

    def test_subscription_diff(self):
        msgs = pumpportal.subscribe_msgs(["A", "B"], ["W"], prev=({"B", "C"}, set()))
        self.assertEqual(msgs, [{"method": "unsubscribeTokenTrade", "keys": ["C"]},
                                {"method": "subscribeTokenTrade", "keys": ["A"]},
                                {"method": "subscribeAccountTrade", "keys": ["W"]}])
        self.assertEqual(pumpportal.subscribe_msgs(["A"], ["W"], prev=({"A"}, {"W"})), [])


class BalanceError(unittest.TestCase):
    def test_unfunded_key_message_sets_the_resubscribe_flag(self):
        con = lstore.connect(os.path.join(tempfile.mkdtemp(), "hype.db"))
        feed = pumpportal.Feed(con, log=lambda s: None)
        self.assertFalse(feed.balance_error)
        feed.take({"message": "Successfully subscribed to token creation events."})
        self.assertFalse(feed.balance_error)
        feed.take({"errors": "Minimum balance not met for PumpSwap websocket data."})
        self.assertTrue(feed.balance_error)
        con.close()


class Store(unittest.TestCase):
    def test_feed_writes_and_mirrors_followed_wallets(self):
        path = os.path.join(tempfile.mkdtemp(), "hype.db")
        con = lstore.connect(path)
        feed = pumpportal.Feed(con, followed={"KOL"})
        feed.take(_buy("KOL", 2.0, 1000.0, "s1"), NOW)
        feed.take(_buy("NOBODY", 0.5, 300.0, "s2"), NOW)
        feed.take(_buy("KOL", 2.0, 1000.0, "s1"), NOW)        # duplicate delivery
        self.assertEqual(feed.flush(NOW + 2, force=True), 3)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0], 2)
        self.assertEqual([r for r in con.execute("SELECT sig, wallet, mint, side, ts, sol FROM chain_trades")],
                         [("s1", "KOL", MINT, "buy", NOW, 2.0)])
        lstore.prune(con, NOW + 3 * 86400)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0], 0)
        con.close()


class LockedDatabase(unittest.TestCase):
    def test_flush_keeps_rows_while_another_process_holds_the_lock(self):
        import sqlite3
        path = os.path.join(tempfile.mkdtemp(), "hype.db")
        lstore.connect(path).close()
        con = sqlite3.connect(path, timeout=0.05, isolation_level=None)      # short wait, like a busy server
        log = []
        feed = pumpportal.Feed(con, log=log.append)
        feed.take(_buy("W1", 1.0, 1000.0, "s1"), NOW)
        other = sqlite3.connect(path, isolation_level=None)
        other.execute("BEGIN EXCLUSIVE")                                     # e.g. the start-up VACUUM
        self.assertEqual(feed.flush(NOW, force=True), 0)                     # no crash, nothing lost
        self.assertEqual(len(feed.trades), 1)
        self.assertTrue(any("baza zauzeta" in m for m in log))
        other.execute("COMMIT")
        self.assertEqual(feed.flush(NOW + 2, force=True), 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0], 1)
        other.close(); con.close()


class SoldFraction(unittest.TestCase):
    def test_share_a_wallet_sold(self):
        con = lstore.connect(os.path.join(tempfile.mkdtemp(), "hype.db"))
        feed = pumpportal.Feed(con)
        feed.take(_buy("INS", 2.0, 1000.0, "b1", bal=1000.0), NOW - 600)
        feed.take({**_sell("INS", 0.8, 400.0, "s1"), "newTokenBalance": 600.0}, NOW - 100)      # sold 40 %
        feed.take({**_sell("OTHER", 1.0, 1000.0, "s2"), "newTokenBalance": 0}, NOW - 50)          # not an insider
        feed.flush(NOW, force=True)
        self.assertAlmostEqual(pulse.sold_fraction(con, MINT, ["INS"], NOW - 300), 0.4)
        self.assertIsNone(pulse.sold_fraction(con, MINT, ["NOBODY"], NOW - 300))
        self.assertEqual(pulse.sold_fraction(con, MINT, ["OTHER"], NOW - 300), 1.0)
        feed.take({**_sell("INS", 0.9, 600.0, "s3"), "newTokenBalance": 0.0}, NOW - 10)           # out
        feed.flush(NOW + 1, force=True)
        self.assertEqual(pulse.sold_fraction(con, MINT, ["INS"], NOW - 300), 1.0)
        con.close()


class Dump(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "hype.db")
        self.con = lstore.connect(self.path)
        feed = pumpportal.Feed(self.con)
        feed.take(_buy("W0", 1.0, 1000.0, "ref"), NOW - 400)          # 0.001 SOL five minutes before
        for i in range(6):                                              # six wallets dump at -12%
            feed.take(_sell(f"S{i}", 1.0, 1136.0, f"d{i}"), NOW - 30 + i)
        feed.take(_buy("B1", 0.4, 460.0, "b1"), NOW - 10)
        feed.flush(NOW, force=True)

    def test_window_and_dump(self):
        w = pulse.window(self.con, MINT, NOW, 60)
        self.assertEqual((w["buyers"], w["sellers"], w["buys"], w["sells"]), (1, 6, 1, 6))
        self.assertAlmostEqual(w["net_sol"], 0.4 - 6.0, places=2)
        hit, why = pulse.dump(self.con, MINT, NOW)
        self.assertTrue(hit)
        self.assertIn("6 prodavača", why)
        self.assertIn("-13%", why)
        self.assertEqual(pulse.check_dumps(self.con, {MINT, "OTHER"}, NOW), 1)
        self.assertEqual(pulse.check_dumps(self.con, {MINT}, NOW + 30), 0)       # cooldown
        self.assertEqual(len(pulse.alerts(self.con, NOW - 10)), 1)
        self.assertIn("Prodavači prevladavaju", pulse.token_html(MINT, NOW, self.con))
        self.assertIn("Dump prije 0 min", pulse.token_html(MINT, NOW + 5, self.con))

    def test_no_dump_when_buyers_dominate_or_price_holds(self):
        con = lstore.connect(os.path.join(tempfile.mkdtemp(), "hype.db"))
        feed = pumpportal.Feed(con)
        feed.take(_buy("W0", 1.0, 1000.0, "ref"), NOW - 400)
        for i in range(6):                                              # six sellers but the price holds (-2%)
            feed.take(_sell(f"S{i}", 1.0, 1020.0, f"d{i}"), NOW - 30 + i)
        feed.flush(NOW, force=True)
        self.assertEqual(pulse.dump(con, MINT, NOW), (False, None))
        for i in range(10):
            feed.take(_buy(f"B{i}", 1.0, 1200.0, f"b{i}"), NOW - 5)
        feed.flush(NOW, force=True)
        self.assertEqual(pulse.dump(con, MINT, NOW), (False, None))
        st = pulse.status(con, NOW)
        self.assertEqual(st["trades_24h"], 17)
        con.close()


class DemoExit(unittest.TestCase):
    def test_open_trade_is_sold_on_a_dump_alert(self):
        import run_paper
        from paper import sim, store as pstore
        tmp = tempfile.mkdtemp()
        hype = os.path.join(tmp, "hype.db")
        con = lstore.connect(hype)
        con.execute("INSERT INTO live_alerts VALUES (?,?,?,?)", (MINT, NOW - 20, "dump", json.dumps({"why": "6 prodavača"})))
        con.commit(); con.close()
        cfg = sim.load_config(learned=False)
        old_db, old_mk, old_hype = run_paper.DB, run_paper.market, lstore.HYPE_DB
        run_paper.DB, lstore.HYPE_DB = os.path.join(tmp, "paper.db"), hype
        run_paper.market = lambda toks: {t: (0.8, 20000.0, 80000.0, "u") for t in toks}
        try:
            pc = pstore.connect(run_paper.DB)
            pos = sim.open_position(1.0, 50_000, NOW - 600, 50, cfg)
            tid = pstore.open_trade(pc, MINT, "M1", pos, cfg, 100000)
            pstore.open_trade(pc, "OTHER", "O", sim.open_position(1.0, 50_000, NOW - 600, 50, cfg), cfg, 100000)
            pc.commit(); pc.close()
            closed = run_paper.live_exits(cfg, NOW, quiet=True)
            self.assertEqual([s for s, _ in closed], ["M1"])
            pc = pstore.connect(run_paper.DB)
            st, why = pc.execute("SELECT status, exit_reason FROM trades WHERE id=?", (tid,)).fetchone()
            self.assertEqual((st, why), ("closed", "zivi_dump"))
            self.assertEqual(pc.execute("SELECT status FROM trades WHERE token='OTHER'").fetchone()[0], "open")
            self.assertEqual(run_paper.live_exits(cfg, NOW + 1, quiet=True), [])    # nothing left to sell
            pc.close()
            self.assertEqual(run_paper.live_exits({**cfg, "live": {"dump_exit": False}}, NOW), [])
        finally:
            run_paper.DB, run_paper.market, lstore.HYPE_DB = old_db, old_mk, old_hype


if __name__ == "__main__":
    unittest.main()
