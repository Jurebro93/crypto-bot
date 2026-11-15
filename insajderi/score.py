"""Per owner group (chain.owners: same-owner wallets merged) across the events: did they BUY before t0 and SELL into
the jump, on how many tokens, ahead of how many distinct callers / crews, with what lift against chance, lead time
and realized PnL; and what they are:

  insajder     >= min_tokens events bought before AND sold into, >= 2 of them call events, ahead of >= min_callers
               distinct callers or with lift >= min_lift on one caller, median lead >= min_lead_min minutes;
               CONFIRMED when the older 2/3 of the covered events already select it and the newer 1/3 add >= min_confirm
               more such events (out of sample by time, as kol/precall does)
  bot_snajper  out: a bot by the rate rules / wallets.db labels / chainwatch.too_busy, a sniper (most early buys within
               sniper_secs of the token's first trade, or kol/insiders.profile), or it bought early into
               >= busy_events_share of all covered events (buys everything: no information)
  relayer      out: a fee payer for >= relayer_min different owners
  kandidat     2+ such events; promatra: one

Lift: n_wh / (n_w x n_h / U): U covered call events, n_w the owner's call events bought early, n_h caller h's, n_wh
those where the owner bought before h's call (kol/precall.lift). Everything here takes `as_of`: only events whose
window ended before it count, so the walk-forward (copy.py) never looks ahead.
"""
import json
import statistics
from collections import Counter, defaultdict

from insajderi import store

CLS_HR = {"insajder": "insajder", "bot_snajper": "bot / snajper", "relayer": "relayer", "kandidat": "kandidat",
          "promatra": "promatra se"}
OUT = {"bot_snajper", "relayer"}


def lift(n_wh, n_w, n_h, u):
    exp = n_w * n_h / u if u else 0
    return (round(n_wh / exp, 2) if exp else None), round(exp, 3)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def load_parts(con):
    """[(eid, wallet, owner, buy_ts, sol_in, n_sells, sol_out, first_sell_ts, bought_before, sold_into, lead_s)]."""
    return store.q(con, "SELECT eid, wallet, owner, buy_ts, sol_in, n_sells, sol_out, first_sell_ts, bought_before, "
                        "sold_into, lead_s FROM i2_part")


def first_trades(p, toks):
    """{token: ts of its first trade} (kol.db tokens.created_ts, early.db group_fetched.first_ts, hype live_launches)."""
    out = {}
    toks = list(toks)

    def put(t, ts):
        if ts and (t not in out or ts < out[t]):
            out[t] = int(ts)
    for db, sql in (("kol_db", "SELECT token, created_ts FROM tokens WHERE created_ts > 0 AND token IN ({})"),
                    ("early_db", "SELECT mint, first_ts FROM group_fetched WHERE mint IN ({})"),
                    ("hype_db", "SELECT mint, ts FROM live_launches WHERE pool != 'migration' AND mint IN ({})")):
        con = store.ro(p.get(db))
        for i in range(0, len(toks), 400):
            ch = toks[i:i + 400]
            for t, ts in store.q(con, sql.format(",".join("?" * len(ch))), ch):
                put(t, ts)
        if con is not None:
            con.close()
    return out


def bots(con, p, c, cand, since):
    """Bots among `cand` (rate rules on our trades and early.db / hype.db, wallets.db labels, chainwatch.too_busy)."""
    from kol import groupdisc as gd
    if not cand:
        return set()
    out = {w for (w,) in store.q(con, "SELECT DISTINCT wallet FROM i2_trades WHERE ts >= ? GROUP BY wallet, ts / 60 "
                                      "HAVING COUNT(*) > ?", (since, int(c["bot_tx_min"])))}
    out |= {w for (w,) in store.q(con, "SELECT DISTINCT wallet FROM i2_trades WHERE ts >= ? AND slot IS NOT NULL GROUP BY "
                                       "wallet, mint, slot HAVING COUNT(DISTINCT side) > 1", (since,))}
    ec = store.ro(p.get("early_db"))
    if ec is not None:
        out |= gd.bots_sql(ec, store.ro(p.get("hype_db")), since, {"bot_tx_min": int(c["bot_tx_min"])})
        ec.close()
    out &= cand
    out |= gd.bots([], labels=gd._labels(p.get("wallet_db"), cand))
    try:
        from kol import chainwatch
        out |= chainwatch.too_busy(cand, p.get("wallet_db"))
    except Exception:  # noqa: BLE001
        pass
    return out & cand


def classify(parts, events, as_of, c, bad=frozenset(), first_trade=None):
    """{owner: stats} from `parts` over the events whose window ended before as_of (pure). bad: wallets that are bots
    (score.bots); first_trade: {token: ts}."""
    ev = {e["eid"]: e for e in events if e["win_end"] < as_of}
    covered = {eid for eid in ev if ev[eid].get("n_part")} or set(ev)
    calls = [eid for eid in covered if ev[eid]["kind"] == "call"]
    order = sorted(covered, key=lambda x: ev[x]["t0"])
    cut_t = ev[order[int(len(order) * 2 / 3)]]["t0"] if len(order) >= 3 else None
    u_calls = len(calls)
    n_h = Counter(h for eid in calls for h in (ev[eid].get("callers") or {}))
    by = defaultdict(list)
    for r in parts:
        if r[0] in covered:
            by[r[2] or r[1]].append(r)
    first_trade = first_trade or {}
    n_cov = len(covered)
    out = {}
    for owner, rows in by.items():
        members = sorted({r[1] for r in rows})
        early = {r[0]: r for r in rows if r[8]}
        hit_ids = sorted({r[0] for r in rows if r[8]} & {r[0] for r in rows if r[9]}, key=lambda x: ev[x]["t0"])
        call_hits = [eid for eid in hit_ids if ev[eid]["kind"] == "call"]
        front = Counter()
        for eid in call_hits:
            bts = min(r[3] for r in rows if r[0] == eid and r[8])
            for h, ts in (ev[eid].get("callers") or {}).items():
                if bts < ts:
                    front[h] += 1
        n_w = sum(1 for eid in early if ev[eid]["kind"] == "call")
        best_lift, best_h = None, None
        for h, n in front.items():
            if n < 2:
                continue
            lf, _exp = lift(n, n_w, n_h.get(h, n), u_calls)
            if lf is not None and (best_lift is None or lf > best_lift):
                best_lift, best_h = lf, h
        leads = [min(r[10] for r in rows if r[0] == eid and r[8] and r[10] is not None) / 60
                 for eid in hit_ids if any(r[0] == eid and r[8] and r[10] is not None for r in rows)]
        med_lead = _med(leads)
        pnl = [sum((r[6] or 0) for r in rows if r[0] == eid) - sum((r[4] or 0) for r in rows if r[0] == eid)
               for eid in hit_ids]
        snipe = [early[eid][3] - first_trade[ev[eid]["token"]] for eid in early if ev[eid]["token"] in first_trade]
        sniper = len(snipe) >= 2 and sum(1 for x in snipe if 0 <= x <= c["sniper_secs"]) / len(snipe) >= c["sniper_share"]
        busy = n_cov >= 10 and len(early) / n_cov >= c["busy_events_share"]
        st = {"owner": owner, "members": members, "n_early": len(early), "n_hits": len(hit_ids),
              "n_call_hits": len(call_hits), "n_callers": len(front), "callers": dict(front.most_common(8)),
              "lift": best_lift, "lift_caller": best_h, "med_lead_min": round(med_lead, 1) if med_lead is not None else None,
              "pnl_sol": round(sum(pnl), 4) if pnl else None,
              "tokens": [ev[eid]["token"] for eid in hit_ids], "symbols": [ev[eid].get("symbol") for eid in hit_ids],
              "crews": sorted({ev[eid]["crew"] for eid in hit_ids if ev[eid].get("crew")}),
              "first_ts": min((ev[eid]["t0"] for eid in early), default=None), "why": None, "confirmed": False}
        sel = [eid for eid in hit_ids if cut_t is None or ev[eid]["t0"] < cut_t]
        conf = [eid for eid in hit_ids if cut_t is not None and ev[eid]["t0"] >= cut_t]
        if owner.startswith("relayer:"):
            st["cls"], st["why"] = "relayer", "plaća naknade za mnogo drugih vlasnika"
        elif set(members) & set(bad):
            st["cls"], st["why"] = "bot_snajper", "bot (brzina tradeova, oznaka ili previše tradeova dnevno)"
        elif sniper:
            st["cls"], st["why"] = "bot_snajper", f"snajper (kupuje u prvih {c['sniper_secs']} s lansiranja)"
        elif busy:
            st["cls"], st["why"] = "bot_snajper", f"kupio rano u {len(early)} od {n_cov} događaja (kupuje sve)"
        elif (len(hit_ids) >= c["min_tokens"] and len(call_hits) >= 2
              and (len(front) >= c["min_callers"] or (best_lift or 0) >= c["min_lift"])
              and (med_lead is None or med_lead >= c["min_lead_min"])):
            st["cls"] = "insajder"
            sel_ok = len(sel) >= c["min_tokens"]
            st["confirmed"] = bool(sel_ok and len(conf) >= c["min_confirm"])
            st["why"] = (f"kupio prije i prodao u skok na {len(hit_ids)} tokena, ispred {len(front)} callera"
                         + ("" if st["confirmed"] else f" (potvrda: {len(sel)} u starijem, {len(conf)} u novijem dijelu)"))
        elif len(hit_ids) >= 2:
            st["cls"] = "kandidat"
        else:
            st["cls"] = "promatra"
        st["score"] = round(len(hit_ids) + 0.5 * (len(early) - len(hit_ids)) + min(best_lift or 0, 10) / 5
                            + 0.5 * len(front) + (3 if st["confirmed"] else 0) - (5 if st["cls"] in OUT else 0), 2)
        out[owner] = st
    return out


def confirmed(stats):
    """{owner: members} of the confirmed insiders."""
    return {o: s["members"] for o, s in stats.items() if s["cls"] == "insajder" and s["confirmed"]}


def save(con, stats, now):
    old = {o: ts for o, ts in store.q(con, "SELECT owner, confirmed_ts FROM i2_groups")}
    con.execute("DELETE FROM i2_groups")
    rows = []
    for o, s in stats.items():
        if s["n_early"] + s["n_hits"] < 2 and s["cls"] == "promatra":
            continue   # one sighting: not stored (the table stays small)
        cts = old.get(o) or (int(now) if s["confirmed"] else None)
        rows.append((o, json.dumps(s["members"]), len(s["members"]), s["cls"], s["why"], s["n_hits"], s["n_early"],
                     s["n_callers"], s["lift"], s["med_lead_min"], s["pnl_sol"],
                     json.dumps(list(zip(s["tokens"], s["symbols"]))[:30]), json.dumps(s["callers"]),
                     json.dumps(s["crews"]), s["first_ts"], cts if s["confirmed"] else None, s["score"], int(now)))
    con.executemany("INSERT INTO i2_groups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


def watched(con, limit=None):
    """[(owner, [members])] of the confirmed insiders, best first (the demo and the webhook follow these)."""
    out = []
    for o, m in store.q(con, "SELECT owner, members FROM i2_groups WHERE cls = 'insajder' AND confirmed_ts IS NOT NULL "
                             "ORDER BY score DESC"):
        try:
            out.append((o, json.loads(m)))
        except ValueError:
            continue
    return out[:limit] if limit else out
