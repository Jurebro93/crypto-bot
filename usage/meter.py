"""Counts every paid API call this process makes, per hour, script and method, into usage.db.

record() only adds to an in-memory tally; it is written out every FLUSH_S seconds and at exit, so a busy
loop (40 Helius calls/s) costs one small SQLite upsert, not one per call. It never raises: losing a count
must not break a scan.
"""
import atexit
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("USAGE_DB", os.path.join(ROOT, "usage.db"))
FLUSH_S = 30
SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (hour INTEGER, service TEXT, script TEXT, method TEXT,
  calls INTEGER, errors INTEGER, amount REAL, PRIMARY KEY (hour, service, script, method));
CREATE TABLE IF NOT EXISTS account (ts INTEGER, service TEXT, used REAL, lim REAL,
  cycle_start INTEGER, cycle_end INTEGER, extra TEXT);
CREATE TABLE IF NOT EXISTS alerts (key TEXT PRIMARY KEY, service TEXT, level TEXT, title TEXT, detail TEXT,
  first_ts INTEGER, last_ts INTEGER);
"""

_tally = {}
_lock = threading.Lock()
_last_flush = [time.time()]
SCRIPT = os.path.basename(sys.argv[0] or "python") or "python"


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.executescript(SCHEMA)
    return con


def record(service, method, amount=0.0, calls=1, error=False):
    """amount: Helius credits or Apify USD this call cost (0 for a failed call)."""
    try:
        k = (int(time.time()) // 3600 * 3600, service, SCRIPT, method)
        with _lock:
            c = _tally.setdefault(k, [0, 0, 0.0])
            c[0] += calls
            c[1] += 1 if error else 0
            c[2] += amount
        if time.time() - _last_flush[0] > FLUSH_S:
            flush()
    except Exception:
        pass


def flush():
    with _lock:
        items, _last_flush[0] = list(_tally.items()), time.time()
        _tally.clear()
    if not items:
        return
    try:
        con = connect()
        con.executemany("""INSERT INTO usage VALUES (?,?,?,?,?,?,?) ON CONFLICT (hour, service, script, method)
            DO UPDATE SET calls=calls+excluded.calls, errors=errors+excluded.errors, amount=amount+excluded.amount""",
                        [(*k, *v) for k, v in items])
        con.commit()
        con.close()
    except Exception as e:
        print(f"usage meter: {type(e).__name__}: {e}", file=sys.stderr)


atexit.register(flush)


# ---------- Helius pricing (approximate, https://www.helius.dev/docs/billing/credits) ----------

DAS_METHODS = {"getTokenAccounts", "getAsset", "getAssetBatch", "getAssetsByOwner", "searchAssets", "getAssetProof",
               "getAssetsByGroup", "getAssetsByCreator", "getAssetsByAuthority", "getSignaturesForAsset"}


def helius_cost(url, body=None, result=None):
    """(method, credits) for one Helius request, or None if the URL is not Helius."""
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ""
    if not host.endswith("helius-rpc.com"):
        return None
    if host.startswith("api"):  # Enhanced Transactions API
        return "enhanced " + u.path.rsplit("/", 1)[-1], 100
    method = "rpc"
    try:
        method = json.loads(body)["method"]
    except Exception:
        pass
    if method == "getTransactionsForAddress":
        n = len((result or {}).get("data") or []) if isinstance(result, dict) else 0
        return method, max(10, -(-n // 100) * 10)
    if method in DAS_METHODS:
        return method, 10
    return method, 1


def helius(url, body=None, result=None, error=False):
    c = helius_cost(url, body, result)
    if c:
        record("helius", c[0], 0 if error else c[1], error=error)
