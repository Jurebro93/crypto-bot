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
from ui import confidence, data
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


def _err(qs):
    if qs.get("err"):
        return f'<div class=card style="border-color:var(--bad)"><b class=neg>Nije prošlo:</b> {esc(qs["err"])}</div>'
    if qs.get("ok"):
        return f'<div class=card style="border-color:var(--good)">{esc(qs["ok"])}</div>'
    return ""


def _bot_row():
    """The bot's own automatic paper account, as a yardstick (not ranked)."""
    try:
        from paper import sim
        bank = sim.load_config().get("bankroll_usd", 1000)
    except Exception:
        bank = 1000
    tr = data.paper_trades()
    closed = [t for t in tr if t["status"] == "closed"]
    profit = sum(t["pnl_usd"] or 0 for t in tr)
    return ["🤖 bot (automatski, za usporedbu)", "–", num(bank + profit, "${:,.2f}"), signed(profit), signed(profit / bank if bank else 0, "{:+.1%}"),
            num(sum(1 for t in tr if t["status"] == "open")),
            f"{sum(1 for t in closed if (t['pnl_usd'] or 0) > 0)} / {len(closed)}", "–"]


def leaderboard_html(con, live, me=None):
    rows = []
    for i, r in enumerate(store.leaderboard(con, live), 1):
        best = r["best"]
        name = f"<b>{esc(r['user'])}</b>" + (" (ti)" if r["user"] == me else "")
        rows.append([("🥇🥈🥉"[i - 1] if i <= 3 else str(i)) + " " + name, num(r["cash"], "${:,.2f}"), num(r["equity"], "${:,.2f}"),
                     signed(r["profit"]), signed(r["ret"], "{:+.1%}"), num(r["open"]), f"{r['wins']} / {r['closed']}",
                     (f"{esc(best['symbol'] or best['token'][:6])} {best['pnl_usd']:+.2f} $" if best else "–")])
    rows.append(_bot_row())
    return table(["Igrač", ("Slobodno", "n"), ("Stanje računa", "n"), ("Profit $", "n"), ("Povrat", "n"),
                  ("Otvoreno", "n"), "Dobitni / zatvoreni", "Najbolji trejd"], rows)


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
        cands = _suggestions(qs)
        mints = {t["token"] for t in store.trades(con)} | {c["token"] for c in cands}
        mk = market(mints)
        live = {t: v[:3] for t, v in mk.items()}
        mcaps = {t: v[3] for t, v in mk.items() if v[3]}
        b = [f"<h1>Natjecanje</h1><p class=mut>Svatko ima svoj demo račun od ${store.START_USD:,.0f}. Biraš tokene iz "
             f"prijedloga alata, kupuješ i prodaješ po živoj cijeni s DexScreenera (uz 1% fee i slippage kao u pravoj "
             f"trgovini). Pobjeđuje tko ima najviše profita. Bot trguje sam za sebe u <a href=/paper>Demo tradingu</a>; "
             f"ovdje je samo za usporedbu.</p>", _who(user), _err(qs)]
        b.append("<h2>Ljestvica</h2>" + leaderboard_html(con, live, user))
        b.append("<h2>Pozicije i trejdovi svih igrača</h2>"
                 "<p class=mut>Svi vide sve: kada je tko kupio, na kojem market capu, gdje je sada i koliko je u plusu ili minusu. "
                 "PnL otvorenih je ono što bi prodaja sada donijela, uz fee i slippage.</p>"
                 + everyone_html(con, live, mcaps))
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
                         signed(price / t["entry_px"] - 1 if price else None, "{:+.0%}"), signed(pnl),
                         usd(liq), sell_btn])
        b.append(f'<h2>Tvoj račun: {esc(user)}</h2><div class=grid>'
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
        b.append('<h2>Kupi bilo koji token</h2><form method=post action="/natjecanje/buy" class="card flt">'
                 '<input name=token placeholder="adresa tokena ili DexScreener link" size=50 required>'
                 f'{size}<button>Kupi</button><span class=mut>ne mora biti s liste prijedloga</span></form>')
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
            srows.append([tlink(r["token"], r["symbol"]), (confidence.badge_html(r["conf"]), r["conf"], "n"),
                          (razinab(r["razina"]), r["razina"] or 0, "n"), (klasab(r["klasa"]), r["klasa"] or "", ""),
                          (f"<b>{r['passed']}</b>/{r['passed'] + r['failed']}", r["passed"], "n"), scorecell(r["hype_last"]),
                          rugcell(r),
                          badge("bot uzeo", "good") if c.get("trade_id") else (badge("bot preskočio") if c else "–"),
                          usd(r["mcap"]), signed(move, "{:+.0%}"), usd(liq), ago(r["last_seen"]), act])
        b.append(f"<h2>Prijedlozi alata</h2><p class=mut>Isti tokeni i isti poredak kao „Istaknuti kandidati” na "
                 "<a href=/>Pregledu</a>: confidence spaja hype, X, smart money, KOL, holdere, rug filter i evente. "
                 "Tokeni koje je rug filter odbacio i tokeni koji su se u međuvremenu srušili (rug: 70%+ ispod vrha ili "
                 "izvučena likvidnost) su skriveni osim ako ih uključiš ili tražiš po imenu; njih se ne može kupiti. "
                 f"Prikazano {len(srows)} (najviše {SUGGEST_MAX}). Upiši ulog u $ i klikni Kupi.</p>" + _filters(qs))
        b.append(table(["Token", ("Confidence", "n"), ("Razina", "n"), "Klasa", ("Prošao", "n"), ("Hype", "n"), "Rug",
                        "Bot", ("Mcap viđen", "n"), ("Pomak", "n"), ("Likvidnost", "n"), "Zadnje", "Ulog $"], srows,
                       empty="Nijedan token ne odgovara filteru."))

        closed = store.trades(con, user, "closed")
        b.append("<h3>Tvoji zatvoreni trejdovi</h3>" + table(
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
    """Handle a form; returns where to send the browser next."""
    back = "/prijedlozi" if path.startswith("/prijedlozi") else "/natjecanje"
    if not user:
        return f"{back}?err={quote('prijavi se svojim imenom')}"
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
        return f"{back}?err={quote(str(e))}"
    finally:
        con.close()


def everyone_html(con, live, mcaps):
    """Every player's demo positions and trades, open and closed, so the players can see what the others did."""
    rows = []
    for t in store.trades(con):
        price = (live.get(t["token"]) or (None,))[0]
        mc_now = mcaps.get(t["token"])
        entry_mc = t.get("entry_mcap") or (mc_now * t["entry_px"] / price if mc_now and price else None)
        if t["status"] == "open":
            val = store.value(t, price, live[t["token"]][1]) if price else None
            pnl, mc, status = (val - t["size_usd"] if val is not None else None), mc_now, badge("otvoreno", "good")
        else:
            pnl, status = t["pnl_usd"], f"prodano {ts(t['closed_ts'])[0]}"
            mc = t.get("exit_mcap") if t.get("exit_mcap") is not None else \
                (entry_mc * t["exit_px"] / t["entry_px"] if entry_mc and t["entry_px"] else None)
        rows.append([f"<b>{esc(t['user'])}</b>", tlink(t["token"], t["symbol"]), ts(t["opened_ts"]), usd(t["size_usd"]),
                     usd(entry_mc), usd(mc) if mc is not None else ("–", -1, "n"),
                     signed(mc / entry_mc - 1 if mc is not None and entry_mc else None, "{:+.0%}"), signed(pnl),
                     signed(pnl / t["size_usd"] if pnl is not None else None, "{:+.0%}"), status, esc(t["source"] or "")])
    return table(["Igrač", "Token", "Kupljeno", ("Ulog", "n"), ("Ulazni MC", "n"), ("MC sada / izlaz", "n"), ("Pomak MC", "n"),
                  ("PnL $", "n"), ("Povrat", "n"), "Status", "Odakle"], rows, "allp",
                 empty="Nitko još nije kupio nijedan token.")


def _symbol(token):
    try:
        from dexscreener import client
        for p in client.tokens("solana", [token]):
            if p["baseToken"]["address"] == token:
                return p["baseToken"].get("symbol")
    except Exception:
        pass
    return None
