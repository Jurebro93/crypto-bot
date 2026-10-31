"""Shared wallet registry in wallets.db, used by every module that touches wallets.

Own file, not calendar.db: the project folder is a synced network disk and two processes writing the same
SQLite file there lose each other's writes (seen 2026-10-30). One writer per file is the safe pattern.

    from wallets import store as wstore
    con = wstore.connect()
    wstore.observe(con, wallet, token=mint, source="hype", role="early_buyer", ts=..., sol_in=1.2)
    wstore.label(con, wallet, "rugger")
    con.commit()

Tables:
  wallets          one row per wallet: where it was seen, labels, latest score, refresh schedule
  wallet_sightings wallet x token x source x role (free: comes from analyses we already run)
  wallet_trades    parsed swaps (one row per tx and mint), so PnL can be recomputed without new API calls
  wallet_pnl       score / realized / unrealized history, one row per scoring run
  helius_credits   spent credits per call, for the monthly budget
"""
import json
import os
import sqlite3
import time

DB = os.environ.get("WALLET_DB", os.path.join(os.path.dirname(__file__), "..", "wallets.db"))

# labels that keep a wallet off the copytrading list whatever its PnL
BAD_LABELS = {"bot", "rugger", "bundler", "insider", "dev", "cex", "mev", "sniper", "funder_of_rugger"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    wallet TEXT PRIMARY KEY, first_seen INTEGER, last_seen INTEGER, sightings INTEGER DEFAULT 0,
    sources TEXT DEFAULT '{}', labels TEXT DEFAULT '[]', priority REAL DEFAULT 0,
    score REAL, copy_score REAL, tier TEXT, stats TEXT,
    last_tx_ts INTEGER, history_from INTEGER, scored_at INTEGER, next_check INTEGER, credits INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS wallets_next ON wallets (next_check);
CREATE TABLE IF NOT EXISTS wallet_sightings (
    wallet TEXT, token TEXT, source TEXT, role TEXT, ts INTEGER, sol_in REAL, extra TEXT,
    PRIMARY KEY (wallet, token, source, role));
CREATE INDEX IF NOT EXISTS sightings_token ON wallet_sightings (token);
CREATE TABLE IF NOT EXISTS wallet_trades (
    wallet TEXT, sig TEXT, ts INTEGER, mint TEXT, tokens REAL, sol REAL, kind TEXT,
    PRIMARY KEY (sig, wallet, mint));
CREATE INDEX IF NOT EXISTS trades_wallet ON wallet_trades (wallet, ts);
CREATE TABLE IF NOT EXISTS wallet_pnl (
    wallet TEXT, ts INTEGER, realized_sol REAL, unrealized_sol REAL, win_rate REAL, closed INTEGER,
    score REAL, copy_score REAL, PRIMARY KEY (wallet, ts));
CREATE TABLE IF NOT EXISTS helius_credits (ts INTEGER, method TEXT, credits INTEGER, wallet TEXT);
"""

# how much one sighting raises a wallet's place in the scoring queue
ROLE_WEIGHT = {"early_buyer": 2.0, "smart": 3.0, "top_trader": 3.0, "holder": 0.5, "manual": 10.0,
               "dev": -5.0, "bundler": -5.0, "sniper": 1.0, "funder": -1.0, "dust": 0.0}


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.executescript(SCHEMA)
    return con


def _labels(con, wallet):
    row = con.execute("SELECT labels FROM wallets WHERE wallet=?", (wallet,)).fetchone()
    return set(json.loads(row[0] or "[]")) if row else set()


def observe(con, wallet, token=None, source="manual", role="seen", ts=None, sol_in=None, extra=None):
    """Record that an analysis saw this wallet. Cheap: no API call, just bookkeeping and queue priority."""
    now = int(time.time())
    ts = int(ts or now)
    new = con.execute("INSERT OR IGNORE INTO wallet_sightings VALUES (?,?,?,?,?,?,?)",
                      (wallet, token or "", source, role, ts, sol_in, json.dumps(extra) if extra else None)).rowcount
    con.execute("INSERT OR IGNORE INTO wallets (wallet, first_seen, last_seen) VALUES (?,?,?)", (wallet, ts, ts))
    if not new:
        return
    row = con.execute("SELECT sources, priority FROM wallets WHERE wallet=?", (wallet,)).fetchone()
    src = json.loads(row[0] or "{}")
    src[source] = src.get(source, 0) + 1
    prio = (row[1] or 0) + ROLE_WEIGHT.get(role, 1.0)
    con.execute("UPDATE wallets SET last_seen=MAX(last_seen, ?), sightings=sightings+1, sources=?, priority=?, "
                "next_check=CASE WHEN next_check IS NULL OR next_check > ? THEN ? ELSE next_check END WHERE wallet=?",
                (ts, json.dumps(src), prio, now, now, wallet))
    if role in ("dev", "bundler", "sniper"):
        label(con, wallet, role)


def label(con, wallet, name, on=True):
    con.execute("INSERT OR IGNORE INTO wallets (wallet, first_seen, last_seen) VALUES (?,?,?)",
                (wallet, int(time.time()), int(time.time())))
    labels = _labels(con, wallet)
    labels = labels | {name} if on else labels - {name}
    con.execute("UPDATE wallets SET labels=? WHERE wallet=?", (json.dumps(sorted(labels)), wallet))


def labels(con, wallet):
    return _labels(con, wallet)


def save_trades(con, wallet, rows):
    con.executemany("INSERT OR IGNORE INTO wallet_trades VALUES (?,?,?,?,?,?,?)",
                    [(wallet, r["sig"], r["ts"], r["mint"], r["tokens"], r["sol"], r["kind"]) for r in rows])


def trades(con, wallet, since=0):
    cur = con.execute("SELECT sig, ts, mint, tokens, sol, kind FROM wallet_trades WHERE wallet=? AND ts>=? ORDER BY ts",
                      (wallet, since))
    return [dict(zip(("sig", "ts", "mint", "tokens", "sol", "kind"), r)) for r in cur]


def save_score(con, wallet, s, tier, next_check, last_tx_ts=None, history_from=None, credits=0):
    now = int(time.time())
    con.execute("UPDATE wallets SET score=?, copy_score=?, tier=?, stats=?, scored_at=?, next_check=?, "
                "last_tx_ts=COALESCE(?, last_tx_ts), history_from=COALESCE(history_from, ?), credits=credits+? "
                "WHERE wallet=?",
                (s["score"], s["copy_score"], tier, json.dumps(s), now, next_check, last_tx_ts, history_from,
                 credits, wallet))
    con.execute("INSERT OR REPLACE INTO wallet_pnl VALUES (?,?,?,?,?,?,?,?)",
                (wallet, now, s["realized_sol"], s["unrealized_sol"], s["win_rate"], s["closed"], s["score"],
                 s["copy_score"]))


def log_credits(con, method, credits, wallet=None):
    con.execute("INSERT INTO helius_credits VALUES (?,?,?,?)", (int(time.time()), method, credits, wallet))


def credits_since(con, since_ts):
    return con.execute("SELECT COALESCE(SUM(credits),0) FROM helius_credits WHERE ts>=?", (since_ts,)).fetchone()[0]


def queue(con, limit, now=None):
    """Wallets due for a (re)check, best first. Never-scored wallets go by priority, scored ones by tier."""
    now = now or int(time.time())
    # rechecks of scored wallets first (cheap, and they are the ones that matter), then fresh ones by priority
    cur = con.execute("""SELECT wallet, scored_at, labels FROM wallets
                         WHERE next_check IS NOT NULL AND next_check <= ? AND priority > 0
                         ORDER BY (scored_at IS NULL) ASC, COALESCE(copy_score, 0) DESC, priority DESC, last_seen DESC""",
                      (now,))
    out = []
    for wallet, scored_at, lab in cur:
        if set(json.loads(lab or "[]")) & {"rugger", "cex", "mev"}:
            continue
        out.append((wallet, scored_at))
        if len(out) >= limit:
            break
    return out


def signal_wallets(con, min_score=50):
    """Profitable wallets of any style (bots and snipers included): when they buy, it's a signal even if
    we can't copy them. {wallet: style}."""
    out = {}
    for w, stats, lab in con.execute("SELECT wallet, stats, labels FROM wallets WHERE score >= ?", (min_score,)):
        if set(json.loads(lab or "[]")) & {"rugger", "bundler", "insider", "dev", "funder_of_rugger"}:
            continue
        out[w] = json.loads(stats or "{}").get("style", "?")
    return out


def import_hype(con, hype_db):
    """One-time pull of the hype module's smart_wallets table into the shared registry."""
    if not os.path.exists(hype_db):
        return 0
    src = sqlite3.connect(hype_db)
    n = 0
    try:
        rows = src.execute("SELECT wallet, score, stats, found_via, updated FROM smart_wallets").fetchall()
    except sqlite3.OperationalError:
        return 0
    for wallet, score, stats, found_via, updated in rows:
        for mint in (found_via or "").split(","):
            if mint:
                observe(con, wallet, mint, "hype_learn", "early_buyer", updated)
                n += 1
        if json.loads(stats or "{}").get("bot"):
            label(con, wallet, "bot")
    return n


def import_seed(con, path=None):
    """wallets/seed_retro.json: early buyers of several past pumps, found offline by retro/smart.py."""
    path = path or os.path.join(os.path.dirname(__file__), "seed_retro.json")
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        rows = json.load(f).get("wallets", [])
    for r in rows:
        extra = {k: r[k] for k in ("tokens", "wins", "hit_rate", "realized_sol", "score") if k in r}
        observe(con, r["wallet"], None, "retro", "smart", extra=extra)
    return len(rows)


def import_kol(con, kol_db=None):
    """Rotation devs from kol.db (run_kol.py flows): bought before KOL calls and sold into them on 3+ tokens.
    Labelled insider + rotation_dev, which keeps them off the copy list. One-off flippers stay only in kol.db."""
    try:
        from kol import store as kstore
    except ImportError:
        return 0
    n = 0
    for wallet, tokens, lab in kstore.rotation_wallets(kol_db):
        if lab != "rotation_dev":
            continue
        observe(con, wallet, None, "kol", "insider", extra={"tokens": tokens})
        label(con, wallet, "insider")
        label(con, wallet, "rotation_dev")
        n += 1
    return n
