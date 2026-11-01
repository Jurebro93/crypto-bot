"""Copy trading (league/copy.py, ui/copytrade.py): follow a KOL or a wallet, entries, skips, mirrored sells. No network."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store  # noqa: E402

A = "A" * 43
B = "B" * 43
C = "C" * 43
W = "W" * 44


class Copy(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        store.DB = os.path.join(d, "league.db")
        self.paths = {"kol": os.path.join(d, "kol.db"), "hype": os.path.join(d, "hype.db"),
                      "tg": os.path.join(d, "tg.db")}
        os.environ.update(KOL_DB=self.paths["kol"], HYPE_DB=self.paths["hype"], TG_DB=self.paths["tg"])
        k = sqlite3.connect(self.paths["kol"])
        k.executescript("""CREATE TABLE calls (token TEXT, handle TEXT, ts INTEGER, kind TEXT);
            CREATE TABLE kols (handle TEXT, followers INTEGER, score REAL, stats TEXT, bot INTEGER DEFAULT 0);
            CREATE TABLE monitor (handle TEXT);
            CREATE TABLE kol_ids (wallet TEXT, name TEXT, twitter TEXT, source TEXT, pnl REAL, wins INTEGER,
                                  losses INTEGER, rank INTEGER);
            CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);""")
        k.execute("INSERT INTO kols VALUES ('goodkol', 5000, 60, ?, 0)",
                  (json.dumps({"measured": 8, "hit_rate": 0.6, "med_max24": 0.9, "rug_rate": 0.1}),))
        k.execute("INSERT INTO kols VALUES ('scanbot', 100, 70, ?, 1)", (json.dumps({"measured": 50}),))
        k.execute("INSERT INTO monitor VALUES ('goodkol')")
        k.execute("INSERT INTO kol_ids VALUES (?, 'Trader', 'tradr', 'kolscan', 12000, 30, 10, 1)", (W,))
        k.execute("INSERT INTO kv VALUES ('chain_hook', ?)", (json.dumps({"wallets": [W]}),))
        k.commit()
        self.k = k
        h = sqlite3.connect(self.paths["hype"])
        h.executescript("""CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);
            CREATE TABLE kol_mentions (handle TEXT, ca TEXT, ts INTEGER);""")
        h.commit()
        self.h = h
        self.mk = {A: (1.0, 50000, None, 1e6, "AAA"), B: (1.0, 2000, None, 1e6, "BBB"), C: (1.0, 5e6, None, 1e6, "CCC")}

    def market(self, toks):
        return {t: self.mk[t] for t in toks if t in self.mk}

    def test_kol_follow_enters_fresh_call_and_skips_bad(self):
        con = store.connect()
        now = int(time.time())
        fid = copy.follow(con, "Ivan", "kol", "goodkol", "@goodkol", 40, 10, "smart")
        con.execute("UPDATE follows SET created=?", (now - 3600,))
        con.commit()
        self.h.execute("INSERT INTO kol_mentions VALUES ('goodkol', ?, ?)", (A, now - 30))       # fresh: enter
        self.k.execute("INSERT INTO calls VALUES (?, 'goodkol', ?, 'call')", (A, now - 25))     # same token again
        self.k.execute("INSERT INTO calls VALUES (?, 'goodkol', ?, 'call')", (B, now - 60))     # liq $2k: skip
        self.k.execute("INSERT INTO calls VALUES (?, 'goodkol', ?, 'call')", (C, now - 60))     # liq > mcap: skip
        self.k.execute("INSERT INTO calls VALUES (?, 'otherkol', ?, 'call')", (C, now - 60))    # not followed
        self.k.commit()
        self.h.commit()
        done = copy.run_once(con, self.market, now, self.paths)
        self.assertEqual(len(done), 1)
        t = store.trades(con, "Ivan", "open")
        self.assertEqual((len(t), t[0]["token"], t[0]["size_usd"], t[0]["follow_id"]), (1, A, 40, fid))
        self.assertIn("smart", t[0]["auto"])
        acts = {r["token"]: (r["action"], r["note"]) for r in copy.log(con)}
        self.assertEqual(acts[A][0], "ulaz")
        self.assertIn("likvidnost", acts[B][1])
        self.assertIn("lažni pool", acts[C][1])
        self.assertEqual(copy.run_once(con, self.market, now + 60, self.paths), [])   # nothing twice
        # late call is not entered
        self.k.execute("INSERT INTO calls VALUES (?, 'goodkol', ?, 'call')", ("D" * 43, now - 1800))
        self.k.commit()
        copy.run_once(con, self.market, now + 120, self.paths)
        self.assertIn("prekasno", {r["token"]: r["note"] for r in copy.log(con)}["D" * 43])
        self.assertEqual(copy.follow_results(con)[fid]["open"], 1)

    def test_wallet_copy_buys_and_mirrors_sell(self):
        con = store.connect()
        now = int(time.time())
        fid = copy.follow(con, "Panda", "wallet", W, "Trader", 30, 5, "mirror")
        self.h.execute("INSERT INTO chain_trades VALUES ('s1', ?, ?, 'buy', ?, 1.0)", (W, A, now + 5))
        self.h.commit()
        copy.run_once(con, self.market, now + 10, self.paths)
        t = store.trades(con, "Panda", "open")
        self.assertEqual(len(t), 1)
        self.assertIsNone(t[0]["auto"])
        self.mk[A] = (2.0, 50000, None, 2e6, "AAA")
        self.h.execute("INSERT INTO chain_trades VALUES ('s2', ?, ?, 'sell', ?, NULL)", (W, A, now + 70))
        self.h.commit()
        done = copy.run_once(con, self.market, now + 80, self.paths)
        self.assertEqual(len(done), 1)
        closed = store.trades(con, "Panda", "closed")
        self.assertEqual(len(closed), 1)
        self.assertGreater(closed[0]["pnl_usd"], 20)
        r = copy.follow_results(con)[fid]
        self.assertEqual((r["closed"], r["wins"]), (1, 1))
        copy.unfollow(con, "Panda", fid)
        with self.assertRaises(ValueError):
            copy.unfollow(con, "Panda", fid)
        self.assertEqual(copy.follows(con, "Panda"), [])

    def test_per_day_cap_and_cash(self):
        con = store.connect()
        now = int(time.time())
        copy.follow(con, "Jure", "wallet", W, "Trader", 30, 1, "mirror")
        self.mk["E" * 43] = (1.0, 50000, None, 1e6, "EEE")
        self.h.execute("INSERT INTO chain_trades VALUES ('s1', ?, ?, 'buy', ?, 1.0)", (W, A, now + 1))
        self.h.execute("INSERT INTO chain_trades VALUES ('s2', ?, ?, 'buy', ?, 1.0)", (W, "E" * 43, now + 2))
        self.h.commit()
        copy.run_once(con, self.market, now + 10, self.paths)
        self.assertEqual(len(store.trades(con, "Jure", "open")), 1)
        self.assertIn("limit", {r["token"]: r["note"] for r in copy.log(con)}["E" * 43])

    def test_follow_validation(self):
        con = store.connect()
        with self.assertRaises(ValueError):
            copy.follow(con, "Ivan", "kol", "goodkol", size_usd=10000)
        with self.assertRaises(ValueError):
            copy.follow(con, "Ivan", "kol", "goodkol", exit_mode="mirror")
        with self.assertRaises(ValueError):
            copy.follow(con, "Ivan", "kol", "goodkol", exit_mode="tpsl", tp="abc")
        fid = copy.follow(con, "Ivan", "kol", "goodkol", exit_mode="tpsl", tp="100%", sl="-30%")
        self.assertEqual(copy.follow(con, "Ivan", "kol", "goodkol", size_usd=50), fid)   # update, not a second one

    def test_page_and_forms(self):
        from ui import copytrade
        copytrade._CACHE.clear()
        loc = copytrade.post("/natjecanje/copy/follow", {"kind": "kol", "target": "goodkol", "label": "@goodkol",
                                                          "size": "25", "per_day": "10", "exit": "smart"}, "Ivan")
        self.assertIn("ok=", loc)
        self.assertIn("err=", copytrade.post("/natjecanje/copy/follow", {"kind": "kol", "target": "x"}, None))
        for user in ("Ivan", "Panda", None):
            title, body = copytrade.page({}, user)
            self.assertEqual(title, "Copy trading")
            self.assertIn("goodkol", body)
            self.assertNotIn("scanbot", body)          # bot accounts are not offered
            self.assertIn("Trader", body)              # live-followed wallet with its public stats
        body = copytrade.page({}, "Panda")[1]
        self.assertIn("Uđi na njihov call prvi", body)
        self.assertIn("Copy trade-aj ovaj wallet", body)
        self.assertIn("pratiš ✓", copytrade.page({}, "Ivan")[1])
        fid = copy.follows(store.connect(), "Ivan")[0]["id"]
        self.assertIn("ok=", copytrade.post("/natjecanje/copy/stop", {"id": str(fid)}, "Ivan"))


if __name__ == "__main__":
    unittest.main()
