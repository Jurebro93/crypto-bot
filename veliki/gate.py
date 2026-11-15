"""The real-money gate of the big-token range (15.11.; real money: NOT now).

Real money (LEAGUE_USER, mirrored by run_trade.py) only when ALL of:
  1. the owner's switch pravi_novac_veliki is "live" (trade/settings OWNER_SWITCHES: default off, only his own tap on
     /pravi-trade; no owner order in code turns it on);
  2. the proof (PROOF), by default the walk-forward HOLDOUT of the rule "bez_padova" at the REAL size (0.1 SOL):
       n >= 40 trades out of sample (configs picked on older days, traded on newer), EV per trade net of the real
       costs > 0 AND the bootstrap 90 % interval's low (by token-day) > 0;
     the owner may later accept the demo's own record instead (trade/config.json "pravi_novac_veliki": {"dokaz":
     "demo"}): then >= 40 closed demo trades of this strategy with EV > 0 and the 90 % interval's low > 0;
  3. BTC known and no BTC crash active (rule.crash_hours: the same definition the backtest excludes).
Caps (REAL; trade/config.json "pravi_novac_veliki" may LOWER them, and set size_sol up to MAX_SIZE_SOL 0.5): 0.1 SOL a
trade, at most 5 open, a day's loss of 0.3 SOL stops the entries, one position a token. run_trade asks real_refusal()
again on every real buy and its hard rules hold on top (kill switch trade/STOP, the wallet reserve, the rug archive,
a stop on the server, the swap's cost cap max_cost_pct 6 %).
"""
SWITCH = "pravi_novac_veliki"
PROOF = {"n": 40, "ev_min_pct": 0.0, "ci_lo_min_pct": 0.0, "demo_n": 40}
REAL = {"size_sol": 0.1, "max_open": 5, "max_buys_day": 20, "max_loss_day_sol": 0.3}
MAX_SIZE_SOL = 0.5


def _own(cfg=None):
    if cfg is None:
        try:
            from trade import executor
            cfg = executor.load_config()
        except Exception:  # noqa: BLE001 - unreadable: the code's caps
            cfg = {}
    own = (cfg or {}).get(SWITCH)
    return own if isinstance(own, dict) else {}


def real_caps(cfg=None):
    """REAL with the owner's trade/config.json "pravi_novac_veliki": size_sol up to MAX_SIZE_SOL, the rest only lower."""
    own = _own(cfg)
    out = {}
    for k, v in REAL.items():
        try:
            if own.get(k) is None:
                out[k] = v
            elif k == "size_sol":
                out[k] = max(0.01, min(float(own[k]), MAX_SIZE_SOL))
            else:
                out[k] = min(type(v)(own[k]), v)
        except (TypeError, ValueError):
            out[k] = v
    return out


def proof_mode(cfg=None):
    return "demo" if str(_own(cfg).get("dokaz") or "").lower() == "demo" else "walk"


def switch_on(con=None):
    try:
        from trade import settings
        return settings.flag(SWITCH, con) == "live"
    except Exception:  # noqa: BLE001 - unreadable = off
        return False


def wf_proof(proof=None, size_sol=None):
    """(ok, why in Croatian, the numbers) of the walk-forward holdout at the real size."""
    from veliki import store
    p = proof if proof is not None else store.proof()
    s = REAL["size_sol"] if size_sol is None else size_sol
    x = ((p or {}).get("sizes") or {}).get(f"{s:g}")
    if not x:
        # the size the owner chose may lie between the backtest's sizes: the nearest smaller one (costlier) decides
        have = sorted(float(k) for k in ((p or {}).get("sizes") or {}))
        lower = [k for k in have if k <= s]
        x = ((p or {}).get("sizes") or {}).get(f"{lower[-1]:g}") if lower else None
    if not x:
        return False, f"još nema walk-forwarda za {s:g} SOL (run_veliki.py)", None
    n = x.get("n") or 0
    if n < PROOF["n"]:
        return False, f"holdout ima {n} tradeova, treba {PROOF['n']}", x
    ev = x.get("ev_pct")
    if ev is None or ev <= PROOF["ev_min_pct"]:
        return False, f"holdout EV {ev} % po tradeu nije iznad 0", x
    lo = (x.get("ci90_ev_pct") or [None])[0]
    if lo is None or lo <= PROOF["ci_lo_min_pct"]:
        return False, f"donja granica 90 % intervala {lo} % nije iznad 0", x
    return True, "walk-forward holdout prošao", x


def demo_proof(stats=None):
    from veliki import live
    d = stats if stats is not None else live.demo_stats()
    if (d.get("n") or 0) < PROOF["demo_n"]:
        return False, f"demo ima {d.get('n') or 0} zatvorenih, treba {PROOF['demo_n']}"
    if d.get("ev_pct") is None or d["ev_pct"] <= 0:
        return False, f"demo EV {d.get('ev_pct')} % (pravi trošak) nije iznad 0"
    if d.get("ci90_lo_pct") is None or d["ci90_lo_pct"] <= 0:
        return False, f"demo donja granica 90 % intervala {d.get('ci90_lo_pct')} % nije iznad 0"
    return True, "demo dokaz prošao"


def btc_refusal(now=None):
    from veliki import live
    st = live.btc_state(now)
    if not st.get("known"):
        return "BTC cijena po satu nepoznata: bez pravog novca"
    if st.get("crash"):
        return "BTC pada (4 h <= -3 % ili 24 h <= -5 %): bez pravog novca"
    return None


def real_refusal(con=None, proof=None, stats=None, cfg=None, now=None):
    """None when a big-token range entry may also buy with REAL money now, else why not (Croatian). Never raises."""
    try:
        if not switch_on(con):
            return f"prekidač {SWITCH} je isključen"
        if proof_mode(cfg) == "demo":
            ok, why = demo_proof(stats)
        else:
            ok, why, _x = wf_proof(proof, real_caps(cfg)["size_sol"])
        if not ok:
            return why
        return btc_refusal(now)
    except Exception as e:  # noqa: BLE001 - an unreadable proof is no proof
        return f"dokaz se ne može pročitati ({type(e).__name__})"
