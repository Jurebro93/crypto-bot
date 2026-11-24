# Hosting: bi li dva CPU-a pomogla? (10.11.2026.)

**Odgovor:** Ne sada. Druga jezgra ne daje "punu paru": skupljanje stoji na API limitima i na bravi "jedan težak posao",
trgovanje na dvije ankete od 1 s i na mreži, a jedan Python proces ionako ne može koristiti više od jedne jezgre.
Jučerašnje gušenje (CPU ≥ 90 % u 35 % dana) riješio je popravak jednog upita (PR #75, $0): od tada je CPU medijan
18 %, vrh 72 %, nijedna minuta iznad 90 % (127 izmjerenih minuta). Dostupnost danas ne ruši CPU nego deployi: 29 u
jednom danu, a u satu deploya #76 bilo je 659 odgovora 502/503 uz CPU ispod 60 %. Preporuka: ostati na 1 CPU,
dodati čuvara CPU-a i mjerenje (+$0), a 2 CPU (≈ +$60/mj) uzeti tek kad se ispuni jedan od okidača iz točke 6.

**Ograda o cijenama:** nijednu cijenu danas nisam mogao vidjeti. Web pretraga je bila potrošena (zajednički limit
workflowa) prije mog prvog upita, a WebFetch odbija render.com i www.hetzner.com (nisu u dopuštenoj mreži sesije).
Sve cijene dolje su iz znanja modela (cjenici kakve znam do sredine 2026.) i nose oznaku **nepotvrđeno**; uz svaku je
adresa na kojoj se provjerava. Preporuka (opcija A) ne ovisi ni o jednoj od njih. Ono što JE provjereno danas
dolazi iz Render API-ja (plan, limiti, metrike, logovi, deployi) i iz koda.

## 1. Opcije

| Opcija | $/mj | Što kupuje | Što ne kupuje / rizik |
|---|---|---|---|
| **A. Ostati na `1c-2g` + čuvar CPU-a, nice, događaji umjesto anketa, brava po vrsti posla** | +0 (danas ≈ 26: instanca ≈ 25 + disk 5 GB ≈ 1,25; nepotvrđeno) | Pozadina se pauzira prije nego kvota pukne, pa UI, trade i slušači uvijek imaju CPU; dokaz u logu svake minute; teški poslovi mogu raditi 24 h s onim što ostane (≈ 17 CPU-sati dnevno umjesto 5); reakcija Autopilota ≈ 1 s kraća | Jedan dugi posao ne traje kraće; treba 7 dana mjerenja da se vidi je li dosta |
| **B. Render `2c-4g` (stari "Pro")** | ≈ 86 (≈ 85 + disk; **+≈ 60/mj, ≈ 720/god**; nepotvrđeno, pročitati u dashboardu prije klika) | Kvota 2 jezgre: jedan odbjegli proces ne može uzeti više od pola; 4 GB RAM-a (sve baze, 2,9 GB, stanu u keš; dvije gradnje stranica istodobno); jedan klik, restart ≈ 1 min, naplata po sekundi, može se vratiti | Prekid pri deployu, jedan pisac po SQLite bazi, API limiti, GIL; u 127 minuta nakon #75 potražnja nijednom nije prešla 0,72 jezgre, pa druga ne bi bila potrebna ni u jednoj |
| **C. Render web + worker (2 × `1c-2g`)** | ≈ 51 (+25), uz Postgres još ≈ 6–20 (nepotvrđeno) | Teški poslovi na drugom stroju; web bez diska dobio bi deploy bez prekida | Disk vidi samo JEDAN servis: worker ne može do SQLite datoteka. Traži selidbu 24 baze na Postgres ili API između servisa (hype.db je 1,4 GB): tjedni rada i rizik za lanac pravog novca. Ne sada |
| **D. VPS, Hetzner (samo referenca)** | ≈ 4–35 (CX23 2 dijeljene vCPU/4 GB ≈ €3,5–5; CPX32 4 vCPU/8 GB ≈ €11–15; CCX13 2 namjenske vCPU/8 GB ≈ €12,5–16; CCX23 4 namjenske/16 GB ≈ €24,5–32; + IPv4 ≈ €0,5, backup +20 %; uz 1 € ≈ $1,1; sve nepotvrđeno) | 2–4 jezgre i 8–16 GB za trećinu cijene opcije B; prioriteti po procesu (systemd CPUWeight/CPUQuota), što Render nema; lokalni NVMe | Sami radimo TLS, deploy, backup baza (Render daje dnevni snimak diska), nadzor, zakrpe; privatni ključ novčanika na vlastitom serveru; selidba webhook adresa |

Noćni CPU "na sat" (cron job veličine Pro, 5 h svake noći) koštao bi ≈ $18/mj umjesto $60 (nepotvrđeno), ali cron
job ne vidi disk, pa vrijedi isto što i za C.

## 2. Što je izmjereno (Render API, 10.11.2026. 01:25–01:30 CET)

| Što | Vrijednost |
|---|---|
| Plan | `1c-2g`: limit 1 CPU i 2 GiB, 1 instanca, Frankfurt, disk 5 GB (3,2 GB zauzeto). Health check path je PRAZAN. `render.yaml` u repou još piše `plan: starter` |
| CPU 9.11. 00:00–22:20 UTC (prije #75), po 5 min | ≥ 90 % u 91 od 241 intervala (38 %); 20 epizoda zasićenja, ukupno 465 min (35 % vremena), najdulja 50 min; medijan 42 % |
| CPU nakon #75 (22:20–00:27 UTC, 127 minuta) | medijan 18 %, p95 49 %, vrh 72 %; 0 minuta ≥ 90 %, 6 minuta ≥ 50 % |
| Prvih 27 min noćnog prozora (01:00–01:27 CET) | CPU medijan 10 %, vrh 52 %. `run_dugo` je držao bravu 21 min (GeckoTerminal "trenutno zauzet"), a iza njega je 12–22 min čekalo 6 poslova (corr, shadow, learn6, dokazani, KOL krug, backfill) |
| Gradnja /pregled u djetetu | slobodan CPU (22:24–23:41 UTC): medijan 4,5 s (n = 16); razdoblje s epizodama zasićenja (9.11. 19:14–22:19 UTC, n = 36): medijan 10,6 s, vrh 77,7 s, 39 % gradnji ≥ 20 s; noćas dvije gradnje 54 i 46 s (i /tokens 59 s) uz CPU 4–50 % |
| KOL search krug | 1.193–2.809 s prije #75, 71–86 s poslije |
| HTTP 9.11. 00–22 UTC | 97.990 odgovora: 69 % 200, 18,3 % 499 (klijent odustao), 12,6 % 502/503 |
| HTTP 22–24 UTC (deploy #75 u 22:16, #76 u 23:44) i noćas | 22–24 UTC: 91 % 200, 2,9 % 499, 6,1 % 5xx (659 odgovora 502/503 u satu deploya #76); 00:00–00:27 UTC: 96,9 % 200, 2,2 % 5xx bez deploya i uz CPU ≤ 52 % |
| Deployi | 29 na dan 9.11. (UTC), 10 na 8.11., 11 na 7.11.; medijan 62 s po deployu (s buildom), zbroj 33 min 9.11. |
| RAM | 1,7–2,0 GB od 2,0: procesi 0,28–0,42 GB, keš datoteka 1,36–1,57 GB. Baze ≈ 2,9 GB (hype.db 1.404 MB, wallets.db 609, kol.db 358, paper.db 198, tg.db 155) |
| p95 latencija | Render API za ovaj servis ne vraća `http_latency` (prazno): mora je mjeriti aplikacija |

## 3. Što bi 2 CPU-a promijenila, u brojkama

| Pitanje | Danas, 1 CPU | S 2 CPU (B) | S čuvarom na 1 CPU (A) |
|---|---|---|---|
| (a) Stranica dok radi težak posao | Posjetitelj dobiva spremljenu kopiju odmah (ms); pati svježina: gradnja 4,5 s → 20–78 s u zasićenju (39 % gradnji tog razdoblja). Zahtjevi i 1-s fragmenti: kad potražnja D prelazi kvotu, svi procesi rade ≈ 1/D brzine (težak posao + gradnja = ×2 sporije); 499 je pao s 18,3 % na 1–3 % čim je CPU oslobođen | ≈ 4,5–6 s dok su istodobno najviše 2 CPU-posla; fragmenti ×1 do D = 2. Bez učinka na noćašnjih 46–59 s (CPU je bio 4–50 %) | ≈ 4,5–6 s jer se težak posao pauzira dok traje gradnja (gradnje troše ≈ 7 s na 5 min = 2 % jezgre); težak posao toliko kasni |
| (b) Sati za teške poslove | 5 h (01–06) | 24 h po CPU-u: jedna jezgra teškom poslu, druga ostalom (ostalo danas treba medijan 0,18, p95 0,49, vrh 0,72 jezgre). I dalje jedan po jedan i ne brže po poslu | 24 h s ostatkom do 90 %: ≈ 0,7 jezgre medijan ≈ 17 CPU-sati dnevno (danas 5) |
| (c) Reakcija Autopilota | Signal → buđenje kopije: anketa 1 s (prosjek 0,5 s) → demo ulaz → `run_trade` anketa 1 s (prosjek 0,5 s) → Jupiter i potvrda (mreža, sekunde). CPU dio lanca: ≈ 3,5 ms + 10–25 ms (sekundni.md). Telegram: čitanje praćenih kanala svake 2 s | 0 s dobitka dok je CPU slobodan (sve minute nakon #75). Dobitak samo za zasićenja: reakcija se tada ne rasteže ×D i webhook ne dobije 502 | Isto kao B za zasićenje, plus događaji umjesto dviju anketa: ≈ −1 s u prosjeku, −2 s u najgorem slučaju |

Račun za (b) i (c) je procjena iz 2 sata mjerenja nakon #75, ne iz tjedna.

**Što 2 CPU-a NE popravljaju:**
- Jedan pisac po SQLite datoteci ("database is locked" 5.11., 7.11., 8.11. bio je sudar pisaca, ne manjak CPU-a).
- API limite: GeckoTerminal (noćas "60 tokena čeka sljedeći prolaz"), DexScreener 300/min po IP-u, Helius 50 RPC/s i
  10 M kredita, twitterapi.io, Jupiter 429. "Više podataka" je pitanje plaćenih razina (osluskivaci.md, svijece.md).
- GIL: sve niti u `run_ui` (zahtjevi, webhookovi, league copy/auto, niti Autopilota i zivo) dijele jednu jezgru na
  bilo kojem planu. Niti zivo i autopilot-live stalno troše ≈ 7–8 % i ≈ 2 % jezgre, otvoren pop-up ≈ 30 %
  (sekundni.md, sintetika): to se rješava kodom.
- Bravu: teški poslovi idu jedan po jedan na bilo kojem broju jezgri.
- Prekid pri deployu i hladan keš nakon njega (prva gradnja /pregled nakon deploya 34 s).
- Spore gradnje uz slobodan CPU (noćas): sumnja na disk ili RAM, jer baze (2,9 GB) ne stanu u 2 GB. Tu bi pomogla
  4 GB plana B, ali to je RAM, ne CPU, i prvo treba izmjeriti (točka 6).

## 4. Raspored procesa (start.sh) i što druga jezgra paralelizira

| Proces | Ritam | Vrsta | Brava / nice |
|---|---|---|---|
| `run_ui.py` (keep ui) | nit po zahtjevu; nit league auto/copy svakih 20 s ili ≤ 1 s nakon `.copy_wake`; zagrijavanje stranica svakih 300 s | KRITIČNO: stranice, 1-s fragmenti, webhookovi /hook/chain, /hook/x, /hook/kol, kopiranje | nice 0; jedan GIL za sve niti |
| `run_ui.py --render` (dijete, ui/pagecache.py + build_in_child) | po potrebi, jedno odjednom (`UI_BUILDS=1`) | CPU: /pregled 4–5 s, /tokens 2–3 s, /kol 30 s, /ekipe 180 s | nice 5; uz zauzetu bravu gradi ako je slobodno ≥ 600 MB, inače zadnja kopija |
| `run_trade.py follow` (keep trade) | petlja 1 s (`poll_s`) | KRITIČNO: pravi novac | nice 0 |
| `run_tg.py loop` | takt 3 s, praćeni kanali 2 s | KRITIČNO za praćene kanale; mreža | nice 0 |
| `run_live.py loop` | PumpPortal websocket (sad odbijen zbog salda) | KRITIČNO: dump alarmi, buđenje kopije | nice 0 |
| `run_paper.py run --scan` | 60 s; niti 5/30/60/600 s; hype sken u djetetu svakih 120 s | sken: CPU + mreža; demo izlazi osjetljivi na kašnjenje | sken pod bravom (nice 10); nakon 10 min bez skena ide bez brave i bez nice |
| `run_kol.py loop` | krug svakih 20 min: `once` (danju lagani koraci; noću bodovanje 40+ min CPU-a, mjerenje, tokovi), zatim `search-round` | noću CPU, danju mreža | `once`: brava + nice 10; `search-round`: bez brave, nice 10 |
| `run_kol.py minute-loop`, `run_watch.py`, `run_report.py loop` | stalno / sat / 5 min | mreža, lagano | nice 0 |
| `run_sched.py` | pokreće kratku djecu: learn i exits (dnevno), learn6, exits_rb, shadow, corr (samo noću), market, usage, masovno, postai, tokenstatus (lagani) | CPU: fit, corr, shadow; ostalo mreža | teški: brava + nice 10; lagani: bez brave i bez nice |
| bash petlje | ops.health svaku minutu (nadzor memorije: proces > 800 MB, trade > 1.200 MB, gasi se i `keep` ga vraća); ops.health --hourly i rug arhiva (sat); `run_top.py` 180 s; kalendar, dex scan, hype learn, wallets harvest/score, `run_dugo` (`--night`); dokazani + copy 3 h; simianx 180 min | noćni: mreža + CPU | `ops/heavy.py`: jedna brava (flock), nice 10, `--night` = 01–06 Zagreb, `--prio` za backfill |

Stalnih Python procesa je 10 (ui, trade, tg, live, paper, kol, minute, sched, report, watch), uz kratku djecu 12–16.

| Posao | Paralelizira li ga druga jezgra? |
|---|---|
| UI ‖ težak posao (KOL bodovanje, fit, corr, shadow) | DA, različiti procesi |
| UI ‖ gradnja stranice u djetetu; `run_trade` ‖ sve ostalo | DA |
| Dvije gradnje stranica istodobno | Po CPU-u da, ali `UI_BUILDS=1` postoji zbog RAM-a: tek uz 4 GB |
| Dva teška posla istodobno | NE dok brava pušta jedan |
| Niti unutar `run_ui` i `run_paper` | NE (GIL): najviše jedna jezgra po procesu |
| Jedan dugi posao (KOL bodovanje 40+ min) | NE: jednonitan, traje isto, samo ga drugi ne usporavaju |
| Mrežni poslovi (dugo, search, minute, tg, harvest, topcheck) | Nebitno: čekaju API (`run_dugo` 21 min uz ≈ 10 % CPU) |

## 5. Render: cijene i ograničenja (sve nepotvrđeno osim popisa planova)

| Tip (stari naziv) | CPU / RAM | $/mj |
|---|---|---|
| Starter | 0,5 / 512 MB | 7 |
| Standard (veličina koju imamo: `1c-2g`) | 1 / 2 GB | 25 |
| Pro (`2c-4g` po veličini) | 2 / 4 GB | 85 |
| Pro Plus (`4c-8g`) | 4 / 8 GB | 175 |
| Pro Max | 4 / 16 GB | 225 |
| Pro Ultra | 8 / 32 GB | 450 |

Izvor: https://render.com/pricing , zadnje poznato modelu, 10.11.2026. NIJE viđeno. Provjereno 10.11.2026. (Render API):
uz stara imena postoje i tipovi `0.5c-512mb`, `1c-2g`, `2c-4g`, `2c-8g`, `2c-16g`, `4c-8g`, `4c-16g`, `4c-32g`,
`8c-16g` … `12c-96g`, a naš servis je na `1c-2g`. Cijene tih tipova nisam vidio; piše ih dashboard (Settings →
Instance Type), što je korak od jedne minute prije svake odluke.

| Tema | Stanje (nepotvrđeno, gdje provjeriti) |
|---|---|
| Background worker, private service | Iste instance i cijene kao web, bez besplatne razine. https://render.com/docs/background-workers |
| Cron job | Naplata po sekundi rada po cijeni instance (Standard ≈ $0,00058/min, Pro ≈ $0,00197/min), najmanje $1/mj po jobu, najdulje 12 h po pokretanju, bez diska. https://render.com/docs/cronjobs |
| Disk | $0,25/GB/mj: 5 GB = $1,25, 10 GB = $2,50. Samo jedan servis i jedna instanca; nije dostupan u buildu, cron jobu ni one-off jobu; servis s diskom nema deploy bez prekida (stara instanca se gasi prije nove; mjerenje u točki 2 se s tim slaže). https://render.com/docs/disks |
| Autoscaling | Samo vodoravno (broj instanci po cilju CPU/RAM), traži Professional workspace (≈ $19 po korisniku/mj). Servis s diskom ostaje na 1 instanci: za nas ne postoji. Veća instanca samo ručno. https://render.com/docs/scaling |
| CPU prioriteti, cgroups | Nema postavke ni u `render.yaml` ni u dashboardu: servis je jedan kontejner s limitom CPU-a i RAM-a. Unutar kontejnera rade `nice` (kod ga koristi: 10 i 5), SIGSTOP/SIGCONT nad vlastitim procesima i čitanje `/sys/fs/cgroup` (kod već čita `memory.stat`, vidi se u logu). Pisanje u cgroup i podizanje prioriteta: pretpostavljam da ne |
| Hetzner | https://www.hetzner.com/cloud/ , 10.11.2026. NIJE viđeno; rasponi u opciji D pokrivaju cjenik prije i poslije poskupljenja 2026. |

## 6. Jeftiniji put i kada nadogradnja ima smisla

Redom po učinku, sve +$0:
1. **Čuvar CPU-a** (`ops/cpuguard.py`, već u dizajn.md): svake sekunde razlika `usage_usec` iz `cpu.stat` prema kvoti
   iz `cpu.max`; iznad 90 % kroz 2–3 s pauzira (SIGSTOP, do 0,5 s) najtežu pozadinu dok ne padne ispod 80 %; nikad ne
   dira ui, trade, tg, live. Uz to u log svake minute: `nr_throttled` i `throttled_usec` te `cpu.pressure`,
   `io.pressure`, `memory.pressure` (some avg10). To je dokaz za "najviše 90–95 %" i mjera za okidače. "U svakom
   trenutku" znači prosjek od 1 s; unutar 100 ms jezgra je uvijek ili 0 ili 100 %.
2. **Nice gdje ga nema:** lagani poslovi rasporeda (`run_sched.run`, light), `run_top.py`, `run_watch.py`,
   minute-loop i hype sken bez brave idu na nice 0. Nice pomaže samo dok se procesi natječu za istu jezgru; kad se
   potroši kvota, staju svi do kraja perioda bez obzira na nice. Zato je čuvar glavni alat, nice dodatak.
3. **Brava po vrsti posla:** brava je uvedena zbog memorije na 512 MB. Mrežni poslovi (`run_dugo`) ne trebaju
   jedino mjesto: dva mjesta kad je slobodno ≥ 600 MB i CPU < 60 %, ili ih označiti laganima. Noćas bi 6 poslova
   prošlo bez 12–22 min čekanja, bez ijedne nove jezgre.
4. **Događaji umjesto anketa:** `.copy_wake` → `threading.Event` unutar UI procesa (webhook i kopija su u istom
   procesu) uz datoteku za druge procese; `run_trade` budi signal kad kopija upiše trade, puni prolaz svakih 5–10 s
   kao osigurač; 1-s fragmenti preko jedne otvorene veze ili uvjetnog GET-a. Popravci S1–S3 iz sekundni.md skidaju
   ≈ 10 % CPU-a stalno.
5. **Dostupnost:** jedan skupni deploy dnevno (pravilo već postoji; 9.11. ih je bilo 29); upisati `/healthz`
   (ruta postoji) kao health check u Renderu; uskladiti `render.yaml` (`plan: starter`) sa stvarnim planom, da ga
   sinkronizacija Blueprinta ne vrati na 0,5 CPU (nisam provjerio je li Blueprint aktivan); vanjska sonda, jer
   unutarnji nadzor ne vidi pad cijelog kontejnera.

**Okidači za opciju B** (nakon 7 dana s čuvarom; dovoljan je jedan):

| # | Mjera | Prag |
|---|---|---|
| T1 | Čuvar pauzira pozadinu | > 20 % vremena 06–01 CET u 3 od 7 dana, ili `throttled_usec` > 1 % vremena unatoč čuvaru |
| T2 | Noćni prozor | U 06:00 neki noćni posao još radi ili čeka u 2 od 7 noći, A držač brave je trošio > 70 % jezgre. Ako je trošio < 30 %: popraviti bravu ili API limit, ne kupovati CPU |
| T3 | p95 odgovora `/healthz` i 1-s fragmenta (sonda svakih 30 s) | > 1 s u više od 1 % sondi dnevno uz `cpu.pressure` > 20 %. Ako je visok `io.pressure` ili `memory.pressure`: razlog je RAM ili disk (smanjiti hype.db ili 4 GB) |
| T4 | Autopilot | p95 "signal primljen → demo ulaz" > 3 s ili "demo ulaz → poslan swap" > 2 s u minutama s CPU-om ≥ 90 % (traži vrijeme primitka signala, kojeg `chain_trades` danas nema) |

## Provjereno / Pretpostavka

**Provjereno (10.11.2026., Render API i kod):** plan `1c-2g`, limiti 1 CPU / 2 GiB, prazan health check, popis tipova
instanci; sve brojke u točki 2 (CPU po 5 min i po 1 min, trajanja gradnji i KOL kruga, HTTP statusi, deployi, RAM i
veličine baza iz log linije "zdravlje"); raspored procesa, brava, nice, noćni prozor, nadzor memorije i ankete od
1 s (start.sh, ops/heavy.py, ops/health.py, ui/pagecache.py, run_ui.py, run_trade.py, league/auto.py, run_sched.py,
run_kol.py, run_paper.py, tg/config.json).

**Pretpostavka:** sve cijene (nepotvrđeno, razlog gore); Renderova pravila o disku, autoscalingu i cron jobovima
(iz dokumentacije kakvu znam, danas nije otvorena); da je CPU limit kvota vremena pod kojom staju svi procesi i da
kontejner vidi više jezgri domaćina (provjera: `nproc` i `cpu.max` pri startu); usporenje ≈ 1/D; mrežni dio reakcije
Autopilota u sekundama; uzrok noćašnjih sporih gradnji (disk ili RAM); stvarni prekid po deployu (62 s uključuje
build, prekid je kraći i nije izmjeren); 17 CPU-sati dnevno (iz 2 h mjerenja); tečaj 1 € ≈ $1,1.

**Nije napravljeno:** pregled cjenika uživo. Kad pretraga bude dostupna ili se render.com i www.hetzner.com
dopuste u mreži sesije, treba potvrditi tablicu u točki 5 i cijenu tipa `2c-4g`.

## Provjera cijena

Druga provjera, 10.11.2026. **Nijedna cijena nije potvrđena ni ispravljena na službenom izvoru:** WebSearch je odbio
sva 3 upita (zajednički limit workflowa od 200 pretraga potrošen), WebFetch ne dolazi do render.com ni
www.hetzner.com (izvan dopuštene mreže sesije). Cijene zato ostaju **nepotvrđeno**; drugi prolaz istog modela nije
neovisna potvrda. Potvrđeno je ono što se vidi u Render API-ju i u kodu te račun u datoteci. Preporuka se ne mijenja.

| Opcija | Tvrdnja u datoteci | Presuda | Izvor i datum | Napomena |
|---|---|---|---|---|
| A | +$0/mj; plan `1c-2g`, limit 1 CPU / 2 GiB, 1 instanca, disk 5 GB, health check prazan | **potvrđeno** | Render API `list_services` i `get_metrics` (`cpu_limit` = 1, `memory_limit` = 2.147.483.600 B), viđeno 10.11.2026.; `render.yaml:6`, `:12` | Promjena je samo u kodu, nema nove usluge |
| A | Današnji račun ≈ $26/mj (instanca ≈ 25 + disk 1,25) | **nepotvrđeno** | https://render.com/pricing , 10.11.2026. nije viđeno | Dvije pretpostavke: cijena starog "Standard" i da novi tip `1c-2g` košta isto. Stvarni iznos piše u dashboardu (Billing) |
| B | `2c-4g` ≈ $85 + disk = ≈ $86; +≈ $60/mj; ≈ $720/god | **nepotvrđeno** (račun točan) | https://render.com/pricing , nije viđeno. Tip `2c-4g` postoji: popis planova u Render API alatu, viđeno 10.11.2026. | 86,25 − 26,25 = 60,00; × 12 = 720 |
| C | 2 × `1c-2g` ≈ $51 (+25); Postgres ≈ $6–20; noćni cron job ≈ $18; disk vidi jedan servis | **nepotvrđeno** (račun točan) | https://render.com/docs/disks , /docs/cronjobs , /docs/background-workers , /docs/scaling , nije viđeno | 2 × 25 + 1,25 = 51,25; 300 min × 30–31 noć × $0,00197 = $17,7–18,3. Postgres od $6 je najmanja instanca, bez prostora za 2,9 GB |
| D | Hetzner CX23 / CPX32 / CCX13 / CCX23 u EUR, ukupno ≈ $4–35/mj | **nepotvrđeno**; raspon **ispravljen** | https://www.hetzner.com/cloud/ , 10.11.2026. nije viđeno | $4–35 je goli server. S IPv4 i backupom (koje red sam navodi): **≈ $5–43/mj**. Nije provjereno: PDV, tečaj (svakih 0,05 $/€ mijenja gornju granicu za ≈ $2), CX33 (4 dijeljene vCPU) kojeg u redu nema |
| Render, ostalo | Disk $0,25/GB; cron $0,00058 i $0,00197/min, min. $1, najdulje 12 h; Professional ≈ $19/korisnik; autoscaling samo vodoravno; dnevni snimak diska | **nepotvrđeno** | adrese iz točke 5, nije viđeno | Stope po minuti slažu se s mjesečnim cijenama iz iste tablice (25 i 85 / 43.200 min), što ne dokazuje da su cijene točne |

**Račun u datoteci (provjereno ponovnim izračunom i ponovnim dohvatom metrike):**

| Brojka | Provjera | Ishod |
|---|---|---|
| CPU ≥ 90 % u 91 od 241 intervala (38 %), medijan 42 % | Ponovni dohvat `cpu_usage` po 5 min, 9.11. 00:00–22:20 UTC | Točno: 91/241 = 37,8 %, medijan 0,42. Prozor ima 268 intervala, 27 je bez podatka; prema cijelom prozoru 34 %, što se slaže s "465 min, 35 %" |
| 127 minuta nakon #75 | 22:20 → 00:27 UTC | Točno |
| ≈ 17 CPU-sati dnevno s čuvarom | (0,90 − 0,18) × 24 | Točno: 17,3 (procjena iz 2 h) |
| Gradnje ≈ 2 % jezgre | 7 s / 300 s | Točno: 2,3 % |
| Reakcija −1 s prosjek, −2 s najgore | dvije ankete od 1 s | Točno |
| HTTP udjeli, RAM, baze | 69 + 18,3 + 12,6 = 99,9 %; 0,28–0,42 + 1,36–1,57 = 1,64–1,99 GB; pet najvećih baza = 2.724 MB od ≈ 2,9 GB | Dosljedno |
| "Trećina cijene opcije B" (D) | CCX23 goli $27–35 prema $86 | 31–41 %; s IPv4 i backupom 38–50 % |

**Tvrdnje o kodu (repo, 10.11.2026.):**

| Tvrdnja | Ishod | Dokaz |
|---|---|---|
| `render.yaml` piše `plan: starter`, disk 5 GB | točno | `render.yaml:6`, `:12` (API: `1c-2g`) |
| 24 baze; 10 stalnih procesa (9 pod `keep` + `run_watch`) | točno | `start.sh:9`; `start.sh:42`, `46`, `124`, `127`, `150`, `158`, `160`, `172`, `175`, `83` |
| Jedna brava (flock), nice 10, noć 01–06 Zagreb, `--prio`; uvedena zbog memorije na 512 MB | točno | `ops/heavy.py:1-6`, `18`, `83`, `113`, `120-121`, `178-183` |
| Nadzor memorije svake minute: 800 MB, trade 1.200 MB; čita cgroup `memory.stat` | točno | `ops/health.py:47-48`, `57-71`, `78`; `start.sh:56` |
| Gradnja u djetetu: nice 5, `UI_BUILDS=1`, prag 600 MB, zagrijavanje 300 s; `/ekipe` 180 s, `/kol` 30 s | točno | `run_ui.py:358`, `414-436`, `1232`, `351`; `ui/pagecache.py:23` |
| `/healthz` postoji | točno | `run_ui.py:498-502` |
| league auto/copy 20 s, buđenje ≤ 1 s (anketa datoteke `.copy_wake`); `run_trade` anketa 1 s | točno | `league/auto.py:22`, `314-322`; `league/copy.py:62-80`; `run_trade.py:338`; `trade/config.json:10` |
| `run_paper`: petlja 60 s, sken 120 s, niti 5/30/60/600 s; nakon 10 min sken bez brave i bez nice | točno | `run_paper.py:1172`, `1174`, `908`, `1076`, `1088`, `1100`, `1136-1139` |
| `run_kol loop` 20 min: `once` pod bravom i nice 10, `search-round` bez brave, nice 10 | točno | `start.sh:124`; `run_kol.py:344-349` |
| `run_sched`: teški pod bravom i nice 10, lagani bez oboje; learn6, exits_rb, shadow, corr samo noću | točno | `run_sched.py:35`, `171`, `173`, `179`, `184` |
| `run_top` 180 s bez nice; simianx 180 min; dokazani + copy 3 h | točno | `start.sh:65`, `170`, `113-120`; `run_top.py:175` |
| Telegram "praćeni kanali svake 2 s" | **ispravljeno: ≥ 3 s** | `poll_followed_s` je 2 (`tg/config.json:35`, `tg/poll.py:49`), ali petlja spava `tick_s` = 3 s po prolazu (`tg/config.json:3`, `run_tg.py:116`) |
| `ops/cpuguard.py` postoji samo u dizajnu | točno | datoteke nema; `audit/2026-11-10/dizajn.md:114-115` |
| DexScreener 300/min po IP-u; Helius 50 RPC/s i 10 M kredita | točno kao zapis u kodu; limit kod dobavljača danas nije viđen | `dexscreener/client.py:3-6`; `render.yaml:38`; `usage/budget.json:3` |

**Preporuka nakon provjere: ista.** Opcija A (+$0) ne ovisi ni o jednoj nepotvrđenoj cijeni, a jedini ispravljeni
iznos (D: ≈ $5–43 umjesto ≈ $4–35) ne mijenja redoslijed. Opcija B ostaje vezana uz okidače T1–T4. Prije klika na
`2c-4g` treba pročitati cijenu u Render dashboardu (Settings → Instance Type, 1 minuta, $0); ako je viša od ≈ $85,
iznos "+≈ $60/mj" u ovoj datoteci više ne vrijedi.

**Provjereno (10.11.2026.):** plan, limiti, disk, health check i popis tipova (Render API); 91/241 i medijan 42 %
(ponovni dohvat metrike); sav račun u tablici gore; tvrdnje o kodu s navedenim redovima.
**Pretpostavka:** sve cijene i pravila Rendera i Hetznera u ovoj datoteci, uključujući da `1c-2g` košta kao stari
"Standard". **Nije napravljeno:** pregled službenih cjenika. Za to treba dopustiti render.com i www.hetzner.com u
mrežnim postavkama sesije ili ponoviti kad pretraga opet bude dostupna.
