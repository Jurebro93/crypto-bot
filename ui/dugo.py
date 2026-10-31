"""/dugorocno: the safer layer. Older Solana tokens that survived and recover from dips (Fartcoin/Useless style), and
older tokens that fell hard and are waking up. Everything from dugo.db (run_dugo.py)."""
import json
import os
import time

from dugo import score as sc, store
from ui.html import ago, badge, esc, num, signed, table, tdesc, tlink, usd

D = 86400


def _stat(v, label):
    return f"<div class=stat><div class=v>{esc(v)}</div><div class=l>{esc(label)}</div></div>"


def _pct(x):
    return signed(None if x is None else 100 * x, "{:+.0f}%")


def _f(x, fmt="{:.2f}"):
    return num(x, fmt)


def _rows(con, kind, day, n=40):
    return con.execute("""SELECT s.mint, t.symbol, s.score, s.rank, s.price, s.liquidity, s.mcap, s.features, s.why
        FROM snap s JOIN tokens t ON t.mint=s.mint WHERE s.kind=? AND s.day=? ORDER BY s.rank LIMIT ?""",
                       (kind, day, n)).fetchall()


def _book(con):
    rows = con.execute("SELECT * FROM book ORDER BY exit_ts IS NOT NULL, entry_ts DESC").fetchall()
    last = {m: p for m, p in con.execute(
        "SELECT mint, c FROM candles WHERE (mint, day) IN (SELECT mint, MAX(day) FROM candles GROUP BY mint)")}
    sol = store.ref(con, "SOL")
    sol_now = sol[max(sol)] if sol else None
    out, tot, tot_sol, inv = [], 0.0, 0.0, 0.0
    for r in rows:
        px = r["exit_price"] if r["exit_ts"] else last.get(r["mint"])
        se = r["sol_exit"] if r["exit_ts"] else sol_now
        ret = px / r["entry_price"] - 1 if px and r["entry_price"] else None
        sret = se / r["sol_entry"] - 1 if se and r["sol_entry"] else None
        if ret is not None:
            inv += r["usd"]
            tot += r["usd"] * ret
            tot_sol += r["usd"] * (sret or 0)
        out.append([tlink(r["mint"], r["symbol"]), "dugoročni" if r["kind"] == "dugorocni" else "buđenje",
                    (time.strftime("%d.%m.", time.gmtime(r["entry_ts"])), r["entry_ts"], ""), usd(r["usd"]), _pct(ret),
                    _pct(sret), _pct(None if ret is None or sret is None else ret - sret),
                    esc(r["reason"]) if r["exit_ts"] else badge("otvoreno", "good")])
    return out, inv, tot, tot_sol


def _uzori(con, day, cfg_uzori):
    out = []
    for name, m in cfg_uzori.items():
        r = con.execute("SELECT features, mcap, liquidity FROM snap WHERE mint=? AND day=? LIMIT 1", (m, day)).fetchone()
        if not r:
            continue
        f = json.loads(r["features"])
        out.append([tlink(m, name), usd(r["mcap"]), _pct(f.get("pad_od_vrha")),
                    num(f.get("oporavaka"), "{:.0f}"), _pct(f.get("udio_oporavaka")), _f(f.get("korelacija_btc")),
                    _f(f.get("beta_btc")), _pct(f.get("povrat_30d"))])
    return out


def page(qs):
    from dugo import run
    cfg = run.config()
    b = ["<h1>Dugoročni i oživljeni tokeni</h1>" + tdesc(
        "Sigurniji sloj uz lov na nove tokene. Ovdje su samo tokeni koji su preživjeli tjednima ili mjesecima, imaju pravu "
        "likvidnost i ponašaju se kao Fartcoin i Useless: padnu, ali se oporave, zajednica ih i dalje zove, a rastu kad "
        "rastu BTC i SOL. Drugi popis su stariji tokeni koji su jako pali i sada se bude. Popisi se osvježavaju svakih "
        "6 sati, a bot jednom tjedno sam provjeri na povijesti koja mjerila stvarno pomažu i polako prilagodi težine.")]
    con = store.ro()
    if con is None:
        return "Dugoročni", "".join(b) + '<div class=empty>Prvi prolaz još traje (nekoliko minuta nakon pokretanja).</div>'
    try:
        day = con.execute("SELECT MAX(day) FROM snap").fetchone()[0]
        if not day:
            return "Dugoročni", "".join(b) + '<div class=empty>Bot još skuplja dnevne cijene; popis se pojavljuje nakon prvog prolaza.</div>'
        n_tok = con.execute("SELECT COUNT(*) FROM tokens WHERE candles_ts IS NOT NULL").fetchone()[0]
        n_all = con.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
        n_dead = con.execute("SELECT COUNT(*) FROM tokens WHERE status='mrtav'").fetchone()[0]
        dug, bud = _rows(con, "dugorocni", day), _rows(con, "budjenje", day)
        brows, inv, tot, tot_sol = _book(con)
        b.append("<div class=grid>" + "".join([
            _stat(f"{n_all:,}", "tokena provjereno"), _stat(n_tok, "preživjelih s poviješću cijena"),
            _stat(con.execute("SELECT COUNT(*) FROM snap WHERE day=? AND kind='dugorocni'", (day,)).fetchone()[0],
                  "na dugoročnom popisu"),
            _stat(con.execute("SELECT COUNT(*) FROM snap WHERE day=? AND kind='budjenje'", (day,)).fetchone()[0], "se budi"),
            _stat(f"{tot:+,.0f} $" if inv else "–", "demo portfelj"),
            _stat(f"{tot - tot_sol:+,.0f} $" if inv else "–", "bolje/lošije od držanja SOL-a"),
        ]) + "</div>")

        b.append("<h2>Uzori: Fartcoin i Useless</h2>" + tdesc(
            "Kako izgledaju tokeni koje želimo naći. Sličnost uzoru na popisu ispod mjeri koliko je token blizu ovom "
            "profilu (pad od vrha, koliko se puta oporavio, kretanje s BTC-om, volatilnost, likvidnost)."))
        b.append(table(["Token", "Tržišna vrijednost", "Od vrha", "Oporavaka", "Udio oporavaka", "Korelacija s BTC",
                        "Beta BTC", "30 dana"], _uzori(con, day, cfg["uzori"]), empty="Uzori još nemaju povijest."))

        b.append("<h2>Dugoročni kandidati</h2>" + tdesc(
            f"Stariji od {cfg['dugorocni']['min_starost_d']} dana, likvidnost barem "
            f"${cfg['dugorocni']['min_likvidnost'] / 1e3:.0f}k, vrijednost barem ${cfg['dugorocni']['min_mcap'] / 1e6:.0f}M. "
            "Ocjena 0-100 je usporedba s ostalim preživjelima danas: 100 = najbolji na svim mjerilima."))
        rows, mints = [], []
        for m, sym, s, rk, px, liq, mc, fj, why in dug:
            f = json.loads(fj)
            rows.append([num(rk, "{:.0f}"), tlink(m, sym), num(s, "{:.0f}"), _pct(f.get("slicnost_uzoru")),
                         num(f.get("starost_d"), "{:.0f} d"), usd(liq), usd(mc), _pct(f.get("pad_od_vrha")),
                         num(f.get("oporavaka"), "{:.0f}"), _pct(f.get("povrat_30d")), _f(f.get("korelacija_btc")),
                         num(f.get("kol_tjedana_60d"), "{:.0f}"), esc(why)])
            mints.append(m)
        b.append(table(["#", "Token", "Ocjena", "Sličnost uzoru", "Starost", "Likvidnost", "Vrijednost", "Od vrha",
                        "Oporavaka", "30 dana", "Korelacija s BTC", "Tjedana s KOL pozivima", "Zašto"], rows, tid="dug"))

        b.append("<h2>Bude se</h2>" + tdesc(
            f"Stariji od {cfg['budjenje']['min_starost_d']} dana, pali barem {-cfg['budjenje']['max_pad_od_vrha']:.0%} od vrha, "
            f"a od dna u zadnjih 30 dana opet gore barem {cfg['budjenje']['min_od_dna_30d']:.0%}. Rizičnije od dugoročnih: "
            "dio ovoga je samo mrtvi skok."))
        rows = []
        for m, sym, s, rk, px, liq, mc, fj, why in bud:
            f = json.loads(fj)
            rows.append([num(rk, "{:.0f}"), tlink(m, sym), num(s, "{:.0f}"), num(f.get("starost_d"), "{:.0f} d"), usd(liq),
                         usd(mc), _pct(f.get("pad_od_vrha")), _pct(f.get("od_dna_30d")),
                         num(f.get("volumen_trend"), "{:.1f}×"), _pct(f.get("povrat_7d")),
                         num(f.get("kol_7d"), "{:.0f}"), esc(why)])
        b.append(table(["#", "Token", "Ocjena", "Starost", "Likvidnost", "Vrijednost", "Od vrha", "Od dna 30 d",
                        "Volumen tjedan / prije", "7 dana", "KOL pozivi 7 d", "Zašto"], rows, tid="bud"))

        b.append("<h2>Demo dugoročni portfelj</h2>" + tdesc(
            f"Bez pravog novca i odvojeno od demo tradinga. Svakih {cfg['knjiga']['svaki_d']} dana bot uloži "
            f"${cfg['knjiga']['usd']} u prvih {cfg['knjiga']['top']} sa svakog popisa i drži dok token ne ispadne iz prvih 15 "
            f"na {cfg['knjiga']['drzi_izvan_top_d']} dana (buđenje ima i stop na {cfg['knjiga']['stop_budjenje']:.0%}). "
            "Stupac \"Bolje od SOL-a\" kaže je li izbor bio bolji od jednostavnog držanja SOL-a u istom razdoblju."))
        b.append(table(["Token", "Popis", "Ulaz", "Uloženo", "Rezultat", "SOL u isto vrijeme", "Bolje od SOL-a", "Stanje"],
                       brows, empty="Prvi ulazi nakon prvog prolaza."))

        runs = con.execute("SELECT ts, kind, applied, n, before, after, note, weights FROM learn_runs ORDER BY ts DESC LIMIT 6").fetchall()
        lr = [[ago(r["ts"]), "dugoročni" if r["kind"] == "dugorocni" else "buđenje", num(r["n"]),
               badge({1: "primijenjeno", -1: "vraćeno", 0: "bez promjene"}[r["applied"]],
                     {1: "good", -1: "warn", 0: ""}[r["applied"]]), esc(r["note"])] for r in runs]
        b.append("<details><summary>Što je bot naučio i odakle su podaci</summary>" + tdesc(
            "Jednom tjedno bot uzme povijest cijena svih preživjelih i pogleda: da smo prije 30 dana birali po ovim "
            "mjerilima, bi li izbor bio bolji od SOL-a? Težine se pomiču najviše 20% odjednom, samo ako je nova verzija "
            "bolja i u starijoj i u novijoj polovici povijesti, a stara se vraća ako se pokaže boljom.")
                 + table(["Kada", "Popis", "Primjera", "Ishod", "Napomena"], lr, empty="Prvo učenje nakon prvog prolaza.")
                 + _weights(con) + _sources() + "</details>")
        if n_dead:
            b.append(f"<p class=mut>{n_dead} tokena je u međuvremenu umrlo (likvidnost nestala ili pad 70%+ u danu) i "
                     "maknuto je s popisa.</p>")
    finally:
        con.close()
    return "Dugoročni", "".join(b)


def _weights(con):
    from dugo import learn, run
    W = learn.current(run.config())
    rows = []
    for kind, w in W.items():
        for c, v in sorted(w.items(), key=lambda x: -abs(x[1])):
            rows.append(["dugoročni" if kind == "dugorocni" else "buđenje", esc(sc.NAMES.get(c, c)), num(v, "{:+.2f}")])
    return "<h3>Težine sada</h3>" + table(["Popis", "Mjerilo", "Težina"], rows, limit=60)


def _sources():
    on = bool(os.environ.get("BIRDEYE_API_KEY"))
    rows = [["DexScreener", "besplatno", "likvidnost, vrijednost, volumen, kupci/prodavači", badge("uključeno", "good")],
            ["GeckoTerminal", "besplatno", "dnevne cijene do 400 dana unatrag (padovi, oporavci, trend)", badge("uključeno", "good")],
            ["CoinGecko", "besplatno", "cijena BTC-a za usporedbu", badge("uključeno", "good")],
            ["Naši KOL i Telegram podaci", "besplatno", "koliko tjedana i koliko ljudi zove token", badge("uključeno", "good")],
            ["Birdeye", "plaćeno, od oko $39 do $99 mjesečno", "rast broja holdera kroz vrijeme (najbolji znak zajednice)",
             badge("uključeno", "good") if on else badge("nije uključeno")]]
    return "<h3>Izvori</h3>" + table(["Izvor", "Cijena", "Što daje", "Stanje"], rows)
