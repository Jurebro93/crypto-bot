"""insajderi.db (INSAJDERI_DB, else next to the other databases; start.sh links it to the persistent disk), the
configuration and the Helius day cap.

Helius cap (15.11., vlasnik: "dio resursa za ovo, veći dio na midcapove"): helius_day credits a UTC day, counted
here (i2_kv "helius:<day>") on every page our own fetches pay for (wallets/rpc.fetch on_credits; the usage meter
counts the same calls under run_insajderi.py). When helius_day is not set, the cap is helius_share (16 %) of what the
old microcap jobs this tool replaces (kol.precall, kol.groupdisc, kol.preshill, run_wallets harvest / score) spent on
an average active day of the last 30 days in usage.db, clamped to [helius_min, helius_max]; helius_fallback without
any measurement (Pretpostavka: their caps in start.sh, 3000 + 3000 + 4000 + ~12000 a night, x 16 % ~ 3500).
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "insajderi2"
PREFIX = "insajderi2: "

DEFAULT = {
    # the event set
    "days": 30, "min_mcap": 30_000, "jump_x": 0.30, "jump_h": 6, "after_peak_s": 3600, "pre_days": 7,
    "late_call_h": 24, "mkt_days": 14, "mkt_x6": 0.50, "mkt_x24": 1.00, "max_mkt_tokens": 800,
    # Helius (the budget; pages of 100 transactions = 10 credits)
    "helius_day": None, "helius_share": 0.16, "helius_min": 1000, "helius_max": 6000, "helius_fallback": 3500,
    "deploy_share": 0.4, "sell_pages": 3, "pre_pages": 2, "lookups_per_event": 10, "acct_pages": 1,
    "max_events_pass": 300, "night_gap_h": 20,
    # who traded / scoring
    "min_sol": 0.05, "min_tokens": 3, "min_confirm": 1, "min_callers": 2, "min_lift": 2.0, "min_lead_min": 2,
    "sniper_secs": 60, "sniper_share": 0.5, "relayer_min": 5, "hub_min": 20, "bot_tx_min": 50,
    "busy_events_share": 0.6,
    # copyability
    "delay_s": 60, "slip_entry": 0.05, "slip_exit": 0.03, "stop": 0.25, "hold_h": 24, "size_usd": 15,
    "bond_mcap": 60_000, "warmup_days": 7, "supply": 1e9, "price_gap_s": 900, "sol_usd": 150.0,
    "sol_usd_hist": True,
    # the demo (flag insajderi2)
    "demo_sol": 0.1, "demo_max_open": 5, "demo_per_day": 10, "fresh_s": 300, "max_webhook": 10,
    # smart money / trending
    "smart_min_jumps": 2, "signal_min_clusters": 2, "signal_window_s": 3600, "cluster_gap_s": 300,
    "cluster_min_tokens": 2, "trend_h": 6, "trend_top": 20,
    "keep_days": 60,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS i2_events (eid TEXT PRIMARY KEY, kind TEXT, token TEXT, symbol TEXT, t0 INTEGER,
    handle TEXT, crew TEXT, n_callers INTEGER, callers TEXT, mcap0 REAL, peak_ts INTEGER, peak_x REAL,
    win_end INTEGER, catalyst TEXT, catalysts TEXT, src TEXT, prio REAL, fetched INTEGER DEFAULT 0,
    n_part INTEGER, built_ts INTEGER);
CREATE INDEX IF NOT EXISTS i2_events_t0 ON i2_events (t0);
CREATE INDEX IF NOT EXISTS i2_events_token ON i2_events (token, t0);
CREATE TABLE IF NOT EXISTS i2_trades (mint TEXT, wallet TEXT, sig TEXT, ts INTEGER, slot INTEGER, side TEXT, sol REAL,
    tokens REAL, payer TEXT, tacct TEXT, PRIMARY KEY (sig, wallet, mint));
CREATE INDEX IF NOT EXISTS i2_trades_mint ON i2_trades (mint, ts);
CREATE INDEX IF NOT EXISTS i2_trades_wallet ON i2_trades (wallet, ts);
CREATE TABLE IF NOT EXISTS i2_fetch (key TEXT PRIMARY KEY, ts INTEGER, credits INTEGER, n_tx INTEGER, complete INTEGER);
CREATE TABLE IF NOT EXISTS i2_part (eid TEXT, wallet TEXT, owner TEXT, buy_ts INTEGER, sol_in REAL, n_sells INTEGER,
    sol_out REAL, first_sell_ts INTEGER, bought_before INTEGER, sold_into INTEGER, lead_s INTEGER, src TEXT,
    PRIMARY KEY (eid, wallet));
CREATE INDEX IF NOT EXISTS i2_part_owner ON i2_part (owner);
CREATE TABLE IF NOT EXISTS i2_groups (owner TEXT PRIMARY KEY, members TEXT, n_members INTEGER, cls TEXT, why TEXT,
    n_hits INTEGER, n_early INTEGER, n_callers INTEGER, lift REAL, med_lead_min REAL, pnl_sol REAL, tokens TEXT,
    callers TEXT, crews TEXT, first_ts INTEGER, confirmed_ts INTEGER, score REAL, updated INTEGER);
CREATE TABLE IF NOT EXISTS i2_copy (owner TEXT, token TEXT, buy_ts INTEGER, entry_ts INTEGER, mcap REAL, bucket TEXT,
    bonded INTEGER, ret REAL, exit TEXT, call_after_s INTEGER, day TEXT, PRIMARY KEY (owner, token));
CREATE TABLE IF NOT EXISTS i2_trend (mint TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, last_ts INTEGER,
    best_rank INTEGER, src TEXT);
CREATE TABLE IF NOT EXISTS i2_smart (wallet TEXT PRIMARY KEY, owner TEXT, cluster TEXT, roles TEXT, score REAL,
    n_jumps INTEGER, n_calls INTEGER, holder_profit REAL, last_buy_ts INTEGER, last_token TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS i2_signals (token TEXT, ts INTEGER, n_clusters INTEGER, clusters TEXT, mcap REAL,
    ret REAL, exit TEXT, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS i2_demo (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT,
    owner TEXT, buy_ts INTEGER, opened_ts INTEGER, trade_id INTEGER, size_usd REAL, entry_mcap REAL, status TEXT,
    closed_ts INTEGER, pnl_usd REAL, ret REAL, exit_reason TEXT, UNIQUE (user, token));
CREATE TABLE IF NOT EXISTS i2_runs (ts INTEGER, kind TEXT, credits INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS i2_kv (key TEXT PRIMARY KEY, value TEXT);
"""
# scripts of the old microcap jobs whose Helius use the cap is a share of (usage.db usage.script = argv[0]'s name)
OLD_SCRIPTS = ("precall.py", "groupdisc.py", "preshill.py", "run_wallets.py")


def config(cfg=None):
    """DEFAULT with insajderi/config.json on top (or the given dict). Never below the scanner's 10k (CLAUDE.md)."""
    if cfg is None:
        try:
            with open(os.path.join(ROOT, "insajderi", "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    c = {**DEFAULT, **(cfg or {})}
    c["min_mcap"] = max(10_000.0, float(c["min_mcap"]))   # CLAUDE.md: measured in shadow from 10k at most; default 30k
    return c


def db_path():
    if os.environ.get("INSAJDERI_DB"):
        return os.environ["INSAJDERI_DB"]
    return os.path.join(ROOT, "insajderi.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=60)
    con.executescript(SCHEMA)
    return con


def ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
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
        r = q(con, "SELECT value FROM i2_kv WHERE key = ?", (key,))
        return r[0][0] if r else None
    con.execute("INSERT OR REPLACE INTO i2_kv VALUES (?, ?)", (key, str(value)))


def day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(int(now)))


def paths(**over):
    """Every database read here, by the owning modules' own rules (tests pass their own)."""
    from kol import groupdisc as gd
    p = gd.paths()
    extra = {"insajderi_db": db_path(),
             "midcap_db": None, "xfeat_db": None, "trade_db": None, "usage_db": None, "corr_db": None,
             "listing_db": os.environ.get("LISTING_DB") or os.path.join(ROOT, "listing.db")}
    try:
        from veliki import midcap
        extra["midcap_db"] = midcap.db_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        from scan import xmom
        extra["xfeat_db"] = xmom.db_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        from trade import settings
        extra["trade_db"] = settings.DB
    except Exception:  # noqa: BLE001
        pass
    try:
        from usage import meter
        extra["usage_db"] = meter.DB
    except Exception:  # noqa: BLE001
        pass
    try:
        from corr import store as cstore
        extra["corr_db"] = cstore.DB
    except Exception:  # noqa: BLE001
        pass
    p.update(extra)
    p.update({k: v for k, v in over.items() if v is not None})
    return p


# ---------- the Helius budget ------------------------------------------------------------------------------------------

def old_jobs_day(usage_db, now, days=30):
    """(average Helius credits on an active day of the old microcap jobs, active days) from usage.db, or (None, 0)."""
    con = ro(usage_db)
    rows = q(con, f"""SELECT hour / 86400, SUM(amount) FROM usage WHERE service = 'helius' AND hour >= ? AND
        script IN ({','.join('?' * len(OLD_SCRIPTS))}) GROUP BY hour / 86400 HAVING SUM(amount) > 0""",
             (int(now) - days * 86400, *OLD_SCRIPTS))
    if con is not None:
        con.close()
    if not rows:
        return None, 0
    return sum(r[1] for r in rows) / len(rows), len(rows)


def helius_cap(c, now, usage_db=None):
    """(credits a UTC day, how it was set in Croatian)."""
    if c.get("helius_day") not in (None, ""):
        return int(c["helius_day"]), "zadano (helius_day)"
    avg, n = old_jobs_day(usage_db, now)
    if avg is None:
        return int(c["helius_fallback"]), "bez mjerenja starih poslova (Pretpostavka: 16 % njihovih stropova)"
    cap = int(min(c["helius_max"], max(c["helius_min"], avg * float(c["helius_share"]))))
    return cap, f"{c['helius_share']:.0%} prosjeka starih poslova ({avg:,.0f} kr./dan, {n} dana)"


def helius_spent(con, now):
    return int(float(kv(con, f"helius:{day(now)}") or 0))


def helius_left(con, c, now, usage_db=None):
    cap, _how = helius_cap(c, now, usage_db)
    return max(0, cap - helius_spent(con, now))


def add_spent(con, now, n):
    if n > 0:
        k = f"helius:{day(now)}"
        kv(con, k, helius_spent(con, now) + int(n))
        con.commit()
