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
                result is under if_pnl_below_pct % (GROSS: price vs the average entry; the panel's "time stop" field is
                this with if_pnl_below_pct 1000 = everything out after X min)
  time_stop_min, min_profit_pct (12.11., owner's order point 3): from time_stop_min minutes after the LAST entry on,
                sell everything whenever the result NET of the round-trip cost (trade/cost.round_trip, the same model as
                every EV: 2 x fee_side + 2 x the impact of the position's stake in the pool) is under min_profit_pct %
                (default 0 = at least break-even after cost). Trigger "time_stop_min".
  max_stop_pct  (12.11.) the widest stop the plan accepts, percent below the average entry (12 = never wider than
                -12 %): a stop the plan gives that is wider is REFUSED with the numbers; a plan without its own stop gets
                -max_stop_pct when that is tighter than the stop it would keep. sl_default (sl_floor) still holds on top;
                the owner's own typed SL (a panel plan) is never limited by it (11.11.: "ručno uvijek nadjačava").
  breakeven_after_tp1, breakeven_buffer_pct (13.11., owner's order point 4: "Nativni break-even stop nakon TP1"): once
                TP1 (the plan's first take profit) has sold, the stop of what is left moves to break-even: the average
                entry + breakeven_buffer_pct % (default: the round-trip cost of the rest, trade/cost.round_trip, the
                same model as min_profit_pct). Never lower than the stop in force (a tighter stop stays), so never
                wider than sl_default either; works wherever the plan executes (paper and live). An exit_events row
                trigger "breakeven" (share 0) and the plan's view / describe() show it; the stop that then fires is
                the trigger "stop" with the note "break-even".
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

13.11. (owner's order point 2: "Slippage na stop i trailing izlazima (~5 % preko triggera)"; the 12.11. logs: X's
stop at MC $62.6k fired at $58.3k, ber's trailing at ~$446k fired at $425k, and the real sells landed 1.3-1.9 s after
the trigger at about those prices, so the gap opened BEFORE the trigger, between the level and the first price the
executor saw): the stop and the trailing also read the newest trade the PumpPortal feed saw in the token (run_live.py
-> hype.db live_trades, sub-second, local, no API cost; fresh_prices) and fire on the lower of that and the market
quote (DexScreener 3-s cache); the peaks and the take profits keep the market quote. Every executed trigger records
the level it crossed, the price that crossed it, its feed and its age (exit_events level_px, px_src, px_age_s,
trig_ts), and a sale on the real account rings trade/wake, so run_trade sends the real sell within ~0.1 s instead
of its next pass (it measures the fill against the level: trade.db exit_fills).

Safety: a price older than STALE_S (60 s) fires only the hard stop, never a TP or the trailing; the owner's
"Pauziraj exit planove" (trade settings exit_plans_paused) stops every plan at once and the default TP/SL of each
position is back (league/auto.fast_once skips only lots whose plan is in force); flag exit_plans: off nothing, shadow
and paper on the real Autopilot account only log what a plan would do (shadow_decisions), paper executes on the demo
account autopilot-paper, live on both. 11.11. (Jure: GTA's plan was only logged and the real exit went through the
default TP): the owner switch exit_plan_live ("live" = on, default off) makes a plan execute on the REAL account for
a Grok autotrade position (every open lot bought by Grok autotrade, source "Grok auto (MCP)", while Grok autotrade is
on) whatever exit_plans' mode (grok_live); everything else as above. execution() says per account whether a plan
sells live or paper, and why (get_portfolio_status, set_exit_plan). Every execution: table exit_events (trigger
tp1/tp2/.../trailing/stop/time_stop, plan_id, price, MC, share, PnL, note exit_plan_live when that switch made it
run) and a notice to the owner (ui/grokauto.notify: Telegram when set, log).

11.11. (owner: "Plan izlaza uz kupnju: DA. Kad ručna ili autotrade kupnja ima TP/SL/trailing/time stop u panelu, server
uz kupnju odmah postavi exit plan i taj plan se STVARNO izvršava na pravom računu ... Stop nikad ne smije biti širi od
sl_default"): a plan the owner's own action sets (ui/pravitrade: a buy with exit fields from the Autopilot panel, Brza
kupnja, Kupi from "Što kupiti", a Grok autotrade buy, an approved Grok request, "Uredi SL-TP") is a PANEL plan: its
client starts with PANEL_SRC and under exit_plan_live it executes on the real account whoever bought the lots
(panel_live). Its stop is never looser than sl_floor(): the stricter of the owner's sl_default (trade settings, the
Autopilot's default stop). status() says per position whether its plan runs live, only on paper or in
the shadow, and why (the Autopilot page, get_portfolio_status).
"""
import json
import re
import sqlite3
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
# 13.11. (owner's order point 2): the level a trigger crossed (USD per token), the feed and age of the price that
# crossed it, and the trigger's time to the millisecond (run_trade measures the real sale's latency and slip by them)
EVENT_COLS = (("level_px", "REAL"), ("px_src", "TEXT"), ("px_age_s", "REAL"), ("trig_ts", "REAL"))
_LAST = {}   # token -> (price, mcap, liq, ts): the last good quote, for the staleness rule


def ensure(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(exit_events)")}
    for col, typ in EVENT_COLS:
        if col not in have:
            try:
                con.execute(f"ALTER TABLE exit_events ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as e:   # another connection added it a moment ago
                if "duplicate column" not in str(e):
                    raise


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


def validate(con, token, plan, sl_default, now=None, extra=None, tighten_only=True, hr=False):
    """The plan normalized, with the stop's price per account; ValueError with the reason. Every account must hold
    an open position in the token (at least one).
    11.11. (plan uz kupnju): extra {user: [lot]} = lots about to be bought (the check runs BEFORE anything is written,
    on the position as it will be); tighten_only=False for the owner's own exit (a panel plan may loosen a stop, never
    past sl_default); hr = the refusals in the owner's words ("SL −40 % je širi od zadanog −30 %; najviše −30 %")."""
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    out = {"take_profits": [], "trailing": None, "stop": None, "time_stop": None,
           "reason": str(plan.get("reason") or "")[:300]}
    if isinstance(plan.get("panel"), dict):   # 11.11.: the owner's fields as typed (shown, and compared on a DCA)
        out["panel"] = {k: plan["panel"].get(k) for k in ("tp", "sl", "trail", "time")}
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
    # 12.11. (owner's order point 3): a time stop measured NET of the cost, and the widest stop the plan accepts
    if plan.get("time_stop_min") is not None:
        out["time_stop_min"] = _num(plan["time_stop_min"], "time_stop_min", 1, 7 * 1440)
        out["min_profit_pct"] = (_num(plan["min_profit_pct"], "min_profit_pct", -99, 1000)
                                 if plan.get("min_profit_pct") is not None else 0.0)
    elif plan.get("min_profit_pct") is not None:
        raise ValueError("min_profit_pct goes with time_stop_min (after time_stop_min minutes, sell when the net "
                         "result is under min_profit_pct)")
    max_stop = None
    if plan.get("max_stop_pct") is not None:
        max_stop = abs(_num(plan["max_stop_pct"], "max_stop_pct", -99, 99))   # 12 and -12 mean the same: -12 %
        if max_stop < 1:
            raise ValueError("max_stop_pct must be 1..99 (percent below the average entry)")
        out["max_stop_pct"] = max_stop
    stop = _level(plan["stop"], "stop") if plan.get("stop") is not None else None
    if not (out["take_profits"] or out["trailing"] or stop or out["time_stop"] or out.get("time_stop_min")
            or max_stop):
        raise ValueError("an empty plan: give take_profits, trailing, stop, time_stop or time_stop_min")
    # 13.11. (owner's order point 4): the rest's stop to break-even (entry + cost) once TP1 has sold
    be = plan.get("breakeven_after_tp1")
    if be not in (None, True, False):
        raise ValueError("breakeven_after_tp1 must be true or false")
    if be:
        if not out["take_profits"]:
            raise ValueError("breakeven_after_tp1 needs take_profits: the stop moves to break-even after TP1 sold")
        if out["take_profits"][0]["sell_share"] >= 1 - 1e-9:
            raise ValueError("breakeven_after_tp1: TP1 sells the whole position, nothing is left for a break-even stop")
        out["breakeven_after_tp1"] = True
        out["breakeven_buffer_pct"] = None
        if plan.get("breakeven_buffer_pct") is not None:
            buf = _num(plan["breakeven_buffer_pct"], "breakeven_buffer_pct", 0, 50)
            tp1 = out["take_profits"][0]
            if tp1["kind"] == "pct" and tp1["v"] <= buf + 1e-9:
                raise ValueError(f"TP1 +{tp1['v']:g} % is not above the break-even level +{buf:g} %: "
                                 "the stop would sell the rest at once")
            out["breakeven_buffer_pct"] = buf
    elif plan.get("breakeven_buffer_pct") is not None:
        raise ValueError("breakeven_buffer_pct goes with breakeven_after_tp1 true")
    acc = plan.get("accounts")
    if acc is not None:
        acc = [acc] if isinstance(acc, str) else acc
        if not isinstance(acc, list) or not acc or any(a not in _users() for a in acc):
            raise ValueError(f"accounts must be a list of {', '.join(_users())}")
        out["accounts"] = sorted(set(acc))
    held = {u: _lots(con, u, token) + list((extra or {}).get(u) or []) for u in _scope(out)}
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
                if hr:
                    raise ValueError(f"TP MC {mc_words(tp['v'])} je ispod prosječnog ulaza")
                raise ValueError(f"take profit at MC ${tp['v']:,.0f} is under the average entry")
        floor = avg * (1 - sl_default / 100)
        cap = avg * (1 - max_stop / 100) if max_stop else None   # 12.11.: the plan's own widest stop
        cur = current_stop_px(con, u, token, lots)
        if stop:
            px = _px(stop[0], stop[1], avg, ratio)
            if px < floor * (1 - 1e-9):
                if hr:   # 11.11. (owner): refused with the numbers, the level is never changed silently
                    raise ValueError(f"SL {stop_words(stop, px, avg)} je širi od zadanog −{sl_default:g} %; "
                                     f"najviše −{sl_default:g} %")
                raise ValueError(f"stop is looser than sl_default (-{sl_default:g} % from the average entry)")
            if cap and px < cap * (1 - 1e-9):
                if hr:
                    raise ValueError(f"SL {stop_words(stop, px, avg)} je širi od max_stop_pct −{max_stop:g} % ovog "
                                     f"plana; najviše −{max_stop:g} % od prosječnog ulaza")
                raise ValueError(f"stop {(px / avg - 1) * 100:+.1f} % from the average entry is wider than "
                                 f"max_stop_pct (-{max_stop:g} %): set the stop at -{max_stop:g} % or tighter, or "
                                 "raise max_stop_pct")
            if tighten_only and cur and px < cur - 1e-12:
                raise ValueError(f"a stop may only be tightened: the position's stop is "
                                 f"{(cur / avg - 1) * 100:+.1f} % from the average entry")
            stop_px[u] = px
        else:
            stop_px[u] = max(cur or 0, floor) if cur else floor
            if cap and stop_px[u] < cap:   # 12.11.: no stop of its own: the plan sets -max_stop_pct itself
                stop_px[u] = cap
    out["stop"] = {"kind": stop[0], "v": stop[1]} if stop else None
    return out, stop_px


def active(con, token, ro=False):
    """The token's active plan (plan and state as dicts) or None. ro (11.11.): a read-only connection (the Autopilot
    page): the table is not created, a database without it has no plan."""
    if ro:
        try:
            r = con.execute("SELECT * FROM exit_plans WHERE token=? AND status='active' ORDER BY id DESC LIMIT 1",
                            (token,)).fetchone()
        except sqlite3.Error:
            return None
    else:
        ensure(con)
        r = con.execute("SELECT * FROM exit_plans WHERE token=? AND status='active' ORDER BY id DESC LIMIT 1", (token,)).fetchone()
    if not r:
        return None
    d = dict(r) if hasattr(r, "keys") else dict(zip([c[0] for c in con.execute(
        "SELECT * FROM exit_plans LIMIT 0").description], r))
    d["plan"], d["state"] = json.loads(d["plan"]), json.loads(d["state"] or "{}")
    return d


def set_plan(con, token, plan, sl_default, client="mcp", now=None, tighten_only=True, hr=False):
    """Store a plan (the previous one of the token is replaced). Returns {"plan_id", "plan", "replaced"}."""
    ensure(con)
    now = int(now or time.time())
    norm, stop_px = validate(con, token, plan, sl_default, now, tighten_only=tighten_only, hr=hr)
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


LIVE_FLAG = "exit_plan_live"


def _grok_src():
    try:
        from ui import grokauto
        return grokauto.SRC
    except Exception:  # noqa: BLE001
        return "Grok auto (MCP)"


# 11.11. (Jure: "exit_plan_live: DA, svaka live pozicija (autotrade i odobreni tradeovi) mora imati aktivan exit
# plan"): an MCP buy request the owner approved is bought with this source (ui/pravitrade._post_mcp_ok); it starts
# with "ručno" so the daily automatic-spend limit counts it as the owner's own buy (trade/executor.OWN_REASONS)
APPROVED_SRC = "ručno: Grok odobreno (MCP)"


def grok_live(user, lots):
    """11.11. (Jure: GTA's plan was only logged while the flag exit_plans was paper, and the real exit went through the
    default TP): True when the owner switch exit_plan_live is "live", the account is the real Autopilot account, every
    open lot of the token is a Grok autotrade buy (league trades source "Grok auto (MCP)") or an MCP request the owner
    approved (APPROVED_SRC, 11.11.), and Grok autotrade is switched on whenever an autotrade lot is among them (Grok's
    limits: a plan only sells, which autotrade allows for any open position while it is on). Then
    the plan runs on the real account whatever exit_plans' mode; everything else is unchanged."""
    try:
        from trade import settings as ts
        if user != ts.LEAGUE_USER or ts.flag(LIVE_FLAG) != "live":
            return False
        src = _grok_src()
        if not lots or any((t.get("source") or "") not in (src, APPROVED_SRC) for t in lots):
            return False
        if all((t.get("source") or "") == APPROVED_SRC for t in lots):
            return True   # 11.11.: the owner approved the buy himself; the switch alone covers its plan
        from ui import grokauto
        tcon = ts.connect()
        try:
            return bool(grokauto.state(tcon)["on"])
        finally:
            tcon.close()
    except Exception:  # noqa: BLE001 - unreadable: the old behaviour (exit_plans decides)
        return False


# 11.11. (owner: "Plan izlaza uz kupnju: DA"): the client of a plan the owner's own action set (a buy with exit fields
# from the panel, a Grok autotrade buy, an approved Grok request, a proposal's Kupi, "Uredi SL-TP"; ui/pravitrade)
PANEL_SRC = "panel:"
# 11.11.: a live plan's stop is never looser than this, percent below the average entry, nor than the owner's
# sl_default (sl_floor takes the stricter). Until 11.11. ensure_live_plans read the owner's setting as
# ts.merged(tcon), without the config: a TypeError every time, so every default plan got its fallback, -30 %.
DEFAULT_PLAN_SL = 30.0   # the stop of Grok's default plans (ensure_live_plans), as they ran before 11.11.


# 11.11. (owner: "Ako ja ručno prilikom kupovine postavim drugačiji stop loss nego što je zadan … ručno uvijek
# nadjačava ono što je zapisano programski"): a stop the owner typed himself is checked against this only (a sane
# ceiling), never against sl_default; sl_default stays the default of an empty field and the limit of Grok's stops
OWNER_SL_MAX = 99.0


def owner_floor(typed_sl, floor):
    """The floor a stop is validated with: OWNER_SL_MAX when the owner typed the stop himself, else `floor`."""
    return OWNER_SL_MAX if (typed_sl or "").strip() else floor


def sl_floor(cfg=None):
    """Percent below the average entry a panel / live plan's stop may be at most: the owner's sl_default (trade
    settings "sl_default", the Autopilot's default stop under Pravila, SL_DEFAULT 60 unless changed; cfg = trade
    settings merged, else read here). 11.11. (Jure: "Stop nikad ne smije biti širi od sl_default"): exactly that, no
    other cap (the "-30 %" the plans showed came from a TypeError fallback in ensure_live_plans, fixed)."""
    from trade import settings as ts
    v = (cfg or {}).get("sl_default") if cfg is not None else None
    if v is None:
        try:
            tcon = ts.connect()
            try:
                v = ts.raw(tcon).get("sl_default")
            finally:
                tcon.close()
        except Exception:  # noqa: BLE001 - unreadable: the default
            v = None
    try:
        v = abs(float(v)) if v else float(ts.SL_DEFAULT)
    except (TypeError, ValueError):
        v = float(ts.SL_DEFAULT)
    return v


def is_panel(plan):
    return bool(plan) and str(plan.get("client") or "").startswith(PANEL_SRC)


def panel_live(plan, user):
    """True when a panel plan executes on the real account by the owner's switch exit_plan_live (whoever bought the
    position's lots: the owner set its exit himself)."""
    try:
        from trade import settings as ts
        from . import flags
        return is_panel(plan) and user == ts.LEAGUE_USER and flags.mode(LIVE_FLAG) == "live"
    except Exception:  # noqa: BLE001
        return False


def execution(user, lots, m=None, plan=None):
    """{"mode": live | paper | shadow | off, "executes": bool, "real_account": bool, "why"} of a plan on one account:
    live = the plan sells on the real account (exit_plans live, or exit_plan_live for a Grok autotrade position or a
    panel plan); paper = it sells only on the demo account autopilot-paper, the real account only logs it."""
    from trade import settings as ts
    from . import flags
    m = m or flags.mode("exit_plans")
    real = user == ts.LEAGUE_USER
    if paused():
        return {"mode": "off", "executes": False, "real_account": real, "why": "vlasnik je pauzirao planove izlaza"}
    if flags.applies("exit_plans", user, m):
        return {"mode": "live" if real else "paper", "executes": True, "real_account": real,
                "why": f"zastavica exit_plans: {m}"}
    if real and panel_live(plan, user):   # 11.11.: the owner's own exit from the panel
        return {"mode": "live", "executes": True, "real_account": True,
                "why": "exit_plan_live: plan iz panela (uz kupnju ili spremljen SL/TP) izvršava se na pravom računu"}
    if real and grok_live(user, lots):
        return {"mode": "live", "executes": True, "real_account": True,
                "why": "exit_plan_live: Grok autotrade pozicija izvršava se na pravom računu"}
    why = {"paper": "exit_plans je paper: na pravom računu samo zapis (sjena), izvršava se na demo računu "
                    "autopilot-paper; zadani TP/SL pozicije ostaje",
           "shadow": "exit_plans je u sjeni: samo zapis, zadani TP/SL ostaje",
           "off": "exit_plans je isključen: zadani TP/SL ostaje"}.get(m, m)
    if real:
        try:
            if ts.flag(LIVE_FLAG) == "live":
                why += ("; exit_plan_live vrijedi za plan iz panela (kupnja s izlazom, spremljen SL/TP) i za pozicije u "
                        "kojima je svaki ulaz Grok autotrade, dok je Grok autotrade uključen")
        except Exception:  # noqa: BLE001
            pass
    return {"mode": "paper" if m == "paper" else m, "executes": False, "real_account": real, "why": why}


def in_force_tokens(con, user):
    """Tokens whose plan replaces the default TP/SL of `user`'s lots now (league/auto.fast_once skips those): every
    planned token while exit_plans applies to the account, else (11.11.) the Grok autotrade positions and the panel
    plans under exit_plan_live."""
    try:
        from trade import settings as ts
        from . import flags
        m = flags.mode("exit_plans")   # cached reads first: the 1-s exit loop asks this for every account
        on = m != "off" and flags.applies("exit_plans", user, m)
        sw = not on and user == ts.LEAGUE_USER and flags.mode(LIVE_FLAG) == "live"
        if not (on or sw) or paused():
            return set()
        ensure(con)
        rows = [(t, cl) for t, pl, cl in con.execute("SELECT token, plan, client FROM exit_plans WHERE status='active'")
                if user in _scope(json.loads(pl or "{}"))]
        if on:
            return {t for t, _cl in rows}
        return {t for t, cl in rows if str(cl or "").startswith(PANEL_SRC) or grok_live(user, _lots(con, user, t))}
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


FRESH_S = 5   # 13.11.: a PumpPortal trade older than this is no fresher than the market quote
FRESH_BAND = (0.5, 2.0)   # 13.11.: a trade price this far from a fresh market quote is a bad print (or units), not used


def _sol_usd():
    """SOL/USD without a network call (trade/equity.sol_usd_cached: the process' cache, else the last wallet
    snapshot's, at most minutes old): the 1-s exit loop never waits on a price request for it."""
    try:
        from trade import equity
        return equity.sol_usd_cached()
    except Exception:  # noqa: BLE001
        return None


def fresh_prices(tokens, now, path=None):
    """13.11. (owner's order point 2): {token: (USD per token, age in s, "pumpportal")} of the newest trade the
    PumpPortal feed (run_live.py, hype.db live_trades: every trade of a subscribed token, written once a second)
    saw in each token within FRESH_S, at the SOL price already known (_sol_usd). A local read-only query per token:
    no network, no API cost (the feed subscribes the Autopilot's open lots and planned tokens, live/pumpportal.wanted).
    {} when the feed has nothing fresh (a token PumpPortal does not cover, no trade in FRESH_S, no SOL price)."""
    if not tokens:
        return {}
    try:
        from live import store as live_store
        con = live_store.ro(path)
    except Exception:  # noqa: BLE001
        return {}
    if con is None:
        return {}
    out = {}
    try:
        rows = {}
        for t in tokens:
            r = con.execute("SELECT price_sol, ts FROM live_trades WHERE mint=? AND ts>=? ORDER BY ts DESC, rowid DESC "
                            "LIMIT 1", (t, int(now - FRESH_S))).fetchone()
            if r and r[0] and r[0] > 0:
                rows[t] = r
        sol = _sol_usd() if rows else None
        if sol:
            for t, (px_sol, ts) in rows.items():
                out[t] = (px_sol * sol, max(0.0, now - ts), "pumpportal")
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def _event(con, p, user, token, trig, price, mcap, share, pnl, mode, stale, note="", level_px=None, px_src=None,
           px_age_s=None, trig_ts=None):
    """One exit_events row. 13.11.: level_px / px_src / px_age_s / trig_ts (EVENT_COLS) when the caller knows them."""
    t = time.time() if trig_ts is None else trig_ts
    con.execute("INSERT INTO exit_events (ts, plan_id, user, token, trigger, price, mcap, share, pnl_usd, mode, stale, "
                "note, level_px, px_src, px_age_s, trig_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(t), p["id"], user, token, trig, price, mcap, share, pnl, mode, int(bool(stale)), note, level_px,
                 px_src, px_age_s, t))
    con.commit()


def _sell(con, user, lots, frac_of_rest, price, liq, mcap, rule):
    """Sell frac_of_rest of every open lot (1 = all). Returns the PnL in USD.
    11.11. (owner: "plan se STVARNO izvršava na pravom računu"): on the real account a partial sale keeps the lot's
    size and lowers its quantity (store.sell_part, as the Smart sell's partial fills), because run_trade mirrors the
    share still held (qty / bought qty = qty / (size_usd / entry_eff)) into the real position. store.sell_partial
    scales size_usd and qty together, so that share stayed 1.0 and a plan's TP1 half was never sold for real (the
    real position kept everything until a full close). The demo account keeps sell_partial (its own closed rows)."""
    from trade import settings as ts
    pnl = 0.0
    for t in lots:
        if frac_of_rest >= 0.999:
            pnl += store.sell(con, user, t["id"], price, liq, f"plan izlaza: {rule}", mcap=mcap, exit_rule=rule)
        elif user == ts.LEAGUE_USER:
            q = (t["qty"] or 0) * frac_of_rest
            net = store.sell_part(con, t["id"], frac_of_rest, price, liq)
            pnl += net - q * (t.get("entry_eff") or t.get("entry_px") or 0)
        else:
            p, _all = store.sell_partial(con, user, t["id"], frac_of_rest, price, liq, mcap=mcap)
            pnl += p
    return pnl


def net_pnl_pct(lots, price, liq=None):
    """12.11. (owner's order point 3: "neto"): the position's result at `price` NET of the round-trip cost, percent
    from the average entry: (price / average entry - 1) - trade/cost.round_trip(the open lots' stake in USD, liq), the
    one cost model every EV uses (fee_side calibrated from trade.db, else league/store.FEE; liq unknown = its
    DEFAULT_LIQ). None without an entry price."""
    avg = _avg(lots)
    if not avg or not price:
        return None
    from trade import cost
    size = sum(t.get("size_usd") or 0 for t in lots) or None
    return ((price / avg - 1) - cost.round_trip(size, liq)) * 100


def levels(p, user):
    """13.11.: {"stop": USD per token, "trailing": the trailing's level now (its peak - trail_pct) or None} of one
    account; the price a downside trigger fires at."""
    st, tr = p["state"], p["plan"].get("trailing")
    pk = st.get("trail_peak_px", {}).get(user)
    return {"stop": st.get("stop_px", {}).get(user),
            "trailing": pk * (1 - tr["trail_pct"] / 100) if tr and pk else None}


def decide(p, user, lots, price, mcap, age_s, now, liq=None, low_px=None):
    """(trigger, share of the ORIGINAL position, frac of what is left) or None, and the state changes (in place).
    liq (12.11.): the pool's liquidity now, for the cost of the net time stop (time_stop_min).
    low_px (13.11., owner's order point 2): a fresher price of the token (fresh_prices: the newest PumpPortal trade);
    the stop and the trailing fire on the lower of it and `price`, everything else (peaks, take profits, time stops)
    stays on `price`."""
    st, plan = p["state"], p["plan"]
    dn = min(price, low_px) if low_px and low_px > 0 else price
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
    if stop and dn <= stop:
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
    if tr and tp_peak and dn <= tp_peak * (1 - tr["trail_pct"] / 100):
        return "trailing", left, 1.0
    ts_ = plan.get("time_stop")
    if ts_:
        last_entry = max(t["opened_ts"] or 0 for t in lots)
        if now - last_entry >= ts_["after_min"] * 60 and pnl_pct < ts_["if_pnl_below_pct"]:
            return "time_stop", left, 1.0
    if plan.get("time_stop_min"):   # 12.11.: X min after the last entry, out unless at least min_profit_pct NET
        last_entry = max(t["opened_ts"] or 0 for t in lots)
        if now - last_entry >= plan["time_stop_min"] * 60:
            net = net_pnl_pct(lots, price, liq)
            if net is not None and net < (plan.get("min_profit_pct") or 0.0) - 1e-9:
                return "time_stop_min", left, 1.0
    return None


def _ring(why):
    try:
        from trade import wake
        wake.ring(why)
    except Exception:  # noqa: BLE001 - run_trade then finds the sale at its next pass, as before
        pass


def _level_words(level, px, mcap, src, age):
    """13.11.: ", razina MC $62,600 (cijena −6,9 % od razine, pumpportal, 1 s)" for the notice of an execution."""
    if not level or not px:
        return ""
    ratio = mcap / px if mcap and px else None
    lvl = f"MC ${level * ratio:,.0f}" if ratio else f"${level:.6g}"
    return f", razina {lvl} (cijena {(px / level - 1) * 100:+.1f} % od razine, {src}, {age or 0:.0f} s)"


BE_MIN_GAP = 0.005   # 13.11.: a break-even level at or over the TP1 price goes this far under it (never fires at once)


def breakeven(con, p, user, tok, lots, price, mcap, liq, frac, mode):
    """13.11. (owner's order point 4: "Ako set_exit_plan ... ne podržava automatsko pomicanje stopa na break-even
    (entry + trošak) nakon izvršenja TP1, dodaj tu opciju za preostali dio pozicije"): after TP1 of a plan with
    breakeven_after_tp1, the stop of `user` moves to the average entry + breakeven_buffer_pct, by default + the
    round-trip cost of what is left (trade/cost.round_trip: the rest's stake in the pool's liquidity now), but never
    under the stop in force (state stop_px only goes up here) and never at / over the TP1 price itself (BE_MIN_GAP
    under it, so the rest is not sold the next second when TP1 sat under the cost). An exit_events row (trigger
    "breakeven", share 0) and state["be"][user]. Returns the words for the TP1 notice."""
    st, plan = p["state"], p["plan"]
    avg = _avg(lots)
    if not avg:
        return ""
    buf = plan.get("breakeven_buffer_pct")
    if buf is None:
        from trade import cost
        rest = sum(t.get("size_usd") or 0 for t in lots) * max(0.0, 1.0 - frac)
        buf = cost.round_trip(rest or None, liq) * 100
    be_px = avg * (1 + buf / 100)
    capped = be_px >= price * (1 - BE_MIN_GAP)
    if capped:
        be_px = price * (1 - BE_MIN_GAP)
    cur = st["stop_px"].get(user) or 0
    new = max(cur, be_px)
    st["stop_px"][user] = new
    st.setdefault("be", {})[user] = {"px": new, "buf_pct": round(buf, 3), "ts": int(time.time()), "capped": capped}
    ratio = mcap / price if mcap and price else None
    words = f"MC ${new * ratio:,.0f}" if ratio else f"${new:.6g}"
    note = (f"stop na break-even: prosječni ulaz + {buf:.2f} % troška = {words}"
            + ("; TP1 je ispod troška: stop tik ispod cijene TP1" if capped else "")
            + ("; stop u snazi je već bio viši, ostaje" if new > be_px + 1e-15 else ""))
    _event(con, p, user, tok, "breakeven", new, new * ratio if ratio else None, 0.0, None, mode, False, note,
           level_px=be_px, px_src="plan")
    return f"; {note}"


DEFAULT_CLIENT = "auto: zadani plan (vlasnik 11.11.)"


def default_plan(lots, sl_default=30.0):
    """The plan a live Grok position gets when none is set: its own TP / SL (league auto tpsl of the newest lot, as a
    percent from the average entry), all of it at the TP; no TP known = only the stop. None when nothing is known."""
    avg = _avg(lots)
    if not avg:
        return None
    a = {}
    for t in reversed(lots):
        try:
            a = json.loads(t.get("auto") or "{}") or {}
        except ValueError:
            a = {}
        if a.get("mode") == "tpsl":
            break
    plan = {"accounts": [lots[0]["user"]], "reason": "zadani plan: vlastiti TP/SL pozicije (exit_plan_live, vlasnik 11.11.)"}
    tp, sl = a.get("tp_px"), a.get("sl_px")
    if tp and tp > avg:
        plan["take_profits"] = [{"at_pct": round((tp / avg - 1) * 100, 2), "sell_share": 1.0}]
    floor = -abs(float(sl_default or 30))
    st = round((sl / avg - 1) * 100, 2) if sl and sl < avg else floor
    plan["stop"] = {"at_pct": max(st, floor)}
    return plan


def ensure_live_plans(con, now=None, sl_default=None, log=print):
    """11.11. (Jure: "svaka live pozicija (autotrade i odobreni tradeovi) mora imati aktivan exit plan"): every open
    real-account token that exit_plan_live covers (grok_live) and that has no active plan gets default_plan. [token]."""
    from trade import settings as ts
    from . import flags
    if flags.mode(LIVE_FLAG) != "live" or paused():
        return []
    if sl_default is None:
        # 11.11.: was ts.merged(tcon) (no config: TypeError, so always the fallback 30); Grok's default plans keep
        # the -30 % they ran with (never looser), and never looser than the owner's sl_default either
        sl_default = min(DEFAULT_PLAN_SL, sl_floor())
    out = []
    toks = [r[0] for r in con.execute("SELECT DISTINCT token FROM trades WHERE user=? AND status='open'", (ts.LEAGUE_USER,))]
    for tok in toks:
        if active(con, tok):
            continue
        lots = _lots(con, ts.LEAGUE_USER, tok)
        if not grok_live(ts.LEAGUE_USER, lots):
            continue
        plan = default_plan(lots, sl_default)
        if not plan:
            continue
        try:
            set_plan(con, tok, plan, sl_default, client=DEFAULT_CLIENT, now=now)
            out.append(tok)
            log(f"plan izlaza: {tok[:6]} dobio zadani plan (live pozicija bez plana, exit_plan_live)")
        except ValueError as e:
            log(f"plan izlaza: {tok[:6]} bez zadanog plana: {e}")
    return out


def run_once(con, market, now=None):
    """One pass over the active plans: [(user, token, trigger, text)] of what was executed (or shadow-logged)."""
    from trade import settings as ts
    from . import flags
    now = now or time.time()
    ensure(con)
    m = flags.mode("exit_plans")
    sw = flags.mode(LIVE_FLAG) == "live"   # 11.11.: Grok autotrade positions on the real account (grok_live)
    if sw and not paused():
        try:
            ensure_live_plans(con, now)
        except Exception as e:  # noqa: BLE001 - the plans that exist keep running
            print(f"plan izlaza: zadani planovi: {type(e).__name__}: {e}", flush=True)
    if (m == "off" and not sw) or paused():
        return []
    plans = [dict(r) for r in con.execute("SELECT * FROM exit_plans WHERE status='active'")]
    if not plans:
        return []
    for p in plans:
        p["plan"], p["state"] = json.loads(p["plan"]), json.loads(p["state"] or "{}")
    q = quote(market, {p["token"] for p in plans}, now)
    try:   # 13.11. (owner's order point 2): the newest PumpPortal trade, for the stop and the trailing
        fr = fresh_prices(sorted(q), now)
    except Exception:  # noqa: BLE001 - the market quote alone, as before
        fr = {}
    done = []
    for p in plans:
        tok = p["token"]
        if tok not in q:
            continue
        price, mcap, liq, age = q[tok]
        low, low_age = None, None
        f = fr.get(tok)
        if f and f[0] < price and (age > STALE_S or FRESH_BAND[0] <= f[0] / price <= FRESH_BAND[1]):
            low, low_age = f[0], f[1]
        any_open = False
        for user in _scope(p["plan"]):   # 10.11.: a plan with "accounts" leaves the other account's lots alone
            lots = _lots(con, user, tok)
            if not lots:
                continue
            any_open = True
            on, sh = flags.applies("exit_plans", user, m), flags.shadowing("exit_plans", user, m)
            via = ""
            if not on and sw and (panel_live(p, user) or grok_live(user, lots)):   # 11.11.: a panel plan too
                on, via = True, LIVE_FLAG
            if not (on or sh):
                continue
            before = json.dumps(p["state"])
            hit = decide(p, user, lots, price, mcap, age, now, liq=liq, low_px=low)
            if not hit:
                if json.dumps(p["state"]) != before:
                    _save_state(con, p["id"], p["state"])
                continue
            trig, share, frac = hit
            # 13.11. (owner's order point 2): the price that crossed the level (the lower, fresher one for a stop or a
            # trailing, as decide compared), its feed and age, and the level itself (after decide moved the peak)
            lv = levels(p, user)
            px, mc, src, px_age = price, mcap, "tržište", age
            if trig in ("stop", "trailing") and low is not None:
                px, src, px_age = low, "pumpportal", low_age
                mc = mcap * low / price if mcap and price else mcap
            tp = p["plan"]["take_profits"][int(trig[2:]) - 1] if trig.startswith("tp") else None
            level = (lv.get(trig) if trig in ("stop", "trailing") else
                     _px(tp["kind"], tp["v"], _avg(lots), _mc_ratio(lots)) if tp else None)
            be_note = "break-even" if trig == "stop" and (p["state"].get("be") or {}).get(user) else ""
            if trig.startswith("tp"):
                p["state"]["fired"].setdefault(user, []).append(int(trig[2:]) - 1)
            p["state"]["sold"][user] = min(1.0, p["state"]["sold"].get(user, 0.0) + share)
            t_trig = time.time()
            if on:
                try:
                    pnl = _sell(con, user, lots, frac, px, liq, mc, f"plan_{trig}")
                except ValueError as e:   # closed meanwhile: next pass sees it
                    print(f"plan izlaza #{p['id']} {tok[:6]}: {e}", flush=True)
                    continue
                note = "; ".join(x for x in (via, be_note) if x)
                _event(con, p, user, tok, trig, px, mc, share, pnl, "izvršeno", age > STALE_S, note,
                       level_px=level, px_src=src, px_age_s=px_age, trig_ts=t_trig)
                if user == ts.LEAGUE_USER:   # 13.11.: run_trade sends the real sell now, not at its next pass (rung
                    _ring(f"{tok[:6]} {trig}")   # after the sale and its event are committed: it reads both)
                # 11.11.: the account in words (pravi račun = run_trade mirrors it into the real swap), never "sjena"
                acc = "pravi račun, live" if user == ts.LEAGUE_USER else "demo račun, paper"
                text = (f"plan izlaza #{p['id']} {lots[0].get('symbol') or tok[:6]} ({user}, {acc}): {trig}"
                        + (" (break-even)" if be_note else "")
                        + f", prodano {share:.0%} pozicije na MC ${mc or 0:,.0f}, {pnl:+.2f} $"
                        + _level_words(level, px, mc, src, px_age))
            else:
                flags.shadow(con, "exit_plans", None, tok, f"izlaz {trig}", f"prodaj {share:.0%}",
                             {"plan_id": p["id"], "price": px, "mcap": mc}, now)
                _event(con, p, user, tok, trig, px, mc, share, None, "sjena", age > STALE_S, be_note,
                       level_px=level, px_src=src, px_age_s=px_age, trig_ts=t_trig)
                text = f"plan izlaza #{p['id']} {tok[:6]} ({user}, sjena): bi {trig} {share:.0%}"
            if trig == "tp1" and p["plan"].get("breakeven_after_tp1"):   # 13.11. (owner's order point 4)
                text += breakeven(con, p, user, tok, lots, px, mc, liq, frac, "izvršeno" if on else "sjena")
            if on:
                try:
                    from ui import grokauto
                    grokauto.notify(text)
                except Exception:  # noqa: BLE001
                    print(text, flush=True)
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
           "execution": execution(user, lots, plan=p),   # 11.11.: live (sells on the real account) or paper, and why
           "panel": is_panel(p),   # 11.11.: set by the owner's own exit (a buy from the panel, Uredi SL-TP)
           # 12.11.: the net time stop and the widest stop, None when the plan has none
           "time_stop_min": p["plan"].get("time_stop_min"), "min_profit_pct": p["plan"].get("min_profit_pct"),
           "max_stop_pct": p["plan"].get("max_stop_pct"), "summary": describe(p["plan"]),
           "sold_share": st["sold"].get(user, 0.0), "peak_mc_since_entry": round(peak * ratio) if ratio else None,
           "trailing_active": bool(st["trail_peak_px"].get(user)), "triggers": []}
    if p["plan"].get("breakeven_after_tp1"):   # 13.11. (owner's order point 4): armed, and moved once TP1 sold
        be = (st.get("be") or {}).get(user)
        out["breakeven"] = {"after_tp1": True, "buffer_pct": p["plan"].get("breakeven_buffer_pct"),
                            "buffer": "round-trip cost (trade/cost.round_trip)"
                            if p["plan"].get("breakeven_buffer_pct") is None else "fixed",
                            "active": bool(be), "stop_px": be["px"] if be else None,
                            "stop_mc": round(be["px"] * ratio) if be and ratio else None,
                            "buffer_pct_used": be["buf_pct"] if be else None}
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
        out["triggers"].append({"trigger": "stop", "mc": round(px * ratio) if ratio else None, "distance_pct": dist(px),
                                "breakeven": bool((st.get("be") or {}).get(user))})
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
    if p["plan"].get("time_stop_min"):   # 12.11.: the net time stop, with the net result now
        last_entry = max(t["opened_ts"] or 0 for t in lots)
        net = net_pnl_pct(lots, price)
        out["triggers"].append({"trigger": "time_stop_min", "at_ts": int(last_entry + p["plan"]["time_stop_min"] * 60),
                                "min_profit_pct_net": p["plan"].get("min_profit_pct") or 0.0,
                                "net_pnl_pct_now": round(net, 2) if net is not None else None})
    return out


def events(con, since_ts=0, limit=200):
    """get_exit_events: executed (and shadow) triggers since since_ts, with the real sell's cost when known.
    13.11.: newest first by id (a TP1 and its "breakeven" row share a second); a "breakeven" row sold nothing, so it
    has no real sell; the real sell also carries run_trade's measurement (trade.db exit_fills: the fill in USD per
    token and market cap, slip against the level and against the price seen, seconds from the trigger to the order
    and to its answer, the protective slippage try)."""
    ensure(con)
    rows = [dict(r) for r in con.execute("SELECT * FROM exit_events WHERE ts>=? ORDER BY ts DESC, id DESC LIMIT ?",
                                         (int(since_ts or 0), int(limit)))]
    try:
        from trade import settings as ts
        tcon = ts.connect()
        try:
            for r in rows:
                if r["trigger"] == "breakeven" or not r.get("share"):
                    r["real_sell"] = None
                    continue
                o = tcon.execute("SELECT o.cost_pct, o.signature, o.status FROM orders o JOIN positions p ON p.id=o.position_id "
                                 "WHERE p.token=? AND o.side='sell' AND o.ts BETWEEN ? AND ? ORDER BY o.ts LIMIT 1",
                                 (r["token"], r["ts"] - 5, r["ts"] + 180)).fetchone()
                r["real_sell"] = ({"slippage_cost_pct": o[0], "tx_signature": o[1], "status": o[2]} if o else None)
                try:
                    fills = tcon.execute("SELECT fill_px, mc_ratio, slip_level_pct, slip_seen_pct, sent_after_s, "
                                         "latency_s, cap_pct, cap_result FROM exit_fills WHERE event_id=? ORDER BY id",
                                         (r["id"],)).fetchall()
                except sqlite3.Error:   # run_trade has not created the table yet
                    fills = []
                if fills and r["real_sell"] is not None:
                    r["real_sell"]["fills"] = [
                        {"fill_px": f[0], "fill_mc": round(f[0] * f[1]) if f[0] and f[1] else None,
                         "slip_vs_level_pct": f[2], "slip_vs_seen_pct": f[3], "order_after_trigger_s": f[4],
                         "done_after_trigger_s": f[5], "slip_cap_pct": f[6], "slip_cap_result": f[7]} for f in fills]
        finally:
            tcon.close()
    except Exception:  # noqa: BLE001
        pass
    return rows


# ---------- 11.11.: the plan that goes with a buy (the owner's exit fields in the Autopilot panel) ------------------

def pct_words(v, sign=True):
    """-30 -> "−30 %", 15 -> "+15 %" (the page's way of writing a percent)."""
    s = f"{v:+g}" if sign else f"{v:g}"
    return s.replace("-", "−").replace(".", ",") + " %"


def mc_words(v):
    """160000 -> "$160k", 1250000 -> "$1,25M"."""
    if v >= 1e6:
        return f"${v / 1e6:.2f}M".replace(".", ",")
    return f"${v / 1e3:.1f}k".replace(".0k", "k").replace(".", ",")


def stop_words(stop, px, avg):
    """The stop of a refusal: "−40 %" or "MC $85k (−45 % od prosječnog ulaza)"."""
    kind, v = stop if isinstance(stop, tuple) else (stop["kind"], stop["v"])
    if kind == "pct":
        return pct_words(v)
    return f"MC {mc_words(v)} ({pct_words(round((px / avg - 1) * 100, 1))} od prosječnog ulaza)"


_MC_RE = re.compile(r"\$?([0-9.]+)([kmb])?(mc|mcap)?")


def level_of(text, kind):
    """A TP / SL as the panel takes it -> ("pct", percent from the average entry) | ("mc", market cap) | None (empty).
    The same reading as league/auto.parse_level: "30", "+30%", "-25%", a bare positive SL is a drop; "$200k", "1.2m"."""
    s = (text or "").strip().lower().replace(",", ".").replace(" ", "").replace("−", "-").replace("–", "-")
    if not s:
        return None
    m = _MC_RE.fullmatch(s)
    try:
        if m and (s.startswith("$") or m.group(2) or m.group(3)):
            return "mc", float(m.group(1)) * {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(2) or "", 1)
        m = re.fullmatch(r"([+-]?[0-9.]+)%?", s)
        if not m:
            raise ValueError
        v = float(m.group(1))
    except ValueError:
        raise ValueError(f"ne razumijem '{text}': upiši postotak (npr. 30% ili -25%) ili MC (npr. $200k)")
    if kind == "sl" and v > 0:
        v = -v
    if kind == "tp" and v <= 0:
        raise ValueError("TP mora biti iznad ulazne cijene")
    if kind == "sl" and v <= -100:
        raise ValueError("SL mora biti iznad -100%")
    return "pct", v


def field_num(x, name, lo, hi):
    """The panel's trailing % / time stop (min): "" -> None; "8", "8 %", "8,5" -> 8.0 / 8.5; out of range = refused."""
    s = str(x if x is not None else "").strip().lower().replace(",", ".").replace("%", "").replace("min", "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        raise ValueError(f"{name}: upiši broj")
    if not lo <= v <= hi:
        raise ValueError(f"{name} mora biti {lo:g}-{hi:g}")
    return v


def panel_plan(tp="", sl="", trail=None, time_min=None, floor=None, avg_mc=None, reason="", user=None,
               min_profit_pct=None, max_stop_pct=None):
    """The plan of the owner's exit fields (set_plan's format) or None when none is filled in (no exit: the old
    behaviour). The fast path's shape (fast/paper.PLAN, trade/edge rule E): TP sells everything, or HALF when a
    trailing is set (the rest trails from the TP on: activate_pct = the TP's percent, avg_mc turns a market-cap TP
    into one); the stop = the SL typed, empty = -floor (sl_floor); time stop = everything out after_min after the
    last entry (GROSS, unconditional). The fields as typed go with it ("panel").
    12.11.: min_profit_pct (with time_min) makes the time stop the NET one (time_stop_min: out after time_min unless
    at least min_profit_pct after cost); max_stop_pct limits only the stop the plan sets itself (an empty SL field:
    -min(floor, max_stop_pct)), never a typed SL (the owner's own)."""
    from trade import settings as ts
    tp, sl = (tp or "").strip(), (sl or "").strip()
    tp_l, sl_l = level_of(tp, "tp"), level_of(sl, "sl")
    if not (tp_l or sl_l or trail or time_min):
        return None
    plan = {"accounts": [user or ts.LEAGUE_USER], "reason": (reason or "plan uz kupnju (panel)")[:300],
            "panel": {"tp": tp, "sl": sl, "trail": trail, "time": time_min}}
    tp_pct = None
    if tp_l:
        plan["take_profits"] = [{("at_pct" if tp_l[0] == "pct" else "at_mc_usd"): tp_l[1],
                                 "sell_share": 0.5 if trail else 1.0}]
        tp_pct = tp_l[1] if tp_l[0] == "pct" else ((tp_l[1] / avg_mc - 1) * 100 if avg_mc else None)
    if trail:
        plan["trailing"] = {"activate_pct": round(max(0.0, tp_pct or 0.0), 4), "trail_pct": float(trail)}
    if floor is None:
        floor = sl_floor()
    st = sl_l or ("pct", -abs(float(floor)))
    if max_stop_pct and not sl_l:   # 12.11.: the plan's own stop only; a typed SL stays the owner's
        plan["max_stop_pct"] = abs(float(max_stop_pct))
        st = ("pct", -min(abs(float(floor)), abs(float(max_stop_pct))))
    plan["stop"] = {("at_pct" if st[0] == "pct" else "at_mc_usd"): st[1]}
    if time_min and min_profit_pct is not None:
        plan["time_stop_min"], plan["min_profit_pct"] = float(time_min), float(min_profit_pct)
    elif time_min:
        plan["time_stop"] = {"after_min": float(time_min), "if_pnl_below_pct": 1000}
    return plan


def describe(plan):
    """A stored (normalized) plan in one line: "TP1 +15 % pola · trailing 8 % · SL −10 % · time stop 45 min"."""
    if not plan:
        return ""
    share = {1.0: "sve", 0.5: "pola"}
    bits = []
    for i, tp in enumerate(plan.get("take_profits") or []):
        lvl = pct_words(tp["v"]) if tp["kind"] == "pct" else f"MC {mc_words(tp['v'])}"
        sh = share.get(round(tp["sell_share"], 4)) or pct_words(tp["sell_share"] * 100, sign=False)
        bits.append(f"TP{i + 1} {lvl} {sh}")
    tr = plan.get("trailing")
    if tr:
        bits.append(f"trailing {pct_words(tr['trail_pct'], sign=False)}")
    st = plan.get("stop")
    if st:
        bits.append(f"SL {pct_words(st['v']) if st['kind'] == 'pct' else 'MC ' + mc_words(st['v'])}")
    t = plan.get("time_stop")
    if t:
        cond = "" if (t.get("if_pnl_below_pct") or 0) >= 1000 else f" ako je ispod {pct_words(t['if_pnl_below_pct'])}"
        bits.append(f"time stop {t['after_min']:g} min{cond}")
    if plan.get("time_stop_min"):   # 12.11.
        bits.append(f"time stop {plan['time_stop_min']:g} min ako je ispod "
                    f"{pct_words(plan.get('min_profit_pct') or 0.0)} neto")
    if plan.get("max_stop_pct"):
        bits.append(f"SL najviše {pct_words(-plan['max_stop_pct'])}")
    if plan.get("breakeven_after_tp1"):   # 13.11. (owner's order point 4)
        buf = plan.get("breakeven_buffer_pct")
        bits.append("nakon TP1 stop na break-even ("
                    + (f"ulaz {pct_words(buf)}" if buf is not None else "ulaz + trošak") + ")")
    return " · ".join(bits)


def denorm(plan, stop_only=False):
    """A stored (normalized) plan back in set_plan's input format (to check it again on a changed position)."""
    def lvl(d):
        return {("at_pct" if d["kind"] == "pct" else "at_mc_usd"): d["v"]}
    out = {"reason": plan.get("reason") or ""}
    if plan.get("accounts"):
        out["accounts"] = list(plan["accounts"])
    if plan.get("stop"):
        out["stop"] = lvl(plan["stop"])
    if plan.get("max_stop_pct"):   # 12.11.: a stop limit, checked again with the stop
        out["max_stop_pct"] = plan["max_stop_pct"]
    if not stop_only:
        if plan.get("take_profits"):
            out["take_profits"] = [dict(lvl(t), sell_share=t["sell_share"]) for t in plan["take_profits"]]
        for k in ("trailing", "time_stop", "panel"):
            if plan.get(k):
                out[k] = dict(plan[k])
        if plan.get("time_stop_min"):
            out["time_stop_min"] = plan["time_stop_min"]
            out["min_profit_pct"] = plan.get("min_profit_pct") or 0.0
        if plan.get("breakeven_after_tp1"):   # 13.11.
            out["breakeven_after_tp1"] = True
            if plan.get("breakeven_buffer_pct") is not None:
                out["breakeven_buffer_pct"] = plan["breakeven_buffer_pct"]
    return out


def position_fields(plan, rule=None):
    """{"tp", "sl", "trail", "time"}: the exit an open position has, as the panel's fields (the Autopilot panel shows
    them for a selected position, and a DCA compares what it carries with them): a panel plan's fields as typed, else
    the lots' own TP / SL (league auto "tpsl", the group exit's text first) with the plan's trailing / time stop."""
    if plan and isinstance(plan.get("plan", {}).get("panel"), dict):
        return dict(plan["plan"]["panel"])
    rule = rule or {}
    tp = sl = ""
    if rule.get("mode") == "tpsl":
        g = rule.get("grp") or {}
        tp = g.get("tp") or rule.get("tp_in") or rule.get("tp") or ""
        sl = g.get("sl") or rule.get("sl_in") or rule.get("sl") or ""
    pl = (plan or {}).get("plan") or {}
    t = pl.get("time_stop") or {}
    return {"tp": tp, "sl": sl, "trail": (pl.get("trailing") or {}).get("trail_pct"),
            "time": t.get("after_min") if (t.get("if_pnl_below_pct") or 0) >= 1000 else None}


def _norm_lvl(text, kind, floor=None):
    """A TP / SL text in one form for comparing ("30" = "+30%" = "30 %"; an empty SL = the default -floor)."""
    try:
        lv = level_of(text, kind)
    except ValueError:
        return (text or "").strip().lower()
    if lv is None and kind == "sl" and floor:
        lv = ("pct", -abs(float(floor)))
    return (lv[0], round(lv[1], 6)) if lv else None


def same_exit(a, b, floor=None):
    """True when two sets of exit fields {"tp", "sl", "trail", "time"} mean the same exit."""
    a, b = a or {}, b or {}

    def n(x):
        try:
            return round(float(x), 6) if x not in (None, "") else None
        except (TypeError, ValueError):
            return x
    return (_norm_lvl(a.get("tp"), "tp") == _norm_lvl(b.get("tp"), "tp")
            and _norm_lvl(a.get("sl"), "sl", floor) == _norm_lvl(b.get("sl"), "sl", floor)
            and n(a.get("trail")) == n(b.get("trail")) and n(a.get("time")) == n(b.get("time")))


def extend(con, token, floor, client=None):
    """A DCA / one more lot without new exit fields (11.11., owner: "postojeći plan pokriva i novi lot"): the active
    plan stays with its state (fired take profits, peaks); its stop is measured again from the NEW average entry (a
    percent stop is "from the average entry"; a stop the plan derived = never looser than -floor from it; a market cap
    stop stays). client: the plan becomes a panel plan (it was live before the owner's lot and must stay so). Returns
    the plan or None."""
    p = active(con, token)
    if not p:
        return None
    st = p["state"]
    for u in _scope(p["plan"]):
        lots = _lots(con, u, token)
        if not lots:
            continue
        avg = _avg(lots)
        if not avg:
            continue
        s = p["plan"].get("stop")
        if s and s["kind"] == "pct":
            st["stop_px"][u] = avg * (1 + s["v"] / 100)
        elif not s:
            st["stop_px"][u] = max(st["stop_px"].get(u) or 0, avg * (1 - floor / 100))
            if p["plan"].get("max_stop_pct"):   # 12.11.: the plan's own stop never wider than -max_stop_pct
                st["stop_px"][u] = max(st["stop_px"][u], avg * (1 - p["plan"]["max_stop_pct"] / 100))
        be = (st.get("be") or {}).get(u)
        if be:   # 13.11.: after TP1 the break-even holds, measured from the NEW average entry
            be["px"] = avg * (1 + (be.get("buf_pct") or 0) / 100)
            st["stop_px"][u] = max(st["stop_px"].get(u) or 0, be["px"])
        st.setdefault("base_qty", {})[u] = sum(t["qty"] or 0 for t in lots)
    _save_state(con, p["id"], st)
    if client:
        con.execute("UPDATE exit_plans SET client=? WHERE id=?", (client, p["id"]))
        con.commit()
        p["client"] = client
    return p


def status(con, token, pos_live=True, autopilot_live=True, user=None, plan=None, lots=None, ro=False):
    """{"plan_mode": live | paper | shadow, "reason", "summary", "plan_id", "client"} of a position's exit plan on the
    real account (11.11., owner: "U kartici pozicije jasno prikaži 'plan aktivan (live)' ili 'samo paper'"):
      live    the plan is in force and sells on the real account (exit_plan_live for a panel plan / a Grok position,
              or exit_plans live), the position is a real one and the Autopilot is live;
      shadow  a plan exists but the real account only logs it (no plan from the panel, the default TP/SL holds);
      paper   everything else, with the reason (a demo position, the Autopilot not live, the plans paused,
              exit_plan_live not live, no plan)."""
    from trade import settings as ts
    from . import flags
    user = user or ts.LEAGUE_USER
    if plan is None:
        plan = active(con, token, ro=ro)
    if plan and user not in _scope(plan["plan"]):
        plan = None
    out = {"plan_id": plan["id"] if plan else None, "client": plan["client"] if plan else None,
           "summary": describe(plan["plan"]) if plan else ""}

    def r(mode, why):
        out.update(plan_mode=mode, reason=why)
        return out
    if not pos_live:
        return r("paper", "pozicija je demo (paper): bez pravog novca")
    if not autopilot_live:
        return r("paper", "Autopilot nije live: pravi novac se ne kreće")
    if paused():
        return r("paper", "planovi izlaza su pauzirani (kill switch): vrijedi TP/SL pozicije")
    m = flags.mode("exit_plans")
    if m != "live" and flags.mode(LIVE_FLAG) != "live":
        return r("paper", "exit_plan_live nije live: plan se na pravom računu ne izvršava")
    if not plan:
        return r("paper", "pozicija nema plan izlaza iz panela: vrijedi njen TP/SL (plan postavlja kupnja s izlazom "
                          "ili Spremi SL/TP)")
    lots = lots if lots is not None else _lots(con, user, token)
    ex = execution(user, lots, m, plan=plan)
    if ex["executes"] and ex["real_account"]:
        return r("live", ex["why"])
    return r("shadow", "plan u sjeni: pozicija je bez plana iz panela (vrijedi njen TP/SL; Spremi SL/TP ga čini živim)")
