"""Kritičar (OpenAI): its ledger, budget and the measurement of its own advice, in trade.db (on the persistent disk with
the positions and the assistant's notes; rows small: no prompt is stored, only a 12-character hash of it).

  critic_calls     one row per API call: ts, kind (trades | daily | deep), model, tokens in / out, cost_usd, ok, error,
                   phash (sha256 of the prompt, 12 hex), n (positions or findings in the answer)
  critic_verdicts  one row per open-trade verdict: the position (pid = first lot, token, mode, strategy), the verdict and
                   its confidence, PnL % and MC at the critique, the position's USD value then; filled later by
                   evaluate(): MC 30 and 60 min after (0 = could not be measured) and the MC when the position closed
  critic_kv        small state between the short processes (the hourly "no key" line, the budget lines once a period)

Budget (CLAUDE.md: "KONSTANTNO preispituj efikasnost"; the owner's caps 15.11.): OPENAI_DAY_USD (default 1.00) for the
routine work of a UTC day (live comments, the daily review, the re-checks), OPENAI_DEEP_USD (default 2.00) per deep
session (outside the day's cap), OPENAI_MONTH_USD (default 40) for everything in a UTC month. When money is short the
owner's order holds: 1. the live comment on a real-money fill, 2. the deep session, 3. the daily review, 4. the
15-min re-checks. In the day: a re-check leaves LIVE_RESERVE_USD for live comments and, until today's review ran,
DAILY_RESERVE_USD for it; the review leaves LIVE_RESERVE_USD. In the month: MONTH_RESERVE[kind] stays free for the
kinds above it. Each check counts the most the next call can cost (openai_api.max_cost), so a cap is never crossed;
when one is reached the critic makes no call of that kind and logs one line per period. pick() tries the cheap model
when the strong one does not fit (and for re-checks and live comments once CHEAP_AT of the day is used).

Measurement (vlasnik: "više učiti za manje novca"): a verdict is scored against what the price did after it. move r =
MC later / MC at the critique - 1. A sell-type verdict (prodaj, prodaj_dio, stegni_sl) is right when r <= -HIT_BAND
(the price fell more than about a round trip's cost), a hold-type one (drzi, prosiri_sl) when r > -HIT_BAND. "$ if
followed" compares the advice with what the bot did: prodaj exits all at the critique's MC, prodaj_dio half, drzi holds;
the bot held to the horizon or sold when the position closed before it; value = (advice's return - bot's return) x the
position's USD value at the critique. stegni_sl / prosiri_sl get a hit but no $ (the stop's path is not simulated).
"""
import datetime as dt
import hashlib
import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS critic_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, kind TEXT NOT NULL, model TEXT, tokens_in INTEGER,
    tokens_out INTEGER, cost_usd REAL, ok INTEGER, error TEXT, phash TEXT, n INTEGER);
CREATE INDEX IF NOT EXISTS critic_calls_ts ON critic_calls (ts);
CREATE TABLE IF NOT EXISTS critic_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, call_id INTEGER, note_id INTEGER, pid INTEGER,
    token TEXT, symbol TEXT, mode TEXT, strategy TEXT, verdict TEXT, confidence REAL, pnl_pct REAL, mc0 REAL,
    value_usd REAL, mc30 REAL, mc60 REAL, mc_close REAL, closed_ts INTEGER, done INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS critic_verdicts_pid ON critic_verdicts (pid, ts);
CREATE INDEX IF NOT EXISTS critic_verdicts_open ON critic_verdicts (done, ts);
CREATE TABLE IF NOT EXISTS critic_kv (k TEXT PRIMARY KEY, v TEXT);
"""


def _env_f(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


DAY_USD = _env_f("OPENAI_DAY_USD", 1.00)
MONTH_USD = _env_f("OPENAI_MONTH_USD", 40.0)
DEEP_USD = _env_f("OPENAI_DEEP_USD", 2.00)
DAILY_RESERVE_USD = 0.55      # the daily review's most (gpt-6-astra: ~13k tokens in at 10 $, at most 8k out at 50 $/1M)
LIVE_RESERVE_USD = 0.15       # about one strong live comment, or ten cheap ones
ROUTINE = ("live", "daily", "trades")
PRIORITY = ("live", "deep", "daily", "trades")              # the owner's order when money is short
MONTH_RESERVE = {"live": 0.0, "deep": 1.0, "daily": 3.0, "trades": 5.0}   # USD of the month kept for the kinds above
HIT_BAND = 0.02               # ~ the round trip's cost: a sell pays only when the price falls more than that
SELL_SHARE = {"prodaj": 1.0, "prodaj_dio": 0.5, "drzi": 0.0}
SELL_KIND = ("prodaj", "prodaj_dio", "stegni_sl")
EVAL_LATE_S = 3600            # a +30 / +60 min point not measurable this long after its time is given up (0)
DONE_AFTER_S = 24 * 3600      # a verdict whose position is still open after this is closed without a close point
MATCH_S = 300                 # a stored snapshot this close to the asked time stands for it


def connect(path=None):
    from trade import settings
    con = sqlite3.connect(path or settings.DB, timeout=30)
    con.executescript(SCHEMA)
    return con


def ensure(con):
    con.executescript(SCHEMA)


def phash(text):
    return hashlib.sha256((text or "").encode()).hexdigest()[:12]


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM critic_kv WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r[0])
    except ValueError:
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO critic_kv VALUES (?,?)", (k, json.dumps(v)))
    con.commit()


def book(con, kind, model, usage, cost_usd, ok, error=None, text="", n=None, now=None):
    """One critic_calls row; returns its id."""
    u = usage or {}
    cur = con.execute("INSERT INTO critic_calls (ts, kind, model, tokens_in, tokens_out, cost_usd, ok, error, phash, n) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (int(now or time.time()), kind, model, int(u.get("in") or 0), int(u.get("out") or 0),
                       round(float(cost_usd or 0), 6), 1 if ok else 0, (str(error)[:200] if error else None),
                       phash(text) if text else None, n))
    con.commit()
    return cur.lastrowid


# ---------- budget ---------------------------------------------------------------------------------------------------

def day_start(now):
    return int(now) // 86400 * 86400


def month_start(now):
    d = dt.datetime.fromtimestamp(int(now), dt.timezone.utc)
    return int(dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp())


def spent(con, since, kinds=None):
    sql, args = "SELECT COALESCE(SUM(cost_usd), 0) FROM critic_calls WHERE ts >= ?", [int(since)]
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        args += list(kinds)
    return float(con.execute(sql, args).fetchone()[0] or 0)


def local_day_start(now, tz="Europe/Zagreb"):
    """Midnight of the Zagreb day of `now` (the owner's day: the daily review is once per it)."""
    from zoneinfo import ZoneInfo
    d = dt.datetime.fromtimestamp(int(now), ZoneInfo(tz))
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def daily_done(con, now):
    """The daily review was stored today (Zagreb day)."""
    return con.execute("SELECT 1 FROM critic_calls WHERE kind='daily' AND ok=1 AND ts >= ? LIMIT 1",
                       (local_day_start(now),)).fetchone() is not None


def refusal(con, kind, est_usd, now=None, log=print, quiet=False):
    """None when a call of `kind` that costs at most est_usd fits every cap, else the reason (Croatian). The first
    refusal of a period is logged once (quiet: not logged, the caller tries a cheaper model first)."""
    now = int(now or time.time())
    est = max(0.0, float(est_usd or 0))
    m = spent(con, month_start(now))
    why, period = None, None
    mcap = MONTH_USD - MONTH_RESERVE.get(kind, 0.0)
    if m + est > mcap:
        why = (f"mjesečni strop {MONTH_USD:.2f} $ (potrošeno {m:.3f} $"
               + (f", {MONTH_RESERVE[kind]:.0f} $ čuva se za važnije pozive" if mcap < MONTH_USD else "") + ")")
        period = f"mjesec:{kind}:{month_start(now)}"
    elif kind in ROUTINE:
        d = spent(con, day_start(now), ROUTINE)
        keep = []
        if kind in ("trades", "daily"):
            keep.append(("live komentare", LIVE_RESERVE_USD))
        if kind == "trades" and not daily_done(con, now):
            keep.append(("dnevni pregled", DAILY_RESERVE_USD))
        cap = DAY_USD - sum(x for _w, x in keep)
        if d + est > cap:
            why = (f"dnevni strop {DAY_USD:.2f} $ (potrošeno {d:.3f} $"
                   + "".join(f", {x:.2f} $ čuva se za {w}" for w, x in keep) + ")")
            period = f"dan:{kind}:{day_start(now)}"
    elif kind == "deep" and est > DEEP_USD:
        why = f"strop dubinske sesije {DEEP_USD:.2f} $ (procjena {est:.3f} $)"
        period = f"deep:{day_start(now)}"
    if why and not quiet and kv_get(con, f"budget_log:{kind}") != period:
        kv_put(con, f"budget_log:{kind}", period)
        log(f"kritičar: {why}, nema više poziva vrste {kind} do novog razdoblja", flush=True)
    return why


def pick(con, kind, preferred, chars, max_out, now=None, log=print):
    """(model, est USD) for the next call of `kind`: the preferred model when it fits, else the cheap one; the cheap
    one first for re-checks and live comments once openai_api.CHEAP_AT of the day's budget is used. (None, reason)
    when neither fits (logged once a period)."""
    from critic import openai_api
    now = int(now or time.time())
    order = [preferred]
    cheap = openai_api.MODEL_CHEAP
    if cheap and cheap != preferred:
        if kind in ("trades", "live") and spent(con, day_start(now), ROUTINE) > openai_api.CHEAP_AT * DAY_USD:
            order = [cheap]
        else:
            order.append(cheap)
    why = None
    for i, m in enumerate(order):
        est = openai_api.max_cost(m, chars, max_out)
        why = refusal(con, kind, est, now, log, quiet=i < len(order) - 1)
        if why is None:
            return m, est
    return None, why


def budget(con, now=None):
    now = int(now or time.time())
    return {"dan_usd": round(spent(con, day_start(now), ROUTINE), 4), "dan_strop": DAY_USD,
            "mjesec_usd": round(spent(con, month_start(now)), 4), "mjesec_strop": MONTH_USD,
            "dubinski_strop_sesije": DEEP_USD}


# ---------- verdicts and their measurement ----------------------------------------------------------------------------

def add_verdict(con, call_id, note_id, pos, v, now=None):
    con.execute("INSERT INTO critic_verdicts (ts, call_id, note_id, pid, token, symbol, mode, strategy, verdict, "
                "confidence, pnl_pct, mc0, value_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(now or time.time()), call_id, note_id, pos["pid"], pos["token"], pos.get("sym"), pos.get("mode"),
                 pos.get("strategy"), v["verdict"], v["confidence"], pos.get("pnl_pct"), pos.get("mc_now"),
                 pos.get("value_usd")))


def last_verdicts(con, pids):
    """{pid: (ts, pnl_pct, verdict)} of the newest verdict per position."""
    ids = [int(p) for p in pids if p]
    if not ids:
        return {}
    out = {}
    for pid, ts, pnl, verdict in con.execute(
            f"SELECT pid, ts, pnl_pct, verdict FROM critic_verdicts WHERE pid IN ({','.join('?' * len(ids))}) "
            "ORDER BY id", ids):
        out[pid] = (ts, pnl, verdict)
    return out


def mc_at(token, ts, snaps=None):
    """The market cap stored nearest to ts (within MATCH_S) in our own snapshots (range.db snaps, hype.db token_pulse),
    or None. snaps: the test seam (a list of {"ts", "mcap"})."""
    if snaps is None:
        snaps = []
        try:
            from rangedca import data as rdata
            con = rdata.ro()
            try:
                if con is not None:
                    snaps += rdata.own_rows(con, token, ts - MATCH_S)
            finally:
                if con is not None:
                    con.close()
            snaps += rdata.pulse_rows(token, ts - MATCH_S)
        except Exception:  # noqa: BLE001 - no stored data: the live price or nothing
            snaps = []
    best = min((s for s in snaps if s.get("mcap") and abs(s["ts"] - ts) <= MATCH_S),
               key=lambda s: abs(s["ts"] - ts), default=None)
    return float(best["mcap"]) if best else None


def _closed(tcon, row):
    """(closed, closed_ts) of the position group behind a verdict: no open lot of its token and mode left."""
    pid, token, mode = row["pid"], row["token"], row["mode"]
    left = tcon.execute("SELECT COUNT(*) FROM positions WHERE token=? AND COALESCE(mode,'dry')=? AND status IN "
                        "('open','pending') AND id >= ?", (token, mode or "dry", pid)).fetchone()[0]
    if left:
        return False, None
    r = tcon.execute("SELECT MAX(closed_ts) FROM positions WHERE token=? AND COALESCE(mode,'dry')=? AND id >= ?",
                     (token, mode or "dry", pid)).fetchone()
    return True, (int(r[0]) if r and r[0] else None)


def evaluate(con, now=None, live=None, mc_at_fn=None, live_fn=None):
    """Fill the +30 / +60 min and the close market caps of open verdict rows. A point is read from our stored
    snapshots (mc_at_fn, default mc_at); one still missing while it is fresh (within 2 x MATCH_S of its time) takes
    the live market cap: `live` ({token: mcap}) or live_fn(tokens) called ONCE for all such tokens (free DexScreener).
    A point not measurable EVAL_LATE_S after its time is given up (0). The close comes from trade.db positions (no
    open lot of the token and mode left). Returns how many rows changed."""
    now = int(now or time.time())
    fn = mc_at_fn or mc_at
    rows = con.execute("SELECT id, ts, pid, token, mode, mc30, mc60, mc_close, closed_ts FROM critic_verdicts "
                       "WHERE done=0 ORDER BY id LIMIT 500").fetchall()
    plans, want = [], set()
    for vid, ts, pid, token, mode, mc30, mc60, mcc, cts in rows:
        upd, need = {}, {}
        for col, h, cur in (("mc30", 1800, mc30), ("mc60", 3600, mc60)):
            if cur is not None or now < ts + h:
                continue
            x = fn(token, ts + h)
            if x is not None:
                upd[col] = x
            elif now - (ts + h) <= MATCH_S * 2:
                need[col] = True
            elif now - (ts + h) > EVAL_LATE_S:
                upd[col] = 0.0
        if cts is None:
            try:
                closed, cts_new = _closed(con, {"pid": pid, "token": token, "mode": mode})
            except sqlite3.Error:
                closed, cts_new = False, None
            if closed:
                cts_new = cts_new or now
                upd["closed_ts"] = cts_new
                x = fn(token, cts_new)
                if x is not None:
                    upd["mc_close"] = x
                elif now - cts_new <= MATCH_S * 2:
                    need["mc_close"] = True
                else:
                    upd["mc_close"] = 0.0
        if need:
            want.add(token)
        plans.append((vid, ts, token, mc30, mc60, cts, upd, need))
    if want and live is None and live_fn is not None:
        try:
            live = live_fn(sorted(want)) or {}
        except Exception:  # noqa: BLE001 - no live price: the point waits for the next pass (or is given up)
            live = {}
    live = live or {}
    changed = 0
    for vid, ts, token, mc30, mc60, cts, upd, need in plans:
        for col in need:
            x = live.get(token)
            if x:
                upd[col] = float(x)
            elif col == "mc_close":
                upd[col] = 0.0
        m30, m60 = upd.get("mc30", mc30), upd.get("mc60", mc60)
        if m30 is not None and m60 is not None and (upd.get("closed_ts", cts) is not None or now - ts > DONE_AFTER_S):
            upd["done"] = 1
        if upd:
            con.execute(f"UPDATE critic_verdicts SET {', '.join(f'{k}=?' for k in upd)} WHERE id=?",
                        [*upd.values(), vid])
            changed += 1
    if changed:
        con.commit()
    return changed


def score(verdict, mc0, mc_h, closed_ts=None, mc_close=None, ts=None, horizon_s=None):
    """(hit True/False/None, delta fraction vs the bot or None) of one verdict at one horizon. mc_h: MC at the
    horizon (0/None = not measured). closed_ts / mc_close: the bot's exit when it came before the horizon."""
    if not mc0 or not mc_h:
        return None, None
    r = mc_h / mc0 - 1
    hit = (r <= -HIT_BAND) if verdict in SELL_KIND else (r > -HIT_BAND)
    f = SELL_SHARE.get(verdict)
    if f is None:
        return hit, None
    bot_r = r
    if closed_ts and mc_close and (horizon_s is None or (ts is not None and closed_ts <= ts + horizon_s)):
        bot_r = mc_close / mc0 - 1
    adv_r = (1 - f) * r
    return hit, adv_r - bot_r


def stats(con, days=7, now=None):
    """The critic's own numbers over `days`: calls, cost per kind, and per verdict the hit rate at +30 / +60 min and
    at the close, and the USD the advice would have saved (+) or lost (-) against what the bot did."""
    now = int(now or time.time())
    since = now - int(days) * 86400
    calls = {}
    for kind, n, ok, usd, tin, tout in con.execute(
            "SELECT kind, COUNT(*), SUM(ok), COALESCE(SUM(cost_usd), 0), COALESCE(SUM(tokens_in), 0), "
            "COALESCE(SUM(tokens_out), 0) FROM critic_calls WHERE ts >= ? GROUP BY kind", (since,)):
        calls[kind] = {"poziva": n, "uspjelo": ok or 0, "usd": round(usd, 4), "tokena_ulaz": tin, "tokena_izlaz": tout}
    per = {}
    for (verdict, ts, mc0, mc30, mc60, mcc, cts, val) in con.execute(
            "SELECT verdict, ts, mc0, mc30, mc60, mc_close, closed_ts, value_usd FROM critic_verdicts WHERE ts >= ?",
            (since,)):
        p = per.setdefault(verdict, {"n": 0, "h30": [0, 0], "h60": [0, 0], "hz": [0, 0], "usd60": 0.0, "usdz": 0.0})
        p["n"] += 1
        for key, mch, hs in (("h30", mc30, 1800), ("h60", mc60, 3600), ("hz", mcc, None)):
            hit, delta = score(verdict, mc0, mch, cts, mcc, ts, hs)
            if hit is None:
                continue
            p[key][0] += 1
            p[key][1] += 1 if hit else 0
            if delta is not None and val and key in ("h60", "hz"):
                p["usd60" if key == "h60" else "usdz"] += delta * val
    out_v = {}
    names = {"h30": "30", "h60": "60", "hz": "zatvaranje"}
    for v, p in per.items():
        out_v[v] = {"n": p["n"],
                    **{f"pogodak_{w}": (round(p[k][1] / p[k][0], 3) if p[k][0] else None) for k, w in names.items()},
                    **{f"izmjereno_{w}": p[k][0] for k, w in names.items()},
                    "usd_60min": round(p["usd60"], 2), "usd_zatvaranje": round(p["usdz"], 2)}
    sugg = {}
    try:
        from critic import notes as cnotes
        sugg = cnotes.suggestion_status(con, since)
    except Exception:  # noqa: BLE001 - no notes table yet
        sugg = {}
    total = sum(c["usd"] for c in calls.values())
    return {"dana": days, "pozivi": calls, "ukupno_usd": round(total, 4),
            "poziva": sum(c["poziva"] for c in calls.values()), "presude": out_v, "prijedlozi": sugg,
            "budzet": budget(con, now)}


def stats_line(s):
    """One sentence of stats() for the daily note, the log and the report."""
    v = s.get("presude") or {}
    parts = []
    for name, d in sorted(v.items(), key=lambda kv: -kv[1]["n"]):
        h = d.get("pogodak_60") if d.get("pogodak_60") is not None else d.get("pogodak_30")
        parts.append(f"{name} {d['n']}" + (f" (pogodak 60 min {h * 100:.0f} %)" if h is not None else ""))
    usd = sum((d.get("usd_60min") or 0) for d in v.values())
    return (f"Kritičar {s.get('dana')} d: {s.get('poziva', 0)} poziva, {s.get('ukupno_usd', 0):.3f} $; presude: "
            + (", ".join(parts) or "nema") + f"; da su praćene (60 min): {usd:+.2f} $").replace(".", ",")
