"""Google Analytics 4: the counting tag on the public site (with a consent banner) and the numbers back over the
GA4 Data API into analytics.db for the 📈 Analitika page.

  GA4_MEASUREMENT_ID   G-XXXXXXX from GA4 → Admin → Data streams → Web; without it no tag is added
  GA4_PROPERTY_ID      numeric property id (Admin → Property details); without it nothing is read back
  The read-back uses the same service account as Search Console (GSC_SERVICE_ACCOUNT_JSON); its e-mail must be a
  Viewer of the GA4 property and the "Google Analytics Data API" must be enabled in the same Cloud project.

EU rules: the tag is loaded only after the visitor taps Accept on the banner (choice kept in localStorage), IP
anonymised, no ads signals. Declining loads nothing. Only public pages carry the tag, never the logged-in app.
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
    "en": ("We use Google Analytics cookies to count visits and improve the site. No ads.", "Accept", "Decline"),
    "hr": ("Koristimo Google Analytics kolačiće da brojimo posjete i poboljšamo stranicu. Bez oglasa.", "Prihvati", "Odbij"),
}


def measurement_id():
    m = (os.environ.get("GA4_MEASUREMENT_ID") or "").strip()
    return m if m.startswith("G-") and m[2:].isalnum() else ""


def property_id():
    p = (os.environ.get("GA4_PROPERTY_ID") or "").strip().removeprefix("properties/")
    return p if p.isdigit() else ""


def tag(lang="en"):
    """Consent banner + deferred gtag for public pages; "" when GA4_MEASUREMENT_ID is not set."""
    mid = measurement_id()
    if not mid:
        return ""
    msg, yes, no = TXT.get(lang, TXT["en"])
    return (
        "<div id=cc role=dialog aria-live=polite hidden style='position:fixed;left:12px;right:12px;bottom:12px;z-index:60;"
        "max-width:560px;margin:0 auto;background:#fff;color:#111;border:1px solid #e5e7eb;border-radius:14px;"
        "box-shadow:0 8px 30px rgba(0,0,0,.12);padding:14px 16px;font-size:14px;line-height:1.45'>"
        f"<p style='margin:0 0 10px'>{msg}</p><div style='display:flex;gap:8px;flex-wrap:wrap'>"
        f"<button type=button data-cc=y style='flex:1;min-height:44px;border:0;border-radius:10px;background:#4f46e5;"
        f"color:#fff;font-weight:600;font-size:15px'>{yes}</button>"
        f"<button type=button data-cc=n style='flex:1;min-height:44px;border:1px solid #d1d5db;border-radius:10px;"
        f"background:#fff;color:#111;font-size:15px'>{no}</button></div></div>"
        "<script>(()=>{const K='ms_consent',M=" + json.dumps(mid) + ";let c=null;try{c=localStorage.getItem(K)}catch(e){}"
        "function load(){if(window.gtag)return;window.dataLayer=window.dataLayer||[];window.gtag=function(){dataLayer.push(arguments)};"
        "gtag('js',new Date());gtag('config',M,{anonymize_ip:true,allow_google_signals:false,allow_ad_personalization_signals:false});"
        "const s=document.createElement('script');s.async=1;s.src='https://www.googletagmanager.com/gtag/js?id='+M;document.head.appendChild(s)}"
        "const b=document.getElementById('cc');if(c==='y')load();else if(c!=='n')b.hidden=false;"
        "b.addEventListener('click',e=>{const v=e.target.dataset&&e.target.dataset.cc;if(!v)return;"
        "try{localStorage.setItem(K,v)}catch(e){}b.hidden=true;if(v==='y')load()})})();</script>")


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
