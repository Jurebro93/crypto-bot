"""Pick exit rules by replaying price paths through paper/sim.py, the same code that trades.

Score of a rule set = average return per trade minus lambda x average loss, so a loss hurts more than a gain of the
same size helps ("every trade should end in profit") while one 20x still counts in full (moonshots). The search is
coordinate descent over the grid in exits/config.json: change one rule at a time, keep what helps, repeat.

Guardrails before a new set is used (nothing is applied by hand):
- at least min_paths paths for the class;
- it must beat the current set on the older AND the newer half of the paths (time split), and on live paths
  alone once there are min_live_check of them;
- every rule moves at most max_steps grid positions per run (no jumps);
- the gain must be at least min_gain (0.5 percentage points per trade), or nothing changes;
- it must still beat the current set with its best few paths left out (robust_top), so a couple of 25x hits cannot
  pick the rules on their own.

Closer to reality (1.11., stop -15% but replayed median -65% to -83%): every fill pays slippage (paper config
slip), a stop on a coarse historical path fills where the minute checks would have caught it (cfg coarse, measured
on live stop exits, see exits/fit.reality), and live paths (minute ticks of our own candidates) weigh together at
least live_share of the score.
"""
import json
import os
import random
import statistics

from paper import sim

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
KEYS = ("sl", "sl_delay_min", "tp", "trail_tiers", "sl_after_tp", "stale", "max_hold_h", "moonbag", "moon_trail", "kol_hold_min",
        "kol_trail_add")
SIM_KEYS = ("sl", "sl_delay_min", "tp", "trail_tiers", "sl_after_tp", "max_hold_h", "moonbag", "moon_trail", "moon_hold_h", "kol_hold_min",
            "kol_trail_add")


def load_config(path=None):
    with open(path or CONFIG) as f:
        return json.load(f)


def params_of(cfg):
    """The learned keys of a paper config (stale is stored as stale_min/stale_ret there)."""
    p = {k: cfg.get(k) for k in ("sl", "tp", "max_hold_h")}
    p["trail_tiers"] = cfg.get("trail_tiers") or [[cfg.get("trail_after", 0.5), cfg.get("trail", 0.3)]]
    p["sl_after_tp"] = cfg.get("sl_after_tp", 0.0 if cfg.get("breakeven_after_tp") else None)
    p["stale"] = [cfg["stale_min"], cfg.get("stale_ret", 0.1)] if cfg.get("stale_min") else None
    p["moonbag"], p["moon_trail"] = cfg.get("moonbag", 0), cfg.get("moon_trail", 0.6)
    p["kol_hold_min"], p["kol_trail_add"] = cfg.get("kol_hold_min", 0), cfg.get("kol_trail_add", 0.0)
    p["sl_delay_min"] = cfg.get("sl_delay_min", 0) or 0
    return p


def to_sim(base, params):
    """Paper config with the learned keys applied."""
    c = {**base, **{k: v for k, v in params.items() if k in SIM_KEYS}}
    st = params.get("stale")
    c["stale_min"], c["stale_ret"] = (st[0], st[1]) if st else (None, 0.1)
    return c


def replay_path(path, cfg):
    if path.get("src") == "live" and cfg.get("coarse"):  # minute ticks: the stop fills where the ticks say
        cfg = {k: v for k, v in cfg.items() if k != "coarse"}
    t0 = path["ts"]
    pts = [(t0 + dt, m, liq) for dt, m, liq in path["pts"]]
    calls = [t0 + c for c in path.get("kol") or ()]
    return sim.replay(1.0, path["liq0"] or 50_000, t0, pts, cfg, calls=calls)


def live_weights(paths, ecfg):
    """Weight per path: live paths together count at least live_share of the score (at most live_w_max each),
    seed paths 1. None when there are no live paths (plain average)."""
    n_live = sum(p.get("src") == "live" for p in paths)
    n_seed = len(paths) - n_live
    share = ecfg.get("live_share", 0.5)
    if not n_live or not n_seed or n_live / len(paths) >= share:
        return None
    w = min(ecfg.get("live_w_max", 10.0), share / (1 - share) * n_seed / n_live)
    return [w if p.get("src") == "live" else 1.0 for p in paths]


def evaluate(paths, cfg, lam=1.0, cap=10.0, weights=None):
    """Replay every path; summary numbers the dashboard shows and the objective the search maximises.
    In the score one trade counts at most `cap` (+1000%): a single 600x (or a mispriced tx) must not pick the rules.
    weights: one per path (live paths heavier, see live_weights); only the score uses them."""
    if not paths:
        return {"n": 0, "score": float("-inf")}
    rets, moon = [], []
    reasons = {}
    for p in paths:
        r = replay_path(p, cfg)
        rets.append(r["ret"])
        reasons[r["exit_reason"]] = reasons.get(r["exit_reason"], 0) + 1
        pk = max((m for _, m, _ in p["pts"]), default=1.0)
        if pk >= 10:
            moon.append((r["ret"] + 1, pk))
    n = len(rets)
    mean = sum(rets) / n
    w = weights if weights and len(weights) == n else [1.0] * n
    tw = sum(w)
    mean_c = sum(min(r, cap) * x for r, x in zip(rets, w)) / tw
    loss = sum(-r * x for r, x in zip(rets, w) if r < 0) / tw
    srt = sorted(rets)
    return {"n": n, "score": round(mean_c - lam * loss, 5), "mean": round(mean, 4), "median": round(statistics.median(rets), 4),
            "win": round(sum(r > 0 for r in rets) / n, 4), "big_loss": round(sum(r <= -0.3 for r in rets) / n, 4),
            "p10": round(srt[max(0, n // 10 - 1)], 4), "best": round(srt[-1], 2),
            "moon_n": len(moon), "moon_mult": round(sum(m for m, _ in moon) / len(moon), 2) if moon else None,
            "moon_peak": round(sum(p for _, p in moon) / len(moon), 1) if moon else None, "exits": reasons}


def _index(grid, value):
    try:
        return grid.index(value)
    except ValueError:
        return None


def search(paths, base, current, ecfg, rng=None):
    """Coordinate descent from `current` (learned keys). Each key may move at most max_steps grid positions."""
    grid, lam, steps = ecfg["grid"], ecfg["lambda_loss"], ecfg["max_steps"]
    cap = ecfg.get("ret_cap", 10.0)
    allowed = {}
    for k in KEYS:
        g = grid[k]
        i = _index(g, current.get(k))
        allowed[k] = g if i is None else g[max(0, i - steps): i + steps + 1]
    best = {"sl_delay_min": 0, **current}
    wts = live_weights(paths, ecfg)
    ref = evaluate(paths, to_sim(base, best), lam, cap, wts)
    best_score = ref["score"]
    keys = list(KEYS)
    rng = rng or random.Random(7)
    for _ in range(ecfg["rounds"]):
        rng.shuffle(keys)
        moved = False
        for k in keys:
            for v in allowed[k]:
                if v == best.get(k):
                    continue
                trial = {**best, k: v}
                ev = evaluate(paths, to_sim(base, trial), lam, cap, wts)
                s = ev["score"]
                if s > best_score + 1e-6 and moon_ok(ev, ref, ecfg):
                    best, best_score, moved = trial, s, True
        if not moved:
            break
    return best


def moon_ok(new, ref, ecfg):
    """Moonshot guard: on paths that reached 10x the new rules must keep moon_keep of what the current rules made."""
    if not ref.get("moon_mult") or ref.get("moon_n", 0) < 5:
        return True
    return (new.get("moon_mult") or 0) >= ecfg.get("moon_keep", 0.8) * ref["moon_mult"]


def without_top(paths, cfg, ecfg):
    """The paths minus the best robust_top share (at least robust_min) by what `cfg` made on them."""
    k = max(ecfg.get("robust_min", 3), int(len(paths) * ecfg.get("robust_top", 0.01)))
    if len(paths) <= 2 * k:
        return paths
    scored = sorted(paths, key=lambda p: replay_path(p, cfg)["ret"])
    return scored[:-k]


def split(paths):
    """Older and newer half by entry time."""
    ps = sorted(paths, key=lambda p: p["ts"])
    return ps[:len(ps) // 2], ps[len(ps) // 2:]


def fit_profile(paths, base, current, ecfg):
    """One class: search on all paths, then check the result on each time half and on live paths.
    Returns (decision dict, new params or None)."""
    lam, cap = ecfg["lambda_loss"], ecfg.get("ret_cap", 10.0)
    current = {"sl_delay_min": 0, **current}  # profiles learned before the stop delay existed
    n = len(paths)
    out = {"n": n, "n_live": sum(p["src"] == "live" for p in paths),
           "n_shadow": sum(p["src"] == "shadow" for p in paths)}
    if n < ecfg["min_paths"]:
        out["note"] = f"premalo putanja ({n} od potrebnih {ecfg['min_paths']})"
        return out, None
    old, new = split(paths)
    cand = search(old, base, current, ecfg)  # learn on the older half only ...
    cfg_now, cfg_new = to_sim(base, current), to_sim(base, cand)
    wts = live_weights(paths, ecfg)
    out["live_w"] = round(max(wts), 2) if wts else 1.0
    out["now"], out["new"] = evaluate(paths, cfg_now, lam, cap, wts), evaluate(paths, cfg_new, lam, cap, wts)
    out["new_params"] = cand
    halves = []
    for h in (old, new):  # ... it must also win on the newer half it has never seen
        a, b = evaluate(h, cfg_now, lam, cap)["score"], evaluate(h, cfg_new, lam, cap)["score"]
        halves.append((a, b))
    out["halves"] = [[round(a, 4), round(b, 4)] for a, b in halves]
    live = [p for p in paths if p["src"] == "live"]
    if len(live) >= ecfg["min_live_check"]:
        a, b = evaluate(live, cfg_now, lam, cap)["score"], evaluate(live, cfg_new, lam, cap)["score"]
        out["live"] = [round(a, 4), round(b, 4)]
        if b < a:
            out["note"] = "novi skup je bolji na povijesti, ali lošiji na našim live putanjama"
            return out, None
    if cand == current:
        out["note"] = "trenutna pravila su već najbolja u dopuštenom koraku"
        return out, None
    if not moon_ok(out["new"], out["now"], ecfg):
        out["note"] = "novi skup bi izgubio previše na moonshotovima"
        return out, None
    if any(b < a for a, b in halves):
        out["note"] = "novi skup nije bolji u obje polovice podataka"
        return out, None
    rest = without_top(paths, cfg_new, ecfg)
    if len(rest) < len(paths):
        rw = live_weights(rest, ecfg)
        a, b = evaluate(rest, cfg_now, lam, cap, rw)["score"], evaluate(rest, cfg_new, lam, cap, rw)["score"]
        out["robust"] = [round(a, 4), round(b, 4)]
        if b < a:
            out["note"] = (f"novi skup je bolji samo zbog {len(paths) - len(rest)} najboljih pogodaka; "
                           "bez njih je lošiji, pa ostaju stara pravila")
            return out, None
    gain = out["new"]["score"] - out["now"]["score"]
    if gain < ecfg["min_gain"]:
        out["note"] = f"dobitak premali ({gain:+.2%} po tradeu)"
        return out, None
    out["note"] = f"bolje za {gain:+.2%} po tradeu na {n} putanja"
    return out, cand


def describe(params):
    """Plain Croatian description of a rule set for the dashboard."""
    tp = []
    for lvl, frac in params.get("tp") or []:
        what = "vrati ulog" if frac == "cost" else f"prodaj {frac:.0%}"
        tp.append(f"na {1 + lvl:g}x {what}")
    trail = ", ".join(f"od {1 + a:g}x pad {b:.0%} od vrha" for a, b in params.get("trail_tiers") or [])
    st = params.get("stale")
    sat = params.get("sl_after_tp")
    dl = params.get("sl_delay_min")
    parts = [("bez stop lossa (samo rug izlaz)" if params["sl"] <= -0.95 else f"stop loss {params['sl']:.0%}")
             + (f" (uključi se tek {dl} min nakon kupnje)" if dl and params["sl"] > -0.95 else ""), "; ".join(tp) or "bez take profita", f"trailing: {trail}" if trail else "",
             (f"nakon prvog TP ostatak izlazi na {sat:+.0%}" if sat is not None else ""),
             (f"ako u {st[0]} min ne naraste {st[1]:.0%}, izlaz" if st else ""), f"najdulje {params['max_hold_h']} h",
             (f"moonbag {params['moonbag']:.0%} ostaje dok ne padne {params['moon_trail']:.0%} od vrha"
              if params.get("moonbag") else ""),
             (f"{params['kol_hold_min']} min nakon calla influencera nema izlaza zbog mirovanja"
              + (f", trailing širi za {params['kol_trail_add']:.0%}" if params.get("kol_trail_add") else "")
              if params.get("kol_hold_min") else "")]
    return "; ".join(p for p in parts if p)


def sl_grid(paths, base, current, ecfg, sls=None, delays=None):
    """Every stop loss level x stop delay on the same paths, the rest of the rules as they are now: the table
    "Gdje rezati gubitak" on Učenje. Returns {"n", "rows": [{"sl", "delay", "mean", "median", "win", "score"}]}."""
    lam, cap = ecfg["lambda_loss"], ecfg.get("ret_cap", 10.0)
    sls = sls or [x for x in ecfg["grid"]["sl"] if x > -0.95] + [None]  # -0.99 in the grid is the "no stop" row
    delays = delays or ecfg["grid"].get("sl_delay_min") or [0]
    wts = live_weights(paths, ecfg)
    rows = []
    for sl in sls:
        for d in delays:
            p = {**current, "sl": -0.99 if sl is None else sl, "sl_delay_min": d}
            ev = evaluate(paths, to_sim(base, p), lam, cap, wts)
            rows.append({"sl": sl, "delay": d, "mean": ev.get("mean"), "median": ev.get("median"),
                         "win": ev.get("win"), "score": ev.get("score")})
            if sl is None:
                break  # no stop: the delay changes nothing
    return {"n": len(paths), "rows": rows}
