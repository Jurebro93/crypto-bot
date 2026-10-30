"""The "Tržište" page: trading volume per launchpad (pump.fun, LaunchLab/bonk.fun, Meteora DBC…) and per trading
terminal, the whole Solana DEX trend, the market regime and the check of the hypothesis "more Solana volume =
more memecoin trading". Everything from market.db (run_market.py)."""
import datetime as dt

from market import regime, sources, store
from ui import data
from ui.html import ago, badge, bar, esc, num, signed, table, tdesc, tip, ts, usd

D = 86400
COLORS = {"launchpad": ("#2a78d6", "#3987e5"), "dex": ("#eb6834", "#d95926"), "price": ("#1baf7a", "#199e70")}
NAMES = {"launchpad": "Launchpadi (trenchevi)", "dex": "Solana DEX ukupno", "price": "Cijena SOL"}
LEVEL = {"vruće": "good", "neutralno": "", "hladno": "bad"}


def _pct(x):
    return signed(None if x is None else 100 * x, "{:+.0f}%")


def _spark(vals, w=110, h=24):
    vals = [v or 0 for v in vals]
    if len(vals) < 2 or not max(vals):
        return ""
    mx = max(vals)
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - 2 - (h - 4) * v / mx:.1f}" for i, v in enumerate(vals))
    return (f'<svg width={w} height={h} role=img aria-label="30 dana"><polyline points="{pts}" fill=none '
            f'stroke="var(--bar)" stroke-width=2 stroke-linejoin=round stroke-linecap=round /></svg>')


def _rolling7(ser, days):
    return {d: sum(ser[d - i * D] for i in range(7)) for d in days if all(ser.get(d - i * D) is not None for i in range(7))}


def _chart(con, day, n=90):
    """Indexed lines (first day = 100) so three different units share one axis: 7-day launchpad volume,
    7-day Solana DEX volume, SOL price. Hover a day for the raw numbers."""
    days = [day - i * D for i in range(n - 1, -1, -1)]
    lp = _rolling7(dict(store.series(con, "all:launchpad")), days)
    dx = _rolling7(dict(store.series(con, "all:dex")), days)
    pr = dict(con.execute("SELECT day, usd FROM price"))
    series = {"launchpad": lp, "dex": dx, "price": pr}
    days = [d for d in days if d in lp and d in dx]
    if len(days) < 10:
        return '<div class=empty>Još nema dovoljno dana za graf.</div>'
    idx = {}
    for k, s in series.items():
        base = next((s[d] for d in days if s.get(d)), None)
        idx[k] = {d: 100 * s[d] / base for d in days if s.get(d) and base}
    allv = [v for s in idx.values() for v in s.values()]
    lo, hi = min(allv + [100]) * 0.95, max(allv + [100]) * 1.05
    W, H, L, R, T, B = 900, 260, 44, 150, 10, 24
    x = lambda i: L + i * (W - L - R) / (len(days) - 1)  # noqa: E731
    y = lambda v: T + (H - T - B) * (hi - v) / (hi - lo)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:{W}px;height:auto" role=img '
           f'aria-label="Indeks volumena launchpada, Solana DEX volumena i cijene SOL, zadnjih {len(days)} dana">'
           '<style>.mk1{stroke:var(--c1)}.mk2{stroke:var(--c2)}.mk3{stroke:var(--c3)}'
           f'svg{{--c1:{COLORS["launchpad"][0]};--c2:{COLORS["dex"][0]};--c3:{COLORS["price"][0]}}}'
           f'@media(prefers-color-scheme:dark){{svg{{--c1:{COLORS["launchpad"][1]};--c2:{COLORS["dex"][1]};--c3:{COLORS["price"][1]}}}}}'
           '.hv:hover{fill:var(--line);fill-opacity:.5}</style>']
    for v in (lo + (hi - lo) * f for f in (0, .25, .5, .75, 1)):
        out.append(f'<line x1={L} x2={W - R} y1={y(v):.1f} y2={y(v):.1f} stroke="var(--line)" />'
                   f'<text x={L - 6} y={y(v) + 4:.1f} text-anchor=end font-size=11 fill="var(--mut)">{v:.0f}</text>')
    out.append(f'<line x1={L} x2={W - R} y1={y(100):.1f} y2={y(100):.1f} stroke="var(--mut)" stroke-dasharray="3 3" />')
    for i in (0, len(days) // 2, len(days) - 1):
        out.append(f'<text x={x(i):.1f} y={H - 6} text-anchor=middle font-size=11 fill="var(--mut)">'
                   f'{dt.datetime.fromtimestamp(days[i], dt.timezone.utc):%d.%m.}</text>')
    for n_, k in enumerate(("launchpad", "dex", "price"), 1):
        pts = [(x(i), y(idx[k][d])) for i, d in enumerate(days) if d in idx[k]]
        if not pts:
            continue
        out.append(f'<polyline class=mk{n_} points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill=none '
                   'stroke-width=2 stroke-linejoin=round stroke-linecap=round />')
        out.append(f'<text x={pts[-1][0] + 8:.1f} y={pts[-1][1] + 4:.1f} font-size=11 fill="var(--fg)">'
                   f'{NAMES[k]} {idx[k][days[-1]]:.0f}</text>' if days[-1] in idx[k] else "")
    step = (W - L - R) / (len(days) - 1)
    for i, d in enumerate(days):
        tt = (f"{dt.datetime.fromtimestamp(d, dt.timezone.utc):%d.%m.%Y}: launchpadi 7d {usd(lp.get(d))[0]}, "
              f"Solana DEX 7d {usd(dx.get(d))[0]}" + (f", SOL ${pr[d]:.2f}" if pr.get(d) else ""))
        out.append(f'<rect class=hv x={x(i) - step / 2:.1f} y={T} width={step:.1f} height={H - T - B} fill=transparent>'
                   f'<title>{esc(tt)}</title></rect>')
    out.append("</svg>")
    legend = " ".join(f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px">'
                      f'<i style="width:14px;height:2px;background:{COLORS[k][0]};display:inline-block"></i>{NAMES[k]}</span>'
                      for k in ("launchpad", "dex", "price"))
    return f'<div class=card><div class=mut style="margin-bottom:6px">{legend}</div>{"".join(out)}</div>'


def _platforms(con, grp, day):
    rows = con.execute(
        """SELECT p.slug, p.name,
                  SUM(CASE WHEN d.day=? THEN d.volume END),
                  SUM(CASE WHEN d.day>? THEN d.volume END),
                  SUM(CASE WHEN d.day<=? AND d.day>? THEN d.volume END)
           FROM daily d JOIN platforms p ON p.slug=d.slug WHERE p.grp=? AND d.day>?
           GROUP BY p.slug HAVING SUM(CASE WHEN d.day>? THEN d.volume END) >= 10000 ORDER BY 4 DESC""",
        (day, day - 7 * D, day - 7 * D, day - 14 * D, grp, day - 30 * D, day - 7 * D)).fetchall()
    total = sum(r[3] or 0 for r in rows) or 1
    out = []
    for slug, name, y1, v7, p7 in rows:
        spark = [v for _, v in store.series(con, slug, day - 29 * D)]
        out.append([esc(sources.label(slug, name)), usd(y1), usd(v7), _pct(v7 / p7 - 1 if v7 and p7 else None),
                    (f"{bar(v7, total, 60)} {100 * (v7 or 0) / total:.0f}%", v7 or 0, "n"), _spark(spark)])
    return out


def _days(con, day, n=30):
    lp = dict(store.series(con, "all:launchpad", day - (n + 1) * D))
    dx = dict(store.series(con, "all:dex", day - (n + 1) * D))
    tm = dict(store.series(con, "all:terminal", day - (n + 1) * D))
    pr = dict(con.execute("SELECT day, usd FROM price WHERE day>?", (day - (n + 1) * D,)))
    rg = {d: (s, lb) for d, s, lb in con.execute("SELECT day, score, label FROM regime WHERE day>?", (day - (n + 1) * D,))}
    rows = []
    for i in range(n):
        d = day - i * D
        ch = lambda s: (s[d] / s[d - D] - 1) if s.get(d) and s.get(d - D) else None  # noqa: E731
        r = rg.get(d)
        rows.append([ts(d, "%d.%m. %a"), usd(lp.get(d)), _pct(ch(lp)), usd(dx.get(d)), _pct(ch(dx)), usd(tm.get(d)),
                     (f"{100 * lp[d] / dx[d]:.1f}%", lp[d] / dx[d], "n") if lp.get(d) and dx.get(d) else num(None),
                     num(pr.get(d), "${:,.2f}"), _pct(ch(pr)),
                     (badge(f"{r[1]} {r[0]:.0f}", LEVEL.get(r[1], "")), r[0], "") if r else ("–", -1, "")])
    return rows


def _trades(con):
    """Our closed demo trades grouped by the regime that was known when they were opened."""
    trades = data.q(data.PAPER_DB, "SELECT opened_ts, ret, pnl_usd FROM trades WHERE status='closed' AND opened_ts IS NOT NULL")
    groups = {}
    for t in trades:
        r = regime.at(t["opened_ts"], con)
        groups.setdefault(r["label"] if r else "nepoznat", []).append(t)
    rows = []
    for lb in ("vruće", "neutralno", "hladno", "nepoznat"):
        g = groups.get(lb)
        if not g:
            continue
        rets = [t["ret"] or 0 for t in g]
        wins = sum(1 for x in rets if x > 0)
        rows.append([badge(lb, LEVEL.get(lb, "")), num(len(g)), num(100 * wins / len(g), "{:.0f}%"),
                     signed(100 * sum(rets) / len(g), "{:+.1f}%"), signed(sum(t["pnl_usd"] or 0 for t in g), "{:+,.0f}")])
    return rows


def page(qs):
    head = ("<h1>Tržište: volumen po platformama</h1>"
            "<p class=mut>Koliko se trejda na kojem launchpadu (pump.fun, bonk.fun, Meteora…) i u kojim terminalima, "
            "kako se kreće cijeli Solana DEX volumen i je li tržište trencheva sada vruće ili hladno. "
            "Izvor: DefiLlama (besplatno), provjerava se svaki sat, a DefiLlama brojeve osvježava jednom dnevno, pa su svi brojevi za pune UTC dane.</p>")
    con = store.ro()
    if con is None:
        return "Tržište", head + '<div class=empty>Još nema market.db: pokreni <code>python3 run_market.py collect</code> (server to radi svaki sat).</div>'
    try:
        day = con.execute("SELECT MAX(day) FROM daily WHERE slug='all:launchpad'").fetchone()[0]
        if not day:
            return "Tržište", head + '<div class=empty>market.db je još prazan.</div>'
        r = regime.current(con)
        h = regime.hypothesis(con)
        snap = con.execute("SELECT MAX(ts) FROM snap").fetchone()[0]
        body = [head]
        if r:
            f = r["features"]
            stats = [
                (f'{badge(r["label"].upper(), LEVEL.get(r["label"], ""))} {r["score"]:.0f}/100',
                 "režim tržišta " + tip("Prosjek tri ranga u zadnjih 90 dana: volumen launchpada (7 d), volumen cijele "
                                        "Solane (7 d) i rast launchpada tjedan na tjedan. 66+ vruće, 33 i manje hladno. "
                                        "Scoring ga može koristiti kao značajku market_regime (0-1).")),
                (usd(f["launchpad_7d"])[0] + f' <small>{_pct(f["launchpad_growth7d"])[0]}</small>', "launchpadi zadnjih 7 dana (vs tjedan prije)"),
                (usd(f["dex_7d"])[0] + f' <small>{_pct(f["dex_growth7d"])[0]}</small>', "cijeli Solana DEX zadnjih 7 dana"),
                (usd(f["terminal_7d"])[0] + f' <small>{_pct(f["terminal_growth7d"])[0]}</small>' if f.get("terminal_7d") else "–",
                 "trading terminali i botovi 7 dana"),
                (f'{100 * f["launchpad_share"]:.1f}%' if f.get("launchpad_share") else "–", "udio launchpada u Solana DEX volumenu"),
                (f'${f["sol_price"]:.2f} <small>{_pct(f["sol_price_7d"])[0]}</small>' if f.get("sol_price") else "–", "cijena SOL (7 d promjena)"),
            ]
            body.append(f'<p class=mut>Režim za {ts(r["day"], "%d.%m.%Y")[0]} (zadnji puni dan)'
                        + (f', zadnja provjera izvora {ago(snap)[0]}' if snap else "") + "</p>")
            body.append('<div class=grid>' + "".join(f'<div class=stat><div class=v>{v}</div><div class=l>{lb}</div></div>'
                                                     for v, lb in stats) + "</div>")
        else:
            body.append('<div class=card>Režim još nije izračunat: treba barem ~100 dana povijesti (skida se pri prvom pokretanju).</div>')
        body.append(f'<h2>Hipoteza: kad raste volumen na Solani, trejda se više shitcoina?</h2><div class=card>{esc(regime.verdict(h))}'
                    "<br><span class=mut>Korelacija dnevnih promjena: +1 = uvijek zajedno, 0 = nema veze, −1 = suprotno. "
                    "Solana DEX ovdje ne uključuje PumpSwap (to su graduirani pump.fun tokeni), da se trenchevi ne broje dvaput.</span></div>")
        if h:
            hrows = [["Isti dan: Solana DEX ↔ launchpadi", signed(h["same_day"])],
                     ["Solana DEX danas → launchpadi sutra", signed(h["lead1"])],
                     ["Cijena SOL ↔ launchpadi", signed(h["price"])],
                     ["Tjedni smjer isti (rast/pad)", num(None if h["week_agree"] is None else 100 * h["week_agree"], "{:.0f}%")]]
            body.append(tdesc(f"Provjera na zadnjih {h['days']} dana, računa se iznova svaki sat.")
                        + table(["Usporedba", ("Vrijednost", "n")], hrows))
        body.append("<h2>Trend (indeks, prvi dan = 100)</h2>" + tdesc(
            "Volumen launchpada i cijelog Solana DEX-a kao zbroj zadnjih 7 dana, i cijena SOL, sve preračunato da prvi dan bude 100, "
            "pa se vidi tko raste brže. Prijeđi mišem preko dana za prave brojeve.") + _chart(con, day))
        cols = ["Platforma", ("Jučer", "n"), ("7 dana", "n"), ("Promjena 7d", "n"),
                ("Udio", "n"), "30 dana"]
        body.append("<h2>Launchpadi (trenchevi)</h2>" + tdesc(
            "Gdje se tokeni rađaju i trejdaju na bonding curveu. bonk.fun radi na Raydium LaunchLabu, Bags i Believe na Meteora DBC. "
            "Platforme ispod $10k tjedno su skrivene.") + table(cols, _platforms(con, "launchpad", day)))
        body.append("<h2>Trading terminali i botovi</h2>" + tdesc(
            "Aplikacije kroz koje trench trejderi kupuju (Axiom, GMGN, Photon, BullX, Trojan…), samo Solana dio. "
            "Taj volumen je već uključen u DEX-ove ispod njih, ovdje je zato što pokazuje koliko je trenchera aktivno.")
                    + table(cols, _platforms(con, "terminal", day)))
        body.append("<h2>Najveći Solana DEX-ovi</h2>" + tdesc("Top 15 po volumenu u zadnjih 7 dana, za usporedbu s launchpadima.")
                    + table(cols, _platforms(con, "dex", day)[:15]))
        body.append("<h2>Po danu (30 dana)</h2>" + tdesc("Puni UTC dani. Udio = koliki dio cijelog Solana DEX volumena ide kroz launchpade.")
                    + table(["Dan", ("Launchpadi", "n"), ("Promjena", "n"), ("Solana DEX", "n"), ("Promjena DEX", "n"),
                             ("Terminali", "n"), ("Udio", "n"), ("SOL", "n"), ("Promjena SOL", "n"), "Režim"], _days(con, day)))
        body.append("<h2>Naši demo tradeovi po režimu</h2>" + tdesc(
            "Zatvoreni demo tradeovi podijeljeni po režimu koji je bio poznat u trenutku kupnje. Ako vruće tržište stvarno pomaže, "
            "win rate i prosječni povrat bi trebali biti viši u redu vruće.")
                    + table(["Režim", ("Tradeova", "n"), ("Win", "n"), ("Prosj. povrat", "n"), ("PnL $", "n")], _trades(con),
                            empty="Još nema zatvorenih demo tradeova."))
        return "Tržište", "".join(body)
    finally:
        con.close()
