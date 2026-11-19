"""bnb.db (BNB_DB, else $DATA_DIR/bnb.db like the other databases, else next to the code), the configuration
(DEFAULT + bnb/config.json) and the small helpers. One chain column on every table that could ever hold more than
one chain (chain = "bsc").

The tables mirror insajderi.db's (i2_events / i2_trades / i2_part / i2_pp / i2_cover) so the same summaries can be
produced; the trades are PARSED swaps (one row a Swap log, never the raw log), so a full fill stays small.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAIN = "bsc"
PREFIX = "bnb: "
# the version of a deep read (bnb_cover.depth): an event read below it is read again (as insajderi/store.FETCH_DEPTH)
FETCH_DEPTH = 2   # 19.11. 23:00: 2 = read on rpc-bsc.48.club (publicnode returned EMPTY logs past ~10 h, silently)

DEFAULT = {
    # the universe (the same band as Solana: 15-200 M first, 2-15 M second; CLAUDE.md: never under 30k)
    "min_mcap": 30_000, "max_mcap": 200_000_000, "min_liq": 25_000, "focus_mcap": 15_000_000,
    "pump2_mcap": 2_000_000, "max_tokens": 400,
    # discovery (free): GeckoTerminal pages and DexScreener queries
    "gt_volume_pages": 10, "gt_trend_pages": 3, "gt_dex_pages": 5,
    "gt_dexes": ["pancakeswap_v2", "pancakeswap-v3-bsc", "pancakeswap-infinity-clmm"], "ds_queries": ["bsc", "wbnb", "bnb meme", "pancakeswap", "four meme",
                                                             "binance", "cz", "usd1", "usdt bsc"],
    # candles: 180 daily, 45 days hourly (only for tokens whose daily candles moved >= hour_gate in a day or two)
    "days_1d": 180, "days_1h": 45, "hour_gate": 0.5,
    # the pump rules (insajderi/store.DEFAULT: the SAME numbers)
    "mkt_x6": 0.50, "mkt_x24": 1.00, "mkt_x1d": 0.50, "mkt_x3d": 1.00, "after_peak_s": 3600,
    "pump_pre_h": 24, "pump_pre_h_1d": 72,
    # who traded: the public RPC. rpc_logs: the logs (rpc-bsc.48.club: 5,000 blocks a call, real logs ~145 h back,
    # "header not found" past it); rpc_misc: heads, block times, eth_call, eth_getCode, receipts (publicnode: batch 200).
    # 19.11. 23:00: publicnode answers eth_getLogs older than ~10 h with an EMPTY list (no error) up to ~24 days, so it
    # is never used for logs (bnb/izvori.md)
    "rpc_logs": ["https://rpc-bsc.48.club"], "rpc_misc": ["https://bsc-rpc.publicnode.com"],
    "rpc_poll": ["https://rpc-bsc.48.club", "https://bsc.drpc.org"],
    "block_s": 0.45, "max_range": 5_000, "rpc_gap_s": 0.5, "archive_s": 132 * 3600,
    # the class (insajderi/prijepumpe.py: the same names and numbers); min_sol: 0.05 SOL at the SOL/USD of the day
    "min_sol": 0.05, "pump_min_tokens": 3, "min_confirm": 1, "min_lead_min": 2, "sniper_secs": 60,
    "sniper_share": 0.5, "busy_events_share": 0.6, "mm_min_side": 3, "mm_min_events": 2, "bot_tx_min": 50,
    "bot_events": 0.6,
    # the pass (production): wall clock and calls a UTC day; the backfill here has its own
    "pass_max_s": {"pass": 1500, "backfill": 36000, "track": 240}, "calls_day": 40_000, "gt_calls_pass": 120,
    "max_events_pass": 60, "db_max_mb": 400,
    # tracking and the measurement (league/mjera.py semantics)
    "track_max_addrs": 200, "track_chunk": 40, "track_blocks": 4000, "stop": 0.25, "hold_h": 24,
    "entry_wait_s": 600, "no_price_s": 6 * 3600, "stakes_usd": [50, 250], "rt_floor": 0.03, "gas_usd": 0.02,
    "fee_side_default": 0.0025,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS bnb_tokens (chain TEXT, token TEXT, symbol TEXT, name TEXT, pool TEXT, dex TEXT,
    quote TEXT, quote_sym TEXT, pool_created INTEGER, mcap REAL, fdv REAL, liq REAL, vol24 REAL, decimals INTEGER,
    qdecimals INTEGER, fee REAL, src TEXT, seen_ts INTEGER, candles_ts INTEGER, meme INTEGER, why_out TEXT,
    PRIMARY KEY (chain, token));
CREATE TABLE IF NOT EXISTS bnb_candles (chain TEXT, token TEXT, res TEXT, ts INTEGER, o REAL, h REAL, l REAL,
    c REAL, v REAL, PRIMARY KEY (chain, token, res, ts));
CREATE TABLE IF NOT EXISTS bnb_px (series TEXT, ts INTEGER, usd REAL, PRIMARY KEY (series, ts));
CREATE TABLE IF NOT EXISTS bnb_events (chain TEXT, eid TEXT PRIMARY KEY, kind TEXT, token TEXT, symbol TEXT,
    pool TEXT, t0 INTEGER, peak_ts INTEGER, peak_x REAL, win_end INTEGER, src TEXT, tier TEXT, peak_mc REAL,
    mcap0 REAL, prio REAL, fetched INTEGER DEFAULT 0, n_part INTEGER, reach TEXT, built_ts INTEGER);
CREATE INDEX IF NOT EXISTS bnb_events_token ON bnb_events (token, t0);
CREATE TABLE IF NOT EXISTS bnb_trades (chain TEXT, token TEXT, pool TEXT, tx TEXT, li INTEGER, block INTEGER,
    ts INTEGER, trader TEXT, side TEXT, amt REAL, quote TEXT, qamt REAL, usd REAL, sol_eq REAL, how TEXT,
    recip TEXT, PRIMARY KEY (tx, li));
CREATE INDEX IF NOT EXISTS bnb_trades_tok ON bnb_trades (token, ts);
CREATE INDEX IF NOT EXISTS bnb_trades_trader ON bnb_trades (trader, ts);
CREATE TABLE IF NOT EXISTS bnb_fetch (key TEXT PRIMARY KEY, ts INTEGER, n INTEGER, calls INTEGER, ok INTEGER);
CREATE TABLE IF NOT EXISTS bnb_cover (eid TEXT PRIMARY KEY, depth INTEGER, pre_s INTEGER, pre_cov REAL,
    jump_s INTEGER, jump_cov REAL, n_swaps INTEGER, calls INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS bnb_part (chain TEXT, eid TEXT, wallet TEXT, owner TEXT, buy_ts INTEGER, sol_in REAL,
    n_sells INTEGER, sol_out REAL, first_sell_ts INTEGER, bought_before INTEGER, sold_into INTEGER, lead_s INTEGER,
    usd_in REAL, usd_out REAL, PRIMARY KEY (eid, wallet));
CREATE INDEX IF NOT EXISTS bnb_part_wallet ON bnb_part (wallet);
CREATE TABLE IF NOT EXISTS bnb_pp (chain TEXT, owner TEXT, members TEXT, n_members INTEGER, cls TEXT, why TEXT,
    n_pumps15 INTEGER, n_pumps2 INTEGER, n_tokens INTEGER, med_lead_min REAL, pnl_sol REAL, pnl_usd REAL,
    pumps TEXT, confirmed_ts INTEGER, last_seen INTEGER, updated INTEGER, PRIMARY KEY (chain, owner));
CREATE TABLE IF NOT EXISTS bnb_code (addr TEXT PRIMARY KEY, kind TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS bnb_kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS bnb_runs (ts INTEGER, kind TEXT, secs REAL, calls TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS bnb_mjera (id INTEGER PRIMARY KEY AUTOINCREMENT, chain TEXT, source TEXT, gid TEXT,
    wallet TEXT, token TEXT, symbol TEXT, tx TEXT, their_buy_ts INTEGER, their_usd REAL, seen_ts INTEGER,
    delay_s INTEGER, entry_ts INTEGER, entry_price REAL, entry_mcap REAL, mc_bucket TEXT, liq REAL, guard TEXT,
    status TEXT, exit_ts INTEGER, exit_price REAL, exit_reason TEXT, ret_gross REAL, cost_50 REAL, cost_250 REAL,
    ret_net_50 REAL, ret_net_250 REAL, token_day TEXT, last_px_ts INTEGER, last_px REAL);
CREATE INDEX IF NOT EXISTS bnb_mjera_status ON bnb_mjera (status, last_px_ts);
"""


def config(cfg=None):
    """DEFAULT with bnb/config.json on top (or the given dict). min_mcap never under 30k (CLAUDE.md)."""
    if cfg is None:
        try:
            with open(os.path.join(ROOT, "bnb", "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    c = {**DEFAULT, **{k: v for k, v in (cfg or {}).items() if not k.startswith("_")}}
    c["min_mcap"] = max(30_000.0, float(c["min_mcap"]))
    return c


def on():
    """The environment switch BNB_ON (default 1): 0 turns the whole thing off."""
    return os.environ.get("BNB_ON", "1").strip() not in ("0", "false", "no", "off", "")


def db_path():
    if os.environ.get("BNB_DB"):
        return os.environ["BNB_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "bnb.db")
    return os.path.join(ROOT, "bnb.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
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
        r = q(con, "SELECT value FROM bnb_kv WHERE key = ?", (key,))
        return r[0][0] if r else None
    con.execute("INSERT OR REPLACE INTO bnb_kv VALUES (?, ?)", (key, str(value)))


def kv_json(con, key, value=None, default=None):
    if value is None:
        try:
            v = kv(con, key)
            return json.loads(v) if v else default
        except ValueError:
            return default
    kv(con, key, json.dumps(value, ensure_ascii=False))


def day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))


def size_mb(path=None):
    path = path or db_path()
    tot = 0
    for p in (path, path + "-wal"):
        try:
            tot += os.path.getsize(p)
        except OSError:
            pass
    return tot / 1e6


class Clock:
    """A wall-clock bound (seconds; None = unbounded). fn: the clock (tests pass a fake)."""

    def __init__(self, max_s, fn=None):
        self.fn = fn or time.monotonic
        self.t0 = self.fn()
        self.max_s = float(max_s) if max_s else None

    def elapsed(self):
        return self.fn() - self.t0

    def over(self):
        return self.max_s is not None and self.elapsed() >= self.max_s
