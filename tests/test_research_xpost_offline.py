"""10.11. (Jure): the one X post with the method, read on the server with the X API (fake here): the post, the
author's thread, the article; files, log blob, marker only when something was read."""
import base64
import gzip
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import xpost  # noqa: E402

POST = {"id": xpost.POST_ID, "text": "Metoda: 1) nađi tokene 2) pogledaj prve kupce", "createdAt": "Tue Nov 10",
        "likeCount": 10, "retweetCount": 2, "replyCount": 1, "viewCount": 900, "url": "https://x.com/i/1",
        "author": {"userName": "iiamjeph", "name": "Jeph", "followers": 5000},
        "entities": {"urls": [{"expanded_url": "https://gmgn.ai"}]}}


def fake(url, params):
    if "tweet_ids" in params:
        return {"tweets": [POST]}
    if "query" in params:
        return {"tweets": [POST, dict(POST, id="2120056013063671999", text="3) filtriraj snajpere")]}
    return {"article": {"title": "Kako nalazim rane novčanike", "contents": [{"text": "Korak po korak"}]}}


class XPost(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ["DATA_DIR"] = self.d
        self.kdb = os.path.join(self.d, "kol.db")
        c = sqlite3.connect(self.kdb)
        c.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
        c.commit()
        c.close()

    def tearDown(self):
        os.environ.pop("DATA_DIR", None)

    def test_post_thread_article_files_and_log(self):
        from kol import store as kstore
        lines = []
        with mock.patch.object(kstore, "DB", self.kdb):
            self.assertEqual(xpost.main([], get=fake, log=lines.append), 0)
            self.assertEqual(xpost.main([], get=fake, log=lines.append), 0)         # once
        self.assertIn("research xpost: već napravljeno", lines)
        md = open(os.path.join(self.d, "research", xpost.NAME + ".md")).read()
        for s in ("Metoda: 1)", "3) filtriraj snajpere", "Kako nalazim rane novčanike", "Korak po korak",
                  "https://gmgn.ai", "pregleda 900"):
            self.assertIn(s, md)
        blob = "".join(x.split(" ", 2)[2] for x in lines if x.startswith("XPOST "))
        self.assertEqual(gzip.decompress(base64.b64decode(blob)).decode(), md)
        spent = sqlite3.connect(self.kdb).execute("SELECT value FROM kv").fetchone()[0]
        self.assertLess(float(spent), 0.01)

    def test_nothing_read_leaves_no_marker(self):
        from kol import store as kstore
        with mock.patch.object(kstore, "DB", self.kdb):
            xpost.main([], get=lambda u, p: {}, log=lambda s: None)
        self.assertFalse(os.path.exists(os.path.join(self.d, "research", xpost.NAME + ".done")))


if __name__ == "__main__":
    unittest.main()
