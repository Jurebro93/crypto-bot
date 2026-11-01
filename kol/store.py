"""kol.db: X calls, their outcome, call groups, wallet flows around calls and rotation devs.

Own file (one writer per SQLite file, see wallets/store.py). Only run_kol.py writes it; the dashboard and
run_hype read it read-only.

Tables:
  calls      one row per (tweet, token): author, followers, link, kind (call/brag/warn/bot, buy/sell for wallets),
             price path after the tweet; bad = why the measured path is not trusted (e.g. dust market cap)
  kols       one row per X account: latest followers, call power and the stats behind it
  tokens     token -> pool used for the price history (DexScreener pair) and supply for mcap
  groups     2+ different authors calling the same token within GROUP_SECS
  flows      Helius swaps around one call: buys before, sells after, insiders
  insiders   wallet bought shortly before a call and sold into it
  kol_wallets wallets that did that on several tokens ("rotation dev")
  signals    per token: the newest group of well-scored KOLs, read by run_hype as feature kol_group
  seen_cache Apify cache rows already copied, so a run does not re-read old ones
  searches   when we last paid for an X search per target
  watch      the live watchlist: best KOLs by call power, followed in real time
  monitor    accounts the xquik monitor currently watches (synced to watch)
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
CREATE TABLE IF NOT EXISTS watch (
    handle TEXT PRIMARY KEY, score REAL, since INTEGER, reason TEXT);
CREATE TABLE IF NOT EXISTS monitor (handle TEXT PRIMARY KEY, since INTEGER, last_run INTEGER);
CREATE TABLE IF NOT EXISTS token_hours (token TEXT, hour INTEGER, volume REAL, updated INTEGER,
    PRIMARY KEY (token, hour));
CREATE TABLE IF NOT EXISTS sessions (key TEXT PRIMARY KEY, n INTEGER, hits INTEGER, med_max24 REAL, factor REAL,
    updated INTEGER);
CREATE TABLE IF NOT EXISTS kol_ids (
    wallet TEXT PRIMARY KEY, name TEXT, twitter TEXT, telegram TEXT, source TEXT, pnl REAL, wins INTEGER,
    losses INTEGER, rank INTEGER, first_seen INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS converge (
    token TEXT PRIMARY KEY, ts INTEGER, first_ts INTEGER, score REAL, n_x INTEGER, n_tg INTEGER, n_chain INTEGER,
    n_other INTEGER, platforms TEXT, handles TEXT, mcap0 REAL, dev_selling INTEGER, kol_selling INTEGER,
    updated INTEGER);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS seen_cache (key TEXT PRIMARY KEY, ts INTEGER);
CREATE TABLE IF NOT EXISTS searches (target TEXT PRIMARY KEY, kind TEXT, last_ts INTEGER, n INTEGER DEFAULT 0);
"""


# columns added after the first release (ALTER on old files; CREATE above stays as it was for seed imports)
MIGRATE = [("kols", "bot", "INTEGER DEFAULT 0"), ("kols", "bot_why", "TEXT"),
           ("calls", "bad", "TEXT"), ("calls", "mver", "INTEGER"), ("calls", "mtry", "INTEGER")]


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.executescript(SCHEMA)
    for table, col, typ in MIGRATE:
        if col not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    con.commit()
    return con


def bot_handles(path=None):
    """Handles of automated alert accounts (kol/bots.py); their posts are kind 'bot', not KOL calls."""
    from kol import bots
    con = ro(path)
    try:
        return bots.handles(con)
    finally:
        if con is not None:
            con.close()


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


def session_now(path=None, now=None):
    """{session: asia|eu|us, factor, signal_hit_rate, signal_n} for entry and exit logic (kol/sessions.py)."""
    from kol import sessions
    con = ro(path)
    try:
        return sessions.now_info(con, now)
    finally:
        if con is not None:
            con.close()


def token_sessions(mint, path=None):
    """{session: share of the token's volume} from its 5-min candles; {} if unknown."""
    from kol import sessions
    con = ro(path)
    if con is None:
        return {}
    try:
        return sessions.token_shares(con, mint)
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


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


SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.db.gz")


def import_seed(con, path=SEED):
    """Merge a kol.db made off-server (run_kol.py backfill) into this one, once per seed file: calls, kols, tokens,
    flows, insiders. Rows already here win. Returns new calls, or 0 if missing or already imported."""
    import gzip
    import hashlib
    import shutil
    import tempfile
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        key = "seed:" + hashlib.sha1(f.read()).hexdigest()
    if con.execute("SELECT 1 FROM seen_cache WHERE key = ?", (key,)).fetchone():
        return 0
    tmp = os.path.join(tempfile.mkdtemp(), "seed.db")
    with gzip.open(path, "rb") as src, open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst)
    before = con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    con.execute("ATTACH DATABASE ? AS seed", (tmp,))
    try:
        for t in ("calls", "kols", "tokens", "flows", "insiders", "searches"):
            cols = ", ".join(r[1] for r in con.execute(f"PRAGMA seed.table_info({t})"))  # main may have more
            con.execute(f"INSERT OR IGNORE INTO main.{t} ({cols}) SELECT {cols} FROM seed.{t}")
        con.execute("INSERT OR REPLACE INTO seen_cache VALUES (?, strftime('%s','now'))", (key,))
        con.commit()
    finally:
        con.execute("DETACH DATABASE seed")
        os.remove(tmp)
    return con.execute("SELECT COUNT(*) FROM calls").fetchone()[0] - before


def hook_key():
    """Key for /hook/kol: KOL_HOOK_KEY, or derived from UI_PASSWORD so nothing has to be set by hand."""
    import hashlib
    k = os.environ.get("KOL_HOOK_KEY")
    if k:
        return k
    pw = os.environ.get("UI_PASSWORD")
    return hashlib.sha256(f"kol-hook:{pw}".encode()).hexdigest()[:32] if pw else ""


def converge(tokens=None, max_age_min=60, path=None):
    """token -> {score, first_ts, n_x, n_tg, n_chain, platforms, handles, ...} for fresh multi-source convergences
    (kol/converge.py). {} if kol.db is missing."""
    import json
    import time
    con = ro(path)
    if con is None:
        return {}
    try:
        cur = con.execute("SELECT * FROM converge WHERE ts >= ?", (int(time.time() - max_age_min * 60),))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur]
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    want = set(tokens) if tokens is not None else None
    out = {}
    for r in rows:
        if want is None or r["token"] in want:
            r["platforms"] = json.loads(r["platforms"] or "[]")
            r["handles"] = json.loads(r["handles"] or "[]")
            out[r["token"]] = r
    return out


def chain_key():
    """Key for /hook/chain (Helius webhook of KOL wallets), derived like hook_key."""
    import hashlib
    k = hook_key()
    return hashlib.sha256(f"chain:{k}".encode()).hexdigest()[:32] if k else ""
