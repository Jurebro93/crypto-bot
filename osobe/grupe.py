"""Group call power (27.11., vlasnik: "grupe influencera, koliko ih zove isti token zajedno i koliko to mijenja cijenu,
moć poziva, težina").

An EVENT is a token's first post by a tracked account plus every other tracked account's first post about the same
token within WINDOW_S of it (kol.db calls, kind call / brag, measured price path, no 'bad' flag). Its size is the
number of distinct accounts. The outcome is the price path after the event's FIRST post (calls.r1h / r6h / r24h, so
a late echo cannot make a group look better), MINUS the token's own usual move over the same horizon (from kol.db
snaps outside the call windows when there are enough of them, else the usual move after a single account's call) and
MINUS the realistic round-trip cost, never under RT_FLOOR (3 %: veliki/replay.RT_FLOOR, the measured round trip).

Split: by size 1 / 2-3 / 4+, and per recurring pair of accounts (2+ events together). Plus whether a person of
osobe.db bought before the event and sold within POST_S after it (selling into the calls).

The method stays here; the page shows the results only (the owner wants it hidden). Nothing here trades.
"""
import bisect
import json
import random
import statistics
from collections import defaultdict
from itertools import combinations

from osobe import store

WINDOW_S = 30 * 60
HORIZONS = (("1h", 3600, "r1h"), ("6h", 6 * 3600, "r6h"), ("24h", 86400, "r24h"))
RT_FLOOR = 0.03
SIZE_USD = 15.0           # 0.1 SOL at ~150 $ (the demo / real stake)
PAIR_MIN = 2
BASE_MIN = 4              # snaps samples before the token's own baseline is used
PRE_S, POST_S = 24 * 3600, 2 * 3600
BOOT_N = 1000


def bucket(n):
    return "1" if n <= 1 else ("2-3" if n <= 3 else "4+")


def cost(liq):
    """Round trip as a fraction: fees + twice the price impact of SIZE_USD in a pool of `liq` $, never under RT_FLOOR."""
    impact = 2 * SIZE_USD / liq if liq and liq > 0 else 0.0
    return max(RT_FLOOR, 0.01 + impact)


def events(calls, window_s=WINDOW_S):
    """calls: [(handle, token, ts, r1h, r6h, r24h)] (first post per handle and token). -> [event dict]."""
    by_tok = defaultdict(list)
    for h, tok, ts, *rs in calls:
        by_tok[tok].append((ts, h, rs))
    out = []
    for tok, cs in by_tok.items():
        cs.sort()
        i = 0
        while i < len(cs):
            t0, h0, rs0 = cs[i]
            hs = [h0]
            j = i + 1
            while j < len(cs) and cs[j][0] - t0 <= window_s:
                if cs[j][1] not in hs:
                    hs.append(cs[j][1])
                j += 1
            out.append({"token": tok, "t0": t0, "handles": hs, "n": len(hs),
                        "r": dict(zip([k for k, _s, _c in HORIZONS], rs0))})
            i = j
    return out


def baselines(snaps, call_ts, horizons=HORIZONS):
    """snaps: {token: [(ts, price)] sorted}; call_ts: {token: [ts]}. -> {(token, key): median move} of the token's
    own price over each horizon, from snapshot pairs that do not overlap any call window [t - h, t + 24 h]."""
    out = {}
    for tok, pts in snaps.items():
        if len(pts) < 3:
            continue
        ts = [t for t, _p in pts]
        cts = sorted(call_ts.get(tok, []))
        for key, h, _c in horizons:
            moves = []
            for t, p in pts:
                if not p:
                    continue
                k = bisect.bisect_left(cts, t - 86400)
                if k < len(cts) and cts[k] <= t + h:
                    continue
                j = bisect.bisect_left(ts, t + h)
                if j < len(ts) and abs(ts[j] - (t + h)) <= h * 0.25 and pts[j][1]:
                    moves.append(pts[j][1] / p - 1)
            if len(moves) >= BASE_MIN:
                out[(tok, key)] = statistics.median(moves)
    return out


def excess(evs, base, liq):
    """Adds e["x"][key] = move - baseline - cost for every measured horizon; the fallback baseline is the median move
    after a single account's call (what a call usually does on its own)."""
    solo = {}
    for key, _h, _c in HORIZONS:
        xs = [e["r"].get(key) for e in evs if e["n"] == 1 and e["r"].get(key) is not None]
        solo[key] = statistics.median(xs) if xs else 0.0
    for e in evs:
        c = cost(liq.get(e["token"]))
        e["x"], e["own_base"] = {}, False
        for key, _h, _col in HORIZONS:
            r = e["r"].get(key)
            if r is None:
                continue
            b = base.get((e["token"], key))
            if b is not None:
                e["own_base"] = True
            e["x"][key] = r - (b if b is not None else solo[key]) - c
    return evs


def _boot(xs, seed=27, n=BOOT_N):
    if len(xs) < 5:
        return None
    rnd = random.Random(seed)
    ms = sorted(statistics.fmean(rnd.choices(xs, k=len(xs))) for _ in range(n))
    return round(ms[int(0.05 * n)], 4), round(ms[int(0.95 * n) - 1], 4)


def stats(evs, key="24h"):
    evs = [e for e in evs if key in e.get("x", {})]
    xs = [e["x"][key] for e in evs]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": round(statistics.fmean(xs), 4), "median": round(statistics.median(xs), 4),
            "pos_share": round(sum(1 for x in xs if x > 0) / len(xs), 3), "ci90": _boot(xs),
            "sold_into_share": round(sum(1 for e in evs if e.get("sold_into")) / len(evs), 3)}


def mark_sellers(evs, person_book):
    """person_book: {pid: {mint: (sorted buys, sorted sells)}}; marks e["sold_into"] = [pid] of persons that bought
    in [t0 - PRE_S, t0) and sold in [t0, t0 + POST_S]."""
    by_mint = defaultdict(list)
    for pid, book in person_book.items():
        for m, bs in book.items():
            by_mint[m].append((pid, bs))
    for e in evs:
        t0, who = e["t0"], []
        for pid, (buys, sells) in by_mint.get(e["token"], ()):
            i = bisect.bisect_left(buys, t0 - PRE_S)
            if i < len(buys) and buys[i] < t0:
                j = bisect.bisect_left(sells, t0)
                if j < len(sells) and sells[j] <= t0 + POST_S:
                    who.append(pid)
        e["sold_into"] = who
    return evs


def summarize(evs):
    by_b = defaultdict(list)
    for e in evs:
        by_b[bucket(e["n"])].append(e)
    sizes = {b: {k: stats(by_b.get(b, []), k) for k, _h, _c in HORIZONS} for b in ("1", "2-3", "4+")}
    pairs = defaultdict(list)
    for e in evs:
        if e["n"] >= 2:
            for a, b in combinations(sorted(set(e["handles"]), key=str.lower), 2):
                pairs[(a, b)].append(e)
    rec = []
    for (a, b), es in pairs.items():
        if len(es) >= PAIR_MIN:
            s = stats(es, "24h")
            s1 = stats(es, "1h")
            rec.append({"handles": [a, b], "n": len(es), "x24": s.get("mean"), "x1": s1.get("mean"),
                        "pos_share": s.get("pos_share"), "sold_into_share": s.get("sold_into_share"),
                        "tokens": [e["token"] for e in es[:5]]})
    rec.sort(key=lambda r: (-r["n"], -(r["x24"] or -9)))
    sellers = defaultdict(int)
    for e in evs:
        for pid in e.get("sold_into") or ():
            sellers[pid] += 1
    return {"events": len(evs), "own_base": sum(1 for e in evs if e.get("own_base")), "sizes": sizes,
            "pairs": rec[:40], "sellers": sorted(([p, n] for p, n in sellers.items()), key=lambda x: -x[1])[:30]}


def load(p, handles=None):
    """(first posts, snaps by token, call ts by token, liquidity by token) from kol.db."""
    kc = store.ro(p.get("kol_db"))
    first = {}
    q = ("SELECT handle, token, ts, r1h, r6h, r24h, {} rug FROM calls WHERE kind IN ('call', 'brag') ORDER BY ts")
    raw = store.q(kc, q.format("bad,")) or store.q(kc, q.format("NULL,"))   # an older kol.db without calls.bad
    for h, tok, ts, r1, r6, r24, bad, rug in raw:
        if (h, tok) not in first:
            first[(h, tok)] = (h, tok, ts, r1, r6, r24, bad, rug)
    rows = [r[:6] for r in first.values() if not r[6]]   # untrusted path out; a rug stays in (a real loss)
    if handles is not None:
        rows = [r for r in rows if r[0] and r[0].lower() in handles]
    toks = {r[1] for r in rows}
    snaps = defaultdict(list)
    for tok, ts, price in store.q(kc, "SELECT token, ts, price FROM snaps ORDER BY token, ts"):
        if tok in toks:
            snaps[tok].append((ts, price))
    liq = {t: l for t, l in store.q(kc, "SELECT token, liquidity FROM tokens WHERE liquidity IS NOT NULL")}
    if kc is not None:
        kc.close()
    cts = defaultdict(list)
    for _h, tok, ts, *_r in rows:
        cts[tok].append(ts)
    return rows, snaps, cts, liq


def run(p, handles, person_book):
    rows, snaps, cts, liq = load(p, handles)
    evs = events(rows)
    excess(evs, baselines(snaps, cts), liq)
    mark_sellers(evs, person_book)
    return summarize(evs)


def save(con, res, now):
    store.kv(con, "grupe", {**res, "ts": int(now)})


def latest(con):
    return store.kv(con, "grupe")


def dumps(res):
    return json.dumps(res, ensure_ascii=False)
