"""Rug / collapse after the fact: a token that has already been rugged (its pool pulled, or a crash with the dev or
a top holder selling, or the rug filter rating it high risk) must not be offered to anyone any more, whatever the
rug filter said before.

The rug filter (rugfilter/check.py) judges a token *before* entry from its mechanics and wallets. This module
judges what *happened*: we compare the newest market cap and liquidity with the highest the bot has seen for that
token in the last `WINDOW_H` hours (hype scans and the 2-minute pulse).

11.11. (Jure: "rugan" meant only "70 %+ under the peak"; X (CccS…y1eU), labelled rugan, was later at $387k, +155 %
from the call): the owner's rule. 11.11. evening (Jure: "mjeri pad likvidnosti na SOL (quote) strani poola, ne u
USD"), measured on the pool itself. In a constant-product pool (pump.fun migrated to PumpSwap, Raydium AMM / CPMM,
Meteora DYN) the SOL reserve is y = L * sqrt(p), with L = sqrt(x * y) the pool's invariant and p the price in SOL. An
organic -85 % dump with no LP removed leaves L as it was and cuts the SOL side to sqrt(0.15) = 0.387 of its peak
(-61 %): "SOL side -50 %" alone would call a plain dump (X) a rug. Pulling LP lowers L, whatever the price does. So a
token is RUGGED only when
  - its pool invariant L = sol_reserve / sqrt(price_in_sol) fell LIQ_RUG (50 %) or more from its peak (LP removed;
    no price condition: L does not move with the price), OR
  - it crashed (DROP, 70 %+ under the peak) AND the dev or a top holder is selling, or the rug filter rates it high
    risk (rug_evidence: rug.db's newest report VISOK RIZIK / ODBAČEN on anything but thin liquidity, "dev je
    prodao" / "dev je prebacio"; range.db's transfer holders net-selling, rangedca/holders).
  For a pool whose L is not constant (concentrated liquidity: Meteora DLMM / DAMM v2, Raydium CLMM, Orca whirlpool;
  a bonding curve; is_cp) the SOL side itself is the measure, -50 % with the price at least half down, and the
  reason says "ne-CP pool".
A crash without any of that is a "dump nakon pumpe" (kind "dump"): not a block, only a P modifier x 0.7 where the
old label blocked (ui/kandidati, proposals/build, fast/decide through trade/edge.modifiers(dump=...)).
Where L comes from (pool_drops): the SOL side and the price in SOL the hype scan stores in token_pulse (liq_sol,
price_native, pool, dex from DexScreener liquidity.quote / priceNative, hype/pulse.record), compared within the same
pool; otherwise from the USD numbers every snapshot has, L ~ liquidity_usd / sqrt(mcap * SOL/USD) (the supply is
constant, SOL/USD per day from market.db), and with only peak / now numbers (judge without `pool`) from those, as if
the liquidity and the market cap peaked together. Every result also carries the plain SOL-side fall ("sol_drop") and
what the owner's literal rule would have said ("sol_rule"), for the comparison in rugfilter/relabel.
check() returns only the rug, so every caller that blocked on it keeps blocking, under the new rule; assess()
returns the rug or the dump. Nothing stored is rewritten: the check is recomputed on every look. rugfilter/archive
keeps its own cleanup rule (judge_legacy, unchanged); its stored kinds are read through the new rule (archive.kinds,
rugfilter/relabel next to the old label).

If a collapsed token later climbs back above `RECOVER` of its peak it is shown again (the check is recomputed on
every look, nothing is stored).
"""
import bisect
import json
import math
import os
import sqlite3
import time

WINDOW_H = 24
DROP = 0.70          # market cap at least 70% below the peak seen in WINDOW_H -> collapsed (a dump; a rug with evidence)
LIQ_DROP = 0.60      # judge_legacy (rugfilter/archive's cleanup): liquidity at least 60% below its peak ...
LIQ_PRICE_DROP = 0.50  # ... together with market cap at least 50% below its peak (liquidity pulled)
LIQ_RUG = 0.50       # 11.11.: a rug when the pool invariant L (CP) / the SOL side (non-CP) fell this much from its peak
RECOVER = 0.50       # recomputed each time; above half of the peak it is no longer collapsed
MIN_PEAK_MCAP = 5000  # below this nothing meaningful to compare
DUMP = "dump nakon pumpe"
RUG_DB = None        # rug.db (None: ui/data.RUG_DB); the offline tests pass their own
MARKET_DB = None     # market.db (daily SOL/USD for L from USD numbers); None: DATA_DIR/market.db
SOL_MINT = "So11111111111111111111111111111111111111112"
FRESH_S = 900        # the SOL-side series counts as "now" when its newest row is this close to the newest snapshot
EVIDENCE_TTL_S = 60
_EVIDENCE = {}


def _k(x):
    return f"${x / 1000:,.1f}k"


def is_cp(dex):
    """True: a constant-product pool (PumpSwap, Raydium AMM v4 / CPMM, Meteora DYN, FluxBeam); False: concentrated
    liquidity (Meteora DLMM / DAMM v2, Raydium CLMM, Orca whirlpool) or a bonding curve, where L is not constant;
    None: unknown (treated as CP: almost every bonded token we see is on PumpSwap). dex: "dexId" or
    "dexId/label,label" as pair_pool stores it."""
    if not dex:
        return None
    d = str(dex).lower()
    dex_id, _, labels = d.partition("/")
    labs = {x.strip() for x in labels.split(",") if x.strip()}
    if dex_id == "orca" or "dlmm" in dex_id or "clmm" in dex_id or labs & NON_CP_LABELS:
        return False
    if dex_id in CURVES:
        return False
    if dex_id in CP_DEXES or labs & {"cpmm", "amm", "dyn", "amm v4"}:
        return True
    return None


NON_CP_LABELS = {"clmm", "dlmm", "wp", "whirlpool", "dyn2", "damm v2", "dammv2", "dbc", "concentrated"}
CURVES = {"pumpfun", "launchlab", "moonshot", "boop", "believe"}
CP_DEXES = {"pumpswap", "raydium", "meteora", "fluxbeam", "pumpfun-amm"}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def pair_pool(p, sol_usd=None):
    """{"liq_sol", "price_native", "pool", "dex"} of a DexScreener pair: the SOL side is liquidity.quote when the quote
    token is SOL / WSOL (price_native = priceNative, in SOL), else liquidity.usd / 2 / SOL price (price_usd / SOL price;
    None without sol_usd). dex = dexId plus its labels ("raydium/CLMM")."""
    p = p or {}
    liq = p.get("liquidity") or {}
    q = p.get("quoteToken") or {}
    sol_quote = q.get("address") == SOL_MINT or str(q.get("symbol") or "").upper() in ("SOL", "WSOL")
    if sol_quote:
        ls, px = _f(liq.get("quote")), _f(p.get("priceNative"))
    elif sol_usd and sol_usd > 0:
        usd, pu = _f(liq.get("usd")), _f(p.get("priceUsd"))
        ls = usd / 2 / sol_usd if usd else None
        px = pu / sol_usd if pu else None
    else:
        ls = px = None
    labels = [str(x) for x in (p.get("labels") or []) if x]
    dex = (p.get("dexId") or "") + ("/" + ",".join(labels) if labels else "")
    return {"liq_sol": ls if ls and ls > 0 else None, "price_native": px if px and px > 0 else None,
            "pool": p.get("pairAddress"), "dex": dex or None}


def approx_pool(peak_mcap, now_mcap, peak_liq, now_liq):
    """pool dict from peak / now numbers only (judge called without a series): L ~ liquidity / sqrt(mcap), as if the
    liquidity and the market cap peaked together; the SOL side ~ the USD liquidity (SOL/USD taken as steady)."""
    out = {"l_drop": None, "sol_drop": None, "cp": None, "src": "vrhovi", "empty": False}
    if not peak_liq or now_liq is None:
        return out
    out["sol_drop"] = 1 - now_liq / peak_liq
    if now_liq <= 0:
        out.update(l_drop=1.0, empty=True)
    elif now_mcap and now_mcap > 0 and peak_mcap and peak_mcap > 0:
        out["l_drop"] = 1 - (now_liq / peak_liq) * math.sqrt(peak_mcap / now_mcap)
    return out


def literal_kind(drop, sol_drop, evidence=None):
    """What the owner's literal words of 11.11. evening would say: "rug" = SOL side -50 % or more, or 70 %+ down with
    the dev / a top holder selling or a high rug risk; "dump" = 70 %+ down otherwise; None. Only for comparison."""
    if sol_drop is not None and sol_drop >= LIQ_RUG:
        return "rug"
    if drop is not None and drop >= DROP:
        return "rug" if evidence else "dump"
    return None


def _pct(x):
    return f"{x:.0%}" if x is not None else "?"


def _nonc(pool):
    return f"ne-CP pool {pool.get('dex')}" if pool.get("dex") else "ne-CP pool"


def judge(peak_mcap, now_mcap, peak_liq=None, now_liq=None, evidence=None, pool=None):
    """None, or {"kind": "rug" | "dump", "drop", "liq_drop", "l_drop", "sol_drop", "cp", "dex", "basis", "sol_rule",
    "text"} under the pool rule (module text). pool: pool_drops() of the token's series; without it L comes from the
    peak / now numbers (approx_pool). evidence: the Croatian line of the dev / a top holder selling or the rug filter's
    high risk (rug_evidence), which turns a crash into a rug. Plain Croatian text for the dashboard."""
    if not peak_mcap or peak_mcap < MIN_PEAK_MCAP or now_mcap is None or now_mcap < 0:
        return None
    drop = 1 - now_mcap / peak_mcap
    liq_drop = (1 - (now_liq or 0) / peak_liq) if peak_liq and now_liq is not None else None
    pool = pool or approx_pool(peak_mcap, now_mcap, peak_liq, now_liq)
    l_drop, sol_drop, cp = pool.get("l_drop"), pool.get("sol_drop"), pool.get("cp")
    if cp is False:   # L is not constant in this pool: the SOL side, with the price at least half down
        pulled = sol_drop is not None and sol_drop >= LIQ_RUG and drop >= 1 - RECOVER
    else:             # an empty pool (liquidity 0) is a rug only together with a real fall, as before
        pulled = l_drop is not None and l_drop >= LIQ_RUG and (not pool.get("empty") or drop >= 1 - RECOVER)
    if not pulled and drop < DROP:
        return None
    out = {"drop": round(drop, 3), "liq_drop": None if liq_drop is None else round(liq_drop, 3),
           "l_drop": None if l_drop is None else round(l_drop, 3),
           "sol_drop": None if sol_drop is None else round(sol_drop, 3), "cp": cp, "dex": pool.get("dex"),
           "basis": pool.get("src"), "sol_rule": literal_kind(drop, sol_drop, evidence)}
    fell = f"srušio se {drop:.0%} od vrha ({_k(peak_mcap)} → {_k(now_mcap)})"
    if pulled:
        how = (f"SOL strana poola {_pct(sol_drop)} manja ({_nonc(pool)})" if cp is False
               else f"pool (L) {_pct(l_drop)} manji od vrha, SOL strana {_pct(sol_drop)} manja")
        return {"kind": "rug", **out, "text": f"izvučena likvidnost: {how}; pad {drop:.0%} od vrha "
                                              f"({_k(peak_mcap)} → {_k(now_mcap)})"}
    if evidence:
        return {"kind": "rug", **out, "text": f"{fell}; {evidence}"}
    if cp is False:
        liq = f"SOL strana {_pct(sol_drop)} manja ({_nonc(pool)})"
    elif l_drop is None:
        liq = "likvidnost nepoznata"
    else:
        hold = "pool drži" if l_drop < 0.2 else f"pool {l_drop:.0%} manji"
        why = " (pad cijene, ne izvlačenje)" if l_drop < 0.2 and (sol_drop or 0) >= 0.4 else ""
        liq = f"{hold}, SOL strana {_pct(sol_drop)} manja{why}" if sol_drop is not None else hold
    return {"kind": "dump", **out, "text": f"{DUMP}: pao {drop:.0%} od vrha ({_k(peak_mcap)} → {_k(now_mcap)}), {liq}, "
                                         "bez prodaje deva i visokog rug rizika"}


def judge_usd(peak_mcap, now_mcap, peak_liq=None, now_liq=None, evidence=None):
    """The rule of 11.11. noon (USD liquidity more than 50 % down = rug), kept ONLY so rugfilter/relabel can show what
    the pool rule changed; nothing decides on it any more."""
    if not peak_mcap or peak_mcap < MIN_PEAK_MCAP or now_mcap is None or now_mcap < 0:
        return None
    drop = 1 - now_mcap / peak_mcap
    liq_drop = (1 - (now_liq or 0) / peak_liq) if peak_liq and now_liq is not None else None
    if drop < 1 - RECOVER:
        return None
    pulled = liq_drop is not None and liq_drop > LIQ_RUG
    if not pulled and drop < DROP:
        return None
    out = {"drop": round(drop, 3), "liq_drop": None if liq_drop is None else round(liq_drop, 3)}
    fell = f"srušio se {drop:.0%} od vrha ({_k(peak_mcap)} → {_k(now_mcap)})"
    if pulled:
        text = (f"{fell}, likvidnost {liq_drop:.0%} manja" if drop >= DROP
                else f"izvučena likvidnost ({liq_drop:.0%} manje) i pad {drop:.0%} od vrha")
        return {"kind": "rug", **out, "text": text}
    if evidence:
        return {"kind": "rug", **out, "text": f"{fell}; {evidence}"}
    if liq_drop is None:
        liq = "likvidnost nepoznata"
    elif liq_drop > 0:
        liq = f"likvidnost {liq_drop:.0%} manja"
    else:
        liq = "likvidnost drži"
    return {"kind": "dump", **out, "text": f"{DUMP}: pao {drop:.0%} od vrha ({_k(peak_mcap)} → {_k(now_mcap)}), {liq}, "
                                         "bez prodaje deva i visokog rug rizika"}


def judge_legacy(peak_mcap, now_mcap, peak_liq=None, now_liq=None):
    """The rule before 11.11. (70 %+ under the peak, or 60 %+ less liquidity with a 50 %+ fall), kept ONLY for
    rugfilter/archive's hourly cleanup, so what it deletes from hype.db does not change with the label."""
    if not peak_mcap or peak_mcap < MIN_PEAK_MCAP or now_mcap is None or now_mcap < 0:
        return None
    drop = 1 - now_mcap / peak_mcap
    liq_drop = (1 - (now_liq or 0) / peak_liq) if peak_liq and now_liq is not None else None
    if drop < 1 - RECOVER:
        return None
    if drop >= DROP:
        text = f"srušio se {drop:.0%} od vrha (${peak_mcap / 1000:,.1f}k → ${now_mcap / 1000:,.1f}k)"
    elif liq_drop is not None and liq_drop >= LIQ_DROP and drop >= LIQ_PRICE_DROP:
        text = f"izvučena likvidnost ({liq_drop:.0%} manje) i pad {drop:.0%} od vrha"
    else:
        return None
    if liq_drop is not None and liq_drop >= LIQ_DROP and drop >= DROP:
        text += f", likvidnost {liq_drop:.0%} manja"
    return {"drop": round(drop, 3), "liq_drop": None if liq_drop is None else round(liq_drop, 3), "text": text}


def peaks(db_path, tokens, hours=WINDOW_H, now=None):
    """token -> [peak_mcap, peak_liq, last_mcap, last_liq, last_ts, series] from hype_signals + token_pulse in hype.db
    (series: the pool state pool_drops() reads; token_pulse's SOL side when those columns are there)."""
    tokens = list(tokens)
    if not tokens or not os.path.exists(db_path):
        return {}
    since = int((now or time.time()) - hours * 3600)
    out = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return {}
    try:
        for i in range(0, len(tokens), 400):
            part = tokens[i:i + 400]
            ph = ",".join("?" * len(part))
            for table, extras in (("hype_signals", ("",)), ("token_pulse", (", liq_sol, price_native, pool, dex", ""))):
                for extra in extras:   # an older token_pulse without the SOL columns: the plain read
                    try:
                        rows = con.execute(f"SELECT token, ts, mcap, liquidity{extra} FROM {table} WHERE ts >= ? "
                                           f"AND token IN ({ph})", (since, *part)).fetchall()
                    except sqlite3.OperationalError:
                        continue
                    for row in rows:
                        add(out, *row)
                    break
    finally:
        con.close()
    return out


_SOL_DAYS = {"ts": 0.0, "cfg": object(), "days": {}, "keys": [], "memo": {}}


def _load_sol_days():
    path = MARKET_DB
    if path is None:
        try:
            from ops import disk
            path = os.path.join(disk.DATA_DIR, "market.db")
        except Exception:  # noqa: BLE001
            path = ""
    days = {}
    if path and os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            try:
                days = {int(d): float(u) for d, u in con.execute("SELECT day, usd FROM price WHERE usd > 0")}
            finally:
                con.close()
        except sqlite3.Error:
            days = {}
    _SOL_DAYS.update(ts=time.time(), cfg=MARKET_DB, days=days, keys=sorted(days), memo={})


def sol_usd_at(ts):
    """SOL/USD of ts's UTC day from market.db price (the nearest known day either way); 1.0 without market.db, which
    is fine for L's ratios as long as every point of a token uses the same source. Read once an hour, memo per day
    (peaks() calls it for every row)."""
    if _SOL_DAYS["cfg"] is not MARKET_DB or time.time() - _SOL_DAYS["ts"] > 3600:
        _load_sol_days()
    day = int(ts) // 86400
    v = _SOL_DAYS["memo"].get(day)
    if v is None:
        days = _SOL_DAYS["days"]
        d = day * 86400
        if not days:
            v = 1.0
        elif d in days:
            v = days[d]
        else:
            keys = _SOL_DAYS["keys"]
            i = bisect.bisect_left(keys, d)
            near = [keys[j] for j in (i - 1, i) if 0 <= j < len(keys)]
            v = days[min(near, key=lambda k: abs(k - d))]
        _SOL_DAYS["memo"][day] = v
    return v


def _series():
    return {"u": None, "z": 0, "s": {}}


def _fold(st, ts, mcap, liq, liq_sol=None, price_native=None, pool=None, dex=None):
    """One snapshot into the pool state: u = the USD-based L (liquidity / sqrt(mcap * SOL/USD)) and the SOL side
    (liquidity / 2 / SOL/USD) as [peak_L, last_L, peak_sol, last_sol, last_ts]; z = the newest ts with liquidity 0;
    s = per pool the exact L (SOL side / sqrt(price in SOL)) as [peak_L, last_L, peak_sol, last_sol, last_ts, dex]."""
    if mcap and mcap > 0 and liq is not None:
        if liq > 0:
            sol = sol_usd_at(ts)
            lu, ls = liq / math.sqrt(mcap * sol), liq / 2 / sol
            u = st["u"]
            if u is None:
                st["u"] = [lu, lu, ls, ls, ts]
            else:
                u[0], u[2] = max(u[0], lu), max(u[2], ls)
                if ts >= u[4]:
                    u[1], u[3], u[4] = lu, ls, ts
        else:
            st["z"] = max(st["z"], ts)
    if liq_sol and liq_sol > 0 and price_native and price_native > 0:
        L = liq_sol / math.sqrt(price_native)
        v = st["s"].get(pool or "?")
        if v is None:
            st["s"][pool or "?"] = [L, L, liq_sol, liq_sol, ts, dex]
        else:
            v[0], v[2] = max(v[0], L), max(v[2], liq_sol)
            if ts >= v[4]:
                v[1], v[3], v[4], v[5] = L, liq_sol, ts, dex or v[5]


def add(acc, token, ts, mcap, liq, liq_sol=None, price_native=None, pool=None, dex=None):
    """Fold one observation into acc[token] = [peak_mcap, peak_liq, last_mcap, last_liq, last_ts, series]."""
    r = acc.setdefault(token, [0.0, 0.0, None, None, 0, _series()])
    if len(r) < 6:
        r.append(_series())
    if mcap:
        r[0] = max(r[0], mcap)
    if liq:
        r[1] = max(r[1], liq)
    if ts >= r[4] and mcap:
        r[2], r[3], r[4] = mcap, liq, ts
    _fold(r[5], ts, mcap, liq, liq_sol, price_native, pool, dex)
    return r


def pool_drops(peak_row, live_mcap=None, live_liq=None, now=None):
    """{"l_drop", "sol_drop", "cp", "dex", "src", "empty"} of a peaks() row (None for a row without a series): the
    exact L of the newest pool in token_pulse when that series is as fresh as the newest snapshot (FRESH_S), else the
    USD-based L, with the live market cap / liquidity folded in as the newest point."""
    if not peak_row or len(peak_row) < 6 or not isinstance(peak_row[5], dict):
        return None
    st = peak_row[5]
    u = list(st["u"]) if st["u"] else None
    z = st["z"]
    now = int(now or time.time())
    if live_mcap and live_mcap > 0 and live_liq is not None:
        if live_liq > 0:
            sol = sol_usd_at(now)
            lu, ls = live_liq / math.sqrt(live_mcap * sol), live_liq / 2 / sol
            u = [max(u[0], lu), lu, max(u[2], ls), ls, now] if u else [lu, lu, ls, ls, now]
        else:
            z = max(z, now)
    newest = max(st["s"].items(), key=lambda kv: kv[1][4]) if st["s"] else None
    dex = newest[1][5] if newest else None
    out = {"l_drop": None, "sol_drop": None, "cp": is_cp(dex), "dex": dex, "src": None, "empty": False}
    u_ts = u[4] if u else 0
    if z > u_ts and z >= (newest[1][4] if newest else 0):
        out.update(l_drop=1.0, sol_drop=1.0, src="likvidnost 0", empty=True)
        return out
    if newest and newest[1][4] >= u_ts - FRESH_S:
        pl, ll, ps, ls = newest[1][:4]
        out.update(l_drop=1 - ll / pl if pl else None, sol_drop=1 - ls / ps if ps else None, src="sol")
    elif u:
        out.update(l_drop=1 - u[1] / u[0] if u[0] else None, sol_drop=1 - u[3] / u[2] if u[2] else None, src="usd")
    return out


def assess(peak_row, live_mcap=None, live_liq=None, token=None, evidence=None):
    """The rug OR the dump after a pump of a peaks() row (judge's dict), preferring a live market cap / liquidity when
    given (and counting it into the peak and the pool series). token: for a dump the evidence (rug_evidence) is looked
    up, which can make it a rug; evidence given: used as is."""
    if not peak_row:
        return None
    pm, pl, lm, ll = peak_row[:4]
    now_m = live_mcap if live_mcap is not None else lm
    now_l = live_liq if live_liq is not None else ll
    args = (max(pm or 0, now_m or 0), now_m, max(pl or 0, now_l or 0) or None, now_l)
    pool = pool_drops(peak_row, live_mcap, live_liq)
    j = judge(*args, evidence=evidence, pool=pool)
    if j and j["kind"] == "dump" and evidence is None and token:
        ev = rug_evidence(token)
        if ev:
            j = judge(*args, evidence=ev, pool=pool)
    return j


def check(peak_row, live_mcap=None, live_liq=None, token=None, evidence=None):
    """The RUG of a peaks() row under the owner's rule (judge kind "rug"), or None: no collapse, or only a dump after
    a pump (assess() returns that one). Every caller that blocks on it blocks only a rug."""
    j = assess(peak_row, live_mcap, live_liq, token, evidence)
    return j if j and j["kind"] == "rug" else None


# ---------- the evidence that turns a crash into a rug -----------------------------------------------------------
def _rug_db():
    if RUG_DB:
        return RUG_DB
    try:
        from ui import data
        return data.RUG_DB
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rug.db")


def rug_report(token, path=None):
    """(verdict, score, data dict) of the newest rug.db report of the token, or None (read-only, one row)."""
    p = path or _rug_db()
    if not token or not p or not os.path.exists(p):
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None
    try:
        r = con.execute("SELECT verdict, score, data FROM rug_reports WHERE mint=? ORDER BY checked_at DESC LIMIT 1",
                        (token,)).fetchone()
    except sqlite3.Error:
        r = None
    finally:
        con.close()
    if not r:
        return None
    try:
        d = json.loads(r[2]) if isinstance(r[2], str) and r[2] else (r[2] or {})
    except ValueError:
        d = {}
    return r[0], r[1], d if isinstance(d, dict) else {}


MECHANICS = ("mint authority", "freeze authority", "RugCheck ga je označio kao rugan")
DEV_SELLS = ("dev je prodao", "dev je prebacio")


def rug_signals(token, path=None):
    """{"mechanics", "risk", "dev"}: Croatian lines from the rug filter's newest report (each None when not there):
    mechanics = mint / freeze authority or RugCheck "rugged" (hard fails); risk = VISOK RIZIK, or ODBAČEN on anything
    but "likvidnost samo" (rug_risk high); dev = the dev sold or moved his tokens."""
    out = {"mechanics": None, "risk": None, "dev": None}
    rep = rug_report(token, path)
    if not rep:
        return out
    v, sc, d = rep
    hard = [str(h) for h in d.get("hard_fails") or [] if h]
    flags = [str(f) for f in d.get("flags") or [] if f]
    mech = [h for h in hard if h.startswith(MECHANICS)]
    if mech:
        out["mechanics"] = f"rug mehanika: {mech[0]}"
    real_hard = [h for h in hard if not h.startswith("likvidnost samo")]
    if v == "VISOK RIZIK":
        out["risk"] = "rug filter: visok rizik" + (f", ocjena {float(sc):.0f}/100" if sc is not None else "")
    elif v == "ODBAČEN" and real_hard:
        out["risk"] = f"rug filter: odbačen ({real_hard[0]})"
    dev = [x for x in hard + flags if any(w in x for w in DEV_SELLS)]
    if dev:
        out["dev"] = f"dev prodaje ({dev[0]})"
    return out


def _holders_selling(token):
    """rangedca/holders' newest reading (range.db kv hold:<token>, only tokens with an open range round): the holders
    that got the token by transfer net-sold > 2 % of supply in 15 min, within the last day."""
    try:
        from rangedca import data as rdata
        con = rdata.ro()
    except Exception:  # noqa: BLE001
        return None
    if con is None:
        return None
    try:
        st = rdata.kv_get(con, f"hold:{token}") or {}
    except sqlite3.Error:
        st = {}
    finally:
        con.close()
    if st.get("why") and time.time() - (st.get("checked") or 0) <= 86400:
        return f"top holderi prodaju ({st['why']})"
    return None


def rug_evidence(token, now=None):
    """The line that makes a crash a rug (the dev / a top holder selling, or the rug filter's high risk), or None.
    Cached EVIDENCE_TTL_S per token; any read error is no evidence."""
    now = now or time.time()
    hit = _EVIDENCE.get(token)
    if hit and now - hit[0] < EVIDENCE_TTL_S:
        return hit[1]
    try:
        sg = rug_signals(token)
        ev = sg["dev"] or sg["risk"] or _holders_selling(token)
    except Exception:  # noqa: BLE001 - evidence is a reading, never the reason a loop stops
        ev = None
    if len(_EVIDENCE) > 500:
        _EVIDENCE.clear()
    _EVIDENCE[token] = (now, ev)
    return ev
