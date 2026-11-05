"""5.11. (Nicholas): a token's own socials as a signal. What DexScreener lists for the pair (info.socials, websites,
imageUrl/header = paid "Enhanced Token Info") plus a free look at the Telegram preview (t.me/s/<channel>:
subscribers, last post, posts on the page). An X link that is a tweet or a search page is not a profile (the Aren
case: a random post about a leopard). Features (0-1) for hype/score.py and confidence; strategies "Ozbiljan projekt"
and "Sumnjivi socijali" buy on them so the claim is measured, not believed.
"""
import json
import re
import sqlite3
import time
import urllib.parse

CACHE_S = 6 * 3600
_SUBS = re.compile(r'tgme_(?:header_counter|page_extra)">\s*([\d.,]+)\s*([KkMm]?)\s*(subscribers|members)', re.S)
_TIMES = re.compile(r'<time datetime="([^"]+)"')


def classify(info):
    """DexScreener pair info -> {x: profile|tweet|search|none, x_url, tg, tg_handle, web, paid}."""
    info = info or {}
    out = {"x": "none", "x_url": None, "tg": False, "tg_handle": None, "web": bool(info.get("websites")),
           "paid": bool(info.get("imageUrl") and info.get("header"))}
    for s in info.get("socials") or []:
        url, typ = (s.get("url") or ""), (s.get("type") or "").lower()
        if typ == "twitter" or "x.com/" in url or "twitter.com/" in url:
            out["x_url"] = url
            path = urllib.parse.urlparse(url).path.strip("/")
            if "/status/" in url or "/i/" in path:
                out["x"] = "tweet"
            elif "/search" in url or "q=" in url or not path or path in ("home", "explore"):
                out["x"] = "search"
            elif "/communities/" in url:
                out["x"] = "community"
            else:
                out["x"] = "profile"
        elif typ == "telegram" or "t.me/" in url:
            out["tg"] = True
            h = urllib.parse.urlparse(url).path.strip("/").split("/")[0]
            out["tg_handle"] = h.lstrip("+") if h and not h.startswith("+") else None   # +invite links are groups
    return out


def _num(s, suf):
    v = float(s.replace(",", ""))
    return int(v * {"k": 1e3, "m": 1e6}.get(suf.lower(), 1))


def telegram_probe(handle, fetch=None, now=None):
    """{subs, last_post_age_h, posts_7d, kind} from the public preview (channel) or the join page (group); None when
    neither exists. One HTTP request, no key."""
    from event_calendar.http import USER_AGENT
    import urllib.request
    now = now or time.time()
    fetch = fetch or (lambda url: urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=15).read().decode("utf-8", "replace"))
    try:
        page = fetch(f"https://t.me/s/{handle}")
    except Exception:  # noqa: BLE001
        page = ""
    m = _SUBS.search(page or "")
    times = _TIMES.findall(page or "")
    if times:
        import datetime as dt
        last = max(dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() for t in times)
        week = sum(1 for t in times if now - dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() <= 7 * 86400)
        return {"kind": "channel", "subs": _num(m.group(1), m.group(2)) if m else None,
                "last_post_age_h": round((now - last) / 3600, 1), "posts_7d": week}
    try:
        page = fetch(f"https://t.me/{handle}")
    except Exception:  # noqa: BLE001
        return None
    m = _SUBS.search(page or "")
    if not m:
        return None
    return {"kind": "group" if m.group(3) == "members" else "channel", "subs": _num(m.group(1), m.group(2)),
            "last_post_age_h": None, "posts_7d": None}


def features(cls, tg=None):
    """0-1 features. socijali_x: profile 1, community 0.6, tweet 0.3, search/none 0. socijali_tg: by size and
    activity. socijali_placeni: paid DexScreener profile. ozbiljan_projekt: paid + real X profile + Telegram with
    50+ members and (for a channel) a post in the last 24 h. sumnjivi_socijali: X is a tweet/search page, or no
    Telegram at all."""
    x = {"profile": 1.0, "community": 0.6, "tweet": 0.3}.get(cls["x"], 0.0)
    tgf = 0.0
    if cls["tg"]:
        tgf = 0.2
        if tg and tg.get("subs"):
            tgf = 0.4 if tg["subs"] >= 20 else 0.25
            if tg["subs"] >= 100:
                tgf = 0.6
            if tg["subs"] >= 500:
                tgf = 0.8
            if tg.get("last_post_age_h") is not None and tg["last_post_age_h"] <= 24:
                tgf = min(1.0, tgf + 0.2)
    active_tg = bool(tg and (tg.get("subs") or 0) >= 50 and (tg.get("kind") == "group" or (tg.get("last_post_age_h") or 999) <= 24))
    serious = 1.0 if (cls["paid"] and cls["x"] == "profile" and active_tg) else 0.0
    suspicious = 1.0 if (cls["x"] in ("tweet", "search") or not cls["tg"]) else 0.0
    return {"socijali_x": x, "socijali_tg": round(tgf, 2), "socijali_placeni": 1.0 if cls["paid"] else 0.0,
            "ozbiljan_projekt": serious, "sumnjivi_socijali": suspicious}


def describe(cls, tg=None):
    """One sentence for Za/Protiv on the token page."""
    x = {"profile": "pravi X profil", "community": "X zajednica", "tweet": "X link je tuđi tweet, ne profil",
         "search": "X link je stranica pretrage, ne profil", "none": "bez X-a"}[cls["x"]]
    if cls["tg"] and tg:
        t = f"Telegram {tg.get('subs') or '?'} članova" + (f", zadnji post prije {tg['last_post_age_h']:.0f} h" if tg.get("last_post_age_h") is not None else "")
    elif cls["tg"]:
        t = "Telegram (nije provjeren)"
    else:
        t = "bez Telegrama"
    return f"{x}; {t}; {'plaćeni DexScreener profil' if cls['paid'] else 'besplatni profil'}" + ("; web" if cls["web"] else "")


# ---- cache in hype.db (one probe per token per 6 h) ----

def _table(con):
    con.execute("CREATE TABLE IF NOT EXISTS socials (token TEXT PRIMARY KEY, ts INTEGER, data TEXT)")


def cached(con, token, now=None):
    _table(con)
    r = con.execute("SELECT ts, data FROM socials WHERE token=?", (token,)).fetchone()
    if r and (now or time.time()) - r[0] < CACHE_S:
        try:
            return json.loads(r[1])
        except ValueError:
            return None
    return None


def probe_and_store(con, token, info, now=None, fetch=None):
    """features + detail for one token, from cache or one Telegram request."""
    now = now or time.time()
    c = cached(con, token, now)
    if c is not None:
        return c
    cls = classify(info)
    tg = telegram_probe(cls["tg_handle"], fetch, now) if cls.get("tg_handle") else None
    d = {"cls": cls, "tg": tg, "features": features(cls, tg), "opis": describe(cls, tg)}
    _table(con)
    con.execute("INSERT OR REPLACE INTO socials VALUES (?,?,?)", (token, int(now), json.dumps(d)))
    con.commit()
    return d
