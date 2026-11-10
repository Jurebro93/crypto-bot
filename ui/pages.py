"""One function per page. Each returns (title, body_html)."""
import datetime as dt
import os
import time
from urllib.parse import quote

from ui import data, explain, jobs, labels
from eventpick import load as pickload, score as pickscore
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

def autopilot_marks(now=None):
    """9.11. (audit P44): what the bot copies by, next to the page's copy_score: the proven-twice list
    (wallets/dokazani.latest: wallet -> row with as_of, bags), the wallets the real-money account follows
    (ui/pravitrade.followed_wallets) and the Autopilot's 14-day wallet stats (ui/autopilot.wallet_recs). Read-only;
    every source may be missing (empty until the first run after a deploy), the page then shows "ne" / dashes."""
    proven, followed, recs, as_of = {}, set(), {}, None
    try:
        from wallets import dokazani
        for r in dokazani.latest():
            proven[r["wallet"]] = r
            as_of = max(as_of or 0, r.get("as_of") or 0) or as_of
    except Exception:  # noqa: BLE001
        pass
    try:
        from ui import pravitrade
        followed = set(pravitrade.followed_wallets())
    except Exception:  # noqa: BLE001
        pass
    try:
        from ui import autopilot
        recs = {r["wallet"]: r["s"] for r in (autopilot.wallet_recs(now) or {}).get(14) or []}
    except Exception:  # noqa: BLE001
        pass
    return {"proven": proven, "followed": followed, "recs": recs, "as_of": as_of}


def _mark_cells(w, marks):
    """Three cells: Dokazani dvaput · Prati Autopilot · Autopilot 14 d (ROI, win, closed of its chain buys)."""
    pr = marks["proven"].get(w)
    bags = f' <span class=mut title="otvorenih gubitnika koje nije zatvorio">{pr["bags"]} bagova</span>' if pr and pr.get("bags") else ""
    yes_p = (badge("DA", "good") + bags, 1, "n") if pr else (badge("ne"), 0, "n")
    yes_f = (badge("DA", "good"), 1, "n") if w in marks["followed"] else (badge("ne"), 0, "n")
    r = marks["recs"].get(w)
    rec = ((f'{signed(r["roi"], "{:+.0%}")[0]} · win {r["win"]:.0%} · {r["closed"]} zatv.', r["roi"], "n") if r
           else ("–", -1e18, "n mut"))
    return [yes_p, yes_f, rec]


MARK_HEAD = [("Dokazani dvaput", "n"), ("Prati Autopilot", "n"), ("Autopilot 14 d", "n")]


def wallets(qs):
    """Novčanici: Aktivnost (who just bought or sold) · Za kopiranje (the copy list) · Svi (every scored wallet)."""
    from ui.html import seg
    # 7.11. (Jure): the copy list with its verdict opens first; the raw activity feed (addresses) goes last
    v = qs.get("v") or ("svi" if qs.get("all") == "1" else "lista")
    sw = seg([("/wallets", "Za kopiranje"), ("/wallets?v=svi", "Svi"), ("/wallets?v=aktivnost", "Aktivnost")],
             "/wallets" + (f"?v={v}" if v != "lista" else ""))
    # 10.11. (Jure, prijedlog 4.6 i 5.1): "Prijedlog za danas" (prijedlog.box) lives only on Pregled; Novčanici
    # start with their own list
    top = ""
    if v == "aktivnost":
        from ui import core
        try:
            act = core.wallet_block(n=40, hours=48)
        except Exception as e:  # noqa: BLE001 - a broken block must not take the page down
            act = f"<div class=card>Aktivnost se trenutno ne može prikazati ({esc(type(e).__name__)}).</div>"
        return "Novčanici", "<h1>Novčanici</h1>" + top + sw + act
    show_all = v == "svi"
    from ui import preporuka
    try:   # 4.11.: the verdict first, the table after ("what do I do with this"); 7.11.: folded under the new box
        box = preporuka.wallets_box(data.wallets(scored_only=True), preporuka.copies_from_strat())
    except Exception as e:  # noqa: BLE001
        box = f"<div class=card>Preporuka se trenutno ne može složiti ({esc(type(e).__name__)}).</div>"
    box = f"<details class=more><summary>Detalji preporuke: uvjeti, ljestvica +15/+30/+50 %, drugi izbor</summary>{box}</details>"
    min_score = float(qs.get("min_score", explain.COPY_MIN_SCORE))
    min_closed = int(qs.get("min_closed", explain.COPY_MIN_CLOSED))
    ws = data.wallets(scored_only=not show_all)
    marks = autopilot_marks()   # 9.11. (audit P44): the bot's own lists next to the page's copy_score
    # 9.11. (audit P44): "Za kopiranje" puts the wallets the Autopilot actually copies by (proven twice, followed) on
    # top of the copy_score order, so the hand pick and the bot's pick are the same list; the other views keep theirs
    if v == "lista":
        ws = sorted(ws, key=lambda w: (w["wallet"] in marks["proven"], w["wallet"] in marks["followed"]), reverse=True)
    rows = []
    for w in ws:
        s = w["stats"]
        ok, why = explain.shortlist(w, min_score, min_closed)
        if v == "lista" and not ok:
            continue
        if v == "lista":
            rows.append([wlink(w["wallet"]), *_mark_cells(w["wallet"], marks), scorecell(w["copy_score"]), signed(s.get("closed_pnl_sol")),
                         num(s.get("win_rate"), "{:.0%}"), num(s.get("closed")), mins(s.get("median_hold_min")),
                         num(s.get("last_trade_days"), "{:.0f}")])
            continue
        rows.append([wlink(w["wallet"]), tierb(w["tier"]), *_mark_cells(w["wallet"], marks),
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
        head = ["Novčanik", *MARK_HEAD, ("Copy", "n"), ("PnL SOL", "n"), ("Win", "n"), ("Zatv.", "n"), ("Medijan držanja", "n"),
                ("Neaktivan d", "n")]
    else:
        head = ["Wallet", "Tier", *MARK_HEAD, "Na listi", ("Copy", "n"), ("Ocjena", "n"), ("PnL SOL", "n"), ("ROI", "n"),
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
    # data time, not render time: when the proven list was computed (wallets/dokazani, 3-h cycle) and what the marks mean
    n_pf = sum(1 for w in ws if w["wallet"] in marks["proven"] or w["wallet"] in marks["followed"])
    legend = ('<p class=mut style="font-size:13px"><b>Dokazani dvaput</b> = prošao wallets/dokazani (prije i poslije reza'
              + (f"; lista iz {ago(marks['as_of'])[0]}" if marks["as_of"] else "; lista još nije izračunata") + "), "
              "<b>Prati Autopilot</b> = račun pravog novca ga prati ili je dokazan (to su novčanici čije kupnje bot broji kao "
              "poziv), <b>Autopilot 14 d</b> = ROI/win/zatvoreno na njegovim kupnjama u 14 dana (Autopilot preporuke). "
              f"Copy ocjena je zasebno bodovanje ove stranice; u ovom pogledu {n_pf} novčanika ima oznaku bota.</p>")
    return "Novčanici", ("<h1>Novčanici</h1>" + top + sw + box + form + legend
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
    t = data.token_tier(mint)   # 10.11. (audit S2): one row by key, not the whole table
    if not t:
        return ""
    t0 = {"prolaz": badge("T0 prošao", "good"), "pad": badge("T0 pao", "bad"), "nije": badge("izvan skena")}.get(t.get("t0"), "")
    put = ""
    if t.get("put_skokovitost") is not None:
        put = (f" · put do mcapa: brzina {t['put_brzina']:+.2f}/h, skokovitost {t['put_skokovitost']:.0%}, "
               f"zadržavanje {t['put_zadrzavanje']:.0%}")
    return (f"<p>Slojevita analiza: {razinab(t.get('razina'))} {klasab(t.get('klasa'))} {t0} "
            f"<span class=mut>{esc(t.get('t0_razlog') or '')}{esc(put)} · potrošeno ~{t.get('credits') or 0} Helius kredita</span></p>")


# 10.11. (Jure: "Ostalo mi se sviđa", prijedlog 4.3, maketa token.html): the token page as a detail page in the calm
# language. Top like Apple Dionice (name and short address left, mcap and 24 h right), the mcap chart with the calls as
# dots (ui/tokenchart), one verdict panel (pouzdanost, the same number as on the list, šansa next to it; one sentence;
# one "Za / Protiv" line), Kupi as a sheet and Kopiraj adresu, the outside sites as words, then Tržište, Tko ga je
# zvao, Smart walleti, Provjera ruga, and "Kako je dobio ocjenu" (full reading, the seven layers, live pulse) one tap
# away. Every number of the old page is still here; nothing is computed differently.

TOKEN_CSS = """<style>
.tkp-back{display:inline-flex;align-items:center;gap:7px;color:var(--acc);font-size:17px;padding:8px 0 0;text-decoration:none}
.tkp-back::before{content:"";width:9px;height:9px;border-left:2px solid var(--acc);border-bottom:2px solid var(--acc);transform:rotate(45deg);margin-left:3px}
.tkp-dh{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;padding:12px 0 0}
.tkp-dh>div{min-width:0}.tkp-dh .ms-h1{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tkp-r{text-align:right;flex:none}
.tkp-px{font-size:22px;font-weight:700;letter-spacing:-.02em;white-space:nowrap;font-variant-numeric:tabular-nums}
.tkp-s{font-size:15px;color:var(--mut);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tkp-cp{all:unset;cursor:pointer;color:var(--mut)}.tkp-cp:hover{color:var(--fg)}
.tkp-ci{display:inline-block;width:11px;height:13px;border:1.6px solid currentColor;border-radius:3px;margin:0 2px -2px 6px;box-shadow:2px -2px 0 -.5px #fff,3px -3px 0 0 currentColor}
.tkp-msg{border:1px solid var(--line);border-radius:14px;padding:10px 14px;margin:12px 0 0;font-size:15px}
.tkp-msg.neg{border-color:var(--bad)}
.tkp-v .ms-name{margin-top:2px}.tkp-v .ms-name+p{margin-top:6px}
.tkp-go{margin:12px 0 0;padding:11px 0 0;border-top:1px solid var(--line2);font-size:15px;color:var(--mut);line-height:1.4}
.tkp-go b{color:var(--fg);font-weight:600}
.tkp-btns{display:flex;gap:10px;margin:16px 0 0}
.tkp-btn{all:unset;box-sizing:border-box;flex:1;display:block;text-align:center;border-radius:12px;padding:13px 0;font-size:17px;font-weight:600;cursor:pointer}
.tkp-btn.p{background:var(--fg);color:#fff}.tkp-btn.s{background:var(--soft);color:var(--fg)}
.tkp-btn.p[aria-disabled=true]{background:var(--line2)}
.tkp-links{font-size:15px;color:var(--mut);margin:12px 0 0;line-height:1.6}.tkp-links a{color:var(--acc);text-decoration:none}
.tkp-chg{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:14px;margin:12px 0 0;overflow:hidden}
.tkp-chg div{padding:9px 0;text-align:center}.tkp-chg div+div{border-left:1px solid var(--line)}
.tkp-chg span{display:block;font-size:13px;color:var(--mut)}.tkp-chg b{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.tkp-kv{display:grid;grid-template-columns:1fr 1fr;column-gap:24px;margin:4px 0 0}
.tkp-kv div{padding:11px 0;border-bottom:1px solid var(--line);min-width:0}
.tkp-kv span{display:block;font-size:13px;color:var(--mut)}.tkp-kv b{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.tkp .pos{color:var(--good)}.tkp .neg{color:var(--bad)}
.tkp-h2s{font-size:15px;font-weight:400;letter-spacing:0;color:var(--mut)}
.tkp-state{font-size:15px;color:var(--mut);margin:8px 0 2px}
.tkp-chk{display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:46px;border-bottom:1px solid var(--line);font-size:17px}
.tkp-chk:last-child{border-bottom:0}.tkp-chk span{font-size:15px;color:var(--mut);text-align:right}
.tkp-chk span.warn{color:var(--warn)}.tkp-chk span.bad{color:var(--bad)}
.tkp-d>summary{list-style:none;cursor:pointer}.tkp-d>summary::-webkit-details-marker{display:none}
.tkp-d[open]>summary .ms-chev{transform:rotate(135deg)}
.tkp-d>.tkp-in{padding:4px 0 18px;font-size:15px;line-height:1.5}
.tkp-d:not(:last-child)>summary.ms-row{border-bottom:1px solid var(--line)}
.tkp-list{list-style:none;margin:6px 0;padding:0}.tkp-list li{padding:3px 0}
.tkp-all{margin:6px 0 0}.tkp-all>summary{font-size:15px;color:var(--acc)}
.tkp-g2>section>.ms-h2:first-child{margin-top:40px}
@media(min-width:900px){
 .tkp-g2{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);column-gap:44px;align-items:start}
 .tkp-g2.a .ms-panel{margin-top:16px}
 .tkp-kv{grid-template-columns:1fr 1fr 1fr}
}
</style>"""

TOKEN_JS = """<script>(()=>{const sh=document.getElementById('qb-sheet');
document.addEventListener('click',e=>{const c=e.target.closest('[data-copy]');if(c){e.preventDefault();const m=c.dataset.copy,
 t=c.querySelector('.tkp-cl')||c,o=t.textContent,done=()=>{t.textContent='Kopirano';setTimeout(()=>t.textContent=o,1500)};
 (navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject()).then(done,()=>prompt('Kopiraj adresu:',m));return}
 const b=e.target.closest('[data-buy]');if(b&&sh&&sh.showModal){e.preventDefault();sh.showModal();return}
 if(sh&&(e.target===sh||e.target.closest('#qb-sheet [data-close]')))sh.close();
 const a=e.target.closest('a[href^="#"]');if(a){const d=document.getElementById(a.getAttribute('href').slice(1));if(d&&d.tagName==='DETAILS')d.open=true}});
const d=location.hash&&document.getElementById(location.hash.slice(1));if(d&&d.tagName==='DETAILS')d.open=true})()</script>"""

DEX_NAME = {"raydium": "Raydium", "pumpswap": "PumpSwap", "meteora": "Meteora", "orca": "Orca", "launchlab": "LaunchLab"}
TOKEN_LINKS = (("DexScreener", "dexscreener.com"), ("Birdeye", "birdeye.so"), ("GMGN", "gmgn.ai"), ("Solscan", "solscan.io"),
               ("X", "x.com"))


def _short_addr(a):
    return f"{a[:4]}…{a[-4:]}" if a and len(a) > 10 else (a or "")


def _price_txt(p):
    """0.000412 -> "0,000412 $" (three significant digits), 1.234 -> "1,23 $"."""
    import math
    from ui.redak import NBSP, num
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    dec = 2 if p >= 1 else max(2, -math.floor(math.log10(p)) + 2)
    return f"{num(p, min(dec, 12))}{NBSP}$"


def _age_txt(ms):
    if not ms:
        return None
    d = time.time() - ms / 1000
    return f"{int(d // 3600)} h" if d < 2 * 86400 else f"{int(d // 86400)} d"


def _token_status(mint):
    """The token's hype/tokenstatus row by its key (the page used to read the whole table for one row)."""
    rows = data.q(data.HYPE_DB, "SELECT * FROM token_status WHERE token=?", (mint,))
    return rows[0] if rows else None


def _zone_mcap0(mint, now):
    """mcap at the moment today's suggestion (Pregled) showed this token, or None (prijedlog_log, by key)."""
    rows = data.q(data.HYPE_DB, "SELECT mcap0 FROM prijedlog_log WHERE token=? AND ts>=? ORDER BY ts DESC LIMIT 1",
                  (mint, int(now - 86400)))
    return rows[0]["mcap0"] if rows and rows[0].get("mcap0") else None


def _token_links(mint, url=None, dead=False):
    from ui.html import EXT_SITES
    from urllib.parse import quote as _q
    mk = {dom: f for _, dom, f in EXT_SITES}
    out = []
    for name, dom in TOKEN_LINKS:
        href = url if (dom == "dexscreener.com" and url and not dead) else (
            f"https://dexscreener.com/search?q={_q(mint)}" if dom == "dexscreener.com" and dead else mk[dom](_q(mint)))
        out.append(f'<a href="{esc(href)}" target=_blank rel=noopener>{esc(name)}</a>')
    return " · ".join(out)


def _market_html(pair, st, top, rug, det, pl, url):
    """Tržište (like DexScreener): 5 min, 1 h, 6 h, 24 h in one strip, then price, liquidity, volume, buys / sells,
    holders, top 10, age and where it trades. Live pair first (DexScreener, 60 s cache), then what the bases know."""
    from ui import redak as R
    b = [R.section("Tržište", "DexScreener" if url else None, url)]
    ch = (pair or {}).get("priceChange") or {}
    if pair and any(ch.get(k) is not None for k in ("m5", "h1", "h6", "h24")):
        b.append('<div class="tkp-chg">' + "".join(
            f'<div><span>{lab}</span><b class="{R.tone(ch.get(k))}">{esc(R.pct(ch.get(k)))}</b></div>'
            for k, lab in (("m5", "5 min"), ("h1", "1 h"), ("h6", "6 h"), ("h24", "24 h"))) + "</div>")
    last = pl[-1] if pl else {}
    tx = ((pair or {}).get("txns") or {}).get("h1") or {}
    rc = (top or {}).get("rc") or {}
    pf = (det or {}).get("pumpfun") or {}
    holders = rc.get("holders") or next((x["holders"] for x in reversed(pl or []) if x.get("holders")), None) or pf.get("holders")
    t10 = rc.get("top10")
    if t10 is None:
        t10 = (rug or {}).get("top10_pct")
    if t10 is None and pf.get("top10HoldersPercent") is not None:
        v = pf["top10HoldersPercent"]
        t10 = v / 100 if v > 100 else v
    dex = (pair or {}).get("dexId") or (st or {}).get("dex_id")
    kv = [("Cijena", _price_txt((pair or {}).get("priceUsd") or (st or {}).get("price"))),
          ("Likvidnost", R.usd(((pair or {}).get("liquidity") or {}).get("usd") or (st or {}).get("liq") or None)),
          ("Volumen 1 h", R.usd(((pair or {}).get("volume") or {}).get("h1") or last.get("vol_h1") or None)),
          ("Kupnje / prodaje 1 h", f'{R.num(tx.get("buys"))} / {R.num(tx.get("sells"))}' if tx else
           (f'{R.num(last.get("buys_h1"))} / {R.num(last.get("sells_h1"))}' if last.get("buys_h1") is not None else None)),
          ("Holderi", R.num(holders) if holders else None),
          ("Top 10 holdera", R.pct(t10, sign=False) if t10 is not None else None),
          ("Starost", _age_txt((pair or {}).get("pairCreatedAt"))),
          ("Bondan", None if not dex else ("ne, još na krivulji" if dex == "pumpfun" else f"da, {DEX_NAME.get(dex, dex)}"))]
    kv = [(k, v) for k, v in kv if v and v != R.DASH and v != "– / –"]
    if kv:
        b.append('<div class="tkp-kv">' + "".join(f"<div><span>{esc(k)}</span><b>{esc(v)}</b></div>" for k, v in kv) + "</div>")
    if st and not st.get("has_pair"):
        b.append(R.hint("DexScreener više nema par za ovaj token (nema trgovanja)."
                        + (f" GeckoTerminal: vrijednost {R.usd(st['gt_fdv'])}, promet 24 h {R.usd(st.get('gt_vol24') or 0)}."
                           if st.get("gt_fdv") else "")))
    elif not kv:
        b.append(R.hint("Tržišni podaci za ovaj token trenutno nisu dostupni."))
    s = (top or {}).get("state") or {}
    if s.get("advice"):
        lab = (s.get("label") or "").split(" ", 1)[-1] if s.get("label") else ""
        b.append(R.hint(f"{lab}: {s['advice']}" if lab else s["advice"]))
    return "".join(b)


def _callers_html(mint, mcap_now, now):
    """Tko ga je zvao: the four newest first calls with the one influencer verdict (ui/kolsummary), the mcap at the
    call and the rise since; "Svih N" opens the full table of posts and KOL wallet trades (ui/kol.token_section)."""
    import json
    from ui import redak as R
    from ui import tokenchart
    cs = tokenchart.calls(mint)
    try:
        from ui import kol as _kol
        full = _kol.token_section(mint)
    except Exception:  # noqa: BLE001
        full = ""
    head = R.section("Tko ga je zvao", f"Svih {len(cs)}" if len(cs) > 4 or (full and cs) else None, "#pozivi")
    if not cs:
        return head + R.hint("Nitko od praćenih računa ga nije objavio.") + (
            f'<details class="tkp-all" id="pozivi"><summary>Kupnje KOL novčanika</summary>{full}</details>' if full else "")
    show = sorted(cs, key=lambda c: -c[0])[:4]
    first = cs[0][0]
    rug = {}
    try:
        from kol import store
        hs = [c[1] for c in show]
        for r in data.q(store.DB, f"SELECT handle, stats FROM kols WHERE handle IN ({','.join('?' * len(hs))})", hs):
            rug[r["handle"]] = (json.loads(r["stats"] or "{}") or {}).get("rug_rate")
    except Exception:  # noqa: BLE001
        pass
    from ui import kolsummary
    items = []
    for ts_, hnd, m0 in show:
        v = kolsummary.kol_verdict(hnd)
        rr = rug.get(hnd)
        when = ("prvi, " if ts_ == first else "") + R.ago(ts_, now)
        if rr is not None and rr >= 0.3:
            reason = R.cat(R.raw(f'<span class="ms-warn">{esc(R.pct(rr, sign=False, frac=True))} rugova</span>'), " · ", when)
        else:
            reason = R.cat(R.dot(v["dot"]) if v.get("dot") else "", v["word"], " · ", when)
        growth = (mcap_now / m0 - 1) * 100 if (mcap_now and m0) else None
        name = (hnd[3:] + " (TG)") if hnd.startswith("tg:") else "@" + hnd
        items.append(R.row(name, reason=reason, value=R.usd(m0) if m0 else R.DASH,
                           sub=R.pct(growth) if growth is not None else None, sub_tone=R.tone(growth), href=f"/kol/{hnd}"))
    return (head + R.rows(items) + R.hint("Desno: mcap kod poziva i koliko je od tada narastao.")
            + (f'<details class="tkp-all" id="pozivi"><summary>Svi pozivi i kupnje KOL novčanika</summary>{full}</details>'
               if full else ""))


def _smart_html(mint, det, now):
    """Smart walleti: who of the registry bought it (good roles only), how much, and whether it still holds."""
    from ui import redak as R
    sg = [x for x in data.sightings(token=mint) if x.get("role") in ("early_buyer", "smart", "top_trader", "holder", "manual")]
    seen, rows = set(), []
    for x in sg:
        if x["wallet"] not in seen:
            seen.add(x["wallet"])
            rows.append(x)
    n_sm = len((det or {}).get("smart_buyers") or [])
    sub = f"{n_sm} među prvima" if n_sm else (f"{len(rows)} iz registra" if rows else "")
    head = f'<h2 class="ms-h2"><span>Smart walleti</span><span class="tkp-h2s">{esc(sub)}</span></h2>'
    if not rows:
        return head + R.hint("Nijedan wallet iz registra nije zabilježen na ovom tokenu.")
    rows = sorted(rows, key=lambda x: -(x.get("sol_in") or 0))[:5]
    ws = [x["wallet"] for x in rows]
    proven = set()
    try:
        from wallets import dokazani
        proven = {r["wallet"] for r in dokazani.latest()}
    except Exception:  # noqa: BLE001
        pass
    reg = {r["wallet"]: r for r in data.q(data.WALLET_DB, f"SELECT wallet, copy_score FROM wallets WHERE wallet IN "
                                                          f"({','.join('?' * len(ws))})", ws)}
    items = []
    for x in rows:
        w = x["wallet"]
        tr = data.q(data.WALLET_DB, "SELECT tokens, kind FROM wallet_trades WHERE wallet=? AND mint=?", (w, mint))
        bought = sum(t["tokens"] or 0 for t in tr if t["kind"] == "buy")
        sold = sum(t["tokens"] or 0 for t in tr if t["kind"] == "sell")
        if bought and sold:
            f = min(1.0, sold / bought)
            hold = "prodao sve" if f >= 0.95 else "prodao pola" if 0.4 <= f <= 0.6 else f"prodao {R.pct(f, sign=False, frac=True)}"
        elif bought:
            hold = "još drži"
        else:
            hold = None
        cs_ = (reg.get(w) or {}).get("copy_score")
        if w in proven:
            what = R.cat(R.dot("good"), "dokazan dvaput")
        elif cs_:
            what = f"copy ocjena {R.num(cs_)}"
        else:
            what = ROLE.get(x["role"], (x["role"],))[0]
        items.append(R.row(_short_addr(w), reason=R.cat(what, " · ", R.ago(x.get("ts"), now)),
                           value=R.sol(x.get("sol_in"), 2) if x.get("sol_in") else None, sub=hold, href=f"/wallet/{w}"))
    return head + R.rows(items)


def _rug_html(top, rug, now):
    """Provjera ruga: the fresh check of a recommended token (topcheck) or else the newest rug filter report."""
    from ui import redak as R, topcheckui
    state, rows = topcheckui.check_state(top), topcheckui.check_rows(top)
    if not rows:
        state, rows = topcheckui.rug_state(rug), topcheckui.rug_rows(rug)
    when = R.ago(state[2], now) if state and state[2] else ""
    head = f'<h2 class="ms-h2"><span>Provjera ruga</span><span class="tkp-h2s">{esc(when)}</span></h2>'
    if not state:
        return head + R.hint("Još nije provjeren: puna provjera ide tokenima koji prođu prve razine analize.")
    return (head + f'<div class="tkp-state">{R.dot(state[0], state[1])}</div>'
            + "".join(f'<div class="tkp-chk">{esc(k)}<span class="{kind or ""}">{esc(v)}</span></div>' for k, v, kind in rows))


def _sum_row(title, sub=None, value=None):
    """A row that opens what is under it (<summary> in the ms-row look)."""
    return (f'<summary class="ms-row"><div class="ms-m"><div class="ms-t">{esc(title)}</div>'
            + (f'<div class="ms-s">{esc(sub)}</div>' if sub else "") + "</div>"
            + (f'<div class="ms-e"><div class="ms-v mut" style="font-weight:400">{esc(value)}</div></div>' if value else "")
            + '<span class="ms-chev" aria-hidden="true"></span></summary>')


def token(mint, qs):
    from ui import redak as R
    now = time.time()
    ev = data.event_tokens(mint)
    sigs = data.hype_signals("token=?", (mint,), "ts DESC")
    rugs = data.rug_reports(mint)
    from ui import evidence, quickbuy, tokenchart
    from ui.tokens import SHEET_CSS
    dsym, dlist = quickbuy.dugo_info(mint)
    try:   # 7.11.: the exact pair page, or "no pair any more" (hype/tokenstatus)
        st = _token_status(mint)
    except Exception:  # noqa: BLE001
        st = None
    pair = evidence.live_pair(mint)
    rug = rugs[0] if rugs else None
    sym = (ev[0]["symbol"] if ev else None) or (sigs[0]["symbol"] if sigs else None) or (rug["symbol"] if rug else None) \
        or ((pair or {}).get("baseToken") or {}).get("symbol") or dsym
    name = ((pair or {}).get("baseToken") or {}).get("name") or ((rug or {}).get("data") or {}).get("name") \
        or (sigs[0].get("name") if sigs else None)
    url = (ev[0]["url"] if ev else None) or (sigs[0]["url"] if sigs else None)
    if st and st.get("has_pair") and st.get("pair_url"):
        url = st["pair_url"]
    url = (pair or {}).get("url") or url
    dead = bool(st) and not st.get("has_pair") and not pair
    analysed = bool(ev or sigs or rugs)

    locked = why_bad = rec_note = None
    top = None
    if analysed:
        from rugfilter import archive, collapse
        arch = archive.get(mint, data.HYPE_DB)
        col = None if arch else collapse.check(collapse.peaks(data.HYPE_DB, [mint]).get(mint))
        if arch:
            why_bad = (f'Rugan i izbačen iz praćenja {time.strftime("%d.%m. %H:%M", time.gmtime(arch["archived_ts"]))} UTC: '
                       f'{arch["reason"]} ({archive.KIND_HR.get(arch["kind"], arch["kind"])}); kupnja je zaključana')
        rec = None if arch else archive.recovered(mint, data.HYPE_DB)
        if rec:
            rec_note = (f'Vraćen u praćenje {time.strftime("%d.%m. %H:%M", time.gmtime(rec["recovered_ts"]))} UTC: bio je '
                        f'izbačen kao rug {time.strftime("%d.%m.", time.gmtime(rec["archived_ts"]))} ({rec["reason"] or ""}), '
                        f'a zatim se oporavio na {R.pct(rec["mcap"] / rec["peak_mcap"], sign=False, frac=True)} vrha '
                        f'({R.usd(rec["mcap"])} od {R.usd(rec["peak_mcap"])}).')
        if col:
            why_bad = f'Rugan: {col["text"]}; maknut je s prijedloga i kupnja je zaključana'
        if arch or col:
            locked = "token je rugan"
        from topcheck import store as topstore
        top = topstore.read_all().get(mint)
        if top and top.get("verdict") == "pao" and not locked:
            locked = "token je pao na obaveznom rug checku"
            why_bad = why_bad or ("Pao na obaveznoj provjeri ruga: " + "; ".join(((top.get("safety") or {}).get("fails") or [])[:2]))
        if not why_bad and rug and rug["verdict"] == "ODBAČEN":
            why_bad = "Rug filter ga je odbacio: " + "; ".join((rug["data"].get("hard_fails") or ["tvrdi pad"])[:2])

    sig = sigs[0] if sigs else None
    from ui import confidence, sansa
    _, det = evidence.details(mint)
    pc = data.paper_candidates(mint)
    cand = pc[0] if pc else None
    cs = evidence.checks(mint, sig, det, rug, ev, cand)
    role = "canonical" if any(e["role"] == "canonical" for e in ev) else None
    mk = (rug["data"].get("market") if rug else None) or {}
    feats = (data.js(sig["features"], {}) or {}) if sig else {}
    cargs = (sig["score"] if sig else None, feats, det, rug["verdict"] if rug else None, role,
             (sig or {}).get("liquidity") or mk.get("liquidity"), (sig or {}).get("mcap") or mk.get("mcap"))
    conf, parts = confidence.score(*cargs)
    keyed = confidence.parts_keyed(*cargs)
    sn, an, pr, pa = sansa.score(conf, cs)
    best = max(ev, key=lambda e: e["score"] or 0) if ev else None
    mcap_now = (pair or {}).get("marketCap") or (pair or {}).get("fdv") or ((st or {}).get("mcap") if (st or {}).get("has_pair") else None) \
        or (sig or {}).get("mcap") or mk.get("mcap")
    ch = (pair or {}).get("priceChange") or {}
    h1 = ch.get("h1")
    m0 = _zone_mcap0(mint, now) if analysed else None
    zone_x = mcap_now / m0 if (mcap_now and m0) else None
    from ui import narrative
    try:
        from ui.radar import reasons as _reasons
        why = _reasons(feats, det) if sig else []
    except Exception:  # noqa: BLE001
        why = []

    b = [TOKEN_CSS, tokenchart.CSS, f"<style>{SHEET_CSS}{quickbuy.SHEET_CSS}</style>", '<div class="ms-page ms-wide tkp">']
    if qs.get("err"):
        b.append(f'<p class="tkp-msg neg">Nije prošlo, ništa nije spremljeno: {esc(qs["err"])}</p>')
    elif qs.get("ok"):
        b.append(f'<p class="tkp-msg">{esc(qs["ok"])} <a href="/natjecanje#moj">Vidi svoj račun na Natjecanju</a></p>')
    b.append('<a class="tkp-back" href="/tokens">Tokeni</a>')
    sub = R.cat(name + " · " if name and name != sym else "",
                R.raw(f'<button type="button" class="tkp-cp" data-copy="{esc(mint)}" title="Kopiraj adresu {esc(mint)}">'
                      f'<span class="tkp-cl">{esc(_short_addr(mint))}</span><span class="tkp-ci" aria-hidden="true"></span></button>'))
    right = ""
    if mcap_now:
        right = (f'<div class="tkp-r"><div class="tkp-px">{esc(R.usd(mcap_now))}</div>'
                 + (f'<div class="tkp-s">24 h <span class="{R.tone(ch["h24"])}">{esc(R.pct(ch["h24"]))}</span></div>'
                    if ch.get("h24") is not None else "") + "</div>")
    b.append(f'<div class="tkp-dh"><div><h1 class="ms-h1" translate=no>{esc(sym or _short_addr(mint))}</h1>'
             f'<div class="tkp-s">{sub}</div></div>{right}</div>')

    # verdict panel, buttons, outside sites
    if analysed:
        word, kind = narrative.token_verdict(conf, mcap_now, rug["verdict"] if rug else None, locked,
                                             (top or {}).get("verdict"), h1, zone_x)
        sentence = narrative.token_sentence(why, word, zone_x, why_bad, h1)
        za, protiv = narrative.za_protiv(keyed, parts)
        zt, pt = narrative.za_protiv_line(za, protiv)
        lbl = R.cat(R.dot(kind) if kind in ("warn", "bad") else "", f"Pouzdanost {conf} · šansa za skok {sn}")
        panel = (f'<div class="ms-panel ms-verdict tkp-v"><div class="ms-lbl">{lbl}</div><div class="ms-name">{esc(word)}</div>'
                 f'<p>{esc(sentence)}</p><div class="tkp-go"><b>Za:</b> {esc(zt)} <b>Protiv:</b> {esc(pt)}</div></div>')
    else:
        panel = (f'<div class="ms-panel ms-verdict tkp-v"><div class="ms-lbl">Bez analize</div><div class="ms-name">'
                 f'{"Na popisu " + esc(dlist) if dlist else "Nije u analizi"}</div><p>'
                 + (f'Token je na popisu <a href="/dugorocno">{esc(dlist)}</a>; brojke su na stranici Dugoročni.' if dlist else
                    "Ovaj token nije ni u jednoj analizi. Tržište i vanjske stranice su ispod.") + "</p></div>")
    if rec_note:
        panel += R.hint(rec_note)
    buy_txt = (f"Kupnja je zaključana: {locked}." if locked else
               'Kupnja: demo 50 $ na Natjecanju<span class="adm-only"> ili Autopilot (pravi novac)</span>.')
    actions = ('<div class="tkp-btns"><button type="button" class="tkp-btn p" data-buy'
               + (' aria-disabled="true"' if locked else "") + '>Kupi</button>'
               f'<button type="button" class="tkp-btn s" data-copy="{esc(mint)}"><span class="tkp-cl">Kopiraj adresu</span></button></div>'
               f'<p class="tkp-links">{buy_txt}<br>{_token_links(mint, url, dead)}</p>')
    chart = tokenchart.chart_html(mint, sym or "", now)
    if chart:
        b.append(f'<div class="tkp-g2 a"><div>{chart}</div><div>{panel}{actions}</div></div>')
    else:
        b.append(panel + actions)

    pl = data.token_pulse(mint)
    b.append('<div class="tkp-g2"><section>' + _market_html(pair, st, top, rug, det, pl, url) + "</section><section>"
             + _callers_html(mint, mcap_now, now) + "</section></div>")
    b.append('<div class="tkp-g2"><section>' + _smart_html(mint, det, now) + "</section><section>"
             + _rug_html(top, rug, now) + "</section></div>")

    # how it got its grade: the full reading, the seven layers, live pulse (all one tap away)
    opened = qs.get("sve") == "1"
    b.append(R.section("Kako je dobio ocjenu"))
    full = []
    if analysed:
        try:
            head_, paras = narrative.interpret(mint)
        except Exception as e:  # noqa: BLE001 - never break the page over the summary
            print(f"narrative {mint}: {type(e).__name__}: {e}")
            head_, paras = "", []
        pts = "".join(f'<li><b class="{R.tone(p)}">{esc(R.num(p, 0, sign=True))}</b> {esc(t)}</li>' for p, t in parts)
        full.append(f'<details class="tkp-d"{" open" if opened else ""}>'
                    + _sum_row("Cijelo tumačenje", "za i protiv, svaki razlog s brojem")
                    + f'<div class="tkp-in"><p>{head_}</p>{"".join(paras)}'
                    + (f"<p><b>Pouzdanost {conf}</b>, po dijelovima:</p><ul class=tkp-list>{pts}</ul>" if pts else "")
                    + sansa.explain_html(sn, conf, an, pr, pa).replace("confidence", "pouzdanost") + "</div></details>")
    layers = _layers_html(mint, ev, sigs, rugs, pc, best, role, opened)
    full.append(f'<details class="tkp-d" id="slojevi"{" open" if opened else ""}>'
                + _sum_row("Slojevi analize", "KOL, hype, rug, puls, walleti, X, event", f"{an} od {sansa.N}")
                + f'<div class="tkp-in">{sansa.dots_html(cs)} {tier_html(mint) if analysed else ""}{layers}</div></details>')
    from hype import pulse as hpulse
    sf = hpulse.strength(pl) if pl else {}
    try:
        from live import pulse as _lp
        live_html = _lp.token_html(mint)
    except Exception:  # noqa: BLE001 - the live card never breaks the page
        live_html = ""
    full.append(f'<details class="tkp-d" id="puls"{" open" if opened else ""}>'
                + _sum_row("Puls uživo", (hpulse.describe(sf) or "").replace("Snaga: ", "")
                           or ("kupci i prodavači u zadnjih 15 min" if live_html else "nema očitanja u zadnja 24 h"))
                + f'<div class="tkp-in">{live_html}{_pulse_table(pl)}</div></details>')
    b.append('<div class="ms-list">' + "".join(full) + "</div>")
    b.append(R.hint("Pouzdanost: koliko se neovisni izvori slažu. Šansa za skok: koliko je sličnih tokena nastavilo rasti.")
             .replace("</p>", ' <a class="ms-acc" href="/pojmovnik#confidence" style="text-decoration:none">Pojmovnik</a></p>'))
    b.append(quickbuy.buy_sheet(mint, sym, locked) + "</div>" + TOKEN_JS)
    # a detail page of about three screens: no row of section chips on top (ui/secnav builds one from 3+ <h2>)
    return sym or short(mint), "".join(b).replace("<h2", '<h2 data-sec=""')


def _pulse_table(pl):
    """The pulse readings (hype/pulse, every 2 min while the token is interesting), newest first."""
    if not pl:
        return ""
    return table(["Vrijeme", ("Mcap", "n"), ("Vol 5 min", "n"), ("Vol 1 h", "n"), ("Kupnje 1 h", "n"), ("Prodaje 1 h", "n"),
                  ("Holderi (puls)", "n")],
                 [[ts(x["ts"]), usd(x["mcap"]), usd(x["vol_m5"]), usd(x["vol_h1"]), num(x["buys_h1"]), num(x["sells_h1"]),
                   (f"{x['holders']} <span class=mut>{esc(x['holders_src'] or '')}</span>", x["holders"], "n") if x["holders"] else num(None)]
                  for x in pl[::-1][:48]])


def _layers_html(mint, ev, sigs, rugs, pc, best, role, opened):
    """The analysis layers as they were on the old page (event, hype, rug filter, demo trading, wallets), each folded,
    with every table. 10.11.: moved under "Kako je dobio ocjenu → Slojevi analize"; the KOL layer is under "Tko ga je
    zvao" and the pulse under "Puls uživo"."""
    b = [f"<p class=mut style='font-size:13px'><a href='?sve={'0' if opened else '1'}'>{'Sklopi sve' if opened else 'Otvori sve'}</a></p>"]
    sigs_asc = sigs[::-1]

    def sec(sid, title, summary, force=False):
        return (f"<details id={sid}{' open' if opened or force else ''}><summary><b>{title}</b> "
                f"<span class=mut>· {summary}</span></summary>")

    # layer 1: event
    ev_sum = (f"{esc(best['event'])} · {'pravi' if role else 'kopija'} · ocjena {best['score']}" if best else "nije vezan uz event")
    b.append(sec("event", "1. Event sloj", ev_sum))
    if not ev:
        b.append("<p class=mut>Nije pronađen ni za jedan event iz kalendara.</p>")
    for e in ev:
        d = dict(e["data"])
        d.setdefault("cto", e["cto"])
        erole = "pravi (canonical)" if e["role"] == "canonical" else "kopija (copycat)"
        b.append(f'<div class=card><b>{esc(e["event"])}</b> · {esc(e["event_date"])} · pojam '
                 f'<code>{esc(e["keyword"])}</code> · {badge(erole, "good" if e["role"] == "canonical" else "")}'
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
        b.append(table(["Signal", ("Vrijednost 0-1", "n"), ("Težina", "n"), ("Doprinos", "n"), "", ("Što mjeri", "wrap")], rows))
        b.append(f"<p>Zbroj doprinosa: <b>{sum(r[3][1] for r in rows):.1f}</b> <span class=mut>(spremljeno {last['score']})</span></p>")
        snaps = data.hype_snapshots(mint)
        if len(snaps) > 1:
            b.append("<h3>Cijena od prvog signala</h3>" + _spark(snaps, sigs_asc[0]["price"]))
        b.append("<h3>Svi signali</h3>")
        b.append(table(["Vrijeme", ("Ocjena", "n"), ("Cijena", "n"), ("Mcap", "n"), ("Likvidnost", "n"), "Izvori"],
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
        b.append(table(["Provjera", ("Vrijednost", "wrap")], [[esc(k), (esc(x), "", "wrap")] for k, x in metr]))
        top = h.get("top") or []
        if top:
            b.append("<h3>Top holderi</h3>" + table(["Wallet", ("%", "n"), "Insajder"],
                                                   [[wlink(x["wallet"]), num(x.get("pct"), "{:.1f}"),
                                                     badge("da", "bad") if x.get("insider") else "ne"] for x in top]))
        md = os.path.join("rug", f"{mint}.md")
        if data.read_output(md) is not None:
            b.append(f'<p><a href="/outputs/{quote(md)}">Puni rug izvještaj</a></p>')
        if len(rugs) > 1:
            b.append("<h3>Ranije provjere</h3>" + table(["Vrijeme", "Presuda", ("Ocjena", "n")],
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

    # wallets on this token (10.11.: copy score and labels of just these wallets, by key, not the whole registry)
    sg = data.sightings(token=mint)
    b.append(sec("walleti", "5. Walleti viđeni na ovom tokenu", f"{len(sg)} iz registra"))
    ws = sorted({x["wallet"] for x in sg})
    wmap = {}
    for i in range(0, len(ws), 500):
        part = ws[i:i + 500]
        for w in data.q(data.WALLET_DB, f"SELECT wallet, copy_score, tier, labels FROM wallets WHERE wallet IN ({','.join('?' * len(part))})", part):
            w["labels"] = data.js(w.get("labels"), []) or []
            wmap[w["wallet"]] = w
    b.append(table(["Wallet", "Uloga", "Izvor", ("SOL", "n"), ("Copy", "n"), "Tier", "Oznake"],
                   [[wlink(x["wallet"]), esc(ROLE.get(x["role"], (x["role"],))[0]), esc(SOURCE.get(x["source"], x["source"])),
                     num(x["sol_in"], "{:.2f}"), num((wmap.get(x["wallet"]) or {}).get("copy_score")),
                     tierb((wmap.get(x["wallet"]) or {}).get("tier")),
                     " ".join(badge(l, "bad") for l in (wmap.get(x["wallet"]) or {}).get("labels", []))] for x in sg],
                   empty="Nijedan wallet nije zabilježen za ovaj token."))
    b.append("</details>")
    return "".join(b)


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

def _pick_cell(ranked, watches=None):
    """Event row: the most likely pumper on one line (name, icons, score); its reasons and every other token
    ranked sit in one closed <details>, so the row stays short until someone opens it (Nicholas 4.11.)."""
    if not ranked:
        return "–"
    best = ranked[0]
    if best["pump"] is None:
        return "<span class=mut>nijedan token ne prolazi provjere</span>"
    pk = "good" if best["pump"] >= 60 else "warn" if best["pump"] >= 35 else ""
    score = f"{best['pump']:.0f}/100"
    head = f"{tlink(best['token'], best['symbol'])} {badge(score, pk)}"
    w = (watches or {}).get(best["token"])
    if w and w.get("verdict"):
        from ui.watch import VERDICT_KIND
        head += f'<div class=evw>⏳ {badge(w["verdict"], VERDICT_KIND.get(w["verdict"], ""))}</div>'
    why = "".join(f"<div>{p:+.0f} {esc(t)}</div>" for p, t in best["reasons"][:6])
    others = []
    for i, t in enumerate(ranked[1:], 2):
        val = "isključen: " + esc(t["excluded"]) if t["pump"] is None else f"{t['pump']:.0f}/100"
        others.append(f"<div>{i}. {tlink(t['token'], t['symbol'])} {val}</div>")
    lab = "zašto" + (f" · još {len(others)}" if others else "")
    body = (f"<div class=mut>{why}</div>" + (f"<div class=evo><b>Ostali tokeni</b>{''.join(others)}</div>" if others else ""))
    return head + f"<details class=evd><summary>{lab}</summary><div class=evx>{body}</div></details>"


def _when(date, hype=None):
    """'danas' / 'sutra' / 'za 3 d' / 'prije 2 d' with the date and the calendar colour dot; sorts by date."""
    try:
        d = time.strptime(str(date)[:10], "%Y-%m-%d")
        n = round((time.mktime(d) - time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))) / 86400)
    except (ValueError, TypeError):
        return ("–", "", "")
    txt = {0: "danas", 1: "sutra", -1: "jučer"}.get(n) or (f"za {n} d" if n > 0 else f"prije {-n} d")
    from ui import evcal
    return (f"<b>{txt}</b><div class=mut>{evcal.dot(hype)} {d.tm_mday}.{d.tm_mon}.</div>", str(date), "")


def _ev_cell(e):
    """Event title + one small line (kind · source) + keyword chips (max 4): replaces three wide columns."""
    t = (f'<a href="{esc(e["url"])}" target=_blank rel=noopener>{esc(e["title"])}</a>' if e.get("url") else esc(e["title"]))
    meta = f'<div class=evm>{esc(labels.kind(e["kind"]))} · {esc(labels.event_source(e["source"]))}</div>'
    kws = e.get("keywords") or []
    chips = "".join(f"<span class=kw translate=no>{esc(k)}</span>" for k in kws[:4])
    if len(kws) > 4:
        chips += f'<span class="kw mut" title="{esc(" ".join(kws[4:]))}">+{len(kws) - 4}</span>'
    return (t + meta + (f"<div class=kws>{chips}</div>" if chips else ""), e["title"] + " " + " ".join(kws), "wrap evc")


EV_CSS = """<style>
#et td.evc{min-width:210px;max-width:340px}.evm{font-size:12px;color:var(--mut);margin-top:2px}
.kws{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}.kw{font-size:11px;padding:1px 6px;border-radius:6px;
 background:color-mix(in srgb,var(--acc) 8%,var(--card));border:1px solid var(--line);white-space:nowrap}
#et td.evt{min-width:170px;max-width:300px;white-space:normal}.evw{margin-top:3px}
details.evd summary{font-size:12px;color:var(--acc);cursor:pointer;margin-top:3px}
.evx{font-size:12px;white-space:normal;max-width:300px;padding-top:3px}.evo{margin-top:6px}
details.evh summary{font-size:12px;color:var(--acc);cursor:pointer}.evh .evx div{white-space:normal}
table.cards#et td.evt,table.cards#et td.evc{max-width:none}table.cards#et td.evt .evx{max-width:none}
.evstat{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 10px}.evstat a,.evstat span{font-size:13px;padding:6px 10px;
 border:1px solid var(--line);border-radius:10px;background:var(--card);text-decoration:none;color:var(--fg)}
.evstat b{font-size:15px}
</style>"""


def _ev_detail(e, ranked, det):
    """Pop-up body for one event (calendar tap): everything the list row has, written out."""
    from ui import evcal
    c, lab = evcal.level(e.get("hype"))
    t = (f'<a href="{esc(e["url"])}" target=_blank rel=noopener>{esc(e["title"])} ↗</a>' if e.get("url") else esc(e["title"]))
    kws = " ".join(f"<span class=kw translate=no>{esc(k)}</span>" for k in e.get("keywords") or [])
    tl = e.get("token_likelihood")
    pick = _pick_cell(ranked, None) if ranked else "<span class=mut>još nema tokena</span>"
    return (f'<div class=ecev><h3>{evcal.dot(e.get("hype"))}{t}</h3>'
            f'<div class=lab>{esc(labels.kind(e["kind"]))} · {esc(labels.event_source(e["source"]))} · {esc(e["date"])}</div>'
            f'<div class=row><span><span class=lab>Hype {info("Hype")}</span> {bar(e["hype"] or 0, 100, 60)} <b>{(e["hype"] or 0):g}</b> ({lab})</span>'
            f'<span><span class=lab>Šansa za token {info("Šansa za token")}</span> <b>{"–" if tl is None else f"{tl:.2f}"}</b></span></div>'
            + (f'<div class="kws">{kws}</div>' if kws else "")
            + f'<div class=row style="display:block"><span class=lab>Najizgledniji token {info("Najizgledniji token")}</span><div>{pick}</div></div>'
            + f'<div class=row style="display:block"><span class=lab>Zašto ta ocjena</span>{det}</div></div>')


def _events_rows(evs, watches):
    """[(event, list row, pop-up html)] for every event, best token per event ranked with eventpick."""
    et = {}
    for t in data.event_tokens():
        et.setdefault((t["event_date"], t["event"]), []).append(t)
    rugs, kol = data.rug_latest(), pickload.kol_mentions()
    out = []
    for e in evs:
        toks = sorted(et.get((e["date"], e["title"]), []), key=lambda t: -(t["score"] or 0))
        ranked = pickscore.rank(toks, rugs, watches, kol) if toks else []
        parts = explain.event_hype(e)
        det = (f"<details class=evh><summary>raspis</summary><div class=evx>"
               + "".join(f"<div>{esc(n)} {info(n)}: <b>{p:.1f}</b>/{m} <span class=mut>{esc(x)}</span></div>" for n, p, m, x in parts)
               + "</div></details>")
        row = [_ev_cell(e), _when(e["date"], e.get("hype")), scorecell(e["hype"]), num(e.get("token_likelihood"), "{:.2f}"),
               (_pick_cell(ranked, watches) if toks else "", (ranked[0]["pump"] or 0) if ranked else -1, "wrap evt"),
               (det, "", "")]
        e["_has_tok"] = bool(toks)
        out.append((e, row, _ev_detail(e, ranked, det)))
    return out


def events(qs):
    from ui import evcal, watch
    allev = data.events()
    past = qs.get("past") == "1"
    only_tok = qs.get("tok") == "1"
    today = time.strftime("%Y-%m-%d")
    watches = pickload.watches()
    built = _events_rows(allev, watches)
    shown = [(e, r) for e, r, _ in built if (past or not e["date"] or e["date"] >= today) and (not only_tok or e["_has_tok"])]
    tbl = table([("Event", "wrap"), "Kada", ("Hype", "n"), ("Šansa za token", "n"), "Najizgledniji token",
                 "Zašto ta ocjena"], [r for _, r in shown], "et",
                "Nema evenata za ovaj izbor. Bot osvježava kalendar sam svakih 6 h.")
    upcoming = [e for e, _, _ in built if not e["date"] or e["date"] >= today]
    n_watch = watch.tracked_count()
    stat = (f'<div class=evstat><span><b>{len(upcoming)}</b> nadolazećih</span>'
            f'<span><b>{sum(e["_has_tok"] for e in upcoming)}</b> s tokenom</span>'
            f'<a href="#prije"><b>{n_watch}</b> tokena u praćenju ⏳ ↓</a></div>')
    form = (f'<form class=flt method=get>{filt("et", "Filtriraj event, ključnu riječ…")}'
            f'<label><input type=checkbox name=tok value=1 {"checked" if only_tok else ""} onchange="this.form.submit()"> samo s tokenom</label> '
            f'<label><input type=checkbox name=past value=1 {"checked" if past else ""} onchange="this.form.submit()"> i prošli</label></form>')
    intro = ("<h1>Eventi</h1><p class=mut>Događaji iz kalendara, tokeni napravljeni za njih i kreću li ti tokeni prije "
             "događaja. <a href=/criteria#eventi>Kriteriji</a>.</p>")
    cal = evcal.render([(e, d) for e, _, d in built], dt.date.fromisoformat(today))
    lst = ("<h2 id=lista>📋 Svi eventi po datumu</h2>" + tdesc(
        'Iz kalendara alat uzme ključne riječi događaja i na DexScreeneru traži tokene s tim imenom ili simbolom. '
        'Hype = koliko se o događaju priča, šansa za token = procjena da će netko napraviti token. '
        '<i>Najizgledniji token</i> je onaj s najvećom ocjenom pumpe 0-100 (organsko trgovanje, prostor za rast, rug provjera, '
        'volumen i smart walleti prema eventu, KOL-ovi); „zašto” otvara razloge i ostale tokene, ⏳ je zaključak praćenja prije '
        'eventa. Tokeni koje rug provjera odbaci ili s likvidnošću ispod $2k ne mogu biti izbor. Ocjena je procjena, ne garancija.')
        + form + tbl)
    return "Eventi", (EV_CSS + intro + stat + "<h2 id=kalendar>📅 Kalendar</h2>"
                      + '<p class=mut style="margin:0">Dodirni dan za detalje događaja.</p>' + cal
                      + lst + '<h2 id=prije>⏳ Prije eventa</h2>' + watch.sections())


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
