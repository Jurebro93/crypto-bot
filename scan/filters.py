"""The scanner's filters. Pure where possible (a market dict `m` in, a reason or None out), tested offline.

A market dict (scan/market.py builds it from DexScreener, GeckoTerminal and the PumpPortal tables):
    token symbol name price mcap liq vol_m5 vol_h1 vol_h24 txns_m5 txns_h1 buys_h1 sells_h1 buyers_h1 ch_m5 ch_h1
    ch_h24 dex curve (True = still on a bonding curve) src

Order of one check (scan/market.check): stage_filter -> entry_gates (league/copy._enter's gates) -> fees_filter ->
facts (free tables first, Helius only now and within the day's credit cap) -> rug_check. The first failing filter
is the reason ("why"); the ones that passed are the pass reasons shown in get_market_signals.

Two rules are kept apart because the sources differ:
  why      the scanner's own rule (sources scan and beta): stage_filter in full, a migrated token needs 1 h volume
  why_sig  the rule for a caller / wallet signal (the baseline the scanner is compared with): the same filters
           without the scanner's volume rule (the Autopilot copies a call on its own gates, not on volume)
"""
import json

from league import copy as lcopy

VOLUME_RULE = "stage_volume"


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def stage_filter(m, cfg):
    """(stage, tradeable, why, why_sig). The phase rules (CLAUDE.md, 10.11. owner's update):
      final_stretch  still on the bonding curve (pump.fun and other launchpads) with market cap >= final_stretch_min_mcap
                     (10k): measured only, NEVER tradeable (new pump.fun tokens are not taken, bonded ones are)
      migrated       bonded (a PumpSwap / Raydium / other AMM pair) with 1 h volume >= migrated_min_vol_h1 (30k);
                     tradeable only at market cap >= trade_min_mcap (never under 30k)
    A migrated token under the volume line fails the scanner's rule (why = VOLUME_RULE) but not a caller signal's."""
    mcap, vol = _f(m.get("mcap")) or 0, _f(m.get("vol_h1")) or 0
    if m.get("curve"):
        floor = float(cfg["final_stretch_min_mcap"])
        if mcap < floor:
            why = f"na krivulji, MC ${mcap:,.0f} ispod ${floor:,.0f} (final stretch)"
            return "curve", False, why, why
        return "final_stretch", False, None, None
    tradeable = mcap >= float(cfg["trade_min_mcap"])
    if vol < float(cfg["migrated_min_vol_h1"]):
        return "migrated", tradeable, VOLUME_RULE, None
    return "migrated", tradeable, None, None


def volume_rule_text(m, cfg):
    return (f"migriran, ali volumen 1 h ${_f(m.get('vol_h1')) or 0:,.0f} ispod "
            f"${float(cfg['migrated_min_vol_h1']):,.0f}")


def entry_gates(m, stage, archived=frozenset(), dead=frozenset()):
    """The copy loop's own entry gates (league/copy._enter) that do not depend on a follow: liquidity, market cap
    ceiling, fake pool, liquidity / market cap ratio, not a memecoin, rug archive and collapse; plus hype/tokenstatus:
    a token the 6-hourly status pass found without a DexScreener pair (dead) and that DexScreener does not price now
    either. The 30k floor is not a reason here: under it the token is measured with tradeable=false (stage_filter).
    On the curve the pool gates do not apply (a curve has no pool; such a token is never tradeable anyway). None or
    the reason in Croatian."""
    from kol import converge
    tok = m["token"]
    price, liq, mcap = _f(m.get("price")), _f(m.get("liq")) or 0, _f(m.get("mcap")) or 0
    c = lcopy.CFG
    if not price:
        return "nema cijene (DexScreener / GeckoTerminal)"
    nm = converge.not_a_memecoin(tok, m.get("symbol"), liq if liq else None)
    if nm:
        return nm
    if tok in archived:
        return "token je u arhivi rugova"
    if tok in dead and m.get("src") != "dexscreener":
        return "DexScreener više nema par tog tokena (status tokena)"
    if stage != "final_stretch":
        if liq < c["min_liq"]:
            return f"premala likvidnost (${liq:,.0f}), ne bi se moglo izaći"
        if mcap and mcap > c["max_mcap"]:
            return "velik token (preko $50M), to nije poziv na memecoin"
        if mcap and liq > mcap:
            return "lažni pool (likvidnost veća od market capa), tipičan rug"
        if mcap and liq < c["min_liq_mcap"] * mcap:
            return (f"likvidnost ${liq:,.0f} je samo {liq / mcap:.1%} MC-a (granica {c['min_liq_mcap']:.0%}): "
                    "najveći holder bi srušio cijenu prije stopa")
    col = lcopy._rugged(tok, mcap or None, liq or None)
    if col:
        return f"token je rugan ({col['text']})"
    return None


def fee_rate(m, cfg):
    r = cfg["fee_rates"]
    if m.get("curve"):
        return float(r["curve"])
    return float(r["pumpswap"] if "pump" in str(m.get("dex") or "") else r["other"])


def fees_filter(m, trades, cfg, sol_usd):
    """Enough fees paid and organic volume, not wash. PumpPortal sends no fee field, so fees_paid_sol is ESTIMATED:
    the last hour's volume in SOL times the pool's fee (fee_rates: curve 1.25 %, PumpSwap 0.3 %, other AMM 0.25 %).
    Volume comes from the token's PumpPortal trades of the last hour when run_live is subscribed to it (20+ trades;
    then also the wash score of rugfilter/analysis.volume_quality: round trips, top-5 wallets, repeated sizes, bot
    timing), else from DexScreener's 1 h volume (then wash is unknown and the turnover vol_h1 / liquidity stands in).
    Passes with fees_paid_sol >= min_fees_sol, txns_h1 >= min_txns_h1, unique buyers / traders >= min_traders_h1 (when
    known: GeckoTerminal's buyers or PumpPortal's wallets), wash <= max_wash (when known) and turnover <=
    max_turnover_h1 (when there is a pool). Returns {"why", "fees_paid_sol", "buy_share", "wash", "unique_traders",
    "src"}."""
    rate = fee_rate(m, cfg)
    out = {"why": None, "fees_paid_sol": None, "buy_share": None, "wash": None,
           "unique_traders": m.get("buyers_h1"), "src": "dexscreener"}
    rows = [t for t in trades or [] if t.get("side") in ("buy", "sell")]
    if len(rows) >= 20:
        from rugfilter import analysis
        vol_sol = sum(_f(t.get("amount")) or 0 for t in rows)
        vq = analysis.volume_quality(rows)
        out.update(src="pumpportal", fees_paid_sol=round(vol_sol * rate, 3),
                   buy_share=round(sum(1 for t in rows if t["side"] == "buy") / len(rows), 3),
                   wash=analysis.wash_score(vq), unique_traders=vq.get("wallets"))
        txns = max(len(rows), int(m.get("txns_h1") or 0))
    else:
        vol_usd = _f(m.get("vol_h1")) or 0
        out["fees_paid_sol"] = round(vol_usd / (sol_usd or 150.0) * rate, 3) if vol_usd else 0.0
        tx = int(m.get("txns_h1") or 0)
        out["buy_share"] = round((m.get("buys_h1") or 0) / tx, 3) if tx else None
        txns = tx
    liq, vol = _f(m.get("liq")) or 0, _f(m.get("vol_h1")) or 0
    if out["fees_paid_sol"] < float(cfg["min_fees_sol"]):
        out["why"] = (f"premalo plaćenih naknada u zadnjem satu (~{out['fees_paid_sol']:.2f} SOL, treba "
                      f"{float(cfg['min_fees_sol']):g}+)")
    elif txns < int(cfg["min_txns_h1"]):
        out["why"] = f"samo {txns} transakcija u zadnjem satu (treba {cfg['min_txns_h1']}+)"
    elif out["unique_traders"] is not None and int(out["unique_traders"]) < int(cfg["min_traders_h1"]):
        out["why"] = (f"samo {int(out['unique_traders'])} različitih kupaca/tradera u satu na {txns} transakcija "
                      f"(treba {cfg['min_traders_h1']}+): volumen vrti nekoliko novčanika")
    elif out["wash"] is not None and out["wash"] > float(cfg["max_wash"]):
        out["why"] = f"lažni volumen (wash {out['wash']:.0f}/100, granica {float(cfg['max_wash']):g})"
    elif liq > 0 and vol / liq > float(cfg["max_turnover_h1"]):
        out["why"] = (f"promet {vol / liq:.0f}x likvidnosti u satu (granica {float(cfg['max_turnover_h1']):g}x): "
                      "volumen se vrti, nije organski")
    return out


def rug_tables():
    """(topcheck rows, rug.db newest reports) by token: the scanner pass's cache (league/copy._CONC_CACHE) when a pass
    runs, else one fresh read."""
    cache = lcopy._CONC_CACHE
    if cache is not None:
        if "tc" not in cache:
            cache["tc"], cache["rug"] = lcopy._conc_tables()
        return cache["tc"], cache["rug"]
    return lcopy._conc_tables()


# 10.11. (Grok's note, BOXCAT): the scanner listed "rug provjera prolazi" while the bot's own rug filter (rug.db,
# run_rug.py / rugfilter/score.py) rated the token VISOK RIZIK. rug_check read only the concentration NUMBERS of that
# report (league/copy._concentration: top 10, cluster, bundle, insiders, dev), never its verdict, so a high-risk score
# from snipers, a serial dev, wash volume or dev selling passed. The verdict is a reason of its own now.
RUG_RISK_PREFIXES = ("rug filter: ", "koncentriran supply", "rug check: pao")


def is_rug_risk(why):
    """True when a scanner reason is a rug RISK rating (the rug filter's verdict, supply concentration, topcheck
    'pao'), not a collapse, a missing pool or a mint / freeze authority: ui/kandidati may override only these."""
    return bool(why) and str(why).startswith(RUG_RISK_PREFIXES)


def rug_filter_why(token, rug=None):
    """The rug filter's newest verdict as a reason (or None): ODBAČEN (a hard fail) and VISOK RIZIK (score under 50)
    fail; OPREZ, PROLAZI and no report pass. A hard fail that is only "likvidnost samo $x" is left to the live
    liquidity gates (entry_gates): the report may be from the bonding curve, before the token had a pool, and then
    its verdict is unknown (no score), not a reason."""
    if rug is None:
        rug = rug_tables()[1]
    r = (rug or {}).get(token)
    if not r:
        return None
    data = r.get("data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data) or {}
        except ValueError:
            data = {}
    v = r.get("verdict")
    hard = [str(h) for h in data.get("hard_fails") or [] if h and not str(h).startswith("likvidnost samo")]
    flags = [str(f) for f in data.get("flags") or [] if f]
    if v == "ODBAČEN" and hard:
        return f"rug filter: odbačen ({hard[0]})"
    if v == "VISOK RIZIK":
        sc = r.get("score")
        return ("rug filter: visok rizik" + (f", ocjena {float(sc):.0f}/100" if sc is not None else "")
                + (f" ({flags[0]})" if flags else ""))
    return None


def rug_filter_word(token, rug=None):
    """The rug filter's verdict in a word for the pass reason ("oprez", "prolazi", "nema izvještaja")."""
    if rug is None:
        rug = rug_tables()[1]
    r = (rug or {}).get(token) or {}
    v = r.get("verdict")
    if v == "ODBAČEN" and rug_filter_why(token, rug) is None:   # only a curve-time "likvidnost samo": see above
        return "bez ocjene (stari izvještaj s krivulje, likvidnost se provjerava sada)"
    return (v or "nema izvještaja").lower()


def rug_check(token, facts, cfg, missing_why=None):
    """The rug check of a candidate that passed the cheap filters: the bot's own rug tables first (topcheck.db
    RugCheck summary and rug.db full report through league/copy._concentration: verdict 'pao', top 10 / cluster /
    bundle / insiders / dev over the hard lines; and the rug filter's own verdict, rug_filter_why), then the facts
    (Helius or free tables): mint or freeze authority still set, top 10 wallets over max_top10_pct, fewer holders
    than min_holders. facts None = not checked yet (the day's Helius credits are spent, no key, or the call failed:
    missing_why says which): that is a reason too, the token waits. Returns (why or None, top10 text)."""
    why, shown = lcopy._concentration(token)
    if why:
        return why, shown
    rf = rug_filter_why(token)
    if rf:
        return rf, shown
    if facts is None:
        return missing_why or "čeka provjeru holdera", shown
    if facts.get("mint_auth"):
        return "mint ovlast nije odbačena: dev može tiskati nove tokene", shown
    if facts.get("freeze_auth"):
        return "freeze ovlast nije odbačena: dev može zamrznuti novčanike", shown
    t10 = _f(facts.get("top10_pct"))
    if t10 is not None and t10 > float(cfg["max_top10_pct"]):
        return f"koncentriran supply: top 10 novčanika drži {t10:.0f}% (granica {float(cfg['max_top10_pct']):g}%)", shown
    h = facts.get("holders")
    if h is not None and not facts.get("holders_capped") and h < int(cfg["min_holders"]):
        return f"samo {h} holdera (treba {cfg['min_holders']}+)", shown
    return None, (f"top10 {t10:.0f}%" if t10 is not None else shown)


SYSTEM = "11111111111111111111111111111111"


def helius_facts(mint, rpc, pages=2):
    """(facts, credits) from Helius RPC: mint / freeze authority (getAccountInfo, 1 credit), the top 10 WALLETS'
    share (getTokenLargestAccounts + two getMultipleAccounts: owners, and which owners are ordinary wallets, so the
    curve, the pool vaults and programs are not holders; 3 credits) and the holder count (DAS getTokenAccounts, 10
    credits a page of 1000, at most `pages`; holders_capped when the last page was full). facts None on an error; the
    credits spent until then are still returned (the usage meter counts every call in event_calendar/http._fetch)."""
    credits = 0
    try:
        acc = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        credits += 1
        info = (((acc or {}).get("value") or {}).get("data") or {}).get("parsed", {}).get("info") or {}
        dec = int(info.get("decimals") or 0)
        supply = float(info.get("supply") or 0) / 10 ** dec if info.get("supply") else 0.0
        big = rpc("getTokenLargestAccounts", [mint])
        credits += 1
        accts = [(a["address"], float(a.get("uiAmount") or 0)) for a in (big or {}).get("value") or []][:20]
        wallets = {}
        if accts:
            got = rpc("getMultipleAccounts", [[a for a, _ in accts], {"encoding": "jsonParsed"}])
            credits += 1
            owners = []
            for (addr, amt), a in zip(accts, (got or {}).get("value") or []):
                try:
                    owners.append((a["data"]["parsed"]["info"]["owner"], amt))
                except (TypeError, KeyError):
                    continue
            if owners:
                kinds = rpc("getMultipleAccounts", [[o for o, _ in owners],
                                                    {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])
                credits += 1
                for (o, amt), k in zip(owners, (kinds or {}).get("value") or []):
                    if k is None or k.get("owner") == SYSTEM:   # an ordinary wallet; programs and pools are not holders
                        wallets[o] = wallets.get(o, 0) + amt
        top10 = round(sum(sorted(wallets.values(), reverse=True)[:10]) / supply * 100, 1) if supply and wallets else None
        holders, capped, page = 0, False, 1
        while page <= pages:
            res = rpc("getTokenAccounts", {"mint": mint, "limit": 1000, "page": page,
                                           "options": {"showZeroBalance": False}})
            credits += 10
            rows = (res or {}).get("token_accounts") or []
            holders += len({r.get("owner") for r in rows if r.get("owner")})
            if len(rows) < 1000:
                break
            capped = page == pages
            page += 1
        return ({"top10_pct": top10, "holders": holders, "holders_capped": int(capped),
                 "mint_auth": info.get("mintAuthority"), "freeze_auth": info.get("freezeAuthority"), "src": "helius"},
                credits)
    except Exception:  # noqa: BLE001 - a failed check is "not checked", retried after the cache time
        return None, credits


HELIUS_COST = 4   # credits of helius_facts before the holder pages


def free_facts(token, tc_rows, pulse_holders):
    """Facts the bot already has, no call: topcheck.db's RugCheck summary (top 10, holders, authorities) of the
    recommended tokens, and the holder count hype/pulse keeps for retained tokens. None when neither knows the token
    well enough (top 10 or holders missing)."""
    rc = ((tc_rows or {}).get(token) or {}).get("rc") or {}
    top10 = _f(rc.get("top10"))
    holders = rc.get("holders") or (pulse_holders or {}).get(token)
    if top10 is None or not holders:
        return None
    return {"top10_pct": top10, "holders": int(holders), "holders_capped": 0,
            "mint_auth": rc.get("mint_auth") or None, "freeze_auth": rc.get("freeze_auth") or None, "src": "besplatno"}
