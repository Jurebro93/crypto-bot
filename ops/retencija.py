"""Retention of two raw tables by the owner's rules (11.11., Jure: "ništa se stvarno ne briše bez moje potvrde nakon
što vidim brojke"). Each task has its own owner switch (trade/settings OWNER_SWITCHES, "uživo" = on, default off):
off = it only MEASURES and writes one log line of what it WOULD delete; on = it deletes, only 01-06 Zagreb, under the
heavy-job lock, at low priority (start.sh "low", the CPU guard may pause it: ops/cpuguard "retencija").

    python3 -m ops.retencija --auto    start.sh, after the hourly upkeep: hourly aggregate; the measurement at the first
                                       pass after a deploy and daily from 06:30 Zagreb (never 01-06); with a switch on,
                                       the deletion once a night inside 01-06
    python3 -m ops.retencija           the measurement now (log lines), nothing deleted

A. hype.db live_trades (switch live_trades_retention, G29)
   The table holds swaps of OTHER traders from the PumpPortal stream (live/pumpportal.py: the tokens we watch, the
   wallets we follow): sig, mint, wallet, side, sol, tokens, price_sol, mcap_sol, pool, ts, balance_after. Our own
   executed buys and sells are in trade.db (positions: sol_in, sol_back, fees_sol, opened_ts, closed_ts, reason;
   orders: signature, fee_lamports) and league.db (trades, real_trades): this module never writes those. A
   live_trades row is OUR swap when its wallet is ours (trade/wallet.addresses: the key, the address saved on
   /pravi-trade, SOLANA_PUBLIC_KEY) or its sig is a trade.db orders.signature; such rows are never deleted.
   Until 11.11. live/store.prune deleted EVERY row older than 48 h every 10 minutes (ours and the followed wallets'
   included, no aggregate); that delete is gone, this module is the only one.

   Hourly aggregate live_trades_hourly (mint, hour): buys, sells, buy_sol, sell_sol, distinct wallets, price open /
   high / low / close (price_sol > 0, open / close by time) and the last mcap_sol of the hour. Built in both modes for
   every finished hour (hour end + LATE_S), once (a final hour is never rebuilt, so a deletion can never shrink it),
   and never deleted. hype.db live_state 'hourly_upto': every hour before it is in the aggregate.

   Deleted with the switch on: rows older than KEEP_H (48 h) whose hour is in the aggregate, EXCEPT
     - our swaps (above);
     - wallets we follow or score (KEEP_WALLET_SOURCES, the exact tables): kol.db kv chain_hook (the Helius webhook
       list, what the feed follows) and league.db follows kind 'wallet' (followed), wallets.db wallets with
       scored_at (not 'izbačen'), dokazani, copy_rank kind 'wallet' (rang), precall_insiders, early.db
       precall_wallets (insajderi), preshill_wallets, group_member kind 'wallet' (grupe), kol.db insiders (2+
       tokens), kol_wallets, kol_ids, hype.db smart_wallets;
     - rows a reader with a window over 48 h needs (long_windows): kol/preshill reads every trade of a shill-network
       token from T0 - 6 h to T0 + 24 h (buyers of wallets nobody follows, tokens with T0 in the last 14 days:
       PRESHILL_DAYS, the window is the owner's to set), and the unmeasured group / pre-shill signals of the last
       3 days read the token's prices from ts to ts + 4 h (kol/groupdisc._candles).
   Readers of live_trades (grep 11.11.) and how far back they read:
     1 h          fast/checks, run_top (topcheck/safety, proposals/build), momentum/data, zonewatch/prices,
                  scan/market (per wallet: unique traders, wash; scan/market's mint list is aggregate-shaped)
     60-300 s     live/pulse window/dump (Autopilot dump exit)
     minutes      run_paper (followed buyers), wallets/dokazani.wallet_buy (strat), kol/precall copy, kol/groupdisc
                  incr (35 min), kol/preshill recent_buys (~1.5 h)
     <= 26 h      kol/crew.bought_before (KOL wallets: kept anyway)
     24 / 48 h    live/pulse.status, ui/pocetna (counts only)
     48 h         wallets/rang.live_points (prices per mint, seconds matter: the hourly aggregate is too coarse),
                  kol/precall build_buys (designed for 48 h; copies the buyers into early.db precall_buys)
     since entry  live/pulse.sold_fraction (strat 'insajderi': kol.db insiders wallets, kept anyway)
     > 48 h       kol/preshill (above; per wallet, kept by long_windows), kol/groupdisc + kol/preshill measure_due
                  (prices per mint, up to 3 d + 4 h, kept by long_windows), kol/preshill peaks (prices, the hourly
                  aggregate's high is enough past 24 h)
     whole table  bot rules of kol/precall, kol/groupdisc, kol/preshill (trades per wallet per minute / day: they
                  work on what is there), ui/mcpdata wallet history (one wallet, no window)
   (exits/fit.live_trades is a function over paper.db, not this table.)

B. tg.db posts text (switch tg_text_retention, G30)
   A post with a CA becomes kol.db calls rows (kol/collect.from_telegram: tweet_id 'tg:<channel>/<post>', token,
   handle 'tg:<channel>', ts, text[:600]); kol/snap measures mcap0 / r1h / r6h / r24h / max24 from DexScreener
   snapshots (kol.db snaps, kept 3 days), events.db call_outcomes change_4h / change_24h (night batch), minute.db
   call_path r60. The text of a post older than TG_KEEP_D (14 d, by post time and by the time we saw it) is deleted
   (UPDATE text = NULL; the row and its metadata stay, never a DELETE) only when every call of the post has all of
   REQUIRED (one source each is enough), or the post gave no call. A field no table has (11.11.: r15m and the 72-h
   peak) keeps the text of every post with a call until it is added (a column of that name in calls, or another
   source below). Readers of the text: learn/postai (last 6 h), kol/collect (new posts only), ui/izvori and
   tg/store.summary (newest 40 / 60); none reads text older than 14 days. Until 11.11. tg/store.prune deleted the
   rows without a CA and every text older than 30 days whatever the measurements; it does nothing now.
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import time

from ops import disk

D, H = 86400, 3600
KEEP_H = float(os.environ.get("RETENCIJA_LIVE_KEEP_H", "48"))
TG_KEEP_D = float(os.environ.get("RETENCIJA_TG_KEEP_D", "14"))
LATE_S = 1800                 # an hour is final this long after its end (the feed buffers rows while hype.db is busy)
AGG_MAX_HOURS = int(os.environ.get("RETENCIJA_AGG_MAX_HOURS", "48"))   # hours aggregated per hourly pass (catch-up)
TG_BATCH = 5000               # posts per UPDATE (rowid range)
PAUSE_S = 0.2                 # between two delete statements: the live feed and run_tg get the write lock
HEAVY_WAIT_S = 1200
SWITCH_LIVE = "live_trades_retention"
SWITCH_TG = "tg_text_retention"
STATE = ".retencija.json"
# 12.11. (Jure: "VACUUM / sažimanje hype.db (oko 250 MB) i events.db nakon rezanja wallet kopija na 7 dana"): once a
# night, after the deletions and after the events night batch (03:00 Zagreb, its retention cuts the wallet copies to
# 7 days), VACUUM of these files when at least COMPACT_WASTE of the file is dead space and the disk keeps
# COMPACT_MARGIN_MB free above the packed copy while it is written (the feeds keep writing meanwhile). Else the reason
# is logged and the next night tries again. ops/dbs.compact still runs hourly at its own 35 % threshold.
COMPACT_FILES = ("events", "hype")
COMPACT_FROM_H = 4            # Zagreb hour: after the events night batch
COMPACT_UNTIL = (5, 40)       # no new VACUUM after this (the window closes at 06:00)
COMPACT_WASTE = float(os.environ.get("RETENCIJA_COMPACT_WASTE", "0.10"))
COMPACT_MARGIN_MB = float(os.environ.get("RETENCIJA_COMPACT_MARGIN_MB", "250"))
DAILY_AT = (6, 30)
TZ = "Europe/Zagreb"
# long readers (module text): the owner sets these windows; the defaults are the readers' own
PRESHILL_DAYS = float(os.environ.get("RETENCIJA_PRESHILL_DAYS", "14"))   # kol/preshill DEFAULT days
PRESHILL_PRE_S, PRESHILL_POST_S = 6 * H, D                              # kol/preshill pre_window_s, post_s
MEASURE_DAYS, MEASURE_SPAN_S = 3, 4 * H                                  # groupdisc / preshill measure_due, _candles

DB_FILES = {"hype": ("HYPE_DB", "hype.db"), "wallets": ("WALLET_DB", "wallets.db"), "kol": ("KOL_DB", "kol.db"),
            "league": ("LEAGUE_DB", "league.db"), "early": ("EARLY_DB", "early.db"), "trade": ("TRADE_DB", "trade.db"),
            "tg": ("TG_DB", "tg.db"), "events": ("EVENTS_DB", "events.db"), "minute": ("MINUTE_DB", "minute.db")}

# (label in the log, database, query) - wallets whose live_trades rows are never deleted
CHAIN_HOOK = "SELECT value FROM kv WHERE key = 'chain_hook'"
KEEP_WALLET_SOURCES = (
    ("praćeni (Helius webhook)", "kol", CHAIN_HOOK),
    ("praćeni (natjecanje, Autopilot)", "league", "SELECT DISTINCT target FROM follows WHERE kind = 'wallet'"),
    ("ocijenjeni", "wallets", "SELECT wallet FROM wallets WHERE scored_at IS NOT NULL "
                              "AND COALESCE(labels, '') NOT LIKE '%izbačen%'"),
    ("dokazani", "wallets", "SELECT DISTINCT wallet FROM dokazani"),
    ("rang", "wallets", "SELECT target FROM copy_rank WHERE kind = 'wallet'"),
    ("insajderi", "wallets", "SELECT wallet FROM precall_insiders"),
    ("insajderi (kandidati)", "early", "SELECT wallet FROM precall_wallets"),
    ("insajderi (kol.db)", "kol", "SELECT wallet FROM insiders GROUP BY wallet HAVING COUNT(DISTINCT token) >= 2"),
    ("kupci prije shill mreže", "early", "SELECT wallet FROM preshill_wallets"),
    ("grupe", "early", "SELECT member FROM group_member WHERE kind = 'wallet'"),
    ("pametni", "hype", "SELECT wallet FROM smart_wallets"),
    ("KOL novčanici", "kol", "SELECT wallet FROM kol_wallets"),
    ("KOL identiteti", "kol", "SELECT wallet FROM kol_ids"),
)

# B: what a call needs before its post's text may go: (name, sources); one non-NULL source is enough.
# k = kol.db calls (the call row itself), e = events.db call_outcomes (mint + tweet_id), m = minute.db call_path
REQUIRED = (
    ("mint", (("k", "calls", "token"),)),
    ("autor", (("k", "calls", "handle"),)),
    ("vrijeme", (("k", "calls", "ts"),)),
    ("MC poziva", (("k", "calls", "mcap0"),)),
    ("r15m", (("k", "calls", "r15m"),)),
    ("r1h", (("k", "calls", "r1h"), ("m", "call_path", "r60"))),
    ("r4h", (("k", "calls", "r4h"), ("e", "call_outcomes", "change_4h"))),
    ("r24h", (("k", "calls", "r24h"), ("e", "call_outcomes", "change_24h"))),
    ("vrh 72h", (("k", "calls", "max72h"), ("k", "calls", "max72"), ("e", "call_outcomes", "max_72h"))),
)

AGG_SCHEMA = """CREATE TABLE IF NOT EXISTS live_trades_hourly (
    mint TEXT, hour INTEGER, buys INTEGER, sells INTEGER, buy_sol REAL, sell_sol REAL, wallets INTEGER,
    open_px REAL, high_px REAL, low_px REAL, close_px REAL, last_mcap_sol REAL, trades INTEGER, built_ts INTEGER,
    PRIMARY KEY (mint, hour));
CREATE INDEX IF NOT EXISTS live_trades_hourly_hour ON live_trades_hourly (hour);
CREATE TABLE IF NOT EXISTS live_state (key TEXT PRIMARY KEY, value TEXT);"""
_IN_HOUR = "x.mint = t.mint AND x.ts >= :h AND x.ts < :e"
AGG_SQL = f"""INSERT OR REPLACE INTO live_trades_hourly
SELECT t.mint, :h, SUM(t.side = 'buy'), SUM(t.side = 'sell'),
    COALESCE(SUM(CASE WHEN t.side = 'buy' THEN t.sol END), 0), COALESCE(SUM(CASE WHEN t.side = 'sell' THEN t.sol END), 0),
    COUNT(DISTINCT t.wallet),
    (SELECT x.price_sol FROM live_trades x WHERE {_IN_HOUR} AND x.price_sol > 0 ORDER BY x.ts, x.rowid LIMIT 1),
    MAX(CASE WHEN t.price_sol > 0 THEN t.price_sol END), MIN(CASE WHEN t.price_sol > 0 THEN t.price_sol END),
    (SELECT x.price_sol FROM live_trades x WHERE {_IN_HOUR} AND x.price_sol > 0 ORDER BY x.ts DESC, x.rowid DESC LIMIT 1),
    (SELECT x.mcap_sol FROM live_trades x WHERE {_IN_HOUR} AND x.mcap_sol IS NOT NULL
     ORDER BY x.ts DESC, x.rowid DESC LIMIT 1),
    COUNT(*), :now
FROM live_trades t WHERE t.ts >= :h AND t.ts < :e GROUP BY t.mint"""

# the three "never delete" tests on a live_trades row t (temp tables filled by _keep_tables)
OURS = "(COALESCE(t.wallet, '') IN (SELECT w FROM temp.r_our) OR COALESCE(t.sig, '') IN (SELECT s FROM temp.r_sig))"
FOLLOWED = "COALESCE(t.wallet, '') IN (SELECT w FROM temp.r_keep)"
READERS = "EXISTS (SELECT 1 FROM temp.r_win k WHERE k.mint = t.mint AND t.ts BETWEEN k.lo AND k.hi)"


# ---------- small helpers ----------------------------------------------------------------------------------------
def paths(data_dir=None):
    """{key: database path}: the env override (only without data_dir), else DATA_DIR/<file>."""
    d = data_dir or disk.DATA_DIR
    return {k: (None if data_dir else os.environ.get(env)) or os.path.join(d, name) for k, (env, name) in DB_FILES.items()}


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


def _rw(path, timeout=60):
    con = sqlite3.connect(path, timeout=timeout)
    con.execute(f"PRAGMA busy_timeout = {timeout * 1000}")
    return con


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _has(con, table, schema="main"):
    return bool(_q(con, f"SELECT 1 FROM {schema}.sqlite_master WHERE type = 'table' AND name = ?", (table,)))


def _mb(b):
    return f"{(b or 0) / 1e6:.1f}"


def _n(x):
    return f"{int(x or 0):,}".replace(",", ".")


def _zagreb(ts):
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(ts, ZoneInfo(TZ))


def in_night(now=None, default=True):
    """True inside the heavy-job night window (ops/heavy.NIGHT, 01-06 Zagreb by default); `default` without a window
    (heavy jobs may then run any time, the measurement then never waits)."""
    from ops import heavy
    win = heavy.night_hours()
    if win is None:
        return default
    h = _zagreb(now or time.time()).hour
    a, b = win
    return a <= h < b if a < b else (h >= a or h < b)


def switch_on(name, trade_db=None):
    """True when the owner switched `name` on ("live"); anything unreadable is off (nothing is deleted)."""
    try:
        from trade import settings
        return settings.flag(name, path=trade_db) == "live"
    except Exception:  # noqa: BLE001
        return False


def table_bytes(con, table, schema="main"):
    """(bytes of the table with its indexes or None without dbstat, rows)."""
    rows = (_q(con, f"SELECT COUNT(*) FROM {schema}.{table}") or [(0,)])[0][0]
    names = [r[0] for r in _q(con, f"SELECT name FROM {schema}.sqlite_master WHERE tbl_name = ?", (table,))]
    if not names:
        return None, rows
    q = ",".join("?" * len(names))
    for sql in (f"SELECT SUM(pgsize) FROM dbstat('{schema}', 1) WHERE name IN ({q})",
                f"SELECT SUM(pgsize) FROM dbstat('{schema}') WHERE name IN ({q})"):
        try:
            return con.execute(sql, names).fetchone()[0], rows
        except sqlite3.Error:
            continue
    return None, rows


def row_bytes(con):
    """Bytes one live_trades row takes with its indexes: dbstat when the build has it, else from the text lengths."""
    b, n = table_bytes(con, "live_trades")
    if b and n:
        return b / n
    r = (_q(con, "SELECT AVG(LENGTH(sig) + LENGTH(mint) + COALESCE(LENGTH(wallet), 0) + LENGTH(side) + "
                 "COALESCE(LENGTH(pool), 0)), AVG(LENGTH(sig) + LENGTH(mint)), AVG(LENGTH(mint)) FROM "
                 "(SELECT sig, mint, wallet, side, pool FROM live_trades LIMIT 5000)") or [(None, None, None)])[0]
    data, pk, mi = (r[0] or 230) + 60, (r[1] or 132) + 15, (r[2] or 44) + 25
    return (data + pk + mi + 22) * 1.15   # row + PK (sig, mint) + (mint, ts) + (ts) + page slack


# ---------- A. live_trades ---------------------------------------------------------------------------------------
def our_wallets(p):
    """(our addresses, signatures of our orders): trade/wallet.addresses and trade.db orders.signature."""
    addrs, sigs = set(), set()
    tc = _ro(p.get("trade"))
    try:
        from trade import wallet as tw
        addrs |= {a for a in tw.addresses(tc) if a}
    except Exception:  # noqa: BLE001 - no key / no table: the env address below still counts
        pass
    if os.environ.get("SOLANA_PUBLIC_KEY"):
        addrs.add(os.environ["SOLANA_PUBLIC_KEY"])
    sigs |= {s for (s,) in _q(tc, "SELECT signature FROM orders WHERE COALESCE(signature, '') != ''")}
    if tc is not None:
        tc.close()
    return addrs, sigs


def keep_wallets(p):
    """(every wallet we follow or score, {label: wallets}) from KEEP_WALLET_SOURCES."""
    out, per = set(), {}
    for label, db, sql in KEEP_WALLET_SOURCES:
        con = _ro(p.get(db))
        rows = _q(con, sql)
        if con is not None:
            con.close()
        got = set()
        for (v,) in rows:
            if sql == CHAIN_HOOK:
                try:
                    got |= {w for w in (json.loads(v or "{}").get("wallets") or []) if w}
                except (ValueError, AttributeError):
                    pass
            elif v:
                got.add(v)
        per[label] = len(got)
        out |= got
    return out, per


def _preshill_windows():
    try:
        from kol import preshill
        c = preshill.config()
        return float(c["days"]), int(c["pre_window_s"]), int(c["post_s"])
    except Exception:  # noqa: BLE001
        return PRESHILL_DAYS, PRESHILL_PRE_S, PRESHILL_POST_S


def long_windows(p, now):
    """[(mint, lo, hi, reader)]: rows of `mint` with lo <= ts <= hi a reader with a window over 48 h still needs."""
    out = []
    ec = _ro(p.get("early"))
    if ec is None:
        return out
    try:
        days, pre, post = _preshill_windows()
        if "RETENCIJA_PRESHILL_DAYS" in os.environ:   # the owner's window
            days = PRESHILL_DAYS
        for tok, t0, ws in _q(ec, "SELECT token, t0, window_start FROM preshill_tokens WHERE t0 >= ?",
                              (int(now - days * D),)):
            out.append((tok, int(ws if ws is not None else t0 - pre), int(t0) + post, "kupci prije shill mreže"))
        for table, reader in (("group_signals", "mjerenje grupa"), ("group_traces", "mjerenje grupa"),
                              ("preshill_signals", "mjerenje shill mreže")):
            for tok, ts in _q(ec, f"SELECT token, ts FROM {table} WHERE measured_ts IS NULL AND ts >= ?",
                              (int(now - MEASURE_DAYS * D),)):
                out.append((tok, int(ts) - 60, int(ts) + MEASURE_SPAN_S, reader))
    finally:
        ec.close()
    return out


def _keep_tables(con, ours, sigs, keep, windows):
    con.execute("CREATE TEMP TABLE IF NOT EXISTS r_our (w TEXT PRIMARY KEY)")
    con.execute("CREATE TEMP TABLE IF NOT EXISTS r_sig (s TEXT PRIMARY KEY)")
    con.execute("CREATE TEMP TABLE IF NOT EXISTS r_keep (w TEXT PRIMARY KEY)")
    con.execute("CREATE TEMP TABLE IF NOT EXISTS r_win (mint TEXT, lo INTEGER, hi INTEGER)")
    con.execute("CREATE INDEX IF NOT EXISTS temp.r_win_mint ON r_win (mint, lo)")
    for t in ("r_our", "r_sig", "r_keep", "r_win"):
        con.execute(f"DELETE FROM temp.{t}")
    con.executemany("INSERT OR IGNORE INTO temp.r_our VALUES (?)", [(w,) for w in ours])
    con.executemany("INSERT OR IGNORE INTO temp.r_sig VALUES (?)", [(s,) for s in sigs])
    con.executemany("INSERT OR IGNORE INTO temp.r_keep VALUES (?)", [(w,) for w in keep])
    con.executemany("INSERT INTO temp.r_win VALUES (?,?,?)", [(m, lo, hi) for m, lo, hi, _r in windows])


def ensure_hourly(con):
    con.executescript(AGG_SCHEMA)


def _state(con, key):
    r = _q(con, "SELECT value FROM live_state WHERE key = ?", (key,))
    try:
        return int(float(r[0][0])) if r and r[0][0] is not None else None
    except (TypeError, ValueError):
        return None


def build_hourly(path, now=None, max_hours=AGG_MAX_HOURS):
    """Aggregate every finished hour not aggregated yet (at most max_hours; None = all). -> (hours, rows written).
    An hour is built once: hourly_upto only moves forward, and a missing marker never goes below the aggregate's
    newest hour, so an hour whose raw rows were partly deleted is never built again."""
    if not _exists(path):
        return 0, 0
    now = int(now or time.time())
    con = _rw(path)
    try:
        if not _has(con, "live_trades"):
            return 0, 0
        ensure_hourly(con)
        upto = _state(con, "hourly_upto")
        if upto is None:
            mn = con.execute("SELECT MIN(ts) FROM live_trades").fetchone()[0]
            top = con.execute("SELECT MAX(hour) FROM live_trades_hourly").fetchone()[0]
            if mn is None:
                return 0, 0
            upto = max(int(mn) - int(mn) % H, (top + H) if top is not None else 0)
        last = (now - LATE_S) - (now - LATE_S) % H   # hours starting before this have ended LATE_S ago
        hours = rows = 0
        h = upto
        while h < last and (max_hours is None or hours < max_hours):
            nxt = con.execute("SELECT MIN(ts) FROM live_trades WHERE ts >= ?", (h,)).fetchone()[0]
            if nxt is None or nxt >= last:   # nothing more in finished hours: jump to the end
                h = last
                break
            h = max(h, int(nxt) - int(nxt) % H)
            con.execute("BEGIN IMMEDIATE")
            rows += con.execute(AGG_SQL, {"h": h, "e": h + H, "now": now}).rowcount
            con.execute("INSERT OR REPLACE INTO live_state VALUES ('hourly_upto', ?)", (str(h + H),))
            con.commit()
            hours += 1
            h += H
        if h > upto and (_state(con, "hourly_upto") or 0) < h:
            con.execute("INSERT OR REPLACE INTO live_state VALUES ('hourly_upto', ?)", (str(h),))
            con.commit()
        return hours, rows
    finally:
        con.close()


def _keep_inputs(p, now):
    ours, sigs = our_wallets(p)
    keep, per = keep_wallets(p)
    return ours, sigs, keep, per, long_windows(p, now)


def measure_live(p, now=None, keep_h=KEEP_H):
    """What the deletion would do now (nothing is written): {old, old_b, ours, wallets, readers, gone, gone_b, agg,
    agg_b, per, windows}. None without the table."""
    now = int(now or time.time())
    cut = now - int(keep_h * H)
    hc = _ro(p.get("hype"))
    if hc is None or not _has(hc, "live_trades"):
        if hc is not None:
            hc.close()
        return None
    try:
        ours, sigs, keep, per, windows = _keep_inputs(p, now)
        _keep_tables(hc, ours, sigs, keep, windows)
        got = dict(hc.execute(f"""SELECT CASE WHEN {OURS} THEN 'ours' WHEN {FOLLOWED} THEN 'wallets'
                                          WHEN {READERS} THEN 'readers' ELSE 'gone' END AS k, COUNT(*)
                                  FROM live_trades t WHERE t.ts < ? GROUP BY k""", (cut,)).fetchall())
        rb = row_bytes(hc)
        old = sum(got.values())
        agg_b, agg = (table_bytes(hc, "live_trades_hourly") if _has(hc, "live_trades_hourly") else (0, 0))
        if agg and not agg_b:
            agg_b = agg * 190   # mint + 12 numbers + the primary key and hour index
        by_reader = {}
        for _m, _lo, _hi, r in windows:
            by_reader[r] = by_reader.get(r, 0) + 1
        return {"cut": cut, "keep_h": keep_h, "old": old, "old_b": old * rb, "ours": got.get("ours", 0),
                "wallets": got.get("wallets", 0), "readers": got.get("readers", 0), "gone": got.get("gone", 0),
                "gone_b": got.get("gone", 0) * rb, "row_b": rb, "agg": agg, "agg_b": agg_b, "per": per,
                "n_keep": len(keep), "n_ours": len(ours), "n_sigs": len(sigs), "windows": by_reader}
    finally:
        hc.close()


def live_lines(m, on=False):
    """The log lines of measure_live (the owner's wording)."""
    if m is None:
        return ["retencija live_trades: hype.db nema tablicu live_trades, nema se što mjeriti"]
    kept = m["ours"] + m["wallets"] + m["readers"]
    head = "prekidač uključen, briše noću 01-06" if on else "samo mjerenje"
    out = [f"retencija live_trades ({head}): redova stariji od {m['keep_h']:.0f} h {_n(m['old'])} ({_mb(m['old_b'])} MB), "
           f"od toga ostaje (praćeni novčanici / naši swapovi) {_n(kept)} (praćeni i ocjenjivani novčanici "
           f"{_n(m['wallets'])}, naši swapovi {_n(m['ours'])}, čitači s duljim prozorom {_n(m['readers'])}); "
           f"obrisalo bi {_n(m['gone'])} redova ≈ {_mb(m['gone_b'])} MB; satni agregat {_n(m['agg'])} redova ≈ "
           f"{_mb(m['agg_b'])} MB"]
    per = ", ".join(f"{k} {_n(v)}" for k, v in m["per"].items() if v) or "nijedan"
    win = ", ".join(f"{k} {_n(v)}" for k, v in m["windows"].items()) or "nijedan"
    out.append(f"retencija live_trades: zadržani novčanici {_n(m['n_keep'])} ({per}); naši: {_n(m['n_ours'])} adresa, "
               f"{_n(m['n_sigs'])} potpisa naloga; čitači s duljim prozorom (prozori tokena): {win}")
    return out


def delete_live(p, now=None, log=print, stop=None, keep_h=KEEP_H):
    """With the switch on (the caller checks it): the hourly aggregate is completed, then rows older than keep_h whose
    hour is aggregated go, one hour per statement, except OURS / FOLLOWED / READERS. -> {gone, gone_b, ...}."""
    now = int(now or time.time())
    path = p.get("hype")
    if not _exists(path):
        return None
    build_hourly(path, now, max_hours=None)
    hc = _rw(path)
    try:
        if not _has(hc, "live_trades"):
            return None
        hc.execute("CREATE INDEX IF NOT EXISTS live_trades_ts ON live_trades (ts)")   # ops/dbs makes it at start-up
        hc.commit()
        upto = _state(hc, "hourly_upto") or 0
        lim = min(now - int(keep_h * H), upto)
        ours, sigs, keep, _per, windows = _keep_inputs(p, now)
        _keep_tables(hc, ours, sigs, keep, windows)
        hc.commit()
        rb = row_bytes(hc)
        gone, stopped, lo = 0, False, 0
        while True:   # one hour per statement; hours without rows are jumped over (kept rows stay for good)
            nxt = hc.execute("SELECT MIN(ts) FROM live_trades WHERE ts >= ? AND ts < ?", (lo, lim)).fetchone()[0]
            if nxt is None:
                break
            if stop and stop():
                stopped = True
                break
            lo = int(nxt) - int(nxt) % H
            hi = min(lo + H, lim)
            k = hc.execute(f"""DELETE FROM live_trades WHERE rowid IN (SELECT t.rowid FROM live_trades t
                WHERE t.ts >= ? AND t.ts < ? AND NOT {OURS} AND NOT {FOLLOWED} AND NOT {READERS})""", (lo, hi)).rowcount
            hc.commit()
            gone += k
            lo = hi
            if k and PAUSE_S:
                time.sleep(PAUSE_S)
        left = hc.execute("SELECT COUNT(*) FROM live_trades WHERE ts < ?", (lim,)).fetchone()[0]
        agg = hc.execute("SELECT COUNT(*) FROM live_trades_hourly").fetchone()[0]
        out = {"gone": gone, "gone_b": gone * rb, "left": left, "agg": agg, "stopped": stopped, "lim": lim}
        log(f"retencija live_trades (brisanje): obrisano {_n(gone)} redova ≈ {_mb(gone * rb)} MB (starijih od "
            f"{keep_h:.0f} h, sat u satnom agregatu); ostaje starijih {_n(left)} (naši swapovi, praćeni i ocjenjivani "
            f"novčanici, čitači s duljim prozorom); satni agregat {_n(agg)} redova"
            + ("; prekinuto na kraju noćnog prozora, nastavlja sljedeće noći" if stopped else "")
            + ". Oslobođene stranice baza odmah ponovno koristi; datoteka se smanjuje tek sažimanjem (VACUUM).")
        return out
    finally:
        hc.close()


# ---------- B. tg.db posts text ----------------------------------------------------------------------------------
def _attach(con, p):
    """Attach kol.db (k), events.db (e), minute.db (m) read-only; -> {alias: {table: set(columns)}}."""
    got = {}
    for alias, key, tables in (("k", "kol", ("calls",)), ("e", "events", ("call_outcomes",)),
                               ("m", "minute", ("call_path",))):
        path = p.get(key)
        if not _exists(path):
            continue
        try:
            con.execute(f"ATTACH DATABASE ? AS {alias}", (f"file:{path}?mode=ro",))
        except sqlite3.Error:
            continue
        got[alias] = {t: {r[1] for r in _q(con, f"PRAGMA {alias}.table_info({t})")} for t in tables}
    return got


def _call_cond(att, existing_only=False):
    """(SQL true when one call row c has every REQUIRED field, [fields no table has])."""
    conds, missing = [], []
    for name, srcs in REQUIRED:
        alts = []
        for alias, table, col in srcs:
            if col not in (att.get(alias) or {}).get(table, ()):
                continue
            if alias == "k":
                alts.append(f"NULLIF(c.{col}, '') IS NOT NULL")
            elif alias == "e":
                alts.append(f"EXISTS (SELECT 1 FROM e.call_outcomes x WHERE x.mint = c.token AND x.tweet_id = c.tweet_id "
                            f"AND x.{col} IS NOT NULL)")
            else:
                alts.append(f"EXISTS (SELECT 1 FROM m.call_path x WHERE x.tweet_id = c.tweet_id AND x.token = c.token "
                            f"AND x.{col} IS NOT NULL)")
        if alts:
            conds.append("(" + " OR ".join(alts) + ")")
        else:
            missing.append(name)
            if not existing_only:
                conds.append("0")
    return " AND ".join(conds) or "1", missing


def _tg_parts(att):
    """(n calls of the post, n complete, n complete on the fields that exist, missing fields) as SQL over `posts`."""
    if "calls" not in (att.get("k") or {}) or not att["k"]["calls"]:
        n = "(CASE WHEN COALESCE(posts.cas, '') != '' THEN 1 ELSE 0 END)"   # kol.db unreadable: a CA post waits
        return n, "0", "0", ["kol.db calls (nečitljiv)"]
    tid = "'tg:' || posts.channel || '/' || posts.post"
    full, missing = _call_cond(att)
    have, _m = _call_cond(att, existing_only=True)
    n = f"(SELECT COUNT(*) FROM k.calls c WHERE c.tweet_id = {tid})"
    ok = f"(SELECT COUNT(*) FROM k.calls c WHERE c.tweet_id = {tid} AND {full})"
    ok2 = f"(SELECT COUNT(*) FROM k.calls c WHERE c.tweet_id = {tid} AND {have})"
    return n, ok, ok2, missing


OLD_POST = "posts.text IS NOT NULL AND COALESCE(posts.ts, posts.seen_ts) < :cut AND posts.seen_ts < :cut"


def measure_tg(p, now=None, keep_d=TG_KEEP_D):
    """{old, done, nocall, waiting, bytes, done_have, bytes_have, missing}: posts with text older than keep_d; None
    without tg.db posts. Nothing is written."""
    now = int(now or time.time())
    path = p.get("tg")
    if not _exists(path):
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        if not _has(con, "posts"):
            return None
        att = _attach(con, p)
        n, ok, ok2, missing = _tg_parts(att)
        r = con.execute(f"""SELECT COUNT(*), SUM(n = 0), SUM(n > 0 AND ok = n), SUM(n > 0 AND ok < n),
                                   SUM(CASE WHEN n = 0 OR ok = n THEN b ELSE 0 END), SUM(n > 0 AND ok2 = n),
                                   SUM(CASE WHEN n > 0 AND ok2 = n THEN b ELSE 0 END)
                            FROM (SELECT {n} AS n, {ok} AS ok, {ok2} AS ok2, LENGTH(CAST(posts.text AS BLOB)) AS b
                                  FROM posts WHERE {OLD_POST})""", {"cut": now - int(keep_d * D)}).fetchone()
        return {"keep_d": keep_d, "old": r[0] or 0, "nocall": r[1] or 0, "done": r[2] or 0, "waiting": r[3] or 0,
                "bytes": r[4] or 0, "done_have": r[5] or 0, "bytes_have": r[6] or 0, "missing": missing}
    finally:
        con.close()


def tg_lines(m, on=False):
    if m is None:
        return ["tg tekst: tg.db nema objava, nema se što mjeriti"]
    head = "prekidač uključen, briše noću 01-06" if on else "samo mjerenje"
    line = (f"tg tekst ({head}): objava starijih od {m['keep_d']:.0f} d {_n(m['old'])}, s potpunim mjerenjima "
            f"{_n(m['done'])}, bez poziva {_n(m['nocall'])}, čeka mjerenja {_n(m['waiting'])}; tekst bi se obrisao za "
            f"{_n(m['done'] + m['nocall'])} objava ≈ {_mb(m['bytes'])} MB (nakon VACUUM-a)")
    if m["missing"]:
        line += (f"; u bazi nema polja: {', '.join(m['missing'])} (dok se ne dodaju, tekst objava s pozivima ostaje; "
                 f"s postojećim poljima potpuno izmjereno bi bilo {_n(m['done_have'])} objava, još "
                 f"≈ {_mb(m['bytes_have'])} MB)")
    return [line]


def delete_tg(p, now=None, log=print, stop=None, keep_d=TG_KEEP_D, compact=True):
    """With the switch on (the caller checks it): UPDATE posts SET text = NULL for the posts measure_tg counts as
    done or without a call, by rowid ranges; rows are never deleted. Then tg.db is compacted when it pays."""
    now = int(now or time.time())
    path = p.get("tg")
    if not _exists(path):
        return None
    con = sqlite3.connect(f"file:{path}", uri=True, timeout=60)
    con.execute("PRAGMA busy_timeout = 60000")
    try:
        if not _has(con, "posts"):
            return None
        att = _attach(con, p)
        n, ok, _ok2, _missing = _tg_parts(att)
        top = con.execute("SELECT MAX(rowid) FROM posts").fetchone()[0] or 0
        cut = now - int(keep_d * D)
        done = freed = 0
        stopped = False
        for lo in range(0, top + 1, TG_BATCH):
            if stop and stop():
                stopped = True
                break
            where = f"rowid >= :lo AND rowid < :hi AND {OLD_POST} AND ({n} = 0 OR {ok} = {n})"
            args = {"lo": lo, "hi": lo + TG_BATCH, "cut": cut}
            freed += con.execute(f"SELECT COALESCE(SUM(LENGTH(CAST(text AS BLOB))), 0) FROM posts WHERE {where}",
                                 args).fetchone()[0]
            done += con.execute(f"UPDATE posts SET text = NULL WHERE {where}", args).rowcount
            con.commit()
            if PAUSE_S:
                time.sleep(PAUSE_S)
    finally:
        con.close()
    packed = None
    if compact and done and not stopped:
        try:
            from ops import dbs
            packed = dbs.compact(path, min_waste=0.10)
        except Exception as e:  # noqa: BLE001 - the text is gone either way; the pages come back at the next compact
            packed = f"nije sažeto ({type(e).__name__})"
    log(f"tg tekst (brisanje): tekst obrisan za {_n(done)} objava ≈ {_mb(freed)} MB (red i metapodaci ostaju)"
        + (f"; sažimanje {packed}" if packed else "")
        + ("; prekinuto na kraju noćnog prozora, nastavlja sljedeće noći" if stopped else ""))
    return {"done": done, "freed": freed, "stopped": stopped, "packed": packed}


# ---------- when: state, the measurement, the night ------------------------------------------------------------
def state_path(data_dir=None):
    return os.path.join(data_dir or disk.DATA_DIR, STATE)


def load_state(data_dir=None):
    try:
        with open(state_path(data_dir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st, data_dir=None):
    p = state_path(data_dir)
    try:
        with open(p + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def due(st, now=None, commit=None):
    """'deploy' | 'dnevno' | None: the measurement at the first pass after a deploy (commit marker), else once a day
    from 06:30 Zagreb; never inside the night window (ops/diskreport.due's rule)."""
    now = now or time.time()
    if in_night(now, default=False):
        return None
    commit = os.environ.get("RENDER_GIT_COMMIT", "") if commit is None else commit
    if not st or st.get("commit", "") != commit:
        return "deploy"
    z = _zagreb(now)
    if (z.hour, z.minute) >= DAILY_AT and st.get("daily") != z.date().isoformat():
        return "dnevno"
    return None


def measure(p, now=None, log=print):
    """Both measurements, their log lines. -> {"live": ..., "tg": ...}."""
    on_live, on_tg = switch_on(SWITCH_LIVE, p.get("trade")), switch_on(SWITCH_TG, p.get("trade"))
    out = {}
    for key, fn, lines, on in (("live", measure_live, live_lines, on_live), ("tg", measure_tg, tg_lines, on_tg)):
        try:
            out[key] = fn(p, now)
            for ln in lines(out[key], on):
                log(ln)
        except Exception as e:  # noqa: BLE001 - one task must not stop the other
            log(f"retencija {key}: mjerenje nije uspjelo: {type(e).__name__}: {str(e)[:160]}")
    return out


def compact_due(st, now):
    """True once a night from COMPACT_FROM_H Zagreb until COMPACT_UNTIL, inside the night window."""
    z = _zagreb(now)
    return (in_night(now, default=False) and z.hour >= COMPACT_FROM_H and (z.hour, z.minute) < COMPACT_UNTIL
            and st.get("compacted") != z.date().isoformat())


def compact_night(p, now=None, log=print, st=None, compact=None):
    """12.11.: VACUUM of COMPACT_FILES (above); the caller holds the heavy-job lock. -> {name: result or reason}."""
    from ops import dbs
    compact = compact or dbs.compact
    now = int(now or time.time())
    st = st if st is not None else {}
    out, t0 = {}, time.time()
    for k in COMPACT_FILES:
        path = p.get(k)
        if not _exists(path):
            continue
        z = _zagreb(now + time.time() - t0)   # a VACUUM takes minutes: the clock moves on
        if (z.hour, z.minute) >= COMPACT_UNTIL:
            out[k] = "preskočeno: kraj noćnog prozora"
            continue
        why = []
        try:
            res = compact(path, min_waste=COMPACT_WASTE, margin_mb=COMPACT_MARGIN_MB, why=why)
        except Exception as e:  # noqa: BLE001 - one file must not stop the other; the next night tries again
            res, why = None, [f"{type(e).__name__}: {str(e)[:120]}"]
        out[k] = res or ("nije sažeto: " + ("; ".join(why) or "?"))
    st["compacted"] = _zagreb(now).date().isoformat()
    log("retencija: noćno sažimanje (VACUUM): " + "; ".join(f"{k}.db {v}" for k, v in out.items())
        + f" | disk slobodno {disk.free_mb() or 0:.0f} MB")
    return out


def night(p, now=None, log=print, st=None, stop=None):
    """With a switch on, inside the night window, once a night: the deletion under the heavy-job lock; from
    COMPACT_FROM_H, once a night, the VACUUM of COMPACT_FILES (compact_night)."""
    now = int(now or time.time())
    st = st if st is not None else {}
    want = [k for k, name in (("live", SWITCH_LIVE), ("tg", SWITCH_TG)) if switch_on(name, p.get("trade"))]
    day = _zagreb(now).date().isoformat()
    want = [k for k in want if st.get(f"deleted_{k}") != day]
    pack = compact_due(st, now)
    if (not want and not pack) or not in_night(now):
        return {}
    from ops import heavy
    t0 = time.time()
    stop = stop or (lambda: not in_night(now + time.time() - t0))   # the window closes at 06:00: stop between statements
    out = {}
    with heavy.slot(wait=HEAVY_WAIT_S, label="retencija (brisanje)") as got:
        if not got:
            log("retencija: brava teških poslova zauzeta, brisanje pokušavam sljedeći sat")
            return {}
        for k in want:
            try:
                out[k] = (delete_live if k == "live" else delete_tg)(p, now, log, stop)
                if out[k] is not None and not out[k].get("stopped"):
                    st[f"deleted_{k}"] = day
            except Exception as e:  # noqa: BLE001
                log(f"retencija {k}: brisanje nije uspjelo: {type(e).__name__}: {str(e)[:160]}")
        if pack and not stop():
            out["compact"] = compact_night(p, now, log, st)
    return out


def run_auto(p=None, now=None, log=print, data_dir=None, commit=None):
    """--auto: the hourly aggregate; the measurement when due(); the night deletion when a switch is on."""
    p = p or paths(data_dir)
    now = int(now or time.time())
    out = {}
    try:
        out["agg"] = build_hourly(p.get("hype"), now)
    except sqlite3.Error as e:   # a busy hype.db: the next hour catches up
        log(f"retencija: satni agregat preskočen ({str(e)[:80]})")
    st = load_state(data_dir)
    why = due(st, now, commit)
    if why:
        log(f"retencija: mjerenje ({'prvi prolaz nakon deploya' if why == 'deploy' else 'dnevno od 06:30'})")
        out["measure"] = measure(p, now, log)
        st["commit"] = os.environ.get("RENDER_GIT_COMMIT", "") if commit is None else commit
        z = _zagreb(now)
        if (z.hour, z.minute) >= DAILY_AT:
            st["daily"] = z.date().isoformat()
        st["ts"] = now
    out["night"] = night(p, now, log, st)
    save_state(st, data_dir)
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    log = lambda s: print(s, flush=True)  # noqa: E731
    if "--auto" in argv:
        run_auto(log=log)
        return 0
    p = paths()
    measure(p, log=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
