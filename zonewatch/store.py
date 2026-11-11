"""zonewatch.db: the zones, their state, the alerts and the delivery log (DATA_DIR, like range.db).

Writers: run_zonewatch.py (the loop), the MCP tool arm_zone (run_ui.py) and zonewatch.notify.post_alert's direct
callers; WAL journal and a short busy timeout, so none of them waits on another for long. Everyone else reads it
read-only.

Tables
  armed_zones    one row per (mint, zone_type, source): lo, hi (market cap USD; a stop given as one number has
                 lo = hi), note, symbol, kid (who armed it: mcp:<key fingerprint> | owner | range), created_ts,
                 updated_ts, expires_at. zone_type bottom | dca | top | stop | custom; source manual | range | event.
                 manual / event: armed by hand (MCP arm_zone, the owner's CLI), at most TTL_MAX_H = 2 h; range: the
                 range engine's zones (rangedca/detect.py, read from range.db, never computed here).
                 A disarmed or expired row stays (expires_at <= now) a week for the history.
  zone_state     (mint, zone_type, source): inside 0/1, since_ts, last_mcap, last_ts (the state machine, zones.py)
  range_ver      one row per token with range zones: zone_version (+1 for every new range computation of rangedca
                 this job has read, i.e. a newer ranges.ts), computed_ts (ranges.ts: when rangedca computed the
                 range), window_h (the hours of data the computation spanned, ranges data span_h; detect's window is
                 24 h), updated_ts. Every alarm and get_armed_zones carry these three for a range zone.
  alerts         one row per alarm: id (stable, the webhook-id across retries), ts, mint, zone_type, event, source,
                 status pending | sent | failed | config_error | not_configured | off | expired, attempts,
                 http_status, posted_ts, payload (the JSON body)
  zonewatch_log  one row per delivery attempt: ts, alert_id, event, attempt, status, http_status, latency_ms, host
                 (scheme + host only, never the path or the query), error (a short class, never the message)
  arm_log        every arm_zone write (ts, kid, mint, zone_type, source, what): the audit trail and the hourly limit
  px             the newest numbers this job fetched itself per mint (DexScreener), for the next pass
  kv             day counters, the team_catalyst watermark, last_post_ok, last_error, range_why (why an eligible
                 token has no range zones), the one-time migration flag; 11.11. pos_prev (the real account's
                 positions and their levels as the last pass saw them), pos_wm (the executors' records read so far),
                 pos_watch (counts for get_hourly_brief), range_on_pos (held tokens whose range was active)
  pos_alert      (mint, lkey, level): the last position_level alarm of one position level (the debounce)
  zone_state rows of source "position" are the position levels' states (zone_type pos:<level key> and
                 pos:<level key>:near), kept while the token is held
11.11. (Jure: "nikad fiksni seed"): the HOPE seed of PR #122 is gone; migrate_once expires what it may have armed
(its kv key seed:hope_1111 is left harmless) and cuts every hand-armed zone to at most 2 h from then.
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
TTL_DEFAULT_H, TTL_MAX_H = 2, 2      # 11.11. (Jure): a hand-armed zone lives at most 2 h
MAX_ARMED = int(os.environ.get("ZONEWATCH_MAX_ARMED") or 100)
RATE_PER_HOUR = int(os.environ.get("ZONEWATCH_ARM_PER_HOUR") or 60)
NOTE_MAX = 300
KEEP_EXPIRED_D = 7
KEEP_ALERTS_D = 30
KEEP_LOG_D = 14
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
OWNER = "owner"

MIGRATE_KEY = "migrate:noseed_1111"   # the seed expired and the hand-armed TTLs cut, once

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
CREATE TABLE IF NOT EXISTS range_ver (
    mint TEXT PRIMARY KEY, zone_version INTEGER, computed_ts INTEGER, window_h REAL, updated_ts INTEGER);
CREATE TABLE IF NOT EXISTS pos_alert (
    mint TEXT, lkey TEXT, level TEXT, ts INTEGER, alert_id TEXT, PRIMARY KEY (mint, lkey, level));
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
    """The data flag zonewatch (trade settings G25): off | shadow | paper | live; "off" when unreadable."""
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
            raise ValueError(f"ttl_h must be 0 (disarm) to {TTL_MAX_H} hours (a hand-armed zone lives at most "
                             f"{TTL_MAX_H} h; the range zones follow the range engine by themselves)")
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
    """MCP arm_zone (and the owner's CLI): upsert one zone on (mint, zone_type, source) for at most TTL_MAX_H (2 h);
    ttl_h 0 disarms it.
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


def migrate_once(con, now=None, log=print):
    """11.11. (Jure: "nikad fiksni seed"): once (kv MIGRATE_KEY), expire the zones the HOPE seed of PR #122 may have
    armed (its arm_log rows "seed"; arm_log "seed uklonjen") and cut every hand-armed zone still in force to at most
    TTL_MAX_H from now. Returns True when it ran."""
    now = int(now or time.time())
    if kv_get(con, MIGRATE_KEY):
        return False
    gone = 0
    for m, zt, src in con.execute("SELECT DISTINCT mint, zone_type, source FROM arm_log WHERE what='seed'").fetchall():
        n = con.execute("UPDATE armed_zones SET expires_at=?, updated_ts=? WHERE mint=? AND zone_type=? AND source=? "
                        "AND kid=? AND expires_at > ?", (now, now, m, zt, src, OWNER, now)).rowcount
        if n:
            gone += n
            con.execute("DELETE FROM zone_state WHERE mint=? AND zone_type=? AND source=?", (m, zt, src))
            con.execute("INSERT INTO arm_log VALUES (?,?,?,?,?,?)", (now, OWNER, m, zt, src, "seed uklonjen"))
    cut = con.execute("UPDATE armed_zones SET expires_at=? WHERE source IN ('manual', 'event') AND expires_at > ?",
                      (now + TTL_MAX_H * 3600, now + TTL_MAX_H * 3600)).rowcount
    kv_put(con, MIGRATE_KEY, now)
    con.commit()
    if gone or cut:
        log(f"zonewatch: fiksne HOPE zone istekle ({gone}), ručnim zonama rok skraćen na najviše {TTL_MAX_H} h ({cut})")
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
    con.execute("DELETE FROM zone_state WHERE source != 'position' AND NOT EXISTS (SELECT 1 FROM armed_zones a WHERE "
                "a.mint = zone_state.mint AND a.zone_type = zone_state.zone_type AND a.source = zone_state.source AND "
                "a.expires_at > ?)", (int(now),))
    # a position level's state lives while the token is held (job.evaluate_positions drops it at the close); one not
    # seen for a week is a leftover
    con.execute("DELETE FROM zone_state WHERE source = 'position' AND COALESCE(last_ts, 0) < ?",
                (int(now - KEEP_EXPIRED_D * 86400),))
    con.execute("DELETE FROM pos_alert WHERE ts < ?", (int(now - KEEP_EXPIRED_D * 86400),))
    con.execute("DELETE FROM alerts WHERE ts < ?", (int(now - KEEP_ALERTS_D * 86400),))
    con.execute("DELETE FROM zonewatch_log WHERE ts < ?", (int(now - KEEP_LOG_D * 86400),))
    con.execute("DELETE FROM arm_log WHERE ts < ?", (int(now - KEEP_ALERTS_D * 86400),))
    con.execute("DELETE FROM px WHERE ts < ?", (int(now - 86400),))
    con.execute("DELETE FROM range_ver WHERE updated_ts < ?", (int(now - KEEP_EXPIRED_D * 86400),))
    con.commit()
    try:
        con.execute("PRAGMA incremental_vacuum")
    except sqlite3.Error:
        pass


# ---------- range zones (source range) ------------------------------------------------------------------------------
# 11.11. (Jure, zbirni ispravak F): ONE source of zones, the range engine (rangedca/detect.py: pivots of 24 h, touches
# weighted by age with a half-life of 8 h; stop: 11.11. the ATR stop, range_low_low - 1.5 x ATR, x 0.85 without ATR)
# and the recomputation rangedca already does
# (run_range.py every ~5 min). This job only reads range.db; it adds the version (range_ver) and nothing else.

def _range_rows(now, range_path=None):
    """[(token, symbol, ts, src, score, rll, rlt, rhl, rht, range_low_px, supply, span_h, stop_mc)] of the active
    ranges computed in the last RANGE_FRESH_S (15 min), market caps from the range JSON (json_extract: no JSON parsed in
    Python); span_h = the hours of data the computation spanned (window_h); stop_mc (11.11., the owner's decision 1) =
    the range's hard stop in market cap (ranges.data "stop": the ATR stop), None for a range computed before it."""
    from rangedca import data, trade
    con = data.ro(range_path)
    if con is None:
        return []
    try:
        src = "src" if data.has_src(con) else "'signal'"
        q = (f"SELECT token, symbol, ts, {src}, score, json_extract(data, '$.zones.mc.range_low_low'), "
             "json_extract(data, '$.zones.mc.range_low_top'), json_extract(data, '$.zones.mc.range_high_low'), "
             "json_extract(data, '$.zones.mc.range_high_top'), json_extract(data, '$.zones.range_low'), "
             "json_extract(data, '$.metrics.supply'), json_extract(data, '$.span_h'), "
             "json_extract(data, '$.stop.mc') FROM ranges WHERE active = 1 AND ts >= ?")
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
                            (x.get("metrics") or {}).get("supply"), x.get("span_h"), (x.get("stop") or {}).get("mc")))
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


def position_tokens():
    """{token} with an open trade on the real Autopilot account (league.db trades, user trade.settings.LEAGUE_USER;
    the owner's manual HOPE position is one), read-only; set() on any error. The demo account (PAPER_USER) is not
    the real account: its tokens get no zones for it."""
    try:
        from rangedca import data
        from trade import settings
        con = data._league_ro()
    except Exception:  # noqa: BLE001
        return set()
    if con is None:
        return set()
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT token FROM trades WHERE user=? AND status='open'",
                                          (settings.LEAGUE_USER,)) if r[0]}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def range_zones(row, lot1_mc=None):
    """The range engine's zones of one active range, in market cap USD (rangedca/detect.py and rules.py):
        bottom   range_low_low .. range_low_top
        dca      lot 2 at -10 to -15 % under lot 1 (rules lot2_lo / lot2_hi): under the open round's lot 1 when there
                 is one, else under the middle of the bottom zone (range_low), never under the floor range_low_low x
                 0.92 (lot 2's own floor); left out when that leaves nothing
        top      range_high_low .. range_high_top (half out at range_high_low)
        stop     the range's hard stop (11.11., the owner's decision 1: the ATR stop, range_low_low - 1.5 x ATR,
                 5-20 % under it; ranges.data "stop"), range_low_low x 0.85 for a range computed before it; lo = hi
    [(zone_type, lo, hi)]; [] when the market caps are unknown (no supply)."""
    from rangedca import rules
    tok, sym, ts, src, score, rll, rlt, rhl, rht, rl_px, supply = row[:11]
    if not all(isinstance(v, (int, float)) and v > 0 for v in (rll, rlt, rhl, rht)):
        return []
    r = rules.RULES
    out = [("bottom", float(rll), float(rlt)), ("top", float(rhl), float(rht))]
    ref = lot1_mc or (rl_px * supply if rl_px and supply else (rll + rlt) / 2)
    d_hi = ref * (1 - r["lot2_lo"])
    d_lo = max(ref * (1 - r["lot2_hi"]), rll * r["floor_x"])
    if d_lo < d_hi:
        out.append(("dca", round(d_lo), round(d_hi)))
    sm = row[12] if len(row) > 12 else None
    stop = round(sm) if isinstance(sm, (int, float)) and 0 < sm < rll else round(rll * r["stop_x"])
    out.append(("stop", stop, stop))
    return out


def _entry_ready(now):
    """{token} of the active ranges an entry would pass now (rangedca/view: no breakout, entry_now passes); set() on
    any error (then only the open rounds, the positions and the hand-armed zones alarm)."""
    try:
        from rangedca import data, trade, view
        out = set()
        for tok, r in (data.read_ranges(since=now - trade.RANGE_FRESH_S) or {}).items():
            if not r.get("active") or view.is_breakout(r):
                continue
            if trade.entry_view(r, (r.get("metrics") or {}).get("price"), now) is None:
                out.add(tok)
        return out
    except Exception:  # noqa: BLE001
        return set()


def no_range_why(tokens, now, range_path=None):
    """{token: why it has no active range now} from range.db (read-only): never computed (rangedca does not follow
    it), the newest computation too old, or the range engine's own status and reason ("probijen gore: cijena iznad
    range_high_top × 1,15", "nema raspona: ...", "isključen: ...")."""
    from rangedca import data, trade
    tokens = sorted(tokens)
    if not tokens:
        return {}
    con = data.ro(range_path)
    if con is None:
        return {t: "range.db ne postoji (rangedca još nije računao raspone)" for t in tokens}
    out = {}
    try:
        for t in tokens:
            r = con.execute("SELECT ts, status, active, data FROM ranges WHERE token=?", (t,)).fetchone()
            if not r:
                out[t] = "rangedca nema izračun raspona za token (nije među kandidatima signalnog prolaza)"
                continue
            ts, status, active, d = r
            if now - (ts or 0) > trade.RANGE_FRESH_S:
                out[t] = f"raspon zastario: zadnji izračun prije {int((now - (ts or 0)) // 60)} min ({status or '?'})"
                continue
            try:
                why = (json.loads(d) or {}).get("why") if d else None
            except ValueError:
                why = None
            if active:   # active but no zone at or over 30k (or no supply): nothing to watch
                out[t] = "raspon bez zona u MC iznad 30k"
            else:
                out[t] = (status or "bez raspona") + (f": {why}" if why else "")
    except sqlite3.Error as e:
        for t in tokens:
            out.setdefault(t, f"range.db nije pročitan ({type(e).__name__})")
    finally:
        con.close()
    return out


def _why_key(w):
    """The part of a reason that names it ("slab volumen", "isključen", "raspon zastario"): what is logged once."""
    return (w or "").split(":")[0]


def _bump_versions(con, keep_ts, now):
    """range_ver: +1 for every token whose range computation (ranges.ts) is newer than the one read last time."""
    old = {m: (v, ts) for m, v, ts in con.execute("SELECT mint, zone_version, computed_ts FROM range_ver")}
    for tok, (ts, wh) in keep_ts.items():
        v, last = old.get(tok, (0, None))
        if last is None or int(ts) > int(last):
            con.execute("INSERT OR REPLACE INTO range_ver VALUES (?,?,?,?,?)",
                        (tok, int(v or 0) + 1, int(ts), None if wh is None else round(float(wh), 2), int(now)))


def versions(con, mints=None):
    """{mint: {"zone_version", "computed_ts", "window_h"}} of the tokens with range zones."""
    out = {}
    try:
        rows = con.execute("SELECT mint, zone_version, computed_ts, window_h FROM range_ver").fetchall()
    except sqlite3.Error:   # a zonewatch.db opened read-only before this job created the table
        return out
    for m, v, ts, wh in rows:
        if mints is None or m in mints:
            out[m] = {"zone_version": v, "computed_ts": ts, "window_h": wh}
    return out


def sync_range(con, now, rows=None, lot1=None, log=print, eligible=None, positions=None):
    """The range engine's active ranges -> armed_zones (source range): upsert their zones (expiring RANGE_FRESH_S +
    5 min after the range was computed, so a range the engine stops computing goes away by itself) and expire at once
    the range zones of tokens whose range is no longer active. Returns (tokens, zones written).
    11.11. (Jure): only tokens with an open range round, an entry-ready range or an open position on the real account
    (position_tokens) get range zones, and ONLY when rangedca has an active range for them: an eligible token without
    one gets no zones, and why goes to the log once (when it changes) and to kv range_why. eligible: that set
    (computed when rows are read here; None with given rows = no filter, for the callers that pass their own rows).
    Every newer range computation of a token with zones is a new zone_version (range_ver)."""
    from rangedca import trade
    read_here = rows is None
    reasons = {}
    if rows is None:
        rows = _range_rows(now)
        if eligible is None:
            lot1 = _open_lot1_mc() if lot1 is None else lot1
            positions = position_tokens() if positions is None else set(positions)
            ready = _entry_ready(now)
            for t in lot1:
                reasons.setdefault(t, []).append("otvorena runda")
            for t in ready:
                reasons.setdefault(t, []).append("entry_ready")
            for t in positions:
                reasons.setdefault(t, []).append("pozicija na pravom računu")
            eligible = set(lot1) | ready | positions
    lot1 = _open_lot1_mc() if lot1 is None else lot1
    keep, n, keep_ts = set(), 0, {}
    for row in rows:
        tok, sym, ts, src = row[0], row[1], int(row[2] or now), row[3] or "signal"
        if not tok or not MINT_RE.match(tok):
            continue
        if eligible is not None and tok not in eligible:
            continue
        sc = row[4]
        why = reasons.get(tok) or (["lot 1 otvoren"] if lot1.get(tok) else [])
        note = f"raspon {src}" + (f", ocjena {sc:.2f}" if isinstance(sc, (int, float)) else "") + \
            "".join(f", {w}" for w in why)
        wrote = False
        for zt, lo, hi in range_zones(row, lot1.get(tok)):
            if lo < MIN_MCAP:   # CLAUDE.md: nothing under 30k (a stop of a 32k floor at 27k is left out too)
                continue
            keep.add((tok, zt))
            wrote = True
            if upsert(con, tok, zt, lo, hi, note, "range", "range", ts + trade.RANGE_FRESH_S + 300, now, sym,
                      reset=False) != "unchanged":
                n += 1
        if wrote:
            keep_ts[tok] = (ts, row[11] if len(row) > 11 else None)
    _bump_versions(con, keep_ts, now)
    gone = [(m, zt) for m, zt in con.execute("SELECT mint, zone_type FROM armed_zones WHERE source='range' AND "
                                             "expires_at > ?", (int(now),)) if (m, zt) not in keep]
    for m, zt in gone:
        con.execute("UPDATE armed_zones SET expires_at=? WHERE mint=? AND zone_type=? AND source='range'", (int(now), m, zt))
    if eligible is not None:
        missing = {t for t in eligible if t not in keep_ts and MINT_RE.match(t or "")}
        whys = no_range_why(missing, now) if read_here else {t: "nema aktivnog raspona" for t in missing}
        said = kv_get(con, "range_why") or {}
        for t, w in sorted(whys.items()):
            if _why_key(said.get(t)) != _why_key(w):   # once per status, not on every changed number
                log(f"zonewatch: {t[:6]}… ({', '.join(reasons.get(t) or ['prati se'])}) bez zona: {w}")
        kv_put(con, "range_why", whys)
    con.commit()
    return len({t for t, _ in keep}), n
