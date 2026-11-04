"""Audit 4.11. R6/R7/F01/F02: is a strategy's result real, or one lucky trade on borrowed money?

Pure functions over closed trades (dicts with pnl_usd, size_usd, token and an entry/close time), shared by the
Usporedba strategija page (strat positions) and the Demo trading page (paper trades):

- without_top(): the result without the best 1 / 5 trades and without the best token (R7). If the plus disappears
  the result is "koncentriran", not "profitabilan".
- status(): uči (fewer than MIN_CLOSED closed) / kandidat (beats the random control per trade after costs, overall
  and on both time halves, and still beats it without the top 5) / ne diraj pravi novac. Without a control there is
  no "kandidat" (R6). "kandidat" is a status for more testing, never a permission to trade real money (R5).
- portfolio(): replay with a fixed bankroll and no borrowing (F01): a trade whose stake the cash cannot cover is
  skipped, cash returns when the trade closes. Shown next to the research ledger, which keeps buying below $0.
"""
MIN_CLOSED = 100
TOP_K = 5


def _t(x, *names):
    for n in names:
        if x.get(n):
            return x[n]
    return 0


def _pnl(x):
    return x.get("pnl_usd") or 0.0


def without_top(trades, k=TOP_K):
    """{total, n, no_best, no_top5, no_best_token, best_share, concentrated}."""
    pn = sorted((_pnl(t) for t in trades), reverse=True)
    total = sum(pn)
    by_tok = {}
    for t in trades:
        by_tok[t.get("token")] = by_tok.get(t.get("token"), 0.0) + _pnl(t)
    best_tok = max(by_tok.values()) if by_tok else 0.0
    no_best = total - (pn[0] if pn else 0.0)
    no_topk = total - sum(pn[:k])
    no_tok = total - best_tok
    return {"total": total, "n": len(pn), "no_best": no_best, "no_top5": no_topk, "no_best_token": no_tok,
            "best": pn[0] if pn else 0.0, "best_share": (pn[0] / total) if pn and total > 0 else None,
            "concentrated": total > 0 and (no_best <= 0 or no_tok <= 0)}


def _halves(trades):
    ts = sorted(_t(t, "closed_ts", "entry_ts", "opened_ts") for t in trades)
    if len(ts) < 2:
        return [trades]
    cut = ts[len(ts) // 2]
    return [[t for t in trades if _t(t, "closed_ts", "entry_ts", "opened_ts") < cut],
            [t for t in trades if _t(t, "closed_ts", "entry_ts", "opened_ts") >= cut]]


def _per_trade(trades, drop_top=0):
    pn = sorted((_pnl(t) for t in trades), reverse=True)[drop_top:]
    return sum(pn) / len(pn) if pn else None


def status(trades, control=None, min_closed=MIN_CLOSED):
    """(key, label, reason). key in uci / kandidat / ne_diraj."""
    n = len(trades)
    if n < min_closed:
        return "uci", "uči", f"{n} od {min_closed} zatvorenih tradeova; prije toga nema presude"
    if not control:
        return "ne_diraj", "ne diraj pravi novac", "nema kontrole (nasumični ulaz) za usporedbu, a bez nje nema kandidata"
    c = _per_trade(control)
    me = _per_trade(trades)
    if me is None or c is None or me <= c:
        return "ne_diraj", "ne diraj pravi novac", "ne pobjeđuje nasumični ulaz po tradeu nakon troškova"
    for h in _halves(trades):
        hm = _per_trade(h)
        if hm is None or hm <= c:
            return "ne_diraj", "ne diraj pravi novac", "pobjeđuje kontrolu samo u jednoj polovici razdoblja"
    no5 = _per_trade(trades, TOP_K)
    if no5 is None or no5 <= c or no5 <= 0:
        return "ne_diraj", "ne diraj pravi novac", "bez 5 najboljih tradeova više ne pobjeđuje kontrolu"
    return "kandidat", "kandidat", "bolja od nasumičnog ulaza u obje polovice i bez 5 najboljih (samo za daljnje testiranje)"


def portfolio(trades, bankroll=1000.0):
    """Replay in entry order with no borrowing. {value, cash_low, taken, skipped}."""
    ev = []
    for i, t in enumerate(trades):
        size = t.get("size_usd") or 0.0
        ev.append((_t(t, "entry_ts", "opened_ts"), 1, i, size, 0.0))
        ev.append((_t(t, "closed_ts") or _t(t, "entry_ts", "opened_ts"), 0, i, size, _pnl(t)))
    ev.sort(key=lambda e: (e[0], -e[1]))  # same second: open first, so a trade cannot close before it opened
    cash, low, taken, skipped, live = float(bankroll), float(bankroll), 0, 0, set()
    # closes at the same timestamp as an open come before it in reality only if earlier; keep open-first order
    for ts, is_open, i, size, pnl in ev:
        if is_open:
            if size <= cash + 1e-9:
                cash -= size
                live.add(i)
                taken += 1
            else:
                skipped += 1
        elif i in live:
            cash += size + pnl
            live.discard(i)
        low = min(low, cash)
    return {"value": cash, "cash_low": low, "taken": taken, "skipped": skipped}
