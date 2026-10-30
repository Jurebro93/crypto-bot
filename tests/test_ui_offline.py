"""Dashboard renders every page with no databases at all and with the real ones (read-only)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_ui  # noqa: E402
from ui import data  # noqa: E402

PAGES = ["/", "/wallets", "/wallets?all=1", "/tokens", "/events", "/paper", "/criteria", "/learn", "/outputs",
         "/wallet/none", "/token/none"]


def render(path):
    from urllib.parse import parse_qsl, urlsplit
    u = urlsplit(path)
    return run_ui.route(u.path, dict(parse_qsl(u.query)))


class EmptyData(unittest.TestCase):
    def test_pages_without_databases(self):
        tmp = tempfile.mkdtemp()
        saved = dict(data.GROUPS), data.OUT
        try:
            for k in data.GROUPS:
                data.GROUPS[k] = [os.path.join(tmp, "missing.db")]
            data.CAL_DB = os.path.join(tmp, "missing.db")
            data.OUT = tmp
            for p in PAGES:
                title, body = render(p)
                self.assertTrue(body, p)
        finally:
            data.GROUPS.update(saved[0])
            data.OUT = saved[1]
            data.CAL_DB = os.path.join(data.HERE, "calendar.db")

    def test_output_path_traversal(self):
        self.assertIsNone(data.read_output("../README.md"))


if __name__ == "__main__":
    unittest.main()
