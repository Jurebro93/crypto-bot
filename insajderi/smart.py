"""The "pametni novac" list (15.11. extension): wallets that are
  (a) early buyers across several jumps (bought before t0 of >= smart_min_jumps events; selling into them counts more),
  (b) insiders before calls (score.py: insajder, confirmed or not),
  (c) profitable large holders of established midcaps, from the listing agent's table when it exists (any table with
      'holder' in its name with a wallet column and a profit column in listing.db); skipped otherwise,
minus bots, snipers and relayers, in CLUSTERS: one owner (same funder: chain.owners) and owners that co-buy the same
tokens within cluster_gap_s (5 min) on >= cluster_min_tokens tokens.

Signal: >= signal_min_clusters independent clusters' smart wallets buy the same token within signal_window_s; measured
walk-forward (the smart set of day D from the events before D only; our entry after the k-th cluster's buy + delay,
exit when one of them sells / stop / time, net of cost: copy.simulate). Demo only; never real money.
"""
import hashlib
import json
from collections import Counter, defaultdict

from insajderi import copy, score, store


def _cid(members):
    return "k" + hashlib.sha1(",".join(sorted(members)).encode()).hexdigest()[:8]


def holder_profit(listing_db):
    """{wallet: profit} from the listing agent's holder table when present; {} otherwise."""
    con = store.ro(listing_db)
    out = {}
    for (name,) in store.q(con, "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%holder%'"):
        cols = [r[1] for r in store.q(con, f"PRAGMA table_info({name})")]
        wc = "wallet" if "wallet" in cols else "owner" if "owner" in cols else None
        pc = next((x for x in ("profit_usd", "pnl_usd", "profit", "pnl", "realized_usd") if x in cols), None)
        if not wc or not pc:
            continue
        for w, v in store.q(con, f"SELECT {wc}, MAX({pc}) FROM {name} GROUP BY {wc}"):
            if w and v is not None and v > 0:
                out[w] = max(out.get(w, 0), float(v))
    if con is not None:
        con.close()
    return out


def roles(stats, events, parts, as_of, c, hp=None):
    """{owner: {"members", "roles", "n_jumps", "n_sold", "score"}} of the smart owners known at as_of (pure)."""
    ev = {e["eid"]: e for e in events if e["win_end"] < as_of}
    early, sold = defaultdict(set), defaultdict(set)
    members = defaultdict(set)
    for r in parts:
        if r[0] not in ev:
            continue
        o = r[2] or r[1]
        members[o].add(r[1])
        if r[8]:
            early[o].add(r[0])
            if r[9]:
                sold[o].add(r[0])
    out = {}
    for o, eids in early.items():
        st = stats.get(o) or {}
        if st.get("cls") in score.OUT or o.startswith("relayer:"):
            continue
        rl = []
        if len(eids) >= int(c["smart_min_jumps"]):
            rl.append("rani kupac skokova")
        if st.get("cls") == "insajder":
            rl.append("insajder prije poziva" + (" (potvrđen)" if st.get("confirmed") else ""))
        prof = sum((hp or {}).get(w, 0) for w in members[o])
        if prof > 0:
            rl.append("profitabilni holder")
        if not rl:
            continue
        sc = len(eids) + len(sold[o]) + (3 if st.get("confirmed") else 1 if st.get("cls") == "insajder" else 0) + \
            (1 if prof > 0 else 0)
        out[o] = {"members": sorted(members[o]), "roles": rl, "n_jumps": len(eids), "n_sold": len(sold[o]),
                  "score": sc, "holder_profit": prof or None}
    for w, v in (hp or {}).items():   # (c) alone: a profitable holder we never saw early
        if not any(w in x["members"] for x in out.values()):
            out.setdefault(w, {"members": [w], "roles": ["profitabilni holder"], "n_jumps": 0, "n_sold": 0, "score": 1,
                               "holder_profit": v})
    return out


def clusters(owners_members, trades, c):
    """{owner: cluster id}: owners that bought the same token within cluster_gap_s on >= cluster_min_tokens tokens are
    one cluster (one owner alone is its own)."""
    from kol import together
    owner_of = {w: o for o, ms in owners_members.items() for w in ms}
    first = {}
    for w, m, ts, side, _s, _t in trades:
        o = owner_of.get(w)
        if o and side == "buy" and (o, m) not in first:
            first[(o, m)] = ts
    by_tok = defaultdict(list)
    for (o, m), ts in first.items():
        by_tok[m].append((ts, o))
    pair = Counter()
    gap = int(c["cluster_gap_s"])
    for m, xs in by_tok.items():
        xs.sort()
        for i, (ta, a) in enumerate(xs):
            for tb, b in xs[i + 1:]:
                if tb - ta > gap:
                    break
                if a != b:
                    pair[tuple(sorted((a, b)))] += 1
    links = [(a, b) for (a, b), n in pair.items() if n >= int(c["cluster_min_tokens"])]
    out = {o: o for o in owners_members}
    for comp in together.components(links):
        cid = _cid(comp)
        for o in comp:
            out[o] = cid
    return {o: (v if v != o else _cid([o])) for o, v in out.items()}


def signals(smart_members, cl, trades, c, since, until):
    """[(token, ts, [cluster ids])]: the first time >= signal_min_clusters clusters' smart wallets bought one token
    within signal_window_s, in [since, until)."""
    owner_of = {w: o for o, ms in smart_members.items() for w in ms}
    first = {}
    for w, m, ts, side, _s, _t in trades:
        o = owner_of.get(w)
        if o and side == "buy":
            k = (cl.get(o, o), m)
            if k not in first or ts < first[k]:
                first[k] = ts
    by_tok = defaultdict(list)
    for (k, m), ts in first.items():
        by_tok[m].append((ts, k))
    out = []
    need, win = int(c["signal_min_clusters"]), int(c["signal_window_s"])
    for m, xs in by_tok.items():
        xs.sort()
        for i in range(need - 1, len(xs)):
            ts, _k = xs[i]
            grp = [k for t, k in xs[:i + 1] if ts - t <= win]
            if len(set(grp)) >= need:
                if since <= ts < until:
                    out.append((m, ts, sorted(set(grp))))
                break
    return out


def run(con, p, c, now, stats, events, parts):
    """The list, the clusters, the walk-forward of the signal and what they buy now -> summary dict."""
    hp = holder_profit(p.get("listing_db"))
    cur = roles(stats, events, parts, now + 1, c, hp)
    allw = {w for x in cur.values() for w in x["members"]}
    trades = copy.wallet_trades(con, p, allw) if allw else []
    cl = clusters({o: x["members"] for o, x in cur.items()}, trades, c)
    last = {}
    for w, m, ts, side, _s, _t in trades:
        if side == "buy":
            last[w] = (ts, m)
    con.execute("DELETE FROM i2_smart")
    rows = []
    for o, x in cur.items():
        for w in x["members"]:
            lb = last.get(w, (None, None))
            rows.append((w, o, cl.get(o), json.dumps(x["roles"], ensure_ascii=False), x["score"], x["n_jumps"],
                         int(any("insajder" in r for r in x["roles"])), x["holder_profit"], lb[0], lb[1], int(now)))
    con.executemany("INSERT OR REPLACE INTO i2_smart VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    # walk-forward of the signal
    sig_rows = []
    if events:
        start = min(e["t0"] for e in events) + int(c["warmup_days"]) * 86400
        d = start - start % 86400 + 86400
        by_w = defaultdict(list)
        for t in trades:
            by_w[t[0]].append(t)
        pr = None
        rt = copy.cost_rt(c)
        while d <= now:
            st = score.classify(parts, events, d, c)
            sm = roles(st, events, parts, d, c, hp)
            if sm:
                mem = {o: x["members"] for o, x in sm.items()}
                cld = clusters(mem, [t for t in trades if t[2] < d], c)
                for tok, ts, ks in signals(mem, cld, trades, c, d, min(d + 86400, now)):
                    if pr is None:
                        pr = copy.Prices(con, p, c, {t[1] for t in trades})
                    ws = {w for o, ms in mem.items() if cld.get(o, o) in ks for w in ms}
                    sells = sorted((t for w in ws for t in by_w.get(w, []) if t[1] == tok and t[3] == "sell" and t[2] > ts),
                                   key=lambda t: t[2])
                    sim = copy.simulate((None, tok, ts, "buy", None, None), sells, pr, c, rt)
                    sig_rows.append((tok, ts, len(ks), json.dumps(ks), sim and sim["mcap"], sim and sim["ret"],
                                     sim and sim["exit"]))
            d += 86400
    con.execute("DELETE FROM i2_signals")
    con.executemany("INSERT OR REPLACE INTO i2_signals VALUES (?,?,?,?,?,?,?)", sig_rows)
    con.commit()
    from trade import edge
    rets = [r[5] for r in sig_rows if r[5] is not None]
    s = edge.ev_stats(rets)
    pct = (lambda v: None if v is None else round(v * 100, 2))
    mem = {o: x["members"] for o, x in cur.items()}
    now_sig = [{"token": t, "ts": ts, "n_clusters": len(ks), "clusters": ks}
               for t, ts, ks in signals(mem, cl, trades, c, now - 6 * 3600, now + 1)]
    top = sorted(rows, key=lambda r: -r[4])[:20]
    return {"n_wallets": len(rows), "n_owners": len(cur), "n_clusters": len(set(cl.values())),
            "min_clusters": int(c["signal_min_clusters"]), "holder_table": bool(hp),
            "signal": {"n": s["n"], "ev_pct": pct(s["ev"]), "ci90_lo_pct": pct(s["lo90"]),
                       "hit_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1) if rets else None,
                       "signals": len(sig_rows)},
            "top": [{"wallet": r[0], "owner": r[1], "cluster": r[2], "roles": json.loads(r[3]), "score": r[4],
                     "last_buy_ts": r[8], "last_token": r[9]} for r in top],
            "now": now_sig[:20]}
