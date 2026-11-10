"""Errors to Sentry with the standard library only (10.11., Jure: "Iskoristi Sentry da analiziraš i popraviš kod").

Until now an exception lived only in the Render log, one line among thousands ("greška: ...", "ui-greska ..."), and a
failure that repeated for days (the deleted-posts check failing in every KOL round, a dead source of "Što kupiti
sada") was found by reading logs by hand. Here the exception goes to Sentry, where equal errors are grouped, counted
and dated. No sentry-sdk: the container stays stdlib-only, and this file sends far less than the SDK would.

    from ops import sentry
    sentry.init("trade")                              # once per process; without SENTRY_DSN nothing happens, ever
    sentry.capture(e, where="run_trade.cmd_follow")   # an exception the code swallows (call it inside `except`)
    sentry.message("...", level="warning")            # a plain text event
    sentry.flush(2)                                   # short-lived process: wait for the queue (init does it at exit)

Sent: exception type and text (the text goes through scrub()), the stack as file / function / line, component,
release (git sha), environment. Never sent: local variables, source lines, environment variables, cookies, request
paths and queries, IP addresses, the host name, wallet addresses, keys.

What keeps it harmless for the process that calls it:
- capture() only builds a small dict and puts it on a bounded queue (full queue = the event is dropped); the HTTP
  POST happens in one daemon thread with a short timeout, so the trade loop or a page never waits for Sentry;
- at most PER_MINUTE events a minute per process, and the same error (type + innermost own frame) at most once in
  SAME_EVERY_S; after SAME_FAST reports in a row only once in SAME_SLOW_S, because a loop that fails every pass would
  otherwise use up the free monthly quota in days. The last report of an error is also kept as a small file in
  STAMP_DIR, so the short child processes (page builds, KOL rounds) share the same limit;
- nothing here raises to the caller, and a failed send is one log line an hour;
- importing this file does no work that depends on the machine (no network, no disk, no environment), so the import
  cannot fail where the tests passed. The entry points still call init() inside try/except: they belong to other
  groups of files, and a broken reporter must never keep the trade loop or the dashboard from starting.
"""
import atexit
import collections
import datetime as dt
import hashlib
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repository: frames under it are "in app"
CLIENT = "memesonar-stdlib/1"
QUEUE_MAX = 50            # events waiting for the sender; more than this are dropped, never waited for
PER_MINUTE = 30           # events a minute per process
SAME_EVERY_S = 300        # the same error at most once in 5 min ...
SAME_FAST = 3             # ... for its first 3 reports in a row, then
SAME_SLOW_S = 3600        # once an hour while it keeps happening (the free plan has a monthly quota)
SAME_FORGET_S = 6 * 3600  # quiet this long = a new streak (the first reports are fast again)
TIMEOUT_S = 3             # one POST; the queue is bounded, so a slow Sentry costs events, not time
FLUSH_AT_EXIT_S = 2.0
FAIL_LOG_EVERY_S = 3600
MAX_FRAMES = 50
MAX_CHAIN = 5             # "raised while handling" links followed
MAX_TEXT = 500            # characters of exception text kept after scrubbing
SEEN_MAX = 500
LEVELS = ("fatal", "error", "warning", "info", "debug")
STAMP_DIR = None          # where the last report of each error is kept; None = <temp dir>/memesonar-sentry, found on
                          # first use (never at import: tempfile raises when no directory is writable, e.g. a full disk)
HIDDEN = "[Filtered]"     # the word Sentry itself uses for removed data

_state = {"dsn": None, "component": "", "hooks": None, "pause_until": 0.0, "fail_log": 0.0, "pid": None,
          "thread": None, "atexit": False}
_lock = threading.Lock()
_q = queue.Queue(maxsize=QUEUE_MAX)
_recent = collections.deque()   # times of the events accepted in the last minute
_seen = {}                      # fingerprint -> [last sent, reports in a row, suppressed since]
STATS = {"sent": 0, "failed": 0, "dup": 0, "rate": 0, "full": 0}   # for tests and a look from the shell


# ---------------------------------------------------------------- DSN and wire format

_DSN = re.compile(r"^(https?)://([^:@/\s]+)(?::[^@/\s]*)?@([^/\s?#]+)((?:/[^/\s?#]+)*)/(\d+)/?$")


def parse_dsn(dsn):
    """{'key', 'host', 'project', 'url'} of https://<key>@<host>/<project_id>, or None when it is not a DSN.
    The old form with a secret (key:secret@) and a path before the project id (self-hosted) are read too; the
    secret is never used."""
    m = _DSN.match((dsn or "").strip())
    if not m:
        return None
    scheme, key, host, prefix, project = m.groups()
    return {"key": key, "host": host, "project": project, "url": f"{scheme}://{host}{prefix}/api/{project}/envelope/"}


def auth_header(dsn):
    return f"Sentry sentry_version=7, sentry_key={dsn['key']}, sentry_client={CLIENT}"


def envelope(event, now=None):
    """Bytes of a Sentry envelope with one event item: three JSON lines (envelope header, item header, payload).
    `length` is the payload size in bytes; the payload is ASCII-only JSON, so no line break can appear inside it."""
    now = time.time() if now is None else now
    body = json.dumps(event, separators=(",", ":")).encode("ascii")
    sent = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(now % 1 * 1000):03d}Z"
    head = json.dumps({"event_id": event["event_id"], "sent_at": sent}, separators=(",", ":")).encode("ascii")
    item = json.dumps({"type": "event", "length": len(body), "content_type": "application/json"},
                      separators=(",", ":")).encode("ascii")
    return head + b"\n" + item + b"\n" + body + b"\n"


# ---------------------------------------------------------------- scrubbing
# every repeat below is bounded where a long run could make the search quadratic: scrub() runs in the thread
# that reports the error (the trade loop, a request), on at most 8 * MAX_TEXT characters, a few ms at worst

_URL_USER = re.compile(r"(\b[a-z][a-z0-9+.-]{0,15}://)[^/\s@'\"]{1,200}@", re.I)
_URL_QUERY = re.compile(r"(\b[a-z][a-z0-9+.-]{0,15}://[^\s?#'\"<>]{0,400})\?[^\s'\"<>]*", re.I)
_HEADER = re.compile(r"\b((?:proxy-)?authorization|(?:set-)?cookie|x-[\w-]{0,30}?(?:key|token|auth)[\w-]{0,30}|api[-_]?key|"
                     r"(?:private|secret)[-_ ]?key|password|lozinka)(['\"]?\s*:\s*['\"]?)[^\r\n'\"]+", re.I)
# 10.11.: a dict or JSON printed into the text ({'token': 'x'}, {"access_token": "..."}): short values too, which the
# long-run rule below never sees; only a quoted name followed by a quoted value, so "token: BONK" stays readable
_QUOTED = re.compile(r"""(['"][\w-]{0,30}?(?:key|token|secret|passw|pwd|lozink|auth|cookie|session)[\w-]{0,30}['"]"""
                     r"""\s*:\s*['"])[^'"\r\n]{1,400}""", re.I)
_BEARER = re.compile(r"\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}", re.I)
_KEY_VALUE = re.compile(r"((?:key|token|secret|passw|pwd|lozink|auth|cookie|session|signature)[\w-]{0,40}\s*=\s*)"
                        r"(?!\[Filtered\])[^\s&;,'\")\]}>]+", re.I)
_OUR_COOKIE = re.compile(r"\b(cb_\w+=)[^;\s'\"]+")
_TG_BOT = re.compile(r"\bbot\d{6,}:[\w-]{20,}")
_JWT = re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}")
_BYTE_LIST = re.compile(r"\[\s*\d{1,3}(?:\s*,\s*\d{1,3}){31,}\s*\]")   # a private key printed as a list of bytes
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_RUN = re.compile(r"[A-Za-z0-9+/=_-]{24,}")


def _classes(s):
    return any(c.isupper() for c in s), any(c.islower() for c in s), any(c.isdigit() for c in s)


def _secret_like(s):
    """A run of key-alphabet characters that reads like a key, an address or a hash rather than a word: 32+ with
    letters and digits (hex, base58, base64, UUID); 32+ letters of which a quarter or more are capitals (base58 that
    happens to have no digit: 1 address in 200; CamelCase names have far fewer capitals); or 24-31 characters with
    capitals, small letters and digits together."""
    up, low, dig = _classes(s)
    if len(s) >= 32:
        if dig:
            return up or low
        return up and low and sum(c.isupper() for c in s) * 4 >= len(s)
    return up and low and dig


def _plain_word(p):
    """A part of a path that is an ordinary word: small letters (digits, - and _ allowed), no capitals: api, v0."""
    return 2 <= len(p) < 24 and not any(c.isupper() for c in p) and any(c.isalpha() for c in p)


def _hide_run(m):
    s = m.group(0)
    if "/" not in s:
        return HIDDEN if _secret_like(s) else s
    parts = s.split("/")
    # '/' is also a letter of base64. A path has ordinary words between the slashes (/v0/addresses/<wallet>/
    # transactions); base64 almost never has two of them, and a '+' or a closing '=' gives it away at once. Measured
    # on 20,000 random 64-byte keys: a first version that looked at each part alone left up to the whole key readable
    # in 1.6 % of them.
    if ("+" in s or s.endswith("=") or sum(map(_plain_word, parts)) < 2) and _secret_like(s.replace("/", "")):
        return HIDDEN
    # a path: only the parts that are themselves a key or an address go, so the text still says which call failed
    return "/".join(HIDDEN if (len(p) >= 24 and _secret_like(p)) or (len(p) >= 12 and all(_classes(p))) else p
                    for p in parts)


def scrub(text, limit=MAX_TEXT):
    """Exception text without what must not leave the server: query strings and logins in URLs, values after
    key-like names (api-key=, token=, Authorization:, Cookie:), bearer tokens, long base58 / base64 / hex runs
    (private keys, API keys, signatures and also wallet and token addresses), e-mail and IP addresses. It hides too
    much rather than too little: a hidden token address costs a look at the log, a leaked key costs money."""
    try:
        s = str(text)
    except Exception:  # noqa: BLE001 - an exception whose __str__ fails still gets reported
        return "<tekst greške se ne može pročitati>"
    s = s[:8 * limit].encode("utf-8", "replace").decode("utf-8")   # bounded work; no lone surrogates in the JSON
    s = _URL_USER.sub(rf"\1{HIDDEN}@", s)
    s = _URL_QUERY.sub(rf"\1?{HIDDEN}", s)
    s = _HEADER.sub(rf"\1\2{HIDDEN}", s)
    s = _QUOTED.sub(rf"\1{HIDDEN}", s)
    s = _BEARER.sub(rf"\1 {HIDDEN}", s)
    s = _KEY_VALUE.sub(rf"\1{HIDDEN}", s)
    s = _OUR_COOKIE.sub(rf"\1{HIDDEN}", s)
    s = _TG_BOT.sub(f"bot{HIDDEN}", s)
    s = _JWT.sub(HIDDEN, s)
    s = _BYTE_LIST.sub(HIDDEN, s)
    s = _EMAIL.sub("[email]", s)
    s = _IPV4.sub("[ip]", s)
    s = _RUN.sub(_hide_run, s)
    return s if len(s) <= limit else s[:limit] + "…"


# ---------------------------------------------------------------- the event

def _frame(filename, function, lineno):
    path = filename if filename.startswith("<") else os.path.abspath(filename)
    in_app = path.startswith(ROOT + os.sep) and "site-packages" not in path
    if in_app:
        name = os.path.relpath(path, ROOT).replace(os.sep, "/")
    else:   # outside the repository only the last two parts: no home directory, no user name
        name = "/".join(path.replace("\\", "/").split("/")[-2:])
    return {"filename": name, "function": function, "lineno": lineno or 0, "in_app": in_app}


def frames_of(tb):
    """[{filename, function, lineno, in_app}] of a traceback, oldest call first (the order Sentry wants). Only the
    code object and the line are read: local variables never leave the frame."""
    out = []
    while tb is not None:
        code = tb.tb_frame.f_code
        out.append(_frame(code.co_filename, code.co_name, tb.tb_lineno))
        tb = tb.tb_next
    return out[-MAX_FRAMES:]


def fingerprint(kind, frames, where=""):
    """What makes two errors "the same" for the 5-minute rule: the type and the innermost frame of our own code
    (the innermost frame of any code when none is ours, the call site label when there is no stack at all)."""
    top = next((f for f in reversed(frames) if f["in_app"]), frames[-1] if frames else None)
    return (kind, top["filename"], top["function"], top["lineno"]) if top else (kind, where)


def _chain(exc):
    """The exception and what led to it (raise ... from, or raised while handling another), oldest first."""
    out, seen = [], set()
    while exc is not None and id(exc) not in seen and len(out) < MAX_CHAIN:
        seen.add(id(exc))
        out.append(exc)
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return out[::-1]


def _exception_value(exc, frames):
    t = type(exc)
    v = {"type": t.__name__, "value": scrub(exc)}
    if t.__module__ not in ("builtins", "__main__"):
        v["module"] = t.__module__
    if frames:
        v["stacktrace"] = {"frames": frames}
    return v


def build_event(exc=None, where="", level="error", text=None, frames=None, handled=True, mechanism="generic",
                suppressed=0, now=None):
    """The event payload: an exception (with its chain) or a plain message `text`. `frames` are the frames of `exc`
    when the caller already has them."""
    comp = _state["component"] or "?"
    ev = {"event_id": uuid.uuid4().hex, "timestamp": round(time.time() if now is None else now, 3),
          "platform": "python", "level": level if level in LEVELS else "error", "logger": f"memesonar.{comp}",
          "server_name": "render",   # fixed: the real host name says nothing and is not ours to publish
          "environment": "production" if os.environ.get("RENDER") else "local", "tags": {"component": comp}}
    release = (os.environ.get("RENDER_GIT_COMMIT") or "").strip()
    if release:
        ev["release"] = release[:64]
    if where:
        ev["tags"]["where"] = scrub(where, 120)
    if suppressed:
        ev["extra"] = {"suppressed_since_last_report": suppressed}
    if exc is not None:
        chain = _chain(exc)
        values = [_exception_value(e, frames_of(e.__traceback__)) for e in chain[:-1]]
        last = _exception_value(exc, frames if frames is not None else frames_of(exc.__traceback__))
        last["mechanism"] = {"type": mechanism, "handled": bool(handled)}
        ev["exception"] = {"values": values + [last]}
    else:
        ev["message"] = {"formatted": scrub(text)}
    return ev


# ---------------------------------------------------------------- limits

def _stamp_dir():
    global STAMP_DIR
    if STAMP_DIR is None:
        STAMP_DIR = os.path.join(tempfile.gettempdir(), "memesonar-sentry")
    return STAMP_DIR


def _stamp_path(fp):
    """One small file per error: its name is a hash of the fingerprint, its content the reports in a row, its
    modification time the last report. Nothing readable about the error is written."""
    return os.path.join(_stamp_dir(), hashlib.sha1(repr(fp).encode("utf-8", "replace")).hexdigest()[:20])


def _stamp_read(fp):
    """[last sent, reports in a row] another process (or this one before) left for this error, or None."""
    try:
        p = _stamp_path(fp)
        last = os.path.getmtime(p)
        with open(p) as f:
            return [last, int(f.read().strip() or 1)]
    except (OSError, ValueError):
        return None


def _stamp_write(fp, now, streak):
    try:
        os.makedirs(_stamp_dir(), exist_ok=True)
        p = _stamp_path(fp)
        with open(p, "w") as f:
            f.write(str(streak))
        os.utime(p, (now, now))
    except OSError:   # no temp directory to write to: the limit still holds inside this process
        pass


def _stamp_prune(now):
    """Stamps older than SAME_FORGET_S decide nothing any more; removed at init so the folder stays a few files."""
    try:
        for name in os.listdir(_stamp_dir()):
            p = os.path.join(STAMP_DIR, name)
            if now - os.path.getmtime(p) > SAME_FORGET_S:
                os.remove(p)
    except OSError:
        pass


def _too_soon(rec, now):
    return 0 <= now - rec[0] < (SAME_EVERY_S if rec[1] < SAME_FAST else SAME_SLOW_S)


def _admit(fp, now):
    """Number of equal errors held back since the last report when this one may go out; None when it may not
    (the same error too soon, or PER_MINUTE reached)."""
    with _lock:
        rec = _seen.get(fp)
        if rec is None or not _too_soon(rec, now):
            on_disk = _stamp_read(fp)   # only when memory would let it through: at most once per error per window
            if on_disk and (rec is None or on_disk[0] > rec[0]):
                rec = [on_disk[0], on_disk[1], rec[2] if rec else 0]
        if rec is not None and _too_soon(rec, now):
            rec[2] += 1
            _seen[fp] = rec
            STATS["dup"] += 1
            return None
        while _recent and now - _recent[0] >= 60:
            _recent.popleft()
        if len(_recent) >= PER_MINUTE:
            STATS["rate"] += 1
            return None
        _recent.append(now)
        streak = rec[1] + 1 if rec is not None and now - rec[0] <= SAME_FORGET_S else 1
        held = rec[2] if rec is not None else 0
        if len(_seen) >= SEEN_MAX:   # a process with hundreds of different errors: forget the oldest half
            for k in sorted(_seen, key=lambda k: _seen[k][0])[:SEEN_MAX // 2]:
                del _seen[k]
        _seen[fp] = [now, streak, 0]
    _stamp_write(fp, now, streak)
    return held


# ---------------------------------------------------------------- sending

def _log(text):
    """One line to stderr, never stdout: a page build child (run_ui.py --render) writes the page itself to stdout."""
    print(f"sentry: {text}", file=sys.stderr, flush=True)


def _send_failed(why, now):
    STATS["failed"] += 1
    if now - _state["fail_log"] >= FAIL_LOG_EVERY_S:
        _state["fail_log"] = now
        _log(f"slanje greške nije uspjelo ({why}); o tome najviše jedan redak na sat")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is not followed: the event and the key go to the host in the DSN or nowhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(url, headers, body):
    """The only network call in this file: one POST with a short timeout. Raises what urllib raises."""
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.build_opener(_NoRedirect).open(req, timeout=TIMEOUT_S) as r:
        r.read()


def _send(event, now=None):
    """One POST of one event. True when Sentry took it; a failure is counted, logged once an hour and forgotten."""
    now = time.time() if now is None else now
    dsn = _state["dsn"]
    if not dsn or now < _state["pause_until"]:
        return False
    try:
        _post(dsn["url"], {"Content-Type": "application/x-sentry-envelope", "X-Sentry-Auth": auth_header(dsn),
                           "User-Agent": CLIENT}, envelope(event, now))
        STATS["sent"] += 1
        return True
    except urllib.error.HTTPError as e:
        if e.code == 429:   # quota or burst limit: Sentry says for how long it takes nothing
            try:
                wait = float(e.headers.get("Retry-After") or 60)
            except (TypeError, ValueError):
                wait = 60
            _state["pause_until"] = now + min(max(wait, 60), 3600)
        elif e.code in (401, 403, 404):   # wrong or revoked DSN: nothing will pass, ask again in an hour
            _state["pause_until"] = now + 3600
        _send_failed(f"HTTP {e.code}", now)
        e.close()
    except Exception as e:  # noqa: BLE001 - no network, timeout, TLS: the event is lost, the process is not
        _send_failed(type(e).__name__, now)
    return False


def _drain():
    while True:
        event = _q.get()
        try:
            _send(event)
        except Exception:  # noqa: BLE001 - the sender thread must outlive anything
            pass
        finally:
            _q.task_done()


def _offer(event):
    """Queue the event for the sender thread (started on the first event, so a process without errors has no
    extra thread). False when the queue is full."""
    try:
        _q.put_nowait(event)
    except queue.Full:
        STATS["full"] += 1
        return False
    with _lock:
        t = _state["thread"]
        if t is None or not t.is_alive() or _state["pid"] != os.getpid():
            t = threading.Thread(target=_drain, name="sentry", daemon=True)
            _state["thread"], _state["pid"] = t, os.getpid()
            t.start()
    return True


def flush(timeout=FLUSH_AT_EXIT_S):
    """Wait up to `timeout` seconds for queued events to be sent; True when nothing is left. For short-lived
    processes (a page build child, one KOL round); init() registers it at exit."""
    end = time.monotonic() + max(0.0, timeout or 0.0)
    while _q.unfinished_tasks and time.monotonic() < end:
        time.sleep(0.02)
    return not _q.unfinished_tasks


# ---------------------------------------------------------------- public calls

def enabled():
    return bool(_state["dsn"])


def _report(fp, build, now=None):
    now = time.time() if now is None else now
    if now < _state["pause_until"]:   # Sentry said "not now" (quota, wrong key): nothing is built or queued meanwhile
        return False
    if _q.full():
        STATS["full"] += 1
        return False
    held = _admit(fp, now)
    if held is None:
        return False
    return _offer(build(held, now))


def _capture(exc, where, level, handled=True, mechanism="generic", tb=None, now=None):
    if not _state["dsn"]:
        return False
    if exc is None:
        exc = sys.exc_info()[1]
    if isinstance(exc, tuple):   # (type, value, traceback) as sys.exc_info() gives it
        exc, tb = exc[1], (exc[2] if len(exc) > 2 else None)
    if not isinstance(exc, BaseException) or isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
        return False
    frames = frames_of(tb if tb is not None else exc.__traceback__)
    return _report(fingerprint(type(exc).__name__, frames, where),
                   lambda held, t: build_event(exc, where, level, frames=frames, handled=handled, mechanism=mechanism,
                                               suppressed=held, now=t), now)


def capture(exc=None, where="", level="error"):
    """Report an exception the code is about to swallow. exc=None takes the one being handled (call it inside
    `except`). `where` is a short label of the call site (never a URL or anything a visitor typed). Returns True when
    the event was queued; never raises and never waits for the network."""
    try:
        return _capture(exc, where, level)
    except Exception:  # noqa: BLE001 - reporting an error must not become one
        return False


def message(text, level="warning", where=""):
    """Report a plain text event (scrubbed like exception text). True when it was queued; never raises."""
    try:
        if not _state["dsn"]:
            return False
        clean = scrub(text)
        return _report(("message", clean[:120], where),
                       lambda held, t: build_event(None, where, level, text=clean, suppressed=held, now=t))
    except Exception:  # noqa: BLE001
        return False


def _install_hooks():
    """Uncaught exceptions of the main thread, of other threads and of HTTP request threads are reported, and then
    handled exactly as before (the previous hook is always called, so the traceback still reaches the log)."""
    prev_sys, prev_thread = sys.excepthook, threading.excepthook

    def on_uncaught(etype, value, tb):
        try:
            _capture(value, "sys.excepthook", "fatal", handled=False, mechanism="excepthook", tb=tb)
        except Exception:  # noqa: BLE001
            pass
        prev_sys(etype, value, tb)

    def on_thread(args):
        try:
            name = getattr(args.thread, "name", "") or "?"
            _capture(args.exc_value, f"dretva {name}", "error", handled=False, mechanism="threading",
                     tb=args.exc_traceback)
        except Exception:  # noqa: BLE001
            pass
        prev_thread(args)

    sys.excepthook, threading.excepthook = on_uncaught, on_thread
    hooks = {"sys": (on_uncaught, prev_sys), "thread": (on_thread, prev_thread), "http": None}
    # the dashboard: an exception in a request thread that the handler does not catch (the 1-s Autopilot fragments,
    # public pages, POSTs) ends in socketserver's handle_error, which neither hook above ever sees. Only in a
    # process that already serves HTTP.
    ss = sys.modules.get("socketserver")
    if ss is not None:
        prev_http = ss.BaseServer.handle_error

        def handle_error(self, request, client_address):
            try:
                exc = sys.exc_info()[1]
                if not isinstance(exc, ConnectionError):   # the visitor left (1-s polls drop old requests): no error
                    _capture(exc, "http zahtjev", "error", handled=False, mechanism="socketserver")
            except Exception:  # noqa: BLE001
                pass
            return prev_http(self, request, client_address)

        ss.BaseServer.handle_error = handle_error
        hooks["http"] = (ss, handle_error, prev_http)
    return hooks


def init(component):
    """Turn reporting on for this process, labelled `component` (ui, trade, sched, kol ...). Without SENTRY_DSN, or
    with one that cannot be read, nothing is installed and every call here stays a no-op. Safe to call twice; never
    raises. True when reporting is on."""
    try:
        dsn = parse_dsn(os.environ.get("SENTRY_DSN", ""))
        if not dsn:
            if (os.environ.get("SENTRY_DSN") or "").strip():
                _log("SENTRY_DSN nije u obliku https://<ključ>@<host>/<projekt>, greške se ne šalju")
            return False
        if _state["hooks"] is None:
            _state["hooks"] = _install_hooks()
        if not _state["atexit"]:   # a short process (page build child, one round) sends what it queued before it ends
            atexit.register(flush)
            _state["atexit"] = True
            _stamp_prune(time.time())
        _state["dsn"], _state["component"] = dsn, str(component or "?")[:40]   # last: on only when all of it is in place
        return True
    except Exception as e:  # noqa: BLE001 - a broken reporter must never stop the process it reports for
        _log(f"nije pokrenut ({type(e).__name__})")
        return False


def _reset():
    """Tests only: reporting off, hooks back to what they were, limits and counters cleared."""
    hooks, _state["hooks"] = _state["hooks"], None
    if hooks:
        if sys.excepthook is hooks["sys"][0]:
            sys.excepthook = hooks["sys"][1]
        if threading.excepthook is hooks["thread"][0]:
            threading.excepthook = hooks["thread"][1]
        if hooks["http"] and hooks["http"][0].BaseServer.handle_error is hooks["http"][1]:
            hooks["http"][0].BaseServer.handle_error = hooks["http"][2]
    if _state["atexit"]:
        atexit.unregister(flush)
    _state.update(dsn=None, component="", pause_until=0.0, fail_log=0.0, atexit=False)
    with _lock:
        _seen.clear()
        _recent.clear()
    while True:
        try:
            _q.get_nowait()
            _q.task_done()
        except queue.Empty:
            break
    for k in STATS:
        STATS[k] = 0
