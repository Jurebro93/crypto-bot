"""Makro influenceri (15.11.2026., vlasnik: "Slažem se s prijedlogom koraka za plan makroinfluencera s dopunama
kritičara"): kripto računi 100k+ čije izjave o smjeru tržišta (BTC / ETH / SOL / altovi / memeovi / ukupno) mjerimo
zaključanim pravilima prema stvarnom kretanju; tri odvojene ocjene (prediktivna kvaliteta, ekonomska vrijednost,
integritet), brisanja kao "naknadno nedostupno", indeks konsenzusa najtočnijih kao DEMO ulaz u veliki/makro.

Pilot 50 računa prvo; proširenje na 300 tek kad provjera klasifikacije prođe (makroinf/quality.py) — 15.11. navečer
vlasnik je izričitim nalogom naložio proširenje na 300-500 najredovitijih računa (discover.py: vrata nadjačana nalogom,
zapisano), dnevno praćenje svih, biblioteku svih objava i tumačenje (raspoloženje, teme). 16.11. vlasnik: "možeš
pratiti influencere od 30k+ followera i dodaj ih na listu": prag 30k pratitelja, strop 800 računa, drugi val
proširenja s vlastitim stropovima troška (discover.record_order2 / step2). Moduli:
  store     makroinf.db, konfiguracija, stropovi troška (twitterapi, OpenAI) po fazi
  racuni    sjeme računa, vlasnikova datoteka racuni_vlasnik.json, razrješenje handleova, kandidati za imena bez poznatog handlea
  fetch     mjesečne kvote napredne pretrage + zadnjih 100 objava, dnevno inkrementalno
  classify  gpt-5-mini, strogi JSON, 20 objava po zahtjevu, revizijski trag (model, verzija upita)
  prices    istina: BTC / ETH / SOL dnevno + satno, košara altova i memeova (CoinGecko, keširano)
  rules     ZAKLJUČANA pravila mjerenja (RULES_VERSION), epizode, registar teza, bazne strategije
  score     tri ocjene, Wilson, skupljanje (shrinkage), "nedovoljno dokaza"
  deleted   ponovna provjera po id-u na +1 / +7 / +30 d, stanja bez optužbi
  index     klasteri, indeks konsenzusa, walk-forward bez curenja, dodatni EV, automatsko isključivanje
  quality   300 stratificiranih uzoraka, kritičar na ~100, preciznost / odziv po kategoriji, vrata proširenja
  report    log linije, kartica, MCP, kritičar, jutarnji izvještaj
  public    javne stranice (iza vlasnikova prekidača makroinf_javno), sve indeksirane, raspoloženje i teme
  discover  proširenje po nalogu vlasnika: otkrivanje, proba, odabir po redovitosti, procjena i trošak po fazi
  mood      raspoloženje (udio bikovskih / medvjeđih / neutralnih, ponderirano točnošću, pravilo presude, izvori)
  teme      teme dana (jeftini model, strop unutar dnevnog; rječnik kad nema modela)
  library   biblioteka svih spremljenih objava s filtrima
  appviews  tumačenje i biblioteka u aplikaciji (tab Makro: Pregled | Biblioteka)
  run       orkestracija (krug svakih 10 min, noćno ocjenjivanje)
"""
