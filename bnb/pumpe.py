"""Step 1: the BSC pump list.

Universe: tokens seen on GeckoTerminal's BSC lists and DexScreener (izvor.gt_lists / ds_lists), each priced on its
most liquid supported pool (PancakeSwap v2 / v3 / Infinity CL, Uniswap v2 / v3 on BSC; never a launchpad curve),
memecoins only (meme(): veliki/universe.non_meme's rule + the BSC stables, wrapped / pegged majors, LSTs, CEX tokens
and the chain's blue chips), market cap now <= max_mcap (200 M; GeckoTerminal / DexScreener market cap, the FDV
when there is none) and >= min_mcap (30k, CLAUDE.md), liquidity >= min_liq (25,000 $).

Candles (GeckoTerminal OHLCV, USD, the memecoin's side of its pool): daily for days_1d (180; GeckoTerminal's free
history ends there), hourly for days_1h (45; two calls of 1000) only for a token whose daily candles moved >= +50 %
in a day or two within those 45 days (hour_gate: a +50 % hourly jump always shows in the daily highs and lows, so the
gate loses no 1h pump and saves ~2 calls a quiet token).

Pumps: the SAME rules and code as Solana (insajderi/events.find_jumps, tier_of): 1h closes +mkt_x6 (50 %) within 6 h
or +mkt_x24 (100 %) within 24 h; daily closes +mkt_x1d (50 %) in a day or +mkt_x3d (100 %) within 3 days; a daily
pump whose window holds a 1h pump's t0 is that pump (the 1h one stands). Tier by PEAK market cap: "pumpa15" >= 15 M,
"pumpa2" 2-15 M (peak MC = today's MC x the peak close / the last close: today's supply, as on Solana).
"""
import re

from bnb import izvor, store, swaps

NON_MEME_BSC = frozenset(s.upper() for s in (
    "BNB", "WBNB", "BTCB", "ETH", "WETH", "CAKE", "XVS", "TWT", "SFP", "ALPACA", "BAKE", "BSW", "BUSD", "USDT", "USDC",
    "FDUSD", "USD1", "TUSD", "DAI", "LISUSD", "USDE", "SUSDE", "USDF", "USDX", "USDD", "USDS", "SLISBNB", "BNBX",
    "ANKRBNB", "STKBNB", "WBETH", "ASBNB", "SOLVBTC", "XSOLVBTC", "UNIBTC", "STBTC", "PUMPBTC", "LBTC", "ENZOBTC",
    "ADA", "DOT", "XRP", "LINK", "DOGE", "LTC", "BCH", "FIL", "ATOM", "TRX", "AVAX", "SHIB", "MATIC", "POL", "UNI",
    "AAVE", "NEAR", "ETC", "TON", "SUI", "APT", "INJ", "SOL", "XAUT", "PAXG", "LISTA", "THE", "ASTER", "BGB", "OKB",
    "GT", "KCS", "MX", "HT", "WOO", "CRO", "LEO", "FET", "TAO", "ARB", "OP", "1INCH", "COMP", "MKR", "SNX", "CRV",
    "SUSHI", "YFI", "BAND", "ZRO", "STG", "PENDLE", "WLFI", "AVNT"))
_NAME_RX = re.compile(r"binance-peg|bnb pegged|wrapped|staked|bridged|liquid staking|restaked|xstock|tokenized|"
                      r"\bvault\b|lp token|pegged", re.I)


def meme(sym, name=None):
    """(True, None) for a token the pump list may hold, else (False, why)."""
    s = (sym or "").upper().strip().lstrip("$")
    if s in NON_MEME_BSC:
        return False, "stable / majors / LST / CEX / blue chip"
    try:
        from veliki import universe
        if universe.non_meme(sym, name):
            return False, "nije memecoin (pravilo veliki/universe.non_meme)"
    except Exception:  # noqa: BLE001
        pass
    if name and _NAME_RX.search(name):
        return False, "omotan / vezan / staked (ime)"
    return True, None


def merge_candidates(rows):
    """{token: best row}: one pool a token, the most liquid supported one (kind_of known)."""
    out = {}
    for r in rows:
        if not r or not swaps.kind_of(r.get("dex"), r.get("pool")):
            continue
        cur = out.get(r["token"])
        if cur is None or (r.get("liq") or 0) > (cur.get("liq") or 0):
            keep = {k: cur.get(k) for k in ("mcap", "name") if cur and cur.get(k)} if cur else {}
            out[r["token"]] = dict(r, **{k: v for k, v in keep.items() if not r.get(k)})
    return out


def judge(r, c):
    """(ok, why) of one candidate row against the universe's band."""
    ok, why = meme(r.get("symbol"), r.get("name"))
    if not ok:
        return False, why
    mc = r.get("mcap") or r.get("fdv")
    if mc is None:
        return False, "nema MC"
    if mc > float(c["max_mcap"]):
        return False, "MC iznad 200 M"
    if mc < float(c["min_mcap"]):
        return False, "MC ispod 30k"
    if (r.get("liq") or 0) < float(c["min_liq"]):
        return False, "likvidnost ispod 25k"
    return True, None


def discover(con, c, now, log=print):
    """Store the universe (bnb_tokens): GeckoTerminal + DexScreener lists, then DexScreener tokens/v1 for the market cap
    and the most liquid pool of each. -> (kept, seen)."""
    rows = izvor.gt_lists(c, log) + izvor.ds_lists(c)
    cand = merge_candidates(rows)
    best = izvor.best_pairs(list(cand))
    for tok, b in best.items():   # DexScreener's market cap / most liquid pool win when they exist
        r = cand.get(tok) or {}
        if (b.get("liq") or 0) >= (r.get("liq") or 0) or not r:
            cand[tok] = dict(b, name=b.get("name") or r.get("name"))
        else:
            cand[tok] = dict(r, mcap=b.get("mcap") or r.get("mcap"), name=b.get("name") or r.get("name"))
    kept = 0
    for tok, r in cand.items():
        ok, why = judge(r, c)
        kept += ok
        con.execute("""INSERT INTO bnb_tokens (chain, token, symbol, name, pool, dex, quote, quote_sym, pool_created, mcap,
            fdv, liq, vol24, src, seen_ts, meme, why_out) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (chain, token) DO UPDATE SET symbol = excluded.symbol, name = COALESCE(excluded.name, name),
            pool = excluded.pool, dex = excluded.dex, quote = excluded.quote, quote_sym = excluded.quote_sym,
            pool_created = excluded.pool_created, mcap = excluded.mcap, fdv = excluded.fdv, liq = excluded.liq,
            vol24 = excluded.vol24, src = excluded.src, seen_ts = excluded.seen_ts, meme = excluded.meme,
            why_out = excluded.why_out""",
                    (store.CHAIN, tok, r.get("symbol"), r.get("name"), r["pool"], r["dex"], r["quote"],
                     r["quote_sym"], r.get("created"), r.get("mcap"), r.get("fdv"), r.get("liq"), r.get("vol24"),
                     r.get("src"), int(now), int(ok), why))
    con.commit()
    return kept, len(cand)


def universe(con, c):
    """[(token, symbol, pool, mcap, candles_ts)] of the stored memecoins in the band, best volume first."""
    return store.q(con, "SELECT token, symbol, pool, COALESCE(mcap, fdv), candles_ts FROM bnb_tokens WHERE chain = ? "
                        "AND meme = 1 ORDER BY vol24 DESC LIMIT ?", (store.CHAIN, int(c["max_tokens"])))


def hour_gate(daily, c, now):
    """True when the daily candles of the last days_1h days moved >= hour_gate (50 %) within a day or two."""
    since = now - int(c["days_1h"]) * 86400 - 86400
    d = [x for x in daily if x[0] >= since]
    g = 1 + float(c["hour_gate"])
    for i in range(len(d)):
        lo = min(x[3] for x in d[max(0, i - 1):i + 1] if x[3]) if any(x[3] for x in d[max(0, i - 1):i + 1]) else None
        hi = max(x[2] for x in d[i:i + 2])
        if lo and hi >= lo * g:
            return True
    return False


def save_candles(con, tok, res, rows):
    con.executemany("INSERT OR REPLACE INTO bnb_candles VALUES (?,?,?,?,?,?,?,?,?)",
                    [(store.CHAIN, tok, res, *r) for r in rows])


def fetch_candles(con, c, tok, pool, now, budget=None):
    """Daily (1 call) and, behind the gate, hourly (2 calls) candles of one token. -> calls used."""
    n = 1
    day = izvor.ohlcv(pool, tok, "day", limit=min(1000, int(c["days_1d"]) + 5))
    if not day:   # a failed / empty answer is never marked done: retried, at most 3 times (then skipped as done)
        k = f"cfail:{tok}"
        tries = int(float(store.kv(con, k) or 0)) + 1
        store.kv(con, k, tries)
        if tries < 3:
            con.commit()
            return n
    save_candles(con, tok, "1d", day)
    if day and hour_gate(day, c, now):
        hr = izvor.ohlcv(pool, tok, "hour", limit=1000)
        n += 1
        if hr and hr[0][0] > now - int(c["days_1h"]) * 86400:
            hr = izvor.ohlcv(pool, tok, "hour", limit=1000, before=hr[0][0]) + hr
            n += 1
        save_candles(con, tok, "1h", [x for x in hr if x[0] >= now - int(c["days_1h"]) * 86400])
    con.execute("UPDATE bnb_tokens SET candles_ts = ? WHERE chain = ? AND token = ?", (int(now), store.CHAIN, tok))
    con.commit()
    return n


def closes(con, tok, res, since):
    return [(int(ts), float(cl)) for ts, cl in store.q(con, "SELECT ts, c FROM bnb_candles WHERE chain = ? AND token = ? "
                                                            "AND res = ? AND ts >= ? ORDER BY ts",
                                                       (store.CHAIN, tok, res, int(since))) if cl]


def _ev(kind_prefix, tok, sym, pool, t0, base, pk_ts, pk, kind, src, mcap, last, c, win_end):
    from insajderi import events as iev
    mc0 = (mcap * base / last) if mcap and last else None
    peak_mc = (mcap * pk / last) if mcap and last else None
    x = pk / base - 1
    return {"eid": f"{kind_prefix}:{tok}:{t0}", "kind": "jump", "token": tok, "symbol": sym, "pool": pool, "t0": t0,
            "peak_ts": pk_ts, "peak_x": round(x, 4), "win_end": win_end, "src": src, "mcap0": mc0, "peak_mc": peak_mc,
            "tier": iev.tier_of(peak_mc, c), "prio": round(min(x, 10.0) + (1.0 if (mc0 or 0) >= 5e6 else 0.0), 3),
            "callers": {}, "n_callers": 0, "handle": None, "crew": None}


def token_events(con, c, tok, sym, pool, mcap, now):
    """[event dict] of one token: 1h pumps of the hourly closes, then the daily pumps not already one of them."""
    from insajderi import events as iev
    out = []
    h = closes(con, tok, "1h", now - int(c["days_1h"]) * 86400)
    if len(h) >= 3:
        last = h[-1][1]
        for t0, base, pk_ts, pk, kind in iev.find_jumps(h, float(c["mkt_x6"]), float(c["mkt_x24"])):
            out.append(_ev("j", tok, sym, pool, t0, base, pk_ts, pk, kind, f"c1h {kind}", mcap, last, c,
                           pk_ts + int(c["after_peak_s"])))
    d = closes(con, tok, "1d", now - int(c["days_1d"]) * 86400)
    if len(d) >= 3:
        last = d[-1][1]
        avoid = [(e["t0"], e["win_end"]) for e in out]
        for t0, base, pk_ts, pk, kind in iev.find_jumps(d, float(c["mkt_x1d"]), float(c["mkt_x3d"]), 86400,
                                                        3 * 86400, ("1d", "3d")):
            pk_end = pk_ts + 86400
            win_end = pk_end + int(c["after_peak_s"])
            if any(t0 <= t <= win_end for t, _we in avoid):
                continue
            e = _ev("d", tok, sym, pool, t0, base, pk_end, pk, kind, f"c1d {kind}", mcap, last, c, win_end)
            out.append(e)
    mc_min = float(c["min_mcap"])
    return [e for e in out if e["mcap0"] is None or e["mcap0"] >= mc_min]


def save_events(con, events, now):
    """Upsert (a stored event keeps its fetch state). -> new ones."""
    n = 0
    for e in events:
        if store.q(con, "SELECT 1 FROM bnb_events WHERE eid = ?", (e["eid"],)):
            con.execute("UPDATE bnb_events SET peak_ts = ?, peak_x = ?, win_end = ?, tier = ?, peak_mc = ?, mcap0 = ?, "
                        "prio = ? WHERE eid = ?", (e["peak_ts"], e["peak_x"], e["win_end"], e["tier"], e["peak_mc"],
                                                   e["mcap0"], e["prio"], e["eid"]))
            continue
        con.execute("""INSERT INTO bnb_events (chain, eid, kind, token, symbol, pool, t0, peak_ts, peak_x, win_end, src,
            tier, peak_mc, mcap0, prio, built_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (store.CHAIN, e["eid"], e["kind"], e["token"], e["symbol"], e["pool"], e["t0"], e["peak_ts"],
                     e["peak_x"], e["win_end"], e["src"], e["tier"], e["peak_mc"], e["mcap0"], e["prio"], int(now)))
        n += 1
    con.commit()
    return n


KEYS = ("eid", "kind", "token", "symbol", "pool", "t0", "peak_ts", "peak_x", "win_end", "src", "tier", "peak_mc",
        "mcap0", "prio", "fetched", "n_part", "reach")


def load(con, tiered=True):
    sql = f"SELECT {', '.join(KEYS)} FROM bnb_events WHERE chain = ?" + (" AND tier IS NOT NULL" if tiered else "")
    out = []
    for r in store.q(con, sql + " ORDER BY t0", (store.CHAIN,)):
        d = dict(zip(KEYS, r))
        d.update(callers={}, n_callers=0, handle=None, crew=None)
        out.append(d)
    return out


def build(con, c, now, clock=None, log=print, gt_budget=None):
    """Candles for the universe tokens without fresh ones (oldest first, within gt_budget calls), then every
    token's events. -> {"tokens", "candled", "gt_calls", "events_new", "events"}."""
    toks = universe(con, c)
    todo = sorted((t for t in toks if not t[4] or now - t[4] > 20 * 3600), key=lambda t: t[4] or 0)
    calls = 0
    done = 0
    for tok, sym, pool, mcap, _cts in todo:
        if clock is not None and clock.over():
            break
        if gt_budget is not None and calls >= gt_budget:
            break
        calls += fetch_candles(con, c, tok, pool, now)
        done += 1
    evs = []
    for tok, sym, pool, mcap, _cts in toks:
        evs += [e for e in token_events(con, c, tok, sym, pool, mcap, now) if e["tier"]]
    new = save_events(con, evs, now)
    return {"tokens": len(toks), "candled": done, "gt_calls": calls, "events_new": new, "events": len(evs),
            "left": max(0, len(todo) - done)}

