"""11.11. (Jure: "DA, alarm za otvorene pozicije na njihov vlastiti SL, TP i trailing (i DCA naloge), neovisno o
rasponu"): the open positions of the REAL account as zonewatch sees them, and their own exit / buy levels. Grok only
advises from these alarms; nothing here trades.

A position = every open lot of one token on the real Autopilot account (league.db trades, user trade.settings
.LEAGUE_USER, status open): manual buys (ručno), Grok autotrade (Grok auto), MCP requests the owner approved
(odobreno), copies and the rest alike. The demo account (PAPER_USER) is not alarmed: the owner asked for his
positions.

    load()      one dict per token: lots, qty, qty-weighted average entry (price and MC), size, sources, the exit plan
                (league/exitplan: in force or not), the real positions' sol_in (trade.db positions by league_id) and the
                levels, each in the unit its executor compares (basis price | mcap):
          sl        a stop: the lots' own TP/SL stop (auto tpsl sl_px; lots with the same stop are one level), Smart
                    sell's stop and its lock after a take profit (auto_state of paper/sim), the open range round's hard
                    stop; trailing=True for Smart sell's trailing stop once it trails and the plan's trailing once it
                    is active (they move with the peak)
          tp        the lots' tp_px, Smart sell's next take profit, the plan's take profits not fired yet
          dca       the owner's DCA orders (trade settings dca_orders, level in MC) and the buy orders (buy_orders) of a
                    token already held
                While an exit plan is IN FORCE for the account (exitplan.in_force_tokens) its stop, take profits and
                trailing replace the lots' own sl / tp (the plan wins, as in league/auto.fast_once); a plan that is not
                in force (shadow) does not sell, so its levels are not watched.
    changes()   what the executors did since the last pass: an executed level sells within a second (league/auto
                .fast_once, exitplan.run_once, ui/pravitrade.dca_once), before a 30 s pass can see the price there, so
                the hits also come from the executors' own records: exit_events of a plan (mode izvršeno), lots closed
                with exit_rule sl / tp / smart_*, a Smart sell take profit (tp_done up), dca_log / buy_log
    pnl()       PnL % from the average entry, USD (qty x price + realized - size, before fees), SOL (the real
                positions' sol_in when the lot maps, else the USD at the SOL price the equity snapshots stored)
Read-only on league.db and trade.db; no network (prices come from zonewatch/prices.py).
"""
import json
import os
import re
import sqlite3

SAME = 1e-6   # two lots' levels closer than this (relative) are one level
SL_NAMES = ("sl", "smart_sl", "smart_lock", "smart_trail", "range_stop", "plan_stop", "plan_trailing")
# league exit_rule of a closed lot -> (level, the level names it can be, most likely first)
CLOSE_RULES = {"sl": ("sl_hit", ("sl", "range_stop")), "tp": ("tp_hit", ("tp",)),
               "smart_sl": ("sl_hit", ("smart_lock", "smart_sl")), "smart_trail": ("sl_hit", ("smart_trail", "smart_lock")),
               "smart_tp": ("tp_hit", ("smart_tp",))}
PLAN_TRIG = {"stop": ("sl_hit", "plan_stop"), "trailing": ("sl_hit", "plan_trailing")}
_MC_RE = re.compile(r"na MC \$([\d,.]+)")
_LVL_RE = re.compile(r"(?:granica|razina) \$([\d,.]+)")


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def league_path():
    from league import store as lstore
    return lstore.DB


def trade_path():
    from trade import settings
    return settings.DB


def real_user():
    from trade import settings
    return settings.LEAGUE_USER


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _js(x, default=None):
    if isinstance(x, (dict, list)):
        return x
    try:
        v = json.loads(x) if x else None
    except (TypeError, ValueError):
        v = None
    return default if v is None else v


def source_label(src):
    """ručno | Grok auto | odobreno | kopija | range | momentum | DCA | the source itself (short)."""
    s = (src or "").strip()
    try:
        from league import exitplan
        approved = exitplan.APPROVED_SRC
    except Exception:  # noqa: BLE001
        approved = "ručno: Grok odobreno (MCP)"
    if s == approved or "Grok odobreno" in s:
        return "odobreno"
    if s.startswith("Grok auto"):
        return "Grok auto"
    if s.startswith("ručno"):
        return "ručno"
    if s.startswith("copy") or s.startswith("kopija"):
        return "kopija"
    for p, lab in (("range", "range"), ("momentum", "momentum"), ("DCA", "DCA"), ("paper", "demo strategija")):
        if s.startswith(p):
            return lab
    return s[:40] or "nepoznato"


# ---------- reading ------------------------------------------------------------------------------------------------

def _settings(tcon, keys):
    out = {}
    if tcon is None:
        return out
    try:
        for k, v in tcon.execute(f"SELECT k, v FROM settings WHERE k IN ({','.join('?' * len(keys))})", keys):
            out[k] = _js(v)
    except sqlite3.Error:
        pass
    return out


def _sol_usd(tcon):
    """The SOL price the newest equity snapshot stored (no network)."""
    if tcon is None:
        return None
    try:
        r = tcon.execute("SELECT sol_usd FROM (SELECT sol_usd, ts FROM equity ORDER BY ts DESC LIMIT 500) WHERE sol_usd "
                         "IS NOT NULL ORDER BY ts DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    return _f(r[0]) if r else None


def _real_sol(tcon, lot_ids):
    """{league lot id: SOL still in it} of the open real positions (trade.db positions.league_id: sol_in x the share
    of qty_raw still held)."""
    if tcon is None or not lot_ids:
        return {}
    ids = sorted(lot_ids)
    try:
        rows = tcon.execute(f"SELECT league_id, sol_in, qty_raw, qty_left FROM positions WHERE status='open' AND league_id "
                            f"IN ({','.join('?' * len(ids))})", ids).fetchall()
    except sqlite3.Error:
        return {}
    out = {}
    for lid, sol_in, raw, left in rows:
        if lid is None or not sol_in:
            continue
        share = (left / raw) if raw and left is not None and raw > 0 else 1.0
        out[int(lid)] = out.get(int(lid), 0.0) + float(sol_in) * share
    return out


def _plans(lcon, user):
    """{token: {"id", "plan", "state", "in_force"}} of the active exit plans that apply to the account."""
    try:
        from league import exitplan
    except Exception:  # noqa: BLE001
        return {}
    try:
        rows = lcon.execute("SELECT id, token, plan, state FROM exit_plans WHERE status='active' ORDER BY id").fetchall()
    except sqlite3.Error:
        return {}
    if not rows:
        return {}
    try:
        force = exitplan.in_force_tokens(lcon, user)
    except Exception:  # noqa: BLE001 - unreadable: no plan counts as in force (the lots' own levels are watched)
        force = set()
    out = {}
    for pid, tok, pl, st in rows:
        plan = _js(pl, {})
        if user not in exitplan._scope(plan):
            continue
        out[tok] = {"id": pid, "plan": plan, "state": _js(st, {}), "in_force": tok in force}
    return out


def _range_stops(lcon, user):
    try:
        rows = lcon.execute("SELECT token, levels FROM range_rounds WHERE status='open' AND user=?", (user,)).fetchall()
    except sqlite3.Error:
        return {}
    return {t: _f((_js(lv, {}) or {}).get("stop_px")) for t, lv in rows if t}


# ---------- the levels ---------------------------------------------------------------------------------------------

def _lv(kind, name, src, basis, value, ratio, lots=(), key=None, trailing=False, **extra):
    price = value if basis == "price" else (value / ratio if ratio else None)
    mcap = value if basis == "mcap" else (value * ratio if ratio else None)
    d = {"key": key or name, "kind": kind, "name": name, "src": src, "basis": basis, "trailing": bool(trailing),
         "price": price, "mcap": round(mcap, 2) if mcap else None, "lots": sorted(lots)}
    d.update(extra)
    return d


def _smart(t):
    """[(kind, name, price, trailing, step)] of a Smart sell lot from its auto_state (paper/sim position and config);
    [] before the first auto sell pass stored the state."""
    st = _js(t.get("auto_state"), {}) or {}
    pos, cfg = st.get("pos") or {}, st.get("cfg") or {}
    entry = _f(pos.get("entry_px"))
    if not entry or not pos.get("open", True) or pos.get("bag"):
        return []
    try:
        from paper import sim
        done = int(pos.get("tp_done") or 0)
        peak = float(pos.get("peak") or 0.0)
    except Exception:  # noqa: BLE001 - a state this code does not know: no Smart levels, never a broken pass
        return []

    def stop():
        return entry * (1 + float(cfg["sl"])) if done == 0 and _f(cfg.get("sl")) is not None else None

    def lock():
        a = sim.after_tp_stop(pos, cfg)
        return entry * (1 + a) if a is not None else None

    def trail():
        tr = sim.trail_for(peak, cfg)
        return entry * (1 + peak) * (1 - tr) if tr is not None else None

    def target():
        tps = cfg.get("tp") or []
        return entry * (1 + float(tps[done][0])) if done < len(tps) else None
    out = []
    for kind, name, fn, trailing in (("sl", "smart_sl", stop, False), ("sl", "smart_lock", lock, False),
                                     ("sl", "smart_trail", trail, True), ("tp", "smart_tp", target, False)):
        try:   # each on its own: a config without one of the keys loses only that level
            px = fn()
        except Exception:  # noqa: BLE001
            px = None
        if px:
            out.append((kind, name, px, trailing, done))
    return out


def _group(levels):
    """Lots with the same level (kind, name, value within SAME) are one level; its key is name:<lowest lot id>."""
    out = []
    for lv in levels:
        v = lv["price"] if lv["basis"] == "price" else lv["mcap"]
        for o in out:
            ov = o["price"] if o["basis"] == "price" else o["mcap"]
            if o["name"] == lv["name"] and v and ov and abs(v - ov) <= SAME * max(v, ov):
                o["lots"] = sorted(set(o["lots"]) | set(lv["lots"]))
                break
        else:
            out.append(dict(lv))
    for o in out:
        if o["lots"] and o["key"] == o["name"]:
            o["key"] = f"{o['name']}:{o['lots'][0]}"
    return out


def levels_of(lots, ratio, avg, plan=None, range_stop=None, dca=(), buys=(), user=None, now=None):
    """The levels of one position (see the module text)."""
    out = []
    if plan and plan.get("in_force"):
        st, pl = plan.get("state") or {}, plan.get("plan") or {}
        stop = _f((st.get("stop_px") or {}).get(user))
        if stop:
            out.append(_lv("sl", "plan_stop", "plan", "price", stop, ratio))
        fired = set((st.get("fired") or {}).get(user) or [])
        for i, tp in enumerate(pl.get("take_profits") or []):
            if i in fired:
                continue
            try:
                from league import exitplan
                px = exitplan._px(tp["kind"], tp["v"], avg, ratio)
            except Exception:  # noqa: BLE001 - an MC target without a known supply
                continue
            out.append(_lv("tp", f"plan_tp{i + 1}", "plan", "price", px, ratio, share=tp.get("sell_share")))
        tr, tpk = pl.get("trailing"), _f((st.get("trail_peak_px") or {}).get(user))
        if tr and tpk:
            out.append(_lv("sl", "plan_trailing", "plan", "price", tpk * (1 - float(tr["trail_pct"]) / 100), ratio,
                           trailing=True, trail_pct=tr["trail_pct"]))
    else:
        own = []
        for t in lots:
            a = _js(t.get("auto"), {}) or {}
            if a.get("mode") == "tpsl":
                if _f(a.get("sl_px")):
                    own.append(_lv("sl", "sl", "auto", "price", float(a["sl_px"]), ratio, [t["id"]], text=a.get("sl")))
                if _f(a.get("tp_px")):
                    own.append(_lv("tp", "tp", "auto", "price", float(a["tp_px"]), ratio, [t["id"]], text=a.get("tp")))
            elif a.get("mode") == "smart":
                for kind, name, px, trailing, step in _smart(t):
                    own.append(_lv(kind, name, "smart", "price", px, ratio, [t["id"]], trailing=trailing, step=step))
        out += _group(own)
        if range_stop:
            out.append(_lv("sl", "range_stop", "range", "price", range_stop, ratio))
    for o in dca:
        if _f(o.get("mc")):
            out.append(_lv("dca", "dca", "dca_orders", "mcap", float(o["mc"]), ratio, key=f"dca:{o.get('id')}",
                           sol=o.get("sol"), order_id=o.get("id"), text=o.get("txt")))
    for o in buys:
        if _f(o.get("mc")) and (now is None or (o.get("until") or 0) > now):
            out.append(_lv("dca", "buy_order", "buy_orders", "mcap", float(o["mc"]), ratio, key=f"buy:{o.get('id')}",
                           sol=o.get("sol"), order_id=o.get("id")))
    return out


def load(now, user=None, lpath=None, tpath=None):
    """[position dict] of the real account (see the module text), None when league.db cannot be read (then the job
    changes no state)."""
    user = user or real_user()
    path = lpath or league_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return []   # no league.db: nothing held
    lcon = _ro(path)
    if lcon is None:
        return None
    try:
        try:
            rows = [dict(r) for r in lcon.execute("SELECT * FROM trades WHERE user=? AND status='open' ORDER BY id",
                                                  (user,))]
        except sqlite3.Error:
            return None
        if not rows:
            return []
        plans = _plans(lcon, user)
        rstops = _range_stops(lcon, user)
    finally:
        lcon.close()
    tcon = _ro(tpath or trade_path())
    try:
        s = _settings(tcon, ["dca_orders", "buy_orders"])
        sol = _real_sol(tcon, {r["id"] for r in rows})
        sol_usd = _sol_usd(tcon)
    finally:
        if tcon is not None:
            tcon.close()
    by = {}
    for r in rows:
        if r.get("token"):
            by.setdefault(r["token"], []).append(r)
    out = []
    for tok, lots in by.items():
        qty = sum(_f(t.get("qty")) or 0 for t in lots)
        avg = sum((_f(t.get("entry_px")) or 0) * (_f(t.get("qty")) or 0) for t in lots) / qty if qty else None
        ratio = next((t["entry_mcap"] / t["entry_px"] for t in lots if _f(t.get("entry_mcap")) and _f(t.get("entry_px"))),
                     None)
        mq = [(t["entry_mcap"], _f(t.get("qty")) or 0) for t in lots if _f(t.get("entry_mcap"))]
        avg_mc = (sum(m * q for m, q in mq) / sum(q for _, q in mq)) if mq and sum(q for _, q in mq) else \
            (avg * ratio if avg and ratio else None)
        plan = plans.get(tok)
        p = {"mint": tok, "symbol": next((t["symbol"] for t in lots if t.get("symbol")), None), "account": user,
             "lots": [t["id"] for t in lots], "qty": qty, "avg_entry_price": avg,
             "avg_entry_mcap": round(avg_mc, 2) if avg_mc else None, "ratio": ratio,
             "size_usd": round(sum(_f(t.get("size_usd")) or 0 for t in lots), 4),
             "sources": sorted({source_label(t.get("source")) for t in lots}),
             "plan_id": plan["id"] if plan else None, "plan_in_force": bool(plan and plan["in_force"]),
             "opened_ts": min(t.get("opened_ts") or 0 for t in lots),
             "_lots": [{"id": t["id"], "qty": _f(t.get("qty")) or 0, "entry_px": _f(t.get("entry_px")),
                        "size_usd": _f(t.get("size_usd")) or 0, "realized": _f(t.get("realized")) or 0} for t in lots],
             "_sol": {k: v for k, v in sol.items() if k in {t["id"] for t in lots}}, "_sol_usd": sol_usd,
             "_tp_done": {t["id"]: int((((_js(t.get("auto_state"), {}) or {}).get("pos") or {}).get("tp_done") or 0))
                          for t in lots if (_js(t.get("auto"), {}) or {}).get("mode") == "smart"}}
        p["levels"] = levels_of(lots, ratio, avg, plan, rstops.get(tok),
                                [o for o in s.get("dca_orders") or [] if isinstance(o, dict) and o.get("token") == tok],
                                [o for o in s.get("buy_orders") or [] if isinstance(o, dict) and o.get("token") == tok],
                                user, now)
        out.append(p)
    return out


def price_mcap(p, snap):
    """(price, mcap) of a snapshot, the missing one from the position's MC per unit of price."""
    price, mcap = _f((snap or {}).get("price")), _f((snap or {}).get("mcap"))
    r = p.get("ratio")
    if not price and mcap and r:
        price = mcap / r
    if not mcap and price and r:
        mcap = price * r
    return price, mcap


def distance_pct(lv, price, mcap):
    """How far the level is from the price now, in % of the price (negative: the level is below it), in the level's
    own unit (basis); None without both numbers."""
    basis = lv.get("basis") or "price"
    ref = lv.get("price") if basis == "price" else lv.get("mcap")
    val = price if basis == "price" else mcap
    return round((ref / val - 1) * 100, 2) if ref and val else None


def pnl(p, price):
    """{pnl_pct, pnl_usd, pnl_sol, pnl_sol_src} at this price (None where it cannot be told)."""
    out = {"pnl_pct": None, "pnl_usd": None, "pnl_sol": None, "pnl_sol_src": None}
    if not price or price <= 0:
        return out
    avg = p.get("avg_entry_price")
    if avg:
        out["pnl_pct"] = round((price / avg - 1) * 100, 2)
    usd, sol, srcs, known = 0.0, 0.0, set(), True
    lots = p.get("_lots") or []
    if not lots or any(not t.get("qty") for t in lots):
        return out   # a lot without its quantity: no money figure rather than a wrong one
    for t in lots:
        u = t["qty"] * price + t["realized"] - t["size_usd"]
        usd += u
        sm = p.get("_sol") or {}
        sin = sm.get(t["id"]) or sm.get(str(t["id"]))   # str keys after the kv round trip
        if sin and t.get("entry_px"):
            sol += sin * (price / t["entry_px"] - 1)
            srcs.add("sol_in")
        elif p.get("_sol_usd"):
            sol += u / p["_sol_usd"]
            srcs.add("qty×cijena")
        else:
            known = False
    out["pnl_usd"] = round(usd, 2)
    if known and srcs:
        out["pnl_sol"] = round(sol, 4)
        out["pnl_sol_src"] = srcs.pop() if len(srcs) == 1 else "mješovito"
    return out


def block(p, price):
    """The position part of an alarm."""
    b = {"lots": len(p.get("lots") or []), "lot_ids": list(p.get("lots") or []), "qty": p.get("qty"),
         "avg_entry_price": p.get("avg_entry_price"), "avg_entry_mcap": p.get("avg_entry_mcap"),
         "size_usd": p.get("size_usd"), "sources": p.get("sources"), "account": p.get("account"),
         "plan_id": p.get("plan_id"), "plan_in_force": p.get("plan_in_force"), "opened_ts": p.get("opened_ts")}
    b.update(pnl(p, price))
    return b


def plan_zones(pos):
    """{mint: [zone-like dicts in MC]} of the positions' levels, for prices.plan (the fast poll near a level)."""
    out = {}
    for p in pos or []:
        zs = out.setdefault(p["mint"], [])
        for lv in p["levels"]:
            if not lv.get("mcap"):
                continue
            zt = "top" if lv["kind"] == "tp" else "stop"
            zs.append({"mint": p["mint"], "zone_type": zt, "lo": lv["mcap"], "hi": lv["mcap"], "source": "position"})
    return out


def compact(pos):
    """What the next pass needs of this one (zonewatch.db kv pos_prev): per mint the lots, the levels, the position
    block's fixed part and Smart sell's tp_done per lot."""
    out = {}
    for p in pos or []:
        out[p["mint"]] = {"symbol": p.get("symbol"), "lots": p["lots"], "ratio": p.get("ratio"),
                          "levels": {lv["key"]: {k: lv.get(k) for k in ("kind", "name", "src", "basis", "price", "mcap",
                                                                         "lots", "trailing", "step", "order_id")}
                                     for lv in p["levels"]},
                          "pos": {k: p.get(k) for k in ("account", "lots", "qty", "avg_entry_price", "avg_entry_mcap",
                                                        "size_usd", "sources", "plan_id", "plan_in_force", "opened_ts",
                                                        "ratio", "_lots", "_sol", "_sol_usd")},
                          "tp_done": {str(k): v for k, v in (p.get("_tp_done") or {}).items()}}
    return out


# ---------- what the executors did ---------------------------------------------------------------------------------

def _maxes(lcon, tcon):
    wm = {"ev": 0, "dca": 0, "buy": 0}
    if lcon is not None:
        try:
            wm["ev"] = int(lcon.execute("SELECT COALESCE(MAX(id), 0) FROM exit_events").fetchone()[0] or 0)
        except sqlite3.Error:
            pass
    s = _settings(tcon, ["dca_log", "buy_log"])
    for k, lk in (("dca", "dca_log"), ("buy", "buy_log")):
        wm[k] = max([int(x.get("ts") or 0) for x in s.get(lk) or [] if isinstance(x, dict)] + [0])
    return wm


def _match(prev_lv, names, lots):
    """The previous level's key among `names` whose lots overlap `lots`, else None."""
    for n in names:
        for k, lv in prev_lv.items():
            if lv.get("name") == n and (not lv.get("lots") or set(lv["lots"]) & set(lots)):
                return k
    return None


def _num_text(x):
    try:
        return float(x.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def changes(prev, pos, wm, now, user=None, lpath=None, tpath=None):
    """[fill dict] of what the executors did since the last pass on the positions held then, and the new watermark.
    A fill: {mint, level (sl_hit | tp_hit | dca_hit), key (the previous pass's level), name, ts, price, mcap, ok,
    text, lots}. Without a watermark (first pass): only the watermark."""
    user = user or real_user()
    prev = prev or {}
    lcon = _ro(lpath or league_path())
    tcon = _ro(tpath or trade_path())
    out = []
    try:
        cur = _maxes(lcon, tcon)
        if not wm:
            return [], cur
        now_lots = {lid for p in pos or [] for lid in p["lots"]}
        held = {p["mint"]: p for p in pos or []}
        # 1. an exit plan's executions (league/exitplan: exit_events, mode izvršeno on this account)
        if lcon is not None and prev:
            try:
                rows = lcon.execute("SELECT id, ts, token, trigger, price, mcap, share FROM exit_events WHERE id > ? AND "
                                    "user=? AND mode='izvršeno' ORDER BY id", (int(wm.get("ev") or 0), user)).fetchall()
            except sqlite3.Error:
                rows = []
            for eid, ts, tok, trig, px, mc, share in rows:
                if tok not in prev:
                    continue
                if trig in PLAN_TRIG:
                    level, name = PLAN_TRIG[trig]
                elif (trig or "").startswith("tp"):
                    level, name = "tp_hit", f"plan_{trig}"
                else:   # time_stop: no level of its own
                    continue
                out.append({"mint": tok, "level": level, "name": name, "key": name, "ts": ts, "price": px, "mcap": mc,
                            "ok": True, "text": f"plan izlaza: {trig}, prodano {float(share or 0):.0%} pozicije",
                            "lots": [], "src": "plan"})
        # 2. lots watched last pass and closed since by their own stop / target (league/auto)
        gone = sorted({lid for m in prev.values() for lid in m.get("lots") or []} - now_lots)
        if lcon is not None and gone:
            try:
                rows = lcon.execute(f"SELECT id, token, closed_ts, exit_px, exit_mcap, exit_rule, note FROM trades WHERE "
                                    f"user=? AND status='closed' AND id IN ({','.join('?' * len(gone))})",
                                    (user, *gone)).fetchall()
            except sqlite3.Error:
                rows = []
            grp = {}
            for lid, tok, ts, px, mc, rule, note in rows:
                if rule not in CLOSE_RULES or (note or "").startswith("plan izlaza") or tok not in prev:
                    continue
                level, names = CLOSE_RULES[rule]
                if rule == "sl" and (note or "").startswith("range"):
                    names = ("range_stop", "sl")
                key = _match(prev[tok].get("levels") or {}, names, [lid]) or f"{names[0]}:{lid}"
                g = grp.setdefault((tok, key), {"mint": tok, "level": level, "key": key, "ts": ts, "price": px,
                                                "mcap": mc, "ok": True, "text": note, "lots": [], "src": "lot",
                                                "name": (prev[tok].get("levels") or {}).get(key, {}).get("name") or names[0]})
                g["lots"].append(lid)
                g["ts"] = max(g["ts"] or 0, ts or 0)
            out += list(grp.values())
        # 3. a Smart sell take profit sells a part and the lot stays open: its tp_done went up
        for tok, m in prev.items():
            p = held.get(tok)
            if not p:
                continue
            for lid, done in (p.get("_tp_done") or {}).items():
                was = (m.get("tp_done") or {}).get(str(lid))
                if was is not None and done > int(was):
                    key = _match(m.get("levels") or {}, ("smart_tp",), [lid]) or f"smart_tp:{lid}"
                    out.append({"mint": tok, "level": "tp_hit", "name": "smart_tp", "key": key, "ts": now, "price": None,
                                "mcap": None, "ok": True, "text": f"Smart sell: take profit {int(was) + 1}",
                                "lots": [lid], "src": "smart"})
        # 4. the owner's DCA orders and buy orders of a held token (ui/pravitrade dca_log / buy_log)
        s = _settings(tcon, ["dca_log", "buy_log"])
        for wk, lk, name in (("dca", "dca_log", "dca"), ("buy", "buy_log", "buy_order")):
            for x in reversed([x for x in s.get(lk) or [] if isinstance(x, dict)]):
                tok, ts, text = x.get("token"), int(x.get("ts") or 0), str(x.get("text") or "")
                if ts <= int(wm.get(wk) or 0) or tok not in prev:
                    continue
                mc_m, lvl_m = _MC_RE.search(text), _LVL_RE.search(text)
                if not mc_m:   # closed position, expired order, fell straight through: no level was hit
                    continue
                mc, lvl = _num_text(mc_m.group(1)), _num_text(lvl_m.group(1)) if lvl_m else None
                cand = {k: lv for k, lv in (prev[tok].get("levels") or {}).items() if lv.get("name") == name}
                key = None
                if cand:
                    ref = lvl or mc
                    key = min(cand, key=lambda k: abs((cand[k].get("mcap") or 0) - (ref or 0)))
                ratio = prev[tok].get("ratio")
                out.append({"mint": tok, "level": "dca_hit", "name": name, "key": key or f"{name}:mc{int(lvl or mc or 0)}",
                            "ts": ts, "price": (mc / ratio) if mc and ratio else None, "mcap": mc,
                            "ok": "nije prošl" not in text, "text": text, "lots": [], "src": lk, "level_mcap": lvl})
    finally:
        for c in (lcon, tcon):
            if c is not None:
                c.close()
    return out, {k: max(int(wm.get(k) or 0), int(cur.get(k) or 0)) for k in cur}
