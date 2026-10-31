"""SQLite upkeep for every database on the data disk.

- WAL journal: the dashboard's long reads no longer block the bot's writes; the WAL file is cut back to zero
  every hour (checkpoint TRUNCATE) so it cannot keep growing.
- auto_vacuum=INCREMENTAL, switched on once per file with a VACUUM at start-up (only when the disk has room for
  it); after that every hour hands deleted pages back to the disk without rewriting the file.
- Retention of raw API answers: apify_cache rows (the full JSON of every Apify run) older than APIFY_KEEP_DAYS.
  Calls/channels in them are copied to kol.db/tg.db within minutes, and no Apify call reuses a cache older than
  7 days, so nothing is fetched (or paid) again. Only the "raw tweets" pop-up of tokens older than that is empty.
"""
import glob
import os
import sqlite3
import time

from ops import disk

APIFY_KEEP_DAYS = float(os.environ.get("APIFY_KEEP_DAYS", "14"))
VACUUM_MAX_MB = float(os.environ.get("VACUUM_MAX_MB", "400"))


def files():
    return sorted(p for p in glob.glob(os.path.join(disk.DATA_DIR, "*.db")) if os.path.getsize(p) > 0)


def _con(path, timeout=60):
    con = sqlite3.connect(path, timeout=timeout)
    con.execute(f"PRAGMA busy_timeout={timeout * 1000}")
    return con


def retention(now=None):
    """Delete raw data past its use. Returns {table: rows deleted}."""
    now = now or time.time()
    out = {}
    hype = os.path.join(disk.DATA_DIR, "hype.db")
    if os.path.exists(hype) and os.path.getsize(hype) > 0:
        con = _con(hype)
        try:
            n = con.execute("DELETE FROM apify_cache WHERE ts < ?", (int(now - APIFY_KEEP_DAYS * 86400),)).rowcount
            con.commit()
            out["apify_cache"] = n
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                print(f"retencija apify_cache nije uspjela: {e}", flush=True)
        finally:
            con.close()
    return out


def startup():
    """Once before the loops start: retention, auto_vacuum switch (VACUUM where there is room), WAL on."""
    t0 = time.time()
    gone = retention()
    msgs = []
    for path in files():
        name = os.path.basename(path)
        try:
            con = _con(path, timeout=30)
            mb = os.path.getsize(path) / 1e6
            if con.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
                free = disk.free_mb() or 0
                if mb <= VACUUM_MAX_MB and free > mb + 150:
                    t = time.time()
                    con.execute("PRAGMA journal_mode=DELETE")    # auto_vacuum can only change outside WAL
                    con.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    con.execute("VACUUM")
                    msgs.append(f"{name} {mb:.0f}->{os.path.getsize(path) / 1e6:.0f} MB ({time.time() - t:.0f} s)")
            con.execute("PRAGMA journal_mode=WAL")
            con.close()
        except sqlite3.OperationalError as e:
            print(f"baze: {name} preskočena ({e})", flush=True)
    print(f"baze: WAL uključen, obrisano {gone or 'ništa'}, sažeto: {', '.join(msgs) or 'ništa'} "
          f"({time.time() - t0:.0f} s)", flush=True)


def hourly():
    """Retention, give freed pages back to the disk, cut WAL files back to zero."""
    gone = retention()
    freed = 0.0
    for path in files():
        before = os.path.getsize(path) + (os.path.getsize(path + "-wal") if os.path.exists(path + "-wal") else 0)
        try:
            con = _con(path, timeout=20)
            if con.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:
                con.execute("PRAGMA incremental_vacuum")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.close()
        except sqlite3.OperationalError:
            continue
        after = os.path.getsize(path) + (os.path.getsize(path + "-wal") if os.path.exists(path + "-wal") else 0)
        freed += max(0, before - after) / 1e6
    print(f"baze: retencija {gone or 'ništa'}, vraćeno disku {freed:.0f} MB", flush=True)


def table_sizes(path, top=4):
    """[(table, MB)] biggest first, from SQLite's dbstat (empty when the build lacks it)."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        rows = con.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC LIMIT ?", (top,)).fetchall()
        con.close()
        return [(n, b / 1e6) for n, b in rows]
    except sqlite3.OperationalError:
        return []
