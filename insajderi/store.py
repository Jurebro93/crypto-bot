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
    "max_events_pass": 300, "night_gap_h": 20, "once_gap_h": 3, "incr_share": 0.1,
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
    # the influencers' probably linked wallets (insajderi/kolwallets.py, 16.11.): the window of his calls, the trades
    # around each (bought up to pre_days before, sold within kol_fast_s / kol_post_s after), its own small share of
    # the Helius day cap (kol_helius_share a day, kol_pass_credits a pass), the classes and the time bound of a pass
    "kol_days": 60, "kol_max_calls": 150, "kol_public_buys": True, "kol_fast_s": 3600, "kol_post_s": 86400,
    "kol_helius_share": 0.10, "kol_pass_credits": 1500, "kol_sell_pages": 2, "kol_pre_pages": 2, "kol_lookups": 5,
    "kol_helius_public_buys": False,   # Helius only for his posts; a public wallet's buys use the data we already hold
    "kol_fund_lookups": 10, "kol_max_s": 600, "kol_incr_s": 120, "kol_min_calls": 2, "kol_confirm_calls": 3,
    "kol_min_lift": 2.0, "kol_min_universe": 10, "kol_split_s": 21600, "kol_min_transfer_sol": 0.05, "kol_hops": 2,
    "kol_max_listed": 30, "kol_pred_days": 3, "kol_pred_call_days": 7,
    # the optional read of the seeded handles' posts from X (twitterapi.io): OFF while kol_x_usd_day is 0 (a new cost
    # is the owner's decision); on, at most that many USD a UTC day, kol_x_handles accounts a pass, each at most every
    # kol_x_every_h; an HTTP 402 is "nema kredita" and pauses it kol_x_pause_h
    "kol_x_usd_day": 0.0, "kol_x_handles": 6, "kol_x_every_h": 6, "kol_x_days": 7, "kol_x_pause_h": 6,
    # 19.11. (vlasnik: "svi resursi u pronalaženje novčanika koji kupuju PRIJE pumpe i prodaju u pumpu"; insajderi/
    # prijepumpe.py): the pump tiers by PEAK market cap of a market jump (focus_mcap 15M: "pumpa15", first priority;
    # pump2_mcap 2M: "pumpa2", second; then everything else), the class "kupuje prije pumpe" (bought before t0 AND sold
    # into the jump on >= pump_min_tokens distinct pump tokens, a PAID buy: sol_in >= min_sol), the market-maker
    # exclusion (>= mm_min_side buys AND sells of one token inside one window on >= mm_min_events windows), the copy
    # test (60 s as copy.py; "brzo" fast_delay_s 2 s, a print within fast_gap_s else their price x (1 + slip_fast),
    # an ASSUMPTION; stake pp_size_sol and pp_size_sol_big; the round trip never under veliki/replay.RT_FLOOR 3 %;
    # pp_min_n copies before a number is a finding; a 95 % bootstrap by token, boot_n draws), the random-wallet null
    # (null_k owners a day at least, seed null_seed) and the bundles (>= bundle_min_wallets wallets of one owner or one
    # fee payer buying in the same slot / second, or an owner group of 2+ wallets whose buys in [t0 - 1 h, t0 +
    # bundle_early_s] are >= bundle_share of the window's buy volume; listed from bundle_min_pumps pumps)
    "focus_mcap": 15_000_000, "pump2_mcap": 2_000_000, "pump_min_tokens": 3, "mm_min_side": 3, "mm_min_events": 2,
    "fast_delay_s": 2, "fast_gap_s": 5, "slip_fast": 0.01, "pp_size_sol": 0.1, "pp_size_sol_big": 0.5,
    "pp_min_n": 20, "boot_n": 2000, "null_k": 5, "null_seed": 19, "bundle_min_wallets": 3, "bundle_early_s": 3600,
    "bundle_share": 0.30, "bundle_min_pumps": 2,
    # 19.11. (the 18.11. problem: a pass held the heavy-job lock for hours): a wall-clock budget per pass; every long
    # stage asks the same Clock and stops cleanly (what was done is saved, the rest waits for the next pass). incr runs
    # the list and the bundles only when that stage took under incr_list_max_s on the last full pass
    "pass_max_s": {"once": 900, "incr": 420, "night": 5400}, "rest_time_share": 0.5, "pump_time_share": 0.65, "rest_credit_share": 1.0, "incr_list_max_s": 60,
    # 19.11. navečer (vlasnik: "zašto ne možeš provjeriti povijesne podatke, više tokena koji su pumpali i tko je kupio
    # prije, a prodao u pumpi?"): pumps also from the DAILY candles (pump_days_1d back: +mkt_x1d in a day or +mkt_x3d
    # within 3 days), the tiered events kept and scored over pump_days (the call events keep `days`), a deeper Helius
    # read of every tiered event spread over its windows (pump_* pages in slices: pump_slices_pre / pump_slices_jump;
    # pre window pump_pre_h before t0, 24 h for a 1h event, pump_pre_h_1d for a 1d one; at most pump_event_max_credits
    # an event), and a bounded one-time backfill budget (backfill until / helius_day, once 1800 s, incr_share 0.2)
    "pump_days": 180, "pump_days_1d": 180, "mkt_x1d": 0.50, "mkt_x3d": 1.00, "pump_sell_pages": 20,
    "pump_pre_pages": 20, "pump_lookups": 40, "pump_acct_pages": 2, "pump_event_max_credits": 2000,
    "pump_slices_pre": 10, "pump_slices_jump": 10, "pump_pre_h": 24, "pump_pre_h_1d": 72,
    # 19.11. navečer (2): the deep read's calls on pump_fetch_workers threads (1 = sequential), all of this process's
    # Helius calls under helius_rps requests a second (wallets/rpc.LIMIT)
    "pump_fetch_workers": 6, "helius_rps": 8,
    # 19.11. navečer (3): the list stage alone stops at its next step after list_max_s seconds (a hard guard: the pass
    # deadline is the other)
    "list_max_s": 600,
    # 19.11. navečer: Birdeye's top traders by realized PnL on the pump tokens (insajderi/birdeye.py; free plan 30,000
    # CU a month: 25,000 here, 30 CU a call, 0.7 calls a second, 3 pages of 10 a token, each token once in 14 days)
    "birdeye": {"cu_month": 25000, "cu_call": 30, "rps": 0.7, "pages": 3, "time_frame": "90d", "refresh_d": 14,
                "max_s": 120},
    "backfill": {"from": "2026-11-19", "until": "2026-11-25", "helius_day": 250000, "once_s": 1800, "incr_share": 0.2},
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
CREATE INDEX IF NOT EXISTS i2_part_wallet ON i2_part (wallet);
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
CREATE TABLE IF NOT EXISTS i2_runs (ts INTEGER, kind TEXT, credits INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS i2_kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS i2_cover (eid TEXT PRIMARY KEY, depth INTEGER, pre_s INTEGER, pre_cov REAL, jump_s INTEGER,
    jump_cov REAL, n_tx INTEGER, credits INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS i2_pp (owner TEXT PRIMARY KEY, members TEXT, n_members INTEGER, cls TEXT, why TEXT,
    n_pumps15 INTEGER, n_pumps2 INTEGER, n_tokens INTEGER, med_lead_min REAL, pnl_sol REAL, confirmed_ts INTEGER,
    last_seen INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS i2_pp_copy (variant TEXT, owner TEXT, token TEXT, buy_ts INTEGER, entry_ts INTEGER,
    mcap REAL, bucket TEXT, ret REAL, ret_big REAL, exit TEXT, miss TEXT, day TEXT,
    PRIMARY KEY (variant, owner, token));
CREATE TABLE IF NOT EXISTS i2_pp_hist (owner TEXT PRIMARY KEY, cls TEXT, confirmed INTEGER, n_members INTEGER,
    n_scored INTEGER, realized_sol REAL, profitable_share REAL, pump_pnl_sol REAL, agrees INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS i2_bundle (bid TEXT PRIMARY KEY, kind TEXT, members TEXT, n_members INTEGER,
    n_pumps INTEGER, n_pumps15 INTEGER, share_med REAL, sold_into INTEGER, tokens TEXT, last_seen INTEGER,
    updated INTEGER);
"""
# 19.11.: columns added to a table that already exists in production (connect() adds them when missing)
MIGRATIONS = (("i2_events", "tier", "TEXT"), ("i2_events", "peak_mc", "REAL"))
# 19.11. navečer: the deep, time-spread Helius read of a tiered event (chain.fetch_event_deep); FETCH_DEPTH is the
# version: an event whose i2_cover.depth is lower (or that has none: the old 3 + 2 pages from one end) is read again
FETCH_DEPTH = 2
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


class Clock:
    """The wall-clock budget of one pass (pass_max_s[kind]; None = unbounded) and the measured seconds per stage.
    fn: the clock (time.monotonic; tests pass a fake). over(): the budget is spent; cut(what): note what a stage left
    undone; stage(name): a context manager adding the stage's seconds to stages."""

    def __init__(self, kind, c, fn=None):
        self.fn = fn or time.monotonic
        self.t0 = self.fn()
        lim = (c.get("pass_max_s") or {})
        self.max_s = float(lim[kind]) if isinstance(lim, dict) and lim.get(kind) else None
        self.cuts, self.stages = [], {}
        self.sub = {}   # 19.11. navečer: the list stage's steps (seconds), run.analyze
        self.copy_sub = {}   # 19.11. navečer (2): the copy stage's walks ("pp", "ins")

    def elapsed(self):
        return self.fn() - self.t0

    def over(self):
        return self.max_s is not None and self.elapsed() >= self.max_s

    def left_s(self):
        return None if self.max_s is None else max(0.0, self.max_s - self.elapsed())

    def cut(self, what):
        if what not in self.cuts:
            self.cuts.append(what)

    def stage(self, name):
        clock = self

        class _S:
            def __enter__(self):
                self.t = clock.fn()

            def __exit__(self, *_a):
                clock.stages[name] = round(clock.stages.get(name, 0.0) + clock.fn() - self.t, 1)
                return False
        return _S()


MEM_LOG_MB = 300   # 20.11.: ops/health.py kills one process over 800 MB RSS; the pass says so well before (20.11. (2):
# from 300 MB, after every stage and step, so one pass in the log shows the whole profile)


def rss_mb():
    """The process's resident memory in MB (/proc/self/status VmRSS), None where it cannot be read."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def mem_line(step, limit=MEM_LOG_MB):
    """'insajderi2: memorija 512 MB nakon koraka <step>' when the RSS is `limit` MB or more, else None."""
    r = rss_mb()
    if r is None or r < limit:
        return None
    return f"{PREFIX}memorija {r} MB nakon koraka {step}"


def db_path():
    if os.environ.get("INSAJDERI_DB"):
        return os.environ["INSAJDERI_DB"]
    data = os.environ.get("DATA_DIR")   # the persistent disk (Render /var/data), as midcap.db / konsenzus.db
    if data and os.path.isdir(data):
        return os.path.join(data, "insajderi.db")
    return os.path.join(ROOT, "insajderi.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=60)
    con.executescript(SCHEMA)
    migrate(con)
    return con


def migrate(con):
    """ALTER TABLE ... ADD COLUMN for every MIGRATIONS column a table does not have yet (an existing insajderi.db: the
    new columns start NULL; events.mark_tiers fills tier / peak_mc on the next pass). Idempotent."""
    for table, col, typ in MIGRATIONS:
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    con.commit()


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
             "midcap_db": None, "veliki_db": None, "xfeat_db": None, "trade_db": None, "usage_db": None, "corr_db": None,
             "listing_db": os.environ.get("LISTING_DB") or os.path.join(ROOT, "listing.db"), "makroinf_db": None}
    try:
        from makroinf import store as mstore
        extra["makroinf_db"] = mstore.db_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        from veliki import midcap
        extra["midcap_db"] = midcap.db_path()
        from veliki import store as vstore   # 19.11. navečer: its daily candles (events.daily_events)
        extra["veliki_db"] = vstore.db_path()
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


def backfill_on(c, now):
    """19.11. navečer: True from backfill.from up to and including backfill.until (UTC days; the one-time history
    backfill)."""
    b = c.get("backfill") or {}
    return bool(b.get("until")) and str(b.get("from") or "") <= day(now) <= str(b["until"])


def backfill_label(c):
    """'punjenje povijesti do 25.11.' of backfill.until."""
    u = str((c.get("backfill") or {}).get("until") or "")
    return f"punjenje povijesti do {u[8:10]}.{u[5:7]}." if len(u) == 10 else "punjenje povijesti"


def effective(c, now):
    """The config of a pass at `now`: during the backfill pass_max_s once = backfill.once_s (1800) and incr_share =
    backfill.incr_share (0.2); after backfill.until the normal values."""
    if not backfill_on(c, now):
        return c
    b = c.get("backfill") or {}
    out = dict(c)
    out["pass_max_s"] = dict(c.get("pass_max_s") or {}, once=float(b.get("once_s") or 1800))
    out["incr_share"] = float(b.get("incr_share") or c["incr_share"])
    return out


def helius_cap(c, now, usage_db=None):
    """(credits a UTC day, how it was set in Croatian). 19.11. navečer: until backfill.until the backfill's own day cap
    (250k; worst case 5 days x 250k = 1.25M credits), then helius_day."""
    if backfill_on(c, now) and (c.get("backfill") or {}).get("helius_day"):
        return int(c["backfill"]["helius_day"]), backfill_label(c)
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
