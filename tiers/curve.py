"""Bonding-curve forensics for a pump.fun token, computed once per token from its on-chain history.

The retrospective study (retro/, 25k tokens) found that what happened on the bonding curve before graduation
separates the tokens that later did 5x from the rest: time spent on the curve, who holds how much, whether
pump.fun's own "mayhem" account traded it, how spiky the path was. This module fetches that history through
Helius (getTransactionsForAddress, ~10 credits per 100 txs, capped by CURVE_MAX_PAGES) and turns it into
0..1 features for the hype score plus flags for token_tier. Nothing here is a hard cut: the learning loop
(learn/) moves the weights; the initial ones in hype/weights.json follow the signs and sizes of the study's model.
"""
import json
import os
import statistics
import time
import urllib.request

from retro import chain, collect
from retro import features as F

MAX_PAGES = int(os.environ.get("CURVE_MAX_PAGES", "15"))  # 15 pages = 1500 curve txs = at most 150 credits
PER_DAY = int(os.environ.get("CURVE_PER_DAY", "300"))  # new tokens per day, so a busy day stays under 45k credits
META_TIMEOUT = 15


def fetch(mint, max_pages=None, meta=True):
    """History of one pump.fun mint from its create tx to graduation (or to now / the page cap).

    Returns None when the mint's first transaction is not a pump.fun create (not a pump.fun token), else
    {"raw": study features, "flags": {...}, "t_create", "t_grad", "complete", "credits", "meta"}.
    """
    before = chain.credits_used()
    info, rows = collect.fetch_token(mint, None, max_pages or MAX_PAGES)
    credits = chain.credits_used() - before
    if not info.get("t_create") or not rows:
        return None
    cols = ("mint", "n", "ts", "slot", "wallet", "side", "tokens", "sol", "price", "curve_sol")
    trs = [dict(zip(cols, r)) for r in rows]
    tok = {"t_create": info["t_create"], "slot_create": info.get("slot_create"), "creator": info.get("creator")}
    t_grad = info.get("t_grad")
    cut = t_grad or trs[-1]["ts"]
    md = _meta(info.get("uri")) if meta else None
    raw = F.at(trs, tok, cut, None, md)
    raw.update(F.path_shape([(r["ts"], r["price"]) for r in trs], cut, tok["t_create"]))
    raw["top3_buy_share"] = F.buy_concentration(trs, cut)
    priced = [r["price"] for r in trs if r["price"]]
    quote_sol = bool(priced) and statistics.median(priced) * chain.SUPPLY >= 2  # a SOL curve starts near 28 SOL mcap
    grad_min = (t_grad - tok["t_create"]) / 60 if t_grad else None
    flags = {"bundle_launch": 1 if (t_grad and t_grad - tok["t_create"] < 60) else 0,
             "mayhem": int(raw.get("mayhem") or 0), "quote_sol": int(quote_sol), "grad_min": grad_min}
    return {"raw": _clean(raw), "flags": flags, "t_create": tok["t_create"], "t_grad": t_grad,
            "complete": int(bool(info.get("complete"))), "credits": credits, "meta": md}


def _meta(uri):
    """Name/description/socials from the token's metadata JSON (pump.fun's IPFS gateway); None on any failure."""
    if not uri or not uri.startswith("http"):
        return None
    if "/ipfs/" in uri:
        uri = "https://pump.mypinata.cloud/ipfs/" + uri.split("/ipfs/", 1)[1]
    try:
        req = urllib.request.Request(uri, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=META_TIMEOUT) as r:
            d = json.loads(r.read(200000))
        return {k: d.get(k) for k in ("twitter", "telegram", "website", "description")}
    except Exception:
        return None


def _clean(d):
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items() if v is not None}


def _clip(x):
    return max(0.0, min(1.0, x))


def hype_features(raw):
    """0..1 features for the hype score, each pointing the way the study found favourable (higher = more 5x).

    Study signs at graduation (logistic coefficients): mayhem -0.80, protocol volume -0.53, dev holds +0.48,
    max drawdown +0.45, description length +0.42, dev sold share +0.41, Telegram -0.40, website +0.38,
    curve age +0.37, spike share -0.36, big-buy share -0.34, top1 +0.32; quintiles: top10 > 35% 9.0% vs
    < 18% 1.8%, holders < 69 7.8% vs > 402 1.2%, last-5-min buy share < 0.18 8.8% vs > 0.54 3.7%,
    bundle 5-21% best, > 48% worst, median buy > 0.16 SOL best.
    """
    if not raw or "age_min" not in raw:
        return {}
    g = raw.get
    f = {
        "krivulja_starost": _clip((g("age_min") or 0) / 360),                 # 6 h on the curve = 1
        "krivulja_bez_mayhema": 1.0 - float(g("mayhem") or 0),
        "krivulja_organski_volumen": 1.0 - _clip(g("proto_vol_frac") or 0),
        "krivulja_dev_drzi": _clip((g("dev_hold_pct") or 0) / 5),             # 5% of supply = 1
        "krivulja_dev_prodao": _clip(g("dev_sold_frac") or 0),
        "krivulja_postupnost": 1.0 - _clip(g("spike_share") or 0),
        "krivulja_male_kupnje": 1.0 - _clip(g("big_buy_frac") or 0),
        "krivulja_top1": _clip((g("top1_pct") or 0) / 10),
        "krivulja_top10": _clip((g("top10_pct") or 0) / 50),
        "krivulja_mirna_zadnjih5": 1.0 - _clip(g("last5_buy_share") or 0),
        "krivulja_malo_holdera": 1.0 - _clip((g("holders") or 0) / 400),
        "krivulja_bundle_umjeren": 1.0 - _clip(((g("bundle_pct") or 0) - 20) / 30),  # <= 20% = 1, 50% = 0
        "krivulja_medijan_kupnje": _clip((g("median_buy_sol") or 0) / 0.2),
    }
    if g("max_dd_pct") is not None:
        f["krivulja_pad_od_vrha"] = _clip(g("max_dd_pct") / 100)
    if g("desc_len") is not None:  # metadata was reachable
        f["krivulja_opis"] = _clip(g("desc_len") / 50)
        f["krivulja_web"] = float(g("has_website") or 0)
        f["krivulja_bez_telegrama"] = 1.0 - float(g("has_telegram") or 0)
    return {k: round(v, 3) for k, v in f.items()}


def budget_left(con, now=None):
    """How many more tokens may be fetched today (CURVE_PER_DAY minus those fetched in the last 24 h)."""
    since = int((now or time.time()) - 86400)
    n = con.execute("SELECT COUNT(*) FROM token_tier WHERE krivulja_ts >= ?", (since,)).fetchone()[0]
    return max(0, PER_DAY - n)


def needs_fetch(row, now=None, refresh_h=6):
    """A pump.fun token with no curve snapshot yet, or one taken before graduation (incomplete) more than
    refresh_h ago, so a token that graduated since gets its full curve once."""
    if not row or not row.get("krivulja_ts"):
        return True
    if row.get("krivulja_complete"):
        return False
    return (now or time.time()) - row["krivulja_ts"] > refresh_h * 3600


def describe(flags, raw):
    """One Croatian line for the dashboard / log."""
    if not raw:
        return ""
    bits = [f"{(raw.get('age_min') or 0) / 60:.1f} h na krivulji", f"{raw.get('holders', 0)} holdera",
            f"top10 {raw.get('top10_pct', 0):.0f}%", f"bundle {raw.get('bundle_pct', 0):.0f}%"]
    if flags.get("mayhem"):
        bits.append("pump.fun mayhem")
    if flags.get("bundle_launch"):
        bits.append("graduirao u prvoj minuti (bundle)")
    if not flags.get("quote_sol", 1):
        bits.append("krivulja nije u SOL-u")
    return ", ".join(bits)
