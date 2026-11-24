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
import sqlite3
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


PART_COLS = "eid, wallet, owner, buy_ts, sol_in, n_sells, sol_out, first_sell_ts, bought_before, sold_into, lead_s"
# the owner group of a row, as `r[2] or r[1]` in Python (an empty owner falls back to the wallet too)
OWNER_KEY = "(CASE WHEN owner IS NULL OR owner = '' THEN wallet ELSE owner END)"


def load_parts(con, relevant=False):
    """[(eid, wallet, owner, buy_ts, sol_in, n_sells, sol_out, first_sell_ts, bought_before, sold_into, lead_s)].

    relevant (20.11., production: the full pass was killed at 800 MB RSS; i2_part holds ~1M rows after the deep pump
    reads, almost all of them wallets that only sold into one jump): only the rows of the owner groups that can be
    anything but "promatra" in score.classify / prijepumpe.classify / smart.roles, i.e. EVERY row of an owner that
    bought early (bought_before) in at least one event, of a relayer owner, and of any owner sharing a wallet with
    those. An owner with no early buy anywhere is "promatra" in score.classify (it has no early event: not a sniper,
    not "kupuje sve", never in score.bots' candidates), absent from prijepumpe.classify and smart.roles, and never
    stored (score.save skips promatra with n_early + n_hits < 2); quiet_owners() counts them for the class counts. Same
    row order as the full read (rowid), so every per-owner sum is added in the same order."""
    if not relevant:
        return store.q(con, f"SELECT {PART_COLS} FROM i2_part")
    con.execute("DROP TABLE IF EXISTS temp.i2_rel")
    con.execute("CREATE TEMP TABLE i2_rel (k TEXT PRIMARY KEY)")
    con.execute(f"INSERT OR IGNORE INTO temp.i2_rel SELECT {OWNER_KEY} FROM i2_part WHERE bought_before OR "
                f"owner LIKE 'relayer:%'")
    con.execute(f"INSERT OR IGNORE INTO temp.i2_rel SELECT {OWNER_KEY} FROM i2_part WHERE wallet IN (SELECT wallet "
                f"FROM i2_part WHERE {OWNER_KEY} IN (SELECT k FROM temp.i2_rel))")
    # 20.11. (2): one string object per event id and per wallet / owner (sqlite gives a new one per row; ~200 bytes a
    # row on ~600k rows); the values are the same
    rows, same = [], {}
    try:
        for r in con.execute(f"SELECT {PART_COLS} FROM i2_part WHERE {OWNER_KEY} IN (SELECT k FROM temp.i2_rel) "
                             "ORDER BY rowid"):
            eid, w, o = r[0], r[1], r[2]
            eid = same.setdefault(eid, eid)
            w = same.setdefault(w, w)
            o = w if o == w else same.setdefault(o, o)
            rows.append((eid, w, o) + r[3:])
    except sqlite3.Error:
        rows = []
    con.execute("DROP TABLE temp.i2_rel")
    return rows


def covered_ids(events, as_of):
    """The event ids classify() counts at as_of (its `covered`)."""
    ev = {e["eid"]: e for e in events if e["win_end"] < as_of}
    return {eid for eid in ev if ev[eid].get("n_part")} or set(ev)


def quiet_owners(con, events, as_of, parts):
    """The number of owner groups classify(full i2_part, events, as_of) would hold that are NOT in `parts` (a
    load_parts(relevant=True) read): each of them is "promatra" there (see load_parts)."""
    cov = covered_ids(events, as_of)
    if not cov:
        return 0
    con.execute("DROP TABLE IF EXISTS temp.i2_cov")
    con.execute("CREATE TEMP TABLE i2_cov (eid TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO temp.i2_cov VALUES (?)", [(x,) for x in cov])
    n_all = (store.q(con, f"SELECT COUNT(DISTINCT {OWNER_KEY}) FROM i2_part WHERE eid IN (SELECT eid FROM temp.i2_cov)")
             or [(0,)])[0][0]
    con.execute("DROP TABLE temp.i2_cov")
    mine = {r[2] or r[1] for r in parts if r[0] in cov}
    return max(0, int(n_all or 0) - len(mine))


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


_AGG = []   # [(list, len, aggregate)]: the list itself is held, so its id is never reused while cached
AGG_KEEP = 3   # 20.11. (2): the pass's rows, the walks' subset of them (sharing its entries) and one small list; a small
#               list (a day's few owners) never pushes the big ones out (each rebuild of ~600k rows is ~150 MB, 4 s)


def _agg_get(parts):
    for x in _AGG:
        if x[0] is parts and x[1] == len(parts):
            return x[2]
    return None


def _agg_put(parts, v):
    _AGG.append((parts, len(parts), v))
    while len(_AGG) > AGG_KEEP:
        del _AGG[min(range(len(_AGG) - 1), key=lambda i: _AGG[i][1])]


def aggregate(parts):
    """{owner: {eid: [first buy ts, min lead, bought, sold, sol_in, sol_out, (wallets)]}} in one pass over the rows
    (cached for the same list: the walk-forward classifies the same rows once a day). 20.11. (2): the wallets of an
    (owner, event) are a tuple (a row is one (event, wallet): i2_part's key), ~170 bytes less than a set each."""
    hit = _agg_get(parts)
    if hit is not None:
        return hit
    out = defaultdict(dict)
    for eid, w, owner, bts, sin, _ns, sout, _fs, bb, si, lead in parts:
        a = out[owner or w].get(eid)
        if a is None:
            a = out[owner or w][eid] = [None, None, False, False, 0.0, 0.0, (w,)]
        elif w not in a[6]:
            a[6] = a[6] + (w,)
        if bb:
            a[2] = True
            if bts is not None and (a[0] is None or bts < a[0]):
                a[0] = bts
            if lead is not None and (a[1] is None or lead < a[1]):
                a[1] = lead
        if si:
            a[3] = True
        a[4] += sin or 0
        a[5] += sout or 0
    _agg_put(parts, out)
    return out


def aggregate_subset(sub, parent):
    """Prime aggregate()'s cache for `sub`, a list of EVERY row of some owners of `parent` in parent's order (walkcache.
    multi_parts), from parent's cached aggregate: the same dict (an owner's entry reads only its own rows), without a
    second copy of ~600k rows' aggregate (20.11. (2)). No-op when parent is not the cached list."""
    v = _agg_get(parent)
    if v is None or _agg_get(sub) is not None:
        return
    keys = {r[2] or r[1] for r in sub}
    out = defaultdict(dict)
    for o, by in v.items():
        if o in keys:
            out[o] = by
    _agg_put(sub, out)


def classify(parts, events, as_of, c, bad=frozenset(), first_trade=None, slim=None):
    """{owner: stats} from `parts` over the events whose window ended before as_of (pure). bad: wallets that are bots
    (score.bots); first_trade: {token: ts}.
    slim (20.11. (2), production: ~160k owner groups with an early buy, ~1.3 KB of stats each): "light" -> every owner
    only {"cls", "confirmed", "n_early", "n_hits"} (+ "members" of a confirmed one: confirmed()), for the walk-forwards
    that need the class alone; "store" -> that light form for the owners save() never stores (promatra with
    n_early + n_hits < 2), the full stats for the rest. The class of every owner is the same in every form."""
    ev = {e["eid"]: e for e in events if e["win_end"] < as_of}
    covered = covered_ids(events, as_of)
    calls = [eid for eid in covered if ev[eid]["kind"] == "call"]
    order = sorted(covered, key=lambda x: ev[x]["t0"])
    cut_t = ev[order[int(len(order) * 2 / 3)]]["t0"] if len(order) >= 3 else None
    u_calls = len(calls)
    n_h = Counter(h for eid in calls for h in (ev[eid].get("callers") or {}))
    agg = aggregate(parts)
    first_trade = first_trade or {}
    n_cov = len(covered)
    bad = set(bad)
    out = {}
    for owner, by_eid in agg.items():
        mine = {eid: a for eid, a in by_eid.items() if eid in covered}
        if not mine:
            continue
        members = None
        early = {eid: a for eid, a in mine.items() if a[2]}
        hit_ids = sorted((eid for eid, a in early.items() if a[3]), key=lambda x: ev[x]["t0"])
        call_hits = [eid for eid in hit_ids if ev[eid]["kind"] == "call"]
        front = Counter()
        for eid in call_hits:
            bts = early[eid][0]
            for h, ts in (ev[eid].get("callers") or {}).items():
                if bts is not None and bts < ts:
                    front[h] += 1
        n_w = sum(1 for eid in early if ev[eid]["kind"] == "call")
        best_lift, best_h = None, None
        for h, n in front.items():
            if n < 2:
                continue
            lf, _exp = lift(n, n_w, n_h.get(h, n), u_calls)
            if lf is not None and (best_lift is None or lf > best_lift):
                best_lift, best_h = lf, h
        leads = [early[eid][1] / 60 for eid in hit_ids if early[eid][1] is not None]
        med_lead = _med(leads)
        snipe = [early[eid][0] - first_trade[ev[eid]["token"]] for eid in early
                 if ev[eid]["token"] in first_trade and early[eid][0] is not None]
        sniper = len(snipe) >= 2 and sum(1 for x in snipe if 0 <= x <= c["sniper_secs"]) / len(snipe) >= c["sniper_share"]
        busy = n_cov >= 10 and len(early) / n_cov >= c["busy_events_share"]
        sel = [eid for eid in hit_ids if cut_t is None or ev[eid]["t0"] < cut_t]
        conf = [eid for eid in hit_ids if cut_t is not None and ev[eid]["t0"] >= cut_t]
        if bad:
            members = sorted({w for a in mine.values() for w in a[6]})
        confirmed_ = False
        if owner.startswith("relayer:"):
            cls, why = "relayer", "plaća naknade za mnogo drugih vlasnika"
        elif bad and set(members) & bad:
            cls, why = "bot_snajper", "bot (brzina tradeova, oznaka ili previše tradeova dnevno)"
        elif sniper:
            cls, why = "bot_snajper", f"snajper (kupuje u prvih {c['sniper_secs']} s lansiranja)"
        elif busy:
            cls, why = "bot_snajper", f"kupio rano u {len(early)} od {n_cov} događaja (kupuje sve)"
        elif (len(hit_ids) >= c["min_tokens"] and len(call_hits) >= 2
              and (len(front) >= c["min_callers"] or (best_lift or 0) >= c["min_lift"])
              and (med_lead is None or med_lead >= c["min_lead_min"])):
            cls = "insajder"
            sel_ok = len(sel) >= c["min_tokens"]
            confirmed_ = bool(sel_ok and len(conf) >= c["min_confirm"])
            why = (f"kupio prije i prodao u skok na {len(hit_ids)} tokena, ispred {len(front)} callera"
                   + ("" if confirmed_ else f" (potvrda: {len(sel)} u starijem, {len(conf)} u novijem dijelu)"))
        elif len(hit_ids) >= 2:
            cls, why = "kandidat", None
        else:
            cls, why = "promatra", None
        if slim == "light" or (slim == "store" and cls == "promatra" and len(early) + len(hit_ids) < 2):
            out[owner] = {"cls": cls, "confirmed": confirmed_, "n_early": len(early), "n_hits": len(hit_ids)}
            if confirmed_:
                out[owner]["members"] = members or sorted({w for a in mine.values() for w in a[6]})
            continue
        if members is None:
            members = sorted({w for a in mine.values() for w in a[6]})
        pnl = [early[eid][5] - early[eid][4] for eid in hit_ids]
        st = {"owner": owner, "members": members, "n_early": len(early), "n_hits": len(hit_ids),
              "n_call_hits": len(call_hits), "n_callers": len(front), "callers": dict(front.most_common(8)),
              "lift": best_lift, "lift_caller": best_h, "med_lead_min": round(med_lead, 1) if med_lead is not None else None,
              "pnl_sol": round(sum(pnl), 4) if pnl else None,
              "tokens": [ev[eid]["token"] for eid in hit_ids], "symbols": [ev[eid].get("symbol") for eid in hit_ids],
              "crews": sorted({ev[eid]["crew"] for eid in hit_ids if ev[eid].get("crew")}),
              "first_ts": min((ev[eid]["t0"] for eid in early), default=None), "why": why, "confirmed": confirmed_,
              "cls": cls}
        st["score"] = round(len(hit_ids) + 0.5 * (len(early) - len(hit_ids)) + min(best_lift or 0, 10) / 5
                            + 0.5 * len(front) + (3 if st["confirmed"] else 0) - (5 if st["cls"] in OUT else 0), 2)
        out[owner] = st
    return out


def light(stats):
    """The light form of classify() stats (slim="light"): what the pass reads after save() (the class, confirmed, the
    members of a confirmed group), 20.11. (2): ~90 MB less for the walks and smart money."""
    out = {}
    for o, s in stats.items():
        x = {"cls": s["cls"], "confirmed": s["confirmed"], "n_early": s["n_early"], "n_hits": s["n_hits"]}
        if s["confirmed"]:
            x["members"] = s["members"]
        out[o] = x
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
