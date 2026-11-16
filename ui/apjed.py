"""Jednostavni "Prekidači" i "Postavke" stranice /pravi-trade (16.11., vlasnik: "kad otvorim, ima 15 kartica ovih, svaka
se može dodatno proširiti. Ne razumijem šta koja znači, kao da na kineskom piše ... Ovo jednostavno treba biti toliko
jednostavnije. Onda ovo settings, rules, isto.").

A presentation layer only: every form posts to the endpoint it always did (/pravi-trade/flag, /switch, /limits, /tp,
/sl, /grokon, /grokoff, /groklimits, /exitpause, /exitresume, /mcpok, /mcpno ...), nothing here changes what a switch
does. What changes is what the owner reads:

  Prekidači   what he needs daily on one screen, in plain Croatian, no internal codes (P14, MK3), no flag names:
                1. Pravi novac             one big switch + the caps and today's use in one line each
                2. Što bot trguje          two rows: Midcap dnevni raspon, Midcap 7 dana (state only)
                3. Istraživanje (demo)     one row that lists what runs; on / off per item inside
                4. Hitno zaustavi sve      the kill switch, red, always visible
                5. Napredno (N)            everything else as one closed, searchable list of plain rows
              a Grok request that waits for his tap is a row above them (and the badge on the closed card).
  Postavke    four blocks: Limiti, Izlazi, Obavijesti, Napredno (the rest, closed and searchable). What Prekidači
              shows is not repeated; what does nothing while the bot trades midcaps only (fokus_midcap) is left out
              (IDLE_FLAGS, IDLE_LIMITS, IDLE_CARDS: hidden, never deleted; "Stari prikaz" still lists everything).

Every row: a name of 2-4 plain words, one sentence "što radi", its state.
"""
import re
import time

from trade import executor, settings
from ui import pravitrade as pt
from ui import redak
from ui.html import esc

# ---------- plain words --------------------------------------------------------------------------------------------
# flag -> (name of 2-4 plain words, one sentence "što radi", the mode that means "on")
PLAIN = {
    settings.SWITCH_ALL: ("Pravi novac: kopiranje",
                          "Kopiranje influencera i novčanika i stare strategije kupuju pravim novcem bez dokaza u demu.", "live"),
    settings.VEL_SWITCH: ("Pravi novac", "Bot sam kupuje i prodaje pravim SOL-om, unutar stropova.", "live"),
    settings.VELIKI: ("Midcap u demu",
                      "Demo račun trguje oba midcap pravila (dnevni raspon i 7 dana), bez pravog novca.", "paper"),
    "exit_plan_live": ("Posebni izlazi uživo",
                       "Izlazi s više ciljeva i pomičnim stopom rade i na pravom novcu, ne samo u demu.", "live"),
    "rug_labels_v2_ok": ("Nove oznake prevara",
                         "Bot koristi novije oznake prevarantskih tokena umjesto starog, strožeg bloka.", "live"),
    "live_trades_retention": ("Brisanje starih tradeova",
                              "Noću briše stare sirove podatke o tuđim tradeovima da baza ne raste; sažeci ostaju.", "live"),
    "tg_text_retention": ("Brisanje starih poruka",
                          "Noću briše tekst starih Telegram objava; zapis da je objava postojala ostaje.", "live"),
    settings.ZADNJIH5: ("Prati najbolje izvore",
                        "Autopilot sam prati influencere i novčanike čijih je zadnjih 5 poziva zaradilo barem 10 %.", "live"),
    settings.KRITICAR: ("AI kritičar",
                        "Drugi AI svaki dan pregleda otvorene pozicije i pravila i piše savjete. Ništa ne kupuje ni ne mijenja.",
                        "live"),
    settings.IZVORI: ("Pravi novac: konsenzus",
                      "Stara strategija: kupnja kad se više izvora složi oko istog tokena.", "live"),
    settings.OSC_SWITCH: ("Pravi novac: oscilator",
                          "Stara strategija: brze kupnje i prodaje tokena koji tijekom dana idu gore-dolje.", "live"),
    settings.FOKUS: ("Samo midcapovi",
                     "Bot skuplja podatke i trguje samo tokene vrijedne 2 do 200 milijuna $; sve za male tokene je ugašeno.",
                     "live"),
    settings.ARHIVA: ("Arhiva malih tokena",
                      "Noću seli stare podatke malih i propalih tokena u arhivu na disku da baza bude brža. Ništa se ne briše.",
                      "live"),
    settings.MIKROKAP: ("Bez malih tokena",
                        "Bot automatski ne kupuje tokene manje od 5 milijuna $; tvoje ručne kupnje to ne dira.", "live"),
    settings.MIKROKAP_MOON: ("Iznimka za male tokene",
                             "Samo u demu: bot smije kupiti mali token kad ga istovremeno spominje puno neovisnih izvora.",
                             "paper"),
    settings.MAKROINF_JAVNO: ("Javne stranice influencera",
                              "Stranice s ocjenama makro influencera vidljive su svima na internetu.", "live"),
    settings.INSAJDERI2: ("Insajderi", "Demo kupuje kad provjerena grupa ranih kupaca kupi token.", "paper"),
    settings.MAKROINF: ("Makro influenceri",
                        "Demo ne ulazi u nove pozicije dok najtočniji makro influenceri očekuju pad.", "paper"),
}
# Napredno of Prekidači, in this order (the owner's switches that are not one of the four rows above it)
NAPREDNO = (settings.SWITCH_ALL, settings.VELIKI, settings.FOKUS, settings.MIKROKAP, settings.MIKROKAP_MOON,
            "exit_plan_live", settings.KRITICAR, "rug_labels_v2_ok", settings.ZADNJIH5, settings.IZVORI,
            settings.OSC_SWITCH, settings.MAKROINF_JAVNO, settings.ARHIVA, "live_trades_retention", "tg_text_retention")
REAL_MONEY = frozenset({settings.SWITCH_ALL, settings.VEL_SWITCH, settings.IZVORI, settings.OSC_SWITCH})
# what does nothing while the bot trades midcaps only (ops/fokus.py OFF / RETARGET: their runners do not run or are
# pointed at the midcap list). Hidden from Postavke while fokus_midcap is on and the flag itself is off; never deleted.
IDLE_FLAGS = {
    "range_dca": "range", "range_market": "range", "range_demo": "range", "range_flip": "range", "range_missed": "range",
    "momentum_scalp": "momentum", "proposals": "prijedlozi", "market_scan": "skener", "event_tokens": "eventi",
    "insider_copy": "insajderi prije poziva", "pre_shill": "kupci prije shill mreže", "group_discovery": "ekipe callera",
    "fast_path": "brzi put", "x_call_scalp": "brzi put", "konsenzus": "konsenzus", "oscilator": "oscilator",
    settings.IZVORI: "konsenzus", settings.OSC_SWITCH: "oscilator", settings.ZADNJIH5: "zadnjih 5",
    "early_score": "nova lansiranja", "early_persist": "nova lansiranja",
}
IDLE_LIMITS = ("range_scalp_trades_day", "range_scalp_target_usd")   # run_range does not run: the fields are carried hidden
LOCKED_BOXES = ("follow_paper", "simianx")                           # locked since 4.11. (settings.LOCKED): never did anything
IDLE_CARDS = ("fast-path", "konsenzus", "oscilator")                 # diagnostics of strategies that do not run


def fokus_on(tcon):
    try:
        return settings.flag(settings.FOKUS, con=tcon) == "live"
    except Exception:  # noqa: BLE001 - unreadable = the old behaviour, nothing hidden
        return False


def flag_toast(name, mode):
    """The line after a switch was saved, in the page's plain words ("Pravi novac: uključen."); None for a flag
    without a plain name (the caller keeps its own text)."""
    p = PLAIN.get(name)
    if not p:
        return None
    on = mode == p[2] or (mode == "live" and p[2] == "paper")
    if name == settings.MAKROINF and mode == "shadow":
        return f"{p[0]}: samo mjeri."
    return f"{p[0]}: {'uključeno' if on else 'isključeno'}."


def _is_on(st, name):
    m = (st.get(name) or {}).get("mode") or "off"
    want = PLAIN.get(name, ("", "", "live"))[2]
    return m == want or m == "live"


def _g(x):
    return pt._g(x)


def _plural(n, one, few, many):
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def _flag_btn(name, on, owner, small=True, confirm=""):
    """The on / off control of one flag: a switch that posts the other state to /pravi-trade/flag; a viewer reads
    the word."""
    word = "uključeno" if on else "isključeno"
    if not owner:
        return f'<span class="apx-jst{" on" if on else ""}">{word}</span>'
    mode = "off" if on else PLAIN.get(name, ("", "", "live"))[2]
    lab = esc(PLAIN.get(name, (name,))[0])
    ask = f' onsubmit="return confirm(\'{esc(confirm)}\')"' if confirm and not on else ""
    return (f'<form method=post action=/pravi-trade/flag class=apx-jf{ask}><input type=hidden name=name value={esc(name)}>'
            f'<input type=hidden name=mode value={mode}><button class="ap-sw{" on" if on else ""}{"" if small else " apx-jbig"}" '
            f'role=switch aria-checked={"true" if on else "false"} aria-label="{lab}: {"isključi" if on else "uključi"}" '
            f'title="{"Isključi" if on else "Uključi"}"></button></form>')


# ---------- Prekidači ----------------------------------------------------------------------------------------------

def novac_state(tcon, cfg, now):
    """What the row "Pravi novac" says: {"on", "running", "why", "caps", "floor", "buys", "open", "pnl", "others"}.
    on = the switch (pravi_novac_veliki); running = real money can actually be bought with now (the switch, "Hitno
    zaustavi" not pressed, the key in place, nothing holds the midcap entries); why = what holds it, in plain words;
    others = other real-money buyers that are on (they live in Napredno)."""
    caps = executor.veliki_caps(cfg)
    on = executor.veliki_on(tcon)
    why = ""
    if on:
        if not cfg.get("on"):
            why = "sve je zaustavljeno (dolje „Pokreni ponovno”)"
        elif not executor.armed():
            why = "ključ novčanika nije postavljen, kupnje su samo proba"
        else:
            try:
                from veliki import gate
                r = gate.real_refusal(con=tcon, now=now)
            except Exception:  # noqa: BLE001 - unreadable: said as unknown, never as "runs"
                r = "nepoznato"
            if r:
                why = ("BTC naglo pada: bot čeka da se smiri" if "BTC" in r and "pad" in r else
                       "cijena BTC-a trenutno nije poznata: bot čeka" if "BTC" in r else
                       "čeka dokaz iz testa na povijesti" if r != "nepoznato" else "stanje se trenutno ne može pročitati")
    tz = cfg.get("day_tz")
    try:
        buys = executor.veliki_buys(tcon, now, "live", tz)
        n_open = tcon.execute("SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'").fetchone()[0]
        pnl = executor.day_pnl(tcon, now, "live", tz)
    except Exception:  # noqa: BLE001
        buys = n_open = pnl = None
    others = []
    try:
        if settings.pravi_novac_sve(con=tcon):
            others.append("kopiranje")
        from ui import grokauto
        if grokauto.state(tcon, now)["on"]:
            others.append("Grok autotrade")
        st = settings.flag_state(tcon)
        others += [PLAIN[n][0].split(": ")[-1] for n in (settings.IZVORI, settings.OSC_SWITCH) if _is_on(st, n)]
    except Exception:  # noqa: BLE001
        pass
    return {"on": on, "running": on and not why, "why": why, "caps": caps, "floor": executor.equity_floor(cfg),
            "buys": buys, "open": n_open, "pnl": pnl, "others": others, "stopped": not cfg.get("on")}


def caps_text(ns):
    c = ns["caps"]
    return (f'{_g(c["max_sol_per_trade"])} SOL po kupnji · {c["max_open"]} otvorenih · {c["max_buys_day"]} kupnji dnevno · '
            f'dnevni gubitak {_g(c["max_loss_day"])} SOL · staje ako novčanik padne pod {_g(ns["floor"])} SOL')


def today_text(ns):
    if ns["buys"] is None:
        return ""
    pnl = ns["pnl"] or 0.0
    res = ("rezultat 0" if abs(pnl) < 0.00005 else
           f'{"dobit" if pnl > 0 else "gubitak"} {redak.num(abs(pnl), 3)} SOL')
    return (f'danas {ns["buys"]} {_plural(ns["buys"], "kupnja", "kupnje", "kupnji")}, otvoreno {ns["open"]} od '
            f'{ns["caps"]["max_open"]}, {res}')


def _novac_row(ns, owner):
    name, what, _m = PLAIN[settings.VEL_SWITCH]
    lines = [f'<p class=apx-js><b>Stropovi:</b> {esc(caps_text(ns))}.</p>']
    t = today_text(ns)
    if t:
        lines.append(f'<p class=apx-js><b>Danas:</b> {esc(t[6:])}.</p>')
    if ns["on"] and ns["why"]:
        lines.append(f'<p class="apx-js warn">Uključen, ali sada ne kupuje: {esc(ns["why"])}.</p>')
    if ns["others"]:
        lines.append(f'<p class="apx-js warn">Pravim novcem kupuje i: {esc(", ".join(ns["others"]))} (pod Napredno).</p>')
    ctl = _flag_btn(settings.VEL_SWITCH, ns["on"], owner, small=False,
                    confirm="Uključiti pravi novac? Bot će sam kupovati pravim SOL-om, unutar stropova.")
    state = "uključen" if ns["on"] else "isključen"
    return (f'<div class="apx-jtop apx-jr apx-jnovac{" on" if ns["on"] else ""}" id=fl-{settings.VEL_SWITCH}>'
            f'<div class=apx-jh><div class=apx-jt><b>{esc(name)}</b><span class="apx-jst{" on" if ns["on"] else ""}">{state}</span>'
            f'</div>{ctl}</div><p class=apx-jd>{esc(what)}</p>{"".join(lines)}</div>')


def midcap_state(tcon, now):
    """{"demo", "intra_real", "range_real"}: is the midcap demo on, and does each rule also buy with real money now
    (the switch on and nothing holding it; the 7-day rule only once its test on history is in the plus, veliki/live)."""
    out = {"demo": False, "intra_real": False, "range_real": False}
    try:
        out["demo"] = settings.flag(settings.VELIKI, con=tcon) in ("paper", "live")
        from veliki import gate
        if gate.switch_on(tcon) and gate.real_refusal(con=tcon, now=now) is None:
            out["intra_real"] = True
            out["range_real"] = bool(gate.wf_proof(size_sol=gate.real_caps()["size_sol"])[0])
    except Exception as e:  # noqa: BLE001 - the rows still say what the rules are
        print(f"autopilot: stanje midcap pravila nije složeno: {type(e).__name__}: {e}", flush=True)
    return out


def _rules_block(ms):
    def state(real):
        if not ms["demo"] and not real:
            return "isključeno", ""
        return ("demo + pravi novac", " on") if real else ("samo demo", "")
    rows = []
    for name, what, real in (
            ("Midcap dnevni raspon", "Kupuje velike tokene pri dnu raspona zadnja dva dana, proda sve na +10 do 15 %.",
             ms["intra_real"]),
            ("Midcap 7 dana", "Isto, pri dnu raspona zadnjih 7 dana. Samo demo dok test ne pokaže plus.",
             ms["range_real"])):
        word, cls = state(real)
        rows.append(f'<div class=apx-jr2><div><b>{name}</b><span class=apx-jd>{what}</span></div>'
                    f'<span class="apx-jst{cls}">{word}</span></div>')
    return f'<div class="apx-jtop apx-jg" id=sw-trguje><h3 class=apx-jh3>Što bot trguje</h3>{"".join(rows)}</div>'


def _research_row(tcon, owner):
    st = settings.flag_state(tcon)
    items = []
    for name in (settings.INSAJDERI2, settings.MAKROINF):
        nm, what, _m = PLAIN[name]
        mode = (st.get(name) or {}).get("mode") or "off"
        on = mode in ("paper", "live")
        note = " Sada samo mjeri, ne utječe na demo." if name == settings.MAKROINF and mode == "shadow" else ""
        items.append((nm, what + note, on, _flag_btn(name, on, owner), name))
    items.insert(1, ("Listing signali", "Mjeri što se dogodi s cijenom nakon najave listanja na burzi. Bez novca, uvijek radi.",
                     True, '<span class="apx-jst on">mjeri</span>', ""))
    run = [nm.lower() for nm, _w, on, _c, _n in items if on]
    reason = ("radi: " + ", ".join(run)) if run else "ništa ne radi"
    inner = "".join(f'<div class=apx-jr2{f" id=fl-{n}" if n else ""}><div><b>{esc(nm)}</b><span class=apx-jd>{esc(w)}</span></div>{c}</div>'
                    for nm, w, _on, c, n in items)
    r = pt._srow("Istraživanje (samo demo)", reason, f"{len(run)} od {len(items)}", None, value_tone="mut")
    return (f'<details class="ap-it apx-jtop apx-ji" id=sw-istr><summary>{r}</summary><div class=in>'
            f'<p class=apx-jd>Ovo ne troši pravi novac: bot samo provjerava bi li se isplatilo.</p>{inner}</div></details>')


def _stop_row(cfg, owner):
    on = bool(cfg.get("on"))
    if on:
        what = "Odmah prekida svaku kupnju pravim novcem, i tvoju ručnu. Prodaje otvorenih pozicija idu dalje."
        form = ('<form method=post action=/pravi-trade/switch class=apx-jf onsubmit="return confirm(\'Zaustaviti sve? '
                'Nove kupnje staju odmah, otvorene pozicije se i dalje prodaju po pravilima.\')"><input type=hidden '
                'name=on value=0><button class=apx-jstop>Zaustavi sve</button></form>')
        state = '<span class="apx-jst on">radi</span>'
    else:
        what = "Zaustavljeno: ništa se ne kupuje pravim novcem. Prodaje otvorenih pozicija idu dalje."
        form = ('<form method=post action=/pravi-trade/switch class=apx-jf onsubmit="return confirm(\'Pokrenuti ponovno? '
                'Bot smije opet kupovati pravim SOL-om, unutar stropova.\')"><input type=hidden name=on value=1>'
                '<button class=apx-jgo>Pokreni ponovno</button></form>')
        state = '<span class="apx-jst bad">zaustavljeno</span>'
    if not owner:
        form = ""
    return (f'<div class="apx-jtop apx-jr apx-jkill{"" if on else " off"}" id=sw-autopilot><div class=apx-jh><div class=apx-jt>'
            f'<b>Hitno zaustavi sve</b>{state}</div>{form}</div><p class=apx-jd>{what}</p></div>')


def _strip_sec(html):
    """The inside of a pt._sec / pt._item (its details and summary taken off), so a row never opens a card that
    opens another card."""
    m = re.match(r"\s*<details[^>]*>\s*<summary>.*?</summary>\s*<div class=in>(.*)</div>\s*</details>\s*$", html or "", re.S)
    return m.group(1) if m else (html or "")


def _adv_row(name, what, state, tone, inner, iid, on=False):
    r = pt._srow(name, what, state, None, value_tone=tone)
    return (f'<details class="ap-it apx-jn" id={iid} data-jn{" data-on" if on else ""}><summary>{r}</summary>'
            f'<div class=in>{inner}</div></details>')


def _advanced(d, tcon, cfg, owner, now):
    """[(html, is it on)] of the rows under "Napredno": the other owner switches by their plain names, Grok autotrade
    (state, today, limits), the exit plans' pause."""
    st = settings.flag_state(tcon)
    fokus = fokus_on(tcon)
    rows = []
    for name in NAPREDNO:
        if name not in st:
            continue
        nm, what, _m = PLAIN[name]
        on = _is_on(st, name)
        idle = fokus and name in IDLE_FLAGS
        if idle:
            what += " Ne radi dok bot trguje samo midcapove."
        if name == settings.SWITCH_ALL:   # its warning box with the caps and the button, as the owner ordered 14.11.
            inner = pt._safe("pravi-novac-sve", pt._switch_box, tcon, cfg, owner)
            rows.append((f'<div id=fl-{name}>' + _adv_row(nm, what, "uključeno" if on else "isključeno",
                                                           "bad" if on else "mut", inner, "sw-pravi", on) + '</div>', on))
            continue
        ask = "Uključiti pravi novac za ovu strategiju?" if name in REAL_MONEY else ""
        inner = (f'<div class=apx-jr2><div><b>{"Uključeno" if on else "Isključeno"}</b></div>'
                 f'{_flag_btn(name, on, owner, confirm=ask)}</div>')
        rows.append((_adv_row(nm, what, "uključeno" if on else "isključeno", "good" if on else "mut", inner,
                              f"fl-{name}", on), on))
    try:
        from ui import grokauto
        g_on = bool(grokauto.state(tcon, now)["on"])
    except Exception:  # noqa: BLE001
        g_on = False
    glive = pt._safe("grok-auto", pt._grok_auto_live, tcon, owner, d.get("positions"), now, False)
    gset = _strip_sec(pt._safe("grok-postavke", pt._grok_auto_setup, tcon, owner))
    if glive or gset:
        rows.append((_adv_row("Grok autotrade", "AI Grok sam kupuje i prodaje pravim novcem, unutar svojih limita.",
                              "uključeno" if g_on else "isključeno", "bad" if g_on else "mut", glive + gset, "sw-grok", g_on),
                     g_on))
    plans = pt._safe("exit-planovi", pt._exit_plans_block, tcon, owner)
    if plans:
        paused = bool(settings.raw(tcon).get("exit_plans_paused"))
        rows.append((_adv_row("Pauza posebnih izlaza", "Zaustavlja izlaze s više ciljeva; pozicije se tada prodaju po "
                              "običnom cilju i stopu.", "pauzirano" if paused else "rade", "warn" if paused else "mut",
                              plans, "sw-planovi", paused), paused))
    return rows


SEARCH = ('<label class=apx-jq><span class=apx-mut>Traži</span><input type=search data-jq placeholder="npr. brisanje, Grok, '
          'arhiva" autocomplete=off></label>')


def prekidaci(d, tcon, cfg, owner, now=None):
    """(the body of "Prekidači", the closed card's line, how many of Grok's requests wait). Five top rows at most
    (class apx-jtop); a waiting request is a row above them."""
    now = now or time.time()
    ns = novac_state(tcon, cfg, now)
    parts = []
    n_wait = 0
    mcp = pt._safe("mcp", pt._mcp_requests, tcon, owner)
    if mcp:
        try:
            from ui import mcpapi
            n_wait = len(mcpapi.pending(tcon, now)) if owner else 0
        except Exception:  # noqa: BLE001
            n_wait = 1
        r = pt._srow("Grok čeka tvoje odobrenje", "kupnja ili prodaja koju je predložio; vrijedi 15 min", "čeka", None,
                     value_tone="warn")
        parts.append(f'<details class=ap-it id=sw-mcp><summary>{r}</summary><div class=in>{mcp}</div></details>')
    parts.append(_novac_row(ns, owner))
    parts.append(_rules_block(midcap_state(tcon, now)))
    parts.append(pt._safe("istraživanje", _research_row, tcon, owner))
    parts.append(_stop_row(cfg, owner))
    adv = pt._safe("napredno", _advanced, d, tcon, cfg, owner, now, fallback=[])
    if adv:
        n_on = sum(1 for _h, on in adv if on)
        r = pt._srow(f"Napredno ({len(adv)})", "stare strategije, Grok, posebni izlazi, čišćenje baze",
                     f"{n_on} {_plural(n_on, 'uključen', 'uključena', 'uključeno')}", None, value_tone="mut")
        parts.append(f'<details class="ap-it apx-jtop apx-jadv" id=sw-napredno><summary>{r}</summary><div class=in>'
                     f'{SEARCH}<div class=apx-jlist>{"".join(h for h, _on in adv)}</div>'
                     '<p class="apx-mut apx-jnone" hidden>Nema prekidača s tim riječima.</p></div></details>')
    if ns["stopped"]:
        summ = "Zaustavljeno: ništa se ne kupuje pravim novcem"
    else:
        summ = "Pravi novac: " + ("uključen" if ns["on"] else "isključen")
        if ns["on"] and ns["why"]:
            summ += ", sada ne kupuje"
        t = today_text(ns)
        if ns["on"] and t:
            summ += " · " + ", ".join(t.split(", ")[:1] + t.split(", ")[2:])
    return "".join(p for p in parts if p), summ, n_wait


# ---------- Postavke -----------------------------------------------------------------------------------------------

def _limits_form(cfg, owner, fokus):
    """"Tvoje kupnje i kopiranje": the four limits the owner changes (ulog, otvorene pozicije, dnevni gubitak, ostaje u
    novčaniku) and the rest under "Još limita", one form to the same /pravi-trade/limits. The range scalp's two fields
    travel hidden while the range does not run; the two locked boxes are not shown (the server ignores them anyway)."""
    main = (("size_sol", "Ulog po kupnji (SOL)"), ("max_open", "Najviše otvorenih pozicija"),
            ("max_loss_day", "Dnevni gubitak, onda stop (SOL)"), ("min_sol_reserve", "Uvijek ostaje u novčaniku (SOL)"))
    more = [(k, lab) for k, (lab, *_r) in settings.LIMITS.items()
            if k not in dict(main) and not (fokus and k in IDLE_LIMITS)]
    if not owner:
        items = "".join(f"<li>{esc(lab)}: <b>{esc(_g(cfg.get(k)) if cfg.get(k) is not None else '–')}</b></li>"
                        for k, lab in main)
        return f"<ul style='margin:0;padding-left:18px'>{items}</ul>"

    def field(k, lab):
        return f'<label>{esc(lab)} <input name={k} value="{esc(str(cfg.get(k, "")))}" inputmode=decimal></label>'
    hidden = "".join(f'<input type=hidden name={k} value="{esc(str(cfg.get(k, "")))}">' for k in IDLE_LIMITS
                     if fokus and cfg.get(k) is not None)
    extra = "".join(field(k, lab) for k, lab in more)
    extra += (f'<label>Najviše SOL po tokenu (tvoje kupnje) <input name=owner_token_cap '
              f'value="{_g(cfg.get("owner_token_cap", settings.DCA_TOKEN_CAP))}" inputmode=decimal></label>'
              f'<label class=ap-chk><input type=checkbox name=dca_cap_owner value=1{" checked" if cfg.get("dca_cap_owner") else ""}> '
              'drži strop po tokenu: kupnja koja bi ga prešla ne prolazi</label>'
              f'<label class=ap-chk><input type=checkbox name=use_pump value=1{" checked" if cfg.get("use_pump", True) else ""}> '
              'ako prva burza ne prođe, probaj preko rezervne (PumpPortal)</label>')
    return (f'<form method=post action=/pravi-trade/limits class=ap-lim style="display:block">'
            + "".join(field(k, lab) for k, lab in main) + hidden
            + f'<details class=apx-jmore><summary>Još limita</summary>{extra}</details>'
            '<p class=mut>Kad se dosegne dnevni gubitak, kupnje staju do ponoći; prodaje idu uvijek.</p>'
            '<button>Spremi limite</button></form>')


def _limiti(tcon, cfg, owner, now, fokus):
    ns = novac_state(tcon, cfg, now)
    c = ns["caps"]
    meta = (f'ulog {_g(c["max_sol_per_trade"])} SOL · {c["max_open"]} otvorenih · dnevni gubitak {_g(c["max_loss_day"])} SOL '
            f'· pod {_g(ns["floor"])} SOL')
    inner = ('<h3 class=ap-sub><span>Bot (automatski)</span></h3>'
             f'<p>Ulog <b>{_g(c["max_sol_per_trade"])} SOL</b> po kupnji · najviše <b>{c["max_open"]} otvorenih</b> pozicija · '
             f'najviše <b>{c["max_buys_day"]} kupnji</b> dnevno · dnevni gubitak <b>{_g(c["max_loss_day"])} SOL</b>, onda stop '
             f'do sutra · pod novčanika <b>{_g(ns["floor"])} SOL</b>: ispod toga bot ne kupuje.</p>'
             '<p class=mut>Ovi stropovi su zadani u programu; mijenjaju se na tvoj zahtjev, ne ovdje.</p>'
             f'<div id=limiti><h3 class=ap-sub><span>Tvoje kupnje i kopiranje</span></h3>{_limits_form(cfg, owner, fokus)}</div>')
    return pt._sec("Limiti", meta, inner, sid="limiti-b")


def exit_rules():
    """The midcap exits as they are in the code now: (target low, target high, break-even at, time stop hours or None)."""
    try:
        from veliki import intra, rule
        ci, cr = intra.cfg_of(), dict(rule.RULE)
        own = getattr(rule, "OWNER_EXIT", {})
        tps = sorted({float(ci["tp"]), float(cr["tp"])})
        return tps[0], tps[-1], float(own.get("be_at") or 0) * 100, own.get("time_h", cr.get("time_h"))
    except Exception:  # noqa: BLE001 - the owner's rule of 15.11. as text
        return 10.0, 15.0, 5.0, None


def exit_text():
    lo, hi, be, th = exit_rules()
    tp = f"+{_g(lo)} %" if lo == hi else f"+{_g(lo)} do {_g(hi)} %"
    return (f"cijeli profit na {tp}" + (f" · stop na ulaz od +{_g(be)} %" if be else "")
            + (f" · izlaz nakon {_g(th)} h" if th else " · bez vremenskog stopa"))


def _choice(action, field, cur, choices, sign):
    return "".join(f'<form method=post action={action} style="margin:0"><input type=hidden name={field} value={v}>'
                   f'<button{" class=ap-go" if v == cur else ""}>{sign}{v} %</button></form>' for v in choices)


def _izlazi(cfg, owner):
    lo, hi, be, th = exit_rules()
    tp = f"+{_g(lo)} %" if lo == hi else f"+{_g(lo)} do {_g(hi)} %"
    cur_tp = int(cfg.get("tp_default") or 15)
    cur_sl = int(cfg.get("sl_default") or settings.SL_DEFAULT)
    bot = (f'<h3 class=ap-sub><span>Bot (midcap)</span></h3><ul class=apx-jul><li><b>Cilj:</b> proda cijelu poziciju na {tp} '
           'dobiti.</li>'
           + (f'<li><b>Bez gubitka:</b> kad pozicija dođe na +{_g(be)} %, stop se diže na cijenu ulaza.</li>' if be else "")
           + '<li><b>Stop:</b> ispod dna raspona u kojem je kupio.</li>'
           + (f'<li><b>Vrijeme:</b> izlazi nakon {_g(th)} h.</li>' if th else
              '<li><b>Vrijeme:</b> nema vremenskog stopa; izlazi ranije samo na novu opasnost.</li>') + '</ul>')
    mine = (f'<h3 class=ap-sub id=cilj><span>Tvoje kupnje i kopiranje: cilj</span><span>sada +{cur_tp} %</span></h3>'
            + (f'<div class=ap-btns style="margin:0 0 10px">{_choice("/pravi-trade/tp", "tp", cur_tp, pt.TP_CHOICES, "+")}</div>'
               if owner else "")
            + f'<h3 class=ap-sub id=stop><span>Tvoje kupnje i kopiranje: stop</span><span>sada −{cur_sl} %</span></h3>'
            + (f'<div class=ap-btns style="margin:0 0 10px">{_choice("/pravi-trade/sl", "sl", cur_sl, settings.SL_CHOICES, "−")}</div>'
               if owner else "")
            + '<p class=mut>Vrijedi za nove kupnje bez upisanog cilja i stopa. Otvorene pozicije zadržavaju svoje; '
              'mijenjaju se na samoj poziciji.</p>')
    return pt._sec("Izlazi", exit_text(), bot + mine, sid="izlazi-b")


def _obavijesti(tcon, owner, parts):
    """What the tool tells the owner and what waits for his answer: Grok's daily summary, the tool's and the critic's
    suggestions, the hourly review of the follows."""
    rows = "".join(h for h in parts if h)
    n = len(re.findall(r"<details class=ap-sec", rows))
    meta = "poruke i prijedlozi alata" if rows else "nema novih poruka"
    inner = ('<p class=mut>Bot ne šalje poruke na mobitel. Ono što čeka tvoj dodir pojavi se na vrhu stranice; ovdje su '
             'poruke i prijedlozi alata.</p>' + (rows or '<p class=mut>Trenutno nema ničega.</p>'))
    return pt._sec("Obavijesti", meta, inner, sid="obavijesti", value=str(n) if n else None)


def _short(words, n=58):
    """The first clause of a flag's description as its plain name."""
    w = re.split(r"[:;(]| - ", str(words), 1)[0].strip()
    return w if len(w) <= n else w[:n].rsplit(" ", 1)[0] + "…"


def flags_block(tcon, owner, fokus):
    """"Pravila u testiranju": the plan's rules behind their flags, the ones that are on first, each with its sentence
    and the same form as before (POST /pravi-trade/flag). The owner's switches are in Prekidači; rules of strategies
    that do not run while the bot trades midcaps only are left out while they are off."""
    st = settings.flag_state(tcon)
    shown, hidden = [], 0
    for name, (_item, words) in settings.FLAGS.items():
        if name in settings.OWNER_SWITCHES or name in (settings.VELIKI, settings.INSAJDERI2, settings.MAKROINF):
            continue
        m = st[name]["mode"]
        if fokus and name in IDLE_FLAGS and m == "off":
            hidden += 1
            continue
        shown.append((m == "off", name, words, m))
    shown.sort(key=lambda x: x[0])
    rows = []
    for _off, name, words, m in shown:
        bits = [f'<p>{esc(words)}.</p>']
        if fokus and name in IDLE_FLAGS:
            bits.append('<p class=mut>Ne radi dok bot trguje samo midcapove.</p>')
        if owner:
            opts = "".join(f'<option value={mm}{" selected" if mm == m else ""}>{pt.FLAG_WORDS[mm]}</option>'
                           for mm in settings.FLAG_MODES)
            bits.append(f'<form method=post action=/pravi-trade/flag class=ap-btns style="margin:0 0 10px">'
                        f'<input type=hidden name=name value={esc(name)}><select name=mode>{opts}</select>'
                        f'<button>Spremi</button></form>')
        r = pt._srow(_short(words), None, pt.FLAG_WORDS[m].split(" ")[0], None, value_tone=pt.FLAG_TONE[m])
        rows.append(f'<details class="ap-it apx-jn" id=fl-{esc(name)} data-jn><summary>{r}</summary>'
                    f'<div class=in>{"".join(bits)}</div></details>')
    n_on = sum(1 for off, *_x in shown if not off)
    meta = f"{n_on} od {len(shown)} uključeno" if n_on else f"{len(shown)} pravila, sva isključena"
    intro = ('<p class=mut>Nova pravila se prvo samo mjere („sjena”), zatim rade na demo računu („paper”), a na pravi novac '
             'idu tek kad se dokažu. Tvoji prekidači su u sekciji <a href="#prekidaci">Prekidači</a>.</p>'
             + (f'<p class=mut>Skriveno {hidden} {_plural(hidden, "pravilo", "pravila", "pravila")} starih strategija koje ne '
                'rade dok bot trguje samo midcapove (sva su u starom prikazu stranice).</p>' if hidden else ""))
    return pt._sec("Pravila u testiranju", meta, intro + SEARCH + f'<div class=apx-jlist>{"".join(rows)}</div>'
                   '<p class="apx-mut apx-jnone" hidden>Nema pravila s tim riječima.</p>', sid="zastavice")


def postavke(tcon, con, cfg, owner, now, prefill="", setup=None, diag=None):
    """The four blocks of "Postavke". con: league.db; setup: the wallet's setup steps (owner); diag: [(name, html)] of
    the diagnostic cards the caller already built (ui/apterm keeps deciding which ones have something to show)."""
    fokus = fokus_on(tcon)
    diag = [(n, h) for n, h in (diag or []) if h and not (fokus and n in IDLE_CARDS)]
    notif_names = ("pregled", "preporuke", "openai-prijedlozi", "sazetak")
    notif = [h for n, h in diag if n in notif_names]
    rest = [h for n, h in diag if n not in notif_names]
    adv = [pt._safe("praćenja", pt._follows, con, owner, settings.raw(tcon), prefill, "Koga bot kopira"),
           pt._safe("zastavice", flags_block, tcon, owner, fokus),
           pt._safe("grok", pt._mcp_section, tcon, owner),
           pt._safe("wallet", pt._wallet_row, tcon, owner, setup or {}),
           pt._safe("pozivnice", pt._invites, tcon) if owner else "",
           pt._safety(),
           pt._sec("Test naloga na burzi", "proba bez novca", pt._safe("trigger", pt._trigger_card, tcon, owner), sid="trigger-b")
           if owner else ""] + rest
    adv = [h for h in adv if h]
    adv_inner = ("".join(adv) + '<p class=apx-mut style="margin-top:14px"><a href="/pravi-trade?stari=1">Stari prikaz '
                 'stranice</a> (sve postavke na starom mjestu)</p>')
    blocks = [pt._safe("limiti", _limiti, tcon, cfg, owner, now, fokus),
              pt._safe("izlazi", _izlazi, cfg, owner),
              pt._safe("obavijesti", _obavijesti, tcon, owner, notif),
              pt._sec(f"Napredno ({len(adv)})", "koga bot kopira, pravila u testiranju, Grok ključ, novčanik, dijagnostika",
                      adv_inner, sid="napredno")]
    return f'<div class="ap-grp apx-jpost">{"".join(b for b in blocks if b)}</div>'
