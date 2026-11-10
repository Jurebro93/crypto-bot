"""Everything the morning report needs, from the databases the loops already fill (no paid API calls).

Each section is collected on its own and degrades to None/[] when its database or table does not exist yet,
so a fresh deploy still gets a report. All connections are read-only."""
import json
import os
import sqlite3
import statistics
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86400
# UTC trading sessions, same as kol/sessions.py and exits/paths.py
SESSIONS = [("asia", 0, 8), ("eu", 8, 14), ("us", 14, 24)]
NAMES = {"asia": "Azija", "eu": "Europa", "us": "SAD"}


def db_path(name):
    return os.path.join(os.environ.get("REPORT_DB_DIR") or HERE, name)


def ro(name):
    p = db_path(name)
    if not os.path.exists(p) or os.path.getsize(p) == 0:
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    except sqlite3.Error:
        return []


def session_of(ts):
    h = time.gmtime(ts).tm_hour
    return next(s for s, a, b in SESSIONS if a <= h < b)


def _learned_dir():
    try:
        from learn import weights
        return weights.LEARNED_DIR
    except Exception:
        return os.environ.get("LEARNED_DIR") or os.path.join(HERE, "learned")


# ---------- what the bot learned in the last 24 h ----------

def weight_changes(now):
    con = ro("hype.db")
    rows = _q(con, "SELECT * FROM learn_runs WHERE ts >= ? ORDER BY ts", (now - DAY,))
    last = _q(con, "SELECT ts, klasa FROM learn_runs WHERE applied = 1 ORDER BY ts DESC LIMIT 1")
    if con:
        con.close()
    out = []
    for r in rows:
        try:
            old, new = json.loads(r["old"] or "{}"), json.loads(r["new"] or "{}")
        except ValueError:
            old, new = {}, {}
        deltas = []
        for k in set(old) | set(new):
            a, b = old.get(k), new.get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(b - a) > 1e-9:
                deltas.append((k, a, b))
        deltas.sort(key=lambda d: -abs(d[2] - d[1]))
        out.append({"klasa": r["klasa"], "ts": r["ts"], "n": r["n"], "applied": bool(r["applied"]),
                    "metric_old": r["metric_old"], "metric_new": r["metric_new"], "note": r["note"],
                    "top": [{"feature": k, "old": round(a, 3), "new": round(b, 3)} for k, a, b in deltas[:6]]})
    return {"runs": out, "last_applied": last[0] if last else None}


def exit_changes(now):
    try:
        with open(os.path.join(_learned_dir(), "exits.json")) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {"changed": [], "runs": [], "profiles": 0}
    changed = []
    for k, p in (state.get("profiles") or {}).items():
        if (p.get("ts") or 0) >= now - DAY:
            ev = p.get("eval") or {}
            changed.append({"profil": k, "v": p.get("v"), "params": p.get("params"), "eval": ev,
                            "prev_params": (p.get("prev") or {}).get("params")})
    runs = [r for r in state.get("runs", []) if (r.get("ts") or 0) >= now - DAY]
    return {"changed": changed, "runs": runs, "profiles": len(state.get("profiles") or {})}


def session_accuracy():
    con = ro("kol.db")
    rows = _q(con, "SELECT key, n, hits, med_max24, factor FROM sessions")
    if con:
        con.close()
    out = {}
    for r in rows:
        kind, _, s = r["key"].partition(":")
        if s in NAMES and kind in ("signal", "call", "vol"):
            out.setdefault(s, {})[kind] = {"n": r["n"], "hit": (r["hits"] / r["n"]) if r["n"] else None,
                                           "med_max24": r["med_max24"], "factor": r["factor"]}
    return out


# ---------- KOLs ----------

def kols(now, top=10):
    con = ro("kol.db")
    if con is None:
        return {"top": [], "watch": [], "best_calls": [], "new_kols": 0, "calls_24h": 0}
    best = []
    for r in _q(con, "SELECT handle, score, followers, stats FROM kols WHERE score IS NOT NULL ORDER BY score DESC "
                     "LIMIT 60"):
        s = json.loads(r["stats"] or "{}")
        if (s.get("measured") or 0) < 3:
            continue
        best.append({"handle": r["handle"], "score": round(r["score"], 1), "followers": r["followers"],
                     "measured": s.get("measured"), "hit_rate": s.get("hit_rate"), "med_max24": s.get("med_max24"),
                     "late": s.get("prepump_rate"), "rug_rate": s.get("rug_rate"), "region": s.get("region"),
                     "med_views": s.get("med_views"), "confidence": s.get("confidence")})
        if len(best) >= top:
            break
    watch = [r["handle"] for r in _q(con, "SELECT handle FROM watch ORDER BY score DESC")]
    calls = _q(con, "SELECT handle, symbol, token, url, ts, followers, views, r1h, r6h, max24, mcap0 FROM calls "
                    "WHERE kind = 'call' AND first_by_kol = 1 AND bad IS NULL AND ts >= ? ORDER BY COALESCE(max24, r6h, r1h, -1) DESC "
                    "LIMIT 8", (now - 2 * DAY,))
    n24 = _q(con, "SELECT COUNT(*) n FROM calls WHERE kind = 'call' AND ts >= ?", (now - DAY,))
    new = _q(con, "SELECT COUNT(*) n FROM kols WHERE first_seen >= ?", (now - DAY,))
    con.close()
    return {"top": best, "watch": watch, "best_calls": calls, "calls_24h": n24[0]["n"] if n24 else 0,
            "new_kols": new[0]["n"] if new else 0}


# ---------- tokens ----------

def _shares(hours):
    tot = {s: 0.0 for s in NAMES}
    for h, v in hours.items():
        tot[session_of(h)] += v or 0
    sm = sum(tot.values())
    return {s: v / sm for s, v in tot.items()} if sm > 0 else {}


def today_tokens(now, sess_acc, limit=8, active_h=2, min_mcap=5000):
    """Real candidates only: passed the T0 rug sieve, traded in the last active_h hours, mcap >= min_mcap
    (2.11.: 6 of 8 listed tokens were dead ~2k$ tokens that never passed T0). Ranked by score x learned factor of the session
    their volume concentrates in; tokens peaking in the sessions still ahead today come first."""
    hype = ro("hype.db")
    rows = _q(hype, "SELECT token, symbol, klasa, razina, t0, score, mcap, liquidity, age_h, last_ts FROM token_tier "
                    "WHERE last_ts >= ? AND razina >= 1 AND t0 = 'prolaz' AND COALESCE(mcap, 0) >= ? "
                    "ORDER BY score DESC LIMIT 200", (now - active_h * 3600, min_mcap))
    if hype:
        hype.close()
    if not rows:
        return {"now": session_of(now), "tokens": []}
    kol = ro("kol.db")
    hours, sig = {}, {}
    marks = ",".join("?" * len(rows))
    for r in _q(kol, f"SELECT token, hour, volume FROM token_hours WHERE token IN ({marks})", [r["token"] for r in rows]):
        hours.setdefault(r["token"], {})[r["hour"]] = r["volume"]
    for r in _q(kol, f"SELECT token, n_good, n_authors, handles, dev_selling, ts FROM signals WHERE token IN ({marks})",
                [r["token"] for r in rows]):
        sig[r["token"]] = r
    if kol:
        kol.close()
    cur = session_of(now)
    order = [s for s, _, _ in SESSIONS]
    ahead = order[order.index(cur):]
    out = []
    for r in rows:
        sh = _shares(hours.get(r["token"], {}))
        dom = max(sh, key=sh.get) if sh and max(sh.values()) >= 0.45 else None
        a = sess_acc.get(dom) or {}
        best = max((x for x in (a.get("signal"), a.get("call")) if x), key=lambda x: x.get("n") or 0, default={})
        f = best.get("factor") or 1.0
        s = sig.get(r["token"])
        kol_bonus = 1.15 if s and s["n_good"] and not s["dev_selling"] else 1.0
        rank = (r["score"] or 0) * f * kol_bonus * (1.1 if dom in ahead else 1.0)
        out.append({**r, "shares": sh, "dominant": dom, "factor": f, "rank": round(rank, 1),
                    "kol": (s["handles"] if s else None), "ahead": dom in ahead})
    out.sort(key=lambda x: -x["rank"])
    return {"now": cur, "tokens": out[:limit]}


def pulse(now, limit=8):
    """Tokens whose holders and volume kept growing over the last 24 h (token_pulse, hype/pulse.py)."""
    con = ro("hype.db")
    rows = _q(con, "SELECT p.token, p.ts, p.vol_h1, p.holders, p.mcap, p.buys_h1, p.sells_h1, t.symbol, t.klasa "
                   "FROM token_pulse p LEFT JOIN token_tier t ON t.token = p.token WHERE p.ts >= ? ORDER BY p.token, p.ts",
              (now - DAY,))
    if con:
        con.close()
    by = {}
    for r in rows:
        by.setdefault(r["token"], []).append(r)
    out = []
    for tok, rs in by.items():
        # one reading per hour (the scan writes every 2 min)
        hourly = {}
        for r in rs:
            hourly[r["ts"] // 3600] = r
        hs = [hourly[k] for k in sorted(hourly)]
        held = [r["holders"] for r in hs if r["holders"]]
        vols = [r["vol_h1"] or 0 for r in hs]
        if len(hs) < 3 or len(held) < 3 or held[0] <= 0:
            continue
        ups = sum(1 for a, b in zip(held, held[1:]) if b >= a) / (len(held) - 1)
        growth = held[-1] / held[0] - 1
        half = len(vols) // 2
        v1, v2 = (sum(vols[:half]) / max(half, 1)), (sum(vols[half:]) / max(len(vols) - half, 1))
        vtrend = (v2 / v1 - 1) if v1 > 0 else None
        vret = (vols[-1] / max(vols)) if max(vols) > 0 else None
        if growth <= 0:
            continue
        score = growth * ups * (1 + max(min(vtrend or 0, 2), -0.9))
        out.append({"token": tok, "symbol": rs[-1]["symbol"], "klasa": rs[-1]["klasa"], "hours": len(hs),
                    "holders0": held[0], "holders1": held[-1], "growth": growth, "consistency": ups,
                    "vol_trend": vtrend, "vol_retention": vret, "mcap": hs[-1]["mcap"], "score": score,
                    "holders_series": held[-24:], "vol_series": vols[-24:]})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# ---------- demo trading ----------

def paper(now):
    con = ro("paper.db")
    closed = _q(con, "SELECT symbol, token, ret, pnl_usd, exit_reason, max_ret, closed_ts FROM trades "
                     "WHERE status = 'closed' AND closed_ts >= ?", (now - DAY,))
    opened = _q(con, "SELECT COUNT(*) n FROM trades WHERE opened_ts >= ?", (now - DAY,))
    open_now = _q(con, "SELECT COUNT(*) n FROM trades WHERE status != 'closed'")
    week = _q(con, "SELECT closed_ts, pnl_usd, ret FROM trades WHERE status = 'closed' AND closed_ts >= ?",
              (now - 7 * DAY,))
    if con:
        con.close()
    days = {}
    for r in week:
        d = time.strftime("%d.%m.", time.gmtime(r["closed_ts"]))
        x = days.setdefault(d, {"day": d, "pnl": 0.0, "n": 0, "wins": 0})
        x["pnl"] += r["pnl_usd"] or 0
        x["n"] += 1
        x["wins"] += 1 if (r["ret"] or 0) > 0 else 0
    rets = [r["ret"] for r in closed if r["ret"] is not None]
    closed.sort(key=lambda r: -(r["ret"] or -9))
    return {"closed": len(closed), "opened": opened[0]["n"] if opened else 0,
            "open_now": open_now[0]["n"] if open_now else 0,
            "wins": sum(1 for x in rets if x > 0), "pnl": sum(r["pnl_usd"] or 0 for r in closed),
            "median_ret": statistics.median(rets) if rets else None,
            "best": closed[:3], "worst": closed[-3:][::-1] if len(closed) > 3 else [],
            "week": [days[k] for k in sorted(days, key=lambda d: (d[3:5], d[:2]))]}


def market(now):
    try:
        from market import regime
        r = regime.at(now)
        return {"score": r["score"], "label": r["label"], "day": r["day"]} if r else None
    except Exception:
        return None


def collect(now=None):
    now = int(now or time.time())
    acc = session_accuracy()
    try:
        with open(os.path.join(HERE, "kol", "config.json")) as f:
            hit_x = json.load(f).get("hit_x", 0.5)
    except (OSError, ValueError):
        hit_x = 0.5
    data = {"ts": now, "kol_hit_definition": f"+{hit_x:.0%} u 24 h nakon poziva", "weights": weight_changes(now), "exits": exit_changes(now), "sessions": acc,
            "kols": kols(now), "today": today_tokens(now, acc), "pulse": pulse(now), "paper": paper(now),
            "market": market(now), "koltest": koltest(now), "rules": rules(now),
            "strategije": strategije(now), "spend": spend(now), "skener": skener(now)}
    return data


def skener(now):
    """The market scanner in shadow (scan/shadow.report_data): per source found / outcomes / +20 % within 1 h and 4 h
    / -30 % first / EV, the paper gate, lead time, today's spend per paid source. None before scan.db exists."""
    try:
        from scan import shadow, store
        path = db_path("scan.db") if os.environ.get("REPORT_DB_DIR") else store.db_path()
        con = store.ro(path)
        if con is None:
            return None
        try:
            return shadow.report_data(now, con=con)
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - never break the report on this section
        return None


def spend(now):
    """Only the urgent spend warnings (level bad) from usage/watch.py; the rest stays on the /usage page.
    [] when nothing is urgent."""
    try:
        import sqlite3
        from usage import meter, watch
        con = sqlite3.connect(f"file:{meter.DB}?mode=ro", uri=True, timeout=10)
        try:
            return [a for a in watch.evaluate(con, now=now) if a["level"] == "bad"]
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - never break the report on this section
        return []


def rules(now):
    """The 1.11. entry rules (paper/rules.py): rug share before/after the hard gate, what the gate refused, the
    $100k A/B, the 3-KOL trigger per session and the stake per session. None when nothing ran yet."""
    try:
        import sqlite3
        from paper import rules as R
        st = R.load()
        start = (st.get("since") or {}).get("gate")
        if not start:
            return None
        path = db_path("paper.db")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            out = {"since": start, "rug": R.rug_share(con, start), "gate": R.gate_shadow(con, start),
                   "kol3": R.by_session(con, "kol3", 14, now), "kol3_10": R.kol3_tight(con, 14, now),
                   "ab": st.get("ab"),
                   "sessions": (st.get("sessions") or {}).get("by") or {},
                   "refused_day": con.execute("SELECT COUNT(*) FROM candidates WHERE decision='skip_gate' AND "
                                              "first_ts>=?", (now - DAY,)).fetchone()[0]}
        finally:
            con.close()
        out["history"] = [h for h in st.get("history") or [] if h.get("ts", 0) >= now - DAY]
        return out
    except Exception:  # noqa: BLE001 - never break the report on this section
        return None


def strategije(now):
    """Five $1000 demo accounts by entry source (strat/, page /strategije), best first; None before the first entry."""
    try:
        from ui import strategije as sg
        return sg.report_data(now)
    except Exception:  # noqa: BLE001 - never break the report on this section
        return None


def koltest(now):
    """The separate 7-day KOL test book (koltest/, page /kol-test); None before it starts."""
    try:
        from ui import koltest as kt
        return kt.report_data(now)
    except Exception:  # noqa: BLE001 - never break the report on this section
        return None
