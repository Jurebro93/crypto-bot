"""Google Search Console over its API: how people find memesonar.app on Google (clicks, impressions, queries, pages).

Access is a Google Cloud *service account* (a robot Google account with its own e-mail). Nicholas creates it, adds
its e-mail as a user of the Search Console property and puts the JSON key into the Render env var
GSC_SERVICE_ACCOUNT_JSON (the raw JSON or the same text base64-encoded). Nothing runs until that variable is set.

  GSC_SERVICE_ACCOUNT_JSON   the key (required)
  GSC_SITE                   property, default sc-domain:<host of SITE_URL> (a Domain property, verified by TXT)
  GSC_EVERY_H                refresh interval in hours, default 6 (Google's data lags ~2 days anyway)
  GSC_INSPECT_DAY            URL Inspection calls per day, default 300 (Google allows 2,000/day, 600/min)

collect() stores everything in analytics.db (written only by the UI process): one row per day for the whole site,
and the top queries / pages / countries / devices of the last 28 days and of the 28 days before (for the change).
Google keeps 16 months, we keep the daily totals for good. A failed refresh leaves the last good data in place and
stores the error in plain Croatian for the page to show.
"""
import base64
import datetime as dt
import json
import os
import re
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


def _http(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def _api(path, body=None):
    try:
        return _http(API + path, body)
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        if e.code == 403 and ("has not been used" in msg or "SERVICE_DISABLED" in msg):
            raise GscError("Google Search Console API nije uključen u Google Cloud projektu: APIs & Services → "
                           "Library → Google Search Console API → Enable.")
        if e.code in (403, 404):
            # no e-mail here: this text also goes to the server log (the page shows the e-mail in the setup steps)
            raise GscError(f"Service account nema pristup svojstvu {site()}. U Search Consoleu: Settings → "
                           "Users and permissions → Add user → upiši e-mail računa sa stranice Analitika "
                           "(dovoljno je Restricted).")
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
        CREATE TABLE IF NOT EXISTS gsc_pages (page TEXT PRIMARY KEY, imp_cur REAL, imp_prev REAL,
                                              clicks_cur REAL, clicks_prev REAL);
        CREATE TABLE IF NOT EXISTS gsc_inspect (url TEXT PRIMARY KEY, ts INTEGER, verdict TEXT, coverage_state TEXT,
                                                robots_state TEXT, indexing_state TEXT, page_fetch_state TEXT,
                                                last_crawl TEXT, google_canonical TEXT, user_canonical TEXT);
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


# --- diagnosis: why impressions fell (log lines + the "Indeksiranost" block on the Analitika page) -------------
# Everything below runs after collect() in its own try blocks: a failure here never touches the numbers above.
# Log lines to search for: "gsc dani:", "gsc stranice:", "gsc indeks:", "gsc indeks primjeri".

INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
DAYS_SHOWN = 21
DAYS_EVERY_S = 6 * 3600 - 600     # "at most every 6 h", with a little slack for the 6 h refresh loop
SECTIONS = [("/telegram/*", ("telegram", "telegram-channels", "telegram-kanali")),
            ("/coin/*", ("coin",)),
            ("/influencer/*", ("influencer", "influencers", "influenceri")),
            ("/macro-influencer/*", ("macro-influencer", "macro-influencers", "makro-influencer", "makro-influenceri")),
            ("/glossary/*", ("glossary", "rjecnik")),
            ("/blog/*", ("blog",)),
            ("/how-to-buy/*", ("how-to-buy", "kako-kupiti")),
            ("/rug-check/*", ("rug-check", "provjera")),
            ("naslovnica", ("",))]
BAD_WORDS = ("noindex", "5xx", "401", "robots", "redirect")
EXAMPLES = 15


class InspectStop(GscError):
    """URL Inspection cannot go on this run (403, 429, network, sign-in); message is one plain Croatian log line."""


def base_url():
    """Public origin whose URLs we inspect (must belong to the property)."""
    s = (os.environ.get("SITE_URL") or "").strip().rstrip("/")
    if s:
        return s
    st = site()
    return st.rstrip("/") if st.startswith("http") else "https://" + st.removeprefix("sc-domain:")


def section(url):
    """Section name of a page by its first path segment; the /hr/ twin counts with its English section."""
    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    if parts and parts[0] == "hr":
        parts = parts[1:]
    seg = parts[0] if parts else ""
    for name, segs in SECTIONS:
        if seg in segs:
            return name
    return "ostalo"


def _path(url):
    p = urllib.parse.urlparse(url)
    return (p.path or "/") + (("?" + p.query) if p.query else "")


def days_lines(path=None, today=None, force=False):
    """[series line, lag line] for the last 21 days (missing day = 0: Google returns no row for a day without
    impressions); [] when the series has not changed or was logged less than 6 h ago."""
    today = today or dt.date.today()
    con = connect(path)
    try:
        have = dict((d, (i, c)) for d, i, c in con.execute("SELECT day, impressions, clicks FROM gsc_daily"))
        days = [today - dt.timedelta(days=n) for n in range(DAYS_SHOWN, 0, -1)]
        line = "gsc dani: " + "; ".join(
            f"{d} i={have.get(str(d), (0, 0))[0] or 0:.0f} k={have.get(str(d), (0, 0))[1] or 0:.0f}" for d in days)
        m = meta(con)
        if not force and (m.get("dani_sig") == line or time.time() - float(m.get("dani_ts") or 0) < DAYS_EVERY_S):
            return []
        _set(con, dani_sig=line, dani_ts=int(time.time()))
        con.commit()
        return [line, "gsc: zadnja 3 dana su nepotpuna (kašnjenje Googlea)"]
    finally:
        con.close()


def week_periods(today=None):
    """(cur_start, cur_end, prev_start, prev_end): the last 7 complete days (LAG_DAYS respected) and the 7 before."""
    today = today or dt.date.today()
    end = today - dt.timedelta(days=LAG_DAYS + 1)
    start = end - dt.timedelta(days=6)
    return start, end, start - dt.timedelta(days=7), start - dt.timedelta(days=1)


def pages_lines(path=None, today=None, q=None):
    """Pages by impressions, last 7 complete days against the 7 before, into gsc_pages; one log line."""
    q = q or query
    cs, ce, ps, pe = week_periods(today)
    try:
        cur = q(cs, ce, ("page",), 1000)
        prev = q(ps, pe, ("page",), 1000)
    except GscError as e:
        return [f"gsc stranice: {e}"]
    rows = {}
    for which, rs in ((0, cur), (1, prev)):
        for r in rs:
            x = rows.setdefault(r["keys"][0], [0, 0, 0, 0])
            x[which] = r.get("impressions") or 0
            x[2 + which] = r.get("clicks") or 0
    con = connect(path)
    try:
        con.execute("DELETE FROM gsc_pages")
        con.executemany("INSERT OR REPLACE INTO gsc_pages VALUES (?,?,?,?,?)", [(k, *v) for k, v in rows.items()])
        _set(con, pages_cur=f"{cs}|{ce}", pages_prev=f"{ps}|{pe}", pages_ts=int(time.time()))
        con.commit()
    finally:
        con.close()
    n = sum(1 for v in rows.values() if v[0] > 0)
    m = sum(1 for v in rows.values() if v[1] > 0)
    lost = sum(1 for v in rows.values() if v[1] > 0 and v[0] <= 0)
    sec = {name: [0, 0, 0, 0] for name in [s_ for s_, _ in SECTIONS] + ["ostalo"]}
    for k, v in rows.items():
        x = sec[section(k)]
        x[0] += v[1] > 0
        x[1] += v[0] > 0
        x[2] += v[1]
        x[3] += v[0]
    parts = ", ".join(f"{name} {a}→{b} (i {pi:.0f}→{ci:.0f})" for name, (a, b, pi, ci) in sec.items())
    return [f"gsc stranice: s impresijama zadnjih 7 d {n} (prije {m}); izgubilo sve impresije {lost}; po sekciji: {parts}"]


def inspect_url(url, site_url=None):
    """One URL Inspection call → indexStatusResult dict. Raises InspectStop (stop this run) or GscError (this URL)."""
    try:
        res = _http(INSPECT_URL, {"inspectionUrl": url, "siteUrl": site_url or site()})
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        if e.code == 403 and ("has not been used" in msg or "SERVICE_DISABLED" in msg):
            raise InspectStop("gsc indeks: Search Console API nije uključen u Google Cloud projektu (APIs & Services → "
                              "Library → Google Search Console API → Enable); pregled indeksa preskočen.")
        if e.code in (401, 403):
            raise InspectStop(f"gsc indeks: service account nema dozvolu za pregled URL-ova svojstva {site()} "
                              f"(HTTP {e.code}); pregled indeksa preskočen.")
        if e.code == 429:
            raise InspectStop("gsc indeks: Google kaže da previše pitamo (limit pregleda URL-ova); nastavak u idućem krugu.")
        raise GscError(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise InspectStop(f"gsc indeks: Google se ne javlja ({e.reason}); nastavak u idućem krugu.")
    except InspectStop:
        raise
    except GscError as e:   # sign-in (token) failed: same plain message as collect(), no key or e-mail in it
        raise InspectStop(f"gsc indeks: {e}")
    except (OSError, ValueError) as e:
        raise InspectStop(f"gsc indeks: Google se ne javlja ({type(e).__name__}); nastavak u idućem krugu.")
    return (res.get("inspectionResult") or {}).get("indexStatusResult") or {}


def hub_urls():
    """Homepage (both languages) and the public hub tables."""
    paths = ["/", "/hr"]
    try:
        from ui import public
        paths += [p for p in public.hub_paths() if p != "/sitemap.xml"]
    except Exception:  # noqa: BLE001
        paths += ["/solana-meme-coins", "/influencers", "/telegram-channels", "/glossary", "/blog"]
    b = base_url()
    return [b + p if p != "/" else b + "/" for p in paths]


def _sitemap_xml():
    """The sitemap text: built in-process by ui/public.py (no network); else fetched from the site once."""
    try:
        from ui import public
        return public.sitemap()
    except Exception:  # noqa: BLE001
        with urllib.request.urlopen(base_url() + "/sitemap.xml", timeout=60) as r:
            return r.read().decode("utf-8", "replace")


def sitemap_urls(con, today, src=None):
    """Sitemap URLs on the public origin, rebuilt once a day and kept in gsc_meta."""
    m = meta(con)
    if m.get("sm_day") == str(today) and m.get("sm_urls"):
        return json.loads(m["sm_urls"])
    xml = (src or _sitemap_xml)()
    b = base_url()
    urls = list(dict.fromkeys(b + _path(u.strip()) for u in re.findall(r"<loc>(.*?)</loc>", xml or "")))
    _set(con, sm_day=today, sm_urls=json.dumps(urls))
    con.commit()
    return urls


def inspect_order(con, today, sitemap=None, cap=None):
    """URLs to inspect now: hubs, then pages that lost all impressions (most previous impressions first), then the
    sitemap, least recently inspected first (a rotation); none already inspected in the last 20 h; at most cap."""
    recent = {u for (u,) in con.execute("SELECT url FROM gsc_inspect WHERE ts >= ?", (int(time.time()) - 20 * 3600,))}
    last = dict(con.execute("SELECT url, ts FROM gsc_inspect"))
    lost = [p for (p,) in con.execute("SELECT page FROM gsc_pages WHERE imp_prev > 0 AND imp_cur <= 0 "
                                      "ORDER BY imp_prev DESC, page")]
    sm = sitemap if sitemap is not None else sitemap_urls(con, today)
    sm = sorted(sm, key=lambda u: last.get(u) or 0)   # stable: never inspected first, in sitemap order
    out = []
    for u in hub_urls() + lost + sm:
        if u not in recent and u not in out:
            out.append(u)
            if cap is not None and len(out) >= cap:
                break
    return out


def _bad(verdict, state, fetch):
    if verdict == "PASS":
        return False
    return (fetch or "") != "SUCCESSFUL" or any(w in (state or "").lower() for w in BAD_WORDS)


def inspect_lines(path=None, today=None, call=None, sleep=time.sleep, sitemap=None, pause=1.0):
    """Today's share of URL Inspection (GSC_INSPECT_DAY, default 300, ~1 per second) into gsc_inspect; log lines."""
    call = call or inspect_url
    today = today or dt.date.today()
    cap = int(os.environ.get("GSC_INSPECT_DAY", "300"))
    con = connect(path)
    try:
        m = meta(con)
        used = int(m.get("inspect_used") or 0) if m.get("inspect_day") == str(today) else 0
        if used >= cap:
            return []
        try:
            todo = inspect_order(con, today, sitemap, cap - used)
        except Exception as e:  # noqa: BLE001
            return [f"gsc indeks: popis stranica nedostupan ({type(e).__name__}); pregled preskočen."]
        done, errors, stop = [], 0, None
        for i, url in enumerate(todo):
            if i:
                sleep(pause)
            try:
                r = call(url)
            except InspectStop as e:
                stop = str(e)
                break
            except GscError:
                errors += 1
                used += 1
                if errors >= 5 and not done:
                    stop = "gsc indeks: Google odbija pregled (5 grešaka zaredom); nastavak u idućem krugu."
                    break
                continue
            used += 1
            row = (url, int(time.time()), r.get("verdict") or "", r.get("coverageState") or "nepoznato",
                   r.get("robotsTxtState") or "", r.get("indexingState") or "", r.get("pageFetchState") or "",
                   r.get("lastCrawlTime") or "", r.get("googleCanonical") or "", r.get("userCanonical") or "")
            con.execute("INSERT OR REPLACE INTO gsc_inspect VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            done.append(row)
            if len(done) % 25 == 0:
                _set(con, inspect_day=today, inspect_used=used)
                con.commit()
        kv = {"inspect_day": today, "inspect_used": used, "inspect_error": stop}
        if done:
            kv["inspect_ok"] = int(time.time())
        _set(con, **kv)
        con.commit()
    finally:
        con.close()
    lines = []
    if done or errors or not stop:
        counts = {}
        for row in done:
            counts[row[3]] = counts.get(row[3], 0) + 1
        txt = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append(f"gsc indeks: pregledano {len(done)}; {txt or 'nema rezultata'}"
                     + (f"; greške {errors}" if errors else ""))
        ex = {}
        for url, _, verdict, state, _, _, fetch, *_ in done:
            if _bad(verdict, state, fetch):
                ex.setdefault(state, []).append(_path(url))
        for state, us in sorted(ex.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"gsc indeks primjeri {state}: " + ", ".join(us[:EXAMPLES]))
    if stop:
        lines.append(stop)
    return lines


def diagnose(path=None, today=None, q=None, call=None, sleep=time.sleep, sitemap=None):
    """The three diagnosis steps, each on its own: returns the log lines, never raises."""
    out = []
    for name, fn in (("dani", lambda: days_lines(path, today)),
                     ("stranice", lambda: pages_lines(path, today, q)),
                     ("indeks", lambda: inspect_lines(path, today, call, sleep, sitemap))):
        try:
            out += fn()
        except Exception as e:  # noqa: BLE001  (type only: a message could carry request details)
            out.append(f"gsc {name}: neočekivana greška {type(e).__name__}")
    return out


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
        try:
            for line in diagnose():
                print(line, flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"gsc dijagnoza: neočekivana greška {type(e).__name__}", flush=True)
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
