"""Calls from X: every tweet the bot already paid for (hype.db apify_cache), webhook mentions, and two small
searches of our own (follow-up on tokens that KOLs are calling, latest tweets of the best KOLs).

A call is one (tweet, token) pair. The token is any Solana CA in the tweet text; a token search also counts a
tweet that only writes the $TICKER, as match "ticker", when the tweet names no other CA.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import time

from hype.telegram import _CA, _TICKER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HYPE_DB = os.environ.get("HYPE_DB", os.path.join(ROOT, "hype.db"))
X_ACTOR = "apidojo/tweet-scraper"
CACHE_PREFIXES = ("x_buzz:", "kol_search:", "kol_timeline:")

# "15X on $ICOIN", "78.6x on my tg", "did a 20x", "115x $ICOIN" (post opens with the multiple): bragging about a
# past pump, not a call. "next 100x" inside a sentence stays a call.
_BRAG = re.compile(r"\b\d+(?:[.,]\d+)?\s?x\s+(?:on|from|up|in|with|done|already|secured|profit|gain|since)\b"
                   r"|\b(?:did|hit|printed|secured|called|up|done|made)\s+(?:a\s+|an\s+)?\d+(?:[.,]\d+)?\s?x\b"
                   r"|^\W*\d+(?:[.,]\d+)?\s?x\b", re.I)


def _int(x):
    try:
        return int(float(str(x).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def tweet_ts(s):
    """'Fri Oct 30 21:58:58 +0000 2026' or ISO -> unix seconds; None if unknown."""
    if not s:
        return None
    if isinstance(s, (int, float)):
        return int(s / 1000 if s > 1e12 else s)
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return int(dt.datetime.strptime(s.replace("Z", "+0000"), fmt).timestamp())
        except ValueError:
            pass
    return None


_HEX = re.compile(r"x?[0-9a-fA-F]+")


def cas_in(text):
    """Solana addresses in a post. An EVM address "0x<40 hex>" is not one: the base58 pattern used to pick up its
    tail "x<hex>" (the leading 0 is not base58) as a fake Solana token."""
    text = text or ""
    out = set()
    for m in _CA.finditer(text):
        c = m.group(0)
        if not any(ch.isdigit() for ch in c) or _HEX.fullmatch(c):
            continue
        if m.start() > 0 and text[m.start() - 1] == "0" and c[:1] in "xX":
            continue
        out.add(c)
    return sorted(out)


# "SCAM ALERT", "stay away, it'll rug": a warning about the token, not a call to buy it
_WARN = re.compile(r"scam alert|rug alert|honeypot alert|stay away|it.?ll rug|avoid this|do not buy|don.?t buy", re.I)


def kind_of(text):
    if _WARN.search(text or ""):
        return "warn"
    return "brag" if _BRAG.search(text or "") else "call"


def calls_from_tweet(t, target=None, symbol=None, source="x_buzz"):
    """List of call dicts for one scraped tweet. Retweets are skipped (the original author made the call)."""
    if not isinstance(t, dict) or t.get("noResults") or t.get("isRetweet"):
        return []
    a = t.get("author") or t.get("user") or {}
    handle = a.get("userName") or a.get("screen_name") or a.get("username")
    ts = tweet_ts(t.get("createdAt"))
    tid = str(t.get("id") or "")
    if not handle or not ts or not tid:
        return []
    text = t.get("fullText") or t.get("text") or ""
    found = cas_in(text)
    pairs = [(c, "ca") for c in found]
    if target and target not in found and not found and symbol:
        tickers = {x.upper() for x in _TICKER.findall(text)}
        if symbol.upper() in tickers:
            pairs.append((target, "ticker"))
    base = {"tweet_id": tid, "handle": handle, "ts": ts,
            "url": t.get("url") or f"https://x.com/{handle}/status/{tid}", "text": text[:600],
            "followers": _int(a.get("followers") or a.get("followersCount") or a.get("followers_count")),
            "likes": _int(t.get("likeCount")), "retweets": _int(t.get("retweetCount")), "views": _int(t.get("viewCount")),
            "kind": kind_of(text), "source": source, "symbol": symbol if target else None,
            "author": {"name": a.get("name"), "verified": bool(a.get("isBlueVerified") or a.get("isVerified"))}}
    return [dict(base, token=c, match=m, symbol=(symbol if c == target else None)) for c, m in pairs]


def _is_bot(con, handle):
    try:
        r = con.execute("SELECT bot FROM kols WHERE handle = ?", (handle,)).fetchone()
    except sqlite3.OperationalError:
        return False
    return bool(r and r[0])


def save(con, calls):
    """Insert new calls. Posts of accounts already flagged as automated (kol/bots.py) are stored as kind 'bot', so
    they never count as a KOL call, not even in the minutes before the next score run."""
    n = 0
    for c in calls:
        if c.get("kind") in ("call", "brag", "warn") and _is_bot(con, c["handle"]):
            c = dict(c, kind="bot")
        n += con.execute("""INSERT OR IGNORE INTO calls (tweet_id, token, handle, ts, url, text, followers, likes, retweets,
            views, kind, match, source, symbol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (c["tweet_id"], c["token"], c["handle"], c["ts"], c["url"], c["text"], c["followers"],
                          c["likes"], c["retweets"], c["views"], c["kind"], c["match"], c["source"],
                          c["symbol"])).rowcount
        au = c.get("author") or {}
        con.execute("""INSERT INTO kols (handle, name, followers, verified, first_seen, last_seen) VALUES (?,?,?,?,?,?)
            ON CONFLICT (handle) DO UPDATE SET
              name=COALESCE(excluded.name, name),
              followers=CASE WHEN excluded.last_seen >= last_seen OR followers IS NULL OR followers = 0
                             THEN COALESCE(NULLIF(excluded.followers, 0), followers) ELSE followers END,
              verified=MAX(COALESCE(verified, 0), excluded.verified),
              first_seen=MIN(first_seen, excluded.first_seen), last_seen=MAX(last_seen, excluded.last_seen)""",
                    (c["handle"], au.get("name"), c["followers"] or None, int(au.get("verified") or 0), c["ts"], c["ts"]))
    return n


def _target(key):
    """(ca, symbol) a cached token search was for, or (None, None) for a timeline search."""
    try:
        inp = json.loads(key.split(":", 2)[2])
    except (IndexError, ValueError):
        return None, None
    terms = inp.get("searchTerms") or []
    ca = next((s for s in terms if _CA.fullmatch(s or "")), None)
    sym = next((s[1:] for s in terms if (s or "").startswith("$")), None)
    return ca, sym


def from_hype_cache(con, hype_db=None):
    """Copy calls out of every X search the bot cached in hype.db. The cache row is replaced on the next identical
    search, so this has to run often; seen_cache remembers (key, ts) already copied."""
    path = hype_db or HYPE_DB
    if not os.path.exists(path):
        return 0
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    n = 0
    try:
        where = " OR ".join("key LIKE ?" for _ in CACHE_PREFIXES)
        try:
            keys = src.execute(f"SELECT key, ts FROM apify_cache WHERE {where}",
                               [p + "%" for p in CACHE_PREFIXES]).fetchall()
        except sqlite3.OperationalError:
            keys = []
        seen = dict(con.execute("SELECT key, ts FROM seen_cache"))
        # only the searches not copied yet are read with their tweets (all of them at once held every raw
        # Apify answer in memory on each 20-minute round)
        for key, ts in keys:
            if seen.get(key) == ts:
                continue
            row = src.execute("SELECT ts, items FROM apify_cache WHERE key = ?", (key,)).fetchone()
            if row is None:
                continue
            ts, items = row
            if seen.get(key) == ts:
                continue
            ca, sym = _target(key)
            source = key.split(":", 1)[0]
            try:
                tweets = json.loads(items)
            except ValueError:
                tweets = []
            del items
            for t in tweets:
                n += save(con, calls_from_tweet(t, ca, sym, source))
            con.execute("INSERT OR REPLACE INTO seen_cache VALUES (?,?)", (key, ts))
    finally:
        src.close()
    return n


_STATUS = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/(\w{1,15})/status/(\d{6,})")
# the webhook text is every string of the payload joined: "<id> <url> <id> <createdAt ms> <lang> <post text> ..."
_HOOK_HEAD = re.compile(r"^\s*(?:\d{6,}\s+)?(?:https?://\S+/status/\d+\s+)(?:\d{6,}\s+){0,3}(?:[a-z]{2,3}\s+)?")
SNOWFLAKE_EPOCH = 1288834974657


def snowflake_ts(tid):
    """Post time (unix s) hidden in an X post id; None for ids from before 2010 or not numeric."""
    try:
        i = int(tid)
    except (TypeError, ValueError):
        return None
    return ((i >> 22) + SNOWFLAKE_EPOCH) // 1000 if i > 1 << 40 else None


def hook_post(handle, ts, text):
    """(tweet_id, handle, ts, url, text) of one webhook row. The payload carries the post's own link: from it come
    the real post id (so the same post found by a search is not stored twice), the exact time and the link that
    the table shows. Without one: the old synthetic id and the profile link."""
    text = text or ""
    links = _STATUS.findall(text)
    if not links:
        return f"hook-{handle}-{ts}", handle, ts, f"https://x.com/{handle}", text
    h, tid = next(((a, b) for a, b in links if a.lower() == (handle or "").lower()), links[0])
    return (tid, h, snowflake_ts(tid) or ts, f"https://x.com/{h}/status/{tid}",
            _HOOK_HEAD.sub("", text, count=1) if _HOOK_HEAD.match(text) else text)


def fix_hook_rows(con):
    """Rows saved from the webhook before hook_post: give them the real post id, link, time and text, and drop the
    ones that a search already stored under the real id (the same post twice, one copy without a link)."""
    n = 0
    for tid0, token, handle, ts, text in con.execute(
            "SELECT tweet_id, token, handle, ts, text FROM calls WHERE tweet_id LIKE 'hook-%'").fetchall():
        tid, h, t, url, clean = hook_post(handle, ts, text)
        if tid.startswith("hook-"):
            continue
        if con.execute("SELECT 1 FROM calls WHERE tweet_id = ? AND token = ?", (tid, token)).fetchone():
            con.execute("DELETE FROM calls WHERE tweet_id = ? AND token = ?", (tid0, token))
        else:
            con.execute("UPDATE calls SET tweet_id = ?, handle = ?, ts = ?, url = ?, text = ? WHERE tweet_id = ? "
                        "AND token = ?", (tid, h, t, url, clean[:600], tid0, token))
        n += 1
    return n


def from_webhook(con, hype_db=None):
    """kol_mentions rows written by the xquik monitor webhook (no followers in that payload)."""
    path = hype_db or HYPE_DB
    if not os.path.exists(path):
        return 0
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        rows = src.execute("SELECT ts, handle, ca, text FROM kol_mentions WHERE ca != '' AND handle != ''").fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        src.close()
    fix_hook_rows(con)
    n = 0
    for ts, handle, ca, text in rows:
        if ca not in cas_in(ca):  # EVM address tail ("x3ea...7777") from before the check: not a Solana token
            continue
        tid, h, t, url, clean = hook_post(handle, ts, text)
        n += save(con, [{"tweet_id": tid, "token": ca, "handle": h, "ts": t, "url": url,
                         "text": clean[:600], "followers": 0, "likes": 0, "retweets": 0, "views": 0,
                         "kind": kind_of(clean), "match": "ca", "source": "webhook", "symbol": None}])
    return n


# ---------------- paid searches (Apify, budgeted per source in hype/apify.json) ----------------

def _searched(con, target, kind, now):
    con.execute("INSERT INTO searches VALUES (?,?,?,1) ON CONFLICT (target) DO UPDATE SET last_ts=excluded.last_ts, "
                "n=n+1", (target, kind, now))


def followup_targets(con, cfg, now=None):
    """Tokens called 1-24 h ago that we have not searched for a while, tokens that already pumped first: who
    called a winner early is how new KOLs get found. Then tokens with many callers."""
    now = now or int(time.time())
    f = cfg["followup"]
    rows = con.execute("""
        SELECT c.token, MAX(c.symbol), COUNT(DISTINCT c.handle) AS n, MAX(COALESCE(k.score, 0)) AS best,
               MAX(COALESCE(c.max24, 0)) AS up
        FROM calls c LEFT JOIN kols k ON k.handle = c.handle
        WHERE c.kind = 'call' AND c.ts BETWEEN ? AND ?
        GROUP BY c.token ORDER BY (up >= 1.0) DESC, n DESC, best DESC""",
                       (now - f["max_age_h"] * 3600, now - f["after_h"] * 3600)).fetchall()
    last = dict(con.execute("SELECT target, last_ts FROM searches WHERE kind = 'followup'"))
    return [(t, s) for t, s, n, best, up in rows if now - (last.get(t) or 0) >= f["again_h"] * 3600]


def followup(con, cfg, run=None):
    """Search the CA (and $TICKER) of the top follow-up targets. Returns new calls."""
    from hype import apify
    run = run or apify.run
    f = cfg["followup"]
    n, now = 0, int(time.time())
    for token, sym in followup_targets(con, cfg)[:f["per_run"]]:
        terms = [token] + ([f"${sym}"] if sym and len(sym) >= 3 else [])
        items = run("kol_search", X_ACTOR, {"searchTerms": terms, "maxItems": f["max_items"], "sort": "Latest"})
        _searched(con, token, "followup", now)
        n += save(con, [c for t in items for c in calls_from_tweet(t, token, sym, "kol_search")])
    return n


def timeline_handles(con, cfg, now=None):
    """Accounts for the next timeline query, rotating: the live watchlist first, then candidates not looked at in
    timeline.refresh_d days (most calls, best score, most followers). Every author we ever saw gets a turn, so new
    KOLs are scored on all their calls, misses included, not only on the token where we first saw them."""
    now = now or int(time.time())
    t = cfg["timeline"]
    last = {k[3:]: v for k, v in con.execute("SELECT target, last_ts FROM searches WHERE target LIKE 'tl:%'")}
    watch = [r[0] for r in con.execute("SELECT handle FROM watch ORDER BY score DESC")]
    rows = con.execute("""
        SELECT k.handle FROM kols k JOIN calls c ON c.handle = k.handle AND c.kind = 'call'
        WHERE k.handle NOT LIKE 'tg:%' AND k.handle NOT LIKE 'w:%'
        GROUP BY k.handle HAVING COUNT(DISTINCT c.token) >= ? OR MAX(COALESCE(k.followers, 0)) >= ?
        ORDER BY COALESCE(k.score, 0) DESC, COUNT(DISTINCT c.token) DESC, COALESCE(k.followers, 0) DESC""",
                       (t["min_calls"], t["min_followers"])).fetchall()
    due = [h for h, in rows if h not in watch and now - (last.get(h) or 0) >= t["refresh_d"] * 86400]
    return (watch + due)[:t["kols"]]


def timeline(con, cfg, run=None, now=None):
    """Latest tweets of the best KOLs in one query (every timeline.every_h hours): their new calls on any token,
    also tokens our scanner has not seen yet."""
    from hype import apify
    run = run or apify.run
    now = now or int(time.time())
    t = cfg["timeline"]
    last = con.execute("SELECT last_ts FROM searches WHERE target = 'timeline'").fetchone()
    if last and now - last[0] < t["every_h"] * 3600:
        return 0
    handles = timeline_handles(con, cfg)
    if not handles:
        return 0
    query = " OR ".join(f"from:{h}" for h in handles)
    items = run("kol_timeline", X_ACTOR, {"searchTerms": [query], "maxItems": t["max_items"], "sort": "Latest"})
    _searched(con, "timeline", "timeline", now)
    for h in handles:
        _searched(con, f"tl:{h}", "timeline_kol", now)
    return save(con, [c for it in items for c in calls_from_tweet(it, source="kol_timeline")])


# ---------------- Telegram (tg.db, run_tg.py) and KOL wallets on chain (hype.db chain_trades) ----------------

def from_telegram(con, tg_db=None):
    """Telegram posts with a CA become calls: author 'tg:<channel>', followers = subscribers, views = post views.
    A forwarded post is kind 'repost' (the original channel made the call; it is a candidate of its own)."""
    from tg import store as tstore
    src = tstore.ro(tg_db)
    if src is None:
        return 0
    last = (con.execute("SELECT ts FROM seen_cache WHERE key='tg:posts'").fetchone() or (0,))[0]
    try:
        rows = src.execute("""SELECT p.channel, p.post, p.ts, p.seen_ts, p.text, p.cas, p.views, p.fwd_from, p.source,
                                     c.subs, c.title
                              FROM posts p LEFT JOIN channels c ON c.name = p.channel
                              WHERE p.seen_ts >= ? AND p.cas != '' ORDER BY p.seen_ts""", (last,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        src.close()
    n, top = 0, last
    for ch, post, ts, seen, text, cas, views, fwd, source, subs, title in rows:
        top = max(top, seen)
        if not ts:
            continue
        kind = "repost" if fwd else kind_of(text)
        base = {"tweet_id": f"tg:{ch}/{post}", "handle": f"tg:{ch}", "ts": ts, "url": f"https://t.me/{ch}/{post}",
                "text": (text or "")[:600], "followers": subs or 0, "likes": 0, "retweets": 0, "views": views or 0,
                "kind": kind, "match": "ca", "source": "tg" if source != "tgstat" else "tgstat", "symbol": None,
                "author": {"name": title, "verified": False}}
        n += save(con, [dict(base, token=c) for c in cas.split(",") if c])
    con.execute("INSERT OR REPLACE INTO seen_cache VALUES ('tg:posts', ?)", (top,))
    return n


def wallet_handles(con):
    """wallet -> author handle: the KOL's X handle as we know it in kols (case-insensitive), else 'w:<name>'."""
    known = {h.lower(): h for h, in con.execute("SELECT handle FROM kols WHERE handle NOT LIKE 'tg:%'")}
    out = {}
    for wallet, name, tw in con.execute("SELECT wallet, name, twitter FROM kol_ids"):
        if tw:
            out[wallet] = known.get(tw.lower(), tw)
        else:
            out[wallet] = "w:" + (name or wallet[:6])
    return out


def from_chain(con, hype_db=None):
    """Swaps of tracked KOL wallets (Helius webhook -> hype.db chain_trades) as calls of kind 'buy' / 'sell'.
    They do not count in the KOL's call score; kol/converge.py uses them (a KOL usually buys before posting)."""
    path = hype_db or HYPE_DB
    if not os.path.exists(path):
        return 0
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    last = (con.execute("SELECT ts FROM seen_cache WHERE key='chain:trades'").fetchone() or (0,))[0]
    try:
        rows = src.execute("SELECT sig, wallet, mint, side, ts, sol FROM chain_trades WHERE ts >= ? ORDER BY ts",
                           (last,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        src.close()
    who = wallet_handles(con)
    n, top = 0, last
    for sig, wallet, mint, side, ts, sol in rows:
        top = max(top, ts)
        h = who.get(wallet) or "w:" + wallet[:6]
        n += con.execute("""INSERT OR IGNORE INTO calls (tweet_id, token, handle, ts, url, text, followers, likes,
            retweets, views, kind, match, source, symbol) VALUES (?,?,?,?,?,?,0,0,0,0,?,?,?,NULL)""",
                         (f"sig:{sig}", mint, h, ts, f"https://solscan.io/tx/{sig}", f"{side} {sol or 0:.2f} SOL",
                          side, "wallet", "chain")).rowcount
    con.execute("INSERT OR REPLACE INTO seen_cache VALUES ('chain:trades', ?)", (top,))
    return n
