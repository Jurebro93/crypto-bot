"""Fokus midcap (15.11., vlasnik: "Ne želim više mikrokapove uopće, nikakvi resursi na njih: ni trgovanje, ni skeniranje,
ni analiza. Sve resurse prebaci na midcapove ... 2M do 200M ... posebno TRENDING tokene na DexScreeneru").

ONE owner switch, trade/settings "fokus_midcap" (an OWNER_SWITCH: "uživo" = on; switched on once by his order 15.11. in
ui/assistnotes.OWNER_FLAG_ORDERS; any other mode = exactly the old behaviour). One tap under Prekidači undoes it: every
job below reads the switch at the start of its pass (the short processes) or every few seconds (the loops).

  OFF        the job does not run while the switch is on (its pass ends at once: no database, no network, no line)
  RETARGET   the job runs, but on the midcaps (MC 2M-200M, veliki/config.json "data") instead of the microcaps
  kept       everything else: open positions' exits, the owner's manual trading, copy (behind the 5M capgate), the
             midcap strategy (veliki/), the OpenAI critic, the morning report, safety, wallet / real-trade bookkeeping

Who asks:
  ops/heavy.main      every job started through "python3 -m ops.heavy ..." (skip_cmd on its command line)
  run_sched.run       every scheduler job (the same matcher on its command)
  the runners below   gate() at the start of their main (the ones start.sh runs without ops.heavy)
  loops               on() (cached 2 s by trade/settings.flag)

python3 -m ops.fokus     the start line ("fokus midcap: isključeno N poslova ...") - start.sh, once a start
"""
import os
import sys
import time

SWITCH = "fokus_midcap"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (canonical script / module, first sub-command or None = any) -> (key, what it did for the microcaps)
OFF = (
    (("run_scan", None), "skener", "skener tržišta od 10k (pump.fun/PumpSwap/Raydium, svakih 150 s)"),
    (("kol.precall", None), "insajderi", "cijene novih pump.fun lansiranja +10/+30/+90 min i insajderi prije poziva"),
    (("kol.groupdisc", None), "grupe", "ekipe callera i skriveni popisi novčanika (Helius noću)"),
    (("kol.preshill", None), "shill", "kupci prije shill mreže (Helius noću, anketa 30 min)"),
    (("run_hype", "learn"), "hype_learn", "pametni novčanici iz ranih kupaca pobjednika (Helius)"),
    (("run_hype", "scan"), "hype_scan", "hype sken novih tokena (dijete demo petlje svake 2 min)"),
    (("run_hype", "status"), "tokenstatus", "status hype tokena svakih 6 h (DexScreener + GeckoTerminal)"),
    (("run_wallets", "harvest"), "wallets_harvest", "skupljanje novčanika iz analiza mikrokapova (Helius)"),
    (("run_wallets", "score"), "wallets_score", "ocjenjivanje novčanika (Helius, 6000 kredita svaka 3 h noću)"),
    (("wallets.solfill", None), "solfill", "iznosi prodaja tuđih tradeova iz transakcija (Helius)"),
    (("research.hope", None), "research", "jednokratno istraživanje mikrokapa Hope (Helius)"),
    (("research.hope_report", None), "research", "sažetak istraživanja Hope"),
    (("run_range", None), "range", "range_dca + range_market 30k-5M lista (snimke svake minute, noćni backtest)"),
    (("run_topics", None), "eventi", "event tokeni: podudaranje novih lansiranja s temama"),
    (("run_momentum", None), "momentum", "momentum scalp mikrokapova (snimke svake minute, noćni backtest)"),
    (("run_proposals", None), "prijedlozi", "prijedlozi svih (mikrokap) strategija svakih 150 s"),
    (("kol.zadnjih5", None), "zadnjih5", "walk-forward zadnjih 5 poziva influencera i novčanika"),
    (("run_izlazi", None), "izlazi", "naučeni izlazi po izvoru mikrokap poziva"),
    (("run_konsenzus", None), "konsenzus", "konsenzus izvora (istraživanje walk-forward)"),
    (("run_oscilator", None), "oscilator", "oscilator: walk-forward skalpiranja na minutnim podacima mikrokapova"),
    (("run_events", "night"), "events_night", "noćna obrada događaja: nemjereni pozivi iz GT minuta, Helius 5000"),
    (("run_kol", "backfill"), "kol_backfill", "povijest poziva (Apify, plaćeno)"),
    (("kol.backfill_calls", None), "kolfill", "nemjereni pozivi noću (300 GeckoTerminal)"),
    (("run_learn", None), "learn", "učenje hype težina, sjena, masovna sjena (tisuće nevidljivih tradeova), AI oznake objava"),
    (("run_corr", None), "corr", "korelacije KOL / wallet skupina i pump faktora (+ Claude jednom dnevno)"),
    (("run_exits", "fit"), "exits_fit", "dnevno učenje pravila izlaza po hype klasi"),
    (("run_dex", "scan"), "dex_scan", "DexScreener tokeni događaja od 5k likvidnosti"),
    (("run_watch", None), "watch", "tokeni prije događaja: DexScreener svaki sat, Helius kupci (3000 kredita)"),
)
# loops / processes that keep running but on the midcaps (or without the microcap part) while the switch is on
RETARGET = (
    ("live", "PumpPortal: bez novih lansiranja (subscribeNewToken) i bez migracija; samo otvorene pozicije i praćeni "
             "novčanici igrača"),
    ("paper", "demo petlja: bez hype skena i bez novih demo ulaza (koltest, strategije); izlazi otvorenih ostaju"),
    ("auto", "Natjecanje: bez ulaza mikrokap strategija (fast path, konsenzus, range, momentum, prijedlozi); kopiranje "
             "(iza 5M), DCA i svi izlazi ostaju"),
    ("fast", "brzi put (i x_call_scalp) miruje kao da je zastavica isključena"),
    ("kol_measure", "KOL mjerenje cijene nakon poziva samo za tokene midcap liste"),
    ("kol_minute", "minutne svijeće nakon poziva samo za tokene midcap liste"),
    ("top", "provjera ruga / holdera: otvorene pozicije + midcap lista umjesto mikrokap preporuka"),
    ("grok", "Grokovi zadaci: midcap_review za trending midcapove umjesto X provjera mikrokap kandidata"),
    ("xmom", "X momentum (twitterapi, isti dnevni strop skenera 0,30 $) za trending midcapove"),
)
KEPT = ("ui", "trade (pravi novac / probni swapovi)", "cpuguard", "uptime", "health", "diskreport", "retencija",
        "rug arhiva", "kalendar", "dugo", "simianx", "veliki (lista, backtest, demo)", "zonewatch", "kol krug (X pozivi)",
        "tg", "novčanici dokazani / rang / copy (samo baze)", "tržište / BTC", "potrošnja", "web", "events tick",
        "EV izvještaj", "dnevni trošak", "kritičar", "jutarnji izvještaj", "povrat pravila izlaza",
        "stranice tokena (midcap svemir + top 100)")
# 15.11. (vlasnik: "dio resursa zadrži za ovo, veći dio ide na midcapove"): jobs that run on microcap data WHILE the
# switch is on, as an explicit exception with their own budget (they are never in OFF, so nothing above stops them)
EXCEPTIONS = (
    (("run_insajderi", None), "insajderi2",
     "Insajderi 2.0: kupci prije poziva / skokova koji prodaju u skok, pametni novac (insajderi/); strop Helius "
     "kredita dnevno (16 % starih poslova insajderi/grupe/shill/novčanici, zadano 3.500), nice, veliki prolaz noću"),
)
_OFF_KEYS = {key for _m, key, _w in OFF}
# what each OFF / RETARGET job cost, from its own caps in the code and start.sh (Pretpostavka: the caps, not a measured
# day; the CPU guard logs only pauses and the biggest protected consumer, so the CPU column is the job class / budget)
SAVED = {
    "skener": "CPU: kratki proces svakih 150 s (SCANS); API: Helius do 30.000 kr./dan, GeckoTerminal 150/dan, X 0,30 $/dan",
    "insajderi": "DexScreener do 4.000/dan (besplatno), Helius 3.000 kr./noć; disk: nova lansiranja u hype.db",
    "grupe": "Helius 3.000 kr./noć; CPU: noćni prolaz + svakih 15 min",
    "shill": "Helius 3.000 kr./noć + 1.000/dan; CPU: noćni prolaz + svakih 30 min",
    "hype_learn": "Helius (učenje 5 pobjednika dnevno); CPU noću",
    "hype_scan": "CPU: najveći pozadinski sken (dijete demo petlje svake 2 min, ~65 MB); DexScreener + RugCheck",
    "tokenstatus": "DexScreener 30 + GeckoTerminal do 120 svakih 6 h",
    "wallets_harvest": "Helius (skupljanje); CPU noću",
    "wallets_score": "Helius 6.000 kr. po prolazu (do ~12.000/noć), 15 % mjesečnih kredita",
    "solfill": "Helius 200 getTransaction/noć",
    "research": "jednokratno ~1.200 kr. (već odrađeno)",
    "range": "DexScreener do 6.500/dan, GeckoTerminal 60/dan (prioritet ključa), Helius 3.000/dan; range.db snimke svake minute",
    "eventi": "DexScreener 1.200/dan, GeckoTerminal 20/dan, Birdeye 100",
    "momentum": "DexScreener svake minute (60 tokena), GeckoTerminal 100/dan + 60 noću, Helius 2.000/dan",
    "prijedlozi": "DexScreener serije svakih 150 s; CPU",
    "zadnjih5": "CPU: walk-forward pod teškom bravom nakon deploya i noću",
    "izlazi": "CPU: walk-forward svih izvora noću",
    "konsenzus": "CPU: 20 min proračuna nakon deploya i noću",
    "oscilator": "CPU: 15 min proračuna nakon deploya i noću",
    "events_night": "GeckoTerminal 600/noć, Helius 5.000/noć; CPU noću",
    "kol_backfill": "Apify (plaćeno, samo uz KOL_BACKFILL_USD)",
    "kolfill": "GeckoTerminal 300/noć",
    "learn": "CPU (dnevni fit, sjena); masovno: GeckoTerminal ključ do 1.000/noć (~60 % ključa 11.11.) + besplatni danju; "
             "postai: Claude Haiku API",
    "corr": "CPU noću + jedan Claude poziv dnevno",
    "exits_fit": "CPU dnevno",
    "dex_scan": "DexScreener svakih 6 h",
    "watch": "DexScreener svaki sat, Helius do 3.000 kr. po prolazu",
    "live": "PumpPortal: svako novo pump.fun lansiranje + migracije (CPU slušača, hype.db rast), trade poruke kandidata "
            "(SOL novčanika za podatke, strop LIVE_MAX_TRADES_DAY)",
    "paper": "CPU hype skena i ulaza demo bota",
    "auto": "CPU ulaza mikrokap strategija u run_ui",
    "fast": "Helius do 20.000 kr./dan (samo kad RugCheck ne radi), DexScreener/RugCheck po signalu",
    "kol_measure": "GeckoTerminal (rezervira besplatni limit do 8 min svakih 20 min), Helius tokovi",
    "kol_minute": "GeckoTerminal minutne svijeće (prioritet ključa, ~27 % ključa 11.11.), minute.db rast",
    "top": "isto (RugCheck/Jupiter/Helius 30/dan), samo drugi tokeni",
    "grok": "Grokov rad (bez našeg troška)",
    "xmom": "isti strop 0,30 $/dan",
}


def on(con=None):
    """True while the owner switch fokus_midcap is "live". Never raises: unreadable = off (the old behaviour)."""
    if os.environ.get("FOKUS_MIDCAP_FORCE") in ("0", "1"):   # tests / an emergency override without the database
        return os.environ["FOKUS_MIDCAP_FORCE"] == "1"
    try:
        from trade import settings
        return settings.flag(SWITCH, con) == "live"
    except Exception:  # noqa: BLE001
        return False


def canon(argv):
    """(script or module, first sub-command) of a command line: [python, "run_x.py", "sub", ...],
    [python, "-m", "kol.precall", "night"], ["/abs/kol/precall.py", "incr"] (sys.argv of "-m"), ["kol/backfill_calls.py"]."""
    a = [str(x) for x in (argv or [])]
    if a and (os.path.basename(a[0]).startswith("python") or a[0] == sys.executable):
        a = a[1:]
    if a and a[0] == "-m":
        mod, rest = (a[1] if len(a) > 1 else ""), a[2:]
    elif a:
        p = a[0]
        if os.path.isabs(p) and p.startswith(ROOT + os.sep):
            p = os.path.relpath(p, ROOT)
        p = p[:-3] if p.endswith(".py") else p
        mod, rest = p.replace(os.sep, ".").lstrip("."), a[1:]
    else:
        return "", None
    sub = next((x for x in rest if not x.startswith("-")), None)
    return mod, sub


def off_key(argv):
    """The OFF key of this command line, else None (whatever the switch). An EXCEPTION is never off."""
    mod, sub = canon(argv)
    if any(m == mod and (s is None or s == sub) for (m, s), _k, _w in EXCEPTIONS):
        return None
    for (m, s), key, _what in OFF:
        if m == mod and (s is None or s == sub):
            return key
    return None


def skip_cmd(argv, con=None):
    """The OFF key when the switch is on and this command is a microcap job, else None."""
    key = off_key(argv)
    return key if key and on(con) else None


def skip(key, con=None):
    """True when the switch is on and `key` is an OFF job (or a RETARGET part asking whether to drop its microcap part)."""
    return on(con) and (key in _OFF_KEYS or key in {k for k, _w in RETARGET})


def gate(argv=None):
    """At the start of a runner's main: exit 0 at once while the switch is on and this is a microcap job."""
    if skip_cmd(sys.argv if argv is None else argv):
        sys.exit(0)


# ---------- the midcap list (veliki/midcap.py: midcap.db) for the retargeted jobs ------------------------------------

_MINTS = {"ts": 0.0, "v": frozenset(), "rows": []}


def midcap_rows(max_age_s=60):
    """[{"mint", "symbol", "mcap", "vol24", "trend"}] of the midcap data universe, by 24 h volume (cached)."""
    if time.monotonic() - _MINTS["ts"] < max_age_s and _MINTS["ts"]:
        return list(_MINTS["rows"])
    rows = []
    try:
        from veliki import midcap
        rows = midcap.members()
    except Exception:  # noqa: BLE001 - no midcap.db yet: the veliki list
        rows = []
    if not rows:
        try:
            from veliki import store
            rows = [{"mint": x["mint"], "symbol": x.get("symbol"), "mcap": x.get("mcap"), "vol24": x.get("vol24"),
                     "trend": 0} for x in (store.the_list() or {}).get("tokens") or [] if x.get("mint")]
        except Exception:  # noqa: BLE001
            rows = []
    _MINTS.update(ts=time.monotonic(), rows=rows, v=frozenset(r["mint"] for r in rows))
    return list(rows)


def midcap_mints(max_age_s=60):
    midcap_rows(max_age_s)
    return _MINTS["v"]


def held_tokens():
    """Mints we hold right now (league.db open trades of every account, veliki demo, trade.db real lots): their rug
    and holder checks stay whatever the switch says."""
    import sqlite3
    out = []
    for db, sql in (("league.db", "SELECT DISTINCT token FROM trades WHERE status='open'"),
                    ("league.db", "SELECT DISTINCT token FROM veliki_trades WHERE status='open'"),
                    ("trade.db", "SELECT DISTINCT token FROM positions WHERE status IN ('open','pending')"),
                    ("paper.db", "SELECT DISTINCT token FROM trades WHERE status='open'")):
        p = os.path.join(ROOT, db)
        if not os.path.exists(p):
            continue
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
            try:
                out += [r[0] for r in con.execute(sql) if r[0]]
            finally:
                con.close()
        except sqlite3.Error:
            continue
    return list(dict.fromkeys(out))


# ---------- the lines ---------------------------------------------------------------------------------------------------

def start_line(con=None):
    """fokus midcap: isključeno N poslova za mikrokapove (...), preusmjereno M (...); prikupljanje: K midcap tokena
    (2M-200M), izvori ..."""
    try:
        from veliki import midcap
        c = midcap.config()
        k = len(midcap.members())
        src = midcap.SOURCES_TEXT
    except Exception as e:  # noqa: BLE001
        c, k, src = {"min_mcap": 2e6, "max_mcap": 2e8}, 0, f"(midcap.db nečitljiv: {type(e).__name__})"
    rng = f"{c['min_mcap'] / 1e6:,.0f}M–{c['max_mcap'] / 1e6:,.0f}M"
    if not on(con):
        return (f"fokus midcap: ISKLJUČEN (prekidač {SWITCH} nije „uživo”): svi poslovi kao prije; prikupljanje midcapova "
                f"({rng}) ne radi")
    offs = list(dict.fromkeys(key for _m, key, _w in OFF))
    return (f"fokus midcap: isključeno {len(offs)} poslova za mikrokapove ({', '.join(offs)}), preusmjereno "
            f"{len(RETARGET)} ({', '.join(k_ for k_, _w in RETARGET)}); iznimka s budžetom: "
            f"{', '.join(k_ for _m, k_, _w in EXCEPTIONS)}; prikupljanje: {k} midcap tokena ({rng}), izvori {src}")


def table():
    """[(key, what it did, "isključeno" | "preusmjereno: ...")] for the report and output/midpivot.md."""
    out, seen = [], set()
    for _m, key, what in OFF:
        if key not in seen:
            seen.add(key)
            out.append((key, what, "isključeno"))
    out += [(k, "", "preusmjereno: " + w) for k, w in RETARGET]
    out += [(k, w, "iznimka s budžetom") for _m, k, w in EXCEPTIONS]
    return out


def markdown():
    """output/midpivot.md: the inventory (job -> what it did -> off / retargeted -> what it cost)."""
    lines = ["# Fokus midcap — popis poslova (ops/fokus.py)", "",
             f"Prekidač `{SWITCH}`: {'UKLJUČEN' if on() else 'isključen'}. Brojke troška su stropovi iz koda "
             "(Pretpostavka), ne izmjereni dan.", "", "| posao | što je radilo | sada | trošak koji otpada |",
             "|---|---|---|---|"]
    for key, what, how in table():
        lines.append(f"| {key} | {what or '—'} | {how} | {SAVED.get(key, '—')} |")
    lines += ["", "Zadržano: " + ", ".join(KEPT) + ".", "",
              "Novo: sakupljač midcapova (veliki/midcap.py, run_veliki.py midcap svakih 90 s): " + start_line()]
    return "\n".join(lines) + "\n"


def main(argv=None):
    print(start_line(), flush=True)
    try:   # the inventory next to the other reports (output/ is on the persistent disk)
        os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
        with open(os.path.join(ROOT, "output", "midpivot.md"), "w", encoding="utf-8") as f:
            f.write(markdown())
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
