"""What MCP clients and get_hourly_brief see of the zone watch.

    mcp_tool()     arm_zone (upsert one zone for at most 2 h; ttl_h=0 disarms it) and get_armed_zones (the zones in
                   force with their state, distance and last alarm; a range zone with zone_version, computed_ts and
                   window_h of its range); client attribution mcp:<key fingerprint>
    brief_part()   get_hourly_brief.zonewatch {armed, alerts_24h, last_post_ok, last_error, configured, without_range}
Read-only except arm_zone (zonewatch.db armed_zones / arm_log) and the one-time migration (store.migrate_once).
"""
import sqlite3
import time

from zonewatch import notify, store, zones

LIMIT_DEFAULT, LIMIT_MAX = 100, 300
HOW = ("Zones are market cap USD. Range zones (source range) come only from MemeSonar's range engine (swing points "
       "of 24 h, touches weighted by age, recomputed about every 5 min; stop = range_low_low x 0.85), for tokens with an "
       "open range round, an entry-ready range or an open position on the real account, and only while the engine "
       "has an active range for them; each newer computation is a new zone_version (computed_ts = when it was "
       "computed, window_h = the hours of data it spanned), and every alarm of a range zone carries the three. "
       "zone_enter / zone_exit when the market cap crosses a bottom, dca or custom zone, top_hit at >= top lo, "
       "stop_hit at <= the stop; hysteresis 0.5 %; the same mint + zone + event at most once in 30 min (stop_hit: "
       "always, at most once a minute). Tokens within 10 % of a zone are re-priced every 30 s. A hand-armed zone "
       "(arm_zone) lives at most 2 h. Disarm: arm_zone with ttl_h=0 (same mint, zone_type, source).")


def _state_of(z, st, px, now):
    mc = (px or {}).get("mcap") or (st or {}).get("last_mcap")
    ts = (px or {}).get("ts") or (st or {}).get("last_ts")
    d, side = zones.distance(z, mc) if mc else (None, None)
    inside = (st or {}).get("inside")
    return {"state": "unknown" if inside is None else ("inside" if inside else "outside"),
            "inside_since_ts": (st or {}).get("since_ts") if inside else None,
            "mcap_now": round(mc) if mc else None, "mcap_ts": ts, "mcap_age_s": int(now - ts) if ts else None,
            "distance_pct": round(d * 100, 2) if d is not None else None, "zone_is": side}


def armed_zones(mint=None, source=None, limit=None, now=None, path=None):
    """get_armed_zones: the zones in force, hand-armed first, each with its state."""
    now = int(now or time.time())
    try:
        lim = max(1, min(LIMIT_MAX, int(limit if limit is not None else LIMIT_DEFAULT)))
    except (TypeError, ValueError):
        return {"error": "limit must be an integer 1-300"}
    src = str(source).strip().lower() if source else None
    if src and src not in store.SOURCES:
        return {"error": f"source must be one of {', '.join(store.SOURCES)}"}
    m = str(mint).strip() if mint else None
    if m and not store.MINT_RE.match(m):
        return {"error": "mint must be a Solana token address"}
    cfg = notify.config()
    out = {"ts": now, "flag_mode": store.mode(), "configured": cfg.configured, "zones": [], "counts": {},
           "limits": {"max_armed": store.MAX_ARMED, "arm_per_hour": store.RATE_PER_HOUR, "ttl_h_default":
                      store.TTL_DEFAULT_H, "ttl_h_max": store.TTL_MAX_H, "min_mcap_usd": store.MIN_MCAP},
           "how": HOW}
    con = store.connect(path)
    try:
        store.migrate_once(con, now, log=lambda s: None)   # the loop's job; a first look before it ever ran
        zs = store.active(con, now, m, src)
        out["counts"] = dict(con.execute("SELECT source, COUNT(*) FROM armed_zones WHERE expires_at > ? GROUP BY source",
                                         (now,)).fetchall())
        sts = store.states(con)
        mints = sorted({z["mint"] for z in zs})
        px = {r[0]: {"mcap": r[1], "ts": r[2], "symbol": r[3]} for r in con.execute(
            f"SELECT mint, mcap, ts, symbol FROM px WHERE mint IN ({','.join('?' * len(mints))})", mints)} if mints else {}
        ver = store.versions(con)
        last = {}
        for mt, zt, ev, ts, status in con.execute(
                "SELECT mint, zone_type, event, ts, status FROM alerts WHERE ts >= ? ORDER BY ts", (now - 30 * 86400,)):
            last[(mt, zt)] = {"event": ev, "ts": ts, "status": status}
        for z in zs[:lim]:
            p = px.get(z["mint"])
            out["zones"].append({
                "mint": z["mint"], "symbol": z.get("symbol") or (p or {}).get("symbol"), "zone_type": z["zone_type"],
                "lo": z["lo"], "hi": z["hi"], "source": z["source"], "note": z.get("note"), "armed_by": z.get("kid"),
                "created_ts": z.get("created_ts"), "updated_ts": z.get("updated_ts"), "expires_at": z["expires_at"],
                "expires_in_h": round((z["expires_at"] - now) / 3600, 1),
                **{k: (ver.get(z["mint"]) or {}).get(k) if z["source"] == "range" else None
                   for k in notify.RANGE_FIELDS},
                **_state_of(z, sts.get((z["mint"], z["zone_type"], z["source"])), p, now),
                "last_alert": last.get((z["mint"], z["zone_type"]))})
        out["shown"] = len(out["zones"])
        out["total"] = len(zs)
    except sqlite3.Error as e:
        return {"error": f"zonewatch.db: {type(e).__name__}"}
    finally:
        con.close()
    return out


def arm_zone(a, kid):
    """MCP arm_zone: upsert (mint, zone_type, source); ttl_h=0 disarms."""
    now = int(time.time())
    con = store.connect()
    try:
        store.migrate_once(con, now, log=lambda s: None)
        res = store.arm(a.get("mint") or a.get("token") or a.get("token_address"), a.get("zone_type"), a.get("lo"),
                        a.get("hi"), a.get("note"), a.get("ttl_h"), a.get("source") or "manual", kid=kid, now=now, con=con)
    finally:
        con.close()
    z = res["zone"] or {}
    mode = store.mode()
    if res["changed"] == "disarmed":
        msg = "Disarmed."
    elif mode == "off":
        msg = "Stored. The owner has zonewatch off: nothing is watched until it is on."
    elif notify.config().configured:
        msg = "Stored. MemeSonar watches it now and posts to Grok Bot."
    else:
        msg = "Stored. MemeSonar watches it now; the webhook is not configured, so alarms are only stored."
    return {"zone": {k: z.get(k) for k in ("mint", "zone_type", "lo", "hi", "source", "note", "expires_at", "symbol")},
            "changed": res["changed"], "flag_mode": mode, "message": msg + " " + HOW}


def mcp_tool(name, a, kid="local"):
    a = a if isinstance(a, dict) else {}
    try:
        if name == "arm_zone":
            return arm_zone(a, kid)
        return armed_zones(a.get("mint") or a.get("token"), a.get("source"), a.get("limit"))
    except ValueError as e:
        return {"error": str(e)}
    except sqlite3.Error as e:
        return {"error": f"zonewatch.db: {type(e).__name__}"}


def brief_part(now=None, path=None):
    """get_hourly_brief.zonewatch: zones in force, alarms of the last 24 h, the last good POST and the last error,
    whether the webhook is configured and the flag."""
    now = int(now or time.time())
    cfg = notify.config()
    out = {"flag_mode": store.mode(), "configured": cfg.configured, "armed": 0, "armed_by_source": {},
           "alerts_24h": 0, "alerts_24h_by_event": {}, "alerts_24h_by_status": {}, "last_post_ok": None,
           "last_error": None, "without_range": {},
           "tool": "get_armed_zones for the zones, arm_zone to set one"}
    con = store.ro(path)
    if con is None:
        return out
    try:
        by = dict(con.execute("SELECT source, COUNT(*) FROM armed_zones WHERE expires_at > ? GROUP BY source",
                              (now,)).fetchall())
        out.update(armed=sum(by.values()), armed_by_source=by)
        out["alerts_24h_by_event"] = dict(con.execute("SELECT event, COUNT(*) FROM alerts WHERE ts >= ? GROUP BY event",
                                                      (now - 86400,)).fetchall())
        out["alerts_24h_by_status"] = dict(con.execute("SELECT status, COUNT(*) FROM alerts WHERE ts >= ? GROUP BY "
                                                       "status", (now - 86400,)).fetchall())
        out["alerts_24h"] = sum(out["alerts_24h_by_event"].values())
        out["last_post_ok"] = store.kv_get(con, "last_post_ok")
        out["last_error"] = store.kv_get(con, "last_error")
        # 11.11.: the watched tokens (open round, entry-ready, real-account position) without an active range: why
        out["without_range"] = store.kv_get(con, "range_why") or {}
    except sqlite3.Error as e:
        out["error"] = f"zonewatch.db: {type(e).__name__}"
    finally:
        con.close()
    return out
