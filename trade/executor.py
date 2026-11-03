"""Real buys and sells through Jupiter Ultra, behind a risk gate. trade.db logs every attempt.

Live trading needs all three: the switch on the page /pravi-trade (cfg["on"], trade/settings.py), env TRADE_LIVE=1
and SOLANA_PRIVATE_KEY (both set by the owner in Render). Anything less is dry-run: the same quote is fetched and
logged, nothing is signed or sent. Switch off = no new real buys; sells of real positions still go through as long
as the key is there. Kill switch file trade/STOP also stops every new buy.
"""
import json
import os
import sqlite3
import time

from trade import jupiter, settings, wallet

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STOP_FILE = os.path.join(HERE, "STOP")
LAMPORTS = 1_000_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER UNIQUE, token TEXT, symbol TEXT, opened_ts INTEGER,
    mode TEXT, status TEXT, reason TEXT, sol_in REAL, qty_raw INTEGER, qty_left INTEGER, sol_back REAL,
    fills_done INTEGER DEFAULT 0, closed_ts INTEGER, league_id INTEGER);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, position_id INTEGER, token TEXT, side TEXT, mode TEXT,
    amount_in INTEGER, amount_out INTEGER, cost_pct REAL, status TEXT, reason TEXT, error TEXT, signature TEXT,
    request_id TEXT);
"""


def load_config(path=None):
    with open(path or CONFIG_PATH) as f:
        return json.load(f)


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    con.execute(settings.SCHEMA)
    if "league_id" not in {r[1] for r in con.execute("PRAGMA table_info(positions)")}:
        con.execute("ALTER TABLE positions ADD COLUMN league_id INTEGER")
    return con


def armed():
    """The owner put the key and TRADE_LIVE=1 into Render: real swaps are possible (the switch decides buys)."""
    return os.environ.get("TRADE_LIVE") == "1" and wallet.can_sign()


def is_live(cfg):
    return bool(cfg.get("on")) and armed()


def day_pnl(con, now, mode):
    """SOL won (+) or lost (-) on positions closed since midnight (server time) in this mode."""
    return con.execute("SELECT COALESCE(SUM(sol_back - sol_in),0) FROM positions WHERE mode=? AND status='closed' "
                       "AND closed_ts>=?", (mode, _day_start(now))).fetchone()[0]


def _day_start(now):
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def gate_buy(con, cfg, size_sol, now, live, balance=None):
    """Reason the buy is blocked, or None."""
    if os.path.exists(STOP_FILE):
        return "kill switch (trade/STOP)"
    if size_sol <= 0 or size_sol > cfg["max_sol_per_trade"]:
        return f"{size_sol} SOL iznad limita {cfg['max_sol_per_trade']}"
    spent = con.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE opened_ts>=? AND mode=? "
                        "AND status IN ('open','closed')", (_day_start(now), "live" if live else "dry")).fetchone()[0]
    if spent + size_sol > cfg["max_sol_per_day"] + 1e-9:
        return f"dnevni limit: potrošeno {spent:.3f} od {cfg['max_sol_per_day']} SOL"
    if "max_loss_day" in cfg:
        lost = day_pnl(con, now, "live" if live else "dry")
        if lost <= -cfg["max_loss_day"]:
            return f"dnevni gubitak {lost:+.3f} SOL, granica -{cfg['max_loss_day']} SOL: stop do ponoći"
    n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='open' AND mode=?",
                         ("live" if live else "dry",)).fetchone()[0]
    if n_open >= cfg["max_open"]:
        return f"{n_open} otvorenih pozicija"
    if live:
        if balance is None:
            balance = wallet.sol_balance(wallet.address())
        if balance - size_sol < cfg["min_sol_reserve"]:
            return f"stanje {balance:.3f} SOL, rezerva {cfg['min_sol_reserve']}"
    return None


def swap(input_mint, output_mint, amount_raw, live, max_cost_pct=None):
    """One swap (live) or one quote (dry). Returns {status, amount_in, amount_out, cost_pct, error, ...}."""
    try:
        o = jupiter.order(input_mint, output_mint, amount_raw, taker=wallet.address())
    except Exception as e:
        return {"status": "failed", "error": f"order: {type(e).__name__}: {e}", "amount_in": amount_raw}
    res = {"amount_in": int(o.get("inAmount") or amount_raw), "amount_out": int(o.get("outAmount") or 0),
           "cost_pct": jupiter.cost_pct(o), "request_id": o.get("requestId"), "error": o.get("error")}
    if not res["amount_out"]:
        return {**res, "status": "failed", "error": o.get("error") or "nema rute"}
    if max_cost_pct is not None and res["cost_pct"] is not None and res["cost_pct"] > max_cost_pct:
        return {**res, "status": "blocked", "error": f"trošak {res['cost_pct']}% > {max_cost_pct}%"}
    if not live:
        return {**res, "status": "dry"}
    if not o.get("transaction"):
        return {**res, "status": "failed"}
    try:
        r = jupiter.execute(wallet.sign(o["transaction"]), o["requestId"])
    except Exception as e:
        return {**res, "status": "failed", "error": f"execute: {type(e).__name__}: {e}"}
    if r.get("status") != "Success":
        return {**res, "status": "failed", "error": r.get("error") or str(r.get("code")), "signature": r.get("signature")}
    return {**res, "status": "ok", "signature": r.get("signature"), "error": None,
            "amount_in": int(r.get("inputAmountResult") or res["amount_in"]),
            "amount_out": int(r.get("outputAmountResult") or res["amount_out"])}


def _log(con, now, pid, token, side, mode, res, reason):
    con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, cost_pct, status, "
                "reason, error, signature, request_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(now), pid, token, side, mode, res.get("amount_in"), res.get("amount_out"), res.get("cost_pct"),
                 res["status"], reason, res.get("error"), res.get("signature"), res.get("request_id")))


def buy(con, cfg, token, symbol=None, paper_id=None, size_sol=None, now=None, reason="", league_id=None):
    """Gate, then swap SOL -> token. Always leaves one positions row (open, blocked or failed) so a signal
    is never retried by accident."""
    now, live = now or time.time(), is_live(cfg)
    mode, size_sol = "live" if live else "dry", size_sol or cfg["size_sol"]
    why = gate_buy(con, cfg, size_sol, now, live)
    if why:
        res = {"status": "blocked", "error": why, "amount_in": int(size_sol * LAMPORTS)}
    else:
        res = swap(jupiter.SOL, token, int(size_sol * LAMPORTS), live, cfg["max_cost_pct"])
    ok = res["status"] in ("ok", "dry")
    status = "open" if ok else ("blocked" if res["status"] == "blocked" else "failed")
    cur = con.execute("INSERT INTO positions (paper_id, league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                      "qty_raw, qty_left, sol_back) VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
                      (paper_id, league_id, token, symbol, int(now), mode, status, reason if ok else res.get("error"),
                       res["amount_in"] / LAMPORTS if ok else 0, res.get("amount_out") if ok else 0,
                       res.get("amount_out") if ok else 0))
    _log(con, now, cur.lastrowid, token, "buy", mode, res, reason)
    con.commit()
    return {**res, "id": cur.lastrowid, "status": status, "mode": mode, "swap_status": res["status"]}


def sell(con, cfg, position_id, frac=1.0, close=False, now=None, reason=""):
    """Sell frac of the originally bought quantity (close=True sells everything left)."""
    now = now or time.time()
    token, mode, qty, left, sol_back = con.execute(
        "SELECT token, mode, qty_raw, qty_left, sol_back FROM positions WHERE id=?", (position_id,)).fetchone()
    live = mode == "live"
    if live and not armed():  # never "dry-sell" a real position and mark it closed
        res = {"status": "failed", "error": "prava pozicija, ali ključ ili TRADE_LIVE nisu postavljeni", "amount_in": 0}
        _log(con, now, position_id, token, "sell", mode, res, reason)
        con.commit()
        return res
    if close and live:
        left = min(left, wallet.token_raw_balance(wallet.address(), token)) or left
    amount = left if close else min(left, int(qty * frac))
    if amount <= 0:
        return {"status": "noop"}
    res = swap(token, jupiter.SOL, amount, live)
    if res["status"] in ("ok", "dry"):
        left -= res["amount_in"]
        sol_back += res["amount_out"] / LAMPORTS
        done = close or left <= 0
        con.execute("UPDATE positions SET qty_left=?, sol_back=?, status=?, closed_ts=? WHERE id=?",
                    (max(left, 0), sol_back, "closed" if done else "open", int(now) if done else None, position_id))
    _log(con, now, position_id, token, "sell", mode, res, reason)
    con.commit()
    return res
