"""Entry, exit, base-rate and cost rules of momentum_scalp (pure: no I/O except the round-trip cost, which
reads trade/cost's cached fee calibration). The data job (momentum/job.py), the paper
trader (momentum/trade.py) and the backtest (momentum/backtest.py) call the same functions, so a backtest or a base
rate number is the rule that would trade.

Entry (every condition must be KNOWN and pass; an unknown input is a reason, never a guess in our favour):
  bonded           a pool with liquidity, not the pump.fun curve (CLAUDE.md: new pump.fun tokens are not taken)
  mcap             30k .. 3M (CLAUDE.md: never under 30k)
  liquidity        >= $15k (trade/cost.LIQ_HARD_MIN: the owner's only liquidity block, 11.11. rule B)
  change 5 min     +5 % .. +15 % (a jump that is under way, not one that already ran)
  buy share 5 min  buys / (buys + sells) transactions of the last 5 minutes >= 0.6
  volume spike     volume of the last 5 min >= 3x the average 5-min volume of the hour before it:
                   vol_m5 / ((vol_h1 - vol_m5) / 11); no baseline (nothing traded in the hour before) = unknown
  (fees / volume >= 0.2 % was removed 11.11., owner's rule B: a property of the pool that never caught anything)
  turnover         volume 1 h / liquidity <= 25x (scan config max_turnover_h1: volume that spins the pool many times)
  anti-wash        (the real check, wash_check) unique traders against transactions and volume, like scan/filters'
                   max_wash: from the token's PumpPortal trades (exact wallets, free) the rug filter's wash score
                   (round trips, top-5 wallets' share, repeated sizes, bot timing) <= 50, transactions per wallet <= 4,
                   USD per wallet in the hour <= max($1,500, 2 % of liquidity), >= 20 unique wallets; from GeckoTerminal
                   (unique buyers / sellers per window) the same ratios on (buyers + sellers), which counts a wallet
                   that both bought and sold twice, so its ratios are lower bounds (the lenient side; said in the reason)
  buyers rising    >= 8 unique buyers in the last 5 min and more than 1.2x the 5 min before (PumpPortal: exact
                   windows) or 1.5x the hour's average per 5 min (GeckoTerminal: (buyers_h1 - buyers_m5) / 11, a lower
                   bound of the earlier windows' buyers, hence the stricter factor)
  rug              the verdict the scanner and get_trade_candidates use (ui/kandidati.rug_view): level hard or risk
                   is a reason
  top 10           top 10 wallets < 35 % of the supply (scan.db / topcheck / rug.db, else Helius within the day cap)
  shill network    nobody of the shill network called it in the last hour: a paid shiller (kol/shillers) or a member
                   of a caller crew graded exit_liquidity or bad (kol/groupdisc)
Exit: half at +15 % (TP1); the rest on an 8 % trailing stop from the peak; stop -10 % from the entry on everything
still held; time stop: everything out 45 minutes after the entry. A stale price (> 60 s) fires only the stop.
Base rate: for EVERY signal (traded or not) whether +15 % came before -10 % within 45 min (the honest hit rate of
the entry), and the result of the exit rules above on the same path after the round-trip cost.

Round-trip cost: trade/cost.round_trip, the ONE model (11.11., owner's rule A): 2 x fee_side + 2 x the AMM impact
of the stake (usd / (liquidity / 2 + usd)); fee_side = league/store.FEE (1 % a side) until trade.db orders.cost_pct
calibrates it. At $15 in a $40k pool that is 2 % + 2 x 0.07 % = ~2.15 %. With TP +15 / SL -10 and 2-3 % round trip the
break-even hit rate is (10 + c) / 25 = ~49-52 %, i.e. ~50 %, NOT 45 % (break_even_p).
"""

from trade import cost as _cost

RULES = {
    "mcap_min": 30_000, "mcap_max": 3_000_000, "liq_min": _cost.LIQ_HARD_MIN,
    "ch5_min": 0.05, "ch5_max": 0.15, "buy_share_min": 0.6, "vol_x_min": 3.0,
    "turnover_max": 25.0,
    "buyers_min_5m": 8, "buyers_x_exact": 1.2, "buyers_x_hour": 1.5,
    "wash_max": 50.0, "tx_per_trader_max": 4.0, "usd_per_trader_min_cap": 1500.0, "usd_per_trader_liq": 0.02,
    "traders_min_h1": 20, "top10_max": 35.0,
    "tp1": 0.15, "tp1_share": 0.5, "trail": 0.08, "stop": 0.10, "time_s": 45 * 60,
    "cooldown_s": 45 * 60, "chase_max": 0.05,
}
FEE_SIDE = _cost.FEE_DEMO     # league/store.FEE: the demo account's fee per side (its booking in simulate / _net)
LOT_USD = _cost.DEFAULT_USD   # ~0.1 SOL, the Autopilot's size_sol
DEFAULT_LIQ = _cost.DEFAULT_LIQ   # pool depth for the impact when the liquidity is not known


def _r(cfg):
    return {**RULES, **(cfg or {})}


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# ---------- cost and EV -------------------------------------------------------------------------------------------
def impact(usd, liq):
    return _cost.impact(usd, liq)


def round_trip_cost(usd=LOT_USD, liq=None, fee_side=None):
    """Fraction of the stake lost to one buy and one sell: trade/cost.round_trip (fee both sides, calibrated when
    trade.db has measured swaps, + the pool impact both ways). fee_side given: that fee instead."""
    return _cost.round_trip(usd, liq, fee_side)


def ev(p, tp, sl, cost):
    """EV per trade as a fraction of the stake: p x TP - (1 - p) x SL - cost (tp, sl, cost fractions, sl > 0)."""
    return p * tp - (1 - p) * sl - cost


def break_even_p(tp, sl, cost):
    """The hit rate at which ev() is 0: (sl + cost) / (tp + sl). TP 0.15 / SL 0.10 / cost 0.025 -> 0.50."""
    return (sl + cost) / (tp + sl) if tp + sl > 0 else None


# ---------- entry -------------------------------------------------------------------------------------------------
def vol_x(vol_m5, vol_h1):
    """Volume of the last 5 min / the average 5-min volume of the 55 min before it; None without a baseline."""
    v5, v1 = _f(vol_m5), _f(vol_h1)
    if v5 is None or v1 is None:
        return None
    base = (v1 - v5) / 11
    if base <= 0:
        return None
    return v5 / base


def buy_share(buys, sells):
    b, s = _f(buys), _f(sells)
    if b is None or s is None or b + s <= 0:
        return None
    return b / (b + s)


def cheap_check(m, cfg=None):
    """The conditions DexScreener's free snapshot answers. m: {price, mcap, liq, vol_m5, vol_h1, buys_m5, sells_m5,
    ch_m5 (percent, as DexScreener), bonded, fee_rate}. Returns None or the reason in Croatian."""
    c = _r(cfg)
    if not m or not _f(m.get("price")):
        return "nema cijene"
    if not m.get("bonded"):
        return "još na pump.fun krivulji ili bez poola (uzimaju se bondani)"
    mcap, liq = _f(m.get("mcap")) or 0, _f(m.get("liq")) or 0
    if mcap < c["mcap_min"]:
        return f"MC ${mcap:,.0f} ispod 30k"
    if mcap > c["mcap_max"]:
        return f"MC ${mcap:,.0f} iznad ${c['mcap_max']:,.0f}"
    if liq < c["liq_min"]:
        return f"likvidnost ${liq:,.0f}, treba ${c['liq_min']:,.0f}"
    ch = _f(m.get("ch_m5"))
    if ch is None:
        return "promjena 5 min nepoznata"
    ch /= 100.0
    if ch < c["ch5_min"] - 1e-9:
        return f"cijena 5 min {ch:+.1%} (treba {c['ch5_min']:+.0%} do {c['ch5_max']:+.0%})"
    if ch > c["ch5_max"] + 1e-9:
        return f"cijena 5 min {ch:+.1%}: skok je već prošao (najviše {c['ch5_max']:+.0%})"
    bs = buy_share(m.get("buys_m5"), m.get("sells_m5"))
    if bs is None:
        return "udio kupnji u 5 min nepoznat"
    if bs < c["buy_share_min"] - 1e-9:
        return f"kupnje {bs:.0%} transakcija u 5 min (treba {c['buy_share_min']:.0%})"
    vx = vol_x(m.get("vol_m5"), m.get("vol_h1"))
    if vx is None:
        return "nema osnovice volumena (sat prije bez trgovanja)"
    if vx < c["vol_x_min"] - 1e-9:
        return f"volumen 5 min je {vx:.1f}x prosjeka sata (treba {c['vol_x_min']:g}x)"
    vol_h1 = _f(m.get("vol_h1")) or 0
    if liq > 0 and vol_h1 / liq > c["turnover_max"]:
        return f"promet {vol_h1 / liq:.0f}x likvidnosti u satu (granica {c['turnover_max']:g}x): volumen se vrti"
    return None


def buyers_check(b, cfg=None):
    """b: {"now": unique buyers of the last 5 min, "before": unique buyers of the 5 min before (exact) OR "hour_rate":
    the hour's per-5-min average (GeckoTerminal lower bound), "how"}; None when unknown. Returns None or the reason."""
    c = _r(cfg)
    if not b or b.get("now") is None:
        return "jedinstveni kupci nepoznati (nema PumpPortal tradeova ni GeckoTerminal očitanja)"
    now = int(b["now"])
    if now < c["buyers_min_5m"]:
        return f"samo {now} jedinstvenih kupaca u 5 min (treba {c['buyers_min_5m']}+)"
    if b.get("before") is not None:
        ref, x, what = float(b["before"]), c["buyers_x_exact"], "prethodnih 5 min"
    elif b.get("hour_rate") is not None:
        ref, x, what = float(b["hour_rate"]), c["buyers_x_hour"], "prosjeka sata po 5 min"
    else:
        return "nema usporedbe kupaca s prije"
    if now <= ref * x + 1e-9:
        return f"kupci ne rastu: {now} u 5 min, {ref:.1f} {what} (treba više od {x:g}x)"
    return None


def wash_check(w, liq=None, cfg=None):
    """The real anti-wash check. w: {"how": pumpportal | gecko, "wash": score 0-100 or None, "traders_h1",
    "tx_per_trader", "usd_per_trader"}; None = unknown. Returns None or the reason."""
    c = _r(cfg)
    if not w:
        return "lažni volumen se ne može provjeriti (nema jedinstvenih tradera)"
    lb = " (donja granica: kupci + prodavači)" if w.get("how") == "gecko" else ""
    tr = w.get("traders_h1")
    if tr is None:
        return "broj jedinstvenih tradera nepoznat"
    if int(tr) < c["traders_min_h1"]:
        return f"samo {int(tr)} jedinstvenih tradera u satu (treba {c['traders_min_h1']}+): volumen vrti nekoliko novčanika"
    if w.get("wash") is not None and float(w["wash"]) > c["wash_max"]:
        return f"lažni volumen (wash {float(w['wash']):.0f}/100, granica {c['wash_max']:g})"
    tpt = _f(w.get("tx_per_trader"))
    if tpt is None:
        return "transakcije po traderu nepoznate"
    if tpt > c["tx_per_trader_max"]:
        return f"{tpt:.1f} transakcija po traderu{lb} (granica {c['tx_per_trader_max']:g}): botovi vrte volumen"
    upt = _f(w.get("usd_per_trader"))
    cap = max(c["usd_per_trader_min_cap"], c["usd_per_trader_liq"] * (_f(liq) or 0))
    if upt is None:
        return "volumen po traderu nepoznat"
    if upt > cap:
        return f"${upt:,.0f} volumena po traderu u satu{lb} (granica ${cap:,.0f}): nekoliko novčanika vrti volumen"
    return None


def top10_check(top10, cfg=None):
    c = _r(cfg)
    t = _f(top10)
    if t is None:
        return "top 10 holdera nepoznat"
    if t >= c["top10_max"]:
        return f"top 10 novčanika drži {t:.0f} % (treba ispod {c['top10_max']:g} %)"
    return None


def rug_check(rv):
    """rv: ui/kandidati.rug_view's answer (level ok | unknown | oprez | risk | hard)."""
    if not rv:
        return "rug provjera nije uspjela"
    if rv.get("level") == "hard":
        return f"rug: {(rv.get('hard') or ['tvrdi rug'])[0]}"
    if rv.get("level") == "risk":
        return f"rug rizik: {(rv.get('risk') or ['visok rizik'])[0]}"
    return None


def shill_check(handles):
    if handles:
        return f"zove ga mreža shillera: {', '.join(sorted(handles)[:3])}"
    return None


def entry_check(f, cfg=None):
    """Every condition of a feature dict (momentum/job.py): None when a signal, else (key, reason) of the first that
    failed, in the order the job computes them (free first, the paid top 10 lookup last)."""
    for key, fn in CHECKS:
        why = fn(f, cfg)
        if why:
            return key, why
    return None


CHECKS = (("market", cheap_check),
          ("wash", lambda f, cfg: wash_check(f.get("wash_in"), f.get("liq"), cfg)),
          ("buyers", lambda f, cfg: buyers_check(f.get("buyers_in"), cfg)),
          ("rug", lambda f, cfg: rug_check(f.get("rug_in"))),
          ("shill", lambda f, cfg: shill_check(f.get("shill_in"))),
          ("top10", lambda f, cfg: top10_check(f.get("top10"), cfg)))


# ---------- exit --------------------------------------------------------------------------------------------------
def exit_step(st, entry_px, price, now, opened_ts, stale=False, cfg=None):
    """One price tick of an open momentum trade. st: the trade's state, changed in place (tp1, peak). Returns
    (reason, fraction of what is left to sell) or None. Reasons: stop, tp1, trailing, time."""
    c = _r(cfg)
    if not price or price <= 0 or not entry_px:
        return None
    if price <= entry_px * (1 - c["stop"]) + 1e-15:
        return "stop", 1.0
    if stale:
        return None
    st["peak"] = max(st.get("peak") or entry_px, price)
    if not st.get("tp1") and price >= entry_px * (1 + c["tp1"]) - 1e-15:
        st["tp1"] = True
        return "tp1", c["tp1_share"]
    if st.get("tp1") and price <= st["peak"] * (1 - c["trail"]) + 1e-15:
        return "trailing", 1.0
    if now - opened_ts >= c["time_s"]:
        return "time", 1.0
    return None


def outcome(path, entry_px, entry_ts, now=None, cfg=None):
    """The base rate of one signal. path: [(ts, price)] or [(ts, o, h, l, c)] after the signal, oldest first.
    Returns {"first": tp | sl | time | None (still open), "hit": 1 | 0 | None, "resolved_ts", "max_pct", "min_pct"}:
    TP = +15 % reached before -10 % within 45 min; with OHLC a candle that touches both counts as SL (pessimistic)."""
    c = _r(cfg)
    tp_px, sl_px, end = entry_px * (1 + c["tp1"]), entry_px * (1 - c["stop"]), entry_ts + c["time_s"]
    hi = lo = None
    for row in path or []:
        ts = row[0]
        if ts <= entry_ts:
            continue
        if ts > end:
            break
        h, l_ = (row[1], row[1]) if len(row) < 5 else (row[2], row[3])
        if not h or not l_:
            continue
        hi = h if hi is None else max(hi, h)
        lo = l_ if lo is None else min(lo, l_)
        if l_ <= sl_px:
            return _out("sl", 0, ts, hi, lo, entry_px)
        if h >= tp_px:
            return _out("tp", 1, ts, hi, lo, entry_px)
    last = (path or [(None,)])[-1][0] if path else None
    if (now is not None and now >= end) or (last is not None and last >= end):
        return _out("time", 0, end, hi, lo, entry_px)
    return _out(None, None, None, hi, lo, entry_px)


def _out(first, hit, ts, hi, lo, entry_px):
    return {"first": first, "hit": hit, "resolved_ts": int(ts) if ts else None,
            "max_pct": round((hi / entry_px - 1) * 100, 2) if hi else None,
            "min_pct": round((lo / entry_px - 1) * 100, 2) if lo else None}


def simulate(path, entry_px, entry_ts, liq=None, usd=LOT_USD, cfg=None):
    """The exit rules on a path after the signal: (result as a fraction of the stake after the round-trip cost, exit
    reasons) or (None, reasons) while the 45 minutes are not over and the trade is still open. path: [(ts, price)] or
    [(ts, o, h, l, c)]. Fills: TP1 at its level (the live executor sells at the first second at or over it); stop and
    trailing at their level unless the price gapped past it (then at that price: the pessimistic side); time at the
    last price. A candle touching both the stop and TP1 is a stop."""
    c = _r(cfg)
    st, left, got, reasons = {}, 1.0, 0.0, []
    stop_px, tp_px = entry_px * (1 - c["stop"]), entry_px * (1 + c["tp1"])
    end = entry_ts + c["time_s"]
    last_px = entry_px
    for row in path or []:
        ts = row[0]
        if ts <= entry_ts:
            continue
        if len(row) >= 5:
            o, h, l_, cl = row[1], row[2], row[3], row[4]
        else:
            o = h = l_ = cl = row[1]
        if not cl:
            continue
        if ts > end:
            break
        if l_ <= stop_px:
            fill = min(stop_px, o) if o else stop_px
            got += left * fill / entry_px
            reasons.append("stop")
            return _net(got, liq, usd, c), reasons
        low = l_
        if not st.get("tp1") and h >= tp_px:
            st["tp1"], st["peak"] = True, h
            got += c["tp1_share"] * tp_px / entry_px
            left -= c["tp1_share"]
            reasons.append("tp1")
            low = cl   # inside the candle that reached TP1 only its close is known to come after the high
        if st.get("tp1"):
            st["peak"] = max(st["peak"], h)
            trail_px = st["peak"] * (1 - c["trail"])
            if low <= trail_px:
                fill = min(trail_px, o) if o and o < trail_px else trail_px
                got += left * fill / entry_px
                reasons.append("trailing")
                return _net(got, liq, usd, c), reasons
        last_px = cl
        if ts >= end:
            break
    last_ts = path[-1][0] if path else entry_ts
    if last_ts >= end:
        got += left * last_px / entry_px
        reasons.append("time")
        return _net(got, liq, usd, c), reasons
    return None, reasons


def _net(gross_multiple, liq, usd, c):
    """Gross proceeds multiple (exit value / entry price) -> net result fraction after the round trip, as the demo
    account books it (league/store.buy / sell): the buy gets (1 - impact) / (1 + fee) of the tokens, the sale keeps
    (1 - fee) x (1 - impact) of their value."""
    imp = impact(usd, liq)
    bought = (1 - imp) / (1 + FEE_SIDE)
    kept = (1 - FEE_SIDE) * (1 - imp)
    return round(gross_multiple * bought * kept - 1, 5)
