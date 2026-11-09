"""Dokazani novčanici (9.11.2026, Jure): the wallets worth following second by second and copying in the demo.

The audit of 8./9.11. found the only predictor in the database: a wallet's own realized result persists (Spearman
+0.42 before/after a cut among copyable wallets; wallets that were profitable with a 50 %+ win rate on 5+ closed
positions before the cut stayed profitable after it in 23 of 29 cases). Influencer calls showed no such skill, and
our copies of "top" wallets lost 10 % a trade because they copied bots and snipers. So:

copyable   median hold >= min_hold_min, <= max_tpd trades a day, no bot/sniper/bundler/mev/rugger/cex/dev label
           (and not 'izbačen', stripped by ops/prune)
proven     on trades before now - cut_days: closed >= min_closed, realized > 0, win rate >= min_win;
           AND on trades after the cut: closed >= min_after and realized > 0  (proven twice, not once)

run() evaluates every copyable scored wallet from its stored trades (no API calls), stores one row per wallet per
run in `dokazani`, and current() gives the latest passing set to the Helius webhook / PumpPortal list
(kol/chainwatch.wanted) and to the demo copy strategy 'dokazani' (strat/signals, strat/run), which records the
delay and the wallet's own fill for every copy so the slippage of copying is measured, not assumed.
"""
import os
import sqlite3
import time
import json

from wallets import pnl, store as wstore

SCHEMA = """
CREATE TABLE IF NOT EXISTS dokazani (
    wallet TEXT, as_of INTEGER, closed_before INTEGER, realized_before REAL, win_before REAL,
    closed_after INTEGER, realized_after REAL, win_after REAL, passed INTEGER, PRIMARY KEY (wallet, as_of));
CREATE INDEX IF NOT EXISTS dokazani_asof ON dokazani (as_of);
"""
RULE = {"cut_days": 5, "min_closed": 5, "min_win": 0.5, "min_after": 2, "min_hold_min": 10, "max_tpd": 50}
BAD = {"bot", "sniper", "bundler", "mev", "rugger", "cex", "dev", "izbačen"}
MIN_SOL = 0.02


def ensure(con):
    con.executescript(SCHEMA)


def copyable(stats, labels, rule=None):
    r = rule or RULE
    s = stats or {}
    return ((s.get("median_hold_min") or 0) >= r["min_hold_min"] and (s.get("trades_per_day") or 0) <= r["max_tpd"]
            and not set(labels or ()) & BAD)


def _realized(trades):
    pos = pnl.positions(trades)
    closed = [p for p in pos.values() if p["status"] == "closed" and p.get("cost", 0) >= MIN_SOL]
    wins = sum(1 for p in closed if p["realized"] > 0)
    return sum(p["realized"] for p in closed), len(closed), wins


def evaluate(con, now=None, rule=None):
    """[{wallet, closed_before, realized_before, win_before, closed_after, realized_after, win_after, passed}] for
    every copyable scored wallet with trades on both sides of the cut."""
    r = rule or RULE
    now = int(now or time.time())
    cut = now - r["cut_days"] * 86400
    out = []
    for wallet, stats, labels in con.execute("SELECT wallet, stats, labels FROM wallets WHERE scored_at IS NOT NULL").fetchall():
        try:
            s, lab = json.loads(stats or "{}"), json.loads(labels or "[]")
        except ValueError:
            continue
        if not copyable(s, lab, r):
            continue
        trades = wstore.trades(con, wallet)
        before = [t for t in trades if t["ts"] < cut]
        after = [t for t in trades if t["ts"] >= cut]
        if not before or not after:
            continue
        rb, nb, wb = _realized(before)
        ra, na, wa = _realized(after)
        if nb == 0:
            continue
        passed = (nb >= r["min_closed"] and rb > 0 and wb / nb >= r["min_win"] and na >= r["min_after"] and ra > 0)
        out.append({"wallet": wallet, "closed_before": nb, "realized_before": round(rb, 3), "win_before": round(wb / nb, 2),
                    "closed_after": na, "realized_after": round(ra, 3), "win_after": round(wa / na, 2) if na else None,
                    "passed": int(passed)})
    return out


def save(con, rows, now=None):
    ensure(con)
    now = int(now or time.time())
    con.executemany("INSERT OR REPLACE INTO dokazani VALUES (?,?,?,?,?,?,?,?,?)",
                    [(r["wallet"], now, r["closed_before"], r["realized_before"], r["win_before"], r["closed_after"],
                      r["realized_after"], r["win_after"], r["passed"]) for r in rows])
    con.execute("DELETE FROM dokazani WHERE as_of < ?", (now - 30 * 86400,))


def run(con, now=None, log=print):
    now = int(now or time.time())
    rows = evaluate(con, now)
    save(con, rows, now)
    con.commit()
    passed = [r for r in rows if r["passed"]]
    if log:
        tot_a = sum(r["realized_after"] for r in passed)
        log(f"dokazani: {len(passed)} od {len(rows)} kopirljivih novčanika prošlo dvaput (prije i poslije reza); "
            f"poslije reza zajedno {tot_a:+.1f} SOL na {sum(r['closed_after'] for r in passed)} zatvorenih")
    return len(passed), len(rows)


def current(path=None):
    """Set of wallets that passed in the latest run (read-only; empty without the table)."""
    path = path or wstore.DB
    if not path or not os.path.exists(path):
        return set()
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return set()
    try:
        last = con.execute("SELECT MAX(as_of) FROM dokazani").fetchone()[0]
        if not last:
            return set()
        return {w for (w,) in con.execute("SELECT wallet FROM dokazani WHERE as_of=? AND passed=1", (last,))}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def latest(path=None, passed_only=True):
    """Rows of the latest run as dicts (plus the wallet's style/hold/trades-a-day from wallets.stats), best after-cut
    result first; [] without the table."""
    path = path or wstore.DB
    if not path or not os.path.exists(path):
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        con.row_factory = sqlite3.Row
        last = con.execute("SELECT MAX(as_of) FROM dokazani").fetchone()[0]
        if not last:
            return []
        rows = [dict(r) for r in con.execute("SELECT d.*, w.stats, w.labels FROM dokazani d LEFT JOIN wallets w ON w.wallet = d.wallet "
                                             "WHERE d.as_of = ?" + (" AND d.passed = 1" if passed_only else ""), (last,))]
    except sqlite3.Error:
        return []
    finally:
        con.close()
    for r in rows:
        try:
            s = json.loads(r.pop("stats", None) or "{}")
        except ValueError:
            s = {}
        r["style"], r["hold_min"], r["tpd"] = s.get("style"), s.get("median_hold_min"), s.get("trades_per_day")
    rows.sort(key=lambda r: -(r.get("realized_after") or 0))
    return rows


def wallet_buy(hype_db, wallet, mint, near_ts):
    """The wallet's own fill from the live feed (hype.db live_trades): {mcap_sol, price_sol, ts} or None."""
    if not hype_db or not os.path.exists(hype_db):
        return None
    try:
        con = sqlite3.connect(f"file:{hype_db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        r = con.execute("SELECT mcap_sol, price_sol, ts FROM live_trades WHERE wallet=? AND mint=? AND side='buy' "
                        "ORDER BY ABS(ts - ?) LIMIT 1", (wallet, mint, int(near_ts))).fetchone()
        return {"mcap_sol": r[0], "price_sol": r[1], "ts": r[2]} if r else None
    except sqlite3.Error:
        return None
    finally:
        con.close()
