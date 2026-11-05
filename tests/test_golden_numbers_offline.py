"""Golden numbers (4.11. evening, after a day of "this number is wrong"): ONE synthetic set of databases with known
contents, rendered through every place that shows a count, and each shown number must equal the known truth.

Known truth built below:
  kol.db      4 X accounts (one a bot), 1 Telegram channel, 1 tracked wallet; 6 real calls (5 X + 1 Telegram),
              1 brag, 30 wallet swaps; 4 of the 6 calls measured, 2 of them 2x
  tg.db       2 channels, 3 posts
  wallets.db  3 wallets
  hype.db     2 tokens in token_tier, 1 archived rug, 2 hype_signals tokens
  paper.db    1 candidate, 1 trade

If a page needs a different definition of a number, change the page or this truth table on purpose, never silently.

    python3 -m unittest tests.test_golden_numbers_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOW = int(time.time())
DAY = 86400


def build(tmp):
    """Create every database with the known rows. Returns {name: path}."""
    from hype import store as hstore
    from kol import store as kstore
    from paper import store as pstore
    from tg import store as tstore
    from wallets import store as wstore
    p = {n: os.path.join(tmp, n + ".db") for n in ("kol", "tg", "wallets", "hype", "paper")}

    k = kstore.connect(p["kol"])
    for h, foll, bot in (("alice", 5000, 0), ("bob", 800, 0), ("carol", 120000, 0), ("scanbot", 300, 1),
                         ("tg:gemcalls", 0, 0), ("w:7xKXtg", 0, 0)):
        k.execute("INSERT INTO kols (handle, followers, first_seen, bot) VALUES (?,?,?,?)", (h, foll, NOW - 3 * DAY, bot))
    calls = [("1", "T1", "alice", "call", 1.5), ("2", "T2", "alice", "call", 0.1), ("3", "T1", "bob", "call", 2.2),
             ("4", "T3", "carol", "call", None), ("5", "T4", "scanbot", "call", 0.0), ("6", "T2", "tg:gemcalls", "call", None),
             ("7", "T1", "alice", "brag", None)]
    for tid, tok, h, kind, m in calls:
        k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24, first_by_kol) VALUES (?,?,?,?,?,?,1)",
                  (tid, tok, h, NOW - 2 * DAY, kind, m))
    for i in range(30):
        k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?, 'T9', 'w:7xKXtg', ?, ?)",
                  (f"s{i}", NOW - DAY, "buy" if i % 2 else "sell"))
    k.commit(); k.close()

    t = tstore.connect(p["tg"])
    for ch in ("gemcalls", "alphachat"):
        t.execute("INSERT INTO channels (name, found_ts, status) VALUES (?, ?, 'active')", (ch, NOW - 2 * DAY))
    for ch in ("deadspam1", "deadspam2", "candidate3"):   # known but not active: never "Telegram kanali" on Pregled
        t.execute("INSERT INTO channels (name, found_ts, status) VALUES (?, ?, ?)",
                  (ch, NOW - 2 * DAY, "candidate" if ch.startswith("cand") else "dead"))
    for i in range(3):
        t.execute("INSERT INTO posts (channel, post, ts, seen_ts, cas) VALUES ('gemcalls', ?, ?, ?, 'T2')",
                  (i, NOW - DAY, NOW - DAY))
    t.commit(); t.close()

    w = wstore.connect(p["wallets"])
    for i in range(3):
        w.execute("INSERT INTO wallets (wallet, first_seen, last_seen) VALUES (?, ?, ?)", (f"W{i}", NOW - DAY, NOW))
    w.commit(); w.close()

    h = hstore.connect(p["hype"])
    h.executescript("""CREATE TABLE IF NOT EXISTS token_tier (token TEXT PRIMARY KEY, klasa TEXT);
                       CREATE TABLE IF NOT EXISTS rug_archive (token TEXT PRIMARY KEY, archived_ts INTEGER);""")
    h.execute("INSERT INTO token_tier VALUES ('T1', 'mali')"); h.execute("INSERT INTO token_tier VALUES ('T2', 'mali')")
    h.execute("INSERT INTO rug_archive VALUES ('T8', ?)", (NOW - DAY,))
    for tok in ("T1", "T2"):
        h.execute("INSERT INTO hype_signals (ts, token, symbol, score, price, mcap, liquidity, features, sources) "
                  "VALUES (?, ?, ?, 55, 1.0, 1e5, 2e4, '{}', 'profile')", (NOW - DAY, tok, tok))
    h.commit(); h.close()

    pp = pstore.connect(p["paper"])
    pp.execute("INSERT INTO candidates (token, first_ts, origin, decision) VALUES ('T1', ?, 'hype', 'taken')", (NOW - DAY,))
    pp.execute("INSERT INTO trades (token, symbol, opened_ts, status, size_usd, entry_px, config) "
               "VALUES ('T1', 'T1', ?, 'open', 50, 1.0, '{}')", (NOW - DAY,))
    pp.commit(); pp.close()
    return p


TRUTH = {"x_accounts": 4, "x_accounts_not_bot": 3, "x_calls": 5, "calls_all_kinds": 6, "wallet_swaps": 30,
         "measured_calls": 4, "measured_2x": 2, "tg_channels": 2, "tg_posts": 3, "wallets": 3,
         "tokens_checked": 3, "tokens_analysed": 3}   # tokens analysed: T1, T2 (hype) + T1 (candidate) = 2 distinct + rug? see test


class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.p = build(cls.tmp)
        from kol import store as kstore
        from tg import store as tstore
        from wallets import store as wstore
        from ui import data, landing
        cls.saved = {}

        def patch(mod, name, val):
            cls.saved[(mod, name)] = getattr(mod, name)
            setattr(mod, name, val)
        patch(kstore, "DB", cls.p["kol"])
        cls.old_env = os.environ.get("KOL_DB")
        os.environ["KOL_DB"] = cls.p["kol"]          # ui/public.py reads the env, not kol.store.DB
        patch(tstore, "DB", cls.p["tg"])
        patch(wstore, "DB", cls.p["wallets"])
        patch(landing, "HERE", cls.tmp)
        patch(data, "HERE", cls.tmp)
        patch(data, "HYPE_DB", cls.p["hype"])
        patch(data, "WALLET_DB", cls.p["wallets"])
        patch(data, "PAPER_DB", cls.p["paper"])
        patch(data, "RUG_DB", os.path.join(cls.tmp, "rug.db"))
        patch(data, "CAL_DB", os.path.join(cls.tmp, "calendar.db"))
        patch(data, "GROUPS", {"wallets": [cls.p["wallets"]], "rug": [data.RUG_DB], "hype": [cls.p["hype"]],
                               "cal": [data.CAL_DB], "paper": [cls.p["paper"]]})

    @classmethod
    def tearDownClass(cls):
        for (mod, name), val in cls.saved.items():
            setattr(mod, name, val)
        if cls.old_env is None:
            os.environ.pop("KOL_DB", None)
        else:
            os.environ["KOL_DB"] = cls.old_env

    def test_landing(self):
        from ui import landing
        v = landing.compute()
        self.assertEqual(v["kols"], TRUTH["x_accounts"])                   # X accounts only: not tg:, not w:
        self.assertEqual(v["calls"], TRUTH["calls_all_kinds"])             # kind = 'call', X and Telegram
        self.assertEqual(v["wallets"], TRUTH["wallets"])
        self.assertEqual(v["tokens"], TRUTH["tokens_checked"])             # token_tier + rug_archive
        self.assertEqual(v["measured"], TRUTH["measured_calls"])
        self.assertAlmostEqual(v["call_2x"], TRUTH["measured_2x"] / TRUTH["measured_calls"])

    def test_pregled_tiles(self):
        from ui import pocetna
        by = {label: c for _, label, _, c in pocetna.metrics(NOW)}
        self.assertEqual(by["Influenceri (X)"][0], TRUTH["x_accounts"])
        self.assertEqual(by["Pozivi influencera (X + Telegram)"][0], TRUTH["calls_all_kinds"])
        self.assertEqual(by["Kupnje i prodaje praćenih novčanika"][0], TRUTH["wallet_swaps"])
        self.assertEqual(by["Aktivni Telegram kanali"][0], TRUTH["tg_channels"])
        # the same number on /izvori ("aktivnih Telegram kanala"): one truth, two pages
        import sqlite3
        st = dict(sqlite3.connect(self.p["tg"]).execute("SELECT status, COUNT(*) FROM channels GROUP BY status"))
        self.assertEqual(st["active"], by["Aktivni Telegram kanali"][0])
        self.assertEqual(by["Telegram poruke"][0], TRUTH["tg_posts"])
        self.assertEqual(by["Novčanici u registru"][0], TRUTH["wallets"])
        self.assertEqual(by["Rug provjere"][0], 0) if "Rug provjere" in by else None
        # "this week" = everything (all rows are 1-3 days old), last week = 0
        for label, (total, new, prev) in by.items():
            self.assertEqual((new, prev), (total, 0), label)

    def test_pregled_row_total_is_a_row_count(self):
        from ui import pocetna
        rows, size, n_db = pocetna._db_totals_now()
        self.assertEqual(n_db, 5)
        self.assertGreater(size, 0)
        self.assertLess(rows, 2000)          # was ~7 billion when timestamp keys were summed

    def test_public_leaderboard_and_proven(self):
        from ui import kolsummary, public
        from kol import store as kstore
        con = kstore.connect(self.p["kol"])
        try:
            cfg = {"good_score": 50}
            self.assertEqual(kolsummary.proven(con, cfg), [])          # nobody scored yet: 0, and that is the truth
            con.execute("UPDATE kols SET score = 70, stats = ? WHERE handle = 'alice'",
                        (json.dumps({"measured": 12, "trial": False, "hit_rate": 0.6}),))
            # a bot keeps score NULL (kol/score.score_kols stores it as bot_score), so it can never be "proven"
            con.execute("UPDATE kols SET score = NULL, stats = ? WHERE handle = 'scanbot'",
                        (json.dumps({"measured": 50, "trial": False, "bot_score": 80}),))
            con.commit()
            self.assertEqual([h for _, h, _, _ in kolsummary.proven(con, cfg)], ["alice"])
        finally:
            con.close()
        rows = public.influencers()
        self.assertEqual([r["handle"] for r in rows], ["alice"])        # the bot never reaches the public list


if __name__ == "__main__":
    unittest.main()
