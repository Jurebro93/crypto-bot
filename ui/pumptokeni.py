"""/pump-tokeni: „Pump Fun tokeni” (25.11., vlasnik). Vidi ga SAMO vlasnik (run_ui.py provjerava is_owner prije
svega; ostalima 403 „nije za tvoj račun”; stavka izbornika own-only se ostalima reže na poslužitelju). Nije javno,
noindex, nije u sitemapu.

Nacrti (tema, ime, simbol, opis, slika, skupina, stanje, provjera imena), uređivanje i vlastita slika, „Predloži teme”
(event_calendar: opći praznici), izbor novčanika (zadano isključen), „Lansiraj” / „Lansiraj odabrane” uz okvir
potvrde, pokušaji, knjiga ishoda sa zbrojem po skupini i CSV. Sve slanje radi posao pumptokeni.posao, jedno po jedno.
"""
import base64
import datetime as dt
import json
import os
import time

from pumptokeni import devwallet, guards, image, launch, outcomes, provjera, store
from ui.html import badge, esc, table, tdesc

PATH = "/pump-tokeni"
STATE_WORDS = {"nacrt": ("nacrt", ""), "u_redu": ("u redu za slanje", "warn"), "salje": ("šalje se", "warn"),
               "lansiran": ("lansiran", "good"), "greska": ("greška", "bad"), "odbijen": ("odbijen", "bad")}
ATTEMPT_WORDS = {"priprema": "priprema", "poslano": "poslano, čeka potvrdu", "lansiran": "lansiran",
                 "neuspio": "nije uspio", "nepoznato": "nepoznato (potpis se provjerava)", "odbijeno": "odbijeno prije slanja"}
_BAL = {}


def _con():
    con = store.connect()
    store.seed(con)
    return con


def _sol(x, d=4):
    return "–" if x is None else f"{x:.{d}f}"


def _short(a):
    return f"{a[:4]}…{a[-4:]}" if a and len(a) > 10 else (a or "")


def balance(addr, max_age=60):
    """SOL saldo (RPC, predmemorija 60 s) ili None."""
    if not addr:
        return None
    hit = _BAL.get(addr)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    try:
        from trade import wallet
        v = wallet.sol_balance(addr)
    except Exception:  # noqa: BLE001
        v = None
    _BAL[addr] = (time.time(), v)
    return v


def suggest(con, today=None, days=60, path=None):
    """Opći praznici iz event_calendar/events_manual.json (kind 'holiday') u sljedećih `days` dana koji još nemaju
    nacrt. [(tema, datum)]. Ništa o osobama ni brendovima (samo kind holiday)."""
    today = today or dt.date.today()
    path = path or os.path.join(store.ROOT, "event_calendar", "events_manual.json")
    try:
        with open(path, encoding="utf-8") as f:
            evs = json.load(f)
    except (OSError, ValueError):
        return []
    have = {(d.get("tema") or "").lower() for d in store.drafts(con)}
    out = []
    for e in evs:
        if e.get("kind") != "holiday":
            continue
        ds = e.get("date") or ""
        try:
            if len(ds) == 5:   # recurring MM-DD
                d = dt.date(today.year, int(ds[:2]), int(ds[3:]))
                if d < today:
                    d = d.replace(year=today.year + 1)
            else:
                d = dt.date.fromisoformat(ds)
        except ValueError:
            continue
        if today <= d <= today + dt.timedelta(days=days) and (e.get("title") or "").lower() not in have:
            out.append((e["title"], d.isoformat()))
    return sorted(out, key=lambda x: x[1])


# ---------- page -------------------------------------------------------------------------------------------------

def _msg(qs):
    if qs.get("err"):
        return f'<div class=card style="border-color:var(--bad)"><b class=neg>Nije prošlo:</b> {esc(qs["err"])}</div>'
    if qs.get("ok"):
        return f'<div class=card style="border-color:var(--good)">{esc(qs["ok"])}</div>'
    return ""


def _wallet_html(con, c):
    ch = launch.wallet_choice(con)
    saved = store.get(con, "novcanik", launch.TOOL)
    addr = launch.address(ch) if ch != launch.OFF else None
    bal = balance(addr) if addr else None
    lines = [f"<b>Sada:</b> {esc(launch.CHOICES[ch])}"]
    if saved == launch.TRADING and ch == launch.OFF:
        lines.append("<span class=neg>Trgovački je bio izabran, ali prekidač nije uključen: isključeno.</span>")
    if ch != launch.OFF:
        lines.append(f"Adresa: <code>{esc(addr) if addr else 'nema ključa'}</code>"
                     + (f" · saldo <b>{bal:.4f} SOL</b> <a href=/pump-tokeni>osvježi</a>" if bal is not None else ""))
    tool = devwallet.address()
    if tool:
        tool_html = (f"<p>Novčanik pokusa u alatu: <code>{esc(tool)}</code>"
                     + (f" · saldo {balance(tool):.4f} SOL" if balance(tool) is not None else "") + "</p>"
                     "<form method=post action=/pump-tokeni/vrati onsubmit=\"return ptRefund(this)\">"
                     "<b>Vrati ostatak</b> (sav SOL minus mrežna naknada) na adresu: <input name=adresa size=46 "
                     "placeholder='tvoja adresa'> <input type=hidden name=potvrda value=''>"
                     f"<input type=hidden name=saldo value='{balance(tool) or 0:.6f}'> <button>↩ Vrati ostatak</button>"
                     "</form>")
    else:
        tool_html = ("<form method=post action=/pump-tokeni/stvori onsubmit=\"if(!confirm('Stvoriti novčanik pokusa u "
                     "alatu? Tajni ključ ostaje samo u datoteci na disku servisa (nikad se ne prikazuje). Na njega šalji samo "
                     "male iznose (npr. 0,2 SOL).'))return false;this.potvrda.value='1'\"><input type=hidden name=potvrda "
                     "value=''><button>🔑 Stvori novčanik pokusa</button></form>")
    radios = "".join(
        f"<label style='display:block;margin:4px 0'><input type=radio name=izbor value={k} "
        f"{'checked' if k == ch else ''}> {esc(v)}</label>" for k, v in launch.CHOICES.items())
    return ("<h2>Novčanik</h2><div class=card style='max-width:760px'>" + "<br>".join(lines) + tool_html +
            "<p class=neg><b>Upozorenje:</b> na novčanik pokusa idu samo mali iznosi. Ključ je samo u datoteci na disku "
            "servisa: ako se disk izgubi, ključ i SOL na njemu su izgubljeni. Zato „Vrati ostatak” nakon svake faze.</p>"
            "<form method=post action=/pump-tokeni/novcanik onsubmit=\"return ptWallet(this)\" style='margin-top:8px'>"
            + radios +
            "<p class=mut>Zasebni novčanik iz env: ključ (PUMP_DEV_PRIVATE_KEY) na Render upisuješ ti; alat ga nikad ne "
            "ispisuje ni ne logira.</p>"
            "<p class=neg><b>Trgovački novčanik</b> (SOLANA_PRIVATE_KEY): trošak lansiranja i naknada miješaju se s "
            "rezultatom pravog novca, a novčanik ostaje <b>javno označen kao dev</b> ovih tokena. Ne lansira se kad mu je "
            f"saldo ispod {c['min_sol'][launch.TRADING]:g} SOL.</p>"
            "<label><input type=checkbox name=potvrda value=1> Potvrđujem izbor trgovačkog novčanika</label> "
            "<button type=submit>Spremi novčanik</button></form></div>")


def _preflight_html(con):
    pf = store.get(con, "provjera") or {}
    st = launch.stopped(con)
    pil = store.get(con, "pilot") or {}
    rows = [[str(x["k"]), esc(x["naziv"]),
             badge("radi", "good") if x["ok"] else badge("ne radi", "bad") if x["ok"] is False else
             badge("pri prvom lansiranju", "warn"), esc(x["tekst"])] for x in pf.get("koraci") or []]
    head = ("<h2>Provjera prije lansiranja</h2>"
            + (f"<p>{badge('ZELENO', 'good') if pf.get('zeleno') else badge('NIJE ZELENO', 'bad')} "
               f"<span class=mut>{time.strftime('%d.%m. %H:%M', time.localtime(pf['ts']))}, nacrti "
               f"{esc(', '.join('#' + str(i) for i in pf.get('ids') or []))}</span></p>" if pf else
               "<p class=mut>Još nije pokrenuta.</p>"))
    return (head + table(["#", "Korak", "Stanje", "Detalj"], rows, tid="ptpf", empty="Nema rezultata.")
            + "<p><button type=submit form=ptl formaction=/pump-tokeni/provjera>🩺 Pokreni provjeru</button> "
              "<span class=mut>(za odabrane nacrte; bez odabira za sve koji se mogu lansirati)</span></p>"
            + ("<p><b>Red:</b> " + (f"<span class=neg>zaustavljen: {esc(st.get('razlog'))}</span>" if st else
                                    ("radi (pilot odobren " + time.strftime('%d.%m. %H:%M',
                                                                            time.localtime(pil['odobren_ts'])) + ")")
                                    if pil else "pilot nije odobren")
               + " <form method=post action=/pump-tokeni/zaustavi style=display:inline><button class=sm>⏹ Zaustavi red"
                 "</button></form></p>"))


def _check_cell(d):
    r = store.check_of(d)
    if not r:
        return "<span class=mut>nije provjereno</span>"
    if r.get("ok") and guards.fresh_ok(r):
        return badge("prolazi", "good") + f"<br><span class=mut>{esc(r.get('dex') or '')}</span>"
    if r.get("ok"):
        return badge("zastarjelo", "warn") + "<br><span class=mut>provjera starija od 24 h: ponovi</span>"
    return badge("odbijeno", "bad") + "<br>" + "<br>".join(esc(x) for x in r.get("razlozi") or [])


def _draft_rows(con):
    rows = []
    for d in store.drafts(con):
        w, k = STATE_WORDS.get(d["stanje"], (d["stanje"], ""))
        did = d["id"]
        can_launch = d["stanje"] in ("nacrt", "odbijen", "greska")
        act = []
        if can_launch:
            act.append(f"<button type=submit form=ptl name=id value={did} class=sm>🚀 Lansiraj (pilot)</button>")
        if d["stanje"] == "u_redu":
            act.append(f"<form method=post action=/pump-tokeni/makni style=display:inline><input type=hidden name=id "
                       f"value={did}><button class=sm>Makni iz reda</button></form>")
        act.append(f"<a href='#n{did}'>Uredi</a>")
        img = (f"<img src='/pump-tokeni/slika/{did}' width=56 height=56 alt='' loading=lazy style='border-radius:8px'>"
               if d["slika"] else "<span class=mut>nema</span>")
        rows.append([f"<input type=checkbox name=id value={did} form=ptl {'disabled' if not can_launch else ''}>",
                     esc(d["tema"] or "") + (f"<br><span class=mut>{esc(d['datum_teme'] or '')}</span>" if d['datum_teme'] else ""),
                     f"<b>{esc(d['ime'] or '')}</b>", f"<code>{esc(d['simbol'] or '')}</code>",
                     f"<span style='font-size:12.5px'>{esc(d['opis'] or '')}</span>", img, esc(d["skupina"] or ""),
                     badge(w, k), _check_cell(d), " ".join(act)])
    return rows


def _edit_forms(con):
    b = []
    for d in store.drafts(con):
        did = d["id"]
        lock = d["stanje"] in ("salje", "lansiran")

        def inp(name, label, maxlen):
            return (f"<label style='display:block;margin:4px 0'><b>{label}</b><br><input name={name} maxlength={maxlen} "
                    f"value=\"{esc(d.get(name) or '')}\" style='width:100%;max-width:420px' {'disabled' if lock else ''}>"
                    "</label>")
        b.append(f"<details id=n{did} class=card style='max-width:760px'><summary><b>#{did} {esc(d['simbol'] or '')}</b> "
                 f"{esc(d['ime'] or '')}</summary>"
                 + (f"<p class=mut>Lansiran ili se šalje: polja se više ne mijenjaju.</p>" if lock else "")
                 + f"<form method=post action=/pump-tokeni/uredi><input type=hidden name=id value={did}>"
                 + inp("tema", "Tema", 80) + inp("datum_teme", "Datum teme (YYYY-MM-DD)", 10) + inp("ime", "Ime", 32)
                 + inp("simbol", "Simbol (2-10 slova/brojki)", 10)
                 + "<label style='display:block;margin:4px 0'><b>Opis</b> <span class=mut>(engleski, kratak, istinit, bez "
                   "obećanja zarade, bez poveznica)</span><br><textarea name=opis rows=3 maxlength=500 "
                   f"style='width:100%;max-width:560px' {'disabled' if lock else ''}>{esc(d['opis'] or '')}</textarea></label>"
                 + inp("skupina", "Skupina pokusa", 40)
                 + ("" if lock else "<button type=submit>💾 Spremi</button>") + "</form>"
                 + ("" if lock else
                    f"<form method=post action=/pump-tokeni/slika enctype=application/x-www-form-urlencoded "
                    f"style='margin-top:8px'><input type=hidden name=id value={did}><input type=hidden name=data>"
                    "<b>Vlastita slika</b> <input type=file accept='image/*' onchange=\"ptImg(this)\"> "
                    "<span class=mut>(preradi se u 512×512 PNG)</span></form>"
                    f"<form method=post action=/pump-tokeni/generiraj style='margin-top:6px'><input type=hidden name=id "
                    f"value={did}><button class=sm>🎨 Nova slika iz generatora</button></form>"
                    f"<form method=post action=/pump-tokeni/provjeri style='margin-top:6px'><input type=hidden name=id "
                    f"value={did}><button class=sm>🔎 Provjeri ime</button></form>")
                 + "</details>")
    return "".join(b)


def _attempt_rows(con):
    rows = []
    for a in store.attempts(con, 200):
        mint = a["mint"] or ""
        rows.append([time.strftime("%d.%m. %H:%M", time.localtime(a["ts"])), esc(a["tema"] or ""),
                     esc(a["skupina"] or ""), f"<code>{esc(a['simbol'] or '')}</code>",
                     esc(launch.CHOICES.get(a["novcanik"], a["novcanik"] or "")),
                     (f"<a href='https://pump.fun/coin/{esc(mint)}' target=_blank rel='noopener noreferrer'>"
                      f"{esc(_short(mint))} ↗</a>" if mint and a["stanje"] == "lansiran" else esc(_short(mint))),
                     (f"<a href='https://solscan.io/tx/{esc(a['potpis'])}' target=_blank rel='noopener noreferrer'>"
                      f"{esc(_short(a['potpis']))} ↗</a>" if a["potpis"] else ""),
                     (_sol(a["trosak_sol"], 5), a["trosak_sol"] or 0, "n"), (_sol(a["sim_sol"], 5), a["sim_sol"] or 0, "n"),
                     esc(ATTEMPT_WORDS.get(a["stanje"], a["stanje"] or "")),
                     f"<span class=neg>{esc(a['greska'])}</span>" if a["greska"] else ""])
    return rows


def _book_html(con):
    rows, groups = outcomes.book(con)

    def pt(r, k, f):
        x = r["tocke"].get(k, {}).get(f)
        return "–" if x is None else (f"{x:,.0f}" if isinstance(x, float) else str(x))
    trs = [[f"<code>{esc(r['simbol'])}</code>", esc(r["skupina"] or ""),
            pt(r, "1h", "promet_usd"), pt(r, "12h", "promet_usd"), pt(r, "24h", "promet_usd"), pt(r, "7d", "promet_usd"),
            pt(r, "24h", "txns"), "–" if r["max_mcap_usd"] is None else f"{r['max_mcap_usd']:,.0f}",
            "–" if r["bondan"] is None else ("da" if r["bondan"] else "ne"),
            _sol(r.get("trosak_sol"), 5), _sol(r["naknada_sol"], 5),
            ("–" if r["neto_sol"] is None else f"<b class={'pos' if r['neto_sol'] >= 0 else 'neg'}>"
             f"{r['neto_sol']:+.5f}</b>")] for r in rows]
    gs = [[esc(k), str(g["n"]), str(g["s_ishodom"]), str(g["bondano"]), _sol(g["trosak_sol"], 5),
           _sol(g["naknada_sol"], 5), f"<b class={'pos' if g['neto_sol'] >= 0 else 'neg'}>{g['neto_sol']:+.5f}</b>"]
          for k, g in sorted(groups.items())]
    return ("<h2>Knjiga ishoda</h2>" + tdesc(
        "DexScreener na +1 h, +12 h, +24 h i +7 d od lansiranja (besplatno). Promet u $; na +7 d samo zadnji dan. "
        f"Procjena naknade: promet × 0,30 % / cijena SOL-a, <b>{esc(outcomes.RATE_NOTE)}</b>. Neto = procjena naknade − "
        "izmjereni trošak lansiranja.")
        + table(["Simbol", "Skupina", ("Promet 1 h", "n"), ("12 h", "n"), ("24 h", "n"), ("7 d (dan)", "n"),
                 ("Tx 24 h", "n"), ("Najviši mcap", "n"), "Bondan", ("Trošak SOL", "n"), ("Naknada SOL (procj.)", "n"),
                 ("Neto SOL", "n")], trs, tid="ptbook", empty="Još nema lansiranih tokena.")
        + "<h3>Zbroj po skupini</h3>"
        + table(["Skupina", ("Tokena", "n"), ("S ishodom", "n"), ("Bondano", "n"), ("Trošak SOL", "n"),
                 ("Naknada SOL (procj.)", "n"), ("Neto SOL", "n")], gs, tid="ptgrp", empty="Nema skupina s lansiranjem.")
        + "<p><a href=/pump-tokeni/csv download>⬇ Preuzmi CSV</a> <span class=mut>(za istraživanje; bez adresa kupaca)"
          "</span></p>")


JS = """<script>
function ptWallet(f){var r=f.querySelector('input[name=izbor]:checked');if(!r)return false;
if(r.value==='trgovacki'){if(!f.potvrda.checked){alert('Za trgovački novčanik označi kvačicu potvrde.');return false}
return confirm('Trgovački novčanik (SOLANA_PRIVATE_KEY) plaća lansiranja pokusa.\\nTrošak i naknada miješaju se s rezultatom pravog novca, a novčanik ostaje javno označen kao dev.\\nPotvrđuješ?')}return true}
function ptLaunch(f,ev){var b=ev&&ev.submitter;if(b&&b.getAttribute('formaction'))return true;
var boxes=document.querySelectorAll('input[name=id][form=ptl]');var sel=[];
if(b&&b.name==='id'){boxes.forEach(function(x){x.checked=false});sel=[b.value]}else{boxes.forEach(function(x){if(x.checked)sel.push(x.value)})}
if(!sel.length){alert('Odaberi barem jedan nacrt.');return false}var c=PT,n=sel.length;
var names=sel.map(function(i){return '#'+i+' '+(c.names[i]||'')}).join(', ');
var t='ODOBRI PILOT\\nNovčanik: '+c.w+'\\nNacrti ('+n+'): '+names+'\\nRazmak: '+c.gap+' min (prvi odmah), najviše '+c.day+' dnevno\\nOčekivani ukupni trošak: oko '+(n*c.lo).toFixed(4)+'–'+(n*c.hi).toFixed(4)+' SOL ('+c.lo+'–'+c.hi+' po tokenu, izmjereno); strop simulacije '+c.max+' SOL po tokenu\\nBEZ VLASTITE KUPNJE (0 SOL), token se ostavlja.\\nAko prvo lansiranje ne uspije ili trošak prijeđe strop, red staje sam.';
if(!confirm(t))return false;f.potvrda.value='1';return true}
function ptRefund(f){var a=(f.adresa.value||'').trim();if(!a){alert('Upiši adresu.');return false}
if(!confirm('Vrati ostatak s novčanika pokusa\\nNa adresu: '+a+'\\nIznos: oko '+(parseFloat(f.saldo.value)-0.000005).toFixed(6)+' SOL (sav saldo minus mrežna naknada; točan iznos se čita pri slanju)\\nPrije slanja ide simulacija.'))return false;f.potvrda.value='1';return true}
function ptImg(i){var f=i.files&&i.files[0];if(!f)return;if(f.size>3000000){alert('Slika je veća od 3 MB.');return}
var r=new FileReader();r.onload=function(){var fm=i.form;fm.data.value=r.result;fm.submit()};r.readAsDataURL(f)}
</script>"""


def page(qs, user, auto=None):
    con = _con()
    try:
        auto = (os.environ.get("PUMP_TOKENI_AUTO_PROVJERA", "1") != "0") if auto is None else auto
        if auto and provjera.due(con):
            try:
                provjera.run(con)
            except Exception as e:  # noqa: BLE001 - the page always opens
                print(f"pump tokeni provjera: nije uspjela ({type(e).__name__})", flush=True)
        c = launch.cfg()
        ch = launch.wallet_choice(con)
        addr = launch.address(ch) if ch != launch.OFF else None
        now = int(time.time())
        why = launch.blocked_reason(con, now)
        note = store.get(con, "red_razlog") or {}
        n_q = len(launch.queue(con))
        wlabel = (launch.CHOICES[ch] + (f" {_short(addr)}" if addr else "")) if ch != launch.OFF else "ISKLJUČEN"
        pt = {"w": wlabel, "lo": launch.EXPECTED[0], "hi": launch.EXPECTED[1], "max": c["max_sol"],
              "gap": int(c["razmak_s"] // 60), "day": c["dnevno"],
              "names": {str(d["id"]): f"{d['simbol']} {d['ime']}" for d in store.drafts(con)}}
        b = ["<meta name=robots content='noindex,nofollow'>",
             "<h1>🧪 Pump Fun tokeni</h1>",
             "<p class=mut>Ovu stranicu vidi samo vlasnik. Kontrolirani pokus: lansiranje vlastitih tokena na pump.fun "
             "<b>bez vlastite kupnje (0 SOL)</b>; token se ostavlja. Alat naše tokene nikad ne kupuje ni ne prodaje.</p>",
             _msg(qs),
             "<div class=card style='max-width:760px'>"
             f"<b>Stropovi:</b> danas poslano {launch.sent_today(con, now)} od {c['dnevno']} (tvrdi max "
             f"{launch.HARD_MAX_DNEVNO}) · razmak {int(c['razmak_s'] // 60)} min · simulacija najviše {c['max_sol']:g} SOL "
             f"po tokenu · priority do {c['priority_sol']:g} SOL · u redu {n_q}<br>"
             f"<b>Očekivani trošak:</b> oko {launch.EXPECTED[0]:g}–{launch.EXPECTED[1]:g} SOL po tokenu (izmjereno s lanca "
             "25.11.: mrežna naknada ~0,0002, ostalo najam računa)<br>"
             f"<b>Metapodaci:</b> IPFS preko {'Pinate (PINATA_JWT)' if c['ipfs'] == 'pinata' else 'pump.fun/api/ipfs'}"
             + ("" if c["ipfs"] == "pinata" else " <span class=neg>(PumpPortal dokumentacija 25.11.: pump.fun ovaj "
                                               "put više ne podržava; za Pinatu upiši PINATA_JWT na Render)</span>")
             + "<br><b>Red sada:</b> " + (f"<span class=neg>{esc(why)}</span>" if why else "spreman")
             + (f"<br><span class=mut>Zadnja napomena posla: {esc(note.get('tekst', ''))}</span>" if note else "")
             + "</div>",
             _wallet_html(con, c),
             _preflight_html(con),
             "<h2>Nacrti</h2>",
             tdesc("Svaki nacrt prije lansiranja mora proći provjeru imena: DexScreener (nema poznatog tokena istog imena "
                   "ili simbola s likvidnošću ≥ 50k $), zabranjene riječi, bez poveznica u opisu. Posao je ponavlja "
                   "odmah prije slanja."),
             f"<form id=ptl method=post action=/pump-tokeni/lansiraj onsubmit=\"return ptLaunch(this,event)\">"
             "<input type=hidden name=potvrda value=''></form>",
             table(["", "Tema", "Ime", "Simbol", "Opis", "Slika", "Skupina", "Stanje", "Provjera", ""], _draft_rows(con),
                   tid="ptnac", empty="Nema nacrta."),
             "<p><button type=submit form=ptl>✅ Odobri pilot (lansiraj odabrane)</button> "
             "<button type=submit form=ptl formaction=/pump-tokeni/provjera>🩺 Provjera prije lansiranja</button> "
             "<span class=mut>Okvir potvrde ispisuje novčanik, nacrte, razmak i očekivani trošak; zatim posao sam "
             "lansira jedan po jedan (prvi odmah). Pilot se odobrava samo uz zelenu provjeru.</span></p>",
             "<form method=post action=/pump-tokeni/provjeri style=display:inline><input type=hidden name=id value=sve>"
             "<button class=sm>🔎 Provjeri sva imena</button></form> "
             "<form method=post action=/pump-tokeni/teme style=display:inline><button class=sm>💡 Predloži teme</button>"
             "</form>",
             _edit_forms(con),
             "<details class=card style='max-width:760px'><summary><b>➕ Novi nacrt (ručni unos)</b></summary>"
             "<form method=post action=/pump-tokeni/nacrt>"
             + "".join(f"<label style='display:block;margin:4px 0'><b>{lab}</b><br><input name={n} maxlength={m} "
                       f"style='width:100%;max-width:420px'></label>"
                       for n, lab, m in (("tema", "Tema", 80), ("datum_teme", "Datum (YYYY-MM-DD)", 10),
                                         ("ime", "Ime", 32), ("simbol", "Simbol", 10), ("skupina", "Skupina", 40)))
             + "<label style='display:block;margin:4px 0'><b>Opis</b><br><textarea name=opis rows=3 maxlength=500 "
               "style='width:100%;max-width:560px'></textarea></label><button type=submit>Dodaj</button></form></details>",
             "<details class=card style='max-width:760px'><summary><b>🚫 Zabranjene riječi</b></summary>"
             f"<p class=mut>Uvijek: {esc(', '.join(guards.BANNED))}, „by &lt;ime&gt;”, poveznice. Dodaj svoje (zarezom):</p>"
             "<form method=post action=/pump-tokeni/zabranjene><input name=rijeci style='width:100%;max-width:560px' "
             f"value=\"{esc(', '.join(store.get(con, 'zabranjene', []) or []))}\"> <button>Spremi</button></form></details>",
             "<h2>Pokušaji lansiranja</h2>",
             table(["Vrijeme", "Tema", "Skupina", "Simbol", "Novčanik", "Mint", "Potpis", ("Trošak SOL", "n"),
                    ("Simulacija SOL", "n"), "Stanje", "Greška"], _attempt_rows(con), tid="ptpok",
                   empty="Još nijedan pokušaj."),
             _book_html(con),
             f"<script>var PT={json.dumps(pt, ensure_ascii=False)};</script>" + JS]
        return "Pump Fun tokeni", "".join(b)
    finally:
        con.close()


def image_png(did):
    con = _con()
    try:
        d = store.draft(con, did)
        return d["slika"] if d else None
    finally:
        con.close()


def csv_bytes():
    con = _con()
    try:
        return outcomes.csv_text(con).encode("utf-8")
    finally:
        con.close()


# ---------- POST ---------------------------------------------------------------------------------------------------

def _ids(form):
    out = []
    for x in form.get("id_list") or ([form["id"]] if form.get("id") else []):
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def post(path, form, user, search=None):
    """Vlasnikov POST; vraća adresu preusmjeravanja (s ?ok= ili ?err=)."""
    from urllib.parse import quote
    from trade import settings
    if not settings.is_owner(user):
        return PATH + "?err=" + quote("samo vlasnik")
    act = path[len(PATH) + 1:] if path.startswith(PATH + "/") else ""
    con = _con()
    try:
        msg = _do(con, act, form, user, search)
        return PATH + "?ok=" + quote(msg)
    except ValueError as e:
        return PATH + "?err=" + quote(str(e))
    finally:
        con.close()


def _do(con, act, form, user, search=None):
    extra = store.get(con, "zabranjene", []) or []
    if act == "nacrt":
        f = {k: form.get(k, "") for k in store.DRAFT_FIELDS}
        if not (f.get("ime") and f.get("simbol")):
            raise ValueError("ime i simbol su obavezni")
        did = store.add_draft(con, f, image.generate(f["ime"].strip(), f["simbol"].strip().upper()))
        return f"nacrt #{did} dodan; provjeri ime prije lansiranja"
    if act == "uredi":
        did = (_ids(form) or [0])[0]
        d = store.update_draft(con, did, {k: form[k] for k in store.DRAFT_FIELDS if k in form})
        if not d["slika_vlastita"]:
            store.set_image(con, did, image.generate(d["ime"] or "", d["simbol"] or ""), False)
        return f"#{did} spremljen; provjera imena se ponavlja"
    if act in ("slika", "generiraj"):
        did = (_ids(form) or [0])[0]
        d = store.draft(con, did)
        if not d or d["stanje"] in ("salje", "lansiran"):
            raise ValueError("slika se mijenja samo na nacrtu koji nije lansiran")
        if act == "generiraj":
            store.set_image(con, did, image.generate(d["ime"] or "", d["simbol"] or ""), False)
            return f"#{did}: nova slika iz generatora"
        data = form.get("data") or ""
        raw = base64.b64decode(data.split(",", 1)[-1] or "", validate=False) if data else b""
        store.set_image(con, did, image.normalize(raw), True)
        return f"#{did}: tvoja slika spremljena (512×512 PNG)"
    if act == "provjeri":
        ids = [d["id"] for d in store.drafts(con)] if form.get("id") == "sve" else _ids(form)
        n_ok = 0
        for did in ids:
            d = store.draft(con, did)
            if not d or d["stanje"] in ("salje", "lansiran"):
                continue
            r = guards.check(d, extra, search=search)
            store.save_check(con, did, r)
            n_ok += 1 if r["ok"] else 0
        return f"provjereno {len(ids)}, prolazi {n_ok}"
    if act == "lansiraj":
        ids = _ids(form)
        n, why = launch.approve_pilot(con, ids, user, str(form.get("potvrda") or "") == "1")
        print(f"pump tokeni: pilot odobren ({n} nacrta: {', '.join('#' + str(i) for i in ids)})", flush=True)
        return f"pilot odobren: u redu {n}" + (f"; preskočeno: {'; '.join(why)}" if why else "")
    if act == "provjera":
        steps = provjera.run(con, _ids(form) or None, search=search)
        bad = [x for x in steps if x["ok"] is False]
        return "provjera: zeleno" if not bad else f"provjera: ne radi {', '.join(str(x['k']) for x in bad)}"
    if act == "zaustavi":
        launch.stop_queue(con, "vlasnik: Zaustavi red")
        return "red zaustavljen"
    if act == "stvori":
        if str(form.get("potvrda") or "") != "1":
            raise ValueError("stvaranje samo uz potvrdu")
        addr = devwallet.create()
        print(f"pump tokeni: novčanik pokusa stvoren, adresa {addr}", flush=True)
        if store.get(con, "novcanik") is None:
            store.put(con, "novcanik", launch.TOOL)
        return f"novčanik pokusa stvoren: {addr} (pošalji mu malo SOL-a, npr. 0,2)"
    if act == "vrati":
        r = devwallet.refund(form.get("adresa"), user, str(form.get("potvrda") or "") == "1")
        return (f"vraćeno {r['iznos_sol']:.6f} SOL, potpis {r['potpis']}" +
                ("" if r["ok"] else " (potvrda još nije stigla)" if r["ok"] is None else " (palo na lancu)"))
    if act == "makni":
        for did in _ids(form):
            launch.dequeue(con, did)
        return "maknuto iz reda"
    if act == "teme":
        sug = suggest(con)
        if not sug:
            return "kalendar nema novih općih praznika u sljedećih 60 dana: unesi temu ručno"
        for tema, datum in sug:
            store.add_draft(con, {"tema": tema, "datum_teme": datum, "ime": "", "simbol": "", "opis": ""})
        return f"dodano {len(sug)} tema iz kalendara: upiši ime, simbol i opis"
    if act == "novcanik":
        choice = form.get("izbor") or launch.OFF
        launch.set_wallet(con, choice, user, tap=str(form.get("potvrda") or "") == "1")
        return f"novčanik: {launch.CHOICES[choice]}"
    if act == "zabranjene":
        words = [w.strip() for w in (form.get("rijeci") or "").split(",") if w.strip()][:200]
        store.put(con, "zabranjene", words)
        return f"zabranjenih riječi (tvojih): {len(words)}"
    raise ValueError("nepoznata radnja")
