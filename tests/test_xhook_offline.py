"""5.11.: twitterapi.io filter rules + webhook for live X calls (kol/xhook.py)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import store as kstore, xhook  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
NOW = 1_800_000_000
CA = "DDmGnuvroxVrb7CSyjYcezFU8gnAfhKasg4ZZezmpump"


class Rules(unittest.TestCase):
    def test_packing_under_255(self):
        hs = [f"handle{i:02d}xx" for i in range(40)]
        rules = xhook.rules_for(hs, CFG)
        self.assertTrue(all(len(v) <= 250 for _, v in rules))
        self.assertEqual(sum(v.count("from:") for _, v in rules), 40)
        self.assertEqual([t for t, _ in rules][:2], ["memesonar-1", "memesonar-2"])

    def test_handles_and_sync(self):
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        con.execute("INSERT INTO kols (handle, score, followers, bot) VALUES ('top1', 80, 5000, 0)")
        con.execute("INSERT INTO kols (handle, score, followers, bot) VALUES ('bigguy', NULL, 50000, 0)")
        con.execute("INSERT INTO kols (handle, score, followers, bot) VALUES ('scanbot', 90, 90000, 1)")
        con.execute("INSERT INTO watch (handle, score) VALUES ('top1', 80)")
        from kol import discover
        con.execute(discover.FOLLOW_SCHEMA)
        con.execute("INSERT INTO follows VALUES ('top1', 'bigguy', ?, 50000, '')", (NOW,))
        con.execute("INSERT INTO follows VALUES ('other', 'bigguy', ?, 50000, '')", (NOW,))
        con.commit()
        with mock.patch("kol.discover.list_stars", return_value=["MustStopMurad"]):
            hs = xhook.handles(con, CFG)
        self.assertEqual(hs[:3], ["top1", "bigguy", "MustStopMurad"])
        self.assertNotIn("scanbot", hs)
        calls = []
        rules = {"rules": []}

        def api(method, path, body=None):
            calls.append((method, path, body))
            if path == "get_rules":
                return rules
            if path == "add_rule":
                rules["rules"].append({"rule_id": f"R{len(rules['rules']) + 1}", "tag": body["tag"], "value": body["value"]})
                return {"rule_id": rules["rules"][-1]["rule_id"], "status": "success"}
            return {"status": "success"}
        os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"] = "https://x.example", "k"
        try:
            with mock.patch("kol.discover.list_stars", return_value=["MustStopMurad"]):
                self.assertTrue(xhook.sync(con, CFG, api=api, now=NOW, log=lambda s: None))
                self.assertFalse(xhook.sync(con, CFG, api=api, now=NOW + 60, log=lambda s: None))   # unchanged
            self.assertEqual(xhook.hook_url(), "https://x.example/hook/x?key=k")
        finally:
            del os.environ["RENDER_EXTERNAL_URL"], os.environ["KOL_HOOK_KEY"]
        adds = [c for c in calls if c[1] == "add_rule"]
        ups = [c for c in calls if c[1] == "update_rule"]
        self.assertEqual(len(adds), 1)
        self.assertTrue(all(u[2]["is_effect"] == 1 and u[2]["interval_seconds"] == 30 for u in ups))
        st = json.loads(con.execute("SELECT value FROM kv WHERE key='xhook'").fetchone()[0])
        self.assertEqual(st["ids"], {"memesonar-1": "R1"})
        con.close()


class Ingest(unittest.TestCase):
    def test_payload_shapes_become_calls(self):
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        kstore.connect(path).close()
        tw = {"id": "9001", "text": f"aping {CA} now", "createdAt": "Thu Nov 05 12:00:00 +0000 2026",
              "author": {"userName": "caller", "followers": 40000}}
        self.assertEqual(xhook.ingest({"tweets": [tw]}, kol_db=path, now=NOW, log=lambda s: None), 1)
        self.assertEqual(xhook.ingest(tw, kol_db=path, now=NOW, log=lambda s: None), 0)                  # same post again
        tw2 = {**tw, "id": "9002"}
        self.assertEqual(xhook.ingest([tw2], kol_db=path, now=NOW, log=lambda s: None), 1)
        self.assertEqual(xhook.ingest({"event": "ping"}, kol_db=path, now=NOW, log=lambda s: None), 0)
        con = kstore.connect(path)
        rows = con.execute("SELECT handle, token, source FROM calls ORDER BY tweet_id").fetchall()
        self.assertEqual(rows, [("caller", CA, "x_hook"), ("caller", CA, "x_hook")])
        self.assertEqual(con.execute("SELECT value FROM kv WHERE key='xhook_count'").fetchone()[0], "4")
        self.assertEqual(len(json.loads(con.execute("SELECT value FROM kv WHERE key='xhook_samples'").fetchone()[0])), 4)
        con.close()


if __name__ == "__main__":
    unittest.main()
