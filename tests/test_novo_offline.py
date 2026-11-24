"""'Što je novo' (/novo): every news entry by date for every role, and the one-line notice data on every page."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import roles  # noqa: E402
from ui import html, i18n, novo  # noqa: E402


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


class NovoEnglish(unittest.TestCase):
    """19.11. (audit): /novo in English through ui/i18n like every app page, never waiting on a translation call:
    the dates, the empty text and the entries of 11.-19.11. come from the static dictionary ui/i18n_en.json."""
    RECENT = ("2026-11-11", "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-19")
    OLD_14 = "Povijest Telegram kanala za ocjene callera"   # an entry from before, translated by the worker

    def setUp(self):
        self.stack = mock.patch.multiple(i18n, _start_worker=mock.DEFAULT, _can_call=mock.Mock(return_value=False),
                                         _auto={}, _pending={})
        self.stack.start()
        self.addCleanup(self.stack.stop)

    def _en(self, body):
        tok = i18n.LANG.set("en")
        try:
            return i18n.translate(body)
        finally:
            i18n.LANG.reset(tok)

    def test_recent_entries_and_dates_in_english(self):
        recent = [x for x in novo.items() if x["datum"] in self.RECENT and x["naslov"] != self.OLD_14]
        self.assertGreaterEqual(len(recent), 14)
        for x in recent:
            tx = x.get("tekst") or ""
            li = (f"<ul class=nvl><li><b>{html.esc(x['naslov'])}</b><br><span class=mut>"
                  f"{html.esc(tx[:1].upper() + tx[1:])}</span></li></ul>")
            i18n._pending.clear()
            out = self._en(li)
            self.assertEqual(list(i18n._pending), [], x["naslov"])          # nothing left for the worker
            self.assertNotIn(x["naslov"], out)
        t, body = novo.page({})
        out = self._en(body)
        for en in ("19 November 2026", "17 November 2026", "11 November 2026", "Wallets worth following",
                   "Autopilot is paused", "Autopilot as a trading terminal", "Macro influencers", "What's new"):
            self.assertIn(en, out)
        self.assertNotIn("studenoga", out)
        self.assertIn("cb_novo=", out)                                    # the script is left alone
        # Croatian stays Croatian
        self.assertIn("19. studenoga 2026.", body)
        self.assertIn("Novčanici koje vrijedi pratiti", body)
        self.assertEqual(i18n.translate(body), body)                       # LANG hr: untouched

    def test_every_month_and_the_empty_page(self):
        for m in range(1, 13):
            d = novo._day(f"2026-{m:02d}-05")
            out = self._en(f"<h2>{d}</h2>")
            self.assertRegex(out, r"<h2>5 [A-Z][a-z]+ 2026</h2>", d)
        with mock.patch.object(novo, "items", return_value=[]):
            out = self._en(novo.page({})[1])
        self.assertIn("No news recorded yet.", out)

    def test_notice_says_new_in_english(self):
        page = html.page("Tokeni", "<h1>x</h1>", "/tokens")
        self.assertIn("(h.lang==='en'?'new':'novo')", page)               # the "N new" next to "What's new"
        vise = html.vise_page({})[1]
        out = self._en(vise)
        self.assertIn(">new</span>", out)                                  # before the script fills in N
        self.assertIn(">novo</span>", vise)


if __name__ == "__main__":
    unittest.main()
