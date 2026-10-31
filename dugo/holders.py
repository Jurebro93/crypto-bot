"""Big holders of the long-term tokens, organic holder counts and exchange listings.

Nicholas 2026-10-31: the holders of the survivors are the bigger players. What do they buy (small tokens too),
whose calls do they follow, does the number of real holders keep growing, does the token get listed on exchanges.

- Top holders: Helius getTokenLargestAccounts (top 20 token accounts) + getMultipleAccounts to resolve owners and
  drop pools/vaults (owner not a normal wallet). ~3 credits per token, once a week per token: a sample, not a crawl.
  An address in the top holders of many tokens is a custodian or exchange and is labelled so in the wallet registry.
- Their trades come from the wallet registry (run_wallets scores them within its own Helius budget, role big_holder).
- Holder count and spread: GeckoTerminal token info (free): number of holders and the share held outside the top 40.
  A growing count with a growing "rest" share is organic growth; growth that all lands in the top 10 is not.
- Listings: CoinGecko's free coin-by-contract endpoint (tickers), weekly.
"""
import json
import os
import sqlite3
import time
import urllib.parse

from event_calendar import http

D = 86400
SYSTEM = "11111111111111111111111111111111"
TOP_CEX = {"binance", "gdax", "coinbase", "okex", "okx", "bybit_spot", "bybit", "kucoin", "gate", "bitget", "mxc",
           "mexc", "huobi", "htx", "kraken", "upbit", "bithumb", "crypto_com", "bingx", "robinhood"}
DEX_HINTS = ("raydium", "orca", "meteora", "pump", "jupiter", "lifinity", "phoenix", "openbook", "saber", "dex", "swap",
             "fluxbeam", "solfi", "goosefx", "invariant", "crema")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rpc(method, params):
    from rugfilter import helius
    return helius.rpc(method, params)


def top_holders(mint, n=20):
    """[(wallet, ui_amount)] of the largest holders that are ordinary wallets (pools, vaults, programs dropped)."""
    res = _rpc("getTokenLargestAccounts", [mint])
    accts = [(a["address"], float(a.get("uiAmount") or 0)) for a in (res.get("value") or [])][:n]
    if not accts:
        return []
    info = _rpc("getMultipleAccounts", [[a for a, _ in accts], {"encoding": "jsonParsed"}]).get("value") or []
    owners = []
    for (addr, amt), acc in zip(accts, info):
        try:
            owners.append((acc["data"]["parsed"]["info"]["owner"], amt))
        except (TypeError, KeyError):
            continue
    if not owners:
        return []
    kinds = _rpc("getMultipleAccounts", [[o for o, _ in owners], {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}]
                 ).get("value") or []
    out = {}
    for (o, amt), acc in zip(owners, kinds):
        # a normal wallet is owned by the system program; None = never funded with SOL but still a keypair wallet
        if acc is None or acc.get("owner") == SYSTEM:
            out[o] = out.get(o, 0) + amt
    return sorted(out.items(), key=lambda x: -x[1])


def holder_info(mint, gap=6):
    """(holders, top-10 share %, share outside the top 40 %) from GeckoTerminal's free token info, or None."""
    from dugo import sources
    d = sources._gecko(f"/tokens/{mint}/info", gap)
    h = ((d.get("data") or {}).get("attributes") or {}).get("holders") or {}
    if not h.get("count"):
        return None
    dist = h.get("distribution_percentage") or {}
    f = lambda k: float(dist[k]) if dist.get(k) not in (None, "") else None  # noqa: E731
    return int(h["count"]), f("top_10"), f("rest")


def listings(mint):
    """(top exchanges, all centralised exchanges, names) from CoinGecko, or None when CoinGecko doesn't list it."""
    try:
        d = http.get_json(f"https://api.coingecko.com/api/v3/coins/solana/contract/{urllib.parse.quote(mint)}",
                          ttl=6 * 3600, retries=1)
    except Exception:
        return None
    cex = set()
    for t in d.get("tickers") or []:
        m = (t.get("market") or {})
        ident = (m.get("identifier") or "").lower()
        if ident and not any(h in ident for h in DEX_HINTS):
            cex.add(ident)
    top = sorted(cex & TOP_CEX)
    return len(top), len(cex), sorted(cex)


# ---------- reading the wallet registry (written by run_wallets) ----------

def _wallets_ro():
    p = os.environ.get("WALLET_DB", os.path.join(HERE, "wallets.db"))
    if not os.path.exists(p):
        return None
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)


def _kol_ro():
    p = os.environ.get("KOL_DB", os.path.join(HERE, "kol.db"))
    if not os.path.exists(p):
        return None
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)


def whale_wallets(con):
    """{wallet: [long-term token mints it is a top holder of]} from the last 45 days, custodians excluded."""
    out = {}
    for w, mint, lab in con.execute("""SELECT wallet, mint, label FROM big_holders WHERE day >= ?""",
                                    (int(time.time()) - 45 * D,)):
        if lab != "skrbnik":
            out.setdefault(w, set()).add(mint)
    return {w: sorted(m) for w, m in out.items()}


def whale_buys(con, days=14, now=None):
    """{mint: {"n": distinct big-holder wallets that bought it, "sol": total SOL, "wallets": [...], "first": ts}}
    for every token (small ones too) bought by big holders of the long-term tokens in the last `days`."""
    now = now or time.time()
    whales = whale_wallets(con)
    w = _wallets_ro()
    if not whales or w is None:
        return {}
    out = {}
    try:
        qs = ",".join("?" * len(whales))
        for wallet, mint, sol, ts in w.execute(f"""SELECT wallet, mint, sol, ts FROM wallet_trades
                WHERE kind='buy' AND ts >= ? AND wallet IN ({qs})""", (now - days * D, *whales)):
            if mint in whales[wallet]:      # topping up its own long-term bag is not a new pick
                continue
            r = out.setdefault(mint, {"n": 0, "sol": 0.0, "wallets": set(), "first": ts, "buys": []})
            r["wallets"].add(wallet)
            r["sol"] += abs(sol or 0)
            r["first"] = min(r["first"], ts)
            r["buys"].append((wallet, ts))
    except sqlite3.Error:
        return {}
    finally:
        w.close()
    for r in out.values():
        r["n"] = len(r["wallets"])
        r["wallets"] = sorted(r["wallets"])
    return out


def followed_kols(buys, window_h=6):
    """Which KOL calls big holders buy after: {handle: {"buys": n, "wallets": n, "tokens": n}} where a buy came within
    `window_h` hours after the KOL's call of the same token (kol.db, X and Telegram)."""
    k = _kol_ro()
    if k is None or not buys:
        return {}
    out = {}
    try:
        for mint, r in buys.items():
            calls = k.execute("SELECT handle, ts FROM calls WHERE token=? AND (kind IS NULL OR kind!='brag')", (mint,)).fetchall()
            for wallet, ts in r["buys"]:
                for handle, cts in calls:
                    if 0 <= ts - cts <= window_h * 3600:
                        h = out.setdefault(handle, {"buys": 0, "wallets": set(), "tokens": set()})
                        h["buys"] += 1
                        h["wallets"].add(wallet)
                        h["tokens"].add(mint)
    except sqlite3.Error:
        return {}
    finally:
        k.close()
    return {h: {"buys": v["buys"], "wallets": len(v["wallets"]), "tokens": len(v["tokens"])} for h, v in out.items()}


def exchange_share(con, mint, now=None):
    """(share of supply held by exchange/custodian addresses among the top holders now, change vs a reading at least
    7 days older). Burze often receive a large part of the supply before a listing; sellers moving to an exchange look
    the same, so this is a learned signal, not a rule."""
    now = now or time.time()
    days = [d for (d,) in con.execute("SELECT DISTINCT day FROM big_holders WHERE mint=? ORDER BY day DESC", (mint,))]
    if not days:
        return None, None

    def share(d):
        return con.execute("SELECT COALESCE(SUM(share), 0) FROM big_holders WHERE mint=? AND day=? AND label='skrbnik'",
                           (mint, d)).fetchone()[0]
    now_s = share(days[0])
    old = next((d for d in days[1:] if d <= days[0] - 7 * D), None)
    return now_s, (now_s - share(old) if old is not None else None)


def signals(path=None, days=14):
    """For other modules (hype scanner): {mint: number of distinct big holders of long-term tokens that bought it in
    the last `days`}. Read-only; {} when dugo.db or the registry is missing."""
    from dugo import store
    con = store.ro(path)
    if con is None:
        return {}
    try:
        return {m: r["n"] for m, r in whale_buys(con, days).items()}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


# ---------- the weekly pass (run_dugo.py) ----------

def refresh(con, cfg, now=None, log=print):
    """Top holders, organic holder counts and listings for the best tokens of both lists, each at most once a week."""
    now = int(now or time.time())
    day = now // D * D
    h = cfg["holderi"]
    if not os.environ.get("HELIUS_API_KEY"):
        log("holderi: nema Helius ključa, preskačem")
        return
    snap_day = con.execute("SELECT MAX(day) FROM snap").fetchone()[0]
    rows = con.execute("""SELECT s.mint, MAX(s.price), MIN(s.rank) FROM snap s WHERE s.day=? AND s.rank <= ?
        GROUP BY s.mint ORDER BY MIN(s.rank)""", (snap_day, h["top_tokena"])).fetchall()
    done_h = done_c = done_l = 0
    gecko_blocked = False
    for mint, price, _ in rows:
        last = con.execute("SELECT MAX(day) FROM big_holders WHERE mint=?", (mint,)).fetchone()[0] or 0
        if last <= now - h["svakih_d"] * D:
            try:
                hold = top_holders(mint)
                supply = float(_rpc("getTokenSupply", [mint])["value"].get("uiAmount") or 0)
                con.executemany("INSERT OR REPLACE INTO big_holders (mint, day, wallet, amount, usd, share) VALUES (?,?,?,?,?,?)",
                                [(mint, day, w, a, a * (price or 0), a / supply if supply else None) for w, a in hold])
                done_h += 1
            except Exception as e:
                log(f"holderi {mint[:6]}: {e}")
        lastc = con.execute("SELECT MAX(day) FROM holder_info WHERE mint=?", (mint,)).fetchone()[0] or 0
        if lastc <= now - h["info_svakih_d"] * D and not gecko_blocked:
            try:
                r = holder_info(mint, cfg["gecko_gap_s"])
                if r:
                    con.execute("INSERT OR REPLACE INTO holder_info VALUES (?,?,?,?,?)", (mint, day, *r))
                    done_c += 1
            except Exception as e:
                log(f"broj holdera {mint[:6]}: {e}")
                gecko_blocked = "429" in str(e)     # free limit used up: next pass
        lastl = con.execute("SELECT MAX(day) FROM listings WHERE mint=?", (mint,)).fetchone()[0] or 0
        if lastl <= now - h["svakih_d"] * D and done_l < h["coingecko_po_prolazu"]:
            r = listings(mint)
            done_l += 1
            con.execute("INSERT OR REPLACE INTO listings VALUES (?,?,?,?,?)",
                        (mint, day, *(r[:2] if r else (0, 0)), json.dumps(r[2] if r else [])))
            time.sleep(h["coingecko_razmak_s"])
        con.commit()
    # an address among the top holders of many different tokens is an exchange or custodian, not a player
    con.execute("UPDATE big_holders SET label=NULL")
    con.execute(f"""UPDATE big_holders SET label='skrbnik' WHERE wallet IN (SELECT wallet FROM big_holders
        WHERE day >= ? GROUP BY wallet HAVING COUNT(DISTINCT mint) >= ?)""", (now - 45 * D, h["skrbnik_tokena"]))
    con.commit()
    log(f"holderi: top holderi za {done_h}, broj holdera za {done_c}, burze za {done_l} tokena")
