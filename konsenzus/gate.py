"""The real-money gate of the source consensus strategy (15.11.).

Real money (LEAGUE_USER, mirrored by run_trade.py) only when BOTH:
  1. the owner's switch pravi_novac_izvori is "live" (trade/settings, an owner switch: default off, only his tap on
     /pravi-trade turns it on; no owner order in code ever does);
  2. the best candidate's HOLDOUT (the untouched last 25 % of days of konsenzus/research) passes PROOF: n >= 30,
     EV >= +3 % per trade net of costs and stop slippage, the day-block bootstrap 90 % interval's low > 0, AND
     trade/edge.live_proof on the same results (the owner's rule D, the Student-t interval).
Everything else stays demo. The hard rules (kill switch, wallet / reserve, rug archive, MC >= 30k, bonded only,
liquidity >= 15k, the swap cost cap 6 %, one position per token, a server-side stop) are checked at the entry
(konsenzus/live) and again by run_trade on the real buy (_switch_hard) and trade/executor (IZVORI_CAPS).
"""
PROOF = {"n": 30, "ev_min_pct": 3.0, "ci_lo_min_pct": 0.0}
# the wallet universe is today's lists (konsenzus/research CAVEAT): a holdout made mostly of wallet entries also needs
# the demo account's own konsenzus result before real money
WALLET_SHARE_DEMO = 0.3
DEMO_N = 10
SWITCH = "pravi_novac_izvori"


def holdout_proof(rets, st):
    """(ok, why in Croatian) of the holdout results (fractions) and their stats (research.stats)."""
    from trade import edge
    st = st or {}
    n = st.get("n") or 0
    if n < PROOF["n"]:
        return False, f"holdout ima {n} tradeova, treba {PROOF['n']}"
    ev = st.get("ev_pct")
    if ev is None or ev < PROOF["ev_min_pct"]:
        return False, f"holdout EV {ev if ev is not None else '?'} % ispod +{PROOF['ev_min_pct']:g} %"
    lo = st.get("ci_lo_pct")
    if lo is None or lo <= PROOF["ci_lo_min_pct"]:
        return False, f"donja granica 90 % intervala (blok po danu) {lo} % nije iznad 0"
    ok, why, _s = edge.live_proof(rets or [])
    if not ok:
        return False, f"trade/edge dokaz nije prošao: {why}"
    return True, "dokaz prošao"


def switch_on(con=None):
    try:
        from trade import settings
        return settings.flag(SWITCH, con) == "live"
    except Exception:  # noqa: BLE001 - unreadable = off
        return False


def real_refusal(spec=None, con=None):
    """None when a konsenzus signal may also buy with REAL money now, else why not (Croatian). Never raises."""
    try:
        if not switch_on(con):
            return "prekidač pravi_novac_izvori je isključen"
        if spec is None:
            from konsenzus import store
            spec = store.best()
        if not spec:
            return "još nema izračuna kandidata (run_konsenzus.py)"
        if not spec.get("proof_ok"):
            return f"kandidat {spec.get('key')} nema dokaz na holdoutu: {spec.get('proof_why')}"
        if ((spec.get("holdout") or {}).get("wallet_share") or 0) >= WALLET_SHARE_DEMO:
            from konsenzus import live
            d = live.demo_stats()
            if (d.get("n") or 0) < DEMO_N or (d.get("ev_pct") is None or d["ev_pct"] <= 0):
                return (f"holdout je većinom novčanici (lista novčanika je današnja, optimistično): treba i demo "
                        f"{DEMO_N}+ zatvorenih s EV > 0 (sada {d.get('n') or 0}, EV {d.get('ev_pct')})")
        return None
    except Exception as e:  # noqa: BLE001 - an unreadable proof is no proof
        return f"dokaz se ne može pročitati ({type(e).__name__})"
