"""BNB Chain in the app: /bnb (24.11., vlasnik: "Pa zašto misliš da skrepamo te sve tokene i BNB chain da ih jednostavno
ne bi prikazali? Želim to sve prikazano u frontendu, raspoređeno po tabovima, da bude jasno što je što.").

The page reads bnb.db only through bnb/pogled.py (read-only, never raises, "nothing yet" when the database or the job
is not there) and shows four sections; their <h2> headings become the chips under the title (ui/secnav), so every
section is one tap away: Sažetak · Pumpe · Novčanici prije pumpe · Mjerenje praćenja. BNB is analysis only (bnb/):
nothing here trades. 24.11. (Jure: "Želim da običan korisnik vidi zaradu u novčaniku"): the amounts and the realized
result are shown to every user, next to the neutral facts (which token, how long before the jump).

Neutral wording: a wallet on the list bought before and sold into pumps more often than the rules let pass; nothing
says who it is or why.
"""
import time
from urllib.parse import quote

from ui import redak as rd
from ui.html import esc, lead, table, ts as fts


def _t(ts, fmt="%d.%m. %H:%M"):
    """A plain time string (ui.html.ts returns a table cell)."""
    return time.strftime(fmt, time.gmtime(int(ts))) if ts else rd.DASH

TITLE = "BNB Chain: pumpe i novčanici"
TIER = {"pumpa15": "15 M $ i više", "pumpa2": "2–15 M $"}
CLS = {"prije_pumpe": "kupuje prije pumpe", "kandidat": "kandidat (dvije pumpe)"}
SRC = {"bnb_prije_pumpe": "novčanici prije pumpe", "bnb_kandidat": "kandidati"}
EXIT = {"tp": "cilj", "sl": "stop", "time": "vrijeme", "miss": "promašeno"}
GROUPS_N = 60
PUMPS_N = 80
MJERA_N = 40

CSS = """<style>
.bnb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:8px 0 14px}
.bnb-grid .st{border:1px solid var(--line);border-radius:12px;background:var(--card);padding:10px 12px}
.bnb-grid .v{font-size:20px;font-weight:700;letter-spacing:-.01em}.bnb-grid .l{font-size:12.5px;color:var(--mut);line-height:1.3}
.bnb-w{border:1px solid var(--line);border-radius:12px;background:var(--card);margin:8px 0;padding:0 12px}
.bnb-w summary{cursor:pointer;padding:10px 0;font-size:14px;line-height:1.45;display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center}
.bnb-w code{font-size:13px;background:var(--soft);border-radius:6px;padding:2px 6px}
.bnb-w .in{padding:4px 0 12px;font-size:13.5px;line-height:1.5}
.bnb-w ul{margin:6px 0 8px 18px;padding:0}.bnb-w li{margin:3px 0}
.bnb-tag{font-size:12px;border-radius:999px;padding:2px 8px;background:var(--soft);color:var(--mut)}
.bnb-tag.ok{background:#e6f6ec;color:#166534}.bnb-tag.warn{background:#fff4e5;color:#9a3412}
.bnb-note{font-size:12.5px;color:var(--mut);margin:6px 0 14px;line-height:1.45}
</style>"""


def _short(w):
    w = str(w or "")
    return w if len(w) <= 14 else f"{w[:6]}…{w[-4:]}"


def _tok(t, sym):
    t = str(t or "")
    name = esc(sym or _short(t))
    return f'<a href="https://dexscreener.com/bsc/{quote(t)}" target=_blank rel="noopener noreferrer" translate=no>{name}</a>' if t else name


def _addr(w):
    w = str(w or "")
    return (f'<code translate=no title="{esc(w)}">{esc(_short(w))}</code> '
            f'<a href="https://bscscan.com/address/{quote(w)}" target=_blank rel="noopener noreferrer">BscScan ↗</a>')


def _stat(v, l):
    return f'<div class=st><div class=v>{v}</div><div class=l>{esc(l)}</div></div>'


def _lead_txt(m):
    if m is None:
        return rd.DASH
    try:
        m = float(m)
    except (TypeError, ValueError):
        return rd.DASH
    return f"{rd.num(m)} min prije skoka" if m >= 0 else f"{rd.num(-m)} min nakon skoka"


def _empty(why):
    return (CSS + f"<h1>{esc(TITLE)}</h1>" + lead(why)
            + "<p class=bnb-note>Posao „bnb” čita BNB Smart Chain svaka 3 sata (GeckoTerminal, DexScreener, javni RPC, sve "
              "besplatno), traži pumpe od 2 M $ naviše i novčanike koji kupe prije njih i prodaju u rast. Kad napravi prvi "
              "prolaz, ovdje su četiri odjeljka: sažetak, pumpe, novčanici i mjerenje praćenja.</p>")


def summary_html(s, f, now):
    pumps15 = f.get("pumpe15_1d")
    pumps2 = f.get("pumpe2_1d")
    last = s.get("updated")
    calls = s.get("calls") or {}
    free = calls.get("free") or {}
    grid = "".join([
        _stat(rd.num(s.get("tokens")), "meme tokena u krugu"),
        _stat(rd.num(s.get("pumps")), "pumpi pronađeno"),
        _stat(f'{rd.num(pumps15)} / {rd.num(pumps2)}' if f else rd.DASH, "pumpi u 1 danu: 15 M $+ / 2–15 M $"),
        _stat(rd.num(s.get("read")), "pumpi pročitano do dna"),
        _stat(rd.num(s.get("groups")), "novčanika „kupuje prije pumpe”"),
        _stat(rd.num(s.get("confirmed")), "potvrđeno na novijim podacima"),
        _stat(rd.num(s.get("trades")), "swapova spremljeno"),
        _stat(rd.ago(last, now) if last else rd.DASH, f"zadnji prolaz{(' (' + esc(str(s.get('last_pass')) ) + ')') if s.get('last_pass') else ''}"),
    ])
    bits = []
    if f:
        bits.append(f"Rani kupci na pročitanim pumpama: {rd.num(f.get('rani'))}, od njih prodali u pumpu "
                    f"{rd.num(f.get('rani_prodali'))}; blizu praga (dvije pumpe) {rd.num(f.get('blizu_praga'))}; "
                    f"izvan besplatne povijesti {rd.num(f.get('izvan_dosega'))} pumpi.")
    if calls.get("rpc"):
        bits.append(f"Lanac se čita s {esc(str(calls['rpc']))}"
                    + (" (besplatni pozivi po izvoru: " + ", ".join(f"{esc(k)} {rd.num(v)}" for k, v in free.items()) + ")"
                       if free else "") + ".")
    if not s.get("confirmed"):
        bits.append("Nijedan novčanik još nije potvrđen na novijim podacima: popis dolje je sirov, čita se kao statistika, "
                    "ne kao preporuka.")
    return ('<h2 id=sazetak>Sažetak</h2>' + lead("Što je posao do sada našao na BNB Smart Chainu, sve iz besplatnih izvora.")
            + f'<div class=bnb-grid>{grid}</div>' + (f'<p class=bnb-note>{" ".join(bits)}</p>' if bits else ""))


def pumps_html(ps):
    rows = []
    for p in ps:
        px = p.get("peak_x")
        rows.append([
            _tok(p.get("token"), p.get("symbol")),
            (esc(TIER.get(p.get("tier"), rd.DASH)), 15 if p.get("tier") == "pumpa15" else 2),
            fts(p["t0"]) if p.get("t0") else rd.DASH,
            (esc(f"{rd.num(px, 1)}×") if px else rd.DASH, px or 0, "n"),
            (esc(rd.usd(p.get("mcap0"))), p.get("mcap0") or 0, "n"),
            (esc(rd.usd(p.get("peak_mc"))), p.get("peak_mc") or 0, "n"),
            (esc(rd.num(p.get("n_part"))) if p.get("n_part") is not None else rd.DASH, p.get("n_part") or 0, "n"),
            ("pročitano" if p.get("fetched") else "čeka", 1 if p.get("fetched") else 0),
        ])
    return ('<h2 id=pumpe>Pumpe</h2>' + lead("Tokeni koji su skočili, najnoviji prvi; vrh = koliko puta od početka skoka. "
                                             "„Pročitano” znači da su kupnje prije skoka pročitane s lanca.")
            + table([("Token", ""), ("Razina", ""), ("Skok", ""), ("Vrh", "n"), ("Mcap na početku", "n"), ("Mcap na vrhu", "n"),
                     ("Sudionika", "n"), ("Lanac", "")], rows, tid="bnbpumpe",
                    empty="Još nijedna pumpa nije pronađena.", limit=PUMPS_N))


def _pump_li(p):
    t = esc(_t(p.get("t0")))
    usd_in, usd_out = p.get("usd_in"), p.get("usd_out")
    money = ""
    if usd_in is not None or usd_out is not None:
        money = f' · uloženo {esc(rd.usd(usd_in))}, izašlo {esc(rd.usd(usd_out))}'
    return (f'<li>{_tok(p.get("token"), p.get("symbol"))} · {esc(TIER.get(p.get("tier"), rd.DASH))} · {t} · '
            f'{esc(_lead_txt(p.get("lead_min")))}{money}</li>')


def _group_html(g, now):
    conf = g.get("confirmed")
    tag = ('<span class="bnb-tag ok">potvrđeno</span>' if conf else
           '<span class="bnb-tag warn">kandidat</span>' if g.get("cls") == "kandidat" else
           '<span class=bnb-tag>čeka potvrdu</span>')
    n15, n2, nt = g.get("n_pumps15") or 0, g.get("n_pumps2") or 0, g.get("n_tokens") or 0
    head = (f'{_addr(g.get("address"))} {tag} <span>{rd.num(n15 + n2)} {_skok(n15 + n2)}'
            f'{f" ({rd.num(n15)} od 15 M $)" if n15 else ""} · {rd.num(nt)} {_tokena(nt)} · '
            f'kupuje {esc(_lead_txt(g.get("med_lead_min")))} · zadnji put {esc(rd.ago(g.get("last_seen"), now))}</span>')
    pumps = g.get("pumps") or []
    inner = (f'<p>{esc(g.get("why") or "")}</p>' if g.get("why") else "")
    if g.get("pnl_usd") is not None:
        inner += f'<p>Ostvareno na tim skokovima: <b class="{rd.tone(g["pnl_usd"])}">{esc(rd.usd(g["pnl_usd"], sign=True))}</b></p>'
    inner += (f'<p><b>Skokovi</b> ({rd.num(len(pumps))})</p><ul>' + "".join(_pump_li(p) for p in pumps[:30]) + '</ul>'
              + (f'<p class=bnb-note>Prikazano 30 od {rd.num(len(pumps))}.</p>' if len(pumps) > 30 else "")
              if pumps else '<p class=bnb-note>Pojedinačni skokovi još nisu spremljeni za ovaj novčanik.</p>')
    return f'<details class=bnb-w><summary>{head}</summary><div class=in>{inner}</div></details>'


def _skok(n):
    n = int(n or 0)
    if n % 10 == 1 and n % 100 != 11:
        return "skok"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "skoka"
    return "skokova"


def _tokena(n):
    n = int(n or 0)
    return "token" if n % 10 == 1 and n % 100 != 11 else "tokena"


def groups_html(gs, now):
    gs = sorted(gs, key=lambda g: ((0 if g.get("confirmed") else 1), -(g.get("last_seen") or 0), -(g.get("n_tokens") or 0)))
    body = "".join(_group_html(g, now) for g in gs[:GROUPS_N]) if gs else \
        '<p class=bnb-note>Još nijedan novčanik ne prolazi pravilo (barem 3 tokena kupljena prije skoka i prodana u rast). ' \
        'Kandidati s dvije pumpe pojavljuju se čim budu spremljeni.</p>'
    return ('<h2 id=novcanici>Novčanici prije pumpe</h2>'
            + lead("Novčanici koji su kupili prije skoka i prodali u rast, potvrđeni prvi, zatim po zadnjoj aktivnosti; dodir "
                   "na redak otvara svaki skok.") + body
            + (f'<p class=bnb-note>Prikazano {GROUPS_N} od {rd.num(len(gs))}.</p>' if len(gs) > GROUPS_N else "")
            + '<p class=bnb-note>Statistika iz javnih podataka s lanca, nije financijski savjet; prošli rezultat ne jamči budući.</p>')


def mjera_html(m, now):
    by = m.get("by_source") or {}
    if not any((s or {}).get("signals") for s in by.values()):   # the sources exist with zeros before the first signal
        by = {}
    rows = []
    for src, s in by.items():
        rows.append([esc(SRC.get(src, src)), (rd.num(s.get("signals")), s.get("signals") or 0, "n"),
                     (rd.num(s.get("measured")), s.get("measured") or 0, "n"), (rd.num(s.get("open")), s.get("open") or 0, "n"),
                     (rd.num(s.get("misses")), s.get("misses") or 0, "n"),
                     (esc(rd.pct(s.get("win_pct"), sign=False)) if s.get("win_pct") is not None else rd.DASH, s.get("win_pct") or 0, "n"),
                     (esc(rd.pct(s.get("mean_net_50_pct"), 1)) if s.get("mean_net_50_pct") is not None else rd.DASH, s.get("mean_net_50_pct") or 0, "n"),
                     (esc(rd.pct(s.get("mean_net_250_pct"), 1)) if s.get("mean_net_250_pct") is not None else rd.DASH, s.get("mean_net_250_pct") or 0, "n"),
                     (f"{rd.num(s['median_delay_s'])} s" if s.get("median_delay_s") is not None else rd.DASH, s.get("median_delay_s") or 0, "n")])
    srows = []
    for r in (m.get("rows") or [])[:MJERA_N]:
        st = r.get("status") or ""
        word = {"open": "otvoreno", "closed": f"zatvoreno ({EXIT.get(r.get('exit_reason'), r.get('exit_reason') or '')})",
                "miss": "promašeno"}.get(st, st)
        srows.append([_tok(r.get("token"), r.get("symbol")), esc(SRC.get(r.get("source"), r.get("source") or "")),
                      fts(r["seen_ts"]) if r.get("seen_ts") else rd.DASH,
                      (f"{rd.num(r['delay_s'])} s" if r.get("delay_s") is not None else rd.DASH, r.get("delay_s") or 0, "n"),
                      (esc(rd.usd(r.get("entry_mcap"))), r.get("entry_mcap") or 0, "n"), esc(word),
                      (esc(rd.pct(r["ret_net_50"], 1, frac=True)) if r.get("ret_net_50") is not None else rd.DASH, r.get("ret_net_50") or 0, "n"),
                      (esc(rd.pct(r["ret_net_250"], 1, frac=True)) if r.get("ret_net_250") is not None else rd.DASH, r.get("ret_net_250") or 0, "n")])
    return ('<h2 id=mjerenje>Mjerenje praćenja</h2>'
            + lead("Što bi donijelo kupiti kad novčanik s popisa kupi: ulaz nakon stvarnog kašnjenja, neto nakon troška od "
                   "0,5 % i 2,5 % po smjeru. Bez novca, samo mjerenje.")
            + table([("Izvor", ""), ("Signala", "n"), ("Izmjereno", "n"), ("Otvoreno", "n"), ("Promašeno", "n"), ("U plusu", "n"),
                     ("Neto 0,5 %", "n"), ("Neto 2,5 %", "n"), ("Kašnjenje", "n")], rows, tid="bnbmjera",
                    empty="Mjerenje još nije počelo: čeka prvi novčanik na popisu i njegovu novu kupnju.")
            + (table([("Token", ""), ("Izvor", ""), ("Viđeno", ""), ("Kašnjenje", "n"), ("Mcap na ulazu", "n"), ("Stanje", ""),
                      ("Neto 0,5 %", "n"), ("Neto 2,5 %", "n")], srows, tid="bnbmjerar", limit=MJERA_N) if srows else ""))


METHOD = ('<h2 id=metoda>Kako čitati</h2>'
          '<ul class=bnb-note style="margin-left:18px">'
          '<li>Pumpa: token koji je u jednom satu ili danu skočio toliko da mu vrh pređe 2 M $ (razina 2–15 M $) ili 15 M $ (razina 15 M $ i više).</li>'
          '<li>Novčanik „kupuje prije pumpe”: na barem tri takva tokena kupio je prije skoka i prodao u rast; „potvrđeno” znači da je isto napravio i na novijim podacima koje pravilo nije vidjelo kad je odabran.</li>'
          '<li>Mjerenje: svaka nova kupnja novčanika s popisa postaje zamišljeni ulaz s našim kašnjenjem i troškom; tek kad je to u plusu s intervalom iznad nule, ima smisla razgovarati o pravom novcu.</li>'
          '<li>Sve iz besplatnih izvora (GeckoTerminal, DexScreener, javni RPC); dnevni strop poziva drži trošak na nuli.</li></ul>')


def page(qs=None, now=None):
    now = now or int(time.time())
    from bnb import pogled, store
    if store.ro() is None:
        return TITLE, _empty("BNB baza još ne postoji: posao se još nije pokrenuo (ili je isključen s BNB_ON=0).")
    s = pogled.summary()
    f = pogled.funnel()
    ps = pogled.pumps(PUMPS_N)
    gs = pogled.groups("prije_pumpe", GROUPS_N) + pogled.groups("kandidat", GROUPS_N)
    m = pogled.measurement(MJERA_N)
    body = (CSS + f"<h1>{esc(TITLE)}</h1>"
            + lead("BNB Smart Chain: pumpe, novčanici koji kupuju prije njih i što bi donijelo pratiti ih. Analiza, bez trgovanja.")
            + summary_html(s, f, now) + pumps_html(ps) + groups_html(gs, now) + mjera_html(m, now) + METHOD)
    return TITLE, body
