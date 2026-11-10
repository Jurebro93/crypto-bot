"""Insajderi prije poziva (10.11., Jure: "uhvati sve nove tokene i počni mjeriti one koji dođu do 10.000; uz Grok ih
očisti i nađi one koje calleri zovu rano; najvažnije: prepoznaj i koreliraj kupnje novčanika koji su kupili PRIJE
poziva; ako to prepoznamo na više tokena, možemo kopirati te novčanike"). Flag insider_copy (G14), default off.

1) Launches from 10k. run_live.py subscribes to every new pump.fun token by default (LIVE_NEW_TOKENS, free PumpPortal
   event -> hype.db live_launches). Here each launch is priced with DexScreener batch lookups (30 tokens a call,
   free but rate limited: at most dex_calls_pass a pass and dex_calls_day a day, counted in precall_kv and the usage
   meter) at +10 / +30 / +90 min after the launch (a check that came due while the pass slept is merged into the next
   one; a launch that is dead at a check - under launch_dead_usd with no volume - is not checked again). A launch that
   reaches launch_min_mcap (10k) gets reached_ts; the market scanner (scan/market.from_launches, flag market_scan)
   takes it as a candidate for promote_h hours: on the curve it is final_stretch, measured in shadow, never tradeable
   (nothing on the bonding curve or under 30k is ever bought: the copy loop's gates hold that for every copy).

2) Pre-call buyers. For every token called by a tracked caller (kol.db calls of kind 'call', X and Telegram, bot
   accounts out; the FIRST call of each caller) with the market cap at that call >= min_call_mcap (10k), or a captured
   launch that reached 10k before the call (market cap at the call unknown): the wallets that bought between the
   token's first trade (or the call - 6 h, whichever is later) and the call. Our own data first (early.db
   early_buyers / group_buys of smart_discovery and group_discovery, hype.db live_trades / chain_trades, kol.db
   insiders of kol/flows.py), Helius getTransactionsForAddress only for what is missing: the window before the FIRST
   call (newest first, pre_pages pages) and the hour after it (post_pages), once per mint (precall_fetched: a mint
   is never fetched twice), at most night_credits a pass (wallets/rpc.fetch, metered by usage/meter). A trade is
   attributed to the signer whose balance of the mint changed (kol/groupdisc.owner_trades), never to the fee payer:
   relayed / gasless swaps are paid by a relayer for many traders (10.11. Hope research).

   Per wallet across tokens: tokens bought before the first call (n_first), median minutes before the next call,
   which callers' calls it front-runs (wallet <-> caller pairs with their lift against chance, n_wh / (n_w * n_h / U)
   over the covered tokens, as kol/groupdisc does for caller pairs), share of those tokens that rose >= +30 % within
   1 h after the call it front-ran (minute.db hi60, else kol.db r1h / max24), whether it sold into that call (first
   sell within 60 min after) and its PnL on them. Out: relayers, bots (rate rules, wallets.db labels, chainwatch
   too_busy), snipers (kol/insiders.profile, or most buys within sniper_secs of the launch), dev-funded buys and
   same-owner bundles (kol/groupdisc._funders / owner_ids), and wallets the owner labelled bot / sniper. Out of sample
   by time: tokens first called in the older 2/3 of `days` select (n >= min_tokens before the first call, or before
   one caller's calls with lift >= min_lift), the newer 1/3 confirm (n >= min_confirm, rose30 not worse than
   min_rose30). Status: confirmed | candidate | watch | excluded.

   Stored: early.db precall_* (own tables); kol.db precall_links (caller <-> front-running wallets) and wallets.db
   precall_insiders (label 'precall_insider', SEPARATE table) are rewritten by the night pass. The tier / labels /
   scores in wallets.db `wallets` that the trading code reads (league/copy._wallet_tiers, signal_for,
   kol/chainwatch.own_wallets) are never written here.

3) Grok. MCP get_insider_candidates (read-only): wallets, stats, the callers they front-run, example tokens with
   times. Verdicts come back through submit_suggestion with proposed_change {"insider_label": {"wallet", "label":
   insider|team|bot|sniper|legit, "note"}}; only the owner's "Primijeni na bota" stores it (ui/assistnotes, trade.db
   settings insider_labels). bot / sniper keep a wallet out of copying.

4) Copy behind insider_copy: off - nothing runs (except the free launch capture in run_live); shadow - what would be
   copied goes to league.db shadow_decisions (league/flags.shadow); paper - the demo account PAPER_USER follows the
   top confirmed wallets (league/copy.follow, kind wallet, exit mirror: sells when they sell) within the copy loop's
   limits, the real Autopilot account only logs, and kol/chainwatch.wanted() adds them to the Helius webhook (only in
   paper / live: webhook events cost credits); live - also the Autopilot account, reachable only through
   trade/settings.live_refusal (backtest + 7 days of paper in the plus) AND live_refusal() here (>= live_min_closed
   closed paper copies of these wallets with EV > 0). Never automatic.

Passes: `python3 -m kol.precall incr` every 15 min (launch checks, fresh calls and their buyers from our databases
before live_trades is pruned at 48 h, the copy step; no Helius by default) and `python3 -m kol.precall night` (01-06
Zagreb under ops.heavy --night, at most once in night_gap_h: calls, Helius windows, the wallet analysis, the mirrors).
"""
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict

from kol import groupdisc as gd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "insider_copy"
LABELS = ("insider", "team", "bot", "sniper", "legit")
NO_COPY_LABELS = {"bot", "sniper"}
LABEL_SHAPE = {"insider_label": {"wallet": "<adresa>", "label": "insider|team|bot|sniper|legit", "note": "zašto"}}
STATUS_HR = {"confirmed": "potvrđen", "candidate": "kandidat", "watch": "promatra se", "excluded": "isključen"}
DUST_SOL = 0.001

DEFAULT = {
    # 1) launches from 10k
    "launch_checks_min": [10, 30, 90], "launch_min_mcap": 10_000, "launch_dead_usd": 5_000, "launch_dead_vol_h1": 300,
    "dex_calls_pass": 40, "dex_calls_day": 4000, "dex_gap_s": 0.5, "launch_keep_h": 24, "promote_h": 6,
    # 2) calls and windows
    "days": 30, "min_call_mcap": 10_000, "max_call_mcap": 50_000_000, "pre_window_s": 6 * 3600, "late_call_h": 24,
    "sold_window_s": 3600, "rose": 0.30, "min_sol": 0.05, "max_buyers": 300, "incr_days": 2,
    # Helius: the night pass only, unless --credits is given to incr
    "night_credits": 3000, "incr_credits": 0, "pre_pages": 2, "post_pages": 1, "night_gap_h": 20, "early_s": 1800,
    # wallet selection
    "min_tokens": 3, "min_confirm": 2, "min_link": 2, "min_lift": 2.0, "min_rose30": 0.5, "sniper_secs": 60,
    "sniper_share": 0.5, "relayer_min": 5, "bot_tx_min": 50, "hub_min": 20, "dev_share": 0.5, "max_watch": 5000,
    # copy (flag insider_copy)
    "max_follows": 5, "size_usd": 25, "per_day": 3, "max_webhook": 20,
    # paper -> live proof
    "live_min_closed": 20,
    "keep_days": 45,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS precall_launch (mint TEXT PRIMARY KEY, launch_ts INTEGER, symbol TEXT, creator TEXT,
    checks INTEGER DEFAULT 0, last_check_ts INTEGER, mcap_last REAL, mcap_max REAL, reached_ts INTEGER,
    mcap_reach REAL, curve INTEGER, dead INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS precall_launch_ts ON precall_launch (launch_ts);
CREATE INDEX IF NOT EXISTS precall_launch_reached ON precall_launch (reached_ts);
CREATE TABLE IF NOT EXISTS precall_calls (token TEXT, handle TEXT, call_ts INTEGER, mcap0 REAL, rose30 INTEGER,
    PRIMARY KEY (token, handle));
CREATE TABLE IF NOT EXISTS precall_tokens (token TEXT PRIMARY KEY, t0 INTEGER, first_handle TEXT, n_callers INTEGER,
    last_call_ts INTEGER, first_trade_ts INTEGER, window_start INTEGER, mcap0 REAL, rose30 INTEGER, dev TEXT,
    launch_ts INTEGER, buyers INTEGER, built_ts INTEGER);
CREATE INDEX IF NOT EXISTS precall_tokens_t0 ON precall_tokens (t0);
CREATE TABLE IF NOT EXISTS precall_trades (mint TEXT, wallet TEXT, sig TEXT, ts INTEGER, slot INTEGER, side TEXT,
    sol REAL, tokens REAL, payer TEXT, PRIMARY KEY (sig, wallet, mint));
CREATE INDEX IF NOT EXISTS precall_trades_mint ON precall_trades (mint, ts);
CREATE TABLE IF NOT EXISTS precall_fetched (mint TEXT PRIMARY KEY, ts INTEGER, credits INTEGER, n_tx INTEGER,
    since_ts INTEGER, until_ts INTEGER, oldest_ts INTEGER, complete INTEGER);
CREATE TABLE IF NOT EXISTS precall_buys (token TEXT, wallet TEXT, buy_ts INTEGER, sol_in REAL, sold_ts INTEGER,
    sol_out REAL, payer TEXT, src TEXT, PRIMARY KEY (token, wallet));
CREATE INDEX IF NOT EXISTS precall_buys_wallet ON precall_buys (wallet);
CREATE TABLE IF NOT EXISTS precall_wallets (wallet TEXT PRIMARY KEY, status TEXT, why TEXT, score REAL,
    n_tokens INTEGER, n_first INTEGER, n_sel INTEGER, n_conf INTEGER, med_min REAL, rose30 REAL, sold_into REAL,
    pnl_sol REAL, stats TEXT, first_seen INTEGER, status_ts INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS precall_links (wallet TEXT, handle TEXT, n INTEGER, expected REAL, lift REAL, med_min REAL,
    PRIMARY KEY (wallet, handle));
CREATE TABLE IF NOT EXISTS precall_follows (follow_id INTEGER PRIMARY KEY, user TEXT, wallet TEXT, created INTEGER,
    stopped INTEGER);
CREATE TABLE IF NOT EXISTS precall_seen (wallet TEXT, token TEXT, ts INTEGER, PRIMARY KEY (wallet, token));
CREATE TABLE IF NOT EXISTS precall_runs (ts INTEGER, kind TEXT, credits INTEGER, dex_calls INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS precall_kv (key TEXT PRIMARY KEY, value TEXT);
"""
KOL_SCHEMA = """CREATE TABLE IF NOT EXISTS precall_links (handle TEXT, wallet TEXT, n INTEGER, lift REAL, med_min REAL,
    status TEXT, updated INTEGER, PRIMARY KEY (handle, wallet))"""
WALLET_SCHEMA = """CREATE TABLE IF NOT EXISTS precall_insiders (wallet TEXT PRIMARY KEY, label TEXT, status TEXT,
    why TEXT, n_tokens INTEGER, n_first INTEGER, med_min REAL, rose30 REAL, sold_into REAL, pnl_sol REAL,
    callers TEXT, owner_label TEXT, updated INTEGER)"""


# ===================================================================================================================
# basics
# ===================================================================================================================
def config(cfg=None):
    """DEFAULT with kol/config.json "insider_copy" on top (or the given cfg's section)."""
    if cfg is None:
        try:
            with open(os.path.join(ROOT, "kol", "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
    c = {**DEFAULT, **((cfg or {}).get(FLAG) or {})}
    c["launch_min_mcap"] = max(10_000, float(c["launch_min_mcap"]))   # owner: measured from 10k, never lower
    c["min_call_mcap"] = max(10_000, float(c["min_call_mcap"]))
    return c


def paths(**over):
    p = gd.paths(**{k: v for k, v in over.items() if k != "trade_db"})
    try:
        from trade import settings
        p["trade_db"] = settings.DB
    except Exception:  # noqa: BLE001
        p["trade_db"] = None
    if over.get("trade_db"):
        p["trade_db"] = over["trade_db"]
    return p


def connect(path=None):
    con = sqlite3.connect(path or gd.db_path(), timeout=60)
    con.executescript(SCHEMA)
    return con


_ro, _q, _med, _r = gd._ro, gd._q, gd._med, gd._r


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def mode(trade_db=None):
    """The flag's mode; "off" when trade settings cannot be read (the safe side)."""
    try:
        from trade import settings
        return settings.flag(FLAG, path=trade_db)
    except Exception:  # noqa: BLE001
        return "off"


def kv(con, key, value=None):
    if value is None:
        r = _q(con, "SELECT value FROM precall_kv WHERE key = ?", (key,))
        return r[0][0] if r else None
    con.execute("INSERT OR REPLACE INTO precall_kv VALUES (?, ?)", (key, str(value)))


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _in(xs):
    return ",".join("?" * len(xs))


# ===================================================================================================================
# 1) launches from 10k
# ===================================================================================================================
def _curve_ids():
    try:
        from scan import store as sstore
        return set(sstore.DEFAULT["curve_dex_ids"])
    except Exception:  # noqa: BLE001
        return {"pumpfun", "pump-fun"}


def dex_rows(pairs):
    """DexScreener pairs -> {mint: {"mcap", "vol_h1", "curve", "symbol"}}: the biggest market cap among a mint's pairs."""
    curve = _curve_ids()
    out = {}
    for p in pairs or []:
        if not isinstance(p, dict) or p.get("chainId") not in (None, "solana"):
            continue
        t = (p.get("baseToken") or {}).get("address")
        if not t:
            continue
        mc = _f(p.get("marketCap")) or _f(p.get("fdv"))
        row = {"mcap": mc, "vol_h1": _f((p.get("volume") or {}).get("h1")) or 0.0,
               "curve": (p.get("dexId") or "") in curve, "symbol": (p.get("baseToken") or {}).get("symbol")}
        cur = out.get(t)
        if cur is None or (mc or 0) > (cur["mcap"] or 0):
            out[t] = row
    return out


def _dex_default(tokens):
    from dexscreener import client
    return client.tokens("solana", list(tokens))


def dex_left(con, c, now):
    """DexScreener calls this module may still make today (UTC)."""
    used = int(float(kv(con, f"dex:{_day(now)}") or 0))
    return max(0, int(c["dex_calls_day"]) - used)


def _dex_spent(con, n, now):
    if n <= 0:
        return
    k = f"dex:{_day(now)}"
    kv(con, k, int(float(kv(con, k) or 0)) + n)
    try:
        from usage import meter
        meter.record("dexscreener", "insajderi-lansiranja", 0.0, calls=n)
    except Exception:  # noqa: BLE001
        pass


def due_checks(rows, offs, now):
    """rows [(mint, launch_ts, checks)] -> [(mint, k)]: k = the latest check (index into offs) that is due and not done.
    A check that came due while the pass slept is merged into the later one (one DexScreener look, not two)."""
    out = []
    for mint, lts, checks in rows:
        age = now - (lts or now)
        due = [i for i, o in enumerate(offs) if age >= o]
        if due and due[-1] >= (checks or 0):
            out.append((mint, due[-1]))
    return out


def measure_launches(con, p, c, now, dex=None, log=print):
    """Read new launches from hype.db, price the due ones with DexScreener (capped), mark the ones at 10k.
    Returns {"new", "checked", "reached", "dex_calls", "dead"}."""
    offs = sorted(int(x) * 60 for x in c["launch_checks_min"])
    out = {"new": 0, "checked": 0, "reached": 0, "dex_calls": 0, "dead": 0}
    hc = _ro(p["hype_db"])
    since = max(int(float(kv(con, "launch_seen_ts") or 0)) - 120, now - offs[-1] - 3600)
    rows = _q(hc, "SELECT mint, ts, symbol, creator FROM live_launches WHERE pool != 'migration' AND ts > ? AND ts <= ?",
              (since, now))
    if hc is not None:
        hc.close()
    for r in rows:
        out["new"] += con.execute("INSERT OR IGNORE INTO precall_launch (mint, launch_ts, symbol, creator) VALUES "
                                  "(?,?,?,?)", r).rowcount
    kv(con, "launch_seen_ts", now)
    pending = _q(con, "SELECT mint, launch_ts, checks FROM precall_launch WHERE reached_ts IS NULL AND dead = 0 AND "
                      "checks < ? AND launch_ts <= ? AND launch_ts >= ?", (len(offs), now - offs[0], now - offs[-1] - 7200))
    due = due_checks(pending, offs, now)
    due.sort(key=lambda x: (x[1], x[0]))   # the first check first: a fast mover is seen early
    cap = min(int(c["dex_calls_pass"]), dex_left(con, c, now)) * 30
    due = due[:cap]
    if not due:
        con.commit()
        return out
    gap = float(c["dex_gap_s"]) if dex is None else 0.0   # the 300/min limit is per IP, shared with every process
    dex = dex or _dex_default
    k_of = dict(due)
    mints = [m for m, _k in due]
    got = {}
    for i, ch in enumerate(_chunks(mints, 30)):
        if i and gap:
            time.sleep(gap)
        try:
            pairs = dex(ch)
        except Exception as e:  # noqa: BLE001 - DexScreener down: the rest waits for the next pass
            log(f"insajderi: DexScreener {type(e).__name__}: {str(e)[:80]}")
            break
        out["dex_calls"] += 1
        _dex_spent(con, 1, now)
        rows = dex_rows(pairs)
        got.update({m: rows.get(m) for m in ch})
    floor, dead_usd, dead_vol = float(c["launch_min_mcap"]), float(c["launch_dead_usd"]), float(c["launch_dead_vol_h1"])
    for m, r in got.items():
        mc = (r or {}).get("mcap")
        reached = mc is not None and mc >= floor
        dead = int(bool(r) and mc is not None and mc < dead_usd and (r.get("vol_h1") or 0) < dead_vol)
        con.execute("""UPDATE precall_launch SET checks = ?, last_check_ts = ?, mcap_last = ?,
            mcap_max = MAX(COALESCE(mcap_max, 0), COALESCE(?, 0)), reached_ts = CASE WHEN ? THEN ? ELSE reached_ts END,
            mcap_reach = CASE WHEN ? THEN ? ELSE mcap_reach END, curve = ?, dead = ?,
            symbol = COALESCE(symbol, ?) WHERE mint = ?""",
                    (k_of[m] + 1, now, mc, mc, int(reached), now, int(reached), mc,
                     None if not r else int(bool(r.get("curve"))), dead, (r or {}).get("symbol"), m))
        out["checked"] += 1
        out["reached"] += int(reached)
        out["dead"] += dead
    con.commit()
    return out


def reached(now=None, hours=None, path=None, trade_db=None):
    """[(mint, symbol)] of launches that reached 10k in the last promote_h hours, for the market scanner
    (scan/market.from_launches). [] when the flag is off or nothing was measured. Read-only."""
    if mode(trade_db) == "off":
        return []
    now = int(now or time.time())
    h = float(hours if hours is not None else config()["promote_h"])
    ec = _ro(path or gd.db_path())
    rows = _q(ec, "SELECT mint, symbol FROM precall_launch WHERE reached_ts >= ? ORDER BY reached_ts DESC LIMIT 200",
              (int(now - h * 3600),))
    if ec is not None:
        ec.close()
    return rows


# ===================================================================================================================
# 2) calls, windows, buyers
# ===================================================================================================================
def _rose30(hi60, r1h, max24, rose):
    """1 when the price rose >= rose within 1 h of the call, 0 when it did not, None when unknown."""
    if hi60 is not None:
        return int(hi60 >= rose)
    if r1h is not None and r1h >= rose:
        return 1
    if max24 is not None and max24 < rose:
        return 0
    return None


def collect_calls(con, p, c, now, since=None):
    """kol.db calls -> precall_calls (first call of each qualifying caller per token) and precall_tokens, for the tokens
    with a call since `since` (default: the last `days`), a few hundred tokens at a time (memory stays small).
    Returns the number of tokens written."""
    kc = _ro(p["kol_db"])
    if kc is None:
        return 0
    try:
        from kol import store as kstore
        bots = set(kstore.bot_handles(p["kol_db"]))
    except Exception:  # noqa: BLE001
        bots = set()
    since = int(since if since is not None else now - c["days"] * 86400)
    toks = [t for (t,) in _q(kc, "SELECT DISTINCT token FROM calls WHERE kind = 'call' AND ts >= ? AND ts <= ?",
                             (since, now)) if len(t or "") >= 32]
    mc, hc = _ro(p.get("minute_db")), _ro(p["hype_db"])
    n = 0
    try:
        for ch in _chunks(toks, 300):
            n += _collect_chunk(con, kc, mc, hc, ch, bots, c)
            con.commit()
    finally:
        for x in (kc, mc, hc):
            if x is not None:
                x.close()
    return n


def _collect_chunk(con, kc, mc, hc, toks, bots, c):
    q = _in(toks)
    rows = [r for r in _q(kc, f"""SELECT token, handle, MIN(ts), mcap0, tweet_id, r1h, max24 FROM calls WHERE
        kind = 'call' AND handle NOT LIKE 'w:%' AND token IN ({q}) GROUP BY token, handle""", toks) if r[1] not in bots]
    if not rows:
        return 0
    created = dict(_q(kc, f"SELECT token, created_ts FROM tokens WHERE created_ts > 0 AND token IN ({q})", toks))
    by = defaultdict(list)
    for r in rows:
        by[r[0]].append(r)
    hi60 = {}
    tids = [r[4] for r in rows if r[4]]
    for ch in _chunks(tids):
        hi60.update({(t, k): h for t, k, h in _q(mc, f"SELECT tweet_id, token, hi60 FROM call_path WHERE hi60 IS NOT "
                                                    f"NULL AND tweet_id IN ({_in(ch)})", ch)})
    launch, dev = {}, {}
    for m, lts, cr, rts in _q(con, f"SELECT mint, launch_ts, creator, reached_ts FROM precall_launch WHERE mint IN ({q})",
                              toks):
        launch[m] = (lts, rts)
        if cr:
            dev[m] = cr
    for m, ft, d in _q(con, f"SELECT mint, first_ts, dev FROM group_fetched WHERE mint IN ({q})", toks):
        if ft:
            created[m] = min(x for x in (created.get(m), ft) if x)
        if d and m not in dev:
            dev[m] = d
    for m, ft in _q(con, f"SELECT mint, MIN(first_buy_ts) FROM early_buyers WHERE mint IN ({q}) GROUP BY mint", toks):
        if ft:
            created[m] = min(x for x in (created.get(m), ft) if x)
    for m, ts, cr in _q(hc, f"SELECT mint, ts, creator FROM live_launches WHERE pool != 'migration' AND mint IN ({q})",
                        toks):
        launch.setdefault(m, (ts, None))
        if cr and m not in dev:
            dev[m] = cr
    n = 0
    lo, hi, rose = float(c["min_call_mcap"]), float(c["max_call_mcap"]), float(c["rose"])
    for tok, calls in by.items():
        t0 = min(r[2] for r in calls)
        lts, rts = launch.get(tok, (None, None))
        ok = []
        for t, h, ts, mc0, tid, r1h, mx in calls:
            if ts - t0 > c["late_call_h"] * 3600:
                continue
            good = (mc0 is not None and lo <= mc0 <= hi) or (mc0 is None and rts is not None and rts <= ts)
            if good:
                ok.append((h, ts, mc0, _rose30(hi60.get((tid, t)), r1h, mx, rose)))
        if not ok:
            continue
        ft = [x for x in (created.get(tok), lts) if x]
        first_trade = min(ft) if ft else None
        ws = max(first_trade or 0, t0 - int(c["pre_window_s"]))
        ok.sort(key=lambda x: x[1])
        con.executemany("INSERT OR REPLACE INTO precall_calls VALUES (?,?,?,?,?)", [(tok, h, ts, m0, r) for h, ts, m0, r in ok])
        con.execute("""INSERT INTO precall_tokens (token, t0, first_handle, n_callers, last_call_ts, first_trade_ts,
            window_start, mcap0, rose30, dev, launch_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET
            t0 = excluded.t0, first_handle = excluded.first_handle, n_callers = excluded.n_callers,
            last_call_ts = excluded.last_call_ts, first_trade_ts = excluded.first_trade_ts,
            window_start = excluded.window_start, mcap0 = excluded.mcap0, rose30 = excluded.rose30,
            dev = COALESCE(excluded.dev, dev), launch_ts = COALESCE(excluded.launch_ts, launch_ts)""",
                    (tok, t0, min(calls, key=lambda r: r[2])[1], len(ok), ok[-1][1], first_trade, ws, ok[0][2], ok[0][3],
                     dev.get(tok), lts))
        n += 1
    return n


def aggregate(trades, ws, t_end, c):
    """trades: (wallet, ts, side, sol, payer, src) of one token -> {wallet: [buy_ts, sol_in, sold_ts, sol_out, payer,
    srcs]}: the first buy in [ws, t_end) (t_end: the last qualifying call), the SOL of those buys, the first sell after
    that buy (within 24 h of t_end) and the SOL of the sells. Wallets whose known SOL is under min_sol are dust."""
    out = {}
    trades = sorted(trades, key=lambda x: x[1] or 0)
    for w, ts, side, sol, payer, src in trades:
        if not w or ts is None or side != "buy" or not ws <= ts < t_end:
            continue
        o = out.get(w)
        if o is None:
            o = out[w] = [int(ts), 0.0, None, None, payer, set(), False]
        if sol is not None:
            o[1] += abs(sol)
            o[6] = True
        o[5].add(src)
        if payer and not o[4]:
            o[4] = payer
    for w, ts, side, sol, _payer, src in trades:
        o = out.get(w)
        if o is None or side != "sell" or ts is None or ts < o[0] or ts > t_end + 86400:
            continue
        if o[2] is None:
            o[2] = int(ts)
            o[3] = 0.0
        if sol is not None:
            o[3] += abs(sol)
        o[5].add(src)
    res = {}
    for w, (bts, sin, sts, sout, payer, srcs, known) in out.items():
        if known and sin < c["min_sol"]:
            continue
        res[w] = [bts, round(sin, 6) if known else None, sts, None if sout is None else round(sout, 6), payer,
                  ",".join(sorted(srcs))]
    if len(res) > c["max_buyers"]:   # the biggest buyers first (unknown SOL last), then the earliest
        keep = sorted(res, key=lambda w: (-(res[w][1] or -1), res[w][0]))[:int(c["max_buyers"])]
        res = {w: res[w] for w in keep}
    return res


def _sources(con, p, toks):
    """{token: [(wallet, ts, side, sol, payer, src)]} from every free source we have for `toks`."""
    by = defaultdict(list)
    for ch in _chunks(toks):
        q = _in(ch)
        for m, w, ts, side, sol, payer in _q(con, f"SELECT mint, wallet, ts, side, sol, payer FROM precall_trades WHERE "
                                                 f"mint IN ({q})", ch):
            by[m].append((w, ts, side, sol, payer, "helius"))
        for m, w, ts, side, sol, payer in _q(con, f"SELECT mint, wallet, ts, side, sol, payer FROM group_buys WHERE "
                                                 f"mint IN ({q})", ch):
            by[m].append((w, ts, side, sol, payer, "grupe"))
        for m, w, ts, sin, sts, sout in _q(con, f"SELECT mint, wallet, first_buy_ts, sol_in, sold_ts, sol_out FROM "
                                               f"early_buyers WHERE mint IN ({q})", ch):
            by[m].append((w, ts, "buy", sin, None, "rani"))
            if sts:
                by[m].append((w, sts, "sell", sout, None, "rani"))
    hc = _ro(p["hype_db"])
    if hc is not None:
        for ch in _chunks(toks):
            q = _in(ch)
            for m, w, ts, side, sol in _q(hc, f"SELECT mint, wallet, ts, side, sol FROM live_trades WHERE mint IN ({q})", ch):
                by[m].append((w, ts, side, sol, None, "pumpportal"))
            for m, w, ts, side, sol in _q(hc, f"SELECT mint, wallet, ts, side, sol FROM chain_trades WHERE mint IN ({q})", ch):
                by[m].append((w, ts, side, sol, None, "webhook"))
        hc.close()
    kc = _ro(p["kol_db"])
    if kc is not None:   # kol/flows.py insiders (before 10.11. the fee payer: relayers are dropped in the analysis)
        for ch in _chunks(toks):
            for w, m, bts, sts, sin, sout in _q(kc, f"SELECT wallet, token, bought_ts, sold_ts, sol_in, sol_out FROM "
                                                    f"insiders WHERE token IN ({_in(ch)})", ch):
                if bts:
                    by[m].append((w, bts, "buy", sin, None, "flows"))
                if sts:
                    by[m].append((w, sts, "sell", sout, None, "flows"))
        kc.close()
    return by


def build_buys(con, p, c, now, tokens=None):
    """precall_buys of `tokens` (default: every token of the last `days` not built since its last call) from the free
    sources; merged with what is already stored (live_trades is pruned at 48 h, so an earlier look stays). Returns
    the number of tokens built."""
    if tokens is None:   # never built, built before the hour after its last call was over, or called in the last 2 days
        rows = _q(con, "SELECT token, window_start, last_call_ts FROM precall_tokens WHERE t0 >= ? AND "
                       "(built_ts IS NULL OR built_ts < last_call_ts + ? OR t0 >= ?)",
                  (now - c["days"] * 86400, int(c["sold_window_s"]) + 3600, now - 2 * 86400))
    else:
        rows = []
        for ch in _chunks(tokens):
            rows += _q(con, f"SELECT token, window_start, last_call_ts FROM precall_tokens WHERE token IN ({_in(ch)})", ch)
    n = 0
    for ch in _chunks(rows, 100):
        src = _sources(con, p, [r[0] for r in ch])
        for tok, ws, t_end in ch:
            agg = aggregate(src.get(tok) or [], ws or 0, (t_end or 0) + 1, c)
            con.executemany("""INSERT INTO precall_buys VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(token, wallet) DO UPDATE SET
                buy_ts = MIN(buy_ts, excluded.buy_ts), sol_in = MAX(COALESCE(sol_in, 0), COALESCE(excluded.sol_in, 0)),
                sold_ts = CASE WHEN sold_ts IS NULL THEN excluded.sold_ts WHEN excluded.sold_ts IS NULL THEN sold_ts
                               ELSE MIN(sold_ts, excluded.sold_ts) END,
                sol_out = MAX(COALESCE(sol_out, 0), COALESCE(excluded.sol_out, 0)),
                payer = COALESCE(payer, excluded.payer), src = excluded.src""",
                            [(tok, w, *v) for w, v in agg.items()])
            nb = con.execute("SELECT COUNT(*) FROM precall_buys WHERE token = ?", (tok,)).fetchone()[0]
            con.execute("UPDATE precall_tokens SET buyers = ?, built_ts = ? WHERE token = ?", (nb, now, tok))
            n += 1
        con.commit()
    return n


def fetch_candidates(con, c, now):
    """[(token, since, t0)] worth one Helius read: called in the last `days`, the first call at least an hour old (so
    the hour after it exists), never fetched, and the window before the first call not covered by our own data
    (group_discovery's first 30 min, PumpPortal trades from the window's start). Most callers first, newest first."""
    rows = _q(con, """SELECT t.token, t.window_start, t.t0, t.n_callers FROM precall_tokens t LEFT JOIN precall_fetched f
        ON f.mint = t.token WHERE f.mint IS NULL AND t.t0 >= ? AND t.t0 <= ? ORDER BY t.n_callers DESC, t.t0 DESC""",
              (now - c["days"] * 86400, now - int(c["sold_window_s"])))
    out = []
    for ch in _chunks(rows):
        toks = [r[0] for r in ch]
        gf = dict(_q(con, f"SELECT mint, first_ts FROM group_fetched WHERE mint IN ({_in(toks)})", toks))
        for tok, ws, t0, _n in ch:
            since = ws or t0 - int(c["pre_window_s"])
            if gf.get(tok):
                since = max(since, gf[tok] + int(c["early_s"]))
            if since < t0:
                out.append((tok, since, t0))
    return out


def fetch_windows(con, c, now, budget, fetch=None, log=print):
    """Helius for the windows our data does not cover, within `budget` credits. -> (mints read, credits spent)."""
    if budget <= 0:
        return 0, 0
    if fetch is None:
        from wallets import rpc
        fetch = rpc.fetch
    per = (int(c["pre_pages"]) + int(c["post_pages"])) * 10
    spent = [0]

    def on_credits(n):
        spent[0] += n

    n = 0
    for tok, since, t0 in fetch_candidates(con, c, now):
        if spent[0] + per > budget:
            break
        before = spent[0]
        try:
            pre, complete = fetch(tok, since_ts=since, until_ts=t0, max_pages=int(c["pre_pages"]), oldest_first=False,
                                  on_credits=on_credits)
            post, _ = fetch(tok, since_ts=t0, until_ts=t0 + int(c["sold_window_s"]), max_pages=int(c["post_pages"]),
                            oldest_first=True, on_credits=on_credits) if int(c["post_pages"]) > 0 else ([], True)
        except Exception as e:  # noqa: BLE001 - one mint fails, the pass goes on (and it is tried again next night)
            log(f"insajderi: {tok[:6]}… Helius {type(e).__name__}: {str(e)[:80]}")
            continue
        rows = []
        for tx in list(pre) + list(post):
            trades, payer, _s = gd.owner_trades(tx, tok)
            sig = ((tx.get("transaction") or {}).get("signatures") or ["?"])[0]
            for o, side, amount, sol in trades:
                if abs(sol) >= DUST_SOL:
                    rows.append((tok, o, sig, tx.get("blockTime") or 0, tx.get("slot"), side, abs(sol), amount, payer))
        con.executemany("INSERT OR IGNORE INTO precall_trades VALUES (?,?,?,?,?,?,?,?,?)", rows)
        oldest = min((tx.get("blockTime") or t0 for tx in pre), default=None)
        con.execute("INSERT OR REPLACE INTO precall_fetched VALUES (?,?,?,?,?,?,?,?)",
                    (tok, now, spent[0] - before, len(pre) + len(post), since, t0, oldest, int(bool(complete))))
        con.execute("UPDATE precall_tokens SET built_ts = NULL WHERE token = ?", (tok,))
        con.commit()
        n += 1
    return n, spent[0]


# ===================================================================================================================
# the wallet analysis
# ===================================================================================================================
def lift(n_wh, n_w, n_h, u):
    """Shared tokens against chance: n_wh / (n_w * n_h / u). None when the expectation is 0."""
    exp = n_w * n_h / u if u else 0
    return (round(n_wh / exp, 2) if exp else None), round(exp, 3)


def _next_call(callers, b):
    """(handle, ts, rose30) of the first qualifying call after the buy b, or None."""
    nxt = [(ts, h, r) for h, (ts, r) in callers.items() if ts > b]
    if not nxt:
        return None
    ts, h, r = min(nxt)
    return h, ts, r


def _share(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def wallet_stats(obs, cut, c, totals, sniper_ext=False):
    """obs: one dict per token the wallet bought before a call: {"token", "t0", "buy_ts", "callers" {h: (ts, rose30)},
    "sold_ts", "sol_in", "sol_out", "first_trade"} (dev-funded and bundle buys already out). cut: tokens first called
    before it select, after it confirm. totals: {"sel": (U, {h: n_h}), "conf": (...), "all": (...)} over the covered
    tokens. -> stats with status (confirmed | candidate | watch | None) and why (sniper)."""
    pw = int(c["pre_window_s"])
    out_obs = []
    for o in obs:
        nx = _next_call(o["callers"], o["buy_ts"])
        if nx is None:
            continue
        h, ts, r = nx
        sold = o.get("sold_ts")
        front = {hh for hh, (tt, _r) in o["callers"].items() if tt - pw <= o["buy_ts"] < tt}
        out_obs.append({**o, "next": h, "next_ts": ts, "min_before": (ts - o["buy_ts"]) / 60, "rose30": r,
                        "sold_into": int(bool(sold) and ts <= sold <= ts + int(c["sold_window_s"])),
                        "first": o["buy_ts"] < o["t0"], "front": front, "sel": o["t0"] < cut})
    if not out_obs:
        return None

    def links_of(part, key):
        u, n_h = totals[key]
        n_w = len(part)
        cnt = Counter(h for o in part for h in o["front"])
        res = {}
        for h, n in cnt.items():
            lf, exp = lift(n, n_w, n_h.get(h, n), u)
            mins = _med([(o["callers"][h][0] - o["buy_ts"]) / 60 for o in part if h in o["front"]])
            res[h] = {"n": n, "expected": exp, "lift": lf, "med_min": _r(mins, 1)}
        return res

    sel = [o for o in out_obs if o["sel"]]
    conf = [o for o in out_obs if not o["sel"]]
    links_all = links_of(out_obs, "all")
    links_sel = links_of(sel, "sel") if sel else {}
    best = max(((h, d) for h, d in links_sel.items() if d["n"] >= c["min_link"] and (d["lift"] or 0) >= c["min_lift"]),
               key=lambda x: (x[1]["n"], x[1]["lift"] or 0), default=(None, None))[0]
    n_first_sel = sum(o["first"] for o in sel)
    n_first_conf = sum(o["first"] for o in conf)
    n_best_sel = sum(1 for o in sel if best in o["front"]) if best else 0
    n_best_conf = sum(1 for o in conf if best in o["front"]) if best else 0
    r30_sel, r30_conf = _share(o["rose30"] for o in sel), _share(o["rose30"] for o in conf)
    sel_ok = (n_first_sel >= c["min_tokens"] or n_best_sel >= c["min_tokens"]) and \
        (r30_sel is None or r30_sel >= c["min_rose30"])
    conf_ok = (n_first_conf >= c["min_confirm"] or n_best_conf >= c["min_confirm"]) and \
        (r30_conf is None or r30_conf >= c["min_rose30"])
    ft = [o["buy_ts"] - o["first_trade"] for o in out_obs if o.get("first_trade")]
    sniper = sniper_ext or (len(ft) >= 2 and sum(1 for x in ft if x <= c["sniper_secs"]) / len(ft) >= c["sniper_share"])
    closed = [(o["sol_out"] or 0) - (o["sol_in"] or 0) for o in out_obs if o.get("sold_ts") and o.get("sol_in")]
    n_first = sum(o["first"] for o in out_obs)
    status = "confirmed" if sel_ok and conf_ok else "candidate" if sel_ok else "watch" if len(out_obs) >= 2 else None
    why = None
    if sniper and status:
        status, why = "excluded", "sniper (kupuje u prvim sekundama lansiranja)"
    best_all = max(links_all.items(), key=lambda x: (x[1]["n"], x[1]["lift"] or 0), default=(None, {}))[1]
    rose = _share(o["rose30"] for o in out_obs)
    score = (n_first + 0.5 * (len(out_obs) - n_first) + 2 * (rose or 0) + min(10.0, best_all.get("lift") or 0) / 5
             + (3 if status == "confirmed" else 0))
    return {"status": status, "why": why, "score": round(score, 2), "n_tokens": len(out_obs), "n_first": n_first,
            "n_sel": max(n_first_sel, n_best_sel), "n_conf": max(n_first_conf, n_best_conf),
            "med_min": _r(_med(o["min_before"] for o in out_obs), 1), "rose30": rose,
            "sold_into": _share(o["sold_into"] for o in out_obs), "pnl_sol": _r(sum(closed)) if closed else None,
            "links": links_all, "best_caller_sel": best, "rose30_sel": r30_sel, "rose30_conf": r30_conf,
            "first_sel": n_first_sel, "first_conf": n_first_conf, "best_sel": n_best_sel, "best_conf": n_best_conf,
            "n_closed": len(closed)}


def owner_labels(trade_db=None):
    """{wallet: {"label", "note", "ts", "note_id"}} the owner applied ("Primijeni na bota"; trade.db settings
    insider_labels). Read-only; {} when unreadable."""
    try:
        from trade import settings
        tc = _ro(trade_db or settings.DB)
    except Exception:  # noqa: BLE001
        return {}
    r = _q(tc, "SELECT v FROM settings WHERE k = 'insider_labels'")
    if tc is not None:
        tc.close()
    try:
        d = json.loads(r[0][0]) if r else {}
    except (ValueError, TypeError):
        d = {}
    return d if isinstance(d, dict) else {}


def parse_label(x):
    """proposed_change["insider_label"] -> (wallet, label, note); ValueError (Croatian) when it is not one."""
    if not isinstance(x, dict):
        raise ValueError("insider_label mora biti objekt {wallet, label, note}")
    w = str(x.get("wallet") or "").strip()
    lab = str(x.get("label") or "").strip().lower()
    if not 32 <= len(w) <= 44 or not w.isalnum() or any(ch in w for ch in "0OIl"):
        raise ValueError("insider_label.wallet nije Solana adresa")
    if lab not in LABELS:
        raise ValueError(f"insider_label.label mora biti jedno od: {', '.join(LABELS)}")
    return w, lab, str(x.get("note") or "")[:300]


def _relayers(con, c):
    paid = _q(con, "SELECT DISTINCT payer, wallet FROM precall_trades WHERE payer IS NOT NULL AND payer != wallet")
    paid += _q(con, "SELECT DISTINCT payer, wallet FROM group_buys WHERE payer IS NOT NULL AND payer != wallet")
    return gd.relayers(paid, c["relayer_min"]), paid


def _bots(con, p, c, since, cand):
    """Bots among `cand`: rate rules on our Helius trades, group_discovery's rules (group_buys, live_trades), wallets.db
    labels bot / mev / sniper and chainwatch.too_busy (> 60 trades a day, bundler / mev / cex / rugger)."""
    out = {w for (w,) in _q(con, "SELECT DISTINCT wallet FROM precall_trades WHERE ts >= ? GROUP BY wallet, ts / 60 "
                                 "HAVING COUNT(*) > ?", (since, c["bot_tx_min"]))}
    out |= {w for (w,) in _q(con, "SELECT DISTINCT wallet FROM precall_trades WHERE ts >= ? AND slot IS NOT NULL "
                                  "GROUP BY wallet, mint, slot HAVING COUNT(DISTINCT side) > 1", (since,))}
    out |= gd.bots_sql(con, _ro(p["hype_db"]), since, {"bot_tx_min": c["bot_tx_min"]})
    out &= cand
    out |= gd.bots([], labels=gd._labels(p.get("wallet_db"), cand))
    try:
        from kol import chainwatch
        out |= chainwatch.too_busy(cand, p.get("wallet_db"))
    except Exception:  # noqa: BLE001
        pass
    return out & cand


def _profile_sniper(wallets, p):
    try:
        from kol import insiders
    except Exception:  # noqa: BLE001
        return set()
    out = set()
    for w in wallets:
        try:
            pr = insiders.profile(w, p.get("wallet_db"), p.get("kol_db"))
        except Exception:  # noqa: BLE001
            pr = None
        if pr and pr.get("sniper"):
            out.add(w)
    return out


def analyze(con, p, c, now):
    """The wallet analysis over the covered tokens of the last `days`: precall_wallets and precall_links rewritten.
    Heavy parts in SQLite; Python holds one wallet's rows at a time plus the token table. Returns a summary."""
    since = now - int(c["days"]) * 86400
    cut = now - int(c["days"]) * 86400 // 3
    toks = {}
    for tok, t0, ft, dev in _q(con, "SELECT token, t0, first_trade_ts, dev FROM precall_tokens WHERE t0 >= ? AND "
                                    "buyers > 0", (since,)):
        toks[tok] = {"t0": t0, "first_trade": ft, "dev": dev, "callers": {}}
    for tok, h, ts, r in _q(con, "SELECT c.token, c.handle, c.call_ts, c.rose30 FROM precall_calls c JOIN precall_tokens t "
                                 "ON t.token = c.token WHERE t.t0 >= ? AND t.buyers > 0", (since,)):
        if tok in toks:
            toks[tok]["callers"][h] = (ts, r)
    totals = {}
    for key, part in (("all", toks), ("sel", {t: d for t, d in toks.items() if d["t0"] < cut}),
                      ("conf", {t: d for t, d in toks.items() if d["t0"] >= cut})):
        totals[key] = (len(part), Counter(h for d in part.values() for h in d["callers"]))
    relay, paid = _relayers(con, c)
    con.executescript("DROP TABLE IF EXISTS temp.pw; CREATE TEMP TABLE pw (wallet TEXT PRIMARY KEY);"
                      "DROP TABLE IF EXISTS temp.pt; CREATE TEMP TABLE pt (token TEXT PRIMARY KEY);")
    con.executemany("INSERT INTO temp.pt VALUES (?)", [(t,) for t in toks])
    con.execute("INSERT INTO temp.pw SELECT b.wallet FROM precall_buys b JOIN temp.pt t ON t.token = b.token "
                "GROUP BY b.wallet HAVING COUNT(*) >= 2")
    cand = {w for (w,) in _q(con, "SELECT wallet FROM temp.pw")} - relay
    bots = _bots(con, p, c, since, cand) if cand else set()
    labels = owner_labels(p.get("trade_db"))
    # one owner (shared non-hub funder, or a non-relayer fee payer that paid for it) and the dev's funding
    funders = gd._funders(p, toks, cand) if cand else defaultdict(set)
    for pay, w in paid:
        if w in cand and pay not in relay:
            funders[w].add(pay)
    fan = Counter(f for fs in funders.values() for f in fs)
    owner = gd.owner_ids(funders, {f for f, n in fan.items() if n > c["hub_min"]}, relay)
    per_owner = Counter()
    for tok, w in _q(con, "SELECT b.token, b.wallet FROM precall_buys b JOIN temp.pw p ON p.wallet = b.wallet"):
        if tok in toks and w in owner:   # owner ids are a member's address (the smallest), so count every member
            per_owner[(tok, owner[w])] += 1
    bundle = {k for k, n in per_owner.items() if n >= 2}
    old = {w: (s, fs, st) for w, s, fs, st in _q(con, "SELECT wallet, status, first_seen, status_ts FROM precall_wallets")}
    res, links = {}, []
    cur, rows = None, []

    def finish(w, rows):
        if not rows or w is None:
            return
        obs, dev_n = [], 0
        for tok, bts, sin, sts, sout, payer in rows:
            d = toks.get(tok)
            if d is None:
                continue
            dv = d["dev"]
            if dv and (w == dv or payer == dv or dv in funders.get(w, ())):
                dev_n += 1
                continue
            if (tok, owner.get(w, w)) in bundle:
                continue
            obs.append({"token": tok, "t0": d["t0"], "buy_ts": bts, "callers": d["callers"], "sold_ts": sts,
                        "sol_in": sin, "sol_out": sout, "first_trade": d["first_trade"]})
        st = wallet_stats(obs, cut, c, totals)
        if dev_n >= 2 and dev_n >= c["dev_share"] * (dev_n + len(obs)):
            st = {**(st or {"links": {}}), "n_tokens": dev_n + len(obs), "status": "excluded",
                  "why": "dev ili novčanik koji je dev financirao"}
        if not st or not st["status"]:
            return
        if w in bots and st["status"] != "excluded":
            st.update(status="excluded", why="bot (brzina trgovanja, oznaka ili previše tradeova dnevno)")
        lab = (labels.get(w) or {}).get("label")
        if lab in NO_COPY_LABELS and st["status"] != "excluded":
            st.update(status="excluded", why=f"vlasnik ga je označio: {lab}")
        res[w] = st

    for w, tok, bts, sin, sts, sout, payer in con.execute(
            "SELECT b.wallet, b.token, b.buy_ts, b.sol_in, b.sold_ts, b.sol_out, b.payer FROM precall_buys b "
            "JOIN temp.pw p ON p.wallet = b.wallet ORDER BY b.wallet"):
        if w != cur:
            if cur not in relay:
                finish(cur, rows)
            cur, rows = w, []
        rows.append((tok, bts, sin, sts, sout, payer))
    if cur not in relay:
        finish(cur, rows)
    con.executescript("DROP TABLE IF EXISTS temp.pw; DROP TABLE IF EXISTS temp.pt;")
    # snipers by their own trade history (wallets.db, kol/insiders.profile) for the ones that would count
    look = [w for w, s in res.items() if s["status"] in ("candidate", "confirmed")]
    for w in _profile_sniper(look, p):
        res[w].update(status="excluded", why="sniper (kol/insiders.profile: većina kupnji nikad nije pozvana)")
    watch = sorted((w for w, s in res.items() if s["status"] == "watch"), key=lambda w: -res[w]["score"])
    for w in watch[int(c["max_watch"]):]:
        del res[w]
    con.execute("DELETE FROM precall_wallets")
    con.execute("DELETE FROM precall_links")
    for w, s in res.items():
        o = old.get(w)
        first = o[1] if o else now
        sts = o[2] if o and o[0] == s["status"] else now
        stats = {k: v for k, v in s.items() if k not in ("links", "status", "why", "score")}
        con.execute("INSERT INTO precall_wallets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (w, s["status"], s.get("why"), s.get("score"), s.get("n_tokens"), s.get("n_first"), s.get("n_sel"),
                     s.get("n_conf"), s.get("med_min"), s.get("rose30"), s.get("sold_into"), s.get("pnl_sol"),
                     json.dumps(stats, separators=(",", ":")), first, sts, now))
        for h, d in (s.get("links") or {}).items():
            if d["n"] >= c["min_link"]:
                links.append((w, h, d["n"], d["expected"], d["lift"], d["med_min"]))
    con.executemany("INSERT INTO precall_links VALUES (?,?,?,?,?,?)", links)
    con.commit()
    st = Counter(s["status"] for s in res.values())
    return {"tokens": len(toks), "wallets": len(res), "confirmed": st.get("confirmed", 0),
            "candidates": st.get("candidate", 0), "excluded": st.get("excluded", 0), "watch": st.get("watch", 0),
            "relayers": len(relay), "bots": len(bots), "links": len(links)}


def mirror(con, p, now, log=print):
    """kol.db precall_links (caller <-> front-running wallets) and wallets.db precall_insiders (label
    'precall_insider'), rewritten from early.db. Never the `wallets` table (tier, labels, scores)."""
    rows = _q(con, "SELECT wallet, status, why, n_tokens, n_first, med_min, rose30, sold_into, pnl_sol FROM "
                   "precall_wallets WHERE status IN ('candidate', 'confirmed', 'excluded')")
    keep = {r[0]: r for r in rows}
    links = [r for r in _q(con, "SELECT handle, wallet, n, lift, med_min FROM precall_links") if r[1] in keep]
    labels = owner_labels(p.get("trade_db"))
    by_w = defaultdict(list)
    for h, w, n, lf, mm in links:
        by_w[w].append({"handle": h, "n": n, "lift": lf, "med_min": mm})
    n_k = n_w = 0
    try:
        kc = sqlite3.connect(p["kol_db"], timeout=60)
        try:
            kc.execute(KOL_SCHEMA)
            kc.execute("DELETE FROM precall_links")
            kc.executemany("INSERT INTO precall_links VALUES (?,?,?,?,?,?,?)",
                           [(h, w, n, lf, mm, keep[w][1], now) for h, w, n, lf, mm in links])
            kc.commit()
            n_k = len(links)
        finally:
            kc.close()
    except sqlite3.Error as e:
        log(f"insajderi: kol.db precall_links nije upisan ({e})")
    try:
        wc = sqlite3.connect(p["wallet_db"], timeout=60)
        try:
            wc.execute(WALLET_SCHEMA)
            wc.execute("DELETE FROM precall_insiders")
            wc.executemany("INSERT INTO precall_insiders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           [(w, "precall_insider", s, why, n, nf, mm, r30, si, pnl,
                             json.dumps(sorted(by_w.get(w, []), key=lambda x: -x["n"])[:10], separators=(",", ":")),
                             (labels.get(w) or {}).get("label"), now)
                            for w, s, why, n, nf, mm, r30, si, pnl in rows])
            wc.commit()
            n_w = len(rows)
        finally:
            wc.close()
    except sqlite3.Error as e:
        log(f"insajderi: wallets.db precall_insiders nije upisan ({e})")
    return n_k, n_w


# ===================================================================================================================
# 4) copy behind the flag
# ===================================================================================================================
def copy_set(con=None, c=None, trade_db=None, path=None):
    """[(wallet, score)]: the confirmed wallets worth copying, best first, without the owner's bot / sniper labels."""
    c = c or config()
    own = con is None
    con = con or _ro(path or gd.db_path())
    rows = _q(con, "SELECT wallet, score FROM precall_wallets WHERE status = 'confirmed' ORDER BY score DESC, wallet LIMIT ?",
              (int(c["max_follows"]) * 3,))
    if own and con is not None:
        con.close()
    labels = owner_labels(trade_db)
    out = [(w, s) for w, s in rows if (labels.get(w) or {}).get("label") not in NO_COPY_LABELS]
    return out[:int(c["max_follows"])]


def webhook_wallets(limit=None, trade_db=None, path=None):
    """Wallets kol/chainwatch.wanted() adds to the Helius webhook: the copy set, ONLY while the flag is in paper or
    live (every webhook event costs a credit); [] otherwise."""
    if mode(trade_db) not in ("paper", "live"):
        return []
    c = config()
    ws = [w for w, _s in copy_set(None, c, trade_db, path)]
    return ws[:int(limit if limit is not None else c["max_webhook"])]


def _shadow_lines(p, rows, now):
    """rows [(token, old, new, detail)] -> league.db shadow_decisions under this flag (league/flags.shadow)."""
    if not rows or not p.get("league_db"):
        return 0
    from league import flags as lflags
    try:
        lc = sqlite3.connect(p["league_db"], timeout=30)
    except sqlite3.Error:
        return 0
    try:
        n = sum(bool(lflags.shadow(lc, FLAG, None, t, o, nw, d, now)) for t, o, nw, d in rows)
        lc.commit()
    finally:
        lc.close()
    return n


def _stop_follows(con, p, now, keep_users=(), keep_wallets=frozenset()):
    """Stop this module's follows (league.db) that are no longer wanted. Returns how many."""
    rows = _q(con, "SELECT follow_id, user, wallet FROM precall_follows WHERE stopped IS NULL")
    drop = [(fid, u) for fid, u, w in rows if u not in keep_users or w not in keep_wallets]
    if not drop or not p.get("league_db"):
        return 0
    n = 0
    lc = sqlite3.connect(p["league_db"], timeout=30)
    try:
        for fid, u in drop:
            try:
                n += lc.execute("UPDATE follows SET active = 0, stopped = ? WHERE id = ? AND user = ? AND active = 1",
                                (now, fid, u)).rowcount or 0
            except sqlite3.Error:
                pass
            con.execute("UPDATE precall_follows SET stopped = ? WHERE follow_id = ?", (now, fid))
        lc.commit()
    finally:
        lc.close()
    con.commit()
    return n


def copy_step(con, p, c, now, m, log=print):
    """Shadow lines for the copy set's fresh buys and follow changes; in paper the demo account follows them (in live
    the Autopilot account too). Returns {"set", "seen", "followed", "stopped", "shadow"}."""
    from trade import settings
    want = [w for w, _s in copy_set(con, c, p.get("trade_db"))]
    out = {"set": len(want), "seen": 0, "followed": 0, "stopped": 0, "shadow": 0}
    lines = []
    last = int(float(kv(con, "copy_seen_ts") or 0)) or now - 900
    if want:
        hc = _ro(p["hype_db"])
        q = _in(want)
        buys = _q(hc, f"SELECT wallet, mint, MIN(ts) FROM chain_trades WHERE side = 'buy' AND ts > ? AND wallet IN ({q}) "
                      f"GROUP BY wallet, mint", (last - 60, *want))
        buys += _q(hc, f"SELECT wallet, mint, MIN(ts) FROM live_trades WHERE side = 'buy' AND ts > ? AND wallet IN ({q}) "
                       f"GROUP BY wallet, mint", (last - 60, *want))
        if hc is not None:
            hc.close()
        for w, mint, ts in sorted(buys, key=lambda r: r[2]):
            if con.execute("INSERT OR IGNORE INTO precall_seen VALUES (?,?,?)", (w, mint, ts)).rowcount:
                out["seen"] += 1
                if m in ("shadow", "paper"):
                    lines.append((mint, "nema", "kopiraj kupnju insajdera",
                                  {"wallet": w, "ts": ts, "who": "Autopilot (samo zapis)",
                                   "note": "kopija prolazi ista vrata kao svaka: ispod 30k i na krivulji se ne kupuje"}))
    kv(con, "copy_seen_ts", now)
    users = ((settings.PAPER_USER,) if m == "paper" else (settings.PAPER_USER, settings.LEAGUE_USER) if m == "live" else ())
    out["stopped"] = _stop_follows(con, p, now, users, set(want))
    ours = {(u, w) for u, w in _q(con, "SELECT user, wallet FROM precall_follows WHERE stopped IS NULL")}
    if users and want and p.get("league_db"):
        from league import copy as lcopy
        lc = sqlite3.connect(p["league_db"], timeout=30)
        try:
            lcopy.ensure(lc)
            for u in users:
                for w in want:
                    if (u, w) in ours:
                        continue
                    if lc.execute("SELECT 1 FROM follows WHERE user = ? AND kind = 'wallet' AND target = ? AND active = 1",
                                  (u, w)).fetchone():
                        continue   # the owner already follows it his own way: never taken over
                    fid = lcopy.follow(lc, u, "wallet", w, f"insajder prije poziva {w[:4]}…", c["size_usd"],
                                       c["per_day"], "mirror")
                    con.execute("INSERT OR REPLACE INTO precall_follows VALUES (?,?,?,?,NULL)", (fid, u, w, now))
                    out["followed"] += 1
        finally:
            lc.close()
        con.commit()
    if m in ("shadow", "paper"):   # the Autopilot account only logs which wallets it would follow
        prev = set(json.loads(kv(con, "would_follow") or "[]"))
        for w in sorted(set(want) - prev):
            lines.append((w, "ne prati", "prati insajdera (mirror)", {"wallet": w, "who": "Autopilot (samo zapis)"}))
        for w in sorted(prev - set(want)):
            lines.append((w, "prati insajdera", "ne prati", {"wallet": w, "who": "Autopilot (samo zapis)"}))
        kv(con, "would_follow", json.dumps(sorted(want)))
    con.commit()
    out["shadow"] = _shadow_lines(p, lines, now)
    return out


def live_refusal(con, now=None, path=None, league_db=None, cfg=None):
    """trade/settings.LIVE_GATES: None when insider_copy may go live (on top of the backtest and 7 days of paper in the
    plus), else why not: >= live_min_closed closed paper copies of this module's follows since the flag went to paper,
    with EV (mean return) > 0. con: trade.db. A proof that cannot be read refuses."""
    from trade import settings
    c = config(cfg)
    st = settings.flag_state(con)[FLAG]
    since = st["since"] or 0
    ec = _ro(path or gd.db_path())
    fids = [f for (f,) in _q(ec, "SELECT follow_id FROM precall_follows WHERE user = ?", (settings.PAPER_USER,))]
    if ec is not None:
        ec.close()
    rets = []
    if fids:
        from league import store as lstore
        lc = _ro(league_db or lstore.DB)
        for ch in _chunks(fids):
            for ret, pnl, size in _q(lc, f"SELECT ret, pnl_usd, size_usd FROM trades WHERE user = ? AND status = 'closed' "
                                         f"AND opened_ts >= ? AND follow_id IN ({_in(ch)})", (settings.PAPER_USER, since, *ch)):
                r = ret if ret is not None else (pnl / size if pnl is not None and size else None)
                if r is not None:
                    rets.append(r)
        if lc is not None:
            lc.close()
    need = int(c["live_min_closed"])
    if len(rets) < need:
        return f"paper ima tek {len(rets)} od {need} zatvorenih kopija insajdera"
    ev = sum(rets) / len(rets)
    if ev <= 0:
        return f"EV paper kopija insajdera {ev:+.1%} na {len(rets)} tradeova nije iznad nule"
    return None


# ===================================================================================================================
# the passes
# ===================================================================================================================
def _stop_if_off(p, now):
    """Flag off: nothing runs, except that follows this module started earlier are switched off (read-only check
    first, so a pass with nothing to undo writes nothing)."""
    path = p["early_db"]
    ec = _ro(path)
    rows = _q(ec, "SELECT 1 FROM precall_follows WHERE stopped IS NULL LIMIT 1")
    if ec is not None:
        ec.close()
    if not rows:
        return 0
    con = connect(path)
    try:
        return _stop_follows(con, p, now)
    finally:
        con.close()


def prune(con, c, now):
    keep = now - int(c["keep_days"]) * 86400
    con.execute("DELETE FROM precall_launch WHERE reached_ts IS NULL AND launch_ts < ?", (now - int(c["launch_keep_h"]) * 3600,))
    con.execute("DELETE FROM precall_launch WHERE launch_ts < ?", (keep,))
    con.execute("DELETE FROM precall_trades WHERE ts < ?", (keep,))
    con.execute("DELETE FROM precall_buys WHERE token IN (SELECT token FROM precall_tokens WHERE t0 < ?)", (keep,))
    con.execute("DELETE FROM precall_calls WHERE token IN (SELECT token FROM precall_tokens WHERE t0 < ?)", (keep,))
    con.execute("DELETE FROM precall_tokens WHERE t0 < ?", (keep,))
    con.execute("DELETE FROM precall_seen WHERE ts < ?", (keep,))
    con.execute("DELETE FROM precall_runs WHERE ts < ?", (keep,))
    con.execute("DELETE FROM precall_kv WHERE key LIKE 'dex:%' AND key < ?", (f"dex:{_day(keep)}",))


def incremental(cfg=None, now=None, log=print, dex=None, fetch=None, credits=None, **over):
    """The 15-minute pass. None when the flag is off (nothing read, written or paid)."""
    p = paths(**over)
    now = int(now or time.time())
    m = mode(p.get("trade_db"))
    if m == "off":
        _stop_if_off(p, now)
        return None
    c = config(cfg)
    con = connect(p["early_db"])
    try:
        la = measure_launches(con, p, c, now, dex, log)
        con.execute("DELETE FROM precall_launch WHERE reached_ts IS NULL AND launch_ts < ?",   # 20-40k a day: a day only
                    (now - int(c["launch_keep_h"]) * 3600,))
        n_calls = collect_calls(con, p, c, now, since=now - int(c["incr_days"]) * 86400)
        # live_trades is kept 48 h: the buyers of a fresh call are taken while they are there, and again until the
        # hour after its last call is over (the sells into the call)
        fresh = [t for (t,) in _q(con, "SELECT token FROM precall_tokens WHERE last_call_ts >= ? AND (built_ts IS NULL "
                                       "OR (built_ts < last_call_ts + ? AND built_ts < ?))",
                                  (now - 46 * 3600, int(c["sold_window_s"]) + 3600, now - 600))]
        n_built = build_buys(con, p, c, now, fresh) if fresh else 0
        spent = 0
        budget = int(c["incr_credits"] if credits is None else credits)
        if budget > 0:
            day = _day(now)
            used = int(float(kv(con, f"incr_credits:{day}") or 0))
            _n, spent = fetch_windows(con, c, now, budget, fetch, log)
            kv(con, f"incr_credits:{day}", used + spent)
            if _n:
                build_buys(con, p, c, now)
        cp = copy_step(con, p, c, now, m, log)
        detail = {"launches": la, "calls": n_calls, "built": n_built, "copy": cp}
        con.execute("INSERT INTO precall_runs VALUES (?,?,?,?,?)", (now, "incr", spent, la["dex_calls"], json.dumps(detail)))
        con.commit()
        if la["checked"] or n_built or cp["seen"] or cp["followed"] or cp["stopped"]:
            log(f"insajderi (15 min, {m}): {la['new']} novih lansiranja, provjereno {la['checked']} "
                f"(DexScreener {la['dex_calls']} poziva), {la['reached']} do 10k; {n_built} tokena s kupcima prije "
                f"poziva; kopija: {cp['set']} novčanika, {cp['seen']} novih kupnji, +{cp['followed']}/-{cp['stopped']} "
                f"praćenja" + (f", Helius {spent} kredita" if spent else ""))
        return detail
    finally:
        con.close()


def night(cfg=None, now=None, credits=None, log=print, fetch=None, force=False, **over):
    """The full pass (01-06 Zagreb under ops.heavy --night). None when the flag is off or a pass ran < night_gap_h ago."""
    p = paths(**over)
    m = mode(p.get("trade_db"))
    if m == "off":
        log("insajderi: zastavica insider_copy je isključena, noćni prolaz ne radi ništa")
        return None
    c = config(cfg)
    now = int(now or time.time())
    con = connect(p["early_db"])
    try:
        last = int(float(kv(con, "last_night") or 0))
        if not force and now - last < c["night_gap_h"] * 3600:
            log(f"insajderi: noćni prolaz je već bio prije {(now - last) / 3600:.1f} h, preskačem")
            return None
        n_calls = collect_calls(con, p, c, now)
        budget = int(c["night_credits"] if credits is None else credits)
        n_read, spent = fetch_windows(con, c, now, budget, fetch, log)
        n_built = build_buys(con, p, c, now)
        res = analyze(con, p, c, now)
        n_k, n_w = mirror(con, p, now, log)
        prune(con, c, now)
        kv(con, "last_night", now)
        detail = {**res, "calls_tokens": n_calls, "built": n_built, "mints_read": n_read, "credits": spent,
                  "budget": budget, "kol_links": n_k, "wallet_rows": n_w}
        con.execute("INSERT INTO precall_runs VALUES (?,?,?,?,?)", (now, "night", spent, 0, json.dumps(detail)))
        con.commit()
        log(f"insajderi (noć, {m}): {res['tokens']} pozvanih tokena s kupcima prije poziva, {res['confirmed']} "
            f"potvrđenih i {res['candidates']} kandidata, {res['excluded']} isključenih ({res['relayers']} relayera, "
            f"{res['bots']} botova); Helius {n_read} tokena za {spent} kredita (strop {budget})")
        return detail
    finally:
        con.close()


# ===================================================================================================================
# read side: MCP, report
# ===================================================================================================================
def _labels_from_notes(trade_db=None):
    """{wallet: [{"label", "note", "status", "note_id"}]} proposed through submit_suggestion (not yet applied)."""
    from trade import settings
    tc = _ro(trade_db or settings.DB)
    out = defaultdict(list)
    for nid, pc, status in _q(tc, "SELECT id, proposed_change, status FROM assistant_notes WHERE kind = 'suggestion' "
                                  "AND proposed_change LIKE '%insider_label%' AND status IN ('novo', 'prihvaćeno') "
                                  "ORDER BY id DESC LIMIT 500"):
        try:
            w, lab, note = parse_label((json.loads(pc) or {}).get("insider_label"))
        except (ValueError, TypeError, AttributeError):
            continue
        out[w].append({"label": lab, "note": note, "status": status, "note_id": nid})
    if tc is not None:
        tc.close()
    return out


def candidates(min_tokens=None, limit=None, path=None, trade_db=None):
    """get_insider_candidates: the candidate and confirmed wallets with stats, the callers they front-run and example
    tokens with times; empty with a note while the flag is off."""
    m = mode(trade_db)
    c = config()
    base = {"flag": FLAG, "flag_mode": m, "label_shape": LABEL_SHAPE, "labels": list(LABELS),
            "no_copy_labels": sorted(NO_COPY_LABELS), "statuses_hr": STATUS_HR,
            "rule": {"window": "od prvog tradea tokena (ili 6 h prije poziva) do poziva", "min_call_mcap": c["min_call_mcap"],
                     "select": f"starije 2/3 od {c['days']} dana: >= {c['min_tokens']} tokena prije prvog poziva ili "
                               f"prije poziva jednog callera s liftom >= {c['min_lift']}",
                     "confirm": f"novija 1/3: >= {c['min_confirm']} tokena, rast +30 % u 1 h barem {c['min_rose30']:.0%}"}}
    if m == "off":
        return {**base, "wallets": [], "total": 0, "note": "zastavica insider_copy je isključena"}
    try:
        mt = max(1, int(min_tokens if min_tokens is not None else c["min_tokens"]))
        lim = max(1, min(200, int(limit or 50)))
    except (TypeError, ValueError):
        return {"error": "min_tokens and limit must be integers"}
    ec = _ro(path or gd.db_path())
    rows = _q(ec, "SELECT wallet, status, why, score, n_tokens, n_first, n_sel, n_conf, med_min, rose30, sold_into, "
                  "pnl_sol, stats, first_seen, status_ts, updated FROM precall_wallets WHERE status IN ('candidate', "
                  "'confirmed') AND n_tokens >= ? ORDER BY status = 'confirmed' DESC, score DESC LIMIT ?", (mt, lim))
    total = (_q(ec, "SELECT COUNT(*) FROM precall_wallets WHERE status IN ('candidate', 'confirmed') AND n_tokens >= ?",
                (mt,)) or [(0,)])[0][0]
    labels = owner_labels(trade_db)
    proposed = _labels_from_notes(trade_db)
    out = []
    for (w, st, why, sc, n, nf, ns, nc, mm, r30, si, pnl, stats, fs, sts, upd) in rows:
        links = [{"caller": h, "tokens": k, "expected": e, "lift": lf, "median_min_before": mmb}
                 for h, k, e, lf, mmb in _q(ec, "SELECT handle, n, expected, lift, med_min FROM precall_links WHERE "
                                                "wallet = ? ORDER BY n DESC, lift DESC LIMIT 8", (w,))]
        ex = []
        for tok, bts, sin, sold, sout, t0, mc0, fh in _q(
                ec, "SELECT b.token, b.buy_ts, b.sol_in, b.sold_ts, b.sol_out, t.t0, t.mcap0, t.first_handle FROM "
                    "precall_buys b JOIN precall_tokens t ON t.token = b.token WHERE b.wallet = ? AND b.buy_ts < "
                    "t.last_call_ts ORDER BY t.t0 DESC LIMIT 6", (w,)):
            calls = _q(ec, "SELECT handle, call_ts, rose30 FROM precall_calls WHERE token = ? AND call_ts > ? ORDER BY "
                           "call_ts LIMIT 1", (tok, bts))
            nxt = calls[0] if calls else (None, None, None)
            ex.append({"token": tok, "bought_ts": bts, "sol_in": sin, "first_call_ts": t0, "first_caller": fh,
                       "mcap_at_first_call": mc0, "next_call_by": nxt[0], "next_call_ts": nxt[1],
                       "minutes_before_next_call": round((nxt[1] - bts) / 60, 1) if nxt[1] else None,
                       "rose30_within_1h": None if nxt[2] is None else bool(nxt[2]), "sold_ts": sold, "sol_out": sout,
                       "sold_into_call": bool(sold and nxt[1] and nxt[1] <= sold <= nxt[1] + c["sold_window_s"]),
                       "under_30k": bool(mc0 and mc0 < 30000)})
        lab = labels.get(w) or {}
        out.append({"wallet": w, "status": st, "status_hr": STATUS_HR.get(st), "score": sc, "tokens": n,
                    "tokens_before_first_call": nf, "select_tokens": ns, "confirm_tokens": nc,
                    "median_min_before_call": mm, "rose30_share": r30, "sold_into_call_share": si, "pnl_sol": pnl,
                    "stats": json.loads(stats or "{}"), "callers_front_run": links, "examples": ex,
                    "label": lab.get("label"), "label_note": lab.get("note"),
                    "proposed_labels": (proposed.get(w) or [])[:5], "first_seen_ts": fs, "status_since_ts": sts,
                    "updated_ts": upd, "copied": st == "confirmed" and lab.get("label") not in NO_COPY_LABELS})
    if ec is not None:
        ec.close()
    return {**base, "wallets": out, "total": total}


def mcp_tool(name, a):
    a = a if isinstance(a, dict) else {}
    return candidates(a.get("min_tokens"), a.get("limit"))


def report_data(now=None, path=None, trade_db=None, league_db=None):
    """The daily report section: launches measured / at 10k, new candidates, confirmed ones, paper results and the
    day's cost per source. None while the flag is off and nothing was ever stored."""
    now = int(now or time.time())
    m = mode(trade_db)
    ec = _ro(path or gd.db_path())
    if ec is None or not _q(ec, "SELECT 1 FROM precall_runs LIMIT 1"):
        if ec is not None:
            ec.close()
        return None
    day = now - 86400
    try:
        la = _q(ec, "SELECT COUNT(*), SUM(checks > 0), SUM(reached_ts >= ?) FROM precall_launch WHERE launch_ts >= ?",
                (day, day))[0]
        runs = _q(ec, "SELECT kind, COUNT(*), SUM(credits), SUM(dex_calls) FROM precall_runs WHERE ts >= ? GROUP BY kind",
                  (day,))
        st = dict(_q(ec, "SELECT status, COUNT(*) FROM precall_wallets GROUP BY status"))
        new = _q(ec, "SELECT wallet, status, n_tokens, n_first, med_min, rose30 FROM precall_wallets WHERE status IN "
                     "('candidate', 'confirmed') AND status_ts >= ? ORDER BY score DESC LIMIT 10", (day,))
        conf = _q(ec, "SELECT wallet, n_tokens, n_sel, n_conf, med_min, rose30, sold_into FROM precall_wallets WHERE "
                      "status = 'confirmed' ORDER BY score DESC LIMIT 10")
        fids = [f for (f,) in _q(ec, "SELECT follow_id FROM precall_follows")]
    finally:
        ec.close()
    paper = {"n": 0, "ev": None, "pnl": 0.0, "open": 0}
    if fids:
        from league import store as lstore
        lc = _ro(league_db or lstore.DB)
        rets = []
        for ch in _chunks(fids):
            for status, ret, pnl in _q(lc, f"SELECT status, ret, pnl_usd FROM trades WHERE follow_id IN ({_in(ch)})", ch):
                if status == "closed":
                    paper["n"] += 1
                    paper["pnl"] += pnl or 0
                    if ret is not None:
                        rets.append(ret)
                elif status == "open":
                    paper["open"] += 1
        if lc is not None:
            lc.close()
        paper["ev"] = round(sum(rets) / len(rets), 4) if rets else None
        paper["pnl"] = round(paper["pnl"], 2)
    cost = {k: {"runs": n, "helius_credits": int(cr or 0), "dex_calls": int(dx or 0)} for k, n, cr, dx in runs}
    return {"mode": m, "launches_24h": la[0] or 0, "checked_24h": la[1] or 0, "reached_10k_24h": la[2] or 0,
            "status": st, "new_24h": [dict(zip(("wallet", "status", "tokens", "first", "med_min", "rose30"), r)) for r in new],
            "confirmed": [dict(zip(("wallet", "tokens", "sel", "conf", "med_min", "rose30", "sold_into"), r)) for r in conf],
            "paper": paper, "cost_24h": cost}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Insajderi prije poziva i mjerenje novih tokena od 10k (zastavica insider_copy)")
    ap.add_argument("cmd", choices=("night", "incr", "status"))
    ap.add_argument("--credits", type=int, default=None, help="Helius krediti za ovaj prolaz (strop)")
    ap.add_argument("--force", action="store_true", help="noćni prolaz i ako je bio prije manje od 20 h")
    a = ap.parse_args(argv)
    if a.cmd == "night":
        night(credits=a.credits, force=a.force)
    elif a.cmd == "incr":
        incremental(credits=a.credits)
    else:
        ec = _ro(gd.db_path())
        for ts, kind, cr, dx, d in _q(ec, "SELECT ts, kind, credits, dex_calls, detail FROM precall_runs ORDER BY ts DESC LIMIT 10"):
            print(time.strftime("%d.%m. %H:%M", time.gmtime(ts)), kind, f"Helius {cr}", f"DexScreener {dx}", d)
        print(f"zastavica {FLAG}: {mode()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
