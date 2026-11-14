"""The Autopilot chart's history on demand (14.11. 17:01, owner: "Graf ne prikazuje dobro": YoungBull on 1h showed one
candle in the middle and a fragment cut at the left edge; ui/apgraf.py, ui/apterm.candles_data, ui/static/ap/ap.js).

A thin stored series asks for ONE GeckoTerminal request (queued, never in the request thread), throttled per token and
kind, capped per day in range.db kv graf_day, paced per minute and counted for the CoinGecko job "graf"; the candles
it stores (range.db gt_candles / gt_hours) are served on the next read and reused by the range job; a token with
enough data never asks; the JSON says why the chart is short (fill.note, young.note). The browser part: a Playwright
run of the real ap.js at 390 px (tests/graf_playwright.js) with 2 candles on 1h, a series that grows on the left after
the history arrives, and a young token that shows 5m for itself only. No network: the fetchers are fakes and the
browser gets the page from a local server, every other address is refused.

    python3 -m unittest tests.test_graf_povijest_offline
"""
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy  # noqa: E402
from tests.test_apterm_offline import Env  # noqa: E402
from ui import apgraf, apterm, pravitrade  # noqa: E402

H0 = (int(time.time()) // 3600 - 2) * 3600   # an hour boundary in the past
NOW = H0 + 61 * 60                             # 61 minutes after it (the owner's report: 16:00 -> 17:01)
YB = "YBuuu11111111111111111111111111111111111pump"     # a young token (YoungBull): its pair was created at H0
OLD = "Star111111111111111111111111111111111111pump"      # 20 h of our own minute snapshots
OLD7 = "Tjed111111111111111111111111111111111111pump"     # 3 days old, we hold only its last 2 h
POOL = "Poo1111111111111111111111111111111111111111"
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


def row(mcap, born, pair=POOL):
    return {"price": mcap / 1e9, "mcap": mcap, "liq": 22_400.0, "vol_h1": 336_000.0, "ch_m5": 3.5, "ch_h1": 129.0,
            "ch_h24": 129.0, "w": {"m5": {"buys": 40, "sells": 20}}, "symbol": "YB", "created_ms": born * 1000,
            "pair": pair}


def minutes(t0, t1, px=80_200 / 1e9):
    """GeckoTerminal-like minute candles [t0, t1) rising from px."""
    out, p = [], px
    for t in range(t0, t1, 60):
        q = p * 1.002
        out.append((t, p, q * 1.001, p * 0.999, q, 1500.0))
        p = q
    return out


class Graf(Env):
    def setUp(self):
        super().setUp()
        self.rdb = os.path.join(self.tmp.name, "range.db")
        env = mock.patch.dict(os.environ, {"RANGE_DB": self.rdb, "RANGE_HYPE_DB": os.path.join(self.tmp.name, "h.db"),
                                           "MINUTE_DB": os.path.join(self.tmp.name, "minute.db")})
        env.start()
        self.addCleanup(env.stop)
        from kol import store as kstore
        from rangedca import data as rdata
        self.rdata = rdata
        rdata.connect(self.rdb).close()
        self.calls = []
        self.hours_rows = []
        for p in (mock.patch.object(kstore, "DB", os.path.join(self.tmp.name, "kol.db")),
                  mock.patch.object(apgraf, "MANUAL", True),
                  mock.patch.object(apgraf, "_cooling", lambda: 0.0),
                  mock.patch.object(apgraf, "POOL_LOOKUP", self._no_lookup),
                  mock.patch.object(apgraf, "FETCH", {"m1": self._m1, "h1": self._h1})):
            p.start()
            self.addCleanup(p.stop)
        apgraf.reset()
        self.addCleanup(apgraf.reset)
        self.put_live({YB: row(92_300.0, H0), OLD: row(400_000.0, NOW - 20 * 3600), OLD7: row(250_000.0, NOW - 3 * 86400)})

    def put_live(self, rows):
        with pravitrade._LOCK:
            pravitrade._LIVE_CACHE[tuple(sorted(rows))] = (NOW, rows)

    def _no_lookup(self, mint):
        raise AssertionError("the pool came from the live row, not from another request")

    def _m1(self, pool, start, end):
        from event_calendar import http
        self.calls.append(("m1", pool, start, end, http.cg_job()))
        born = H0 if pool == POOL else start
        return minutes(max(start, born), end)

    def _h1(self, pool, start, end):
        from event_calendar import http
        self.calls.append(("h1", pool, start, end, http.cg_job()))
        return self.hours_rows

    def snaps(self, tok, t0, t1, mcap=92_000.0):
        con = self.rdata.connect(self.rdb)
        con.executemany("INSERT INTO snaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(tok, t, mcap / 1e9, mcap, 22_000.0, 9000.0, 90_000.0, None, 10, 5, None, 100, 50)
                         for t in range(t0, t1, 60)])
        con.commit()
        con.close()

    def kv_day(self):
        con = self.rdata.connect(self.rdb)
        try:
            return self.rdata.day_used(con, apgraf.DAY_KEY, NOW)
        finally:
            con.close()

    def c(self, tok, tf, unit="mc"):
        apterm._CANDLES.clear()   # every read sees the database (the cache is 20 s)
        return apterm.candles_data("Jure", tok, tf, unit, now=NOW)


class Need(unittest.TestCase):
    def test_what_is_thin(self):
        now = NOW
        mins = minutes(now - 300, now)                        # 5 minutes of our snapshots
        bars = [{"time": t - t % 3600} for t, *_ in mins[:1]]
        self.assertEqual(apgraf.need(300, 24, now, [], []), ("m1", "prazno"))
        self.assertEqual(apgraf.need(3600, 168, now, [], []), ("h1", "prazno"))          # age unknown: hours
        self.assertEqual(apgraf.need(3600, 168, now, mins, bars, born=now - 3660), ("m1", "pocetak"))   # young: minutes
        self.assertEqual(apgraf.need(300, 24, now, mins, bars), ("m1", "pocetak"))         # older than 5 minutes
        self.assertEqual(apgraf.need(300, 24, now, mins, bars, born=now - 400), None)      # as old as its data
        full = minutes(now - 998 * 60, now)
        self.assertIsNone(apgraf.need(300, 24, now, full, [{"time": full[0][0]}]))         # one request's reach: enough
        self.assertIsNone(apgraf.need(60, 6, now, full, [{"time": full[0][0]}]))
        stale = minutes(now - 998 * 60, now - 3600)
        self.assertEqual(apgraf.need(300, 24, now, stale, [{"time": stale[0][0]}]), ("m1", "kraj"))   # nobody snapshots it

    def test_croatian_candle_count(self):
        self.assertEqual([apterm._svijeca(n) for n in (1, 2, 4, 5, 12, 21, 22)],
                         ["je 1 svijeća", "su 2 svijeće", "su 4 svijeće", "je 5 svijeća", "je 12 svijeća",
                          "je 21 svijeća", "su 22 svijeće"])


class Fill(Graf):
    def test_thin_series_asks_once_then_the_stored_candles_are_served(self):
        self.seed()
        self.snaps(YB, NOW - 300, NOW)                       # the bot started to watch it 5 minutes ago
        c = self.c(YB, "1h")
        self.assertEqual((c["fill"]["state"], c["fill"]["kind"], c["fill"]["why"]), ("dohvacam", "m1", "pocetak"))
        self.assertEqual(c["fill"]["note"], "Dohvaćam povijest (GeckoTerminal)…")
        self.assertIsNone(c["young"])                        # decided after the history, not before
        self.assertEqual(c["born"], H0)
        self.assertEqual([b["time"] for b in c["candles"]], [H0, H0 + 3600])   # as on his phone: 2, the first cut short
        self.assertEqual(self.calls, [])                     # never in the request thread
        self.c(YB, "1h")
        self.c(YB, "5m")                                     # the same kind for 5m: still one job
        self.assertEqual(list(apgraf._QUEUE), [(YB, "m1")])
        self.assertEqual(apgraf.drain(now=NOW), 1)
        self.assertEqual(self.calls, [("m1", POOL, NOW - 998 * 60, NOW, "graf")])   # the live row's pool, job "graf"
        self.assertEqual(self.kv_day(), 1)
        con = self.rdata.connect(self.rdb)
        n, pool, fetched = con.execute("SELECT n, pool, fetched FROM gt_candles WHERE token=?", (YB,)).fetchone()
        self.assertEqual((n, pool, fetched), (61, POOL, NOW))
        # the range job reuses it: its own seed of this token waits 24 h, as after its own
        self.assertIsNone(self.rdata.seed(con, YB, POOL, NOW + 60, fetch=lambda *a: self.fail("seeded again")))
        con.close()
        c = self.c(YB, "1h")                                 # the stored candles are served
        self.assertIsNone(c["fill"])
        self.assertEqual([b["time"] for b in c["candles"]], [H0, H0 + 3600])
        self.assertAlmostEqual(c["candles"][0]["open"], 80_200.0)
        self.assertEqual(c["first_ts"], H0)
        y = c["young"]                                       # 2 candles on 1h: why, and which TF shows more
        self.assertEqual((y["bars"], y["pick"], y["more"]), (2, "5m", ["1m", "5m"]))
        self.assertEqual(y["counts"], {"1m": 61, "5m": 13, "15m": 5})
        hm = apterm._hm(H0)
        self.assertEqual(y["note"], f"Token je mlad (prvi podaci {hm}): na 1h su 2 svijeće — 1m/5m pokazuju više")
        self.assertEqual((y["why"], y["bars_txt"]), (f"Token je mlad (prvi podaci {hm})", "na 1h su 2 svijeće"))
        c5 = self.c(YB, "5m")
        self.assertEqual((len(c5["candles"]), c5["young"], c5["fill"]), (13, None, None))
        json.dumps(c)                                        # the route sends it as JSON
        self.c(YB, "1h")
        self.assertEqual(apgraf.drain(now=NOW), 0)           # nothing asked again
        self.assertEqual(len(self.calls), 1)

    def test_a_token_with_enough_data_never_asks(self):
        self.snaps(OLD, NOW - 20 * 3600 + 60, NOW)           # every minute since its pair was created
        for tf in apterm.TFS:
            c = self.c(OLD, tf)
            self.assertIsNone(c["fill"], tf)
            self.assertIsNone(c["young"], tf)
        self.assertEqual((apgraf._QUEUE, self.calls, self.kv_day()), ({}, [], 0))

    def test_the_day_cap_the_token_gap_and_the_minute_pace(self):
        toks = [f"Tok{ch}" + "1" * 36 + "pump" for ch in "ABCD"]
        self.put_live({t: row(100_000.0, NOW - 3600) for t in toks})
        for t in toks:
            self.snaps(t, NOW - 300, NOW)
        with mock.patch.object(apgraf, "GRAF_PER_MIN", 2):
            for t in toks[:3]:
                self.assertEqual(self.c(t, "5m")["fill"]["state"], "dohvacam")
            self.assertEqual(apgraf.drain(now=NOW), 2)       # two a minute; the third waits in the queue
            self.assertEqual(len(apgraf._QUEUE), 1)
            self.assertGreater(apgraf.step(now=NOW), 0)
            apgraf._SENT.clear()                             # a minute later
            self.assertEqual(apgraf.drain(now=NOW), 1)
        self.assertEqual(self.kv_day(), 3)
        with mock.patch.object(apgraf, "GRAF_DAY", 3):
            c = self.c(toks[3], "5m")
            self.assertEqual(c["fill"]["state"], "strop")    # today's cap: no job, the note says why
            self.assertIn("strop povijesti grafa", c["fill"]["note"])
            self.assertEqual(apgraf._QUEUE, {})
        # a token filled at NOW: a stale end is topped up only after 30 min, and only while it trades
        self.assertEqual(apgraf.request(toks[0], "m1", "kraj", NOW + 29 * 60), "nedavno")
        self.assertEqual(apgraf.request(toks[0], "m1", "kraj", NOW + 31 * 60), "dohvacam")
        self.assertEqual(apgraf.request(toks[1], "m1", "pocetak", NOW + 31 * 60), "nedavno")   # GT gave what it has: 6 h
        self.assertEqual(apgraf.request(toks[1], "m1", "pocetak", NOW + 6 * 3600 + 1), "dohvacam")
        self.assertEqual(self.kv_day(), 3)                   # asking costs nothing; only a sent request counts

    def test_errors_a_busy_geckoterminal_and_the_switch(self):
        self.snaps(YB, NOW - 300, NOW)
        with mock.patch.object(apgraf, "_cooling", lambda: 12.0):
            self.assertEqual(self.c(YB, "5m")["fill"]["state"], "ceka")
        self.assertEqual(apgraf._QUEUE, {})

        def boom(*a):
            raise OSError("429")
        with mock.patch.dict(apgraf.FETCH, {"m1": boom}):
            self.assertEqual(self.c(YB, "5m")["fill"]["state"], "dohvacam")
            apgraf.drain(now=NOW)
        c = self.c(YB, "5m")
        self.assertEqual(c["fill"]["state"], "greska")
        self.assertIn("novi pokušaj za 30 min", c["fill"]["note"])
        self.assertEqual(apgraf.request(YB, "m1", "pocetak", NOW + 31 * 60), "dohvacam")
        apgraf.reset()

        def gone(*a):
            import urllib.error
            raise urllib.error.HTTPError("https://x", 404, "Not Found", None, None)
        with mock.patch.dict(apgraf.FETCH, {"m1": gone}):
            self.c(YB, "5m")
            apgraf.drain(now=NOW)
        c = self.c(YB, "5m")                                 # GeckoTerminal does not know the pool: 6 h, not 30 min
        self.assertEqual(c["fill"]["state"], "nema_poola")
        self.assertIn("ne poznaje pool", c["fill"]["note"])
        self.assertEqual(apgraf.request(YB, "m1", "pocetak", NOW + 31 * 60), "nema_poola")
        apgraf.reset()
        with mock.patch.object(apgraf, "MANUAL", False):     # no background thread (tests, AP_BG_REFRESH=0): off
            self.assertEqual(self.c(YB, "5m")["fill"]["state"], "iskljuceno")
            self.assertEqual(self.c(YB, "5m")["fill"]["note"], "")
        with mock.patch.object(apgraf, "ENABLED", False):
            self.assertEqual(apgraf.request(YB, "m1", "pocetak", NOW, bg=True), "iskljuceno")
        self.assertEqual(self.kv_day(), 2)                   # the two requests that were sent

    def test_the_worker_thread_never_blocks_the_request(self):
        self.snaps(YB, NOW - 300, NOW)
        gate, stored = threading.Event(), []

        def slow(pool, start, end):
            gate.wait(10)
            return minutes(H0, NOW)
        apgraf.on_store(stored.append)
        self.addCleanup(apgraf._HOOKS.remove, stored.append)
        now = time.time()
        with mock.patch.object(apgraf, "MANUAL", False), mock.patch.dict(apgraf.FETCH, {"m1": slow}):
            t0 = time.monotonic()
            self.assertEqual(apgraf.request(YB, "m1", "pocetak", now, hint=POOL, bg=True), "dohvacam")
            self.assertLess(time.monotonic() - t0, 0.5)      # the request thread only queues it
            deadline = time.monotonic() + 5
            while not apgraf._RUN and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(apgraf.request(YB, "m1", "pocetak", now, hint=POOL, bg=True), "dohvacam")   # running
            gate.set()
            while (YB, "m1") not in apgraf._DONE and time.monotonic() < deadline + 5:
                time.sleep(0.01)
        self.assertEqual(stored, [YB])                       # ui/apterm's cached series is dropped
        self.assertEqual(len(self.c(YB, "5m")["candles"]), 13)

    def test_hour_candles_for_the_1h_view_of_an_older_token(self):
        self.snaps(OLD7, NOW - 2 * 3600, NOW, mcap=250_000.0)
        t0 = NOW - NOW % 3600 - 71 * 3600
        self.hours_rows = [(t0 + i * 3600, 2e-4, 2.2e-4, 1.9e-4, 2.1e-4, 50_000.0) for i in range(72)]
        c = self.c(OLD7, "1h")
        self.assertEqual((c["fill"]["state"], c["fill"]["kind"]), ("dohvacam", "h1"))
        apgraf.drain(now=NOW)
        self.assertEqual([x[0] for x in self.calls], ["h1"])
        self.assertEqual(self.calls[0][2:], (NOW - 168 * 3600, NOW, "graf"))
        c = self.c(OLD7, "1h")
        self.assertIsNone(c["fill"])
        self.assertEqual(len(c["candles"]), 72)
        self.assertEqual(c["candles"][0]["time"], t0)
        self.assertAlmostEqual(c["candles"][0]["open"], 200_000.0, delta=1)   # MC: x the live supply (1e9)
        self.assertEqual(c["vol"][0], 50_000.0)
        self.assertAlmostEqual(c["candles"][-1]["close"], 250_000.0)   # the newest hour: our snapshots, fresher
        con = self.rdata.connect(self.rdb)
        self.assertIsNone(con.execute("SELECT 1 FROM gt_candles WHERE token=?", (OLD7,)).fetchone())   # minutes only
        self.assertEqual(con.execute("SELECT n FROM gt_hours WHERE token=?", (OLD7,)).fetchone()[0], 72)
        con.close()
        self.assertEqual(self.c(OLD7, "5m")["fill"]["kind"], "m1")   # the 5m view of the same token: minutes

    def test_merge_hours(self):
        bars = [{"time": 7200, "open": 1, "high": 1, "low": 1, "close": 1},
                {"time": 10800, "open": 2, "high": 2, "low": 2, "close": 2}]
        gt = [(3600, 5, 5, 5, 5, 10.0), (7200, 6, 6, 6, 6, 20.0), (10800, 7, 7, 7, 7, 30.0)]
        out, vols = apterm.merge_hours(bars, [1.0, 2.0], gt, mult=10)
        self.assertEqual([(b["time"], b["close"]) for b in out], [(3600, 50.0), (7200, 60.0), (10800, 2)])
        self.assertEqual(vols, [10.0, 20.0, 2.0])
        self.assertEqual(apterm.merge_hours(bars, [1.0, 2.0], []), (bars, [1.0, 2.0]))

    def test_the_cost_line_and_the_note_under_the_chart(self):
        self.snaps(YB, NOW - 300, NOW)
        self.c(YB, "5m")
        apgraf.drain(now=NOW)
        from usage import daily
        g = daily.graf(NOW)
        self.assertEqual(g, {"zahtjeva": 1, "strop": apgraf.GRAF_DAY})
        self.assertIn(f"graf povijest 1/{apgraf.GRAF_DAY} zahtjeva GeckoTerminalu", daily.line({"day": "x", "graf": g}))
        _, body = pravitrade.page({"m": YB}, "Jure")
        self.assertIn("id=apx-cnote", body)


class CgJob(unittest.TestCase):
    def test_one_thread_counts_for_its_own_job(self):
        from event_calendar import http
        base = http.cg_job()
        seen = []
        with http.cg_job_as("graf"):
            self.assertEqual(http.cg_job(), "graf")
            t = threading.Thread(target=lambda: seen.append(http.cg_job()))
            t.start()
            t.join()
        self.assertEqual(seen, [base])                       # the other threads keep the process's job
        self.assertEqual(http.cg_job(), base)


def _have_playwright():
    if not shutil.which("node"):
        return False
    try:
        r = subprocess.run(["node", "-e", "const {chromium}=require('playwright');"
                            "process.exit(require('fs').existsSync(chromium.executablePath())?0:1)"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class _Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/pravi-trade":
            return self._out(200, self.server.page.encode(), "text/html; charset=utf-8")
        if path.startswith("/pravi-trade/static/"):
            a = apterm.static_asset(path[len("/pravi-trade/static/"):])
            if a:
                return self._out(200, a[0] if isinstance(a[0], bytes) else a[0].encode(), a[2] + "; charset=utf-8")
        return self._out(404, b"", "text/plain")

    def _out(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(_have_playwright(), "node + playwright + chromium")
class Browser(Graf):
    """The real ap.js at 390 px: every candle whole after each read (pixels of the chart's canvas), a young token
    on 5m for itself only. Screenshots go to GRAF_SHOTS (default: a temporary folder)."""

    def test_candles_whole_at_390_px(self):
        self.seed()
        self.put_live({YB: row(92_300.0, H0)})
        from ui.html import page as layout
        html = layout(*pravitrade.page({"m": YB}, "Jure"), "/pravi-trade")
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Quiet)
        srv.daemon_threads = True
        srv.page = html
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        out = os.environ.get("GRAF_SHOTS") or self.tmp.name
        js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graf_playwright.js")
        r = subprocess.run(["node", js, f"http://127.0.0.1:{srv.server_address[1]}", YB, out, str(H0)],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:] + r.stdout[-2000:])
        rep = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(rep["errors"], [])
        two = rep["dvije"]                                   # 2 candles on 1h, both whole, as candles
        self.assertEqual(two["runs"], 2, two)
        self.assertTrue(two["whole"], two)
        self.assertLessEqual(max(two["widths"]), 30, two)    # not one 111-px block per candle (fitContent of 1-2 bars)
        grow = rep["rast"]                                   # the history arrives: 3 candles, the new one on the left
        self.assertEqual(grow["tfs"][:2], ["1h", "1h"])
        self.assertEqual(grow["runs"], 3, grow)
        self.assertTrue(grow["whole"], grow)
        self.assertGreaterEqual(min(grow["first"], two["first"]), 4, grow)   # room at the left edge, nothing cut
        self.assertIn("Dohvaćam povijest", grow["note_first"])
        young = rep["mlad"]                                  # a young token: 5m for itself, the saved 1h stays
        self.assertEqual(young["tfs"][:2], ["1h", "5m"])
        self.assertEqual((young["on"], young["saved"]), ("5m", "1h"))
        self.assertIn("zato prikazujem 5m", young["note"])
        self.assertEqual(young["runs"], 13, young)
        self.assertTrue(young["whole"], young)
        self.assertGreaterEqual(young["first"], 4, young)                  # half a candle of room at both edges
        self.assertLessEqual(young["last"], young["pane"] - 4, young)


if __name__ == "__main__":
    unittest.main()
