"""19.11. (vlasnik: "On the web page write a message that Autopilot is currently paused because of a change in
strategy and that users will be notified when it continues"): ui/pauza.py and its places, offline.

  - the state: trade.db settings "pravi_novac_pauza" {"on": true}, read-only, never raises, kept 60 s
  - the notice on /autopilot and /en/autopilot (Croatian page translated by ui/i18n), on the front page's Autopilot
    place in both languages; absent when the key is off or missing; nothing private in it
  - while paused nothing next to it says real money is trading (hero, title, description, the app banner)
  - the copies: the notice is gone within the pause cache (60 s) + the guest copy (10 s) after the pause ends

    python3 -m unittest tests.test_pauza_offline
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import test_apjavno_offline as ap  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import apjavno, i18n, pauza  # noqa: E402

HR = ("Autopilot je trenutno pauziran zbog promjene strategije. Sve resurse usmjerili smo na pronalaženje novčanika "
      "koji kupuju prije rasta. Korisnike ćemo obavijestiti kada se Autopilot nastavi.")
EN = ("Autopilot is currently paused while we change the strategy. All resources now go to finding wallets that buy "
      "before a rise. We will notify users when Autopilot resumes.")
FORBIDDEN = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|pravi_novac|pauza\b|SOL\b|\$|€|[1-9A-HJ-NP-Za-km-z]{32,44}|"
                       r"Helius|Apify|OpenAI|Claude|Render|trade\.db|settings|switch|prekidač")


def note_of(html):
    m = re.search(r'<div class="[^"]*soc-note"[^>]*>(.*?)</div>', html, re.S)
    return m.group(1) if m else None


class Base(ap.Base):
    def setUp(self):
        super().setUp()
        pauza.reset()
        self.addCleanup(pauza.reset)

    def pause(self, on=True, raw=None):
        con = executor.connect(settings.DB)
        con.execute("INSERT OR REPLACE INTO settings (k, v, ts, who) VALUES (?,?,?,?)",
                    ("pravi_novac_pauza", raw if raw is not None else json.dumps({"on": on, "why": "strategija"}),
                     int(time.time()), "Jure"))
        con.commit()
        con.close()
        pauza.reset()
        apjavno.reset_cache()

    def en(self, html):
        tok = i18n.LANG.set("en")
        try:
            with mock.patch.object(i18n, "_start_worker"):
                return i18n.translate(html)
        finally:
            i18n.LANG.reset(tok)


class State(Base):
    def test_read_is_defensive(self):
        self.assertFalse(pauza.read(os.path.join(self.d, "nema.db")))          # no trade.db
        sqlite3.connect(os.path.join(self.d, "prazna.db")).close()
        self.assertFalse(pauza.read(os.path.join(self.d, "prazna.db")))        # no settings table
        self.trade().close()
        self.assertFalse(pauza.read())                                          # no key
        self.pause(True)
        self.assertTrue(pauza.read())
        self.pause(False)
        self.assertFalse(pauza.read())
        for raw in ("nije json", json.dumps(True), json.dumps({"on": "da"}), json.dumps([1])):
            self.pause(raw=raw)
            self.assertFalse(pauza.read(), raw)

    def test_kept_sixty_seconds(self):
        self.pause(True)
        t = time.time()
        self.assertTrue(pauza.on(t))
        self.pause(False)
        pauza._CACHE.update(ts=t, val=True)                                     # what this process last saw
        self.assertTrue(pauza.on(t + pauza.TTL_S - 1))                          # not re-read inside 60 s
        self.assertFalse(pauza.on(t + pauza.TTL_S))
        with mock.patch.object(pauza, "read", side_effect=AssertionError("re-read")):
            for _ in range(20):
                pauza.on(t + pauza.TTL_S + 5)                                   # one read serves many requests


class Pages(Base):
    def test_autopilot_page_both_languages(self):
        self.live()
        self.pause(True)
        for lang in ("hr", "en"):
            apjavno.reset_cache()
            html = apjavno.guest_html({}, lang)
            if lang == "en":
                html = self.en(html)        # run_ui translates the Croatian page for /en/autopilot
            note = note_of(html)
            self.assertEqual(note, EN if lang == "en" else HR)
            self.assertIsNone(FORBIDDEN.search(note))
            self.assertEqual(html.count("soc-note"), 1)
            self.assertLess(html.index("soc-note"), html.index("apj-hero"))     # at the top
            self.assertNotIn("Uživo · pravi novac", html)
            self.assertNotIn("pravim novcem, prema podacima alata", html)
        hr = apjavno.guest_html({}, "hr")
        self.assertIn("Pauzirano", hr)
        self.assertIn("<title>Autopilot (pauziran)", hr)
        self.assertIn("Autopilot je trenutno pauziran zbog promjene strategije. Javno:", hr)        # meta description
        en = self.en(apjavno.guest_html({}, "en"))
        self.assertIn("Autopilot is currently paused while we change the strategy. In public:", en)
        self.assertIn("Autopilot opens no new positions while it is paused. The wallet, the entries and the exits stay "
                      "public.", en)
        self.assertIn(HR, apjavno.page({}, "Jure")[1])                          # the in-app copy too
        self.assertEqual(apjavno.banner_html(path="/tokens"), "")              # no "Autopilot je live" in the app
        self.assertIn("Pauzirano", apjavno.live_fragment("hr"))                # the 15-s refresh keeps it

    def test_absent_when_off_or_missing(self):
        self.live()
        for state in (None, False):
            if state is not None:
                self.pause(state)
            apjavno.reset_cache()
            for lang in ("hr", "en"):
                html = apjavno.guest_html({}, lang)
                self.assertNotIn("soc-note", html)
                self.assertIn("Uživo · pravi novac", html)                      # as before
            self.assertIn("Tradanje pravim sredstvima je live", apjavno.landing_strip("hr"))
            self.assertIn("apj-ban", apjavno.banner_html(path="/tokens"))

    def test_front_page_both_languages(self):
        from ui import landing
        self.pause(True)
        for lang, want in (("hr", HR), ("en", EN)):
            strip = apjavno.landing_strip(lang)
            self.assertEqual(note_of(strip), want)
            self.assertIn("translate=no", strip)
            self.assertNotIn("is live", strip)
            with mock.patch.object(landing, "stats", return_value=({}, None)):
                page = landing.page_html({}, lang=lang)
            self.assertEqual(note_of(page), want)
            self.assertIsNone(FORBIDDEN.search(note_of(page)))
        self.live()
        self.assertEqual(note_of(apjavno.landing_strip("en")), EN)              # paused wins over "live"
        self.pause(False)
        self.assertNotIn("soc-note", apjavno.landing_strip("en"))

    def test_the_notice_leaves_with_the_caches(self):
        """Pause off: gone after the pause cache (TTL_S 60 s) and the guest copy (GUEST_TTL_S 10 s), at most 70 s."""
        self.trade().close()
        self.pause(True)
        self.assertIn("soc-note", apjavno.guest_html({}, "hr"))
        con = executor.connect(settings.DB)                                     # the owner ends the pause
        settings.put(con, "pravi_novac_pauza", {"on": False}, "Jure")
        con.close()
        t0 = time.time()
        pauza._CACHE.update(ts=t0, val=True)                                    # this process still remembers it
        apjavno._GUEST[("page", "hr")] = (t0, apjavno._GUEST[("page", "hr")][1])
        self.assertIn("soc-note", apjavno.guest_html({}, "hr"))                 # inside both lifetimes
        pauza._CACHE["ts"] = t0 - pauza.TTL_S
        apjavno._GUEST[("page", "hr")] = (t0 - apjavno.GUEST_TTL_S, apjavno._GUEST[("page", "hr")][1])
        self.assertNotIn("soc-note", apjavno.guest_html({}, "hr"))


if __name__ == "__main__":
    unittest.main()
