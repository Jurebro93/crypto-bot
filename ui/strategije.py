"""/strategije. 16.11. (vlasnik: "Treba maknuti strategije koje ne doprinose učenju i ove s micro capovima ... Sada idemo
s mid cap tokenima"): on top the MIDCAP strategies in one table (report/midcap.strategies: the veliki demo and the real
account by rule, Insajderi 2.0 demo, the holders' signal measurement, the walk-forward variants), below the old microcap
comparison (strat/: demo accounts of $1000 side by side, same exit rules) as a collapsed, read-only archive while the
owner switch fokus_midcap is on (open while it is off)."""
import time

from ui.html import note, ago, badge, esc, num, signed, table, tdesc, tlink

COLORS = ["#4f46e5", "#0891b2", "#16a34a", "#d97706", "#94a3b8"]
EXIT = {"stop_loss": "stop loss", "rug": "rug / nestao", "trailing": "prateći stop", "breakeven": "na ulaznoj cijeni",
        "stale": "ništa se ne događa", "time": "isteklo vrijeme", "moonbag_trailing": "moonbag stop",
        "moonbag_time": "moonbag vrijeme", "smart_sell_eksplozija": "smart sell (eksplozija)"}


def _cfg():
    from strat import run
    return run.load_config()


def _exit(r):
    if not r:
        return "–"
    if r.startswith("take_profit_"):
        return "take profit +" + f"{float(r[12:-1]):.0%}"
    return EXIT.get(r, r)


def _pct(x):
    if x is None:
        return ("–", -1e18, "n")
    c = "pos" if x > 0 else "neg" if x < 0 else ""
    return (f'<span class="{c}">{x:+.1%}</span>', x, "n")


def _chart(eq, cfg):
    """Static SVG: account value of each strategy over time, $1000 line dashed. Scales to the phone width."""
    if not eq:
        return ""
    names = {s["key"]: (s["name"], COLORS[i % len(COLORS)]) for i, s in enumerate(cfg["strategies"])}
    ts = sorted({t for t, _, _ in eq})
    if len(ts) < 2:
        return ""
    vals = [v for _, _, v in eq] + [cfg["bankroll_usd"]]
    lo, hi = min(vals), max(vals)
    pad = max(5.0, (hi - lo) * 0.08)
    lo, hi = lo - pad, hi + pad
    W, H, L, R, T, B = 640, 260, 52, 10, 10, 24
    x = lambda t: L + (t - ts[0]) / (ts[-1] - ts[0]) * (W - L - R)  # noqa: E731
    y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role=img aria-label="Stanje računa po strategiji" '
           f'style="width:100%;height:auto;display:block">']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        out.append(f'<line x1={L} x2={W - R} y1={y(v):.1f} y2={y(v):.1f} stroke="#e5e7eb"/>'
                   f'<text x={L - 6} y={y(v) + 4:.1f} text-anchor=end font-size=11 fill="#6b7280">${v:,.0f}</text>')
    b = y(cfg["bankroll_usd"])
    out.append(f'<line x1={L} x2={W - R} y1={b:.1f} y2={b:.1f} stroke="#9ca3af" stroke-dasharray="4 4"/>')
    for t, anchor in ((ts[0], "start"), (ts[-1], "end")):
        out.append(f'<text x={x(t):.1f} y={H - 6} text-anchor={anchor} font-size=11 fill="#6b7280">'
                   f'{time.strftime("%d.%m. %H:%M", time.gmtime(t))}</text>')
    by = {}
    for t, k, v in eq:
        by.setdefault(k, []).append((t, v))
    for k, pts in by.items():
        if k not in names:
            continue
        name, col = names[k]
        dash = ' stroke-dasharray="5 4"' if k == "kontrola" else ""
        p = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in sorted(pts))
        out.append(f'<polyline points="{p}" fill=none stroke="{col}" stroke-width=2.2{dash}><title>{esc(name)}'
                   f'</title></polyline>')
    out.append("</svg>")
    legend = " ".join(f'<span style="white-space:nowrap;margin-right:10px"><i style="display:inline-block;width:12px;'
                      f'height:3px;background:{c};vertical-align:middle;margin-right:4px"></i>{esc(n)}</span>'
                      for n, c in names.values())
    return f'<div class=card>{"".join(out)}<p class=mut>{legend}</p></div>'


def _card(s, rank, n, color):
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "") if s["closed"] + s["open"] else ""
    kind = "pos" if s["ret"] > 0 else "neg" if s["ret"] < 0 else ""
    hit = f"{s['hit']:.0%}" if s["hit"] is not None else "–"
    return (f'<div class=stat style="border-top:4px solid {color}">'
            f'<div class=l>{medal} {rank}. od {n} · {esc(s["icon"])} <b>{esc(s["name"])}</b></div>'
            f'<div class="v {kind}">${s["value"]:,.0f} <small>({s["ret"]:+.1%})</small></div>'
            + (f'<div class=mut style="font-size:12px">nadopunjeno +${s["topup"]:,.0f} (uloženo ukupno ${1000 + s["topup"]:,.0f})</div>'
               if s.get("topup") else "") +
            f'<div class=l>{s["closed"]} zatvoreno · {s["open"]} otvoreno · uspješnost {hit} · '
            f'slobodno ${s["cash"]:,.0f}</div>'
            + (f'<div class=l title="udio zatvorenih tradeova koji su završili s barem +15 %; donja četvrtina = '
               f'rezultat ispod kojeg je najgorih 25 % tradeova">≥ +15 %: <b>{s["p15"]:.0%}</b> '
               f'({round(s["p15"] * s["closed"])} od {s["closed"]}) · donja četvrtina {s["q25"]:+.0%}</div>'
               if s.get("p15") is not None else "") + _robust_line(s) +
            f'<div class=l style="margin-top:4px">{esc(s["opis"])}</div></div>')


STATUS_CLS = {"uci": "", "kandidat": "good", "ne_diraj": "bad", "kontrola": "", "zamrznuto": "bad"}


def _robust_line(s):
    """R7 + R6 + F01 under each card: status, result without the best trade / token, $1000 without borrowing."""
    rb, st, pf = s.get("robust"), s.get("status"), s.get("portfolio")
    if not rb or not st:
        return ""
    out = f'<div class=l style="margin-top:4px">{badge(st[1], STATUS_CLS.get(st[0], ""))} {esc(st[2])}</div>'
    if rb["n"]:
        conc = " · <b>koncentrirano</b>: plus ovisi o jednom tradeu/tokenu" if rb["concentrated"] else ""
        m = lambda x: f'{"+" if x >= 0 else "−"}${abs(x):,.0f}'  # noqa: E731
        out += (f'<div class=l>Zatvoreni bez najboljeg tradea: {m(rb["no_best"])} · bez 5 najboljih: '
                f'{m(rb["no_top5"])} · bez najboljeg tokena: {m(rb["no_best_token"])}{conc}</div>')
    if pf and (pf["taken"] or pf["skipped"]):
        out += (f'<div class=l>S pravih $1.000 bez posuđivanja: ${pf["value"]:,.0f} ({pf["taken"]} tradeova, '
                f'{pf["skipped"]} preskočeno jer nije bilo novca)</div>')
    return out


def natjecanje_block():
    """Natjecanje (Nicholas 4.11.): the five strategy accounts as cards, best first, so everyone sees how the tool
    learns and which kind of trade works. Empty when strat.db is not there yet."""
    from strat import run, store
    cfg = _cfg()
    con = store.ro()
    if con is None:
        return ""
    try:
        summ = run.summary(con, cfg, run.exit_rules(time.time()))
    except Exception:  # noqa: BLE001 - never breaks the Natjecanje page
        return ""
    finally:
        con.close()
    color = {s["key"]: COLORS[i % len(COLORS)] for i, s in enumerate(cfg["strategies"])}
    order = sorted((s for s in summ if not s.get("baseline")), key=lambda s: -s["value"])
    lead = order[0] if order and order[0]["closed"] else None
    total = sum(s["closed"] for s in summ)
    lim = ("bez ograničenja novca (račun smije u minus, pa vidimo i koliko bi izgubio)"
           if not cfg.get("cash_limit", True) else f"dok ima novca na računu")
    return ("<h2 id=strategije>🤖 Kako alat uči: 5 strategija</h2>"
            + tdesc(f"Alat trguje s pet odvojenih demo računa od ${cfg['bankroll_usd']:,.0f}: svaki kupuje iz drugog "
                    f"izvora (top novčanici, influenceri, izbor alata posebno za male, srednje i velike tokene), a svi prodaju po istim pravilima. "
                    f"Ulog ${cfg['size_usd']:.0f} po tradeu, {lim}. Tako se vidi koji tip tradeova stvarno zarađuje."
                    + (f" Zasad vodi <b>{esc(lead['icon'])} {esc(lead['name'])}</b> ({lead['ret']:+.1%})." if lead else "")
                    + (f" Zatvoreno ukupno {total}; pouzdana usporedba treba ~20 po strategiji." if total < 20 * len(summ)
                       else "")
                    + ' <a href=/strategije>Sve brojke, graf i tradeovi →</a>')
            + "<div class=grid>" + "".join(_card(s, i + 1, len(order), color[s["key"]]) for i, s in enumerate(order))
            + "</div>")


VRSTA = {"demo": ("demo", ""), "pravi": ("pravi novac", "good"), "mjerenje": ("mjerenje", "warn"),
         "backtest": ("backtest", "")}


def page(qs):
    """16.11. (vlasnik: "zašto u strategijama nema tradeova? Treba maknuti strategije koje ne doprinose učenju i ove s
    micro capovima ... Sada idemo s mid cap tokenima"): the MIDCAP strategies in one table (demo, real, measurement,
    backtest), the old microcap accounts below as a collapsed, read-only archive while fokus_midcap is on."""
    now = time.time()
    try:
        from strat import run
        paused = run.paused()
    except Exception:  # noqa: BLE001
        paused = False
    h = ["<h1>Usporedba strategija</h1>", midcap_html(now), mikrokap_html(now, paused)]
    return "Usporedba strategija", "".join(h)


def _wcell(x, vrsta):
    if vrsta == "backtest" or not x:
        return ("–", -1e18, "n")
    if vrsta == "mjerenje":
        return (f"{x['n']} signala", x["n"], "n")
    p = x.get("pnl_usd") or 0.0
    c = "pos" if p > 0 else "neg" if p < 0 else ""
    return (f'<span class="{c}">{p:+,.2f} $</span><br><small class=mut>{x["n"]} zatv.</small>', p, "n")


def midcap_rows_html(rows):
    out = []
    for r in rows:
        word, cls = VRSTA.get(r["vrsta"], (r["vrsta"], ""))
        ev, ci = r.get("ev_pct"), r.get("ci")
        evc = "pos" if (ev or 0) > 0 else "neg" if (ev or 0) < 0 else ""
        ev_html = ("–" if ev is None else f'<span class="{evc}">{ev:+.2f} %</span>') + (
            f'<br><small class=mut>CI {esc(r.get("ci_label"))}: {ci[0]:+.1f}…{ci[1]:+.1f}</small>' if ci else "")
        out.append([f'{badge(word, cls)} <b>{esc(r["naziv"])}</b>'
                    + (f'<br><small class=mut>{esc(r.get("opis") or "")}</small>' if r.get("opis") else ""),
                    num(r.get("n")), (ev_html, ev if ev is not None else -1e18, "n"),
                    (f'{r["pogodak"]:.0%}' if r.get("pogodak") is not None else "–",
                     r["pogodak"] if r.get("pogodak") is not None else -1, "n"),
                    _wcell(r.get("d24"), r["vrsta"]), _wcell(r.get("d7"), r["vrsta"])])
    return out


def midcap_html(now):
    try:
        from report import midcap as rmid
        rows = rmid.strategies(now)
    except Exception as e:  # noqa: BLE001 - the page shows the archive even if the midcap data is unreadable
        return note(f"Midcap usporedba se ne može pročitati ({esc(type(e).__name__)}).")
    out = ("<h2 id=midcap>Midcap strategije (MC 2M–200M)</h2>"
           + tdesc("Od 15.11. bot trguje midcapove (prekidač fokus_midcap). U jednoj tablici: demo i pravi novac po "
                   "pravilu (<b>dnevni raspon</b>: zona zadnjih 48 h, cijeli profit na +10 % neto; <b>raspon 7 d</b>: "
                   "zona zadnjih 7 dana), Insajderi 2.0 u demu, mjerenje signala holdera (bez novca) i backtest "
                   "(walk-forward: pravilo birano na starijim danima, testirano na novijima). Svi rezultati su nakon "
                   "pravog troška. <b>EV</b> = prosjek po tradeu; <b>CI</b> = interval (90 % za demo i pravi novac, 95 % "
                   "po danu za backtest): kad mu je donja granica ispod nule, prednost još nije dokazana. <b>24 h</b> i "
                   "<b>7 d</b> = zarada zatvorenih tradeova u tom razdoblju.")
           + '<div class=midtab>' + table(["Strategija", ("n", "n"), ("EV po tradeu", "n"), ("Pogodak", "n"),
                                          ("24 h", "n"), ("7 d", "n")], midcap_rows_html(rows), tid="midstr")
           + "</div>")
    return out + kopija_html(now) + MID_CSS


def kopija_html(now):
    """16.11. (wallets/kopija.py): under the comparison table, what WE would have earned copying the proven wallets:
    the verdict, the small table (after delay and cost, out of sample), the gap to the wallet's own return, the demo
    copies and what is stale. "" before the first run; never takes the page down."""
    try:
        from report import midcap as rmid
        k = rmid.kopija(now)
    except Exception:  # noqa: BLE001
        k = None
    if not k or not (k.get("presuda") or k.get("demo")):
        return ""

    def row(r):
        if r.get("malo"):
            return [esc(r["naziv"]), num(r.get("n")), ("premalo podataka", -1e18, "n mut"), "–", "–"]
        ev, ci = r.get("ev_pct"), r.get("ci")
        c = "pos" if (ev or 0) > 0 else "neg" if (ev or 0) < 0 else ""
        return [esc(r["naziv"]), num(r.get("n")),
                (f'<span class="{c}">{ev:+.2f} %</span>'
                 + (f'<br><small class=mut>CI 90 %: {ci[0]:+.1f}…{ci[1]:+.1f}</small>' if ci else ""), ev, "n"),
                (f'{r["pogodak"]:.0%}' if r.get("pogodak") is not None else "–", r.get("pogodak") or -1, "n"),
                (f'{r["zbroj_sol"]:+.2f} SOL' if r.get("zbroj_sol") is not None else "–", r.get("zbroj_sol") or 0, "n")]
    ul = lambda xs: "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in xs) + "</ul>"   # noqa: E731
    head = ["Što je mjereno", ("Kopija", "n"), ("EV po tradeu", "n"), ("Pogodak", "n"), ("Zbroj", "n")]
    h = ['<h2 id=kopija>Kopiranje dokazanih novčanika: koliko bismo zaradili mi</h2>']
    if k.get("presuda"):
        h.append(f"<p><b>{esc(k['presuda'])}</b></p>")
        if k.get("redovi"):
            h.append('<div class=midtab>' + table(head, [row(r) for r in k["redovi"]], tid="kopija-t") + "</div>")
            h.append(note(f"Novčanici su odabrani na starijem dijelu podataka; mjereno je samo na zadnjih "
                          f"{esc(k.get('dana_izvan'))} dana koje odabir nije vidio, s ulogom "
                          f"{esc(str(k.get('ulog_sol')).replace('.', ','))} SOL, nakon kašnjenja i troška."))
        if k.get("razlika"):
            h.append("<h3>Zašto je novčanik u plusu, a kopija nije ista</h3>" + ul(k["razlika"]))
        if k.get("skupine"):
            h.append("<details><summary>Po veličini tokena, likvidnosti i načinu trgovanja novčanika</summary><div class=midtab>"
                     + table(head, [row(r) for r in k["skupine"]], tid="kopija-s") + "</div></details>")
        if k.get("mreza"):
            h.append(f"<details><summary>Svih {len(k['mreza'])} isprobanih kombinacija (odabir · kašnjenje · izlaz)</summary>"
                     "<div class=midtab>" + table(head, [row(r) for r in k["mreza"]], tid="kopija-m", limit=0)
                     + "</div></details>")
    d = k.get("demo")
    if d:
        late = f", ulaz tipično {d['kasnjenje_med_s']:.0f} s nakon njega" if d.get("kasnjenje_med_s") is not None else ""
        ev = f", prosjek {d['ev_pct']:+.2f} % po kopiji" if d.get("ev_pct") is not None else ""
        h.append(note(f"Demo kopije (mjerenje unaprijed, samo demo račun, i ispod 5M $): zatvoreno {d['n']}, otvoreno "
                      f"{d['otvoreno']}{ev}{late}. Izlaz: {esc(k.get('demo_izlaz') or 'njegov izlaz ili stop −20 %')}."))
    if k.get("svjezina"):
        h.append("<h3>Što je zastarjelo</h3>" + ul(k["svjezina"]))
    if k.get("napomene") or k.get("pristranosti"):
        h.append("<details><summary>Kako čitati i gdje test griješi</summary>"
                 + ul((k.get("napomene") or []) + (k.get("pristranosti") or [])) + "</details>")
    return "".join(h)


# 16.11.: the table must read on a phone (390 px) without sideways scrolling: the strategy's name wraps, the numbers
# stay narrow
MID_CSS = ("<style>.midtab table.s td,.midtab table.s th{padding:6px 6px}.midtab table.s td:first-child{white-space:normal;"
           "min-width:150px}.midtab small{font-size:11px}@media(max-width:700px){.midtab table.s{font-size:12px}"
           ".midtab table.s td,.midtab table.s th{padding:5px 4px}.midtab table.s td:first-child{min-width:130px}"
           ".midtab .b{font-size:10px;padding:0 5px}}</style>")


def mikrokap_html(now, paused):
    """The old comparison of the microcap accounts (strat/), collapsed and read-only while fokus_midcap is on."""
    try:
        from report import midcap as rmid
        from report import render as rrender
        line = rrender.mikrokap_line(rmid.mikrokap(now))
    except Exception:  # noqa: BLE001
        line = "Mikrokap strategije pauzirane od 15.11. (fokus midcap)."
    head = "Arhiva: mikrokap strategije" if paused else "Mikrokap strategije"
    if not paused:
        line = line.replace(" pauzirane od 15.11. (fokus midcap)", "").replace("konačni rezultat", "rezultat")
    return (f'<details id=arhiva{"" if paused else " open"}><summary><b>{head}</b></summary>'
            f'<p class=mut>{esc(line)}</p>{_mikrokap_body(now, paused)}</details>')


def _mikrokap_body(now, paused):
    from strat import run, store
    cfg = _cfg()
    h = []
    con = store.ro()
    if con is None:
        return tdesc("Nema zapisa mikrokap strategija (strat.db).")
    try:
        ex = run.exit_rules(now)
        summ = run.summary(con, cfg, ex)
        if not paused:
            h.append(_verdict_box(summ))
        start = int(float(store.kv_get(con, "start_ts", now)))
        eq = con.execute("SELECT ts, strat, value FROM equity WHERE ts >= ? ORDER BY ts",
                         (now - 30 * 86400,)).fetchall()
        recent = store.rows(con, "status IN ('open','closed') AND COALESCE(entry_ts, 0) >= ?", (now - 7 * 86400,))
        skips = con.execute("SELECT strat, close_reason, COUNT(*) FROM positions WHERE status='skip' "
                            "GROUP BY strat, close_reason").fetchall()
    finally:
        con.close()
    color = {s["key"]: COLORS[i % len(COLORS)] for i, s in enumerate(cfg["strategies"])}
    name = {s["key"]: s["name"] for s in cfg["strategies"]}
    days = (now - start) / 86400
    h.append(tdesc(
        f"Pet odvojenih demo računa, svaki je krenuo s ${cfg['bankroll_usd']:,.0f} i kupuje iz drugog izvora. Svi "
        f"prodaju po <b>istim pravilima izlaza</b> kao glavni demo bot (stop loss, take profit, smart sell, ono što je "
        f"alat naučio), pa je jedina razlika odakle je došla kupnja. Ulog je ${cfg['size_usd']:.0f} po tokenu, najviše "
        f"{cfg['max_open']} otvorenih i {cfg['per_hour']} novih na sat po računu"
        + ("; kad potroši $1000, nastavlja dalje u minus da alat uči na više tradeova" if not cfg.get("cash_limit", True)
           else "") + f". Signal koji vidimo kasnije od "
        f"{cfg['max_delay_min']} min se preskače. Bez pravog novca. Radi od "
        f"{time.strftime('%d.%m. %H:%M', time.gmtime(start))} UTC ({days:.1f} dana)."
        + (" <b>Pauzirano od 15.11.</b> (prekidač fokus_midcap): bez novih ulaza, otvorene pozicije se zatvaraju "
           "svojim izlazima; samo za čitanje." if paused else "")))
    order = sorted((s for s in summ if not s.get("baseline")), key=lambda s: -s["value"])
    h.append("<div class=grid>" + "".join(_card(s, i + 1, len(order), color[s["key"]])
                                          for i, s in enumerate(order)) + "</div>")
    ctrl = next((s for s in summ if s["key"] == "kontrola"), None)
    h.append(tdesc(
        "<b>Statusi</b> (audit 4.11.): <b>uči</b> = manje od 100 zatvorenih tradeova, nema presude; <b>kandidat</b> = "
        "po tradeu nakon troškova bolja od nasumičnog ulaza (kontrole) u obje polovice razdoblja i i bez 5 najboljih "
        "tradeova, to znači samo daljnje testiranje; <b>ne diraj pravi novac</b> = sve ostalo. Uz svaki rezultat piše "
        "i rezultat bez najboljeg tradea i tokena: ako plus tada nestane, rezultat je koncentriran, a ne profitabilan. "
        "„S pravih $1.000 bez posuđivanja” = isti tradeovi kad račun ne smije u minus (trade za koji nema novca se "
        "preskače); glavni broj iznad je istraživačka knjiga koja smije u minus da bot uči."))
    if ctrl:
        h.append("<div class=grid>" + _card(ctrl, 0, 0, color.get("kontrola", "#94a3b8")).replace("0. od 0 · ", "Mjerilo · ")
                 + "</div>")
    total = sum(s["closed"] for s in summ)
    if total < 20 * len(summ) and not paused:
        h.append(note(f"⏳ Još je rano: zatvoreno je {total} tradeova. Pouzdana usporedba treba barem ~20 zatvorenih "
                       f"po strategiji (obično 2–4 dana)."))
    if ctrl and ctrl["closed"] >= 10:
        beat = [s["name"] for s in summ if s["key"] != "kontrola" and s["value"] > ctrl["value"]]
        h.append(tdesc("🎲 Nasumični izbor je kontrola: " + (
            f"bolje od sreće zasad rade: <b>{esc(', '.join(beat))}</b>." if beat else
            "zasad ga nijedna strategija ne pobjeđuje, znači da izvori još ne donose prednost.")))

    h.append("<h2 id=graf>Stanje računa kroz vrijeme</h2>" + (_chart(eq, cfg) or tdesc(
        "Graf se crta nakon prve dvije snimke (svakih 15 min).")))

    rows = []
    for s in order:
        b, w = s["best"], s["worst"]
        rows.append([f'{esc(s["icon"])} {esc(s["name"])}', num(s["value"], "${:,.0f}"), _pct(s["ret"]),
                     signed(s["pnl_closed"], "${:+,.0f}"), num(s["closed"]), num(s["open"]),
                     (f"{s['hit']:.0%}" if s["hit"] is not None else "–", s["hit"] if s["hit"] is not None else -1, "n"),
                     _pct(s["avg_ret"]), _pct(s["med_ret"]), num(s["x2"]),
                     (f'{tlink(b["token"], b["symbol"])} {b["pnl_usd"]:+,.0f}$' if b else "–"),
                     (f'{tlink(w["token"], w["symbol"])} {w["pnl_usd"]:+,.0f}$' if w else "–")])
    h.append("<h2 id=usporedba>Usporedba brojki</h2>" + tdesc(
        "Vrijednost računa = slobodan novac + otvorene pozicije kao da ih prodaš sada (uračunat trošak i klizanje "
        "cijene). Uspješnost = udio zatvorenih tradeova u plusu. Prosječni i medijan rezultata su po tradeu.")
             + table(["Strategija", ("Vrijednost računa", "n"), ("Rezultat", "n"), ("Zarada zatvorenih", "n"),
                      ("Zatvoreno", "n"), ("Otvoreno", "n"), ("Uspješnost", "n"), ("Prosjek po tradeu", "n"),
                      ("Medijan po tradeu", "n"), ("Došlo do 2x", "n"), "Najbolji", "Najgori"], rows))

    rows = []
    for p in sorted(recent, key=lambda p: -(p["entry_ts"] or 0)):
        st = p["state"] or {}
        rows.append([f'<i style="display:inline-block;width:8px;height:8px;border-radius:4px;background:'
                     f'{color.get(p["strat"], "#999")}"></i> {esc(name.get(p["strat"], p["strat"]))}',
                     tlink(p["token"], p["symbol"]), esc(p["why"] or ""), (ago(p["entry_ts"])[0], p["entry_ts"], "n"),   # ago() is (text, sort key, class): the cell showed the tuple (4.11.)
                     num(p["entry_mcap"], "${:,.0f}"), num(p["size_usd"], "${:,.0f}"),
                     _pct(st.get("peak")), signed(p["pnl_usd"], "${:+,.2f}"), _pct(p["ret"]),
                     "otvoreno" if p["status"] == "open" else _exit(p["exit_reason"])])
    h.append("<h2 id=tradeovi>Tradeovi zadnjih 7 dana</h2>" + tdesc(
        "Svaka kupnja svake strategije: zašto je kupljeno, najviši rast nakon ulaza i kako je završilo. Isti token "
        "može kupiti više strategija, svaka sa svog računa.")
             + table(["Strategija", "Token", "Zašto", ("Kupljeno", "n"), ("Mcap na ulazu", "n"), ("Ulog", "n"),
                      ("Najviši rast", "n"), ("Zarada", "n"), ("Rezultat", "n"), "Izlaz"], rows, tid="strtr",
                     mints=[p["token"] for p in sorted(recent, key=lambda p: -(p["entry_ts"] or 0))]))

    if skips and not paused:
        rows = [[esc(name.get(k, k)), esc(r or "–"), num(n)] for k, r, n in sorted(skips, key=lambda x: -x[2])]
        h.append("<h2 id=preskoceno>Što nije kupljeno i zašto</h2>" + tdesc(
            "Signali koji su stigli, ali ih račun nije kupio (zadnjih 10 dana).")
                 + table(["Strategija", "Razlog", ("Broj", "n")], rows))
    if not paused:
        h.append(wallets_html(cfg))
    return "".join(h)


def wallets_html(cfg):
    """Which tracked wallets the "Top novčanici" account copies, by how our copies of them did (strat.run)."""
    from strat import run, store
    con = store.ro()
    if con is None:
        return ""
    try:
        rank = run.wallet_rank(con, cfg)
        top, out = run.wallets_allowed(con, cfg)
    finally:
        con.close()
    if not rank:
        return ""
    min_n = cfg.get("novcanici_min_n", 3)
    rows = [[esc(w), num(n), _pct(m), signed(p, "${:+,.2f}"),
             badge("kopira se (top)", "good") if w in top else badge("ne kopira se", "bad") if w in out
             else badge("još se mjeri", "")] for w, n, m, p in rank]
    return ("<h2 id=novcanici>Top novčanici: koje kopiramo</h2>" + tdesc(
        f"Kopiramo samo {cfg.get('novcanici_top', 10)} najboljih praćenih novčanika: onih čije su kupnje, kad smo ih "
        f"kopirali, prosječno najviše zaradile (barem {min_n} zatvorena tradea, prosjek u plusu, jedan trade najviše "
        f"+300%). Novi novčanik se kopira dok ne skupi {min_n} tradea; izmjereni koji nije u vrhu više se ne kopira.")
            + table(["Novčanik", ("Kopiranih tradeova", "n"), ("Prosjek po tradeu", "n"), ("Zarada", "n"), "Status"],
                    rows))


def report_data(now=None):
    """For the morning e-mail and the learning: ranking of the five accounts. None before the first entry."""
    from strat import run, store
    con = store.ro()
    if con is None:
        return None
    try:
        cfg = _cfg()
        s = run.summary(con, cfg, run.exit_rules(now or time.time()))
        day = (now or time.time()) - 86400
        d1 = dict(con.execute("SELECT strat, COALESCE(SUM(pnl_usd), 0) FROM positions WHERE status='closed' AND "
                              "closed_ts >= ? GROUP BY strat", (day,)).fetchall())
    finally:
        con.close()
    if not any(x["closed"] + x["open"] for x in s):
        return None
    return [{"key": x["key"], "name": x["name"], "value": round(x["value"], 2), "ret": round(x["ret"], 4),
             "closed": x["closed"], "open": x["open"], "hit": x["hit"], "pnl_24h": round(d1.get(x["key"], 0), 2),
             "status": x["status"][1], "no_best": round(x["robust"]["no_best"], 2)}
            for x in sorted((x for x in s if not x.get("baseline")), key=lambda x: -x["value"])]


def _verdict_box(summ):
    """'Što bih ja napravio' on top of the comparison (Nicholas 4.11.): the one sentence the statuses add up to."""
    if not summ:
        return ""
    st = {s["key"]: s for s in summ}
    kand = [s for s in summ if (s.get("status") or ("",))[0] == "kandidat"]
    ctrl = st.get("kontrola")
    best = max((s for s in summ if s["key"] != "kontrola"), key=lambda s: s["ret"], default=None)
    if kand:
        names = ", ".join(f"{s['icon']} {s['name']}" for s in kand)
        txt = (f"Kandidat za dalje testiranje: <b>{esc(names)}</b> — tuče nasumični ulaz po tradeu, u obje polovice "
               "razdoblja i bez 5 najboljih tradeova. Ni to još nije dozvola za pravi novac: pustio bih je da skupi "
               "200 zatvorenih pa odlučio.")
    elif best:
        s = best["status"] or ("", "", "")
        txt = (f"Ne bih stavljao pravi novac ni na jednu. Najbolje stoji <b>{esc(best['icon'])} {esc(best['name'])}</b> "
               f"({best['ret']:+.1%}), ali presuda je „{esc(s[1])}”: {esc(s[2])}."
               + (f" Nasumična kontrola je na {ctrl['ret']:+.1%}: strategija vrijedi tek kad je jasno iznad toga." if ctrl else ""))
    else:
        txt = "Još nema podataka."
    return f"<div class=card><p><b>Što bih ja napravio:</b> {txt} Svaka strategija ovdje je zaseban demo račun; što ih više mjerimo, alat brže uči što prolazi.</p></div>"
