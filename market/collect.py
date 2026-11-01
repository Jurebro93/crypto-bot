"""Pull the DefiLlama numbers into market.db: daily history per platform, group totals, SOL price, hourly snapshot."""
import time

from market import sources

D = 86400
KEEP_DAYS = 400
EXTRA_MIN_WEEK = 500_000   # $ in 7 days
PARTIAL_SHARE = 0.6


def today(now=None):
    return int((now or time.time()) // D * D)


def save_platforms(con, protos):
    con.executemany("INSERT INTO platforms VALUES (?,?,?,?) ON CONFLICT(slug) DO UPDATE SET name=excluded.name,"
                    " category=excluded.category, grp=excluded.grp",
                    [(s, n, c, g) for s, (n, c, g) in protos.items()])


def daily(con, ov, now=None, fetch=sources.protocol_daily, min_week=EXTRA_MIN_WEEK):
    """Daily volume per kept protocol plus 'all:<group>' totals. The current UTC day is still filling up,
    so it is skipped (DefiLlama repeats the rolling 24 h under today's date). Protocols the overview's breakdown
    leaves out (trading apps, some launchpads) are fetched one by one when they did at least min_week in 7 days.
    Returns the number of days written."""
    protos = sources.protocols(ov)
    save_platforms(con, protos)
    by_name = {}
    for p in ov.get("protocols") or []:
        if p.get("slug") in protos:
            for k in (p.get("name"), p.get("displayName")):
                if k:
                    by_name[k] = p["slug"]
    cut, first = today(now), today(now) - KEEP_DAYS * D
    vols, seen = {}, set()
    for day, parts in ov.get("totalDataChartBreakdown") or []:
        day = int(day) // D * D
        for name, vol in (parts or {}).items():
            slug = by_name.get(name)
            if slug and isinstance(vol, (int, float)):
                seen.add(slug)
                if first <= day < cut:
                    vols[(day, slug)] = float(vol)
    for p in ov.get("protocols") or []:
        s = p.get("slug")
        if s in protos and s not in seen and (p.get("total7d") or 0) >= min_week:
            try:
                pts = fetch(s)
            except Exception as e:
                print(f"market: {s} povijest nije uspjela: {e}")
                continue
            for day, vol in pts:
                day = day // D * D
                if first <= day < cut:
                    vols[(day, s)] = vol
    tot = {}
    for (day, slug), vol in vols.items():
        k = (day, f"all:{protos[slug][2]}")
        tot[k] = tot.get(k, 0.0) + vol
    last = partial_day(tot)
    if last:   # DefiLlama has not finished that day yet: keep it out until a later fetch has it complete
        vols = {k: v for k, v in vols.items() if k[0] != last}
        tot = {k: v for k, v in tot.items() if k[0] != last}
        con.execute("DELETE FROM daily WHERE day>=?", (last,))
        con.execute("DELETE FROM regime WHERE day>=?", (last,))
        print(f"market: {last} još nepotpun na DefiLlami, preskačem", flush=True)
    con.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?)",
                    [(d, s, v) for (d, s), v in list(vols.items()) + list(tot.items())])
    con.execute("DELETE FROM daily WHERE day<?", (first,))
    return len({d for d, _ in vols})


def partial_day(tot, share=PARTIAL_SHARE):
    """The newest day when its whole Solana DEX volume is below `share` of the median of the 7 days before it
    (DefiLlama sometimes lists a day before all protocols have reported it, e.g. 31.10.2026 showed $0.83B vs ~$1.9B)."""
    dex = {d: v for (d, k), v in tot.items() if k == "all:dex"}
    if len(dex) < 8:
        return None
    last = max(dex)
    prev = sorted(dex.get(last - i * D) for i in range(1, 8) if dex.get(last - i * D))
    if len(prev) < 5:
        return None
    med = prev[len(prev) // 2]
    return last if dex[last] < share * med else None


def prices(con, pts):
    con.executemany("INSERT OR REPLACE INTO price VALUES (?,?)", [(t // D * D, p) for t, p in pts])


def snapshot(con, ov, now=None):
    """Rolling 24 h and 7 d volume per platform and group right now (one row set per hour)."""
    ts = int((now or time.time()) // 3600 * 3600)
    protos = sources.protocols(ov)
    save_platforms(con, protos)
    rows, tot = [], {}
    for p in ov.get("protocols") or []:
        s = p.get("slug")
        if s not in protos or p.get("total24h") is None:
            continue
        v24, v7 = float(p["total24h"] or 0), float(p.get("total7d") or 0)
        rows.append((ts, s, v24, v7))
        g = protos[s][2]
        a = tot.setdefault(g, [0.0, 0.0])
        a[0] += v24
        a[1] += v7
    rows += [(ts, f"all:{g}", a, b) for g, (a, b) in tot.items()]
    con.executemany("INSERT OR REPLACE INTO snap VALUES (?,?,?,?)", rows)
    con.execute("DELETE FROM snap WHERE ts<?", (ts - 60 * D,))
    return len(rows)
