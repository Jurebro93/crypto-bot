"""Multi-source convergence: several good callers on different platforms (X, Telegram) and KOL wallets buying
on chain, all on the same token within a short window. This is the moment to be in before the crowd.

compute() only reads (kol.db, tg.db, hype.db), so the hype scan calls it every 2 minutes on fresh data;
run_kol.py stores the result in kol.db converge for the dashboard and the history.

Score 0-100 (kol/config.json converge):
- each good author (KOL score >= good_score) on X or Telegram: pts_good, at most 3 per platform;
- each tracked KOL wallet that bought: pts_wallet, at most 3;
- each other author: pts_other, at most 10;
- every extra platform with a good author or a wallet buy: + pts_platform (X + Telegram beats three X accounts);
- times the learned session factor (kol/sessions.py), times 0.3 if a tracked wallet already sells, times 0.5 for
  a paid-promo pattern (promo_channels Telegram posts inside promo_secs and the first caller is not good).
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT = {"window_min": 30, "fresh_min": 15, "pts_good": 18, "pts_wallet": 22, "pts_other": 3, "pts_platform": 12,
           "promo_channels": 5, "promo_secs": 120, "min_score": 20}


def _ro(path):
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def events(now, window_s, kol_db=None, tg_db=None, hype_db=None):
    """[(token, ts, platform, author, kind)] in the window, from every source, plus (scores, wallet->handle)."""
    kc = _ro(kol_db or os.path.join(ROOT, "kol.db"))
    tc = _ro(tg_db or os.environ.get("TG_DB") or os.path.join(ROOT, "tg.db"))
    hc = _ro(hype_db or os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db"))
    since = now - window_s
    ev = []
    try:
        scores = dict(_q(kc, "SELECT handle, COALESCE(score, 0) FROM kols"))
        who = {}
        for w, tw, name in _q(kc, "SELECT wallet, twitter, name FROM kol_ids"):
            who[w] = tw or "w:" + (name or w[:6])
        fac = {}
        try:
            from kol import sessions
            fac = sessions.factors(kc) if kc else {}
        except sqlite3.OperationalError:
            pass
        for tok, ts, h, kind, src in _q(kc, "SELECT token, ts, handle, kind, source FROM calls WHERE ts >= ? "
                                            "AND kind = 'call'", (since,)):
            plat = "tg" if h.startswith("tg:") else "x"   # wallet swaps come from hype.db chain_trades below
            ev.append((tok, ts, plat, h, kind))
        for h, ca, ts in _q(hc, "SELECT handle, ca, ts FROM kol_mentions WHERE ts >= ? AND ca != ''", (since,)):
            ev.append((ca, ts, "x", h, "call"))   # live X webhook, before run_kol copies it
        for ch, ts, cas, fwd in _q(tc, "SELECT channel, ts, cas, fwd_from FROM posts WHERE ts >= ? AND cas != ''",
                                   (since,)):
            for ca in cas.split(","):
                ev.append((ca, ts, "tg", f"tg:{ch}", "repost" if fwd else "call"))
        for w, mint, side, ts in _q(hc, "SELECT wallet, mint, side, ts FROM chain_trades WHERE ts >= ?", (since,)):
            ev.append((mint, ts, "chain", who.get(w, "w:" + w[:6]), side))
    finally:
        for c in (kc, tc, hc):
            if c is not None:
                c.close()
    return ev, scores, fac


def score_token(evs, scores, fac, cfg, good, now):
    from kol import sessions
    calls = sorted((e for e in evs if e[4] == "call"), key=lambda e: e[1])
    buys = {e[3] for e in evs if e[4] == "buy"}
    sells = {e[3] for e in evs if e[4] == "sell"} & buys
    if not calls and not buys:
        return None
    goods = {"x": set(), "tg": set()}
    others = set()
    for _, ts, plat, h, _k in calls:
        (goods[plat] if (scores.get(h) or 0) >= good else others).add(h)
    others -= goods["x"] | goods["tg"]
    plats = [p for p in ("x", "tg") if goods[p]] + (["chain"] if buys else [])
    pts = (cfg["pts_good"] * (min(len(goods["x"]), 3) + min(len(goods["tg"]), 3))
           + cfg["pts_wallet"] * min(len(buys), 3) + cfg["pts_other"] * min(len(others), 10)
           + cfg["pts_platform"] * max(0, len(plats) - 1))
    first = min([e[1] for e in calls] + [e[1] for e in evs if e[4] == "buy"])
    pts *= fac.get(sessions.session_of(first), 1.0)
    tg_calls = [e for e in calls if e[2] == "tg"]
    promo = False
    if len(tg_calls) >= cfg["promo_channels"]:
        burst = [e for e in tg_calls if e[1] - tg_calls[0][1] <= cfg["promo_secs"]]
        promo = len({e[3] for e in burst}) >= cfg["promo_channels"] and (scores.get(calls[0][3]) or 0) < good
    if promo:
        pts *= 0.5
    if sells:
        pts *= 0.3
    last = max(e[1] for e in evs)
    return {"score": round(min(100.0, pts), 1), "first_ts": first, "last_ts": last,
            "n_x": len(goods["x"]), "n_tg": len(goods["tg"]), "n_chain": len(buys), "n_other": len(others),
            "platforms": plats or sorted({e[2] for e in calls}), "kol_selling": int(bool(sells)), "promo": promo,
            "handles": sorted(goods["x"] | goods["tg"] | buys)[:20]}


def compute(now=None, cfg=None, good=50, **paths):
    """token -> convergence dict, for tokens with fresh activity and score >= min_score."""
    cfg = dict(DEFAULT, **(cfg or {}))
    now = now or int(time.time())
    ev, scores, fac = events(now, cfg["window_min"] * 60, **paths)
    by = {}
    for e in ev:
        by.setdefault(e[0], []).append(e)
    out = {}
    for tok, evs in by.items():
        r = score_token(evs, scores, fac, cfg, good, now)
        if r and r["score"] >= cfg["min_score"] and now - r["last_ts"] <= cfg["fresh_min"] * 60:
            out[tok] = r
    return out


def save(con, conv, now=None):
    """kol.db converge: newest state per token (kept 7 days)."""
    now = now or int(time.time())
    for tok, r in conv.items():
        con.execute("""INSERT INTO converge VALUES (?,?,?,?,?,?,?,?,?,?,NULL,0,?,?) ON CONFLICT (token) DO UPDATE SET
            ts=excluded.ts, score=MAX(score, excluded.score), n_x=MAX(n_x, excluded.n_x), n_tg=MAX(n_tg, excluded.n_tg),
            n_chain=MAX(n_chain, excluded.n_chain), n_other=MAX(n_other, excluded.n_other), platforms=excluded.platforms,
            handles=excluded.handles, kol_selling=excluded.kol_selling, updated=excluded.updated""",
                    (tok, r["last_ts"], r["first_ts"], r["score"], r["n_x"], r["n_tg"], r["n_chain"], r["n_other"],
                     json.dumps(r["platforms"]), json.dumps(r["handles"]), r["kol_selling"], now))
    con.execute("DELETE FROM converge WHERE ts < ?", (now - 7 * 86400,))
    return len(conv)
