"""Grok's predictions and how they came out (11.11., Jure: get_hourly_brief.grok_predictions said the flag only
reserves the slot). MCP tool submit_grok_prediction (ui/mcpapi) -> events.db table grok_predictions.

A prediction, made at `ts` (the server stamps ts_received; a ts older than MAX_LAG_S is refused: a prediction is
about the future):
  token, mcap (USD at ts; under 30k refused, CLAUDE.md), strategy momentum | range | call,
  p_tp            probability that +tp_pct comes before -sl_pct (the trade's own levels)
  p_up            {1h, 4h, 24h} x {up10, up20, up50}: probability that the high within the horizon reaches +10 / +20 /
                  +50 % (sent flat as p_up10_1h ... p_up50_24h, or nested); within a horizon up10 >= up20 >= up50,
                  and a longer horizon never lower than a shorter one
  p_drop30_first  probability that -30 % comes before +20 % (the scanner's shadow rule, scan/shadow sl_first)
  verdict runner | avoid | neutral, reasons (text)
The prediction's fields are never changed once stored (the flag grok_predictions calls them immutable); only the
score columns of the row are filled later.

MemeSonar's own probability for the same trade, stored with it for the calibration table (use what exists, no model
of its own): get_trade_candidates' row of the token (ui/kandidati: ev_pct, the n-weighted EV of the measured records
its sources rest on, after the round-trip cost and the price impact, n_samples) turned into the EV-implied
probability of a bet at +tp_pct / -sl_pct: p = (ev + COST + sl) / (tp + sl), clipped to 0..1 (ev, tp, sl as
fractions; COST added back because ev is net of it). Null when the token is not a candidate right now or its EV rests
on no measured outcome (ms_from says which).

Scoring (score_due, the 5-min events tick, no network): after each horizon (+ GRACE_S) from the minute data we
already keep: events.db price ticks, minute.db call_candles, range.db snapshots and seed candles, hype.db token_pulse,
merged per minute (high, low, close). Entry = the close of the newest minute at or before ts (at most ENTRY_S
earlier), else the open of the first minute after it (at most ENTRY_S later). Per horizon: max_gain_pct,
max_loss_pct, first (tp | sl | none: the level the path touched first; both in one minute counts as sl), up10 /
up20 / up50, coverage (share of the horizon's minutes with data), n_points. A horizon is scored once its data
reaches 75 % of it (or a level was touched); with too little data it waits for the night step (night(): GeckoTerminal
candles, at most PRED_GT_NIGHT requests a night and never past the remeasure step's own night cap, the same counter)
and is "unavailable" UNAVAILABLE_S after it ended.
  tp_first      1 = +tp before -sl within 24 h; 0 = -sl first, or neither within 24 h; null while undecided
  drop30_first  1 = -30 % before +20 % within 24 h; 0 = not; null while undecided

The brief (brief_part): predictions scored since `since`, and the calibration per p_tp bucket (0-0.2 ... 0.8-1):
predicted (mean p) against actual (share of tp_first) in %, separately for Grok and for MemeSonar, over the last
CAL_DAYS days, with Brier scores (p_tp, and every p_up / p_drop30_first of Grok's).
The data flag grok_predictions (trade settings DATA_FLAGS): off refuses new predictions; scoring and the brief run in
every mode.
"""
import json
import re
import sqlite3
import threading
import time

from events import store
from trade import cost as _tcost

FLAG = "grok_predictions"
STRATEGIES = ("momentum", "range", "call")
VERDICTS = ("runner", "avoid", "neutral")
HORIZONS = (("1h", 3600), ("4h", 4 * 3600), ("24h", 24 * 3600))
LEVELS = (10, 20, 50)
MIN_MCAP = 30_000
MAX_LAG_S = 15 * 60       # ts at most this old (a prediction is made before what it predicts)
FUTURE_S = 300
ENTRY_S = 300
GRACE_S = 10 * 60         # a horizon is scored this long after it ended (the feeds catch up)
COVER_MIN = 0.75          # the data must reach 75 % of the horizon
UNAVAILABLE_S = 30 * 3600
RATE_PER_HOUR = 120
REASONS_MAX = 2000
COST = _tcost.FEE_ROUND_TRIP   # the round-trip cost the measured records (and so ev_pct) are net of: trade/cost (0.02)
CAL_DAYS = 30
PRED_GT_NIGHT = int(store._env_num("PRED_GT_NIGHT", 60))
MS_FRESH_S = 15 * 60      # a kandidati list this old is still "now" for MemeSonar's probability
MS_TIMEOUT_S = 4.0
BUCKETS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS grok_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, ts_received INTEGER NOT NULL, token TEXT NOT NULL,
    mcap REAL, strategy TEXT, p_tp REAL, tp_pct REAL, sl_pct REAL, p_up TEXT, p_drop30_first REAL, verdict TEXT,
    reasons TEXT, key_id TEXT,
    ms_p_tp REAL, ms_ev_pct REAL, ms_n INTEGER, ms_from TEXT,
    entry_px REAL, scores TEXT, tp_first INTEGER, drop30_first INTEGER, decided_ts INTEGER, scored_ts INTEGER,
    done INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS grok_predictions_due ON grok_predictions (done, ts);
CREATE INDEX IF NOT EXISTS grok_predictions_scored ON grok_predictions (scored_ts);
CREATE INDEX IF NOT EXISTS grok_predictions_key ON grok_predictions (key_id, ts_received);
"""


def ensure(con):
    con.executescript(SCHEMA)


def _has(con):
    try:
        return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='grok_predictions'").fetchone())
    except sqlite3.Error:
        return False


# ---------- intake -------------------------------------------------------------------------------------------------

def _p(x, name, need=False):
    if x is None:
        if need:
            raise ValueError(f"{name} is required (0-1)")
        return None
    if isinstance(x, bool):
        raise ValueError(f"{name} must be a probability 0-1")
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a probability 0-1")
    if not 0 <= v <= 1:
        raise ValueError(f"{name} must be a probability 0-1")
    return round(v, 4)


def _num(x, name, lo, hi):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if isinstance(x, bool) or not lo < v <= hi:
        raise ValueError(f"{name} must be above {lo:g} and at most {hi:g}")
    return v


def parse_p_up(a):
    """{"1h": {"up10": p, ...}, ...} from flat p_up10_1h ... or a nested p_up; ValueError when inconsistent."""
    nested = a.get("p_up") if isinstance(a.get("p_up"), dict) else {}
    out = {}
    for hz, _s in HORIZONS:
        row = {}
        sub = nested.get(hz) if isinstance(nested.get(hz), dict) else {}
        for lv in LEVELS:
            v = a.get(f"p_up{lv}_{hz}")
            if v is None:
                v = sub.get(f"up{lv}", sub.get(str(lv)))
            p = _p(v, f"p_up{lv}_{hz}")
            if p is not None:
                row[f"up{lv}"] = p
        if row:
            vals = [row.get(f"up{lv}") for lv in LEVELS]
            known = [v for v in vals if v is not None]
            if any(b > a_ + 1e-9 for a_, b in zip(known, known[1:])):
                raise ValueError(f"p_up of {hz} must not grow with the level (up10 >= up20 >= up50)")
            out[hz] = row
    for lv in LEVELS:   # the high within 4 h is at least the high within 1 h
        seq = [out.get(hz, {}).get(f"up{lv}") for hz, _s in HORIZONS]
        known = [v for v in seq if v is not None]
        if any(b + 1e-9 < a_ for a_, b in zip(known, known[1:])):
            raise ValueError(f"p_up{lv} must not fall with a longer horizon (1h <= 4h <= 24h)")
    return out


def validate(a, now):
    """The prediction normalized, or ValueError with the reason (in English: the client reads it)."""
    if not isinstance(a, dict):
        raise ValueError("arguments must be an object")
    tok = str(a.get("token") or a.get("token_address") or "").strip()
    if not MINT.fullmatch(tok):
        raise ValueError("token must be a Solana token address")
    ts = a.get("ts")
    if ts is None:
        ts = now
    try:
        ts = int(float(ts))
    except (TypeError, ValueError):
        raise ValueError("ts must be unix seconds")
    if ts > 1e12:
        ts //= 1000
    if ts > now + FUTURE_S:
        raise ValueError("ts is in the future")
    if ts < now - MAX_LAG_S:
        raise ValueError(f"ts is older than {MAX_LAG_S // 60} min: a prediction is made before what it predicts")
    mcap = _num(a.get("mcap") if a.get("mcap") is not None else a.get("market_cap_usd"), "mcap", 0, 1e13)
    if mcap < MIN_MCAP:
        raise ValueError("mcap under $30k: MemeSonar does not analyse such tokens")
    strat = str(a.get("strategy") or "").strip().lower()
    if strat not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
    verdict = str(a.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    tp = _num(a.get("tp_pct"), "tp_pct", 0, 1000)
    try:
        sl = abs(float(a.get("sl_pct")))
    except (TypeError, ValueError):
        raise ValueError("sl_pct must be a number (the stop in % below the entry)")
    if not 0 < sl < 100:
        raise ValueError("sl_pct must be above 0 and under 100")
    reasons = a.get("reasons")
    if isinstance(reasons, list):
        reasons = "; ".join(str(x) for x in reasons)
    return {"token": tok, "ts": ts, "mcap": mcap, "strategy": strat, "verdict": verdict, "tp_pct": tp, "sl_pct": sl,
            "p_tp": _p(a.get("p_tp"), "p_tp", need=True), "p_up": parse_p_up(a),
            "p_drop30_first": _p(a.get("p_drop30_first"), "p_drop30_first"),
            "reasons": str(reasons or "")[:REASONS_MAX]}


def implied_p(ev_pct, tp_pct, sl_pct):
    """The probability that makes a bet at +tp / -sl worth ev_pct (net of COST): (ev + COST + sl) / (tp + sl)."""
    if ev_pct is None or not tp_pct or not sl_pct:
        return None
    ev, tp, sl = ev_pct / 100, tp_pct / 100, sl_pct / 100
    return round(max(0.0, min(1.0, (ev + COST + sl) / (tp + sl))), 4)


def _kandidati_rows():
    """get_trade_candidates' rows now: the cached list when it is fresh, else one build (at most MS_TIMEOUT_S)."""
    from ui import kandidati
    c = kandidati._CACHE
    if c.get("rows") is not None and time.time() - (c.get("ts") or 0) <= MS_FRESH_S:
        return c["rows"]
    box = {}
    th = threading.Thread(target=lambda: box.setdefault("rows", kandidati._cached()[0]), name="pred-ms", daemon=True)
    th.start()
    th.join(MS_TIMEOUT_S)
    return box.get("rows")


def memesonar_view(token, tp_pct, sl_pct, rows_fn=None):
    """{"p_tp", "ev_pct", "n_samples", "from"}: MemeSonar's own probability for the same trade (module text)."""
    try:
        rows = (rows_fn or _kandidati_rows)()
    except Exception as e:  # noqa: BLE001 - no candidate list: no MemeSonar probability, the prediction still counts
        return {"p_tp": None, "ev_pct": None, "n_samples": None, "from": f"kandidati nedostupni ({type(e).__name__})"}
    if rows is None:
        return {"p_tp": None, "ev_pct": None, "n_samples": None, "from": "kandidati se nisu stigli izračunati"}
    row = next((r for r in rows if r.get("token") == token), None)
    if row is None:
        return {"p_tp": None, "ev_pct": None, "n_samples": None, "from": "token nije među kandidatima"}
    ev, n = row.get("ev_pct"), row.get("n_samples")
    if ev is None or not n:
        return {"p_tp": None, "ev_pct": ev, "n_samples": n, "from": "EV kandidata nema izmjerenih ishoda"}
    return {"p_tp": implied_p(ev, tp_pct, sl_pct), "ev_pct": ev, "n_samples": n,
            "from": "get_trade_candidates ev_pct -> EV-implied p"}


def flag_mode(tcon=None):
    from trade import settings
    try:
        return settings.flag(FLAG, con=tcon)
    except Exception:  # noqa: BLE001 - unreadable: off
        return "off"


def submit(a, kid="local", now=None, econ=None, tcon=None, rows_fn=None):
    """submit_grok_prediction: {"id", "status": "stored", ...}; ValueError with the reason when refused."""
    now = int(now or time.time())
    if flag_mode(tcon) == "off":
        raise ValueError("refused: the owner has the prediction intake switched off (flag grok_predictions); "
                         "nothing was stored")
    d = validate(a, now)
    ms = memesonar_view(d["token"], d["tp_pct"], d["sl_pct"], rows_fn)
    own = econ is None
    econ = econ or store.connect()
    try:
        ensure(econ)
        n = econ.execute("SELECT COUNT(*) FROM grok_predictions WHERE key_id=? AND ts_received>?",
                         (kid, now - 3600)).fetchone()[0]
        if n >= RATE_PER_HOUR:
            raise ValueError(f"rate limit: at most {RATE_PER_HOUR} predictions an hour per key")
        cur = econ.execute(
            "INSERT INTO grok_predictions (ts, ts_received, token, mcap, strategy, p_tp, tp_pct, sl_pct, p_up, "
            "p_drop30_first, verdict, reasons, key_id, ms_p_tp, ms_ev_pct, ms_n, ms_from) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d["ts"], now, d["token"], d["mcap"], d["strategy"], d["p_tp"], d["tp_pct"], d["sl_pct"],
             json.dumps(d["p_up"]) if d["p_up"] else None, d["p_drop30_first"], d["verdict"], d["reasons"], kid,
             ms["p_tp"], ms["ev_pct"], ms["n_samples"], ms["from"]))
        econ.commit()
        pid = cur.lastrowid
    finally:
        if own:
            econ.close()
    print(f"mcp: Grokovo predviđanje #{pid} {d['token'][:6]} {d['strategy']} p_tp {d['p_tp']:g} ({d['verdict']})",
          flush=True)
    return {"id": pid, "status": "stored", "ts": d["ts"], "token": d["token"],
            "score_after": {hz: d["ts"] + s + GRACE_S for hz, s in HORIZONS},
            "memesonar": ms,
            "message": ("Stored, immutable. Scored after 1 h, 4 h and 24 h from the minute data MemeSonar keeps "
                        "(max gain, max loss, TP before SL); get_hourly_brief shows the results and the calibration.")}


# ---------- the price path -------------------------------------------------------------------------------------------

def _minute_rows(token, t0, t1, econ):
    """[(minute, order, o, h, l, c)] from every local store (each source optional)."""
    out = []
    try:
        for ts_ms, payload in econ.execute("SELECT ts, payload FROM events WHERE mint = ? AND type = 'price_tick' AND "
                                           "ts >= ? AND ts <= ? ORDER BY ts", (token, t0 * 1000, t1 * 1000)):
            try:
                p = float(json.loads(payload or "{}").get("p") or 0)
            except (ValueError, TypeError):
                continue
            if p > 0:
                t = ts_ms // 1000
                out.append((t - t % 60, t, p, p, p, p))
    except sqlite3.Error:
        pass
    try:
        from rangedca import data
    except Exception:  # noqa: BLE001
        return out
    candles = []
    try:
        candles += data.call_candles(token, t0, t1)
    except Exception:  # noqa: BLE001
        pass
    snaps = []
    rcon = None
    try:
        rcon = data.ro()
        if rcon is not None:
            candles += data.gt_rows(rcon, token, t0, t1)
            snaps += data.own_rows(rcon, token, t0)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if rcon is not None:
            rcon.close()
    try:
        snaps += data.pulse_rows(token, t0)
    except Exception:  # noqa: BLE001
        pass
    for c in candles:
        m = int(c[0]) - int(c[0]) % 60
        if t0 - 60 <= m <= t1 and c[4]:
            out.append((m, m + 59, float(c[1]), float(c[2]), float(c[3]), float(c[4])))
    for s in snaps:
        t = int(s["ts"])
        if t0 <= t <= t1 and s.get("price"):
            p = float(s["price"])
            out.append((t - t % 60, t, p, p, p, p))
    return out


def merge(rows):
    """[(minute, o, h, l, c)] oldest first: per minute the first open, the highest high, the lowest low, the last
    close (by the order key: a point's own second, a candle's end)."""
    by = {}
    for m, order, o, h, l, c in sorted(rows, key=lambda r: (r[0], r[1])):
        cur = by.get(m)
        if cur is None:
            by[m] = [o, h, l, c]
        else:
            cur[1], cur[2], cur[3] = max(cur[1], h), min(cur[2], l), c
    return [(m, *v) for m, v in sorted(by.items())]


def series(token, t0, t1, econ, extra=()):
    """The merged minute path of `token` in [t0, t1]; extra: candles (ts, o, h, l, c[, v]) fetched by the night."""
    rows = _minute_rows(token, t0, t1, econ)
    for c in extra or ():
        m = int(c[0]) - int(c[0]) % 60
        if t0 - 60 <= m <= t1 and c[4]:
            rows.append((m, m + 59, float(c[1]), float(c[2]), float(c[3]), float(c[4])))
    return merge(rows)


def entry(cs, ts):
    """(price, minute, how) of the entry at ts (module text), None without a price near ts."""
    before = [c for c in cs if ts - ENTRY_S <= c[0] <= ts]
    if before:
        c = before[-1]
        return c[4], c[0], "close"
    after = [c for c in cs if ts < c[0] <= ts + ENTRY_S]
    if after:
        return after[0][1], after[0][0], "open"
    return None


def first_touch(path, px, up_pct, down_pct):
    """"tp" | "sl" | "none": which of +up_pct / -down_pct the path touched first (both in one minute: sl)."""
    hi, lo = px * (1 + up_pct / 100), px * (1 - down_pct / 100)
    for _m, _o, h, l, _c in path:
        if l <= lo:
            return "sl"
        if h >= hi:
            return "tp"
    return "none"


def score_horizon(cs, e, ts, secs, tp, sl, now):
    """One horizon's result, or None while it cannot be scored yet (see the module text)."""
    if now < ts + secs + GRACE_S:
        return None
    px, m_e, how = e
    path = [c for c in cs if (c[0] > m_e if how == "close" else c[0] >= m_e) and c[0] <= ts + secs]
    first = first_touch(path, px, tp, sl) if path else "none"
    reach = bool(path) and path[-1][0] >= ts + COVER_MIN * secs
    if not (reach and len(path) >= 3) and first == "none":
        if now >= ts + secs + UNAVAILABLE_S:
            return {"status": "unavailable", "why": "premalo minutnih podataka", "n_points": len(path),
                    "scored_ts": int(now)}
        return None
    hi = max(c[2] for c in path)
    lo = min(c[3] for c in path)
    gain, loss = (hi / px - 1) * 100, (lo / px - 1) * 100
    return {"status": "ok", "first": first, "max_gain_pct": round(gain, 2), "max_loss_pct": round(loss, 2),
            **{f"up{lv}": gain >= lv for lv in LEVELS},
            "coverage": round(min(1.0, len(path) / (secs / 60)), 3), "n_points": len(path), "partial": not reach,
            "scored_ts": int(now)}


def score_one(r, now, econ, extra=()):
    """(changed, row updates) of one stored prediction (a dict of its columns)."""
    ts, tok = r["ts"], r["token"]
    scores = json.loads(r["scores"] or "{}")
    if not any(hz not in scores and now >= ts + s + GRACE_S for hz, s in HORIZONS):
        return False, {}   # nothing new is due: no store is read
    cs = series(tok, ts - ENTRY_S - 60, ts + HORIZONS[-1][1], econ, extra)
    e = entry(cs, ts)
    if e is None:
        if now >= ts + HORIZONS[-1][1] + UNAVAILABLE_S:
            for hz, _s in HORIZONS:
                scores.setdefault(hz, {"status": "unavailable", "why": "nema cijene oko trenutka predviđanja",
                                       "scored_ts": int(now)})
            return True, {"scores": scores, "done": 1, "scored_ts": int(now)}
        return False, {}
    changed = False
    for hz, secs in HORIZONS:
        if hz in scores:
            continue
        s = score_horizon(cs, e, ts, secs, r["tp_pct"], r["sl_pct"], now)
        if s is not None:
            scores[hz] = s
            changed = True
    if not changed:
        return False, {}
    up = {"scores": scores, "entry_px": e[0], "scored_ts": int(now), "done": int(all(hz in scores for hz, _s in HORIZONS))}
    if r.get("tp_first") is None:
        for hz, _s in HORIZONS:
            s = scores.get(hz) or {}
            if s.get("status") == "ok" and s["first"] != "none":
                up.update(tp_first=int(s["first"] == "tp"), decided_ts=int(now))
                break
        else:
            if (scores.get("24h") or {}).get("status") == "ok":
                up.update(tp_first=0, decided_ts=int(now))
    if r.get("drop30_first") is None:
        path = [c for c in cs if (c[0] > e[1] if e[2] == "close" else c[0] >= e[1]) and c[0] <= ts + HORIZONS[-1][1]]
        f = first_touch(path, e[0], 20, 30)
        if f != "none":
            up["drop30_first"] = int(f == "sl")
        elif (scores.get("24h") or {}).get("status") == "ok":
            up["drop30_first"] = 0
    return True, up


def _save(econ, pid, up):
    up = dict(up)
    if "scores" in up:
        up["scores"] = json.dumps(up["scores"])
    econ.execute(f"UPDATE grok_predictions SET {', '.join(f'{k}=?' for k in up)} WHERE id=?", [*up.values(), pid])


def _due(econ, now, limit):
    cur = econ.execute("SELECT * FROM grok_predictions WHERE done = 0 AND ts <= ? ORDER BY ts LIMIT ?",
                       (int(now) - HORIZONS[0][1] - GRACE_S, int(limit)))
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, x)) for x in cur.fetchall()]


def score_due(econ, now=None, limit=200, log=print):
    """Score every prediction whose next horizon is due from the data we have (the 5-min tick). Returns how many
    predictions got a new horizon."""
    now = int(now or time.time())
    if not _has(econ):
        return 0
    n = 0
    for r in _due(econ, now, limit):
        changed, up = score_one(r, now, econ)
        if changed:
            _save(econ, r["id"], up)
            n += 1
    if n:
        econ.commit()
    return n


# ---------- the night: GeckoTerminal for what the day's data could not score ---------------------------------------

def _pool(econ, token, fetch_dex):
    r = econ.execute("SELECT pool FROM pools WHERE token = ?", (token,)).fetchone()
    if r and r[0]:
        return r[0]
    try:
        from events import sources
        kcon = sources._ro(sources.db_paths()["kol"])
        if kcon is not None:
            try:
                r = kcon.execute("SELECT pair FROM tokens WHERE token = ? AND pair IS NOT NULL", (token,)).fetchone()
            finally:
                kcon.close()
            if r and r[0]:
                return r[0]
    except Exception:  # noqa: BLE001
        pass
    try:
        got = (fetch_dex([token]) or {}).get(token)   # DexScreener, free
    except Exception:  # noqa: BLE001
        got = None
    return got[0] if got and got[0] else None


def night(econ, now=None, log=print, fetch=None, fetch_dex=None, cap=None):
    """For predictions with a horizon past due that the day's data could not score: GeckoTerminal minute candles
    (1-minute for 1 h / 4 h, 5-minute for 24 h; one request each), at most `cap` (PRED_GT_NIGHT) and never past
    events/remeasure's night cap (cap_left / _spend: the same counter). Returns {"requests", "scored", "why"}."""
    from events import remeasure
    now = int(now or time.time())
    if not _has(econ):
        return {"requests": 0, "scored": 0, "why": "još nema predviđanja"}
    rows = [r for r in _due(econ, now, 500)]
    want = []
    for r in rows:
        sc = json.loads(r["scores"] or "{}")
        miss = [(hz, s) for hz, s in HORIZONS if hz not in sc and now >= r["ts"] + s + GRACE_S]
        if miss:
            want.append((r, miss[-1]))
    if not want:
        return {"requests": 0, "scored": 0, "why": "ništa ne čeka podatke"}
    left = min(PRED_GT_NIGHT if cap is None else cap, remeasure.cap_left(econ, now))
    if left <= 0:
        return {"requests": 0, "scored": 0, "why": "noćni strop GeckoTerminala potrošen"}
    live = fetch is None
    fetch = fetch or remeasure.gt_candles
    fetch_dex = fetch_dex or remeasure.dex_pools
    if live:
        from event_calendar import http
        from kol import measure
        if http.cooling(measure.GECKO) > 30:
            return {"requests": 0, "scored": 0, "why": "GeckoTerminal je zauzet (drugi posao ili 429)"}
        http.reserve(measure.GECKO, 600)
    used = scored = 0
    try:
        for r, (hz, secs) in want:
            if used >= left:
                break
            pool = _pool(econ, r["token"], fetch_dex)
            if not pool:
                continue
            end = min(now, r["ts"] + secs + 60)
            agg = 5 if secs > 4 * 3600 else 1
            limit = int((end - (r["ts"] - ENTRY_S - 60)) // (60 * agg)) + 2
            used += 1
            try:
                got = fetch(pool, end, min(1000, limit), agg)
            except Exception:  # noqa: BLE001
                got = None
            if got is None:
                break   # GeckoTerminal held by another job: the rest waits for the next night
            if agg > 1:   # a 5-minute candle stands for its five minutes: spread so coverage counts minutes
                got = [(c[0] + k * 60, *c[1:]) for c in got for k in range(agg)]
            changed, up = score_one(r, now, econ, extra=got)
            if changed:
                _save(econ, r["id"], up)
                scored += 1
        econ.commit()
    finally:
        if live:
            from event_calendar import http
            from kol import measure
            http.release(measure.GECKO)
        if used:
            remeasure._spend(econ, now, used)
    log(f"događaji: Grokova predviđanja: {scored} ocijenjeno iz GeckoTerminala ({used} zahtjeva)")
    return {"requests": used, "scored": scored, "why": ""}


# ---------- reading: the brief -----------------------------------------------------------------------------------------

def _bucket(p):
    for lo, hi in BUCKETS:
        if lo <= p < hi or (hi == 1.0 and p == 1.0):
            return f"{lo:.1f}-{hi:.1f}"
    return None


def calibration(econ, now=None, days=CAL_DAYS):
    """{"grok": [...], "memesonar": [...], "brier": {...}, "n_decided"}: per p_tp bucket n, predicted_pct (mean p) and
    actual_pct (share of tp_first), over the decided predictions of the last `days` days."""
    now = int(now or time.time())
    rows = econ.execute("SELECT p_tp, ms_p_tp, tp_first, p_up, scores, p_drop30_first, drop30_first FROM "
                        "grok_predictions WHERE ts >= ?", (now - days * 86400,)).fetchall()
    dec = [r for r in rows if r[2] is not None]

    def table(idx):
        by = {}
        for r in dec:
            if r[idx] is None:
                continue
            by.setdefault(_bucket(r[idx]), []).append((r[idx], r[2]))
        out = []
        for lo, hi in BUCKETS:
            k = f"{lo:.1f}-{hi:.1f}"
            xs = by.get(k) or []
            out.append({"bucket": k, "n": len(xs),
                        "predicted_pct": round(sum(p for p, _y in xs) / len(xs) * 100, 1) if xs else None,
                        "actual_pct": round(sum(y for _p, y in xs) / len(xs) * 100, 1) if xs else None})
        return out

    def brier(pairs):
        pairs = [(p, y) for p, y in pairs if p is not None and y is not None]
        return {"n": len(pairs), "brier": round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 4) if pairs else None}
    b = {"grok_p_tp": brier((r[0], r[2]) for r in dec), "memesonar_p_tp": brier((r[1], r[2]) for r in dec),
         "paired": {"grok": brier((r[0], r[2]) for r in dec if r[1] is not None),
                    "memesonar": brier((r[1], r[2]) for r in dec if r[1] is not None)},
         "grok_p_drop30_first": brier((r[5], r[6]) for r in rows)}
    for hz, _s in HORIZONS:
        for lv in LEVELS:
            pairs = []
            for r in rows:
                pu = json.loads(r[3] or "{}").get(hz) or {}
                s = json.loads(r[4] or "{}").get(hz) or {}
                if pu.get(f"up{lv}") is not None and s.get("status") == "ok":
                    pairs.append((pu[f"up{lv}"], int(bool(s.get(f"up{lv}")))))
            b[f"grok_p_up{lv}_{hz}"] = brier(pairs)
    return {"grok": table(0), "memesonar": table(1), "brier": b, "n_decided": len(dec), "window_days": days,
            "actual": "share of predictions where +tp_pct came before -sl_pct within 24 h (both in one minute = sl)"}


def brief_part(econ, since, now=None, limit=50):
    """get_hourly_brief.grok_predictions."""
    now = int(now or time.time())
    mode = flag_mode()
    if econ is None or not _has(econ):
        return {"flag_mode": mode, "items": [], "pending": 0, "calibration": None,
                "note": ("još nema nijednog predviđanja (submit_grok_prediction)" if mode != "off" else
                         "unos predviđanja je isključen (zastavica grok_predictions); vlasnik ga uključuje")}
    cur = econ.execute("SELECT id, ts, token, mcap, strategy, verdict, p_tp, tp_pct, sl_pct, p_drop30_first, ms_p_tp, "
                       "ms_ev_pct, ms_n, entry_px, scores, tp_first, drop30_first, scored_ts, done FROM grok_predictions "
                       "WHERE scored_ts >= ? ORDER BY scored_ts DESC LIMIT ?", (int(since), int(limit)))
    cols = [c[0] for c in cur.description]
    items = []
    for x in cur.fetchall():
        d = dict(zip(cols, x))
        d["scores"] = json.loads(d["scores"] or "{}")
        d["done"] = bool(d["done"])
        items.append(d)
    pending = econ.execute("SELECT COUNT(*) FROM grok_predictions WHERE done = 0").fetchone()[0]
    out = {"flag_mode": mode, "items": items, "pending": pending, "calibration": calibration(econ, now)}
    if mode == "off":
        out["note"] = "unos predviđanja je isključen (zastavica grok_predictions); stara se i dalje ocjenjuju"
    return out
