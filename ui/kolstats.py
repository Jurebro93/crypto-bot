"""Honest public statistics of one X account or Telegram channel, from kol.db (9.11.2026, SEO plan 7.11.).

The private score (kol/score.py) counts a call as a hit when the 24 h candle wick reached +50 %; on meme coins a wick
is not a sale anyone made, and accounts with 100 % such "hits" had median 24 h returns of -84 to -99 %. The public
pages therefore show tradable outcomes only, on CLEAN calls:
  - kind 'call' (not bot posts, brags, warnings, wallet swaps), outcome measured (max24 not NULL), not marked bad;
  - not from an account flagged as a bot;
  - not found through outcome-selected sources (kol_win, kol_search, backfill, kol_trend, x_buzz: those searches
    start from tokens that already rose, so every call they return looks good by construction);
  - not a late call (pre2h >= 1.0: the price had already doubled in the 2 h before the post);
  - older than the public delay (fresh calls are for members).
Metrics: n, share with the price higher 1 h after the post (up1h), share that reached +15 % within 24 h (hit15), median
24 h return (med24), share that fell 90 %+ (rug), best and worst 24 h return, per-month history, time-of-day split.
Fewer than MIN_CLEAN clean calls = "premalo podataka": the page says so, carries noindex and makes no claim.
"""
import json
import sqlite3
import statistics
import time

MIN_CLEAN = 10
BIASED_SOURCES = ("kol_win", "kol_search", "backfill", "kol_trend", "x_buzz")
PUBLIC_DELAY_S = 86400
HIT = 0.15
RUG = -0.9


def _bots(con):
    try:
        return {h for (h,) in con.execute("SELECT handle FROM kols WHERE COALESCE(bot, 0) = 1")}
    except sqlite3.OperationalError:
        return set()


def clean_calls(con, handle, now=None):
    """[dict(ts, token, symbol, url, mcap0, r1h, r24h, max24)] of the clean, measured calls of one handle."""
    now = now or time.time()
    q = ",".join("?" * len(BIASED_SOURCES))
    try:
        rows = con.execute(f"""SELECT ts, token, symbol, url, mcap0, r1h, r24h, max24 FROM calls
            WHERE handle = ? AND kind = 'call' AND max24 IS NOT NULL AND bad IS NULL AND ts < ?
              AND COALESCE(pre2h, 0) < 1.0 AND COALESCE(source, '') NOT IN ({q}) ORDER BY ts DESC""",
                           (handle, int(now - PUBLIC_DELAY_S), *BIASED_SOURCES)).fetchall()
    except sqlite3.OperationalError:
        return []
    keys = ("ts", "token", "symbol", "url", "mcap0", "r1h", "r24h", "max24")
    return [dict(zip(keys, r)) for r in rows]


def _share(xs, pred):
    xs = [x for x in xs if x is not None]
    return (sum(1 for x in xs if pred(x)) / len(xs)) if xs else None


def stats(calls, now=None):
    """The honest numbers of a list of clean calls (see module doc). Always returns a dict; n may be 0."""
    now = now or time.time()
    r1 = [c["r1h"] for c in calls]
    r24 = [c["r24h"] for c in calls]
    mx = [c["max24"] for c in calls]
    with24 = [c for c in calls if c["r24h"] is not None]
    months = {}
    for c in calls:
        m = time.strftime("%Y-%m", time.gmtime(c["ts"]))
        d = months.setdefault(m, {"month": m, "n": 0, "hit15": 0, "rug": 0, "r24": []})
        d["n"] += 1
        d["hit15"] += (c["max24"] or 0) >= HIT
        d["rug"] += c["r24h"] is not None and c["r24h"] <= RUG
        if c["r24h"] is not None:
            d["r24"].append(c["r24h"])
    hist = []
    for m in sorted(months):
        d = months[m]
        hist.append({"month": m, "n": d["n"], "hit15": d["hit15"] / d["n"], "rug": d["rug"] / d["n"],
                     "med24": statistics.median(d["r24"]) if d["r24"] else None})
    from kol import sessions
    sess = {}
    for c in calls:
        s = sessions.session_of(c["ts"])
        sess[s] = sess.get(s, 0) + 1
    first = min((c["ts"] for c in calls), default=None)
    return {
        "n": len(calls), "enough": len(calls) >= MIN_CLEAN,
        "up1h": _share(r1, lambda x: x > 0), "hit15": _share(mx, lambda x: x >= HIT),
        "med24": statistics.median([x for x in r24 if x is not None]) if any(x is not None for x in r24) else None,
        "med1h": statistics.median([x for x in r1 if x is not None]) if any(x is not None for x in r1) else None,
        "rug": _share(r24, lambda x: x <= RUG),
        "best": max(with24, key=lambda c: c["r24h"]) if with24 else None,
        "worst": min(with24, key=lambda c: c["r24h"]) if with24 else None,
        "months": hist, "sessions": sess, "since": first,
    }


def baseline(con, now=None, min_n=MIN_CLEAN, cache=None):
    """Median up1h / hit15 / med24 across every account with at least min_n clean calls: the bar a profile is
    compared with ("isto kao prosjek" is the honest default). Cached for the process for an hour."""
    now = now or time.time()
    cache = _BASE if cache is None else cache
    if cache.get("ts", 0) > now - 3600 and cache.get("v"):
        return cache["v"]
    bots = _bots(con)
    q = ",".join("?" * len(BIASED_SOURCES))
    try:
        rows = con.execute(f"""SELECT handle, r1h, r24h, max24 FROM calls WHERE kind = 'call' AND max24 IS NOT NULL
            AND bad IS NULL AND ts < ? AND COALESCE(pre2h, 0) < 1.0 AND COALESCE(source, '') NOT IN ({q})
            AND handle NOT LIKE 'w:%'""", (int(now - PUBLIC_DELAY_S), *BIASED_SOURCES)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    by = {}
    for h, r1, r24, mx in rows:
        if h in bots:
            continue
        by.setdefault(h, []).append((r1, r24, mx))
    ups, hits, meds = [], [], []
    for h, v in by.items():
        if len(v) < min_n:
            continue
        u = _share([x[0] for x in v], lambda x: x > 0)
        hh = _share([x[2] for x in v], lambda x: x >= HIT)
        r = [x[1] for x in v if x[1] is not None]
        if u is not None:
            ups.append(u)
        if hh is not None:
            hits.append(hh)
        if r:
            meds.append(statistics.median(r))
    v = {"accounts": len([1 for x in by.values() if len(x) >= min_n]),
         "up1h": statistics.median(ups) if ups else None, "hit15": statistics.median(hits) if hits else None,
         "med24": statistics.median(meds) if meds else None}
    cache["ts"], cache["v"] = now, v
    return v


_BASE = {}


def clean_counts(con, now=None, prefix=None):
    """{handle: clean measured calls} for every non-bot handle (prefix 'tg:' = Telegram channels only, '' = X only)."""
    now = now or time.time()
    bots = _bots(con)
    q = ",".join("?" * len(BIASED_SOURCES))
    try:
        rows = con.execute(f"""SELECT handle, COUNT(*) FROM calls WHERE kind = 'call' AND max24 IS NOT NULL
            AND bad IS NULL AND ts < ? AND COALESCE(pre2h, 0) < 1.0 AND COALESCE(source, '') NOT IN ({q})
            AND handle NOT LIKE 'w:%' GROUP BY handle""", (int(now - PUBLIC_DELAY_S), *BIASED_SOURCES)).fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for h, n in rows:
        if h in bots:
            continue
        if prefix == "tg:" and not h.startswith("tg:"):
            continue
        if prefix == "" and h.startswith("tg:"):
            continue
        out[h] = n
    return out


def channel_rows(con, now=None, min_n=MIN_CLEAN):
    """Telegram channels with at least min_n clean calls, with their honest stats, best first by up1h then n."""
    counts = clean_counts(con, now, prefix="tg:")
    out = []
    for h, n in counts.items():
        if n < min_n:
            continue
        s = stats(clean_calls(con, h, now), now)
        try:
            r = con.execute("SELECT name, followers, stats FROM kols WHERE handle = ?", (h,)).fetchone()
        except sqlite3.OperationalError:
            r = None
        ks = json.loads((r[2] if r else None) or "{}")
        per_day = None
        if s["since"] and (now or time.time()) - s["since"] > 86400:
            per_day = ks.get("calls", s["n"]) / (((now or time.time()) - s["since"]) / 86400)
        out.append({"handle": h, "channel": h[3:], "title": r[0] if r else None, "subs": r[1] if r else None,
                    "per_day": per_day, **s})
    out.sort(key=lambda r: (-(r["up1h"] or 0), -r["n"]))
    return out


def pct(x, signed=False):
    if x is None:
        return "–"
    return f"{x * 100:+.0f}%" if signed else f"{x * 100:.0f}%"


def verdict(s, base, lang):
    """One honest sentence: what the clean calls say, compared with the median account, or 'premalo podataka'."""
    if not s["enough"]:
        return ({"en": "Too little data: {n} measured calls so far (we need {m} before we say anything about an "
                       "account). The page is updated as calls are measured.",
                 "hr": "Premalo podataka: dosad {n} izmjerenih poziva (treba nam {m} prije nego išta kažemo o računu). "
                       "Stranica se osvježava kako se pozivi mjere."}[lang]).format(n=s["n"], m=MIN_CLEAN)
    b_up = base.get("up1h")
    better = s["up1h"] is not None and b_up is not None and s["up1h"] > b_up + 0.05
    worse = s["up1h"] is not None and b_up is not None and s["up1h"] < b_up - 0.05
    if lang == "en":
        cmp_ = ("better than the median account" if better else "worse than the median account" if worse else
                "about the same as the median account")
        return (f"On {s['n']} clean measured calls, the price was higher one hour after the post {pct(s['up1h'])} of "
                f"the time ({cmp_}: {pct(b_up)} across {base.get('accounts', 0)} accounts), {pct(s['hit15'])} reached "
                f"+15 % within 24 hours, the median 24 h result was {pct(s['med24'], True)} and {pct(s['rug'])} of the "
                f"tokens fell 90 % or more. Past calls, not a prediction.")
    cmp_ = ("bolje od medijana računa" if better else "lošije od medijana računa" if worse else "otprilike kao medijan računa")
    return (f"Na {s['n']} čistih izmjerenih poziva cijena je sat nakon objave bila viša u {pct(s['up1h'])} slučajeva "
            f"({cmp_}: {pct(b_up)} na {base.get('accounts', 0)} računa), {pct(s['hit15'])} ih je doseglo +15 % unutar "
            f"24 sata, medijan rezultata nakon 24 h je {pct(s['med24'], True)}, a {pct(s['rug'])} tokena palo je 90 % ili "
            f"više. Prošli pozivi, ne predviđanje.")
