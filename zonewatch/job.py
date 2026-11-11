"""One pass of the zone watch (run_zonewatch.py loop, every EVERY_S = 30 s, low priority). Flag zonewatch off: the
pass reads the flag and ends (nothing watched, nothing fetched, nothing posted).

    1. HOPE's zones once (store.seed_once), the range engine's active ranges -> zones (source range) when range.db
       has a newer computation or every 5 min
    2. the numbers of every token with a zone (prices.py: stored snapshots first, one DexScreener batch for the near
       / armed ones, inside the day cap)
    3. every zone's state (zones.step): an event on a crossing; the same mint + zone_type + event at most once in
       30 min (stop_hit: once in 60 s, never held back longer); several sources of the same zone in one pass: one alarm
    4. each alarm is stored (alerts, status pending) and written to events.db (type zone_alert), then posted
       (notify.deliver); stop_hit first, then the oldest; at most POST_BUDGET_S of posting a pass, the rest waits for
       the next pass (same id); an alarm still pending after PENDING_MAX_S is dropped as expired (a late alarm is noise)
    5. team_catalyst rows of events.db (another module's events) forwarded once each (dedupe by the row id)
    6. one cost line a UTC day: DexScreener requests / cap, POSTs ok / failed, alarms by event
"""
import json
import sqlite3
import time

from zonewatch import notify, prices, store, zones

EVERY_S = 30
RANGE_SYNC_S = 300
POST_BUDGET_S = 20
PENDING_MAX_S = 600
PRUNE_EVERY_S = 3600
CATALYST_FIRST_S = 1800   # the first pass forwards team_catalyst rows of the last 30 min, never an old backlog
CATALYST_BATCH = 20
CATALYST_MAX_CHARS = 4000
SRC_ORDER = {"manual": 0, "event": 1, "range": 2}


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
    pending) and the count of debounced ones."""
    rug_fn = rug_fn or prices.rug_risk
    uniq_fn = uniq_fn or prices.uniq_traders_1h
    st = store.states(con)
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
        p = notify.normalize(_payload(aid, ev, z, s, now, extra, rug_fn(z["mint"], s.get("mcap"), s.get("liq")),
                                      uniq_fn(z["mint"], now, tx5)), now)
        if notify.record(con, p, "pending", now):
            out.append(p)
    con.commit()
    return out, debounced


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
    """Post the pending alerts, stop_hit first then the oldest, within budget_s; too old -> expired. Returns
    {status: count}."""
    clock = clock or time.time
    t0 = clock()
    done = {}
    rows = con.execute("SELECT id, ts, event FROM alerts WHERE status='pending' ORDER BY (event='stop_hit') DESC, ts, id"
                       ).fetchall()
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


def pass_once(now=None, fetch=None, cfg=None, opener=None, sleep=None, clock=None, log=print, rug_fn=None,
              uniq_fn=None, flag=None, path=None):
    """One pass. Returns a summary dict ({"mode": "off"} when the flag is off)."""
    flag = flag or store.mode()
    if flag == "off":
        return {"mode": "off"}
    now = int(now or time.time())
    con = store.connect(path)
    try:
        store.seed_once(con, now)
        _sync_range(con, now, log)
        zs = store.active(con, now)
        by = {}
        for z in zs:
            by.setdefault(z["mint"], []).append(z)
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
        cat = forward_catalyst(con, now, snaps=snaps, log=log)
        sent = deliver_pending(con, now, cfg, flag, opener, sleep, clock)
        cost_line(con, now, log)
        if now - (store.kv_get(con, "pruned") or 0) >= PRUNE_EVERY_S:
            store.prune(con, now)
            store.kv_put(con, "pruned", now)
            con.commit()
        return {"mode": flag, "zones": len(zs), "tokens": len(by), "asked": len(ask), "alerts": len(new),
                "catalyst": len(cat), "debounced": debounced, "delivered": sent}
    finally:
        con.close()
