"""X early momentum (10.11., spec item 3; extends the X features of ui/xfeat.py).

For a scanner passer or a beta candidate: one twitterapi.io search (kol/twapi.search, `"<CA>" OR $TICKER`, the last
75 minutes, at most x_max_pages pages of ~20 posts) and from the posts:
    posts15 / posts60     posts with the CA or the ticker in the last 15 / 60 min
    authors15 / authors60 unique authors in those windows
    bot_share             share of authors whose account is younger than 30 days or has under 100 followers (a bot
                          proxy; only when the search result carries the author's createdAt / followers: no extra paid
                          call per author). None when no author carries them
    organic               an author that is not a bot proxy and not a known alert bot (kol.db kols.bot)
    x_momentum_score      log2((organic authors in the last 15 min + 1) / (organic authors in the 60 min before
                          that * 15/60 + 1)): the last 15 minutes' rate against the previous hour's, smoothed by one
                          author; > 0 = growing, 1 = twice the rate, -1 = half
    caller_called         a known caller already called it: a kol.db calls row (kind call) on the token, or one of
                          the authors is a scored caller (kol.db kols with a score)
    x_early               the momentum grows (score > 0 with at least x_min_authors organic authors in 15 min) and no
                          known caller posted it yet
Cost: twitterapi.io $0.00015 a post (kol/twapi.cost). The search goes through twapi's own day counter (kol.db kv
twapi:<day>, metered in usage.db as twitterapi), and the scanner keeps its own cap on top: x_usd_day ($0.30), sliced
by the hour (scan/store.allowance), counted in scan.db kv xusd:<day>.

Grok first: a row Grok sent through submit_x_features (xfeat.db x_features, source "mcp:<key>") for the token in the
last 2 h takes precedence; such a token is not searched (no cost) and its values are shown with source "grok".

Storage: xfeat.db, sibling table x_momentum (insert only, like x_features). It is the scanner's own measurement, so
it is written while the flag market_scan is on; the flag x_features_ingest keeps governing only the MCP intake of
Grok's rows (ui/xfeat.submit) and is neither needed nor bypassed here.
"""
import json
import math
import os
import sqlite3
import time

SCHEMA = """CREATE TABLE IF NOT EXISTS x_momentum (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, ts INTEGER NOT NULL, posts15 INTEGER, posts60 INTEGER,
    authors15 INTEGER, authors60 INTEGER, organic15 INTEGER, organic_prev60 INTEGER, bot_share REAL,
    caller_called INTEGER, known_authors TEXT, score REAL, x_early INTEGER, usd REAL, source TEXT NOT NULL)"""
INDEX = "CREATE INDEX IF NOT EXISTS x_momentum_token ON x_momentum (token, ts)"
GROK_FRESH_S = 2 * 3600
NEW_ACCOUNT_S = 30 * 86400
MIN_FOLLOWERS = 100


def db_path():
    from ui import xfeat
    return xfeat.db_path()


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.execute(SCHEMA)
    con.execute(INDEX)
    return con


def _int(x):
    try:
        return int(float(str(x).replace(",", "")))
    except (TypeError, ValueError):
        return None


def post_rows(tweets):
    """twitterapi.io posts -> [{handle, ts, followers, created_ts}] (retweets out: the original author counts)."""
    from kol.collect import tweet_ts
    out = []
    for t in tweets or []:
        if not isinstance(t, dict) or t.get("isRetweet") or t.get("retweeted_tweet"):
            continue
        a = t.get("author") or t.get("user") or {}
        h = a.get("userName") or a.get("screen_name") or a.get("username")
        ts = tweet_ts(t.get("createdAt"))
        if not h or not ts:
            continue
        fol = a.get("followers", a.get("followersCount", a.get("followers_count")))
        out.append({"handle": h.lower(), "ts": ts, "followers": _int(fol) if fol is not None else None,
                    "created_ts": tweet_ts(a.get("createdAt")) if a.get("createdAt") else None})
    return out


def momentum(posts, now, known=frozenset(), bots=frozenset(), called=False, min_authors=2):
    """The counts and the score from post rows (see the module text). Pure."""
    now = int(now)
    w15 = [p for p in posts if now - 900 < p["ts"] <= now]
    w60 = [p for p in posts if now - 3600 < p["ts"] <= now]
    prev = [p for p in posts if now - 4500 < p["ts"] <= now - 900]
    seen_meta = [p for p in posts if p.get("followers") is not None or p.get("created_ts")]

    def botlike(p):
        if p["handle"] in bots:
            return True
        if p.get("followers") is not None and p["followers"] < MIN_FOLLOWERS:
            return True
        return bool(p.get("created_ts") and now - p["created_ts"] < NEW_ACCOUNT_S)

    authors = {}
    for p in posts:
        authors.setdefault(p["handle"], p)
    a_meta = {h: p for h, p in authors.items() if p.get("followers") is not None or p.get("created_ts")}
    bot_share = round(sum(1 for p in a_meta.values() if botlike(p)) / len(a_meta), 3) if seen_meta and a_meta else None
    org15 = {p["handle"] for p in w15 if not botlike(p)}
    org_prev = {p["handle"] for p in prev if not botlike(p)}
    score = round(math.log2((len(org15) + 1) / (len(org_prev) * 15 / 60 + 1)), 3)
    known_auth = sorted({p["handle"] for p in posts if p["handle"] in known})
    caller_called = bool(called or known_auth)
    grows = score > 0 and len(org15) >= min_authors
    return {"posts15": len(w15), "posts60": len(w60), "authors15": len({p["handle"] for p in w15}),
            "authors60": len({p["handle"] for p in w60}), "organic15": len(org15), "organic_prev60": len(org_prev),
            "bot_share": bot_share, "caller_called": caller_called, "known_authors": known_auth[:10],
            "x_momentum_score": score, "x_early": bool(grows and not caller_called)}


GROK_KEYS = ("x_momentum_score", "x_early", "ca_posts_1h", "unique_authors_15m", "unique_authors_60m")


def _grok(ts_asof, features):
    """A Grok x_features row -> {"source": "grok", "ts", "x_momentum_score", "x_early", "posts60"}, or None when it
    carries none of the momentum keys."""
    try:
        f = json.loads(features)
    except (TypeError, ValueError):
        return None
    if not isinstance(f, dict) or not any(k in f for k in GROK_KEYS):
        return None
    sc = f.get("x_momentum_score")
    try:
        sc = round(float(sc), 3) if sc is not None else None
    except (TypeError, ValueError):
        sc = None
    early = f.get("x_early")
    return {"source": "grok", "ts": ts_asof, "x_momentum_score": sc,
            "x_early": bool(early) if isinstance(early, (bool, int)) else None, "posts60": _int(f.get("ca_posts_1h"))}


def _grok_rows(con, tokens, now):
    """{token: Grok's newest momentum row of the last 2 h} from x_features (source mcp:*, live rows only)."""
    out = {}
    if not tokens:
        return out
    q = ",".join("?" * len(tokens))
    try:
        rows = con.execute(f"SELECT subject, ts_asof, features FROM x_features WHERE subject_kind='token' AND "
                           f"subject IN ({q}) AND source LIKE 'mcp:%' AND backfill=0 AND ts_asof >= ? "
                           f"ORDER BY ts_asof, id", (*tokens, int(now) - GROK_FRESH_S)).fetchall()
    except sqlite3.Error:
        return out
    for tok, ts, f in rows:   # oldest first: the newest usable row wins
        g = _grok(ts, f)
        if g:
            out[tok] = g
    return out


def grok_row(token, now, path=None):
    """Grok's newest X momentum row for the token in the last 2 h (see _grok), or None."""
    from ui import xfeat
    con = xfeat.ro(path)
    if con is None:
        return None
    try:
        return _grok_rows(con, [token], now).get(token)
    finally:
        con.close()


def latest(tokens, path=None, since=None, now=None):
    """{token: the newest X momentum of the token} (read-only), for get_market_signals: the scanner's own row from
    x_momentum, with Grok's hand-checked row of the last 2 h on top (it takes precedence)."""
    tokens = list(dict.fromkeys(tokens))
    p = path or db_path()
    if not tokens or not os.path.exists(p) or not os.path.getsize(p):
        return {}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return {}
    out = {}
    try:
        q = ",".join("?" * len(tokens))
        try:
            for tok, ts, sc, early, called, posts60, a15, bs, src in con.execute(
                    f"SELECT token, MAX(ts), score, x_early, caller_called, posts60, authors15, bot_share, source "
                    f"FROM x_momentum WHERE token IN ({q}) AND ts >= ? GROUP BY token", (*tokens, int(since or 0))):
                out[tok] = {"ts": ts, "x_momentum_score": sc, "x_early": bool(early), "caller_called": bool(called),
                            "posts60": posts60, "authors15": a15, "bot_share": bs, "source": src}
        except sqlite3.Error:
            pass
        for tok, g in _grok_rows(con, tokens, now or time.time()).items():
            out[tok] = {**out.get(tok, {}), **{k: v for k, v in g.items() if v is not None}}
    finally:
        con.close()
    return out


def query(token, symbol):
    """The search: the CA, and the cashtag when the ticker is a plain 2-10 character word."""
    sym = "".join(ch for ch in (symbol or "") if ch.isalnum())
    q = f'"{token}"'
    if 2 <= len(sym) <= 10 and sym == (symbol or "").strip().lstrip("$"):
        q += f" OR ${sym}"
    return q


def measure(token, symbol, now, scon, kcon, cfg, get=None, known=frozenset(), bots=frozenset(), xcon=None, log=print):
    """Measure one token and store the row in xfeat.db x_momentum. Returns the row dict, or None when it was not
    measured (no key, the scanner's X budget for now is spent, or the search failed). scon: scan.db (its xusd
    counter), kcon: kol.db (twapi's day counter and the known calls)."""
    from kol import twapi
    from scan import store
    g = grok_row(token, now)
    if g:
        return dict(g, token=token, measured=False)
    if not twapi.key() and get is None:
        return None
    left = store.budget_left(scon, "xusd", cfg["x_usd_day"], now)
    if left < twapi.MIN_REQ * int(cfg["x_max_pages"]):
        return None
    before = twapi.spent(kcon, now)
    try:
        tweets = twapi.search(kcon, query(token, symbol), now - 4500, before + left, get=get,
                              max_pages=int(cfg["x_max_pages"]), now=now)
    except Exception as e:  # noqa: BLE001 - X is extra information, never the reason a pass stops
        log(f"skener: X pretraga {token[:6]}: {type(e).__name__}: {str(e)[:80]}")
        tweets = None
    kcon.commit()
    usd = max(0.0, twapi.spent(kcon, now) - before)   # a page paid before a failure still counts
    store.add_spent(scon, "xusd", usd, now)
    if tweets is None:
        return None
    try:
        called = bool(kcon.execute("SELECT 1 FROM calls WHERE token=? AND kind='call' AND ts<=? LIMIT 1",
                                   (token, int(now))).fetchone())
    except sqlite3.Error:
        called = False
    m = momentum(post_rows(tweets), now, known, bots, called, int(cfg["x_min_authors"]))
    own = xcon is None
    xcon = xcon or connect()
    try:
        xcon.execute("INSERT INTO x_momentum (token, ts, posts15, posts60, authors15, authors60, organic15, "
                     "organic_prev60, bot_share, caller_called, known_authors, score, x_early, usd, source) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (token, int(now), m["posts15"], m["posts60"], m["authors15"], m["authors60"], m["organic15"],
                      m["organic_prev60"], m["bot_share"], int(m["caller_called"]), ",".join(m["known_authors"]),
                      m["x_momentum_score"], int(m["x_early"]), round(usd, 5), "scan"))
        xcon.commit()
    finally:
        if own:
            xcon.close()
    return dict(m, token=token, usd=round(usd, 5), source="scan", measured=True)


def known_handles(kcon):
    """(scored callers, bot handles) of kol.db, lower case; read once per pass, only when X is measured."""
    try:
        known = {h.lower() for (h,) in kcon.execute("SELECT handle FROM kols WHERE score IS NOT NULL AND score > 0")}
    except sqlite3.Error:
        known = set()
    try:
        from kol import bots
        b = {h.lower() for h in bots.handles(kcon)}
    except Exception:  # noqa: BLE001
        b = set()
    return known - b, b
