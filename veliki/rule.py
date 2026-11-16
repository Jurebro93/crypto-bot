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
DEFAULT_LIQ = 500_000.0
H, M15, D = 3600, 900, 86400
CRASH = {"d4h": -0.03, "d24h": -0.05}
FRESH_MIN_H = 24
BREAK = 0.03          # a 1h close this far under the support breaks the range: the zone restarts after it
ZONE = {"q_slo": 0.05, "q_shi": 0.20, "q_rlo": 0.80, "q_rhi": 0.95, "width_min": 0.08, "width_max": 1.20,
        "er_max": 0.40, "drift_min": -0.35, "min_h_frac": 0.6}
# 15.11. popodne (owner: "drži duže ... stop -20 % ... TP 8 / 15 / 25 % neto + trailing ... DCA -10 %"; the critic: the
# range from past prices only, a breakout invalidates it, a stop by the range's invalidation + volatility capped at
# -20 %, never widened; DCA off by default): 1h bars, the zone of the last 7 / 14 days, target +8 / 15 / 25 % net with or
# without a 5 % trailing after it, time stop 3 / 7 days, stop -20 % (the owner's) - -10 / -15 % and the ATR stop reported
RULE = {"bar_s": 3600, "look_d": 7, "tp": 15.0, "trail": 0.0, "stop": "pct20", "stop_pct": 0.20, "time_h": 168,
        "near": 0.02, "touch_bars": 3, "cooldown_s": 6 * 3600, "entry_slip": 0.002, "exit_slip": 0.002,
        "stop_slip": 0.005, "stop_fill": "level", "min_net_mid": 0.03, "crash_filter": True, "dca": 0.0,
        "btc_up": False, "atr_k": 2.0, "atr_n": 14, "stop_cap": 0.20, "btc_mode": "dno", "inflow_x": 1.0,
        "half": 0.5, "tx_frac": 0.0, "dca_mode": "pct", "dca_atr_k": 3.0, "dca_min": 0.05, "dca_cats": ("A", "B"),
        "reasoned": False, "macro_filter": False, "vol_collapse": 0.30, "cut_pct": 0.10, "protect_min": 0.01,
        "be_at": 0.0}
# 15.11. navečer (vlasnik: "Trade ne treba biti vremenski ograničen, nego sa stop loss ili take profit ... ako bude 5 %
# profitu, stavi stop loss na ulaz, a onda take profit staviš na 10-15 % ... ako odmah nakon ulaza krene u mali loss,
# onda čekaš"): OWNER_EXIT = the live exit of both midcap rules: no time stop, the stop moves to break-even once the
# position is be_at (+5 %) NET above it, the target sells half (the rest: break-even + trailing); the reasoned exit
# "los" fires only on NEW danger (liquidity pulled, holders selling, the team / insiders block, a deposit to sell),
# never on facts known at the entry (concentration, dev share, authorities: veliki/prioritet.static_risk refuses those
# before the buy)
OWNER_EXIT = {"time_h": None, "be_at": 0.05}
# 16.11. (vlasnik: "više tradeova, zatvaraju se gdje postoji dobar razlog ... uključi DCA"; the critic: "TP +8 % pa
# trailing 5 %" could leave the WHOLE position at ~+2.6 % = 1.08 x 0.95):
#   half       with a trailing (trail > 0) the target sells `half` (50 %) of the position (locked), the rest's stop moves
#              to break-even (be_px: the entry + the round trip's cost, so the rest never closes below 0 % net) and the
#              rest trails `trail` under its highest price since; the time stop closes the rest. half 0 = the old
#              whole-position trailing (walk.py reports it as "cijeli_trailing"). tx_frac: one swap's network fee as a
#              share of one lot (the extra sale costs it once).
#   DCA        one lot more per position at most (dca > 0 or dca_mode "zona" / "atr"), see dca_level / dca_refusal;
#              the average entry moves the target and the break-even, the stop stays the FIRST entry's (never wider).
#   reasoned   the reasoned exits (reasoned_exit): BTC free fall (protect a profit / cut below -cut_pct), the macro
#              regime risk_off, the token's volume collapsing (24 h < vol_collapse x its 7-day average), a bad dip
#              reason (live: veliki/prioritet "los", holderi deposit-to-sell); off in the plain grid, a walk variant.
#   macro_filter  no new entry while veliki/makro says risk_off (walk variant; live always).
# btc_mode (the owner's correction 15.11. popodne): "dno" = the live rule: no entry in a BTC free fall, the range rule
# when normal, and while the bottom forms ALSO a bounce candle with token inflow (the hour's volume above its 6 h average)
# anywhere under the range's middle; "zabrana" = no entry at all while a crash (crash_hours) lasts; "bez" = no BTC rule
BTC_MODES = ("bez", "zabrana", "dno")
GRID = {"tp": (8.0, 15.0, 25.0), "trail": (0.0, 0.05, 0.10), "time_h": (72, 168), "look_d": (7, 14)}
STOPS = {"pct10": 0.10, "pct15": 0.15, "pct20": 0.20, "atr": None}
REASON_HR = {"tp": "cilj", "trail": "trailing nakon cilja", "stop": "stop", "time": "vremenski stop",
             "kraj": "kraj podataka", "rug": "rug / slom", "be": "break-even nakon prodane polovice",
             "btc_zastita": "BTC slobodan pad: zaštita profita", "btc_rez": "BTC slobodan pad: rez ispod -10 %",
             "makro_zastita": "makro risk-off: zaštita profita", "makro_rez": "makro risk-off: rez ispod -10 %",
             "volumen": "volumen se urušio (24 h < 30 % prosjeka 7 d)", "los": "razlog pada postao loš",
             "nestalo": "nestalo", "likvidnost": "likvidnost pala 50 %+ u satu (LP povučen?)"}
DCA_HR = {"pct": "cijena {d:.0%} ispod prvog ulaza", "zona": "dno zone (podrška)", "atr": "{k:g} x ATR ispod ulaza"}


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

    def __init__(self, hours, closes=None):
        self.px = sorted((int(t) // H * H, float(p)) for t, p in (closes or []) if p)
        self.pts = [t for t, _ in self.px]
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

    def regime(self, t, vol=None):
        """(state, why) of BTC at t (the owner 15.11. popodne: "ako je BTC pao i ima znakova da je našao dno i volumen
        raste ... to je signal za POČETI kupovati"), from the hourly closes known at t:
          slobodan_pad      BTC's lowest close of the last 24 h is at most 2 h old AND 4 h <= -3 %: no new entries
          dno_se_potvrduje  after a drop (the 72 h high -> the low since <= -5 %, or 7 d <= -10 %), no new low for
                            >= 6 h, 4 h > 0, and (when known) BTC's 24 h volume above its own 24 h average
          normalno          the rest
        vol: {hour ts: BTC 24 h volume} or None (unknown: that condition is left out and said)."""
        key = (int(t) // H, bool(vol))
        hit = self._reg.get(key) if hasattr(self, "_reg") else None
        if hit is not None:
            return hit
        if not hasattr(self, "_reg"):
            self._reg = {}
        i = bisect.bisect_right(self.pts, int(t)) - 1
        if i < 0 or t - self.pts[i] > 3 * H + 59:
            self._reg[key] = ("normalno", "BTC nepoznat")
            return self._reg[key]
        j24 = bisect.bisect_left(self.pts, self.pts[i] - 24 * H)
        j72 = bisect.bisect_left(self.pts, self.pts[i] - 72 * H)
        j7d = bisect.bisect_left(self.pts, self.pts[i] - 7 * D)
        last24 = self.px[j24:i + 1]
        lo24_t = min(last24, key=lambda x: x[1])[0]
        d4 = self.chg(t, 4)
        if d4 is not None and d4 <= CRASH["d4h"] and self.pts[i] - lo24_t <= 2 * H:
            self._reg[key] = ("slobodan_pad", f"novo dno BTC-a prije {(self.pts[i] - lo24_t) / H:.0f} h, 4 h {d4:+.1%}")
            return self._reg[key]
        w72 = self.px[j72:i + 1]
        hi_k = max(range(len(w72)), key=lambda k: w72[k][1])
        after = w72[hi_k:]
        low = min(after, key=lambda x: x[1])
        drop = low[1] / w72[hi_k][1] - 1
        d7 = self.px[i][1] / self.px[j7d][1] - 1 if j7d < i else None
        if (drop <= -0.05 or (d7 is not None and d7 <= -0.10)) and self.pts[i] - low[0] >= 6 * H \
                and d4 is not None and d4 > 0:
            why = f"pad {drop:+.1%} (7 d {d7:+.1%})" if d7 is not None else f"pad {drop:+.1%}"
            why += f", bez novog dna {(self.pts[i] - low[0]) / H:.0f} h, 4 h {d4:+.1%}"
            if vol:
                vs = [vol[h] for h in range(self.pts[i] - 24 * H, self.pts[i] + 1, H) if h in vol]
                v = vol.get(self.pts[i])
                if v is None or len(vs) < 6 or v <= sum(vs) / len(vs):
                    self._reg[key] = ("normalno", why + ", ali volumen BTC-a nije iznad prosjeka 24 h")
                    return self._reg[key]
                why += ", volumen BTC-a iznad prosjeka 24 h"
            else:
                why += " (volumen BTC-a nepoznat)"
            self._reg[key] = ("dno_se_potvrduje", why)
            return self._reg[key]
        self._reg[key] = ("normalno", f"4 h {d4:+.1%}" if d4 is not None else "normalno")
        return self._reg[key]

    def chg(self, t, hours=4):
        """BTC's change over the last `hours` known at t (None without the closes)."""
        i = bisect.bisect_right(self.pts, int(t)) - 1
        j = bisect.bisect_left(self.pts, int(t) - hours * H)
        if i < 0 or j >= i:
            return None
        return self.px[i][1] / self.px[j][1] - 1

    def overlaps(self, t0, t1):
        """True when a crash hour falls inside [t0, t1]."""
        i = bisect.bisect_left(self.ts, int(t0) // H * H)
        while i < len(self.ts) and self.ts[i] <= t1:
            if self.flag[i]:
                return True
            i += 1
        return False


NO_CRASH = Crash({})


def crash_of(btc_h, cfg=None):
    return Crash(crash_hours(btc_h, cfg), btc_h)


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


def zone_at(h1_ts, h1, t, look_d, crash=None, cfg=None):
    """The zone at t from PAST candles only; a range broken downwards inside the window (a 1h close BREAK under its
    support) is not re-used: the window restarts after the last such close (>= FRESH_MIN_H of candles after it)."""
    w, fresh, why = window(h1_ts, h1, t, look_d, crash, cfg)
    if why:
        return {"ok": False, "why": why, "fresh": fresh, "n": len(w)}
    for _ in range(3):
        zo = zone_of(w, cfg)
        if not zo.get("s_lo"):
            break
        lim = zo["s_lo"] * (1 - BREAK)
        k = max((i for i, c in enumerate(w) if c[4] < lim), default=None)
        if k is None:
            break
        rest = w[k + 1:]
        if len(rest) < FRESH_MIN_H * 0.8:
            return {"ok": False, "why": "raspon probijen dolje: čeka se novi", "fresh": fresh, "n": len(rest),
                    "broken": True}
        w, fresh = rest, True
    zo = zone_of(w, cfg)
    zo["fresh"] = fresh
    zo["atr"] = atr(w, (cfg or {}).get("atr_n", RULE["atr_n"]))
    return zo


def atr(h1, n=14):
    """The mean true range of the last n candles (price units), None with fewer than 3."""
    if len(h1) < 3:
        return None
    trs = [max(c[2] - c[3], abs(c[2] - p[4]), abs(c[3] - p[4])) for p, c in zip(h1, h1[1:])][-n:]
    return sum(trs) / len(trs) if trs else None


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
            hit = zone_at(self.ts, self.h1, int(t) // H * H, look_d, self.crash, self.cfg)
            self._c[key] = hit
        return hit


# ---------- entry / exit ---------------------------------------------------------------------------------------------

def base_signal(bars, i, zone, cfg=None, crash=None):
    """The config-free part of the entry at the close of completed bar i: None or why (Croatian)."""
    c = {**RULE, **(cfg or {})}
    if i < c["touch_bars"]:
        return "premalo svijeća"
    t_dec = bars[i][0] + c["bar_s"]
    mode = c.get("btc_mode") if c["crash_filter"] else "bez"
    b, p = bars[i], bars[i - 1]
    px = b[4]
    if crash is not None and mode == "zabrana" and crash.active(t_dec):
        return "BTC pada (4 h <= -3 % ili 24 h <= -5 %): zabrana novih ulaza"
    if crash is not None and mode == "dno":
        st, why = crash.regime(t_dec)
        if st == "slobodan_pad":
            return f"BTC slobodan pad ({why}): bez novih ulaza"
        if st == "dno_se_potvrduje" and inflow(bars, i, c) and px > p[4] and px > b[1] \
                and (not zone or not zone.get("ok") or px <= zone["mid"]):
            return None    # the bottom forms + money flows into the token: buy the bounce (under the range's middle)
    if not zone or not zone.get("ok"):
        return (zone or {}).get("why") or "nema zone"
    if px < zone["s_lo"]:
        return "ispod podrške (probija dolje)"
    if px > zone["s_hi"] * (1 + c["near"]):
        return "nije na podršci"
    if min(x[3] for x in bars[i - c["touch_bars"] + 1:i + 1]) > zone["s_hi"]:
        return "zadnje svijeće nisu dotaknule podršku"
    if not (px > p[4] and px > b[1]):
        return "nema odbijanja (zatvaranje nije iznad prethodnog i otvaranja)"
    if b[3] < min(x[3] for x in bars[max(0, i - 4):i]):
        return "novo dno (nema višeg dna)"
    return None


def inflow(bars, i, cfg=None):
    """Money flowing into the token: bar i's volume above inflow_x x the mean of the 6 bars before it (the backtest's
    proxy; live adds DexScreener's buy share, veliki/live.inflow_live)."""
    c = {**RULE, **(cfg or {})}
    if i < 6 or len(bars[i]) < 6:
        return False
    prev = [x[5] or 0.0 for x in bars[i - 6:i]]
    m = sum(prev) / 6
    return bool(m > 0 and (bars[i][5] or 0.0) > c["inflow_x"] * m)


def stop_px(entry, zone, cfg=None):
    """The stop price fixed at the entry (never widened): "pctNN" = entry x (1 - NN %); "atr" = under the support by
    atr_k x ATR, at most stop_cap (20 %) under the entry."""
    c = {**RULE, **(cfg or {})}
    mode = c.get("stop") or "pct20"
    if mode == "atr" and zone and zone.get("atr") and zone.get("s_lo"):
        return max(entry * (1 - c["stop_cap"]), zone["s_lo"] - c["atr_k"] * zone["atr"])
    p = STOPS.get(mode) or c["stop_pct"]
    return entry * (1 - p)


def config_refusal(px, zone, rt, cfg=None, crash=None, t=None):
    """The config's part of the entry at a signal close px: the stop below the support, the target inside reach."""
    c = {**RULE, **(cfg or {})}
    e = px * (1 + c["entry_slip"])
    if zone and zone.get("ok") and stop_px(e, zone, c) > zone["s_lo"] * 0.999:
        return "stop ne bi bio ispod podrške"
    if c.get("btc_up") and crash is not None and t is not None:
        ch = crash.chg(t, 4)
        if ch is None or ch <= 0:
            return "BTC se još nije okrenuo gore (4 h)"
    if c["tp"] in ("mid", "top") and not (zone and zone.get("ok")):
        return "cilj sredina / vrh traži raspon"
    tp = tp_price(e, c["tp"], rt, zone, c)
    if c["tp"] in ("mid", "top"):
        if net_ret(e, tp * (1 - c["exit_slip"]), rt) < c["min_net_mid"]:
            return "sredina / vrh raspona preblizu nakon troška"
    return None   # a net % target may lie above the range (the owner: hold longer for +8 / 15 / 25 %)


def signal(bars, i, zone, rt, cfg=None, crash=None):
    """None when the close of completed bar i is an entry under this zone and config, else why (Croatian)."""
    c = {**RULE, **(cfg or {})}
    why = base_signal(bars, i, zone, c, crash)
    return why if why else config_refusal(bars[i][4], zone, rt, c, crash, bars[i][0] + c["bar_s"])


def _path(b):
    o, h, l, c = b[1], b[2], b[3], b[4]
    return ((o, "o"), (l, "l"), (h, "h"), (c, "c")) if c >= o else ((o, "o"), (h, "h"), (l, "l"), (c, "c"))


def be_price(entry, rt, cfg=None):
    """The break-even price of a position bought at `entry` (average): the rest sold there nets 0 % after the round
    trip's cost and the exit slippage."""
    c = {**RULE, **(cfg or {})}
    return entry / ((1 - min(max(rt, 0.0), 0.5)) * (1 - c["exit_slip"]))


def half_of(cfg=None):
    """The share sold at the target: cfg half when a trailing follows the target, else 0 (sell all at the target)."""
    c = {**RULE, **(cfg or {})}
    return float(c.get("half") or 0.0) if c.get("trail") else 0.0


def on_price(pos, px, kind, b_open, cfg=None):
    """One price point of the position's path (kind "o" open, "l" low, "h" high, "c" close, "t" a live tick):
    None, or (reason, fill) when the (rest of the) position exits here. The first touch of the target with a
    trailing sells `half` (pos["half_px"], the stop moves to break-even pos["be_px"]); the same function decides on the
    backtest's bar path and on the live ticks (veliki/live.exit_why)."""
    c = {**RULE, **(cfg or {})}
    tr = c.get("trail") or 0.0
    h = half_of(c)
    down = kind in ("o", "l", "t", "c")
    up = kind in ("o", "h", "t", "c")
    lvl = None
    if tr and pos.get("peak"):
        lvl = max(pos["peak"] * (1 - tr), pos["be_px"] if pos.get("half_px") and pos.get("be_px") else
                  pos["tp_px"] * (1 - tr))
    if kind == "l" and lvl is not None and lvl > pos["stop_px"] and px <= lvl:
        # a bar's continuous fall reaches the (higher) trailing level before the stop / break-even
        return "trail", min(lvl, b_open) * (1 - c["exit_slip"])
    if down and px <= pos["stop_px"]:
        base = px if kind == "t" else (b_open if kind == "o" else min(pos["stop_px"], b_open))
        if c["stop_fill"] == "low" and kind == "l":
            base = px
        return ("be" if (pos.get("half_px") or pos.get("be_armed")) and pos["stop_px"] >= pos.get("be_px", 0) * 0.999
                else "stop"), base * (1 - c["stop_slip"])
    if lvl is not None and down and px <= lvl:
        return "trail", (px if kind in ("t", "c") else min(lvl, b_open)) * (1 - c["exit_slip"])
    ba = c.get("be_at") or 0.0
    if ba and up and not pos.get("half_px") and pos.get("be_px") and px >= pos["be_px"] * (1 + ba) \
            and pos["stop_px"] < pos["be_px"]:
        pos["stop_px"] = pos["be_px"]   # +be_at net reached: the stop to break-even (the owner's rule)
        pos["be_armed"] = True
    if up and px >= pos["tp_px"]:
        # 15.11. navečer (vlasnik): the whole profit at the target unless the whole market rises (live row_cfg sets
        # full_tp from veliki/makro.bull); a rest already running after its half keeps trailing
        if not tr or (c.get("full_tp") and not pos.get("half_px")):
            return "tp", (px if kind in ("o", "t") else pos["tp_px"]) * (1 - c["exit_slip"])
        if h and not pos.get("half_px"):
            pos["half_px"] = (px if kind in ("o", "t") else pos["tp_px"]) * (1 - c["exit_slip"])
            pos["half"] = h
            be = pos.get("be_px") or pos["entry"]
            pos["be_px"] = be
            pos["stop_px"] = max(pos["stop_px"], be)
        pos["peak"] = max(pos.get("peak") or 0.0, px)
    if tr and pos.get("peak") and kind in ("h", "t", "c"):
        pos["peak"] = max(pos["peak"], px)
    return None


def exit_on_bar(pos, b, cfg=None):
    """(reason, fill) when the open position (or its rest after the half) exits inside bar b, else None. pos {entry,
    ts, tp_px, stop_px, be_px?, peak?, half_px?}. With trail > 0 the target sells half (cfg half, 50 %), moves the
    rest's stop to break-even and arms a trailing stop trail under the highest high since (half 0: the old whole
    position trailing, never under the target's own level x (1 - trail))."""
    c = {**RULE, **(cfg or {})}
    path = _path(b)
    worst = c.get("same_bar") == "stop"
    s0 = pos["stop_px"]
    if worst and b[3] <= s0:
        # veliki/replay.py's conservative reading (off by default): a bar whose low reaches the stop it started with is
        # walked open-low-high-close, so a bar that touches both the stop and the target (or the break-even level) is
        # a stop; only an open already at the target still sells there
        path = ((b[1], "o"), (b[3], "l"), (b[2], "h"), (b[4], "c"))
    for px, kind in path:
        hit = on_price(pos, px, kind, b[1], c)
        if hit:
            if worst and hit[0] in ("be", "stop") and pos["stop_px"] > s0 and kind in ("l", "c"):
                # the stop moved up INSIDE this bar (break-even armed at its high) and the price then fell through it:
                # filled at that level, not at the bar's open under it (min(stop, open) is for a stop set before the bar)
                hit = (hit[0], pos["stop_px"] * (1 - c["stop_slip"]))
            return hit
    if c.get("time_h") and b[0] + c["bar_s"] - pos["ts"] >= c["time_h"] * H:
        return ("trail" if pos.get("peak") else "time"), b[4] * (1 - c["exit_slip"])
    return None


def blend_ret(pos, fill, rt, cfg=None, lots=1):
    """The position's net return: the half sold at the target (pos half_px, share pos half) and the rest at fill, both
    at the round trip rt; the extra sale costs one more network fee (tx_frac of a lot / lots)."""
    c = {**RULE, **(cfg or {})}
    h = pos.get("half") or 0.0 if pos.get("half_px") else 0.0
    r = (1 - h) * net_ret(pos["entry"], fill, rt)
    if h:
        r += h * net_ret(pos["entry"], pos["half_px"], rt) - (c.get("tx_frac") or 0.0) / max(1, lots)
    return r


# ---------- DCA (16.11., vlasnik: "uključi DCA: tokeni poput Uselessa su se puno puta oporavili na prvi znak oporavka
# Bitcoina") -------------------------------------------------------------------------------------------------------

def dca_level(entry, zone=None, cfg=None):
    """The price of the one DCA lot under the FIRST entry: "pct" entry x (1 - dca) (-10 %); "zona" just under the
    zone's support low (s_lo x 0.98); "atr" entry - dca_atr_k x the zone's 1h ATR; the last two at least dca_min (5 %)
    under the entry. None: no DCA."""
    c = {**RULE, **(cfg or {})}
    m = c.get("dca_mode") or "pct"
    deep = entry * (1 - (c.get("dca_min") or 0.05))
    if m == "zona" and zone and zone.get("s_lo"):
        return min(deep, zone["s_lo"] * 0.98)
    if m == "atr" and zone and zone.get("atr"):
        return min(deep, entry - c["dca_atr_k"] * zone["atr"])
    if not c.get("dca"):
        return None
    return entry * (1 - c["dca"])


def bounce_ok(m):
    """(ok, why) of a token's history after BTC bounces (veliki/metrics: btc_up_n days of BTC +3 %, btc_up_hit the
    share with the token higher 72 h later, btc_up_72h the mean): at least 3 such days and a hit rate >= 50 % or a
    positive mean."""
    m = m or {}
    n = m.get("btc_up_n") or 0
    if n < 3:
        return False, f"premalo dana BTC +3 % u povijesti ({n})"
    hit, mean = m.get("btc_up_hit"), m.get("btc_up_72h")
    if (hit is not None and hit >= 0.5) or (mean is not None and mean > 0):
        return True, f"nakon BTC +3 % dana gore {hit if hit is not None else '?'} ({n} dana, prosjek 72 h {mean} %)"
    return False, f"nakon BTC +3 % dana se ne oporavlja (pogodak {hit}, prosjek 72 h {mean} %)"


def dca_refusal(ctx, cfg=None):
    """None when the one DCA lot may be bought now, else why (Croatian). ctx: btc_state (rule.Crash.regime), macro
    (veliki/makro: risk_on / neutral / risk_off / None unknown), cat (A / B / C), metrics (the token's metrics row:
    bounce_ok), dip_kind (veliki/prioritet: los / trzisni / benigni / nejasno / None), bad (a known bad reason: LP
    pulled, dev selling, rug flag, deposit to sell), vol_ratio (24 h / 7-day average volume), lots (already bought),
    room (the caps' refusal or None). The same function in the backtest (what the candles can show) and live."""
    c = {**RULE, **(cfg or {})}
    if (ctx.get("lots") or 1) >= 2:
        return "DCA već iskorišten (jedan po poziciji)"
    if ctx.get("half_done"):
        return "polovica već prodana na cilju"
    if ctx.get("btc_state") == "slobodan_pad":
        return "BTC u slobodnom padu"
    if ctx.get("macro") == "risk_off":
        return "makro režim risk-off"
    if ctx.get("bad"):
        return f"loš razlog pada ({ctx['bad']})"
    if ctx.get("dip_kind") == "los":
        return "razlog pada loš (prioritet)"
    if ctx.get("cat") not in tuple(c.get("dca_cats") or ("A", "B")):
        return f"kategorija {ctx.get('cat') or '?'} (DCA samo A / B)"
    ok, why = bounce_ok(ctx.get("metrics"))
    if not ok:
        return why
    vr = ctx.get("vol_ratio")
    if vr is not None and vr < c["vol_collapse"]:
        return f"volumen se urušio ({vr:.0%} prosjeka 7 d)"
    if ctx.get("room"):
        return ctx["room"]
    return None


def dca_why(ctx, cfg=None):
    """The DCA's reason for the log (Croatian)."""
    c = {**RULE, **(cfg or {})}
    m = c.get("dca_mode") or "pct"
    parts = [DCA_HR.get(m, m).format(d=c.get("dca") or 0.10, k=c.get("dca_atr_k") or 3)]
    parts.append(f"BTC {ctx.get('btc_state') or '?'}")
    parts.append(f"makro {ctx.get('macro') or 'nepoznat'}")
    parts.append(f"kategorija {ctx.get('cat')}")
    if ctx.get("dip_kind"):
        parts.append(f"pad {ctx['dip_kind']}")
    parts.append(bounce_ok(ctx.get("metrics"))[1])
    return ", ".join(parts)


def reasoned_exit(pos, px, rt, ctx, cfg=None):
    """(reason, new stop or None) of a reasoned exit at price px (16.11., vlasnik: "zatvaraju se tradeovi gdje postoji
    dobar razlog"), else (None, None). ctx: bad / dip_kind "los" -> los; btc_state slobodan_pad -> btc_zastita when
    the rest is >= protect_min (+1 %) net, btc_rez when <= -cut_pct (-10 %) from the FIRST entry; macro risk_off ->
    makro_zastita / makro_rez the same, between them the stop tightens to the first entry x (1 - cut_pct); vol_ratio <
    vol_collapse -> volumen. The backtest sees BTC, the macro regime and the volume; live also the dip reason."""
    c = {**RULE, **(cfg or {})}
    net = net_ret(pos["entry"], px * (1 - c["exit_slip"]), rt)
    first = pos.get("first") or pos["entry"]
    from_first = px / first - 1
    if ctx.get("bad"):   # 15.11. navečer: only new danger (live.context: dynamic reasons), never facts known at entry
        return "los", None
    if ctx.get("btc_state") == "slobodan_pad":
        if net >= c["protect_min"]:
            return "btc_zastita", None
        if from_first <= -c["cut_pct"]:
            return "btc_rez", None
    if ctx.get("macro") == "risk_off":
        if net >= c["protect_min"]:
            return "makro_zastita", None
        if from_first <= -c["cut_pct"]:
            return "makro_rez", None
        tight = first * (1 - c["cut_pct"])
        if tight > pos["stop_px"]:
            return None, tight
    vr = ctx.get("vol_ratio")
    if vr is not None and vr < c["vol_collapse"]:
        return "volumen", None
    return None, None


def vol_ratios(bars):
    """[24 h volume / the 7-day daily average or None] per 1h bar (prefix sums; None without 168 bars or when more
    than a quarter of the window has no volume: own DexScreener bars carry none)."""
    n = len(bars)
    v = [float(b[5] or 0.0) if len(b) > 5 else 0.0 for b in bars]
    zero = [1 if x <= 0 else 0 for x in v]
    ps, pz = [0.0], [0]
    for x, z in zip(v, zero):
        ps.append(ps[-1] + x)
        pz.append(pz[-1] + z)
    out = [None] * n
    for j in range(167, n):
        if pz[j + 1] - pz[j - 167] > 42:
            continue
        s7 = ps[j + 1] - ps[j - 167]
        if s7 <= 0:
            continue
        out[j] = (ps[j + 1] - ps[j - 23]) / (s7 / 7)
    return out


def candidates(bars, zones, look_d, crash=None, cfg=None, pit=None):
    """[(i, zone)] of the bars whose close passes the config-free part of the entry (zone valid, touch, near support,
    bounce, no crash) and, with pit(ts), the point-in-time universe (MC 5-150M and age > 15 d AT that time)."""
    c = {**RULE, **(cfg or {}), "look_d": look_d}
    out = []
    for i in range(c["touch_bars"], len(bars) - 1):
        t = bars[i][0] + c["bar_s"]
        if pit is not None and not pit(t, bars[i][4]):
            continue
        z = zones.at(t, look_d)
        if not z.get("ok") and not (c.get("btc_mode") == "dno" and c["crash_filter"]):
            continue
        if base_signal(bars, i, z, c, crash) is None:
            out.append((i, z))
    return out


def _bt_ctx(ctx, t, crash, j, lots):
    """The backtest's view of the DCA / reasoned-exit context at time t (bar j): BTC's state, the macro regime
    (ctx["macro"](t)), the token's category and metrics (static), the volume ratio of bar j; the candles cannot show a
    dip's reason (live only)."""
    vr = ctx.get("vol")
    return {"btc_state": crash.regime(t)[0] if crash is not None else None,
            "macro": ctx["macro"](t) if ctx.get("macro") else None, "cat": ctx.get("cat"),
            "metrics": ctx.get("metrics"), "vol_ratio": vr[j] if vr and j < len(vr) else None, "lots": len(lots)}


def simulate(bars, cands, size_usd, rt, cfg=None, drt=None, t0=None, t1=None, crash=None, rt2=None, ctx=None):
    """The trades of one token: entries from cands (candidates()) that pass this config, one position at a time, the
    cooldown after an exit, filled at the next bar's open (no look-ahead); open positions keep their losses through a
    crash (only NEW entries are banned). With a trailing, half is sold at the target, the rest trails from break-even
    (blend_ret). rt2: the round trip with the DCA lot (cost_at lots=2); ctx (None: no smart DCA conditions, no
    reasoned exits): {"macro": fn(t) -> regime, "cat", "metrics", "vol": vol_ratios(bars)}. [{ts, out_ts, entry,
    exit, reason, ret, pnl, ret_demo, lots, hours, mae, mfe, half, dca, zone_fresh, crash_overlap}]."""
    c = {**RULE, **(cfg or {})}
    drt = rt if drt is None else drt
    bs = c["bar_s"]
    out = []
    free_at = -1
    n = len(bars)
    for i, z in cands:
        ts_dec = bars[i][0] + bs
        if i + 1 >= n or i < free_at or ts_dec < (t0 or 0) or (t1 is not None and ts_dec >= t1):
            continue
        if config_refusal(bars[i][4], z, rt, c, crash, ts_dec):
            continue
        b = bars[i + 1]
        e = b[1] * (1 + c["entry_slip"])
        if c.get("macro_filter") and ctx and ctx.get("macro") and ctx["macro"](ts_dec) == "risk_off":
            continue
        pos = {"entry": e, "first": e, "ts": b[0], "tp_px": tp_price(e, c["tp"], rt, z, c), "stop_px": stop_px(e, z, c),
               "be_px": be_price(e, rt, c)}
        if c["tp"] in ("mid", "top") and pos["tp_px"] <= e:
            continue
        lots = [e]
        dca_px = dca_level(e, z, c) if (c.get("dca") or c.get("dca_mode") in ("zona", "atr")) else None
        if dca_px is not None and dca_px <= pos["stop_px"] * 1.02:
            dca_px = None     # a DCA level at the stop: no DCA (the stop never widens)
        crt = rt
        hit, j = None, i + 1
        lo, hi = e, e
        dca_log = None
        while j < n:
            bj = bars[j]
            if dca_px is not None and len(lots) == 1 and not pos.get("half_px") and bj[3] <= dca_px:
                fill_d = min(dca_px, bj[1]) * (1 + c["entry_slip"])
                why = None if fill_d > pos["stop_px"] else "ispod stopa"
                if why is None and ctx is not None:
                    why = dca_refusal(_bt_ctx(ctx, bj[0], crash, j, lots), c)
                if why is None:
                    lots.append(fill_d)    # the one DCA lot: the average entry, the net target and the BE move with it
                    avg = 2 / (1 / lots[0] + 1 / lots[1])
                    crt = rt if rt2 is None else rt2
                    pos["entry"] = avg
                    pos["be_px"] = be_price(avg, crt, c)
                    if c["tp"] not in ("mid", "top"):
                        pos["tp_px"] = tp_price(avg, c["tp"], crt, z, c)
                    dca_log = {"ts": bj[0], "px": fill_d}
                else:
                    dca_px = None if why != "ispod stopa" else dca_px
            hit = exit_on_bar(pos, bj, c)
            lo, hi = min(lo, bj[3]), max(hi, bj[2])
            if hit:
                break
            if c.get("reasoned") and ctx is not None:
                rs, tight = reasoned_exit(pos, bj[4], crt, _bt_ctx(ctx, bj[0] + bs, crash, j, lots), c)
                if rs:
                    hit = (rs, bj[4] * (1 - c["exit_slip"]))
                    break
                if tight:
                    pos["stop_px"] = tight
            j += 1
        if not hit:
            j = n - 1
            hit = ("kraj", bars[-1][4] * (1 - c["exit_slip"]))
        reason, fill = hit
        k = len(lots)
        r = blend_ret(pos, fill, crt, c, k)
        rd = blend_ret(pos, fill, drt, c, k)
        out_ts = bars[j][0] + bs
        out.append({"ts": b[0], "out_ts": out_ts, "entry": pos["entry"], "exit": fill, "reason": reason, "ret": r,
                    "pnl": r * size_usd * k, "ret_demo": rd, "lots": k, "hours": round((out_ts - b[0]) / H, 2),
                    "half": bool(pos.get("half_px")), "dca": dca_log, "first": e,
                    "mae": round(max(-0.99, min(lo, fill) / pos["entry"] - 1), 4),
                    "mfe": round(max(hi, fill) / pos["entry"] - 1, 4), "rt": crt, "fx": fill / pos["entry"],
                    "zone_fresh": bool(z.get("fresh")), "zone_ok": bool(z.get("ok")),
                    "crash_overlap": bool(crash is not None and crash.overlaps(b[0], out_ts))})
        free_at = j + int(c["cooldown_s"] // bs)
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


def configs(grid=None, stop="pct20"):
    g = {**GRID, **(grid or {})}
    return [{"tp": tp, "trail": tr, "time_h": th, "look_d": lk, "stop": stop}
            for lk in g["look_d"] for tp in g["tp"] for tr in g["trail"] for th in g["time_h"]]


def cfg_key(c):
    tp = c["tp"] if isinstance(c["tp"], str) else f"{c['tp']:g}%"
    return (f"tp{tp}" + (f"+tr{c['trail'] * 100:g}" if c.get("trail") else "") + f"/{c.get('stop', 'pct20')}/"
            f"{c['time_h'] // 24 if c['time_h'] % 24 == 0 else c['time_h']}{'d' if c['time_h'] % 24 == 0 else 'h'}/"
            f"z{c['look_d']}d" + (f"/dca{c['dca'] * 100:g}" if c.get("dca") else ""))
