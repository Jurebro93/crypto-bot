"""/dugorocno: the safer layer. Older Solana tokens that survived and recover from dips (Fartcoin/Useless style), and
older tokens that fell hard and are waking up. Everything from dugo.db (run_dugo.py)."""
import json
import os
import time

from dugo import score as sc, store
from ui.html import ago, badge, esc, num, signed, table, tdesc, tlink, usd

D = 86400
KIND_HR = {"dugorocni": "dugoročni", "budjenje": "buđenje", "jaki": "jaki"}


def _stat(v, label):
    return f"<div class=stat><div class=v>{esc(v)}</div><div class=l>{esc(label)}</div></div>"


def _pct(x):
    return signed(None if x is None else 100 * x, "{:+.0f}%")


def _share(x):
    return num(None if x is None else 100 * x, "{:.0f}%")


def _f(x, fmt="{:.2f}"):
    return num(x, fmt)


def _rows(con, kind, day, n=40):
    return con.execute("""SELECT s.mint, t.symbol, s.score, s.rank, s.price, s.liquidity, s.mcap, s.features, s.why
        FROM snap s JOIN tokens t ON t.mint=s.mint WHERE s.kind=? AND s.day=? AND COALESCE(t.status,'')!='sumnjivo'
        ORDER BY s.rank LIMIT ?""",
                       (kind, day, n)).fetchall()


def _flagged_note(con):
    """Tokens out of the ranking because their pools disagree on the price (audit 4.11. F04, e.g. PYTH)."""
    rows = con.execute("SELECT symbol, mint FROM tokens WHERE status='sumnjivo' ORDER BY symbol LIMIT 12").fetchall()
    if not rows:
        return ""
    names = ", ".join(esc(sym or m[:6]) for sym, m in rows)
    return (f"<p class=mut style='font-size:13px'>⚠️ Izvan rangiranja zbog sukoba cijena između poolova "
            f"({len(rows)}): {names}. Vraćaju se kad se izvori slože.</p>")


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
        out.append([tlink(r["mint"], r["symbol"]), KIND_HR.get(r["kind"], r["kind"]),
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
                    num(f.get("oporavaka"), "{:.0f}"), _share(f.get("udio_oporavaka")), _f(f.get("korelacija_btc")),
                    _f(f.get("beta_btc")), _pct(f.get("povrat_30d"))])
    return out


def page(qs):
    from dugo import run
    cfg = run.config()
    from ui.tokens import switch
    b = ["<h1>Tokeni</h1>" + switch("/dugorocno")]
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
        dug, bud, jak = _rows(con, "dugorocni", day), _rows(con, "budjenje", day), _rows(con, "jaki", day)
        from ui import simianx as sxui
        sx_ops, sx_ins, sx_con = sxui.load()
        brows, inv, tot, tot_sol = _book(con)
        b.append("<h2>Dugoročni kandidati</h2>" + tdesc(
            f"Stariji od {cfg['dugorocni']['min_starost_d']} dana, likvidnost barem "
            f"${cfg['dugorocni']['min_likvidnost'] / 1e3:.0f}k, vrijednost barem ${cfg['dugorocni']['min_mcap'] / 1e6:.0f}M. "
            "Ocjena 0-100 je usporedba s ostalim preživjelima danas: 100 = najbolji na svim mjerilima.")
            + _flagged_note(con))
        rows, mints = [], []
        for m, sym, s, rk, px, liq, mc, fj, why in dug:
            f = json.loads(fj)
            rows.append([num(rk, "{:.0f}"), tlink(m, sym), num(s, "{:.0f}"), _share(f.get("slicnost_uzoru")),
                         num(f.get("starost_d"), "{:.0f} d"), usd(liq), usd(mc), _pct(f.get("pad_od_vrha")),
                         num(f.get("oporavaka"), "{:.0f}"), _pct(f.get("povrat_30d")), _f(f.get("korelacija_btc")),
                         num(f.get("kol_tjedana_60d"), "{:.0f}"), num(f.get("holderi")), _pct(f.get("holderi_30d")),
                         num(f.get("burze_velike"), "{:.0f}"), num(f.get("veliki_kupuju"), "{:.0f}"),
                         sxui.cell(sx_ops, sx_ins, m), esc(why)])
            mints.append(m)
        b.append(table(["#", "Token", "Ocjena", "Sličnost uzoru", "Starost", "Likvidnost", "Vrijednost", "Od vrha",
                        "Oporavaka", "30 dana", "Korelacija s BTC", "Tjedana s KOL pozivima", "Holderi", "Rast holdera 30 d",
                        "Velike burze", "Kupuje ga velikih holdera", "SimianX", "Zašto"], rows, tid="dug"))

        g = cfg["jaki"]
        b.append("<h2 id=jaki>Jaki tokeni: veća vrijednost, stalan volumen, rast holdera</h2>" + tdesc(
            f"Stariji od {g['min_starost_d']} dana, vrijednost barem ${g['min_mcap'] / 1e6:.0f}M, likvidnost barem "
            f"${g['min_likvidnost'] / 1e3:.0f}k, prosječno barem ${g['min_volumen_dan'] / 1e3:.0f}k volumena dnevno u zadnja "
            "2 tjedna i to ravnomjerno (bez dana kad trgovanje stane), nisu pali više od "
            f"{-g['min_pad_od_vrha']:.0%} od vrha i broj holdera im ne pada. Najviše vrijede stalnost volumena i rast holdera; "
            "težine bot sam podešava jednom tjedno na povijesti."))
        rows = []
        for m, sym, s_, rk, px, liq, mc, fj, why in jak:
            f = json.loads(fj)
            rows.append([num(rk, "{:.0f}"), tlink(m, sym), num(s_, "{:.0f}"), num(f.get("starost_d"), "{:.0f} d"), usd(mc),
                         usd(liq), usd(f.get("volumen_dan")), _share(f.get("stalnost_volumena")), num(f.get("holderi")),
                         _pct(f.get("holderi_30d")), _pct(f.get("povrat_30d")), _pct(f.get("pad_od_vrha")),
                         sxui.cell(sx_ops, sx_ins, m), esc(why)])
        b.append(table(["#", "Token", "Ocjena", "Starost", "Vrijednost", "Likvidnost", "Volumen dnevno (14 d)",
                        "Stalnost volumena", "Holderi", "Rast holdera 30 d", "30 dana", "Od vrha", "SimianX", "Zašto"], rows, tid="jak",
                       empty="Još nijedan token ne zadovoljava sve uvjete; popis se puni kako stižu dnevne cijene."))

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
                         num(f.get("kol_7d"), "{:.0f}"), sxui.cell(sx_ops, sx_ins, m), esc(why)])
        b.append(table(["#", "Token", "Ocjena", "Starost", "Likvidnost", "Vrijednost", "Od vrha", "Od dna 30 d",
                        "Volumen tjedan / prije", "7 dana", "KOL pozivi 7 d", "SimianX", "Zašto"], rows, tid="bud"))

        stats = ("<div class=grid>" + "".join([
            _stat(f"{n_all:,}", "tokena provjereno"), _stat(n_tok, "preživjelih s poviješću cijena"),
            _stat(con.execute("SELECT COUNT(*) FROM snap WHERE day=? AND kind='dugorocni'", (day,)).fetchone()[0],
                  "na dugoročnom popisu"),
            _stat(con.execute("SELECT COUNT(*) FROM snap WHERE day=? AND kind='jaki'", (day,)).fetchone()[0], "jakih"),
            _stat(con.execute("SELECT COUNT(*) FROM snap WHERE day=? AND kind='budjenje'", (day,)).fetchone()[0], "se budi"),
            _stat(f"{tot:+,.0f} $" if inv else "–", "demo portfelj"),
            _stat(f"{tot - tot_sol:+,.0f} $" if inv else "–", "bolje/lošije od držanja SOL-a"),
        ]) + "</div>")

        b.append("<h2>Uzori: Fartcoin i Useless</h2>" + tdesc(
            "Kako izgledaju tokeni koje želimo naći. Sličnost uzoru na popisu ispod mjeri koliko je token blizu ovom "
            "profilu (pad od vrha, koliko se puta oporavio, kretanje s BTC-om, volatilnost, likvidnost)."))
        b.append(table(["Token", "Tržišna vrijednost", "Od vrha (6 mj.)", "Oporavaka", "Udio oporavaka", "Korelacija s BTC",
                        "Beta BTC", "30 dana"], _uzori(con, day, cfg["uzori"]), empty="Uzori još nemaju povijest."))

        try:
            b.append(sxui.section(sx_con, sx_ops, sx_ins))
        finally:
            if sx_con is not None:
                sx_con.close()
        b.append("<h2>Brojke</h2>" + stats)
        b.append(_whales(con, cfg))
        b.append(_listings(con, day))
        mx = cfg["mix"]
        b.append("<h2>Demo dugoročni portfelj</h2>" + tdesc(
            f"Bez pravog novca i odvojeno od demo tradinga. Svakih {cfg['knjiga']['svaki_d']} dana bot uloži "
            f"${cfg['knjiga']['usd']} po tokenu u zdravi mix s dugoročnog popisa: {mx['veliki']} velika (iznad "
            f"${mx['veliki_mcap'] / 1e6:.0f}M), {mx['srednji']} srednja (${mx['srednji_mcap'] / 1e6:.0f}-"
            f"{mx['veliki_mcap'] / 1e6:.0f}M) i {mx['mali']} mali, plus prvih {cfg['knjiga']['top']} jakih i prvih {cfg['knjiga']['top']} koji se bude. Drži dok token ne ispadne iz prvih 15 "
            f"na {cfg['knjiga']['drzi_izvan_top_d']} dana (buđenje ima i stop na {cfg['knjiga']['stop_budjenje']:.0%}). "
            "Stupac \"Bolje od SOL-a\" kaže je li izbor bio bolji od jednostavnog držanja SOL-a u istom razdoblju."))
        b.append(table(["Token", "Popis", "Ulaz", "Uloženo", "Rezultat", "SOL u isto vrijeme", "Bolje od SOL-a", "Stanje"],
                       brows, empty="Prvi ulazi nakon prvog prolaza."))

        runs = con.execute("SELECT ts, kind, applied, n, before, after, note, weights FROM learn_runs ORDER BY ts DESC LIMIT 6").fetchall()
        lr = [[ago(r["ts"]), KIND_HR.get(r["kind"], r["kind"]), num(r["n"]),
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


def _sym(con, mint):
    r = con.execute("SELECT symbol, mcap FROM tokens WHERE mint=?", (mint,)).fetchone()
    return (r[0], r[1]) if r else (None, None)


def _whales(con, cfg):
    from dugo import holders
    try:
        buys = holders.whale_buys(con)
        kols = holders.followed_kols(buys)
        n_wh = len(holders.whale_wallets(con))
    except Exception:
        buys, kols, n_wh = {}, {}, 0
    mx = cfg["mix"]
    out = ["<h2>Što kupuju veliki holderi</h2>" + tdesc(
        f"Bot jednom tjedno uzme 20 najvećih holdera svakog dugoročnog tokena (bez poolova i burzi; sada {n_wh} walleta) "
        "i prati što još kupuju, i velike i male tokene. Kad više njih kupi isti token, to je znak da veći igrači ulaze; "
        "isti signal dobiva i skener novih tokena. Kupnja vlastitog dugoročnog tokena se ne broji.")]
    rows = []
    for mint, r in sorted(buys.items(), key=lambda x: (-x[1]["n"], -x[1]["sol"]))[:40]:
        sym, mc = _sym(con, mint)
        size = "–" if mc is None else "velik" if mc >= mx["veliki_mcap"] else "srednji" if mc >= mx["srednji_mcap"] else "mali"
        rows.append([tlink(mint, sym), num(r["n"]), num(r["sol"], "{:,.1f}"), usd(mc), esc(size), ago(r["first"])])
    out.append(table(["Token", "Velikih holdera kupilo", "SOL ukupno", "Vrijednost", "Veličina", "Prva kupnja"], rows,
                     empty="Još nema: walleti velikih holdera čekaju prvu provjeru trejdova (registar walleta, nekoliko sati)."))
    rows = [[f'<a href="/kol/{esc(h)}">{esc(h)}</a>', num(v["buys"]), num(v["wallets"]), num(v["tokens"])]
            for h, v in sorted(kols.items(), key=lambda x: (-x[1]["wallets"], -x[1]["buys"]))[:25]]
    out.append("<h3>Na čije pozive ulaze</h3>" + tdesc(
        "KOL-ovi i Telegram kanali čiji poziv je bio do 6 sati prije kupnje velikog holdera istog tokena.")
               + table(["KOL / kanal", "Kupnji nakon poziva", "Različitih velikih holdera", "Tokena"], rows,
                       empty="Još nema kupnji velikih holdera nakon nečijeg poziva."))
    return "".join(out)


def _listings(con, day):
    from dugo import holders
    rows = []
    for (mint,) in con.execute("SELECT DISTINCT mint FROM big_holders"):
        sh, ch = holders.exchange_share(con, mint)
        r = con.execute("SELECT top_cex, all_cex, names FROM listings WHERE mint=? ORDER BY day DESC LIMIT 1", (mint,)).fetchone()
        if (ch or 0) < 0.01 and not r:
            continue
        sym, mc = _sym(con, mint)
        rows.append(([tlink(mint, sym), usd(mc), _share(sh), signed(None if ch is None else 100 * ch, "{:+.1f} pp"),
                      num(r[0] if r else None, "{:.0f}"), num(r[1] if r else None, "{:.0f}")], ch or 0))
    rows.sort(key=lambda x: -x[1])
    return ("<h2>Burze i mogući listinzi</h2>" + tdesc(
        "Prije listanja burza često primi veći dio supplyja na svoju adresu. Bot prepoznaje adrese burzi i skrbnika "
        "(ista adresa među top holderima šest i više tokena) i prati koliki dio supplyja drže. Rast udjela je signal, "
        "ne sigurnost: isto izgleda i kad netko prebaci tokene na burzu da ih proda.")
            + table(["Token", "Vrijednost", "Drže burze", "Promjena (tjedan+)", "Velike burze", "Sve burze"],
                    [r for r, _ in rows], empty="Prvo mjerenje top holdera je u tijeku."))


def _weights(con):
    from dugo import learn, run
    W = learn.current(run.config())
    rows = []
    for kind, w in W.items():
        for c, v in sorted(w.items(), key=lambda x: -abs(x[1])):
            rows.append([KIND_HR.get(kind, kind), esc(sc.NAMES.get(c, c)), num(v, "{:+.2f}")])
    return "<h3>Težine sada</h3>" + table(["Popis", "Mjerilo", "Težina"], rows, limit=60)


def _sources():
    on = bool(os.environ.get("BIRDEYE_API_KEY"))
    rows = [["DexScreener", "besplatno", "likvidnost, vrijednost, volumen, kupci/prodavači", badge("uključeno", "good")],
            ["GeckoTerminal", "besplatno", "dnevne cijene do 400 dana unatrag (padovi, oporavci, trend)", badge("uključeno", "good")],
            ["CoinGecko", "besplatno", "cijena BTC-a za usporedbu", badge("uključeno", "good")],
            ["Naši KOL i Telegram podaci", "besplatno", "koliko tjedana i koliko ljudi zove token", badge("uključeno", "good")],
            ["GeckoTerminal podaci o tokenu", "besplatno", "broj holdera i koliko drže najveći, svaka 3 dana", badge("uključeno", "good")],
            ["Helius", "naš plan, oko 4.000 kredita tjedno", "20 najvećih holdera po tokenu, jednom tjedno", badge("uključeno", "good")],
            ["CoinGecko", "besplatno", "na kojim je burzama izlistan", badge("uključeno", "good")],
            ["Birdeye", "plaćeno, od oko $39 do $99 mjesečno", "točniji broj holdera i njihova povijest unatrag",
             badge("uključeno", "good") if on else badge("nije uključeno")],
            ["Arkham", "plaćeno, cijena na upit", "imena adresa (koja burza, koji market maker, koji fond)",
             badge("opcija")]]
    return "<h3>Izvori</h3>" + table(["Izvor", "Cijena", "Što daje", "Stanje"], rows)
