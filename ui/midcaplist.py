"""What the tool follows now (19.11., vlasnik: "Kome treba ova stranica... baš ništa na njoj nema"): the midcap list
and the pumps, read-only, for the Tokeni page, the Pregled block "Skočili nedavno" and the influencer call filter.

  midcap.db (veliki/midcap.py, run_veliki.py midcap)   tokens with member=1: symbol, MC, liquidity, 24 h volume, the
                                                        last pass (last_ts); the newest snap row per token for the 24 h
                                                        price change (one index seek per token: PRIMARY KEY (id, ts))
  tokenstranice.db pages                                the token's name (the token pages the tool already builds)
  insajderi.db i2_events                                the pumps: tier "pumpa15" (peak MC >= 15M) / "pumpa2" (2-15M),
                                                        t0, peak_ts, peak_x (1 + peak_x = the multiple), peak_mc
  insajderi.db i2_part + i2_pp                          per pump: how many owner groups classified "prije_pumpe"
                                                        (insajderi/prijepumpe.classify: owner = i2_part.owner, else the
                                                        wallet, exactly as score.aggregate) had a wallet that bought
                                                        before t0 (bought_before = 1)
  kol.db snaps                                          the newest market cap of a called token (mcap_now)

Never raises, never touches the network; every database is opened read-only and may be missing.
"""
import os
import sqlite3
import time

TIER_HI = 15e6          # insajderi/store.py focus_mcap: "Od 15 M $"
TIER_LO = 2e6           # pump2_mcap / veliki/config data_min_mcap: "2-15 M $"
RULE_MCAP = 30_000      # CLAUDE.md: tokens under 30k $ are not analysed
PUMP_DAYS = 7           # "U zadnjih 7 dana skočilo ih je N"
PUMP_LIST_DAYS = 30     # how far back the tab "Skočili nedavno" lists pumps
MC_FRESH_S = 3 * 86400  # mcap_now: an older reading is not "the market cap now"
STALE_S = 3600          # the list's own age shown as a date beyond this


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1")
        return con
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def paths():
    out = {}
    try:
        from veliki import midcap
        out["midcap"] = midcap.db_path()
    except Exception:  # noqa: BLE001
        out["midcap"] = None
    try:
        from insajderi import store as istore
        out["insajderi"] = istore.db_path()
    except Exception:  # noqa: BLE001
        out["insajderi"] = None
    try:
        from tokenstranice import store as tstore
        out["tokenstranice"] = tstore.db_path()
    except Exception:  # noqa: BLE001
        out["tokenstranice"] = None
    try:
        from kol import store as kstore
        out["kol"] = kstore.DB
    except Exception:  # noqa: BLE001
        out["kol"] = None
    return out


def tier(mc):
    if mc is None:
        return None
    if mc >= TIER_HI:
        return "15"
    if mc >= TIER_LO:
        return "2"
    return None


def _members(con):
    rows = _q(con, "SELECT mint, id, symbol, mcap, liq, vol24, last_ts FROM tokens WHERE member = 1")
    out = []
    for mint, tid, sym, mc, liq, v24, last in rows:
        ch = None
        if tid is not None:
            r = _q(con, "SELECT c24, mc, liq, ts FROM snap WHERE id = ? ORDER BY ts DESC LIMIT 1", (tid,))
            if r:
                ch = r[0][0]
                mc = r[0][1] if r[0][1] is not None and (r[0][3] or 0) >= (last or 0) else mc
                liq = r[0][2] if r[0][2] is not None and (r[0][3] or 0) >= (last or 0) else liq
        out.append({"mint": mint, "symbol": sym, "mcap": mc, "liq": liq, "vol24": v24, "last_ts": last, "c24": ch})
    return out


def _names(path, mints):
    con = _ro(path)
    if con is None:
        return {}
    try:
        out = {}
        ms = list(mints)
        for i in range(0, len(ms), 500):
            part = ms[i:i + 500]
            for m, nm in _q(con, f"SELECT mint, name FROM pages WHERE mint IN ({','.join('?' * len(part))})", part):
                if nm:
                    out[m] = nm
        return out
    finally:
        con.close()


def pumps(path, now, days=PUMP_LIST_DAYS):
    """[{eid, token, symbol, t0, peak_ts, pct, peak_mc, tier, groups}] newest first (tiered market jumps)."""
    con = _ro(path)
    if con is None:
        return []
    try:
        cols = {r[1] for r in _q(con, "PRAGMA table_info(i2_events)")}
        if "tier" not in cols:
            return []
        rows = _q(con, "SELECT eid, token, symbol, t0, peak_ts, peak_x, peak_mc, tier FROM i2_events "
                       "WHERE tier IN ('pumpa15', 'pumpa2') AND t0 >= ? ORDER BY t0 DESC", (int(now - days * 86400),))
        out = [{"eid": e, "token": tok, "symbol": sym, "t0": t0, "peak_ts": pk, "pct": (px * 100 if px is not None else None),
                "peak_mc": pmc, "tier": t, "groups": None} for e, tok, sym, t0, pk, px, pmc, t in rows]
        if out and _q(con, "SELECT name FROM sqlite_master WHERE name = 'i2_pp'") \
                and _q(con, "SELECT name FROM sqlite_master WHERE name = 'i2_part'"):
            eids = [p["eid"] for p in out]
            got = {}
            for i in range(0, len(eids), 500):
                part = eids[i:i + 500]
                for eid, n in _q(con, "SELECT p.eid, COUNT(DISTINCT COALESCE(p.owner, p.wallet)) FROM i2_part p "
                                      "JOIN i2_pp g ON g.owner = COALESCE(p.owner, p.wallet) "
                                      "WHERE g.cls = 'prije_pumpe' AND p.bought_before = 1 "
                                      f"AND p.eid IN ({','.join('?' * len(part))}) GROUP BY p.eid", part):
                    got[eid] = n
            for p in out:
                p["groups"] = got.get(p["eid"], 0)
        return out
    finally:
        con.close()


def load(now=None, p=None):
    """{"ok": midcap.db readable, "tokens": [...], "pumps": [...], "by_mint": {mint: newest pump}, "updated": ts,
    "n15", "n2", "pumped7": distinct tokens with a pump in PUMP_DAYS}."""
    now = now or time.time()
    p = p or paths()
    con = _ro(p.get("midcap"))
    toks = []
    if con is not None:
        try:
            toks = _members(con)
        finally:
            con.close()
    names = _names(p.get("tokenstranice"), [t["mint"] for t in toks]) if toks else {}
    for t in toks:
        t["name"] = names.get(t["mint"])
        t["tier"] = tier(t["mcap"])
    pl = pumps(p.get("insajderi"), now)
    by_mint = {}
    for x in pl:
        by_mint.setdefault(x["token"], x)
    for t in toks:
        t["pump"] = by_mint.get(t["mint"])
    sym = {t["mint"]: t for t in toks}
    for x in pl:
        m = sym.get(x["token"])
        x["mcap"] = m["mcap"] if m else None
        x["c24"] = m["c24"] if m else None
        x["liq"] = m["liq"] if m else None
        x["name"] = (m or {}).get("name") or names.get(x["token"])
        if m and m.get("symbol"):
            x["symbol"] = m["symbol"]
    upd = max((t["last_ts"] or 0 for t in toks), default=0) or None
    return {"ok": con is not None, "tokens": toks, "pumps": pl, "by_mint": by_mint, "updated": upd,
            "n15": sum(1 for t in toks if t["tier"] == "15"), "n2": sum(1 for t in toks if t["tier"] == "2"),
            "pumped7": len({x["token"] for x in pl if x["t0"] >= now - PUMP_DAYS * 86400 and x["token"] in sym})}


# ---------- the market cap now of any token (the influencer call filter) ---------------------------------------------

def mcap_now(mints, now=None, p=None):
    """{mint: (mcap, tracked)}: the newest market cap no older than MC_FRESH_S from midcap.db (tracked = a member),
    else kol.db's newest snap. A mint without a fresh reading is missing (unknown = not shown as current)."""
    now = now or time.time()
    p = p or paths()
    ms = [m for m in dict.fromkeys(mints or []) if m]
    out = {}
    if not ms:
        return out
    con = _ro(p.get("midcap"))
    if con is not None:
        try:
            for i in range(0, len(ms), 500):
                part = ms[i:i + 500]
                for m, mc, last, mem in _q(con, f"SELECT mint, mcap, last_ts, member FROM tokens WHERE mint IN "
                                                f"({','.join('?' * len(part))})", part):
                    if mc is not None and (last or 0) >= now - MC_FRESH_S:
                        out[m] = (mc, bool(mem))
        finally:
            con.close()
    rest = [m for m in ms if m not in out]
    con = _ro(p.get("kol"))
    if con is not None and rest:
        try:
            for i in range(0, len(rest), 500):
                part = rest[i:i + 500]
                for m, mc, ts in _q(con, "SELECT token, mcap, MAX(ts) FROM snaps WHERE token IN "
                                         f"({','.join('?' * len(part))}) GROUP BY token", part):
                    if mc is not None and (ts or 0) >= now - MC_FRESH_S:
                        out[m] = (mc, False)
        finally:
            con.close()
    return out


def split_calls(items, key, now=None, mc=None, p=None):
    """(shown, hidden) of call items: shown = market cap now known and >= RULE_MCAP, tracked midcaps (>= TIER_LO) first,
    otherwise in the given order; hidden = the rest (under 30k now, dead or unknown), in the given order. key(item) ->
    mint. Display only: the callers' statistics are computed elsewhere and never from this."""
    items = list(items or [])
    mc = mc if mc is not None else mcap_now([key(x) for x in items], now, p)
    shown, hidden = [], []
    for i, x in enumerate(items):
        v = mc.get(key(x))
        (shown if v and v[0] >= RULE_MCAP else hidden).append((i, x))
    shown.sort(key=lambda ix: (0 if (mc[key(ix[1])][1] and mc[key(ix[1])][0] >= TIER_LO) else 1, ix[0]))
    return [x for _i, x in shown], [x for _i, x in hidden]


def hidden_line(n):
    """"još N poziva na tokene koji danas vrijede ispod 30.000 $" (unknown and dead count with them)."""
    return f"još {n} {'poziv' if n % 10 == 1 and n % 100 != 11 else 'poziva'} na tokene koji danas vrijede ispod 30.000 $"


def info(mint, p=None):
    """(symbol, name) of a token from midcap.db / tokenstranice.db, (None, None) when neither knows it."""
    p = p or paths()
    sym = name = None
    con = _ro(p.get("midcap"))
    if con is not None:
        try:
            r = _q(con, "SELECT symbol FROM tokens WHERE mint = ?", (mint,))
            sym = r[0][0] if r else None
        finally:
            con.close()
    con = _ro(p.get("tokenstranice"))
    if con is not None:
        try:
            r = _q(con, "SELECT symbol, name FROM pages WHERE mint = ?", (mint,))
            if r:
                sym, name = sym or r[0][0], r[0][1]
        finally:
            con.close()
    return sym, name
