"""Health: range compute and 5-min numbers in the feed-gap check; no "trade" gap without trades (12.11. popodne,
owner: "U health/feed-gap dodaj range_compute i range_numbers: last-write, starost, alert ako je computed_ts ili
numbers_ts stariji od 8–10 min. „Nema Autopilot trade eventa" nije rupa u feedu ako taj dan nije bilo tradeova").

    python3 -m unittest tests.test_health_range_offline
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from events import health  # noqa: E402

ZG = ZoneInfo("Europe/Zagreb")


def zg(h, m=0):
    return int(dt.datetime(2026, 11, 12, h, m, tzinfo=ZG).timestamp())


class RangeGap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "range.db")
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE ranges (token TEXT PRIMARY KEY, ts INTEGER, symbol TEXT, status TEXT, active INTEGER, "
                    "score REAL, price REAL, mcap REAL, pos_pct REAL, data TEXT, state TEXT)")
        now = zg(13, 40)
        rows = (("AIB", now - 600, 1, now - 600),        # computed 10 min ago, numbers 10 min ago
                ("NOB", now - 590, 1, now - 230),        # numbers 4 min ago: the newest counts
                ("OLD", now - 9000, 0, now - 9000))      # inactive: ignored
        for tok, ts, act, mts in rows:
            con.execute("INSERT INTO ranges (token, ts, active, data) VALUES (?,?,?,?)",
                        (tok, ts, act, json.dumps({"mts": mts})))
        con.commit()
        con.close()
        self.now = now

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_reads_last_write_and_age(self):
        st = {s["type"]: s for s in health.range_status(self.now, self.path)}
        self.assertEqual(st["range_compute"]["last_ts"], self.now - 590)
        self.assertEqual(st["range_compute"]["gap_min"], 9.8)
        self.assertEqual(st["range_numbers"]["last_ts"], self.now - 230)
        self.assertEqual(st["range_compute"]["n_active"], 2)

    def test_alert_over_9_min_day_and_night_not_under(self):
        st = health.range_status(self.now, self.path)
        al = health.alerts_for(st, self.now)
        self.assertEqual([a["key"] for a in al], ["range:gap:range_compute"])     # numbers 3.8 min: fine
        self.assertIn("star 10 min", al[0]["title"])
        night = [dict(s, gap_min=12.0) for s in st]
        self.assertEqual(len(health.alerts_for(night, zg(3, 0))), 2)              # the job runs at night too
        ok = [dict(s, gap_min=8.5) for s in st]
        self.assertEqual(health.alerts_for(ok, self.now), [])

    def test_no_range_db_no_rows(self):
        self.assertEqual(health.range_status(self.now, os.path.join(self.tmp.name, "nema.db")), [])


class TradeGap(unittest.TestCase):
    ST = [{"type": "trade", "last_ts": zg(10, 20), "gap_min": 200.0, "n7d": 500, "active": True, "sources": {}}]

    def test_no_trades_is_no_gap(self):
        self.assertEqual(health.alerts_for(self.ST, zg(13, 40), newest={"trade": zg(10, 20)}), [])
        self.assertEqual(health.alerts_for(self.ST, zg(13, 40), newest={}), [])      # source unknown: no proof

    def test_a_trade_the_sync_missed_is_a_gap(self):
        al = health.alerts_for(self.ST, zg(13, 40), newest={"trade": zg(12, 0)})
        self.assertEqual([a["key"] for a in al], ["events:gap:trade"])


if __name__ == "__main__":
    unittest.main()
