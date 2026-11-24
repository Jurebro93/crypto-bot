"""Exploration "arms": which combination of sources triggered a demo trade, how each combination does, and why a
trade lost. The bot gives more exploration trades to arms that win (Thompson sampling) and never fully stops an
arm (keep_frac), so a source that gets better is noticed.

Arm = sorted platforms + session, e.g. 'tg+x|us', 'chain+x|eu', 'dex|asia'. Exploration entries also pass a second
draw on their score band ('ocjena 45+', see band_of).
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


BANDS = ((45, "45+"), (35, "35-45"), (0, "do 35"))


def band_of(score):
    """Score band of an exploration entry, its own 'arm': 31.10. the high-score exploration entries (45+) lost 7 of
    8 (hype already priced in, bought the top) while those under 35 won 11 of 21 (ANSEM came in at 31). Which band
    deserves trades is learned from results like any arm, never fixed by hand."""
    s = score or 0
    return "ocjena " + next(name for lo, name in BANDS if s >= lo)


MC_BANDS = ((1e6, "preko 1M $"), (2e5, "200k–1M $"), (5e4, "50–200k $"), (0, "ispod 50k $"))


def mc_band(mcap):
    """Market-cap band at entry, its own 'arm' (Nicholas 4.11.): a $10k token and a $800k token are different
    games (the small ones rug far more often), so each band is measured on its own and a band that keeps losing
    gets fewer entries, learned from results like any arm."""
    if not mcap:
        return "mc ?"
    return "mc " + next(name for lo, name in MC_BANDS if mcap >= lo)


def stats(con, cfg=None):
    """{arm: [wins, losses]} from closed trades that carry an arm, plus {'ocjena <band>': [w, l]} for closed
    exploration trades by the score they came in with. Trades someone sold by hand do not count (not the bot's
    result)."""
    cfg = dict(DEFAULT, **(cfg or {}))
    out = {}
    for conf, ret, state, score, mc in con.execute(
            "SELECT t.config, t.ret, t.state, c.score, t.entry_mcap FROM trades t LEFT JOIN candidates c "
            "ON c.trade_id=t.id WHERE t.status='closed' AND t.config LIKE '%\"arm\"%'"):
        c = json.loads(conf or "{}")
        arm = c.get("arm")
        if not arm or '"rucno"' in (state or ""):
            continue
        win = 0 if (ret or 0) > cfg["win_ret"] else 1
        # reward by size (2.11.): +5% counts ~1 win, +100% 2, +200% or more 3, so an arm with a few big winners is
        # not starved by one with many tiny ones; a loss counts 1
        amt = 1 + min(2.0, max(0.0, ret or 0)) if win == 0 else 1
        out.setdefault(arm, [0, 0])[win] += amt
        if c.get("entry_mode") == "explore" and score is not None:
            out.setdefault(band_of(score), [0, 0])[win] += amt
        if mc:
            out.setdefault(mc_band(mc), [0, 0])[win] += amt
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
    if r == "rucno":
        return "prodano ručno"
    if r == "hitni_izlaz":
        return "hitni izlaz (pool se praznio ili nagli pad)"
    if r == "kol_prodaje":
        return "KOL novčanik prodao"
    if r == "zivi_dump":
        return "dump u živom toku (prodano u sekundama)"
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
    for conf, ret, pnl, er, mx, mn, score in con.execute(
            "SELECT t.config, t.ret, t.pnl_usd, t.exit_reason, t.max_ret, t.min_ret, c.score FROM trades t "
            "LEFT JOIN candidates c ON c.trade_id=t.id WHERE t.status='closed'"):
        c = json.loads(conf or "{}")
        if c.get("entry_mode") not in ("explore", "konv", "mc100k", "mc100k2", "kol3", "aktivni"):
            continue
        keys = [c.get("arm") or "bez kraka"] + ([band_of(score)] if c.get("entry_mode") == "explore"
                                                 and score is not None else [])
        for key in keys:
            a = arms.setdefault(key, [0, 0, 0.0, 0.0])
            a[0] += 1
            a[1] += (ret or 0) > 0
            a[2] += ret or 0
            a[3] += pnl or 0
        why = loss_reason(er, mx, mn, ret)
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    rows = sorted(((k, n, w, s / n, p) for k, (n, w, s, p) in arms.items()), key=lambda r: -r[4])
    return rows, reasons
