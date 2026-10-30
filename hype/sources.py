"""Apify-backed sources for the hype scanner: pump.fun feeds, GMGN smart wallets, X trends, Google Trends,
and KOL tweets pushed in by the xquik monitor's webhook. Each is cached and budgeted in hype/apify.py.
"""
import json
import re
import sqlite3
import statistics
import time

from hype import apify, telegram
from hype.score import _norm

PUMPFUN = "muhammetakkurtt/pump-fun-token-scraper-monitor"
GMGN = "muhammetakkurtt/gmgn-copytrade-wallet-scraper"
X_TRENDS = "karamelo/twitter-trends-scraper"
G_TRENDS = "apify/google-trends-scraper"
KOL = "xquik/x-twitter-crypto-tracker"

# trends that are words every second token name contains
_STOP = {"THE", "AND", "FOR", "WITH", "THIS", "THAT", "COIN", "TOKEN", "SOLANA", "CRYPTO", "MEME", "HAPPY", "DAY",
         "NEW", "GOOD", "MORNING", "NIGHT", "FRIDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "SATURDAY",
         "SUNDAY", "WEEKEND", "OCTOBER", "NOVEMBER", "DECEMBER", "JANUARY"}


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ---------------- pump.fun ----------------

def pumpfun_tokens(cfg=None):
    """mint -> pump.fun record (board, kolCount, holders, risk shares) from the configured boards."""
    cfg = cfg or apify.config()["pumpfun"]
    out = {}
    for board in cfg["boards"]:
        inp = {"board": board, "maxItems": cfg["max_items"], **cfg.get("filters", {})}
        for t in apify.run("pumpfun", PUMPFUN, inp, cache_secs=cfg["every_min"] * 60):
            if t.get("mint"):
                cur = out.setdefault(t["mint"], dict(t, boards=[]))
                cur["boards"].append(board)
    return out


# ---------------- GMGN smart wallets ----------------

def gmgn_score(w):
    """0-100 from GMGN's 7-day stats, same spirit as onchain.score_wallet. Bots and snipers get 0."""
    tags = set(w.get("tags") or [])
    txs = _f(w.get("txs_7d"))
    hold = _f(w.get("avg_holding_period_7d"))
    big = _f(w.get("pnl_2x_5x_num_7d")) + 2 * _f(w.get("pnl_gt_5x_num_7d"))
    wr = _f(w.get("winrate_7d"))
    profit = _f(w.get("realized_profit_7d"))
    bot = txs > 3000 or (hold and hold < 30) or bool(tags & {"snipe_bot", "sandwich_bot"})
    s = {"source": "gmgn", "win_rate": round(wr, 2), "pnl_usd_7d": round(profit), "big_wins": int(big),
         "tx_7d": int(txs), "median_hold_min": round(hold / 60, 1) if hold else None, "bot": bot,
         "tags": sorted(tags), "twitter": w.get("twitter_username")}
    score = 0 if bot else 35 * min(1, wr / 0.7) + 30 * min(1, max(0, profit) / 50000) + 20 * min(1, big / 8) \
        + 15 * min(1, txs / 100)
    s["score"] = round(score)
    return s


def gmgn_wallets(con):
    cfg = apify.config()["gmgn"]
    found = []  # fetch first: apify.run writes hype.db too, and an open write here would lock it
    for tt in cfg["trader_types"]:
        inp = {"chain": "sol", "traderType": tt, "sortBy": cfg["sort_by"], "limit": cfg["limit"]}
        found += apify.run("gmgn", GMGN, inp, cache_secs=cfg["every_h"] * 3600)
    n = 0
    for w in found:
        addr = w.get("wallet_address") or w.get("address")
        if not addr:
            continue
        s = gmgn_score(w)
        old = con.execute("SELECT score, found_via FROM smart_wallets WHERE wallet = ?", (addr,)).fetchone()
        if old and old[1] != "gmgn":  # our own Helius PnL score wins over GMGN's
            continue
        con.execute("INSERT OR REPLACE INTO smart_wallets VALUES (?,?,?,?,?)",
                    (addr, s["score"], json.dumps(s), "gmgn", int(time.time())))
        n += 1
    con.commit()
    return n


# ---------------- X trends ----------------

def x_trends():
    cfg = apify.config()["x_trends"]
    trends = []
    for c in cfg["countries"]:
        for t in apify.run("x_trends", X_TRENDS, {"country": c, "live": True},
                           cache_secs=cfg["every_min"] * 60):
            if t.get("trend"):
                trends.append({"trend": t["trend"], "period": t.get("timePeriod"), "volume": t.get("volume")})
    return trends


def trend_keys(trends):
    """Normalized trend terms worth matching against token names (>= 4 chars, not filler words)."""
    keys = {}
    for t in trends:
        whole = _norm(t["trend"].lstrip("#$"))
        if len(whole) >= 4 and whole not in _STOP:
            keys[whole] = t["trend"]
        for w in re.findall(r"[A-Za-z0-9]{4,}", t["trend"]):
            n = _norm(w)
            if n not in _STOP and not n.isdigit():
                keys.setdefault(n, t["trend"])
    return keys


def trend_match(symbol, name, keys):
    """The X trend a token is named after, or None."""
    s, n = _norm(symbol), _norm(name)
    for k, trend in keys.items():
        if k == s or k == n or (len(k) >= 5 and (k in n or k in s)):
            return trend
    return None


# ---------------- Google Trends ----------------

def search_rise(term):
    """Last 24 h of Google search interest vs the 6 days before (1.0 = flat). None if no data."""
    cfg = apify.config()["google_trends"]
    items = apify.run("google_trends", G_TRENDS, {"searchTerms": [term], "timeRange": "now 7-d", "maxItems": 1,
                                                  "skipDebugScreen": True}, cache_secs=cfg["cache_h"] * 3600)
    if not items:
        return None
    vals = [(int(p["time"]), (p.get("value") or [0])[0]) for p in items[0].get("interestOverTime_timelineData") or []]
    if len(vals) < 48:
        return None
    cut = vals[-1][0] - 86400
    recent = [v for t, v in vals if t > cut]
    before = [v for t, v in vals if t <= cut]
    base = statistics.mean(before) if before else 0
    return round(statistics.mean(recent) / base, 2) if base else (2.0 if any(recent) else None)


# ---------------- KOL tweets (xquik monitor -> webhook) ----------------

def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def _handle(x):
    if isinstance(x, dict):
        for k in ("username", "userName", "screen_name", "handle"):
            if isinstance(x.get(k), str):
                return x[k]
        for v in x.values():
            h = _handle(v)
            if h:
                return h
    return None


def ingest_kol_event(payload, db_path):
    """Store the CAs and $tickers of one webhook event. The payload shape is not documented, so search all text."""
    text = " ".join(_strings(payload))
    cas = sorted({c for c in telegram._CA.findall(text) if any(ch.isdigit() for ch in c)})
    tickers = sorted({t.upper() for t in telegram._TICKER.findall(text)})
    if not cas and not tickers:
        return 0
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE IF NOT EXISTS kol_mentions (ts INTEGER, handle TEXT, ca TEXT, tickers TEXT, text TEXT)")
    for ca in cas or [""]:
        con.execute("INSERT INTO kol_mentions VALUES (?,?,?,?,?)",
                    (int(time.time()), _handle(payload) or "", ca, ",".join(tickers), text[:500]))
    con.commit()
    con.close()
    return len(cas or [""])


def kol_counts(con, hours=6):
    """CA -> distinct KOL handles that tweeted it recently; ticker -> same."""
    try:
        rows = con.execute("SELECT handle, ca, tickers FROM kol_mentions WHERE ts >= ?",
                           (int(time.time() - hours * 3600),)).fetchall()
    except sqlite3.OperationalError:
        return {}, {}
    by_ca, by_tk = {}, {}
    for h, ca, tks in rows:
        if ca:
            by_ca.setdefault(ca, set()).add(h)
        for t in filter(None, tks.split(",")):
            by_tk.setdefault(t, set()).add(h)
    return {k: len(v) for k, v in by_ca.items()}, {k: len(v) for k, v in by_tk.items()}


def kol_monitor(handles, webhook_url, stop=False):
    """Start (or stop) the xquik monitor for these X accounts; it posts each new tweet to webhook_url.
    Costs ~$0.0045 per account per hour (~$3.24 per account per month) while it runs."""
    inp = {"twitterHandles": handles, "monitorName": "crypto-bot-kol", "webhookUrls": webhook_url,
           "newPosts": True, "replies": False, "quotes": True, "reposts": True, "deletedPosts": True,
           "profileChanges": False, "stop": stop}
    return apify.run("kol_monitor", KOL, inp)
