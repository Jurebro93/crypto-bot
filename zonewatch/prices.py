"""The numbers of a watched token, cheapest first (CLAUDE.md: measure, reuse, cap).

  1. snapshots the bot already stores: range.db snaps (the range engine's candidates and the market watchlist,
     every 1 / 5 / 15 min) and hype.db token_pulse (the hype scan, ~2 min); plus px, this job's own last fetch
  2. one DexScreener /tokens batch (free, 30 tokens a request; dexscreener/client.tokens_live: the scanners' rate
     limiter and cache, but 5 s timeout and no retry, so DexScreener trouble never holds the 30 s loop) only for
       near       tokens within NEAR (10 %) of a zone: when their newest number is older than FAST_S (30 s)
       armed      hand-armed tokens (manual / event) and tokens without any number: older than FRESH_S (60 s)
       far        range tokens far from every zone: older than SLOW_S (5 min)
     at most MAX_REQ_PASS (4) requests a pass (DexScreener's 300 a minute is per IP and shared by every process) and
     ZONEWATCH_DEX_DAY (3000) a UTC day, spread over the day (by second s at most cap x (s + 60) / 86400), near tokens
     first; a request that goes out anyway is filled up with the stalest other tokens (no extra cost).
Unique traders of the last hour only from what is stored (hype.db live_trades, the PumpPortal stream; null when the
stream does not cover the token); the rug verdict from ui/kandidati.rug_view on that one token, cached RUG_TTL_S.
"""
import os
import sqlite3
import time

from zonewatch import store, zones


def _env_i(name, default, lo, hi):
    try:
        v = int(float(os.environ.get(name) or default))
    except ValueError:
        v = default
    return min(hi, max(lo, v))


FAST_S = _env_i("ZONEWATCH_FAST_S", 30, 10, 600)
FRESH_S = _env_i("ZONEWATCH_FRESH_S", 60, 10, 900)
SLOW_S = _env_i("ZONEWATCH_SLOW_S", 300, 60, 3600)
STALE_S = _env_i("ZONEWATCH_STALE_S", 900, 120, 7200)   # older numbers are not evaluated (no state change, no alarm)
DEX_DAY = _env_i("ZONEWATCH_DEX_DAY", 3000, 0, 100_000)
MAX_REQ_PASS = _env_i("ZONEWATCH_MAX_REQ", 4, 0, 4)
BATCH = 30
SLACK_S = 5          # the loop runs every 30 s: a number 25 s old is due now
RUG_TTL_S = 900
COLD_S = 900          # a token DexScreener did not return is asked again after 15 min
PP_COVER = 0.5       # PumpPortal trades of the last 5 min >= this share of DexScreener's txns m5: it covers the token
FIELDS = ("ts", "price", "mcap", "liq", "vol_m5", "vol_h1", "buys_m5", "sells_m5", "buys_h1", "sells_h1")


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _range_path():
    from rangedca import data
    return data.db_path()


def _hype_path():
    from rangedca import data
    return data.hype_path()


def _newest(con, sql, mints, src):
    out = {}
    if con is None:
        return out
    try:
        for m in mints:
            r = con.execute(sql, (m,)).fetchone()
            if r and r[0]:
                out[m] = dict(zip(FIELDS, r), src=src)
    except sqlite3.Error:
        pass
    return out


def latest(con, mints, range_path=None, hype_path=None):
    """{mint: newest snapshot dict (FIELDS + symbol + src)} over px (ours), range.db snaps and hype.db token_pulse;
    one primary-key lookup per mint and table."""
    mints = list(mints)
    out = {}
    for m, *vals in con.execute(f"SELECT mint, {', '.join(FIELDS)}, symbol FROM px WHERE mint IN "
                                f"({','.join('?' * len(mints))})", mints) if mints else []:
        out[m] = dict(zip(FIELDS + ("symbol",), vals), src="dexscreener")
    rc = _ro(range_path or _range_path())
    syms = {}
    try:
        got = _newest(rc, f"SELECT {', '.join(FIELDS)} FROM snaps WHERE token=? ORDER BY ts DESC LIMIT 1", mints, "range_snap")
        if rc is not None:
            try:
                syms = {m: s for m, s in rc.execute(f"SELECT token, symbol FROM pools WHERE token IN "
                                                    f"({','.join('?' * len(mints))})", mints)} if mints else {}
            except sqlite3.Error:
                syms = {}
    finally:
        if rc is not None:
            rc.close()
    hc = _ro(hype_path or _hype_path())
    try:
        pulse = _newest(hc, "SELECT ts, price, mcap, liquidity, vol_m5, vol_h1, buys_m5, sells_m5, buys_h1, sells_h1 "
                            "FROM token_pulse WHERE token=? ORDER BY ts DESC LIMIT 1", mints, "pulse")
    finally:
        if hc is not None:
            hc.close()
    for src in (got, pulse):
        for m, s in src.items():
            if m not in out or (s["ts"] or 0) > (out[m]["ts"] or 0):
                s["symbol"] = (out.get(m) or {}).get("symbol") or syms.get(m)
                out[m] = s
    for m, s in out.items():
        if not s.get("symbol") and syms.get(m):
            s["symbol"] = syms[m]
    return out


def plan(zs_by_mint, snaps, now, cold=None):
    """[(priority, distance, mint)] of the tokens to fetch now, most urgent first: 0 near a zone (newest number older
    than FAST_S), 1 hand-armed or without any number (older than FRESH_S), 2 range tokens far from every zone
    (older than SLOW_S); and {mint: priority} of every token for the fill-up. A token DexScreener did not know at
    the last ask (cold) is not asked again before its time."""
    due, prio = [], {}
    cold = cold or {}
    for m, zs in zs_by_mint.items():
        if (cold.get(m) or 0) > now:
            continue
        s = snaps.get(m)
        mc = (s or {}).get("mcap")
        age = now - (s or {}).get("ts", 0) if s and s.get("ts") else None
        dist, is_near = zones.near(zs, mc) if mc else (None, False)
        hand = any(z["source"] in zones.HAND for z in zs)
        if is_near:
            p, limit = 0, FAST_S - SLACK_S
        elif hand or age is None:
            p, limit = 1, FRESH_S - SLACK_S
        else:
            p, limit = 2, SLOW_S - SLACK_S
        prio[m] = (p, dist if dist is not None else 9.0)
        if age is None or age > limit:
            due.append((p, dist if dist is not None else 9.0, m))
    due.sort()
    return due, prio


def budget_left(con, now):
    """DexScreener requests still allowed now: the day cap spread evenly over the UTC day (by second s of the day at
    most cap x (s + 60) / 86400), so a busy hour never spends the night's share; what a quiet stretch left is kept."""
    sec = int(now) % 86400
    return max(0, int(DEX_DAY * (sec + 60) / 86400) - store.day_used(con, "dex", now))


def pick(due, prio, snaps, now, budget):
    """The mints of this pass's requests: the due ones (most urgent first) in at most `budget` requests of BATCH,
    the last request filled up with the stalest other tokens. Returns (mints, dropped due)."""
    n_req = min(budget, MAX_REQ_PASS, -(-len(due) // BATCH))
    if n_req <= 0:
        return [], len(due)
    take = [m for _, _, m in due][:n_req * BATCH]
    room = n_req * BATCH - len(take)
    if room > 0:
        rest = sorted((m for m in prio if m not in set(take)),
                      key=lambda m: -(now - ((snaps.get(m) or {}).get("ts") or 0)))
        take += [m for m in rest if now - ((snaps.get(m) or {}).get("ts") or 0) > SLACK_S][:room]
    return take, max(0, len(due) - n_req * BATCH)


def fetch_pairs(tokens):
    """DexScreener /tokens for up to 30 tokens a request through the live path (dexscreener/client.tokens_live: the
    shared per-IP rate limiter and HTTP cache, 5 s timeout, no retry); [] on any error (the stored snapshots serve
    this pass). rangedca/data.fetch_pairs is the same request on the scanners' path (30 s timeout, retries with
    back-off up to a minute), too slow for an alarm loop."""
    if not tokens:
        return []
    try:
        from dexscreener import client
        return client.tokens_live("solana", list(tokens), ttl=20) or []
    except Exception as e:  # noqa: BLE001 - never the URL or the message, only the class
        print(f"zonewatch: DexScreener nije odgovorio ({type(e).__name__})", flush=True)
        return []


def poll(con, mints, now, fetch=None):
    """One DexScreener /tokens batch per 30 mints (counted in kv day:dex before the call); stores px and returns
    {mint: snapshot}."""
    if not mints:
        return {}
    from rangedca import data
    store.day_add(con, "dex", -(-len(mints) // BATCH), now)
    con.commit()
    pairs = (fetch or fetch_pairs)(list(mints))
    got = {}
    for m, p in data.best_pairs(pairs).items():
        if m not in mints:
            continue
        s = data.snap_of(p, now)
        if not s.get("price"):
            continue
        row = {k: s.get(k) for k in FIELDS}
        row.update(symbol=s.get("symbol"), src="dexscreener")
        con.execute("INSERT OR REPLACE INTO px VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m, *[row[k] for k in FIELDS], row["symbol"], "dexscreener"))
        got[m] = row
    if pairs:   # an answer without some of the asked tokens: those wait COLD_S (a wrong or dead mint costs nothing)
        cold = {k: v for k, v in (store.kv_get(con, "cold") or {}).items() if v > now}
        cold.update({m: int(now + COLD_S) for m in mints if m not in got})
        store.kv_put(con, "cold", cold)
    con.commit()
    return got


def cold(con, now):
    return {k: v for k, v in (store.kv_get(con, "cold") or {}).items() if v > now}


def uniq_traders_1h(mint, now, txns_m5=None, path=None):
    """Distinct wallets that traded the token in the last hour, from hype.db live_trades (the PumpPortal stream we
    already store, free); None when the stream does not cover the token (under 20 trades in the hour, or its last 5
    minutes hold fewer than half the transactions DexScreener counted)."""
    con = _ro(path or _hype_path())
    if con is None:
        return None
    try:
        rows = con.execute("SELECT wallet, ts FROM live_trades WHERE mint=? AND ts>=? LIMIT 5000",
                           (mint, int(now - 3600))).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    r5 = sum(1 for _, ts in rows if ts > now - 300)
    if len(rows) < 20 or (txns_m5 and r5 < PP_COVER * txns_m5):
        return None
    return len({w for w, _ in rows if w})


_RUG = {}   # mint -> (monotonic time, level)


class _RugSrc:
    """ui/kandidati.rug_view's two reads for one token (the same as ui/mcpapi._RugSrc)."""

    def __init__(self, peaks):
        self.peaks = peaks or {}

    def collapse(self, token, mcap, liq):
        from rugfilter import collapse
        return collapse.check(self.peaks.get(token), mcap, liq)

    def concentration(self, token):
        from league import copy as lcopy
        return lcopy._concentration(token)


def _rug_tables(mint):
    """(topcheck rows, rug.db newest report) of ONE token, by primary key (never the whole tables: this process stays
    small)."""
    import json
    tc, rug = {}, {}
    try:
        from topcheck import store as tstore
        con = _ro(tstore.DB)
        if con is not None:
            try:
                con.row_factory = sqlite3.Row
                r = con.execute("SELECT * FROM top_check WHERE token=?", (mint,)).fetchone()
                if r:
                    d = dict(r)
                    for k in ("state_json", "safety_json", "rc_json", "sell_json"):
                        try:
                            d[k[:-5]] = json.loads(d.pop(k, None) or "null")
                        except ValueError:
                            d[k[:-5]] = None
                    tc[mint] = d
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        from ui import data as udata
        for path in udata.GROUPS["rug"]:
            con = _ro(path)
            if con is None:
                continue
            try:
                con.row_factory = sqlite3.Row
                r = con.execute("SELECT * FROM rug_reports WHERE mint=? ORDER BY checked_at DESC LIMIT 1",
                                (mint,)).fetchone()
            except sqlite3.Error:
                r = None
            finally:
                con.close()
            if r and (mint not in rug or (r["checked_at"] or 0) > (rug[mint].get("checked_at") or 0)):
                d = dict(r)
                d["data"] = udata.js(d.get("data"), {}) or {}
                rug[mint] = d
    except Exception:  # noqa: BLE001
        pass
    return tc, rug


def rug_risk(mint, mcap=None, liq=None, now_mono=None):
    """ok | unknown | oprez | risk | hard (ui/kandidati.rug_view on this one token), cached RUG_TTL_S; None when it
    cannot be read."""
    t = now_mono if now_mono is not None else time.monotonic()
    hit = _RUG.get(mint)
    if hit and t - hit[0] < RUG_TTL_S:
        return hit[1]
    level = None
    try:
        from league import copy as lcopy
        from rugfilter import archive, collapse
        from ui import data as udata, kandidati
        tables = _rug_tables(mint)
        mine = None
        if lcopy._CONC_CACHE is None:   # _concentration reads these two tables, not the whole files
            mine = lcopy._CONC_CACHE = {"tc": tables[0], "rug": tables[1]}
        try:
            src = _RugSrc(collapse.peaks(udata.HYPE_DB, [mint]))
            level = kandidati.rug_view(mint, mcap or None, liq, src, tables, archive.blocked(), None)["level"]
        finally:
            if mine is not None and lcopy._CONC_CACHE is mine:
                lcopy._CONC_CACHE = None
    except Exception as e:  # noqa: BLE001 - the alarm goes out without it
        print(f"zonewatch: rug ocjena nije pročitana ({type(e).__name__})", flush=True)
        level = None
    if len(_RUG) > 500:
        _RUG.clear()
    _RUG[mint] = (t, level)
    return level
