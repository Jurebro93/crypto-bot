"""20.11.: one Birdeye compute-unit (CU) budget a calendar month for every caller.

The owner's Birdeye key is the free Standard plan: 30,000 CU a month. insajderi/birdeye.py counts its own calls in
insajderi.db be_usage (month TEXT PRIMARY KEY, calls, cu) and stops at its cu_month (insajderi/config.json birdeye,
25,000). dugo/sources.holders_birdeye (GET /defi/token_overview, up to candles_per_run calls a pass) was not counted
at all. It now books into the SAME month row (take()), so:
  - the month's total (insajderi + dugo) is one number, read by insajderi's own left_cu() before each of its calls and
    by the daily cost line (usage/daily.py);
  - dugo stops once the total would pass the cap.
The same row instead of a usage.db "birdeye" service: one place to read, and insajderi (whose code is not touched
here) sees dugo's spend without a change.

CU per call: docs https://docs.birdeye.so (guides/what-is-compute-unit-cost, checked 20.11.): /defi/token_overview is
a fixed 18 CU.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CU_TOKEN_OVERVIEW = 18
DEFAULT_CAP = 25000
SCHEMA = "CREATE TABLE IF NOT EXISTS be_usage (month TEXT PRIMARY KEY, calls INTEGER, cu INTEGER)"


def db_path():
    """insajderi.db, where insajderi/store.db_path() puts it (INSAJDERI_DB, else DATA_DIR, else the repo root)."""
    try:
        from insajderi import store
        return store.db_path()
    except Exception:  # noqa: BLE001
        return os.environ.get("INSAJDERI_DB") or os.path.join(ROOT, "insajderi.db")


def cap():
    """The month's CU cap: insajderi/config.json birdeye.cu_month (25,000 of the plan's 30,000)."""
    try:
        with open(os.path.join(ROOT, "insajderi", "config.json")) as f:
            return int((json.load(f).get("birdeye") or {}).get("cu_month") or DEFAULT_CAP)
    except (OSError, ValueError, TypeError):
        return DEFAULT_CAP


def month(now):
    return time.strftime("%Y-%m", time.gmtime(int(now)))


def used(now=None, path=None):
    """(calls, CU) booked this calendar month (UTC) by every caller; (0, 0) without the database. Read-only."""
    p = path or db_path()
    if not os.path.exists(p):
        return 0, 0
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
        try:
            r = con.execute("SELECT calls, cu FROM be_usage WHERE month = ?", (month(now or time.time()),)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return 0, 0
    return (int(r[0] or 0), int(r[1] or 0)) if r else (0, 0)


def take(cu, now=None, path=None, limit=None):
    """Book one call of `cu` CU in this month's row when the total stays within the cap: True = make the call.
    False when the cap is reached or the database cannot be used (no count, no call). Never raises."""
    now = now or time.time()
    limit = cap() if limit is None else int(limit)
    try:
        con = sqlite3.connect(path or db_path(), timeout=30)
        try:
            con.execute(SCHEMA)
            con.execute("BEGIN IMMEDIATE")
            r = con.execute("SELECT cu FROM be_usage WHERE month = ?", (month(now),)).fetchone()
            if (int(r[0] or 0) if r else 0) + int(cu) > limit:
                con.rollback()
                return False
            con.execute("INSERT INTO be_usage VALUES (?, 1, ?) ON CONFLICT (month) DO UPDATE SET calls = calls + 1, "
                        "cu = cu + excluded.cu", (month(now), int(cu)))
            con.commit()
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False
