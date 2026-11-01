"""Daily exit learning run: rollback check on live paper trades, then a guarded re-fit per class."""
import json
import os
import sqlite3
import time

from paper import sim

from . import learn, paths, profiles


def groups(live, seed, max_paths):
    """Paths per class plus 'default' (all). Live paths first (they are the bot's real entries); the seed fills
    the rest up to max_paths, so as live data grows the old study weighs less and less."""
    out = {}
    classes = {p["klasa"] for p in live + seed}

    def pick(match):
        lv = sorted([p for p in live if match(p)], key=lambda p: -p["ts"])[:max_paths]
        sd = sorted([p for p in seed if match(p)], key=lambda p: -p["ts"])
        return lv + sd[:max(0, max_paths - len(lv))]

    for k in sorted(classes) + ["default"]:
        out[k] = pick(lambda p, k=k: k == "default" or p["klasa"] == k)
    # per trading session (asia/eu/us by entry hour): volume and who is awake differ, so may the best exits.
    # A class+session gets its own rules only with enough paths (fit_profile's min_paths), else the class ones.
    for k in sorted(classes):
        for s, _, _ in paths.SESSIONS:
            out[f"{k}/{s}"] = pick(lambda p, k=k, s=s: p["klasa"] == k and paths.session_of(p["ts"]) == s)
    return out


def live_trades(paper_db, profile_name):
    """Closed paper trades opened with this profile: (ret, path for replay)."""
    if not os.path.exists(paper_db):
        return []
    con = sqlite3.connect(f"file:{paper_db}?mode=ro", uri=True, timeout=30)
    out = []
    try:
        for token, opened, ret, cfg, state in con.execute(
                "SELECT token, opened_ts, ret, config, state FROM trades WHERE status='closed'"):
            c = json.loads(cfg or "{}")
            if c.get("exit_profile") != profile_name:
                continue
            st = json.loads(state or "{}")
            if any(f.get("reason") == "rucno" for f in st.get("fills") or ()):
                continue  # sold by hand: not what the rules did
            rows = con.execute("SELECT ts, price, liquidity FROM ticks WHERE token=? AND ts>? ORDER BY ts",
                               (token, opened)).fetchall()
            out.append({"ret": ret or 0, "entry_px": st.get("entry_px"), "entry_liq": st.get("entry_liq"),
                        "opened": opened, "path": rows})
    finally:
        con.close()
    return out


def check_rollback(state, paper_db, base, ecfg, now):
    """A profile that does worse live than its predecessor would have on the same trades goes back."""
    notes = []
    lam, cap = ecfg["lambda_loss"], ecfg.get("ret_cap", 10.0)
    for k, p in list(state.get("profiles", {}).items()):
        trades = live_trades(paper_db, f"{k}@{p['v']}")
        if len(trades) < ecfg["rollback_min_trades"]:
            continue
        prev = (p.get("prev") or {}).get("params") or learn.params_of(base)
        cfg_prev = learn.to_sim(base, prev)
        sc = lambda rs: sum(min(r, cap) for r in rs) / len(rs) - lam * sum(-r for r in rs if r < 0) / len(rs)  # noqa: E731
        actual = sc([t["ret"] for t in trades])
        replay = sc([sim.replay(t["entry_px"], t["entry_liq"], t["opened"], t["path"], cfg_prev)["ret"]
                     for t in trades if t["entry_px"]])
        if actual < replay - ecfg["rollback_margin"]:
            why = (f"live {len(trades)} tradeova: ocjena {actual:+.2f}, prethodna pravila bi dala {replay:+.2f}")
            profiles.rollback(state, k, why, now)
            notes.append({"klasa": k, "rollback": True, "note": why})
    return notes


COARSE_DEFAULT = {"p_caught": 0.7, "gap": -0.05}


def reality(paper_db, ecfg=None, since=0):
    """How our live demo stops really filled: {n, p_caught, gap, secs, measured}. p_caught = share of stop/rug exits
    sold within 15 points of the stop (the minute check caught it), gap = median distance below the stop of those.
    With fewer than reality_min_n exits the defaults hold (70%, 5 points)."""
    ecfg = ecfg or {}
    out = {**COARSE_DEFAULT, "secs": ecfg.get("coarse_s", 300), "n": 0, "measured": False}
    if not paper_db or not os.path.exists(paper_db):
        return out
    try:
        con = sqlite3.connect(f"file:{paper_db}?mode=ro", uri=True, timeout=30)
        rows = con.execute("SELECT ret, config, state FROM trades WHERE status='closed' AND exit_reason IN "
                           "('stop_loss', 'rug') AND opened_ts>=?", (since,)).fetchall()
        con.close()
    except sqlite3.OperationalError:
        return out
    caught, n = [], 0
    for ret, cfg, state in rows:
        st = json.loads(state or "{}")
        if st.get("tp_done") or any(f.get("reason") == "rucno" for f in st.get("fills") or ()):
            continue  # a stop after a take profit, or sold by hand: not a first stop
        sl = json.loads(cfg or "{}").get("sl")
        if sl is None or ret is None:
            continue
        n += 1
        if ret >= sl - 0.15:
            caught.append(ret - sl)
    out["n"] = n
    if n >= ecfg.get("reality_min_n", 20):
        caught.sort()
        out["p_caught"] = round(len(caught) / n, 3)
        out["gap"] = round(max(-0.15, min(0.0, caught[len(caught) // 2])), 3) if caught else -0.15
        out["measured"] = True
    return out


def run(paper_db, hype_db=None, now=None, apply=True, seed=None):
    now = now or time.time()
    ecfg, base = learn.load_config(), sim.load_config()
    real = reality(paper_db, ecfg, since=now - ecfg["live_days"] * 86400)
    base = {**base, "coarse": {k: real[k] for k in ("secs", "p_caught", "gap")}}
    state = profiles.load()
    report = check_rollback(state, paper_db, base, ecfg, now) if apply else []
    rolled = {r["klasa"] for r in report}
    live = paths.from_paper(paper_db, hype_db, since=now - ecfg["live_days"] * 86400,
                            tol=ecfg["tolerance"], max_points=ecfg["max_points"])
    seed = paths.load_seed() if seed is None else seed
    for k, ps in groups(live, seed, ecfg["max_paths"]).items():
        if k in rolled:
            continue
        own = state.get("profiles", {}).get(k)
        parent = k.split("/")[0] if "/" in k else ("default" if k != "default" else None)
        current = own["params"] if own else profiles.current(state, parent, base)[0]
        dec, cand = learn.fit_profile(ps, base, current, ecfg)
        dec["klasa"] = k
        dec["applied"] = bool(cand and apply)
        if cand and apply:
            profiles.put(state, k, cand, {x: dec["new"].get(x) for x in ("n", "score", "mean", "median", "win",
                                                                        "big_loss", "moon_n", "moon_mult")}, now)
        report.append(dec)
    if apply:
        state["sim_version"] = sim.SIM_VERSION  # fitted under these exit mechanics (profiles.needs_refit)
        state["reality"] = {**real, "slip": base.get("slip", 0.0), "ts": int(now)}
        state.setdefault("runs", []).append({"ts": int(now), "items": [
            {k: r.get(k) for k in ("klasa", "n", "n_live", "applied", "rollback", "note")} for r in report]})
        profiles.save(state)
    return report
