"""10.11. (završni pregled, drugi krug): public JSON-LD cannot be closed by a name, token links are http(s) only, the
public leaderboard's verdict columns do not break on a phone, moved /kol sections are linked where they live now."""
import json
import os
import unittest

from ui import evidence, public

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Hardening(unittest.TestCase):
    def test_json_ld_escapes_a_closing_script_tag(self):
        src = open(public.__file__, encoding="utf-8").read()
        self.assertEqual(src.count('replace("</", "<\\\\/")'), 2)   # the profile and its FAQ block
        payload = json.dumps({"name": "x</script><img src=x onerror=alert(1)>"}).replace("</", "<\\/")
        self.assertNotIn("</script", payload)
        self.assertEqual(json.loads(payload)["name"], "x</script><img src=x onerror=alert(1)>")   # same data for search

    def test_token_links_are_http_only(self):
        src = open(evidence.__file__, encoding="utf-8").read()
        self.assertIn('startswith(("https://", "http://"))', src)

    def test_public_verdict_columns_do_not_wrap(self):
        src = open(public.__file__, encoding="utf-8").read()
        self.assertIn(".vdc{white-space:nowrap}", src)
        self.assertIn('"1\u00a0h"', src)   # a no-break space between 1 and h

    def test_moved_sections_are_linked_on_kol_analize(self):
        for path in ("ui/glossary.py", "ui/core.py", "ui/kol.py"):
            src = open(os.path.join(ROOT, path), encoding="utf-8").read()
            for anchor in ("#provjera", "#kopiraju", "#parovi", "#kupnje"):
                self.assertNotIn(f'"/kol{anchor}"', src, (path, anchor))


if __name__ == "__main__":
    unittest.main()
