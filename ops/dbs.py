"""SQLite upkeep for every database on the data disk.

- WAL journal: the dashboard's long reads no longer block the bot's writes; the WAL file is cut back to zero
  every hour (checkpoint TRUNCATE) so it cannot keep growing.
- auto_vacuum=INCREMENTAL, switched on once per file with a VACUUM at start-up (only when the disk has room for
  it); after that every hour hands deleted pages back to the disk without rewriting the file.
- Retention of raw API answers: apify_cache rows (the full JSON of every Apify run) older than APIFY_KEEP_DAYS.
  Calls/channels in them are copied to kol.db/tg.db within minutes, and no Apify call reuses a cache older than
  7 days, so nothing is fetched (or paid) again. Only the "raw tweets" pop-up of tokens older than that is empty.
- Slimming of hype_signals (one row per token per scan, ~3 KB each, ~250 MB a day on 1.11.): the weights JSON is
  read only from a token's newest signal, and features only from its first (learning) and newest (scan, dashboard)
  signal. Every other row keeps ts, score, price, mcap, liquidity, sources (charts, collapse filter, history table);
  its weights are dropped at once and its features after SLIM_FEATURES_H hours. Nothing any page or loop reads is
  lost; the per-scan feature history of older rows is.
- Compaction: a file with >= COMPACT_WASTE (35%) of dead space is rewritten (VACUUM) at start-up and once a day, when the
  disk has room for the rewritten copy. Without it the slimmed rows would keep their old pages.
- Covering index on hype_signals (ts, token, score, mcap, liquidity, symbol): Pregled reads the newest signals from
  the ~5 MB index instead of the whole 200+ MB table.
"""
import glob
import os
import sqlite3
import time

from ops import disk

APIFY_KEEP_DAYS = float(os.environ.get("APIFY_KEEP_DAYS", "14"))
VACUUM_MAX_MB = float(os.environ.get("VACUUM_MAX_MB", "400"))
SLIM_FEATURES_H = float(os.environ.get("SLIM_FEATURES_H", "24"))
COMPACT_WASTE = float(os.environ.get("COMPACT_WASTE", "0.35"))   # a freshly packed file has ~10-25% slack
SLIM_BATCH = 3000


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


def slim_signals(path=None, now=None, batch=SLIM_BATCH):
    """Drop what no reader uses from older hype_signals rows (see module doc). Batched by rowid with a WAL
    checkpoint between batches, so the first pass over a big table never needs its size in free disk.
    Returns (rows without weights, rows without features)."""
    path = path or os.path.join(disk.DATA_DIR, "hype.db")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0, 0
    now = now or time.time()
    cut = int(now - SLIM_FEATURES_H * 3600)
    con = _con(path)
    nw = nf = 0
    try:
        top = con.execute("SELECT MAX(rowid) FROM hype_signals").fetchone()[0] or 0
        for lo in range(0, top + 1, batch):
            hi = lo + batch
            nw += con.execute("""UPDATE hype_signals SET weights = NULL WHERE rowid >= ? AND rowid < ?
                AND weights IS NOT NULL
                AND ts < (SELECT MAX(ts) FROM hype_signals h WHERE h.token = hype_signals.token)""", (lo, hi)).rowcount
            nf += con.execute("""UPDATE hype_signals SET features = NULL WHERE rowid >= ? AND rowid < ?
                AND features IS NOT NULL AND ts < ?
                AND ts > (SELECT MIN(ts) FROM hype_signals h WHERE h.token = hype_signals.token)
                AND ts < (SELECT MAX(ts) FROM hype_signals h WHERE h.token = hype_signals.token)""",
                              (lo, hi, cut)).rowcount
            con.commit()
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            print(f"sažimanje hype signala nije uspjelo: {e}", flush=True)
    finally:
        con.close()
    return nw, nf


def ensure_indexes(path=None):
    path = path or os.path.join(disk.DATA_DIR, "hype.db")
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return
    con = _con(path)
    try:
        con.execute("CREATE INDEX IF NOT EXISTS hype_signals_cover ON hype_signals "
                    "(ts, token, score, mcap, liquidity, symbol)")
        con.commit()
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            print(f"indeks hype signala nije napravljen: {e}", flush=True)
    finally:
        con.close()


def waste(path):
    """Share of the file that is free pages or unused bytes inside pages (dbstat), or None without dbstat."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        size, unused = con.execute("SELECT SUM(pgsize), SUM(unused) FROM dbstat").fetchone()
        free = con.execute("PRAGMA freelist_count").fetchone()[0] * con.execute("PRAGMA page_size").fetchone()[0]
        con.close()
        total = os.path.getsize(path)
        return ((unused or 0) + free) / total if total else 0.0
    except sqlite3.OperationalError:
        return None


def compact(path, min_waste=COMPACT_WASTE, offline=False):
    """VACUUM when at least min_waste of the file is dead space and the disk can hold the rewritten copy (in WAL
    mode the new content goes through the WAL first). Returns 'a->b MB (s)' or None.

    offline=True (start-up only, nothing else has the file open): when the data disk is too full for that, the
    packed copy is built on the container's own temporary disk (VACUUM INTO), copied next to the file and swapped
    in, so only the packed size has to fit on the data disk."""
    w = waste(path)
    mb = os.path.getsize(path) / 1e6
    new_mb = mb * (1 - (w or 0))
    need = new_mb + 50
    if w is None or w < min_waste or mb * w < 10:   # < 10 MB to win: not worth it
        return None
    if (disk.free_mb() or 0) < need:
        return _compact_via_tmp(path, mb, new_mb) if offline else None
    t = time.time()
    con = _con(path, timeout=120)
    try:
        con.execute("VACUUM")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as e:
        print(f"baze: {os.path.basename(path)} nije sažeta ({e})", flush=True)
        return None
    finally:
        con.close()
    return f"{os.path.basename(path)} {mb:.0f}->{os.path.getsize(path) / 1e6:.0f} MB ({time.time() - t:.0f} s)"


def _compact_via_tmp(path, mb, new_mb):
    import shutil
    import tempfile
    tmpdir = tempfile.gettempdir()
    if (disk.free_mb(tmpdir) or 0) < mb + 50 or (disk.free_mb() or 0) < new_mb + 20:
        print(f"baze: {os.path.basename(path)} se ne može sažeti, premalo mjesta ({disk.free_mb():.0f} MB slobodno)",
              flush=True)
        return None
    t = time.time()
    tmp = os.path.join(tmpdir, os.path.basename(path) + ".packed")
    new = path + ".packed"
    for p in (tmp, new):
        if os.path.exists(p):
            os.remove(p)
    con = _con(path, timeout=120)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("VACUUM INTO ?", (tmp,))
    except sqlite3.OperationalError as e:
        print(f"baze: {os.path.basename(path)} nije sažeta ({e})", flush=True)
        return None
    finally:
        con.close()
    chk = sqlite3.connect(tmp)
    ok = chk.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    chk.close()
    if not ok:
        os.remove(tmp)
        print(f"baze: {os.path.basename(path)} kopija nije ispravna, original ostaje", flush=True)
        return None
    shutil.copyfile(tmp, new)
    with open(new, "rb") as f:
        os.fsync(f.fileno())
    os.remove(tmp)
    os.replace(new, path)          # the old -wal was emptied by the checkpoint above; a stale one must not replay
    for ext in ("-wal", "-shm"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.close()
    return f"{os.path.basename(path)} {mb:.0f}->{os.path.getsize(path) / 1e6:.0f} MB (preko privremenog diska, {time.time() - t:.0f} s)"


def startup():
    """Once before the loops start: retention, auto_vacuum switch (VACUUM where there is room), WAL on."""
    t0 = time.time()
    gone = retention()
    nw, nf = slim_signals()
    if nw or nf:
        gone["hype_signals sažeto"] = nw + nf
    ensure_indexes()
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
            vacuumed = bool(msgs) and msgs[-1].startswith(name + " ")
            con.execute("PRAGMA journal_mode=WAL")
            con.close()
            done = None if vacuumed else compact(path, offline=True)
            if done:
                msgs.append(done)
        except sqlite3.OperationalError as e:
            print(f"baze: {name} preskočena ({e})", flush=True)
    print(f"baze: WAL uključen, obrisano {gone or 'ništa'}, sažeto: {', '.join(msgs) or 'ništa'} "
          f"({time.time() - t0:.0f} s)", flush=True)


def hourly():
    """Retention, give freed pages back to the disk, cut WAL files back to zero."""
    gone = retention()
    nw, nf = slim_signals()
    if nw or nf:
        gone["hype_signals sažeto"] = nw + nf
    day = time.strftime("%Y-%m-%d", time.gmtime())
    mark = os.path.join(disk.DATA_DIR, ".compacted")
    try:
        with open(mark) as f:
            last = f.read().strip()
    except OSError:
        last = ""
    if last != day:   # once a day: rewrite files whose slimmed/deleted rows left dead space
        out = [c for c in (compact(p) for p in files()) if c]
        if out:
            print("baze: dnevno sažimanje " + ", ".join(out), flush=True)
        try:
            with open(mark, "w") as f:
                f.write(day)
        except OSError:
            pass
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
