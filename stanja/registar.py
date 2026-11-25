"""The registry: every state machine of the app, declared once (see stanja/__init__.py).

A machine = M(key, title, area, store, states, moves, who, ...):
  key      a stable id (English, snake_case): what the MCP tool and the page address it by
  title    the Croatian name the owner reads
  area     novac (real money) | strategije | odobrenja | podaci (collection, paid budgets) | posao (jobs, ops) |
           racuni (accounts) | sucelje (the browser)
  store    where the state lives (table.column, settings key, file, "u memoriji procesa" = lost at a deploy)
  states   {literal exactly as the code writes it: the Croatian word a person reads}. A derived state that has no
           literal in the code (a phase read from several columns) is written in angle brackets: "<wide>".
  moves    [(from, to, what performs it and when)]; "*" = any state, "-" = the row does not exist yet
  who      who may move it: vlasnik | program | Grok | sat (the clock)
  scan     [(source file, column or key name)]: where tests/test_stanja_offline.py reads the real literals
  also     more files a declared literal may be mentioned in (for the "dead state" check only)
  extra    literals the scan finds next to the same column name that belong to something else (said why)
  caveats  what a reader must know before trusting the state (found 17.11.; Croatian, the owner reads them)
  board    True: stanja/ploca.py shows its state now

Nothing here is executed by trading code. Changing a literal here changes no behaviour: it makes the test fail until
the code and the registry agree again, which is the point.
"""


class Machine:
    __slots__ = ("key", "title", "area", "store", "states", "moves", "who", "scan", "also", "extra", "caveats", "board")

    def __init__(self, key, title, area, store, states, moves=(), who="program", scan=(), also=(), extra=(),
                 caveats=(), board=False):
        self.key, self.title, self.area, self.store = key, title, area, store
        self.states, self.moves, self.who = dict(states), tuple(moves), who
        self.scan, self.also, self.extra = tuple(scan), tuple(also), frozenset(extra)
        self.caveats, self.board = tuple(caveats), bool(board)

    def label(self, literal):
        """The Croatian word for a state; the literal itself when it is not declared (never raises)."""
        return self.states.get(literal, str(literal))

    def as_dict(self):
        return {"key": self.key, "title": self.title, "area": self.area, "store": self.store, "who": self.who,
                "states": [{"state": k, "label": v} for k, v in self.states.items()],
                "moves": [{"from": a, "to": b, "by": c} for a, b, c in self.moves], "caveats": list(self.caveats)}


M = Machine
AREAS = {"novac": "Pravi novac", "strategije": "Strategije", "odobrenja": "Odobrenja", "podaci": "Podaci i plaćeni API-ji",
         "posao": "Pozadinski poslovi", "racuni": "Korisnički računi", "sucelje": "Sučelje (preglednik)"}
OC = {"open": "otvoreno", "closed": "zatvoreno"}

MACHINES = [
    # ---------------------------------------------------------------- pravi novac ------------------------------------
    M("autopilot_switch", "Autopilot (glavni prekidač)", "novac", "trade.db settings 'on' + env TRADE_LIVE + ključ",
      {"<live>": "uključen, kupuje pravim novcem", "<dry>": "uključen, ali bez ključa: kupnje su probne",
       "<off>": "isključen: automatske kupnje idu kao probne"},
      [("<off>", "<live>", "vlasnik: prekidač na stranici Autopilot (/pravi-trade/switch)"),
       ("<live>", "<off>", "vlasnik: prekidač ili „Prodaj sve”")], who="vlasnik",
      caveats=("Isključen prekidač ne blokira kupnje nego ih pretvara u probne (pozicija 'dry', status 'open').",
               "Isto stanje ima tri imena: 'dry' u bazi, 'trial' u MCP-u, „probno” na stranici.",
               "„Hitno zaustavi sve” mijenja samo ovaj prekidač, ne kill switch."), board=True),
    M("kill_switch", "Kill switch (datoteka STOP)", "novac", "datoteka trade/STOP",
      {"<active>": "aktivan: svaka kupnja je blokirana", "<clear>": "nije aktivan"},
      [("<clear>", "<active>", "ručno: stvoriti datoteku trade/STOP na poslužitelju"),
       ("<active>", "<clear>", "ručno: obrisati datoteku")], who="vlasnik",
      caveats=("Nijedan gumb u aplikaciji ga ne pali ni gasi; stranica i MCP ga ne prikazuju u polju mode.",), board=True),
    M("sell_all", "Prodaj sve", "novac", "trade.db settings 'sell_all' (0 ili vrijeme)",
      {"<idle>": "ne traje", "<running>": "u tijeku: prodaje svaku otvorenu poziciju"},
      [("<idle>", "<running>", "vlasnik: „Prodaj sve” (ujedno gasi Autopilot)"),
       ("<running>", "<idle>", "program: kad više nema nijedne otvorene pozicije")], who="vlasnik",
      caveats=("Nema roka: pozicija koja se ne da prodati drži ga zauvijek (pokušaj svakih 30 s).",
               "Ponovno paljenje Autopilota ga ne briše, pa se i nova pozicija odmah prodaje."), board=True),
    M("real_money_switch", "Prekidači pravog novca po strategiji", "novac",
      "trade.db settings 'flag:pravi_novac_sve|izvori|oscilator|veliki|nauceno|risk_off'",
      {"live": "uključeno: strategija smije kupovati pravim novcem", "off": "isključeno"},
      [("off", "live", "vlasnik na stranici (bez dokaza: vlasnikov prekidač)"), ("live", "off", "vlasnik; nalog 15.11. jednom"),
       ("*", "*", "nalog vlasnika 18.11. jednom i uvjetno: pravi_novac_nauceno uključen i pravi_novac_veliki isključen "
                  "samo ako ispravljeni test učenja (bez curenja budućnosti) potvrdi plus uz prag +1 %; inače čeka vlasnika")],
      who="vlasnik", also=("trade/settings.py",),
      caveats=("Prekidač prima i 'shadow' i 'paper', a oba znače isključeno.",
               "Oscilator nema svoju granu u izvršitelju: njegov prekidač gleda samo run_trade.",
               "pravi_novac_nauceno i pravi_novac_veliki dijele iste stropove (otvorene pozicije, kupnje dnevno, dnevni "
               "gubitak) i isti pravi račun: jedan token drži samo jedno od ta dva pravila.",
               "pravi_novac_risk_off (23.11.) pali vlasnik dodirom na stranici Autopilot uz potvrdu; jednokratni nalog "
               "vlasnika 23.11. (settings.riskoff_order_2311, do 24.11. 12:00 UTC) postoji, ali još nije spojen na "
               "pokretanje; isti dodir uključuje i pravi_novac_veliki i skida pauzu od 19.11.; radi samo dok je makro "
               "risk-off jedini filtar (najviše 2 pozicije, 0,1 SOL, trošak kruga najmanje 4 %); gašenje ne dira "
               "otvorene pozicije."), board=True),
    M("flag", "Zastavice (off / sjena / demo / uživo)", "novac", "trade.db settings 'flag:<ime>' {mode, since, who}",
      {"off": "isključeno", "shadow": "sjena (samo mjeri)", "paper": "demo račun", "live": "uživo"},
      [("*", "off", "uvijek dopušteno"), ("off", "paper", "uz paper_refusal"),
       ("*", "live", "samo uz dokaz (live_refusal); NEVER_LIVE zastavice nikad")], who="vlasnik",
      scan=(("trade/settings.py", "mode"),),
      caveats=("„Uključeno” kod nekih zastavica znači 'live', kod drugih 'paper' (midcap, moonshot).",), board=True),
    M("day_loss_stop", "Dnevni gubitak (auto-stop)", "novac", "izvedeno pri svakoj kupnji iz trade.db (nije spremljeno)",
      {"<allowed>": "kupnje dopuštene", "<stopped>": "stoji do ponoći (Zagreb)"},
      [("<allowed>", "<stopped>", "program: dnevni rezultat ≤ −strop"), ("<stopped>", "<allowed>", "sat: ponoć po Zagrebu")],
      who="sat", caveats=("Dnevni rezultat se računa na dva načina (naknade naloga dana / naknade pozicije), pa zbroj "
                          "po strategijama ne mora biti jednak broju koji zaustavlja.",), board=True),
    M("position", "Prava pozicija (životni ciklus)", "novac", "trade.db positions.status",
      {"pending": "kupnja u tijeku", "open": "otvorena", "closed": "zatvorena", "blocked": "blokirana (nije kupljeno)",
       "failed": "nije prošla"},
      [("-", "pending", "executor.buy prije swapa"), ("-", "blocked", "kill switch, stropovi, provjere"),
       ("pending", "open", "swap potvrđen (buy ili reconcile_pending)"), ("pending", "failed", "swap pao"),
       ("open", "closed", "executor.sell; prazan novčanik; reconcile prodaja")],
      scan=(("trade/executor.py", "status"), ("run_trade.py", "status")),
      caveats=("Zatvaranje (sell) i završetak kupnje ne provjeravaju trenutno stanje retka.",
               "Dnevnik, MCP popis i dio stranice ne prikazuju 'pending'.",
               "'closed' može značiti i „novčanik je bio prazan”, bez prodaje.")),
    M("position_mode", "Način pozicije", "novac", "trade.db positions.mode",
      {"live": "pravi novac", "dry": "probno (bez swapa)"}, [("-", "live", "Autopilot uključen i ključ postoji"),
                                                              ("-", "dry", "inače")],
      scan=(("trade/executor.py", "mode"),)),
    M("order", "Nalog (swap)", "novac", "trade.db orders.status",
      {"ok": "prošao", "failed": "pao", "blocked": "blokiran", "dry": "probni", "pending": "poslan, čeka potvrdu",
       "wait": "čeka (backoff prodaje)", "noop": "ništa za prodati"},
      [("-", "pending", "namjera prodaje prije swapa"), ("pending", "ok", "red se briše i piše novi"),
       ("pending", "failed", "reconcile nakon prekida")],
      scan=(("trade/executor.py", "status"), ("run_trade.py", "status")), extra=("Success",),
      caveats=("'wait' i 'noop' postoje samo kao povratna vrijednost, ne u bazi.",
               "Bez ključa svaki prolaz upisuje novi 'failed' red (jedan u sekundi).")),
    M("sell_request", "Ručna prodaja jedne pozicije", "novac", "trade.db settings 'sell_req' {id pozicije: udio}",
      {"<none>": "nema zahtjeva", "<queued>": "u tijeku"},
      [("<none>", "<queued>", "vlasnik (gumb Prodaj), odobren Grokov zahtjev, Grok autotrade"),
       ("<queued>", "<none>", "program: prodaja prošla ili pozicija više nije otvorena")], who="vlasnik, Grok",
      caveats=("Nema roka: neuspjela prodaja ostaje u redu.",
               "Grok dobiva 'executed' čim je zahtjev stavljen u red, ne kad je prodaja prošla.")),
    M("cost_measurement", "Mjerenje troška kruga (jednokratno, pravi novac)", "novac",
      "trade.db settings 'mjerenje_troska_1811' (JSON, polje status)",
      {"ceka": "čeka uvjete za sljedeći ulog", "kupnja": "kupnja poslana (zapisano prije swapa)",
       "prodaja": "kupljeno, prodaje cijelu količinu",
       "prodaja_kasni": "prodaja nepotvrđena u 120 s: pokušaj svake 2 min, najviše 15 (30 min); više ništa ne kupuje",
       "gotovo": "sva tri uloga izmjerena", "odustalo": "prekinuto (razlog i otvoreno u zapisu)"},
      [("-", "ceka", "program: prvi prolaz trade petlje nakon deploya (run_trade._mjerenje_once)"),
       ("ceka", "ceka", "program: uvjet nije ispunjen (jedan redak, ponovno za 30 min)"),
       ("ceka", "kupnja", "program: Autopilot uživo, bez kill switcha i „Prodaj sve”, stanje ≥ 1 + ulog + 0,05 SOL"),
       ("kupnja", "prodaja", "program: executor.buy potvrdio swap (ili reconcile_pending nakon restarta)"),
       ("kupnja", "ceka", "program: kupnja pala, a swap sigurno nije prošao (još jedan pokušaj, najviše jednom)"),
       ("prodaja", "ceka", "program: executor.sell potvrdio prodaju, slijedi veći ulog nakon 20 s"),
       ("prodaja", "gotovo", "program: prodan i treći ulog"),
       ("prodaja", "prodaja_kasni", "program: prodaja nepotvrđena u 120 s ili nakon 3 pokušaja (nakon restarta 1); "
                                    "preostali ulozi otkazani"),
       ("prodaja_kasni", "odustalo", "program: prodaja potvrđena (rezultat uloga zapisan), poziciju zatvorio netko "
                                     "drugi („Prodaj sve”, gumb vlasnika), ili 15 pokušaja bez potvrde"),
       ("*", "odustalo", "program: izvršitelj odbio kupnju, 24 h bez uvjeta, nesklad knjige, pozicija zatvorena izvana")],
      who="program", scan=(("trade/mjerenje.py", "status"),),
      extra=("open", "pending", "ok"),   # trade.db positions.status / orders.status in the same file's SQL
      caveats=("Jednokratno: nakon 'gotovo' ili 'odustalo' se više nikad ne pokreće (isti ključ je i brava).",
               "Pozicija mjerenja nema automatski stop (nema demo par u league.db): ako prodaja ne prođe u 120 s, "
               "mjerenje je pokušava prodati još 30 min (svake 2 min, 15 puta); nakon toga ostaje na stranici "
               "Autopilot (gumbi za prodaju) i prodaje je „Prodaj sve”.",
               "U 'prodaja_kasni' svaki poziv prodaje se broji, i kad izvršitelj odgovori da još čeka svoj razmak "
               "nakon neuspjelih prodaja (5, 10, 20 ... do 600 s): stvarnih pokušaja swapa je manje od 15.",
               "Uz nadjačavanje (ulozi 0,3 i 0,5 SOL) izvršitelj ne primjenjuje ni strop troška swapa; štiti izbor "
               "tokena (likvidnost ≥ 2M $, volumen ≥ 500k $) i provjera prodaje prije kupnje.",
               "MJERENJE_TROSKA=0 ga gasi; ništa ne mijenja postavke, stropove ni prekidače.")),
    M("grok_autotrade", "Grok autotrade", "novac", "trade.db settings 'grok_autotrade' {on, paused_until, who, since}",
      {"<off>": "ugašen", "<on>": "uključen: Grok kupuje i prodaje sam, unutar svojih limita",
       "<paused>": "pauziran do ponoći (dnevni gubitak)"},
      [("<off>", "<on>", "vlasnik: prekidač „Grok autotrade”"), ("<on>", "<off>", "vlasnik; nalog 15.11. jednom"),
       ("<on>", "<paused>", "program: Grokov dnevni gubitak ≥ strop"), ("<paused>", "<on>", "sat: ponoć po Zagrebu")],
      who="vlasnik", caveats=("Grok ga ne može sam uključiti ni mijenjati svoje limite.",
                              "'executed' u Grokovom dnevniku znači „zapisano”, ne „swap prošao”."), board=True),
    M("grok_log", "Grok autotrade: dnevnik", "novac", "trade.db settings 'grok_auto_log' (status po retku)",
      {"on": "prekidač uključen", "off": "prekidač ugašen", "paused": "pauza", "executed": "izvršeno", "rejected": "odbijeno"},
      scan=(("ui/grokauto.py", "status"),), extra=("open", "closed", "live", "upcoming"),
      caveats=("Isto polje nosi i stanja prekidača i ishode tradeova.",)),
    M("exit_plans_pause", "Planovi izlaza (pauza vlasnika)", "novac", "trade.db settings 'exit_plans_paused'",
      {"<running>": "rade", "<paused>": "pauzirani: nijedan plan ne prodaje"},
      [("<running>", "<paused>", "vlasnik: /exitpause"), ("<paused>", "<running>", "vlasnik: /exitresume")],
      who="vlasnik", caveats=("Pauza nema roka.",), board=True),
    M("exit_plan", "Plan izlaza pozicije", "novac", "league.db exit_plans.status + JSON state",
      {"active": "aktivan", "replaced": "zamijenjen novim", "done": "gotov (nema otvorenih lotova)"},
      [("-", "active", "set_plan (stari postaje replaced)"), ("active", "done", "procjena: svi lotovi prodani")],
      who="vlasnik, Grok", scan=(("league/exitplan.py", "status"),), extra=("open",)),
    M("veliki_proof", "Midcap: dokaz za pravi novac", "novac", "trade.db settings 'veliki_dokaz' + trade/config.json",
      {"walk": "walk-forward dokaz", "demo": "dokaz iz demo tradeova", "nalog_vlasnika": "nalog vlasnika (bez čekanja dokaza)"},
      [("walk", "nalog_vlasnika", "nalog vlasnika 15.11., jednom")], who="vlasnik",
      scan=(("veliki/gate.py", "mode"),), also=("veliki/gate.py",),
      caveats=("'nalog_vlasnika' nema povratka u kodu: ostaje i nakon gašenja i paljenja prekidača.",), board=True),
    M("mcp_access", "Pristup za Groka (MCP ključ)", "novac", "env MCP_API_KEY, inače trade.db settings 'mcp_key'",
      {"<on>": "uključen", "<off>": "ugašen (API ne postoji)"},
      [("<off>", "<on>", "vlasnik: „Napravi MCP ključ”"), ("<on>", "<on>", "vlasnik: „Novi ključ” (stari odmah prestaje)"),
       ("<on>", "<off>", "vlasnik: „Ugasi pristup”")], who="vlasnik", board=True),
    M("mcp_client", "Grok bot (MCP klijent): zadnji poziv", "novac", "trade.db settings 'mcp_seen' {ts, tool, n_day}",
      {"<active>": "zove: zadnji poziv u zadnjih sat vremena", "<quiet>": "tih: nije zvao dulje od sat vremena",
       "<never>": "nije zvao otkad se ovo bilježi (18.11.)"},
      [("<quiet>", "<active>", "Grok pozove bilo koji alat (get_grok_tasks, submit_signal_opinion…)"),
       ("<active>", "<quiet>", "sat: sat vremena bez poziva")], who="Grok",
      caveats=("Bilježi se najviše jednom u minuti; broj poziva danas broji se od zadnjeg pokretanja aplikacije.",
               "Grok se spaja izvana: ako ne zove, treba ga pokrenuti na njegovoj strani ili mu dati važeći ključ.",),
      board=True),
    M("bot_heartbeat", "Proces koji trguje (run_trade)", "novac", "trade.db settings 'heartbeat' (svakih 60 s)",
      {"<alive>": "radi", "<silent>": "ne javlja se dulje od 3 min", "<never>": "još se nije javio"},
      who="program", board=True),
    # ---------------------------------------------------------------- strategije -------------------------------------
    M("veliki_trade", "Midcap pozicija", "strategije", "league.db veliki_trades.status (+ reason, exit_why, kind)", OC,
      [("-", "open", "veliki/live.enter"), ("open", "closed", "veliki/live.close (stop, cilj, trailing, rug, razlog)")],
      scan=(("veliki/live.py", "status"),),
      caveats=("Razlog 'time' se više ne izvršava uživo, a kartica ga još može prikazati.",
               "'be' (izlaz na ulazu) je definiran na dva načina (manage i exit_why).")),
    M("veliki_kind", "Midcap pozicija: pravilo", "strategije", "league.db veliki_trades.kind",
      {"range": "raspon 7 d", "intra": "dnevni raspon"}, scan=(("veliki/live.py", "kind"),),
      caveats=("Stari redci imaju NULL umjesto 'range'.",)),
    M("veliki_stop_phase", "Midcap pozicija: faza stopa", "strategije",
      "league.db veliki_trades: stop_px, wide_px, tight_ts, be_px, half_px, lots",
      {"<wide>": "široki stop −20 %", "<tight>": "uži stop (BTC pada)", "<breakeven>": "stop na ulazu",
       "<half>": "pola prodano na cilju", "<dca>": "dokupljeno (2 lota)"},
      [("<wide>", "<tight>", "BTC −1,5 % u 4 h ili slobodan pad"), ("<tight>", "<wide>", "BTC miran"),
       ("*", "<breakeven>", "+5 % neto drži 30 s")],
      caveats=("Brojači potvrde (30 s / 10 s) i prozor likvidnosti su u memoriji procesa: deploy ih briše.",)),
    M("explorer_variant", "Demo istraživač: zašto je ušao u ono što je pravilo odbilo", "strategije",
      "league.db veliki_trades.varijanta (račun autopilot-istrazivac)",
      {"sire": "donja polovica zone (pravilo traži donjih 25 %)", "pada": "u zoni pravila, ali svijeće još padaju",
       "grok": "Grok na X-u kaže kupi, pravilo ne bi ušlo",
       "povlacenje": "povlačenje nakon skoka (30-60 % skoka u 24 h, svijeće stale; cilj vrh skoka)"},
      also=("veliki/istrazivac.py", "veliki/povlacenje.py"),
      caveats=("Samo demo, na vlastitom računu: ne ulazi u dokaz za pravi novac ni u red „veliki demo”.",)),
    M("learner_trade", "Naučeno pravilo: demo račun i njegov pravi blizanac", "strategije",
      "league.db veliki_trades.varijanta 'nauceno:<profil>' (račun autopilot-nauceno; pravi blizanac na pravom računu) "
      "+ veliki_ucenik (prognoza, činjenice, što je bilo s pravim blizancem)",
      {"open": "otvoreno", "closed": "zatvoreno (razlog tp / stop / time; pravi blizanac i rug / likvidnost; "
                                     "'odbijeno' = kupnja pravim novcem nije izvršena, bez rezultata)"},
      [("-", "open", "veliki/ucenik.try_enter: prognoza najboljeg profila iznad +1 % neto (pravi blizanac samo uz "
                     "prekidač pravi_novac_nauceno i sve provjere pravog ulaza)"),
       ("open", "closed", "veliki/ucenik.mark: cilj, stop ili 72 h profila na sljedećoj kotaciji; pravi blizanac i rug "
                          "/ pad likvidnosti; neizvršena prava kupnja = 'odbijeno'")],
      also=("veliki/ucenik.py",),
      caveats=("Pravilo je zapisano 18.11.2026. prije prvog tradea i ne dorađuje se; presuda nakon 21 dana ili 60 "
               "token-dana.",
               "Oznaka retka je profil izlaza: nauceno:skalp (+3 % / −4 %), kratko (+6 / −8), uski (+10 / −8), pravilo "
               "(+10 / −20), siroko (+20 / −20).",
               "Izlazi dnevnog pravila (break-even, BTC stop, izlaz s razlogom) ove retke ne diraju.",
               "Naoružani izlaz (razina prijeđena, čeka sljedeću kotaciju) je u memoriji procesa: deploy ga briše, "
               "sljedeća kotacija ga ponovno naoruža. Razine su u retku.")),
    M("shadow_trade", "Knjiga sjene: zamišljeni trade", "strategije", "league.db veliki_sjena.status (+ reason, profil)", OC,
      [("-", "open", "svaki kandidat po 15-min svijeći, u svakom profilu izlaza"),
       ("open", "closed", "razina prijeđena pa sljedeća kotacija; 72 h; token bez kotacije")],
      scan=(("veliki/sjena.py", "status"),),
      caveats=("Samo redci: nema računa, nema novca i ništa što odlučuje o trgovanju ih ne čita.",
               "Ćelija je dokaz tek uz 20 token-dana i potvrdu na kasnijim danima.")),
    M("dip_reason", "Midcap: razlog pada tokena", "strategije", "midcap.db kv 'prio' (dip.kind)",
      {"los": "loš razlog", "trzisni": "tržišni pad", "benigni": "bezazlen", "nejasno": "nejasno"},
      scan=(("veliki/prioritet.py", "kind"), ("veliki/live.py", "kind"))),
    M("btc_regime", "BTC režim", "strategije", "izračun iz satnih svijeća (u memoriji procesa, po satu)",
      {"slobodan_pad": "slobodan pad: nema novih ulaza", "dno_se_potvrduje": "dno se potvrđuje", "normalno": "normalno"},
      who="program", also=("veliki/rule.py",),
      caveats=("Nepoznat BTC se vodi kao 'normalno' („BTC nepoznat”).", "Nema histereze između stanja."), board=True),
    M("macro_regime", "Makro režim (volumen meme platformi)", "strategije", "midcap.db makro_h (svaki sat)",
      {"risk_on": "risk-on", "neutral": "neutralno", "risk_off": "risk-off: nema novih ulaza"},
      who="program", scan=(("veliki/makro.py", "regime"),),
      caveats=("Očitanje starije od 3 h se vodi kao neutralno.",
               "Trade nosi dvije makro oznake (regime i makro)."), board=True),
    M("strategy_trade", "Demo trade strategije (raspon, momentum, oscilator, konsenzus, insajderi)", "strategije",
      "league.db range_rounds / momentum_trades / oscilator_trades / konsenzus_trades / insajderi2_trades .status", OC,
      [("-", "open", "enter"), ("open", "closed", "izlaz strategije ili sync_closed kad su lotovi prodani")],
      scan=(("rangedca/trade.py", "status"), ("momentum/trade.py", "status"), ("oscilator/live.py", "status"),
            ("konsenzus/live.py", "status"), ("insajderi/live.py", "status")),
      caveats=("Svaka strategija ima svoj rječnik razloga izlaza (trail / trailing, be / breakeven, stop / sl).",
               "Konsenzus, insajderi i fast: ako league trade nestane, redak ostaje otvoren zauvijek.")),
    M("range_flip", "Raspon: proboj i pauza tokena", "strategije", "range.db range_flip.state",
      {"normal": "normalno", "flip_candidate": "mogući proboj (ulazi stoje)", "flipped": "raspon okrenut",
       "paused": "pauza (ulazi stoje)", "resumed": "nastavljeno"},
      scan=(("rangedca/detect.py", "state"),), caveats=("Promjena verzije pravila vraća sve tokene na 'normal'.",)),
    M("fast_signal", "Brza provjera signala (posao)", "strategije", "fast.db signals.status",
      {"queued": "u redu", "running": "radi", "retry": "ponavlja se", "done": "gotovo", "failed": "nije uspjelo"},
      scan=(("fast/worker.py", "status"), ("fast/paper.py", "status"), ("fast/live.py", "status")),
      extra=("open", "closed"),
      caveats=("Posao koji sruši proces vraća se u red bez povećanja brojača pokušaja.",
               "'retry' se na stranici prikazuje kao neuspjeh.")),
    M("fast_decision", "Brza provjera: odluka", "strategije", "fast.db signals.decision",
      {"BUY_PAPER": "kupi (demo)", "BUY_LIVE": "kupi (pravi novac)", "SKIP": "preskoči", "CHECK_FAILED": "provjera nije uspjela"},
      scan=(("fast/worker.py", "decision"),), also=("fast/store.py",)),
    M("fast_trade", "Fast demo trade", "strategije", "league.db fast_trades.status", OC,
      scan=(("fast/paper.py", "status"),), extra=("done",)),
    M("x_call_entry", "X poziv: ulaz", "strategije", "fast.db x_calls.entry_status",
      {"pending": "čeka provjeru", "entered": "ušli", "blocked": "blokirano", "off": "isključeno", "expired": "isteklo"},
      scan=(("fast/xscalp.py", "entry_status"),)),
    M("strat_position", "Simulirana pozicija (strat)", "strategije", "strat.db positions.status",
      {"pending": "čeka cijenu", "open": "otvorena", "closed": "zatvorena", "skip": "preskočena"},
      scan=(("strat/run.py", "status"),)),
    M("koltest_position", "Test poziva influencera", "strategije", "koltest.db positions.status",
      {"pending": "čeka", "open": "otvorena", "done": "gotova", "skip": "preskočena"},
      scan=(("koltest/run.py", "status"),), also=("koltest/store.py", "koltest/book.py")),
    M("paper_decision", "Demo kandidat: odluka", "strategije", "paper.db candidates.decision",
      {"taken": "uzet", "ignored": "zanemaren"}, scan=(("run_paper.py", "decision"),),
      caveats=("Postoji i osam 'skip_*' razloga; ponovna provjera sprema samo prijelaz u 'taken'.",)),
    M("precall_wallet", "Novčanik koji kupuje prije poziva", "strategije", "kol.db precall_wallets.status / preshill_wallets.status",
      {"confirmed": "potvrđen", "candidate": "kandidat", "watch": "promatra se", "excluded": "isključen"},
      scan=(("kol/precall.py", "status"), ("kol/preshill.py", "status")),
      extra=("novo", "prihvaćeno", "open", "closed"),
      caveats=("Isti stroj postoji dvaput (precall, preshill) s različitim pravilima.",)),
    M("follow", "Praćenje (kopiranje) izvora", "strategije", "league.db follows.active",
      {"<active>": "prati se", "<paused>": "pauzirano"},
      [("<active>", "<paused>", "odjava, jednokratno praćenje, satni pregled, precall, paper sync"),
       ("<paused>", "<active>", "vlasnik: „Vrati”")], who="vlasnik, program",
      caveats=("Pet mjesta pauzira praćenje, a „Vrati” postoji samo za pauzu satnog pregleda.",)),
    # ---------------------------------------------------------------- odobrenja --------------------------------------
    M("mcp_request", "Grokov zahtjev za trade", "odobrenja", "trade.db settings 'mcp_requests' (status po zahtjevu)",
      {"pending": "čeka tvoje odobrenje", "approved": "odobren (poslan u kupnju)", "rejected": "odbijen",
       "failed": "nije uspio", "expired": "istekao", "obsolete": "zastario (pozicija više nije otvorena)"},
      [("-", "pending", "Grok: execute_trade bez autotradea"), ("pending", "approved", "vlasnik: Odobri"),
       ("pending", "rejected", "vlasnik: Odbij"), ("pending", "expired", "sat: stariji od roka"),
       ("pending", "obsolete", "program: prodaja pozicije koja je već zatvorena")], who="vlasnik",
      scan=(("ui/mcpapi.py", "status"),), also=("ui/pravitrade.py",), extra=("open", "pending_approval"),
      caveats=("'approved' znači „poslano u ručnu kupnju”; stvarni ishod kupnje se ne vraća u zahtjev.",)),
    M("assistant_note", "Bilješka asistenta (Grok, kritičar)", "odobrenja", "trade.db assistant_notes.status",
      {"novo": "novo: čeka tebe", "prihvaćeno": "prihvaćeno", "odbijeno": "odbijeno", "primijenjeno": "primijenjeno"},
      [("novo", "prihvaćeno", "vlasnik"), ("novo", "odbijeno", "vlasnik"), ("prihvaćeno", "primijenjeno", "vlasnik: Primijeni"),
       ("novo", "primijenjeno", "vijeće (18.11.): oba ocjenjivača bez „protiv”, dopuštena postavka koja nije pravi novac"),
       ("novo", "prihvaćeno", "vijeće: prihvaćeno, ali traži izmjenu koda (za izvedbu)"),
       ("novo", "odbijeno", "vijeće: oba ocjenjivača protiv")],
      who="vlasnik, vijeće", scan=(("ui/assistnotes.py", "status"),), extra=("open",),
      caveats=("'novo' nema roka ni čišćenja.", "'prihvaćeno' se koristi i za „sažetak pročitan”.",
               "Od 18.11. prijedloge (suggestion) novije od prvog prolaza vijeća odlučuje vijeće; stariji i sve što "
               "dira pravi novac ostaje vlasniku.")),
    # 18.11. (vlasnik: "Kad Grok pošalje prijedlog, Claude i OpenAI moraju biti kritični ... prihvatiti ako se slažu";
    # vijece/): the council's two state sets
    M("council_review", "Vijeće: ocjena prijedloga", "odobrenja", "trade.db vijece_ocjene.verdict (jedna po članu i bilješci)",
      {"slazem": "slaže se", "doradi": "slaže se uz doradu", "protiv": "protiv"},
      [("-", "slazem", "član vijeća koji nije predlagač: prijedlog ima smisla kakav jest"),
       ("-", "doradi", "član vijeća: slaže se uz konkretnu bolju verziju (refined_change kad je to postavka)"),
       ("-", "protiv", "član vijeća: s razlogom")], who="OpenAI, Claude, Grok",
      scan=(("vijece/store.py", "verdict"), ("vijece/kriticari.py", "verdict"), ("vijece/odluka.py", "verdict"),
            ("vijece/mcp.py", "verdict")),
      caveats=("Ocjena se ne mijenja: jedna po članu i bilješci.",
               "Grok ocjenjuje kad pozove MCP; ako ne odgovori 6 h od bilješke, odlučuje se bez njega.",
               "OpenAI i Claude ocjenjuju unutar dnevnog budžeta (0,60 $ svaki); bez ključa ili budžeta bilješka čeka.")),
    M("council_decision", "Vijeće: odluka o prijedlogu", "odobrenja", "trade.db vijece_odluke.odluka (jedna po bilješci)",
      {"prihvaceno_primijenjeno": "prihvaćeno i primijenjeno", "prihvaceno_za_izvedbu": "prihvaćeno, čeka izmjenu koda",
       "odbijeno": "odbijeno (oba ocjenjivača protiv)", "vlasniku": "odlučuje vlasnik"},
      [("-", "prihvaceno_primijenjeno", "oba ocjenjivača bez „protiv”, dopuštena postavka koja nije pravi novac"),
       ("-", "prihvaceno_za_izvedbu", "oba bez „protiv”, promjena traži kod"),
       ("-", "odbijeno", "oba ocjenjivača protiv"),
       ("-", "vlasniku", "podijeljeni glasovi, dvije različite dorade, pravi novac ili primjena nije prošla")],
      who="program (vijeće)", scan=(("vijece/odluka.py", "odluka"), ("vijece/store.py", "odluka"), ("vijece/smjer.py", "odluka")),
      caveats=("Odluka je konačna za vijeće; 'vlasniku' ostavlja bilješku na 'novo' na stranici Autopilot.",
               "Pravi novac (ulog, broj pozicija, TP, SL, copy.*, live / autotrade / kill) vijeće nikad ne primjenjuje.",
               "Redak s razlogom „odluka u tijeku” znači da je proces pao usred odluke: odlučuje vlasnik.")),
    M("assistant_suggestion", "Prijedlog težine callera", "odobrenja", "trade.db assistant_suggestions.status",
      {"pending": "čeka tebe", "approved": "odobren", "rejected": "odbijen"}, who="vlasnik",
      scan=(("ui/assistnotes.py", "status"),), also=("ui/mcpdata.py", "ui/pravitrade.py"),
      caveats=("Isti postupak odobravanja kao bilješke, ali s engleskim riječima.",)),
    M("proposal", "Prijedlog kupnje", "odobrenja", "proposals.db proposals.status",
      {"novo": "novo", "kupljeno": "kupljeno", "isteklo": "isteklo", "odbijeno": "odbijeno"},
      [("novo", "kupljeno", "vlasnik kupio"), ("novo", "odbijeno", "vlasnik"), ("novo", "isteklo", "sat, izvor nestao, stop")],
      who="vlasnik", scan=(("proposals/store.py", "status"),), also=("proposals/job.py", "proposals/paper.py"),
      caveats=("Ako prijedlog istekne između prikaza i kupnje, kupnja se ne zapiše kao 'kupljeno'.",)),
    M("access_request", "Zahtjev za pristup aplikaciji", "racuni", "league.db access_requests.status",
      {"novi": "novi", "pozvan": "pozvan", "odbijen": "odbijen", "obrisan": "obrisan"}, who="vlasnik",
      scan=(("ui/landing.py", "status"),), extra=("active", "quiet", "slow")),
    M("idea", "Ideja korisnika", "racuni", "league.db ideas.status",
      {"novo": "novo", "u izradi": "u izradi", "napravljeno": "napravljeno", "odbijeno": "odbijeno"}, who="vlasnik",
      also=("ui/league.py",)),
    # ---------------------------------------------------------------- podaci -----------------------------------------
    M("x_credit_breaker", "twitterapi: nema kredita (HTTP 402)", "podaci", "makroinf/xapi: u memoriji procesa, 30 min",
      {"<ok>": "radi", "<no_credit>": "nema kredita: pozivi stoje"},
      [("<ok>", "<no_credit>", "HTTP 402"), ("<no_credit>", "<ok>", "sat: nakon 30 min")], who="sat",
      caveats=("Pauza je u memoriji, a svaki prolaz je novi proces: pauza ne preživi do sljedećeg prolaza.",
               "402 se vodi kao „strop dosegnut” i trajno završava val otkrivanja računa.")),
    M("makroinf_discovery", "Makro influenceri: val otkrivanja", "podaci", "makroinf.db kv 'otkrivanje' / 'otkrivanje2' (step)",
      {"pratitelji": "pratitelji", "spominjanja": "spominjanja", "pretraga": "pretraga", "adam": "čeka vlasnika (Adam)",
       "profili": "profili", "ocjena": "ocjena", "proba": "proba", "odabir": "odabir", "gotovo": "gotovo"},
      scan=(("makroinf/discover.py", "step"),), extra=("ponovno",),
      caveats=("'gotovo' nema povratka osim brisanja zapisa.",)),
    M("makroinf_account", "Makro influencer: račun", "podaci", "makroinf.db accounts.status",
      {"novo": "novo", "aktivan": "aktivan", "neaktivan": "neaktivan (30 d bez objave)", "odbijen": "odbijen",
       "uklonjen": "uklonjen", "needs_owner_confirm": "čeka potvrdu vlasnika"},
      scan=(("makroinf/racuni.py", "status"),), extra=("potvrden",)),
    M("makroinf_candidate", "Makro influencer: kandidat", "podaci", "makroinf.db disc.status",
      {"kandidat": "kandidat", "spreman": "spreman", "odbijen": "odbijen", "probano": "probano", "dodan": "dodan",
       "adam": "čeka vlasnika (Adam)"},
      scan=(("makroinf/discover.py", "status"),), extra=("aktivan", "neaktivan")),
    M("tg_channel", "Telegram kanal", "podaci", "tg.db channels.status",
      {"active": "aktivan", "quiet": "tih", "slow": "spor"},
      scan=(("tg/pratitelji.py", "status"),),   # 19.11.: the reader (tg/poll.py) is gone; only the follower count
      caveats=("Od 19.11. nitko ne mijenja status: popis je zamrznut (bez otkrivanja). Stari retci 'candidate' i 'dead' "
               "ostaju u bazi, ali se ne prikazuju i ne broje.",)),
    M("zone_alert", "Zonski alarm Grok Botu", "podaci", "zonewatch.db alerts.status",
      {"pending": "čeka slanje", "sent": "poslan", "failed": "nije poslan", "config_error": "greška postavki",
       "not_configured": "webhook nije postavljen", "off": "isključeno", "expired": "istekao"},
      scan=(("zonewatch/notify.py", "status"), ("zonewatch/job.py", "status")),
      extra=("ok", "duplicate", "error", "unknown"),
      caveats=("Uspjeh je 'sent' u alarmima, a 'ok' u dnevniku.", "'failed' je konačan: ne ponavlja se.")),
    M("event_topic", "Tema događaja", "podaci", "league.db event_topics.status",
      {"upcoming": "dolazi", "live": "traje", "done": "završeno"}, who="Grok, vlasnik",
      scan=(("topics/job.py", "status"),), also=("topics/store.py", "topics/view.py"),
      caveats=("Tema bez datuma se nikad sama ne završi; ništa ne prebacuje 'upcoming' u 'live'.",)),
    M("call_outcome", "Ishod poziva (mjerenje)", "podaci", "events.db call_outcomes.status",
      {"pending": "čeka", "ok": "izmjereno", "unmeasured": "nije izmjereno", "unavailable": "nedostupno"},
      scan=(("events/outcomes.py", "status"),)),
    M("rug_archive", "Arhiva rugova", "podaci", "hype.db rug_watch → rug_archive.kind → rug_recovered",
      {"srusen": "srušen", "likvidnost": "likvidnost povučena", "mehanika": "mehanika tokena"},
      scan=(("rugfilter/archive.py", "kind"),),
      caveats=("'mehanika' se nikad ne oporavlja; nakon 14 dana ništa se ne oporavlja.",
               "Oporavak ovisi o poslu koji fokus na midcapove gasi.")),
    M("usage_alert", "Upozorenje o potrošnji API-ja", "podaci", "usage.db alerts.level",
      {"warn": "upozorenje", "bad": "kritično"}, scan=(("usage/watch.py", "level"),),
      caveats=("Nema stanja „riješeno”: redak ostaje.",)),
    M("spend_cap", "Dnevni stropovi plaćenih API-ja", "podaci", "kv po modulu (twapi, scan, holderi, makroinf, kritičar…)",
      {"<under>": "ispod stropa", "<slice>": "satni dio potrošen", "<cap>": "dnevni strop dosegnut"}, who="sat",
      caveats=("Svaki modul ima svoj brojač i pravila; nema zajedničkog stropa po plaćenom računu.",)),
    M("pumpportal_feed", "PumpPortal feed uživo", "podaci", "u memoriji veze + live_state kv",
      {"<full>": "puni feed", "<slice>": "satni dio potrošen: samo otvorene pozicije",
       "<cap>": "dnevni strop: samo otvorene pozicije", "<unfunded>": "bez sredstava: ponovno spajanje svakih 5 min"},
      caveats=("Brojač sata kreće od nule pri svakom spajanju, pa feed nakon prekida može stati do sat vremena.",)),
    # ---------------------------------------------------------------- posao ------------------------------------------
    M("fokus_midcap", "Fokus na midcapove", "posao", "trade.db settings 'flag:fokus_midcap'",
      {"live": "uključen: mikrokap poslovi ne rade", "off": "isključen"}, who="vlasnik", also=("ops/fokus.py",),
      board=True),
    # 19.11. (vlasnik: influenceri i Telegram jednom u 5 dana, sve resurse na novčanike; ops/drustveni.py)
    # 19.11. (vlasnik: "Demo money maybe no longer makes sense ... Yes, start with both steps"; league/mjera.py)
    # 19.11. (vlasnik: BNB chain i praćenje novčanika; bnb/prati.py): mjerenje novih kupnji BSC novčanika, bez novca
    M("bnb_measure_row", "BNB: mjerenje jedne nove kupnje praćenog novčanika", "strategije", "bnb.db bnb_mjera.status",
      {"open": "otvoreno (čeka ulaz ili izlaz)", "closed": "zatvoreno (izmjereno)", "miss": "promašaj (ne ulazi u prosjek)"},
      [("-", "open", "program: poll vidi kupnju"), ("open", "closed", "program: prodali su / stop / vrijeme"),
       ("open", "miss", "program: bez cijene, likvidnost, MC ispod 30k")],
      scan=(("bnb/prati.py", "status"),), caveats=("Samo redci u postotku; nikad trade ni novac.",)),
    M("wallet_measure_mode", "Praćenje novčanika: demo novac ili mjerenje po ulazu", "strategije",
      "trade.db settings 'mjera_nacin' (auto / demo / mjera) + league.db mjera_kv 'prebaceno'",
      {"auto": "auto: demo tradeovi teku usporedno s mjerenjem (23.11.: demo nikad ne staje)",
       "demo": "demo: demo tradeovi praćenja novčanika teku usporedno s mjerenjem",
       "mjera": "mjera: samo mjerenje, tri demo izvora ne otvaraju nove tradeove",
       "<switched>": "auto, mjerenje potvrđeno na istim tradeovima; demo i dalje otvara tradeove"},
      [("-", "auto", "zadano od 19.11. (nalog vlasnika)"),
       ("auto", "<switched>", "program: jednom, kad se mjerenje i demo slažu (≥ 20 parova, medijan razlike ≤ 1,5 pp); demo ne staje"),
       ("*", "*", "vlasnik: gumbi auto / demo / mjera na stranici Autopilot")], who="vlasnik",
      also=("league/mjera.py",),
      caveats=("Mjerenje teče u svakom načinu; način odlučuje samo otvaraju li tri demo izvora nove demo tradeove.",
               "Otvoreni demo tradeovi izlaze po svojim pravilima; ništa se ne briše.",
               "Prebacivanje u autu je jednokratno: kasnije razilaženje ga ne vraća (vlasnik može staviti 'demo')."),
      board=True),
    M("social_window", "Influenceri i Telegram: prozor osvježavanja", "posao", "DATA_DIR/drustveni.json {prvi, log}",
      {"<open>": "otvoren: influenceri i Telegram se osvježavaju", "<closed>": "zatvoren: poslovi influencera i Telegrama "
       "miruju do sljedećeg prozora", "<first>": "prvi prozor počinje pri sljedećem startu",
       "<always>": "uvijek otvoren (SOCIAL_ALWAYS=1, staro ponašanje)",
       "<nopersist>": "otvoren: nema trajnog stanja (DATA_DIR nije postavljen)"},
      [("-", "<open>", "prvi start nakon deploya 19.11. (python3 -m ops.drustveni) ili prvi posao koji pita"),
       ("<open>", "<closed>", "sat: SOCIAL_WINDOW_H (6 h) nakon početka prozora"),
       ("<closed>", "<open>", "sat: SOCIAL_EVERY_D (5 dana) nakon početka prethodnog prozora")], who="sat",
      also=("ops/drustveni.py",),
      caveats=("Noćni poslovi (zadnjih5, konsenzus, makroinf noć) koji prođu vrata u prozoru čekaju noćni prozor i "
               "rade tada, i ako je društveni prozor već zatvoren.",
               "Promjena SOCIAL_EVERY_D ili SOCIAL_WINDOW_H računa se od istog prvog početka (ne pomiče ga).",
               "Računi koje prati pravi novac zadržavaju X webhook pravilo i izvan prozora."), board=True),
    M("heavy_lock", "Brava teških poslova", "posao", "flock /tmp/memesonar-heavy.lock (+ .who, .prio)",
      {"<free>": "slobodna", "<held>": "zauzeta", "<waiting>": "posao čeka"},
      caveats=("Ime držatelja se ne briše nakon otpuštanja, pa log može imenovati posao koji je već gotov.",)),
    M("sched_job", "Raspored poslova", "posao", "sched_state.json {posao: datum ili vrijeme}",
      {"<due>": "na redu", "<running>": "radi", "<done>": "gotov za danas", "<retry>": "ponavlja se"},
      caveats=("Dnevni posao se bilježi kao gotov i kad padne.", "Dvadesetak dretvi piše istu datoteku bez brave.")),
    M("night_archive", "Noćna arhiva", "posao", "DATA_DIR/.arhiva.json + arhiva_stanje.sqlite",
      {"zadrži": "zadrži", "arhiviraj": "arhiviraj", "čeka": "čeka"}, also=("ops/arhiva.py",),
      caveats=("Prekid usred brisanja ostavlja .gz bez zapisa o premještanju.",)),
    M("critic_loop", "Kritičar (OpenAI)", "posao", "trade.db critic_kv",
      {"<ok>": "radi", "<pause>": "pauza 10 min nakon neuspjelog poziva", "<budget>": "dnevni budžet potrošen"},
      who="sat"),
    M("report_send", "Jutarnji izvještaj", "posao", "output/report-state.json",
      {"<built>": "složen", "<sent>": "poslan", "<error>": "greška"},
      caveats=("Brojač pokušaja je u memoriji: svaki restart daje novih 5.",)),
    # ---------------------------------------------------------------- računi i sučelje --------------------------------
    M("invite", "Pozivnica", "racuni", "league.db invites (kind, used_by, revoked)",
      {"<valid>": "vrijedi", "<used>": "iskorištena", "<revoked>": "povučena"}, who="vlasnik",
      caveats=("Pozivnice nemaju rok.",)),
    M("rekt_round", "Natjecanje: rekt krug", "racuni", "league.db rekts",
      {"<round>": "💀 rekt · N. krug"}, caveats=("Stupac round se piše, a krug se broji iz redaka.",)),
    M("ui_poller", "Osvježavanje stranice Autopilot", "sucelje", "preglednik (ap.js, POLL_JS)",
      {"<live>": "živo", "<stale>": "nema svježih podataka", "<retry>": "ponovni pokušaj"},
      caveats=("Dva pollera s različitim pravilima ponavljanja (10 s / 3 s) i prikaza zastarjelosti.",)),
    M("chart_fill", "Graf: dohvat povijesti", "sucelje", "ui/apgraf fill.state",
      {"dohvacam": "dohvaćam", "nedavno": "nedavno dohvaćeno", "greska": "greška", "nema_poola": "nema poola",
       "strop": "dnevni strop", "ceka": "čeka", "iskljuceno": "isključeno"}, also=("ui/apgraf.py",),
      caveats=("Preglednik ponovno pita samo na 'dohvacam', ne i na 'ceka'.",)),
]

BY_KEY = {m.key: m for m in MACHINES}

# One vocabulary for "why a trade was closed" across the strategies (each wrote its own: trail / trailing, be /
# breakeven, stop / sl, tp / tp1 / tp2). Read side only: reports and agents can group exits the same way everywhere;
# no strategy's own literal changes.
EXITS = {"tp": "cilj", "tp_part": "dio na cilju", "trailing": "trailing stop", "breakeven": "stop na ulazu",
         "stop": "stop", "time": "vrijeme", "rug": "rug", "liquidity": "likvidnost", "reason": "loš razlog pada",
         "btc": "BTC zaštita", "macro": "makro zaštita", "volume": "kolaps volumena", "source_sold": "izvor je prodao",
         "gave_up": "odustajanje", "outside": "prodano izvan strategije", "missing": "trade nestao", "other": "ostalo"}
EXIT_MAP = {
    "veliki": {"tp": "tp", "trail": "trailing", "be": "breakeven", "stop": "stop", "time": "time", "rug": "rug",
               "likvidnost": "liquidity", "los": "reason", "btc_zastita": "btc", "btc_rez": "btc",
               "makro_zastita": "macro", "makro_rez": "macro", "volumen": "volume", "nestalo": "missing"},
    "rangedca": {"stop": "stop", "tp1": "tp_part", "tp2": "tp", "top": "tp", "trailing": "trailing",
                 "breakeven": "breakeven", "time": "time", "odustajanje": "gave_up", "rug": "rug",
                 "prodano izvan runde": "outside"},
    "momentum": {"tp1": "tp_part", "trailing": "trailing", "stop": "stop", "time": "time",
                 "prodano izvan strategije": "outside"},
    "oscilator": {"tp": "tp", "stop": "stop", "time": "time", "rug": "rug", "nestalo": "missing", "kraj": "time"},
    "sjena": {"tp": "tp", "stop": "stop", "vrijeme": "time", "bez_cijene": "missing"},
    "league": {"tp": "tp", "sl": "stop", "time": "time", "rug": "rug", "smart_trail": "trailing",
               "smart_other": "other", "wallet_sold": "source_sold"},
}


def exit_key(module, literal):
    """The shared exit word for a strategy's own exit literal ("odustajanje: razlog" -> gave_up); "other" when the
    module or the literal is not known. Never raises."""
    lit = str(literal or "").split(":", 1)[0].strip()
    return (EXIT_MAP.get(module) or {}).get(lit) or (EXIT_MAP["league"].get(lit) if module != "league" else None) or "other"


def exit_label(module, literal):
    return EXITS[exit_key(module, literal)]


def label(key, literal):
    """The Croatian word for a state of a machine; the literal itself when either is unknown."""
    m = BY_KEY.get(key)
    return m.label(literal) if m else str(literal)


def describe(area=None, key=None):
    """The registry as plain data (the MCP tool, the page): one machine, one area or everything."""
    ms = [m for m in MACHINES if (not key or m.key == key) and (not area or m.area == area)]
    return {"areas": AREAS, "count": len(ms), "machines": [m.as_dict() for m in ms],
            "exit_words": EXITS if not key else None}
