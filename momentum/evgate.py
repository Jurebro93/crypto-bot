"""Grok's EV gate and its calibration (flag grok_ev_gate, G17; 11.11. Jure, part D).

Grok's buy gate for autotrade was "P(+20 % within 4 h) >= 0.6" in Grok's own prompt. A probability alone says nothing
about the exits the position really gets, so the gate is now an expected value with the strategy's own TP / SL:

    EV = p_tp x TP - (1 - p_tp) x SL - cost          (fractions of the stake)

11.11. (the owner's rule D, trade/edge): an AUTOTRADE buy (this gate enforcing: paper / live) needs EV >= +3 % AND
Grok's measured record for the strategy: n >= 10 resolved requests it priced with EV > 0 (any mode, any decision:
every request with p_tp is recorded and resolved), their results (+TP when TP came first, -SL otherwise, minus the
request's cost) with a mean whose 90 % interval's lower bound is > 0 (trade/edge.live_proof; the EV >= +3 % of that
rule is this request's own EV). Until that record exists every autotrade buy is refused while the gate enforces.

  p_tp      Grok's probability (0-1) that the take profit comes BEFORE the stop, sent in execute_trade
  strategy  momentum_scalp: TP +15 %, SL -10 %, horizon 45 min (momentum/rules: TP1 +15 %, stop -10 %, time 45 min)
            range_dca:      TP = the range's range_high_low, SL = its hard stop (range_low_low x 0.85), both from the
                            token's current range (range.db) against the price now; horizon 24 h; no active range =
                            no levels (refused while the gate enforces)
            other (default): the exit Grok's buy really gets on the Autopilot (ui/pravitrade._post_buy): the owner's
                            last TP (default +15 %) and the default stop (sl_default, -60 % unless changed); horizon 4 h.
                            With +15 / -60 the break-even p is ~0.83: the honest price of a wide stop.
  cost      the round trip of the stake: trade/cost.round_trip, the ONE model (2 x fee_side + 2 x the AMM impact)
A buy with strategy momentum_scalp or range_dca also gets that strategy's TP / SL as its exit (ui/grokauto passes them
to the buy), so the levels the gate priced are the levels that trade; "other" keeps the owner's exit.

Modes (trade/settings flag grok_ev_gate; the owner sets it, nothing here does):
  off      no check (every request with p_tp is still RECORDED for calibration: bookkeeping, not enforcement)
  shadow   the check runs; a buy it would refuse goes through and is logged (league.db shadow_decisions + calib row
           decision "shadow_reject")
  paper / live   a Grok autotrade BUY with EV < +3 %, without Grok's proof for the strategy, without p_tp or without
                 levels is refused with the reason
Sells are never gated. Requests that wait for the owner's approval (require_approval=true) are recorded, never refused.

Calibration: every recorded request keeps p_tp, strategy, TP / SL, cost, EV and the price at the request; run_momentum
resolves it from its own DexScreener snapshots (free, once a minute, only tokens with an open row): hit = 1 when +TP
came before -SL within the horizon, 0 when the stop came first or the horizon ended. Reported: Brier score
(mean (p - hit)^2; 0.25 = a coin flip's skill at p = 0.5) and the reliability per p bucket (mean p vs the hit rate).
Prices are minute samples: a wick inside a minute is not seen, for TP and SL alike.
"""
import time

from trade import edge

from . import data, rules

FLAG = "grok_ev_gate"
STRATEGIES = ("momentum_scalp", "range_dca", "other")
MOMENTUM = {"tp": rules.RULES["tp1"], "sl": rules.RULES["stop"], "horizon_s": rules.RULES["time_s"]}
RANGE_HORIZON_S = 24 * 3600
OTHER_HORIZON_S = 4 * 3600
BUCKETS = [(i / 10, (i + 1) / 10) for i in range(10)]
TRACK_DAYS = 60


def mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def parse(body):
    """(p_tp or None, strategy, error or None) from an execute_trade body. Both fields are optional."""
    p = body.get("p_tp")
    if p is None or p == "":
        p = None
    else:
        try:
            p = float(p)
        except (TypeError, ValueError):
            return None, None, "p_tp must be a number 0-1 (Grok's probability that TP comes before SL)"
        if not 0 <= p <= 1:
            return None, None, "p_tp must be between 0 and 1"
    s = str(body.get("strategy") or "other").strip().lower()
    if s not in STRATEGIES:
        return None, None, f"strategy must be one of {', '.join(STRATEGIES)}"
    return p, s, None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def levels(strategy, token, price, mcap=None, tcon=None, ranges=None):
    """{"tp", "sl" (fractions, sl > 0), "horizon_s", "from", "exit": (tp text, sl text) for the buy or None} or
    (None, why)."""
    if strategy == "momentum_scalp":
        m = MOMENTUM
        return {"tp": m["tp"], "sl": m["sl"], "horizon_s": m["horizon_s"], "from": "momentum_scalp: TP1 +15 %, stop -10 %",
                "exit": (f"{m['tp'] * 100:g}%", f"-{m['sl'] * 100:g}%")}, None
    if not price or price <= 0:
        return None, "no price for the token"
    if strategy == "range_dca":
        if ranges is None:
            from rangedca import data as rdata
            ranges = rdata.read_ranges(tokens=[token])
        r = (ranges or {}).get(token)
        if not r or not r.get("active") or not r.get("zones"):
            return None, "no active range for that token (get_range_candidates)"
        from rangedca import rules as rrules
        lv = rrules.levels_of(r)
        tp, sl = lv["rhl"] / price - 1, 1 - lv["stop_px"] / price
        if tp <= 0:
            return None, "the price is already in the range's top zone: no range take profit above it"
        if sl <= 0:
            return None, "the price is under the range's hard stop"
        sup = (mcap / price) if mcap else ((r.get("metrics") or {}).get("supply"))
        ex = (f"${lv['rhl'] * sup:.0f}", f"${lv['stop_px'] * sup:.0f}") if sup else (f"{tp * 100:.1f}%", f"-{sl * 100:.1f}%")
        return {"tp": tp, "sl": sl, "horizon_s": RANGE_HORIZON_S, "from": "range zones: TP range_high_low, SL "
                "range_low_low x 0.85", "exit": ex}, None
    from league import auto
    from ui import pravitrade
    from trade import settings
    own = tcon is None
    tcon = tcon or settings.connect()
    try:
        cfg = pravitrade._cfg(tcon)
    finally:
        if own:
            tcon.close()
    tp_t, sl_t = pravitrade._last_exit(cfg)
    sl_t = sl_t or pravitrade._sl0(cfg)
    try:
        tp_px, _ = auto.parse_level(tp_t, price, mcap, "tp")
        sl_px, _ = auto.parse_level(sl_t, price, mcap, "sl")
    except ValueError as e:
        return None, f"the owner's exit cannot be priced ({e})"
    if not tp_px or not sl_px:
        return None, "the owner's exit has no TP or no stop"
    return {"tp": tp_px / price - 1, "sl": 1 - sl_px / price, "horizon_s": OTHER_HORIZON_S,
            "from": f"the owner's exit for Grok buys: TP {tp_t}, SL {sl_t}", "exit": None}, None


def cost(amount_sol, sol_usd, liq):
    """trade/cost.round_trip of the stake (through momentum/rules.round_trip_cost)."""
    usd = (amount_sol or 0.1) * (sol_usd or 150.0)
    return rules.round_trip_cost(usd, liq)


def track(strategy, now=None, path=None, days=TRACK_DAYS):
    """Grok's measured record for a strategy: the results of its resolved requests it priced with EV > 0 (+TP when
    TP came first, else -SL, minus the request's own cost; fractions), last `days`."""
    now = int(now or time.time())
    con = data.ro(path)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT hit, tp_pct, sl_pct, cost_pct FROM calib WHERE strategy=? AND status='done' AND hit IS "
                           "NOT NULL AND ev_pct > 0 AND ts >= ?", (strategy, now - days * 86400)).fetchall()
    except Exception:  # noqa: BLE001 - an old momentum.db: no record
        rows = []
    finally:
        con.close()
    return [((tp or 0) if h else -(sl or 0)) / 100 - (c or 0) / 100 for h, tp, sl, c in rows]


def decide(p, lv, c, rec=None):
    """{"ev", "break_even_p", "pass" (the autotrade rule: EV >= +3 % and the record's proof), "ev_ok", "proof",
    "proof_why"} of one request (p, lv may be None; rec: track() of the strategy)."""
    ok, why, st = edge.live_proof(rec or [])
    if p is None or not lv:
        return {"ev": None, "break_even_p": rules.break_even_p(lv["tp"], lv["sl"], c) if lv else None, "pass": False,
                "ev_ok": False, "proof": st, "proof_why": why}
    e = rules.ev(p, lv["tp"], lv["sl"], c)
    ev_ok = e >= edge.EV_LIVE_MIN - 1e-12
    return {"ev": e, "break_even_p": rules.break_even_p(lv["tp"], lv["sl"], c), "pass": ev_ok and ok, "ev_ok": ev_ok,
            "proof": st, "proof_why": why}


def check(token, amount, p, strategy, market=None, now=None, sol_usd=None, tcon=None, ranges=None, gate_mode=None):
    """The gate for one buy: {"mode", "p_tp", "strategy", "levels", "cost", "ev", "break_even_p", "reject" (reason
    when this buy must be refused now, else None), "shadow_reject" (reason logged in shadow), "price", "mcap",
    "liq"}."""
    m = gate_mode or mode()
    if market is None:
        from league import copy
        market = copy.market
    q = (market({token}) or {}).get(token) or ()
    price, liq, mcap = (q[0], q[1], q[3]) if len(q) >= 4 else (None, None, None)
    lv, why_lv = levels(strategy, token, price, mcap, tcon, ranges)
    if sol_usd is None:
        try:
            from rangedca import trade as rtrade
            sol_usd = rtrade.sol_usd()
        except Exception:  # noqa: BLE001
            sol_usd = None
    c = cost(amount, sol_usd, liq)
    rec = track(strategy, now) if p is not None and lv else []
    d = decide(p, lv, c, rec)
    why = None
    if p is None:
        why = "grok_ev_gate: send p_tp (0-1, your probability that TP comes before SL) and strategy"
    elif not lv:
        why = f"grok_ev_gate: no TP/SL for strategy {strategy}: {why_lv}"
    elif not d["ev_ok"]:
        why = (f"grok_ev_gate: EV {d['ev'] * 100:+.2f} % < +{edge.EV_LIVE_MIN * 100:.0f} % (p_tp {p:.2f} x TP "
               f"{lv['tp'] * 100:.1f} % - {1 - p:.2f} x SL {lv['sl'] * 100:.1f} % - cost {c * 100:.2f} %; break-even "
               f"p_tp {d['break_even_p']:.2f})")
    elif not d["pass"]:
        why = (f"grok_ev_gate: EV {d['ev'] * 100:+.2f} %, but your measured record for {strategy} is not proof yet "
               f"({d['proof_why']}; autotrade needs n >= {edge.N_MIN} resolved requests priced EV > 0 whose mean "
               f"result has its 90 % interval above 0)")
    return {"mode": m, "p_tp": p, "strategy": strategy, "levels": lv, "levels_why": why_lv, "cost": c, "ev": d["ev"],
            "break_even_p": d["break_even_p"], "proof": {k: d["proof"].get(k) for k in ("n", "ev", "lo90")},
            "price": price, "mcap": mcap, "liq": liq,
            "reject": why if m in ("paper", "live") else None,
            "shadow_reject": why if m == "shadow" else None, "would_reject": why}


def record(g, token, amount, request, now=None, path=None):
    """One calibration row (only when p_tp was sent and the levels are known); returns its id or None. Never raises."""
    if g.get("p_tp") is None or not g.get("levels") or not g.get("price"):
        return None
    now = int(now or time.time())
    lv = g["levels"]
    decision = ("reject" if g.get("reject") else "shadow_reject" if g.get("shadow_reject") else
                "would_reject" if g.get("would_reject") else "pass")
    try:
        con = data.connect(path)
        try:
            cur = con.execute(
                "INSERT INTO calib (ts, token, strategy, p_tp, tp_pct, sl_pct, cost_pct, ev_pct, horizon_s, levels_from, "
                "gate_mode, decision, request, amount_sol, entry_px, entry_mcap, status) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now, token, g["strategy"], g["p_tp"], lv["tp"] * 100, lv["sl"] * 100, g["cost"] * 100,
                 g["ev"] * 100 if g.get("ev") is not None else None, lv["horizon_s"], lv["from"], g["mode"], decision,
                 request, amount, g["price"], g.get("mcap"), "open"))
            con.commit()
            return cur.lastrowid
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 - bookkeeping never fails a trade
        print(f"grok ev gate: kalibracija nije zapisana ({type(e).__name__})", flush=True)
        return None


def mark(row_id, request, path=None):
    """The request's final status on its calibration row (executed / rejected / pending_approval)."""
    if not row_id:
        return
    try:
        con = data.connect(path)
        try:
            con.execute("UPDATE calib SET request=? WHERE id=?", (request, row_id))
            con.commit()
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        pass


def shadow_log(g, token):
    """league.db shadow_decisions: the buy the gate would have refused (mode shadow)."""
    try:
        from league import flags, store as lstore
        lcon = lstore.connect()
        try:
            flags.shadow(lcon, FLAG, None, token, "kupi (Grok auto)", "odbij (EV < +3 % ili bez dokaza)",
                         {"p_tp": g["p_tp"], "strategy": g["strategy"], "ev": g["ev"], "why": g["shadow_reject"]})
            lcon.commit()
        finally:
            lcon.close()
    except Exception:  # noqa: BLE001
        pass


# ---------- outcomes and calibration ------------------------------------------------------------------------------
def open_tokens(con):
    return [r[0] for r in con.execute("SELECT DISTINCT token FROM calib WHERE status='open'")]


def resolve(con, now):
    """Close the calibration rows whose TP or SL came, or whose horizon ended, from momentum.db snapshots. Returns
    the number resolved."""
    n = 0
    rows = con.execute("SELECT id, token, ts, tp_pct, sl_pct, horizon_s, entry_px FROM calib WHERE status='open'").fetchall()
    for rid, tok, ts, tp, sl, hz, px in rows:
        if not px:
            con.execute("UPDATE calib SET status='done', first='no_price' WHERE id=?", (rid,))
            continue
        path = data.snap_rows(con, tok, ts + 1, ts + hz)
        o = path_outcome(path, px, ts, tp / 100, sl / 100, hz, now)
        if o["first"] is None:
            continue
        con.execute("UPDATE calib SET status='done', first=?, hit=?, resolved_ts=?, max_pct=?, min_pct=? WHERE id=?",
                    (o["first"], o["hit"], o["resolved_ts"], o["max_pct"], o["min_pct"], rid))
        n += 1
    con.commit()
    return n


def path_outcome(path, entry_px, entry_ts, tp, sl, horizon_s, now):
    """rules.outcome with this request's own TP / SL / horizon."""
    return rules.outcome(path, entry_px, entry_ts, now, {"tp1": tp, "stop": sl, "time_s": horizon_s})


def calibration(rows):
    """rows: [(p, hit)] resolved. {"n", "brier", "base_rate", "mean_p", "buckets": [{"p_from", "p_to", "n",
    "mean_p", "hit_rate"}]}."""
    rows = [(float(p), int(h)) for p, h in rows if p is not None and h is not None]
    n = len(rows)
    if not n:
        return {"n": 0, "brier": None, "base_rate": None, "mean_p": None, "buckets": []}
    out = {"n": n, "brier": round(sum((p - h) ** 2 for p, h in rows) / n, 4),
           "base_rate": round(sum(h for _p, h in rows) / n, 3), "mean_p": round(sum(p for p, _h in rows) / n, 3),
           "buckets": []}
    for lo, hi in BUCKETS:
        xs = [(p, h) for p, h in rows if lo <= p < hi or (hi == 1.0 and p == 1.0)]
        if xs:
            out["buckets"].append({"p_from": lo, "p_to": hi, "n": len(xs), "mean_p": round(sum(p for p, _ in xs) / len(xs), 3),
                                   "hit_rate": round(sum(h for _, h in xs) / len(xs), 3)})
    return out


def report(now=None, days=30, path=None):
    """Calibration of the last `days` per strategy and overall, plus the gate's mode and today's decisions; None
    without momentum.db."""
    now = int(now or time.time())
    con = data.ro(path)
    if con is None:
        return {"flag_mode": mode(), "n_requests": 0, "note": "još nijedan zahtjev s p_tp"}
    try:
        rows = con.execute("SELECT strategy, p_tp, hit, status, decision, ev_pct, ts FROM calib WHERE ts >= ?",
                           (now - days * 86400,)).fetchall()
    finally:
        con.close()
    done = [(s, p, h) for s, p, h, st, _d, _e, _t in rows if st == "done" and h is not None]
    out = {"flag_mode": mode(), "window_days": days, "n_requests": len(rows),
           "open": sum(1 for r in rows if r[3] == "open"), "all": calibration([(p, h) for _s, p, h in done]),
           "by_strategy": {s: calibration([(p, h) for ss, p, h in done if ss == s]) for s in STRATEGIES
                           if any(ss == s for ss, _p, _h in done)},
           "decisions_24h": {}}
    for _s, _p, _h, _st, d, _e, ts in rows:
        if ts >= now - 86400:
            out["decisions_24h"][d] = out["decisions_24h"].get(d, 0) + 1
    out["rule"] = ("autotrade: EV = p_tp x TP - (1 - p_tp) x SL - cost >= +3 % AND the strategy's measured record "
                   "(n >= 10 resolved requests priced EV > 0, the 90 % interval of their mean result above 0); "
                   "momentum_scalp TP 15 / SL 10 (45 min), range_dca from the zones (24 h), other = the owner's exit "
                   "for Grok buys (4 h); hit = TP before SL within the horizon")
    return out


def lines(rep):
    """Croatian report lines of report() (daily reports)."""
    if not rep or not rep.get("n_requests"):
        return [f"Grok EV vrata ({(rep or {}).get('flag_mode', 'off')}): još nijedan zahtjev s p_tp."]
    a = rep["all"]
    out = [f"Grok EV vrata ({rep['flag_mode']}): {rep['n_requests']} zahtjeva s p_tp u {rep['window_days']} dana, "
           f"riješeno {a['n']}, otvoreno {rep['open']}"
           + (f"; Brier {a['brier']:.3f} (0,25 = nagađanje na 0,5), prosječni p {a['mean_p']:.2f}, stvarni pogodak "
              f"{a['base_rate']:.0%}" if a["n"] else "")
           + "."]
    for b in a.get("buckets") or []:
        out.append(f"  p {b['p_from']:.1f}-{b['p_to']:.1f}: {b['n']} zahtjeva, prosječni p {b['mean_p']:.2f}, "
                   f"pogodak {b['hit_rate']:.0%}")
    d = rep.get("decisions_24h") or {}
    if d:
        out.append("  zadnja 24 h: " + ", ".join(f"{k} {v}" for k, v in sorted(d.items())))
    return out
