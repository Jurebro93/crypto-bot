"""11.11. (Jure: "real-time zone alarm na Grok Bot", data flag zonewatch G25): zonewatch/. The state machine with its
hysteresis, the debounce (30 min; stop_hit always, at most once a minute), the POST's retries (timeout / 5xx / 429
only, 1-2-4 s, Retry-After capped at 10 s, the same alert id / webhook-id on every try), Bearer and Standard Webhooks
headers against known vectors, the key and the URL's path never in a log, a table or an error, no POST without the
env, Hope's fall on 11.11. (00:00 CET ~133k -> 03:55 CET ~92k: exactly one dca zone_enter, one zone_exit, no stop, no
top), arm_zone / get_armed_zones (schema, validation, ttl, upsert, limits, disarm), the HOPE seed once, the range
engine's zones, team_catalyst rows forwarded once, get_hourly_brief's part, the CPU guard and start.sh. No network.

    python3 -m unittest tests.test_zonewatch_offline
"""
import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import io
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from events import store as estore  # noqa: E402
from trade import settings  # noqa: E402
from zonewatch import job, notify, prices, store, view, zones  # noqa: E402

HOPE = store.SEED["mint"]
MINT = "Zone1111111111111111111111111111111111pump"
MINT2 = "Zone2222222222222222222222222222222222pump"
NOW = 1794384000   # 2026-11-11 08:00 UTC
SECRET_PATH = "/v1/routines/rt_SECRETPATH123/trigger"
SECRET_QUERY = "token=QSECRET987"
URL = f"https://hooks.example.test{SECRET_PATH}?{SECRET_QUERY}"
KEY = "sk-SUPERSECRETKEY-abc123"


def _reset_events():
    with estore._LOCK:
        estore._Q.clear()
        if estore._STATE.get("con") is not None:
            try:
                estore._STATE["con"].close()
            except sqlite3.Error:
                pass
        estore._STATE.update(con=None, con_path=None, path=None, exists_at=0.0, exists=False, fails=0)
    estore._TIGHT.update(at=0.0, val=False)


class Opener:
    """A urllib stand-in: answers from a list (an int status, (status, headers) or an exception), records requests."""

    def __init__(self, answers):
        self.answers, self.reqs = list(answers), []

    def __call__(self, req, timeout):
        self.reqs.append({"url": req.full_url, "headers": {k.lower(): v for k, v in req.header_items()},
                          "body": req.data, "timeout": timeout})
        a = self.answers.pop(0) if self.answers else 200
        if isinstance(a, BaseException):
            raise a
        st, hd = a if isinstance(a, tuple) else (a, {})
        if st >= 300:
            raise urllib.error.HTTPError(req.full_url, st, "x", hd, io.BytesIO(b""))
        return st, hd


class Clock:
    def __init__(self, t=NOW):
        self.t, self.slept = float(t), []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def pair(tok, mcap, sym="HOPE", liq=40_000.0):
    return {"chainId": "solana", "baseToken": {"address": tok, "symbol": sym}, "priceUsd": str(mcap / 1e9),
            "marketCap": mcap, "dexId": "pumpswap", "pairAddress": "Pool" + tok[:6], "liquidity": {"usd": liq},
            "volume": {"m5": 2000.0, "h1": 30_000.0}, "txns": {"m5": {"buys": 7, "sells": 3}, "h1": {"buys": 60, "sells": 40}},
            "priceChange": {"m5": -1.0}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.db = os.path.join(d, "zonewatch.db")
        env = {"ZONEWATCH_DB": self.db, "RANGE_DB": os.path.join(d, "range.db"),
               "RANGE_HYPE_DB": os.path.join(d, "hype.db"), "EVENTS_DB": os.path.join(d, "events.db")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("GROKBOT_WEBHOOK_URL", "GROKBOT_WEBHOOK_KEY", "GROKBOT_WEBHOOK_AUTH"):
            os.environ.pop(k, None)
        self._sdb = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        settings._FLAG_CACHE.clear()
        self.tcon = settings.connect()
        self.addCleanup(self._restore)
        _reset_events()
        self.addCleanup(_reset_events)
        prices._RUG.clear()
        self.con = store.connect()
        self.addCleanup(self.con.close)

    def _restore(self):
        self.tcon.close()
        settings.DB = self._sdb
        settings._FLAG_CACHE.clear()

    def flag(self, m):
        settings.put(self.tcon, "flag:zonewatch", {"mode": m, "since": NOW})
        settings._FLAG_CACHE.clear()

    def cfg(self, key=KEY, auth=None):
        return notify.Config(URL, key, auth)

    def zone(self, zt, lo, hi, source="manual", mint=MINT):
        return {"mint": mint, "zone_type": zt, "lo": lo, "hi": hi, "source": source, "note": None, "symbol": "TST"}

    def all_text(self):
        """Every value of every table of zonewatch.db (and events.db) as one string."""
        out = []
        for path in (self.db, os.environ["EVENTS_DB"]):
            if not os.path.exists(path):
                continue
            c = sqlite3.connect(path)
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                out += [repr(r) for r in c.execute(f"SELECT * FROM {t}")]
            c.close()
        return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------------------
class StateMachine(Base):
    def run_series(self, z, series, prev=None):
        evs = []
        for i, mc in enumerate(series):
            prev, ev, _ = zones.step(z, prev, mc, NOW + i * 30)
            if ev:
                evs.append((i, ev))
        return evs, prev

    def test_hysteresis_at_the_edge_no_flapping(self):
        z = self.zone("dca", 100_000, 105_000)
        # enter at 104.9k; 105.3k and 104.8k jitter on the upper edge stay inside (+0.5 % = 105,525); 105.6k leaves
        evs, _ = self.run_series(z, [110_000, 104_900, 105_300, 104_800, 105_400, 105_600, 105_100, 104_900])
        self.assertEqual(evs, [(1, "zone_enter"), (5, "zone_exit"), (7, "zone_enter")])   # 105.1k: still outside
        evs, _ = self.run_series(z, [110_000, 104_000, 99_600, 100_100, 99_550, 99_400])   # lower edge: -0.5 % = 99,500
        self.assertEqual(evs, [(1, "zone_enter"), (5, "zone_exit")])

    def test_stop_top_and_first_observation(self):
        stop = self.zone("stop", 85_000, 85_000)
        evs, _ = self.run_series(stop, [90_000, 84_000, 85_300, 84_900, 86_000, 84_500])
        self.assertEqual(evs, [(1, "stop_hit"), (5, "stop_hit")])            # back above the stop: no alarm
        top = self.zone("top", 145_000, 155_000)
        evs, _ = self.run_series(top, [140_000, 146_000, 160_000, 144_500, 144_000])
        self.assertEqual(evs, [(1, "top_hit"), (4, "zone_exit")])            # above top_hi is still the top
        # first observation inside: a hand-armed zone alarms once (initial), a range zone never
        st, ev, ex = zones.step(self.zone("dca", 100_000, 105_000), None, 102_000, NOW)
        self.assertEqual((ev, ex["initial"], st["inside"]), ("zone_enter", True, True))
        st, ev, _ = zones.step(self.zone("dca", 100_000, 105_000, "range"), None, 102_000, NOW)
        self.assertIsNone(ev)
        self.assertTrue(st["inside"])
        self.assertEqual(zones.distance(self.zone("dca", 100_000, 105_000), 120_000), (0.125, "below"))
        self.assertEqual(zones.distance(self.zone("stop", 85_000, 85_000), 85_000)[1], "inside")


# ---------------------------------------------------------------------------------------------------------------------
class Debounce(Base):
    def evaluate(self, mc, t, mint=MINT):
        snaps = {mint: {"ts": t, "mcap": mc, "price": mc / 1e9, "liq": 40_000.0, "buys_m5": 7, "sells_m5": 3,
                        "buys_h1": 60, "sells_h1": 40, "src": "pulse", "symbol": "TST"}}
        out, deb = job.evaluate(self.con, store.active(self.con, t), snaps, t, rug_fn=lambda *a: "ok",
                                uniq_fn=lambda *a: 42)
        return [p["event"] for p in out], deb

    def test_second_enter_within_30_min_suppressed_then_allowed(self):
        store.arm(MINT, "dca", 100_000, 105_000, kid="owner", now=NOW, con=self.con)
        self.assertEqual(self.evaluate(110_000, NOW), ([], 0))
        self.assertEqual(self.evaluate(102_000, NOW + 30), (["zone_enter"], 0))
        self.assertEqual(self.evaluate(110_000, NOW + 60), (["zone_exit"], 0))
        self.assertEqual(self.evaluate(102_000, NOW + 120), ([], 1))          # 2nd enter within 30 min
        self.assertEqual(self.evaluate(110_000, NOW + 180), ([], 1))          # 2nd exit within 30 min
        self.assertEqual(self.evaluate(102_000, NOW + 30 + 1800), (["zone_enter"], 0))   # 30 min after the first
        p = json.loads(self.con.execute("SELECT payload FROM alerts WHERE event='zone_enter' ORDER BY ts").fetchone()[0])
        self.assertEqual((p["rug_risk"], p["uniq_traders_1h"], p["buy_share_5m"], p["buy_share_1h"]), ("ok", 42, 0.7, 0.6))

    def test_stop_hit_always_but_at_most_once_a_minute(self):
        store.arm(MINT, "stop", 85_000, None, kid="owner", now=NOW, con=self.con)
        self.assertEqual(self.evaluate(90_000, NOW), ([], 0))
        self.assertEqual(self.evaluate(84_000, NOW + 30), (["stop_hit"], 0))
        self.assertEqual(self.evaluate(90_000, NOW + 40), ([], 0))
        self.assertEqual(self.evaluate(84_000, NOW + 60), ([], 1))            # 30 s after the last: held back
        self.assertEqual(self.evaluate(90_000, NOW + 70), ([], 0))
        self.assertEqual(self.evaluate(84_000, NOW + 100), (["stop_hit"], 0))   # 70 s later: always alarms

    def test_two_sources_of_the_same_zone_alarm_once(self):
        store.arm(MINT, "dca", 100_000, 105_000, kid="owner", now=NOW, con=self.con)
        store.upsert(self.con, MINT, "dca", 99_000, 104_000, "raspon", "range", "range", NOW + 900, NOW)
        self.evaluate(110_000, NOW)
        evs, _ = self.evaluate(102_000, NOW + 30)
        self.assertEqual(evs, ["zone_enter"])
        self.assertEqual(self.con.execute("SELECT source FROM alerts").fetchall(), [("manual",)])


# ---------------------------------------------------------------------------------------------------------------------
class Delivery(Base):
    def payload(self, aid="zw_1794384000_abcdef0123"):
        return notify.normalize({"id": aid, "event": "zone_enter", "mint": MINT, "zone_type": "dca", "zone_lo": 1e5,
                                 "zone_hi": 1.05e5, "mcap": 102_000, "source": "manual", "ts": NOW})

    def test_timeout_5xx_429_retried_three_times_with_backoff_same_id(self):
        c = Clock()
        op = Opener([TimeoutError("timed out"), 503, (429, {"Retry-After": "7"}), 200])
        res = notify.post(self.cfg(auth="standard"), self.payload(), op, c.sleep, c)
        self.assertTrue(res["ok"])
        self.assertEqual((res["attempts"], res["status"]), (4, "sent"))
        self.assertEqual(c.slept, [1, 2, 7])                                   # 429's Retry-After 7 s > backoff 4 s
        ids = {r["headers"]["webhook-id"] for r in op.reqs}
        self.assertEqual(ids, {"zw_1794384000_abcdef0123"})                     # the same id on every try
        self.assertEqual(len({r["headers"]["webhook-timestamp"] for r in op.reqs}), 4)   # fresh per attempt
        self.assertEqual({r["body"] for r in op.reqs}.__len__(), 1)
        self.assertTrue(all(r["timeout"] == 5 for r in op.reqs))
        # all four fail: 1 + 3 retries, then failed; Retry-After capped at 10 s
        c = Clock()
        op = Opener([500, urllib.error.URLError(f"cannot reach {URL}"), (429, {"Retry-After": "120"}), 502])
        res = notify.post(self.cfg(), self.payload(), op, c.sleep, c)
        self.assertEqual((res["ok"], res["status"], res["attempts"]), (False, "failed", 4))
        self.assertEqual(c.slept, [1, 2, 10])

    def test_400_401_403_404_and_redirects_not_retried(self):
        for code in (400, 401, 403, 404, 301):
            c = Clock()
            op = Opener([code, 200])
            res = notify.post(self.cfg(), self.payload(), op, c.sleep, c)
            self.assertEqual((res["status"], res["attempts"], res["http_status"], c.slept), ("config_error", 1, code, []))

    def test_bearer_header_and_standard_webhooks_vectors(self):
        op = Opener([200])
        p = self.payload()
        notify.post(self.cfg(), p, op, Clock().sleep, Clock())
        h = op.reqs[0]["headers"]
        self.assertEqual(h["authorization"], f"Bearer {KEY}")
        self.assertEqual(h["content-type"], "application/json")
        self.assertNotIn("webhook-signature", h)
        self.assertEqual(op.reqs[0]["body"], json.dumps(p, separators=(",", ":"), ensure_ascii=False).encode())
        # Standard Webhooks: the published example (whsec_ secret, msg id, timestamp, body) ...
        self.assertEqual(notify.signature("whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", "msg_p5jXN8AQM9LWM0D4loKWxJek",
                                          1614265330, b'{"test": 2432232314}'),
                         "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=")
        # ... and a vector computed here: HMAC-SHA256(base64-decoded secret, "id.ts.body")
        raw = b"zonewatch-test-secret-32-bytes!!"
        key = "whsec_" + base64.b64encode(raw).decode()
        cfg = notify.Config(URL, key)                                           # whsec_ switches to standard by itself
        self.assertEqual(cfg.auth, "standard")
        op, c = Opener([200]), Clock(1_800_000_000)
        notify.post(cfg, p, op, c.sleep, c)
        h, body = op.reqs[0]["headers"], op.reqs[0]["body"]
        want = base64.b64encode(hmac.new(raw, f"{p['id']}.1800000000.".encode() + body, hashlib.sha256).digest()).decode()
        self.assertEqual((h["webhook-id"], h["webhook-timestamp"], h["webhook-signature"]),
                         (p["id"], "1800000000", f"v1,{want}"))
        self.assertNotIn("authorization", h)                                     # the secret never travels
        # GROKBOT_WEBHOOK_AUTH=standard with a key that is not base64: its raw UTF-8 bytes
        cfg = notify.Config(URL, "plain-key-not-b64!", "standard")
        sig = notify.signature(cfg.key, "a", 1, b"{}")
        self.assertEqual(sig, "v1," + base64.b64encode(hmac.new(b"plain-key-not-b64!", b"a.1.{}", hashlib.sha256)
                                                       .digest()).decode())

    def test_payload_has_every_owner_field_plus_event_and_id(self):
        p = notify.normalize({"mint": MINT, "zone_type": "team_catalyst", "ts": NOW, "extra": 1})
        for k in notify.OWNER_FIELDS + ("id", "event"):
            self.assertIn(k, p)
        self.assertEqual((p["event"], p["rug_risk"], p["extra"]), ("team_catalyst", None, 1))
        self.assertEqual(p["id"], notify.normalize({"mint": MINT, "zone_type": "team_catalyst", "ts": NOW})["id"])


# ---------------------------------------------------------------------------------------------------------------------
class Secrets(Base):
    def test_key_and_url_never_in_stdout_tables_results_or_errors(self):
        self.flag("shadow")
        cfg = self.cfg()
        self.assertNotIn(KEY, repr(cfg) + str(cfg))
        self.assertNotIn("SECRETPATH", repr(cfg))
        out = io.StringIO()
        results = []
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            for answers in ([200], [401], [urllib.error.URLError(f"no route to {URL} key={KEY}")] * 4,
                            [RuntimeError(f"boom {URL} {KEY}")] * 4, [(503, {"Retry-After": "x"})] * 4):
                c = Clock()
                results.append(notify.post_alert({"mint": MINT, "zone_type": "dca", "event": "zone_enter",
                                                  "ts": NOW + len(results)}, con=self.con, cfg=cfg, flag="shadow",
                                                 opener=Opener(answers), sleep=c.sleep, clock=c))
            for kind in ("standard",):   # the signing secret must never be logged either
                c = Clock()
                results.append(notify.post_alert({"mint": MINT, "zone_type": "dca", "event": "zone_exit", "ts": NOW + 9},
                                                 con=self.con, cfg=notify.Config(URL, KEY, kind), flag="shadow",
                                                 opener=Opener([500, 200]), sleep=c.sleep, clock=c))
        self.assertEqual([r["status"] for r in results], ["sent", "config_error", "failed", "failed", "failed", "sent"])
        text = out.getvalue() + "\n" + self.all_text() + "\n" + json.dumps(results)
        for secret in (KEY, SECRET_PATH, "SECRETPATH", SECRET_QUERY, "QSECRET", URL):
            self.assertNotIn(secret, text, secret)
        hosts = {r[0] for r in self.con.execute("SELECT DISTINCT host FROM zonewatch_log")}
        self.assertEqual(hosts, {"https://hooks.example.test"})
        errs = {r[0] for r in self.con.execute("SELECT DISTINCT error FROM zonewatch_log WHERE error IS NOT NULL")}
        self.assertTrue(errs <= {"HTTP 401", "URLError", "RuntimeError", "HTTP 503", "HTTP 500"}, errs)
        lat = self.con.execute("SELECT COUNT(*) FROM zonewatch_log WHERE latency_ms IS NULL").fetchone()[0]
        self.assertEqual(lat, 0)
        last = store.kv_get(self.con, "last_error")
        self.assertEqual(last["status"], "failed")
        self.assertNotIn(KEY, json.dumps(view.brief_part(NOW)))

    def test_a_pass_that_raises_never_shows_the_url(self):
        import run_zonewatch
        logs = []

        def boom(**k):
            raise ValueError(f"{URL} {KEY}")
        with mock.patch.object(job, "pass_once", boom), mock.patch.object(time, "sleep", side_effect=[None, StopIteration]):
            with self.assertRaises(StopIteration):
                run_zonewatch.loop(log=logs.append)
        self.assertEqual(logs, ["zonewatch: prolaz nije uspio (ValueError)"])


# ---------------------------------------------------------------------------------------------------------------------
class NotConfigured(Base):
    def test_no_post_status_not_configured_one_line_a_day_health_false(self):
        self.flag("shadow")
        op = Opener([200])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for i in range(3):
                r = notify.post_alert({"mint": MINT, "zone_type": "dca", "event": "zone_enter", "ts": NOW + i},
                                      con=self.con, opener=op, now=NOW + i)
                self.assertEqual(r["status"], "not_configured")
        self.assertEqual(op.reqs, [])
        self.assertEqual(out.getvalue().count("webhook nije postavljen"), 1)
        st = self.con.execute("SELECT status, COUNT(*) FROM zonewatch_log GROUP BY status").fetchall()
        self.assertEqual(st, [("not_configured", 3)])
        self.assertEqual({r[0] for r in self.con.execute("SELECT status FROM alerts")}, {"not_configured"})
        b = view.brief_part(NOW)
        self.assertFalse(b["configured"])
        self.assertEqual((b["alerts_24h"], b["last_post_ok"], b["last_error"]), (3, None, None))
        self.assertFalse(notify.config({"GROKBOT_WEBHOOK_URL": "http://hooks.example.test/x",
                                        "GROKBOT_WEBHOOK_KEY": "k"}).configured)   # not https
        self.assertTrue(notify.config({"GROKBOT_WEBHOOK_URL": URL, "GROKBOT_WEBHOOK_KEY": "k"}).configured)

    def test_flag_off_watches_nothing_posts_nothing(self):
        self.assertEqual(job.pass_once(fetch=lambda t: self.fail("fetched")), {"mode": "off"})
        r = notify.post_alert({"mint": MINT, "zone_type": "dca", "event": "zone_enter"}, con=self.con,
                              cfg=self.cfg(), opener=Opener([200]))
        self.assertEqual(r["status"], "off")
        self.assertIn("zonewatch", settings.FLAGS)
        self.assertEqual(settings.FLAGS["zonewatch"][0], "G25")
        self.assertIn("zonewatch", settings.DATA_FLAGS)
        self.assertEqual(settings.flag("zonewatch", con=self.tcon), "off")


# ---------------------------------------------------------------------------------------------------------------------
class HopeReplay(Base):
    """11.11.: Hope fell from ~133k at 00:00 CET to the bottom ~92k at 03:55 CET (then a small bounce). Passes every
    30 s with DexScreener answering the series: exactly one zone_enter for the dca zone (100-105k) while crossing, one
    zone_exit under 100k, no stop_hit (85k), no top_hit (145k)."""
    T0 = int(dt.datetime(2026, 11, 10, 23, 0, tzinfo=dt.timezone.utc).timestamp())   # 00:00 CET 11.11.
    BOTTOM = 3 * 3600 + 55 * 60

    def mcap(self, t):
        k = t - self.T0
        base = 133_000 - 41_000 * k / self.BOTTOM if k <= self.BOTTOM else 92_000 + 4_000 * (k - self.BOTTOM) / 2100
        return base * (1 + 0.002 * math.sin(k / 97.0) + 0.001 * math.sin(k / 13.0))   # +-0.3 % jitter

    def test_replay(self):
        self.flag("shadow")
        clock = Clock(self.T0)
        op = Opener([200] * 50)
        asked, seen = [], []

        def fetch(toks):
            asked.append(len(toks))
            seen.append(self.mcap(clock.t))
            return [pair(t, seen[-1]) for t in toks]
        for k in range(0, 4 * 3600 + 30 * 60 + 1, 30):
            clock.t = self.T0 + k
            job.pass_once(now=self.T0 + k, fetch=fetch, cfg=self.cfg(), opener=op, sleep=clock.sleep, clock=clock,
                          log=lambda s: None, rug_fn=lambda *a: "ok", uniq_fn=lambda *a: None, flag="shadow")
        probe = self.con.execute("SELECT status FROM alerts WHERE event='test'").fetchall()
        self.assertEqual(probe, [("sent",)])                                   # 11.11.: one probe at the first pass
        rows = self.con.execute("SELECT event, zone_type, ts, status, payload FROM alerts WHERE event != 'test' "
                                "ORDER BY ts").fetchall()
        evs = [(e, z) for e, z, *_ in rows]
        self.assertEqual(evs, [("zone_enter", "dca"), ("zone_exit", "dca")], rows)
        enter = json.loads(rows[0][4])
        cet = dt.datetime.fromtimestamp(rows[0][2], dt.timezone(dt.timedelta(hours=1)))
        self.assertTrue(dt.time(2, 25) <= cet.time() <= dt.time(2, 55), cet)
        self.assertTrue(100_000 <= enter["mcap"] <= 105_000 * 1.005, enter["mcap"])
        self.assertEqual((enter["zone_lo"], enter["zone_hi"], enter["source"], enter["symbol"]),
                         (100_000.0, 105_000.0, "manual", "HOPE"))
        self.assertEqual(enter["direction"], "down")
        for k in notify.OWNER_FIELDS + ("id", "event"):
            self.assertIn(k, enter)
        self.assertEqual({r[3] for r in rows}, {"sent"})
        self.assertEqual(len(op.reqs), 3)
        self.assertEqual(json.loads(op.reqs[0]["body"])["event"], "test")
        self.assertEqual(json.loads(op.reqs[1]["body"])["id"], enter["id"])
        self.assertLess(min(seen), 93_000)                                      # the bottom was seen ...
        self.assertGreater(min(seen), 85_000 * 1.05)                            # ... well above the stop
        self.assertTrue(all(n <= 30 for n in asked))
        self.assertLessEqual(sum(1 for _ in asked), 4 * 3600 // 30 + 2)   # at most one request a pass


# ---------------------------------------------------------------------------------------------------------------------
class ArmTools(Base):
    def tool(self, name, args, kid="abc123"):
        from ui import mcpapi
        return mcpapi._tool(name, args, kid=kid)

    def test_schema_validation_upsert_ttl_disarm_attribution(self):
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(names["get_armed_zones"]["annotations"]["readOnlyHint"])
        self.assertFalse(names["arm_zone"]["annotations"]["readOnlyHint"])
        self.assertEqual(names["arm_zone"]["inputSchema"]["required"], ["mint", "zone_type"])
        self.assertEqual(names["arm_zone"]["inputSchema"]["properties"]["zone_type"]["enum"],
                         ["bottom", "dca", "top", "stop", "custom"])
        for bad, why in (({"mint": "nope", "zone_type": "dca", "lo": 1e5, "hi": 2e5}, "mint"),
                         ({"mint": MINT, "zone_type": "floor", "lo": 1e5, "hi": 2e5}, "zone_type"),
                         ({"mint": MINT, "zone_type": "dca", "lo": 2e5, "hi": 1e5}, "lo must be <= hi"),
                         ({"mint": MINT, "zone_type": "dca", "lo": 1e5}, "needs lo and hi"),
                         ({"mint": MINT, "zone_type": "dca", "lo": 20_000, "hi": 25_000}, "30,000"),
                         ({"mint": MINT, "zone_type": "dca", "lo": 1e5, "hi": 2e5, "ttl_h": 721}, "ttl_h"),
                         ({"mint": MINT, "zone_type": "dca", "lo": True, "hi": 2e5}, "number"),
                         ({"mint": MINT, "zone_type": "dca", "lo": 1e5, "hi": 2e5, "source": "range"}, "range engine")):
            d, err = self.tool("arm_zone", bad)
            self.assertTrue(err, bad)
            self.assertIn(why, d["error"])
        d, err = self.tool("arm_zone", {"mint": MINT, "zone_type": "stop", "lo": 85_000, "note": "x"})
        self.assertFalse(err, d)
        self.assertEqual((d["zone"]["lo"], d["zone"]["hi"], d["changed"]), (85_000.0, 85_000.0, "created"))
        d, _ = self.tool("arm_zone", {"mint": MINT, "zone_type": "dca", "lo": 100_000, "hi": 105_000, "ttl_h": 2})
        zid = self.con.execute("SELECT id FROM armed_zones WHERE mint=? AND zone_type='dca'", (MINT,)).fetchone()[0]
        d, _ = self.tool("arm_zone", {"mint": MINT, "zone_type": "dca", "lo": 101_000, "hi": 106_000})   # upsert
        self.assertEqual(d["changed"], "updated")
        row = self.con.execute("SELECT id, lo, hi, kid, expires_at - updated_ts FROM armed_zones WHERE mint=? AND "
                               "zone_type='dca'", (MINT,)).fetchone()
        self.assertEqual(row, (zid, 101_000.0, 106_000.0, "mcp:abc123", 72 * 3600))
        g, err = self.tool("get_armed_zones", {"mint": MINT})
        self.assertFalse(err, g)
        self.assertEqual({z["zone_type"] for z in g["zones"]}, {"stop", "dca"})
        self.assertEqual(g["zones"][0]["armed_by"], "mcp:abc123")
        for k in ("state", "distance_pct", "last_alert", "expires_at", "mcap_now"):
            self.assertIn(k, g["zones"][0])
        self.assertIn("ttl_h=0", g["how"])
        # disarm with ttl_h=0; a second disarm has nothing left
        d, err = self.tool("arm_zone", {"mint": MINT, "zone_type": "dca", "ttl_h": 0})
        self.assertEqual((err, d["changed"]), (False, "disarmed"))
        d, err = self.tool("arm_zone", {"mint": MINT, "zone_type": "dca", "ttl_h": 0})
        self.assertTrue(err)
        # ttl expiry
        store.arm(MINT2, "top", 145_000, 155_000, ttl_h=1, kid="owner", now=NOW, con=self.con)
        self.assertEqual(len(store.active(self.con, NOW + 3599, MINT2)), 1)
        self.assertEqual(store.active(self.con, NOW + 3600, MINT2), [])

    def test_rate_limit_and_cap(self):
        for i in range(store.RATE_PER_HOUR):
            store.arm(MINT, "dca", 100_000 + i, 105_000 + i, kid="mcp:k1", now=NOW + i, con=self.con)
        with self.assertRaisesRegex(ValueError, "rate limit"):
            store.arm(MINT, "dca", 100_000, 105_000, kid="mcp:k1", now=NOW + 100, con=self.con)
        store.arm(MINT, "dca", 100_000, 105_000, kid="mcp:k2", now=NOW + 100, con=self.con)   # another key
        store.arm(MINT, "dca", 100_000, 105_000, kid="mcp:k1", now=NOW + 3700, con=self.con)  # an hour later
        with mock.patch.object(store, "MAX_ARMED", 2):
            store.arm(MINT, "top", 145_000, 155_000, kid="mcp:k3", now=NOW, con=self.con)
            with self.assertRaisesRegex(ValueError, "at most 2 active"):
                store.arm(MINT2, "top", 145_000, 155_000, kid="mcp:k3", now=NOW, con=self.con)
            store.arm(MINT, "top", 146_000, 156_000, kid="mcp:k3", now=NOW, con=self.con)    # an update is fine

    def test_hope_seed_once_survives_restarts(self):
        self.assertTrue(store.seed_once(self.con, NOW))
        self.assertFalse(store.seed_once(self.con, NOW + 10))
        con2 = store.connect()
        self.assertFalse(store.seed_once(con2, NOW + 8 * 86400))   # expired, never re-armed
        con2.close()
        rows = self.con.execute("SELECT zone_type, lo, hi, source, note, expires_at - created_ts FROM armed_zones "
                                "WHERE mint=? ORDER BY zone_type", (HOPE,)).fetchall()
        self.assertEqual(rows, [("dca", 100_000.0, 105_000.0, "manual", "vlasnik ručno kupio ~133k", 7 * 86400),
                                ("stop", 85_000.0, 85_000.0, "manual", "vlasnik ručno kupio ~133k", 7 * 86400),
                                ("top", 145_000.0, 155_000.0, "manual", "vlasnik ručno kupio ~133k", 7 * 86400)])


# ---------------------------------------------------------------------------------------------------------------------
class RangeZones(Base):
    def test_active_ranges_become_zones_inactive_ones_expire(self):
        from rangedca import data
        rc = data.connect()
        res = {"ts": NOW, "status": "aktivan", "active": True, "score": 0.8, "pos_pct": 10.0,
               "zones": {"range_low_low": 60e-6, "range_low_top": 66e-6, "range_high_low": 95e-6, "range_high_top": 100e-6,
                         "range_low": 63e-6, "range_high": 97e-6,
                         "mc": {"range_low_low": 60_000, "range_low_top": 66_000, "range_high_low": 95_000,
                                "range_high_top": 100_000}},
               "metrics": {"price": 64e-6, "mcap": 64_000, "supply": 1e9}, "source": "market"}
        data.save_range(rc, MINT, res, {}, "RNG")
        data.save_range(rc, MINT2, dict(res, active=False, status="slab volumen"), {}, "OFF")
        rc.commit()
        rc.close()
        toks, n = store.sync_range(self.con, NOW + 60, lot1={}, eligible={MINT})
        self.assertEqual((toks, n), (1, 4))
        z = {r[0]: (r[1], r[2]) for r in self.con.execute("SELECT zone_type, lo, hi FROM armed_zones WHERE source='range' "
                                                          "AND mint=?", (MINT,))}
        self.assertEqual(z["bottom"], (60_000.0, 66_000.0))
        self.assertEqual(z["top"], (95_000.0, 100_000.0))
        self.assertEqual(z["stop"], (51_000.0, 51_000.0))                       # range_low_low x 0.85
        self.assertEqual(z["dca"], (55_200.0, 56_700.0))                        # 63k x 0.90 / max(63k x 0.85, 60k x 0.92)
        self.assertEqual(store.sync_range(self.con, NOW + 90, lot1={}, eligible={MINT})[1], 0)   # nothing moved: nothing written
        # the engine moving a range zone's edges keeps its state (the zone moving onto the price is an entry too)
        store.save_state(self.con, (MINT, "bottom", "range"), {"inside": False, "since_ts": NOW, "last_mcap": 67_000,
                                                               "last_ts": NOW})
        store.upsert(self.con, MINT, "bottom", 61_000, 68_000, "raspon", "range", "range", NOW + 900, NOW, reset=False)
        self.assertEqual(store.states(self.con)[(MINT, "bottom", "range")]["inside"], False)
        store.upsert(self.con, MINT, "bottom", 60_000, 66_000, "raspon", "range", "range", NOW + 900, NOW, reset=False)
        # an open round's lot 1 at 64k: dca -10..-15 % under it
        store.sync_range(self.con, NOW + 120, lot1={MINT: 64_000})
        self.assertEqual(self.con.execute("SELECT lo, hi FROM armed_zones WHERE zone_type='dca' AND source='range'")
                         .fetchone(), (55_200.0, 57_600.0))
        # the range goes away: its zones expire at once
        rc = data.connect()
        rc.execute("UPDATE ranges SET active=0")
        rc.commit()
        rc.close()
        store.sync_range(self.con, NOW + 180, lot1={})
        self.assertEqual(store.active(self.con, NOW + 181, source="range"), [])


# ---------------------------------------------------------------------------------------------------------------------
class Catalyst(Base):
    def test_team_catalyst_rows_forwarded_once_and_dual_write(self):
        self.flag("shadow")
        econ = estore.connect(os.environ["EVENTS_DB"])
        ins = ("INSERT INTO events (ts, mint, type, source, actor, mcap_usd, payload, uid) VALUES (?,?,?,?,?,?,?,?)")
        econ.execute(ins, ((NOW - 7200) * 1000, MINT, "team_catalyst", "x", "team", 90_000, "{}", 1))   # old: skipped
        econ.execute(ins, ((NOW - 60) * 1000, MINT, "team_catalyst", "x", "team", 95_000,
                           json.dumps({"symbol": "TST", "why": "tim objavio partnerstvo"}), 2))
        econ.execute(ins, ((NOW - 50) * 1000, MINT, "call", "x", "caller", 95_000, "{}", 3))
        econ.commit()
        op, c = Opener([200, 200]), Clock()
        sent = []
        for k in range(2):
            job.forward_catalyst(self.con, NOW + k, log=sent.append)
            job.deliver_pending(self.con, NOW + k, self.cfg(), "shadow", op, c.sleep, c)
        self.assertEqual(len(op.reqs), 1)
        body = json.loads(op.reqs[0]["body"])
        self.assertEqual((body["zone_type"], body["event"], body["mint"], body["mcap"], body["symbol"]),
                         ("team_catalyst", "team_catalyst", MINT, 95_000, "TST"))
        self.assertEqual(body["id"], f"tc_{econ.execute('SELECT id FROM events WHERE uid=2').fetchone()[0]}")
        for k in notify.OWNER_FIELDS:
            self.assertIn(k, body)
        estore.flush(os.environ["EVENTS_DB"])
        self.assertEqual(econ.execute("SELECT COUNT(*) FROM events WHERE type='zone_alert'").fetchone()[0], 1)
        econ.close()
        # direct callers: post_alert(dict) with the same id is a no-op the second time
        r1 = notify.post_alert({"id": "tc_direct_1", "zone_type": "team_catalyst", "mint": MINT}, con=self.con,
                               cfg=self.cfg(), flag="shadow", opener=Opener([200]), sleep=c.sleep, clock=c)
        r2 = notify.post_alert({"id": "tc_direct_1", "zone_type": "team_catalyst", "mint": MINT}, con=self.con,
                               cfg=self.cfg(), flag="shadow", opener=Opener([200]), sleep=c.sleep, clock=c)
        self.assertEqual((r1["status"], r2["status"]), ("sent", "duplicate"))

    def test_missing_events_db_or_table_is_nothing(self):
        self.assertEqual(job.forward_catalyst(self.con, NOW), [])
        c = sqlite3.connect(os.environ["EVENTS_DB"])
        c.execute("CREATE TABLE other (x)")
        c.commit()
        c.close()
        self.assertEqual(job.forward_catalyst(self.con, NOW), [])


# ---------------------------------------------------------------------------------------------------------------------
class Budget(Base):
    def test_four_requests_a_pass_near_first_and_the_day_cap(self):
        by = {f"Tok{i:03d}" + "1" * 36 + "pump": [self.zone("dca", 100_000, 105_000, "range")] for i in range(200)}
        snaps = {m: {"ts": NOW - 100, "mcap": 110_000 if i < 150 else 300_000} for i, m in enumerate(by)}
        due, prio = prices.plan(by, snaps, NOW)
        self.assertEqual(sum(1 for d in due if d[0] == 0), 150)                  # 150 near (within 10 %)
        self.assertEqual(len(due), 150)                                         # the far ones: their 100 s is fresh
        ask, dropped = prices.pick(due, prio, snaps, NOW, budget=1000)
        self.assertEqual((len(ask), dropped), (120, 30))                        # 4 x 30, never more a pass
        ask, dropped = prices.pick(due, prio, snaps, NOW, budget=1)
        self.assertEqual((len(ask), dropped), (30, 120))
        self.assertEqual(prices.pick(due, prio, snaps, NOW, budget=0), ([], 150))
        with mock.patch.object(prices, "DEX_DAY", 240):
            t = int(dt.datetime(2026, 11, 11, 0, 30, tzinfo=dt.timezone.utc).timestamp())
            self.assertEqual(prices.budget_left(self.con, t), 5)               # 00:30 UTC: 240 x 1860 / 86400
            store.day_add(self.con, "dex", 5, t)
            self.assertEqual(prices.budget_left(self.con, t), 0)
            self.assertEqual(prices.budget_left(self.con, t + 3600), 10)         # an hour later: 10 more
        # one near token: its request is filled up with the stalest others (no extra cost)
        snaps2 = {m: {"ts": NOW - 200, "mcap": 300_000} for m in by}
        first = next(iter(by))
        snaps2[first] = {"ts": NOW - 40, "mcap": 104_000}
        due, prio = prices.plan(by, snaps2, NOW)
        ask, _ = prices.pick(due, prio, snaps2, NOW, budget=10)
        self.assertEqual((ask[0], len(ask)), (first, 30))
        # the default request: DexScreener's live path (5 s, no retry), an error is no snapshot this pass
        from dexscreener import client
        seen = []
        with mock.patch.object(client, "tokens_live", lambda ch, toks, ttl=None: seen.append((ch, toks, ttl)) or []):
            self.assertEqual(prices.fetch_pairs([MINT]), [])
        self.assertEqual(seen, [("solana", [MINT], 20)])
        out = io.StringIO()
        with mock.patch.object(client, "tokens_live", mock.Mock(side_effect=OSError(f"x {URL}"))), \
                contextlib.redirect_stdout(out):
            self.assertEqual(prices.fetch_pairs([MINT]), [])
        self.assertNotIn("SECRETPATH", out.getvalue())
        # a mint DexScreener does not know waits 15 min (a wrong or dead mint costs nothing)
        got = prices.poll(self.con, [MINT, MINT2], NOW, fetch=lambda toks: [pair(MINT, 120_000)])
        self.assertEqual(list(got), [MINT])
        cold = prices.cold(self.con, NOW)
        self.assertEqual(set(cold), {MINT2})
        due, _ = prices.plan({MINT2: [self.zone("dca", 1e5, 1.05e5, mint=MINT2)]}, {}, NOW, cold)
        self.assertEqual(due, [])
        self.assertEqual(prices.cold(self.con, NOW + prices.COLD_S), {})
        self.assertEqual(store.day_used(self.con, "dex", NOW), 6)                 # 5 above + this one request


# ---------------------------------------------------------------------------------------------------------------------
class Brief(Base):
    def test_hourly_brief_zonewatch_part(self):
        from events import brief
        self.flag("shadow")
        store.seed_once(self.con, NOW)
        c = Clock()
        notify.post_alert({"mint": HOPE, "zone_type": "dca", "event": "zone_enter", "ts": NOW}, con=self.con,
                          cfg=self.cfg(), flag="shadow", opener=Opener([200]), sleep=c.sleep, clock=c, now=NOW)
        notify.post_alert({"mint": HOPE, "zone_type": "dca", "event": "zone_exit", "ts": NOW + 1}, con=self.con,
                          cfg=self.cfg(), flag="shadow", opener=Opener([401]), sleep=c.sleep, clock=c, now=NOW + 1)
        z = brief.zonewatch_part(NOW + 60)
        for k in ("armed", "alerts_24h", "last_post_ok", "last_error", "configured"):
            self.assertIn(k, z)
        self.assertEqual((z["armed"], z["alerts_24h"], z["last_post_ok"], z["configured"], z["flag_mode"]),
                         (3, 2, NOW, False, "shadow"))
        self.assertEqual((z["last_error"]["status"], z["last_error"]["http_status"]), ("config_error", 401))
        with mock.patch.dict(os.environ, {"GROKBOT_WEBHOOK_URL": URL, "GROKBOT_WEBHOOK_KEY": KEY}):
            self.assertTrue(brief.zonewatch_part(NOW + 60)["configured"])
        full = brief.build(now=NOW + 60)
        self.assertIn("zonewatch", full)
        self.assertIn("zonewatch", full["timing_ms"])
        from ui import mcpapi
        desc = {t["name"]: t for t in mcpapi.TOOLS}["get_hourly_brief"]["description"]
        self.assertIn("zonewatch", desc)


# ---------------------------------------------------------------------------------------------------------------------
class Process(unittest.TestCase):
    def test_cpuguard_and_start_sh(self):
        from ops import cpuguard as g
        name, rank, why = g.classify(["python3", "run_zonewatch.py", "loop"])
        self.assertEqual((name, rank), ("zonewatch", g.JOBS))
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("low keep zonewatch python3 run_zonewatch.py loop", sh)
        self.assertNotIn("ops.heavy --night run_zonewatch", sh)
        self.assertIn("zone_alert", estore.TYPES)
        from events import health
        st = [{"type": "zone_alert", "active": True, "last_ts": NOW - 7200, "gap_min": 120.0, "sources": {}}]
        self.assertEqual(health.alerts_for(st, now=int(dt.datetime(2026, 11, 11, 11, 0, tzinfo=dt.timezone.utc)
                                                             .timestamp())), [])   # sparse by nature: never a gap


if __name__ == "__main__":
    unittest.main()


class Faza11(Base):
    """11.11. (Jure): range zones only for open rounds / entry-ready tokens; the probe alarm once."""

    def test_range_zones_only_for_eligible_tokens(self):
        a, b = "A" * 43, "B" * 43
        rows = [(a, "AAA", NOW, "signal", 0.8, 60_000, 70_000, 120_000, 130_000, None, None),
                (b, "BBB", NOW, "market", 0.8, 60_000, 70_000, 120_000, 130_000, None, None)]
        toks, _n = store.sync_range(self.con, NOW, rows=rows, lot1={}, eligible={a})
        self.assertEqual(toks, 1)
        mints = {m for m, in self.con.execute("SELECT DISTINCT mint FROM armed_zones WHERE source='range'")}
        self.assertEqual(mints, {a})

    def test_probe_once_only_when_configured(self):
        self.assertIsNone(job.probe_once(self.con, NOW, notify.config({}), log=lambda s: None))
        cfg = notify.config({"GROKBOT_WEBHOOK_URL": "https://grok.example/hook", "GROKBOT_WEBHOOK_KEY": "k"})
        pid = job.probe_once(self.con, NOW, cfg, log=lambda s: None)
        self.assertTrue(pid)
        self.assertIsNone(job.probe_once(self.con, NOW + 60, cfg, log=lambda s: None))
        ev = self.con.execute("SELECT event, status FROM alerts WHERE id=?", (pid,)).fetchone()
        self.assertEqual(ev, ("test", "pending"))

