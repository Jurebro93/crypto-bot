"""Posts of the measured accounts (twitterapi.io advanced search, Latest).

Backfill, per account, units in fetch_log so a deploy resumes where it stopped:
  zadnjih          the last 200 posts of any kind (last_pages = 10 pages, no retweets): context and tone, the activity
                   and regularity check; an account found by discovery already has its newest page (src proba), so its
                   zadnjih goes on from before it (that page is not bought twice)
  zadnjih+         accounts of the pilot (5 pages then): the posts 101-200, from before the oldest one stored
  mj:YYYY-MM:a/b   MONTHLY QUOTAS over 18 months: "from:<h> (<macro keywords>) -filter:retweets" in each half of each
                   month, one page (~20 posts) each (the critic: "mjesečne kvote objava"). Order: the first half of
                   every month (newest first, so every month gets a window), then the second halves; at depth_posts
                   (500) market posts an account the rest is not bought (fetch_log phase "dubina_puna"). A window the
                   zadnjih posts already cover is not bought either ("pokriveno"); a partly covered one ends where they
                   start.
16.11. (the owner's second wave, 30k+ accounts: "smaller accounts; keep cost down"): an account of that wave (source
prosirenje2) gets the last 200 posts + up to wave2_depth_posts (300) market posts over wave2_months (12) (cfg_for).
Daily (15.11. navečer, the owner: "svaki dan skrepat njihove nove postove"): every active account once in incr_every_s,
the macro query since its newest stored post (<= incr_pages pages), the most regular accounts first, per account in
daily_fetch so a round that runs out of time leaves the rest for the next round (not for the next day). Inactive
accounts (no post in 30 days) are asked once a week; a new post makes them active again.
No retweets (the query and the parser); replies are kept (the classifier decides whether they state a view); quoted
posts are stored with their text. Dedup by post id (INSERT OR IGNORE: the first unit that saw a post keeps it).
fetched_ts is when WE had the post: the prospective index uses it as the availability time (no look-ahead).
"""
import calendar
import re
import time

from makroinf import racuni, store, xapi

KEYWORDS = ("btc", "bitcoin", "eth", "ethereum", "sol", "solana", "alts", "altcoins", "altseason", "memes", "memecoins",
            "bull", "bullish", "bear", "bearish", "bottom", "top", "crash", "cycle", "ath", "rally", "dump", "breakout",
            "macro", "buy", "sell")
KW_QUERY = "(" + " OR ".join(KEYWORDS) + ")"
# the local prefilter before the LLM (cheap): the same words, price levels ("60k", "$95,000"), "market"
KW_RE = re.compile(r"\b(btc|bitcoin|eth|ethereum|sol|solana|alts?|altcoins?|altseason|memes?|memecoins?|crypto|"
                   r"bull\w*|bear\w*|bottom\w*|top(?:ped|s)?|crash\w*|cycle|ath|rally|dump\w*|pump\w*|breakout|macro|"
                   r"market|support|resistance|target|long|short|buy|sell|recession|liquidity|fed|rates?)\b|"
                   r"\$?\d{2,3}(?:[.,]\d)?\s?k\b|\$\d{1,3}(?:,\d{3})+", re.I)


def kw_pass(text, quoted=None):
    return bool(KW_RE.search(f"{text or ''} {quoted or ''}"))


def month_units(now, months):
    """['mj:YYYY-MM:a', 'mj:YYYY-MM:b', ...] newest month first, with their [since, until) windows."""
    t = time.gmtime(int(now))
    y, m = t.tm_year, t.tm_mon
    out = []
    for _ in range(int(months)):
        start = calendar.timegm((y, m, 1, 0, 0, 0))
        mid = calendar.timegm((y, m, 16, 0, 0, 0))
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = min(calendar.timegm((ny, nm, 1, 0, 0, 0)), int(now))
        if mid < end:
            out.append((f"mj:{y:04d}-{m:02d}:b", mid, end))
        out.append((f"mj:{y:04d}-{m:02d}:a", start, min(mid, end)))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def parse(t, handle_hint=None):
    """One twitterapi.io post -> row dict, or None (retweet / no id / no time)."""
    if not isinstance(t, dict) or t.get("noResults") or t.get("isRetweet") or t.get("retweeted_tweet"):
        return None
    from kol.collect import tweet_ts
    a = t.get("author") or {}
    h = a.get("userName") or handle_hint
    tid = str(t.get("id") or "")
    ts = tweet_ts(t.get("createdAt"))
    if not tid or not ts or not h:
        return None
    qt = t.get("quoted_tweet") if isinstance(t.get("quoted_tweet"), dict) else None
    qh = ((qt or {}).get("author") or {}).get("userName") if qt else None

    def i(k):
        try:
            return int(t.get(k)) if t.get(k) is not None else None
        except (TypeError, ValueError):
            return None
    return {"id": tid, "handle": h, "ts": int(ts), "text": (t.get("text") or t.get("fullText") or "")[:2000],
            "quoted_text": ((qt or {}).get("text") or "")[:1000] or None, "quoted_handle": qh, "lang": t.get("lang"),
            "likes": i("likeCount"), "retweets": i("retweetCount"), "replies": i("replyCount"), "quotes": i("quoteCount"),
            "views": i("viewCount"), "is_reply": 1 if t.get("isReply") else 0,
            "url": t.get("url") or f"https://x.com/{h}/status/{tid}"}


def save(con, rows, src, now):
    n = 0
    for r in rows:
        if not r:
            continue
        cur = con.execute("INSERT OR IGNORE INTO tweets (id, handle, ts, text, quoted_text, quoted_handle, lang, likes, "
                          "retweets, replies, quotes, views, is_reply, url, src, fetched_ts, kw) VALUES "
                          "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (r["id"], r["handle"], r["ts"], r["text"], r["quoted_text"], r["quoted_handle"], r["lang"],
                           r["likes"], r["retweets"], r["replies"], r["quotes"], r["views"], r["is_reply"], r["url"], src,
                           int(now), 1 if kw_pass(r["text"], r["quoted_text"]) else 0))
        n += cur.rowcount
    return n


def _pages(con, c, query, pages, ph, handle, src, now, get, stop_before=None):
    """Up to `pages` pages of one query; (new posts stored, posts seen). Raises xapi.CapReached at the cap."""
    cursor, seen, new = "", 0, 0
    for _ in range(int(pages)):
        tw, cursor = xapi.search_page(con, query, cursor, ph, c, now, get, what=src.split(":")[0])
        rows = [parse(t, handle) for t in tw]
        rows = [r for r in rows if r and r["handle"].lower() == handle.lower()]
        seen += len(rows)
        new += save(con, rows, src, now)
        if not cursor or not tw or (stop_before and rows and min(r["ts"] for r in rows) <= stop_before):
            break
    return new, seen


LAST_SRC = ("zadnjih", "zadnjih+", "proba")   # complete samples of the newest posts (any kind)
REG_CAP = 8.0                                # market posts a day: more than this is not "more regular"


def market_units(now, months):
    """month_units in the fetch order: the first half of every month newest first, then the second halves."""
    us = month_units(now, months)
    return [u for u in us if u[0].endswith(":a")] + [u for u in us if u[0].endswith(":b")]


WAVE2 = "prosirenje2"   # accounts.source of the second wave (discover.step2)


def wave2_cfg(c):
    """The configuration with the second wave's depth (the last 200 posts + 300 market posts over 12 months)."""
    return {**c, "months": int(c.get("wave2_months") or c["months"]),
            "depth_posts": int(c.get("wave2_depth_posts") or c["depth_posts"]),
            "last_pages": int(c.get("wave2_last_pages") or c["last_pages"])}


def cfg_for(con, c, handle, wave2=None):
    """The configuration the account's backfill runs with: the second wave's accounts their own depth (wave2: the set
    of their handles when the caller already has it)."""
    if wave2 is None:
        wave2 = {h for (h,) in store.q(con, "SELECT handle FROM accounts WHERE handle = ? AND source = ?",
                                       (handle, WAVE2))}
    return wave2_cfg(c) if handle in wave2 else c


def units_left(con, c, handle, now):
    """The backfill units not done yet (c: the account's own configuration, cfg_for). A month that starts after the
    account's backfill began is not a unit: the daily macro query covers it (no second, paid read of the same posts)."""
    rows = store.q(con, "SELECT unit, done_ts, n FROM fetch_log WHERE handle = ?", (handle,))
    done = {u for u, _t, _n in rows}
    first = min((t for _u, t, _n in rows if t), default=None)
    want = int(c["last_pages"]) * int(c["page_posts"])
    todo = []
    if "zadnjih" not in done:
        todo.append(("zadnjih", None, None))
    elif "zadnjih+" not in done:
        n_last = next((n for u, _t, n in rows if u == "zadnjih"), 0) or 0
        if 5 * int(c["page_posts"]) - 10 <= n_last <= want - 10:   # the pilot's 100 and there were more
            todo.append(("zadnjih+", None, None))
    todo += [u for u in market_units(now, c["months"]) if u[0] not in done and (first is None or u[1] < first)]
    return todo


def depth(con, handle):
    """Market (keyword) posts of the account stored by the backfill (the daily ones not counted)."""
    r = store.q(con, "SELECT COUNT(*) FROM tweets WHERE handle = ? AND kw = 1 AND src <> 'dnevno'", (handle,))
    return int(r[0][0]) if r else 0


def _oldest_last(con, handle):
    r = store.q(con, f"SELECT MIN(ts), COUNT(*) FROM tweets WHERE handle = ? AND src IN "
                     f"({','.join('?' * len(LAST_SRC))})", (handle, *LAST_SRC))
    return (r[0][0], r[0][1]) if r and r[0][1] else (None, 0)


def _mark(con, h, unit, p, n=0):
    con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?,?,?)", (h, unit, int(time.time()), n, None, p))


def backfill(con, c, now=None, get=None, log=print, deadline=None, ph=None, handles=None, tier=None):
    """Work through the backfill units, round-robin over the accounts (one unit each per turn, so a cap or a deadline
    leaves every account partly covered instead of a few fully). handles in priority order (the most regular first);
    tier: round-robin inside groups of that many (the first group done before the next). Returns {"units", "new",
    "left", "cap"}."""
    now = int(now or time.time())
    out = {"units": 0, "new": 0, "left": 0, "cap": None}
    if not xapi.has_key(get):
        out["cap"] = "nema ključa"
        return out
    accs = list(handles if handles is not None else [h for h, _c, _s in racuni.active(con)])
    groups = [accs[k:k + int(tier)] for k in range(0, len(accs), int(tier))] if tier else [accs]
    w2 = {h for (h,) in store.q(con, "SELECT handle FROM accounts WHERE source = ?", (WAVE2,))}
    c0, c2 = c, (wave2_cfg(c) if w2 else c)   # the second wave's accounts: their own depth
    for gi, grp in enumerate(groups):
        queues = {h: units_left(con, c2 if h in w2 else c0, h, now) for h in grp}
        while any(queues.values()):
            for h in list(queues):
                if not queues[h]:
                    continue
                if deadline and time.time() > deadline:
                    out["left"] = sum(len(v) for v in queues.values()) + sum(
                        len(units_left(con, c2 if x in w2 else c0, x, now)) for g in groups[gi + 1:] for x in g)
                    return out
                unit, a, b = queues[h].pop(0)
                p = ph or store.phase(con, "twapi")
                c = c2 if h in w2 else c0
                cap_posts = int(c.get("depth_posts") or 0)
                if unit.startswith("mj:"):
                    if cap_posts and depth(con, h) >= cap_posts:   # deep enough: the rest is not bought
                        for u, _a, _b in [(unit, a, b)] + queues[h]:
                            _mark(con, h, u, "dubina_puna")
                        queues[h] = []
                        con.commit()
                        continue
                    z0, _zn = _oldest_last(con, h)
                    if z0 is not None and a >= z0:                 # the newest posts already hold this window
                        _mark(con, h, unit, "pokriveno")
                        con.commit()
                        continue
                    if z0 is not None and b > z0:
                        b = z0
                try:
                    if unit == "zadnjih":
                        z0, zn = _oldest_last(con, h)   # discovery's probe page: go on from before it
                        pages = max(0, int(c["last_pages"]) - -(-zn // int(c["page_posts"]))) if zn else int(c["last_pages"])
                        q = f"from:{h} -filter:retweets" + (f" until_time:{int(z0)}" if zn else "")
                        new, seen = _pages(con, c, q, pages, p, h, "zadnjih", now, get) if pages else (0, 0)
                        seen += zn
                    elif unit == "zadnjih+":
                        z0, zn = _oldest_last(con, h)
                        pages = max(1, -(-(int(c["last_pages"]) * int(c["page_posts"]) - zn) // int(c["page_posts"])))
                        q = f"from:{h} -filter:retweets" + (f" until_time:{int(z0)}" if z0 else "")
                        new, seen = _pages(con, c, q, pages, p, h, "zadnjih+", now, get)
                        seen += zn
                    else:
                        q = f"from:{h} {KW_QUERY} -filter:retweets since_time:{int(a)} until_time:{int(b)}"
                        new, seen = _pages(con, c, q, c["half_pages"], p, h, unit, now, get)
                except xapi.CapReached as e:
                    out["cap"] = str(e)
                    out["left"] = sum(len(v) for v in queues.values()) + 1
                    con.commit()
                    return out
                except Exception as e:  # noqa: BLE001 - a failed unit stays in the queue for the next round
                    log(store.PREFIX + f"dohvat @{h} {unit}: {type(e).__name__}: {str(e)[:100]}")
                    continue
                _mark(con, h, unit, p, seen)
                con.commit()
                out["units"] += 1
                out["new"] += new
    out["left"] = 0
    return out


def incremental(con, c, now=None, get=None, log=print, deadline=None, ph=None, handles=None):
    """The day's macro posts of every active account since its newest stored post (<= incr_pages pages): accounts
    not fetched in incr_every_s (daily_fetch), the most regular first, an inactive one once a week; an account whose
    backfill has not started yet waits for it (its zadnjih unit reads the same posts). Deadline-safe: what is left
    goes in the next round. Returns {"accounts", "new", "left", "cap", "reaktivirano"}."""
    now = int(now or time.time())
    out = {"accounts": 0, "new": 0, "left": 0, "cap": None, "reaktivirano": 0}
    if not xapi.has_key(get):
        out["cap"] = "nema ključa"
        return out
    every = int(c.get("incr_every_s") or 20 * 3600)
    last = dict(store.q(con, "SELECT handle, ts FROM daily_fetch"))
    started = {h for (h,) in store.q(con, "SELECT handle FROM fetch_log WHERE unit = 'zadnjih'")}
    rows = handles if handles is not None else racuni.by_regularity(con, ("aktivan", "neaktivan"))
    todo = []
    for h, st in rows:
        gap = 7 * 86400 if st == "neaktivan" else every
        if h in started and now - int(last.get(h) or 0) >= gap:
            todo.append((h, st))
    for k, (h, st) in enumerate(todo):
        if deadline and time.time() > deadline:
            out["left"] = len(todo) - k
            break
        r = store.q(con, "SELECT MAX(ts) FROM tweets WHERE handle = ?", (h,))
        since = int((r[0][0] if r and r[0][0] else now - 7 * 86400))
        q = f"from:{h} {KW_QUERY} -filter:retweets since_time:{since + 1}"
        try:
            new, _seen = _pages(con, c, q, c["incr_pages"], ph or store.phase(con, "twapi"), h, "dnevno", now, get,
                                stop_before=since)
        except xapi.CapReached as e:
            out["cap"] = str(e)
            out["left"] = len(todo) - k
            break
        except Exception as e:  # noqa: BLE001
            log(store.PREFIX + f"dnevni dohvat @{h}: {type(e).__name__}: {str(e)[:100]}")
            continue
        con.execute("INSERT OR REPLACE INTO daily_fetch VALUES (?,?,?)", (h, now, new))
        if st == "neaktivan" and new:
            con.execute("UPDATE accounts SET status = 'aktivan', why = 'opet objavljuje' WHERE handle = ? AND "
                        "status = 'neaktivan'", (h,))
            out["reaktivirano"] += 1
        out["accounts"] += 1
        out["new"] += new
        con.commit()
    return out


def regularity(con, h, now=None, n=100):
    """(posts a day, market share, regularity) of the account's newest complete posts (zadnjih / probe): regularity =
    market posts a day, capped at REG_CAP. None without 3 such posts."""
    rows = store.q(con, f"SELECT ts, kw, fetched_ts FROM tweets WHERE handle = ? AND src IN "
                        f"({','.join('?' * len(LAST_SRC))}) ORDER BY ts DESC LIMIT ?", (h, *LAST_SRC, int(n)))
    if len(rows) < 3:
        return None
    end = max(int(r[2] or r[0]) for r in rows)
    span_d = max(1.0, (end - rows[-1][0]) / 86400)
    posts_day = len(rows) / span_d
    share = sum(1 for r in rows if r[1]) / len(rows)
    return round(posts_day, 3), round(share, 3), round(min(posts_day * share, REG_CAP), 3)


def update_regularity(con, now=None):
    """accounts.posts_day / market_share / regularity of every measured account (local, no request)."""
    n = 0
    for (h,) in store.q(con, "SELECT handle FROM accounts WHERE status IN ('novo', 'aktivan', 'neaktivan')"):
        r = regularity(con, h, now)
        if r:
            con.execute("UPDATE accounts SET posts_day = ?, market_share = ?, regularity = ? WHERE handle = ?", (*r, h))
            n += 1
    con.commit()
    return n
