"""Call power on the midcaps: which X accounts push our midcap memecoins, how hard, and what the price did after
(18.11., owner: "Želim da Twitter API kredite koristiš za ove mid-capove koje smo odabrali, da vidimo od kojih je
zvao, od kojih agresivno gura. Želim naći na taj način velike influencere koji imaju veliku moć poziva ... ako oni
zovu nekog malog meme coina, znači da će sigurno eksplodirati. Na to želim trošiti kredite").

Two sources of posts:
  free   the posts already bought for the macro-influencer module (makroinf.db tweets, ~250k posts of ~540 accounts):
         read where they stand, nothing fetched
  paid   sweep(): one X search per midcap for the last SEARCH_DAYS, only posts with reach (min_faves), at most PAGES
         pages a token (~100 posts, $0.015). A whole pass over the collector's members costs at most ~$2.50; it runs
         once per SWEEP_EVERY_D, under a hard cap of DAY_USD a UTC day counted in this module's own file. The posts
         are kept (moc.db posts), so no post is bought twice.

A MENTION is a post that names a midcap by its cashtag ($SYMBOL, only symbols that belong to exactly one of our
tokens and are not a generic ticker) or by its mint address. The same account naming the same token again within
DEDUP_S counts once for the outcome (the first), but every post counts for "how hard he pushes".

OUTCOME: the token's 15m close at the post, then +1 h, +4 h, +24 h (midcap.db candles), minus what that token does
on average over the same horizon. So "+3 %" means three points more than the token's usual move, not the raw move:
a coin that only goes up makes nobody look powerful.

POWER of an account: the mean of that excess at 24 h over its token-days, with a 90 % interval; an account is
ranked only from MIN_CLUSTERS token-days and by the interval's LOW (a few lucky posts do not rank). Reported next
to it: followers, posts, how many of our midcaps it named, the most posts on one token within 7 days (the push).

This measures a hypothesis, it proves nothing yet: an account that posts after the price has already moved looks
powerful too. The next step uses the ranked accounts as a watch list for SMALL coins on the demo account, and that
measurement decides. Nothing here trades. Result: moc.db kv "moc", one line "moć poziva: ...", MCP get_call_power.
"""
import bisect
import json
import os
import re
import sqlite3
import time

H, D, M15 = 3600, 86400, 900
PREFIX = "moć poziva: "
KV = "moc"
DAYS = 45
DEDUP_S = 6 * H
HORIZONS = (("1h", H), ("4h", 4 * H), ("24h", D))
MIN_CLUSTERS = 8
SEARCH_DAYS = 30
MIN_FAVES = 25
PAGES = 5
SWEEP_EVERY_D = 7
RUN_TOKENS = 60            # searches in one run (the job holds the heavy-job lock): a full pass takes ~1.5 days
RUN_S = 240
DAY_USD = float(os.environ.get("MOC_DAY_USD", "4.0"))
GENERIC = frozenset("SOL USD USDC USDT BTC ETH BNB XRP ADA TON SUI AI CEO APP NFT DEX USA GM GN ATH CA DM".split())
_TICKER = re.compile(r"\$([A-Za-z][A-Za-z0-9]{2,11})(?![A-Za-z0-9])")
SCHEMA = """CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, handle TEXT, ts INTEGER, text TEXT, likes INTEGER,
    retweets INTEGER, views INTEGER, followers INTEGER, token TEXT, fetched_ts INTEGER);
CREATE INDEX IF NOT EXISTS posts_ts ON posts (ts);"""


def db_path(path=None):
    if path:
        return path
    if os.environ.get("MOC_DB"):
        return os.environ["MOC_DB"]
    from veliki import midcap
    return os.path.join(os.path.dirname(os.path.abspath(midcap.db_path())), "moc.db")


def connect(path=None):
    con = sqlite3.connect(db_path(path), timeout=30)
    con.executescript(SCHEMA)
    return con


def _kv(con, k, v=None):
    if v is None:
        r = con.execute("SELECT value FROM kv WHERE key=?", (k,)).fetchone()
        return r[0] if r else None
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    return v


# ---------- the tokens and the mentions -------------------------------------------------------------------------------

def symbols(tokens):
    """({SYMBOL: mint} of the symbols that name exactly one of our tokens and are no generic ticker, {mint: symbol})."""
    by = {}
    names = {}
    for t in tokens:
        s = (t.get("symbol") or "").strip().upper()
        names[t["mint"]] = t.get("symbol") or t["mint"][:6]
        if len(s) >= 3 and s.isalnum() and s not in GENERIC and not s.startswith(t["mint"][:6].upper()):
            by.setdefault(s, set()).add(t["mint"])
    return {s: next(iter(m)) for s, m in by.items() if len(m) == 1}, names


def mentions_of(posts, symmap, mints):
    """[{handle, token, ts, how, likes, views, followers, id}] of the posts that name one of our midcaps."""
    out = []
    for p in posts:
        text = p.get("text") or ""
        if not text or ("$" not in text and len(text) < 32):
            continue
        found = {}
        for m in mints:
            if m in text:
                found[m] = "ca"
        if "$" in text:
            for s in _TICKER.findall(text):
                tok = symmap.get(s.upper())
                if tok and tok not in found:
                    found[tok] = "ticker"
        for tok, how in found.items():
            out.append({"handle": (p.get("handle") or "").lstrip("@"), "token": tok, "ts": int(p["ts"]), "how": how,
                        "likes": p.get("likes") or 0, "views": p.get("views") or 0, "followers": p.get("followers"),
                        "id": p.get("id")})
    return [m for m in out if m["handle"]]


def first_only(ms, gap=DEDUP_S):
    """The mentions that count for the outcome: per (account, token), one per `gap` (the first)."""
    last, out = {}, []
    for m in sorted(ms, key=lambda x: x["ts"]):
        k = (m["handle"].lower(), m["token"])
        if k in last and m["ts"] - last[k] < gap:
            continue
        last[k] = m["ts"]
        out.append(m)
    return out


def push_of(ms):
    """{handle lower: (the most posts on one token within 7 days, that token)}."""
    by = {}
    for m in ms:
        by.setdefault((m["handle"].lower(), m["token"]), []).append(m["ts"])
    out = {}
    for (h, tok), ts in by.items():
        ts.sort()
        best = max(bisect.bisect_left(ts, t + 7 * D) - i for i, t in enumerate(ts))   # a 7-day window from each post
        if best > out.get(h, (0, None))[0]:
            out[h] = (best, tok)
    return out


# ---------- the price after a post --------------------------------------------------------------------------------------

class Prices:
    """One token's 15m closes: the excess move after a time (the move minus the token's mean move over the horizon)."""

    def __init__(self, b15):
        self.ts = [int(b[0]) for b in b15]
        self.c = [float(b[4]) for b in b15]
        self.base = {}
        for name, h in HORIZONS:
            k = h // M15
            rs = [self.c[i + k] / self.c[i] - 1 for i in range(0, len(self.c) - k, 4) if self.c[i] > 0
                  and self.ts[i + k] - self.ts[i] <= h + 2 * H]
            self.base[name] = sum(rs) / len(rs) if rs else None

    def _at(self, t, slack=2 * M15):
        """Index of the bar that contains t (its close is the first price a reader could act on), or None."""
        i = bisect.bisect_right(self.ts, int(t)) - 1
        if i < 0 or t - self.ts[i] > M15 + slack:
            return None
        return i

    def excess(self, t):
        """{horizon: excess return} for a post at t; a horizon without candles (or a baseline) is left out."""
        i = self._at(t)
        if i is None or self.c[i] <= 0:
            return {}
        out = {}
        for name, h in HORIZONS:
            j = bisect.bisect_right(self.ts, self.ts[i] + h) - 1
            if j <= i or self.ts[j] - self.ts[i] < h - 2 * M15 or self.base.get(name) is None:
                continue
            out[name] = self.c[j] / self.c[i] - 1 - self.base[name]
        return out


# ---------- the ranking -------------------------------------------------------------------------------------------------

def rank(ms, prices, names=None, min_clusters=MIN_CLUSTERS):
    """{"accounts": [...], "tokens": [...], ...} from the mentions and {mint: Prices}."""
    from veliki import nauceno
    push = push_of(ms)
    acc = {}
    per_tok = {}
    measured = 0
    for m in first_only(ms):
        h = m["handle"].lower()
        a = acc.setdefault(h, {"handle": m["handle"], "followers": None, "posts": 0, "tokens": set(),
                               "x": {n: [] for n, _s in HORIZONS}, "likes": []})
        a["posts"] += 1
        a["tokens"].add(m["token"])
        a["likes"].append(m["likes"] or 0)
        if m.get("followers"):
            a["followers"] = max(a["followers"] or 0, int(m["followers"]))
        per_tok.setdefault(m["token"], {}).setdefault(h, 0)
        per_tok[m["token"]][h] += 1
        p = prices.get(m["token"])
        ex = p.excess(m["ts"]) if p else {}
        if ex:
            measured += 1
        for n, v in ex.items():
            a["x"][n].append(((m["token"], m["ts"] // D), v))
    rows = []
    for h, a in acc.items():
        st = {n: nauceno._stat(v) for n, v in a["x"].items()}
        s24 = st["24h"]
        rows.append({"handle": a["handle"], "followers": a["followers"], "posts": a["posts"], "tokens": len(a["tokens"]),
                     "push": push.get(h, (0, None))[0],
                     "push_token": (names or {}).get(push.get(h, (0, None))[1], push.get(h, (0, None))[1]),
                     "likes_med": sorted(a["likes"])[len(a["likes"]) // 2] if a["likes"] else 0,
                     "x1h": st["1h"]["ev"], "x4h": st["4h"]["ev"], "x24h": s24["ev"], "lo": s24["lo"], "hi": s24["hi"],
                     "hit": s24["hit"], "clusters": s24["clusters"],
                     "ranked": bool(s24["clusters"] >= min_clusters and s24["lo"] is not None)})
    ranked = sorted((r for r in rows if r["ranked"]), key=lambda r: -r["lo"])
    pushers = sorted(rows, key=lambda r: (-r["push"], -r["posts"]))[:15]
    toks = []
    for tok, hs in per_tok.items():
        top = sorted(hs.items(), key=lambda kv: -kv[1])[:5]
        toks.append({"token": tok, "symbol": (names or {}).get(tok, tok[:6]), "accounts": len(hs),
                     "posts": sum(hs.values()), "top": [{"handle": acc[h]["handle"], "posts": n} for h, n in top]})
    toks.sort(key=lambda t: -t["accounts"])
    return {"mentions": len(ms), "counted": sum(r["posts"] for r in rows), "measured": measured, "accounts": len(rows),
            "tokens_named": len(per_tok), "ranked_n": len(ranked), "positive_n": sum(1 for r in ranked if r["lo"] > 0),
            "top": ranked[:20], "bottom": ranked[-5:][::-1] if len(ranked) > 5 else [], "pushers": pushers,
            "tokens": toks[:30]}


# ---------- the paid sweep ----------------------------------------------------------------------------------------------

def sweep(con, tokens, symmap, now, get=None, log=print, day_usd=DAY_USD, every_d=SWEEP_EVERY_D, pages=PAGES,
          run_tokens=RUN_TOKENS, run_s=RUN_S):
    """One X search per token not searched in the last every_d days, the biggest volume first, while today's spend in
    this module is under day_usd, at most run_tokens searches and run_s seconds a run. {"searched", "posts", "usd",
    "left", "stopped"}. Never raises."""
    from kol import twapi
    out = {"searched": 0, "posts": 0, "usd": 0.0, "stopped": None}
    if get is None and not twapi.key():
        out["stopped"] = "nema ključa"
        return out
    inv = {m: s for s, m in symmap.items()}
    start = twapi.spent(con, now)
    t_end = time.time() + run_s
    due = [t for t in tokens if now - float(_kv(con, f"s:{t['mint']}") or 0) >= every_d * D]
    out["left"] = len(due)
    for t in due:
        mint = t["mint"]
        if out["searched"] >= run_tokens or time.time() > t_end:
            out["stopped"] = "ostatak u sljedećem prolazu"
            break
        if twapi.spent(con, now) >= day_usd:
            out["stopped"] = f"dnevni strop {day_usd:g} $"
            break
        sym = inv.get(mint)
        q = (f"(${sym} OR {mint})" if sym else mint) + f" min_faves:{MIN_FAVES} -filter:replies"
        try:
            items = twapi.search(con, q, now - SEARCH_DAYS * D, day_usd, get=get, max_pages=pages, now=now)
        except Exception as e:  # noqa: BLE001 - 402 (no credit), 429, a network error: stop, keep what we have
            con.commit()
            out["stopped"] = f"{type(e).__name__}: {str(e)[:80]}"
            break
        from kol.collect import tweet_ts
        n = 0
        for it in items:
            if not isinstance(it, dict) or it.get("isRetweet") or it.get("retweeted_tweet"):
                continue
            a = it.get("author") or {}
            handle, ts, tid = a.get("userName"), tweet_ts(it.get("createdAt")), str(it.get("id") or "")
            if not handle or not ts or not tid:
                continue
            con.execute("INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (tid, handle, ts, (it.get("fullText") or it.get("text") or "")[:1000], it.get("likeCount") or 0,
                         it.get("retweetCount") or 0, it.get("viewCount") or 0,
                         a.get("followers") or a.get("followersCount") or None, mint, int(now)))
            n += 1
        _kv(con, f"s:{mint}", int(now))
        con.commit()
        out["searched"] += 1
        out["left"] -= 1
        out["posts"] += n
    out["usd"] = round(twapi.spent(con, now) - start, 4)
    return out


# ---------- running it --------------------------------------------------------------------------------------------------

def free_posts(now, days=DAYS, path=None):
    """The already bought posts of the macro-influencer module that can name a token (a '$' or a long text)."""
    from makroinf import store as mstore
    con = mstore.ro(path)
    if con is None:
        return []
    try:
        fol = dict(con.execute("SELECT handle, followers FROM accounts"))
        return [{"id": i, "handle": h, "ts": ts, "text": tx, "likes": lk, "views": vw, "followers": fol.get(h)}
                for i, h, ts, tx, lk, vw in con.execute(
                    "SELECT id, handle, ts, text, likes, views FROM tweets WHERE ts>=? AND text LIKE '%$%'",
                    (int(now) - days * D,))]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _a(r):
    return (f"@{r['handle']} {r['x24h']:+.1%} u 24 h iznad prosjeka tokena [{r['lo']:+.1%}; {r['hi']:+.1%}], "
            f"{r['clusters']} token-dana, {r['tokens']} tokena"
            + (f", {r['followers'] / 1000:.0f}k pratitelja" if r.get("followers") else ""))


def line(res):
    if not res or not res.get("ts"):
        return PREFIX + "još nema rezultata"
    sw = res.get("sweep") or {}
    paid = (f"; pretraga X-a: {sw.get('searched', 0)} tokena (još {sw.get('left', 0)} na redu), {sw.get('posts', 0)} novih "
            f"objava, {sw.get('usd', 0):.2f} $"
            + (f" (stala: {sw['stopped']})" if sw.get("stopped") else "")) if sw else ""
    top = "; ".join(_a(r) for r in (res.get("top") or [])[:3]) or "nitko još nema dovoljno poziva"
    push = "; ".join(f"@{r['handle']} {r['push']}x {r.get('push_token') or ''} u 7 d" for r in (res.get("pushers") or [])[:3]
                     if r["push"] >= 3) or "—"
    return (f"{PREFIX}{res['mentions']} spominjanja {res['tokens_named']} midcapova od {res['accounts']} računa "
            f"({res.get('free_posts', 0)} kupljenih objava pregledano, {res.get('paid_posts', 0)} iz pretrage); izmjereno "
            f"{res['measured']} poziva; računa s dovoljno poziva ({MIN_CLUSTERS}+ token-dana): {res['ranked_n']}, s donjom "
            f"granicom iznad nule: {res['positive_n']}; najjači: {top}; najviše guraju: {push}{paid} ({res.get('secs', 0)} s)")


def latest(path=None):
    p = db_path(path)
    if not os.path.exists(p):
        return {}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        r = con.execute("SELECT value FROM kv WHERE key=?", (KV,)).fetchone()
        return json.loads(r[0]) if r else {}
    except (sqlite3.Error, ValueError, TypeError):
        return {}
    finally:
        con.close()


def mcp(args=None):
    res = latest()
    if not res:
        return {"note": "no result yet: the first pass runs ~25 min after a start"}
    lim = max(1, min(int((args or {}).get("limit") or 20), 50))

    def rnd(r):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
    return {"ts": res["ts"], "mentions": res["mentions"], "accounts": res["accounts"], "tokens_named": res["tokens_named"],
            "measured": res["measured"], "ranked": res["ranked_n"], "positive": res["positive_n"],
            "top": [rnd(r) for r in (res.get("top") or [])[:lim]], "bottom": [rnd(r) for r in res.get("bottom") or []],
            "pushers": [rnd(r) for r in (res.get("pushers") or [])[:lim]], "tokens": (res.get("tokens") or [])[:lim],
            "sweep": res.get("sweep"),
            "read_me": ("x1h / x4h / x24h = the token's move after the account's post MINUS that token's average move "
                        "over the same horizon (mean over token-days); lo / hi = 90 % interval of x24h; ranked only "
                        f"from {MIN_CLUSTERS} token-days, by lo. push = the most posts on one of our midcaps within 7 "
                        "days. A hypothesis under measurement: an account that posts after the move looks powerful "
                        "too. Statements about named accounts are statistics, not accusations.")}


def run(now=None, log=print, path=None, mpath=None, xpath=None, get=None, paid=True, save=True):
    """Free posts + one paid sweep (when due and under the cap) -> mentions -> outcomes -> ranking. path: moc.db,
    mpath: midcap.db, xpath: makroinf.db. Never raises: {} and a line."""
    from veliki import midcap, replay
    now = int(now or time.time())
    t0 = time.time()
    try:
        mcon = midcap.ro(mpath)
        if mcon is None:
            log(PREFIX + "nema podataka (midcap.db još ne postoji)")
            return {}
        con = connect(path)
        try:
            toks, _short, _gone = replay.tokens(mcon, min_days=1)
            symmap, names = symbols(toks)
            sw = sweep(con, toks, symmap, now, get=get, log=log) if paid else {}
            bought = [{"id": i, "handle": h, "ts": ts, "text": tx, "likes": lk, "views": vw, "followers": fo}
                      for i, h, ts, tx, lk, vw, fo in con.execute(
                          "SELECT id, handle, ts, text, likes, views, followers FROM posts WHERE ts>=?", (now - DAYS * D,))]
            free = free_posts(now, path=xpath)
            seen, posts = set(), []
            for p in bought + free:
                if p["id"] not in seen:
                    seen.add(p["id"])
                    posts.append(p)
            ms = mentions_of(posts, symmap, set(names))
            prices = {}
            for tok in {m["token"] for m in ms}:
                b15 = replay.bars(mcon, "c15", tok)
                if len(b15) >= 8:
                    prices[tok] = Prices(b15)
            res = rank(ms, prices, names)
            res.update(ts=now, free_posts=len(free), paid_posts=len(bought), sweep=sw, secs=round(time.time() - t0, 1))
            if save:
                _kv(con, KV, json.dumps(res, ensure_ascii=False, default=str))
                con.commit()
        finally:
            mcon.close()
            con.close()
        log(line(res))
        return res
    except Exception as e:  # noqa: BLE001 - a measurement: it never takes its caller down
        try:
            log(PREFIX + f"nije uspio ({type(e).__name__}: {str(e)[:160]})")
        except Exception:  # noqa: BLE001
            pass
        return {}
