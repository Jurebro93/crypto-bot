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
from trade import executor, pumpportal, settings, wallet
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
        items += f"<li>SimianX signali: <b>{'uključeni' if cfg.get('simianx') else 'isključeni'}</b></li>"
        return f"<h2 id=limiti>Limiti</h2><ul>{items}</ul>"
    fields = "".join(f'<label style="display:block;margin:6px 0">{esc(lab)} <input name={k} value="{cfg.get(k, "")}" '
                     f'inputmode=decimal style="width:90px"></label>' for k, (lab, *_rest) in settings.LIMITS.items())
    paper = (f'<label style="display:block;margin:6px 0"><input type=checkbox name=follow_paper value=1'
             f'{" checked" if cfg.get("follow_paper") else ""}> prati i demo strategiju bota (osim KOL-ova i walleta ispod)</label>')
    pump = (f'<label style="display:block;margin:6px 0"><input type=checkbox name=use_pump value=1'
            f'{" checked" if cfg.get("use_pump", True) else ""}> ako Jupiter ne prođe, probaj preko PumpPortala '
            f'(naknada {pumpportal.FEE_PCT}%)</label>')
    simx = (f'<label style="display:block;margin:6px 0"><input type=checkbox name=simianx value=1'
            f'{" checked" if cfg.get("simianx") else ""}> kupuj i na SimianX signale „kupi” (long), s njihovim stopom i '
            f'ciljem; uključi tek kad se pokažu dobri u demu</label>')
    return (f'<h2 id=limiti>Limiti</h2><form method=post action=/pravi-trade/limits class=card>{fields}{paper}{pump}{simx}'
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


def _sell_btns(pid, pending):
    if pending is not None:
        return badge(f"prodaja {float(pending):.0%} u tijeku", "warn")
    return "".join(f'<form method=post action=/pravi-trade/sell style="display:inline;margin:0 4px 0 0" onsubmit="return '
                   f'confirm(\'Prodati {lab} ove pozicije odmah?\')"><input type=hidden name=id value={pid}>'
                   f'<input type=hidden name=frac value={fr}><button>Prodaj {lab}</button></form>'
                   for fr, lab in (("0.5", "50%"), ("1", "sve")))


def _positions(tcon, viewer_buy, owner=False, pending=None):
    pending = pending or {}
    rows = []
    for (pid, tok, sym, ts, mode, st, why, sin, sback, q, ql, closed, fees) in tcon.execute(
            "SELECT id, token, symbol, opened_ts, mode, status, reason, sol_in, sol_back, qty_raw, qty_left, closed_ts, "
            "COALESCE(fees_sol,0) FROM positions ORDER BY id DESC LIMIT 60"):
        kind = badge("PRAVO", "good") if mode == "live" else badge("probno")
        stb = {"open": badge("otvoreno", "warn"), "closed": badge("zatvoreno"), "blocked": badge("preskočeno"),
               "failed": badge("greška", "bad")}.get(st, esc(st))
        pnl = (sback or 0) - (sin or 0) - fees if st == "closed" else None
        left = f"{ql / q:.0%}" if q else "–"
        buy = (f'<a href="https://jup.ag/swap/SOL-{quote(tok)}" target=_blank rel=noopener>Kupi i ti ↗</a>'
               if viewer_buy and st == "open" else "")
        if owner and st == "open":
            buy = _sell_btns(pid, pending.get(str(pid)))
        rows.append([ago(ts), tlink(tok, sym), kind, stb, num(sin, "{:.3f}"), num(sback, "{:.4f}"), left,
                     num(fees if mode == "live" else None, "{:.5f}"), signed(pnl, "{:+.4f}"), (esc(why or ""), "", "wrap"),
                     buy])
    return ('<h2 id=pozicije>Pozicije</h2><p class=mut>Zarada = vraćeno − uloženo − mrežne naknade. Jupiterova '
            'naknada (0,05–0,1%) je već u iznosima; mrežne naknade su potpis, prioritet i depozit za novi token račun '
            '(~0,002 SOL), koji se vrati kad se pozicija proda do kraja.</p>' + table(
        ["Kada", "Token", "Vrsta", "Status", ("Uloženo SOL", "n"), ("Vraćeno SOL", "n"), ("Još drži", "n"),
         ("Mrežne naknade SOL", "n"), ("Zarada SOL", "n"), ("Razlog", "wrap"), ""], rows, tid="ptpos",
        empty="Još nema kupnji. Pojave se čim netko koga bot prati objavi poziv ili kupi token."))


def _orders(tcon):
    rows = []
    sides = {"buy": "kupnja", "sell": "prodaja", "rent": "depozit natrag"}
    for ts, tok, side, mode, st, cost, err, sig, route, fee in tcon.execute(
            "SELECT o.ts, o.token, o.side, o.mode, o.status, o.cost_pct, o.error, o.signature, o.route, o.fee_lamports "
            "FROM orders o ORDER BY o.id DESC LIMIT 40"):
        link = f'<a href="https://solscan.io/tx/{esc(sig)}" target=_blank rel=noopener>Solscan ↗</a>' if sig else ""
        rows.append([ago(ts), tlink(tok), sides.get(side, side),
                     badge("PRAVO", "good") if mode == "live" else badge("probno"), esc(st),
                     esc(executor.ROUTE_HR.get(route, route or "")), num(cost, "{:.2f}%"),
                     num(fee / executor.LAMPORTS if fee is not None else None, "{:+.5f}"), (esc(err or ""), "", "wrap"), link])
    return ('<details><summary>Svi nalozi (zadnjih 40)</summary>' + table(
        ["Kada", "Token", "Strana", "Vrsta", "Status", "Ruta", ("Trošak swapa", "n"), ("Mrežne naknade SOL", "n"),
         ("Greška", "wrap"), "Transakcija"], rows, tid="ptord", empty="Još nema naloga.") + '</details>')


def _invites(tcon):
    inv = {u.lower() for u in settings.invited(tcon)}
    boxes = "".join(f'<label style="display:block;margin:4px 0"><input type=checkbox name=u value="{esc(u)}"'
                    f'{" checked" if u.lower() in inv else ""}> {esc(u)}</label>'
                    for u in store.users() if not settings.is_owner(u))
    return ('<h2 id=pozivnice>Tko još vidi ovu stranicu</h2><form method=post action=/pravi-trade/invite class=card>'
            '<p class=mut>Pozvani igrači vide stanje, pozicije i koga bot prati. Ne mogu ništa mijenjati ni trošiti tvoj '
            'novac; gumb „Kupi i ti” im otvara Jupiter da kupe istim tokenom iz <b>svog</b> walleta.</p>'
            f'{boxes or "<p>Nema drugih igrača.</p>"}<button>Spremi tko vidi</button></form>')


def _warnings(tcon, cfg, con):
    """Everything that would stop or hurt a trade right now, in plain words (Nicholas 3.11.: network congestion,
    too little SOL to sell, anything else worth knowing)."""
    now = time.time()
    w = []   # (level, text)
    live_ready = executor.armed()
    beat = cfg.get("heartbeat") or 0
    if not beat:
        w.append(("warn", "Trade proces se još nije javio (prvih minutu nakon pokretanja to je normalno)."))
    elif now - beat > 180:
        w.append(("bad", f"Trade proces ne radi već {int((now - beat) // 60)} min: nove kupnje i prodaje stoje. "
                         "Provjeri Render logove (run_trade.py)."))
    if os.path.exists(executor.STOP_FILE):
        w.append(("bad", "Uključen je kill switch (datoteka trade/STOP): nove kupnje su zaustavljene."))
    n_open_live = tcon.execute("SELECT COUNT(*) FROM positions WHERE mode='live' AND status='open'").fetchone()[0]
    if live_ready:
        bal = _balance(wallet.address())
        if bal is not None:
            reserve = executor.reserve_sol(cfg, n_open_live)
            need = cfg["size_sol"] + executor.BUY_OVERHEAD_SOL + executor.reserve_sol(cfg, n_open_live + 1)
            if bal < reserve:
                w.append(("bad", f"Opasno malo SOL-a: {bal:.4f}. Za prodaju {n_open_live} otvorenih pozicija treba "
                                 f"barem {reserve:.4f} SOL za mrežne naknade. Uplati SOL u wallet."))
            elif bal < need:
                w.append(("warn", f"Premalo SOL-a za novu kupnju: stanje {bal:.4f}, treba {need:.4f} (ulog "
                                  f"{cfg['size_sol']:g} + naknade i depozit {executor.BUY_OVERHEAD_SOL:g} + rezerva za "
                                  f"prodaju {executor.reserve_sol(cfg, n_open_live + 1):.4f}). Bot neće kupovati, "
                                  "prodaje rade."))
    mode = "live" if executor.is_live(cfg) else "dry"
    start = executor._day_start(now)
    spent = tcon.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE mode=? AND opened_ts>=? AND status IN "
                         "('open','closed')", (mode, start)).fetchone()[0]
    if spent >= cfg["max_sol_per_day"] - 1e-9:
        w.append(("warn", f"Dnevni limit potrošnje je dosegnut ({spent:.3f} SOL): nove kupnje tek nakon ponoći (UTC)."))
    if executor.day_pnl(tcon, now, mode) <= -cfg["max_loss_day"]:
        w.append(("bad", f"Dnevni gubitak je dosegnuo -{cfg['max_loss_day']:g} SOL: nove kupnje stoje do ponoći (UTC)."))
    recent = tcon.execute("SELECT code, error, prio_lamports, status FROM orders WHERE ts>=? ORDER BY id DESC LIMIT 30",
                          (now - 1800,)).fetchall()
    landed_fail = sum(1 for c, *_ in recent if c in (-1000, -1005, -1006, -2000))
    prio = [p for _, _, p, _ in recent if p]
    if landed_fail >= 2:
        w.append(("warn", f"Mreža je zagušena: {landed_fail} transakcija u zadnjih 30 min nije stiglo u blok. Bot "
                          "ponavlja automatski, ali ulazi mogu kasniti."))
    if prio and max(prio[:5]) >= 1_000_000:
        p = max(prio[:5]) / executor.LAMPORTS
        w.append(("warn", f"Mreža je zagušena: naknada za prioritet je sad oko {p:.4f} SOL po swapu, to je "
                          f"{100 * p / cfg['size_sol']:.1f}% uloga od {cfg['size_sol']:g} SOL."))
    if any(c == 2 for c, *_ in recent):
        w.append(("bad", "Jupiter javlja da wallet nema dovoljno SOL-a za mrežnu naknadu. Uplati malo SOL-a."))
    if any("429" in (e or "") or "HTTPError" in (e or "") for _, e, _, _ in recent):
        w.append(("warn", "Jupiter je odbio dio zahtjeva (previše upita bez ključa). Besplatan JUP_API_KEY s "
                          "portal.jup.ag u Renderu to rješava."))
    stuck = []
    for pid, sym, tok in tcon.execute("SELECT id, symbol, token FROM positions WHERE status='open'").fetchall():
        last = [r[0] for r in tcon.execute("SELECT status FROM orders WHERE position_id=? AND side='sell' ORDER BY id "
                                           "DESC LIMIT 3", (pid,))]
        if len(last) == 3 and all(x == "failed" for x in last):
            stuck.append(sym or tok[:6])
    if stuck:
        w.append(("bad", f"Ne može se prodati: {', '.join(stuck)}. Zadnja 3 pokušaja nisu prošla (moguće nema "
                         "likvidnosti ili je rug). Bot pokušava i dalje, najviše svakih 10 min."))
    if cfg["size_sol"] < 0.03:
        w.append(("warn", f"Ulog {cfg['size_sol']:g} SOL je malen: mrežne naknade i depozit (~0,003 SOL po kupnji, "
                          "depozit se vrati) su velik dio uloga."))
    if not copy.follows(con, settings.LEAGUE_USER) and not cfg.get("follow_paper") and not cfg.get("simianx"):
        w.append(("warn", "Bot nikoga ne prati: neće ništa kupiti dok ne dodaš influencera ili wallet."))
    if not w:
        return '<div class=card style="border-color:var(--good)">✅ Nema upozorenja.</div>'
    color = {"bad": "var(--bad)", "warn": "var(--warn)"}
    return "".join(f'<div class=card style="border-left:4px solid {color[lv]}">{"⛔" if lv == "bad" else "⚠️"} '
                   f'{esc(t)}</div>' for lv, t in w)


def _manual_buy(cfg):
    return ('<h2 id=rucno>Kupi ručno</h2><form method=post action=/pravi-trade/buy class=card onsubmit="return confirm('
            '\'Kupiti ovaj token pravim novcem (ako je prekidač uključen)?\')">'
            '<input name=token placeholder="adresa tokena ili DexScreener link" size=34 required style="max-width:100%"> '
            f'<label>SOL <input name=sol value="{cfg["size_sol"]:g}" inputmode=decimal style="width:70px"></label> '
            '<label>izlaz <select name=exit><option value=smart>Smart sell</option><option value=tpsl>moj TP/SL</option>'
            '<option value=manual>prodajem sam</option></select></label> '
            '<input name=tp placeholder="TP npr. 100%" size=11> <input name=sl placeholder="SL npr. -30%" size=11> '
            '<button>Kupi</button><p class=mut>Prolazi iste provjere i limite kao automatske kupnje (rug, likvidnost, '
            'dnevni limit, rezerva za prodaju).</p></form>')


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
                 'Sve unutar limita ispod.</p>', msg, _status(cfg, owner), _warnings(tcon, cfg, con), _today(tcon, cfg),
                 _follows(con, owner), _positions(tcon, not owner, owner, cfg.get("sell_req")),
                 _manual_buy(cfg) if owner else "", _orders(tcon), _limits(cfg, owner), _candidates(con, owner)]
        finally:
            con.close()
        if owner:
            b.append(_invites(tcon))
        b.append('<h3>Kako je zaštićeno</h3><ul class=mut>'
                 '<li>Pravi novac ide samo kad je prekidač uključen <b>i</b> u Renderu stoje ključ i TRADE_LIVE=1. '
                 'Ključ nikad nije u kodu ni na ovoj stranici.</li>'
                 '<li>U walletu drži samo iznos kojim bot smije trgovati.</li>'
                 '<li>Dnevni limit potrošnje i dnevni gubitak zaustavljaju nove kupnje do ponoći.</li>'
                 f'<li>U walletu uvijek ostaje barem {executor.RESERVE_FLOOR_SOL:g} SOL (i {executor.SELL_COST_SOL:g} SOL '
                 'po otvorenoj poziciji) za mrežne naknade prodaje, pa kupnja koja bi pojela taj minimum ne prolazi.</li>'
                 '<li>Swap se ne radi ako je trošak (klizanje + naknada) veći od limita.</li>'
                 '<li>Rute redom: Jupiter → Jupiter Ultra → PumpPortal (ako je uključen). Na sljedeću rutu ide se samo '
                 'kad swap sigurno nije prošao; ako Jupiter ne odgovori, prvo se provjeri wallet, da se ništa ne kupi dvaput.</li>'
                 '<li>Neuspjela prodaja se ponavlja: nakon 5 s, 10 s, 20 s… najviše svakih 10 min, dok ne prođe.</li>'
                 '<li>Brzina: poziv ili kupnju praćenog vidimo u sekundama (⚡ uživo), demo ulaz nastane u idućih ~20 s, '
                 'pravi swap 5 s nakon toga i traje 1–5 s. Sve se odmah vidi u tablicama ovdje.</li>'
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
            settings.put(tcon, "use_pump", form.get("use_pump") == "1", user)
            settings.put(tcon, "simianx", form.get("simianx") == "1", user)
            return f"{BACK}?ok={qq('Limiti spremljeni.')}#limiti"
        if path == "/pravi-trade/sell":
            pid, frac = str(int(form.get("id") or 0)), float(form.get("frac") or 1)
            if not 0 < frac <= 1:
                raise ValueError("udio mora biti između 0 i 100%")
            if not tcon.execute("SELECT 1 FROM positions WHERE id=? AND status='open'", (int(pid),)).fetchone():
                raise ValueError("ta pozicija nije otvorena")
            req = dict(settings.raw(tcon).get("sell_req") or {})
            req[pid] = frac
            settings.put(tcon, "sell_req", req, user)
            return f"{BACK}?ok={qq(f'Prodaja {frac:.0%} poslana, za nekoliko sekundi je u tablici.')}#pozicije"
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
            if path == "/pravi-trade/buy":
                return _post_buy(con, tcon, form, user)
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


def _post_buy(con, tcon, form, user):
    """Manual buy: a demo trade on the real-trade account (same rug/liquidity checks as Natjecanje), its own SOL
    stake for the mirror, and its exit rule; run_trade.py turns it into the real swap within the limits."""
    from urllib.parse import quote as qq
    from league import auto
    from rugfilter import collapse
    from ui import data, real
    from ui.league import MINT, _symbol, market
    token = (form.get("token") or "").strip()
    if not MINT.fullmatch(token):
        token = real.resolve(token)[0]
    sol = float((form.get("sol") or "0").replace(",", "."))
    lab, _typ, lo, hi = settings.LIMITS["size_sol"]
    if not lo <= sol <= hi:
        raise ValueError(f"SOL mora biti između {lo:g} i {hi:g}")
    live = market({token})
    if token not in live:
        raise ValueError("nema cijene za tu adresu (je li to adresa tokena, a ne walleta?)")
    price, liq, _, mcap = live[token]
    col = collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
    if col:
        raise ValueError(f"token je rugan ({col['text']}), kupnja je zaključana")
    sym = _symbol(token)
    tid = store.buy(con, settings.LEAGUE_USER, token, sym, 25, price, liq, "ručno (pravi trade)", None, mcap)
    ex = form.get("exit") or "smart"
    if ex == "smart":
        auto.set_auto(con, settings.LEAGUE_USER, tid, "smart")
    elif ex == "tpsl":
        auto.set_auto(con, settings.LEAGUE_USER, tid, "tpsl", form.get("tp", ""), form.get("sl", ""))
    sizes = dict(settings.raw(tcon).get("manual_size") or {})
    sizes[str(tid)] = sol
    settings.put(tcon, "manual_size", dict(list(sizes.items())[-200:]), user)
    return f"{BACK}?ok={qq(f'Kupnja {sym or token[:6]} za {sol:g} SOL poslana, za nekoliko sekundi je u tablici.')}#pozicije"


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
