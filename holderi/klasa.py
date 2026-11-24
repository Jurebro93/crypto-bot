"""Holder classification of one midcap's top holders and the metrics for that token range (pure: no network).

Classes, first match wins:
  lp        a pool / AMM / locker / launchpad account (RugCheck knownAccounts except the creator, its markets' accounts,
            the DexScreener pool), or an owner that is a program (not a system wallet)
  burn      the incinerator / system address
  exchange  a known exchange wallet (holderi/burze registry, with its confidence) or a heuristic one: a RugCheck name of
            an exchange, an owner among the top holders of >= cross_min midcaps (custodian)
  team      the creator / deployer, an owner the creator funded, wallets.db label dev
  insider   RugCheck's insider flag, wallets.db label insider / bundler, or one of >= 2 top holders with the same funder
            (a cluster) or bought in the launch's first minutes (early, when known)
  whale     >= whale_pct (1 %) of supply
  normal    the rest
Metrics (shares in % of supply): by class; insider_ex = team + insider (exchanges and LP never counted: the owner's
"holders of large shares are often EXCHANGES"); hhi = sum of share^2 of the non-pool, non-burn holders (0-10000;
>= 1500 concentrated, >= 2500 very); top10_ex = the top 10 without pools, burn and exchanges; per exchange its share.
"""
CLASSES = ("lp", "burn", "exchange", "team", "insider", "whale", "normal")
POOL_TYPES = {"AMM", "LOCKER", "STAKING", "BRIDGE", "LAUNCHPAD", "PROGRAM", "DEX", "VAULT"}


def classify(holders, *, pools=(), creator=None, reg=None, cross=None, labels=None, funders=None, early=(),
             known=None, burn=None, whale_pct=1.0, cross_min=5):
    """[{owner, acct, amount, pct, cls, why, exchange?, conf?}] of holders [{owner, acct, amount, pct, insider?}]."""
    from holderi import burze
    reg, cross, labels, funders, known = reg or {}, cross or {}, labels or {}, funders or {}, known or {}
    burn = burze.BURN if burn is None else burn
    pools = set(pools or ())
    early = set(early or ())
    fcount = {}
    for h in holders:
        f = funders.get(h.get("owner"))
        if f:
            fcount[f] = fcount.get(f, 0) + 1
    out = []
    for h in holders:
        o, a = h.get("owner"), h.get("acct")
        pct = float(h.get("pct") or 0)
        kn = known.get(o) or known.get(a) or {}
        lab = set(labels.get(o) or ())
        r = {"owner": o, "acct": a, "amount": h.get("amount"), "pct": round(pct, 4)}
        kname = kn.get("name") or ""
        if o in burn or a in burn:
            r.update(cls="burn", why="burn adresa")
        elif (o in pools or a in pools or h.get("program_owner")
              or (kn and str(kn.get("type") or "").upper() not in ("CREATOR", "") and not burze.known_name(kname))):
            r.update(cls="lp", why="pool / program" + (f" ({kname})" if kname else ""))
        elif o in reg:
            e = reg[o]
            r.update(cls="exchange", exchange=e["exchange"], conf=e["confidence"],
                     why=f"burza {burze.NAMES.get(e['exchange'], e['exchange'])} ({e['status']}, {e['confidence']:.2f})")
        elif burze.known_name(kname):
            ex = burze.known_name(kname)
            r.update(cls="exchange", exchange=ex, conf=0.6, why=f"RugCheck naziv „{kname}“ (heuristika)")
        elif cross.get(o, 0) >= cross_min:
            r.update(cls="exchange", exchange="nepoznata", conf=0.5,
                     why=f"top holder {cross[o]} midcapova (skrbnik / burza, heuristika)")
        elif "cex" in lab:
            r.update(cls="exchange", exchange="nepoznata", conf=0.5, why="wallets.db oznaka cex")
        elif creator and (o == creator or funders.get(o) == creator or str(kn.get("type") or "").upper() == "CREATOR"):
            r.update(cls="team", why="kreator" if o == creator else "financirao ga kreator")
        elif "dev" in lab:
            r.update(cls="team", why="wallets.db oznaka dev")
        elif h.get("insider"):
            r.update(cls="insider", why="RugCheck insider")
        elif lab & {"insider", "bundler", "rotation_dev"}:
            r.update(cls="insider", why="wallets.db oznaka " + ", ".join(sorted(lab & {"insider", "bundler", "rotation_dev"})))
        elif funders.get(o) and fcount.get(funders[o], 0) >= 2:
            r.update(cls="insider", why=f"isti financijer kao još {fcount[funders[o]] - 1} top holdera")
        elif o in early:
            r.update(cls="insider", why="kupio u prvim minutama")
        elif pct >= whale_pct:
            r.update(cls="whale", why=f"kit ({pct:.1f} %)")
        else:
            r.update(cls="normal", why="")
        out.append(r)
    return out


def metrics(rows):
    """The class shares and metrics of classified rows (see the module text)."""
    sh = {c: 0.0 for c in CLASSES}
    per_ex = {}
    for r in rows:
        sh[r["cls"]] += r["pct"]
        if r["cls"] == "exchange":
            per_ex[r.get("exchange") or "nepoznata"] = round(per_ex.get(r.get("exchange") or "nepoznata", 0) + r["pct"], 3)
    real = [r["pct"] for r in rows if r["cls"] not in ("lp", "burn")]
    top_ex = sorted((r["pct"] for r in rows if r["cls"] not in ("lp", "burn", "exchange")), reverse=True)[:10]
    return {"shares": {c: round(v, 3) for c, v in sh.items()},
            "insider_ex": round(sh["team"] + sh["insider"], 3),
            "hhi": round(sum(p * p for p in real), 1),
            "top10_ex": round(sum(top_ex), 3), "exchanges": per_ex, "n": len(rows)}


def diff(prev_rows, rows, min_pct=0.5):
    """Changes between two snapshots of the same token: {"out": [(owner, cls, -pct)], "in": [(owner, cls, +pct)],
    "new": [owners new in the top], "gone": [...]} for changes of >= min_pct of supply (owners matched by address)."""
    a = {r["owner"]: r for r in prev_rows or [] if r.get("owner")}
    b = {r["owner"]: r for r in rows or [] if r.get("owner")}
    out, inn = [], []
    for o in set(a) | set(b):
        pa = (a.get(o) or {}).get("pct") or 0.0
        pb = (b.get(o) or {}).get("pct") or 0.0
        cls = (b.get(o) or a.get(o) or {}).get("cls")
        d = pb - pa
        if d <= -min_pct:
            out.append((o, cls, round(d, 3)))
        elif d >= min_pct:
            inn.append((o, cls, round(d, 3)))
    out.sort(key=lambda x: x[2])
    inn.sort(key=lambda x: -x[2])
    return {"out": out, "in": inn, "new": sorted(set(b) - set(a)), "gone": sorted(set(a) - set(b))}


def from_rugcheck(rc, extra_pools=()):
    """(holders [{owner, acct, amount, pct, insider}], pools set, creator, known {addr: {name, type}}, supply) of a
    RugCheck report (free; the midcap collector reads it daily anyway)."""
    if not isinstance(rc, dict):
        return [], set(), None, {}, None
    known = {a: {"name": (v or {}).get("name"), "type": (v or {}).get("type")} for a, v in (rc.get("knownAccounts") or {}).items()}
    pools = {a for a, v in known.items() if str(v.get("type") or "").upper() in POOL_TYPES
             or (str(v.get("type") or "").upper() not in ("CREATOR", "") and not _exname(v.get("name")))}
    pools |= set(extra_pools or ())
    for m in rc.get("markets") or []:
        pools.add(m.get("pubkey"))
        for side in ("liquidityAAccount", "liquidityBAccount"):
            pools.add((m.get(side) or {}).get("owner"))
            pools.add(m.get(side.replace("Account", "")))
    pools.discard(None)
    hs = []
    for h in rc.get("topHolders") or []:
        try:
            pct = float(h.get("pct") or 0)
        except (TypeError, ValueError):
            continue
        hs.append({"owner": h.get("owner") or h.get("address"), "acct": h.get("address"), "amount": h.get("uiAmount"),
                   "pct": pct, "insider": bool(h.get("insider"))})
    tok = rc.get("token") or {}
    supply = None
    try:
        supply = float(tok.get("supply") or 0) / 10 ** int(tok.get("decimals") or 0) or None
    except (TypeError, ValueError):
        supply = None
    return hs, pools, rc.get("creator"), known, supply


def _exname(name):
    from holderi import burze
    return burze.known_name(name)
