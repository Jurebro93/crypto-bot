"""Per-token categories of the midcap list (15.11., owner: "drže konstantan volumen mjesecima, i u bear marketu ...
rastu kad BTC raste"; pure: the daily / 1h candles and BTC closes in, numbers out).

    age        days since the oldest pool; owner's bucket 15-30 d / 1-3 mj / 3-6 mj / 6+ mj, the critic's 16-30 / 31-90 / >90
    volume     pers30 / pers90: share of the last 30 / 90 days (of the days the token existed) with a day's volume >=
               VOL_DAY_FLOOR ($50k); cv30: the coefficient of variation of the daily volume, last 30 days
    BTC        beta_d / corr_d on daily returns (last 90 days), beta_4h / corr_4h on 4 h returns (the 1h candles we
               hold, ~40 days); btc_up_24h / btc_up_72h: the token's mean return 24 h / 72 h after a BTC day of +3 %
    drawdown   dd_ath: the last close against the highest high of the daily history
    bounces    from the daily history, entries NOT on a BTC crash day: every day closing in the bottom 20 % of its
               trailing 30-day range -> the next 7 days' best high (up7) and worst low (dn7); hit15: share with up7 >=
               +15 %; med_up7 / med_dn7
Category (cat): "A" old (> 90 d) + constant volume (pers90 >= 0.8) + follows BTC (corr_d >= 0.3); "B" > 30 d and pers30
>= 0.6; "C" the rest. score ranks inside a category: 2 x pers90 + corr_d + 2 x hit15 + 0.5 x max(dd_ath, -1).
"""
import math

D, H = 86400, 3600
VOL_DAY_FLOOR = 50_000.0
CAT_TEXT = {"A": "A: stari + stalni volumen + prati BTC", "B": "B: srednji ili stalan volumen",
            "C": "C: mlad ili nestalan volumen"}


def age_bucket(age_d):
    if age_d is None:
        return "?"
    return "15-30 d" if age_d <= 30 else "1-3 mj" if age_d <= 90 else "3-6 mj" if age_d <= 180 else "6+ mj"


def age_bucket_critic(age_d):
    if age_d is None:
        return "?"
    return "16-30 d" if age_d <= 30 else "31-90 d" if age_d <= 90 else ">90 d"


def _rets(closes):
    """{ts: return} of consecutive closes [(ts, c)]."""
    out = {}
    for (t0, a), (t1, b) in zip(closes, closes[1:]):
        if a and b and a > 0:
            out[t1] = b / a - 1
    return out


def beta_corr(xs, ys):
    """(beta of y on x, correlation) or (None, None) with fewer than 8 pairs."""
    n = len(xs)
    if n < 8:
        return None, None
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    cv = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if vx <= 0 or vy <= 0:
        return None, None
    return round(cv / vx, 3), round(cv / math.sqrt(vx * vy), 3)


def agg(candles, step):
    """Candles [(ts, o, h, l, c, v)] -> closes per `step` seconds [(bucket ts, last close)]."""
    out = {}
    for c in candles:
        out[int(c[0]) // step * step] = c[4]
    return sorted(out.items())


def compute(daily, hourly, btc_d, btc_h, created_ts=None, now=None, crash=None):
    """The metrics dict of one token (see the module text). daily / hourly: [(ts, o, h, l, c, v)] oldest first."""
    now = now or (daily[-1][0] + D if daily else 0)
    out = {}
    age = (now - created_ts) / D if created_ts else ((now - daily[0][0]) / D if daily else None)
    out["age_d"] = round(age, 1) if age is not None else None
    out["age_bucket"] = age_bucket(age)
    out["age_bucket_k"] = age_bucket_critic(age)
    vols = [(c[0], c[5] or 0.0) for c in daily]
    for w in (30, 90):
        last = [v for t, v in vols if t >= now - w * D]
        out[f"pers{w}"] = round(sum(1 for v in last if v >= VOL_DAY_FLOOR) / len(last), 3) if last else None
    v30 = [v for t, v in vols if t >= now - 30 * D]
    if len(v30) >= 5 and sum(v30) > 0:
        m = sum(v30) / len(v30)
        out["cv30"] = round(math.sqrt(sum((v - m) ** 2 for v in v30) / len(v30)) / m, 3)
        out["vol_day_avg30"] = round(m)
    else:
        out["cv30"], out["vol_day_avg30"] = None, None
    # BTC beta / correlation
    tr = _rets([(c[0] // D * D, c[4]) for c in daily if c[0] >= now - 91 * D])
    br = _rets([(t // D * D, p) for t, p in btc_d])
    ks = sorted(set(tr) & set(br))
    out["beta_d"], out["corr_d"] = beta_corr([br[k] for k in ks], [tr[k] for k in ks])
    t4 = _rets(agg(hourly, 4 * H))
    b4 = _rets(agg([(t, p, p, p, p, 0) for t, p in btc_h], 4 * H))
    k4 = sorted(set(t4) & set(b4))
    out["beta_4h"], out["corr_4h"] = beta_corr([b4[k] for k in k4], [t4[k] for k in k4])
    # after BTC +3 % days
    bd = sorted((t // D * D, p) for t, p in btc_d)
    closes = {c[0] // D * D: c[4] for c in daily}
    up24, up72 = [], []
    for (t0, a), (t1, b) in zip(bd, bd[1:]):
        if a and b / a - 1 >= 0.03 and t1 in closes:
            c0 = closes[t1]
            if t1 + D in closes and c0:
                up24.append(closes[t1 + D] / c0 - 1)
            if t1 + 3 * D in closes and c0:
                up72.append(closes[t1 + 3 * D] / c0 - 1)
    out["btc_up_n"] = len(up24)
    out["btc_up_24h"] = round(sum(up24) / len(up24) * 100, 2) if up24 else None
    out["btc_up_72h"] = round(sum(up72) / len(up72) * 100, 2) if up72 else None
    # drawdown from the all-time high of the daily history
    if daily:
        hi = max(c[2] for c in daily)
        out["dd_ath"] = round(daily[-1][4] / hi - 1, 3) if hi > 0 else None
        out["ath_ts"] = max(daily, key=lambda c: c[2])[0]
        out["days_history"] = len(daily)
    else:
        out["dd_ath"], out["days_history"] = None, 0
    # bounces from the bottom of the trailing 30-day range (daily), not on a BTC crash day
    ups, dns = [], []
    for i in range(30, len(daily) - 1):
        t = daily[i][0]
        if crash is not None and crash.overlaps(t, t + D - 1):
            continue
        w = daily[i - 30:i]
        lo, hi = min(c[3] for c in w), max(c[2] for c in w)
        c = daily[i][4]
        if hi <= lo or not (lo <= c <= lo + 0.2 * (hi - lo)):
            continue
        nxt = daily[i + 1:i + 8]
        if len(nxt) < 3:
            continue
        ups.append(max(x[2] for x in nxt) / c - 1)
        dns.append(min(x[3] for x in nxt) / c - 1)
    out["bounce_n"] = len(ups)
    out["hit15"] = round(sum(1 for u in ups if u >= 0.15) / len(ups), 3) if ups else None
    out["med_up7"] = round(sorted(ups)[len(ups) // 2] * 100, 1) if ups else None
    out["med_dn7"] = round(sorted(dns)[len(dns) // 2] * 100, 1) if dns else None
    out["cat"] = category(out)
    out["score"] = score(out)
    return out


def category(m):
    age, p90, p30, corr = m.get("age_d") or 0, m.get("pers90"), m.get("pers30"), m.get("corr_d")
    if age > 90 and (p90 or 0) >= 0.8 and (corr or 0) >= 0.3:
        return "A"
    if age > 30 and (p30 or 0) >= 0.6:
        return "B"
    return "C"


def score(m):
    return round(2 * (m.get("pers90") or 0) + (m.get("corr_d") or 0) + 2 * (m.get("hit15") or 0)
                 + 0.5 * max(m.get("dd_ath") if m.get("dd_ath") is not None else -1, -1), 3)
