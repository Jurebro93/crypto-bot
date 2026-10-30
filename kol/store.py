"""kol.db: X calls, their outcome, call groups, wallet flows around calls and rotation devs.

Own file (one writer per SQLite file, see wallets/store.py). Only run_kol.py writes it; the dashboard and
run_hype read it read-only.

Tables:
  calls      one row per (tweet, token): author, followers, link, kind (call/brag), price path after the tweet
  kols       one row per X account: latest followers, call power and the stats behind it
  tokens     token -> pool used for the price history (DexScreener pair) and supply for mcap
  groups     2+ different authors calling the same token within GROUP_SECS
  flows      Helius swaps around one call: buys before, sells after, insiders
  insiders   wallet bought shortly before a call and sold into it
  kol_wallets wallets that did that on several tokens ("rotation dev")
  signals    per token: the newest group of well-scored KOLs, read by run_hype as feature kol_group
  seen_cache Apify cache rows already copied, so a run does not re-read old ones
  searches   when we last paid for an X search per target
"""
import os
import sqlite3

DB = os.environ.get("KOL_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, url TEXT, text TEXT, followers INTEGER,
    likes INTEGER, retweets INTEGER, views INTEGER, kind TEXT, match TEXT, source TEXT, symbol TEXT,
    first_by_kol INTEGER, first_overall INTEGER,
    p0 REAL, mcap0 REAL, pre2h REAL, r1h REAL, r6h REAL, r24h REAL, max24 REAL, vol_before REAL, vol_after REAL,
    vol_lift REAL, rug INTEGER, complete INTEGER DEFAULT 0, measured_ts INTEGER,
    PRIMARY KEY (tweet_id, token));
CREATE INDEX IF NOT EXISTS calls_token ON calls (token, ts);
CREATE INDEX IF NOT EXISTS calls_handle ON calls (handle, ts);
CREATE TABLE IF NOT EXISTS kols (
    handle TEXT PRIMARY KEY, name TEXT, followers INTEGER, verified INTEGER, first_seen INTEGER, last_seen INTEGER,
    score REAL, power_rel REAL, stats TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY, symbol TEXT, name TEXT, pair TEXT, supply REAL, created_ts INTEGER,
    liquidity REAL, tries INTEGER DEFAULT 0, updated INTEGER);
CREATE TABLE IF NOT EXISTS groups (
    token TEXT, start_ts INTEGER, end_ts INTEGER, n_authors INTEGER, handles TEXT, first_handle TEXT,
    good_authors INTEGER, mcap0 REAL, r1h REAL, max24 REAL, vol_lift REAL, insiders INTEGER, dev_selling INTEGER,
    PRIMARY KEY (token, start_ts));
CREATE TABLE IF NOT EXISTS flows (
    tweet_id TEXT, token TEXT, ts INTEGER, pre_buy_sol REAL, pre_sell_sol REAL, post_buy_sol REAL,
    post_sell_sol REAL, buyers_pre INTEGER, sellers_post INTEGER, insiders INTEGER, insider_sol REAL,
    rotation_selling INTEGER, txs INTEGER, credits INTEGER, done_ts INTEGER, PRIMARY KEY (tweet_id, token));
CREATE TABLE IF NOT EXISTS insiders (
    wallet TEXT, token TEXT, call_ts INTEGER, bought_ts INTEGER, sold_ts INTEGER, sol_in REAL, sol_out REAL,
    PRIMARY KEY (wallet, token));
CREATE TABLE IF NOT EXISTS kol_wallets (
    wallet TEXT PRIMARY KEY, label TEXT, tokens INTEGER, sol_in REAL, sol_out REAL, token_list TEXT,
    first_seen INTEGER, last_seen INTEGER);
CREATE TABLE IF NOT EXISTS signals (
    token TEXT PRIMARY KEY, ts INTEGER, n_good INTEGER, n_authors INTEGER, handles TEXT, dev_selling INTEGER,
    feature REAL);
CREATE TABLE IF NOT EXISTS seen_cache (key TEXT PRIMARY KEY, ts INTEGER);
CREATE TABLE IF NOT EXISTS searches (target TEXT PRIMARY KEY, kind TEXT, last_ts INTEGER, n INTEGER DEFAULT 0);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only handle for other modules; None if run_kol.py has not created the file yet."""
    path = path or DB
    if not os.path.exists(path) or not os.path.getsize(path):  # start.sh touches it before the first run
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def signals(tokens=None, max_age_h=6, path=None):
    """token -> {feature, n_good, handles, dev_selling} for fresh KOL group calls. {} if kol.db is missing."""
    import json
    import time
    con = ro(path)
    if con is None:
        return {}
    try:
        rows = con.execute("SELECT token, n_good, n_authors, handles, dev_selling, feature FROM signals WHERE ts >= ?",
                           (int(time.time() - max_age_h * 3600),)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    want = set(tokens) if tokens is not None else None
    return {t: {"n_good": g, "n_authors": n, "handles": json.loads(h or "[]"), "dev_selling": bool(d), "feature": f}
            for t, g, n, h, d, f in rows if want is None or t in want}


def rotation_wallets(path=None):
    """[(wallet, tokens, label)] for run_wallets harvest."""
    con = ro(path)
    if con is None:
        return []
    try:
        return con.execute("SELECT wallet, tokens, label FROM kol_wallets").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
