"""Compact price paths for exit learning.

A path is one possible trade: entry at price 1.0 with the pool's liquidity, then [(seconds after entry, price as a
multiple of entry, liquidity USD), ...]. Points are thinned to the ones that matter for exits (every move of more
than `tol`, plus the running highs and lows), so thousands of paths fit in a few MB and replay fast.

Sources:
- seed: exits/seed_paths.json.gz, built once from the retrospective study (retro.db, 25k pump.fun tokens), shipped
  in git so the server needs no Helius credits for it;
- live: paper.db ticks of every candidate the bot tracked (taken or skipped), entry at its first tick.
"""
import gzip
import json
import math
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed_paths.json.gz")


def compress(points, tol=0.03, max_points=160):
    """points: [(dt, mult, liq)] sorted by dt. Keep a point when the price moved more than tol from the last kept
    one, when it sets a new high or low, and always the last; then cap the count, keeping extremes."""
    if not points:
        return []
    kept, last, hi, lo = [], None, -1.0, math.inf
    for i, (t, m, liq) in enumerate(points):
        if m is None:
            continue
        new_ext = m > hi or m < lo
        hi, lo = max(hi, m), min(lo, m)
        if last is None or new_ext or abs(m / last - 1) >= tol or m <= 0 or i == len(points) - 1:
            kept.append((int(t), round(float(m), 5), round(float(liq or 0))))
            last = m if m > 0 else 1e-12
    while len(kept) > max_points:  # drop every second non-extreme point until it fits
        prices = [k[1] for k in kept]
        top, bottom = prices.index(max(prices)), prices.index(min(prices))
        kept = [k for j, k in enumerate(kept) if j % 2 == 0 or j in (top, bottom, len(kept) - 1)]
    return kept


def make(src, klasa, ts, liq0, mcap0, points, tol=0.03, max_points=160, **extra):
    return {"src": src, "klasa": klasa, "ts": int(ts), "liq0": round(liq0 or 0), "mcap0": round(mcap0 or 0),
            "pts": compress(points, tol, max_points), **extra}


def peak(path):
    return max((m for _, m, _ in path["pts"]), default=1.0)


def load_seed(path=SEED):
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt") as f:
        return json.load(f)["paths"]


def save_seed(paths, meta, path=SEED):
    with gzip.open(path, "wt", compresslevel=9) as f:
        json.dump({"meta": meta, "paths": paths}, f, separators=(",", ":"))
    return path


def classify(mcap, age_h):
    """Same class bounds as the live bot (tiers/config.json)."""
    from tiers import classify as tc
    return tc.klasa(mcap, age_h)


def from_paper(paper_db, hype_db=None, since=0, tol=0.03, max_points=160):
    """Live paths: every tracked candidate (taken or skipped) from its first tick on. Class from token_tier."""
    if not os.path.exists(paper_db):
        return []
    con = sqlite3.connect(f"file:{paper_db}?mode=ro", uri=True, timeout=30)
    klase = {}
    if hype_db and os.path.exists(hype_db):
        try:
            h = sqlite3.connect(f"file:{hype_db}?mode=ro", uri=True, timeout=30)
            klase = dict(h.execute("SELECT token, klasa FROM token_tier WHERE klasa IS NOT NULL"))
            h.close()
        except sqlite3.OperationalError:
            klase = {}
    out = []
    try:
        cands = con.execute("SELECT token, first_ts, origin, price, liquidity, mcap FROM candidates "
                            "WHERE decision!='ignored' AND price>0 AND first_ts>=?", (since,)).fetchall()
        for token, ts, origin, price, liq, mcap in cands:
            rows = con.execute("SELECT ts, price, liquidity FROM ticks WHERE token=? AND ts>? ORDER BY ts",
                               (token, ts)).fetchall()
            if len(rows) < 5:
                continue
            pts = [(t - ts, (p or 0) / price, l or 0) for t, p, l in rows]
            k = "event" if origin == "event" else klase.get(token) or classify(mcap, None)
            out.append(make("live", k, ts, liq, mcap, pts, tol, max_points, token=token))
    finally:
        con.close()
    return out
