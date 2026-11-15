"""holderi.db (HOLDERI_DB, else DATA_DIR/holderi.db, else the project folder): small, one writer (run_holderi.py and the
midcap collector's RugCheck hook, both short processes; WAL off like the other small stores).

    snap          one row per (mint, ts, rank): the top holders of one snapshot with their class
    profile       one row per (mint, ts): the class shares and metrics of that snapshot (JSON), the newest one is read
    xbal          an exchange wallet's balance of a midcap over time (wallet, mint, ts, amount, pct)
    moves         a large move of supply out of a holder (traced: to whom, how, which exchange) - the raw evidence
    signals       every listing / deposit-to-sell / caution signal with its score, reasons and the price then; the price
                  after 1 h / 24 h / 7 d and the control (median midcap) over the same windows, for the measurement
    burze_dodane  exchange wallets added by Grok (MCP submit_exchange_wallet) or found by the heuristics (nepotvrđeno)
    holder_pos    the profitable "diamond" holders of established midcaps: cost basis, unrealized profit, funder, cluster
    holder_buys   what those holders bought (wallet, cluster, token, ts, sol, usd, tokens, mc_at_buy, src_mint, sig)
    follow        the tokens bought by >= 2 clusters and their price after 1 h / 24 h / 7 d (the follow-them measurement)
    funders       a wallet's first SOL funder (from its oldest transactions; a week old at most is re-asked)
    kv            counters (credits a day), the exchange listing lists (lst:<exchange>), notification dedup
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = """
CREATE TABLE IF NOT EXISTS snap (mint TEXT, ts INTEGER, rank INTEGER, owner TEXT, acct TEXT, amount REAL, pct REAL,
    cls TEXT, why TEXT, PRIMARY KEY (mint, ts, rank)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS snap_owner ON snap (owner, ts);
CREATE TABLE IF NOT EXISTS profile (mint TEXT, ts INTEGER, symbol TEXT, mcap REAL, src TEXT, data TEXT,
    PRIMARY KEY (mint, ts));
CREATE TABLE IF NOT EXISTS xbal (wallet TEXT, mint TEXT, ts INTEGER, amount REAL, pct REAL,
    PRIMARY KEY (wallet, mint, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS moves (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, ts INTEGER, sender TEXT,
    sender_cls TEXT, dest TEXT, dest_cls TEXT, exchange TEXT, pct REAL, kind TEXT, sig TEXT, conf REAL, data TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS moves_key ON moves (mint, sender, dest, ts);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, symbol TEXT, ts INTEGER,
    kind TEXT, exchange TEXT, score REAL, reasons TEXT, mcap REAL, px REAL, listed TEXT, notified INTEGER DEFAULT 0,
    px_1h REAL, px_24h REAL, px_7d REAL, ctl_1h REAL, ctl_24h REAL, ctl_7d REAL);
CREATE INDEX IF NOT EXISTS signals_mint ON signals (mint, ts);
CREATE TABLE IF NOT EXISTS burze_dodane (address TEXT PRIMARY KEY, exchange TEXT, kind TEXT, confidence REAL,
    status TEXT, source TEXT, ts INTEGER, who TEXT);
CREATE TABLE IF NOT EXISTS holder_pos (wallet TEXT, mint TEXT, ts INTEGER, amount REAL, pct REAL, first_ts INTEGER,
    cost_usd REAL, value_usd REAL, mult REAL, known_cost REAL, funder TEXT, cluster TEXT, diamond INTEGER,
    PRIMARY KEY (wallet, mint));
CREATE TABLE IF NOT EXISTS holder_buys (wallet TEXT, cluster TEXT, token TEXT, ts INTEGER, sol REAL, usd REAL,
    tokens REAL, mc_at_buy REAL, src_mint TEXT, sig TEXT, PRIMARY KEY (sig, wallet, token));
CREATE INDEX IF NOT EXISTS holder_buys_tok ON holder_buys (token, ts);
CREATE TABLE IF NOT EXISTS follow (token TEXT PRIMARY KEY, symbol TEXT, ts INTEGER, first_buy_ts INTEGER,
    clusters INTEGER, holders INTEGER, mc REAL, liq REAL, px REAL, cost_rt REAL, px_1h REAL, px_24h REAL, px_7d REAL);
CREATE TABLE IF NOT EXISTS funders (wallet TEXT PRIMARY KEY, funder TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def db_path():
    if os.environ.get("HOLDERI_DB"):
        return os.environ["HOLDERI_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "holderi.db")
    return os.path.join(ROOT, "holderi.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM profile LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    try:
        return json.loads(r[0]) if r else default
    except (TypeError, ValueError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


def day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def count(con, now, **add):
    """Adds to today's counters (kv cnt:<day>): helius credits, RugCheck calls, exchange list calls, signals."""
    k = f"cnt:{day(now)}"
    d = kv_get(con, k, {}) or {}
    for a, v in add.items():
        d[a] = round((d.get(a) or 0) + (v or 0), 3)
    kv_put(con, k, d)
    return d


def latest_profiles(con, mints=None, max_age_s=3 * 86400, now=None):
    """{mint: profile dict} of the newest profile per mint (younger than max_age_s)."""
    now = int(now or time.time())
    out = {}
    for m, ts, sym, mc, src, data in con.execute(
            "SELECT p.mint, p.ts, p.symbol, p.mcap, p.src, p.data FROM profile p JOIN (SELECT mint, MAX(ts) mts FROM "
            "profile GROUP BY mint) x ON x.mint = p.mint AND x.mts = p.ts WHERE p.ts >= ?", (now - max_age_s,)):
        if mints is not None and m not in mints:
            continue
        try:
            d = json.loads(data or "{}")
        except ValueError:
            d = {}
        d.update(mint=m, ts=ts, symbol=sym, mcap=mc, src=src)
        out[m] = d
    return out


def snap_rows(con, mint, ts):
    return [dict(zip(("rank", "owner", "acct", "amount", "pct", "cls", "why"), r)) for r in con.execute(
        "SELECT rank, owner, acct, amount, pct, cls, why FROM snap WHERE mint=? AND ts=? ORDER BY rank", (mint, ts))]


def prev_ts(con, mint, ts):
    r = con.execute("SELECT MAX(ts) FROM profile WHERE mint=? AND ts < ?", (mint, ts)).fetchone()
    return r[0] if r else None


def prune(con, now, keep_days=45):
    cut = int(now) - keep_days * 86400
    for t in ("snap", "profile", "xbal"):
        con.execute(f"DELETE FROM {t} WHERE ts < ?", (cut,))
    con.execute("DELETE FROM holder_buys WHERE ts < ?", (int(now) - 120 * 86400,))
