"""Is every feed still flowing? (11.11., Jure: the wallet feed was empty for ~20 h and nobody noticed.)

check() runs with the 5-min tick: for every event type that is ACTIVE (at least ACTIVE_MIN events in the 7 days before
its newest event, about one an hour, so a type that is sparse by nature, e.g. trades on a quiet day, never alarms,
while a feed that stopped a day ago still does) and whose newest
event is older than GAP_MIN (60) minutes, while the clock in Zagreb is between 08 and 24, it records an alert:

  usage.db alerts (usage/watch.remember, key "events:gap:<type>", service "podaci"): the history on the Potrošnja
  page shows when it started and when it was last seen; the server log gets a line when an alert is new or got
  worse and once a day while it lasts (usage/watch.to_log); events.db kv "health" keeps the current list for
  get_hourly_brief. Outside 08-24 nothing is raised (a quiet night is normal), but a gap that started at night is
  raised at 08:00 if it still lasts.

gaps() answers "when was a feed empty" from the old table itself (hype.db chain_trades by its ts index), so the
question can be asked about days before events.db existed: python3 run_events.py gaps --hours 48
"""
import datetime as dt
import sqlite3
import time
from zoneinfo import ZoneInfo

from events import sources, store

TZ = "Europe/Zagreb"
WINDOW = (8, 24)        # [from, to) Zagreb hours in which a gap is raised
GAP_MIN = 60
ACTIVE_MIN = 7 * 24     # events in 7 days for a type to count as a feed that should not stop
SERVICE = "podaci"
NAMES = {"call": "pozivi (X/Telegram)", "wallet_buy": "kupnje praćenih novčanika", "wallet_sell": "prodaje praćenih "
         "novčanika", "transfer": "transferi novčanika", "x_post": "X objave", "price_tick": "cijene",
         "trade": "tradeovi Autopilota", "signal": "signali", "zone_alert": "zonski alarmi"}
NO_GAP = frozenset({"zone_alert"})   # 11.11.: alarms come when prices cross zones; an hour without one is normal
# 12.11. popodne (owner: "„Nema Autopilot trade eventa" nije rupa u feedu ako taj dan nije bilo tradeova"): a type whose
# silence is checked against its own source tables: a gap only when the source holds a row newer than the newest event
# (the sync missed it), never because nothing was traded
SOURCE_CHECKED = frozenset({"trade"})
SYNC_SLACK_S = 600      # the sync runs every 5 min: a source row this much newer than the newest event is a real gap
# 12.11. popodne (owner: "U health/feed-gap dodaj range_compute i range_numbers: last-write, starost, alert ako je
# computed_ts ili numbers_ts stariji od 8–10 min"): read from range.db (ranges.ts = computed_ts of the active ranges,
# data.mts = numbers_ts); both run day and night, so no Zagreb window
RANGE_GAP_MIN = 9.0
RANGE_TYPES = {"range_compute": "izračun raspona (computed_ts)", "range_numbers": "5-min brojke raspona (numbers_ts)"}
NAMES.update(RANGE_TYPES)


def in_window(now=None, window=WINDOW):
    h = dt.datetime.fromtimestamp(now or time.time(), ZoneInfo(TZ)).hour
    return window[0] <= h < window[1]


def status(econ, now=None):
    """[{type, last_ts, gap_min, n7d, active, sources: {source: last_ts}}] of every type, from the (type, ts) index.
    n7d is counted only up to ACTIVE_MIN (enough to know the type is a feed; the 5-min tick stays cheap), and the
    newest event per source is read only for a type that is silent longer than GAP_MIN."""
    now = int(now or time.time())
    out = []
    for t in store.TYPES:
        last = econ.execute("SELECT MAX(ts) FROM events WHERE type = ?", (t,)).fetchone()[0]
        # the 7 days BEFORE the newest event: a feed that went silent 20 h ago is still a feed that should flow
        n7 = econ.execute("SELECT COUNT(*) FROM (SELECT 1 FROM events WHERE type = ? AND ts >= ? LIMIT ?)",
                          (t, (last or 0) - 7 * 86400 * 1000, ACTIVE_MIN)).fetchone()[0] if last else 0
        gap = round((now - last / 1000) / 60, 1) if last else None
        by = {}
        if last and gap > GAP_MIN:
            for s, ts in econ.execute("SELECT source, MAX(ts) FROM events WHERE type = ? AND ts >= ? GROUP BY source",
                                      (t, last - 7 * 86400 * 1000)):
                by[s or "?"] = int(ts // 1000)
        out.append({"type": t, "last_ts": int(last // 1000) if last else None, "gap_min": gap, "n7d": int(n7 or 0),
                    "active": n7 >= ACTIVE_MIN, "sources": by})
    return out


def source_newest(t, paths=None):
    """The newest row time (unix s) of the sources that write type t (events/sources.Source), None if unreadable."""
    best = None
    try:
        p = paths or sources.paths()
        for src in sources.sources():
            if t not in src.types:
                continue
            con = sources._ro(p.get(src.db))
            if con is None:
                continue
            try:
                where = f" WHERE {src.where}" if src.where else ""
                v = con.execute(f"SELECT MAX({src.ts}) FROM {src.table}{where}").fetchone()[0]
            except sqlite3.Error:
                v = None
            finally:
                con.close()
            if v is not None:
                v = int(v / 1000) if v > 10**11 else int(v)   # ms or s
                best = v if best is None else max(best, v)
    except Exception:  # noqa: BLE001 - unknown: the caller treats it as "no proof of a gap"
        return None
    return best


def range_status(now=None, path=None):
    """[{type: range_compute | range_numbers, last_ts, gap_min, active, n_active, sources}] from range.db; [] when the
    range job is off (no range.db or no active range)."""
    now = int(now or time.time())
    try:
        from rangedca import data
        con = data.ro(path)
    except Exception:  # noqa: BLE001
        return []
    if con is None:
        return []
    try:
        n, comp, nums = con.execute("SELECT COUNT(*), MAX(ts), MAX(CAST(json_extract(data, '$.mts') AS INTEGER)) "
                                    "FROM ranges WHERE active = 1").fetchone()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    if not n:
        return []
    out = []
    for t, last in (("range_compute", comp), ("range_numbers", nums or comp)):
        last = int(last) if last else None
        out.append({"type": t, "last_ts": last, "gap_min": round((now - last) / 60, 1) if last else None,
                    "active": True, "n_active": int(n), "sources": {}})
    return out


RECENT_MIN = 15
RECENT_TYPES = ("price_tick", "transfer")
RECENT_WORDS = {"price_tick": "cijene", "transfer": "transferi"}


def recent_counts(econ, now=None, minutes=RECENT_MIN, types=RECENT_TYPES):
    """{type: events whose time is in the last `minutes`} from the (type, ts) index. 12.11. (owner, nalog 3: "potvrdi da
    price_tick i transfer događaji ponovno pišu nakon PR #149 (broj događaja u zadnjih 15 min)"): the sync line counts
    only what the sync itself added (kol/snap and the Helius webhook write their rows directly, events/hooks.py), so
    the 5-min tick also logs these counts, whoever wrote the rows."""
    since = (int(now or time.time()) - int(minutes * 60)) * 1000
    return {t: int(econ.execute("SELECT COUNT(*) FROM events WHERE type = ? AND ts >= ?", (t, since)).fetchone()[0])
            for t in types}


def recent_text(counts, minutes=RECENT_MIN):
    """"zadnjih 15 min: cijene 812, transferi 37" for the tick's log line."""
    return f"zadnjih {minutes} min: " + ", ".join(f"{RECENT_WORDS.get(t, t)} {n}" for t, n in counts.items())


def _hhmm(ts):
    return dt.datetime.fromtimestamp(ts, ZoneInfo(TZ)).strftime("%d.%m. %H:%M")


def alerts_for(st, now=None, window=WINDOW, gap_min=GAP_MIN, newest=None):
    """The alerts of a status() list (pure: the tests give it any clock). newest: {type: the source's newest row} for
    SOURCE_CHECKED types (check() reads it); range_* types use RANGE_GAP_MIN at any hour."""
    now = int(now or time.time())
    day = in_window(now, window)
    out = []
    for s in st:
        if s["type"] in NO_GAP:
            continue
        rng = s["type"] in RANGE_TYPES
        if not rng and not day:
            continue
        limit = RANGE_GAP_MIN if rng else gap_min
        if not s["active"] or s["last_ts"] is None or s["gap_min"] is None or s["gap_min"] <= limit:
            continue
        if s["type"] in SOURCE_CHECKED:
            src = (newest or {}).get(s["type"])
            if src is None or src <= s["last_ts"] + SYNC_SLACK_S:
                continue   # nothing newer in the source: no trades, not a gap
        if rng:
            name = NAMES.get(s["type"], s["type"])
            out.append({"key": f"range:gap:{s['type']}", "service": SERVICE, "level": "bad" if s["gap_min"] >= 30
                        else "warn", "type": s["type"], "gap_min": s["gap_min"], "last_ts": s["last_ts"],
                        "title": f"Raspon: {name} star {s['gap_min']:.0f} min",
                        "detail": f"Zadnji upis {_hhmm(s['last_ts'])} (Zagreb), aktivnih raspona {s.get('n_active')}; "
                                  f"prag {RANGE_GAP_MIN:g} min (posao radi svakih ~5 min)."})
            continue
        hours = s["gap_min"] / 60
        name = NAMES.get(s["type"], s["type"])
        src = ", ".join(f"{k} {_hhmm(v)}" for k, v in sorted(s["sources"].items(), key=lambda x: -x[1]))
        out.append({"key": f"events:gap:{s['type']}", "service": SERVICE, "level": "bad" if hours >= 6 else "warn",
                    "type": s["type"], "gap_min": s["gap_min"], "last_ts": s["last_ts"],
                    "title": f"Nema događaja: {name} već {hours:.1f} h" if hours >= 2 else
                             f"Nema događaja: {name} već {s['gap_min']:.0f} min",
                    "detail": f"Zadnji događaj {_hhmm(s['last_ts'])} (Zagreb); po izvoru: {src or '-'}. Tip je aktivan "
                              f"(barem {ACTIVE_MIN} događaja u 7 dana prije zadnjeg), provjera radi od "
                              f"{window[0]:02d} do {window[1]:02d} h."})
    return out


def record(alerts, now=None, log=print, usage_db=None):
    """Into usage.db alerts (the history on the Potrošnja page) and the log (new, worse, or once a day)."""
    if not alerts:
        return 0
    try:
        from usage import meter, watch
        con = meter.connect(usage_db)
        try:
            watch.remember(con, alerts, now)
            for a in watch.to_log(con, alerts, now):
                log(f"UPOZORENJE podaci: {a['title']}. {a['detail']}")
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 - the alert still goes to the log
        for a in alerts:
            log(f"UPOZORENJE podaci: {a['title']} ({type(e).__name__} pri upisu u usage.db)")
    return len(alerts)


def check(econ=None, now=None, log=print, usage_db=None):
    """status + alerts; stores {"ts", "alerts", "status"} in events.db kv "health" for the brief. Returns alerts."""
    now = int(now or time.time())
    own = econ is None
    econ = econ or store.connect()
    try:
        st = status(econ, now) + range_status(now)
        newest = {t: source_newest(t) for t in SOURCE_CHECKED
                  if any(x["type"] == t and x["gap_min"] and x["gap_min"] > GAP_MIN for x in st)}
        al = alerts_for(st, now, newest=newest)
        record(al, now, log, usage_db)
        store.kv_put(econ, "health", {"ts": now, "alerts": al, "status": st})
        econ.commit()
        return al
    finally:
        if own:
            econ.close()


def latest(econ=None, max_age_s=1800):
    """The last check's alerts for get_hourly_brief ([] when the check is older than max_age_s)."""
    own = econ is None
    econ = econ or store.ro()
    if econ is None:
        return {"ts": None, "alerts": [], "note": "events.db još ne postoji"}
    try:
        h = store.kv_get(econ, "health") or {}
    finally:
        if own:
            econ.close()
    if not h or time.time() - (h.get("ts") or 0) > max_age_s:
        return {"ts": h.get("ts"), "alerts": [], "note": "provjera zdravlja nije radila zadnjih 30 min"}
    return {"ts": h.get("ts"), "alerts": h.get("alerts") or []}


def gaps(hours=48, now=None, min_gap_min=GAP_MIN, paths=None):
    """{"wallet_feed": [(from_ts, to_ts, minutes)], "calls": [...]} longest silences of the old tables in the last
    `hours` (chain_trades and kol.db calls by their ts indexes; the last row of each list may run up to now)."""
    now = int(now or time.time())
    since = now - int(hours * 3600)
    paths = paths or sources.db_paths()
    out = {}
    for name, db, sql in (("wallet_feed", "hype", "SELECT ts FROM chain_trades WHERE ts >= ? ORDER BY ts"),
                          ("wallet_feed_buys", "hype", "SELECT ts FROM chain_trades WHERE ts >= ? AND side = 'buy' "
                                                       "ORDER BY ts"),
                          ("calls", "kol", "SELECT ts FROM calls WHERE ts >= ? AND kind = 'call' ORDER BY ts")):
        con = sources._ro(paths.get(db))
        if con is None:
            continue
        try:
            ts = [int(r[0]) for r in con.execute(sql, (since,)) if r[0]]
        except sqlite3.Error:
            continue
        finally:
            con.close()
        prev, found = since, []
        for t in ts + [now]:
            if t - prev > min_gap_min * 60:
                found.append((prev, t, round((t - prev) / 60)))
            prev = max(prev, t)
        out[name] = sorted(found, key=lambda g: -g[2])
    return out
