"""zonewatch.db: the zones, their state, the alerts and the delivery log (DATA_DIR, like range.db).

Writers: run_zonewatch.py (the loop), the MCP tool arm_zone (run_ui.py) and zonewatch.notify.post_alert's direct
callers; WAL journal and a short busy timeout, so none of them waits on another for long. Everyone else reads it
read-only.

Tables
  armed_zones    one row per (mint, zone_type, source): lo, hi (market cap USD; a stop given as one number has
                 lo = hi), note, symbol, kid (who armed it: mcp:<key fingerprint> | owner | range), created_ts,
                 updated_ts, expires_at. zone_type bottom | dca | top | stop | custom; source manual | range | event.
                 A disarmed or expired row stays (expires_at <= now) a week for the history.
  zone_state     (mint, zone_type, source): inside 0/1, since_ts, last_mcap, last_ts (the state machine, zones.py)
  alerts         one row per alarm: id (stable, the webhook-id across retries), ts, mint, zone_type, event, source,
                 status pending | sent | failed | config_error | not_configured | off | expired, attempts,
                 http_status, posted_ts, payload (the JSON body)
  zonewatch_log  one row per delivery attempt: ts, alert_id, event, attempt, status, http_status, latency_ms, host
                 (scheme + host only, never the path or the query), error (a short class, never the message)
  arm_log        every arm_zone write (ts, kid, mint, zone_type, source, what): the audit trail and the hourly limit
  px             the newest numbers this job fetched itself per mint (DexScreener), for the next pass
  kv             the seed flag, day counters, the team_catalyst watermark, last_post_ok, last_error
"""
import json
import os
import re
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "zonewatch"
ZONE_TYPES = ("bottom", "dca", "top", "stop", "custom")
SOURCES = ("manual", "range", "event")
ARM_SOURCES = ("manual", "event")   # range zones come from the range engine only
MIN_MCAP = 30_000                    # CLAUDE.md: tokens under 30k are not analysed
MAX_MCAP = 1e11
TTL_DEFAULT_H, TTL_MAX_H = 72, 720
MAX_ARMED = int(os.environ.get("ZONEWATCH_MAX_ARMED") or 100)
RATE_PER_HOUR = int(os.environ.get("ZONEWATCH_ARM_PER_HOUR") or 60)
NOTE_MAX = 300
KEEP_EXPIRED_D = 7
KEEP_ALERTS_D = 30
KEEP_LOG_D = 14
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
OWNER = "owner"

# 11.11. (Jure): HOPE bought by hand at ~133k; armed once (kv seed:hope), source manual, 7 days
SEED_KEY = "seed:hope_1111"
SEED = {"mint": "GxRPJsRK9TE9EgBhLxrFGcRYLGqPJe4fxtiPmdXCpump", "symbol": "HOPE", "note": "vlasnik ručno kupio ~133k",
        "ttl_h": 7 * 24, "zones": (("dca", 100_000, 105_000), ("stop", 85_000, 85_000), ("top", 145_000, 155_000))}

SCHEMA = """
CREATE TABLE IF NOT EXISTS armed_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT NOT NULL, zone_type TEXT NOT NULL, lo REAL NOT NULL, hi REAL NOT NULL,
    note TEXT, source TEXT NOT NULL, symbol TEXT, kid TEXT, created_ts INTEGER, updated_ts INTEGER,
    expires_at INTEGER NOT NULL, UNIQUE (mint, zone_type, source));
CREATE INDEX IF NOT EXISTS armed_zones_exp ON armed_zones (expires_at);
CREATE TABLE IF NOT EXISTS zone_state (
    mint TEXT, zone_type TEXT, source TEXT, inside INTEGER, since_ts INTEGER, last_mcap REAL, last_ts INTEGER,
    PRIMARY KEY (mint, zone_type, source));
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, ts INTEGER, mint TEXT, zone_type TEXT, event TEXT, source TEXT, status TEXT,
    attempts INTEGER DEFAULT 0, http_status INTEGER, posted_ts INTEGER, payload TEXT);
CREATE INDEX IF NOT EXISTS alerts_ts ON alerts (ts);
CREATE INDEX IF NOT EXISTS alerts_key ON alerts (mint, zone_type, event, ts);
CREATE INDEX IF NOT EXISTS alerts_status ON alerts (status, ts);
CREATE TABLE IF NOT EXISTS zonewatch_log (
    ts INTEGER, alert_id TEXT, event TEXT, attempt INTEGER, status TEXT, http_status INTEGER, latency_ms INTEGER,
    host TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS zonewatch_log_ts ON zonewatch_log (ts);
CREATE TABLE IF NOT EXISTS arm_log (ts INTEGER, kid TEXT, mint TEXT, zone_type TEXT, source TEXT, what TEXT);
CREATE INDEX IF NOT EXISTS arm_log_kid ON arm_log (kid, ts);
CREATE TABLE IF NOT EXISTS px (
    mint TEXT PRIMARY KEY, ts INTEGER, price REAL, mcap REAL, liq REAL, vol_m5 REAL, vol_h1 REAL, buys_m5 INTEGER,
    sells_m5 INTEGER, buys_h1 INTEGER, sells_h1 INTEGER, symbol TEXT, src TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def db_path():
    """zonewatch.db: ZONEWATCH_DB, else DATA_DIR (Render /var/data), else the repository root."""
    if os.environ.get("ZONEWATCH_DB"):
        return os.environ["ZONEWATCH_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "zonewatch.db")
    return os.path.join(ROOT, "zonewatch.db")


def connect(path=None, timeout=10):
    p = path or db_path()
    new = not os.path.exists(p) or not os.path.getsize(p)
    con = sqlite3.connect(p, timeout=timeout)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    try:
        con.execute("PRAGMA journal_mode=WAL")   # the MCP tool and the brief never wait on the loop's pass
    except sqlite3.Error:
        pass
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only connection, None while zonewatch.db does not exist (the job never ran, nothing armed)."""
    p = path or db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM armed_zones LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def mode(trade_db=None):
    """The data flag zonewatch (trade settings G21): off | shadow | paper | live; "off" when unreadable."""
    try:
        from trade import settings
        return settings.flag(FLAG, path=trade_db) if trade_db else settings.flag(FLAG)
    except Exception:  # noqa: BLE001 - an unreadable flag is off
        return "off"


def kv_get(con, k, default=None):
    try:
        r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    except sqlite3.Error:
        return default
    if not r:
        return default
    try:
        return json.loads(r[0])
    except ValueError:
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))


def day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def day_used(con, key, now):
    return int((kv_get(con, f"day:{key}") or {}).get(day(now), 0))


def day_add(con, key, n, now):
    d = kv_get(con, f"day:{key}") or {}
    keep = {k: v for k, v in d.items() if k >= day(now - 8 * 86400)}   # a week for the weekly cost report
    keep[day(now)] = int(keep.get(day(now), 0)) + int(n)
    kv_put(con, f"day:{key}", keep)
    return keep[day(now)]


# ---------- zones ---------------------------------------------------------------------------------------------------

COLS = ("id", "mint", "zone_type", "lo", "hi", "note", "source", "symbol", "kid", "created_ts", "updated_ts",
        "expires_at")


def _zone(row):
    return dict(zip(COLS, row))


def active(con, now, mint=None, source=None):
    """The zones in force (expires_at > now), hand-armed first (manual, event, range), then by mint."""
    sql, args = f"SELECT {', '.join(COLS)} FROM armed_zones WHERE expires_at > ?", [int(now)]
    if mint:
        sql += " AND mint = ?"
        args.append(mint)
    if source:
        sql += " AND source = ?"
        args.append(source)
    rows = [_zone(r) for r in con.execute(sql, args)]
    order = {s: i for i, s in enumerate(SOURCES)}
    return sorted(rows, key=lambda z: (order.get(z["source"], 9), z["mint"], z["zone_type"]))


def upsert(con, mint, zone_type, lo, hi, note, source, kid, expires_at, now, symbol=None, reset=True):
    """Insert or update one zone. A re-armed zone with new bounds starts afresh (reset: the next observation is a
    first one); a range zone keeps its state when the engine moves its edges (reset=False: the zone moving onto the
    price is an entry too). A zone revived after it expired always starts afresh. Returns "created" | "updated" |
    "unchanged"."""
    old = con.execute("SELECT lo, hi, note, expires_at FROM armed_zones WHERE mint=? AND zone_type=? AND source=?",
                      (mint, zone_type, source)).fetchone()
    if old is None:
        con.execute("INSERT INTO armed_zones (mint, zone_type, lo, hi, note, source, symbol, kid, created_ts, updated_ts, "
                    "expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (mint, zone_type, float(lo), float(hi), note, source, symbol, kid, int(now), int(now), int(expires_at)))
        con.execute("DELETE FROM zone_state WHERE mint=? AND zone_type=? AND source=?", (mint, zone_type, source))
        return "created"
    moved = abs(old[0] - lo) > 1e-6 * max(1.0, lo) or abs(old[1] - hi) > 1e-6 * max(1.0, hi)
    revived = (old[3] or 0) <= now
    if not moved and not revived and old[2] == (note if note is not None else old[2]) and old[3] == int(expires_at):
        return "unchanged"
    con.execute("UPDATE armed_zones SET lo=?, hi=?, note=COALESCE(?, note), kid=?, updated_ts=?, expires_at=?, "
                "symbol=COALESCE(?, symbol) WHERE mint=? AND zone_type=? AND source=?",
                (float(lo), float(hi), note, kid, int(now), int(expires_at), symbol, mint, zone_type, source))
    if (moved and reset) or revived:
        con.execute("DELETE FROM zone_state WHERE mint=? AND zone_type=? AND source=?", (mint, zone_type, source))
    return "updated"


def _num(x, name):
    if isinstance(x, bool) or x is None or x == "":
        raise ValueError(f"{name} must be a number (market cap in USD)")
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number (market cap in USD)")
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number")
    return v


def validate(mint, zone_type, lo, hi, ttl_h, source):
    """(mint, zone_type, lo, hi, ttl_h, source) cleaned, or ValueError with the reason for the client. ttl_h 0 means
    disarm (lo / hi are then not needed)."""
    m = str(mint or "").strip()
    if not MINT_RE.match(m):
        raise ValueError("mint must be a Solana token address (base58, 32-44 characters)")
    zt = str(zone_type or "").strip().lower()
    if zt not in ZONE_TYPES:
        raise ValueError(f"zone_type must be one of {', '.join(ZONE_TYPES)}")
    src = str(source or "manual").strip().lower()
    if src not in ARM_SOURCES:
        raise ValueError("source must be manual or event (range zones come from the range engine itself)")
    if ttl_h is None or ttl_h == "":
        ttl = float(TTL_DEFAULT_H)
    else:
        ttl = _num(ttl_h, "ttl_h")
        if ttl < 0 or ttl > TTL_MAX_H:
            raise ValueError(f"ttl_h must be 0 (disarm) to {TTL_MAX_H} hours")
    if ttl == 0:
        return m, zt, None, None, 0.0, src
    lo_v = _num(lo, "lo") if lo not in (None, "") else None
    hi_v = _num(hi, "hi") if hi not in (None, "") else None
    if zt == "stop":
        if lo_v is None and hi_v is None:
            raise ValueError("a stop needs lo (the stop's market cap; hi may be left out)")
        lo_v = lo_v if lo_v is not None else hi_v
        hi_v = hi_v if hi_v is not None else lo_v
    elif lo_v is None or hi_v is None:
        raise ValueError(f"a {zt} zone needs lo and hi (market cap in USD)")
    if lo_v > hi_v:
        raise ValueError("lo must be <= hi")
    if lo_v < MIN_MCAP:
        raise ValueError(f"lo must be at least {MIN_MCAP:,} USD market cap (tokens under 30k are not analysed)")
    if hi_v > MAX_MCAP:
        raise ValueError("hi is not a plausible market cap")
    return m, zt, lo_v, hi_v, ttl, src


def arm(mint, zone_type, lo=None, hi=None, note=None, ttl_h=None, source="manual", kid="local", now=None, con=None,
        path=None):
    """MCP arm_zone (and the owner's CLI): upsert one zone on (mint, zone_type, source); ttl_h 0 disarms it.
    Returns the stored zone and what changed; ValueError with the reason for the client (bad field, the hourly limit
    of RATE_PER_HOUR writes per key, more than MAX_ARMED active hand-armed zones, nothing to disarm)."""
    now = int(now or time.time())
    m, zt, lo_v, hi_v, ttl, src = validate(mint, zone_type, lo, hi, ttl_h, source)
    nt = str(note).strip()[:NOTE_MAX] if note not in (None, "") else None
    owner = kid == OWNER
    own = con is None
    con = con or connect(path)
    try:
        if not owner:
            n = con.execute("SELECT COUNT(*) FROM arm_log WHERE kid=? AND ts>?", (kid, now - 3600)).fetchone()[0]
            if n >= RATE_PER_HOUR:
                raise ValueError(f"rate limit: at most {RATE_PER_HOUR} arm_zone calls an hour per key")
        cur = con.execute("SELECT expires_at FROM armed_zones WHERE mint=? AND zone_type=? AND source=?",
                          (m, zt, src)).fetchone()
        is_active = bool(cur and (cur[0] or 0) > now)
        if ttl == 0:
            if not is_active:
                raise ValueError(f"no active {zt} zone ({src}) armed for this mint: nothing to disarm")
            con.execute("UPDATE armed_zones SET expires_at=?, updated_ts=?, kid=? WHERE mint=? AND zone_type=? AND source=?",
                        (now, now, kid, m, zt, src))
            con.execute("DELETE FROM zone_state WHERE mint=? AND zone_type=? AND source=?", (m, zt, src))
            what = "disarmed"
        else:
            if not is_active and not owner:
                n_act = con.execute("SELECT COUNT(*) FROM armed_zones WHERE source != 'range' AND expires_at > ?",
                                    (now,)).fetchone()[0]
                if n_act >= MAX_ARMED:
                    raise ValueError(f"at most {MAX_ARMED} active armed zones: disarm one first (ttl_h=0)")
            sym = con.execute("SELECT symbol FROM px WHERE mint=?", (m,)).fetchone()
            what = upsert(con, m, zt, lo_v, hi_v, nt, src, kid, now + int(ttl * 3600), now, sym[0] if sym else None)
        con.execute("INSERT INTO arm_log VALUES (?,?,?,?,?,?)", (now, kid, m, zt, src, what))
        con.commit()
        row = con.execute(f"SELECT {', '.join(COLS)} FROM armed_zones WHERE mint=? AND zone_type=? AND source=?",
                          (m, zt, src)).fetchone()
    finally:
        if own:
            con.close()
    print(f"zonewatch: {what} {zt} {m[:6]}… ({src}, {kid})", flush=True)
    return {"zone": _zone(row) if row else None, "changed": what}


def seed_once(con, now=None):
    """Arm HOPE's zones once (kv SEED_KEY survives restarts; after 7 days they expire and are never re-armed)."""
    now = int(now or time.time())
    if kv_get(con, SEED_KEY):
        return False
    for zt, lo, hi in SEED["zones"]:
        upsert(con, SEED["mint"], zt, lo, hi, SEED["note"], "manual", OWNER, now + SEED["ttl_h"] * 3600, now,
               SEED["symbol"])
        con.execute("INSERT INTO arm_log VALUES (?,?,?,?,?,?)", (now, OWNER, SEED["mint"], zt, "manual", "seed"))
    kv_put(con, SEED_KEY, now)
    con.commit()
    print(f"zonewatch: HOPE zone postavljene (dca 100-105k, stop 85k, top 145-155k, {SEED['ttl_h'] // 24} dana)",
          flush=True)
    return True


def states(con, keys=None):
    """{(mint, zone_type, source): state dict} (all, or of these keys)."""
    out = {}
    for m, zt, src, ins, since, mc, ts in con.execute("SELECT mint, zone_type, source, inside, since_ts, last_mcap, last_ts "
                                                      "FROM zone_state"):
        k = (m, zt, src)
        if keys is None or k in keys:
            out[k] = {"inside": None if ins is None else bool(ins), "since_ts": since, "last_mcap": mc, "last_ts": ts}
    return out


def save_state(con, key, st):
    con.execute("INSERT OR REPLACE INTO zone_state VALUES (?,?,?,?,?,?,?)",
                (*key, None if st.get("inside") is None else int(bool(st["inside"])), st.get("since_ts"),
                 st.get("last_mcap"), st.get("last_ts")))


def prune(con, now):
    con.execute("DELETE FROM armed_zones WHERE expires_at < ?", (int(now - KEEP_EXPIRED_D * 86400),))
    con.execute("DELETE FROM zone_state WHERE NOT EXISTS (SELECT 1 FROM armed_zones a WHERE a.mint = zone_state.mint "
                "AND a.zone_type = zone_state.zone_type AND a.source = zone_state.source AND a.expires_at > ?)",
                (int(now),))
    con.execute("DELETE FROM alerts WHERE ts < ?", (int(now - KEEP_ALERTS_D * 86400),))
    con.execute("DELETE FROM zonewatch_log WHERE ts < ?", (int(now - KEEP_LOG_D * 86400),))
    con.execute("DELETE FROM arm_log WHERE ts < ?", (int(now - KEEP_ALERTS_D * 86400),))
    con.execute("DELETE FROM px WHERE ts < ?", (int(now - 86400),))
    con.commit()
    try:
        con.execute("PRAGMA incremental_vacuum")
    except sqlite3.Error:
        pass


# ---------- range zones (source range) ------------------------------------------------------------------------------

def _range_rows(now, range_path=None):
    """[(token, symbol, ts, src, score, rll, rlt, rhl, rht, range_low_px, supply)] of the active ranges computed in
    the last RANGE_FRESH_S (15 min), market caps from the range JSON (json_extract: no JSON parsed in Python)."""
    from rangedca import data, trade
    con = data.ro(range_path)
    if con is None:
        return []
    try:
        src = "src" if data.has_src(con) else "'signal'"
        q = (f"SELECT token, symbol, ts, {src}, score, json_extract(data, '$.zones.mc.range_low_low'), "
             "json_extract(data, '$.zones.mc.range_low_top'), json_extract(data, '$.zones.mc.range_high_low'), "
             "json_extract(data, '$.zones.mc.range_high_top'), json_extract(data, '$.zones.range_low'), "
             "json_extract(data, '$.metrics.supply') FROM ranges WHERE active = 1 AND ts >= ?")
        try:
            return con.execute(q, (int(now - trade.RANGE_FRESH_S),)).fetchall()
        except sqlite3.OperationalError:   # no JSON1 in this SQLite: parse in Python (only the active rows)
            out = []
            for tok, sym, ts, s, sc, d in con.execute(f"SELECT token, symbol, ts, {src}, score, data FROM ranges WHERE "
                                                      "active = 1 AND ts >= ?", (int(now - trade.RANGE_FRESH_S),)):
                try:
                    x = json.loads(d)
                except ValueError:
                    continue
                z = x.get("zones") or {}
                mc = z.get("mc") or {}
                out.append((tok, sym, ts, s, sc, mc.get("range_low_low"), mc.get("range_low_top"),
                            mc.get("range_high_low"), mc.get("range_high_top"), z.get("range_low"),
                            (x.get("metrics") or {}).get("supply")))
            return out
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _open_lot1_mc():
    """{token: entry market cap of lot 1} of the open range rounds (league.db, read-only); {} on any error."""
    try:
        from rangedca import data
        con = data._league_ro()
    except Exception:  # noqa: BLE001
        return {}
    if con is None:
        return {}
    try:
        return {t: mc for t, mc in con.execute("SELECT token, entry_mc FROM range_rounds WHERE status='open' "
                                                "AND entry_mc > 0")}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def range_zones(row, lot1_mc=None):
    """The range engine's zones of one active range, in market cap USD (rangedca/detect.py and rules.py):
        bottom   range_low_low .. range_low_top
        dca      lot 2 at -10 to -15 % under lot 1 (rules lot2_lo / lot2_hi): under the open round's lot 1 when there
                 is one, else under the middle of the bottom zone (range_low), never under the floor range_low_low x
                 0.92 (lot 2's own floor); left out when that leaves nothing
        top      range_high_low .. range_high_top (half out at range_high_low)
        stop     range_low_low x 0.85 (the round's hard stop), lo = hi
    [(zone_type, lo, hi)]; [] when the market caps are unknown (no supply)."""
    from rangedca import rules
    tok, sym, ts, src, score, rll, rlt, rhl, rht, rl_px, supply = row
    if not all(isinstance(v, (int, float)) and v > 0 for v in (rll, rlt, rhl, rht)):
        return []
    r = rules.RULES
    out = [("bottom", float(rll), float(rlt)), ("top", float(rhl), float(rht))]
    ref = lot1_mc or (rl_px * supply if rl_px and supply else (rll + rlt) / 2)
    d_hi = ref * (1 - r["lot2_lo"])
    d_lo = max(ref * (1 - r["lot2_hi"]), rll * r["floor_x"])
    if d_lo < d_hi:
        out.append(("dca", round(d_lo), round(d_hi)))
    stop = round(rll * r["stop_x"])
    out.append(("stop", stop, stop))
    return out


def sync_range(con, now, rows=None, lot1=None, log=print):
    """The range engine's active ranges -> armed_zones (source range): upsert their zones (expiring RANGE_FRESH_S +
    5 min after the range was computed, so a range the engine stops computing goes away by itself) and expire at once
    the range zones of tokens whose range is no longer active. Returns (tokens, zones written)."""
    from rangedca import trade
    rows = _range_rows(now) if rows is None else rows
    lot1 = _open_lot1_mc() if lot1 is None else lot1
    keep, n = set(), 0
    for row in rows:
        tok, sym, ts, src = row[0], row[1], int(row[2] or now), row[3] or "signal"
        if not tok or not MINT_RE.match(tok):
            continue
        sc = row[4]
        note = f"raspon {src}" + (f", ocjena {sc:.2f}" if isinstance(sc, (int, float)) else "") + \
            (", lot 1 otvoren" if lot1.get(tok) else "")
        for zt, lo, hi in range_zones(row, lot1.get(tok)):
            if lo < MIN_MCAP:   # CLAUDE.md: nothing under 30k (a stop of a 32k floor at 27k is left out too)
                continue
            keep.add((tok, zt))
            if upsert(con, tok, zt, lo, hi, note, "range", "range", ts + trade.RANGE_FRESH_S + 300, now, sym,
                      reset=False) != "unchanged":
                n += 1
    gone = [(m, zt) for m, zt in con.execute("SELECT mint, zone_type FROM armed_zones WHERE source='range' AND "
                                             "expires_at > ?", (int(now),)) if (m, zt) not in keep]
    for m, zt in gone:
        con.execute("UPDATE armed_zones SET expires_at=? WHERE mint=? AND zone_type=? AND source='range'", (int(now), m, zt))
    con.commit()
    return len({t for t, _ in keep}), n
