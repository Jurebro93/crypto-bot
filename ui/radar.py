"""The "Radar" page: what the hype scanner sees right now, in plain Croatian, plus whether the algorithm works
and what the paid sources cost. Read-only like the rest of the UI."""
import json
import os
import time

from ui import data
from ui.html import ago, badge, bar, esc, table, tlink, usd

HYPE_DIR = os.path.join(data.HERE, "hype")


def _pct(v):
    v = v or 0
    return v / 100 if v > 100 else v  # pump.fun reports some shares x100


def reasons(f, x):
    """Plain sentences for the features that pushed the score up, strongest first."""
    g = lambda k: f.get(k) or 0  # noqa: E731
    out = []
    if g("x_trend") and x.get("x_trend"):
        out.append((1.0, f"Ime je upravo trending tema na X-u („{x['x_trend']}“)."))
    if g("narrative") >= 0.4:
        n = x.get("copycats")
        out.append((g("narrative"), f"Tema je vruća: {n if n else 'puno'} tokena istog imena u zadnja 3 dana."))
    if g("turnover") >= 0.4:
        v = "3x ili više" if g("turnover") >= 1 else f"{g('turnover') * 3:.1f}x"
        out.append((g("turnover"), f"Novac ulazi brzo: volumen u zadnjem satu je {v} likvidnosti."))
    if g("buy_pressure") >= 0.4:
        out.append((g("buy_pressure"), f"Kupci prevladavaju: oko {50 + g('buy_pressure') * 20:.0f}% transakcija su kupnje."))
    if g("momentum") >= 0.25:
        v = "+200% ili više" if g("momentum") >= 1 else f"oko +{g('momentum') * 200:.0f}%"
        out.append((g("momentum"), f"Cijena raste: {v} u zadnjem satu."))
    if g("smart_money"):
        n = len(x.get("smart_buyers") or [])
        out.append((1.0, f"{n} provjerenih smart walleta je među prvim kupcima."))
    if g("kol_wallets") >= 0.4:
        out.append((g("kol_wallets"), f"KOL walleti ga trejdaju ({(x.get('pumpfun') or {}).get('kolCount')} na pump.fun)."))
    if g("kol_x"):
        out.append((g("kol_x"), "Praćeni influenceri su ga objavili na X-u."))
    if g("x_buzz") >= 0.25:
        xb = x.get("x") or {}
        infl = ", ".join("@" + h for h, _ in (xb.get("influencers") or [])[:3])
        who = f"{xb['authors']} različitih autora" if xb.get("authors") else "više autora"
        out.append((g("x_buzz"), f"Priča se na X-u: {who}"
                                 + (f", uključujući {infl}." if infl else ", bez velikih influencera.")))
    if g("telegram"):
        out.append((g("telegram"), "Objavljen u Telegram call kanalima."))
    if g("search_trend") >= 0.2:
        out.append((g("search_trend"), f"Google pretraga imena raste ({x.get('search_rise')}x u zadnja 24 h)."))
    if g("calendar"):
        out.append((0.8, "Pogađa nadolazeći događaj iz kalendara."))
    if g("revival") >= 0.4:
        out.append((g("revival"), "Stari token se budi: zadnji sat volumena višestruko je iznad dnevnog prosjeka."))
    if g("takeover"):
        out.append((0.7, "Moguće je preuzimanje zajednice (CTO ili novi profil)."))
    if g("fresh") >= 0.8:
        out.append((0.3, "Nov je, star manje od nekoliko sati."))
    if g("paid"):
        out.append((0.1, "Dev je platio DexScreener promociju (slab signal, lako se kupi)."))
    return [t for _, t in sorted(out, key=lambda r: -r[0])]


def risks(r, x, rug):
    out = []
    pf = x.get("pumpfun") or {}
    if _pct(pf.get("bundlerOwnedPercent")) >= 15:
        out.append(f"Bundleri drže {_pct(pf['bundlerOwnedPercent']):.0f}% ponude.")
    if _pct(pf.get("devHoldingsPercent")) >= 5:
        out.append(f"Dev drži {_pct(pf['devHoldingsPercent']):.0f}%.")
    if _pct(pf.get("top10HoldersPercent")) >= 35:
        out.append(f"Top 10 holdera drži {_pct(pf['top10HoldersPercent']):.0f}%.")
    if (r["liquidity"] or 0) < 10000:
        out.append(f"Mala likvidnost ({usd(r['liquidity'])[0]}): lako se manipulira i teško izlazi.")
    if (r["mcap"] or 0) > 1_000_000:
        out.append("Već je velik (mcap iznad $1M): manje prostora za rast.")
    if rug and rug.get("verdict") in ("VISOK RIZIK", "ODBAČEN", "OPREZ"):
        out.append(f"Rug filter: {rug['verdict']}.")
    return out


def _label(s):
    if s >= 50:
        return badge("jak kandidat", "good")
    if s >= 35:
        return badge("pratiti", "warn")
    return badge("slab")


def latest(hours=3, window_min=20):
    """Newest signal per token from the latest scan (signals within window_min of the newest), with its details."""
    since = int(time.time() - hours * 3600)
    sigs = data.hype_signals("ts >= ?", (since,), limit=3000)
    if sigs:
        newest = max(s["ts"] for s in sigs)
        sigs = [s for s in sigs if s["ts"] >= newest - window_min * 60]
    best = {}
    for s in sigs:
        if s["token"] not in best:
            best[s["token"]] = s
    det = {}
    for d in data.q(data.HYPE_DB, "SELECT token, ts, extra FROM hype_details WHERE ts >= ? ORDER BY ts DESC", (since,)):
        det.setdefault(d["token"], data.js(d["extra"], {}) or {})
    rows = []
    for t, s in best.items():
        rows.append({**s, "features": data.js(s["features"], {}) or {}, "extra": det.get(t, {})})
    return sorted(rows, key=lambda r: -(r["score"] or 0))


def _rugs():
    out = {}
    for r in data.rug_reports():
        out.setdefault(r["mint"], r)
    return out


def _algo():
    """Plain-language health check of the scoring, from hype/evaluate.py on a read-only connection."""
    con = data._connect(data.HYPE_DB)
    if con is None:
        return "<p class=mut>Nema baze hype.db.</p>"
    try:
        from hype import evaluate
        rows = evaluate.outcomes(con, horizon_h=24, hit=1.0)
    except Exception as e:
        return f"<p class=mut>Ocjena algoritma nije uspjela: {esc(e)}</p>"
    finally:
        con.close()
    first = data.q(data.HYPE_DB, "SELECT MIN(ts) t, COUNT(DISTINCT token) n FROM hype_signals")
    if len(rows) < 30:
        t0 = (first[0]["t"] if first else None) or time.time()
        left = max(0, 24 - (time.time() - t0) / 3600)
        return (f"<div class=card><b>Još ne znamo radi li algoritam.</b> Bot je dosad zapisao "
                f"{first[0]['n'] if first else 0} tokena, a ishod (je li token udvostručen u 24 h) poznat je za "
                f"{len(rows)}. Za prvu pouzdanu ocjenu treba barem 30 ishoda"
                + (f", prvi stižu za oko {left:.0f} h." if left > 0 else ".")
                + " Do tada su težine početna pretpostavka, i ne treba ulaziti pravim novcem samo na temelju ocjene.</div>")
    b = []
    base = sum(r["hit"] for r in rows) / len(rows)
    buckets = evaluate.by_bucket(rows)
    hi = [x for x in buckets if x["bucket"] in ("60-80", "80-100", "40-60")]
    hi_rate = (sum(x["hit_rate"] * x["n"] for x in hi) / sum(x["n"] for x in hi)) if hi else None
    verdict = ("Viša ocjena stvarno znači veću šansu za rast." if hi_rate is not None and hi_rate > base * 1.3 else
               "Viša ocjena zasad NE predviđa rast bolje od slučaja; težine treba promijeniti." if hi_rate is not None
               else "Još nema tokena s visokom ocjenom da se usporedi.")
    b.append(f"<div class=card><b>{verdict}</b> Od {len(rows)} tokena s poznatim ishodom, {base:.0%} je u 24 h "
             f"barem udvostručilo cijenu"
             + (f", a među onima s ocjenom 40+ njih {hi_rate:.0%}." if hi_rate is not None else ".") + "</div>")
    b.append(table(["Ocjena", ("Tokena", "n"), ("Udvostručilo se", "n"), "", ("Rug", "n"), ("Medijan nakon 24 h", "n")],
                   [[esc(x["bucket"]), (str(x["n"]), x["n"], "n"), (f"{x['hit_rate']:.0%}", x["hit_rate"], "n"),
                     bar(x["hit_rate"] * 100), (f"{x['rug_rate']:.0%}", x["rug_rate"], "n"),
                     (f"{x['median_end']:+.0%}", x["median_end"], "n")] for x in buckets]))
    from ui.pages import FEATURE
    lines = []
    for x in sorted(evaluate.feature_lift(rows), key=lambda x: -(x["lift"] or 0)):
        if x["n_strong"] < 8 or x["lift"] is None:
            continue
        word = ("pomaže" if x["lift"] >= 1.3 else "ne pomaže (čak šteti)" if x["lift"] <= 0.7 else "neutralan")
        kind = "good" if x["lift"] >= 1.3 else "bad" if x["lift"] <= 0.7 else ""
        lines.append(f"<li class={kind}><b>{esc(x['feature'])}</b> {word}: kad je jak, {x['hit_strong']:.0%} tokena "
                     f"se udvostruči (inače {x['hit_weak']:.0%}). <span class=mut>{esc(FEATURE.get(x['feature'], ''))}</span></li>")
    if lines:
        b.append("<h3>Koji signali stvarno rade</h3><ul class=r>" + "".join(lines) + "</ul>")
    pt = evaluate.paper_trade(rows, 50)
    if pt.get("trades"):
        b.append(f"<p>Simulacija: kupnja svakog tokena s ocjenom 50+ i prodaja na +100% ili -50% dala bi "
                 f"<b>{pt['avg_ret']:+.0%}</b> prosječno po trejdu ({pt['trades']} trejdova, {pt['win_rate']:.0%} u plusu), "
                 f"prije naknada.</p>")
    return "".join(b)


def _costs():
    try:
        cfg = json.load(open(os.path.join(HYPE_DIR, "apify.json")))
    except Exception:
        return "<p class=mut>Nema hype/apify.json.</p>"
    day = int(time.time() - 86400)
    spent = {r["source"]: r for r in data.q(data.HYPE_DB, "SELECT source, SUM(cost_usd) c, SUM(items) n, COUNT(*) runs, "
                                                          "MAX(ts) last FROM apify_runs WHERE ts >= ? GROUP BY source", (day,))}
    rows, tot = [], 0
    names = {"pumpfun": "pump.fun feedovi", "x_buzz": "X buzz po tokenu", "x_trends": "X trending teme",
             "google_trends": "Google Trends", "gmgn": "GMGN smart walleti", "kol_monitor": "KOL tracker na X-u"}
    for src, budget in cfg["daily_usd"].items():
        s = spent.get(src) or {}
        c = s.get("c") or 0
        tot += c
        rows.append([esc(names.get(src, src)), (f"${c:.2f}", c, "n"), (f"${budget:.2f}", budget, "n"),
                     bar(c, budget or 1, 80), (str(s.get("runs") or 0), s.get("runs") or 0, "n"),
                     ago(s.get("last")) if s.get("last") else "–"])
    month = ""
    try:
        from hype import apify
        used, cap = apify.monthly()
        month = (f"<p>Apify račun ovaj mjesec: <b>${used:.2f}</b> od ${cap:.0f}. Bot staje sam kad do limita ostane "
                 f"${cfg.get('monthly_reserve_usd', 3)}.</p>")
    except Exception:
        pass
    return (month + table(["Izvor", ("Potrošeno 24 h", "n"), ("Dnevni budžet", "n"), "", ("Runova", "n"), "Zadnji"], rows)
            + f"<p class=mut>Ukupno u 24 h ${tot:.2f}. Procjena po cijeni po rezultatu iz Apify Storea; "
              f"budžeti se mijenjaju u <code>hype/apify.json</code>.</p>")


def page(qs):
    rows = latest()
    rugs = _rugs()
    b = ["<h1>Radar</h1>"]
    if not rows:
        b.append("<div class=card><b>Nema svježih signala.</b> Hype skener nije radio u zadnja 3 sata "
                 "(<code>run_hype.py scan</code> ili <code>run_paper.py run --scan</code>).</div>")
    else:
        last = max(r["ts"] for r in rows)
        strong = [r for r in rows if r["score"] >= 50]
        watch = [r for r in rows if 35 <= r["score"] < 50]
        top = rows[0]
        lead = (f"Zadnji prolaz {ago(last)[0]}: pregledano <b>{len(rows)}</b> tokena. "
                + (f"<b>{len(strong)}</b> jakih kandidata, {len(watch)} za pratiti. " if strong else
                   f"Nijedan nije jak kandidat (ocjena 50+); {len(watch)} ih vrijedi pratiti. ")
                + f"Najbolji je <b>{esc(top['symbol'])}</b> ({top['score']:.0f}/100)"
                + (": " + esc(reasons(top["features"], top["extra"])[0].rstrip(".").lower()) + "." if reasons(top["features"], top["extra"]) else "."))
        b.append(f"<div class=card style='font-size:15px'>{lead}</div>")
        b.append("<p class=mut>Ocjena 0-100 je ponderirani prosjek izmjerenih signala. 50+ = jak kandidat, 35-50 = pratiti. "
                 "Ocjena nije preporuka za kupnju dok odjeljak „Radi li algoritam“ ne pokaže da predviđa rast.</p>")
        b.append("<h2>Kandidati sada</h2>")
        tr = []
        for r in rows[:25]:
            why = reasons(r["features"], r["extra"])[:3]
            risk = risks(r, r["extra"], rugs.get(r["token"]))
            tr.append([tlink(r["token"], r["symbol"]), (f"{bar(r['score'], 100, 60)} {r['score']:.0f}", r["score"], "n"),
                       _label(r["score"]), usd(r["mcap"]), usd(r["liquidity"]),
                       ("<ul class=r>" + "".join(f"<li class=good>{esc(t)}</li>" for t in why) + "</ul>" if why else
                        "<span class=mut>samo tržišni signali, ništa posebno</span>", "", "wrap"),
                       ("<ul class=r>" + "".join(f"<li class=bad>{esc(t)}</li>" for t in risk) + "</ul>" if risk else
                        "<span class=mut>nema poznatih</span>", "", "wrap")])
        b.append(table(["Token", ("Ocjena", "n"), "", ("Mcap", "n"), ("Likv.", "n"), ("Zašto", "wrap"), ("Rizici", "wrap")], tr))

        b.append("<h2>Narativi</h2><div class=two><div>")
        tr_rows = [r for r in rows if r["extra"].get("x_trend")]
        b.append("<h3>Tokeni nazvani po X trendu</h3>" + table(
            ["Token", "Trend na X-u", ("Ocjena", "n")],
            [[tlink(r["token"], r["symbol"]), esc(r["extra"]["x_trend"]), (f"{r['score']:.0f}", r["score"], "n")] for r in tr_rows],
            empty="Nijedan token ne nosi ime trenutnog X trenda."))
        b.append("</div><div>")
        cc = sorted([r for r in rows if r["extra"].get("copycats")], key=lambda r: -r["extra"]["copycats"])[:10]
        b.append("<h3>Teme s najviše kopija (3 dana)</h3>" + table(
            ["Token", ("Kopija", "n"), ("Ocjena", "n")],
            [[tlink(r["token"], r["symbol"]), (str(r["extra"]["copycats"]), r["extra"]["copycats"], "n"),
              (f"{r['score']:.0f}", r["score"], "n")] for r in cc], empty="Nema podataka o kopijama."))
        b.append("</div></div><p class=mut>Kad se pojavi puno tokena istog imena, tema je živa: kockari ne kopiraju mrtve "
                 "narative. Generičke riječi (INU, CAT) daju lažne kopije.</p>")

    sw = data.smart_wallets()
    good = [w for w in sw if (w["score"] or 0) >= 50]
    by_src = {}
    for w in good:
        k = "GMGN" if w["found_via"] == "gmgn" else "naša analiza (Helius)"
        by_src[k] = by_src.get(k, 0) + 1
    with_smart = [r for r in rows if r["extra"].get("smart_buyers")]
    b.append("<h2>Smart money</h2>")
    b.append(f"<p>U bazi je <b>{len(good)}</b> walleta s ocjenom 50+ ("
             + ", ".join(f"{v} iz {k}" for k, v in by_src.items()) + "). "
             + (f"Ulaze rano u: {', '.join(esc(r['symbol']) for r in with_smart[:8])}." if with_smart else
                "U zadnjim prolazima nijedan od njih nije bio među prvim kupcima kandidata.") + "</p>")
    b.append("<h2>Radi li algoritam?</h2>" + _algo())
    b.append("<h2>Troškovi Apifyja</h2>" + _costs())
    return "Radar", "".join(b)
