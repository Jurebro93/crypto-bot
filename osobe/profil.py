"""Persons from wallet links, and each person's profile (27.11.).

cluster()   union of links with confidence >= dokazi.LINK_MIN; a component bigger than MAX_PERSON is cut to its strong
            links only, and dropped when still too big (more wallets than one person plausibly runs: a hub we missed).
            A person keeps its id between nights: a component takes the old id that most of its wallets had.
profile()   wallets, combined PnL (wallets/pnl.py over the members' parsed trades, open book at unknown price, so only
            realized is counted), tokens and themes, timing against pumps (insajderi i2_part: bought before, sold into),
            bundle behaviour, KOL insider rows, style, and a copyability placeholder.
"""
import hashlib
import json
import statistics
from collections import Counter, defaultdict

from osobe import dokazi, nadimak, store

MAX_PERSON = 40
STRONG = 0.75


def _components(pairs):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    out = defaultdict(set)
    for x in list(parent):
        out[find(x)].add(x)
    return list(out.values())


def cluster(link_items, min_conf=dokazi.LINK_MIN, max_size=MAX_PERSON):
    """link_items: [((a, b), conf, evidence)] -> [(members set, {wallet: best link conf})], persons of 2+ wallets."""
    strong = [(k, c) for k, c, _e in link_items if c >= min_conf]
    best = defaultdict(float)
    for (a, b), c in strong:
        best[a] = max(best[a], c)
        best[b] = max(best[b], c)
    out = []
    for comp in _components([k for k, _c in strong]):
        if len(comp) > max_size:
            sub = [k for k, c in strong if c >= STRONG and k[0] in comp]
            for sc in _components(sub):
                if 2 <= len(sc) <= max_size:
                    out.append(sc)
            continue
        if len(comp) >= 2:
            out.append(comp)
    return [(c, {w: best[w] for w in c}) for c in out]


def person_ids(comps, old_member):
    """[(members, conf map)] -> [(pid, members, conf map)]; an old id is kept when it was the most common old id of
    the members (and no other component took it), else a new id from the smallest member."""
    used, out = set(), []
    for ms, cm in sorted(comps, key=lambda x: -len(x[0])):
        votes = Counter(old_member[w] for w in ms if w in old_member)
        pid = next((o for o, _n in votes.most_common() if o not in used), None)
        if pid is None:
            pid = "o" + hashlib.sha1(min(ms).encode()).hexdigest()[:10]
            while pid in used:
                pid = "o" + hashlib.sha1((pid + "x").encode()).hexdigest()[:10]
        used.add(pid)
        out.append((pid, ms, cm))
    return out


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pnl_of(rows):
    """Combined realized PnL of the members' wallets.db rows (one book: a transfer between own wallets is a move)."""
    from wallets import pnl
    if not rows:
        return None
    pos = pnl.positions(rows, prices={})
    s = pnl.score(pos, rows)
    return {"realized_sol": s["realized_sol"], "closed": s["closed"], "positions": s["positions"],
            "win_rate": s["win_rate"], "median_hold_min": s["median_hold_min"], "style": s["style"],
            "median_buy_sol": s["median_buy_sol"], "big_wins": s["big_wins"]}


def timing(p, members):
    """Against the pumps the insider tool measured: events where a member bought before t0 / sold into the jump,
    the median lead (minutes), and how many were big pumps (tier pumpa15)."""
    ic = store.ro(p.get("insajderi_db"))
    ms = list(members)
    rows = store.q(ic, f"SELECT p.eid, p.bought_before, p.sold_into, p.lead_s, e.tier, e.token, e.symbol FROM i2_part p "
                       f"LEFT JOIN i2_events e ON e.eid = p.eid WHERE p.wallet IN ({dokazi._in(ms)})", ms) if ms else []
    if not rows and ms:   # an older insajderi.db without the tier column
        rows = [(*r[:4], None, None, None) for r in store.q(
            ic, f"SELECT eid, bought_before, sold_into, lead_s FROM i2_part WHERE wallet IN ({dokazi._in(ms)})", ms)]
    if ic is not None:
        ic.close()
    ev = {}
    for eid, bb, si, lead, tier, tok, sym in rows:
        e = ev.setdefault(eid, {"bb": 0, "si": 0, "lead": None, "tier": tier, "token": tok, "symbol": sym})
        e["bb"] |= int(bb or 0)
        e["si"] |= int(si or 0)
        if bb and lead is not None:
            e["lead"] = max(e["lead"] or 0, lead)
    pre = [e for e in ev.values() if e["bb"]]
    return {"events": len(ev), "pre_pump": len(pre), "sold_into": sum(1 for e in pre if e["si"]),
            "big_pumps": sum(1 for e in pre if e["tier"] == "pumpa15"),
            "median_lead_min": round(_med([e["lead"] for e in pre]) / 60, 1) if _med([e["lead"] for e in pre]) else None,
            "examples": [{"token": e["token"], "symbol": e["symbol"], "sold_into": bool(e["si"])}
                         for e in sorted(pre, key=lambda e: -(e["lead"] or 0))[:5] if e["token"]]}


def bundles(p, members):
    ic = store.ro(p.get("insajderi_db"))
    ms = set(members)
    n, pumps = 0, 0
    for raw, np_ in store.q(ic, "SELECT members, n_pumps FROM i2_bundle"):
        if ms & set(dokazi._members(raw)):
            n += 1
            pumps += np_ or 0
    if ic is not None:
        ic.close()
    ec = store.ro(p.get("early_db"))
    ml = list(ms)
    pre_b = store.q(ec, f"SELECT COUNT(*) FROM preshill_buys WHERE bundle = 1 AND wallet IN ({dokazi._in(ml)})", ml) \
        if ml else []
    if ec is not None:
        ec.close()
    return {"bundles": n, "bundle_pumps": pumps, "launch_bundle_buys": (pre_b[0][0] if pre_b else 0) or 0}


def kol_insider(p, members):
    kc = store.ro(p.get("kol_db"))
    ml = list(members)
    r = store.q(kc, f"SELECT COUNT(*), COUNT(DISTINCT token) FROM insiders WHERE wallet IN ({dokazi._in(ml)})", ml) \
        if ml else []
    if kc is not None:
        kc.close()
    return {"kol_front_runs": (r[0][1] if r else 0) or 0}


def symbols(p, mints):
    """{mint: (symbol, name)} from kol.db tokens and insajderi i2_events (what we already know)."""
    out = {}
    ml = list(mints)
    kc = store.ro(p.get("kol_db"))
    for ch in dokazi._chunks(ml):
        for m, s, n in store.q(kc, f"SELECT token, symbol, name FROM tokens WHERE token IN ({dokazi._in(ch)})", ch):
            out[m] = (s, n)
    if kc is not None:
        kc.close()
    ic = store.ro(p.get("insajderi_db"))
    for ch in dokazi._chunks([m for m in ml if m not in out]):
        for m, s in store.q(ic, f"SELECT token, symbol FROM i2_events WHERE token IN ({dokazi._in(ch)}) "
                                "AND symbol IS NOT NULL", ch):
            out.setdefault(m, (s, None))
    if ic is not None:
        ic.close()
    return out


def tokens_of(trade_rows, syms):
    """Top tokens by buys and the dominant theme."""
    buys = Counter(r[1] for r in trade_rows if r[4] == "buy")
    themes = Counter()
    for m, n in buys.items():
        s, nm = syms.get(m, (None, None))
        t = nadimak.theme_of(s) or nadimak.theme_of(nm)
        if t:
            themes[t] += 1
    top = [{"mint": m, "symbol": syms.get(m, (None,))[0], "buys": n} for m, n in buys.most_common(8)]
    n_tok = len(buys)
    theme = None
    if themes:
        t, k = themes.most_common(1)[0]
        if k >= 2 and k >= 0.25 * n_tok:
            theme = t
    return {"n_tokens": n_tok, "top": top, "theme": theme, "themes": dict(themes.most_common(4))}


def traits(prof):
    """The few numbers the nickname and the reasons read."""
    pn = prof.get("pnl") or {}
    return {"n_wallets": prof["n_wallets"], "pre_pump": prof["timing"]["pre_pump"],
            "sold_into": prof["timing"]["sold_into"], "bundles": prof["bundle"]["bundles"],
            "pnl_sol": pn.get("realized_sol"), "style": pn.get("style"),
            "median_hold_min": pn.get("median_hold_min"), "theme": prof["tokens"]["theme"]}


def reasons(prof):
    """2-3 plain sentences: what this person is notable for (results only, no method)."""
    t, b, pn, tk = prof["timing"], prof["bundle"], prof.get("pnl") or {}, prof["tokens"]
    out = []
    if t["pre_pump"]:
        s = f"Kupio prije {t['pre_pump']} pumpi"
        if t["sold_into"]:
            s += f", na {t['sold_into']} prodao u rast"
        if t["median_lead_min"]:
            s += f"; obično oko {_mins(t['median_lead_min'])} prije početka"
        out.append(s + ".")
    if b["bundles"] or b["launch_bundle_buys"]:
        out.append(f"Kupuje u snopu s vlastitim novčanicima na lansiranju ({b['bundles'] or b['launch_bundle_buys']}"
                   f"{' puta' if b['bundles'] else ' kupnji'}).")
    if prof["n_wallets"] >= 3:
        out.append(f"Koristi {prof['n_wallets']} povezanih novčanika.")
    if pn.get("realized_sol") is not None and pn.get("closed"):
        v = f"{pn['realized_sol']:+.2f}".replace(".", ",").replace("-", "−")
        out.append(f"Ostvareno {v} SOL na {pn['closed']} zatvorenih pozicija.")
    if tk["theme"]:
        out.append(f"Najčešće trguje {nadimak.THEMES[tk['theme']].split(' ', 1)[1]}.")
    if prof["kol"]["kol_front_runs"]:
        out.append(f"Kupio prije poziva influencera na {prof['kol']['kol_front_runs']} tokena.")
    return out[:3] or ["Novčanici su povezani, ali o ponašanju još nema dovoljno podataka."]


def _mins(m):
    if m >= 1440:
        return f"{m / 1440:.0f} d"
    if m >= 60:
        return f"{m / 60:.0f} h"
    return f"{m:.0f} min"


def profile(p, members, cm, trade_rows, pnl_rows, syms, link_ev):
    ms = sorted(members)
    rows = [r for w in ms for r in pnl_rows.get(w, [])]
    tr = [r for r in trade_rows if r[0] in members]
    ts = [r[2] for r in tr] + [r["ts"] for r in rows]
    kinds = Counter()
    for e in link_ev:
        for k in e:
            kinds[k] += 1
    prof = {"wallets": [{"wallet": w, "conf": round(cm.get(w, 1.0), 2)} for w in ms], "n_wallets": len(ms),
            "pnl": pnl_of(rows), "tokens": tokens_of(tr, syms), "timing": timing(p, ms), "bundle": bundles(p, ms),
            "kol": kol_insider(p, ms), "evidence": dict(kinds.most_common()),
            "first_ts": min(ts) if ts else None, "last_ts": max(ts) if ts else None, "n_trades": len(tr),
            "copy": {"status": "još se ne mjeri", "note": "Kopiranje osobe mjerit će se tek kad test izvan uzorka bude "
                                                          "imao dovoljno primjera."}}
    prof["traits"] = traits(prof)
    prof["reasons"] = reasons(prof)
    return prof


def save(con, persons, links_kept, now):
    """persons: [(pid, members, conf map, profile)]; names kept from os_names, new ones invented."""
    names = dict(store.q(con, "SELECT pid, name FROM os_names"))
    taken = set(names.values())
    con.execute("DELETE FROM os_persons")
    con.execute("DELETE FROM os_member")
    con.execute("DELETE FROM os_links")
    for pid, ms, cm, prof in persons:
        name = names.get(pid)
        if not name:
            name = nadimak.make(pid, prof["traits"], taken)
            taken.add(name)
            names[pid] = name
            con.execute("INSERT OR REPLACE INTO os_names VALUES (?,?,?)", (pid, name, int(now)))
        confs = sorted(cm.values())
        conf = round(statistics.median(confs), 3) if confs else None
        pn = (prof.get("pnl") or {}).get("realized_sol")
        con.execute("INSERT INTO os_persons VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, json.dumps(sorted(ms)), len(ms), conf, name, json.dumps(prof["traits"]),
                     json.dumps(prof, ensure_ascii=False), pn, prof["first_ts"], prof["last_ts"], int(now)))
        con.executemany("INSERT OR REPLACE INTO os_member VALUES (?,?,?)",
                        [(w, pid, round(cm.get(w, 1.0), 3)) for w in ms])
    con.executemany("INSERT OR REPLACE INTO os_links VALUES (?,?,?,?,?,?)",
                    [(a, b, c, json.dumps(sorted(ev)), json.dumps(ev, ensure_ascii=False), int(now))
                     for (a, b), c, ev in links_kept])
