"""Natjecanje: Ivan, Panda and Jure each pick demo trades from the bot's suggestions; leaderboard by profit;
plus the box for feature ideas. Data in league.db (league/store.py), never in the bot's own paper.db.

Pages get the logged-in player (Basic auth user name, see run_ui.py); None means the shared UI_PASSWORD,
which can look but not trade.
"""
import re
import time
from urllib.parse import quote

from league import store
from ui import data
from ui.html import ago, badge, esc, num, scorecell, signed, table, tlink, ts, usd, verdict
from ui.paper import _live

SUGGEST_H = 48
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
STATUS = {"novo": "", "u izradi": "warn", "napravljeno": "good", "odbijeno": "bad"}


def _form(action, fields, button, extra=""):
    hidden = "".join(f'<input type=hidden name="{esc(k)}" value="{esc(v)}">' for k, v in fields.items())
    return (f'<form method=post action="{action}" style="display:inline-flex;gap:4px;margin:0">{hidden}{extra}'
            f'<button>{button}</button></form>')


def login_help():
    """Shown when the browser's login box is cancelled, and explains how to log in."""
    miss = store.missing_passwords()
    note = (f"<p class=neg>Lozinke još nisu postavljene za: {esc(', '.join(miss))}. Upiši ih u Render → crypto-bot → "
            f"Environment kao {esc(', '.join('UI_PASS_' + u.upper() for u in miss))}.</p>") if miss else ""
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


def _suggestions():
    since = time.time() - SUGGEST_H * 3600
    return [c for c in data.paper_candidates() if (c["first_ts"] or 0) >= since][:60]


def page(qs, user):
    con = store.connect()
    try:
        mine = store.trades(con, user, "open") if user else []
        cands = _suggestions()
        everyone_open = store.trades(con, status="open")
        live = _live({t["token"] for t in everyone_open} | {c["token"] for c in cands})
        b = [f"<h1>Natjecanje</h1><p class=mut>Svatko ima svoj demo račun od ${store.START_USD:,.0f}. Biraš tokene iz "
             f"prijedloga alata, kupuješ i prodaješ po živoj cijeni s DexScreenera (uz 1% fee i slippage kao u pravoj "
             f"trgovini). Pobjeđuje tko ima najviše profita. Bot trguje sam za sebe u <a href=/paper>Demo tradingu</a>; "
             f"ovdje je samo za usporedbu.</p>", _who(user), _err(qs)]
        b.append("<h2>Ljestvica</h2>" + leaderboard_html(con, live, user))
        if not user:
            return "Natjecanje", "".join(b)

        acc = store.account(con, user)
        unreal, rows = 0.0, []
        for t in mine:
            price, liq, _ = live.get(t["token"], (None, None, None))
            val = store.value(t, price, liq) if price else None
            pnl = val - t["size_usd"] if val is not None else None
            unreal += pnl or 0
            sell_btn = _form("/natjecanje/sell", {"id": t["id"]}, "Prodaj") if price else \
                _form("/natjecanje/sell", {"id": t["id"], "rug": 1}, "Otpiši (nema cijene)")
            rows.append([tlink(t["token"], t["symbol"]), ago(t["opened_ts"]), usd(t["size_usd"]),
                         num(t["entry_px"], "{:.4g}"), num(price, "{:.4g}"),
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
            ["Token", "Kupljeno", ("Ulog", "n"), ("Ulazna cijena", "n"), ("Sada", "n"), ("Pomak", "n"),
             ("PnL $ (ako prodaš sad)", "n"), ("Likvidnost", "n"), ""], rows, empty="Nemaš otvorenih pozicija."))

        size = f'<input name=size type=number min=1 step=1 value=50 style="width:70px" title="ulog u $">'
        srows = []
        for c in cands:
            price, liq, _ = live.get(c["token"], (None, None, None))
            move = price / c["price"] - 1 if price and c["price"] else None
            act = _form("/natjecanje/buy", {"token": c["token"], "symbol": c["symbol"] or "", "score": c["score"] or "",
                                            "source": c["origin"] or ""}, "Kupi", size) if price else \
                '<span class=mut>nema cijene</span>'
            srows.append([tlink(c["token"], c["symbol"]), ago(c["first_ts"]), esc(c["origin"]), scorecell(c["score"]),
                          badge("bot uzeo" if c.get("trade_id") else "bot preskočio", "good" if c.get("trade_id") else ""),
                          (esc(c["reason"] or ""), "", "wrap"), verdict(c["rug_verdict"]),
                          signed(move, "{:+.0%}"), usd(liq), act])
        b.append(f"<h2>Prijedlozi alata (zadnjih {SUGGEST_H} h)</h2><p class=mut>Tokeni koje je bot razmotrio, najnoviji "
                 "prvi. „Pomak” je promjena cijene otkad ga je alat vidio. Upiši ulog u $ i klikni Kupi.</p>")
        b.append(table(["Token", "Viđen", "Porijeklo", ("Hype", "n"), "Bot", ("Razlog", "wrap"), "Rug", ("Pomak", "n"),
                        ("Likvidnost", "n"), "Ulog $"], srows, empty="Alat zadnjih dana nije ništa predložio."))
        b.append('<form method=post action="/natjecanje/buy" class=flt>Ili zalijepi adresu tokena: '
                 f'<input name=token placeholder="mint adresa" size=46 required>{size}<button>Kupi</button></form>')

        closed = store.trades(con, user, "closed")
        b.append("<h3>Tvoji zatvoreni trejdovi</h3>" + table(
            ["Token", "Kupljeno", "Prodano", ("Ulog", "n"), ("PnL $", "n"), ("Povrat", "n"), "Napomena"],
            [[tlink(t["token"], t["symbol"]), ts(t["opened_ts"]), ts(t["closed_ts"]), usd(t["size_usd"]),
              signed(t["pnl_usd"]), signed(t["ret"], "{:+.0%}"), esc(t["note"] or "")] for t in closed],
            empty="Još ništa nisi prodao."))
        b.append("<p class=mut>Ideja kako poboljšati alat? Upiši je u <a href=/prijedlozi>Prijedloge</a>.</p>")
        return "Natjecanje", "".join(b)
    finally:
        con.close()


def ideas_page(qs, user):
    con = store.connect()
    try:
        b = ["<h1>Prijedlozi za nove feature</h1><p class=mut>Što bi alat trebao raditi bolje ili drugačije? "
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


def post(path, form, user):
    """Handle a form; returns where to send the browser next."""
    back = "/prijedlozi" if path.startswith("/prijedlozi") else "/natjecanje"
    if not user:
        return f"{back}?err={quote('prijavi se svojim imenom')}"
    con = store.connect()
    try:
        if path == "/natjecanje/buy":
            token = form.get("token", "").strip()
            if not MINT.fullmatch(token):
                raise ValueError("to nije Solana adresa tokena")
            live = _live({token}) if token else {}
            if token not in live:
                raise ValueError("DexScreener ne zna cijenu tog tokena")
            price, liq, _ = live[token]
            symbol = form.get("symbol") or _symbol(token)
            size = float(form.get("size") or 0)
            store.buy(con, user, token, symbol, size, price, liq, form.get("source", "ručno"),
                      float(form["score"]) if form.get("score") else None)
            return f"{back}?ok={quote(f'Kupljeno {symbol or token[:6]} za ${size:,.0f}')}"
        if path == "/natjecanje/sell":
            tid = int(form.get("id") or 0)
            t = next((t for t in store.trades(con, user, "open") if t["id"] == tid), None)
            if not t:
                raise ValueError("nema te otvorene pozicije")
            if form.get("rug"):
                pnl = store.sell(con, user, tid, 0, 0, "otpisano: nema cijene")
            else:
                live = _live({t["token"]})
                if t["token"] not in live:
                    raise ValueError("DexScreener trenutno ne daje cijenu, probaj ponovo")
                price, liq, _ = live[t["token"]]
                pnl = store.sell(con, user, tid, price, liq)
            msg = f"Prodano {t['symbol'] or t['token'][:6]}: {pnl:+.2f} $"
            return f"{back}?ok={quote(msg)}"
        if path == "/prijedlozi/add":
            store.add_idea(con, user, form.get("text"))
            return f"{back}?ok={quote('Hvala, prijedlog je spremljen.')}"
        if path == "/prijedlozi/status":
            if form.get("status") in STATUS:
                store.set_idea_status(con, int(form.get("id") or 0), form["status"])
            return back
        return back
    except (ValueError, KeyError) as e:
        return f"{back}?err={quote(str(e))}"
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
