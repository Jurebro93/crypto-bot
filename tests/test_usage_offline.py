"""Spend tracking: Helius pricing, the meter's hourly upsert, and each warning rule on synthetic data."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from usage import meter, watch  # noqa: E402

H, D = 3600, 86400
NOW = 1793623800  # 2026-11-02 12:50 UTC, three days into a cycle that starts on the 30th


def fresh():
    meter.DB = os.path.join(tempfile.mkdtemp(), "usage.db")
    return meter.connect()


def add(con, hours_ago, amount, service="helius", script="run_hype.py", method="rpc", calls=1, errors=0):
    hr = (NOW - hours_ago * H) // H * H
    con.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET amount=amount+excluded.amount, "
                "calls=calls+excluded.calls, errors=errors+excluded.errors", (hr, service, script, method, calls, errors, amount))


def keys(con):
    con.commit()
    return {a["key"] for a in watch.evaluate(con, now=NOW)}


class Pricing(unittest.TestCase):
    def test_helius_costs(self):
        self.assertEqual(meter.helius_cost("https://api-mainnet.helius-rpc.com/v0/addresses/X/transactions?api-key=k"),
                         ("enhanced transactions", 100))
        body = json.dumps({"method": "getTransactionsForAddress"}).encode()
        self.assertEqual(meter.helius_cost("https://mainnet.helius-rpc.com/?api-key=k", body, {"data": [0] * 250}),
                         ("getTransactionsForAddress", 30))
        self.assertEqual(meter.helius_cost("https://mainnet.helius-rpc.com/", json.dumps({"method": "getBalance"}))[1], 1)
        self.assertIsNone(meter.helius_cost("https://api.dexscreener.com/x"))

    def test_record_and_flush_add_up(self):
        fresh()
        for _ in range(5):
            meter.record("helius", "getBalance", 1)
        meter.flush()
        meter.record("helius", "getBalance", 1, error=True)
        meter.flush()
        con = meter.connect()
        self.assertEqual(con.execute("SELECT SUM(calls), SUM(errors), SUM(amount) FROM usage").fetchone(), (6, 1, 6.0))

    def test_cycle(self):
        import datetime as dtm
        t = dtm.datetime(2026, 11, 5, tzinfo=dtm.timezone.utc).timestamp()
        s, e = watch.cycle(30, t)
        self.assertEqual(dtm.datetime.fromtimestamp(s, dtm.timezone.utc).date(), dtm.date(2026, 10, 30))
        self.assertEqual(dtm.datetime.fromtimestamp(e, dtm.timezone.utc).date(), dtm.date(2026, 11, 30))
        s, _ = watch.cycle(30, dtm.datetime(2027, 2, 28, 12, tzinfo=dtm.timezone.utc).timestamp())  # clamps to Feb 28
        self.assertEqual(dtm.datetime.fromtimestamp(s, dtm.timezone.utc).date(), dtm.date(2027, 2, 28))


class Rules(unittest.TestCase):
    def test_quiet_month_has_no_warnings(self):
        con = fresh()
        for h in range(72):
            add(con, h, 10000)  # 240k/day, budget is ~333k/day
        self.assertEqual(keys(con), set())

    def test_pace_over_budget(self):
        con = fresh()
        for h in range(48):
            add(con, h, 30000)  # 720k/day
        self.assertIn("helius:pace", keys(con))

    def test_leak_in_one_script(self):
        con = fresh()
        for h in range(2, 48):
            add(con, h, 5000)
        add(con, 0, 120000, script="run_wallets.py")
        add(con, 1, 120000, script="run_wallets.py")
        self.assertIn("helius:leak:run_wallets.py", keys(con))

    def test_spike_against_own_history(self):
        con = fresh()
        for h in range(2, 48):
            add(con, h, 2000)
        add(con, 0, 30000)
        self.assertIn("helius:spike:run_hype.py", keys(con))

    def test_exponential_growth(self):
        con = fresh()
        for d, per_h in enumerate([200, 400, 900, 2000, 5000][::-1]):
            for h in range(24):
                add(con, d * 24 + h, per_h * 10)
        self.assertIn("helius:exp", keys(con))

    def test_spend_outside_the_bot(self):
        con = fresh()
        cs, ce = watch.cycle(30, NOW)
        for h in range(12):
            add(con, h, 0.01, service="apify")
        con.execute("INSERT INTO account VALUES (?,?,?,?,?,?,?)", (NOW - 10 * H, "apify", 5.0, 60, cs, ce, "{}"))
        con.execute("INSERT INTO account VALUES (?,?,?,?,?,?,?)", (NOW - 60, "apify", 8.0, 60, cs, ce, "{}"))
        self.assertIn("apify:outside", keys(con))

    def test_retry_storm(self):
        con = fresh()
        add(con, 0, 0, calls=900, errors=900)
        self.assertIn("helius:errors:run_hype.py", keys(con))

    def test_remember_keeps_first_seen(self):
        con = fresh()
        a = [{"key": "k", "service": "helius", "level": "warn", "title": "t", "detail": "d"}]
        watch.remember(con, a, NOW - 600)
        watch.remember(con, a, NOW)
        self.assertEqual(con.execute("SELECT first_ts, last_ts FROM alerts").fetchone(), (NOW - 600, NOW))


class Fixes20261101(unittest.TestCase):
    """01.11.2026: one ongoing warning was logged ~100x a day, the Helius forecast jumped from 03.11. to 16.11. as a
    one-off burst slid out of the 26 h window, and webhook events were billed but never counted."""

    def snaps(self, con, points, extra=None):
        cs, ce = watch.cycle(30, NOW)
        for hrs, used in points:
            con.execute("INSERT INTO account VALUES (?,?,?,?,?,?,?)",
                        (NOW - int(hrs * H), "helius", used, 10e6, cs, ce, json.dumps(extra(hrs) if extra else {})))

    def test_one_off_burst_is_not_the_monthly_pace(self):
        con = fresh()
        # 200k/day steady for 3 days, plus a single 1.2M burst 20 h ago (a backfill)
        pts = [(h, 200000 * (72 - h) / 24 + (1.2e6 if h <= 20 else 0)) for h in range(72, -1, -1)]
        self.snaps(con, pts)
        con.commit()
        st = watch.status(con, "helius", watch.config(), NOW)
        self.assertLess(st["rate_day"], 400000)            # the 24 h window alone would say ~1.4M/day
        self.assertIn("račun", st["rate_src"])
        self.assertNotIn("helius:pace", keys(con))

    def test_busy_yesterday_is_not_todays_pace(self):
        con = fresh()
        # 31.10.-like: 2.4M spread over a whole busy day 26-50 h ago, then a calm 220k/day
        pts, used = [], 0.0
        for h in range(72, -1, -1):
            pts.append((h, used))
            used += 100000 if 26 <= h < 50 else 220000 / 24
        self.snaps(con, pts)
        con.commit()
        st = watch.status(con, "helius", watch.config(), NOW)
        self.assertLess(st["rate_day"], 300000)

    def test_lasting_rise_still_counts(self):
        con = fresh()
        pts, used = [], 0.0
        for h in range(72, -1, -1):
            pts.append((h, used))
            used += (900000 if h <= 12 else 200000) / 24
        self.snaps(con, pts)
        con.commit()
        st = watch.status(con, "helius", watch.config(), NOW)
        self.assertGreater(st["rate_day"], 500000)

    def test_short_meter_is_not_extrapolated(self):
        con = fresh()
        add(con, 0, 2.0, service="apify")                 # $2 in the first hour of counting: not $48/day
        con.commit()
        st = watch.status(con, "apify", watch.config(), NOW)
        self.assertEqual(st["rate_day"], 0.0)
        self.assertNotIn("apify:pace", keys(con))

    def test_ongoing_warning_logged_once_a_day(self):
        con = fresh()
        a = [{"key": "helius:pace", "service": "helius", "level": "warn", "title": "t", "detail": "d"}]
        logged = 0
        for i in range(96):                                # one day of 15-min checks
            watch.remember(con, a, NOW + i * 900)
            logged += len(watch.to_log(con, a, NOW + i * 900))
        self.assertEqual(logged, 1)
        a[0]["level"] = "bad"                              # got worse: logged again at once
        watch.remember(con, a, NOW + 96 * 900)
        self.assertEqual(len(watch.to_log(con, a, NOW + 96 * 900)), 1)
        self.assertEqual(len(watch.to_log(con, a, NOW + 97 * 900)), 0)

    def test_nested_rpc_answer_and_webhook_events(self):
        body = json.dumps({"method": "getTransactionsForAddress", "params": ["W", {"limit": 1000}]}).encode()
        self.assertEqual(meter.helius_cost("https://mainnet.helius-rpc.com/", body,
                                           {"jsonrpc": "2.0", "result": {"data": [0] * 450}})[1], 50)
        fresh()
        meter.helius_webhook(37)
        meter.helius_webhook(0, managed=True)
        meter.flush()
        con = meter.connect()
        got = dict(con.execute("SELECT method, SUM(amount) FROM usage GROUP BY method"))
        self.assertEqual(got, {"webhook događaji": 37.0, "webhook upravljanje": 100.0})
        self.assertEqual(meter.helius_category("webhook događaji"), "webhooks")
        self.assertEqual(meter.helius_category("getTokenAccounts"), "das")

    def test_outside_names_the_category(self):
        con = fresh()
        for h in range(12):
            add(con, h, 1000, method="getBalance")
        self.snaps(con, [(10, 1e6), (0.02, 1e6 + 300000)],
                   extra=lambda h: {"credits": {"rpc": 500000 + (12000 if h < 1 else 0),
                                                "webhooks": 100000 + (288000 if h < 1 else 0)}})
        con.commit()
        out = {a["key"]: a for a in watch.evaluate(con, now=NOW)}
        self.assertIn("helius:outside", out)
        self.assertIn("webhook događaji", out["helius:outside"]["detail"])


class Page(unittest.TestCase):
    def test_page_and_banner(self):
        con = fresh()
        for h in range(48):
            add(con, h, 30000)
        con.commit()
        from ui import usage
        orig = watch.evaluate
        watch.evaluate = lambda c, cfg=None, now=None: orig(c, cfg, NOW)
        self.addCleanup(setattr, watch, "evaluate", orig)
        title, body = usage.page({})
        self.assertIn("Potrošnja kredita", body)
        usage._cache["ts"] = 0
        self.assertIn("/usage", usage.banner())
        meter.DB = os.path.join(tempfile.mkdtemp(), "none.db")
        self.assertIn("Bot još nije napravio nijedan plaćeni poziv", usage.page({})[1])


if __name__ == "__main__":
    unittest.main()
