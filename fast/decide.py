"""The decision of one fast_check (fast/checks.py results + the source's record).

    EV = P(TP) x TP - (1 - P) x SL - cost(liq)          TP +15 %, SL -10 % (the fast path's exits), cost by the pool's
                                                         liquidity: 3 % above $50k, 5 % $25-50k, 8 % under $25k
                                                         (proposals/build.cost_for; under $20k check d already failed)
    P = (hits + K x base) / (n + K)                      K = 10: the source's own record (hits of n closed) shrunk
                                                         toward the base rate of its kind; with n < 10 the base rate
                                                         weighs more than the source, with n >= 10 the source does
    base = TP-first rate of the kind's measured signals in fast.db (outcomes.base_rates, >= BASE_MIN_N of them in 30
           days), else the documented prior: no edge = the break-even P at the cheapest cost, (SL + 3 %) / (TP + SL)
           = 52 %; an unmeasured kind never looks good by itself.

Order (the first that applies):
  a check is "error"        CHECK_FAILED with the check's reason (retried by the worker; never a skip)
  a check is "fail"         SKIP "<check>: <rule and number>" (the first failing check in a-e order; the others listed)
  proven source             run_trade.PROOF (closed >= 10, PnL > 0, >= 40 % winners; fast/sources.has_proof):
                            EV > 0 -> BUY_LIVE (the trade settings' stake), else SKIP "EV ... <= 0"
  source still collecting   fewer closed than PROOF's 10: BUY_PAPER with the small stake PAPER_SOL (0.05 SOL demo),
                            whatever the EV: the paper trade is how its proof builds itself (Jure, point 4)
  measured, not proven      EV > 0 -> BUY_PAPER (small stake), else SKIP "izvor bez dokaza ... i EV <= 0"
"""
import os

TP, SL = 0.15, 0.10
K = 10
BASE_MIN_N = 20
PAPER_SOL = float(os.environ.get("FAST_PAPER_SOL", "0.05"))
ORDER = ("rug", "holders", "flow", "price", "source")


def prior(cost=0.03):
    """No edge: the P at which EV = 0 at the cheapest cost."""
    return round((SL + cost) / (TP + SL), 4)


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
    return {"p": PRIOR, "n": 0, "src": f"prior bez prednosti ((SL + 3 %) / (TP + SL) = {PRIOR:.0%})"}


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
    cost = price.get("cost_pct")
    cost = cost / 100 if cost is not None else None
    base = base_for(q.get("kind"), rates)
    p = p_tp(q.get("hits"), q.get("n"), base["p"])
    e = ev(p, cost) if cost is not None else None
    out = {"ev_pct": round(e * 100, 2) if e is not None else None, "p_tp": round(p, 4),
           "cost_pct": round(cost * 100, 1) if cost is not None else None, "base": base, "fails": fails,
           "errors": errors, "size_sol": None}
    tail = (f" (P {p:.0%} iz {q.get('hits') or 0}/{q.get('n') or 0}, baza {base['p']:.0%}, trošak "
            f"{cost * 100:.0f} %)" if cost is not None else "")
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
        if e > 0:
            return dict(out, decision="BUY_LIVE", key="ev", size_sol=float(live_sol),
                        reason=f"dokazan izvor, EV {_pct(e)}{tail}")
        return dict(out, decision="SKIP", key="ev", reason=f"EV {_pct(e)} ≤ 0{tail}")
    if int(q.get("closed") or 0) < P["closed"]:
        return dict(out, decision="BUY_PAPER", key="explore", size_sol=float(paper_sol),
                    reason=(f"izvor bez dokaza (zatvorenih {int(q.get('closed') or 0)} od {P['closed']}): paper ulog "
                            f"{f'{paper_sol:g}'.replace('.', ',')} SOL da skupi n; EV {_pct(e)}{tail}"))
    if e > 0:
        return dict(out, decision="BUY_PAPER", key="ev", size_sol=float(paper_sol),
                    reason=f"izvor bez dokaza ({q.get('proof_why')}), EV {_pct(e)}{tail}: paper")
    return dict(out, decision="SKIP", key="ev", reason=f"izvor bez dokaza ({q.get('proof_why')}) i EV {_pct(e)} ≤ 0{tail}")
