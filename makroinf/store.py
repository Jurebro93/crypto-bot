"""makroinf.db (MAKROINF_DB, else DATA_DIR/makroinf.db like the other databases; start.sh links it to the persistent
disk), the configuration and the spend caps.

Spend (CLAUDE.md: "prije svakog novog troška izmjeri"): every paid call is booked here (table spend: ts, day, src,
phase, what, usd) and in usage.db (usage/meter: service "twitterapi" / "openai", method "makroinf"). The caps, per phase:
  pilot       twitterapi one-off PILOT (5 $) for the 50-account backfill; OpenAI one-off (4 $) for its classification
  dan         after the pilot: twitterapi 0,50 $ a UTC day (incremental fetch, deletion checks, profiles, the rest of the
              backfill), OpenAI 0,25 $ a UTC day (the new posts)
  provjera    the quality check's critic pass (OPENAI_MODEL_DEEP), 1 $ a check
  prosirenje  the expansion to 300 accounts, only after a passed check (or the owner forces it): its own one-off caps
A call is made only when the most it can cost fits the cap left (twitterapi: a full page; OpenAI: openai_api.max_cost),
so a cap is never crossed; at the cap the job stops cleanly and says so in the log.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "makroinf: "
FLAG = "makroinf_indeks"     # DEMO input of the index into veliki/makro (paper by the owner's order, NEVER_LIVE)
SWITCH = "makroinf_javno"    # owner switch: the public pages (default off: routes 404, nothing in the sitemap)

DEFAULT = {
    # caps (USD)
    "pilot_twapi_usd": 5.0, "day_twapi_usd": 0.50, "pilot_openai_usd": 4.0, "day_openai_usd": 0.25,
    "quality_openai_usd": 1.0, "expand_twapi_usd": 15.0, "expand_openai_usd": 5.0,
    # accounts
    "pilot_n": 50, "expand_n": 300, "min_followers": 100_000, "active_days": 30, "circle_max": 4, "circle_min_mentions": 3,
    # fetch: 12 months back, two half-month windows a month with one page (~20 posts) each = ~40 macro posts a month
    # spread over the year, + the last 100 posts (5 pages); daily: the macro query since the last fetch (<= 3 pages)
    "months": 12, "half_pages": 1, "last_pages": 5, "incr_pages": 3, "page_posts": 20,
    # classification
    "cls_model": "gpt-5-mini", "cls_batch": 20, "cls_effort": "minimal", "cls_out_per_post": 220, "cls_max_tries": 2,
    "cls_workers": 4,
    # a round of run.krug (every ~10 min from start.sh, every minute while the pilot runs): at most this long
    "krug_s": 420, "prices_every_s": 20 * 3600, "incr_every_s": 20 * 3600, "deleted_every_s": 6 * 3600,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (handle TEXT PRIMARY KEY, name TEXT, category TEXT, lang TEXT, source TEXT,
    status TEXT, why TEXT, owner_seed INTEGER DEFAULT 0, user_id TEXT, followers INTEGER, statuses INTEGER,
    created_at TEXT, last_post_ts INTEGER, resolved_ts INTEGER, added_ts INTEGER, protected INTEGER DEFAULT 0,
    note TEXT);
CREATE TABLE IF NOT EXISTS profile_d (handle TEXT, day TEXT, followers INTEGER, statuses INTEGER,
    PRIMARY KEY (handle, day));
CREATE TABLE IF NOT EXISTS candidates (handle TEXT, for_name TEXT, name TEXT, followers INTEGER, bio TEXT,
    why TEXT, ts INTEGER, status TEXT DEFAULT 'needs_owner_confirm', PRIMARY KEY (handle, for_name));
CREATE TABLE IF NOT EXISTS fetch_log (handle TEXT, unit TEXT, done_ts INTEGER, n INTEGER, usd REAL, phase TEXT,
    PRIMARY KEY (handle, unit));
CREATE TABLE IF NOT EXISTS tweets (id TEXT PRIMARY KEY, handle TEXT, ts INTEGER, text TEXT, quoted_text TEXT,
    quoted_handle TEXT, lang TEXT, likes INTEGER, retweets INTEGER, replies INTEGER, quotes INTEGER, views INTEGER,
    is_reply INTEGER, url TEXT, src TEXT, fetched_ts INTEGER, kw INTEGER, cls_ts INTEGER, cls_v TEXT, cls_model TEXT,
    cls_tries INTEGER DEFAULT 0, macro INTEGER);
CREATE INDEX IF NOT EXISTS tweets_handle ON tweets (handle, ts);
CREATE INDEX IF NOT EXISTS tweets_cls ON tweets (cls_ts, kw);
CREATE TABLE IF NOT EXISTS calls (id TEXT, asset TEXT, handle TEXT, ts INTEGER, avail_ts INTEGER, direction TEXT,
    horizon_days REAL, conditional INTEGER, cond_text TEXT, trigger_level REAL, trigger_dir TEXT, target REAL,
    invalidation REAL, confidence TEXT, prob REAL, promo INTEGER, unclear INTEGER, withdraws INTEGER, model TEXT,
    prompt_v TEXT, cls_ts INTEGER, PRIMARY KEY (id, asset));
CREATE INDEX IF NOT EXISTS calls_handle ON calls (handle, asset, ts);
CREATE TABLE IF NOT EXISTS outcomes (eid TEXT, horizon TEXT, rules_v TEXT, handle TEXT, asset TEXT, direction TEXT,
    w REAL, t_call INTEGER, t_start INTEGER, p0 REAL, thr REAL, ret REAL, res TEXT, level TEXT, follow REAL,
    b_bull TEXT, b_rand_hit REAL, b_rand_dec REAL, b_trend TEXT, b_bull_follow REAL, b_trend_follow REAL,
    prob REAL, done_ts INTEGER, first_id TEXT, n_calls INTEGER, hz TEXT, PRIMARY KEY (eid, horizon, rules_v));
CREATE INDEX IF NOT EXISTS outcomes_handle ON outcomes (handle);
CREATE TABLE IF NOT EXISTS register (handle TEXT, asset TEXT, ts INTEGER, event TEXT, eid TEXT, detail TEXT,
    rules_v TEXT);
CREATE INDEX IF NOT EXISTS register_handle ON register (handle, ts);
CREATE TABLE IF NOT EXISTS deletions (id TEXT PRIMARY KEY, handle TEXT, base_ts INTEGER, stage INTEGER DEFAULT 0,
    state TEXT, n_miss INTEGER DEFAULT 0, first_miss_ts INTEGER, last_check INTEGER, n_err INTEGER DEFAULT 0,
    detail TEXT);
CREATE TABLE IF NOT EXISTS scores (handle TEXT PRIMARY KEY, rules_v TEXT, ts INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS index_d (day INTEGER, asset TEXT, mode TEXT, kind TEXT, value REAL, coverage INTEGER,
    data TEXT, PRIMARY KEY (day, asset, mode, kind));
CREATE TABLE IF NOT EXISTS px (asset TEXT, res TEXT, ts INTEGER, close REAL, PRIMARY KEY (asset, res, ts));
CREATE TABLE IF NOT EXISTS px_meta (asset TEXT PRIMARY KEY, ts INTEGER, n INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS spend (ts INTEGER, day TEXT, src TEXT, phase TEXT, what TEXT, usd REAL);
CREATE INDEX IF NOT EXISTS spend_day ON spend (src, day);
CREATE TABLE IF NOT EXISTS quality (id TEXT PRIMARY KEY, stratum TEXT, category TEXT, ours TEXT, critic TEXT,
    agree_macro INTEGER, agree_dir INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS demo_block (ts INTEGER, token TEXT, symbol TEXT, price REAL, idx REAL, mode TEXT);
CREATE TABLE IF NOT EXISTS runs (ts INTEGER, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def config(cfg=None):
    """DEFAULT with makroinf/config.json on top (or the given dict)."""
    if cfg is None:
        try:
            with open(os.path.join(ROOT, "makroinf", "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    return {**DEFAULT, **(cfg or {})}


def db_path():
    if os.environ.get("MAKROINF_DB"):
        return os.environ["MAKROINF_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "makroinf.db")
    return os.path.join(ROOT, "makroinf.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    p = path or db_path()
    if not p or not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def kv(con, key, value=None):
    if value is None:
        r = q(con, "SELECT value FROM kv WHERE key = ?", (key,))
        return r[0][0] if r else None
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, value if isinstance(value, str) else json.dumps(value)))


def kv_json(con, key, default=None):
    v = kv(con, key)
    if v is None:
        return default
    try:
        return json.loads(v)
    except ValueError:
        return default


def day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(int(now)))


# ---------- spend ------------------------------------------------------------------------------------------------------

SRC_METER = {"twitterapi": ("twitterapi", "makroinf"), "openai": ("openai", "makroinf"),
             "openai_deep": ("openai", "makroinf_provjera"), "coingecko": ("coingecko", "makroinf")}


def book(con, src, usd, phase, what, now=None):
    """One paid call: spend row + usage meter (never raises on the meter)."""
    now = int(now or time.time())
    con.execute("INSERT INTO spend VALUES (?,?,?,?,?,?)", (now, day(now), src, phase, what, float(usd)))
    try:
        from usage import meter
        svc, method = SRC_METER.get(src, (src, "makroinf"))
        meter.record(svc, method, float(usd))
    except Exception:  # noqa: BLE001 - losing a count must not break the job
        pass


def spent(con, src, phase=None, day_=None):
    sql, args = "SELECT COALESCE(SUM(usd), 0) FROM spend WHERE src = ?", [src]
    if phase:
        sql += " AND phase = ?"
        args.append(phase)
    if day_:
        sql += " AND day = ?"
        args.append(day_)
    r = q(con, sql, tuple(args))
    return float(r[0][0]) if r else 0.0


def phase(con, kind):
    """The phase new spend of `kind` ("twapi" | "openai") belongs to: pilot until that part of the pilot is done,
    then dan; the expansion while its cap is open (expand_open)."""
    if kv(con, f"pilot_{kind}_done") is None:
        return "pilot"
    return "dan"


def left(con, kind, ph=None, now=None, c=None):
    """USD left under the cap of this phase (kind "twapi" | "openai"; ph defaults to phase())."""
    c = c or config()
    now = now or time.time()
    ph = ph or phase(con, kind)
    src = "twitterapi" if kind == "twapi" else "openai"
    if ph == "pilot":
        return max(0.0, float(c[f"pilot_{kind}_usd"]) - spent(con, src, "pilot"))
    if ph == "prosirenje":
        cap = float((kv_json(con, "prosirenje", {}) or {}).get(f"{kind}_usd") or c[f"expand_{kind}_usd"])
        return max(0.0, cap - spent(con, src, "prosirenje"))
    if ph == "provjera":
        return max(0.0, float(c["quality_openai_usd"]) - spent(con, "openai_deep", "provjera",
                                                               kv(con, "provjera_dan") or day(now)))
    # dan: everything of the UTC day after the pilot (the backfill rest, incremental, deletions, profiles)
    return max(0.0, float(c[f"day_{kind}_usd"]) - spent(con, src, "dan", day(now)))


def costs(con, now=None):
    """{src: {phase: usd}} plus today's numbers, for the card / the hourly line / MCP."""
    now = now or time.time()
    out = {}
    for src, ph, usd in q(con, "SELECT src, phase, SUM(usd) FROM spend GROUP BY src, phase"):
        out.setdefault(src, {})[ph] = round(float(usd), 4)
    today = {src: round(float(usd), 4) for src, usd in q(con, "SELECT src, SUM(usd) FROM spend WHERE day = ? GROUP BY src",
                                                         (day(now),))}
    return {"ukupno": out, "danas": today}
