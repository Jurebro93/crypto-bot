"""The bot's account in Natjecanje ("liga"), round 2 (Nicholas 4.11.: round 1 went to $0 on bad trades; learn from
the mistakes and iterate until profitable).

Round 1 counted every demo trade, including the learning trades (exploration, konvergencija, A/B, KOL waves) that
exist to measure, not to earn. From round 2 the demo still takes every learning trade (paper money, no daily cap,
all of it feeds learning), but the league account only counts a trade when its kind has PROVEN itself:

    group = entry mode + arm (sources + trading session), e.g. "explore:tg+x|us"
    proven = in the last `days` days, at least `min_n` closed demo trades of that group, mean return after costs
             (each trade capped at +300%) above 0, and the bootstrap 90% range of that mean entirely above 0.

Every pass re-checks this, so a group that starts losing drops out of the league by itself and one that starts
winning comes in: the iteration Nicholas asked for, with no hand edits. Trades are flagged when opened (config
"liga": true) so the league display (ui/leaguedash) sums only those from the round start.
"""
import json
import random
import time

DEFAULT = {"enabled": True, "days": 7, "min_n": 15, "cap": 3.0, "boot": 400, "level": 0.9, "refresh_s": 600}
_CACHE = {"ts": 0, "data": None}


def config(cfg=None):
    return {**DEFAULT, **((cfg or {}).get("liga") or {})}


def group_of(cfg_t):
    return f"{cfg_t.get('entry_mode') or 'core'}:{cfg_t.get('arm') or '?'}"


def _boot_low(rets, n_boot, level, rng):
    n = len(rets)
    means = sorted(sum(rng.choice(rets) for _ in range(n)) / n for _ in range(n_boot))
    return means[int((1 - level) / 2 * n_boot)]


def groups(con, now=None, cfg=None, rng=None):
    """{group: {n, mean, low, win, proven}} from closed demo trades of the last `days` days (hand sales excluded)."""
    lc = config(cfg)
    now = now or time.time()
    rng = rng or random.Random(11)
    by = {}
    for conf, ret, state in con.execute(
            "SELECT config, ret, state FROM trades WHERE status='closed' AND closed_ts>=?",
            (int(now - lc["days"] * 86400),)):
        if '"rucno"' in (state or ""):
            continue
        try:
            c = json.loads(conf or "{}")
        except ValueError:
            continue
        by.setdefault(group_of(c), []).append(min(lc["cap"], ret or 0.0))
    out = {}
    for g, rets in by.items():
        n = len(rets)
        mean = sum(rets) / n
        low = _boot_low(rets, lc["boot"], lc["level"], rng) if n >= lc["min_n"] else None
        out[g] = {"n": n, "mean": round(mean, 4), "low": None if low is None else round(low, 4),
                  "win": round(sum(r > 0 for r in rets) / n, 3),
                  "proven": bool(n >= lc["min_n"] and mean > 0 and low is not None and low > 0)}
    return out


def proven(con, now=None, cfg=None):
    """Cached groups() for the trading loop (re-computed every refresh_s)."""
    lc = config(cfg)
    now = now or time.time()
    if _CACHE["data"] is None or now - _CACHE["ts"] > lc["refresh_s"]:
        _CACHE.update(ts=now, data=groups(con, now, cfg))
    return _CACHE["data"]


def flag(con, cfg_t, cfg, now=None):
    """Set cfg_t['liga'] (and the group) on a trade being opened; True when it counts in the league round."""
    lc = config(cfg)
    g = group_of(cfg_t)
    cfg_t["liga_group"] = g
    cfg_t["liga"] = bool(lc["enabled"] and (proven(con, now, cfg).get(g) or {}).get("proven"))
    return cfg_t["liga"]
