"""proposals.db (DATA_DIR): the proposals, their status and what happened after, the near misses per day, our own
price points for the after-outcomes, the callers' quick-exit benchmark, the daily report and a small kv.

Writers: run_proposals.py (the pass: new / updated / expired proposals, outcomes, near misses, prices, benchmark,
report), the owner's taps on the Autopilot page (Odbij, Kupi: one row's status) and, 11.11., the demo account's paper
loop (proposals/paper.py, run_ui: the waiting columns, the stop rule's isteklo and the paper entry, short timeout).
Readers: the Autopilot card, the MCP tool get_proposals and the paper loop, read-only with a short cache. WAL, so a
reader never waits for the pass.
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
    after TEXT, after_done INTEGER NOT NULL DEFAULT 0,
    below_sl_at_creation INTEGER, last_mcap REAL, last_mcap_ts INTEGER, zone_seen_ts INTEGER, zone_seen_mcap REAL,
    paper_ts INTEGER, paper_mcap REAL);
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
BASE_COLS = ("id", "token", "symbol", "created_ts", "updated_ts", "expires_ts", "status", "status_ts", "status_why",
             "strategy", "sources", "n_independent", "ev_pct", "p_tp", "tp_pct", "sl_pct", "price0", "mcap0", "liq0",
             "size_sol", "row", "reject_reason", "reject_note", "decided_by", "bought_sol", "after", "after_done")
# 11.11. (the owner's rules after HAOBIBI): the waiting state. below_sl_at_creation 1 / 0: the market cap was under /
# above the proposal's stop when it was made (the stop rule, strategies.wait_check); last_mcap(_ts): the newest market
# cap the pass or the demo account's paper loop read; zone_seen_ts / zone_seen_mcap: the first time it was seen inside
# its entry zone; paper_ts / paper_mcap: the demo account's paper entry ("ušao (paper) na MC ...", status stays novo).
# 11.11. (the owner's decision 4, proposals/publish.py): wait_why NULL = published (shown), else the state "čeka zonu"
# with the reason (outside the entry zone, or within 1 ATR of the stop); published_ts / published_mcap: the first time it
# was published. A proposal made before these columns reads as published (as it was shown then).
WAIT_COLS = (("below_sl_at_creation", "INTEGER"), ("last_mcap", "REAL"), ("last_mcap_ts", "INTEGER"),
             ("zone_seen_ts", "INTEGER"), ("zone_seen_mcap", "REAL"), ("paper_ts", "INTEGER"), ("paper_mcap", "REAL"),
             ("wait_why", "TEXT"), ("published_ts", "INTEGER"), ("published_mcap", "REAL"))
COLS = BASE_COLS + tuple(c for c, _t in WAIT_COLS)
PRICE_FRESH_S = 600     # a market cap older than this is not the price "now" (sync, the view)


def db_path():
    """proposals.db on the persistent disk (DATA_DIR, Render /var/data), like momentum.db and range.db."""
    if os.environ.get("PROPOSALS_DB"):
        return os.environ["PROPOSALS_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "proposals.db")
    return os.path.join(ROOT, "proposals.db")


def connect(path=None, timeout=30):
    p = path or db_path()
    new = not os.path.exists(p) or not os.path.getsize(p)
    con = sqlite3.connect(p, timeout=timeout)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    con.executescript(SCHEMA)
    migrate(con)
    return con


def migrate(con):
    """The waiting columns on a proposals.db made before them (ALTER TABLE, once)."""
    have = {r[1] for r in con.execute("PRAGMA table_info(proposals)")}
    for c, t in WAIT_COLS:
        if c not in have:
            con.execute(f"ALTER TABLE proposals ADD COLUMN {c} {t}")
    con.commit()


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
    """Proposals as dicts. A read-only reader of a proposals.db the pass has not migrated yet gets the waiting columns
    as None."""
    for cols in (COLS, BASE_COLS):
        try:
            rows = con.execute(f"SELECT {', '.join(cols)} FROM proposals WHERE {where} ORDER BY {order} LIMIT ?",
                               (*args, int(limit))).fetchall()
        except sqlite3.OperationalError as e:
            if cols is COLS and "no such column" in str(e):
                continue
            return []
        except sqlite3.Error:
            return []
        return [_dict(tuple(r) + (None,) * (len(COLS) - len(cols))) for r in rows]
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
    from . import strategies
    c = _cols(p)
    c.update(token=p["token"], created_ts=int(now), updated_ts=int(now), status="novo", status_ts=int(now),
             price0=p.get("price0"), mcap0=p.get("mcap0"), liq0=p.get("liq0"),
             below_sl_at_creation=strategies.below_stop(p.get("mcap0"), strategies.stop_of(p)),
             wait_why=p.get("wait_why"), published_ts=None if p.get("wait_why") else int(now),
             published_mcap=None if p.get("wait_why") else p.get("mcap0"))
    cur = con.execute(f"INSERT INTO proposals ({', '.join(c)}) VALUES ({', '.join('?' * len(c))})", list(c.values()))
    return cur.lastrowid


def update(con, pid, p, now):
    c = _cols(p)
    c["updated_ts"] = int(now)
    con.execute(f"UPDATE proposals SET {', '.join(f'{k}=?' for k in c)} WHERE id=? AND status='novo'",
                [*c.values(), int(pid)])
    mark_published(con, [(pid, p.get("wait_why"), (p.get("market") or {}).get("market_cap_usd") or p.get("mcap0"))], now)


def mark_published(con, pubs, now):
    """pubs [(proposal id, wait_why or None, market cap)]: the publication state (11.11., decision 4): wait_why NULL =
    published (the first time: published_ts / published_mcap), else "čeka zonu" with the reason."""
    for pid, why, mc in pubs:
        pub = why is None
        con.execute("UPDATE proposals SET wait_why=?, published_ts=CASE WHEN ? AND published_ts IS NULL THEN ? ELSE "
                    "published_ts END, published_mcap=CASE WHEN ? AND published_mcap IS NULL THEN ? ELSE published_mcap "
                    "END WHERE id=? AND status='novo'",
                    ((why or None) and str(why)[:300], int(pub), int(now), int(pub), mc, int(pid)))


def published(p):
    """True when a proposal (a read() dict) is published now (wait_why empty; an old row without the column too)."""
    return not p.get("wait_why")


def set_status(con, pid, status, why, now, **extra):
    """novo -> kupljeno | isteklo | odbijeno (once: a decided proposal keeps its status). True when changed."""
    if status not in STATUSES:
        raise ValueError("nepoznat status prijedloga")
    cols = {"status": status, "status_ts": int(now), "status_why": (why or "")[:300], **extra}
    cur = con.execute(f"UPDATE proposals SET {', '.join(f'{k}=?' for k in cols)} WHERE id=? AND status='novo'",
                      [*cols.values(), int(pid)])
    return cur.rowcount > 0


def mark_seen(con, seen, now):
    """seen [(proposal id, market cap, inside its zone)]: the newest market cap, and the first time inside the zone."""
    for pid, mc, inside in seen:
        if not mc:
            continue
        con.execute("UPDATE proposals SET last_mcap=?, last_mcap_ts=?, zone_seen_ts=CASE WHEN ? AND zone_seen_ts IS NULL "
                    "THEN ? ELSE zone_seen_ts END, zone_seen_mcap=CASE WHEN ? AND zone_seen_mcap IS NULL THEN ? ELSE "
                    "zone_seen_mcap END WHERE id=? AND status='novo'",
                    (float(mc), int(now), int(bool(inside)), int(now), int(bool(inside)), float(mc), int(pid)))


def mark_paper(con, pid, mcap, now):
    """The demo account's paper entry of a waiting proposal (status stays novo: the owner may still buy it)."""
    cur = con.execute("UPDATE proposals SET paper_ts=?, paper_mcap=?, status_why=? WHERE id=? AND status='novo' AND "
                      "paper_ts IS NULL", (int(now), mcap, f"ušao (paper) na MC ${float(mcap or 0):,.0f}", int(pid)))
    return cur.rowcount > 0


def last_px(con, tokens, since):
    """{token: (ts, market cap)}: the newest point of proposals.db px at or after since."""
    toks = list(tokens)
    if not toks:
        return {}
    try:
        rows = con.execute(f"SELECT token, ts, mcap FROM px WHERE ts >= ? AND mcap > 0 AND token IN "
                           f"({','.join('?' * len(toks))}) ORDER BY ts", (int(since), *toks)).fetchall()
    except sqlite3.Error:
        return {}
    return {t: (ts, m) for t, ts, m in rows}


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
