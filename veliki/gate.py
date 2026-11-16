"""The real-money gate of the big-token range (15.11.; real money: NOT now).

Real money (LEAGUE_USER, mirrored by run_trade.py) only when ALL of:
  1. the owner's switch pravi_novac_veliki is "live" (trade/settings OWNER_SWITCHES: default off, only his own tap on
     /pravi-trade; no owner order in code turns it on);
  2. the proof (PROOF), by default the walk-forward HOLDOUT of the live rule (walk.LIVE_VARIANT "dno") at the REAL
     size (0.1 SOL), the critic's criteria (15.11.): n >= 40 trades out of sample (configs picked on older days,
     traded on newer), EV net of the real costs > 0, the 95 % interval's low > 0 with the bootstrap blocked by DAY
     (memecoins move together), EV still > 0 at DOUBLED modeled costs, and > 0 without any one token
     (leave-one-token-out);
     the owner may later accept the demo's own record instead (trade/config.json "pravi_novac_veliki": {"dokaz":
     "demo"}): then >= 40 closed demo trades of this strategy with EV > 0 and the 90 % interval's low > 0;
  3. BTC known and not in a free fall (rule.Crash.regime "slobodan_pad": the same definition the backtest uses).
Caps (REAL; trade/config.json "pravi_novac_veliki" may LOWER them, and set size_sol up to MAX_SIZE_SOL 0.5): 0.2 SOL a
trade (16.11., the owner; 0.1 before), at most 5 open, a day's loss of 0.3 SOL stops the entries, one position a token. run_trade asks real_refusal()
again on every real buy and its hard rules hold on top (kill switch trade/STOP, the wallet reserve, the rug archive,
a stop on the server, the swap's cost cap max_cost_pct 6 %).
"""
SWITCH = "pravi_novac_veliki"
PROOF = {"n": 40, "ev_min_pct": 0.0, "ci_lo_min_pct": 0.0, "demo_n": 40, "ev_2x_min_pct": 0.0, "loto_min_pct": 0.0}
# 16.11. popodne (vlasnik: "treba sada deployat sav kapital moguć"; his answer to "Kapital": "5 pozicija × 0,2 SOL"):
# the stake 0.1 -> 0.2 SOL, still 5 open; the day's loss cap and the wallet's 1 SOL floor do not move
REAL = {"size_sol": 0.2, "max_open": 5, "max_buys_day": 20, "max_loss_day_sol": 0.3}
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


def proof_mode(cfg=None, con=None):
    """"walk" (holdout), "demo" (trade/config.json "dokaz": "demo") or "nalog_vlasnika" (15.11.: the owner's chat order
    "Odmah kreni tradat s pravim novcem", trade settings veliki_dokaz, set once by ui/assistnotes): real money without
    waiting for the proof; the proof is still computed and written on every real trade."""
    try:
        from trade import settings
        c = con or settings.connect()
        try:
            if str(settings.raw(c).get("veliki_dokaz") or "") == "nalog_vlasnika":
                return "nalog_vlasnika"
        finally:
            if con is None:
                c.close()
    except Exception:  # noqa: BLE001 - unreadable settings: the config's mode
        pass
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
    lo = (x.get("ci95_day_pct") or x.get("ci90_ev_pct") or [None])[0]
    if lo is None or lo <= PROOF["ci_lo_min_pct"]:
        return False, f"donja granica 95 % intervala (po danu) {lo} % nije iznad 0", x
    if x.get("ev_2x_cost_pct") is not None and x["ev_2x_cost_pct"] <= PROOF["ev_2x_min_pct"]:
        return False, f"uz dvostruki trošak EV {x['ev_2x_cost_pct']} % nije iznad 0", x
    if x.get("loto_min_pct") is not None and x["loto_min_pct"] <= PROOF["loto_min_pct"]:
        return False, f"bez jednog tokena EV pada na {x['loto_min_pct']} %: rezultat nosi jedan token", x
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
        return f"BTC slobodan pad ({st.get('why')}): bez novih pravih ulaza"
    return None


def real_refusal(con=None, proof=None, stats=None, cfg=None, now=None):
    """None when a big-token range entry may also buy with REAL money now, else why not (Croatian). Never raises."""
    try:
        if not switch_on(con):
            return f"prekidač {SWITCH} je isključen"
        mode = proof_mode(cfg, con)
        if mode == "nalog_vlasnika":   # 15.11.: the owner's order, no proof wait; BTC free fall still holds entries
            return btc_refusal(now)
        if mode == "demo":
            ok, why = demo_proof(stats)
        else:
            ok, why, _x = wf_proof(proof, real_caps(cfg)["size_sol"])
        if not ok:
            return why
        return btc_refusal(now)
    except Exception as e:  # noqa: BLE001 - an unreadable proof is no proof
        return f"dokaz se ne može pročitati ({type(e).__name__})"
