"""Natjecanje history: every player's account value over time, for the chart and the rank change on the page.

A snapshot per player every SNAP_EVERY_S (open positions at the live DexScreener price), written by the auto
sell thread of the dashboard process, which is league.db's only writer. 4 players x 96 a day is ~400 small
rows a day; rows older than KEEP_DAYS are dropped. Before the first snapshot existed the curve is rebuilt
from the closed trades (open positions then count at what they cost).
"""
import time

from . import store

SNAP_EVERY_S = 900
KEEP_DAYS = 180

SCHEMA = """CREATE TABLE IF NOT EXISTS equity (ts INTEGER, user TEXT, equity REAL, open INTEGER);
CREATE INDEX IF NOT EXISTS equity_ts ON equity(ts);"""


def _ensure(con):
    con.executescript(SCHEMA)


def last_ts(con):
    try:
        return con.execute("SELECT MAX(ts) FROM equity").fetchone()[0] or 0
    except Exception:
        return 0


def snapshot(con, market, now=None):
    """Write one row per player. Skipped when there are open positions but DexScreener gave no price at all
    (they would count at cost and draw a fake dip)."""
    now = int(now or time.time())
    _ensure(con)
    opened = {t["token"] for t in store.trades(con, status="open")}
    mk = market(opened) if opened else {}
    if opened and not mk:
        return 0
    live = {t: v[:3] for t, v in mk.items()}
    rows = store.leaderboard(con, live)
    con.executemany("INSERT INTO equity VALUES (?,?,?,?)", [(now, r["user"], round(r["equity"], 4), r["open"])
                                                          for r in rows])
    con.execute("DELETE FROM equity WHERE ts < ?", (now - KEEP_DAYS * 86400,))
    con.commit()
    return len(rows)


def maybe_snapshot(con, market, now=None):
    now = now or time.time()
    if now - last_ts(con) >= SNAP_EVERY_S:
        return snapshot(con, market, now)
    return 0


def start_ts(con):
    """When the competition started: the first account."""
    row = con.execute("SELECT MIN(created) FROM accounts").fetchone()
    return row[0] if row and row[0] else None


def series(con, users=None):
    """user -> [(ts, equity)] oldest first: rebuilt from closed trades up to the first snapshot, then snapshots."""
    users = users or store.users()
    try:
        first = con.execute("SELECT MIN(ts) FROM equity").fetchone()[0]
        snaps = con.execute("SELECT ts, user, equity FROM equity ORDER BY ts").fetchall()
    except Exception:
        first, snaps = None, []
    t0 = start_ts(con)
    out = {}
    for u in users:
        acc = con.execute("SELECT start_usd, created FROM accounts WHERE user=?", (u,)).fetchone()
        start = acc[0] if acc else store.START_USD
        begin = (acc[1] if acc and acc[1] else None) or t0
        pts = [(begin, start)] if begin else []
        eq = start
        for t in sorted(store.trades(con, u, "closed"), key=lambda t: t["closed_ts"] or 0):
            if first and (t["closed_ts"] or 0) >= first:
                break
            eq += t["pnl_usd"] or 0
            pts.append((t["closed_ts"], eq))
        out[u] = pts
    for ts, u, e in snaps:
        if u in out:
            out[u].append((ts, e))
    return out


def value_at(points, ts):
    """Last known value at or before ts (None if the series starts later)."""
    v = None
    for t, e in points:
        if t > ts:
            break
        v = e
    return v


def bot_series(trades, since, base=1000.0):
    """The bot's automatic demo account on the same footing as a player: $`base` at the competition start plus
    what its trades closed since then made."""
    pts, eq = [(since, base)], base
    for t in sorted((t for t in trades if t["status"] == "closed" and (t["closed_ts"] or 0) >= since),
                    key=lambda t: t["closed_ts"]):
        eq += t["pnl_usd"] or 0
        pts.append((t["closed_ts"], eq))
    return pts
