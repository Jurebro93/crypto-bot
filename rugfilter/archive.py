"""Rugged tokens out of the live database: archived once, never tracked again, remembered for learning.

Nicholas, 1.11.: "tokene koji su pulani skroz izbaciti iz baze, prestati ih pratiti, prestati trošiti resurse na
njih ... ali učiti iz tih koji su bili rugani, da se ne dodaju novi koji će biti isti takvi".

Once an hour (ops/dbs.hourly) every token first seen at least MIN_AGE_H hours ago is judged on its whole history in
hype.db (not only the last 24 h like rugfilter/collapse.py):

- srusen      market cap 70%+ below the highest the bot ever saw, and not back above half of it
- likvidnost  liquidity 60%+ below its peak together with a 50%+ fall (pool pulled), or the pair vanished
- mehanika    rug mechanics before entry (T0 fail on mint/freeze authority, RugCheck "rugged", rug filter ODBAČEN)

Such a token gets one row in `rug_archive` (what it looked like when the bot first saw it, how and how far it fell)
and everything else about it is deleted from hype.db: the per-scan signal rows, the 2-minute pulse, the extra
details. Kept for the learning loops, so they do not start believing every token pumps: the FIRST signal row
(entry features), at most two price snapshots per hour of its life (the highest and the last of each hour), the
first and the last details row, and the token_tier row. From then on the scan, the price tracker, the pulse and the
paid checks skip it (`blocked()`), and no page lists it.

Never archived: tokens with an open demo, competition or KOL-test position (their exit still needs prices) and
tokens on the long-term lists (dugo.db, judged by their own rules).

learn/rugprofile.py learns from this table which entry profiles end as rugs and stops similar new tokens early.
"""
import json
import os
import sqlite3
import time

from rugfilter import collapse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HYPE_DB = os.path.join(ROOT, "hype.db")
MIN_AGE_H = float(os.environ.get("RUG_ARCHIVE_MIN_AGE_H", "26"))  # learning horizon is 24 h; outcome must be complete
BATCH = int(os.environ.get("RUG_ARCHIVE_BATCH", "2000"))           # tokens per hourly run, keeps the run short
KINDS_REAL = ("srusen", "likvidnost")   # rugs that actually happened (the labels the rug profile learns from)

SCHEMA = """
CREATE TABLE IF NOT EXISTS rug_archive (
    token TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, last_ts INTEGER, archived_ts INTEGER, klasa TEXT,
    kind TEXT, reason TEXT, peak_mcap REAL, last_mcap REAL, peak_liq REAL, last_liq REAL, pad REAL,
    entry TEXT, removed TEXT);
CREATE INDEX IF NOT EXISTS rug_archive_ts ON rug_archive (archived_ts);
"""

_cache = {"ts": 0, "path": None, "set": frozenset()}


def connect(path=None):
    con = sqlite3.connect(path or HYPE_DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.executescript(SCHEMA)
    return con


def blocked(path=None, ttl=300):
    """Set of archived mints (cached `ttl` seconds). Empty when the table does not exist yet."""
    path = path or HYPE_DB
    now = time.time()
    if _cache["path"] == path and now - _cache["ts"] < ttl:
        return _cache["set"]
    s = frozenset()
    if os.path.exists(path):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
            try:
                s = frozenset(t for (t,) in con.execute("SELECT token FROM rug_archive"))
            finally:
                con.close()
        except sqlite3.Error:
            s = frozenset()
    _cache.update(ts=now, path=path, set=s)
    return s


def forget_cache():
    _cache.update(ts=0, path=None, set=frozenset())


# ---------- judging ----------

def _protected():
    """Mints that must keep their price history: open positions anywhere, long-term lists."""
    out = set()
    for name, sql in (("paper.db", "SELECT token FROM trades WHERE status='open'"),
                      ("league.db", "SELECT token FROM trades WHERE status='open'"),
                      ("koltest.db", "SELECT token FROM positions WHERE book_closed_ts IS NULL AND entry_ts IS NOT NULL"),
                      ("dugo.db", "SELECT mint FROM tokens WHERE candles_ts IS NOT NULL")):
        p = os.path.join(ROOT, name)
        if not os.path.exists(p):
            continue
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
            try:
                out |= {r[0] for r in con.execute(sql)}
            finally:
                con.close()
        except sqlite3.Error:
            continue
    return out


def _rug_verdicts(tokens):
    p = os.path.join(ROOT, "rug.db")
    out = {}
    if not tokens or not os.path.exists(p):
        return out
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return out
    try:
        toks = list(tokens)
        for i in range(0, len(toks), 400):
            part = toks[i:i + 400]
            for m, v, s in con.execute(f"SELECT mint, verdict, score FROM rug_reports WHERE mint IN ({','.join('?' * len(part))}) "
                                       "ORDER BY checked_at", part):
                out[m] = (v, s)
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def judge(peak_mcap, last_mcap, peak_liq, last_liq, t0=None, t0_razlog=None, verdict=None):
    """(kind, plain Croatian reason) or None. Actual collapse first: it is what the rug profile learns from."""
    if peak_mcap and peak_mcap >= collapse.MIN_PEAK_MCAP:
        if (last_mcap or 0) <= 0 and (last_liq or 0) <= 0:
            return "likvidnost", f"par nestao s DEX-a (vrh ${peak_mcap / 1000:,.1f}k)"
        j = collapse.judge(peak_mcap, last_mcap or 0, peak_liq or None, last_liq)
        if j:
            return ("srusen" if j["drop"] >= collapse.DROP else "likvidnost"), j["text"]
    if t0 == "pad" and t0_razlog and not t0_razlog.startswith("sliči rugovima"):
        return "mehanika", t0_razlog
    if verdict == "ODBAČEN":
        return "mehanika", "rug filter: ODBAČEN (mehanika ruga)"
    return None


def candidates(con, now=None, limit=None):
    """[(token, kind, reason, stats)] for tokens old enough, not archived, not protected."""
    now = now or time.time()
    cutoff = int(now - MIN_AGE_H * 3600)
    tiers = {r[0]: r[1:] for r in con.execute(
        "SELECT token, symbol, first_ts, last_ts, klasa, t0, t0_razlog FROM token_tier "
        "WHERE first_ts <= ? AND token NOT IN (SELECT token FROM rug_archive)", (cutoff,))}
    if not tiers:
        return []
    agg = {}
    for table in ("hype_snapshots", "token_pulse"):
        try:
            for t, pm, pl, lt in con.execute(f"SELECT token, MAX(mcap), MAX(liquidity), MAX(ts) FROM {table} GROUP BY token"):
                if t not in tiers:
                    continue
                a = agg.setdefault(t, [0.0, 0.0, 0, None, None])
                a[0], a[1] = max(a[0], pm or 0), max(a[1], pl or 0)
                if (lt or 0) >= a[2]:
                    row = con.execute(f"SELECT mcap, liquidity FROM {table} WHERE token=? AND ts=?", (t, lt)).fetchone()
                    a[2], a[3], a[4] = lt, row[0] if row else None, row[1] if row else None
        except sqlite3.OperationalError:
            continue
    verdicts = _rug_verdicts(tiers)
    prot = _protected()
    out = []
    for t, (sym, first, last, klasa, t0, t0r) in tiers.items():
        if t in prot:
            continue
        pm, pl, lts, lm, ll = agg.get(t, [0, 0, 0, None, None])
        k = judge(pm, lm, pl, ll, t0, t0r, (verdicts.get(t) or (None,))[0])
        if not k:
            continue
        drop = round(1 - (lm or 0) / pm, 3) if pm else None
        out.append((t, k[0], k[1], {"symbol": sym, "first_ts": first, "last_ts": max(last or 0, lts or 0), "klasa": klasa,
                                     "peak_mcap": pm, "last_mcap": lm, "peak_liq": pl, "last_liq": ll, "drop": drop,
                                     "verdict": verdicts.get(t)}))
        if limit and len(out) >= limit:
            break
    return out


# ---------- archiving ----------

def entry_profile(con, token, stats):
    """What the token looked like when the bot first saw it: the facts the rug profile learns from."""
    e = {"verdict": (stats.get("verdict") or (None, None))[0], "rug_score": (stats.get("verdict") or (None, None))[1]}
    r = con.execute("SELECT ts, score, price, mcap, liquidity, features, sources FROM hype_signals WHERE token=? "
                    "ORDER BY ts LIMIT 1", (token,)).fetchone()
    if r:
        try:
            feats = json.loads(r[5]) if r[5] else {}
        except ValueError:
            feats = {}
        e.update(ts=r[0], score=r[1], price=r[2], mcap=r[3], liquidity=r[4], features=feats, sources=r[6])
    t = con.execute("SELECT age_h, t0, t0_razlog, razina, mcap, liquidity FROM token_tier WHERE token=?", (token,)).fetchone()
    if t:
        e.update(age_h=t[0], t0=t[1], t0_razlog=t[2], razina=t[3])
        e.setdefault("mcap", t[4])
        e.setdefault("liquidity", t[5])
    d = con.execute("SELECT extra FROM hype_details WHERE token=? ORDER BY ts LIMIT 1", (token,)).fetchone()
    if d and d[0]:
        try:
            pf = (json.loads(d[0]) or {}).get("pumpfun") or {}
            e["pumpfun"] = {k: pf.get(k) for k in ("holders", "top10HoldersPercent", "bundlerOwnedPercent",
                                                    "snipersOwnedPercent", "devHoldingsPercent", "kolCount") if pf.get(k) is not None}
        except ValueError:
            pass
    return e


def purge(con, token):
    """Delete everything but the learning record. Returns {table: rows deleted}."""
    gone = {}

    def run(name, sql, args):
        try:
            gone[name] = con.execute(sql, args).rowcount
        except sqlite3.OperationalError:
            gone[name] = 0

    run("hype_signals", "DELETE FROM hype_signals WHERE token=? AND ts > (SELECT MIN(ts) FROM hype_signals WHERE token=?)",
        (token, token))
    # per hour of its life: the highest-price snapshot and the last one (max return and end-of-horizon / rug flag)
    run("hype_snapshots", """DELETE FROM hype_snapshots WHERE token=? AND rowid NOT IN (
            SELECT rid FROM (SELECT rowid AS rid, MAX(price) FROM hype_snapshots WHERE token=? GROUP BY CAST(ts / 3600 AS INTEGER))
            UNION SELECT rid FROM (SELECT rowid AS rid, MAX(ts) FROM hype_snapshots WHERE token=? GROUP BY CAST(ts / 3600 AS INTEGER)))""",
        (token, token, token))
    run("hype_details", """DELETE FROM hype_details WHERE token=? AND ts NOT IN (
            SELECT MIN(ts) FROM hype_details WHERE token=? UNION SELECT MAX(ts) FROM hype_details WHERE token=?)""",
        (token, token, token))
    run("token_pulse", "DELETE FROM token_pulse WHERE token=?", (token,))
    return {k: v for k, v in gone.items() if v}


def archive(con, cands, now=None):
    now = int(now or time.time())
    n, rows = 0, 0
    for t, kind, reason, st in cands:
        e = entry_profile(con, t, st)
        gone = purge(con, t)
        con.execute("INSERT OR REPLACE INTO rug_archive VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t, st["symbol"], st["first_ts"], st["last_ts"], now, st["klasa"], kind, reason, st["peak_mcap"],
                     st["last_mcap"], st["peak_liq"], st["last_liq"], st["drop"], json.dumps(e), json.dumps(gone)))
        con.commit()   # per token: the scan writes the same file every 2 minutes
        n += 1
        rows += sum(gone.values())
    return n, rows


def run(path=None, now=None, limit=BATCH, log=print):
    """One hourly pass. Returns (tokens archived, rows deleted)."""
    path = path or HYPE_DB
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0, 0
    con = connect(path)
    try:
        try:
            c = candidates(con, now, limit)
        except sqlite3.OperationalError as e:   # fresh database without token_tier yet
            if "no such table" in str(e):
                return 0, 0
            raise
        n, rows = archive(con, c, now)
    finally:
        con.close()
    forget_cache()
    if n and log:
        kinds = {}
        for _, k, _, _ in c:
            kinds[k] = kinds.get(k, 0) + 1
        log(f"rugovi: arhivirano {n} tokena ({', '.join(f'{k} {v}' for k, v in kinds.items())}), obrisano {rows} "
            "redaka; više se ne prate")
    return n, rows


# ---------- reading (dashboard, learning) ----------

def summary(path=None, now=None):
    """{"n", "n24", "by_kind": {kind: n}, "rows_deleted"} for the dashboard."""
    path = path or HYPE_DB
    out = {"n": 0, "n24": 0, "by_kind": {}, "rows_deleted": 0}
    if not os.path.exists(path):
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return out
    try:
        since = int((now or time.time()) - 86400)
        for kind, n, n24 in con.execute("SELECT kind, COUNT(*), SUM(archived_ts >= ?) FROM rug_archive GROUP BY kind", (since,)):
            out["by_kind"][kind] = n
            out["n"] += n
            out["n24"] += n24 or 0
        for (rm,) in con.execute("SELECT removed FROM rug_archive"):
            try:
                out["rows_deleted"] += sum((json.loads(rm) or {}).values())
            except (TypeError, ValueError):
                pass
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    return out


def get(token, path=None):
    """The archive row of one mint as a dict, or None."""
    path = path or HYPE_DB
    if not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            r = con.execute("SELECT * FROM rug_archive WHERE token=?", (token,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not r:
        return None
    d = dict(r)
    try:
        d["entry"] = json.loads(d["entry"] or "{}")
    except ValueError:
        d["entry"] = {}
    return d


KIND_HR = {"srusen": "srušio se", "likvidnost": "izvučena likvidnost", "mehanika": "mehanika ruga"}
