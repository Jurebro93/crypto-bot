"""The POST to Grok Bot's webhook (env GROKBOT_WEBHOOK_URL, GROKBOT_WEBHOOK_KEY; never in the repository or a log).

Body: one compact JSON object (the exact bytes signed are the bytes sent), Content-Type application/json:
    id, event (zone_enter | zone_exit | stop_hit | top_hit | team_catalyst) and the owner's fields
    mint, symbol, zone_type, zone_lo, zone_hi, mcap, price, liq, vol_5m, vol_1h, buys_5m, sells_5m, buy_share_5m,
    buy_share_1h, uniq_traders_1h, rug_risk, source, ts (null when unknown, never left out), plus a few extras
    (ts_iso, direction, note, initial, data_age_s, price_source).
Auth (the receiver's docs could not be read from the sandbox, so both are implemented):
    bearer     (default)  Authorization: Bearer <GROKBOT_WEBHOOK_KEY>
    standard   (GROKBOT_WEBHOOK_AUTH=standard, or a key starting "whsec_")  Standard Webhooks: webhook-id (the alert
               id, the same on every retry), webhook-timestamp (unix seconds, fresh per attempt), webhook-signature
               "v1,<base64 HMAC-SHA256(secret, f'{id}.{timestamp}.{body}')>", the secret = base64 of the key after
               "whsec_" (its raw UTF-8 bytes when that is not base64). No Authorization header then.
Delivery: timeout TIMEOUT_S (5 s); retried only on a network error, a timeout, 429 or 5xx: 3 retries after 1, 2, 4 s
(a Retry-After, capped at 10 s, when it asks for longer); 3xx (redirects are never followed: a header must not travel
to another host) and the other 4xx are a configuration error, logged once, not retried.
Secrets: neither the key nor the URL's path or query is ever printed, stored or put into an exception's text: the
log has scheme + host, the status, the latency, the attempt and a short error class (never an exception message).
Without the env (or with a URL that is not https): nothing is posted, every alert is stored with status
not_configured and the server log gets one line a day.
"""
import base64
import binascii
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from zonewatch import store

TIMEOUT_S = 5
RETRIES = 3
BACKOFF_S = (1, 2, 4)
RETRY_AFTER_MAX_S = 10
OWNER_FIELDS = ("mint", "symbol", "zone_type", "zone_lo", "zone_hi", "mcap", "price", "liq", "vol_5m", "vol_1h",
                "buys_5m", "sells_5m", "buy_share_5m", "buy_share_1h", "uniq_traders_1h", "rug_risk", "source", "ts")
USER_AGENT = "memesonar-zonewatch/1.0"
FINAL = ("sent", "failed", "config_error", "not_configured", "off", "expired")


class Config:
    """The webhook settings of this process. repr / str never show the key or the URL's path."""
    __slots__ = ("url", "key", "auth", "host", "why")

    def __init__(self, url=None, key=None, auth=None):
        self.url, self.key = (url or "").strip(), (key or "").strip()
        a = (auth or "").strip().lower()
        self.auth = "standard" if a == "standard" or self.key.startswith("whsec_") else "bearer"
        self.host, self.why = None, None
        if not self.url or not self.key:
            self.why = "GROKBOT_WEBHOOK_URL / GROKBOT_WEBHOOK_KEY nisu postavljeni"
            return
        try:
            u = urllib.parse.urlsplit(self.url)
            host = u.hostname or ""
            port = f":{u.port}" if u.port else ""
        except ValueError:
            u, host, port = None, "", ""
        local = host in ("localhost", "127.0.0.1")
        if not u or not host or not (u.scheme == "https" or (u.scheme == "http" and local)):
            self.why = "GROKBOT_WEBHOOK_URL nije https adresa"
            return
        self.host = f"{u.scheme}://{host}{port}"

    @property
    def configured(self):
        return self.why is None

    def __repr__(self):
        return f"<webhook {self.auth} {self.host or 'nije postavljen'}>"

    __str__ = __repr__


def config(env=None):
    e = os.environ if env is None else env
    return Config(e.get("GROKBOT_WEBHOOK_URL"), e.get("GROKBOT_WEBHOOK_KEY"), e.get("GROKBOT_WEBHOOK_AUTH"))


# ---------- the body and the headers --------------------------------------------------------------------------------

def share(b, s):
    try:
        b, s = float(b), float(s)
    except (TypeError, ValueError):
        return None
    return round(b / (b + s), 4) if b + s > 0 else None


def new_id(*parts):
    """A stable alert id: zw_<unix ts>_<10 hex of the parts>."""
    h = hashlib.blake2b("|".join(str(p) for p in parts).encode(), digest_size=5).hexdigest()
    return f"zw_{int(parts[-1]) if parts and isinstance(parts[-1], (int, float)) else int(time.time())}_{h}"


def normalize(alert, now=None):
    """The payload: the owner's fields (null when unknown, never left out), id and event, then the extras as given.
    An id is made once here when the caller did not bring one (it then stays the same over the retries)."""
    a = dict(alert or {})
    now = int(now or time.time())
    if a.get("ts") is None:
        a["ts"] = now
    a["ts"] = int(float(a["ts"]))
    if a["ts"] > 1e11:   # milliseconds
        a["ts"] //= 1000
    zt = a.get("zone_type")
    ev = a.get("event") or ("team_catalyst" if zt == "team_catalyst" else None)
    if a.get("buy_share_5m") is None:
        a["buy_share_5m"] = share(a.get("buys_5m"), a.get("sells_5m"))
    # the id travels as the webhook-id header: letters, digits and _ . : - only
    aid = re.sub(r"[^A-Za-z0-9_.:-]", "", str(a.get("id") or ""))[:80] or \
        new_id(a.get("mint"), zt, ev, a.get("source"), a["ts"])
    out = {"id": aid, "event": ev}
    for k in OWNER_FIELDS:
        out[k] = a.get(k)
    out["ts_iso"] = dt.datetime.fromtimestamp(out["ts"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for k, v in a.items():
        if k not in out:
            out[k] = v
    return out


def body_bytes(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def secret_bytes(key):
    """Standard Webhooks: the secret is the base64 after "whsec_"; a key that is not base64 is used as its UTF-8."""
    k = key[6:] if key.startswith("whsec_") else key
    try:
        raw = base64.b64decode(k, validate=True)
        if raw:
            return raw
    except (binascii.Error, ValueError):
        pass
    return k.encode("utf-8")


def signature(key, msg_id, ts, body):
    """'v1,<base64 HMAC-SHA256(secret, b"{id}.{ts}.{body}")>' (Standard Webhooks)."""
    msg = f"{msg_id}.{int(ts)}.".encode("utf-8") + body
    return "v1," + base64.b64encode(hmac.new(secret_bytes(key), msg, hashlib.sha256).digest()).decode("ascii")


def headers(cfg, msg_id, ts, body):
    h = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if cfg.auth == "standard":
        h.update({"webhook-id": msg_id, "webhook-timestamp": str(int(ts)),
                  "webhook-signature": signature(cfg.key, msg_id, ts, body)})
    else:
        h["Authorization"] = f"Bearer {cfg.key}"
    return h


# ---------- the request ---------------------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):   # a redirect is a configuration error
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(req, timeout):
    """(status, headers) of one request (urllib, no redirects followed)."""
    with _OPENER.open(req, timeout=timeout) as r:
        r.read(4096)
        return r.status, r.headers


def _retry_after(h):
    try:
        v = (h or {}).get("Retry-After")
    except Exception:  # noqa: BLE001
        return None
    if not v:
        return None
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        return max(0.0, parsedate_to_datetime(v).timestamp() - time.time())
    except Exception:  # noqa: BLE001
        return None


def _err_class(e):
    """A short, secret-free name of what went wrong (never str(e): urllib may put the URL into it)."""
    if isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower():
        return "timeout"
    if isinstance(e, urllib.error.URLError):
        r = getattr(e, "reason", None)
        if isinstance(r, TimeoutError) or "timed out" in type(r).__name__.lower():
            return "timeout"
        return f"URLError/{type(r).__name__}" if r is not None and not isinstance(r, str) else "URLError"
    return type(e).__name__


def send_once(cfg, body, msg_id, opener=None, now=None):
    """One attempt: (http_status or None, retry_after_s or None, error class or None, latency ms)."""
    ts = int(now if now is not None else time.time())
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(cfg.url, data=body, headers=headers(cfg, msg_id, ts, body), method="POST")
        status, hdrs = (opener or _open)(req, TIMEOUT_S)
        return int(status), _retry_after(hdrs), None, round((time.perf_counter() - t0) * 1000)
    except urllib.error.HTTPError as e:
        try:
            ra = _retry_after(e.headers)
        except Exception:  # noqa: BLE001
            ra = None
        try:
            e.close()
        except Exception:  # noqa: BLE001
            pass
        return int(e.code), ra, f"HTTP {int(e.code)}", round((time.perf_counter() - t0) * 1000)
    except Exception as e:  # noqa: BLE001 - network error, timeout, TLS: retried
        return None, None, _err_class(e), round((time.perf_counter() - t0) * 1000)


def retryable(status):
    return status is None or status == 429 or status >= 500


def post(cfg, payload, opener=None, sleep=None, clock=None, on_attempt=None):
    """POST one alert with the retries. on_attempt(attempt, status, http_status, latency_ms, error) per try.
    Returns {"ok", "status" (sent | failed | config_error), "http_status", "attempts", "latency_ms", "error"}."""
    sleep = sleep or time.sleep
    clock = clock or time.time
    body = body_bytes(payload)
    msg_id = payload["id"]
    out = {"ok": False, "status": "failed", "http_status": None, "attempts": 0, "latency_ms": None, "error": None}
    for attempt in range(1, RETRIES + 2):
        code, ra, err, ms = send_once(cfg, body, msg_id, opener, clock())
        out.update(attempts=attempt, http_status=code, latency_ms=ms, error=err)
        if code is not None and 200 <= code < 300:
            out.update(ok=True, status="sent", error=None)
            if on_attempt:
                on_attempt(attempt, "ok", code, ms, None)
            return out
        again = retryable(code) and attempt <= RETRIES
        st = "retry" if again else ("failed" if retryable(code) else "config_error")
        if on_attempt:
            on_attempt(attempt, st, code, ms, err)
        if not again:
            out["status"] = st
            return out
        wait = BACKOFF_S[attempt - 1]
        if ra:
            wait = max(wait, min(ra, RETRY_AFTER_MAX_S))
        sleep(wait)
    return out


# ---------- the alert's life in zonewatch.db ------------------------------------------------------------------------

def _log(con, now, alert_id, event, attempt, status, http_status, latency_ms, host, error):
    con.execute("INSERT INTO zonewatch_log VALUES (?,?,?,?,?,?,?,?,?)",
                (int(now), alert_id, event, attempt, status, http_status, latency_ms, host, error))


def _say_daily(con, key, text, now):
    """One line a UTC day for this key."""
    if store.kv_get(con, f"said:{key}") != store.day(now):
        store.kv_put(con, f"said:{key}", store.day(now))
        print(text, flush=True)


def record(con, payload, status="pending", now=None):
    """Store an alert (INSERT OR IGNORE by id: an id seen before is a duplicate). True when it is new. alerts.ts is
    when it was stored (the debounce, the pending expiry and the 24 h count run on it); the payload keeps its own ts."""
    now = int(now or time.time())
    before = con.total_changes
    con.execute("INSERT OR IGNORE INTO alerts (id, ts, mint, zone_type, event, source, status, attempts, payload) "
                "VALUES (?,?,?,?,?,?,?,0,?)",
                (payload["id"], now, payload.get("mint"), payload.get("zone_type"),
                 payload.get("event"), payload.get("source"), status, body_bytes(payload).decode("utf-8")))
    new = con.total_changes > before
    if new:
        try:   # dual write (events.db type zone_alert); emit never raises and never waits on the database
            from events import store as estore
            estore.emit("zone_alert", payload.get("ts") or now, payload.get("mint"), "zonewatch", None, None,
                        payload.get("mcap"), payload, key=f"zone_alert|{payload['id']}")
        except Exception:  # noqa: BLE001
            pass
    return new


def deliver(con, alert_id, cfg=None, flag=None, now=None, opener=None, sleep=None, clock=None):
    """Send one stored alert (status pending) and record the outcome: off (flag off: nothing posted),
    not_configured (no env: nothing posted), sent | failed | config_error. Returns the outcome dict."""
    now = int(now or time.time())
    row = con.execute("SELECT payload, status, event FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not row:
        return {"ok": False, "status": "unknown"}
    if row[1] != "pending":
        return {"ok": row[1] == "sent", "status": "duplicate" if row[1] == "sent" else row[1]}
    payload = json.loads(row[0])
    event = row[2]
    cfg = cfg or config()
    flag = flag or store.mode()
    if flag == "off":
        con.execute("UPDATE alerts SET status='off' WHERE id=?", (alert_id,))
        _log(con, now, alert_id, event, 0, "off", None, None, cfg.host, None)
        con.commit()
        return {"ok": False, "status": "off"}
    if not cfg.configured:
        con.execute("UPDATE alerts SET status='not_configured' WHERE id=?", (alert_id,))
        _log(con, now, alert_id, event, 0, "not_configured", None, None, None, None)
        _say_daily(con, "not_configured", f"zonewatch: webhook nije postavljen ({cfg.why}); alarmi se spremaju, ništa se "
                                          "ne šalje", now)
        con.commit()
        return {"ok": False, "status": "not_configured"}
    clock = clock or time.time

    def on_attempt(attempt, st, code, ms, err):
        _log(con, clock(), alert_id, event, attempt, st, code, ms, cfg.host, err)
        con.commit()
        print(f"zonewatch: POST {cfg.host} {event} → {code or err} ({ms} ms, pokušaj {attempt})", flush=True)
    res = post(cfg, payload, opener, sleep, clock, on_attempt)
    con.execute("UPDATE alerts SET status=?, attempts=?, http_status=?, posted_ts=? WHERE id=?",
                (res["status"], res["attempts"], res["http_status"], int(clock()), alert_id))
    if res["ok"]:
        store.kv_put(con, "last_post_ok", int(clock()))
    else:
        store.kv_put(con, "last_error", {"ts": int(clock()), "status": res["status"], "http_status": res["http_status"],
                                         "error": res["error"], "alert_id": alert_id})
        if res["status"] == "config_error":
            _say_daily(con, f"config_error:{res['http_status']}",
                       f"zonewatch: webhook odbija ({res['http_status']}): provjeri GROKBOT_WEBHOOK_URL / KEY / AUTH", now)
    con.commit()
    return res


def post_alert(alert, con=None, now=None, cfg=None, flag=None, opener=None, sleep=None, clock=None, path=None):
    """For direct callers (team_catalyst, scripts): normalize the dict (the owner's fields as null when missing; give
    "id" to make a repeat a no-op, and "event"), store it, write it to events.db, POST it now with the retries.
    Never raises; returns {"ok", "status", "id", ...} (status sent | failed | config_error | not_configured | off |
    duplicate | error)."""
    own = con is None
    try:
        payload = normalize(alert, now)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": "error", "error": type(e).__name__}
    try:
        con = con or store.connect(path)
        try:
            new = record(con, payload, "pending", now)
            con.commit()
            res = deliver(con, payload["id"], cfg, flag, now, opener, sleep, clock)
            if not new and res.get("status") == "duplicate":
                res = {"ok": True, "status": "duplicate"}
        finally:
            if own:
                con.close()
    except (sqlite3.Error, OSError) as e:
        return {"ok": False, "status": "error", "id": payload["id"], "error": type(e).__name__}
    return dict(res, id=payload["id"])
