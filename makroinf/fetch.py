"""Posts of the measured accounts (twitterapi.io advanced search, Latest).

Backfill (the pilot), per account, units in fetch_log so a deploy resumes where it stopped:
  zadnjih          the last 100 posts of any kind (5 pages, no retweets): context and tone, the activity check
  mj:YYYY-MM:a/b   MONTHLY QUOTAS over 12 months: "from:<h> (<macro keywords>) -filter:retweets" in each half of each
                   month, one page (~20 posts) each, so the year is covered evenly (~40 macro posts a month) instead of
                   the newest 300 hits only (the critic: "mjesečne kvote objava")
Daily (after the pilot): the macro query since the newest stored post of the account (<= incr_pages pages).
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


def units_left(con, c, handle, now):
    """The backfill units not done yet. A month that starts after the account's backfill began is not a unit: the
    daily macro query covers it (no second, paid read of the same posts)."""
    rows = store.q(con, "SELECT unit, done_ts FROM fetch_log WHERE handle = ?", (handle,))
    done = {u for u, _t in rows}
    first = min((t for _u, t in rows if t), default=None)
    todo = [("zadnjih", None, None)] if "zadnjih" not in done else []
    todo += [u for u in month_units(now, c["months"]) if u[0] not in done and (first is None or u[1] < first)]
    return todo


def backfill(con, c, now=None, get=None, log=print, deadline=None, ph=None, handles=None):
    """Work through the backfill units, round-robin over the accounts (one unit each per turn, so a cap or a deadline
    leaves every account partly covered instead of a few fully). Returns {"requests", "new", "left", "cap"}."""
    now = int(now or time.time())
    out = {"units": 0, "new": 0, "left": 0, "cap": None}
    if not xapi.has_key(get):
        out["cap"] = "nema ključa"
        return out
    accs = handles if handles is not None else [h for h, _c, _s in racuni.active(con)]
    queues = {h: units_left(con, c, h, now) for h in accs}
    while any(queues.values()):
        for h in list(queues):
            if not queues[h]:
                continue
            if deadline and time.time() > deadline:
                out["left"] = sum(len(v) for v in queues.values())
                return out
            unit, a, b = queues[h].pop(0)
            p = ph or store.phase(con, "twapi")
            try:
                if unit == "zadnjih":
                    new, seen = _pages(con, c, f"from:{h} -filter:retweets", c["last_pages"], p, h, "zadnjih", now, get)
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
            con.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?,?,?)", (h, unit, int(time.time()), seen,
                                                                                  None, p))
            con.commit()
            out["units"] += 1
            out["new"] += new
    out["left"] = 0
    return out


def incremental(con, c, now=None, get=None, log=print, deadline=None):
    """The day's macro posts of every active account since its newest stored post (<= incr_pages pages)."""
    now = int(now or time.time())
    out = {"accounts": 0, "new": 0, "cap": None}
    if not xapi.has_key(get):
        out["cap"] = "nema ključa"
        return out
    for h, _cat, _src in racuni.active(con):
        if deadline and time.time() > deadline:
            break
        last = store.q(con, "SELECT MAX(ts) FROM tweets WHERE handle = ?", (h,))
        since = int((last[0][0] if last and last[0][0] else now - 7 * 86400))
        q = f"from:{h} {KW_QUERY} -filter:retweets since_time:{since + 1}"
        try:
            new, _seen = _pages(con, c, q, c["incr_pages"], store.phase(con, "twapi"), h, "dnevno", now, get,
                                stop_before=since)
        except xapi.CapReached as e:
            out["cap"] = str(e)
            break
        except Exception as e:  # noqa: BLE001
            log(store.PREFIX + f"dnevni dohvat @{h}: {type(e).__name__}: {str(e)[:100]}")
            continue
        out["accounts"] += 1
        out["new"] += new
        con.commit()
    return out
