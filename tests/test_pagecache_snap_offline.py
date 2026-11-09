"""Warmed pages are saved to disk and served at once after a restart (empty memory), then rebuilt in the background;
a POST (clear) makes older snapshots unusable."""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import pagecache  # noqa: E402


class Snap(unittest.TestCase):
    def setUp(self):
        self.saved = (pagecache.SNAP_DIR, set(pagecache._snap_paths), pagecache._cleared_at)
        pagecache.SNAP_DIR = tempfile.mkdtemp()
        pagecache._snap_paths.clear()
        pagecache._snap_paths.add("/pregled")
        pagecache._cleared_at = 0.0
        pagecache._store.clear()

    def tearDown(self):
        pagecache.SNAP_DIR, paths, pagecache._cleared_at = self.saved
        pagecache._snap_paths.clear()
        pagecache._snap_paths.update(paths)
        pagecache._store.clear()

    def test_served_from_disk_after_restart_then_refreshed(self):
        key = ("/pregled", "", None)
        pagecache.get(key, lambda: (200, b"<p>v1</p>" * 300))
        self.assertTrue(os.listdir(pagecache.SNAP_DIR))
        pagecache._store.clear()                      # "deploy": memory empty
        done = threading.Event()

        def slow():
            done.set()
            return 200, b"<p>v2</p>" * 300
        t0 = time.time()
        code, raw, gz = pagecache.get(key, slow)
        self.assertLess(time.time() - t0, 1)
        import gzip
        self.assertIn(b"v1", raw or gzip.decompress(gz))
        self.assertTrue(done.wait(5))                 # rebuilt in the background

    def test_not_saved_for_query_or_other_pages(self):
        pagecache.get(("/pregled", "x=1", None), lambda: (200, b"a"))
        pagecache.get(("/kol", "", None), lambda: (200, b"a"))
        self.assertEqual(os.listdir(pagecache.SNAP_DIR), [])

    def test_clear_invalidates_snapshot(self):
        key = ("/pregled", "", None)
        pagecache.get(key, lambda: (200, b"old"))
        time.sleep(0.01)
        pagecache.clear()
        code, raw, gz = pagecache.get(key, lambda: (200, b"new"))
        import gzip
        self.assertEqual(raw or gzip.decompress(gz), b"new")


if __name__ == "__main__":
    unittest.main()


class SnapshotAfterClearTest(unittest.TestCase):
    """9.11. 18:08: a POST's clear() made the saved copy 'out of date' while the KOL round held the heavy lock, so
    Pregled was a 503 for 20 min. The last-copy fallback may serve a copy from before the clear (stale_ok)."""

    def setUp(self):
        import tempfile
        from ui import pagecache
        self.pagecache = pagecache
        self.saved = (pagecache.SNAP_DIR, set(pagecache._snap_paths), pagecache._cleared_at)
        self.tmp = tempfile.mkdtemp()
        pagecache.SNAP_DIR = self.tmp
        pagecache._snap_paths.add("/probna")   # not /pregled: a background render from an earlier test may still write it
        pagecache._cleared_at = 0.0

    def tearDown(self):
        import shutil
        pc = self.pagecache
        pc.SNAP_DIR, paths, pc._cleared_at = self.saved
        pc._snap_paths.clear()
        pc._snap_paths.update(paths)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stale_ok_serves_copy_from_before_clear(self):
        import gzip
        import time
        pc = self.pagecache
        key = ("/probna", "", None)
        pc._save_snap(key, gzip.compress(b"<html>kopija</html>"))
        self.assertIsNotNone(pc._load_snap(key))
        pc._cleared_at = time.time() + 1      # a POST after the save
        self.assertIsNone(pc._load_snap(key))                  # the normal path waits for a fresh build
        snap = pc._load_snap(key, stale_ok=True)               # the last-copy fallback does not
        self.assertEqual(gzip.decompress(snap[3]), b"<html>kopija</html>")
