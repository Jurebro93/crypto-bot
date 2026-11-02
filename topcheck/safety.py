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


def judge(mint, rc, sell=None, full=None, pumpfun_suffix="pump"):
    """Combine the checks. `rc` is summarize_rc() output, `sell` sell_test() output, `full` the newest rug.db row
    ({'verdict', 'data': {'hard_fails': [...]}}) or None. Returns {'verdict', 'fails', 'warns', 'oks', 'checks'};
    checks maps each line the page shows (mint, freeze, lp, holderi, dev, honeypot, rug filter) to (status, text),
    status in 'ok' | 'warn' | 'fail' | None (not checked)."""
    fails, warns, oks, checks = [], [], [], {}

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
        if rc["launchpad"] and (lp is None or lp >= LP_WARN):
            put("lp", "ok", f"likvidnost na launchpadu ({rc['launchpad']}), tvorac je ne može izvući")
        elif lp is None:
            put("lp", None, "nema podatka o LP-u")
        elif lp < LP_FAIL:
            put("lp", "fail", f"LP zaključan ili spaljen samo {lp:.0f}%: likvidnost se može izvući")
        elif lp < LP_WARN:
            put("lp", "warn", f"LP zaključan ili spaljen {lp:.0f}%")
        else:
            put("lp", "ok", f"LP zaključan ili spaljen {lp:.0f}%")
        t10 = rc["top10"]
        if t10 is None:
            put("holderi", None, "nema podatka o holderima")
        elif t10 > TOP10_FAIL:
            put("holderi", "fail", f"top 10 holdera drži {t10:.0f}% (bez poolova)")
        elif t10 > TOP10_WARN:
            put("holderi", "warn", f"top 10 holdera drži {t10:.0f}%")
        else:
            put("holderi", "ok", f"top 10 holdera drži {t10:.0f}%")
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
        if v == "ODBAČEN":
            put("rugfilter", "fail", "rug filter: " + (hard[0] if hard else "ODBAČEN"))
        elif v == "VISOK RIZIK":
            put("rugfilter", "warn", "rug filter: visok rizik")
        else:
            put("rugfilter", "ok", f"rug filter: {(v or '').lower() or 'prošao'}")
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
