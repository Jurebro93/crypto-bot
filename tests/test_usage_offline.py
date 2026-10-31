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
        self.assertIn("Još nema usage.db", usage.page({})[1])


if __name__ == "__main__":
    unittest.main()
