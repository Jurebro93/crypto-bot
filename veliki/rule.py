"""The big-token range rule (pure: walk.py and live.py call the same functions, so a backtest number is the rule the
demo trades). No database, no clock of its own.

Series: 15m bars [(ts, o, h, l, c, v)] (ts = the bar's start), 1h candles the same shape; oldest first.

BTC crash (the owner 15.11.: "NE računajući velike padove Bitcoina, onda je cijelo tržište dolje"), objective and the
same in the backtest and live: at hour t (BTC hourly closes known at t only)
    crash(t) = BTC 4 h change <= CRASH["d4h"] (-3 %)  OR  BTC 24 h change <= CRASH["d24h"] (-5 %)
(market/makro's "pada" by its 4 h drop, plus a day's drop). A crash PERIOD is a run of crash hours; it ends at the first
hour that is not one. While a crash is active no entry is made; unknown BTC (no closes within 3 h) blocks nothing in the
demo and blocks every REAL buy (gate.py).

Zones (at a decision time T, only 1h candles COMPLETED by T): the last `look_d` days (3 or 7), or - FRESH RANGE - when
a crash ended inside that window, only the candles since its end, and then at least FRESH_MIN_H (24 h) of them; a zone
straddling a crash is never used (the owner: "sada se stvara novi range, iskoristi ga"). From those candles:
    support    s_lo = q05 of the lows,   s_hi = q20 of the closes
    resistance r_lo = q80 of the closes, r_hi = q95 of the highs        mid = (s_hi + r_lo) / 2
valid when the range is wide enough to pay (r_lo / s_hi - 1 >= ZONE["width_min"] 4 %), not absurd (<= 60 %), not a
trend (efficiency ratio |c_last - c_first| / sum |dc| <= ZONE["er_max"] 0.35) and not sliding (c_last / c_first - 1 >=
-20 %).

Entry at the CLOSE of a completed 15m bar i (all of):
    the last hour's 15m lows touched the support (min low of bars i-3..i <= s_hi)
    the close is back in / just above the support: s_lo <= c <= s_hi x (1 + near 1 %)
    bounce confirmation: c > the previous close AND c > the bar's open AND the bar's low is no new low (>= the lowest
    low of the 4 bars before it) - a higher low
    the stop sits below the support: entry x (1 - stop_pct) <= s_lo
    the target fits: a net % target's price <= r_hi; "mid" / "top" (mid / r_lo) at least +1 % net above the entry
    no BTC crash active, no position in the token, the cooldown (1 h after an exit) over
filled at the NEXT bar's open x (1 + entry_slip 0.1 %).
Exits on 15m bars (path open-low-high-close for a rising bar, open-high-low-close for a falling one):
    tp     the bar's high >= tp_px -> tp_px x (1 - exit_slip); tp_px = entry x (1 + t) / ((1 - rt) x (1 - exit_slip))
           for a net target t (3 / 5 / 8 %), or the range's mid / r_lo (zone at the entry, frozen)
    stop   the bar's low <= entry x (1 - stop_pct) (3 / 5 / 7 %) -> min(stop, open) x (1 - stop_slip 0.3 %) (a deep
           pool: the server stop fills near its level; walk.py also reports the bar-low fill)
    time   time_h (12 / 24 / 48 h) after the entry -> the close x (1 - exit_slip)
    kraj   end of data -> the last close
Cost (rt, fraction of the stake, never zero): trade/cost.round_trip(size_usd, liq, fee = the pool's fee a side + Jupiter's
route fee) + 2 x the network fee of a swap (0.0005 SOL or the measured median) / size. demo_rt: the same at
trade/cost.fee_side() (the measured fee a side: league/store.FEE or the trade.db calibration).
Result ret = exit / entry x (1 - rt) - 1, pnl = ret x size_usd.
"""
import bisect

SIZES_SOL = (0.1, 0.5, 1.0)
SOL_USD = 150.0
DEFAULT_LIQ = 1_000_000.0
H, M15, D = 3600, 900, 86400
CRASH = {"d4h": -0.03, "d24h": -0.05}
FRESH_MIN_H = 24
ZONE = {"q_slo": 0.05, "q_shi": 0.20, "q_rlo": 0.80, "q_rhi": 0.95, "width_min": 0.04, "width_max": 0.60,
        "er_max": 0.35, "drift_min": -0.20, "min_h_frac": 0.6}
RULE = {"look_d": 3, "tp": 5.0, "stop_pct": 0.05, "time_h": 24, "near": 0.01, "touch_bars": 4, "cooldown_s": 3600,
        "entry_slip": 0.001, "exit_slip": 0.001, "stop_slip": 0.003, "stop_fill": "level", "min_net_mid": 0.01,
        "crash_filter": True, "dca": 0.0}
GRID = {"tp": (3.0, 5.0, 8.0, "mid", "top"), "stop_pct": (0.03, 0.05, 0.07), "time_h": (12, 24, 48), "look_d": (3, 7)}
REASON_HR = {"tp": "cilj", "stop": "stop", "time": "vremenski stop", "kraj": "kraj podataka", "rug": "rug / slom"}


def _f(x, d=None):
    try:
        return float(x) if x is not None else d
    except (TypeError, ValueError):
        return d


# ---------- cost -----------------------------------------------------------------------------------------------------

def fee_side_of(dex=None, url=None):
    """The real account's swap fee a side: the pool's (rangedca/rules.pool_fee: 0.25 % an AMM, 0.3 % PumpSwap) + the
    Jupiter route fee (0.1 %)."""
    from rangedca import rules
    return rules.pool_fee(dex or "raydium", url) + rules.ROUTE_FEE


def tx_sol():
    """(SOL a swap, where from): the measured network fee (rangedca/trade.tx_fee_sol) or 0.0005 SOL."""
    try:
        from rangedca import trade as rtrade
        return rtrade.tx_fee_sol()
    except Exception:  # noqa: BLE001
        from rangedca import rules
        return rules.TX_FEE_SOL, "zadano"


def cost_at(size_sol, liq, sol_usd=SOL_USD, fee_side=None, tx=None, lots=1):
    """{"size_usd", "rt" (real round trip, fraction), "parts"}: trade/cost.round_trip with the token's liquidity at the
    pool + route fee, plus the network fee of every swap (lots buys + 1 sale)."""
    from trade import cost
    su = _f(sol_usd, SOL_USD) or SOL_USD
    usd = float(size_sol) * su * lots
    lq = _f(liq) or DEFAULT_LIQ
    fs = fee_side_of() if fee_side is None else float(fee_side)
    txs = 0.0005 if tx is None else float(tx)
    base = cost.round_trip(usd, lq, fee=fs)
    net = (lots + 1) * txs * su / usd
    return {"size_usd": usd, "rt": base + net,
            "parts": {"fee": 2 * fs, "impact": base - 2 * fs, "net": net, "liq": lq, "tx_sol": txs}}


def demo_rt(size_usd, liq, fee=None):
    """The round trip at the measured fee a side (trade/cost.fee_side) + the impact at the token's liquidity."""
    from trade import cost
    return cost.round_trip(size_usd, _f(liq) or DEFAULT_LIQ, cost.fee_side() if fee is None else fee)


def tp_frac(tp):
    return float(tp) / 100.0


def tp_price(entry, tp, rt, zone, cfg=None):
    """The take-profit price for the target `tp` (net %, or "mid" / "top" of the zone frozen at the entry)."""
    c = {**RULE, **(cfg or {})}
    if tp == "mid":
        return zone["mid"]
    if tp == "top":
        return zone["r_lo"]
    return entry * (1 + tp_frac(tp)) / ((1 - min(max(rt, 0.0), 0.5)) * (1 - c["exit_slip"]))


def net_ret(entry, exit_, rt):
    return exit_ / entry * (1 - rt) - 1


# ---------- BTC crash ------------------------------------------------------------------------------------------------

def crash_hours(btc_h, cfg=None):
    """{hour ts: True/False} from BTC hourly closes [(ts, usd)]: crash(t) = 4 h <= d4h or 24 h <= d24h (closes at or
    before t only). Hours without a close 4 h / 24 h back use what exists (a 24 h change needs >= 20 h of history)."""
    c = {**CRASH, **(cfg or {})}
    pts = sorted((int(t) // H * H, float(p)) for t, p in btc_h if p)
    ts = [t for t, _ in pts]
    out = {}
    for i, (t, p) in enumerate(pts):
        j4 = bisect.bisect_left(ts, t - 4 * H)
        j24 = bisect.bisect_left(ts, t - 24 * H)
        d4 = p / pts[j4][1] - 1 if j4 < i and t - ts[j4] >= 3 * H else None
        d24 = p / pts[j24][1] - 1 if j24 < i and t - ts[j24] >= 20 * H else None
        out[t] = bool((d4 is not None and d4 <= c["d4h"]) or (d24 is not None and d24 <= c["d24h"]))
    return out


class Crash:
    """Crash state at any time from crash_hours(): active(t), last_end(t) (the end of the last crash period that ended
    at or before t, None), known(t) (a BTC hour within 3 h)."""

    def __init__(self, hours):
        self.ts = sorted(hours)
        self.flag = [hours[t] for t in self.ts]
        self.ends = []      # the first non-crash hour after each crash run
        prev = False
        for t, f in zip(self.ts, self.flag):
            if prev and not f:
                self.ends.append(t)
            prev = f
        self.periods = []
        start = None
        for t, f in zip(self.ts, self.flag):
            if f and start is None:
                start = t
            if not f and start is not None:
                self.periods.append((start, t))
                start = None
        if start is not None:
            self.periods.append((start, None))

    def _i(self, t):
        return bisect.bisect_right(self.ts, int(t)) - 1

    def known(self, t):
        i = self._i(t)
        return i >= 0 and t - self.ts[i] <= 3 * H + 59

    def active(self, t):
        i = self._i(t)
        return bool(i >= 0 and self.flag[i] and t - self.ts[i] <= 3 * H + 59)

    def last_end(self, t):
        i = bisect.bisect_right(self.ends, int(t)) - 1
        return self.ends[i] if i >= 0 else None

    def overlaps(self, t0, t1):
        """True when a crash hour falls inside [t0, t1]."""
        i = bisect.bisect_left(self.ts, int(t0) // H * H)
        while i < len(self.ts) and self.ts[i] <= t1:
            if self.flag[i]:
                return True
            i += 1
        return False


NO_CRASH = Crash({})


# ---------- zones ----------------------------------------------------------------------------------------------------

def quantile(xs, q):
    s = sorted(xs)
    if not s:
        return None
    k = (len(s) - 1) * q
    i = int(k)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


def zone_of(h1, cfg=None):
    """The zone of these 1h candles (already the window): {s_lo, s_hi, r_lo, r_hi, mid, width, er, drift, n, ok, why}."""
    z = {**ZONE, **(cfg or {})}
    if len(h1) < 6:
        return {"ok": False, "why": "premalo satnih svijeća", "n": len(h1)}
    lows = [c[3] for c in h1]
    highs = [c[2] for c in h1]
    closes = [c[4] for c in h1]
    s_lo, s_hi = quantile(lows, z["q_slo"]), quantile(closes, z["q_shi"])
    r_lo, r_hi = quantile(closes, z["q_rlo"]), quantile(highs, z["q_rhi"])
    if not s_lo or s_lo <= 0:
        return {"ok": False, "why": "nema cijene", "n": len(h1)}
    s_hi = max(s_hi, s_lo * 1.002)
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    er = abs(closes[-1] - closes[0]) / path if path > 0 else 1.0
    out = {"s_lo": s_lo, "s_hi": s_hi, "r_lo": r_lo, "r_hi": r_hi, "mid": (s_hi + r_lo) / 2, "n": len(h1),
           "width": r_lo / s_hi - 1, "er": er, "drift": closes[-1] / closes[0] - 1, "t0": h1[0][0], "t1": h1[-1][0] + H}
    why = None
    if out["width"] < z["width_min"]:
        why = f"raspon preuzak ({out['width']:.1%})"
    elif out["width"] > z["width_max"]:
        why = f"raspon preširok ({out['width']:.0%})"
    elif er > z["er_max"]:
        why = f"trend, ne raspon (ER {er:.2f})"
    elif out["drift"] < z["drift_min"]:
        why = f"klizi dolje ({out['drift']:.0%})"
    out["ok"], out["why"] = why is None, why
    return out


def window(h1_ts, h1, t, look_d, crash=None, cfg=None):
    """(the 1h candles the zone at time t is built from, fresh: bool, why or None). Only candles completed by t; a crash
    ending inside the window cuts it (fresh range), at least FRESH_MIN_H hours then."""
    z = {**ZONE, **(cfg or {})}
    t0 = t - look_d * D
    fresh = False
    end = (crash or NO_CRASH).last_end(t)
    if end is not None and end > t0:
        t0, fresh = end, True
        if t - end < FRESH_MIN_H * H:
            return [], True, f"novi raspon se tek stvara ({(t - end) / H:.0f} h od kraja pada BTC-a, treba {FRESH_MIN_H} h)"
    i0 = bisect.bisect_left(h1_ts, t0)
    i1 = bisect.bisect_right(h1_ts, t - H)       # a candle starting at ts is complete at ts + 1 h
    w = h1[i0:i1]
    need = FRESH_MIN_H if fresh else max(FRESH_MIN_H, look_d * 24 * z["min_h_frac"])
    if len(w) < need * 0.8:
        return w, fresh, f"premalo satnih svijeća ({len(w)} od {need:.0f})"
    return w, fresh, None


def h1_from_15m(bars, h1=None):
    """1h candles: the given 1h candles, every hour that has 15m bars rebuilt from them (live and backtest agree)."""
    agg = {}
    for b in bars:
        hts = int(b[0]) // H * H
        a = agg.get(hts)
        if a is None:
            agg[hts] = [hts, b[1], b[2], b[3], b[4], b[5] if len(b) > 5 else 0.0]
        else:
            a[2], a[3], a[4] = max(a[2], b[2]), min(a[3], b[3]), b[4]
            a[5] += b[5] if len(b) > 5 else 0.0
    out = {int(c[0]): tuple(c[:6]) for c in (h1 or [])}
    for k, a in agg.items():
        out[k] = tuple(a)
    return [out[k] for k in sorted(out)]


class Zones:
    """Zone at any 15m decision time of one token, cached per (hour, look_d)."""

    def __init__(self, h1, crash=None, cfg=None):
        self.h1 = h1
        self.ts = [c[0] for c in h1]
        self.crash = crash or NO_CRASH
        self.cfg = cfg
        self._c = {}

    def at(self, t, look_d):
        key = (int(t) // H, look_d)
        hit = self._c.get(key)
        if hit is None:
            w, fresh, why = window(self.ts, self.h1, int(t) // H * H, look_d, self.crash, self.cfg)
            if why:
                hit = {"ok": False, "why": why, "fresh": fresh, "n": len(w)}
            else:
                hit = zone_of(w, self.cfg)
                hit["fresh"] = fresh
            self._c[key] = hit
        return hit


# ---------- entry / exit ---------------------------------------------------------------------------------------------

def base_signal(bars, i, zone, cfg=None, crash=None):
    """The config-free part of the entry at the close of completed 15m bar i: None or why (Croatian)."""
    c = {**RULE, **(cfg or {})}
    if not zone or not zone.get("ok"):
        return (zone or {}).get("why") or "nema zone"
    if i < c["touch_bars"]:
        return "premalo 15m svijeća"
    t_dec = bars[i][0] + M15
    if c["crash_filter"] and crash is not None and crash.active(t_dec):
        return "BTC pada (4 h <= -3 % ili 24 h <= -5 %): bez ulaza"
    b, p = bars[i], bars[i - 1]
    px = b[4]
    if px < zone["s_lo"]:
        return "ispod podrške (probija dolje)"
    if px > zone["s_hi"] * (1 + c["near"]):
        return "nije na podršci"
    if min(x[3] for x in bars[i - c["touch_bars"] + 1:i + 1]) > zone["s_hi"]:
        return "zadnji sat nije dotaknuo podršku"
    if not (px > p[4] and px > b[1]):
        return "nema odbijanja (zatvaranje nije iznad prethodnog i otvaranja)"
    if b[3] < min(x[3] for x in bars[max(0, i - 4):i]):
        return "novo dno (nema višeg dna)"
    return None


def config_refusal(px, zone, rt, cfg=None):
    """The config's part of the entry at a signal close px: the stop below the support, the target inside the range."""
    c = {**RULE, **(cfg or {})}
    e = px * (1 + c["entry_slip"])
    if e * (1 - c["stop_pct"]) > zone["s_lo"] * 0.999:
        return f"stop {c['stop_pct']:.0%} ne bi bio ispod podrške"
    tp = tp_price(e, c["tp"], rt, zone, c)
    if c["tp"] in ("mid", "top"):
        if net_ret(e, tp * (1 - c["exit_slip"]), rt) < c["min_net_mid"]:
            return "sredina / vrh raspona preblizu nakon troška"
    elif tp > zone["r_hi"]:
        return f"cilj +{c['tp']:g} % neto iznad vrha raspona"
    return None


def signal(bars, i, zone, rt, cfg=None, crash=None):
    """None when the close of completed 15m bar i is an entry under this zone and config, else why (Croatian)."""
    why = base_signal(bars, i, zone, cfg, crash)
    return why if why else config_refusal(bars[i][4], zone, rt, cfg)


def _path(b):
    o, h, l, c = b[1], b[2], b[3], b[4]
    return ((o, "o"), (l, "l"), (h, "h"), (c, "c")) if c >= o else ((o, "o"), (h, "h"), (l, "l"), (c, "c"))


def exit_on_bar(pos, b, cfg=None):
    """(reason, fill) when the open position exits inside bar b, else None. pos {entry, ts, tp_px, stop_px}."""
    c = {**RULE, **(cfg or {})}
    for px, kind in _path(b):
        if kind in ("o", "l") and px <= pos["stop_px"]:
            base = b[3] if c["stop_fill"] == "low" else min(pos["stop_px"], b[1])
            return "stop", base * (1 - c["stop_slip"])
        if kind in ("o", "h") and px >= pos["tp_px"]:
            return "tp", (max(pos["tp_px"], b[1]) if kind == "o" else pos["tp_px"]) * (1 - c["exit_slip"])
    if b[0] + M15 - pos["ts"] >= c["time_h"] * H:
        return "time", b[4] * (1 - c["exit_slip"])
    return None


def candidates(bars, zones, look_d, crash=None, cfg=None):
    """[(i, zone)] of the bars whose close passes the config-free part of the entry (zone valid, touch, near support,
    bounce, no crash); simulate() adds the config's stop / target checks. Computed once per look_d."""
    c = {**RULE, **(cfg or {}), "look_d": look_d}
    out = []
    for i in range(c["touch_bars"], len(bars) - 1):
        z = zones.at(bars[i][0] + M15, look_d)
        if not z.get("ok"):
            continue
        if base_signal(bars, i, z, c, crash) is None:
            out.append((i, z))
    return out


def simulate(bars, cands, size_usd, rt, cfg=None, drt=None, t0=None, t1=None, crash=None):
    """The trades of one token: entries from cands (candidates()) that pass this config, one position at a time, the
    cooldown after an exit, filled at the next bar's open (no look-ahead). [{ts, out_ts, entry, exit, reason, ret, pnl,
    ret_demo, hours, zone_fresh, crash_overlap}]."""
    c = {**RULE, **(cfg or {})}
    drt = rt if drt is None else drt
    out = []
    free_at = -1
    n = len(bars)
    for i, z in cands:
        ts_dec = bars[i][0] + M15
        if i + 1 >= n or i < free_at or ts_dec < (t0 or 0) or (t1 is not None and ts_dec >= t1):
            continue
        if config_refusal(bars[i][4], z, rt, c):
            continue
        b = bars[i + 1]
        e = b[1] * (1 + c["entry_slip"])
        pos = {"entry": e, "ts": b[0], "tp_px": tp_price(e, c["tp"], rt, z, c), "stop_px": e * (1 - c["stop_pct"])}
        if c["tp"] in ("mid", "top") and pos["tp_px"] <= e:
            continue
        lots = [e]
        dca_px = e * (1 - c["dca"]) if c.get("dca") else None
        hit, j = None, i + 1
        while j < n:
            bj = bars[j]
            if dca_px is not None and len(lots) == 1 and bj[3] <= dca_px and bj[3] > pos["stop_px"]:
                lots.append(dca_px)    # one more lot at -dca: the average entry and the net target move with it
                avg = 2 / (1 / lots[0] + 1 / lots[1])
                pos["entry"] = avg
                if c["tp"] not in ("mid", "top"):
                    pos["tp_px"] = tp_price(avg, c["tp"], rt, z, c)
            hit = exit_on_bar(pos, bj, c)
            if hit:
                break
            j += 1
        if not hit:
            j = n - 1
            hit = ("kraj", bars[-1][4] * (1 - c["exit_slip"]))
        reason, fill = hit
        k = len(lots)
        r = net_ret(pos["entry"], fill, rt)
        rd = net_ret(pos["entry"], fill, drt)
        out_ts = bars[j][0] + M15
        out.append({"ts": b[0], "out_ts": out_ts, "entry": pos["entry"], "exit": fill, "reason": reason, "ret": r,
                    "pnl": r * size_usd * k, "ret_demo": rd, "lots": k, "hours": round((out_ts - b[0]) / H, 2),
                    "zone_fresh": bool(z.get("fresh")),
                    "crash_overlap": bool(crash is not None and crash.overlaps(b[0], out_ts))})
        free_at = j + int(c["cooldown_s"] // M15)
    return out


def summary(trades, size_usd=None):
    n = len(trades)
    if not n:
        return {"n": 0, "hit": None, "ev_pct": None, "ev_usd": None, "pnl_usd": 0.0, "worst_pct": None, "reasons": {}}
    w = sum(1 for x in trades if x["ret"] > 0)
    rs = {}
    for x in trades:
        rs[x["reason"]] = rs.get(x["reason"], 0) + 1
    return {"n": n, "hit": round(w / n, 3), "ev_pct": round(sum(x["ret"] for x in trades) / n * 100, 3),
            "ev_usd": round(sum(x["pnl"] for x in trades) / n, 4), "pnl_usd": round(sum(x["pnl"] for x in trades), 3),
            "worst_pct": round(min(x["ret"] for x in trades) * 100, 2),
            "ev_demo_pct": round(sum(x["ret_demo"] for x in trades) / n * 100, 3), "reasons": rs}


def configs(grid=None):
    g = {**GRID, **(grid or {})}
    return [{"tp": tp, "stop_pct": s, "time_h": th, "look_d": lk}
            for lk in g["look_d"] for tp in g["tp"] for s in g["stop_pct"] for th in g["time_h"]]


def cfg_key(c):
    tp = c["tp"] if isinstance(c["tp"], str) else f"{c['tp']:g}%"
    return f"tp{tp}/sl{c['stop_pct'] * 100:g}/{c['time_h']}h/{c['look_d']}d" + (f"/dca{c['dca'] * 100:g}" if c.get("dca") else "")
