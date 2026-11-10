"""Exit plans (10.11. ~21:45, Jure: "MCP alat set_exit_plan + serverski izvršitelj izlaza (flag exit_plans, start =
paper, pa live nakon testa)").

A plan for one token's open position (all its open lots on an Autopilot account), set by the MCP client (Grok) with
set_exit_plan, replaces the position's default TP/SL while the flag applies to that account and the owner has not
paused plans:

  take_profits  [{at_pct | at_mc_usd, sell_share}]: at +at_pct % from the average entry (qty-weighted entry price of
                the open lots) or at a market cap, sell that share of the position as it was when the plan was set
                (shares together at most 1); each fires once
  trailing      {activate_pct, trail_pct}: active from +activate_pct %, then everything is sold at -trail_pct % from
                the highest price after the activation
  stop          {at_pct | at_mc_usd}: the hard stop; it may only be TIGHTENED: never looser than the position's
                current stop nor than sl_default from the average entry. Without one the position's current stop stays.
  time_stop     {after_min, if_pnl_below_pct}: after_min minutes after the LAST entry, sell everything when the
                result is under if_pnl_below_pct %
  reason        one line
  accounts      (optional, 10.11. range_dca) the Autopilot accounts the plan applies to, e.g. ["autopilot-paper"];
                without it every Autopilot account holding the token (the old behaviour). A token still has ONE
                active plan and a new one replaces it whatever the scope. With it, a plan meant for a range position
                on the demo account never takes over a copy of the same token on the real account.

The executor (run_once) runs every second inside league/auto.fast_loop (the Autopilot's 1-s exit thread): it reads
the price of every planned token (league/copy.market, Jupiter when DexScreener has none), keeps the peak since the
entry and since the trailing activation, and on a trigger sells the demo lots at once (league/store.sell_partial /
sell): the real positions follow within seconds through run_trade.py, which mirrors full and partial demo sales
with its cost cap (max_cost_pct) and retries ("pokušavam opet"). No owner tap: a plan only protects or takes profit
on an open position, it never buys.

Safety: a price older than STALE_S (60 s) fires only the hard stop, never a TP or the trailing; the owner's
"Pauziraj exit planove" (trade settings exit_plans_paused) stops every plan at once and the default TP/SL of each
position is back (league/auto.fast_once skips only lots whose plan is in force); flag exit_plans: off nothing, shadow
and paper on the real Autopilot account only log what a plan would do (shadow_decisions), paper executes on the demo
account autopilot-paper, live on both. Every execution: table exit_events (trigger tp1/tp2/.../trailing/stop/
time_stop, plan_id, price, MC, share, PnL) and a notice to the owner (ui/grokauto.notify: Telegram when set, log).
"""
import json
import time

from . import store

STALE_S = 60
SCHEMA = """
CREATE TABLE IF NOT EXISTS exit_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, created_ts INTEGER, client TEXT, reason TEXT, plan TEXT,
    status TEXT, state TEXT, replaced_by INTEGER);
CREATE INDEX IF NOT EXISTS exit_plans_token ON exit_plans (token, status);
CREATE TABLE IF NOT EXISTS exit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, plan_id INTEGER, user TEXT, token TEXT, trigger TEXT,
    price REAL, mcap REAL, share REAL, pnl_usd REAL, mode TEXT, stale INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS exit_events_ts ON exit_events (ts);
"""
_LAST = {}   # token -> (price, mcap, liq, ts): the last good quote, for the staleness rule


def ensure(con):
    con.executescript(SCHEMA)


def _users():
    from trade import settings as ts
    return (ts.LEAGUE_USER, ts.PAPER_USER)


def _scope(plan):
    """The accounts a stored plan applies to (every Autopilot account when it names none)."""
    acc = (plan or {}).get("accounts")
    return tuple(u for u in _users() if not acc or u in acc)


def _lots(con, user, token):
    return [dict(r) for r in con.execute("SELECT * FROM trades WHERE user=? AND token=? AND status='open' ORDER BY id",
                                         (user, token))]


def _avg(lots):
    q = sum(t["qty"] or 0 for t in lots)
    if not q:
        return None
    return sum((t["entry_px"] or 0) * (t["qty"] or 0) for t in lots) / q


def _mc_ratio(lots):
    """market cap per unit of price (the supply), from a lot with both; None when unknown."""
    for t in lots:
        if t.get("entry_mcap") and t.get("entry_px"):
            return t["entry_mcap"] / t["entry_px"]
    return None


def _num(x, name, lo=None, hi=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ValueError(f"{name} must be {lo}..{hi}")
    return v


def _level(d, name):
    """{"at_pct": x} or {"at_mc_usd": y} -> ("pct", x) | ("mc", y)."""
    if not isinstance(d, dict):
        raise ValueError(f"{name} must be an object with at_pct or at_mc_usd")
    if d.get("at_pct") is not None and d.get("at_mc_usd") is not None:
        raise ValueError(f"{name}: at_pct OR at_mc_usd, not both")
    if d.get("at_pct") is not None:
        return "pct", _num(d["at_pct"], f"{name}.at_pct", -99, 10000)
    if d.get("at_mc_usd") is not None:
        return "mc", _num(d["at_mc_usd"], f"{name}.at_mc_usd", 1, 1e12)
    raise ValueError(f"{name} needs at_pct or at_mc_usd")


def _px(kind, v, avg, ratio):
    if kind == "pct":
        return avg * (1 + v / 100)
    if not ratio:
        raise ValueError("this position has no entry market cap: use at_pct")
    return v / ratio


def current_stop_px(con, user, token, lots=None):
    """The position's stop in force: an active plan's stop, else the tightest auto sl_px of its lots; None = none."""
    lots = lots if lots is not None else _lots(con, user, token)
    p = active(con, token)
    if p and user in _scope(p["plan"]) and p["state"].get("stop_px", {}).get(user):
        return p["state"]["stop_px"][user]
    s = [json.loads(t["auto"]).get("sl_px") for t in lots if t.get("auto") and (json.loads(t["auto"]) or {}).get("sl_px")]
    try:   # 10.11. (range_dca): a range position's own hard stop is its stop (a plan may only tighten it)
        from rangedca import trade as rtrade
        rs = rtrade.stop_px(con, user, token)
        if rs:
            s.append(rs)
    except Exception:  # noqa: BLE001 - no range module or table: the lots' own stops
        pass
    return max(s) if s else None


def validate(con, token, plan, sl_default, now=None):
    """The plan normalized, with the stop's price per account; ValueError with the reason. Every account must hold
    an open position in the token (at least one)."""
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    out = {"take_profits": [], "trailing": None, "stop": None, "time_stop": None,
           "reason": str(plan.get("reason") or "")[:300]}
    tps = plan.get("take_profits") or []
    if not isinstance(tps, list) or len(tps) > 6:
        raise ValueError("take_profits must be a list of at most 6")
    total = 0.0
    for i, tp in enumerate(tps):
        kind, v = _level(tp, f"take_profits[{i}]")
        if kind == "pct" and v <= 0:
            raise ValueError(f"take_profits[{i}].at_pct must be above 0 (a take profit is above the entry)")
        share = _num(tp.get("sell_share"), f"take_profits[{i}].sell_share", 0.01, 1)
        total += share
        out["take_profits"].append({"kind": kind, "v": v, "sell_share": share})
    if total > 1 + 1e-9:
        raise ValueError(f"take_profits sell_share add up to {total:g}, at most 1")
    if plan.get("trailing") is not None:
        tr = plan["trailing"]
        if not isinstance(tr, dict):
            raise ValueError("trailing must be {activate_pct, trail_pct}")
        out["trailing"] = {"activate_pct": _num(tr.get("activate_pct"), "trailing.activate_pct", 0, 10000),
                           "trail_pct": _num(tr.get("trail_pct"), "trailing.trail_pct", 1, 90)}
    if plan.get("time_stop") is not None:
        t = plan["time_stop"]
        if not isinstance(t, dict):
            raise ValueError("time_stop must be {after_min, if_pnl_below_pct}")
        out["time_stop"] = {"after_min": _num(t.get("after_min"), "time_stop.after_min", 1, 7 * 1440),
                            "if_pnl_below_pct": _num(t.get("if_pnl_below_pct"), "time_stop.if_pnl_below_pct", -99, 1000)}
    stop = _level(plan["stop"], "stop") if plan.get("stop") is not None else None
    if not (out["take_profits"] or out["trailing"] or stop or out["time_stop"]):
        raise ValueError("an empty plan: give take_profits, trailing, stop or time_stop")
    acc = plan.get("accounts")
    if acc is not None:
        acc = [acc] if isinstance(acc, str) else acc
        if not isinstance(acc, list) or not acc or any(a not in _users() for a in acc):
            raise ValueError(f"accounts must be a list of {', '.join(_users())}")
        out["accounts"] = sorted(set(acc))
    held = {u: _lots(con, u, token) for u in _scope(out)}
    held = {u: l for u, l in held.items() if l}
    if not held:
        raise ValueError("no open Autopilot position in that token" + (" on those accounts" if acc else "")
                         + ": a plan is only for an open position")
    stop_px = {}
    for u, lots in held.items():
        avg, ratio = _avg(lots), _mc_ratio(lots)
        if not avg:
            raise ValueError("the position has no entry price")
        for tp in out["take_profits"]:
            if _px(tp["kind"], tp["v"], avg, ratio) <= avg * 0.999 and tp["kind"] == "mc":
                raise ValueError(f"take profit at MC ${tp['v']:,.0f} is under the average entry")
        floor = avg * (1 - sl_default / 100)
        cur = current_stop_px(con, u, token, lots)
        if stop:
            px = _px(stop[0], stop[1], avg, ratio)
            if px < floor - 1e-12:
                raise ValueError(f"stop is looser than sl_default (-{sl_default:g} % from the average entry)")
            if cur and px < cur - 1e-12:
                raise ValueError(f"a stop may only be tightened: the position's stop is "
                                 f"{(cur / avg - 1) * 100:+.1f} % from the average entry")
            stop_px[u] = px
        else:
            stop_px[u] = max(cur or 0, floor) if cur else floor
    out["stop"] = {"kind": stop[0], "v": stop[1]} if stop else None
    return out, stop_px


def active(con, token):
    ensure(con)
    r = con.execute("SELECT * FROM exit_plans WHERE token=? AND status='active' ORDER BY id DESC LIMIT 1", (token,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["plan"], d["state"] = json.loads(d["plan"]), json.loads(d["state"] or "{}")
    return d


def set_plan(con, token, plan, sl_default, client="mcp", now=None):
    """Store a plan (the previous one of the token is replaced). Returns {"plan_id", "plan", "replaced"}."""
    ensure(con)
    now = int(now or time.time())
    norm, stop_px = validate(con, token, plan, sl_default, now)
    old = active(con, token)
    state = {"stop_px": stop_px, "sold": {}, "fired": {}, "peak_px": {}, "trail_peak_px": {},
             "base_qty": {u: sum(t["qty"] or 0 for t in _lots(con, u, token)) for u in stop_px}}
    cur = con.execute("INSERT INTO exit_plans (token, created_ts, client, reason, plan, status, state) VALUES (?,?,?,?,?,?,?)",
                      (token, now, client, norm["reason"], json.dumps(norm), "active", json.dumps(state)))
    pid = cur.lastrowid
    if old:
        con.execute("UPDATE exit_plans SET status='replaced', replaced_by=? WHERE id=?", (pid, old["id"]))
    con.commit()
    return {"plan_id": pid, "plan": norm, "stop_price": stop_px,
            "replaced": {"plan_id": old["id"], "plan": old["plan"]} if old else "the position's default TP/SL"}


def _save_state(con, pid, state):
    con.execute("UPDATE exit_plans SET state=? WHERE id=?", (json.dumps(state), pid))
    con.commit()


def paused():
    try:
        from trade import settings as ts
        tcon = ts.connect()
        try:
            return bool(ts.raw(tcon).get("exit_plans_paused"))
        finally:
            tcon.close()
    except Exception:  # noqa: BLE001 - unreadable: plans keep running (they only protect)
        return False


def in_force_tokens(con, user):
    """Tokens whose plan replaces the default TP/SL of `user`'s lots now (league/auto.fast_once skips those)."""
    try:
        from . import flags
        m = flags.mode("exit_plans")
        if m == "off" or not flags.applies("exit_plans", user, m) or paused():
            return set()
        ensure(con)
        return {t for t, pl in con.execute("SELECT token, plan FROM exit_plans WHERE status='active'")
                if user in _scope(json.loads(pl or "{}"))}
    except Exception:  # noqa: BLE001
        return set()


def quote(market, tokens, now):
    """{token: (price, mcap, liq, age_s)}: this second's quote, else the last good one with its age."""
    mk = {}
    try:
        from .auto import _fast_market
        mk = _fast_market(market, sorted(tokens)) if tokens else {}
    except Exception:  # noqa: BLE001
        mk = {}
    out = {}
    for t in tokens:
        m = mk.get(t)
        if m and m[0] and m[0] > 0:
            _LAST[t] = (m[0], m[3] if len(m) > 3 else None, m[1], now)
        if t in _LAST:
            px, mc, liq, ts = _LAST[t]
            out[t] = (px, mc, liq, now - ts)
    return out


def _event(con, p, user, token, trig, price, mcap, share, pnl, mode, stale, note=""):
    con.execute("INSERT INTO exit_events (ts, plan_id, user, token, trigger, price, mcap, share, pnl_usd, mode, stale, note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (int(time.time()), p["id"], user, token, trig, price, mcap, share, pnl,
                                                     mode, int(bool(stale)), note))
    con.commit()


def _sell(con, user, lots, frac_of_rest, price, liq, mcap, rule):
    """Sell frac_of_rest of every open lot (1 = all). Returns the PnL in USD."""
    pnl = 0.0
    for t in lots:
        if frac_of_rest >= 0.999:
            pnl += store.sell(con, user, t["id"], price, liq, f"plan izlaza: {rule}", mcap=mcap, exit_rule=rule)
        else:
            p, _all = store.sell_partial(con, user, t["id"], frac_of_rest, price, liq, mcap=mcap)
            pnl += p
    return pnl


def decide(p, user, lots, price, mcap, age_s, now):
    """(trigger, share of the ORIGINAL position, frac of what is left) or None, and the state changes (in place)."""
    st, plan = p["state"], p["plan"]
    avg, ratio = _avg(lots), _mc_ratio(lots)
    if not avg:
        return None
    stale = age_s > STALE_S
    sold = st["sold"].get(user, 0.0)
    left = max(0.0, 1.0 - sold)
    if left <= 1e-9:
        return None
    # peaks (fresh prices only)
    if not stale:
        if price > st["peak_px"].get(user, avg):
            st["peak_px"][user] = price
        tr = plan.get("trailing")
        if tr and (price >= avg * (1 + tr["activate_pct"] / 100) or st["trail_peak_px"].get(user)):
            if price > st["trail_peak_px"].get(user, 0):
                st["trail_peak_px"][user] = price
    stop = st["stop_px"].get(user)
    if stop and price <= stop:
        return "stop", left, 1.0
    if stale:
        return None   # a late feed: only the hard stop
    pnl_pct = (price / avg - 1) * 100
    fired = st["fired"].setdefault(user, [])
    for i, tp in enumerate(plan.get("take_profits") or []):
        if i in fired:
            continue
        if price >= _px(tp["kind"], tp["v"], avg, ratio):
            share = min(tp["sell_share"], left)
            return f"tp{i + 1}", share, share / left
    tr = plan.get("trailing")
    tp_peak = st["trail_peak_px"].get(user)
    if tr and tp_peak and price <= tp_peak * (1 - tr["trail_pct"] / 100):
        return "trailing", left, 1.0
    ts_ = plan.get("time_stop")
    if ts_:
        last_entry = max(t["opened_ts"] or 0 for t in lots)
        if now - last_entry >= ts_["after_min"] * 60 and pnl_pct < ts_["if_pnl_below_pct"]:
            return "time_stop", left, 1.0
    return None


def run_once(con, market, now=None):
    """One pass over the active plans: [(user, token, trigger, text)] of what was executed (or shadow-logged)."""
    from . import flags
    now = now or time.time()
    ensure(con)
    m = flags.mode("exit_plans")
    if m == "off" or paused():
        return []
    plans = [dict(r) for r in con.execute("SELECT * FROM exit_plans WHERE status='active'")]
    if not plans:
        return []
    for p in plans:
        p["plan"], p["state"] = json.loads(p["plan"]), json.loads(p["state"] or "{}")
    q = quote(market, {p["token"] for p in plans}, now)
    done = []
    for p in plans:
        tok = p["token"]
        if tok not in q:
            continue
        price, mcap, liq, age = q[tok]
        any_open = False
        for user in _scope(p["plan"]):   # 10.11.: a plan with "accounts" leaves the other account's lots alone
            lots = _lots(con, user, tok)
            if not lots:
                continue
            any_open = True
            on, sh = flags.applies("exit_plans", user, m), flags.shadowing("exit_plans", user, m)
            if not (on or sh):
                continue
            before = json.dumps(p["state"])
            hit = decide(p, user, lots, price, mcap, age, now)
            if not hit:
                if json.dumps(p["state"]) != before:
                    _save_state(con, p["id"], p["state"])
                continue
            trig, share, frac = hit
            if trig.startswith("tp"):
                p["state"]["fired"].setdefault(user, []).append(int(trig[2:]) - 1)
            p["state"]["sold"][user] = min(1.0, p["state"]["sold"].get(user, 0.0) + share)
            if on:
                try:
                    pnl = _sell(con, user, lots, frac, price, liq, mcap, f"plan_{trig}")
                except ValueError as e:   # closed meanwhile: next pass sees it
                    print(f"plan izlaza #{p['id']} {tok[:6]}: {e}", flush=True)
                    continue
                _event(con, p, user, tok, trig, price, mcap, share, pnl, "izvršeno", age > STALE_S)
                text = (f"plan izlaza #{p['id']} {lots[0].get('symbol') or tok[:6]} ({user}): {trig}, prodano "
                        f"{share:.0%} pozicije na MC ${mcap or 0:,.0f}, {pnl:+.2f} $")
                try:
                    from ui import grokauto
                    grokauto.notify(text)
                except Exception:  # noqa: BLE001
                    print(text, flush=True)
            else:
                flags.shadow(con, "exit_plans", None, tok, f"izlaz {trig}", f"prodaj {share:.0%}",
                             {"plan_id": p["id"], "price": price, "mcap": mcap}, now)
                _event(con, p, user, tok, trig, price, mcap, share, None, "sjena", age > STALE_S)
                text = f"plan izlaza #{p['id']} {tok[:6]} ({user}, sjena): bi {trig} {share:.0%}"
            _save_state(con, p["id"], p["state"])
            done.append((user, tok, trig, text))
        if not any_open:
            con.execute("UPDATE exit_plans SET status='done' WHERE id=?", (p["id"],))
            con.commit()
    return done


def view(con, token, user, price=None, mcap=None):
    """For get_portfolio_status: the plan in force, the peak since the entry and the distance to every trigger."""
    p = active(con, token)
    if not p:
        return None
    if user not in _scope(p["plan"]):
        return {"plan_id": p["id"], "plan": p["plan"], "note": f"the plan applies to {', '.join(_scope(p['plan']))} only"}
    lots = _lots(con, user, token)
    if not lots:
        return {"plan_id": p["id"], "plan": p["plan"], "note": "no open lots on this account"}
    avg, ratio = _avg(lots), _mc_ratio(lots)
    if price is None and mcap and ratio:
        price = mcap / ratio
    st = p["state"]
    peak = st["peak_px"].get(user, avg)
    out = {"plan_id": p["id"], "set_ts": p["created_ts"], "client": p["client"], "reason": p["reason"], "plan": p["plan"],
           "sold_share": st["sold"].get(user, 0.0), "peak_mc_since_entry": round(peak * ratio) if ratio else None,
           "trailing_active": bool(st["trail_peak_px"].get(user)), "triggers": []}
    if not price:
        return out

    def dist(px):
        return round((px / price - 1) * 100, 2)
    for i, tp in enumerate(p["plan"].get("take_profits") or []):
        px = _px(tp["kind"], tp["v"], avg, ratio)
        out["triggers"].append({"trigger": f"tp{i + 1}", "fired": i in st["fired"].get(user, []),
                                "mc": round(px * ratio) if ratio else None, "distance_pct": dist(px)})
    if st["stop_px"].get(user):
        px = st["stop_px"][user]
        out["triggers"].append({"trigger": "stop", "mc": round(px * ratio) if ratio else None, "distance_pct": dist(px)})
    tr = p["plan"].get("trailing")
    if tr:
        tpk = st["trail_peak_px"].get(user)
        px = tpk * (1 - tr["trail_pct"] / 100) if tpk else avg * (1 + tr["activate_pct"] / 100)
        out["triggers"].append({"trigger": "trailing" if tpk else "trailing_activation",
                                "mc": round(px * ratio) if ratio else None, "distance_pct": dist(px)})
    ts_ = p["plan"].get("time_stop")
    if ts_:
        last_entry = max(t["opened_ts"] or 0 for t in lots)
        out["triggers"].append({"trigger": "time_stop", "at_ts": int(last_entry + ts_["after_min"] * 60),
                                "if_pnl_below_pct": ts_["if_pnl_below_pct"]})
    return out


def events(con, since_ts=0, limit=200):
    """get_exit_events: executed (and shadow) triggers since since_ts, with the real sell's cost when known."""
    ensure(con)
    rows = [dict(r) for r in con.execute("SELECT * FROM exit_events WHERE ts>=? ORDER BY ts DESC LIMIT ?",
                                         (int(since_ts or 0), int(limit)))]
    try:
        from trade import settings as ts
        tcon = ts.connect()
        try:
            for r in rows:
                o = tcon.execute("SELECT o.cost_pct, o.signature, o.status FROM orders o JOIN positions p ON p.id=o.position_id "
                                 "WHERE p.token=? AND o.side='sell' AND o.ts BETWEEN ? AND ? ORDER BY o.ts LIMIT 1",
                                 (r["token"], r["ts"] - 5, r["ts"] + 180)).fetchone()
                r["real_sell"] = ({"slippage_cost_pct": o[0], "tx_signature": o[1], "status": o[2]} if o else None)
        finally:
            tcon.close()
    except Exception:  # noqa: BLE001
        pass
    return rows
