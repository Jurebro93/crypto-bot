"""One pass of the market scanner (run_scan.py once, every SCAN_EVERY_S from start.sh). Flag market_scan off: the
pass returns at once, before any database or network is touched.

Discovery (cheapest first; everything but GeckoTerminal is free or already paid for by another job):
  pumpportal   hype.db live_launches pool 'migration' (bonded in the last 6 h, free PumpPortal event) and live_trades
               of the last hour (the tokens run_live is subscribed to; the scanner adds no subscription, so the
               PumpPortal SOL budget LIVE_MAX_TRADES_DAY is unchanged)
  hype         hype.db hype_signals of the last 15 min (the hype scan's pump.fun boards, already paid on Apify)
  graduates    kol.db graduates first seen in the last 24 h (the KOL round's PumpSwap pool listing)
  launch10k    new pump.fun launches that reached 10k at their +10/+30/+90 min check (kol/precall.py, flag insider_copy)
  dexscreener  latest token profiles and boosts (free API), Solana only; their descriptions feed the meta keywords
  gecko        one page of pump.fun curve pools and one of PumpSwap pools by volume, every gt_every_min, inside the
               scanner's own GeckoTerminal day cap gt_calls_day (the paid CoinGecko day budget is shared with the bot)
  caller/wallet the signals of the last minutes (kol/converge.events: X, Telegram; buys of followed wallets): the
               baseline the scanner is compared with, under the same filters (filters.py: why_sig)
Pricing: DexScreener tokens (free, 60 s scanner cache, 30 tokens a call) for the candidates and every open shadow /
beta row in one batch; GeckoTerminal's numbers when DexScreener has no pair; PumpPortal's last trade otherwise.
Per token cache: a token is checked again only after recheck_min (10 min); a new caller / wallet signal is always
checked (DexScreener is free and the Helius facts have their own FACTS_TTL_H cache).
"""
import json
import os
import sqlite3
import statistics
import time

from scan import filters, meta, shadow, store

WSOL = "So11111111111111111111111111111111111111112"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"


def log(msg):
    print(f"skener: {msg}", flush=True)


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def paths():
    from league import store as lstore
    root = store.ROOT
    return {"hype": os.environ.get("HYPE_DB") or os.path.join(root, "hype.db"),
            "kol": os.environ.get("KOL_DB") or os.path.join(root, "kol.db"),
            "tg": os.environ.get("TG_DB") or os.path.join(root, "tg.db"),
            "league": lstore.DB,
            "wallets": os.environ.get("WALLET_DB") or os.path.join(root, "wallets.db")}


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


class Net:
    """The network seams: the offline tests replace each with a stand-in."""

    def dex_pairs(self, tokens):
        from dexscreener import client
        return client.tokens("solana", list(tokens))

    def dex_lists(self):
        from dexscreener import client
        out = []
        for fn in (client.latest_token_profiles, client.latest_boosts):
            try:
                out += list(fn() or [])
            except Exception:  # noqa: BLE001 - discovery is best effort
                pass
        return out

    def gt(self, path, params):
        from event_calendar import http
        return http.get_json(f"{GT}{path}", params, ttl=600, headers={"Accept": "application/json"}, retries=1)

    def helius(self, method, params):
        from rugfilter import helius
        return helius.rpc(method, params)

    def helius_ready(self):
        return bool(os.environ.get("HELIUS_API_KEY"))

    x_get = None   # kol/twapi._get (the tests pass their own)

    def kandidati(self, now):
        """10.11.: the combined candidate list, ranked (ui/kandidati.build); a test net without this method skips the
        combined shadow log."""
        from ui import kandidati
        return kandidati.build(now, details=False)[0]


# ---------- discovery -------------------------------------------------------------------------------------------

def _add(c, tok, via, **kw):
    if not tok:
        return None
    d = c.setdefault(tok, {"via": set(), "signals": {}})
    d["via"].add(via)
    for k, v in kw.items():
        if v is not None and d.get(k) is None:
            d[k] = v
    return d


def from_pumpportal(hc, now, cfg, c):
    curve = set(cfg["curve_pools"])
    for mint, name, sym in _q(hc, "SELECT mint, name, symbol FROM live_launches WHERE pool='migration' AND ts >= ? "
                                  "ORDER BY ts DESC LIMIT 100", (int(now) - 6 * 3600,)):
        _add(c, mint, "pumpportal", name=name or None, symbol=sym or None, migrated=True)
    for mint, _ts, pool, mcap_sol, px, n, uniq, vol, buys in _q(
            hc, "SELECT mint, MAX(ts), pool, mcap_sol, price_sol, COUNT(*), COUNT(DISTINCT wallet), SUM(sol), "
                "SUM(side='buy') FROM live_trades WHERE ts >= ? GROUP BY mint ORDER BY SUM(sol) DESC LIMIT 150",
                (int(now) - 3600,)):
        d = _add(c, mint, "pumpportal")
        d["pp"] = {"pool": pool, "mcap_sol": mcap_sol, "price_sol": px, "trades": n, "wallets": uniq,
                   "vol_sol": vol, "buys": buys, "curve": (pool or "pump") in curve}
        if pool and pool not in curve:
            d["migrated"] = True


def from_hype(hc, now, c):
    for tok, _ts, sym, name in _q(hc, "SELECT token, MAX(ts), symbol, name FROM hype_signals WHERE ts >= ? "
                                      "GROUP BY token ORDER BY MAX(ts) DESC LIMIT 80", (int(now) - 900,)):
        _add(c, tok, "hype", symbol=sym, name=name)


def from_graduates(kc, now, cfg, c):
    for tok, sym, fdv in _q(kc, "SELECT token, symbol, fdv FROM graduates WHERE first_seen >= ? AND fdv >= ? "
                                "ORDER BY first_seen DESC LIMIT 60",
                            (int(now) - 86400, float(cfg["final_stretch_min_mcap"]))):
        _add(c, tok, "graduates", symbol=sym, migrated=True)


def from_launches(now, c):
    """10.11. (Jure, flag insider_copy, kol/precall.py): new pump.fun launches the +10/+30/+90 min DexScreener checks
    saw at 10k or more in the last promote_h hours. On the curve they are final_stretch: measured, never tradeable."""
    try:
        from kol import precall
        rows = precall.reached(now)
    except Exception as e:  # noqa: BLE001 - discovery is best effort
        log(f"lansiranja od 10k: {type(e).__name__}: {str(e)[:80]}")
        rows = []
    for mint, sym in rows:
        _add(c, mint, "launch10k", symbol=sym or None)


def from_dex_lists(items, c, con, now):
    for it in items or []:
        if not isinstance(it, dict) or it.get("chainId") != "solana" or not it.get("tokenAddress"):
            continue
        tok = it["tokenAddress"]
        _add(c, tok, "dexscreener")
        if it.get("description"):
            con.execute("INSERT OR REPLACE INTO profiles VALUES (?,?,?)", (tok, int(now), str(it["description"])[:500]))


def gt_market(p, cfg):
    """A GeckoTerminal pool -> market dict (filters.py), or None."""
    a = p.get("attributes") or {}
    rel = p.get("relationships") or {}
    tok = (((rel.get("base_token") or {}).get("data") or {}).get("id") or "").split("_", 1)[-1]
    dex = ((rel.get("dex") or {}).get("data") or {}).get("id") or ""
    if not tok:
        return None
    tx = a.get("transactions") or {}
    h1, m5 = tx.get("h1") or {}, tx.get("m5") or {}
    vol, ch = a.get("volume_usd") or {}, a.get("price_change_percentage") or {}
    b, s = int(h1.get("buys") or 0), int(h1.get("sells") or 0)
    return {"token": tok, "symbol": (a.get("name") or "").split(" / ")[0][:20], "name": None,
            "price": _f(a.get("base_token_price_usd")), "mcap": _f(a.get("market_cap_usd")) or _f(a.get("fdv_usd")),
            "liq": _f(a.get("reserve_in_usd")) or 0.0, "vol_m5": _f(vol.get("m5")) or 0.0,
            "vol_h1": _f(vol.get("h1")) or 0.0, "vol_h24": _f(vol.get("h24")) or 0.0,
            "txns_m5": int(m5.get("buys") or 0) + int(m5.get("sells") or 0), "txns_h1": b + s, "buys_h1": b,
            "sells_h1": s, "buyers_h1": h1.get("buyers"), "ch_m5": _f(ch.get("m5")), "ch_h1": _f(ch.get("h1")),
            "ch_h24": _f(ch.get("h24")), "dex": dex, "curve": dex in set(cfg["curve_dex_ids"]), "src": "gecko"}


def gt_take(con, now, cfg, n=1):
    """One GeckoTerminal call from the scanner's own day budget (sliced by the hour); counted in scan.db and in the
    usage meter (service coingecko: the paid plan is flat, so the amount is 0 and the calls are what is watched)."""
    if store.budget_left(con, "gt", cfg["gt_calls_day"], now) < n:
        return False
    store.add_spent(con, "gt", n, now)
    try:
        from usage import meter
        meter.record("coingecko", "skener", 0.0, calls=n)
    except Exception:  # noqa: BLE001
        pass
    return True


def from_gecko(net, con, now, cfg, c, gt_rows):
    """Every gt_every_min one page per phase (gt_pages: the pump.fun curve by transactions, PumpSwap by volume)."""
    last = _f(store.kv_get(con, "last_gt_ts")) or 0
    if now - last < float(cfg["gt_every_min"]) * 60:
        return 0
    store.kv_set(con, "last_gt_ts", int(now))
    n = 0
    for stage, (dex, sort) in (cfg.get("gt_pages") or {}).items():
        if not gt_take(con, now, cfg):
            break
        n += 1
        try:
            d = net.gt(f"/dexes/{dex}/pools", {"page": 1, "sort": sort})
        except Exception as e:  # noqa: BLE001
            log(f"GeckoTerminal {dex}: {type(e).__name__}: {str(e)[:80]}")
            continue
        for p in (d or {}).get("data") or []:
            m = gt_market(p, cfg)
            if m:
                if stage == "final_stretch":
                    m["curve"] = True
                gt_rows[m["token"]] = m
                _add(c, m["token"], "gecko", symbol=m["symbol"])
    return n


def followed_wallets(p):
    """The wallets whose buys are signals: the real-money account's wallet follows and the proven-twice list (the
    same set as ui/pravitrade.followed_wallets, read here without importing the page module)."""
    out = set()
    lc = _ro(p["league"])
    try:
        from trade import settings
        out |= {w for (w,) in _q(lc, "SELECT target FROM follows WHERE user=? AND active=1 AND kind='wallet'",
                                 (settings.LEAGUE_USER,))}
    finally:
        if lc is not None:
            lc.close()
    try:
        from wallets import dokazani
        out |= set(dokazani.current())
    except Exception:  # noqa: BLE001
        pass
    return out


def from_signals(con, now, cfg, c, p):
    """Caller (X / Telegram calls) and wallet (buys of followed wallets) signals since the last pass."""
    last = _f(store.kv_get(con, "last_sig_ts")) or 0
    since = max(last - 60, now - float(cfg["signal_window_min"]) * 60)
    store.kv_set(con, "last_sig_ts", int(now))
    try:
        from kol import converge
        ev, _s, _w = converge.events(int(now), int(now - since), kol_db=p["kol"], tg_db=p["tg"], hype_db=p["hype"])
    except Exception as e:  # noqa: BLE001
        log(f"signali: {type(e).__name__}: {str(e)[:80]}")
        ev = []
    from kol.collect import is_solana_mint
    for tok, ts, plat, who, kind in ev:
        if plat in ("x", "tg") and kind == "call" and is_solana_mint(tok):
            d = _add(c, tok, "signal")
            d["signals"].setdefault("caller", (ts, who))
    fw = followed_wallets(p)
    if fw:
        hc = _ro(p["hype"])
        try:
            q = ",".join("?" * len(fw))
            for w, mint, ts in _q(hc, f"SELECT wallet, mint, MIN(ts) FROM chain_trades WHERE ts >= ? AND side='buy' "
                                      f"AND wallet IN ({q}) GROUP BY mint", (int(since), *sorted(fw))):
                d = _add(c, mint, "signal")
                d["signals"].setdefault("wallet", (ts, "w:" + w))
        finally:
            if hc is not None:
                hc.close()


# ---------- pricing -----------------------------------------------------------------------------------------------

def dex_markets(pairs, cfg):
    """DexScreener pairs -> ({token: market dict}, [SOL prices seen]). A token is migrated when any non-curve pair has
    liquidity; then its deepest such pair gives the numbers, else its busiest curve pair (curve=True)."""
    curve_ids = set(cfg["curve_dex_ids"])
    by, sol = {}, []
    for p in pairs or []:
        if not isinstance(p, dict) or p.get("chainId") not in (None, "solana"):
            continue
        t = (p.get("baseToken") or {}).get("address")
        if not t:
            continue
        liq = _f((p.get("liquidity") or {}).get("usd")) or 0.0
        dex = p.get("dexId") or ""
        pu, pn = _f(p.get("priceUsd")), _f(p.get("priceNative"))
        if (p.get("quoteToken") or {}).get("address") == WSOL and pu and pn:
            sol.append(pu / pn)
        is_curve = dex in curve_ids or "DBC" in (p.get("labels") or [])
        tx, vol, ch = p.get("txns") or {}, p.get("volume") or {}, p.get("priceChange") or {}
        h1, m5 = tx.get("h1") or {}, tx.get("m5") or {}
        row = {"token": t, "symbol": (p.get("baseToken") or {}).get("symbol"), "name": (p.get("baseToken") or {}).get("name"),
               "price": pu, "mcap": _f(p.get("marketCap")) or _f(p.get("fdv")), "liq": liq,
               "vol_m5": _f(vol.get("m5")) or 0.0, "vol_h1": _f(vol.get("h1")) or 0.0, "vol_h24": _f(vol.get("h24")) or 0.0,
               "txns_m5": int(m5.get("buys") or 0) + int(m5.get("sells") or 0),
               "txns_h1": int(h1.get("buys") or 0) + int(h1.get("sells") or 0), "buys_h1": int(h1.get("buys") or 0),
               "sells_h1": int(h1.get("sells") or 0), "buyers_h1": None, "ch_m5": _f(ch.get("m5")),
               "ch_h1": _f(ch.get("h1")), "ch_h24": _f(ch.get("h24")), "dex": dex, "curve": is_curve,
               "src": "dexscreener"}
        cur = by.get(t)
        key = (0 if is_curve or liq <= 0 else 1, liq if not is_curve else row["vol_h1"])
        if cur is None or key > cur[0]:
            by[t] = (key, row)
    return {t: r for t, (_k, r) in by.items()}, sol


def sol_price(con, seen):
    """SOL in USD: the median of this batch's SOL-quoted pairs (priceUsd / priceNative), else the last one kept."""
    if seen:
        px = statistics.median(seen)
        store.kv_set(con, "sol_usd", round(px, 4))
        return px
    return _f(store.kv_get(con, "sol_usd")) or 150.0


def pp_market(tok, d, sol_usd):
    """A market dict from PumpPortal's last trade when no API knows the token (no liquidity: never tradeable)."""
    pp = d.get("pp") or {}
    if not pp.get("price_sol"):
        return None
    return {"token": tok, "symbol": d.get("symbol"), "name": d.get("name"), "price": pp["price_sol"] * sol_usd,
            "mcap": (pp.get("mcap_sol") or 0) * sol_usd, "liq": 0.0, "vol_m5": 0.0,
            "vol_h1": (pp.get("vol_sol") or 0) * sol_usd, "vol_h24": None, "txns_m5": 0, "txns_h1": pp.get("trades") or 0,
            "buys_h1": pp.get("buys") or 0, "sells_h1": (pp.get("trades") or 0) - (pp.get("buys") or 0),
            "buyers_h1": None, "ch_m5": None, "ch_h1": None, "ch_h24": None, "dex": pp.get("pool"),
            "curve": bool(pp.get("curve")), "src": "pumpportal"}


# ---------- one check -----------------------------------------------------------------------------------------------

class Ctx:
    """What a pass shares between the checks: market data, the Helius budget, the free tables."""

    def __init__(self, con, net, cfg, now, p):
        self.con, self.net, self.cfg, self.now, self.p = con, net, cfg, now, p
        self.archived = frozenset()
        self.dead = frozenset()   # hype/tokenstatus: no DexScreener pair at the last 6-hourly status pass
        self.sol_usd = 150.0
        self.helius_stopped = False
        self.stop_why = self.facts_why = None
        self.credits = 0
        self.tc = {}
        self.pulse = {}
        self.hc = None

    def trades(self, tok):
        """The token's PumpPortal trades of the last hour as rugfilter/analysis rows (side, wallet, amount, ts)."""
        return [{"side": s, "wallet": w, "amount": sol or 0, "ts": ts}
                for s, w, sol, ts in _q(self.hc, "SELECT side, wallet, sol, ts FROM live_trades WHERE mint=? AND ts>=? "
                                                 "LIMIT 3000", (tok, int(self.now) - 3600))]

    def facts(self, tok, tradeable=True):
        """Holders / top 10 / authorities: the scan.db cache, the free tables, then Helius within the credit cap. A
        token that can never be bought (curve, under 30k) gets Helius only while the day has used under
        helius_measure_share of the cap: the credits go to tradeable tokens first. Sets self.facts_why when None."""
        self.facts_why = None
        ttl = float(self.cfg["facts_ttl_h"]) * 3600
        r = self.con.execute("SELECT ts, holders, holders_capped, top10_pct, mint_auth, freeze_auth, src FROM facts "
                             "WHERE token=?", (tok,)).fetchone()
        if r and self.now - r[0] < ttl:
            return {"holders": r[1], "holders_capped": r[2], "top10_pct": r[3], "mint_auth": r[4], "freeze_auth": r[5],
                    "src": r[6]}
        f = filters.free_facts(tok, self.tc, self.pulse)
        if f is None and not tradeable and store.spent(self.con, "helius", self.now) >= \
                float(self.cfg["helius_credits_day"]) * float(self.cfg["helius_measure_share"]):
            self.facts_why = "čeka provjeru holdera (Helius krediti danas idu tokenima koji se mogu kupiti)"
            return None
        if f is None:
            f = self.helius_facts(tok)
        if f is not None:
            self.con.execute("INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?,?,?)",
                             (tok, int(self.now), f.get("holders"), f.get("holders_capped"), f.get("top10_pct"),
                              f.get("mint_auth"), f.get("freeze_auth"), f.get("src")))
        return f

    def helius_facts(self, tok):
        if self.helius_stopped:
            self.facts_why = self.stop_why
            return None
        if not self.net.helius_ready():
            self.helius_stopped = True
            self.stop_why = self.facts_why = "čeka provjeru holdera (nema HELIUS_API_KEY)"
            return None
        need = filters.HELIUS_COST + 10 * int(self.cfg["helius_holder_pages"])
        left = store.budget_left(self.con, "helius", self.cfg["helius_credits_day"], self.now)
        if left < need:   # the day's cap (or this hour's slice of it) is spent: no more Helius in this pass
            self.helius_stopped = True
            self.stop_why = self.facts_why = "čeka provjeru holdera (dnevni strop Helius kredita potrošen)"
            log(f"dnevni strop Helius kredita: {store.spent(self.con, 'helius', self.now):.0f} od "
                f"{self.cfg['helius_credits_day']} (udio do ovog sata); provjere holdera čekaju")
            return None
        f, credits = filters.helius_facts(tok, self.net.helius, int(self.cfg["helius_holder_pages"]))
        self.credits += credits
        store.add_spent(self.con, "helius", credits, self.now)
        if f is None:
            self.facts_why = "provjera holdera nije uspjela (Helius), ponovno nakon predmemorije"
        return f


def check(m, cfg, ctx, has_signal):
    """Run every filter on one priced token. Returns {"stage", "tradeable", "why", "why_sig", "reasons", fees...}."""
    tok = m["token"]
    stage, tradeable, why_stage, why_stage_sig = filters.stage_filter(m, cfg)
    out = {"stage": stage, "tradeable": tradeable, "why": None, "why_sig": None, "reasons": [], "fees_paid_sol": None,
           "buy_share": None, "wash": None, "holders": None, "top10_pct": None}
    if why_stage_sig:
        out["why"] = out["why_sig"] = why_stage_sig
        return out
    vol_fail = why_stage == filters.VOLUME_RULE
    if vol_fail and not has_signal:   # the scanner's own rule already says no, and no signal needs the rest
        out["why"] = filters.volume_rule_text(m, cfg)
        out["why_sig"] = "nije provjereno (nema signala)"
        return out
    out["reasons"].append(("na krivulji, MC " if stage == "final_stretch" else "migriran, MC ")
                          + f"${m.get('mcap') or 0:,.0f}, volumen 1 h ${m.get('vol_h1') or 0:,.0f}"
                          + ("" if tradeable else " (samo mjerenje: ne kupuje se)"))
    g = filters.entry_gates(m, stage, ctx.archived, ctx.dead)
    if g:
        out["why"] = out["why_sig"] = g
        return out
    out["reasons"].append("ulazna pravila kopiranja prolaze (likvidnost, MC, pool, arhiva, kolaps)")
    ru = runup_why(m, stage, cfg, ctx)   # 11.11. (Grok #54 / #96 / #105): before the paid facts
    if ru:
        out["why"] = out["why_sig"] = ru
        return out
    fee = filters.fees_filter(m, ctx.trades(tok), cfg, ctx.sol_usd)
    out.update(fees_paid_sol=fee["fees_paid_sol"], buy_share=fee["buy_share"], wash=fee["wash"])
    if fee["why"]:
        out["why"] = out["why_sig"] = fee["why"]
        return out
    out["reasons"].append(f"naknade ~{fee['fees_paid_sol']:.2f} SOL u satu ({fee['src']})"
                          + (f", wash {fee['wash']:.0f}/100" if fee["wash"] is not None else ""))
    facts = ctx.facts(tok, tradeable)
    if facts:
        out.update(holders=facts.get("holders"), top10_pct=facts.get("top10_pct"))
    why, shown = filters.rug_check(tok, facts, cfg, ctx.facts_why)
    if why:
        out["why"] = out["why_sig"] = why
        return out
    # 10.11. (BOXCAT): the label says what was checked, the rug filter's verdict included (a truthful "prolazi")
    out["reasons"].append(f"rug provjera prolazi ({shown}, holdera {facts.get('holders')}"
                          + ("+" if facts.get("holders_capped") else "") + f", izvor {facts.get('src')}, "
                          f"rug filter: {filters.rug_filter_word(tok)})")
    if vol_fail:
        out["why"] = filters.volume_rule_text(m, cfg)
    return out


def first_seen(con, tok, now, cfg):
    """(mcap, ts) of the scanner's first sighting of the token as bonded within runup_window_h (cand.mcap_first), or
    None (never seen bonded, the anchor is older than the window, or an older scan.db without the column)."""
    try:
        r = con.execute("SELECT mcap_first, mcap_first_ts FROM cand WHERE token=?", (tok,)).fetchone()
    except sqlite3.Error:
        return None
    if not r or not r[0] or not r[1] or now - r[1] > float(cfg.get("runup_window_h") or 24) * 3600:
        return None
    return float(r[0]), int(r[1])


def runup_why(m, stage, cfg, ctx):
    """11.11. (Grok #54 / #96 / #105): the run-up cap. A bonded token at runup_max_x (4x) or more over the market cap
    at the scanner's first sighting of it as bonded fails as "kasno" (for the scanner's own rule and for a caller /
    wallet signal alike, so neither enters shadow as a pass). None when the cap is off, the token is on the curve or
    the anchor is unknown."""
    cap = float(cfg.get("runup_max_x") or 0)
    con = getattr(ctx, "con", None)
    mc = _f(m.get("mcap"))
    if cap <= 0 or stage != "migrated" or con is None or not mc:
        return None
    fs = first_seen(con, m["token"], getattr(ctx, "now", None) or time.time(), cfg)
    if not fs or mc / fs[0] < cap:
        return None
    return (f"kasno: već {mc / fs[0]:.1f}× od prvog viđenja skenera (MC ${fs[0]:,.0f} -> ${mc:,.0f}, granica "
            f"{cap:g}×)")


def anchor_first(con, tok, m, stage, now, cfg):
    """Set the run-up anchor (cand.mcap_first / mcap_first_ts) at the first sighting of the token as bonded, and again
    at the first bonded sighting after runup_window_h; a curve sighting never sets it (graduating is not a run-up)."""
    mc = _f(m.get("mcap"))
    if stage != "migrated" or not mc:
        return False
    try:
        r = con.execute("SELECT mcap_first_ts FROM cand WHERE token=?", (tok,)).fetchone()
        if r is None or (r[0] and now - r[0] <= float(cfg.get("runup_window_h") or 24) * 3600):
            return False
        con.execute("UPDATE cand SET mcap_first=?, mcap_first_ts=? WHERE token=?", (mc, int(now), tok))
    except sqlite3.Error:
        return False
    return True


def save(con, tok, d, m, res, now):
    via = ",".join(sorted(d["via"]))
    passed = int(res["why"] is None)
    old = con.execute("SELECT via, first_pass_ts FROM cand WHERE token=?", (tok,)).fetchone()
    if old:
        via = ",".join(sorted((set((old[0] or "").split(",")) | d["via"]) - {""}))
    discovered = bool(set(via.split(",")) - {"signal"})
    first_pass = (old[1] if old and old[1] else None) or (int(now) if passed and discovered else None)
    con.execute("""INSERT INTO cand (token, symbol, name, via, first_seen, last_seen, checked_ts, stage, tradeable, passed,
        why, reasons, price, mcap, liq, vol_h1, ch_h1, ch_h24, fees_paid_sol, buy_share, holders, top10_pct, wash,
        first_pass_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(token) DO UPDATE SET symbol=COALESCE(excluded.symbol, symbol), name=COALESCE(excluded.name, name),
        via=excluded.via, last_seen=excluded.last_seen, checked_ts=excluded.checked_ts, stage=excluded.stage,
        tradeable=excluded.tradeable, passed=excluded.passed, why=excluded.why, reasons=excluded.reasons,
        price=excluded.price, mcap=excluded.mcap, liq=excluded.liq, vol_h1=excluded.vol_h1, ch_h1=excluded.ch_h1,
        ch_h24=excluded.ch_h24, fees_paid_sol=excluded.fees_paid_sol, buy_share=excluded.buy_share,
        holders=COALESCE(excluded.holders, holders), top10_pct=COALESCE(excluded.top10_pct, top10_pct),
        wash=excluded.wash, first_pass_ts=excluded.first_pass_ts""",
                (tok, m.get("symbol") or d.get("symbol"), m.get("name") or d.get("name"), via, int(now), int(now),
                 int(now), res["stage"], int(bool(res["tradeable"])), passed, res["why"],
                 json.dumps(res["reasons"], ensure_ascii=False), m.get("price"), m.get("mcap"), m.get("liq"),
                 m.get("vol_h1"), m.get("ch_h1"), m.get("ch_h24"), res["fees_paid_sol"], res["buy_share"],
                 res["holders"], res["top10_pct"], res["wash"], first_pass))
    return discovered


def seen_only(con, tok, d, now):
    """A candidate inside its 10-minute cache: only last_seen and the discovery sources move."""
    old = con.execute("SELECT via FROM cand WHERE token=?", (tok,)).fetchone()
    via = ",".join(sorted((set((old[0] if old else "").split(",")) | d["via"]) - {""}))
    con.execute("UPDATE cand SET via=?, last_seen=? WHERE token=?", (via, int(now), tok))


# ---------- the pass --------------------------------------------------------------------------------------------------

def pass_once(now=None, net=None, cfg=None, p=None, settings_path=None):
    """One scanner pass. Returns a summary dict ({"off": True} when the flag is off)."""
    if not store.on(settings_path):
        return {"off": True}
    from league import copy as lcopy
    now = int(now or time.time())
    net = net or Net()
    cfg = cfg or store.config()
    p = p or paths()
    con = store.connect()
    hc, kc = _ro(p["hype"]), _ro(p["kol"])
    ctx = Ctx(con, net, cfg, now, p)
    ctx.hc = hc
    lcopy._CONC_CACHE = {}   # copy._concentration reads the topcheck / rug tables once for this pass
    out = {"off": False, "candidates": 0, "checked": 0, "passed": {}, "credits": 0, "gt": 0, "x_usd": 0.0,
           "finished": 0}
    try:
        c, gt_rows = {}, {}
        from_pumpportal(hc, now, cfg, c)
        from_hype(hc, now, c)
        from_graduates(kc, now, cfg, c)
        from_launches(now, c)
        from_dex_lists(net.dex_lists(), c, con, now)
        out["gt"] = from_gecko(net, con, now, cfg, c, gt_rows)
        from_signals(con, now, cfg, c, p)
        out["candidates"] = len(c)
        # the per-token cache: inside recheck_min only signals are checked again
        fresh = {t for (t,) in con.execute("SELECT token FROM cand WHERE checked_ts >= ?",
                                           (now - float(cfg["recheck_min"]) * 60,))}
        todo = [t for t, d in c.items() if t not in fresh or d["signals"]]
        todo.sort(key=lambda t: (not c[t]["signals"], "pumpportal" not in c[t]["via"], t))
        todo = todo[:int(cfg["max_candidates"])]
        for t, d in c.items():
            if t not in todo and t in fresh:
                seen_only(con, t, d, now)
        track_toks = shadow.open_tokens(con) | meta.pending_tokens(con)
        try:
            pairs = net.dex_pairs(sorted(set(todo) | track_toks))
            ok_prices = True
        except Exception as e:  # noqa: BLE001 - no DexScreener this pass: judged on GeckoTerminal / PumpPortal numbers
            # without shadow entries (the path is DexScreener's), and no open row is moved (a failed fetch is not a
            # token that lost its pair)
            log(f"DexScreener: {type(e).__name__}: {str(e)[:80]}")
            pairs, ok_prices = [], False
        mk, sol_seen = dex_markets(pairs, cfg)
        ctx.sol_usd = sol_price(con, sol_seen)
        try:
            from rugfilter import archive
            ctx.archived = archive.blocked(p["hype"])
        except Exception:  # noqa: BLE001
            pass
        try:
            from topcheck import store as tstore
            ctx.tc = tstore.read_all() or {}
        except Exception:  # noqa: BLE001
            ctx.tc = {}
        if todo:
            q = ",".join("?" * len(todo))
            ctx.dead = frozenset(t for (t,) in _q(hc, f"SELECT token FROM token_status WHERE has_pair=0 AND checked_ts >= ? "
                                                      f"AND token IN ({q})", (now - 12 * 3600, *todo)))
        ctx.pulse = {t: h for t, h, _ts in _q(hc, "SELECT token, holders, MAX(ts) FROM token_pulse WHERE holders IS NOT "
                                                  "NULL AND ts >= ? GROUP BY token",
                                              (now - float(cfg["facts_ttl_h"]) * 3600,))}
        checked = []
        for t in todo:
            d = c[t]
            m = mk.get(t) or gt_rows.get(t) or pp_market(t, d, ctx.sol_usd)
            if not m or not m.get("price"):
                continue
            m = dict(m)
            if gt_rows.get(t) and m.get("buyers_h1") is None:
                m["buyers_h1"] = gt_rows[t].get("buyers_h1")
            if d.get("migrated"):   # PumpPortal saw the migration: DexScreener may still show only the curve pair
                m["curve"] = False
            m["symbol"] = m.get("symbol") or d.get("symbol")
            res = check(m, cfg, ctx, bool(d["signals"]))
            discovered = save(con, t, d, m, res, now)
            anchor_first(con, t, m, res["stage"], now, cfg)   # 11.11.: the run-up anchor (runup_why)
            out["checked"] += 1
            entered = []
            if m.get("src") != "dexscreener":   # the shadow path is DexScreener's: no pair there, no shadow entry
                checked.append((t, d, m, res))
                continue
            if res["why"] is None and discovered:
                if shadow.enter(con, t, "scan", res["stage"], res["tradeable"], now, m["price"], m.get("mcap"), m.get("symbol")):
                    entered.append("scan")
            for src in d["signals"]:
                if res["why_sig"] is None and shadow.enter(con, t, src, res["stage"], res["tradeable"], now, m["price"],
                                                           m.get("mcap"), m.get("symbol")):
                    entered.append(src)
            for src in entered:
                out["passed"][src] = out["passed"].get(src, 0) + 1
            checked.append((t, d, m, res))
        con.commit()
        # meta / beta
        refresh_metas(con, net, cfg, now, gt_rows)
        out["passed"]["beta"] = match_betas(con, cfg, now, checked)
        con.commit()
        # X momentum, lead time, the shadow paths
        out["x_usd"] = x_momentum(con, cfg, now, p, net)
        update_lead_times(con, now, p)
        con.commit()
        for src, n in log_kandidati(con, net, cfg, now).items():
            out["passed"][src] = out["passed"].get(src, 0) + n
        if ok_prices:
            prices = {t: r["price"] for t, r in mk.items() if r.get("price")}
            out["finished"] = shadow.track(con, prices, now, cfg)
            meta.track(con, prices, now)
        if now - (_f(store.kv_get(con, "last_prune")) or 0) >= 3600:
            store.prune(con, now)
            store.kv_set(con, "last_prune", now)
        out["credits"] = ctx.credits
        con.commit()
    finally:
        lcopy._CONC_CACHE = None
        for x in (hc, kc):
            if x is not None:
                x.close()
        con.close()
    return out


def refresh_metas(con, net, cfg, now, gt_rows):
    """Every meta_every_min: the active metas (meta.runners) from the tokens the scanner priced in the last 24 h,
    priced again now, plus GeckoTerminal's trending pools (one call within the GT budget). Under the heavy-job lock
    when it is free (ops/heavy.slot(wait=0)); busy: the next pass tries again."""
    last = _f(store.kv_get(con, "last_meta_ts")) or 0
    if now - last < float(cfg["meta_every_min"]) * 60:
        return False
    try:
        from ops import heavy
        slot = heavy.slot(wait=0, label="skener meta")
    except Exception:  # noqa: BLE001 - no lock available (tests, another OS): run without it
        slot = None
    import contextlib
    with (slot or contextlib.nullcontext(True)) as got:
        if not got:
            return False
        rows = {}
        toks = [t for (t,) in con.execute("SELECT token FROM cand WHERE checked_ts >= ? AND COALESCE(mcap, 0) >= ? "
                                          "ORDER BY mcap DESC LIMIT 300",
                                          (now - 86400, float(cfg["runner_min_mcap"]) / 2))]
        if toks:
            try:
                rows.update(dex_markets(net.dex_pairs(toks), cfg)[0])
            except Exception as e:  # noqa: BLE001
                log(f"meta: DexScreener: {type(e).__name__}: {str(e)[:80]}")
        if gt_take(con, now, cfg):
            try:
                d = net.gt("/trending_pools", {"page": 1, "duration": "1h"})
                for pl in (d or {}).get("data") or []:
                    m = gt_market(pl, cfg)
                    if m and m["token"] not in rows:
                        rows[m["token"]] = m
            except Exception as e:  # noqa: BLE001
                log(f"meta: GeckoTerminal: {type(e).__name__}: {str(e)[:80]}")
        for t, m in gt_rows.items():
            rows.setdefault(t, m)
        picked = meta.runners([dict(r, token=t) for t, r in rows.items()], cfg)
        if picked:
            desc = dict(con.execute("SELECT token, description FROM profiles"))
            meta.store_metas(con, now, picked, desc)
        store.kv_set(con, "last_meta_ts", now)
        return bool(picked)


def match_betas(con, cfg, now, checked):
    """Compare every token checked for the first time (beta_checked empty) with the current metas; a match makes a
    beta row (passing or not, for the meta-state measure) and, when the token passed its filters, a shadow entry
    under source beta. Returns the number of new beta shadow entries."""
    metas = meta.current(con)
    if not metas:
        return 0
    mts = metas[0]["ts"]
    parents = {m["token"]: m for m in metas}
    desc = {}
    n = 0
    for t, d, m, res in checked:
        row = con.execute("SELECT beta_checked FROM cand WHERE token=?", (t,)).fetchone()
        if row and row[0]:
            continue
        if t in parents:   # a runner is never its own beta
            con.execute("UPDATE cand SET beta_checked=? WHERE token=?", (mts, t))
            continue
        if t not in desc:
            r = con.execute("SELECT description FROM profiles WHERE token=?", (t,)).fetchone()
            desc[t] = r[0] if r else ""
        cand = {"token": t, "symbol": m.get("symbol") or d.get("symbol"), "name": m.get("name") or d.get("name"),
                "description": desc[t]}
        score, parent, matched = meta.best_parent(cand, metas)
        con.execute("UPDATE cand SET beta_checked=?, beta_score=?, beta_parent=? WHERE token=?",
                    (mts, score or None, parent["token"] if parent and score else None, t))
        if parent is None or score < float(cfg["beta_min"]):
            continue
        meta.record(con, cand, parent, score, matched, now, ",".join(sorted(d["via"])), m.get("price"),
                    parent.get("price"))
        ok = res["why"] is None or (d["signals"] and res["why_sig"] is None)
        if ok and shadow.enter(con, t, "beta", res["stage"], res["tradeable"], now, m.get("price"), m.get("mcap"),
                               cand["symbol"]):
            n += 1
    return n


def x_momentum(con, cfg, now, p, net):
    """X early momentum for the youngest scanner passers and beta passers, x_per_pass a pass, each at most every
    x_every_min, within the scanner's X budget. Returns the USD spent."""
    rows = con.execute(
        "SELECT token, symbol FROM cand WHERE (x_ts IS NULL OR x_ts < ?) AND ((passed=1 AND first_pass_ts >= ?) OR "
        "(beta_score >= ? AND checked_ts >= ? AND token IN (SELECT token FROM shadow WHERE source='beta'))) "
        "ORDER BY COALESCE(first_pass_ts, checked_ts) DESC LIMIT ?",
        (now - float(cfg["x_every_min"]) * 60, now - float(cfg["x_window_h"]) * 3600, float(cfg["beta_min"]),
         now - float(cfg["x_window_h"]) * 3600, int(cfg["x_per_pass"]))).fetchall()
    if not rows:
        return 0.0
    from kol import twapi
    from scan import xmom
    if not twapi.key() and net.x_get is None:
        return 0.0
    try:
        kcon = sqlite3.connect(p["kol"], timeout=30)
        kcon.executescript("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);")
    except sqlite3.Error:
        return 0.0
    usd = 0.0
    try:
        known, bots = xmom.known_handles(kcon)
        for tok, sym in rows:
            r = xmom.measure(tok, sym, now, con, kcon, cfg, get=net.x_get, known=known, bots=bots, log=log)
            if r is None:
                if store.budget_left(con, "xusd", cfg["x_usd_day"], now) < twapi.MIN_REQ * int(cfg["x_max_pages"]):
                    break
                continue
            usd += r.get("usd") or 0.0
            con.execute("UPDATE cand SET x_ts=? WHERE token=?", (now, tok))
    finally:
        kcon.close()
    return round(usd, 5)


def log_kandidati(con, net, cfg, now):
    """10.11. (ui/kandidati.py): every kandidati_every_min the combined candidate list (net.kandidati) and its shadow
    entries: source kandidati for a tradeable row the first time it ranks in the top kandidati_top_n, source
    grok_override for every tradeable row Grok's fresh evidence lifted over a rug risk rating. Free (DexScreener and
    the bot's own databases); a failure is logged and never stops the pass. Returns {source: new entries}."""
    fn = getattr(net, "kandidati", None)
    if fn is None:
        return {}
    last = _f(store.kv_get(con, "last_kand_ts")) or 0
    if now - last < float(cfg["kandidati_every_min"]) * 60:
        return {}
    store.kv_set(con, "last_kand_ts", int(now))
    try:
        rows = fn(now)
        from ui import kandidati
        out = kandidati.log_shadow(con, rows, now, int(cfg["kandidati_top_n"]))
    except Exception as e:  # noqa: BLE001 - the combined list is extra; the scanner's own pass goes on
        log(f"kandidati: {type(e).__name__}: {str(e)[:80]}")
        return {}
    con.commit()
    return out


def update_lead_times(con, now, p):
    """lead_time_min of the passers of the last 24 h that have none yet: minutes from the scanner's first pass to the
    token's first caller signal (kol.db calls of kind call, bots out; X and Telegram with their own post time) or
    first buy of a followed wallet. Negative = a caller was first."""
    rows = con.execute("SELECT token, first_pass_ts FROM cand WHERE first_pass_ts >= ? AND lead_time_min IS NULL",
                       (now - 86400,)).fetchall()
    if not rows:
        return 0
    found = dict(rows)
    toks = sorted(found)
    first = {}
    q = ",".join("?" * len(toks))
    oldest = min(found.values()) - 86400
    kc = _ro(p["kol"])
    try:
        got = _q(kc, f"SELECT token, MIN(ts), handle FROM calls WHERE token IN ({q}) AND kind='call' AND handle NOT IN "
                     f"(SELECT handle FROM kols WHERE bot=1) GROUP BY token", toks) or \
            _q(kc, f"SELECT token, MIN(ts), handle FROM calls WHERE token IN ({q}) AND kind='call' GROUP BY token", toks)
        for tok, ts, h in got:
            first[tok] = (ts, h)
    finally:
        if kc is not None:
            kc.close()
    fw = followed_wallets(p)
    if fw:
        hc = _ro(p["hype"])
        try:
            qw = ",".join("?" * len(fw))
            for tok, ts, w in _q(hc, f"SELECT mint, MIN(ts), wallet FROM chain_trades WHERE ts >= ? AND mint IN ({q}) "
                                     f"AND side='buy' AND wallet IN ({qw}) GROUP BY mint", (oldest, *toks, *sorted(fw))):
                if tok not in first or ts < first[tok][0]:
                    first[tok] = (ts, "w:" + w)
        finally:
            if hc is not None:
                hc.close()
    n = 0
    for tok, (ts, who) in first.items():
        lead = round((ts - found[tok]) / 60, 1)
        con.execute("UPDATE cand SET first_signal_ts=?, first_signal_by=?, lead_time_min=? WHERE token=?",
                    (int(ts), who, lead, tok))
        n += 1
    return n


# ---------- read side (get_market_signals) -------------------------------------------------------------------------

def recent(now=None, minutes=None, path=None, cfg=None):
    """{token: scanner row} of the passers of the last `minutes` (show_min) and the beta candidates that passed, for
    ui/mcpapi.signals. Read-only; {} without scan.db."""
    cfg = cfg or store.config()
    now = int(now or time.time())
    since = now - int(minutes or cfg["show_min"]) * 60
    con = store.ro(path)
    if con is None:
        return {}
    out = {}
    try:
        con.row_factory = sqlite3.Row
        for r in con.execute(
                "SELECT * FROM cand WHERE checked_ts >= ? AND (passed=1 OR token IN (SELECT token FROM shadow WHERE "
                "found_ts >= ?)) ORDER BY checked_ts DESC LIMIT 60", (since, since)):
            d = dict(r)
            try:
                d["reasons"] = json.loads(d.get("reasons") or "[]")
            except ValueError:
                d["reasons"] = []
            d["sources"] = sorted({s for (s,) in con.execute("SELECT source FROM shadow WHERE token=? AND found_ts >= ?",
                                                             (d["token"], since))})
            out[d["token"]] = d
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return out


def lead_for(token_row, first_call_ts):
    """lead_time_min of a scanner row against a caller row's first call: the stored one, else computed now."""
    if token_row.get("lead_time_min") is not None:
        return token_row["lead_time_min"]
    fp = token_row.get("first_pass_ts")
    if fp and first_call_ts:
        return round((first_call_ts - fp) / 60, 1)
    return None
