"""Token status: does the token still have a DexScreener pair, the exact pair page, a fresh market cap, and a
GeckoTerminal fallback when DexScreener dropped it.

7.11. (Jure): the DexScreener icon next to "SpaceX" opened nothing: the token has no pair any more (GeckoTerminal:
fdv $7k, no volume), and the table still showed its last known $69.5k. Of 475 tokens on /tokens, 296 had no pair.
A 6-hourly pass checks every listed token (30 per DexScreener call, free) and, for the ones without a pair, asks
GeckoTerminal for the token (free, 30/min). Pages read token_status: the icon goes to the exact pair page, a dead
token says so, the market cap column shows the freshest number and where it came from.

    python3 run_hype.py status            # one pass (run_sched: every TOKENSTATUS_EVERY_MIN, default 360)
"""
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HYPE_DB = os.path.join(os.environ.get("DATA_DIR") or ROOT, "hype.db")
SCHEMA = """CREATE TABLE IF NOT EXISTS token_status (
    token TEXT PRIMARY KEY, has_pair INTEGER, pair_url TEXT, dex_id TEXT, price REAL, mcap REAL, liq REAL,
    gt_price REAL, gt_fdv REAL, gt_vol24 REAL, checked_ts INTEGER, gt_checked_ts INTEGER)"""
DAYS = 14          # tokens seen in signals this recently are checked
MAX_TOKENS = 900   # per pass (30 DexScreener calls)
MAX_GT = 40        # GeckoTerminal lookups per pass for tokens without a pair (30/min shared with the KOL cycle)


def ensure(con):
    con.execute(SCHEMA)


def listed_tokens(con, now=None, extra=()):
    """Tokens a page may show: recent signals, event tokens, open demo and strategy positions."""
    now = now or time.time()
    toks = {t for (t,) in con.execute("SELECT DISTINCT token FROM hype_signals WHERE ts >= ?", (now - DAYS * 86400,))}
    toks |= set(extra)
    for path, sql in ((os.path.join(os.path.dirname(HYPE_DB), "calendar.db"), "SELECT DISTINCT token FROM event_tokens"),
                      (os.path.join(os.path.dirname(HYPE_DB), "paper.db"), "SELECT token FROM trades WHERE status='open'"),
                      (os.path.join(os.path.dirname(HYPE_DB), "strat.db"), "SELECT token FROM positions WHERE status='open'")):
        try:
            c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                toks |= {r[0] for r in c.execute(sql) if r[0]}
            finally:
                c.close()
        except sqlite3.Error:
            pass
    return sorted(t for t in toks if t)


def dex_lookup(tokens):
    """{token: {pair_url, dex_id, price, mcap, liq}} for tokens DexScreener still prices (deepest pair)."""
    from dexscreener import client
    out = {}
    for p in client.tokens("solana", tokens):
        if not p or p.get("chainId") != "solana":
            continue
        t = (p.get("baseToken") or {}).get("address")
        liq = (p.get("liquidity") or {}).get("usd") or 0
        if t and liq >= out.get(t, {}).get("liq", -1):
            out[t] = {"pair_url": p.get("url"), "dex_id": p.get("dexId"), "price": float(p.get("priceUsd") or 0),
                      "mcap": p.get("marketCap") or p.get("fdv") or 0, "liq": liq}
    return out


def gt_lookup(token):
    """GeckoTerminal token info (price, fdv, 24 h volume) or None."""
    from event_calendar import http
    from kol import measure
    measure._GT.wait()
    try:
        d = http.get_json(f"{measure.GECKO}/tokens/{token}", {}, ttl=3600, headers={"Accept": "application/json"}, retries=0)
    except Exception:  # noqa: BLE001
        return None
    a = ((d or {}).get("data") or {}).get("attributes") or {}
    if not a:
        return None
    try:
        return {"gt_price": float(a.get("price_usd") or 0), "gt_fdv": float(a.get("fdv_usd") or 0),
                "gt_vol24": float((a.get("volume_usd") or {}).get("h24") or 0)}
    except (TypeError, ValueError):
        return None


def refresh(con, now=None, tokens=None, dex=None, gt=None, log=print):
    """One pass. Returns (checked, with_pair, gt_filled)."""
    now = int(now or time.time())
    ensure(con)
    toks = (tokens if tokens is not None else listed_tokens(con, now))[:MAX_TOKENS]
    dex = dex or dex_lookup
    gt = gt or gt_lookup
    found = {}
    for i in range(0, len(toks), 30):
        try:
            found.update(dex(toks[i:i + 30]))
        except Exception as e:  # noqa: BLE001
            log(f"status: DexScreener: {type(e).__name__}: {e}")
    # 7.11. 09:32: the first version kept ONE write transaction open across 120 GeckoTerminal lookups (~6 min) and
    # locked hype.db for the live feed and the scanner ("database is locked"). 11:35: and the second wrote nothing
    # until every GeckoTerminal lookup was done, which behind the shared 30/min gate (KOL round, masovno) took 30+
    # min, so the pages never saw "nema para". Now: DexScreener results are written at once (short commits), then
    # each GeckoTerminal answer is written as it comes.
    for t in toks:
        d = found.get(t)
        if d:
            con.execute("INSERT INTO token_status (token, has_pair, pair_url, dex_id, price, mcap, liq, checked_ts) "
                        "VALUES (?,1,?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET has_pair=1, pair_url=excluded.pair_url, "
                        "dex_id=excluded.dex_id, price=excluded.price, mcap=excluded.mcap, liq=excluded.liq, "
                        "checked_ts=excluded.checked_ts", (t, d["pair_url"], d["dex_id"], d["price"], d["mcap"], d["liq"], now))
        else:
            con.execute("INSERT INTO token_status (token, has_pair, checked_ts) VALUES (?,0,?) ON CONFLICT(token) DO UPDATE "
                        "SET has_pair=0, checked_ts=excluded.checked_ts", (t, now))
    con.commit()
    log(f"status: provjereno {len(toks)} tokena, s parom {len(found)}, bez para {len(toks) - len(found)}; GeckoTerminal slijedi")
    n_gt = 0
    for t in toks:
        if t in found or n_gt >= MAX_GT:
            continue
        last = (con.execute("SELECT gt_checked_ts FROM token_status WHERE token=?", (t,)).fetchone() or (None,))[0] or 0
        if now - last < 6 * 3600:
            continue
        n_gt += 1
        g = gt(t)
        if g:
            con.execute("UPDATE token_status SET gt_price=?, gt_fdv=?, gt_vol24=?, gt_checked_ts=? WHERE token=?",
                        (g["gt_price"], g["gt_fdv"], g["gt_vol24"], now, t))
        else:
            con.execute("UPDATE token_status SET gt_checked_ts=? WHERE token=?", (now, t))
        con.commit()
    log(f"status: gotovo, GeckoTerminal {n_gt} tokena bez para")
    return len(toks), len(found), n_gt


def read(path=None, log=print):
    """{token: row dict} for the pages; {} when the table does not exist yet. 7.11. 11:50: a /tokens build during the
    status job's writes got {} and drew every token as alive, silently; now three tries 2 s apart, and the failure
    is logged, so the pages say why a dead token looks alive."""
    last = None
    for attempt in range(3):
        try:
            con = sqlite3.connect(f"file:{path or HYPE_DB}?mode=ro", uri=True, timeout=15)
            try:
                con.row_factory = sqlite3.Row
                return {r["token"]: dict(r) for r in con.execute("SELECT * FROM token_status")}
            finally:
                con.close()
        except sqlite3.Error as e:
            last = e
            if "no such table" in str(e):
                return {}
            time.sleep(2)
    log(f"status: čitanje nije uspjelo: {type(last).__name__}: {last}")
    return {}


def market_cell(status, mcap, now=None):
    """(text, sort value, class) for a market-cap column: the freshest number and, for a dead token, the truth."""
    from ui.html import ago, usd
    now = now or time.time()
    s = status
    if not s:
        return usd(mcap)
    if s.get("has_pair"):
        v = s.get("mcap") or mcap
        return usd(v)
    if s.get("gt_fdv"):
        txt, val, cls = usd(s["gt_fdv"])
        return (f'{txt} <small class=mut title="DexScreener više nema par; vrijednost s GeckoTerminala">GT</small>', val, cls)
    return (f'<span class=mut title="DexScreener više nema par za ovaj token (provjereno {ago(s.get("checked_ts"))[0]})">'
            f'nema para</span>', -1, "n")
