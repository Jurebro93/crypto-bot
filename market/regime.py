"""Market regime: is the trench market hot or cold right now, as one 0-100 number the scoring can use.

score = mean of three percentile ranks over the last 90 days:
  - launchpad volume, last 7 days (pump.fun, LaunchLab/bonk.fun, Meteora DBC…)
  - whole Solana DEX volume, last 7 days
  - launchpad growth, last 7 days vs the 7 days before
>= 66 "vruće", <= 33 "hladno", otherwise "neutralno". Needs about 6 weeks of daily history
(30 days of 7-day sums), the first collect downloads 400 days.

For scoring/learning: at(ts)["score"] / 100 is the feature "market_regime" for anything that happened at ts
(it uses the last complete UTC day before ts, so there is no look-ahead).
"""
import json
import math
import time

from market import store

D = 86400
WINDOW = 90
HOT, COLD = 66, 33
KEYS = ("all:launchpad", "all:dex", "all:terminal")


def _sums7(ser):
    """{day: sum of the 7 days ending on day} for days with a full week behind them."""
    days = sorted(ser)
    out = {}
    for d in days:
        w = [ser.get(d - i * D) for i in range(7)]
        if all(v is not None for v in w):
            out[d] = sum(w)
    return out


def _pct(x, vals):
    """Share of vals at or below x (0-1)."""
    vals = [v for v in vals if v is not None]
    return sum(1 for v in vals if v <= x) / len(vals) if vals else None


def label(score):
    if score is None:
        return None
    return "vruće" if score >= HOT else "hladno" if score <= COLD else "neutralno"


def _load(con):
    ser = {k: dict(store.series(con, k)) for k in KEYS}
    # for the hypothesis: Solana DEX without PumpSwap (graduated pump.fun tokens), so trench volume is not on both sides
    ps = dict(store.series(con, "pumpswap"))
    ser["dex_ex"] = {d: v - ps.get(d, 0) for d, v in ser["all:dex"].items()}
    price = dict(con.execute("SELECT day, usd FROM price"))
    return ser, price, {k: _sums7(v) for k, v in ser.items()}


def compute(con, day=None, _cache=None):
    """Features and score for one day (default: the newest stored day). None without enough history."""
    ser, price, s7 = _cache or _load(con)
    days = sorted(s7["all:launchpad"])
    if not days:
        return None
    day = day or days[-1]
    if day not in s7["all:launchpad"] or day not in s7["all:dex"]:
        return None
    lo = day - (WINDOW - 1) * D
    f = {"day": day}
    for k in KEYS:
        name = k.split(":")[1]
        v7, p7 = s7[k].get(day), s7[k].get(day - 7 * D)
        f[f"{name}_7d"] = v7
        f[f"{name}_prev7d"] = p7
        f[f"{name}_growth7d"] = (v7 / p7 - 1) if v7 is not None and p7 else None
        hist = [v for d, v in s7[k].items() if lo <= d <= day]
        f[f"{name}_pct90"] = _pct(v7, hist) if v7 is not None and len(hist) >= 30 else None
    growth = {d: s7["all:launchpad"][d] / s7["all:launchpad"][d - 7 * D] - 1
              for d in s7["all:launchpad"] if lo <= d <= day and s7["all:launchpad"].get(d - 7 * D)}
    g = f["launchpad_growth7d"]
    f["launchpad_growth_pct90"] = _pct(g, growth.values()) if g is not None and len(growth) >= 30 else None
    f["launchpad_share"] = f["launchpad_7d"] / f["dex_7d"] if f["dex_7d"] else None
    p0, p7 = price.get(day), price.get(day - 7 * D)
    f["sol_price"] = p0
    f["sol_price_7d"] = (p0 / p7 - 1) if p0 and p7 else None
    parts = [f["launchpad_pct90"], f["dex_pct90"], f["launchpad_growth_pct90"]]
    if any(p is None for p in parts):
        return None
    score = round(100 * sum(parts) / 3, 1)
    return {"day": day, "score": score, "label": label(score), "features": f}


def compute_all(con, now=None):
    """(Re)compute and store the regime for every stored day that has enough history. Returns rows written."""
    cache = _load(con)
    n = 0
    for day in sorted(cache[0]["all:launchpad"]):
        r = compute(con, day, cache)
        if r:
            con.execute("INSERT OR REPLACE INTO regime VALUES (?,?,?,?,?)",
                        (day, r["score"], r["label"], json.dumps(r["features"]), int(now or time.time())))
            n += 1
    return n


def _row(r):
    return {"day": r[0], "score": r[1], "label": r[2], "features": json.loads(r[3] or "{}")} if r else None


def at(ts, con=None):
    """Regime that was known at time ts: the last complete UTC day before ts. None if market.db has none."""
    own = con is None
    con = con or store.ro()
    if con is None:
        return None
    try:
        r = con.execute("SELECT day, score, label, features FROM regime WHERE day<=? ORDER BY day DESC LIMIT 1",
                        (int(ts) // D * D - D,)).fetchone()
    except Exception:
        r = None
    finally:
        if own:
            con.close()
    return _row(r)


def current(con=None):
    """The newest regime (yesterday's, UTC)."""
    return at(time.time() + D, con)


def feature(ts=None):
    """market_regime in 0-1 for the scoring; None when unknown (score then simply ignores it)."""
    r = at(ts or time.time())
    return None if r is None else r["score"] / 100


# --- the hypothesis: when Solana volume rises, do the trenches trade more? -------------------------------

def _corr(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return None if not sx or not sy else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def _changes(ser, days):
    """{day: log change vs previous day}."""
    return {d: math.log(ser[d] / ser[d - D]) for d in days if ser.get(d) and ser.get(d - D)}


def hypothesis(con, days=WINDOW):
    """Correlations between daily changes, over the last `days` days:
    same_day: SOL DEX volume vs launchpad volume; lead1: SOL DEX today vs launchpad tomorrow;
    price: SOL price vs launchpad volume; week_agree: share of days where the 7-day growth of both has the same sign."""
    ser, price, s7 = _load(con)
    lp, dx = ser["all:launchpad"], ser["dex_ex"]
    if not lp:
        return None
    end = max(lp)
    rng = [end - i * D for i in range(days - 1, -1, -1)]
    cl, cd, cp = _changes(lp, rng), _changes(dx, rng), _changes(price, rng)
    both = [d for d in rng if d in cl and d in cd]
    lead = [d for d in rng if d in cd and d + D in cl]
    pr = [d for d in rng if d in cl and d in cp]
    s7l, s7d = s7["all:launchpad"], s7["dex_ex"]
    agree = [d for d in rng if s7l.get(d) and s7l.get(d - 7 * D) and s7d.get(d) and s7d.get(d - 7 * D)]
    same = [d for d in agree if (s7l[d] > s7l[d - 7 * D]) == (s7d[d] > s7d[d - 7 * D])]
    return {"days": len(both), "same_day": _corr([cd[d] for d in both], [cl[d] for d in both]),
            "lead1": _corr([cd[d] for d in lead], [cl[d + D] for d in lead]),
            "price": _corr([cp[d] for d in pr], [cl[d] for d in pr]),
            "week_agree": len(same) / len(agree) if len(agree) >= 10 else None, "week_days": len(agree)}


def verdict(h):
    """Plain-Croatian reading of hypothesis()."""
    if not h or h["same_day"] is None:
        return "Još nema dovoljno dana podataka za provjeru."
    c = h["same_day"]
    s = ("jako" if abs(c) >= 0.6 else "umjereno" if abs(c) >= 0.3 else "slabo") + (" zajedno" if c > 0 else " suprotno")
    out = f"U zadnjih {h['days']} dana dnevne promjene volumena na Solani i u trenchevima idu {s} (korelacija {c:+.2f})."
    if h["week_agree"] is not None:
        out += f" Tjedni trend (rast ili pad) im se poklapa {h['week_agree']:.0%} dana."
    if h["lead1"] is not None:
        out += (" Rast Solane danas malo najavljuje rast trencheva sutra" if h["lead1"] >= 0.2 else
                " Rast Solane danas ne najavljuje trencheve sutra") + f" ({h['lead1']:+.2f})."
    return out
