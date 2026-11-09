"""TP/SL iz podataka (9.11.2026, Jure: "TP 20 / SL -40? koliko nam čistih pogodaka treba? neka alat dinamički odluči
kad može biti profitabilno").

The arithmetic first. A trade that takes +TP % or loses SL %, with a round-trip cost of c % of the stake, breaks
even when the target comes before the stop in

    p* = (SL + c) / (TP + SL)

of the trades. With the demo's cost (league/store.FEE, 1 % a side): TP 15 / SL 20 needs 63 %, TP 20 / SL 40 needs
70 %, TP 30 / SL 15 needs 38 %. A wider stop RAISES the bar: it pays only when it turns enough stopped trades into
winners, and only the measured paths can say whether it does.

kol/minute.py measures every call minute by minute for an hour and stores the first minute each level above (UPS)
and below (DOWNS) the entry was touched (minute.db call_lv). From those, for any TP/SL pair, one call is:
    'tp'    the target was touched in an EARLIER minute than the stop                      -> +TP
    'sl'    the stop came first, or both in the same minute (order unknown: the stop)      -> -SL
    'time'  neither within the hour: out at the close of minute 60 (r60)
and the expected result per trade is the mean over the calls, after cost.

decide() picks the pair for one source (an account, or a crew's calls):
  - fewer than MIN_N measured calls (one per token): no decision (ok None); the caller keeps its default exit
  - every pair's mean is pulled toward "no edge" (minus the cost; everybody's result for that pair when that is
    worse and stands on POOL_MIN_N+ calls) by PRIOR_N pseudo-calls, so ten lucky calls do not look like a strategy
  - the pair is chosen on the OLDER two thirds of the calls and must be in the plus on the NEWER third too (the
    "proven twice" idea of wallets/dokazani.py): a pair that only fits the past is not taken
  - the result per trade must be above zero even at the low end of its range (mean minus Z standard errors over
    all calls): with 25 pairs to choose from and a few dozen calls, a mean alone is in the plus by chance far too
    often (simulated sources WITHOUT any edge passed 7-30 % of the time on the mean alone, 1-8 % with the bound)
  - ok True only when, on top of that, the cautious estimate over all calls is at least MIN_EV % per trade;
    otherwise ok False, which for the copy means: do not enter this call
Calls measured before the levels were stored have an exact minute only for -20 % and +5..+30 %: for any other
stop the order is taken against us whenever it cannot be proven (never an optimistic guess); kol/minute.py
measures them again when its queue is empty.

Nothing here costs an API call: it reads minute.db (read-only) and does arithmetic.
"""
import json
import math
import os
import sqlite3
import time

TPS = (10, 15, 20, 30, 50)
SLS = (10, 15, 20, 30, 40)
COST = 2.0        # % of the stake per round trip: league/store.FEE is 1 % a side (pool impact comes on top)
MIN_N = 10        # measured calls (one per token) before the tool decides by itself
MIN_EV = 1.0      # % per trade the cautious estimate must reach
PRIOR_N = 10      # pseudo-calls of "no edge" every source starts with
POOL_MIN_N = 200  # everybody's result counts as the starting point only from this many measured calls
Z = 2.0           # standard errors the mean must stay above zero by (see the module text and the simulation there)
DAYS = 30         # kol/minute.KEEP_DAYS
HOLD_MIN = 60     # the measured horizon: a copy with a data exit is closed after this long (kol/minute.HORIZON_MIN)
READ_TIMEOUT_S = 2   # how long a decision waits for minute.db before it is "unknown"
LEGACY_UP = (5, 10, 15, 20, 30)   # the targets the old rows have an exact minute for (call_path t5..t30)

_COLS = ("tweet_id", "token", "handle", "ts", "hi60", "lo60", "r60", "t5", "t10", "t15", "t20", "t30", "sl_min", "lv")


def breakeven(tp, sl, cost=COST):
    """Share of trades in which +tp % must come before -sl % for a zero result after `cost` % per round trip."""
    return (sl + cost) / (tp + sl)


def _levels(row):
    """({level %: first minute} up, same down, exact) of one measured call; exact False for a row without call_lv."""
    got = row.get("_lv")
    if got is None:
        lv = row.get("lv")
        if lv and lv != "x":
            d = json.loads(lv) if isinstance(lv, str) else lv
            got = ({int(k): v for k, v in (d.get("u") or {}).items()},
                   {int(k): v for k, v in (d.get("d") or {}).items()}, True)
        else:
            up = {tp: row[f"t{tp}"] for tp in LEGACY_UP if row.get(f"t{tp}") is not None}
            got = (up, {20: row["sl_min"]} if row.get("sl_min") is not None else {}, False)
        row["_lv"] = got
    return got


def outcome(row, tp, sl):
    """('tp' | 'sl' | 'time', gross % of the stake) of one measured call under take profit +tp % / stop -sl %."""
    up, dn, exact = _levels(row)
    a, b = up.get(tp), dn.get(sl)
    if not exact:
        lo = row.get("lo60")
        if b is None and sl != 20 and lo is not None and lo <= -sl / 100:
            # the stop was touched at a minute the old row does not have: no earlier than the -20 % minute for a
            # wider stop, any minute for a tighter one; taken as early as it could have been (against us)
            b = dn.get(20, 0) if sl > 20 else 0
        # a target outside LEGACY_UP has no minute either: it stays "not reached" (a win is never guessed)
    if a is not None and (b is None or a < b):
        return "tp", float(tp)
    if b is not None:
        # 10.11. (review): the price is checked every few seconds, not continuously: when the low of the stop's
        # minute went through deeper levels too, the stop is booked at the deepest one touched in that minute
        # (a -10 % stop in a minute that printed -30 % did not fill at -10 %). Old rows know only the level asked.
        deep = max([d for d, m in dn.items() if m == b and d >= sl] or [sl]) if exact else sl
        return "sl", -float(deep)
    # neither level inside the hour: out at the close of minute 60, which by definition lies between the two.
    # Clamped, because an old row has no minute for some targets (its close can sit above a target it "never
    # reached") and a second measurement can disagree with the stored close; booking more than the target would
    # be the optimistic guess this module never makes (10.11., review: +300 % was booked under TP 50).
    return "time", max(-float(sl), min((row.get("r60") or 0.0) * 100, float(tp)))


def grid(rows, cost=COST, tps=TPS, sls=SLS):
    """{(tp, sl): {n, tp, sl, time (shares), ev (mean % per trade after cost)}} over the measured calls."""
    out, n = {}, len(rows)
    for tp in tps:
        for sl in sls:
            k = {"tp": 0, "sl": 0, "time": 0}
            tot = sq = 0.0
            for r in rows:
                kind, g = outcome(r, tp, sl)
                k[kind] += 1
                tot += g - cost
                sq += (g - cost) ** 2
            ev = tot / n if n else 0.0
            sd = math.sqrt(max(0.0, (sq - n * ev * ev) / (n - 1))) if n > 1 else 0.0
            out[(tp, sl)] = {"n": n, "tp": k["tp"] / n if n else 0.0, "sl": k["sl"] / n if n else 0.0,
                             "time": k["time"] / n if n else 0.0, "ev": ev, "sd": sd}
    return out


def _shrunk(ev, n, prior, prior_n):
    return (ev * n + prior * prior_n) / (n + prior_n) if n + prior_n else prior


def decide(rows, pool=None, cost=COST, min_n=MIN_N, min_ev=MIN_EV, prior_n=PRIOR_N, z=Z):
    """The exit for one source from its measured calls (see the module text). Returns a dict:
    ok        True (enter with tp/sl), False (do not enter), None (too few calls to tell)
    tp, sl    the chosen pair in percent (absent when ok is None)
    n, n_new  measured calls, and how many of them are the newer part
    win, stop, time   shares of the calls that ended at the target, at the stop, on time
    need      share of targets the pair needs for zero (breakeven)
    ev        cautious expected % per trade over all calls (after cost, pulled toward no edge)
    ev_raw, ev_new    the plain mean over all calls and over the newer part
    lo        the low end of the plain mean (ev_raw minus z standard errors); ok needs it above zero
    base      the pair with its numbers, why = one Croatian sentence for the log and the page."""
    rows = sorted(rows, key=lambda r: r["ts"])
    n = len(rows)
    if n < min_n:
        return {"ok": None, "n": n, "why": f"premalo izmjerenih poziva ({n} od {min_n})"}
    k_new = max(3, n // 3)
    older, newer = rows[:n - k_new], rows[n - k_new:]
    g_old, g_new, g_all = grid(older, cost), grid(newer, cost), grid(rows, cost)

    def prior(pair):
        # "no edge" loses the cost. Everybody's result for this pair replaces it only when it is WORSE and stands
        # on enough calls: a source has to show its own edge, the crowd's luck never lifts it over the line
        p = (pool or {}).get(pair) or (pool or {}).get(f"{pair[0]}/{pair[1]}")
        return min(p["ev"], -cost) if p and (p.get("n") or 0) >= POOL_MIN_N and "ev" in p else -cost

    best = max(g_old, key=lambda pr: (_shrunk(g_old[pr]["ev"], len(older), prior(pr), prior_n), -pr[1], pr[0]))
    a = g_all[best]
    ev = _shrunk(a["ev"], n, prior(best), prior_n)
    ev_old = _shrunk(g_old[best]["ev"], len(older), prior(best), prior_n)
    ev_new = g_new[best]["ev"]
    tp, sl = best
    need = breakeven(tp, sl, cost)
    lo = a["ev"] - z * a["sd"] / math.sqrt(n)
    edge = ev >= min_ev and ev_old > 0
    ok = edge and ev_new > 0 and lo > 0
    base = (f"TP +{tp} % / SL −{sl} %: na {n} izmjerenih poziva cilj prije stopa {a['tp']:.0%} (treba {need:.0%}), "
            f"očekivano {ev:+.1f} % po tradeu")
    if ok:
        why = f"izlaz po podacima {base}; na novijih {len(newer)} poziva {ev_new:+.1f} %"
    elif not edge:
        why = f"po podacima se ne isplati: najbolji izlaz {base}"
    elif ev_new <= 0:
        why = (f"po podacima se ne isplati: najbolji izlaz {base}, ali na novijih {len(newer)} poziva gubi "
               f"({ev_new:+.1f} % po tradeu)")
    else:
        why = (f"po podacima još nije dokazano: najbolji izlaz {base}, ali uz ovakvo rasipanje {n} poziva nije "
               f"dovoljno (donja granica {lo:+.1f} % po tradeu)")
    return {"ok": ok, "tp": tp, "sl": sl, "n": n, "n_new": len(newer), "win": a["tp"], "stop": a["sl"],
            "time": a["time"], "need": need, "ev": ev, "ev_raw": a["ev"], "ev_new": ev_new, "lo": lo,
            "base": base, "why": why}


# ---------- reading minute.db -------------------------------------------------------------------------------------

def rows(mcon, handles=None, days=DAYS, now=None):
    """Measured calls of the window as dicts (with 'lv', None for a row without levels), oldest first, one per
    (account, token): the first, as kol/minute.handle_stats counts them. handles: only these accounts (any case)."""
    now = int(now or time.time())
    cols = ", ".join(f"c.{c}" for c in _COLS[:-1])

    def read(where, args):
        where = "c.entry IS NOT NULL AND c.bad IS NULL AND c.ts >= ?" + where
        args = [now - days * 86400, *args]
        try:
            return mcon.execute(f"SELECT {cols}, l.lv FROM call_path c LEFT JOIN call_lv l ON l.tweet_id = c.tweet_id "
                                f"AND l.token = c.token WHERE {where}", args).fetchall()
        except sqlite3.OperationalError as e:
            if "no such table: call_lv" not in str(e):
                raise   # locked / damaged: the caller treats it as "unknown" (10.11., review), never as "all old rows"
            # a minute.db from before call_lv: its writer creates the table on its next pass
            return mcon.execute(f"SELECT {cols}, NULL FROM call_path c WHERE {where}", args).fetchall()

    if handles is None:
        got = read("", [])
    else:
        hs = sorted({h for h in handles if h})
        if not hs:
            return []
        q = ",".join("?" * len(hs))
        # the follow's target is the handle as kol.db stores it (league/copy.events matches it exactly), so the
        # index on (handle, ts) answers; a differently typed case is looked for only when that finds nothing
        got = read(f" AND c.handle IN ({q})", hs) or read(f" AND LOWER(c.handle) IN ({q})", sorted({h.lower() for h in hs}))
    first = {}
    for r in got:
        d = dict(zip(_COLS, r))
        k = (d["handle"], d["token"])
        if k not in first or d["ts"] < first[k]["ts"]:
            first[k] = d
    return sorted(first.values(), key=lambda d: d["ts"])


def crew_rows(rws, k=1, window_s=1800):
    """One row per token for a crew: the first call at which k different members have called the token within the
    window_s before it (k = 1: the first caller). That is the call league/copy.run_once enters a crew follow on
    (it counts the members inside crew_window_min around the newest call, not from the crew's first call)."""
    by = {}
    for r in sorted(rws, key=lambda r: r["ts"]):
        by.setdefault(r["token"], []).append(r)
    out = []
    for calls in by.values():
        for i, r in enumerate(calls):
            if len({x["handle"] for x in calls[:i + 1] if r["ts"] - x["ts"] <= window_s}) >= k:
                out.append(r)
                break
    return sorted(out, key=lambda r: r["ts"])


def pool(mcon, days=DAYS, now=None, cost=COST):
    """Everybody's measured calls under every pair: {'ts', 'n', 'pairs': {'tp/sl': {n, tp, sl, time, ev, need}}}."""
    rws = rows(mcon, None, days, now)
    g = grid(rws, cost)
    return {"ts": int(now or time.time()), "n": len(rws), "cost": cost,
            "pairs": {f"{tp}/{sl}": {**{k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()},
                                     "need": round(breakeven(tp, sl, cost), 4)} for (tp, sl), d in g.items()}}


def save_pool(mcon, days=DAYS, now=None):
    """kol/minute.loop, once a pass: kv tpsl_pool in minute.db (the only writer of that file)."""
    p = pool(mcon, days, now)
    mcon.execute("INSERT OR REPLACE INTO kv VALUES ('tpsl_pool', ?)", (json.dumps(p),))
    mcon.commit()
    return p


def load_pool(mcon):
    """The saved pool ({'n': 0, 'pairs': {}} when there is none yet)."""
    try:
        r = mcon.execute("SELECT value FROM kv WHERE key = 'tpsl_pool'").fetchone()
        return json.loads(r[0]) if r else {"ts": 0, "n": 0, "pairs": {}}
    except (sqlite3.OperationalError, ValueError):
        return {"ts": 0, "n": 0, "pairs": {}}


def for_handles(handles, k=1, window_s=1800, days=DAYS, now=None, path=None):
    """decide() for an account (one handle) or a crew (several; k = how many of them must call), read from
    minute.db. None when minute.db is missing or cannot be read (unknown is never a decision)."""
    from kol import minute
    hs = [h for h in handles if h]
    if not hs:
        return None
    p = path or minute.db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:   # a short wait: this read sits in front of a buy, and minute.db has one writer with short transactions
        mcon = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=READ_TIMEOUT_S)
    except sqlite3.Error:
        return None
    try:
        rws = rows(mcon, hs, days, now)
        if len(hs) > 1 or k > 1:
            rws = crew_rows(rws, max(1, min(int(k or 1), len(hs))), window_s)
        return decide(rws, load_pool(mcon).get("pairs"))
    except sqlite3.Error:
        return None
    finally:
        mcon.close()
