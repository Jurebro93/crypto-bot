"""11.11. (Jure: "real-time zone alarm na Grok Bot", data flag zonewatch G25): zonewatch/. The state machine with its
hysteresis, the debounce (30 min; stop_hit always, at most once a minute), the POST's retries (timeout / 5xx / 429
only, 1-2-4 s, Retry-After capped at 10 s, the same alert id / webhook-id on every try), Bearer and Standard Webhooks
headers against known vectors, the key and the URL's path never in a log, a table or an error, no POST without the
env, arm_zone / get_armed_zones (schema, validation, ttl at most 2 h, upsert, limits, disarm), no fixed seed (the old
HOPE seed expired once), the range engine's zones (the only computed zones: rangedca/detect.py, read from range.db)
with their zone_version / computed_ts / window_h, eligibility (open round, entry-ready, a real-account position, and
only with an active range; else the reason is logged once), HOPE from the range.db snapshots of the 10.11. fixture
(rangedca's signal pass -> zonewatch, up to 22:18 CET), team_catalyst rows forwarded once, get_hourly_brief's part,
the CPU guard and start.sh. No network.

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

HOPE = "GxRPJsRK9TE9EgBhLxrFGcRYLGqPJe4fxtiPmdXCpump"   # the owner's manual position (11.11.); no zones are seeded
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
                         ({"mint": MINT, "zone_type": "dca", "lo": 1e5, "hi": 2e5, "ttl_h": 2.5}, "at most 2 h"),
                         ({"mint": MINT, "zone_type": "dca", "lo": 1e5, "hi": 2e5, "ttl_h": 72}, "ttl_h"),
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
        self.assertEqual(row, (zid, 101_000.0, 106_000.0, "mcp:abc123", 2 * 3600))   # 11.11.: default 2 h
        g, err = self.tool("get_armed_zones", {"mint": MINT})
        self.assertFalse(err, g)
        self.assertEqual({z["zone_type"] for z in g["zones"]}, {"stop", "dca"})
        self.assertEqual(g["zones"][0]["armed_by"], "mcp:abc123")
        for k in ("state", "distance_pct", "last_alert", "expires_at", "mcap_now"):
            self.assertIn(k, g["zones"][0])
        self.assertIn("ttl_h=0", g["how"])
        self.assertEqual((g["limits"]["ttl_h_default"], g["limits"]["ttl_h_max"]), (2, 2))
        for k in notify.RANGE_FIELDS:   # a hand-armed zone has no range version
            self.assertIsNone(g["zones"][0][k])
        sch = names["arm_zone"]["inputSchema"]["properties"]["ttl_h"]
        self.assertEqual((sch["maximum"], sch["default"]), (2, 2))
        self.assertIn("default 2, max 2", names["arm_zone"]["description"])
        self.assertNotIn("720", names["arm_zone"]["description"])
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

    def test_no_fixed_seed_and_the_old_one_expires_once(self):
        """11.11. (Jure: "nikad fiksni seed"): nothing arms HOPE by itself; the zones PR #122's seed may have armed
        expire once, and every hand-armed zone is cut to at most 2 h."""
        self.assertFalse(hasattr(store, "SEED") or hasattr(store, "seed_once"))
        # a zonewatch.db as PR #122 left it: the seed (7 days) and a hand-armed zone of 72 h
        for zt, lo, hi in (("dca", 100_000, 105_000), ("stop", 85_000, 85_000), ("top", 145_000, 155_000)):
            store.upsert(self.con, HOPE, zt, lo, hi, "vlasnik ručno kupio ~133k", "manual", store.OWNER,
                         NOW + 7 * 86400, NOW - 3600, "HOPE")
            self.con.execute("INSERT INTO arm_log VALUES (?,?,?,?,?,?)", (NOW - 3600, store.OWNER, HOPE, zt, "manual",
                                                                         "seed"))
        store.upsert(self.con, MINT, "custom", 60_000, 70_000, "grok", "manual", "mcp:k", NOW + 72 * 3600, NOW - 60)
        store.kv_put(self.con, "seed:hope_1111", NOW - 3600)   # the old key stays, harmless
        self.con.commit()
        said = []
        self.assertTrue(store.migrate_once(self.con, NOW, log=said.append))
        self.assertFalse(store.migrate_once(self.con, NOW + 60, log=said.append))   # once
        self.assertEqual(store.active(self.con, NOW + 1, HOPE), [])
        z = store.active(self.con, NOW + 1, MINT)
        self.assertEqual([(x["zone_type"], x["expires_at"]) for x in z], [("custom", NOW + 2 * 3600)])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM arm_log WHERE what='seed uklonjen'").fetchone()[0], 3)
        self.assertEqual(len(said), 1)
        # a pass and the MCP tools never arm anything by themselves
        self.flag("shadow")
        job.pass_once(now=NOW + 120, fetch=lambda t: [], log=lambda s: None, flag="shadow")
        view.armed_zones(now=NOW + 120)
        self.assertEqual(store.active(self.con, NOW + 121, HOPE), [])


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
        # one range computation = one version (the same ranges.ts read twice: still version 1); window_h = span_h
        self.assertEqual(store.versions(self.con), {MINT: {"zone_version": 1, "computed_ts": NOW, "window_h": None}})
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
        for zt, lo, hi in (("dca", 100_000, 105_000), ("stop", 85_000, 85_000), ("top", 145_000, 155_000)):
            store.arm(HOPE, zt, lo, hi, kid="owner", now=NOW, con=self.con)
        store.kv_put(self.con, "range_why", {MINT2: "isključen: volumen zadnjeg sata pao ispod pola prosjeka 6 h"})
        self.con.commit()
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
        self.assertEqual(z["without_range"], {MINT2: "isključen: volumen zadnjeg sata pao ispod pola prosjeka 6 h"})
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


# ---------------------------------------------------------------------------------------------------------------------
def _league(path, rows):
    """league.db with trades rows (user, token, status, opened_ts)."""
    from league import store as lstore
    c = lstore.connect(path)
    for user, tok, status, ts in rows:
        c.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px) VALUES (?,?,?,?,?,?,?)",
                  (user, tok, tok[:4], ts, status, 50.0, 1e-4))
    c.commit()
    c.close()


class Eligibility(Base):
    """11.11. (Jure, zbirni ispravak F): range zones for tokens with an open range round, an entry-ready range or an
    open position on the REAL account (LEAGUE_USER), and only while rangedca has an active range for them; otherwise
    no zones and the reason in the log (once per status) and in get_hourly_brief."""

    def setUp(self):
        super().setUp()
        from league import store as lstore
        self.league = os.path.join(self.tmp.name, "league.db")
        p = mock.patch.object(lstore, "DB", self.league)
        p.start()
        self.addCleanup(p.stop)

    def save(self, tok, active=True, status="aktivan", why="", ts=NOW, span_h=9.5):
        from rangedca import data
        rc = data.connect()
        res = {"ts": ts, "status": status, "active": active, "why": why, "score": 0.8, "pos_pct": 40.0, "span_h": span_h,
               "zones": {"range_low_low": 60e-6, "range_low_top": 66e-6, "range_high_low": 95e-6, "range_high_top": 100e-6,
                         "range_low": 63e-6, "range_high": 97e-6,
                         "mc": {"range_low_low": 60_000, "range_low_top": 66_000, "range_high_low": 95_000,
                                "range_high_top": 100_000}},
               "metrics": {"price": 80e-6, "mcap": 80_000, "supply": 1e9}, "source": "signal"}
        data.save_range(rc, tok, res, {}, tok[:4])
        rc.commit()
        rc.close()

    def test_real_account_positions_only_and_only_with_an_active_range(self):
        from trade import settings as ts
        a, b, c, d = ("A" * 43), ("B" * 43), ("C" * 43), ("D" * 43)
        _league(self.league, [(ts.LEAGUE_USER, a, "open", NOW - 600), (ts.PAPER_USER, b, "open", NOW - 600),
                              (ts.LEAGUE_USER, b, "closed", NOW - 900), (ts.LEAGUE_USER, c, "open", NOW - 300),
                              (ts.LEAGUE_USER, d, "open", NOW - 200)])
        self.assertEqual(store.position_tokens(), {a, c, d})                  # the demo account is not the real one
        self.save(a)                                                           # active range
        self.save(b)                                                           # active, but only a demo position
        self.save(c, active=False, status="probijen gore", why="cijena iznad range_high_top × 1,15")
        logs = []
        with mock.patch.object(store, "_entry_ready", lambda now: set()):
            toks, _ = store.sync_range(self.con, NOW + 60, log=logs.append)
        self.assertEqual(toks, 1)
        z = {(m, zt) for m, zt in self.con.execute("SELECT mint, zone_type FROM armed_zones WHERE source='range'")}
        self.assertEqual({m for m, _ in z}, {a})
        self.assertEqual({zt for _, zt in z}, {"bottom", "dca", "top", "stop"})
        note = self.con.execute("SELECT note FROM armed_zones WHERE mint=? AND zone_type='top'", (a,)).fetchone()[0]
        self.assertIn("pozicija na pravom računu", note)
        self.assertEqual(store.versions(self.con)[a], {"zone_version": 1, "computed_ts": NOW, "window_h": 9.5})
        why = store.kv_get(self.con, "range_why")
        self.assertEqual(set(why), {c, d})                                     # b is no reason at all: not logged
        self.assertEqual(why[c], "probijen gore: cijena iznad range_high_top × 1,15")
        self.assertIn("nema izračun raspona", why[d])
        self.assertEqual(len(logs), 2)
        # the same reasons (a number in them may change) are not logged again; a new range computation = a new version
        self.save(a, ts=NOW + 300, span_h=9.6)
        with mock.patch.object(store, "_entry_ready", lambda now: set()):
            store.sync_range(self.con, NOW + 330, log=logs.append)
        self.assertEqual(len(logs), 2)
        self.assertEqual(store.versions(self.con)[a], {"zone_version": 2, "computed_ts": NOW + 300, "window_h": 9.6})
        # the range of a goes inactive: its zones expire at once and why is logged
        self.save(a, active=False, status="isključen", why="volumen zadnjeg sata pao ispod pola prosjeka 6 h", ts=NOW + 600)
        with mock.patch.object(store, "_entry_ready", lambda now: set()):
            store.sync_range(self.con, NOW + 630, log=logs.append)
        self.assertEqual(store.active(self.con, NOW + 631, source="range"), [])
        self.assertEqual(len(logs), 3)
        self.assertIn("isključen: volumen zadnjeg sata", logs[-1])
        self.assertIn("isključen", view.brief_part(NOW + 640)["without_range"][a])

    def test_open_round_and_entry_ready_still_count(self):
        a, b = "A" * 43, "B" * 43
        self.save(a)
        self.save(b)
        with mock.patch.object(store, "_entry_ready", lambda now: {b}), \
                mock.patch.object(store, "_open_lot1_mc", lambda: {a: 64_000}):
            toks, _ = store.sync_range(self.con, NOW + 60, log=lambda s: None)
        self.assertEqual(toks, 2)
        notes = dict(self.con.execute("SELECT mint, note FROM armed_zones WHERE zone_type='bottom'").fetchall())
        self.assertIn("otvorena runda", notes[a])
        self.assertIn("entry_ready", notes[b])

    def test_the_signal_pass_follows_the_real_accounts_tokens_first(self):
        """rangedca's signal pass (data.candidates) takes the Autopilot accounts' open tokens (autopilot_tokens, at most
        15); the real account's come first, so the demo account's newer ones never push them out."""
        from rangedca import data
        from trade import settings as ts
        demo = [(ts.PAPER_USER, f"P{i:02d}" + "1" * 40, "open", NOW - i) for i in range(20)]
        _league(self.league, demo + [(ts.LEAGUE_USER, HOPE, "open", NOW - 86400)])
        got = data.autopilot_tokens()
        self.assertEqual((len(got), got[0]), (15, HOPE))
        rc = data.connect()
        self.addCleanup(rc.close)
        self.assertIn(HOPE, data.candidates(rc, NOW))


# ---------------------------------------------------------------------------------------------------------------------
class HopeFixture(Base):
    """HOPE's zones from range.db snapshots of the stored 10.11. fixture (tests/fixtures/range_hope_20261110.json.gz:
    GeckoTerminal minutes 10:01-21:18 UTC = 11:01-22:18 CET, supply 1e9). Each minute becomes one range.db snapshot
    the moment it would have been taken (price = close, MC, the 5-minute and 1-hour volume from the minutes; liquidity
    45k is assumed: the fixture has none). HOPE is the owner's position on the real account and nothing else (no open
    round, no seed, no arming). rangedca's own signal pass (run_range.once, every minute; ranges every ~5 min) and the
    zonewatch pass (every 30 s) run side by side from 15:55 to 21:18:30 UTC. What the range engine says, zonewatch
    watches: zones exactly while HOPE's range is active (16:06-17:2x UTC, bottom ~51-56k, top ~89-96k, a new
    zone_version every computation), none afterwards (excluded for falling volume, then too little volume), with the
    reason logged once per status; alarms carry zone_version, computed_ts and window_h."""

    def setUp(self):
        super().setUp()
        import gzip
        from league import store as lstore
        from rangedca import data
        from trade import settings as ts
        with gzip.open(os.path.join(ROOT, "tests", "fixtures", "range_hope_20261110.json.gz"), "rt") as f:
            self.fx = json.load(f)
        self.assertEqual(self.fx["token"], HOPE)
        league = os.path.join(self.tmp.name, "league.db")
        p = mock.patch.object(lstore, "DB", league)
        p.start()
        self.addCleanup(p.stop)
        _league(league, [(ts.LEAGUE_USER, HOPE, "open", self.fx["candles"][0][0])])
        self.rc = data.connect()
        self.addCleanup(self.rc.close)
        self.rc.execute("INSERT INTO pools VALUES (?,?,?,?,?)", (HOPE, self.fx["pool"], "pumpswap", "HOPE",
                                                                 self.fx["candles"][0][0]))
        self.rc.commit()
        self.fed = 0

    def feed(self, t):
        """The fixture's minutes up to t as range.db snapshots (taken 20 s into the minute)."""
        cs, sup = self.fx["candles"], self.fx["supply"]
        while self.fed < len(cs) and cs[self.fed][0] + 20 <= t:
            i = self.fed
            ts_, _o, _h, _l, cl, _v = cs[i]
            v5 = sum(x[5] for x in cs[max(0, i - 4):i + 1])
            v60 = sum(x[5] for x in cs[max(0, i - 59):i + 1])
            self.rc.execute("INSERT INTO snaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (HOPE, ts_ + 20, cl, cl * sup, 45_000.0, v5, v60, None, None, None, None, None, None))
            self.fed += 1
        self.rc.commit()

    def test_zones_versions_and_alarms_follow_the_range_engine(self):
        import run_range
        from rangedca import data, rules
        self.flag("shadow")
        econ = estore.connect(os.environ["EVENTS_DB"])
        self.addCleanup(econ.close)
        modes = {"range_dca": "paper", "range_market": "off", "event_tokens": "off"}
        end = self.fx["candles"][-1][0] + 30                      # 21:18:30 UTC = 22:18:30 CET
        t0 = int(dt.datetime(2026, 11, 10, 15, 55, tzinfo=dt.timezone.utc).timestamp())
        logs, seen, zones_at, gt = [], [], {}, []
        op, c = Opener([200] * 50), Clock(t0)
        with mock.patch.object(run_range, "_mode", lambda name="range_dca": modes[name]):
            for t in range(t0, end + 1, 30):
                c.t = t
                self.feed(t)
                if t % 60 == 0:
                    run_range.once(now=t, log=lambda s: None, fetch=lambda toks: [],
                                   gt_fetch=lambda *a: gt.append(a) and None)   # GeckoTerminal says no (no network)
                job.pass_once(now=t, fetch=lambda toks: [], cfg=self.cfg(), opener=op, sleep=c.sleep, clock=c,
                              log=logs.append, rug_fn=lambda *a: "ok", uniq_fn=lambda *a: None, flag="shadow")
                r = (data.read_ranges() or {}).get(HOPE) or {}
                zs = {z["zone_type"]: (z["lo"], z["hi"]) for z in store.active(self.con, t, HOPE)}
                zones_at[t] = (r.get("status"), r.get("ts"), r.get("zones"), zs,
                               dict(store.versions(self.con).get(HOPE) or {}), r.get("span_h"),
                               (r.get("stop") or {}).get("mc"))
                seen.append(r.get("status"))
        self.assertLessEqual(len(gt), 3)   # rangedca asked for a seed while it had < 6 h; the range came from snapshots
        # nothing hand-armed, nothing seeded: every zone came from the range engine
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM armed_zones WHERE source != 'range'").fetchone()[0], 0)
        active = [t for t, (st, *_r) in zones_at.items() if st == "aktivan"]
        self.assertTrue(active, set(seen))
        first, last = min(active), max(active)
        cet = dt.timezone(dt.timedelta(hours=1))
        self.assertEqual(dt.datetime.fromtimestamp(first, cet).strftime("%H"), "17")   # 6 h of data from 11:01 CET
        atr_stops = 0
        for t, (st, rts, rz, zs, ver, span, smc) in zones_at.items():
            if st == "aktivan" and t - rts <= 900:   # an active, fresh range: its zones, exactly
                mc = rz["mc"]
                self.assertEqual(zs["bottom"], (mc["range_low_low"], mc["range_low_top"]), t)
                self.assertEqual(zs["top"], (mc["range_high_low"], mc["range_high_top"]), t)
                # 11.11. (the owner's decision 1): the range's hard stop, the ATR stop (ranges.data "stop"); x 0.85
                # only for a range without it
                stop = smc if smc else round(mc["range_low_low"] * rules.RULES["stop_x"])
                atr_stops += int(bool(smc) and smc != round(mc["range_low_low"] * rules.RULES["stop_x"]))
                self.assertEqual(zs["stop"], (stop, stop), t)
                self.assertEqual(ver["computed_ts"], rts, t)              # computed_ts = when rangedca computed it
                self.assertEqual(ver["window_h"], span, t)                # window_h = the hours of data it spanned
                self.assertTrue(48_000 < mc["range_low_low"] < 56_000 and 80_000 < mc["range_high_low"] < 100_000, mc)
            elif st != "aktivan":                     # no active range: no zones (the owner's rule)
                self.assertEqual(zs, {}, (t, st))
        # one version per range computation of rangedca (every ~5 min while active), never per zonewatch pass
        vers = [zones_at[t][4]["zone_version"] for t in sorted(zones_at) if zones_at[t][4]]
        self.assertEqual(vers, sorted(vers))
        n_comp = len({zones_at[t][1] for t in active})
        self.assertEqual(max(vers), n_comp)
        self.assertGreaterEqual(n_comp, 10)
        self.assertTrue(6.0 <= zones_at[first][4]["window_h"] <= 6.2, zones_at[first][4])   # detect needs 6 h
        # at the end of the fixture (22:18 CET): the range is excluded / too thin, so HOPE has no zones, and why
        self.assertGreater(atr_stops, 0)
        st_end, _ts, _z, zs_end, _v, _s, _sm = zones_at[end]
        self.assertNotEqual(st_end, "aktivan")
        self.assertEqual(zs_end, {})
        why = view.brief_part(end)["without_range"]
        self.assertTrue(why[HOPE].startswith(st_end), why)
        said = [x.split("bez zona: ")[1].split(":")[0] for x in logs if "bez zona" in x]
        self.assertTrue(all(a != b for a, b in zip(said, said[1:])), said)   # once per status change, never repeated
        self.assertIn("isključen", said)
        self.assertLessEqual(len(said), 6)
        # the alarms (all of them range zones of HOPE) carry the range's version
        rows = self.con.execute("SELECT event, zone_type, ts, payload FROM alerts WHERE event != 'test' ORDER BY ts, id"
                                ).fetchall()
        self.assertTrue(rows)
        pv = []
        for ev, zt, ts_, pl in rows:
            p = json.loads(pl)
            self.assertEqual((p["mint"], p["source"]), (HOPE, "range"))
            self.assertTrue(first <= ts_ <= last + 60, ts_)               # only while the range is active
            for k in notify.RANGE_FIELDS:
                self.assertIsNotNone(p[k], (k, p))
            self.assertLessEqual(p["computed_ts"], ts_)
            self.assertGreaterEqual(p["window_h"], 6.0)
            pv.append(p["zone_version"])
        self.assertEqual(pv, sorted(pv))
        self.assertIn(("top_hit", "top"), [(e, z) for e, z, *_ in rows])
        # 11.11. (Jure): HOPE is held on the real account, so rangedca switching its range off (18:25 CET: the last
        # hour's volume under half of the 6 h average) is ONE range_off alarm with that reason
        off = [json.loads(pl) for ev, _zt, _ts, pl in rows if ev == "range_off"]
        self.assertEqual([(p["reason_key"], p["range_status"]) for p in off], [("weak_volume", "isključen")])
        self.assertEqual(off[0]["position"]["account"], settings.LEAGUE_USER)
        if os.environ.get("ZW_DEBUG"):
            for ev, zt, ts_, pl in rows:
                q = json.loads(pl)
                print(dt.datetime.fromtimestamp(ts_, cet).strftime("%H:%M:%S"), ev, zt, q["zone_lo"], q["zone_hi"],
                      q["mcap"], q["zone_version"], q["computed_ts"], q["window_h"], q["direction"])
        estore.flush(os.environ["EVENTS_DB"])
        self.assertEqual(econ.execute("SELECT COUNT(*) FROM events WHERE type='zone_alert'").fetchone()[0], len(rows) + 1)


if __name__ == "__main__":
    unittest.main()
