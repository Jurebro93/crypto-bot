"""27.11.2026. (vlasnik, X budžet priority 1 and 2): who on X calls the tokens our watched wallets buy, and when.

Watched wallets: the proven set (wallets/dokazani.current: profitable before and after the cut; the pre-pump buyers
the Helius webhook follows). For each token one of them BOUGHT in the last back_h hours (wallets.db wallet_trades,
kind 'buy'), not searched yet, one twitterapi.io search for its address (kol/twapi.search, X budget category
"pozivi", job "novcanici"), from an hour before the first buy until now. Every post that names it is saved like any
other call (kol.db calls, source "kol_nx": who, the exact time), so call power, wallet <-> influencer linking and
the KOL score see it.

Candidates (priority 2, new influencers; no extra request): an account that called the token within after_h hours
AFTER a watched wallet's buy goes into kol.db nx_kandidati (handle, token, wallet, buy_ts, call_ts, delay_s, known);
known = 0 when the account was not in kols before this call. Nothing here trades. Spend: only the X budget (and
the twitterapi day counter, kol.db twapi:<day>); per_run tokens a round at most.
"""
import os
import sqlite3
import time

DEFAULT = {"back_h": 48, "after_h": 6, "per_run": 8, "pages": 2, "pre_s": 3600}
SCHEMA = """CREATE TABLE IF NOT EXISTS nx_kandidati (handle TEXT, token TEXT, wallet TEXT, buy_ts INTEGER,
    call_ts INTEGER, delay_s INTEGER, known INTEGER, found_ts INTEGER, PRIMARY KEY (handle, token));"""


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("novcanici_x") or {})}


def ensure(con):
    con.executescript(SCHEMA)


def wallet_buys(wallets, since, path=None):
    """{mint: [(buy_ts, wallet)]} of the watched wallets' buys since `since` (read-only; {} without the db)."""
    if not wallets:
        return {}
    if path is None:
        from wallets import store as wstore
        path = wstore.DB
    if not path or not os.path.exists(path):
        return {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    out = {}
    try:
        ws = sorted(wallets)
        for i in range(0, len(ws), 500):
            part = ws[i:i + 500]
            q = ",".join("?" * len(part))
            for w, mint, ts in con.execute(f"SELECT wallet, mint, ts FROM wallet_trades WHERE kind = 'buy' AND ts >= ? "
                                           f"AND wallet IN ({q})", (int(since), *part)):
                if mint:
                    out.setdefault(mint, []).append((int(ts), w))
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {m: sorted(v) for m, v in out.items()}


def targets(con, buys, now):
    """[(mint, first_buy_ts, buys)] not searched yet, newest buy first."""
    done = {t[3:] for (t,) in con.execute("SELECT target FROM searches WHERE target LIKE 'nx:%'")}
    rows = [(m, v[0][0], v) for m, v in buys.items() if m not in done]
    return sorted(rows, key=lambda r: -max(t for t, _w in r[2]))


def candidates(calls, buys, after_s):
    """[(handle, wallet, buy_ts, call_ts, delay_s)]: the first call of each account within after_s after a buy."""
    out = {}
    for c in calls:
        h, ts = c.get("handle"), c.get("ts")
        if not h or not ts:
            continue
        for bt, w in buys:
            if bt <= ts <= bt + after_s:
                if h not in out or ts < out[h][2]:
                    out[h] = (w, bt, ts, ts - bt)
                break
    return [(h, *v) for h, v in sorted(out.items())]


def search(con, cfg, get=None, now=None, wallets=None, wpath=None, log=print):
    """One round. Returns the number of new calls saved."""
    from kol import collect, twapi
    if not twapi.key() and get is None:
        return 0
    ensure(con)
    c = config(cfg)
    now = int(now or time.time())
    if wallets is None:
        from wallets import dokazani
        wallets = dokazani.current()
    buys = wallet_buys(wallets, now - c["back_h"] * 3600, wpath)
    n = n_cand = 0
    for mint, first, bl in targets(con, buys, now)[:c["per_run"]]:
        if not twapi._room("pozivi", twapi.MAX_PAGE, now):
            log("novčanici X: X budžet (pozivi) za danas potrošen, ostatak u sljedećem krugu")
            break
        try:
            items = twapi.search(con, mint, first - c["pre_s"], float("inf"), get=get, max_pages=c["pages"],
                                 now=now, cat="pozivi", job="novcanici")
        except Exception as e:  # noqa: BLE001 - one bad query must not stop the round
            log(f"novčanici X: upit nije uspio ({type(e).__name__}: {str(e)[:80]})")
            continue
        calls = [x for it in items for x in collect.calls_from_tweet(it, mint, None, "kol_nx") if x["token"] == mint]
        known = {h for (h,) in con.execute("SELECT handle FROM kols")} if calls else set()
        n += collect.save(con, calls)
        collect._searched(con, f"nx:{mint}", "novcanici", now)
        for h, w, bt, ts, delay in candidates(calls, bl, c["after_h"] * 3600):
            n_cand += con.execute("INSERT OR IGNORE INTO nx_kandidati VALUES (?,?,?,?,?,?,?,?)",
                                  (h, mint, w, bt, ts, delay, int(h in known), now)).rowcount
        con.commit()
    if n or n_cand:
        log(f"novčanici X: {n} novih poziva, {n_cand} kandidata (zvali nakon kupnje naših novčanika)")
    return n
