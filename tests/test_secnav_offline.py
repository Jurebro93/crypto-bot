"""Long-page navigation (ui/secnav.py): section chips + back-to-top on the dashboard and the public pages."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import html, public, secnav  # noqa: E402


class SecnavTest(unittest.TestCase):
    def test_dashboard_page_has_chips_and_top_button(self):
        out = html.page("T", "<h1>T</h1><h2>A</h2><h2>B</h2><h2>C</h2>", "/")
        self.assertIn('id=secnav', out)
        self.assertIn('id=totop', out)
        self.assertIn('aria-label="Povratak na vrh"', out)
        self.assertIn(".secnav{", out)
        self.assertIn("function build()", out)
        self.assertLess(out.index("<main>"), out.index("id=secnav"))

    def test_public_shell_english_labels(self):
        out = public._shell("en", "T", "d", "/x", "/hr/x", "<h1>T</h1><h2>A</h2>")
        self.assertIn('aria-label="Back to top"', out)
        self.assertIn("function build()", out)
        hr = public._shell("hr", "T", "d", "/x", "/hr/x", "<h1>T</h1>")
        self.assertIn('aria-label="Sekcije stranice"', hr)

    def test_labels_translated_in_english_app(self):
        import json
        d = json.load(open(os.path.join(os.path.dirname(secnav.__file__), "i18n_en.json")))
        self.assertEqual(d["Povratak na vrh"], "Back to top")
        self.assertEqual(d["Sekcije stranice"], "Page sections")

    def test_table_paging_labels(self):
        out = html.page("T", "<h1>T</h1>", "/")
        self.assertIn("<div id=pglab hidden><span>Vidi još</span>", out)
        self.assertIn("const PG=25", out)
        en = public._shell("en", "T", "d", "/x", "/hr/x", "<h1>T</h1>")
        self.assertIn("<span>See more:</span>", en)

    def test_js_has_no_script_close(self):
        self.assertNotIn("</script", secnav.JS)


if __name__ == "__main__":
    unittest.main()
