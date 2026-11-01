"""Google Search Console over its API: how people find memesonar.app on Google (clicks, impressions, queries, pages).

Access is a Google Cloud *service account* (a robot Google account with its own e-mail). Nicholas creates it, adds
its e-mail as a user of the Search Console property and puts the JSON key into the Render env var
GSC_SERVICE_ACCOUNT_JSON (the raw JSON or the same text base64-encoded). Nothing runs until that variable is set.

  GSC_SERVICE_ACCOUNT_JSON   the key (required)
  GSC_SITE                   property, default sc-domain:<host of SITE_URL> (a Domain property, verified by TXT)
  GSC_EVERY_H                refresh interval in hours, default 6 (Google's data lags ~2 days anyway)

collect() stores everything in analytics.db (written only by the UI process): one row per day for the whole site,
and the top queries / pages / countries / devices of the last 28 days and of the 28 days before (for the change).
Google keeps 16 months, we keep the daily totals for good. A failed refresh leaves the last good data in place and
stores the error in plain Croatian for the page to show.
"""
import base64
import datetime as dt
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("ANALYTICS_DB", os.path.join(HERE, "analytics.db"))
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://www.googleapis.com/webmasters/v3"
TOKEN_URI = "https://oauth2.googleapis.com/token"
LAG_DAYS = 2          # Search Console's numbers for the last ~2 days are incomplete
TOP = {"query": 250, "page": 250, "country": 50, "device": 5}
PERIOD = 28
_tok = {}   # scope -> {"value", "exp"}
_lock = threading.Lock()


class GscError(Exception):
    """Message is plain Croatian, ready for the page."""


# --- configuration --------------------------------------------------------------------------------------------

def key_info():
    """The service account key as a dict, None when the variable is not set. Raises GscError if it is unreadable."""
    raw = (os.environ.get("GSC_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        return None
    if not raw.startswith("{"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:  # noqa: BLE001
            raise GscError("GSC_SERVICE_ACCOUNT_JSON nije ispravan: zalijepi cijeli sadržaj JSON datoteke (počinje s {).")
    try:
        info = json.loads(raw)
    except ValueError:
        raise GscError("GSC_SERVICE_ACCOUNT_JSON nije ispravan JSON: zalijepi cijeli sadržaj datoteke, bez rezanja.")
    if info.get("type") != "service_account" or not info.get("private_key") or not info.get("client_email"):
        raise GscError("Ovo nije ključ service accounta: u Google Cloudu otvori service account → Keys → Add key → JSON.")
    return info


def configured():
    return bool((os.environ.get("GSC_SERVICE_ACCOUNT_JSON") or "").strip())


def account_email():
    try:
        info = key_info()
    except GscError:
        return None
    return info and info["client_email"]


def site():
    s = os.environ.get("GSC_SITE")
    if s:
        return s
    host = urllib.parse.urlparse(os.environ.get("SITE_URL") or "https://memesonar.app").hostname or "memesonar.app"
    return "sc-domain:" + host.removeprefix("www.")


# --- HTTP -----------------------------------------------------------------------------------------------------

def _post_form(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def token(scope=SCOPE):
    """Access token for the service account (signed JWT exchanged at Google), reused until 5 min before expiry.
    The same key serves Search Console and GA4 (analytics/ga4.py), each with its own read-only scope."""
    with _lock:
        t = _tok.get(scope) or {}
        if t.get("value") and time.time() < t["exp"] - 300:
            return t["value"]
        info = key_info()
        if not info:
            raise GscError("Ključ još nije postavljen (GSC_SERVICE_ACCOUNT_JSON na Renderu).")
        from google.auth import crypt, jwt
        now = int(time.time())
        try:
            signer = crypt.RSASigner.from_service_account_info(info)
        except Exception:  # noqa: BLE001
            raise GscError("Privatni ključ u GSC_SERVICE_ACCOUNT_JSON se ne može pročitati: napravi novi JSON ključ.")
        uri = info.get("token_uri") or TOKEN_URI
        assertion = jwt.encode(signer, {"iss": info["client_email"], "scope": scope, "aud": uri,
                                        "iat": now, "exp": now + 3600})
        try:
            res = _post_form(uri, {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": assertion.decode() if isinstance(assertion, bytes) else assertion})
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if "invalid_grant" in body:
                raise GscError("Google je odbio ključ (obrisan ili istekao). Napravi novi JSON ključ i zamijeni ga na Renderu.")
            raise GscError(f"Google prijava nije uspjela (HTTP {e.code}).")
        _tok[scope] = {"value": res["access_token"], "exp": now + int(res.get("expires_in", 3600))}
        return res["access_token"]


def _api(path, body=None):
    url = API + path
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        if e.code == 403 and ("has not been used" in msg or "SERVICE_DISABLED" in msg):
            raise GscError("Google Search Console API nije uključen u Google Cloud projektu: APIs & Services → "
                           "Library → Google Search Console API → Enable.")
        if e.code in (403, 404):
            raise GscError(f"Račun {account_email()} nema pristup svojstvu {site()}. U Search Consoleu: Settings → "
                           "Users and permissions → Add user → upiši taj e-mail (dovoljno je Restricted).")
        if e.code == 429:
            raise GscError("Google kaže da previše pitamo (limit); idući pokušaj za nekoliko sati.")
        raise GscError(f"Search Console API greška (HTTP {e.code}).")
    except urllib.error.URLError as e:
        raise GscError(f"Google se ne javlja ({e.reason}); idući pokušaj sam.")


def sites():
    """Properties this account can read: [(siteUrl, permissionLevel)]."""
    return [(s["siteUrl"], s.get("permissionLevel")) for s in _api("/sites").get("siteEntry", [])]


def query(start, end, dims=(), limit=1000, site_url=None):
    """searchAnalytics.query rows: [{"keys": [...], "clicks", "impressions", "ctr", "position"}]."""
    body = {"startDate": str(start), "endDate": str(end), "dimensions": list(dims), "rowLimit": limit,
            "dataState": "all", "type": "web"}
    path = f"/sites/{urllib.parse.quote(site_url or site(), safe='')}/searchAnalytics/query"
    return _api(path, body).get("rows", [])


# --- storage --------------------------------------------------------------------------------------------------

def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS gsc_daily (day TEXT PRIMARY KEY, clicks REAL, impressions REAL, ctr REAL, position REAL);
        CREATE TABLE IF NOT EXISTS gsc_top (kind TEXT, period TEXT, key TEXT, clicks REAL, impressions REAL,
                                            ctr REAL, position REAL, PRIMARY KEY (kind, period, key));
        CREATE TABLE IF NOT EXISTS gsc_meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    return con


def meta(con):
    return dict(con.execute("SELECT k, v FROM gsc_meta"))


def _set(con, **kv):
    con.executemany("INSERT OR REPLACE INTO gsc_meta VALUES (?,?)", [(k, None if v is None else str(v)) for k, v in kv.items()])


def periods(today=None):
    """(cur_start, cur_end, prev_start, prev_end): the last 28 complete days and the 28 before them."""
    today = today or dt.date.today()
    end = today - dt.timedelta(days=LAG_DAYS + 1)
    start = end - dt.timedelta(days=PERIOD - 1)
    pend = start - dt.timedelta(days=1)
    return start, end, pend - dt.timedelta(days=PERIOD - 1), pend


def collect(path=None, today=None, q=None):
    """One refresh into analytics.db. Returns the number of daily rows stored; raises GscError (also stored)."""
    q = q or query
    today = today or dt.date.today()
    con = connect(path)
    try:
        have = con.execute("SELECT COUNT(*) FROM gsc_daily").fetchone()[0]
        first = today - dt.timedelta(days=486 if not have else 35)   # first run: all 16 months Google keeps
        try:
            daily = q(first, today, ("date",), 25000)
            cs, ce, ps, pe = periods(today)
            tops = {}
            for kind, n in TOP.items():
                tops[(kind, "cur")] = q(cs, ce, (kind,), n)
                tops[(kind, "prev")] = q(ps, pe, (kind,), n)
        except GscError as e:
            _set(con, last_error=str(e), last_try=int(time.time()))
            con.commit()
            raise
        con.executemany("INSERT OR REPLACE INTO gsc_daily VALUES (?,?,?,?,?)",
                        [(r["keys"][0], r["clicks"], r["impressions"], r["ctr"], r["position"]) for r in daily])
        con.execute("DELETE FROM gsc_top")
        con.executemany("INSERT OR REPLACE INTO gsc_top VALUES (?,?,?,?,?,?,?)",
                        [(kind, per, r["keys"][0], r["clicks"], r["impressions"], r["ctr"], r["position"])
                         for (kind, per), rows in tops.items() for r in rows])
        _set(con, last_ok=int(time.time()), last_try=int(time.time()), last_error=None, site=site(),
             cur=f"{cs}|{ce}", prev=f"{ps}|{pe}")
        con.commit()
        return len(daily)
    finally:
        con.close()


def _loop(every_s):
    time.sleep(float(os.environ.get("GSC_START_DELAY_S", "90")))
    while True:
        try:
            n = collect()
            print(f"gsc: {n} dana spremljeno", flush=True)
        except GscError as e:
            print(f"gsc: {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"gsc: neočekivana greška {e!r}", flush=True)
        time.sleep(every_s)


def start():
    """Background refresh in the UI process (analytics.db's only writer); does nothing without the key."""
    if not configured():
        return False
    threading.Thread(target=_loop, args=(float(os.environ.get("GSC_EVERY_H", "6")) * 3600,), daemon=True,
                     name="gsc").start()
    return True


if __name__ == "__main__":   # python3 -m analytics.gsc  → check access and refresh once
    print("račun:", account_email(), "| svojstvo:", site())
    print("pristup:", sites())
    print("spremljeno dana:", collect())
