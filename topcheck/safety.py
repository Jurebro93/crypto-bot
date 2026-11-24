"""Obavezan rug check za preporučene tokene. Pure functions over data fetched by run_top.py, tested offline.

Sources, all free or already paid for:
  RugCheck report (free API)   mint / freeze authority, LP locked or burned, top holders, creator, Token-2022
                               extensions (transfer fee, permanent delegate, non-transferable, transfer hook)
  Jupiter quote (free API)     can it be SOLD and how much comes back: the honeypot test
  rug filter (Helius, plan)    rugfilter/check.py full report from rug.db: bundles, snipers, dev history, clusters,
                               wash volume; at most every few hours per token under a daily cap

Verdict:
  pao       a hard rug mechanic: the token is hidden from suggestions and cannot be bought from them
  oprez     something to know before buying (shown as ⚠ with the reasons)
  prolazi   every check that ran passed
  nepoznato no data yet (RugCheck did not answer)
"""

LP_FAIL, LP_WARN = 20.0, 80.0            # % of LP locked or burned (outside a launchpad curve)
TOP10_FAIL, TOP10_WARN = 60.0, 35.0      # % held by the 10 largest holders, pools and lockers excluded
DEV_FAIL, DEV_WARN = 20.0, 5.0           # % the creator still holds
FEE_FAIL = 10.0                          # transfer fee %
SELL_FAIL, SELL_WARN = 0.5, 0.85         # share of the value that comes back on a test sale (price impact included)
# 11.11. (Grok's notes #74 / #77): DAKITTY (-99 %) and DacityCoin 2 (-93 %) got 'prolazi' while both traded on bot
# volume: the judge never looked at the trades. volume_check() reads what run_top already has, no new call: the
# DexScreener pair (buys / sells and volume per window, liquidity) and, when run_live is subscribed to the token, its
# PumpPortal trades of the last hour (hype.db live_trades: unique traders, round trips, repeated sizes, bot timing
# through rugfilter/analysis, the same wash score scan/filters.fees_filter uses), plus the full rug filter's own
# wash score when rug.db has one.
WASH_FAIL, WASH_WARN = 60.0, 35.0        # rugfilter/score T wash_hard / wash_warn (0 organic .. 100 fake)
WASH_MIN_TRADES = 20                     # PumpPortal trades needed to judge (= scan/filters.fees_filter)
MIN_TRADERS, MIN_TRADERS_TX = 20, 100    # fewer unique wallets than this on 100+ trades = a few wallets churn it
MAX_TRADES_PER_TRADER = 10.0
TURNOVER_H1 = 25.0                       # 1 h volume over liquidity (= scan max_turnover_h1)
TURNOVER_H24 = 200.0                     # 24 h volume over liquidity
SYM_MAX = 0.01                           # buys and sells within 1 % of each other ...
SYM_MIN_TX_H1, SYM_MIN_TX_H24 = 300, 3000   # ... in BOTH the hour (300+ tx) and the day (3,000+ tx): paired bot trades
MICRO_MIN_TX, MICRO_USD = 500, 8.0       # 500+ transactions in the hour averaging under $8: volume-bot prints


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def summarize_rc(rc, extra_pools=()):
    """The few facts we need from a RugCheck report (reports can be 2 MB; only this small dict is stored).
    `extra_pools`: pool addresses known from elsewhere (DexScreener pairAddress), never counted as holders."""
    if not rc or not isinstance(rc, dict):
        return None
    tok = rc.get("token") or {}
    supply = _num(tok.get("supply")) or 0
    dec = int(tok.get("decimals") or 0)
    known = rc.get("knownAccounts") or {}
    # every account RugCheck knows by name is infrastructure (AMM, locker, launchpad curve, stake pool...), except the
    # creator, who is judged separately
    pools = {a for a, v in known.items() if (v or {}).get("type") != "CREATOR"} | set(extra_pools)
    best_lp, best_usd = None, -1.0
    for m in rc.get("markets") or []:
        pools.add(m.get("pubkey"))
        for side in ("liquidityAAccount", "liquidityBAccount"):
            acc = m.get(side) or {}
            pools.add(acc.get("owner"))
            pools.add(m.get(side.replace("Account", "")))
        lp = m.get("lp") or {}
        usd = (_num(lp.get("quoteUSD")) or 0) + (_num(lp.get("baseUSD")) or 0)
        if lp.get("lpLockedPct") is not None and usd > best_usd:
            best_lp, best_usd = _num(lp.get("lpLockedPct")), usd
    pools.discard(None)
    holders = [h for h in rc.get("topHolders") or []
               if h.get("address") not in pools and h.get("owner") not in pools and (_num(h.get("pct")) or 0) > 0]
    top10 = round(sum(_num(h.get("pct")) or 0 for h in holders[:10]), 1) if holders else None
    if not rc.get("markets"):   # partial report (RugCheck still scanning): the pool cannot be told from a whale
        top10 = None
    insiders = round(sum(_num(h.get("pct")) or 0 for h in holders if h.get("insider")), 1)
    cb = _num(rc.get("creatorBalance")) or 0
    dev = None
    if supply:
        dev = cb / supply * 100
        if dev > 100 and dec:
            dev = cb * 10 ** dec / supply * 100
        dev = round(dev, 1)
    ext = rc.get("token_extensions") or {}
    fee = _num((rc.get("transferFee") or {}).get("pct")) or 0
    das = ext.get("defaultAccountState")
    return {
        "mint_auth": rc.get("mintAuthority") or tok.get("mintAuthority"),
        "freeze_auth": rc.get("freezeAuthority") or tok.get("freezeAuthority"),
        "rugged": bool(rc.get("rugged")),
        "launchpad": ((rc.get("launchpad") or {}).get("name") or "") or None,
        "lp_locked": None if best_lp is None else round(best_lp, 1),
        "has_market": bool(rc.get("markets")),
        "top10": top10, "insiders": insiders, "dev_pct": dev,
        "creator_tokens": len(rc.get("creatorTokens") or []),
        "holders": rc.get("totalHolders"),
        "fee": fee,
        "perm_delegate": bool(ext.get("permanentDelegate")),
        "non_transferable": bool(ext.get("nonTransferable")),
        "transfer_hook": bool(ext.get("transferHook")),
        "frozen_default": bool(das) and "frozen" in str(das).lower(),
        "danger": [r.get("name") for r in rc.get("risks") or [] if r.get("level") == "danger"][:5],
        "decimals": dec, "supply": supply,
    }


def summarize_light(sm):
    """Fallback from RugCheck's light /report/summary: authorities and LP from its risk list, no holder data."""
    if not sm or not isinstance(sm, dict) or "risks" not in sm:
        return None
    names = " | ".join((r.get("name") or "").lower() for r in sm.get("risks") or [])
    ext = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    return {
        "mint_auth": "mint authority" in names or None, "freeze_auth": "freeze authority" in names or None,
        "rugged": "rugged" in names, "launchpad": None,
        "lp_locked": None if sm.get("lpLockedPct") is None else round(_num(sm["lpLockedPct"]) or 0, 1),
        "has_market": True, "top10": None, "insiders": 0, "dev_pct": None, "creator_tokens": 0, "holders": None,
        "fee": 0, "perm_delegate": "permanent" in names, "non_transferable": False,
        "transfer_hook": "transfer hook" in names and sm.get("tokenProgram") == ext, "frozen_default": False,
        "danger": [r.get("name") for r in sm.get("risks") or [] if r.get("level") == "danger"][:5],
        "decimals": None, "supply": 0, "light": True,
    }


def sell_test(quote, usd_in):
    """Jupiter sell quote -> {'ok', 'ratio', 'impact', 'err'}; ratio = share of the value that comes back."""
    if quote is None:
        return {"ok": None, "ratio": None, "impact": None, "err": "Jupiter nije odgovorio"}
    if quote.get("error") or quote.get("errorCode") or not quote.get("outAmount"):
        return {"ok": False, "ratio": None, "impact": None,
                "err": str(quote.get("errorCode") or quote.get("error") or "nema rute za prodaju")[:80]}
    usd_out = _num(quote.get("_usd_out"))
    ratio = round(usd_out / usd_in, 3) if usd_out is not None and usd_in else None
    impact = _num(quote.get("priceImpactPct"))
    return {"ok": True, "ratio": ratio, "impact": None if impact is None else round(impact * 100, 2), "err": None}


def _window(pair, key):
    """(buys, sells, volume_usd) of one DexScreener window (m5, h1, h6, h24); zeros when missing."""
    tx = ((pair or {}).get("txns") or {}).get(key) or {}
    return int(tx.get("buys") or 0), int(tx.get("sells") or 0), _num(((pair or {}).get("volume") or {}).get(key)) or 0.0


def volume_check(pair=None, trades=None, full_wash=None):
    """(status, text) of the bot / wash volume check, status 'fail' | 'warn' | 'ok' | None (no data: not checked).
    pair: the DexScreener pair; trades: [{side, wallet, amount, ts}] of the last hour (PumpPortal); full_wash: the rug
    filter's wash score. fail = wash score >= WASH_FAIL. warn (the first that applies): wash >= WASH_WARN, too few
    unique traders for the trades, too many trades per trader, 1 h or 24 h volume far over the liquidity, buys and
    sells equal within 1 % in both the hour and the day on many transactions, a flood of tiny transactions."""
    rows = [t for t in trades or [] if t.get("side") in ("buy", "sell")]
    vq, wash = None, _num(full_wash)
    if len(rows) >= WASH_MIN_TRADES:
        from rugfilter import analysis
        vq = analysis.volume_quality(rows)
        w = analysis.wash_score(vq)
        if w is not None and (wash is None or w > wash):
            wash = w
    detail = (f": {vq['wallets']} različitih novčanika na {vq['trades']} tradeova, round trip "
              f"{vq['round_trip_volume_pct']:.0f}% volumena, botovski ritam {vq['bot_timing_volume_pct']:.0f}%") if vq else ""
    if wash is not None and wash >= WASH_FAIL:
        return "fail", f"volumen lažan: wash {wash:.0f}/100 (granica {WASH_FAIL:g}){detail}"
    if wash is not None and wash >= WASH_WARN:
        return "warn", f"volumen sumnjiv: wash {wash:.0f}/100 (granica {WASH_WARN:g}){detail}"
    if vq and vq["trades"] >= MIN_TRADERS_TX and vq["wallets"] < MIN_TRADERS:
        return "warn", (f"volumen vrti nekoliko novčanika: {vq['wallets']} različitih na {vq['trades']} tradeova u "
                        f"satu (treba {MIN_TRADERS}+)")
    if vq and vq["trades_per_wallet"] > MAX_TRADES_PER_TRADER:
        return "warn", (f"volumen botovski: {vq['trades_per_wallet']:.0f} tradeova po novčaniku u satu "
                        f"(granica {MAX_TRADES_PER_TRADER:g})")
    liq = _num(((pair or {}).get("liquidity") or {}).get("usd")) or 0.0
    b1, s1, v1 = _window(pair, "h1")
    b24, s24, v24 = _window(pair, "h24")
    if liq > 0 and v1 / liq > TURNOVER_H1:
        return "warn", f"volumen se vrti: promet sata {v1 / liq:.0f}× likvidnosti (granica {TURNOVER_H1:g}×)"
    if liq > 0 and v24 / liq > TURNOVER_H24:
        return "warn", f"volumen se vrti: promet dana {v24 / liq:.0f}× likvidnosti (granica {TURNOVER_H24:g}×)"
    n1, n24 = b1 + s1, b24 + s24
    if n1 >= SYM_MIN_TX_H1 and n24 >= SYM_MIN_TX_H24 and abs(b1 - s1) / n1 <= SYM_MAX and abs(b24 - s24) / n24 <= SYM_MAX:
        return "warn", (f"volumen botovski: kupnje i prodaje gotovo jednake ({b1}/{s1} u satu, {b24}/{s24} u 24 h), "
                        "tipično za botove koji kupuju i odmah prodaju")
    if n1 >= MICRO_MIN_TX and v1 / n1 < MICRO_USD:
        return "warn", (f"volumen botovski: {n1} transakcija u satu, prosječno ${v1 / n1:.2f} po transakciji "
                        f"(granica ${MICRO_USD:g})")
    if vq:
        return "ok", f"volumen izgleda organski ({vq['wallets']} novčanika na {vq['trades']} tradeova u satu)"
    if pair and (n1 or v1):
        return "ok", f"volumen bez znakova botova u paru ({n1} transakcija u satu)"
    return None, "volumen: nema podatka o tradeovima"


def judge(mint, rc, sell=None, full=None, pumpfun_suffix="pump", pair=None, trades=None):
    """Combine the checks. `rc` is summarize_rc() output, `sell` sell_test() output, `full` the newest rug.db row
    ({'verdict', 'data': {'hard_fails': [...], 'flags': [...], 'holders': {'top10_pct'}, ...}}) or None. Returns
    {'verdict', 'fails', 'warns', 'oks', 'checks'}; checks maps each line the page shows (mint, freeze, lp, holderi,
    dev, honeypot, rug filter, volumen) to (status, text), status in 'ok' | 'warn' | 'fail' | None (not checked).
    9.11. (audit P36): holders unknown is a warn, so the verdict is 'oprez', never 'prolazi' on missing data.
    11.11. (Grok #74 / #77): pair (DexScreener) and trades (PumpPortal, last hour) feed volume_check: bot or wash
    volume is 'oprez' (or 'pao' at a wash score of WASH_FAIL+) with the reason; no data leaves the line unchecked."""
    fails, warns, oks, checks = [], [], [], {}
    fdata = (full or {}).get("data") or {}
    full_t10 = _num((fdata.get("holders") or {}).get("top10_pct"))   # 9.11. (audit P29): rug.db top10 when RugCheck has none

    def put(key, status, text):
        checks[key] = (status, text)
        {"fail": fails, "warn": warns, "ok": oks}.get(status, []).append(text)

    pump = mint.endswith(pumpfun_suffix)
    if rc:
        if rc["rugged"]:
            put("rugcheck", "fail", "RugCheck ga vodi kao rugan")
        if rc["mint_auth"] and not pump:
            put("mint", "fail", "mint authority aktivan: tvorac može tiskati nove tokene")
        else:
            put("mint", "ok", "mint authority ugašen")
        if rc["freeze_auth"] and not pump:
            put("freeze", "fail", "freeze authority aktivan: tvorac ti može zamrznuti tokene")
        else:
            put("freeze", "ok", "freeze authority ugašen")
        lp = rc["lp_locked"]
        pad = rc["launchpad"] or ("pump.fun" if pump and rc.get("light") else None)
        if pad and (lp is None or lp >= LP_WARN or rc.get("light")):
            put("lp", "ok", f"likvidnost na launchpadu ({pad}), tvorac je ne može izvući")
        elif lp is None:
            put("lp", None, "nema podatka o LP-u")
        elif lp < LP_FAIL:
            put("lp", "fail", f"LP zaključan ili spaljen samo {lp:.0f}%: likvidnost se može izvući")
        elif lp < LP_WARN:
            put("lp", "warn", f"LP zaključan ili spaljen {lp:.0f}%")
        else:
            put("lp", "ok", f"LP zaključan ili spaljen {lp:.0f}%")
        t10, src = rc["top10"], ""
        if t10 is None and full_t10 is not None:
            t10, src = full_t10, " (rug filter)"
        if t10 is None:
            put("holderi", "warn", "nema podatka o holderima: koncentracija nepoznata")
        elif t10 > TOP10_FAIL:
            put("holderi", "fail", f"top 10 holdera drži {t10:.0f}% (bez poolova){src}")
        elif t10 > TOP10_WARN:
            put("holderi", "warn", f"top 10 holdera drži {t10:.0f}%{src}")
        else:
            put("holderi", "ok", f"top 10 holdera drži {t10:.0f}%{src}")
        dev = rc["dev_pct"]
        many = rc["creator_tokens"] >= 10
        if dev is not None and dev > DEV_FAIL:
            put("dev", "fail", f"dev još drži {dev:.0f}%")
        elif (dev or 0) > DEV_WARN or many:
            put("dev", "warn", (f"dev drži {dev:.0f}%" if (dev or 0) > DEV_WARN else "dev ne drži velik udio")
                + (f", napravio je {rc['creator_tokens']} tokena" if many else ""))
        else:
            put("dev", "ok", "dev ne drži velik udio" if dev is not None else "dev: nema podatka")
        trap = []
        if rc["fee"] >= FEE_FAIL:
            trap.append(f"porez na prijenos {rc['fee']:.0f}%")
        if rc["perm_delegate"]:
            trap.append("permanent delegate (netko ti može uzeti tokene)")
        if rc["non_transferable"]:
            trap.append("token se ne može prenijeti")
        if rc["frozen_default"]:
            trap.append("novi računi su zamrznuti")
        if trap:
            put("honeypot", "fail", "honeypot: " + ", ".join(trap))
        for d in rc["danger"]:
            if d and not any(d.lower() in x.lower() for x in fails):
                warns.append(f"RugCheck upozorava: {d}")
    else:
        put("mint", None, "RugCheck nije odgovorio")
    if "honeypot" not in checks:
        s = sell or {}
        if s.get("ok") is False:
            put("honeypot", "warn", f"test prodaje nije našao rutu ({s.get('err') or 'nema rute'})")
        elif s.get("ok") and s.get("ratio") is not None and s["ratio"] < SELL_FAIL:
            put("honeypot", "fail", f"honeypot: na testnoj prodaji vrati se samo {s['ratio']:.0%} vrijednosti")
        elif s.get("ok") and s.get("ratio") is not None and s["ratio"] < SELL_WARN:
            put("honeypot", "warn", f"testna prodaja vraća {s['ratio']:.0%} vrijednosti (porez ili tanka likvidnost)")
        elif s.get("ok"):
            put("honeypot", "ok", "testna prodaja prolazi" + (f" ({s['ratio']:.0%} vrijednosti)" if s.get("ratio") else ""))
        elif rc and rc["transfer_hook"]:
            put("honeypot", "warn", "transfer hook: program može blokirati prodaju")
        else:
            put("honeypot", None, "test prodaje nije napravljen")
    if full:
        v = full.get("verdict")
        hard = ((full.get("data") or {}).get("hard_fails") or [])
        if rc and rc["launchpad"]:   # on the bonding curve DexScreener reports no liquidity: not a rug mechanic
            hard = [h for h in hard if not h.startswith("likvidnost samo")]
            if v == "ODBAČEN" and not hard:
                v = "OPREZ"
        flags = [f for f in (fdata.get("flags") or []) if f]
        if v == "ODBAČEN":
            put("rugfilter", "fail", "rug filter: " + (hard[0] if hard else "ODBAČEN"))
        elif v == "VISOK RIZIK":
            put("rugfilter", "warn", "rug filter: visok rizik" + (f" ({flags[0]})" if flags else ""))
        elif v == "OPREZ":   # 9.11. (audit P29): snipers, bundles, fresh wallets, clusters under the hard line are a warn
            put("rugfilter", "warn", "rug filter: oprez" + (f" ({flags[0]})" if flags else ""))
        else:
            put("rugfilter", "ok", f"rug filter: {(v or '').lower() or 'prošao'}")
    if pair is not None or trades or fdata.get("wash_score") is not None:
        put("volumen", *volume_check(pair, trades, fdata.get("wash_score")))
    if fails:
        verdict = "pao"
    elif not rc:
        verdict = "nepoznato"
    elif warns:
        verdict = "oprez"
    else:
        verdict = "prolazi"
    return {"verdict": verdict, "fails": fails, "warns": warns, "oks": oks,
            "checks": {k: list(v) for k, v in checks.items()}}
