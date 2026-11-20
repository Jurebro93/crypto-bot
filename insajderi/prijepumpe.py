"""Novčanici koji kupuju PRIJE pumpe (19.11., vlasnik: "Ono što svaki dan želim su voleti ... svi resursi u
pronalaženje novčanika koji kupuju PRIJE pumpe (prije poziva influencera, prije nego što dođe izlazna likvidnost) i
PRODAJU u pumpu ... kad nađemo profitabilan novčanik i njegova povijest to dokaže, kopiramo ga u roku od sekunde";
isti dan kasnije: "midcapovi od 2 do 15 miliona ostaju, veći fokus na 15 do 200 ... traži bundle novčanike koji
pomiču cijenu i, najvažnije, insajderske novčanike").

Statistics, never accusations: a group here "kupuje prije pumpe" (bought before and sold into pumps more often than
a list of rules lets pass); nothing says who they are or why.

The pumps: the market jumps (events.py, midcap.db 1h closes) by PEAK market cap, events.tier_of: "pumpa15" (peak
>= focus_mcap 15M, the first Helius priority) and "pumpa2" (2-15M, the second); a call event that absorbed such a
jump (events.merge) carries its tier.

The class (classify, pure, as_of: only events whose window ended before it):
  prije_pumpe  an owner group (chain.owners: same funder / fee payer / corr.db merged) that BOUGHT before t0 with a
               PAID buy (sol_in >= min_sol: a swap paid in SOL; tokens received by transfer never are a buy: chain.
               _rows_of keeps only paid swaps, and a buy of another source with an unknown price is not "paid") and
               SOLD into the jump on >= pump_min_tokens (3) distinct pump tokens (both tiers count, reported apart),
               median lead >= min_lead_min; CONFIRMED by the insajder rule (score.classify): the pump events covered
               are cut at 2/3 by time; the older part must already hold >= pump_min_tokens of its tokens and the newer
               part >= min_confirm more hits
  excluded, each with its reason (why): relayer (fee payer of 5+ owners), bot (score.bots: rate, same-slot buy and
               sell, wallets.db labels, too busy), snajper (most early buys within sniper_secs of launch), kupuje sve
               (early in >= busy_events_share of >= 10 covered pumps), market maker (>= mm_min_side buys AND sells of
               one token inside one window [t0 - 6 h, win_end] on >= mm_min_events windows: two-sided flow, no
               direction), jednokratni (seen in one event only: a fresh wallet, no history), bez plaćene kupnje (it
               would pass only with buys whose price is unknown or zero: a transfer / airdrop cost basis)

The copy test (walk, the same walk-forward as copy.walk: for each UTC day D the confirmed set is classified from the
events whose window ended BEFORE D only; their buys of tokens new to them made during D; one trade a token):
  60 s     copy.simulate as the insider test (entry +delay_s at the first price, exit when they sell / stop / hold_h)
  brzo     copy.simulate(fast=True): +2 s at the token's own print within 5 s, else THEIR price x (1 + slip_fast):
           "Pretpostavka klizanja 1 %", an assumption, never a measurement
  null     the same days, the same delay and cost, copying owners drawn at random (seed null_seed) from the early
           buyers of the pumps known before D that are NOT selected (at least null_k a day, as many as selected)
  cost     trade/cost.round_trip at pp_size_sol (0.1 SOL) with the pool's liquidity when the collector knew it, never
           under veliki/replay.RT_FLOOR (3 %, the measured round trip: the source of truth sjena / učenik use); one
           more number at pp_size_sol_big (0.5 SOL)
  misses   a buy that could not be copied (no price at entry: "bez cijene"; liquidity known and under trade/cost
           LIQ_HARD_MIN: "likvidnost") stays a row with miss set, counted in n_buys and the miss share, never dropped
  numbers  mean net return a trade, a 95 % interval by a bootstrap over TOKENS (boot_n draws), n trades, n tokens,
           n owner groups, per MC bucket at entry (copy.BUCKETS: "15M+" and "5M-15M" apart)

Bundles (bundles, from the Helius rows chain.py stores: slot, fee payer; owner ids from i2_part): in a pump's window
[t0 - 6 h, win_end], (a) >= bundle_min_wallets wallets of ONE owner group or ONE fee payer (not themselves) buying
the token in the same slot (else the same second) = a same-block bundle; (b) an owner group of 2+ wallets whose buys
in [t0 - 1 h, t0 + bundle_early_s] are >= bundle_share of the window's buy volume (SOL). Listed from bundle_min_pumps
pumps with the pumps, the wallets, the median share of the early buy volume and whether they sold into the pump.
Only events Helius read have slot / payer: other sources carry neither.

Demo / measurement only: nothing here places or changes a trade (NEVER_LIVE, as the rest of insajderi/).
"""
import json
import os
import random
import statistics
import time
from collections import Counter, defaultdict

from insajderi import copy, score, store

CLS_HR = {"prije_pumpe": "kupuje prije pumpe", "relayer": "relayer", "bot": "bot", "snajper": "snajper",
          "kupuje_sve": "kupuje sve", "market_maker": "market maker (dvostrani promet)", "jednokratni": "jednokratni",
          "bez_placanja": "bez plaćene kupnje (prijenos / nepoznata cijena)", "kandidat": "kandidat",
          "promatra": "promatra se"}
OUT_NAME = "novcanici_prije_pumpe.md"
PREFIX = "novčanici prije pumpe: "


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pump_events(events, as_of):
    """{eid: event} of the pump events (a tier) whose window ended before as_of."""
    return {e["eid"]: e for e in events if e.get("tier") and e["win_end"] < as_of}


# ---------- exclusions that need the trades ---------------------------------------------------------------------------

def market_makers(con, events, c, stop=None):
    """Wallets with two-sided flow: >= mm_min_side buys AND >= mm_min_side sells of the token inside one pump window
    [t0 - 6 h, win_end] on >= mm_min_events windows (our Helius rows, i2_trades)."""
    by_tok = defaultdict(list)
    for e in events:
        if e.get("tier"):
            by_tok[e["token"]].append((int(e["t0"]) - 6 * 3600, int(e["win_end"])))
    side_min, ev_min = int(c["mm_min_side"]), int(c["mm_min_events"])
    hits = Counter()
    for tok, wins in by_tok.items():
        if stop is not None and stop():
            return None
        rows = store.q(con, "SELECT wallet, ts, side FROM i2_trades WHERE mint = ?", (tok,))
        for lo, hi in wins:
            n = defaultdict(lambda: [0, 0])
            for w, ts, side in rows:
                if lo <= (ts or 0) <= hi:
                    n[w][0 if side == "buy" else 1] += 1
            for w, (b, s) in n.items():
                if b >= side_min and s >= side_min:
                    hits[w] += 1
    return {w for w, k in hits.items() if k >= ev_min}


# ---------- the class -------------------------------------------------------------------------------------------------

def classify(parts, events, as_of, c, bad=frozenset(), first_trade=None, mm=frozenset()):
    """{owner: stats} of every owner group that bought early into a pump event known at as_of (pure)."""
    ev = {e["eid"]: e for e in events if e["win_end"] < as_of}
    covered_all = {eid for eid in ev if ev[eid].get("n_part")} or set(ev)
    pumps = {eid for eid in covered_all if ev[eid].get("tier")}
    order = sorted(pumps, key=lambda x: ev[x]["t0"])
    cut_t = ev[order[int(len(order) * 2 / 3)]]["t0"] if len(order) >= 3 else None
    agg = score.aggregate(parts)
    ft = first_trade or {}
    need = int(c["pump_min_tokens"])
    min_sol = float(c["min_sol"])
    n_cov = len(pumps)
    bad, mm = set(bad), set(mm)
    out = {}
    for owner, by_eid in agg.items():
        mine = {eid: a for eid, a in by_eid.items() if eid in pumps}
        early = {eid: a for eid, a in mine.items() if a[2]}
        if not early:
            continue
        seen_events = [eid for eid in by_eid if eid in covered_all]
        members = sorted({w for eid in seen_events for w in by_eid[eid][6]})
        both = sorted((eid for eid, a in early.items() if a[3]), key=lambda x: ev[x]["t0"])
        hits = [eid for eid in both if (early[eid][4] or 0) >= min_sol]          # a PAID buy, then sold into it
        toks = {ev[eid]["token"] for eid in hits}
        toks_any = {ev[eid]["token"] for eid in both}
        t15 = {ev[eid]["token"] for eid in hits if ev[eid]["tier"] == "pumpa15"}
        t2 = {ev[eid]["token"] for eid in hits if ev[eid]["tier"] == "pumpa2"}
        leads = [early[eid][1] / 60 for eid in hits if early[eid][1] is not None]
        med_lead = _med(leads)
        snipe = [early[eid][0] - ft[ev[eid]["token"]] for eid in early
                 if ev[eid]["token"] in ft and early[eid][0] is not None]
        sniper = (len(snipe) >= 2
                  and sum(1 for x in snipe if 0 <= x <= c["sniper_secs"]) / len(snipe) >= c["sniper_share"])
        busy = n_cov >= 10 and len(early) / n_cov >= c["busy_events_share"]
        sel = {ev[eid]["token"] for eid in hits if cut_t is None or ev[eid]["t0"] < cut_t}
        conf = [eid for eid in hits if cut_t is not None and ev[eid]["t0"] >= cut_t]
        st = {"owner": owner, "members": members, "n_pumps15": len(t15), "n_pumps2": len(t2), "n_tokens": len(toks),
              "n_early": len(early), "med_lead_min": round(med_lead, 1) if med_lead is not None else None,
              "pnl_sol": round(sum(early[eid][5] - early[eid][4] for eid in hits), 4) if hits else None,
              "last_seen": max((early[eid][0] for eid in early if early[eid][0] is not None), default=None),
              "tokens": sorted(toks), "confirmed": False, "why": None}
        if owner.startswith("relayer:"):
            st["cls"], st["why"] = "relayer", "plaća naknade za mnogo drugih vlasnika"
        elif set(members) & bad:
            st["cls"] = "bot"
            st["why"] = "bot (brzina tradeova, kupnja i prodaja u istom slotu, oznaka ili previše tradeova)"
        elif sniper:
            st["cls"], st["why"] = "snajper", f"kupuje u prvih {c['sniper_secs']} s lansiranja"
        elif busy:
            st["cls"], st["why"] = "kupuje_sve", f"kupio rano u {len(early)} od {n_cov} pumpi"
        elif set(members) & mm:
            st["cls"] = "market_maker"
            st["why"] = (f"dvostrani promet: barem {c['mm_min_side']} kupnje i prodaje u istom prozoru na "
                         f"{c['mm_min_events']}+ pumpe")
        elif len(seen_events) <= 1:
            st["cls"], st["why"] = "jednokratni", "viđen u jednom događaju (nema povijesti)"
        elif len(toks) < need <= len(toks_any):
            st["cls"] = "bez_placanja"
            st["why"] = (f"{len(toks_any)} pumpi samo uz kupnje bez poznate cijene (prijenos ili nepoznat trošak), "
                         f"plaćeno {len(toks)}")
        elif len(toks) >= need and (med_lead is None or med_lead >= c["min_lead_min"]):
            st["cls"] = "prije_pumpe"
            st["confirmed"] = bool(len(sel) >= need and len(conf) >= int(c["min_confirm"]))
            st["why"] = (f"kupio prije i prodao u pumpu na {len(toks)} tokena ({len(t15)} do ≥ 15M, {len(t2)} do 2-15M)"
                         + ("" if st["confirmed"]
                            else f" (potvrda: {len(sel)} u starijem, {len(conf)} u novijem dijelu)"))
        elif len(toks) >= 2:
            st["cls"] = "kandidat"
        else:
            st["cls"] = "promatra"
        out[owner] = st
    return out


def confirmed(stats):
    return {o: s["members"] for o, s in stats.items() if s["cls"] == "prije_pumpe" and s["confirmed"]}


# ---------- bundles ---------------------------------------------------------------------------------------------------

def bundles(con, events, c, as_of, stop=None):
    """{bid: {"kind", "members", "pumps", "pumps15", "shares", "sold", "tokens", "last"}} of the pump windows ended
    before as_of (see the module text). Reads i2_trades (slot, payer) and i2_part (owner, sold_into)."""
    pumps = [e for e in events if e.get("tier") and e["win_end"] < as_of]
    # 20.11. (production: the full pass killed at 800+ MB): the wallet -> owner map of every participant (~1M after the
    # deep reads) is resolved in a temp table (the same "last row wins" of a dict over the same query) and only the
    # wallets whose owner is not themselves come into memory (owner.get(w, w) answers the same); the sellers are read
    # per event
    con.execute("DROP TABLE IF EXISTS temp.i2_wown")
    con.execute("CREATE TEMP TABLE i2_wown (wallet TEXT PRIMARY KEY, owner TEXT)")
    try:
        con.execute("INSERT OR REPLACE INTO temp.i2_wown SELECT DISTINCT wallet, owner FROM i2_part WHERE owner IS NOT "
                    "NULL")
        owner = {w: o for w, o in store.q(con, "SELECT wallet, owner FROM temp.i2_wown WHERE owner IS NOT wallet")}
    finally:
        con.execute("DROP TABLE IF EXISTS temp.i2_wown")
    min_w, share_min = int(c["bundle_min_wallets"]), float(c["bundle_share"])
    out, sold = {}, {}

    def put(bid, kind, ws, e, share):
        b = out.setdefault(bid, {"kind": kind, "members": set(), "pumps": set(), "pumps15": set(), "shares": {},
                                 "sold": set(), "tokens": set(), "last": 0})
        b["members"] |= set(ws)
        # 19.11. (fix): pumps are counted as distinct pump TOKENS per bundle, never per event or per wallet (two events
        # of one token, or a call event and its jump, are one pump); save_bundles rewrites the whole table each pass
        b["pumps"].add(e["token"])
        if e["tier"] == "pumpa15":
            b["pumps15"].add(e["token"])
        if share is not None:
            b["shares"][e["token"]] = max(share, b["shares"].get(e["token"], 0.0))
        if set(ws) & sold[e["eid"]]:
            b["sold"].add(e["token"])
        b["tokens"].add(e["token"])
        b["last"] = max(b["last"], int(e["t0"]))
        if b["kind"] != kind:
            b["kind"] = "isti blok + udio"

    for e in pumps:
        if stop is not None and stop():
            return None   # cut: the stored bundles of the last full run stay
        t0, end = int(e["t0"]), int(e["win_end"])
        rows = store.q(con, "SELECT wallet, ts, slot, sol, payer FROM i2_trades WHERE mint = ? AND side = 'buy' AND "
                            "ts BETWEEN ? AND ?", (e["token"], t0 - 6 * 3600, end))
        if not rows:
            continue
        sold = {e["eid"]: {w for (w,) in store.q(con, "SELECT wallet FROM i2_part WHERE eid = ? AND sold_into = 1",
                                                  (e["eid"],))}}
        tot = sum(r[3] or 0 for r in rows)
        early_sol = defaultdict(float)
        early_w = defaultdict(set)
        for w, ts, _slot, sol, _payer in rows:
            if t0 - 3600 <= ts <= t0 + int(c["bundle_early_s"]):
                o = owner.get(w, w)
                early_sol[o] += sol or 0
                early_w[o].add(w)
        shares = {o: (v / tot if tot else None) for o, v in early_sol.items()}
        blocks = defaultdict(list)
        for w, ts, slot, _sol, payer in rows:
            blocks[("s", slot) if slot is not None else ("t", ts)].append((w, payer))
        for blk in blocks.values():
            by = defaultdict(set)
            for w, payer in blk:
                by["o:" + owner.get(w, w)].add(w)
                if payer and payer != w:
                    by["p:" + payer].add(w)
            for key, ws in by.items():
                if len(ws) >= min_w:
                    os_ = {owner.get(w, w) for w in ws}
                    put(key, "isti blok", ws, e, sum(early_sol.get(o, 0.0) for o in os_) / tot if tot else None)
        for o, sh in shares.items():
            if sh is not None and sh >= share_min and len(early_w[o]) >= 2:
                put("o:" + o, "udio ranih kupnji", early_w[o], e, sh)
    return out


def save_bundles(con, bs, c, now):
    con.execute("DELETE FROM i2_bundle")
    rows = []
    for bid, b in bs.items():
        if len(b["pumps"]) < int(c["bundle_min_pumps"]):
            continue
        sh = _med(list(b["shares"].values()))
        rows.append((bid, b["kind"], json.dumps(sorted(b["members"])), len(b["members"]), len(b["pumps"]),
                     len(b["pumps15"]), round(sh, 4) if sh is not None else None, len(b["sold"]),
                     json.dumps(sorted(b["tokens"])[:30]), b["last"], int(now)))
    con.executemany("INSERT OR REPLACE INTO i2_bundle VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


# ---------- the copy test ---------------------------------------------------------------------------------------------

def rt_floor():
    """The round-trip floor (fraction): veliki/replay.RT_FLOOR (3 %), the one the shadow book and the učenik use."""
    try:
        from veliki import replay
        return float(replay.RT_FLOOR)
    except Exception:  # noqa: BLE001
        return 0.03


def round_trip(size_sol, sol_usd, liq):
    """trade/cost.round_trip at size_sol (USD at sol_usd) with the pool's liquidity, never under rt_floor()."""
    try:
        from trade import cost
        rt = cost.round_trip(float(size_sol) * float(sol_usd), liq)
    except Exception:  # noqa: BLE001
        rt = 0.04
    return max(rt, rt_floor())


def liq_floor():
    try:
        from trade import cost
        return float(cost.LIQ_HARD_MIN)
    except Exception:  # noqa: BLE001
        return 15_000.0


def _copy_row(r, own, owner, pr, c, d, fast):
    """One copy of their buy r -> the row (always: a miss is a row with miss set)."""
    sells = [s for s in own if s[1] == r[1] and s[3] == "sell" and s[2] > r[2]]
    row = {"owner": owner, "token": r[1], "buy_ts": r[2], "day": store.day(d), "miss": None, "ret": None,
           "ret_big": None, "entry_ts": None, "mcap": None, "bucket": "?", "exit": None, "assumed": False}
    sim = copy.simulate(r, sells, pr, c, 0.0, fast=fast)
    if not sim:
        row["miss"] = "bez cijene"
        return row
    liq = pr.liq_at(r[1], sim["entry_ts"])
    if liq is not None and liq < liq_floor():
        row["miss"] = "likvidnost"
        return row
    su = pr.sol_usd(sim["entry_ts"])
    gross = sim["ret"]
    row.update(entry_ts=sim["entry_ts"], mcap=sim["mcap"], bucket=copy.bucket_of(sim["mcap"]), exit=sim["exit"],
               assumed=bool(sim.get("assumed")),
               ret=round(gross - round_trip(c["pp_size_sol"], su, liq), 4),
               ret_big=round(gross - round_trip(c["pp_size_sol_big"], su, liq), 4))
    return row


def _days(events, c, now):
    start = min(e["t0"] for e in events) + int(c["warmup_days"]) * 86400
    d0 = start - start % 86400 + 86400
    return list(range(d0, int(now) - int(now) % 86400 + 86400, 86400))


def selection(c, events, parts, now, bad=frozenset(), first_trade=None, mm=frozenset(), null=True, stop=None):
    """(days, {day: selected}, {day: null owners}, members) of the walk-forward. Day D: the confirmed "kupuje prije
    pumpe" groups classified from the events whose window ended BEFORE D only; the null: as many owners as selected
    (at least null_k), drawn at random (null_seed) from the early buyers of the pump events known before D that are not
    selected and not excluded. None when stop() came true first (19.11.: the pass's time budget)."""
    if not events:
        return [], {}, {}, set()
    days = _days(events, c, now)
    sel_by_day, null_by_day = {}, {}
    rng = random.Random(int(c["null_seed"]))
    owner_members = defaultdict(set)
    early_owners = defaultdict(set)   # eid -> owners that bought early (the null's pool)
    for eid, w, o, _b, _si, _ns, _so, _fs, bb, _sd, _l in parts:
        owner_members[o or w].add(w)
        if bb:
            early_owners[eid].add(o or w)
    for d in days:
        if stop is not None and stop():
            return None
        st = classify(parts, events, d, c, bad, first_trade, mm)
        sel_by_day[d] = confirmed(st)
        if null:
            pool = set()
            for eid in pump_events(events, d):
                pool |= early_owners.get(eid, set())
            excl = {o for o, s in st.items() if s["cls"] not in ("prije_pumpe", "kandidat", "promatra")}
            pool = sorted(pool - set(sel_by_day[d]) - excl)
            k = min(len(pool), max(len(sel_by_day[d]), int(c["null_k"])))
            null_by_day[d] = {o: sorted(owner_members[o]) for o in rng.sample(pool, k)} if k else {}
    members = {w for x in sel_by_day.values() for ms in x.values() for w in ms}
    members |= {w for x in null_by_day.values() for ms in x.values() for w in ms}
    return days, sel_by_day, null_by_day, members


def walk(con, p, c, events, parts, now, bad=frozenset(), first_trade=None, mm=frozenset(), trades=None, prices=None,
         null=True, sel=None, stop=None):
    """{"60s": [row], "brzo": [row], "null": [row]} and the selected sets per day (see selection(); one copy a token
    new to the group, bought during D). sel: selection()'s result when the caller has it; trades: the wallets' trades
    when the caller read them (19.11.: once a pass for this and copy.walk). stop() true: (None, {}): a cut walk is no
    result."""
    out = {"60s": [], "brzo": [], "null": []}
    if not events:
        return out, {}
    sel = sel if sel is not None else selection(c, events, parts, now, bad, first_trade, mm, null, stop)
    if sel is None:
        return None, {}
    days, sel_by_day, null_by_day, members = sel
    if not members:
        return out, sel_by_day
    trades = trades if trades is not None else copy.wallet_trades(con, p, members)
    by_w = defaultdict(list)
    for r in trades:
        by_w[r[0]].append(r)
    pr = prices or copy.Prices(con, p, c)
    for variant, chosen in (("60s", sel_by_day), ("brzo", sel_by_day), ("null", null_by_day)):
        taken = set()
        for d in days:
            if stop is not None and stop():
                return None, sel_by_day
            for owner, ms in (chosen.get(d) or {}).items():
                own = sorted((r for m in ms for r in by_w.get(m, [])), key=lambda r: r[2])
                before = {r[1] for r in own if r[2] < d}
                for r in own:
                    if not d <= r[2] < d + 86400 or r[3] != "buy" or r[1] in before or r[1] in taken or r[2] > now:
                        continue
                    taken.add(r[1])
                    out[variant].append(_copy_row(r, own, owner, pr, c, d, fast=(variant == "brzo")))
    return out, sel_by_day


def boot(rows, key, n=2000, seed=7):
    """(mean, lo, hi) of the mean net return a trade, the 95 % interval by a bootstrap over TOKENS (each draw takes
    tokens with replacement, all of a token's trades with it). (None, None, None) without a trade; no interval with
    one token."""
    by = defaultdict(list)
    for r in rows:
        if r.get(key) is not None:
            by[r["token"]].append(r[key])
    xs = [x for v in by.values() for x in v]
    if not xs:
        return None, None, None
    mean = sum(xs) / len(xs)
    toks = list(by.values())
    if len(toks) < 2:
        return mean, None, None
    rng = random.Random(seed)
    means = []
    for _ in range(int(n)):
        pick = [toks[rng.randrange(len(toks))] for _ in toks]
        s = sum(sum(v) for v in pick)
        k = sum(len(v) for v in pick)
        means.append(s / k)
    means.sort()
    return mean, means[int(0.025 * len(means))], means[min(len(means) - 1, int(0.975 * len(means)))]


def stats(rows, c):
    """{"n_buys", "n", "n_tokens", "n_owners", "miss_pct", "misses", "ev_pct", "lo_pct", "hi_pct", "ev_big_pct",
    "assumed_pct"} of copy rows (the misses counted, never dropped)."""
    pct = (lambda v: None if v is None else round(v * 100, 2))
    done = [r for r in rows if r.get("ret") is not None]
    m, lo, hi = boot(done, "ret", c["boot_n"])
    mb, _l, _h = boot(done, "ret_big", 1)
    return {"n_buys": len(rows), "n": len(done), "n_tokens": len({r["token"] for r in done}),
            "n_owners": len({r["owner"] for r in done}),
            "misses": dict(Counter(r["miss"] for r in rows if r.get("miss"))),
            "miss_pct": round(100 * sum(1 for r in rows if r.get("miss")) / len(rows), 1) if rows else None,
            "ev_pct": pct(m), "lo_pct": pct(lo), "hi_pct": pct(hi), "ev_big_pct": pct(mb),
            "assumed_pct": round(100 * sum(1 for r in done if r.get("assumed")) / len(done), 1) if done else None}


def summarize(res, c):
    """Per variant: all, and per MC bucket at entry; the selected minus the null."""
    out = {}
    for v, rows in res.items():
        out[v] = {"svi": stats(rows, c)}
        for name, _lo, _hi in copy.BUCKETS:
            out[v][name] = stats([r for r in rows if r.get("bucket") == name], c)
    a, b = (out.get("60s") or {}).get("svi") or {}, (out.get("null") or {}).get("svi") or {}
    out["razlika_pct"] = (round(a["ev_pct"] - b["ev_pct"], 2) if a.get("ev_pct") is not None
                          and b.get("ev_pct") is not None else None)
    return out


def save_copy(con, res):
    con.execute("DELETE FROM i2_pp_copy")
    con.executemany("INSERT OR REPLACE INTO i2_pp_copy VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(v, r["owner"], r["token"], r["buy_ts"], r.get("entry_ts"), r.get("mcap"), r.get("bucket"),
                      r.get("ret"), r.get("ret_big"), r.get("exit"), r.get("miss"), r["day"])
                     for v, rows in res.items() for r in rows])
    con.commit()


def save(con, st, now):
    old = {o: ts for o, ts in store.q(con, "SELECT owner, confirmed_ts FROM i2_pp")}
    con.execute("DELETE FROM i2_pp")
    rows = []
    for o, s in st.items():
        if s["cls"] in ("promatra", "jednokratni"):
            continue   # one sighting: counted in the classes, not stored (the table stays small)
        cts = (old.get(o) or int(now)) if s["confirmed"] else None
        rows.append((o, json.dumps(s["members"]), len(s["members"]), s["cls"], s["why"], s["n_pumps15"], s["n_pumps2"],
                     s["n_tokens"], s["med_lead_min"], s["pnl_sol"], cts, s["last_seen"], int(now)))
    con.executemany("INSERT INTO i2_pp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


# ---------- the pass --------------------------------------------------------------------------------------------------

def history(con, st, now, wallet_db=None):
    """19.11. (feed back of wallets/povijest.py, REPORT ONLY: never a selection rule, that would be tuning on the same
    data): per "kupuje prije pumpe" / kandidat group the members' own scored history (wallets.db) -> i2_pp_hist; agrees
    = the history's realized SOL has the sign of the group's pump record (pnl_sol), None while no member is scored.
    -> {"groups", "with_history", "agree", "disagree"}."""
    from wallets import povijest
    rows, out = [], {"groups": 0, "with_history": 0, "agree": 0, "disagree": 0}
    for o, s in st.items():
        if s["cls"] not in ("prije_pumpe", "kandidat"):
            continue
        h = povijest.group_history(s["members"], wallet_db)
        out["groups"] += 1
        agrees = None
        if h["n_scored"]:
            out["with_history"] += 1
            agrees = int((h["realized_sol"] > 0) == ((s.get("pnl_sol") or 0) > 0))
            out["agree" if agrees else "disagree"] += 1
        rows.append((o, s["cls"], int(bool(s["confirmed"])), h["n_members"], h["n_scored"], h["realized_sol"],
                     h["profitable_share"], s.get("pnl_sol"), agrees, int(now)))
    con.execute("DELETE FROM i2_pp_hist")
    con.executemany("INSERT INTO i2_pp_hist VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return out


def funnel(con, c, events, parts, st, now):
    """19.11. navečer (vlasnik: "zašto će večeras pisati premalo podataka?"): the honest funnel before any group
    qualifies (the class thresholds do not move): {"pumpe15_1h", "pumpe15_1d", "pumpe2_1h", "pumpe2_1d" (pump events
    found), "duboko" (read at full depth: i2_cover.depth >= store.FETCH_DEPTH), "rani" (distinct wallets that bought
    before t0 of a pump), "rani_prodali" (of them, also sold into it), "blizu_praga" (owner groups with pump_min_tokens
    - 1 paid pumps bought before and sold into, not excluded), "grupe" (the list: prije_pumpe), "potvrdjeno",
    "pokrivenost_pre_med" / "pokrivenost_skok_med" (median share of the pre / jump window the deep reads covered, %),
    "n_pokrivenost" (events with a coverage)}."""
    from insajderi import events as iev
    out = {k: 0 for k in ("pumpe15_1h", "pumpe15_1d", "pumpe2_1h", "pumpe2_1d", "duboko", "rani", "rani_prodali",
                          "blizu_praga", "grupe", "potvrdjeno")}
    tiered = {e["eid"]: e for e in events if e.get("tier") in ("pumpa15", "pumpa2")}
    for e in tiered.values():
        out[f"pumpe{'15' if e['tier'] == 'pumpa15' else '2'}_{iev.res_of(e)}"] += 1
    cov = {eid: (d, pc, jc) for eid, d, pc, jc in store.q(con, "SELECT eid, depth, pre_cov, jump_cov FROM i2_cover")}
    deep = [cov[eid] for eid in tiered if eid in cov and (cov[eid][0] or 0) >= store.FETCH_DEPTH]
    out["duboko"] = len(deep)
    pre = [x[1] for x in deep if x[1] is not None]
    jmp = [x[2] for x in deep if x[2] is not None]
    out["pokrivenost_pre_med"] = round(100 * _med(pre), 1) if pre else None
    out["pokrivenost_skok_med"] = round(100 * _med(jmp), 1) if jmp else None
    out["n_pokrivenost"] = len(pre)
    rani, prodali = set(), set()
    for r in parts:
        if r[0] in tiered and r[8]:
            rani.add(r[1])
            if r[9]:
                prodali.add(r[1])
    out["rani"], out["rani_prodali"] = len(rani), len(prodali)
    need = int(c["pump_min_tokens"])
    # 19.11. navečer: "blizu praga" = WALLETS with need - 1 distinct pump tokens bought (paid) before and sold into,
    # the same count funnel_sql gives before the list is computed
    toks = defaultdict(set)
    for r in parts:
        if r[0] in tiered and r[8] and r[9] and (r[4] or 0) >= float(c["min_sol"]):
            toks[r[1]].add(tiered[r[0]]["token"])
    out["blizu_praga"] = sum(1 for v in toks.values() if len(v) == need - 1)
    out["grupe"] = sum(1 for s in st.values() if s["cls"] == "prije_pumpe")
    out["potvrdjeno"] = len(confirmed(st))
    return out


def funnel_sql(con, c, events):
    """19.11. navečer: the funnel from cheap SQL counts, computed FIRST in a pass (before the owners, the bots and the
    classes), so the owner gets it even when the list stage is cut. The same keys as funnel(); "grupe" and
    "potvrdjeno" are the stored list's (i2_pp) of the last computed pass."""
    from insajderi import events as iev
    out = {k: 0 for k in ("pumpe15_1h", "pumpe15_1d", "pumpe2_1h", "pumpe2_1d", "duboko", "rani", "rani_prodali",
                          "blizu_praga", "grupe", "potvrdjeno")}
    tiered = {e["eid"]: e for e in events if e.get("tier") in ("pumpa15", "pumpa2")}
    for e in tiered.values():
        out[f"pumpe{'15' if e['tier'] == 'pumpa15' else '2'}_{iev.res_of(e)}"] += 1
    cov = {eid: (d, pc, jc) for eid, d, pc, jc in store.q(con, "SELECT eid, depth, pre_cov, jump_cov FROM i2_cover")}
    deep = [cov[eid] for eid in tiered if eid in cov and (cov[eid][0] or 0) >= store.FETCH_DEPTH]
    out["duboko"] = len(deep)
    pre = [x[1] for x in deep if x[1] is not None]
    jmp = [x[2] for x in deep if x[2] is not None]
    out["pokrivenost_pre_med"] = round(100 * _med(pre), 1) if pre else None
    out["pokrivenost_skok_med"] = round(100 * _med(jmp), 1) if jmp else None
    out["n_pokrivenost"] = len(pre)
    con.execute("DROP TABLE IF EXISTS temp.i2_tier")
    con.execute("CREATE TEMP TABLE i2_tier (eid TEXT PRIMARY KEY, token TEXT)")
    con.executemany("INSERT INTO temp.i2_tier VALUES (?, ?)", [(eid, e["token"]) for eid, e in tiered.items()])
    q = lambda sql, a=(): (store.q(con, sql, a) or [(0,)])[0][0] or 0   # noqa: E731
    out["rani"] = q("SELECT COUNT(DISTINCT p.wallet) FROM i2_part p JOIN temp.i2_tier t ON t.eid = p.eid "
                    "WHERE p.bought_before = 1")
    out["rani_prodali"] = q("SELECT COUNT(DISTINCT p.wallet) FROM i2_part p JOIN temp.i2_tier t ON t.eid = p.eid "
                            "WHERE p.bought_before = 1 AND p.sold_into = 1")
    out["blizu_praga"] = q("SELECT COUNT(*) FROM (SELECT p.wallet FROM i2_part p JOIN temp.i2_tier t ON t.eid = p.eid "
                           "WHERE p.bought_before = 1 AND p.sold_into = 1 AND COALESCE(p.sol_in, 0) >= ? GROUP BY "
                           "p.wallet HAVING COUNT(DISTINCT t.token) = ?)",
                           (float(c["min_sol"]), int(c["pump_min_tokens"]) - 1))
    con.execute("DROP TABLE temp.i2_tier")
    out["grupe"] = q("SELECT COUNT(*) FROM i2_pp WHERE cls = 'prije_pumpe'")
    out["potvrdjeno"] = q("SELECT COUNT(*) FROM i2_pp WHERE cls = 'prije_pumpe' AND confirmed_ts IS NOT NULL")
    return out


def funnel_line(pp):
    """The funnel line (19.11. navečer), one per pass next to the main line."""
    f = (pp or {}).get("lijevak")
    if not f:
        return PREFIX + "lijevak: još nema prolaza"
    cov = (f"medijan {f['pokrivenost_pre_med']:.0f} % (skok {f['pokrivenost_skok_med']:.0f} %, "
           f"{f['n_pokrivenost']} pumpi)" if f.get("pokrivenost_pre_med") is not None else "još nema dubokog čitanja")
    return (f"{PREFIX}lijevak: pumpi ≥ 15M {f['pumpe15_1h'] + f['pumpe15_1d']} (1h {f['pumpe15_1h']}, 1d "
            f"{f['pumpe15_1d']}), 2-15M {f['pumpe2_1h'] + f['pumpe2_1d']} (1h {f['pumpe2_1h']}, 1d {f['pumpe2_1d']}); "
            f"pročitano do pune dubine {f['duboko']}; ranih kupaca {f['rani']}, od njih prodali u pumpu "
            f"{f['rani_prodali']}; blizu praga (2 pumpe) {f['blizu_praga']}; grupa s 3+ pumpe {f['grupe']}; potvrđeno "
            f"{f['potvrdjeno']}; pokrivenost prozora prije skoka: {cov}"
            + (f"; {pp['punjenje']}" if pp.get("punjenje") else ""))


def run_list(con, c, now, events, parts, bad=frozenset(), first_trade=None, prev=None, stop=None):
    """The class list and the bundles, stored -> (the summary block without the copy numbers, the market makers).
    stop() true before the end: the stored list / bundles of the last run stay and the block says "cut"."""
    prev = prev or {}
    mm = market_makers(con, events, c, stop)
    if mm is None:
        return dict(prev, cut="popis"), set()
    st = classify(parts, events, now + 1, c, bad, first_trade, mm)
    save(con, st, now)
    bs = bundles(con, events, c, now + 1, stop)
    n_b = save_bundles(con, bs, c, now) if bs is not None else prev.get("bundles", 0)
    pumps = pump_events(events, now + 1)
    cov = [e for e in pumps.values() if e.get("n_part")]
    cls = Counter(s["cls"] for s in st.values())
    out = {"ts": int(now), "pumps15": sum(1 for e in pumps.values() if e["tier"] == "pumpa15"),
           "pumps2": sum(1 for e in pumps.values() if e["tier"] == "pumpa2"),
           "covered15": sum(1 for e in cov if e["tier"] == "pumpa15"),
           "covered2": sum(1 for e in cov if e["tier"] == "pumpa2"),
           "fetched15": sum(1 for e in pumps.values() if e["tier"] == "pumpa15" and e.get("fetched")),
           "groups": cls.get("prije_pumpe", 0), "confirmed": len(confirmed(st)), "classes": dict(cls),
           "market_makers": len(mm), "bundles": n_b, "min_tokens": int(c["pump_min_tokens"]),
           "min_n": int(c["pp_min_n"]), "slip_fast_pct": round(float(c["slip_fast"]) * 100, 2),
           "copy": prev.get("copy"), "copy_ts": prev.get("copy_ts")}
    if store.backfill_on(c, now):   # 19.11. navečer: the line says the backfill budget applies
        out["punjenje"] = store.backfill_label(c)
    if bs is None:
        out["cut"] = "bundle"
    out["lijevak"] = funnel(con, c, events, parts, st, now)
    try:   # 19.11.: the members' own history (wallets/povijest.py), report only
        out["povijest"] = history(con, st, now)
    except Exception as e:  # noqa: BLE001 - the list never fails on it
        out["povijest"] = {"error": f"{type(e).__name__}: {e}"[:120]}
    return out, mm


def run_copy(con, p, c, now, events, parts, block, res):
    """Store the copy rows `res` (walk()'s) and put their numbers into the block (copy_ts = now)."""
    save_copy(con, res)
    return dict(block, copy=summarize(res, c), copy_ts=int(now))


def run(con, p, c, now, events, parts, bad=frozenset(), first_trade=None, prev=None, light=False):
    """The list and the bundles, and (not light) the copy test -> the summary block (tests; run.analyze calls the
    parts in its own order under the pass's time budget)."""
    block, mm = run_list(con, c, now, events, parts, bad, first_trade, prev)
    if light and block.get("copy"):
        return block
    res, _sel = walk(con, p, c, events, parts, now, bad, first_trade, mm)
    return run_copy(con, p, c, now, events, parts, block, res)


# ---------- what it says ----------------------------------------------------------------------------------------------

def _ci(s):
    if not s or s.get("ev_pct") is None:
        return "nema kopija"
    ci = f" [{s['lo_pct']:+.1f}; {s['hi_pct']:+.1f}]" if s.get("lo_pct") is not None else " [interval: 1 token]"
    return f"{s['ev_pct']:+.1f} %{ci} n={s['n']}"


def line(pp, helius_today=0, helius_cap=0):
    """The ONE daily log line (see the order of 19.11.)."""
    if not pp:
        return PREFIX + f"još nema prolaza; Helius danas {helius_today:,}/{helius_cap:,}"
    cp = pp.get("copy") or {}
    a, f, z = ((cp.get(k) or {}).get("svi") or {} for k in ("60s", "brzo", "null"))
    heli = f"Helius danas {helius_today:,}/{helius_cap:,}" + (f" ({pp['punjenje']})" if pp.get("punjenje") else "")
    if pp.get("copy_ts") and pp.get("ts") and pp["copy_ts"] != pp["ts"]:   # 19.11.: incr reuses the full pass's copy
        heli = f"brojke kopije iz prolaza {_t(pp['copy_ts'])} UTC; " + heli
    head = (f"{PREFIX}{pp.get('covered15', 0)} pumpi ≥ 15M i {pp.get('covered2', 0)} pumpi 2-15M pokriveno "
            f"(od {pp.get('pumps15', 0)} + {pp.get('pumps2', 0)}), {pp.get('groups', 0)} grupa kupuje prije pumpe "
            f"({pp.get('confirmed', 0)} potvrđeno), bundle grupa {pp.get('bundles', 0)}")
    if pp.get("copy_progress"):   # 19.11. navečer (2): the incremental walk has not reached today yet
        return head + f"; {pp['copy_progress']}, brojke kad dođe do danas; {heli}"
    if not pp.get("confirmed") or (a.get("n") or 0) < int(pp.get("min_n") or 20):
        return (head + f"; premalo podataka za kopiju: {a.get('n', 0)} kopija od {a.get('n_buys', 0)} kupnji (treba "
                f"{pp.get('min_n', 20)}; grupa treba {pp.get('min_tokens', 3)} pumpe i potvrdu na novijim danima); "
                f"nasumični: {_ci(z)}; {heli}")
    a15 = (cp.get("60s") or {}).get("15M+") or {}
    return (head + f"; kopija 60 s: {_ci(a)} (promašeno {a.get('miss_pct')} %; MC ≥ 15M pri ulazu {_ci(a15)}; "
            f"uz 0,5 SOL {a.get('ev_big_pct')} %), brzo 2 s (Pretpostavka klizanja {pp.get('slip_fast_pct', 1):g} %): "
            f"{_ci(f)} (promašeno {f.get('miss_pct')} %), nasumični: {_ci(z)} (promašeno {z.get('miss_pct')} %), "
            f"odabrani minus nasumični {cp.get('razlika_pct')} pp; {heli}")


def _sh(w):
    return (w or "?")[:4] + "…" + (w or "?")[-4:]


def _t(ts):
    return time.strftime("%d.%m. %H:%M", time.gmtime(ts)) if ts else "—"


def groups(con, limit=50, cls="prije_pumpe"):
    rows = store.q(con, "SELECT owner, n_members, cls, why, n_pumps15, n_pumps2, n_tokens, med_lead_min, pnl_sol, "
                        "confirmed_ts, last_seen FROM i2_pp WHERE cls = ? ORDER BY (confirmed_ts IS NULL), "
                        "n_pumps15 DESC, n_tokens DESC LIMIT ?", (cls, int(limit)))
    keys = ("owner", "n_members", "cls", "why", "n_pumps15", "n_pumps2", "n_tokens", "med_lead_min", "pnl_sol",
            "confirmed_ts", "last_seen")
    return [dict(zip(keys, r)) for r in rows]


def bundle_rows(con, limit=30):
    rows = store.q(con, "SELECT bid, kind, n_members, n_pumps, n_pumps15, share_med, sold_into, last_seen "
                        "FROM i2_bundle ORDER BY n_pumps15 DESC, n_pumps DESC LIMIT ?", (int(limit),))
    keys = ("bid", "kind", "n_members", "n_pumps", "n_pumps15", "share_med", "sold_into", "last_seen")
    return [dict(zip(keys, r)) for r in rows]


def _hist_line(pp):
    """19.11.: the members' own history against the pump record (wallets/povijest.py; only reported, never a rule)."""
    h = (pp or {}).get("povijest") or {}
    if not h or "groups" not in h:
        return "Povijest članova (novčanici povijest): još nema."
    return (f"Povijest članova (novčanici povijest, samo izvještaj, nije pravilo odabira): od {h['groups']} grupa "
            f"{h['with_history']} ima ocijenjenu povijest barem jednog člana; povijest se slaže s rekordom pumpi kod "
            f"{h['agree']}, ne slaže kod {h['disagree']}.")


def markdown(pp, con, helius_today=0, helius_cap=0):
    L = ["# Novčanici koji kupuju prije pumpe", "",
         f"Prolaz {_t((pp or {}).get('ts'))} UTC. Statistika, ne optužba: „kupuje prije pumpe” znači samo da je grupa "
         "novčanika više puta kupila prije skoka i prodala u skok. Samo mjerenje i demo; pravi novac nikad iz ovog "
         "alata.",
         "", line(pp, helius_today, helius_cap), "", "## Popis (potvrđeni prvi)", "",
         "| grupa | novčanika | pumpi ≥ 15M | pumpi 2-15M | vodstvo med. min | PnL SOL | potvrđeno | zadnji put |",
         "|---|---|---|---|---|---|---|---|"]
    gs = groups(con)
    for g in gs:
        L.append(f"| {_sh(g['owner'])} | {g['n_members']} | {g['n_pumps15']} | {g['n_pumps2']} | {g['med_lead_min']} | "
                 f"{g['pnl_sol']} | {'da' if g['confirmed_ts'] else 'ne'} | {_t(g['last_seen'])} |")
    if not gs:
        L.append("| — | | | | | | | |")
    cls = (pp or {}).get("classes") or {}
    L += ["", "Isključeno (razlog): " + (", ".join(f"{CLS_HR.get(k, k)} {v}" for k, v in sorted(cls.items())
                                                   if k not in ("prije_pumpe",)) or "—"), "",
          _hist_line(pp), "", funnel_line(pp), "",
          "## Kopiranje (walk-forward: odabir samo iz prošlosti, trošak nikad ispod 3 %, promašaji brojani)", "",
          "| varijanta | skupina | kupnji | kopija | tokena | grupa | promašeno % | prosjek % | 95 % od | 95 % do "
          "| uz 0,5 SOL % |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    cp = (pp or {}).get("copy") or {}
    for v, name in (("60s", "60 s"), ("brzo", "brzo 2 s (Pretpostavka klizanja 1 %)"), ("null", "nasumični")):
        for k in ("svi", "15M+", "5M-15M", "1M-5M", "<1M"):
            x = (cp.get(v) or {}).get(k) or {}
            L.append(f"| {name} | {k} | {x.get('n_buys', 0)} | {x.get('n', 0)} | {x.get('n_tokens', 0)} | "
                     f"{x.get('n_owners', 0)} | {x.get('miss_pct')} | {x.get('ev_pct')} | {x.get('lo_pct')} | "
                     f"{x.get('hi_pct')} | {x.get('ev_big_pct')} |")
    L += ["", f"Odabrani minus nasumični (60 s, svi): {cp.get('razlika_pct')} postotnih bodova.", "",
          "## Bundle novčanici (pomiču cijenu)", "",
          "| bundle | vrsta | novčanika | pumpi | od toga ≥ 15M | udio ranih kupnji (medijan) | prodali u pumpu "
          "| zadnji put |",
          "|---|---|---|---|---|---|---|---|"]
    bs = bundle_rows(con)
    for b in bs:
        sh = f"{b['share_med'] * 100:.0f} %" if b["share_med"] is not None else "—"
        L.append(f"| {_sh(b['bid'][2:])} ({'vlasnik' if b['bid'].startswith('o:') else 'platitelj'}) | {b['kind']} | "
                 f"{b['n_members']} | {b['n_pumps']} | {b['n_pumps15']} | {sh} | {b['sold_into']} od {b['n_pumps']} | "
                 f"{_t(b['last_seen'])} |")
    if not bs:
        L.append("| — | | | | | | | |")
    try:   # 19.11. navečer: Birdeye, a second source (insajderi/birdeye.py)
        from insajderi import birdeye
        L += [""] + birdeye.md_section(con) if con is not None else []
    except Exception:  # noqa: BLE001
        pass
    L += ["", "## Pretpostavka", "",
          "- „brzo 2 s”: ulaz po vlastitom tradeu tokena unutar 5 s, inače njihova cijena + 1 % (pretpostavka, ne "
          "mjerenje)",
          "- vrh pumpe = najviše satno zatvaranje (ne fitilj); MC vrha = današnji MC × vrh / zadnje zatvaranje",
          "- bundle: isti slot ili ista sekunda samo za događaje koje je Helius pročitao; ostali izvori nemaju slot ni "
          "platitelja", ""]
    return "\n".join(L) + "\n"


def write(pp, helius_today=0, helius_cap=0, path=None):
    from insajderi import report
    con = store.ro(path or store.db_path())
    try:
        text = markdown(pp, con, helius_today, helius_cap)
    finally:
        if con is not None:
            con.close()
    os.makedirs(report.OUT_DIR, exist_ok=True)
    with open(os.path.join(report.OUT_DIR, OUT_NAME), "w", encoding="utf-8") as f:
        f.write(text)
    return text
