"""Dnevnik odluka: every token the "Prijedlog za danas" box shows is written down with its grade and the market cap at
that moment; 24 h later the price path (hype_snapshots, every 20 min) says what it did. Audit 7.11.: a decision
must be reproducible and testable, not only shown. The box then carries its own track record per grade ("visoka:
5 od 8 dalo +15 % prije stopa"), the same exit rule the box tells the user (TP +15 %, stop −25 %), order-aware:
+15 % touched AFTER the stop would have fired does not count.
"""
import sqlite3
import statistics
import time

SCHEMA = """CREATE TABLE IF NOT EXISTS prijedlog_log (
    token TEXT, day TEXT, ts INTEGER, kind TEXT, razina TEXT, mcap0 REAL, conf REAL,
    max24 REAL, r24 REAL, hit INTEGER, stop_first INTEGER, n_snap INTEGER, labelled_ts INTEGER,
    PRIMARY KEY (token, day))"""
TP, SL = 0.15, -0.25
HORIZON_S = 24 * 3600


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def log(path, picks, kind, now=None):
    """One row per token per UTC day (the first grade it was shown with). Silent on a locked or missing DB.
    9.11. (audit P50/P51): the Pregled box passes kind='zivo' and razina='uživo' for the Autopilot's live rows, so
    summary()/sentence() never add them to the old pipeline's 'visoka' record."""
    if not picks:
        return 0
    now = int(now or time.time())
    try:
        con = sqlite3.connect(path, timeout=5)
    except sqlite3.Error:
        return 0
    try:
        con.execute(SCHEMA)
        n = 0
        for p in picks:
            if not p.get("mcap0"):
                continue
            cur = con.execute("INSERT OR IGNORE INTO prijedlog_log (token, day, ts, kind, razina, mcap0, conf) VALUES (?,?,?,?,?,?,?)",
                              (p["token"], _day(now), now, kind, p.get("razina") or "visoka", p["mcap0"], p.get("conf")))
            n += cur.rowcount
        con.commit()
        return n
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def outcome(path, mcap0, tp=TP, sl=SL):
    """path: [(ts, value)] after the pick -> (max24, r24, hit, stop_first). hit: +tp reached before −sl."""
    vals = [v for _, v in path if v and v > 0]
    if not mcap0 or len(vals) < 2:
        return None
    rets = [v / mcap0 - 1 for v in vals]
    tp_at = next((i for i, r in enumerate(rets) if r >= tp), None)
    sl_at = next((i for i, r in enumerate(rets) if r <= sl), None)
    stop_first = sl_at is not None and (tp_at is None or sl_at < tp_at)
    return max(rets), rets[-1], int(tp_at is not None and not stop_first), int(stop_first)


def label(con, now=None):
    """Fill max24/r24/hit/stop_first for picks older than 24 h from hype_snapshots. Returns rows labelled."""
    now = int(now or time.time())
    con.execute(SCHEMA)
    rows = con.execute("SELECT token, day, ts, mcap0 FROM prijedlog_log WHERE labelled_ts IS NULL AND ts <= ?",
                       (now - HORIZON_S,)).fetchall()
    n = 0
    for token, day, ts, mcap0 in rows:
        snaps = con.execute("SELECT ts, mcap, price FROM hype_snapshots WHERE token=? AND ts>=? AND ts<=? ORDER BY ts",
                            (token, ts, ts + HORIZON_S)).fetchall()
        path = [(t, m) for t, m, _ in snaps if m]
        if len(path) < 2 and snaps:   # no market cap in the snapshots: scale the price path to mcap0
            p0 = next((p for _, _, p in snaps if p), None)
            path = [(t, mcap0 * p / p0) for t, _, p in snaps if p] if p0 else []
        o = outcome(path, mcap0)
        if o:
            con.execute("UPDATE prijedlog_log SET max24=?, r24=?, hit=?, stop_first=?, n_snap=?, labelled_ts=? "
                        "WHERE token=? AND day=?", (*o, len(path), now, token, day))
        else:
            con.execute("UPDATE prijedlog_log SET n_snap=?, labelled_ts=? WHERE token=? AND day=?", (len(path), now, token, day))
        n += 1
    con.commit()
    return n


def summary(path, days=7, now=None):
    """{razina: {n, labelled, hit, stop_first, med_max}} over the last `days`; {} without the table."""
    now = int(now or time.time())
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        rows = con.execute("SELECT razina, max24, hit, stop_first, labelled_ts FROM prijedlog_log WHERE ts >= ?",
                           (now - days * 86400,)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    out = {}
    for raz, mx, hit, sf, lab in rows:
        s = out.setdefault(raz, {"n": 0, "labelled": 0, "hit": 0, "stop_first": 0, "maxes": []})
        s["n"] += 1
        if lab and mx is not None:
            s["labelled"] += 1
            s["hit"] += hit or 0
            s["stop_first"] += sf or 0
            s["maxes"].append(mx)
    for s in out.values():
        s["med_max"] = statistics.median(s.pop("maxes")) if s["labelled"] else None
    return out


def sentence(summ, min_n=3):
    """One Croatian line of the box's own record, or '' before there is enough."""
    parts = []
    for raz in ("uživo", "visoka", "srednja", "niska"):   # 9.11. (audit P50): the live list's rows are their own grade
        s = summ.get(raz)
        if s and s["labelled"] >= min_n:
            parts.append(f"{raz} {s['hit']} od {s['labelled']} dalo +{TP * 100:.0f} % prije stopa (stop prvi {s['stop_first']}, "
                         f"medijan vrha {s['med_max']:+.0%})")
    if not parts:
        return ""
    return "Moji prijedlozi zadnjih 7 dana, provjereni 24 h kasnije: " + "; ".join(parts) + "."
