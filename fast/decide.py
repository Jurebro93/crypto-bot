"""The decision of one fast_check (fast/checks.py results + the source's record).

    EV = P(TP) x TP - (1 - P) x SL - cost               TP +15 %, SL -10 % (the fast path's exits, trade/edge rule E);
                                                         cost = trade/cost.round_trip of the stake in the pool (the ONE
                                                         model, rule A; under $15k check d already failed)
    P = (hits + K x base) / (n + K) x p_mult             K = 10: the source's own record (hits of n closed) shrunk
                                                         toward the base rate of its kind; with n < 10 the base rate
                                                         weighs more than the source, with n >= 10 the source does;
                                                         p_mult = trade/edge.modifiers (rule B: a 4x+ run-up from the
                                                         first call P x 0.7 and size x 0.5, wash P x 0.5; never a block)
    base = TP-first rate of the kind's measured signals in fast.db (outcomes.base_rates, >= BASE_MIN_N of them in 30
           days), else the documented prior: no edge = the break-even P at the cheapest cost (the fee part of the cost
           model, no impact), (SL + 2 %) / (TP + SL) = 48 %; an unmeasured kind never looks good by itself.
    size = min(the stake, the stake with <= 2 % slippage) x the volume factor x the size modifiers (trade/cost.size_sol).


Order (the first that applies):
  a check is "error"        CHECK_FAILED with the check's reason (retried by the worker; never a skip)
  a check is "fail"         SKIP "<check>: <rule and number>" (the first failing check in a-e order; the others listed)
  proven source             run_trade.PROOF (11.11. owner's rule D, trade/edge.live_proof on the source's closed
                            results: n >= 10, EV >= +3 %, the 90 % interval's lower bound > 0; no win-rate rule;
                            fast/sources.has_proof): this signal's EV >= +3 % -> BUY_LIVE (the trade settings' stake),
                            EV > 0 -> BUY_PAPER, else SKIP "EV ... <= 0"
  source still collecting   fewer closed than PROOF's 10: BUY_PAPER with the small stake PAPER_SOL (0.05 SOL demo),
                            whatever the EV: the paper trade is how its proof builds itself (Jure, point 4)
  measured, not proven      EV > 0 -> BUY_PAPER (small stake; paper: EV > 0 to collect n), else SKIP "izvor bez dokaza
                            ... i EV <= 0"
"""
import os

from trade import cost as tcost, edge

TP, SL = edge.TP, edge.SL
K = 10
BASE_MIN_N = 20
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


def decide(checks, q, rates=None, live_sol=0.1, paper_sol=PAPER_SOL):
    """{"decision", "reason", "key" (the check or rule that decided), "ev_pct", "p_tp", "cost_pct", "size_sol",
    "base", "fails", "errors"}."""
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
                          wash="wash" in (flow.get("tags") or []))
    p = p_tp(q.get("hits"), q.get("n"), base["p"]) * mods["p_mult"]
    e = ev(p, cost) if cost is not None else None
    out = {"ev_pct": round(e * 100, 2) if e is not None else None, "p_tp": round(p, 4),
           "cost_pct": round(cost * 100, 2) if cost is not None else None, "base": base, "fails": fails,
           "errors": errors, "size_sol": None, "modifiers": mods}
    tail = (f" (P {p:.0%} iz {q.get('hits') or 0}/{q.get('n') or 0}, baza {base['p']:.0%}"
            + (f", × {mods['p_mult']:g}" if mods["p_mult"] < 1 else "") + f", trošak {cost * 100:.1f} %)"
            if cost is not None else "")

    def size(sol):
        """11.11. (owner's rule C): min(the stake, the 2 % slippage stake) x volume factor x size modifiers."""
        return round(tcost.size_sol(sol, price.get("liq"), price.get("sol_usd"), price.get("vol_h1"),
                                    mods["size_mult"]), 6)
    if errors:
        more = [checks[k]["text"] for k in fails]
        return dict(out, decision="CHECK_FAILED", key=errors[0],
                    reason="; ".join(checks[k]["text"] for k in errors) + (f" (uz to: {'; '.join(more)})" if more else ""))
    if fails:
        more = [checks[k]["text"] for k in fails[1:]]
        return dict(out, decision="SKIP", key=fails[0],
                    reason=checks[fails[0]]["text"] + (f" (i još: {'; '.join(more)})" if more else ""))
    if e is None:
        return dict(out, decision="SKIP", key="price", reason="cijena: trošak po likvidnosti nepoznat")
    P = sources.proof_rule()
    if q.get("proof"):
        if e >= P["ev_min"] - 1e-12:   # live: this signal's EV >= +3 % too (rule D)
            return dict(out, decision="BUY_LIVE", key="ev", size_sol=size(live_sol),
                        reason=f"dokazan izvor, EV {_pct(e)}{tail}")
        if e > 0:
            return dict(out, decision="BUY_PAPER", key="ev", size_sol=size(paper_sol),
                        reason=f"dokazan izvor, ali EV {_pct(e)} < {_pct(P['ev_min'])} za pravi novac{tail}: paper")
        return dict(out, decision="SKIP", key="ev", reason=f"EV {_pct(e)} ≤ 0{tail}")
    if int(q.get("closed") or 0) < P["closed"]:
        return dict(out, decision="BUY_PAPER", key="explore", size_sol=size(paper_sol),
                    reason=(f"izvor bez dokaza (zatvorenih {int(q.get('closed') or 0)} od {P['closed']}): paper ulog "
                            f"{f'{paper_sol:g}'.replace('.', ',')} SOL da skupi n; EV {_pct(e)}{tail}"))
    if e > 0:
        return dict(out, decision="BUY_PAPER", key="ev", size_sol=size(paper_sol),
                    reason=f"izvor bez dokaza ({q.get('proof_why')}), EV {_pct(e)}{tail}: paper")
    return dict(out, decision="SKIP", key="ev", reason=f"izvor bez dokaza ({q.get('proof_why')}) i EV {_pct(e)} ≤ 0{tail}")
