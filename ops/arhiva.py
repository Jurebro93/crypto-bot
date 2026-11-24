"""Archive of microcap and rug data (15.11., Jure: "Makni mikrokapove i rugove i sve njihove povijesne podatke iz baze
... one koji su od početka zadržali volumen, njih zadrži"; asked delete or archive: "Arhiviraj onda dok ima prostora na
disku"). Nothing is destroyed: the rows of such a token move from the live databases into gzipped SQLite files on the
data disk (DATA_DIR/archive/<db>/<table>_<YYYYMMDD>.sqlite.gz, the same table schema) and only then leave the live
table; `python3 run_arhiva.py vrati <db> <table> [--date YYYYMMDD]` puts them back.

Owner switch arhiva_mikrokapova (trade/settings OWNER_SWITCHES, "uživo" = on, by his order 15.11.): on = at night the
rows move; any other mode = the plan only (log + output/arhiva_plan.md), nothing moves (dry run).

When: start.sh calls `run_arhiva.py --auto` every 30 min at low priority (the CPU guard may pause it, ops/cpuguard
"arhiva"); it works only inside the heavy-job night window (ops/heavy.NIGHT, 01-06 Zagreb), starts no new table after
UNTIL (05:40), takes the heavy-job lock per step (classification, then each table: the other night jobs interleave),
and finishes a night's work once (state DATA_DIR/.arhiva.json); a night cut short (window, disk, a locked database)
goes on the next night.

Which tokens (one verdict per mint for every table, archive/arhiva_stanje.sqlite verdict):
  KEEP (never archived)
    - every token of trade.db (real orders, positions, exits, critic verdicts, assistant notes; not its logs of
      refused / shown tokens, KEEP_WHOLE_SKIP), of veliki.db (the
      midcap list and its history), midcap.db tokens (the 2-200M collector, veliki/midcap.py), konsenzus.db,
      oscilator.db, izlazi.db; dugo.db tokens (the long-term list)
    - open positions anywhere (league / paper / koltest / strat / range / fast / momentum / proposals: a token column
      and status 'open'), every league.db trade and real_trade of the owner (his manual trades), exit and DCA plans
    - last known MC >= KEEP_MC (2M) in our own data, or MC >= KEEP_MC now (DexScreener /tokens batch, free, 30 mints
      a request, DEX_PER_MIN, at most DEX_MAX mints a night, cached DEX_TTL_D days; a mint not checked yet waits)
    - "kept its volume from the start" (KEEP_VOL_*): our own daily volume (range.db snaps, hype.db token_pulse,
      kol.db snaps: 24 x the day's mean 1 h volume; hype.db token_status: GeckoTerminal 24 h) >= $50k on >= 80 % of the days since we first saw it,
      and still trading now (DexScreener 24 h volume >= $50k, or our own last day within 2 days >= $50k)
    - first seen less than MIN_AGE_D days ago (its outcome is not known yet)
  ARCHIVE  everything else of a mint that is a microcap (last MC < KEEP_MC: DexScreener now when checked, else our
    newest snapshot) or rugged / dead (hype.db rug_archive and not rug_recovered, no DexScreener pair any more, or 24 h
    volume < DEAD_VOL_USD on each of the last DEAD_DAYS days we measured)
  Never touched: trade.db, league.db, veliki / midcap / konsenzus / oscilator / izlazi / critic, the rug archive list
  (hype.db rug_archive and its label tables: the bot needs it to never buy them again), the rug filter's rejections
  (rug.db rug_reports ODBAČEN / VISOK RIZIK), open demo trades (paper.db trades status open), settings / kv / state
  tables, every table without a token column (listed in the plan).

How one table moves (copy -> verify -> gzip -> verify -> delete):
  1. disk guard: free >= max(MIN_FREE_B, FREE_X x table size), else "arhiva: stala, premalo prostora (...)" and the
     night stops; a database another process keeps write-locked longer than BUSY_S is left for the next night
  2. the rows (rowid batches of BATCH) copied into archive/<db>/<table>_<date>.sqlite, the same CREATE TABLE, with the
     source rowid; a sha256 over (rowid, columns) of what was read
  3. verify: the archive file reopened, quick_check, row count and sha256 must match; else nothing is deleted
  4. gzip (streamed, 1 MB chunks), then the .gz decompressed (streamed) and its sha256 compared with the file's;
     else nothing is deleted
  5. delete in batches (BEGIN IMMEDIATE, a WAL checkpoint and PAUSE_S between batches): only rows whose every column
     still equals the archived copy (a row changed since the copy stays live and goes another night)
  6. per database at the end: PRAGMA incremental_vacuum (auto_vacuum files), then VACUUM (ops/dbs.compact) only when
     free >= VACUUM_X x the file's size
Logs: "arhiva: plan ...", per table "arhiva: hype.db hype_snapshots: premješteno N redaka (X MB → arhiva Y MB gz),
ostaje M", at the end "arhiva: oslobođeno Z MB, disk slobodno W GB".
"""
import datetime as dt
import glob
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.request

from ops import disk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D, H = 86400, 3600
SWITCH = "arhiva_mikrokapova"
KEEP_MC = float(os.environ.get("ARHIVA_KEEP_MC", "2000000"))
# "kept its volume from the start" (the owner's words), from our own snapshots
KEEP_VOL_USD = float(os.environ.get("ARHIVA_KEEP_VOL_USD", "50000"))   # 24 h volume of a good day
KEEP_VOL_SHARE = float(os.environ.get("ARHIVA_KEEP_VOL_SHARE", "0.80"))  # share of days since first seen
KEEP_VOL_RECENT_D = 2          # "still trading now" from our own data: a good day this recent
DEAD_VOL_USD, DEAD_DAYS = 1000.0, 3   # "volume ~0 for days"
MIN_AGE_D = float(os.environ.get("ARHIVA_MIN_AGE_D", "3"))
MIN_FREE_B = float(os.environ.get("ARHIVA_MIN_FREE_GB", "1")) * 1e9
FREE_X = 2.0                   # free space before a table >= this x the table's size
VACUUM_X = 1.2                 # VACUUM a database only with free >= this x its size
BATCH = int(os.environ.get("ARHIVA_BATCH", "5000"))
PAUSE_S = 0.2                  # between two delete batches: the feeds get the write lock
BUSY_S = 30                    # busy timeout of the live databases; longer held = next night
LOCK_TRIES = 3
HEAVY_WAIT_S = 1200
UNTIL = (5, 40)                # no new table (and no VACUUM) after this Zagreb time
DEX_MAX = int(os.environ.get("ARHIVA_DEX_MAX", "45000"))   # mints checked on DexScreener a night (1 500 requests)
DEX_PER_MIN = 120              # well under the 300/min per IP every other process shares
DEX_TTL_D = 7.0
DEX_BASE = "https://api.dexscreener.com"
STATE = ".arhiva.json"
TZ = "Europe/Zagreb"

# name -> (env override, file name); the env override only without an explicit data_dir (tests)
DB_FILES = {"hype": ("HYPE_DB", "hype.db"), "events": ("EVENTS_DB", "events.db"), "wallets": ("WALLET_DB", "wallets.db"),
            "tg": ("TG_DB", "tg.db"), "kol": ("KOL_DB", "kol.db"), "paper": ("PAPER_DB", "paper.db"),
            "early": ("EARLY_DB", "early.db"), "shadow": ("SHADOW_DB", "shadow.db"), "minute": ("MINUTE_DB", "minute.db"),
            "scan": ("SCAN_DB", "scan.db"), "range": ("RANGE_DB", "range.db"), "rug": ("RUG_DB", "rug.db"),
            "topcheck": ("TOPCHECK_DB", "topcheck.db"),
            # read only (keep rules, MC / volume sources), never archived
            "trade": ("TRADE_DB", "trade.db"), "league": ("LEAGUE_DB", "league.db"), "veliki": ("VELIKI_DB", "veliki.db"),
            "midcap": ("MIDCAP_DB", "midcap.db"), "konsenzus": ("KONSENZUS_DB", "konsenzus.db"),
            "oscilator": ("OSCILATOR_DB", "oscilator.db"), "izlazi": ("IZLAZI_DB", "izlazi.db"),
            "dugo": ("DUGO_DB", "dugo.db"), "koltest": ("KOLTEST_DB", "koltest.db"), "strat": ("STRAT_DB", "strat.db"),
            "fast": ("FAST_DB", "fast.db"), "momentum": ("MOMENTUM_DB", "momentum.db"),
            "proposals": ("PROPOSALS_DB", "proposals.db")}
# the databases whose token rows move, in this order (biggest first: the most room back early in the night)
ARCHIVE_DBS = ("hype", "events", "wallets", "tg", "kol", "paper", "early", "shadow", "minute", "scan", "range", "rug",
               "topcheck")
# every token referenced in these is kept (money, the midcap lists, the strategies on them)
KEEP_WHOLE_DBS = ("trade", "veliki", "midcap", "konsenzus", "oscilator", "izlazi")
# ... except their logs of tokens they only looked at (the microcap gate's refusals, the skip journal's samples, the
# proposals shown): those tokens were never bought, and keeping them would keep every microcap the gate refused
KEEP_WHOLE_SKIP = {("trade", "mikrokap_log"), ("trade", "skip_live"), ("trade", "prijedlog_log")}
KEY_COLS = ("mint", "token", "ca", "token_mint")
# tables never archived even with a token column: the rug archive list and its labels (the bot must never buy them)
KEEP_TABLES = {"hype": {"rug_archive", "rug_watch", "rug_recovered", "rug_relabel", "rug_relabel_sol",
                        "rug_relabel_runs", "smart_wallets", "live_state", "apify_cache", "apify_runs"}}
SKIP_NAME = ("kv", "settings", "config", "state", "meta", "runs", "budget")   # name or name ending: never archived
# extra condition on rows that may move (SQL on the live table)
EXTRA_WHERE = {("paper", "trades"): "COALESCE(status, '') != 'open'",            # only the closed demo history
               ("rug", "rug_reports"): "COALESCE(verdict, '') NOT IN ('ODBAČEN', 'VISOK RIZIK')"}   # rejections stay
# a column with a comma list of mints: the row moves when every mint in it is archived
LIST_KEYS = {("tg", "posts"): "cas"}
# the owner (or a later decision) leaves tables out without a code change: ARHIVA_SKIP="wallets.wallet_trades,kol.calls"
SKIP_ENV = {x.strip() for x in os.environ.get("ARHIVA_SKIP", "").split(",") if x.strip()}
# 15.11. (owner, after the archive order: "i dalje želim naći insajdere i botove koji kupuju prije poziva ... na
# postojećim podacima"; "holderi u profitu ... što kupuju"; microcap MEASUREMENT allowed for that research): the
# tables Insajderi 2.0 and the smart-money / jump-catalyst research read stay in the live DBs until that research has
# run on them; the owner (or a later decision) releases them by removing them here. ARHIVA_SKIP adds more.
RESEARCH_KEEP = {"wallets.wallet_trades", "kol.calls", "kol.snaps", "kol.insiders", "tg.posts", "early.precall_trades",
                 "early.group_buys", "early.early_buyers", "hype.chain_trades", "hype.live_trades",
                 "hype.chain_transfers", "events.call_outcomes", "kol.call_outcomes"}
SKIP_ENV = SKIP_ENV | RESEARCH_KEEP
# last known MC per mint: (db, table, key, ts, mc)
MC_SOURCES = (("hype", "hype_signals", "token", "ts", "mcap"), ("hype", "hype_snapshots", "token", "ts", "mcap"),
              ("hype", "token_pulse", "token", "ts", "mcap"), ("hype", "token_status", "token", "checked_ts", "mcap"),
              ("kol", "snaps", "token", "ts", "mcap"), ("range", "snaps", "token", "ts", "mcap"),
              ("paper", "ticks", "token", "ts", "mcap"), ("topcheck", "top_check", "token", "ts", "mcap"),
              ("events", "events", "mint", "ts", "mcap_usd"))
# daily 24 h volume per mint: (db, table, key, ts, expression per day over the day's rows)
# (kol.db token_hours is volume per hour of the DAY, 0-23, for the sessions: not a daily series)
VOL_SOURCES = (("range", "snaps", "token", "ts", "AVG(vol_h1) * 24"),
               ("hype", "token_pulse", "token", "ts", "AVG(vol_h1) * 24"), ("kol", "snaps", "token", "ts", "AVG(vol_h1) * 24"),
               ("hype", "token_status", "token", "checked_ts", "MAX(gt_vol24)"))
# open positions and the owner's trades: (label, db, sql); a missing table or column is skipped
OWNER_SQL = (("vlasnikovi tradeovi (league)", "league", "SELECT token FROM trades WHERE LOWER(user) = :owner"),
             ("vlasnikovi pravi tradeovi (league)", "league", "SELECT token FROM real_trades"),
             ("planovi izlaza (league)", "league", "SELECT token FROM exit_plans"),
             ("DCA planovi (league)", "league", "SELECT token FROM dca_plans"),
             ("KOL test otvoreno", "koltest", "SELECT token FROM positions WHERE book_closed_ts IS NULL"),
             ("dugoročna lista", "dugo", "SELECT mint FROM tokens"))
OPEN_DBS = ("league", "paper", "koltest", "strat", "range", "fast", "momentum", "proposals", "trade")

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (mint TEXT PRIMARY KEY, first_ts INTEGER, last_ts INTEGER);
CREATE TABLE IF NOT EXISTS mc (mint TEXT PRIMARY KEY, ts INTEGER, mc REAL);
CREATE TABLE IF NOT EXISTS vol (mint TEXT, day INTEGER, v REAL, PRIMARY KEY (mint, day));
CREATE TABLE IF NOT EXISTS dex (mint TEXT PRIMARY KEY, ts INTEGER, mc REAL, vol24 REAL, pair INTEGER);
CREATE TABLE IF NOT EXISTS keep (mint TEXT PRIMARY KEY, why TEXT);
CREATE TABLE IF NOT EXISTS rug (mint TEXT PRIMARY KEY, why TEXT);
CREATE TABLE IF NOT EXISTS verdict (mint TEXT PRIMARY KEY, action TEXT, why TEXT);
CREATE INDEX IF NOT EXISTS verdict_action ON verdict (action, mint);
CREATE TABLE IF NOT EXISTS moved (id INTEGER PRIMARY KEY, ts INTEGER, db TEXT, tbl TEXT, day TEXT, file TEXT,
    rows INTEGER, deleted INTEGER, live_b REAL, gz_b INTEGER, sha TEXT, restored_ts INTEGER);
"""
ARCHIVE = "arhiviraj"


class Stop(Exception):
    """The night stops here (disk, window); the message is the log line."""


# ---------- small helpers ----------------------------------------------------------------------------------------
def paths(data_dir=None):
    d = data_dir or disk.DATA_DIR
    return {k: (None if data_dir else os.environ.get(env)) or os.path.join(d, name) for k, (env, name) in DB_FILES.items()}


def archive_dir(data_dir=None):
    return (None if data_dir else os.environ.get("ARHIVA_DIR")) or os.path.join(data_dir or disk.DATA_DIR, "archive")


def _exists(path):
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def _ro(path):
    if not _exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("PRAGMA busy_timeout = 10000")
        return con
    except sqlite3.Error:
        return None


def _rw(path, timeout=BUSY_S):
    # autocommit (transactions are explicit); uri=True so the read-only ATTACH of the state / archive file works
    con = sqlite3.connect(f"file:{path}", uri=True, timeout=timeout, isolation_level=None)
    con.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    return con


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _qi(name):
    return '"' + str(name).replace('"', '""') + '"'


def _mb(b):
    return f"{(b or 0) / 1e6:.1f}".replace(".", ",")


def _gb(b):
    return f"{(b or 0) / 1e9:.2f}".replace(".", ",")


def _n(x):
    return f"{int(x or 0):,}".replace(",", ".")


def _zagreb(ts):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(ts, ZoneInfo(TZ))


def in_night(now=None):
    from ops import retencija
    return retencija.in_night(now or time.time(), default=True)


def switch_on(trade_db=None):
    from ops import retencija
    return retencija.switch_on(SWITCH, trade_db)


def free_b(path):
    mb = disk.free_mb(path if path and os.path.isdir(path) else None)
    return (mb or 0) * 1e6


def columns(con, table, schema="main"):
    return [r[1] for r in _q(con, f"PRAGMA {schema}.table_info({_qi(table)})")]


def tables(con):
    return [r[0] for r in _q(con, "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                                  "ORDER BY name")]


def key_of(db, table, cols):
    """The token column of a table to archive, or None (kept / no token key)."""
    low = table.lower()
    if (table in KEEP_TABLES.get(db, ()) or f"{db}.{table}" in SKIP_ENV
            or any(low == s or low.endswith("_" + s) for s in SKIP_NAME)):
        return None
    if (db, table) in LIST_KEYS:
        return LIST_KEYS[(db, table)] if LIST_KEYS[(db, table)] in cols else None
    return next((c for c in KEY_COLS if c in cols), None)


def table_bytes(con, table):
    from ops import retencija
    b, n = retencija.table_bytes(con, table)
    return b, n


# ---------- the verdict per mint ---------------------------------------------------------------------------------
def _state(data_dir=None):
    d = archive_dir(data_dir)
    os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(f"file:{os.path.join(d, 'arhiva_stanje.sqlite')}", uri=True, timeout=60)
    con.executescript(STATE_SCHEMA)
    return con


def _attach(con, path, alias):
    if not _exists(path):
        return False
    try:
        con.execute(f"ATTACH DATABASE ? AS {alias}", (f"file:{path}?mode=ro",))
        return True
    except sqlite3.Error:
        return False


def _detach(con, alias):
    try:
        con.execute(f"DETACH DATABASE {alias}")
    except sqlite3.Error:
        pass


def _has_cols(con, alias, table, cols):
    have = set(columns(con, table, alias))
    return bool(have) and all(c in have for c in cols)


def gather(st, p, now, log=print):
    """seen / mc / vol from the live databases (read only, attached to the state db), keep and rug sets."""
    for t in ("seen", "mc", "vol", "keep", "rug"):
        st.execute(f"DELETE FROM {t}")
    st.commit()
    for db in ARCHIVE_DBS:   # first / last time we saw each mint, over every table the archive would touch
        if not _attach(st, p.get(db), "s"):
            continue
        try:
            for table in tables_of(st, "s"):
                cols = columns(st, table, "s")
                key = key_of(db, table, cols)
                if not key or (db, table) in LIST_KEYS:
                    continue
                ts = next((c for c in ("ts", "first_ts", "found_ts", "checked_at", "checked_ts", "opened_ts",
                                       "first_seen", "call_ts", "created_ts") if c in cols), None)
                lo, hi = (f"MIN({_qi(ts)})", f"MAX({_qi(ts)})") if ts else ("NULL", "NULL")
                st.execute(f"""INSERT INTO seen SELECT {_qi(key)}, {lo}, {hi} FROM s.{_qi(table)}
                               WHERE COALESCE({_qi(key)}, '') != '' GROUP BY {_qi(key)}
                               ON CONFLICT(mint) DO UPDATE SET
                               first_ts = MIN(COALESCE(seen.first_ts, excluded.first_ts), COALESCE(excluded.first_ts, seen.first_ts)),
                               last_ts = MAX(COALESCE(seen.last_ts, excluded.last_ts), COALESCE(excluded.last_ts, seen.last_ts))""")
                st.commit()
        finally:
            _detach(st, "s")
    for db, table, key, ts, mc in MC_SOURCES:
        if _attach(st, p.get(db), "s"):
            try:
                if _has_cols(st, "s", table, (key, ts, mc)):
                    st.execute(f"""INSERT INTO mc SELECT {key}, MAX({ts}), {mc} FROM s.{table} WHERE {mc} > 0 GROUP BY {key}
                                   ON CONFLICT(mint) DO UPDATE SET ts = excluded.ts, mc = excluded.mc
                                   WHERE excluded.ts > mc.ts""")
                    st.commit()
            finally:
                _detach(st, "s")
    for db, table, key, ts, expr in VOL_SOURCES:
        if _attach(st, p.get(db), "s"):
            try:
                cols = [key, ts] + [c for c in ("volume", "vol_h1", "gt_vol24") if c in expr]
                if _has_cols(st, "s", table, cols):
                    st.execute(f"""INSERT INTO vol SELECT {key}, {ts} / {D}, {expr} FROM s.{table} WHERE {ts} IS NOT NULL
                                   GROUP BY {key}, {ts} / {D} HAVING {expr} IS NOT NULL
                                   ON CONFLICT(mint, day) DO UPDATE SET v = MAX(vol.v, excluded.v)""")
                    st.commit()
            finally:
                _detach(st, "s")
    per = keep_sources(st, p)
    rug = rug_sources(st, p)
    log("arhiva: zadržani po izvoru: " + (", ".join(f"{k} {_n(v)}" for k, v in per.items() if v) or "nijedan")
        + f"; rug / mrtvi iz arhive rugova {_n(rug)}")
    return per


def tables_of(con, alias):
    return [r[0] for r in _q(con, f"SELECT name FROM {alias}.sqlite_master WHERE type = 'table' "
                                  "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _keep_add(st, label, mints):
    rows = [(m, label) for m in mints if m]
    st.executemany("INSERT OR IGNORE INTO keep VALUES (?, ?)", rows)
    return len(rows)


def keep_sources(st, p):
    """Rule 1: {label: mints} into keep."""
    per = {}
    from trade import settings
    owner = settings.owner()
    for db in KEEP_WHOLE_DBS:   # every token these databases mention
        con = _ro(p.get(db))
        got = set()
        for table in tables(con):
            if (db, table) in KEEP_WHOLE_SKIP:
                continue
            cols = columns(con, table)
            for c in KEY_COLS:
                if c in cols:
                    got |= {r[0] for r in _q(con, f"SELECT DISTINCT {_qi(c)} FROM {_qi(table)}")}
        if con is not None:
            con.close()
        per[f"{db}.db"] = _keep_add(st, f"{db}.db", got)
    for label, db, sql in OWNER_SQL:
        con = _ro(p.get(db))
        per[label] = _keep_add(st, label, {r[0] for r in _q(con, sql, {"owner": owner})})
        if con is not None:
            con.close()
    n_open = 0
    for db in OPEN_DBS:   # every open position: a token column and status 'open' in a trades / positions table
        con = _ro(p.get(db))
        for table in tables(con):
            cols = columns(con, table)
            key = next((c for c in KEY_COLS if c in cols), None)
            if key and "status" in cols:
                n_open += _keep_add(st, "otvorena pozicija", {r[0] for r in _q(
                    con, f"SELECT {_qi(key)} FROM {_qi(table)} WHERE LOWER(status) IN ('open', 'opening', 'pending', 'partial')")})
        if con is not None:
            con.close()
    per["otvorene pozicije"] = n_open
    st.commit()
    return per


def rug_sources(st, p):
    con = _ro(p.get("hype"))
    rec = {r[0] for r in _q(con, "SELECT token FROM rug_recovered")}
    rows = [(t, f"rug arhiva ({k or '?'})") for t, k in _q(con, "SELECT token, kind FROM rug_archive") if t not in rec]
    if con is not None:
        con.close()
    st.executemany("INSERT OR IGNORE INTO rug VALUES (?, ?)", rows)
    st.commit()
    return len(rows)


def _dex_fetch(mints):
    """{mint: (mc, vol24, has_pair)} for up to 30 mints; raises on a network error (those mints wait)."""
    req = urllib.request.Request(f"{DEX_BASE}/tokens/v1/solana/{','.join(mints)}",
                                 headers={"User-Agent": "Mozilla/5.0 (archive check)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        pairs = json.loads(r.read().decode() or "[]") or []
    best = {}
    for pr in pairs if isinstance(pairs, list) else []:
        m = ((pr.get("baseToken") or {}).get("address")) or ""
        liq = float((pr.get("liquidity") or {}).get("usd") or 0)
        if m in mints and (m not in best or liq > best[m][0]):
            best[m] = (liq, float(pr.get("marketCap") or pr.get("fdv") or 0),
                       float((pr.get("volume") or {}).get("h24") or 0))
    return {m: ((best[m][1], best[m][2], 1) if m in best else (0.0, 0.0, 0)) for m in mints}


def dex_check(st, now, log=print, fetch=None, limit=DEX_MAX, stop=None):
    """DexScreener for the candidates without a fresh check (known-MC ones first, oldest first)."""
    fetch = fetch or _dex_fetch
    cut = now - int(DEX_TTL_D * D)
    todo = [r[0] for r in st.execute(
        """SELECT s.mint FROM seen s LEFT JOIN mc ON mc.mint = s.mint LEFT JOIN dex ON dex.mint = s.mint
           WHERE s.mint NOT IN (SELECT mint FROM keep) AND s.mint NOT IN (SELECT mint FROM rug)
             AND COALESCE(mc.mc, 0) < ? AND (dex.ts IS NULL OR dex.ts < ?) AND LENGTH(s.mint) BETWEEN 32 AND 48
           ORDER BY mc.mc IS NULL, COALESCE(s.last_ts, 0) LIMIT ?""", (KEEP_MC, cut, int(limit)))]
    gap, done, failed, t0 = 60.0 / DEX_PER_MIN, 0, 0, time.time()
    for i in range(0, len(todo), 30):
        if stop and stop():
            break
        part = todo[i:i + 30]
        t = time.time()
        try:
            got = fetch(part)
        except Exception:  # noqa: BLE001 - these mints wait for the next night
            failed += len(part)
            got = {}
        st.executemany("INSERT OR REPLACE INTO dex VALUES (?, ?, ?, ?, ?)",
                       [(m, now, mc, v, pair) for m, (mc, v, pair) in got.items()])
        st.commit()
        done += len(got)
        wait = gap - (time.time() - t)
        if wait > 0 and fetch is _dex_fetch:
            time.sleep(wait)
    log(f"arhiva: DexScreener provjera {_n(done)} tokena ({_n(len(todo))} na redu, neuspjelo {_n(failed)}, "
        f"{time.time() - t0:.0f} s)")
    return done


def classify(st, now, log=print):
    """verdict (mint, action, why) for every mint seen; -> {why: n}."""
    today, cut_age, fresh = now // D, now - int(MIN_AGE_D * D), now - int(DEX_TTL_D * D)
    st.execute("DELETE FROM verdict")
    st.execute("CREATE TEMP TABLE IF NOT EXISTS vstat (mint TEXT PRIMARY KEY, ok INTEGER, total INTEGER, last_good INTEGER, "
               "dead INTEGER)")
    st.execute("DELETE FROM temp.vstat")
    st.execute(f"""INSERT INTO temp.vstat SELECT s.mint,
        (SELECT COUNT(*) FROM vol v WHERE v.mint = s.mint AND v.day >= s.first_ts / {D} AND v.day < :today AND v.v >= :thr),
        MAX(1, :today - COALESCE(s.first_ts, :now) / {D}),
        (SELECT MAX(v.day) FROM vol v WHERE v.mint = s.mint AND v.v >= :thr),
        (SELECT COUNT(*) = :dd AND MAX(x.v) < :dead FROM (SELECT v.v FROM vol v WHERE v.mint = s.mint
                                                           ORDER BY v.day DESC LIMIT :dd) x)
        FROM seen s""", {"today": today, "thr": KEEP_VOL_USD, "now": now, "dd": DEAD_DAYS, "dead": DEAD_VOL_USD})
    rows = st.execute("""SELECT s.mint, k.why, r.why, mc.mc, s.first_ts, d.ts >= :fresh, d.mc, d.vol24, d.pair,
                                 vs.ok, vs.total, vs.last_good, vs.dead
                          FROM seen s LEFT JOIN keep k ON k.mint = s.mint LEFT JOIN rug r ON r.mint = s.mint
                          LEFT JOIN mc ON mc.mint = s.mint LEFT JOIN dex d ON d.mint = s.mint
                          LEFT JOIN temp.vstat vs ON vs.mint = s.mint""", {"fresh": fresh})
    out, batch, kept_vol = {}, [], 0
    for (m, kwhy, rwhy, last_mc, first_ts, dfresh, dmc, dvol, dpair, ok, total, last_good, dead) in rows:
        trading = (dfresh and (dvol or 0) >= KEEP_VOL_USD) or (last_good is not None and last_good >= today - KEEP_VOL_RECENT_D)
        vol_kept = bool(ok) and total and ok / total >= KEEP_VOL_SHARE and trading
        if kwhy:
            act, why = "zadrži", kwhy
        elif dfresh and (dmc or 0) >= KEEP_MC:
            act, why = "zadrži", "MC ≥ 2M sada (DexScreener)"
        elif not dfresh and not rwhy and (last_mc or 0) >= KEEP_MC:
            act, why = "zadrži", "zadnji MC ≥ 2M"
        elif vol_kept:
            act, why = "zadrži", "zadržao volumen od početka"
            kept_vol += 1
        elif first_ts is not None and first_ts > cut_age:
            act, why = "zadrži", f"prvi put viđen prije manje od {MIN_AGE_D:g} d"
        elif rwhy:
            act, why = ARCHIVE, "rug"
        elif dfresh and not dpair:
            act, why = ARCHIVE, "mrtav (nema para na DexScreeneru)"
        elif dfresh and (dvol or 0) < DEAD_VOL_USD and dead:
            act, why = ARCHIVE, "mrtav (volumen ~0 danima)"
        elif dfresh:
            act, why = ARCHIVE, "mikrokap (MC < 2M sada)"
        else:
            act, why = "čeka", "čeka provjeru na DexScreeneru"
        out[why] = out.get(why, 0) + 1
        batch.append((m, act, why))
        if len(batch) >= 20000:
            st.executemany("INSERT OR REPLACE INTO verdict VALUES (?, ?, ?)", batch)
            batch = []
    st.executemany("INSERT OR REPLACE INTO verdict VALUES (?, ?, ?)", batch)
    st.commit()
    log(f"arhiva: pravilo „zadržao volumen od početka” (24 h volumen ≥ {KEEP_VOL_USD / 1000:.0f}k $ na ≥ "
        f"{KEEP_VOL_SHARE:.0%} dana od prvog viđenja i trguje se i sada): {_n(kept_vol)} tokena")
    return out


# ---------- the plan -------------------------------------------------------------------------------------------
def plan(p, data_dir=None, log=print):
    """[{db, table, key, rows, move, mb, move_mb}] and [(db, table, why)] left alone; the verdict must exist."""
    st_path = os.path.join(archive_dir(data_dir), "arhiva_stanje.sqlite")
    items, left = [], []
    for db in ARCHIVE_DBS:
        path = p.get(db)
        if not _exists(path):
            continue
        con = _ro(path)
        if con is None:
            left.append((db, "*", "baza nečitljiva"))
            continue
        try:
            _attach(con, st_path, "v")
            for table in tables(con):
                cols = columns(con, table)
                key = key_of(db, table, cols)
                if not key:
                    left.append((db, table, "zadržana tablica" if any(c in cols for c in KEY_COLS) else "bez ključa tokena"))
                    continue
                sql = (_q(con, "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)) or [("",)])[0][0]
                if "WITHOUT ROWID" in (sql or "").upper():
                    left.append((db, table, "WITHOUT ROWID (ne seli se)"))
                    continue
                try:
                    move = count_move(con, db, table, key)
                except sqlite3.Error as e:
                    left.append((db, table, f"nečitljiva ({str(e)[:60]})"))
                    continue
                b, rows = table_bytes(con, table)
                b = b if b is not None else rows * 200
                items.append({"db": db, "table": table, "key": key, "rows": rows, "move": move, "b": b,
                              "move_b": b * move / rows if rows else 0})
        finally:
            con.close()
    return items, left


def _where(db, table, key, alias="v"):
    w = f"{_qi(key)} IN (SELECT mint FROM {alias}.verdict WHERE action = '{ARCHIVE}')"
    return w + (f" AND ({EXTRA_WHERE[(db, table)]})" if (db, table) in EXTRA_WHERE else "")


def _list_ok(con, cas, alias="v"):
    """{cas text: True} when every mint of the comma list is archived."""
    mints = {m for c in cas for m in (c or "").split(",") if m}
    arch = set()
    ml = list(mints)
    for i in range(0, len(ml), 500):
        part = ml[i:i + 500]
        arch |= {r[0] for r in con.execute(f"SELECT mint FROM {alias}.verdict WHERE action = '{ARCHIVE}' AND mint IN "
                                           f"({','.join('?' * len(part))})", part)}
    return {c: bool(c) and all(m in arch for m in c.split(",") if m) for c in cas}


def count_move(con, db, table, key):
    if (db, table) in LIST_KEYS:
        n = 0
        for lo, hi in _ranges(con, table):
            cas = [r[0] for r in con.execute(f"SELECT {_qi(key)} FROM {_qi(table)} WHERE rowid >= ? AND rowid < ? "
                                             f"AND COALESCE({_qi(key)}, '') != ''", (lo, hi))]
            ok = _list_ok(con, set(cas))
            n += sum(1 for c in cas if ok.get(c))
        return n
    return con.execute(f"SELECT COUNT(*) FROM {_qi(table)} WHERE {_where(db, table, key)}").fetchone()[0]


def _ranges(con, table, batch=BATCH, schema="main"):
    """rowid ranges [lo, hi) covering the table, empty stretches jumped over."""
    lo = con.execute(f"SELECT MIN(rowid) FROM {schema}.{_qi(table)}").fetchone()[0]
    top = con.execute(f"SELECT MAX(rowid) FROM {schema}.{_qi(table)}").fetchone()[0]
    while lo is not None and lo <= top:
        yield lo, lo + batch
        lo = con.execute(f"SELECT MIN(rowid) FROM {schema}.{_qi(table)} WHERE rowid >= ?", (lo + batch,)).fetchone()[0]


def plan_lines(items, left, verdicts, dry):
    move = sum(i["move"] for i in items)
    mb = sum(i["move_b"] for i in items)
    keep = sum(n for w, n in verdicts.items() if not (w.startswith("rug") or w.startswith("mrtav") or w.startswith("mikrokap")))
    arch = sum(verdicts.values()) - keep
    head = ("arhiva: plan (prekidač arhiva_mikrokapova isključen: samo plan, ništa se ne seli)" if dry
            else "arhiva: plan (prekidač uključen: seli noću 01-06)")
    out = [f"{head}: tokena za arhivu {_n(arch)}, zadržano {_n(keep)} ("
           + ", ".join(f"{w} {_n(n)}" for w, n in sorted(verdicts.items(), key=lambda x: -x[1])) + f"); redaka za "
           f"premjestiti {_n(move)} ≈ {_mb(mb)} MB"]
    by_db = {}
    for i in items:
        d = by_db.setdefault(i["db"], [0, 0, 0])
        d[0] += i["move_b"]
        d[1] += i["b"] - i["move_b"]
        d[2] += i["move"]
    out.append("arhiva: plan po bazi: " + "; ".join(f"{db}.db seli {_mb(a)} MB ({_n(n)} redaka), ostaje {_mb(b)} MB"
                                                   for db, (a, b, n) in by_db.items()))
    if left:
        out.append("arhiva: plan, ostaju netaknute (bez ključa tokena ili zadržane): "
                   + ", ".join(f"{db}.db {t}" for db, t, _w in left))
    return out


def write_plan(items, left, verdicts, dry, now, out_dir=None):
    out_dir = out_dir or os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    z = _zagreb(now)
    lines = [f"# Arhiva mikrokapova: plan {z:%d.%m.%Y. %H:%M}", "",
             ("Prekidač arhiva_mikrokapova **isključen**: samo plan, ništa se ne seli." if dry else
              "Prekidač arhiva_mikrokapova **uključen**: retci se noću sele u archive/<baza>/<tablica>_<datum>.sqlite.gz."),
             "", "## Tokeni", "", "| Odluka | Tokena |", "|---|---:|"]
    lines += [f"| {w} | {_n(n)} |" for w, n in sorted(verdicts.items(), key=lambda x: -x[1])]
    lines += ["", "## Tablice", "", "| Baza | Tablica | Ključ | Redaka | Seli | MB seli | MB ostaje |",
              "|---|---|---|---:|---:|---:|---:|"]
    for i in sorted(items, key=lambda x: (ARCHIVE_DBS.index(x["db"]), -x["move_b"])):
        lines.append(f"| {i['db']}.db | {i['table']} | {i['key']} | {_n(i['rows'])} | {_n(i['move'])} | "
                     f"{_mb(i['move_b'])} | {_mb(i['b'] - i['move_b'])} |")
    lines += ["", "## Ostaju netaknute", "", "| Baza | Tablica | Zašto |", "|---|---|---|"]
    lines += [f"| {db}.db | {t} | {w} |" for db, t, w in left]
    path = os.path.join(out_dir, "arhiva_plan.md")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)
    return path


# ---------- one table ------------------------------------------------------------------------------------------
def _ipk(con, table, schema="main"):
    """The INTEGER PRIMARY KEY column (the rowid alias) or None."""
    info = _q(con, f"PRAGMA {schema}.table_info({_qi(table)})")
    pk = [r for r in info if r[5]]
    return pk[0][1] if len(pk) == 1 and (pk[0][2] or "").upper() == "INTEGER" else None


def _row_hash(h, row):
    h.update(repr(tuple(row)).encode("utf-8", "surrogatepass"))
    h.update(b"\n")


def _archive_file(adir, db, table, day):
    d = os.path.join(adir, db)
    os.makedirs(d, exist_ok=True)
    base, i = os.path.join(d, f"{table}_{day}"), 1
    path = base + ".sqlite"
    while os.path.exists(path) or os.path.exists(path + ".gz"):
        i += 1
        path = f"{base}_{i}.sqlite"
    return path


def _gzip(src, dst, chunk=1 << 20):
    h = hashlib.sha256()
    with open(src, "rb") as f, gzip.open(dst + ".tmp", "wb", compresslevel=6) as g:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            g.write(b)
    os.replace(dst + ".tmp", dst)
    return h.hexdigest()


def _gunzip_sha(path, out=None, chunk=1 << 20):
    h = hashlib.sha256()
    with gzip.open(path, "rb") as g:
        f = open(out, "wb") if out else None
        try:
            while True:
                b = g.read(chunk)
                if not b:
                    break
                h.update(b)
                if f:
                    f.write(b)
        finally:
            if f:
                f.close()
    return h.hexdigest()


def _locked(e):
    return "locked" in str(e) or "busy" in str(e)


def _write(con, fn, label, path, log):
    """fn() inside BEGIN IMMEDIATE; a lock held longer than BUSY_S, LOCK_TRIES times -> Stop for this database."""
    for i in range(1, LOCK_TRIES + 1):
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                out = fn()
                con.execute("COMMIT")
                return out
            except BaseException:
                con.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            if not _locked(e) or i == LOCK_TRIES:
                if _locked(e):
                    from ops import dblock
                    raise Stop(f"arhiva: {label} zauzeta dulje od {BUSY_S * LOCK_TRIES} s (drže je: "
                               f"{dblock.holders(path) or '?'}), nastavljam sljedeće noći") from e
                raise
            time.sleep(1)


def move_table(p, db, table, now, log=print, data_dir=None, stop=None, verify_hook=None):
    """Copy -> verify -> gzip -> verify -> delete for one table. -> dict, or None when nothing moves."""
    path = p[db]
    adir = archive_dir(data_dir)
    st_path = os.path.join(adir, "arhiva_stanje.sqlite")
    con = _rw(path)
    arc = None
    try:
        con.execute("ATTACH DATABASE ? AS v", (f"file:{st_path}?mode=ro",))
        cols = columns(con, table)
        key = key_of(db, table, cols)
        row = _q(con, "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,))
        if not key or not row or "WITHOUT ROWID" in (row[0][0] or "").upper():
            return None
        create = row[0][0]
        listed = (db, table) in LIST_KEYS
        n_move = count_move(con, db, table, key)
        if not n_move:
            return None
        b, rows = table_bytes(con, table)
        b = b if b is not None else rows * 200
        free, need = free_b(os.path.dirname(path)), max(MIN_FREE_B, FREE_X * b)
        if free < need:
            raise Stop(f"arhiva: stala, premalo prostora (slobodno {free / 1e9:.2f} GB, za {db}.db {table} treba "
                       f"{need / 1e9:.2f} GB: najmanje {MIN_FREE_B / 1e9:g} GB i {FREE_X:g} × tablica {_mb(b)} MB)")
        ipk = _ipk(con, table)
        qcols = ", ".join(_qi(c) for c in cols)
        sel = f"SELECT rowid, {qcols} FROM {_qi(table)} WHERE rowid >= ? AND rowid < ?"
        where = "" if listed else f" AND {_where(db, table, key)}"
        ins_cols = qcols if ipk else f"rowid, {qcols}"
        ins = f"INSERT INTO {_qi(table)} ({ins_cols}) VALUES ({','.join('?' * (len(cols) + (0 if ipk else 1)))})"
        day = _zagreb(now).strftime("%Y%m%d")
        arc = _archive_file(adir, db, table, day)
        a = sqlite3.connect(arc)
        a.execute("PRAGMA journal_mode = OFF")
        a.execute("PRAGMA synchronous = OFF")
        a.execute(create)
        a.execute("CREATE TABLE _arhiva (k TEXT PRIMARY KEY, v TEXT)")
        h, n = hashlib.sha256(), 0
        try:
            for lo, hi in _ranges(con, table):
                if stop and stop():
                    raise Stop(f"arhiva: {db}.db {table}: prekinuto (kraj noćnog prozora), ništa nije obrisano, "
                               "nastavlja sljedeće noći")
                got = con.execute(sel + where + " ORDER BY rowid", (lo, hi)).fetchall()
                if listed:
                    ok = _list_ok(con, {r[1 + cols.index(key)] for r in got})
                    got = [r for r in got if ok.get(r[1 + cols.index(key)])]
                for r in got:
                    _row_hash(h, r)
                a.executemany(ins, [r[1:] if ipk else r for r in got])
                a.commit()
                n += len(got)
            meta = {"db": db, "table": table, "key": key, "columns": json.dumps(cols), "rows": str(n),
                    "sha_rows": h.hexdigest(), "created": str(int(time.time())), "source": os.path.basename(path)}
            a.executemany("INSERT INTO _arhiva VALUES (?, ?)", list(meta.items()))
            a.commit()
        finally:
            a.close()
        # verify the copy: reopened, quick_check, count and checksum
        bad = verify_copy(arc, table, cols, n, h.hexdigest())
        if verify_hook:
            bad = verify_hook("copy", arc) or bad
        if bad:
            log(f"arhiva: {db}.db {table}: provjera kopije nije prošla ({bad}), ništa nije obrisano")
            _rm(arc)
            return {"db": db, "table": table, "moved": 0, "failed": bad}
        gz = arc + ".gz"
        raw_sha = _gzip(arc, gz)
        gz_sha = _gunzip_sha(gz)
        bad = None if gz_sha == raw_sha else "gzip se ne raspakira u istu datoteku"
        if verify_hook:
            bad = verify_hook("gz", gz) or bad
        if bad:
            log(f"arhiva: {db}.db {table}: provjera .gz nije prošla ({bad}), ništa nije obrisano")
            _rm(arc)
            _rm(gz)
            return {"db": db, "table": table, "moved": 0, "failed": bad}
        # delete: only rows still equal to the archived copy
        con.execute("ATTACH DATABASE ? AS a", (f"file:{arc}?mode=ro",))
        eq = " AND ".join(f"m.{_qi(c)} IS x.{_qi(c)}" for c in cols)
        dele = (f"DELETE FROM main.{_qi(table)} WHERE rowid IN (SELECT x.rowid FROM a.{_qi(table)} x JOIN "
                f"main.{_qi(table)} m ON m.rowid = x.rowid WHERE x.rowid >= ? AND x.rowid < ? AND {eq})")
        deleted = 0
        for lo, hi in _ranges(con, table, schema="a"):
            deleted += _write(con, lambda: con.execute(dele, (lo, hi)).rowcount, f"{db}.db", path, log)
            try:
                con.execute("PRAGMA main.wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass
            if PAUSE_S:
                time.sleep(PAUSE_S)
        con.execute("DETACH DATABASE a")
        gz_b = os.path.getsize(gz)
        _rm(arc)
        left = con.execute(f"SELECT COUNT(*) FROM {_qi(table)}").fetchone()[0]
        live_b = b * n / rows if rows else 0
        log(f"arhiva: {db}.db {table}: premješteno {_n(deleted)} redaka ({_mb(live_b)} MB → arhiva {_mb(gz_b)} MB gz), "
            f"ostaje {_n(left)}" + (f"; {_n(n - deleted)} se promijenilo nakon kopije, ostaje u bazi i ide druge noći"
                                    if n - deleted else ""))
        st = _state(data_dir)
        try:
            st.execute("INSERT INTO moved (ts, db, tbl, day, file, rows, deleted, live_b, gz_b, sha) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (int(time.time()), db, table, day, os.path.relpath(gz, adir), n, deleted, live_b, gz_b, raw_sha))
            st.commit()
        finally:
            st.close()
        arc = None
        return {"db": db, "table": table, "moved": deleted, "copied": n, "left": left, "live_b": live_b, "gz_b": gz_b,
                "file": gz}
    finally:
        if arc:   # without a .gz nothing was deleted; with one it is verified and holds every deleted row
            _rm(arc)
        con.close()


def verify_copy(arc, table, cols, n, sha):
    """None when the archive file is sound and holds exactly the rows read, else the reason."""
    try:
        a = sqlite3.connect(f"file:{arc}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return f"ne otvara se ({e})"
    try:
        if a.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            return "quick_check nije ok"
        cnt = a.execute(f"SELECT COUNT(*) FROM {_qi(table)}").fetchone()[0]
        if cnt != n:
            return f"redaka {cnt}, kopirano {n}"
        h = hashlib.sha256()
        for r in a.execute(f"SELECT rowid, {', '.join(_qi(c) for c in cols)} FROM {_qi(table)} ORDER BY rowid"):
            _row_hash(h, r)
        return None if h.hexdigest() == sha else "kontrolni zbroj se ne slaže"
    finally:
        a.close()


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _db_bytes(path):
    return sum(os.path.getsize(path + s) for s in ("", "-wal") if os.path.exists(path + s))


def finish_db(path, log=print, until=None):
    """incremental_vacuum on an auto_vacuum file, then VACUUM only with free >= VACUUM_X x size. -> text."""
    try:
        con = _rw(path)
        try:
            if con.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:
                con.execute("PRAGMA incremental_vacuum")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            con.close()
    except sqlite3.Error:
        pass
    size = os.path.getsize(path) if os.path.exists(path) else 0
    free = free_b(os.path.dirname(path))
    if until and until():
        return "VACUUM preskočen: kraj noćnog prozora"
    if free < VACUUM_X * size:
        return f"VACUUM preskočen: slobodno {free / 1e9:.2f} GB < {VACUUM_X:g} × {size / 1e9:.2f} GB"
    from ops import dbs
    why = []
    res = dbs.compact(path, min_waste=0.05, margin_mb=100, why=why)
    return f"VACUUM {res}" if res else ("VACUUM preskočen: " + ("; ".join(why) or "?"))


# ---------- the night ------------------------------------------------------------------------------------------
def state_path(data_dir=None):
    return os.path.join(data_dir or disk.DATA_DIR, STATE)


def load_state(data_dir=None):
    try:
        with open(state_path(data_dir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st, data_dir=None):
    pth = state_path(data_dir)
    try:
        with open(pth + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(pth + ".tmp", pth)
    except OSError:
        pass


def _late(now, t0):
    z = _zagreb(now + time.time() - t0)
    return (z.hour, z.minute) >= UNTIL or not in_night(now + time.time() - t0)


def run(p=None, now=None, log=print, data_dir=None, out_dir=None, fetch=None, dry=None, stop=None, slot=None,
        verify_hook=None, force=False):
    """One night: verdict, plan, and with the switch on the move. -> summary dict ({} when nothing was due)."""
    p = p or paths(data_dir)
    now = int(now or time.time())
    if not force and not in_night(now):
        return {}
    st_json = load_state(data_dir)
    night = _zagreb(now).date().isoformat()
    dry = (not switch_on(p.get("trade"))) if dry is None else dry
    if not force and (st_json.get("done") == night or (dry and st_json.get("plan_done") == night)):
        return {}
    t0 = time.time()
    stop = stop or (lambda: _late(now, t0))
    if slot is None:
        from ops import heavy
        slot = lambda label: heavy.slot(wait=HEAVY_WAIT_S, label=label)  # noqa: E731
    out = {"night": night, "dry": dry, "moved": 0, "gz_b": 0, "freed_b": 0, "tables": [], "stopped": None}
    with slot("arhiva (plan)") as got:   # the heavy reads under the lock ...
        if not got:
            log("arhiva: brava teških poslova zauzeta, plan pokušavam za 30 min")
            return {}
        st = _state(data_dir)
        try:
            gather(st, p, now, log)
        finally:
            st.close()
    st = _state(data_dir)   # ... the DexScreener lookups (minutes of waiting on the network) without it
    try:
        dex_check(st, now, log, fetch=fetch, stop=stop)
    finally:
        st.close()
    with slot("arhiva (plan)") as got:
        if not got:
            log("arhiva: brava teških poslova zauzeta, plan pokušavam za 30 min")
            return {}
        st = _state(data_dir)
        try:
            verdicts = classify(st, now, log)
        finally:
            st.close()
        items, left = plan(p, data_dir, log)
    for ln in plan_lines(items, left, verdicts, dry):
        log(ln)
    try:
        write_plan(items, left, verdicts, dry, now, out_dir)
    except OSError as e:
        log(f"arhiva: plan nije zapisan ({e})")
    out.update(plan_rows=sum(i["move"] for i in items), plan_b=sum(i["move_b"] for i in items))
    if dry:
        if not force:   # the night's plan once; a switch turned on later the same night still moves
            st_json.update(plan_done=night, last=out, ts=now)
            save_state(st_json, data_dir)
        return out
    order = sorted((i for i in items if i["move"]), key=lambda i: (ARCHIVE_DBS.index(i["db"]), -i["b"]))
    by_db, sizes = {}, {}
    for i in order:
        by_db.setdefault(i["db"], []).append(i)
    try:
        for db, its in by_db.items():
            path = p[db]
            sizes[db] = _db_bytes(path)
            touched = False
            try:
                for i in its:
                    if stop():
                        raise Stop("arhiva: stala, kraj noćnog prozora; nastavlja sljedeće noći")
                    with slot(f"arhiva ({db}.db {i['table']})") as got:
                        if not got:
                            raise Stop("arhiva: brava teških poslova zauzeta, nastavljam za 30 min")
                        res = move_table(p, db, i["table"], now, log, data_dir, stop, verify_hook)
                    if res:
                        out["tables"].append(res)
                        out["moved"] += res.get("moved", 0)
                        out["gz_b"] += res.get("gz_b", 0)
                        touched = touched or bool(res.get("moved"))
            except Stop as e:
                if "zauzeta dulje" in str(e):   # this database is held: the next one goes on
                    log(str(e))
                    out["stopped"] = out["stopped"] or str(e)
                else:
                    raise
            finally:
                if touched:
                    with slot(f"arhiva (VACUUM {db}.db)") as got:
                        res = finish_db(path, log, stop) if got else "VACUUM preskočen: brava zauzeta"
                    out["freed_b"] += max(0, sizes[db] - _db_bytes(path))
                    log(f"arhiva: {db}.db: {res}")
    except Stop as e:
        log(str(e))
        out["stopped"] = str(e)
    free = free_b(os.path.dirname(p.get("hype") or "") or None)
    log(f"arhiva: oslobođeno {_mb(out['freed_b'])} MB, disk slobodno {_gb(free)} GB"
        + f" (premješteno {_n(out['moved'])} redaka, arhiva {_mb(out['gz_b'])} MB gz"
        + ("; nastavlja sljedeće noći" if out["stopped"] else "") + ")")
    out["free_b"] = free
    if not out["stopped"]:
        st_json["done"] = night
    out["tables"] = [{k: v for k, v in t.items() if k != "file"} for t in out["tables"]]
    st_json.update(last=out, ts=now)
    save_state(st_json, data_dir)
    return out


# ---------- restore --------------------------------------------------------------------------------------------
def restore(p, db, table, date=None, log=print, data_dir=None):
    """Re-insert archive/<db>/<table>_<date>*.sqlite.gz (every date without one) into the live table: INSERT OR IGNORE,
    the .gz stays. -> (inserted, skipped)."""
    adir = archive_dir(data_dir)
    files = sorted(glob.glob(os.path.join(adir, db, f"{table}_{date or ''}*.sqlite.gz")))
    files = [f for f in files if os.path.basename(f)[len(table) + 1:][:8].isdigit()]
    if not files:
        log(f"arhiva vrati: nema arhive {db}/{table}" + (f" za {date}" if date else ""))
        return 0, 0
    path = p[db]
    ins_n = skip_n = 0
    for gz in files:
        tmp = gz[:-3] + ".vrati"
        try:
            _gunzip_sha(gz, out=tmp)
            a = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
            cols = json.loads(dict(a.execute("SELECT k, v FROM _arhiva").fetchall())["columns"])
            con = _rw(path)
            try:
                live = set(columns(con, table))
                if not live:
                    con.execute(a.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                                          (table,)).fetchone()[0])
                    live = set(cols)
                use = [c for c in cols if c in live]
                q = ", ".join(_qi(c) for c in use)
                sql = f"INSERT OR IGNORE INTO {_qi(table)} ({q}) VALUES ({','.join('?' * len(use))})"
                cur = a.execute(f"SELECT {q} FROM {_qi(table)} ORDER BY rowid")
                while True:
                    rows = cur.fetchmany(BATCH)
                    if not rows:
                        break
                    k = _write(con, lambda: con.executemany(sql, rows).rowcount, f"{db}.db", path, log)
                    ins_n += k
                    skip_n += len(rows) - k
            finally:
                con.close()
                a.close()
        finally:
            _rm(tmp)
        st = _state(data_dir)
        try:
            st.execute("UPDATE moved SET restored_ts = ? WHERE file = ?", (int(time.time()), os.path.relpath(gz, adir)))
            st.commit()
        finally:
            st.close()
    log(f"arhiva vrati: {db}.db {table}: vraćeno {_n(ins_n)} redaka iz {len(files)} datoteka, preskočeno {_n(skip_n)} "
        "(već postoje); arhiva ostaje")
    return ins_n, skip_n


def summary(data_dir=None, now=None, max_age_h=30):
    """The last night's result for the morning report, or None."""
    st = load_state(data_dir)
    last = st.get("last")
    if not last or (now or time.time()) - (st.get("ts") or 0) > max_age_h * H:
        return None
    return last


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    log = lambda s: print(s, flush=True)  # noqa: E731
    if argv and argv[0] == "vrati":
        if len(argv) < 3:
            sys.exit("upotreba: python3 run_arhiva.py vrati <baza> <tablica> [--date YYYYMMDD]")
        date = argv[argv.index("--date") + 1] if "--date" in argv else None
        db = argv[1][:-3] if argv[1].endswith(".db") else argv[1]
        if db not in ARCHIVE_DBS:
            sys.exit(f"nepoznata baza {argv[1]} (arhivira se: {', '.join(ARCHIVE_DBS)})")
        restore(paths(), db, argv[2], date, log)
        return 0
    if argv and argv[0] == "plan":   # the plan now, nothing moves (heavy reads: meant for the night)
        run(log=log, dry=True, force=True)
        return 0
    if "--auto" in argv:
        run(log=log)
        return 0
    sys.exit("upotreba: python3 run_arhiva.py --auto | plan | vrati <baza> <tablica> [--date YYYYMMDD]")


if __name__ == "__main__":
    sys.exit(main())
