"""The "Kriteriji" page: every selection rule and weight in one place, read live from the modules where possible."""
import json
import os

from ui import data, explain
from ui.html import bar, esc, table
from ui import labels
from ui.labels import FEATURE_DESC as FEATURE


def _try(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _parts_table(rows):
    return table(["Dio", ("Max bodova", "n"), ("Kako se računa", "wrap")],
                 [[esc(n), (f"{m:g}", m, "n"), (esc(x), "", "wrap")] for n, m, x in rows])


def page(qs):
    b = ["<h1>Kriteriji odabira</h1><p class=mut>Kako bot bira evente, tokene i wallete. Brojke na ovoj stranici su "
         "one koje bot upravo koristi, pa se svaka promjena (i ona koju bot sam nauči) odmah vidi ovdje.</p>"]
    b.append("""<div class=card><b>Tok podataka</b><ol>
<li><b>Kalendar</b>: nadolazeći događaji, hype ocjena 0-100, ključne riječi.</li>
<li><b>DexScreener</b>: za svaki event traži tokene po ključnim riječima, odvaja pravi od kopija.</li>
<li><b>Hype skener</b> (svake 2 min): rani signali tokena koji rastu, neovisno o kalendaru.</li>
<li><b>Rug filter</b>: Helius + RugCheck provjera holdera, deva, bundlea, lažnog volumena.</li>
<li><b>Walleti</b>: rani kupci pobjedničkih tokena ulaze u registar, ocjenjuju se po PnL-u, najbolji idu na copy listu.</li>
</ol></div>""")

    # ---- events
    b.append("<h2 id=eventi>1. Eventi (kalendar)</h2><h3>Hype ocjena eventa (0-100)</h3>")
    b.append(_parts_table([
        ("Slavnost osobe", 25, "broj Wikipedija koje imaju članak (Wikidata sitelinks), log skala, 300 = max"),
        ("Pregledi 30 dana", 15, "Wikipedia pageviews, log skala, 10M = max"),
        ("Rast interesa", 10, "trend pregleda: (trend - 1) × 10"),
        ("Polymarket volumen", 20, "volumen oklada na event, log skala, $100M = max"),
        ("Veza s kripto publikom", 25, "osobe i teme koje kripto publika prati (popis ispod)"),
        ("Ručno dodan", 10, "event koji je netko ručno dodao u kalendar"),
        ("Blizina datuma", 5, "5 - 0.5 × dana do eventa"),
    ]))
    aff = _try(lambda: __import__("event_calendar.enrich", fromlist=["x"]).CRYPTO_AFFINITY, {})
    if aff:
        b.append("<p><b>Kripto afinitet (bodovi):</b> " + ", ".join(f"{esc(k)} {v}" for k, v in
                                                                 sorted(aff.items(), key=lambda kv: -kv[1])) + "</p>")
    prior = _try(lambda: __import__("event_calendar.enrich", fromlist=["x"]).KIND_PRIOR, {})
    b.append("<h3>Šansa da event dobije token (0-1)</h3><p>Početna vrijednost po vrsti eventa, plus 0.3 × afinitet/25, "
             "+0.15 ako opis sadrži okidače (died, arrested, viral, trailer…), +0.1 za skok pregleda ≥10x, +0.05 za ≥5 "
             "vijesti, +0.1 za potres ≥8 ili tsunami. Rutinski eventi (Starlink, CPI, FOMC…) = 0.05.</p>")
    if prior:
        b.append(table(["Vrsta", ("Početna šansa", "n")], [[esc(labels.kind(k)), (f"{v:.2f}", v, "n")]
                                                           for k, v in sorted(prior.items(), key=lambda kv: -kv[1])]))
    b.append("<p><b>Konačni poredak:</b> (hype + viralnost + vijesti) × (0.3 + 0.7 × šansa za token).</p>")

    # ---- tokens: dex
    b.append("<h2 id=tokeni>2. Tokeni za event (DexScreener)</h2>")
    noise = _try(lambda: sorted(__import__("dexscreener.match", fromlist=["x"]).NOISE), [])
    mx = _try(lambda: __import__("dexscreener.match", fromlist=["x"]).MAX_MCAP, 500e6)
    b.append(f"<p><b>Filtri:</b> samo Solana; token pripada eventu ako mu je simbol jednak pojmu ili ime sadrži pojam; "
             f"odbacuje likvidnost ispod $5,000, volumen 24h ispod $100 (mrtav par) i mcap "
             f"iznad ${mx / 1e6:,.0f}M (veliki tokeni). Pojmovi bez šuma"
             + (f" ({esc(', '.join(noise[:30]))}{'…' if len(noise) > 30 else ''})" if noise else "") + ".</p>")
    b.append("<h3>Organska ocjena (0-100)</h3>")
    b.append(_parts_table([
        ("Starost", 15, "log, 30+ dana = max"), ("Likvidnost", 15, "log, $1M = max"),
        ("Volumen 24h", 25, "log od $1k/dan, $1M/dan = max"), ("Broj transakcija", 15, "log od 10 tx/dan, 10k = max"),
        ("Omjer kupnji", 10, "10 ako 40-70% kupnji, 4 ako 30-80%, inače 0; tek od 50 tx/dan"),
        ("Wash kazna", -15, "-15 ako je volumen više od 30x likvidnost"),
        ("Društvene mreže", 10, "4 po mreži + 3 za web"), ("Community takeover", 15, "CTO na DexScreeneru"),
        ("Točan simbol", 10, "simbol točno jednak pojmu"),
    ]))
    b.append("<p>Najviša ocjena unutar eventa = <b>pravi</b> token, ostali su <b>kopije</b>.</p>")

    # ---- hype
    b.append("<h2 id=razine>2b. Slojevita analiza: klase i razine</h2><p>Svaki token koji sken vidi dobiva <b>klasu</b> i "
             "<b>razinu</b>. Skupe provjere (Helius, Apify) dobivaju samo tokeni koji su "
             "stigli do razine; tko ne prođe ostaje u bazi i prati mu se cijena, pa bot pri učenju vidi i što je propušteno.</p>")
    tc = _try(lambda: json.load(open(os.path.join(data.HERE, "tiers", "config.json"))), {})
    kl = tc.get("klase", {})
    b.append(table(["Klasa", ("Tko ulazi", "wrap"), ("Cilj (početni, uči se)", "wrap")], [
        ["Moonshot", (f"mcap &lt; ${kl.get('moonshot', {}).get('mcap_max', 0):,.0f}, mlađi od {kl.get('moonshot', {}).get('age_max_h', 0) / 24:.0f} dana", "", "wrap"), ("3x u 24 h", "", "wrap")],
        ["Rizičan", ("sve između Moonshota i Stabilnih", "", "wrap"), ("2x u 24 h", "", "wrap")],
        ["Event", ("pravi token događaja iz kalendara", "", "wrap"), ("+50% do dana eventa", "", "wrap")],
        ["Stabilni", (f"mcap &gt; ${kl.get('stabilni', {}).get('mcap_min', 0):,.0f}, stariji od {kl.get('stabilni', {}).get('age_min_h', 0) / 24:.0f} dana", "", "wrap"), ("+30% u 72 h", "", "wrap")]]))
    b.append(table(["Razina", ("Što se radi", "wrap"), ("Cijena po tokenu", "wrap"), ("Tvrdi pad", "wrap")], [
        ["T0", ("DexScreener tržište, RugCheck authority i LP, pump.fun podaci, kalendar; oblik puta do mcapa", "", "wrap"), ("0", "", "wrap"),
         ("samo mehanika ruga: aktivan mint/freeze authority, LP nezaključan izvan launchpada", "", "wrap")],
        ["T1", ("rani kupci i smart walleti (1 stranica Heliusa), kopije teme", "", "wrap"), ("~10 kredita", "", "wrap"), ("nema", "", "wrap")],
        ["T2", ("pun rug filter, X buzz", "", "wrap"), ("~525 kredita + Apify", "", "wrap"), ("rug ODBAČEN", "", "wrap")],
        ["T3", ("Google Trends, KOL, tok walleta oko poziva, ponovna provjera dok je istaknut", "", "wrap"), ("1-3k kredita + Apify", "", "wrap"), ("nema; crvene zastavice spuštaju Šansu", "", "wrap")]]))
    b.append("<p class=mut>Likvidnost, top 10 holderi, dev udio i bundleri <b>nisu</b> pragovi: ulaze kao signali s težinom koju "
             "bot sam uči iz ishoda. Signali oblika puta do mcapa (brzina rasta, rast u jednom skoku, drži li se blizu vrha) "
             "imaju težinu 0 dok ih bot ne nauči.</p>")
    b.append("<h2 id=hype>3. Hype ocjena tokena (0-100)</h2><p>Svaki signal je 0-1; ocjena = Σ(signal × težina) / "
             "Σ težina × 100. Ovo su početne težine; bot ih svaki dan sam prilagođava po klasi tokena iz ishoda, uz "
             "zaštite (<a href=/learn>Učenje</a>).</p>")
    hd = os.path.join(data.HERE, "hype")
    w = _try(lambda: json.load(open(os.path.join(hd, "weights.json"))), {})
    tot = sum(w.values()) or 1
    rows = []
    for k in sorted(set(w) | set(FEATURE), key=lambda k: -w.get(k, 0)):
        rows.append([esc(labels.feat(k)), (f"{w.get(k, 0):g}", w.get(k, 0), "n"), (f"{100 * w.get(k, 0) / tot:.1f}%", w.get(k, 0), "n"),
                     bar(w.get(k, 0), max(w.values() or [1])), (esc(FEATURE.get(k, "")), "", "wrap")])
    b.append(table(["Signal", ("Težina", "n"), ("Udio", "n"), "", ("Što mjeri", "wrap")], rows))
    b.append("<p><b>Kandidati:</b> novi DexScreener profili i ažuriranja, boostovi, CTO, tokeni iz 3 najbrže rastuće "
             "teme (metas) i CA adrese iz praćenih Telegram kanala. X buzz preko Apifyja samo za "
             "top 5 s ocjenom ≥ 40.</p>")

    # ---- rug
    T = _try(lambda: __import__("rugfilter.score", fromlist=["x"]).T, {})
    g = lambda k, d="?": T.get(k, d)  # noqa: E731
    b.append("<h2 id=rug>4. Rug filter</h2><p>Kreće od 100. <b>Tvrdi pad</b> odmah daje presudu ODBAČEN. Zastavice "
             "oduzimaju bodove, smart walleti među ranim kupcima dodaju +5 svaki (max +15). Presuda: ≥ 75 PROLAZI, 50-74 "
             "OPREZ, &lt; 50 VISOK RIZIK.</p><h3>Tvrdi padovi</h3><ul class=r>")
    for x in ["mint authority nije ugašena (dev može tiskati tokene)", "freeze authority nije ugašena",
              "RugCheck ga je označio kao rugan", f"bundle u bloku kreacije > {g('bundle_hard')}% supplyja",
              f"serijski kreator: ≥ {g('serial_dev_tokens')} tokena, živih < {g('serial_dev_alive_pct')}%",
              "dev već označen kao ruger, ili financiran iz walleta koji je financirao rug",
              f"jedan klaster walleta (isti izvor SOL-a) ima > {g('cluster_hard')}%",
              f"RugCheck insajderska mreža > {g('insider_hard')}%", f"wash score ≥ {g('wash_hard')} (lažni volumen)",
              f"likvidnost ispod ${g('min_liquidity_usd', 0):,}"]:
        b.append(f"<li class=bad>{esc(x)}</li>")
    b.append("</ul><h3>Zastavice (kazne)</h3>")
    b.append(table(["Uvjet", ("Bodova", "n")], [[esc(x), (f"-{p}", p, "n")] for x, p in [
        (f"bundle > {g('bundle_warn')}%", 20), (f"snajperi > {g('sniper_warn')}% u prvih ~8 s", 15),
        (f"snajperi > {g('sniper_mild')}%", 8), (f"klaster > {g('cluster_warn')}%", 15),
        ("rani kupci koje je financirao dev (insajderi)", 15), ("poznati bundleri/rugeri među kupcima (10 po walletu)", 30),
        (f"top 10 holdera > {g('top10_warn')}%", 15), (f"top 10 holdera > {g('top10_mild')}%", 8),
        (f"wash score ≥ {g('wash_warn')}", 15), (f"RugCheck insajderi > {g('insider_warn')}%", 10),
        (f"kreator napravio ≥ {g('dev_many_tokens')} tokena", 10), (f"dev drži > {g('dev_hold_warn')}%", 10),
        (f"dev prodao ≥ {g('dev_sold_warn')}% početnog udjela", 10), ("dev prebacio tokene na druge wallete", 10),
        (f"> {g('fresh_warn')}% ranih kupaca ili holdera su fresh walleti", 10), ("dev wallet mlađi od 3 dana", 5),
        ("volumen 24h > 50x likvidnost", 5)]]))
    b.append(f"<p>Max preporučeni ulaz = likvidnost / 2 × {g('max_slippage_pct')}% (pomak cijene od ~{g('max_slippage_pct')}%).</p>")

    # ---- wallets
    b.append("<h2 id=walleti>5. Walleti i copy lista</h2><h3>Kako wallet uđe u registar (harvest)</h3>")
    b.append("<p>Tokeni iz hype signala (score ≥ 40, zadnjih 7 dana), event tokena i po želji DexScreener feedova. "
             "<b>Pobjednici</b> = mcap ≥ $1M i mlađi od 14 dana; za top 10 uzima prvih 60 kupaca. Uloga kupca:</p>")
    b.append(table(["Uloga", "Uvjet", "Učinak"], [
        ["dev", "transakcija kreatora", "oznaka dev, nikad na copy listi"],
        ["snajper", "isti slot kao prva kupnja ili ≤ 3 s nakon nje", "oznaka sniper, nikad na copy listi"],
        ["sitni kupac", "uložio < 0.1 SOL", "ne ide u red za ocjenu"],
        ["rani kupac", "ostali", "+2 prioriteta u redu za ocjenu"]]))
    b.append("<p>Rug filter i hype learn također dodaju wallete (holderi, bundleri, financijeri, smart walleti).</p>")
    b.append("<h3>Ocjena profitabilnosti (0-100), zadnjih 30-60 dana</h3>")
    b.append(_parts_table([
        ("Zatvoreni profit", 25, "log10(1 + PnL SOL) / 2; 100 SOL = max"), ("ROI na uloženo", 20, "+100% = max"),
        ("Win rate", 20, "korigiran prema 50%: (dobitni + 1) / (zatvoreni + 2); 25% = 0, 70% = max"),
        ("Profit factor", 15, "dobici / gubici; 1 = 0, 3+ = max"), ("2x+ trejdovi", 10, "5 = max"),
        ("Raspršenost profita", 10, "1 - udio najvećeg trejda u dobiti (samo ako je u plusu)")]))
    b.append("<p>Zbroj × min(1, zatvorenih / 10): manje od 10 zatvorenih pozicija = premalo dokaza.</p>")
    from wallets import rang
    b.append("<h3>Ocjena za kopiranje (od 11.11.)</h3><p>Zadnjih 30 dana, samo zatvorene pozicije. Apsolutna zarada u "
             "SOL-u nije u ocjeni (vidi se u detaljima novčanika).</p>")
    names = {"win": "Win rate, donja granica (Wilson 90 %)", "median": "Medijan povrata po tradeu",
             "pf": "Profit factor", "copy": "Kopirljivost (likvidnost na ulazu, naš trošak 0,1-0,15 SOL, dobitak nakon "
             "našeg kašnjenja)", "recency": "Svježina (poluživot 7 dana)"}
    b.append(_parts_table([(names[k], round(100 * w), "") for k, w in rang.WEIGHTS.items()]))
    b.append(f"<p>Koncentracija (najveći trade nosi više od {rang.CONC_MAX:.0%} zarade): ocjena × {rang.CONC_MULT:g}. "
             f"Ispod {rang.MIN_N} zatvorenih: nije dokazan. Medijan likvidnosti na ulazu ispod "
             f"{rang.MIN_LIQ_USD // 1000}k $ ili nepoznat: nije kopirljivo (vidi se, ali se pravim novcem ne kopira).</p>")
    b.append(f"<h3>Copy lista</h3><p>dokazan, kopirljiv, ocjena za kopiranje ≥ <b>{explain.COPY_MIN_SCORE}</b>, "
             f"bez oznaka: <b>{esc(', '.join(sorted(labels.wallet_label(x) for x in explain.BAD_LABELS)))}</b>.</p>")
    b.append(table(["Tier", "Uvjet", "Ponovna provjera"], [
        ["A", "stara copy ocjena ≥ 60", "svakih 6 h"], ["B", "ocjena ≥ 40 ili stara copy ≥ 35", "dnevno"],
        ["C", "ostali", "tjedno"], ["D", "bot, ili stara copy 0 uz ≥ 10 zatvorenih", "samo ako ga druga analiza opet vidi"]]))
    b.append("<p>Tier je samo raspored provjera (trošak Helius kredita): stara copy ocjena tu ostaje, nigdje drugdje.</p>")

    # ---- paper
    cfg = _try(lambda: __import__("paper.sim", fromlist=["x"]).load_config(), {})
    b.append("<h2 id=confidence>6. Confidence (koliko alat vjeruje tokenu)</h2><p>Jedan broj 0-100 za poredak tokena. "
             "Hype ocjena je baza, neovisne potvrde dodaju bodove, poznati rizici oduzimaju. Uz svaki token u pop-upu piše "
             "koji je dio koliko donio. Razine: 55+ visoka, 35-54 srednja, ispod 35 niska. Na stranici Demo trading je "
             "tablica koja pokazuje pobjeđuju li tokeni s visokom razinom stvarno češće.</p>")
    b.append(table(["Dio", ("Bodova", "n"), ("Uvjet", "wrap")], [[esc(a), (esc(p_), 0, "n"), (esc(c), "", "wrap")] for a, p_, c in [
        ("Hype ocjena", "do +60", "0.6 × hype ocjena"), ("X buzz", "+8", "jak signal „Priča se na X-u” ili barem jedan influencer"),
        ("Smart money", "+10", "smart walleti među prvim kupcima"), ("KOL", "+7", "KOL walleti ili objava praćenih influencera"),
        ("Telegram", "+4", "objavljen u call kanalima"), ("X trend", "+5", "ime je trending tema na X-u"),
        ("Event", "+6", "pravi token nadolazećeg eventa"), ("Holderi", "+6 / -10", "top 10 < 35% i bundleri < 15%, inače kazna"),
        ("Rug filter", "+10 / +3 / -25 / 0", "PROLAZI / OPREZ / VISOK RIZIK / ODBAČEN = confidence 0"),
        ("Likvidnost", "-10", "ispod $10k"), ("Veličina", "-5", "mcap iznad $1M"),
        ("Kasni ulaz", "-5", "cijena već jako skočila, a kupci više ne prevladavaju")]]))
    b.append("<h2 id=paper>7. Paper trading (ulaz i izlaz)</h2>")
    if not cfg:
        b.append("<p class=mut>Pravila demo tradinga se ne mogu pročitati.</p>")
    else:
        b.append("<p>Ovo su pravila koja demo trading upravo koristi. Pravila ulaza (najmanja ocjena, likvidnost, blokirane "
                 "rug presude) bot svaki dan sam prilagođava iz dnevnog pregleda, a izlaze uči po klasi tokena "
                 "(<a href=/izlazi>Izlazi</a>). Svaka promjena prolazi zaštite i sama se vraća ako se pokaže lošijom.</p>")
        b.append(table(["Pravilo", "Vrijednost"],
                       [[esc(labels.cfg_name(k)), esc(labels.cfg_value(k, v))] for k, v in cfg.items() if not k.startswith("_")]))
    return "Kriteriji", "".join(b)
