"""Correlation between "the event is getting closer" and a token's volume, buying and smart-money entries."""


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(xs, ys):
    """Rank correlation -1..1 (robust to memecoin outliers); None when there is too little or flat data."""
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pts) < 4:
        return None
    rx, ry = _rank([p[0] for p in pts]), _rank([p[1] for p in pts])
    n = len(pts)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    if not vx or not vy:
        return None
    return round(cov / (vx * vy), 2)


MIN_SNAPSHOTS = 6


def verdict(c):
    """Plain-Croatian reading of one token's correlations."""
    if c["n"] < MIN_SNAPSHOTS:
        return "premalo podataka"
    vol, smart, buyers = c["corr_volume"] or 0, c["corr_smart"] or 0, c["corr_buyers"] or 0
    if c["bad_total"] and c["bad_total"] >= max(3, c["smart_total"]):
        return "ulaze loši walleti"
    if vol >= 0.5 and (smart >= 0.3 or c["smart_total"] >= 2):
        return "volumen i smart money rastu prema eventu"
    if vol >= 0.5 or buyers >= 0.5:
        return "volumen raste prema eventu"
    if vol <= -0.5:
        return "volumen pada (hype je možda već prošao)"
    return "bez jasne veze s eventom"


def correlate(snaps):
    """snaps: one token's snapshots oldest first. closeness = -days_to_event, so positive = rises toward the event."""
    close = [-(s["days_to_event"]) for s in snaps]
    vols = [s["vol_h1"] for s in snaps]
    buys = [s["buys_h1"] for s in snaps]
    wallet_snaps = [s for s in snaps if s["new_buyers"] is not None]
    wclose = [-(s["days_to_event"]) for s in wallet_snaps]
    first_vol = next((v for v in vols if v), 0)
    last_vol = vols[-1] if vols else 0
    c = {
        "n": len(snaps),
        "first_ts": snaps[0]["ts"] if snaps else None,
        "last_ts": snaps[-1]["ts"] if snaps else None,
        "corr_volume": spearman(close, vols),
        "corr_buys": spearman(close, buys),
        "corr_buyers": spearman(wclose, [s["new_buyers"] for s in wallet_snaps]),
        "corr_smart": spearman(wclose, [s["smart_buyers"] for s in wallet_snaps]),
        "corr_price": spearman(close, [s["price"] for s in snaps]),
        "vol_change": round((last_vol - first_vol) / first_vol * 100, 1) if first_vol else None,
        "buyers_total": sum(s["new_buyers"] or 0 for s in wallet_snaps),
        "smart_total": sum(s["smart_buyers"] or 0 for s in wallet_snaps),
        "bad_total": sum(s["bad_buyers"] or 0 for s in wallet_snaps),
    }
    c["verdict"] = verdict(c)
    return c
