"""X features from the outside analyst (Grok) through the MCP endpoint, plan item 3.6 minimal (10.11., Grok MCP audit
10: "Hope CA posts started ~2 h before our first tracked call"). Grok reads X; MemeSonar does not pay for an X search
of every CA. Grok writes what it counted (e.g. how many posts contained the token's CA in one hour) and the tool keeps
it, point in time, for a later test of whether it predicts anything. Scoring does not read it yet.

Storage: xfeat.db (its own file, next to the other databases: XFEAT_DB, else DATA_DIR, else next to kol.db, the
kol/minute.db_path rule), table x_features. Insert only: no tool updates or deletes a row.
    subject_kind  token | handle | wallet       subject     the mint / X handle / wallet address
    ts_asof       the moment the features describe (given by the client)
    ts_observed   when the server received them (set here, never by the client): a backtest uses only rows whose
                  ts_observed is before its decision, so a value counted later cannot leak into the past
    features      JSON object (at most JSON_MAX characters); recommended for the CA count:
                  {"ca_posts_1h": 12, "ca_posts_hour_ts": 1794300000}  (posts with the CA in the hour starting then)
    source        "mcp:<key fingerprint>"      backfill   1 = the client counted a past hour after the fact
Writes are accepted only while the trade setting flag x_features_ingest is not "off" (the owner switches it on the
Autopilot page) and at most RATE_PER_HOUR per key an hour (as ui/assistnotes).

10.11. (market scanner, scan/xmom.py): the scanner's OWN X counts go to the sibling table x_momentum in the same file
(posts / unique authors in 15 / 60 min, bot share, x_momentum_score, x_early; source "scan"), insert only as well. It
is written while the flag market_scan is on; x_features_ingest keeps governing only this MCP intake, and Grok's rows
here (source mcp:*) take precedence over the scanner's count for the same token (scan/xmom.latest).
"""
import json
import os
import re
import sqlite3
import time

KINDS = ("token", "handle", "wallet")
JSON_MAX = 20_000
RATE_PER_HOUR = 120
KEY_MAX = 64
FUTURE_S = 300            # a ts_asof this far in the future is a clock error, refused
LIVE_S = 3 * 3600         # a ts_asof older than this is a backfill: the client must say so (backfill=true)
OLDEST_TS = 1_600_000_000
MAX_LIMIT = 500
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
FLAG = "x_features_ingest"

SCHEMA = """CREATE TABLE IF NOT EXISTS x_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT, subject_kind TEXT NOT NULL, subject TEXT NOT NULL,
    ts_observed INTEGER NOT NULL, ts_asof INTEGER NOT NULL, features TEXT NOT NULL, source TEXT,
    backfill INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL)"""
INDEXES = ("CREATE INDEX IF NOT EXISTS x_features_subject ON x_features (subject_kind, subject, ts_asof)",
           "CREATE INDEX IF NOT EXISTS x_features_source ON x_features (source, created)")


def db_path():
    """xfeat.db on the persistent disk: XFEAT_DB, else DATA_DIR (Render /var/data), else next to kol.db."""
    if os.environ.get("XFEAT_DB"):
        return os.environ["XFEAT_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "xfeat.db")
    from kol import store
    return os.path.join(os.path.dirname(os.path.abspath(store.DB)), "xfeat.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.execute(SCHEMA)
    for sql in INDEXES:
        con.execute(sql)
    con.commit()
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


# ---------- validation ---------------------------------------------------------------------------------------------

def _kind(x):
    k = str(x or "token").strip().lower()
    if k not in KINDS:
        raise ValueError(f"subject_kind must be one of {', '.join(KINDS)}")
    return k


def _subject(x, kind):
    s = str(x or "").strip()
    if kind in ("token", "wallet"):
        if not MINT.fullmatch(s):
            raise ValueError(f"subject must be a Solana {'token' if kind == 'token' else 'wallet'} address")
        return s
    s = s.lstrip("@")
    if not HANDLE.fullmatch(s):
        raise ValueError("subject must be an X handle (letters, digits, _; up to 15)")
    return s.lower()


def _int(x, name):
    if isinstance(x, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if v != int(v):
        raise ValueError(f"{name} must be an integer")
    return int(v)


def _features(x):
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except ValueError:
            raise ValueError("features must be a JSON object")
    if not isinstance(x, dict) or not x:
        raise ValueError("features must be a non-empty JSON object")
    for k in x:
        if not isinstance(k, str) or not k or len(k) > KEY_MAX:
            raise ValueError(f"feature names must be strings of 1-{KEY_MAX} characters")
    if "ca_posts_1h" in x:
        n = _int(x["ca_posts_1h"], "ca_posts_1h")
        if n < 0:
            raise ValueError("ca_posts_1h must be 0 or more")
        x = {**x, "ca_posts_1h": n}
    if "ca_posts_hour_ts" in x:
        h = _int(x["ca_posts_hour_ts"], "ca_posts_hour_ts")
        if h < OLDEST_TS:
            raise ValueError("ca_posts_hour_ts must be unix seconds (the start of the counted hour)")
        x = {**x, "ca_posts_hour_ts": h}
    s = json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    if len(s) > JSON_MAX:
        raise ValueError(f"features are larger than {JSON_MAX} characters")
    return s


def _on(tcon=None):
    """The owner's switch (trade settings flag x_features_ingest): "off" refuses every write."""
    from trade import settings
    own = tcon is None
    try:
        tcon = tcon or settings.connect()
    except sqlite3.Error:
        return False
    try:
        return settings.flag(FLAG, con=tcon) != "off"
    finally:
        if own:
            tcon.close()


# ---------- the MCP tools ------------------------------------------------------------------------------------------

def submit(subject, subject_kind="token", features=None, ts_asof=None, backfill=False, kid="local", now=None,
           tcon=None, path=None):
    """Insert one row; returns {"id", ...}. Raises ValueError with the reason for the client."""
    now = int(now or time.time())
    if not _on(tcon):
        raise ValueError(f"X features are switched off (trade settings flag {FLAG} is off): nothing stored")
    kind = _kind(subject_kind)
    subj = _subject(subject, kind)
    feats = _features(features)
    if ts_asof is None or ts_asof == "":
        raise ValueError("ts_asof is required: unix seconds of the moment the features describe")
    asof = _int(ts_asof, "ts_asof")
    if asof < OLDEST_TS or asof > now + FUTURE_S:
        raise ValueError("ts_asof must be unix seconds, not in the future")
    if not isinstance(backfill, bool):
        backfill = str(backfill).strip().lower() in ("1", "true", "yes")
    if asof < now - LIVE_S and not backfill:
        raise ValueError(f"ts_asof is more than {LIVE_S // 3600} h old: send backfill=true for a past hour (backfills "
                         "are kept apart from live observations)")
    source = f"mcp:{kid}"
    con = connect(path)
    try:
        n = con.execute("SELECT COUNT(*) FROM x_features WHERE source=? AND created>?", (source, now - 3600)).fetchone()[0]
        if n >= RATE_PER_HOUR:
            raise ValueError(f"rate limit: at most {RATE_PER_HOUR} X feature rows an hour per key")
        cur = con.execute("INSERT INTO x_features (subject_kind, subject, ts_observed, ts_asof, features, source, "
                          "backfill, created) VALUES (?,?,?,?,?,?,?,?)",
                          (kind, subj, now, asof, feats, source, int(bool(backfill)), now))
        con.commit()
        rid = cur.lastrowid
    finally:
        con.close()
    print(f"mcp: X značajke #{rid} za {kind} {subj[:8]} spremljene", flush=True)
    return {"id": rid, "subject": subj, "subject_kind": kind, "ts_observed": now, "ts_asof": asof,
            "backfill": bool(backfill), "status": "stored",
            "message": ("Stored in MemeSonar's X features (insert only); get_trade_candidates and the market scanner "
                        "read a token row for 2 h (instead of a paid X lookup), and 30 min as evidence for a rug override.")}


def read(subject, subject_kind="token", since=None, limit=None, path=None):
    """The rows of one subject, newest ts_asof first."""
    kind = _kind(subject_kind)
    subj = _subject(subject, kind)
    try:
        lim = max(1, min(MAX_LIMIT, int(limit if limit is not None else 100)))
    except (TypeError, ValueError):
        lim = 100
    try:
        since = int(since or 0)
    except (TypeError, ValueError):
        since = 0
    con = ro(path)
    rows, total = [], 0
    if con is not None:
        try:
            total = con.execute("SELECT COUNT(*) FROM x_features WHERE subject_kind=? AND subject=? AND ts_asof>=?",
                                (kind, subj, since)).fetchone()[0]
            for i, obs, asof, f, src, bf in con.execute(
                    "SELECT id, ts_observed, ts_asof, features, source, backfill FROM x_features WHERE subject_kind=? "
                    "AND subject=? AND ts_asof>=? ORDER BY ts_asof DESC, id DESC LIMIT ?", (kind, subj, since, lim)):
                try:
                    feats = json.loads(f)
                except ValueError:
                    feats = None
                rows.append({"id": i, "ts_observed": obs, "ts_asof": asof, "features": feats, "source": src,
                             "backfill": bool(bf)})
        except sqlite3.Error:
            rows, total = [], 0
        finally:
            con.close()
    return {"ts": int(time.time()), "subject": subj, "subject_kind": kind, "since": since, "limit": lim,
            "total": total, "rows": rows,
            "notes": "insert-only rows, newest ts_asof first; ts_observed = when MemeSonar received the row (a test "
                     "of a feature uses only rows observed before its decision); backfill = counted after the fact"}
