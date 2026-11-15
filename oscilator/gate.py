"""The real-money gate of the oscillator scalp (15.11.; real money: NOT now).

Real money (LEAGUE_USER, mirrored by run_trade.py) only when ALL of:
  1. the owner's switch pravi_novac_oscilator is "live" (trade/settings OWNER_SWITCHES: default off, only his own tap
     on /pravi-trade; no owner order in code turns it on);
  2. the walk-forward proof at the REAL size (REAL["size_sol"], default 0.1 SOL) and the demo target (1 $ net):
       n >= PROOF n (100 trades of the top-K picks, out of sample: picked on day D, traded on D+1),
       EV per trade net of the real costs > 0 AND the bootstrap 90 % interval's low (by token-day) > 0,
       $ a day for the K tokens > 0;
  3. the demo account's own oscillator trades: >= PROOF demo_n (50) closed with EV > 0 at the real cost model.
Caps of the real account (REAL, trade/config.json "pravi_novac_oscilator" may only lower them): size 0.1 SOL, at most
3 open, 30 buys a Zagreb day, a day's loss of 0.3 SOL stops the entries (oscilator/live.enter); run_trade asks
real_refusal() again on every real buy and its own hard rules / trade/executor's caps hold on top.
"""
SWITCH = "pravi_novac_oscilator"
PROOF = {"n": 100, "ev_min_pct": 0.0, "ci_lo_min_pct": 0.0, "usd_day_min": 0.0, "demo_n": 50, "demo_ev_min_pct": 0.0}
REAL = {"size_sol": 0.1, "max_open": 3, "max_buys_day": 30, "max_loss_day_sol": 0.3}


def real_caps(cfg=None):
    """REAL, each the smaller of the code's and trade/config.json "pravi_novac_oscilator"'s."""
    if cfg is None:
        try:
            from trade import executor
            cfg = executor.load_config()
        except Exception:  # noqa: BLE001 - unreadable: the code's caps
            cfg = {}
    own = (cfg or {}).get(SWITCH) if isinstance((cfg or {}).get(SWITCH), dict) else {}
    out = {}
    for k, v in REAL.items():
        try:
            out[k] = min(type(v)(own[k]), v) if own.get(k) is not None else v
        except (TypeError, ValueError):
            out[k] = v
    return out


def switch_on(con=None):
    try:
        from trade import settings
        return settings.flag(SWITCH, con) == "live"
    except Exception:  # noqa: BLE001 - unreadable = off
        return False


def wf_proof(proof=None, size_sol=None, target_usd=None):
    """(ok, why in Croatian, the numbers) of the walk-forward at the real size."""
    from oscilator import live, store
    p = proof if proof is not None else store.proof()
    s = REAL["size_sol"] if size_sol is None else size_sol
    tg = live.DEMO_TARGET_USD if target_usd is None else target_usd
    x = ((p or {}).get("sizes") or {}).get(f"{s:g}@{tg:g}")
    if not x:
        return False, f"još nema walk-forwarda za {s:g} SOL / {tg:g} $ (run_oscilator.py)", None
    n = x.get("n") or 0
    if n < PROOF["n"]:
        return False, f"walk-forward ima {n} tradeova, treba {PROOF['n']}", x
    ev = x.get("ev_pct")
    if ev is None or ev <= PROOF["ev_min_pct"]:
        return False, f"walk-forward EV {ev} % po tradeu nije iznad 0", x
    lo = (x.get("ci90_ev_pct") or [None])[0]
    if lo is None or lo <= PROOF["ci_lo_min_pct"]:
        return False, f"donja granica 90 % intervala {lo} % nije iznad 0", x
    if (x.get("usd_day") or 0) <= PROOF["usd_day_min"]:
        return False, f"$ dnevno {x.get('usd_day')} nije iznad 0", x
    return True, "walk-forward dokaz prošao", x


def demo_proof(stats=None):
    from oscilator import live
    d = stats if stats is not None else live.demo_stats()
    if (d.get("n") or 0) < PROOF["demo_n"]:
        return False, f"demo ima {d.get('n') or 0} zatvorenih, treba {PROOF['demo_n']}"
    if d.get("ev_pct") is None or d["ev_pct"] <= PROOF["demo_ev_min_pct"]:
        return False, f"demo EV {d.get('ev_pct')} % (pravi trošak) nije iznad 0"
    return True, "demo dokaz prošao"


def real_refusal(con=None, proof=None, stats=None):
    """None when an oscillator entry may also buy with REAL money now, else why not (Croatian). Never raises."""
    try:
        if not switch_on(con):
            return f"prekidač {SWITCH} je isključen"
        ok, why, _x = wf_proof(proof)
        if not ok:
            return why
        ok, why = demo_proof(stats)
        if not ok:
            return why
        return None
    except Exception as e:  # noqa: BLE001 - an unreadable proof is no proof
        return f"dokaz se ne može pročitati ({type(e).__name__})"
