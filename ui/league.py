"""Natjecanje: Ivan, Panda and Jure each pick demo trades from the bot's suggestions; leaderboard by profit;
plus the box for feature ideas. Data in league.db (league/store.py), never in the bot's own paper.db.

Pages get the logged-in player (Basic auth user name, see run_ui.py); None means the shared UI_PASSWORD,
which can look but not trade.
"""
import re
import sqlite3
import time
from urllib.parse import quote

from league import store
from ui import confidence, data, leaguedash
from rugfilter import collapse
from ui.html import price as pricecell, ago, badge, esc, klasab, num, razinab, rugcell, scorecell, signed, table, tlink, ts, usd
from ui.paper import _live, _mc, market

SUGGEST_H = 48
SUGGEST_MAX = 80
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
STATUS = {"novo": "", "u izradi": "warn", "napravljeno": "good", "odbijeno": "bad"}


def _form(action, fields, button, extra=""):
    hidden = "".join(f'<input type=hidden name="{esc(k)}" value="{esc(v)}">' for k, v in fields.items())
    return (f'<form method=post action="{action}" style="display:inline-flex;gap:4px;margin:0">{hidden}{extra}'
            f'<button>{button}</button></form>')


def login_help():
    """Shown when the browser's login box is cancelled, and explains how to log in."""
    miss = store.missing_passwords()
    note = (f"<p class=neg>Lozinke još nisu postavljene za: {esc(', '.join(miss))}. Postavljaju se u postavkama "
            "servera na Renderu.</p>") if miss else ""
    return ("<h1>Prijava</h1><p>U prozor preglednika upiši <b>svoje ime</b> "
            f"({esc(', '.join(store.users()))}) kao korisničko ime i <b>svoju lozinku</b>.</p>{note}"
            "<p><a href=/prijava>Pokušaj ponovo</a> · <a href=/natjecanje>Natrag</a></p>")


def _who(user):
    if user:
        return (f'<p class=mut>Prijavljen si kao <b>{esc(user)}</b> · '
                f'<a href="/prijava?kao={quote(user)}">promijeni korisnika</a></p>')
    miss = store.missing_passwords()
    extra = (f" <span class=neg>(lozinke još nisu postavljene za {esc(', '.join(miss))})</span>") if miss else ""
    return (f'<div class=card>Gledaš sa zajedničkom lozinkom pa ne možeš trgovati ni slati prijedloge. '
            f'<a href=/prijava><button>Prijavi se svojim imenom</button></a>{extra}</div>')


def _copy_card(con, user):
    """Prominent way into copy trading (/copy-trading), at the top of Natjecanje for everyone."""
    try:
        from league import copy
        mine = [f for f in copy.follows(con) if f["user"] == user] if user else []
    except sqlite3.OperationalError:
        mine = []
    now = (f"Trenutno pratiš: <b>{len(mine)}</b> ({esc(', '.join(f['label'] or f['target'][:6] for f in mine[:4]))}"
           f"{'…' if len(mine) > 4 else ''}). ") if mine else ""
    return ('<div class=card style="border:2px solid var(--acc,#f97316);display:flex;gap:14px;align-items:center;'
            'flex-wrap:wrap;margin:10px 0"><div style="font-size:30px">🔁</div><div style="flex:1;min-width:220px">'
            '<b style="font-size:17px">Copy trading: prati KOL-ove i wallete</b><br>'
            '<span class=mut>Detaljna statistika svakog influencera i walleta. Klikni „Prati i ulazi na svaki njegov call” ili '
            f'„Copy trade-aj ovaj wallet” i alat trguje umjesto tebe na ovom demo računu. {now}</span></div>'
            '<a href="/copy-trading"><button style="font-size:15px;padding:8px 16px">Otvori copy trading →</button></a>'
            '</div>')


def _err(qs):
    if qs.get("err"):
        return (f'<div class=card style="border:2px solid var(--bad);background:var(--badbg)"><b class=neg>❌ Nije prošlo, '
                f'ništa nije spremljeno:</b> {esc(qs["err"])}</div>')
    if qs.get("ok"):
        return f'<div class=card style="border:2px solid var(--good);background:var(--goodbg)">✅ {esc(qs["ok"])}</div>'
    return ""


def db_error(e):
    """SQLite errors in plain Croatian: on 1.11. the server disk was full for three hours and every buy failed with
    the English 'database or disk is full', which the players did not notice."""
    msg = str(e)
    if isinstance(e, sqlite3.OperationalError):
        if "full" in msg or "I/O" in msg:
            return "disk servera je trenutno pun pa se trade nije mogao spremiti. Pokušaj ponovo za par minuta."
        if "locked" in msg:
            return "baza je bila zauzeta. Pokušaj ponovo."
        return f"greška baze ({msg}). Pokušaj ponovo."
    return msg


def log_action(user, path, result):
    """Every competition action in the server log, so 'I made a trade but it is not there' can be checked."""
    print(f"natjecanje: {user or 'gost'} {path.rsplit('/', 1)[-1]} -> {result}", flush=True)


# leaderboard, podium, chart, player cards: ui/leaguedash.py


_API = {"ts": 0, "body": ""}


def api():
    """/api/natjecanje: the live numbers of the Natjecanje page (refreshed every minute without a reload). Shared
    by every open tab for 20 s, so several viewers mean one DexScreener call, not one each."""
    if time.time() - _API["ts"] < 20 and _API["body"]:
        return _API["body"]
    con = store.connect()
    try:
        body = leaguedash.api(con, market({t["token"] for t in store.trades(con, status="open")}))
    finally:
        con.close()
    _API.update(ts=time.time(), body=body)
    return body


def _suggestions(qs):
    """The same tokens and ranking as the Pregled page's standout candidates (every module's verdicts combined into
    confidence), filtered by the search form."""
    from ui import overview
    try:
        hours = int(qs.get("h") or SUGGEST_H)
        min_conf = float(qs.get("min") or 0)
    except ValueError:
        hours, min_conf = SUGGEST_H, 0
    rows = overview.token_rows(since=time.time() - hours * 3600)
    q = (qs.get("q") or "").strip().lower()
    if q:
        rows = [r for r in rows if q in (r["symbol"] or "").lower() or q in r["token"].lower()]
    if min_conf:
        rows = [r for r in rows if (r["conf"] or 0) >= min_conf]
    if qs.get("klasa"):
        rows = [r for r in rows if r["klasa"] == qs["klasa"]]
    if not qs.get("odb") and not q:
        rows = [r for r in rows if not r["hard"]]
    return sorted(rows, key=overview._rank, reverse=True)[:SUGGEST_MAX]


def _filters(qs):
    from tiers.classify import KLASA_HR
    sel = lambda name, opts: f"<select name={name}>" + "".join(  # noqa: E731
        f'<option value="{esc(v)}"{" selected" if str(qs.get(name, "")) == str(v) else ""}>{esc(t)}</option>'
        for v, t in opts) + "</select>"
    return ('<form method=get class=flt><input name=q placeholder="traži ime ili adresu" size=26 '
            f'value="{esc(qs.get("q", ""))}">'
            + sel("h", [(24, "zadnja 24 h"), (48, "zadnjih 48 h"), (168, "zadnjih 7 dana")])
            + sel("min", [("", "svaki confidence"), (40, "confidence ≥ 40"), (60, "confidence ≥ 60"), (75, "confidence ≥ 75")])
            + sel("klasa", [("", "sve klase")] + list(KLASA_HR.items()))
            + f'<label><input type=checkbox name=odb value=1{" checked" if qs.get("odb") else ""}> i odbačeni i rugani</label>'
            + '<button>Filtriraj</button> <a href=/natjecanje>očisti</a></form>')


def page(qs, user):
    con = store.connect()
    try:
        mine = store.trades(con, user, "open") if user else []
        bot_dca = {d["token"]: d["reason"] for d in data.paper_dca() if not d["done"]}
        cands = _suggestions(qs) if user else []   # suggestions only for players: guests can't buy
        from ui import quickbuy
        strong = quickbuy.strong()
        mints = ({t["token"] for t in store.trades(con, status="open")} | {c["token"] for c in cands}
                 | {t["mint"] for t in strong})
        mk = market(mints)
        live = {t: v[:3] for t, v in mk.items()}
        mcaps = {t: v[3] for t, v in mk.items() if v[3]}
        b = [f"<h1>Natjecanje</h1><p class=lead>Svatko ima svoj demo račun od ${store.START_USD:,.0f} (bez pravog novca). "
             "Biraš tokene iz prijedloga alata, kupuješ i prodaješ po živoj cijeni s DexScreenera, uz 1% naknade i "
             "klizanje cijene kao u pravoj trgovini. Pobjeđuje tko ima najviše na računu.</p>", _who(user), _err(qs)]
        b.append(_copy_card(con, user))
        b.append('<p style="margin:6px 0 10px"><a href=/whatsapp style="display:inline-flex;align-items:center;gap:6px;'
                 'background:#25d366;color:#fff;border-radius:10px;padding:8px 14px;font-weight:600;text-decoration:none">'
                 '📲 Pošalji stanje u WhatsApp grupu</a></p>')
        if user:
            from ui import register
            b.append('<div class=ctl style="margin:8px 0"><a class=chip href="#predlozeni">⭐ Predloženi tokeni</a>'
                     '<a class=chip href="#moj">💼 Moj račun</a>'
                     '<a class=chip href="#kupi">🛒 Kupi token</a><a class=chip href="#dca">🔄 Automatski DCA</a><a class=chip href="#prijedlozi">💡 Prijedlozi alata</a>'
                     '<a class=chip href="#zatvoreni">📜 Moji zatvoreni</a>'
                     '<a class=chip href="/copy-trading">🔁 Copy trading: prati influencera ili wallet</a>'
                     + ('<a class=chip href="#pozovi" onclick="document.getElementById(\'pozovi\').open=true">'
                        '👥 Pozovi prijatelja</a>' if register.can_invite(user) else '') + '</div>')
            b.append(register.invite_box(user))
        b.append(quickbuy.block(strong + quickbuy.fresh(cands, mk), mk, user))
        b.append(leaguedash.dashboard(con, mk, user))
        if not user:
            return "Natjecanje", "".join(b)

        acc = store.account(con, user)
        unreal, rows = 0.0, []
        mpk = collapse.peaks(data.HYPE_DB, {t["token"] for t in mine})
        for t in mine:
            price, liq, _ = live.get(t["token"], (None, None, None))
            val = store.value(t, price, liq) if price else None
            pnl = val - t["size_usd"] if val is not None else None
            unreal += pnl or 0
            sell_btn = _form("/natjecanje/sell", {"id": t["id"]}, "Prodaj") if price else \
                _form("/natjecanje/sell", {"id": t["id"], "rug": 1}, "Otpiši (nema cijene)")
            mc_now = t["entry_mcap"] * price / t["entry_px"] if price and t["entry_mcap"] and t["entry_px"] else None
            if mc_now and t["entry_mcap"]:
                collapse.add(mpk, t["token"], t["opened_ts"], t["entry_mcap"], None)
            col = collapse.check(mpk.get(t["token"]), mc_now, liq) if mc_now else None
            rug_hint = (" " + badge("💀 rugan", "bad") + f'<div class=neg style="font-size:12px">{esc(col["text"])}; '
                        'oporavak je rijedak, razmisli o prodaji.</div>') if col else ""
            dca_hint = rug_hint + ((" " + badge("bot: DCA prijedlog", "warn") + f'<div class=mut style="font-size:12px">'
                                    f'{esc(bot_dca[t["token"]])}</div>') if t["token"] in bot_dca else "")
            rows.append([tlink(t["token"], t["symbol"]) + dca_hint + _auto_cell(t), ago(t["opened_ts"]), usd(t["size_usd"]),
                         pricecell(t["entry_px"]), pricecell(price), usd(t["entry_mcap"]), usd(mc_now),
                         signed(price / t["entry_px"] - 1 if price else None, "{:+.0%}"),
                         (leaguedash.live_pnl(t["id"], pnl), pnl if pnl is not None else -1e18, "n"),
                         usd(liq), sell_btn])
        b.append(f'<h2 id=moj>Tvoj račun: {esc(user)}</h2><div class=grid>'
                 f'<div class=stat><div class=v>${acc["start"] + acc["realized"] + unreal:,.2f}</div><div class=l>stanje računa</div></div>'
                 f'<div class=stat><div class=v>${acc["cash"]:,.2f}</div><div class=l>slobodno za ulaganje</div></div>'
                 f'<div class=stat><div class="v {"pos" if acc["realized"] > 0 else "neg" if acc["realized"] < 0 else ""}">'
                 f'{acc["realized"]:+,.2f} $</div><div class=l>ostvareno (zatvoreni)</div></div>'
                 f'<div class=stat><div class="v {"pos" if unreal > 0 else "neg" if unreal < 0 else ""}">{unreal:+,.2f} $</div>'
                 f'<div class=l>otvoreno (live)</div></div></div>')
        b.append("<h3>Otvorene pozicije</h3>" + table(
            ["Token", "Kupljeno", ("Ulog", "n"), ("Ulazna cijena", "n"), ("Sada", "n"), ("MC ulaz", "n"),
             ("MC sada", "n"), ("Pomak", "n"),
             ("PnL $ (ako prodaš sad)", "n"), ("Likvidnost", "n"), ""], rows, empty="Nemaš otvorenih pozicija."))
        if mine:
            b.append(_auto_form(mine))

        size = f'<input name=size type=number min=1 step=1 value=50 style="width:70px" title="ulog u $">'
        b.append('<h2 id=kupi>Kupi bilo koji token</h2><form method=post action="/natjecanje/buy" class="card flt">'
                 '<input name=token placeholder="adresa tokena ili DexScreener link" size=50 required>'
                 f'{size}<button>Kupi</button><span class=mut>ne mora biti s liste prijedloga</span></form>')
        b.append(_dca_box(con, user, qs, live, mine))
        srows = []
        for r in cands:
            price, liq, _ = live.get(r["token"], (None, None, None))
            c = r["cand"] or {}
            move = price / c["price"] - 1 if price and c.get("price") else None
            col = collapse.check(r.get("peak"), mcaps.get(r["token"]), liq) if price else None
            r["collapse"] = col or r.get("collapse")
            if r["collapse"] and not (qs.get("odb") or qs.get("q")):
                continue  # dumped since it was suggested: off the list so nobody buys it
            act = ('<span class=neg title="Token se već srušio; kupnja je zaključana.">rugan, ne kupuj</span>'
                   if r["collapse"] else
                   _form("/natjecanje/buy", {"token": r["token"], "symbol": r["symbol"] or "", "score": r["conf"] or "",
                                             "source": f"confidence {r['conf']}"}, "Kupi", size) if price else
                   '<span class=mut>nema cijene</span>')
            srows.append([tlink(r["token"], r["symbol"]) + " " + quickbuy.copy_btn(r["token"], "📋", small=True),
                          (confidence.badge_html(r["conf"]), r["conf"], "n"),
                          (razinab(r["razina"]), r["razina"] or 0, "n"), (klasab(r["klasa"]), r["klasa"] or "", ""),
                          (f"<b>{r['passed']}</b>/{r['passed'] + r['failed']}", r["passed"], "n"), scorecell(r["hype_last"]),
                          rugcell(r),
                          badge("bot uzeo", "good") if c.get("trade_id") else (badge("bot preskočio") if c else "–"),
                          usd(r["mcap"]), signed(move, "{:+.0%}"), usd(liq), ago(r["last_seen"]), act])
        b.append(f"<h2 id=prijedlozi>Prijedlozi alata</h2><p class=mut>Isti tokeni i isti poredak kao „Istaknuti kandidati” na "
                 "<a href=/>Pregledu</a>: confidence spaja hype, X, smart money, KOL, holdere, rug filter i evente. "
                 "Tokeni koje je rug filter odbacio i tokeni koji su se u međuvremenu srušili (rug: 70%+ ispod vrha ili "
                 "izvučena likvidnost) su skriveni osim ako ih uključiš ili tražiš po imenu; njih se ne može kupiti. "
                 f"Prikazano {len(srows)} (najviše {SUGGEST_MAX}). Upiši ulog u $ i klikni Kupi.</p>" + _filters(qs))
        b.append(table(["Token", ("Confidence", "n"), ("Razina", "n"), "Klasa", ("Prošao", "n"), ("Hype", "n"), "Rug",
                        "Bot", ("Mcap viđen", "n"), ("Pomak", "n"), ("Likvidnost", "n"), "Zadnje", "Ulog $"], srows,
                       empty="Nijedan token ne odgovara filteru."))

        closed = store.trades(con, user, "closed")
        b.append("<h3 id=zatvoreni>Tvoji zatvoreni trejdovi</h3>" + table(
            ["Token", "Kupljeno", "Prodano", ("MC ulaz", "n"), ("MC izlaz", "n"), ("Ulog", "n"), ("PnL $", "n"),
             ("Povrat", "n"), "Napomena"],
            [[tlink(t["token"], t["symbol"]), ts(t["opened_ts"]), ts(t["closed_ts"]), usd(t["entry_mcap"]),
              usd(t["exit_mcap"]), usd(t["size_usd"]),
              signed(t["pnl_usd"]), signed(t["ret"], "{:+.0%}"), esc(t["note"] or "")] for t in closed],
            empty="Još ništa nisi prodao."))
        b.append("<p class=mut>Ideja kako poboljšati alat? Upiši je u <a href=/prijedlozi>Prijedloge</a>.</p>")
        return "Natjecanje", "".join(b)
    finally:
        con.close()


def ideas_page(qs, user):
    con = store.connect()
    try:
        b = ["<h1>Prijedlozi za nove mogućnosti</h1><p class=mut>Što bi alat trebao raditi bolje ili drugačije? "
             "Sve ideje se spremaju ovdje i svi ih vide.</p>", _who(user), _err(qs)]
        if user:
            b.append('<form method=post action="/prijedlozi/add" class=card><textarea name=text rows=4 required '
                     'style="width:100%;font:inherit;background:var(--card);color:var(--fg);border:1px solid var(--line);'
                     'border-radius:6px;padding:8px" placeholder="npr. upozori me kad token iz mojih pozicija padne 30%…">'
                     f'</textarea><p><button>Pošalji prijedlog</button> <span class=mut>kao {esc(user)}</span></p></form>')
        rows = []
        for i in store.ideas(con):
            sel = "".join(f'<option{" selected" if s == i["status"] else ""}>{s}</option>' for s in STATUS)
            change = _form("/prijedlozi/status", {"id": i["id"]}, "Spremi", f"<select name=status>{sel}</select>") \
                if user else ""
            rows.append([ts(i["ts"]), esc(i["user"]), (esc(i["text"]).replace("\n", "<br>"), "", "wrap"),
                         badge(i["status"], STATUS.get(i["status"], "")) + " " + change])
        b.append(table(["Kada", "Tko", ("Prijedlog", "wrap"), "Status"], rows, empty="Još nema prijedloga."))
        return "Prijedlozi", "".join(b)
    finally:
        con.close()


def _kupnji(n):
    """4 kupnje, 5 kupnji, 21 kupnja."""
    return f"{n} " + ("kupnja" if n % 10 == 1 and n % 100 != 11 else
                      "kupnje" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "kupnji")


def _in(ts_):
    """'za 12 min' / 'za 3 h' until a future unix time."""
    s = max(0, int(ts_ - time.time()))
    if s < 90:
        return "za manje od minute" if s < 60 else "za 1 min"
    if s < 5400:
        return f"za {s // 60} min"
    if s < 172800:
        return f"za {s / 3600:.0f} h"
    return f"za {s / 86400:.0f} dana"


def _dca_box(con, user, qs, live, mine):
    """Automatic DCA: start a plan (token, amount per buy, how often, how many), see and stop your plans."""
    from league import dca
    try:
        plans = dca.plans(con, user, active=None)
    except sqlite3.OperationalError:
        plans = []
    pos = {t["token"]: t for t in mine}
    every = "".join(f'<option value={k}{" selected" if k == 1440 else ""}>{v}</option>' for k, v in dca.EVERY.items())
    pre = esc(qs.get("dca") or "")
    b = ['<h2 id=dca>🔄 Automatski DCA</h2><p class=tdesc>DCA znači kupovati <b>isti iznos u pravilnim razmacima</b> '
         'umjesto sve odjednom: kad cijena padne kupiš jeftinije, kad naraste manje te boli što nisi sve uložio. '
         'Odaberi token, koliko po kupnji, koliko često i koliko puta, a alat kupuje sam s tvog demo računa (i preko '
         'noći). Sve kupnje idu u <b>jednu poziciju</b> tog tokena čija je ulazna cijena prosjek svih kupnji; prodaješ je '
         'kao i svaku drugu (ili joj uključiš auto sell). DCA staje sam kad obavi sve kupnje, kad ti ponestane novca ili '
         'ako se token sruši.</p>',
         '<form method=post action="/natjecanje/dca/start" class="card flt" id=dcaf>'
         f'<input name=token placeholder="adresa tokena ili DexScreener link" size=44 required value="{pre}">'
         '<label>$ po kupnji <input name=amount type=number min=5 max=500 step=1 value=20 style="width:70px"></label>'
         f'<select name=every>{every}</select>'
         '<label>broj kupnji <input name=n type=number min=2 max=100 step=1 value=10 style="width:60px"></label>'
         '<button>▶ Pokreni DCA</button><span class=mut id=dcat></span></form>'
         '<script>(function(){var f=document.getElementById("dcaf");if(!f)return;function u(){var a=+f.amount.value||0,'
         'n=+f.n.value||0;document.getElementById("dcat").textContent="ukupno najviše $"+(a*n).toLocaleString("hr")+'
         '", prva kupnja odmah"}f.addEventListener("input",u);u()})()</script>']
    rows = []
    for p in plans:
        t = pos.get(p["token"])
        price, liq, _ = live.get(p["token"], (None, None, None))
        val = store.value(t, price, liq) if t and price else None
        pnl = val - t["size_usd"] if val is not None else None
        mc_now = t["entry_mcap"] * price / t["entry_px"] if t and price and t["entry_mcap"] and t["entry_px"] else None
        if p["active"]:
            status = badge("aktivan", "good") + f' <span class=mut>sljedeća {_in(p["next_ts"])}</span>'
            act = _form("/natjecanje/dca/stop", {"id": p["id"]}, "⏹ Zaustavi")
        else:
            status = badge("završen" if (p["why"] or "").startswith("gotovo") else "zaustavljen") + \
                f'<div class=mut style="font-size:12px">{esc(p["why"] or "")}</div>'
            act = ""
        rows.append([tlink(p["token"], p["symbol"]), esc(dca.describe(p)), usd(p["spent"]),
                     usd(t["entry_mcap"] if t else None), usd(mc_now), signed(pnl),
                     status, (esc(p["last_note"] or "čeka prvu kupnju"), "", "wrap"), act])
    if plans:
        b.append(table(["Token", "Plan", ("Uloženo", "n"), ("Prosječni MC ulaza", "n"), ("MC sada", "n"),
                        ("PnL pozicije $", "n"), "Stanje", ("Zadnje", "wrap"), ""], rows))
    else:
        b.append('<p class=mut>Još nemaš DCA planova.</p>')
    return "".join(b)


def _auto_cell(t):
    from league import auto
    d = auto.describe(t.get("auto"))
    part = f" · već prodano za ${t['realized']:,.2f}" if t.get("realized") else ""
    return f'<div class=mut style="font-size:12px">{esc(d + part)}</div>' if d or part else ""


def _auto_form(mine):
    """Auto sell: smart exit (learned rules) or your own TP/SL in percent or market cap."""
    opts = "".join(f'<option value={t["id"]}>{esc(t["symbol"] or t["token"][:6])} (MC ulaz {_mc(t["entry_mcap"])})</option>'
                   for t in mine)
    return ('<h3>Auto sell</h3><p class=tdesc>Alat prodaje umjesto tebe (provjera svake minute, i preko noći). '
            '<b>Pametni izlaz</b> koristi pravila naučena iz povijesti za klasu tokena (djelomične prodaje, trailing, moonbag, '
            'pauza nakon calla influencera; vidi <a href=/izlazi>Izlazi</a>). <b>Moj TP/SL</b>: upiši postotak '
            '(<code>100%</code>, <code>-30%</code>; SL <code>30</code> znači -30%) ili market cap (<code>$500k</code>, '
            '<code>1.2M</code>), alat sam preračuna cijenu. Djelomične prodaje se vide uz poziciju, a novac se vraća na račun '
            'kad se pozicija zatvori.</p>'
            '<form method=post action="/natjecanje/auto" class="card flt">'
            f'<select name=id>{opts}</select><select name=mode><option value=smart>pametni izlaz</option>'
            '<option value=tpsl>moj TP/SL</option><option value=off>isključi auto sell</option></select>'
            '<input name=tp placeholder="TP: 100% ili $500k" size=16><input name=sl placeholder="SL: -30% ili $40k" size=16>'
            '<button>Postavi</button></form>')


def post(path, form, user):
    """Handle a form; returns where to send the browser next. Successful actions are logged too."""
    loc = _post(path, form, user)
    if "ok=" in loc:
        from urllib.parse import unquote
        log_action(user, path, unquote(loc.split("ok=", 1)[1].split("#", 1)[0]))
    return loc


def _post(path, form, user):
    back = "/prijedlozi" if path.startswith("/prijedlozi") else "/natjecanje"
    tb = form.get("back") or ""
    if path == "/natjecanje/buy" and tb.startswith("/token/") and MINT.fullmatch(tb[len("/token/"):]):
        back = tb   # bought from the token page: stay there
    _API["ts"] = 0   # a trade changes the live numbers
    if not user:
        return f"{back}?err={quote('prijavi se svojim imenom')}"
    if path.startswith("/natjecanje/pozivnica/"):
        from ui import register
        try:
            return register.post_invite(path, form, user)
        except sqlite3.OperationalError as e:
            return f"{back}?err={quote(db_error(e))}"
    con = store.connect()
    try:
        if path == "/natjecanje/buy":
            token = form.get("token", "").strip()
            if not MINT.fullmatch(token):   # pasted DexScreener link (token or pair) or text around the address
                from ui import real
                token = real.resolve(token)[0]
            live = market({token}) if token else {}
            if token not in live:
                raise ValueError("DexScreener ne zna cijenu tog tokena")
            price, liq, _, mcap = live[token]
            col = collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
            if col:
                raise ValueError(f"token je rugan ({col['text']}), kupnja je zaključana")
            symbol = form.get("symbol") or _symbol(token)
            size = float(form.get("size") or 0)
            store.buy(con, user, token, symbol, size, price, liq, form.get("source", "ručno"),
                      float(form["score"]) if form.get("score") else None, mcap)
            return f"{back}?ok={quote(f'Kupljeno {symbol or token[:6]} za ${size:,.0f} na MC {_mc(mcap)}')}"
        if path == "/natjecanje/sell":
            tid = int(form.get("id") or 0)
            t = next((t for t in store.trades(con, user, "open") if t["id"] == tid), None)
            if not t:
                raise ValueError("nema te otvorene pozicije")
            if form.get("rug"):
                pnl = store.sell(con, user, tid, 0, 0, "otpisano: nema cijene")
            else:
                live = market({t["token"]})
                if t["token"] not in live:
                    raise ValueError("DexScreener trenutno ne daje cijenu, probaj ponovo")
                price, liq, _, mcap = live[t["token"]]
                pnl = store.sell(con, user, tid, price, liq, mcap=mcap)
            msg = f"Prodano {t['symbol'] or t['token'][:6]}: {pnl:+.2f} $"
            return f"{back}?ok={quote(msg)}"
        if path == "/natjecanje/dca/start":
            from league import dca
            token = form.get("token", "").strip()
            if not MINT.fullmatch(token):
                from ui import real
                token = real.resolve(token)[0]
            live = market({token}) if token else {}
            if token not in live:
                raise ValueError("DexScreener ne zna cijenu tog tokena")
            price, liq, _, mcap = live[token]
            col = collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
            if col:
                raise ValueError(f"token je rugan ({col['text']}), DCA nije pokrenut")
            if (liq or 0) < dca.CFG["min_liq"]:
                raise ValueError(f"premala likvidnost (${liq or 0:,.0f}); za DCA treba barem ${dca.CFG['min_liq']:,}")
            symbol = _symbol(token)
            amount, n, every = float(form.get("amount") or 0), int(form.get("n") or 0), int(form.get("every") or 0)
            dca.start(con, user, token, symbol, amount, every, n)
            msg = (f"DCA pokrenut: {symbol or token[:6]}, ${amount:,.0f} {dca.EVERY[every]}, {_kupnji(n)} "
                   f"(ukupno najviše ${amount * n:,.0f}). Prva kupnja unutar minute.")
            return f"{back}?ok={quote(msg)}#dca"
        if path == "/natjecanje/dca/stop":
            from league import dca
            dca.stop(con, user, int(form.get("id") or 0))
            return f"{back}?ok={quote('DCA zaustavljen. Već kupljeno ostaje u tvojoj poziciji.')}#dca"
        if path == "/natjecanje/auto":
            from league import auto
            a = auto.set_auto(con, user, int(form.get("id") or 0), form.get("mode", ""), form.get("tp", ""),
                              form.get("sl", ""))
            return f"{back}?ok={quote(auto.describe(a) or 'Auto sell isključen')}"
        if path == "/prijedlozi/add":
            store.add_idea(con, user, form.get("text"))
            return f"{back}?ok={quote('Hvala, prijedlog je spremljen.')}"
        if path == "/prijedlozi/status":
            if form.get("status") in STATUS:
                store.set_idea_status(con, int(form.get("id") or 0), form["status"])
            return back
        return back
    except (ValueError, KeyError, sqlite3.OperationalError) as e:
        log_action(user, path, f"NIJE PROŠLO: {e}")
        return f"{back}?err={quote(db_error(e))}"
    finally:
        con.close()


def _symbol(token):
    try:
        from dexscreener import client
        for p in client.tokens("solana", [token]):
            if p["baseToken"]["address"] == token:
                return p["baseToken"].get("symbol")
    except Exception:
        pass
    return None
