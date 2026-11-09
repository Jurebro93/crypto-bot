"""The "Prijedlog za danas" box on top of Tokeni, Influenceri and Novčanici (Jure 7.11.): the first thing a user
sees is what the tool concluded from everything it analysed and, concretely, where to put money today and why.
The tables come after. Each pick carries the market cap at the moment of the analysis; the page asks
/api/prijedlog every minute for the live market cap and says "OK" / "pričekaj povlačenje" (the user may read the
page minutes later, when a $50k entry is already $70k)."""
import json
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


def chances(days=14):
    """{band: (share of calls with max24 >= TARGET, n)} from kol.db measured calls (the retro of 7.11.)."""
    out = {}
    try:
        rows = data.q(_kol_db(), "SELECT mcap0, max24 FROM calls WHERE max24 IS NOT NULL AND kind IN ('call','bot') "
                                   "AND ts >= ? AND source NOT IN ('kol_win')", (int(time.time() - days * 86400),))
    except Exception:  # noqa: BLE001
        rows = []
    by = {}
    for r in rows:
        by.setdefault(_band(r["mcap0"]), []).append(r["max24"] or 0)
    for b, xs in by.items():
        if len(xs) >= 30:
            out[b] = (sum(1 for x in xs if x >= TARGET) / len(xs), len(xs))
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
        pairs = (fetch or (lambda t: client.tokens("solana", t)))(tokens)
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
                  "ch_h1": ch.get("h1"), "ch_h24": ch.get("h24")}
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
        mp = data.q(kp, "SELECT t10, sl_min FROM call_path WHERE token = ? AND entry IS NOT NULL AND bad IS NULL", (token,))
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
    parts = ["Teza: " + (za[0].rstrip(".") if za else "ocjena alata i Šansa iznad praga") + "."]
    if lv:
        turn = lv["vol_h1"] / lv["liq"] if lv.get("liq") else 0
        ch1 = f"{lv['ch_h1']:+.0f} %" if lv.get("ch_h1") is not None else "?"
        ch24 = f"{lv['ch_h24']:+.0f} %" if lv.get("ch_h24") is not None else "?"
        parts.append(f"Uživo: {lv['txns_h1']} transakcija i ${lv['vol_h1']:,.0f} volumena u zadnjem satu ({turn:.1f}× likvidnosti), "
                     f"cijena 1 h {ch1}, 24 h {ch24}.")
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
    for razina, ok in (("visoka", lambda r: overview.relevant(r) and now - (r["last_seen"] or 0) <= MAX_AGE_S),
                       ("srednja", lambda r: overview.relevant(r) and now - (r["last_seen"] or 0) <= 24 * 3600)):
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
        if rv and rv not in ("PROŠAO", "OK") and f"rug filter: {rv}" not in protiv:
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
    try:   # 9.11.: the minute check (kol/minute.py) is the honest measure; the leaderboard's hit is a 24-h wick
        from kol import minute, store as kstore
        kc = kstore.ro(_kol_db())
        if kc is not None:
            try:
                minute_stats = dict(minute.handle_stats(kc, 14, int(now), min_n=1))
            finally:
                kc.close()
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


def group_pick():
    """The best crew of KOLs that call together (kol/together): follow them, enter when they post."""
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
    good = [c for c in tog.get("clusters") or [] if c["stats"]["n"] >= 3 and (c["stats"]["hit"] or 0) >= 0.5
            and (c["stats"]["rug"] or 0) < 0.4 and not c.get("shill")]
    if not good:
        return None
    c = good[0]
    return {"members": c["members"][:5], "n": c["stats"]["n"], "hit": c["stats"]["hit"], "rug": c["stats"]["rug"],
            "tokens": c["tokens"]}


def _chance_txt(c):
    if not c:
        return "povijest još nema dovoljno sličnih poziva"
    return f"{c[0]:.0%} sličnih tokena (po market capu) napravilo je +30 % u 24 h ({c[1]} izmjerenih poziva)"


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
    cls = {"visoka": "good", "srednja": "warn", "niska": "bad"}[raz]
    stake = {"visoka": "25–50 $", "srednja": "20–25 $", "niska": "10 $ ili samo gledaj"}[raz]
    text = p.get("thesis") or ("Zašto: " + ("; ".join(p["why"]) or "ocjena alata i Šansa") + ".")
    return (f'<li data-p="{esc(p["token"])}" data-m0="{p["mcap0"]:.0f}"><b>{_tl(p["token"], p["symbol"])}</b> '
            f'<span class="b {cls}">vjerojatnost {raz}</span> ulog {stake} · '
            f'na <b>{usd(p["mcap0"])[0]}</b> sada · pouzdanost {p["conf"] or 0:.0f}'
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


def box(kind, now=None, rows=None, live=None):
    """kind: tokeni | influenceri | novcanici. HTML of the box (with the live-price script)."""
    now = now or time.time()
    an = analysed(now)
    try:
        from hype import tokenstatus
        status = tokenstatus.read(data.HYPE_DB)
    except Exception:  # noqa: BLE001
        status = {}
    picks, near, note = token_picks_ex(now, rows=rows, status=status, live=live)
    mak = _makro_line()
    rec = ""
    try:   # dnevnik odluka: write the picks down, show the box's own 7-day record (ui/prijedlog_log)
        from ui import prijedlog_log
        prijedlog_log.log(data.HYPE_DB, picks, kind, now)
        rec = prijedlog_log.sentence(prijedlog_log.summary(data.HYPE_DB, now=now))
    except Exception:  # noqa: BLE001
        pass
    head = (f"Analizirao sam u zadnja 24 h: {an.get('tokena', 0)} tokena, {an.get('poziva', 0)} poziva od "
            f"{an.get('kolova', 0)} računa, {an.get('novcanika', 0)} ocijenjenih novčanika i {an.get('tradeova', 0)} "
            "demo tradeova strategija.")
    b = [CSS, f'<div class="pdj" id="pdj" data-kind="{esc(kind)}" data-ts="{int(now)}"><h2>Prijedlog za danas '
         f'<small class=mut style="font-weight:400;font-size:12px" id=pdj-age>osvježeno upravo sada</small></h2>',
         f"<p class=an>{esc(head)}" + (f" Tržište: {esc(mak)}" if mak else "") + (f" {esc(rec)}" if rec else "") + "</p>"]
    if kind == "tokeni":
        if picks:
            b.append("<p>Ako želiš zaraditi danas, ovo bih ušao sada; svaki je prošao sve provjere i trguje se upravo sada "
                     "(visoka = svjež do 6 h, srednja = do 24 h):</p><ol>"
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
    elif kind == "pregled":
        parts = []
        if picks:
            parts.append("<p><b>U ovom trenutku bih uložio</b> u ove tokene (demo 25–50 $ po tokenu):</p><ol>"
                         + "".join(_item(p, status) for p in picks) + "</ol>")
        else:
            parts.append(_near_html(near, note))
        ws = wallet_picks(now, n=1)
        if ws:
            w, st_ = ws[0], ws[0]["stats"]
            parts.append(f"<p><b>Pratio bih novčanik</b> {wlink(w['wallet'])} (pouzdanost {esc(w['tier'])}, "
                         f"{st_.get('closed', 0)} zatvorenih, {(st_.get('win_rate') or 0):.0%} dobitnih) i kopirao njegove kupnje "
                         "unutar 2 minute, 20–50 $ po tradeu.</p>")
        else:
            parts.append("<p><b>Novčanici:</b> još nijedan nema ni 3 zatvorena tradea u plusu; čim ga ima, piše ovdje.</p>")
        g = group_pick()
        if g:
            mem = ", ".join(f'<a href="/kol/{esc(h)}">@{esc(h)}</a>' for h in g["members"])
            parts.append(f"<p><b>Čekao bih da ova ekipa objavi token</b>: {mem}. Kad su zvali zajedno ({g['n']} puta), "
                         f"token se udvostručio u {g['hit']:.0%} slučajeva, rug {(g['rug'] or 0):.0%} (stara mjera: najviši "
                         f"fitilj u 24 h, na {g['n']} zajednička poziva; što su stvarno dali +5–30 % prije stopa po minutama "
                         "piše na <a href=/ekipe>/ekipe</a>). Ulaz čim objave, ako je token ispod 1 M $ i još nije +25 % od "
                         "poziva: na Autopilotu upiši račune odvojene zarezom.</p>")
        ch = chances()
        mid = ch.get("100–300k") or ch.get("300k–1M")
        parts.append("<p><b>Očekivanje i izlaz:</b> "
                     + (f"u zadnja 2 tjedna {mid[0]:.0%} sličnih tokena (100k–1M) napravilo je +30 % u 24 h ({mid[1]} poziva); "
                        if mid else "")
                     + "ciljam +15 % na pola pozicije, ostatak vodim s pratećim stopom 15 %, stop −25 %; kod tokena 1 M+ "
                     "ljestvica +15 %/+30 % i stop −20 %. Ako BTC pada, stop se širi na −50 % i držim do oporavka.</p>")
        b += parts
    b.append("</div>" + JS)
    return "".join(b)


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
