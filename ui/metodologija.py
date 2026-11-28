"""/hr/metodologija, /methodology (28.11.2026): what every measure means and how it is checked, at concept level only.
Never weights, thresholds, formulas, internal services or table names (tests/test_naslovnica_offline.py checks the text
with the same patterns as tests/test_skrivanje_offline.py). Sources are named as "javni lanac, licencirani tržišni podaci".
"""
from ui.html import esc

T = {
    "hr": dict(
        title="Metodologija MemeSonara: kako mjerimo pozive i novčanike",
        desc="Što znači svaka mjera na MemeSonaru i kako je provjeravamo: izvan uzorka, uz stvarni trošak od najmanje "
             "3 %, s kašnjenjem i s brojanjem promašenih ulaza.",
        h1="Kako mjerimo",
        lead="Svaki broj na MemeSonaru je mjerenje prošlih događaja. Ovdje piše što koji broj znači i kako ga "
             "provjeravamo, bez skrivenih pretpostavki u našu korist.",
        rules_h="Četiri pravila za svaki broj",
        rules=[("Izvan uzorka", "Ocjenu provjeravamo samo na danima koje nije vidjela: bilježimo je točno onakvu kakva "
                "je bila u trenutku prikaza, a ishod gledamo tek poslije. Kad se pravilo ocjene promijeni, brojanje "
                "kreće ispočetka."),
               ("Stvarni trošak, nikad ispod 3 %", "Svaki rezultat „nakon troška” uključuje kupnju i prodaju: naknade "
                "i utjecaj na cijenu u stvarnoj likvidnosti tokena. Kad je izračunati trošak manji od 3 % za kupnju i "
                "prodaju zajedno, računamo 3 %."),
               ("Kašnjenje", "Nitko ne kopira u istoj sekundi. Kopiranje novčanika i poziva mjerimo kao da kasnimo "
                "5 sekundi, 30 sekundi i 2 minute, po cijeni koja je tada stvarno bila."),
               ("Promašeni ulazi se broje", "Kad za ulaz ne postoji stvarna cijena, ulaz ostaje u statistici kao "
                "promašen. Ne bacamo ga i ne zamjenjujemo boljom cijenom.")],
        sections=[
            ("influenceri", "Pozivi influencera", [
                "Poziv je objava na X-u koja imenuje Solana token. Mjerimo što je cijena napravila od minute objave: "
                "sat kasnije, dan kasnije, najviši vrh u danu i je li token završio kao rug.",
                "Brojimo samo čiste pozive: ne kasne pozive (nakon što je cijena već naglo narasla), ne pozive nađene "
                "tek pretragom tokena koji su već narasli, i ne račune koji su botovi.",
                "Javno prikazujemo pozive starije od 24 sata. Uz svaki profil piše koliko je poziva izmjereno; s malo "
                "poziva ne donosimo presudu."]),
            ("novcanici", "Novčanici i osobe", [
                "Tražimo novčanike koji opetovano kupe prije naglog rasta tokena i prodaju u rast. Jedan sretan trade "
                "nije dovoljan: obrazac se mora ponoviti i potvrditi na kasnijim podacima.",
                "Osoba je skupina novčanika za koje javni lanac pokazuje da ih vjerojatno vodi ista strana (zajedničko "
                "financiranje, prijenosi, kupnje u istom trenutku). To je statistička veza, a ne tvrdnja o tome tko je "
                "netko.",
                "Bundle novčanici su skupine koje kupuju zajedno i time pomiču cijenu; označavamo ih zasebno.",
                "Kopirljivost odgovara na jedno pitanje: da smo kopirali svaku kupnju i prodaju tog novčanika ili "
                "influencera s kašnjenjem, nakon stvarnog troška, bi li rezultat bio u plusu, i drži li se to i na "
                "novijim danima."]),
            ("rizik", "Rizik tokena", [
                "Provjera ruga gleda znakove koji su prije prethodili rugovima i naglim slomovima: tko drži ponudu, "
                "može li se token prodati, ovlasti nad tokenom i stanje likvidnosti.",
                "Presuda se uspoređuje s onim što se dogodilo idući dan. Koliko je puta presuda bila točna u zadnjih 30 "
                "dana piše uz nju."]),
            ("tocnost", "Točnost uz svaku ocjenu", [
                "Uz ocjenu piše koliko je puta bila točna u zadnjih 30 dana, na koliko slučajeva, i raspon u kojem je "
                "prava točnost vjerojatno. Za usporedbu navodimo koliko se isto dogodilo kod svih tokena, da se vidi "
                "pomaže li ocjena uopće.",
                "Dok slučajeva nema dovoljno, piše „premalo podataka”, a ne broj."]),
            ("izvori", "Izvori podataka", [
                "Javni lanac (transakcije, prijenosi, stanja), licencirani tržišni podaci (cijene, likvidnost, "
                "volumen) i javne objave na X-u. Sve mjere računamo sami.",
                "Ne objavljujemo težine, pragove ni formule ocjena: korisnik vidi rezultat, veličinu uzorka i "
                "kratke razloge."]),
        ],
        not_h="Što ne tvrdimo",
        nots=["Ne tvrdimo da imamo profitabilan trading bot i ne trgujemo umjesto korisnika.",
              "Prošli rezultati ne predviđaju buduće. Memecoini su vrlo rizični.",
              "Podaci, ne financijski savjet."],
        more="Pogledaj cijene", more_href="/hr/cijene", check="Provjeri influencera", check_href="/hr/provjeri-influencera"),
    "en": dict(
        title="MemeSonar methodology: how we measure calls and wallets",
        desc="What every measure on MemeSonar means and how we check it: out of sample, with a real cost of at least "
             "3%, with a delay and with missed entries counted.",
        h1="How we measure",
        lead="Every number on MemeSonar is a measurement of past events. This page says what each number means and how "
             "we check it, with no hidden assumptions in our favour.",
        rules_h="Four rules for every number",
        rules=[("Out of sample", "A score is checked only on days it had not seen: we record it exactly as it was "
                "shown and look at the outcome only afterwards. When the rule behind a score changes, the count starts "
                "again."),
               ("Real cost, never below 3%", "Every result “after cost” includes the buy and the sell: fees and the "
                "price impact in the token's real liquidity. When the computed cost of the buy and sell together is "
                "under 3%, we use 3%."),
               ("Delay", "Nobody copies in the same second. Copying wallets and calls is measured as if we were 5 "
                "seconds, 30 seconds and 2 minutes late, at the price that was really there then."),
               ("Missed entries count", "When there is no real price for an entry, the entry stays in the numbers as "
                "missed. We do not drop it or replace it with a better price.")],
        sections=[
            ("influencers", "Influencer calls", [
                "A call is a post on X that names a Solana token. We measure what the price did from the minute of the "
                "post: an hour later, a day later, the day's peak and whether the token ended as a rug.",
                "We count clean calls only: not late calls (after the price had already risen sharply), not calls "
                "found only by searching tokens that had already risen, and not accounts that are bots.",
                "Public pages show calls older than 24 hours. Every profile says how many calls were measured; with "
                "few calls we give no verdict."]),
            ("wallets", "Wallets and people", [
                "We look for wallets that buy before a sharp rise and sell into it, again and again. One lucky trade is "
                "not enough: the pattern has to repeat and hold on later data.",
                "A person is a group of wallets that the public chain shows are probably run by the same party (shared "
                "funding, transfers, buys at the same moment). It is a statistical link, not a statement about who "
                "anyone is.",
                "Bundle wallets are groups that buy together and so move the price; we mark them separately.",
                "Copyability answers one question: had we copied every buy and sell of this wallet or influencer with "
                "a delay, after the real cost, would the result have been in profit, and does it hold on newer days."]),
            ("risk", "Token risk", [
                "The rug check looks at signs that came before past rugs and sharp collapses: who holds the supply, "
                "whether the token can be sold, authorities over the token and the state of its liquidity.",
                "The verdict is compared with what happened the next day. How often the verdict was right in the last "
                "30 days is shown next to it."]),
            ("accuracy", "Accuracy next to every score", [
                "Next to a score it says how often it was right in the last 30 days, on how many cases, and the range "
                "the true accuracy probably lies in. For comparison we show how often the same happened across all "
                "tokens, so you can see whether the score helps at all.",
                "Until there are enough cases it says “too little data”, not a number."]),
            ("sources", "Data sources", [
                "The public chain (transactions, transfers, balances), licensed market data (prices, liquidity, "
                "volume) and public posts on X. We compute every measure ourselves.",
                "We do not publish the weights, thresholds or formulas of scores: you see the result, the sample size "
                "and short reasons."]),
        ],
        not_h="What we do not claim",
        nots=["We do not claim to have a profitable trading bot, and we do not trade for users.",
              "Past results do not predict future ones. Memecoins are very risky.",
              "Data, not financial advice."],
        more="See pricing", more_href="/pricing", check="Check an influencer", check_href="/check-influencer"),
}

CSS = """<style>
.mt-rules{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin:0 0 28px}
.mt-rules div{border:1px solid var(--line);border-radius:18px;padding:18px;background:#fff}
.mt-rules b{display:block;font-size:17px;margin-bottom:6px}.mt-rules span{color:var(--mut);font-size:15.5px}
.mt-sec{max-width:760px}.mt-sec p{font-size:16.5px}
@media(max-width:760px){.mt-rules{grid-template-columns:1fr}}
</style>"""


def page(lang):
    from ui import naslovnica as N
    from ui import public as P
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    rules = "".join(f"<div><b>{esc(h)}</b><span>{esc(d)}</span></div>" for h, d in t["rules"])
    secs = "".join(f"<h2 id={sid}>{esc(h)}</h2>" + "".join(f"<p>{esc(p)}</p>" for p in ps) for sid, h, ps in t["sections"])
    nots = "".join(f"<li>{esc(x)}</li>" for x in t["nots"])
    body = (f"{CSS}<section class=ph1><h1>{t['h1']}</h1><p class=lead>{t['lead']}</p></section>"
            f"<h2>{t['rules_h']}</h2><div class=mt-rules>{rules}</div><div class=mt-sec>{secs}"
            f"<h2>{t['not_h']}</h2><ul>{nots}</ul>"
            f"<p><a class='btn p' href={t['check_href']}>{t['check']}</a> <a class='btn g' href={t['more_href']}>"
            f"{t['more']}</a></p></div>")
    en, hr = N.PATHS["method"]
    return P._shell(lang, t["title"], t["desc"], en, hr, body)
