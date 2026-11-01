"""Favicon set: every file exists, is served, and is linked in page heads."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui import favicon  # noqa: E402


class Favicon(unittest.TestCase):
    def test_files(self):
        for p in favicon.PATHS:
            body, ctype = favicon.get(p)
            self.assertTrue(body and ctype, p)
        self.assertTrue(favicon.get("/favicon.ico")[0][:4] == b"\x00\x00\x01\x00")
        m = json.loads(favicon.get("/site.webmanifest")[0])
        self.assertEqual(m["name"], "MemeSonar")
        self.assertIsNone(favicon.get("/nope.png"))

    def test_linked(self):
        from ui import html, loginpage, public
        self.assertIn('href="/favicon.ico"', html.page("T", "<h1>x</h1>", "/"))
        code, body, _ = public.route("/glossary")
        self.assertIn(b"rel=apple-touch-icon", body)
        self.assertIn("Allow: /favicon", public.robots())


if __name__ == "__main__":
    unittest.main()
