"""Insider wallets as a signal of their own (Nicholas 4.11.: "tko kupuje prije poziva - kupuj s njima").

kol.db `insiders` (kol/flows.py, Helius history around strong calls) holds wallets that bought a token in the hour
BEFORE a KOL called it and what they did after. A wallet that does this on several tokens knows something, or is
part of the team. They are kept off the copy list on purpose (they sell into the call); here they are a signal:

  wallets()      the insider wallets by how many called tokens they bought early (chain webhook follows the best)
  profile()      insider or sniper? share of a wallet's bought tokens that were EVER called, and how many seconds
                 after launch it buys. A sniper buys every launch in its first seconds; most are never called.
  signal()       tokens that 2+ insider wallets bought within a window, with no KOL call yet (hype.db chain_trades,
                 the Helius webhook feed): the "insajderi" demo strategy buys these
  sold_since()   did an insider of that token sell after our entry? The strategy exits with them
  sell_timing()  when insiders sell relative to the 2nd and 3rd call on the token: the exit rule candidate
"""
import os
import sqlite3
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = {"min_tokens": 2, "window_min": 10, "min_wallets": 2, "sniper_secs": 60, "sniper_called_share": 0.3,
           "profile_min_buys": 10, "max_wallets": 50}


def cfg_of(cfg=None):
    return dict(DEFAULT, **((cfg or {}).get("insiders") or {}))


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        return None


def wallets(con, min_tokens=2, limit=50):
    """[(wallet, tokens bought before a call, tokens sold after the call)] best first, from kol.db insiders."""
    try:
        rows = con.execute("""SELECT wallet, COUNT(DISTINCT token), SUM(sold_ts IS NOT NULL) FROM insiders
                              WHERE bought_ts IS NOT NULL AND bought_ts < call_ts GROUP BY wallet
                              HAVING COUNT(DISTINCT token) >= ? ORDER BY 2 DESC, 3 DESC LIMIT ?""",
                           (min_tokens, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(w, n, s or 0) for w, n, s in rows]


def profile(wallet, wallet_db=None, kol_db=None, c=None):
    """{'bought': n, 'called': n, 'called_share': x, 'med_secs_after_launch': s|None, 'sniper': bool} or None when the
    wallet has no trade history in wallets.db yet (run_wallets.py score has not reached it)."""
    c = c or DEFAULT
    from wallets import store as wstore
    wcon = _ro(wallet_db or wstore.DB)
    if wcon is None:
        return None
    try:
        buys = wcon.execute("SELECT mint, MIN(ts) FROM wallet_trades WHERE wallet=? AND kind='buy' GROUP BY mint",
                            (wallet,)).fetchall()
    except sqlite3.OperationalError:
        buys = []
    finally:
        wcon.close()
    if not buys:
        return None
    from kol import store as kstore
    kcon = _ro(kol_db or kstore.DB)
    called, created = set(), {}
    if kcon is not None:
        try:
            mints = [m for m, _ in buys]
            for i in range(0, len(mints), 500):
                chunk = mints[i:i + 500]
                q = ",".join("?" * len(chunk))
                called |= {t for (t,) in kcon.execute(f"SELECT DISTINCT token FROM calls WHERE kind='call' AND token IN ({q})", chunk)}
                created.update(dict(kcon.execute(f"SELECT token, created_ts FROM tokens WHERE created_ts IS NOT NULL AND token IN ({q})", chunk)))
        except sqlite3.OperationalError:
            pass
        finally:
            kcon.close()
    after = [ts - created[m] for m, ts in buys if m in created and ts and ts >= created[m]]
    med = statistics.median(after) if after else None
    share = len([m for m, _ in buys if m in called]) / len(buys)
    sniper = (len(buys) >= c["profile_min_buys"] and share < c["sniper_called_share"]) or (med is not None and med <= c["sniper_secs"])
    return {"bought": len(buys), "called": len([m for m, _ in buys if m in called]), "called_share": round(share, 2),
            "med_secs_after_launch": None if med is None else int(med), "sniper": bool(sniper)}


def good_set(kol_db=None, wallet_db=None, cfg=None):
    """Insider wallets minus the snipers: what the webhook follows and the strategy listens to."""
    c = cfg_of(cfg)
    from kol import store as kstore
    con = _ro(kol_db or kstore.DB)
    if con is None:
        return set()
    try:
        cand = wallets(con, c["min_tokens"], c["max_wallets"] * 2)
    finally:
        con.close()
    out = set()
    for w, _n, _s in cand:
        p = profile(w, wallet_db, kol_db, c)
        if p and p["sniper"]:
            continue
        out.add(w)
        if len(out) >= c["max_wallets"]:
            break
    return out


def signal(hype_db, kol_db, insiders, now, window_s=600, min_wallets=2):
    """[(token, ts, who, score)]: tokens that min_wallets+ insider wallets bought within window_s of each other
    (newest buys only, inside [now - window_s, now]) and nobody has called yet. ts = the buy that completed the group."""
    if not insiders:
        return []
    hcon = _ro(hype_db)
    if hcon is None:
        return []
    by = {}
    try:
        q = ",".join("?" * len(insiders))
        for w, m, ts in hcon.execute(f"SELECT wallet, mint, MIN(ts) FROM chain_trades WHERE side='buy' AND ts >= ? "
                                     f"AND wallet IN ({q}) GROUP BY wallet, mint", (int(now - window_s), *insiders)):
            by.setdefault(m, {})[w] = ts
    except sqlite3.OperationalError:
        return []
    finally:
        hcon.close()
    out = []
    if not by:
        return out
    kcon = _ro(kol_db)
    called = set()
    if kcon is not None:
        try:
            q = ",".join("?" * len(by))
            called = {t for (t,) in kcon.execute(f"SELECT DISTINCT token FROM calls WHERE kind='call' AND token IN ({q})", list(by))}
        except sqlite3.OperationalError:
            pass
        finally:
            kcon.close()
    for m, ws in by.items():
        if len(ws) < min_wallets or m in called:
            continue
        times = sorted(ws.values())
        ts = times[min_wallets - 1]
        names = ", ".join(w[:4] + "…" for w, _ in sorted(ws.items(), key=lambda kv: kv[1])[:3])
        out.append((m, int(ts), f"{len(ws)} insajdera prije poziva: {names}", len(ws)))
    return out


def sold_since(hype_db, token, since, insiders):
    """Earliest sell of `token` by one of `insiders` after `since`, or None."""
    if not insiders:
        return None
    hcon = _ro(hype_db)
    if hcon is None:
        return None
    try:
        q = ",".join("?" * len(insiders))
        r = hcon.execute(f"SELECT MIN(ts) FROM chain_trades WHERE mint=? AND side='sell' AND ts > ? AND wallet IN ({q})",
                         (token, int(since), *insiders)).fetchone()
        return r[0] if r and r[0] else None
    except sqlite3.OperationalError:
        return None
    finally:
        hcon.close()


def sell_timing(con):
    """When insiders sell, relative to the 2nd and 3rd distinct caller of the token (minutes; negative = before):
    {'n': tokens, 'to_2nd': {'med','q25','q75'}, 'to_3rd': {...}, 'before_3rd_share': x}. The exit-rule candidate:
    if most insider sells land right after the 3rd call, sell by the 3rd call."""
    try:
        calls = con.execute("SELECT token, handle, ts FROM calls WHERE kind='call' ORDER BY token, ts").fetchall()
        sells = con.execute("SELECT token, sold_ts FROM insiders WHERE sold_ts IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return {"n": 0}
    nth = {}
    for tok, h, ts in calls:
        d = nth.setdefault(tok, [])
        if h not in {x[0] for x in d}:
            d.append((h, ts))
    d2, d3, toks = [], [], set()
    for tok, sold in sells:
        seq = nth.get(tok) or []
        if len(seq) >= 2:
            d2.append((sold - seq[1][1]) / 60)
            toks.add(tok)
        if len(seq) >= 3:
            d3.append((sold - seq[2][1]) / 60)

    def q(xs):
        if not xs:
            return None
        s = sorted(xs)
        return {"med": round(statistics.median(s), 1), "q25": round(s[len(s) // 4], 1), "q75": round(s[(3 * len(s)) // 4], 1), "n": len(s)}
    return {"n": len(toks), "to_2nd": q(d2), "to_3rd": q(d3),
            "before_3rd_share": round(sum(1 for x in d3 if x <= 0) / len(d3), 2) if d3 else None}
