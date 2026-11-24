"""Entry sources in the learning: how much better than a random entry is each strategy of the comparison (strat.db)?

The strategy comparison (strat/) buys the same way from different sources (KOL calls, top wallets, insiders, the
tool's own picks per market-cap band) with the SAME exits, plus a random control ("kontrola") from the same scanner.
So the difference between a strategy and the control per trade is what its SOURCE adds, not luck of the market:

    lift(source) = mean return per closed trade of the strategy - mean of the control (each trade capped at +300%)
    range        = 90% bootstrap range of that difference (learn/champion.boot_diff, the same test as model vs
                   weights)
    weight       = lift when the whole range is on one side of zero, else 0 ("not different from random"); 0 too
                   while the strategy or the control has fewer than MIN_N closed trades ("premalo podataka")

Into the decision model (learn/champion.py, gbm) every decision point gets, point in time (no lookahead):
    izv_<key>   1 when that source had signalled the token before the point (strat.db positions, signal_ts <= ts;
                for the tool's own picks only an actual entry before the point counts)
    izv_tezina  the sum of the weights of those sources, computed only from trades closed before the point's day
    izv_n       how many sources had signalled it
The model then learns by itself how much a source is worth next to the other signals; the linear hype weights are
left alone (their score is computed in the scanner, before strat.db sees a token).

Read-only on strat.db. Nothing here buys or sells.
"""
import os
import sqlite3
import time

from learn import champion

MIN_N = 20          # closed trades needed by a strategy AND by the control before a lift is shown as a number
DAYS = 14           # only trades closed in the last DAYS days (old regimes fade out)
CAP = 3.0
BOOT = 300
MAX_W = 0.5         # one source never weighs more than ±50 percentage points per trade
WALLET_KEYS = ("novcanici", "top_novcanici")   # the old all-wallets account signals the same wallets
_CACHE = {"ts": 0, "key": None, "data": None}
_DAYS = {}          # (db, day start) -> {source: weight}


def _db(path=None):
    from strat import store
    return path or store.DB


def _ro(path=None):
    p = _db(path)
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
        con.execute("SELECT 1 FROM positions LIMIT 1")
        return con
    except sqlite3.OperationalError:
        return None


def _cfg():
    from strat import run
    return run.load_config()


def sources(cfg=None):
    """[(key, name, icon)] of the strategies that are sources (everything except the control)."""
    cfg = cfg or _cfg()
    return [(s["key"], s["name"], s.get("icon", "")) for s in cfg["strategies"] if not s.get("baseline")]


def _closed(con, before, days):
    """{strat: [capped ret]} of closed trades in [before - days, before)."""
    out = {}
    for k, ret in con.execute("SELECT strat, ret FROM positions WHERE status='closed' AND closed_ts < ? AND "
                              "closed_ts >= ?", (int(before), int(before - days * 86400))):
        out.setdefault(k, []).append(min(CAP, ret or 0.0))
    return out


def verdict(n, nc, lift, rng, min_n=MIN_N):
    """(key, plain-words status) for one source."""
    if n < min_n or nc < min_n:
        return "premalo", f"premalo podataka ({n} od {min_n} zatvorenih" + (
            f", kontrola {nc} od {min_n})" if nc < min_n else ")")
    if rng and rng[0] > 0:
        return "bolje", "bolje od nasumičnog ulaza"
    if rng and rng[1] < 0:
        return "losije", "lošije od nasumičnog ulaza"
    return "isto", "ne razlikuje se od nasumičnog (raspon uključuje nulu)"


def lifts(con, now=None, cfg=None, days=DAYS, min_n=MIN_N, boot=BOOT):
    """{key: {name, icon, n, mean, n_ctrl, mean_ctrl, lift, range, weight, status, text}} as of `now` (only trades
    closed before it). The control itself is not in the result; its numbers sit on every row."""
    cfg = cfg or _cfg()
    now = now or time.time()
    by = _closed(con, now, days)
    ctrl = by.get("kontrola", [])
    mc = sum(ctrl) / len(ctrl) if ctrl else None
    out = {}
    for k, name, icon in sources(cfg):
        a = by.get(k, [])
        m = sum(a) / len(a) if a else None
        lift = (m - mc) if (m is not None and mc is not None) else None
        enough = len(a) >= min_n and len(ctrl) >= min_n
        rng = champion.boot_diff(a, ctrl, boot) if enough else None
        st, txt = verdict(len(a), len(ctrl), lift, rng, min_n)
        w = 0.0
        if st in ("bolje", "losije"):
            w = round(max(-MAX_W, min(MAX_W, lift)), 4)
        out[k] = {"name": name, "icon": icon, "n": len(a), "mean": None if m is None else round(m, 4),
                  "n_ctrl": len(ctrl), "mean_ctrl": None if mc is None else round(mc, 4),
                  "lift": None if lift is None else round(lift, 4), "range": rng, "weight": w, "status": st,
                  "text": txt}
    return out


def current(path=None, now=None, ttl=600):
    """lifts() as of now, cached ttl seconds (the dashboard and the live bot call this; strat.db is small)."""
    now = now or time.time()
    key = _db(path)
    if _CACHE["data"] is not None and _CACHE["key"] == key and now - _CACHE["ts"] < ttl:
        return _CACHE["data"]
    con = _ro(path)
    if con is None:
        return None
    try:
        data = lifts(con, now)
    finally:
        con.close()
    _CACHE.update(ts=now, key=key, data=data)
    return data


# ---------------------------------------------------------------- features for the decision model

def _signals(con):
    """{token: [(source key, ts)]}: when each source first had the token. The tool's own picks count from entry."""
    out = {}
    for k, token, sig, entry, status in con.execute(
            "SELECT strat, token, signal_ts, entry_ts, status FROM positions"):
        key = "top_novcanici" if k in WALLET_KEYS else k
        if key.startswith("alat") or key == "kontrola":
            if key == "kontrola" or status not in ("open", "closed") or not entry:
                continue
            ts = entry
        else:
            ts = sig
        if ts:
            out.setdefault(token, []).append((key, int(ts)))
    return out


def _start(con):
    try:
        r = con.execute("SELECT value FROM kv WHERE key='start_ts'").fetchone()
        return int(float(r[0])) if r else 0
    except (sqlite3.OperationalError, ValueError):
        return 0


def _day0(ts):
    return int(ts // 86400 * 86400)


def features_for(token, ts, sigs, weights_of, known, start=0):
    """izv_* features of one decision point. weights_of(day_ts) -> {key: weight}. Only what was known at ts: a
    signal that came later leaves the point exactly like a token no source ever had (izv_n 0). Before the comparison
    started (start) nothing is known: no features at all (missing, not 0)."""
    if not start or ts < start:
        return {}
    have = {k for k, t in sigs.get(token, ()) if t <= ts and k in known}
    w = weights_of(_day0(ts))
    f = {f"izv_{k}": 1.0 for k in sorted(have)}
    f["izv_n"] = float(len(have))
    f["izv_tezina"] = round(sum(w.get(k, 0.0) for k in have), 4)
    return f


def enrich(rs, path=None, cfg=None):
    """Add izv_* features to labelled shadow rows in place (and return them). No strat.db: rows unchanged."""
    if not rs:
        return rs
    con = _ro(path)
    if con is None:
        return rs
    cfg = cfg or _cfg()
    known = {k for k, _, _ in sources(cfg)}
    try:
        sigs = _signals(con)
        start = _start(con)
        db = _db(path)

        def weights_of(day):
            # a past day's snapshot never changes (only trades closed before it count): computed once per process
            if (db, day) not in _DAYS:
                _DAYS[(db, day)] = {k: v["weight"] for k, v in lifts(con, day, cfg).items()}
            return _DAYS[(db, day)]

        for r in rs:
            f = features_for(r.get("token"), r.get("ts") or 0, sigs, weights_of, known, start)
            if f:
                r["features"] = {**(r.get("features") or {}), **f}
    finally:
        con.close()
    return rs


_LIVE = {"ts": 0, "sigs": None, "start": 0}


def live_features(token, now=None, path=None):
    """Same features for a token right now (paper candidate scored by the model). {} when unknown."""
    now = now or time.time()
    if _LIVE["sigs"] is None or now - _LIVE["ts"] > 120:
        con = _ro(path)
        if con is None:
            return {}
        try:
            _LIVE.update(ts=now, sigs=_signals(con), start=_start(con))
        finally:
            con.close()
    cur = current(path, now) or {}
    w = {k: v["weight"] for k, v in cur.items()}
    return features_for(token, now, _LIVE["sigs"], lambda _d: w, set(cur) or {k for k, _, _ in sources()},
                        _LIVE["start"])
