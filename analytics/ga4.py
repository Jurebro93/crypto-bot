"""Google Analytics 4: the counting tag on the public site (with a consent banner) and the numbers back over the
GA4 Data API into analytics.db for the 📈 Analitika page.

  GA4_ID               G-XXXXXXX from GA4 → Admin → Data streams → Web (GA4_MEASUREMENT_ID still works)
  GTM_ID               GTM-XXXXXX, Google Tag Manager container; with neither set no banner and no tag is added
  GA4_PROPERTY_ID      numeric property id (Admin → Property details); without it nothing is read back
  The read-back uses the same service account as Search Console (GSC_SERVICE_ACCOUNT_JSON); its e-mail must be a
  Viewer of the GA4 property and the "Google Analytics Data API" must be enabled in the same Cloud project.

EU rules (28.11.: Google Consent Mode v2, every default denied): nothing from Google loads before the visitor taps
Accept on the banner (choice kept in the first-party cookie ms_consent, 180 days), IP anonymised, no ads signals.
Declining loads nothing. Only public pages carry the tag, never the logged-in app.
"""
import datetime as dt
import json
import os
import threading
import time
import urllib.error
import urllib.request

from analytics import gsc

SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
API = "https://analyticsdata.googleapis.com/v1beta"
PERIOD = 28

TXT = {
    "en": ("We use Google Analytics cookies only with your consent, to count visits and improve the site. No ads.",
           "Accept", "Decline", "Cookie settings"),
    "hr": ("Kolačiće Google Analyticsa koristimo samo uz tvoj pristanak, da brojimo posjete i poboljšamo stranicu. "
           "Bez oglasa.", "Prihvati", "Odbij", "Postavke kolačića"),
}
COOKIE = "ms_consent"           # y = accepted, n = declined; 180 days, first-party, no tracking in it
COOKIE_DAYS = 180


def measurement_id():
    """GA4_ID (28.11.), else the older GA4_MEASUREMENT_ID; "" unless it looks like G-XXXX."""
    m = (os.environ.get("GA4_ID") or os.environ.get("GA4_MEASUREMENT_ID") or "").strip()
    return m if m.startswith("G-") and m[2:].isalnum() else ""


def gtm_id():
    """GTM_ID (28.11.): GTM-XXXX; "" otherwise (then no Tag Manager)."""
    m = (os.environ.get("GTM_ID") or "").strip()
    return m if m.startswith("GTM-") and m[4:].isalnum() else ""


def property_id():
    p = (os.environ.get("GA4_PROPERTY_ID") or "").strip().removeprefix("properties/")
    return p if p.isdigit() else ""


# 28.11. (vlasnik: GA4 + GTM, EU banner, Google Consent Mode v2 defaults denied): nothing from Google is fetched before
# the visitor taps Accept. The inline part only sets the consent defaults (all denied) in a local dataLayer; Accept
# writes the cookie, updates analytics_storage to granted (ads stay denied) and only then adds gtag.js / gtm.js.
# Decline writes the cookie and loads nothing. A link with data-cc-open reopens the banner.
JS = (
    "(()=>{const K=%(cookie)s,G=%(ga)s,T=%(gtm)s,D=%(days)d;"
    "window.dataLayer=window.dataLayer||[];window.gtag=window.gtag||function(){dataLayer.push(arguments)};"
    "gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',"
    "analytics_storage:'denied',functionality_storage:'denied',personalization_storage:'denied',"
    "security_storage:'granted',wait_for_update:500});gtag('set','ads_data_redaction',true);"
    "const get=()=>{const m=document.cookie.match(new RegExp('(?:^|; )'+K+'=([yn])'));return m?m[1]:null};"
    "const put=v=>{document.cookie=K+'='+v+'; Max-Age='+(D*86400)+'; Path=/; SameSite=Lax'+"
    "(location.protocol==='https:'?'; Secure':'')};"
    "let done=0;const load=()=>{if(done)return;done=1;"
    "gtag('consent','update',{analytics_storage:'granted'});"
    "if(G){gtag('js',new Date());gtag('config',G,{anonymize_ip:true,allow_google_signals:false,"
    "allow_ad_personalization_signals:false});const s=document.createElement('script');s.async=1;"
    "s.src='https://www.googletagmanager.com/gtag/js?id='+G;document.head.appendChild(s)}"
    "if(T){dataLayer.push({'gtm.start':Date.now(),event:'gtm.js'});const s=document.createElement('script');"
    "s.async=1;s.src='https://www.googletagmanager.com/gtm.js?id='+T;document.head.appendChild(s)}};"
    "const b=document.getElementById('cc');const c=get();if(c==='y')load();else if(c!=='n')b.hidden=false;"
    "b.addEventListener('click',e=>{const v=e.target.dataset&&e.target.dataset.cc;if(!v)return;put(v);"
    "b.hidden=true;if(v==='y')load()});"
    "document.addEventListener('click',e=>{const a=e.target.closest&&e.target.closest('[data-cc-open]');"
    "if(a){e.preventDefault();b.hidden=false}})})();")


def enabled():
    return bool(measurement_id() or gtm_id())


def tag(lang="en"):
    """Consent banner + consent-gated gtag / GTM for public pages; "" when neither GA4_ID nor GTM_ID is set."""
    mid, gid = measurement_id(), gtm_id()
    if not (mid or gid):
        return ""
    msg, yes, no, _settings = TXT.get(lang, TXT["en"])
    js = JS % {"cookie": json.dumps(COOKIE), "ga": json.dumps(mid), "gtm": json.dumps(gid), "days": COOKIE_DAYS}
    return (
        "<div id=cc role=dialog aria-live=polite aria-label=Cookies hidden style='position:fixed;left:12px;right:12px;"
        "bottom:12px;z-index:200;max-width:560px;margin:0 auto;background:#fff;color:#111;border:1px solid #e5e7eb;"
        "border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.12);padding:14px 16px;font-size:14px;line-height:1.45'>"
        f"<p style='margin:0 0 10px'>{msg}</p><div style='display:flex;gap:8px;flex-wrap:wrap'>"
        f"<button type=button data-cc=y style='flex:1;min-height:44px;border:0;border-radius:10px;background:#4f46e5;"
        f"color:#fff;font-weight:600;font-size:15px;cursor:pointer'>{yes}</button>"
        f"<button type=button data-cc=n style='flex:1;min-height:44px;border:1px solid #d1d5db;border-radius:10px;"
        f"background:#fff;color:#111;font-size:15px;cursor:pointer'>{no}</button></div></div>"
        f"<script>{js}</script>")


def settings_link(lang="en"):
    """Footer link that reopens the banner; "" when no tag is configured."""
    if not enabled():
        return ""
    return f"<a href=# data-cc-open>{TXT.get(lang, TXT['en'])[3]}</a>"


# --- Data API ---------------------------------------------------------------------------------------------------

def report(start, end, dims, metrics, limit=1000):
    """runReport rows as [{"keys": [...], "vals": [...]}]."""
    body = {"dateRanges": [{"startDate": str(start), "endDate": str(end)}],
            "dimensions": [{"name": d} for d in dims], "metrics": [{"name": m} for m in metrics], "limit": limit}
    if metrics:
        body["orderBys"] = [{"metric": {"metricName": metrics[0]}, "desc": True}] if dims != ("date",) else \
            [{"dimension": {"dimensionName": "date"}}]
    req = urllib.request.Request(f"{API}/properties/{property_id()}:runReport", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + gsc.token(SCOPE), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        if e.code == 403 and ("has not been used" in msg or "SERVICE_DISABLED" in msg):
            raise gsc.GscError("Google Analytics Data API nije uključen: Google Cloud → APIs & Services → Library → "
                               "Google Analytics Data API → Enable.")
        if e.code in (403, 404):
            raise gsc.GscError(f"Račun {gsc.account_email()} nema pristup GA4 svojstvu {property_id()}. U GA4: Admin → "
                               "Property access management → + → upiši taj e-mail, uloga Viewer.")
        if e.code == 400:
            raise gsc.GscError("GA4_PROPERTY_ID nije ispravan: to je broj iz GA4 → Admin → Property details (ne G-…).")
        raise gsc.GscError(f"GA4 API greška (HTTP {e.code}).")
    except urllib.error.URLError as e:
        raise gsc.GscError(f"Google se ne javlja ({e.reason}); idući pokušaj sam.")
    return [{"keys": [d["value"] for d in r.get("dimensionValues", [])],
             "vals": [float(m["value"]) for m in r.get("metricValues", [])]} for r in res.get("rows", [])]


DAILY = ("activeUsers", "sessions", "screenPageViews", "engagementRate")
TOPS = {"page": (("pagePath",), 100), "source": (("sessionSourceMedium",), 50), "country": (("country",), 50)}
TOP_M = ("activeUsers", "sessions", "screenPageViews")


def connect(path=None):
    con = gsc.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS ga_daily (day TEXT PRIMARY KEY, users REAL, sessions REAL, views REAL, engaged REAL);
        CREATE TABLE IF NOT EXISTS ga_top (kind TEXT, key TEXT, users REAL, sessions REAL, views REAL,
                                           PRIMARY KEY (kind, key));
    """)
    return con


def collect(path=None, today=None, rep=None):
    rep = rep or report
    today = today or dt.date.today()
    con = connect(path)
    try:
        have = con.execute("SELECT COUNT(*) FROM ga_daily").fetchone()[0]
        try:
            daily = rep(today - dt.timedelta(days=400 if not have else 35), today - dt.timedelta(days=1), ("date",), DAILY, 1000)
            tops = {k: rep(today - dt.timedelta(days=PERIOD), today - dt.timedelta(days=1), d, TOP_M, n)
                    for k, (d, n) in TOPS.items()}
        except gsc.GscError as e:
            gsc._set(con, ga_error=str(e), ga_try=int(time.time()))
            con.commit()
            raise
        con.executemany("INSERT OR REPLACE INTO ga_daily VALUES (?,?,?,?,?)",
                        [(f"{r['keys'][0][:4]}-{r['keys'][0][4:6]}-{r['keys'][0][6:]}", *r["vals"]) for r in daily])
        con.execute("DELETE FROM ga_top")
        con.executemany("INSERT OR REPLACE INTO ga_top VALUES (?,?,?,?,?)",
                        [(k, r["keys"][0], *r["vals"]) for k, rows in tops.items() for r in rows])
        gsc._set(con, ga_ok=int(time.time()), ga_try=int(time.time()), ga_error=None)
        con.commit()
        return len(daily)
    finally:
        con.close()


def configured():
    return bool(property_id() and gsc.configured())


def _loop(every_s):
    time.sleep(float(os.environ.get("GSC_START_DELAY_S", "90")) + 30)
    while True:
        try:
            print(f"ga4: {collect()} dana spremljeno", flush=True)
        except gsc.GscError as e:
            print(f"ga4: {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"ga4: neočekivana greška {e!r}", flush=True)
        time.sleep(every_s)


def start():
    if not configured():
        return False
    threading.Thread(target=_loop, args=(float(os.environ.get("GSC_EVERY_H", "6")) * 3600,), daemon=True,
                     name="ga4").start()
    return True
