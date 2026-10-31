"""Rendered-page cache, gzip and the row cap that keep the dashboard fast on a phone."""
import gzip
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import html, pagecache  # noqa: E402


class PageCache(unittest.TestCase):
    def setUp(self):
        pagecache.clear()
        self.n = 0

    def build(self, code=200):
        def b():
            self.n += 1
            time.sleep(0.2)
            return code, b"<p>" + b"x" * 5000
        return b

    def test_one_render_for_concurrent_visitors(self):
        ts = [threading.Thread(target=pagecache.get, args=(("/", "", None), self.build())) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(self.n, 1)

    def test_stale_served_and_refreshed_in_background(self):
        pagecache.get(("/t", "", None), self.build())
        old = pagecache.FRESH_S
        pagecache.FRESH_S = 0
        try:
            t0 = time.time()
            code, raw, gz = pagecache.get(("/t", "", None), self.build())
            self.assertLess(time.time() - t0, 0.1)     # did not wait for the render
            self.assertEqual(gzip.decompress(gz), raw)
            time.sleep(0.4)
            self.assertEqual(self.n, 2)
        finally:
            pagecache.FRESH_S = old

    def test_errors_not_stored(self):
        pagecache.get(("/e", "", None), self.build(500))
        self.assertNotIn(("/e", "", None), pagecache._store)


class RowCap(unittest.TestCase):
    rows = [[str(i)] for i in range(500)]

    def test_capped_with_link(self):
        out = html.table(["A"], self.rows, mints=[f"m{i}" for i in range(500)])
        self.assertEqual(out.count("<tr"), html.MAX_ROWS + 1)
        self.assertIn("?sve=1", out)

    def test_show_all(self):
        tok = html.SHOW_ALL.set(True)
        try:
            out = html.table(["A"], self.rows)
        finally:
            html.SHOW_ALL.reset(tok)
        self.assertEqual(out.count("<tr"), 501)
        self.assertNotIn("?sve=1", out)


if __name__ == "__main__":
    unittest.main()
