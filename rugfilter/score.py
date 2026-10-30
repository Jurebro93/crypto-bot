"""Hard filters and a 0-100 wallet-health score. Thresholds come from the research doc and are a starting
guess: tune them with a backtest (tokens that rugged vs. ones that held)."""

T = {
    "bundle_hard": 20, "bundle_warn": 10,
    "cluster_hard": 25, "cluster_warn": 15,
    "insider_hard": 25, "insider_warn": 10,
    "sniper_warn": 20, "sniper_mild": 10,
    "top10_warn": 50, "top10_mild": 30,
    "serial_dev_tokens": 10, "serial_dev_alive_pct": 10, "dev_many_tokens": 3,
    "dev_hold_warn": 10, "dev_sold_warn": 50,
    "fresh_warn": 50,
    "wash_hard": 60, "wash_warn": 35,
    "min_liquidity_usd": 5000, "max_slippage_pct": 5,
}


def max_entry_usd(liquidity_usd, slippage_pct=T["max_slippage_pct"]):
    """Rough trade size that moves a constant-product pool by slippage_pct (half the liquidity is each side)."""
    return round((liquidity_usd or 0) / 2 * slippage_pct / 100)


def score(r):
    hard, flags, good = [], [], []
    s = 100.0

    def flag(points, text):
        nonlocal s
        s -= points
        flags.append(text)

    a = r.get("authorities", {})
    if a.get("mintAuthority"):
        hard.append(f"mint authority nije ugašena ({a['mintAuthority'][:6]}…): dev može tiskati nove tokene")
    if a.get("freezeAuthority"):
        hard.append(f"freeze authority nije ugašena: dev može zamrznuti tvoje tokene")
    if r.get("rugcheck", {}).get("rugged"):
        hard.append("RugCheck ga je označio kao rugan")

    L = r.get("launch", {})
    if L:
        b = L.get("bundle_pct", 0)
        if b > T["bundle_hard"]:
            hard.append(f"bundle {b}% supplyja u bloku kreacije ({L['bundle_wallets']} walleta)")
        elif b > T["bundle_warn"]:
            flag(20, f"bundle {b}% supplyja ({L['bundle_wallets']} walleta)")
        elif L.get("bundle_wallets", 0) == 0:
            good.append("nema bundlea u bloku kreacije")
        sn = L.get("sniper_pct", 0)
        if sn > T["sniper_warn"]:
            flag(15, f"snajperi kupili {sn}% u prvih ~8 s ({L['sniper_wallets']} walleta)")
        elif sn > T["sniper_mild"]:
            flag(8, f"snajperi {sn}% u prvih ~8 s")

    d = r.get("dev", {})
    if d:
        n, alive = d.get("tokens_created", 0), d.get("tokens_alive", 0)
        if n >= T["serial_dev_tokens"] and 100 * alive / n < T["serial_dev_alive_pct"]:
            hard.append(f"serijski kreator: {n} tokena, živih {alive}")
        elif n >= T["dev_many_tokens"]:
            flag(10, f"kreator je napravio {n} tokena (živih {alive})")
        if d.get("hold_pct", 0) > T["dev_hold_warn"]:
            flag(10, f"dev još drži {d['hold_pct']}%")
        init = r.get("launch", {}).get("dev_initial_pct", 0)
        if init and d.get("sold_pct", 0) >= init * T["dev_sold_warn"] / 100:
            flag(10, f"dev je prodao {d['sold_pct']}% (kupio {init}% na startu)")
        if d.get("moved_pct", 0) > 1:
            flag(10, f"dev je prebacio {d['moved_pct']}% na druge wallete (skrivanje udjela)")
        if d.get("known_rugger"):
            hard.append("dev je već označen kao ruger u ranijim provjerama")
        if d.get("funder_known_bad"):
            hard.append("dev je financiran iz walleta koji je već financirao rug")
        if d.get("fresh"):
            flag(5, "dev wallet je nov (mlađi od 3 dana pri kreaciji)")

    c = r.get("cluster", {})
    cmax = max(c.get("holding_pct", 0), c.get("early_pct", 0))
    if cmax > T["cluster_hard"]:
        hard.append(f"jedan klaster ({len(c['wallets'])} walleta, isti izvor SOL-a) ima {cmax}%")
    elif cmax > T["cluster_warn"]:
        flag(15, f"klaster od {len(c['wallets'])} walleta ima {cmax}%")
    if c.get("dev_linked_early"):
        flag(15, f"{c['dev_linked_early']} ranih kupaca financirao je dev ili isti izvor kao dev (insajderi)")

    kb = r.get("known_bad", [])
    if kb:
        flag(min(30, 10 * len(kb)), f"{len(kb)} ranih kupaca ili holdera već je bilo bundler/insajder/ruger na drugim tokenima")

    ins = r.get("rugcheck", {}).get("insider_pct", 0)
    if ins > T["insider_hard"]:
        hard.append(f"RugCheck insajderska mreža drži {ins}%")
    elif ins > T["insider_warn"]:
        flag(10, f"RugCheck insajderska mreža drži {ins}%")

    h = r.get("holders", {})
    t10 = h.get("top10_pct", 0)
    if t10 > T["top10_warn"]:
        flag(15, f"top 10 holdera (bez poola) drži {t10}%")
    elif t10 > T["top10_mild"]:
        flag(8, f"top 10 holdera drži {t10}%")
    elif t10:
        good.append(f"top 10 holdera samo {t10}%")
    for key, label in (("fresh_early_pct", "ranih kupaca"), ("fresh_holders_pct", "top holdera")):
        if h.get(key, 0) > T["fresh_warn"]:
            flag(10, f"{h[key]}% {label} su fresh walleti (botovi ili jedna osoba)")

    w = r.get("wash_score")
    vq = r.get("volume", {})
    if w is not None:
        if w >= T["wash_hard"]:
            hard.append(f"lažni volumen (wash score {w}): {_vq_text(vq)}")
        elif w >= T["wash_warn"]:
            flag(15, f"sumnjiv volumen (wash score {w}): {_vq_text(vq)}")
        elif vq.get("trades", 0) >= 50:
            good.append(f"volumen izgleda organski ({vq['wallets']} walleta u {vq['trades']} tradeova)")

    m = r.get("market", {})
    if m:
        liq = m.get("liquidity") or 0
        if liq < T["min_liquidity_usd"]:
            hard.append(f"likvidnost samo ${liq:,.0f}")
        if liq and (m.get("vol_24h") or 0) / liq > 50:
            flag(5, f"volumen 24h je {m['vol_24h'] / liq:.0f}x likvidnost")

    sm = r.get("smart_wallets", [])
    if sm:
        s += min(15, 5 * len(sm))
        good.append(f"{len(sm)} smart walleta među ranim kupcima / holderima")

    s = max(0, min(100, round(s)))
    verdict = "ODBAČEN" if hard else "VISOK RIZIK" if s < 50 else "OPREZ" if s < 75 else "PROLAZI"
    return {"verdict": verdict, "score": None if hard else s, "hard_fails": hard, "flags": flags, "positives": good}


def _vq_text(vq):
    return (f"{vq.get('round_trip_volume_pct')}% volumena kupuje i prodaje isti wallet, top 5 walleta "
            f"{vq.get('top5_volume_pct')}%, {vq.get('trades_per_wallet')} tradeova po walletu")
