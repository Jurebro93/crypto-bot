"""DCA ("buy the dip") suggestions on open paper trades, and how they turned out.

A suggestion is only logged, never executed: the daily review measures whether buying more at the signal would
have helped (held to the trade's own exit), so the rule earns its place on data before anyone acts on it.
Averaging down a memecoin usually just makes a loser bigger, hence the strict gates: the dip must sit above the
stop loss, liquidity must still be there, the price must already bounce off its low, and only one per trade.
"""
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS dca_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER UNIQUE, token TEXT, symbol TEXT, ts INTEGER,
    price REAL, mcap REAL, liquidity REAL, dip REAL, low REAL, liq_ratio REAL, size_usd REAL, reason TEXT);
"""

DEFAULT = {"enabled": True, "min_drop": -0.2, "sl_buffer": 0.03, "min_liq_ratio": 0.6, "bounce": 0.08,
           "min_age_min": 20, "size_frac": 0.5}


def rules(cfg):
    return {**DEFAULT, **(cfg.get("dca") or {})}


def check(pos, price, liq, ts, cfg):
    """A reason string if this observation is a DCA moment for the position, else None."""
    r = rules(cfg)
    if not r["enabled"] or not pos["open"] or pos["tp_done"] or price <= 0:
        return None
    ret = price / pos["entry_px"] - 1
    liq_ratio = liq / pos["entry_liq"] if pos["entry_liq"] else 0
    off_low = (1 + ret) / (1 + pos["low"]) - 1 if pos["low"] > -1 else 0
    if (ret <= r["min_drop"] and ret > cfg["sl"] + r["sl_buffer"] and liq_ratio >= r["min_liq_ratio"]
            and off_low >= r["bounce"] and ts - pos["opened_ts"] >= r["min_age_min"] * 60):
        return (f"pad {ret:+.0%} od ulaza, odskočio {off_low:+.0%} od dna {pos['low']:+.0%}, "
                f"likvidnost {liq_ratio:.0%} ulazne")
    return None


def log(con, trade_id, token, symbol, pos, price, liq, mcap, ts, reason, cfg):
    """Insert once per trade; returns True if this is a new signal."""
    con.executescript(SCHEMA)
    cur = con.execute("INSERT OR IGNORE INTO dca_signals (trade_id, token, symbol, ts, price, mcap, liquidity, dip, "
                      "low, liq_ratio, size_usd, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (trade_id, token, symbol, int(ts), price, mcap, liq, price / pos["entry_px"] - 1, pos["low"],
                       liq / pos["entry_liq"] if pos["entry_liq"] else 0, pos["size_usd"] * rules(cfg)["size_frac"],
                       reason))
    return cur.rowcount > 0


def outcomes(con, fee=0.01, now=None):
    """Every signal with its result: buying size_usd more at the signal and selling at the trade's exit
    (or the latest price while it is open), plus the best and the 24 h price after the signal."""
    now = now or time.time()
    try:  # read-only callers (the dashboard) may meet a paper.db that has no signals table yet
        sigs = con.execute("SELECT * FROM dca_signals ORDER BY ts").fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for (sid, tid, token, sym, ts, price, mcap, liq, dip, low, ratio, size, reason) in sigs:
        t = con.execute("SELECT status, closed_ts, exit_reason FROM trades WHERE id=?", (tid,)).fetchone()
        status, closed_ts, exit_reason = t or ("?", None, None)
        until = closed_ts or now
        path = con.execute("SELECT ts, price, liquidity FROM ticks WHERE token=? AND ts>? AND ts<=? ORDER BY ts",
                           (token, ts, max(until, ts + 86400))).fetchall()
        to_exit = [p for s, p, _ in path if s <= until and p is not None]
        exit_px = to_exit[-1] if to_exit else price
        day = [p for s, p, _ in path if s <= ts + 86400 and p]
        ret = (exit_px * (1 - fee)) / (price * (1 + fee)) - 1 if price else 0
        out.append({"id": sid, "trade_id": tid, "token": token, "symbol": sym, "ts": ts, "price": price, "mcap": mcap,
                    "dip": dip, "reason": reason, "size_usd": size, "status": status, "exit_reason": exit_reason,
                    "exit_px": exit_px, "ret_to_exit": round(ret, 4), "pnl_usd": round((size or 0) * ret, 2),
                    "max_24h": round(max(day) / price - 1, 4) if day and price else None,
                    "done": status == "closed"})
    return out


def summary(rows):
    done = [r for r in rows if r["done"]]
    if not done:
        return {"n": len(rows), "closed": 0}
    return {"n": len(rows), "closed": len(done), "win": round(sum(r["ret_to_exit"] > 0 for r in done) / len(done), 2),
            "avg": round(sum(r["ret_to_exit"] for r in done) / len(done), 3),
            "pnl": round(sum(r["pnl_usd"] for r in done), 2),
            "rug": round(sum(r["exit_reason"] == "rug" for r in done) / len(done), 2)}
