"""ONE round-trip cost model, the size by slippage and the liquidity / volume floors (11.11., the owner's consolidated
correction, rules A, B and C). Every EV in the code takes its cost from here: momentum (rules.round_trip_cost,
evgate.cost), rangedca (backtest), proposals (build), the fast path (checks / decide), ui/kandidati (ev_estimate,
caller records) and the measurement pipelines' record cost (FEE_ROUND_TRIP).

Units: FRACTIONS of the stake (0.0215 = 2.15 %). A "*_pct" field elsewhere is that x 100.

    cost(size_usd, liq) = 2 x fee_side + 2 x impact        impact = size_usd / (liq / 2 + size_usd)

impact    the AMM impact of a constant-product pool with half the liquidity on each side (league/store.impact, the
          demo account's own fill model). Liquidity unknown: DEFAULT_LIQ ($40k, momentum's documented assumption).
fee_side  league/store.FEE (1 % a side: the swap route, priority fee and a margin; FEE_DEMO) until trade.db has
          measured swaps. Calibration (simple; it REPLACES the fee part, never the impact): the median of the last
          CALIB_N (30) trade.db orders that carry a cost_pct (live AND dry rows: a dry order is a real Jupiter quote
          for our size), each order's own per-side cost = cost_pct (the quote's USD in vs USD out: Jupiter's fee and
          its price impact at our size, ~0.1 % at 0.1 SOL in a $40k pool, so that impact is barely counted twice)
          + its network fee (fee_lamports / the SOL side of the swap: amount_in of a buy, amount_out of a sell).
          With fewer than CALIB_MIN_N (5) such orders: FEE_DEMO. Never below 0. Cached CALIB_TTL_S per trade.db.
FEE_ROUND_TRIP  2 x FEE_DEMO = 0.02: the fixed fee part the measurement pipelines' records are net of (scan.db shadow,
          kol/tpsl, events, kol/groupdisc, kol/preshill, the callers' 1 h records). Records stay comparable over time;
          a decision on such a record subtracts calib_delta() (2 x fee_side - FEE_ROUND_TRIP, 0 uncalibrated) and the
          impact of its own size on top, which is the same model.

Size (rule C): size = min(strategy cap, the largest stake whose simulated buy slippage (impact) is <= SLIP_MAX 2 %)
    impact(u, liq) <= s  <=>  u <= s / (1 - s) x liq / 2        ($153 in a $15k pool, $510 in a $50k one)
then x the volume factor (rule B): 1 h volume >= VOL_FULL ($10k) -> 1; VOL_FLOOR ($3k) .. $10k -> volume / $10k; under
$3k -> 0 (the hard floor: too little volume to trade); volume unknown -> 1 (the caller passes what it read).
Hard floor (rule B): liquidity under LIQ_HARD_MIN ($15k) is never bought (liq_block).
"""
import os
import sqlite3
import statistics
import time

try:
    from league import store as _lstore
    FEE_DEMO = float(_lstore.FEE)
except Exception:  # noqa: BLE001 - the league package always exists; a broken import must not hide the model
    FEE_DEMO = 0.01
FEE_ROUND_TRIP = round(2 * FEE_DEMO, 6)
DEFAULT_USD = 15.0          # ~0.1 SOL: the Autopilot's stake (momentum/rules.LOT_USD)
DEFAULT_LIQ = 40_000.0
SLIP_MAX = 0.02
LIQ_HARD_MIN = 15_000
VOL_FULL, VOL_FLOOR = 10_000, 3_000
CALIB_N, CALIB_MIN_N = 30, 5
CALIB_TTL_S = 600
LAMPORTS = 1_000_000_000
_CAL = {}                   # trade.db path -> (read time, fee_side or None, n)


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def impact(usd, liq):
    """The AMM impact of a stake of `usd` in a pool of `liq` (fraction; liq unknown -> DEFAULT_LIQ)."""
    side = (_f(liq) or DEFAULT_LIQ) / 2
    usd = max(0.0, _f(usd) or 0.0)
    return usd / (side + usd) if side > 0 else 1.0


# ---------- calibration ----------------------------------------------------------------------------------------------

def side_cost(cost_pct, side=None, amount_in=None, amount_out=None, fee_lamports=None):
    """One order's per-side cost (fraction): cost_pct / 100 + its network fee over the SOL side of the swap."""
    c = _f(cost_pct)
    if c is None:
        return None
    sol = _f(amount_in) if side == "buy" else _f(amount_out) if side == "sell" else None
    net = (_f(fee_lamports) or 0.0) / sol if sol and sol > 0 else 0.0
    return c / 100 + net


def calibrate(rows, n=CALIB_N, min_n=CALIB_MIN_N):
    """(fee_side or None, how many orders) from rows [(cost_pct, side, amount_in, amount_out, fee_lamports)], newest
    first: the median per-side cost of the newest n with a cost; None under min_n of them."""
    xs = [x for x in (side_cost(*r) for r in rows) if x is not None][:n]
    if len(xs) < min_n:
        return None, len(xs)
    return max(0.0, statistics.median(xs)), len(xs)


def _trade_db(path=None):
    if path:
        return path
    try:
        from trade import settings
        return settings.DB
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trade.db")


def calibration(path=None, now=None):
    """{"fee_side", "calibrated", "n", "from"}: the fee part in force (cached CALIB_TTL_S per trade.db)."""
    p = _trade_db(path)
    now = now or time.time()
    hit = _CAL.get(p)
    if hit is None or now - hit[0] > CALIB_TTL_S:
        fee, n = None, 0
        if os.path.exists(p) and os.path.getsize(p):
            try:
                con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2)
                try:
                    rows = con.execute("SELECT cost_pct, side, amount_in, amount_out, fee_lamports FROM orders WHERE "
                                       "cost_pct IS NOT NULL ORDER BY id DESC LIMIT ?", (CALIB_N,)).fetchall()
                finally:
                    con.close()
                fee, n = calibrate(rows)
            except sqlite3.Error:
                fee, n = None, 0
        hit = (now, fee, n)
        _CAL[p] = hit
    fee, n = hit[1], hit[2]
    return {"fee_side": fee if fee is not None else FEE_DEMO, "calibrated": fee is not None, "n": n,
            "from": (f"medijan zadnjih {n} naloga (trade.db orders.cost_pct + mrežna naknada)" if fee is not None
                     else f"league/store.FEE {FEE_DEMO:g} po strani (izmjerenih naloga {n}, treba {CALIB_MIN_N})")}


def fee_side(path=None):
    return calibration(path)["fee_side"]


def reset_cache():
    _CAL.clear()


# ---------- the cost -------------------------------------------------------------------------------------------------

def round_trip(size_usd=None, liq=None, fee=None):
    """The round-trip cost of a stake (FRACTION): 2 x fee_side + 2 x impact (see the module text)."""
    fs = fee_side() if fee is None else float(fee)
    return 2 * fs + 2 * impact(DEFAULT_USD if size_usd is None else size_usd, liq)


def min_round_trip(fee=None):
    """The fee part alone (no impact): the cheapest round trip, the 'no edge' prior's cost."""
    return 2 * (fee_side() if fee is None else float(fee))


def calib_delta(fee=None):
    """What a decision subtracts on top of a record net of FEE_ROUND_TRIP: 2 x fee_side - FEE_ROUND_TRIP."""
    return min_round_trip(fee) - FEE_ROUND_TRIP


def demo_adjust(fee=None):
    """A demo trade's return (booked at league/store.FEE a side) -> net of the calibrated fee: add this."""
    return -calib_delta(fee)


# ---------- size and floors ------------------------------------------------------------------------------------------

def max_size_usd(liq, slip=SLIP_MAX):
    """The largest stake (USD) whose buy impact stays <= slip; 0 without a known pool."""
    liq = _f(liq)
    if not liq or liq <= 0:
        return 0.0
    return slip / (1 - slip) * liq / 2


def vol_factor(vol_h1):
    """Size factor of the 1 h volume (rule B): 1 from $10k, volume / $10k from $3k, 0 under $3k; unknown -> 1."""
    v = _f(vol_h1)
    if v is None:
        return 1.0
    if v < VOL_FLOOR:
        return 0.0
    return min(1.0, v / VOL_FULL)


def size_sol(cap_sol, liq, sol_usd, vol_h1=None, mult=1.0):
    """The stake in SOL: min(cap_sol, the 2 % slippage stake) x the volume factor x mult (the P / size modifiers)."""
    cap = max(0.0, _f(cap_sol) or 0.0)
    su = _f(sol_usd)
    if su and su > 0 and _f(liq):
        cap = min(cap, max_size_usd(liq) / su)
    return round(cap * vol_factor(vol_h1) * max(0.0, float(mult)), 6)


def liq_block(liq):
    """The hard liquidity floor (rule B): the reason in Croatian, or None. Unknown liquidity blocks too."""
    v = _f(liq)
    if v is None:
        return "likvidnost nepoznata"
    if v < LIQ_HARD_MIN:
        return f"likvidnost ${v:,.0f} ispod ${LIQ_HARD_MIN / 1000:.0f}k"
    return None


def vol_block(vol_h1):
    """The 1 h volume hard floor (rule B: under $3k nothing is bought): the reason or None (unknown: None)."""
    v = _f(vol_h1)
    if v is not None and v < VOL_FLOOR:
        return f"volumen 1 h ${v:,.0f} ispod ${VOL_FLOOR / 1000:.0f}k"
    return None


def describe():
    """The model as get_scoring_config / get_proposals can show it."""
    c = calibration()
    return {"formula": "cost = 2 x fee_side + 2 x size_usd / (liq / 2 + size_usd) (fraction of the stake)",
            "fee_side": round(c["fee_side"], 5), "calibrated": c["calibrated"], "fee_from": c["from"],
            "size_rule": f"size = min(strategy cap, largest stake with buy impact <= {SLIP_MAX:.0%}) x volume factor",
            "liq_hard_min_usd": LIQ_HARD_MIN, "vol_full_usd": VOL_FULL, "vol_floor_usd": VOL_FLOOR}
