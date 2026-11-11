"""proposals.db (DATA_DIR): the proposals, their status and what happened after, the near misses per day, our own
price points for the after-outcomes, the callers' quick-exit benchmark, the daily report and a small kv.

Writers: run_proposals.py (the pass: new / updated / expired proposals, outcomes, near misses, prices, benchmark,
report) and the owner's taps on the Autopilot page (Odbij, Kupi: one row's status). Readers: the Autopilot card, the
MCP tool get_proposals and the demo account's paper entries, read-only with a short cache. WAL, so a reader never
waits for the pass.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUSES = ("novo", "kupljeno", "isteklo", "odbijeno")
KEEP_DAYS = 30          # proposals, near misses and prices older than this are deleted by the pass
PX_KEEP_S = 6 * 3600    # our own price points are needed only for the 4 h after-outcome

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, symbol TEXT, created_ts INTEGER, updated_ts INTEGER,
    expires_ts INTEGER, status TEXT NOT NULL DEFAULT 'novo', status_ts INTEGER, status_why TEXT,
    strategy TEXT, sources TEXT, n_independent INTEGER, ev_pct REAL, p_tp REAL, tp_pct REAL, sl_pct REAL,
    price0 REAL, mcap0 REAL, liq0 REAL, size_sol REAL, row TEXT,
    reject_reason TEXT, reject_note TEXT, decided_by TEXT, bought_sol REAL,
    after TEXT, after_done INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS proposals_status ON proposals (status, token);
CREATE INDEX IF NOT EXISTS proposals_created ON proposals (created_ts);
CREATE INDEX IF NOT EXISTS proposals_after ON proposals (after_done, created_ts);
CREATE TABLE IF NOT EXISTS seen (day TEXT, token TEXT, strategy TEXT, symbol TEXT, first_ts INTEGER, last_ts INTEGER,
    best_ev REAL, proposed INTEGER, why TEXT, mcap REAL, PRIMARY KEY (day, token, strategy));
CREATE TABLE IF NOT EXISTS px (token TEXT, ts INTEGER, price REAL, mcap REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS bench (handle TEXT PRIMARY KEY, n INTEGER, hits INTEGER, sl_first INTEGER, ev_pct REAL,
    ts INTEGER);
CREATE TABLE IF NOT EXISTS reports (day TEXT PRIMARY KEY, ts INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
COLS = ("id", "token", "symbol", "created_ts", "updated_ts", "expires_ts", "status", "status_ts", "status_why",
        "strategy", "sources", "n_independent", "ev_pct", "p_tp", "tp_pct", "sl_pct", "price0", "mcap0", "liq0",
        "size_sol", "row", "reject_reason", "reject_note", "decided_by", "bought_sol", "after", "after_done")


def db_path():
    """proposals.db on the persistent disk (DATA_DIR, Render /var/data), like momentum.db and range.db."""
    if os.environ.get("PROPOSALS_DB"):
        return os.environ["PROPOSALS_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "proposals.db")
    return os.path.join(ROOT, "proposals.db")


def connect(path=None):
    p = path or db_path()
    new = not os.path.exists(p) or not os.path.getsize(p)
    con = sqlite3.connect(p, timeout=30)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    """Read-only connection, None while proposals.db does not exist (the flag was never on)."""
    p = path or db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


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
    con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))


def _dict(r):
    d = dict(zip(COLS, r))
    for k in ("sources", "row", "after"):
        try:
            d[k] = json.loads(d[k]) if d[k] else ([] if k == "sources" else {})
        except ValueError:
            d[k] = [] if k == "sources" else {}
    return d


def read(con, where="1=1", args=(), order="id DESC", limit=500):
    try:
        return [_dict(r) for r in con.execute(f"SELECT {', '.join(COLS)} FROM proposals WHERE {where} ORDER BY {order} "
                                              f"LIMIT ?", (*args, int(limit)))]
    except sqlite3.Error:
        return []


def one(con, pid):
    got = read(con, "id=?", (int(pid),), limit=1)
    return got[0] if got else None


def active(con):
    """{token: proposal} of the proposals with status novo."""
    return {p["token"]: p for p in read(con, "status='novo'", order="id")}


def last_by_token(con, tokens):
    """{token: the newest proposal of the token, any status}."""
    out = {}
    toks = list(tokens)
    for i in range(0, len(toks), 500):
        part = toks[i:i + 500]
        for p in read(con, f"token IN ({','.join('?' * len(part))})", part, order="id", limit=100_000):
            out[p["token"]] = p
    return out


def _cols(p):
    """The columns of a merged row (proposals/build.finish); the whole row is kept as JSON in "row"."""
    r = {k: v for k, v in p.items() if k != "rank"}
    return {"symbol": p.get("symbol"), "expires_ts": int(p["expires_ts"]), "strategy": p.get("strategy"),
            "sources": json.dumps(p.get("sources") or []), "n_independent": p.get("n_independent"),
            "ev_pct": p.get("ev_pct"), "p_tp": p.get("p_tp"), "tp_pct": p.get("tp_pct"), "sl_pct": p.get("sl_pct"),
            "size_sol": p.get("size_sol"), "row": json.dumps(r, ensure_ascii=False)}


def insert(con, p, now):
    c = _cols(p)
    c.update(token=p["token"], created_ts=int(now), updated_ts=int(now), status="novo", status_ts=int(now),
             price0=p.get("price0"), mcap0=p.get("mcap0"), liq0=p.get("liq0"))
    cur = con.execute(f"INSERT INTO proposals ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", list(c.values()))
    return cur.lastrowid


def update(con, pid, p, now):
    c = _cols(p)
    c["updated_ts"] = int(now)
    con.execute(f"UPDATE proposals SET {', '.join(f'{k}=?' for k in c)} WHERE id=? AND status='novo'",
                [*c.values(), int(pid)])


def set_status(con, pid, status, why, now, **extra):
    """novo -> kupljeno | isteklo | odbijeno (once: a decided proposal keeps its status). True when changed."""
    if status not in STATUSES:
        raise ValueError("nepoznat status prijedloga")
    cols = {"status": status, "status_ts": int(now), "status_why": (why or "")[:300], **extra}
    cur = con.execute(f"UPDATE proposals SET {', '.join(f'{k}=?' for k in cols)} WHERE id=? AND status='novo'",
                      [*cols.values(), int(pid)])
    return cur.rowcount > 0


REJECT_REASONS = ("kasno", "ne vjerujem izvoru", "rug rizik", "premala likvidnost", "već imam dosta", "drugo")


def reject(pid, reason, note="", user="", now=None, path=None):
    """The owner's Odbij with one of REJECT_REASONS (or free text) and an optional note: stored for learning."""
    reason = (reason or "").strip()[:80] or "drugo"
    note = (note or "").strip()[:500]
    now = int(now or time.time())
    con = connect(path)
    try:
        ok = set_status(con, pid, "odbijeno", f"vlasnik: {reason}", now, reject_reason=reason, reject_note=note,
                        decided_by=user or "")
        con.commit()
    finally:
        con.close()
    if not ok:
        raise ValueError("prijedlog više nije otvoren (kupljen, odbijen ili istekao)")
    return True


def mark_bought(pid, sol, user="", now=None, path=None):
    """The owner bought through the proposal's Kupi (the buy went through _post_buy): status kupljeno."""
    now = int(now or time.time())
    con = connect(path)
    try:
        ok = set_status(con, pid, "kupljeno", "vlasnik je kupio (Brza kupnja)", now, bought_sol=float(sol or 0),
                        decided_by=user or "")
        con.commit()
        return one(con, pid) if ok else None
    finally:
        con.close()


def prune(con, now):
    """Old rows out (KEEP_DAYS; our price points after PX_KEEP_S)."""
    con.execute("DELETE FROM proposals WHERE created_ts < ? AND status != 'novo'", (int(now) - KEEP_DAYS * 86400,))
    con.execute("DELETE FROM seen WHERE last_ts < ?", (int(now) - KEEP_DAYS * 86400,))
    con.execute("DELETE FROM px WHERE ts < ?", (int(now) - PX_KEEP_S - 3600,))
    con.execute("DELETE FROM reports WHERE ts < ?", (int(now) - 90 * 86400,))
