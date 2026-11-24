"""Profitable "diamond" holders of the established midcaps and what they buy now (15.11., owner: "Find wallets that hold
large amounts of established, profitable tokens and are in big profit holding them — what are they buying now? Cluster
them; several big holders of old tokens buying the same microcaps are probably insiders on the smaller tokens").

  1. positions   the top profit_tokens (15) of the veliki table (category A, then B, then C; the veliki list without a
                 table), their top profit_holders (20) holders from the newest snapshot without pools, burn and exchanges:
                 the token account's oldest transactions (10 credits, once every profit_every_h = a week) -> first buy,
                 cost (SOL legs at that day's SOL/USD, DefiLlama free; transfers in at that day's close from our daily
                 candles when we have them, else unknown) -> holder_pos (cost_usd, value_usd, mult, known_cost share)
                 diamond = value >= diamond_min_usd ($25k), held >= diamond_min_days (30), mult >= diamond_min_mult (2x)
                 with at least half of the cost known
  2. buys        every buys_every_h (24 h) each diamond's swaps of the last buys_days (7) (10 credits): what it bought
                 (any market cap: measuring microcaps is allowed for research, TRADING them stays blocked) -> holder_buys
                 (wallet, cluster, token, ts, sol, usd, tokens, mc_at_buy, src_mint, sig); mc_at_buy = MC now x (price
                 paid / price now), DexScreener free
  3. clusters    union of: the same first funder (10 credits, cached a week), co-buying the same token within cobuy_min
                 (10) minutes, a transfer between them -> cluster id "k" + the smallest wallet's first 8 characters
  4. digest      "Što kupuju profitabilni holderi": tokens bought by >= follow_min_clusters (2) clusters in 7 days with MC,
                 liquidity, holders, clusters, first buy; the first time a token qualifies it goes to `follow` with the
                 price then and the round-trip cost at follow_size_sol (veliki/rule.cost_at); 1 h / 24 h / 7 d later the
                 price (DexScreener) -> the measurement (rule fixed before the data: enter when it qualifies; demo only,
                 no real money, no trade at all on microcaps)
"""
import hashlib
import json
import time

from holderi import chain, store

PREFIX = "holderi (profitabilni): "
FETCH = {}   # tests: "table" () -> [{mint, symbol, cat}], "dex" (mints) -> {mint: (px, mc, liq, symbol)},
#              "sol_usd" -> fn(ts), "px_day" (mint, ts) -> px
SKIP = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}


def established(n):
    """[{mint, symbol, cat}] of the veliki table (A, B, C), else the veliki list."""
    if "table" in FETCH:
        return FETCH["table"]()[:n]
    out = []
    try:
        from veliki import view as vview
        tab = vview.summary(zones=False).get("table") or []
        out = sorted(({"mint": x["mint"], "symbol": x.get("symbol"), "cat": x.get("cat")} for x in tab if x.get("mint")),
                     key=lambda x: {"A": 0, "B": 1}.get(x["cat"], 2))
    except Exception:  # noqa: BLE001
        out = []
    if not out:
        try:
            from veliki import store as vstore
            out = [{"mint": x["mint"], "symbol": x.get("symbol"), "cat": None} for x in (vstore.the_list() or {}).get("tokens") or []]
        except Exception:  # noqa: BLE001
            out = []
    # 15.11. (vlasnik: "i za ove nove tokene i volete koji ih drže, isto njih prati"): after the veliki table, every
    # member of the midcap collector (2M-200M, by 24 h volume), so the new trending midcaps get their holders too
    if len(out) < n:
        try:
            from veliki import midcap
            have = {x["mint"] for x in out}
            out += [{"mint": x["mint"], "symbol": x.get("symbol"), "cat": None} for x in midcap.members()
                    if x.get("mint") and x["mint"] not in have]
        except Exception:  # noqa: BLE001 - no collector: the table alone
            pass
    return out[:n]


def dex(mints):
    """{mint: (price, mc, liq, symbol)} from DexScreener (free), the deepest pool."""
    mints = [m for m in dict.fromkeys(mints) if m]
    if not mints:
        return {}
    if "dex" in FETCH:
        return FETCH["dex"](mints)
    out = {}
    try:
        from dexscreener import client
        for p in client.tokens("solana", mints):
            m = ((p or {}).get("baseToken") or {}).get("address")
            liq = float(((p or {}).get("liquidity") or {}).get("usd") or 0)
            if m in mints and liq >= (out.get(m) or (0, 0, -1))[2]:
                out[m] = (float(p.get("priceUsd") or 0), float(p.get("marketCap") or p.get("fdv") or 0), liq,
                          (p.get("baseToken") or {}).get("symbol"))
    except Exception:  # noqa: BLE001
        pass
    return out


def _sol_usd():
    if "sol_usd" in FETCH:
        return FETCH["sol_usd"]
    from wallets import rpc
    return rpc.sol_usd_history(400)


def px_day(mint, ts):
    """That day's close of `mint` from our daily candles (midcap.db, then veliki.db), None when unknown."""
    if "px_day" in FETCH:
        return FETCH["px_day"](mint, ts)
    d = int(ts) // 86400 * 86400
    for mod in ("veliki.midcap", "veliki.store"):
        try:
            m = __import__(mod, fromlist=["ro"])
            con = m.ro()
            if con is None:
                continue
            try:
                r = con.execute("SELECT c FROM c1d WHERE token=? AND ts BETWEEN ? AND ? ORDER BY ts LIMIT 1",
                                (mint, d - 86400, d + 86400)).fetchone()
            finally:
                con.close()
            if r and r[0]:
                return float(r[0])
        except Exception:  # noqa: BLE001
            continue
    return None


def cost_basis(txs, wallet, mint, sol_usd):
    """{"first_ts", "bought", "known_tokens", "known_cost_usd", "avg_cost"} of a wallet's inflows of `mint`."""
    from wallets import rpc
    first, bought, known_t, known_c = None, 0.0, 0.0, 0.0
    for tx in sorted(txs or [], key=chain.tx_ts):
        for r in rpc.parse(tx, wallet, sol_usd):
            if r["mint"] != mint or r["tokens"] <= 0:
                continue
            first = first or r["ts"]
            bought += r["tokens"]
            if r["kind"] == "buy":
                rate = sol_usd(r["ts"]) if callable(sol_usd) else sol_usd
                if rate:
                    known_t += r["tokens"]
                    known_c += -r["sol"] * rate
            else:
                p = px_day(mint, r["ts"])
                if p:
                    known_t += r["tokens"]
                    known_c += r["tokens"] * p
    return {"first_ts": first, "bought": bought, "known_tokens": known_t, "known_cost_usd": known_c,
            "avg_cost": known_c / known_t if known_t else None}


def positions(con, c, now, budget, toks, log=print):
    """Step 1 (see the module text). n positions refreshed this pass (at most profit_pass)."""
    px = dex([t["mint"] for t in toks])
    sol_usd = None
    n = 0
    for t in toks:
        pts = con.execute("SELECT MAX(ts) FROM profile WHERE mint=?", (t["mint"],)).fetchone()[0]
        if not pts or t["mint"] not in px:
            continue
        p_now = px[t["mint"]][0]
        rows = [r for r in store.snap_rows(con, t["mint"], pts) if r["cls"] not in ("lp", "burn", "exchange")]
        for r in rows[:int(c["profit_holders"])]:
            old = con.execute("SELECT ts FROM holder_pos WHERE wallet=? AND mint=?", (r["owner"], t["mint"])).fetchone()
            if old and now - old[0] < float(c["profit_every_h"]) * 3600:
                continue
            if n >= int(c.get("profit_pass") or 40):
                return n
            sol_usd = sol_usd or _sol_usd()
            try:
                txs = chain.history(r["acct"] or r["owner"], budget)
            except Exception:  # noqa: BLE001
                txs = None
            if txs is None:
                return n
            cb = cost_basis(txs, r["owner"], t["mint"], sol_usd)
            amt = float(r["amount"] or 0)
            value = amt * p_now
            known = cb["known_tokens"] / cb["bought"] if cb["bought"] else 0.0
            cost = cb["avg_cost"] * amt if cb["avg_cost"] else None
            mult = value / cost if cost else None
            held_d = (now - cb["first_ts"]) / 86400 if cb["first_ts"] else None
            dia = int(bool(value >= float(c["diamond_min_usd"]) and held_d is not None
                           and held_d >= float(c["diamond_min_days"]) and mult and mult >= float(c["diamond_min_mult"])
                           and known >= 0.5))
            con.execute("INSERT OR REPLACE INTO holder_pos (wallet, mint, ts, amount, pct, first_ts, cost_usd, value_usd, "
                        "mult, known_cost, funder, cluster, diamond) VALUES (?,?,?,?,?,?,?,?,?,?,"
                        "(SELECT funder FROM holder_pos WHERE wallet=? AND mint=?),"
                        "(SELECT cluster FROM holder_pos WHERE wallet=? AND mint=?),?)",
                        (r["owner"], t["mint"], int(now), amt, r["pct"], cb["first_ts"],
                         None if cost is None else round(cost, 2), round(value, 2),
                         None if mult is None else round(mult, 2), round(known, 2), r["owner"], t["mint"], r["owner"],
                         t["mint"], dia))
            n += 1
        con.commit()
    return n


def diamonds(con):
    """{wallet: [src mints]} of the diamond holders."""
    out = {}
    for w, m in con.execute("SELECT wallet, mint FROM holder_pos WHERE diamond=1"):
        out.setdefault(w, []).append(m)
    return out


def buys(con, c, now, budget, log=print):
    """Step 2 (see the module text): the diamonds' swaps of the last buys_days -> holder_buys. n wallets read."""
    from wallets import rpc
    dia = diamonds(con)
    if not dia:
        return 0
    sol_usd = None
    n = 0
    links = store.kv_get(con, "links", []) or []
    for w, srcs in sorted(dia.items()):
        last = store.kv_get(con, f"buys_ts:{w}", 0) or 0
        if now - int(last) < float(c["buys_every_h"]) * 3600:
            continue
        if n >= int(c.get("profit_pass") or 40):
            break
        try:
            txs = chain.txs(w, int(now - float(c["buys_days"]) * 86400), budget)
        except Exception:  # noqa: BLE001
            txs = None
        if txs is None:
            break
        sol_usd = sol_usd or _sol_usd()
        rows = []
        for tx in txs:
            keys = set(chain._keys(tx))
            for o in dia:
                if o != w and o in keys and [min(w, o), max(w, o)] not in links:
                    links.append([min(w, o), max(w, o)])
            for r in rpc.parse(tx, w, sol_usd):
                if r["kind"] != "buy" or r["mint"] in SKIP or r["mint"] in srcs or r["tokens"] <= 0:
                    continue
                rate = sol_usd(r["ts"]) if callable(sol_usd) else sol_usd
                rows.append((w, None, r["mint"], int(r["ts"]), round(-r["sol"], 6),
                             round(-r["sol"] * rate, 2) if rate else None, r["tokens"], None, srcs[0], r["sig"]))
        con.executemany("INSERT OR IGNORE INTO holder_buys VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        store.kv_put(con, f"buys_ts:{w}", int(now))
        n += 1
    store.kv_put(con, "links", links[-2000:])
    # mc at the buy for the rows without it: MC now x price paid / price now (DexScreener, free)
    need = con.execute("SELECT DISTINCT token FROM holder_buys WHERE mc_at_buy IS NULL AND ts >= ?",
                       (int(now) - 8 * 86400,)).fetchall()
    px = dex([t for (t,) in need])
    for tok, (p, mc, _liq, _sym) in px.items():
        if p and mc:
            con.execute("UPDATE holder_buys SET mc_at_buy = ROUND(? * (usd / tokens) / ?) WHERE token=? AND "
                        "mc_at_buy IS NULL AND usd IS NOT NULL AND tokens > 0", (mc, p, tok))
    con.commit()
    return n


def clusters(con, c, now, budget):
    """Step 3: union-find over the diamonds; writes holder_pos.cluster and holder_buys.cluster. {wallet: cluster}."""
    from holderi import run as hrun
    dia = sorted(diamonds(con))
    parent = {w: w for w in dia}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    fund = {}
    for w in dia:
        f = hrun.get_funder(con, w, budget, now)
        if f:
            fund.setdefault(f, []).append(w)
            if f in parent:
                union(f, w)
    for ws in fund.values():
        for o in ws[1:]:
            union(ws[0], o)
    win = float(c["cobuy_min"]) * 60
    by_tok = {}
    for w, tok, ts in con.execute("SELECT wallet, token, ts FROM holder_buys WHERE ts >= ?", (int(now) - 30 * 86400,)):
        if w in parent:
            by_tok.setdefault(tok, []).append((ts, w))
    for rows in by_tok.values():
        rows.sort()
        for (t1, w1), (t2, w2) in zip(rows, rows[1:]):
            if w1 != w2 and t2 - t1 <= win:
                union(w1, w2)
    for a, b in store.kv_get(con, "links", []) or []:
        if a in parent and b in parent:
            union(a, b)
    out = {w: "k" + find(w)[:8] for w in dia}
    for w, k in out.items():
        con.execute("UPDATE holder_pos SET cluster=? WHERE wallet=?", (k, w))
        con.execute("UPDATE holder_buys SET cluster=? WHERE wallet=?", (k, w))
    con.commit()
    return out


def digest(con, c, now):
    """Step 4: [{token, symbol, clusters, holders, first_buy_ts, usd, mc, liq, mc_at_first}] bought by >= 2 clusters."""
    rows = {}
    for tok, k, w, ts, usd, mcb in con.execute(
            "SELECT token, cluster, wallet, ts, usd, mc_at_buy FROM holder_buys WHERE ts >= ? AND cluster IS NOT NULL",
            (int(now - float(c["buys_days"]) * 86400),)):
        r = rows.setdefault(tok, {"token": tok, "clusters": set(), "holders": set(), "first_buy_ts": ts, "usd": 0.0,
                                  "mc_at_first": mcb})
        r["clusters"].add(k)
        r["holders"].add(w)
        r["usd"] += usd or 0
        if ts < r["first_buy_ts"]:
            r["first_buy_ts"], r["mc_at_first"] = ts, mcb
    out = [r for r in rows.values() if len(r["clusters"]) >= int(c["follow_min_clusters"])]
    px = dex([r["token"] for r in out])
    for r in out:
        p = px.get(r["token"]) or (None, None, None, None)
        r.update(clusters=len(r["clusters"]), holders=len(r["holders"]), usd=round(r["usd"], 2), px=p[0], mc=p[1],
                 liq=p[2], symbol=p[3])
    out.sort(key=lambda r: (-r["clusters"], -r["holders"], -r["usd"]))
    store.kv_put(con, "digest", {"ts": int(now), "rows": out[:30]})
    for r in out:
        if r["px"] and not con.execute("SELECT 1 FROM follow WHERE token=?", (r["token"],)).fetchone():
            try:
                from veliki import rule
                rt = rule.cost_at(float(c["follow_size_sol"]), r["liq"])["rt"]
            except Exception:  # noqa: BLE001
                rt = None
            con.execute("INSERT INTO follow (token, symbol, ts, first_buy_ts, clusters, holders, mc, liq, px, cost_rt) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", (r["token"], r["symbol"], int(now), r["first_buy_ts"],
                                                         r["clusters"], r["holders"], r["mc"], r["liq"], r["px"], rt))
    con.commit()
    return out


def follow_outcomes(con, now):
    """1 h / 24 h / 7 d prices of the followed tokens (DexScreener, free; read within 2 h of the due time, else -1)."""
    rows = con.execute("SELECT token, ts, px_1h, px_24h, px_7d FROM follow WHERE px_7d IS NULL").fetchall()
    due = []
    for tok, ts, *have in rows:
        for (name, h), v in zip((("1h", 3600), ("24h", 86400), ("7d", 7 * 86400)), have):
            if v is None and now >= ts + h:
                due.append((tok, name, now - (ts + h) <= 2 * 3600))
    if not due:
        return 0
    px = dex([d[0] for d in due if d[2]])
    for tok, name, fresh in due:
        p = (px.get(tok) or (None,))[0] if fresh else None
        con.execute(f"UPDATE follow SET px_{name}=? WHERE token=?", (p if p else -1, tok))
    con.commit()
    return len(due)


def measure(con):
    """{h: {"n", "hit", "ev_pct"}} of the followed tokens net of the round-trip cost (the rule fixed in advance)."""
    out = {}
    for name in ("1h", "24h", "7d"):
        rets = [(b / a - 1) - (rt or 0.02) for a, b, rt in con.execute(
            f"SELECT px, px_{name}, cost_rt FROM follow WHERE px > 0 AND px_{name} > 0")]
        if rets:
            out[name] = {"n": len(rets), "hit": round(sum(1 for r in rets if r > 0) / len(rets), 2),
                         "ev_pct": round(sum(rets) / len(rets) * 100, 2)}
        else:
            out[name] = {"n": 0}
    return out


def run(con, c, now, budget, reg, log=print):
    """Steps 1-4 within the cap, by their own clocks. {"positions", "buys", "diamonds", "digest"}."""
    toks = established(int(c["profit_tokens"]))
    out = {"positions": positions(con, c, now, budget, toks, log) if toks else 0}
    out["buys"] = buys(con, c, now, budget, log)
    if now - int(store.kv_get(con, "clusters_ts", 0) or 0) >= 3600 or out["buys"]:
        cl = clusters(con, c, now, budget)
        out["diamonds"] = len(cl)
        d = digest(con, c, now)
        out["digest"] = len(d)
        store.kv_put(con, "clusters_ts", int(now))
        if d and now - int(store.kv_get(con, "digest_said", 0) or 0) >= 86400:
            store.kv_put(con, "digest_said", int(now))
            log(PREFIX + "Što kupuju profitabilni holderi: " + ", ".join(
                f"{r.get('symbol') or r['token'][:6]} ({r['clusters']} klastera, {r['holders']} holdera, MC "
                f"${(r.get('mc') or 0) / 1e6:,.2f}M)" for r in d[:8]))
    out["follow"] = follow_outcomes(con, now)
    con.commit()
    return out


def cluster_id(wallet):
    return "k" + hashlib.sha1(wallet.encode()).hexdigest()[:8]


def summary(con, now=None, limit=30):
    """For the MCP tool / card / critic: diamonds, clusters, the digest, the measurement."""
    now = int(now or time.time())
    dia = [dict(zip(("wallet", "mint", "amount", "pct", "first_ts", "cost_usd", "value_usd", "mult", "known_cost",
                     "cluster"), r)) for r in con.execute(
        "SELECT wallet, mint, amount, pct, first_ts, cost_usd, value_usd, mult, known_cost, cluster FROM holder_pos "
        "WHERE diamond=1 ORDER BY value_usd DESC LIMIT ?", (int(limit),))]
    n_pos = con.execute("SELECT COUNT(*), SUM(diamond) FROM holder_pos").fetchone()
    d = store.kv_get(con, "digest", {}) or {}
    for r in d.get("rows") or []:
        r.pop("clusters_set", None)
    recent = [dict(zip(("wallet", "cluster", "token", "ts", "sol", "usd", "mc_at_buy", "src_mint"), r)) for r in con.execute(
        "SELECT wallet, cluster, token, ts, sol, usd, mc_at_buy, src_mint FROM holder_buys ORDER BY ts DESC LIMIT ?",
        (int(limit),))]
    return {"positions_measured": n_pos[0] or 0, "diamonds": n_pos[1] or 0, "diamond_rows": dia,
            "digest": d.get("rows") or [], "digest_ts": d.get("ts"), "recent_buys": recent, "follow": measure(con),
            "follow_n": con.execute("SELECT COUNT(*) FROM follow").fetchone()[0]}


def json_rows(rows):
    return json.loads(json.dumps(rows, default=list))
