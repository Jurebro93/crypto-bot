"""Programmatic SEO pages per Solana meme coin (EN main, HR), built on the public coin data in ui/coins.py (read-only).

- /coin/<slug>/price-prediction      /hr/coin/<slug>/prognoza        data-based scenarios, what 2x/5x/10x would mean
- /how-to-buy/<slug>                 /hr/kako-kupiti/<slug>          steps, contract address, slippage for its pool
- /rug-check/<slug>                  /hr/provjera/<slug>             safety checks from on-chain audit data
- /how-to-buy, /rug-check            /hr/kako-kupiti, /hr/provjera   hubs listing the top 100
No made-up price targets: scenarios are arithmetic on market cap plus the signals we measure. Not financial advice.
"""
import json
import os
import re
import time

from ui.html import esc

SLUG = re.compile(r"[a-z0-9\-]{1,40}")
EXCH_EN, EXCH_HR = "/blog/best-crypto-exchanges-croatia", "/hr/blog/najbolje-kripto-mjenjacnice-hrvatska"

T = {
    "en": dict(
        pp="/coin/{s}/price-prediction", buy="/how-to-buy/{s}", rug="/rug-check/{s}", coin="/coin/{s}",
        buy_hub="/how-to-buy", rug_hub="/rug-check", lb="/solana-meme-coins", exch=EXCH_EN, home="/",
        cta="Request access", nfa="Not financial advice. Meme coins are extremely risky; most go to zero.",
        # price prediction
        pp_title="{name} ({sym}) price prediction: data-based scenarios | MemeSonar",
        pp_desc="{sym} price prediction without made-up targets: what 2x, 5x and 10x would mean for {name}'s market "
                "cap, plus {pos} of {n} live signals pointing up. Updated every 3 hours.",
        pp_h1="{sym} price prediction",
        pp_lead="{name} trades at {price} with a {mcap} market cap (#{rank} Solana meme coin). Instead of guessing a "
                "price, we show what each move would require and what our live signals say right now.",
        sc_h="What would {sym} need to reach each price?",
        sc_cols=("Scenario", "Price", "Market cap needed", "Comparable coin today"),
        sc_names=(("-50%", 0.5), ("Today", 1.0), ("2x", 2), ("5x", 5), ("10x", 10)),
        sc_none="bigger than any meme coin in our list",
        sig_h="Live signals", sig_lead="{pos} of {n} signals point up, {neg} point down.",
        sig_cols=("Signal", "Now", "Reading"),
        up="up", down="down", flat="neutral",
        sig=dict(chg="Price change, 24 h", hold="Holder change, 24 h", flow="Buys vs sells, 24 h",
                 org="Organic trading score", liq="Liquidity vs market cap", top="Top holders' share",
                 calls="Influencer calls measured"),
        chart_h="{sym} price history", chart_src="our snapshots",
        pp_how="How to read this: a 10x needs ten times today's market cap, so check whether any meme coin is that "
               "big today. Signals change every few hours; members see them live with alerts.",
        # how to buy
        b_title="How to buy {name} ({sym}) on Solana: step by step | MemeSonar",
        b_desc="Where and how to buy {sym}: the real contract address, the cheapest route via Phantom and Jupiter, "
               "slippage for its ${liq} pool and a safety check before you buy.",
        b_h1="How to buy {name} ({sym})",
        b_lead="{name} is a Solana token, so the cheapest way is usually: buy SOL on an EU-regulated exchange, send it "
               "to a Solana wallet and swap it for {sym}. Always use the contract address below; fake tokens copy the "
               "name.",
        addr="Official {sym} contract address (Solana)", copy="Copy",
        steps_h="Step by step",
        steps=("Buy SOL (or USDC) on an EU-regulated exchange. See <a href={exch}>the best exchanges for Croatia and "
               "the EU</a>, compared by licence and fees.",
               "Install a Solana wallet such as Phantom or Solflare and write the recovery phrase on paper. Never share "
               "it with anyone, including us.",
               "Withdraw the SOL from the exchange to your wallet address. Send a small test amount first.",
               "Open Jupiter (jup.ag) or the swap inside your wallet, paste the {sym} contract address above and check "
               "that the symbol and logo match.",
               "Set slippage (see the table below for this pool), confirm the swap and keep some SOL for network fees.",
               "Decide your exit before you buy: where you take profit and where you cut the loss."),
        cex_h="Is {sym} on a centralised exchange?",
        cex_yes="Our data shows {sym} trading on {n} centralised exchanges. The best known: {names}. Prefer one with an "
                "EU licence (see <a href={exch}>which exchanges are licensed</a>); not every coin listed worldwide is offered "
                "to EU customers. Smaller venues in that count are not named here.",
        cex_small="Our data shows {sym} on {n} smaller centralised exchanges, none of the well-known ones, so we don't "
                  "name them. The on-chain route above is the safer way to buy it.",
        mica_yes="EU licence",
        cex_no="We have no centralised exchange listing for {sym}, so the on-chain route above is the way to buy it.",
        slip_h="What a buy costs in the {liq} pool",
        slip_sub="Fewer tokens than the quoted price, constant-product pool, before fees",
        slip_cols=("Buy size", "Fewer tokens than quoted"),
        safe_h="Before you buy: safety check", safe_link="Full {sym} rug check →",
        # rug check
        r_title="Is {name} ({sym}) safe? Rug check: {ok} of {n} checks passed | MemeSonar",
        r_desc="{sym} rug check from on-chain data: mint and freeze authority, top holders, developer balance, "
               "liquidity, holders and age. {ok} of {n} checks passed. Updated every 3 hours.",
        r_h1="Is {sym} safe? Rug check",
        r_lead="{ok} of {n} checks passed for {name}. These are measurements of on-chain data, not an accusation or a "
               "recommendation. A token can pass every check and still fall.",
        r_cols=("Check", "{sym}", "Safe range", "Result"),
        ok="pass", warn="caution", bad="fail",
        chk=dict(mint=("Mint authority", "off", "Can new tokens be printed?"),
                 freeze=("Freeze authority", "off", "Can your tokens be frozen?"),
                 top=("Top holders' share", "under 35%", "A few wallets control the price?"),
                 dev=("Developer's share", "under 5%", "Can the creator dump on buyers?"),
                 liq=("Liquidity", "at least $10k", "Can you sell without crashing it?"),
                 ratio=("Liquidity vs market cap", "at least 1%", "Is the market cap real?"),
                 holders=("Holders", "at least 1,000", "Real demand?"),
                 age=("Age", "older than 30 days", "Survived the first weeks?"),
                 org=("Organic trading", "score 40+", "Real traders or bots?")),
        r_more="How we check: <a href=/blog/how-to-spot-a-rug-pull>7 checks from 10,650 tokens</a>.",
        days="{n} days", years="{n} years",
        # hubs
        hb_title="How to buy Solana meme coins: guides for the top 100 | MemeSonar",
        hb_desc="Step-by-step buying guides for the 100 biggest Solana meme coins, with the real contract address and "
                "slippage for each pool.",
        hb_h1="How to buy Solana meme coins",
        hb_lead="Pick a coin for its buying guide. Every guide uses the real contract address and our safety checks.",
        hr_title="Solana meme coin rug checks: top 100 safety scores | MemeSonar",
        hr_desc="Rug checks for the 100 biggest Solana meme coins: mint and freeze authority, top holders, liquidity and "
                "more, updated every 3 hours.",
        hr_h1="Solana meme coin rug checks",
        hr_lead="Checks passed out of 9 for each of the 100 biggest Solana meme coins.",
        hub_cols=("#", "Coin", "Market cap", "Checks passed"),
        more_h="More about {sym}", m_coin="{sym} price and holders", m_pp="{sym} price prediction",
        m_buy="How to buy {sym}", m_rug="Is {sym} safe?", m_exch="Best exchanges in the EU",
    ),
    "hr": dict(
        pp="/hr/coin/{s}/prognoza", buy="/hr/kako-kupiti/{s}", rug="/hr/provjera/{s}", coin="/hr/coin/{s}",
        buy_hub="/hr/kako-kupiti", rug_hub="/hr/provjera", lb="/hr/solana-meme-coini", exch=EXCH_HR, home="/hr",
        cta="Zatraži pristup", nfa="Nije financijski savjet. Meme coini su izuzetno rizični; većina završi na nuli.",
        pp_title="{name} ({sym}) prognoza cijene: scenariji iz podataka | MemeSonar",
        pp_desc="Prognoza cijene {sym} bez izmišljenih ciljeva: što bi 2x, 5x i 10x značili za market cap tokena {name} "
                "i {pos} od {n} živih signala koji pokazuju gore. Osvježava se svaka 3 sata.",
        pp_h1="{sym} prognoza cijene",
        pp_lead="{name} trenutno vrijedi {price}, a market cap mu je {mcap} (#{rank} Solana meme coin). Umjesto da "
                "nagađamo cijenu, pokazujemo što bi svaki pomak zahtijevao i što naši živi signali sad kažu.",
        sc_h="Što bi {sym} trebao da dođe do svake cijene?",
        sc_cols=("Scenarij", "Cijena", "Potreban market cap", "Usporediv coin danas"),
        sc_names=(("-50%", 0.5), ("Danas", 1.0), ("2x", 2), ("5x", 5), ("10x", 10)),
        sc_none="veće od bilo kojeg meme coina na našoj listi",
        sig_h="Živi signali", sig_lead="{pos} od {n} signala pokazuje gore, {neg} dolje.",
        sig_cols=("Signal", "Sada", "Očitanje"),
        up="gore", down="dolje", flat="neutralno",
        sig=dict(chg="Promjena cijene, 24 h", hold="Promjena broja holdera, 24 h", flow="Kupnje naspram prodaja, 24 h",
                 org="Ocjena organskog trgovanja", liq="Likvidnost naspram market capa", top="Udio najvećih holdera",
                 calls="Izmjereni pozivi influencera"),
        chart_h="Povijest cijene {sym}", chart_src="naše snimke",
        pp_how="Kako ovo čitati: 10x traži deset puta veći market cap od današnjeg, pa provjeri je li ijedan meme coin "
               "danas toliko velik. Signali se mijenjaju svakih nekoliko sati; članovi ih vide uživo s obavijestima.",
        b_title="Kako kupiti {name} ({sym}) na Solani: korak po korak | MemeSonar",
        b_desc="Gdje i kako kupiti {sym}: prava adresa ugovora, najjeftiniji put preko Phantoma i Jupitera, slippage za "
               "bazen od ${liq} i provjera sigurnosti prije kupnje.",
        b_h1="Kako kupiti {name} ({sym})",
        b_lead="{name} je Solana token, pa je najjeftiniji put obično: kupi SOL na mjenjačnici reguliranoj u EU, pošalji "
               "ga u Solana novčanik i zamijeni za {sym}. Uvijek koristi adresu ugovora ispod; lažni tokeni kopiraju ime.",
        addr="Službena adresa ugovora za {sym} (Solana)", copy="Kopiraj",
        steps_h="Korak po korak",
        steps=("Kupi SOL (ili USDC) na mjenjačnici reguliranoj u EU. Vidi <a href={exch}>najbolje mjenjačnice za "
               "Hrvatsku i EU</a>, usporedbu po licenci i naknadama.",
               "Instaliraj Solana novčanik kao što su Phantom ili Solflare i zapiši frazu za oporavak na papir. Nikad je "
               "nikome ne daj, ni nama.",
               "Pošalji SOL s mjenjačnice na adresu svog novčanika. Prvo pošalji mali probni iznos.",
               "Otvori Jupiter (jup.ag) ili swap u novčaniku, zalijepi adresu ugovora za {sym} odozgo i provjeri da se "
               "simbol i logo poklapaju.",
               "Postavi slippage (vidi tablicu ispod za ovaj bazen), potvrdi swap i ostavi malo SOL-a za naknade mreže.",
               "Odluči o izlazu prije kupnje: gdje uzimaš dobit, a gdje režeš gubitak."),
        cex_h="Je li {sym} na centraliziranoj mjenjačnici?",
        cex_yes="Prema našim podacima {sym} se trguje na {n} centraliziranih mjenjačnica. Najpoznatije: {names}. Biraj "
                "onu s EU licencom (vidi <a href={exch}>koje mjenjačnice imaju licencu</a>); nije svaki coin s globalne liste "
                "dostupan korisnicima u EU. Manje mjenjačnice iz tog broja ovdje ne navodimo.",
        cex_small="Prema našim podacima {sym} je na {n} manjih centraliziranih mjenjačnica, nijednoj od poznatih, pa ih ne "
                  "navodimo. Put preko novčanika gore je sigurniji način kupnje.",
        mica_yes="EU licenca",
        cex_no="Nemamo podatak da je {sym} na centraliziranoj mjenjačnici, pa je put preko novčanika gore način kupnje.",
        slip_h="Koliko košta kupnja u bazenu od {liq}",
        slip_sub="Manje tokena od prikazane cijene, bazen s konstantnim produktom, prije naknada",
        slip_cols=("Iznos kupnje", "Manje tokena od prikazanog"),
        safe_h="Prije kupnje: provjera sigurnosti", safe_link="Cijela provjera ruga za {sym} →",
        r_title="Je li {name} ({sym}) siguran? Provjera ruga: prošlo {ok} od {n} | MemeSonar",
        r_desc="Provjera ruga za {sym} iz podataka na blockchainu: mint i freeze authority, najveći holderi, udio "
               "developera, likvidnost, holderi i starost. Prošlo {ok} od {n}. Osvježava se svaka 3 sata.",
        r_h1="Je li {sym} siguran? Provjera ruga",
        r_lead="Za {name} je prošlo {ok} od {n} provjera. To su mjerenja podataka s blockchaina, a ne optužba ni "
               "preporuka. Token može proći sve provjere i svejedno pasti.",
        r_cols=("Provjera", "{sym}", "Sigurno", "Rezultat"),
        ok="prolazi", warn="oprez", bad="pada",
        chk=dict(mint=("Mint authority", "isključen", "Mogu li se tiskati novi tokeni?"),
                 freeze=("Freeze authority", "isključen", "Mogu li ti zamrznuti tokene?"),
                 top=("Udio najvećih holdera", "ispod 35%", "Kontrolira li cijenu nekoliko novčanika?"),
                 dev=("Udio developera", "ispod 5%", "Može li kreator prodati kupcima?"),
                 liq=("Likvidnost", "barem $10k", "Možeš li prodati a da ga ne srušiš?"),
                 ratio=("Likvidnost naspram market capa", "barem 1%", "Je li market cap stvaran?"),
                 holders=("Holderi", "barem 1.000", "Postoji li stvarna potražnja?"),
                 age=("Starost", "starije od 30 dana", "Je li preživio prve tjedne?"),
                 org=("Organsko trgovanje", "ocjena 40+", "Pravi traderi ili botovi?")),
        r_more="Kako provjeravamo: <a href=/hr/blog/kako-prepoznati-rug-pull>7 provjera iz 10.650 tokena</a>.",
        days="{n} dana", years="{n} god.",
        hb_title="Kako kupiti Solana meme coine: vodiči za top 100 | MemeSonar",
        hb_desc="Vodiči korak po korak za kupnju 100 najvećih Solana meme coina, s pravom adresom ugovora i slippageom "
                "za svaki bazen.",
        hb_h1="Kako kupiti Solana meme coine",
        hb_lead="Odaberi coin za vodič za kupnju. Svaki vodič koristi pravu adresu ugovora i naše provjere sigurnosti.",
        hr_title="Provjera ruga za Solana meme coine: ocjene sigurnosti top 100 | MemeSonar",
        hr_desc="Provjere ruga za 100 najvećih Solana meme coina: mint i freeze authority, najveći holderi, likvidnost i "
                "više, osvježeno svaka 3 sata.",
        hr_h1="Provjera ruga za Solana meme coine",
        hr_lead="Broj prođenih provjera od 9 za svaki od 100 najvećih Solana meme coina.",
        hub_cols=("#", "Coin", "Market cap", "Prošlo provjera"),
        more_h="Više o {sym}", m_coin="{sym} cijena i holderi", m_pp="{sym} prognoza cijene",
        m_buy="Kako kupiti {sym}", m_rug="Je li {sym} siguran?", m_exch="Najbolje mjenjačnice u EU",
    ),
}


# ---------- helpers -------------------------------------------------------------------------------------------------

def _P():
    from ui import public
    return public


def _num(s, lang):
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".") if lang == "hr" else s


def _usd(x, lang):
    return _num(_P()._usd(x), lang)


def _price(x, lang):
    return _num(_P()._price(x), lang)


def _load(slug):
    from ui import coins as K
    if not SLUG.fullmatch(slug or ""):
        return None
    r, hist = K.coin(slug)
    if not r:
        return None
    r["a"] = json.loads(r.get("audit") or "{}")
    r["hist"] = hist
    return r


def _dd(s):
    """'Bonk (Bonk)' -> 'Bonk' when a coin's name and symbol are the same."""
    return re.sub(r"(?i)\b([\w$.\-]+(?: [\w$.\-]+)*) \((\1)\)", r"\1", s)


def _names(r):
    sym = (r["symbol"] or "").strip() or r["slug"].upper()
    name = (r["name"] or "").strip() or sym
    return esc(name), esc(sym)


def more(r, lang, skip=""):
    """Chip row linking every page about this coin (used on all of them and on the coin page)."""
    t = T[lang]
    _, sym = _names(r)
    s = r["slug"]
    items = [("coin", t["coin"], t["m_coin"]), ("pp", t["pp"], t["m_pp"]), ("buy", t["buy"], t["m_buy"]),
             ("rug", t["rug"], t["m_rug"])]
    chips = "".join(f"<a href={u.format(s=s)}>{lab.format(sym=sym)}</a>" for k, u, lab in items if k != skip)
    chips += f"<a href={t['exch']}>{t['m_exch']}</a>"
    return f"<h2 class=s>{t['more_h'].format(sym=sym)}</h2><div class=chips>{chips}</div>"


def _lock(lang):
    from ui.blog import L as BL
    t, b = T[lang], BL[lang]
    return f"<div class=lock><p>{b['lock']}</p><a class='btn sm' href={t['home']}#pristup>{t['cta']}</a></div>"


def _table(head, rows, num_from=1):
    h = "".join(f"<th{' class=n' if j >= num_from else ''}>{x}</th>" for j, x in enumerate(head))
    b = "".join("<tr>" + "".join(f"<td{' class=n' if j >= num_from else ''}>{c}</td>" for j, c in enumerate(r)) + "</tr>"
                for r in rows)
    return f"<div class=tw><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"


def _ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj).replace("</", "<\\/") + "</script>"


def _faq_ld(qa):
    return _ld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)}}
        for q, a in qa]})


def _addr(r, lang):
    t = T[lang]
    _, sym = _names(r)
    m = esc(r["mint"])
    return (f"<div class=card style='margin:18px 0'><span class=mut style='font-size:13px'>{t['addr'].format(sym=sym)}"
            f"</span><div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px'><code "
            f"style='font-size:13px;word-break:break-all'>{m}</code><button class='btn g sm' type=button onclick=\""
            f"navigator.clipboard&&navigator.clipboard.writeText('{m}');this.textContent='✓'\">{t['copy']}</button>"
            f"</div></div>")


# ---------- centralised exchanges -----------------------------------------------------------------------------------

# Only well-known exchanges are named; the long tail of small venues in the listing data is counted, never listed.
# True = holds an EU MiCA licence we verified (1 Nov 2026, see the exchanges article); None = not verified by us, so no
# claim either way. Order = how well known.
MAJOR_CEX = [("binance", "Binance", None), ("coinbase", "Coinbase", True), ("okx", "OKX", True),
             ("kraken", "Kraken", True), ("bybit-eu", "Bybit EU", True), ("bybit", "Bybit", None), ("crypto-com", "Crypto.com", True),
             ("bitpanda", "Bitpanda", True), ("bitstamp", "Bitstamp", True), ("bitvavo", "Bitvavo", True),
             ("gemini", "Gemini", True), ("bitget", "Bitget", None), ("kucoin", "KuCoin", None),
             ("gate", "Gate", None), ("mexc", "MEXC", None), ("htx", "HTX", None)]
_CEX_ALIAS = {"gdax": "coinbase", "okex": "okx", "bybit_spot": "bybit", "mxc": "mexc", "huobi": "htx",
              "bitpanda_pro": "bitpanda", "bitpanda-pro": "bitpanda", "crypto_com": "crypto-com", "cryptocom": "crypto-com", "crypto.com": "crypto-com", "gate-io": "gate",
              "gateio": "gate", "gate.io": "gate", "huobi": "htx", "okex": "okx", "coinbase-exchange": "coinbase",
              "coinbase-pro": "coinbase", "binance-com": "binance", "kraken-pro": "kraken"}


def cex_major(names):
    """[(display name, has MiCA licence)] for the well-known exchanges in a listing's names (JSON list or text)."""
    try:
        ids = json.loads(names) if isinstance(names, str) else list(names or [])
    except (ValueError, TypeError):
        ids = re.findall(r"[a-z0-9._\-]+", str(names or "").lower())
    have = {_CEX_ALIAS.get(str(x).lower().strip(), str(x).lower().strip()) for x in ids}
    return [(lab, mica) for key, lab, mica in MAJOR_CEX if key in have]


def cex_short(names, k=5):
    """' · Binance, Coinbase, OKX' (well-known names only) or '' for the coin page's safety table."""
    major = [lab for lab, _m in cex_major(names)[:k]]
    return f" · {', '.join(major)}" if major else ""


def cex_text(o, lang, sym):
    """Plain sentence about centralised listings: count + well-known names, with EU-licence marks."""
    t = T[lang]
    if not (o.get("cex") and o["cex"][0]):
        return t["cex_no"].format(sym=sym)
    major = cex_major(o["cex"][1])
    if not major:
        return t["cex_small"].format(sym=sym, n=o["cex"][0])
    names = ", ".join(f"{lab} ({t['mica_yes']})" if m else lab for lab, m in major)
    return t["cex_yes"].format(sym=sym, n=o["cex"][0], names=names, exch=t["exch"])


# ---------- signals and checks --------------------------------------------------------------------------------------

def signals(r, o, lang):
    """[(label, value text, +1 up / 0 neutral / -1 down)] from live data."""
    t = T[lang]
    S = t["sig"]
    out = []
    c = r.get("chg24h")
    if c is not None:
        out.append((S["chg"], _num(f"{c:+.1f}%", lang), 1 if c > 3 else -1 if c < -3 else 0))
    w = json.loads(r.get("win") or "{}")
    hc = (w.get("24h") or [None, None])[1]
    if hc is not None:
        out.append((S["hold"], _num(f"{hc:+.2f}%", lang), 1 if hc > 0.2 else -1 if hc < -0.2 else 0))
    b, s = r.get("buys24") or 0, r.get("sells24") or 0
    if b + s:
        ratio = b / (b + s)
        out.append((S["flow"], _num(f"{ratio * 100:.0f}% / {100 - ratio * 100:.0f}%", lang),
                    1 if ratio > 0.53 else -1 if ratio < 0.47 else 0))
    org = r.get("organic")
    if org is not None:
        out.append((S["org"], _num(f"{org:.0f}/100", lang), 1 if org >= 60 else -1 if org < 30 else 0))
    if r.get("liq") and r.get("mcap"):
        lr = r["liq"] / r["mcap"]
        out.append((S["liq"], _num(f"{lr * 100:.1f}%", lang), 1 if lr >= 0.03 else -1 if lr < 0.01 else 0))
    top = r["a"].get("topHoldersPercentage")
    if top is not None:
        out.append((S["top"], _num(f"{top:.0f}%", lang), 1 if top < 20 else -1 if top > 40 else 0))
    n = len(o.get("calls") or []) + (o.get("fresh") or 0)
    if n:
        out.append((S["calls"], str(n), 1 if n >= 3 else 0))
    return out


def checks(r, lang):
    """[(key, value text, 'ok'|'warn'|'bad')] for the rug check."""
    t = T[lang]
    a = r["a"]
    out = []
    if "mintAuthorityDisabled" in a:
        out.append(("mint", t["ok"] if a["mintAuthorityDisabled"] else t["bad"], "ok" if a["mintAuthorityDisabled"] else "bad"))
    if "freezeAuthorityDisabled" in a:
        out.append(("freeze", t["ok"] if a["freezeAuthorityDisabled"] else t["bad"],
                    "ok" if a["freezeAuthorityDisabled"] else "bad"))
    if a.get("topHoldersPercentage") is not None:
        v = a["topHoldersPercentage"]
        out.append(("top", _num(f"{v:.0f}%", lang), "ok" if v < 35 else "warn" if v < 50 else "bad"))
    if a.get("devBalancePercentage") is not None:
        v = a["devBalancePercentage"]
        out.append(("dev", _num(f"{v:.1f}%", lang), "ok" if v < 5 else "warn" if v < 15 else "bad"))
    if r.get("liq") is not None:
        out.append(("liq", _usd(r["liq"], lang), "ok" if r["liq"] >= 10000 else "bad"))
        if r.get("mcap"):
            v = r["liq"] / r["mcap"]
            out.append(("ratio", _num(f"{v * 100:.1f}%", lang), "ok" if v >= 0.01 else "warn" if v >= 0.002 else "bad"))
    if r.get("holders") is not None:
        out.append(("holders", _P()._int(r["holders"], lang), "ok" if r["holders"] >= 1000 else "bad"))
    age = _age_days(r.get("created"))
    if age is not None:
        txt = t["years"].format(n=_num(f"{age / 365:.1f}", lang)) if age >= 365 else t["days"].format(n=int(age))
        out.append(("age", txt, "ok" if age >= 30 else "warn"))
    if r.get("organic") is not None:
        out.append(("org", _num(f"{r['organic']:.0f}/100", lang), "ok" if r["organic"] >= 40 else "warn"))
    return out


def _age_days(created):
    if not created:
        return None
    try:
        ts = time.mktime(time.strptime(str(created)[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except ValueError:
        return None
    return max(0.0, (time.time() - ts) / 86400)


def score(r):
    """(passed, total) for hubs and titles."""
    c = checks(r, "en")
    return sum(1 for x in c if x[2] == "ok"), len(c)


# ---------- pages ---------------------------------------------------------------------------------------------------

def prediction(slug, lang):
    from ui import coins as K
    P = _P()
    r = _load(slug)
    if not r:
        return None
    t = T[lang]
    name, sym = _names(r)
    o = K.ours(r["mint"], P.PUBLIC_DELAY_S)
    sig = signals(r, o, lang)
    pos, neg = sum(1 for s in sig if s[2] > 0), sum(1 for s in sig if s[2] < 0)
    rows = [x for x in K.top() if x.get("mcap")]
    sc = []
    for lab, m in t["sc_names"]:
        cap = (r["mcap"] or 0) * m
        peer = min((x for x in rows if x["mint"] != r["mint"] and x["mcap"] >= cap), key=lambda x: x["mcap"], default=None)
        peer_txt = (f"<a href={t['coin'].format(s=peer['slug'])}>{esc(peer['symbol'])}</a> ({_usd(peer['mcap'], lang)})"
                    if peer else t["sc_none"])
        sc.append((f"<b>{lab}</b>", _price((r["price"] or 0) * m, lang), _usd(cap, lang), peer_txt))
    rd = {1: f"<span class=pos>▲ {t['up']}</span>", -1: f"<span class=neg>▼ {t['down']}</span>", 0: f"<span class=mut>– {t['flat']}</span>"}
    sig_rows = [(lab, val, rd[v]) for lab, val, v in sig]
    pts = ([(c["day"], c["c"]) for c in o["candles"]] if len(o["candles"]) >= 7 else
           [(h["ts"], h["price"]) for h in r["hist"] if h.get("price")])
    svg = K.svg_line(pts, color="#2a78d6", label=t["chart_h"].format(sym=sym)) if len(pts) >= 2 else ""
    chart = (f"<div class=card style='padding:18px;margin:20px 0'><b style='font-size:16px'>{t['chart_h'].format(sym=sym)}"
             f"</b> <span class=mut style='font-size:13px'>· {t['chart_src']}</span>{svg}</div>") if svg else ""
    lead = t["pp_lead"].format(name=name, price=_price(r["price"], lang), mcap=_usd(r["mcap"], lang),
                               rank=r.get("rank") or "–")
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={t['coin'].format(s=slug)}>← {sym}</a></div>"
            f"<h1>{t['pp_h1'].format(sym=sym)}</h1><p class=lead>{lead}</p></section>{chart}"
            f"<h2>{t['sc_h'].format(sym=sym)}</h2>{_table(t['sc_cols'], sc)}"
            f"<h2>{t['sig_h']}</h2><p>{t['sig_lead'].format(pos=pos, n=len(sig), neg=neg)}</p>"
            f"{_table(t['sig_cols'], sig_rows)}<p class=note>{t['pp_how']}</p>{_lock(lang)}"
            f"<p class=note>{t['nfa']}</p></article>{more(r, lang, 'pp')}")
    title = t["pp_title"].format(name=r["name"] or sym, sym=r["symbol"] or sym)
    desc = t["pp_desc"].format(name=r["name"] or sym, sym=r["symbol"] or sym, pos=pos, n=len(sig))
    return P._shell(lang, _dd(title), desc, T["en"]["pp"].format(s=slug), T["hr"]["pp"].format(s=slug), _dd(body))


def how_to_buy(slug, lang):
    from ui import coins as K
    from ui.blogviz import grid
    P = _P()
    r = _load(slug)
    if not r:
        return None
    t = T[lang]
    name, sym = _names(r)
    o = K.ours(r["mint"], P.PUBLIC_DELAY_S)
    steps = "".join(f"<li>{s.format(sym=sym, exch=t['exch'])}</li>" for s in t["steps"])
    cex = cex_text(o, lang, sym)
    R = (r.get("liq") or 0) / 2
    slip = ""
    if R > 0:
        sizes = (100, 500, 1000, 5000)
        vals = [100 * x / (R + x) for x in sizes]
        slip = grid(t["slip_h"].format(liq=_usd(r["liq"], lang)), [_usd(x, lang).replace(".0k", "k") for x in sizes],
                    [(sym, [round(v, 1) for v in vals])], sub=t["slip_sub"], cap=50, lang=lang)
    ok, n = score(r)
    safe = (f"<h2>{t['safe_h']}</h2><p>{t['r_lead'].format(ok=ok, n=n, name=name)} "
            f"<a href={t['rug'].format(s=slug)}>{t['safe_link'].format(sym=sym)}</a></p>")
    qa = [(t["b_h1"].format(name=name, sym=sym) + "?", re.sub(r"<[^>]+>", "", t["b_lead"].format(name=name, sym=sym))),
          (t["cex_h"].format(sym=sym), cex)]
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={t['buy_hub']}>← {t['hb_h1']}</a></div>"
            f"<h1>{t['b_h1'].format(name=name, sym=sym)}</h1><p class=lead>{t['b_lead'].format(name=name, sym=sym)}</p>"
            f"</section>{_addr(r, lang)}<h2>{t['steps_h']}</h2><ol>{steps}</ol>{slip}"
            f"<h2>{t['cex_h'].format(sym=sym)}</h2><p>{cex}</p>{safe}{_lock(lang)}<p class=note>{t['nfa']}</p>"
            f"</article>{more(r, lang, 'buy')}")
    title = t["b_title"].format(name=r["name"] or sym, sym=r["symbol"] or sym)
    desc = t["b_desc"].format(sym=r["symbol"] or sym, liq=_usd(r.get("liq"), lang).lstrip("$"))
    return P._shell(lang, _dd(title), desc, T["en"]["buy"].format(s=slug), T["hr"]["buy"].format(s=slug), _dd(body),
                    jsonld=_faq_ld(qa))


def rug_check(slug, lang):
    P = _P()
    r = _load(slug)
    if not r:
        return None
    t = T[lang]
    name, sym = _names(r)
    c = checks(r, lang)
    ok = sum(1 for x in c if x[2] == "ok")
    badge = {"ok": f"<span class=pos>✓ {t['ok']}</span>", "warn": f"<span class=mut>! {t['warn']}</span>",
             "bad": f"<span class=neg>✗ {t['bad']}</span>"}
    rows = [(f"<b>{t['chk'][k][0]}</b><br><span class=mut style='font-size:13px'>{t['chk'][k][2]}</span>", v,
             t["chk"][k][1], badge[s]) for k, v, s in c]
    head = tuple(h.format(sym=sym) for h in t["r_cols"])
    body = (f"<article class=art><section class=ph1><div class=crumb><a href={t['rug_hub']}>← {t['hr_h1']}</a></div>"
            f"<h1>{t['r_h1'].format(sym=sym)}</h1><p class=lead>{t['r_lead'].format(ok=ok, n=len(c), name=name)}</p>"
            f"</section><div class=tw><table><thead><tr>"
            + "".join(f"<th{' class=n' if j in (1,) else ''}>{h}</th>" for j, h in enumerate(head))
            + "</tr></thead><tbody>"
            + "".join(f"<tr><td style='white-space:normal'>{a}</td><td class=n>{b}</td><td class=mut>{d}</td><td>{e}</td></tr>"
                      for a, b, d, e in rows)
            + f"</tbody></table></div>{_addr(r, lang)}<p>{t['r_more']}</p>{_lock(lang)}<p class=note>{t['nfa']}</p>"
            f"</article>{more(r, lang, 'rug')}")
    title = t["r_title"].format(name=r["name"] or sym, sym=r["symbol"] or sym, ok=ok, n=len(c))
    desc = t["r_desc"].format(sym=r["symbol"] or sym, ok=ok, n=len(c))
    return P._shell(lang, _dd(title), desc, T["en"]["rug"].format(s=slug), T["hr"]["rug"].format(s=slug), _dd(body))


def hub(kind, lang):
    from ui import coins as K
    P = _P()
    t = T[lang]
    rows = K.top()
    out = []
    for x in rows:
        x["a"] = json.loads(x.get("audit") or "{}")
        ok, n = score(x)
        link = (t["buy"] if kind == "buy" else t["rug"]).format(s=x["slug"])
        out.append((x.get("rank") or "", f"<a href={link}>{esc(x['symbol'] or x['slug'])}</a> "
                    f"<span class=mut>{esc((x['name'] or '')[:30])}</span>", _usd(x["mcap"], lang), f"{ok}/{n}"))
    key = "hb" if kind == "buy" else "hr"
    body = (f"<section class=ph1><div class=eyebrow>MemeSonar</div><h1>{t[key + '_h1']}</h1>"
            f"<p class=lead>{t[key + '_lead']}</p></section>{_table(t['hub_cols'], out, 2)}{_lock(lang)}")
    en, hr = (T["en"]["buy_hub"], T["hr"]["buy_hub"]) if kind == "buy" else (T["en"]["rug_hub"], T["hr"]["rug_hub"])
    return P._shell(lang, t[key + "_title"], t[key + "_desc"], en, hr, body)


# ---------- daily lists (gainers, trending, new) -------------------------------------------------------------------

LISTS = {
    "gainers": dict(en="/solana-meme-coins/gainers", hr="/hr/solana-meme-coini/rastuci"),
    "trending": dict(en="/solana-meme-coins/trending", hr="/hr/solana-meme-coini/popularni"),
    "new": dict(en="/solana-meme-coins/new", hr="/hr/solana-meme-coini/novi"),
}
LT = {
    "en": dict(
        gainers=("Top Solana meme coin gainers today", "Biggest 24 h gainers among the top 100 Solana meme coins | MemeSonar",
                 "The Solana meme coins that rose most in the last 24 hours, from the top 100 by market cap, with liquidity "
                 "and a rug check for each. Updated every 3 hours.",
                 "The {n} biggest 24 h price gains among the top 100 Solana meme coins (pools with at least $25k "
                 "liquidity, so a tiny pool can't fake a jump).", "24 h change"),
        trending=("Trending Solana meme coins today", "Trending Solana meme coins: most traders in 24 h | MemeSonar",
                  "The Solana meme coins with the most unique traders in the last 24 hours, with volume, buy/sell split and "
                  "a rug check for each. Updated every 3 hours.",
                  "The {n} Solana meme coins most people traded in the last 24 hours (unique traders, not just volume, "
                  "which bots can inflate).", "Traders, 24 h"),
        new=("New Solana meme coins in the top 100", "New Solana meme coins: youngest in the top 100 | MemeSonar",
             "The youngest Solana meme coins that made it into the top 100 by market cap, with age, holders and a rug "
             "check for each. Updated every 3 hours.",
             "The {n} youngest coins in the top 100. New coins are the riskiest: check the rug score before anything "
             "else.", "Age"),
        cols=("#", "Coin", "Price", "24 h", "Market cap", "Checks"), other="Other lists", all="All top 100",
    ),
    "hr": dict(
        gainers=("Solana meme coini s najvećim rastom danas", "Najveći rast u 24 h među top 100 Solana meme coina | MemeSonar",
                 "Solana meme coini koji su najviše porasli u zadnja 24 sata, iz top 100 po market capu, s likvidnošću i "
                 "provjerom ruga za svaki. Osvježava se svaka 3 sata.",
                 "{n} najvećih rasta cijene u 24 h među top 100 Solana meme coina (bazeni s barem $25k likvidnosti, da "
                 "mali bazen ne lažira skok).", "Promjena 24 h"),
        trending=("Popularni Solana meme coini danas", "Popularni Solana meme coini: najviše tradera u 24 h | MemeSonar",
                  "Solana meme coini s najviše različitih tradera u zadnja 24 sata, s volumenom, omjerom kupnji i prodaja i "
                  "provjerom ruga za svaki. Osvježava se svaka 3 sata.",
                  "{n} Solana meme coina kojima je trgovalo najviše ljudi u zadnja 24 sata (različiti traderi, ne samo "
                  "volumen, koji botovi mogu napuhati).", "Tradera, 24 h"),
        new=("Novi Solana meme coini u top 100", "Novi Solana meme coini: najmlađi u top 100 | MemeSonar",
             "Najmlađi Solana meme coini koji su ušli u top 100 po market capu, sa starošću, holderima i provjerom ruga za "
             "svaki. Osvježava se svaka 3 sata.",
             "{n} najmlađih coina u top 100. Novi coini su najrizičniji: prvo pogledaj provjeru ruga.", "Starost"),
        cols=("#", "Coin", "Cijena", "24 h", "Market cap", "Provjere"), other="Ostale liste", all="Svih top 100",
    ),
}
LIST_N = 25


def _pick(kind, rows):
    if kind == "gainers":
        rows = [x for x in rows if (x.get("liq") or 0) >= 25_000 and x.get("chg24h") is not None]
        return sorted(rows, key=lambda x: -x["chg24h"])
    if kind == "trending":
        return sorted([x for x in rows if x.get("traders24")], key=lambda x: -x["traders24"])
    return sorted([x for x in rows if _age_days(x.get("created")) is not None], key=lambda x: _age_days(x["created"]))


def list_links(lang, skip=""):
    lt = LT[lang]
    chips = "".join(f"<a href={LISTS[k][lang]}>{lt[k][0]}</a>" for k in LISTS if k != skip)
    return f"<h2 class=s>{lt['other']}</h2><div class=chips>{chips}<a href={T[lang]['lb']}>{lt['all']}</a></div>"


def daily(kind, lang):
    from ui import coins as K
    P = _P()
    t, lt = T[lang], LT[lang]
    h1, title, desc, lead, metric = lt[kind]
    rows = _pick(kind, K.top())[:LIST_N]
    trs = []
    for i, x in enumerate(rows, 1):
        x["a"] = json.loads(x.get("audit") or "{}")
        ok, n = score(x)
        if kind == "trending":
            m = _num(f"{x['traders24']:,}", lang)
        elif kind == "new":
            d = _age_days(x["created"])
            m = t["days"].format(n=int(d)) if d < 365 else t["years"].format(n=_num(f"{d / 365:.1f}", lang))
        else:
            m = None
        cells = [(str(i), "mut"),
                 (f"<a href={t['coin'].format(s=x['slug'])}>{P._icon(x.get('icon'), x['symbol'])}"
                  f"{esc(x['symbol'] or x['slug'])}</a><div class=mut style='font-size:12px'>"
                  f"{esc((x['name'] or '')[:24])}</div>", ""),
                 (_price(x["price"], lang), "n x"),
                 (_num(P._chg(x["chg24h"]), lang) if x.get("chg24h") is not None else "–", "n"),
                 (_usd(x["mcap"], lang), "n x"), (f"<a href={t['rug'].format(s=x['slug'])}>{ok}/{n}</a>", "n")]
        if m is not None:
            cells.insert(4, (m, "n"))
        trs.append("<tr>" + "".join(f"<td class='{c}'>{v}</td>" for v, c in cells) + "</tr>")
    head = [(h, c) for h, c in zip(lt["cols"], ("", "", "n x", "n", "n x", "n"))]
    if kind != "gainers":
        head.insert(4, (metric, "n"))
    table = ("<div class=tw><table class=coins><thead><tr>" + "".join(f"<th class='{c}'>{h}</th>" for h, c in head)
             + f"</tr></thead><tbody>{''.join(trs)}</tbody></table></div>")
    upd = max((x.get("updated") or 0 for x in rows), default=0)
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(upd)) if upd else ""
    body = (f"<section class=ph1><div class=eyebrow><a href={t['lb']}>{'Solana meme coini' if lang == 'hr' else 'Solana meme coins'}</a></div><h1>{h1}</h1>"
            f"<p class=lead>{lead.format(n=len(rows))}</p></section>{table}"
            f"<p class=mut style='font-size:13px'>{when} · Jupiter, MemeSonar</p>{_lock(lang)}"
            f"<p class=mut style='font-size:13px'>{t['nfa']}</p>{list_links(lang, kind)}")
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    ld = _ld({"@context": "https://schema.org", "@type": "ItemList", "name": h1, "itemListElement": [
        {"@type": "ListItem", "position": i, "name": f"{x['name']} ({x['symbol']})", "url": base + T["en"]["coin"].format(s=x["slug"])}
        for i, x in enumerate(rows, 1)]})
    return P._shell(lang, _dd(title), desc, LISTS[kind]["en"], LISTS[kind]["hr"], body, jsonld=ld)


# ---------- routing and sitemap -------------------------------------------------------------------------------------

_ROUTES = [
    (re.compile(r"/coin/([^/]+)/price-prediction"), prediction, "en"),
    (re.compile(r"/hr/coin/([^/]+)/prognoza"), prediction, "hr"),
    (re.compile(r"/how-to-buy/([^/]+)"), how_to_buy, "en"),
    (re.compile(r"/hr/kako-kupiti/([^/]+)"), how_to_buy, "hr"),
    (re.compile(r"/rug-check/([^/]+)"), rug_check, "en"),
    (re.compile(r"/hr/provjera/([^/]+)"), rug_check, "hr"),
]
_HUBS = {"/how-to-buy": ("buy", "en"), "/hr/kako-kupiti": ("buy", "hr"), "/rug-check": ("rug", "en"),
         "/hr/provjera": ("rug", "hr")}


def match(path):
    """A zero-argument page function for a path this module serves, or None."""
    p = path.rstrip("/") or path
    for kind, v in LISTS.items():
        if p in (v["en"], v["hr"]):
            return lambda: daily(kind, "hr" if p == v["hr"] else "en")
    if p in _HUBS:
        kind, lang = _HUBS[p]
        return lambda: hub(kind, lang)
    for rx, fn, lang in _ROUTES:
        m = rx.fullmatch(p)
        if m:
            s = m.group(1)
            return lambda: fn(s, lang)
    return None


def urls():
    """[(path_en, path_hr, priority)] for ranked coins only."""
    from ui import coins as K
    out = [(T["en"]["buy_hub"], T["hr"]["buy_hub"], "0.7"), (T["en"]["rug_hub"], T["hr"]["rug_hub"], "0.7")]
    out += [(v["en"], v["hr"], "0.8") for v in LISTS.values()]
    for x in K.top():
        s = x["slug"]
        out += [(T["en"][k].format(s=s), T["hr"][k].format(s=s), "0.6") for k in ("pp", "buy", "rug")]
    return out


ROBOTS = ("/how-to-buy", "/hr/kako-kupiti", "/rug-check", "/hr/provjera")
