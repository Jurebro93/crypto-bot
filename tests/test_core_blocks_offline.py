"""Pregled built around the three core features (Nicholas 2.11.): influencer + wallet blocks, Natjecanje only as a
bonus at the bottom of the menu."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import store  # noqa: E402
from ui import core, html  # noqa: E402


class CoreBlocksTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old = store.DB
        store.DB = os.path.join(self.d, "kol.db")
        con = sqlite3.connect(store.DB)
        con.executescript(store.SCHEMA)
        now = time.time()
        good = json.dumps({"measured": 12, "hit_rate": 0.5, "med_max24": 0.8})
        con.executemany("INSERT INTO kols (handle, name, followers, score, stats) VALUES (?,?,?,?,?)",
                        [("ace", "Ace", 50000, 80, good), ("few", "Few", 10, 90, json.dumps({"measured": 2})),
                         ("trial", "T", 10, 95, json.dumps({"measured": 20, "trial": True}))])
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, symbol) VALUES ('1','MINT1','ace',?,'call','AAA')",
                    (now - 600,))
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, symbol, text, max24) "
                    "VALUES ('2','MINT2','w:abc123',?,'buy','BBB','buy 1.5 SOL',0.4)", (now - 300,))
        con.commit()
        con.close()

    def tearDown(self):
        store.DB = self.old

    def test_kol_block_only_proven(self):
        h = core.kol_block()
        self.assertIn("ace", h)
        self.assertNotIn("/kol/few", h)
        self.assertNotIn("/kol/trial", h)
        self.assertIn("AAA", h)

    def test_wallet_block(self):
        h = core.wallet_block()
        self.assertIn("kupio", h)
        self.assertIn("BBB", h)
        self.assertIn("1.50", h)

    def test_blocks_have_anchors(self):
        h = core.blocks()
        self.assertIn("id=influenceri", h)
        self.assertIn("id=novcanici", h)


class MenuTest(unittest.TestCase):
    def test_core_first_bonus_last(self):
        names = [s for s, _ in html.SECTIONS]
        for c in html.CORE:
            self.assertLess(names.index(c), names.index("Bot trguje (demo)"))
        self.assertEqual(names[-1], html.BONUS)
        self.assertIn("/natjecanje", [p["href"] for p in html.SECTIONS[-1][1]])

    def test_natjecanje_not_in_header_or_bottom_bar(self):
        out = html.page("x", "<h1>x</h1>", "/")
        header = out[out.index("<header"):out.index("</header>")]
        self.assertNotIn("natjecanje", header)
        bbar = out[out.index("class=bbar"):]
        self.assertNotIn('href="/natjecanje"', bbar[:bbar.index("</nav>")])
        self.assertNotIn("natjecanje", html.quick_links())


if __name__ == "__main__":
    unittest.main()


class TtlCacheTest(unittest.TestCase):
    def test_shared_between_processes_via_file(self):
        from ui import data
        old = data.TTL_DIR
        data.TTL_DIR = tempfile.mkdtemp()
        try:
            calls = []
            fn = lambda: calls.append(1) or {"a": [1, 2]}  # noqa: E731
            self.assertEqual(data.ttl_cache("x:1", 60, fn), {"a": [1, 2]})
            data._TTL.clear()   # a new child process: empty memory, the file is still there
            self.assertEqual(data.ttl_cache("x:1", 60, fn), {"a": [1, 2]})
            self.assertEqual(len(calls), 1)
            data._TTL.clear()
            data.ttl_cache("x:1", 0, fn)   # expired: computed again
            self.assertEqual(len(calls), 2)
        finally:
            data.TTL_DIR = old
