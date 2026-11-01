"""Natjecanje history: every player's account value over time, for the chart and the rank change on the page.

A snapshot per player every SNAP_EVERY_S (open positions at the live DexScreener price), written by the auto
sell thread of the dashboard process, which is league.db's only writer. 4 players x 96 a day is ~400 small
rows a day; rows older than KEEP_DAYS are dropped. Before the first snapshot existed the curve is rebuilt
from the closed trades (open positions then count at what they cost).
"""
import json
import time

from . import store

SNAP_EVERY_S = 900
KEEP_DAYS = 180

SCHEMA = """CREATE TABLE IF NOT EXISTS equity (ts INTEGER, user TEXT, equity REAL, open INTEGER);
CREATE INDEX IF NOT EXISTS equity_ts ON equity(ts);"""
JUMP_SHARE = 0.25   # a move of the account this big between two snapshots gets a "?" on the chart ...
JUMP_MIN_USD = 250  # ... and at least this many dollars


def _ensure(con):
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(equity)")}
    if "detail" not in cols:  # open positions' values at the snapshot, to explain a jump on the chart
        con.execute("ALTER TABLE equity ADD COLUMN detail TEXT")
    tcols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    if "peak_px" not in tcols:  # highest price seen while open: "max moguće da se prodalo na vrhu"
        con.execute("ALTER TABLE trades ADD COLUMN peak_px REAL")


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
    detail = {}
    for t in store.trades(con, status="open"):
        if t["token"] in live:
            price, liq, _ = live[t["token"]]
            detail.setdefault(t["user"], {})[t["symbol"] or t["token"][:6]] = round(store.value(t, price, liq), 2)
            if price and price > 0:
                con.execute("UPDATE trades SET peak_px = MAX(COALESCE(peak_px, 0), ?) WHERE id=?", (price, t["id"]))
    con.executemany("INSERT INTO equity (ts, user, equity, open, detail) VALUES (?,?,?,?,?)",
                    [(now, r["user"], round(r["equity"], 4), r["open"], json.dumps(detail.get(r["user"]) or {}))
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


def jumps(con, users=None, since=0):
    """Big moves of a player's account between two snapshots, with a plain explanation for the chart's "?" marks:
    [{ts, user, before, after, text}]. The position whose value moved most is named; a move that is undone in the
    next snapshot is called out as a probable bad price reading (1.11.: Jure's account showed $8k twice for 15
    minutes because DexScreener reported pairless at 80x its real price)."""
    try:
        _ensure(con)
        rows = con.execute("SELECT ts, user, equity, detail FROM equity WHERE ts>=? ORDER BY user, ts",
                           (since,)).fetchall()
    except Exception:
        return []
    by = {}
    for ts, u, e, d in rows:
        if users is None or u in users:
            by.setdefault(u, []).append((ts, e, json.loads(d) if d else None))
    out = []
    for u, pts in by.items():
        skip = None
        for i in range(1, len(pts)):
            if i == skip:  # the drop back after a spike: explained by the spike's mark
                continue
            (t0, e0, d0), (t1, e1, d1) = pts[i - 1], pts[i]
            diff = e1 - e0
            if abs(diff) < max(JUMP_MIN_USD, JUMP_SHARE * abs(e0)):
                continue
            who = ""
            if d0 is not None and d1 is not None:
                moves = {k: d1.get(k, 0) - d0.get(k, 0) for k in set(d0) | set(d1)}
                k = max(moves, key=lambda x: abs(moves[x]), default=None)
                if k and abs(moves[k]) >= 0.5 * abs(diff):
                    a, b = d0.get(k), d1.get(k)
                    who = (f" Najviše se promijenila pozicija {k}: ${a:,.0f} → ${b:,.0f}"
                           + (f" (x{b / a:.1f})" if a and b and b > a else "") + "." if a is not None and b is not None
                           else f" Promjena dolazi od pozicije {k}.")
            back = i + 1 < len(pts) and abs(pts[i + 1][1] - e0) < 0.3 * abs(diff)
            if back:
                skip = i + 1
            text = (f"Račun {'skočio' if diff > 0 else 'pao'} s ${e0:,.0f} na ${e1:,.0f} u 15 minuta.{who}"
                    + (" U idućem mjerenju vratio se natrag, pa je najvjerojatnije bila pogrešna cijena s "
                       "DexScreenera, a ne stvarni rast. Od 1.11. alat takve cijene sam prepoznaje i ne koristi."
                       if back else ""))
            out.append({"ts": t1, "user": u, "before": round(e0, 2), "after": round(e1, 2), "text": text,
                        "bad": bool(back)})
    return sorted(out, key=lambda x: x["ts"])
