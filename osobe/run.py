"""The night pass (run_osobe.py noc, run_sched.py job "osobe", 03:20 Zagreb under the heavy-job lock): read what the
other jobs stored, build links, persons, profiles, the X links and the group call power, write osobe.db.

Reads only (no API call, no credits). Bounded: MAX_CANDIDATES wallets, LOOKBACK_D days of trades.
"""
import time

from osobe import dokazi, grupe, profil, store, xveza

PREFIX = "osobe: "


def build_links(p, now, log=print):
    cands, why = dokazi.candidates(p)
    cset = set(cands)
    tr = dokazi.trades(p, cands, now)
    xf = dokazi.transfers(p, now)
    hubs = dokazi.hubs_of([(a, b) for a, b, *_r in xf], dokazi.exchanges(p))
    links = dokazi.Links()
    relay = dokazi.add_payers(links, tr)
    hubs |= relay
    fund = dokazi.funders(p, cands)
    fan = {}
    for w, fs in fund.items():
        for f in fs:
            fan[f] = fan.get(f, 0) + 1
    hubs |= {f for f, n in fan.items() if n > dokazi.HUB_MIN}
    dokazi.add_funding(links, fund, xf, hubs)
    dokazi.add_sweeps(links, xf, hubs, cset)
    busy = dokazi.add_cobuys(links, tr, cset)
    owners, groups = dokazi.insider_owners(p)
    dokazi.add_groups(links, owners, groups, hubs)
    log(f"{PREFIX}{len(cands)} novčanika, {len(tr)} kupnji/prodaja, {len(xf)} prijenosa, {len(links.ev)} parova, "
        f"{len(hubs)} čvorišta, {len(busy)} botova izbačeno")
    return cands, why, tr, links


def run(p=None, now=None, log=print, con=None):
    p = p or store.paths()
    now = int(now or time.time())
    t0 = time.monotonic()
    own = con is None
    con = con or store.connect(p.get("osobe_db"))
    try:
        cands, why, tr, links = build_links(p, now, log)
        items = list(links.items())
        comps = profil.cluster(items)
        old = dict(store.q(con, "SELECT wallet, pid FROM os_member"))
        persons = profil.person_ids(comps, old)
        members = set().union(*(ms for _p, ms, _c in persons)) if persons else set()
        # wallets a person brought in (a funder, a sweep target) that are no candidates: their trades too
        extra = members - set(cands)
        if extra:
            tr = tr + dokazi.trades(p, extra, now)
        pnl_rows = dokazi.wallet_rows(p, members)
        syms = profil.symbols(p, {r[1] for r in tr if r[0] in members})
        ev_by = {}
        for (a, b), c, ev in items:
            if c >= dokazi.LINK_MIN:
                ev_by.setdefault(a, []).append(ev)
                ev_by.setdefault(b, []).append(ev)
        out = []
        for pid, ms, cm in persons:
            evs = [e for w in ms for e in ev_by.get(w, [])]
            out.append((pid, ms, cm, profil.profile(p, ms, cm, tr, pnl_rows, syms, evs)))
        kept = [(k, c, ev) for k, c, ev in items if c >= dokazi.LINK_MIN and k[0] in members]
        profil.save(con, out, kept, now)
        handles, public = xveza.tracked(p)
        cmap = xveza.calls(p, handles)
        xl = xveza.evaluate({pid: ms for pid, ms, _c in persons}, tr, cmap, handles, public, xveza.ik_groups(p))
        xveza.save(con, xl, now)
        books = {pid: xveza._book(tr, ms) for pid, ms, _c in persons}
        gr = grupe.run(p, handles, books)
        grupe.save(con, gr, now)
        summ = {"ts": now, "candidates": len(cands), "persons": len(out), "wallets": len(members),
                "links": len(kept), "xlinks": sum(len(v) for v in xl.values()),
                "xlinks_shown": sum(1 for v in xl.values() for _h, pr, _e in v if pr >= xveza.SHOW_MIN),
                "group_events": gr.get("events", 0), "seconds": round(time.monotonic() - t0, 1)}
        store.kv(con, "zadnji", summ)
        con.commit()
        log(f"{PREFIX}{summ['persons']} osoba ({summ['wallets']} novčanika), {summ['xlinks_shown']} mogućih veza s X "
            f"računima iznad praga, {summ['group_events']} događaja poziva, {summ['seconds']} s")
        return summ
    finally:
        if own:
            con.close()


def summary(path=None):
    con = store.ro(path or store.db_path())
    if con is None:
        return None
    try:
        return store.kv(con, "zadnji")
    finally:
        con.close()
