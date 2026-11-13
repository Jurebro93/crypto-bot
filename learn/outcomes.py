"""Outcomes for every token, the class-relative definition of a pump, and what the sieve missed."""
import json
import os
import time

from hype import evaluate
from tiers import classify

HERE = os.path.dirname(os.path.abspath(__file__))


def config():
    with open(os.path.join(HERE, "config.json")) as f:
        return json.load(f)


def _tiers(con):
    try:
        return {r[0]: {"klasa": r[1], "razina": r[2], "t0": r[3], "t0_razlog": r[4], "razlog": r[5], "mcap": r[6],
                       "first_ts": r[7], "symbol": r[8]}
                for r in con.execute("SELECT token, klasa, razina, t0, t0_razlog, razlog, mcap, first_ts, symbol FROM token_tier")}
    except Exception:
        return {}


def rows(con, cfg=None, now=None):
    """evaluate.outcomes plus klasa and a class-relative hit; tokens without a token_tier row get a class from mcap."""
    cfg = cfg or config()
    now = now or time.time()
    tiers = _tiers(con)
    out = evaluate.outcomes(con, cfg["horizon_h"], hit=1.0, now=now)
    mcaps = {r[0]: r[1] for r in con.execute(
        "SELECT s.token, s.mcap FROM hype_signals s JOIN (SELECT token, MIN(ts) ts FROM hype_signals GROUP BY token) f "
        "ON s.token=f.token AND s.ts=f.ts")}
    for r in out:
        t = tiers.get(r["token"]) or {}
        r["klasa"] = t.get("klasa") or classify.klasa(mcaps.get(r["token"]), None)
        r["razina"] = t.get("razina") or 0
    thr = skok_thresholds(out, cfg, now)
    for r in out:
        r["skok"] = thr[r["klasa"]]
        r["hit"] = r["max_ret"] >= thr[r["klasa"]]
    return out, thr


def shadow_rows(cfg=None, now=None, path=None):
    """Labelled shadow-book points (learn/shadow.py) in the shape fit.run expects: features as they were at the
    decision point, hit = the trade the bot could actually have taken (paper/sim replay with the class's exit rules)
    made at least shadow.hit_ret after costs. This is the target since 2.11.; the max price in 24 h after the first
    signal (rows()) is kept for the Učenje correlations and as a fallback while a class has too few points."""
    from learn import shadow
    cfg = cfg or config()
    now = now or time.time()
    since = now - cfg["skok_window_d"] * 86400
    from learn import champion
    hl = (cfg.get("model") or {}).get("half_life_d", champion.DEFAULT["half_life_d"])
    longs = shadow.long_targets(cfg)
    out = []
    for r in shadow.rows(path, since=since):
        if not r["features"] or champion.in_holdout(r["ts"]):
            continue
        w = 0.5 ** (max(0.0, now - r["ts"]) / 86400 / hl)
        if (r.get("klasa") or "default") in longs:   # 9.11.: long target (+30% in 72 h), see shadow.long_targets
            if r.get("hit_dug") not in (0, 1):
                continue   # not labelled yet, or no prices for the window: no verdict
            out.append({**r, "hit": bool(r["hit_dug"]), "max_ret": r["max_dug"], "w": w, "cilj_dug": True})
        else:
            out.append({**r, "hit": bool(r["hit"]), "max_ret": r["max2_ret"], "w": w})
    return out


def event_rows(con, point="B100000", cfg=None, now=None):
    """Outcomes judged from a decision point (tier_events: first time at/above $100k or $1M) instead of the first
    signal: features as they were then, max/2nd-max return over the horizon. The study's best entry was $100k."""
    from tiers import store as tstore
    cfg = cfg or config()
    now = now or time.time()
    out = []
    for e in tstore.events(con, point):
        if e["ts"] > now - cfg["horizon_h"] * 3600 or not e["price"]:
            continue
        snaps = con.execute("SELECT ts, price FROM hype_snapshots WHERE token=? AND ts>? AND ts<=? ORDER BY ts",
                            (e["token"], e["ts"], e["ts"] + cfg["horizon_h"] * 3600)).fetchall()
        path = [p / e["price"] - 1 for _, p in snaps if p]
        if not path:
            continue
        out.append({**e, "max_ret": max(path), "max2_ret": sorted(path)[-2] if len(path) >= 2 else max(path),
                    "end_ret": path[-1]})
    return out


def skok_thresholds(rows, cfg=None, now=None):
    """Per class: the (skok_pct)th percentile of max returns in the last skok_window_d days, else the initial value."""
    cfg = cfg or config()
    now = now or time.time()
    since = now - cfg["skok_window_d"] * 86400
    thr = dict(cfg["skok_init"])
    for k in thr:
        xs = sorted(r["max_ret"] for r in rows if r.get("klasa") == k and r["ts"] >= since)
        if len(xs) >= cfg["min_class_rows"]:
            thr[k] = round(max(0.1, xs[min(len(xs) - 1, int(len(xs) * cfg["skok_pct"] / 100))]), 3)
    return thr


def missed(con, thr, cfg=None, now=None, hours=7 * 24, excluded=None):
    """Tokens that never got a paid check (razina 0, or outside the scan) and still made their class's pump.
    12.11. (Jure, točka 4: "kad token ima manje od 3 točke cijene u prozoru, označi rezultat kao 'nepouzdano' i ne
    računaj ga u statistiku propuštenih"): a pump read from fewer than 3 snapshots is nepouzdano: not in the list;
    excluded (a list) gets those rows ("quality" nepouzdano, "n_points") for the count."""
    from rangedca import missed as rmissed
    cfg = cfg or config()
    now = now or time.time()
    out = []
    for r in con.execute("SELECT token, symbol, klasa, razina, t0, t0_razlog, razlog, mcap, first_ts FROM token_tier "
                         "WHERE last_ts >= ? AND (razina = 0 OR t0 IN ('nije', 'pad'))", (now - hours * 3600,)):
        token, sym, klasa, razina, t0, t0_why, why, mcap, first_ts = r
        snaps = con.execute("SELECT ts, price FROM hype_snapshots WHERE token=? AND price > 0 ORDER BY ts", (token,)).fetchall()
        if len(snaps) < 2:
            continue
        p0 = snaps[0][1]
        max_ret = max(p / p0 - 1 for _, p in snaps)
        klasa = klasa or classify.klasa(mcap, None)
        if max_ret >= thr.get(klasa, 1.0):
            row = {"token": token, "symbol": sym, "klasa": klasa, "razina": razina, "t0": t0,
                   "reason": why or t0_why or "nije stigao do plaćene provjere", "mcap": mcap,
                   "max_ret": round(max_ret, 2), "first_ts": first_ts or snaps[0][0]}
            if rmissed.unreliable(len(snaps)):   # 12.11.: two snapshots are no measured pump
                if excluded is not None:
                    excluded.append({**row, "max_ret": None, "quality": rmissed.UNRELIABLE, "n_points": len(snaps)})
                continue
            out.append(row)
    return sorted(out, key=lambda x: -x["max_ret"])
