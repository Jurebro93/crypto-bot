"""The "Korelacije" page: organised KOL groups, wallets tied to X accounts, wallet groups of one owner, which signals
go with pumps, what known groups touch right now, and Claude's plain-language reading of it all.
Read-only from corr.db (written by run_corr.py every hour)."""
from urllib.parse import quote

from corr import store
from ui.labels import wallet_label
from ui.html import ago, badge, esc, num, table, tdesc, tlink, wlink

CONF = {"visoko": "good", "srednje": "warn", "nisko": ""}


def _acct(h):
    if h.startswith("tg:"):
        name = h[3:]
        return (f'<a href="/kol/{quote(h)}">✈ {esc(name)}</a> <a href="https://t.me/{quote(name)}" target=_blank '
                f'rel=noopener class=mut style="text-decoration:none">↗</a>')
    if h.startswith("w:"):  # tracked wallet without a known X account: no X profile to open
        return f'<a href="/kol/{quote(h)}">👛 {esc(h[2:])}</a>'
    return (f'<a href="/kol/{quote(h)}">@{esc(h)}</a> '
            f'<a href="https://x.com/{quote(h)}" target=_blank rel=noopener class=mut style="text-decoration:none">↗</a>')


def _pct(x):
    return ("–", -1, "n") if x is None else (f"{x * 100:.0f}%", x, "n")


def _lift(x):
    if x is None:
        return ("–", -1, "n")
    c = "pos" if x >= 1.3 else "neg" if x < 0.9 else ""
    return (f'<span class="{c}">{x:.2f}×</span>', x, "n")


def _scorecell(v):
    kind = "good" if v >= 70 else "warn" if v >= 50 else ""
    return (badge(f"{v:.0f}", kind), v, "n")


def _ai_block(ai, snap):
    if ai:
        d = ai["data"]
        src = f'AI tumačenje ({esc(ai["model"])}, {ago(ai["ts"])[0]}' + (f', ${ai["cost"]:.2f}' if ai.get("cost") else "") + ")"
        if not ai.get("fresh"):
            src += " · podaci su se u međuvremenu promijenili, novo tumačenje stiže jednom dnevno"
    else:
        from corr import ai as cai
        d = cai.fallback(snap)
        src = ("Tumačenje iz pravila. AI tumačenje se uključuje sam čim je postavljen isti AI ključ kao za jutarnji "
               "e-mail izvještaj.")
    out = [f'<div class=card><h2 style="margin-top:0">{esc(d.get("naslov", ""))}</h2>']
    if d.get("zakljucci"):
        out.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in d["zakljucci"]) + "</ul>")
    if d.get("sada"):
        out.append("<p><b>Sada:</b></p><ul>" + "".join(f"<li><b>{esc(x['token'])}</b>: {esc(x['zasto'])}</li>"
                                                     for x in d["sada"]) + "</ul>")
    if d.get("upozorenja"):
        out.append("<p><b>Oprez:</b></p><ul>" + "".join(f'<li class=neg>{esc(x)}</li>' for x in d["upozorenja"]) + "</ul>")
    out.append(f'<p class=mut>{src}</p></div>')
    # rule lines only repeat the numbers the cards already show, so the cards get AI words only from the real AI
    return "".join(out), ({g["id"]: g for g in d.get("grupe", [])} if ai else {}), d


def page(qs):
    ts, snap, ai = store.latest()
    if not snap:
        return "Korelacije", ('<h1>Korelacije</h1><div class=empty>Prva analiza još nije gotova (radi se svaki sat). '
                              'Osvježi stranicu za nekoliko minuta.</div>')
    i = snap["inputs"]
    body = ["<h1>Korelacije</h1>",
            f'<p class=mut>Zadnja analiza {ago(ts)[0]}: {i["calls"]:,} poziva s {i["accounts"]} računa'
            + (f' i {i["tg_posts"]} Telegram objava' if i.get("tg_posts") else "")
            + f', {i["trades"]:,} kupnji i prodaja walleta, {i["fund_edges"]:,} veza izvora novca. '
            "Ništa se ne plaća dodatno: sve je iz podataka koje bot već ima.</p>"]
    ai_html, ai_groups, d = _ai_block(ai, snap)
    body.append(ai_html)

    # active now
    act = snap.get("active") or []
    body.append("<h2>Aktivno sada</h2>" + tdesc(
        "Tokeni koje poznata grupa dira u zadnjih nekoliko sati: dva ili više računa iste KOL grupe su ih pozvala ili "
        "su walleti iz iste grupe kupili. Ovo je mjesto za brz ulaz prije gomile ako grupa ima dobar rezultat."))
    rows = []
    for a in act:
        who = "; ".join((f'{w["n"]} računa iz grupe <a href="#{w["id"]}">{esc(w["id"])}</a>' if w["kind"] == "kol"
                         else f'{w["n"]} walleta iz grupe <a href="#{w["id"]}">{esc(w["id"])}</a>') for w in a["who"])
        rows.append([tlink(a["token"], a.get("symbol")), ago(a["first_ts"]), who,
                     _scorecell(max(w["score"] for w in a["who"]))])
    body.append(table(["Token", "Prvi signal", "Tko", "Organiziranost"], rows, "c_act",
                      empty="Trenutno nijedna poznata grupa ne dira novi token."))

    from ui import corrviz
    body.append(corrviz.CSS)
    body.append("<h2>Što diže šansu za 2x</h2>" + corrviz.factors(snap["factors"]))
    body.append("<h2>KOL grupe</h2>" + tdesc(
        "Računi koji opetovano zovu iste tokene u razmaku od par minuta: najčešće ista ekipa ili plaćena kampanja. "
        "Oznaka u naslovu kaže što s grupom napraviti.") + corrviz.kol_cards(snap["clusters"], ai_groups))
    body.append("<h2>Tko kupuje prije poziva</h2>" + tdesc(
        "Walleti koji kupe token prije nego ga određeni račun pozove, i to opetovano. Zelena točka je kupnja, plava "
        "crta poziv, crvena prodaja nakon poziva.") + corrviz.link_cards(snap["links"]))
    body.append("<h2>Walleti jednog vlasnika</h2>" + tdesc(
        "Skupine walleta iza kojih je vjerojatno ista osoba ili ekipa. Svaka točka je jedan wallet.")
        + corrviz.group_cards(snap["groups"], ai_groups))
    body.append('<details class=card style="margin-top:18px"><summary><b>Sve tablice</b> '
                '<span class=mut>(svi brojevi za detaljnu provjeru)</span></summary>')

    # KOL groups
    body.append("<h2>KOL grupe</h2>" + tdesc(
        "Računi koji opetovano zovu iste tokene unutar 30 minuta, puno češće nego što bi bilo slučajno. Čvrsto vremenski "
        "zbijena grupa s istim vođom obično je jedna ekipa ili plaćena kampanja. Usporedba 'zajedno' i 'sami' kaže "
        "vrijedi li ulaziti kad se grupa poklopi."))
    rows = []
    for cl in snap["clusters"]:
        g = ai_groups.get(cl["id"], {})
        name = esc(g.get("ime") or f"Grupa oko @{cl['leader']}")
        rows.append([f'<b>{name}</b>' + (" " + badge("TG + X", "warn") if cl.get("cross_platform") else ""),
                     _scorecell(cl["score"]), num(cl["size"]), num(cl["tokens"]),
                     (_acct(cl["leader"]) if cl["leader"] else "–", cl["leader"] or ""), _pct(cl["leader_share"]),
                     num(cl["spread_min"], "{:.0f} min"), _pct(cl["hit_together"]), _pct(cl["hit_solo"]),
                     _pct(cl["late_share"]), num(len(cl.get("wallets") or [])), ago(cl["last_ts"])])
    body.append(table(["KOL grupa", "Organiziranost", "Računa", "Zajedno tokena", "Vođa", "Vođa prvi", "Razmak",
                       "2x zajedno", "2x sami", "Kasni", "Povezanih walleta", "Zadnji zajednički"], rows, "c_kol",
                      empty="Još nema dovoljno zajedničkih poziva za grupu."))
    # wallet <-> account links
    body.append("<h2>Walleti povezani s računima</h2>" + tdesc(
        "Wallet koji kupi token malo prije nego ga određeni račun pozove, i to na više tokena. Ako još i proda nakon "
        "poziva, to je vjerojatno račun sam, netko tko ga plaća ili netko kome javlja unaprijed. Snajperi koji kupuju "
        "sve nove tokene su filtrirani."))
    rows = [[wlink(x["wallet"]), (_acct(x["handle"]), x["handle"]), num(x["tokens"]), num(x["of_calls"]),
             num(x["strength"], "{:.2f}"), num(x["sold_into"]), num(x["lead_min"], "{:.0f} min"),
             num(x["sol_in"], "{:.1f}"), num(x["sol_out"], "{:.1f}"),
             " ".join(badge(wallet_label(lb), "bad" if lb in ("insider", "rugger", "dev") else "") for lb in x.get("labels") or [])]
            for x in snap["links"]]
    body.append(table(["Wallet", "Račun", "Kupio prije", "Poziva računa", "Jačina veze", "Prodao u poziv",
                       "Koliko prije", "SOL uloženo", "SOL izvučeno", "Oznake"], rows, "c_links",
                      empty="Još nema walleta koji se ponavljaju prije poziva istog računa."))

    # owner groups
    body.append("<h2>Grupe walleta (jedan vlasnik)</h2>" + tdesc(
        "Walleti koji izgledaju kao jedna osoba ili ekipa: novac im dolazi s istog izvora (burze su izuzete), rug "
        "provjera ih je stavila u isti klaster, ili kupuju isti token u istoj sekundi na više tokena. Ako su povezani "
        "i s X računima, to je insider grupa koja sama kupi pa javi."))
    rows = []
    for g in snap["groups"]:
        a = ai_groups.get(g["id"], {})
        rows.append([esc(a.get("ime") or f"Walleti {g['wallets'][0][:4]}…"),
                     _scorecell(g["score"]), num(g["size"]), num(g["shared_tokens"]), num(g["created"]),
                     ", ".join(f"{esc(k)} {v}" for k, v in g["reasons"].items()),
                     ", ".join(_acct(h) for h in g["handles"][:4]) or "–",
                     " ".join(badge(f"{wallet_label(k)} {v}") for k, v in g["labels"].items()) or "–",
                     num(g["realized_sol"], "{:+.1f}"), ago(g["last_ts"]),
                     " ".join(wlink(w) for w in g["wallets"][:3])])
    body.append(table(["Grupa walleta", "Organiziranost", "Walleta u grupi", "Tokeni više walleta", "Kreirali tokena", "Veze",
                       "Povezani računi", "Oznake", "Zarada SOL", "Zadnja kupnja", "Walleti"], rows, "c_groups",
                      empty="Još nema walleta povezanih istim vlasnikom."))

    # pump factors
    f = snap["factors"]
    body.append("<h2>Što ide uz pumpu</h2>" + tdesc(
        f"Za {f['n']:,} tokena s KOL pozivom i izmjerenim ishodom: koliko često se token udvostručio u 24 h kad je "
        f"signal bio prisutan i kad nije. Prosjek svih: {_pct(f['base_hit'])[0]}. Više od 1,3× je koristan signal."))
    sig = {s["signal"]: s["tumacenje"] for s in d.get("signali", [])}
    rows = [[esc(x["factor"]), num(x["n_yes"]), _pct(x["hit_yes"]), num(x["n_no"]), _pct(x["hit_no"]), _lift(x["lift"]),
             esc(sig.get(x["factor"], ""))] for x in f["factors"]]
    body.append(table(["Signal uz poziv", "Sa signalom", "2x sa", "Bez signala", "2x bez", "Omjer", "Tumačenje"], rows, "c_fac",
                      empty="Premalo izmjerenih tokena."))

    # followed
    fol = store.followed()
    body.append("<h2>Praćene grupe</h2>" + tdesc(
        "Grupe koje bot prati sam: one s organiziranošću 60+ ili koje je AI označio. Walleti iz praćenih grupa idu u "
        "registar walleta s oznakom 'grupa' (češće se provjeravaju; na copy listu idu samo ako su u plusu), a njihova nova aktivnost se pokazuje gore pod "
        "Aktivno sada."))
    rows = [[f'<a href="#{esc(x["id"])}">{esc(x["name"])}</a>', esc("KOL računi" if x["kind"] == "kol" else "walleti"),
             num(len(x["members"])), _scorecell(x["score"] or 0), esc(x["reason"]), ago(x["since"])] for x in fol]
    body.append(table(["Praćena grupa", "Vrsta grupe", "Članova", "Organiziranost", "Zašto", "Pratimo od"], rows, "c_fol",
                      empty="Još nijedna grupa nije dovoljno jasna za praćenje."))

    # pairs
    body.append("<h2>Najjači parovi računa</h2>" + tdesc(
        "Dva računa koja najčešće zovu isti token u razmaku do 30 min. Omjer = koliko puta češće nego da biraju tokene "
        "nasumično. 'Prvi' = koliko puta je prvi naveden račun zvao prije drugog."))
    rows = [[(_acct(p["a"]), p["a"]), (_acct(p["b"]), p["b"]), num(p["n"]), _pct(p["overlap"]), num(p["lift"], "{:.0f}×"),
             _pct(p["a_first"]), num(p["gap_min"], "{:.0f} min")] for p in snap["pairs"]]
    body.append(table(["Račun A", "Račun B", "Zajedno tokena", "Udio zajedničkih", "Iznad slučajnosti", "A prvi",
                       "Razmak"], rows, "c_pairs"))
    body.append("</details>")
    if d.get("sto_jos"):
        body.append("<h2>Što bi još pomoglo</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in d["sto_jos"]) + "</ul>")
    return "Korelacije", _handles("".join(body))


def _handles(html):
    """Stored group names and AI texts carry raw handles ('@tg:chan', 'Grupa tg:chan', '@w:name'): show them the way the
    rest of the page does (✈ chan, 👛 name). Attribute values (data-v="tg:…") are left alone."""
    import re
    html = re.sub(r'(?<!=")@?tg:([A-Za-z0-9_]+)', r"✈ \1", html)
    return re.sub(r'(?<!=")@w:([A-Za-z0-9_]+)', r"👛 \1", html)
