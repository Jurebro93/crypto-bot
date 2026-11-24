"""Feature flags on the competition side (10.11., Jure: "Specifikacija za Claudea", Phase 0).

trade/settings.py holds the flags (FLAGS, flag(), set_flag()); this module is what league/copy.py, league/auto.py
and the page need around them:

- applies(name, user): should the NEW rule run for this account? live -> the Autopilot account and the paper
  account; paper -> only the paper account; shadow / off -> nobody. Players never.
- shadow(con, ...): one line in league.db shadow_decisions when the new rule would have decided otherwise than the
  old one (modes shadow and paper, for the Autopilot account), so the owner sees what a flag would change before
  any money depends on it.
- sync_paper(con): while any flag is in paper mode, the paper account PAPER_USER follows exactly what LEAGUE_USER
  follows (same targets, stakes, exits); with no flag in paper its follows are switched off. run_trade.py mirrors
  only LEAGUE_USER, so the paper account never moves real money.
- paper_result(con, since): closed trades and PnL of the paper account, the "7 days in the plus" part of the gate.

Everything here is best effort: a flag that cannot be read is "off" and the old behaviour runs.
"""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, flag TEXT, follow_id INTEGER, token TEXT,
    old_action TEXT, new_action TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS shadow_decisions_ts ON shadow_decisions (ts);
CREATE INDEX IF NOT EXISTS shadow_decisions_flag ON shadow_decisions (flag, ts);
CREATE TABLE IF NOT EXISTS paper_map (src INTEGER PRIMARY KEY, paper INTEGER);
"""
KEEP_DAYS = 30


def _ts():
    try:
        from trade import settings as ts
        return ts
    except Exception:  # noqa: BLE001 - league/ without trade/: no flags, old behaviour
        return None


def ensure(con):
    """Tables when missing. executescript commits, which must not happen in the middle of a copy pass that calls
    shadow(), so it runs only when a table is actually missing (a cheap sqlite_master read otherwise)."""
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                      "AND name IN ('shadow_decisions', 'paper_map')")}
    if len(have) < 2:
        con.executescript(SCHEMA)


def mode(name):
    """The flag's mode, "off" when trade settings cannot be read."""
    ts = _ts()
    if ts is None:
        return "off"
    try:
        return ts.flag(name)
    except Exception:  # noqa: BLE001
        return "off"


def autopilot_users():
    ts = _ts()
    return (ts.LEAGUE_USER, ts.PAPER_USER) if ts else ()


def applies(name, user, m=None):
    """True when the new rule `name` runs for `user` (see the module text)."""
    ts = _ts()
    if ts is None or not user:
        return False
    m = m or mode(name)
    if m == "live":
        return user in (ts.LEAGUE_USER, ts.PAPER_USER)
    if m == "paper":
        return user == ts.PAPER_USER
    return False


def shadowing(name, user, m=None):
    """True when the old rule still decides for `user` but the new one is to be logged next to it: the Autopilot
    account while the flag is in shadow or paper."""
    ts = _ts()
    if ts is None or user != ts.LEAGUE_USER:
        return False
    return (m or mode(name)) in ("shadow", "paper")


def shadow(con, name, follow_id, token, old_action, new_action, detail=None, now=None):
    """Log one decision the new rule would have taken differently. Never raises (a full disk loses the line)."""
    if old_action == new_action:
        return False
    try:
        ensure(con)
        con.execute("INSERT INTO shadow_decisions (ts, flag, follow_id, token, old_action, new_action, detail) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (int(now or time.time()), name, follow_id, token, old_action, new_action,
                     detail if isinstance(detail, str) or detail is None
                     else json.dumps(detail, ensure_ascii=False, separators=(",", ":"))))
        return True
    except sqlite3.Error:
        return False


def shadow_summary(con, since):
    """{flag: {"n": decisions changed, "last": ts}} since `since`."""
    try:
        ensure(con)
        rows = con.execute("SELECT flag, COUNT(*), MAX(ts) FROM shadow_decisions WHERE ts >= ? GROUP BY flag",
                           (int(since),)).fetchall()
    except sqlite3.Error:
        return {}
    return {r[0]: {"n": r[1], "last": r[2]} for r in rows}


def shadow_rows(con, name=None, limit=50):
    try:
        ensure(con)
        sql = "SELECT ts, flag, follow_id, token, old_action, new_action, detail FROM shadow_decisions"
        args = ()
        if name:
            sql += " WHERE flag = ?"
            args = (name,)
        return con.execute(sql + " ORDER BY ts DESC, id DESC LIMIT ?", (*args, int(limit))).fetchall()
    except sqlite3.Error:
        return []


def prune(con, now=None):
    try:
        con.execute("DELETE FROM shadow_decisions WHERE ts < ?", (int(now or time.time()) - KEEP_DAYS * 86400,))
    except sqlite3.Error:
        pass


def sync_paper(con, now=None, paper_on=None):
    """Mirror the Autopilot account's active follows onto the paper account while any flag is in paper mode;
    otherwise switch the paper follows off. Returns (added, updated, stopped)."""
    ts = _ts()
    if ts is None:
        return 0, 0, 0
    now = int(now or time.time())
    if paper_on is None:
        try:
            paper_on = ts.any_paper()
        except Exception:  # noqa: BLE001
            paper_on = False
    ensure(con)
    added = updated = stopped = 0
    if not paper_on:
        cur = con.execute("UPDATE follows SET active=0, stopped=? WHERE user=? AND active=1", (now, ts.PAPER_USER))
        con.execute("DELETE FROM paper_map")
        con.commit()
        return 0, 0, cur.rowcount or 0
    src = {r[0]: r for r in con.execute(
        "SELECT id, kind, target, label, size_usd, per_day, exit FROM follows WHERE user=? AND active=1",
        (ts.LEAGUE_USER,))}
    pm = dict(con.execute("SELECT src, paper FROM paper_map"))
    for sid, (_i, kind, target, label, size, per_day, ex) in src.items():
        pid = pm.get(sid)
        row = con.execute("SELECT kind, target, label, size_usd, per_day, exit, active FROM follows WHERE id=? AND user=?",
                          (pid, ts.PAPER_USER)).fetchone() if pid else None
        if row and row[6]:
            if tuple(row[:6]) != (kind, target, label, size, per_day, ex):
                con.execute("UPDATE follows SET kind=?, target=?, label=?, size_usd=?, per_day=?, exit=? WHERE id=?",
                            (kind, target, label, size, per_day, ex, pid))
                updated += 1
            continue
        if row is not None and not row[6] and json.loads(ex or "{}").get("once"):
            continue   # a "next call only" follow already used its entry on the paper side: it stays stopped
        cur = con.execute("INSERT INTO follows (user, kind, target, label, size_usd, per_day, exit, created) "
                          "VALUES (?,?,?,?,?,?,?,?)", (ts.PAPER_USER, kind, target, label, size, per_day, ex, now))
        con.execute("INSERT OR REPLACE INTO paper_map VALUES (?,?)", (sid, cur.lastrowid))
        added += 1
    for sid, pid in pm.items():
        if sid not in src:
            cur = con.execute("UPDATE follows SET active=0, stopped=? WHERE id=? AND user=? AND active=1",
                              (now, pid, ts.PAPER_USER))
            stopped += cur.rowcount or 0
            con.execute("DELETE FROM paper_map WHERE src=?", (sid,))
    con.commit()
    return added, updated, stopped


def paper_result(con, since):
    """{"n": closed trades, "pnl": USD, "open": open trades} of the paper account opened since `since`."""
    ts = _ts()
    if ts is None:
        return {"n": 0, "pnl": 0.0, "open": 0}
    try:
        n, pnl, op = con.execute(
            "SELECT COALESCE(SUM(status='closed'),0), COALESCE(SUM(CASE WHEN status='closed' THEN pnl_usd END),0), "
            "COALESCE(SUM(status='open'),0) FROM trades WHERE user=? AND opened_ts>=?",
            (ts.PAPER_USER, int(since or 0))).fetchone()
    except sqlite3.Error:
        return {"n": 0, "pnl": 0.0, "open": 0}
    return {"n": int(n), "pnl": float(pnl), "open": int(op)}
