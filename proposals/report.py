"""The daily proposals report, 23:30 Zagreb, hooked into events/evreport (run_sched "evreport": the EV report per
feature phase calls ev_rows for the flag proposals while it is not off).

Per strategy, over the Zagreb day: proposals made, bought (Kupi), rejected, expired, hit rate (TP before SL within 4 h
of the proposal, outcomes.py), EV per proposal (the measured 4 h result of a trade on its exit after cost), the paper
proof of the demo account (proposals/paper.py: closed trades, hit = ret > 0, EV) and the reasons the owner gave.
The day's biggest risers we did NOT propose (market cap >= $30k): the scanner's universe (scan.db cand: 24 h change)
and the momentum universe (momentum.db snapshots: the day's highest market cap over the lowest before it), and per
strategy whether it saw the token (proposed it), nearly did (seen: blocked or EV <= 0, with the reason; momentum also
a token it watched without a signal) or never saw it. Stored in proposals.db reports (get_proposals "report") and as
log lines.

12.11. (Jure, točka 4: "kad token ima manje od 3 točke cijene u prozoru, označi rezultat kao 'nepouzdano' i ne
računaj ga u statistiku propuštenih"): a momentum riser seen in fewer than 3 snapshots of the day is no missed riser
(missed_risers_unreliable counts them; the scanner's 24 h change is DexScreener's own number, no points of ours), and
a proposal through its zone whose hypothetical lot had fewer than 3 minutes of prices after the entry is "propušten
ulaz" with quality "nepouzdano": no outcome, not in the outcome counts or the average (unreliable counts them).
"""
import datetime as dt
import json
import sqlite3
import time
from zoneinfo import ZoneInfo

from . import store, strategies

TZ = "Europe/Zagreb"
RISERS = 10
RISE_MIN_X = 1.5
MIN_MCAP = 30_000


def day_bounds(now):
    d = dt.datetime.fromtimestamp(int(now), ZoneInfo(TZ))
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return d.date().isoformat(), int(start.timestamp())


def _summ(ps):
    meas = [p for p in ps if ((p.get("after") or {}).get("4h") or {}).get("status") == "ok"]
    hits = sum(1 for p in meas if p["after"]["4h"]["first"] == "tp")
    rets = [p["after"]["4h"]["ret_pct"] for p in meas]
    return {"proposals": len(ps), "bought": sum(1 for p in ps if p["status"] == "kupljeno"),
            "rejected": sum(1 for p in ps if p["status"] == "odbijeno"),
            "expired": sum(1 for p in ps if p["status"] == "isteklo"), "measured": len(meas),
            "hit_rate": round(hits / len(meas), 3) if meas else None,
            "ev_pct": round(sum(rets) / len(rets), 2) if rets else None,
            "ev_expected_pct": round(sum(p.get("ev_pct") or 0 for p in ps) / len(ps), 2) if ps else None}


def risers(now, start, scan_con=None, mom_con=None, thin=None):
    """[{"token", "symbol", "rise_x", "mcap", "from"}] of the day, mcap >= 30k, rise >= RISE_MIN_X, biggest first.
    12.11. (Jure, točka 4): a momentum rise read from fewer than 3 snapshots of the day is nepouzdano: not a riser;
    thin (a list) gets those risers (with "n_points") for the count."""
    from rangedca import missed as rmissed
    by = {}
    own_s = scan_con is None
    try:
        if scan_con is None:
            from scan import store as sstore
            scan_con = sstore.ro()
    except Exception:  # noqa: BLE001
        scan_con = None
    if scan_con is not None:
        try:
            for tok, sym, mc, ch in scan_con.execute("SELECT token, symbol, mcap, ch_h24 FROM cand WHERE last_seen >= ? AND "
                                                     "mcap >= ? AND ch_h24 IS NOT NULL", (int(start), MIN_MCAP)):
                x = 1 + float(ch) / 100
                if x >= RISE_MIN_X:
                    by[tok] = {"token": tok, "symbol": sym, "rise_x": round(x, 2), "mcap": mc, "from": "skener (24 h)"}
        except sqlite3.Error:
            pass
        finally:
            if own_s:
                scan_con.close()
    own_m = mom_con is None
    try:
        if mom_con is None:
            from momentum import data as mdata
            mom_con = mdata.ro()
    except Exception:  # noqa: BLE001
        mom_con = None
    if mom_con is not None:
        try:
            lo, best, last, pts = {}, {}, {}, {}
            for tok, mc in mom_con.execute("SELECT token, mcap FROM snaps WHERE ts >= ? AND ts <= ? AND mcap > 0 ORDER BY "
                                           "token, ts", (int(start), int(now))):
                lo[tok] = min(lo.get(tok, mc), mc)
                x = mc / lo[tok]
                if mc >= MIN_MCAP and x > best.get(tok, (0, 0))[0]:
                    best[tok] = (x, mc)
                last[tok] = mc
                pts[tok] = pts.get(tok, 0) + 1
            for tok, (x, mc) in best.items():
                if x >= RISE_MIN_X and rmissed.unreliable(pts.get(tok)):   # 12.11.: too few snapshots for a rise
                    if thin is not None and tok not in by:
                        thin.append({"token": tok, "symbol": None, "rise_x": round(x, 2), "mcap": mc,
                                     "from": "momentum svemir (dan)", "n_points": pts.get(tok)})
                    continue
                if x >= RISE_MIN_X and x > (by.get(tok) or {}).get("rise_x", 0):
                    by[tok] = {"token": tok, "symbol": (by.get(tok) or {}).get("symbol"), "rise_x": round(x, 2), "mcap": mc,
                               "from": "momentum svemir (dan)"}
        except sqlite3.Error:
            pass
        finally:
            if own_m:
                mom_con.close()
    return sorted(by.values(), key=lambda r: -r["rise_x"])[:RISERS * 3]


def _momentum_seen(tokens, start, mom_con=None):
    """({tokens with a momentum signal today}, {tokens momentum watched today})."""
    own = mom_con is None
    try:
        if mom_con is None:
            from momentum import data as mdata
            mom_con = mdata.ro()
    except Exception:  # noqa: BLE001
        mom_con = None
    if mom_con is None or not tokens:
        return set(), set()
    try:
        q = ",".join("?" * len(tokens))
        sig = {t for (t,) in mom_con.execute(f"SELECT DISTINCT token FROM signals WHERE ts >= ? AND token IN ({q})",
                                             (int(start), *tokens))}
        watched = {t for (t,) in mom_con.execute(f"SELECT DISTINCT token FROM snaps WHERE ts >= ? AND token IN ({q})",
                                                 (int(start), *tokens))}
        return sig, watched
    except sqlite3.Error:
        return set(), set()
    finally:
        if own:
            mom_con.close()


def missed(con, rs, day, start, mom_con=None, limit=RISERS):
    """The risers we did not propose, each with per strategy vidio / skoro / nikad (at most `limit`)."""
    toks = [r["token"] for r in rs]
    if not toks:
        return []
    q = ",".join("?" * len(toks))
    proposed = {t for (t,) in con.execute(f"SELECT DISTINCT token FROM proposals WHERE created_ts >= ? AND token IN ({q})",
                                          (int(start), *toks))}
    seen = {}
    for tok, k, prop, why, ev in con.execute(f"SELECT token, strategy, proposed, why, best_ev FROM seen WHERE day = ? AND "
                                             f"token IN ({q})", (day, *toks)):
        seen.setdefault(tok, {})[k] = (prop, why, ev)
    sig, watched = _momentum_seen(toks, start, mom_con)
    out = []
    for r in rs:
        s = seen.get(r["token"]) or {}
        if r["token"] in proposed or any(v[0] for v in s.values()):
            continue   # we proposed it: not a missed riser
        per = {}
        for k in strategies.STRATEGIES:
            if k in s:
                per[k] = "skoro: " + (s[k][1] or f"EV {s[k][2]}")
            elif k == "momentum" and r["token"] in sig:
                per[k] = "vidio: momentum signal (nije prošao u prijedlog)"
            elif k == "momentum" and r["token"] in watched:
                per[k] = "skoro: praćen u momentum svemiru, bez signala"
            else:
                per[k] = "nikad"
        out.append({**r, "strategies": per})
        if len(out) >= limit:
            break
    return out


def daily(now=None, path=None, lcon=None, scan_con=None, mom_con=None):
    """The day's report dict (and stored in proposals.db reports)."""
    now = int(now or time.time())
    day, start = day_bounds(now)
    con = store.connect(path)
    try:
        ps = store.read(con, "created_ts >= ?", (start,), order="id", limit=10_000)
        per = {k: _summ([p for p in ps if k in (p.get("sources") or [])]) for k in strategies.STRATEGIES}
        reasons = {}
        for p in ps:
            if p["status"] == "odbijeno":
                reasons[p.get("reject_reason") or "drugo"] = reasons.get(p.get("reject_reason") or "drugo", 0) + 1
        try:
            from . import paper
            proof = paper.proof(lcon)
        except Exception:  # noqa: BLE001
            proof = {}
        thin = []
        rs = risers(now, start, scan_con, mom_con, thin)
        rep = {"day": day, "ts": now, "all": _summ(ps), "per_strategy": per, "paper": proof,
               "reject_reasons": reasons, "missed_risers": missed(con, rs, day, start, mom_con),
               # 12.11. (Jure, točka 4): the risers we did not propose seen in fewer than 3 snapshots (not listed)
               "missed_risers_unreliable": len(missed(con, thin, day, start, mom_con, len(thin))) if thin else 0,
               "how": ("hit = TP prije SL-a u 4 h od prijedloga; EV = izmjereni rezultat trejda po izlazu prijedloga "
                       "nakon troška (TP -> +TP, SL -> -SL, ništa -> zatvaranje); paper = demo račun (ret > 0)")}
        con.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (day, now, json.dumps(rep, ensure_ascii=False)))
        con.commit()
        return rep
    finally:
        con.close()


def latest(path=None):
    con = store.ro(path)
    if con is None:
        return None
    try:
        r = con.execute("SELECT data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
        return json.loads(r[0]) if r else None
    except (sqlite3.Error, ValueError):
        return None
    finally:
        con.close()


def lines(rep):
    """Croatian log lines of the report."""
    if not rep:
        return []

    def pct(x):
        return f"{x:.0%}" if x is not None else "-"

    def ev(x):
        return f"{x:+.2f} %" if x is not None else "-"
    a = rep["all"]
    out = [f"Prijedlozi {rep['day']}: {a['proposals']} prijedloga, kupljeno {a['bought']}, odbijeno {a['rejected']}, "
           f"isteklo {a['expired']}; izmjereno {a['measured']}, pogodak (TP prije SL u 4 h) {pct(a['hit_rate'])}, "
           f"EV {ev(a['ev_pct'])} (očekivani {ev(a['ev_expected_pct'])})."]
    for k, s in rep["per_strategy"].items():
        if s["proposals"]:
            pp = (rep.get("paper") or {}).get(k) or {}
            out.append(f"  {strategies.HR.get(k, k)}: {s['proposals']} prijedloga, kupljeno {s['bought']}, pogodak "
                       f"{pct(s['hit_rate'])} (n={s['measured']}), EV {ev(s['ev_pct'])}; paper {pp.get('n', 0)} "
                       f"zatvorenih, EV {ev(pp.get('ev_pct'))}.")
    if rep.get("reject_reasons"):
        out.append("  Odbijeno zbog: " + ", ".join(f"{k} {v}" for k, v in rep["reject_reasons"].items()) + ".")
    for m in (rep.get("missed_risers") or [])[:5]:
        saw = "; ".join(f"{strategies.HR.get(k, k)} {v}" for k, v in m["strategies"].items() if v != "nikad") or \
            "nijedna strategija ga nije vidjela"
        out.append(f"  Propušten rast: {m.get('symbol') or m['token'][:6]} {m['rise_x']:.1f}x (MC ${m.get('mcap') or 0:,.0f}, "
                   f"{m['from']}): {saw}.")
    if rep.get("missed_risers_unreliable"):   # 12.11. (Jure, točka 4)
        from rangedca import missed as rmissed
        out.append(f"  Propušten rast, {rmissed.note(rep['missed_risers_unreliable'])} u snimkama dana: "
                   "nije na popisu.")
    return out


# ---------- 11.11. (the owner's rules after HAOBIBI): proposals through their entry zone without a paper entry ----------

ZONE_HOURS = 48
MISS_HORIZON_S = 24 * 3600   # the hypothetical lot is followed at most this long after its entry
MISS_LIST = 10
KINDS = ("missed", "paper", "skipped_range", "skipped_held", "not_in_zone", "no_data")
KIND_HR = {"missed": "propušten ulaz", "paper": "paper ulaz", "skipped_range": "preskočeno: range runda/cooldown",
           "skipped_held": "preskočeno: demo već drži token", "not_in_zone": "cijena nije ušla u zonu",
           "no_data": "nema cijena"}
OUT_HR = {"tp": "TP prvi", "sl": "SL prvi", "time": "vrijeme", "open": "otvoreno"}


def _soft_expiry(p):
    """An expiry the waiting rules no longer make (its source vanished, its EV or a strategy went with the price): the
    proposal would have waited until expires_ts."""
    why = (p.get("status_why") or "")
    if not why.startswith("više ne vrijedi: "):
        return False
    rest = why[len("više ne vrijedi: "):]
    return rest.startswith("izvor prijedloga je nestao") or rest.startswith("EV ") or \
        any(rest.startswith(h + ":") for h in strategies.HR.values())


def window_end(p, now):
    """Until when a proposal waited for its zone: the owner's decision (kupljeno / odbijeno), the stop rule, a hard
    block or the time at status_ts; still novo or a soft expiry (_soft_expiry): its validity expires_ts. Capped at now."""
    if p["status"] in ("kupljeno", "odbijeno") or (p["status"] == "isteklo" and not _soft_expiry(p)):
        end = p.get("status_ts") or p.get("expires_ts")
    else:
        end = p.get("expires_ts")
    return min(int(now), int(end or now))


def _range_rounds(lcon, user):
    """{token: [(opened_ts, closed_ts or None)]} of the demo account's range rounds (league.db)."""
    out = {}
    try:
        for tok, o, c in lcon.execute("SELECT token, opened_ts, closed_ts FROM range_rounds WHERE user=?", (user,)):
            out.setdefault(tok, []).append((o or 0, c))
    except sqlite3.Error:
        pass
    return out


def _held_at(lcon, user, tok, ts):
    """True when the demo account held the token at ts in a trade that is not a proposal's or a range lot."""
    try:
        return lcon.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND opened_ts<=? AND (closed_ts IS NULL OR "
                            "closed_ts>?) AND COALESCE(source, '') NOT LIKE 'prijedlog%' AND COALESCE(source, '') NOT "
                            "LIKE 'range lot%' LIMIT 1", (user, tok, int(ts), int(ts))).fetchone() is not None
    except sqlite3.Error:
        return False


def _paper_entries(lcon, user):
    """{proposal id: the demo lot's entry market cap or None} of the demo account's paper entries (league.db)."""
    try:
        return {pid: mc for pid, mc in lcon.execute(
            "SELECT pt.proposal_id, t.entry_mcap FROM proposal_trades pt LEFT JOIN trades t ON t.id = pt.trade_id "
            "WHERE pt.user=?", (user,))}
    except sqlite3.Error:
        from . import paper
        return {pid: None for pid in paper.taken_ids(lcon, user)}


def _sol_usd():
    try:
        from ui import kandidati
        return float(kandidati.SOL_USD)
    except Exception:  # noqa: BLE001
        return 250.0


def zone_miss_one(p, cs, now, taken, rounds, lcon=None, user=None, cooldown_s=1200, sol_usd=None):
    """One proposal against its minute path cs (price): {"id", "token", "symbol", "strategy", "kind" (KINDS), "zone",
    "sl", "first_in_zone_ts", "first_in_zone_mc", "outcome", "ret_pct"}. The walk (strategies.wait_check's rules):
    from its creation to window_end, the first minute whose close is inside the zone and above the stop is the entry;
    a low under the stop ends the wait first when the stop rule was armed (above the stop at creation, or in the zone
    since). The outcome: outcomes.exit_sim on the proposal's exit plan, net of trade/cost.round_trip of its stake in
    its pool."""
    from trade import cost as tcost
    from . import outcomes
    r = p.get("row") or {}
    z, sl = strategies.zone_of(r, p.get("mcap0")), strategies.stop_of(r)
    px0, mc0 = p.get("price0") or r.get("price0"), p.get("mcap0") or r.get("mcap0")
    supply = (float(mc0) / float(px0)) if px0 and mc0 else None
    out = {"id": p["id"], "token": p["token"], "symbol": p.get("symbol"), "strategy": p.get("strategy"),
           "status": p["status"], "zone": [round(z[0]), round(z[1])] if z else None, "sl": sl,
           "first_in_zone_ts": None, "first_in_zone_mc": None, "outcome": None, "ret_pct": None}
    if p["id"] in taken:
        mc = taken[p["id"]] if isinstance(taken, dict) else None
        out.update(kind="paper", paper_mcap=mc,   # the old rule bought at any price (HAOBIBI: $88k, zone $104-112k)
                   paper_in_zone=(None if not mc or not z else bool(z[0] <= mc <= z[1] and (not sl or mc > sl))))
        return out
    if not z or not supply or not cs:
        out["kind"] = "no_data"
        return out
    t0, t_end = int(p["created_ts"]), window_end(p, now)
    b0 = p.get("below_sl_at_creation")
    armed = (b0 if b0 is not None else strategies.below_stop(mc0, sl)) == 0
    entry = None
    for c in cs:
        m = c[0]
        if m + 59 < t0:
            continue
        if m > t_end:
            break
        if armed and sl and c[3] * supply < sl:
            break   # the stop rule: under the stop after the proposal was made -> isteklo
        mc = c[4] * supply
        if z[0] <= mc <= z[1] and (not sl or mc > sl):
            entry = c
            break
    if entry is None:
        out["kind"] = "not_in_zone"
        return out
    t_in = max(int(entry[0]), t0)
    out.update(first_in_zone_ts=t_in, first_in_zone_mc=round(entry[4] * supply))
    if any(o - 1 <= t_in <= (c if c else now) + cooldown_s for o, c in rounds.get(p["token"], [])):
        out["kind"] = "skipped_range"
        return out
    if lcon is not None and user and _held_at(lcon, user, p["token"], t_in):
        out["kind"] = "skipped_held"
        return out
    t_end_sim = min(int(now), t_in + MISS_HORIZON_S)
    # 12.11. (Jure, točka 4): the minutes of prices the hypothetical lot is followed on (exit_sim's own walk); fewer
    # than 3 = its outcome is nepouzdano: kept as a missed entry, no outcome, in no outcome count or average
    from rangedca import missed as rmissed
    n_pts = sum(1 for c in cs if entry[0] < c[0] <= t_end_sim)
    if rmissed.unreliable(n_pts):
        out.update(kind="missed", n_points=n_pts, quality=rmissed.UNRELIABLE)
        return out
    first, gross, _m = outcomes.exit_sim(cs, entry[4], entry[0], r.get("exit_plan") or {}, supply, t_end_sim)
    cost = tcost.round_trip(float(p.get("size_sol") or 0.1) * (sol_usd or _sol_usd()), p.get("liq0") or r.get("liq0"))
    out.update(kind="missed", outcome=first, ret_pct=round((gross - cost) * 100, 2), n_points=n_pts)
    return out


def zone_misses(now=None, hours=ZONE_HOURS, path=None, con=None, econ=None, lcon=None, path_fn=None):
    """Every proposal made in the last `hours`: did the price come into its entry zone while it waited (status novo, or
    expired only because its source vanished: the rule now keeps it waiting), was there a paper entry (league.db
    proposal_trades), was it skipped (range_dca's round or cooldown on the demo account, another demo position), and
    for the missed ones the hypothetical outcome from the first in-zone price on the proposal's exit, net of
    trade/cost.round_trip. Prices: outcomes.path (proposals.db px, momentum.db snaps, events.db ticks, minute.db call
    candles, range.db snapshots and seed candles, hype.db token_pulse), read-only, no paid call. The range pause
    (range_flip) is not stored per minute: not part of the report."""
    from trade import settings
    from . import outcomes
    now = int(now or time.time())
    own = con is None
    con = con if con is not None else store.ro(path)
    own_l = lcon is None
    if lcon is None:
        try:
            from league import store as lstore
            lcon = sqlite3.connect(f"file:{lstore.DB}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            lcon = sqlite3.connect(":memory:")
    own_e = econ is None and path_fn is None
    if own_e:
        try:
            from events import store as estore
            econ = estore.ro()
        except Exception:  # noqa: BLE001
            econ = None
    try:
        ps = store.read(con, "created_ts >= ?", (now - hours * 3600,), order="id", limit=5000) if con is not None else []
        user = settings.PAPER_USER
        taken = _paper_entries(lcon, user)
        rounds = _range_rounds(lcon, user)
        try:
            from rangedca import rules
            cd = int(rules.RULES["cooldown_s"])
        except Exception:  # noqa: BLE001
            cd = 1200
        sol = _sol_usd()
        rows = []
        for p in ps:
            t1 = min(now, window_end(p, now) + MISS_HORIZON_S)
            cs = (path_fn(p["token"], int(p["created_ts"]) - 60, t1) if path_fn else
                  outcomes.path(p["token"], int(p["created_ts"]) - 60, t1, econ, con))
            rows.append(zone_miss_one(p, cs, now, taken, rounds, lcon, user, cd, sol))
    finally:
        if own and con is not None:
            con.close()
        if own_l:
            lcon.close()
        if own_e and econ is not None:
            econ.close()
    return summarize(rows, now, hours)


def _agg(rs):
    miss = [r for r in rs if r["kind"] == "missed" and not r.get("quality")]   # 12.11.: nepouzdano apart
    rets = [r["ret_pct"] for r in miss if r.get("ret_pct") is not None]
    return {"n": len(rs), **{k: sum(1 for r in rs if r["kind"] == k) for k in KINDS},
            "paper_outside_zone": sum(1 for r in rs if r["kind"] == "paper" and r.get("paper_in_zone") is False),
            "outcomes": {o: sum(1 for r in miss if r["outcome"] == o) for o in OUT_HR},
            "avg_ret_pct": round(sum(rets) / len(rets), 2) if rets else None,
            "unreliable": sum(1 for r in rs if r["kind"] == "missed" and r.get("quality"))}


def summarize(rows, now, hours=ZONE_HOURS):
    by = {}
    for r in rows:
        by.setdefault(r.get("strategy") or "?", []).append(r)
    miss = sorted([r for r in rows if r["kind"] == "missed"], key=lambda r: -(r["first_in_zone_ts"] or 0))
    return {"ts": int(now), "hours": hours, **_agg(rows), "per_strategy": {k: _agg(v) for k, v in sorted(by.items())},
            "list": [{k: r.get(k) for k in ("id", "token", "symbol", "strategy", "zone", "sl", "first_in_zone_ts",
                                            "first_in_zone_mc", "outcome", "ret_pct", "n_points", "quality")}
                     for r in miss[:MISS_LIST * 3]],
            "skipped": [{k: r.get(k) for k in ("id", "token", "symbol", "strategy", "kind", "zone", "first_in_zone_ts",
                                               "first_in_zone_mc")}
                        for r in rows if r["kind"] in ("skipped_range", "skipped_held")][:MISS_LIST * 3],
            "paper_outside": [{k: r.get(k) for k in ("id", "token", "symbol", "strategy", "zone", "sl", "paper_mcap")}
                              for r in rows if r["kind"] == "paper" and r.get("paper_in_zone") is False][:MISS_LIST * 3],
            "how": ("ulaz = prva minuta (zatvaranje) u zoni ulaza i iznad stopa dok je prijedlog čekao (novo, ili istekao "
                    "samo jer mu je nestao izvor); stop prije zone ga gasi ako je pri prijedlogu bio iznad stopa; ishod = "
                    "izlaz prijedloga (TP / SL / trailing / vrijeme) najviše 24 h, nakon trade/cost.round_trip; "
                    "preskočeno = range runda ili njen cooldown na demo računu, ili demo već drži token; "
                    "nepouzdano = manje od 3 minute s cijenom nakon ulaza: bez ishoda, nije u ishodima ni prosjeku")}


def zone_lines(rep):
    """The Render log block of zone_misses (one block: the first line, per strategy, the short list)."""
    if not rep:
        return []

    def pct(x):
        return f"{x:+.1f} %".replace(".", ",") if x is not None else "-"

    from rangedca import missed as rmissed

    def oc(o, n_unrel=0):   # 12.11. (Jure, točka 4): the nepouzdano ones are in no outcome, said how many
        return ", ".join([f"{OUT_HR[k]} {o.get(k, 0)}" for k in OUT_HR]
                         + ([rmissed.note(n_unrel)] if n_unrel else []))
    out = [f"prijedlozi kroz zonu bez paper ulaza ({rep['hours']} h): {rep['missed']} od {rep['n']}, ishod: "
           f"{oc(rep['outcomes'], rep.get('unreliable'))}, prosjek {pct(rep['avg_ret_pct'])} nakon troška; paper ulaz "
           f"{rep['paper']} (od toga "
           f"izvan zone ili ispod SL-a {rep.get('paper_outside_zone', 0)}), "
           f"{KIND_HR['skipped_range']} {rep['skipped_range']}, {KIND_HR['skipped_held']} {rep['skipped_held']}, "
           f"zona nije dosegnuta {rep['not_in_zone']}, bez cijena {rep['no_data']}"]
    per = [f"{strategies.HR.get(k, k)} {s['missed']} od {s['n']} ({oc(s['outcomes'], s.get('unreliable'))}, "
           f"{pct(s['avg_ret_pct'])})" for k, s in rep["per_strategy"].items() if s["n"]]
    if per:
        out.append("  po strategiji: " + "; ".join(per))
    for r in rep["list"][:MISS_LIST]:
        z = r.get("zone")
        out.append(f"  {r.get('symbol') or r['token'][:6]} ({strategies.HR.get(r.get('strategy'), r.get('strategy'))}) "
                   f"zona {strategies.zone_text(z)}, prvi u zoni {strategies._usd(r.get('first_in_zone_mc'))} -> "
                   + (f"{rmissed.UNRELIABLE}, {rmissed.detail(r.get('n_points'), '24 h')}" if r.get("quality") else
                      f"{OUT_HR.get(r.get('outcome'), r.get('outcome'))} {pct(r.get('ret_pct'))}"))
    return out


def ev_rows(now, mode, path=None, log=print):
    """events/evreport: build the day's report, log it, and return one ev_report row per strategy with proposals."""
    rep = daily(now, path)
    for ln in lines(rep):
        log(ln)
    rows = []
    for k, s in rep["per_strategy"].items():
        if not s["proposals"]:
            continue
        pp = (rep.get("paper") or {}).get(k) or {}
        rows.append({"flag": "proposals", "phase": mode, "part": f"prijedlozi:{k}", "n": s["proposals"],
                     "n_outcomes": s["measured"], "hit_rate": s["hit_rate"], "avg_pnl_pct": s["ev_pct"],
                     "ev_pct": s["ev_pct"], "max_dd_pct": None, "baseline_ev_pct": s["ev_expected_pct"],
                     "baseline_n": None, "delta_ev_pct": (round(s["ev_pct"] - s["ev_expected_pct"], 2)
                                                          if s["ev_pct"] is not None and s["ev_expected_pct"] is not None
                                                          else None),
                     "note": (f"kupljeno {s['bought']}, odbijeno {s['rejected']}, isteklo {s['expired']}; paper "
                              f"{pp.get('n', 0)} zatvorenih (EV {pp.get('ev_pct')}); osnovica = očekivani EV prijedloga"),
                     "proposal": None})
    return rows
