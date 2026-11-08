"""8.11.: locked-database retry names the holders; table sizes line; learning survives rows without a class."""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import dblock  # noqa: E402


class DbLock(unittest.TestCase):
    def test_retry_then_success_and_holders(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "x.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE t (x)")
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return "ok"
        logs = []
        with mock.patch("time.sleep"):
            self.assertEqual(dblock.retry(fn, "test", tries=4, wait=1, log=lambda *a, **k: logs.append(a[0]), path=path), "ok")
        self.assertEqual(len(logs), 2)
        self.assertIn("drže je", logs[0])
        self.assertTrue(any(pid == os.getpid() for pid, _ in dblock.holders(path)))   # this process has it open
        con.close()
        with mock.patch("time.sleep"), self.assertRaises(sqlite3.OperationalError):
            dblock.retry(lambda: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")), "t", tries=2, wait=1,
                         log=lambda *a, **k: None, path=path)
        with self.assertRaises(sqlite3.OperationalError):   # other errors are not retried
            dblock.retry(lambda: (_ for _ in ()).throw(sqlite3.OperationalError("no such table")), "t", tries=3, log=lambda *a, **k: None)


class FitNoneClass(unittest.TestCase):
    def test_rows_without_class_use_default(self):
        from learn import fit
        rows = [{"klasa": None, "ret": 0.1, "ts": 1, "hit": 0, "features": {}}, {"klasa": "T1", "ret": 0.2, "ts": 2, "hit": 1, "features": {}}]
        with mock.patch("learn.outcomes.rows", return_value=(rows, {"T1": 0.5, None: 0.1})), \
                mock.patch("learn.outcomes.config", return_value={"cilj": "vrh", "min_rows": 1000, "horizon_h": 24}), \
                mock.patch("hype.score.load_weights", return_value={}), \
                mock.patch("learn.weights.load", return_value={}):
            rep = fit.run(None, now=1, apply=False)
        self.assertEqual(sorted(r["klasa"] for r in rep), ["T1", "default"])


if __name__ == "__main__":
    unittest.main()
