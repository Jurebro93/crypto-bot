"""One pass of the zone watch (run_zonewatch.py loop, every EVERY_S = 30 s, low priority). Flag zonewatch off: the
pass reads the flag and ends (nothing watched, nothing fetched, nothing posted).

    1. once: the old fixed HOPE seed expired and the hand-armed zones cut to 2 h (store.migrate_once; never a seed
       again); the range engine's active ranges -> zones (source range) when range.db has a newer computation or
       every 5 min, for the tokens with an open range round, an entry-ready range or an open position on the real
       account, and only while rangedca has an active range for them (store.sync_range); each newer computation is
       a new zone_version
    2. the numbers of every token with a zone (prices.py: stored snapshots first, one DexScreener batch for the near
       / armed ones, inside the day cap)
    3. every zone's state (zones.step): an event on a crossing; the same mint + zone_type + event at most once in
       30 min (stop_hit: once in 60 s, never held back longer); several sources of the same zone in one pass: one
       alarm; a range zone's alarm carries zone_version, computed_ts and window_h of the range it comes from
    4. each alarm is stored (alerts, status pending) and written to events.db (type zone_alert), then posted
       (notify.deliver); stop_hit first, then the oldest; at most POST_BUDGET_S of posting a pass, the rest waits for
       the next pass (same id); an alarm still pending after PENDING_MAX_S is dropped as expired (a late alarm is noise)
    5. team_catalyst rows of events.db (another module's events) forwarded once each (dedupe by the row id)
    6. one cost line a UTC day: DexScreener requests / cap, POSTs ok / failed, alarms by event
11.11. (Jure, odluke vlasnika): the real account's open positions (zonewatch/positions.py) are priced with the zones
(their levels in the fast poll near a level) and alarm on their OWN levels, with or without a range (event
position_level, level sl_near | sl_hit | tp_hit | dca_hit; evaluate_positions), and a held token whose range rangedca
switches off alarms once (event range_off, with the reason; range_off). The demo account is never alarmed.
"""
import json
import sqlite3
import time

from zonewatch import notify, positions, prices, store, zones

EVERY_S = 30
RANGE_SYNC_S = 300
POST_BUDGET_S = 20
PENDING_MAX_S = 600
PRUNE_EVERY_S = 3600
CATALYST_FIRST_S = 1800   # the first pass forwards team_catalyst rows of the last 30 min, never an old backlog
CATALYST_BATCH = 20
CATALYST_MAX_CHARS = 4000
SRC_ORDER = {"manual": 0, "event": 1, "range": 2}
POS_SRC = "position"      # zone_state rows and alarms of a position's own levels
FILL_DEDUP_S = 900        # an executor's fill of a level alarmed by its crossing within this: no second alarm
PREV_MAX_AGE_S = 900      # what the last pass saw (positions, ranges) older than this (the loop was off): no diffs
RANGE_KEYS = ("break_up", "break_down", "weak_volume", "other")


def _sync_range(con, now, log):
    """store.sync_range when range.db has a newer range computation than the last sync, or every RANGE_SYNC_S."""
    try:
        from rangedca import data
        rc = data.ro()
        newest = None
        if rc is not None:
            try:
                newest = rc.execute("SELECT MAX(ts) FROM ranges WHERE active = 1").fetchone()[0]
            except sqlite3.Error:
                newest = None
            finally:
                rc.close()
        last = store.kv_get(con, "range_sync") or {}
        if newest == last.get("newest") and now - (last.get("ts") or 0) < RANGE_SYNC_S:
            return None
        toks, n = store.sync_range(con, now, log=log)
        store.kv_put(con, "range_sync", {"ts": now, "newest": newest, "tokens": toks})
        con.commit()
        return toks
    except Exception as e:  # noqa: BLE001 - the hand-armed zones are watched without it
        log(f"zonewatch: zone raspona nisu pročitane ({type(e).__name__})")
        return None


def _payload(alert_id, event, z, s, now, extra, rug, uniq):
    mc = s.get("mcap")
    return {"id": alert_id, "event": event, "mint": z["mint"], "symbol": s.get("symbol") or z.get("symbol"),
            "zone_type": z["zone_type"], "zone_lo": z["lo"], "zone_hi": z["hi"],
            "mcap": round(mc) if isinstance(mc, (int, float)) else None, "price": s.get("price"), "liq": s.get("liq"),
            "vol_5m": s.get("vol_m5"), "vol_1h": s.get("vol_h1"), "buys_5m": s.get("buys_m5"),
            "sells_5m": s.get("sells_m5"), "buy_share_5m": notify.share(s.get("buys_m5"), s.get("sells_m5")),
            "buy_share_1h": notify.share(s.get("buys_h1"), s.get("sells_h1")), "uniq_traders_1h": uniq,
            "rug_risk": rug, "source": z["source"], "ts": int(now),
            "direction": extra.get("direction"), "initial": bool(extra.get("initial")), "note": z.get("note"),
            "data_age_s": int(now - (s.get("ts") or now)), "price_source": s.get("src")}


def _last_alert(con, mint, zone_type, event):
    r = con.execute("SELECT MAX(ts) FROM alerts WHERE mint=? AND zone_type=? AND event=?",
                    (mint, zone_type, event)).fetchone()
    return r[0] if r else None


def evaluate(con, zs, snaps, now, rug_fn=None, uniq_fn=None):
    """Step every zone with a fresh enough number; store the states; return the new alerts' payloads (stored as
    pending) and the count of debounced ones. A range zone's alarm carries its range's version (store.versions)."""
    rug_fn = rug_fn or prices.rug_risk
    uniq_fn = uniq_fn or prices.uniq_traders_1h
    st = store.states(con)
    ver = store.versions(con, {z["mint"] for z in zs if z["source"] == "range"})
    fired, seen = [], set()
    for z in sorted(zs, key=lambda z: SRC_ORDER.get(z["source"], 9)):
        s = snaps.get(z["mint"])
        if not s or not s.get("mcap") or not s.get("ts") or now - s["ts"] > prices.STALE_S:
            continue
        key = (z["mint"], z["zone_type"], z["source"])
        prev = st.get(key)
        if prev and prev.get("last_ts") and s["ts"] < prev["last_ts"]:
            continue   # an older number than the one the state already saw
        new, ev, extra = zones.step(z, prev, float(s["mcap"]), s["ts"])
        store.save_state(con, key, new)
        if ev:
            fired.append((z, ev, s, extra))
    out, debounced = [], 0
    for z, ev, s, extra in fired:
        k = (z["mint"], z["zone_type"], ev)
        if k in seen:   # the same zone from another source in this pass: one alarm
            continue
        last = _last_alert(con, *k)
        if last is not None and now - last < zones.debounce_s(ev):
            debounced += 1
            continue
        seen.add(k)
        aid = notify.new_id(z["mint"], z["zone_type"], ev, z["source"], int(now))
        tx5 = (s.get("buys_m5") or 0) + (s.get("sells_m5") or 0)
        p = _payload(aid, ev, z, s, now, extra, rug_fn(z["mint"], s.get("mcap"), s.get("liq")),
                     uniq_fn(z["mint"], now, tx5))
        if z["source"] == "range":
            p.update(ver.get(z["mint"]) or {})
        p = notify.normalize(p, now)
        if notify.record(con, p, "pending", now):
            out.append(p)
    con.commit()
    return out, debounced


# ---------- the real account's positions (11.11., zonewatch/positions.py) -------------------------------------------

def load_positions(now, log=print, **kw):
    """positions.load, None when league.db cannot be read (logged once a UTC day; no position state changes then)."""
    try:
        pos = positions.load(now, **kw)
        why = None if pos is not None else "league.db nije čitljiv"
    except Exception as e:  # noqa: BLE001 - the zones are watched without it
        pos, why = None, type(e).__name__
    if why and _SAID.get("positions") != store.day(now):
        _SAID["positions"] = store.day(now)
        log(f"zonewatch: pozicije pravog računa nisu pročitane ({why}); zone se prate i bez njih")
    return pos


_SAID = {}


def _pos_last(con, mint, key, level):
    r = con.execute("SELECT ts FROM pos_alert WHERE mint=? AND lkey=? AND level=?", (mint, key, level)).fetchone()
    return r[0] if r else None


def _pos_mark(con, mint, key, level, now, alert_id):
    con.execute("INSERT OR REPLACE INTO pos_alert VALUES (?,?,?,?,?)", (mint, key, level, int(now), alert_id))


def _pos_payload(aid, level, lv, p, s, now, extra, rug, uniq, price, mcap, fill=None):
    """The owner's fields (zone_type position_sl | position_tp | position_dca, zone_lo = zone_hi = the level's market
    cap, source position) plus the level and the position."""
    z = {"mint": p["mint"], "symbol": p.get("symbol"), "zone_type": f"position_{lv['kind']}", "lo": lv.get("mcap"),
         "hi": lv.get("mcap"), "source": POS_SRC, "note": (fill or {}).get("text") or lv.get("text")}
    out = _payload(aid, "position_level", z, s or {}, now, extra, rug, uniq)
    if mcap and (fill is not None or out.get("mcap") is None):   # a fill: where the executor sold / bought
        out["mcap"] = round(mcap)
    if price and (fill is not None or out.get("price") is None):
        out["price"] = price
    out.update(level=level, level_key=lv["key"], level_name=lv.get("name"),
               level_kind="trailing" if lv.get("trailing") else lv["kind"], level_src=lv.get("src"),
               level_mcap=lv.get("mcap"), level_price=lv.get("price"), level_basis=lv.get("basis", "price"),
               distance_pct=positions.distance_pct(lv, price, mcap),
               position=positions.block(p, price), filled=fill is not None,
               fill=({k: fill.get(k) for k in ("ts", "price", "mcap", "ok", "text", "lots", "src")} if fill else None))
    return notify.normalize(out, now)


def evaluate_positions(con, pos, snaps, now, rug_fn=None, uniq_fn=None, lpath=None, tpath=None):
    """position_level alarms of the real account's open positions (positions.load: `pos`, None = unreadable, then
    nothing changes): every level steps on the token's newest fresh number (zones.level_zones / level_step; the states
    are zone_state rows of source position), plus what the executors did since the last pass (positions.changes: a
    sale at a stop / target or a DCA buy happens within a second, before a 30 s pass sees the price there).
    Debounce per (token, level key, level) in pos_alert: sl_near 30 min, sl_hit / tp_hit / dca_hit 60 s; a fill whose
    crossing was alarmed in the last FILL_DEDUP_S is not alarmed again. Returns (payloads, debounced)."""
    rug_fn = rug_fn or prices.rug_risk
    uniq_fn = uniq_fn or prices.uniq_traders_1h
    if pos is None:
        return [], 0
    last_pass = store.kv_get(con, "pos_prev") or {}
    fresh = now - int(last_pass.get("ts") or 0) <= PREV_MAX_AGE_S
    prev = (last_pass.get("pos") or {}) if fresh else {}
    try:
        fills, wm = positions.changes(prev, pos, store.kv_get(con, "pos_wm") if fresh else None, now, lpath=lpath,
                                      tpath=tpath)
    except Exception as e:  # noqa: BLE001 - the crossings are still watched
        print(f"zonewatch: zapisi izvršitelja nisu pročitani ({type(e).__name__})", flush=True)
        fills, wm = [], store.kv_get(con, "pos_wm")
    st = {k: v for k, v in store.states(con).items() if k[2] == POS_SRC}
    fired = []
    for p in pos:
        s = snaps.get(p["mint"])
        if not s or not s.get("ts") or now - s["ts"] > prices.STALE_S:
            continue
        price, mcap = positions.price_mcap(p, s)
        for lv in p["levels"]:
            val = price if lv["basis"] == "price" else mcap
            ref = lv["price"] if lv["basis"] == "price" else lv["mcap"]
            if not val or not ref:
                continue
            got = []
            for z, first, level in zones.level_zones(lv["kind"], ref):
                key = (p["mint"], f"pos:{lv['key']}" + (":near" if level == "sl_near" else ""), POS_SRC)
                ps = st.get(key)
                if ps and ps.get("last_ts") and s["ts"] < ps["last_ts"]:
                    continue   # an older number than the one the state already saw
                new, entered, extra = zones.level_step(z, ps, val, s["ts"], first)
                store.save_state(con, key, new)
                if entered:
                    got.append((level, extra))
            for level, extra in got:
                if level == "sl_near" and any(g[0] == "sl_hit" for g in got):
                    continue
                fired.append((p, lv, level, extra, s, price, mcap, None))
    held = {p["mint"]: p for p in pos}
    for f in fills:
        m = f["mint"]
        pv = prev.get(m) or {}
        lv = dict((pv.get("levels") or {}).get(f["key"]) or
                  {"kind": {"sl_hit": "sl", "tp_hit": "tp"}.get(f["level"], "dca"), "name": f.get("name"),
                   "src": f.get("src"), "basis": "mcap" if f["level"] == "dca_hit" else "price", "price": None,
                   "mcap": None, "lots": f.get("lots") or []})
        lv["key"] = f["key"]
        if not lv.get("mcap") and f.get("level_mcap"):
            lv["mcap"] = f["level_mcap"]
        p = held.get(m) or dict(pv.get("pos") or {}, mint=m, symbol=pv.get("symbol"), closed=True)
        s = snaps.get(m) or {}
        price0, mcap0 = positions.price_mcap(p, s)
        price = f.get("price") or (f["mcap"] / p["ratio"] if f.get("mcap") and p.get("ratio") else price0)
        mcap = f.get("mcap") or (price * p["ratio"] if price and p.get("ratio") else mcap0)
        fired.append((p, lv, f["level"], {"initial": False, "direction": None}, s, price, mcap, f))
    out, debounced = [], 0
    for p, lv, level, extra, s, price, mcap, fill in fired:
        last = _pos_last(con, p["mint"], lv["key"], level)
        win = FILL_DEDUP_S if fill is not None else zones.level_debounce_s(level)
        if last is not None and now - last < win:
            debounced += 1
            continue
        aid = notify.new_id(p["mint"], lv["key"], level, "fill" if fill else "cross", int(now))
        tx5 = (s.get("buys_m5") or 0) + (s.get("sells_m5") or 0)
        payload = _pos_payload(aid, level, lv, p, s, now, extra, rug_fn(p["mint"], mcap, s.get("liq")),
                               uniq_fn(p["mint"], now, tx5), price, mcap, fill)
        if notify.record(con, payload, "pending", now):
            _pos_mark(con, p["mint"], lv["key"], level, now, aid)
            out.append(payload)
    mints = sorted(held)
    con.execute(f"DELETE FROM zone_state WHERE source=? AND mint NOT IN ({','.join('?' * len(mints))})",
                (POS_SRC, *mints))   # a token no longer held: its levels' states go (a new position starts afresh)
    store.kv_put(con, "pos_prev", {"ts": int(now), "pos": positions.compact(pos)})
    if wm is not None:
        store.kv_put(con, "pos_wm", wm)
    kinds = {}
    for p in pos:
        for lv in p["levels"]:
            k = "trailing" if lv.get("trailing") else lv["kind"]
            kinds[k] = kinds.get(k, 0) + 1
    store.kv_put(con, "pos_watch", {"ts": int(now), "positions": len(pos), "levels": sum(kinds.values()),
                                    "levels_by_kind": kinds, "plans_in_force": sum(1 for p in pos if p["plan_in_force"]),
                                    "priced": sum(1 for p in pos if (snaps.get(p["mint"]) or {}).get("ts") and
                                                  now - snaps[p["mint"]]["ts"] <= prices.STALE_S)})
    con.commit()
    return out, debounced


def range_reason(why):
    """(key, text) of why a range is off: key break_up | break_down | weak_volume | other, from range.db's status and
    why (store.no_range_why); key None when the range is still active (only no zone at or over 30k)."""
    t = (why or "").strip() or "nema aktivnog raspona"
    w = t.lower()
    if w.startswith("raspon bez zona"):
        return None, t
    if w.startswith("raspon zastario") or w.startswith("range.db") or w.startswith("rangedca nema"):
        return "other", t
    if "probijen gore" in w:
        return "break_up", t
    if "probijen dolje" in w or "niža dna" in w:   # rules.py: a break down, or two lower lows in a row
        return "break_down", t
    if "volumen" in w:   # "slab volumen" (detect) or "isključen: volumen zadnjeg sata pao ..." (rules)
        return "weak_volume", t
    return "other", t


def range_off(con, pos, snaps, now, rug_fn=None, uniq_fn=None, log=print):
    """11.11. (Jure: "kad rangedca isključi raspon tokena s otvorenom pozicijom, JEDAN alarm range_off s razlogom"):
    a held token (real account) whose range zones were in force at the last pass and are gone now (the range sync
    expires them when rangedca's range is no longer active) -> one alarm range_off with the reason (range_reason of
    kv range_why) and the last zone_version / computed_ts / window_h. It re-arms when the range is active again.
    Returns the payloads."""
    rug_fn = rug_fn or prices.rug_risk
    uniq_fn = uniq_fn or prices.uniq_traders_1h
    if pos is None:
        return []
    held = {p["mint"]: p for p in pos}
    on = {r[0] for r in con.execute("SELECT DISTINCT mint FROM armed_zones WHERE source='range' AND expires_at > ?",
                                    (int(now),))}
    ver = store.versions(con)
    last = store.kv_get(con, "range_on_pos") or {}
    was = (last.get("mints") or {}) if now - int(last.get("ts") or 0) <= PREV_MAX_AGE_S else {}
    whys = store.kv_get(con, "range_why") or {}
    keep, out = {}, []
    for m, p in held.items():
        if m in on:
            keep[m] = ver.get(m) or {}
            continue
        if m not in was:
            continue
        why = whys.get(m)
        if why is None:
            try:
                why = store.no_range_why({m}, now).get(m)
            except Exception:  # noqa: BLE001
                why = None
        key, text = range_reason(why)
        if key is None:   # still active, only without a zone over 30k: not off
            keep[m] = was[m]
            continue
        v = {k: (ver.get(m) or {}).get(k) or (was.get(m) or {}).get(k) for k in notify.RANGE_FIELDS}
        last_z = {zt: [lo, hi] for zt, lo, hi in con.execute(
            "SELECT zone_type, lo, hi FROM armed_zones WHERE mint=? AND source='range'", (m,))}
        s = snaps.get(m) or {}
        price, mcap = positions.price_mcap(p, s)
        aid = notify.new_id(m, "range_off", v.get("zone_version"), int(v.get("computed_ts") or now))
        z = {"mint": m, "symbol": p.get("symbol"), "zone_type": "range", "lo": (last_z.get("bottom") or [None])[0],
             "hi": (last_z.get("top") or [None, None])[1], "source": "range", "note": text}
        tx5 = (s.get("buys_m5") or 0) + (s.get("sells_m5") or 0)
        pl = _payload(aid, "range_off", z, s, now, {"initial": False}, rug_fn(m, mcap, s.get("liq")),
                      uniq_fn(m, now, tx5))
        if pl.get("mcap") is None and mcap:
            pl["mcap"] = round(mcap)
        pl.update(v)
        pl.update(reason=text, reason_key=key, range_status=text.split(":")[0], last_zones=last_z,
                  position=positions.block(p, price))
        pl = notify.normalize(pl, now)
        if notify.record(con, pl, "pending", now):
            out.append(pl)
            log(f"zonewatch: {p.get('symbol') or m[:6]} raspon isključen ({key}: {text}), alarm range_off")
    store.kv_put(con, "range_on_pos", {"ts": int(now), "mints": keep})
    con.commit()
    return out


def forward_catalyst(con, now, econ=None, snaps=None, log=print):
    """team_catalyst rows of events.db (written by another module) -> alerts, once each (id tc_<row id>, watermark in
    kv). A missing events.db, table or type: nothing. Returns the new payloads."""
    from events import store as estore
    own = econ is None
    econ = econ or estore.ro()
    if econ is None:
        return []
    out = []
    try:
        wm = store.kv_get(con, "tc_watermark")
        if wm is None:
            r = econ.execute("SELECT COALESCE(MAX(id), 0) FROM events WHERE type='team_catalyst' AND ts < ?",
                             (int((now - CATALYST_FIRST_S) * 1000),)).fetchone()
            wm = int(r[0] or 0)
        rows = econ.execute("SELECT id, ts, mint, source, actor, mcap_usd, payload FROM events WHERE type='team_catalyst' "
                            "AND id > ? ORDER BY id LIMIT ?", (int(wm), CATALYST_BATCH)).fetchall()
        for rid, ts, mint, src, actor, mc, pl in rows:
            wm = max(int(wm), int(rid))
            if (ts or 0) < (now - CATALYST_FIRST_S) * 1000:   # a stale catalyst (the flag was off) is no alarm
                continue
            try:
                p = json.loads(pl) if pl else {}
            except ValueError:
                p = {}
            p = p if isinstance(p, dict) else {"payload": p}
            s = (snaps or {}).get(mint) or {}
            a = {k: p.get(k) for k in notify.OWNER_FIELDS if p.get(k) is not None}
            for k, sk in (("symbol", "symbol"), ("price", "price"), ("liq", "liq"), ("vol_5m", "vol_m5"),
                          ("vol_1h", "vol_h1"), ("buys_5m", "buys_m5"), ("sells_5m", "sells_m5")):
                if a.get(k) is None and s.get(sk) is not None:
                    a[k] = s[sk]
            if a.get("buy_share_1h") is None:
                a["buy_share_1h"] = notify.share(s.get("buys_h1"), s.get("sells_h1"))
            a.update(id=f"tc_{rid}", event="team_catalyst", zone_type="team_catalyst", mint=mint or p.get("mint"),
                     mcap=mc if mc is not None else (p.get("mcap") or s.get("mcap")), source=a.get("source") or "event",
                     ts=int((ts or now * 1000) // 1000), event_row_id=rid, catalyst=p, catalyst_source=src,
                     catalyst_actor=actor)
            if len(json.dumps(p, default=str)) > CATALYST_MAX_CHARS:   # the webhook body stays small
                a["catalyst"] = {k: v for k, v in p.items() if isinstance(v, (str, int, float, bool)) and
                                 len(str(v)) <= 300}
            payload = notify.normalize(a, now)
            if notify.record(con, payload, "pending", now):
                out.append(payload)
        store.kv_put(con, "tc_watermark", int(wm))
        con.commit()
    except sqlite3.Error:
        return out
    finally:
        if own:
            econ.close()
    if out:
        log(f"zonewatch: {len(out)} team_catalyst događaj(a) za slanje")
    return out


def deliver_pending(con, now, cfg=None, flag=None, opener=None, sleep=None, clock=None, budget_s=POST_BUDGET_S):
    """Post the pending alerts, the stops first (stop_hit, a position's sl_near / sl_hit) then the oldest, within
    budget_s; too old -> expired. Returns {status: count}."""
    clock = clock or time.time
    t0 = clock()
    done = {}
    rows = con.execute("SELECT id, ts, event FROM alerts WHERE status='pending' ORDER BY (event='stop_hit' OR "
                       "zone_type='position_sl') DESC, ts, id").fetchall()
    for aid, ts, ev in rows:
        if now - (ts or now) > PENDING_MAX_S:
            con.execute("UPDATE alerts SET status='expired' WHERE id=?", (aid,))
            con.commit()
            done["expired"] = done.get("expired", 0) + 1
            continue
        if clock() - t0 > budget_s:
            done["waiting"] = done.get("waiting", 0) + 1
            continue
        res = notify.deliver(con, aid, cfg, flag, now, opener, sleep, clock)
        done[res["status"]] = done.get(res["status"], 0) + 1
    return done


def cost_line(con, now, log=print):
    """One line at the first pass of a UTC day about yesterday: DexScreener requests / cap, POSTs, alarms."""
    today = store.day(now)
    last = store.kv_get(con, "cost_day")
    if last == today:
        return None
    store.kv_put(con, "cost_day", today)
    con.commit()
    if last is None:
        return None
    from calendar import timegm
    a = timegm(time.strptime(last, "%Y-%m-%d"))
    b = a + 86400
    dex = int((store.kv_get(con, "day:dex") or {}).get(last, 0))
    ok = con.execute("SELECT COUNT(*) FROM zonewatch_log WHERE ts >= ? AND ts < ? AND status='ok'", (a, b)).fetchone()[0]
    bad = con.execute("SELECT COUNT(*) FROM zonewatch_log WHERE ts >= ? AND ts < ? AND status IN ('failed', "
                      "'config_error')", (a, b)).fetchone()[0]
    by = dict(con.execute("SELECT event, COUNT(*) FROM alerts WHERE ts >= ? AND ts < ? GROUP BY event", (a, b)).fetchall())
    line = (f"zonewatch trošak ({last}): dexscreener {dex}/{prices.DEX_DAY} zahtjeva (besplatno), webhook {ok} ok / "
            f"{bad} neuspjelih, alarmi " + (", ".join(f"{k} {v}" for k, v in sorted(by.items())) or "0") + ", 0 $")
    log(line)
    return line


def probe_once(con, now, cfg=None, log=print):
    """11.11. (Jure: "javi kad je live da Grok Bot pošalje probni alarm"): one test alarm (event "test") the first
    time the webhook env is set, so the receiving routine can be checked end to end; never again (kv probe_sent). No
    token (mint null): it says nothing about any coin."""
    c = cfg or notify.config()
    if not c.configured or store.kv_get(con, "probe_sent"):
        return None
    p = notify.normalize({"event": "test", "zone_type": "test", "mint": None, "symbol": None, "source": "manual",
                          "note": "probni alarm MemeSonar zonewatch (jednom, pri prvom pokretanju s postavljenim "
                                  "webhookom); nije trgovinski signal"}, now)
    notify.record(con, p, "pending", now)
    store.kv_put(con, "probe_sent", now)
    con.commit()
    log("zonewatch: probni alarm (event test) spremljen za slanje Grok Botu")
    return p["id"]


def pass_once(now=None, fetch=None, cfg=None, opener=None, sleep=None, clock=None, log=print, rug_fn=None,
              uniq_fn=None, flag=None, path=None):
    """One pass. Returns a summary dict ({"mode": "off"} when the flag is off)."""
    flag = flag or store.mode()
    if flag == "off":
        return {"mode": "off"}
    now = int(now or time.time())
    con = store.connect(path)
    try:
        store.migrate_once(con, now, log)
        probe_once(con, now, cfg, log)
        _sync_range(con, now, log)
        zs = store.active(con, now)
        by = {}
        for z in zs:
            by.setdefault(z["mint"], []).append(z)
        pos = load_positions(now, log)   # 11.11.: the real account's positions and their own levels
        for m, pz in positions.plan_zones(pos).items():
            by[m] = by.get(m, []) + pz   # priced with the zones (a level within 10 %: the fast poll)
        snaps = prices.latest(con, by)
        due, prio = prices.plan(by, snaps, now, prices.cold(con, now))
        left = prices.budget_left(con, now)
        ask, dropped = prices.pick(due, prio, snaps, now, left)
        if dropped and store.kv_get(con, "said:dex_cap") != store.day(now):
            store.kv_put(con, "said:dex_cap", store.day(now))
            log(f"zonewatch: dnevni strop DexScreenera ({prices.DEX_DAY}) ili 4 zahtjeva po prolazu: {dropped} tokena "
                "čeka sljedeći prolaz (koriste se spremljene snimke)")
        if ask:
            try:
                snaps.update(prices.poll(con, ask, now, fetch))
            except Exception as e:  # noqa: BLE001 - the stored snapshots still serve this pass
                log(f"zonewatch: DexScreener nije odgovorio ({type(e).__name__})")
        new, debounced = evaluate(con, zs, snaps, now, rug_fn, uniq_fn)
        pnew, pdeb = evaluate_positions(con, pos, snaps, now, rug_fn, uniq_fn)
        roff = range_off(con, pos, snaps, now, rug_fn, uniq_fn, log)
        cat = forward_catalyst(con, now, snaps=snaps, log=log)
        sent = deliver_pending(con, now, cfg, flag, opener, sleep, clock)
        cost_line(con, now, log)
        if now - (store.kv_get(con, "pruned") or 0) >= PRUNE_EVERY_S:
            store.prune(con, now)
            store.kv_put(con, "pruned", now)
            con.commit()
        return {"mode": flag, "zones": len(zs), "tokens": len(by), "asked": len(ask), "alerts": len(new),
                "positions": len(pos or []), "position_alerts": len(pnew), "range_off": len(roff),
                "catalyst": len(cat), "debounced": debounced + pdeb, "delivered": sent}
    finally:
        con.close()
