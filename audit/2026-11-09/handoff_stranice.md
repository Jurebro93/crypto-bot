# Handoff iz grupe "stranice" (9.11.2026, audit) – datoteke izvan mog vlasništva

Što sam napravio u svojim datotekama (kontekst): ui/kol.py (hook_handles iz kv 'xhook', minute_stats/minute_cells,
speed_badge, stupci +10/+15 % prije stopa + 🔥 vruća lista na ljestvici, stupac "X webhook" u Prati uživo), ui/copytrade.py
(kol_rows: novi ključevi hook/fast/ms/hot, sort fast→hot→score, 'live' NEPROMIJENJEN = monitor), ui/pocetna.py (najbolji
influencer po minutnoj mjeri, oznaka "(istraživačka knjiga)" uz 24 h/7 d, highlight "Svi webhook novčanici" + broj
praćenih+dokazanih, _hl_converge preskače not_a_memecoin i archive.blocked), ui/pages.py (stupci Dokazani dvaput / Prati
Autopilot / Autopilot 14 d, dokazani+praćeni na vrh "Za kopiranje", as_of liste), ui/tokens.py (market(): starost tržišne
provjere > 15 min i oznaka "ispod 30k", zaglavlje "Zadnji signal"), ui/confidence.py + ui/evidence.py (None holder udjeli =
"nepoznato", nikad +6 / prolaz), ui/overview.py (_holder_shape iz topcheck rc + rug.db bez novih upita).

## P42 – ui/autopilot.py:109-113 i :314 (auto_targets), ui/pravitrade.py:460, ui/help.py:169 – "uživo" = webhook skup
- `ui/copytrade.kol_rows()` redci sad nose `r["hook"]` (račun je u pravilima X webhooka, kv 'xhook' values) i
  `r["fast"] = r["live"] or r["hook"]`; `r["live"]` ostaje samo xquik monitor tablica da se ne mijenja ponašanje
  autopilota bez odluke.
- Što: u `kol_recs` (autopilot.py:109-113) koristiti `good[h]["fast"]` za `live`/why i sort; u `auto_targets`
  (autopilot.py:314) filtrirati po `r["fast"]` umjesto `r["live"]` – inače računi koje webhook dostavlja u sekundama
  (vruća lista, praćeni, veliki) nikad ne ulaze u auto-izbor, a lista je prazna bez APIFY_TOKEN-a (verifikator P42).
  U `_kol_why` tekst "Pratimo ga uživo" → "X webhook / xquik: objave stižu u sekundama". help.py:169 i pravitrade.py:460
  opisuju 'uživo' kao monitor: dodati webhook.
- Pogođeni testovi: tests/test_autopilot_zovu_offline.py, tests/test_pravitrade_offline.py (recs s ključem "live";
  ako se pređe na "fast", fixture dodaje `"fast": live`).

## P43 – ui/autopilot.py:23,57-77 kol_stats – score iz minutne mjere
- `kol_rows()` redci nose `r["ms"]` = kol/minute.handle_stats redak (hit10, hit15, sl, n, med_t10…; None dok nema 3+
  poziva u 14 dana) i `r["hot"]` (vruća lista). Što: u `kol_stats`/`kol_recs` score računati iz `ms["hit15"]` (uz kaznu
  `ms["sl"]`) kad `ms["n"] >= 3`, fallback na postojeći max24 HIT=0.5; u why ispisati obje mjere. Isti helper:
  `ui.kol.minute_stats(now)` → (handle→stats, hot set), čist, bez stanja.
- Pogođeni testovi: tests/test_autopilot_zovu_offline.py (kol_stats), tests/test_pravitrade_offline.py.

## P70 – ui/pocetna.py:264 kartica "Kupnje i prodaje praćenih novčanika" (vlasništvo moje, test NIJE)
- tests/test_golden_numbers_offline.py:145 traži točan label 'Kupnje i prodaje praćenih novčanika' pa kartica NIJE
  preimenovana; highlight (pocetna.py _hl_wallets) jest ("Svi webhook novčanici u zadnja 24 h"). Što: promijeniti label na
  "Kupnje i prodaje svih webhook novčanika" u pocetna.py:264 i test_golden_numbers_offline.py:145 u istom commitu.
- ui/core.py:82-91 wallet_block (/wallets Aktivnost): naslov/opis feeda u ui/pages.py je moj, ali blok je u core.py;
  po želji dodati u opis "svi webhook novčanici (leaderboard), ne samo praćeni".

## P56 (handoff izvori) – run_hype.py:287-290 extra["pumpfun"]
- ui/overview.token_rows sad puni det["pumpfun"] iz topcheck rc + rug.db (ui/overview._holder_shape) kad ga sken nije
  dao; sken (run_hype.py) i dalje piše prazan pumpfun – preporuka iz handoff_izvori stoji (holders.pumpfun_shape([t]) pri
  skenu), da i pop-up /token/ i učenje (learn/confmodel) vide iste udjele.
- ui/radar.risks (moje) NIJE mijenjan: _pct(None)=0 ne prijavljuje rizik, što je ispravno (nepoznato nije rizik).

## P83/P84 – hype/tokenstatus.market_cell
- Starost provjere i "ispod 30k" dodaje omotač ui/tokens.market(); market_cell je nepromijenjen. Po želji prebaciti
  `ago(checked_ts)` u market_cell (grana has_pair) da i drugi pozivači (ui/pravitrade?) dobiju oznaku.

## Testovi
- Puni `python3 -m unittest discover -s tests` zelen pri završetku (1009 testova). Tijekom rada su privremeno padali
  tests/test_ekipa_follow_offline.py i tests/test_autopilot_zovu_offline.py (zadani stop '-20%' iz league/copy, grupa novac)
  i tests/test_audit_20261109_zivo_offline.py – druge grupe su ih popravile, nije moje.

## Napomene
- ui/pagecache._same_snapshot: provjereno, _save_snap preskače spremanje iste stranice (mtime ostaje) – test dodan u
  tests/test_audit_20261109_stranice_offline.py::SnapshotAge. Ništa nije mijenjano.
- Nema novih mrežnih poziva: svi novi podaci su čitanja kol.db kv/monitor, minute.db, wallets.db (dokazani), league.db
  (follows), hype.db chain_trades, topcheck/rug tablice već u memoriji; /kol i /ekipe builderi ostaju čisti.
