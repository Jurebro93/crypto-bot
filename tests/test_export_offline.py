"""7.11.: /admin/export/<db> gives a gzipped read-only copy only with EXPORT_KEY; without the env it is a 404."""
import gzip
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_ui  # noqa: E402


class Export(unittest.TestCase):
    def _call(self, name, qs):
        h = run_ui.Handler.__new__(run_ui.Handler)
        h.headers = {}
        h.wfile = io.BytesIO()
        h.sent = []
        h.send_response = lambda code: h.sent.append(code)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None
        h._send = lambda code, body, ctype="text/html", gz=None, translated=False: h.sent.append(code)
        h._export(name, qs)
        return h

    def test_key_required_and_copy_is_a_database(self):
        d = tempfile.mkdtemp()
        c = sqlite3.connect(os.path.join(d, "kol.db"))
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
        c.close()
        with mock.patch.dict(os.environ, {"DATA_DIR": d, "EXPORT_KEY": "tajna"}):
            self.assertEqual(self._call("kol.db", {"key": "kriva"}).sent, [404])
            h = self._call("kol.db", {"key": "tajna"})
            raw = gzip.decompress(h.wfile.getvalue())
            self.assertTrue(raw.startswith(b"SQLite format 3"))
            self.assertEqual(self._call("secrets.db", {"key": "tajna"}).sent, [404])   # not on the list
        with mock.patch.dict(os.environ, {"DATA_DIR": d, "EXPORT_KEY": ""}):
            self.assertEqual(self._call("kol.db", {"key": ""}).sent, [404])             # no key configured: no route


if __name__ == "__main__":
    unittest.main()
