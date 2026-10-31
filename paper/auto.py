"""The daily review's entry-rule changes applied by the bot itself, with guardrails and rollback. Nothing manual.

Learned values live on the persistent disk (LEARNED_DIR/paper.json, a few KB) as an overlay on paper/config.json,
so a redeploy keeps them and paper/config.json in the repo stays the starting point:

    {"params": {"min_score": 55}, "history": [{"ts", "day", "changes", "prev", "n", "text", "kind"}]}

Guardrails, on top of the review's own test (better overall and on both time halves, MIN_N tokens):
- only entry rules (prag ocjene, min likvidnost, blokirane rug presude); exits are learned per class by exits/,
- at least AUTO_MIN_N tokens behind the change, entry threshold moves at most MAX_SCORE_STEP per day,
- one change per day,
- rollback: once ROLLBACK_MIN_N new tokens exist after a change, the new rules must still do at least as well as
  the old ones on exactly those tokens, else the old values come back.
"""
import json
import os
import time

from learn import weights as _w

AUTO_KEYS = ("min_score", "min_liq", "block_verdicts")
AUTO_MIN_N = 30
MAX_SCORE_STEP = 10
BLOCK_MIN_N = 10  # blocking one more rug verdict only needs enough tokens with that verdict
ROLLBACK_MIN_N = 15
MAX_HISTORY = 60


def path():
    return os.path.join(_w.LEARNED_DIR, "paper.json")


def load():
    try:
        with open(path()) as f:
            st = json.load(f)
        return {"params": st.get("params") or {}, "history": st.get("history") or []}
    except (OSError, ValueError):
        return {"params": {}, "history": []}


def save(state):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    state["history"] = state.get("history", [])[-MAX_HISTORY:]
    tmp = path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path())


def overlay(cfg):
    """paper/config.json with the learned entry rules on top."""
    p = load()["params"]
    return {**cfg, **{k: v for k, v in p.items() if k in AUTO_KEYS}} if p else cfg


def _label():
    from ui import labels
    return labels


def _rollback(state, cfg, learn_rows, now):
    """Undo the last change if the tokens seen since it would have done better under the old rules."""
    from . import review
    last = next((h for h in reversed(state["history"]) if h.get("kind") == "primijenjeno" and not h.get("checked")), None)
    if not last:
        return None
    since = [r for r in learn_rows if r["ts"] >= last["ts"]]
    if len(since) < ROLLBACK_MIN_N:
        return None
    old_cfg = {**cfg, **last["prev"]}
    new = review.pnl([r for r in since if review.would_take(r, cfg)], cfg)
    old = review.pnl([r for r in since if review.would_take(r, old_cfg)], old_cfg)
    last["checked"] = int(now)
    if new["pnl"] >= old["pnl"]:
        last["check"] = f"potvrđeno na {len(since)} novih tokena ({new['pnl']:+.0f} vs {old['pnl']:+.0f} USD po starim pravilima)"
        return None
    state["params"].update(last["prev"])
    L = _label()
    text = (f"Vraćeno na staro ({L.cfg_change(last['prev'])}): "
            f"na {len(since)} tokena nakon promjene stara pravila bi dala {old['pnl']:+.0f} USD, nova {new['pnl']:+.0f} USD.")
    entry = {"ts": int(now), "day": time.strftime("%Y-%m-%d", time.localtime(now)), "kind": "vraćeno",
             "changes": last["prev"], "prev": last["changes"], "n": len(since), "text": text}
    state["history"].append(entry)
    return entry


def apply(rep, cfg, learn_rows=None, exits_learned=True, now=None):
    """Decide on the review's suggestions. Returns [{kind: primijenjeno|vraćeno|čeka, text}] in plain words and
    updates the overlay. cfg is the effective config the review ran with (base + overlay)."""
    now = now or time.time()
    state = load()
    out = []
    rb = _rollback(state, cfg, learn_rows or [], now) if learn_rows is not None else None
    if rb:
        out.append(rb)
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    done_today = any(h.get("day") == day and h.get("kind") == "primijenjeno" for h in state["history"])
    L = _label()
    for s in rep.get("suggestions") or []:
        ch = {k: v for k, v in (s.get("change") or {}).items()}
        if not ch:
            continue
        entry_ch = {k: v for k, v in ch.items() if k in AUTO_KEYS}
        if not entry_ch:
            if exits_learned:
                out.append({"kind": "info", "text": "Izlaze (stop loss, take profit, trailing) bot uči zasebno po klasi "
                                                    "tokena, pa ovaj prijedlog ide tamo (stranica Izlazi)."})
            continue
        n = s.get("n") or 0
        if rb or done_today:
            out.append({"kind": "čeka", "text": f"{L.cfg_change(entry_ch)}: čeka sutra (danas je već bila jedna promjena)."})
            continue
        need = BLOCK_MIN_N if set(entry_ch) == {"block_verdicts"} else AUTO_MIN_N
        if n < need:
            out.append({"kind": "čeka", "text": f"{L.cfg_change(entry_ch)}: izgleda bolje, ali na samo {n} tokena; "
                                                f"bot to mijenja sam tek kad ima barem {need}."})
            continue
        if "min_score" in entry_ch:
            cur = cfg.get("min_score", 0)
            step = max(-MAX_SCORE_STEP, min(MAX_SCORE_STEP, entry_ch["min_score"] - cur))
            entry_ch["min_score"] = cur + step
        prev = {k: cfg.get(k) for k in entry_ch}
        state["params"].update(entry_ch)
        text = f"Bot je promijenio: {L.cfg_change(entry_ch)} (na temelju {n} tokena). " + L.plain(s.get("text", ""))
        entry = {"ts": int(now), "day": day, "kind": "primijenjeno", "changes": entry_ch, "prev": prev, "n": n,
                 "text": text.strip()}
        state["history"].append(entry)
        out.append(entry)
        done_today = True
    if out or rb:
        save(state)
    return out
