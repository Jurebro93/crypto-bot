"""5.11.: /share/novosti.png (ui/sharecard.py): the day's novosti as a PNG card, nothing else on it."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import sharecard  # noqa: E402


class Card(unittest.TestCase):
    def test_png_from_the_days_entries_only(self):
        items = [{"datum": "2026-11-05", "naslov": "Novo A", "tekst": "opis a", "naslov_en": "New A", "tekst_en": "desc a"},
                 {"datum": "2026-11-05", "naslov": "Bez prijevoda", "tekst": "x"},
                 {"datum": "2026-11-04", "naslov": "Staro", "tekst": "opis", "naslov_en": "Old"}]
        with mock.patch("ui.novo.items", return_value=items):
            self.assertEqual(sharecard.entries("2026-11-05"), [("New A", "desc a")])          # English only
            self.assertEqual(sharecard.entries("2026-11-05", "hr"), [("Novo A", "opis a"), ("Bez prijevoda", "x")])
            b = sharecard.png("2026-11-05")
            self.assertTrue(b and b[:8] == b"\x89PNG\r\n\x1a\n")
            self.assertIsNone(sharecard.png("2026-11-03"))      # no entries: 404 upstream, nothing invented

    def test_route_is_public(self):
        import run_ui
        self.assertTrue(run_ui.is_public("/share/novosti.png"))
        self.assertFalse(run_ui.is_public("/share/novosti.json"))


if __name__ == "__main__":
    unittest.main()
