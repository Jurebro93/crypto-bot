"""Read-only lookups for eventpick from the databases other modules write. Missing DBs mean no data."""
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _q(name, env, sql, args=()):
    path = os.environ.get(env) or os.path.join(HERE, name)
    if not os.path.exists(path):
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def watches():
    """token -> newest watch_correlation row (eventwatch)."""
    out = {}
    for r in _q("watch.db", "WATCH_DB", "SELECT * FROM watch_correlation ORDER BY updated_ts"):
        out[r["token"]] = r
    return out


def kol_mentions(days=7):
    """token -> number of distinct KOLs who called it in the last `days` days."""
    cut = int(time.time()) - days * 86400
    return {r["token"]: r["n"] for r in _q("kol.db", "KOL_DB",
            "SELECT token, COUNT(DISTINCT handle) n FROM calls WHERE kind = 'call' AND ts >= ? GROUP BY token", (cut,))}
