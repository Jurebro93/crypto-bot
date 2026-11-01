"""Naš token (ourtoken/, ui/nastoken.py): project form validation, costs and supply split, pump.fun dev-buy math,
vault donations matched to players, influencer ranking, marketing plan, live advice, pages and forms. No network."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ourtoken import advisor, costs, store, treasury  # noqa: E402
from ui import nastoken  # noqa: E402

VAULT = "84AWq5MbyGf2QrMMcaCnRbG3wAnjn7vy5N5WAnBZMdTs"
IVAN = "7" * 44
MINT = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"


class Base(unittest.TestCase):
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "nastoken.db")
        nastoken._SOL.update(ts=time.time(), px=100.0)
        nastoken.store_users = lambda: ["Ivan", "Jure"]
        advisor._CACHE.update(hours=(time.time(), None), lift=(time.time(), None), partners=(time.time(), []))
        treasury._CACHE.clear()
        os.environ["NAS_TOKEN_TREZOR"] = ""


class Form(Base):
    def test_validation(self):
        with self.assertRaises(ValueError):
            store.clean({"name": "X", "symbol": "AB"})
        with self.assertRaises(ValueError):
            store.clean({"name": "Ime", "symbol": "A"})
        with self.assertRaises(ValueError):   # own pool needs SOL for liquidity
            store.clean({"name": "Ime", "symbol": "ABC", "launch": "raydium", "liq_sol": "0"})
        with self.assertRaises(ValueError):
            store.clean({"name": "Ime", "symbol": "ABC", "infl_pct": "20", "team_pct": "20"})
        d = store.clean({"name": "Naš Token", "symbol": "na-sh!", "launch": "pumpfun", "supply": "5",
                         "website": "nas.hr"})
        self.assertEqual(d["symbol"], "NASH")
        self.assertEqual(d["supply"], 1_000_000_000)   # pump.fun is fixed
        self.assertEqual(d["website"], "https://nas.hr")

    def test_save_edit_mint_delete(self):
        con = store.connect()
        pid = store.save(con, "Jure", {"name": "Naš", "symbol": "NASH"})
        store.save(con, "Ivan", {"name": "Naš 2", "symbol": "NASH"}, pid)
        self.assertEqual(store.get(con, pid)["name"], "Naš 2")
        with self.assertRaises(ValueError):
            store.delete(con, pid, "Ivan")        # only the creator
        with self.assertRaises(ValueError):
            store.set_mint(con, pid, "nije-adresa")
        store.set_mint(con, pid, MINT)
        with self.assertRaises(ValueError):
            store.delete(con, pid, "Jure")        # a launched token stays
        self.assertEqual(store.projects(con)[0]["status"], "live")

    def test_donor_wallet_unique(self):
        con = store.connect()
        store.set_donor(con, "Ivan", IVAN)
        with self.assertRaises(ValueError):
            store.set_donor(con, "Jure", IVAN)
        with self.assertRaises(ValueError):
            store.set_donor(con, "Jure", "abc")
        self.assertEqual(store.donors(con), {"Ivan": IVAN})


class Costs(unittest.TestCase):
    def test_pump_curve(self):
        self.assertAlmostEqual(costs.pump_buy_pct(1), 3.46, places=1)
        self.assertAlmostEqual(costs.pump_buy_pct(costs.pump_sol_for_pct(8)), 8, places=6)

    def test_launch_cost(self):
        c = costs.launch_cost({"launch": "raydium", "liq_sol": 10, "dev_buy_sol": 0, "mkt_usd": 300}, 100)
        self.assertAlmostEqual(c["sol"], 10.22)
        self.assertAlmostEqual(c["usd"], 1322)
        p = costs.launch_cost({"launch": "pumpfun", "dev_buy_sol": 1, "mkt_usd": 0}, 100)
        self.assertAlmostEqual(p["sol"], 1.02)
        split = costs.supply_split({"launch": "pumpfun", "infl_pct": 3, "team_pct": 5})
        self.assertAlmostEqual(sum(x for _, x, _ in split), 100)


class Vault(Base):
    def tx(self, sender, lamports, usdc=0.0):
        return {"blockTime": 1, "transaction": {"signatures": ["sig"], "message": {"accountKeys": [sender, VAULT]}},
                "meta": {"preBalances": [10**10, 0], "postBalances": [10**10 - lamports, lamports],
                         "preTokenBalances": [], "postTokenBalances": [
                             {"owner": VAULT, "mint": treasury.USDC, "uiTokenAmount": {"uiAmount": usdc}}] if usdc else []}}

    def test_incoming_and_players(self):
        out = {"blockTime": 2, "transaction": {"signatures": ["s2"], "message": {"accountKeys": [VAULT, IVAN]}},
               "meta": {"preBalances": [5 * 10**9, 0], "postBalances": [4 * 10**9, 10**9]}}
        txs = [self.tx(IVAN, 2 * 10**9), self.tx("Z" * 44, 0, usdc=50), out]
        gifts = treasury.incoming(txs, VAULT)
        self.assertEqual(len(gifts), 2)             # outgoing is not a gift
        per = treasury.by_player(gifts, {"Ivan": IVAN}, 100)
        self.assertAlmostEqual(per["Ivan"]["usd"], 200)
        self.assertAlmostEqual(per["?"]["usd"], 50)

    def test_vault_section(self):
        con = store.connect()
        self.assertIn("nema adresu", nastoken.vault_html(con, "Jure"))
        os.environ["NAS_TOKEN_TREZOR"] = VAULT
        treasury._CACHE[VAULT] = (time.time(), {"address": VAULT, "sol": 2.0, "usdc": 0.0, "error": None,
                                                "gifts": treasury.incoming([self.tx(IVAN, 2 * 10**9)], VAULT)})
        store.set_donor(con, "Ivan", IVAN)
        pid = store.save(con, "Jure", {"name": "Naš", "symbol": "NASH", "dev_buy_sol": "3.98", "mkt_usd": "0"})
        html = nastoken.vault_html(con, "Jure", store.get(con, pid))   # goal 4 SOL = $400, $200 each
        self.assertIn(VAULT, html)
        self.assertIn("✅", html)                    # Ivan sent his $200
        self.assertIn("$200", html)


class Advice(unittest.TestCase):
    def test_influencers(self):
        rows = [{"handle": "big", "followers": 60_000, "score": 60, "s": {"measured": 10, "hit_rate": 0.6,
                                                                          "rug_rate": 0.05, "prepump_rate": 0.1}},
                {"handle": "tiny", "followers": 500, "score": 70, "s": {"measured": 10, "hit_rate": 0.9}},
                {"handle": "rugger", "followers": 60_000, "score": 40, "s": {"measured": 10, "hit_rate": 0.2,
                                                                             "rug_rate": 0.5, "prepump_rate": 0.6}}]
        out = advisor.influencers(rows)
        self.assertEqual([r["handle"] for r in out], ["big", "rugger"])
        self.assertTrue(any("oprez" in w for w in out[1]["why"]))

    def test_hours_and_cocall(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE calls (token, handle, ts, views, max24, kind)")
        now = time.time()
        rows = []
        for h in range(24):
            for i in range(50):
                rows.append((f"t{h}-{i}", "a", int(now // 86400 - 2) * 86400 + h * 3600,
                             1000 if h == 12 else 100, 0.6 if h == 12 else 0.1, "call"))
        con.executemany("INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?)", rows)
        best = advisor.best_hours(con, now=now)
        self.assertIsNotNone(best)
        self.assertTrue(9 <= best["start_zg"] <= 21)
        con2 = sqlite3.connect(":memory:")
        con2.execute("CREATE TABLE calls (token, handle, ts, views, max24, kind)")
        data = [(f"g{i}", h, 1000 + j * 60, 0, 1.5 if i % 2 else 0.1, "call") for i in range(6)
                for j, h in enumerate("abc")]
        data += [(f"s{i}", "a", 1000, 0, 1.5 if i % 5 == 0 else 0.1, "call") for i in range(30)]
        con2.executemany("INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?)", data)
        lift = advisor.cocall_lift(con2)
        self.assertEqual(lift["group_n"], 6)
        self.assertAlmostEqual(lift["group_rate"], 0.5)
        self.assertAlmostEqual(lift["solo_rate"], 0.2)

    def test_live_advice(self):
        self.assertIn("ne vidi", advisor.live_advice({})[0][1])
        adv = advisor.live_advice({"price": 1, "mcap": 1e6, "liq": 1e4, "vol24": 5e4, "buys24": 30, "sells24": 60,
                                   "top10": 50, "dex": "raydium"})
        levels = [lv for lv, _ in adv]
        self.assertEqual(levels.count("bad"), 2)     # thin liquidity + concentrated holders
        self.assertIn("warn", levels)

    def test_plan(self):
        ph = advisor.plan({"symbol": "NASH", "launch": "pumpfun", "mkt_usd": 500}, None, None, [{"handle": "x"}])
        self.assertEqual(len(ph), 4)
        self.assertTrue(any("@x" in s for s, _, _ in ph[0][1]))


class Pages(Base):
    def test_pages_and_forms(self):
        advisor.live_stats = lambda m: {"price": 0.001, "mcap": 1e6, "liq": 2e5, "vol24": 3e5, "buys24": 80,
                                        "sells24": 40, "url": None}
        loc = nastoken.post("/nas-token/novi", {"name": "Naš", "symbol": "NASH"}, "Jure")
        self.assertTrue(loc.startswith("/nas-token/1?ok="))
        self.assertIn("err=", nastoken.post("/nas-token/novi", {"name": "N", "symbol": "NASH"}, "Jure"))
        self.assertIn("prijavi", nastoken.post("/nas-token/novi", {}, None))
        title, body = nastoken.page({}, "Jure")
        self.assertIn("$NASH", body)
        title, body = nastoken.project_page(1, {}, "Jure")
        self.assertIn("Paket za lansiranje", body)
        self.assertIn("pump.fun/create", body)
        self.assertIn("ok=", nastoken.post("/nas-token/1/adresa", {"mint": MINT}, "Jure"))
        title, body = nastoken.project_page(1, {}, "Jure")
        self.assertIn("Brojke tokena uživo", body)
        self.assertIn("Što alat predlaže", body)
        self.assertIn("ok=", nastoken.post("/nas-token/novcanik", {"address": IVAN}, "Jure"))
        self.assertIn("Nema tog", nastoken.project_page(99, {}, "Jure")[1])


class Launch(Base):
    def test_test_mint_kept_apart(self):
        con = store.connect()
        pid = store.save(con, "Jure", {"name": "Naš", "symbol": "NASH"})
        store.set_mint(con, pid, MINT, "test")
        p = store.get(con, pid)
        self.assertEqual((p["test_mint"], p["mint"], p["status"]), (MINT, None, "test"))

    def test_buttons_locked_until_test_and_go_ahead(self):
        os.environ.pop("NAS_TOKEN_MAINNET", None)
        con = store.connect()
        pid = store.save(con, "Jure", {"name": "Naš", "symbol": "NASH", "image_url": "https://x.hr/a.png"})
        html = nastoken.launch_html(store.get(con, pid), "h")
        self.assertIn("data-net=devnet", html)
        self.assertNotIn("data-net=mainnet", html)
        store.set_mint(con, pid, MINT, "test")
        self.assertNotIn("data-net=mainnet", nastoken.launch_html(store.get(con, pid), "h"))
        os.environ["NAS_TOKEN_MAINNET"] = "1"
        try:
            html = nastoken.launch_html(store.get(con, pid), "h")
            self.assertIn("data-launch=pump data-net=mainnet", html)
            self.assertIn("/nas-token/1/meta.json", html)
        finally:
            os.environ.pop("NAS_TOKEN_MAINNET", None)

    def test_api_gates(self):
        os.environ.pop("NAS_TOKEN_MAINNET", None)
        self.assertEqual(nastoken.api_post("/nas-token/rpc", {"net": "devnet", "method": "getLatestBlockhash"}, None)[0], 401)
        self.assertEqual(nastoken.api_post("/nas-token/rpc", {"net": "devnet", "method": "getBalance"}, "Jure")[0], 400)
        self.assertEqual(nastoken.api_post("/nas-token/rpc", {"net": "mainnet", "method": "sendTransaction"}, "Jure")[0], 403)
        self.assertEqual(nastoken.api_post("/nas-token/1/pump-tx", {}, "Jure")[0], 403)

    def test_meta_json(self):
        import json
        con = store.connect()
        pid = store.save(con, "Jure", {"name": "Naš", "symbol": "NASH", "image_url": "https://x.hr/a.png",
                                       "x_url": "x.com/nash"})
        m = json.loads(nastoken.meta_json(pid))
        self.assertEqual((m["symbol"], m["image"], m["twitter"]), ("NASH", "https://x.hr/a.png", "https://x.com/nash"))
        self.assertIsNone(nastoken.meta_json(99))

    def test_pumpportal_tx_check(self):
        raw = open(os.path.join(os.path.dirname(__file__), "fixtures", "pumpportal_create.bin"), "rb").read()
        payer, mint = VAULT, "7Hx2bP4o1Dc6b2fKjnS5xCw3J3bm9yZ1xTqT5rWk5uZp"
        self.assertTrue(nastoken.tx_ok(raw, payer, mint))
        self.assertFalse(nastoken.tx_ok(raw, mint, payer))
        self.assertFalse(nastoken.tx_ok(raw[:50], payer, mint))


class Strategy(Base):
    def test_page(self):
        title, body = nastoken.strategy_page({}, "Jure")
        self.assertIn("$NAŠ", body)                  # no project yet: generic ticker
        con = store.connect()
        pid = store.save(con, "Jure", {"name": "Radar", "symbol": "RADAR"})
        title, body = nastoken.strategy_page({"t": str(pid)}, "Jure")
        for part in ("Ukratko", "tim od 4", "Claude Code", "Besplatno", "Izvori", "$RADAR"):
            self.assertIn(part, body)
        self.assertNotIn("{SYM}", body)


if __name__ == "__main__":
    unittest.main()
