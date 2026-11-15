"""Stranice tokena (15.11.2026., vlasnik: "Mogu li svi ti novi tokeni koje uhvatimo isto imat svoj page sa statistikom,
feedbackom, podacima koga je zvao i tako dalje, volumen, interpretacijom i mišljenje").

Svaki token našeg midcap svemira (midcap.db članovi + lista "veliki", MC 2M-200M, bondani, nisu u arhivi rugova, meme)
uz današnjih top 100 dobiva javnu stranicu na istoj adresi kao top 100: /coin/<slug> (EN, glavna) i /hr/coin/<slug>.
Mikrokapovi ne (vlasnik: nikakvi resursi na mikrokapove). Token koji izađe iz svemira zadržava zamrznutu stranicu s
napomenom "više ne pratimo".

    store.py      tokenstranice.db: stranice (snimka svih brojki, jednom na sat), slugovi (stari uvijek rade), AI mišljenja
                  i knjiga poziva OpenAI-ja (vlastiti dnevni strop)
    podaci.py     tko ima stranicu (svemir) i sve brojke jedne stranice iz naših baza (midcap.db, veliki.db, dugo.db,
                  public.db, kol.db, holderi.db, insajderi.db); bez mreže
    tumac.py      tumačenje: pravila -> rečenice iz brojki (EN + HR), besplatno
    misljenje.py  mišljenje AI-ja (gpt-5-mini, strogi prompt, najviše jednom dnevno po tokenu, strop 0,30 $/dan)
    povratne.py   komentari i 👍/👎 prijavljenih igrača (league.db, uzorak ui/apjavno: 500 znakova, strop, vlasnik skriva)
    ui/tokenstranica.py   javna stranica (EN + HR), dijelovi za top 100 (ui/public.coin_page), privatni blok na
                  /token/<adresa>, fragment povratnih informacija
run_tokenstranice.py sat: osvježavanje svih stranica + mala serija mišljenja, jedan red u logu (run_sched, svaki sat).
"""
