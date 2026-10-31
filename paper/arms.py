"""Exploration "arms": which combination of sources triggered a demo trade, how each combination does, and why a
trade lost. The bot gives more exploration trades to arms that win (Thompson sampling) and never fully stops an
arm (keep_frac), so a source that gets better is noticed.

Arm = sorted platforms + session, e.g. 'tg+x|us', 'chain+x|eu', 'dex|asia'.
"""
import json
import random

PLATFORM = {"telegram": "tg", "kol_x": "x", "kol_group": "x", "konv": "konv", "profile": "dex", "profile_update": "dex",
            "boost": "dex", "top_boost": "dex", "takeover": "dex", "zadrzan": "dex"}
DEFAULT = {"min_n": 6, "floor": 0.2, "keep_frac": 0.1, "win_ret": 0.0}


def platforms_of(c, conv=None):
    out = set()
    for s in c.get("sources") or ():
        p = PLATFORM.get(s) or ("pump" if s.startswith("pumpfun") else "meta" if s.startswith("meta:") else None)
        if p and p != "konv":
            out.add(p)
    f = c.get("features") or {}
    if f.get("telegram"):
        out.add("tg")
    if f.get("kol_x") or f.get("kol_group"):
        out.add("x")
    if f.get("pump_live") or f.get("kol_wallets"):
        out.add("pump")
    if conv:
        out |= set(conv.get("platforms") or [])
    return sorted(out) or ["dex"]


def arm_of(c, conv=None, now=None):
    from kol import sessions
    import time
    return "+".join(platforms_of(c, conv)) + "|" + sessions.session_of(now or time.time())


def stats(con, cfg=None):
    """{arm: [wins, losses]} from closed trades that carry an arm."""
    cfg = dict(DEFAULT, **(cfg or {}))
    out = {}
    for conf, ret in con.execute("SELECT config, ret FROM trades WHERE status='closed' AND config LIKE '%\"arm\"%'"):
        arm = json.loads(conf or "{}").get("arm")
        if arm:
            w = out.setdefault(arm, [0, 0])
            w[0 if (ret or 0) > cfg["win_ret"] else 1] += 1
    return out


def allow(arm, st, cfg=None, rng=random):
    """(take it?, theta): Beta(wins+1, losses+1) draw; arms with few trades always pass."""
    cfg = dict(DEFAULT, **(cfg or {}))
    w, l = st.get(arm, [0, 0])
    if w + l < cfg["min_n"]:
        return True, None
    theta = rng.betavariate(w + 1, l + 1)
    return theta >= cfg["floor"] or rng.random() < cfg["keep_frac"], round(theta, 2)


def loss_reason(exit_reason, max_ret, min_ret, ret):
    """Plain reason for a losing trade, for the learning and the page."""
    r = exit_reason or ""
    if (ret or 0) > 0:
        return None
    if r == "rug":
        return "rug (likvidnost nestala)"
    if r == "kol_prodaje":
        return "KOL novčanik prodao"
    if r in ("stale", "time"):
        return "nema pokreta (vremenski izlaz)"
    if r == "stop_loss" and (max_ret or 0) < 0.05:
        return "kasni ulaz (odmah pad)"
    if r == "stop_loss" and (max_ret or 0) >= 0.2:
        return "dobit nije uzeta na vrijeme"
    if r == "stop_loss":
        return "stop loss"
    if r in ("trailing", "breakeven"):
        return "pad nakon malog rasta"
    return r or "ostalo"


def report(con):
    """[(arm, trades, wins, avg ret, pnl)] and {reason: count} of losing exploration/convergence trades."""
    arms, reasons = {}, {}
    for conf, ret, pnl, er, mx, mn in con.execute(
            "SELECT config, ret, pnl_usd, exit_reason, max_ret, min_ret FROM trades WHERE status='closed'"):
        c = json.loads(conf or "{}")
        if c.get("entry_mode") not in ("explore", "konv"):
            continue
        a = arms.setdefault(c.get("arm") or "bez kraka", [0, 0, 0.0, 0.0])
        a[0] += 1
        a[1] += (ret or 0) > 0
        a[2] += ret or 0
        a[3] += pnl or 0
        why = loss_reason(er, mx, mn, ret)
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    rows = sorted(((k, n, w, s / n, p) for k, (n, w, s, p) in arms.items()), key=lambda r: -r[4])
    return rows, reasons
