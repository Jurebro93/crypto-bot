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
HIT = 0.5            # a call is a hit when the price rose +50% at some point within 24 h (old measure, fallback only)
MIN_CALLS = 3        # fewer measured calls in the window = not enough to judge
MIN_CLOSED = 3       # wallets: tokens bought and sold in the window
# 9.11. (audit P12/P15/P16): the minute check (kol/minute.py, +10 % before the -20 % stop within the hour) is the
# primary rank of influencers; the 24-h wick above stands in only while an account has fewer than MIN_MINUTE measured
# minute calls (DNEVNIK 9.11.: the wick is "too late and too optimistic for real money"). Same bar as minute.hot().
MIN_MINUTE = 10   # 10.11. (Jure: "preporučuješ ovog influencera kao najboljeg, a ima većinu loss"): 6 calls at 6/6
                  # ranked first; 10 is the bar kol/tpsl.MIN_N already uses before money follows a measure
OLD_MIN_MINUTE = 5   # below MIN_MINUTE the minute check cannot rank, but from here it can already say "bad"
WILSON_Z = 1.64   # 10.11.: rank by the lower end of the +10 % share (one-sided 95 %), not by the raw share of a few calls
HOT_HIT10 = 0.5
HOT_MAX_SL = 0.3
MAX_OPEN_SHARE = 0.5   # 9.11. (audit P13/P34): wallets with more than half of the bought tokens never sold are not copied
CANDLE_S = 300         # kol/measure.CANDLE: a call is complete once 24 h + one candle have passed
MOON_MIN_LIQ = 20_000
TOP = 10             # kept per window (the auto pick looks deeper than the page)
MAX_RUG = 0.3        # 9.11. (review): rug share above this (wick or minute measure) excludes an influencer
SHOW = 5
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
    hi = now - D - CANDLE_S   # 9.11. (audit P15): a call younger than 24 h is still being measured; its max24 is not a miss
    out = {}
    for h, ts, mx, r24, rug in calls:
        if ts < lo or ts > hi or mx is None:
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
    m = s.get("minute") or {}
    parts = []
    if s.get("mjera") == "minutna":   # 9.11. (audit P12/P15): say which measure chose the account
        parts.append(f"minutna provjera ({days} d): {m['n']} poziva, +10 % prije stopa u {m['hit10']:.0%}, stop prvi {m['sl']:.0%}"
                     + (f", do +10 % medijan {m['med_t10']:.0f} min" if m.get("med_t10") is not None else ""))
    if s.get("n"):
        parts.append(f"u zadnjih {days} dana {s['n']} izmjerenih callova; {s['hits']} ({s['hit']:.0%}) je u 24 h naraslo +50% ili više")
        if s["med24"] is not None:
            parts.append(f"tipičan rezultat dan kasnije {100 * s['med24']:+.0f}%")
        parts.append("bez ruga" if not s["rugs"] else f"{s['rugs']} rug ({s['rug']:.0%})")
    if s.get("mjera") != "minutna":
        parts.append(f"stara mjera (fitilj +50 % u 24 h): minutna provjera još nema {MIN_MINUTE} poziva"
                     + (f", ima {m['n']}" if m.get("n") else ""))
    txt = "; ".join(parts) + "."
    txt += (" Pratimo ga uživo, pa bot uđe u sekundama." if live else
            " Ne pratimo ga uživo: njegove callove vidimo kasnije, pa bot često zakasni na ulaz.")
    return txt


def minute_windows(now):
    """{days: {handle: stats}} from the minute check (kol/minute.handle_stats, one measured call per account and
    token); empty dicts when minute.db is missing or unreadable."""
    out = {d: {} for d in WINDOWS}
    try:
        from kol import minute
        mc = minute.ro()
        if mc is None:
            return out
        try:
            for d in WINDOWS:
                out[d] = dict(minute.handle_stats(mc, d, int(now), min_n=1))
        finally:
            mc.close()
    except Exception as e:  # noqa: BLE001
        print(f"autopilot: minutna provjera: {type(e).__name__}: {e}", flush=True)
    return out


def wilson_low(share, n, z=WILSON_Z):
    """Lower end of the Wilson interval of a share measured on n calls: 6 of 6 is about 0.69, 40 of 50 about 0.70,
    so a short lucky run no longer outranks a long good record (10.11.)."""
    if not n:
        return 0.0
    p = max(0.0, min(1.0, share))
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (c - r) / d)


def kol_rank(st, mst):
    """handle -> s for one window. 9.11. (audit P12/P15/P16): an account with MIN_MINUTE+ measured minute calls is
    judged by them alone (+10 % before the stop in HOT_HIT10+, stop first in at most HOT_MAX_SL; known bad minute data
    never falls back to the wick); an account with fewer keeps the old 24-h wick stats (st), marked mjera='fitilj'
    so the page and the auto pick can say which measure chose it. score: hit10 - sl (minutna) or the wick score.
    9.11. (review): a known rug share over MAX_RUG on EITHER measure excludes the account in both branches (a pump that
    rugs after +10 % counts as a minute hit, so the minute check alone would let it through). The two scores are on
    different scales; kol_recs sorts minutna ahead of fitilj on purpose, so with TOP+ minute-vouched accounts the
    wick fallback drops off the list entirely (intended: the fallback is only for accounts the minute check cannot
    judge yet)."""
    out = {}
    for h in set(st) | set(mst):
        m = mst.get(h)
        if m and m["n"] >= MIN_MINUTE:
            if m["hit10"] < HOT_HIT10 or m["sl"] > HOT_MAX_SL:
                continue
            if (m.get("rug") or 0) > MAX_RUG or ((st.get(h) or {}).get("rug") or 0) > MAX_RUG:
                continue   # known bad: a rug share on either measure is never a candidate for the real-money follow
            s = dict(st.get(h) or {"n": 0, "hits": 0, "rugs": 0, "r24": [], "hit": 0.0, "rug": 0.0, "med24": None})
            s.update(minute=m, mjera="minutna", score=wilson_low(m["hit10"], m["n"]) - m["sl"])
        else:
            s = st.get(h)
            if not s or s["n"] < MIN_CALLS or s["rug"] > MAX_RUG or s["hit"] <= 0:
                continue
            if m and (m.get("rug") or 0) > MAX_RUG:
                continue   # 9.11. (review): a rug the minute check saw counts even before it has MIN_MINUTE calls
            if m and m["n"] >= OLD_MIN_MINUTE and (m["hit10"] < HOT_HIT10 or m["sl"] > HOT_MAX_SL):
                continue   # 10.11. (pregled): 5-9 minute calls that already failed the bar are known bad, not "too few"
            s = dict(s, minute=m, mjera="fitilj")
        out[h] = s
    return out


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
        mins = minute_windows(t)
        out = {}
        for days in WINDOWS:
            st = kol_stats(calls, t, days)
            mst = {h: m for h, m in mins.get(days, {}).items() if h in good}
            rows = []
            try:   # 10.11.: the one influencer verdict every page shows (ui/kolsummary.verdict_stats, cached 5 min)
                from ui import kolsummary
                vs = kolsummary.verdict_stats(days)
            except Exception:  # noqa: BLE001 - the list stands without the word
                vs = {}
            for h, s in kol_rank(st, mst).items():
                live = good[h]["live"]
                v = vs.get(h) or {}
                # 10.11. (Jure: "preporučuješ ovog influencera kao najboljeg, a ima većinu loss"): an account we do not
                # watch live reaches us minutes late, after the pump its minute check measures; it is listed as too
                # slow for us (can_copy False) and is never the "best" of the window nor the auto pick (live only)
                rows.append({"handle": h, "live": live, "can_copy": bool(live), "s": s, "why": _kol_why(h, s, days, live),
                             "followers": good[h].get("followers"), "verdict": v.get("word"), "verdict_key": v.get("key")})
            # live first, then the accounts the minute check vouches for, then the wick fallback by its own score
            rows.sort(key=lambda r: (r["live"], r["s"]["mjera"] == "minutna", r["s"]["score"]), reverse=True)
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
        k = per.setdefault((w, mint), {"first": None, "in": 0.0, "out": 0.0, "sold": False})
        if side == "buy":
            if k["first"] is None:
                k["first"] = ts
            k["in"] += sol or 0
        elif k["first"] is not None:
            k["sold"] = True   # 9.11. (audit P14): chain_trades sells carry no SOL amount (chainwatch writes None)
            k["out"] += sol or 0
    out = {}
    for (w, _mint), k in per.items():
        if k["first"] is None or k["first"] < lo or k["in"] <= 0:
            continue
        s = out.setdefault(w, {"bought": 0, "closed": 0, "priced": 0, "wins": 0, "sol_in": 0.0, "sol_out": 0.0})
        s["bought"] += 1
        if k["sold"]:
            s["closed"] += 1
        if k["out"] > 0:   # the return is known only where the sale's SOL was recorded
            s["priced"] += 1
            s["wins"] += 1 if k["out"] > k["in"] else 0
            s["sol_in"] += k["in"]
            s["sol_out"] += k["out"]
    for s in out.values():
        s["open"] = s["bought"] - s["closed"]   # 9.11. (audit P13/P34): never sold = bags; not -100 %, but a penalty
        s["open_share"] = s["open"] / s["bought"] if s["bought"] else 0
        s["win"] = s["wins"] / s["priced"] if s["priced"] else 0
        s["roi"] = s["sol_out"] / s["sol_in"] - 1 if s["sol_in"] else None   # None: no sale amount recorded
        s["pnl"] = s["sol_out"] - s["sol_in"]
        s["avg_in"] = s["sol_in"] / s["priced"] if s["priced"] else 0
        # what a copier gets is the % return, not the wallet's SOL; few closed tokens weigh less; bags cost
        s["score"] = (min(s["roi"] or 0, 3.0) * min(1.0, s["closed"] / 8) + 0.3 * (s["win"] - 0.5) - s["open_share"])
    return out


def _wallet_why(s, days):
    held = f", još drži {s['open']}" if s.get("open") else ""
    if s.get("roi") is None:
        ret = "Iznos prodaja nije zapisan, pa povrat ne znam (nepoznato). "
    else:
        ret = (f"Na prodanima {100 * s['roi']:+.0f}% ({s['pnl']:+.2f} SOL), prosječno ulaže {s['avg_in']:.2f} SOL po tokenu. ")
    return (f"u {days} dana kupio {s['bought']} tokena, {s['closed']} prodao{held}; {s['wins']} u plusu ({s['win']:.0%}). "
            + ret + "Pratimo ga uživo, pa bot kupi u sekundama nakon njega.")


def _proven_why(r):
    hold = f", drži medijan {r['hold_min']:.0f} min" if r.get("hold_min") is not None else ""
    bags = (f"; {r['bags']} kupljenih tokena još drži ({r['bag_share']:.0%} knjige)" if r.get("bags") is not None
            and r.get("bag_share") is not None else "")
    return (f"dokazan dvaput (vlastiti rezultat na lancu): prije reza od 5 dana {r.get('closed_before') or 0} zatvorenih, "
            f"{(r.get('win_before') or 0):.0%} dobitnih, {(r.get('realized_before') or 0):+.2f} SOL; poslije reza "
            f"{r.get('closed_after') or 0} zatvorenih, {(r.get('realized_after') or 0):+.2f} SOL{hold}{bags}. "
            "Pratimo ga uživo, pa bot kupi u sekundama nakon njega.")


def proven_wallets():
    """9.11. (audit P13/P14): the wallets proven twice (wallets/dokazani.py: own on-chain result before AND after a
    5-day cut, copyable style, under a third of the book in open bags) as the auto pick's first wallet source. The
    7/14/30-day list below needs the SOL of each sale, which chain_trades does not record (sell rows carry None), so
    in production it stays empty and the auto pick never chose a wallet while the page said none qualified."""
    def build():
        from wallets import dokazani
        out = []
        for r in dokazani.latest():
            share = r.get("bag_share")
            if share is not None and share >= dokazani.RULE["max_bag_share"]:
                continue
            out.append({"wallet": r["wallet"], "name": "", "why": _proven_why(r), "proven": True,
                        "s": {"roi": None, "win": r.get("win_before"), "closed": r.get("closed_before"),
                              "score": r.get("realized_after") or 0}})
        return out
    return _cached("proven", build) or []


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
                # 9.11. (audit P13/P14): an unknown return (no sale amounts) is not a pass; many bags are not either
                if s["closed"] < MIN_CLOSED or s["roi"] is None or s["roi"] <= 0 or s["open_share"] > MAX_OPEN_SHARE:
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


# ---------- auto pick: the tool chooses whom the real-money account follows ----------------------------------------

AUTO_EVERY_S = 3600
_LAST = {"ts": 0}


def auto_targets(days, n, keep=(), skip=()):
    """[(kind, target, label, why)] the tool would follow: the n best live-watched influencers and the n best wallets of
    the window. An earlier pick in `keep` stays while it is still in the top 2n, so the list does not churn every hour."""
    out = []
    proven = proven_wallets()   # 9.11. (audit P13/P14): proven-twice wallets first, the window list after them
    seen = {r["wallet"] for r in proven}
    # 10.11. (Jure: da, popravi rangiranje): the auto pick takes only accounts we watch live AND that the minute check
    # vouches for (MIN_MINUTE+ calls); the 24-h wick fallback ("too optimistic for real money", 9.11.) stays a hint
    # 10.11. (pregled): an earlier pick that is still live and still recommended stays whatever the measure (a count
    # going 10 -> 9 as old calls leave the window must not unfollow it: a new follow id restarts its demo proof)
    groups = (("kol", [r for r in kol_recs().get(days) or [] if r["live"] and (
                   r["s"].get("mjera") == "minutna" or ("kol", r["handle"]) in keep)]),
              ("wallet", proven + [r for r in wallet_recs().get(days) or [] if r["wallet"] not in seen]))
    for kind, rows in groups:
        key = (lambda r: r["handle"]) if kind == "kol" else (lambda r: r["wallet"])
        # earlier picks still in the top 2n stay first, the rest of the n places go to the best new ones
        cand = [r for r in rows if (kind, key(r)) not in skip][:2 * n]
        picked = [r for r in cand if (kind, key(r)) in keep][:n]
        picked += [r for r in cand if r not in picked][:n - len(picked)]
        for r in picked:
            label = "" if kind == "kol" else (r.get("name") or "")
            out.append((kind, key(r), label, r["why"]))
    return out


def sync_follows(con, tcon, now=None, force=False):
    """Make the real-money account's auto follows match auto_targets(). Manual follows are never touched.
    Returns [text] of what changed. Runs at most once an hour (league/auto.py loop), or at once with force."""
    from league import copy
    from trade import settings
    now = now or time.time()
    if not force and now - _LAST["ts"] < AUTO_EVERY_S:
        return []
    _LAST["ts"] = now
    s = settings.raw(tcon)
    if not s.get("auto_pick"):
        return []
    days = int(s.get("auto_days") or 14)
    n = int(s.get("auto_n") or 3)
    auto_ids = {int(i) for i in s.get("auto_follows") or []}
    active = {f["id"]: f for f in copy.follows(con, settings.LEAGUE_USER)}
    mine = {(f["kind"], f["target"]): fid for fid, f in active.items() if fid in auto_ids}
    manual = {(f["kind"], f["target"]) for fid, f in active.items() if fid not in auto_ids}
    skip = {tuple(x) for x in s.get("auto_skip") or []}
    want = auto_targets(days, n, keep=set(mine), skip=skip)
    if not want:   # no data (e.g. stats not computed yet): keep what we have rather than drop everyone
        return []
    want_keys = {(k, t) for k, t, _, _ in want}
    want_kinds = {k for k, _, _, _ in want}
    log, changes = list(s.get("auto_log") or []), []
    for key, fid in mine.items():
        if key[0] not in want_kinds:
            continue   # 10.11. (pregled): no candidate of this kind at all (minute.db or kol.db locked, a quiet day): keep
        if key not in want_keys:
            copy.unfollow(con, settings.LEAGUE_USER, fid)
            auto_ids.discard(fid)
            changes.append(("−", key[0], key[1], f"ispao iz najboljih {2 * n} u zadnjih {days} dana"))
    tp = f"{int(s.get('tp_default') or 15)}%"   # 9.11. (audit P68): the owner's exit target holds for the auto picks too
    for kind, target, label, why in want:
        if (kind, target) in mine or (kind, target) in manual:
            continue
        if kind == "wallet":   # a wallet copy sells when he sells (mirror): the intended default
            fid = copy.follow(con, settings.LEAGUE_USER, kind, target, label, 25, 5)
        else:
            fid = copy.follow(con, settings.LEAGUE_USER, kind, target, label, 25, 5, "tpsl", tp, copy.DEFAULT_SL)
        auto_ids.add(fid)
        changes.append(("+", kind, target, why))
    settings.put(tcon, "auto_follows", sorted(auto_ids), "alat")
    if changes:
        log = ([{"ts": int(now), "op": op, "kind": k, "target": t, "why": w} for op, k, t, w in changes] + log)[:30]
        settings.put(tcon, "auto_log", log, "alat")
    return [f"autopilot {op} {k} {t}" for op, k, t, _ in changes]


def maybe_sync(con):
    """league/auto.py loop: once an hour, only while the owner has switched the auto pick on."""
    from trade import settings
    if time.time() - _LAST["ts"] < AUTO_EVERY_S:
        return []
    tcon = settings.connect()
    try:
        from trade import executor
        executor.connect(settings.DB).close()
        return sync_follows(con, tcon)
    finally:
        tcon.close()


if os.environ.get("AUTOPILOT_NO_CACHE") == "1":   # tests
    CACHE_S = 0
