"""Statistics over the replayed events: per delay and exit, per wallet, and the out-of-sample test (choose wallets
on the older half, judge them on the newer half). Pure functions on lists, so the page and the tests share them."""
import json
import math
import random
import statistics

from kolcopy import replay

EXITS = ("mirror", "h1", "h6", "h24")


def summarize(vals, boot=1000, seed=7):
    """n, mean, median, win share, mean without the best 1% (at least the best one from 10 trades), 90% interval of
    the mean: bootstrap up to 300 trades, normal approximation above (same answer there, and the page stays fast).
    None for an empty list."""
    v = [x for x in vals if isinstance(x, (int, float))]
    if not v:
        return None
    n = len(v)
    k = max(1, n // 100) if n >= 10 else 0
    trimmed = sorted(v)[:n - k] if k else v
    lo = hi = None
    if n > 300 and boot:
        half = 1.645 * statistics.stdev(v) / math.sqrt(n)
        lo, hi = sum(v) / n - half, sum(v) / n + half
    elif n >= 5 and boot:
        rnd = random.Random(seed)
        means = sorted(sum(rnd.choices(v, k=n)) / n for _ in range(boot))
        lo, hi = means[int(0.05 * boot)], means[min(boot - 1, int(0.95 * boot))]
    return {"n": n, "mean": sum(v) / n, "median": statistics.median(v), "win": sum(x > 0 for x in v) / n,
            "trim": sum(trimmed) / len(trimmed), "lo": lo, "hi": hi}


def verdict(s, min_n=30):
    if not s or s["n"] < min_n or s["lo"] is None:
        return "premalo podataka"
    if s["lo"] > 0:
        return "u plusu"
    if s["hi"] < 0:
        return "u minusu"
    return "nejasno"


def rets(events, cfg, now=None):
    """[(event, {delay: {exit: net}})] for events not skipped."""
    out = []
    for ev in events:
        if ev["status"] == "skip":
            continue
        out.append((ev, replay.returns(ev, cfg, now)))
    return out


def by_delay(rs, cfg):
    """{(delay, exit): summary} plus how many copies were skipped because the KOL sold before our entry."""
    out, skips = {}, {}
    for d in [0] + list(cfg["delays_s"]):
        for x in EXITS:
            vals = [r[d][x] for _, r in rs if d in r and x in r[d]]
            skips[(d, x)] = sum(v == "skip" for v in vals)
            out[(d, x)] = summarize(vals, cfg.get("boot", 1000))
    return out, skips


def per_wallet(rs, cfg, delay, exit_="mirror"):
    """{wallet: summary + hold_min (median KOL hold) + tokens}"""
    vals, holds = {}, {}
    for ev, r in rs:
        v = r.get(delay, {}).get(exit_)
        if isinstance(v, (int, float)):
            vals.setdefault(ev["wallet"], []).append(v)
        if ev["sell_ts"]:
            holds.setdefault(ev["wallet"], []).append((ev["sell_ts"] - ev["t0"]) / 60)
    out = {}
    for w, v in vals.items():
        s = summarize(v, boot=0)
        s["hold_min"] = statistics.median(holds[w]) if holds.get(w) else None
        out[w] = s
    return out


def oos(rs, cfg, delay, exit_="mirror"):
    """Can we pick the good wallets in advance? Split the events with a known result at the median t0; wallets with
    at least min_first results in the older half and a positive mean there, best `top` of them; their results in the
    newer half against all wallets in the newer half."""
    rows = sorted(((ev["t0"], ev["wallet"], r[delay][exit_]) for ev, r in rs
                   if isinstance(r.get(delay, {}).get(exit_), (int, float))), key=lambda x: x[0])
    if len(rows) < 10:
        return None
    split = rows[len(rows) // 2][0]
    first, second = [x for x in rows if x[0] < split], [x for x in rows if x[0] >= split]
    by = {}
    for _, w, v in first:
        by.setdefault(w, []).append(v)
    o = cfg.get("oos") or {}
    ranked = sorted(((sum(v) / len(v), w) for w, v in by.items() if len(v) >= o.get("min_first", 3)), reverse=True)
    picked = [w for m, w in ranked if m > 0][:o.get("top", 10)]
    boot = cfg.get("boot", 1000)
    return {"split": split, "picked": picked,
            "picked_first": summarize([v for _, w, v in first if w in picked], boot),
            "picked_second": summarize([v for _, w, v in second if w in picked], boot),
            "all_second": summarize([v for _, _, v in second], boot)}


def load(con):
    evs = []
    for r in con.execute("SELECT * FROM events ORDER BY t0"):
        e = dict(r)
        e["points"] = json.loads(e["points"] or "{}")
        evs.append(e)
    return evs


def fmt_pct(x):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.1%}"
