"""Data the tool collected but cannot use any more goes; what could still earn money stays (Jure, 8.11.2026).

Runs inside ops/dbs.retention (start-up and once an hour). DATA_PRUNE=dry (default) only COUNTS what each rule would
delete and prints it; DATA_PRUNE=on deletes. Every rule, with what the 8.11. audit found behind it:

kol.db
  w_pozivi      swaps of tracked wallets without a known X account were copied into `calls` as pseudo-calls
                ('w:<6 chars>'): 572,899 of 744,088 rows, nothing reads them except the wallet page; GeckoTerminal
                measured them instead of real X/Telegram calls (39,743 of 40,772 Telegram calls never measured).
                kol/collect.from_chain no longer writes them; rows older than W_KEEP_DAYS go.
  neaktivni_x   X accounts last seen 30+ days ago with 0 measured calls (785 accounts, 1,274 calls): never scored,
                never shown; they only inflate "Influenceri (X)". Account and its calls go.
wallets.db
  gubitnici     wallets scored as losers (tier D: bots or 10+ closed trades without profit) or inactive 30+ days
                without a profitable record: 2,461 tier-D wallets held 989,493 of 1,764,256 trade rows (56% of the
                937 MB file). Their trade rows go, the summary row stays (label 'izbačen' keeps them out of the
                scoring queue, so no Helius credits are spent on them again; 28,570 credits went to re-scoring
                losers in the week before). Profitable wallets (3+ closed, realized > 0) and wallets younger than
                YOUNG_DAYS keep everything.
hype.db
  chain         chain_trades / chain_transfers older than CHAIN_KEEP_DAYS (was 30; the strategies, insiders and
                convergence read the last hours, masovno the last day).
  mrtvi_tokeni  price snapshots and detail rows of tokens whose pair vanished (token_status.has_pair = 0), older
                than DEAD_KEEP_DAYS: the learning loops labelled them long ago.
paper.db
  tikovi        price ticks of tokens the demo never traded, older than UNTRADED_TICK_DAYS (1,717,785 of 2,143,400
                ticks were such; learn/shadow reads 72 h back). Ticks of traded tokens keep paper/config.json
                ticks_keep_days.

Growth watch: the row counts of the biggest tables are kept in DATA_DIR/.rows.json; a table that grew by more than
GROWTH_WARN rows since the last hourly run is named in the log ("raste brzo"), so the next pile of unused data is
seen in a day, not after a month.
"""
import json
import os
import sqlite3
import time

from ops import disk

W_KEEP_DAYS = float(os.environ.get("PRUNE_W_KEEP_DAYS", "2"))   # only the wallet page reads them; chain_trades keeps the swaps
INACTIVE_DAYS = float(os.environ.get("PRUNE_INACTIVE_DAYS", "30"))
YOUNG_DAYS = float(os.environ.get("PRUNE_YOUNG_DAYS", "14"))
CHAIN_KEEP_DAYS = float(os.environ.get("PRUNE_CHAIN_KEEP_DAYS", "14"))
DEAD_KEEP_DAYS = float(os.environ.get("PRUNE_DEAD_KEEP_DAYS", "14"))
UNTRADED_TICK_DAYS = float(os.environ.get("PRUNE_UNTRADED_TICK_DAYS", "4"))
GROWTH_WARN = int(os.environ.get("PRUNE_GROWTH_WARN", "30000"))   # rows per hour
BATCH = 20000
LABEL = "izbačen"
D = 86400


def on():
    """True when DATA_PRUNE says delete; anything else (default 'dry') only counts."""
    return os.environ.get("DATA_PRUNE", "dry").strip().lower() in ("on", "1", "true", "da")


def _con(path, timeout=60):
    con = sqlite3.connect(path, timeout=timeout)
    con.execute(f"PRAGMA busy_timeout={timeout * 1000}")
    return con


def _exists(path):
    return path and os.path.exists(path) and os.path.getsize(path) > 0


def _delete(con, table, where, params=(), batch=BATCH):
    """Count, then (when on) delete in batches by rowid so no single transaction holds the file for long."""
    n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]
    if not n or not on():
        return n
    while True:
        k = con.execute(f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} WHERE {where} LIMIT {batch})",
                        params).rowcount
        con.commit()
        if k < batch:
            break
    return n


def kol(path, now=None):
    """{'w_pozivi': n, 'neaktivni_x': n, 'neaktivni_x_pozivi': n}"""
    out = {}
    if not _exists(path):
        return out
    now = now or time.time()
    con = _con(path)
    try:
        out["w_pozivi"] = _delete(con, "calls", "handle LIKE 'w:%' AND ts < ?", (int(now - W_KEEP_DAYS * D),))
        cut = int(now - INACTIVE_DAYS * D)
        rows = con.execute("SELECT handle, stats FROM kols WHERE handle NOT LIKE 'tg:%' AND handle NOT LIKE 'w:%' "
                           "AND COALESCE(last_seen, first_seen, 0) < ?", (cut,)).fetchall()
        gone = [h for h, st in rows if not json.loads(st or "{}").get("measured")]
        out["neaktivni_x"] = len(gone)
        n_calls = 0
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            q = ",".join("?" * len(chunk))
            n_calls += con.execute(f"SELECT COUNT(*) FROM calls WHERE handle IN ({q})", chunk).fetchone()[0]
            if on():
                con.execute(f"DELETE FROM calls WHERE handle IN ({q})", chunk)
                con.execute(f"DELETE FROM kols WHERE handle IN ({q})", chunk)
                con.commit()
        out["neaktivni_x_pozivi"] = n_calls
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            print(f"čišćenje kol.db nije uspjelo: {e}", flush=True)
    finally:
        con.close()
    return out


def loser_wallets(con, now):
    """Wallets whose trade rows can go: tier D, scored losers (10+ closed, nothing realized) and wallets inactive
    INACTIVE_DAYS without a profitable record; never wallets younger than YOUNG_DAYS (unless tier D) or profitable."""
    rows = con.execute("SELECT wallet, first_seen, last_seen, scored_at, tier, stats, labels FROM wallets "
                       "WHERE scored_at IS NOT NULL AND EXISTS (SELECT 1 FROM wallet_trades t WHERE t.wallet = wallets.wallet)").fetchall()
    out = []
    for w, fs, ls, _sa, tier, st, lab in rows:
        if LABEL in json.loads(lab or "[]"):
            continue   # already stripped; a new sighting may bring it back through the queue only if the label goes
        s = json.loads(st or "{}")
        closed, realized = s.get("closed", 0) or 0, s.get("realized_sol", 0) or 0
        profitable = closed >= 3 and realized > 0
        if profitable:
            continue
        young = (fs or 0) > now - YOUNG_DAYS * D
        if tier == "D":
            out.append(w)
        elif young:
            continue
        elif closed >= 10 and realized <= 0:
            out.append(w)
        elif (ls or 0) < now - INACTIVE_DAYS * D:
            out.append(w)
    return out


def wallets(path, now=None):
    """{'gubitnici': wallets stripped, 'gubitnici_tradeovi': trade rows}"""
    out = {}
    if not _exists(path):
        return out
    now = now or time.time()
    con = _con(path)
    try:
        gone = loser_wallets(con, now)
        out["gubitnici"] = len(gone)
        n = 0
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            q = ",".join("?" * len(chunk))
            n += con.execute(f"SELECT COUNT(*) FROM wallet_trades WHERE wallet IN ({q})", chunk).fetchone()[0]
            if on():
                con.execute(f"DELETE FROM wallet_trades WHERE wallet IN ({q})", chunk)
                # a later full re-score (if the label is ever lifted) must fetch the whole history again
                for w in chunk:
                    lab = json.loads(con.execute("SELECT labels FROM wallets WHERE wallet=?", (w,)).fetchone()[0] or "[]")
                    if LABEL not in lab:
                        lab.append(LABEL)
                    con.execute("UPDATE wallets SET labels=?, next_check=NULL, last_tx_ts=NULL, history_from=NULL "
                                "WHERE wallet=?", (json.dumps(lab), w))
                con.commit()
        out["gubitnici_tradeovi"] = n
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            print(f"čišćenje wallets.db nije uspjelo: {e}", flush=True)
    finally:
        con.close()
    return out


def hype(path, now=None):
    """{'chain': n, 'mrtvi_tokeni': n}"""
    out = {}
    if not _exists(path):
        return out
    now = now or time.time()
    con = _con(path)
    try:
        cut = int(now - CHAIN_KEEP_DAYS * D)
        n = 0
        for t in ("chain_trades", "chain_transfers"):
            try:
                n += _delete(con, t, "ts < ?", (cut,))
            except sqlite3.OperationalError as e:
                if "no such table" not in str(e):
                    raise
        out["chain"] = n
        dead = "token IN (SELECT token FROM token_status WHERE COALESCE(has_pair, 1) = 0) AND ts < ?"
        cut = int(now - DEAD_KEEP_DAYS * D)
        n = 0
        for t in ("hype_snapshots", "hype_details"):
            try:
                n += _delete(con, t, dead, (cut,))
            except sqlite3.OperationalError as e:
                if "no such table" not in str(e):
                    raise
        out["mrtvi_tokeni"] = n
    except sqlite3.OperationalError as e:
        print(f"čišćenje hype.db nije uspjelo: {e}", flush=True)
    finally:
        con.close()
    return out


def paper(path, now=None):
    """{'tikovi': n}: ticks of tokens the demo never traded, older than UNTRADED_TICK_DAYS."""
    out = {}
    if not _exists(path):
        return out
    now = now or time.time()
    con = _con(path)
    try:
        out["tikovi"] = _delete(con, "ticks", "ts < ? AND token NOT IN (SELECT token FROM trades)",
                                (int(now - UNTRADED_TICK_DAYS * D),))
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            print(f"čišćenje paper.db nije uspjelo: {e}", flush=True)
    finally:
        con.close()
    return out


WATCH = {"hype.db": ("hype_signals", "hype_snapshots", "hype_details", "chain_trades", "live_trades", "apify_cache"),
         "kol.db": ("calls", "kols"), "wallets.db": ("wallet_trades", "wallets"), "paper.db": ("ticks",),
         "tg.db": ("posts",), "shadow.db": ("points",)}


def growth(data_dir=None, now=None, state_path=None):
    """[(db.table, rows, rows per hour)] of tables that grew faster than GROWTH_WARN an hour since the last call."""
    data_dir = data_dir or disk.DATA_DIR
    now = now or time.time()
    state_path = state_path or os.path.join(data_dir, ".rows.json")
    try:
        with open(state_path) as f:
            prev = json.load(f)
    except (OSError, ValueError):
        prev = {}
    cur = {"ts": now}
    warn = []
    for db, tables in WATCH.items():
        p = os.path.join(data_dir, db)
        if not _exists(p):
            continue
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
        except sqlite3.Error:
            continue
        for t in tables:
            try:
                n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                continue
            key = f"{db}.{t}"
            cur[key] = n
            if key in prev and prev.get("ts"):
                hours = max(0.25, (now - prev["ts"]) / 3600)
                rate = (n - prev[key]) / hours
                if rate > GROWTH_WARN:
                    warn.append((key, n, int(rate)))
        con.close()
    try:
        with open(state_path, "w") as f:
            json.dump(cur, f)
    except OSError:
        pass
    return warn


def run_all(now=None, data_dir=None, log=print):
    """Every rule on every database; one log line. Returns {rule: rows}."""
    data_dir = data_dir or disk.DATA_DIR
    now = now or time.time()
    out = {}
    for fn, name in ((kol, "kol.db"), (wallets, "wallets.db"), (hype, "hype.db"), (paper, "paper.db")):
        try:
            out.update(fn(os.path.join(data_dir, name), now))
        except Exception as e:  # noqa: BLE001 - one database must not stop the others
            log(f"čišćenje {name} nije uspjelo: {type(e).__name__}: {e}")
    mode = "brisanje" if on() else "suho brojanje, DATA_PRUNE=on briše"
    log(f"čišćenje ({mode}): " + (", ".join(f"{k} {v:,}" for k, v in out.items() if v) or "ništa za obrisati"))
    try:
        for key, n, rate in growth(data_dir, now):
            log(f"čišćenje: {key} raste brzo, +{rate:,} redaka na sat ({n:,} ukupno): provjeri tko to piše i tko čita")
    except Exception as e:  # noqa: BLE001
        log(f"čišćenje: praćenje rasta nije uspjelo: {e}")
    return out
