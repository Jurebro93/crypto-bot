"""The oscillator scalp rule on 1-minute bars and its cost at a size (pure; walk.py and live.py call the same functions,
so a backtest number is the rule the demo trades).

Bars: [(ts, open, high, low, close, ...)] oldest first (rangedca/data.merge's candles; extra columns ignored). The
rolling window is by TIME (win_s), so a sparse series (only minutes with a trade) works too.

The rule (one fixed set, chosen BEFORE any data was looked at; the walk-forward picks tokens, never parameters, so the
result is not fitted; walk.SENS measures a few neighbours on the fixtures only):
  window   the previous win_s (60 min) of bars, the current bar excluded: lo = the lowest low, hi = the highest high;
           at least min_hist_s (30 min) and MIN_BARS (10) bars of it
  entry    at a bar's CLOSE c when (all of):
             lo <= c <= lo + band x (hi - lo)              the lower quarter of the hour's range, not under its low
             c > the previous bar's close                  the 1-minute momentum stopped falling
             the take-profit price fits under hi           tp_px(c) <= hi: the target net of ALL costs is reachable
                                                           inside the range the token just made (so a tiny swing at a
                                                           small size, where cost eats it, is never bought)
             not in the cooldown (cooldown_s, 2 min after an exit)
           filled at the NEXT bar's open x (1 + entry_slip 0.2 %)
  exit     take profit  the bar's high >= tp_px: filled at tp_px x (1 - exit_slip)
           stop         the bar's low <= entry x (1 - stop_pct 8 %): filled at the bar's LOW x (1 - stop_slip 0.5 %)
                        (the owner's "stops filled at bar low minus slippage": pessimistic on a wick)
           rug          the bar's low <= entry x 0.5: the same fill, reason "rug"
           time stop    time_s (60 min) after the entry: the bar's close x (1 - exit_slip)
           end of data  the last bar's close x (1 - exit_slip), reason "kraj"
           inside a bar the path is open, low, high, close for a rising bar and open, high, low, close for a falling one
           (rangedca/backtest.tick_path "wick"); the entry bar is walked from its open
  target   tp_usd net (1 $ / 2 $ per trade, the owner's "1-2 $") or tp_pct: t = tp_usd / size_usd;
           tp_px = entry x (1 + t) / ((1 - rt) x (1 - exit_slip))   (what the sale returns over the stake = t)
  cost     rt = rangedca/rules.real_cost([size], liq, fee_side, tx_usd, sells=1): 2 x fee a side (the pool's 0.3 %
           PumpSwap + Jupiter's route 0.1 %) + the AMM impact of the buy and of the sale (trade/cost.impact at the
           token's liquidity) + 2 x the network fee of a swap (0.0005 SOL, or the median of trade.db's orders) / size.
           demo_rt: the same trade at the demo account's flat fee a side (trade/cost.fee_side(): league/store.FEE or
           its trade.db calibration, 2.9 % on 15.11.) + impact, so the owner sees both (coordinator 15.11.)
  result   ret = exit / entry x (1 - rt) - 1 (net fraction of the stake), pnl = ret x size_usd
"""
import collections

SIZES_SOL = (0.1, 0.3, 0.5, 1.0)
TARGETS_USD = (1.0, 2.0)
SOL_USD = 150.0            # = rangedca/backtest.BT_SOL_USD when no live SOL price is known
DEFAULT_LIQ = 40_000.0     # = trade/cost.DEFAULT_LIQ (liquidity unknown in history)
MIN_BARS = 10
RULE = {"win_s": 3600, "band": 0.25, "stop_pct": 0.08, "time_s": 3600, "cooldown_s": 120, "entry_slip": 0.002,
        "exit_slip": 0.002, "stop_slip": 0.005, "min_hist_s": 1800, "rug_x": 0.5, "stop_fill": "low"}
REASON_HR = {"tp": "cilj neto", "stop": "stop", "rug": "rug / slom", "time": "vremenski stop", "kraj": "kraj podataka"}


def _f(x, d=None):
    try:
        return float(x) if x is not None else d
    except (TypeError, ValueError):
        return d


# ---------- cost ---------------------------------------------------------------------------------------------------

def real_fee_side(dex=None, url=None):
    """The real account's swap fee a side: the pool's (rangedca/rules.pool_fee) + Jupiter's route fee."""
    from rangedca import rules
    return rules.pool_fee(dex or "pumpswap", url) + rules.ROUTE_FEE   # unknown pool: PumpSwap's 0.3 % (the higher)


def tx_sol():
    """(SOL per swap, where from): the measured network fee (rangedca/trade.tx_fee_sol) or rules.TX_FEE_SOL."""
    try:
        from rangedca import trade as rtrade
        return rtrade.tx_fee_sol()
    except Exception:  # noqa: BLE001
        from rangedca import rules
        return rules.TX_FEE_SOL, "zadano"


def demo_fee_side():
    """The demo account's flat fee a side (trade/cost.fee_side: league/store.FEE or the trade.db calibration)."""
    try:
        from trade import cost
        return cost.fee_side()
    except Exception:  # noqa: BLE001
        return 0.01


def cost_at(size_sol, liq, sol_usd=SOL_USD, fee_side=None, tx=None):
    """{"size_usd", "rt" (real round trip, fraction), "parts"} of one round trip of size_sol in a pool of liq."""
    from rangedca import rules
    from trade import cost
    su = _f(sol_usd, SOL_USD) or SOL_USD
    usd = float(size_sol) * su
    lq = _f(liq) or DEFAULT_LIQ
    fs = real_fee_side() if fee_side is None else float(fee_side)
    txs = rules.TX_FEE_SOL if tx is None else float(tx)
    rt = rules.real_cost([usd], lq, fs, txs * su, sells=1)
    imp = cost.impact(usd, lq)
    return {"size_usd": usd, "rt": rt, "parts": {"fee": 2 * fs, "impact": 2 * imp, "net": 2 * txs * su / usd,
                                                 "liq": lq, "tx_sol": txs}}


def demo_rt(size_usd, liq, fee=None):
    """The round trip at the demo account's flat fee a side + impact (trade/cost.round_trip)."""
    from trade import cost
    return cost.round_trip(size_usd, _f(liq) or DEFAULT_LIQ, demo_fee_side() if fee is None else fee)


def target_frac(size_usd, tp_usd=None, tp_pct=None):
    """The net target as a fraction of the stake: tp_usd / size_usd, or tp_pct."""
    if tp_usd:
        return float(tp_usd) / float(size_usd)
    return float(tp_pct or 0.03)


def tp_px(entry, t, rt, cfg=None):
    c = {**RULE, **(cfg or {})}
    return entry * (1 + t) / ((1 - min(max(rt, 0.0), 0.5)) * (1 - c["exit_slip"]))


def need_move(t, rt, cfg=None):
    """The price move (fraction) from the signal's close to the take profit, entry slippage included."""
    c = {**RULE, **(cfg or {})}
    return (1 + c["entry_slip"]) * tp_px(1.0, t, rt, c) - 1


def net_ret(entry, exit_, rt):
    return exit_ / entry * (1 - rt) - 1


# ---------- the rolling window -------------------------------------------------------------------------------------

def windows(bars, win_s=RULE["win_s"]):
    """[(lo, hi, span_s, n)] per bar i over the bars of (ts_i - win_s, ts_i) (bar i excluded): monotonic deques, O(n)."""
    out = []
    dmin, dmax = collections.deque(), collections.deque()   # indices, lows increasing / highs decreasing
    start = 0
    for i, b in enumerate(bars):
        t = b[0]
        while start < i and bars[start][0] <= t - win_s:
            if dmin and dmin[0] == start:
                dmin.popleft()
            if dmax and dmax[0] == start:
                dmax.popleft()
            start += 1
        if dmin:
            out.append((bars[dmin[0]][3], bars[dmax[0]][2], t - bars[start][0], i - start))
        else:
            out.append((None, None, 0, 0))
        lo, hi = b[3], b[2]
        while dmin and bars[dmin[-1]][3] >= lo:
            dmin.pop()
        dmin.append(i)
        while dmax and bars[dmax[-1]][2] <= hi:
            dmax.pop()
        dmax.append(i)
    return out


def signal(bars, i, win, t, rt, cfg=None):
    """None when bar i's close is an entry, else why (Croatian). win: windows(bars)[i]."""
    c = {**RULE, **(cfg or {})}
    lo, hi, span, n = win
    if lo is None or n < MIN_BARS or span < min(c["min_hist_s"], c["win_s"] * 0.5):
        return "premalo povijesti u prozoru"
    px = bars[i][4]
    if not px or px <= 0 or hi <= lo:
        return "nema raspona"
    if px < lo:
        return "ispod dna prozora (probija dolje)"
    if px > lo + c["band"] * (hi - lo):
        return f"nije u donjih {c['band']:.0%} raspona"
    if i == 0 or not px > bars[i - 1][4]:
        return "još pada (zatvaranje nije iznad prethodnog)"
    if px * (1 + need_move(t, rt, c)) > hi:
        return f"cilj nakon troška ({need_move(t, rt, c):.1%}) iznad vrha prozora"
    return None


def _path(b, from_open=True):
    o, h, l, c = b[1], b[2], b[3], b[4]
    return ((o, "o"), (l, "l"), (h, "h"), (c, "c")) if c >= o else ((o, "o"), (h, "h"), (l, "l"), (c, "c"))


def exit_on_bar(pos, b, cfg=None):
    """(reason, fill) when the open position exits inside bar b, else None. pos {entry, tp_px, stop_px, ts}."""
    c = {**RULE, **(cfg or {})}
    for px, kind in _path(b):
        if kind in ("o", "l") and px <= pos["stop_px"]:
            # the owner's "stop at the bar's low minus slippage" (pessimistic on a wick); stop_fill "level": at the
            # stop (or the open when it gapped under it) minus slippage, the live 5-s loop's best case
            base = b[3] if c.get("stop_fill", "low") == "low" else min(pos["stop_px"], b[1])
            fill = base * (1 - c["stop_slip"])
            return ("rug" if b[3] <= pos["entry"] * c["rug_x"] else "stop"), fill
        if kind in ("o", "h") and px >= pos["tp_px"]:
            return "tp", (max(pos["tp_px"], b[1]) if kind == "o" else pos["tp_px"]) * (1 - c["exit_slip"])
    if b[0] - pos["ts"] >= c["time_s"]:
        return "time", b[4] * (1 - c["exit_slip"])
    return None


def simulate(bars, size_usd, liq, tp_usd=None, tp_pct=None, rt=None, t0=None, t1=None, cfg=None, win=None, drt=None):
    """The trades of one token over bars (entries only for bars with t0 <= ts < t1; the earlier bars are the window's
    warm-up, no look-ahead: a signal at bar i fills at bar i+1's open). Returns [{ts, out_ts, entry, exit, reason,
    ret, pnl, ret_demo, pnl_demo, mins}]. rt: the real round trip (cost_at); drt: the demo-fee round trip (demo_rt)."""
    c = {**RULE, **(cfg or {})}
    if not bars:
        return []
    t = target_frac(size_usd, tp_usd, tp_pct)
    rt = cost_at(size_usd / SOL_USD, liq)["rt"] if rt is None else rt
    drt = rt if drt is None else drt
    win = win or windows(bars, c["win_s"])
    t0 = bars[0][0] if t0 is None else t0
    t1 = bars[-1][0] + 1 if t1 is None else t1
    out, pos, cool, pend = [], None, 0, False

    def close(reason, fill, ts):
        nonlocal pos, cool
        r = net_ret(pos["entry"], fill, rt)
        rd = net_ret(pos["entry"], fill, drt)
        out.append({"ts": pos["ts"], "out_ts": ts, "entry": pos["entry"], "exit": fill, "reason": reason,
                    "ret": r, "pnl": r * size_usd, "ret_demo": rd, "pnl_demo": rd * size_usd,
                    "mins": round((ts - pos["ts"]) / 60, 1)})
        pos, cool = None, ts + c["cooldown_s"]

    for i, b in enumerate(bars):
        ts = b[0]
        if pend:   # the signal of the previous bar fills at this bar's open
            pend = False
            e = b[1] * (1 + c["entry_slip"])
            pos = {"entry": e, "ts": ts, "tp_px": tp_px(e, t, rt, c), "stop_px": e * (1 - c["stop_pct"])}
        if pos:
            hit = exit_on_bar(pos, b, c)
            if hit:
                close(hit[0], hit[1], ts)
        if pos or ts < t0 or ts >= t1 or ts < cool or i + 1 >= len(bars) or bars[i + 1][0] >= t1:
            continue
        if signal(bars, i, win[i], t, rt, c) is None:
            pend = True
    if pos:
        close("kraj", bars[-1][4] * (1 - c["exit_slip"]), bars[-1][0])
    return out


def summary(trades):
    """n, wins, hit, ev_pct (mean net % a trade), ev_usd, pnl_usd, worst_pct, reasons."""
    n = len(trades)
    if not n:
        return {"n": 0, "wins": 0, "hit": None, "ev_pct": None, "ev_usd": None, "pnl_usd": 0.0, "worst_pct": None,
                "ev_demo_pct": None, "pnl_demo_usd": 0.0, "reasons": {}}
    w = sum(1 for x in trades if x["pnl"] > 0)
    rs = {}
    for x in trades:
        rs[x["reason"]] = rs.get(x["reason"], 0) + 1
    return {"n": n, "wins": w, "hit": round(w / n, 3), "ev_pct": round(sum(x["ret"] for x in trades) / n * 100, 3),
            "ev_usd": round(sum(x["pnl"] for x in trades) / n, 4), "pnl_usd": round(sum(x["pnl"] for x in trades), 3),
            "worst_pct": round(min(x["ret"] for x in trades) * 100, 2),
            "ev_demo_pct": round(sum(x["ret_demo"] for x in trades) / n * 100, 3),
            "pnl_demo_usd": round(sum(x["pnl_demo"] for x in trades), 3), "reasons": rs}
