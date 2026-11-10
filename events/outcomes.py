"""Night: what happened after every call and every followed wallet's buy, and who is worth listening to.

call_outcomes (events.db), one row per call / wallet_buy event (uid = the event's uid):
    max_1h, max_4h, max_24h   highest move within 1 / 4 / 24 h of the entry (fraction; a one-print wick counts up to
                              3x the candle body, as kol/measure and kol/minute do)
    min_before_max            lowest move from the entry until the 24 h high (the 4 h high when 24 h is not known)
    change_4h, change_24h     the close 4 h / 24 h after the entry
    ev                        the result of one copy: TP +20 % / SL -30 % (whichever is touched first; both in the
                              same candle = the stop), else out at 4 h; minus 2 % round-trip cost
    status                    pending (younger than 26 h) | ok | unmeasured (calls only: no data yet, the night
                              remeasure takes them, events/remeasure.py) | unavailable (with the reason)
    src                       where the path came from: minute_candles (minute.db, 4 h after each measured call),
                              kol_measure (kol.db 24 h figures), price_ticks (events.db), gt_minute (remeasure)
The data is our own: no request is made here.

scores (events.db), recomputed every night from call_outcomes of the last SCORE_DAYS days, the first event per
(actor, token, day) only (a caller posting the same CA ten times is one call):
    kind caller (X) | channel (Telegram) | wallet;  n (events), n_measured (status ok with a 4 h high), hits (+20 %
    within 4 h), hit_rate = hits / n_measured, median_max_4h, median_max_24h, ev (mean of the measured)

early_wallets: wallets whose buys came before the first call of a token (within EARLY_WINDOW_H), how often those
tokens won (+100 % within 4 h of the call), and the insiders of kol/insiders.py; EXTRA_EARLY takes more finders
(callables (econ, now) -> [{"wallet", "n_early", "n_wins", "median_lead_min", "source"}]).
"""
import json
import sqlite3
import statistics
import time

from events import sources, store

COST = 0.02
TP, SL = 0.20, -0.30
WICK_X = 3.0
PENDING_S = 26 * 3600
MIN_AGE_S = 4 * 3600
SCORE_DAYS = 30
EARLY_WINDOW_H = 6
WIN_4H = 1.0
TICK_TOL_S = 20 * 60     # a price tick this close to a checkpoint stands for it (DexScreener snapshots every ~20 min)
EXTRA_EARLY = []


# ---------- the path of one entry (pure) ----------------------------------------------------------------------------

def points_from_candles(candles, wick=WICK_X):
    """1-min candles [(ts, o, h, l, c, v)] -> [(t_end, hi, lo, close)] with the capped wick."""
    return [(c[0] + 60, min(c[2], max(c[1], c[4]) * wick), c[3], c[4]) for c in sorted(candles)]


def points_from_ticks(ticks):
    """[(ts, price)] -> points."""
    return [(t, p, p, p) for t, p in sorted(ticks) if p]


def entry_from_candles(candles, ts, within_s=300):
    """(entry price, the time the path starts) for a call at ts: the close of its minute, else the open of the first
    candle within `within_s` after it; None when there is none (kol/minute's rule, bad 'svijeca')."""
    m0 = ts - ts % 60
    for c in sorted(candles):
        if c[0] == m0 and c[4]:
            return c[4], m0 + 60
        if m0 < c[0] <= m0 + within_s and c[1]:
            return c[1], c[0]
    return None


def entry_from_ticks(ticks, ts, after_s=600, before_s=300):
    """The first tick within after_s after ts, else the last within before_s before it."""
    after = [(t, p) for t, p in sorted(ticks) if ts <= t <= ts + after_s and p]
    if after:
        return after[0][1], after[0][0]
    before = [(t, p) for t, p in sorted(ticks) if ts - before_s <= t < ts and p]
    return (before[-1][1], ts) if before else None


def metrics(points, t0, entry, horizon, tol=0):
    """The outcome fields of one entry at t0 (unix s) from points after it; horizon: the last moment the data covers
    (a checkpoint after it is unknown, None)."""
    out = {"max_1h": None, "max_4h": None, "max_24h": None, "min_before_max": None, "change_4h": None,
           "change_24h": None, "ev": None}
    if not entry or entry <= 0:
        return out
    pts = [p for p in points if p[0] > t0 - 1]
    for name, h in (("max_1h", 1), ("max_4h", 4), ("max_24h", 24)):
        end = t0 + h * 3600
        if horizon + tol < end:
            continue
        w = [p for p in pts if p[0] <= end + tol]
        out[name] = (max(p[1] for p in w) / entry - 1) if w else 0.0
    for name, h in (("change_4h", 4), ("change_24h", 24)):
        end = t0 + h * 3600
        if horizon + tol < end:
            continue
        w = [p for p in pts if p[0] <= end + tol]
        out[name] = (w[-1][3] / entry - 1) if w else 0.0
    span = 24 if out["max_24h"] is not None else 4 if out["max_4h"] is not None else None
    if span:
        w = [p for p in pts if p[0] <= t0 + span * 3600 + tol]
        if w:
            top = max(range(len(w)), key=lambda i: w[i][1])
            out["min_before_max"] = min(0.0, min(p[2] for p in w[:top + 1]) / entry - 1)
    for p in (p for p in pts if p[0] <= t0 + 4 * 3600 + tol):   # TP / SL within 4 h, the stop first in a tie
        if p[2] <= entry * (1 + SL):
            out["ev"] = SL - COST
            break
        if p[1] >= entry * (1 + TP):
            out["ev"] = TP - COST
            break
    else:
        if out["change_4h"] is not None:
            out["ev"] = out["change_4h"] - COST
    return {k: (round(v, 5) if v is not None else None) for k, v in out.items()}


# ---------- the night pass ------------------------------------------------------------------------------------------

def _ro(name):
    return sources._ro(sources.db_paths().get(name)) if name in sources.db_paths() else None


def _minute_ro():
    try:
        from kol import minute
        return sources._ro(minute.db_path())
    except Exception:  # noqa: BLE001
        return None


def _candles(mcon, tok, start, end):
    if mcon is None:
        return []
    try:
        from kol import minute
        return minute.candles_for(mcon, tok, start, end)
    except Exception:  # noqa: BLE001 - no call_candles table (older minute.db)
        return []


def _measured_24h(kcon, tids):
    """{(tweet_id, token): (max24, r24h, mcap0, bad)} of kol.db's 5-min measure."""
    out = {}
    if kcon is None or not tids:
        return out
    ids = sorted({t for t, _ in tids})
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        try:
            for tid, tok, mx, r24, mc, bad in kcon.execute(
                    f"SELECT tweet_id, token, max24, r24h, mcap0, bad FROM calls WHERE tweet_id IN "
                    f"({','.join('?' * len(part))})", part):
                out[(tid, tok)] = (mx, r24, mc, bad)
        except sqlite3.Error:
            break
    return out


def _ticks(econ, mint, start, end):
    return [(t // 1000, json.loads(p or "{}").get("p")) for t, p in econ.execute(
        "SELECT ts, payload FROM events WHERE mint = ? AND type = 'price_tick' AND ts >= ? AND ts <= ? ORDER BY ts",
        (mint, start * 1000, end * 1000))]


def outcome_of(ev, now, candles=None, ticks=None, k24=None):
    """The call_outcomes row of one event dict {uid, kind, mint, actor, source, ts, tweet_id, mcap0} (pure)."""
    ts = ev["ts"]
    res, src, reason = None, None, None
    mcap0 = ev.get("mcap0")
    if candles:
        e = entry_from_candles(candles, ts)
        if e:
            # a minute without a candle had no trade (the price stood), so stored candles that reach 200+ minutes
            # after the entry cover the 4 h; shorter ones end with their last candle
            last = max(c[0] for c in candles) + 60
            horizon = min(now, e[1] + 4 * 3600) if last >= e[1] + 200 * 60 else last
            res = metrics(points_from_candles(candles), e[1], e[0], max(horizon, e[1]))
            src = "minute_candles"
    if (res is None or res["max_4h"] is None) and ticks:
        e = entry_from_ticks(ticks, ts)
        if e:
            res2 = metrics(points_from_ticks(ticks), e[1], e[0], max(t for t, _ in ticks), TICK_TOL_S)
            if res is None or res2["max_4h"] is not None:
                res, src = res2, "price_ticks"
    if k24:
        mx, r24, mc, bad = k24
        mcap0 = mcap0 if mcap0 is not None else mc
        if not bad and mx is not None:
            res = res or {k: None for k in ("max_1h", "max_4h", "max_24h", "min_before_max", "change_4h",
                                            "change_24h", "ev")}
            res["max_24h"] = mx if res.get("max_24h") is None else res["max_24h"]
            res["change_24h"] = r24 if res.get("change_24h") is None else res["change_24h"]
            src = (src + "+kol_measure") if src else "kol_measure"
    age = now - ts
    if mcap0 is not None and mcap0 < store.MIN_MCAP:
        status, reason = "unavailable", "ispod 30k"
    elif res and res.get("max_4h") is not None and (res.get("max_24h") is not None or age >= PENDING_S):
        status = "ok"
        reason = None if res.get("max_24h") is not None else "bez 24 h"
    elif age < PENDING_S:
        status = "pending"
    elif ev["kind"] == "call":
        status, reason = "unmeasured", "nema svijeća ni cijena"
    else:
        status, reason = "unavailable", "nema cijena"
    r = res or {}
    return (ev["uid"], ev["kind"], ev["mint"], ev["actor"], ev["source"], ts, ev.get("tweet_id"), mcap0, None,
            r.get("max_1h"), r.get("max_4h"), r.get("max_24h"), r.get("min_before_max"), r.get("change_4h"),
            r.get("change_24h"), r.get("ev"), status, reason, src, int(now))


FINAL = "(status = 'unavailable' OR (status = 'ok' AND max_24h IS NOT NULL) OR src LIKE 'gt_minute%')"


CHUNK = 20_000
COMPUTE_BUDGET_S = 1200


def _chunk(econ, evs, now, kcon, mcon):
    """call_outcomes rows of one chunk of events (grouped per token: its candles and ticks are read once)."""
    by = {}
    for e in evs:
        by.setdefault(e["mint"], []).append(e)
    rows = []
    k24 = _measured_24h(kcon, [(e["tweet_id"], e["mint"]) for e in evs if e["tweet_id"]])
    for mint, es in by.items():
        t_lo, t_hi = min(e["ts"] for e in es) - 600, max(e["ts"] for e in es) + 25 * 3600
        cand = _candles(mcon, mint, t_lo, t_hi)
        ticks = _ticks(econ, mint, t_lo, t_hi)
        for e in es:
            c = [x for x in cand if e["ts"] - 600 <= x[0] <= e["ts"] + 24 * 3600 + 120] if cand else None
            tk = [x for x in ticks if e["ts"] - 600 <= x[0] <= e["ts"] + 25 * 3600] if ticks else None
            rows.append(outcome_of(e, now, c, tk, k24.get((e["tweet_id"], mint)) if e["tweet_id"] else None))
    return rows


def compute(econ, now=None, log=print, chunk=CHUNK, budget_s=COMPUTE_BUDGET_S):
    """The night's outcomes: events of type call / wallet_buy newer than the watermark minus 26 h (the pending ones
    get finished) and older than MIN_AGE_S, not final yet, in chunks of `chunk` events (memory stays small), a commit
    each. Watermark kv 'wm:outcomes' = the newest event time done; past `budget_s` the night stops where it is and
    the next night goes on from there."""
    now = int(now or time.time())
    wm = store.kv_get(econ, "wm:outcomes")
    lo = (int(wm) if wm else now - 15 * 86400) - PENDING_S
    hi = now - MIN_AGE_S
    final = {u for (u,) in econ.execute(f"SELECT uid FROM call_outcomes WHERE ts >= ? AND {FINAL}", (lo,))}
    kcon, mcon = _ro("kol"), _minute_ro()
    st, cur_ts, cur_id, done_to, t0 = {}, lo * 1000, -1, hi, time.monotonic()
    try:
        while True:
            evs, n = [], 0
            for rid, u, t, mint, actor, src, typ, mc, payload in econ.execute(
                    "SELECT id, uid, ts, mint, actor, source, type, mcap_usd, payload FROM events WHERE type IN "
                    "('call', 'wallet_buy') AND (ts > ? OR (ts = ? AND id > ?)) AND ts <= ? ORDER BY ts, id LIMIT ?",
                    (cur_ts, cur_ts, cur_id, hi * 1000, chunk)):
                n += 1
                cur_ts, cur_id = t, rid
                if u in final or not mint:
                    continue
                tid = None
                if typ == "call":
                    try:
                        tid = json.loads(payload or "{}").get("tweet_id")
                    except ValueError:
                        tid = None
                evs.append({"uid": u, "kind": typ, "mint": mint, "actor": actor, "source": src, "ts": t // 1000,
                            "tweet_id": tid, "mcap0": mc})
            rows = _chunk(econ, evs, now, kcon, mcon)
            econ.executemany("INSERT OR REPLACE INTO call_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             rows)
            econ.commit()
            for r in rows:
                st[r[16]] = st.get(r[16], 0) + 1
            if n < chunk:
                break
            if time.monotonic() - t0 > budget_s:
                done_to = cur_ts // 1000 + PENDING_S   # the next night starts right after this event
                log(f"događaji: ishodi stali nakon {budget_s} s, nastavak sljedeće noći")
                break
    finally:
        for c in (kcon, mcon):
            if c is not None:
                c.close()
    store.kv_put(econ, "wm:outcomes", min(hi, done_to))
    econ.commit()
    log(f"događaji: ishodi {sum(st.values())} (" + ", ".join(f"{k} {v}" for k, v in sorted(st.items())) + ")")
    return st


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def scores(econ, now=None, days=SCORE_DAYS, log=print):
    """Recompute the scores table from call_outcomes (measured calls only count; n_measured says how many)."""
    now = int(now or time.time())
    rows = econ.execute("SELECT kind, actor, source, mint, ts, status, max_4h, max_24h, ev FROM call_outcomes "
                        "WHERE ts >= ? AND actor IS NOT NULL ORDER BY ts", (now - days * 86400,)).fetchall()
    seen, agg = set(), {}
    for kind, actor, source, mint, ts, status, m4, m24, ev in rows:
        k = (actor, mint, ts // 86400)
        if k in seen:
            continue
        seen.add(k)
        sk = "wallet" if kind == "wallet_buy" else ("channel" if source == "telegram" or actor.startswith("tg:")
                                                     else "caller")
        a = agg.setdefault((sk, actor), {"n": 0, "m4": [], "m24": [], "ev": [], "last": 0})
        a["n"] += 1
        a["last"] = max(a["last"], ts)
        if status == "ok" and m4 is not None:
            a["m4"].append(m4)
            a["m24"].append(m24)
            if ev is not None:
                a["ev"].append(ev)
    out = []
    for (sk, actor), a in agg.items():
        nm = len(a["m4"])
        hits = sum(1 for x in a["m4"] if x >= TP)
        out.append((sk, actor, a["n"], nm, hits, round(hits / nm, 4) if nm else None, _med(a["m4"]), _med(a["m24"]),
                    round(sum(a["ev"]) / len(a["ev"]), 4) if a["ev"] else None, a["last"], now))
    econ.execute("DELETE FROM scores")
    econ.executemany("INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?)", out)
    econ.commit()
    by = {}
    for r in out:
        by[r[0]] = by.get(r[0], 0) + 1
    log(f"događaji: ocjene {len(out)} (" + ", ".join(f"{k} {v}" for k, v in sorted(by.items())) + "), samo izmjereni "
        f"pozivi ({sum(r[3] for r in out)} od {sum(r[2] for r in out)})")
    return by


def score_of(econ, actors):
    """{actor: {kind, n, n_measured, hit_rate, median_max_4h, ev}} for the brief."""
    out = {}
    acts = sorted({a for a in actors if a})
    for i in range(0, len(acts), 400):
        part = acts[i:i + 400]
        for kind, actor, n, nm, _h, hr, m4, _m24, ev in econ.execute(
                f"SELECT kind, actor, n, n_measured, hits, hit_rate, median_max_4h, median_max_24h, ev FROM scores "
                f"WHERE actor IN ({','.join('?' * len(part))})", part):
            out[actor] = {"kind": kind, "n": n, "n_measured": nm, "hit_rate": hr, "median_max_4h": m4, "ev": ev}
    return out


def early_wallets(econ, now=None, days=SCORE_DAYS, log=print):
    """Wallets buying before the first call of a token: n_early, n_wins (+100 % within 4 h after the call), lead."""
    now = int(now or time.time())
    since = (now - days * 86400) * 1000
    first = dict(econ.execute("SELECT mint, MIN(ts) FROM events WHERE type = 'call' AND ts >= ? GROUP BY mint",
                              (since,)).fetchall())
    win = {}
    for mint, m4 in econ.execute("SELECT mint, MAX(max_4h) FROM call_outcomes WHERE kind = 'call' AND status = 'ok' "
                                 "AND ts >= ? GROUP BY mint", (now - days * 86400,)):
        win[mint] = (m4 or 0) >= WIN_4H
    agg = {}
    for mint, fts in first.items():
        for w, ts in econ.execute("SELECT actor, MIN(ts) FROM events WHERE mint = ? AND type = 'wallet_buy' AND ts < ? "
                                  "AND ts >= ? GROUP BY actor", (mint, fts, fts - EARLY_WINDOW_H * 3600 * 1000)):
            a = agg.setdefault(w, {"n": 0, "wins": 0, "lead": [], "last": 0})
            a["n"] += 1
            a["wins"] += 1 if win.get(mint) else 0
            a["lead"].append((fts - ts) / 60000)
            a["last"] = max(a["last"], ts // 1000)
    rows = {w: (w, a["n"], a["wins"], round(a["wins"] / a["n"], 3), _med(a["lead"]), "events", a["last"], now)
            for w, a in agg.items() if a["n"] >= 2}
    extra = []
    try:
        from kol import insiders
        kcon = _ro("kol")
        if kcon is not None:
            try:
                extra = [{"wallet": w, "n_early": n, "n_wins": None, "median_lead_min": None, "source": "insiders"}
                         for w, n, _sold in insiders.wallets(kcon, 2, 500)]
            finally:
                kcon.close()
    except Exception as e:  # noqa: BLE001 - the insiders list is an extra
        log(f"događaji: insajderi nisu pročitani ({type(e).__name__})")
    for fn in EXTRA_EARLY:
        try:
            extra += list(fn(econ, now) or [])
        except Exception as e:  # noqa: BLE001
            log(f"događaji: dodatni izvor ranih novčanika {getattr(fn, '__name__', fn)}: {type(e).__name__}")
    for x in extra:
        w = x.get("wallet")
        if w and w not in rows:
            n = int(x.get("n_early") or 0)
            wins = x.get("n_wins")
            rows[w] = (w, n, wins, round(wins / n, 3) if wins is not None and n else None, x.get("median_lead_min"),
                       x.get("source") or "extra", None, now)
    econ.execute("DELETE FROM early_wallets")
    econ.executemany("INSERT INTO early_wallets VALUES (?,?,?,?,?,?,?,?)", list(rows.values()))
    econ.commit()
    log(f"događaji: rani novčanici {len(rows)} (iz događaja {len(agg)}, dodatno {len(extra)})")
    return len(rows)


def lookup(pairs, econ=None):
    """{(tweet_id, token): outcome dict} for ui/mcpdata (measure_status from the night's measurement)."""
    own = econ is None
    econ = econ or store.ro()
    if econ is None or not pairs:
        return {}
    out = {}
    try:
        tids = sorted({t for t, _ in pairs if t})
        for i in range(0, len(tids), 400):
            part = tids[i:i + 400]
            cur = econ.execute(f"SELECT tweet_id, mint, status, reason, src, max_1h, max_4h, max_24h, change_24h, "
                               f"min_before_max, mcap0 FROM call_outcomes WHERE tweet_id IN ({','.join('?' * len(part))})",
                               part)
            for tid, mint, st, why, src, m1, m4, m24, c24, mbm, mc in cur:
                out[(tid, mint)] = {"status": st, "reason": why, "src": src, "max_1h": m1, "max_4h": m4,
                                    "max_24h": m24, "change_24h": c24, "min_before_max": mbm, "mcap0": mc}
    except sqlite3.Error:
        return {}
    finally:
        if own:
            econ.close()
    return out
