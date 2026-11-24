"""events.db: one row per thing that happened, whatever collector saw it.

    events   id, ts (UTC milliseconds), slot, mint, type, source, actor, sol_amount, mcap_usd, payload (JSON text), uid
      type     call | wallet_buy | wallet_sell | transfer | x_post | price_tick | trade | signal
      source   x | telegram | helius | pumpportal | dexscreener | autopilot | grok | scan | groups
      actor    caller handle (X) / tg:<channel> / wallet / X handle / account / flag; NULL for a price
      uid      63-bit hash of the source row's own key (tweet+token, signature+mint, mint+minute ...): a collector's
               direct write and the 5-min sync of the same row are one event (INSERT OR IGNORE), and a re-run of the
               backfill adds nothing
    indexes  (mint, ts), (actor, ts), (type, ts), uid unique; mint and actor partial (a price tick has no actor:
             no index entry for it, ~10 % of a price row)

Who writes: the collectors through emit() (dual write next to their own tables) and run_events.py (the sync every
5 min, the backfill, the night batch). emit() never blocks and never raises: rows go to an in-memory queue and a
daemon thread writes them every second with a short busy timeout; when that fails the rows stay queued (bounded)
and the 5-min sync fills whatever was lost from the old tables. A collector can therefore never be broken or slowed
by events.db. emit() writes only into an events.db that already exists (start.sh touches it on the data disk), so a
checkout without it (the test suite of the other modules) writes nothing.

Retention: price_tick 30 days (older than PRICE_THIN_D days thinned to one per mint per 5 min), everything else 90
days (EVENTS_KEEP_<TYPE>_D overrides). Disk budget: events.db holding more than EVENTS_MAX_MB (600), or the data disk
under EVENTS_MIN_FREE_MB (600) free, cuts price ticks and transfers first (to 7 days at most), then the wallet feed (to
EVENTS_WALLET_FLOOR_D, 7 days, at most), logged; only while the DISK is tight emit() and the sync skip price ticks and
transfers (12.11.: an events.db over its budget no longer stops the live feeds).
"""
import atexit
import collections
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TYPES = ("call", "wallet_buy", "wallet_sell", "transfer", "x_post", "price_tick", "trade", "signal")
# 11.11. (zonewatch/): every zone alarm sent (or meant) for Grok Bot, source zonewatch, the alarm JSON as payload
TYPES += ("zone_alert",)
LOW_VALUE = ("price_tick", "transfer")   # cut first when the disk is tight
DAY = 86400
H = 3600


def _env_num(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return float(default)


MAX_MB = _env_num("EVENTS_MAX_MB", 600)
MIN_FREE_MB = _env_num("EVENTS_MIN_FREE_MB", 600)
# 13.11. (owner: "NE zaustavljaj price/transfer feedove dok disk stvarno nije pun"): the live feeds stop only under
# this much free disk (with the pages SQLite reuses); MIN_FREE_MB (600) only makes the retention cut the cheap copies.
# The night of 12./13.11. had 350-440 MB free for hours and the price / transfer events stopped for that time.
FEED_MIN_FREE_MB = _env_num("EVENTS_FEED_MIN_FREE_MB", 150)
# 13.11. (owner: "NE briši vlasnikove tradeove iz events.db; tuđe tradeove u events.db drži na 7 dana (originali ostaju u
# hype.db i wallets.db)"): our own trades (type "trade": Autopilot / demo and real positions) are never deleted; the
# followed wallets' trades (copies) keep WALLET_FLOOR_D days
NEVER_DELETE = ("trade",)
PRICE_THIN_D = _env_num("EVENTS_PRICE_THIN_D", 3)
WALLET_FLOOR_D = _env_num("EVENTS_WALLET_FLOOR_D", 7)   # 12.11.: was 30; the wallet feed's copies, see retention()
BACKFILL_FILL = 0.8   # 12.11.: the night's backfill stops once events.db's pages in use reach this share of MAX_MB
MIN_MCAP = 30_000   # CLAUDE.md: tokens under 30k are not analysed; their price ticks are not kept

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, slot INTEGER, mint TEXT, type TEXT NOT NULL, source TEXT,
    actor TEXT, sol_amount REAL, mcap_usd REAL, payload TEXT, uid INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS events_uid ON events (uid);
CREATE INDEX IF NOT EXISTS events_mint_ts ON events (mint, ts) WHERE mint IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_actor_ts ON events (actor, ts) WHERE actor IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_type_ts ON events (type, ts);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS sizes (day TEXT PRIMARY KEY, ts INTEGER, bytes INTEGER, rows INTEGER, by_type TEXT,
    free_mb REAL);
CREATE TABLE IF NOT EXISTS call_outcomes (
    uid INTEGER PRIMARY KEY, kind TEXT, mint TEXT, actor TEXT, source TEXT, ts INTEGER, tweet_id TEXT,
    mcap0 REAL, entry REAL, max_1h REAL, max_4h REAL, max_24h REAL, min_before_max REAL, change_4h REAL,
    change_24h REAL, ev REAL, status TEXT, reason TEXT, src TEXT, measured_ts INTEGER);
CREATE INDEX IF NOT EXISTS call_outcomes_actor ON call_outcomes (actor, ts);
CREATE INDEX IF NOT EXISTS call_outcomes_mint ON call_outcomes (mint, ts);
CREATE INDEX IF NOT EXISTS call_outcomes_status ON call_outcomes (status, ts);
CREATE INDEX IF NOT EXISTS call_outcomes_tweet ON call_outcomes (tweet_id);
CREATE TABLE IF NOT EXISTS scores (
    kind TEXT, actor TEXT, n INTEGER, n_measured INTEGER, hits INTEGER, hit_rate REAL, median_max_4h REAL,
    median_max_24h REAL, ev REAL, last_ts INTEGER, updated INTEGER, PRIMARY KEY (kind, actor));
CREATE TABLE IF NOT EXISTS early_wallets (
    wallet TEXT PRIMARY KEY, n_early INTEGER, n_wins INTEGER, win_rate REAL, median_lead_min REAL, source TEXT,
    last_ts INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS pools (token TEXT PRIMARY KEY, pool TEXT, supply REAL, ts INTEGER);
CREATE TABLE IF NOT EXISTS ev_report (
    day TEXT, flag TEXT, phase TEXT, part TEXT, n INTEGER, n_outcomes INTEGER, hit_rate REAL, avg_pnl_pct REAL,
    ev_pct REAL, max_dd_pct REAL, baseline_ev_pct REAL, baseline_n INTEGER, delta_ev_pct REAL, proposal TEXT,
    note TEXT, created INTEGER, PRIMARY KEY (day, flag, part));
"""


def db_path():
    """events.db on the persistent disk: EVENTS_DB, else DATA_DIR (Render /var/data), else the repo folder (start.sh
    symlinks that one to the disk, like scan.db)."""
    if os.environ.get("EVENTS_DB"):
        return os.environ["EVENTS_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "events.db")
    return os.path.join(ROOT, "events.db")


def connect(path=None, timeout=30, shared=False):
    """shared=True: the one connection of emit()'s writer, used by the writer thread and by an exit flush in the main
    thread (always under _LOCK, so one thread at a time)."""
    con = sqlite3.connect(path or db_path(), timeout=timeout, check_same_thread=not shared)
    try:
        con.execute("PRAGMA journal_mode=WAL")   # readers (the MCP brief) never wait for the writer
    except sqlite3.Error:
        pass
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only handle; None while events.db does not exist or is empty."""
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("SELECT 1 FROM events LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def uid(key):
    """63-bit positive integer of a row key (blake2b): 8 bytes in the unique index instead of an 88-char signature."""
    return int.from_bytes(hashlib.blake2b(str(key).encode(), digest_size=8).digest(), "big") >> 1


def ms(ts):
    """Seconds or milliseconds -> integer UTC milliseconds."""
    ts = float(ts)
    return int(ts if ts > 1e12 else ts * 1000)


def _payload(p):
    if p is None:
        return None
    if isinstance(p, str):
        return p
    return json.dumps({k: v for k, v in p.items() if v is not None}, separators=(",", ":"), ensure_ascii=False,
                      default=str) or None


def row(type_, ts, mint=None, source=None, actor=None, sol=None, mcap=None, payload=None, slot=None, key=None):
    """One events row as the INSERT takes it: (ts, slot, mint, type, source, actor, sol_amount, mcap_usd, payload,
    uid). key: the source row's own key (uid); None = a key from type, ts, mint and actor."""
    if type_ not in TYPES:
        raise ValueError(f"unknown event type {type_}")
    t = ms(ts)
    k = key if key is not None else f"{type_}|{t}|{mint}|{actor}"
    return (t, slot, mint, type_, source, actor, None if sol is None else float(sol),
            None if mcap is None else float(mcap), _payload(payload), uid(k))


def insert(con, rows):
    """INSERT OR IGNORE the rows; returns how many were new."""
    if not rows:
        return 0
    before = con.total_changes
    con.executemany("INSERT OR IGNORE INTO events (ts, slot, mint, type, source, actor, sol_amount, mcap_usd, payload, "
                    "uid) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return con.total_changes - before


# ---------- kv: watermarks and last runs ----------------------------------------------------------------------------

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
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v)))


# ---------- the disk guard ------------------------------------------------------------------------------------------

def size_mb(path=None):
    path = path or db_path()
    total = 0
    for p in (path, path + "-wal"):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total / 1e6


def free_mb(path=None):
    try:
        import shutil
        return shutil.disk_usage(os.path.dirname(os.path.realpath(path or db_path())) or ".").free / 1e6
    except OSError:
        return None


def used_mb(con=None, path=None):
    """MB of events.db that hold data (pages minus the free list): a DELETE frees pages for reuse without shrinking
    the file, so the budget is measured on this, not on the file size. (used, free-list) in MB."""
    own = con is None
    try:
        con = con or sqlite3.connect(f"file:{path or db_path()}?mode=ro", uri=True, timeout=2)
        pc, fl, ps = (con.execute(f"PRAGMA {k}").fetchone()[0] for k in ("page_count", "freelist_count", "page_size"))
        return (pc - fl) * ps / 1e6, fl * ps / 1e6
    except sqlite3.Error:
        return size_mb(path), 0.0
    finally:
        if own and con is not None:
            con.close()


def over_budget(con=None, path=None):
    """events.db holds more than MAX_MB, or the disk (with the pages SQLite will reuse) has under MIN_FREE_MB free."""
    used, reusable = used_mb(con, path)
    free = free_mb(path)
    return used > MAX_MB or (free is not None and free + reusable < MIN_FREE_MB)


_TIGHT = {"at": 0.0, "val": False}


def disk_tight(path=None):
    """The data disk (with the pages SQLite will reuse) has under FEED_MIN_FREE_MB free (13.11.: was MIN_FREE_MB)."""
    used, reusable = used_mb(None, path)
    free = free_mb(path)
    return free is not None and free + reusable < FEED_MIN_FREE_MB


def checkpoint(con, mode="PASSIVE"):
    """13.11.: a WAL checkpoint during and after a big write (retention, the night batch). The night of 12./13.11.
    events.db's WAL grew by ~460 MB in the night batch and hype.db's by ~480 MB in the live_trades deletion (the
    readers keep old snapshots, so the WAL cannot restart) until the hourly upkeep cut it back; with 350 MB free.
    PASSIVE never waits; TRUNCATE (at the end) waits up to the connection's busy timeout. Never raises."""
    try:
        return con.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
    except sqlite3.Error:
        return None


def tight(path=None):
    """True while the DISK is tight (checked every 60 s): price ticks and transfers are then not written.
    12.11. (owner: "price-tick i wallet-transfer feedovi nemaju događaja od 03:34"): an events.db above MAX_MB no longer
    stops the live feeds (the night's backfill had filled it with 14 days of copied wallet trades and the feeds stayed
    off all day); retention brings the file back under MAX_MB by cutting the copies instead."""
    now = time.monotonic()
    if now - _TIGHT["at"] > 60:
        p = path or db_path()
        _TIGHT.update(at=now, val=bool(os.path.exists(p) and os.path.getsize(p) and disk_tight(path=p)))
    return _TIGHT["val"]


# ---------- emit(): the collectors' side of the dual write ---------------------------------------------------------

QUEUE_MAX = 50_000
_Q = collections.deque(maxlen=QUEUE_MAX)
_LOCK = threading.Lock()
_STATE = {"thread": None, "fails": 0, "last_log": 0.0, "exists_at": 0.0, "exists": False, "path": None, "con": None}
FLUSH_S = 1.0
WRITE_TIMEOUT_S = 2.0


def _on():
    """emit() writes only while events.db exists (checked every 30 s) and EVENTS_OFF is not set."""
    if os.environ.get("EVENTS_OFF") == "1":
        return False
    path = db_path()
    now = time.monotonic()
    if path != _STATE["path"] or now - _STATE["exists_at"] > 30:
        _STATE.update(path=path, exists_at=now, exists=os.path.exists(path))
    return _STATE["exists"]


def _log_fail(e):
    _STATE["fails"] += 1
    now = time.time()
    if now - _STATE["last_log"] > 60:
        _STATE["last_log"] = now
        print(f"događaji: upis u events.db nije uspio ({type(e).__name__}: {e}); {len(_Q)} redaka čeka, "
              "5-minutna sinkronizacija nadoknađuje", file=sys.stderr, flush=True)


def emit(type_, ts, mint=None, source=None, actor=None, sol=None, mcap=None, payload=None, slot=None, key=None):
    """Queue one event for events.db. Never raises, never waits on the database."""
    try:
        if not _on():
            return False
        if type_ in LOW_VALUE and tight():
            return False
        if type_ == "price_tick" and mcap is not None and mcap < MIN_MCAP:
            return False
        _Q.append(row(type_, ts, mint, source, actor, sol, mcap, payload, slot, key))
        _start()
        return True
    except Exception as e:  # noqa: BLE001 - the collector must never notice
        _log_fail(e)
        return False


def emit_rows(rows):
    """Queue rows built with row() (several at once)."""
    try:
        if not rows or not _on():
            return 0
        _Q.extend(rows)
        _start()
        return len(rows)
    except Exception as e:  # noqa: BLE001
        _log_fail(e)
        return 0


def flush(path=None, timeout=WRITE_TIMEOUT_S):
    """Write what is queued now. Returns rows written; on a locked or missing file the rows stay queued."""
    with _LOCK:
        if not _Q:
            return 0
        batch = [_Q.popleft() for _ in range(min(len(_Q), 5000))]
        try:
            target = path or db_path()
            if not os.path.exists(target):
                return 0   # removed meanwhile: nothing to write into (the rows are dropped, the sync refills)
            con = _STATE["con"]
            if con is None or _STATE.get("con_path") != target:
                if con is not None:
                    con.close()
                con = connect(target, timeout=timeout, shared=True)
                _STATE.update(con=con, con_path=target)
            n = insert(con, batch)
            con.commit()
            _STATE["fails"] = 0
            return n
        except Exception as e:  # noqa: BLE001
            _Q.extendleft(reversed(batch))   # bounded: beyond QUEUE_MAX the oldest fall out (the sync refills them)
            try:
                if _STATE["con"] is not None:
                    _STATE["con"].close()
            except Exception:  # noqa: BLE001
                pass
            _STATE["con"] = None
            _log_fail(e)
            return 0


def _loop():
    while True:
        time.sleep(FLUSH_S)
        try:
            while _Q and flush():
                pass
        except Exception as e:  # noqa: BLE001 - the writer thread never dies
            _log_fail(e)


def _start():
    t = _STATE["thread"]
    if t is None or not t.is_alive():
        with _LOCK:
            t = _STATE["thread"]
            if t is None or not t.is_alive():
                t = threading.Thread(target=_loop, name="events-writer", daemon=True)
                t.start()
                _STATE["thread"] = t


@atexit.register
def _at_exit():
    try:   # a short-lived process (a KOL round) writes its queue before it ends; a locked file is not waited for long
        for _ in range(10):
            if not _Q or not flush():
                break
    except Exception:  # noqa: BLE001
        pass


# ---------- retention and the size log ------------------------------------------------------------------------------

def keep_days(type_):
    if type_ in ("wallet_buy", "wallet_sell"):   # 13.11. (owner): the followed wallets' trades, 7 days
        return _env_num(f"EVENTS_KEEP_{type_.upper()}_D", WALLET_FLOOR_D)
    default = 30 if type_ == "price_tick" else 90
    return _env_num(f"EVENTS_KEEP_{type_.upper()}_D", _env_num("EVENTS_KEEP_D", default) if type_ != "price_tick"
                    else default)


def retention(con, now=None, log=print, batch=20_000):
    """Delete what is past its type's retention (in batches, a commit each), thin old price ticks to one per mint per
    5 min, and when events.db is still over MAX_MB (or the disk under MIN_FREE_MB) cut price ticks, then transfers,
    a week at a time. Returns {type: rows deleted}."""
    now = int(now or time.time())
    out = collections.Counter()

    def _delete(where, args, label):
        k = 0
        while True:
            n = con.execute(f"DELETE FROM events WHERE id IN (SELECT id FROM events WHERE {where} LIMIT {batch})",
                            args).rowcount
            con.commit()
            out[label] += n
            k += 1
            if k % 5 == 0:
                checkpoint(con)   # 13.11.: keep the WAL from growing by the whole deletion
            if n < batch:
                break

    for t in TYPES:
        if t in NEVER_DELETE:
            continue
        _delete("type = ? AND ts < ?", (t, (now - int(keep_days(t) * DAY)) * 1000), t)
    # one price per mint per 5 min after PRICE_THIN_D days: the rest keeps the minute
    lo, hi = (now - int(keep_days("price_tick") * DAY)) * 1000, (now - int(PRICE_THIN_D * DAY)) * 1000
    done_to = kv_get(con, "thinned_to", 0) or 0
    if hi > done_to:
        start = max(lo, done_to)
        n = con.execute("""DELETE FROM events WHERE type = 'price_tick' AND ts >= ? AND ts < ? AND id NOT IN (
            SELECT MIN(id) FROM events WHERE type = 'price_tick' AND ts >= ? AND ts < ? GROUP BY mint, ts / 300000)""",
                        (start, hi, start, hi)).rowcount
        kv_put(con, "thinned_to", hi)
        con.commit()
        out["price_tick (prorijeđeno)"] += n
    # over budget: cut the cheapest types a week at a time (never below 7 days), then the wallet feed (12.11.: never
    # below WALLET_FLOOR_D, 7 days: it is a copy of hype.db chain_trades / wallets.db wallet_trades, which keep the
    # history; the trades of our own accounts are type "trade" and never cut here); measured on the pages in use
    for types, floor in ((LOW_VALUE, 7), (("wallet_sell", "wallet_buy"), WALLET_FLOOR_D)):
        for t in types:
            days = keep_days(t)
            while over_budget(con) and days > floor:
                days = max(floor, days - 7)
                before = out[t]
                _delete("type = ? AND ts < ?", (t, (now - int(days * DAY)) * 1000), t)
                if out[t] != before:
                    log(f"događaji: events.db preko budžeta ({used_mb(con)[0]:.0f} MB / {MAX_MB:.0f} MB): {t} "
                        f"skraćeno na {days:.0f} d")
    try:
        if con.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:   # incremental (ops/dbs): give freed pages back
            con.execute("PRAGMA incremental_vacuum")
    except sqlite3.Error:
        pass
    checkpoint(con, "TRUNCATE")
    return {k: v for k, v in out.items() if v}


def log_size(con, now=None, log=print):
    """One row a day in sizes (file size, rows per type, free disk) and one log line."""
    now = int(now or time.time())
    import datetime as dt
    day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
    by = dict(con.execute("SELECT type, COUNT(*) FROM events GROUP BY type").fetchall())
    rows = sum(by.values())
    b = int(size_mb() * 1e6)
    free = free_mb()
    con.execute("INSERT OR REPLACE INTO sizes VALUES (?,?,?,?,?,?)", (day, now, b, rows, json.dumps(by), free))
    con.commit()
    prev = con.execute("SELECT bytes FROM sizes WHERE day < ? ORDER BY day DESC LIMIT 1", (day,)).fetchone()
    growth = f", {(b - prev[0]) / 1e6:+.1f} MB od jučer" if prev else ""
    log(f"događaji: events.db {b / 1e6:.1f} MB{growth}, {rows} redaka ("
        + ", ".join(f"{k} {v}" for k, v in sorted(by.items(), key=lambda x: -x[1])) + ")"
        + (f", disk slobodno {free:.0f} MB" if free is not None else ""))
    return {"day": day, "bytes": b, "rows": rows, "by_type": by, "free_mb": free}
