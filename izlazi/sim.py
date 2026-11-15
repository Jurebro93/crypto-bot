"""The exit of one entry on its price path, for every rule of the grid (15.11., owner: "nauči iz podataka najbolji
mogući stop loss i najbolji take profit, po izvoru ... možda širi stop loss i čekati duže").

A PATH is one entry we would have taken: bars after our entry at price 1.0, (end of the bar in seconds after the entry,
high, low, close) as multiples of the entry price (the high is kol/minute's capped wick), up to HORIZON_S (24 h), the
pool's round-trip cost of our stake (a fraction, never 0: izlazi/data takes it from trade/cost and rangedca/rules), the
moment the source itself sold (for the mirror rule: its sale + our lag) and the moment a rug flag was raised (hype.db
rug_archive, the pool's liquidity under half of the entry's).

A RULE (Params):
  sl      the stop, % under the entry (SLS)
  grace   minutes after the entry in which only the catastrophic stop (CAT_STOP, -50 %) and the rug flags apply
          (GRACES; 0 = the stop from the first second). After the grace the stop is checked again at once: a price
          already under it sells at that price.
  tp1     the first take profit, % NET of the round trip (the trigger is the entry x (1 + tp1 + cost), as
          league/exitplan.quick_plan), selling `share` of the position (SHARES)
  trail   after TP1 (share < 1): the rest's stop is break-even (entry + cost, league/exitplan.breakeven) and, with
          trail > 0, a trailing stop trail % under the peak since TP1 (TRAILS; 0 = break-even only)
  tmax    the time stop, minutes after the entry: everything still held is sold at the close (TMAXS; 1440 = the
          horizon, i.e. none within the data)
  mirror  1 = sell what is left when the source sells (copies of wallets); 0 = ignore its sale
DEFAULT is today's rule (league/exitplan "brzi profit", PR #172): stop -20 %, no grace, half at +12 % net, break-even +
trailing 10 %, no time stop, the mirror sale on top.

Fills (pessimistic, never better than the level): a stop / break-even / trailing fills at min(level, the previous
close) x (1 - slip_stop) (a gap under the level sells at the price there; the owner measured ~5 % slip over the
trigger on 12./13.11., izlazi/data reads trade.db exit_fills); a take profit, the time stop and the mirror sale at the
level / close x (1 - slip_mkt). A stop and a take profit in the same bar: the stop. The rug flag sells at the bar's
close x (1 - slip_stop). A path that ends before the rule's time stop is sold at its last close (incomplete; izlazi/learn
only offers a time stop most of a source's paths cover).

Prep precomputes, once per path, the record lows from the start and from every grace end, the record highs and the
first bar at every time, so one rule is a few bisects (the grid runs inside the night window on a CPU-limited box); the
rest after TP1 is simulated once per (TP1 bar, trailing) and cached. evaluate() is the same arithmetic written plainly
(the tests check both agree).
"""
import array
import bisect
import collections
import math

SLS = (10, 15, 20, 25, 30, 40, 50)
GRACES = (0, 5, 15, 30, 60)
TP1S = (8, 12, 15, 20, 30, 50)
SHARES = (0.5, 1.0)
TRAILS = (0, 10, 15, 20)
TMAXS = (45, 120, 360, 1440)
MIRRORS = (0, 1)
CAT_STOP = 50.0                # % under the entry: the only stop inside the grace (with the rug flags)
HORIZON_S = 24 * 3600
BE_MIN_GAP = 0.005             # league/exitplan.BE_MIN_GAP: break-even never at / over the TP1 price
SLIP_STOP = 0.05               # stop / trailing fill under the level (the owner's 13.11. measurement) unless measured
SLIP_MKT = 0.01                # take profit, time stop, mirror sale
TOL_S = 15 * 60                # a path that ends this much before a time stop still counts as covering it
MAX_BARS = 240                 # a path is thinned (tol doubled) until it has at most this many bars (memory: ~6 KB)
# bar boundaries kept exact when a path is thinned (the grace ends and the time stops)
BOUNDS_S = tuple(sorted({g * 60 for g in GRACES if g} | {t * 60 for t in TMAXS}))

Params = collections.namedtuple("Params", "sl grace tp1 share trail tmax mirror")
DEFAULT = Params(20, 0, 12, 0.5, 10, 1440, 1)
DIMS = ("sl", "grace", "tp1", "share", "trail", "tmax", "mirror")
VALUES = {"sl": SLS, "grace": GRACES, "tp1": TP1S, "share": SHARES, "trail": TRAILS, "tmax": TMAXS, "mirror": MIRRORS}


def canon(p, mirror_ok=True):
    """The rule in its one spelling: a whole-position TP1 has no rest (trail 0); a source that never sells has no
    mirror rule (0)."""
    p = Params(*p)
    if p.share >= 0.999:
        p = p._replace(share=1.0, trail=0)
    if not mirror_ok:
        p = p._replace(mirror=0)
    return p


def complexity(p, hold=1440):
    """How many moving parts a rule has (the simplest rule within one standard error of the best is taken); hold =
    the longest time stop the data can judge (holding that long is no time stop)."""
    return int(p.grace > 0) + int(p.share < 0.999) + int(p.trail > 0) + int(p.tmax < hold)


def as_dict(p):
    p = Params(*p)
    return {"sl": p.sl, "grace": p.grace, "tp1": p.tp1, "share": p.share, "trail": p.trail, "tmax": p.tmax,
            "mirror": bool(p.mirror)}


def from_dict(d):
    d = d or {}
    return Params(float(d.get("sl", DEFAULT.sl)), float(d.get("grace", 0)), float(d.get("tp1", DEFAULT.tp1)),
                  float(d.get("share", DEFAULT.share)), float(d.get("trail") or 0), float(d.get("tmax", 1440)),
                  int(bool(d.get("mirror", True))))


def words(p, cost_pct=None):
    """'SL −25 %, grace 15 min (samo −50 % / rug), TP1 +15 % neto (50 %), ostatak BE + trailing 10 %, vrijeme 6 h,
    prodaj kad on proda' (Croatian, for the log and the pages)."""
    p = Params(*p)
    out = [f"SL −{p.sl:g} %"]
    if p.grace:
        out.append(f"grace {p.grace:g} min (samo −{CAT_STOP:g} % / rug)")
    share = "sve" if p.share >= 0.999 else f"{p.share:.0%}".replace("%", " %")
    out.append(f"TP1 +{p.tp1:g} % neto ({share})")
    if p.share < 0.999:
        out.append("ostatak BE" + (f" + trailing {p.trail:g} %" if p.trail else ""))
    if p.tmax < 1440:
        out.append(f"vrijeme {p.tmax / 60:g} h" if p.tmax >= 60 else f"vrijeme {p.tmax:g} min")
    out.append("prodaj kad on proda" if p.mirror else "bez mirrora")
    return ", ".join(out).replace(".", ",") if cost_pct is None else ", ".join(out)


# ---------- the path --------------------------------------------------------------------------------------------------

def bars_from_candles(candles, t_entry, horizon_s=HORIZON_S, wick=3.0, max_wait=300):
    """(entry price, path start unix s, [(dt_end, hi, lo, close)] as multiples of the entry) of an entry at t_entry on
    1-minute candles [(t, o, h, l, c, ...)] sorted by time (kol/zadnjih5._entry's rule: the close of the minute holding
    t_entry, else the open of the first candle within max_wait after it); None without an entry."""
    from kol import zadnjih5
    e = zadnjih5._entry(candles, t_entry, max_wait)
    if not e:
        return None
    entry, t0, j = e
    out = []
    for c in candles[j:]:
        dt = c[0] + 60 - t0
        if dt <= 0:
            continue
        if dt > horizon_s:
            break
        hi = zadnjih5._capped(c, wick)
        lo, cl = c[3], c[4]
        if not (hi and lo and cl) or hi <= 0 or lo <= 0 or cl <= 0:
            continue
        out.append((int(dt), hi / entry, lo / entry, cl / entry))
    return entry, t0, out


def thin(bars, tol=0.01, bounds=BOUNDS_S):
    """Fewer bars for the same exits: consecutive bars that stay within tol of the last kept close are merged into
    one (their high, their low, the last close, the last end); never across a grace end or a time stop (bounds), and a
    bar that sets a new high or low since the entry is always its own. The error on any level crossing is under tol."""
    out = []
    pend = None
    ref, hi_all, lo_all = 1.0, 1.0, 1.0
    for b in bars:
        t, h, lo, c = b
        crosses = pend is not None and any(pend[0] < x <= t for x in bounds) if bounds else False
        new_ext = h > hi_all or lo < lo_all
        far = h >= ref * (1 + tol) or lo <= ref * (1 - tol)
        if pend is not None and (crosses or new_ext or far):
            out.append(tuple(pend))
            ref = pend[3]
            pend = None
            far = h >= ref * (1 + tol) or lo <= ref * (1 - tol)
        if pend is None:
            pend = [t, h, lo, c]
        else:
            pend = [t, max(pend[1], h), min(pend[2], lo), c]
        hi_all, lo_all = max(hi_all, h), min(lo_all, lo)
        if new_ext or far:
            out.append(tuple(pend))
            ref = c
            pend = None
    if pend is not None:
        out.append(tuple(pend))
    return out


def fit(bars, max_bars=MAX_BARS, tol=0.01):
    """thin() with tol doubled until the path has at most max_bars bars (a quiet path keeps every move over 1 %)."""
    out = thin(bars, tol)
    while len(out) > max_bars and tol < 0.3:
        tol *= 2
        out = thin(bars, tol)
    while len(out) > max_bars:   # still too long: merge neighbours pairwise (never across the last bar)
        out = [(b[0], max(a[1], b[1]), min(a[2], b[2]), b[3]) for a, b in zip(out[0::2], out[1::2])] + (
            [out[-1]] if len(out) % 2 else [])
    return out


def pack(bars):
    """(T, H, L, C) compact arrays of a path (int32 seconds, float32 multiples): what izlazi/data keeps in memory."""
    return (array.array("i", (int(b[0]) for b in bars)), array.array("f", (b[1] for b in bars)),
            array.array("f", (b[2] for b in bars)), array.array("f", (b[3] for b in bars)))


def unpack(arrs):
    T, H, L, C = arrs
    return list(zip(T, H, L, C))


def path_stats(bars, win_mfe=0.20):
    """{mfe, mae, mae_before_peak, t_peak_min, recover_min, winner} of one path (fractions; minutes).
    winner = the path reached +win_mfe; mae_before_peak = the deepest low before the highest high (how deep a winner
    dips first); recover_min = from that low back to the entry price (None when it never came back before the peak)."""
    if not bars:
        return None
    ip = max(range(len(bars)), key=lambda i: bars[i][1])
    mfe = bars[ip][1] - 1
    lows = [b[2] for b in bars]
    mae = min(lows) - 1
    im = min(range(ip + 1), key=lambda i: bars[i][2])
    mbp = min(0.0, bars[im][2] - 1)
    rec = None
    if mbp < 0:
        for j in range(im + 1, len(bars)):
            if bars[j][3] >= 1.0 or bars[j][1] >= 1.0:
                rec = (bars[j][0] - bars[im][0]) / 60
                break
    return {"mfe": mfe, "mae": mae, "mae_before_peak": mbp, "t_peak_min": bars[ip][0] / 60, "recover_min": rec,
            "winner": mfe >= win_mfe}


# ---------- the rule on one path -------------------------------------------------------------------------------------

def _first_at(times, t):
    """Index of the first bar ending at or after t, or None."""
    if t is None:
        return None
    i = bisect.bisect_left(times, t)
    return i if i < len(times) else None


class Prep:
    """One path ready for many rules (see the module text). cost: the round trip (fraction); sell_s: seconds after
    the entry the mirror sale happens (the source's sale + our lag), None when it did not sell within the path;
    rug_s: seconds after the entry of the first rug flag, None."""

    __slots__ = ("T", "H", "L", "C", "S", "n", "cost", "sell_i", "rug_i", "cover", "slip_stop", "slip_mkt", "_rl",
                 "_rh", "_sg", "_rest", "_ti")

    def __init__(self, bars, cost, sell_s=None, rug_s=None, cover=None, slip_stop=SLIP_STOP, slip_mkt=SLIP_MKT):
        """bars: [(dt_end, hi, lo, close)] or pack()'s (T, H, L, C) arrays (shared, not copied)."""
        if isinstance(bars, tuple) and len(bars) == 4 and isinstance(bars[0], array.array):
            self.T, self.H, self.L, self.C = bars
        else:
            self.T, self.H, self.L, self.C = pack(bars)
        self.n = len(self.T)
        self.S = array.array("i", [0]) + self.T[:-1]          # the start of every bar
        self.cost = max(0.0, float(cost))
        self.cover = int(cover if cover is not None else (self.T[-1] if self.T else 0))
        self.sell_i = _first_at(self.T, sell_s) if sell_s is not None and sell_s >= 0 else None
        self.rug_i = _first_at(self.T, rug_s) if rug_s is not None and rug_s >= 0 else None
        self.slip_stop, self.slip_mkt = float(slip_stop), float(slip_mkt)
        self._sg = {}
        self._rl = {}
        for g in GRACES:
            s = bisect.bisect_left(self.S, g * 60)
            self._sg[g] = s
            if s not in self._rl:
                self._rl[s] = self._records_low(s)
        hs, ix, top = array.array("f"), array.array("i"), -math.inf
        for i, h in enumerate(self.H):
            if h > top:
                top = h
                hs.append(h)
                ix.append(i)
        self._rh = (hs, ix)
        self._rest = {}
        self._ti = {}

    def _records_low(self, s):
        nl, ix, low = array.array("f"), array.array("i"), math.inf
        for i in range(s, self.n):
            lo = self.L[i]
            if lo < low:
                low = lo
                nl.append(-lo)
                ix.append(i)
        return nl, ix

    def _sg_of(self, g):
        s = self._sg.get(g)
        if s is None:
            s = bisect.bisect_left(self.S, g * 60)
            self._sg[g] = s
        if s not in self._rl:
            self._rl[s] = self._records_low(s)
        return s

    def first_low(self, s, lvl):
        """First bar at index >= s whose low is at or under lvl, or None."""
        nl, ix = self._rl[s]
        k = bisect.bisect_left(nl, -lvl)
        return ix[k] if k < len(ix) else None

    def first_high(self, lvl):
        hs, ix = self._rh
        k = bisect.bisect_left(hs, lvl)
        return ix[k] if k < len(ix) else None

    def time_i(self, tmax_min):
        r = self._ti.get(tmax_min)
        if r is None and tmax_min not in self._ti:
            r = _first_at(self.T, tmax_min * 60) if tmax_min * 60 < HORIZON_S else None
            self._ti[tmax_min] = r
        return r

    def covers(self, tmax_min):
        return self.cover >= min(tmax_min * 60, HORIZON_S) - TOL_S

    def rest(self, k, trail, tp_lvl):
        """(bar, fill multiple) where the rest after TP1 at bar k leaves through break-even or the trailing, or
        (None, None) when it is still held at the end of the path."""
        key = (k, trail)
        hit = self._rest.get(key)
        if hit is not None:
            return hit
        be = 1 + self.cost
        if be >= tp_lvl * (1 - BE_MIN_GAP):
            be = tp_lvl * (1 - BE_MIN_GAP)
        peak = self.H[k]
        out = (None, None)
        tr = trail / 100 if trail else 0.0
        for j in range(k + 1, self.n):
            lvl = max(be, peak * (1 - tr)) if tr else be
            if self.L[j] <= lvl:
                out = (j, min(lvl, self.C[j - 1]) * (1 - self.slip_stop))
                break
            if self.H[j] > peak:
                peak = self.H[j]
        self._rest[key] = out
        return out

    def run(self, p):
        """(net result as a fraction of the stake after the round trip, why, the bar it ended in) of rule p."""
        if not self.n:
            return -self.cost, "prazno", None
        s_g = self._sg_of(p.grace)
        cat_lvl = 1 - CAT_STOP / 100
        stop_lvl = 1 - p.sl / 100
        tp_lvl = 1 + p.tp1 / 100 + self.cost
        best = None   # (bar, priority, why)
        ic = self.first_low(0, cat_lvl)
        if ic is not None and ic < s_g:
            best = (ic, 0, "cat")
        i_s = self.first_low(s_g, stop_lvl) if s_g < self.n else None
        if i_s is not None and (best is None or (i_s, 0) < best[:2]):
            best = (i_s, 0, "sl")
        for i, pr, why in ((self.rug_i, 0, "rug"), (self.sell_i if p.mirror else None, 1, "mirror"),
                           (self.time_i(p.tmax), 2, "time"), (self.first_high(tp_lvl), 3, "tp")):
            if i is not None and (best is None or (i, pr) < best[:2]):
                best = (i, pr, why)
        if best is None:
            return self.C[-1] * (1 - self.slip_mkt) - 1 - self.cost, "kraj", self.n - 1
        i, _pr, why = best
        if why in ("cat", "sl"):
            lvl = cat_lvl if why == "cat" else stop_lvl
            prev = self.C[i - 1] if i > 0 else 1.0
            return min(lvl, prev) * (1 - self.slip_stop) - 1 - self.cost, why, i
        if why == "rug":
            return self.C[i] * (1 - self.slip_stop) - 1 - self.cost, why, i
        if why in ("mirror", "time"):
            return self.C[i] * (1 - self.slip_mkt) - 1 - self.cost, why, i
        # TP1
        got = p.share * tp_lvl * (1 - self.slip_mkt)
        if p.share >= 0.999:
            return got - 1 - self.cost, "tp", i
        left = 1 - p.share
        j, fill = self.rest(i, p.trail, tp_lvl)
        best2 = (j, 0, "be_trail") if j is not None else None
        for k2, pr, w in ((self.rug_i, 0, "rug"), (self.sell_i if p.mirror else None, 1, "mirror"),
                          (self.time_i(p.tmax), 2, "time")):
            if k2 is not None and k2 > i and (best2 is None or (k2, pr) < best2[:2]):
                best2 = (k2, pr, w)
        if best2 is None:
            return got + left * self.C[-1] * (1 - self.slip_mkt) - 1 - self.cost, "tp+kraj", self.n - 1
        j2, _pr, w = best2
        if w == "be_trail":
            v = fill
        elif w == "rug":
            v = self.C[j2] * (1 - self.slip_stop)
        else:
            v = self.C[j2] * (1 - self.slip_mkt)
        return got + left * v - 1 - self.cost, "tp+" + w, j2

    def net(self, p):
        return self.run(p)[0]


def evaluate(bars, p, cost, sell_s=None, rug_s=None, slip_stop=SLIP_STOP, slip_mkt=SLIP_MKT):
    """The same rule written plainly, bar by bar (the reference Prep.run is checked against): net fraction."""
    cat_lvl = 1 - CAT_STOP / 100
    stop_lvl = 1 - p.sl / 100
    tp_lvl = 1 + p.tp1 / 100 + cost
    be = min(1 + cost, tp_lvl * (1 - BE_MIN_GAP))
    left, got, stage, peak, prev = 1.0, 0.0, 0, None, 1.0
    for i, (t, h, lo, c) in enumerate(bars):
        start = bars[i - 1][0] if i else 0
        rug = rug_s is not None and t >= rug_s
        mir = p.mirror and sell_s is not None and t >= sell_s
        tim = p.tmax * 60 < HORIZON_S and t >= p.tmax * 60
        if stage == 0:
            lvl = stop_lvl if start >= p.grace * 60 else cat_lvl
            if lo <= lvl:
                return min(lvl, prev) * (1 - slip_stop) - 1 - cost
            if rug:
                return c * (1 - slip_stop) - 1 - cost
            if mir or tim:
                return c * (1 - slip_mkt) - 1 - cost
            if h >= tp_lvl:
                got = p.share * tp_lvl * (1 - slip_mkt)
                left = 1 - p.share
                if left <= 1e-9:
                    return got - 1 - cost
                stage, peak = 1, h
        else:
            lvl = max(be, peak * (1 - p.trail / 100)) if p.trail else be
            if lo <= lvl:
                return got + left * min(lvl, prev) * (1 - slip_stop) - 1 - cost
            if rug:
                return got + left * c * (1 - slip_stop) - 1 - cost
            if mir or tim:
                return got + left * c * (1 - slip_mkt) - 1 - cost
            peak = max(peak, h)
        prev = c
    last = bars[-1][3] if bars else 1.0
    return got + left * last * (1 - slip_mkt) - 1 - cost


# ---------- numbers over many results (pure) -------------------------------------------------------------------------

def mean(xs):
    return sum(xs) / len(xs) if xs else None


def sd(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def max_dd(rets):
    """The deepest fall of the running sum of results (in stakes), results in time order."""
    run, top, dd = 0.0, 0.0, 0.0
    for r in rets:
        run += r
        top = max(top, run)
        dd = max(dd, top - run)
    return dd


def quantile(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo = math.floor(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def bootstrap(xs, b=500, seed=7, alpha=0.10, ys=None):
    """The (alpha/2, 1 - alpha/2) percentile interval of the mean of xs (or of the paired mean xs - ys), resampled b
    times with a fixed seed (the same data gives the same interval)."""
    import random
    if not xs:
        return None, None
    d = [x - y for x, y in zip(xs, ys)] if ys is not None else list(xs)
    n = len(d)
    if n == 1:
        return d[0], d[0]
    rnd = random.Random(seed)
    ms = sorted(sum(d[rnd.randrange(n)] for _ in range(n)) / n for _ in range(b))
    return ms[int(alpha / 2 * (b - 1))], ms[int((1 - alpha / 2) * (b - 1))]
