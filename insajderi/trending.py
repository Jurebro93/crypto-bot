"""Entering trending (15.11. extension): what preceded a token entering the DexScreener / GeckoTerminal trending lists,
so we see it earlier; the "uskoro trending" score with a walk-forward check. No API: midcap.db only.

  log       every pass: the members of midcap.db the collector sees on a trending / promoted list (tokens.trend set)
            -> i2_trend (first_ts = the first pass that saw it there). midcap.db keeps no history of the lists, so the
            log starts with this tool; before it only the tokens that were members first and trended later count
  features  per member token and hour (the last snap of the hour): volume acceleration v1h / (v24 / 24), buyers
            b1h and their acceleration b1h / (b24 / 24), buy share b1h / (b1h + s1h), price change c1h, liquidity / MC
  label     not trending at that hour, entered trending within trend_h (6 h) after it
  score     sum of z-scored features weighted by their standardized difference (positives minus the rest) on the
            OLDER 2/3 of the days; checked on the newer 1/3: precision of the top `trend_top` hours against the base rate
"""
import json
import math
import sqlite3
from collections import defaultdict

from insajderi import store

FEATURES = ("vacc", "b1h", "bacc", "bshare", "c1h", "liq_mc")
TREND_SRC = ("dex_boost_top", "dex_boost", "dex_profile", "dex_cto", "gt_trend")


def log_entries(con, p, now):
    """Record the tokens on a trending list now. Returns the number of new entries."""
    mc = store.ro(p.get("midcap_db"))
    rows = store.q(mc, "SELECT mint, symbol, trend, src, first_ts FROM tokens WHERE trend IS NOT NULL")
    if mc is not None:
        mc.close()
    n = 0
    for mint, sym, rank, src, _fts in rows:
        cur = con.execute("SELECT first_ts, best_rank FROM i2_trend WHERE mint = ?", (mint,)).fetchone()
        if cur:
            con.execute("UPDATE i2_trend SET last_ts = ?, best_rank = MIN(COALESCE(best_rank, 9999), ?) WHERE mint = ?",
                        (int(now), rank, mint))
            continue
        try:
            keys = [k for k in json.loads(src or "{}") if k in TREND_SRC]
        except ValueError:
            keys = []
        con.execute("INSERT INTO i2_trend VALUES (?,?,?,?,?,?)", (mint, sym, int(now), int(now), rank, ",".join(keys)))
        n += 1
    con.commit()
    return n


class _F:
    """The features of one token-hour: f[name] like the dict it replaces (23.11.: ~270k token-hours of 14 days of
    midcap.db were 270k dicts next to the 270k fetched rows; the night pass's stage c was killed at 911 MB)."""
    __slots__ = FEATURES

    def __init__(self, *v):
        for k, x in zip(FEATURES, v):
            setattr(self, k, x)

    def __getitem__(self, k):
        try:
            return getattr(self, k)
        except AttributeError:
            raise KeyError(k) from None


def hourly(p, since):
    """{mint: [(hour ts, features)]} from midcap.db snap (the last snap of each hour). 23.11.: the rows are read one
    at a time (no fetchall) and the features are a slotted _F, not a dict (the same numbers)."""
    mc = store.ro(p.get("midcap_db"))
    if mc is None:
        return {}
    out = defaultdict(list)
    try:
        ids = dict(store.q(mc, "SELECT id, mint FROM tokens"))
        cur = mc.execute("""SELECT id, ts / 3600, MAX(ts), mc, liq, v1h, v24, b1h, s1h, b24, c1h FROM snap WHERE ts >= ?
            GROUP BY id, ts / 3600""", (int(since),))
        for i, h, _ts, mcap, liq, v1h, v24, b1h, s1h, b24, c1h in cur:
            m = ids.get(i)
            if not m:
                continue
            f = _F((v1h or 0) / ((v24 or 0) / 24) if v24 else 0.0, float(b1h or 0),
                   (b1h or 0) / ((b24 or 0) / 24) if b24 else 0.0,
                   (b1h or 0) / ((b1h or 0) + (s1h or 0)) if (b1h or s1h) else 0.5,
                   float(c1h or 0), (liq or 0) / mcap if mcap else 0.0)
            out[m].append((int(h) * 3600, f))
    except sqlite3.Error:   # as store.q: an unreadable midcap.db is no data
        return {}
    finally:
        mc.close()
    for m in out:
        out[m].sort(key=lambda x: x[0])
    return out


def samples(series, entries, trend_h):
    """[(ts, features, label)]: hours before a token's first trending entry (or all hours of a token never seen
    trending); label 1 when the entry comes within trend_h hours."""
    out = []
    for m, xs in series.items():
        ent = entries.get(m)
        for ts, f in xs:
            if ent is not None and ts >= ent:
                break
            out.append((ts, f, int(ent is not None and ent - ts <= trend_h * 3600)))
    return out


def fit(train):
    """{feature: (mean, sd, weight)}: z-scoring on the training rows, weight = standardized difference of the means."""
    w = {}
    for k in FEATURES:
        xs = [_squash(f[k]) for _ts, f, _y in train]
        if len(xs) < 2:
            continue
        m = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) or 1.0
        pos = [_squash(f[k]) for _ts, f, y in train if y]
        neg = [_squash(f[k]) for _ts, f, y in train if not y]
        if not pos or not neg:
            continue
        w[k] = (m, sd, (sum(pos) / len(pos) - sum(neg) / len(neg)) / sd)
    return w


def _squash(x):
    return math.copysign(math.log1p(abs(x)), x)


def score(f, w):
    return sum(wt * (_squash(f[k]) - m) / sd for k, (m, sd, wt) in w.items())


def run(con, p, c, now):
    """The log, the walk-forward of the score and the current "uskoro trending" list -> summary dict."""
    new = log_entries(con, p, now)
    entries = {m: ts for m, ts in store.q(con, "SELECT mint, first_ts FROM i2_trend")}
    series = hourly(p, now - int(c["mkt_days"]) * 86400)
    sm = samples(series, entries, float(c["trend_h"]))
    out = {"entries": len(entries), "new": new, "n_train": 0, "n_test": 0, "top": int(c["trend_top"]),
           "precision_pct": None, "base_pct": None, "weights": {}, "soon": []}
    if not sm:
        return out
    days = sorted({ts // 86400 for ts, _f, _y in sm})
    cut = days[int(len(days) * 2 / 3)] * 86400 if len(days) >= 3 else None
    train = [x for x in sm if cut is None or x[0] < cut]
    test = [x for x in sm if cut is not None and x[0] >= cut]
    w = fit(train)
    out.update(n_train=len(train), n_test=len(test), weights={k: round(v[2], 3) for k, v in w.items()},
               pos_train=sum(y for _t, _f, y in train), pos_test=sum(y for _t, _f, y in test))
    if test and w:
        ranked = sorted(test, key=lambda x: -score(x[1], w))
        top = ranked[:int(c["trend_top"])]
        out["precision_pct"] = round(100 * sum(y for _t, _f, y in top) / len(top), 1)
        out["base_pct"] = round(100 * sum(y for _t, _f, y in test) / len(test), 2)
    if w:   # the current list: the newest hour of every member not trending yet
        cur = [(m, xs[-1]) for m, xs in series.items() if xs and m not in entries and xs[-1][0] >= now - 2 * 3600]
        out["soon"] = [{"token": m, "score": round(score(f, w), 2), **{k: round(f[k], 3) for k in FEATURES}}
                       for m, (_ts, f) in sorted(cur, key=lambda x: -score(x[1][1], w))[:10]]
    return out
