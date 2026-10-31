"""The "Pregled" page: standout candidates (pop-up with evidence), how the data grows, tokens that passed several
analyses, and wallets that buy the same tokens (clusters, drawn as a graph)."""
import json
import time

from ui import confidence, data, evidence, explain, paper, sansa
from ui.html import tdesc, ago, badge, esc, klasab, modal, num, razinab, scorecell, short, table, tierb, tlink, usd, wlink

GOOD_ROLES = ("early_buyer", "smart", "top_trader", "holder", "manual")


def _iso_ts(s):
    try:
        import datetime as dt
        return int(dt.datetime.fromisoformat(s).timestamp())
    except (TypeError, ValueError):
        return None


# ---------- token layers ----------

def token_rows(since=None):
    """One row per token with its latest signal, details, rug report, events and paper decision."""
    from rugfilter import collapse
    sigs, pk = {}, {}
    day = time.time() - collapse.WINDOW_H * 3600
    for s in data.hype_signals(limit=50000):
        if s["ts"] >= day:
            collapse.add(pk, s["token"], s["ts"], s["mcap"], s["liquidity"])
        r = sigs.setdefault(s["token"], {"last": s, "first_ts": s["ts"], "max": 0})
        r["first_ts"] = min(r["first_ts"], s["ts"])
        r["max"] = max(r["max"], s["score"] or 0)
        if s["ts"] > r["last"]["ts"]:
            r["last"] = s
    dets = {}
    for d in data.q(data.HYPE_DB, "SELECT token, ts, extra FROM hype_details ORDER BY ts DESC"):
        dets.setdefault(d["token"], data.js(d["extra"], {}) or {})
    rugs = {}
    for r in data.rug_reports():
        rugs.setdefault(r["mint"], r)
    evs = {}
    for e in data.event_tokens():
        evs.setdefault(e["token"], []).append(e)
    cands = {}
    for c in data.paper_candidates():
        cands.setdefault(c["token"], c)
    tiers = data.token_tiers()
    out = []
    for t in set(sigs) | set(rugs) | set(evs) | set(cands):
        s = sigs.get(t)
        last_seen = max([s["last"]["ts"] if s else 0, rugs[t]["checked_at"] if t in rugs else 0,
                         cands[t]["first_ts"] if t in cands else 0]
                        + [_iso_ts(e["seen_at"]) or 0 for e in evs.get(t, [])])
        if since and last_seen < since:
            continue
        cs = evidence.checks(t, s["last"] if s else None, dets.get(t), rugs.get(t), evs.get(t), cands.get(t))
        sym = (s["last"]["symbol"] if s else None) or (rugs[t]["symbol"] if t in rugs else None) or \
            (evs[t][0]["symbol"] if t in evs else None) or (cands[t]["symbol"] if t in cands else None)
        mcap = (s["last"]["mcap"] if s else None) or ((rugs[t]["data"].get("market") or {}).get("mcap") if t in rugs else None)
        passed = sum(1 for _, ok, _ in cs if ok)
        failed = sum(1 for _, ok, _ in cs if ok is False)
        hard = t in rugs and rugs[t]["verdict"] == "ODBAČEN"
        liq = (s["last"]["liquidity"] if s else None) or ((rugs[t]["data"].get("market") or {}).get("liquidity") if t in rugs else None) \
            or (evs[t][0]["liquidity"] if t in evs else None)
        role = "canonical" if any(e["role"] == "canonical" for e in evs.get(t, [])) else ("copycat" if t in evs else None)
        conf, parts = confidence.score(s["last"]["score"] if s else None,
                                       (data.js(s["last"]["features"], {}) or {}) if s else {}, dets.get(t, {}),
                                       rugs[t]["verdict"] if t in rugs else None, role, liq, mcap)
        tier = tiers.get(t) or {}
        if tier.get("t0") == "pad":
            hard = True
        col = collapse.check(pk.get(t))  # already dumped: never a candidate, whatever the rug filter said
        if col:
            hard = True
        sn, an, _, _ = sansa.score(conf, cs)
        out.append({"token": t, "symbol": sym, "checks": cs, "passed": passed, "failed": failed, "hard": hard,
                    "tier": tier, "razina": tier.get("razina"), "klasa": tier.get("klasa"), "sansa": sn, "analysed": an,
                    "conf": conf, "conf_parts": parts, "liq": liq, "rug": rugs.get(t), "events": evs.get(t, []),
                    "cand": cands.get(t), "collapse": col, "peak": pk.get(t),
                    "hype": s["max"] if s else None, "hype_last": s["last"]["score"] if s else None,
                    "mcap": mcap, "last_seen": last_seen, "det": dets.get(t, {}),
                    "features": (data.js(s["last"]["features"], {}) or {}) if s else {}})
    return out


def _rank(r):
    """Šansa first (passed analyses weigh in), then confidence, then hype."""
    return (r["sansa"], r["conf"], r["hype"] or 0)


def _class_hint(k):
    return {"moonshot": "mcap < $150k, mlađi od 3 dana; cilj 3x", "rizican": "između; cilj 2x",
            "event": "pravi token događaja; cilj +50% do eventa", "stabilni": "mcap > $2M, stariji od 7 dana; cilj +30%"}.get(k, "")


def featured(recent, per_class=3):
    """(eligible rows by Šansa, {klasa or None: top rows}) — the one definition of "istaknuti kandidati", used by the
    Pregled page and by the scan (featured tokens are re-scored every pass, see hype.pulse.retained)."""
    from tiers.classify import KLASE
    elig = sorted([r for r in recent if sansa.featured_ok(r)], key=_rank, reverse=True)
    out = {k: [r for r in elig if r["klasa"] == k][:per_class] for k in KLASE}
    out[None] = [r for r in elig if not r["klasa"]][:per_class]
    return elig, {k: v for k, v in out.items() if v}


def featured_tokens(hours=24, per_class=3):
    """Mints currently shown as featured on Pregled, best first."""
    _, per = featured(token_rows(since=time.time() - hours * 3600), per_class)
    return [r["token"] for rows in per.values() for r in rows]


def _card(r):
    try:
        from ui.radar import reasons
        why = reasons(r["features"], r["det"])[:2]
    except Exception:
        why = []
    ok = [lab for lab, v, _ in r["checks"] if v]
    bad = [lab for lab, v, _ in r["checks"] if v is False]
    from hype import pulse
    snaga = pulse.describe(r["features"])
    return (f'<button class="cand stat" data-mint="{esc(r["token"])}" type=button>'
            f'<div style="display:flex;justify-content:space-between;gap:8px"><b style="font-size:17px">{esc(r["symbol"] or short(r["token"]))}</b>'
            f'<span title="Šansa za skok"><b style="font-size:17px">{r["sansa"]}</b> <span class=mut style="font-size:12px">šansa · conf {r["conf"]}</span></span></div>'
            f'<div style="margin:4px 0">{sansa.dots_html(r["checks"])} <span class=mut style="font-size:12px">{r["analysed"]}/{sansa.N} slojeva</span>'
            f' {razinab(r["razina"])} {klasab(r["klasa"])}'
            f' <span class=mut>{usd(r["mcap"])[0]} mcap · {ago(r["last_seen"])[0]}</span></div>'
            f'<div style="font-size:12px">{" ".join(badge("✓ " + x, "good") for x in ok)} {" ".join(badge("✗ " + x, "bad") for x in bad)}</div>'
            + (f'<div style="font-size:12px;margin-top:6px;color:var(--good)">{esc(snaga)}</div>' if snaga else "")
            + (f'<div class=mut style="font-size:12px;margin-top:6px">{esc(why[0])}</div>' if why else
               f'<div class=mut style="font-size:12px;margin-top:6px">{esc(r["conf_parts"][0][1])}</div>' if r["conf_parts"] else "")
            + "<div style='font-size:12px;margin-top:6px;color:var(--acc)'>Klikni za analizu i dokaze →</div></button>")


def sieve_html(hours=24):
    """One line on what the free T0 sieve did today and how the tokens split into classes."""
    sm = data.tier_summary(hours)
    if not sm or not any(sm["t0"].values()):
        return ""
    from tiers.classify import KLASA_HR
    t0, kl, rz = sm["t0"], sm["klasa"], sm["razina"]
    parts = [f"<b>{t0.get('prolaz', 0)}</b> prošlo T0", f"<b>{t0.get('pad', 0)}</b> palo na mehanici ruga",
             f"<b>{t0.get('nije', 0)}</b> izvan skena (premalo ili preveliko), samo praćeno"]
    deep = sum(n for r, n in rz.items() if (r or 0) >= 1)
    klase = ", ".join(f"{KLASA_HR.get(k, k)} {n}" for k, n in sorted(kl.items(), key=lambda kv: -kv[1]) if k != "?")
    return (f"<p class=mut>Slojevita analiza, zadnja {hours} h: " + " · ".join(parts)
            + f" · <b>{deep}</b> dobilo plaćenu provjeru (T1+). Klase: {esc(klase) or '–'}. "
            "Pada se samo na mehanici ruga; likvidnost i holderi su signali čiju težinu bot uči, ne pragovi.</p>")


# ---------- growth ----------

POINTS = [("sada", 0), ("1 h", 3600), ("6 h", 6 * 3600), ("24 h", 86400), ("3 d", 3 * 86400), ("7 d", 7 * 86400)]


def _first_seen():
    tok = {}

    def see(t, ts):
        if t and ts:
            tok[t] = min(tok.get(t, ts), ts)
    for r in data.multi("hype", "SELECT token, MIN(ts) ts FROM hype_signals GROUP BY token"):
        see(r["token"], r["ts"])
    for r in data.multi("rug", "SELECT mint, MIN(checked_at) ts FROM rug_reports GROUP BY mint"):
        see(r["mint"], r["ts"])
    for r in data.cal("SELECT token, MIN(seen_at) s FROM event_tokens GROUP BY token"):
        see(r["token"], _iso_ts(r["s"]))
    for r in data.multi("paper", "SELECT token, first_ts ts FROM candidates"):
        see(r["token"], r["ts"])
    wal = {r["wallet"]: r["first_seen"] for r in data.multi("wallets", "SELECT wallet, first_seen FROM wallets",
                                                           key=lambda r: r["wallet"]) if r["first_seen"]}
    scored = {r["wallet"]: r["ts"] for r in data.multi("wallets", "SELECT wallet, MIN(ts) ts FROM wallet_pnl GROUP BY wallet",
                                                      key=lambda r: r["wallet"])}
    for r in data.multi("wallets", "SELECT wallet, scored_at FROM wallets WHERE scored_at IS NOT NULL",
                        key=lambda r: r["wallet"]):
        scored.setdefault(r["wallet"], r["scored_at"])
    copy = {w["wallet"]: w.get("scored_at") or 0 for w in data.wallets() if explain.shortlist(w)[0]}
    rug = [r["checked_at"] for r in data.multi("rug", "SELECT checked_at FROM rug_reports")]
    smart = [r["updated"] for r in data.smart_wallets() if (r["score"] or 0) >= 50]
    return {"Tokena analizirano": list(tok.values()), "Walleta u registru": list(wal.values()),
            "Walleta ocijenjeno": list(scored.values()), "Smart walleta (50+)": smart,
            "Rug provjera": rug, "Na copy listi": list(copy.values())}


def _chart(series, now, days=7, step=3600):
    """Cumulative counts over the last `days`, one line per series (normalised to its own max)."""
    colors = ["var(--bar)", "#e8590c", "#2b8a3e", "#ae3ec9"]
    W, H = 640, 150
    t0 = now - days * 86400
    lines, legend = [], []
    for i, (name, tss) in enumerate(list(series.items())[:4]):
        tss = sorted(t for t in tss if t)
        pts, j = [], 0
        for k in range(days * 86400 // step + 1):
            t = t0 + k * step
            while j < len(tss) and tss[j] <= t:
                j += 1
            pts.append(j)
        mx = max(pts) or 1
        path = " ".join(f"{W * k / (len(pts) - 1):.1f},{H - 4 - (H - 8) * v / mx:.1f}" for k, v in enumerate(pts))
        lines.append(f'<polyline points="{path}" fill=none stroke="{colors[i]}" stroke-width=2 vector-effect=non-scaling-stroke />')
        legend.append(f'<span style="color:{colors[i]}">■</span> {esc(name)} ({pts[0]} → {pts[-1]})')
    ticks = "".join(f'<line x1="{W * d / days:.1f}" x2="{W * d / days:.1f}" y1=0 y2={H} stroke="currentColor" stroke-opacity=.08 />'
                    for d in range(1, days))
    return (f'<div class=card><svg viewBox="0 0 {W} {H}" width="100%" height="{H}" preserveAspectRatio=none>{ticks}{"".join(lines)}</svg>'
            f'<div style="display:flex;justify-content:space-between" class=mut><span>prije {days} d</span><span>sada</span></div>'
            f'<div style="font-size:12px">{" · ".join(legend)}</div>'
            f'<div class=mut style="font-size:12px">Svaka linija je skalirana na svoj maksimum, pa se vidi tempo rasta, ne omjer.</div></div>')


def growth():
    now = time.time()
    series = _first_seen()
    rows = []
    for name, tss in series.items():
        cells = [esc(name)]
        cur = len(tss)
        for label, back in POINTS:
            n = sum(1 for t in tss if t and t <= now - back)
            if back == 0:
                cells.append(num(n))
            else:
                d = cur - n
                cells.append((f"{n:,} <span class={'pos' if d else 'mut'}>+{d:,}</span>", n, "n"))
        rows.append(cells)
    head = ["", ("Sada", "n")] + [(f"Prije {l}", "n") for l, _ in POINTS[1:]]
    return (tdesc('Koliko tokena, walleta, signala i rug provjera je alat imao u svakom trenutku. Pokazuje puni li se baza i koliko brzo.') + table(head, rows) + "<p class=mut>Broj u stupcu = stanje u tom trenutku; zeleno = koliko je dodano od tada.</p>"
            + _chart({k: series[k] for k in ("Tokena analizirano", "Walleta u registru", "Walleta ocijenjeno", "Rug provjera")}, now))


# ---------- wallet clusters ----------

def clusters(min_shared=3, max_wallets_per_token=80):
    """Wallets that bought the same tokens. Edge = >= min_shared common tokens; cluster = connected component."""
    bad = {w["wallet"] for w in data.wallets(scored_only=False) if set(w["labels"]) & explain.BAD_LABELS}
    holds = {}
    for r in data.multi("wallets", f"SELECT wallet, token FROM wallet_sightings WHERE role IN ({','.join('?' * len(GOOD_ROLES))})",
                        GOOD_ROLES):
        if r["token"] and r["wallet"] not in bad:
            holds.setdefault(r["wallet"], set()).add(r["token"])
    for r in data.multi("wallets", "SELECT DISTINCT wallet, mint FROM wallet_trades WHERE kind='buy'"):
        if r["wallet"] not in bad:
            holds.setdefault(r["wallet"], set()).add(r["mint"])
    by_token = {}
    for w, ts_ in holds.items():
        for t in ts_:
            by_token.setdefault(t, set()).add(w)
    pair = {}
    for t, ws in by_token.items():
        if len(ws) < 2 or len(ws) > max_wallets_per_token:  # skip stables / mega tokens everybody touched
            continue
        ws = sorted(ws)
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                pair[(ws[i], ws[j])] = pair.get((ws[i], ws[j]), 0) + 1
    edges = [(a, b, n) for (a, b), n in pair.items() if n >= min_shared]
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b_, _ in edges:
        parent[find(a)] = find(b_)
    comp = {}
    for a, b_, _ in edges:
        comp.setdefault(find(a), set()).update((a, b_))
    out = []
    for ws in comp.values():
        cnt = {}
        for w in ws:
            for t in holds[w]:
                cnt[t] = cnt.get(t, 0) + 1
        shared = sorted(((t, n) for t, n in cnt.items() if n >= 2), key=lambda x: -x[1])
        out.append({"wallets": sorted(ws), "shared": shared,
                    "edges": [(a, b_, n) for a, b_, n in edges if a in ws]})
    return sorted(out, key=lambda c: (-len(c["wallets"]), -len(c["shared"]))), len(holds)


def funding_clusters():
    """Wallets funded by the same wallet (from the rug filter's funder tracing)."""
    by = {}
    for r in data.multi("wallets", "SELECT wallet, token, extra FROM wallet_sightings WHERE role='funder'"):
        e = data.js(r["extra"], {}) or {}
        if e.get("funded"):
            by.setdefault(r["wallet"], {"funded": set(), "tokens": set()})
            by[r["wallet"]]["funded"].add(e["funded"])
            by[r["wallet"]]["tokens"].add(r["token"])
    return sorted(((f, v) for f, v in by.items() if len(v["funded"]) >= 2), key=lambda x: -len(x[1]["funded"]))


def _graph(cl, syms, reg, max_w=30, max_t=12):
    """Bipartite wallet-token graph of the biggest clusters, laid out in the browser (tiny force simulation)."""
    nodes, links, seen_t = [], [], {}
    for ci, c in enumerate(cl[:4]):
        ws = sorted(c["wallets"], key=lambda w: -((reg.get(w) or {}).get("copy_score") or 0))[:max_w]
        toks = [t for t, _ in c["shared"][:max_t]]
        for w in ws:
            r = reg.get(w) or {}
            nodes.append({"id": w, "k": "w", "c": ci, "label": short(w), "score": r.get("copy_score") or 0, "tier": r.get("tier")})
        for t in toks:
            if t not in seen_t:
                seen_t[t] = True
                nodes.append({"id": t, "k": "t", "c": ci, "label": syms.get(t) or short(t)})
        tset = set(toks)
        for w in ws:
            for t in (c.get("holds", {}).get(w) or ()):
                if t in tset:
                    links.append([w, t])
    return nodes, links


GRAPH_JS = """
(()=>{const el=document.getElementById('g');if(!el)return;const G=JSON.parse(el.dataset.g);if(!G.nodes.length)return;
const W=el.clientWidth||900,H=480,N=G.nodes,idx={},k=Math.sqrt(W*H/N.length)*.75;
N.forEach((n,i)=>{idx[n.id]=i;const a=2*Math.PI*n.c/4;n.x=W/2+Math.cos(a)*W/5+(Math.random()-.5)*80;n.y=H/2+Math.sin(a)*H/5+(Math.random()-.5)*80});
const L=G.links.map(([a,b])=>[idx[a],idx[b]]).filter(([a,b])=>a!=null&&b!=null);
let T=W/8;for(let it=0;it<300;it++){N.forEach(n=>{n.dx=0;n.dy=0});
 for(let i=0;i<N.length;i++)for(let j=i+1;j<N.length;j++){let dx=N[i].x-N[j].x,dy=N[i].y-N[j].y,d=Math.max(.01,Math.hypot(dx,dy)),f=k*k/d;dx/=d;dy/=d;N[i].dx+=dx*f;N[i].dy+=dy*f;N[j].dx-=dx*f;N[j].dy-=dy*f}
 L.forEach(([a,b])=>{let dx=N[a].x-N[b].x,dy=N[a].y-N[b].y,d=Math.max(.01,Math.hypot(dx,dy)),f=d*d/k;dx/=d;dy/=d;N[a].dx-=dx*f;N[a].dy-=dy*f;N[b].dx+=dx*f;N[b].dy+=dy*f});
 N.forEach(n=>{n.dx+=(W/2-n.x)*.02*k/10;n.dy+=(H/2-n.y)*.02*k/10;const d=Math.max(.01,Math.hypot(n.dx,n.dy)),m=Math.min(d,T);n.x=Math.max(24,Math.min(W-90,n.x+n.dx/d*m));n.y=Math.max(14,Math.min(H-14,n.y+n.dy/d*m))});
 T*=.985}
const col=['#4c6ef5','#e8590c','#2b8a3e','#ae3ec9'];let s=`<svg width="${W}" height="${H}" style="max-width:100%">`;
L.forEach(([a,b])=>s+=`<line x1="${N[a].x}" y1="${N[a].y}" x2="${N[b].x}" y2="${N[b].y}" stroke="${col[N[a].c]}" stroke-opacity=".25"/>`);
N.forEach(n=>{if(n.k=='w'){const r=4+n.score/10;s+=`<a href="/wallet/${n.id}"><circle cx="${n.x}" cy="${n.y}" r="${r}" fill="${col[n.c]}" fill-opacity=".85"><title>${n.label} · copy ${n.score} · tier ${n.tier||'-'}</title></circle></a>`}
 else s+=`<a href="https://dexscreener.com/solana/${n.id}" target=_blank><rect x="${n.x-5}" y="${n.y-5}" width=10 height=10 fill="var(--card)" stroke="currentColor"/><text x="${n.x+8}" y="${n.y+4}" font-size=11 fill="currentColor">${n.label}</text></a>`});
el.innerHTML=s+'</svg>'})();
"""






def page(qs):
    now = time.time()
    b = ["<h1>Pregled</h1>", "<h2>Demo trading: rezultat</h2>", paper.summary_html()]

    # 1. standout candidates: per class, only tokens that reached a paid tier and had enough layers analysed
    recent = token_rows(since=now - 86400)
    b.append("<h2>Istaknuti kandidati (24 h)</h2>")
    b.append("<p class=mut>Poredani po <b>Šansi za skok</b>: confidence puta koliko je od 7 neovisnih slojeva stvarno "
             "analizirano, minus 15% po palom sloju. Istaknut može biti samo token koji je stigao barem do T1, nije pao ni na "
             "čemu tvrdom i ima barem 3 analizirana sloja; točkice pokazuju slojeve (zelena prošao, crvena pao, siva nije "
             "analiziran). Klikni karticu za raspis s brojkama, izvorima i linkovima na dokaze.</p>")
    from tiers.classify import KLASA_HR, KLASE
    elig, per_class = featured(recent)
    shown = 0
    for k in KLASE:
        top = per_class.get(k, [])
        if not top:
            continue
        shown += len(top)
        b.append(f"<h3>{esc(KLASA_HR[k])} <span class=mut style='font-weight:400;font-size:13px'>{_class_hint(k)}</span></h3>")
        b.append("<div class=grid style='grid-template-columns:repeat(auto-fit,minmax(280px,1fr))'>"
                 + "".join(_card(r) for r in top) + "</div>")
    rest = per_class.get(None, [])
    if rest:
        shown += len(rest)
        b.append("<h3>Bez klase</h3><div class=grid style='grid-template-columns:repeat(auto-fit,minmax(280px,1fr))'>"
                 + "".join(_card(r) for r in rest) + "</div>")
    if not shown:
        wait = sorted(recent, key=_rank, reverse=True)[:3]
        b.append("<div class=card>Nijedan token u zadnja 24 h još ne zadovoljava uvjete za isticanje (T1+, bez tvrdog pada, 3+ "
                 "analizirana sloja). Najbliži su: " + ", ".join(tlink(r["token"], r["symbol"]) + f" (šansa {r['sansa']}, T{r['razina'] or 0}, {r['analysed']} slojeva)" for r in wait)
                 + ".</div>" if wait else "<div class=card>U zadnja 24 h nijedan modul nije zapisao token.</div>")

    b.append(sieve_html())

    # 2. growth, folded: the overview answers "what now"; how the base grows is detail
    b.append("<details style='margin-top:16px'><summary><b>Kako se baza puni</b> <span class=mut>(tokeni, walleti, provjere kroz 7 dana)</span></summary>"
             + growth() + "</details>")

    # 3. tokens through several analyses
    allrows = sorted(token_rows(), key=_rank, reverse=True)
    labels = [lab for lab, _, _ in (allrows[0]["checks"] if allrows else [])]
    mark = lambda v: (badge("✓", "good"), 2, "") if v else (badge("✗", "bad"), 0, "") if v is False else ("<span class=mut>–</span>", 1, "")  # noqa: E731
    b.append(f"<h2>Tokeni koji su prošli više analiza</h2><p class=mut>✓ prošao, ✗ pao, – nije analiziran. "
             f"Poredano po Šansi za skok. Klik na naslov stupca sortira po tom stupcu (⇅, ponovni klik obrne redoslijed), <b>ⓘ</b> uz naslov objašnjava stupac, klik na red otvara analizu. Prvih 40 od {len(allrows)}; svi su na "
             f"<a href=/tokens>Tokenima</a>.</p>")
    rows = []
    for r in allrows[:40]:
        rows.append([tlink(r["token"], r["symbol"]), (f"<b>{r['sansa']}</b>", r["sansa"], "n"), (confidence.badge_html(r["conf"]), r["conf"], "n"),
                     (razinab(r["razina"]), r["razina"] or 0, "n"), (klasab(r["klasa"]), r["klasa"] or "", ""),
                     (f"<b>{r['passed']}</b>/{r['passed'] + r['failed']}", r["passed"], "n")]
                    + [mark(ok) for _, ok, _ in r["checks"]] + [scorecell(r["hype_last"]), usd(r["mcap"]), ago(r["last_seen"])])
    b.append(tdesc('Tokeni iz zadnjih 7 dana poredani po Šansi za skok; stupci su neovisne provjere (hype, X, smart money, KOL, holderi, rug, event, demo). Klik na red otvara analizu s dokazima.') + table(["Token", ("Šansa", "n"), ("Confidence", "n"), ("Razina", "n"), "Klasa", ("Prošao", "n")] + labels + [("Hype max", "n"), ("Mcap", "n"), "Zadnje"],
                   rows, "mt", "Nema tokena.", mints=[r["token"] for r in allrows[:40]]))

    # 4. wallet clusters
    min_shared = max(2, int(qs.get("shared", 3) or 3))
    cl, n_hold = clusters(min_shared)
    reg = {w["wallet"]: w for w in data.wallets(scored_only=False)}
    syms = data.symbols()
    holds = {}
    for r in data.multi("wallets", "SELECT DISTINCT wallet, token FROM wallet_sightings"):
        holds.setdefault(r["wallet"], set()).add(r["token"])
    for r in data.multi("wallets", "SELECT DISTINCT wallet, mint FROM wallet_trades WHERE kind='buy'"):
        holds.setdefault(r["wallet"], set()).add(r["mint"])
    for c in cl:
        c["holds"] = {w: holds.get(w, set()) for w in c["wallets"]}
    b.append("<details id=kl" + (" open" if "shared" in qs else "") + " style='margin-top:16px'><summary><b>Walleti koji kupuju iste tokene</b> "
             f"<span class=mut>({len(cl)} klastera od {n_hold} walleta; klik otvara graf i tablicu)</span></summary>")
    b.append(f"<p class=mut>Od {n_hold} walleta s poznatim kupnjama (bez botova, devova, snajpera i bundlera), dva su "
             f"povezana ako dijele barem {min_shared} tokena (prag: <a href='?shared=2#kl'>2</a> · <a href='?shared=3#kl'>3</a> · "
             "<a href='?shared=4#kl'>4</a>); klaster = grupa tako povezanih walleta. Klaster može biti grupa koja "
             "trejda zajedno (jedna osoba s više walleta ili call grupa) ili samo walleti koji love iste narative.</p>")
    if cl:
        nodes, links = _graph(cl, syms, reg)
        b.append(f"<div class=card><b>Graf 4 najveća klastera</b> <span class=mut>(krug = wallet, veći = bolja copy ocjena, "
                 f"boja = klaster; kvadrat = token; klik otvara wallet ili DexScreener)</span>"
                 f"<div id=g data-g='{esc(json.dumps({'nodes': nodes, 'links': links}))}' style='min-height:460px'></div></div>")
        crow = []
        for i, c in enumerate(cl[:15], 1):
            scores = [reg[w]["copy_score"] for w in c["wallets"] if w in reg and reg[w].get("copy_score") is not None]
            best = max(c["wallets"], key=lambda w: (reg.get(w) or {}).get("copy_score") or -1)
            crow.append([num(i), num(len(c["wallets"])),
                         (", ".join(tlink(t, syms.get(t)) + f" <span class=mut>×{n}</span>" for t, n in c["shared"][:6]), "", "wrap"),
                         num(len(c["shared"])), num(sum(scores) / len(scores) if scores else None, "{:.0f}"),
                         wlink(best) + " " + tierb((reg.get(best) or {}).get("tier")),
                         (" ".join(wlink(w) for w in c["wallets"][:8]) + (" …" if len(c["wallets"]) > 8 else ""), "", "wrap")])
        b.append(tdesc('Grupe walleta koje su kupile iste tokene (barem zadani broj zajedničkih). Velika grupa s istim tokenima često je jedna osoba, grupa insajdera ili walleti koji kopiraju istog trejdera.') + table(["#", ("Walleta", "n"), ("Zajednički tokeni (koliko walleta ga ima)", "wrap"), ("Zajedničkih", "n"),
                        ("Prosj. copy", "n"), "Najbolji", ("Walleti", "wrap")], crow))
    else:
        b.append(f"<div class=card>Još nema walleta koji dijele barem {min_shared} tokena.</div>")
    fc = funding_clusters()
    if fc:
        b.append("<h3>Walleti financirani iz istog izvora</h3><p class=mut>Iz rug filtera: jedan wallet je poslao SOL "
                 "na više walleta koji su onda kupovali. Tipično jedna osoba ili insajderska grupa.</p>")
        b.append(tdesc('Svaki red je wallet koji je slao SOL drugim walletima prije njihovih kupnji.') + table(["Financijer", ("Financirao walleta", "n"), ("Na tokenima", "wrap"), ("Walleti", "wrap")],
                       [[wlink(f), num(len(v["funded"])), (", ".join(tlink(t, syms.get(t)) for t in sorted(v["tokens"])), "", "wrap"),
                         (" ".join(wlink(w) for w in sorted(v["funded"])[:10]), "", "wrap")] for f, v in fc[:15]]))

    b.append("</details>")

    # 5. data status, folded
    from ui.labels import db as _db, table_name as _tn
    b.append("<details style='margin-top:16px'><summary>Koliko podataka bot ima</summary><p class=mut>Broj zapisa po "
             "vrsti podataka; 0 znači da taj dio bota još nije ništa zapisao.</p>"
             + table(["Dio bota", "Podaci", ("Zapisa", "n")],
                     [[esc(_db(d)), esc(_tn(t)), num(n)] for d, t, n in data.tables() if t != "sqlite_sequence"])
             + "</details>")

    b.append(modal())
    b.append(f"<script>{GRAPH_JS}</script>")
    return "Pregled", "".join(b)
