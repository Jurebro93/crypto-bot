"""5.11.: trending tokens as a daily source of callers. Who posted the CA of a token that is trending right now?
Those accounts called a winner, whether or not we follow them: the search (twitterapi.io, discover budget) makes
them KOL candidates like kol/discover.winners does for our own winners. The list also feeds the KOL backfill.

Sources (free): GeckoTerminal trending pools (Solana, 24 h, 3 pages) and DexScreener top boosts (paid promotion,
noted as such). Stored in kol.db `trending` (token, day, source, fdv, vol24, first_ts).
"""
import time

from kol import collect

SCHEMA = """CREATE TABLE IF NOT EXISTS trending (
    token TEXT, day TEXT, source TEXT, symbol TEXT, fdv REAL, vol24 REAL, first_ts INTEGER, PRIMARY KEY (token, day))"""
GT = "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools"
DEFAULT = {"pages": 3, "per_run": 10, "pages_x": 2, "back_d": 7, "usd": 0.4, "max_fdv": 100_000_000}


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("trending") or {})}


def fetch_gecko(get=None, pages=3):
    """[{token, symbol, fdv, vol24, created_ts}] from GeckoTerminal trending pools, best first."""
    from event_calendar import http
    get = get or (lambda url, params: http.get_json(url, params, ttl=600, headers={"Accept": "application/json"}))
    out, seen = [], set()
    for page in range(1, pages + 1):
        try:
            d = get(GT, {"page": page, "duration": "24h"})
        except Exception:  # noqa: BLE001
            break
        for p in (d or {}).get("data") or []:
            a = p.get("attributes") or {}
            tid = ((p.get("relationships") or {}).get("base_token") or {}).get("data", {}).get("id") or ""
            tok = tid.split("_", 1)[-1]
            if not tok or tok in seen:
                continue
            seen.add(tok)
            created = a.get("pool_created_at")
            try:
                import datetime as dt
                cts = int(dt.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()) if created else None
            except (ValueError, AttributeError):
                cts = None
            out.append({"token": tok, "symbol": (a.get("name") or "").split(" / ")[0][:20],
                        "fdv": float(a.get("fdv_usd") or 0), "vol24": float((a.get("volume_usd") or {}).get("h24") or 0),
                        "created_ts": cts})
    return out


def fetch_boosts(client=None):
    """[{token, symbol}] Solana tokens with the most active DexScreener boosts (paid)."""
    try:
        from dexscreener import client as dc
        rows = (client or dc.top_boosts)() or []
    except Exception:  # noqa: BLE001
        return []
    return [{"token": r.get("tokenAddress"), "symbol": "", "fdv": 0.0, "vol24": 0.0, "created_ts": None}
            for r in rows if r.get("chainId") == "solana" and r.get("tokenAddress")]


def collect_today(con, cfg, now=None, gecko=None, boosts=None):
    """Store today's trending list (both sources, majors and giant tokens left out). Returns new rows."""
    from kol import converge
    con.execute(SCHEMA)
    c = config(cfg)
    now = now or int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    skip = converge.majors()
    n = 0
    for src, rows in (("gecko", gecko if gecko is not None else fetch_gecko(pages=c["pages"])),
                      ("boost", boosts if boosts is not None else fetch_boosts())):
        for r in rows:
            if r["token"] in skip or (r.get("fdv") or 0) > c["max_fdv"]:
                continue
            cur = con.execute("INSERT OR IGNORE INTO trending VALUES (?,?,?,?,?,?,?)",
                              (r["token"], day, src, r.get("symbol") or "", r.get("fdv") or 0, r.get("vol24") or 0,
                               r.get("created_ts") or now))
            n += cur.rowcount
    con.commit()
    return n


def targets(con, cfg, now=None):
    """[(token, since_ts)] trending tokens (newest day first, gecko before boosts) not yet searched on X."""
    con.execute(SCHEMA)
    c = config(cfg)
    now = now or int(time.time())
    done = {t[6:] for (t,) in con.execute("SELECT target FROM searches WHERE target LIKE 'trend:%'")}
    out = []
    for tok, first in con.execute("SELECT token, MIN(first_ts) FROM trending GROUP BY token "
                                  "ORDER BY MAX(day) DESC, MIN(source = 'gecko') DESC, MAX(vol24) DESC"):
        if tok not in done:
            out.append((tok, max(first or now, now - c["back_d"] * 86400)))
    return out


def search(con, cfg, get=None, now=None, log=print):
    """Who posted each trending token's CA in the last back_d days (twitterapi.io, discovery budget, own daily cap
    trending.usd). New calls become kol.db calls with source 'kol_trend'; the authors become KOL candidates."""
    from kol import discover, twapi
    if not twapi.key() and get is None:
        return 0
    c = config(cfg)
    now = now or int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    row = con.execute("SELECT value FROM kv WHERE key = ?", (f"twtrend:{day}",)).fetchone()
    mine = float(row[0]) if row else 0.0
    n = 0
    for tok, since in targets(con, cfg, now)[:c["per_run"]]:
        left = min(c["usd"] - mine, discover.disc_left(con, cfg, now))
        if left <= 0:
            break
        before = twapi.spent(con, now)
        try:
            items = twapi.search(con, tok, since, before + left, get=get, max_pages=c["pages_x"], now=now)
        except Exception as e:  # noqa: BLE001
            log(f"trending: upit nije uspio ({type(e).__name__}: {e})")
            items = []
        mine += discover._charge(con, now, before)
        collect._searched(con, f"trend:{tok}", "trending", now)
        n += collect.save(con, [cl for it in items for cl in collect.calls_from_tweet(it, tok, None, "kol_trend")])
    con.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"twtrend:{day}", str(mine)))
    con.commit()
    return n


def for_backfill(con, now=None):
    """Trending tokens as backfill entries (kol/backfill.pick): every one counts as a winner."""
    con.execute(SCHEMA)
    now = now or int(time.time())
    out = []
    for tok, sym, first, vol in con.execute("SELECT token, MAX(symbol), MIN(first_ts), MAX(vol24) FROM trending GROUP BY token"):
        launch = int(first or now - 7 * 86400)
        out.append({"mint": tok, "symbol": sym, "launch_ts": launch, "peak_ts": now, "peak_mult": 1 + (vol or 0) / 1e6,
                    "winner": True, "trending": True})
    return out
