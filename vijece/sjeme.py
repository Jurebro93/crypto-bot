"""Vijeće: Claude's first four proposals, stored once (18.11., vlasnik: "neka alat ... odlučuje ... na što usmjeriti sve
resurse, i zašto"; CLAUDE.md: "kako više učiti za manje novca").

Each is a suggestion note under Claude's council key with the measured numbers in evidence and no proposed_change
(class kod: switching a job off is a change of code / start.sh, done by the coding session once OpenAI and Grok, the
reviewers, agree). Stored once (trade settings vijece_claude_1811); the numbers are the ones measured up to 18.11. and
are not recomputed here.
"""
import time

from trade import settings
from ui import assistnotes
from vijece import store

ONCE_KEY = "vijece_claude_1811"

PRIJEDLOZI = (
    {"title": "Ugasiti praćenje 400 KOL računa preko twitterapi (oko 2,70 $ dnevno) dok moć poziva ne izdvoji račune",
     "interpretation": ("Kopiranje poziva influencera nakon troška daje −7,4 % po tradeu (n=308), a čitanje vremenskih "
                        "crta praćenih računa preko twitterapi stajalo je 14,00 $ od 11. do 17.11. Plaćamo podatke za "
                        "strategiju koja je izmjereno u minusu."),
     "improvement": ("Zaustaviti redovito čitanje vremenskih crta 400 KOL računa. Kad moć poziva izdvoji račune s donjom "
                     "granicom iznad nule, pratiti samo njih. Neto zarada: ušteda troška podataka bez gubitka dokazanog "
                     "signala. Mjerenje: trošak twitterapi po danu u dnevnom retku troška; broj računa koje moć poziva "
                     "izdvoji."),
     "evidence": {"kopiranje_poziva_influencera_nakon_troska_pct": -7.4, "n": 308,
                  "twitterapi_timeline_usd": 14.00, "razdoblje": "11.-17.11."}},
    {"title": "Ugasiti OpenAI klasifikaciju makro objava",
     "interpretation": ("Klasifikacija makro objava stajala je 18,16 $ u 3 dana. Indeks 10 najtočnijih računa pogađa 32 %, "
                        "a pravilo „uvijek bull” 34 % (n=158): indeks ne bije najjednostavniju usporedbu."),
     "improvement": ("Zaustaviti OpenAI klasifikaciju makro objava dok indeks na neviđenim danima ne bude bolji od pravila "
                     "„uvijek bull”. Neto zarada: ušteda oko 6 $ dnevno bez gubitka ulaza koji zarađuje. Mjerenje: OpenAI "
                     "trošak po vrsti u dnevnom retku troška."),
     "evidence": {"trosak_usd": 18.16, "dana": 3, "indeks_top10_pogodak_pct": 32, "uvijek_bull_pogodak_pct": 34, "n": 158}},
    {"title": ("Insajderi: jedan noćni prolaz umjesto 60.000 Helius kredita dnevno; ugasiti potragu za sporednim "
               "novčanicima influencera"),
     "interpretation": ("Kopiranje insajdera daje −2,7 % po tradeu (n=1043). Potraga za sporednim novčanicima influencera "
                        "troši 5.000 kredita dnevno i nije potvrdila nijednu grupu. Prolaz insajdera je 18.11. držao bravu "
                        "teških poslova dulje od 30 minuta i zaustavio učenje."),
     "improvement": ("Insajdere računati jednom, noću (01–06), umjesto prolaza tijekom dana; potragu za sporednim "
                     "novčanicima ugasiti. Neto zarada: manje Helius kredita i slobodna brava teških poslova za učenje. "
                     "Mjerenje: Helius krediti po poslu u dnevnom retku troška; čekanje učenja na bravu."),
     "evidence": {"insajderi_kopiranje_pct": -2.7, "n": 1043, "helius_kredita_dnevno": 60000,
                  "sporedni_novcanici_kredita_dnevno": 5000, "potvrdenih_grupa": 0,
                  "brava_teskih_poslova_min_18_11": "30+", "posljedica": "učenje je čekalo"}},
    {"title": "Ugasiti PumpPortal tok tradeova novih pump.fun tokena",
     "interpretation": ("Tok tradeova novih pump.fun tokena stajao je 0,58 SOL u 5 dana (11.–15.11.) za tokene kojima bot "
                        "više ne trguje (fokus je na midcapovima). Sada troši 0,005–0,015 SOL dnevno."),
     "improvement": ("Ugasiti pretplatu na tradeove novih pump.fun tokena; ostaviti tradeove otvorenih pozicija i praćenih "
                     "novčanika. Neto zarada: mala ušteda SOL-a na podacima o tokenima kojima bot ne trguje. "
                     "Mjerenje: PumpPortal SOL po danu u dnevnom retku troška."),
     "evidence": {"pumpportal_sol": 0.58, "dana": 5, "razdoblje": "11.-15.11.", "sada_sol_dnevno": "0,005-0,015",
                  "razlog": "bot više ne trguje novim pump.fun tokenima (fokus midcap)"}},
)


def jednom(con, now=None, log=print):
    """Store PRIJEDLOZI once. [note id] of what was written ([] when it ran before)."""
    if settings.raw(con).get(ONCE_KEY):
        return []
    store.ensure(con)
    ids = []
    for p in PRIJEDLOZI:
        d = assistnotes.submit_suggestion(con, store.CLAUDE_KID, p["title"], p["interpretation"], p["improvement"],
                                          {"vijece": "sjeme", **p["evidence"]}, None)
        ids.append(d["id"])
    settings.put(con, ONCE_KEY, {"ts": int(now or time.time()), "ids": ids}, "vijeće")
    store.reci(log, "sjeme: ", f"Claudeova {len(ids)} prijedloga zapisana (#{', #'.join(map(str, ids))}); ocjenjuju ih "
                               "OpenAI i Grok")
    return ids
