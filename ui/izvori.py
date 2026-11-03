"""/izvori: social call sources besides X - Telegram channels, KOL wallets on chain, the live convergence of
several sources on one token, and which paid sources are switched on."""
import json
import os
import sqlite3
import time

from ui.html import ago, badge, esc, num, table, tdesc, tlink
from ui.kol import klink

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ro(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _stat(v, label):
    return f"<div class=stat><div class=v>{esc(v)}</div><div class=l>{esc(label)}</div></div>"


VIA = {"x": "X objave i profili", "kolscan": "KOLscan", "solanatracker": "Solana Tracker", "tgstat": "TGStat",
       "channels.txt": "ručni popis", "telethon": "Telegram račun", "fomo": "FOMO"}


def via_label(v):
    v = v or ""
    return f"kanal @{v[6:]}" if v.startswith("kanal:") else VIA.get(v, v)


STATUS = {"active": ("aktivan", "good"), "quiet": ("tih", ""), "slow": ("slab, rjeđe", "warn"),
          "candidate": ("kandidat", ""), "dead": ("nije javan", "bad")}


def paid_section():
    """Free and paid sources with which keys are set: shown on /usage (admins only)."""
    kcon = _ro("kol.db")
    try:
        return ("<h2 id=placeni>Besplatni i plaćeni izvori</h2>" + tdesc(
            "Kombiniramo oboje: besplatni daju širinu, plaćeni brzinu i doseg. Plaćeni se uključuju samim postavljanjem "
            "ključa na Renderu.") + paid_sources(kcon))
    finally:
        if kcon:
            kcon.close()


def paid_sources(kcon):
    """Free and paid sources side by side, what each adds and whether it is on."""
    on = lambda k: bool(os.environ.get(k))
    hook = json.loads((_q(kcon, "SELECT value FROM kv WHERE key='chain_hook'") or [("{}",)])[0][0])
    rows = [
        ["Telegram web prikaz (t.me/s)", badge("besplatno", "good"), badge("uključeno", "good"),
         "Javni kanali, 30 s - 5 min kašnjenja, otkrivanje iz X-a, KOL lista i prosljeđivanja"],
        ["TGStat Search API", badge("plaćeno"), badge("uključeno", "good") if on("TGSTAT_TOKEN") else badge("čeka TGSTAT_TOKEN", "warn"),
         "Pretraga svih indeksiranih kanala po CA: tko je zvao prvi, novi kanali koje ne znamo"],
        ["Telegram račun (Telethon)", badge("broj mobitela"), badge("uključeno", "good") if on("TG_SESSION") else badge("čeka TG_SESSION", "warn"),
         "Poruke ispod 1 s i privatne grupe u kojima je račun"],
        ["KOLscan lista", badge("besplatno", "good"), badge("uključeno", "good"), "KOL novčanici s X i Telegram imenom"],
        ["Solana Tracker KOL API", badge("plaćeno"), badge("uključeno", "good") if on("SOLANATRACKER_API_KEY") else badge("čeka SOLANATRACKER_API_KEY", "warn"),
         "Svi praćeni KOL novčanici s PnL-om, ne samo dnevni top"],
        ["Helius webhook KOL novčanika", badge("Helius krediti"),
         badge(f"prati {len(hook.get('wallets', []))}", "good") if hook.get("id") else badge("čeka prvi krug", "warn"),
         "Kupnje i prodaje KOL novčanika u sekundi, prije objave"],
        ["FOMO top traderi (Apify)", badge("plaćeno"), badge("uključeno", "good") if on("APIFY_TOKEN") else badge("nema APIFY_TOKEN", "bad"),
         "Najbolji traderi koje FOMO korisnici kopiraju, tjedno; njihove kupnje prati webhook"],
        ["pump.fun live i KOL boardovi (Apify)", badge("plaćeno"), badge("uključeno", "good") if on("APIFY_TOKEN") else badge("nema APIFY_TOKEN", "bad"),
         "Tokeni koji se upravo streamaju i koje trguju poznati KOL novčanici"],
    ]
    return table(["Izvor", "Cijena", "Stanje", "Što daje"], rows)


def page(qs):
    tcon, kcon = _ro("tg.db"), _ro("kol.db")
    now = time.time()
    b = ["<h1>Društveni izvori kolova</h1>" + tdesc(
        "Osim X-a bot prati javne Telegram call kanale i KOL novčanike na lancu. Kad više dobrih izvora zove isti token "
        "u kratkom vremenu, to je konvergencija: tada bot ulazi malim demo ulogom prije gomile. Sve se otkriva i mjeri "
        "samo; Telegram kanal dobiva ocjenu istim pravilima kao KOL na X-u.")]
    try:
        st = dict(_q(tcon, "SELECT status, COUNT(*) FROM channels GROUP BY status"))
        n24 = (_q(tcon, "SELECT COUNT(*) FROM posts WHERE cas != '' AND seen_ts >= ?", (now - 86400,)) or [(0,)])[0][0]
        lag = [l for l, in _q(tcon, "SELECT lag_s FROM channels WHERE lag_s IS NOT NULL AND status='active'")]
        lag_med = sorted(lag)[len(lag) // 2] if lag else None
        n_ids = (_q(kcon, "SELECT COUNT(*) FROM kol_ids") or [(0,)])[0][0]
        buys = (_q(kcon, "SELECT COUNT(*) FROM calls WHERE kind='buy' AND ts >= ?", (now - 86400,)) or [(0,)])[0][0]
        conv = _q(kcon, """SELECT token, ts, first_ts, score, n_x, n_tg, n_chain, n_other, platforms, handles, kol_selling
                           FROM converge WHERE ts >= ? ORDER BY score DESC""", (now - 6 * 3600,))
        b.append("<div class=grid>" + "".join([
            _stat(st.get("active", 0), "aktivnih Telegram kanala"), _stat(st.get("candidate", 0), "kandidata"),
            _stat(n24, "Telegram objava s CA (24 h)"),
            _stat(f"{lag_med:.0f} s" if lag_med is not None else "–", "kašnjenje čitanja (medijan)"),
            _stat(n_ids, "KOL novčanika s imenom"), _stat(buys, "kupnji KOL novčanika (24 h)"),
            _stat(len(conv), "konvergencija (6 h)")]) + "</div>")

        b.append("<h2 id=konv>Konvergencija izvora</h2>" + tdesc(
            "Tokeni koje je u 30 min zvalo više izvora. Skor 0-100: dobri KOL-ovi na X-u i Telegramu, KOL novčanici koji "
            "kupuju, bonus za više platformi; manji ako KOL novčanik već prodaje ili izgleda kao plaćena promocija. "
            "Iznad praga demo tradinga bot ulazi (stranica Demo trading)."))
        syms = dict(_q(kcon, "SELECT token, symbol FROM tokens"))
        rows = []
        for tok, ts, first, sc, nx, ntg, nch, no, plats, hs, sell in conv:
            hl = json.loads(hs or "[]")
            rows.append([tlink(tok, syms.get(tok)), num(sc), esc(" + ".join(json.loads(plats or "[]"))),
                         num(nx), num(ntg), num(nch), num(no), ago(first),
                         ", ".join(klink(h) for h in hl[:6]) + (" " + badge("KOL prodaje", "bad") if sell else "")])
        b.append(table(["Token", ("Skor", "n"), "Platforme", ("X", "n"), ("TG", "n"), ("Novčanici", "n"),
                        ("Ostali", "n"), "Prvi poziv", "Tko"], rows, empty="Još nema konvergencija u zadnjih 6 h."))

        b.append("<h2 id=kanali>Telegram kanali</h2>" + tdesc(
            "Kanali koje je bot pronašao (linkovi u X objavama i profilima, KOL liste, prosljeđivanja iz drugih kanala, "
            "TGStat). Aktivan = javno objavljuje adrese tokena; čita se svakih 30 s kad je vruć, inače svakih 5 min. "
            "Kanal s 12+ izmjerenih poziva i ocjenom ispod 25 čita se rjeđe."))
        scores = {h[3:]: (sc, json.loads(stt or "{}")) for h, sc, stt in
                  _q(kcon, "SELECT handle, score, stats FROM kols WHERE handle LIKE 'tg:%'")}
        rows = []
        for name, title, subs, status, via, n_posts, n_ca, last_ca, lag_s in _q(tcon, """SELECT name, title, subs,
                status, found_via, n_posts, n_ca, last_ca_ts, lag_s FROM channels WHERE status != 'dead'
                ORDER BY status = 'active' DESC, COALESCE(last_ca_ts, 0) DESC"""):
            sc, s = scores.get(name, (None, {}))
            lab, cls = STATUS.get(status, (status, ""))
            rows.append([klink("tg:" + name) + (f" <span class=mut>{esc(title or '')}</span>" if title else ""),
                         badge(lab, cls), num(subs), num(sc, "{:.0f}"), num(s.get("measured")),
                         (f"{s['hit_rate']:.0%}" if s.get("hit_rate") is not None else "–", s.get("hit_rate") or -1, "n"),
                         num(n_ca), ago(last_ca), num(lag_s, "{:.0f} s"), esc(via_label(via))])
        b.append(table(["Kanal", "Stanje", ("Pretplatnika", "n"), ("Ocjena", "n"), ("Izmjereno", "n"),
                        ("Pogodak", "n"), ("Objava s CA", "n"), "Zadnji CA", ("Kašnjenje", "n"), "Pronađen preko"],
                       rows, empty="Još nema kanala: prvo otkrivanje kreće par minuta nakon pokretanja."))

        rows = []
        for ch, post, ts, cas, text, views, fwd in _q(tcon, """SELECT channel, post, ts, cas, text, views, fwd_from
                FROM posts WHERE cas != '' ORDER BY ts DESC LIMIT 40"""):
            rows.append([ago(ts), klink("tg:" + ch), ", ".join(tlink(c, syms.get(c)) for c in cas.split(",")[:3]),
                         num(views), esc((text or "")[:140]) + (" " + badge("proslijeđeno") if fwd else ""),
                         f'<a href="https://t.me/{esc(ch)}/{post}" target=_blank rel=noopener>↗</a>'])
        b.append("<h3>Zadnje Telegram objave s adresom</h3>" + table(
            ["Kada", "Kanal", "Token", ("Pregleda", "n"), "Tekst", ""], rows, empty="Još nema objava."))

        b.append("<h2 id=novcanici>KOL novčanici</h2>" + tdesc(
            "Novčanici KOL-ova s javnim imenom (KOLscan, Solana Tracker) i najbolji FOMO traderi. Helius webhook javlja "
            "svaku njihovu kupnju i prodaju; KOL obično kupi prije objave, pa je to najraniji signal."))
        rows = []
        for w, name, tw, tg, src, pnl, wins, losses, rank in _q(kcon, """SELECT wallet, name, twitter, telegram, source,
                pnl, wins, losses, rank FROM kol_ids ORDER BY source = 'fomo', COALESCE(rank, 999) LIMIT 300"""):
            rows.append([esc(name or "–"), klink(tw) if tw else "–",
                         f'<a href="{esc(tg)}" target=_blank rel=noopener>✈</a>' if tg else "–", esc(src),
                         num(pnl, "{:,.0f}"), f"{wins or 0}/{(wins or 0) + (losses or 0)}" if wins is not None else "–",
                         f'<a href="https://solscan.io/account/{esc(w)}" target=_blank rel=noopener><code>{esc(w[:6])}…</code></a>'])
        b.append(table(["Ime", "X", "TG", "Izvor", ("PnL (izvor)", "n"), "Pobjede", "Novčanik"], rows,
                       empty="Još nema: lista se čita jednom dnevno."))

        # the free/paid sources table (which keys are set on Render) moved to /usage, admins only (3.11.)
    finally:
        for c in (tcon, kcon):
            if c is not None:
                c.close()
    return "Društveni izvori", "".join(b)
