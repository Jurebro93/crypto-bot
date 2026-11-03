"""Page /pravi-trade: the bot trades real SOL from one dedicated wallet (Nicholas 3.11.).

- The owner (trade/settings.owner(), Render TRADE_OWNER, default Jure) switches it on and off, sets the limits, picks
  the KOLs and wallets to follow and invites registered players.
- Invited players only look (no key or money of theirs is involved); a "Kupi i ti" link opens Jupiter in their own
  wallet.
- Follows are competition follows of the account "pravi-trade" (league/copy.py makes the demo entries and exits
  every minute); run_trade.py follow turns each of them into a real swap through Jupiter (trade/executor.py).
- Real money needs the switch here AND TRADE_LIVE=1 + SOLANA_PRIVATE_KEY in Render, which only the owner sets.
"""
import os
import sqlite3
import time
from urllib.parse import quote

from league import copy, store
from trade import executor, settings, wallet
from ui.html import ago, badge, esc, num, signed, table, tlink, wlink

BACK = "/pravi-trade"
_BAL = {}   # address -> (ts, SOL): one RPC call a minute at most


def _balance(addr):
    if not addr:
        return None
    hit = _BAL.get(addr)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    try:
        val = wallet.sol_balance(addr)
    except Exception:  # noqa: BLE001 - RPC down: the page still renders
        val = None
    _BAL[addr] = (time.time(), val)
    return val


def _cfg(tcon):
    try:
        base = executor.load_config()
    except (OSError, ValueError):
        base = {}
    return settings.merged({"size_sol": 0.05, "max_sol_per_day": 0.5, "max_open": 5, "min_sol_reserve": 0.05,
                            "max_cost_pct": 6, "max_loss_day": 0.3, "max_signal_age_s": 180, **base}, tcon)


def _tcon():
    return executor.connect(settings.DB)


def _league_account(con):
    """The follows' demo account gets a big balance, so the demo side never skips a call for lack of cash
    (the real limits are the ones on this page)."""
    con.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, int(time.time())))
    con.commit()


def _status(cfg, owner):
    armed, on = executor.armed(), cfg["on"]
    addr = wallet.address()
    if on and armed:
        head = '<div class=card style="border:2px solid var(--good)"><b style="font-size:18px">🟢 UKLJUČENO: bot trguje pravim novcem</b>'
    elif on:
        head = ('<div class=card style="border:2px solid var(--warn)"><b style="font-size:18px">🟡 Uključeno, ali bez ključa: '
                'radi samo probno</b><p class=mut>U Renderu još nisu postavljeni SOLANA_PRIVATE_KEY i TRADE_LIVE=1. '
                'Dok ih nema, sve kupnje su probne (bez novca).</p>')
    else:
        head = ('<div class=card><b style="font-size:18px">⚪ ISKLJUČENO: samo probno, bez novca</b>'
                '<p class=mut>Bot i dalje prati odabrane KOL-ove i walletove i bilježi što bi kupio, ali ništa ne potpisuje.</p>')
    bal = _balance(addr)
    rows = [f'<b>Wallet:</b> {f"<a href=https://solscan.io/account/{esc(addr)} target=_blank rel=noopener><code>{esc(addr)}</code></a>" if addr else "nije postavljen"}',
            f'<b>Stanje:</b> {f"{bal:.4f} SOL" if bal is not None else "–"}',
            f'<b>Ključ u Renderu:</b> {"da" if wallet.can_sign() else "ne"} · <b>TRADE_LIVE=1:</b> '
            f'{"da" if os.environ.get("TRADE_LIVE") == "1" else "ne"}']
    if cfg.get("sell_all"):
        rows.append('<b class=neg>Prodaja svega je u tijeku…</b>')
    b = [head, "<p>" + "<br>".join(rows) + "</p>"]
    if owner:
        if on:
            b.append('<form method=post action=/pravi-trade/switch style="display:inline" onsubmit="return confirm('
                     '\'Isključiti? Nove kupnje staju odmah, otvorene pozicije se i dalje prodaju po pravilima.\')">'
                     '<input type=hidden name=on value=0><button>⏸ Isključi pravi trade (nove kupnje staju)</button></form> ')
        else:
            b.append('<form method=post action=/pravi-trade/switch style="display:inline" onsubmit="return confirm('
                     '\'Uključiti pravi trade? Bot će SAM kupovati pravim SOL-om iz walleta, i preko noći, unutar '
                     'limita ispod, dok ne klikneš Isključi.\')"><input type=hidden name=on value=1>'
                     '<button style="background:var(--good);color:#fff">▶ Uključi pravi trade</button></form> ')
        b.append('<form method=post action=/pravi-trade/sellall style="display:inline" onsubmit="return confirm('
                 '\'Prodati SVE otvorene pozicije odmah i isključiti pravi trade?\')">'
                 '<button style="background:var(--bad);color:#fff">🛑 Prodaj sve i isključi</button></form>')
    b.append("</div>")
    return "".join(b)


def _today(tcon, cfg):
    now = time.time()
    mode = "live" if executor.is_live(cfg) else "dry"
    start = executor._day_start(now)
    spent = tcon.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE mode=? AND opened_ts>=? AND status IN "
                         "('open','closed')", (mode, start)).fetchone()[0]
    n_open = tcon.execute("SELECT COUNT(*) FROM positions WHERE mode=? AND status='open'", (mode,)).fetchone()[0]
    pnl = executor.day_pnl(tcon, now, mode)
    word = "pravo" if mode == "live" else "probno"
    return (f'<div class=card><b>Danas ({word}):</b> potrošeno {spent:.3f} od {cfg["max_sol_per_day"]:g} SOL · '
            f'zarada/gubitak zatvorenih <span class="{"pos" if pnl > 0 else "neg" if pnl < 0 else ""}">{pnl:+.4f} SOL</span>'
            f' (stop na -{cfg["max_loss_day"]:g}) · otvoreno {n_open} od {cfg["max_open"]}</div>')


def _limits(cfg, owner):
    if not owner:
        items = "".join(f"<li>{esc(lab)}: <b>{cfg.get(k, '–')}</b></li>" for k, (lab, *_rest) in settings.LIMITS.items())
        return f"<h2 id=limiti>Limiti</h2><ul>{items}</ul>"
    fields = "".join(f'<label style="display:block;margin:6px 0">{esc(lab)} <input name={k} value="{cfg.get(k, "")}" '
                     f'inputmode=decimal style="width:90px"></label>' for k, (lab, *_rest) in settings.LIMITS.items())
    paper = (f'<label style="display:block;margin:6px 0"><input type=checkbox name=follow_paper value=1'
             f'{" checked" if cfg.get("follow_paper") else ""}> prati i demo strategiju bota (osim KOL-ova i walleta ispod)</label>')
    return (f'<h2 id=limiti>Limiti</h2><form method=post action=/pravi-trade/limits class=card>{fields}{paper}'
            '<p class=mut>Ulog po kupnji vrijedi za svako praćenje. Kad se dosegne dnevna potrošnja ili dnevni gubitak, '
            'nove kupnje staju do ponoći (UTC); prodaje idu dalje.</p><button>Spremi limite</button></form>')


def _live_wallets():
    import json
    con = copy._ro(copy._paths()["kol"])
    if con is None:
        return set()
    try:
        row = copy._q(con, "SELECT value FROM kv WHERE key='chain_hook'")
        return set(json.loads((row[0][0] if row else None) or "{}").get("wallets") or [])
    finally:
        con.close()


def _exit_fields():
    return ('<label>izlaz <select name=exit style="max-width:100%">'
            '<option value="">zadano (Smart sell / kad on proda)</option>'
            '<option value=smart>Smart sell (samo influencer)</option>'
            '<option value=mirror>prodaj kad on proda (samo wallet)</option>'
            '<option value=mirror_smart>kad on proda + Smart sell (samo wallet)</option>'
            '<option value=tpsl>moj TP/SL</option></select></label> '
            '<input name=tp placeholder="TP npr. 100%" size=11> <input name=sl placeholder="SL npr. -30%" size=11>')


def _follows(con, owner):
    fl = copy.follows(con, settings.LEAGUE_USER)
    res = copy.follow_results(con)
    rows = []
    for f in fl:
        r = res.get(f["id"], {"n": 0, "open": 0, "closed": 0, "wins": 0})
        who = (f'<a href="/kol/{quote(f["target"])}">@{esc(f["target"])}</a>' if f["kind"] == "kol"
               else wlink(f["target"]) + f" {esc(f['label'] or '')}")
        stop = (f'<form method=post action=/pravi-trade/stop style=margin:0><input type=hidden name=id value={f["id"]}>'
                '<button>Prestani pratiti</button></form>') if owner else ""
        rows.append([badge("influencer" if f["kind"] == "kol" else "wallet"), who, num(f["per_day"]),
                     esc(copy.describe_exit(f["exit"])), ago(f["created"]), num(r["n"]), stop])
    b = ['<h2 id=pratim>Koga bot prati pravim novcem</h2>',
         table(["Što", "Koga", ("Max/dan", "n"), "Izlaz", "Od", ("Ulaza", "n"), ""], rows, tid="ptfol",
               empty="Još nikoga. Dodaj influencera ili wallet ispod ili prebaci neko demo praćenje koje je u plusu.")]
    if owner:
        b.append('<form method=post action=/pravi-trade/follow class=card onsubmit="return confirm(\'Bot će kupovati na '
                 'svaki njegov call / kupnju dok ga ne prestaneš pratiti (pravim novcem ako je prekidač uključen). Dodati?\')">'
                 '<b>Dodaj praćenje</b><br><label>vrsta <select name=kind><option value=kol>influencer (X/Telegram)</option>'
                 '<option value=wallet>wallet</option></select></label> '
                 '<input name=target placeholder="handle bez @ ili adresa walleta" size=30 required style="max-width:100%"> '
                 '<input name=label placeholder="ime (nije obavezno)" size=14> '
                 '<label>najviše ulaza na dan <input name=per_day type=number min=1 max=50 value=5 style="width:60px"></label> '
                 + _exit_fields() + ' <button>Prati pravim novcem</button></form>')
    return "".join(b)


def _candidates(con, owner):
    """Every competition follow that already closed trades, best first: the ones in profit are worth copying."""
    res = copy.follow_results(con)
    have = {(f["kind"], f["target"]) for f in copy.follows(con, settings.LEAGUE_USER)}
    best = {}
    for f in copy.follows(con, active=None):
        r = res.get(f["id"])
        if f["user"] == settings.LEAGUE_USER or not r or not r["closed"]:
            continue
        k = (f["kind"], f["target"])
        acc = best.setdefault(k, {"f": f, "closed": 0, "wins": 0, "pnl": 0.0, "users": set()})
        acc["closed"] += r["closed"]
        acc["wins"] += r["wins"]
        acc["pnl"] += r["pnl"]
        acc["users"].add(f["user"])
    rows = []
    for (kind, target), a in sorted(best.items(), key=lambda kv: -kv[1]["pnl"])[:40]:
        f = a["f"]
        who = (f'<a href="/kol/{quote(target)}">@{esc(target)}</a>' if kind == "kol" else wlink(target) + f" {esc(f['label'] or '')}")
        if (kind, target) in have:
            act = badge("već pratiš ✓", "good")
        elif owner:
            act = (f'<form method=post action=/pravi-trade/copyfollow style=margin:0 onsubmit="return confirm(\'Pratiti '
                   f'{esc(f["label"] or target)} pravim novcem, s istim izlazom kao u demu?\')"><input type=hidden name=id '
                   f'value={f["id"]}><button>Prati pravim novcem</button></form>')
        else:
            act = ""
        rows.append([badge("influencer" if kind == "kol" else "wallet"), who, num(a["closed"]),
                     (f'{a["wins"] / a["closed"]:.0%}', a["wins"] / a["closed"], "n"), signed(a["pnl"], "{:+,.2f} $"),
                     esc(", ".join(sorted(a["users"]))), act])
    return ('<h2 id=kandidati>Demo praćenja: tko je u plusu</h2><p class=mut>Svi KOL-ovi i walleti koje su igrači '
            'pratili na demo računima u Copy tradingu, po zaradi zatvorenih ulaza. Jedan klik ih prebacuje u pravi trade.</p>'
            + table(["Što", "Koga", ("Zatvorenih ulaza", "n"), ("Uspješnost", "n"), ("Zarada zatvorenih $", "n"),
                     "Tko ga prati", ""], rows, tid="ptcand",
                    empty="Još nema demo praćenja sa zatvorenim ulazima. Isprobaj ih u Copy tradingu."))


def _positions(tcon, viewer_buy):
    rows = []
    for (pid, tok, sym, ts, mode, st, why, sin, sback, q, ql, closed) in tcon.execute(
            "SELECT id, token, symbol, opened_ts, mode, status, reason, sol_in, sol_back, qty_raw, qty_left, closed_ts "
            "FROM positions ORDER BY id DESC LIMIT 60"):
        kind = badge("PRAVO", "good") if mode == "live" else badge("probno")
        stb = {"open": badge("otvoreno", "warn"), "closed": badge("zatvoreno"), "blocked": badge("preskočeno"),
               "failed": badge("greška", "bad")}.get(st, esc(st))
        pnl = (sback or 0) - (sin or 0) if st == "closed" else None
        left = f"{ql / q:.0%}" if q else "–"
        buy = (f'<a href="https://jup.ag/swap/SOL-{quote(tok)}" target=_blank rel=noopener>Kupi i ti ↗</a>'
               if viewer_buy and st == "open" else "")
        rows.append([ago(ts), tlink(tok, sym), kind, stb, num(sin, "{:.3f}"), num(sback, "{:.4f}"), left,
                     signed(pnl, "{:+.4f}"), (esc(why or ""), "", "wrap"), buy])
    return ('<h2 id=pozicije>Pozicije</h2>' + table(
        ["Kada", "Token", "Vrsta", "Status", ("Uloženo SOL", "n"), ("Vraćeno SOL", "n"), ("Još drži", "n"),
         ("Zarada SOL", "n"), ("Razlog", "wrap"), ""], rows, tid="ptpos",
        empty="Još nema kupnji. Pojave se čim netko koga bot prati objavi poziv ili kupi token."))


def _orders(tcon):
    rows = []
    for ts, tok, side, mode, st, cost, err, sig in tcon.execute(
            "SELECT o.ts, o.token, o.side, o.mode, o.status, o.cost_pct, o.error, o.signature FROM orders o "
            "ORDER BY o.id DESC LIMIT 40"):
        link = f'<a href="https://solscan.io/tx/{esc(sig)}" target=_blank rel=noopener>Solscan ↗</a>' if sig else ""
        rows.append([ago(ts), tlink(tok), "kupnja" if side == "buy" else "prodaja",
                     badge("PRAVO", "good") if mode == "live" else badge("probno"), esc(st), num(cost, "{:.2f}%"),
                     (esc(err or ""), "", "wrap"), link])
    return ('<details><summary>Svi nalozi (zadnjih 40)</summary>' + table(
        ["Kada", "Token", "Strana", "Vrsta", "Status", ("Trošak swapa", "n"), ("Greška", "wrap"), "Transakcija"], rows,
        tid="ptord", empty="Još nema naloga.") + '</details>')


def _invites(tcon):
    inv = {u.lower() for u in settings.invited(tcon)}
    boxes = "".join(f'<label style="display:block;margin:4px 0"><input type=checkbox name=u value="{esc(u)}"'
                    f'{" checked" if u.lower() in inv else ""}> {esc(u)}</label>'
                    for u in store.users() if not settings.is_owner(u))
    return ('<h2 id=pozivnice>Tko još vidi ovu stranicu</h2><form method=post action=/pravi-trade/invite class=card>'
            '<p class=mut>Pozvani igrači vide stanje, pozicije i koga bot prati. Ne mogu ništa mijenjati ni trošiti tvoj '
            'novac; gumb „Kupi i ti” im otvara Jupiter da kupe istim tokenom iz <b>svog</b> walleta.</p>'
            f'{boxes or "<p>Nema drugih igrača.</p>"}<button>Spremi tko vidi</button></form>')


def page(qs, user):
    tcon = _tcon()
    try:
        if not settings.can_view(tcon, user):
            return ("Pravi trade", '<h1>Pravi trade</h1><div class=card>Ova stranica je samo za pozvane. '
                    'Ako želiš pristup, javi se vlasniku aplikacije.</div>')
        owner = settings.is_owner(user)
        cfg = _cfg(tcon)
        msg = ""
        if qs.get("err"):
            msg = f'<div class=card style="border-color:var(--bad)"><b class=neg>Nije prošlo:</b> {esc(qs["err"])}</div>'
        elif qs.get("ok"):
            msg = f'<div class=card style="border-color:var(--good)">{esc(qs["ok"])}</div>'
        con = store.connect()
        try:
            copy.ensure(con)
            b = ['<h1>Pravi trade</h1><p class=lead>Bot kupuje i prodaje <b>pravim SOL-om</b> iz zasebnog walleta, '
                 'samo kad netko koga ovdje odabereš objavi poziv (influencer) ili kupi token (wallet). '
                 'Sve unutar limita ispod.</p>', msg, _status(cfg, owner), _today(tcon, cfg),
                 _follows(con, owner), _positions(tcon, not owner), _orders(tcon), _limits(cfg, owner),
                 _candidates(con, owner)]
        finally:
            con.close()
        if owner:
            b.append(_invites(tcon))
        b.append('<h3>Kako je zaštićeno</h3><ul class=mut>'
                 '<li>Pravi novac ide samo kad je prekidač uključen <b>i</b> u Renderu stoje ključ i TRADE_LIVE=1. '
                 'Ključ nikad nije u kodu ni na ovoj stranici.</li>'
                 '<li>U walletu drži samo iznos kojim bot smije trgovati.</li>'
                 '<li>Dnevni limit potrošnje i dnevni gubitak zaustavljaju nove kupnje do ponoći.</li>'
                 '<li>Swap se ne radi ako je trošak (klizanje + naknada) veći od limita.</li>'
                 '<li>Ulazi se samo dok je signal svjež (do 3 min nakon demo ulaza); rugani tokeni, lažni poolovi i '
                 'premala likvidnost se preskaču.</li>'
                 '<li>Prekidač mijenja samo vlasnik; pozvani samo gledaju.</li></ul>')
        return "Pravi trade", "".join(b)
    finally:
        tcon.close()


def post(path, form, user):
    from urllib.parse import quote as qq
    tcon = _tcon()
    try:
        if not settings.is_owner(user):
            return f"{BACK}?err={qq('samo vlasnik može mijenjati pravi trade')}"
        if path == "/pravi-trade/switch":
            on = form.get("on") == "1"
            settings.put(tcon, "on", on, user)
            print(f"pravi trade: {user} je {'UKLJUČIO' if on else 'isključio'} prekidač", flush=True)
            return f"{BACK}?ok={qq('Pravi trade je uključen.' if on else 'Pravi trade je isključen: nove kupnje staju.')}"
        if path == "/pravi-trade/sellall":
            settings.put(tcon, "on", False, user)
            settings.put(tcon, "sell_all", int(time.time()), user)
            print(f"pravi trade: {user} je kliknuo Prodaj sve", flush=True)
            return f"{BACK}?ok={qq('Isključeno. Sve otvorene pozicije se prodaju (pokušava svakih 30 s dok ne uspije).')}"
        if path == "/pravi-trade/limits":
            for k, v in settings.parse_limits(form).items():
                settings.put(tcon, k, v, user)
            settings.put(tcon, "follow_paper", form.get("follow_paper") == "1", user)
            return f"{BACK}?ok={qq('Limiti spremljeni.')}#limiti"
        if path == "/pravi-trade/invite":
            names = set(form.get("u_list") or [])
            known = {u.lower(): u for u in store.users()}
            settings.put(tcon, "invited", sorted(known[n.lower()] for n in names if n.lower() in known), user)
            return f"{BACK}?ok={qq('Spremljeno tko vidi stranicu.')}#pozivnice"
        con = store.connect()
        try:
            _league_account(con)
            if path == "/pravi-trade/follow":
                kind = form.get("kind", "")
                target = (form.get("target") or "").strip().lstrip("@")
                if kind == "wallet" and target not in _live_wallets():
                    raise ValueError("ovaj wallet ne pratimo uživo (Helius), pa bot ne bi vidio njegove kupnje na vrijeme. "
                                     "Odaberi wallet s oznakom ⚡ uživo u Copy trading → Walleti ili iz tablice ispod")
                copy.follow(con, settings.LEAGUE_USER, kind, target, form.get("label", ""), 25,
                            form.get("per_day") or 5, form.get("exit", ""), form.get("tp", ""), form.get("sl", ""))
                return f"{BACK}?ok={qq(f'Bot prati {target}.')}#pratim"
            if path == "/pravi-trade/copyfollow":
                src = next((f for f in copy.follows(con, active=None) if f["id"] == int(form.get("id") or 0)), None)
                if not src:
                    raise ValueError("to praćenje ne postoji")
                ex = src["exit"]
                copy.follow(con, settings.LEAGUE_USER, src["kind"], src["target"], src["label"], 25, src["per_day"],
                            ex.get("mode", ""), ex.get("tp", ""), ex.get("sl", ""))
                who = src["label"] or src["target"]
                return f"{BACK}?ok={qq(f'Bot prati {who}.')}#pratim"
            if path == "/pravi-trade/stop":
                copy.unfollow(con, settings.LEAGUE_USER, int(form.get("id") or 0))
                return f"{BACK}?ok={qq('Praćenje zaustavljeno. Otvorene pozicije se prodaju po svom pravilu izlaza.')}#pratim"
        finally:
            con.close()
        return BACK
    except (ValueError, sqlite3.OperationalError) as e:
        return f"{BACK}?err={qq(str(e))}"
    finally:
        tcon.close()


_VIEW = {"ts": 0, "names": set()}


def can_view_cached(user):
    """For the menu cookie on every page: owner + invited, the invite list re-read at most every 30 s."""
    if not user:
        return False
    if settings.is_owner(user):
        return True
    if time.time() - _VIEW["ts"] > 30:
        try:
            con = settings.connect()
            try:
                _VIEW["names"] = {u.lower() for u in settings.invited(con)}
            finally:
                con.close()
        except sqlite3.Error:
            pass
        _VIEW["ts"] = time.time()
    return user.lower() in _VIEW["names"]
