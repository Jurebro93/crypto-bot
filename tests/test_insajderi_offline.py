"""5.11.: insider wallets as a signal (kol/insiders.py), the "insajderi" demo strategy, the webhook share and the
wallet "what could we have taken" ladder.

    python3 -m unittest tests.test_insajderi_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import insiders, store as kstore  # noqa: E402

NOW = int(time.time())
H = 3600


def _kol(path):
    con = kstore.connect(path)
    # token T1: a called at 1000, b at 1300, c at 1600; insiders W1, W2 bought before, W1 sold 2 min after the 3rd call
    for h, ts in (("a", 1000), ("b", 1300), ("c", 1600)):
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?, 'T1', ?, ?, 'call')", (h + "1", h, ts))
    for h, ts in (("a", 5000), ("b", 5200)):
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?, 'T2', ?, ?, 'call')", (h + "2", h, ts))
    rows = [("W1", "T1", 1000, 400, 1720, 1.0, 2.0), ("W2", "T1", 1000, 500, None, 1.0, None),
            ("W1", "T2", 5000, 4500, 5100, 1.0, 1.5), ("W3", "T2", 5000, 4900, 5260, 0.5, 0.7), ("W2", "T2", 5000, 4800, None, 1, None)]
    for r in rows:
        con.execute("INSERT INTO insiders VALUES (?,?,?,?,?,?,?)", r)
    con.execute("INSERT INTO tokens (token, created_ts) VALUES ('T1', 300)")
    con.execute("INSERT INTO tokens (token, created_ts) VALUES ('T2', 4000)")
    con.execute("INSERT INTO tokens (token, created_ts) VALUES ('N1', 9000)")
    con.commit()
    return con


class Wallets(unittest.TestCase):
    def test_ranking_and_sell_timing(self):
        con = _kol(os.path.join(tempfile.mkdtemp(), "kol.db"))
        self.assertEqual(insiders.wallets(con, 2), [("W1", 2, 2), ("W2", 2, 0)])    # W3: one token only
        t = insiders.sell_timing(con)
        self.assertEqual(t["n"], 2)
        self.assertEqual(t["to_3rd"]["n"], 1)                     # only T1 has a third caller
        self.assertAlmostEqual(t["to_3rd"]["med"], 2.0)           # sold 120 s after the 3rd call
        self.assertEqual(t["to_2nd"]["n"], 3)
        self.assertAlmostEqual(t["to_2nd"]["med"], 1.0)           # T2: sold 100 s and 60 s before... (5100-5200)/60=-1.7, (5260-5200)/60=1, T1: 7 -> median 1.0
        con.close()


class Profile(unittest.TestCase):
    def test_insider_vs_sniper(self):
        tmp = tempfile.mkdtemp()
        kol = os.path.join(tmp, "kol.db")
        _kol(kol).close()
        from wallets import store as wstore
        w = wstore.connect(os.path.join(tmp, "wallets.db"))
        # INS: bought T1 and T2 (both later called), minutes after launch
        for mint, ts in (("T1", 400), ("T2", 4500)):
            w.execute("INSERT INTO wallet_trades VALUES ('INS', ?, ?, ?, 100, -1.0, 'buy')", (f"s{mint}", ts, mint))
        # SNIP: 12 launches in their first 5 seconds, only one ever called
        for i in range(12):
            mint = "N1" if i == 0 else f"X{i}"
            w.execute("INSERT INTO wallet_trades VALUES ('SNIP', ?, ?, ?, 100, -1.0, 'buy')", (f"q{i}", 9003 if i == 0 else 20000 + i, mint))
        w.commit(); w.close()
        p = insiders.profile("INS", os.path.join(tmp, "wallets.db"), kol)
        self.assertEqual((p["bought"], p["called"], p["sniper"]), (2, 2, False))
        self.assertEqual(p["med_secs_after_launch"], 300)        # (100 + 500) / 2
        q = insiders.profile("SNIP", os.path.join(tmp, "wallets.db"), kol)
        self.assertTrue(q["sniper"])
        self.assertEqual(q["called_share"], 0.0)                 # N1 was never called in this fixture
        self.assertEqual(q["med_secs_after_launch"], 3)
        self.assertIsNone(insiders.profile("NOBODY", os.path.join(tmp, "wallets.db"), kol))


class Signal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kol = os.path.join(self.tmp, "kol.db")
        _kol(self.kol).close()
        self.hype = os.path.join(self.tmp, "hype.db")
        h = sqlite3.connect(self.hype)
        h.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, PRIMARY KEY (sig, mint))")
        rows = [("1", "W1", "NEW", "buy", NOW - 400), ("2", "W2", "NEW", "buy", NOW - 100),      # 2 insiders, uncalled: signal
                ("3", "W1", "T1", "buy", NOW - 200), ("4", "W2", "T1", "buy", NOW - 150),        # called token: no
                ("5", "W1", "ONE", "buy", NOW - 50),                                              # one wallet: no
                ("6", "W9", "NEW", "buy", NOW - 90),                                              # not an insider
                ("7", "W2", "NEW", "sell", NOW + 500)]
        for sig, w, m, side, ts in rows:
            h.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,0.5)", (sig, w, m, side, ts))
        h.commit(); h.close()

    def test_signal_and_exit(self):
        got = insiders.signal(self.hype, self.kol, {"W1", "W2"}, NOW, window_s=600, min_wallets=2)
        self.assertEqual(len(got), 1)
        tok, ts, who, score = got[0]
        self.assertEqual((tok, ts, score), ("NEW", NOW - 100, 2))          # the buy that completed the pair
        self.assertIn("2 insajdera prije poziva", who)
        self.assertEqual(insiders.signal(self.hype, self.kol, set(), NOW), [])
        self.assertEqual(insiders.sold_since(self.hype, "NEW", NOW, {"W1", "W2"}), NOW + 500)
        self.assertIsNone(insiders.sold_since(self.hype, "NEW", NOW + 600, {"W1", "W2"}))

    def test_strategy_enters_and_exits_with_the_insiders(self):
        from strat import run, store
        cfg = run.load_config()
        cfg = {**cfg, "strategies": [s for s in cfg["strategies"] if s["key"] in ("insajderi", "kontrola")]}
        path = os.path.join(self.tmp, "strat.db")

        class Src:
            kol_db, hype_db = self.kol, self.hype

            def read(self, now, window_s):
                self.insiders = {"W1", "W2"}
                return {"novcanici": [], "kol": [], "alat": [], "scored": [],
                        "insajderi": insiders.signal(self.hype_db, self.kol_db, self.insiders, now, window_s, 2)}
        mk = lambda toks: {t: (1.0, 20000.0, 100000.0, t, "u") for t in toks}
        con = store.connect(path)
        store.kv_set(con, "start_ts", NOW - 3600)   # the account started an hour ago: signals from before "start" are skipped
        con.commit(); con.close()
        r = run.step(now=NOW, cfg=cfg, path=path, market_fn=mk, sources=Src(), quiet=True)
        self.assertEqual(r["entered"], 1)
        con = store.connect(path)
        p = store.rows(con, "strat='insajderi'")[0]
        self.assertEqual((p["token"], p["status"]), ("NEW", "open"))
        con.close()
        r2 = run.step(now=NOW + 700, cfg=cfg, path=path, market_fn=mk, sources=Src(), quiet=True)   # W2 sold at +500
        con = store.connect(path)
        p = store.rows(con, "strat='insajderi'")[0]
        self.assertEqual((p["status"], p["exit_reason"]), ("closed", "insajderi prodaju"))
        con.close()


class WebhookShare(unittest.TestCase):
    def test_insiders_take_their_share(self):
        from kol import chainwatch, idents
        con = _kol(os.path.join(tempfile.mkdtemp(), "kol.db"))
        idents.save(con, [{"wallet": f"ID{i}", "name": f"k{i}", "twitter": None, "telegram": None, "pnl": 1, "wins": 1,
                           "losses": 0, "rank": i} for i in range(10)], "kolscan")
        got = chainwatch.wanted(con, {"max_wallets": 10, "share": {"ids": 0.5, "copy": 0.3, "signal": 0.0, "insajderi": 0.2}},
                                wallet_db=os.path.join(tempfile.mkdtemp(), "none.db"))
        self.assertEqual(got[:5], ["ID0", "ID1", "ID2", "ID3", "ID4"])
        self.assertEqual(got[5:7], ["W1", "W2"])                 # the two insider wallets (W3 has one token)
        self.assertEqual(len(got), 10)                            # leftovers back to the leaderboard
        con.close()


class FollowedWalletsInWebhook(unittest.TestCase):
    def test_a_players_followed_wallet_is_tracked_first(self):
        from kol import chainwatch, idents
        from league import copy as lcopy, store as lstore
        tmp = tempfile.mkdtemp()
        con = _kol(os.path.join(tmp, "kol.db"))
        idents.save(con, [{"wallet": f"ID{i}", "name": f"k{i}", "twitter": None, "telegram": None, "pnl": 1, "wins": 1,
                           "losses": 0, "rank": i} for i in range(10)], "kolscan")
        old, lstore.DB = lstore.DB, os.path.join(tmp, "league.db")
        try:
            lc = lstore.connect(lstore.DB)
            lc.executescript(lcopy.SCHEMA)
            lcopy.follow(lc, "Jure", "wallet", "FOLLOWEDWALLET" + "x" * 30, size_usd=25)
            lc.commit(); lc.close()
            got = chainwatch.wanted(con, {"max_wallets": 8}, wallet_db=os.path.join(tmp, "none.db"))
        finally:
            lstore.DB = old
            con.close()
        self.assertEqual(got[0], "FOLLOWEDWALLET" + "x" * 30)
        self.assertEqual(len(got), 8)


class Ladder(unittest.TestCase):
    def test_what_could_have_been_taken(self):
        from ui import preporuka
        from wallets import store as wstore
        tmp = tempfile.mkdtemp()
        w = wstore.connect(os.path.join(tmp, "wallets.db"))
        for i, mint in enumerate(("A", "B", "C", "D")):
            w.execute("INSERT INTO wallet_trades VALUES ('X', ?, ?, ?, 100, -1.0, 'buy')", (f"s{i}", NOW - 5 * H, mint))
        w.commit(); w.close()
        h = sqlite3.connect(os.path.join(tmp, "hype.db"))
        h.execute("CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, PRIMARY KEY (token, ts))")
        paths = {"A": [1.0, 1.2, 1.1], "B": [1.0, 1.4, 1.6], "C": [1.0, 0.9, 0.8]}    # D: no snapshots
        for mint, pxs in paths.items():
            for j, px in enumerate(pxs):
                h.execute("INSERT INTO hype_snapshots VALUES (?,?,?,0,0)", (mint, NOW - 5 * H + j * 1200, px))
        h.commit(); h.close()
        l = preporuka.wallet_ladder("X", wallet_db=os.path.join(tmp, "wallets.db"), hype_db=os.path.join(tmp, "hype.db"),
                                    paper_db=os.path.join(tmp, "none.db"))
        self.assertEqual((l["buys"], l["checked"]), (4, 3))
        self.assertEqual(l["hit"], {0.15: round(2 / 3, 2), 0.30: round(1 / 3, 2), 0.50: round(1 / 3, 2)})
        self.assertAlmostEqual(l["med_max"], 0.2)
        s = preporuka.ladder_sentence(l)
        self.assertIn("od 3 kupnji koje možemo provjeriti cijenom (od 4 u 30 dana), 67% je dalo barem +15 %", s)


if __name__ == "__main__":
    unittest.main()
