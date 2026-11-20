"""20.11. (2) (production 09:52 UTC: "nadzor memorije: ui (pid 175) drži 1561 MB" after 311 MB three minutes before,
and the log could not say which page), offline: the one line that names it next time.

  - ops/mem.watch: "ui: <path> je podigao memoriju za N MB" when a block raised the process by more than 150 MB,
    silent below, a nested block (a request that builds its page) counted once, never raises
  - run_ui's GET / POST handling and pagecache's builds (the warm and refresh threads too) are watched

    python3 -m unittest tests.test_ui_memorija_offline
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import mem  # noqa: E402


def seq(*vals):
    it = iter(vals)
    return lambda: next(it)


class Watch(unittest.TestCase):
    def test_the_line_above_150_mb_only(self):
        lines = []
        with mock.patch.object(mem, "rss_mb", seq(300, 461)):
            with mem.watch("/novcanici-admin", log=lines.append):
                pass
        self.assertEqual(lines, ["ui: /novcanici-admin je podigao memoriju za 161 MB"])
        lines.clear()
        for a, b in ((300, 450), (500, 300), (None, 900), (300, None)):
            with mock.patch.object(mem, "rss_mb", seq(a, b)):
                with mem.watch("/x", log=lines.append):
                    pass
        self.assertEqual(lines, [])
        r = mem.rss_mb()
        self.assertTrue(r is None or (isinstance(r, int) and r > 0))

    def test_nested_counted_once_and_errors_pass_through(self):
        lines = []
        with mock.patch.object(mem, "rss_mb", seq(100, 900)):   # only the outer block reads the memory
            with mem.watch("/a", log=lines.append):
                with mem.watch("/b", log=lines.append):
                    pass
        self.assertEqual(lines, ["ui: /a je podigao memoriju za 800 MB"])
        with mock.patch.object(mem, "rss_mb", seq(100, 100)), self.assertRaises(ValueError):
            with mem.watch("/c", log=lines.append):
                raise ValueError("x")
        with mock.patch.object(mem, "rss_mb", seq(100, 400)):   # a broken log never breaks the page
            with mem.watch("/d", log=lambda m: 1 / 0):
                pass


class Wired(unittest.TestCase):
    def test_get_and_post_are_watched(self):
        import run_ui
        h = run_ui.Handler.__new__(run_ui.Handler)
        h.path = "/novcanici-admin?x=1"
        lines = []
        with mock.patch.object(mem, "rss_mb", seq(200, 900, 200, 380)), \
                mock.patch("builtins.print", lambda m, **k: lines.append(m)), \
                mock.patch.object(run_ui.Handler, "_do_get", lambda self: None), \
                mock.patch.object(run_ui.Handler, "_do_post", lambda self: None):
            h.do_GET()
            h.do_POST()
        self.assertEqual(lines, ["ui: /novcanici-admin je podigao memoriju za 700 MB",
                                 "ui: POST /novcanici-admin je podigao memoriju za 180 MB"])

    def test_a_background_build_is_watched(self):
        from ui import pagecache
        lines = []
        with mock.patch.object(mem, "rss_mb", seq(100, 400)), \
                mock.patch("builtins.print", lambda m, **k: lines.append(m)), \
                mock.patch.object(pagecache, "trim", lambda: None):
            pagecache._build(("/wallets", "", None), lambda: (200, b"<p>x</p>"))
        self.assertIn("ui: /wallets je podigao memoriju za 300 MB", lines)
        pagecache.clear()


if __name__ == "__main__":
    unittest.main()
