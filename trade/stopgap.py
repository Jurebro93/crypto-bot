"""Stop gaps: the PLANNED stop of every closed position against its ACTUAL exit, and why they differ (16.11., vlasnik,
jutarnji izvještaj: "demo pozicija zatvorena na -59,4 % dok je SL bio oko -20 %").

Recorded at the close (league.db stop_gaps, written by its only writer run_ui: veliki/live.close for the midcap range,
demo AND real account; league/auto for the TP/SL stops of the demo trades, the real account's included):

  stop_px / exit_px   the stop in force at the close (after a break-even move or a tightening) and the exit price
  plan_pct / exit_pct both against the (average) entry, in %; gap_pp = exit_pct - plan_pct (negative = worse than the
                      plan, in percentage points)
  why                 classify(): rug (the pool pulled / the rug check), pad likvidnosti (liquidity >= 50 % under the
                      last hour's high), zastarjela cijena (the quote, or the gap since the previous one, older than
                      STALE_S: no price while it fell), gap (fresh quotes, the price jumped through the stop between
                      two of them), u okviru (within GAP_PP of the plan); an exit above the stop is "iznad stopa"

Read (rows / worst): the recorded rows, plus what the older data already allows (no "why" there: "nepoznato"):
veliki_trades and the TP/SL demo trades closed before the recording (league.db), the real fills of exit plans
(trade.db exit_fills: level vs fill) and of the real positions behind a recorded demo stop (positions.real_exit_px),
the paper bot's stops (paper.db: its sl vs its result). Read-only; never raises (the report calls it).
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STALE_S = 60          # a quote older than this (or this long since the previous one) is stale (veliki/live.STALE_S)
GAP_PP = 2.0          # an exit more than this many points under the planned stop is a gap
LIQ_DROP = 0.5        # liquidity at or under half of the last hour's high = a liquidity drop
LIQ_WINDOW_S = 3600
SCHEMA = """CREATE TABLE IF NOT EXISTS stop_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, src TEXT, ref_id INTEGER, trade_id INTEGER, user TEXT,
    token TEXT, symbol TEXT, reason TEXT, entry_px REAL, stop_px REAL, exit_px REAL, plan_pct REAL, exit_pct REAL,
    gap_pp REAL, why TEXT, q_age_s REAL, q_gap_s REAL, liq_ref REAL, liq_exit REAL);
CREATE INDEX IF NOT EXISTS stop_gaps_ts ON stop_gaps (ts);
CREATE INDEX IF NOT EXISTS stop_gaps_ref ON stop_gaps (src, ref_id);"""
SRC_HR = {"veliki": "veliki", "tpsl": "TP/SL"}
WHY_HR = {"rug": "rug", "likvidnost": "pad likvidnosti", "zastarjelo": "zastarjela cijena", "gap": "gap (skok kroz stop)",
          "u_okviru": "u okviru plana", "iznad": "iznad stopa", "nepoznato": "nepoznato (prije bilježenja)"}


_ENSURED = set()


def ensure(con):
    """The table and its indexes, once per database file a process (no executescript: it would commit the caller's
    open transaction)."""
    try:
        key = con.execute("PRAGMA database_list").fetchone()[2]
    except sqlite3.Error:
        key = None
    if key and key in _ENSURED:
        return
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            con.execute(stmt)
    if key:
        _ENSURED.add(key)


def pcts(entry_px, stop_px, exit_px):
    """(plan_pct, exit_pct, gap_pp) against the entry, None where a price is missing."""
    if not entry_px or entry_px <= 0:
        return None, None, None
    plan = (stop_px / entry_px - 1) * 100 if stop_px else None
    ex = (exit_px / entry_px - 1) * 100 if exit_px is not None else None
    return plan, ex, (ex - plan if plan is not None and ex is not None else None)


def classify(gap_pp, reason=None, q_age_s=None, q_gap_s=None, liq_ref=None, liq_exit=None, rug=False):
    """The key of why the exit differs from the plan (WHY_HR)."""
    if rug or reason == "rug":
        return "rug"
    if reason == "likvidnost" or (liq_ref and liq_exit is not None and liq_exit <= LIQ_DROP * liq_ref):
        return "likvidnost"
    if gap_pp is None:
        return "nepoznato"
    if gap_pp > GAP_PP:
        return "iznad"
    if gap_pp >= -GAP_PP:
        return "u_okviru"
    if (q_age_s or 0) > STALE_S or (q_gap_s or 0) > STALE_S:
        return "zastarjelo"
    return "gap"


def record(con, src, ref_id, user, token, symbol, entry_px, stop_px, exit_px, reason=None, now=None, trade_id=None,
           q_age_s=None, q_gap_s=None, liq_ref=None, liq_exit=None, rug=False):
    """One stop_gaps row (no commit: the caller's close commits). Never raises; returns the why key or None."""
    try:
        if not stop_px or not entry_px:
            return None
        plan, ex, gap = pcts(entry_px, stop_px, exit_px)
        why = classify(gap, reason, q_age_s, q_gap_s, liq_ref, liq_exit, rug)
        ensure(con)
        con.execute("INSERT INTO stop_gaps (ts, src, ref_id, trade_id, user, token, symbol, reason, entry_px, stop_px, "
                    "exit_px, plan_pct, exit_pct, gap_pp, why, q_age_s, q_gap_s, liq_ref, liq_exit) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (int(now or time.time()), src, ref_id, trade_id, user, token, symbol, reason, entry_px, stop_px,
                     exit_px, _r(plan), _r(ex), _r(gap), why, _r(q_age_s, 1), _r(q_gap_s, 1), liq_ref, liq_exit))
        return why
    except Exception as e:  # noqa: BLE001 - a measurement never stops an exit
        print(f"stopgap: zapis nije uspio ({type(e).__name__}: {e})", flush=True)
        return None


def _r(x, n=2):
    return round(float(x), n) if x is not None else None


class Window:
    """The last LIQ_WINDOW_S of quotes per token, in the memory of the loop that prices them every few seconds:
    note() each quote (one point per BUCKET_S kept, the bucket's highest liquidity); ref() = the hour's highest
    liquidity; gap() = seconds between the newest quote and the one before (a quote noted twice counts once)."""
    BUCKET_S = 10

    def __init__(self, window_s=LIQ_WINDOW_S):
        self.window_s = window_s
        self.liq = {}     # token -> [[ts, liq]]
        self.last = {}    # token -> (ts of the newest quote, ts of the one before)

    def note(self, token, ts, liq):
        prev = self.last.get(token)
        if prev is not None and ts <= prev[0]:
            return   # the same quote again
        self.last[token] = (ts, prev[0] if prev else None)
        if not liq or liq <= 0:   # a read of 0 is no measurement
            return
        pts = self.liq.setdefault(token, [])
        if pts and ts - pts[-1][0] < self.BUCKET_S:
            pts[-1][1] = max(pts[-1][1], float(liq))
        else:
            pts.append([ts, float(liq)])
        cut = ts - self.window_s
        while pts and pts[0][0] < cut:
            pts.pop(0)
        if len(self.liq) > 2000:   # tokens no longer priced
            try:
                for t in [t for t, p in list(self.liq.items()) if not p or p[-1][0] < cut]:
                    self.liq.pop(t, None)
                    self.last.pop(t, None)
            except (RuntimeError, IndexError):   # another thread noted meanwhile: the next note prunes
                pass

    def ref(self, token, now, extra=None):
        """The highest liquidity of the last hour (extra: (ts, liq) of the entry, counted when inside the hour)."""
        vals = [v for t, v in list(self.liq.get(token, [])) if t >= now - self.window_s]
        if extra and extra[0] and extra[1] and extra[0] >= now - self.window_s:
            vals.append(float(extra[1]))
        return max(vals) if vals else None

    def gap(self, token):
        cur = self.last.get(token)
        return (cur[0] - cur[1]) if cur and cur[1] else None


# ---------- read: every closed position's plan against its exit ------------------------------------------------------

def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _paths(db_dir=None):
    d = db_dir or os.environ.get("REPORT_DB_DIR")
    if d:
        return {k: os.path.join(d, k) for k in ("league.db", "trade.db", "paper.db")}
    try:
        from league import store as lstore
        lg = lstore.DB
    except Exception:  # noqa: BLE001
        lg = os.path.join(ROOT, "league.db")
    try:
        from trade import settings
        td = settings.DB
    except Exception:  # noqa: BLE001
        td = os.path.join(ROOT, "trade.db")
    return {"league.db": lg, "trade.db": td, "paper.db": os.path.join(ROOT, "paper.db")}


def _has(con, table):
    try:
        return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
    except sqlite3.Error:
        return False


def _row(src, ts, token, symbol, user, plan, ex, why, reason=None, ref=None, q_age=None, liq_ref=None, liq_exit=None):
    gap = ex - plan if plan is not None and ex is not None else None
    return {"izvor": src, "ts": int(ts or 0), "token": token, "simbol": symbol, "racun": user, "ref": ref,
            "izlaz": reason, "plan_stop_pct": _r(plan, 1), "izlaz_pct": _r(ex, 1), "gap_pp": _r(gap, 1),
            "zasto": why, "zasto_hr": WHY_HR.get(why, why), "cijena_stara_s": _r(q_age, 0),
            "pad_likvidnosti_pct": _r((liq_exit / liq_ref - 1) * 100, 0) if liq_ref and liq_exit is not None else None}


def _league_rows(lg, since, real_user):
    out, seen = [], set()
    if _has(lg, "stop_gaps"):
        for r in lg.execute("SELECT * FROM stop_gaps WHERE ts >= ? ORDER BY ts", (since,)):
            seen.add((r["src"], r["ref_id"]))
            if r["trade_id"]:
                seen.add(("trade", r["trade_id"]))
            who = "pravi" if r["user"] == real_user else "demo"
            out.append(_row(f"{SRC_HR.get(r['src'], r['src'])} {who}", r["ts"], r["token"], r["symbol"], r["user"], r["plan_pct"],
                            r["exit_pct"], r["why"], r["reason"], r["ref_id"],
                            max(r["q_age_s"] or 0, r["q_gap_s"] or 0) or None, r["liq_ref"], r["liq_exit"]))
    vel_trades = set()
    if _has(lg, "veliki_trades"):
        cols = {c[1] for c in lg.execute("PRAGMA table_info(veliki_trades)")}
        dca = "dca_trade_id" if "dca_trade_id" in cols else "NULL"
        for r in lg.execute(f"SELECT id, user, token, symbol, closed_ts, entry_px, stop_px, exit_px, reason, trade_id, "
                            f"{dca} AS dca_tid FROM veliki_trades WHERE status='closed' AND closed_ts >= ?", (since,)):
            vel_trades.update(t for t in (r["trade_id"], r["dca_tid"]) if t)
            if ("veliki", r["id"]) in seen:
                continue
            plan, ex, gap = pcts(r["entry_px"], r["stop_px"], r["exit_px"])
            if plan is None:
                continue
            why = classify(gap, r["reason"]) if r["reason"] == "rug" or (gap is not None and gap >= -GAP_PP) \
                else "nepoznato"
            who = "pravi" if r["user"] == real_user else "demo"
            out.append(_row(f"veliki {who}", r["closed_ts"], r["token"], r["symbol"], r["user"], plan, ex, why,
                            r["reason"], r["id"]))
    if _has(lg, "exit_events"):   # the exit plans' stops (league/exitplan: level crossed, price, its age)
        cols = {c[1] for c in lg.execute("PRAGMA table_info(exit_events)")}
        if "level_px" in cols:
            for r in lg.execute("SELECT id, ts, user, token, trigger, price, level_px, px_age_s FROM exit_events WHERE "
                                "ts >= ? AND mode='izvršeno' AND trigger IN ('stop', 'trailing', 'katastrofa') AND "
                                "level_px > 0 AND price IS NOT NULL", (since,)):
                e = lg.execute("SELECT SUM(size_usd), SUM(size_usd / entry_px), MAX(symbol) FROM trades WHERE user=? "
                               "AND token=? AND entry_px > 0 AND closed_ts BETWEEN ? AND ?",
                               (r["user"], r["token"], r["ts"] - 5, r["ts"] + 5)).fetchone()
                entry = e[0] / e[1] if e and e[0] and e[1] else None
                plan, ex, gap = pcts(entry, r["level_px"], r["price"])
                if plan is None:   # no lot found: the gap against the level itself
                    plan, ex = 0.0, (r["price"] / r["level_px"] - 1) * 100
                    gap = ex
                why = classify(gap, q_age_s=r["px_age_s"])
                who = "pravi" if r["user"] == real_user else "demo"
                out.append(_row(f"plan izlaza {who}", r["ts"], r["token"], e[2] if e else None, r["user"], plan, ex,
                                why, r["trigger"], r["id"], r["px_age_s"]))
    if _has(lg, "trades"):
        for r in lg.execute("SELECT id, user, token, symbol, closed_ts, entry_px, exit_px, auto, exit_rule FROM trades "
                            "WHERE status='closed' AND closed_ts >= ? AND exit_rule IN ('sl', 'rug') "
                            "AND auto IS NOT NULL", (since,)):
            if r["id"] in vel_trades or ("trade", r["id"]) in seen or ("tpsl", r["id"]) in seen:
                continue
            try:
                a = json.loads(r["auto"] or "{}") or {}
            except ValueError:
                a = {}
            plan, ex, gap = pcts(r["entry_px"], a.get("sl_px"), r["exit_px"])
            if plan is None:
                continue
            why = "rug" if r["exit_rule"] == "rug" else (classify(gap) if gap is not None and gap >= -GAP_PP
                                                          else "nepoznato")
            who = "pravi" if r["user"] == real_user else "demo"
            out.append(_row(f"TP/SL {who}", r["closed_ts"], r["token"], r["symbol"], r["user"], plan, ex, why,
                            r["exit_rule"], r["id"]))
    return out


def _plan_px(lg, league_id):
    """The planned stop (USD per token) of the demo trade a real position mirrors, from the recorded row, veliki_trades
    or its TP/SL rule; None unknown."""
    if lg is None or not league_id:
        return None
    try:
        if _has(lg, "stop_gaps"):
            r = lg.execute("SELECT stop_px FROM stop_gaps WHERE trade_id=? ORDER BY id DESC LIMIT 1", (league_id,)).fetchone()
            if r and r[0]:
                return float(r[0])
        if _has(lg, "veliki_trades"):
            r = lg.execute("SELECT stop_px FROM veliki_trades WHERE trade_id=? ORDER BY id DESC LIMIT 1",
                           (league_id,)).fetchone()
            if r and r[0]:
                return float(r[0])
        r = lg.execute("SELECT auto FROM trades WHERE id=?", (league_id,)).fetchone()
        if r and r[0]:
            v = (json.loads(r[0]) or {}).get("sl_px")
            return float(v) if v else None
    except (sqlite3.Error, ValueError, TypeError):
        return None
    return None


def _trade_rows(td, lg, since):
    out = []
    if _has(td, "exit_fills"):
        for r in td.execute("SELECT ts, position_id, token, symbol, trigger, level_px, seen_px, fill_px, px_age_s, mode "
                            "FROM exit_fills WHERE ts >= ? AND fill_px IS NOT NULL AND level_px IS NOT NULL",
                            (since,)):
            if str(r["trigger"] or "") not in ("stop", "trailing", "katastrofa"):
                continue
            p = td.execute("SELECT league_id FROM positions WHERE id=?", (r["position_id"],)).fetchone()
            entry = None
            if p and p[0] and lg is not None:
                e = lg.execute("SELECT entry_px FROM trades WHERE id=?", (p[0],)).fetchone()
                entry = e[0] if e else None
            plan, ex, gap = pcts(entry, r["level_px"], r["fill_px"])
            if plan is None:   # no entry: the gap against the level itself
                plan, ex = 0.0, (r["fill_px"] / r["level_px"] - 1) * 100
                gap = ex
            why = classify(gap, q_age_s=r["px_age_s"])
            out.append(_row(f"pravi izlaz ({r['mode']})", r["ts"], r["token"], r["symbol"], "pravi", plan, ex, why,
                            r["trigger"], r["position_id"], r["px_age_s"]))
    if _has(td, "positions"):
        cols = {c[1] for c in td.execute("PRAGMA table_info(positions)")}
        if "real_exit_px" in cols and lg is not None:
            for r in td.execute("SELECT id, token, symbol, closed_ts, league_id, real_exit_px FROM positions WHERE "
                                "status='closed' AND mode='live' AND closed_ts >= ? AND real_exit_px IS NOT NULL "
                                "AND league_id IS NOT NULL", (since,)):
                stop = _plan_px(lg, r["league_id"])
                e = lg.execute("SELECT entry_px, exit_rule FROM trades WHERE id=?", (r["league_id"],)).fetchone()
                if not stop or not e or e[1] not in ("sl", "rug"):
                    continue
                plan, ex, gap = pcts(e[0], stop, r["real_exit_px"])
                why = "rug" if e[1] == "rug" else classify(gap)
                out.append(_row("pravi novac (swap)", r["closed_ts"], r["token"], r["symbol"], "pravi", plan, ex, why,
                                e[1], r["id"]))
    return out


def _paper_rows(pp, since):
    out = []
    if not _has(pp, "trades"):
        return out
    for r in pp.execute("SELECT id, token, symbol, closed_ts, exit_reason, ret, config FROM trades WHERE "
                        "status='closed' AND closed_ts >= ? AND exit_reason IN ('stop_loss', 'rug')", (since,)):
        try:
            sl = (json.loads(r["config"] or "{}") or {}).get("sl")
        except ValueError:
            sl = None
        if sl is None or r["ret"] is None:
            continue
        plan, ex = float(sl) * 100, float(r["ret"]) * 100
        gap = ex - plan
        why = "rug" if r["exit_reason"] == "rug" else (classify(gap) if gap >= -GAP_PP else "nepoznato")
        out.append(_row("paper bot", r["closed_ts"], r["token"], r["symbol"], "paper", plan, ex, why, r["exit_reason"],
                        r["id"]))
    return out


def rows(now=None, days=7, db_dir=None, lcon=None, tcon=None, pcon=None):
    """Every closed position of the last `days` with a planned stop: [row] (see _row), oldest first."""
    now = int(now or time.time())
    since = now - int(days) * 86400
    paths = _paths(db_dir)
    own = []
    lg = lcon or _ro(paths["league.db"])
    td = tcon or _ro(paths["trade.db"])
    pp = pcon or _ro(paths["paper.db"])
    own = [c for c, given in ((lg, lcon), (td, tcon), (pp, pcon)) if c is not None and given is None]
    rf = [(c, c.row_factory) for c in (lcon, tcon, pcon) if c is not None]
    for c, _f in rf:   # a caller's connection reads by name here, and gets its own row factory back below
        c.row_factory = sqlite3.Row
    try:
        try:
            from trade import settings
            real_user = settings.LEAGUE_USER
        except Exception:  # noqa: BLE001
            real_user = "pravi-trade"
        out = []
        for fn, args in ((_league_rows, (lg, since, real_user)), (_trade_rows, (td, lg, since)),
                         (_paper_rows, (pp, since))):
            if args[0] is None:
                continue
            try:
                out += fn(*args)
            except sqlite3.Error as e:
                print(f"stopgap: {fn.__name__}: {e}", flush=True)
        return sorted(out, key=lambda r: r["ts"])
    finally:
        for c, f in rf:
            c.row_factory = f
        for c in own:
            c.close()


def worst(now=None, days=7, n=10, db_dir=None, lcon=None, tcon=None, pcon=None):
    """What the morning report shows: {"dana", "zatvoreno_sa_stopom", "gapova", "medijan_gap_pp", "po_razlogu":
    {why_hr: n}, "najgori": [the n rows furthest under their planned stop, worst first]}. A gap = an exit more than
    GAP_PP points under the plan."""
    rs = rows(now, days, db_dir, lcon, tcon, pcon)
    stops = [r for r in rs if r["gap_pp"] is not None and r["gap_pp"] <= GAP_PP]
    gaps = sorted((r for r in stops if r["gap_pp"] < -GAP_PP), key=lambda r: r["gap_pp"])
    by = {}
    for r in gaps:
        by[r["zasto_hr"]] = by.get(r["zasto_hr"], 0) + 1
    vals = sorted(r["gap_pp"] for r in stops)
    med = None
    if vals:
        k = len(vals) // 2
        med = vals[k] if len(vals) % 2 else (vals[k - 1] + vals[k]) / 2
    return {"dana": days, "zatvoreno_sa_stopom": len(stops), "gapova": len(gaps), "medijan_gap_pp": _r(med, 1),
            "po_razlogu": by, "najgori": gaps[:n]}
