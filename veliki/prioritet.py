"""Priority of the midcaps and "zašto je pao" (15.11. navečer, vlasnik: "Preskoči Good Guy. Kreni od TRENDING i najvećeg
VOLUMENA, onda usporedi BUZZ na društvenim mrežama, tradaj te prve, posebno one koji su sada malo PALI; istraži ZAŠTO
su pali, uđi u tradeove i uči iz toga").

refresh() runs in every midcap collector pass (veliki/midcap.py) on midcap.db and writes kv "prio"; veliki/live reads it
(cached) to try its candidates in this order and stores each trade's components and dip reason (veliki_trades.prio,
.dip), so the critic / backtest can measure later which component predicted the profit.

Components (each in the row, the score is their sum):
  trend   DexScreener boosts / profiles / CTO and GeckoTerminal trending rank: 30 x (1 - rank / 100), 0 without a rank
  vol     24 h volume: 8 x log10(vol24 / $100k), 0-30; accel: the last hour's volume x 24 against the day's, 0-10
  buzz    X momentum (scan/xmom.latest: Grok's fresh row first, else the scanner's): 8 x score (-10..15) + organic
          authors in 15 min (0-10); Grok's latest opinion (veliki.db grok_sig, midcap_review / midcap_dip_reason):
          kupi +10 x confidence, preskoči -10 x confidence
  dip     the price is down over 24 h (snap c24) or 7 d (daily candles) while liquidity (>= 80 % of a day ago) and
          volume (>= 60 % of a day ago) hold: + the size of the dip (0-20) when the reason is market-wide or benign
  listing 15.11. (holderi/, vlasnik: "kad dio ponude ode na novčanik burze ... jak signal"): a PRE-LISTING signal (supply
          reaching an exchange that does not list the token yet) of score >= 40: + 0.5 x score, at most 40. It orders the
          DEMO entries; the real account's order leaves it out until holderi/config.json listing_real (default off;
          the critic: 0 SOL on the transfer alone until it is measured)
  oprez   15.11. (holderi/, vlasnik: "do insiders hold a large share of supply — if yes, be careful"): insiders without
          exchanges and LP over 30 %: - the excess (at most 30); team / insiders moving supply out to sell -20; whales
          depositing to an exchange that lists it -15. From 50 % insiders or with the team selling: "block" (veliki/live
          does not enter; the reason is in the row and in "zašto je pao")
Dip reason (classify):
  los         LP pulled (liquidity -30 % in 24 h), RugCheck danger flags, mint / freeze authority, top-10 > 50 %, dev
              >= 5 %, sells > 1.6 x buys over 24 h while the price falls (holders dumping), Grok's dip verdict preskoči
              -> skip (veliki/live does not enter)
  trzisni     BTC -3 % or worse over 24 h, or the median midcap -5 % or worse: the whole market -> fine to buy
  benigni     profit-taking after a pump (+20 % or more over 7 d before the 24 h dip) with the volume holding
  nejasno     none of these: allowed, without the dip bonus
"""
import json
import math
import statistics
import time

PREFIX = "veliki prioritet: "
CACHE_S = 60
KEEP = 300
_C = {"ts": 0.0, "v": None}


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def static_risk(d):
    """15.11. popodne: the facts of classify() that do not depend on the dip (holder concentration, dev share,
    mint / freeze authority, RugCheck danger, the holders' block): "; "-joined text or None. veliki/live refuses an
    entry on them (demo and real): two real trades (ukHH6c, 61V8vB) were closed 40-70 min after the buy as "razlog pada
    postao loš (top 10 holdera 55-60 %)", a fact known before the buy, paying a round trip for nothing."""
    s = d.get("safety") or {}
    bad = []
    if s.get("danger"):
        bad.append("RugCheck: " + ", ".join(s["danger"][:2]))
    if s.get("mint_auth") or s.get("freeze_auth"):
        bad.append("mint / freeze ovlast")
    if (s.get("top10") or 0) > 50:
        bad.append(f"top 10 holdera {s['top10']:.0f} %")
    if (s.get("dev_pct") or 0) >= 5:
        bad.append(f"dev drži {s['dev_pct']:.0f} %")
    h = d.get("holders") or {}
    if h.get("block"):
        bad.append("holderi: " + h["block"])
    return "; ".join(bad) or None


def dynamic_bad(row):
    """15.11. navečer: the NEW danger of an open position from its priority row: liquidity pulled (>= 30 % in 24 h),
    holders selling (sells 1.6x buys while falling), the holders' block (insiders / the team selling). The static facts
    (concentration, dev share, authorities: static_risk) are not here: they are checked before the buy. Text or None."""
    f = (row or {}).get("facts") or {}
    bad = []
    if f.get("liq_ratio") is not None and f["liq_ratio"] < 0.7:
        bad.append(f"likvidnost {(f['liq_ratio'] - 1):+.0%} u 24 h (LP povučen?)")
    if (f.get("sells_buys") or 0) > 1.6 and (f.get("c24") or 0) < 0:
        bad.append(f"prodaje {f['sells_buys']:.1f}x kupnje u 24 h (holderi prodaju)")
    if (row or {}).get("block"):
        bad.append(row["block"])
    return "; ".join(bad) or None


def classify(d):
    """(kind, why) for one dipped token's facts d: c24, c7d, liq_ratio, vol_ratio, sells_buys, safety, btc24,
    market_med, grok_dip."""
    s = d.get("safety") or {}
    bad = []
    if (d.get("liq_ratio") or 1) < 0.7:
        bad.append(f"likvidnost {(d['liq_ratio'] - 1):+.0%} u 24 h (LP povučen?)")
    if s.get("danger"):
        bad.append("RugCheck: " + ", ".join(s["danger"][:2]))
    if s.get("mint_auth") or s.get("freeze_auth"):
        bad.append("mint / freeze ovlast")
    if (s.get("top10") or 0) > 50:
        bad.append(f"top 10 holdera {s['top10']:.0f} %")
    if (s.get("dev_pct") or 0) >= 5:
        bad.append(f"dev drži {s['dev_pct']:.0f} %")
    if (d.get("sells_buys") or 0) > 1.6 and (d.get("c24") or 0) < 0:
        bad.append(f"prodaje {d['sells_buys']:.1f}x kupnje u 24 h (holderi prodaju)")
    g = d.get("grok_dip") or {}
    if g.get("verdict") == "preskoči" and (g.get("confidence") or 0) >= 0.5:
        bad.append("Grok: razlog pada loš")
    h = d.get("holders") or {}
    if h.get("block"):   # 15.11. holderi/: insiders hold too much or the team is selling
        bad.append("holderi: " + h["block"])
    if bad:
        return "los", "; ".join(bad)
    if (d.get("btc24") is not None and d["btc24"] <= -3) or (d.get("market_med") is not None and d["market_med"] <= -5):
        parts = []
        if d.get("btc24") is not None:
            parts.append(f"BTC {d['btc24']:+.1f} %")
        if d.get("market_med") is not None:
            parts.append(f"medijan midcapova {d['market_med']:+.1f} %")
        return "trzisni", "cijelo tržište pada (" + ", ".join(parts) + ")"
    if (d.get("c7d") or 0) >= 20 and (d.get("vol_ratio") or 0) >= 0.6:
        return "benigni", f"uzimanje profita nakon rasta {d['c7d']:+.0f} % u 7 d, volumen drži"
    return "nejasno", "bez jasnog razloga u podacima"


def score(d):
    """(score, parts) of one token's facts (see the module text)."""
    p = {}
    r = d.get("trend")
    p["trend"] = round(30 * (1 - min(float(r), 100) / 100), 1) if r else 0.0
    v = d.get("vol24") or 0
    p["vol"] = round(max(0.0, min(30.0, 8 * math.log10(v / 1e5))) if v > 1e5 else 0.0, 1)
    v1 = d.get("v1h") or 0
    p["accel"] = round(max(0.0, min(10.0, 5 * (v1 * 24 / v - 1))) if v else 0.0, 1)
    x = d.get("x") or {}
    buzz = 0.0
    if x.get("x_momentum_score") is not None:
        buzz += max(-10.0, min(15.0, 8 * float(x["x_momentum_score"])))
    buzz += min(10.0, float(x.get("authors15") or 0))
    g = d.get("grok") or {}
    if g.get("verdict") in ("kupi", "preskoči"):
        buzz += (10 if g["verdict"] == "kupi" else -10) * float(g.get("confidence") or 0.5)
    p["buzz"] = round(buzz, 1)
    dip = d.get("dip") or {}
    holds = d.get("vol_ratio") is None or d["vol_ratio"] >= 0.6   # "dipped while liquidity and volume hold"
    p["dip"] = round(min(20.0, -min(d.get("c24") or 0, d.get("c7d") or 0)), 1) \
        if dip.get("kind") in ("trzisni", "benigni") and holds else 0.0
    if dip.get("kind") == "los":
        p["dip"] = -50.0
    h = d.get("holders") or {}
    if h.get("listing"):
        p["listing"] = round(float(h["listing"]), 1)
    if h.get("oprez"):
        p["oprez"] = round(float(h["oprez"]), 1)
    return round(sum(p.values()), 1), p


def _holders():
    """{mint: holderi facts} (holderi/view.prio_facts: listing bonus, caution, block), {} without holderi."""
    try:
        from holderi import view as hview
        return hview.prio_facts() or {}
    except Exception:  # noqa: BLE001 - no holder data: no listing / caution component
        return {}


def _btc24(now):
    try:
        from veliki import store
        h = store.btc_hourly()
        if len(h) < 25:
            return None
        last = h[-1]
        old = min(h, key=lambda x: abs(x[0] - (last[0] - 86400)))
        return (last[1] / old[1] - 1) * 100 if old[1] else None
    except Exception:  # noqa: BLE001
        return None


def _grok(mints, now):
    """{mint: {"verdict", "confidence", "dip": bool}} Grok's newest opinions (archived into veliki.db grok_sig)."""
    try:
        from veliki import store
        vcon = store.connect()
        try:
            store.archive_grok(vcon, list(mints), now, since_s=12 * 3600)
            out = {}
            q = ",".join("?" * len(mints))
            for tok, ts, v, c, data in vcon.execute(
                    f"SELECT token, ts, verdict, confidence, data FROM grok_sig WHERE token IN ({q}) AND ts >= ? "
                    "ORDER BY ts", (*mints, int(now - 12 * 3600))):
                dip = "zašto" in (data or "").lower() or "dip_reason" in (data or "")
                out[tok] = {"verdict": v, "confidence": c, "ts": ts, "dip": dip}
            return out
        finally:
            vcon.close()
    except Exception:  # noqa: BLE001 - no Grok: no buzz from him
        return {}


def refresh(con, now=None):
    """Compute the priority of every member of midcap.db (con), store kv "prio" and return it."""
    from veliki import midcap
    now = int(now or time.time())
    toks = con.execute("SELECT mint, id, symbol, vol24, trend, liq FROM tokens WHERE member=1").fetchall()
    if not toks:
        return None
    ids = {r[1]: r for r in toks}
    last = {}
    for tid, ts, liq, v1, v24, b24, s24, c24 in con.execute(
            "SELECT s.id, s.ts, s.liq, s.v1h, s.v24, s.b24, s.s24, s.c24 FROM snap s JOIN (SELECT id, MAX(ts) mts FROM "
            "snap WHERE ts >= ? GROUP BY id) m ON m.id = s.id AND m.mts = s.ts", (now - 3 * 3600,)):
        last[tid] = (ts, liq, v1, v24, b24, s24, c24)
    old = {}
    for tid, liq, v24 in con.execute(
            "SELECT s.id, s.liq, s.v24 FROM snap s JOIN (SELECT id, MIN(ts) mts FROM snap WHERE ts BETWEEN ? AND ? "
            "GROUP BY id) m ON m.id = s.id AND m.mts = s.ts", (now - 27 * 3600, now - 21 * 3600)):
        old[tid] = (liq, v24)
    c7 = {}
    for tok, c_now, c_old in con.execute(
            "SELECT token, (SELECT c FROM c1d x WHERE x.token=d.token ORDER BY ts DESC LIMIT 1), "
            "(SELECT c FROM c1d y WHERE y.token=d.token AND y.ts <= ? ORDER BY ts DESC LIMIT 1) FROM "
            "(SELECT DISTINCT token FROM c1d) d", (now - 7 * 86400,)):
        if c_now and c_old:
            c7[tok] = (c_now / c_old - 1) * 100
    mints = [r[0] for r in toks]
    sa = midcap.safety_latest(con, set(mints))
    try:
        from scan import xmom
        xs = xmom.latest(mints, since=now - 6 * 3600, now=now)
    except Exception:  # noqa: BLE001
        xs = {}
    c24s = [x[6] for x in last.values() if x[6] is not None]
    med = statistics.median(c24s) if len(c24s) >= 10 else None
    btc = _btc24(now)
    hold = _holders()
    facts = {}
    for mint, tid, sym, vol24, trend, liq in toks:
        ls = last.get(tid)
        if not ls:
            continue
        _ts, liq_n, v1, v24, b24, s24, c24 = ls
        o = old.get(tid)
        d = {"mint": mint, "symbol": sym, "trend": trend, "vol24": v24 or vol24, "v1h": v1, "c24": c24,
             "c7d": round(c7[mint], 1) if mint in c7 else None,
             "liq_ratio": round(liq_n / o[0], 2) if o and o[0] and liq_n else None,
             "vol_ratio": round(v24 / o[1], 2) if o and o[1] and v24 else None,
             "sells_buys": round(s24 / b24, 2) if b24 and s24 else None, "safety": sa.get(mint),
             "btc24": None if btc is None else round(btc, 1), "market_med": None if med is None else round(med, 1),
             "x": xs.get(mint) or {}, "holders": hold.get(mint) or {}}
        facts[mint] = d
    dipped = [m for m, d in facts.items() if min(d.get("c24") or 0, d.get("c7d") or 0) <= -5]
    gk = _grok(sorted(set(dipped) | {m for m, d in facts.items() if d.get("trend")}), now) if facts else {}
    rows = []
    for m, d in facts.items():
        d["grok"] = gk.get(m) or {}
        d["grok_dip"] = d["grok"] if (d["grok"].get("dip") or m in dipped) else {}   # his newest word on a dipped one
        if m in dipped and (d.get("liq_ratio") or 1) >= 0.8 or m in dipped and (d.get("liq_ratio") or 1) < 0.7:
            kind, why = classify(d)
            d["dip"] = {"kind": kind, "why": why, "c24": d.get("c24"), "c7d": d.get("c7d")}
        elif m in dipped:
            d["dip"] = {"kind": "nejasno", "why": "likvidnost pala 20-30 %: oprez", "c24": d.get("c24"),
                        "c7d": d.get("c7d")}
        sc, parts = score(d)
        row = {"mint": m, "symbol": d.get("symbol"), "score": sc, "parts": parts, "dip": d.get("dip"),
               "facts": {k: d.get(k) for k in ("c24", "c7d", "liq_ratio", "vol_ratio", "sells_buys", "trend",
                                               "vol24", "btc24", "market_med")}}
        risk = static_risk(d)
        if risk:
            row["risk"] = risk
        h = d.get("holders") or {}
        if h.get("block"):
            row["block"] = "holderi: " + h["block"]
        if h.get("listing") or h.get("oprez"):
            row["holders"] = {k: h.get(k) for k in ("listing", "listing_score", "listing_ex", "oprez", "why")}
        rows.append(row)
    rows.sort(key=lambda r: -r["score"])
    prio = {"ts": now, "rows": rows[:KEEP]}
    midcap.kv_put(con, "prio", prio)
    con.commit()
    _C.update(ts=0.0)
    return prio


def cached(path=None):
    """{mint: row} of the newest priority (midcap.db kv prio), cached CACHE_S."""
    if _C["v"] is not None and time.monotonic() - _C["ts"] < CACHE_S and path is None:
        return _C["v"]
    v = {}
    try:
        from veliki import midcap
        con = midcap.ro(path)
        if con is not None:
            try:
                p = midcap.kv_get(con, "prio", {}) or {}
                if time.time() - (p.get("ts") or 0) <= 6 * 3600:
                    v = {r["mint"]: r for r in p.get("rows") or []}
            finally:
                con.close()
    except Exception:  # noqa: BLE001 - no priority: the list order
        v = {}
    if path is None:
        _C.update(ts=time.monotonic(), v=v)
    return v


def real_score(r):
    """The score the REAL account orders by: without the listing bonus unless holderi/config.json listing_real (15.11.,
    the critic: 0 SOL on the transfer alone until the signal is measured)."""
    lb = (r.get("parts") or {}).get("listing") or 0
    if not lb:
        return r["score"]
    try:
        from holderi import run as hrun
        if hrun.config().get("listing_real"):
            return r["score"]
    except Exception:  # noqa: BLE001
        pass
    return round(r["score"] - lb, 1)


def order(tokens, prio=None, real=False):
    """The tokens in priority order (unknown ones after, in their own order); real=True: the real account's order."""
    p = cached() if prio is None else prio
    idx = {t: i for i, t in enumerate(tokens)}
    key = real_score if real else (lambda r: r["score"])
    return sorted(tokens, key=lambda t: (0, -key(p[t])) if t in p else (1, idx[t]))


def meta(tok, prio=None):
    """(prio JSON, dip JSON) of one token for its trade row (None, None when not known)."""
    r = (cached() if prio is None else prio).get(tok)
    if not r:
        return None, None
    return (json.dumps({"score": r["score"], **r["parts"], "facts": r.get("facts")}, ensure_ascii=False),
            json.dumps(r["dip"], ensure_ascii=False) if r.get("dip") else None)


def line(prio, n=10):
    rows = (prio or {}).get("rows") or []
    return PREFIX + (", ".join(
        f"{r.get('symbol') or r['mint'][:6]} {r['score']:.0f} (trend {r['parts']['trend']:.0f}, vol "
        f"{r['parts']['vol']:.0f}, buzz {r['parts']['buzz']:.0f}"
        + (f", pad {r['dip']['kind']} {min(r['dip'].get('c24') or 0, r['dip'].get('c7d') or 0):+.0f} %" if r.get("dip") else "")
        + (f", LISTING +{r['parts']['listing']:.0f}" if r["parts"].get("listing") else "")
        + (f", oprez {r['parts']['oprez']:.0f}" if r["parts"].get("oprez") else "")
        + (", BLOK" if r.get("block") else "")
        + ")" for r in rows[:n]) or "još nema podataka")


def dipped_top(n=5, prio=None):
    """The top n dipped midcaps by score (for Grok's midcap_dip_reason tasks)."""
    p = cached() if prio is None else prio
    return [r for r in sorted(p.values(), key=lambda r: -r["score"]) if r.get("dip")][:n]
