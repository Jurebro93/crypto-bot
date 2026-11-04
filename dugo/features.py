"""Features of one token from its daily candles, computed only from data up to the last candle given.

The same function serves the live list and the backtest in dugo/learn.py (cut the candles at day t, measure what
happened after t), so what the bot learns from history is exactly what it ranks with today.
candles: [(day, open, high, low, close, volume)] oldest first, day = UTC midnight in unix seconds.
ref: {day: close} of a reference (SOL or BTC).
"""
import math
import statistics as st

D = 86400


def _rets(closes):
    return [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]


def _corr(x, y):
    if len(x) < 20:
        return None
    try:
        return st.correlation(x, y)
    except (st.StatisticsError, ZeroDivisionError):
        return None


def paired_returns(candles, ref, n=90):
    """Daily log returns of the token and the reference on the same days, last n days."""
    cl = {c[0]: c[4] for c in candles[-(n + 1):]}
    days = sorted(d for d in cl if d in ref and d - D in cl and d - D in ref)
    a, b = [], []
    for d in days:
        if cl[d - D] > 0 and cl[d] > 0 and ref[d - D] > 0 and ref[d] > 0:
            a.append(math.log(cl[d] / cl[d - D]))
            b.append(math.log(ref[d] / ref[d - D]))
    return a, b


def episodes(closes, fall=0.4, back=0.5):
    """Dips of at least `fall` from a running peak, and how many of them won back at least `back` of the loss
    before the next dip started. Returns (dips, recovered)."""
    dips = rec = 0
    peak = closes[0] if closes else 0
    trough = None
    for c in closes:
        if trough is None:
            if c > peak:
                peak = c
            elif peak and c <= peak * (1 - fall):
                dips, trough = dips + 1, c
        else:
            trough = min(trough, c)
            if c >= trough + back * (peak - trough):
                rec += 1
                peak, trough = c, None
    return dips, rec


def compute(candles, sol=None, btc=None):
    """{feature: value or None}. Needs at least 14 candles."""
    if len(candles) < 14:
        return None
    closes = [c[4] for c in candles if c[4]]
    vols = [c[5] or 0 for c in candles]
    if len(closes) < 14:
        return None
    last = closes[-1]
    ath = max(c[2] or c[4] for c in candles)
    low30 = min((c[3] or c[4]) for c in candles[-30:])
    f = {"starost_d": (candles[-1][0] - candles[0][0]) / D + 1,
         "pad_od_vrha": last / ath - 1 if ath else None,
         "od_dna_30d": last / low30 - 1 if low30 else None}
    for n in (7, 30, 90):
        f[f"povrat_{n}d"] = last / closes[-n - 1] - 1 if len(closes) > n and closes[-n - 1] else None
    v7 = sum(vols[-7:]) / 7
    v21 = sum(vols[-28:-7]) / max(1, len(vols[-28:-7]))
    f["volumen_trend"] = v7 / v21 if v21 else None
    # constant trading: daily volume of the last 14 days without big gaps (1 = same every day, 0 = spikes and dead days)
    v14 = vols[-14:]
    m14 = sum(v14) / len(v14)
    f["volumen_dan"] = m14
    f["stalnost_volumena"] = max(0.0, min(1.0, 1 - st.pstdev(v14) / m14)) if m14 > 0 else 0.0
    ma30 = sum(closes[-30:]) / len(closes[-30:])
    ma90 = sum(closes[-90:]) / len(closes[-90:])
    f["iznad_ma30"] = last / ma30 - 1
    f["ma30_iznad_ma90"] = ma30 / ma90 - 1 if len(closes) >= 60 else None
    r = _rets(closes[-91:])
    f["volatilnost"] = st.pstdev(r) if len(r) > 5 else None
    dips, rec = episodes(closes)
    f["padova"], f["oporavaka"] = dips, rec
    f["udio_oporavaka"] = rec / dips if dips else None
    for name, ref in (("sol", sol), ("btc", btc)):
        f[f"korelacija_{name}"] = f[f"beta_{name}"] = f[f"rast_s_{name}"] = None
        if not ref:
            continue
        a, b = paired_returns(candles, ref)
        c = _corr(a, b)
        f[f"korelacija_{name}"] = c
        if c is not None:
            vb = st.variance(b)   # sample variance, like st.covariance (DS01: was pvariance -> beta 30/29)
            f[f"beta_{name}"] = st.covariance(a, b) / vb if vb else None
            up = [x for x, y in zip(a, b) if y > 0.01]
            down = [x for x, y in zip(a, b) if y < -0.01]
            if len(up) >= 5 and len(down) >= 5:
                # gains on the reference's good days minus losses on its bad days: >0 = rides rallies harder than dips
                f[f"rast_s_{name}"] = st.mean(up) + st.mean(down)
    return f


def forward(candles_all, day, n=30):
    """Close-to-close return from `day` to `day + n` days (None when that day is not in the data)."""
    cl = {c[0]: c[4] for c in candles_all}
    a, b = cl.get(day), cl.get(day + n * D)
    return b / a - 1 if a and b else None
