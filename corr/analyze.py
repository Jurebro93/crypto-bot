"""Cross-signal correlations from data the bot already has (no API calls):

  1. KOL clusters      X accounts (and Telegram channels, if collected) that keep calling the same tokens within
                       minutes of each other; leader, spread, outcome vs. the same accounts calling alone.
  2. Wallet <-> KOL    wallets that buy a token shortly before a given account calls it, on several tokens, and
                       sell into the call: the account's own wallet, its paymaster, or someone it tips off.
  3. Owner groups      wallets that look like one owner: same funding source, bought in the same second
                       (bundle) on several tokens, or put in one cluster by the rug check.
  4. Pump factors      for KOL-called tokens: how much more often a token doubled with each signal than without.
  5. Active now        tokens a known cluster or owner group is touching in the last hours.

Everything is read-only from kol.db, wallets.db, rug.db, hype.db. Pure functions take plain lists so the tests
can feed synthetic data; load_* functions read the databases.
"""
import hashlib
import json
import os
import sqlite3
import statistics
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "corr", "config.json")


def cfg():
    with open(CONFIG) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _share(xs):
    xs = [x for x in xs if x is not None]
    return sum(1 for x in xs if x) / len(xs) if xs else None


# ---------------------------------------------------------------- loading

def load_calls(kol_db):
    """First real call (not a brag) per (account, token): dicts handle, token, ts, max24, r1h, pre2h, views,
    followers, url, symbol."""
    con = _ro(kol_db)
    if con is None:
        return []
    try:
        syms = dict(con.execute("SELECT token, symbol FROM tokens"))
        rows = con.execute("""SELECT handle, token, MIN(ts), max24, r1h, pre2h, views, followers, url, symbol
                              FROM calls WHERE kind='call' GROUP BY handle, token""").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [{"handle": h, "token": t, "ts": ts, "max24": m, "r1h": r1, "pre2h": p, "views": v, "followers": f,
             "url": u, "symbol": s or syms.get(t), "src": "x"} for h, t, ts, m, r1, p, v, f, u, s in rows]


def load_tg(hype_db):
    """Telegram channel posts with a contract address, as calls by 'tg:<channel>' (no price outcome)."""
    import datetime as dt
    con = _ro(hype_db)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT channel, time, ca FROM tg_mentions WHERE ca IS NOT NULL AND ca != ''").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    first = {}
    for ch, when, ca in rows:
        try:
            ts = int(dt.datetime.fromisoformat(str(when).replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
        k = ("tg:" + ch, ca)
        first[k] = min(first.get(k, ts), ts)
    return [{"handle": h, "token": t, "ts": ts, "max24": None, "r1h": None, "pre2h": None, "views": None,
             "followers": None, "url": f"https://t.me/{h[3:]}", "symbol": None, "src": "tg"}
            for (h, t), ts in first.items()]


def load_trades(wallet_db, kol_db=None, days=30, now=None):
    """Buys and sells of the last `days`: [(wallet, mint, ts, kind, sol)] from wallets.db wallet_trades plus kol.db
    insiders (Helius flows around calls). Bounded so the run stays small in memory on the server."""
    out = []
    since = int((now or time.time()) - days * 86400)
    con = _ro(wallet_db)
    if con is not None:
        try:
            out += con.execute("SELECT wallet, mint, ts, kind, ABS(COALESCE(sol, 0)) FROM wallet_trades "
                               "WHERE kind IN ('buy', 'sell') AND ts >= ?", (since,)).fetchall()
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    con = _ro(kol_db)
    if con is not None:
        try:
            for w, t, b, s, si, so in con.execute(
                    "SELECT wallet, token, bought_ts, sold_ts, sol_in, sol_out FROM insiders"):
                if b:
                    out.append((w, t, b, "buy", si or 0))
                if s:
                    out.append((w, t, s, "sell", so or 0))
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    return out


def load_wallet_info(wallet_db):
    """wallet -> {labels, score, realized_sol, style}, and funding edges [(funder, wallet)] from sightings."""
    info, edges = {}, []
    con = _ro(wallet_db)
    if con is None:
        return info, edges
    try:
        for w, labels, score, stats in con.execute("SELECT wallet, labels, score, stats FROM wallets"):
            st = json.loads(stats or "{}")
            info[w] = {"labels": json.loads(labels or "[]"), "score": score,
                       "realized_sol": st.get("realized_sol"), "style": st.get("style")}
        for w, extra in con.execute("SELECT wallet, extra FROM wallet_sightings WHERE extra LIKE '%funde%'"):
            try:
                x = json.loads(extra)
            except ValueError:
                continue
            if x.get("funder"):
                edges.append((x["funder"], w))
            if x.get("funded"):
                edges.append((w, x["funded"]))
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    return info, edges


def load_rug(rug_db, max_reports=3000):
    """From the newest rug reports: funding edges [(funder, wallet)], rug clusters [[wallets]], hubs (exchange-like
    funders the rug check already recognised) and per-token flags {mint: {bundle_pct, dev}}."""
    edges, clusters, hubs, flags = [], [], set(), {}
    con = _ro(rug_db)
    if con is None:
        return edges, clusters, hubs, flags
    try:
        rows = con.execute("SELECT mint, data FROM rug_reports WHERE data IS NOT NULL ORDER BY checked_at DESC LIMIT ?",
                           (max_reports,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    for mint, data in rows:
        try:
            d = json.loads(data)
        except ValueError:
            continue
        for w in d.get("wallets") or []:
            if isinstance(w, dict) and w.get("funder") and w.get("wallet"):
                edges.append((w["funder"], w["wallet"]))
        cl = (d.get("cluster") or {}).get("wallets") or []
        if len(cl) >= 2:
            clusters.append(cl)
        hubs.update(d.get("hubs") or [])
        if mint not in flags:
            la = d.get("launch") or {}
            flags[mint] = {"bundle_pct": la.get("bundle_pct"), "dev": la.get("dev") or (d.get("dev") or {}).get("wallet")}
    return edges, clusters, hubs, flags


# ---------------------------------------------------------------- 1. KOL clusters

def pair_stats(calls, c):
    """Per account: tokens called. Per pair (a, b), a < b: tokens called by both within window_secs, who was first,
    minutes between them."""
    by_tok = defaultdict(list)
    n_calls = Counter()
    for x in calls:
        by_tok[x["token"]].append(x)
        n_calls[x["handle"]] += 1
    pairs = defaultdict(lambda: {"tokens": set(), "a_first": 0, "gaps": []})
    for tok, xs in by_tok.items():
        xs.sort(key=lambda x: x["ts"])
        xs = xs[:c["max_authors_per_token"]]
        for i, x in enumerate(xs):
            for y in xs[i + 1:]:
                if y["ts"] - x["ts"] > c["window_secs"]:
                    break
                if x["handle"] == y["handle"]:
                    continue
                a, b = sorted((x["handle"], y["handle"]))
                p = pairs[(a, b)]
                if tok in p["tokens"]:
                    continue
                p["tokens"].add(tok)
                p["a_first"] += x["handle"] == a
                p["gaps"].append((y["ts"] - x["ts"]) / 60)
    n_tok = max(1, len(by_tok))
    for (a, b), p in pairs.items():
        n = len(p["tokens"])
        p["n"] = n
        p["jaccard"] = n / max(1, n_calls[a] + n_calls[b] - n)
        p["overlap"] = n / max(1, min(n_calls[a], n_calls[b]))           # share of the smaller account's calls
        p["lift"] = n / max(1e-9, n_calls[a] * n_calls[b] / n_tok)        # vs. two accounts picking tokens at random
    return n_calls, dict(pairs)


def _components(nodes, edges):
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comp = defaultdict(set)
    for n in nodes:
        comp[find(n)].add(n)
    return [s for s in comp.values() if len(s) >= 2]


def clusters_from_pairs(pairs, c):
    """Connected groups of strong pairs. A group bigger than max_cluster is split again with a stricter
    threshold, so one busy shill account does not glue 50 unrelated accounts together."""
    def split(nodes, jmin):
        es = [(a, b) for (a, b), p in pairs.items() if a in nodes and b in nodes
              and p["n"] >= c["min_together"] and p["overlap"] >= jmin and p["lift"] >= c["min_lift"]]
        out = []
        for comp in _components({n for e in es for n in e}, es):
            if len(comp) > c["max_cluster"] and jmin < 0.9:
                out += split(comp, jmin + 0.08)
            else:
                out.append(comp)
        return out
    nodes = {n for pair in pairs for n in pair}
    return split(nodes, c["min_overlap"])


def describe_cluster(members, calls, pairs, c):
    """Tokens the members called together, leader, timing, outcome vs. their solo calls, organisation score."""
    mine = [x for x in calls if x["handle"] in members]
    by_tok = defaultdict(list)
    for x in mine:
        by_tok[x["token"]].append(x)
    together, solo = [], []
    for tok, xs in by_tok.items():
        xs.sort(key=lambda x: x["ts"])
        hs = {x["handle"] for x in xs if x["ts"] - xs[0]["ts"] <= c["window_secs"]}
        (together if len(hs) >= 2 else solo).append((tok, xs, hs))
    firsts = Counter(xs[0]["handle"] for _, xs, _ in together)
    spreads = [(max(x["ts"] for x in xs if x["handle"] in hs) - xs[0]["ts"]) / 60 for _, xs, hs in together]
    t_out = [xs[0]["max24"] for _, xs, _ in together]
    s_out = [xs[0]["max24"] for _, xs, _ in solo]
    t_late = [None if xs[0]["pre2h"] is None else xs[0]["pre2h"] >= c["late_pre2h"] for _, xs, _ in together]
    pump = c["pump_x"]
    hit_t = _share([None if m is None else m >= pump for m in t_out])
    hit_s = _share([None if m is None else m >= pump for m in s_out])
    ps = [p for (a, b), p in pairs.items() if a in members and b in members]
    cohesion = statistics.mean(p["overlap"] for p in ps) if ps else 0
    spread = _med(spreads)
    tight = 1.0 if spread is None else max(0.0, min(1.0, 1 - (spread - 5) / 115))   # 5 min -> 1, 2 h -> 0
    rep = min(1.0, len(together) / 15)
    leader, lead_n = (firsts.most_common(1)[0] if firsts else (None, 0))
    srcs = {m.split(":")[0] if m.startswith("tg:") else "x" for m in members}
    key = hashlib.sha1(",".join(sorted(members)).encode()).hexdigest()[:8]
    return {
        "id": "k" + key, "members": sorted(members), "size": len(members), "tokens": len(together),
        "cross_platform": len(srcs) > 1,
        "leader": leader, "leader_share": round(lead_n / len(together), 2) if together else None,
        "spread_min": None if spread is None else round(spread, 1),
        "hit_together": None if hit_t is None else round(hit_t, 2), "n_together_measured": sum(m is not None for m in t_out),
        "hit_solo": None if hit_s is None else round(hit_s, 2), "n_solo_measured": sum(m is not None for m in s_out),
        "med_max24": None if _med(t_out) is None else round(_med(t_out), 2),
        "late_share": None if _share(t_late) is None else round(_share(t_late), 2),
        "cohesion": round(cohesion, 2),
        "score": round(100 * (0.4 * min(1.0, cohesion / 0.5) + 0.35 * tight + 0.25 * rep)),
        "last_ts": max((xs[0]["ts"] for _, xs, _ in together), default=None),
        "edges": sorted(([a, b, round(p["overlap"], 2), p["n"]] for (a, b), p in pairs.items()
                         if a in members and b in members and p["n"] >= 2), key=lambda e: -e[3])[:40],
        "examples": [{"token": tok, "symbol": xs[0].get("symbol"), "ts": xs[0]["ts"], "first": xs[0]["handle"],
                      "n": len(hs), "max24": xs[0]["max24"]}
                     for tok, xs, hs in sorted(together, key=lambda t: -t[1][0]["ts"])[:6]],
    }


# ---------------------------------------------------------------- 2. wallet <-> KOL links

def wallet_links(calls, trades, c, info=None):
    """(wallet, account) pairs where the wallet bought before the account's call on min_link_tokens+ tokens."""
    info = info or {}
    by_mint = defaultdict(list)
    called = {x["token"] for x in calls}
    for w, m, ts, kind, sol in trades:
        if m in called:
            by_mint[m].append((ts, w, kind, sol))
    for v in by_mint.values():
        v.sort()
    import bisect
    links = defaultdict(lambda: {"tokens": set(), "sold_into": set(), "leads": [], "sol_in": 0.0, "sol_out": 0.0})
    for x in calls:
        tr = by_mint.get(x["token"])
        if not tr:
            continue
        t0 = x["ts"]
        lo = bisect.bisect_left(tr, (t0 - c["wallet_pre_secs"],))
        hi = bisect.bisect_left(tr, (t0,))
        before = {}
        for ts, w, kind, sol in tr[lo:hi]:
            if kind == "buy":
                b = before.setdefault(w, [ts, 0.0])
                b[1] += sol
        if not before:
            continue
        end = bisect.bisect_right(tr, (t0 + c["wallet_post_secs"], "￿"))
        sold = defaultdict(float)
        for ts, w, kind, sol in tr[hi:end]:
            if kind == "sell" and w in before:
                sold[w] += sol
        for w, (ts, sol) in before.items():
            ln = links[(w, x["handle"])]
            ln["tokens"].add(x["token"])
            ln["leads"].append((t0 - ts) / 60)
            ln["sol_in"] += sol
            if w in sold:
                ln["sold_into"].add(x["token"])
                ln["sol_out"] += sold[w]
    n_calls = Counter(x["handle"] for x in calls)
    # how many called tokens each wallet bought at all: a sniper that buys every launch is "before" every call
    # by accident, a real link buys mostly the tokens this one account calls
    w_called = defaultdict(set)
    for m, tr in by_mint.items():
        for ts, w, kind, sol in tr:
            if kind == "buy":
                w_called[w].add(m)
    out = []
    for (w, h), ln in links.items():
        n = len(ln["tokens"])
        if n < c["min_link_tokens"]:
            continue
        share, prec = n / max(1, n_calls[h]), n / max(1, len(w_called[w]))
        strength = (share * prec) ** 0.5
        if strength < c["min_link_strength"] and len(ln["sold_into"]) < c["min_link_tokens"]:
            continue
        out.append({"wallet": w, "handle": h, "tokens": n, "of_calls": n_calls[h], "wallet_called": len(w_called[w]),
                    "strength": round(strength, 2),
                    "share": round(share, 2), "sold_into": len(ln["sold_into"]),
                    "lead_min": round(_med(ln["leads"]), 1), "sol_in": round(ln["sol_in"], 2),
                    "sol_out": round(ln["sol_out"], 2), "labels": (info.get(w) or {}).get("labels", []),
                    "token_list": sorted(ln["tokens"])[:10]})
    out.sort(key=lambda r: (-r["strength"] * r["tokens"], -r["sold_into"]))
    return out


# ---------------------------------------------------------------- 3. owner groups

def cobuy_edges(trades, c):
    """Wallet pairs that bought the same token in the same cobuy_secs bucket on 2+ different tokens (bundles)."""
    buckets = defaultdict(set)
    for w, m, ts, kind, sol in trades:
        if kind == "buy":
            buckets[(m, ts // max(1, c["cobuy_secs"]))].add(w)
    pair_tokens = defaultdict(set)
    bought = defaultdict(set)
    for w, m, ts, kind, sol in trades:
        if kind == "buy":
            bought[w].add(m)
    for (m, _), ws in buckets.items():
        if 2 <= len(ws) <= 20:
            ws = sorted(ws)
            for i, a in enumerate(ws):
                for b in ws[i + 1:]:
                    pair_tokens[(a, b)].add(m)
    # snipers all hit the launch block of every token, so co-buys only count when they are a big part of what
    # the smaller wallet does at all
    return [(a, b, len(t)) for (a, b), t in pair_tokens.items()
            if len(t) >= 2 and len(t) / max(1, min(len(bought[a]), len(bought[b]))) >= c["cobuy_min_share"]]


def owner_groups(fund_edges, rug_clusters, cobuys, hubs, trades, links, info, flags, c):
    """Wallets joined by: a common (non-exchange) funder, the same rug cluster, or repeated same-second buys."""
    info = info or {}
    fan = Counter(f for f, _ in set(fund_edges))
    bad_funder = {f for f, n in fan.items() if n > c["funder_hub_max"]} | set(hubs) \
        | {w for w, i in info.items() if "cex" in (i.get("labels") or [])}
    edges, why = [], defaultdict(Counter)
    for f, w in set(fund_edges):
        if f in bad_funder or f == w:
            continue
        edges.append((f, w))
        why[f]["izvor novca"] += 1
        why[w]["izvor novca"] += 1
    for cl in rug_clusters:
        for w in cl[1:]:
            edges.append((cl[0], w))
            why[w]["rug klaster"] += 1
        why[cl[0]]["rug klaster"] += 1
    for a, b, n in cobuys:
        edges.append((a, b))
        why[a]["kupnja u istoj sekundi"] += 1
        why[b]["kupnja u istoj sekundi"] += 1
    nodes = {n for e in edges for n in e}
    comps = _components(nodes, edges)
    toks = defaultdict(set)
    last = defaultdict(int)
    for w, m, ts, kind, sol in trades:
        if kind == "buy":
            toks[w].add(m)
            last[w] = max(last[w], ts)
    devs = defaultdict(set)
    for m, f in flags.items():
        if f.get("dev"):
            devs[f["dev"]].add(m)
    link_by_w = defaultdict(set)
    for ln in links:
        link_by_w[ln["wallet"]].add(ln["handle"])
    out = []
    for comp in comps:
        tokens = set().union(*(toks[w] for w in comp))
        created = set().union(*(devs[w] for w in comp))
        if len(tokens | created) < c["min_group_tokens"] and len(comp) < 3:
            continue
        reasons = Counter()
        for w in comp:
            reasons.update(why[w])
        labels = Counter(lab for w in comp for lab in (info.get(w) or {}).get("labels", []))
        pnl = [(info.get(w) or {}).get("realized_sol") for w in comp]
        pnl = [p for p in pnl if p is not None]
        handles = sorted(set().union(*(link_by_w[w] for w in comp)))
        key = hashlib.sha1(",".join(sorted(comp)).encode()).hexdigest()[:8]
        multi = sum(1 for t in tokens if sum(1 for w in comp if t in toks[w]) >= 2)
        score = min(100, round(25 * min(2, len(comp) / 3) + 15 * min(2, multi / 3) + 20 * bool(handles)
                               + 10 * bool(created)))
        out.append({"id": "w" + key, "wallets": sorted(comp)[:50], "size": len(comp), "tokens": len(tokens),
                    "shared_tokens": multi, "created": len(created), "reasons": dict(reasons.most_common()),
                    "labels": dict(labels.most_common(5)), "realized_sol": round(sum(pnl), 2) if pnl else None,
                    "handles": handles[:10], "score": score,
                    "last_ts": max((last[w] for w in comp), default=0) or None,
                    "token_list": sorted(tokens, key=lambda t: -sum(1 for w in comp if t in toks[w]))[:10]})
    out.sort(key=lambda g: (-g["score"], -g["size"]))
    return out


# ---------------------------------------------------------------- 4. pump factors

def pump_factors(calls, clusters, links, groups, flags, c):
    """For each KOL-called token with a measured outcome: did it double (max24 >= pump_x) with / without a signal."""
    by_tok = defaultdict(list)
    for x in calls:
        if x["src"] == "x":
            by_tok[x["token"]].append(x)
    mem = {}
    for cl in clusters:
        for m in cl["members"]:
            mem.setdefault(m, cl["id"])
    linked = {(ln["handle"], t) for ln in links for t in ln["token_list"]}
    grp_tokens = {t for g in groups for t in g["token_list"]}
    views = sorted(x["views"] for x in calls if x.get("views"))
    vmed = views[len(views) // 2] if views else None
    rows = []
    for tok, xs in by_tok.items():
        xs.sort(key=lambda x: x["ts"])
        f = xs[0]
        if f["max24"] is None:
            continue
        early = [x for x in xs if x["ts"] - f["ts"] <= 3600]
        ids = Counter(mem[x["handle"]] for x in early if x["handle"] in mem)
        h = time.gmtime(f["ts"]).tm_hour
        rows.append({
            "hit": f["max24"] >= c["pump_x"],
            "3+ računa u prvih sat vremena": len({x["handle"] for x in early}) >= 3,
            "2+ člana iste KOL grupe": any(n >= 2 for n in ids.values()),
            "povezani wallet kupio prije poziva": any((x["handle"], tok) in linked for x in xs),
            "insider grupa walleta u tokenu": tok in grp_tokens,
            "prvi poziv s više pregleda od medijana": None if vmed is None or f.get("views") is None else f["views"] >= vmed,
            "prvi poziv nakon pumpe (kasno)": None if f["pre2h"] is None else f["pre2h"] >= c["late_pre2h"],
            "prvi poziv u SAD sesiji (14-24 UTC)": h >= 14,
            "prvi poziv u Azija sesiji (00-08 UTC)": h < 8,
            "bundle pri kreaciji > 20%": None if (flags.get(tok) or {}).get("bundle_pct") is None
            else flags[tok]["bundle_pct"] > 20,
        })
    out = []
    base = _share([r["hit"] for r in rows])
    for k in (rows[0].keys() if rows else []):
        if k == "hit":
            continue
        yes = [r["hit"] for r in rows if r[k] is True]
        no = [r["hit"] for r in rows if r[k] is False]
        if len(yes) < 3 or len(no) < 3:
            continue
        hy, hn = _share(yes), _share(no)
        out.append({"factor": k, "n_yes": len(yes), "hit_yes": round(hy, 3), "n_no": len(no), "hit_no": round(hn, 3),
                    "lift": None if not hn else round(hy / hn, 2)})
    out.sort(key=lambda r: -(r["lift"] or 0))
    return {"n": len(rows), "base_hit": None if base is None else round(base, 3), "factors": out}


# ---------------------------------------------------------------- 5. active now

def active_now(calls, clusters, groups, trades, c, now=None):
    now = now or time.time()
    since = now - c["active_hours"] * 3600
    syms = {x["token"]: x.get("symbol") for x in calls if x.get("symbol")}
    out = {}
    for cl in clusters:
        ms = set(cl["members"])
        hits = defaultdict(list)
        for x in calls:
            if x["ts"] >= since and x["handle"] in ms:
                hits[x["token"]].append(x)
        for tok, xs in hits.items():
            if len({x["handle"] for x in xs}) >= 2:
                xs.sort(key=lambda x: x["ts"])
                a = out.setdefault(tok, {"token": tok, "symbol": syms.get(tok), "first_ts": xs[0]["ts"], "who": []})
                a["who"].append({"kind": "kol", "id": cl["id"], "n": len({x["handle"] for x in xs}),
                                 "names": sorted({x["handle"] for x in xs})[:5], "score": cl["score"]})
    member = {w: g for g in groups for w in g["wallets"]}
    gh = defaultdict(lambda: defaultdict(list))
    for w, m, ts, kind, sol in trades:
        if kind == "buy" and ts >= since and w in member:
            gh[m][member[w]["id"]].append((ts, w))
    gscore = {g["id"]: g["score"] for g in groups}
    for tok, by in gh.items():
        for gid, xs in by.items():
            a = out.setdefault(tok, {"token": tok, "symbol": syms.get(tok), "first_ts": min(t for t, _ in xs), "who": []})
            a["first_ts"] = min(a["first_ts"], min(t for t, _ in xs))
            a["who"].append({"kind": "wallets", "id": gid, "n": len({w for _, w in xs}), "names": [], "score": gscore[gid]})
    rows = sorted(out.values(), key=lambda a: (-sum(w["score"] for w in a["who"]), -a["first_ts"]))
    return rows


# ---------------------------------------------------------------- all together

def build(kol_db, wallet_db, rug_db, hype_db, c=None, now=None):
    """The whole snapshot as one JSON-able dict."""
    c = c or cfg()
    t0 = time.time()
    calls = load_calls(kol_db) + load_tg(hype_db)
    trades = load_trades(wallet_db, kol_db, c.get("trade_days", 30), now)
    info, fedges = load_wallet_info(wallet_db)
    redges, rclusters, hubs, flags = load_rug(rug_db)
    n_calls, pairs = pair_stats(calls, c)
    clusters = [describe_cluster(m, calls, pairs, c) for m in clusters_from_pairs(pairs, c)]
    clusters = [cl for cl in clusters if cl["tokens"] >= c["min_together"]]
    clusters.sort(key=lambda cl: (-cl["score"], -cl["tokens"]))
    links = wallet_links(calls, trades, c, info)
    groups = owner_groups(fedges + redges, rclusters, cobuy_edges(trades, c), hubs, trades, links, info, flags, c)
    # a cluster's wallets: linked wallets of its members
    for cl in clusters:
        ms = set(cl["members"])
        ws = sorted({ln["wallet"] for ln in links if ln["handle"] in ms})
        cl["wallets"] = ws[:20]
        gids = {g["id"] for g in groups if set(g["wallets"]) & set(ws)}
        cl["groups"] = sorted(gids)
    for g in groups:
        g["clusters"] = [cl["id"] for cl in clusters if set(cl["members"]) & set(g["handles"])]
    factors = pump_factors(calls, clusters, links, groups, flags, c)
    top_pairs = sorted(({"a": a, "b": b, "n": p["n"], "overlap": round(p["overlap"], 2), "lift": round(p["lift"], 1),
                         "a_first": round(p["a_first"] / p["n"], 2), "gap_min": round(_med(p["gaps"]), 1)}
                        for (a, b), p in pairs.items() if p["n"] >= c["min_together"]),
                       key=lambda p: (-p["overlap"] * p["n"]))
    mr = c["max_rows"]
    return {
        "built": int(now or time.time()), "secs": round(time.time() - t0, 1),
        "inputs": {"calls": len(calls), "accounts": len(n_calls), "tg_posts": sum(1 for x in calls if x["src"] == "tg"),
                   "trades": len(trades), "wallets": len(info), "fund_edges": len(fedges) + len(redges),
                   "rug_clusters": len(rclusters), "measured_tokens": factors["n"]},
        "clusters": clusters[:mr], "pairs": top_pairs[:mr], "links": links[:mr * 2], "groups": groups[:mr],
        "factors": factors, "active": active_now(calls, clusters, groups, trades, c, now)[:mr],
    }


def digest(snap):
    """Hash of what the AI would read (without timings), so unchanged data is not interpreted twice."""
    d = {k: v for k, v in snap.items() if k not in ("built", "secs", "active")}
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]


def follow_list(snap, ai=None, c=None):
    """Groups to follow: organisation score >= follow_min_score, or the AI said so."""
    c = c or cfg()
    want = {g.get("id") for g in ((ai or {}).get("grupe") or []) if g.get("pratiti")}
    out = []
    for cl in snap["clusters"]:
        if cl["score"] >= c["follow_min_score"] or cl["id"] in want:
            out.append({"id": cl["id"], "kind": "kol", "name": "Grupa " + (cl["leader"] or cl["members"][0]),
                        "members": cl["members"], "score": cl["score"],
                        "reason": f"{cl['tokens']} zajedničkih tokena, razmak {cl['spread_min']} min"})
    for g in snap["groups"]:
        if g["score"] >= c["follow_min_score"] or g["id"] in want:
            out.append({"id": g["id"], "kind": "wallets", "name": f"Walleti {g['wallets'][0][:4]}… ({g['size']})",
                        "members": g["wallets"], "score": g["score"],
                        "reason": ", ".join(f"{k} {v}" for k, v in list(g["reasons"].items())[:3])})
    return out
