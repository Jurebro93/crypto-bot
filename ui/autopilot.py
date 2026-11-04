"""Recommendations on the Autopilot page (/pravi-trade, Nicholas 4.11.): which influencers and wallets the tool
would follow with real money, judged on the last 7, 14 and 30 days of stored history, and which tokens it would
buy now (a few safer long-term ones and a few moonshots), each with the reason in plain words.

Only stored data is read (read-only, no API cost):
  influencers  kol.db calls (every measured call: best rise in 24 h, result after 24 h, rug) + who is watched live
               (kol.db monitor); bots, accounts on trial and accounts with fewer than 3 measured calls are left out
               the same way as on Copy trading (ui.copytrade.kol_rows).
  wallets      hype.db chain_trades of the wallets watched live (Helius webhook list): SOL in and out per token,
               kept 30 days.
  tokens       dugo.db snap (long-term layer, daily) and topcheck.db (fresh market state + rug check of the top
               suggestions, every 3 min); kol.db converge says who else is in.
Nothing here is advice that a token will rise: the reasons say what the history shows, the page says the risk.
"""
import json
import os
import statistics
import time

WINDOWS = (7, 14, 30)
D = 86400
CACHE_S = 300
HIT = 0.5            # a call is a hit when the price rose +50% at some point within 24 h
MIN_CALLS = 3        # fewer measured calls in the window = not enough to judge
MIN_CLOSED = 3       # wallets: tokens bought and sold in the window
MOON_MIN_LIQ = 20_000
TOP = 5
_CACHE = {}


def _cached(name, fn):
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    try:
        val = fn()
    except Exception as e:  # noqa: BLE001 - a recommendation box must never break the page
        print(f"autopilot: {name}: {type(e).__name__}: {e}", flush=True)
        val = None
    _CACHE[name] = (time.time(), val)
    return val


def _ro(path):
    from league import copy
    return copy._ro(path)


def _q(con, sql, args=()):
    from league import copy
    return copy._q(con, sql, args)


# ---------- influencers -------------------------------------------------------------------------------------------

def kol_stats(calls, now, days):
    """calls: [(handle, ts, max24, r24h, rug)] -> handle -> stats of the calls made in the window (only calls at
    least 24 h old are measured, so the window ends 24 h ago)."""
    lo = now - days * D
    out = {}
    for h, ts, mx, r24, rug in calls:
        if ts < lo or mx is None:
            continue
        s = out.setdefault(h, {"n": 0, "hits": 0, "rugs": 0, "r24": []})
        s["n"] += 1
        s["hits"] += 1 if mx >= HIT else 0
        s["rugs"] += 1 if rug else 0
        if r24 is not None:
            s["r24"].append(r24)
    for s in out.values():
        s["hit"] = s["hits"] / s["n"]
        s["rug"] = s["rugs"] / s["n"]
        s["med24"] = statistics.median(s["r24"]) if s["r24"] else None
        # small samples are pulled towards a coin flip, rugs count double against
        s["score"] = (s["hits"] + 1) / (s["n"] + 4) - 2 * s["rug"]
    return out


def _kol_why(h, s, days, live):
    parts = [f"u zadnjih {days} dana {s['n']} izmjerenih callova; {s['hits']} ({s['hit']:.0%}) je u 24 h naraslo +50% ili više"]
    if s["med24"] is not None:
        parts.append(f"tipičan rezultat dan kasnije {100 * s['med24']:+.0f}%")
    parts.append("bez ruga" if not s["rugs"] else f"{s['rugs']} rug ({s['rug']:.0%})")
    txt = "; ".join(parts) + "."
    txt += (" Pratimo ga uživo, pa bot uđe u sekundama." if live else
            " Ne pratimo ga uživo: njegove callove vidimo kasnije, pa bot često zakasni na ulaz.")
    return txt


def kol_recs(now=None):
    def build():
        from league import copy
        from ui.copytrade import kol_rows
        t = now or time.time()
        good = {r["handle"]: r for r in kol_rows()}
        con = _ro(copy._paths()["kol"])
        if con is None or not good:
            return {d: [] for d in WINDOWS}
        try:
            calls = _q(con, "SELECT handle, ts, max24, r24h, rug FROM calls WHERE kind='call' AND ts >= ?",
                       (int(t - max(WINDOWS) * D),))
        finally:
            con.close()
        calls = [c for c in calls if c[0] in good]
        out = {}
        for days in WINDOWS:
            st = kol_stats(calls, t, days)
            rows = []
            for h, s in st.items():
                if s["n"] < MIN_CALLS or s["rug"] > 0.3 or s["hit"] <= 0:
                    continue
                live = good[h]["live"]
                rows.append({"handle": h, "live": live, "s": s, "why": _kol_why(h, s, days, live),
                             "followers": good[h].get("followers")})
            rows.sort(key=lambda r: (r["live"], r["s"]["score"]), reverse=True)
            out[days] = rows[:TOP]
        return out
    return _cached(f"kol{now or ''}", build) or {d: [] for d in WINDOWS}


# ---------- wallets -----------------------------------------------------------------------------------------------

def wallet_stats(trades, now, days):
    """trades: [(wallet, mint, side, ts, sol)] -> wallet -> stats of the tokens it first bought in the window and
    sold (part of) again: SOL in, SOL out, how many ended in profit."""
    lo = now - days * D
    per = {}
    for w, mint, side, ts, sol in sorted(trades, key=lambda r: r[3]):
        k = per.setdefault((w, mint), {"first": None, "in": 0.0, "out": 0.0})
        if side == "buy":
            if k["first"] is None:
                k["first"] = ts
            k["in"] += sol or 0
        elif k["first"] is not None:
            k["out"] += sol or 0
    out = {}
    for (w, _mint), k in per.items():
        if k["first"] is None or k["first"] < lo or k["in"] <= 0:
            continue
        s = out.setdefault(w, {"bought": 0, "closed": 0, "wins": 0, "sol_in": 0.0, "sol_out": 0.0})
        s["bought"] += 1
        if k["out"] > 0:
            s["closed"] += 1
            s["wins"] += 1 if k["out"] > k["in"] else 0
            s["sol_in"] += k["in"]
            s["sol_out"] += k["out"]
    for s in out.values():
        s["win"] = s["wins"] / s["closed"] if s["closed"] else 0
        s["roi"] = s["sol_out"] / s["sol_in"] - 1 if s["sol_in"] else 0
        s["pnl"] = s["sol_out"] - s["sol_in"]
        s["avg_in"] = s["sol_in"] / s["closed"] if s["closed"] else 0
        # what a copier gets is the % return, not the wallet's SOL; few closed tokens weigh less
        s["score"] = min(s["roi"], 3.0) * min(1.0, s["closed"] / 8) + 0.3 * (s["win"] - 0.5)
    return out


def _wallet_why(s, days):
    return (f"u {days} dana kupio {s['bought']} tokena, {s['closed']} prodao; {s['wins']} u plusu ({s['win']:.0%}). "
            f"Na prodanima {100 * s['roi']:+.0f}% ({s['pnl']:+.2f} SOL), prosječno ulaže {s['avg_in']:.2f} SOL po tokenu. "
            "Pratimo ga uživo, pa bot kupi u sekundama nakon njega.")


def wallet_recs(now=None):
    def build():
        from league import copy
        t = now or time.time()
        p = copy._paths()
        kc = _ro(p["kol"])
        try:
            hook = json.loads((_q(kc, "SELECT value FROM kv WHERE key='chain_hook'") or [("{}",)])[0][0] or "{}")
            ids = {r[0]: r for r in _q(kc, "SELECT wallet, name, twitter FROM kol_ids")}
        finally:
            if kc is not None:
                kc.close()
        watched = hook.get("wallets") or []
        if not watched:
            return {d: [] for d in WINDOWS}
        hc = _ro(p["hype"])
        q = ",".join("?" * len(watched))
        try:
            trades = _q(hc, f"SELECT wallet, mint, side, ts, sol FROM chain_trades WHERE ts >= ? AND wallet IN ({q})",
                        (int(t - max(WINDOWS) * D), *watched))
        finally:
            if hc is not None:
                hc.close()
        out = {}
        for days in WINDOWS:
            rows = []
            for w, s in wallet_stats(trades, t, days).items():
                if s["closed"] < MIN_CLOSED or s["roi"] <= 0:
                    continue
                _, name, tw = ids.get(w, (w, None, None))
                rows.append({"wallet": w, "name": name or (f"@{tw}" if tw else ""), "s": s, "why": _wallet_why(s, days)})
            rows.sort(key=lambda r: r["s"]["score"], reverse=True)
            out[days] = rows[:TOP]
        return out
    return _cached(f"wal{now or ''}", build) or {d: [] for d in WINDOWS}


# ---------- tokens ------------------------------------------------------------------------------------------------

def _usd(x):
    if not x:
        return "–"
    return f"${x / 1e9:.1f} mlrd" if x >= 1e9 else f"${x / 1e6:.1f} mil" if x >= 1e6 else f"${x / 1e3:.0f} tis"


def _long_term(n=3):
    from dugo import store as dstore
    con = dstore.ro()
    if con is None:
        return []
    try:
        rows = con.execute("""SELECT s.mint, t.symbol, s.kind, s.score, s.mcap, s.liquidity, s.why FROM snap s
            JOIN tokens t ON t.mint=s.mint WHERE s.kind IN ('jaki', 'dugorocni') AND s.day=(SELECT MAX(day) FROM snap)
            ORDER BY s.score DESC""").fetchall()
    finally:
        con.close()
    out, seen = [], set()
    for m, sym, kind, sc, mc, liq, why in rows:
        if m in seen:
            continue
        seen.add(m)
        kind_hr = "jak, stariji token" if kind == "jaki" else "preživio pad i oporavlja se"
        out.append({"mint": m, "symbol": sym, "kind": "dugo", "score": sc,
                    "why": f"{kind_hr}; vrijednost {_usd(mc)}, likvidnost {_usd(liq)}. {why or ''}".strip()})
        if len(out) >= n:
            break
    return out


def _converge(mints, now):
    from league import copy
    con = _ro(copy._paths()["kol"])
    if con is None or not mints:
        return {}
    try:
        q = ",".join("?" * len(mints))
        rows = _q(con, f"SELECT token, handles, n_x, n_tg, n_chain FROM converge WHERE ts >= ? AND token IN ({q})",
                  (int(now - D), *mints))
    finally:
        con.close()
    out = {}
    for tok, handles, nx, ntg, nch in rows:
        try:
            hs = json.loads(handles or "[]")
        except ValueError:
            hs = []
        out[tok] = {"handles": hs if isinstance(hs, list) else [], "n": (nx or 0) + (ntg or 0) + (nch or 0)}
    return out


def _moonshots(n=3, now=None):
    from topcheck import store as tstore
    t = now or time.time()
    top = tstore.read_all(max_age_h=1)
    rows = []
    for tok, r in top.items():
        st = r.get("state") or {}
        if r.get("verdict") != "prolazi" or r.get("rank") is None or st.get("state") in ("pumpa", "pada"):
            continue
        if (r.get("liq") or 0) < MOON_MIN_LIQ:
            continue
        rows.append(r)
    rows.sort(key=lambda r: r["rank"])
    rows = rows[:n]
    conv = _converge([r["token"] for r in rows], t)
    out = []
    for r in rows:
        st = r.get("state") or {}
        parts = [f"#{r['rank']} među prijedlozima alata po confidenceu", "prošao rug check"]
        c = conv.get(r["token"])
        if c and c["handles"]:
            parts.append("u zadnja 24 h ušli: " + ", ".join(str(h) for h in c["handles"][:3]))
        if st.get("advice"):
            parts.append(st["advice"].rstrip("."))
        parts.append(f"vrijednost {_usd(r.get('mcap'))}, likvidnost {_usd(r.get('liq'))}")
        out.append({"mint": r["token"], "symbol": r.get("symbol"), "kind": "moon", "score": None,
                    "why": "; ".join(parts) + ". Visok rizik: samo mali ulog."})
    return out


def token_recs(now=None):
    def build():
        long_ = []
        moon = []
        try:
            long_ = _long_term()
        except Exception as e:  # noqa: BLE001
            print(f"autopilot: dugoročni: {type(e).__name__}: {e}", flush=True)
        try:
            moon = _moonshots(now=now)
        except Exception as e:  # noqa: BLE001
            print(f"autopilot: moonshot: {type(e).__name__}: {e}", flush=True)
        return {"dugo": long_, "moon": moon}
    return _cached(f"tok{now or ''}", build) or {"dugo": [], "moon": []}


def clear():
    _CACHE.clear()


if os.environ.get("AUTOPILOT_NO_CACHE") == "1":   # tests
    CACHE_S = 0
