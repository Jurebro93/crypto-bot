"""Natjecanje: Ivan, Panda and Jure each pick demo trades from the bot's suggestions; leaderboard by profit;
plus the box for feature ideas. Data in league.db (league/store.py), never in the bot's own paper.db.

Pages get the logged-in player (Basic auth user name, see run_ui.py); None means the shared UI_PASSWORD,
which can look but not trade.
"""
import re
import sqlite3
import time
from urllib.parse import quote

from league import namesake, store
from ui import confidence, data, leaguedash
from ui import topcheckui as topui
from rugfilter import collapse
from ui.html import ago, badge, esc, klasab, razinab, rugcell, scorecell, signed, table, tlink, ts, usd
from ui.paper import _mc, market

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
    return ('<div class=card style="border:1px solid #c7d2fe;background:linear-gradient(135deg,rgba(79,70,229,.06),rgba(15,181,160,.06)),#fff;display:flex;gap:14px;align-items:center;'
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
        head = [f"<h1>Natjecanje</h1><p class=lead>Svatko ima svoj demo račun od ${store.START_USD:,.0f} (bez pravog novca). "
                "Biraš tokene iz prijedloga alata, kupuješ i prodaješ po živoj cijeni s DexScreenera, uz 1% naknade i "
                "klizanje cijene kao u pravoj trgovini. Pobjeđuje tko ima najviše na računu.</p>", _who(user), _err(qs)]
        wa = ('<p style="margin:6px 0 10px"><a href=/whatsapp style="display:inline-flex;align-items:center;gap:6px;'
              'background:#25d366;color:#fff;border-radius:10px;padding:8px 14px;font-weight:600;text-decoration:none">'
              '📲 Pošalji stanje u WhatsApp grupu</a></p>')
        if not user:
            b = head + [_copy_card(con, user), wa, quickbuy.block(strong, mk, user, compact=True),
                        leaguedash.dashboard(con, mk, user)]
            return "Natjecanje", "".join(b)
        # Nicholas 1.11. 20:46: own positions and selling them first, then the account and buys/sells, then the rest
        from ui import register
        rest = "".join([quickbuy.top_buy(user), _copy_card(con, user), register.invite_box(user), wa])
        b = list(head)
        acc = store.account(con, user)
        pos_html, unreal = _positions(mine, live, bot_dca)
        b.append(f'<h2 id=pozicije>💼 Moje pozicije ({len(mine)})</h2>'
                 f'<p class=mut style="margin:2px 0 8px">Stanje računa <b>${acc["start"] + acc["realized"] + unreal:,.2f}</b>'
                 f' · slobodno <b>${acc["cash"]:,.2f}</b> · otvoreno <b class={"pos" if unreal > 0 else "neg" if unreal < 0 else ""}>'
                 f'{unreal:+,.2f} $</b></p>' + _autobuy_banner(con, user) + pos_html)
        from league import auto as autosell
        b.append(_auto_form(mine, autosell.get_rule(con, user)))
        b.append(_dca_box(con, user, qs, live, mine))
        b.append(f'<h2 id=moj>Tvoj račun: {esc(user)}</h2><div class=grid>'
                 f'<div class=stat><div class=v>${acc["start"] + acc["realized"] + unreal:,.2f}</div><div class=l>stanje računa</div></div>'
                 f'<div class=stat><div class=v>${acc["cash"]:,.2f}</div><div class=l>slobodno za ulaganje</div></div>'
                 f'<div class=stat><div class="v {"pos" if acc["realized"] > 0 else "neg" if acc["realized"] < 0 else ""}">'
                 f'{acc["realized"]:+,.2f} $</div><div class=l>ostvareno (zatvoreni)</div></div>'
                 f'<div class=stat><div class="v {"pos" if unreal > 0 else "neg" if unreal < 0 else ""}">{unreal:+,.2f} $</div>'
                 f'<div class=l>otvoreno (live)</div></div></div>')
        closed = store.trades(con, user, "closed")
        b.append("<h3 id=zatvoreni>Moje kupnje i prodaje (zatvoreno)</h3>" + table(
            ["Token", "Kupljeno", "Prodano", ("MC ulaz", "n"), ("MC izlaz", "n"), ("Ulog", "n"), ("PnL $", "n"),
             ("Povrat", "n"), "Napomena"],
            [[tlink(t["token"], t["symbol"]), ts(t["opened_ts"]), ts(t["closed_ts"]), usd(t["entry_mcap"]),
              usd(t["exit_mcap"]), usd(t["size_usd"]),
              signed(t["pnl_usd"]), signed(t["ret"], "{:+.0%}"), esc(t["note"] or "")] for t in closed],
            empty="Još ništa nisi prodao."))
        b.append(rest)
        b.append(quickbuy.block(strong + quickbuy.fresh(cands, mk), mk, user, compact=True))
        b.append(leaguedash.dashboard(con, mk, user))

        size = '<input name=size type=number min=1 step=1 value=50 style="width:70px" title="ulog u $">'
        srows = []
        for r in cands:
            price, liq, _ = live.get(r["token"], (None, None, None))
            c = r["cand"] or {}
            move = price / c["price"] - 1 if price and c.get("price") else None
            col = collapse.check(r.get("peak"), mcaps.get(r["token"]), liq) if price else None
            r["collapse"] = col or r.get("collapse")
            if r["collapse"] and not (qs.get("odb") or qs.get("q")):
                continue  # dumped since it was suggested: off the list so nobody buys it
            top = r.get("top")
            failed = bool(top and top.get("verdict") == "pao")
            act = ('<span class=neg title="Token se već srušio; kupnja je zaključana.">rugan, ne kupuj</span>'
                   if r["collapse"] else
                   '<span class=neg title="Pao na obaveznom rug checku; kupnja iz prijedloga je zaključana.">pao na rug checku</span>'
                   if failed else
                   _form("/natjecanje/buy", {"token": r["token"], "symbol": r["symbol"] or "", "score": r["conf"] or "",
                                             "source": f"confidence {r['conf']}"}, "Kupi", size) if price else
                   '<span class=mut>nema cijene</span>')
            srows.append([tlink(r["token"], r["symbol"]) + " " + quickbuy.copy_btn(r["token"], "📋", small=True)
                          + topui.badges(top), topui.advice_cell(top),
                          (confidence.badge_html(r["conf"]), r["conf"], "n"),
                          (razinab(r["razina"]), r["razina"] or 0, "n"), (klasab(r["klasa"]), r["klasa"] or "", ""),
                          (f"<b>{r['passed']}</b>/{r['passed'] + r['failed']}", r["passed"], "n"), scorecell(r["hype_last"]),
                          rugcell(r) if r["collapse"] or not top else (topui.rug_badge(top), top.get("verdict") or "", ""),
                          badge("bot uzeo", "good") if c.get("trade_id") else (badge("bot preskočio") if c else "–"),
                          usd(r["mcap"]), signed(move, "{:+.0%}"), usd(liq), ago(r["last_seen"]), act])
        b.append(f"<h2 id=prijedlozi>Prijedlozi alata</h2><p class=mut>Isti tokeni i isti poredak kao „Istaknuti kandidati” na "
                 "<a href=/>Pregledu</a>: confidence spaja hype, X, smart money, KOL, holdere, rug filter i evente. "
                 "Tokeni koje je rug filter odbacio i tokeni koji su se u međuvremenu srušili (rug: 70%+ ispod vrha ili "
                 "izvučena likvidnost) su skriveni osim ako ih uključiš ili tražiš po imenu; njih se ne može kupiti. "
                 f"Prikazano {len(srows)} (najviše {SUGGEST_MAX}). Upiši ulog u $ i klikni Kupi.</p>"
                 "<p class=mut>Prvih 20 prijedloga alat provjerava <b>svake 3 minute</b>: nova analiza u svakom skenu, "
                 "<b>stanje tržišta</b> (🚀 pumpa: ne kupuj, pričekaj · ↗ pad uz oporavak · 📉 pada · ➖ stabilno) i "
                 "<b>obavezan rug check</b> (mint i freeze authority, LP, top holderi, dev, honeypot test prodaje, pun rug "
                 "filter). Token koji padne na rug checku se skriva i ne nudi za kupnju.</p>" + _filters(qs))
        b.append(table(["Token", ("Savjet", "wrap"), ("Confidence", "n"), ("Razina", "n"), "Klasa", ("Prošao", "n"), ("Hype", "n"), "Rug check",
                        "Bot", ("Mcap viđen", "n"), ("Pomak", "n"), ("Likvidnost", "n"), "Zadnje", "Ulog $"], srows,
                       empty="Nijedan token ne odgovara filteru."))

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
         f'<input name=token placeholder="adresa tokena ili DexScreener link" size=44 style="max-width:100%;min-width:0" required value="{pre}">'
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


POS_CSS = (".pos-bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:4px 0 8px}"
           ".pos-bar button{padding:6px 12px;border-radius:999px;font-size:14px}.pos-bar button.on{background:var(--fg,#0b1220);"
           "color:#fff;border-color:var(--fg,#0b1220)}"
           ".pos-list{display:grid;grid-template-columns:1fr;gap:6px;margin:6px 0 12px}"
           ".pos-list.tiles{grid-template-columns:repeat(auto-fill,minmax(min(100%,290px),1fr));gap:8px}"
           ".pos-c{box-sizing:border-box;max-width:100%;min-width:0;padding:8px 12px;margin:0;overflow-wrap:anywhere}"
           ".pos-c *{box-sizing:border-box}.pos-c>summary{list-style:none;cursor:pointer;display:flex;align-items:center;"
           "gap:8px}.pos-c>summary::-webkit-details-marker{display:none}"
           ".pos-n{font-size:15px;font-weight:700;min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;"
           "white-space:nowrap}.pos-p{font-size:15px;font-weight:700;text-align:right;white-space:nowrap}"
           ".pos-p small{font-size:12px;font-weight:600}.pos-v{font-size:12px;color:var(--mut);white-space:nowrap}"
           ".pos-x{font-size:12px;color:var(--mut);transition:transform .15s}.pos-c[open] .pos-x{transform:rotate(180deg)}"
           ".pos-m{color:var(--mut);font-size:12.5px;margin:6px 0;line-height:1.45}"
           ".pos-s{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.pos-s form,.pos-d form{margin:0}"
           ".pos-s button,.pos-a button,.pos-d button{width:100%;min-height:38px;font-size:14px;font-weight:700;"
           "border-radius:8px}"
           ".pos-all{background:var(--bad,#dc2626)!important;color:#fff!important;border-color:var(--bad,#dc2626)!important}"
           ".pos-a{display:flex;gap:6px;margin-top:6px}.pos-a input{flex:1 1 auto;min-width:0;width:100%;font-size:16px;"
           "padding:7px 10px;border-radius:8px}.pos-a button{flex:0 0 auto;width:auto;padding:0 14px}"
           ".pos-k{font-size:12px;color:var(--mut);margin:8px 0 3px}"
           ".pos-d{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}"
           ".pos-l{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:13px}"
           ".pos-w{font-size:12px;margin:4px 0;line-height:1.4}")

POS_JS = ("<script>(function(){var L=document.getElementById('poslist');if(!L)return;"
          "function set(v,save){L.classList.toggle('tiles',v=='tiles');"
          "L.querySelectorAll('details').forEach(function(d){d.open=v=='tiles'});"
          "document.querySelectorAll('[data-posv]').forEach(function(b){b.classList.toggle('on',b.dataset.posv==v)});"
          "if(save){try{localStorage.setItem('posView',v)}catch(e){}}}"
          "var v='list';try{v=localStorage.getItem('posView')||'list'}catch(e){}set(v);"
          "document.querySelectorAll('[data-posv]').forEach(function(b){b.onclick=function(){set(b.dataset.posv,1)}})})();"
          "function posDca(m){var f=document.getElementById('dcaf');if(!f)return true;f.token.value=m;"
          "f.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(function(){f.amount.focus()},400);"
          "f.style.outline='3px solid var(--good,#16a34a)';return false}</script>")


def _sym(t):
    return esc((t["symbol"] or t["token"][:6]).replace("'", "").replace('"', ""))


def _sell_btn(t, frac, label, worth, cls=""):
    what = "CIJELU poziciju" if frac == 1 else f"{frac:.0%} pozicije"
    approx = f" (oko ${worth * frac:,.2f})" if worth else ""
    return (f'<form method=post action="/natjecanje/sell" onsubmit="return confirm(\'Prodati {what} {_sym(t)}{approx} '
            f'po trenutnoj cijeni?\')"><input type=hidden name=id value={t["id"]}><input type=hidden name=frac '
            f'value={frac}><button{cls}>{label}</button></form>')


def _add_btn(t, size):
    return (f'<form method=post action="/natjecanje/add" onsubmit="return confirm(\'Dokupiti još ${size} {_sym(t)} '
            f'po trenutnoj cijeni? Ulazna cijena pozicije postaje prosjek svih kupnji.\')">'
            f'<input type=hidden name=id value={t["id"]}><input type=hidden name=size value={size}>'
            f'<button>+ ${size}</button></form>')


def origin(t):
    """Who opened the position, in words: a manual buy or one of the automatic buyers (copy trading, Automatski DCA).
    Nicholas 2.11.: woke up to five positions he did not remember buying; they came from a wallet copy he had
    switched on the day before and nothing in Moje pozicije said so."""
    src = (t.get("source") or "").strip()
    if src.startswith("copy "):
        return "kupio automatski copy trading (" + src[5:] + ")"
    if src.startswith("DCA"):
        return "kupio automatski DCA (" + src + ")"
    return "kupio ručno"


def _origin_tag(t):
    src = t.get("source") or ""
    if src.startswith("copy "):
        return ' <small class=mut title="kupljeno automatski: copy trading">🔁 copy</small>'
    if src.startswith("DCA"):
        return ' <small class=mut title="kupljeno automatski: Automatski DCA">🔄 DCA</small>'
    return ""


def _autobuy_banner(con, user):
    """Everything that buys on this account by itself, right above the positions, with a stop button each.
    Nothing new is bought without the player switching it on; this makes sure he also sees that it is on."""
    try:
        from league import copy, dca
        fl = copy.follows(con, user)
        pl = dca.plans(con, user)
    except sqlite3.OperationalError:
        return ""
    if not fl and not pl:
        return ""
    rows = []
    for f in fl:
        who = ("wallet " + (f["label"] or f["target"][:6])) if f["kind"] == "wallet" else (f["label"] or f["target"])
        rows.append(f'<li>🔁 Copy trading: <b>{esc(who)}</b> · ${f["size_usd"]:,.0f} po ulazu, do {f["per_day"]} '
                    f'na dan · uključeno {ago(f["created"])[0]} '
                    + _form("/natjecanje/copy/stop", {"id": f["id"], "back": "natjecanje"}, "⏹ Prestani") + '</li>')
    for p in pl:
        rows.append(f'<li>🔄 Automatski DCA: <b>{esc(p["symbol"] or p["token"][:6])}</b> · {esc(dca.describe(p))} '
                    + _form("/natjecanje/dca/stop", {"id": p["id"]}, "⏹ Zaustavi") + '</li>')
    return ('<div class=card style="border:2px solid #f59e0b;background:#fffbeb;margin:6px 0 10px">'
            f'<b>⚠️ Automatske kupnje su uključene ({len(rows)})</b> <span class=mut style="font-size:13px">Ovo kupuje '
            'na tvom demo računu samo od sebe, i preko noći, dok ga ne zaustaviš. Pozicije koje je kupilo imaju oznaku '
            '🔁 ili 🔄.</span><ul style="margin:6px 0 0;padding-left:18px;line-height:1.9">' + "".join(rows)
            + '</ul></div>')


def _positions(mine, live, bot_dca):
    """Open positions on top of Natjecanje (Nicholas 1.11.). Default a compact list (one line per position: name,
    value, PnL; tap to open the actions), or tiles; the choice is remembered. Actions: sell 25% / 50% / Sve or a
    dollar amount, buy more now (+$10/25/50 into the same position) and automatic DCA, TP/SL. Every trade asks
    first. Returns (html, unrealized PnL)."""
    if not mine:
        return ('<p class="card mut">Nemaš otvorenih pozicija. Kupi token u okviru „🛒 Kupi token odmah” niže '
                'ili iz Predloženih tokena.</p>', 0.0)
    unreal, cards = 0.0, []
    mpk = collapse.peaks(data.HYPE_DB, {t["token"] for t in mine})
    for t in mine:
        price, liq, _ = live.get(t["token"], (None, None, None))
        val = store.value(t, price, liq) if price else None
        pnl = val - t["size_usd"] if val is not None else None
        worth = val - store._realized(t) if val is not None else None
        unreal += pnl or 0
        mc_now = t["entry_mcap"] * price / t["entry_px"] if price and t["entry_mcap"] and t["entry_px"] else None
        if mc_now and t["entry_mcap"]:
            collapse.add(mpk, t["token"], t["opened_ts"], t["entry_mcap"], None)
        col = collapse.check(mpk.get(t["token"]), mc_now, liq) if mc_now else None
        warn = ""
        if col:
            warn += (f'<div class="pos-w neg">💀 <b>Rugan:</b> {esc(col["text"])}. Oporavak je rijedak, razmisli o '
                     'prodaji.</div>')
        if t["token"] in bot_dca:
            warn += f'<div class="pos-w mut">🔄 Bot predlaže DCA: {esc(bot_dca[t["token"]])}</div>'
        big = namesake.check(t["token"], t["symbol"], mc_now or t["entry_mcap"]) if t["symbol"] else None
        if big:
            warn += f'<div class="pos-w">{namesake.text(big, t["symbol"], mc_now or t["entry_mcap"])}</div>'
        move = price / t["entry_px"] - 1 if price and t["entry_px"] else None
        pct = f' <small class={"pos" if (move or 0) > 0 else "neg" if (move or 0) < 0 else ""}>{move:+.0%}</small>' \
            if move is not None else ""
        meta = (f'Ulog {usd(t["size_usd"])[0]}' + (f' · vrijedi oko <b>${worth:,.2f}</b>' if worth is not None else "")
                + f' · MC {usd(t["entry_mcap"])[0]} → {usd(mc_now)[0]} · kupljeno {ago(t["opened_ts"])[0]}'
                + f' · {esc(origin(t))}'
                + (f' · likvidnost {usd(liq)[0]}' if liq else "")
                + (f' · cijena ${price:.3g} ({"DexScreener" if liq else "Jupiter, bez poola"}; osvježeno {time.strftime("%H:%M", time.gmtime())} UTC)'
                   if price else ""))
        if price:
            act = ('<div class=pos-k>Prodaj</div><div class=pos-s>' + _sell_btn(t, 0.25, "25%", worth)
                   + _sell_btn(t, 0.5, "50%", worth) + _sell_btn(t, 1, "Sve", worth, " class=pos-all") + '</div>'
                   f'<form method=post action="/natjecanje/sell" class=pos-a onsubmit="var v=this.usd.value;'
                   f'return v&&confirm(\'Prodati za $\'+v+\' od {_sym(t)}?\')">'
                   f'<input type=hidden name=id value={t["id"]}><input name=usd type=number inputmode=decimal min=1 '
                   f'step=any placeholder="ili iznos u $" aria-label="iznos u $"><button>Prodaj</button></form>'
                   '<div class=pos-k>Dokupi odmah u istu poziciju (ulazna cijena postaje prosjek)</div><div class=pos-d>'
                   + "".join(_add_btn(t, s) for s in (10, 25, 50)) + '</div>')
        else:
            act = ('<div class="pos-w mut">DexScreener trenutno ne daje cijenu.</div>'
                   + _form("/natjecanje/sell", {"id": t["id"], "rug": 1}, "Otpiši (nema cijene)"))
        auto_js = (f"var s=document.getElementById('autoid'),a=document.getElementById('autoall');"
                   f"if(s){{s.value='{t['id']}'}}if(a&&a.checked){{a.click()}}")
        links = (f'<div class=pos-l><a href="/natjecanje?dca={quote(t["token"])}#dca" '
                 f'onclick="return posDca(\'{esc(t["token"])}\')" title="isti iznos svakih nekoliko sati ili dana, '
                 f'sam od sebe">🔄 Automatski DCA (kupuj redovito)</a>'
                 f'<a href="#autosell" onclick="{auto_js}">🎯 TP/SL auto sell</a></div>')
        sym = ("💀 " if col else "") + esc(t["symbol"] or t["token"][:6]) + _origin_tag(t)
        cards.append(f'<details class="card pos-c"><summary><span class=pos-n>{sym}</span>'
                     + (f'<span class=pos-v>${worth:,.0f}</span>' if worth is not None else "")
                     + f'<span class=pos-p>{leaguedash.live_pnl(t["id"], pnl)} ${pct}</span>'
                     '<span class=pos-x>▾</span></summary>'
                     f'<div style="margin-top:6px">{tlink(t["token"], t["symbol"])}</div>'
                     f'<div class=pos-m>{meta}</div>{_auto_cell(t)}{warn}{act}{links}</details>')
    bar = ('<div class=pos-bar><span class=mut style="font-size:13px">Prikaz:</span>'
           '<button type=button data-posv=list>☰ Lista</button><button type=button data-posv=tiles>▦ Kartice</button>'
           '<span class=mut style="font-size:12px">Dodirni poziciju za prodaju, dokup i TP/SL. Ručna kupnja i prodaja '
           'prvo pita za potvrdu; copy trading i Automatski DCA kupuju sami dok ih ne zaustaviš (oznaka 🔁 ili 🔄 '
           'uz poziciju).</span></div>')
    return f'<style>{POS_CSS}</style>{bar}<div class=pos-list id=poslist>{"".join(cards)}</div>{POS_JS}', unreal


def _auto_cell(t):
    from league import auto
    d = auto.describe(t.get("auto"))
    part = f" · već prodano za ${t['realized']:,.2f}" if t.get("realized") else ""
    return f'<div class=mut style="font-size:12px">{esc(d + part)}</div>' if d or part else ""


def _auto_form(mine, rule=None):
    """Auto sell: smart exit (learned rules) or your own TP/SL in percent or market cap, for one position or (checkbox)
    for all open positions at once, optionally also for every new buy."""
    from league import auto
    opts = "".join(f'<option value={t["id"]}>{esc(t["symbol"] or t["token"][:6])} (MC ulaz {_mc(t["entry_mcap"])})</option>'
                   for t in mine)
    now = ""
    if rule:
        now = ('<div class="card" style="margin:8px 0">✅ <b>Pravilo za nove kupnje je uključeno:</b> '
               f'{esc(auto.describe_rule(rule))}. Svaka nova pozicija ga dobije odmah nakon kupnje (osim copy tradinga, '
               'koji ima svoj izlaz). '
               + _form("/natjecanje/auto", {"all": 1, "mode": "off", "keep": 1}, "Isključi pravilo") + '</div>')
    one = (f'<select name=id id=autoid style="max-width:100%">{opts}</select>' if mine else '')
    all_box = (f'<label style="flex-basis:100%;line-height:1.5"><input type=checkbox name=all value=1 id=autoall'
               f'{" checked" if not mine or rule else ""}> primijeni na <b>sve otvorene pozicije</b> ({len(mine)})</label>'
               if mine else '<input type=hidden name=all value=1>')
    new_box = ('<label style="flex-basis:100%;line-height:1.5"><input type=checkbox name=new value=1'
               f'{" checked" if rule or not mine else ""}> i na <b>sve nove kupnje</b> (ručne, brza kupnja, DCA)</label>')
    return ('<h3 id=autosell>Auto sell</h3><p class=tdesc>Alat prodaje umjesto tebe (provjera svake minute, i preko noći). '
            '<b>Smart sell</b> prodaje kako token raste: dio na svakoj razini zarade (take profit ljestvica), ostatak '
            'prati vrh (trailing stop), a ako token <b>eksplodira</b> (3x u 15 minuta) odmah proda pola ostatka, '
            'prije nego što cijena padne natrag. Pravila su naučena iz povijesti za klasu tokena; vidi '
            '<a href=/izlazi>Izlazi</a>. <b>Moj TP/SL</b>: upiši postotak '
            '(<code>100%</code>, <code>-30%</code>; SL <code>30</code> znači -30%) ili market cap (<code>$500k</code>, '
            '<code>1.2M</code>), alat sam preračuna cijenu za svaku poziciju. Postotak se računa od ulaza svake pozicije. '
            'Kvačica <b>sve otvorene pozicije</b> postavi isto pravilo na sve odjednom; <b>sve nove kupnje</b> ga '
            'pamti i stavlja na svaku sljedeću kupnju. Pojedinoj poziciji i dalje možeš promijeniti pravilo ručno. '
            'Djelomične prodaje se vide uz poziciju, a novac se vraća na račun kad se pozicija zatvori.</p>'
            + now +
            '<form method=post action="/natjecanje/auto" class="card flt" id=autof>'
            + one + '<select name=mode><option value=tpsl>moj TP/SL</option><option value=smart selected>Smart sell (prodaje kako raste)</option>'
            '<option value=off>isključi auto sell</option></select>'
            f'<input name=tp placeholder="TP: 100% ili $500k" size=16 value="{esc((rule or {}).get("tp") or "")}" '
            'style="max-width:100%">'
            f'<input name=sl placeholder="SL: -30% ili $40k" size=16 value="{esc((rule or {}).get("sl") or "")}" '
            'style="max-width:100%">'
            + all_box + new_box + '<button>Postavi</button></form>'
            '<script>(function(){var a=document.getElementById("autoall"),s=document.getElementById("autoid");'
            'if(!a||!s)return;function u(){s.disabled=a.checked;s.style.opacity=a.checked?.4:1}'
            'a.addEventListener("change",u);u()})()</script>')


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
                raise ValueError("ni DexScreener ni Jupiter ne znaju cijenu za tu adresu. Provjeri je li to adresa "
                                 "tokena, a ne novčanika (na GMGN-u i Solscanu je lako kopirati krivu). Adrese "
                                 "pump.fun tokena obično završavaju na „pump”.")
            price, liq, _, mcap = live[token]
            col = collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
            if col:
                raise ValueError(f"token je rugan ({col['text']}), kupnja je zaključana")
            size = float(form.get("size") or 0)
            have = next((t for t in store.trades(con, user, "open") if t["token"] == token), None)
            if have:   # Nicholas 2.11.: buying a token you already hold adds to that position (average entry)
                return _add_more(con, user, have, size, price, liq, back)
            symbol = form.get("symbol") or _symbol(token)
            store.buy(con, user, token, symbol, size, price, liq, form.get("source", "ručno"),
                      float(form["score"]) if form.get("score") else None, mcap)
            msg = f'Kupljeno {symbol or token[:6]} za ${size:,.0f} na MC {_mc(mcap)}'
            big = namesake.check(token, symbol, mcap)
            if big:   # Filip 5.11.: pump.fun ARIA (MC $74k) bought while watching AriaAI on Binance
                msg += (f'. Pozor: postoji {big["name"]} ({symbol}) s MC {_mc(big["mcap"])} na adresi '
                        f'{big["token"][:4]}…{big["token"][-4:]}; ovaj ima MC {_mc(mcap)}. Ako si htio onaj veliki, '
                        'kupio si kopiju.')
            return f"{back}?ok={quote(msg)}"
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
                frac = 1.0
                if form.get("usd"):   # "upiši iznos u $": share of what the rest is worth now
                    want = float(form["usd"])
                    rest = store.value(t, price, liq) - store._realized(t)
                    if want <= 0 or rest <= 0:
                        raise ValueError("upiši iznos veći od $0")
                    frac = min(1.0, want / rest)
                elif form.get("frac"):
                    frac = float(form["frac"])
                    if not 0 < frac <= 1:
                        raise ValueError("neispravan dio pozicije")
                pnl, whole = store.sell_partial(con, user, tid, frac, price, liq, mcap=mcap)
                sym = t['symbol'] or t['token'][:6]
                msg = (f"Prodano sve: {sym}, {pnl:+.2f} $" if whole else
                       f"Prodano {frac:.0%} pozicije {sym}: {pnl:+.2f} $. Ostatak je i dalje otvoren.")
                return f"{back}?ok={quote(msg)}#pozicije"
            msg = f"Otpisano {t['symbol'] or t['token'][:6]}: {pnl:+.2f} $"
            return f"{back}?ok={quote(msg)}#pozicije"
        if path == "/natjecanje/add":   # "Dokupi +$N" on a position card
            from league import dca
            tid = int(form.get("id") or 0)
            t = next((t for t in store.trades(con, user, "open") if t["id"] == tid), None)
            if not t:
                raise ValueError("nema te otvorene pozicije")
            size = float(form.get("size") or 0)
            live = market({t["token"]})
            if t["token"] not in live:
                raise ValueError("DexScreener trenutno ne daje cijenu, probaj ponovo")
            price, liq, _, mcap = live[t["token"]]
            if collapse.check(collapse.peaks(data.HYPE_DB, [t["token"]]).get(t["token"]), mcap, liq):
                raise ValueError("token je rugan, dokup je zaključan")
            return _add_more(con, user, t, size, price, liq, back)
        if path == "/natjecanje/dca/start":
            from league import dca
            token = form.get("token", "").strip()
            if not MINT.fullmatch(token):
                from ui import real
                token = real.resolve(token)[0]
            live = market({token}) if token else {}
            if token not in live:
                raise ValueError("ni DexScreener ni Jupiter ne znaju cijenu za tu adresu. Provjeri je li to adresa "
                                 "tokena, a ne novčanika (na GMGN-u i Solscanu je lako kopirati krivu). Adrese "
                                 "pump.fun tokena obično završavaju na „pump”.")
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
        if path == "/natjecanje/auto" and (form.get("all") or form.get("new")):
            from league import auto
            mode = form.get("mode", "")
            if form.get("keep"):   # "Isključi pravilo": only stop it for new buys, positions keep what they have
                n, skipped = auto.apply_all(con, user, "off", all_open=False)
                return f"{back}?ok={quote('Pravilo za nove kupnje je isključeno. Otvorene pozicije zadržavaju svoj auto sell.')}#autosell"
            all_open = bool(form.get("all")) and con.execute(
                "SELECT 1 FROM trades WHERE user=? AND status='open'", (user,)).fetchone() is not None
            n, skipped = auto.apply_all(con, user, mode, form.get("tp", ""), form.get("sl", ""),
                                        apply_new=bool(form.get("new")) and mode not in ("", "off"), all_open=all_open)
            if not form.get("all") and form.get("id"):   # one position from the dropdown + the rule for new buys
                auto.set_auto(con, user, int(form["id"]), mode, form.get("tp", ""), form.get("sl", ""))
                n = 1
            what = auto.describe_rule({"mode": mode, "tp": form.get("tp"), "sl": form.get("sl")}) \
                if mode not in ("", "off") else "auto sell isključen"
            msg = f"{what[:1].upper() + what[1:]}: postavljeno na {n} " + ("otvorenu poziciju" if n == 1 else "otvorenih pozicija")
            if mode not in ("", "off") and form.get("new"):
                msg += " i na sve nove kupnje"
            if skipped:
                msg += ". Preskočeno: " + "; ".join(f"{sym} ({why})" for sym, why in skipped[:5])
            return f"{back}?ok={quote(msg)}#autosell"
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


def _add_more(con, user, t, size, price, liq, back):
    """Buy more into an open position (Dokupi +$N, or Kupi with a token you already hold): same position, entry price
    becomes the dollar-weighted average, size grows."""
    from league import dca
    cash = store.account(con, user)["cash"]
    if size <= 0 or size > cash + 1e-9:
        raise ValueError(f"za dokup treba ${size:,.0f}, a slobodno je ${cash:,.2f}")
    if not price or price <= 0:
        raise ValueError("nema cijene za token")
    if not liq or liq < 1000:
        raise ValueError("likvidnost premala (< $1k)")
    dca.add_to(con, t["id"], size, price, liq)
    msg = (f"Dokupljeno {t['symbol'] or t['token'][:6]} za ${size:,.0f} u postojeću poziciju (sad ukupno "
           f"${t['size_usd'] + size:,.0f}); ulazna cijena je prosjek svih kupnji.")
    return f"{back}?ok={quote(msg)}#pozicije"


def _symbol(token):
    try:
        from dexscreener import client
        for p in client.tokens("solana", [token]):
            if p["baseToken"]["address"] == token:
                return p["baseToken"].get("symbol")
    except Exception:
        pass
    return None
