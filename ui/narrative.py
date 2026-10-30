"""Plain-language reading of everything the bot knows about one token: what may happen and on what evidence.

Every sentence is built from a stored number (no free text is invented), so the interpretation can be checked
against the sections below it in the pop-up / token page. It is a reading of the data, not advice.
"""
import time

from ui import confidence, data, evidence
from ui.html import esc


def _pct(v):
    v = v or 0
    return v / 100 if v > 100 else v


def _usd(x):
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}k" if x >= 1e3 else f"${x:.0f}"


def _smart(wallets, syms):
    """Sentences about smart buyers and their track record (hype.db smart_wallets + the wallet registry)."""
    known = {w["wallet"]: w for w in data.smart_wallets()}
    reg = {w["wallet"]: w for w in data.wallets()}
    lines = []
    for w in wallets[:4]:
        st = data.js((known.get(w) or {}).get("stats"), {}) or {}
        rs = (reg.get(w) or {}).get("stats") or {}
        bits = []
        if st.get("source") == "gmgn":
            if st.get("pnl_usd_7d"):
                bits.append(f"zaradio {_usd(st['pnl_usd_7d'])} u 7 dana (GMGN)")
            if st.get("win_rate"):
                bits.append(f"{st['win_rate']:.0%} trejdova u plusu")
        else:
            pnl = rs.get("closed_pnl_sol") if rs else st.get("pnl_sol")
            if pnl:
                bits.append(f"{pnl:+.1f} SOL na zatvorenim pozicijama")
            wr = rs.get("win_rate") if rs else st.get("win_rate")
            if wr:
                bits.append(f"{wr:.0%} u plusu")
        big = rs.get("big_wins") or st.get("big_wins")
        if big:
            bits.append(f"{big} trejdova barem 2x")
        early = [syms.get(t) or t[:6] for t in (st.get("early_in") or []) if t]
        if early:
            bits.append("rano ušao u " + ", ".join(early[:3]))
        lines.append(f"wallet {w[:4]}…{w[-4:]}" + (f" ({'; '.join(bits)})" if bits else ""))
    return lines


def interpret(mint):
    """(headline, [paragraph html]) for the top of a token's page."""
    sigs = data.hype_signals("token=?", (mint,), "ts DESC", limit=200)
    sig = sigs[0] if sigs else None
    _, det = evidence.details(mint)
    rugs = data.rug_reports(mint)
    rug = rugs[0] if rugs else None
    ev = data.event_tokens(mint)
    pair = evidence.live_pair(mint)
    _, tw = evidence.tweets(mint)
    f = (data.js(sig["features"], {}) or {}) if sig else {}
    mk = (rug or {}).get("data", {}).get("market") or {}
    liq = ((pair or {}).get("liquidity") or {}).get("usd") or (sig or {}).get("liquidity") or mk.get("liquidity")
    mcap = (pair or {}).get("marketCap") or (pair or {}).get("fdv") or (sig or {}).get("mcap") or mk.get("mcap")
    role = "canonical" if any(e["role"] == "canonical" for e in ev) else None
    conf, parts = confidence.score(sig["score"] if sig else None, f, det, rug["verdict"] if rug else None, role, liq, mcap)
    level, _ = confidence.level(conf)
    sym = ((pair or {}).get("baseToken") or {}).get("symbol") or (sig or {}).get("symbol") or (rug or {}).get("symbol") or mint[:6]
    syms = data.symbols()

    pro, con, facts = [], [], []
    # market
    if pair:
        chg = pair.get("priceChange") or {}
        vol = pair.get("volume") or {}
        tx = (pair.get("txns") or {}).get("h1") or {}
        age_h = (time.time() * 1000 - (pair.get("pairCreatedAt") or time.time() * 1000)) / 3.6e6
        facts.append(f"{esc(sym)} je star {age_h:.0f} h" if age_h < 72 else f"{esc(sym)} je star {age_h / 24:.0f} dana")
        facts.append(f"mcap {_usd(mcap or 0)}, likvidnost {_usd(liq or 0)}")
        if vol.get("h1"):
            facts.append(f"u zadnjem satu {_usd(vol['h1'])} volumena i {tx.get('buys', 0)} kupnji naspram {tx.get('sells', 0)} prodaja")
        if chg.get("h1") is not None:
            facts.append(f"cijena {chg['h1']:+.0f}% u 1 h i {chg.get('h24') or 0:+.0f}% u 24 h")
    # smart money
    sm = det.get("smart_buyers") or []
    if sm:
        pro.append(f"Među prvim kupcima je <b>{len(sm)} smart walleta</b> s dokazanim rezultatima: "
                   + esc("; ".join(_smart(sm, syms))) + ". Takvi walleti obično ulaze prije rasta, pa je to najjači "
                   "pojedinačni signal koji alat ima.")
    # X / influencers
    x = det.get("x") or {}
    authors, views, infl = {}, 0, []
    for t in tw:
        h, fol, _ = evidence._author(t)
        authors[h] = max(authors.get(h, 0), fol)
        views += t.get("viewCount") or 0
    infl = sorted(((h, n) for h, n in authors.items() if n >= 10000), key=lambda r: -r[1]) or \
        [tuple(i) for i in x.get("influencers") or []]
    n_auth = len(authors) or x.get("authors") or 0
    if infl:
        n = len(infl)
        pro.append(f"Na X-u ga je objavio <b>{n} {'veći račun' if n == 1 else 'veća računa' if n < 5 else 'većih računa'}</b> ("
                   + esc(", ".join(f"@{h} s {n:,} pratitelja" for h, n in infl[:3]))
                   + f"); ukupno {n_auth} različitih autora i {views:,} pregleda. Kad veliki računi objave CA, dolazi novi "
                   "val kupaca.")
    elif n_auth >= 5:
        pro.append(f"Na X-u ga spominje {n_auth} različitih autora ({views:,} pregleda), ali bez velikih influencera, "
                   "pa je buzz zasad organski i malen.")
    elif sig:
        con.append("Na X-u se o njemu gotovo ne priča" + (f" ({n_auth} autora)" if n_auth else "") + ".")
    if f.get("kol_x"):
        pro.append("Praćeni KOL računi su ga objavili na X-u.")
    kg = det.get("kol_group") or {}
    if kg.get("dev_selling"):
        con.append(f"Grupni KOL poziv ({kg.get('n_authors')} autora u 30 min), ali walleti koji su kupili prije poziva "
                   "prodaju u njega.")
    elif kg:
        pro.append(f"Grupni KOL poziv na X-u: {kg.get('n_authors')} autora u 30 min, od toga {kg.get('n_good')} s dobrom "
                   "poviješću poziva (stranica KOL-ovi).")
    pf = det.get("pumpfun") or {}
    if pf.get("kolCount"):
        pro.append(f"Na pump.fun ga trejda {pf['kolCount']} KOL walleta.")
    if det.get("x_trend"):
        pro.append(f"Ime je trenutno trending tema na X-u („{esc(det['x_trend'])}“), pa ga ljudi nalaze sami.")
    if det.get("copycats"):
        (pro if det["copycats"] >= 5 else facts).append(
            f"Postoji {det['copycats']} tokena istog imena iz zadnja 3 dana: tema je živa"
            + (", a ovaj je vodeći među njima" if role == "canonical" else "")
            + ("." if det["copycats"] >= 5 else ""))
    if det.get("search_rise"):
        pro.append(f"Google pretraga imena porasla je {det['search_rise']}x u 24 h.")
    if (f.get("turnover") or 0) >= 0.7 and (f.get("buy_pressure") or 0) >= 0.4:
        pro.append("Novac ulazi brzo i kupci prevladavaju nad prodavačima.")
    if role == "canonical" and ev:
        pro.append(f"Pravi je token događaja „{esc(ev[0]['event'])}“ ({esc(ev[0]['event_date'])}); oko takvih datuma "
                   "interes obično raste.")
    # holders / rug
    if pf:
        t10, bund = _pct(pf.get("top10HoldersPercent")), _pct(pf.get("bundlerOwnedPercent"))
        if t10 < 35 and bund < 15:
            pro.append(f"Ponuda je raspršena: top 10 holdera drži {t10:.0f}%, bundleri {bund:.0f}%, {pf.get('holders') or '?'} holdera.")
        else:
            con.append(f"Ponuda je koncentrirana (top 10 drži {t10:.0f}%, bundleri {bund:.0f}%): par walleta može srušiti cijenu.")
    if rug:
        d = rug["data"]
        if rug["verdict"] == "ODBAČEN":
            con.append("Rug filter ga je <b>odbacio</b>: " + esc("; ".join(d.get("hard_fails", [])[:2])) + ".")
        elif rug["verdict"] == "VISOK RIZIK":
            con.append("Rug filter: visok rizik (" + esc("; ".join(d.get("flags", [])[:2])) + ").")
        elif rug["verdict"] == "PROLAZI":
            pro.append("Rug filter ga je pustio: nema bundlea, insajderskih klastera ni lažnog volumena iznad pragova.")
        else:
            con.append("Rug filter: oprez (" + esc("; ".join(d.get("flags", [])[:2])) + ").")
    else:
        con.append("Rug filter ga još nije provjerio, pa holderi i dev nisu potvrđeni.")
    if liq is not None and liq < 10000:
        con.append(f"Likvidnost je mala ({_usd(liq)}): i mala prodaja jako miče cijenu, a izlaz je skup.")
    if mcap and mcap > 1_000_000:
        con.append(f"Već je na {_usd(mcap)} mcap, pa je prostor za višestruki rast manji nego kod svježih tokena.")
    if (f.get("momentum") or 0) >= 0.9 and (f.get("buy_pressure") or 0) < 0.2:
        con.append("Cijena je već jako skočila, a kupci više ne prevladavaju: moguće je da je vrh prošao.")
    h1 = ((pair or {}).get("priceChange") or {}).get("h1")
    crashed = h1 is not None and h1 <= -50
    if crashed:
        con = [c for c in con if not c.startswith("Cijena je već jako skočila")]
        con.insert(0, f"<b>Cijena je pala {-h1:.0f}% u zadnjem satu</b>: rani kupci ili dev su izašli, a takvi tokeni se "
                      "rijetko vrate.")
    if not sm and sig:
        con.append("Nijedan poznati smart wallet nije među prvim kupcima.")

    # what the tool expects
    if rug and rug["verdict"] == "ODBAČEN":
        head = f"Alat ne bi ulazio u {esc(sym)}: rug filter je našao tvrdi problem."
    elif crashed:
        head = f"Alat ne bi sada ulazio u {esc(sym)}: cijena se srušila u zadnjem satu, signali su od prije pada."
    elif level == "visoka":
        head = (f"Alat vidi <b>dobru šansu</b> da {esc(sym)} nastavi rasti u sljedećim satima: više neovisnih izvora "
                "se slaže.")
    elif level == "srednja":
        head = (f"Alat vidi <b>umjerenu šansu</b> za rast {esc(sym)}: postoje pravi signali, ali nisu svi potvrđeni.")
    else:
        head = (f"Alat zasad <b>ne vidi dovoljno dokaza</b> da će {esc(sym)} rasti: signala je malo ili su slabi.")
    head += f" Confidence {conf}/100 ({level})."

    out = []
    if facts:
        out.append("<p><b>Stanje:</b> " + "; ".join(facts) + ".</p>")
    if pro:
        out.append("<p><b>Zašto bi mogao rasti:</b> " + " ".join(pro) + "</p>")
    if con:
        out.append("<p><b>Što govori protiv:</b> " + " ".join(con) + "</p>")
    watch = []
    if not sm:
        watch.append("ulazak smart walleta")
    if not infl:
        watch.append("objava većeg influencera")
    if not rug:
        watch.append("rezultat rug provjere")
    if watch:
        out.append("<p class=mut><b>Što bi podiglo procjenu:</b> " + ", ".join(watch) + ". Prodaje deva ili top holdera, pad "
                   "likvidnosti ili prestanak spominjanja na X-u bi je spustili.</p>")
    out.append("<p class=mut style='font-size:12px'>Ovo je čitanje izmjerenih podataka, ne savjet. Koliko je takva procjena "
               "dosad bila točna vidi se u tablici „Je li confidence točan?“ na stranici Demo trading.</p>")
    return head, out


def html(mint):
    try:
        head, paras = interpret(mint)
    except Exception as e:  # never break the page over the summary
        return f"<div class=card><span class=mut>Interpretacija nije uspjela: {esc(e)}</span></div>"
    return (f"<div class=card style='border-left:4px solid var(--acc)'><div style='font-size:16px;margin-bottom:6px'>{head}</div>"
            + "".join(paras) + "</div>")
