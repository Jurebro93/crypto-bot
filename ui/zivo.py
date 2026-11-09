"""Živi prijedlozi za Autopilot (9.11., Jure): "tu moraju biti tokeni koji se osvježavaju svaku sekundu; sve filtrirano
(T1–T4, rug, likvidnost); cijena, volumen, novi pozivatelj, kupnja smart walleta svježi; uložimo 0,15 SOL, zaradimo
15 % i van".

Two layers, so the page can be fast and still strict:
- candidates(): every ~CAND_TTL s. Tokens from the fresh-check store (run_top.py: rug check 'prolazi', not pumping or
  falling), the suggestion log of the last 6 h, the convergence table (several sources on one token in 30 min) and
  "Zovu sada" (gather_callers). Each must be a Solana mint, not a major/wrapped/xStock, not archived by the rug
  filter, not a token whose tier sieve said 'pad', and have a market cap of 30k+.
- rows(): every LIVE_TTL s. One DexScreener request for the candidates (price, MC, liquidity, 5-min and 1-h volume,
  transactions and change), callers of the last 10 min (kol/converge.events) and buys of the proven/followed
  wallets in the last 10 min (hype.db chain_trades). A token stays only while it trades now (prijedlog.alive) and
  is not falling; the order is what moved last: new callers, smart buys, 5-min change, money speed.
- The expectation for +15 %: the callers' minute check (kol/minute.py handle_stats hit15) when they have one,
  otherwise the market-cap band's measured chance of +30 % in 24 h (ui/prijedlog.chances).
"""
import time

CAND_TTL = 60
LIVE_TTL = 1
RECENT_S = 600
MAX_SIGNAL_AGE_S = 6 * 3600
_CANDS = {"ts": 0.0, "rows": []}
_ROWS = {"ts": 0.0, "rows": []}
_MIN = {"ts": 0.0, "stats": {}}


def _tiers():
    try:
        from ui import data
        return data.token_tiers()
    except Exception:  # noqa: BLE001
        return {}


def candidates(now=None, sources=None):
    """[{token, symbol, src, why, ts0, mcap0, conf, rank}] after the slow filters; sources: injected for tests."""
    now = now or time.time()
    if sources is None and now - _CANDS["ts"] < CAND_TTL:
        return _CANDS["rows"]
    from kol import converge
    from kol.collect import is_solana_mint
    src = sources if sources is not None else _sources(now)
    try:
        from rugfilter import archive
        archived = archive.blocked()
    except Exception:  # noqa: BLE001
        archived = frozenset()
    tiers = _tiers() if sources is None else {}
    out, seen = [], set()
    for c in src:
        t = c["token"]
        if t in seen or not is_solana_mint(t) or t in archived:
            continue
        if converge.not_a_memecoin(t, c.get("symbol"), c.get("liq")):
            continue
        tier = tiers.get(t) or {}
        if tier.get("t0") == "pad":
            continue
        if (c.get("mcap0") or 0) and c["mcap0"] < 30_000:
            continue
        if c.get("ts0") and now - c["ts0"] > MAX_SIGNAL_AGE_S and c["src"] != "alat":
            continue
        c = dict(c, tier=tier.get("razina"), klasa=tier.get("klasa"))
        seen.add(t)
        out.append(c)
    if sources is None:
        _CANDS.update(ts=now, rows=out)
    return out


def _sources(now):
    """The raw candidate rows from the bases (each already carries a reason)."""
    out = []
    try:   # fresh check of the tool's own top suggestions (run_top.py every 3 min: rug check, market state)
        from topcheck import store as tstore
        for tok, r in tstore.read_all(max_age_h=1).items():
            st = (r.get("state") or {}).get("state")
            if r.get("verdict") == "prolazi" and st not in ("pumpa", "pada"):
                out.append({"token": tok, "symbol": r.get("symbol"), "src": "alat", "ts0": r.get("ts"), "mcap0": r.get("mcap"),
                            "liq": r.get("liq"), "rank": r.get("rank"), "why": [f"#{r.get('rank')} alata, rug check prošao"]})
    except Exception:  # noqa: BLE001
        pass
    try:   # the suggestion box's own picks (ui/prijedlog, already live-gated when logged)
        from ui import prijedlog
        for p in prijedlog.latest_picks(now, limit=10):
            if p.get("razina") == "visoka" and now - (p.get("ts") or 0) <= MAX_SIGNAL_AGE_S:
                out.append({"token": p["token"], "symbol": None, "src": "prijedlog", "ts0": p.get("ts"), "mcap0": p.get("mcap0"),
                            "conf": p.get("conf"), "why": [f"prijedlog Pregleda, pouzdanost {p.get('conf') or 0:.0f}"]})
    except Exception:  # noqa: BLE001
        pass
    try:   # several sources on one token within 30 min (kol/converge, stored by the KOL round)
        from kol import store as kstore
        from league import copy
        kc = copy._ro(kstore.DB)
        if kc is not None:
            try:
                for tok, ts, sc, nx, ntg, nch, mcap0 in copy._q(kc, "SELECT token, ts, score, n_x, n_tg, n_chain, mcap0 FROM converge "
                                                                   "WHERE ts >= ? ORDER BY score DESC LIMIT 20", (int(now) - 1800,)):
                    out.append({"token": tok, "symbol": None, "src": "konvergencija", "ts0": ts, "mcap0": mcap0,
                                "why": [f"konvergencija {sc:.0f}: {nx} X, {ntg} TG, {nch} novčanika"]})
            finally:
                kc.close()
    except Exception:  # noqa: BLE001
        pass
    try:   # who is calling right now (already live-checked)
        from ui import pravitrade
        for tok, callers, first, _last, sym, m in pravitrade.gather_callers(now, limit=12):
            who = ", ".join(("👛 " + c[0][2:8] if c[1] == "chain" else c[0]) for c in callers[:3])
            out.append({"token": tok, "symbol": sym, "src": "zovu", "ts0": first, "mcap0": m.get("mcap"), "liq": m.get("liq"),
                        "why": [f"zovu: {who}"]})
    except Exception:  # noqa: BLE001
        pass
    return out


def _recent_callers(now, tokens):
    """token -> [handle] that called it in the last RECENT_S (X and Telegram)."""
    try:
        from kol import converge
        ev, _s, _f = converge.events(int(now), RECENT_S)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for tok, ts, plat, who, kind in ev:
        if tok in tokens and kind == "call" and plat != "chain":
            out.setdefault(tok, [])
            if who not in out[tok]:
                out[tok].append(who)
    return out


def _smart_buys(now, tokens):
    """token -> number of proven/followed wallets that bought it in the last RECENT_S."""
    try:
        from league import copy
        from ui import pravitrade
        ws = pravitrade.followed_wallets()
        if not ws:
            return {}
        hc = copy._ro(copy._paths()["hype"])
        if hc is None:
            return {}
        try:
            q = ",".join("?" * len(ws))
            rows = copy._q(hc, f"SELECT mint, COUNT(DISTINCT wallet) FROM chain_trades WHERE ts >= ? AND side = 'buy' "
                               f"AND wallet IN ({q}) GROUP BY mint", (int(now) - RECENT_S, *sorted(ws)))
        finally:
            hc.close()
        return {m: n for m, n in rows if m in tokens}
    except Exception:  # noqa: BLE001
        return {}


def _minute_stats(now):
    """handle -> stats from the minute check, refreshed every 60 s (cheap: minute.db is small)."""
    if now - _MIN["ts"] < 60:
        return _MIN["stats"]
    stats = {}
    try:
        from kol import minute
        mc = minute.ro()
        if mc is not None:
            try:
                stats = dict(minute.handle_stats(mc, 14, int(now), min_n=3))
            finally:
                mc.close()
    except Exception:  # noqa: BLE001
        stats = {}
    _MIN.update(ts=now, stats=stats)
    return stats


def expectation(callers, mstats, chance):
    """(text, value) for "+15 %": callers' minute check when any has one, else the band's +30 %/24 h chance."""
    hs = [mstats[h] for h in callers if h in mstats]
    if hs:
        v = sum(s["hit15"] for s in hs) / len(hs)
        n = sum(s["n"] for s in hs)
        return f"pozivatelji: +15 % prije stopa u {v:.0%} ({n} izmjerenih poziva, minutna provjera)", v
    if chance and chance[0] is not None:
        return f"{chance[0]:.0%} sličnih tokena (po MC-u) dalo +30 % u 24 h ({chance[1]} poziva)", chance[0]
    return "još bez mjerenja", None


def rows(now=None, cands=None, live=None, callers=None, smart=None, mstats=None, chances=None):
    """The live table: candidates that trade right now, with fresh numbers, most active first. Cached LIVE_TTL."""
    now = now or time.time()
    injected = cands is not None
    if not injected and now - _ROWS["ts"] < LIVE_TTL:
        return _ROWS["rows"]
    from ui import prijedlog
    cs = cands if injected else candidates(now)
    if not cs:
        if not injected:
            _ROWS.update(ts=now, rows=[])
        return []
    toks = [c["token"] for c in cs][:30]
    lv = live if live is not None else prijedlog.live_market(toks)
    if lv is None:
        if not injected:
            _ROWS.update(ts=now, rows=[])
        return []
    callers = callers if callers is not None else _recent_callers(now, set(toks))
    smart = smart if smart is not None else _smart_buys(now, set(toks))
    mstats = mstats if mstats is not None else _minute_stats(now)
    ch = chances if chances is not None else _chances()
    out = []
    for c in cs:
        t = c["token"]
        m = lv.get(t)
        why_not = prijedlog.alive(m)
        if why_not or (m.get("mcap") or 0) < 30_000:
            continue
        band = prijedlog._band(m["mcap"])
        exp_txt, exp_v = expectation(callers.get(t, []), mstats, ch.get(band))
        r = {**c, "live": m, "callers10": callers.get(t, []), "smart10": smart.get(t, 0), "expect": exp_txt, "expect_v": exp_v,
             "age_s": now - (c.get("ts0") or now), "checked": now}
        r["reasons"] = fresh_reasons(r)
        if not r["reasons"]:   # 9.11. 15:43 (Jure, GROK): "called in Telegram a day ago" is not a reason to buy now
            continue
        turn = (m["vol_h1"] / m["liq"]) if m.get("liq") else 0
        r["heat"] = (3 * len(r["callers10"]) + 4 * r["smart10"] + (m.get("ch_m5") or 0) / 10 + min(3.0, turn))
        out.append(r)
    out.sort(key=lambda r: (-r["heat"], r["age_s"]))
    if not injected:
        _ROWS.update(ts=now, rows=out)
    return out


MOVE_M5 = 5.0        # +5 % in 5 minutes with real prints counts as a fresh reason
MOVE_VOL_M5 = 1000.0
MOVE_TX_M5 = 5


def fresh_reasons(r):
    """Only what happened in the last minutes, in plain words: new callers, smart-wallet buys, a 5-minute move with
    volume, money speed. The static source reason (a call yesterday, a tool rank) is a tag, never a reason."""
    m = r.get("live") or {}
    out = []
    if r.get("callers10"):
        names = ", ".join(h[3:] if h.startswith("tg:") else "@" + h for h in r["callers10"][:4])
        out.append(f"novi pozivatelj{'i' if len(r['callers10']) > 1 else ''} u 10 min: {names}")
    if r.get("smart10"):
        out.append(f"{r['smart10']} pametnih novčanika kupilo u 10 min")
    if (m.get("ch_m5") or 0) >= MOVE_M5 and (m.get("vol_m5") or 0) >= MOVE_VOL_M5 and (m.get("txns_m5") or 0) >= MOVE_TX_M5:
        out.append(f"+{m['ch_m5']:.0f} % u 5 min na ${m['vol_m5']:,.0f} ({m['txns_m5']} tx)")
    turn = (m.get("vol_h1") or 0) / m["liq"] if m.get("liq") else 0
    if turn >= 1.0 and out:
        out.append(f"novac ulazi brzo: volumen sata {turn:.1f}× likvidnosti")
    return out


def _chances():
    try:
        from ui import prijedlog
        return prijedlog.chances()
    except Exception:  # noqa: BLE001
        return {}
