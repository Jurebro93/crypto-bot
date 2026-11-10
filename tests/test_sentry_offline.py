"""Errors to Sentry without a new package (ops/sentry.py, 10.11.): DSN parsing, the envelope on the wire, what an event
may and may not contain (no local variables, no paths outside the repository, no host name), the scrubber on
realistic strings, the limits (30 a minute, the same error once in 5 min and then hourly, shared with child
processes), the bounded queue, the silent no-op without SENTRY_DSN, hooks that pass on to the previous ones, and the
guarded init block in every long-running entry point. No network: the POST is replaced, or goes to 127.0.0.1."""
import argparse
import ast
import base64
import contextlib
import datetime as dt
import email.message
import io
import json
import os
import random
import re
import socket
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import sentry  # noqa: E402

REAL_POST = sentry._post
KEY = "0123456789abcdef0123456789abcdef"
HOST = "o4500000000000000.ingest.de.sentry.io"
DSN = f"https://{KEY}@{HOST}/4500000000000001"
ENTRY = {"run_ui.py": "ui", "run_trade.py": "trade", "run_sched.py": "sched", "run_kol.py": "kol", "run_tg.py": "tg",
         "run_report.py": "report", "run_paper.py": "paper", "run_watch.py": "watch", "run_live.py": "live"}

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
HEX = "0123456789abcdef"
URLSAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"


def fake(n, alphabet=B58, seed=7):
    """A made-up secret of n characters, the same on every run. Built here and not written out, so that nothing in
    this file looks like a real key to a secret scanner; none of these ever existed."""
    rnd = random.Random(seed)
    return "".join(rnd.choice(alphabet) for _ in range(n))


HELIUS = "-".join(fake(n, HEX, seed=n) for n in (8, 4, 4, 4, 12))            # the shape of a Helius API key (UUID)
WALLET = fake(44, seed=3)                                                      # the shape of a Solana address
_RND = random.Random(2)   # one generator: a new Random(2) per byte gave 64 equal bytes, a "key" that was no key at all
KEY_BYTES = [_RND.randrange(256) for _ in range(64)]                            # a Solana keypair as 64 bytes
PRIVATE_KEY = fake(88, seed=5)                                                 # ... and as Phantom exports it (base58)
JWT = "eyJ" + fake(17, URLSAFE, 1) + "." + "eyJ" + fake(40, URLSAFE, 2) + "." + fake(43, URLSAFE, 3)
TG_BOT = "bot" + "123456789" + ":" + fake(35, URLSAFE, 4)                      # Telegram bot token in an API URL


def boom(kind=ValueError, text="pukao sam"):
    lozinka = "LOKALNA-TAJNA-koja-ne-smije-van"   # noqa: F841 - a local variable: must never be in an event
    raise kind(text)


def caught(kind=ValueError, text="pukao sam"):
    """An exception with a real traceback (caught -> boom), always from the same two lines of this file."""
    try:
        boom(kind, text)
    except Exception as e:  # noqa: BLE001
        return e


def err(i):
    """A different error each time: the type is part of what makes two errors "the same"."""
    return caught(type(f"Greska{i}", (Exception,), {}))


class Base(unittest.TestCase):
    """Reporting switched on with a made-up DSN; every POST lands in self.sent instead of on the network."""
    INIT = "proba"

    def setUp(self):
        sentry._reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent = []
        self.post = mock.MagicMock(side_effect=lambda url, headers, body: self.sent.append((url, headers, body)))
        env = mock.patch.dict(os.environ, {"SENTRY_DSN": DSN})
        for p in (mock.patch.object(sentry, "STAMP_DIR", os.path.join(self.tmp.name, "stamps")),
                  mock.patch.object(sentry, "_post", self.post), env):
            p.start()
            self.addCleanup(p.stop)
        for name in ("RENDER", "RENDER_GIT_COMMIT"):
            os.environ.pop(name, None)   # put back by the patch.dict above
        self.addCleanup(self._off)       # registered last = runs first, while the patches still hold
        if self.INIT:
            self.assertTrue(sentry.init(self.INIT))

    def _off(self):
        sentry.flush(5)
        sentry._reset()

    def events(self):
        self.assertTrue(sentry.flush(5))
        return [json.loads(body.split(b"\n")[2]) for _, _, body in self.sent]


class DsnAndWire(unittest.TestCase):
    def test_dsn_forms(self):
        self.assertEqual(sentry.parse_dsn(DSN), {"key": KEY, "host": HOST, "project": "4500000000000001",
                                                 "url": f"https://{HOST}/api/4500000000000001/envelope/"})
        # the old form with a secret, a port, a path before the project id (self-hosted), spaces around it
        old = sentry.parse_dsn("https://javni:tajni@sentry.example.com:9000/prefiks/7")
        self.assertEqual((old["key"], old["url"]), ("javni", "https://sentry.example.com:9000/prefiks/api/7/envelope/"))
        self.assertNotIn("tajni", json.dumps(old))   # the secret half is never kept
        self.assertEqual(sentry.parse_dsn("  http://k@127.0.0.1:8000/1/ \n")["url"], "http://127.0.0.1:8000/api/1/envelope/")

    def test_not_a_dsn(self):
        for bad in ("", None, "   ", "sentry", f"https://{HOST}/42", f"https://@{HOST}/42", f"https://{KEY}@{HOST}",
                    f"https://{KEY}@{HOST}/", f"https://{KEY}@{HOST}/abc", f"ftp://{KEY}@{HOST}/42", f"https://{KEY}@/42",
                    f"{KEY}@{HOST}/42"):
            self.assertIsNone(sentry.parse_dsn(bad), bad)

    def test_auth_header(self):
        self.assertEqual(sentry.auth_header(sentry.parse_dsn(DSN)),
                         f"Sentry sentry_version=7, sentry_key={KEY}, sentry_client=memesonar-stdlib/1")

    def test_envelope_is_three_json_lines_and_says_how_long_the_payload_is(self):
        ev = {"event_id": "a" * 32, "timestamp": 1.5, "message": {"formatted": "čćžšđ\nredak dva \u2028 kraj"}}
        now = dt.datetime(2026, 11, 10, 1, 2, 3, tzinfo=dt.timezone.utc).timestamp() + 0.25
        raw = sentry.envelope(ev, now=now)
        self.assertTrue(raw.endswith(b"\n"))
        raw.decode("ascii")   # the payload is escaped JSON: its length in bytes is its length in characters
        lines = raw[:-1].split(b"\n")
        self.assertEqual(len(lines), 3)   # a line break inside the payload would have made a fourth
        head, item, body = (json.loads(x) for x in lines)
        self.assertEqual(head, {"event_id": "a" * 32, "sent_at": "2026-11-10T01:02:03.250Z"})
        self.assertEqual(item, {"type": "event", "length": len(lines[2]), "content_type": "application/json"})
        self.assertEqual(body, ev)


class EventContent(Base):
    def test_fields(self):
        with mock.patch.dict(os.environ, {"RENDER": "true", "RENDER_GIT_COMMIT": "df3aabb0c1d2e3f4"}):
            self.assertTrue(sentry.capture(caught(), where="proba.mjesto"))
        ev, = self.events()
        self.assertRegex(ev["event_id"], r"^[0-9a-f]{32}$")
        self.assertAlmostEqual(ev["timestamp"], time.time(), delta=60)
        self.assertEqual({k: v for k, v in ev.items() if k not in ("event_id", "timestamp", "exception")},
                         {"platform": "python", "level": "error", "logger": "memesonar.proba", "server_name": "render",
                          "release": "df3aabb0c1d2e3f4", "environment": "production",
                          "tags": {"component": "proba", "where": "proba.mjesto"}})

    def test_outside_render_no_release_and_a_local_environment(self):
        sentry.capture(caught())
        ev, = self.events()
        self.assertNotIn("release", ev)
        self.assertEqual((ev["environment"], ev["tags"]), ("local", {"component": "proba"}))

    def test_stack_is_file_function_line_oldest_call_first(self):
        e = caught(text="x")
        sentry.capture(e)
        ev, = self.events()
        x, = ev["exception"]["values"]
        self.assertEqual((x["type"], x["value"], x["mechanism"]), ("ValueError", "x", {"type": "generic", "handled": True}))
        self.assertNotIn("module", x)   # a builtin
        frames = x["stacktrace"]["frames"]
        for f in frames:
            self.assertEqual(set(f), {"filename", "function", "lineno", "in_app"})
        self.assertEqual([f["function"] for f in frames], ["caught", "boom"])
        self.assertEqual(frames[-1], {"filename": "tests/test_sentry_offline.py", "function": "boom",
                                      "lineno": traceback.extract_tb(e.__traceback__)[-1].lineno, "in_app": True})

    def test_no_local_variables_no_paths_no_host_no_environment(self):
        with mock.patch.dict(os.environ, {"HELIUS_API_KEY": "kljuc-iz-okoline-123456"}):
            sentry.capture(caught())
            self.assertTrue(sentry.flush(5))
        raw = self.sent[0][2].decode("ascii")
        for leak in ("LOKALNA-TAJNA", "lozinka", "kljuc-iz-okoline", ROOT, os.path.expanduser("~") + "/",
                     socket.gethostname(), '"vars"', "context_line", "pre_context", '"request"', '"user"', '"modules"'):
            self.assertNotIn(leak, raw)

    def test_frames_outside_the_repository_are_short_and_not_ours(self):
        try:
            json.loads("{nije json")
        except ValueError as e:
            sentry.capture(e)
        ev, = self.events()
        x = ev["exception"]["values"][-1]
        self.assertEqual((x["type"], x["module"]), ("JSONDecodeError", "json.decoder"))
        frames = x["stacktrace"]["frames"]
        self.assertEqual((frames[0]["filename"], frames[0]["in_app"]), ("tests/test_sentry_offline.py", True))
        lib = [f for f in frames if not f["in_app"]]
        self.assertTrue(lib)
        for f in lib:
            self.assertRegex(f["filename"], r"^json/\w+\.py$")   # two last parts: no install path, no home directory

    def test_cause_first_reported_error_last(self):
        try:
            try:
                boom(KeyError, "outAmount")
            except KeyError as e:
                raise RuntimeError("kotacija nije stigla") from e
        except RuntimeError as e:
            sentry.capture(e)
        ev, = self.events()
        vals = ev["exception"]["values"]
        self.assertEqual([(v["type"], v["value"]) for v in vals], [("KeyError", "'outAmount'"), ("RuntimeError", "kotacija nije stigla")])
        self.assertEqual(["mechanism" in v for v in vals], [False, True])
        self.assertEqual(vals[0]["stacktrace"]["frames"][-1]["function"], "boom")

    def test_exception_text_is_scrubbed(self):
        sentry.capture(caught(RuntimeError, f"HTTP Error 401 for url: https://mainnet.helius-rpc.com/?api-key={HELIUS}"))
        self.assertTrue(sentry.flush(5))
        raw = self.sent[0][2].decode("ascii")
        self.assertNotIn(HELIUS, raw)
        self.assertIn("https://mainnet.helius-rpc.com/?[Filtered]", raw)

    def test_capture_takes_the_handled_exception_or_exc_info(self):
        try:
            boom()
        except ValueError:
            self.assertTrue(sentry.capture(where="bez argumenta"))
        try:
            boom(TypeError)
        except TypeError:
            self.assertTrue(sentry.capture(sys.exc_info()))
        evs = self.events()
        self.assertEqual([e["exception"]["values"][-1]["type"] for e in evs], ["ValueError", "TypeError"])
        self.assertEqual(evs[1]["exception"]["values"][-1]["stacktrace"]["frames"][-1]["function"], "boom")

    def test_levels(self):
        sentry.capture(err(1), level="warning")
        sentry.capture(err(2), level="nepostojeća")
        self.assertEqual([e["level"] for e in self.events()], ["warning", "error"])

    def test_capture_never_raises(self):
        class Los(Exception):
            def __str__(self):
                raise RuntimeError("ni poruku ne zna reći")

        self.assertFalse(sentry.capture())                    # nothing is being handled
        self.assertFalse(sentry.capture("nije iznimka"))
        self.assertFalse(sentry.capture(KeyboardInterrupt()))  # Ctrl+C and exits are not errors
        self.assertFalse(sentry.capture(SystemExit(1)))
        self.assertTrue(sentry.capture(Los()))                # no traceback, broken text: still one event
        ev, = self.events()
        x, = ev["exception"]["values"]
        self.assertEqual((x["type"], x["value"]), ("Los", "<tekst greške se ne može pročitati>"))
        self.assertNotIn("stacktrace", x)
        with mock.patch.object(sentry, "build_event", side_effect=RuntimeError("pokvaren")):
            self.assertFalse(sentry.capture(caught(TypeError)))
            self.assertFalse(sentry.message("x"))

    def test_message_event(self):
        self.assertTrue(sentry.message("dostupnost: 5 neuspjeha zaredom, api-key=abc123", level="info"))
        self.assertTrue(sentry.message("druga poruka"))
        self.assertFalse(sentry.message("dostupnost: 5 neuspjeha zaredom, api-key=abc123"))   # the same text within 5 min
        a, b = self.events()
        self.assertEqual((a["message"], a["level"]), ({"formatted": "dostupnost: 5 neuspjeha zaredom, api-key=[Filtered]"}, "info"))
        self.assertEqual((b["message"], b["level"]), ({"formatted": "druga poruka"}, "warning"))
        self.assertNotIn("exception", a)


class Scrub(unittest.TestCase):
    def gone(self, text, *secrets, keeps=()):
        out = sentry.scrub(text)
        for s in secrets:
            self.assertNotIn(s, out)
        for k in keeps:
            self.assertIn(k, out)
        return out

    def test_helius_rpc_url_with_api_key(self):
        out = self.gone(f"HTTP Error 401: Unauthorized for url: https://mainnet.helius-rpc.com/?api-key={HELIUS}", HELIUS)
        self.assertEqual(out, "HTTP Error 401: Unauthorized for url: https://mainnet.helius-rpc.com/?[Filtered]")
        self.gone(f"wss://pumpportal.fun/api/data?api-key={HELIUS} zatvoren", HELIUS, keeps=("pumpportal.fun/api/data", "zatvoren"))
        # the same key outside a URL, as urllib, a dict or a shell line would show it
        for form in (f"api-key={HELIUS}", f"apikey={HELIUS}&x=1", f"?key={HELIUS}", f"token={HELIUS}", f"{{'api_key': '{HELIUS}'}}",
                     f"HELIUS_API_KEY={HELIUS}", f"x-api-key: {HELIUS}", f"ključ {HELIUS} odbijen"):
            self.gone("zahtjev nije uspio: " + form, HELIUS, HELIUS[:13], keeps=("zahtjev nije uspio",))

    def test_short_values_after_key_like_names(self):
        for text, secret in (("GET /x?token=kratki1 nije uspio", "kratki1"), ("UI_PASSWORD=tajna123 odbijen", "tajna123"),
                             ("{'password': 'tajna123'}", "tajna123"), ("Authorization: Basic dTpw", "dTpw"),
                             ("api-key=abc123, pokušaj 2", "abc123"), ("lozinka: mojatajna", "mojatajna"),
                             ("secret=s3kr3t kraj", "s3kr3t"), ("X-Hook-Key: h00k", "h00k"), ("?key=k1&limit=5", "k1"),
                             ("poslano s Bearer kratki-token-1", "kratki-token-1"),
                             # 10.11.: a dict or a JSON answer printed into the text, with short values
                             ("{'token': 'abc123short', 'mint': 'x'}", "abc123short"),
                             ('odgovor {"access_token": "ya29.kratki", "expires_in": 3599}', "ya29.kratki"),
                             ("{'client_secret': 'tajna', 'n': 2}", "tajna"), ('{"session_id": "s-77"}', "s-77")):
            self.assertIn("[Filtered]", self.gone(text, secret))
        # ... and only there: the same words as plain text are not values to hide
        for text in ("token: BONK nije prošao", "KeyError: 'token'", "{'mint': 'x', 'n': 2}"):
            self.assertEqual(sentry.scrub(text), text)

    def test_wallet_address_in_a_url_keeps_the_call_readable(self):
        out = self.gone(f"HTTPError: https://api.helius.xyz/v0/addresses/{WALLET}/transactions?api-key={HELIUS}&limit=100",
                        WALLET, HELIUS, "limit=100")
        self.assertEqual(out, "HTTPError: https://api.helius.xyz/v0/addresses/[Filtered]/transactions?[Filtered]")
        self.gone(f"novčanik {WALLET} nema stanje", WALLET, WALLET[:12], keeps=("novčanik", "nema stanje"))

    def test_solana_private_key_in_every_shape(self):
        self.gone(f"ValueError: neispravan ključ {PRIVATE_KEY}", PRIVATE_KEY, PRIVATE_KEY[:16], PRIVATE_KEY[-16:],
                  keeps=("neispravan ključ",))
        as_list = "[" + ", ".join(str(b) for b in KEY_BYTES) + "]"
        self.gone(f"keypair mora imati 64 bajta: {as_list}", as_list, ", ".join(str(b) for b in KEY_BYTES[:5]))
        b64 = base64.b64encode(bytes(KEY_BYTES)).decode()
        self.assertTrue("/" in b64 and "+" in b64)   # the hard shape: it also looks like a file path
        self.gone(f"ne mogu dekodirati {b64}", b64, b64[:12], b64[-12:])
        hexa = bytes(KEY_BYTES).hex()
        self.gone(f"hex {hexa}", hexa, hexa[:20])

    def test_bearer_token_cookie_email_address_bot_token(self):
        out = self.gone(f"401 {{'Authorization': 'Bearer {JWT}', 'Accept': 'application/json'}}", JWT, JWT[:20], JWT[-20:])
        self.assertIn("'Accept': 'application/json'", out)
        self.gone(f"odgovor 403 na token {JWT}", JWT, JWT[:20])
        self.gone("loš zahtjev, Cookie: cb_s=Jure|1799999999|0a1b2c3d4e5f; cb_lang=hr", "Jure|1799999999", "cb_lang=hr")
        self.gone("sesija cb_s=Jure|1799999999|0a1b2c3d odbijena", "Jure|1799999999", keeps=("odbijena",))
        self.assertEqual(self.gone("550 primatelj netko.treci+proba@example.com odbijen", "netko.treci", "example.com"),
                         "550 primatelj [email] odbijen")
        self.assertEqual(sentry.scrub("veza s 203.0.113.77 prekinuta"), "veza s [ip] prekinuta")
        self.gone(f"https://api.telegram.org/{TG_BOT}/sendMessage -> 403", TG_BOT[13:], keeps=("api.telegram.org", "sendMessage"))
        self.gone("https://korisnik:lozinka123@example.com/x nije dostupan", "korisnik", "lozinka123", keeps=("example.com/x",))
        self.gone(f"sentry: {DSN}", KEY, keeps=(HOST,))

    def test_ordinary_error_text_survives(self):
        for text in ("database is locked", "'outAmount'", "HTTP Error 429: Too Many Requests", "list index out of range",
                     "[Errno 2] No such file or directory: '/var/data/output/report-2026-11-10.html'",
                     "no such column: follow_id", "UNIQUE constraint failed: positions.league_id",
                     "could not convert string to float: 'abc'", "signal star 412 s", "cmd_search trajao 2809 s",
                     "token BONK nije prošao: likvidnost 2,1 % MC-a", "name 'rows' is not defined",
                     "unsupported operand type(s) for +: 'NoneType' and 'float'",
                     "MC $28,400 ispod 30k (pravilo: ispod 30k se ne kupuje)", "https://api.dexscreener.com/latest/dex/search",
                     "/opt/render/project/src/trade/__pycache__/executor.cpython-313.pyc"):
            self.assertEqual(sentry.scrub(text), text)

    def test_long_and_odd_text(self):
        out = sentry.scrub("riječ " * 2000)
        self.assertEqual(len(out), sentry.MAX_TEXT + 1)
        self.assertTrue(out.endswith("…"))
        self.assertEqual((sentry.scrub(None), sentry.scrub(12)), ("None", "12"))
        half = sentry.scrub("pola znaka \ud800 kraj")   # a lone surrogate would make JSON that Sentry refuses
        self.assertNotIn("\ud800", half)
        self.assertIn("kraj", half)

    def test_stays_fast_on_hostile_text(self):
        t = time.perf_counter()
        for text in ("x" * 4000, "x-" * 2000, "key" * 1400, "a://" * 1000, "http://" * 600, "eyJ" * 1300, "a@" * 2000,
                     "[1," * 1300, "aB1/" * 1000, "cookie:" * 600, "1." * 2000):
            sentry.scrub(text)
        self.assertLess(time.perf_counter() - t, 2.0)   # measured ~40 ms for all of them; the check is for "never seconds"


class Limits(Base):
    def cap(self, exc, now):
        return sentry._capture(exc, "", "error", now=now)

    def test_at_most_thirty_events_a_minute(self):
        t0 = time.time()
        took = [self.cap(err(i), t0 + i) for i in range(sentry.PER_MINUTE + 5)]
        self.assertEqual(took, [True] * sentry.PER_MINUTE + [False] * 5)
        self.assertEqual(sentry.STATS["rate"], 5)
        self.assertEqual(len(self.events()), sentry.PER_MINUTE)
        # a minute after the first ones, room again for exactly as many as went out of the window
        self.assertEqual([self.cap(err(100 + i), t0 + 61) for i in range(3)], [True, True, False])

    def test_same_error_once_in_five_minutes_then_once_an_hour(self):
        t0 = time.time()
        self.assertTrue(self.cap(caught(), t0))
        self.assertFalse(self.cap(caught(), t0 + 1))
        self.assertFalse(self.cap(caught(), t0 + 299))
        self.assertTrue(self.cap(caught(), t0 + 300))        # 2nd report
        self.assertFalse(self.cap(caught(), t0 + 599))
        self.assertTrue(self.cap(caught(), t0 + 600))        # 3rd in a row: from here once an hour
        self.assertFalse(self.cap(caught(), t0 + 900))
        self.assertFalse(self.cap(caught(), t0 + 600 + 3599))
        self.assertTrue(self.cap(caught(), t0 + 600 + 3600))
        self.assertEqual(sentry.STATS["dup"], 5)
        # each report says how many equal errors were held back before it
        self.assertEqual([e.get("extra") for e in self.events()],
                         [None, {"suppressed_since_last_report": 2}, {"suppressed_since_last_report": 1},
                          {"suppressed_since_last_report": 2}])

    def test_an_error_that_went_quiet_is_reported_fast_again(self):
        t0 = time.time()
        for at in (0, 300, 600):
            self.assertTrue(self.cap(caught(), t0 + at))
        back = t0 + 600 + sentry.SAME_FORGET_S + 1
        self.assertTrue(self.cap(caught(), back))
        self.assertFalse(self.cap(caught(), back + 299))
        self.assertTrue(self.cap(caught(), back + 300))      # 5 minutes again, not an hour

    def test_same_type_from_another_place_is_another_error(self):
        def drugdje():
            raise ValueError("isti tip, drugo mjesto")

        try:
            drugdje()
        except ValueError as e:
            other = e
        self.assertTrue(sentry.capture(caught()))
        self.assertTrue(sentry.capture(other))
        self.assertFalse(sentry.capture(caught()))
        self.assertFalse(sentry.capture(other))

    def test_fingerprint_is_type_and_innermost_own_frame(self):
        ours = {"filename": "trade/executor.py", "function": "buy", "lineno": 310, "in_app": True}
        lib = {"filename": "sqlite3/dbapi2.py", "function": "execute", "lineno": 5, "in_app": False}
        self.assertEqual(sentry.fingerprint("OperationalError", [ours, lib]), ("OperationalError", "trade/executor.py", "buy", 310))
        self.assertEqual(sentry.fingerprint("OperationalError", [lib]), ("OperationalError", "sqlite3/dbapi2.py", "execute", 5))
        self.assertEqual(sentry.fingerprint("OperationalError", [], "run_trade.cmd_follow"), ("OperationalError", "run_trade.cmd_follow"))

    def test_child_processes_share_the_limit_through_a_stamp_file(self):
        t0 = time.time()
        self.assertTrue(self.cap(caught(), t0))
        name, = os.listdir(sentry.STAMP_DIR)
        self.assertRegex(name, r"^[0-9a-f]{20}$")   # a hash: nothing about the error can be read from the disk
        with sentry._lock:
            sentry._seen.clear()                    # "another process": no memory of the report, only the file
        self.assertFalse(self.cap(caught(), t0 + 60))
        self.assertTrue(self.cap(caught(), t0 + 300))
        self.assertEqual(len(os.listdir(sentry.STAMP_DIR)), 1)

    def test_limit_holds_without_a_writable_temp_directory(self):
        blocker = os.path.join(self.tmp.name, "datoteka")
        open(blocker, "w").close()
        with mock.patch.object(sentry, "STAMP_DIR", os.path.join(blocker, "stamps")):   # a folder cannot be made here
            self.assertTrue(sentry.capture(caught()))
            self.assertFalse(sentry.capture(caught()))

    def test_old_stamps_are_removed_at_start(self):
        os.makedirs(sentry.STAMP_DIR)
        old, fresh = (os.path.join(sentry.STAMP_DIR, n) for n in ("stari", "svjezi"))
        for p in (old, fresh):
            open(p, "w").close()
        os.utime(old, (time.time() - sentry.SAME_FORGET_S - 60,) * 2)
        sentry._stamp_prune(time.time())
        self.assertEqual(os.listdir(sentry.STAMP_DIR), ["svjezi"])


class QueueAndSending(Base):
    def test_post_goes_to_the_envelope_address_with_the_key_in_the_header(self):
        sentry.capture(caught(text="x"))
        self.assertTrue(sentry.flush(5))
        (url, headers, body), = self.sent
        self.assertEqual(url, f"https://{HOST}/api/4500000000000001/envelope/")
        self.assertEqual(headers, {"Content-Type": "application/x-sentry-envelope", "User-Agent": "memesonar-stdlib/1",
                                   "X-Sentry-Auth": f"Sentry sentry_version=7, sentry_key={KEY}, sentry_client=memesonar-stdlib/1"})
        head, item, payload = body.split(b"\n")[:3]
        self.assertEqual(json.loads(head)["event_id"], json.loads(payload)["event_id"])
        self.assertEqual(json.loads(item), {"type": "event", "length": len(payload), "content_type": "application/json"})
        self.assertEqual(sentry.STATS["sent"], 1)

    def test_one_post_short_timeout_no_redirects(self):
        seen = {}

        class Answer:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def fake_open(opener, req, data=None, timeout=None):
            seen.update(url=req.full_url, method=req.get_method(), data=req.data, timeout=timeout,
                        headers={k.lower(): v for k, v in req.header_items()},
                        handlers={type(h).__name__ for h in opener.handlers})
            return Answer()

        with mock.patch.object(urllib.request.OpenerDirector, "open", fake_open):
            REAL_POST("https://primjer.invalid/api/1/envelope/", {"X-Sentry-Auth": "Sentry x"}, b"abc")
        self.assertEqual((seen["url"], seen["method"], seen["data"], seen["timeout"]),
                         ("https://primjer.invalid/api/1/envelope/", "POST", b"abc", sentry.TIMEOUT_S))
        self.assertEqual(seen["headers"]["x-sentry-auth"], "Sentry x")
        self.assertIn("_NoRedirect", seen["handlers"])
        self.assertNotIn("HTTPRedirectHandler", seen["handlers"])
        self.assertIsNone(sentry._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://drugdje.invalid/"))
        self.assertLessEqual(sentry.TIMEOUT_S, 5)

    def test_full_queue_drops_and_never_waits(self):
        gate = threading.Event()
        self.post.side_effect = lambda *a: gate.wait(20)   # Sentry does not answer
        self.addCleanup(gate.set)
        with mock.patch.object(sentry, "PER_MINUTE", 10_000):
            t = time.perf_counter()
            took = [sentry.capture(err(i)) for i in range(sentry.QUEUE_MAX + 20)]
            spent = time.perf_counter() - t
        self.assertLess(spent, 2.0)
        # the queue holds QUEUE_MAX, plus the one the sender is stuck on
        self.assertIn(took.count(True), (sentry.QUEUE_MAX, sentry.QUEUE_MAX + 1))
        self.assertEqual(took.count(False), sentry.STATS["full"])
        self.assertFalse(sentry.flush(0.05))               # flush gives up, it does not hang
        gate.set()
        self.assertTrue(sentry.flush(5))
        self.assertEqual(self.post.call_count, took.count(True))

    def test_failed_send_is_one_line_an_hour_on_stderr_without_the_key(self):
        self.post.side_effect = urllib.error.URLError("nema mreže")
        with contextlib.redirect_stderr(io.StringIO()) as errs, contextlib.redirect_stdout(io.StringIO()) as out:
            for i in range(3):
                self.assertTrue(sentry.capture(err(i)))    # the caller is not told and does not care
            self.assertTrue(sentry.flush(5))
            first = errs.getvalue()
            sentry._send(sentry.build_event(text="x"), now=time.time() + sentry.FAIL_LOG_EVERY_S + 1)
        self.assertEqual(sentry.STATS["failed"], 4)
        self.assertEqual(first.count("\n"), 1)
        self.assertRegex(first, r"^sentry: slanje greške nije uspjelo \(URLError\)")
        self.assertEqual(errs.getvalue().count("\n"), 2)   # an hour later: one more line
        self.assertNotIn(KEY, errs.getvalue())
        self.assertNotIn(HOST, errs.getvalue())
        self.assertEqual(out.getvalue(), "")               # stdout of a page build child is the page itself

    def test_sentry_says_wait_and_nothing_is_queued_meanwhile(self):
        hdrs = email.message.Message()
        hdrs["Retry-After"] = "120"
        self.post.side_effect = urllib.error.HTTPError("https://x.invalid/", 429, "Too Many Requests", hdrs, None)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(sentry.capture(err(1)))
            self.assertTrue(sentry.flush(5))
        self.assertAlmostEqual(sentry._state["pause_until"] - time.time(), 120, delta=10)
        self.assertFalse(sentry.capture(err(2)))
        self.assertFalse(sentry.message("i poruka čeka"))
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(sentry._q.qsize(), 0)

    def test_wrong_key_asks_again_in_an_hour(self):
        self.post.side_effect = urllib.error.HTTPError("https://x.invalid/", 401, "Unauthorized", email.message.Message(), None)
        with contextlib.redirect_stderr(io.StringIO()) as errs:
            sentry.capture(err(1))
            self.assertTrue(sentry.flush(5))
        self.assertAlmostEqual(sentry._state["pause_until"] - time.time(), 3600, delta=10)
        self.assertIn("HTTP 401", errs.getvalue())

    def test_capture_does_not_wait_for_a_slow_sentry(self):
        gate = threading.Event()
        self.post.side_effect = lambda *a: gate.wait(20)
        self.addCleanup(gate.set)
        t = time.perf_counter()
        self.assertTrue(sentry.capture(err(1)))
        self.assertTrue(sentry.capture(err(2)))
        self.assertLess(time.perf_counter() - t, 1.0)
        gate.set()


class NoDsn(unittest.TestCase):
    def setUp(self):
        sentry._reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.post = mock.MagicMock()
        env = mock.patch.dict(os.environ)
        for p in (mock.patch.object(sentry, "STAMP_DIR", self.tmp.name), mock.patch.object(sentry, "_post", self.post), env):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("SENTRY_DSN", None)
        self.addCleanup(sentry._reset)
        self.hooks = (sys.excepthook, threading.excepthook, socketserver.BaseServer.handle_error)

    def unchanged(self):
        self.assertEqual((sys.excepthook, threading.excepthook, socketserver.BaseServer.handle_error), self.hooks)
        self.assertFalse(sentry.enabled())
        self.assertFalse(sentry._state["atexit"])
        self.assertEqual(sentry._q.qsize(), 0)
        self.assertEqual(os.listdir(self.tmp.name), [])
        self.post.assert_not_called()

    def test_everything_is_a_silent_no_op(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as errs:
            self.assertFalse(sentry.init("trade"))
            self.assertFalse(sentry.capture(caught(), where="x"))
            try:
                boom()
            except ValueError:
                self.assertFalse(sentry.capture())
            self.assertFalse(sentry.message("x"))
            self.assertTrue(sentry.flush(0))
        self.assertEqual(out.getvalue() + errs.getvalue(), "")
        self.unchanged()

    def test_empty_value_is_no_dsn(self):
        os.environ["SENTRY_DSN"] = "  "
        with contextlib.redirect_stderr(io.StringIO()) as errs:
            self.assertFalse(sentry.init("ui"))
        self.assertEqual(errs.getvalue(), "")
        self.unchanged()

    def test_unreadable_dsn_says_so_and_stays_off(self):
        os.environ["SENTRY_DSN"] = "https://nije-dsn.example.com/projekt"
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as errs:
            self.assertFalse(sentry.init("ui"))
            self.assertFalse(sentry.capture(caught()))
        self.assertIn("SENTRY_DSN nije u obliku", errs.getvalue())
        self.assertNotIn("nije-dsn", errs.getvalue())   # the value itself is not repeated in the log
        self.assertEqual(out.getvalue(), "")
        self.unchanged()

    def test_init_that_fails_inside_leaves_reporting_off(self):
        os.environ["SENTRY_DSN"] = DSN
        with mock.patch.object(sentry, "_install_hooks", side_effect=RuntimeError("pokvaren")), \
                contextlib.redirect_stderr(io.StringIO()) as errs:
            self.assertFalse(sentry.init("ui"))
        self.assertIn("sentry: nije pokrenut (RuntimeError)", errs.getvalue())
        self.assertFalse(sentry.capture(caught()))
        self.unchanged()


class Hooks(Base):
    INIT = None   # the "previous" hooks below must be in place before init

    def setUp(self):
        super().setUp()
        self.calls = []
        for p in (mock.patch.object(sys, "excepthook", lambda *a: self.calls.append(("sys", a[0].__name__))),
                  mock.patch.object(threading, "excepthook", lambda args: self.calls.append(("thread", args.exc_type.__name__))),
                  mock.patch.object(socketserver.BaseServer, "handle_error",
                                    lambda srv, request, client_address: self.calls.append(("http", client_address)))):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._off)   # first: sentry puts back the hooks above, then the patches put back the real ones

    def test_uncaught_exception_is_reported_and_passed_on(self):
        self.assertTrue(sentry.init("trade"))
        e = caught(RuntimeError, "petlja je stala")
        sys.excepthook(type(e), e, e.__traceback__)
        self.assertEqual(self.calls, [("sys", "RuntimeError")])   # the old hook still prints the traceback
        ev, = self.events()
        x = ev["exception"]["values"][-1]
        self.assertEqual((ev["level"], ev["tags"], x["mechanism"]),
                         ("fatal", {"component": "trade", "where": "sys.excepthook"}, {"type": "excepthook", "handled": False}))
        self.assertEqual(x["stacktrace"]["frames"][-1]["function"], "boom")

    def test_ctrl_c_is_passed_on_and_not_reported(self):
        sentry.init("trade")
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.assertEqual(self.calls, [("sys", "KeyboardInterrupt")])
        self.assertEqual(self.events(), [])

    def test_exception_in_a_thread(self):
        sentry.init("ui")
        t = threading.Thread(target=boom, args=(KeyError, "outAmount"), name="auto-sell")
        t.start()
        t.join()
        self.assertEqual(self.calls, [("thread", "KeyError")])
        ev, = self.events()
        x = ev["exception"]["values"][-1]
        self.assertEqual((ev["level"], ev["tags"]["where"], x["type"], x["mechanism"]),
                         ("error", "dretva auto-sell", "KeyError", {"type": "threading", "handled": False}))
        self.assertEqual(x["stacktrace"]["frames"][-1]["function"], "boom")

    def test_request_thread_of_a_real_server(self):
        """A handler without try/except (the 1-s fragments, public pages, POSTs): socketserver prints the traceback and
        drops the connection; neither sys.excepthook nor threading.excepthook ever sees it."""
        sentry.init("ui")

        class Page(BaseHTTPRequestHandler):
            def do_GET(self):
                if "otisao" in self.path:
                    raise BrokenPipeError(32, "Broken pipe")
                raise LookupError("fragment bez try/except")

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1 never through a proxy
        try:
            for path in ("/pravi-trade/log?m=tajni-upit", "/otisao"):
                with self.assertRaises(Exception):
                    direct.open(f"http://127.0.0.1:{srv.server_address[1]}{path}", timeout=10)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual([c[0] for c in self.calls], ["http", "http"])   # both still reach the old handler
        ev, = self.events()                                              # the visitor who left is not an error
        x = ev["exception"]["values"][-1]
        self.assertEqual((x["type"], x["mechanism"], ev["tags"]["where"]),
                         ("LookupError", {"type": "socketserver", "handled": False}, "http zahtjev"))
        raw = json.dumps(ev)
        for leak in ("127.0.0.1", "pravi-trade", "tajni-upit"):          # no address, no path, no query
            self.assertNotIn(leak, raw)

    def test_init_twice_installs_once(self):
        sentry.init("ui")
        first = (sys.excepthook, threading.excepthook, socketserver.BaseServer.handle_error)
        sentry.init("trade")
        self.assertEqual((sys.excepthook, threading.excepthook, socketserver.BaseServer.handle_error), first)
        e = caught()
        sys.excepthook(type(e), e, e.__traceback__)
        self.assertEqual(self.calls, [("sys", "ValueError")])            # the old hook once, not twice
        ev, = self.events()
        self.assertEqual(ev["tags"]["component"], "trade")

    def test_broken_reporter_still_passes_the_exception_on(self):
        sentry.init("ui")
        with mock.patch.object(sentry, "_capture", side_effect=RuntimeError("pokvaren")):
            e = caught()
            sys.excepthook(type(e), e, e.__traceback__)
            t = threading.Thread(target=boom)
            t.start()
            t.join()
            try:
                boom()
            except ValueError:
                socketserver.BaseServer.handle_error(object(), None, ("x", 1))
        self.assertEqual(self.calls, [("sys", "ValueError"), ("thread", "ValueError"), ("http", ("x", 1))])

    def test_reset_puts_the_previous_hooks_back(self):
        before = (sys.excepthook, threading.excepthook, socketserver.BaseServer.handle_error)
        sentry.init("ui")
        self.assertNotEqual((sys.excepthook, threading.excepthook, socketserver.BaseServer.handle_error), before)
        sentry._reset()
        self.assertEqual((sys.excepthook, threading.excepthook, socketserver.BaseServer.handle_error), before)


def _parents(tree):
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


class EntryPoints(unittest.TestCase):
    def test_every_loop_start_sh_keeps_alive_reports(self):
        with open(os.path.join(ROOT, "start.sh")) as f:
            code = "\n".join(ln for ln in f.read().splitlines() if not ln.lstrip().startswith("#"))
        # 10.11.: any "keep <name> ... run_x.py" outside a comment, also behind a prefix ("low keep ..." of the CPU
        # priority change in start.sh, "if ...; then keep ..."), so a new form of the line cannot hide a new loop
        kept = set(re.findall(r"\bkeep [\w-]+ [^\n#]*?\b(run_\w+\.py)", code))
        self.assertTrue({"run_ui.py", "run_trade.py", "run_kol.py", "run_sched.py"} <= kept, kept)
        self.assertFalse(kept - set(ENTRY), "novi stalni proces u start.sh: dodaj mu blok sentry.init(...) na početak "
                                            "main() i ime u ENTRY ovog testa")

    def test_init_is_first_in_main_and_guarded(self):
        for name, comp in ENTRY.items():
            with open(os.path.join(ROOT, name)) as f:
                tree = ast.parse(f.read())
            up = _parents(tree)
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "init" and isinstance(n.func.value, ast.Name) and n.func.value.id == "sentry"]
            self.assertEqual(len(calls), 1, name)
            self.assertEqual([a.value for a in calls[0].args], [comp], name)
            guard = up[up[calls[0]]]   # Call -> Expr -> Try
            self.assertIsInstance(guard, ast.Try, name)
            self.assertEqual([h.type.id for h in guard.handlers], ["Exception"], name)
            self.assertFalse([n for h in guard.handlers for n in ast.walk(h) if isinstance(n, ast.Raise)], name)
            home = up[guard]
            body = [s for s in home.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]
            self.assertIs(body[0], guard, f"{name}: prije svega ostalog u procesu")
            if name == "run_live.py":   # no main(): the block under `if __name__ == "__main__":`
                self.assertIsInstance(home, ast.If, name)
                self.assertIn("__main__", ast.unparse(home.test))
            else:
                self.assertEqual((type(home), home.name), (ast.FunctionDef, "main"), name)

    def test_import_alone_turns_nothing_on(self):
        code = ("import sys, threading\n"
                "hooks = (sys.excepthook, threading.excepthook)\n"
                "import run_ui, run_trade, run_sched, run_kol, run_tg, run_report, run_paper, run_watch, run_live\n"
                "from ops import sentry\n"
                "assert (sys.excepthook, threading.excepthook) == hooks and not sentry.enabled()\n"
                "print('uvoz u redu')\n")
        for dsn in (None, DSN):   # also with the variable set: only main() starts reporting, an import never does
            env = {k: v for k, v in os.environ.items() if k != "SENTRY_DSN"}
            if dsn:
                env["SENTRY_DSN"] = dsn
            r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "uvoz u redu"), r.stderr[-800:])

    def _mains(self):
        import run_kol
        import run_paper
        import run_report
        import run_tg
        import run_trade
        import run_ui
        import run_watch

        def report():   # the only main() here that reads sys.argv itself
            with mock.patch.object(sys, "argv", ["run_report.py", "--help"]):
                run_report.main()

        return {"ui": lambda: run_ui.main(["--help"]), "trade": lambda: run_trade.main(["--help"]),
                "kol": lambda: run_kol.main(["--help"]), "tg": lambda: run_tg.main(["--help"]),
                "paper": lambda: run_paper.main(["--help"]), "watch": lambda: run_watch.main(["--help"]), "report": report}

    def test_main_starts_reporting_with_its_component_and_then_runs(self):
        for comp, run in self._mains().items():
            with mock.patch.object(sentry, "init") as init, contextlib.redirect_stdout(io.StringIO()) as out, \
                    self.assertRaises(SystemExit) as stop:
                run()
            init.assert_called_once_with(comp)
            self.assertEqual(stop.exception.code, 0, comp)
            self.assertIn("usage:", out.getvalue(), comp)   # argparse got its turn after the init block

    def test_main_runs_when_the_reporter_is_broken(self):
        for comp, run in self._mains().items():
            with mock.patch.object(sentry, "init", side_effect=RuntimeError("pokvaren")), \
                    contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as errs, \
                    self.assertRaises(SystemExit) as stop:
                run()
            self.assertEqual(stop.exception.code, 0, comp)
            self.assertIn("usage:", out.getvalue(), comp)
            self.assertEqual(errs.getvalue(), "sentry: RuntimeError: pokvaren\n", comp)   # one line, then on with the start

    def test_scheduler_main(self):
        import run_sched
        with mock.patch.object(sentry, "init") as init, mock.patch.object(run_sched, "JOBS", []), \
                mock.patch.object(run_sched.time, "sleep", side_effect=StopIteration):
            with self.assertRaises(StopIteration):   # the scheduler's endless sleep, reached after the init block
                run_sched.main()
        init.assert_called_once_with("sched")

    def test_live_script_starts(self):
        env = {k: v for k, v in os.environ.items() if k != "SENTRY_DSN"}
        r = subprocess.run([sys.executable, "run_live.py", "--help"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn("usage:", r.stdout)
        self.assertEqual(r.stderr, "")


class CaptureSites(unittest.TestCase):
    def _follow(self, cap):
        import run_trade
        with mock.patch.object(run_trade, "load", return_value={"max_signal_age_s": 60, "poll_s": 0}), \
                mock.patch.object(run_trade.executor, "connect", side_effect=sqlite3.OperationalError("database is locked")), \
                mock.patch.object(run_trade.executor, "is_live", return_value=False), \
                mock.patch.object(run_trade.wallet, "address", return_value=None), \
                mock.patch.object(run_trade.signal, "signal"), mock.patch.dict(run_trade.STOPPING, {"flag": False}), \
                mock.patch.object(sentry, "capture", cap), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errs:
            self.assertIsNone(run_trade.cmd_follow(argparse.Namespace(config=None, once=True)))
        return errs.getvalue()

    def test_trade_loop_error_goes_to_sentry_with_the_exception(self):
        cap = mock.MagicMock()
        log = self._follow(cap)
        self.assertIn("greška: OperationalError: database is locked", log)   # the log line stays as it was
        (exc,), kw = cap.call_args
        self.assertIsInstance(exc, sqlite3.OperationalError)
        self.assertIsNotNone(exc.__traceback__)
        self.assertEqual((cap.call_count, kw), (1, {"where": "run_trade.cmd_follow"}))

    def test_trade_loop_survives_a_broken_reporter(self):
        cap = mock.MagicMock(side_effect=RuntimeError("pokvaren"))
        self.assertIn("greška: OperationalError", self._follow(cap))
        self.assertEqual(cap.call_count, 1)

    def test_page_error_has_one_mark_on_the_page_in_the_log_and_in_sentry(self):
        import run_ui
        for cap in (mock.MagicMock(), mock.MagicMock(side_effect=RuntimeError("pokvaren"))):   # a broken reporter: same page
            with mock.patch.object(sentry, "capture", cap), contextlib.redirect_stderr(io.StringIO()) as errs:
                try:
                    boom(KeyError, "x")
                except KeyError:
                    html = run_ui._error_html()
            ref = re.search(r"Oznaka za log: ([0-9a-f]{8})", html).group(1)
            self.assertIn(f"ui-greska {ref}:", errs.getvalue())
            cap.assert_called_once_with(where=f"ui-greska {ref}")

    def test_failing_sources_of_the_live_list_are_reported_one_by_one(self):
        from league import copy
        from topcheck import store as tstore
        from ui import pravitrade, zivo
        with mock.patch.object(tstore, "read_all", side_effect=RuntimeError("alat")), \
                mock.patch.object(pravitrade, "latest_picks", side_effect=AttributeError("prijedlog")), \
                mock.patch.object(copy, "_ro", side_effect=sqlite3.OperationalError("database is locked")), \
                mock.patch.object(pravitrade, "gather_callers", side_effect=KeyError("zovu")), \
                mock.patch.object(sentry, "capture") as cap, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(zivo._sources(time.time()), [])
        self.assertEqual([c.kwargs for c in cap.call_args_list],
                         [{"where": f"zivo izvor {s}"} for s in ("alat", "prijedlog", "konvergencija", "zovu")])
        with mock.patch.object(sentry, "capture", side_effect=RuntimeError("pokvaren")):
            try:
                boom()
            except ValueError:
                zivo._source_failed("alat")   # never raises into the list


class PageBuildEndToEnd(Base):
    INIT = "ui"

    def test_failed_page_build_is_one_event_with_the_mark_of_the_page(self):
        import run_ui
        with mock.patch.object(run_ui, "route", side_effect=ZeroDivisionError("float division by zero")), \
                contextlib.redirect_stderr(io.StringIO()):
            code, raw = run_ui.build("/pregled", {"q": "tajni-upit"})
        self.assertEqual(code, 500)
        ref = re.search(r"Oznaka za log: ([0-9a-f]{8})", raw.decode("utf-8")).group(1)
        ev, = self.events()
        self.assertEqual(ev["tags"], {"component": "ui", "where": f"ui-greska {ref}"})
        self.assertEqual(ev["exception"]["values"][-1]["type"], "ZeroDivisionError")
        self.assertEqual(ev["exception"]["values"][-1]["stacktrace"]["frames"][0],
                         {"filename": "run_ui.py", "function": "build", "in_app": True,
                          "lineno": ev["exception"]["values"][-1]["stacktrace"]["frames"][0]["lineno"]})
        self.assertNotIn("tajni-upit", json.dumps(ev))
        self.assertNotIn("/pregled", json.dumps(ev))


class ShortProcess(unittest.TestCase):
    def test_process_that_dies_sends_its_error_first_and_dies_as_before(self):
        """The real path, in a child: sys.excepthook -> queue -> sender thread -> urllib -> a stand-in on 127.0.0.1,
        with the exit hook waiting for the queue (page build children and KOL rounds live for seconds)."""
        got = []

        class StandIn(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                got.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        code = ("from ops import sentry\n"
                "assert sentry.init('proba')\n"
                "def racun():\n"
                "    tajna = 'LOKALNA-TAJNA'\n"
                "    return 1 / 0\n"
                "racun()\n")
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
            env.update(SENTRY_DSN=f"http://{KEY}@127.0.0.1:{srv.server_address[1]}/42", NO_PROXY="127.0.0.1",
                       no_proxy="127.0.0.1", TMPDIR=tmp)
            try:
                r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertEqual(r.returncode, 1)
        self.assertIn("ZeroDivisionError: division by zero", r.stderr)   # the traceback is printed as always
        (path, headers, body), = got
        self.assertEqual(path, "/api/42/envelope/")
        self.assertEqual((headers["content-type"], headers["x-sentry-auth"]),
                         ("application/x-sentry-envelope", f"Sentry sentry_version=7, sentry_key={KEY}, sentry_client=memesonar-stdlib/1"))
        head, item, payload = body.split(b"\n")[:3]
        self.assertEqual(json.loads(item)["length"], len(payload))
        ev = json.loads(payload)
        x = ev["exception"]["values"][-1]
        self.assertEqual((ev["level"], x["type"], x["mechanism"], [f["function"] for f in x["stacktrace"]["frames"]]),
                         ("fatal", "ZeroDivisionError", {"type": "excepthook", "handled": False}, ["<module>", "racun"]))
        self.assertNotIn(b"LOKALNA-TAJNA", body)


if __name__ == "__main__":
    unittest.main()
