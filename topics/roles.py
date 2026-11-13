"""The role of every token of one event topic (pure, no I/O): main | clone | rug | other.

  rug    the rug check (ui/kandidati.rug_view, the same one get_trade_candidates and the scanner use) says hard (a
         collapse, the rug archive, mint / freeze authority, RugCheck rugged, honeypot) or risk (the rug filter's
         ODBAČEN / VISOK RIZIK, supply concentration, topcheck 'pao')
  clone  younger than CLONE_AGE_S (30 min) AND first-slot buyers hold more than CLONE_SNIPER_PCT (30 %) of the supply.
         The sniper share is, best first: the pump.fun board's snipersOwnedPercent + bundlerOwnedPercent (hype.db
         hype_details, what they HOLD now), the rug filter's sniper_pct + bundle_pct (rug.db, bought in the creation
         slot and the first ~8 s), or our own first page of the mint's transactions (Helius, capped, only at 30k+:
         CLAUDE.md, under 30k is not analysed). Unknown share: never a clone.
  main   at most one per topic: of the tokens that are neither rug nor clone, the most liquid one WITH ORGANIC X
         (ties: the oldest). Organic X = a fresh row (6 h) from Grok (submit_x_features) or the scanner's own count
         with at least ORGANIC_AUTHORS unique authors in 15 min, or ORGANIC_POSTS posts in 60 min when the authors are
         not known, or a known caller / large account named, and a bot share under 50 % (unknown counts as none).
         When no token of the topic has any X row at all, the oldest bonded token with liquidity >= $20k and market
         cap >= $30k is main ("bez X-a": a weaker main, said so in role_why).
  other  everything else.
"""
CLONE_AGE_S = 30 * 60
CLONE_SNIPER_PCT = 30.0
ORGANIC_AUTHORS = 3
ORGANIC_POSTS = 10
X_FRESH_S = 6 * 3600
MAIN_MIN_LIQ = 20_000
MAIN_MIN_MCAP = 30_000


def organic(x, now):
    """True when an X row (scan/xmom.latest shape) shows organic attention (see the module text)."""
    if not x or now - (x.get("ts") or 0) > X_FRESH_S:
        return False
    bots = x.get("bot_share")
    if bots is not None and bots >= 0.5:
        return False
    if x.get("known_callers") or x.get("large_accounts"):
        return True
    a15 = x.get("authors15")
    if a15 is not None:
        return a15 >= ORGANIC_AUTHORS
    return (x.get("posts60") or 0) >= ORGANIC_POSTS


def is_clone(age_s, sniper_pct):
    return age_s is not None and age_s < CLONE_AGE_S and sniper_pct is not None and sniper_pct > CLONE_SNIPER_PCT


def classify(rows, now):
    """rows: [{"token", "created_ts", "sniper_pct", "rug_level", "liq", "mcap", "bonded", "x"}] of one topic.
    Returns {token: (role, why)}."""
    out = {}
    rest = []
    for r in rows:
        age = (now - r["created_ts"]) if r.get("created_ts") else None
        if r.get("rug_level") in ("hard", "risk"):
            out[r["token"]] = ("rug", f"rug provjera: {r['rug_level']}")
        elif is_clone(age, r.get("sniper_pct")):
            out[r["token"]] = ("clone", f"star {age / 60:.0f} min, snajperi drže {r['sniper_pct']:.0f} %")
        else:
            rest.append(r)
    with_x = [r for r in rest if organic(r.get("x"), now)]
    main, why = None, None
    if with_x:
        main = max(with_x, key=lambda r: (r.get("liq") or 0, -(r.get("created_ts") or now)))
        why = f"najlikvidniji s organskim X-om (likvidnost ${main.get('liq') or 0:,.0f})"
    elif not any(r.get("x") for r in rows):
        ok = [r for r in rest if r.get("bonded") and (r.get("liq") or 0) >= MAIN_MIN_LIQ
              and (r.get("mcap") or 0) >= MAIN_MIN_MCAP and r.get("created_ts")]
        if ok:
            main = min(ok, key=lambda r: r["created_ts"])
            why = "bez X-a: najstariji bondani s likvidnošću od $20k"
    for r in rest:
        out[r["token"]] = ("main", why) if main is r else ("other", None)
    return out
