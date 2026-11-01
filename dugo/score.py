"""Scores 0-100 for the two lists, plus "sličnost uzoru" (how close a token's behaviour is to Fartcoin/Useless).

Each feature is turned into its percentile among today's eligible tokens (0 = worst, 1 = best), a missing value
counts as the middle (0.5), and the score is the weighted mean, scaled to 0-100. Negative weights reward low values.
Percentiles keep the score stable when the market as a whole moves: the list says "best of what is out there now".
"""
import math

KINDS = ("dugorocni", "budjenje", "jaki")   # the lists; "jaki" added 1.11. (older, bigger, steady volume, growing holders)

# plain Croatian names for the dashboard and the "zašto" text
NAMES = {
    "starost_d": "star token (preživio mjesecima)", "likvidnost": "duboka likvidnost", "oporavaka": "više oporavaka od padova",
    "udio_oporavaka": "oporavlja se od većine padova", "korelacija_btc": "kreće se s BTC-om",
    "rast_s_btc": "raste jače od BTC-a kad BTC raste", "rast_s_sol": "raste jače od SOL-a kad SOL raste",
    "ma30_iznad_ma90": "srednji trend gore", "iznad_ma30": "cijena iznad prosjeka 30 dana", "pad_od_vrha": "blizu vrha",
    "kol_tjedana_60d": "KOL-ovi ga zovu tjednima", "kol_autora": "zvalo ga je puno KOL-ova", "tg_30d": "spominje se na Telegramu",
    "volumen_mcap": "živo trgovanje za svoju veličinu", "kupci_udio": "više kupaca nego prodavača",
    "slicnost_uzoru": "ponaša se kao Fartcoin/Useless", "volatilnost": "mirnija cijena",
    "od_dna_30d": "odbio se od dna", "volumen_trend": "volumen se vraća", "povrat_7d": "raste zadnji tjedan",
    "kol_7d": "novi KOL pozivi ovaj tjedan", "tg_7d": "novi Telegram spomeni", "pregrijan": "već previše narastao",
    "holderi_30d": "broj holdera stalno raste", "sirenje_vlasnistva": "vlasništvo se širi izvan najvećih walleta",
    "veliki_kupuju": "kupuju ga veliki holderi drugih dugoročnih tokena", "burze_velike": "izlistan na velikim burzama",
    "nova_burza": "nova burza u zadnjem tjednu", "rast_udjela_burzi": "burze primaju sve veći dio supplyja",
    "stalnost_volumena": "stalan volumen svaki dan", "povrat_30d": "raste zadnji mjesec",
}
# features that describe "behaviour like the reference tokens"
PROFILE = ["pad_od_vrha", "udio_oporavaka", "oporavaka", "korelacija_btc", "beta_btc", "rast_s_btc", "volatilnost",
           "likvidnost", "volumen_mcap"]


def derive(f, liq, mcap, vol24, buys, sells, soc, holders_growth=None):
    """Adds market and social features to the candle features (in place) and returns them."""
    f["likvidnost"] = math.log10(liq) if liq and liq > 0 else None
    f["volumen_mcap"] = vol24 / mcap if mcap and vol24 is not None else None
    f["kupci_udio"] = buys / (buys + sells) if (buys or 0) + (sells or 0) >= 20 else None
    p7 = f.get("povrat_7d")
    f["pregrijan"] = max(0.0, p7 - 1.0) if p7 is not None else None
    f["holderi_30d"] = holders_growth
    f.update(soc or {})
    return f


def _pct(values):
    """{key: percentile 0..1} of non-None values (ties share the mean rank)."""
    xs = sorted((v, k) for k, v in values.items() if v is not None and not (isinstance(v, float) and math.isnan(v)))
    n = len(xs)
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1][0] == xs[i][0]:
            j += 1
        p = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
        for k in range(i, j + 1):
            out[xs[k][1]] = p
        i = j + 1
    return out


def similarity(feats, ref_mints):
    """{mint: 0..1} closeness to the average reference profile (1 = behaves most like the references)."""
    cols = {c: {m: f.get(c) for m, f in feats.items()} for c in PROFILE}
    z = {}
    for c, vals in cols.items():
        xs = [v for v in vals.values() if v is not None]
        if len(xs) < 3:
            continue
        mu = sum(xs) / len(xs)
        sd = (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5 or 1
        z[c] = {m: (v - mu) / sd for m, v in vals.items() if v is not None}
    refs = [m for m in ref_mints if m in feats]
    if not refs or not z:
        return {}
    centre = {c: sum(z[c][m] for m in refs if m in z[c]) / max(1, sum(m in z[c] for m in refs)) for c in z}
    dist = {}
    for m in feats:
        d = [(z[c][m] - centre[c]) ** 2 for c in z if m in z[c]]
        if len(d) >= len(z) // 2:
            dist[m] = (sum(d) / len(d)) ** 0.5
    p = _pct(dist)
    return {m: 1 - v for m, v in p.items()}


def score(feats, weights):
    """{mint: (score 0-100, {feature: contribution})} for already-eligible tokens."""
    pct = {c: _pct({m: f.get(c) for m, f in feats.items()}) for c in weights}
    tot = sum(abs(w) for w in weights.values()) or 1
    out = {}
    for m in feats:
        s, parts = 0.0, {}
        for c, w in weights.items():
            p = pct[c].get(m, 0.5)
            v = (p if w >= 0 else 1 - p) * abs(w)
            s += v
            parts[c] = (p - 0.5) * w
        out[m] = (round(100 * s / tot, 1), parts)
    return out


def why(parts, f, n=3):
    """Short plain-language reason: strongest pros and the main con."""
    pros = [c for c, v in sorted(parts.items(), key=lambda x: -x[1]) if v > 0.05][:n]
    cons = [c for c, v in sorted(parts.items(), key=lambda x: x[1]) if v < -0.1][:1]
    txt = ", ".join(NAMES.get(c, c) for c in pros) or "prosječan na svim mjerilima"
    if cons:
        txt += "; slabije: " + NAMES.get(cons[0], cons[0]).replace("star token (preživio mjesecima)", "mlad token")
    return txt


def eligible(kind, f, liq, mcap, cfg):
    g = cfg[kind]
    if (f.get("starost_d") or 0) < g["min_starost_d"] or (liq or 0) < g["min_likvidnost"]:
        return False
    if kind == "dugorocni":
        return (mcap or 0) >= g["min_mcap"]
    if kind == "jaki":
        return (mcap or 0) >= g["min_mcap"] and strong_shape(f, g)
    return (f.get("pad_od_vrha") is not None and f["pad_od_vrha"] <= g["max_pad_od_vrha"]
            and (f.get("od_dna_30d") or 0) >= g["min_od_dna_30d"])


def strong_shape(f, g):
    """"Jaki": steady daily volume, not collapsed, holders not shrinking (unknown holder growth does not block)."""
    hg = f.get("holderi_30d")
    return ((f.get("volumen_dan") or 0) >= g["min_volumen_dan"]
            and (f.get("stalnost_volumena") or 0) >= g["min_stalnost_volumena"]
            and (f.get("pad_od_vrha") is None or f["pad_od_vrha"] >= g["min_pad_od_vrha"])
            and (hg is None or hg >= g["min_holderi_30d"]))
