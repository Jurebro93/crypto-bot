"""The market watchlist of range_dca (11.11., Jure: "širi range watchlist"; flag range_market G20, event tokens flag
event_tokens G19). run_range.py once calls pass_once() every minute while either flag is on; it writes range.db only.

Why: the signal pass (data.candidates) watches at most RANGE_MAX_TOKENS (40) tokens and only those our own signals
name (open rounds, Autopilot tokens, recent ranges, the hype scan's top 40, KOL calls), so get_range_candidates
showed watched=40 out of a market of hundreds of ranging tokens. This pass adds the whole bonded market, inside a
measured daily budget per source (CLAUDE.md: izmjeri i odaberi najjeftinije).

Universe (table mkt), cheapest first:
  migracija    hype.db live_launches pool 'migration' (PumpPortal's free migration event, kept 7 days)
  graduates    kol.db graduates (the KOL round's PumpSwap listing, already paid by nobody)
  skener       scan.db cand: the market scanner's tokens with the numbers it priced in the last 10 min (free)
  event        the main / other tokens of the active event topics (topics.db, flag event_tokens)
  dex_liste    DexScreener latest profiles, latest and top boosts: 3 requests every LISTS_EVERY_S (free API, the
               60-a-minute endpoints), at most LISTS_DAY a day
  gt           GeckoTerminal trending pools and the top pools by 24 h volume: 2 requests every GT_EVERY_S, at most GT_DAY
               a day out of the SHARED CoinGecko budget (3000 a day; scan 150, range seeds 60, events 600 a night,
               momentum 100); their numbers admit a pool without another request
  birdeye      Birdeye's token list by 24 h volume, ONLY with BIRDEYE_API_KEY, every BIRD_EVERY_S, at most BIRDEYE_DAY
Market filter (a market token): bonded, MC $50k-$5M, liquidity >= $15k, volume 1 h >= $10k, at least 6 h old. An
event token only needs what every analysed token needs: bonded and MC >= $30k (CLAUDE.md). A token that fails waits
(next_ts) by its reason: under 30k a day, on the curve 6 h, otherwise 1-2 h; too young until it is 6 h old.

Price series: DexScreener /tokens batches (free, 30 tokens a request, data.fetch_pairs) stored as range.db snaps,
the same table the signal pass writes: the HOT_N (100) most important tokens every HOT_EVERY_S (5 min), the rest
every COLD_EVERY_S (15 min). Order: active ranges near the bottom (entry close), event tokens, then 1 h volume. A
token the hype scan snapshotted in the last 150 s is not asked again (its token_pulse rows are merged by
data.series). A token of the signal pass is left to it (one snapshot a minute). Minute OHLCV from GeckoTerminal for
300 tokens would be ~28,800 requests a day: impossible inside 3000; a GeckoTerminal seed is spent only on a token
close to an entry (run_range.py, inside RANGE_GT_DAY and MKT_SEED_DAY).

Budget per source per UTC day (env-overridable), hour-sliced (by the end of hour h at most cap * (h + 1) / 24), so a
busy morning never spends the night's share. When a pass needs more DexScreener requests than its slice allows, the
LOWEST-volume due tokens are dropped first (the refresh order is by volume) and that is logged. At the first pass of
a new day one line per source: "range watchlist trošak (dan): dexscreener N/cap, ...".
Estimate at 400 watched: 100 x 288 / 30 + 300 x 96 / 30 = ~2,100 requests a day for the series (less what the hype
scan already snapshots), plus discovery (<= DISC_REQ_PASS a pass and its own DISC_DAY 600, so it never eats the
refresh's share) = at most ~2,700 a day under DEX_DAY 3000, ~2 a minute against DexScreener's 300 a minute (a pass
sends at most MAX_REQ_PASS 20).
Nothing here trades. range_dca may enter a market / event token only on the demo account (paper), while its flag
(range_market / event_tokens) is paper; never on the real account (rangedca/trade.py).
"""
import os
import sqlite3
import time

from . import data

MARKET_MAX = int(os.environ.get("RANGE_MARKET_MAX", "400"))
MIN_MCAP = float(os.environ.get("RANGE_MKT_MIN_MCAP", "50000"))
MAX_MCAP = float(os.environ.get("RANGE_MKT_MAX_MCAP", "5000000"))
MIN_LIQ = float(os.environ.get("RANGE_MKT_MIN_LIQ", "15000"))   # 11.11. owner rule B: = trade/cost.LIQ_HARD_MIN
MIN_VOL_H1 = float(os.environ.get("RANGE_MKT_MIN_VOL_H1", "10000"))
MIN_AGE_H = float(os.environ.get("RANGE_MKT_MIN_AGE_H", "6"))
HOT_N = int(os.environ.get("RANGE_MKT_HOT_N", "100"))
HOT_EVERY_S = 300
COLD_EVERY_S = 900
SLACK_S = 30              # the pass runs every 60 s: a token due within 30 s is taken now
DEX_DAY = int(os.environ.get("RANGE_MKT_DEX_DAY", "4000"))
DISC_DAY = int(os.environ.get("RANGE_MKT_DISC_DAY", "1500"))   # of DEX_DAY at most this for discovery (the rest refreshes)
LISTS_DAY = int(os.environ.get("RANGE_MKT_LISTS_DAY", "300"))
GT_DAY = int(os.environ.get("RANGE_MKT_GT_DAY", "130"))
# 11.11. (Jure: "watchlist 300+", faza 1): after 40 min the list held 8 market tokens: PumpPortal migrations mostly die
# under 50k and one page of GeckoTerminal's top pools (20) an hour found almost nothing else. Now GT_TOP_PAGES pages of
# the top pools by 24 h volume + GT_TREND_PAGES of trending (1 h and 6 h) every GT_EVERY_S: 20 pools a request, their
# numbers admit a pool without a DexScreener request. ~10 requests every 2 h = ~120 a day of the shared 3000.
GT_TOP_PAGES = int(os.environ.get("RANGE_MKT_GT_PAGES", "6"))
GT_TREND_PAGES = int(os.environ.get("RANGE_MKT_GT_TREND_PAGES", "2"))
# a watched token stays while it keeps these (admission needs MIN_VOL_H1 / MIN_LIQ): one quiet hour no longer drops it
KEEP_VOL_H1 = float(os.environ.get("RANGE_MKT_KEEP_VOL_H1", "5000"))
KEEP_LIQ = float(os.environ.get("RANGE_MKT_KEEP_LIQ", "15000"))
BIRDEYE_DAY = int(os.environ.get("RANGE_MKT_BIRDEYE_DAY", "24"))
SEED_DAY = int(os.environ.get("RANGE_MKT_SEED_DAY", "20"))   # GeckoTerminal seeds of market / event tokens (in GT_DAY 60)
MAX_REQ_PASS = 30         # DexScreener /tokens requests in one pass (refresh + discovery)
# 11.11. 09:48 (faza 1, dijagnostika): 4,627 in the universe, 2,748 due for a check, 10 watched: 3 requests a pass
# (90 tokens) could not clear the backlog of PumpPortal migrations; DexScreener is free (300 a minute)
DISC_REQ_PASS = int(os.environ.get("RANGE_MKT_DISC_PASS", "10"))   # of them at most this many for discovery
LISTS_EVERY_S = 900
GT_EVERY_S = 7200
BIRD_EVERY_S = 7200
NO_PRICE_WAIT_S = 3 * 86400   # 11.11.: 1,244 dead migrations were asked again every 6 h
KEEP_SNAPS_DAYS = 3       # snapshots of market-only tokens (7 for the signal pass)
MIN_ANALYSED = data.MIN_MCAP   # 30k (CLAUDE.md)
WATCH_FLAG = {"market": "range_market", "event": "event_tokens"}   # never live: trade/settings.NEVER_LIVE
GT ="https://api.geckoterminal.com/api/v2/networks/solana"
CURVE_DEX = ("pumpfun", "pump-fun", "moonshot", "moonit", "launchlab", "raydium-launchlab", "letsbonk", "letsbonk-fun",
             "meteora-dbc")
DAY_KEYS = (("dexscreener", "mkt_dex_day", lambda: DEX_DAY),
            ("od toga otkrivanje", "mkt_disc_day", lambda: DISC_DAY),
            ("dexscreener liste", "mkt_lists_day", lambda: LISTS_DAY),
            ("gt", "mkt_gt_day", lambda: GT_DAY), ("birdeye", "mkt_bird_day", lambda: BIRDEYE_DAY))

SCHEMA = """
CREATE TABLE IF NOT EXISTS mkt (token TEXT PRIMARY KEY, via TEXT, src TEXT, first_seen INTEGER, checked_ts INTEGER,
    next_ts INTEGER, watched INTEGER DEFAULT 0, watched_ts INTEGER, last_snap INTEGER, symbol TEXT, mcap REAL, liq REAL,
    vol_h1 REAL, created_ts INTEGER, why TEXT);
CREATE INDEX IF NOT EXISTS mkt_due ON mkt (watched, next_ts);
"""


def ensure(con):
    con.executescript(SCHEMA)


class Net:
    """The network seams (the offline tests pass their own). pairs: DexScreener /tokens through data.fetch_pairs."""

    def __init__(self, fetch=None):
        self._fetch = fetch

    def pairs(self, tokens):
        return (self._fetch or data.fetch_pairs)(tokens)

    def lists(self):
        from dexscreener import client
        out = []
        for fn in (client.latest_token_profiles, client.latest_boosts, client.top_boosts):
            try:
                out += list(fn() or [])
            except Exception:  # noqa: BLE001 - discovery is best effort
                pass
        return out

    def gt_pools(self, n_req=None):
        """Trending (1 h, 6 h) and the top pools by 24 h volume, page by page, at most n_req requests. None when
        another job holds the shared GeckoTerminal host (11.11.: the first round got 0 pools from 10 requests that
        way): nothing was asked, the round waits for a free minute."""
        from event_calendar import http
        if http.reserved_by_other(f"{GT}/pools") > 0:
            return None
        out = []
        reqs = [("/trending_pools", {"page": pg, "duration": d}) for d in ("1h", "6h") for pg in range(1, GT_TREND_PAGES + 1)]
        reqs += [("/pools", {"page": pg, "sort": "h24_volume_usd_desc"}) for pg in range(1, GT_TOP_PAGES + 1)]
        for path, params in reqs[:n_req if n_req is not None else len(reqs)]:
            try:
                d = http.get_json(f"{GT}{path}", params, ttl=600, headers={"Accept": "application/json"}, retries=1)
                out += list((d or {}).get("data") or [])
            except Exception:  # noqa: BLE001
                pass
        return out

    def birdeye_list(self):
        key = os.environ.get("BIRDEYE_API_KEY")
        if not key:
            return None
        import urllib.parse
        import urllib.request
        from event_calendar import http
        url = "https://public-api.birdeye.so/defi/tokenlist?" + urllib.parse.urlencode(
            {"sort_by": "v24hUSD", "sort_type": "desc", "offset": 0, "limit": 50, "min_liquidity": int(MIN_LIQ)})
        req = urllib.request.Request(url, headers={"X-API-KEY": key, "x-chain": "solana", "Accept": "application/json",
                                                   "User-Agent": http.USER_AGENT})
        d = http._fetch(req, 20, retries=1)
        return list(((d or {}).get("data") or {}).get("tokens") or [])


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _meter(service, method, n=1):
    try:
        from usage import meter
        meter.record(service, method, 0.0, calls=n)
    except Exception:  # noqa: BLE001
        pass


# ---------- budget ------------------------------------------------------------------------------------------------------

def slice_left(con, key, cap, now):
    """Requests this source may still make now: by the end of UTC hour h at most cap * (h + 1) / 24 in total."""
    hour = int(now % 86400 // 3600)
    return max(0, min(cap, int(cap * (hour + 1) / 24)) - data.day_used(con, key, now))


def spend_line(con, now, log=print):
    """At the first pass of a new UTC day: one line with every source's use of the day that ended (the counters
    still hold that day). Also the signal pass's own DexScreener polls and GeckoTerminal seeds."""
    today = data._day(now)
    last = data.kv_get(con, "mkt_spend_day")
    if last == today:
        return None
    data.kv_put(con, "mkt_spend_day", today)
    if not last:
        return None

    def used(key):
        return int((data.kv_get(con, key) or {}).get(last, 0))
    parts = [f"{name} {used(key)}/{cap()}" + (" (bez ključa)" if key == "mkt_bird_day" and not os.environ.get("BIRDEYE_API_KEY")
                                              else "") for name, key, cap in DAY_KEYS]
    line = (f"range watchlist trošak ({last}): " + ", ".join(parts)
            + f"; signalni prolaz dexscreener {used('sig_dex_day')}, gt sjeme {used('gt_day')}/{data.GT_DAY} "
              f"(tržište {used('mkt_seed_day')}/{SEED_DAY}), helius {used('helius_day')} kredita; iz hype skena bez "
              f"troška {used('mkt_reuse_day')} snimki")
    log(line)
    return line


# ---------- filters -------------------------------------------------------------------------------------------------------

def check(s, created_ts, src, now, keep=False):
    """(ok, why, wait_s) of one snapshot (data.snap_of shape) against the filter of its source. keep: a token already
    watched stays with the softer KEEP_VOL_H1 / KEEP_LIQ (11.11.: one quiet hour dropped it at once)."""
    if not s or not s.get("price"):
        return False, "nema cijene na DexScreeneru", NO_PRICE_WAIT_S
    if not s.get("bonded"):
        return False, "još na krivulji (uzimaju se bondani)", 6 * 3600
    mc = s.get("mcap") or 0
    if mc < MIN_ANALYSED:
        return False, "MC ispod 30k (ne analizira se)", 86400
    if src == "event":
        return True, "", 0
    if mc < MIN_MCAP:
        return False, f"MC ${mc:,.0f} ispod ${MIN_MCAP:,.0f}", 2 * 3600
    if mc > MAX_MCAP:
        return False, f"MC ${mc:,.0f} iznad ${MAX_MCAP:,.0f}", 86400
    if (s.get("liq") or 0) < (KEEP_LIQ if keep else MIN_LIQ):
        return False, f"likvidnost ${s.get('liq') or 0:,.0f}", 2 * 3600
    if (s.get("vol_h1") or 0) < (KEEP_VOL_H1 if keep else MIN_VOL_H1):
        return False, f"volumen 1 h ${s.get('vol_h1') or 0:,.0f}", 3600
    if created_ts and now - created_ts < MIN_AGE_H * 3600:
        return False, f"mlađi od {MIN_AGE_H:g} h", int(created_ts + MIN_AGE_H * 3600 - now) + 60
    return True, "", 0


# ---------- universe --------------------------------------------------------------------------------------------------

def add(con, tok, via, now, src="market", symbol=None, created_ts=None, due=None, nums=None):
    """A token into the universe (or one more `via` for a known one). An event token is marked src 'event' and is due
    at once."""
    r = con.execute("SELECT via, src, next_ts, watched FROM mkt WHERE token=?", (tok,)).fetchone()
    nums = nums or {}
    if r is None:
        con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, symbol, mcap, liq, vol_h1, created_ts) "
                    "VALUES (?,?,?,?,?,0,?,?,?,?,?)", (tok, via, src, int(now), int(due if due is not None else now),
                                                       symbol, nums.get("mcap"), nums.get("liq"), nums.get("vol_h1"),
                                                       int(created_ts) if created_ts else None))
        return True
    vias = set((r[0] or "").split(",")) - {""}
    upd = {}
    if via not in vias:
        upd["via"] = ",".join(sorted(vias | {via}))
    if src == "event" and r[1] != "event":
        upd["src"] = "event"
        if not r[3]:
            upd["next_ts"] = int(now)
    if created_ts:
        upd["created_ts"] = int(created_ts)
    for k in ("mcap", "liq", "vol_h1"):
        if nums.get(k) is not None:
            upd[k] = nums[k]
    if upd:
        con.execute(f"UPDATE mkt SET {', '.join(k + '=?' for k in upd)} WHERE token=?", (*upd.values(), tok))
    return False


def _ro(path):
    return data._ro_file(path)


def from_migrations(con, now, hype_db=None):
    wm = data.kv_get(con, "mkt_wm_mig") or 0
    hc = _ro(hype_db or data.hype_path())
    n = 0
    if hc is None:
        return 0
    try:
        for mint, ts, sym in hc.execute("SELECT mint, ts, symbol FROM live_launches WHERE pool='migration' AND ts > ? "
                                        "ORDER BY ts", (int(wm),)):
            n += add(con, mint, "migracija", now, symbol=sym or None, created_ts=ts,
                     due=max(now, ts + MIN_AGE_H * 3600))
            wm = max(wm, ts)
    except sqlite3.Error:
        pass
    finally:
        hc.close()
    data.kv_put(con, "mkt_wm_mig", wm)
    return n


def from_graduates(con, now):
    try:
        from kol import store as kstore
        kc = _ro(kstore.DB)
    except Exception:  # noqa: BLE001
        kc = None
    if kc is None:
        return 0
    wm = data.kv_get(con, "mkt_wm_grad") or 0
    n = 0
    try:
        for tok, sym, created, first in kc.execute("SELECT token, symbol, created_ts, first_seen FROM graduates WHERE "
                                                   "first_seen > ? ORDER BY first_seen", (int(wm),)):
            n += add(con, tok, "graduates", now, symbol=sym, created_ts=created,
                     due=max(now, (created or now) + MIN_AGE_H * 3600))
            wm = max(wm, first or 0)
    except sqlite3.Error:
        pass
    finally:
        kc.close()
    data.kv_put(con, "mkt_wm_grad", wm)
    return n


def from_scanner(con, now, scan_db=None):
    """scan.db cand rows priced in the last 10 min that pass the market filter's numbers (free; seen by the scanner
    for 6 h or more counts as old enough)."""
    try:
        from scan import store as sstore
        sc = _ro(scan_db or sstore.db_path())
    except Exception:  # noqa: BLE001
        sc = None
    if sc is None:
        return 0
    n = 0
    try:
        for tok, sym, first, mc, liq, v1, stage in sc.execute(
                "SELECT token, symbol, first_seen, mcap, liq, vol_h1, stage FROM cand WHERE checked_ts >= ? AND mcap >= ? "
                "AND mcap <= ? AND liq >= ? AND vol_h1 >= ?", (int(now - 600), MIN_MCAP, MAX_MCAP, MIN_LIQ, MIN_VOL_H1)):
            if stage in ("final_stretch", "curve"):
                continue
            n += add(con, tok, "skener", now, symbol=sym, nums={"mcap": mc, "liq": liq, "vol_h1": v1})
    except sqlite3.Error:
        pass
    finally:
        sc.close()
    return n


def from_events(con, now, topics_db=None):
    """The main / other tokens of the active event topics (topics.db), src 'event'."""
    try:
        from topics import store as tstore
        tc = tstore.ro(topics_db)
    except Exception:  # noqa: BLE001
        tc = None
    if tc is None:
        return set()
    try:
        toks = tstore.active_tokens(tc)
    except sqlite3.Error:
        toks = {}
    finally:
        tc.close()
    for tok in toks:
        add(con, tok, "event", now, src="event")
    # an event token whose topic ended (or whose role became clone / rug) is a market token again or leaves
    for (tok,) in con.execute("SELECT token FROM mkt WHERE src='event'").fetchall():
        if tok not in toks:
            con.execute("UPDATE mkt SET src='market' WHERE token=?", (tok,))
    return set(toks)


def gt_row(p):
    """A GeckoTerminal pool -> (token, symbol, created_ts, snapshot dict like data.snap_of), or None."""
    a = p.get("attributes") or {}
    rel = p.get("relationships") or {}
    tok = (((rel.get("base_token") or {}).get("data") or {}).get("id") or "").split("_", 1)[-1]
    dex = ((rel.get("dex") or {}).get("data") or {}).get("id") or ""
    if not tok:
        return None
    vol = a.get("volume_usd") or {}
    liq = _f(a.get("reserve_in_usd")) or 0.0
    created = None
    if a.get("pool_created_at"):
        try:
            from datetime import datetime
            created = int(datetime.fromisoformat(str(a["pool_created_at"]).replace("Z", "+00:00")).timestamp())
        except ValueError:
            created = None
    s = {"price": _f(a.get("base_token_price_usd")), "mcap": _f(a.get("market_cap_usd")) or _f(a.get("fdv_usd")),
         "liq": liq, "vol_h1": _f(vol.get("h1")) or 0.0, "bonded": bool(liq > 0 and dex not in CURVE_DEX)}
    return tok, (a.get("name") or "").split(" / ")[0][:20] or None, created, s


def cg_day_text(con, now):
    """The shared CoinGecko day in one phrase: the key's calls today of CG_DAILY_CALLS (all jobs) and the range list's
    own GT requests of GT_DAY; without the key, the free GeckoTerminal."""
    own = f"range lista {data.day_used(con, 'mkt_gt_day', now)}/{GT_DAY}"
    try:
        from event_calendar import http
        if not http._cg_key_raw():
            return f"CoinGecko bez ključa (besplatni GT), {own}"
        used, cap = http.cg_used()
        lim = http.cg_limit(cap)
        note = (" (potrošen: ostatak dana besplatni GT)" if used >= cap else
                f" (noćni strop {lim} dosegnut: do 06:00 besplatni GT)" if used >= lim else "")
        return f"CoinGecko ključ danas {used}/{cap}{note}, {own}"
    except Exception:  # noqa: BLE001
        return own


def gt_requests():
    """GeckoTerminal requests of one discovery round (trending 1 h + 6 h pages, top-volume pages)."""
    return 2 * GT_TREND_PAGES + GT_TOP_PAGES


def discover_lists(con, now, net, log):
    """DexScreener lists, GeckoTerminal pools and Birdeye's list, each on its own cadence and day cap."""
    n = 0
    if now - (data.kv_get(con, "mkt_lists_ts") or 0) >= LISTS_EVERY_S and slice_left(con, "mkt_lists_day", LISTS_DAY, now) >= 3:
        data.kv_put(con, "mkt_lists_ts", int(now))
        data.day_add(con, "mkt_lists_day", 3, now)
        _meter("dexscreener", "range tržište liste", 3)
        for it in net.lists() or []:
            if isinstance(it, dict) and it.get("chainId") == "solana" and it.get("tokenAddress"):
                n += add(con, it["tokenAddress"], "dex_liste", now)
    gt_req = gt_requests()
    left = slice_left(con, "mkt_gt_day", GT_DAY, now)
    pools = None
    if now - (data.kv_get(con, "mkt_gt_ts") or 0) >= GT_EVERY_S and left >= 2:
        n_req = min(gt_req, left)
        try:
            pools = net.gt_pools(n_req)
        except TypeError:   # an injected net without the n_req argument (tests of the first version)
            pools = net.gt_pools()
        if pools is None:   # the host is held by another job: not charged, asked again next pass
            if now - (data.kv_get(con, "mkt_gt_busy_log") or 0) >= 3600:
                data.kv_put(con, "mkt_gt_busy_log", int(now))
                log("range tržište GT: GeckoTerminal drži drugi posao, runda čeka slobodnu minutu")
        else:
            data.kv_put(con, "mkt_gt_ts", int(now))
            data.day_add(con, "mkt_gt_day", n_req, now)
            _meter("coingecko", "range tržište", n_req)
    if pools is not None:
        got = ok_n = new_n = 0
        for p in pools or []:
            g = gt_row(p) if isinstance(p, dict) else None
            if not g:
                continue
            got += 1
            tok, sym, created, s = g
            ok, why, wait = check(s, created, "market", now)
            ok_n += int(ok)
            k = add(con, tok, "gt", now, symbol=sym, created_ts=created, due=now if ok else now + wait,
                    nums={"mcap": s["mcap"], "liq": s["liq"], "vol_h1": s["vol_h1"]})
            new_n += k
            n += k
        real = ""
        if got:   # 11.11. (Jure): more GT pages only if the shared day has room after the first two real rounds
            k = int(data.kv_get(con, "mkt_gt_real") or 0) + 1
            data.kv_put(con, "mkt_gt_real", k)
            real = f" (prava runda {k})" if k <= 2 else ""
        log(f"range tržište GT: {n_req} upita, {got} poolova, novih {new_n}, prolazi filter {ok_n}{real}; {cg_day_text(con, now)}")
    if (os.environ.get("BIRDEYE_API_KEY") and now - (data.kv_get(con, "mkt_bird_ts") or 0) >= BIRD_EVERY_S
            and slice_left(con, "mkt_bird_day", BIRDEYE_DAY, now) >= 1):
        data.kv_put(con, "mkt_bird_ts", int(now))
        data.day_add(con, "mkt_bird_day", 1, now)
        _meter("birdeye", "range tržište")
        try:
            for t in net.birdeye_list() or []:
                if isinstance(t, dict) and t.get("address"):
                    mc = _f(t.get("mc"))
                    n += add(con, t["address"], "birdeye", now, symbol=t.get("symbol"),
                             nums={"mcap": mc, "liq": _f(t.get("liquidity"))})
        except Exception as e:  # noqa: BLE001
            log(f"range tržište: Birdeye: {type(e).__name__}")
    return n


# ---------- the pass ----------------------------------------------------------------------------------------------------

def _near_entry(con):
    """{token: pos_pct} of active ranges in the bottom 40 % (entry close): refreshed every 5 min first."""
    out = {}
    for tok, pos in con.execute("SELECT token, pos_pct FROM ranges WHERE active=1 AND pos_pct IS NOT NULL AND pos_pct <= 40"):
        out[tok] = pos
    return out


def order(rows, near, open_toks=()):
    """The refresh order: open positions, active ranges near the bottom, event tokens, then the 1 h volume (highest
    first). rows: [(token, src, vol_h1)]."""
    return sorted(rows, key=lambda r: (r[0] not in open_toks, r[0] not in near, r[1] != "event", -(r[2] or 0), r[0]))


def watched(con):
    return [r[0] for r in con.execute("SELECT token FROM mkt WHERE watched=1")]


def _store(con, tok, s, now, src, created_ts, keep, watched=False):
    """Store a fresh snapshot of a watched / candidate token; returns (ok, why, wait). watched: the softer keep
    thresholds of check()."""
    ok, why, wait = check(s, created_ts, src, now, keep=watched)
    if s and s.get("price") and s.get("bonded") and (s.get("mcap") or 0) >= MIN_ANALYSED:
        data.save_snap(con, tok, s)
    if keep:
        ok, why = True, ""
    con.execute("UPDATE mkt SET checked_ts=?, last_snap=?, mcap=?, liq=?, vol_h1=?, symbol=COALESCE(?, symbol), "
                "why=? WHERE token=?", (int(now), int(now) if s else None, (s or {}).get("mcap"), (s or {}).get("liq"),
                                         (s or {}).get("vol_h1"), (s or {}).get("symbol"), why or None, tok))
    return ok, why, wait


def _created(pairs):
    """{token: the oldest pairCreatedAt of its pairs, unix s}."""
    out = {}
    for p in pairs or []:
        t = (p.get("baseToken") or {}).get("address")
        c = p.get("pairCreatedAt")
        if t and c:
            c = int(c / 1000)
            out[t] = min(out.get(t, c), c)
    return out


def pass_once(con, now, net=None, log=print, signal=(), pulse=None, market_on=True, event_on=True, open_toks=(),
              hype_db=None, scan_db=None, topics_db=None):
    """One pass: discovery, refresh of the due watched tokens within the budget, admission of due universe tokens.
    Returns {"tokens": watched tokens in refresh order, "src": {token: market | event}, "stats": {...}}."""
    ensure(con)
    now = int(now)
    net = net or Net()
    spend_line(con, now, log)
    stats = {"refreshed": 0, "reused": 0, "dropped": 0, "admitted": 0, "left": 0, "requests": 0, "new": 0}
    if market_on:
        stats["new"] += from_migrations(con, now, hype_db) + from_graduates(con, now) + from_scanner(con, now, scan_db)
        stats["new"] += discover_lists(con, now, net, log)
    ev = from_events(con, now, topics_db) if event_on else set()
    if not event_on:
        con.execute("UPDATE mkt SET src='market' WHERE src='event'")
    if not market_on:   # event tokens only: the market part of the list rests
        con.execute("UPDATE mkt SET watched=0 WHERE watched=1 AND src!='event'")
    signal = set(signal)
    pulse = set(pulse if pulse is not None else data.pulse_recent(now))
    open_toks = set(open_toks)
    near = _near_entry(con)
    rows = con.execute("SELECT token, src, vol_h1, last_snap FROM mkt WHERE watched=1").fetchall()
    ordered = order([(t, s, v) for t, s, v, _l in rows], near, open_toks)
    last = {t: l for t, _s, _v, l in rows}
    srcs = {t: s for t, s, _v in ordered}
    hot = {t for t, _s, _v in ordered[:HOT_N]}
    due = []
    for t, s, v in ordered:
        if t in signal:
            continue   # the signal pass snapshots it every minute
        every = HOT_EVERY_S if t in hot else COLD_EVERY_S
        if now - (last.get(t) or 0) < every - SLACK_S:
            continue
        if t in pulse:   # the hype scan snapshotted it in the last 150 s: its token_pulse rows are the series
            stats["reused"] += 1
            con.execute("UPDATE mkt SET last_snap=? WHERE token=?", (int(now), t))
            continue
        due.append(t)
    if stats["reused"]:
        data.day_add(con, "mkt_reuse_day", stats["reused"], now)
    allowed = min(MAX_REQ_PASS, slice_left(con, "mkt_dex_day", DEX_DAY, now))
    need = -(-len(due) // 30)
    if need > allowed:
        keep = due[:allowed * 30]
        stats["dropped"] = len(due) - len(keep)
        if now - (data.kv_get(con, "mkt_drop_log") or 0) >= 600:
            data.kv_put(con, "mkt_drop_log", int(now))
            log(f"range tržište: strop DexScreenera ({data.day_used(con, 'mkt_dex_day', now)}/{DEX_DAY} danas, ovaj sat "
                f"još {allowed} upita): preskočeno {stats['dropped']} tokena najmanjeg volumena")
        due = keep
    if due:
        n_req = -(-len(due) // 30)
        data.day_add(con, "mkt_dex_day", n_req, now)
        _meter("dexscreener", "range tržište", n_req)
        stats["requests"] += n_req
        pairs = net.pairs(due) or []
        best = data.best_pairs(pairs)
        made = _created(pairs)
        for t in due:
            p = best.get(t)
            s = data.snap_of(p, now) if p else None
            src = srcs.get(t, "market")
            ok, why, wait = _store(con, t, s, now, src, made.get(t), t in open_toks, watched=True)
            if made.get(t):
                con.execute("UPDATE mkt SET created_ts=? WHERE token=?", (made[t], t))
            stats["refreshed"] += int(bool(s))
            if not ok:
                con.execute("UPDATE mkt SET watched=0, next_ts=?, why=? WHERE token=?", (int(now + wait), why, t))
                stats["left"] += 1
    # admission: due universe tokens (event tokens first, then the known volume), within the discovery share
    n_w = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=1").fetchone()[0]
    room = min(DISC_REQ_PASS, MAX_REQ_PASS - stats["requests"], slice_left(con, "mkt_dex_day", DEX_DAY, now),
               slice_left(con, "mkt_disc_day", DISC_DAY, now))   # discovery never eats the refresh's share
    if room > 0:
        cond = "" if market_on else " AND src='event'"
        cand = [r for r in con.execute(
            f"SELECT token, src, vol_h1, created_ts FROM mkt WHERE watched=0 AND next_ts <= ?{cond} "
            f"ORDER BY src='event' DESC, COALESCE(vol_h1, 0) DESC, first_seen DESC LIMIT ?", (int(now), room * 30))
            if r[0] not in signal]
        if cand:
            n_req = -(-len(cand) // 30)
            data.day_add(con, "mkt_dex_day", n_req, now)
            data.day_add(con, "mkt_disc_day", n_req, now)
            _meter("dexscreener", "range tržište otkrivanje", n_req)
            stats["requests"] += n_req
            pairs = net.pairs([r[0] for r in cand]) or []
            best = data.best_pairs(pairs)
            made = _created(pairs)
            for tok, src, _v, created in cand:
                p = best.get(tok)
                s = data.snap_of(p, now) if p else None
                created = made.get(tok) or created
                ok, why, wait = _store(con, tok, s, now, src, created, False)
                if created:
                    con.execute("UPDATE mkt SET created_ts=? WHERE token=?", (created, tok))
                if not ok:
                    con.execute("UPDATE mkt SET next_ts=? WHERE token=?", (int(now + wait), tok))
                    continue
                if n_w >= MARKET_MAX:   # full: a newcomer replaces the quietest market token when it trades more
                    low = con.execute("SELECT token, vol_h1 FROM mkt WHERE watched=1 AND src='market' ORDER BY "
                                      "COALESCE(vol_h1, 0) LIMIT 1").fetchone()
                    if not low or (src != "event" and (low[1] or 0) >= ((s or {}).get("vol_h1") or 0)) or low[0] in open_toks:
                        con.execute("UPDATE mkt SET next_ts=?, why=? WHERE token=?", (int(now + 3600), "lista puna", tok))
                        continue
                    con.execute("UPDATE mkt SET watched=0, next_ts=?, why=? WHERE token=?",
                                (int(now + 3600), "istisnut: najmanji volumen na punoj listi", low[0]))
                    n_w -= 1
                con.execute("UPDATE mkt SET watched=1, watched_ts=? WHERE token=?", (int(now), tok))
                n_w += 1
                stats["admitted"] += 1
    con.commit()
    universe_line(con, now, log)
    rows = con.execute("SELECT token, src, vol_h1 FROM mkt WHERE watched=1").fetchall()
    ordered = order(rows, near, open_toks)[:MARKET_MAX]
    stats["watched"] = len(ordered)
    stats["events"] = sum(1 for _t, s, _v in ordered if s == "event")
    return {"tokens": [t for t, _s, _v in ordered], "src": {t: s for t, s, _v in ordered}, "stats": stats,
            "event_tokens": ev}


def universe_line(con, now, log=print, every_s=3600):
    """Once an hour (11.11., faza 1: why the list stays short): the universe by source, watched / waiting, and the
    commonest reasons a token is not watched."""
    if now - (data.kv_get(con, "mkt_uni_log") or 0) < every_s:
        return None
    data.kv_put(con, "mkt_uni_log", int(now))
    vias = {}
    for via, n in con.execute("SELECT via, COUNT(*) FROM mkt GROUP BY via"):
        for v in (via or "?").split(","):
            vias[v] = vias.get(v, 0) + n
    w = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=1").fetchone()[0]
    due = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=0 AND next_ts <= ?", (int(now),)).fetchone()[0]
    wait = con.execute("SELECT COUNT(*) FROM mkt WHERE watched=0 AND next_ts > ?", (int(now),)).fetchone()[0]
    whys = {}
    for why, n in con.execute("SELECT why, COUNT(*) FROM mkt WHERE watched=0 AND why IS NOT NULL GROUP BY why"):
        k = (why or "").split(" $")[0].split(" (")[0]
        whys[k] = whys.get(k, 0) + n
    top = ", ".join(f"{k} {n}" for k, n in sorted(whys.items(), key=lambda kv: -kv[1])[:6])
    text = (f"range tržište svemir: {sum(1 for _ in con.execute('SELECT 1 FROM mkt'))} tokena "
            f"({', '.join(f'{k} {n}' for k, n in sorted(vias.items(), key=lambda kv: -kv[1]))}); prati {w}, čeka provjeru "
            f"{due}, odgođeno {wait}; razlozi: {top or '-'}")
    log(text)
    return text


def prune(con, now, keep_tokens=()):
    """Universe rows not watched and not seen for 7 days; snapshots of market-only tokens older than KEEP_SNAPS_DAYS
    (the signal pass's tokens and open rounds keep data.KEEP_DAYS)."""
    ensure(con)
    con.execute("DELETE FROM mkt WHERE watched=0 AND COALESCE(checked_ts, first_seen) < ?", (int(now - 7 * 86400),))
    keep = list(keep_tokens)
    q = f" AND token NOT IN ({','.join('?' * len(keep))})" if keep else ""
    con.execute(f"DELETE FROM snaps WHERE ts < ? AND token IN (SELECT token FROM mkt){q}",
                (int(now - KEEP_SNAPS_DAYS * 86400), *keep))
    con.commit()


def cost_today(con, now):
    """{source: {"used", "cap"}} of today, for get_range_candidates and run_range.py status."""
    out = {name: {"used": data.day_used(con, key, now), "cap": cap()} for name, key, cap in DAY_KEYS}
    out["gt sjeme (tržište)"] = {"used": data.day_used(con, "mkt_seed_day", now), "cap": SEED_DAY}
    out["dexscreener signalni prolaz"] = {"used": data.day_used(con, "sig_dex_day", now), "cap": None}
    out["iz hype skena (besplatno)"] = {"used": data.day_used(con, "mkt_reuse_day", now), "cap": None}
    return out


def counts(con):
    """{"market": n, "event": n} of watched tokens."""
    try:
        return {s: n for s, n in con.execute("SELECT src, COUNT(*) FROM mkt WHERE watched=1 GROUP BY src")}
    except sqlite3.Error:
        return {}


def info(path=None, now=None):
    """Read-only: (counts, cost_today) for the MCP view; ({}, {}) without range.db or the table."""
    con = data.ro(path)
    if con is None:
        return {}, {}
    try:
        return counts(con), cost_today(con, now or time.time())
    except sqlite3.Error:
        return {}, {}
    finally:
        con.close()


def dump(con):
    """For run_range.py status: the watched tokens, most traded first."""
    return [dict(zip(("token", "src", "symbol", "mcap", "liq", "vol_h1", "last_snap", "via"), r)) for r in con.execute(
        "SELECT token, src, symbol, mcap, liq, vol_h1, last_snap, via FROM mkt WHERE watched=1 ORDER BY vol_h1 DESC")]
