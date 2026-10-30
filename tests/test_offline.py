"""Runs the whole calendar pipeline against canned API responses (no network).

    python3 -m unittest discover -s tests
"""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_calendar  # noqa: E402
from event_calendar import enrich, http, sources  # noqa: E402

TODAY = dt.date(2026, 10, 10)


def fake_get_json(url, params=None, **_):
    if "onthisday/births/10/14" in url:
        return {"births": [
            {"year": 1993, "pages": [{"title": "Charlie_Kirk", "normalizedtitle": "Charlie Kirk", "wikibase_item": "Q1"}]},
            {"year": 1950, "pages": [{"title": "Obscure_Person", "wikibase_item": "Q2"}]},
        ]}
    if "onthisday" in url or "featured" in url or "usgs" in url or "cad.api" in url:
        return {}
    if "wikidata.org" in url:
        return {"entities": {"Q1": {"sitelinks": {f"w{i}": {} for i in range(70)}},
                             "Q2": {"sitelinks": {"enwiki": {}}}}}
    if "pageviews" in url:
        return {"items": [{"views": 1000}] * 23 + [{"views": 5000}] * 7}
    if "polymarket" in url:
        return [{"title": "Will Elon Musk tweet 500 times this week?", "endDate": "2026-10-17T16:00:00Z",
                 "slug": "elon-tweets", "volume": "2500000", "volume24hr": "90000"}]
    if "rocketlaunch" in url:
        ts = int(dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc).timestamp())
        return {"result": [{"name": "Starship Flight 12", "sort_date": ts, "slug": "s12", "provider": {"name": "SpaceX"}}]}
    raise AssertionError(f"unexpected url {url}")


class CalendarOffline(unittest.TestCase):
    def setUp(self):
        self._orig, self._orig_text = http.get_json, http.get_text
        http.get_json = fake_get_json
        http.get_text = lambda *a, **k: "<rss><channel></channel></rss>"

    def tearDown(self):
        http.get_json, http.get_text = self._orig, self._orig_text

    def test_pipeline(self):
        events, errors = run_calendar.collect(TODAY, 14, 60)
        self.assertEqual(errors, {})
        events = run_calendar.enrich_all(run_calendar.dedupe(events), TODAY, 10)
        titles = [e["title"] for e in events]
        # Kirk's birthday comes from both manual and Wikipedia: only one survives.
        self.assertEqual(sum("Kirk" in t and "birthday" in t for t in titles), 1)
        kirk_bday = next(e for e in events if "Kirk" in e["title"])
        self.assertEqual(kirk_bday["signals"]["sitelinks"], 70)
        self.assertFalse(any("Obscure" in t for t in titles))
        self.assertTrue(any("Starship" in t for t in titles))
        self.assertTrue(any("Elon" in t for t in titles))
        kirk = next(e for e in events if "Kirk" in e["title"])
        self.assertIn("KIRK", kirk["keywords"])
        self.assertIn("CHARLIEKIRK", kirk["keywords"])
        with tempfile.TemporaryDirectory() as d:
            run_calendar.save_db(events, os.path.join(d, "t.db"))
        print("\n" + run_calendar.report(events, errors, TODAY, 14))

    def test_wikipedia_merges_into_manual_signals(self):
        evs = sources.wikipedia_anniversaries(TODAY, 14, 60)
        self.assertEqual([e["subject"] for e in evs], ["Charlie Kirk"])

    def test_affinity(self):
        self.assertEqual(enrich.affinity({"title": "Elon Musk birthday", "subject": "Elon Musk"}), 25)
        self.assertEqual(enrich.affinity({"title": "Gardening day", "subject": "x"}), 0)


if __name__ == "__main__":
    unittest.main()
