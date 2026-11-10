"""scan.db: the market scanner's own file (one writer: run_scan.py once). The pages, the MCP tools and the report
only read it.

Tables:
  cand     one row per token the scanner looked at: where it came from (via), the newest check (stage, tradeable,
           passed, why, pass reasons, market numbers, fees / buyers / holders / top 10), when it first passed, and
           the lead time over the first caller signal (lead_time_min, minutes; negative = a caller was first)
  facts    holders, top 10 % and mint / freeze authority per token, cached FACTS_TTL_H (Helius or free tables)
  shadow   one row per (token, source, stage): the shadow entry when a candidate passed every filter, its observed
           price path and the outcome of the TP/SL shadow trade (shadow.py)
  metas    the active metas (top runners) of each 15-minute refresh with their narrative keywords
  beta     tokens that copy a runner's narrative (beta_score >= beta_min), with 1 h / 4 h / 24 h results of the token
           and of its parent
  profiles DexScreener profile descriptions (free), for the narrative keywords
  kv       day counters of the paid sources (helius:<day>, gt:<day>, xusd:<day>), last runs, the SOL price
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
FLAG = "market_scan"
SOURCES = ("caller", "wallet", "scan", "beta")
# 10.11. (ui/kandidati.py): the combined list as sources of their own, logged in the same shadow table by the pass:
# kandidati = a top-ranked tradeable candidate when it first ranks in the top kandidati_top_n; grok_override = a
# candidate our rug RISK rating would block, made tradeable by fresh Grok evidence (never a confirmed collapse)
COMBINED = ("kandidati", "grok_override")

# Every value here can be overridden in scan/config.json (the owner's file). Costs first (CLAUDE.md: before every new
# cost, measure what is used; the cheapest source first): DexScreener is free and does the pricing, GeckoTerminal goes
# through the paid CoinGecko day budget shared with the whole bot (CG_DAILY_CALLS 3000), so the scanner keeps its own
# small share; Helius only for tokens that passed every cheap filter; X only for passers and beta candidates.
DEFAULT = {
    "every_s": 150,
    # stage_filter: 10.11. (owner): tokens under 30k MAY be analysed; on the curve from final_stretch_min_mcap up, but
    # never tradeable: only a bonded token at or above trade_min_mcap (never under 30k, CLAUDE.md) can leave shadow
    "final_stretch_min_mcap": 10_000,
    "trade_min_mcap": 30_000,
    "migrated_min_vol_h1": 30_000,
    "recheck_min": 10,               # a token is checked again at most this often (per-token cache)
    "max_candidates": 120,           # new or expired candidates checked per pass, newest first
    "signal_window_min": 15,         # caller / wallet signals read per pass (since the last pass, at most this)
    "curve_pools": ["pump", "bonk", "launchlab", "moonshot"],              # PumpPortal pool names of a bonding curve
    # DexScreener dexId / GeckoTerminal dex id of a bonding curve (checked 10.11.: a pump.fun curve token is dexId
    # "pumpfun" without liquidity on DexScreener, dex "pump-fun" on GeckoTerminal); a Meteora pair labelled DBC too
    "curve_dex_ids": ["pumpfun", "pump-fun", "moonshot", "moonit", "launchlab", "raydium-launchlab", "letsbonk",
                      "letsbonk-fun", "meteora-dbc"],
    # costs
    "helius_credits_day": 5000,      # the scanner's own daily cap; the pass stops its Helius checks there
    "helius_holder_pages": 2,        # DAS getTokenAccounts pages (10 credits, 1000 holders each) for the holder count
    "helius_measure_share": 0.5,     # tokens that can never be bought get Helius only while the day used under this
    "facts_ttl_h": 6,
    "gt_calls_day": 150,             # GeckoTerminal / CoinGecko calls a day for discovery and runners
    "gt_every_min": 15,
    # one page per phase: [dex id, sort] (10.11.: pump-fun answers 0 pools to h24_volume_usd_desc, the tx count works)
    "gt_pages": {"final_stretch": ["pump-fun", "h24_tx_count_desc"], "migrated": ["pumpswap", "h24_volume_usd_desc"]},
    "x_usd_day": 0.30,               # twitterapi.io, the scanner's own share of the X spend
    "x_max_pages": 2,                # about 20 posts a page, $0.00015 a post
    "x_every_min": 15,
    "x_window_h": 2,                 # X is measured only while a passer is this young
    "x_per_pass": 4,
    "x_min_authors": 2,              # organic authors in the last 15 min for x_early
    # fees_filter / rug_check
    "fee_rates": {"curve": 0.0125, "pumpswap": 0.003, "other": 0.0025},
    "min_fees_sol": 0.5,
    "min_txns_h1": 50,
    "min_traders_h1": 20,            # unique buyers (GeckoTerminal) / traders (PumpPortal) in 1 h, when known
                                     # (10.11.: the top pump.fun curve pools had 400+ buys from 3 buyers)
    "max_wash": 50,
    "max_turnover_h1": 25,
    "min_holders": 50,
    "max_top10_pct": 60,
    # meta / beta
    "meta_every_min": 15,
    "runners": 20,
    "runner_min_mcap": 100_000,
    "beta_min": 0.6,
    # shadow trade and the paper gate
    "tp": 0.20, "sl": 0.30, "horizon_h": 4, "cost": 0.02, "max_gap_min": 30,
    "paper_min_outcomes": 30, "gate_days": 30,
    "show_min": 60,                  # get_market_signals: passers of the last hour
    # ui/kandidati.py: the combined candidate list is built and logged in shadow every kandidati_every_min (DexScreener
    # is free; no paid call), its top kandidati_top_n tradeable rows as source kandidati
    "kandidati_every_min": 5,
    "kandidati_top_n": 5,
}


def config(path=None):
    """DEFAULT with scan/config.json on top; trade_min_mcap never under 30k (CLAUDE.md: under 30k is never bought)."""
    cfg = dict(DEFAULT)
    try:
        with open(path or CONFIG, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
    except (OSError, ValueError):
        pass
    cfg["trade_min_mcap"] = max(30_000, float(cfg.get("trade_min_mcap") or 30_000))
    return cfg


def db_path():
    return os.environ.get("SCAN_DB") or os.path.join(ROOT, "scan.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS cand (
    token TEXT PRIMARY KEY, symbol TEXT, name TEXT, via TEXT, first_seen INTEGER, last_seen INTEGER,
    checked_ts INTEGER, stage TEXT, tradeable INTEGER, passed INTEGER, why TEXT, reasons TEXT,
    price REAL, mcap REAL, liq REAL, vol_h1 REAL, ch_h1 REAL, ch_h24 REAL,
    fees_paid_sol REAL, buy_share REAL, holders INTEGER, top10_pct REAL, wash REAL,
    first_pass_ts INTEGER, first_signal_ts INTEGER, first_signal_by TEXT, lead_time_min REAL,
    beta_checked INTEGER, beta_score REAL, beta_parent TEXT, x_ts INTEGER);
CREATE INDEX IF NOT EXISTS cand_pass ON cand (passed, first_pass_ts);
CREATE INDEX IF NOT EXISTS cand_seen ON cand (last_seen);
CREATE TABLE IF NOT EXISTS facts (
    token TEXT PRIMARY KEY, ts INTEGER, holders INTEGER, holders_capped INTEGER, top10_pct REAL, mint_auth TEXT,
    freeze_auth TEXT, src TEXT);
CREATE TABLE IF NOT EXISTS shadow (
    token TEXT, source TEXT, stage TEXT, found_ts INTEGER, tradeable INTEGER, symbol TEXT, entry REAL, mcap0 REAL,
    hi REAL, lo REAL, last REAL, last_ts INTEGER, n_obs INTEGER DEFAULT 0, max_gap_s INTEGER DEFAULT 0,
    t_tp INTEGER, t_sl INTEGER, hi1h REAL, hi4h REAL, r4h REAL, result REAL, exit_why TEXT, bad TEXT,
    done INTEGER DEFAULT 0, PRIMARY KEY (token, source, stage));
CREATE INDEX IF NOT EXISTS shadow_open ON shadow (done, found_ts);
CREATE TABLE IF NOT EXISTS metas (
    ts INTEGER, token TEXT, symbol TEXT, name TEXT, ch_h1 REAL, ch_h24 REAL, mcap REAL, price REAL, keywords TEXT,
    PRIMARY KEY (ts, token));
CREATE TABLE IF NOT EXISTS beta (
    token TEXT, parent TEXT, score REAL, found_ts INTEGER, via TEXT, symbol TEXT, parent_symbol TEXT, matched TEXT,
    p0 REAL, parent_p0 REAL, r1h REAL, r4h REAL, r24h REAL, parent_r1h REAL, parent_r4h REAL, parent_r24h REAL,
    done INTEGER DEFAULT 0, PRIMARY KEY (token, parent));
CREATE INDEX IF NOT EXISTS beta_found ON beta (found_ts);
CREATE TABLE IF NOT EXISTS profiles (token TEXT PRIMARY KEY, ts INTEGER, description TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""
KEEP_CAND_S, KEEP_META_S, KEEP_SHADOW_S, KEEP_BETA_S = 3 * 86400, 3 * 86400, 90 * 86400, 30 * 86400


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.execute("PRAGMA busy_timeout = 30000")
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("SELECT 1 FROM cand LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def kv_get(con, key, default=None):
    r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def kv_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, str(value)))


def day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def spent(con, what, now):
    """Today's (UTC) spend of one paid source: helius (credits), gt (calls), xusd (USD)."""
    try:
        return float(kv_get(con, f"{what}:{day(now)}", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def add_spent(con, what, amount, now):
    k = f"{what}:{day(now)}"
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = CAST(value AS REAL) + ?",
                (k, str(amount), amount))


def allowance(cap, now):
    """How much of a daily cap may be spent by now: the day is sliced by the hour (cap * (hours gone + 1) / 24), so
    a busy morning cannot use what the evening needs (the live feed's hourly slice, live/pumpportal.py)."""
    h = time.gmtime(now).tm_hour
    return float(cap) * min(1.0, (h + 1) / 24)


def budget_left(con, what, cap, now):
    """Units of `what` that may still be spent now (0 when the slice or the day's cap is used)."""
    return max(0.0, min(float(cap), allowance(cap, now)) - spent(con, what, now))


def prune(con, now):
    con.execute("DELETE FROM cand WHERE last_seen < ? AND (first_pass_ts IS NULL OR first_pass_ts < ?)",
                (now - KEEP_CAND_S, now - KEEP_CAND_S))
    con.execute("DELETE FROM metas WHERE ts < ?", (now - KEEP_META_S,))
    con.execute("DELETE FROM shadow WHERE found_ts < ?", (now - KEEP_SHADOW_S,))
    con.execute("DELETE FROM beta WHERE found_ts < ?", (now - KEEP_BETA_S,))
    con.execute("DELETE FROM profiles WHERE ts < ?", (now - KEEP_META_S,))
    con.execute("DELETE FROM facts WHERE ts < ?", (now - KEEP_META_S,))
    # the kv day counters stay: a few bytes a day, and they are the cost history per source (CLAUDE.md weekly report)


def on(path=None):
    """The owner's flag market_scan: anything but off runs the scanner (it only ever measures)."""
    try:
        from trade import settings
        return settings.flag(FLAG, path=path) != "off"
    except Exception:  # noqa: BLE001 - unreadable = off, the old behaviour
        return False


def mode(path=None):
    try:
        from trade import settings
        return settings.flag(FLAG, path=path)
    except Exception:  # noqa: BLE001
        return "off"
