"""KOL-ovi koji zovu zajedno: when several accounts (X and Telegram) call the same token within minutes, who keeps
doing it together (clusters), and how such joint calls end compared with one account calling alone.

Read-only on kol.db (groups from kol/score.build_groups, chance-tested pairs from kol/validate.pair_tests, measured
calls). The outcome of a token is the price path after its FIRST call (calls.max24, r24h), so a late echo cannot
make a group look better. Pure helpers take plain rows so tests can feed synthetic data.
"""
import json
import statistics
from collections import Counter, defaultdict

HIT = 1.0       # +100% (2x) within 24 h after the first call
RUG = -0.9      # -90% at 24 h, or flagged rug
LATE = 1.0      # price had already doubled in the 2 h before the first call
MIN_N = 8       # fewer outcomes than this: shown faded, no verdict


def platform(h):
    return "tg" if (h or "").startswith("tg:") else ("chain" if (h or "").startswith("w:") else "x")


def _stats(rows):
    """rows: [(max24, r24h, rug, pre2h)] -> {n, hit, med, rug, late} (None without rows)."""
    if not rows:
        return {"n": 0, "hit": None, "med": None, "rug": None, "late": None}
    n = len(rows)
    return {"n": n,
            "hit": sum(1 for m, *_ in rows if (m or 0) >= HIT) / n,
            "med": statistics.median(m or 0 for m, *_ in rows),
            "rug": sum(1 for _, r, rg, _p in rows if rg or (r is not None and r <= RUG)) / n,
            "late": sum(1 for *_, p in rows if (p or 0) >= LATE) / n}


def size_bucket(n):
    return "1" if n <= 1 else ("2" if n == 2 else ("3" if n == 3 else "4+"))


def mix_of(handles):
    p = {platform(h) for h in handles} - {"chain"}
    if p == {"x", "tg"}:
        return "X + Telegram"
    return "samo Telegram" if p == {"tg"} else "samo X"


def _first_calls(con):
    """token -> (ts, handle, max24, r24h, rug, pre2h) of its first measured real call."""
    rows = con.execute("""SELECT token, ts, handle, max24, r24h, COALESCE(rug, 0), pre2h FROM calls
                          WHERE kind = 'call' AND max24 IS NOT NULL AND bad IS NULL ORDER BY token, ts""").fetchall()
    out = {}
    for t, ts, h, m, r, rg, p in rows:
        out.setdefault(t, (ts, h, m, r, rg, p))
    return out


def _groups(con):
    try:
        return [(t, s, e, json.loads(hs), fh) for t, s, e, hs, fh in
                con.execute("SELECT token, start_ts, end_ts, handles, first_handle FROM groups")]
    except Exception:  # noqa: BLE001
        return []


def components(pairs):
    """Union-find over proven pairs [(a, b)] -> list of member sets, biggest first."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comp = defaultdict(set)
    for x in list(parent):
        comp[find(x)].add(x)
    return sorted(comp.values(), key=len, reverse=True)


def build(con, shill=frozenset(), now=None):
    """Everything the 'Zovu zajedno' section shows. shill: lowercased handles of paid shillers."""
    first = _first_calls(con)
    groups = _groups(con)
    # group size and members at the first call of each token
    at_first = {}
    for t, s, e, hs, fh in groups:
        f = first.get(t)
        if f and s <= f[0] <= e:
            at_first[t] = hs
    by_size, by_mix, by_shill = defaultdict(list), defaultdict(list), defaultdict(list)
    for t, (ts, h, m, r, rg, p) in first.items():
        hs = at_first.get(t, [h])
        row = (m, r, rg, p)
        by_size[size_bucket(len(hs))].append(row)
        if len(hs) >= 2:
            by_mix[mix_of(hs)].append(row)
            has = any(x.lower() in shill for x in hs)
            by_shill["s plaćenim shillerom" if has else "bez plaćenih shillera"].append(row)
    sizes = {k: _stats(by_size.get(k, [])) for k in ("1", "2", "3", "4+")}
    mixes = {k: _stats(by_mix.get(k, [])) for k in ("samo X", "samo Telegram", "X + Telegram")}
    shills = {k: _stats(v) for k, v in by_shill.items()}

    # clusters from chance-tested pairs (kol/validate.pair_tests ok = 1)
    try:
        proven = con.execute("SELECT a, b, together, lift, p FROM pair_tests WHERE ok = 1").fetchall()
    except Exception:  # noqa: BLE001
        proven = []
    pair_info = {(a, b): (n, lift, p) for a, b, n, lift, p in proven}
    clusters = []
    for members in components([(a, b) for a, b, *_ in proven]):
        joint = [(t, s, hs, fh) for t, s, e, hs, fh in groups if len(members & set(hs)) >= 2]
        rows, leaders, lags = [], Counter(), []
        for t, s, hs, fh in joint:
            f = first.get(t)
            if f and abs(f[0] - s) <= 3600:
                rows.append(f[2:])
            inside = [x for x in hs if x in members]
            leaders[inside[0]] += 1
        st = _stats(rows)
        clusters.append({
            "members": sorted(members, key=lambda x: -leaders.get(x, 0)), "tokens": len({t for t, *_ in joint}),
            "stats": st, "leader": leaders.most_common(1)[0][0] if leaders else None,
            "lead_share": (leaders.most_common(1)[0][1] / sum(leaders.values())) if leaders else None,
            "platforms": sorted({platform(x) for x in members}),
            "shill": sorted(x for x in members if x.lower() in shill),
            "best_lift": max((pair_info[(a, b)][1] or 0) for a, b in pair_info if a in members and b in members)})
    clusters.sort(key=lambda c: (-c["tokens"], -(c["stats"]["hit"] or 0)))
    return {"sizes": sizes, "mixes": mixes, "shills": shills, "clusters": clusters, "n_groups": len(groups),
            "n_tokens": len(first)}


def _p(x):
    return "–" if x is None else f"{x:.0%}"


def verdict(d):
    """Plain-language lines for the top of the section (Croatian)."""
    s = d["sizes"]
    solo, many = s["1"], _merge(s["3"], s["4+"])
    lines = []
    if solo["n"] >= MIN_N and many["n"] >= MIN_N:
        ratio = (many["hit"] / solo["hit"]) if solo["hit"] else None
        if ratio and ratio >= 1.2:
            lines.append(f"Kad 3 ili više računa zove isti token unutar 30 min, token se udvostruči u {_p(many['hit'])} "
                         f"slučajeva, a kad zove samo jedan u {_p(solo['hit'])}. Zajednički poziv je jači signal.")
        elif ratio and ratio <= 0.8:
            lines.append(f"Zajednički pozivi 3+ računa udvostruče se rjeđe ({_p(many['hit'])}) nego kad zove jedan "
                         f"({_p(solo['hit'])}): često je to plaćena kampanja koja se brzo prodaje.")
        else:
            lines.append(f"Zajednički pozivi 3+ računa ({_p(many['hit'])} udvostručenih) prolaze otprilike kao "
                         f"samostalni ({_p(solo['hit'])}). Sama gužva nije signal, gleda se tko zove.")
        if many["rug"] is not None and solo["rug"] is not None and many["rug"] > solo["rug"] + 0.05:
            lines.append(f"Pazi: rugova je više kod gužve ({_p(many['rug'])}) nego kod samostalnih ({_p(solo['rug'])}).")
    else:
        lines.append("Još premalo izmjerenih zajedničkih poziva za zaključak; broji se sam svaki krug.")
    mx = d["mixes"]
    if mx["X + Telegram"]["n"] >= MIN_N and mx["samo X"]["n"] >= MIN_N:
        lines.append(f"X i Telegram zajedno: {_p(mx['X + Telegram']['hit'])} udvostručenih, samo X: "
                     f"{_p(mx['samo X']['hit'])}.")
    sh = d["shills"]
    a, b = sh.get("s plaćenim shillerom"), sh.get("bez plaćenih shillera")
    if a and b and a["n"] >= MIN_N:
        lines.append(f"Grupe u kojima je plaćeni shill s tvoje liste: {_p(a['hit'])} udvostručenih, rugova "
                     f"{_p(a['rug'])} (bez njih {_p(b['hit'])} i {_p(b['rug'])}).")
    good = [c for c in d["clusters"] if c["stats"]["n"] >= 3 and (c["stats"]["hit"] or 0) >= 0.5]
    if d["clusters"]:
        lines.append(f"Dokazanih ekipa koje zovu zajedno: {len(d['clusters'])}"
                     + (f", od toga {len(good)} s više od pola udvostručenih poziva." if good else "."))
    return lines


def _merge(a, b):
    n = a["n"] + b["n"]
    if not n:
        return {"n": 0, "hit": None, "med": None, "rug": None, "late": None}

    def w(k):
        xs = [(s[k], s["n"]) for s in (a, b) if s[k] is not None]
        return sum(v * k_ for v, k_ in xs) / sum(k_ for _, k_ in xs) if xs else None
    return {"n": n, "hit": w("hit"), "med": w("med"), "rug": w("rug"), "late": w("late")}
