"""The daily EV report per feature phase (11.11., Jure, point 4), 23:30 Zagreb (run_sched.py "evreport").

For every flag that is not off (trade/settings.FLAGS) and for the shadow measurements of the scanner, the groups and
the range strategy: signals, hit rate, average PnL %, EV per trade, max drawdown, and the baseline (the same thing
without the feature) where one can be defined. Stored in events.db ev_report (one row per day, flag, part) and in
output/ev-report-YYYYMMDD.{json,md}; the Autopilot page shows the newest day as one closed row under "Još".

How each phase is measured (window: since the flag's mode was set, at most WINDOW_D days):
  shadow   league.db shadow_decisions of the flag. A decision "entry -> skipped" (the rule would have skipped an entry
           the Autopilot made) is matched to the Autopilot's demo trade of that token opened within 15 min: its
           result is what the rule takes away. Without that trade, the token's path after the decision from
           events.db price ticks (TP +20 % / SL -30 % / out at 4 h, minus 2 %). hit = the trade ended in profit.
           EV with the feature = mean result of the Autopilot's closed trades WITHOUT the skipped ones; baseline =
           mean result of all its closed trades in the window; delta = the difference. Other decisions (whom to
           follow, an exit) get n and the token's path after them, no baseline (not definable from the log).
  paper    the paper account (PAPER_USER, it copies the Autopilot's follows with the paper flags on) vs the
           Autopilot's own demo trades in the same window = baseline. Several flags in paper share one paper
           account: the comparison is of the combination (said in the note).
  live     the Autopilot's demo trades since the switch vs the same length of time before it (baseline).
  scan     market_scan: scan.db shadow outcomes per source (TP +20 % / SL -30 % / 4 h, after cost; hit = +20 %
           within 4 h); baseline = the source "caller" (the same rule on the callers' tokens).
  groups   group_discovery: early.db group_signals per kind (hidden_group, caller_group_first); baseline = the mean
           EV of all calls of the window (events.db call_outcomes).
  range    range_dca: the paper rounds (league.db range_rounds); baseline: the newest backtest's EV when one exists.
           11.11. part range_oznake: the owner's learning labels (rangedca/owner.py, counterfactual: the booked rounds
           above are never changed by them), his pins and the watched ranges most similar to his labelled wins (also
           two log lines "range oznake vlasnika: ..." and "range slični ...").
           11.11. (range_missed G27): also split by the round's source, "range:missed" (skipped, then +20 % within
           60 min) vs "range:ostali" (its baseline): rounds, win rate, EV %, PnL $ and the missed live gate.
  momentum momentum_scalp (11.11.): the base rate of every signal (momentum.db; hit = +15 % before -10 % in 45 min,
           EV = the exit rules on the same path after cost) vs the newest backtest, and the paper trades vs that base
           rate with the live gate's verdict (>= 50 trades, EV > 0, hit >= 45 %; break-even is ~50 %, not 45 %).
  kalibracija  grok_ev_gate (11.11.): Grok's p_tp against the outcomes (Brier score, hit rate per p bucket).
  prijedlozi   proposals (11.11., proposals/report.py): per strategy the day's proposals, bought, hit rate (TP before SL
           within 4 h) and the measured EV vs the expected EV (baseline), the demo account's paper proof, and in the log
           and proposals.db reports the day's biggest risers we did not propose (seen / near miss / never saw).
  fast     fast_path (11.11., fast/report.py): the BUY decisions' measured outcome (+15 % before -10 % within 45 min)
           and per check its rejections, how many of them did >= +20 % within 60 min (false rejects) and how many saved
           a loss; the cost line per source in the log.
Max drawdown: the deepest fall of the running sum of results, in percentage points, in time order.
A promotion proposal (shadow -> paper -> live) only with n >= MIN_N outcomes and EV > 0, and only as text: the owner
switches flags by hand on the Autopilot page (trade/settings.set_flag); nothing here changes a flag.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import time
from zoneinfo import ZoneInfo

from events import outcomes, sources, store

TZ = "Europe/Zagreb"
WINDOW_D = 14
MIN_N = 20
MATCH_S = 900
SKIP_NEW = ("preskočeno", "odbij", "bez signala", "ne prati", "preskoči")
ENTER_OLD = ("ulaz", "kupi", "prati")
NEXT = {"shadow": "paper", "paper": "live"}
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def _r(x, nd=4):
    return round(x, nd) if x is not None else None


def summary(results):
    """{"n", "hit_rate", "avg_pnl_pct", "ev_pct", "max_dd_pct"} of a time-ordered list of fractions."""
    xs = [x for x in results if x is not None]
    if not xs:
        return {"n": 0, "hit_rate": None, "avg_pnl_pct": None, "ev_pct": None, "max_dd_pct": None}
    run = peak = dd = 0.0
    for x in xs:
        run += x
        peak = max(peak, run)
        dd = max(dd, peak - run)
    m = sum(xs) / len(xs)
    return {"n": len(xs), "hit_rate": _r(sum(1 for x in xs if x > 0) / len(xs)), "avg_pnl_pct": _r(m * 100, 2),
            "ev_pct": _r(m * 100, 2), "max_dd_pct": _r(dd * 100, 2)}


def _trades(lcon, user, since, until=None):
    """[(opened_ts, closed_ts, token, ret)] closed demo trades of `user` opened in the window, time-ordered."""
    if lcon is None:
        return []
    try:
        return lcon.execute("SELECT opened_ts, closed_ts, token, ret FROM trades WHERE user = ? AND status = 'closed' "
                            "AND opened_ts >= ? AND opened_ts < ? ORDER BY closed_ts",
                            (user, int(since), int(until or 4e9))).fetchall()
    except sqlite3.Error:
        return []


def _path_ev(econ, mint, ts, now):
    if econ is None or not mint:
        return None
    ticks = outcomes._ticks(econ, mint, ts - 300, ts + 5 * 3600)
    if not ticks:
        return None
    e = outcomes.entry_from_ticks(ticks, ts)
    if not e:
        return None
    return outcomes.metrics(outcomes.points_from_ticks(ticks), e[1], e[0], max(t for t, _ in ticks),
                            outcomes.TICK_TOL_S)["ev"]


def _proposal(mode, s, extra=""):
    nxt = NEXT.get(mode)
    if not nxt or (s.get("n") or 0) < MIN_N or (s.get("ev_pct") or 0) <= 0:
        return None
    return f"prijedlog: {mode} → {nxt} (n={s['n']}, EV {s['ev_pct']:+.2f} %){extra}; odobrava vlasnik ručno"


def flag_rows(name, st, lcon, econ, now, paper_flags=()):
    """[ev_report part rows (dicts)] of one flag. paper_flags: every flag in paper mode now."""
    from trade import settings
    mode = st["mode"]
    since = max(int(st.get("since") or 0), now - WINDOW_D * 86400)
    base_tr = _trades(lcon, settings.LEAGUE_USER, since, now)
    base = summary([t[3] for t in base_tr])
    row = {"flag": name, "phase": mode, "part": "flag", "baseline_ev_pct": base["ev_pct"], "baseline_n": base["n"]}
    if mode == "shadow":
        decs = []
        if lcon is not None:
            try:
                decs = lcon.execute("SELECT ts, token, old_action, new_action FROM shadow_decisions WHERE flag = ? AND "
                                    "ts >= ? ORDER BY ts", (name, since)).fetchall()
            except sqlite3.Error:
                decs = []
        skips, other = [], []
        for ts, tok, old, new in decs:
            is_skip = (new or "").lower().startswith(SKIP_NEW) and (old or "").lower().startswith(ENTER_OLD)
            (skips if is_skip else other).append((ts, tok))
        removed, results = set(), []
        for ts, tok in skips:
            hit = next((t for t in base_tr if t[2] == tok and abs(t[0] - ts) <= MATCH_S and t not in removed), None)
            if hit:
                removed.add(hit)
                results.append(hit[3])
            else:
                results.append(_path_ev(econ, tok if tok and MINT.fullmatch(tok) else None, ts, now))
        for ts, tok in other:
            results.append(_path_ev(econ, tok if tok and MINT.fullmatch(tok) else None, ts, now))
        s = summary(results)
        if skips:
            feat = summary([t[3] for t in base_tr if t not in removed])
            row.update(n=len(decs), n_outcomes=s["n"], hit_rate=s["hit_rate"], avg_pnl_pct=s["avg_pnl_pct"],
                       ev_pct=feat["ev_pct"], max_dd_pct=feat["max_dd_pct"],
                       delta_ev_pct=_r((feat["ev_pct"] or 0) - (base["ev_pct"] or 0), 2) if base["n"] else None,
                       note=f"{len(skips)} preskočenih ulaza: njihov prosjek {s['avg_pnl_pct']} %; EV = Autopilot bez njih")
            gate = {"n": feat["n"], "ev_pct": row["delta_ev_pct"]}
        else:
            row.update(n=len(decs), n_outcomes=s["n"], hit_rate=s["hit_rate"], avg_pnl_pct=s["avg_pnl_pct"],
                       ev_pct=s["ev_pct"], max_dd_pct=s["max_dd_pct"], delta_ev_pct=None, baseline_ev_pct=None,
                       note="odluke koje nisu preskok ulaza: put tokena nakon odluke, bez osnovice")
            gate = s
        row["proposal"] = _proposal(mode, {"n": s["n"], "ev_pct": gate.get("ev_pct")})
    elif mode == "paper":
        pap = summary([t[3] for t in _trades(lcon, settings.PAPER_USER, since, now)])
        others = [n for n in paper_flags if n != name]
        row.update(n=pap["n"], n_outcomes=pap["n"], hit_rate=pap["hit_rate"], avg_pnl_pct=pap["avg_pnl_pct"],
                   ev_pct=pap["ev_pct"], max_dd_pct=pap["max_dd_pct"],
                   delta_ev_pct=_r((pap["ev_pct"] or 0) - (base["ev_pct"] or 0), 2) if pap["n"] and base["n"] else None,
                   note="paper račun vs Autopilot u istom razdoblju" + (" (paper račun nosi i druge zastavice u paperu)"
                                                                        if others else ""))
        row["proposal"] = _proposal(mode, pap)
    else:   # live
        dur = now - since
        before = summary([t[3] for t in _trades(lcon, settings.LEAGUE_USER, since - dur, since)])
        row.update(n=base["n"], n_outcomes=base["n"], hit_rate=base["hit_rate"], avg_pnl_pct=base["avg_pnl_pct"],
                   ev_pct=base["ev_pct"], max_dd_pct=base["max_dd_pct"], baseline_ev_pct=before["ev_pct"],
                   baseline_n=before["n"], delta_ev_pct=_r((base["ev_pct"] or 0) - (before["ev_pct"] or 0), 2)
                   if base["n"] and before["n"] else None,
                   note="Autopilot od uključenja vs isto razdoblje prije", proposal=None)
    return [row]


def scan_rows(now, mode):
    """market_scan per source (scan.db shadow)."""
    con = sources._ro(sources.db_paths()["scan"])
    if con is None:
        return []
    try:
        rows = con.execute("SELECT source, found_ts, result, hi4h FROM shadow WHERE found_ts >= ? AND done = 1 AND "
                           "bad IS NULL AND result IS NOT NULL AND tradeable = 1 ORDER BY found_ts",
                           (now - WINDOW_D * 86400,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    by = {}
    for src, _ts, res, hi4 in rows:
        by.setdefault(src, []).append((res, hi4))
    base = summary([r for r, _ in by.get("caller", [])])
    out = []
    for src, xs in sorted(by.items()):
        s = summary([r for r, _ in xs])
        s["hit_rate"] = _r(sum(1 for _, h in xs if (h or 0) >= 0.20) / len(xs)) if xs else None
        out.append({"flag": "market_scan", "phase": mode, "part": f"scan:{src}", "n": len(xs), "n_outcomes": s["n"],
                    "hit_rate": s["hit_rate"], "avg_pnl_pct": s["avg_pnl_pct"], "ev_pct": s["ev_pct"],
                    "max_dd_pct": s["max_dd_pct"], "baseline_ev_pct": None if src == "caller" else base["ev_pct"],
                    "baseline_n": None if src == "caller" else base["n"],
                    "delta_ev_pct": None if src == "caller" or not base["n"] or s["ev_pct"] is None
                    else _r(s["ev_pct"] - base["ev_pct"], 2),
                    "note": "sjena skenera: TP +20 / SL -30 / 4 h nakon troška; osnovica = izvor caller",
                    "proposal": _proposal(mode, s) if src != "caller" else None})
    return out


def group_rows(now, mode, econ):
    con = sources._ro(sources.db_paths()["early"])
    if con is None:
        return []
    try:
        rows = con.execute("SELECT source, ts, ev, hit4h FROM group_signals WHERE ts >= ? AND measured_ts IS NOT NULL "
                           "ORDER BY ts", (now - WINDOW_D * 86400,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    base = {"ev_pct": None, "n": 0}
    if econ is not None:
        base = summary([r[0] for r in econ.execute("SELECT ev FROM call_outcomes WHERE kind = 'call' AND status = 'ok' "
                                                   "AND ts >= ? ORDER BY ts", (now - WINDOW_D * 86400,))])
    by = {}
    for src, _ts, ev, hit in rows:
        by.setdefault(src, []).append((ev, hit))
    out = []
    for src, xs in sorted(by.items()):
        s = summary([e for e, _ in xs])
        hits = [h for _, h in xs if h is not None]
        out.append({"flag": "group_discovery", "phase": mode, "part": f"groups:{src}", "n": len(xs),
                    "n_outcomes": s["n"], "hit_rate": _r(sum(hits) / len(hits)) if hits else None,
                    "avg_pnl_pct": s["avg_pnl_pct"], "ev_pct": s["ev_pct"], "max_dd_pct": s["max_dd_pct"],
                    "baseline_ev_pct": base["ev_pct"], "baseline_n": base["n"],
                    "delta_ev_pct": _r(s["ev_pct"] - base["ev_pct"], 2) if s["ev_pct"] is not None and base["n"]
                    else None, "note": "signal grupe vs svi pozivi istog razdoblja (call_outcomes)",
                    "proposal": _proposal(mode, s)})
    return out


def range_rows(now, mode, lcon, log=print):
    from trade import settings
    if lcon is None:
        return []
    try:
        rows = lcon.execute("SELECT closed_ts, ret FROM range_rounds WHERE user = ? AND status = 'closed' AND "
                            "closed_ts >= ? ORDER BY closed_ts", (settings.PAPER_USER, now - WINDOW_D * 86400)).fetchall()
    except sqlite3.Error:
        return []
    s = summary([r for _, r in rows])
    base, note = None, "paper runde; osnovica: nema backtesta"
    try:
        outdir = os.path.join(store.ROOT, "output")
        files = sorted(f for f in os.listdir(outdir) if f.startswith("range-backtest-") and f.endswith(".json"))
        if files:
            with open(os.path.join(outdir, files[-1])) as f:
                rep = json.load(f)
            ev = ((rep.get("variants") or {}).get("0.7") or {}).get("avg_ret_pct")   # the live rule's threshold
            if ev is not None:
                base, note = float(ev), f"paper runde vs backtest {files[-1][15:23]}"
    except (OSError, ValueError, TypeError):
        pass
    out = [{"flag": "range_dca", "phase": mode, "part": "range", "n": s["n"], "n_outcomes": s["n"],
            "hit_rate": s["hit_rate"], "avg_pnl_pct": s["avg_pnl_pct"], "ev_pct": s["ev_pct"],
            "max_dd_pct": s["max_dd_pct"], "baseline_ev_pct": base, "baseline_n": None,
            "delta_ev_pct": _r(s["ev_pct"] - base, 2) if s["ev_pct"] is not None and base is not None else None,
            "note": note, "proposal": _proposal(mode, s)}]
    return out + range_source_rows(now, mode, lcon) + owner_rows(now, mode, log)


def owner_rows(now, mode, log=print):
    """11.11. (rangedca/owner.py): the owner's labels (counterfactual, the booked rounds above stay as booked) and the
    watched ranges most similar to his labelled wins, as one row "range_oznake" and two log lines; [] without labels."""
    try:
        from rangedca import owner, view
        lbs = owner.labels()
        if not lbs:
            return []
        lab = "; ".join(owner.label_text(lb) for lb in lbs[:5])
        d = view.candidates(0.0, now=now)
        sim = owner.similar_line(d.get("similar") or [], owner.wins(lbs=lbs, now=now))   # 12.11.: the report's clock
        pins = ", ".join(f"{p.get('symbol') or p['token'][:6]} ({'preporuka sada' if p.get('pin_ready') else 'čeka'})"
                         for p in d.get("pins") or [])
    except Exception as e:  # noqa: BLE001 - the rest of the report never waits for this row
        log(f"događaji: EV izvještaj, oznake vlasnika nisu pročitane ({type(e).__name__})")
        return []
    log(f"range oznake vlasnika: {lab}")
    log(sim)
    return [{"flag": "range_dca", "phase": mode, "part": "range_oznake", "n": len(lbs), "n_outcomes": None,
             "hit_rate": None, "avg_pnl_pct": None, "ev_pct": None, "max_dd_pct": None, "baseline_ev_pct": None,
             "baseline_n": None, "delta_ev_pct": None, "proposal": None,
             "note": f"oznake vlasnika (protučinjenične, knjiženo se ne mijenja): {lab}. {sim}"
                     + (f". Prikvačeni: {pins}" if pins else "")}]


def range_source_rows(now, mode, lcon):
    """11.11. (flag range_missed G27): the same paper rounds split by their source (range_rounds.levels "src"): part
    "range:missed" (tokens skipped, then >= +20 % within 60 min; rangedca/missed.py) vs "range:ostali" (every other
    source) = its baseline. Rounds, win rate, EV %, PnL $ (in the note) and the missed live gate's verdict.
    12.11. (Jure, točka 4): a token whose every rise was measured on fewer than 3 prices is nepouzdano, never a missed
    token (rangedca/missed.labelled), so in no round here: the note says how many the list left out."""
    from rangedca import gate, missed as rmissed
    from trade import settings
    try:
        rows = lcon.execute("SELECT closed_ts, ret, pnl_usd, levels FROM range_rounds WHERE user = ? AND status = 'closed' "
                            "AND closed_ts >= ? ORDER BY closed_ts", (settings.PAPER_USER, now - WINDOW_D * 86400)).fetchall()
    except sqlite3.Error:
        return []
    part = {"missed": [], "ostali": []}
    for _ts, ret, pnl, lv in rows:
        part["missed" if gate.round_source(lv) == "missed" else "ostali"].append((ret, pnl or 0.0))
    sm, so = summary([r for r, _p in part["missed"]]), summary([r for r, _p in part["ostali"]])
    try:
        live = gate.missed_refusal() or "prolazi"
    except Exception as e:  # noqa: BLE001
        live = f"nečitljivo ({type(e).__name__})"
    try:
        unrel = rmissed.unreliable_now()["n"]
    except Exception:  # noqa: BLE001 - the count unreadable: the row still comes, without it
        unrel = None
    out = []
    for key, s, base in (("missed", sm, so), ("ostali", so, None)):
        pnl = sum(p for _r, p in part[key])
        out.append({"flag": "range_dca", "phase": mode, "part": f"range:{key}", "n": s["n"], "n_outcomes": s["n"],
                    "hit_rate": s["hit_rate"], "avg_pnl_pct": s["avg_pnl_pct"], "ev_pct": s["ev_pct"],
                    "max_dd_pct": s["max_dd_pct"], "baseline_ev_pct": base["ev_pct"] if base else None,
                    "baseline_n": base["n"] if base else None,
                    "delta_ev_pct": (_r(s["ev_pct"] - base["ev_pct"], 2) if base and s["ev_pct"] is not None
                                     and base["ev_pct"] is not None else None),
                    "note": (f"izvor missed (preskočen, pa +20 % u 60 min) vs ostali izvori: PnL {pnl:+.2f} $; "
                             f"live vrata range_missed: {live}"
                             + (f"; {rmissed.note(unrel)} u 60 min nakon preskoka, nije na listi ni u ovim rundama"
                                if unrel is not None else "")) if key == "missed"
                    else f"range runde svih ostalih izvora (signal, event, market): PnL {pnl:+.2f} $",
                    "proposal": None})
    return out


def momentum_rows(now, mode, lcon):
    """momentum_scalp (11.11., momentum/): the base rate of every signal (hit = +15 % before -10 % in 45 min, EV = the
    exit rules on the same path after cost) vs the newest backtest, and the paper trades vs the live gate."""
    from momentum import data as mdata, gate, rules, view
    from trade import settings
    since = now - WINDOW_D * 86400
    sigs = sorted((s for s in mdata.read_signals(since) if s.get("status") == "done" and s.get("sim_ret") is not None),
                  key=lambda s: s["resolved_ts"] or 0)
    s = summary([x["sim_ret"] for x in sigs])
    hits = sum(int(x["hit"] or 0) for x in sigs)
    bt = view.backtest_latest() or {}
    bev = ((bt.get("variants") or {}).get("osnovno") or {}).get("ev_pct")
    be = rules.break_even_p(rules.RULES["tp1"], rules.RULES["stop"], rules.round_trip_cost())
    rows = [{"flag": "momentum_scalp", "phase": mode, "part": "momentum", "n": len(sigs), "n_outcomes": len(sigs),
             "hit_rate": _r(hits / len(sigs), 3) if sigs else None, "avg_pnl_pct": s["avg_pnl_pct"], "ev_pct": s["ev_pct"],
             "max_dd_pct": s["max_dd_pct"], "baseline_ev_pct": bev, "baseline_n": None,
             "delta_ev_pct": _r(s["ev_pct"] - bev, 2) if s["ev_pct"] is not None and bev is not None else None,
             "note": (f"osnovna stopa svih signala (pogodak = +15 % prije -10 % u 45 min); prag isplativosti ~{be:.0%} "
                      "pri TP 15 / SL 10 i ~2-3 % troška, ne 45 %; osnovica = backtest "
                      + (bt.get("file") or "nema")), "proposal": None}]
    if lcon is not None:
        try:
            tr = lcon.execute("SELECT ret, hit FROM momentum_trades WHERE user = ? AND status = 'closed' AND closed_ts >= ? "
                              "ORDER BY closed_ts", (settings.PAPER_USER, since)).fetchall()
        except sqlite3.Error:
            tr = []
        p = summary([r for r, _h in tr])
        why = gate.refusal()
        rows.append({"flag": "momentum_scalp", "phase": mode, "part": "momentum_paper", "n": p["n"], "n_outcomes": p["n"],
                     "hit_rate": _r(sum(int(h or 0) for _r_, h in tr) / len(tr), 3) if tr else None,
                     "avg_pnl_pct": p["avg_pnl_pct"], "ev_pct": p["ev_pct"], "max_dd_pct": p["max_dd_pct"],
                     "baseline_ev_pct": s["ev_pct"], "baseline_n": len(sigs), "delta_ev_pct":
                     _r(p["ev_pct"] - s["ev_pct"], 2) if p["ev_pct"] is not None and s["ev_pct"] is not None else None,
                     "note": "paper tradeovi (pogodak = TP1 prije stopa) vs osnovna stopa signala; live vrata: "
                             + (why or "prolaze"),
                     "proposal": ("prijedlog: paper → live (>= 50 tradeova, EV > 0, pogodak >= 45 %); odobrava vlasnik "
                                  "ručno") if mode == "paper" and not why else None})
    return rows


def calib_rows(now, mode):
    """grok_ev_gate (11.11., momentum/evgate.py): Grok's p_tp against what happened, 30 days."""
    from momentum import evgate
    rep = evgate.report(now)
    a = (rep or {}).get("all") or {}
    buckets = "; ".join(f"p {b['p_from']:.1f}-{b['p_to']:.1f}: n {b['n']}, pogodak {b['hit_rate']:.0%}"
                        for b in a.get("buckets") or [])
    return [{"flag": "grok_ev_gate", "phase": mode, "part": "kalibracija", "n": (rep or {}).get("n_requests") or 0,
             "n_outcomes": a.get("n") or 0, "hit_rate": a.get("base_rate"), "avg_pnl_pct": None, "ev_pct": None,
             "max_dd_pct": None, "baseline_ev_pct": None, "baseline_n": None, "delta_ev_pct": None,
             "note": (f"Brier {a['brier']:.3f}, prosječni p {a['mean_p']:.2f}" if a.get("n") else "još nema riješenih")
             + (f"; {buckets}" if buckets else ""), "proposal": None}]


COLS = ("n", "n_outcomes", "hit_rate", "avg_pnl_pct", "ev_pct", "max_dd_pct", "baseline_ev_pct", "baseline_n",
        "delta_ev_pct", "proposal", "note")


def build(now=None, econ=None, log=print):
    """All rows of today's report (dicts)."""
    from trade import settings
    now = int(now or time.time())
    tcon = sources._ro(sources.db_paths()["trade"])
    lcon = sources._ro(sources.db_paths()["league"])
    try:
        state = settings.flag_state(tcon) if tcon is not None else {}
        paper = [n for n, v in state.items() if v.get("mode") == "paper"]
        out = []
        for name in settings.FLAGS:
            st = state.get(name) or {"mode": "off"}
            if st["mode"] == "off":
                continue
            try:
                if name == "market_scan":
                    out += scan_rows(now, st["mode"])
                elif name == "group_discovery":
                    out += group_rows(now, st["mode"], econ)
                elif name == "range_dca":
                    out += range_rows(now, st["mode"], lcon, log)
                elif name == "momentum_scalp":
                    out += momentum_rows(now, st["mode"], lcon)
                elif name == "grok_ev_gate":
                    out += calib_rows(now, st["mode"])
                elif name == "proposals":   # 11.11. (proposals/report.py): per strategy, the day's missed risers
                    from proposals import report as preport
                    out += preport.ev_rows(now, st["mode"], log=log)
                elif name == "fast_path":   # 11.11. (fast/report.py): BUY outcomes, false rejects per check, cost
                    from fast import report as freport
                    out += freport.ev_rows(now, st["mode"], log=log)
                elif name == "x_call_scalp":   # 12.11. (fast/xscalp.py): per author class, 7 days, own requests
                    from fast import xscalp
                    out += xscalp.ev_rows(now, st["mode"], log=log)
                out += flag_rows(name, st, lcon, econ, now, paper)
            except Exception as e:  # noqa: BLE001 - one flag costs only its row
                log(f"događaji: EV izvještaj za {name} nije uspio ({type(e).__name__}: {e})")
        return out
    finally:
        for c in (tcon, lcon):
            if c is not None:
                c.close()


def md(day, rows):
    lines = [f"# EV po fazama značajki, {day}", "",
             "| zastavica | faza | dio | n | ishodi | pogodak | prosj. PnL % | EV % | max DD % | osnovica EV % | razlika |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]

    def f(x, pct=False):
        if x is None:
            return "-"
        return f"{x * 100:.0f} %" if pct else (f"{x:+.2f}" if isinstance(x, float) else str(x))
    for r in rows:
        lines.append(f"| {r['flag']} | {r['phase']} | {r['part']} | {r.get('n') or 0} | {r.get('n_outcomes') or 0} | "
                     f"{f(r.get('hit_rate'), True)} | {f(r.get('avg_pnl_pct'))} | {f(r.get('ev_pct'))} | "
                     f"{f(r.get('max_dd_pct'))} | {f(r.get('baseline_ev_pct'))} | {f(r.get('delta_ev_pct'))} |")
    props = [r for r in rows if r.get("proposal")]
    lines += ["", "## Prijedlozi (odobrava vlasnik ručno, ništa se ne mijenja samo)", ""]
    lines += [f"- {r['flag']} ({r['part']}): {r['proposal']}" for r in props] or ["- nema (treba n >= 20 i EV > 0)"]
    lines += ["", "## Bilješke", ""] + [f"- {r['flag']} ({r['part']}): {r['note']}" for r in rows if r.get("note")]
    lines += ["", "Kako se mjeri: events/evreport.py (osnovica je ista stvar bez značajke gdje se može definirati)."]
    return "\n".join(lines) + "\n"


def cost_week(now=None, log=print):
    """11.11. (Jure, preporuka 8): the 7-day sums of the daily cost lines (usage/daily.week), {} when unreadable."""
    try:
        from usage import daily
        return daily.week(now)
    except Exception as e:  # noqa: BLE001 - the EV report never fails on its cost section
        log(f"događaji: trošak po izvoru (7 dana) nije pročitan ({type(e).__name__}: {e})")
        return {}


def cost_md(cost):
    try:
        from usage import daily
        return "\n" + "\n".join(daily.week_md(cost or {})) + "\n"
    except Exception:  # noqa: BLE001
        return ""


def run(now=None, log=print, econ=None, outdir=None):
    now = int(now or time.time())
    own = econ is None
    econ = econ or store.connect()
    try:
        day = dt.datetime.fromtimestamp(now, ZoneInfo(TZ)).date().isoformat()
        rows = build(now, econ, log)
        econ.execute("DELETE FROM ev_report WHERE day = ?", (day,))
        econ.executemany("INSERT OR REPLACE INTO ev_report VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [(day, r["flag"], r["phase"], r["part"], *[r.get(c) for c in COLS], now) for r in rows])
        econ.commit()
        outdir = outdir or os.path.join(store.ROOT, "output")
        try:
            os.makedirs(outdir, exist_ok=True)
            base = os.path.join(outdir, f"ev-report-{day.replace('-', '')}")
            cost = cost_week(now, log)   # 11.11. (preporuka 8): the cost per source of the last 7 days
            with open(base + ".json", "w") as f:
                json.dump({"day": day, "ts": now, "rows": rows, "trosak_7d": cost}, f, ensure_ascii=False, indent=1)
            with open(base + ".md", "w") as f:
                f.write(md(day, rows) + cost_md(cost))
        except OSError as e:
            log(f"događaji: EV izvještaj nije zapisan u output/ ({e})")
        props = [r for r in rows if r.get("proposal")]
        log(f"događaji: EV izvještaj {day}: {len(rows)} redaka, prijedloga {len(props)}"
            + "".join(f"; {r['flag']} ({r['part']}): EV {r['ev_pct']}" for r in rows if r.get("ev_pct") is not None)[:600])
        return {"day": day, "rows": rows}
    finally:
        if own:
            econ.close()


def latest(econ=None):
    """{"day", "rows"} of the newest report for the page and the brief ({} when none)."""
    own = econ is None
    econ = econ or store.ro()
    if econ is None:
        return {}
    try:
        r = econ.execute("SELECT MAX(day) FROM ev_report").fetchone()
        if not r or not r[0]:
            return {}
        cur = econ.execute("SELECT * FROM ev_report WHERE day = ? ORDER BY flag, part", (r[0],))
        cols = [d[0] for d in cur.description]
        return {"day": r[0], "rows": [dict(zip(cols, x)) for x in cur]}
    except sqlite3.Error:
        return {}
    finally:
        if own:
            econ.close()


