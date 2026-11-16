"""Usklađenje: do the numbers of the real wallet add up? (16.11., owner: "krenuo sam sa jednom Solanom, piše da je 1.37
trenutno, a čini mi se da se brojevi ne poklapaju")

Two books describe the same money and the page showed numbers from both without saying how they meet:

  the WALLET  (table equity, trade/equity.py): what is really there. value = free SOL + open positions at the market
              price (+ USDC); PnL = value - money put in. Measured on the chain every 5 min: this one is the truth.
  the LEDGER  (tables positions / orders, trade/executor.py): what each buy and sale took and brought, lot by lot,
              with the network fees Jupiter's quote ESTIMATED (signature, priority fee, the ~0,002 SOL deposit of a
              new token account). The statistics ("67 zatvorenih, +0,188 SOL, najbolji trade Hope +0,211") come from here.

report() puts them side by side, all in SOL, real money (mode 'live') only:

    zatvorene pozicije            sum over closed lots of  SOL back - SOL in - fees
  + otvorene pozicije             their value now (the wallet's own valuation) + what they brought - took - fees so far
  + naknade neuspjelih pokušaja   fees of buys that failed on the chain (their own rows, nothing bought)
  + razlika knjige i novčanika    what is left: PnL of the wallet minus the three lines above
  = ukupni PnL novčanika          value - deposits

The difference is said, never hidden: the wallet is right, and the usual reasons the ledger is off are listed with what
the ledger itself shows of them (estimated fees, lots closed without a recorded sale, sales cut off mid-swap, buys only
the wallet check found, an opening deposit rebuilt from the orders). "ok" = the wallet's own sums hold and the
difference is inside TOL.

Also here, from the same rows: the result per TOKEN (every lot of a token summed: the owner bought Hope 21 times, one
lot's +0,211 said nothing about the token's +0,9), how much of the profit the single best token made, and the deposits
(rent) still locked in empty token accounts (a token fully sold whose account the bot never closed; ~0,002 SOL each),
as an estimate from the ledger: nothing here closes an account or sends anything.

    python3 -m trade.uskladi                    the report of trade.db, as text
    python3 -m trade.uskladi uplata 1.0435      book the opening deposit as verified on the chain (one row of equity;
                                                the old amount is kept in settings 'equity_opening_fix')

Read-only except `uplata`. No network, no RPC, no key. Never raises towards a page: report() answers {"have": False}
with the reason when something is unreadable.
"""
import json
import sqlite3
import time

LAMPORTS = 1_000_000_000
RENT_SOL = 0.00203928       # the rent-exempt deposit of one SPL token account (165 bytes)
TOL_SOL = 0.005             # a difference up to this (or TOL_SHARE of the wallet's value) is "the numbers agree"
TOL_SHARE = 0.005
SUM_TOL = 0.0005            # the wallet's own sums (value = free + positions, PnL = value - deposits): rounding only
RECONCILED = "usklađeno s lancem"       # trade/equity.RECONCILED: a buy only the wallet check found (no orders row)
INTERRUPTED = "prekinuto usred swapa"   # trade/equity.INTERRUPTED: a sale cut off mid-swap, its SOL back unknown


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _summary(con, now):
    from trade import equity
    return equity.summary(con, now) or {}


def _lots(con):
    cols = "id, token, symbol, status, sol_in, qty_raw, qty_left, sol_back, fees_sol, reason, opened_ts, closed_ts"
    return [dict(zip(cols.split(", "), r)) for r in con.execute(
        f"SELECT {cols} FROM positions WHERE mode='live' ORDER BY id")]


def _lot_pnl(p):
    return _f(p["sol_back"]) - _f(p["sol_in"]) - _f(p["fees_sol"])


def _orders(con):
    """Per token: ok buys, ok sales, the time of the last ok buy and of the last rent row (a closed token account);
    plus the ledger's totals: SOL the orders moved, fees booked, rent that came back, sales cut off mid-swap."""
    by, tot = {}, {"moved": 0.0, "fees": 0.0, "rent_back": 0.0, "cut": 0, "sold_pids": set()}
    for token, pid, side, status, a_in, a_out, fee, sig, err, ts in con.execute(
            "SELECT token, position_id, side, status, amount_in, amount_out, fee_lamports, signature, error, ts FROM orders "
            "WHERE mode='live' AND status IN ('ok','failed') ORDER BY id"):
        t = by.setdefault(token, {"buys": 0, "sells": 0, "last_buy": 0, "last_rent": 0})
        fee = fee or 0
        if status == "ok":
            if side == "buy":
                t["buys"] += 1
                t["last_buy"] = max(t["last_buy"], ts or 0)
                tot["moved"] -= (a_in or 0) / LAMPORTS
            elif side == "sell":
                t["sells"] += 1
                tot["sold_pids"].add(pid)
                tot["moved"] += (a_out or 0) / LAMPORTS
            elif side == "rent":
                t["last_rent"] = max(t["last_rent"], ts or 0)
            tot["moved"] -= fee / LAMPORTS
            if fee > 0:
                tot["fees"] += fee / LAMPORTS
            else:
                tot["rent_back"] += -fee / LAMPORTS
        elif sig and fee > 0:           # failed on the chain: it still paid its fee
            tot["moved"] -= fee / LAMPORTS
            tot["fees"] += fee / LAMPORTS
        if side == "sell" and status == "failed" and (err or "").startswith(INTERRUPTED):
            tot["cut"] += 1
    return by, tot


def _tokens(lots, by_orders):
    """[{token, symbol, pnl_sol, lots, buys, sells, open}] of every token with a closed real lot, best first. pnl_sol is
    the sum of its CLOSED lots (an open lot's result is not final and is counted with the open positions)."""
    out = {}
    for p in lots:
        if p["status"] not in ("closed", "open", "pending"):
            continue
        t = out.setdefault(p["token"], {"token": p["token"], "symbol": "", "pnl_sol": 0.0, "lots": 0, "open": False,
                                        "buys": 0, "sells": 0})
        if p["symbol"]:
            t["symbol"] = str(p["symbol"])[:20]
        if p["status"] == "closed":
            t["pnl_sol"] += _lot_pnl(p)
            t["lots"] += 1
        else:
            t["open"] = True
    for tok, t in out.items():
        o = by_orders.get(tok) or {}
        t["buys"], t["sells"] = o.get("buys", 0) or t["lots"], o.get("sells", 0)
        t["pnl_sol"] = round(t["pnl_sol"], 9)
    return sorted((t for t in out.values() if t["lots"]), key=lambda t: -t["pnl_sol"])


def _by_token(tokens):
    """The token view of the closed result: only tokens with no lot open any more ("zatvoreni tokeni"), the best and the
    worst one, and what all the OTHER closed tokens made together (how much of the profit is one token)."""
    done = [t for t in tokens if not t["open"]]
    if not done:
        return {"n": 0, "plus": 0, "sum_sol": 0.0, "best": None, "worst": None, "rest_sol": None, "rest_n": 0}
    best, worst = done[0], done[-1]
    total = sum(t["pnl_sol"] for t in done)
    return {"n": len(done), "plus": sum(1 for t in done if t["pnl_sol"] > 0), "sum_sol": round(total, 9),
            "best": best, "worst": worst if len(done) > 1 else None,
            "rest_sol": round(total - best["pnl_sol"], 9) if len(done) > 1 else None, "rest_n": len(done) - 1}


def _rent(lots, by_orders):
    """The token accounts that should be empty and still hold their deposit, from the ledger alone: tokens the bot
    really bought, with no lot open or in flight, whose account was not closed after the last buy (no 'rent' row).
    An estimate: an account closed by hand, or one that still holds dust, is not seen here."""
    busy = {p["token"] for p in lots if p["status"] in ("open", "pending")}
    bought = {p["token"] for p in lots if p["status"] == "closed" and _f(p["sol_in"]) > 0}
    n = 0
    for tok in bought - busy:
        o = by_orders.get(tok) or {}
        if not o.get("last_rent") or o["last_rent"] < o.get("last_buy", 0):
            n += 1
    return {"n": n, "sol": round(n * RENT_SOL, 6)}


def _opening(con):
    """(ts, SOL, rebuilt from the orders?) of the opening deposit: the first row of the wallet's history."""
    r = con.execute("SELECT ts, flow_sol, src FROM equity ORDER BY ts LIMIT 1").fetchone()
    return (r[0], _f(r[1]), r[2] == "recon") if r else (None, 0.0, False)


def _n(x, dec=3):
    return f"{x:.{dec}f}".replace(".", ",").replace("-", "−")


def _sol(x, dec=3):
    return f"{x:+.{dec}f}".replace(".", ",").replace("-", "−") + " SOL"


def report(con, now=None, summary=None):
    """The reconciliation of the real wallet against the ledger (see the module text). Returns

      {"have": True, "ok": bool, "text": one line for the page, "diff_sol", "tol_sol",
       "wallet": {"value_sol", "free_sol", "pos_sol", "usdc_sol", "deposits_sol", "pnl_sol", "sum_ok", "sum_diff_sol"},
       "closed": {"n", "wins", "pnl_sol", "best": lot, "worst": lot}, "open": {"n", "value_sol", "cash_sol", "pnl_sol"},
       "failed_sol", "book_sol", "lines": [(label, SOL)] of "Kako se zbraja" (the last one is the wallet's PnL),
       "tokens": [...], "by_token": {...}, "rent": {"n", "sol"}, "ledger": {"moved_sol", "fees_sol", "rent_back_sol",
       "positions_sol", "gap_sol"}, "opening": {"ts", "sol", "recon"}, "notes": [Croatian sentences]}

    or {"have": False, "why": ...} when the wallet has no measured value yet or the tables cannot be read.
    summary: trade.equity.summary()'s answer when the caller already holds it (the page's 30-s cache)."""
    now = int(time.time() if now is None else now)
    try:
        s = dict(summary) if summary else _summary(con, now)
        if not s or s.get("value_sol") is None:
            return {"have": False, "why": "vrijednost novčanika još nije izmjerena"}
        lots = _lots(con)
        by_orders, tot = _orders(con)
        op_ts, op_sol, op_recon = _opening(con)
    except sqlite3.Error as e:
        return {"have": False, "why": f"knjiga se ne može pročitati ({type(e).__name__})"}
    value, free, pos = _f(s.get("value_sol")), _f(s.get("sol")), _f(s.get("tokens_sol"))
    usdc_sol = (_f(s.get("usdc")) / s["sol_usd"]) if s.get("usdc") and s.get("sol_usd") else 0.0
    dep, pnl = _f(s.get("net_in_sol")), _f(s.get("pnl_sol"))
    sum_diff = max(abs(value - (free + pos + usdc_sol)), abs(pnl - (value - dep)))
    closed = [p for p in lots if p["status"] == "closed"]
    opened = [p for p in lots if p["status"] == "open"]
    other = [p for p in lots if p["status"] in ("failed", "blocked")]
    c_pnl = sum(_lot_pnl(p) for p in closed)
    o_cash = sum(_lot_pnl(p) for p in opened)
    o_pnl = pos + o_cash
    failed = -sum(_f(p["fees_sol"]) for p in other)
    book = c_pnl + o_pnl + failed
    diff = pnl - book
    tol = max(TOL_SOL, TOL_SHARE * abs(value))
    by_lot = sorted(closed, key=_lot_pnl)

    def lot(p):
        return {"symbol": str(p["symbol"] or "")[:20], "token": p["token"], "pnl": round(_lot_pnl(p), 9)}
    tokens = _tokens(lots, by_orders)
    notes = []
    # what the ledger itself shows of the usual reasons for a difference
    noop = [p for p in closed if _f(p["sol_in"]) > 0 and _f(p["sol_back"]) <= 0 and p["id"] not in tot["sold_pids"]]
    if noop:
        notes.append(f"{len(noop)} {_word(len(noop), 'pozicija je zatvorena', 'pozicije su zatvorene', 'pozicija je zatvoreno')} "
                     f"bez zabilježene prodaje (prodano ručno ili ranijim pokušajem): ulog "
                     f"{_n(sum(_f(p['sol_in']) for p in noop))} SOL u knjizi je gubitak, a SOL je možda stigao u novčanik.")
    if tot["cut"]:
        notes.append(f"{tot['cut']} {_word(tot['cut'], 'prodaja je prekinuta', 'prodaje su prekinute', 'prodaja je prekinuto')} "
                     "usred swapa: što su donijele nije u knjizi.")
    n_rec = sum(1 for p in lots if (p["reason"] or "").startswith(RECONCILED))
    if n_rec:
        notes.append(f"{n_rec} {_word(n_rec, 'kupnju', 'kupnje', 'kupnji')} je našla tek provjera novčanika (bez naloga u knjizi).")
    if tot["fees"] > 0:
        notes.append("Naknade u knjizi su procjena iz Jupiterove ponude (potpis, prioritet, depozit token računa): "
                     f"ukupno knjiženo {_n(tot['fees'])} SOL, stvarno naplaćeno može biti manje.")
    if op_recon:
        notes.append(f"Početna uplata {_n(op_sol, 4)} SOL izračunata je unatrag iz naloga (prije prve snimke "
                     "novčanika); ako je na lancu drugačija, upisuje se naredbom trade.uskladi uplata.")
    pend = sum(1 for p in lots if p["status"] == "pending")
    if pend:
        notes.append(f"{pend} {_word(pend, 'kupnja je', 'kupnje su', 'kupnji je')} upravo u tijeku: zbroj vrijedi nakon nje.")
    positions_sol = c_pnl + o_cash + failed
    lines = [(f"Zatvorene pozicije ({len(closed)})", round(c_pnl, 9)),
             (f"Otvorene pozicije ({len(opened)}), po cijeni sada", round(o_pnl, 9))]
    if abs(failed) >= 0.00005:
        lines.append(("Naknade neuspjelih pokušaja", round(failed, 9)))
    if abs(diff) >= 0.0005:
        lines.append(("Razlika knjige i novčanika", round(diff, 9)))
    lines.append(("Ukupni PnL novčanika (vrijednost − uplate)", round(pnl, 9)))
    sum_ok = sum_diff <= SUM_TOL
    ok = sum_ok and abs(diff) <= tol
    if not sum_ok:
        text = (f"Zbroj novčanika se ne slaže za {_sol(sum_diff, 4).lstrip('+')}: vrijednost {_n(value)} ≠ slobodno "
                f"{_n(free)} + pozicije {_n(pos)}, ili PnL ≠ vrijednost − uplate")
    elif ok:
        text = "Brojevi se slažu ✓"
    else:
        text = (f"Novčanik se slaže ✓ · knjiga tradeova je {'niža' if diff > 0 else 'viša'} za "
                f"{_sol(abs(diff)).lstrip('+')}")
    return {"have": True, "ok": ok, "text": text, "diff_sol": round(diff, 9), "tol_sol": round(tol, 6),
            "wallet": {"value_sol": value, "free_sol": free, "pos_sol": pos, "usdc_sol": round(usdc_sol, 9),
                       "deposits_sol": dep, "pnl_sol": pnl, "sum_ok": sum_ok, "sum_diff_sol": round(sum_diff, 9)},
            "closed": {"n": len(closed), "wins": sum(1 for p in closed if _lot_pnl(p) > 0), "pnl_sol": round(c_pnl, 9),
                       "best": lot(by_lot[-1]) if by_lot else None, "worst": lot(by_lot[0]) if by_lot else None},
            "open": {"n": len(opened), "value_sol": pos, "cash_sol": round(o_cash, 9), "pnl_sol": round(o_pnl, 9)},
            "failed_sol": round(failed, 9), "book_sol": round(book, 9), "lines": lines,
            "tokens": tokens, "by_token": _by_token(tokens), "rent": _rent(lots, by_orders),
            "ledger": {"moved_sol": round(tot["moved"], 9), "fees_sol": round(tot["fees"], 9),
                       "rent_back_sol": round(tot["rent_back"], 9), "positions_sol": round(positions_sol, 9),
                       "gap_sol": round(tot["moved"] - positions_sol, 9)},
            "opening": {"ts": op_ts, "sol": op_sol, "recon": op_recon}, "notes": notes, "ts": s.get("last_ts")}


def _word(n, one, few, many):
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def safe_report(con, now=None, summary=None):
    """report() that never raises (a page calls this)."""
    try:
        return report(con, now, summary)
    except Exception as e:  # noqa: BLE001
        print(f"uskladi: usklađenje nije složeno: {type(e).__name__}: {e}", flush=True)
        return {"have": False, "why": "usklađenje se trenutno ne može složiti"}


def period(con, days, now=None, summary=None):
    """The result of the last `days` days, net of deposits: {"base_sol", "result_sol", "whole"}. result = PnL now - PnL
    of the newest snapshot before the span (0 when the history starts inside it: whole=True, and the result IS the
    total PnL). This replaces "the value's change" (last point minus first point), which counted a deposit inside the
    span as profit and started after the span's first trades."""
    from trade import equity
    now = int(time.time() if now is None else now)
    s = dict(summary) if summary else _summary(con, now)
    if not s or s.get("pnl_sol") is None:
        return {"base_sol": None, "result_sol": None, "whole": False}
    t0 = now - int(days) * 86400
    whole = (s.get("first_ts") or now) >= t0
    base = 0.0 if whole else equity.pnl_before(con, t0)
    return {"base_sol": round(base, 9), "result_sol": round(_f(s["pnl_sol"]) - base, 9), "whole": whole}


def set_opening(con, sol, who="vlasnik", now=None):
    """Book the opening deposit as verified on the chain: the flow of the history's first row becomes `sol` (the row's
    balance stays, so the line itself does not move; only "money put in" and with it PnL do). The amount it replaces
    is kept in settings 'equity_opening_fix'. Returns (old, new). Raises ValueError on a senseless amount."""
    from trade import equity
    sol = float(sol)
    if not 0 < sol < 100_000:
        raise ValueError("uplata mora biti pozitivan iznos u SOL-u")
    equity.ensure(con)
    ts, old, _recon = _opening(con)
    if ts is None:
        raise ValueError("novčanik još nema nijednu snimku")
    now = int(time.time() if now is None else now)
    con.execute("UPDATE equity SET flow_sol=? WHERE ts=?", (round(sol, 9), ts))
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)",
                ("equity_opening_fix", json.dumps({"ts": now, "old": old, "new": sol, "row": ts}), now, who))
    con.commit()
    equity._CACHE.clear()
    return old, sol


def text_report(r):
    """The report as plain lines (the command line, a log)."""
    if not r.get("have"):
        return "Usklađenje: " + (r.get("why") or "nema podataka")
    w = r["wallet"]
    out = [f"Novčanik: vrijednost {w['value_sol']:.4f} = slobodno {w['free_sol']:.4f} + pozicije {w['pos_sol']:.4f}"
           + (f" + USDC {w['usdc_sol']:.4f}" if w["usdc_sol"] else "") + f"; uplate {w['deposits_sol']:.4f}; PnL "
           f"{w['pnl_sol']:+.4f} SOL", "Kako se zbraja:"]
    out += [f"  {'=' if i == len(r['lines']) - 1 else '+'} {lab}: {v:+.4f}" for i, (lab, v) in enumerate(r["lines"])]
    bt = r["by_token"]
    if bt["best"]:
        b = bt["best"]
        out.append(f"Po tokenu: {bt['n']} zatvorenih, {bt['plus']} u plusu, zbroj {bt['sum_sol']:+.4f}; najbolji "
                   f"{b['symbol'] or b['token'][:6]} {b['pnl_sol']:+.4f} ({b['buys']} kupnji, {b['sells']} prodaja)"
                   + (f"; svi ostali zajedno {bt['rest_sol']:+.4f}" if bt["rest_sol"] is not None else ""))
    c = r["closed"]
    if c["best"]:
        out.append(f"Po tradeu: {c['n']} zatvorenih, {c['wins']} dobitnih; najbolji {c['best']['symbol']} "
                   f"{c['best']['pnl']:+.4f}, najgori {c['worst']['symbol']} {c['worst']['pnl']:+.4f}")
    if r["rent"]["n"]:
        out.append(f"Prazni token računi (procjena iz knjige): {r['rent']['n']}, moguće vratiti ~{r['rent']['sol']:.3f} SOL")
    lg = r["ledger"]
    out.append(f"Knjiga naloga: pomaknula {lg['moved_sol']:+.4f}, naknade {lg['fees_sol']:.4f}, vraćeni depoziti "
               f"{lg['rent_back_sol']:.4f}; nalozi minus pozicije {lg['gap_sol']:+.4f}")
    out += ["  · " + n for n in r["notes"]]
    out.append(r["text"])
    return "\n".join(out)


def main(argv=None):
    import sys
    from trade import executor, settings
    argv = list(sys.argv[1:] if argv is None else argv)
    con = executor.connect(settings.DB)
    try:
        if argv[:1] == ["uplata"] and len(argv) == 2:
            old, new = set_opening(con, argv[1].replace(",", "."))
            print(f"Početna uplata: {old:.4f} -> {new:.4f} SOL (staro u settings equity_opening_fix)")
        print(text_report(report(con)))
    finally:
        con.close()


if __name__ == "__main__":
    main()
