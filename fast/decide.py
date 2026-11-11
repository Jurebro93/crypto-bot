"""The decision of one fast_check (fast/checks.py results + the source's record).

    EV = P(TP) x TP - (1 - P) x SL - cost               TP +15 %, SL -10 % (the fast path's exits, trade/edge rule E);
                                                         cost = trade/cost.round_trip of the stake in the pool (the ONE
                                                         model, rule A; under $15k check d already failed)
    P, its 90 % interval and the EV interval: fast/estimate.py (11.11., Jure: "nikad 'nije izmjeren'"). The source's
    own sample (fast.db outcomes of the source, wallets/rang.py, the proposals bench for callers, the Autopilot record:
    the first with n >= 10) shrunk with K = 10 toward the strategy prior of its kind (pooled fast.db outcomes / bench /
    rang of the proven sources / demo copies, >= 20 outcomes, else no edge 48 %); n < 10 is "procjena, n izvora < 10".
    P x p_mult = trade/edge.modifiers (rule B: a 4x+ run-up from the first call P x 0.7 and size x 0.5, wash P x 0.5;
    never a block).
    size = min(the stake, the stake with <= 2 % slippage) x the volume factor x the size modifiers (trade/cost.size_sol).

Order (the first that applies):
  MC out of band            SKIP "cijena: MC $14.0M izvan raspona (30k–5M)" (checks.CFG mcap_min / mcap_max, env
                            FAST_MC_MIN / FAST_MC_MAX), before anything else: an API error elsewhere does not matter
  a check is "error"        CHECK_FAILED with the check's reason (retried by the worker; never a skip)
  a check is "fail"         SKIP "<check>: <rule and number>" (the first failing check in a-e order; the others listed);
                            check d also fails when the source wallet already sold after its buy ("izlazi")
  EV <= 0                   SKIP "EV ... ≤ 0 (P, n, origin, cost)" (11.11., the owner's consolidated rule: paper too
                            needs EV > 0; the old "paper whatever the EV while collecting n" is gone: a source with
                            n < 10 rides on its strategy's prior, and its outcomes are measured on every decision)
  proven source, EV >= +3 % BUY_LIVE = "KUPI (live-eligible)" (run_trade.PROOF on the source's closed results:
                            trade/edge.live_proof n >= 10, EV >= +3 %, the 90 % interval's lower bound > 0); only a
                            label: real money only through run_trade's proof / the owner's tap, paper mode trades it
                            on the demo account
  else EV > 0               BUY_PAPER = "KUPI (paper)" with the small stake PAPER_SOL (0.05 SOL demo): n < 10
                            ("procjena, n izvora < 10"), no live proof, or a proven source under +3 %
"""
import os

from trade import cost as tcost, edge

from . import estimate

TP, SL = edge.TP, edge.SL
K = estimate.K
BASE_MIN_N = estimate.BASE_MIN_N
PAPER_SOL = float(os.environ.get("FAST_PAPER_SOL", "0.05"))
ORDER = ("rug", "holders", "flow", "price", "source")


def prior(cost=None):
    """No edge: the P at which EV = 0 at the cheapest cost (the cost model's fee part, no impact)."""
    c = tcost.FEE_ROUND_TRIP if cost is None else cost
    return round((SL + c) / (TP + SL), 4)


PRIOR = prior()


def p_tp(hits, n, base, k=K):
    hits, n = max(0, int(hits or 0)), max(0, int(n or 0))
    return (min(hits, n) + k * base) / (n + k)


def ev(p, cost):
    return p * TP - (1 - p) * SL - cost


def base_for(kind, rates):
    """{"p", "n", "src"} of the kind's base rate (see the module text)."""
    hits, n = (rates or {}).get(kind) or (0, 0)
    if n >= BASE_MIN_N:
        return {"p": round(hits / n, 4), "n": n, "src": f"fast.db ishodi ({kind}, {hits}/{n} TP prije SL-a)"}
    return {"p": PRIOR, "n": 0, "src": f"prior bez prednosti ((SL + 2 %) / (TP + SL) = {PRIOR:.0%})"}


def _pct(x):
    return f"{x * 100:+.1f} %".replace(".", ",")


def band_fail(checks):
    """True when check d failed on the market-cap band (it decides before any API error elsewhere)."""
    c = checks.get("price") or {}
    return c.get("status") == "fail" and (c.get("values") or {}).get("band") == "out"


def decide(checks, q, rates=None, live_sol=0.1, paper_sol=PAPER_SOL, priors=None, src_rate=None):
    """{"decision", "label", "reason", "key" (the check or rule that decided), "ev_pct", "p_tp", "cost_pct",
    "size_sol", "base", "est" (fast/estimate.stored: P, its 90 % interval, n, origin, the EV interval), "lag",
    "fails", "errors"}. priors: fast/estimate.priors() of the worker (else the fast.db rates alone); src_rate:
    (hits, n) of this source's measured fast.db outcomes."""
    from . import sources
    errors = [k for k in ORDER if (checks.get(k) or {}).get("status") == "error"]
    fails = [k for k in ORDER if (checks.get(k) or {}).get("status") == "fail"]
    q = q or {}
    price = (checks.get("price") or {}).get("values") or {}
    flow = (checks.get("flow") or {}).get("values") or {}
    cost = price.get("cost_pct")
    cost = cost / 100 if cost is not None else None
    base = base_for(q.get("kind"), rates)
    # 11.11. (owner's rule B): the tags of checks c / d change P and the size, never block (X is unknown here: the
    # run-up reduction applies)
    mods = edge.modifiers(runup_x=price.get("runup_x"), x_score=None, buy_share_5m=flow.get("buy_share_5m"),
                          wash="wash" in (flow.get("tags") or []),   # 11.11.: a dump after a pump (check a), P x 0.7
                          dump=((checks.get("rug") or {}).get("values") or {}).get("dump"))
    p = p_tp(q.get("hits"), q.get("n"), base["p"]) * mods["p_mult"]
    e = ev(p, cost) if cost is not None else None
    # 11.11. (fast/estimate, Jure: "nikad 'nije izmjeren'"): P from the source's sample or, under n 10, its strategy's
    # prior (the fast.db base rate above is the first link of that prior), its Wilson 90 % interval, EV and its interval
    kind = q.get("kind")
    pri = estimate.prior_for(kind, priors, rates)
    base = {"p": pri["p"], "n": pri["n"], "src": pri["src"], "strategy": pri.get("strategy")}
    est = estimate.estimate(estimate.sample(kind, q, src_rate), pri, mods["p_mult"], cost)
    p, e = est["p"], est["ev"]
    st = estimate.stored(est)
    out = {"ev_pct": round(e * 100, 2) if e is not None else None, "p_tp": round(p, 4),
           "cost_pct": round(cost * 100, 2) if cost is not None else None, "base": base, "fails": fails,
           "errors": errors, "size_sol": None, "modifiers": mods, "est": st,
           "lag": {"pct": price.get("from_entry_pct"), "txt": price.get("lag_txt"),
                   "sold": bool(price.get("src_sold"))}}
    tail = (f" ({estimate.p_text(st)}; 90 %: {_pct(est['ev_lo'])} do {_pct(est['ev_hi'])}"
            + (f"; × {mods['p_mult']:g}".replace(".", ",") if mods["p_mult"] < 1 else "")
            + f"; trošak {cost * 100:.1f} %)".replace(".", ",") if cost is not None else "")

    def done(decision, key, reason, size_sol=None):
        return dict(out, decision=decision, label=estimate.label(decision), key=key, reason=reason, size_sol=size_sol)

    def size(sol):
        """11.11. (owner's rule C): min(the stake, the 2 % slippage stake) x volume factor x size modifiers."""
        return round(tcost.size_sol(sol, price.get("liq"), price.get("sol_usd"), price.get("vol_h1"),
                                    mods["size_mult"]), 6)
    if band_fail(checks):   # 11.11. (Jure, 4CxjZy at $14M): out of our band, whatever else happened
        more = [checks[k]["text"] for k in fails if k != "price"]
        return done("SKIP", "price", checks["price"]["text"] + (f" (i još: {'; '.join(more)})" if more else ""))
    if errors:
        more = [checks[k]["text"] for k in fails]
        return done("CHECK_FAILED", errors[0],
                    "; ".join(checks[k]["text"] for k in errors) + (f" (uz to: {'; '.join(more)})" if more else ""))
    if fails:
        more = [checks[k]["text"] for k in fails[1:]]
        return done("SKIP", fails[0], checks[fails[0]]["text"] + (f" (i još: {'; '.join(more)})" if more else ""))
    if e is None:
        return done("SKIP", "price", "cijena: trošak po likvidnosti nepoznat")
    P = sources.proof_rule()
    if e <= 0:   # 11.11. (the owner's consolidated rule): paper too needs EV > 0
        why = "" if q.get("proof") or not q.get("proof_why") else f"; izvor bez dokaza ({q.get('proof_why')})"
        return done("SKIP", "ev", f"EV {_pct(e)} ≤ 0{tail}{why}")
    if q.get("proof") and e >= P["ev_min"] - 1e-12:   # live-eligible: this signal's EV >= +3 % too (rule D)
        return done("BUY_LIVE", "ev", f"dokazan izvor, EV {_pct(e)}{tail}", size(live_sol))
    if est["label"]:
        why = f"{est['label']}: paper ulog {f'{paper_sol:g}'.replace('.', ',')} SOL"
    elif q.get("proof"):
        why = f"dokazan izvor, ali EV < {_pct(P['ev_min'])} za pravi novac: paper"
    else:
        why = f"izvor bez dokaza za pravi novac ({q.get('proof_why') or 'nema dokaza'}): paper"
    return done("BUY_PAPER", "explore" if est["label"] else "ev", f"EV {_pct(e)}{tail}; {why}", size(paper_sol))
