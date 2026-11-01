"""Webhook posts get their real X post id/link/time (no duplicate of a searched post), EVM tails are no tokens,
and calls are re-measured at the 1 h / 6 h / 24 h checkpoints instead of every hour."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import collect, measure, score, store  # noqa: E402

CA = "3SsN2bTbu78Y9riYnjfEcnQemXd1jRY6F535zAdFi4Ly"
TID = "2116886825734463905"
HOOK_TEXT = (f"{TID} https://x.com/bitecong/status/{TID} {TID} 1793543723000 en 🤖 AI Signal (SOL) $sharkcat\n\n"
             f"CA: {CA}\n\nsharkcat is about a minute old")
H = 3600


def hype_db(rows):
    path = os.path.join(tempfile.mkdtemp(), "hype.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE kol_mentions (ts INTEGER, handle TEXT, ca TEXT, tickers TEXT, text TEXT)")
    con.executemany("INSERT INTO kol_mentions VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


class Hook(unittest.TestCase):
    def setUp(self):
        self.con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))

    def test_hook_post_fields(self):
        tid, h, ts, url, text = collect.hook_post("bitecong", 1793540124, HOOK_TEXT)
        self.assertEqual((tid, h, url), (TID, "bitecong", f"https://x.com/bitecong/status/{TID}"))
        self.assertEqual(ts, 1793540123)  # from the post id, not the time the webhook arrived
        self.assertTrue(text.startswith("🤖 AI Signal"))

    def test_no_duplicate_of_searched_post(self):
        searched = {"id": TID, "url": f"https://x.com/bitecong/status/{TID}", "text": HOOK_TEXT.split(" en ", 1)[1],
                    "createdAt": 1793540123, "author": {"userName": "bitecong", "followers": 38000}}
        collect.save(self.con, collect.calls_from_tweet(searched))
        # an old-style row saved before the fix, plus the same post arriving again through the webhook
        self.con.execute("INSERT INTO calls (tweet_id, token, handle, ts, url, text, kind, match, source) VALUES "
                         "(?,?,?,?,?,?, 'call', 'ca', 'webhook')", ("hook-bitecong-1793540124", CA, "bitecong",
                                                                     1793540124, "https://x.com/bitecong", HOOK_TEXT))
        path = hype_db([(1793540124, "bitecong", CA, "SHARKCAT", HOOK_TEXT),
                        (1793540200, "bitecong", "x3ea64578738a633c2315d64473b8cfd692f97777", "", HOOK_TEXT)])
        collect.from_webhook(self.con, path)
        rows = self.con.execute("SELECT tweet_id, token, url FROM calls").fetchall()
        self.assertEqual(rows, [(TID, CA, f"https://x.com/bitecong/status/{TID}")])

    def test_old_hook_row_gets_link(self):
        self.con.execute("INSERT INTO calls (tweet_id, token, handle, ts, url, text, kind, match, source) VALUES "
                         "(?,?,?,?,?,?, 'call', 'ca', 'webhook')", ("hook-bitecong-1793540124", CA, "bitecong",
                                                                     1793540124, "https://x.com/bitecong", HOOK_TEXT))
        collect.fix_hook_rows(self.con)
        tid, url, ts, text = self.con.execute("SELECT tweet_id, url, ts, text FROM calls").fetchone()
        self.assertEqual((tid, url, ts), (TID, f"https://x.com/bitecong/status/{TID}", 1793540123))
        self.assertFalse(text.startswith(TID))

    def test_ingest_skips_evm_tail(self):
        from hype import sources
        path = os.path.join(tempfile.mkdtemp(), "hype.db")
        sources.ingest_kol_event({"user": {"username": "x"}, "text": "$BNB CA 0x3ea64578738a633c2315d64473b8cfd692f97777"},
                                 path)
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT ca FROM kol_mentions").fetchall(), [("",)])

    def test_drop_pure_hex_token(self):
        self.con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES "
                         "('1', 'cbc77d4d79a3ca2de38ada8d5edc178d6a7777', 'a', 1, 'call')")
        self.assertEqual(score.drop_fake_tokens(self.con), 1)


class Due(unittest.TestCase):
    def test_checkpoints(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        t0 = 1793500000
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, measured_ts) VALUES "
                    "('1', 'A', 'a', ?, 'call', ?)", (t0, t0 + 300))
        self.assertEqual(measure.due(con, t0 + 50 * 60, 10), [])        # measured, no checkpoint yet
        self.assertEqual(measure.due(con, t0 + H + 700, 10), ["A"])     # 1 h checkpoint passed
        con.execute("UPDATE calls SET measured_ts = ?", (t0 + H + 700,))
        self.assertEqual(measure.due(con, t0 + 3 * H, 10), [])          # not every hour any more
        self.assertEqual(measure.due(con, t0 + 6 * H + 700, 10), ["A"])
        con.execute("UPDATE calls SET mtry = ?", (t0 + 7 * H,))
        self.assertEqual(measure.due(con, t0 + 6 * H + 700, 10), [])    # waiting after a failed fetch

    def test_real_calls_first(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        con.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,?)",
                        [("1", "OLD", "kol", 100, "call"), ("2", "NEW", "bot", 200, "bot")])
        self.assertEqual(measure.due(con, 1000, 1), ["OLD"])


if __name__ == "__main__":
    unittest.main()
