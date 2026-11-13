"""Top of the Influenceri page in plain words (like Učenje): what the data says right now, then the two new
sections "Zovu zajedno" (kol/together.py) and "Plaćeni shilleri" (kol/shillers.json). Only reads kol.db / tg.db."""
import json
import time
import statistics

from kol import shillers, together
from ui.html import badge, esc, lead as _lead, num, table, tdesc, tip

FEE = 0.02   # buy + sell fee and slippage, roughly, for the "na $100" line


def _p(x, sign=False):
    if x is None:
        return "–"
    return f"{x:+.0%}" if sign else f"{x:.0%}"


def _cell(x, sign=False):
    return (_p(x, sign), -9 if x is None else x, "n")


def _handle_name(h):
    return f"✈ {h[3:]}" if h.startswith("tg:") else f"@{h}"


def _link(h):
    from urllib.parse import quote
    return f'<a href="/kol/{quote(h)}">{esc(_handle_name(h))}</a>'


def _validate_word(con):
    from kol import validate
    v = validate.load(con) or {}
    return {"prolazi": ("prolazi test", "good"), "pada": ("pada test", "bad"), "nejasno": ("još nije dokazana", "warn"),
            "malo": ("premalo podataka", "warn")}.get(v.get("state"), ("još se računa", "warn"))


def proven(con, cfg, limit=None):
    """Proven KOLs (not on trial, not bots, score >= good_score), best by the lower end of the score range."""
    out = []
    for h, sc, st in con.execute("SELECT handle, score, stats FROM kols WHERE score IS NOT NULL"):
        s = json.loads(st or "{}")
        if s.get("trial") or (sc or 0) < cfg["good_score"]:
            continue
        out.append((s.get("score_lo") if s.get("score_lo") is not None else sc, h, sc, s))
    out.sort(key=lambda r: -r[0])
    return out[:limit] if limit else out


def shill_rows(con, tg_status=None):
    """One row per listed account: (handle, platform, status, stats dict or {}, measured calls summary)."""
    tg_status = tg_status or {}
    stats = {h.lower(): (h, sc, json.loads(st or "{}")) for h, sc, st in
             con.execute("SELECT handle, score, stats FROM kols")}
    calls = {}
    for h, r1h, m24, r24, rug in con.execute(
            "SELECT LOWER(handle), r1h, max24, r24h, COALESCE(rug, 0) FROM calls WHERE kind = 'call' "
            "AND first_by_kol = 1 AND max24 IS NOT NULL AND bad IS NULL"):
        calls.setdefault(h, []).append((r1h, m24, r24, rug))
    # does the token still trade? pair = found on DexScreener; no pair after 3 lookups = gone (dead or never left
    # the pump.fun curve). Old calls of gone tokens cannot be priced, but how many died is itself the answer.
    alive = {}
    for h, n_all, n_live, n_gone in con.execute(
            "SELECT LOWER(c.handle), COUNT(DISTINCT c.token), COUNT(DISTINCT CASE WHEN t.pair IS NOT NULL THEN c.token END), "
            "COUNT(DISTINCT CASE WHEN t.pair IS NULL AND t.tries >= 3 THEN c.token END) FROM calls c "
            "LEFT JOIN tokens t ON t.token = c.token WHERE c.kind = 'call' GROUP BY LOWER(c.handle)"):
        alive[h] = (n_all, n_live, n_gone)
    rows = []
    for e in shillers.entries():
        for kind, names in (("tg", e.get("tg", [])), ("x", e.get("x", []))):
            for n in names:
                key = ("tg:" + n.lower()) if kind == "tg" else n.lower()
                h, sc, s = stats.get(key, (key if kind == "tg" else n, None, {}))
                cs = calls.get(key, [])
                r1 = [c[0] for c in cs if c[0] is not None]
                summ = {"n": len(cs), "hit": (sum(1 for c in cs if (c[1] or 0) >= 1.0) / len(cs)) if cs else None,
                        "rug": (sum(1 for c in cs if c[3] or (c[2] is not None and c[2] <= -0.9)) / len(cs)) if cs else None,
                        "usd1h": (100 * (statistics.mean(r1) - FEE)) if r1 else None}
                n_all, n_live, n_gone = alive.get(key, (0, 0, 0))
                summ.update(tokens=n_all, live=n_live, gone=n_gone,
                            alive=(n_live / (n_live + n_gone)) if n_live + n_gone else None)
                st = tg_status.get(n.lower()) if kind == "tg" else None
                rows.append({"handle": h, "kind": kind, "tg_status": st, "score": sc, "s": s, "c": summ,
                             "price": e.get("price"), "note": e.get("note")})
    # same account listed twice (e.g. in two sheets): keep the first
    seen, out = set(), []
    for r in rows:
        k = r["handle"].lower()
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def shill_verdict(r, min_calls):
    c = r["c"]
    if r["kind"] == "tg" and r["tg_status"] == "dead":
        return "nedostupan", "Privatni kanal ili osobni račun: bez Telegram računa ne možemo čitati.", "mut"
    if r["kind"] == "tg" and r["tg_status"] in (None, "candidate"):
        return "čeka", "Kanal je dodan, prvo čitanje stiže u sljedećih sat vremena.", "mut"
    if not c["n"] and c.get("alive") is not None and c["live"] + c["gone"] >= 10 and c["alive"] < 0.1:
        return "loš", (f"Od {c['live'] + c['gone']} tokena koje je zvao danas se trguje samo {c['live']} "
                       f"({c['alive']:.0%}); ostali su mrtvi."), "bad"
    if not c["n"]:
        if c.get("tokens"):
            return "čeka mjerenje", f"Zvao {c['tokens']} tokena; cijene se mjere automatski.", "mut"
        return "bez poziva", "Još nismo vidjeli nijedan poziv tokena na Solani.", "mut"
    if c["n"] >= 5 and (c["rug"] or 0) >= 0.5:
        return "loš", f"{c['rug']:.0%} njegovih poziva završi kao rug.", "bad"
    if c["n"] < 5:
        return "premalo", f"Tek {c['n']} izmjerenih poziva: premalo za ocjenu.", "warn"
    if not r["s"].get("trial") and (r["score"] or 0) >= 50:
        return "dokazan", "Dokazao se na dovoljno poziva: ulazi u signale kao i drugi dobri KOL-ovi.", "good"
    if (c["hit"] or 0) >= 0.5:
        return "obećava", (f"Udvostruči se {c['hit']:.0%} poziva, ali treba {min_calls}+ poziva i sigurnu ocjenu "
                           "da uđe u signale."), "warn"
    return "slab", f"Udvostruči se samo {c['hit']:.0%} poziva.", "bad"


def _tg_status():
    try:
        from tg import store as tstore
        con = tstore.ro()
        if con is None:
            return {}
        try:
            return dict(con.execute("SELECT name, status FROM channels"))
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return {}


def top_html(con, cfg, tog=None):
    """The card at the top: one verdict line, three numbers, what the data says in plain words."""
    from ui.learnprogress import CSS
    tog = tog or together.build(con, shillers.handles())
    good = proven(con, cfg)
    s = tog["sizes"]
    many = together._merge(s["3"], s["4+"])
    vw, vcls = _validate_word(con)
    rows = shill_rows(con, _tg_status())
    mc = shillers.cfg(cfg)["min_calls"]
    verd = [shill_verdict(r, mc)[0] for r in rows]
    line = (f"Pratimo {num(con.execute('SELECT COUNT(*) FROM kols').fetchone()[0])[0]} računa; "
            f"{len(good)} {'je prošao' if len(good) == 1 else 'je prošlo'} probu.")
    if not good:   # 4.11.: "0 se dokazalo" read as "nobody is any good"; it is the trial, and history counts for it
        from kol import discover
        t = discover.dcfg(cfg)["trial"]
        line += (f" Proba: {t['min_calls']} izmjerenih poziva, {t['days']} dana od prvog poznatog poziva (povijesni "
                 f"pozivi se računaju) i objave koje netko vidi; uz to ocjena {cfg['good_score']}+.")
    if many["n"] >= together.MIN_N and s["1"]["n"] >= together.MIN_N and many["hit"] and s["1"]["hit"]:
        line += (f" Kad zovu 3+ zajedno, token se udvostruči u {_p(many['hit'])} slučajeva "
                 f"(jedan sam: {_p(s['1']['hit'])}).")
    out = [CSS, "<div class=uc-top>", f"<p class=uc-v>{esc(line)}</p>",
           "<p class=uc-sub>Brojke su iz cijene tokena 24 h nakon prvog poziva. „Udvostruči se” = cijena je barem 2× "
           "unutar 24 h. " + tip("Gledamo prvi poziv na token, pa kasni poziv nakon pumpe ne može popraviti "
                                 "rezultat. Rug = token je pao 90%+ ili mu je nestala likvidnost.") + "</p>",
           "<div class=uc-kpi>",
           f"<div><div class=l>Dokazanih influencera</div><div class=n>{len(good)}</div>"
           f"<div class=o>ocjena {cfg['good_score']}+ i izašli s probe</div></div>",
           f"<div><div class=l>Zovu zajedno (3+)</div><div class=n>{_p(many['hit'])}</div>"
           f"<div class=o>udvostruči se; sam: {_p(s['1']['hit'])}</div></div>",
           f"<div><div class=l>Točnost ocjene</div><div class=n style='font-size:15px'>"
           f"{badge(vw, vcls)}</div><div class=o>test na novim pozivima</div></div>",
           "</div><ul class=uc-ul>"]
    for _, h, sc, st in good[:3]:
        out.append(f"<li>{_link(h)}: {_p(st.get('hit_rate'))} od {st.get('measured', 0)} poziva naraste {cfg['hit_x']:.0%}+ "
                   f"u 24 h, "
                   f"medijan najboljeg rasta {_p(st.get('med_max24'), True)}, rugova {_p(st.get('rug_rate'))}.</li>")
    if not good:
        out.append("<li>Još nitko nije prošao probu (dovoljno poziva i dana praćenja). To je namjerno: jedan sretan "
                   "poziv nije dokaz.</li>")
    for ln in together.verdict(tog)[:2]:
        out.append(f"<li>{esc(ln)}</li>")
    if rows:
        n_dead = verd.count("nedostupan")
        n_meas = sum(1 for r in rows if r["c"]["n"])
        bad = verd.count("loš") + verd.count("slab")
        out.append(f"<li>Tvoja lista plaćenih shillera: {len(rows)} računa, {n_meas} s izmjerenim pozivima, "
                   f"{bad} loših ili slabih, {n_dead} nedostupnih (privatni ili osobni). Dok se ne dokažu, ne "
                   "ulaze u signale ni praćenje uživo.</li>")
    out.append("</ul><a class=uc-go href=/korelacije>Mreže računa i walleta jednog vlasnika: <b>Korelacije →</b></a>"
               "</div>")
    return "".join(out)


def together_html(con, cfg, tog=None):
    tog = tog or together.build(con, shillers.handles())
    out = ["<h2 id=zajedno>Zovu zajedno</h2>", '<p class=mut>Novo (9.11.): <a href="/ekipe">Ekipe i minutna provjera</a>: '
           "mogu li se nakon poziva ekipe ili računa uzeti +5/10/15/20/30 % prije stopa, po minutnim svijećama od minute "
           "poziva.</p>", tdesc(
        f"Više računa (X i Telegram) zove isti token unutar {cfg['group_secs'] // 60} min. Uspoređujemo kako prođe "
        "token kad ga zove jedan račun i kad ga zove gužva, i tražimo ekipe koje to rade stalno (češće nego što bi "
        "dala slučajnost).")]
    out.append("<ul class=uc-ul>" + "".join(f"<li>{esc(x)}</li>" for x in together.verdict(tog)) + "</ul>")
    names = {"1": "Zove samo jedan", "2": "Zovu dvojica", "3": "Zovu trojica", "4+": "Zovu 4 ili više"}

    def row(label, st):
        faded = st["n"] < together.MIN_N
        lab = f"<span class=mut>{esc(label)}</span>" if faded else esc(label)
        return [lab, num(st["n"]), _cell(st["hit"]), _cell(st["med"], True), _cell(st["rug"]), _cell(st["late"])]
    head = ["Tko zove", ("Tokena", "n"), ("Udvostruči se", "n"), ("Medijan rasta", "n"), ("Rug", "n"),
            ("Već napumpan", "n")]
    out.append("<h3>Po broju računa</h3>" + table(head, [row(names[k], v) for k, v in tog["sizes"].items()],
                                                   tid="tg_size", empty="Još nema izmjerenih poziva."))
    mixes = [row(k, v) for k, v in tog["mixes"].items() if v["n"]]
    mixes += [row(k, v) for k, v in tog["shills"].items() if v["n"]]
    if mixes:
        out.append("<h3>Po mreži i plaćenim shillerima</h3>" + table(head, mixes, tid="tg_mix"))
    cl = tog["clusters"]
    rows = []
    for c in cl[:5]:   # 7.11. (Jure): 15+ groups confused everyone; the five strongest, the rest is in the data
        st = c["stats"]
        mem = ", ".join(_link(h) for h in c["members"][:8]) + (f" i još {len(c['members']) - 8}"
                                                               if len(c["members"]) > 8 else "")
        tag = (" " + badge("plaćeni shill", "warn")) if c["shill"] else ""
        if st["n"] >= 3 and (st["hit"] or 0) >= 0.5 and (st["rug"] or 0) < 0.4:
            what = badge("prati ih", "good")
        elif st["n"] >= 3 and ((st["rug"] or 0) >= 0.5 or (st["hit"] or 0) < 0.3):
            what = badge("izbjegavaj", "bad")
        else:
            what = badge("gledaj", "warn")
        lead = (f"{_link(c['leader'])} ({c['lead_share']:.0%})" if c["leader"] else "–")
        rows.append([what + tag, (mem, "", "wrap"), num(len(c["members"])), num(c["tokens"]), lead,
                     _cell(st["hit"]), _cell(st["rug"]), (f"{c['best_lift']:.0f}×", c["best_lift"], "n")])
    out.append("<h3>Ekipe koje stalno zovu zajedno</h3>" + _lead(
        "Računi koji puno češće nego slučajno zovu iste tokene. Prati ih ili izbjegavaj piše u prvom stupcu.") + tdesc(
        "Računi koji zovu iste tokene puno češće nego što bi dala slučajnost (test slučajnosti na parovima). "
        "Prvi = tko najčešće zove prvi; njega vrijedi pratiti. Prati ih = više od pola tokena se udvostruči, malo rugova. "
        "Izbjegavaj = puno rugova ili rijetko rastu (često plaćena kampanja).")
        + table(["Što napraviti", "Računi", ("Računa", "n"), ("Zajedničkih tokena", "n"), "Zove prvi",
                 ("Udvostruči se", "n"), ("Rug", "n"), ("Češće od slučaja", "n")], rows, tid="tg_cl",
                empty="Još nema ekipe koja prolazi test slučajnosti (treba 3+ zajednička tokena)."))
    return "".join(out)


def shill_html(con, cfg):
    rows = shill_rows(con, _tg_status())
    if not rows:
        return ""
    mc = shillers.cfg(cfg)["min_calls"]
    order = {"dokazan": 0, "obećava": 1, "slab": 2, "loš": 3, "premalo": 4, "čeka mjerenje": 5, "bez poziva": 6,
             "čeka": 7, "nedostupan": 8}
    data = []
    for r in rows:
        v, why, cls = shill_verdict(r, mc)
        c = r["c"]
        net = ("–", -1e9, "n") if c["usd1h"] is None else (f"{c['usd1h']:+.0f} $", c["usd1h"], "n")
        data.append((order[v], -(c["usd1h"] or -1e9), [
            badge(v, cls), _link(r["handle"]) + f" <span class=mut>{'Telegram' if r['kind'] == 'tg' else 'X'}</span>",
            num(c["tokens"]), num(c["n"]), _cell(c["alive"]), _cell(c["hit"]), _cell(c["rug"]), net, (esc(why), "", "wrap"),
            (esc(r.get("price") or ""), "", "wrap mut")]))
    data.sort(key=lambda x: (x[0], x[1]))
    # accounts with nothing to show yet: one line of names instead of a card each (110 cards on a phone is a wall)
    quiet_v = (order["bez poziva"], order["čeka"], order["nedostupan"])
    groups = {}
    for r in rows:
        v = shill_verdict(r, mc)[0]
        if order[v] in quiet_v:
            groups.setdefault(v, []).append(_link(r["handle"]))
    data = [d for d in data if d[0] not in quiet_v]
    words = {"bez poziva": "Još bez ijednog poziva tokena na Solani (možda zovu samo ETH/BSC ili ne objavljuju)",
             "čeka": "Dodani, čekaju prvo čitanje", "nedostupan": "Nedostupni: privatni kanal ili osobni račun"}
    tail = "".join(f"<p class=uc-small><b>{esc(words[k])} ({len(v)}):</b> {', '.join(v)}</p>"
                   for k, v in groups.items())
    return ("<h2 id=shilleri>Plaćeni shilleri s tvoje liste</h2>" + tdesc(
        "Kanali i računi iz tvoje tablice koje si plaćao za promociju. Pratimo ih kao sve ostale i mjerimo svaki "
        f"njihov poziv, ali dok ne dokažu {mc}+ poziva i sigurnu ocjenu, ne ulaze u signale, praćenje uživo ni copy "
        "trading. Na $100 = prosječni ishod ulaza na poziv i izlaza nakon 1 h, nakon ~2% troškova. Još živo = koliko "
        "tokena koje je zvao se danas još trguje (ostali su mrtvi ili nikad nisu izašli s pump.funa). Stari pozivi "
        "pune se sami iz povijesti kanala, nekoliko kanala na sat; stari mrtvi tokeni nemaju cijenu, pa se za njih "
        "vidi samo koliko ih je umrlo.")
            + table(["Ocjena", "Račun", ("Zvao tokena", "n"), ("Izmjereno", "n"), ("Još živo", "n"),
                     ("Udvostruči se", "n"), ("Rug", "n"),
                     ("Na $100 (1 h)", "n"), "Zašto", "Cijena objave (tvoja tablica)"],
                    [d[2] for d in data], tid="kshill",
                    empty="Još nijedan račun s tvoje liste nema izmjeren poziv; povijest kanala se puni sama.")
            + tail)


def _sentence(s, cfg):
    """One plain line about a KOL from his stats."""
    bits = []
    n = s.get("measured", 0)
    if s.get("hit_rate") is not None:
        bits.append(f"{s['hit_rate']:.0%} poziva naraste {cfg['hit_x']:.0%}+")
    if (s.get("first_rate") or 0) >= 0.4:
        bits.append("često zove prvi")
    if (s.get("prepump_rate") or 0) >= 0.4:
        bits.append("često kasni (zove nakon pumpe)")
    if (s.get("rug_rate") or 0) >= 0.3:
        bits.append(f"puno rugova ({s['rug_rate']:.0%})")
    elif s.get("rug_rate") is not None:
        bits.append("malo rugova")
    return f"{n} poziva: " + ", ".join(bits) + "."


def leaders_html(con, cfg, limit=8):
    """The best accounts in words, above the big table: proven first, then the most promising on trial."""
    rows = []
    for h, sc, st in con.execute("SELECT handle, score, stats FROM kols WHERE score IS NOT NULL"):
        s = json.loads(st or "{}")
        lo = s.get("score_lo") if s.get("score_lo") is not None else sc
        rows.append((bool(s.get("trial")), -(lo or 0), h, sc, s))
    rows.sort(key=lambda r: (r[0], r[1]))
    if not rows:
        return ""
    out = ["<ul class=uc-ul>"]
    for trial, _, h, sc, s in rows[:limit]:
        tag = (badge("na probi", "warn") if trial else badge("dokazan", "good") if (sc or 0) >= cfg["good_score"]
               else badge("prosječan", ""))
        if s.get("paid_shill"):
            tag += " " + badge("plaćeni shill", "warn")
        out.append(f"<li>{tag} {_link(h)} <span class=mut>ocjena {sc:.0f}</span>: {esc(_sentence(s, cfg))}</li>")
    out.append("</ul><p class=uc-small>Sve brojke za svakoga su u tablici ispod (Stupci = odaberi što vidiš).</p>")
    return "".join(out)


def _mc(x):
    if not x:
        return ("–", -1, "n")
    txt = f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}k"
    return (txt, x, "n")


TG_MIN = 10  # fewer calls than this: no percentage (1 of 1 = 100% is luck)


def tg_history_html():
    """Telegram callers over the last 6 months from Nicholas's Call Analyser + SpyDefi exports (kol/tg_history.json)."""
    import os
    import time
    from ui.html import ago
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "tg_history.json")
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return ""
    rows = d.get("rows") or []
    if not rows:
        return ""
    now = time.time()
    n50 = lambda r: r.get("n50", r["calls"])
    h2 = lambda r: r["hit2_50"] if r.get("hit2_50") is not None else r["hit2"]
    h5 = lambda r: r["hit5_50"] if r.get("hit5_50") is not None else r["hit5"]
    def lo(r):  # Wilson lower bound: 7 of 11 does not outrank 29 of 50
        n, p = n50(r), h2(r)
        z = 1.64
        return (p + z * z / (2 * n) - z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / (1 + z * z / n) if n else 0
    rows = sorted(rows, key=lambda r: (n50(r) < TG_MIN, -lo(r) if n50(r) >= TG_MIN else -n50(r)))
    ok = [r for r in rows if n50(r) >= TG_MIN]
    med = statistics.median(h2(r) for r in ok) if ok else None
    top = [r for r in ok if r["last"] >= now - 30 * 86400 and n50(r) >= 20][:5]
    lines = [f"{len(ok)} Telegram kanala ima barem {TG_MIN} poziva; tipičan od njih udvostruči {_p(med)} "
             f"zadnjih poziva. Kanali s manje poziva nemaju postotak, jer bi bio slučajan."]
    if top:
        lines.append("Najbolji aktivni (barem 20 poziva): " + ", ".join(
            f"{_link('tg:' + r['chan'])} ({_p(h2(r))} od {n50(r)})" for r in top) + ".")
    out = ["<h2 id=tgpovijest>Telegram calleri: zadnjih 50 poziva</h2>", tdesc(
        "Iz tvojih izvoza: Call Analyser bilježi svaki poziv kanala (CA i mcap u trenutku poziva), a SpyDefi koliko je "
        "puta token narastao od poziva. Za svaki kanal gledamo njegovih zadnjih 50 poziva (u zadnjih 6 mjeseci) i koliko "
        "ih je otišlo barem 2× i 5×. To je vrh nakon poziva, ne nužno zarada: tko kupi kasno ili ne proda na vrhu, "
        f"dobije manje. Postotak pokazujemo tek od {TG_MIN} poziva. Samo kanali koje oba izvora prate; zadnjih 30 dana "
        "aktivni se sad čitaju uživo i mjere kao svi ostali."),
           "<ul class=uc-ul>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul>"]
    data = []
    for r in rows:
        n = n50(r)
        few = n < TG_MIN
        if few:
            v = badge("premalo poziva", "")
        elif n >= 20 and h2(r) >= 0.4:
            v = badge("jak", "good")
        elif h2(r) < 0.15:
            v = badge("slab", "bad")
        else:
            v = badge("prosječan", "warn")
        act = badge("aktivan", "good") if r["last"] >= now - 30 * 86400 else badge("utihnuo", "")
        pct = (lambda x: ("–", -1, "n")) if few else _cell
        data.append([v, _link("tg:" + r["chan"]), num(n), pct(h2(r)), pct(h5(r)), num(r["calls"]),
                     (f"{r['max_x']:.0f}×", r["max_x"], "n"), _mc(r.get("med_mcap")), act,
                     ago(r["last"])])
    out.append(table(["Ocjena", "Kanal", ("Zadnjih poziva", "n"), ("Barem 2×", "n"), ("Barem 5×", "n"),
                      ("Poziva u 6 mj.", "n"), ("Najviše", "n"), ("Mcap u pozivu", "n"), "Stanje", "Zadnji poziv"],
                     data, tid="ktghist"))
    return "".join(out)


# ---------- jedna presuda za influencera (10.11., Jure, prijedlog 4.0) ---------------------------------------------
# Isti račun je imao tri ocjene: Autopilot ga bira po minutnoj mjeri (kol/minute.py, +10 % prije stopa −20 % u
# 60 min), ljestvica ga zove "dokazan" po vrhu +50 % u 24 h, a profil pokazuje cijenu 24 h poslije (calls.r24h).
# Odsad svuda dva broja istim imenom i redom, 1 h i 24 h, i jedna presuda iz njih. Pragovi su prijedlog; Jure bira.
VERDICT_H1 = 0.50        # udio poziva do +10 % prije stopa u prvom satu
VERDICT_D24 = 0.40       # udio poziva u plusu dan kasnije
VERDICT_MIN_N = 5        # manje izmjerenih poziva u razdoblju = "premalo poziva"
VERDICT_WINDOWS = (7, 14, 30)
VERDICT_TTL = 300        # s: jedna priručna kopija po razdoblju, svima ista (podaci se mijenjaju svakih ~20 min)
VERDICT_WORD = {"drzi_se": "drži se", "samo_brzo": "samo brzo", "ne_isplati_se": "ne isplati se",
                "premalo": "premalo poziva"}
# naslov presude na vrhu profila (maketa influencer.html: "Samo za brzi izlaz")
VERDICT_TITLE = {"drzi_se": "Drži se i dan kasnije", "samo_brzo": "Samo za brzi izlaz", "ne_isplati_se": "Ne isplati se",
                 "premalo": "Premalo poziva za presudu"}
# boja točke stanja (ui/redak.dot): zeleno drži se, narančasto samo brzo, crveno ne isplati se, sivo premalo
VERDICT_DOT = {"drzi_se": "good", "samo_brzo": "warn", "ne_isplati_se": "bad", "premalo": ""}
_HIT = "do +10 % prije stopa −20 %"


def verdict(h1, d24, n):
    """Presuda za influencera iz dva broja: (key, word, sentence).

    h1:  udio izmjerenih poziva koji su u prvom satu došli do +10 % prije stopa −20 % (0..1; kol/minute.py
         handle_stats "hit10"), None kad još nije izmjereno.
    d24: udio poziva u plusu dan kasnije (0..1; kol.db calls.r24h > 0), None kad se još ne zna.
    n:   broj poziva iza h1 u razdoblju (izmjerenih minutnom provjerom).
    key: "drzi_se" (1 h >= 50 % i 24 h >= 40 %), "samo_brzo" (1 h >= 50 %, 24 h ispod 40 % ili još nepoznat: tada je
         brzi izlaz jedini savjet koji brojke podupiru), "ne_isplati_se" (1 h ispod 50 %), "premalo" (manje od 5
         poziva, ili 1 h još nije izmjeren).
    word: VERDICT_WORD[key] ("drži se", "samo brzo", "ne isplati se", "premalo poziva"); kad poziva ima dovoljno, a
         1 h još nije izmjeren, word je "premalo podataka".
    sentence: jedna rečenica s oba broja, za hero ili profil."""
    from ui.redak import pct
    n = int(n or 0)
    if n < VERDICT_MIN_N:
        cnt = ("Nema izmjerenih poziva" if n <= 0 else "Samo 1 izmjeren poziv" if n == 1
               else f"Samo {n} izmjerena poziva")
        return ("premalo", VERDICT_WORD["premalo"], f"{cnt} u razdoblju; za presudu treba barem {VERDICT_MIN_N}.")
    if h1 is None:
        return ("premalo", "premalo podataka", "Pozivi još nisu izmjereni od minute poziva, pa presude još nema.")
    p1 = pct(h1, sign=False, frac=True)
    p24 = pct(d24, sign=False, frac=True) if d24 is not None else None
    if h1 < VERDICT_H1:
        tail = f", a dan kasnije u plusu je {p24}." if p24 else "."
        return ("ne_isplati_se", VERDICT_WORD["ne_isplati_se"],
                f"Samo {p1} poziva dođe {_HIT} u prvom satu{tail}")
    head = f"U prvom satu {p1} poziva dođe {_HIT}"
    if d24 is None:
        return ("samo_brzo", VERDICT_WORD["samo_brzo"], head + "; kako stoje dan kasnije, još se ne zna.")
    if d24 >= VERDICT_D24:
        return ("drzi_se", VERDICT_WORD["drzi_se"], f"{head}, a dan kasnije {p24} je u plusu.")
    return ("samo_brzo", VERDICT_WORD["samo_brzo"], f"{head}, ali dan kasnije u plusu je samo {p24}: izađi brzo.")


_VCACHE = {}             # (days, kol_db, minute_db) -> (ts, {handle: stats}, {lower-case handle: stats})
_VLOCK = __import__("threading").Lock()


def _day24(kol_db, since, now):
    """{handle: (n, n24, plus24)} from kol.db: one call per account and token (the first, as kol/minute and the
    profile count), posts only (no buys/sells), not marked bad, mcap at the call 30k $ or more (or unknown).
    One indexed range read (calls_ts), no per-handle queries."""
    from kol import store
    con = store.ro(kol_db)
    if con is None:
        return {}
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(calls)")}
        bad = " AND bad IS NULL" if "bad" in cols else ""
        rows = con.execute("SELECT handle, token, ts, r24h, mcap0 FROM calls WHERE ts >= ? AND ts <= ? "
                           f"AND kind NOT IN ('buy', 'sell'){bad} ORDER BY ts", (since, now)).fetchall()
    finally:
        con.close()
    from kol.minute import MIN_MCAP
    seen, out = set(), {}
    for hnd, tok, _ts, r24, mc in rows:
        if (hnd, tok) in seen:
            continue
        seen.add((hnd, tok))
        if mc is not None and mc < MIN_MCAP:
            continue
        n, n24, plus = out.get(hnd, (0, 0, 0))
        out[hnd] = (n + 1, n24 + (r24 is not None), plus + (r24 is not None and r24 > 0))
    return out


def _hour1(minute_db, days, now):
    """{handle: kol/minute.handle_stats row} (n, hit10, ...); {} without minute.db."""
    try:
        from kol import minute
        mcon = minute.ro(minute_db)
        if mcon is None:
            return {}
        try:
            return dict(minute.handle_stats(mcon, days, now, min_n=1))
        finally:
            mcon.close()
    except Exception as e:  # noqa: BLE001 - the pages work without the minute layer
        print(f"kolsummary: minutna provjera: {type(e).__name__}: {e}", flush=True)
        return {}


def verdict_stats(days=14, now=None, kol_db=None, minute_db=None):
    return _stats(days, now, kol_db, minute_db)[0]


def _stats(days=14, now=None, kol_db=None, minute_db=None):
    """{handle: stats} for every account with a call in the last `days` (7, 14 or 30), cached VERDICT_TTL s:
        n      pozivi u razdoblju (prvi po tokenu, 30k $ i više)
        n1     izmjereni minutnom provjerom; h1 udio do +10 % prije stopa (0..1 ili None); hits1 koliko ih je
        n24    s poznatom cijenom dan kasnije; plus24 koliko u plusu; d24 udio (0..1 ili None)
        key, word, sentence, dot   presuda (verdict(h1, d24, n1)) i boja točke (VERDICT_DOT)
    Handles are as stored (X without @, Telegram "tg:<kanal>"). One kol.db range read and one minute.db pass per
    window and TTL, shared by every page (ljestvica, profil, Pregled, Autopilot)."""
    days = int(days)
    key = (days, kol_db, minute_db)
    t = time.time()
    hit = _VCACHE.get(key)
    if hit and now is None and t - hit[0] < VERDICT_TTL:
        return hit[1:]
    with _VLOCK:
        hit = _VCACHE.get(key)
        if hit and now is None and t - hit[0] < VERDICT_TTL:
            return hit[1:]
        end = int(now or t)
        try:
            d24 = _day24(kol_db, end - days * 86400, end)
        except Exception as e:  # noqa: BLE001
            print(f"kolsummary: 24 h: {type(e).__name__}: {e}", flush=True)
            d24 = {}
        m = _hour1(minute_db, days, end)
        out = {}
        for hnd in set(d24) | set(m):
            n, n24, plus = d24.get(hnd, (0, 0, 0))
            ms = m.get(hnd) or {}
            n1 = int(ms.get("n") or 0)
            h1 = ms.get("hit10") if n1 else None
            dd = plus / n24 if n24 >= VERDICT_MIN_N else None
            k, w, s = verdict(h1, dd, n1)
            out[hnd] = {"n": max(n, n1), "n1": n1, "h1": h1, "hits1": round((h1 or 0) * n1), "n24": n24,
                        "plus24": plus, "d24": dd, "key": k, "word": w, "sentence": s, "dot": VERDICT_DOT[k]}
        low = {k.lower(): v for k, v in out.items()}
        if now is None:
            _VCACHE[key] = (t, out, low)
        return out, low


verdict_stats.__doc__ = _stats.__doc__

# 10.11. (Jure, prijedlog 4.4 i 4.5): javna ljestvica je i na engleskom; ista presuda (isti ključ), samo riječ prevedena
VERDICT_WORD_EN = {"drzi_se": "holds up", "samo_brzo": "quick exit only", "ne_isplati_se": "not worth it",
                   "premalo": "too few calls"}


def verdict_counts(r):
    """Ista presuda kao r["sentence"], ali prebrojana ("21 od 30" umjesto "70 %"), za hero ljestvice i vrh profila
    (makete influenceri-ljestvica.html i influencer.html). r: redak iz verdict_stats / kol_verdict. Brojke su iste
    (hits1/n1, plus24/n24); kad presude nema (premalo), vraća r["sentence"]."""
    k, n1, hits, n24, plus = r["key"], r.get("n1") or 0, r.get("hits1") or 0, r.get("n24") or 0, r.get("plus24") or 0
    if k == "premalo":
        return r["sentence"]
    day = None
    if n24 >= VERDICT_MIN_N:
        day = (f"Dan kasnije {plus} od {n24} je u plusu." if k == "drzi_se"
               else f"Ako držiš dan, {n24 - plus} od {n24} završi u minusu." if k == "samo_brzo"
               else f"Dan kasnije u plusu je {plus} od {n24}.")
    if k == "ne_isplati_se":
        return f"Samo {hits} od {n1} poziva dođe do +10\u00a0% u prvom satu, prije stopa −20\u00a0%." + (" " + day if day else "")
    return (f"U prvom satu {hits} od {n1} poziva dođe do +10\u00a0%. "
            + (day or "Kako stoje dan kasnije, još se ne zna."))


def kol_verdict(handle, days=14, now=None, kol_db=None, minute_db=None):
    """verdict_stats(...) row for one account (exact handle, then case-insensitive, "@" ignored); an account with no
    call in the window gets the "premalo" row with zeros. Same cache as verdict_stats, so a page that calls it for
    every row costs one build per window and TTL."""
    st, low = _stats(days, now, kol_db, minute_db)
    hnd = (handle or "").lstrip("@")
    r = st.get(hnd) or low.get(hnd.lower())
    if r is None:
        k, w, s = verdict(None, None, 0)
        r = {"n": 0, "n1": 0, "h1": None, "hits1": 0, "n24": 0, "plus24": 0, "d24": None, "key": k, "word": w,
             "sentence": s, "dot": VERDICT_DOT[k]}
    return r
