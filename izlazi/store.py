"""izlazi.db: the learned exit of every source (izlazi/learn writes it nightly; league/exitplan, the pages, the MCP API
and the OpenAI critic only read it).

    learned_exits  one row per source: source_kind (wallet | kol | ekipa | strategy | the prior rows: <kind> with
                   source_id "*", and "*" / "*" for everything), params (izlazi/sim.Params as JSON), n (entries with a
                   path), n_out (of those, the newer 30 % the rule was NOT chosen on), ev_in (the chosen rule on the
                   older 70 %, shrunk toward the prior), ev_out / default_ev_out (the chosen rule / today's "brzi
                   profit" on the same newer entries, raw), ci_lo / ci_hi (90 % bootstrap interval of ev_out), stats
                   (JSON: hit rate, worst trade, drawdown, the paired interval against the default, the source's own
                   behaviour, coverage), ts. EV fields are PERCENT of the stake per trade, net of the round trip.
    runs           one summary per run (coverage per source kind, timings), the last RUNS_KEEP
    kv             night_day (the Zagreb date the nightly run is done for)

On the persistent disk (IZLAZI_DB, else DATA_DIR/izlazi.db, Render /var/data), small: a few thousand rows at most
(izlazi/learn.MAX_ROWS), replaced as a whole by every run.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_KEEP = 30
CACHE_S = 300
PROOF_MARGIN = 1.0      # real money: the learned rule's EV out of sample at least this many points over the default
PROOF_N_OUT = 8         # ... on at least this many out-of-sample entries
PROOF_DIFF_LO = -1.0    # ... and the paired 90 % interval of (learned - default) per entry not under -1 point at its low end
MAX_AGE_S = 3 * 86400   # a learned row older than this is not used (the nightly run stopped)
SCHEMA = """
CREATE TABLE IF NOT EXISTS learned_exits (
    source_kind TEXT, source_id TEXT, params TEXT, n INTEGER, n_out INTEGER, ev_in REAL, ev_out REAL, ci_lo REAL,
    ci_hi REAL, default_ev_out REAL, stats TEXT, ts INTEGER, PRIMARY KEY (source_kind, source_id));
CREATE TABLE IF NOT EXISTS runs (ts INTEGER PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
COLS = ("source_kind", "source_id", "params", "n", "n_out", "ev_in", "ev_out", "ci_lo", "ci_hi", "default_ev_out",
        "stats", "ts")
_CACHE = {}


def db_path():
    if os.environ.get("IZLAZI_DB"):
        return os.environ["IZLAZI_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "izlazi.db")
    return os.path.join(ROOT, "izlazi.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM learned_exits LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def kv_get(con, k, default=None):
    try:
        r = con.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return json.loads(r[0]) if r else default
    except (sqlite3.Error, ValueError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


def save(con, rows, info, now=None):
    """Replace learned_exits with `rows` (dicts with COLS; params / stats as dicts) and keep the run's summary."""
    now = int(now or time.time())
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("DELETE FROM learned_exits")
        con.executemany(f"INSERT OR REPLACE INTO learned_exits VALUES ({','.join('?' * len(COLS))})",
                        [tuple(json.dumps(r[c], ensure_ascii=False, separators=(",", ":"))
                               if c in ("params", "stats") else r.get(c) for c in COLS) for r in rows])
        con.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)",
                    (now, json.dumps(info, ensure_ascii=False, separators=(",", ":"))))
        con.execute("DELETE FROM runs WHERE ts NOT IN (SELECT ts FROM runs ORDER BY ts DESC LIMIT ?)", (RUNS_KEEP,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    _CACHE.clear()


def _row(r):
    d = dict(zip(COLS, r))
    for c in ("params", "stats"):
        try:
            d[c] = json.loads(d[c] or "{}")
        except ValueError:
            d[c] = {}
    return d


def load(path=None, fresh=False):
    """{(source_kind, source_id): row} of the latest run (read-only, cached CACHE_S per file and its mtime); {}
    without the file or the table."""
    path = path or db_path()
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _CACHE.get(path)
    if hit and not fresh and hit[1] == mt and time.time() - hit[0] < CACHE_S:
        return hit[2]
    out = {}
    con = ro(path)
    if con is not None:
        try:
            for r in con.execute(f"SELECT {', '.join(COLS)} FROM learned_exits"):
                d = _row(r)
                out[(d["source_kind"], d["source_id"])] = d
        except sqlite3.Error:
            out = {}
        finally:
            con.close()
    _CACHE[path] = (time.time(), mt, out)
    return out


def last_run(path=None):
    con = ro(path)
    if con is None:
        return None
    try:
        r = con.execute("SELECT ts, data FROM runs ORDER BY ts DESC LIMIT 1").fetchone()
        return {"ts": r[0], **json.loads(r[1] or "{}")} if r else None
    except (sqlite3.Error, ValueError):
        return None
    finally:
        con.close()


def proven(row, margin=PROOF_MARGIN, n_out_min=PROOF_N_OUT):
    """(True, "") when a learned row may run with REAL money: at least n_out_min out-of-sample entries, its EV out of
    sample at least `margin` points over today's default on the same entries, its 90 % interval not entirely under
    the default's EV, the paired 90 % interval of the difference (the same entries, learned minus default) not lower
    than PROOF_DIFF_LO at its low end (a gain of 1 point that is as likely a loss of 3 is not proof), and a rule that
    differs from the default; else (False, why in Croatian)."""
    from izlazi import sim
    if not row:
        return False, "nema naučenog reda"
    n_out = row.get("n_out") or 0
    ev, dv, hi = row.get("ev_out"), row.get("default_ev_out"), row.get("ci_hi")
    if sim.canon(sim.from_dict(row.get("params"))) == sim.canon(sim.DEFAULT):
        return False, "naučeno = zadano (brzi profit)"
    if n_out < n_out_min:
        return False, f"premalo ulaza van uzorka ({n_out}, treba {n_out_min})"
    if ev is None or dv is None:
        return False, "nema EV-a van uzorka"
    if ev - dv < margin - 1e-9:
        return False, f"EV van uzorka {ev:+.2f} % nije barem {margin:g} boda iznad zadanog {dv:+.2f} %"
    if hi is not None and hi <= dv:
        return False, f"cijeli interval ({row.get('ci_lo'):+.2f} .. {hi:+.2f} %) ispod zadanog {dv:+.2f} %"
    d = (row.get("stats") or {}).get("diff_ci") or [None, None]
    if d[0] is None:
        return False, "nema intervala razlike prema zadanom"
    if d[0] < PROOF_DIFF_LO - 1e-9:
        return False, (f"razlika prema zadanom nesigurna: 90 % interval {d[0]:+.2f} .. {d[1]:+.2f} boda (donji rub "
                       f"ispod {PROOF_DIFF_LO:+g})")
    return True, ""


def fresh_row(row, now=None, max_age_s=MAX_AGE_S):
    return bool(row) and (now or time.time()) - (row.get("ts") or 0) <= max_age_s
