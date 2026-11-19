"""Step 2: who bought before and sold into each pump (the BSC side of insajderi/chain.fetch_event_deep + participants).

Windows (the Solana deep read's): pre = [t0 - pump_pre_h (24 h; 72 h for a 1d pump), t0), jump = [t0, win_end] (the
peak + 1 h). Each window is turned into blocks (block_at: the head and its time, 0.45 s a block, corrected with
eth_getBlockByNumber until within a few seconds) and read in slices of <= max_range blocks: the pool's Swap logs and
the token's Transfer logs of the same blocks (swaps.parse: the trader is the address the tokens end at / came from).
A slice is read whole or not at all (eth_getLogs has no partial page), so coverage = the seconds of the slices read
/ the window's seconds, per window (bnb_cover pre_cov / jump_cov, as i2_cover). Slices before the free RPC's history
(archive_s, ~23 days measured) cannot be read: the event's `reach` says "izvan dosega" (all of it) / "djelomično".

Each swap -> bnb_trades (tx, log index unique: a re-read never counts a trade twice): side, token amount, quote
amount, its USD (USDT / USDC / BUSD / USD1 / FDUSD = 1 $, WBNB / BNB at Binance's BNBUSDT hourly close) and its SOL
equivalent (USD / SOLUSDT of the hour): the Solana rules' min_sol 0.05 then applies as "0.05 SOL in USD at the time".
"""
import bisect

from bnb import rpc as brpc
from bnb import store, swaps

BIG = 1 << 62


# ---------- prices ----------------------------------------------------------------------------------------------------

class Px:
    """USD of the quote assets and of SOL at a time, from bnb_px (series "bnb", "sol": hourly closes)."""

    def __init__(self, con):
        self.s = {}
        for name in ("bnb", "sol"):
            rows = store.q(con, "SELECT ts, usd FROM bnb_px WHERE series = ? ORDER BY ts", (name,))
            self.s[name] = ([r[0] for r in rows], [r[1] for r in rows])

    def at(self, name, ts):
        if name == "usd":
            return 1.0
        xs, ys = self.s.get(name) or ([], [])
        if not xs:
            return None
        i = bisect.bisect_right(xs, ts) - 1
        return ys[max(0, i)]


def fill_prices(con, now, days=200, fetch=None):
    """BNBUSDT and SOLUSDT hourly closes (Binance's public mirror) from the last stored hour (or `days` back) to now.
    -> rows added."""
    from bnb import izvor
    n = 0
    for name, sym in (("bnb", "BNBUSDT"), ("sol", "SOLUSDT")):
        last = store.q(con, "SELECT MAX(ts) FROM bnb_px WHERE series = ?", (name,))
        start = (last[0][0] + 3600) if last and last[0][0] else int(now) - days * 86400
        if start > now - 3600:
            continue
        rows = izvor.klines(sym, start * 1000, int(now) * 1000, fetch=fetch)
        con.executemany("INSERT OR REPLACE INTO bnb_px VALUES (?,?,?)", [(name, ts, v) for ts, v in rows])
        n += len(rows)
    con.commit()
    return n


# ---------- blocks --------------------------------------------------------------------------------------------------

class Blocks:
    """time -> block number on BSC: the head and its time, block_s (0.45 s since the Fermi upgrade, measured: 1 M
    blocks = 450,191 s), corrected by reading the estimated block's time (<= 4 calls, cached)."""

    def __init__(self, rpc, block_s=0.45):
        self.rpc, self.bs = rpc, float(block_s)
        self.head = rpc.head()
        self.head_ts = rpc.block_ts(self.head)
        self.cache = {}

    def at(self, ts):
        ts = int(ts)
        if ts >= self.head_ts:
            return self.head
        key = ts // 60
        if key in self.cache:
            return self.cache[key]
        n = self.head - int((self.head_ts - ts) / self.bs)
        for _ in range(4):
            bts = self.rpc.block_ts(n)
            if bts is None:
                break
            d = ts - bts
            if abs(d) <= 3:
                break
            n = min(self.head, n + int(d / self.bs))
        self.cache[key] = n
        return n


# ---------- tokens --------------------------------------------------------------------------------------------------

def token_meta(con, rpc, tok, pool, dex, quote):
    """(token decimals, token_is0, the pool addresses the tokens move through) of a stored token; the decimals and
    (infinity) the pool key are read once (eth_call) and stored."""
    r = store.q(con, "SELECT decimals, qdecimals FROM bnb_tokens WHERE chain = ? AND token = ?", (store.CHAIN, tok))
    dec = r[0][0] if r and r[0][0] is not None else None
    if dec is None:
        try:
            dec = int(rpc.call("eth_call", [{"to": tok, "data": swaps.SEL_DECIMALS}, "latest"]), 16)
        except Exception:  # noqa: BLE001
            dec = 18
        con.execute("UPDATE bnb_tokens SET decimals = ? WHERE chain = ? AND token = ?", (dec, store.CHAIN, tok))
    kind = swaps.kind_of(dex, pool)
    is0 = None
    if kind == "inf":
        key = store.kv(con, f"poolkey:{pool}")
        if not key:
            try:
                res = rpc.call("eth_call", [{"to": swaps.INF_CL_MANAGER, "data": swaps.SEL_POOLKEY + pool[2:]},
                                            "latest"])
                key = swaps.addr(res[2:66]) + "," + swaps.addr(res[66:130])
                store.kv(con, f"poolkey:{pool}", key)
            except Exception:  # noqa: BLE001
                key = None
        if key:
            c0, _c1 = key.split(",")
            is0 = c0 == tok.lower()
        pools = {swaps.INF_VAULT}
    else:
        pools = {pool}
    con.commit()
    return dec, is0, pools, kind


def swap_filter(pool, kind):
    if kind == "inf":
        return {"address": swaps.INF_CL_MANAGER, "topics": [swaps.INF_CL, pool]}
    return {"address": pool, "topics": [[swaps.V2, swaps.V3, swaps.V3_PCS]]}


def store_trades(con, e, quote, trades, px):
    rows = []
    qser = (swaps.QUOTES.get(quote) or ("?", 18, "usd"))[2]
    for t in trades:
        qusd = px.at(qser, t["ts"]) if t["ts"] else None
        usd = t["qamt"] * qusd if qusd is not None else None
        su = px.at("sol", t["ts"]) if t["ts"] else None
        # pool, quote and the Swap's recipient are not stored a row (the pool / quote are the token's, bnb_tokens; the
        # recipient was only needed for the attribution measurement): ~130 bytes less a swap, the 400 MB cap holds
        # ~1 M swaps
        rows.append((store.CHAIN, e["token"], None, t["tx"], t["li"], t["block"], t["ts"], t["trader"], t["side"],
                     t["amt"], None, t["qamt"], usd, (usd / su) if usd is not None and su else None,
                     None if t["how"] == "transfer" else t["how"], None))
    con.executemany("INSERT OR IGNORE INTO bnb_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def windows(e, c):
    pre_h = float(c["pump_pre_h_1d"] if str(e.get("src") or "").startswith("c1d") else c["pump_pre_h"])
    t0 = int(e["t0"])
    return (("pre", t0 - int(pre_h * 3600), t0), ("jump", t0, int(e["win_end"])))


def fetch_event(con, c, e, rpc, blocks, px, now, clock=None, log=print):
    """Read one pump event's windows (see the module text). -> {"swaps", "calls", "complete", "reach"}. Marked fetched
    (bnb_cover depth = FETCH_DEPTH) only when every slice in reach was read."""
    tokr = store.q(con, "SELECT dex, quote FROM bnb_tokens WHERE chain = ? AND token = ?", (store.CHAIN, e["token"]))
    if not tokr:
        return {"swaps": 0, "calls": 0, "complete": False, "reach": "nema tokena"}
    dex, quote = tokr[0]
    calls0 = rpc.n
    dec, is0, pools, kind = token_meta(con, rpc, e["token"], e["pool"], dex, quote)
    qdec = (swaps.QUOTES.get(quote) or ("?", 18))[1]
    oldest = int(now) - int(c["archive_s"])
    cover, total_sw, complete, out_reach = {}, 0, True, 0
    for name, lo_ts, hi_ts in windows(e, c):
        span = max(1, hi_ts - lo_ts)
        got = 0
        a_ts = max(lo_ts, oldest)
        if a_ts >= hi_ts:
            cover[name] = (span, 0.0)
            out_reach += 1
            continue
        if a_ts > lo_ts:
            out_reach += 0.5
        b0, b1 = blocks.at(a_ts), blocks.at(hi_ts)
        step = int(c["max_range"])
        for i, a in enumerate(range(b0, b1 + 1, step)):
            b = min(b1, a + step - 1)
            key = f"d{store.FETCH_DEPTH}:{e['eid']}:{name}:{i}"
            sec = int(round((b - a + 1) * blocks.bs))
            done = store.q(con, "SELECT n FROM bnb_fetch WHERE key = ? AND ok = 1", (key,))
            if done:
                got += sec
                total_sw += done[0][0] or 0
                continue
            if clock is not None and clock.over():
                complete = False
                break
            st = {}
            try:
                sl = rpc.logs(swap_filter(e["pool"], kind), a, b, max_range=step, stats=st)
                tl = rpc.logs({"address": e["token"], "topics": [swaps.TRANSFER]}, a, b, max_range=step, stats=st) \
                    if sl else []
            except brpc.RpcError as err:
                log(f"{store.PREFIX}{e.get('symbol') or e['token'][:8]} {name} {a}-{b}: {str(err)[:90]}")
                complete = False
                continue
            tr = swaps.parse(sl, tl, e["token"], quote, pools, dec, qdec, is0)
            n = store_trades(con, e, quote, tr, px)
            total_sw += n
            got += sec
            con.execute("INSERT OR REPLACE INTO bnb_fetch VALUES (?,?,?,?,?)", (key, int(now), n, st.get("calls", 0), 1))
            con.commit()
        cover[name] = (span, round(min(1.0, got / span), 4))
    reach = "puno" if not out_reach else ("izvan dosega" if out_reach >= 2 else "djelomično")
    con.execute("UPDATE bnb_events SET reach = ? WHERE eid = ?", (reach, e["eid"]))
    if complete:
        (ps, pc), (js, jc) = cover["pre"], cover["jump"]
        con.execute("INSERT OR REPLACE INTO bnb_cover VALUES (?,?,?,?,?,?,?,?,?)",
                    (e["eid"], store.FETCH_DEPTH, ps, pc, js, jc, total_sw, rpc.n - calls0, int(now)))
        con.execute("UPDATE bnb_events SET fetched = 1 WHERE eid = ?", (e["eid"],))
    con.commit()
    return {"swaps": total_sw, "calls": rpc.n - calls0, "complete": complete, "reach": reach}


def order_key(e):
    """The read order: "pumpa15" first, then "pumpa2"; inside a tier the newest first (the free history is short)."""
    from insajderi.events import TIER_RANK
    return (TIER_RANK.get(e.get("tier"), 9), -int(e["t0"]))


def due(con, events, now, c):
    """Tiered events not read at FETCH_DEPTH whose window ended and whose jump window is still within the free history
    (an event entirely out of reach is marked once and skipped)."""
    deep = {eid: d for eid, d in store.q(con, "SELECT eid, depth FROM bnb_cover")}
    oldest = int(now) - int(c["archive_s"])
    out = []
    for e in events:
        if not e.get("tier") or e["win_end"] > now or (deep.get(e["eid"]) or 0) >= store.FETCH_DEPTH:
            continue
        if e["win_end"] <= oldest:
            if e.get("reach") != "izvan dosega":
                con.execute("UPDATE bnb_events SET reach = 'izvan dosega' WHERE eid = ?", (e["eid"],))
            continue
        out.append(e)
    con.commit()
    return sorted(out, key=order_key)


# ---------- participants (insajderi/chain.participants on the BSC rows) -------------------------------------------------

def participants(e, trades, c):
    """trades [(wallet, ts, side, sol_eq, usd)] of one token -> {wallet: row} for event e: the first buy in the pre
    window [t0 - pre_h, t0) and its SOL equivalent / USD, the sells in [t0, win_end] (count, SOL eq., USD, first).
    Dust (known SOL eq. under min_sol on both sides) out; the Solana rule, with the pre window the deep read covers."""
    (_n, lo, t0), (_m, _t, end) = windows(e, c)
    out = {}
    for w, ts, side, sol, usd in sorted(trades, key=lambda x: x[1] or 0):
        if not w or ts is None:
            continue
        if side == "buy" and lo <= ts < t0:
            o = out.setdefault(w, _row())
            if o["buy_ts"] is None:
                o["buy_ts"] = int(ts)
            if sol is not None:
                o["sol_in"] = (o["sol_in"] or 0) + abs(sol)
            o["usd_in"] = (o["usd_in"] or 0) + abs(usd or 0)
        elif side == "sell" and t0 <= ts <= end:
            o = out.setdefault(w, _row())
            o["n_sells"] += 1
            if sol is not None:
                o["sol_out"] = (o["sol_out"] or 0) + abs(sol)
            o["usd_out"] = (o["usd_out"] or 0) + abs(usd or 0)
            if o["first_sell_ts"] is None:
                o["first_sell_ts"] = int(ts)
    res = {}
    for w, o in out.items():
        small_in = o["sol_in"] is not None and o["sol_in"] < c["min_sol"]
        small_out = o["sol_out"] is not None and o["sol_out"] < c["min_sol"]
        if (o["buy_ts"] is None or small_in) and (not o["n_sells"] or small_out):
            continue
        o["bought_before"] = int(o["buy_ts"] is not None and not small_in)
        o["sold_into"] = int(bool(o["n_sells"]) and not small_out)
        if o["bought_before"]:
            o["lead_s"] = t0 - o["buy_ts"]
        res[w] = o
    return res


def _row():
    return {"buy_ts": None, "sol_in": None, "n_sells": 0, "sol_out": None, "first_sell_ts": None, "bought_before": 0,
            "sold_into": 0, "lead_s": None, "usd_in": None, "usd_out": None}


def build_parts(con, c, events):
    """bnb_part of every read event (owner = the address itself: no free funder grouping on BSC). -> events built."""
    n = 0
    for e in events:
        if not e.get("fetched"):
            continue
        (_n, lo, _t0), (_m, _t, end) = windows(e, c)
        rows = store.q(con, "SELECT trader, ts, side, sol_eq, usd FROM bnb_trades WHERE token = ? AND ts BETWEEN ? AND ?",
                       (e["token"], lo, end))
        part = participants(e, rows, c)
        con.execute("DELETE FROM bnb_part WHERE eid = ?", (e["eid"],))
        con.executemany("INSERT INTO bnb_part VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(store.CHAIN, e["eid"], w, w, o["buy_ts"], o["sol_in"], o["n_sells"], o["sol_out"],
                          o["first_sell_ts"], o["bought_before"], o["sold_into"], o["lead_s"], o["usd_in"],
                          o["usd_out"]) for w, o in part.items()])
        con.execute("UPDATE bnb_events SET n_part = ? WHERE eid = ?", (len(part), e["eid"]))
        n += 1
    con.commit()
    return n
