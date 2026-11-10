"""The "Prijedlog za danas" box (Jure 7.11.): the first thing a user sees is what the tool concluded from everything
it analysed and, concretely, where to put money today and why. Each pick carries the market cap at the moment of the
analysis; the page asks /api/prijedlog every minute for the live market cap and says "OK" / "pričekaj povlačenje"
(the user may read the page minutes later, when a $50k entry is already $70k).

10.11. (Jure, prijedlog 3.1 i 5.1): the box lives only on Pregled, as the compact variant box("pregled") (compact():
one answer, rows, the whole old text in a pop-up). The tokeni / influenceri / novcanici variants stay working for any
caller left (and /api/prijedlog?box=...)."""
import json
import re
import sqlite3
import time

from ui import data
from ui.html import esc, tlink, usd, wlink


def _kol_db():
    from kol import store as _ks
    return _ks.DB

PULL_X = 1.25    # above this multiple of the analysed market cap: wait for a pullback
DROP_X = 0.80    # below: falling, do not chase
MAX_AGE_S = 6 * 3600
TARGET = 0.30    # "chance of +30 %": share of measured calls in the same market-cap band that reached +30 % in 24 h


def _band(m):
    m = m or 0
    return ("<50k" if m < 5e4 else "50–100k" if m < 1e5 else "100–300k" if m < 3e5 else "300k–1M" if m < 1e6
            else "1–10M" if m < 1e7 else "10M+")


def _band_lo_hi(b):
    return {"<50k": (0, 5e4), "50–100k": (5e4, 1e5), "100–300k": (1e5, 3e5), "300k–1M": (3e5, 1e6),
            "1–10M": (1e6, 1e7), "10M+": (1e7, 1e99)}[b]


CHANCES_TTL_S = 600   # 10.11. (audit sekundni S1): max24 changes only when the KOL round measures, so 10 min is fresh
_CHANCES = {}         # (days, kol.db path) -> (wall time, result); only non-empty results are kept


def chances(days=14):
    """{band: (share of calls with max24 >= TARGET, n)} from kol.db measured calls (the retro of 7.11.).
    10.11. (audit sekundni S1): kept 10 min. It used to read every measured call of 14 days on every call: the live
    box asked every 2 s and every open token pop-up every second (166 ms each on a production-sized copy)."""
    key = (days, _kol_db())
    hit = _CHANCES.get(key)
    if hit and time.time() - hit[0] < CHANCES_TTL_S:
        return dict(hit[1])
    out = {}
    try:
        # 9.11. (audit P81): KOL calls only, as kol/together and kol/converge count them: no alert bots (they post
        # every fresh pool) and no 'bad' rows (dust market cap) in the band's denominator
        rows = data.q(_kol_db(), "SELECT mcap0, max24 FROM calls WHERE max24 IS NOT NULL AND kind = 'call' AND bad IS NULL "
                                   "AND ts >= ? AND source NOT IN ('kol_win')", (int(time.time() - days * 86400),))
    except Exception:  # noqa: BLE001
        rows = []
    by = {}
    for r in rows:
        by.setdefault(_band(r["mcap0"]), []).append(r["max24"] or 0)
    for b, xs in by.items():
        if len(xs) >= 30:
            out[b] = (sum(1 for x in xs if x >= TARGET) / len(xs), len(xs))
    if out:   # an empty answer (no file yet, a locked read) is asked again next time
        _CHANCES[key] = (time.time(), dict(out))
    return out


def analysed(now=None):
    """What the tool looked at in the last 24 h, in plain numbers."""
    now = now or time.time()
    since = int(now - 86400)
    n = {}
    try:
        n["tokena"] = data.q(data.HYPE_DB, "SELECT COUNT(DISTINCT token) c FROM hype_signals WHERE ts >= ?", (since,))[0]["c"]
    except Exception:  # noqa: BLE001
        n["tokena"] = 0
    try:
        n["poziva"] = data.q(_kol_db(), "SELECT COUNT(*) c FROM calls WHERE ts >= ? AND kind='call'", (since,))[0]["c"]
        n["kolova"] = data.q(_kol_db(), "SELECT COUNT(*) c FROM kols")[0]["c"]
    except Exception:  # noqa: BLE001
        n["poziva"], n["kolova"] = 0, 0
    try:
        n["novcanika"] = data.q(data.WALLET_DB, "SELECT COUNT(*) c FROM wallets WHERE score IS NOT NULL")[0]["c"]
    except Exception:  # noqa: BLE001
        n["novcanika"] = 0
    try:
        from strat import store as sstore
        con = sstore.ro()
        if con is not None:
            try:
                n["tradeova"] = con.execute("SELECT COUNT(*) FROM positions WHERE seen_ts >= ? AND status != 'skip'",
                                            (since,)).fetchone()[0]
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        n["tradeova"] = 0
    return n


LIVE_MIN = {"txns_h1": 10, "vol_h1": 1000.0, "liq": 20000.0, "max_drop_h1": -20.0}   # 9.11.: a pick must have a live market NOW
# and must not be falling: CATPAD passed the first version at -34 % in the hour ("pada, ne ulazi" was only a note)


def live_market(tokens, fetch=None):
    """token -> {price, liq, mcap, vol_h1, vol_h24, txns_h1, buys_h1, txns_h24, ch_h1, ch_h24} from DexScreener's
    deepest pair (one request per 30 tokens, free); None when the request failed (then nothing is recommended)."""
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        return {}
    try:
        from dexscreener import client
        # 9.11. (audit P2): the live cache (DEX_LIVE_TTL, 3 s), not the scanners' 60 s; `fetch` stays the test seam
        pairs = (fetch or (lambda t: client.tokens_live("solana", t)))(tokens)
    except Exception:  # noqa: BLE001
        return None
    out = {}
    for pr in pairs or []:
        t = (pr.get("baseToken") or {}).get("address")
        liq = (pr.get("liquidity") or {}).get("usd") or 0
        if not t or (t in out and liq < out[t]["liq"]):
            continue
        tx, vol, ch = pr.get("txns") or {}, pr.get("volume") or {}, pr.get("priceChange") or {}
        h1, h24 = tx.get("h1") or {}, tx.get("h24") or {}
        out[t] = {"price": float(pr.get("priceUsd") or 0), "liq": float(liq), "mcap": float(pr.get("marketCap") or pr.get("fdv") or 0),
                  "vol_h1": float(vol.get("h1") or 0), "vol_h24": float(vol.get("h24") or 0),
                  "txns_h1": int((h1.get("buys") or 0) + (h1.get("sells") or 0)), "buys_h1": int(h1.get("buys") or 0),
                  "txns_h24": int((h24.get("buys") or 0) + (h24.get("sells") or 0)),
                  "vol_m5": float(vol.get("m5") or 0), "txns_m5": int(((tx.get("m5") or {}).get("buys") or 0) + ((tx.get("m5") or {}).get("sells") or 0)),
                  "ch_m5": ch.get("m5"), "ch_h1": ch.get("h1"), "ch_h24": ch.get("h24")}
        # 10.11. (Jure: "stavi to u tablicu kao na DexScreeneru"): every window the pair has, buys and sells apart
        out[t]["w"] = {w: {"ch": ch.get(w), "vol": float(vol.get(w) or 0), "buys": int((tx.get(w) or {}).get("buys") or 0),
                           "sells": int((tx.get(w) or {}).get("sells") or 0)} for w in ("m5", "h1", "h6", "h24")}
    return out


def alive(lv):
    """None when the token trades right now; otherwise the plain reason it is not a pick."""
    if lv is None:
        return "nema živog para na DexScreeneru"
    if lv["txns_h1"] < LIVE_MIN["txns_h1"]:
        return f"samo {lv['txns_h1']} transakcija u zadnjem satu (treba {LIVE_MIN['txns_h1']}+)"
    if lv["vol_h1"] < LIVE_MIN["vol_h1"]:
        return f"volumen u zadnjem satu ${lv['vol_h1']:,.0f} (treba ${LIVE_MIN['vol_h1']:,.0f}+)"
    if lv["liq"] < LIVE_MIN["liq"]:
        return f"likvidnost ${lv['liq']:,.0f} (treba ${LIVE_MIN['liq']:,.0f}+)"
    if lv.get("ch_h1") is not None and float(lv["ch_h1"]) <= LIVE_MIN["max_drop_h1"]:
        return f"pada: {float(lv['ch_h1']):+.0f} % u zadnjem satu, ne ulazi dok se ne okrene"
    return None


def history(token):
    """What the bases already know about the token: who called it, how its calls did minute by minute
    (kol/minute.py) and how it ended when the box suggested it before. Zeros when a base is missing."""
    out = {"callers": 0, "bots": 0, "first_call": None, "minute_n": 0, "minute_hit10": 0, "suggested": 0,
           "sugg_hit": 0, "sugg_stop": 0}
    try:
        kp = _kol_db()
        rows = data.q(kp, """SELECT c.handle, MIN(c.ts) AS ts, COALESCE(k.bot, 0) AS bot FROM calls c
            LEFT JOIN kols k ON k.handle = c.handle WHERE c.token = ? AND c.kind = 'call' AND c.handle NOT LIKE 'w:%'
            GROUP BY c.handle""", (token,))
        out["callers"] = sum(1 for r in rows if not r["bot"])
        out["bots"] = sum(1 for r in rows if r["bot"])
        ts = [r["ts"] for r in rows if not r["bot"] and r["ts"]]
        out["first_call"] = min(ts) if ts else None
    except Exception:  # noqa: BLE001
        pass
    try:
        from kol import minute
        mp = data.q(minute.db_path(), "SELECT t10, sl_min FROM call_path WHERE token = ? AND entry IS NOT NULL AND bad IS NULL", (token,))
        out["minute_n"] = len(mp)
        out["minute_hit10"] = sum(1 for r in mp if r["t10"] is not None and (r["sl_min"] is None or r["t10"] < r["sl_min"]))
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = data.q(data.HYPE_DB, "SELECT hit, stop_first FROM prijedlog_log WHERE token = ? AND labelled_ts IS NOT NULL", (token,))
        out["suggested"] = len(rows)
        out["sugg_hit"] = sum(1 for r in rows if r["hit"])
        out["sugg_stop"] = sum(1 for r in rows if r["stop_first"])
    except Exception:  # noqa: BLE001
        pass
    return out


def thesis(p):
    """The case for the pick in plain words, from the measured data only: thesis, live market, history, against."""
    lv, h = p.get("live") or {}, p.get("history") or {}
    za = [w for w in (p.get("why") or []) if w]
    parts = ["Teza: " + (smart_fix(za[0].rstrip(".")) if za else "ocjena alata i Šansa iznad praga") + "."]
    if lv:
        # 10.11. (prijedlog, pravilo 8): Croatian numbers ("5,0k $", "0,1×", "+6 %"); the thesis is read in the Pregled
        # pop-up next to rows that already write them so
        from ui import redak as R
        turn = lv["vol_h1"] / lv["liq"] if lv.get("liq") else 0
        ch1 = R.pct(lv["ch_h1"]) if lv.get("ch_h1") is not None else "?"
        ch24 = R.pct(lv["ch_h24"]) if lv.get("ch_h24") is not None else "?"
        parts.append(f"Uživo: {R.num(lv['txns_h1'])} transakcija i {R.usd(lv['vol_h1'])} volumena u zadnjem satu "
                     f"({R.num(turn, 1)}× likvidnosti), cijena 1 h {ch1}, 24 h {ch24}.")
    hist = []
    hist.append(f"zvalo ga {h['callers']} računa" if h.get("callers") else "nitko ga od praćenih računa nije zvao")
    if h.get("minute_n"):
        hist.append(f"minutna provjera: {h['minute_hit10']} od {h['minute_n']} poziva dalo +10 % prije stopa")
    else:
        hist.append("još bez minutne provjere")
    if h.get("suggested"):
        hist.append(f"već predložen {h['suggested']}×: {h['sugg_hit']}× +15 % prije stopa, {h['sugg_stop']}× stop prvi")
    parts.append("Povijest: " + "; ".join(hist) + ".")
    protiv = [w for w in (p.get("protiv") or []) if w][:2]
    if protiv:
        parts.append("Protiv: " + "; ".join(w.rstrip(".") for w in protiv) + ".")
    return " ".join(parts)


def token_picks_ex(now=None, n=3, rows=None, status=None, ch=None, live=None, max_candidates=12):
    """(picks, near, note). A pick passes every filter (not rugged, confidence >= 35, fresh <= 24 h, mcap >= 30k) AND
    trades right now (LIVE_MIN) AND carries its thesis from the data. near: [(candidate, reason)] that failed only the
    live check, so the page can say why nothing is offered instead of offering the least bad token (Jure 9.11.:
    "token kojeg alat preporuči mora biti tu s razlogom"). note: why the live check could not run."""
    from ui import overview
    now = now or time.time()
    rows = rows if rows is not None else overview.token_rows()
    if status is None:
        try:
            from hype import tokenstatus
            status = tokenstatus.read(data.HYPE_DB)
        except Exception:  # noqa: BLE001
            status = {}
    ch = ch if ch is not None else chances()
    cands = []
    ranked = sorted(rows, key=overview._rank, reverse=True)
    # 9.11. (audit P79): freshness from the last real signal when overview gives it (signal_ts); last_seen also moves
    # with a rug re-check (every 12 h), which is not a new signal
    def _fresh(r):
        return r.get("signal_ts") or r["last_seen"] or 0
    for razina, ok in (("visoka", lambda r: overview.relevant(r) and now - _fresh(r) <= MAX_AGE_S),
                       ("srednja", lambda r: overview.relevant(r) and now - _fresh(r) <= 24 * 3600)):
        for r in ranked:
            if len(cands) >= max_candidates:
                break
            if any(p["token"] == r["token"] for p in cands) or not ok(r):
                continue
            p = _pick(r, status, ch, now)
            if p:
                p["razina"] = razina
                cands.append(p)
    if not cands:
        return [], [], ""
    lv = live if live is not None else live_market([p["token"] for p in cands])
    if lv is None:
        return [], [], "provjera trenutnog prometa (DexScreener) nije uspjela, pa danas ništa ne predlažem"
    picks, near = [], []
    for p in cands:
        m = lv.get(p["token"])
        why_not = alive(m)
        if why_not:
            near.append((p, why_not))
            continue
        p["live"] = m
        if m.get("mcap"):
            p["mcap0"] = m["mcap"]
        p["history"] = history(p["token"])
        p["thesis"] = thesis(p)
        picks.append(p)
        if len(picks) >= n:
            break
    return picks, near, ""


def token_picks(now=None, n=3, rows=None, status=None, ch=None, live=None):
    """Up to n tokens to enter now, best first; see token_picks_ex. Only grades 'visoka' (fresh <= 6 h) and 'srednja'
    (<= 24 h): a token below the confidence bar is never a pick any more (9.11.)."""
    return token_picks_ex(now, n, rows, status, ch, live)[0]


def _pick(r, status, ch, now):
    if True:
        st = status.get(r["token"])
        if st and not st.get("has_pair"):
            return None
        mcap = (st or {}).get("mcap") or r.get("mcap")
        if not mcap or mcap < 30_000:
            return None
        try:
            from ui.radar import reasons
            why = reasons(r["features"], r["det"])[:3]
        except Exception:  # noqa: BLE001
            why = []
        if not why:
            why = [t for p, t in r.get("conf_parts") or [] if p > 0][:3]
        b = _band(mcap)
        protiv = [t for p_, t in r.get("conf_parts") or [] if p_ < 0][:3]
        rv = (r.get("rug") or {}).get("verdict") if isinstance(r.get("rug"), dict) else None
        # only a verdict that is not a pass is a point against (15:43: "Protiv: rug filter: PROLAZI" was shown)
        if rv and rv.upper() not in ("PROLAZI", "PROŠAO", "OK", "PROSAO") and f"rug filter: {rv}" not in protiv:
            protiv.insert(0, f"rug filter: {rv}")
        return {"token": r["token"], "symbol": r["symbol"], "mcap0": mcap, "ts0": int(r["last_seen"] or now),
                "conf": r.get("conf"), "why": why, "protiv": protiv, "band": b, "chance": ch.get(b)}


def kol_picks(now=None, n=3):
    """KOLs worth following today: proven score, enough measured calls, and what they called in the last 6 h."""
    now = now or time.time()
    try:
        from ui.kol import _cfg
        good = _cfg().get("good_score", 60)
    except Exception:  # noqa: BLE001
        good = 60
    try:
        kols = data.q(_kol_db(), "SELECT handle, score, followers, stats FROM kols WHERE score IS NOT NULL "
                                   "ORDER BY score DESC LIMIT 40")
    except Exception:  # noqa: BLE001
        return []
    out = []
    proven = []
    for k in kols:
        try:
            s = json.loads(k["stats"] or "{}")
        except ValueError:
            s = {}
        k = dict(k)
        k["_s"] = s
        if (s.get("measured") or 0) >= 5 and (k["score"] or 0) >= good:
            proven.append(k)
    # proven accounts first; with fewer than n of them, the best on trial with at least 3 measured calls fill in
    rest = [k for k in kols if (dict(k).get("stats") and json.loads(k["stats"] or "{}").get("measured", 0) >= 3)
            and k["handle"] not in {p["handle"] for p in proven}]
    minute_stats = {}
    try:   # 9.11.: the minute check (kol/minute.py, minute.db) is the honest measure; the leaderboard's hit is a 24-h wick
        from kol import minute
        mc = minute.ro()
        if mc is not None:
            try:
                minute_stats = dict(minute.handle_stats(mc, 14, int(now), min_n=1))
            finally:
                mc.close()
    except Exception:  # noqa: BLE001
        minute_stats = {}
    for k in list(proven) + [dict(x, _s=json.loads(x["stats"] or "{}"), _trial=True) for x in rest]:
        s = k["_s"]
        last = data.q(_kol_db(), "SELECT token, symbol, ts, mcap0 FROM calls WHERE handle=? AND kind='call' "
                                   "ORDER BY ts DESC LIMIT 1", (k["handle"],))
        last = last[0] if last else None
        out.append({"handle": k["handle"], "score": k["score"], "followers": k["followers"], "hit": s.get("hit_rate"),
                    "measured": s.get("measured"), "rug": s.get("rug_rate"), "late": s.get("prepump_rate"),
                    "minute": minute_stats.get(k["handle"]),
                    "last": dict(last) if last else None, "trial": bool(k.get("_trial")),
                    "fresh": bool(last and now - (last["ts"] or 0) <= MAX_AGE_S)})
        if len(out) >= n:
            break
    return out


def wallet_picks(now=None, n=2):
    """Wallets to copy today (ui/preporuka ranking) and their freshest buy."""
    try:
        from ui import preporuka
        ranked = preporuka.rank_wallets(data.wallets(scored_only=True), preporuka.copies_from_strat())
    except Exception:  # noqa: BLE001
        return []
    if not ranked:   # nobody passes the copy bar: the best by closed trades and win rate, graded 'niska'
        try:
            ws = [w for w in data.wallets(scored_only=True) if (w.get("stats") or {}).get("closed", 0) >= 3
                  and (w.get("stats") or {}).get("closed_pnl_sol", 0) > 0]
            ws.sort(key=lambda w: (-(w["stats"].get("win_rate") or 0), -(w["stats"].get("closed") or 0)))
            ranked = [(w, {"tier": "niska"}) for w in ws[:n]]
        except Exception:  # noqa: BLE001
            ranked = []
    proven = set()
    try:
        from wallets import dokazani
        proven = set(dokazani.current())
    except Exception:  # noqa: BLE001
        pass
    out = []
    for w, r in ranked[:n]:
        last = None
        try:
            rows = data.q(data.HYPE_DB, "SELECT mint, ts FROM chain_trades WHERE wallet=? AND side='buy' ORDER BY ts DESC LIMIT 1",
                          (w["wallet"],))
            last = dict(rows[0]) if rows else None
        except Exception:  # noqa: BLE001
            pass
        labels = w.get("labels") or []
        if isinstance(labels, str):
            try:
                labels = json.loads(labels)
            except ValueError:
                labels = [x.strip() for x in labels.split(",") if x.strip()]
        try:
            from wallets import dokazani
            cop = dokazani.copyable(w.get("stats") or {}, labels)
        except Exception:  # noqa: BLE001
            cop = None
        out.append({"wallet": w["wallet"], "tier": r["tier"], "stats": w.get("stats") or {}, "last": last,
                    "proven": w["wallet"] in proven, "copyable": cop})
    return out


def _tl(token, sym=None):
    """Compact token link for the box (no icon row: the lists below have them)."""
    from ui.html import short
    from urllib.parse import quote
    return f'<a href="/token/{quote(token)}" translate=no>{esc(sym) if sym else "<code>" + esc(short(token)) + "</code>"}</a>'


CREW_MIN_N = 5          # 9.11. (audit P80): minute measurements before a crew's minute check decides (DNEVNIK 9.11.)
CREW_MIN_HIT10 = 0.5
CREW_MAX_SL = 0.3


def crew_minute_ok(members, crews):
    """None when the minute check (kol/minute.crew_stats 'crews': [(handles, stats, n_tokens, potential)]) has no
    CREW_MIN_N+ measured first calls by 2+ of these members; else whether they gave +10 % before the stop in
    CREW_MIN_HIT10+ with the stop first in at most CREW_MAX_SL (pooled over the matching crews)."""
    mem = set(members or ())
    rows = [(st["n"], st["hit10"], st["sl"]) for hs, st, *_ in crews or []
            if st and len(set(hs)) >= 2 and set(hs) <= mem]
    n = sum(r[0] for r in rows)
    if n < CREW_MIN_N:
        return None
    hit10 = sum(r[0] * r[1] for r in rows) / n
    sl = sum(r[0] * r[2] for r in rows) / n
    return hit10 >= CREW_MIN_HIT10 and sl <= CREW_MAX_SL


def _minute_crews(now=None):
    try:
        from kol import minute, store as _ks
        mcon, kcon = minute.ro(), _ks.ro()
        if mcon is None or kcon is None:
            return []
        try:
            return minute.crew_stats(mcon, kcon, 14, int(now or time.time()), min_n=1).get("crews") or []
        finally:
            mcon.close()
            kcon.close()
    except Exception:  # noqa: BLE001
        return []


def group_pick(crews=None):
    """The best crew of KOLs that call together (kol/together): follow them, enter when they post.
    9.11. (audit P80): a crew needs together.MIN_N joint calls (the module's own bar for a verdict, not 3) and, where
    the minute check has measured it, +10 % before the stop in half of them; crews: injected for tests."""
    try:
        from kol import shillers, store as _ks, together
        con = _ks.ro() if hasattr(_ks, "ro") else None
        if con is None:
            import sqlite3 as _s
            con = _s.connect(f"file:{_ks.DB}?mode=ro", uri=True)
            con.row_factory = _s.Row
        try:
            tog = together.build(con, shillers.handles())
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None
    return pick_crew(tog.get("clusters") or [], crews if crews is not None else _minute_crews())


def pick_crew(clusters, crews):
    from kol import together
    min_n = getattr(together, "MIN_N", 8)
    good = [c for c in clusters if c["stats"]["n"] >= min_n and (c["stats"]["hit"] or 0) >= 0.5
            and (c["stats"]["rug"] or 0) < 0.4 and not c.get("shill")]
    for c in good:
        ok = crew_minute_ok(c["members"], crews)
        if ok is False:   # known bad minute data: not recommended; None (no data yet) keeps the old measure
            continue
        return {"members": c["members"][:5], "n": c["stats"]["n"], "hit": c["stats"]["hit"], "rug": c["stats"]["rug"],
                "tokens": c["tokens"], "minute": ok}
    return None


def _chance_txt(c):
    if not c:
        return "povijest još nema dovoljno sličnih poziva"
    from ui import redak as R
    return (f"{R.pct(c[0], sign=False, frac=True)} sličnih tokena (po market capu) napravilo je +30 % u 24 h "
            f"({R.num(c[1])} izmjerenih poziva)")


def _makro_line():
    try:
        from market import makro
        return makro.line()
    except Exception:  # noqa: BLE001
        return ""


JS = r"""
<script>(()=>{let b=document.getElementById('pdj');if(!b)return;
// 7.11. (Jure): the box rebuilds itself every 60 s from the server (fresh picks), the page need not reload
async function reload(){try{const r=await fetch('/api/prijedlog?box='+encodeURIComponent(b.dataset.kind),{cache:'no-store'});if(!r.ok)return;
 const t=document.createElement('div');t.innerHTML=await r.text();const nb=t.querySelector('#pdj');if(!nb)return;b.replaceWith(nb);b=nb;prices()}catch(e){}}
function age(){const a=document.getElementById('pdj-age'),ts=+(b.dataset.ts||0);if(!a||!ts)return;const s=Math.round(Date.now()/1000-ts);
 a.textContent=s<15?'osvježeno upravo sada':'osvježeno prije '+(s<60?s+' s':Math.round(s/60)+' min')}
setInterval(age,5000);setInterval(reload,60000);
function prices(){const items=[...b.querySelectorAll('[data-p]')];if(!items.length)return;
const fmt=v=>v>=1e6?'$'+(v/1e6).toFixed(2)+'M':v>=1e3?'$'+(v/1e3).toFixed(1)+'k':'$'+Math.round(v);
async function tick(){try{const q=items.map(e=>e.dataset.p).join(',');const r=await fetch('/api/prijedlog?t='+q,{cache:'no-store'});if(!r.ok)return;const j=await r.json();
items.forEach(e=>{const m=j[e.dataset.p];const s=e.querySelector('.pnow');if(!s)return;if(!m||!m.mcap){s.textContent='(cijena trenutno nedostupna)';return}
const x=m.mcap/(+e.dataset.m0||m.mcap);let t='sada '+fmt(m.mcap)+' ('+(x>=1?'+':'')+Math.round((x-1)*100)+'% od analize): ';
if(x>=__PULL__){t+='⏳ pričekaj povlačenje, ne juri';s.className='pnow neg'}else if(x<=__DROP__){t+='⚠️ pada, ne ulazi dok se ne okrene';s.className='pnow neg'}else{t+='✅ još je u zoni ulaza';s.className='pnow pos'}s.textContent=t})}catch(e){}}
tick()}
prices();setInterval(()=>{if(!document.hidden)prices()},60000)})()</script>""".replace("__PULL__", str(PULL_X)).replace("__DROP__", str(DROP_X))

CSS = ("<style>.pdj{border:2px solid var(--acc);border-radius:14px;padding:12px 14px;margin:8px 0 14px;background:var(--card)}"
       ".pdj h2{margin:0 0 6px;font-size:17px}.pdj .an{color:var(--mut);font-size:13px;margin:0 0 8px}"
       ".pdj ol{margin:0;padding-left:20px}.pdj li{margin:0 0 10px}.pdj .pnow{display:block;font-size:13px;margin-top:2px}"
       ".pdj .pnow.pos{color:var(--good)}.pdj .pnow.neg{color:var(--bad)}.pdj .why{color:var(--mut);font-size:13px}"
       ".pdj details{margin-top:6px}.pdj summary{cursor:pointer;color:var(--acc);font-size:13px}</style>")


def kol_thesis(k):
    """Why this account is (or is not yet) worth following, from the numbers: minute check first, then the old 24-h
    wick measure, rugs and late calls."""
    m = k.get("minute") or {}
    parts = []
    if m.get("n"):
        parts.append(f"Minutna provjera (14 d): {m['hit10'] * m['n']:.0f} od {m['n']} poziva dalo +10 % prije stopa, "
                     f"stop prvi {m['sl']:.0%}" + (f", do +10 % medijan {m['med_t10']:.0f} min" if m.get("med_t10") is not None else "") + ".")
    else:
        parts.append("Još bez minutne provjere (puni se od 9.11.): brojke su po staroj mjeri, najviši fitilj +50 % u 24 h.")
    extra = []
    if k.get("rug") is not None:
        extra.append(f"rug {k['rug']:.0%}")
    if k.get("late") is not None:
        extra.append(f"kasni pozivi {k['late']:.0%}")
    if extra:
        parts.append("Protiv: " + ", ".join(extra) + ".")
    return " ".join(parts)


def wallet_thesis(w):
    """Copyability and proof for a wallet pick: proven twice (wallets/dokazani), hold time, trades per day."""
    s = w.get("stats") or {}
    parts = [f"Dokazani dvaput: {'da' if w.get('proven') else 'ne'}.",
             f"Kopirljiv: {'da' if w.get('copyable') else 'ne'} (drži medijan {s.get('median_hold_min') or 0:.0f} min, "
             f"{s.get('trades_per_day') or 0:.0f} tradeova/dan)."]
    return " ".join(parts)


def _item(p, status=None):
    raz = p.get("razina") or "visoka"
    # 9.11. (audit P50/P51/P79): 'uživo' = the Autopilot's live list (fresh reason now); the grade is freshness, not a
    # probability, so the badge says so
    cls = {"uživo": "good", "visoka": "good", "srednja": "warn", "niska": "bad"}.get(raz, "warn")
    stake = {"uživo": "25 $", "visoka": "25–50 $", "srednja": "20–25 $", "niska": "10 $ ili samo gledaj"}.get(raz, "20–25 $")
    text = p.get("thesis") or ("Zašto: " + ("; ".join(p["why"]) or "ocjena alata i Šansa") + ".")
    conf_txt = f' · pouzdanost {p["conf"]:.0f}' if p.get("conf") is not None else ""
    grade = "uživo (Autopilot)" if raz == "uživo" else f"svježina {raz}"
    return (f'<li data-p="{esc(p["token"])}" data-m0="{p["mcap0"]:.0f}"><b>{_tl(p["token"], p["symbol"])}</b> '
            f'<span class="b {cls}">{grade}</span> ulog {stake} · '
            f'na <b>{usd(p["mcap0"])[0]}</b> sada{conf_txt}'
            f'<span class=why><br>{esc(text)} {esc(_chance_txt(p["chance"]))}.</span>'
            f'<span class="pnow mut">provjeravam trenutnu cijenu…</span></li>')


def _near_html(near, note=""):
    """Why nothing is offered: the live-check failures of the best candidates, never as a buy."""
    if note:
        return f"<p><b>Danas ništa ne predlažem:</b> {esc(note)}.</p>"
    out = ["<p><b>Danas nijedan token ne prolazi sve provjere</b> (nije rug, pouzdanost 35+, svjež do 24 h, mcap 30k+ i "
           "živ promet u zadnjem satu: 10+ transakcija, $1k+ volumena, $20k+ likvidnosti, i ne pada više od 20 % u satu). Bolje ništa nego najmanje loš.</p>"]
    if near:
        out.append("<p class=why>Najbliži, ali <b>ne kupuj</b>: " + "; ".join(
            f"{_tl(p['token'], p['symbol'])} ({esc(r)})" for p, r in near[:3]) + ".</p>")
    return "".join(out)


def _base(kind, now=None, rows=None, live=None):
    """What every box shares: what was analysed in 24 h, the token picks (the Autopilot's live list first when it has
    rows), the market line and the box's own 7-day record. The picks are written to the decision log here, once per
    box (ui/prijedlog_log)."""
    now = now or time.time()
    an = analysed(now)
    try:
        from hype import tokenstatus
        status = tokenstatus.read(data.HYPE_DB)
    except Exception:  # noqa: BLE001
        status = {}
    picks, near, note = token_picks_ex(now, rows=rows, status=status, live=live)
    log_kind = kind
    if live is None:   # 9.11. (Jure): the Autopilot's live engine is the source; Pregled follows it
        try:
            from ui import zivo
            zr = zivo.rows(now, sync=True)
            if zr:
                # 9.11. (audit P50/P51): these are the live list's rows, graded 'uživo' and logged under kind 'zivo',
                # so the box's 7-day record keeps the two methods (freshness + confidence vs. live reasons) apart
                picks = [{"token": r["token"], "symbol": r.get("symbol") or (r["live"].get("symbol") if r.get("live") else None),
                          "mcap0": r["live"]["mcap"], "ts0": int(r.get("ts0") or now), "conf": r.get("conf"), "why": r["reasons"],
                          "protiv": [], "band": _band(r["live"]["mcap"]), "chance": None, "razina": "uživo", "live": r["live"],
                          "history": history(r["token"]), "thesis": "Zašto sada: " + "; ".join(r["reasons"]) + ". " + r["expect"] + "."}
                         for r in zr[:3]]
                near, note = [], ""
                log_kind = "zivo"
        except Exception:  # noqa: BLE001
            pass
    mak = _makro_line()
    rec = ""
    try:   # dnevnik odluka: write the picks down, show the box's own 7-day record (ui/prijedlog_log)
        from ui import prijedlog_log
        prijedlog_log.log(data.HYPE_DB, picks, log_kind, now)
        rec = prijedlog_log.sentence(prijedlog_log.summary(data.HYPE_DB, now=now))
    except Exception:  # noqa: BLE001
        pass
    return {"now": now, "an": an, "status": status, "picks": picks, "near": near, "note": note, "mak": mak, "rec": rec}


def box(kind, now=None, rows=None, live=None, parts=None):
    """kind: tokeni | influenceri | novcanici | pregled. HTML of the box (with the live-price script).
    10.11. (Jure, prijedlog 3.1): "pregled" is the compact variant (compact(): one answer, two rows, the full text in
    a pop-up); parts: pregled_parts(...) already computed by the caller, so Pregled reads everything once."""
    if kind == "pregled":
        return compact(parts if parts is not None else pregled_parts(now, rows, live))
    p = _base(kind, now, rows, live)
    now, an, status, picks, near, note, mak, rec = (p["now"], p["an"], p["status"], p["picks"], p["near"], p["note"],
                                                    p["mak"], p["rec"])
    head = (f"Analizirao sam u zadnja 24 h: {an.get('tokena', 0)} tokena, {an.get('poziva', 0)} poziva od "
            f"{an.get('kolova', 0)} računa, {an.get('novcanika', 0)} ocijenjenih novčanika i {an.get('tradeova', 0)} "
            "demo tradeova strategija.")
    b = [CSS, f'<div class="pdj" id="pdj" data-kind="{esc(kind)}" data-ts="{int(now)}"><h2>Prijedlog za danas '
         f'<small class=mut style="font-weight:400;font-size:12px" id=pdj-age>osvježeno upravo sada</small></h2>',
         f"<p class=an>{esc(head)}" + (f" Tržište: {esc(mak)}" if mak else "") + (f" {esc(rec)}" if rec else "") + "</p>"]
    if kind == "tokeni":
        if picks:
            b.append("<p>Ako želiš zaraditi danas, ovo bih ušao sada; svaki je prošao sve provjere i trguje se upravo sada "
                     "(uživo = živa lista <a href=/pravi-trade#ideje>Autopilota</a> sa svježim razlogom, visoka = svjež do 6 h, "
                     "srednja = do 24 h):</p><ol>"
                     + "".join(_item(p, status) for p in picks) + "</ol>")
            b.append("<p class=why>Pravilo: cijena ispod označava je li token još u zoni ulaza. Ako je otišao više od 25 % "
                     "od analize, ne juri ga; pričekaj povlačenje ili sljedeći prijedlog. Izlaz: pola na +15 %, ostatak "
                     "s pratećim stopom 15 %, stop −25 %.</p>")
        else:
            b.append(_near_html(near, note))
    elif kind == "influenceri":
        ks = kol_picks(now)
        if ks:
            b.append("<p>Koga danas slušati (dokazani prvi; „na probi” = dobar početak, još premalo izmjerenih poziva):</p><ol>")
            for k in ks:
                l = k["last"]
                lt = (f" Zadnji poziv: {_tl(l['token'], l.get('symbol'))}" + (f" na {usd(l['mcap0'])[0]}" if l.get("mcap0") else "") + " "
                      f"prije {max(0, (now - (l['ts'] or now)) / 3600):.1f} h." if l else " Bez poziva u zadnje vrijeme.")
                b.append(f'<li><b><a href="/kol/{esc(k["handle"])}">@{esc(k["handle"])}</a></b>'
                         + (' <span class="b warn">na probi</span>' if k.get("trial") else ' <span class="b good">dokazan</span>')
                         + f' · moć poziva {k["score"]:.0f}, pogodak {(k["hit"] or 0):.0%} na {k["measured"]} poziva.{lt}'
                         + f'<span class=why><br>{esc(kol_thesis(k))}'
                         + (' Ulaz ima smisla samo ako je token još blizu cijene poziva; provjeri ispod.' if l and k["fresh"] else "")
                         + '</span></li>')
            b.append("</ol>")
        else:
            b.append("<p>Danas <b>nema dokazanog influencera sa svježim pozivom</b>; ne ulazim na poziv samo zato što je "
                     "poznat račun. Ljestvica ispod pokazuje tko je blizu probe.</p>")
        if picks:
            b.append("<p>Tokeni koje bih uzeo sada (iz svih izvora):</p><ol>" + "".join(_item(p, status) for p in picks[:2]) + "</ol>")
    elif kind == "novcanici":
        ws = wallet_picks(now)
        if ws:
            b.append("<p>Koga danas kopirati (visoka/srednja = prošao uvjete kopiranja, niska = najbolji dostupni, još ispod praga, mali ulog):</p><ol>")
            for w in ws:
                s = w["stats"]
                l = w["last"]
                b.append(f'<li><b>{wlink(w["wallet"])}</b> · pouzdanost {esc(w["tier"])}, {s.get("closed", 0)} zatvorenih, '
                         f'{(s.get("win_rate") or 0):.0%} dobitnih, {(s.get("closed_pnl_sol") or 0):+.1f} SOL ukupno.'
                         + (f" Zadnja kupnja: {_tl(l['mint'])} prije "
                            f"{max(0, (now - (l['ts'] or now)) / 3600):.1f} h." if l else "")
                         + f'<span class=why><br>{esc(wallet_thesis(w))}</span></li>')
            b.append("</ol><p class=why>Ulog 20–50 $ po tradeu, najviše 3 otvorene, izlazi po pravilima bota.</p>")
        else:
            b.append("<p>Još <b>nijedan novčanik nema ni 3 zatvorena tradea u plusu</b>; čim ga ima, piše ovdje s razinom "
                     "vjerojatnosti. Tablice ispod su za one koji žele kopati sami.</p>")
        if picks:
            b.append("<p>Tokeni koje bih uzeo sada:</p><ol>" + "".join(_item(p, status) for p in picks[:2]) + "</ol>")
    b.append("</div>" + JS)
    return "".join(b)


# ---------- Pregled: the compact box (10.11., Jure: "Ostalo mi se sviđa"; prijedlog 3.1) ----------------------------
# The box used to open Pregled with four lines of intro, three tokens with ~50-word theses, a wallet, a crew and an
# exit paragraph (5,1 screens on a phone, one token visible). Now: one answer ("Najbolji ulaz sada"), the other picks
# as rows, one line of the exit rule; the whole old text is one tap away in a pop-up (full_text) with the same
# live zone check. Nothing is computed that the old box did not compute.

STAKE = {"uživo": "25 $", "visoka": "25–50 $", "srednja": "20–25 $", "niska": "10 $ ili samo gledaj"}
EXIT_LINE = "Izlaz: pola na +15\u00a0%, ostatak s pratećim stopom 15\u00a0%, stop −25\u00a0%."


def pregled_parts(now=None, rows=None, live=None):
    """Everything the Pregled box shows, read once per build (Pregled also uses the wallet pick for "Vrijedi pratiti"):
    _base(...) plus wallets (wallet_picks n=1), crew (group_pick) and chances. A part that fails is empty."""
    p = _base("pregled", now, rows, live)
    for key, fn in (("wallets", lambda: wallet_picks(p["now"], n=1)), ("crew", group_pick), ("chances", chances)):
        try:
            p[key] = fn()
        except Exception:  # noqa: BLE001 - the box works without any of them
            p[key] = [] if key == "wallets" else {} if key == "chances" else None
    return p


_SMART = re.compile(r"^(\d+) provjerenih smart walleta je među prvim kupcima\.?$")
_SMART_OK = re.compile(r"^\d+ (provjeren\w* )?smart wallet")


def smart_fix(s, short=False):
    """ui/radar writes "3 provjerenih smart walleta je među prvim kupcima" for every count: the right Croatian form
    ("1 provjereni smart wallet je", "3 provjerena smart walleta su", "5 provjerenih smart walleta je"); short=True the
    maketa's row text ("3 smart walleta među prvim kupcima"). Any other text comes back as it was."""
    from ui.pocetna import plural
    m = _SMART.match(s or "")
    if not m:
        return s
    n = int(m.group(1))
    if short:
        return f"{n} smart {plural(n, 'wallet', 'walleta', 'walleta')} među prvim kupcima"
    return (f"{n} {plural(n, 'provjereni smart wallet je', 'provjerena smart walleta su', 'provjerenih smart walleta je')}"
            " među prvim kupcima" + ("." if s.endswith(".") else ""))


def _why1(p, short=False):
    """One sentence why: the first measured reason (radar reasons or the live list's), not the whole thesis.
    short=True for a row (one line, 15 px, the maketa's "3 smart walleta među prvim kupcima"): the part before ":"
    ("Novac ulazi brzo"); the number of smart wallets in the right Croatian form either way (ui/radar writes
    "3 provjerenih ... je" for every count)."""
    za = [w for w in (p.get("why") or []) if w]
    s = smart_fix((za[0] if za else "ocjena alata i Šansa iznad praga").strip().rstrip("."), short)
    if short and not _SMART_OK.match(s) and ":" in s and 2 <= len(s.split(":", 1)[0].split()) <= 5:
        s = s.split(":", 1)[0]
    s = s[:1].upper() + s[1:]
    return s if short else s + "."


def _facts(p):
    """"pouzdanost 94 · 412k $ · 1 h +18 %" (the live list's rows may have no confidence: then where they come from)."""
    from ui import redak as R
    lv = p.get("live") or {}
    head = f"pouzdanost {p['conf']:.0f}" if p.get("conf") is not None else "živa lista Autopilota"
    out = R.cat(head, " · ", R.usd(p.get("mcap0")))
    if lv.get("ch_h1") is not None:
        t = R.tone(lv["ch_h1"])
        out = R.cat(out, " · 1 h ", R.raw(f'<span class="{t}">' if t else "<span>"), R.pct(lv["ch_h1"]), R.raw("</span>"))
    return out


def _pdata(p, z):
    """data-* the live zone check reads: the token, the market cap at analysis and which text to write."""
    return f'data-p="{esc(p["token"])}" data-m0="{float(p.get("mcap0") or 0):.0f}" data-z="{z}"'


def _tok_href(token):
    from urllib.parse import quote
    return f"/token/{quote(token)}"


def _full_item(p):
    """One pick in the pop-up: the old box's line and its whole thesis, without badges or emojis."""
    from ui import redak as R
    raz = p.get("razina") or "visoka"
    grade = "živa lista Autopilota" if raz == "uživo" else f"svježina {raz}"
    conf = f' · pouzdanost {p["conf"]:.0f}' if p.get("conf") is not None else ""
    text = p.get("thesis") or ("Zašto: " + ("; ".join(p.get("why") or []) or "ocjena alata i Šansa") + ".")
    chance = f" {_chance_txt(p['chance'])}." if raz != "uživo" else ""
    return (f'<li {_pdata(p, "full")}><b>{_tl(p["token"], p["symbol"])}</b> · {esc(grade)} · ulog {esc(STAKE.get(raz, "20–25 $"))}'
            f' · na {esc(R.usd(p.get("mcap0")))} kod analize{esc(conf)}<span class=why><br>{esc(text)}{esc(chance)}</span>'
            '<span class=pnow>provjeravam trenutnu cijenu</span></li>')


def full_text(p):
    """The whole old Pregled box (what was analysed, every pick with its thesis, the wallet, the crew, expectation and
    exit), for the pop-up behind "Cijeli prijedlog za danas". HTML."""
    from ui import redak as R
    an, picks = p.get("an") or {}, p.get("picks") or []
    head = (f"Analizirao sam u zadnja 24 h: {an.get('tokena', 0)} tokena, {an.get('poziva', 0)} poziva od "
            f"{an.get('kolova', 0)} računa, {an.get('novcanika', 0)} ocijenjenih novčanika i {an.get('tradeova', 0)} "
            "demo tradeova strategija.")
    b = [f"<p class=why>{esc(head)}" + (f" Tržište: {esc(p['mak'])}" if p.get("mak") else "")
         + (f" {esc(p['rec'])}" if p.get("rec") else "") + "</p>"]
    if picks:
        b.append("<h3>Tokeni</h3><p>U ovom trenutku bih uložio u ove tokene (demo, ulog po tokenu piše uz svaki; živa "
                 "lista = Autopilot ga vidi sa svježim razlogom, svježina visoka = signal do 6 h, srednja = do 24 h). Ako "
                 f"je token otišao više od {round((PULL_X - 1) * 100)} % iznad cijene analize, ne juri ga; pričekaj "
                 "povlačenje ili sljedeći prijedlog.</p><ol>" + "".join(_full_item(x) for x in picks) + "</ol>")
    else:
        b.append("<h3>Tokeni</h3>" + _near_html(p.get("near") or [], p.get("note") or ""))
    ws = p.get("wallets") or []
    b.append("<h3>Novčanik</h3>")
    if ws:
        w, st_ = ws[0], ws[0]["stats"]
        b.append(f"<p>Pratio bih novčanik {wlink(w['wallet'])} (pouzdanost {esc(w['tier'])}, {st_.get('closed', 0)} "
                 f"zatvorenih, {esc(R.pct(st_.get('win_rate') or 0, sign=False, frac=True))} dobitnih) i kopirao njegove kupnje unutar 2 minute, "
                 f"20–50 $ po tradeu. {esc(wallet_thesis(w))}</p>")
    else:
        b.append("<p>Još nijedan novčanik nema ni 3 zatvorena tradea u plusu; čim ga ima, piše ovdje.</p>")
    g = p.get("crew")
    if g:
        mem = ", ".join(f'<a href="/kol/{esc(h)}">@{esc(h)}</a>' for h in g["members"])
        b.append(f"<h3>Ekipa</h3><p>Čekao bih da ova ekipa objavi token: {mem}. Kad su zvali zajedno ({g['n']} puta), "
                 f"token se udvostručio u {esc(R.pct(g['hit'], sign=False, frac=True))} slučajeva, rug "
                 f"{esc(R.pct(g['rug'] or 0, sign=False, frac=True))} (stara mjera: najviši "
                 f"fitilj u 24 h, na {g['n']} zajednička poziva; što su stvarno dali +5–30 % prije stopa po minutama "
                 "piše na <a href=/ekipe>/ekipe</a>). Ulaz čim objave, ako je token ispod 1 M $ i još nije +25 % od "
                 "poziva: na Autopilotu upiši račune odvojene zarezom.</p>")
    ch = p.get("chances") or {}
    mid = ch.get("100–300k") or ch.get("300k–1M")
    b.append("<h3>Očekivanje i izlaz</h3><p>"
             + (f"U zadnja 2 tjedna {esc(R.pct(mid[0], sign=False, frac=True))} sličnih tokena (100k–1M) napravilo je "
                f"+30 % u 24 h ({esc(R.num(mid[1]))} poziva). " if mid else "")
             + "Ciljam +15 % na pola pozicije, ostatak vodim s pratećim stopom 15 %, stop −25 %; kod tokena 1 M+ "
             "ljestvica +15 %/+30 % i stop −20 %. Ako BTC pada, stop se širi na −50 % i držim do oporavka.</p>")
    return "".join(b)


def dialog(did, title, body_html):
    """A calm pop-up (ms- look): title, "Zatvori", the body. Opened by any element with data-dlg="<did>" (DLG_JS)."""
    return (f'<dialog id="{esc(did)}" class=ms-dlg aria-label="{esc(title)}"><div class=ms-dlg-bar><b>{esc(title)}</b>'
            f'<button type=button data-close>Zatvori</button></div><div class=ms-dlg-body>{body_html}</div></dialog>')


# 10.11. (pregled): the pop-up and its opener; window.__msdlg so a second copy on the page binds nothing twice
DLG_CSS = ("<style>dialog.ms-dlg{max-width:640px;width:calc(100% - 24px);max-height:86vh;border:1px solid var(--line);"
           "border-radius:22px;background:var(--bg);color:var(--fg);padding:0;box-shadow:0 40px 80px -30px rgba(11,18,32,.35)}"
           "dialog.ms-dlg::backdrop{background:rgba(11,18,32,.45)}"
           ".ms-dlg-bar{position:sticky;top:0;z-index:1;display:flex;justify-content:space-between;align-items:center;gap:12px;"
           "padding:14px 18px 12px;background:var(--bg);border-bottom:1px solid var(--line)}.ms-dlg-bar b{font-size:17px;font-weight:600}"
           ".ms-dlg-bar button{font:inherit;font-size:15px;color:var(--acc);background:none;border:0;padding:4px 0;cursor:pointer}"
           ".ms-dlg-body{padding:2px 18px 20px;font-size:15px;line-height:1.45}.ms-dlg-body h3{font-size:17px;font-weight:600;margin:20px 0 4px}"
           ".ms-dlg-body p{margin:8px 0}.ms-dlg-body ol{margin:6px 0;padding-left:20px}.ms-dlg-body li{margin:0 0 12px}"
           ".ms-dlg-body .why{color:var(--mut)}.ms-dlg-body .pnow{display:block;color:var(--mut)}.ms-dlg-body .pnow.warn{color:var(--warn)}"
           ".ms-dlg-body a:not(.ms-row){color:var(--acc)}.ms-dlg-body .ms-list{margin-top:4px}"
           ".ms-dlg-body .ms-row .ms-t{white-space:normal}</style>")
DLG_JS = ("<script>(()=>{if(window.__msdlg)return;window.__msdlg=1;document.addEventListener('click',e=>{"
          "const o=e.target.closest('[data-dlg]');if(o){const d=document.getElementById(o.dataset.dlg);"
          "if(d&&d.showModal){e.preventDefault();d.showModal();d.scrollTop=0}return}"
          "if(e.target.matches&&e.target.matches('dialog.ms-dlg'))e.target.close();"
          "const c=e.target.closest('dialog.ms-dlg [data-close]');if(c)c.closest('dialog').close()})})()</script>")

COMPACT_CSS = ("<style>.pdj-c .pnow.warn{color:var(--warn)}.pdj-rows{margin-top:6px}.pdj-r .pnow{color:var(--warn)}"
               ".pdj-r.out .pwhy{display:none}.pdj-c .ms-hint a{color:var(--acc);text-decoration:none;white-space:nowrap}</style>")

# the live zone check of the compact box: the same rule as the other boxes (PULL_X / DROP_X of the analysed market
# cap), words instead of emojis; rows say something only when the token left the zone
COMPACT_JS = r"""
<script>(()=>{let b=document.getElementById('pdj');if(!b)return;
async function reload(){if(document.hidden||b.querySelector('dialog[open]'))return;
 try{const r=await fetch('/api/prijedlog?box='+encodeURIComponent(b.dataset.kind),{cache:'no-store'});if(!r.ok)return;
 const t=document.createElement('div');t.innerHTML=await r.text();const nb=t.querySelector('#pdj');if(!nb)return;b.replaceWith(nb);b=nb;prices()}catch(e){}}
setInterval(reload,60000);
const N=' ',fmt=v=>v>=1e6?(v/1e6).toFixed(1).replace('.',',')+'M'+N+'$':v>=1e4?Math.round(v/1e3)+'k'+N+'$':v>=1e3?(v/1e3).toFixed(1).replace('.',',')+'k'+N+'$':Math.round(v)+N+'$';
function zone(x){return x>=__PULL__?['pričekaj povlačenje, ne juri',1]:x<=__DROP__?['pada, ne ulazi dok se ne okrene',1]:['još je u zoni ulaza',0]}
async function prices(){const items=[...b.querySelectorAll('[data-p]')];if(!items.length)return;
 try{const q=[...new Set(items.map(e=>e.dataset.p))].join(',');const r=await fetch('/api/prijedlog?t='+q,{cache:'no-store'});if(!r.ok)return;const j=await r.json();
 items.forEach(e=>{const s=e.querySelector('.pnow');if(!s)return;const m=j[e.dataset.p],z=e.dataset.z;
  if(!m||!m.mcap){if(z!=='row')s.textContent='cijena trenutno nedostupna';return}
  const x=m.mcap/(+e.dataset.m0||m.mcap),[t,out]=zone(x),d=Math.round((x-1)*100),dd=(d>0?'+':d<0?'−':'')+Math.abs(d)+N+'%';
  s.textContent=z==='full'?'sada '+fmt(m.mcap)+' ('+dd+' od analize): '+t:z==='row'?(out?t+' ('+dd+')':''):(out?t+' ('+dd+' od analize)':t);
  s.classList.toggle('warn',!!out);e.classList.toggle('out',!!out)})}catch(e){}}
prices();setInterval(()=>{if(!document.hidden)prices()},60000)})()</script>""".replace("__PULL__", str(PULL_X)).replace("__DROP__", str(DROP_X))


def compact(p):
    """The Pregled box: hero "Najbolji ulaz sada" (tap: the token page), the other picks as rows, one line of the exit
    rule with "Cijeli prijedlog za danas" (pop-up with full_text). With no pick: "Danas ništa" and the nearest tokens
    as grey rows that say why not. id=pdj, data-kind=pregled: the minute reload and /api/prijedlog?box=pregled
    keep working. HTML (the script last, as api() expects)."""
    from ui import redak as R
    picks = p.get("picks") or []
    out = [COMPACT_CSS, DLG_CSS, f'<div class=pdj-c id=pdj data-kind=pregled data-ts="{int(p.get("now") or time.time())}">']
    if picks:
        t = picks[0]
        stake = STAKE.get(t.get("razina") or "visoka", "20–25 $")
        foot = R.cat(R.raw("<span>"), f"Ulog u demu {stake} · ", R.raw('<span class=pnow>provjeravam cijenu</span></span>'))
        out.append(f'<div class=pdj-h {_pdata(t, "hero")}>'
                   + R.hero(t.get("symbol") or R.raw(f"<code>{esc(short_addr(t['token']))}</code>"), why=_why1(t),
                            label="Najbolji ulaz sada", facts=_facts(t), href=_tok_href(t["token"]), foot=foot) + "</div>")
        lis = []
        for x in picks[1:3]:
            reason = R.cat(R.raw("<span class=pwhy>"), _why1(x, short=True), R.raw("</span><span class=pnow></span>"))
            conf = f"{x['conf']:.0f}" if x.get("conf") is not None else None
            lis.append(f'<li class=pdj-r {_pdata(x, "row")}>'
                       + R.row(x.get("symbol") or short_addr(x["token"]), reason=reason, value=conf or R.usd(x.get("mcap0")),
                               sub=R.usd(x.get("mcap0")) if conf else None, href=_tok_href(x["token"]),
                               title="pouzdanost i market cap kod analize") + "</li>")
        if lis:
            out.append('<ul class="ms-list pdj-rows">' + "".join(lis) + "</ul>")
    else:
        note, near = p.get("note") or "", p.get("near") or []
        why = (note[:1].upper() + note[1:] + "." if note else
               "Nijedan token ne prolazi sve provjere (nije rug, pouzdanost barem 35, mcap barem 30k $ i živ promet u "
               "zadnjem satu). Bolje ništa nego najmanje loš.")
        out.append(R.hero("Danas ništa", why=why, label="Najbolji ulaz sada"))
        out.append(R.rows([R.row(x.get("symbol") or short_addr(x["token"]), reason=f"ne kupuj: {r}", reason_tone="warn",
                                 href=_tok_href(x["token"]), muted=True) for x, r in near[:2]], cls="pdj-rows"))
    link = '<a href="#pdj-full" data-dlg="pdj-full">Cijeli prijedlog za danas</a>'
    out.append(f'<p class="ms-hint">{esc(EXIT_LINE) if picks else ""}{" " if picks else ""}{link}</p>')
    out.append(dialog("pdj-full", "Prijedlog za danas", full_text(p)))
    out.append("</div>" + DLG_JS + COMPACT_JS)
    return "".join(out)


def short_addr(a):
    from ui.html import short
    return short(a or "")


def api(qs):
    """/api/prijedlog?t=mint,mint → {mint: {mcap, price}} live from DexScreener (the page polls every minute);
    ?box=tokeni|influenceri|novcanici|pregled → the whole box rebuilt now (HTML, no script)."""
    kind = qs.get("box")
    if kind in ("tokeni", "influenceri", "novcanici", "pregled"):
        html = box(kind)
        return html.split("<script>")[0]
    toks = [t for t in (qs.get("t") or "").split(",") if t][:12]
    if not toks:
        return "{}"
    try:
        from koltest import run as kt
        mk = kt.market(set(toks)) or {}
    except Exception:  # noqa: BLE001
        mk = {}
    return json.dumps({t: ({"mcap": mk[t][2], "price": mk[t][0]} if t in mk else None) for t in toks})
