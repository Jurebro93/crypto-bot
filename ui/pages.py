"""One function per page. Each returns (title, body_html)."""
import os
import time
from urllib.parse import quote

from ui import data, explain, jobs, labels
from ui.labels import FEATURE_DESC
from ui.html import (tdesc, info, ago, badge, bar, breakdown, esc, ext_icons, ext_token, ext_wallet, filt, mins, num, price, scorecell,
                     short, signed, table, tierb, tlink, ts, usd, verdict, wlink)

ROLE = {
    "early_buyer": ("rani kupac", "kupio među prvima token koji je kasnije narastao (pobjednik)"),
    "smart": ("smart money", "označen kao uspješan trader"),
    "top_trader": ("top trader", "među najboljim traderima tokena"),
    "holder": ("holder", "među top holderima tokena u rug provjeri"),
    "manual": ("ručno", "dodan ručno"),
    "dev": ("dev", "kreator tokena: nikad se ne kopira"),
    "bundler": ("bundler", "kupio u istom bloku kao kreacija (bundle)"),
    "sniper": ("snajper", "kupio u prvih par sekundi: bot, ne kopira se"),
    "funder": ("financijer", "poslao SOL devu ili ranim kupcima"),
    "dust": ("sitni kupac", "kupio premalo (ispod 0.1 SOL) da bi se računao"),
}
SOURCE = {"harvest": "rani kupci pobjedničkih tokena", "hype_learn": "smart walleti iz hype skenera",
          "rug": "rug filter", "manual": "ručno"}

FEATURE = FEATURE_DESC  # kept for older imports


def _sym_map():
    return data.symbols()


# ---------------- wallets ----------------

def wallets(qs):
    """Novčanici: Aktivnost (who just bought or sold) · Za kopiranje (the copy list) · Svi (every scored wallet)."""
    from ui.html import seg
    v = qs.get("v") or ("svi" if qs.get("all") == "1" else "lista" if qs.get("only") == "list" else "")
    sw = seg([("/wallets", "Aktivnost"), ("/wallets?v=lista", "Za kopiranje"), ("/wallets?v=svi", "Svi")],
             "/wallets" + (f"?v={v}" if v else ""))
    if not v:
        from ui import core
        try:
            act = core.wallet_block(n=40, hours=48)
        except Exception as e:  # noqa: BLE001 - a broken block must not take the page down
            act = f"<div class=card>Aktivnost se trenutno ne može prikazati ({esc(type(e).__name__)}).</div>"
        return "Novčanici", "<h1>Novčanici</h1>" + sw + act
    show_all = v == "svi"
    min_score = float(qs.get("min_score", explain.COPY_MIN_SCORE))
    min_closed = int(qs.get("min_closed", explain.COPY_MIN_CLOSED))
    ws = data.wallets(scored_only=not show_all)
    rows = []
    for w in ws:
        s = w["stats"]
        ok, why = explain.shortlist(w, min_score, min_closed)
        if v == "lista" and not ok:
            continue
        if v == "lista":
            rows.append([wlink(w["wallet"]), scorecell(w["copy_score"]), signed(s.get("closed_pnl_sol")),
                         num(s.get("win_rate"), "{:.0%}"), num(s.get("closed")), mins(s.get("median_hold_min")),
                         num(s.get("last_trade_days"), "{:.0f}")])
            continue
        rows.append([wlink(w["wallet"]), tierb(w["tier"]),
                     badge("DA", "good") if ok else badge("ne"),
                     scorecell(w["copy_score"]), scorecell(w["score"]),
                     signed(s.get("closed_pnl_sol")), signed(s.get("roi_on_cost"), "{:+.0%}"),
                     num(s.get("win_rate"), "{:.0%}"), num(s.get("closed")), num(s.get("big_wins")),
                     mins(s.get("median_hold_min")), num(s.get("median_buy_sol"), "{:.2f}"),
                     num(s.get("trades_per_day"), "{:.1f}"), num(s.get("last_trade_days"), "{:.0f}"),
                     num(s.get("early_in_winners")),
                     esc(", ".join(f"{SOURCE.get(k, k)}" for k in w["sources"])),
                     " ".join(badge(labels.wallet_label(l), "bad") for l in w["labels"]),
                     (esc("; ".join(why + (s.get("copy_notes") or []))) or "–", "", "wrap")])
    form = f'<div class=flt>{filt("wt", "Filtriraj adresu, oznaku…")}</div>'
    if v == "lista":
        head = ["Novčanik", ("Copy", "n"), ("PnL SOL", "n"), ("Win", "n"), ("Zatv.", "n"), ("Medijan držanja", "n"),
                ("Neaktivan d", "n")]
    else:
        head = ["Wallet", "Tier", "Na listi", ("Copy", "n"), ("Ocjena", "n"), ("PnL SOL", "n"), ("ROI", "n"),
                ("Win", "n"), ("Zatv.", "n"), ("2x+", "n"), ("Medijan držanja", "n"), ("Kupnja SOL", "n"), ("Trejd/dan", "n"),
                ("Neaktivan d", "n"), ("Rano u pobj.", "n"), "Izvor", "Oznake", ("Zašto nije na listi / napomene", "wrap")]
    since, last, tail = jobs.status("wallets")
    if since:
        state = f"pokrenuto {ago(since)[0]}, još radi"
    elif last:
        state = f"zadnji ručni prolaz završio {ago(last[1])[0]}" + ("" if last[2] == 0 else f", greška (kod {last[2]})")
    else:
        state = "automatski ide svakih 6 h"
    run = (f'<form id=run method=post action=/run/wallets class="flt adm-only"><button {"disabled" if since else ""}>'
           f'Ocijeni novčanike sada</button> <span class=mut>{esc(state)}</span></form>'
           + (f"<details class=adm-only><summary>Zadnji ispis</summary><pre>{esc(tail)}</pre></details>" if tail else ""))
    return "Novčanici", ("<h1>Novčanici</h1>" + sw + form
                         + table(head, rows, "wt", "Još nema novčanika. Bot ih skuplja sam svakih 6 h.") + run)


POS_STATUS = {"closed": "zatvoreno", "open": "otvoreno", "moved": "prebačeno na drugi wallet",
              "no_cost": "bez kupnje (dobio ga je)"}
# stats that are shares (0.38 -> 38%) and ones that are signed SOL amounts
_SHARE = {"win_rate", "roi_on_cost", "median_roi", "top_trade_share", "free_token_ratio"}
_SOL = {"realized_sol", "unrealized_sol", "closed_pnl_sol"}


def _statval(k, v, style):
    if v is True or v is False:
        return ("da" if v else "ne", int(v), "n")
    if k == "style":
        return (esc(style.get(v, v)), 0, "n")
    if not isinstance(v, (int, float)):
        return (esc(v), 0, "n")
    if k in _SHARE:
        return (f"{v * 100:+.0f}%" if k in ("roi_on_cost", "median_roi") else f"{v * 100:.0f}%", v, "n")
    if k in _SOL:
        return (f"{v:+.2f} SOL", v, "n")
    if k == "median_hold_min":
        return mins(v)
    return (f"{v:,.0f}" if float(v).is_integer() or abs(v) >= 100 else f"{v:.1f}" if k != "profit_factor" and k != "median_buy_sol" else f"{v:.2f}", v, "n")


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
        b.append("<p>Oznake: " + " ".join(badge(labels.wallet_label(l), "bad") for l in w["labels"]) +
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
               "history_days": "dana povijesti", "early_in_winners": "rano u pobjednicima", "credits": "Helius kredita",
               "score": "ocjena profitabilnosti", "copy_score": "copy ocjena", "bot": "izgleda kao bot", "style": "stil trgovanja"}
        style = {"swing": "swing (drži satima)", "scalper": "scalper (brzi ulaz/izlaz)", "bot": "bot", "sniper": "snajper", "holder": "holder"}
        b.append(tdesc('Sirove brojke iz kojih su izračunate ocjene gore, iz zadnjeg ocjenjivanja walleta.') + table(["Metrika", ("Vrijednost", "n")],
                       [[esc(lab.get(k, k.replace("_", " "))), _statval(k, v, style)]
                        for k, v in s.items() if not isinstance(v, (list, dict))]))

    pos, priced = _positions(addr)
    if pos:
        op = [p for p in pos.values() if p["status"] == "open"]
        unr = [p["unrealized"] for p in op if p.get("unrealized") is not None]
        b.append("<h2>Pozicije (iz spremljenih trejdova)</h2>" + tdesc(
            "Otvorene pozicije vrednuju se trenutnom cijenom s DexScreenera (besplatno, osvježava se pri svakom "
            "učitavanju stranice, najviše 1 min stara). Nerealizirano = vrijednost preostalih tokena danas minus "
            "ono što su koštali; ROI uključuje i već prodano. Status otvoreno/zatvoreno je po udjelu prodanog; "
            "token bez ikakvog para na DexScreeneru ostaje bez cijene.")
            + (f"<p>Otvoreno: <b>{len(op)}</b> pozicija, s cijenom {len(unr)}, nerealizirano ukupno "
               f"<b>{signed(sum(unr), '{:+.2f}')[0] if unr else '–'}</b> SOL · <a href='?'>osvježi</a></p>" if op else ""))
        b.append(table(["Token", "Status", ("Uloženo SOL", "n"), ("Realizirano SOL", "n"), ("Vrijedi sada SOL", "n"),
                        ("Nerealizirano SOL", "n"), ("ROI", "n"), ("Kupnji", "n"), ("Prodaja", "n"), ("Držao", "n"),
                        "Zadnje"],
                       [[tlink(p["mint"], syms.get(p["mint"])), esc(POS_STATUS.get(p["status"], p["status"])), num(p.get("cost"), "{:.2f}"),
                         signed(p.get("realized"), "{:+.2f}"),
                         num(p.get("value"), "{:.3f}") if p["status"] == "open" else ("", "", ""),
                         signed(p.get("unrealized"), "{:+.3f}") if p["status"] == "open" else ("", "", ""),
                         signed(p.get("roi"), "{:+.0%}") if p["status"] != "open" or p["mint"] in priced else ("–", -9, "n"),
                         num(p["buys"]), num(p["sells"]), mins(p.get("hold_min")), ts(p["last_ts"])]
                        for p in sorted(pos.values(), key=lambda p: (p["status"] != "open", -(p["last_ts"] or 0)))]))
    if pos:
        b.append(_wallet_charts(pos, syms))
    hist = data.wallet_pnl(addr)
    if hist and len(hist) >= 2:
        from ui import charts
        b.append("<h2>Kako mu se mijenjala ocjena</h2>" + tdesc(
            "Ocjena profitabilnosti i copy ocjena (0-100) iz svakog ocjenjivanja. Rastuća linija = novčanik postaje "
            "bolji; pad znači da je zadnjih tjedana gubio ili trguje teže za kopiranje.")
            + charts.line([{"name": "Ocjena profitabilnosti", "pts": [(h["ts"], h["score"]) for h in hist if h["score"] is not None]},
                           {"name": "Copy ocjena", "pts": [(h["ts"], h["copy_score"]) for h in hist if h["copy_score"] is not None]}],
                          "Ocjene kroz vrijeme", "0-100", fmt="num", ymin=0, ymax=100))
    if hist:
        b.append("<h2>Povijest ocjena</h2>")
        b.append(tdesc('Svako ocjenjivanje ovog walleta kroz vrijeme: vidi se popravlja li se ili kvari.') + table(["Vrijeme", ("Realiz.", "n"), ("Nerealiz.", "n"), ("Win", "n"), ("Zatv.", "n"),
                        ("Ocjena", "n"), ("Copy", "n")],
                       [[ts(h["ts"]), signed(h["realized_sol"]), signed(h["unrealized_sol"]),
                         num(h["win_rate"], "{:.0%}"), num(h["closed"]), num(h["score"]), num(h["copy_score"])]
                        for h in reversed(hist)]))
    if sm:
        b.append("<h2>Smart wallet iz hype skenera</h2>")
        b.append(f"<p>Ocjena hype modula: <b>{sm['score']}</b> · pronađen preko: "
                 + ", ".join(tlink(m, syms.get(m)) for m in (sm.get("found_via") or "").split(",") if m) + "</p>")
    return f"Wallet {short(addr)}", "".join(b)


def _wallet_charts(pos, syms):
    """Running realized profit over time and one bar per closed position."""
    from ui import charts
    closed = sorted((p for p in pos.values() if p["status"] == "closed" and p.get("last_ts") and p.get("realized") is not None),
                    key=lambda p: p["last_ts"])
    if len(closed) < 2:
        return ""
    run, pts = 0.0, [(closed[0]["last_ts"] - 1, 0.0)]
    for p in closed:
        run += p["realized"]
        pts.append((p["last_ts"], run))
    nm = lambda p: "$" + str(syms.get(p["mint"]) or p["mint"][:6]).strip()
    wins = sum(1 for p in closed if p["realized"] > 0)
    return ("<h2>Kako je zarađivao kroz vrijeme</h2>" + tdesc(
        f"{len(closed)} zatvorenih pozicija, {wins} u plusu. Gornji graf: ukupna ostvarena zarada u SOL-u nakon svake "
        "prodaje (raste = zarađuje, pada = gubi). Donji: svaka zatvorena pozicija, plavo dobit, crveno gubitak. "
        "Pređi prstom ili mišem preko grafa za točan broj.")
            + charts.line([{"name": "Ostvareno", "pts": pts}], "Ukupna ostvarena zarada (SOL)",
                          "zbroj nakon svake zatvorene pozicije", fmt="sol", base=0, base_label="nula")
            + charts.bars([(p["last_ts"], nm(p), p.get("roi")) for p in closed[-200:]], "Svaka zatvorena pozicija",
                          "povrat na uloženo", fmt="pct"))


def _positions(addr):
    """({mint: position}, {mint: live SOL price}) with open positions valued at the DexScreener price."""
    rows = data.wallet_trades(addr)
    if not rows:
        return {}, {}
    try:
        from wallets import pnl
        pos = pnl.positions(rows)
        prices = {}
        open_ = [m for m, p in pos.items() if p.get("status") == "open"]
        if open_:
            try:
                from wallets import prices as wprices
                prices = wprices.sol_prices(open_)
            except Exception:
                prices = {}
            if prices:
                pos = pnl.positions(rows, prices)
        return {m: p for m, p in pos.items() if p.get("status") in ("open", "closed")}, prices
    except Exception:
        return {}, {}


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
    from ui import league as _league, quickbuy
    dsym, dlist = quickbuy.dugo_info(mint)
    sym = sym or dsym
    # top to bottom: name + Šansa, rug warnings, one-sentence verdict, Za / Protiv, copy, outside sites; then the
    # layers behind taps; the Natjecanje buy box (bonus) last
    actions = (f"<p>{quickbuy.copy_btn(mint, label='Kopiraj adresu ' + short(mint), big=True)}</p>"
               f"<div class=ext-big>{ext_icons(mint, url)}</div>")
    b = [_league._err(qs) + ('<p><a href="/natjecanje#moj"><b>Vidi svoj račun na Natjecanju →</b></a></p>' if qs.get("ok") else "")]
    natj = ""
    locked = None
    if not (ev or sigs or rugs):
        b.insert(0, f"<h1>{esc(sym or short(mint))}</h1>")
        b.append((f'<p class=mut>Na popisu <a href="/dugorocno">{esc(dlist)}</a>.</p>' if dlist else
                  "<p class=mut>Ovaj token nije ni u jednoj analizi.</p>") + actions)
        b.append(quickbuy.token_box(mint, sym))
    else:
        from rugfilter import archive, collapse
        arch = archive.get(mint, data.HYPE_DB)
        col = None if arch else collapse.check(collapse.peaks(data.HYPE_DB, [mint]).get(mint))
        if arch:
            import time as _t
            b.append(f'<div class=card style="border-color:var(--bad)"><b class=neg>💀 Rugan i izbačen iz praćenja:</b> '
                     f'{esc(arch["reason"])} ({esc(archive.KIND_HR.get(arch["kind"], arch["kind"]))}). '
                     f'Izbačen {_t.strftime("%d.%m. %H:%M", _t.gmtime(arch["archived_ts"]))} UTC: bot ga više ne prati i ne troši '
                     'API kredite na njega, a čuva samo podatke s ulaza da iz njih uči kako izgleda rug. Kupnja je zaključana.</div>')
        if col:
            b.append(f'<div class=card style="border-color:var(--bad)"><b class=neg>💀 Rugan:</b> {esc(col["text"])}. '
                     'Maknut je s prijedloga i kupnja u natjecanju je zaključana.</div>')
        if arch or col:
            locked = "token je rugan"
        from topcheck import store as topstore
        from ui import topcheckui
        top = topstore.read_all().get(mint)
        if top and top.get("verdict") == "pao" and not locked:
            locked = "token je pao na obaveznom rug checku"
        topbox = topcheckui.token_box(top)
        natj = quickbuy.token_box(mint, sym, locked)
        from ui import narrative
        b.append(narrative.verdict_html(mint))
        tiers = tier_html(mint)

    # summary: one card with the verdict numbers, then "za" / "protiv" from the confidence parts
    sigs_asc = sigs[::-1]
    sig = sigs[0] if sigs else None
    from ui import confidence, evidence, sansa
    _, det = evidence.details(mint)
    pc = data.paper_candidates(mint)
    cand = pc[0] if pc else None
    cs = evidence.checks(mint, sig, det, rugs[0] if rugs else None, ev, cand)
    role = "canonical" if any(e["role"] == "canonical" for e in ev) else None
    mk = (rugs[0]["data"].get("market") if rugs else None) or {}
    conf, parts = confidence.score(sig["score"] if sig else None, (data.js(sig["features"], {}) or {}) if sig else {}, det,
                                   rugs[0]["verdict"] if rugs else None, role,
                                   (sig or {}).get("liquidity") or mk.get("liquidity"), (sig or {}).get("mcap") or mk.get("mcap"))
    sn, an, pr, pa = sansa.score(conf, cs)
    best = max(ev, key=lambda e: e["score"] or 0) if ev else None
    if ev or sigs or rugs:
        b.insert(0, f"<div class=tokhead><h1>{esc(sym or short(mint))}</h1><div class=sn><small>Šansa {info('Šansa')}</small>"
                    f"<b>{sn}</b></div></div>")
    za = [t for p_, t in parts if p_ > 0]
    protiv = [t for p_, t in parts if p_ < 0]
    if ev or sigs or rugs:
        if za or protiv:
            b.append("<div class=grid style='grid-template-columns:1fr 1fr;gap:12px'>"
                     "<div class=card><b style='color:var(--good)'>Za</b><ul class=r>"
                     + "".join(f"<li class=good>{esc(t)}</li>" for t in za[:5]) + ("<li class=mut>ništa izmjereno</li>" if not za else "")
                     + "</ul></div><div class=card><b style='color:var(--bad)'>Protiv</b><ul class=r>"
                     + "".join(f"<li class=bad>{esc(t)}</li>" for t in protiv[:5]) + ("<li class=mut>nema zabilježenih rizika</li>" if not protiv else "")
                     + "</ul></div></div>")
        b.append(actions + topbox)
        b.append("<h2>Brojke</h2><div class=grid>")
        for v, l in [(f"<b>{sn}</b>", "šansa za skok"), (conf, "confidence"),
                     (f"{an}/{sansa.N} {sansa.dots_html(cs)}", "slojeva analizirano"),
                     (max(s["score"] or 0 for s in sigs) if sigs else "–", "hype max"),
                     (verdict(rugs[0]["verdict"]) if rugs else "–", "rug presuda"),
                     (best["score"] if best else "–", "event ocjena")]:
            b.append(f"<div class=stat><div class=v>{v}</div><div class=l>{l}</div></div>")
        b.append("</div>" + tiers)
    opened = qs.get("sve") == "1"
    b.append(f"<h2>Slojevi</h2><p class=mut style='font-size:12px'><a href='?sve={'0' if opened else '1'}'>"
             f"{'Sklopi sve' if opened else 'Otvori sve'}</a></p>")

    def sec(sid, title, summary, force=False):
        return (f"<details id={sid}{' open' if opened or force else ''}><summary><b>{title}</b> "
                f"<span class=mut>· {summary}</span></summary>")

    from ui import kol
    kol_html = kol.token_section(mint)
    if kol_html:
        b.append(sec("kol", "KOL sloj", "tko ga je zvao na X-u i što je cijena napravila") + kol_html + "</details>")

    # layer 1: event
    ev_sum = (f"{esc(best['event'])} · {'pravi' if role else 'kopija'} · ocjena {best['score']}" if best else "nije vezan uz event")
    b.append(sec("event", "1. Event sloj", ev_sum))
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
    b.append("</details>")

    # layer 2: hype
    hy_sum = (f"zadnja ocjena {sigs[0]['score']}, max {max(x['score'] or 0 for x in sigs)}, {len(sigs)} signala" if sigs
              else "hype skener ga nije uhvatio")
    b.append(sec("hype", "2. Hype sloj", hy_sum))
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
            rows.append([esc(labels.feat(k)), (f"{val:.2f}", val, "n"), (f"{wt:g}", wt, "n"), (f"{pts:.1f}", pts, "n"),
                         bar(pts, 100 * wt / tot if wt else 1), (f'<span class=mut>{esc(FEATURE.get(k, ""))}</span>', "", "wrap")])
        b.append(f"<p>Zadnji signal {ts(last['ts'])[0]} UTC, ocjena <b>{last['score']}</b>, otkud je došao: "
                 f"{esc(labels.sources(last['sources']))}. Ocjena = Σ(signal × težina) / Σ težina izmjerenih signala × 100; "
                 f"provjera koja nije rađena (npr. X buzz) ne ulazi ni u zbroj ni u nazivnik.</p>")
        b.append(tdesc('Raspis zadnje hype ocjene: koliko je svaki signal izmjeren (0-1), koliko vrijedi i koliko je bodova donio.') + table(["Signal", ("Vrijednost 0-1", "n"), ("Težina", "n"), ("Doprinos", "n"), "", ("Što mjeri", "wrap")], rows))
        b.append(f"<p>Zbroj doprinosa: <b>{sum(r[3][1] for r in rows):.1f}</b> <span class=mut>(spremljeno {last['score']})</span></p>")
        snaps = data.hype_snapshots(mint)
        if len(snaps) > 1:
            b.append("<h3>Cijena od prvog signala</h3>" + _spark(snaps, sigs_asc[0]["price"]))
        b.append("<h3>Svi signali</h3>")
        b.append(tdesc('Svaki put kad ga je hype skener zabilježio, s cijenom i izvorima u tom trenutku.') + table(["Vrijeme", ("Ocjena", "n"), ("Cijena", "n"), ("Mcap", "n"), ("Likvidnost", "n"), "Izvori"],
                       [[ts(s["ts"]), scorecell(s["score"]), price(s["price"]), usd(s["mcap"]),
                         usd(s["liquidity"]), (esc(labels.sources(s["sources"])), "", "wrap")] for s in sigs[:200]]))
    b.append("</details>")

    # layer 3: rug
    rg_sum = (f"{esc(rugs[0]['verdict'])}, ocjena {rugs[0]['score'] if rugs[0]['score'] is not None else '–'}, "
              f"{len(rugs[0]['data'].get('hard_fails', []))} tvrdih, {len(rugs[0]['data'].get('flags', []))} zastavica" if rugs
              else "nije provjeren")
    b.append(sec("rug", "3. Rug filter", rg_sum, force=bool(rugs and rugs[0]["verdict"] in ("ODBAČEN", "VISOK RIZIK"))))
    if not rugs:
        b.append("<p class=mut>Nije provjeren rug filterom: puna provjera ide samo tokenima koji prođu prve razine analize.</p>")
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
                                                     [[wlink(x["wallet"]), num(x.get("pct"), "{:.1f}"),
                                                       badge("da", "bad") if x.get("insider") else "ne"] for x in top]))
        md = os.path.join("rug", f"{mint}.md")
        if data.read_output(md) is not None:
            b.append(f'<p><a href="/outputs/{quote(md)}">Puni rug izvještaj</a></p>')
        if len(rugs) > 1:
            b.append("<h3>Ranije provjere</h3>" + tdesc('Prijašnje rug provjere istog tokena.') + table(["Vrijeme", "Presuda", ("Ocjena", "n")],
                                                        [[ts(x["checked_at"]), verdict(x["verdict"]), num(x["score"])] for x in rugs[1:]]))
    b.append("</details>")

    if pc:
        c = pc[0]
        b.append(sec("paper", "4. Demo trading", f"{esc(labels.decision(c['decision']))} · {esc(labels.reason(c['reason']))}"))
        b.append(f"<div class=card>{_decision(c)} {esc(labels.reason(c['reason']))} <span class=mut>· {esc(labels.source(c['origin']))} · "
                 f"{ts(c['first_ts'])[0]} UTC</span>" + "".join(f"<div class=mut>rug: {esc(x)}</div>" for x in c["rug_flags"]))
        for t in data.paper_trades(mint):
            b.append(f"<p>Trejd #{t['id']}: {'otvoren' if t['status'] == 'open' else 'zatvoren'}, povrat {(t['ret'] or 0):+.0%}, "
                     f"max {(t['max_ret'] or 0):+.0%}" + (f", izlaz: {esc(labels.exit_reason(t['exit_reason']))}" if t['exit_reason'] else "") + "</p>")
        b.append("</div></details>")

    # pulse: what the token did after it earned attention (retained in every scan)
    pl = data.token_pulse(mint)
    if pl:
        from hype import pulse as hpulse
        sf = hpulse.strength(pl)
        hold = [x for x in pl if x["holders"]]
        b.append(sec("puls", "6. Puls (osvježavanje svaka 2 min)",
                     (hpulse.describe(sf) or f"{len(pl)} očitanja") + (f" · holderi {hold[-1]['holders']}" if hold else "")))
        b.append(tdesc("Očitanja za token koji je stigao do razine 1: ostaje u svakom skenu dok god je zanimljiv, pa su ocjena "
                       "i snaga svježi. Najnovije prvo; holderi iz Heliusa svakih 30 min ili s pump.fun ploče.")
                 + table(["Vrijeme", ("Mcap", "n"), ("Vol 5 min", "n"), ("Vol 1 h", "n"), ("Kupnje 1 h", "n"), ("Prodaje 1 h", "n"),
                          ("Holderi (puls)", "n")],
                         [[ts(x["ts"]), usd(x["mcap"]), usd(x["vol_m5"]), usd(x["vol_h1"]), num(x["buys_h1"]), num(x["sells_h1"]),
                           (f"{x['holders']} <span class=mut>{esc(x['holders_src'] or '')}</span>", x["holders"], "n") if x["holders"] else num(None)]
                          for x in pl[::-1][:48]]))
        b.append("</details>")

    # wallets on this token
    sg = data.sightings(token=mint)
    b.append(sec("walleti", "5. Walleti viđeni na ovom tokenu", f"{len(sg)} iz registra"))
    wmap = {w["wallet"]: w for w in data.wallets(scored_only=False)}
    b.append(tdesc('Walleti iz registra koji su kupovali ovaj token, s ulogom (rani kupac, top trader…) i ocjenom.') + table(["Wallet", "Uloga", "Izvor", ("SOL", "n"), ("Copy", "n"), "Tier", "Oznake"],
                   [[wlink(x["wallet"]), esc(ROLE.get(x["role"], (x["role"],))[0]), esc(SOURCE.get(x["source"], x["source"])),
                     num(x["sol_in"], "{:.2f}"), num((wmap.get(x["wallet"]) or {}).get("copy_score")),
                     tierb((wmap.get(x["wallet"]) or {}).get("tier")),
                     " ".join(badge(l, "bad") for l in (wmap.get(x["wallet"]) or {}).get("labels", []))] for x in sg],
                   empty="Nijedan wallet nije zabilježen za ovaj token."))
    b.append("</details>")
    if natj:
        b.append("<h2>Natjecanje</h2>" + natj)
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
               + "".join(f"<div>{esc(n)} {info(n)}: <b>{p:.1f}</b>/{m} <span class=mut>{esc(x)}</span></div>" for n, p, m, x in parts)
               + "</details>")
        rows.append([(esc(e["date"]), e["date"], ""), esc(labels.kind(e["kind"])),
                     (f'<a href="{esc(e["url"])}" target=_blank>{esc(e["title"])}</a>' if e.get("url") else esc(e["title"]), e["title"], "wrap"),
                     scorecell(e["hype"]), num(e.get("token_likelihood"), "{:.2f}"),
                     esc(" ".join(e["keywords"])), esc(labels.event_source(e["source"])),
                     (tl or "–", len(toks), "wrap"), (det, "", "wrap")])
    return table(["Datum", "Vrsta", ("Event", "wrap"), ("Hype", "n"), ("Šansa za token", "n"), "Ključne riječi",
                  "Izvor", ("Tokeni (★ = pravi)", "wrap"), ("Zašto ta ocjena", "wrap")], rows, tid,
                 "Još nema evenata. Bot osvježava kalendar sam svakih 6 h.")


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
    syms = data.symbols()
    rows = [[f'<a href="/outputs/{quote(p)}">{esc(labels.report_name(p, syms))}</a>', ts(m)] for p, m, sz in files]
    return "Izvještaji", ("<h1>Izvještaji</h1><p class=mut>Izvještaji koje bot sam piše: dnevni pregled demo tradinga, "
                          "kalendar, rug provjere, copy lista walleta.</p>"
                          + tdesc('Klik otvara izvještaj.') + table([("Izvještaj", "wrap"), "Napisan"], rows, empty="Još nema izvještaja."))


def output(rel, qs):
    txt = data.read_output(rel)
    if txt is None:
        return None
    name = labels.report_name(rel, data.symbols())
    return name, (f'<p><a href="/outputs">← izvještaji</a></p><h1>{esc(name)}</h1>'
                  f'<pre style="white-space:pre-wrap">{esc(labels.plain_md(txt))}</pre>')


# ---------------- paper trading ----------------

DECISION = {"taken": "good", "take": "good", "buy": "good", "skip": "", "skipped": ""}


def _decision(c):
    d = c.get("decision") or "–"
    return badge(labels.decision(d), DECISION.get(d, "warn" if d.startswith("skip") else "good"))
