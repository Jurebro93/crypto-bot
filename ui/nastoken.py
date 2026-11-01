"""/nas-token: our own Solana meme token. Projects (one or more), the shared vault, the generator form, costs,
the launch package, live stats with advice, the marketing plan and influencer partners from our KOL data.

Nothing here signs or holds a key: launching happens in the players' own wallets, the vault is a public address.
"""
import re
import sqlite3
import time
from urllib.parse import quote

from ourtoken import advisor, costs, store, treasury
from ui.html import ago as _ago, badge, esc, num, table, tdesc, ts, usd as _usd
from ui.kol import klink



def usd(x):
    """Plain text amount (html.usd gives a table cell tuple)."""
    return _usd(x)[0]


def ago(t):
    return _ago(t)[0]


WSOL = "So11111111111111111111111111111111111111112"
_SOL = {"ts": 0, "px": None}


def sol_usd():
    """SOL price from DexScreener, cached 10 min; 150 if unreachable (shown as estimate anyway)."""
    if time.time() - _SOL["ts"] > 600 or not _SOL["px"]:
        try:
            from ui.paper import market
            px = market({WSOL}).get(WSOL, (None,))[0]
        except Exception:  # noqa: BLE001
            px = None
        _SOL.update(ts=time.time(), px=px or _SOL["px"])
    return _SOL["px"] or 150.0


def _msg(qs):
    if qs.get("err"):
        return f'<div class=card style="border-color:var(--bad)"><b class=neg>Nije prošlo:</b> {esc(qs["err"])}</div>'
    if qs.get("ok"):
        return f'<div class=card style="border-color:var(--good)">{esc(qs["ok"])}</div>'
    return ""


def _copy(text, label="📋 Kopiraj"):
    js = ("var m=this.dataset.m,b=this;(navigator.clipboard?navigator.clipboard.writeText(m):Promise.reject())"
          ".then(function(){b.textContent='✅ Kopirano'},function(){prompt('Kopiraj:',m)});return false")
    return f'<button type=button class=sm data-m="{esc(text)}" onclick="{js}">{label}</button>'


RISK = ("<details class=card style='border-color:var(--warn)'><summary><b>⚠️ Prije nego krenete: rizik i pravila</b> "
        "<span class=mut>(pročitaj jednom)</span></summary><ul>"
        "<li><b>Novac je stvaran.</b> Što uplatite u trezor i stavite u token, možete izgubiti u cijelosti. "
        "Više od 98% meme tokena nikad ne uspije. Uplaćujte samo koliko vam ne smeta izgubiti.</li>"
        "<li><b>Zakon.</b> Javna prodaja kripto tokena u EU-u spada pod uredbu MiCA, a u Hrvatskoj nadzire HANFA. "
        "Meme token bez obećanja zarade je siva zona, ali obećavati kupcima zaradu, skrivati da tim drži tokene "
        "ili prodati pa nestati (rug) može biti kazneno djelo. Prije lansiranja pitajte knjigovođu ili odvjetnika; "
        "ovo nije pravni savjet.</li>"
        "<li><b>Porez.</b> Zarada od prodaje tokena se oporezuje kao dohodak od kapitala (u Hrvatskoj 12%).</li>"
        "<li><b>Plaćeni influenceri</b> moraju označiti objavu kao reklamu (#ad). Davati im tokene da šute o "
        "tome je obmana kupaca.</li>"
        "<li><b>Ključevi.</b> Alat nikad ne čuva privatni ključ ni seed frazu. Lansiranje i isplate potpisujete "
        "u svom Phantomu. Ako vam itko (i ova aplikacija) traži seed frazu, to je prevara.</li></ul></details>")


def _status(p):
    return badge(store.STATUS.get(p["status"], p["status"]), "good" if p["status"] == "live" else "warn")


def _budget(p):
    return costs.launch_cost(p, sol_usd())["usd"]


# ---------- vault ------------------------------------------------------------------------------------------------

def vault_html(con, user, goal_p=None):
    addr = treasury.address()
    b = ["<h2 id=trezor>🏦 Zajednički trezor</h2>"]
    players = store_users()
    donors = store.donors(con)
    if not addr:
        b.append("<div class=card><b>Trezor nema adresu.</b> Preporuka: <b>Squads multisig</b> "
                 "(besplatno, app.squads.so). Svaki igrač poveže svoj Phantom, a za isplatu trebaju dvojica od "
                 "trojice. Kad Nicholas pošalje javnu adresu trezora, ovdje se odmah vidi stanje, tko je koliko "
                 "uplatio i koliko još treba. Alat samo čita javnu adresu, nikad ne drži ključ.</div>")
    sol_px = sol_usd()
    v = treasury.read(addr) if addr else {}
    have = ((v.get("sol") or 0) * sol_px + (v.get("usdc") or 0)) if v else 0
    goal = _budget(goal_p) if goal_p else 0
    if addr:
        b.append(f"<div class=card><div><b>Adresa trezora:</b> <code style='word-break:break-all'>{esc(addr)}</code> "
                 f"{_copy(addr, '📋 Kopiraj adresu')} <a href='https://solscan.io/account/{esc(addr)}' target=_blank "
                 "rel=noopener>Solscan ↗</a></div>")
        if v.get("error"):
            b.append(f"<p class=neg>Stanje se trenutno ne može pročitati ({esc(v['error'])}). Pokušaj za par minuta.</p>")
        b.append(f"<div class=grid style='display:flex;gap:18px;flex-wrap:wrap;margin-top:8px'>"
                 f"<div><span class=mut>U trezoru</span><br><b style='font-size:22px'>{usd(have)}</b> "
                 f"<span class=mut>({(v.get('sol') or 0):.3f} SOL + {(v.get('usdc') or 0):,.0f} USDC)</span></div>"
                 + (f"<div><span class=mut>Treba za {esc(goal_p['symbol'])}</span><br><b style='font-size:22px'>"
                    f"{usd(goal)}</b></div><div><span class=mut>Nedostaje</span><br><b style='font-size:22px'>"
                    f"{usd(max(0, goal - have))}</b></div>" if goal_p else "")
                 + "</div><p class=mut>Uplaćuje se SOL ili USDC na ovu adresu iz svog Phantoma (Pošalji → zalijepi "
                   "adresu). Stanje se osvježava svakih 10 minuta. Ovo je Phantom novčanik kojim upravlja Nicholas; "
                   "kad se skupi veći iznos, prelazimo na Squads trezor gdje isplatu potpisuju dvojica.</p></div>")
    # per player: suggested share, sent, still to send
    gifts = v.get("gifts") or []
    per = treasury.by_player(gifts, donors, sol_px)
    fair = costs.share_per_player(goal, 0, players) if goal_p else 0
    rows = []
    for u in players:
        r = per.get(u, {})
        sent = r.get("usd", 0)
        left = max(0.0, fair - sent)
        rows.append([("<b>" + esc(u) + "</b>") if u == user else esc(u),
                     f"<code>{esc(donors[u][:4] + '…' + donors[u][-4:])}</code>" if u in donors else
                     "<span class=mut>nije upisao</span>",
                     usd(fair) if goal_p else "–", usd(sent) if r else "–",
                     (usd(left) if left > 0.5 else "✅") if goal_p else "–"])
    if per.get("?"):
        rows.append(["<span class=mut>Nepoznati novčanici</span>", "", "", usd(per["?"]["usd"]), ""])
    b.append(tdesc("Prijedlog alata: budžet lansiranja podijeljen jednako na sve igrače. "
                   "Uplata se pripiše igraču po novčaniku koji je upisao ispod.") +
             table(["Igrač", "Novčanik", ("Prijedlog uplate", "n"), ("Uplatio", "n"), ("Još treba", "n")], rows,
                   tid="ntdon", empty="Nema igrača."))
    if user:
        mine = donors.get(user, "")
        b.append("<form method=post action=/nas-token/novcanik class=card style='max-width:640px'>"
                 "<b>Moj novčanik za uplate</b> <span class=mut>(javna adresa iz Phantoma, da alat zna da je "
                 "uplata tvoja)</span><br><input name=address style='width:70%' placeholder='npr. 7xKX…' "
                 f"value=\"{esc(mine)}\"> <button type=submit>Spremi</button></form>")
    if gifts:
        who = {a: u for u, a in donors.items()}
        b.append("<details><summary>Zadnje uplate u trezor</summary>" + table(
            ["Vrijeme", "Od", ("SOL", "n"), ("USDC", "n"), "Transakcija"],
            [[ago(g["ts"]), esc(who.get(g["sender"], g["sender"][:4] + "…" + g["sender"][-4:])),
              f"{g['sol']:.3f}" if g["sol"] else "", f"{g['usdc']:,.2f}" if g["usdc"] else "",
              f"<a href='https://solscan.io/tx/{esc(g['sig'])}' target=_blank rel=noopener>Solscan ↗</a>"]
             for g in gifts[:50]], tid="ntgift") + "</details>")
    return "".join(b)


def store_users():
    try:
        from league import store as lstore
        return lstore.users()
    except Exception:  # noqa: BLE001
        return []


# ---------- form -------------------------------------------------------------------------------------------------

def form_html(p=None):
    p = dict(store.DEFAULTS, **(p or {}))
    act = f"/nas-token/{p['id']}/uredi" if p.get("id") else "/nas-token/novi"

    def inp(name, label, help_="", typ="text", extra=""):
        val = p.get(name)
        val = "" if val is None else (f"{val:g}" if isinstance(val, float) else val)
        return (f"<label style='display:block;margin:6px 0'><b>{label}</b>"
                + (f" <span class=mut>{help_}</span>" if help_ else "")
                + f"<br><input name={name} type={typ} value=\"{esc(val)}\" style='width:100%;max-width:420px' {extra}>"
                "</label>")

    opts = "".join(f"<option value={k} {'selected' if p.get('launch') == k else ''}>{esc(v['name'])}</option>"
                   for k, v in costs.PATHS.items())
    return (f"<form method=post action={act} class=card style='max-width:720px'>"
            + inp("name", "Ime tokena", "npr. Naš Token", extra="required maxlength=32")
            + inp("symbol", "Oznaka (ticker)", "2-10 slova, npr. NASH", extra="required maxlength=10")
            + "<label style='display:block;margin:6px 0'><b>Opis</b> <span class=mut>(što je token, zašto je smiješan, "
              f"do 500 znakova)</span><br><textarea name=description rows=3 style='width:100%;max-width:560px'>"
              f"{esc(p.get('description') or '')}</textarea></label>"
            + inp("image_url", "Slika (link)", "kvadratna slika ili GIF; pump.fun traži da je učitaš i tamo")
            + inp("website", "Web stranica", "neobavezno") + inp("x_url", "X (Twitter)", "neobavezno")
            + inp("tg_url", "Telegram grupa", "neobavezno")
            + f"<label style='display:block;margin:6px 0'><b>Gdje lansiramo</b><br><select name=launch>{opts}</select>"
              "</label>"
            + inp("dev_buy_sol", "Naša prva kupnja (SOL)", "kupujemo prvi; na pump.fun 1 SOL ≈ 3.5% supplyja", "number",
                  "step=0.1 min=0")
            + inp("liq_sol", "Likvidnost u poolu (SOL)", "samo za Meteoru/Raydium, npr. 10", "number", "step=0.5 min=0")
            + inp("supply", "Ukupna količina tokena", "samo za Meteoru/Raydium; pump.fun je uvijek 1 milijarda",
                  "number", "min=1000")
            + inp("decimals", "Decimale", "obično 6", "number", "min=0 max=9")
            + inp("infl_pct", "Dio za influencere (%)", "preporuka 2-5%", "number", "step=0.5 min=0 max=20")
            + inp("team_pct", "Dio za tim / trezor (%)", "preporuka do 5%, javno i zaključano", "number",
                  "step=0.5 min=0 max=30")
            + inp("mkt_usd", "Marketinški budžet ($)", "influenceri, boost, web", "number", "step=50 min=0")
            + f"<p><button type=submit>{'💾 Spremi promjene' if p.get('id') else '✨ Napravi nacrt tokena'}</button> "
              "<span class=mut>Nacrt ništa ne šalje na blockchain i ne troši novac.</span></p></form>")


# ---------- list page --------------------------------------------------------------------------------------------

def page(qs, user):
    con = store.connect()
    try:
        ps = store.projects(con)
        goal_p = next((p for p in ps if p["status"] != "live"), None)
        b = ["<h1>🪙 Naš token</h1>", _msg(qs),
             "<p class=lead>Ovdje radimo vlastiti Solana meme token: skupimo novac u zajednički trezor, složimo token, "
             "lansiramo ga iz svog Phantoma, a alat iz svih podataka koje prati predlaže marketing i influencere "
             "za suradnju i prati brojke tokena nakon lansiranja.</p>", RISK]
        b.append("<h2>Naši tokeni</h2>")
        if ps:
            b.append("<div style='display:flex;gap:10px;flex-wrap:wrap'>" + "".join(_card(con, p) for p in ps) + "</div>")
        else:
            b.append("<p class=mut>Još nema nijednog. Napravi prvi nacrt ispod; ništa se ne šalje na blockchain.</p>")
        b.append(vault_html(con, user, goal_p))
        b.append(_ways())
        b.append("<h2 id=novi>✨ Novi token</h2>" + (form_html() if user else
                                                       "<p class=mut>Prijavi se svojim imenom da napraviš token.</p>"))
    finally:
        con.close()
    return "Naš token", "".join(b)


def _card(con, p):
    h = store.history(con, p["id"], 1)
    line = ""
    if h and h[0].get("mcap"):
        line = f"<div>Vrijednost {usd(h[0]['mcap'])} · likvidnost {usd(h[0]['liq'])}</div>"
    elif p["status"] != "live":
        line = f"<div class=mut>Budžet za lansiranje ~{usd(_budget(p))}</div>"
    return (f"<a class=card href='/nas-token/{p['id']}' style='min-width:220px;text-decoration:none;color:inherit'>"
            f"<b style='font-size:18px'>${esc(p['symbol'])}</b> {esc(p['name'])}<div>{_status(p)} "
            f"<span class=mut>{esc(costs.PATHS.get(p['launch'], {}).get('short', ''))}</span></div>{line}"
            f"<div class=mut>napravio {esc(p['created_by'] or '?')}</div></a>")


def _ways():
    rows = []
    for k, v in costs.PATHS.items():
        rows.append([f"<b>{esc(v['name'])}</b>", esc(v["how"]), "<br>".join("✅ " + esc(x) for x in v["plus"]),
                     "<br>".join("⚠️ " + esc(x) for x in v["minus"])])
    return ("<h2>🚀 Kako se token lansira</h2>"
            + tdesc("Tri puta na pravi Solana blockchain. Besplatni je pump.fun, plaćeni traže vlastiti SOL za "
                    "likvidnost. Iznosi su procjena (provjereno 1.11.2026).")
            + table(["Način", "Kako radi", "Dobro", "Loše"], rows, tid="ntways")
            + "<div class=card><b>Tko potpisuje?</b> Lansiranje uvijek potpisuje igrač u svom Phantomu. Alat složi "
              "sve podatke (paket za lansiranje na stranici tokena), a ti ih na pump.fun zalijepiš i potvrdiš. "
              "Gumb \"Lansiraj iz Phantoma\" ravno iz aplikacije (prvo na testnoj mreži, pa na pravoj) uključujemo "
              "kad Nicholas odluči kako; server nikad ne dobiva ključ.</div>")


# ---------- project page -----------------------------------------------------------------------------------------

def project_page(pid, qs, user):
    con = store.connect()
    try:
        p = store.get(con, pid)
        if not p:
            return "Naš token", "<h1>Nema tog tokena</h1><p><a href=/nas-token>Natrag</a></p>"
        stats, hist, advice = {}, [], []
        if p.get("mint"):
            stats = advisor.live_stats(p["mint"])
            if stats.get("price"):
                try:
                    store.add_stats(con, pid, stats)
                except sqlite3.OperationalError:
                    pass
            hist = store.history(con, pid)
            advice = advisor.live_advice(stats, hist)
        b = [f"<h1>🪙 ${esc(p['symbol'])} · {esc(p['name'])}</h1>", _msg(qs),
             f"<p>{_status(p)} <span class=mut>{esc(costs.PATHS[p['launch']]['name'])} · napravio "
             f"{esc(p['created_by'] or '?')} · zadnja promjena {ago(p['updated_ts'])}</span> · "
             "<a href=/nas-token>← svi naši tokeni</a></p>"]
        if p.get("mint"):
            b.append(_live_html(p, stats, hist, advice))
        b.append(_cost_html(p))
        b.append(_package_html(p))
        if user:
            b.append(_mint_form(p))
        b.append(_plan_html(p))
        b.append(vault_html(con, user, p if p["status"] != "live" else None))
        b.append(RISK)
        if user:
            b.append(f"<details><summary><b>✏️ Uredi podatke tokena</b></summary>{form_html(p)}</details>")
            if p["created_by"] == user and p["status"] != "live":
                b.append(f"<form method=post action=/nas-token/{pid}/obrisi onsubmit=\"return confirm('Obrisati nacrt?')\">"
                         "<button class=sm type=submit>🗑 Obriši nacrt</button></form>")
    finally:
        con.close()
    return f"${p['symbol']} · Naš token", "".join(b)


def _live_html(p, s, hist, advice):
    m = p["mint"]
    from ui.html import ext_icons
    b = [f"<h2>📈 Brojke tokena uživo</h2><div class=card><code style='word-break:break-all'>{esc(m)}</code> "
         f"{_copy(m, '📋 Kopiraj adresu')} {ext_icons(m, s.get('url'))}</div>"]
    if s.get("price"):
        cells = [("Cijena", f"${s['price']:.10g}"), ("Tržišna vrijednost", usd(s.get("mcap"))),
                 ("Likvidnost", usd(s.get("liq"))), ("Volumen 24 h", usd(s.get("vol24"))),
                 ("Kupnje / prodaje 24 h", f"{s.get('buys24') or 0} / {s.get('sells24') or 0}"),
                 ("Promjena 24 h", f"{s['chg24']:+.0f}%" if s.get("chg24") is not None else "–"),
                 ("Top 10 novčanika", f"{s['top10']:.0f}%" if s.get("top10") is not None else "–")]
        b.append("<div style='display:flex;gap:10px;flex-wrap:wrap'>" + "".join(
            f"<div class=card style='margin:0'><span class=mut>{k}</span><br><b style='font-size:18px'>{v}</b></div>"
            for k, v in cells) + "</div>")
    colour = {"good": "var(--good)", "warn": "var(--warn)", "bad": "var(--bad)"}
    b.append("<h3>💡 Što alat predlaže sada</h3>" + "".join(
        f"<div class=card style='border-left:4px solid {colour[lv]}'>{esc(t)}</div>" for lv, t in advice))
    if hist:
        b.append("<details><summary>Povijest brojki (snimka svakih 15 min dok netko gleda stranicu)</summary>" + table(
            ["Vrijeme", ("Vrijednost", "n"), ("Likvidnost", "n"), ("Volumen 24 h", "n"), ("Kupnje", "n"),
             ("Prodaje", "n"), ("Top 10 %", "n")],
            [[ts(h["ts"]), _usd(h["mcap"]), _usd(h["liq"]), _usd(h["vol24"]), num(h["buys24"]), num(h["sells24"]),
              num(h["top10"], "{:.0f}")] for h in hist], tid="nthist") + "</details>")
    return "".join(b)


def _cost_html(p):
    c = costs.launch_cost(p, sol_usd())
    rows = [[esc(n), f"{s:.3f}" if s is not None else "–", _usd(u), f"<span class=mut>{esc(note)}</span>"]
            for n, s, u, note in c["rows"]]
    rows.append(["<b>Ukupno</b>", f"<b>{c['sol']:.3f}</b>", f"<b>{usd(c['usd'])}</b>", ""])
    split = costs.supply_split(p)
    b = ["<h2>💰 Koliko košta</h2>",
         tdesc(f"Procjena za {esc(c['path']['name'])} uz SOL ≈ ${sol_usd():,.0f}. Ovo je iznos koji trezor treba "
               "skupiti."),
         table(["Stavka", ("SOL", "n"), ("USD", "n"), "Napomena"], rows, tid="ntcost"),
         "<h3>Kamo ide supply</h3>",
         table(["Dio", ("%", "n"), "Napomena"], [[esc(a), f"{x:g}%", f"<span class=mut>{esc(n)}</span>"]
                                                for a, x, n in split], tid="ntsplit")]
    if p["launch"] == "pumpfun":
        got = costs.pump_buy_pct(p.get("dev_buy_sol"))
        need = float(p.get("infl_pct") or 0) + float(p.get("team_pct") or 0)
        txt = (f"Naša prva kupnja od {p.get('dev_buy_sol') or 0:g} SOL donosi oko <b>{got:.1f}%</b> supplyja. ")
        if need > got + 0.05:
            txt += (f"Za influencere i tim ({need:g}%) treba oko <b>{costs.pump_sol_for_pct(need):.1f} SOL</b>. "
                    "Ili smanji postotke, ili povećaj prvu kupnju. Više od ~10% u rukama tima botovi vide kao rizik.")
        else:
            txt += "To pokriva dio za influencere i tim."
        b.append(f"<div class=card>{txt}</div>")
    b.append("<details><summary>Plaćeni dodaci (nisu obavezni)</summary>" + table(
        ["Dodatak", ("Cijena", "n"), "Što dobijemo"], [[esc(n), usd(x), esc(w)] for n, x, w in costs.EXTRAS],
        tid="ntextra") + "</details>")
    return "".join(b)


def _package_html(p):
    """Everything to paste into the launchpad, field by field with copy buttons."""
    fields = [("Ime", p["name"]), ("Ticker", p["symbol"]), ("Opis", p.get("description") or ""),
              ("Slika", p.get("image_url") or ""), ("Web", p.get("website") or ""), ("X", p.get("x_url") or ""),
              ("Telegram", p.get("tg_url") or "")]
    if p["launch"] != "pumpfun":
        fields += [("Supply", f"{p['supply']:,}".replace(",", "")), ("Decimale", str(p["decimals"]))]
    rows = [[f"<b>{k}</b>", esc(v) if v else "<span class=mut>prazno</span>", _copy(v) if v else ""]
            for k, v in fields]
    where = {"pumpfun": ("https://pump.fun/create", "Otvori pump.fun → Create"),
             "raydium": ("https://raydium.io/liquidity/create-pool/", "Otvori Raydium → Create pool"),
             "meteora": ("https://app.meteora.ag/", "Otvori Meteora")}[p["launch"]]
    steps = {"pumpfun": [
        "Otvori pump.fun u pregledniku gdje je Phantom (ili u Phantomovom pregledniku na mobitelu) i spoji novčanik.",
        "Zalijepi polja iz tablice, učitaj sliku.",
        f"Kod \"buy first\" upiši {p.get('dev_buy_sol') or 0:g} SOL (naša prva kupnja), potvrdi u Phantomu.",
        "Kopiraj adresu novog tokena (na stranici tokena na pump.fun) i upiši je ispod: alat ga odmah počinje pratiti."],
        "raydium": [
            "Token se prvo kreira (mint + metapodaci) u alatu koji podržava Phantom, npr. Raydium ili Solana Token "
            "Creator; obavezno isključi mint i freeze ovlasti.",
            f"Na Raydiumu napravi CPMM pool: {p.get('liq_sol') or 0:g} SOL + dio tokena iz raspodjele.",
            "LP tokene spali (Burn) i objavi transakciju, inače svi alati (i naš) token vide kao mogući rug.",
            "Adresu tokena upiši ispod."],
        "meteora": [
            "Token se prvo kreira (mint + metapodaci) u alatu koji podržava Phantom; obavezno isključi mint i freeze "
            "ovlasti.",
            f"Na Meteori napravi DAMM pool: {p.get('liq_sol') or 0:g} SOL + dio tokena, s dinamičnom naknadom.",
            "LP poziciju zaključaj i objavi transakciju.", "Adresu tokena upiši ispod."]}[p["launch"]]
    return ("<h2>📦 Paket za lansiranje</h2>"
            + tdesc("Sve što launchpad traži, spremno za kopiranje. Lansiranje potpisuješ ti u svom Phantomu; alat "
                    "ne drži nikakav ključ.")
            + table(["Polje", "Vrijednost", ""], rows, tid="ntpkg")
            + "<ol>" + "".join(f"<li>{esc(s)}</li>" for s in steps) + "</ol>"
            + f"<p><a class=cta href='{where[0]}' target=_blank rel=noopener style='display:inline-block;padding:8px "
              f"14px'>{esc(where[1])} ↗</a></p>")


def _mint_form(p):
    opts = "".join(f"<option value={k} {'selected' if p['status'] == k else ''}>{esc(v)}</option>"
                   for k, v in store.STATUS.items() if k != "nacrt")
    return (f"<form method=post action=/nas-token/{p['id']}/adresa class=card style='max-width:720px'>"
            "<b>Token je lansiran? Upiši njegovu adresu</b> <span class=mut>(mint adresa s pump.fun, Solscana ili "
            "DexScreenera)</span><br><input name=mint style='width:70%' "
            f"value=\"{esc(p.get('mint') or '')}\" placeholder='adresa tokena'> <select name=status>{opts}</select> "
            "<button type=submit>Spremi</button></form>")


def _plan_html(p):
    hours = advisor._cached("hours", advisor.best_hours)
    lift = advisor._cached("lift", advisor.cocall_lift)
    partners = advisor._cached("partners", advisor.influencers) or []
    b = ["<h2>📣 Marketinški plan</h2>"]
    facts = []
    if hours:
        facts.append(f"Najbolje vrijeme za objave: <b>{hours['start_zg']:02d}-{(hours['start_zg'] + 3) % 24:02d} h</b> "
                     f"po našem vremenu (medijan {hours['views']:,.0f} pregleda po objavi, u ostalim satima oko "
                     f"{hours['mean_views']:,.0f}; {hours['hit']:.0%} tokena tada naraste +50%). Iz {hours['n']} "
                     "izmjerenih poziva, samo sati kad smo budni.")
    if lift:
        facts.append(f"Kad <b>3+ influencera</b> objavi isti token unutar 15 minuta, token se udvostruči u "
                     f"<b>{lift['group_rate']:.0%}</b> slučajeva ({lift['group_n']} tokena), inače u "
                     f"{lift['solo_rate']:.0%} ({lift['solo_n']}). Zato plan ide na val objava, ne jednu po jednu.")
    if facts:
        b.append("<div class=card>📊 <b>Iz naših podataka:</b><ul>" + "".join(f"<li>{f}</li>" for f in facts)
                 + "</ul></div>")
    for phase, steps in advisor.plan(p, hours, lift, partners):
        b.append(f"<h3>{esc(phase)}</h3><ul>" + "".join(
            f"<li>{esc(s)}" + (f" {badge(c, 'good' if free else 'warn')}" if c else "") + "</li>"
            for s, c, free in steps) + "</ul>")
    b.append("<h2>🤝 S kojim influencerima surađivati</h2>")
    b.append(tdesc("Iz KOL-ova koje alat prati: doseg (pratitelji), koliko njihovih poziva stvarno naraste, rijetki "
                   "rugovi i kasni pozivi. Bot računi su isključeni. Cijena objave je gruba procjena; prijedlog "
                   "dogovora daje tokene postupno, samo za odrađene objave."))
    rows = [[klink(r["handle"]), num(r["followers"]), (f"<b>{r['fit']:.0f}</b>", r["fit"], "n"),
             f"{(r['s'].get('hit_rate') or 0):.0%}", f"{(r['s'].get('rug_rate') or 0):.0%}",
             esc("; ".join(r["why"])), usd(r["price"]), esc(r["deal"])] for r in partners]
    b.append(table(["Influencer", ("Pratitelji", "n"), ("Pogodnost", "n"), ("Pogodak", "n"), ("Rugovi", "n"),
                    "Zašto", ("Objava ~", "n"), "Prijedlog dogovora"], rows, tid="ntinfl",
                   empty="Još nema dovoljno izmjerenih influencera."))
    return "".join(b)


# ---------- forms ------------------------------------------------------------------------------------------------

def post(path, form, user):
    """Handle a form; returns where to send the browser next."""
    m = re.fullmatch(r"/nas-token/(\d+)/(uredi|adresa|obrisi)", path)
    back = f"/nas-token/{m.group(1)}" if m else "/nas-token"
    if not user:
        return f"{back}?err={quote('prijavi se svojim imenom')}"
    con = store.connect()
    try:
        if path == "/nas-token/novi":
            pid = store.save(con, user, form)
            msg = "Nacrt je spremljen. Ispod su trošak, paket za lansiranje, marketinški plan i influenceri."
            _log(user, "novi token", form.get("symbol"))
            return f"/nas-token/{pid}?ok={quote(msg)}"
        if path == "/nas-token/novcanik":
            store.set_donor(con, user, form.get("address"))
            return f"/nas-token?ok={quote('Novčanik spremljen: tvoje uplate u trezor se sad pripisuju tebi.')}#trezor"
        if m:
            pid, act = int(m.group(1)), m.group(2)
            if not store.get(con, pid):
                raise ValueError("nema tog tokena")
            if act == "uredi":
                store.save(con, user, form, pid)
                return f"{back}?ok={quote('Promjene spremljene.')}"
            if act == "adresa":
                store.set_mint(con, pid, form.get("mint"), form.get("status") or "live")
                _log(user, "adresa tokena", form.get("mint"))
                return f"{back}?ok={quote('Adresa spremljena, alat prati token.')}"
            store.delete(con, pid, user)
            return f"/nas-token?ok={quote('Nacrt obrisan.')}"
        return f"/nas-token?err={quote('nepoznata radnja')}"
    except ValueError as e:
        return f"{back}?err={quote(str(e))}"
    except sqlite3.OperationalError as e:
        return f"{back}?err={quote('baza trenutno ne prima promjene (' + str(e) + ')')}"
    finally:
        con.close()


def _log(user, what, detail):
    print(f"nas-token: {user} {what} -> {detail}", flush=True)
