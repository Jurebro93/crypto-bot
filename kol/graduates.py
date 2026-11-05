"""5.11. (Nicholas): graduated pump.fun tokens ("bondali", now trading on PumpSwap) as a standing pool of tokens that
did NOT die at launch: the history to learn from, the place to find the wallets that bought them early, and the
link to today's wallets and callers. Source: GeckoTerminal pools of the pumpswap DEX (free, 20 per page), read
every KOL round by activity; the table only grows (kol.db graduates). Live graduations also arrive from PumpPortal
(hype.db live_launches, pool 'migration').
"""
import datetime as dt
import time

GT = "https://api.geckoterminal.com/api/v2/networks/solana/dexes/pumpswap/pools"
SCHEMA = """CREATE TABLE IF NOT EXISTS graduates (
    token TEXT PRIMARY KEY, pool TEXT, symbol TEXT, created_ts INTEGER, fdv REAL, vol24 REAL, first_seen INTEGER,
    source TEXT, seen INTEGER DEFAULT 1)"""
DEFAULT = {"pages": 5, "sorts": ["h24_tx_count_desc", "h24_volume_usd_desc"], "min_fdv": 30000}


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("graduates") or {})}


def fetch(get=None, pages=5, sorts=("h24_tx_count_desc",)):
    """[{token, pool, symbol, created_ts, fdv, vol24}] from the pumpswap pool listing, deduplicated."""
    from event_calendar import http
    get = get or (lambda url, params: http.get_json(url, params, ttl=900, headers={"Accept": "application/json"}))
    out, seen = [], set()
    for sort in sorts:
        for page in range(1, pages + 1):
            try:
                d = get(GT, {"page": page, "sort": sort})
            except Exception:  # noqa: BLE001
                break
            rows = (d or {}).get("data") or []
            if not rows:
                break
            for p in rows:
                a = p.get("attributes") or {}
                tid = ((p.get("relationships") or {}).get("base_token") or {}).get("data", {}).get("id") or ""
                tok = tid.split("_", 1)[-1]
                if not tok or tok in seen:
                    continue
                seen.add(tok)
                created = a.get("pool_created_at")
                try:
                    cts = int(dt.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()) if created else None
                except (ValueError, AttributeError):
                    cts = None
                out.append({"token": tok, "pool": a.get("address"), "symbol": (a.get("name") or "").split(" / ")[0][:20],
                            "created_ts": cts, "fdv": float(a.get("fdv_usd") or 0),
                            "vol24": float((a.get("volume_usd") or {}).get("h24") or 0)})
    return out


def collect(con, cfg=None, now=None, rows=None):
    """Store what the listing shows now (majors and tiny FDV left out). Returns new tokens."""
    from kol import converge
    con.execute(SCHEMA)
    c = config(cfg)
    now = now or int(time.time())
    skip = converge.majors()
    n = 0
    for r in (rows if rows is not None else fetch(pages=c["pages"], sorts=c["sorts"])):
        if r["token"] in skip or (r.get("fdv") or 0) < c["min_fdv"]:
            continue
        cur = con.execute("INSERT INTO graduates VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(token) DO UPDATE SET "
                          "fdv=excluded.fdv, vol24=MAX(vol24, excluded.vol24), seen=seen+1, pool=COALESCE(graduates.pool, excluded.pool)",
                          (r["token"], r.get("pool"), r.get("symbol"), r.get("created_ts") or now, r.get("fdv") or 0,
                           r.get("vol24") or 0, now, "gecko_pumpswap"))
        if cur.rowcount and con.execute("SELECT seen FROM graduates WHERE token=?", (r["token"],)).fetchone()[0] == 1:
            n += 1
    con.commit()
    return n


def tokens(con, since_ts=None, limit=5000):
    """[(token, pool, created_ts, symbol, fdv)] newest first, for the shadow book and the wallet harvest."""
    try:
        con.execute(SCHEMA)
    except Exception:  # noqa: BLE001
        pass
    q = "SELECT token, pool, created_ts, symbol, fdv FROM graduates"
    args = []
    if since_ts:
        q += " WHERE created_ts >= ?"
        args.append(int(since_ts))
    q += " ORDER BY created_ts DESC LIMIT ?"
    args.append(limit)
    try:
        return con.execute(q, args).fetchall()
    except Exception:  # noqa: BLE001
        return []
