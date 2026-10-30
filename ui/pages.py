"""One function per page. Each returns (title, body_html)."""
import os
import time
from urllib.parse import quote

from ui import data, explain, jobs
from ui.html import (tdesc, ago, badge, bar, breakdown, esc, ext_token, ext_wallet, filt, jsonblock, num, scorecell,
                     short, signed, table, tierb, tlink, ts, usd, verdict, wlink)

ROLE = {
    "early_buyer": ("rani kupac", "kupio među prvima token koji je kasnije narastao (pobjednik)"),
    "smart": ("smart money", "označen kao uspješan trader"),
    "top_trader": ("top trader", "među najboljim traderima tokena"),
    "holder": ("holder", "među top holderima tokena u rug provjeri"),
    "manual": ("ručno", "dodan ručno (`run_wallets.py wallet`)"),
    "dev": ("dev", "kreator tokena: nikad se ne kopira"),
    "bundler": ("bundler", "kupio u istom bloku kao kreacija (bundle)"),
    "sniper": ("snajper", "kupio u prvih par sekundi: bot, ne kopira se"),
    "funder": ("financijer", "poslao SOL devu ili ranim kupcima"),
    "dust": ("sitni kupac", "kupio premalo (ispod 0.1 SOL) da bi se računao"),
}
SOURCE = {"harvest": "harvest (rani kupci pobjednika)", "hype_learn": "hype learn (smart walleti)",
          "rug": "rug filter", "manual": "ručno"}

FEATURE = {
    "fresh": "starost: 1 ispod 1 h, 0 na 72 h",
    "turnover": "volumen zadnjeg sata / likvidnost (3x = 1)",
    "buy_pressure": "udio kupnji u zadnjem satu (iznad 50%)",
    "momentum": "rast cijene u 1 h (+200% = 1)",
    "activity": "broj transakcija u 1 h (log, 2000 = 1)",
    "paid": "plaćeni DexScreener profil ili boost",
    "socials": "broj društvenih mreža i web",
    "narrative": "broj kopija iste teme u 72 h (8 = 1)",
    "calendar": "simbol/ime pogađa ključnu riječ iz kalendara",
    "telegram": "broj Telegram kanala koji su objavili CA u 6 h (3 = 1)",
    "smart_money": "poznati smart walleti među ranim kupcima (4 = 1)",
    "revival": "stari token (>3 d) kojem je zadnji sat volumena višestruko iznad prosjeka",
    "takeover": "revival + CTO ili novi profil",
    "x_buzz": "spominjanja na X-u (autori, influenceri, engagement)",
    "kol_wallets": "pump.fun: broj poznatih KOL walleta koji su trejdali token (5 = 1)",
    "x_trend": "ime ili simbol tokena je trenutno trending tema na X-u",
    "kol_x": "praćeni KOL-ovi tweetali CA ili $ticker u 6 h (2 = 1)",
    "kol_group": "grupni poziv na X-u u 6 h: dobri KOL-ovi (ocjena 50+) zovu isti token u 30 min (2 = 1, ostali autori +0.1 do 0.5); 0 ako devovi prodaju u poziv",
    "search_trend": "Google pretraga imena u zadnja 24 h vs prethodnih 6 dana (3x = 1)",
}


def _sym_map():
    return data.symbols()


# ---------------- wallets ----------------

def wallets(qs):
    show_all = qs.get("all") == "1"
    only = qs.get("only")
    min_score = float(qs.get("min_score", explain.COPY_MIN_SCORE))
    min_closed = int(qs.get("min_closed", explain.COPY_MIN_CLOSED))
    ws = data.wallets(scored_only=not show_all)
    rows = []
    for w in ws:
        s = w["stats"]
        ok, why = explain.shortlist(w, min_score, min_closed)
        if only == "list" and not ok:
            continue
        rows.append([wlink(w["wallet"]), tierb(w["tier"]),
                     badge("DA", "good") if ok else badge("ne"),
                     scorecell(w["copy_score"]), scorecell(w["score"]),
                     signed(s.get("closed_pnl_sol")), signed(s.get("roi_on_cost"), "{:+.0%}"),
                     num(s.get("win_rate"), "{:.0%}"), num(s.get("closed")), num(s.get("big_wins")),
                     num(s.get("median_hold_min"), "{:g}"), num(s.get("median_buy_sol"), "{:g}"),
                     num(s.get("trades_per_day"), "{:g}"), num(s.get("last_trade_days"), "{:g}"),
                     num(s.get("early_in_winners")),
                     esc(", ".join(f"{SOURCE.get(k, k)}" for k in w["sources"])),
                     " ".join(badge(l, "bad") for l in w["labels"]),
                     (esc("; ".join(why + (s.get("copy_notes") or []))) or "–", "", "wrap")])
    form = (f'<form class=flt method=get>{filt("wt", "Filtriraj adresu, oznaku…")}'
            f'<label>min copy <input name=min_score value="{min_score:g}" size=4></label>'
            f'<label>min zatvorenih <input name=min_closed value="{min_closed}" size=3></label>'
            f'<label><input type=checkbox name=only value=list {"checked" if only == "list" else ""}> samo copy lista</label>'
            f'<label><input type=checkbox name=all value=1 {"checked" if show_all else ""}> i neocijenjeni</label>'
            f'<button>Primijeni</button></form>')
    head = ["Wallet", "Tier", "Na listi", ("Copy", "n"), ("Ocjena", "n"), ("PnL SOL", "n"), ("ROI", "n"),
            ("Win", "n"), ("Zatv.", "n"), ("2x+", "n"), ("Drži min", "n"), ("Kupnja SOL", "n"), ("Trejd/dan", "n"),
            ("Neaktivan d", "n"), ("Rano u pobj.", "n"), "Izvor", "Oznake", ("Zašto nije na listi / napomene", "wrap")]
    since, last, tail = jobs.status("wallets")
    if since:
        state = f"pokrenuto {ago(since)[0]}, još radi"
    elif last:
        state = f"zadnji ručni prolaz završio {ago(last[1])[0]}" + ("" if last[2] == 0 else f", greška (kod {last[2]})")
    else:
        state = "od pokretanja dashboarda nije ručno pokretano (automatski ide svakih 6 h)"
    run = (f'<form id=run method=post action=/run/wallets class=flt><button {"disabled" if since else ""}>'
           f'Pokreni ocjenjivanje walleta</button> <span class=mut>{esc(state)}. Prikupi nove walletove, ocijeni red '
           f'(do {jobs.CREDITS} Helius kredita) i osvježi copy listu; traje nekoliko minuta, osvježi stranicu.</span></form>'
           + (f"<details><summary>Zadnji ispis</summary><pre>{esc(tail)}</pre></details>" if tail else ""))
    intro = ("<h1>Walleti</h1><p class=mut>Copy lista = isti uvjeti kao <code>run_wallets.py copy</code>: copy ocjena "
             f"≥ {min_score:g}, barem {min_closed} zatvorenih pozicija, bez loših oznaka. Klik na zaglavlje sortira, "
             "klik na wallet otvara detalje i raspis ocjene. Kriteriji su na stranici <a href=/criteria#walleti>Kriteriji</a>.</p>")
    return "Walleti", intro + run + form + tdesc('Svi walleti u registru s ocjenama; klik na zaglavlje sortira. Walleti s oznakom „Na listi” su kandidati za copytrading.') + table(head, rows, "wt", "Nema walleta. Pokreni `run_wallets.py harvest` i `score`.")


def wallet(addr, qs):
    w = data.wallet(addr)
    sm = {r["wallet"]: r for r in data.smart_wallets()}.get(addr)
    if not w and not sm:
        return "Wallet", f"<h1>Wallet</h1><p>Wallet <code>{esc(addr)}</code> nije u registru.</p>"
    w = w or {"wallet": addr, "stats": {}, "labels": [], "sources": {}, "tier": None, "score": None,
              "copy_score": None}
    s = w["stats"]
    ok, why = explain.shortlist(w)
    syms = _sym_map()
    b = [f"<h1>Wallet <code>{esc(short(addr, 6))}</code></h1><p><code>{esc(addr)}</code> · {ext_wallet(addr)}</p>"]
    b.append("<div class=grid>")
    for v, l in [(tierb(w.get("tier")), "tier"), (w.get("copy_score") if w.get("copy_score") is not None else "–", "copy ocjena"),
                 (w.get("score") if w.get("score") is not None else "–", "ocjena profitabilnosti"),
                 (badge("NA COPY LISTI", "good") if ok else badge("nije na listi"), "status"),
                 (f'{s.get("closed_pnl_sol", 0):+.2f} SOL' if s else "–", "PnL zatvorenih"),
                 (f'{s.get("win_rate", 0):.0%} ({s.get("closed", 0)})' if s else "–", "win rate (zatvorenih)")]:
        b.append(f"<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>")
    b.append("</div>")

    b.append("<h2>Zašto je odabran / izdvojen</h2><div class=card><ul class=r>")
    sg = data.sightings(wallet=addr)
    if not sg:
        b.append("<li>Nema zapisa gdje je viđen.</li>")
    for x in sg:
        role, desc = ROLE.get(x["role"], (x["role"], ""))
        e = x["extra"]
        det = []
        if e.get("secs_after_first") is not None:
            det.append(f"{e['secs_after_first']} s nakon prve kupnje")
        if x.get("sol_in"):
            det.append(f"uložio {x['sol_in']:.2f} SOL")
        if e.get("mcap_now"):
            det.append(f"token danas ${e['mcap_now']:,.0f} mcap")
        if e.get("verdict"):
            det.append(f"rug presuda tokena: {e['verdict']}")
        if e.get("funded"):
            det.append(f"financirao {short(e['funded'])}")
        if e.get("funder"):
            det.append(f"financiran iz {short(e['funder'])}")
        kind = "bad" if x["role"] in ("dev", "bundler", "sniper", "funder") else "good" if x["role"] in (
            "early_buyer", "smart", "top_trader", "manual") else ""
        tok = " na " + tlink(x["token"], syms.get(x["token"])) if x["token"] else ""
        b.append(f'<li class="{kind}"><b>{esc(role)}</b>{tok} · {esc(SOURCE.get(x["source"], x["source"]))} · '
                 f'{ts(x["ts"])[0]}<br><span class=mut>{esc(desc)}{"; " if det else ""}{esc(", ".join(det))}</span></li>')
    b.append("</ul>")
    if s.get("early_in_winners"):
        b.append(f"<p>Rano je ušao u <b>{s['early_in_winners']}</b> pobjednika"
                 + (f": copy ocjena dobiva +{5 * min(3, s['early_in_winners'] - 1)} bonusa." if s['early_in_winners'] > 1 else ".")
                 + "</p>")
    if w["labels"]:
        b.append("<p>Oznake: " + " ".join(badge(l, "bad") for l in w["labels"]) +
                 " <span class=mut>(oznake iz popisa loših nikad ne idu na copy listu)</span></p>")
    b.append(("<p>" + badge("NA COPY LISTI", "good") + " prolazi sve uvjete.</p>") if ok else
             ("<p><b>Nije na copy listi jer:</b> " + esc("; ".join(why)) + "</p>"))
    b.append("</div>")

    if s:
        parts, ev = explain.wallet_score(s)
        b.append("<h2>Raspis ocjene profitabilnosti (0-100)</h2>")
        b.append(breakdown(parts, "Zbroj", w.get("score"), ev,
                           f"(dokaz: {s.get('closed', 0)}/10 zatvorenih pozicija)"))
        b.append("<h2>Raspis copy ocjene</h2><div class=card>")
        mults = explain.copy_multipliers(s, w["labels"])
        m = 1.0
        b.append("<ul class=r>")
        for reason, f in mults:
            m *= f
            b.append(f'<li class="{"bad" if f == 0 else "warn"}">{esc(reason)}: × {f:g}</li>')
        if not mults:
            b.append('<li class=good>nema kazni: drži dovoljno dugo, aktivan, normalne veličine kupnji</li>')
        b.append("</ul>")
        bonus = 5 * min(3, s.get("early_in_winners", 0) - 1) if s.get("early_in_winners", 0) > 1 else 0
        b.append(f"<p>copy = ocjena {w.get('score')} × {m:.2f}"
                 + (f" + {bonus} (rano u više pobjednika)" if bonus and m else "")
                 + f" = <b>{w.get('copy_score')}</b></p></div>")

        b.append("<h2>Statistika</h2>")
        lab = {"positions": "pozicija", "closed": "zatvorenih", "open": "otvorenih", "win_rate": "win rate",
               "realized_sol": "realizirano SOL", "unrealized_sol": "nerealizirano SOL",
               "closed_pnl_sol": "PnL zatvorenih SOL", "roi_on_cost": "ROI na uloženo", "profit_factor": "profit factor",
               "big_wins": "2x+ trejdova", "rugged_in": "zatvoreno s -90% ili gore (rug)", "median_roi": "medijan ROI",
               "top_trade_share": "udio najvećeg trejda u dobiti", "median_hold_min": "medijan držanja (min)",
               "median_buy_sol": "medijan kupnje (SOL)", "trades_per_day": "trejdova dnevno",
               "free_token_ratio": "udio tokena dobivenih besplatno", "last_trade_days": "dana od zadnjeg trejda",
               "history_days": "dana povijesti", "early_in_winners": "rano u pobjednicima", "credits": "Helius kredita"}
        b.append(tdesc('Sirove brojke iz kojih su izračunate ocjene gore, iz zadnjeg ocjenjivanja walleta.') + table(["Metrika", ("Vrijednost", "n")],
                       [[esc(lab.get(k, k)), (esc(v), v if isinstance(v, (int, float)) else 0, "n")]
                        for k, v in s.items() if not isinstance(v, (list, dict))]))

    pos = _positions(addr)
    if pos:
        b.append("<h2>Pozicije (iz spremljenih trejdova)</h2><p class=mut>Nerealizirani PnL ovdje nije izračunat "
                 "(treba živa cijena); status otvoreno/zatvoreno je po udjelu prodanog.</p>")
        b.append(table(["Token", "Status", ("Uloženo SOL", "n"), ("Realizirano SOL", "n"), ("ROI (realiz.)", "n"),
                        ("Kupnji", "n"), ("Prodaja", "n"), ("Drži min", "n"), "Zadnje"],
                       [[tlink(p["mint"], syms.get(p["mint"])), esc(p["status"]), num(p.get("cost"), "{:.3f}"),
                         signed(p.get("realized"), "{:+.3f}"), signed(p.get("roi"), "{:+.0%}"), num(p["buys"]),
                         num(p["sells"]), num(p.get("hold_min"), "{:.0f}"), ts(p["last_ts"])]
                        for p in sorted(pos.values(), key=lambda p: -(p["last_ts"] or 0))]))
    hist = data.wallet_pnl(addr)
    if hist:
        b.append("<h2>Povijest ocjena</h2>")
        b.append(tdesc('Svako ocjenjivanje ovog walleta kroz vrijeme: vidi se popravlja li se ili kvari.') + table(["Vrijeme", ("Realiz.", "n"), ("Nerealiz.", "n"), ("Win", "n"), ("Zatv.", "n"),
                        ("Ocjena", "n"), ("Copy", "n")],
                       [[ts(h["ts"]), signed(h["realized_sol"]), signed(h["unrealized_sol"]),
                         num(h["win_rate"], "{:.0%}"), num(h["closed"]), num(h["score"]), num(h["copy_score"])]
                        for h in reversed(hist)]))
    if sm:
        b.append("<h2>Hype modul (smart_wallets)</h2>")
        b.append(f"<p>Ocjena hype modula: <b>{sm['score']}</b> · pronađen preko: "
                 + ", ".join(tlink(m, syms.get(m)) for m in (sm.get("found_via") or "").split(",") if m) + "</p>")
        b.append(jsonblock(data.js(sm["stats"], {})))
    return f"Wallet {short(addr)}", "".join(b)


def _positions(addr):
    rows = data.wallet_trades(addr)
    if not rows:
        return {}
    try:
        from wallets import pnl
        return {m: p for m, p in pnl.positions(rows).items() if p.get("status") in ("open", "closed")}
    except Exception:
        return {}


# ---------------- tokens ----------------

def tier_html(mint):
    """Where the token stands in the tiered analysis: class, tier reached, T0 verdict, shape of its mcap path."""
    from ui.html import klasab, razinab
    t = data.token_tiers().get(mint)
    if not t:
        return ""
    t0 = {"prolaz": badge("T0 prošao", "good"), "pad": badge("T0 pao", "bad"), "nije": badge("izvan skena")}.get(t.get("t0"), "")
    put = ""
    if t.get("put_skokovitost") is not None:
        put = (f" · put do mcapa: brzina {t['put_brzina']:+.2f}/h, skokovitost {t['put_skokovitost']:.0%}, "
               f"zadržavanje {t['put_zadrzavanje']:.0%}")
    return (f"<p>Slojevita analiza: {razinab(t.get('razina'))} {klasab(t.get('klasa'))} {t0} "
            f"<span class=mut>{esc(t.get('t0_razlog') or '')}{esc(put)} · potrošeno ~{t.get('credits') or 0} Helius kredita</span></p>")


def token(mint, qs):
    ev = data.event_tokens(mint)
    sigs = data.hype_signals("token=?", (mint,), "ts DESC")
    rugs = data.rug_reports(mint)
    sym = (ev[0]["symbol"] if ev else None) or (sigs[0]["symbol"] if sigs else None) or (rugs[0]["symbol"] if rugs else None)
    url = (ev[0]["url"] if ev else None) or (sigs[0]["url"] if sigs else None)
    b = [f"<h1>{esc(sym or short(mint))}</h1><p><code>{esc(mint)}</code> · {ext_token(mint, url)}</p>"]
    if not (ev or sigs or rugs):
        b.append("<p>Ovaj token nije ni u jednoj analizi.</p>")
    else:
        from ui import narrative
        b.append(narrative.html(mint))
        b.append(tier_html(mint))

    # summary
    b.append("<div class=grid>")
    best = max(ev, key=lambda e: e["score"] or 0) if ev else None
    for v, l in [(best["score"] if best else "–", "event ocjena (DexScreener)"),
                 (max(s["score"] or 0 for s in sigs) if sigs else "–", "hype max"),
                 (verdict(rugs[0]["verdict"]) if rugs else "–", "rug presuda"),
                 (rugs[0]["score"] if rugs and rugs[0]["score"] is not None else "–", "rug ocjena")]:
        b.append(f"<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>")
    b.append("</div>")
    from ui import kol
    b.append(kol.token_section(mint))

    # layer 1: event
    b.append('<h2 id=event>1. Event sloj: zašto je vezan uz događaj</h2>')
    if not ev:
        b.append("<p class=mut>Nije pronađen ni za jedan event iz kalendara.</p>")
    for e in ev:
        d = dict(e["data"])
        d.setdefault("cto", e["cto"])
        role = "pravi (canonical)" if e["role"] == "canonical" else "kopija (copycat)"
        b.append(f'<div class=card><b>{esc(e["event"])}</b> · {esc(e["event_date"])} · pojam '
                 f'<code>{esc(e["keyword"])}</code> · {badge(role, "good" if e["role"] == "canonical" else "")}'
                 f'<p class=mut>Token pripada eventu jer mu je simbol jednak pojmu ili ime sadrži pojam. '
                 f'Unutar eventa najviša ocjena je "pravi", ostali su kopije.</p>')
        b.append(breakdown(explain.organic(d), "Organska ocjena", e["score"]))
        b.append("</div>")

    # layer 2: hype
    b.append('<h2 id=hype>2. Hype sloj: rani signal rasta</h2>')
    if not sigs:
        b.append("<p class=mut>Hype skener ga nije uhvatio.</p>")
    else:
        last = sigs[0]
        f = data.js(last["features"], {}) or {}
        wts = data.js(last["weights"], {}) or {}
        tot = sum(wts.get(k, 0) for k in f) or 1  # same as hype/score.py: only measured features count
        rows = []
        for k in sorted(set(f), key=lambda k: -(wts.get(k, 0) * f.get(k, 0))):
            val, wt = f.get(k, 0) or 0, wts.get(k, 0)
            pts = 100 * wt * val / tot
            rows.append([esc(k), (f"{val:.2f}", val, "n"), (f"{wt:g}", wt, "n"), (f"{pts:.1f}", pts, "n"),
                         bar(pts, 100 * wt / tot if wt else 1), (f'<span class=mut>{esc(FEATURE.get(k, ""))}</span>', "", "wrap")])
        b.append(f"<p>Zadnji signal {ts(last['ts'])[0]} UTC, ocjena <b>{last['score']}</b>, izvori: "
                 f"<code>{esc(last['sources'])}</code>. Ocjena = Σ(značajka × težina) / Σ težina izmjerenih značajki × 100; "
                 f"provjera koja nije rađena (npr. X buzz) ne ulazi ni u zbroj ni u nazivnik.</p>")
        b.append(tdesc('Raspis zadnje hype ocjene: koliko je svaki signal izmjeren (0-1), koliko vrijedi i koliko je bodova donio.') + table(["Značajka", ("Vrijednost 0-1", "n"), ("Težina", "n"), ("Doprinos", "n"), "", ("Što mjeri", "wrap")], rows))
        b.append(f"<p>Zbroj doprinosa: <b>{sum(r[3][1] for r in rows):.1f}</b> <span class=mut>(spremljeno {last['score']})</span></p>")
        snaps = data.hype_snapshots(mint)
        if len(snaps) > 1:
            b.append("<h3>Cijena od prvog signala</h3>" + _spark(snaps, sigs[-1]["price"]))
        b.append("<h3>Svi signali</h3>")
        b.append(tdesc('Svaki put kad ga je hype skener zabilježio, s cijenom i izvorima u tom trenutku.') + table(["Vrijeme", ("Ocjena", "n"), ("Cijena", "n"), ("Mcap", "n"), ("Likvidnost", "n"), "Izvori"],
                       [[ts(s["ts"]), scorecell(s["score"]), num(s["price"], "{:.8g}"), usd(s["mcap"]),
                         usd(s["liquidity"]), esc(s["sources"])] for s in sigs[:200]]))

    # layer 3: rug
    b.append('<h2 id=rug>3. Rug filter: je li siguran</h2>')
    if not rugs:
        b.append("<p class=mut>Nije provjeren rug filterom (<code>python3 run_rug.py " + esc(mint) + "</code>).</p>")
    else:
        r = rugs[0]
        d = r["data"]
        b.append(f"<p>{verdict(r['verdict'])} ocjena <b>{r['score'] if r['score'] is not None else '– (tvrdi pad)'}</b>"
                 f" · provjereno {ts(r['checked_at'])[0]} UTC</p><div class=card><ul class=r>")
        for x in d.get("hard_fails", []):
            b.append(f'<li class=bad><b>TVRDI PAD:</b> {esc(x)}</li>')
        for x in d.get("flags", []):
            b.append(f'<li class=warn>{esc(x)}</li>')
        for x in d.get("positives", []):
            b.append(f'<li class=good>{esc(x)}</li>')
        if not (d.get("hard_fails") or d.get("flags") or d.get("positives")):
            b.append("<li>Nema zabilježenih razloga.</li>")
        b.append("</ul><p class=mut>Kreće od 100, svaka zastavica oduzima bodove, smart walleti dodaju do +15. "
                 "Tvrdi pad = odmah ODBAČEN. ≥75 PROLAZI, 50-74 OPREZ, &lt;50 VISOK RIZIK.</p></div>")
        L, h, c, v, dv, m = (d.get(k) or {} for k in ("launch", "holders", "cluster", "volume", "dev", "market"))
        metr = [("Bundle (blok kreacije)", f"{L.get('bundle_pct', '–')}% · {L.get('bundle_wallets', '–')} walleta"),
                ("Snajperi (~8 s)", f"{L.get('sniper_pct', '–')}% · {L.get('sniper_wallets', '–')} walleta"),
                ("Top 10 holdera", f"{h.get('top10_pct', '–')}%"),
                ("Fresh walleti (rani / holderi)", f"{h.get('fresh_early_pct', '–')}% / {h.get('fresh_holders_pct', '–')}%"),
                ("Klaster (isti izvor SOL-a)", f"{max(c.get('holding_pct', 0), c.get('early_pct', 0))}% · {len(c.get('wallets') or [])} walleta"),
                ("Wash score", f"{d.get('wash_score', '–')} (round-trip {v.get('round_trip_volume_pct', '–')}%, top5 {v.get('top5_volume_pct', '–')}%)"),
                ("RugCheck insajderi", f"{(d.get('rugcheck') or {}).get('insider_pct', '–')}%"),
                ("Mint / freeze authority", f"{'AKTIVNA' if (d.get('authorities') or {}).get('mintAuthority') else 'ugašena'} / "
                                            f"{'AKTIVNA' if (d.get('authorities') or {}).get('freezeAuthority') else 'ugašena'}"),
                ("Dev", f"{short(dv.get('wallet', ''))} · napravio {dv.get('tokens_created', '–')} tokena (živih {dv.get('tokens_alive', '–')}) · "
                        f"drži {dv.get('hold_pct', '–')}% · prodao {dv.get('sold_pct', '–')}%"),
                ("Likvidnost / max ulaz (5% slippage)", f"${m.get('liquidity') or 0:,.0f} / ${m.get('max_entry_usd_5pct') or 0:,.0f}")]
        b.append(tdesc('Rezultati pojedinih provjera rug filtera (Helius + RugCheck): ovlasti, dev, holderi, likvidnost.') + table(["Provjera", ("Vrijednost", "wrap")], [[esc(k), (esc(x), "", "wrap")] for k, x in metr]))
        top = h.get("top") or []
        if top:
            b.append("<h3>Top holderi</h3>" + tdesc('Najveći holderi i jesu li povezani s devom ili međusobno (insajderi).') + table(["Wallet", ("%", "n"), "Insajder"],
                                                     [[wlink(x["wallet"]), num(x.get("pct"), "{:g}"),
                                                       badge("da", "bad") if x.get("insider") else "ne"] for x in top]))
        md = os.path.join("rug", f"{mint}.md")
        if data.read_output(md) is not None:
            b.append(f'<p><a href="/outputs/{quote(md)}">Puni rug izvještaj</a></p>')
        if len(rugs) > 1:
            b.append("<h3>Ranije provjere</h3>" + tdesc('Prijašnje rug provjere istog tokena.') + table(["Vrijeme", "Presuda", ("Ocjena", "n")],
                                                        [[ts(x["checked_at"]), verdict(x["verdict"]), num(x["score"])] for x in rugs[1:]]))
        b.append(jsonblock(d))

    pc = data.paper_candidates(mint)
    if pc:
        c = pc[0]
        b.append('<h2 id=paper>4. Paper trading: je li bot uzeo token</h2>')
        b.append(f"<div class=card>{_decision(c)} {esc(c['reason'] or '')} <span class=mut>· {esc(c['origin'])} · "
                 f"{ts(c['first_ts'])[0]} UTC</span>" + "".join(f"<div class=mut>rug: {esc(x)}</div>" for x in c["rug_flags"]))
        for t in data.paper_trades(mint):
            b.append(f"<p>Trejd #{t['id']}: {esc(t['status'])}, povrat {(t['ret'] or 0):+.0%}, max {(t['max_ret'] or 0):+.0%}, "
                     f"izlaz {esc(t['exit_reason'] or '–')}</p>")
        b.append("</div>")

    # wallets on this token
    sg = data.sightings(token=mint)
    b.append('<h2>Walleti viđeni na ovom tokenu</h2>')
    wmap = {w["wallet"]: w for w in data.wallets(scored_only=False)}
    b.append(tdesc('Walleti iz registra koji su kupovali ovaj token, s ulogom (rani kupac, top trader…) i ocjenom.') + table(["Wallet", "Uloga", "Izvor", ("SOL", "n"), ("Copy", "n"), "Tier", "Oznake"],
                   [[wlink(x["wallet"]), esc(ROLE.get(x["role"], (x["role"],))[0]), esc(SOURCE.get(x["source"], x["source"])),
                     num(x["sol_in"], "{:.2f}"), num((wmap.get(x["wallet"]) or {}).get("copy_score")),
                     tierb((wmap.get(x["wallet"]) or {}).get("tier")),
                     " ".join(badge(l, "bad") for l in (wmap.get(x["wallet"]) or {}).get("labels", []))] for x in sg],
                   empty="Nijedan wallet nije zabilježen za ovaj token."))
    return sym or short(mint), "".join(b)


def _spark(snaps, base):
    pts = [(s["ts"], s["price"]) for s in snaps if s["price"]]
    if len(pts) < 2:
        return ""
    base = base or pts[0][1]
    t0, t1 = pts[0][0], pts[-1][0]
    ys = [p / base - 1 for _, p in pts]
    lo, hi = min(ys + [0]), max(ys + [0])
    W, H = 600, 120

    def xy(t, y):
        return (W * (t - t0) / max(1, t1 - t0), H - H * (y - lo) / max(1e-9, hi - lo))
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(t, v) for (t, _), v in zip(pts, ys)))
    zy = xy(t0, 0)[1]
    return (f'<div class=card><svg viewBox="0 0 {W} {H}" width="100%" height="{H}" preserveAspectRatio=none>'
            f'<line x1=0 x2={W} y1={zy:.1f} y2={zy:.1f} stroke="currentColor" stroke-opacity=.2 />'
            f'<polyline points="{path}" fill=none stroke="var(--bar)" stroke-width=2 vector-effect=non-scaling-stroke /></svg>'
            f'<span class=mut>max {max(ys):+.0%} · zadnje {ys[-1]:+.0%} od cijene prvog signala · {len(pts)} točaka</span></div>')


# ---------------- events ----------------

def _events_table(evs, tid):
    et = {}
    for t in data.event_tokens():
        et.setdefault((t["event_date"], t["event"]), []).append(t)
    rows = []
    for e in evs:
        toks = sorted(et.get((e["date"], e["title"]), []), key=lambda t: -(t["score"] or 0))
        tl = ", ".join(tlink(t["token"], t["symbol"]) + ("★" if t["role"] == "canonical" else "") for t in toks[:6])
        parts = explain.event_hype(e)
        det = (f"<details><summary>raspis</summary>"
               + "".join(f"<div>{esc(n)}: <b>{p:.1f}</b>/{m} <span class=mut>{esc(x)}</span></div>" for n, p, m, x in parts)
               + "</details>")
        rows.append([(esc(e["date"]), e["date"], ""), esc(e["kind"]),
                     (f'<a href="{esc(e["url"])}" target=_blank>{esc(e["title"])}</a>' if e.get("url") else esc(e["title"]), e["title"], "wrap"),
                     scorecell(e["hype"]), num(e.get("token_likelihood"), "{:.2f}"),
                     esc(" ".join(e["keywords"])), esc(e["source"]),
                     (tl or "–", len(toks), "wrap"), (det, "", "wrap")])
    return table(["Datum", "Vrsta", ("Event", "wrap"), ("Hype", "n"), ("Šansa za token", "n"), "Ključne riječi",
                  "Izvor", ("Tokeni (★ = pravi)", "wrap"), ("Zašto ta ocjena", "wrap")], rows, tid,
                 "Nema evenata. Pokreni `run_calendar.py`.")


def events(qs):
    evs = data.events()
    past = qs.get("past") == "1"
    today = time.strftime("%Y-%m-%d")
    if not past:
        evs = [e for e in evs if not e["date"] or e["date"] >= today]
    form = (f'<form class=flt method=get>{filt("et", "Filtriraj event, ključnu riječ…")}<label><input type=checkbox '
            f'name=past value=1 {"checked" if past else ""} onchange="this.form.submit()"> i prošli</label></form>')
    intro = ("<h1>Eventi</h1><p class=mut>Događaji iz kalendara s hype ocjenom 0-100 i tokenima koje je DexScreener "
             "pronašao. <a href=/criteria#eventi>Kriteriji</a>.</p>")
    return "Eventi", intro + form + tdesc('Kako alat traži tokene za evente: iz kalendara uzme ključne riječi događaja i na DexScreeneru traži tokene s tim imenom ili simbolom, a najbolje ocijenjeni postaje „pravi” token. Hype = koliko se o događaju priča, šansa za token = procjena da će netko napraviti token.') + _events_table(evs, "et")


# ---------------- outputs ----------------

def outputs(qs):
    files = data.outputs()
    rows = [[f'<a href="/outputs/{quote(p)}">{esc(p)}</a>', ts(m), num(sz / 1024, "{:.1f} kB")] for p, m, sz in files]
    return "Izvještaji", ("<h1>Izvještaji</h1><p class=mut>Markdown izvještaji koje moduli pišu u <code>output/</code>.</p>"
                          + tdesc('Klik otvara izvještaj.') + table(["Datoteka", "Izmijenjeno", ("Veličina", "n")], rows, empty="Nema izvještaja."))


def output(rel, qs):
    txt = data.read_output(rel)
    if txt is None:
        return None
    return rel, f'<p><a href="/outputs">← izvještaji</a></p><h1>{esc(rel)}</h1><pre>{esc(txt)}</pre>'


# ---------------- paper trading ----------------

DECISION = {"taken": "good", "take": "good", "buy": "good", "skip": "", "skipped": ""}


def _decision(c):
    d = c.get("decision") or "–"
    return badge(d, DECISION.get(d, "warn" if d.startswith("skip") else "good"))
