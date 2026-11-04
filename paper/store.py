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
CREATE TABLE IF NOT EXISTS trigger_points (
    token TEXT, ts INTEGER, mode TEXT, symbol TEXT, score REAL, features TEXT, price REAL, liquidity REAL, mcap REAL,
    decision TEXT, reason TEXT, trade_id INTEGER, PRIMARY KEY (token, ts, mode));
CREATE TABLE IF NOT EXISTS reviews (day TEXT PRIMARY KEY, created INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS rug_budget (day TEXT PRIMARY KEY, used INTEGER);
CREATE TABLE IF NOT EXISTS manual_exits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER, frac REAL, ts INTEGER, user TEXT, done_ts INTEGER,
    note TEXT);
"""


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    if "entry_mcap" not in cols:  # older paper.db: add market cap at entry/exit, filled from the ticks
        con.execute("ALTER TABLE trades ADD COLUMN entry_mcap REAL")
        con.execute("ALTER TABLE trades ADD COLUMN exit_mcap REAL")
        con.execute("""UPDATE trades SET
            entry_mcap = (SELECT mcap FROM ticks k WHERE k.token=trades.token AND k.ts<=trades.opened_ts
                          ORDER BY k.ts DESC LIMIT 1),
            exit_mcap = CASE WHEN closed_ts IS NULL THEN NULL ELSE
                (SELECT mcap FROM ticks k WHERE k.token=trades.token AND k.ts<=trades.closed_ts
                 ORDER BY k.ts DESC LIMIT 1) END""")
        con.commit()
    return con


def add_trigger_point(con, c, mode):
    """Every trigger evaluation (mc100k, kol3, aktivni, povratak), taken or skipped: candidates holds one row per
    token, so without this a second look at a token (a comeback after a loss) left no decision point for the shadow
    book to learn from (learn/shadow.py reads this table)."""
    con.execute("INSERT OR IGNORE INTO trigger_points VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (c["token"], int(c["ts"]), mode, c.get("symbol"), c.get("score"), json.dumps(c.get("features") or {}),
                 c.get("price"), c.get("liquidity"), c.get("mcap"), c.get("decision"), c.get("reason"), c.get("trade_id")))


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


def open_trade(con, token, symbol, pos, cfg, mcap=None):
    cur = con.execute("INSERT INTO trades (token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, state, "
                      "config, entry_mcap) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (token, symbol, int(pos["opened_ts"]), "open", pos["size_usd"], pos["entry_px"],
                       pos["entry_eff"], json.dumps(pos), json.dumps(cfg), mcap))
    return cur.lastrowid


def save_trade(con, trade_id, pos, res, mcap=None):
    """mcap: market cap at this observation; stored as the exit market cap once the trade closes."""
    con.execute("UPDATE trades SET status=?, closed_ts=?, exit_reason=?, pnl_usd=?, ret=?, max_ret=?, min_ret=?, "
                "state=?, exit_mcap=COALESCE(?, exit_mcap) WHERE id=?",
                ("open" if pos["open"] else "closed", pos.get("closed_ts"), res["exit_reason"], res["pnl_usd"],
                 res["ret"], res["max_ret"], res["min_ret"], json.dumps(pos), None if pos["open"] else mcap, trade_id))


def open_trades(con):
    return [(i, t, s, json.loads(st)) for i, t, s, st in
            con.execute("SELECT id, token, symbol, state FROM trades WHERE status='open'")]


def path(con, token, since, until=None):
    return con.execute("SELECT ts, price, liquidity FROM ticks WHERE token=? AND ts>? AND ts<=? ORDER BY ts",
                       (token, since, until or time.time() + 1)).fetchall()


def prune_ticks(con, keep_days, now=None):
    """Price ticks older than keep_days go (the 1 GB disk); open trades keep all of theirs. Returns rows deleted."""
    cut = int((now or time.time()) - keep_days * 86400)
    cur = con.execute("DELETE FROM ticks WHERE ts<? AND token NOT IN (SELECT token FROM trades WHERE status='open')",
                      (cut,))
    return cur.rowcount


def rug_budget_take(con, day, limit):
    used = (con.execute("SELECT used FROM rug_budget WHERE day=?", (day,)).fetchone() or [0])[0]
    if used >= limit:
        return False
    con.execute("INSERT OR REPLACE INTO rug_budget VALUES (?,?)", (day, used + 1))
    return True


MANUAL = "rucno"  # exit reason of a sale a person asked for on the Demo trading page


def request_exit(con, trade_id, frac, user=None, now=None):
    """A person asks to sell `frac` (0-1) of what is left of an open demo trade. The paper loop sells it at its next
    price tick (about a minute), so the sale gets the same fee/slippage as the bot's own and nothing races the loop."""
    frac = max(0.0, min(1.0, float(frac)))
    row = con.execute("SELECT status FROM trades WHERE id=?", (int(trade_id),)).fetchone()
    if not row or row[0] != "open" or frac <= 0:
        return False
    con.execute("INSERT INTO manual_exits (trade_id, frac, ts, user) VALUES (?,?,?,?)",
                (int(trade_id), frac, int(now or time.time()), user))
    return True


def pending_exits(con):
    """{trade_id: [(request id, frac of what is left), ...]} not yet carried out, oldest first."""
    out = {}
    for rid, tid, frac in con.execute("SELECT id, trade_id, frac FROM manual_exits WHERE done_ts IS NULL ORDER BY id"):
        out.setdefault(tid, []).append((rid, frac))
    return out


def exit_done(con, request_id, note, now=None):
    con.execute("UPDATE manual_exits SET done_ts=?, note=? WHERE id=?", (int(now or time.time()), note, request_id))


def is_manual(pos):
    """True when a person sold part of this trade by hand: its result is then not the bot's rules' result."""
    return any(f.get("reason") == MANUAL for f in (pos or {}).get("fills") or ())
