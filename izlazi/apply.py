"""The learned exit of an open position (league/exitplan.quick_cover asks here when it sets the plan of a new
automatic position).

Which source a position belongs to (keys_for), most specific first:
  (follow kind, follow target)     a copy (league follows: wallet address, KOL handle, crew "a,b,tg:c")
  ("strategy", name)               fast | proposals | insider | copy | zadnjih5 | simianx | ostalo (strategy_of)
  (follow kind, "*")               every source of that kind (the prior the source's rule is shrunk toward)
  ("*", "*")                       everything
Demo (PAPER_USER): the first key with a learned row (n >= izlazi/learn.MIN_N, or a row shrunk toward its prior) -
demo is where we learn. Real money (LEAGUE_USER, only while pravi_novac_sve is on): a row only when it is proven out
of sample (izlazi/store.proven: n_out >= 8, EV out of sample >= default + 1 point, its interval not entirely under the
default); a source whose OWN row has n_out >= 8 and is not proven keeps the default (its own evidence says no); a
source without enough evidence of its own falls back to the next key. Otherwise today's default ("brzi profit").

The plan (plan_for) is set_plan's input, copied at open time: later learning never changes an open position. Its stop
is never wider than the owner's sl_default (league/exitplan.sl_floor), nor is the catastrophic stop inside the grace.
"""
import json

from izlazi import sim, store

LEARNED_TAG = "naučen izlaz"
LIQ_FLOOR = 0.5          # during and after the grace: the pool under half of the entry's = a rug flag, out at once
NO_LEARN = ("momentum", "range lot", "ručno", "Grok auto", "DCA")   # their own exits (or the owner's) stay


def strategy_of(source, follow=None):
    """The automatic strategy of a lot by its source text (league trades.source) and follow; None for the owner's
    own, Grok's, range and DCA lots."""
    s = (source or "").strip()
    if not s or s.startswith(("ručno", "Grok auto", "range lot", "DCA")):
        return None
    if s.startswith("momentum"):
        return "momentum"
    if s.startswith("fast path") or s.endswith("(fast)"):
        return "fast"
    if s.startswith("prijedlog"):
        return "proposals"
    if s.startswith("simianx"):
        return "simianx"
    f = follow or {}
    if str(f.get("label") or "").startswith("insajder"):
        return "insider"
    ex = f.get("exit") if isinstance(f.get("exit"), dict) else {}
    if ex.get("src") == "zadnjih5":
        return "zadnjih5"
    if s.startswith("copy"):
        return "copy"
    return "ostalo"


def follow_of(con, fid):
    """{kind, target, label, exit} of a league follow, None."""
    if not fid:
        return None
    try:
        r = con.execute("SELECT kind, target, label, exit FROM follows WHERE id=?", (fid,)).fetchone()
    except Exception:  # noqa: BLE001 - no follows table (a bare database)
        return None
    if not r:
        return None
    try:
        ex = json.loads(r[3] or "{}")
    except ValueError:
        ex = {}
    return {"kind": r[0], "target": r[1], "label": r[2], "exit": ex}


def keys_for(con, lots):
    """[(source_kind, source_id)] of a position's lots, most specific first (see the module text); [] for a position
    whose exits are its own (NO_LEARN)."""
    if not lots:
        return []
    t = lots[-1]
    src = t.get("source") or ""
    if any(str(x.get("source") or "").startswith(NO_LEARN) for x in lots):
        return []
    f = follow_of(con, t.get("follow_id"))
    strat = strategy_of(src, f)
    if strat is None or strat == "momentum":
        return []
    out = []
    if f and f.get("kind") in ("wallet", "kol", "ekipa") and f.get("target"):
        out.append((f["kind"], f["target"]))
    out.append(("strategy", strat))
    if f and f.get("kind") in ("wallet", "kol", "ekipa"):
        out.append((f["kind"], "*"))
    out.append(("*", "*"))
    return out


def _norm(sid):
    return str(sid or "").strip().lstrip("@").lower()


def lookup(rows, k):
    """The row of key k; an influencer's handle without '@' and case (a follow may be typed '@Name')."""
    r = rows.get(k)
    if r is None and k[0] == "kol" and k[1] != "*":
        want = _norm(k[1])
        r = next((v for (kind, sid), v in rows.items() if kind == "kol" and _norm(sid) == want), None)
    return r


def choose(rows, keys, real, now=None):
    """(row, key, why) of the learned row a position takes, or (None, None, why)."""
    if not rows or not keys:
        return None, None, "nema naučenih izlaza"
    for i, k in enumerate(keys):
        r = lookup(rows, k)
        if r is None or not store.fresh_row(r, now):
            continue
        if not real:
            return r, k, "demo: naučeno"
        ok, why = store.proven(r)
        if ok:
            return r, k, "dokazano van uzorka"
        if i == 0 and (r.get("n_out") or 0) >= store.PROOF_N_OUT:
            return None, k, f"vlastiti dokaz izvora ne prolazi ({why}): zadano"
    return None, None, "pravi novac: nijedan naučeni izlaz nije dokazan van uzorka, zadano"


def key_words(k):
    kind, sid = k
    if kind == "*":
        return "svi izvori"
    if sid == "*":
        return f"svi ({kind})"
    short = f"{sid[:4]}…{sid[-4:]}" if len(sid) > 24 and " " not in sid and "," not in sid else sid[:40]
    return f"{kind} {short}"


def plan_for(con, user, lots, liq=None, rows=None, now=None, floor=None):
    """(plan as league/exitplan.set_plan takes it, info) of `user`'s new position from its learned row, or
    (None, why). info: {key, row, proof, words} for the log."""
    from league import exitplan
    from trade import cost, settings as ts
    real = user == ts.LEAGUE_USER
    if real:
        try:
            if not ts.pravi_novac_sve():
                return None, "pravi novac bez prekidača pravi_novac_sve: zadano"
        except Exception:  # noqa: BLE001
            return None, "prekidač pravi_novac_sve nečitljiv: zadano"
    elif user != ts.PAPER_USER:
        return None, "nije račun Autopilota"
    keys = keys_for(con, lots)
    if not keys:
        return None, "izvor ima vlastite izlaze"
    rows = store.load() if rows is None else rows
    row, key, why = choose(rows, keys, real, now)
    if row is None:
        return None, why
    avg = exitplan._avg(lots)
    if not avg:
        return None, "pozicija bez ulazne cijene"
    # the mirror rule is applied only when the row could judge it (its entries had the source's sales); else the
    # mirror sale stays as it is today
    judged = bool((row.get("stats") or {}).get("mirror_judged"))
    p = sim.canon(sim.from_dict(row["params"]))
    size = sum(t.get("size_usd") or 0 for t in lots) or None
    liq0 = liq or exitplan._liq_of(lots)
    rt = cost.round_trip(size, liq0) * 100
    floor = exitplan.sl_floor() if floor is None else floor
    sl = min(float(p.sl), float(floor))
    tp1 = round(p.tp1 + rt, 2)
    plan = {"accounts": [user], "take_profits": [{"at_pct": tp1, "sell_share": float(p.share)}],
            "stop": {"at_pct": -sl},
            "grace": {"min": float(p.grace), "cat_pct": min(sim.CAT_STOP, float(floor)), "liq_floor": LIQ_FLOOR,
                      "liq0": round(liq0) if liq0 else None},
            "mirror": bool(p.mirror) if judged else True}
    if p.share < 0.999:
        plan["breakeven_after_tp1"] = True
        if p.trail:
            plan["trailing"] = {"activate_pct": tp1, "trail_pct": float(p.trail)}
    if p.tmax < 1440:
        plan["time_stop"] = {"after_min": float(p.tmax), "if_pnl_below_pct": 1000}
    ok = store.proven(row)[0]
    info = {"key": list(key), "src": key_words(key), "ev_out": row.get("ev_out"), "default_ev_out":
            row.get("default_ev_out"), "n": row.get("n"), "n_out": row.get("n_out"), "proof": ok,
            "learned_ts": row.get("ts"), "params": sim.as_dict(p), "sl_capped": sl < p.sl - 1e-9}
    plan["learned"] = info
    w = words(key, p._replace(sl=sl), row)
    plan["reason"] = w[:300]
    info["words"] = w
    return plan, info


def words(key, p, row):
    """"izlaz naučen: wallet Ab12…yz89 SL −30 %, grace 15 min …, TP1 +15 % neto …, EV van uzorka +3,10 % vs default
    +0,40 % (n 41, van uzorka 12)"."""
    ev, dv = row.get("ev_out"), row.get("default_ev_out")
    evs = (f", EV van uzorka {ev:+.2f} % vs default {dv:+.2f} %".replace(".", ",") if ev is not None and dv is not None
           else ", EV van uzorka nepoznat (premalo ulaza: rubni prior)")
    return (f"izlaz naučen: {key_words(key)} {sim.words(p)}{evs} (n {row.get('n') or 0}, van uzorka "
            f"{row.get('n_out') or 0})")

