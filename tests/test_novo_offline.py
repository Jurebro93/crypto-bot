"""'Što je novo' (/novo): every news entry by date for every role, and the one-line notice data on every page."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import roles  # noqa: E402
from ui import html, novo  # noqa: E402


class Novo(unittest.TestCase):
    def test_page_and_notice(self):
        it = novo.items()
        self.assertGreater(len(it), 10)
        t, body = novo.page({})
        self.assertEqual(t, "Što je novo")
        self.assertIn(it[0]["naslov"], body)
        self.assertIn(it[-1]["naslov"], body)                 # whole history, scrollable
        self.assertIn(f"cb_novo={novo.latest_key()}", body)    # opening it clears the notice
        page = html.page("Tokeni", "<h1>x</h1>", "/tokens")
        self.assertIn(f'<meta name=novo content="{novo.latest_key()}"', page)
        # 10.11. (Jure, prijedlog 3.5): no "Novo" strip on top of every page; unseen news is a dot on "Više" (class
        # novo on <html>, set from the meta key) and "N novo" next to "Što je novo" on the Više page
        self.assertNotIn("a.className='novo-bar'", page)
        self.assertIn("classList.add('novo')", page)
        self.assertIn('class="bi nd"', page)                  # the dot's place on the Više tab
        vise = html.vise_page({})[1]
        self.assertIn('href="/novo"', vise)                    # menu item, now on /vise
        self.assertIn("data-novo", vise)
        self.assertIsNone(roles.deny_get("/novo", "osnovni"))  # every role may open it


if __name__ == "__main__":
    unittest.main()
