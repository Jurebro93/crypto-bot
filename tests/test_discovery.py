"""Offline tests for the big-event sources and token-likelihood scoring.

    python3 -m unittest discover -s tests
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from event_calendar import discovery, enrich, http  # noqa: E402

TODAY = dt.date(2026, 10, 30)

RSS = """<rss><channel>
<item><title>GTA 6 trailer 3 drops on November 5 - IGN</title><link>https://a</link></item>
<item><title>GTA 6 trailer 3 arrives November 5, Rockstar says - Kotaku</title><link>https://b</link></item>
<item><title>Some company quarterly earnings on November 5 - Reuters</title><link>https://c</link></item>
<item><title>Tesla Roadster unveil set for December 12 - Electrek</title><link>https://d</link></item>
<item><title>Musk confirms Roadster demo December 12 - Teslarati</title><link>https://e</link></item>
</channel></rss>"""


def fake_json(url, params=None, **_):
    if "featured/2026/10/29" in url:
        return {"mostread": {"articles": [
            {"title": "Famous_Rapper", "normalizedtitle": "Famous Rapper", "views": 900000,
             "description": "American rapper (died 2026)",
             "view_history": [{"views": 20000}] * 4 + [{"views": 900000}]},
            {"title": "Main_Page", "views": 9000000, "view_history": []},
            {"title": "Steady_Show", "views": 300000, "view_history": [{"views": 290000}] * 5},
        ]}}
    if "featured" in url:
        return {}
    if "usgs" in url:
        return {"features": [{"properties": {"mag": 7.8, "place": "off Japan", "time": 1793318400000,
                                             "url": "https://usgs", "tsunami": 1}},
                             {"properties": {"mag": 6.1, "place": "nowhere", "time": 1793318400000}}]}
    if "cad.api" in url:
        return {"fields": ["des", "cd", "dist", "h"], "data": [["2026 AB", "2026-Nov-10 12:00", "0.002", "21.5"]]}
    raise AssertionError(url)


class Discovery(unittest.TestCase):
    def setUp(self):
        self._j, self._t = http.get_json, http.get_text
        http.get_json = fake_json
        http.get_text = lambda url, params=None, **_: RSS

    def tearDown(self):
        http.get_json, http.get_text = self._j, self._t

    def test_viral_now(self):
        evs = discovery.wikipedia_viral_now(TODAY)
        self.assertEqual([e["subject"] for e in evs], ["Famous Rapper"])
        self.assertGreater(enrich.token_likelihood(evs[0]), 0.5)  # a celebrity death spikes, often gets tokens
        kane = {"title": "Viral now: Harry Kane", "subject": "Harry Kane", "kind": "viral_now", "source": "w",
                "signals": {"description": "English footballer (born 1993)", "spike": 12}}
        self.assertLess(enrich.token_likelihood(kane), 0.2)  # sport is ignored by the memecoin crowd
        import run_calendar
        ranked = run_calendar.enrich_all(evs, TODAY, 5)  # viral events have no sitelinks
        self.assertEqual(ranked[0]["days_until"], 0)

    def test_news_dates(self):
        evs = discovery.news_dates(TODAY, 60, queries=['"release date"'])
        by_subject = {e["subject"]: e for e in evs}
        self.assertEqual(by_subject["GTA 6"]["date"], "2026-11-05")
        self.assertEqual(by_subject["GTA 6"]["kind"], "game_release")
        # the watchlist query for the dateless Tesla Roadster entry picks up the agreed date
        self.assertEqual(by_subject["Tesla Roadster"]["date"], "2026-12-12")
        self.assertNotIn("Some", " ".join(by_subject))  # a single headline is not enough

    def test_disasters(self):
        quakes = discovery.earthquakes(TODAY)
        self.assertEqual(len(quakes), 1)
        rock = discovery.asteroids(TODAY, 30)
        self.assertEqual(rock[0]["date"], "2026-11-10")

    def test_routine_is_noise(self):
        ev = {"title": "SpaceX Starlink (15-18) launch", "subject": "SpaceX Starlink", "kind": "launch", "source": "x"}
        self.assertLess(enrich.token_likelihood(ev), 0.1)
        gta = {"title": "GTA 6 release", "subject": "GTA 6", "kind": "game_release", "source": "manual"}
        self.assertGreater(enrich.token_likelihood(gta), enrich.token_likelihood(ev))


if __name__ == "__main__":
    unittest.main()
