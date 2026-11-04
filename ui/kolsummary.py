"""Top of the Influenceri page in plain words (like Učenje): what the data says right now, then the two new
sections "Zovu zajedno" (kol/together.py) and "Plaćeni shilleri" (kol/shillers.json). Only reads kol.db / tg.db."""
import json
import statistics

from kol import shillers, together
from ui.html import badge, esc, num, table, tdesc, tip

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
            f"{len(good)} se dokazalo pozivima.")
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
    out = ["<h2 id=zajedno>Zovu zajedno</h2>", tdesc(
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
    for c in cl[:30]:
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
    out.append("<h3>Ekipe koje stalno zovu zajedno</h3>" + tdesc(
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
    ok = [r for r in rows if r["calls"] >= 10]
    med = statistics.median(r["hit2"] for r in ok) if ok else None
    top = [r for r in ok if r["last"] >= now - 30 * 86400][:5]
    lines = [f"{len(rows)} Telegram kanala s barem 5 poziva; tipičan kanal udvostruči {_p(med)} poziva."]
    if top:
        lines.append("Najbolji aktivni: " + ", ".join(f"{_link('tg:' + r['chan'])} ({_p(r['hit2'])} od {r['calls']})"
                                                     for r in top) + ".")
    out = ["<h2 id=tgpovijest>Telegram calleri: zadnjih 6 mjeseci</h2>", tdesc(
        "Iz tvojih izvoza: Call Analyser bilježi svaki poziv kanala (CA i mcap u trenutku poziva), a SpyDefi koliko je "
        "puta token narastao od poziva. Spojeno dobijemo koliko poziva svakog kanala je otišlo barem 2× i 5×. To je "
        "vrh nakon poziva, ne nužno zarada: tko kupi kasno ili ne proda na vrhu, dobije manje. Samo kanali koje oba "
        "izvora prate; zadnjih 30 dana aktivni se sad čitaju uživo i mjere kao svi ostali."),
           "<ul class=uc-ul>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul>"]
    data = []
    for r in rows:
        if r["calls"] >= 20 and r["hit2"] >= 0.4:
            v = badge("jak", "good")
        elif r["calls"] < 10:
            v = badge("malo poziva", "")
        elif r["hit2"] < 0.15:
            v = badge("slab", "bad")
        else:
            v = badge("prosječan", "warn")
        act = badge("aktivan", "good") if r["last"] >= now - 30 * 86400 else badge("utihnuo", "")
        data.append([v, _link("tg:" + r["chan"]), num(r["calls"]), _cell(r["hit2"]), _cell(r["hit5"]),
                     (f"{r['max_x']:.0f}×", r["max_x"], "n"), _mc(r.get("med_mcap")), act,
                     ago(r["last"])])
    out.append(table(["Ocjena", "Kanal", ("Poziva", "n"), ("Barem 2×", "n"), ("Barem 5×", "n"), ("Najviše", "n"),
                      ("Mcap u pozivu", "n"), "Stanje", "Zadnji poziv"], data, tid="ktghist"))
    return "".join(out)
