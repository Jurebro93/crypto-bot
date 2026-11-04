"""Real buys and sells, behind a risk gate. trade.db logs every attempt.

Routes, tried in order until one works (trade/jupiter.py, trade/pumpportal.py):
  1. Jupiter Swap API v2 (api.jup.ag/swap/v2), 2. Jupiter Ultra (lite-api.jup.ag), 3. PumpPortal (0.5% fee,
  live only, can be switched off on the page). A route is only left for the next one when the swap surely did not
  happen (no quote, not landed, expired, slippage); when Jupiter never answers, the wallet is checked first.
Costs: the Jupiter swap fee (0.05-0.1%) is inside the amounts; network costs (signature, priority fee, rent of a new
token account) are logged per order (fee_lamports) and taken off the profit. After a full sale the empty token
account is closed and its ~0.002 SOL rent comes back (logged as a negative fee).

Live trading needs all three: the switch on the page /pravi-trade (cfg["on"], trade/settings.py), env TRADE_LIVE=1
and SOLANA_PRIVATE_KEY (both set by the owner in Render). Anything less is dry-run: the same quote is fetched and
logged, nothing is signed or sent. Switch off = no new real buys; sells of real positions still go through as long
as the key is there. Kill switch file trade/STOP also stops every new buy.
"""
import json
import os
import sqlite3
import time

from trade import jupiter, pumpportal, settings, wallet

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STOP_FILE = os.path.join(HERE, "STOP")
LAMPORTS = 1_000_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER UNIQUE, token TEXT, symbol TEXT, opened_ts INTEGER,
    mode TEXT, status TEXT, reason TEXT, sol_in REAL, qty_raw INTEGER, qty_left INTEGER, sol_back REAL,
    fills_done INTEGER DEFAULT 0, closed_ts INTEGER, league_id INTEGER, fees_sol REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, position_id INTEGER, token TEXT, side TEXT, mode TEXT,
    amount_in INTEGER, amount_out INTEGER, cost_pct REAL, status TEXT, reason TEXT, error TEXT, signature TEXT,
    request_id TEXT, route TEXT, code INTEGER, fee_lamports INTEGER, prio_lamports INTEGER);
"""
NEW_COLS = {"positions": [("league_id", "INTEGER"), ("fees_sol", "REAL DEFAULT 0")],
            "orders": [("route", "TEXT"), ("code", "INTEGER"), ("fee_lamports", "INTEGER"), ("prio_lamports", "INTEGER")]}
ROUTES = ("v2", "ultra", "pump")
ROUTE_HR = {"v2": "Jupiter", "ultra": "Jupiter Ultra", "pump": "PumpPortal"}


def load_config(path=None):
    with open(path or CONFIG_PATH) as f:
        return json.load(f)


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.executescript(SCHEMA)
    con.execute(settings.SCHEMA)
    for table, cols in NEW_COLS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return con


def armed():
    """The owner put the key and TRADE_LIVE=1 into Render: real swaps are possible (the switch decides buys)."""
    return os.environ.get("TRADE_LIVE") == "1" and wallet.can_sign()


def is_live(cfg):
    return bool(cfg.get("on")) and armed()


DAY_TZ = "Europe/Zagreb"   # audit 4.11. §14.4: "midnight" is Zagreb midnight, not whatever zone the server has


def day_pnl(con, now, mode, tz=None):
    """Today's cash result in this mode (since midnight in DAY_TZ): SOL back minus SOL in on positions closed today,
    minus EVERY network fee charged today, also the ones of failed buys and sells (audit 4.11. C09/T24)."""
    start = _day_start(now, tz)
    closed = con.execute("SELECT COALESCE(SUM(sol_back - sol_in),0) FROM positions WHERE mode=? AND status='closed' "
                         "AND closed_ts>=?", (mode, start)).fetchone()[0]
    fees = con.execute("SELECT COALESCE(SUM(fee_lamports),0) FROM orders WHERE mode=? AND ts>=?",
                       (mode, start)).fetchone()[0] / LAMPORTS
    return closed - fees


def _day_start(now, tz=None):
    """Unix time of the last midnight in `tz` (default DAY_TZ)."""
    import datetime
    from zoneinfo import ZoneInfo
    z = ZoneInfo(tz or DAY_TZ)
    d = datetime.datetime.fromtimestamp(now, z)
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=z).timestamp())


def gate_buy(con, cfg, size_sol, now, live, balance=None, token=None):
    """Reason the buy is blocked, or None."""
    if os.path.exists(STOP_FILE):
        return "kill switch (trade/STOP)"
    if token is not None:   # T22: an auto follow and a manual follow of the same coin = one real position
        dup = con.execute("SELECT id FROM positions WHERE token=? AND mode=? AND status IN ('open','pending')",
                          (token, "live" if live else "dry")).fetchone()
        if dup:
            return f"već postoji otvorena pozicija u ovom tokenu (#{dup[0]})"
    if size_sol <= 0 or size_sol > cfg["max_sol_per_trade"]:
        return f"{size_sol} SOL iznad limita {cfg['max_sol_per_trade']}"
    tz = cfg.get("day_tz")
    spent = con.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE opened_ts>=? AND mode=? "
                        "AND status IN ('open','closed','pending')", (_day_start(now, tz), "live" if live else "dry")).fetchone()[0]
    if spent + size_sol > cfg["max_sol_per_day"] + 1e-9:
        return f"dnevni limit: potrošeno {spent:.3f} od {cfg['max_sol_per_day']} SOL"
    if "max_loss_day" in cfg:
        lost = day_pnl(con, now, "live" if live else "dry", tz)
        if lost <= -cfg["max_loss_day"]:
            return f"dnevni gubitak {lost:+.3f} SOL, granica -{cfg['max_loss_day']} SOL: stop do ponoći"
    n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status IN ('open','pending') AND mode=?",
                         ("live" if live else "dry",)).fetchone()[0]
    if n_open >= cfg["max_open"]:
        return f"{n_open} otvorenih pozicija"
    if live:
        if balance is None:
            balance = wallet.sol_balance(wallet.address())
        need = size_sol + BUY_OVERHEAD_SOL + reserve_sol(cfg, n_open + 1)
        if balance < need:
            return (f"premalo SOL-a: stanje {balance:.4f}, treba {need:.4f} (ulog {size_sol:g} + naknade i depozit "
                    f"{BUY_OVERHEAD_SOL:g} + rezerva za prodaju {reserve_sol(cfg, n_open + 1):.4f})")
    return None


# what one sale costs at most in network fees (signature + a high priority fee), what a buy adds on top of its
# stake (rent of the new token account ~0.00204 + fees), and the floor that always stays in the wallet so the
# open positions can still be sold (Nicholas 3.11.: "mora ostati minimum, barem za dvije transakcije")
SELL_COST_SOL = 0.002
BUY_OVERHEAD_SOL = 0.003
RESERVE_FLOOR_SOL = 2 * SELL_COST_SOL + 0.006   # 0.01: two sales + a margin


def reserve_sol(cfg, n_positions):
    """SOL that must stay in the wallet: the owner's reserve, but never less than the floor or than the fees to
    sell every position that would be open."""
    return max(cfg.get("min_sol_reserve", 0), RESERVE_FLOOR_SOL, n_positions * SELL_COST_SOL)


def _jup(route, input_mint, output_mint, amount_raw, live, max_cost_pct):
    try:
        o = jupiter.order(input_mint, output_mint, amount_raw, taker=wallet.address(), route=route)
    except Exception as e:
        return {"status": "failed", "retry": True, "error": f"{ROUTE_HR[route]} ne odgovara ({type(e).__name__})",
                "amount_in": amount_raw}
    res = {"amount_in": int(o.get("inAmount") or amount_raw), "amount_out": int(o.get("outAmount") or 0),
           "cost_pct": jupiter.cost_pct(o), "request_id": o.get("requestId"), "error": None,
           "fee_lamports": jupiter.fee_lamports(o), "prio_lamports": int(o.get("prioritizationFeeLamports") or 0),
           "error_code": o.get("errorCode")}
    if not res["amount_out"]:
        return {**res, "status": "failed", "retry": True, "error": o.get("error") or "nema rute"}
    if max_cost_pct is not None and res["cost_pct"] is not None and res["cost_pct"] > max_cost_pct:
        return {**res, "status": "blocked", "error": f"trošak {res['cost_pct']}% > {max_cost_pct}%"}
    if not live:
        return {**res, "status": "dry"}
    if not o.get("transaction"):
        return {**res, "status": "failed", "retry": o.get("errorCode") != 1,
                "error": o.get("errorMessage") or o.get("error") or "Jupiter nije dao transakciju"}
    before = None
    if output_mint != jupiter.SOL:   # to tell later whether a buy landed when Jupiter does not answer
        try:
            before = wallet.token_raw_balance(wallet.address(), output_mint)
        except Exception:  # noqa: BLE001
            before = None
    r = jupiter.execute(wallet.sign(o["transaction"]), o["requestId"], route=route)
    if r is None:   # never answered: the swap may or may not have landed, never try another route blind
        if before is not None:
            try:
                after = wallet.token_raw_balance(wallet.address(), output_mint)
            except Exception:  # noqa: BLE001
                after = before
            if after > before:
                return {**res, "status": "ok", "amount_out": after - before, "error": None,
                        "note": "Jupiter nije odgovorio, ali tokeni su u walletu"}
        return {**res, "status": "failed", "retry": False, "error": f"{ROUTE_HR[route]} nije potvrdio swap; "
                "provjeri wallet na Solscanu"}
    code = r.get("code")
    if r.get("status") != "Success":
        return {**res, "status": "failed", "code": code, "signature": r.get("signature"),
                "retry": code in jupiter.NOT_LANDED or code == 6001, "error": jupiter.explain(code, r.get("error")),
                # a transaction that landed and failed onchain still paid its network fee
                "fee_lamports": res["fee_lamports"] if r.get("signature") and code not in jupiter.NOT_LANDED else 0}
    return {**res, "status": "ok", "signature": r.get("signature"), "error": None, "code": 0,
            "amount_in": int(r.get("totalInputAmount") or r.get("inputAmountResult") or res["amount_in"]),
            "amount_out": int(r.get("totalOutputAmount") or r.get("outputAmountResult") or res["amount_out"])}


def _pump(input_mint, output_mint, amount_raw, live):
    """PumpPortal fallback (live only): amounts read from the wallet before and after, fees included in them."""
    if not live:
        return {"status": "failed", "retry": False, "error": "nema rute (PumpPortal radi samo uživo)",
                "amount_in": amount_raw}
    addr = wallet.address()
    buying = input_mint == jupiter.SOL
    mint = output_mint if buying else input_mint
    try:
        sol0, tok0 = wallet.sol_balance(addr), wallet.token_raw_balance(addr, mint)
        if buying:
            tx = pumpportal.trade_local(addr, "buy", mint, round(amount_raw / LAMPORTS, 9), True)
        else:
            pct = min(100.0, 100.0 * amount_raw / tok0) if tok0 else 100.0
            tx = pumpportal.trade_local(addr, "sell", mint, f"{pct:.4f}%", False)
        sig = wallet.send(wallet.sign_raw(tx))
    except Exception as e:
        return {"status": "failed", "retry": False, "error": f"PumpPortal: {type(e).__name__}: {e}"[:300],
                "amount_in": amount_raw}
    ok = wallet.confirmed(sig)
    sol1, tok1 = wallet.sol_balance(addr), wallet.token_raw_balance(addr, mint)
    if not ok:
        return {"status": "failed", "retry": False, "signature": sig, "amount_in": amount_raw,
                "error": "PumpPortal transakcija nije prošla" if ok is False else "PumpPortal: nije potvrđeno u 45 s",
                "fee_lamports": max(0, int(round((sol0 - sol1) * LAMPORTS))) if ok is False else 0}
    if buying:
        return {"status": "ok", "signature": sig, "amount_in": int(round((sol0 - sol1) * LAMPORTS)),
                "amount_out": tok1 - tok0, "fee_lamports": 0, "cost_pct": None, "error": None}
    return {"status": "ok", "signature": sig, "amount_in": tok0 - tok1, "amount_out": int(round((sol1 - sol0) * LAMPORTS)),
            "fee_lamports": 0, "cost_pct": None, "error": None}


def swap(input_mint, output_mint, amount_raw, live, max_cost_pct=None, routes=ROUTES):
    """One swap (live) or one quote (dry), route by route until one works. Returns {status, route, amount_in,
    amount_out, cost_pct, fee_lamports, error, tried, attempts, fee_total, ...}.
    attempts = every route's own result (its signature and the fee it was charged), fee_total = the sum of the fees
    of all attempts: a failed first try that landed onchain still cost money (audit 4.11. C09)."""
    tried, res, attempts = [], None, []
    for route in routes:
        res = (_pump(input_mint, output_mint, amount_raw, live) if route == "pump" else
               _jup(route, input_mint, output_mint, amount_raw, live, max_cost_pct))
        res["route"] = route
        attempts.append(dict(res))
        tried.append(f"{ROUTE_HR[route]}: {res.get('error') or res['status']}")
        if res["status"] != "failed" or not res.get("retry"):
            break
    if res["status"] == "failed" and len(tried) > 1:
        res["error"] = " · ".join(tried)
    res["tried"] = tried
    res["attempts"] = attempts
    res["fee_total"] = sum(a.get("fee_lamports") or 0 for a in attempts)
    return res


def routes_for(cfg):
    return ROUTES if cfg.get("use_pump", True) else ROUTES[:2]


def _log(con, now, pid, token, side, mode, res, reason):
    """One orders row per attempt: earlier failed routes first (each with its own signature and fee), then the
    final result, so the ledger keeps every try and every fee (audit 4.11. C09)."""
    for i, a in enumerate((res.get("attempts") or [])[:-1]):
        _log_one(con, now, pid, token, side, mode, {**a, "status": "failed"}, f"{reason} · pokušaj {i + 1}")
    _log_one(con, now, pid, token, side, mode, res, reason)


def _log_one(con, now, pid, token, side, mode, res, reason):
    con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, cost_pct, status, "
                "reason, error, signature, request_id, route, code, fee_lamports, prio_lamports) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(now), pid, token, side, mode, res.get("amount_in"), res.get("amount_out"), res.get("cost_pct"),
                 res["status"], reason, res.get("error"), res.get("signature"), res.get("request_id"), res.get("route"),
                 res.get("code") if res.get("code") is not None else res.get("error_code"),
                 res.get("fee_lamports") if mode == "live" else None, res.get("prio_lamports")))


def sell_check(token, size_sol, max_cost_pct):
    """Before every buy: can the same amount be sold straight back? (audit 4.11. §20.4, T26). Quotes SOL -> token
    and then token -> SOL for what the first would give; no sell route, or a round trip losing more than twice the
    allowed swap cost, = reason to refuse the buy, whatever the score. A quote is not an executed sale (F10), but a
    honeypot or a pool too thin to exit shows up here for free. Returns None when fine, else the reason."""
    amount = int(size_sol * LAMPORTS)
    err = None
    for route in ("v2", "ultra"):         # the same fallback as the swap itself
        try:
            q1 = jupiter.order(jupiter.SOL, token, amount, route=route)
            got = int(q1.get("outAmount") or 0)
            if not got:
                return None          # no buy route: swap() reports that itself
            q2 = jupiter.order(token, jupiter.SOL, got, route=route)
            back = int(q2.get("outAmount") or 0)
            break
        except Exception as e:  # noqa: BLE001
            err = e
    else:
        return f"provjera prodaje nije uspjela ({type(err).__name__}); ne kupujem naslijepo"
    if not back:
        return "simulacija prodaje: nema rute za prodaju natrag u SOL (moguć honeypot)"
    loss = 100 * (1 - back / amount)
    if max_cost_pct is not None and loss > 2 * max_cost_pct:
        return f"simulacija prodaje: kupnja pa odmah prodaja gubi {loss:.1f}% (granica {2 * max_cost_pct:g}%)"
    return None


def buy(con, cfg, token, symbol=None, paper_id=None, size_sol=None, now=None, reason="", league_id=None):
    """Gate, then swap SOL -> token. Always leaves one positions row (open, blocked or failed) so a signal
    is never retried by accident. The row is written as 'pending' and committed BEFORE anything is sent, so a crash
    between the swap and the bookkeeping leaves a trace that reconcile_pending() matches with the chain (audit C09)."""
    now, live = now or time.time(), is_live(cfg)
    mode, size_sol = "live" if live else "dry", size_sol or cfg["size_sol"]
    why = gate_buy(con, cfg, size_sol, now, live, token=token)
    if not why and cfg.get("sell_check", True):
        why = sell_check(token, size_sol, cfg.get("max_cost_pct"))
    cur = con.execute("INSERT INTO positions (paper_id, league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                      "qty_raw, qty_left, sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,0,0,0,0,0)",
                      (paper_id, league_id, token, symbol, int(now), mode, "blocked" if why else "pending",
                       why or "namjera zapisana, šaljem"))
    pid = cur.lastrowid
    con.commit()
    if why:
        res = {"status": "blocked", "error": why, "amount_in": int(size_sol * LAMPORTS)}
    else:
        res = swap(jupiter.SOL, token, int(size_sol * LAMPORTS), live, cfg["max_cost_pct"], routes_for(cfg))
    ok = res["status"] in ("ok", "dry")
    status = "open" if ok else ("blocked" if res["status"] == "blocked" else "failed")
    fees = (res.get("fee_total", res.get("fee_lamports")) or 0) / LAMPORTS if live else 0
    con.execute("UPDATE positions SET status=?, reason=?, sol_in=?, qty_raw=?, qty_left=?, fees_sol=? WHERE id=?",
                (status, reason if ok else res.get("error"), res["amount_in"] / LAMPORTS if ok else 0,
                 res.get("amount_out") if ok else 0, res.get("amount_out") if ok else 0, fees, pid))
    _log(con, now, pid, token, "buy", mode, res, reason)
    con.commit()
    return {**res, "id": pid, "status": status, "mode": mode, "swap_status": res["status"]}


def reconcile_pending(con, now=None, min_age_s=60, balance_of=None):
    """After a restart: buys left 'pending' (the process died between sending and bookkeeping) are matched with the
    wallet. Tokens in the wallet -> open position with that quantity; none -> failed. Dry ones -> failed.
    Returns the number of rows settled."""
    now = now or time.time()
    rows = con.execute("SELECT id, token, mode FROM positions WHERE status='pending' AND opened_ts<=?",
                       (int(now - min_age_s),)).fetchall()
    n = 0
    for pid, token, mode in rows:
        have = 0
        if mode == "live":
            try:
                have = (balance_of or (lambda t: wallet.token_raw_balance(wallet.address(), t)))(token)
            except Exception:  # noqa: BLE001 - cannot tell yet: leave it pending, try next round
                continue
        if have > 0:
            con.execute("UPDATE positions SET status='open', qty_raw=?, qty_left=?, reason=? WHERE id=?",
                        (have, have, "usklađeno s lancem nakon restarta (SOL ulog nepoznat)", pid))
        else:
            con.execute("UPDATE positions SET status='failed', reason=? WHERE id=?",
                        ("prekinuto prije potvrde; u walletu nema tokena", pid))
        n += 1
    con.commit()
    return n


SELL_BACKOFF_MAX_S = 600


def _sell_wait(con, position_id, now):
    """Seconds to wait before the next try after failed sales of this position: 5, 10, 20 ... up to 10 min,
    so a token without a route (rug) is not hammered every 5 s."""
    rows = con.execute("SELECT ts, status FROM orders WHERE position_id=? AND side='sell' ORDER BY id DESC LIMIT 12",
                       (position_id,)).fetchall()
    n = 0
    for _, st in rows:
        if st != "failed":
            break
        n += 1
    if not n:
        return 0
    return max(0, rows[0][0] + min(SELL_BACKOFF_MAX_S, 5 * 2 ** (n - 1)) - now)


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
    if _sell_wait(con, position_id, now) > 0:
        return {"status": "wait", "error": "čeka ponovni pokušaj"}
    if close and live:
        have = wallet.token_raw_balance(wallet.address(), token)
        if have <= 0:   # nothing left in the wallet (sold by hand or by an earlier try): just close the record
            con.execute("UPDATE positions SET qty_left=0, status='closed', closed_ts=? WHERE id=?", (int(now), position_id))
            con.commit()
            return {"status": "noop"}
        left = min(left, have)
    amount = left if close else min(left, int(qty * frac))
    if amount <= 0:
        return {"status": "noop"}
    res = swap(token, jupiter.SOL, amount, live, None, routes_for(cfg))
    fees = (res.get("fee_total", res.get("fee_lamports")) or 0) / LAMPORTS if live else 0
    if res["status"] in ("ok", "dry"):
        left -= res["amount_in"]
        sol_back += res["amount_out"] / LAMPORTS
        done = close or left <= 0
        con.execute("UPDATE positions SET qty_left=?, sol_back=?, status=?, closed_ts=?, fees_sol=COALESCE(fees_sol,0)+? "
                    "WHERE id=?", (max(left, 0), sol_back, "closed" if done else "open", int(now) if done else None,
                                   fees, position_id))
        if done and live:
            _reclaim_rent(con, now, position_id, token)
    elif fees:
        con.execute("UPDATE positions SET fees_sol=COALESCE(fees_sol,0)+? WHERE id=?", (fees, position_id))
    _log(con, now, position_id, token, "sell", mode, res, reason)
    con.commit()
    return res


def _reclaim_rent(con, now, position_id, token):
    """Close the now empty token account: its rent (~0.002 SOL) goes back to the wallet."""
    try:
        got = wallet.close_empty(wallet._keypair(), token)
    except Exception as e:  # noqa: BLE001 - the sale itself is done, this is only the deposit
        print(f"trade: zatvaranje token računa {token[:6]}: {type(e).__name__}: {e}", flush=True)
        return
    if got:
        con.execute("UPDATE positions SET fees_sol=COALESCE(fees_sol,0)-? WHERE id=?", (got / LAMPORTS, position_id))
        _log(con, now, position_id, token, "rent", "live", {"status": "ok", "amount_out": got, "fee_lamports": -got,
                                                            "route": "rpc"}, "vraćen depozit token računa")
