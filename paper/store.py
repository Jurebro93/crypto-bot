"""paper.db: every candidate the bot looked at (taken or not), price ticks, paper trades, daily reviews.

Candidates that were skipped stay tracked ("shadow") so the review can tell a good skip from a missed winner.
"""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    token TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, origin TEXT, sources TEXT, score REAL,
    features TEXT, price REAL, liquidity REAL, mcap REAL, decision TEXT, reason TEXT,
    rug_verdict TEXT, rug_score REAL, rug_flags TEXT, trade_id INTEGER, url TEXT);
CREATE TABLE IF NOT EXISTS ticks (
    token TEXT, ts INTEGER, price REAL, liquidity REAL, mcap REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, symbol TEXT, opened_ts INTEGER, closed_ts INTEGER,
    status TEXT, exit_reason TEXT, size_usd REAL, entry_px REAL, entry_eff REAL, pnl_usd REAL, ret REAL,
    max_ret REAL, min_ret REAL, state TEXT, config TEXT);
CREATE TABLE IF NOT EXISTS reviews (day TEXT PRIMARY KEY, created INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS rug_budget (day TEXT PRIMARY KEY, used INTEGER);
"""


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    return con


def known(con):
    return {t for (t,) in con.execute("SELECT token FROM candidates")}


def add_candidate(con, c):
    con.execute("INSERT OR IGNORE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (c["token"], c.get("symbol"), int(c["ts"]), c["origin"], ",".join(sorted(c.get("sources") or [])),
                 c.get("score"), json.dumps(c.get("features") or {}), c.get("price"), c.get("liquidity"),
                 c.get("mcap"), c["decision"], c.get("reason"), c.get("rug_verdict"), c.get("rug_score"),
                 json.dumps(c.get("rug_flags") or []), c.get("trade_id"), c.get("url")))


def tick(con, token, ts, price, liq, mcap):
    con.execute("INSERT OR REPLACE INTO ticks VALUES (?,?,?,?,?)", (token, int(ts), price, liq, mcap))


def open_trade(con, token, symbol, pos, cfg):
    cur = con.execute("INSERT INTO trades (token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, state, "
                      "config) VALUES (?,?,?,?,?,?,?,?,?)",
                      (token, symbol, int(pos["opened_ts"]), "open", pos["size_usd"], pos["entry_px"],
                       pos["entry_eff"], json.dumps(pos), json.dumps(cfg)))
    return cur.lastrowid


def save_trade(con, trade_id, pos, res):
    con.execute("UPDATE trades SET status=?, closed_ts=?, exit_reason=?, pnl_usd=?, ret=?, max_ret=?, min_ret=?, "
                "state=? WHERE id=?",
                ("open" if pos["open"] else "closed", pos.get("closed_ts"), res["exit_reason"], res["pnl_usd"],
                 res["ret"], res["max_ret"], res["min_ret"], json.dumps(pos), trade_id))


def open_trades(con):
    return [(i, t, s, json.loads(st)) for i, t, s, st in
            con.execute("SELECT id, token, symbol, state FROM trades WHERE status='open'")]


def path(con, token, since, until=None):
    return con.execute("SELECT ts, price, liquidity FROM ticks WHERE token=? AND ts>? AND ts<=? ORDER BY ts",
                       (token, since, until or time.time() + 1)).fetchall()


def rug_budget_take(con, day, limit):
    used = (con.execute("SELECT used FROM rug_budget WHERE day=?", (day,)).fetchone() or [0])[0]
    if used >= limit:
        return False
    con.execute("INSERT OR REPLACE INTO rug_budget VALUES (?,?)", (day, used + 1))
    return True
