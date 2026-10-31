"""Learned exit rules per token class, on the persistent disk (LEARNED_DIR/exits.json, a few KB).

{"profiles": {"moonshot": {"v": 3, "params": {...}, "ts": ..., "eval": {...}, "prev": {...}}, "default": ...},
 "runs": [last 60 runs]}

A new paper trade gets the profile of its class (else "default", else paper/config.json as is) copied into its
own stored config, so a later change never alters a trade that is already open.
"""
import json
import os
import time

from learn import weights as _w

from . import learn

MAX_RUNS = 60


def path():
    return os.path.join(_w.LEARNED_DIR, "exits.json")


def load():
    try:
        with open(path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"profiles": {}, "runs": []}


def save(state):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    state["runs"] = state.get("runs", [])[-MAX_RUNS:]
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path())


def needs_refit(state=None):
    """Learned rules were fitted under older exit mechanics (paper.sim.SIM_VERSION changed): re-fit now, not at the
    next daily run, so no trade opens with rules chosen for mechanics that no longer exist."""
    from paper import sim
    state = load() if state is None else state
    return bool(state.get("profiles")) and state.get("sim_version", 1) != sim.SIM_VERSION


def current(state, klasa, base_cfg, sess=None):
    """(params, name) the next trade of this class (and trading session) would use."""
    prof = state.get("profiles", {})
    for k in ((f"{klasa}/{sess}" if klasa and sess else None), klasa, "default"):
        if k and k in prof:
            return prof[k]["params"], f"{k}@{prof[k]['v']}"
    return learn.params_of(base_cfg), "paper/config.json"


def for_trade(base_cfg, klasa, ecfg=None, state=None, now=None):
    """Paper config for a new trade: learned exits of its class (and of the trading session it opens in, when
    that has its own) applied, tagged with the profile name."""
    from . import paths
    ecfg = ecfg or learn.load_config()
    if not ecfg.get("enabled"):
        return base_cfg
    params, name = current(state or load(), klasa, base_cfg, paths.session_of(now or time.time()))
    cfg = learn.to_sim(base_cfg, params)
    cfg["exit_profile"] = name
    return cfg


def put(state, klasa, params, ev, now=None):
    prof = state.setdefault("profiles", {})
    old = prof.get(klasa)
    prof[klasa] = {"v": (old["v"] + 1) if old else 1, "params": params, "ts": int(now or time.time()), "eval": ev,
                   "prev": {"v": old["v"], "params": old["params"]} if old else None}


def rollback(state, klasa, why, now=None):
    p = state["profiles"].get(klasa)
    if not p:
        return False
    if p.get("prev"):
        state["profiles"][klasa] = {"v": p["v"] + 1, "params": p["prev"]["params"], "ts": int(now or time.time()),
                                    "eval": None, "prev": None, "rolled_back_from": p["v"], "why": why}
    else:
        del state["profiles"][klasa]  # back to paper/config.json
    return True
