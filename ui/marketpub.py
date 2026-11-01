"""Public market pages built from market.db (DefiLlama volumes, the market regime) and kol.db (hourly volume of called
tokens, outcome of influencer calls by hour). English main, Croatian under /hr, hreflang pairs:

  /solana-market               /hr/solana-trziste                      dashboard: heat index, volumes, 90-day trend
  /solana-launchpads           /hr/solana-launchpadi                   pump.fun vs LaunchLab (bonk.fun) vs Meteora DBC
  /best-time-to-trade-crypto   /hr/najbolje-vrijeme-za-trgovanje-kriptom   volume and call results by hour and session
  /meme-coin-season-index      /hr/indeks-sezone-meme-coina            the regime score as a 0-100 index, 1 year history
  /solana-dex-volume           /hr/solana-dex-volumen                  top Solana DEXs and trading terminals
  /embed/<chart>, /hr/embed/<chart>                                    small iframe widgets (noindex) linking back here

Only aggregated numbers go public: no fresh signals, tokens, wallets or our own trades. Everything is computed once in
snapshot() and kept for CACHE_S, so a page view never scans the databases (public.route caches the HTML on top).
"""
import datetime as dt
import json
import os
import sqlite3
import threading
import time

from ui.html import esc

D, H = 86400, 3600
CACHE_S = int(os.environ.get("MARKET_PUBLIC_CACHE_S", "1800"))
HIT_X = 0.5                     # an influencer call "worked" when the price rose 50%+ within 24 h (same as everywhere)
MIN_HOUR_N = 15                 # hours with fewer measured calls are shown greyed out
SESSIONS = [("asia", 0, 8), ("eu", 8, 14), ("us", 14, 24)]
C1, C2, C3, C4, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#c3c7d0"
COLD, HOT = "#2a78d6", "#eb6834"

PAGES = {
    "market": ("/solana-market", "/hr/solana-trziste"),
    "launchpads": ("/solana-launchpads", "/hr/solana-launchpadi"),
    "besttime": ("/best-time-to-trade-crypto", "/hr/najbolje-vrijeme-za-trgovanje-kriptom"),
    "season": ("/meme-coin-season-index", "/hr/indeks-sezone-meme-coina"),
    "dex": ("/solana-dex-volume", "/hr/solana-dex-volumen"),
}
EMBEDS = ("meme-season", "launchpads")

# What a DefiLlama platform is, for people who trade meme coins. Only the well-known ones get a description.
LABEL = {
    "pump.fun": ("pump.fun", "the biggest meme coin launchpad, bonding curve", "najveći launchpad za meme coine, bonding curve"),
    "launchlab": ("LaunchLab (bonk.fun)", "Raydium's launchpad, used by bonk.fun / LetsBonk",
                  "Raydiumov launchpad, koristi ga bonk.fun / LetsBonk"),
    "meteora-dynamic-bonding-curve": ("Meteora DBC", "Meteora's bonding curve, used by Bags, Believe and Jupiter Studio",
                                      "Meteorina bonding curve, koriste je Bags, Believe i Jupiter Studio"),
    "pumpswap": ("PumpSwap", "where pump.fun coins trade after graduation", "gdje se pump.fun coini trguju nakon graduacije"),
    "raydium-amm": ("Raydium AMM", "", ""), "orca-dex": ("Orca", "", ""), "meteora-dlmm": ("Meteora DLMM", "", ""),
    "moonshot.money": ("Moonshot", "", ""), "axiom": ("Axiom", "", ""), "gmgn": ("GMGN", "", ""),
    "photon": ("Photon", "", ""), "trojan": ("Trojan", "", ""), "bonkbot": ("BONKbot", "", ""),
}

T = {
    "en": dict(
        nav="Market", nav_d="Solana meme coin market data, updated daily",
        asof="Data as of {d} (last full UTC day). Source: DefiLlama, checked every hour. Updated automatically.",
        hot="hot", neutral="neutral", cold="cold", idx="Meme coin season index",
        lp="Launchpads", dexn="Solana DEX", term="Trading terminals", sol="SOL price",
        lp7="Launchpad volume, 7 days", dex7="Solana DEX volume, 7 days", term7="Trading terminals & bots, 7 days",
        share="Launchpad share of all Solana DEX volume", solp="SOL price (7-day change)",
        vs="vs the week before", yday="Last full day", d7="7 days", chg="Change 7d", sh="Share", m30="Trend 30d", v30="30 days",
        platform="Platform", what="What it is", day="Day", chg1="Change",
        more_h="More market data", embed_h="Embed this chart", embed_p="Free to use on your site or blog. "
        "It updates itself every day and links back to the source.", copy="Copy code", copied="Copied",
        table="Show as table", lock="Members see which new tokens are getting volume right now, which influencers "
        "called them and how their calls played out, live.", cta="Request access", faq="Frequently asked questions",
        nf="Not financial advice. Volumes are what DefiLlama reports for Solana; a platform listed here is data, "
           "not a recommendation.", tz="Show times in", your="your time", local="Your time",
        nodata="Market data is not available yet. It is collected automatically every hour.",
        crumb="Market"),
    "hr": dict(
        nav="Tržište", nav_d="Podaci o Solana meme coin tržištu, svaki dan",
        asof="Podaci za {d} (zadnji puni UTC dan). Izvor: DefiLlama, provjera svaki sat. Osvježava se samo.",
        hot="vruće", neutral="neutralno", cold="hladno", idx="Indeks sezone meme coina",
        lp="Launchpadi", dexn="Solana DEX", term="Trading terminali", sol="Cijena SOL",
        lp7="Volumen launchpada, 7 dana", dex7="Volumen Solana DEX-a, 7 dana", term7="Trading terminali i botovi, 7 dana",
        share="Udio launchpada u ukupnom Solana DEX volumenu", solp="Cijena SOL (promjena 7 dana)",
        vs="u odnosu na tjedan prije", yday="Zadnji puni dan", d7="7 dana", chg="Promjena 7 d", sh="Udio", m30="Trend 30 d", v30="30 dana",
        platform="Platforma", what="Što je to", day="Dan", chg1="Promjena",
        more_h="Još podataka o tržištu", embed_h="Ugradi ovaj graf", embed_p="Besplatno za tvoju stranicu ili blog. "
        "Osvježava se sam svaki dan i vodi natrag na izvor.", copy="Kopiraj kod", copied="Kopirano",
        table="Prikaži kao tablicu", lock="Članovi uživo vide koji novi tokeni upravo dobivaju volumen, koji su ih "
        "influenceri pozvali i kako su prošli njihovi pozivi.", cta="Zatraži pristup", faq="Česta pitanja",
        nf="Nije financijski savjet. Volumeni su ono što DefiLlama prijavljuje za Solanu; platforma na popisu je podatak, "
           "a ne preporuka.", tz="Prikaži vrijeme za", your="tvoje vrijeme", local="Tvoje vrijeme",
        nodata="Podaci o tržištu još nisu dostupni. Skupljaju se automatski svaki sat.",
        crumb="Tržište"),
}

# page key -> (nav label, nav description) per language
NAV = {
    "en": {"market": ("Market today", "Launchpad, DEX and terminal volume, 90-day trend"),
           "season": ("Meme coin season index", "Is it meme season? 0-100, daily"),
           "launchpads": ("Solana launchpads", "pump.fun vs bonk.fun vs Meteora"),
           "dex": ("Solana DEX volume", "Top DEXs and trading terminals"),
           "besttime": ("Best time to trade", "Volume and call results by hour")},
    "hr": {"market": ("Tržište danas", "Volumeni launchpada, DEX-a i terminala, trend 90 dana"),
           "season": ("Indeks sezone meme coina", "Je li sezona meme coina? 0-100, dnevno"),
           "launchpads": ("Solana launchpadi", "pump.fun protiv bonk.fun i Meteore"),
           "dex": ("Solana DEX volumen", "Najveći DEX-ovi i trading terminali"),
           "besttime": ("Najbolje vrijeme za trgovanje", "Volumen i uspjeh poziva po satu")},
}

SESSION_NAMES = {"en": {"asia": "Asia", "eu": "Europe", "us": "United States"},
                 "hr": {"asia": "Azija", "eu": "Europa", "us": "SAD"}}

# ---------- data ----------------------------------------------------------------------------------------------------

_lock = threading.Lock()
_cache = {"t": 0.0, "d": None}


def snapshot(force=False):
    """All numbers the pages need, rebuilt at most every CACHE_S seconds. None when market.db has no data yet."""
    now = time.time()
    with _lock:
        if not force and _cache["d"] is not None and now - _cache["t"] < CACHE_S:
            return _cache["d"]
    try:
        d = build()
    except Exception as e:  # noqa: BLE001  (keep serving the last good numbers)
        print(f"marketpub: {type(e).__name__}: {e}", flush=True)
        d = _cache["d"]
    with _lock:
        _cache.update(t=now, d=d)
    return d


def _plats(con, grp, day):
    rows = con.execute("SELECT d.slug, p.name, d.day, d.volume FROM daily d JOIN platforms p ON p.slug=d.slug "
                       "WHERE p.grp=? AND d.day>?", (grp, day - 60 * D)).fetchall()
    by = {}
    for slug, name, d, v in rows:
        by.setdefault(slug, {"slug": slug, "name": name, "s": {}})["s"][d] = v or 0.0
    out = []
    for p in by.values():
        s = p["s"]
        v7 = sum(s.get(day - i * D, 0) for i in range(7))
        p7 = sum(s.get(day - (7 + i) * D, 0) for i in range(7))
        if v7 < 100_000:            # dust platforms stay out of public tables
            continue
        out.append({"slug": p["slug"], "name": p["name"], "y1": s.get(day), "v7": v7, "p7": p7,
                    "v30": sum(s.get(day - i * D, 0) for i in range(30)),
                    "spark": [s.get(day - i * D, 0) for i in range(29, -1, -1)]})
    out.sort(key=lambda x: -x["v7"])
    return out


def _shares_over_time(con, day, slugs, weeks=26):
    """Weekly points: each top launchpad's share of all launchpad volume in the 7 days ending that day."""
    rows = con.execute("SELECT d.slug, d.day, d.volume FROM daily d JOIN platforms p ON p.slug=d.slug "
                       "WHERE p.grp='launchpad' AND d.day>?", (day - (weeks * 7 + 7) * D,)).fetchall()
    vol = {}
    for slug, d, v in rows:
        vol[(slug, d)] = v or 0.0
    tot = {}
    for (slug, d), v in vol.items():
        tot[d] = tot.get(d, 0.0) + v
    pts = []
    for w in range(weeks - 1, -1, -1):
        end = day - w * 7 * D
        t7 = sum(tot.get(end - i * D, 0) for i in range(7))
        if not t7:
            continue
        sh = {s: sum(vol.get((s, end - i * D), 0) for i in range(7)) / t7 for s in slugs}
        sh["other"] = max(0.0, 1 - sum(sh.values()))
        pts.append((end, sh))
    return pts


def _hours(now):
    """Hour-of-day profile from kol.db: average share of a called token's volume per UTC hour, and how first
    influencer calls did by the UTC hour they were posted (bots excluded, calls older than 24 h only)."""
    from ui import public
    p = public._kol_db()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    try:
        vol, ntok = [0.0] * 24, 0
        try:
            per = {}
            for tok, hr, v in con.execute("SELECT token, hour, volume FROM token_hours WHERE hour BETWEEN 0 AND 23"):
                per.setdefault(tok, {})[hr] = v or 0.0
            for hs in per.values():
                t = sum(hs.values())
                if t > 0:
                    ntok += 1
                    for hr, v in hs.items():
                        vol[hr] += v / t
            vol = [v / ntok for v in vol] if ntok else None
        except sqlite3.OperationalError:
            vol = None
        q = ("SELECT (c.ts / 3600) % 24, COUNT(*), SUM(CASE WHEN c.max24 >= ? THEN 1 ELSE 0 END), MIN(c.ts), MAX(c.ts) "
             "FROM calls c {join} WHERE c.kind='call' AND c.first_by_kol=1 AND c.max24 IS NOT NULL AND c.ts < ? {bot} "
             "GROUP BY 1")
        try:
            rows = con.execute(q.format(join="LEFT JOIN kols k ON k.handle=c.handle", bot="AND COALESCE(k.bot,0)=0"),
                               (HIT_X, now - D)).fetchall()
        except sqlite3.OperationalError:
            rows = con.execute(q.format(join="", bot=""), (HIT_X, now - D)).fetchall()
    finally:
        con.close()
    calls = [[0, 0] for _ in range(24)]
    lo, hi = None, None
    for hr, n, hits, a, b in rows:
        calls[int(hr)] = [n, hits or 0]
        lo = a if lo is None else min(lo, a)
        hi = b if hi is None else max(hi, b)
    if not ntok and not any(n for n, _ in calls):
        return None
    sess = {}
    for s, a, b in SESSIONS:
        n = sum(calls[h][0] for h in range(a, b))
        hits = sum(calls[h][1] for h in range(a, b))
        sess[s] = {"n": n, "hits": hits, "rate": hits / n if n else None,
                   "vol": sum(vol[h] for h in range(a, b)) if vol else None}
    tn = sum(n for n, _ in calls)
    return {"vol": vol, "ntok": ntok, "calls": calls, "n": tn, "rate": sum(h for _, h in calls) / tn if tn else None,
            "from": lo, "to": hi, "sess": sess}


def build(now=None):
    from market import regime, store
    now = now or time.time()
    con = store.ro()
    if con is None:
        return None
    try:
        day = con.execute("SELECT MAX(day) FROM daily WHERE slug='all:launchpad'").fetchone()[0]
        if not day:
            return None
        from market import collect
        dexs = {(d_, "all:dex"): v for d_, v in store.series(con, "all:dex", day - 10 * D)}
        if collect.partial_day(dexs) == day:     # newest day not finished at DefiLlama yet (collect drops it later)
            day -= D
        ser = {k: dict(store.series(con, f"all:{k}", day - 400 * D)) for k in ("launchpad", "dex", "terminal")}
        price = dict(con.execute("SELECT day, usd FROM price WHERE day>?", (day - 400 * D,)))
        reg = [(d, s, lb, json.loads(f or "{}")) for d, s, lb, f in
               con.execute("SELECT day, score, label, features FROM regime WHERE day<=? ORDER BY day", (day,))]
        try:
            hyp = regime.hypothesis(con)
        except Exception:  # noqa: BLE001
            hyp = None
        plats = {g: _plats(con, g, day) for g in ("launchpad", "terminal", "dex")}
        top = [p["slug"] for p in plats["launchpad"][:3]]
        shares = _shares_over_time(con, day, top)
    finally:
        con.close()
    try:
        hours = _hours(now)
    except Exception as e:  # noqa: BLE001
        print(f"marketpub: sati nedostupni: {e}", flush=True)
        hours = None
    return {"day": day, "built": now, "ser": ser, "price": price, "regime": reg, "hyp": hyp, "plats": plats,
            "top_lp": top, "shares": shares, "hours": hours}


# ---------- formatting ----------------------------------------------------------------------------------------------

def _n(s, lang):
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".") if lang == "hr" else s


def usd(x, lang="en"):
    if x is None:
        return "–"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= div:
            return _n(f"${x / div:.2f}{suf}" if div == 1e9 else f"${x / div:.1f}{suf}", lang)
    return _n(f"${x:,.0f}", lang)


def pct(x, lang="en", signed=True, dec=0):
    if x is None:
        return "–"
    return _n(f"{x * 100:+.{dec}f}%" if signed else f"{x * 100:.{dec}f}%", lang)


def _cls(x):
    return "" if x is None else " class=pos" if x > 0 else " class=neg" if x < 0 else ""


def _date(ts, lang, year=True):
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    if lang == "hr":
        return f"{d.day}. {d.month}. {d.year}." if year else f"{d.day}. {d.month}."
    return d.strftime("%b %-d, %Y") if year else d.strftime("%b %-d")


def _month(ts, lang):
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    hr = ("siječanj", "veljača", "ožujak", "travanj", "svibanj", "lipanj", "srpanj", "kolovoz", "rujan", "listopad",
          "studeni", "prosinac")
    return f"{hr[d.month - 1]} {d.year}." if lang == "hr" else d.strftime("%B %Y")


def label(score, lang):
    t = T[lang]
    return t["hot"] if score >= 66 else t["cold"] if score <= 33 else t["neutral"]


def plabel(p, lang):
    x = LABEL.get(p["slug"])
    if not x:
        return esc(p["name"] or p["slug"]), ""
    return esc(x[0]), esc(x[1] if lang == "en" else x[2])


def _sum7(ser, day):
    w = [ser.get(day - i * D) for i in range(7)]
    return sum(w) if all(v is not None for v in w) else None


# ---------- charts --------------------------------------------------------------------------------------------------

CSS = """
.mk{font-variant-numeric:tabular-nums}.mk .asof{color:var(--mut);font-size:14px;margin:-6px 0 22px}
.mk .card .sub{display:block;font-size:13px;margin-top:2px}
.mkg{display:grid;grid-template-columns:300px 1fr;gap:16px;align-items:stretch;margin:0 0 26px}
@media(max-width:820px){.mkg{grid-template-columns:1fr}}
.mkg .cards{grid-template-columns:repeat(3,1fr);margin:0}@media(max-width:520px){.mkg .cards{grid-template-columns:1fr 1fr}}
.gauge{border:1px solid var(--line);border-radius:18px;background:#fff;padding:18px;text-align:center}
.gauge svg{width:100%;max-width:260px;height:auto;display:block;margin:0 auto}
.gauge b{display:block;font-size:44px;letter-spacing:-.03em;line-height:1;margin-top:-6px}
.gauge .gl2{font-size:15px;font-weight:650;text-transform:uppercase;letter-spacing:.06em}.gauge .gt{color:var(--mut);font-size:13px}
.mc{border:1px solid var(--line);border-radius:18px;background:#fff;padding:18px 18px 12px;margin:0 0 18px}
.mc h3{margin:0 0 4px;font-size:17px}.mc .ms{color:var(--mut);font-size:14px;margin:0 0 10px}
.mcl{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--mut);margin:0 0 10px}
.mcl span{display:inline-flex;align-items:center;gap:6px}.mcl i{width:14px;height:3px;border-radius:2px;display:inline-block}
.mcp{position:relative;margin-left:52px;touch-action:pan-y}.mcp svg{display:block;width:100%;overflow:visible}
.mcy{position:absolute;left:-52px;top:0;bottom:0;width:46px}.mcy span{position:absolute;right:0;transform:translateY(-50%);
font-size:11.5px;color:var(--mut)}.mcx{position:relative;height:22px}.mcx span{position:absolute;transform:translateX(-50%);
font-size:11.5px;color:var(--mut);top:6px;white-space:nowrap}.mcx span:first-child{transform:none}
.mcx span:last-child{transform:translateX(-100%)}
.mcv{position:absolute;top:0;width:1px;background:var(--fg);opacity:.35;pointer-events:none;display:none}
.mct{position:absolute;top:0;pointer-events:none;display:none;background:#0b1220;color:#fff;border-radius:10px;
padding:8px 10px;font-size:12.5px;line-height:1.5;white-space:nowrap;z-index:3;box-shadow:0 6px 20px rgba(0,0,0,.15)}
.mct i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.mc details{margin-top:6px;font-size:13px}.mc details summary{cursor:pointer;color:var(--acc)}
.mc details .tw{margin-top:8px;max-height:320px;overflow:auto}.mc details table{font-size:13px}
.hb{display:flex;align-items:flex-end;gap:2px;height:170px;margin-left:0}
.hb>div{flex:1;position:relative;display:flex;align-items:flex-end;height:100%;cursor:default}
.hb>div>em{display:block;width:100%;border-radius:4px 4px 0 0;background:var(--c,#2a78d6);min-height:2px}
.hb>div.lo>em{background:#c3c7d0}.hb>div:hover>em,.hb>div.on>em{filter:brightness(.85)}
.hb>div>span{display:none;position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);background:#0b1220;
color:#fff;border-radius:8px;padding:6px 8px;font-size:12px;white-space:nowrap;z-index:3}.hb>div:hover>span{display:block}
.hx{display:flex;gap:2px;margin-top:4px}.hx span{flex:1;text-align:center;font-size:11px;color:var(--mut)}
@media(max-width:600px){.hx span:nth-child(odd){visibility:hidden}}
.tzr{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 14px;font-size:14px}
.tzr select{font:inherit;border:1px solid var(--line);border-radius:10px;padding:6px 10px;background:#fff}
.shb{display:flex;height:34px;border-radius:10px;overflow:hidden;gap:2px;margin:6px 0 10px}
.shb i{display:block;height:100%}.shb i:first-child{border-radius:10px 0 0 10px}.shb i:last-child{border-radius:0 10px 10px 0}
.cal{display:grid;grid-auto-flow:column;grid-template-rows:repeat(7,1fr);gap:3px;overflow-x:auto;padding-bottom:4px}
.cal i{width:11px;height:11px;border-radius:3px;display:block}
.emb textarea{width:100%;font:13px ui-monospace,Menlo,monospace;border:1px solid var(--line);border-radius:12px;
padding:10px;height:84px;resize:vertical;background:var(--soft)}.emb .btn{margin-top:8px}
.mk .ans a,.mk p.mut a,.mk .ms a,.mk .how a{color:var(--acc);font-weight:600}.spk{vertical-align:middle}.ans{font-size:19px;line-height:1.5;max-width:760px}.ans b{font-weight:720}
.mfaq details{border-bottom:1px solid var(--line);padding:12px 0}.mfaq summary{cursor:pointer;font-weight:650}
.mfaq p{color:var(--mut);margin:8px 0 0;max-width:760px}
"""

JS = """<script>(function(){
function f(v,k){if(v==null||isNaN(v))return'–';var a=Math.abs(v);
if(k=='usd'){return(v<0?'-':'')+(a>=1e9?'$'+(a/1e9).toFixed(2)+'B':a>=1e6?'$'+(a/1e6).toFixed(1)+'M':a>=1e3?'$'+(a/1e3).toFixed(1)+'k':'$'+a.toFixed(0))}
if(k=='pct')return(v*100).toFixed(1)+'%';if(k=='usd2')return'$'+v.toFixed(2);return v.toFixed(0)}
document.querySelectorAll('.mc[data-c]').forEach(function(fig){var c=JSON.parse(fig.getAttribute('data-c'));
var p=fig.querySelector('.mcp'),v=p.querySelector('.mcv'),t=p.querySelector('.mct'),n=c.x.length,hr=document.documentElement.lang=='hr';
function show(e){var r=p.getBoundingClientRect(),x=(e.touches?e.touches[0].clientX:e.clientX)-r.left;
var i=Math.max(0,Math.min(n-1,Math.round(x/r.width*(n-1))));var px=i/(n-1)*r.width;
v.style.display='block';v.style.left=px+'px';v.style.height=(r.height-22)+'px';
var h='<b>'+c.x[i]+'</b>';c.s.forEach(function(s){var y=s.y[i];var raw=s.r?s.r[i]:null;
var val=f(y,c.f);if(raw!=null)val=f(raw,s.rf||'usd')+(c.f=='idx'?' ('+f(y,'idx')+')':'');if(hr)val=val.replace('.',',');
h+='<br><i style="background:'+s.c+'"></i>'+s.n+': '+val});t.innerHTML=h;t.style.display='block';
var w=t.offsetWidth;t.style.left=Math.max(0,Math.min(r.width-w,px+12>r.width-w?px-w-12:px+12))+'px'}
function hide(){v.style.display='none';t.style.display='none'}
p.addEventListener('pointermove',show);p.addEventListener('pointerdown',show);p.addEventListener('pointerleave',hide)});
document.querySelectorAll('.emb button').forEach(function(b){b.addEventListener('click',function(){
var ta=b.parentNode.querySelector('textarea');ta.select();try{navigator.clipboard.writeText(ta.value)}catch(e){document.execCommand('copy')}
b.textContent=b.getAttribute('data-ok')})});
var sel=document.getElementById('tz');if(sel){
function off(z){if(!z)return -new Date().getTimezoneOffset()/60;var d=new Date();
var a=new Date(d.toLocaleString('en-US',{timeZone:z})),b=new Date(d.toLocaleString('en-US',{timeZone:'UTC'}));return Math.round((a-b)/18e5)/2}
function hh(h){h=((h%24)+24)%24;var m=h%1?':30':':00';return String(Math.floor(h)).padStart(2,'0')+m}
function apply(){var o=off(sel.value);document.querySelectorAll('[data-h]').forEach(function(el){var h=+el.getAttribute('data-h');
var l=((h+o)%24+24)%24;if(el.classList.contains('hxl'))el.textContent=String(Math.floor(l));else el.style.order=Math.floor(l);
var tt=el.querySelector('.tl');if(tt)tt.textContent=hh(h+o)+'–'+hh(h+o+1)});
document.querySelectorAll('[data-r]').forEach(function(el){var r=el.getAttribute('data-r').split(',');el.textContent=hh(+r[0]+o)+'–'+hh(+r[1]+o)});
var tzl=document.querySelectorAll('.tzn');tzl.forEach(function(e){e.textContent=sel.options[sel.selectedIndex].text})}
sel.addEventListener('change',apply);apply()}
})();</script>"""


def line_chart(title, sub, xs, series, fmt="usd", lang="en", height=240, guides=(), ymin=None, ymax=None, table_every=1,
               ticks=None):
    """Interactive line chart. series: [(name, color, [y or None], raw or None, raw_fmt)]. One y axis only:
    mixed units are indexed by the caller. guides: [(y, label)] dashed reference lines."""
    t = T[lang]
    ys = [y for _n_, _c, s, *_ in series for y in s if y is not None]
    if len(xs) < 2 or not ys:
        return ""
    lo = min(ys + [g for g, _ in guides]) if ymin is None else ymin
    hi = max(ys + [g for g, _ in guides]) if ymax is None else ymax
    if hi == lo:
        hi = lo + 1
    pad = (hi - lo) * 0.06
    lo, hi = (lo - pad if ymin is None else lo), (hi + pad if ymax is None else hi)
    if fmt == "usd" and ymin is None and lo < 0 <= min(ys):
        lo = 0.0
    W, n = 1000, len(xs)

    def X(i):
        return i * W / (n - 1)

    def Y(v):
        return height * (hi - v) / (hi - lo)

    ticks = ticks or [lo + (hi - lo) * k / 4 for k in range(5)]

    def tf(v):
        if fmt == "usd":
            return usd(v, lang)
        if fmt == "pct":
            return pct(v, lang, signed=False)
        return _n(f"{v:,.0f}", lang)

    svg = [f'<svg viewBox="0 0 {W} {height}" preserveAspectRatio=none height={height} role=img aria-label="{esc(title)}">']
    for v in ticks:
        svg.append(f'<line x1=0 x2={W} y1={Y(v):.1f} y2={Y(v):.1f} stroke="#e8ebf2" vector-effect=non-scaling-stroke />')
    for g, _lab in guides:
        svg.append(f'<line x1=0 x2={W} y1={Y(g):.1f} y2={Y(g):.1f} stroke="#5b6474" stroke-dasharray="4 4" '
                   'vector-effect=non-scaling-stroke />')
    for _name, col, s, *_ in series:
        segs, cur = [], []
        for i, y in enumerate(s):
            if y is None:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append(f"{X(i):.1f},{Y(y):.1f}")
        if cur:
            segs.append(cur)
        for sg in segs:
            svg.append(f'<polyline points="{" ".join(sg)}" fill=none stroke="{col}" stroke-width=2 '
                       'stroke-linejoin=round stroke-linecap=round vector-effect=non-scaling-stroke />')
    svg.append("</svg>")
    yl = "".join(f'<span style="top:{100 * Y(v) / height:.2f}%">{tf(v)}</span>' for v in ticks)
    yl += "".join(f'<span style="top:{100 * Y(g) / height:.2f}%;font-weight:600">{esc(lab)}</span>' for g, lab in guides if lab)
    idx = sorted({0, n // 2, n - 1})
    xl = "".join(f'<span style="left:{100 * i / (n - 1):.2f}%">{esc(xs[i])}</span>' for i in idx)
    legend = ("<div class=mcl>" + "".join(f'<span><i style="background:{c}"></i>{esc(nm)}</span>'
                                          for nm, c, *_ in series) + "</div>") if len(series) > 1 else ""
    data = {"x": xs, "f": fmt, "s": [{"n": nm, "c": c, "y": [None if y is None else round(y, 6) for y in s],
                                       **({"r": raw, "rf": rf} if raw else {})} for nm, c, s, raw, rf in series]}
    rows = "".join("<tr><td>" + esc(xs[i]) + "</td>" + "".join(
        f"<td class=n>{(usd(raw[i], lang) if raw and rf == 'usd' else (_n(f'${raw[i]:.2f}', lang) if raw and raw[i] else '–')) if raw else tf(s[i]) if s[i] is not None else '–'}</td>"
        for _nm, _c, s, raw, rf in series) + "</tr>" for i in range(n - 1, -1, -table_every))
    head = "<th>" + ("Date" if lang == "en" else "Datum") + "</th>" + "".join(f"<th class=n>{esc(nm)}</th>" for nm, *_ in series)
    return (f"<figure class=mc data-c='{esc(json.dumps(data, separators=(',', ':')))}'><h3>{esc(title)}</h3>"
            + (f"<p class=ms>{sub}</p>" if sub else "") + legend
            + f"<div class=mcp><div class=mcy>{yl}</div>{''.join(svg)}<div class=mcx>{xl}</div><i class=mcv></i>"
            f"<div class=mct></div></div><details><summary>{t['table']}</summary><div class=tw><table><thead><tr>{head}"
            f"</tr></thead><tbody>{rows}</tbody></table></div></details></figure>")


def gauge(score, lang, title=None, small=False):
    """Semicircle 0-100: cold (blue) - neutral (grey) - hot (orange), needle at the score, label in text."""
    import math
    t = T[lang]

    def pt(v, r):
        a = math.pi * (1 - v / 100)
        return 100 + r * math.cos(a), 100 - r * math.sin(a)

    arcs = []
    for a, b, col in ((0, 33, COLD), (33.6, 65.4, GREY), (66, 100, HOT)):
        x1, y1 = pt(a, 80)
        x2, y2 = pt(b, 80)
        arcs.append(f'<path d="M{x1:.1f},{y1:.1f} A80,80 0 0 1 {x2:.1f},{y2:.1f}" stroke="{col}" stroke-width=16 fill=none />')
    nx, ny = pt(score, 62)
    lab = label(score, lang)
    return (f"<div class=gauge><svg viewBox='0 0 200 112' role=img aria-label='{esc(t['idx'])} {score:.0f}/100 {lab}'>"
            + "".join(arcs) + f"<line x1=100 y1=100 x2={nx:.1f} y2={ny:.1f} stroke='#0b1220' stroke-width=4 "
            "stroke-linecap=round /><circle cx=100 cy=100 r=7 fill='#0b1220' />"
            "<text x=14 y=111 font-size=10 fill='#5b6474'>0</text><text x=180 y=111 font-size=10 fill='#5b6474'>100</text>"
            f"</svg><b>{score:.0f}</b><div class=gl2>{esc(lab)}</div>"
            + ("" if small else f"<div class=gt>{esc(title or t['idx'])}</div>") + "</div>")


def spark(vals, w=110, h=26):
    vals = [v or 0 for v in vals]
    if len(vals) < 2 or not max(vals):
        return ""
    mx = max(vals)
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - 2 - (h - 4) * v / mx:.1f}" for i, v in enumerate(vals))
    return (f'<svg class=spk width={w} height={h} aria-hidden=true><polyline points="{pts}" fill=none stroke="{C1}" '
            'stroke-width=1.6 stroke-linejoin=round /></svg>')


def _table(head, rows, num_from=1):
    h = "".join(f"<th{' class=n' if j >= num_from else ''}>{x}</th>" for j, x in enumerate(head))
    b = "".join("<tr>" + "".join(f"<td{' class=n' if j >= num_from else ''}>{c}</td>" for j, c in enumerate(r)) + "</tr>"
                for r in rows)
    return f"<div class=tw><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"


def _ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj).replace("</", "<\\/") + "</script>"


def _faq(qa, lang):
    body = "".join(f"<details><summary>{esc(q)}</summary><p>{a}</p></details>" for q, a in qa)
    return f"<h2 class=s>{T[lang]['faq']}</h2><div class=mfaq>{body}</div>"


def _jsonld(key, lang, title, desc, qa, d):
    import re
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    path = PAGES[key][0 if lang == "en" else 1]
    first = d["regime"][0][0] if key == "season" and d["regime"] else d["day"] - 400 * D
    ds = {"@context": "https://schema.org", "@type": "Dataset", "name": title, "description": desc,
          "url": base + path, "isAccessibleForFree": True, "inLanguage": lang,
          "temporalCoverage": f"{dt.datetime.fromtimestamp(first, dt.timezone.utc):%Y-%m-%d}/"
                              f"{dt.datetime.fromtimestamp(d['day'], dt.timezone.utc):%Y-%m-%d}",
          "dateModified": dt.datetime.fromtimestamp(d["built"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
          "creator": {"@type": "Organization", "name": "MemeSonar", "url": base + ("/" if lang == "en" else "/hr")},
          "license": "https://creativecommons.org/licenses/by/4.0/"}
    faq = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)}}
        for q, a in qa]}
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "MemeSonar", "item": base + ("/" if lang == "en" else "/hr")},
        {"@type": "ListItem", "position": 2, "name": T[lang]["crumb"], "item": base + PAGES["market"][lang != "en"]},
        {"@type": "ListItem", "position": 3, "name": NAV[lang][key][0], "item": base + path}]}
    return _ld(ds) + _ld(faq) + _ld(crumbs)


def _gl(slug, lang, text):
    """Link to a public glossary term (EN slug), or the plain text when the term is not public."""
    from ui import glossary_public as GP
    e = GP.BY_EN.get(slug)
    if not e:
        return text
    href = f"/glossary/{e['en']}" if lang == "en" else f"/hr/rjecnik/{e['hr']}"
    return f"<a href={href}>{text}</a>"


def _more(key, lang):
    t = T[lang]
    chips = "".join(f"<a href={PAGES[k][lang != 'en']}>{esc(NAV[lang][k][0])}</a>" for k in NAV[lang] if k != key)
    extra = ([("/solana-meme-coins", "Top 100 Solana meme coins"), ("/solana-meme-coins/gainers", "Top gainers today"),
              ("/best-crypto-tools/trading-bots", "Trading bots compared")] if lang == "en" else
             [("/hr/solana-meme-coini", "Top 100 Solana meme coina"), ("/hr/solana-meme-coini/rastuci", "Najveći rast danas"),
              ("/hr/najbolji-kripto-alati/trading-botovi", "Usporedba trading botova")])
    chips += "".join(f"<a href={h}>{esc(n)}</a>" for h, n in extra)
    return f"<h2 class=s>{t['more_h']}</h2><div class=chips>{chips}</div>"


def _lockbox(lang):
    t = T[lang]
    home = "/" if lang == "en" else "/hr"
    return f"<div class=lock><p>{t['lock']}</p><a class='btn sm' href={home}#pristup>{t['cta']}</a></div>"


def _embed(name, lang):
    t = T[lang]
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    src = f"{base}{'/hr' if lang == 'hr' else ''}/embed/{name}"
    h = 330 if name == "meme-season" else 300
    code = (f'<iframe src="{src}" width="100%" height="{h}" style="border:0;max-width:420px" loading="lazy" '
            f'title="MemeSonar"></iframe>')
    return (f"<h2 class=s>{t['embed_h']}</h2><div class=emb><p class=mut>{t['embed_p']}</p>"
            f"<textarea readonly aria-label='{esc(t['embed_h'])}'>{esc(code)}</textarea>"
            f"<button type=button class='btn sm' data-ok='{esc(t['copied'])}'>{t['copy']}</button></div>")


def _head(key, lang, h1, lead, d):
    t = T[lang]
    hub = PAGES["market"][lang != "en"]
    crumb = (f"<a href={'/' if lang == 'en' else '/hr'}>MemeSonar</a> / "
             + (f"<a href={hub}>{t['crumb']}</a> / " if key != "market" else "") + esc(NAV[lang][key][0]))
    return (f"<section class=ph1><div class=crumb>{crumb}</div><h1>{h1}</h1><p class=lead>{lead}</p>"
            f"<p class=asof>{t['asof'].format(d=_date(d['day'], lang))}</p></section>")


def _page(key, lang, title, desc, body, qa, d):
    from ui import public as P
    en, hr = PAGES[key]
    return P._shell(lang, title, desc, en, hr, f"<div class=mk>{body}</div><style>{CSS}</style>{JS}",
                    jsonld=_jsonld(key, lang, title, desc, qa, d))


def _empty(key, lang):
    from ui import public as P
    t = T[lang]
    en, hr = PAGES[key]
    return P._shell(lang, NAV[lang][key][0] + " | MemeSonar", NAV[lang][key][1], en, hr,
                    f"<section class=ph1><h1>{esc(NAV[lang][key][0])}</h1><p class=lead>{t['nodata']}</p></section>")


def _cur(d):
    """(score, label key, features) of the newest regime day."""
    if not d["regime"]:
        return None
    _day, s, _lb, f = d["regime"][-1]
    return s, f


# ---------- pages ---------------------------------------------------------------------------------------------------

def _xs(days, lang):
    return [_date(x, lang, year=False) for x in days]


def market(lang):
    d = snapshot()
    if not d:
        return _empty("market", lang)
    t, en = T[lang], lang == "en"
    day, ser, price = d["day"], d["ser"], d["price"]
    cur = _cur(d)
    lp, dx, tm = ser["launchpad"], ser["dex"], ser["terminal"]
    lp7, dx7, tm7 = _sum7(lp, day), _sum7(dx, day), _sum7(tm, day)
    lpp, dxp, tmp = _sum7(lp, day - 7 * D), _sum7(dx, day - 7 * D), _sum7(tm, day - 7 * D)
    g = lambda a, b: (a / b - 1) if a and b else None  # noqa: E731
    p0, p7 = price.get(day), price.get(day - 7 * D)
    share = lp7 / dx7 if lp7 and dx7 else None
    score = cur[0] if cur else None
    lab = label(score, lang) if score is not None else "–"
    if en:
        h1 = "Solana meme coin market today"
        lead = (f"On {_date(day, lang)}, the last complete day, Solana launchpads such as pump.fun traded <b>{usd(lp.get(day))}</b> and the "
                f"whole Solana DEX market <b>{usd(dx.get(day))}</b>. The <a href={PAGES['season'][0]}>meme coin season index</a> is <b>{score:.0f}/100 ({lab})</b>: "
                if score is not None else "")
        lead += (f"launchpad volume over the last 7 days is {pct(g(lp7, lpp))} {t['vs']}." if lp7 and lpp else "")
    else:
        h1 = "Solana meme coin tržište danas"
        lead = (f"Dana {_date(day, lang)}, zadnjeg potpunog dana, na Solana launchpadima poput pump.funa trgovalo se <b>{usd(lp.get(day), lang)}</b>, "
                f"a na cijelom Solana DEX tržištu <b>{usd(dx.get(day), lang)}</b>. <a href={PAGES['season'][1]}>Indeks sezone meme coina</a> "
                f"je <b>{score:.0f}/100 ({lab})</b>: " if score is not None else "")
        lead += (f"volumen launchpada u zadnjih 7 dana je {pct(g(lp7, lpp), lang)} {t['vs']}." if lp7 and lpp else "")
    cards = [(usd(lp7, lang), g(lp7, lpp), _gl("launchpad", lang, t["lp7"])),
             (usd(dx7, lang), g(dx7, dxp), _gl("dex", lang, t["dex7"])),
             (usd(tm7, lang), g(tm7, tmp), _gl("trading-bot", lang, t["term7"])),
             (pct(share, lang, signed=False, dec=1), None, _gl("launchpad-share", lang, t["share"])),
             (_n(f"${p0:.2f}", lang) if p0 else "–", g(p0, p7), t["solp"]),
             (usd(lp.get(day), lang), g(lp.get(day), lp.get(day - D)), t["lp"] + " · " + t["yday"].lower())]
    cards_html = "".join(f"<div class=card><b>{v}</b>" + (f"<span class=sub><em{_cls(c)} style='font-style:normal'>"
                                                          f"{pct(c, lang)}</em></span>" if c is not None else "")
                         + f"<span>{lab_}</span></div>" for v, c, lab_ in cards)
    body = [_head("market", lang, h1, lead, d), subnav("market", lang)]
    gtitle = _gl("meme-coin-season-index", lang, t["idx"])
    body.append(f"<div class=mkg>{gauge(score, lang, title=None) if score is not None else ''}"
                f"<div class=cards>{cards_html}</div></div>")
    body.append(f"<p class=mut style='margin:-14px 0 24px'>{gtitle}: " + (
        "0-33 cold, 34-65 neutral, 66-100 hot. " if en else "0-33 hladno, 34-65 neutralno, 66-100 vruće. ")
        + f"<a href={PAGES['season'][lang != 'en']}>{'How it works and 1-year history →' if en else 'Kako radi i povijest za godinu dana →'}</a></p>")
    # 90-day indexed trend (one axis: first day = 100)
    days = [day - i * D for i in range(89, -1, -1)]
    s_lp = {x: _sum7(lp, x) for x in days}
    s_dx = {x: _sum7(dx, x) for x in days}
    days = [x for x in days if s_lp.get(x) and s_dx.get(x)]
    if len(days) > 10:
        def idx(s):
            base = next((s[x] for x in days if s.get(x)), None)
            return [100 * s[x] / base if s.get(x) and base else None for x in days]
        series = [(t["lp"] + " (7d)", C1, idx(s_lp), [s_lp.get(x) for x in days], "usd"),
                  (t["dexn"] + " (7d)", C2, idx(s_dx), [s_dx.get(x) for x in days], "usd"),
                  (t["sol"], C3, idx(price), [price.get(x) for x in days], "usd2")]
        body.append(line_chart(
            "90-day trend (first day = 100)" if en else "Trend 90 dana (prvi dan = 100)",
            "7-day volume of launchpads and of the whole Solana DEX market, and the SOL price, all scaled so the first "
            "day is 100. Above 100 means growth since then. Hover or tap for the real numbers." if en else
            "Volumen launchpada i cijelog Solana DEX-a kroz 7 dana te cijena SOL-a, sve preračunato da je prvi dan 100. "
            "Iznad 100 znači rast od tada. Prijeđi mišem ili dodirni za prave brojeve.",
            _xs(days, lang), series, fmt="idx", lang=lang, guides=[(100, "")], table_every=7))
    # daily launchpad volume
    days30 = [day - i * D for i in range(59, -1, -1)]
    body.append(line_chart("Daily launchpad volume (60 days)" if en else "Dnevni volumen launchpada (60 dana)",
                           "pump.fun, LaunchLab (bonk.fun), Meteora DBC and smaller launchpads together." if en else
                           "pump.fun, LaunchLab (bonk.fun), Meteora DBC i manji launchpadi zajedno.",
                           _xs(days30, lang), [(t["lp"], C1, [lp.get(x) for x in days30], None, None)], lang=lang))
    # hypothesis
    h = d["hyp"]
    if h and h.get("same_day") is not None:
        c = h["same_day"]
        strength = (("strongly" if abs(c) >= .6 else "moderately" if abs(c) >= .3 else "weakly") if en else
                    ("jako" if abs(c) >= .6 else "umjereno" if abs(c) >= .3 else "slabo"))
        if en:
            txt = (f"Over the last {h['days']} days, daily changes in Solana DEX volume and launchpad volume moved "
                   f"<b>{strength} together</b> (correlation {c:+.2f}, where +1 is always together and 0 is no link)."
                   + (f" The weekly direction (up or down) matched on {h['week_agree']:.0%} of days." if h.get("week_agree") is not None else "")
                   + (" A busy day on Solana does <b>not</b> predict a busy day for meme coins tomorrow"
                      if (h.get("lead1") or 0) < .2 else " A busy Solana day slightly predicts more meme coin trading the next day")
                   + (f" ({h['lead1']:+.2f})." if h.get("lead1") is not None else ".")
                   + " PumpSwap (graduated pump.fun coins) is left out of the DEX side so meme volume is not counted twice.")
        else:
            txt = (f"U zadnjih {h['days']} dana dnevne promjene volumena Solana DEX-a i launchpada išle su "
                   f"<b>{strength} zajedno</b> (korelacija {_n(f'{c:+.2f}', lang)}; +1 znači uvijek zajedno, 0 nema veze)."
                   + (f" Tjedni smjer (rast ili pad) poklopio se {_n(f'{100 * h['week_agree']:.0f}', lang)}% dana." if h.get("week_agree") is not None else "")
                   + (" Živ dan na Solani <b>ne</b> najavljuje živ dan za meme coine sutra"
                      if (h.get("lead1") or 0) < .2 else " Živ dan na Solani malo najavljuje više trgovanja meme coinima sutra")
                   + (f" ({_n(f'{h['lead1']:+.2f}', lang)})." if h.get("lead1") is not None else ".")
                   + " PumpSwap (graduirani pump.fun coini) nije u DEX strani, da se meme volumen ne broji dvaput.")
        body.append(("<h2 class=s>Does more Solana volume mean more meme coin trading?</h2>" if en else
                     "<h2 class=s>Znači li više volumena na Solani i više trgovanja meme coinima?</h2>") + f"<p class=ans>{txt}</p>")
    # by day
    rows = []
    for i in range(30):
        x = day - i * D
        ch = lambda s: g(s.get(x), s.get(x - D))  # noqa: E731
        sh = lp[x] / dx[x] if lp.get(x) and dx.get(x) else None
        rows.append([_date(x, lang, year=False), usd(lp.get(x), lang), f"<span{_cls(ch(lp))}>{pct(ch(lp), lang)}</span>",
                     usd(dx.get(x), lang), f"<span{_cls(ch(dx))}>{pct(ch(dx), lang)}</span>", usd(tm.get(x), lang),
                     pct(sh, lang, signed=False, dec=1), _n(f"${price[x]:.2f}", lang) if price.get(x) else "–"])
    body.append(("<h2 class=s>Day by day (30 days)</h2><p class=mut>Full UTC days. Share = part of all Solana DEX volume "
                 "that went through launchpads.</p>" if en else
                 "<h2 class=s>Po danu (30 dana)</h2><p class=mut>Puni UTC dani. Udio = dio ukupnog Solana DEX volumena "
                 "koji je prošao kroz launchpade.</p>")
                + _table([t["day"], t["lp"], t["chg1"], t["dexn"], t["chg1"], t["term"], t["sh"], "SOL"], rows))
    body.append(_lockbox(lang))
    body.append(_embed("meme-season", lang))
    body.append(_more("market", lang))
    top = d["plats"]["launchpad"][0] if d["plats"]["launchpad"] else None
    lpshare = top["v7"] / lp7 if top and lp7 else None
    if en:
        qa = [("How big is the Solana meme coin market today?",
               f"On {_date(day, lang)} Solana launchpads traded {usd(lp.get(day))} and all Solana DEXs {usd(dx.get(day))}. "
               f"Over the last 7 days launchpads did {usd(lp7)}, which is {pct(share, signed=False, dec=1)} of all Solana DEX volume."),
              ("Which launchpad has the most volume?",
               f"{plabel(top, lang)[0]} with {usd(top['v7'])} in 7 days ({pct(lpshare, signed=False)} of all launchpad volume)." if top else "–"),
              ("Where does this data come from?",
               "From DefiLlama's public Solana DEX and launchpad volumes, checked every hour. DefiLlama finalises a day once, so "
               "every number here is for full UTC days. The season index and the charts are our own calculations."),
              ("How often is the page updated?", "Automatically: the source is checked every hour and the page refreshes within 30 minutes.")]
        title = f"Solana Meme Coin Market Volume Today ({_date(day, lang)}): Launchpads, DEX, Trend | MemeSonar"
        desc = (f"Live Solana meme coin market: launchpad volume {usd(lp7)} in 7 days ({pct(g(lp7, lpp))}), Solana DEX "
                f"{usd(dx7)}, trading terminals {usd(tm7)}. Charts and daily data, updated automatically.")
    else:
        qa = [("Koliko je veliko Solana meme coin tržište danas?",
               f"Dana {_date(day, lang)} launchpadi na Solani trgovali su {usd(lp.get(day), lang)}, a svi Solana DEX-ovi "
               f"{usd(dx.get(day), lang)}. U zadnjih 7 dana launchpadi su napravili {usd(lp7, lang)}, što je "
               f"{pct(share, lang, signed=False, dec=1)} ukupnog Solana DEX volumena."),
              ("Koji launchpad ima najviše volumena?",
               f"{plabel(top, lang)[0]} s {usd(top['v7'], lang)} u 7 dana ({pct(lpshare, lang, signed=False)} volumena svih launchpada)." if top else "–"),
              ("Odakle su ovi podaci?",
               "Iz javnih podataka DefiLlame o volumenu Solana DEX-ova i launchpada, provjera svaki sat. DefiLlama dan zaključa "
               "jednom, pa su svi brojevi za pune UTC dane. Indeks sezone i grafovi su naš izračun."),
              ("Koliko se često stranica osvježava?", "Automatski: izvor se provjerava svaki sat, a stranica se osvježi unutar 30 minuta.")]
        title = f"Volumen Solana meme coin tržišta danas ({_date(day, lang)}): launchpadi, DEX, trend | MemeSonar"
        desc = (f"Solana meme coin tržište uživo: volumen launchpada {usd(lp7, lang)} u 7 dana ({pct(g(lp7, lpp), lang)}), "
                f"Solana DEX {usd(dx7, lang)}, trading terminali {usd(tm7, lang)}. Grafovi i dnevni podaci, osvježava se samo.")
    body.append(_faq(qa, lang))
    body.append(f"<p class=mut style='margin-top:26px;font-size:13px'>{t['nf']}</p>")
    return _page("market", lang, title, desc, "".join(body), qa, d)


def launchpads(lang):
    d = snapshot()
    if not d or not d["plats"]["launchpad"]:
        return _empty("launchpads", lang)
    t, en, day = T[lang], lang == "en", d["day"]
    ps = d["plats"]["launchpad"]
    tot7 = sum(p["v7"] for p in ps)
    totp = sum(p["p7"] for p in ps)
    top = ps[0]
    cols = [C1, C2, C3, C4]
    names = {p["slug"]: plabel(p, lang)[0] for p in ps}
    # share bar
    seg, leg = [], []
    other = tot7
    for i, p in enumerate(ps[:3]):
        sh = p["v7"] / tot7 if tot7 else 0
        other -= p["v7"]
        seg.append(f"<i style='width:{100 * sh:.2f}%;background:{cols[i]}' title='{names[p['slug']]} {pct(sh, lang, False, 1)}'></i>")
        leg.append(f"<span><i style='background:{cols[i]}'></i>{names[p['slug']]} {pct(sh, lang, False, 1)}</span>")
    osh = other / tot7 if tot7 else 0
    if osh > 0.0005:
        seg.append(f"<i style='width:{100 * osh:.2f}%;background:{GREY}'></i>")
        leg.append(f"<span><i style='background:{GREY}'></i>{'Other' if en else 'Ostali'} {pct(osh, lang, False, 1)}</span>")
    lead = (f"<b>{names[top['slug']]}</b> handled <b>{pct(top['v7'] / tot7, signed=False)}</b> of all Solana launchpad volume in "
            f"the last 7 days ({usd(top['v7'])} of {usd(tot7)}). Here is how pump.fun, LaunchLab (bonk.fun), Meteora DBC and "
            "the smaller launchpads compare, updated every day." if en else
            f"<b>{names[top['slug']]}</b> je u zadnjih 7 dana imao <b>{pct(top['v7'] / tot7, lang, signed=False)}</b> svog volumena "
            f"Solana launchpada ({usd(top['v7'], lang)} od {usd(tot7, lang)}). Ovdje je usporedba pump.funa, LaunchLaba (bonk.fun), "
            "Meteora DBC-a i manjih launchpada, osvježava se svaki dan.")
    h1 = "Solana launchpads ranked by volume" if en else "Solana launchpadi po volumenu"
    body = [_head("launchpads", lang, h1, lead, d), subnav("launchpads", lang)]
    cards = [(usd(tot7, lang), _gl("launchpad", lang, "All launchpads, 7 days" if en else "Svi launchpadi, 7 dana")),
             (pct((tot7 / totp - 1) if totp else None, lang), t["vs"]),
             (str(len(ps)), "launchpads with $100k+ in 7 days" if en else "launchpada s $100k+ u 7 dana"),
             (pct(top["v7"] / tot7, lang, signed=False), (f"{names[top['slug']]} market share" if en else f"tržišni udio: {names[top['slug']]}"))]
    body.append("<div class=cards style='grid-template-columns:repeat(4,1fr)'>" + "".join(
        f"<div class=card><b>{v}</b><span>{lb}</span></div>" for v, lb in cards) + "</div>")
    body.append(f"<div class=mc><h3>{'Market share, last 7 days' if en else 'Tržišni udio, zadnjih 7 dana'}</h3>"
                f"<div class=shb role=img aria-label='{'Market share' if en else 'Tržišni udio'}'>{''.join(seg)}</div>"
                f"<div class=mcl>{''.join(leg)}</div></div>")
    # share over time
    pts = d["shares"]
    if len(pts) > 3:
        series = [(names.get(s, s), cols[i], [sh.get(s) for _x, sh in pts], None, None) for i, s in enumerate(d["top_lp"])]
        series.append(("Other" if en else "Ostali", GREY, [sh.get("other") for _x, sh in pts], None, None))
        body.append(line_chart("Market share over time (weekly)" if en else "Tržišni udio kroz vrijeme (tjedno)",
                               "Each point is a launchpad's share of all Solana launchpad volume in the 7 days ending that day."
                               if en else "Svaka točka je udio launchpada u ukupnom volumenu Solana launchpada u 7 dana do tog dana.",
                               [_date(x, lang, year=False) for x, _ in pts], series, fmt="pct", lang=lang, ymin=0, ymax=1))
    # daily volume of top 3 (one unit, USD)
    days = [day - i * D for i in range(59, -1, -1)]
    from market import store
    con = store.ro()
    try:
        series = []
        for i, s in enumerate(d["top_lp"]):
            v = dict(store.series(con, s, days[0])) if con else {}
            series.append((names.get(s, s), cols[i], [v.get(x) for x in days], None, None))
    finally:
        if con:
            con.close()
    body.append(line_chart("Daily volume, top 3 launchpads (60 days)" if en else "Dnevni volumen, top 3 launchpada (60 dana)",
                           "", _xs(days, lang), series, lang=lang))
    rows = []
    for i, p in enumerate(ps, 1):
        nm, what = plabel(p, lang)
        ch = (p["v7"] / p["p7"] - 1) if p["p7"] else None
        rows.append([str(i), f"<b>{nm}</b>" + (f"<br><span class=mut style='font-size:13px'>{what}</span>" if what else ""),
                     usd(p["y1"], lang), usd(p["v7"], lang), f"<span{_cls(ch)}>{pct(ch, lang)}</span>",
                     pct(p["v7"] / tot7, lang, signed=False, dec=1), usd(p["v30"], lang), spark(p["spark"])])
    body.append(("<h2 class=s>All Solana launchpads</h2>" if en else "<h2 class=s>Svi Solana launchpadi</h2>")
                + _table(["#", t["platform"], t["yday"], t["d7"], t["chg"], t["sh"], t["v30"], t["m30"]], rows, num_from=2))
    if en:
        body.append("<h2 class=s>What is a Solana launchpad?</h2><p class=ans>A " + _gl("launchpad", lang, "launchpad") +
                    " is a site where anyone can create a new token in a minute. The token first trades on a bonding curve: "
                    "the more people buy, the higher the price. When enough money is in, it " + _gl("graduation", lang, "graduates") +
                    " to a normal DEX pool (pump.fun coins move to PumpSwap). Launchpad volume is the best thermometer of how "
                    "busy the meme coin trenches are, which is why it drives our " +
                    f"<a href={PAGES['season'][0]}>meme coin season index</a>.</p>"
                    "<p class=ans><b>pump.fun</b> is the original and biggest. <b>LaunchLab</b> is Raydium's launchpad, used by "
                    "bonk.fun (LetsBonk). <b>Meteora DBC</b> (dynamic bonding curve) powers launches on Bags, Believe and "
                    "Jupiter Studio. How pump.fun works step by step, and the real odds of a new coin: "
                    "<a href=/blog/what-is-pump-fun>What is pump.fun?</a></p>")
    else:
        body.append("<h2 class=s>Što je Solana launchpad?</h2><p class=ans>" + _gl("launchpad", lang, "Launchpad") +
                    " je stranica na kojoj svatko za minutu napravi novi token. Token se prvo trguje na bonding curveu: što više "
                    "ljudi kupi, to je cijena viša. Kad se skupi dovoljno novca, token " + _gl("graduation", lang, "diplomira") +
                    " na običan DEX bazen (pump.fun coini prelaze na PumpSwap). Volumen launchpada je najbolji termometar koliko "
                    f"su trenchevi živi, zato pokreće naš <a href={PAGES['season'][1]}>indeks sezone meme coina</a>.</p>"
                    "<p class=ans><b>pump.fun</b> je prvi i najveći. <b>LaunchLab</b> je Raydiumov launchpad koji koristi "
                    "bonk.fun (LetsBonk). <b>Meteora DBC</b> (dinamički bonding curve) pokreće lansiranja na Bagsu, Believeu i "
                    "Jupiter Studiju. Kako pump.fun radi korak po korak i kakve su stvarne šanse novog coina: "
                    "<a href=/hr/blog/sto-je-pump-fun>Što je pump.fun?</a></p>")
    body.append(_lockbox(lang))
    body.append(_embed("launchpads", lang))
    body.append(_more("launchpads", lang))
    sec = ps[1] if len(ps) > 1 else None
    lab = {p["slug"]: p for p in ps}.get("launchlab")
    if en:
        qa = [("What is the biggest launchpad on Solana?",
               f"{names[top['slug']]}, with {usd(top['v7'])} traded in the last 7 days, {pct(top['v7'] / tot7, signed=False)} of all "
               "Solana launchpad volume."),
              ("pump.fun vs bonk.fun: which has more volume?",
               (f"In the last 7 days pump.fun traded {usd(lab and {p['slug']: p for p in ps}.get('pump.fun', {}).get('v7'))} and "
                f"LaunchLab, the launchpad behind bonk.fun, {usd(lab['v7'])}." if lab and "pump.fun" in {p['slug'] for p in ps}
                else "One of them is missing from this week's data.")),
              ("Which launchpad is number two?", f"{names[sec['slug']]} with {usd(sec['v7'])} in 7 days." if sec else "–"),
              ("Is a launchpad safe?", "The launchpad itself is just the place where tokens are made. Most new tokens fail and "
               "many are scams, so check every token before buying. See our <a href=/rug-check>rug checks</a>."),
              ("Where does the data come from?", "DefiLlama's public launchpad volumes on Solana, full UTC days, updated daily.")]
        title = f"Solana Launchpads by Volume: pump.fun vs bonk.fun vs Meteora ({_month(day, lang)}) | MemeSonar"
        desc = (f"Which Solana launchpad trades the most? {names[top['slug']]} has {pct(top['v7'] / tot7, signed=False)} of "
                f"launchpad volume ({usd(top['v7'])} in 7 days). Market share chart and daily data for every launchpad.")
    else:
        qa = [("Koji je najveći launchpad na Solani?",
               f"{names[top['slug']]}, s {usd(top['v7'], lang)} u zadnjih 7 dana, {pct(top['v7'] / tot7, lang, signed=False)} "
               "ukupnog volumena Solana launchpada."),
              ("pump.fun ili bonk.fun: tko ima više volumena?",
               (f"U zadnjih 7 dana pump.fun je imao {usd({p['slug']: p for p in ps}.get('pump.fun', {}).get('v7'), lang)}, a "
                f"LaunchLab, launchpad iza bonk.funa, {usd(lab['v7'], lang)}." if lab and "pump.fun" in {p['slug'] for p in ps}
                else "Jedan od njih nedostaje u podacima za ovaj tjedan.")),
              ("Koji je launchpad drugi?", f"{names[sec['slug']]} s {usd(sec['v7'], lang)} u 7 dana." if sec else "–"),
              ("Je li launchpad siguran?", "Launchpad je samo mjesto gdje tokeni nastaju. Većina novih tokena propadne, a mnogi su "
               "prevare, pa provjeri svaki token prije kupnje. Pogledaj naše <a href=/hr/provjera>provjere ruga</a>."),
              ("Odakle su podaci?", "Javni podaci DefiLlame o volumenu launchpada na Solani, puni UTC dani, osvježava se svaki dan.")]
        title = f"Solana launchpadi po volumenu: pump.fun, bonk.fun, Meteora ({_month(day, lang)}) | MemeSonar"
        desc = (f"Koji Solana launchpad ima najviše trgovanja? {names[top['slug']]} ima {pct(top['v7'] / tot7, lang, signed=False)} "
                f"volumena ({usd(top['v7'], lang)} u 7 dana). Graf tržišnog udjela i dnevni podaci za svaki launchpad.")
    body.append(_faq(qa, lang))
    body.append(f"<p class=mut style='margin-top:26px;font-size:13px'>{t['nf']}</p>")
    return _page("launchpads", lang, title, desc, "".join(body), qa, d)


TZS = [("", None), ("UTC", "UTC"), ("London", "Europe/London"), ("Zagreb / Berlin / Paris", "Europe/Zagreb"),
       ("New York", "America/New_York"), ("Los Angeles", "America/Los_Angeles"), ("Dubai", "Asia/Dubai"),
       ("Singapore / Hong Kong / Shanghai", "Asia/Singapore"), ("Tokyo / Seoul", "Asia/Tokyo"), ("Sydney", "Australia/Sydney")]


def _hbars(vals, lang, tip, lo=None, color=C1):
    """24 bars by UTC hour (the time zone switch re-labels and re-orders them). vals[h] or None; lo = set of hours to grey."""
    mx = max([v for v in vals if v] or [1])
    bars = []
    for h_, v in enumerate(vals):
        cls = " class=lo" if lo and h_ in lo else ""
        bars.append(f"<div data-h={h_}{cls}><em style='height:{100 * (v or 0) / mx:.1f}%;--c:{color}'></em>"
                    f"<span><b class=tl>{h_:02d}:00–{(h_ + 1) % 24:02d}:00</b><br>{tip(h_)}</span></div>")
    labels = "".join(f"<span class=hxl data-h={h_}>{h_}</span>" for h_ in range(24))
    return f"<div class=hb>{''.join(bars)}</div><div class='hx'>{labels}</div>"


def _weekday(d, lang):
    """Average launchpad volume per weekday over the last 12 full weeks, as share of the weekly average."""
    lp = d["ser"]["launchpad"]
    day = d["day"]
    by = [[] for _ in range(7)]
    for i in range(84):
        x = day - i * D
        if lp.get(x):
            w = [lp.get(x - k * D) for k in range(-3, 4)]
            w = [v for v in w if v]
            if len(w) >= 5:   # relative to the surrounding week, so a trend does not favour recent days
                by[dt.datetime.fromtimestamp(x, dt.timezone.utc).weekday()].append(lp[x] / (sum(w) / len(w)))
    return [sum(v) / len(v) if v else None for v in by]


def _zbest(rated, best):
    """Two-proportion z score: the best session's hit rate against all other sessions together."""
    import math
    a = rated[best]
    n2 = sum(v["n"] for k, v in rated.items() if k != best)
    h2 = sum(v["hits"] for k, v in rated.items() if k != best)
    if not a["n"] or not n2:
        return 0.0
    p1, p2 = a["hits"] / a["n"], h2 / n2
    p = (a["hits"] + h2) / (a["n"] + n2)
    se = math.sqrt(p * (1 - p) * (1 / a["n"] + 1 / n2))
    return (p1 - p2) / se if se else 0.0


def besttime(lang):
    d = snapshot()
    if not d:
        return _empty("besttime", lang)
    t, en = T[lang], lang == "en"
    hrs = d["hours"]
    sn = SESSION_NAMES[lang]
    body = []
    best_s, same = None, None
    if hrs and hrs["n"]:
        rated = {s: v for s, v in hrs["sess"].items() if v["rate"] is not None and v["n"] >= 30}
        best_s = max(rated, key=lambda s: rated[s]["rate"]) if rated else None
        rr = [v["rate"] for v in rated.values()]
        if best_s and len(rr) > 1 and _zbest(rated, best_s) < 2:
            same = (min(rr), max(rr))      # not clearly better than the other sessions together: noise, not "best"
            best_s = None
    vol = hrs["vol"] if hrs else None
    peak = None
    if vol:
        win = [(sum(vol[(h_ + k) % 24] for k in range(3)), h_) for h_ in range(24)]
        peak = max(win, key=lambda x: (round(x[0], 9), -x[1]))[1]
    vs_ = max(hrs["sess"], key=lambda k: hrs["sess"][k]["vol"] or 0) if vol else None
    if en:
        lead = ("Crypto trades 24/7, but meme coins don't move the same way all day. We measured it: "
                + (f"meme coin volume peaks between <b>{peak:02d}:00 and {(peak + 3) % 24:02d}:00 UTC</b>" if peak is not None else "")
                + (f", and influencer calls posted during the <b>{sn[best_s]}</b> session worked best "
                   f"({pct(hrs['sess'][best_s]['rate'], signed=False)} rose 50%+ within 24 h)." if best_s else
                   f", while influencer calls worked about the same in every session ({pct(same[0], signed=False)}–"
                   f"{pct(same[1], signed=False)} rose 50%+ within 24 h)." if same else ".")
                + " Pick your time zone below to see it in your own hours.")
        h1 = "Best time to trade crypto and meme coins"
    else:
        lead = ("Kripto se trguje 0-24, ali meme coini se ne miču jednako cijeli dan. Izmjerili smo: "
                + (f"volumen meme coina najveći je između <b>{peak:02d}:00 i {(peak + 3) % 24:02d}:00 UTC</b>" if peak is not None else "")
                + (f", a pozivi influencera objavljeni u sesiji <b>{sn[best_s]}</b> prošli su najbolje "
                   f"({pct(hrs['sess'][best_s]['rate'], lang, signed=False)} ih je naraslo 50%+ u 24 h)." if best_s else
                   f", a pozivi influencera radili su otprilike jednako u svakoj sesiji ({pct(same[0], lang, signed=False)}–"
                   f"{pct(same[1], lang, signed=False)} ih je naraslo 50%+ u 24 h)." if same else ".")
                + " Odaberi svoju vremensku zonu ispod i vidi to u svojim satima.")
        h1 = "Najbolje vrijeme za trgovanje kriptom i meme coinima"
    body.append(_head("besttime", lang, h1, lead, d))
    body.append(subnav("besttime", lang))
    opts = "".join(f"<option value='{z or ''}'>{esc(n or t['local'])}</option>" for n, z in TZS)
    body.append(f"<div class=tzr><label for=tz>{t['tz']}</label><select id=tz>{opts}</select>"
                f"<span class=mut>{'(UTC by default without JavaScript)' if en else '(bez JavaScripta UTC)'}</span></div>")
    if vol:
        tip = (lambda h_: f"{pct(vol[h_], signed=False, dec=1)} of daily volume") if en else \
              (lambda h_: f"{pct(vol[h_], lang, signed=False, dec=1)} dnevnog volumena")
        body.append(f"<div class=mc><h3>{'When meme coins trade: share of daily volume by hour' if en else 'Kad se trguje meme coinima: udio dnevnog volumena po satu'}</h3>"
                    f"<p class=ms>{('Average over ' + f'{hrs['ntok']:,}' + ' Solana meme coins that influencers called; each coin counts equally. Hours in <span class=tzn>UTC</span>.') if en else ('Prosjek ' + _n(f'{hrs['ntok']:,}', lang) + ' Solana meme coina koje su pozvali influenceri; svaki coin vrijedi jednako. Sati: <span class=tzn>UTC</span>.')}</p>"
                    + _hbars(vol, lang, tip) + "</div>")
    if hrs and hrs["n"]:
        calls = hrs["calls"]
        rates = [(h_[1] / h_[0]) if h_[0] else None for h_ in calls]
        lo = {i for i, c in enumerate(calls) if c[0] < MIN_HOUR_N}

        def tip2(i):
            n, k = calls[i]
            if not n:
                return "no calls" if en else "nema poziva"
            return (f"{pct(k / n, signed=False)} of {n:,} calls rose 50%+" if en else
                    f"{pct(k / n, lang, signed=False)} od {_n(f'{n:,}', lang)} poziva naraslo 50%+")
        span = (f"{_date(hrs['from'], lang)} – {_date(hrs['to'], lang)}") if hrs.get("from") else ""
        body.append(f"<div class=mc><h3>{'When influencer calls work: share that rose 50%+ within 24 h, by hour posted' if en else 'Kad pozivi influencera rade: udio koji je narastao 50%+ u 24 h, po satu objave'}</h3>"
                    f"<p class=ms>{(f'{hrs['n']:,} first calls of Solana tokens on X, {span}. Grey hours have fewer than {MIN_HOUR_N} calls. Average: {pct(hrs['rate'], signed=False)}. Bot accounts excluded.') if en else (_n(f'{hrs['n']:,}', lang) + f' prvih poziva Solana tokena na X-u, {span}. Sivi sati imaju manje od {MIN_HOUR_N} poziva. Prosjek: {pct(hrs['rate'], lang, signed=False)}. Bot računi izbačeni.')}</p>"
                    + _hbars(rates, lang, tip2, lo=lo, color=C2) + "</div>")
    # sessions table
    rows = []
    for s, a, b in SESSIONS:
        v = hrs["sess"][s] if hrs else {}
        rows.append([f"<b>{sn[s]}</b>", f"{a:02d}:00–{b % 24:02d}:00", f"<span data-r='{a},{b}'>{a:02d}:00–{b % 24:02d}:00</span>",
                     pct(v.get("vol"), lang, signed=False) if v.get("vol") is not None else "–",
                     _n(f"{v.get('n', 0):,}", lang), pct(v.get("rate"), lang, signed=False)])
    body.append(("<h2 class=s>The three trading sessions</h2><p class=mut>Crypto has no opening bell, but traders sleep. "
                 "Asia 00-08 UTC, Europe 08-14 UTC, United States 14-24 UTC.</p>" if en else
                 "<h2 class=s>Tri sesije trgovanja</h2><p class=mut>Kripto nema zvono za otvaranje, ali trejderi spavaju. "
                 "Azija 00-08 UTC, Europa 08-14 UTC, SAD 14-24 UTC.</p>")
                + _table([_gl("trading-session", lang, "Session" if en else "Sesija"), "UTC",
                          f"<span class=tzn>{t['local']}</span>", "Volume" if en else "Volumen",
                          "Calls" if en else "Pozivi", "Rose 50%+" if en else "Naraslo 50%+"], rows, num_from=3))
    wk = _weekday(d, lang)
    we = None
    if wk[5] is not None and wk[6] is not None and all(v is not None for v in wk[:5]):
        we = (wk[5] + wk[6]) / 2 - sum(wk[:5]) / 5        # weekend vs weekday, as a share of the weekly average
    if any(wk):
        days_n = (("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") if en else ("pon", "uto", "sri", "čet", "pet", "sub", "ned"))
        mx = max(v for v in wk if v)
        cells = "".join(f"<div class=cbr><span>{days_n[i]}</span><i><em style='width:{100 * (v or 0) / mx:.0f}%;background:{C1}'></em></i>"
                        f"<b>{pct(round((v or 1) - 1, 2) + 0.0, lang)}</b></div>" for i, v in enumerate(wk))
        body.append(("<h2 class=s>Best day of the week</h2><p class=mut>Launchpad volume on each weekday compared with the "
                     "average of the surrounding week, last 12 weeks.</p>" if en else
                     "<h2 class=s>Najbolji dan u tjednu</h2><p class=mut>Volumen launchpada po danu u tjednu u odnosu na prosjek "
                     "okolnog tjedna, zadnjih 12 tjedana.</p>") + f"<div class=mc>{cells}</div>")
    # what it means
    if en:
        body.append("<h2 class=s>What this means for your trading</h2><ul class=how>"
                    "<li><b>More volume = tighter prices.</b> In busy hours your buy moves the price less (lower "
                    + _gl("slippage", lang, "slippage") + ") and it is easier to sell.</li>"
                    "<li><b>Busy hours are also the most crowded.</b> " + _gl("sniper-bot", lang, "Sniper bots") +
                    " and fast traders are awake too, so entries during the US session were the most expensive in our data.</li>"
                    + (f"<li><b>Weekends were {'quieter' if we < 0 else 'busier'}</b> than weekdays over the last 12 weeks "
                       f"({pct(we)} launchpad volume).</li>" if we is not None and abs(we) >= 0.02 else "")
                    + "<li>Time of day matters less than the entry price. Where to enter a new coin, from 10,650 tokens: "
                    "<a href=/blog/how-to-trade-meme-coins>how to trade meme coins</a>.</li>"
                    "<li>None of this makes a bad token good. Always check the token first: "
                    "<a href=/rug-check>rug checks</a>.</li></ul>")
    else:
        body.append("<h2 class=s>Što to znači za tvoje trgovanje</h2><ul class=how>"
                    "<li><b>Više volumena = bolje cijene.</b> U živim satima tvoja kupnja manje pomakne cijenu (manji "
                    + _gl("slippage", lang, "slippage") + ") i lakše je prodati.</li>"
                    "<li><b>Živi sati su i najgušći.</b> " + _gl("sniper-bot", lang, "Sniper botovi") +
                    " i brzi trejderi su budni, pa su ulazi u SAD sesiji kod nas bili najskuplji.</li>"
                    + (f"<li><b>Vikendi su bili {'mirniji' if we < 0 else 'živahniji'}</b> od radnih dana u zadnjih 12 tjedana "
                       f"({pct(we, lang)} volumena launchpada).</li>" if we is not None and abs(we) >= 0.02 else "")
                    + "<li>Doba dana je manje važno od cijene ulaza. Gdje ući u novi coin, iz 10.650 tokena: "
                    "<a href=/hr/blog/kako-trgovati-meme-coinima>kako trgovati meme coinima</a>.</li>"
                    "<li>Ništa od ovoga ne čini loš token dobrim. Uvijek prvo provjeri token: "
                    "<a href=/hr/provjera>provjera ruga</a>.</li></ul>")
    body.append(_lockbox(lang))
    body.append(_more("besttime", lang))
    if en:
        qa = [("What is the best time of day to trade crypto?",
               (f"For Solana meme coins, volume is highest between {peak:02d}:00 and {(peak + 3) % 24:02d}:00 UTC in our data. "
                if peak is not None else "") + (f"Of the three sessions, {sn[vs_]} has the largest share of meme coin volume "
                f"({pct(hrs['sess'][vs_]['vol'], signed=False)})." if vs_ else "Crypto never closes, so there is no single answer.")),
              ("Which trading session is best for meme coins?",
               (f"Influencer calls posted in the {sn[best_s]} session did best: {pct(hrs['sess'][best_s]['rate'], signed=False)} "
                f"rose 50%+ within 24 hours, against {pct(hrs['rate'], signed=False)} on average." if best_s else
                f"None stands out: influencer calls did about the same in every session ({pct(same[0], signed=False)}–"
                f"{pct(same[1], signed=False)} rose 50%+ within 24 hours), so the hour matters less than the token." if same else
                "We need more measured calls to say.") + " Busy sessions also bring more competition from bots."),
              ("What are the crypto trading sessions?", "Asia 00:00-08:00 UTC, Europe 08:00-14:00 UTC and the United States "
               "14:00-24:00 UTC. They are named after where most traders are awake."),
              ("Is the weekend a good time to trade meme coins?",
               (f"In the last 12 weeks weekend launchpad volume was {pct(we)} compared with weekdays. " if we is not None else "")
               + "The weekday chart above shows how each day did against its own week."),
              ("How did you measure this?", "Hourly volume comes from 5-minute candles of every Solana meme coin influencers "
               "called; call results from MemeSonar's own tracking of first calls on X (24-hour peak). Calls younger than "
               "24 hours and bot accounts are left out.")]
        title = "Best Time to Trade Crypto & Meme Coins by Hour and Session (Our Data) | MemeSonar"
        desc = ("When do Solana meme coins trade most, and when do influencer calls work best? Volume and call results by "
                "hour and session, in your own time zone. Updated automatically.")
    else:
        qa = [("Koje je najbolje doba dana za trgovanje kriptom?",
               (f"Za Solana meme coine volumen je kod nas najveći između {peak:02d}:00 i {(peak + 3) % 24:02d}:00 UTC. "
                if peak is not None else "") + (f"Od tri sesije, {sn[vs_]} ima najveći udio volumena meme coina "
                f"({pct(hrs['sess'][vs_]['vol'], lang, signed=False)})." if vs_ else "Kripto se nikad ne zatvara, pa nema jednog odgovora.")),
              ("Koja je sesija najbolja za meme coine?",
               (f"Pozivi influencera objavljeni u sesiji {sn[best_s]} prošli su najbolje: {pct(hrs['sess'][best_s]['rate'], lang, signed=False)} "
                f"ih je naraslo 50%+ u 24 sata, prema prosjeku od {pct(hrs['rate'], lang, signed=False)}." if best_s else
                f"Nijedna se ne ističe: pozivi influencera prošli su otprilike jednako u svakoj sesiji ({pct(same[0], lang, signed=False)}–"
                f"{pct(same[1], lang, signed=False)} ih je naraslo 50%+ u 24 sata), pa je token važniji od sata." if same else
                "Treba nam više izmjerenih poziva.") + " Žive sesije donose i više konkurencije botova."),
              ("Koje su sesije trgovanja kriptom?", "Azija 00:00-08:00 UTC, Europa 08:00-14:00 UTC i SAD 14:00-24:00 UTC "
               "(kod nas UTC+1 zimi, UTC+2 ljeti). Nazvane su po tome gdje je većina trejdera budna."),
              ("Je li vikend dobro vrijeme za meme coine?",
               (f"U zadnjih 12 tjedana volumen launchpada vikendom bio je {pct(we, lang)} u odnosu na radne dane. " if we is not None else "")
               + "Graf po danima iznad pokazuje kako je svaki dan prošao u odnosu na svoj tjedan."),
              ("Kako ste ovo izmjerili?", "Volumen po satu dolazi iz 5-minutnih svijeća svakog Solana meme coina koji su "
               "influenceri pozvali; rezultati poziva iz našeg praćenja prvih poziva na X-u (vrh u 24 sata). Pozivi mlađi od "
               "24 sata i bot računi nisu uključeni.")]
        title = "Najbolje vrijeme za trgovanje kriptom i meme coinima po satu i sesiji | MemeSonar"
        desc = ("Kad se Solana meme coinima najviše trguje i kad pozivi influencera najbolje rade? Volumen i rezultati po satu "
                "i sesiji, u tvojoj vremenskoj zoni. Osvježava se samo.")
    body.append(_faq(qa, lang))
    body.append(f"<p class=mut style='margin-top:26px;font-size:13px'>{t['nf']}</p>")
    return _page("besttime", lang, title, desc, "".join(body), qa, d)


def _heat(score):
    """Diverging color for a 0-100 score: blue (cold) - grey - orange (hot)."""
    def mix(a, b, f):
        a, b = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))
    mid = "#e3e5ea"
    return mix(COLD, mid, score / 50) if score < 50 else mix(mid, HOT, (score - 50) / 50)


def season(lang):
    d = snapshot()
    if not d or not d["regime"]:
        return _empty("season", lang)
    t, en, day = T[lang], lang == "en", d["day"]
    reg = d["regime"]
    score, f = reg[-1][1], reg[-1][3]
    lab = label(score, lang)
    yr = [r for r in reg if r[0] > day - 365 * D]
    w = [r[1] for r in reg if r[0] > day - 7 * D]
    m = [r[1] for r in reg if r[0] > day - 30 * D]
    hot_days = sum(1 for r in yr if r[1] >= 66)
    peak = max(yr, key=lambda r: r[1]) if yr else None
    last_hot = next((r for r in reversed(reg) if r[1] >= 66), None)
    is_season = score >= 66
    if en:
        h1 = "Meme coin season index"
        lead = (f"Is it meme coin season? <b>{'Yes' if is_season else 'Not right now'}</b>: the index is <b>{score:.0f}/100 ({lab})</b>. "
                "It measures how busy Solana meme coin trading is compared with the last 90 days, from launchpad and DEX "
                "volume. 66 or more means meme season.")
    else:
        h1 = "Indeks sezone meme coina"
        lead = (f"Je li sezona meme coina? <b>{'Da' if is_season else 'Trenutno ne'}</b>: indeks je <b>{score:.0f}/100 ({lab})</b>. "
                "Mjeri koliko je trgovanje Solana meme coinima živo u odnosu na zadnjih 90 dana, iz volumena launchpada i "
                "DEX-a. 66 ili više znači sezona meme coina.")
    body = [_head("season", lang, h1, lead, d), subnav("season", lang)]
    avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    cards = [(f"{avg(w):.0f}" if w else "–", "7-day average" if en else "Prosjek 7 dana"),
             (f"{avg(m):.0f}" if m else "–", "30-day average" if en else "Prosjek 30 dana"),
             (str(hot_days), "hot days in the last year" if en else "vrućih dana u zadnjih godinu dana"),
             (f"{peak[1]:.0f}" if peak else "–", (f"1-year high ({_date(peak[0], lang)})" if en else
                                                  f"najviše u godini ({_date(peak[0], lang)})") if peak else ""),
             (_date(last_hot[0], lang) if last_hot else "–", "last hot day" if en else "zadnji vrući dan"),
             (pct(f.get("launchpad_growth7d"), lang), "launchpad volume, week on week" if en else "volumen launchpada, tjedan na tjedan")]
    body.append(f"<div class=mkg>{gauge(score, lang, title=t['idx'])}<div class=cards>" + "".join(
        f"<div class=card><b>{v}</b><span>{lb}</span></div>" for v, lb in cards) + "</div></div>")
    xs = [_date(r[0], lang, year=True) for r in yr]
    body.append(line_chart("Meme coin season index, last 12 months" if en else "Indeks sezone meme coina, zadnjih 12 mjeseci",
                           "Above the upper line = meme season (hot), below the lower line = cold." if en else
                           "Iznad gornje crte = sezona meme coina (vruće), ispod donje = hladno.",
                           xs, [(t["idx"], C1, [r[1] for r in yr], None, None)], fmt="idx", lang=lang, ymin=0, ymax=100,
                           guides=[(66, ""), (33, "")], table_every=7, ticks=[0, 33, 66, 100]))
    # calendar heatmap (weeks as columns, Monday first)
    if yr:
        first = yr[0][0]
        pad = dt.datetime.fromtimestamp(first, dt.timezone.utc).weekday()
        cells = ["<i style='visibility:hidden'></i>"] * pad
        cells += [f"<i style='background:{_heat(r[1])}' title='{esc(_date(r[0], lang))}: {r[1]:.0f}'></i>" for r in yr]
        legend = "".join(f"<i style='background:{_heat(v)};width:14px;height:10px;display:inline-block;border-radius:2px'></i>"
                         for v in (0, 20, 40, 50, 60, 80, 100))
        body.append(f"<div class=mc><h3>{'Every day of the last year' if en else 'Svaki dan zadnjih godinu dana'}</h3>"
                    f"<p class=ms>{'One square per day, Monday at the top. Hover for the date and value.' if en else 'Jedan kvadratić po danu, ponedjeljak gore. Prijeđi mišem za datum i vrijednost.'}</p>"
                    f"<div class=cal>{''.join(cells)}</div><div class=mcl style='margin-top:8px'><span>"
                    f"{t['cold']} {legend} {t['hot']}</span></div></div>")
    # monthly table
    months = {}
    for r in yr:
        k = dt.datetime.fromtimestamp(r[0], dt.timezone.utc).strftime("%Y-%m")
        months.setdefault(k, []).append(r)
    rows = []
    for k in sorted(months, reverse=True):
        rs = months[k]
        a = avg([r[1] for r in rs])
        rows.append([_month(rs[0][0], lang), f"{a:.0f}", esc(label(a, lang)), str(sum(1 for r in rs if r[1] >= 66)),
                     str(sum(1 for r in rs if r[1] <= 33))])
    body.append(("<h2 class=s>Month by month</h2>" if en else "<h2 class=s>Po mjesecima</h2>") + _table(
        ["Month" if en else "Mjesec", "Average" if en else "Prosjek", "", "Hot days" if en else "Vrućih dana",
         "Cold days" if en else "Hladnih dana"], rows, num_from=1))
    # how it works
    comp = [(f.get("launchpad_pct90"), "Launchpad volume (7 days) vs last 90 days" if en else "Volumen launchpada (7 dana) prema zadnjih 90 dana"),
            (f.get("dex_pct90"), "Solana DEX volume (7 days) vs last 90 days" if en else "Solana DEX volumen (7 dana) prema zadnjih 90 dana"),
            (f.get("launchpad_growth_pct90"), "Launchpad growth week on week vs last 90 days" if en else "Rast launchpada tjedan na tjedan prema zadnjih 90 dana")]
    bars = "".join(f"<div class=cbr><span style='white-space:normal'>{lb}</span><i><em style='width:{100 * (v or 0):.0f}%;background:{C1}'></em></i>"
                   f"<b>{100 * v:.0f}</b></div>" for v, lb in comp if v is not None)
    if en:
        body.append("<h2 class=s>How the index works</h2><p class=ans>Three numbers, each a rank from 0 to 100 against the last "
                    "90 days (100 = the highest of those 90 days). The index is their average. Today:</p>"
                    f"<div class=mc>{bars}</div><p class=ans>Unlike an altcoin season index, which compares large coins with "
                    "Bitcoin, this one looks only at where meme coins are born and traded on Solana: " +
                    f"<a href={PAGES['launchpads'][0]}>launchpads</a> such as pump.fun and the whole "
                    f"<a href={PAGES['dex'][0]}>Solana DEX market</a>. It uses full UTC days from DefiLlama, so it changes once a day.</p>")
    else:
        body.append("<h2 class=s>Kako indeks radi</h2><p class=ans>Tri broja, svaki je rang od 0 do 100 prema zadnjih 90 dana "
                    "(100 = najviše od tih 90 dana). Indeks je njihov prosjek. Danas:</p>"
                    f"<div class=mc>{bars}</div><p class=ans>Za razliku od indeksa altcoin sezone, koji uspoređuje velike coine s "
                    "Bitcoinom, ovaj gleda samo gdje se meme coini rađaju i trguju na Solani: " +
                    f"<a href={PAGES['launchpads'][1]}>launchpade</a> poput pump.funa i cijelo "
                    f"<a href={PAGES['dex'][1]}>Solana DEX tržište</a>. Koristi pune UTC dane s DefiLlame, pa se mijenja jednom dnevno.</p>")
    body.append(_lockbox(lang))
    body.append(_embed("meme-season", lang))
    body.append(_more("season", lang))
    if en:
        qa = [("Is it meme coin season right now?",
               f"{'Yes' if is_season else 'No'}. The meme coin season index is {score:.0f}/100 ({lab}) on {_date(day, lang)}. "
               "We call it meme season at 66 or more."),
              ("When was the last meme coin season?",
               f"The last hot day was {_date(last_hot[0], lang)}." if last_hot else "There was no hot day in our history yet."),
              ("How is the meme coin season index calculated?",
               "It is the average of three 0-100 ranks against the last 90 days: 7-day launchpad volume, 7-day Solana DEX "
               "volume and the week-on-week growth of launchpad volume."),
              ("Is this the same as the altcoin season index?",
               "No. An altcoin season index compares large altcoins with Bitcoin. This index only measures Solana meme coin "
               "trading activity."),
              ("Does a hot market mean I will make money?",
               "No. A hot market means more buyers and more volume, but also more new tokens, more scams and more bots. "
               "It is a thermometer, not a buy signal.")]
        title = f"Meme Coin Season Index: Is It Meme Season? {score:.0f}/100 Today | MemeSonar"
        desc = (f"Is it meme coin season? Today's index: {score:.0f}/100 ({lab}). A daily 0-100 index of Solana meme coin "
                "activity from launchpad and DEX volume, with 1-year history and a free embeddable widget.")
    else:
        qa = [("Je li sada sezona meme coina?",
               f"{'Da' if is_season else 'Ne'}. Indeks sezone meme coina je {score:.0f}/100 ({lab}) na dan {_date(day, lang)}. "
               "Sezonom zovemo 66 ili više."),
              ("Kad je bila zadnja sezona meme coina?",
               f"Zadnji vrući dan bio je {_date(last_hot[0], lang)}." if last_hot else "U našoj povijesti još nije bilo vrućeg dana."),
              ("Kako se računa indeks sezone meme coina?",
               "Prosjek je tri ranga 0-100 prema zadnjih 90 dana: volumen launchpada kroz 7 dana, Solana DEX volumen kroz "
               "7 dana i rast volumena launchpada tjedan na tjedan."),
              ("Je li to isto što i indeks altcoin sezone?",
               "Nije. Indeks altcoin sezone uspoređuje velike altcoine s Bitcoinom. Ovaj indeks mjeri samo trgovanje Solana meme coinima."),
              ("Znači li vruće tržište da ću zaraditi?",
               "Ne. Vruće tržište znači više kupaca i volumena, ali i više novih tokena, prevara i botova. To je termometar, "
               "a ne signal za kupnju.")]
        title = f"Indeks sezone meme coina: je li sezona? {score:.0f}/100 danas | MemeSonar"
        desc = (f"Je li sezona meme coina? Današnji indeks: {score:.0f}/100 ({lab}). Dnevni indeks 0-100 aktivnosti Solana meme "
                "coina iz volumena launchpada i DEX-a, s poviješću za godinu dana i besplatnim widgetom.")
    body.append(_faq(qa, lang))
    body.append(f"<p class=mut style='margin-top:26px;font-size:13px'>{t['nf']}</p>")
    return _page("season", lang, title, desc, "".join(body), qa, d)


def dex(lang):
    d = snapshot()
    if not d or not d["plats"]["dex"]:
        return _empty("dex", lang)
    t, en, day = T[lang], lang == "en", d["day"]
    dx, tm = d["ser"]["dex"], d["ser"]["terminal"]
    ps, ts_ = d["plats"]["dex"], d["plats"]["terminal"]
    d7, dp = _sum7(dx, day), _sum7(dx, day - 7 * D)
    ch = (d7 / dp - 1) if d7 and dp else None
    top = ps[0]
    big = sum(1 for p in ps if p["v7"] >= 7e6)
    if en:
        h1 = "Solana DEX volume today"
        lead = (f"Solana DEXs traded <b>{usd(dx.get(day))}</b> on {_date(day, lang)} and <b>{usd(d7)}</b> in the last 7 days "
                f"({pct(ch)} {t['vs']}). The biggest by volume was <b>{plabel(top, lang)[0]}</b>. Below: every Solana DEX "
                "and the trading terminals meme coin traders use.")
    else:
        h1 = "Solana DEX volumen danas"
        lead = (f"Solana DEX-ovi su {_date(day, lang)} trgovali <b>{usd(dx.get(day), lang)}</b>, a u zadnjih 7 dana <b>{usd(d7, lang)}</b> "
                f"({pct(ch, lang)} {t['vs']}). Najveći po volumenu bio je <b>{plabel(top, lang)[0]}</b>. Ispod: svi Solana "
                "DEX-ovi i trading terminali kojima se služe trejderi meme coina.")
    body = [_head("dex", lang, h1, lead, d), subnav("dex", lang)]
    tm7 = _sum7(tm, day)
    cards = [(usd(dx.get(day), lang), t["yday"]), (usd(d7, lang), _gl("dex", lang, t["dex7"])),
             (pct(ch, lang), t["vs"]), (str(big), "DEXs with $1M+ a day on average" if en else "DEX-ova s $1M+ dnevno u prosjeku"),
             (usd(tm7, lang), _gl("trading-bot", lang, t["term7"])),
             (pct(_sum7(d["ser"]["launchpad"], day) / d7 if d7 else None, lang, signed=False, dec=1),
              _gl("launchpad-share", lang, t["share"]))]
    body.append("<div class=cards>" + "".join(f"<div class=card><b>{v}</b><span>{lb}</span></div>" for v, lb in cards) + "</div>")
    days = [day - i * D for i in range(89, -1, -1)]
    avg7 = [(_sum7(dx, x) / 7) if _sum7(dx, x) else None for x in days]
    body.append(line_chart("Daily Solana DEX volume (90 days)" if en else "Dnevni Solana DEX volumen (90 dana)",
                           "Daily volume and its 7-day average." if en else "Dnevni volumen i njegov prosjek kroz 7 dana.",
                           _xs(days, lang), [(t["dexn"], C1, [dx.get(x) for x in days], None, None),
                                             ("7-day average" if en else "Prosjek 7 dana", C2, avg7, None, None)], lang=lang))
    tot = sum(p["v7"] for p in ps) or 1

    def rows_of(lst, total):
        out = []
        for i, p in enumerate(lst, 1):
            nm, what = plabel(p, lang)
            c = (p["v7"] / p["p7"] - 1) if p["p7"] else None
            out.append([str(i), f"<b>{nm}</b>" + (f"<br><span class=mut style='font-size:13px'>{what}</span>" if what else ""),
                        usd(p["y1"], lang), usd(p["v7"], lang), f"<span{_cls(c)}>{pct(c, lang)}</span>",
                        pct(p["v7"] / total, lang, signed=False, dec=1), spark(p["spark"])])
        return out
    head = ["#", t["platform"], t["yday"], t["d7"], t["chg"], t["sh"], t["m30"]]
    body.append(("<h2 class=s>Top Solana DEXs by volume</h2><p class=mut>Top 20 by 7-day volume. Several of the biggest are "
                 "proprietary market-maker pools that wallets and aggregators such as Jupiter route through, not sites you "
                 "trade on directly.</p>" if en else
                 "<h2 class=s>Najveći Solana DEX-ovi po volumenu</h2><p class=mut>Top 20 po volumenu u 7 dana. Nekoliko najvećih "
                 "su vlastiti bazeni market makera kroz koje novčanici i agregatori poput Jupitera usmjeravaju trgovine, a ne "
                 "stranice na kojima trguješ izravno.</p>") + _table(head, rows_of(ps[:20], tot), num_from=2))
    if ts_:
        ttot = sum(p["v7"] for p in ts_) or 1
        body.append(("<h2 class=s>Trading terminals and bots</h2><p class=mut>Apps meme coin traders click in, Solana volume "
                     "only. Their volume is already inside the DEX numbers above. Listed as data, not a recommendation: see "
                     "our <a href=/best-crypto-tools/trading-bots>trading bot comparison</a>.</p>" if en else
                     "<h2 class=s>Trading terminali i botovi</h2><p class=mut>Aplikacije u kojima trejderi meme coina klikaju, samo "
                     "Solana volumen. Taj volumen je već uključen u DEX brojke iznad. Popis je podatak, a ne preporuka: pogledaj "
                     "našu <a href=/hr/najbolji-kripto-alati/trading-botovi>usporedbu trading botova</a>.</p>")
                    + _table(head, rows_of(ts_[:15], ttot), num_from=2))
    body.append(_lockbox(lang))
    body.append(_more("dex", lang))
    tt = ts_[0] if ts_ else None
    if en:
        qa = [("What is Solana's DEX volume today?",
               f"Solana DEXs traded {usd(dx.get(day))} on {_date(day, lang)} and {usd(d7)} over the last 7 days ({pct(ch)} vs the week before)."),
              ("What is the biggest DEX on Solana?",
               f"By 7-day volume, {plabel(top, lang)[0]} with {usd(top['v7'])} ({pct(top['v7'] / tot, signed=False, dec=1)} of the total)."),
              ("What is the most used trading terminal on Solana?",
               f"By volume, {plabel(tt, lang)[0]} with {usd(tt['v7'])} in 7 days." if tt else "–"),
              ("What is a DEX?", "A decentralized exchange: you swap tokens straight from your own wallet, without an account. "
               "See the <a href=/glossary/dex>glossary</a>."),
              ("Where is the data from?", "DefiLlama's public Solana volumes, full UTC days, refreshed automatically.")]
        title = f"Solana DEX Volume Today ({_date(day, lang)}): Top DEXs & Trading Terminals | MemeSonar"
        desc = (f"Solana DEX volume: {usd(dx.get(day))} on {_date(day, lang)}, {usd(d7)} in 7 days ({pct(ch)}). Every Solana DEX and trading "
                "terminal ranked by volume, with 90-day chart. Updated daily.")
    else:
        qa = [("Koliki je Solana DEX volumen danas?",
               f"Solana DEX-ovi trgovali su {usd(dx.get(day), lang)} dana {_date(day, lang)} i {usd(d7, lang)} u zadnjih 7 dana "
               f"({pct(ch, lang)} u odnosu na tjedan prije)."),
              ("Koji je najveći DEX na Solani?",
               f"Po volumenu u 7 dana {plabel(top, lang)[0]} s {usd(top['v7'], lang)} ({pct(top['v7'] / tot, lang, signed=False, dec=1)} ukupnog)."),
              ("Koji se trading terminal najviše koristi na Solani?",
               f"Po volumenu {plabel(tt, lang)[0]} s {usd(tt['v7'], lang)} u 7 dana." if tt else "–"),
              ("Što je DEX?", "Decentralizirana mjenjačnica: tokene mijenjaš izravno iz svog novčanika, bez računa. Pogledaj "
               "<a href=/hr/rjecnik/dex>rječnik</a>."),
              ("Odakle su podaci?", "Javni podaci DefiLlame za Solanu, puni UTC dani, osvježava se samo.")]
        title = f"Solana DEX volumen danas ({_date(day, lang)}): najveći DEX-ovi i terminali | MemeSonar"
        desc = (f"Solana DEX volumen: {_date(day, lang)} {usd(dx.get(day), lang)}, u 7 dana {usd(d7, lang)} ({pct(ch, lang)}). Svi Solana "
                "DEX-ovi i trading terminali po volumenu, s grafom za 90 dana. Osvježava se svaki dan.")
    body.append(_faq(qa, lang))
    body.append(f"<p class=mut style='margin-top:26px;font-size:13px'>{t['nf']}</p>")
    return _page("dex", lang, title, desc, "".join(body), qa, d)


# ---------- embeds --------------------------------------------------------------------------------------------------

def embed(name, lang):
    """Small standalone widget for other sites (iframe). noindex, links back to the full page."""
    d = snapshot()
    if not d or name not in EMBEDS:
        return None
    en = lang == "en"
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if name == "meme-season":
        if not d["regime"]:
            return None
        s = d["regime"][-1][1]
        inner = gauge(s, lang, small=True)
        title = "Meme coin season index" if en else "Indeks sezone meme coina"
        href = PAGES["season"][lang != "en"]
    else:
        ps = d["plats"]["launchpad"]
        if not ps:
            return None
        tot = sum(p["v7"] for p in ps) or 1
        cols = [C1, C2, C3]
        rows = "".join(f"<div class=r><i style='background:{cols[i]}'></i><span>{plabel(p, lang)[0]}</span>"
                       f"<b>{pct(p['v7'] / tot, lang, False, 1)}</b><em>{usd(p['v7'], lang)}</em></div>" for i, p in enumerate(ps[:3]))
        bar = "".join(f"<i style='width:{100 * p['v7'] / tot:.2f}%;background:{cols[i]}'></i>" for i, p in enumerate(ps[:3]))
        inner = f"<div class=shb>{bar}</div>{rows}"
        title = "Solana launchpads, 7-day market share" if en else "Solana launchpadi, udio u 7 dana"
        href = PAGES["launchpads"][lang != "en"]
    return f"""<!doctype html><html lang={lang}><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta name=robots content="noindex,follow"><title>{esc(title)} | MemeSonar</title><link rel=canonical href="{base}{href}">
<style>body{{margin:0;font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#0b1220;background:#fff}}
.w{{border:1px solid #e8ebf2;border-radius:16px;padding:14px 16px;max-width:400px;box-sizing:border-box}}h1{{font-size:15px;margin:0 0 8px}}
.gauge{{text-align:center}}.gauge svg{{width:100%;max-width:240px;height:auto;display:block;margin:0 auto}}
.gauge b{{display:block;font-size:40px;line-height:1;margin-top:-6px}}.gauge .gl2{{font-size:13px;font-weight:650;text-transform:uppercase;letter-spacing:.06em}}
.shb{{display:flex;height:22px;border-radius:8px;overflow:hidden;gap:2px;margin:4px 0 10px;background:#c3c7d0}}.shb i{{display:block}}
.r{{display:grid;grid-template-columns:12px 1fr auto 70px;gap:8px;align-items:center;margin:5px 0;font-size:14px}}.r i{{width:12px;height:12px;border-radius:3px}}
.r em{{font-style:normal;color:#5b6474;text-align:right}}.f{{display:flex;justify-content:space-between;font-size:12px;color:#5b6474;margin-top:8px}}
.f a{{color:#4f46e5;font-weight:600;text-decoration:none}}</style></head><body><div class=w><h1>{esc(title)}</h1>{inner}
<div class=f><span>{_date(d['day'], lang)}</span><a href="{base}{href}" target=_blank rel=noopener>MemeSonar ↗</a></div></div></body></html>"""


# ---------- routing, nav, sitemap -----------------------------------------------------------------------------------

FNS = {"market": market, "launchpads": launchpads, "besttime": besttime, "season": season, "dex": dex}
_BY_PATH = {p: (k, "en" if i == 0 else "hr") for k, ps in PAGES.items() for i, p in enumerate(ps)}


def match(path):
    """A zero-argument page function for a path this module serves, or None."""
    p = path.rstrip("/") or path
    if p in _BY_PATH:
        k, lang = _BY_PATH[p]
        return lambda: FNS[k](lang)
    for pre, lang in (("/embed/", "en"), ("/hr/embed/", "hr")):
        if p.startswith(pre) and p[len(pre):] in EMBEDS:
            name = p[len(pre):]
            return lambda: embed(name, lang)
    return None


def nav_items(lang):
    """One menu row only (under Meme coins): the hub. The other market pages hang off the hub, the footer row and the
    sitemap, so the menu does not grow by five items."""
    lang = "en" if lang == "en" else "hr"
    n, dsc = (("Market data", "Volume, season index, best time to trade") if lang == "en" else
              ("Podaci o tržištu", "Volumen, indeks sezone, najbolje vrijeme"))
    return [("coins", PAGES["market"][lang != "en"], n, dsc)]


def subnav(key, lang):
    """Chip row under the title of every market page: the hub and its sub-pages."""
    items = "".join(f"<a href={PAGES[k][lang != 'en']}{' style=\'border-color:var(--acc);color:var(--acc)\'' if k == key else ''}>"
                    f"{esc(NAV[lang][k][0])}</a>" for k in NAV[lang])
    return f"<div class=chips style='margin:-8px 0 22px'>{items}</div>"


def urls():
    return [(en, hr, "0.8") for en, hr in PAGES.values()]


ROBOTS = tuple(p for ps in PAGES.values() for p in ps) + ("/embed/", "/hr/embed/")


def warm():
    """Fill the cache in the background at start, so the first visitor does not wait."""
    threading.Thread(target=snapshot, daemon=True).start()
