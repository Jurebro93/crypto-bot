"""Zadnjih 5 (14.11.2026, vlasnik): "Zaprati sve influencere koji su u zadnjih 5 poziva imali barem 10% profita i ulazi
na sve njihove tradeove i izlazi na 10% profita. Vidi na volete isto ... I izračunaj koliko je to kad se oduzmu fijevi
na te ulaze koje ti ulaziš. Jesmo li onda u ikakvom profitu".

First the walk-forward over our own stored data (no API call, read-only on every database), then, only behind a gate,
the follow.

SOURCES and their measured calls / buys (one per source and token: the first, as kol/minute and kol/tpsl count them)
  influencer  minute.db call_path (kol/minute: every real X / Telegram call of the last 30 days, bots out, under 30k
              MC marked bad and left out) with call_lv (the first minute every level was touched) and call_candles
              (the 1-minute GeckoTerminal candles, 4 h after the call): the 21.5k calls of the nightly
              "brzi izlaz" benchmark (proposals/job.bench_rows, the same kol/tpsl.rows filter)
  wallet      the first buy of a token by a wallet: wallets.db wallet_trades (kind buy), hype.db chain_trades and
              events.db wallet_buy (the live feed of followed wallets); its path from the token's own data:
              minute.db call_candles, else hype.db live_trades prints, else events.db price ticks, as 1-minute
              candles. The wallet's own realized PnL is NOT measured here (wallets/rang.py does that).

SELECTION at time t, without look-ahead: the source's LAST K (5) calls / buys before t whose outcome was known by t
(influencer: the call + 70 min, kol/minute measures a call once it is 70 min old; wallet: the buy + 65 min). The
outcome = the max gain within 60 min after the call / buy (influencer: call_path.hi60, kol/minute's capped high;
wallet: the same rule on its path). Variants:
  strogo   all 5 reached +10 %   (the owner's order)
  4od5     at least 4 of the 5
  prosjek  the mean of the 5 max gains >= +10 %
  svi      every call / buy of every source (the baseline, no selection)
Refresh: "noc" = the selection as of the last nightly run (03:00 Zagreb): the follows are refreshed nightly (and after
a start), so this is what following really does; "poziv" = re-evaluated at every call (the ideal, for comparison).

TRADE: the next call / buy of a selected source, entered after our measured lag (league.db copy_log entries of that
kind, else fast.db latency, else 60 s / 30 s; never under LAG_MIN_S): the close of the minute that holds call + lag;
0.1 SOL; exit at +10 % ("bruto", what the follow's tp "10%" does) or at +10 % after the round trip ("neto"); stop =
the owner's default stop (league/exitplan.sl_floor: trade settings sl_default, 60 % unless changed); time stop 60 min
after the entry (the measured hour). Target and stop in the same minute = the stop; a stop is booked at the deepest
level the minute's low reached (kol/tpsl's rule; below -70 % at the low itself). One open position per token. Only
calls the live system would buy: MC >= 30k, liquidity near the entry >= 15k (unknown: kept, priced at
trade/cost.DEFAULT_LIQ, counted), not on the pump.fun curve (a pump mint under the bonding market cap with no DEX
liquidity seen, or a print on pool 'pump'), not in the rug archive at that moment (archived before the call, or rug
mechanics), no bot / shill / bad-label source. Influencer trades without candles fall back to the stored levels
(kol/tpsl.outcome, entry at the call minute's close: a shorter lag, counted as "razine").
COST (the real account, rangedca/rules.real_cost): 2 x (pool fee 0.3 % PumpSwap / 0.25 % other + Jupiter route 0.1 %)
+ the buy's and the sale's AMM impact of the stake at the pool's liquidity + 2 network fees (rangedca/trade
tx_fee_sol: measured on trade.db orders, else 0.0005 SOL). Gross and net are both reported.
CAPS ("uz stropove"): trade/executor.SWITCH_CAPS (10 open, 100 buys a day, stop after -0.5 SOL a day).

FOLLOW (flag prati_zadnjih5 in trade/settings, an owner switch, default off): "uživo" = both types followed. On top,
the runner turns a type on by itself (trade settings zadnjih5_auto) ONLY when the strict variant's walk-forward (noc,
bruto, the follow's exit) is in the plus after costs on at least GATE_N trades; else that type stays off ("zadnjih 5:
ne pratim: ..."). Followed: the currently qualifying sources (strict), at most MAX_FOLLOW per type by the number of
qualifying windows, never a bot / shill / bad-label wallet / "nije kopirljivo" source (wallets/rang gate), on the
Autopilot account (trade/settings.LEAGUE_USER) with league/copy.follow and EXACTLY the measured exit (exit_of): tpsl,
TP +10 % and the stop -sl_default (the same value the walk-forward used, written into the follow) from the copy's
entry price, a 60-min time exit (league/auto "until": sold at the market when neither level was touched), no
stop_grace sleep, and out of the fast path (fast/sources skips exit src "zadnjih5", so its +15 / -10 / 45 min exit never
takes these signals). Under pravi_novac_sve the protective plan (league/exitplan.switch_stop) sits at the lot's own
stop, i.e. the same -sl_default (the -30 % default is only for a position without a stop). A kept follow gets the exit
again when sl_default changed. Only this module's follows (trade settings zadnjih5_follows) are ever stopped; one the
owner stopped himself is not taken back (zadnjih5_skip).

Run: `python3 -m kol.zadnjih5 once` (start.sh, ~5 min after a start, under ops.heavy; skipped when the last run is
younger than MIN_GAP_S), `night` (01-06 Zagreb, once a day), `uzorak --kol-db PATH` (a coarse run on an off-server
kol.db with only 24-h figures; never follows). Output output/zadnjih5.json (MCP get_last5) and "zadnjih 5: " lines.
"""
import bisect
import datetime as dt
import heapq
import json
import os
import sqlite3
import statistics
import sys
import time
import zlib
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 2
TZ = "Europe/Zagreb"
PREFIX = "zadnjih 5: "
K = 5
MIN_GAIN = 0.10
TP = 0.10
HORIZON_S = 3600
KNOWN_S = {"kol": 70 * 60, "wallet": 65 * 60}
LAG_MIN_S = 30
LAG_DEFAULT_S = {"kol": 60, "wallet": 30}
DAYS = 30
STAKE_SOL = 0.1
MIN_MCAP = 30_000
LIQ_MIN = 15_000
BOND_MCAP_SOL = 411.0     # pump.fun's curve completes at ~411 SOL market cap (30 + 85 SOL virtual / 279.9M tokens)
WICK_X = 3.0              # kol/minute: a one-print wick counts up to 3x the candle body
MAX_WAIT_S = 300          # kol/minute: no trade within 5 min of the entry minute = no entry
TOL_S = 15 * 60           # a path that ends earlier than this before the time stop is "nepotpuno"
LIQ_TOL_S = 30 * 60       # wallets/rang.SNAP_TOL_S
DOWNS = (10, 15, 20, 25, 30, 40, 50, 60, 70)   # kol/minute.DOWNS: the stop is booked at the deepest one touched
UPS = (5, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200)
VARIANTS = ("strogo", "4od5", "prosjek", "svi")
VARIANT_HR = {"strogo": "strogo 5/5", "4od5": "4 od 5", "prosjek": "prosjek 5 >= +10 %", "svi": "svi (osnova)"}
REFRESH = ("noc", "poziv")
TPS = ("bruto", "neto")
REFRESH_HOUR = 3
GATE = ("strogo", "noc", "bruto")    # the walk-forward the follow's gate reads: what the follow really does
GATE_N = 30
FLAG = "prati_zadnjih5"
SRC = "zadnjih5"          # the follow's exit "src": fast/sources leaves these follows to their own exit
MAX_FOLLOW = 50
TOP_N = 50
SIZE_USD = 15             # ~0.1 SOL; the real account's stake comes from trade/executor.SWITCH_CAPS anyway
PER_DAY = 10
TP_TEXT = "10%"
CAPS = {"max_open": 10, "max_buys_day": 100, "max_loss_day": 0.5}
MAX_WALLET_EVENTS = int(os.environ.get("ZADNJIH5_MAX_WALLET", "50000"))
BUDGET_S = {"once": 600, "night": 1500}
MIN_GAP_S = int(os.environ.get("ZADNJIH5_MIN_GAP_S", str(3 * 3600)))
TYPE_HR = {"kol": "influenceri", "wallet": "novčanici"}
BAD_WALLET = frozenset({"bot", "rugger", "bundler", "insider", "dev", "cex", "mev", "sniper", "funder_of_rugger"})
NO_FOLLOW_WALLET = BAD_WALLET | {"izbačen"}   # izbačen (ops/prune, a loser) is not followed, but stays in the history
STABLE = frozenset({"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"})
SOL_USD_DEFAULT = 150.0
FAST_KINDS = {"kol": ("influencer", "x_call"), "wallet": ("wallet_follow", "insider", "proven", "pre_shill", "group")}


# ---------- small helpers -------------------------------------------------------------------------------------------

def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def is_pump(mint):
    return bool(mint) and str(mint).endswith("pump")


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def day_of(ts):
    return dt.datetime.fromtimestamp(int(ts), ZoneInfo(TZ)).strftime("%Y-%m-%d")


def refresh_cut(ts, hour=REFRESH_HOUR):
    """The last nightly refresh (hour:00 Zagreb) at or before ts."""
    d = dt.datetime.fromtimestamp(int(ts), ZoneInfo(TZ))
    r = d.replace(hour=hour, minute=0, second=0, microsecond=0)
    if r > d:
        r -= dt.timedelta(days=1)
    return int(r.timestamp())


def paths(over=None):
    """Every database this module reads or writes; `over` replaces any of them (tests, the sample run)."""
    p = dict(over or {})

    def put(k, fn):
        if k not in p:
            try:
                p[k] = fn()
            except Exception:  # noqa: BLE001 - a missing module is a missing source
                p[k] = None
    put("minute", lambda: __import__("kol.minute", fromlist=["db_path"]).db_path())
    put("kol", lambda: __import__("kol.store", fromlist=["DB"]).DB)
    put("hype", lambda: os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db"))
    put("wallets", lambda: __import__("wallets.store", fromlist=["DB"]).DB)
    put("events", lambda: __import__("events.store", fromlist=["db_path"]).db_path())
    put("league", lambda: __import__("league.store", fromlist=["DB"]).DB)
    put("trade", lambda: __import__("trade.settings", fromlist=["DB"]).DB)
    put("fast", lambda: __import__("fast.store", fromlist=["db_path"]).db_path())
    put("market", lambda: __import__("market.store", fromlist=["DB"]).DB)
    put("out", lambda: os.environ.get("ZADNJIH5_OUT") or os.path.join(ROOT, "output", "zadnjih5.json"))
    return p


# ---------- selection (pure) ----------------------------------------------------------------------------------------

def qualifies(gains, variant, k=K, min_gain=MIN_GAIN):
    """Does a window of max gains (fractions, oldest first; the last k count) pass the variant?"""
    if variant == "svi":
        return True
    if len(gains) < k:
        return False
    g = list(gains)[-k:]
    if variant == "strogo":
        return all(x >= min_gain for x in g)
    if variant == "4od5":
        return sum(1 for x in g if x >= min_gain) >= k - 1
    if variant == "prosjek":
        return sum(g) / k >= min_gain
    raise ValueError(f"nepoznata varijanta {variant}")


def window(hist, tss, cutoff, k=K):
    """The max gains (oldest first) of the source's last k events before `cutoff` whose outcome was known by then.
    hist: the source's events sorted by ts; tss: their ts (for bisect). An event at the cutoff itself never counts."""
    i = bisect.bisect_left(tss, cutoff)
    out = []
    j = i - 1
    while j >= 0 and len(out) < k:
        e = hist[j]
        if e.get("gain") is not None and e["known"] <= cutoff:
            out.append(e["gain"])
        j -= 1
    out.reverse()
    return out


def by_source(events):
    out = {}
    for e in sorted(events, key=lambda e: (e["ts"], e["tok"])):
        out.setdefault(e["src"], []).append(e)
    return out


def walk(srcs, variant, refresh="noc", k=K, min_gain=MIN_GAIN):
    """The events the variant enters, without look-ahead: every event of a source selected at that moment (refresh
    "poziv": the window before the event itself; "noc": the window as of the last nightly refresh before it)."""
    out = []
    for hist in srcs.values():
        if variant == "svi":
            out.extend(hist)
            continue
        tss = [e["ts"] for e in hist]
        for e in hist:
            cut = e["ts"] if refresh == "poziv" else refresh_cut(e["ts"])
            if qualifies(window(hist, tss, cut, k), variant, k, min_gain):
                out.append(e)
    return out


def ok_windows(hist, variant="strogo", k=K, min_gain=MIN_GAIN):
    """How many sliding windows of k measured events of this source pass the variant (its record of qualifying)."""
    g = [e["gain"] for e in hist if e.get("gain") is not None]
    return sum(1 for i in range(k - 1, len(g)) if qualifies(g[i - k + 1:i + 1], variant, k, min_gain))


def selected_now(srcs, now, variant="strogo", k=K, min_gain=MIN_GAIN):
    """{source: last k gains} of the sources the variant selects at `now`."""
    out = {}
    for s, hist in srcs.items():
        w = window(hist, [e["ts"] for e in hist], now + 1, k)
        if variant != "svi" and qualifies(w, variant, k, min_gain):
            out[s] = w
    return out


# ---------- one trade's path (pure) ---------------------------------------------------------------------------------

def _entry(cs, t, max_wait=MAX_WAIT_S):
    """(entry price, path start time, index of the first candle after the entry) for an entry at t: the close of the
    minute that holds t, else the open of the first candle within max_wait after it (kol/minute.path's rule).
    cs: candles sorted by time (every reader here hands them sorted)."""
    m = int(t) - int(t) % 60
    i = bisect.bisect_left(cs, (m,))
    if i >= len(cs):
        return None
    c = cs[i]
    if c[0] == m and c[4] and c[4] > 0:
        return c[4], m + 60, i + 1
    if m < c[0] <= m + max_wait and c[1] and c[1] > 0:
        return c[1], c[0], i
    return None


def _capped(c, wick=WICK_X):
    return min(c[2], max(c[1], c[4]) * wick) if c[1] and c[4] else c[2]


def stop_booked(lo_ret, sl):
    """A stop's result: the deepest DOWNS level the minute's low reached (never better than -sl), the low itself under
    -70 %."""
    if lo_ret < -max(DOWNS) / 100:
        return max(lo_ret, -1.0)
    deep = max([d for d in DOWNS if d >= sl * 100 - 1e-9 and lo_ret <= -d / 100 + 1e-12] or [sl * 100])
    return -deep / 100


def max_gain(candles, t, horizon_s=HORIZON_S, wick=WICK_X):
    """The max (capped) gain within horizon_s after an entry at t, from 1-min candles sorted by time; None without an
    entry or any candle after it (an unmeasured call)."""
    cs = candles
    e = _entry(cs, t)
    if not e:
        return None
    entry, t0, j = e
    top = None
    for k in range(j, len(cs)):
        if cs[k][0] >= t0 + horizon_s:
            break
        h = _capped(cs[k], wick)
        top = h if top is None else max(top, h)
    return None if top is None else top / entry - 1


def sim(candles, t_entry, tp, sl, horizon_s=HORIZON_S, wick=WICK_X, covered_to=None, tol_s=TOL_S):
    """One trade on 1-min candles [(t, o, h, l, c, v)] sorted by time: (kind, gross, t_in, t_out, complete) or None
    without an entry.
    kind 'tp' (+tp), 'sl' (stop_booked), 'time' (the close at the time stop, between -sl and +tp). The stop wins a
    minute where both are touched. covered_to: the time the data is known to reach (None = complete); a path that
    ends more than tol_s before the time stop without tp / sl is complete False (booked at its last close)."""
    cs = candles
    e = _entry(cs, t_entry)
    if not e:
        return None
    entry, t0, j = e
    end = t0 + horizon_s
    last = entry
    for k in range(j, len(cs)):
        c = cs[k]
        if c[0] >= end:
            break
        if c[3] is not None and c[3] <= entry * (1 - sl):
            return "sl", stop_booked(c[3] / entry - 1, sl), t0, c[0] + 60, True
        if _capped(c, wick) >= entry * (1 + tp):
            return "tp", tp, t0, c[0] + 60, True
        last = c[4] or last
    complete = covered_to is None or covered_to >= end - tol_s
    return "time", max(-sl, min(last / entry - 1, tp)), t0, end, complete


def to_candles(points):
    """[(ts, price)] (trade prints or price ticks) -> 1-min candles [(t, o, h, l, c, 0)]."""
    out = {}
    for t, p in sorted(points):
        if not p or p <= 0:
            continue
        m = int(t) - int(t) % 60
        c = out.get(m)
        if c is None:
            out[m] = [m, p, p, p, p]
        else:
            c[2], c[3], c[4] = max(c[2], p), min(c[3], p), p
    return [tuple(c) + (0.0,) for _, c in sorted(out.items())]


def level_sim(row, tp, sl):
    """An influencer trade from minute.db's stored levels (kol/tpsl.outcome; entry at the call minute's close): a
    target that is not a stored level is reached only when the next stored level above it was (never a guessed win).
    (kind, gross, t_in, t_out, complete) or None."""
    from kol import tpsl
    need = tp * 100
    lvl = next((u for u in UPS if u >= need - 1e-9), None)
    sl_pct = int(round(sl * 100))
    if lvl is None:
        return None
    kind, g = tpsl.outcome(row, lvl, sl_pct)
    up, dn, _exact = tpsl._levels(row)
    t0 = int(row["ts"]) - int(row["ts"]) % 60 + 60
    if kind == "tp":
        return "tp", tp, t0, t0 + 60 * int(up.get(lvl) or 0), True
    if kind == "sl":
        m = dn.get(sl_pct)
        return "sl", g / 100, t0, t0 + 60 * int(m if m is not None else 60), True
    return "time", min(g / 100, tp), t0, t0 + HORIZON_S, True


# ---------- cost --------------------------------------------------------------------------------------------------

def round_trip(liq, mint, sol_usd, tx_sol, stake_sol=STAKE_SOL):
    """The real account's round trip of one stake, as a fraction (rangedca/rules.real_cost)."""
    from rangedca import rules
    from trade import cost as _cost
    su = sol_usd or SOL_USD_DEFAULT
    fee = rules.pool_fee(dex="pump" if is_pump(mint) else "") + rules.ROUTE_FEE
    return rules.real_cost([stake_sol * su], liq or _cost.DEFAULT_LIQ, fee, (tx_sol or rules.TX_FEE_SOL) * su, sells=1)


def tx_fee():
    """(SOL per swap, where from): rangedca/trade.tx_fee_sol (trade.db orders), else rules.TX_FEE_SOL."""
    try:
        from rangedca import trade as rtrade
        return rtrade.tx_fee_sol()
    except Exception:  # noqa: BLE001 - the default is the documented fallback
        from rangedca import rules
        return rules.TX_FEE_SOL, f"zadano {rules.TX_FEE_SOL:g} SOL po swapu"


def default_sl(trade_db=None):
    """The owner's default stop as a fraction (league/exitplan.sl_floor's rule, read-only from trade.db)."""
    from trade import settings as ts
    v = None
    con = _ro(trade_db or ts.DB)
    r = _q(con, "SELECT v FROM settings WHERE k = 'sl_default'")
    if con is not None:
        con.close()
    try:
        v = json.loads(r[0][0]) if r else None
        v = abs(float(v)) if v else float(ts.SL_DEFAULT)
    except (TypeError, ValueError):
        v = float(ts.SL_DEFAULT)
    return v / 100


def switch_caps():
    try:
        from trade import executor
        c = executor.SWITCH_CAPS
        return {"max_open": int(c["max_open"]), "max_buys_day": int(c["max_buys_day"]),
                "max_loss_day": float(c["max_loss_day"])}
    except Exception:  # noqa: BLE001 - the same numbers, written here
        return dict(CAPS)


def curve_guess(mint, mcap, liq, sol_usd, pool=None):
    """True when the token may have been on the pump.fun curve at the entry: a print on pool 'pump', or a pump mint
    with no DEX liquidity seen and a market cap under the bonding one (BOND_MCAP_SOL)."""
    if pool:
        return str(pool).lower() == "pump"
    if not is_pump(mint) or (liq and liq > 0):
        return False
    return mcap is None or mcap < BOND_MCAP_SOL * (sol_usd or SOL_USD_DEFAULT)


def lag_of(kind, p, now, days=DAYS):
    """(seconds, where from): our entry delay after a call / buy of this kind (see the module text)."""
    xs, src = [], None
    con = _ro(p.get("league"))
    for (d,) in _q(con, "SELECT c.ts - c.ev_ts FROM copy_log c JOIN follows f ON f.id = c.follow_id WHERE f.kind = ? "
                        "AND c.action = 'ulaz' AND c.ts >= ? AND c.ev_ts > 0", (kind, now - days * 86400)):
        if d is not None and 0 <= d <= 3600:
            xs.append(float(d))
    if con is not None:
        con.close()
    if len(xs) >= 5:
        src = f"league copy_log, medijan {len(xs)} ulaza"
    else:
        xs = []
        con = _ro(p.get("fast"))
        q = ",".join("?" * len(FAST_KINDS[kind]))
        for (d,) in _q(con, f"SELECT latency_s FROM signals WHERE kind IN ({q}) AND latency_s >= 0 AND latency_s <= 3600 "
                            f"AND decided_ts >= ?", (*FAST_KINDS[kind], now - days * 86400)):
            xs.append(float(d))
        if con is not None:
            con.close()
        if len(xs) >= 5:
            src = f"fast.db latency_s, medijan {len(xs)} signala"
    if src:
        lag = statistics.median(xs)
    else:
        lag, src = float(LAG_DEFAULT_S[kind]), "zadano (nema izmjerenih ulaza)"
    if lag < LAG_MIN_S:
        src += f", podignuto na {LAG_MIN_S} s"
        lag = float(LAG_MIN_S)
    return lag, src


# ---------- reading our data (read-only) ----------------------------------------------------------------------------

class Data:
    """Read-only connections and the small lookups every event needs (one token at a time, so memory stays small)."""

    def __init__(self, p, now):
        self.p, self.now = p, now
        self.m = _ro(p.get("minute"))
        self.k = _ro(p.get("kol"))
        self.h = _ro(p.get("hype"))
        self.e = _ro(p.get("events"))
        self._sol = None
        self._arch = None
        self._supply = {}

    def close(self):
        for c in (self.m, self.k, self.h, self.e):
            if c is not None:
                c.close()

    def sol_usd(self, ts):
        if self._sol is None:
            try:
                from wallets import rang
                self._sol = rang.sol_usd_days(self.p.get("market")) or {}
            except Exception:  # noqa: BLE001
                self._sol = {}
        d = int(ts) // 86400 * 86400
        for k in range(8):
            v = self._sol.get(d - k * 86400)
            if v:
                return v
        return SOL_USD_DEFAULT

    def archive(self):
        """{token: (archived_ts, kind, recovered_ts)} of hype.db rug_archive."""
        if self._arch is None:
            self._arch = {}
            for tok, ats, kind in _q(self.h, "SELECT token, archived_ts, kind FROM rug_archive"):
                self._arch[tok] = (ats or 0, kind, None)
            for tok, rts in _q(self.h, "SELECT token, recovered_ts FROM rug_recovered"):
                if tok in self._arch:
                    a = self._arch[tok]
                    self._arch[tok] = (a[0], a[1], rts)
        return self._arch

    def archived_at(self, tok, ts):
        """Why the live system would not buy this token at ts because of the rug archive, or None. A token archived
        AFTER the call stays in (those are the losses the copy would have taken)."""
        a = self.archive().get(tok)
        if not a:
            return None
        ats, kind, rec = a
        if kind == "mehanika":
            return "rug arhiva (mehanika ruga prije ulaza)"
        if ats and ats <= ts and not (rec and rec <= ts):
            return "rug arhiva (arhiviran prije poziva)"
        return None

    def candles(self, tok):
        """(candles, covered_to) of minute.db call_candles for the token, or (None, None)."""
        r = _q(self.m, "SELECT data, full, last_ts FROM call_candles WHERE token = ?", (tok,))
        if not r or not r[0][0]:
            return None, None
        try:
            cs = sorted(tuple(c) for c in json.loads(zlib.decompress(r[0][0]).decode()))
        except (ValueError, zlib.error, TypeError):
            return None, None
        if not cs:
            return None, None
        full, last = r[0][1], r[0][2]
        return cs, (float("inf") if full else (last or 0) + 60)

    def prints(self, tok, lo, hi):
        """[(ts, price_sol, mcap_sol, pool)] of hype.db live_trades (PumpPortal prints of every wallet)."""
        return _q(self.h, "SELECT ts, price_sol, mcap_sol, pool FROM live_trades WHERE mint = ? AND ts >= ? AND ts <= ? "
                          "AND price_sol > 0 ORDER BY ts LIMIT 50000", (tok, int(lo), int(hi)))

    def ticks(self, tok, lo, hi):
        """[(ts, price_usd, mcap_usd)] of events.db price ticks (DexScreener snapshots; none under 30k MC)."""
        out = []
        for t, pl, mc in _q(self.e, "SELECT ts, payload, mcap_usd FROM events WHERE mint = ? AND type = 'price_tick' "
                                    "AND ts >= ? AND ts <= ? ORDER BY ts LIMIT 5000", (tok, int(lo) * 1000, int(hi) * 1000)):
            try:
                p = _f(json.loads(pl or "{}").get("p"))
            except ValueError:
                p = None
            if p:
                out.append((t // 1000, p, mc))
        return out

    def liqs(self, tok, lo, hi):
        """[(ts, liq USD)] near the entries: kol.db snaps, hype.db token_pulse / hype_snapshots (wallets/rang's
        SNAP_SOURCES)."""
        out = []
        for con, table, col in ((self.k, "snaps", "liq"), (self.h, "token_pulse", "liquidity"),
                                (self.h, "hype_snapshots", "liquidity")):
            out += _q(con, f"SELECT ts, {col} FROM {table} WHERE token = ? AND ts >= ? AND ts <= ? AND {col} > 0",
                      (tok, int(lo) - LIQ_TOL_S, int(hi) + LIQ_TOL_S))
        return sorted((int(t), float(v)) for t, v in out)

    def supply(self, tok):
        if tok not in self._supply:
            r = _q(self.k, "SELECT supply FROM tokens WHERE token = ?", (tok,))
            self._supply[tok] = _f(r[0][0]) if r else None
        return self._supply[tok]


def nearest(pts, t, tol=LIQ_TOL_S):
    """The value of the point nearest t within tol, from sorted [(ts, v)]; None."""
    if not pts:
        return None
    tss = [x[0] for x in pts]
    i = bisect.bisect_left(tss, t)
    best = min((pts[j] for j in (i - 1, i) if 0 <= j < len(pts)), key=lambda x: abs(x[0] - t), default=None)
    return best[1] if best and abs(best[0] - t) <= tol else None


def _merge(times, before, after):
    """Merged [lo, hi] windows around the times."""
    out = []
    for t in sorted(times):
        lo, hi = t - before, t + after
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def _rules(ev, d, sol, pool=None):
    """Why the live system would not buy this event (None = it would)."""
    mc, liq = ev.get("mcap"), ev.get("liq")
    if mc is not None and mc < MIN_MCAP:
        return "MC ispod 30k"
    if liq is not None and liq < LIQ_MIN:
        return "likvidnost ispod 15k"
    if curve_guess(ev["tok"], mc, liq, sol, pool):
        return "možda na pump.fun krivulji"
    return d.archived_at(ev["tok"], ev["ts"])


def _sims(ev, sol, sl, tx_sol, fn):
    """ev["cost"], ev["usd"] and ev["sims"] {"bruto", "neto"} with fn(tp) -> (kind, gross, t_in, t_out, complete)."""
    ev["cost"] = round_trip(ev.get("liq"), ev["tok"], sol, tx_sol)
    ev["usd"] = STAKE_SOL * sol
    ev["sims"] = {}
    for key, tp in (("bruto", TP), ("neto", TP + ev["cost"])):
        s = fn(tp)
        if s:
            ev["sims"][key] = s


def kol_events(p, now, lag, sl, tx_sol, days=DAYS, log=print):
    """[event] of every measured influencer call of the window (see the module text) and the coverage counts."""
    from kol import shillers
    d = Data(p, now)
    cov = {"pozivi": 0, "svijeće": 0, "razine": 0, "bez_puta": 0, "pravila": {}, "likv_nepoznata": 0}
    try:
        if d.m is None:
            return None, {"greška": "minute.db nije dostupan"}
        since = now - days * 86400
        cols = ("tweet_id", "token", "handle", "ts", "entry", "lag_s", "mcap_e", "hi60", "lo60", "r60", "t5", "t10",
                "t15", "t20", "t30", "sl_min")
        sel = ", ".join("c." + c for c in cols)
        try:
            got = d.m.execute(f"SELECT {sel}, l.lv FROM call_path c LEFT JOIN call_lv l ON l.tweet_id = c.tweet_id AND "
                              f"l.token = c.token WHERE c.entry IS NOT NULL AND c.bad IS NULL AND c.ts >= ? AND c.ts <= ?",
                              (since, now)).fetchall()
        except sqlite3.OperationalError as e:
            if "call_lv" not in str(e):
                raise
            got = d.m.execute(f"SELECT {sel}, NULL FROM call_path c WHERE c.entry IS NOT NULL AND c.bad IS NULL AND "
                              f"c.ts >= ? AND c.ts <= ?", (since, now)).fetchall()
        bots = {h.lower() for (h,) in _q(d.k, "SELECT handle FROM kols WHERE bot = 1")}
        try:
            shill = shillers.handles()
        except Exception:  # noqa: BLE001
            shill = set()
        first = {}
        for r in got:
            row = dict(zip(cols + ("lv",), r))
            h = row["handle"] or ""
            if not h or h.startswith("w:") or h.lower() in bots or h.lower() in shill:
                continue
            key = (h, row["token"])
            if key not in first or row["ts"] < first[key]["ts"]:
                first[key] = row
        rows = sorted(first.values(), key=lambda r: r["ts"])
        cov["pozivi"] = len(rows)
        mc0 = {}
        miss = [(r["tweet_id"], r["token"]) for r in rows if r["mcap_e"] is None and not is_pump(r["token"])]
        for part in _chunks(sorted({t for t, _ in miss})):
            for tid, tok, mc in _q(d.k, f"SELECT tweet_id, token, mcap0 FROM calls WHERE tweet_id IN "
                                        f"({','.join('?' * len(part))})", part):
                mc0[(tid, tok)] = mc
        by_tok = {}
        for r in rows:
            by_tok.setdefault(r["token"], []).append(r)
        out = []
        for tok, rs in by_tok.items():
            cs, cov_to = d.candles(tok)
            lq = d.liqs(tok, min(r["ts"] for r in rs), max(r["ts"] for r in rs))
            for r in rs:
                ts = int(r["ts"])
                sol = d.sol_usd(ts)
                mc = r["mcap_e"] or (r["entry"] * 1e9 if is_pump(tok) and r["entry"] else None) or mc0.get((r["tweet_id"], tok))
                ev = {"src": r["handle"], "tok": tok, "ts": ts, "known": ts + KNOWN_S["kol"],
                      "gain": _f(r["hi60"]), "mcap": mc, "liq": nearest(lq, ts)}
                ev["why"] = _rules(ev, d, sol)
                if ev["why"]:
                    cov["pravila"][ev["why"]] = cov["pravila"].get(ev["why"], 0) + 1
                else:
                    cov["likv_nepoznata"] += ev["liq"] is None
                    row = r

                    def fn(tp, row=row, ts=ts):
                        s = sim(cs, ts + lag, tp, sl, covered_to=cov_to) if cs else None
                        if s and s[4]:
                            return s + ("svijeće",)
                        lv = level_sim(row, tp, sl)
                        return lv + ("razine",) if lv else None
                    _sims(ev, sol, sl, tx_sol, fn)
                    how = (ev["sims"].get("bruto") or (None,) * 6)[5]
                    cov[how or "bez_puta"] += 1
                out.append(ev)
        return out, cov
    finally:
        d.close()


def wallet_buys(p, since, now):
    """{(wallet, mint): first buy ts} of the window and the row count per source."""
    got, n = {}, {}

    def add(rows, name):
        n[name] = 0
        for w, m, ts in rows:
            if not w or not m or not ts or m in STABLE:
                continue
            ts = int(ts)
            k = (w, m)
            if k not in got or ts < got[k]:
                got[k] = ts
            n[name] += 1
    for key, name, sql, scale in (
            ("wallets", "wallets.db wallet_trades", "SELECT wallet, mint, MIN(ts) FROM wallet_trades WHERE kind = 'buy' "
                                                   "AND ts >= ? AND ts <= ? GROUP BY wallet, mint", 1),
            ("hype", "hype.db chain_trades", "SELECT wallet, mint, MIN(ts) FROM chain_trades WHERE side = 'buy' AND "
                                             "ts >= ? AND ts <= ? GROUP BY wallet, mint", 1),
            ("events", "events.db wallet_buy", "SELECT actor, mint, MIN(ts) / 1000 FROM events WHERE type = "
                                               "'wallet_buy' AND ts >= ? AND ts <= ? GROUP BY actor, mint", 1000)):
        con = _ro(p.get(key))
        add(_q(con, sql, (since * scale, now * scale)), name)
        if con is not None:
            con.close()
    return got, n


def wallet_labels(p, wallets):
    """({wallet: labels set}, owner's bot / sniper labels) for the given wallets."""
    out = {}
    con = _ro(p.get("wallets"))
    for part in _chunks(sorted(wallets)):
        for w, lab in _q(con, f"SELECT wallet, labels FROM wallets WHERE wallet IN ({','.join('?' * len(part))})", part):
            try:
                out[w] = set(json.loads(lab or "[]"))
            except ValueError:
                out[w] = set()
    if con is not None:
        con.close()
    owner = set()
    con = _ro(p.get("trade"))
    r = _q(con, "SELECT v FROM settings WHERE k = 'insider_labels'")
    if con is not None:
        con.close()
    try:
        lab = json.loads(r[0][0]) if r else {}
        owner = {w for w, v in (lab or {}).items() if isinstance(v, dict) and v.get("label") in ("bot", "sniper")}
    except (ValueError, TypeError, AttributeError):
        pass
    return out, owner


def wallet_events(p, now, lag, sl, tx_sol, days=DAYS, budget_s=BUDGET_S["once"], log=print):
    """[event] of every first buy of a token by a wallet in the window, with its path (see the module text)."""
    t_start = time.monotonic()
    since = now - days * 86400
    buys, src_n = wallet_buys(p, since, now)
    cov = {"kupnje": len(buys), "izvori": src_n, "svijeće": 0, "printovi": 0, "tikovi": 0, "bez_puta": 0,
           "pravila": {}, "likv_nepoznata": 0, "nepotpuno": 0, "mc_nepoznat": 0, "izbačeni_novčanici": 0}
    if not buys:
        return None, dict(cov, greška="nema kupnji novčanika u bazama")
    labels, owner_bad = wallet_labels(p, {w for w, _ in buys})
    keep = []
    for (w, m), ts in buys.items():
        if labels.get(w, set()) & BAD_WALLET or w in owner_bad:
            cov["izbačeni_novčanici"] += 1
            continue
        keep.append((ts, w, m))
    keep.sort(reverse=True)
    if len(keep) > MAX_WALLET_EVENTS:
        cov["skraćeno_na"] = MAX_WALLET_EVENTS
        keep = keep[:MAX_WALLET_EVENTS]
    cov["od"] = min((t for t, _, _ in keep), default=None)
    by_mint = {}
    for ts, w, m in keep:
        by_mint.setdefault(m, []).append((ts, w))
    d = Data(p, now)
    out = []
    try:
        for n_done, (tok, bs) in enumerate(sorted(by_mint.items(), key=lambda x: -len(x[1]))):
            if time.monotonic() - t_start > budget_s:
                cov["nedovršeno"] = f"stalo nakon {budget_s} s: {n_done} od {len(by_mint)} tokena"
                break
            times = [t for t, _ in bs]
            cs, cov_to = d.candles(tok)
            lq = d.liqs(tok, min(times), max(times))
            span = lag + HORIZON_S + 2 * MAX_WAIT_S
            prints, ticks, pools = [], [], []
            sup = None if is_pump(tok) else d.supply(tok)
            def covers(c, t):
                return bool(c) and bool(_entry(c, t)) and c[-1][0] + 60 >= t + lag + HORIZON_S - TOL_S
            need = [t for t in times if not covers(cs, t)]
            for lo, hi in _merge(need, 120, span):
                pr = d.prints(tok, lo, hi + TOL_S)
                prints += [(t, px) for t, px, _mc, _pool in pr]
                pools += [(t, (mc, pool)) for t, _px, mc, pool in pr]
            pcs = to_candles(prints) if prints else []
            need2 = [t for t in need if not covers(pcs, t)]
            for lo, hi in _merge(need2, 120, span):
                tk = d.ticks(tok, lo, hi + TOL_S)
                ticks += tk
            tcs = to_candles([(t, px) for t, px, _ in ticks]) if ticks else []
            tick_mc = [(t, mc) for t, _px, mc in ticks if mc]
            pools.sort()
            # minute.db keeps a token's candles only around its KOL calls: they count for a buy only when they reach
            # its time stop; prints and ticks end where the data ends (covered_to = the last point)
            opts = []
            if cs:
                opts.append((cs, "svijeće", cs[-1][0] + 60))
            if pcs:
                opts.append((pcs, "printovi", max(t for t, _ in prints)))
            if tcs:
                opts.append((tcs, "tikovi", max(t for t, _, _ in ticks)))
            for ts, w in bs:
                sol = d.sol_usd(ts)
                path, how, cto = None, None, None
                with_entry = [o for o in opts if _entry(o[0], ts)]
                good = [o for o in with_entry if o[2] >= ts + lag + HORIZON_S - TOL_S]
                if good or with_entry:
                    path, how, cto = (good or with_entry)[0]
                near = nearest(pools, ts, 300)
                mc = None
                if near and near[0]:
                    mc = near[0] * sol
                if mc is None and tick_mc:
                    mc = nearest(tick_mc, ts, 1800)
                if mc is None and path:
                    px = _entry(path, ts)[0]
                    if how == "printovi":
                        mc = px * 1e9 * sol if is_pump(tok) else None
                    elif how == "svijeće":
                        mc = px * 1e9 if is_pump(tok) else (px * sup if sup else None)
                ev = {"src": w, "tok": tok, "ts": int(ts), "known": int(ts) + KNOWN_S["wallet"], "mcap": mc,
                      "liq": nearest(lq, ts), "gain": None}
                if mc is not None and mc < MIN_MCAP:
                    # CLAUDE.md: a token under 30k is not analysed at all (no history, no trade)
                    cov["pravila"]["MC ispod 30k"] = cov["pravila"].get("MC ispod 30k", 0) + 1
                    continue
                if path:
                    ev["gain"] = max_gain(path, ts)
                if mc is None:
                    cov["mc_nepoznat"] += 1
                ev["why"] = _rules(ev, d, sol, near[1] if near else None)
                if ev["why"]:
                    cov["pravila"][ev["why"]] = cov["pravila"].get(ev["why"], 0) + 1
                elif not path:
                    cov["bez_puta"] += 1
                else:
                    cov["likv_nepoznata"] += ev["liq"] is None

                    def fn(tp, path=path, ts=ts, cto=cto, how=how):
                        s = sim(path, ts + lag, tp, sl, covered_to=cto)
                        return s + (how,) if s else None
                    _sims(ev, sol, sl, tx_sol, fn)
                    s = ev["sims"].get("bruto")
                    cov[how if s else "bez_puta"] += 1
                    if s and not s[4]:
                        cov["nepotpuno"] += 1
                out.append(ev)
    finally:
        d.close()
    return out, cov


def sample_events(kol_db, now=None, sl=0.6, tx_sol=None):
    """Pretpostavka (uzorak): events from an off-server kol.db that only has the 24-h figures of kol/measure (p0,
    r24h, max24): gain = max24 (24 h instead of 60 min), the trade = +tp when max24 reached it (the order against the
    stop is unknown: taken as the target first, OPTIMISTIC), else the 24-h close between -sl and +tp; no lag; liquidity
    unknown (tokens.liquidity is today's: dead tokens would drop out, a survivor bias), so the cost is priced at
    trade/cost.DEFAULT_LIQ and a pump mint under the bonding market cap counts as "maybe on the curve". Only for a
    rough number on the sample files; never on the server."""
    con = _ro(kol_db)
    if con is None:
        return [], {"greška": "baza uzorka nije dostupna"}
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(kols)")}
        bots = ({h.lower() for (h,) in _q(con, "SELECT handle FROM kols WHERE bot = 1")} if "bot" in cols else set())
        rows = _q(con, "SELECT handle, token, ts, mcap0, max24, r24h, rug FROM calls WHERE kind = 'call' AND ts IS NOT NULL "
                       "ORDER BY ts")
    finally:
        con.close()
    first, out = set(), []
    cov = {"pozivi": 0, "pravila": {}}
    tx = tx_sol or 0.0005
    for h, tok, ts, mc, mx, r24, rug in rows:
        if not h or h.startswith("w:") or h.lower() in bots or (h, tok) in first:
            continue
        first.add((h, tok))
        if mc is not None and mc < MIN_MCAP:
            continue
        cov["pozivi"] += 1
        ev = {"src": h, "tok": tok, "ts": int(ts), "known": int(ts) + 86400 + 300, "gain": _f(mx), "mcap": mc,
              "liq": None}
        if curve_guess(tok, mc, None, SOL_USD_DEFAULT):
            ev["why"] = "možda na pump.fun krivulji"
        else:
            ev["why"] = None
        if ev["why"]:
            cov["pravila"][ev["why"]] = cov["pravila"].get(ev["why"], 0) + 1
        elif mx is not None:
            def fn(tp, mx=mx, r24=r24, ts=int(ts)):
                if mx >= tp:
                    return "tp", tp, ts, ts + 3600, True
                if r24 is None:
                    return None
                return ("sl" if r24 <= -sl else "time"), max(-sl, min(r24, tp)), ts, ts + 86400, True
            _sims(ev, SOL_USD_DEFAULT, sl, tx, lambda tp: (fn(tp) + ("24h",)) if fn(tp) else None)
        out.append(ev)
    return out, cov


# ---------- the simulation and its numbers (pure) -------------------------------------------------------------------

def simulate(cands, tp_key="bruto", caps=None, stake_sol=STAKE_SOL):
    """(trades, skipped) of the candidate events in time order: one open position per token; with caps
    {"max_open", "max_buys_day", "max_loss_day" (SOL)} also the real account's switch caps."""
    trades = []
    skipped = {"pravila": 0, "bez_puta": 0, "token": 0, "otvoreno": 0, "dan": 0, "gubitak": 0}
    busy = {}
    open_heap = []          # t_out of positions open (caps)
    closes = []             # (t_out, day, pnl SOL) not yet realized
    realized, buys = {}, {}
    for e in sorted(cands, key=lambda e: (e["ts"], e["src"], e["tok"])):
        if e.get("why"):
            skipped["pravila"] += 1
            continue
        s = (e.get("sims") or {}).get(tp_key)
        if not s:
            skipped["bez_puta"] += 1
            continue
        kind, gross, t_in, t_out = s[0], s[1], s[2], s[3]
        if busy.get(e["tok"], 0) > t_in:
            skipped["token"] += 1
            continue
        net = gross - e["cost"]
        if caps:
            while open_heap and open_heap[0] <= t_in:
                heapq.heappop(open_heap)
            while closes and closes[0][0] <= t_in:
                _t, dk, pnl = heapq.heappop(closes)
                realized[dk] = realized.get(dk, 0.0) + pnl
            day = day_of(t_in)
            if len(open_heap) >= caps["max_open"]:
                skipped["otvoreno"] += 1
                continue
            if buys.get(day, 0) >= caps["max_buys_day"]:
                skipped["dan"] += 1
                continue
            if realized.get(day, 0.0) <= -caps["max_loss_day"]:
                skipped["gubitak"] += 1
                continue
            buys[day] = buys.get(day, 0) + 1
            heapq.heappush(open_heap, t_out)
            heapq.heappush(closes, (t_out, day_of(t_out), net * stake_sol))
        busy[e["tok"]] = t_out
        trades.append({"src": e["src"], "tok": e["tok"], "ts": e["ts"], "t_in": t_in, "t_out": t_out, "kind": kind,
                       "complete": bool(s[4]) if len(s) > 4 else True, "how": s[5] if len(s) > 5 else None,
                       "gross": gross, "cost": e["cost"], "net": net, "usd": e.get("usd") or STAKE_SOL * SOL_USD_DEFAULT,
                       "liq_known": e.get("liq") is not None})
    return trades, skipped


def summarize(trades, span_days, sl, tp_key="bruto", stake_sol=STAKE_SOL):
    """The numbers of one walk-forward (fractions; *_pct in percent, *_usd per the stake's USD)."""
    n = len(trades)
    if not n:
        return {"n": 0, "per_day": 0.0}
    from trade import edge
    nets = [t["net"] for t in trades]
    gross = [t["gross"] for t in trades]
    costs = [t["cost"] for t in trades]
    c = statistics.mean(costs)
    tps = [t["gross"] for t in trades if t["kind"] == "tp"]
    tpg = statistics.mean(tps) if tps else (TP if tp_key == "bruto" else TP + c)
    # break-even hit rate: need_sl against a full stop on every miss (TP / SL only), need against the misses' real
    # mean result (stops and time exits together)
    miss = [t["gross"] for t in trades if t["kind"] != "tp"]
    loss = -statistics.mean(miss) if miss else sl
    need = (loss + c) / (tpg + loss) if tpg + loss > 0 else None
    st = edge.ev_stats(nets)
    eq = peak = dd = 0.0
    for t in sorted(trades, key=lambda t: t["t_out"]):
        eq += t["net"] * stake_sol
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    usd = statistics.mean(t["usd"] for t in trades)
    kinds = {}
    for t in trades:
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    known = [t["net"] for t in trades if t["liq_known"]]
    inc = [t for t in trades if not t["complete"]]
    worst = statistics.mean([(-sl - t["cost"]) if not t["complete"] and t["kind"] == "time" else t["net"]
                             for t in trades])
    out = {"n": n, "per_day": round(n / max(span_days, 1.0), 2), "sources": len({t["src"] for t in trades}),
           "hit": round(kinds.get("tp", 0) / n, 4), "need_sl": round((sl + c) / (tpg + sl), 4),
           "need": round(need, 4) if need is not None else None, "miss_mean_pct": round(-loss * 100, 3),
           "exits": kinds, "cost_pct": round(c * 100, 3),
           "ev_gross_pct": round(statistics.mean(gross) * 100, 3), "ev_net_pct": round(st["ev"] * 100, 3),
           "ev_lo90_pct": round(st["lo90"] * 100, 3) if st["lo90"] is not None else None,
           "ev_net_usd": round(st["ev"] * usd, 4), "ev_gross_usd": round(statistics.mean(gross) * usd, 4),
           "pnl_sol": round(sum(nets) * stake_sol, 4), "pnl_usd": round(sum(t["net"] * t["usd"] for t in trades), 2),
           "max_dd_sol": round(dd, 4), "max_dd_usd": round(dd * usd / stake_sol, 2),
           "liq_known": len(known), "ev_net_liq_known_pct": round(statistics.mean(known) * 100, 3) if known else None,
           "nepotpuno": len(inc), "ev_net_nepotpuno_stop_pct": round(worst * 100, 3) if inc else None,
           "how": {}}
    for t in trades:
        out["how"][t["how"] or "?"] = out["how"].get(t["how"] or "?", 0) + 1
    return out


def gate(s, n_min=GATE_N):
    """(on, why in Croatian) of a type's follow from its gate summary (EV net > 0 on n_min+ trades)."""
    n, ev = (s or {}).get("n") or 0, (s or {}).get("ev_net_pct")
    if n < n_min:
        return False, (f"premalo tradeova ({n} < {n_min})" + (f", EV neto {ev:+.2f} %" if ev is not None else ""))
    if ev is None or ev <= 0:
        return False, f"EV neto {ev:+.2f} % ≤ 0 na {n} tradeova"
    return True, f"EV neto {ev:+.2f} % > 0 na {n} tradeova (≥ {n_min})"


def analyse(events, kind, now, sl, span_days=None, caps=None):
    """Every variant x refresh x exit of one type, the sources selected now and the top list."""
    srcs = by_source([e for e in events if e.get("src")])
    if span_days is None:
        tss = [e["ts"] for e in events]
        span_days = (max(tss) - min(tss)) / 86400 if tss else 1.0
    caps = caps or switch_caps()
    res = {"events": len(events), "sources": len(srcs), "span_days": round(span_days, 2), "variants": {}, "now": {}}
    gate_trades = []
    for v in VARIANTS:
        res["variants"][v] = {}
        for rf in (("noc",) if v == "svi" else REFRESH):
            cands = walk(srcs, v, rf)
            res["variants"][v][rf] = {}
            for key in TPS:
                tr, sk = simulate(cands, key)
                s = summarize(tr, span_days, sl, key)
                s["skipped"] = sk
                tr_c, sk_c = simulate(cands, key, caps)
                sc = summarize(tr_c, span_days, sl, key)
                s["capped"] = {k: sc.get(k) for k in ("n", "per_day", "hit", "ev_net_pct", "ev_net_usd", "pnl_sol",
                                                      "pnl_usd", "max_dd_sol")}
                s["capped"]["skipped"] = {k: v2 for k, v2 in sk_c.items() if k in ("otvoreno", "dan", "gubitak")}
                res["variants"][v][rf][key] = s
                if (v, rf, key) == GATE:
                    gate_trades = tr
        if v == "svi":
            res["variants"][v]["poziv"] = res["variants"][v]["noc"]   # no selection: the refresh changes nothing
        res["now"][v] = len(srcs) if v == "svi" else len(selected_now(srcs, now, v))
    # the current strict list, by the number of qualifying windows, with each source's strict trades
    now_sel = selected_now(srcs, now, "strogo")
    per = {}
    for t in gate_trades:
        per.setdefault(t["src"], []).append(t)
    top = []
    for s, last in now_sel.items():
        hist = srcs[s]
        tr = per.get(s) or []
        top.append({"id": s, "n_calls": sum(1 for e in hist if e.get("gain") is not None),
                    "ok_windows": ok_windows(hist), "last5_pct": [round(g * 100, 1) for g in last],
                    "last_ts": hist[-1]["ts"], "trades": len(tr), "hits": sum(1 for t in tr if t["kind"] == "tp"),
                    "ev_net_pct": round(statistics.mean(t["net"] for t in tr) * 100, 2) if tr else None})
    top.sort(key=lambda r: (-r["ok_windows"], -r["n_calls"], -(r["last_ts"] or 0)))
    res["top"] = top[:TOP_N]
    res["qualifying_now"] = [r["id"] for r in top]
    res["gate"] = res["variants"][GATE[0]][GATE[1]][GATE[2]]
    return res


# ---------- follows -------------------------------------------------------------------------------------------------

def plan(ours, active, want, on, skip=()):
    """(add [target], remove [(target, follow id)]) for one type. ours: {target: id} of this module's active
    follows; active: {target: id} of every active follow of the account of this kind (never taken over); want: the
    targets to follow, in order; on: follow at all; skip: targets the owner stopped himself (not taken back)."""
    if not on:
        return [], sorted(ours.items())
    w = set(want)
    remove = sorted((t, i) for t, i in ours.items() if t not in w)
    add = [t for t in want if t not in ours and t not in active and t not in set(skip)]
    return add, remove


def label(kind, target):
    who = (target[3:] if target.startswith("tg:") else "@" + target) if kind == "kol" else f"{target[:4]}…{target[-4:]}"
    return f"zadnjih 5: {who}"


def followable(kind, ids, p, log=print):
    """The ids that may be followed: no bot / shill / bad-label wallet, and not "nije kopirljivo" by the copy ranking
    (league/copy._rang_gate's pool rule holds even under pravi_novac_sve, so such a follow would never buy)."""
    out, why = [], {}
    bad = set()
    if kind == "wallet":
        labels, owner_bad = wallet_labels(p, set(ids))
        bad = {w for w, lab in labels.items() if lab & NO_FOLLOW_WALLET} | owner_bad
    else:
        try:
            from kol import shillers
            bad = set(shillers.handles())
        except Exception:  # noqa: BLE001
            bad = set()
        con = _ro(p.get("kol"))
        bad |= {h.lower() for (h,) in _q(con, "SELECT handle FROM kols WHERE bot = 1")}
        if con is not None:
            con.close()
    try:
        from wallets import rang
    except Exception:  # noqa: BLE001
        rang = None
    for t in ids:
        if (t.lower() if kind == "kol" else t) in bad:
            why["bot / shill / loša oznaka"] = why.get("bot / shill / loša oznaka", 0) + 1
            continue
        if rang is not None:
            try:
                ok, w = rang.gate(kind, t)
            except Exception:  # noqa: BLE001 - an unreadable ranking blocks nothing (league/copy does the same)
                ok, w = None, ""
            if ok is False and str(w).startswith("nije kopirljivo"):
                why["nije kopirljivo"] = why.get("nije kopirljivo", 0) + 1
                continue
        out.append(t)
    return out, why


def exit_of(sl):
    """The exit every copy of a zadnjih 5 follow gets, the one the walk-forward measured: TP +10 % and the stop -sl
    from the copy's entry price (not the effective entry), sold at the market 60 min after the entry (league/auto
    "until"), no stop_grace sleep, and out of the fast path (its own exit). {kwarg: value} for league/copy.follow."""
    return {"exit_mode": "tpsl", "tp": TP_TEXT, "sl": f"-{round(sl * 100, 2):g}%", "hold_s": HORIZON_S,
            "from_eff": False, "grace": False, "src": SRC}


def _exit_stored(ex):
    """The part of a stored follow exit that exit_of sets (to see whether a kept follow needs its exit synced)."""
    return (ex.get("mode"), ex.get("tp"), ex.get("sl"), ex.get("hold_s"), ex.get("from_eff", True),
            bool(ex.get("no_grace")), ex.get("src"))


def apply_follows(kind, want, on, p, now, sl, log=print):
    """Make this module's follows of one type on the Autopilot account match `want` (or none when off), each with
    exit_of(sl); a kept follow whose exit differs (the owner changed sl_default) gets it again. Returns {"added",
    "removed", "synced", "total", "skip"}; manual follows and other tools' follows are never touched."""
    from league import copy
    from league import store as lstore
    from trade import settings
    tcon = settings.connect(p.get("trade"))
    lcon = lstore.connect(p.get("league"))
    try:
        copy.ensure(lcon)
        raw = settings.raw(tcon)
        ids_all = dict(raw.get("zadnjih5_follows") or {})
        skip_all = dict(raw.get("zadnjih5_skip") or {})
        skip = set(skip_all.get(kind) or [])
        rows = {r["id"]: r for r in lcon.execute("SELECT id, kind, target, active, exit FROM follows WHERE user = ?",
                                                 (settings.LEAGUE_USER,))}
        ours = {}
        for i in ids_all.get(kind) or []:
            r = rows.get(int(i))
            if r is None or r["kind"] != kind:
                continue
            if r["active"] == 1:
                ours[r["target"]] = r["id"]
            else:
                skip.add(r["target"])   # stopped by the owner (or another tool), not by us: not taken back
        active = {r["target"]: r["id"] for r in rows.values() if r["active"] == 1 and r["kind"] == kind}
        add, remove = plan(ours, active, want, on, skip)
        for t, i in remove:
            copy.unfollow(lcon, settings.LEAGUE_USER, i)
            ours.pop(t, None)
        spec = exit_of(sl)
        want_ex = (spec["exit_mode"], spec["tp"], spec["sl"], spec["hold_s"], False, True, SRC)
        added, synced = [], []
        for t in add + [t for t in ours if t in set(want)]:
            if t in ours:
                try:
                    ex = json.loads(rows[ours[t]]["exit"] or "{}")
                except (ValueError, TypeError):
                    ex = {}
                if _exit_stored(ex) == want_ex:
                    continue
            try:
                fid = copy.follow(lcon, settings.LEAGUE_USER, kind, t, label(kind, t), SIZE_USD, PER_DAY, **spec)
            except ValueError as e:
                log(f"{PREFIX}praćenje {t} nije dodano: {e}")
                continue
            (synced if t in ours else added).append(t)
            ours[t] = fid
        ids_all[kind] = sorted(ours.values())
        skip_all[kind] = sorted(skip)
        settings.put(tcon, "zadnjih5_follows", ids_all, "zadnjih5")
        settings.put(tcon, "zadnjih5_skip", skip_all, "zadnjih5")
        if added or remove:
            hist = list(raw.get("zadnjih5_log") or [])
            hist = ([{"ts": int(now), "op": "+", "kind": kind, "target": t} for t in added]
                    + [{"ts": int(now), "op": "-", "kind": kind, "target": t} for t, _ in remove] + hist)[:60]
            settings.put(tcon, "zadnjih5_log", hist, "zadnjih5")
        return {"added": added, "removed": [t for t, _ in remove], "synced": synced, "total": len(ours),
                "skip": len(skip), "exit": {k: v for k, v in spec.items()}}
    finally:
        lcon.close()
        tcon.close()


def flag_mode(p):
    """The owner switch prati_zadnjih5 ("live" = on for both types); "off" when unreadable."""
    try:
        from trade import settings
        return settings.flag(FLAG, path=p.get("trade"))   # read-only (cached 2 s; set_flag clears the cache)
    except Exception:  # noqa: BLE001
        return "off"


def save_auto(p, auto):
    from trade import settings
    tcon = settings.connect(p.get("trade"))
    try:
        settings.put(tcon, "zadnjih5_auto", auto, "zadnjih5")
    finally:
        tcon.close()


# ---------- the run -------------------------------------------------------------------------------------------------

def line(kind, v, r):
    """One log line of a type and variant (noc + bruto first: what following does)."""
    s = r["variants"][v]["noc"]["bruto"]
    head = f"{PREFIX}{TYPE_HR[kind]} {VARIANT_HR[v]}: izvora sada {r['now'][v]}"
    if not s.get("n"):
        return head + "; tradeova 0"
    txt = (f"{head}; noćno osvježavanje: {s['n']} tradeova ({s['per_day']:.1f}/dan, {s['sources']} izvora), pogodak "
           f"{s['hit']:.0%} (break-even {_p0(s['need'])}, uz pun stop {s['need_sl']:.0%}), EV bruto {s['ev_gross_pct']:+.2f} % / neto {s['ev_net_pct']:+.2f} % "
           f"({s['ev_net_usd']:+.3f} $), ukupno {s['pnl_sol']:+.3f} SOL ({s['pnl_usd']:+.2f} $) na 0,1 SOL ulog, max pad "
           f"-{s['max_dd_sol']:.3f} SOL; uz stropove {s['capped']['n']} tradeova, EV neto "
           f"{_n(s['capped']['ev_net_pct'])} %")
    n2 = r["variants"][v]["noc"]["neto"]
    if n2.get("n"):
        txt += f"; izlaz +10 % neto: EV neto {n2['ev_net_pct']:+.2f} %"
    if v != "svi":
        pz = r["variants"][v]["poziv"]["bruto"]
        if pz.get("n"):
            txt += f"; svaki poziv: {pz['n']} tradeova, EV neto {pz['ev_net_pct']:+.2f} %"
    return txt


def _p0(x):
    return "?" if x is None else f"{x:.0%}"


def _n(x):
    return "?" if x is None else f"{x:+.2f}"


def _load_prev(out):
    try:
        with open(out) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(out, data):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, out)


def run(now=None, p=None, log=print, follow=True, mode="once", days=DAYS):
    """The walk-forward of both types, the gate, the follows (follow=False: none), output/zadnjih5.json, the log
    lines. Returns the output dict."""
    t0 = time.monotonic()
    now = int(now or time.time())
    p = paths(p)
    sl = default_sl(p.get("trade"))
    tx_sol, tx_src = tx_fee()
    lags = {k: lag_of(k, p, now) for k in ("kol", "wallet")}
    out = {"ts": now, "version": VERSION, "mode": mode, "days": days,
           "assumptions": {"k": K, "min_gain_pct": MIN_GAIN * 100, "tp_pct": TP * 100, "sl_pct": round(sl * 100, 1),
                           "horizon_min": HORIZON_S // 60, "stake_sol": STAKE_SOL,
                           "lag_s": {k: [round(v[0], 1), v[1]] for k, v in lags.items()},
                           "known_after_min": {k: v // 60 for k, v in KNOWN_S.items()},
                           "tx_fee_sol": tx_sol, "tx_fee_src": tx_src, "refresh_hour_zagreb": REFRESH_HOUR,
                           "gate": {"variant": GATE[0], "refresh": GATE[1], "exit": GATE[2], "n_min": GATE_N},
                           "caps": switch_caps(), "max_follow": MAX_FOLLOW,
                           "cost": "2 x (pool 0.3 % PumpSwap / 0.25 % + ruta 0.1 %) + utjecaj 0,1 SOL na likvidnost "
                                   "(nepoznata: 40k) x 2 + 2 mrežne naknade"},
           "types": {}, "gate": {}, "follow": {}, "log": []}
    lines = []

    def say(s):
        lines.append(s)
        log(s, flush=True) if log is print else log(s)
    budget = BUDGET_S.get(mode, BUDGET_S["once"])
    for kind in ("kol", "wallet"):
        try:
            if kind == "kol":
                evs, cov = kol_events(p, now, lags[kind][0], sl, tx_sol, days)
            else:
                evs, cov = wallet_events(p, now, lags[kind][0], sl, tx_sol, days, budget)
        except Exception as e:  # noqa: BLE001 - one type's failure never stops the other
            evs, cov = None, {"greška": f"{type(e).__name__}: {e}"}
        if not evs:
            out["types"][kind] = {"coverage": cov, "error": cov.get("greška") or "nema podataka"}
            say(f"{PREFIX}{TYPE_HR[kind]}: nema podataka ({out['types'][kind]['error']})")
            continue
        # trades a day over the data really there (minute.db keeps 30 days; a cut wallet window is shorter)
        span = min(float(days), max(1.0, (now - min(e["ts"] for e in evs)) / 86400))
        r = analyse(evs, kind, now, sl, span_days=span)
        r["coverage"] = cov
        out["types"][kind] = r
        for v in VARIANTS:
            say(line(kind, v, r))
    mode_flag = flag_mode(p)
    out["follow"]["flag"] = mode_flag
    auto, parts = {}, []
    for kind in ("kol", "wallet"):
        r = out["types"][kind]
        if r.get("error"):
            auto[kind] = {"on": False, "why": f"nema podataka ({r['error']})", "ts": now, "known": False}
            continue
        on, why = gate(r["gate"])
        auto[kind] = {"on": on, "why": why, "ts": now, "known": True, "n": r["gate"].get("n"),
                      "ev_net_pct": r["gate"].get("ev_net_pct")}
        parts.append(f"{TYPE_HR[kind]} strogo {why} → {'pratim' if on else 'ne pratim'}")
    out["gate"] = auto
    say(f"{PREFIX}odluka: " + ("; ".join(parts) if parts else "nema podataka ni za jednu vrstu")
        + f" (prekidač {FLAG}: {mode_flag})")
    for kind in ("kol", "wallet"):
        a = auto[kind]
        manual = mode_flag == "live"
        on = manual or a["on"]
        if not on:
            say(f"{PREFIX}ne pratim: {TYPE_HR[kind]}: {a['why']}")
        if not a.get("known"):
            # minute.db / the wallet stores unreadable this run: nothing is added and nothing is stopped
            out["follow"][kind] = {"changed": False, "why": "nema podataka: praćenja ostaju kakva jesu"}
            continue
        r = out["types"][kind]
        want, why_out = (followable(kind, r.get("qualifying_now") or [], p) if on else ([], {}))
        capped = want[:MAX_FOLLOW]
        if not follow:
            out["follow"][kind] = {"on": on, "would_follow": len(capped), "qualifying": len(r.get("qualifying_now") or []),
                                   "excluded": why_out, "applied": False}
            continue
        try:
            res = apply_follows(kind, capped, on, p, now, sl, log=say)
        except Exception as e:  # noqa: BLE001 - a locked league.db: next run
            say(f"{PREFIX}praćenja {TYPE_HR[kind]} nisu usklađena ({type(e).__name__}: {e})")
            continue
        res.update(on=on, manual=manual, auto=a["on"], qualifying=len(r.get("qualifying_now") or []),
                   followable=len(want), excluded=why_out)
        out["follow"][kind] = res
        if res.get("synced"):
            say(f"{PREFIX}praćenja {TYPE_HR[kind]}: izlaz usklađen na {len(res['synced'])} praćenja "
                f"(TP {TP_TEXT}, SL {res['exit']['sl']}, najdulje {HORIZON_S // 60} min)")
        if not on and res["removed"]:
            say(f"{PREFIX}praćenja {TYPE_HR[kind]}: isključeno, prestajem pratiti {len(res['removed'])} izvora")
        elif on:
            say(f"{PREFIX}praćenja {TYPE_HR[kind]}: kvalificira se {res['qualifying']}, smije se pratiti "
                f"{res['followable']}" + (" (izbačeno: " + ", ".join(f"{k} {v}" for k, v in why_out.items()) + ")"
                                          if why_out else "")
                + f", prati se {res['total']} (strop {MAX_FOLLOW}); +{len(res['added'])} / -{len(res['removed'])}; "
                f"{'prekidač uživo' if manual else 'runner po EV-u' if a['on'] else 'isključeno'}; izlaz TP {TP_TEXT} / "
                f"SL {res['exit']['sl']} od ulazne cijene, najdulje {HORIZON_S // 60} min")
    if follow:
        try:
            save_auto(p, auto)
        except Exception as e:  # noqa: BLE001
            say(f"{PREFIX}stanje odluke nije spremljeno ({type(e).__name__}: {e})")
    out["seconds"] = round(time.monotonic() - t0, 1)
    say(f"{PREFIX}gotovo za {out['seconds']:.0f} s (prozor {days} dana, mod {mode})")
    out["log"] = lines
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "once"
    p = paths()
    out_path = p["out"]
    if cmd == "uzorak":
        kdb = argv[argv.index("--kol-db") + 1] if "--kol-db" in argv else None
        dst = argv[argv.index("--out") + 1] if "--out" in argv else None
        evs, cov = sample_events(kdb)
        now = max((e["ts"] for e in evs), default=int(time.time())) + 2 * 86400
        tss = [e["ts"] for e in evs]
        r = analyse(evs, "kol", now, 0.6, span_days=(max(tss) - min(tss)) / 86400 if tss else 1.0)
        r["coverage"] = cov
        res = {"uzorak": kdb, "types": {"kol": r}, "note": "Pretpostavka (uzorak): 24 h umjesto 60 min, TP prije stopa "
                                                           "pretpostavljen (optimistično), bez kašnjenja"}
        for v in VARIANTS:
            print(line("kol", v, r).replace(PREFIX, PREFIX + "uzorak: ", 1))
        if dst:
            _write(dst, res)
        return 0
    prev = _load_prev(out_path)
    now = int(time.time())
    if cmd == "night":
        if prev.get("night_day") == day_of(now) and prev.get("version") == VERSION:
            return 0
    elif cmd == "once" and "--force" not in argv:
        if prev.get("version") == VERSION and now - int(prev.get("ts") or 0) < MIN_GAP_S:
            print(f"{PREFIX}zadnji izračun prije {(now - int(prev['ts'])) / 60:.0f} min, preskačem (MIN_GAP_S)", flush=True)
            return 0
    res = run(now, p, mode=cmd if cmd in BUDGET_S else "once", follow="--no-follow" not in argv)
    res["night_day"] = day_of(now) if cmd == "night" else prev.get("night_day")
    _write(out_path, res)
    return 0


def read(path=None):
    """The last output; {"error"} when there is none yet."""
    d = _load_prev(path or paths()["out"])
    if not d:
        return {"error": "zadnjih 5 još nije izračunat (prvi izračun ~5 min nakon starta)"}
    return d


def mcp(kind=None, top=None, path=None):
    """MCP get_last5: the last output, one type when asked, the top list cut to `top` rows (default 20)."""
    d = read(path)
    if "error" in d:
        return d
    try:
        n = max(0, min(TOP_N, int(top))) if top not in (None, "") else 20
    except (TypeError, ValueError):
        return {"error": "top: cijeli broj 0-50"}
    if kind not in (None, "", "kol", "wallet"):
        return {"error": "type: kol ili wallet"}
    out = {k: v for k, v in d.items() if k not in ("types", "log")}
    out["types"] = {}
    for k, r in (d.get("types") or {}).items():
        if kind and k != kind:
            continue
        r = dict(r)
        r["top"] = (r.get("top") or [])[:n]
        r.pop("qualifying_now", None)
        out["types"][k] = r
    out["log"] = d.get("log") or []
    return out


if __name__ == "__main__":
    sys.exit(main())
