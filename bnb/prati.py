"""Step 4: the tracking poller and the measurement of the listed wallets' new buys (league/mjera.py's semantics, its
own table bnb_mjera: league.db's signal_mjera is not touched).

Watched: the members of bnb_pp "prije_pumpe" groups (confirmed first; source "bnb_prije_pumpe"), then "kandidat"
groups (2 pumps; source "bnb_kandidat"), at most track_max_addrs addresses.

The poll (the cheapest correct way the free RPC allows): ONE eth_getLogs without an address, Transfer topic, topic2
(to) = OR of up to track_chunk watched addresses, over the blocks since the last poll (<= track_blocks a call; on
rpc-bsc.48.club, the measured free endpoint that accepts an address-less filter; drpc as the fallback with 100-block
calls): every token any watched wallet RECEIVED, across all tokens. A received non-quote token is a buy only when its
transaction holds a Swap log (eth_getTransactionReceipt, batched): a plain transfer / airdrop is not a buy. The same
query with topic1 (from) = the watched addresses gives their SELLS of tokens with an open row ("prodali su": any
transfer of the token out of the wallet; Pretpostavka: moving to an own wallet counts as a sale too).

A row (league/mjera semantics, no account, no money):
  entry   the first DexScreener price at or after we SAW the buy (seen_ts = the poll that found it); never their price.
          guard: no price -> waits entry_wait_s, then a miss "bez cijene"; liquidity < trade/cost.LIQ_HARD_MIN (15k) ->
          miss "likvidnost"; MC < 30k -> miss "MC ispod 30k" (CLAUDE.md). Misses are rows, counted, never in a mean.
  exit    their sale seen by a poll -> "prodali su"; price <= entry x (1 - stop 25 %) -> "stop"; hold_h (24 h) after
          the entry -> "vrijeme"; no price for no_price_s (6 h) -> a miss "bez cijene".
  cost    cost_rt(): DEX fee both ways + 2 x the constant-product impact of the stake in the pool's liquidity
          (trade/cost.impact) + gas both ways / stake + the token's transfer tax both ways (measured on the buy's own
          receipt: 1 - received / sent by the pool; the sell tax assumed equal), never under rt_floor (3 %, the
          owner's floor for every shadow / measured trade); at 50 $ and 250 $.
  dedup   (source, gid, token) within 24 h is one row.
"""
import json
import time

from bnb import izvor, store, swaps
from bnb import rpc as brpc

SOURCES = ("bnb_prije_pumpe", "bnb_kandidat")
DEDUP_S = 24 * 3600


def bucket(mcap):
    try:
        from league import mjera
        return mjera.bucket(mcap)
    except Exception:  # noqa: BLE001
        return "?"


def watched(con, c):
    """[(source, owner, [members])], confirmed first."""
    out, n = [], 0
    for src, cls in (("bnb_prije_pumpe", "prije_pumpe"), ("bnb_kandidat", "kandidat")):
        for o, ms in store.q(con, "SELECT owner, members FROM bnb_pp WHERE cls = ? ORDER BY (confirmed_ts IS NULL), "
                                  "n_tokens DESC, n_pumps15 DESC", (cls,)):
            try:
                ms = json.loads(ms)
            except ValueError:
                ms = [o]
            if n + len(ms) > int(c["track_max_addrs"]):
                return out
            out.append((src, o, ms))
            n += len(ms)
    return out


def cost_rt(stake_usd, liq, fee_side, tax_side, c):
    """The round trip as a fraction of the stake (see the module text), never under rt_floor."""
    try:
        from trade import cost
        imp = cost.impact(stake_usd, liq)
    except Exception:  # noqa: BLE001
        side = (liq or 40_000) / 2
        imp = stake_usd / (side + stake_usd)
    gas = 2 * float(c["gas_usd"]) / float(stake_usd)
    rt = 2 * float(fee_side) + 2 * imp + gas + 2 * float(tax_side or 0)
    return max(rt, float(c["rt_floor"]))


def _topic(a):
    return "0x" + "0" * 24 + a[2:].lower()


def poll_logs(rpc, addrs, lo, hi, c, direction="to"):
    """Transfer logs to (or from) any of addrs in [lo, hi] (address-less filter, chunks of track_chunk)."""
    out = []
    ch = int(c["track_chunk"])
    for i in range(0, len(addrs), ch):
        topics = [_topic(a) for a in addrs[i:i + ch]]
        flt = {"topics": [swaps.TRANSFER, None, topics] if direction == "to" else [swaps.TRANSFER, topics]}
        out += rpc.logs(flt, lo, hi, max_range=int(c["track_blocks"]))
    return out


def buys_of(rpc, logs, watch):
    """[{wallet, token, tx, block, ts, usd_paid, tax}] of received tokens whose tx holds a Swap (a buy)."""
    cand = {}
    for lg in logs:
        tok = lg["address"].lower()
        w = swaps.addr(lg["topics"][2])
        if tok in swaps.QUOTES or w not in watch:
            continue
        cand.setdefault(lg["transactionHash"].lower(), []).append((w, tok, lg))
    if not cand:
        return []
    txs = list(cand)
    recs = rpc.batch([("eth_getTransactionReceipt", [h]) for h in txs], size=50)
    out = []
    for h, rec in zip(txs, recs):
        logs = (rec or {}).get("logs") or []
        swap_from = {lg["address"].lower() for lg in logs if lg["topics"] and lg["topics"][0] in swaps.SWAP_TOPICS}
        if not swap_from:
            continue
        pools = swap_from | ({swaps.INF_VAULT} if swaps.INF_CL_MANAGER in swap_from else set())
        trs = [(int(lg["logIndex"], 16), lg["address"].lower(), swaps.addr(lg["topics"][1]), swaps.addr(lg["topics"][2]),
                int(lg["data"] or "0x0", 16)) for lg in logs if lg["topics"] and lg["topics"][0] == swaps.TRANSFER
               and len(lg["topics"]) >= 3]
        for w, tok, lg in cand[h]:
            sent = sum(v for _li, t, f, _to, v in trs if t == tok and f in pools)
            got = sum(v for _li, t, _f, to, v in trs if t == tok and to == w)
            if not sent:
                continue
            paid = {}
            for _li, t, _f, to, v in trs:
                if t in swaps.QUOTES and to in pools:
                    paid[t] = paid.get(t, 0) + v / 10 ** swaps.QUOTES[t][1]
            ts = lg.get("blockTimestamp")
            out.append({"wallet": w, "token": tok, "tx": h, "block": int(lg["blockNumber"], 16),
                        "ts": int(ts, 16) if ts else None, "paid": paid,
                        "tax": max(0.0, 1 - got / sent) if sent and got <= sent else 0.0})
    return out


def record(con, src, gid, b, members, now):
    """One row a (source, group, token) a day. -> id or None."""
    if store.q(con, "SELECT 1 FROM bnb_mjera WHERE source = ? AND gid = ? AND token = ? AND seen_ts > ?",
               (src, gid, b["token"], int(now) - DEDUP_S)):
        return None
    cur = con.execute("INSERT INTO bnb_mjera (chain, source, gid, wallet, token, tx, their_buy_ts, their_usd, seen_ts, "
                      "delay_s, status, mc_bucket, guard) VALUES (?,?,?,?,?,?,?,?,?,?,'open','?',?)",
                      (store.CHAIN, src, gid, b["wallet"], b["token"], b["tx"], b.get("ts"), b.get("usd"), int(now),
                       int(now - b["ts"]) if b.get("ts") else None, json.dumps({"tax": round(b.get("tax") or 0, 4),
                                                                                "members": members[:20]})))
    return cur.lastrowid


def quotes(toks):
    """{token: (price, liq, mcap, symbol, dex labels)} from DexScreener (the most liquid pair of each)."""
    out = {}
    for p in izvor.tokens(toks, ttl=20):
        r = izvor.ds_pair_row(p)
        if not r or not r.get("price"):
            continue
        cur = out.get(r["token"])
        if cur is None or (r["liq"] or 0) > (cur[1] or 0):
            out[r["token"]] = (r["price"], r["liq"], r.get("mcap") or r.get("fdv"), r.get("symbol"), r.get("dex"))
    return out


def fee_side(dex, c):
    """The DEX fee a side: v2 0.25 %; v3 / infinity pools carry their own tier (unknown from DexScreener: 0.25 %)."""
    return float(c["fee_side_default"])


def step(con, c, now, sold=frozenset(), q=None):
    """Price the open rows: entries, exits (pure on the given quotes q {token: (price, liq, mcap, sym, dex)} and the
    set of (gid, token) whose sale a poll saw). -> {"entered", "closed", "missed"}."""
    try:
        from trade import cost
        liq_min = float(cost.LIQ_HARD_MIN)
    except Exception:  # noqa: BLE001
        liq_min = 15_000.0
    out = {"entered": 0, "closed": 0, "missed": 0}
    rows = store.q(con, "SELECT id, gid, token, seen_ts, entry_ts, entry_price, liq, last_px_ts, guard FROM bnb_mjera "
                        "WHERE status = 'open'")
    for rid, gid, tok, seen, ets, epx, liq, last, guard in rows:
        qt = (q or {}).get(tok)
        px = qt[0] if qt else None
        if ets is None:
            if qt and px:
                p, lq, mc, sym = qt[:4]
                why = ("likvidnost" if lq is not None and lq < liq_min else
                       "MC ispod 30k" if mc is not None and mc < float(c["min_mcap"]) else None)
                if why:
                    con.execute("UPDATE bnb_mjera SET status = 'miss', exit_reason = ?, entry_mcap = ?, mc_bucket = ?, "
                                "liq = ?, symbol = ? WHERE id = ?", (why, mc, bucket(mc), lq, sym, rid))
                    out["missed"] += 1
                else:
                    con.execute("UPDATE bnb_mjera SET entry_ts = ?, entry_price = ?, entry_mcap = ?, mc_bucket = ?, "
                                "liq = ?, symbol = ?, token_day = ?, last_px_ts = ?, last_px = ? WHERE id = ?",
                                (int(now), p, mc, bucket(mc), lq, sym, store.day(now), int(now), p, rid))
                    out["entered"] += 1
            elif now - seen > int(c["entry_wait_s"]):
                con.execute("UPDATE bnb_mjera SET status = 'miss', exit_reason = 'bez cijene' WHERE id = ?", (rid,))
                out["missed"] += 1
            continue
        if px:
            con.execute("UPDATE bnb_mjera SET last_px_ts = ?, last_px = ? WHERE id = ?", (int(now), px, rid))
        reason = None
        if px and (gid, tok) in sold:
            reason = "prodali su"
        elif px and px <= epx * (1 - float(c["stop"])):
            reason = "stop"
        elif px and now - ets >= float(c["hold_h"]) * 3600:
            reason = "vrijeme"
        elif not px and now - (last or ets) >= int(c["no_price_s"]):
            con.execute("UPDATE bnb_mjera SET status = 'miss', exit_ts = ?, exit_reason = 'bez cijene' WHERE id = ?",
                        (int(now), rid))
            out["missed"] += 1
            continue
        if reason:
            try:
                tax = float(json.loads(guard or "{}").get("tax") or 0)
            except (ValueError, AttributeError):
                tax = 0.0
            g = px / epx - 1
            fs = fee_side(qt[4] if qt else None, c)
            c50, c250 = (cost_rt(s, liq, fs, tax, c) for s in c["stakes_usd"][:2])
            con.execute("UPDATE bnb_mjera SET status = 'closed', exit_ts = ?, exit_price = ?, exit_reason = ?, "
                        "ret_gross = ?, cost_50 = ?, cost_250 = ?, ret_net_50 = ?, ret_net_250 = ? WHERE id = ?",
                        (int(now), px, reason, g, c50, c250, g - c50, g - c250, rid))
            out["closed"] += 1
    con.commit()
    return out


def run(con, c, now, clock=None, rpc=None, log=print):
    """One poll + one pricing step. -> {"watched", "addrs", "blocks", "buys", "rows", "sold", "delay_s", ...}."""
    out = {"watched": 0, "addrs": 0, "blocks": 0, "buys": 0, "rows": 0, "sold": 0}
    w = watched(con, c)
    out["watched"] = len(w)
    owner_of, members = {}, {}
    for src, o, ms in w:
        for m in ms:
            owner_of[m] = (src, o)
        members[o] = ms
    addrs = sorted(owner_of)
    out["addrs"] = len(addrs)
    sold = set()
    if addrs:
        rpc = rpc or brpc.Rpc(c["rpc_poll"], gap=1.0)
        try:
            head = rpc.head()
            last = int(float(store.kv(con, "track_block") or 0)) or head - int(c["track_blocks"])
            lo = max(last + 1, head - 6 * int(c["track_blocks"]))   # catch up at most ~3 h of chain a poll
            if head >= lo:
                ins = poll_logs(rpc, addrs, lo, head, c, "to")
                outs = poll_logs(rpc, addrs, lo, head, c, "from")
                out["blocks"] = head - lo + 1
                open_toks = {(g, t) for g, t in store.q(con, "SELECT gid, token FROM bnb_mjera WHERE status = 'open'")}
                for lg in outs:
                    wl = swaps.addr(lg["topics"][1])
                    if wl in owner_of and (owner_of[wl][1], lg["address"].lower()) in open_toks:
                        sold.add((owner_of[wl][1], lg["address"].lower()))
                out["sold"] = len(sold)
                buys = buys_of(rpc, ins, set(addrs))
                out["buys"] = len(buys)
                from bnb import chain
                px = chain.Px(con)
                for b in buys:
                    usd = 0.0
                    for qt, amt in b["paid"].items():
                        p = px.at(swaps.QUOTES[qt][2], b["ts"] or now)
                        usd += amt * (p or 0)
                    b["usd"] = round(usd, 2) if usd else None
                    src, o = owner_of[b["wallet"]]
                    if record(con, src, o, b, members.get(o, []), now):
                        out["rows"] += 1
                delays = [now - b["ts"] for b in buys if b.get("ts")]
                out["delay_s"] = max(delays) if delays else None
                store.kv(con, "track_block", head)
                con.commit()
        except brpc.RpcError as e:
            log(f"{store.PREFIX}praćenje: RPC {str(e)[:100]}")
            out["error"] = str(e)[:100]
    toks = [t for (t,) in store.q(con, "SELECT DISTINCT token FROM bnb_mjera WHERE status = 'open'")]
    q = quotes(toks) if toks else {}
    out.update(step(con, c, now, sold, q))
    return out


def summary(con):
    """{source: {"signals", "measured", "misses", "open", "mean_net_50_pct", "mean_net_250_pct", "win_pct",
    "median_delay_s"}}."""
    import statistics
    out = {}
    for src in SOURCES:
        rows = store.q(con, "SELECT status, ret_net_50, ret_net_250, delay_s FROM bnb_mjera WHERE source = ?", (src,))
        done = [r for r in rows if r[0] == "closed" and r[1] is not None]
        ds = [r[3] for r in rows if r[3] is not None]
        out[src] = {"signals": len(rows), "measured": len(done), "misses": sum(1 for r in rows if r[0] == "miss"),
                    "open": sum(1 for r in rows if r[0] == "open"),
                    "mean_net_50_pct": round(100 * statistics.mean(r[1] for r in done), 2) if done else None,
                    "mean_net_250_pct": round(100 * statistics.mean(r[2] for r in done), 2) if done else None,
                    "win_pct": round(100 * sum(1 for r in done if r[1] > 0) / len(done), 1) if done else None,
                    "median_delay_s": statistics.median(ds) if ds else None}
    return out


def line(r):
    return (f"{store.PREFIX}praćenje: {r.get('watched', 0)} grupa ({r.get('addrs', 0)} adresa), {r.get('blocks', 0)} "
            f"blokova, novih kupnji {r.get('buys', 0)}, novih redaka {r.get('rows', 0)}, ulaza {r.get('entered', 0)}, "
            f"zatvoreno {r.get('closed', 0)}, promašeno {r.get('missed', 0)}"
            + (f"; greška {r['error']}" if r.get("error") else ""))
