"""Kritičar (OpenAI): the numbers it reads, all from what the bot already stores (read-only; the only request is the
free DexScreener one for the open positions' live market, ui/prijedlog.live_market). Nothing here is sent anywhere
by itself: critic/trades.py and critic/daily.py build the payload and scrub it (critic/privacy.py).

Strategy statistics (strategy_stats): closed trades of the last `days` per strategy (trade/executor.strategy_of of the
source): the bot's two demo accounts in league.db (LEAGUE_USER's demo record, the paper account) and the real money
(trade.db positions mode live: SOL back + fees against SOL in). Per group: n, win rate, median, EV (mean, net of the
fees the record carries) with its 90 % interval (trade/edge.ev_stats), profit factor, max drawdown of the running
sum (percentage points), the top 3 wins' share of the profit, the exit rules, and the split by BTC regime at the entry
(market.db makro) and by Zagreb time of day.
"""
import bisect
import datetime as dt
import glob
import json
import os
import sqlite3
import statistics
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOL_MINT = "So11111111111111111111111111111111111111112"
TZ = "Europe/Zagreb"
ACCOUNTS = {"demo_zapis_pravog_racuna": "LEAGUE_USER", "demo_racun": "PAPER_USER"}   # label -> settings attribute


def _r(x, n=2):
    return round(float(x), n) if x is not None else None


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("PRAGMA busy_timeout = 10000")
        return con
    except sqlite3.Error:
        return None


# ---------- live market (free DexScreener) ---------------------------------------------------------------------------

def live_market(tokens):
    """({token: live row}, SOL in USD or None) in one DexScreener request per 30 tokens; ({}, None) on failure."""
    toks = [t for t in dict.fromkeys(tokens) if t]
    if not toks:
        return {}, None
    try:
        from ui import prijedlog
        lv = prijedlog.live_market(toks + [SOL_MINT])
    except Exception:  # noqa: BLE001
        lv = None
    if not lv:
        return {}, None
    sol = (lv.pop(SOL_MINT, None) or {}).get("price") or None
    return lv, sol


# ---------- statistics ------------------------------------------------------------------------------------------------

def summary(rets):
    """n, pogodak, medijan_pct, ev_pct, ev_lo90_pct, ev_hi90_pct, profit_factor, max_dd_pp, top3_udio of results
    (fractions, time order)."""
    xs = [float(x) for x in rets if x is not None]
    if not xs:
        return {"n": 0}
    from trade import edge
    s = edge.ev_stats(xs)
    wins = sum(x for x in xs if x > 0)
    losses = -sum(x for x in xs if x < 0)
    run = peak = dd = 0.0
    for x in xs:
        run += x
        peak = max(peak, run)
        dd = max(dd, peak - run)
    top3 = sum(sorted((x for x in xs if x > 0), reverse=True)[:3])
    total = sum(xs)
    return {"n": len(xs), "pogodak": _r(sum(1 for x in xs if x > 0) / len(xs), 3),
            "medijan_pct": _r(statistics.median(xs) * 100), "ev_pct": _r(s["ev"] * 100),
            "ev_lo90_pct": _r(s["lo90"] * 100) if s["lo90"] is not None else None,
            "ev_hi90_pct": _r(s["hi90"] * 100) if s["hi90"] is not None else None,
            "profit_factor": _r(wins / losses) if losses else None, "max_dd_pp": _r(dd * 100),
            "top3_udio_dobiti": _r(top3 / total, 2) if total > 0 else None}


def _makro_series(since):
    try:
        from market import store as mstore
        con = mstore.ro()
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return [], []
    try:
        rows = con.execute("SELECT ts, btc FROM makro WHERE ts >= ? ORDER BY ts", (int(since) - 86400,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    return [r[0] for r in rows], [r[1] for r in rows]


def _regime(ts_list, states, ts):
    i = bisect.bisect_right(ts_list, ts) - 1
    return states[i] if i >= 0 and ts - ts_list[i] < 6 * 3600 else "nepoznato"


def _part_of_day(ts):
    from zoneinfo import ZoneInfo
    h = dt.datetime.fromtimestamp(ts, ZoneInfo(TZ)).hour
    return "00-08" if h < 8 else ("08-16" if h < 16 else "16-24")


def _group(rows, makro):
    """rows: [(opened_ts, ret, exit_rule)] in time order -> summary + exits + regime / time-of-day splits."""
    out = summary([r[1] for r in rows])
    if not rows:
        return out
    ex = {}
    for r in rows:
        ex[r[2] or "?"] = ex.get(r[2] or "?", 0) + 1
    out["izlazi"] = dict(sorted(ex.items(), key=lambda kv: -kv[1])[:6])
    by_reg, by_tod = {}, {}
    for r in rows:
        by_reg.setdefault(_regime(*makro, r[0]), []).append(r[1])
        by_tod.setdefault(_part_of_day(r[0]), []).append(r[1])
    out["po_btc_rezimu"] = {k: {kk: v for kk, v in summary(xs).items() if kk in ("n", "pogodak", "ev_pct")}
                            for k, xs in by_reg.items()}
    out["po_dobu_dana"] = {k: {kk: v for kk, v in summary(xs).items() if kk in ("n", "pogodak", "ev_pct")}
                           for k, xs in sorted(by_tod.items())}
    return out


def strategy_stats(tcon=None, now=None, days=30, lpath=None, detail=True):
    """{strategy: {account label: group}}; detail=False: only n / pogodak / ev_pct / ev_lo90_pct (open trades)."""
    from trade import executor, settings
    now = int(now or time.time())
    since = now - days * 86400
    raw = {}
    try:
        from league import store as lstore
        lcon = _ro(lpath or lstore.DB)
    except Exception:  # noqa: BLE001
        lcon = None
    if lcon is not None:
        try:
            have = {r[1] for r in lcon.execute("PRAGMA table_info(trades)")}
            er = "exit_rule" if "exit_rule" in have else "NULL"
            for label, attr in ACCOUNTS.items():
                user = getattr(settings, attr)
                for ots, ret, src, rule in lcon.execute(
                        f"SELECT opened_ts, ret, source, {er} FROM trades WHERE user=? AND status='closed' AND "
                        "closed_ts >= ? AND ret IS NOT NULL ORDER BY closed_ts", (user, since)):
                    raw.setdefault(executor.strategy_of(src), {}).setdefault(label, []).append((ots or 0, ret, rule))
        except sqlite3.Error:
            pass
        finally:
            lcon.close()
    if tcon is not None:
        try:
            for ots, sin, sback, fees, why in tcon.execute(
                    "SELECT opened_ts, sol_in, sol_back, COALESCE(fees_sol, 0), reason FROM positions WHERE mode='live' "
                    "AND status='closed' AND closed_ts >= ? AND sol_in > 0 ORDER BY closed_ts", (since,)):
                raw.setdefault(executor.strategy_of(why), {}).setdefault("pravi_novac", []).append(
                    (ots or 0, ((sback or 0) - sin - (fees or 0)) / sin, None))
        except sqlite3.Error:
            pass
    makro = _makro_series(since) if detail else ([], [])
    out = {}
    for strat, accs in raw.items():
        out[strat] = {}
        for label, rows in accs.items():
            if detail:
                out[strat][label] = _group(rows, makro)
            else:
                s = summary([r[1] for r in rows])
                out[strat][label] = {k: s.get(k) for k in ("n", "pogodak", "ev_pct", "ev_lo90_pct")}
        d, p = out[strat].get("demo_zapis_pravog_racuna"), out[strat].get("pravi_novac")
        if detail and d and p and d.get("n") and p.get("n"):
            out[strat]["razlika_pravi_minus_demo_ev_pp"] = _r((p["ev_pct"] or 0) - (d["ev_pct"] or 0))
    return out


# ---------- context: macro, rules, changes, cost, reports ------------------------------------------------------------

def makro(now=None):
    try:
        from market import makro as mk
        r = mk.at(now or time.time())
    except Exception:  # noqa: BLE001
        r = None
    if not r:
        return None
    return {"btc": r.get("btc"), "eth": r.get("eth"), "sklonost_altovima": _r(r.get("score"), 2),
            "starost_h": _r(((now or time.time()) - r["ts"]) / 3600, 1)}


def rules(cfg=None):
    """The key rules and caps (numbers only)."""
    out = {}
    try:
        from trade import executor
        out["stropovi_pravog_novca"] = executor.switch_caps(cfg)
    except Exception:  # noqa: BLE001
        pass
    try:
        from trade import cost, edge
        out["ev_pravilo"] = edge.RULE_TEXT
        out["izlaz_signalnih_strategija"] = {"tp": edge.TP, "sl": edge.SL, "trailing": edge.TRAIL,
                                             "vrijeme_min": edge.TIME_MIN, "tp_udio": edge.TP_SHARE}
        out["trosak"] = {"fee_po_strani": cost.FEE_DEMO, "krug_fiksno": cost.FEE_ROUND_TRIP,
                         "slip_max": cost.SLIP_MAX, "min_likvidnost": cost.LIQ_HARD_MIN}
    except Exception:  # noqa: BLE001
        pass
    try:
        from rangedca import rules as rr
        keep = ("score_min", "entry_bottom", "lot1_share", "lot2_lo", "lot2_hi", "stop_x", "stop_min_pct",
                "stop_max_pct", "tp1_share", "tp1_net", "tp2_net", "trail", "time_stop_s")
        out["range"] = {name: {k: getattr(rr, name).get(k) for k in keep if k in getattr(rr, name)}
                        for name in ("RULES", "DEMO", "SCALP") if hasattr(rr, name)}
    except Exception:  # noqa: BLE001
        pass
    try:
        from league import exitplan
        out["plan_izlaza_zadani_sl_pct"] = exitplan.DEFAULT_PLAN_SL
    except Exception:  # noqa: BLE001
        pass
    if cfg:
        out["autopilot"] = {k: cfg.get(k) for k in ("size_sol", "max_open", "max_loss_day", "max_sol_per_day",
                                                    "tp_default", "sl_default", "max_cost_pct", "on")}
    return out


SAFE_KEYS = ("tp_default", "sl_default", "size_sol", "max_open", "max_loss_day", "max_sol_per_day", "max_cost_pct",
             "dca_token_cap", "runup_max", "range_scalp_trades_day", "range_scalp_target_usd", "on", "copy_cfg")


def recent_changes(tcon, now=None, days=7):
    """Settings changed in the last `days`: flags with their mode, the allow-listed limits with their value, every
    other key only by name (its value may be private)."""
    now = int(now or time.time())
    out = []
    try:
        rows = tcon.execute("SELECT k, v, ts FROM settings WHERE ts >= ? ORDER BY ts DESC LIMIT 60",
                            (now - days * 86400,)).fetchall()
    except sqlite3.Error:
        return out
    for k, v, ts in rows:
        try:
            val = json.loads(v)
        except ValueError:
            val = None
        when = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%d.%m. %H:%M UTC")
        if k.startswith("flag:"):
            out.append({"kada": when, "zastavica": k[5:], "mod": (val or {}).get("mode") if isinstance(val, dict) else val})
        elif k in SAFE_KEYS:
            out.append({"kada": when, "postavka": k, "vrijednost": val})
        elif not any(w in k.lower() for w in ("wallet", "key", "addr", "secret", "pass", "token", "invited", "mcp")):
            out.append({"kada": when, "postavka": k})
    return out


def cost_by_source(now=None):
    """The data cost of the last 7 days per source (usage/daily.week, the bot's own counts) without the per-job
    breakdown (internal names)."""
    try:
        from usage import daily
        w = daily.week(now)
    except Exception:  # noqa: BLE001
        return None
    if not w.get("dana"):
        return None
    return {k: w.get(k) for k in ("dana", "x_usd", "apify_usd_bot", "apify_racun_usd", "pumpportal_tradeova",
                                  "pumpportal_sol", "helius_bot", "helius_racun", "ai_usd", "ai_objava",
                                  "coingecko_kljuc", "coingecko_besplatno", "e429", "openai_usd", "openai_poziva")
            if w.get(k) is not None}


def compact(x, depth=0, max_list=8, max_str=240, max_depth=4):
    """A JSON-able copy with lists cut to max_list, strings to max_str and nesting to max_depth."""
    if depth > max_depth:
        return "…"
    if isinstance(x, dict):
        return {str(k): compact(v, depth + 1, max_list, max_str, max_depth) for k, v in list(x.items())[:40]}
    if isinstance(x, (list, tuple)):
        return [compact(v, depth + 1, max_list, max_str, max_depth) for v in list(x)[:max_list]]
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, str):
        return x[:max_str]
    return x


def _newest(pattern):
    files = sorted(glob.glob(os.path.join(ROOT, "output", pattern)))
    if not files:
        return None, None
    try:
        with open(files[-1]) as f:
            return json.load(f), os.path.getmtime(files[-1])
    except (OSError, ValueError):
        return None, None


def _age_h(ts, now):
    return _r((now - ts) / 3600, 1) if ts else None


def reports(now=None, budget_chars=2500):
    """The newest analyses the system made, each cut to about budget_chars of JSON: the EV report per flag
    (events/evreport, 23:30), the range and momentum backtests, the "zadnjih 5" walk-forward, the proposals' daily
    report. {name: {"starost_h", "sadrzaj"}}; a missing one is left out."""
    now = int(now or time.time())
    out = {}

    def put(name, obj, ts):
        if not obj:
            return
        c = compact(obj)
        s = json.dumps(c, ensure_ascii=False, default=str)
        lim, ml = 8, budget_chars
        while len(s) > ml and lim > 1:
            lim -= 2
            c = compact(obj, max_list=lim, max_str=160, max_depth=3)
            s = json.dumps(c, ensure_ascii=False, default=str)
        out[name] = {"starost_h": _age_h(ts, now), "sadrzaj": c if len(s) <= ml * 1.5 else s[:ml]}

    try:
        from events import evreport
        ev = evreport.latest()
        if ev:
            keep = ("flag", "phase", "part", "n", "n_outcomes", "hit_rate", "avg_pnl_pct", "ev_pct", "max_dd_pct",
                    "baseline_ev_pct", "delta_ev_pct", "note")
            rows = [{k: r.get(k) for k in keep if r.get(k) is not None}
                    for r in ev.get("rows") or [] if r.get("flag") != "openai_kritika"]
            put("ev_izvjestaj_po_zastavicama", {"dan": ev.get("day"), "redovi": rows[:30]}, None)
    except Exception:  # noqa: BLE001
        pass
    for name, pat in (("range_backtest", "range-backtest-*.json"), ("momentum_backtest", "momentum-backtest-*.json")):
        obj, ts = _newest(pat)
        put(name, obj, ts)
    try:
        from kol import zadnjih5
        z = zadnjih5.mcp(None, 5)
        if isinstance(z, dict) and "error" not in z:
            put("zadnjih5_walk_forward", z, None)
    except Exception:  # noqa: BLE001
        pass
    try:   # 15.11. (veliki/): the big tokens' range walk-forward per size (without / with BTC crashes) and its demo
        from veliki import view as vview
        v = vview.critic_summary()
        if v:
            put("veliki_tokeni_range", v, None)
    except Exception:  # noqa: BLE001
        pass
    try:   # 15.11. (oscilator/): the oscillating tokens' scalp walk-forward per size and its demo
        from oscilator import view as oview
        o = oview.critic_summary()
        if o:
            put("oscilator", o, None)
    except Exception:  # noqa: BLE001
        pass
    try:   # 15.11. (insajderi/): Insajderi 2.0: who bought before calls / jumps and sold into them, copyability
        from insajderi import report as i2report
        i2 = i2report.critic_summary()
        if i2:
            put("insajderi2", i2, i2.get("ts"))
    except Exception:  # noqa: BLE001
        pass
    try:   # 15.11. (konsenzus/): the source consensus walk-forward and its demo
        from konsenzus import view as kview
        k = kview.critic_summary()
        if k:
            put("konsenzus_izvora", k, None)
    except Exception:  # noqa: BLE001
        pass
    try:
        from proposals import store as pstore
        pcon = _ro(pstore.db_path()) if hasattr(pstore, "db_path") else None
        if pcon is not None:
            try:
                r = pcon.execute("SELECT day, ts, data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
            finally:
                pcon.close()
            if r:
                put("prijedlozi_dnevni_izvjestaj", json.loads(r[2] or "{}"), r[1])
    except Exception:  # noqa: BLE001
        pass
    return out
