"""Plain-Croatian names for everything the dashboard shows that comes from code: feature keys, decisions, event
kinds, signal sources, config keys, scripts, databases. The dashboard is for a trader, not a developer: no file
names, script names, commands, env vars or raw keys on any page. Add new keys here when a module adds them.
"""
import re

# hype score features (hype/weights.json): short name shown in tables and sentences
FEATURE = {
    "fresh": "Svježina (starost tokena)",
    "turnover": "Brzina novca (volumen / likvidnost)",
    "buy_pressure": "Pritisak kupaca",
    "momentum": "Rast cijene u zadnjem satu",
    "activity": "Broj transakcija",
    "paid": "Plaćena promocija na DexScreeneru",
    "socials": "Društvene mreže i web",
    "narrative": "Vruća tema (kopije istog imena)",
    "calendar": "Veza s događajem iz kalendara",
    "telegram": "Objave u Telegram kanalima",
    "smart_money": "Smart walleti među prvim kupcima",
    "revival": "Stari token se budi",
    "takeover": "Preuzimanje zajednice (CTO)",
    "x_buzz": "Priča se na X-u",
    "kol_wallets": "KOL walleti trejdaju token",
    "x_trend": "Ime je trend na X-u",
    "kol_x": "Praćeni KOL-ovi objavili token",
    "search_trend": "Rast Google pretrage",
    "kol_group": "Grupni poziv KOL-ova",
    "konvergencija": "Više izvora zove isto (X + Telegram + novčanici)",
    "veliki_kupuju": "Kupuju ga veliki holderi dugoročnih tokena",
    "pump_live": "Uživo stream na pump.fun",
    "put_brzina": "Brzina rasta do sadašnjeg mcapa",
    "put_skokovitost": "Rast u jednom skoku",
    "put_zadrzavanje": "Drži se blizu vrha",
    "market_regime": "Vrućina tržišta",
    "snaga_volumen": "Volumen drži ritam",
    "snaga_txn": "Transakcije drže ritam",
    "rast_holdera": "Rast broja holdera",
    "organski": "Organski rast (novi holderi, ne vrtnja)",
    "krivulja_starost": "Dugo na pump.fun krivulji",
    "krivulja_bez_mayhema": "Bez mayhem načina",
    "krivulja_organski_volumen": "Volumen nije od trading botova",
    "krivulja_dev_drzi": "Dev još drži dio",
    "krivulja_dev_prodao": "Dev je već prodao dio",
    "krivulja_postupnost": "Postupan rast, bez jednog skoka",
    "krivulja_male_kupnje": "Bez velikih pojedinačnih kupnji",
    "krivulja_top1": "Najveći holder",
    "krivulja_top10": "Udio top 10 holdera",
    "krivulja_mirna_zadnjih5": "Mirnih zadnjih 5 min prije graduacije",
    "krivulja_malo_holdera": "Malo holdera",
    "krivulja_bundle_umjeren": "Umjeren udio bundlera",
    "krivulja_medijan_kupnje": "Veličina tipične kupnje",
    "krivulja_pad_od_vrha": "Prošao je pad od vrha",
    "krivulja_opis": "Ima opis",
    "krivulja_web": "Ima web stranicu",
    "krivulja_bez_telegrama": "Nema Telegram grupu",
}

# what the features measure (one line, shown next to the name)
FEATURE_DESC = {
    "fresh": "1 za token mlađi od 1 h, pada do 0 na 3 dana",
    "market_regime": "koliko je cijelo tržište bilo vruće jučer (launchpadi + Solana DEX), ista za sve tokene",
    "put_brzina": "koliko brzo je mcap rastao od prve snimke (+100% na sat = puno)",
    "put_skokovitost": "koliki dio rasta je došao u jednom koraku (1 = sve odjednom)",
    "put_zadrzavanje": "koliko je mcap blizu svog vrha (1 = na vrhu)",
    "snaga_volumen": "volumen zadnjeg sata prema najboljem satu u zadnjih 6 h (1 = još na vrhu)",
    "snaga_txn": "transakcije zadnjeg sata prema najboljem satu u 6 h (1 = drži ritam)",
    "rast_holdera": "koliko brzo raste broj holdera (10% na sat = puno)",
    "organski": "dolaze li uz transakcije i novi holderi; lažni volumen vrti transakcije bez novih ljudi",
    "turnover": "volumen zadnjeg sata u odnosu na likvidnost (3x = puno)",
    "buy_pressure": "udio kupnji u zadnjem satu, iznad 50% znači da kupci prevladavaju",
    "momentum": "rast cijene u zadnjem satu (+200% = puno)",
    "activity": "broj transakcija u zadnjem satu (2000 = puno)",
    "paid": "dev je platio profil ili boost na DexScreeneru",
    "socials": "koliko društvenih mreža i web stranica token ima",
    "narrative": "koliko tokena istog imena je nastalo u 3 dana (8 = puno)",
    "calendar": "ime ili simbol pogađa nadolazeći događaj iz kalendara",
    "telegram": "koliko Telegram kanala je objavilo adresu u 6 h (3 = puno)",
    "smart_money": "koliko provjerenih uspješnih walleta je među prvim kupcima (4 = puno)",
    "revival": "token stariji od 3 dana kojem je zadnji sat volumena višestruko iznad prosjeka",
    "takeover": "stari token se budi i ima novi profil ili ga je zajednica preuzela",
    "x_buzz": "koliko različitih ljudi i influencera ga spominje na X-u",
    "kol_wallets": "koliko poznatih KOL walleta ga je trejdalo na pump.fun (5 = puno)",
    "x_trend": "ime ili simbol je trenutno trending tema na X-u",
    "kol_x": "praćeni KOL-ovi su objavili adresu ili $ticker u zadnjih 6 h",
    "kol_group": "više dobrih KOL-ova zove isti token u 30 min; 0 ako devovi prodaju u poziv",
    "konvergencija": "dobri KOL-ovi na X-u, dobri Telegram kanali i KOL novčanici koji kupuju, sve na istom tokenu u 30 min (100 = jako; manje ako KOL već prodaje ili izgleda kao plaćena promocija)",
    "veliki_kupuju": "koliko različitih velikih holdera dugoročnih tokena (Fartcoin, Useless…) ga je kupilo u 14 dana (3 = puno)",
    "pump_live": "token se upravo streama uživo na pump.fun (više gledatelja = više)",
    "search_trend": "Google pretraga imena u zadnja 24 h prema prethodnih 6 dana (3x = puno)",
    "krivulja_starost": "koliko je dugo token na pump.fun krivulji (6 h = puno)",
    "krivulja_bez_mayhema": "token nije pokrenut u mayhem načinu (u studiji lošiji)",
    "krivulja_organski_volumen": "manji udio volumena od trading botova i terminala",
    "krivulja_dev_drzi": "koliko dev još drži (5% ponude = puno)",
    "krivulja_dev_prodao": "koliki dio je dev već prodao",
    "krivulja_postupnost": "rast nije došao u jednom naglom skoku",
    "krivulja_male_kupnje": "malo velikih pojedinačnih kupnji",
    "krivulja_top1": "udio najvećeg holdera (10% = puno)",
    "krivulja_top10": "udio top 10 holdera (50% = puno)",
    "krivulja_mirna_zadnjih5": "malo kupnji u zadnjih 5 min prije graduacije",
    "krivulja_malo_holdera": "malo holdera na krivulji (400+ = 0)",
    "krivulja_bundle_umjeren": "bundleri drže do 20% (iznad 50% = 0)",
    "krivulja_medijan_kupnje": "tipična kupnja (0,2 SOL = puno)",
    "krivulja_pad_od_vrha": "koliko je velik pad od vrha već prošao",
    "krivulja_opis": "token ima opis",
    "krivulja_web": "token ima web stranicu",
    "krivulja_bez_telegrama": "token nema Telegram grupu (u studiji bolji)",
}


def feat_low(k):
    """Feature name inside a sentence: first letter small unless it is an acronym (KOL, CTO)."""
    n = feat(k)
    return n if len(n) > 1 and n[1].isupper() else n[:1].lower() + n[1:]


def feat(k):
    """Human name of a feature key; unknown keys get underscores turned into spaces."""
    return FEATURE.get(k) or str(k).replace("_", " ")


# paper trading decisions (paper.db candidates.decision)
DECISION = {
    "taken": "kupljen",
    "skip_score": "preskočen: preniska ocjena",
    "skip_liq": "preskočen: premala likvidnost",
    "skip_mcap": "preskočen: prevelik mcap",
    "skip_full": "preskočen: dosegnut limit pozicija",
    "skip_rug": "preskočen: rug filter",
    "skip_gate": "preskočen: tvrdi filter protiv rugova",
    "skip_sesija": "preskočen: sesija na pauzi",
    "skip_ab": "preskočen: A/B test ulaza",
    "skip_event": "preskočen: event predaleko",
    "ignored": "zanemaren",
}


def decision(k):
    return DECISION.get(k) or (str(k).replace("skip_", "preskočen: ").replace("_", " ") if k else "–")


# event kinds (event_calendar)
KIND = {
    "game_release": "izlazak igre", "launch": "lansiranje", "media_release": "film / serija / album",
    "viral_now": "viralno sada", "disaster": "katastrofa", "death_anniversary": "godišnjica smrti",
    "birthday": "rođendan", "crypto": "kripto događaj", "holiday": "praznik", "launch_deadline": "rok lansiranja",
    "prediction_market": "oklada na tržištu predviđanja", "manual": "ručno dodan", "election": "izbori",
    "rocket_launch": "lansiranje rakete",
}


def kind(k):
    return KIND.get(k) or str(k or "").replace("_", " ")


# where a hype candidate came from
SOURCE = {
    "profile": "novi DexScreener profil", "profile_update": "ažuriran DexScreener profil", "boost": "DexScreener boost",
    "top_boost": "top boost", "takeover": "preuzimanje zajednice", "pumpfun:trending": "pump.fun trending",
    "pumpfun:graduating": "pump.fun pred graduacijom", "pumpfun:kol": "pump.fun KOL", "telegram": "Telegram kanal", "konv": "konvergencija izvora", "pumpfun:live": "pump.fun uživo",
    "kol": "KOL na X-u", "calendar": "kalendar", "event": "event iz kalendara", "hype": "hype skener",
}


def source(k):
    k = str(k or "").strip()
    if k.startswith("event:"):
        return "event „" + k[6:] + "”"
    if k.startswith("meta:"):
        return "vruća tema " + k[5:].replace("-", " ")
    return SOURCE.get(k) or k.replace("_", " ")


def sources(s):
    return ", ".join(source(x) for x in str(s or "").split(",") if x.strip()) or "–"


# background programs (usage.db script column, logs)
SCRIPT = {
    "run_hype.py": "Hype skener", "run_paper.py": "Demo trading + skener", "run_kol.py": "Praćenje KOL-ova",
    "run_wallets.py": "Registar walleta", "run_watch.py": "Praćenje prije eventa", "run_rug.py": "Rug filter",
    "run_learn.py": "Učenje težina", "run_exits.py": "Učenje izlaza", "run_market.py": "Tržište",
    "run_calendar.py": "Kalendar", "run_dex.py": "DexScreener pretraga", "run_trade.py": "Pravi trading",
    "run_ui.py": "Aplikacija", "run_retro.py": "Retrospektiva", "run_usage.py": "Praćenje potrošnje",
}


def script(k):
    return SCRIPT.get(k) or str(k or "").replace(".py", "").replace("run_", "").replace("_", " ")


# paid-call kinds (Apify sources from hype/apify.json, common Helius methods)
CALL = {
    "pumpfun": "pump.fun trending", "x_buzz": "spominjanja na X-u", "x_trends": "trendovi na X-u",
    "google_trends": "Google Trends", "gmgn": "GMGN walleti", "kol_monitor": "KOL-ovi uživo",
    "kol_search": "traženje novih KOL-ova", "kol_timeline": "objave KOL-ova", "kol_backfill": "povijest KOL-ova",
    "getTransaction": "čitanje transakcije", "getSignaturesForAddress": "popis transakcija",
    "getTokenAccounts": "holderi tokena", "getTokenLargestAccounts": "najveći holderi", "getAsset": "podaci o tokenu",
    "getAccountInfo": "podaci računa", "getBalance": "stanje računa", "getParsedTransactions": "čitanje transakcija",
    "parseTransactions": "čitanje transakcija", "getTokenSupply": "ponuda tokena",
    "getProgramAccounts": "računi programa", "searchAssets": "pretraga tokena", "getAssetsByOwner": "tokeni walleta",
}


def call(k):
    return CALL.get(k) or str(k or "").replace("_", " ")


# databases and tables (Pregled → stanje baza)
DB = {
    "calendar.db": "Kalendar i stari zajednički podaci", "hype.db": "Hype skener", "paper.db": "Demo trading",
    "rug.db": "Rug filter", "wallets.db": "Walleti", "trade.db": "Pravi trading", "usage.db": "Potrošnja",
    "league.db": "Natjecanje", "market.db": "Tržište", "kol.db": "KOL-ovi", "watch.db": "Praćenje prije eventa",
}
TABLE = {
    "event_tokens": "tokeni evenata", "events": "događaji", "helius_credits": "Helius potrošnja (staro)",
    "hype_signals": "hype signali", "hype_snapshots": "snimke tokena", "hype_details": "detalji tokena",
    "smart_wallets": "smart walleti", "tg_mentions": "Telegram objave", "wallet_pnl": "PnL walleta",
    "wallet_sightings": "gdje je wallet viđen", "wallet_trades": "trejdovi walleta", "wallets": "walleti",
    "apify_cache": "spremljeni X podaci", "apify_runs": "Apify pokretanja", "rug_reports": "rug provjere",
    "candidates": "kandidati", "reviews": "dnevni pregledi", "rug_budget": "dnevni budžet rug provjera",
    "ticks": "cijene kroz vrijeme", "trades": "trejdovi", "token_tier": "razine tokena", "token_pulse": "puls tokena",
    "learn_runs": "učenje težina", "usage": "plaćeni pozivi", "account": "očitanja računa", "alerts": "upozorenja",
}


def db(k):
    return DB.get(k) or str(k).replace(".db", "")


def table_name(k):
    return TABLE.get(k) or str(k).replace("_", " ")


# demo trading rules (paper/config.json): name + what it means
CFG = {
    "bankroll_usd": ("Početni demo kapital", "$"), "size_usd": ("Ulog po trejdu", "$"),
    "max_open": ("Najviše otvorenih pozicija", ""), "max_entries_per_day": ("Najviše ulaza dnevno", ""),
    "min_score": ("Najmanja hype ocjena za ulaz", ""), "dex_min_score": ("Najmanja ocjena event tokena za ulaz", ""),
    "event_days": ("Event token se kupuje dana prije eventa", "d"),
    "shadow_min_score": ("Preskočene iznad ove ocjene i dalje pratimo", ""),
    "min_liq": ("Najmanja likvidnost", "$"), "max_mcap": ("Najveći mcap", "$"),
    "fee": ("Trošak po kupnji/prodaji (fee + slippage)", "%"), "rug_check": ("Rug provjera prije ulaza", ""),
    "rug_budget_per_day": ("Rug provjera dnevno", ""), "block_verdicts": ("Rug presude koje blokiraju ulaz", ""),
    "sl": ("Stop loss", "%"), "tp": ("Take profit (rast → koliko prodati)", ""),
    "breakeven_after_tp": ("Nakon prvog TP-a stop na ulaznu cijenu", ""),
    "trail_after": ("Trailing stop se pali nakon rasta", "%"), "trail": ("Trailing stop (pad od vrha)", "%"),
    "max_hold_h": ("Najdulje držanje", "h"), "rug_liq": ("Rug = likvidnost pala ispod", "%"),
    "track_h": ("Koliko dugo pratimo preskočene", "h"),
    "rug_shadow_min_score": ("Rug provjera i za preskočene iznad ocjene", ""),
    "dca": ("Dokup u padu (samo zapis)", ""), "moon_hold_h": ("Moonbag držimo najdulje", "h"),
    "kol_hold_min": ("Nakon KOL poziva držimo barem", "min"),
    "kol_trail_add": ("Nakon KOL poziva trailing stop širi za", "%"),
    "ticks_keep_days": ("Povijest cijena čuvamo", "d"),
    "explore": ("Istraživački ulazi (manji ulog, brže učenje)", ""),
    "konv": ("Ulaz na konvergenciju izvora (X + Telegram + KOL novčanici)", ""),
    "arms": ("Krakovi: više ulaza za kombinacije izvora koje pobjeđuju", ""),
}


def cfg_value(k, v):
    """A config value written the way a trader reads it."""
    unit = CFG.get(k, ("", ""))[1]
    if isinstance(v, bool):
        return "da" if v else "ne"
    if k == "tp" and isinstance(v, list):
        return ", ".join(f"+{a * 100:.0f}% → prodaj {b * 100:.0f}%" for a, b in v)
    if k == "block_verdicts" and isinstance(v, list):
        return ", ".join(v) or "nijedna"
    if k == "explore" and isinstance(v, dict):
        return (f"uključeno: gornjih {v.get('top_pct', 30):g}% ocjena, ulog ${v.get('size_usd', 0):g}"
                if v.get("enabled", True) else "isključeno")
    if k == "konv" and isinstance(v, dict):
        tp = (v.get("tp") or [[0, 0]])[0]
        return (f"uključeno: skor ≥ {v.get('min_score', 0):g}, prvi poziv mlađi od {v.get('max_age_min', 0):g} min, "
                f"prodaj {tp[1] * 100:.0f}% na +{tp[0] * 100:.0f}%, van nakon {v.get('stale_min', 0):g} min bez "
                f"+{v.get('stale_ret', 0) * 100:.0f}%" if v.get("enabled", True) else "isključeno")
    if k == "arms" and isinstance(v, dict):
        return f"krak s {v.get('min_n', 6):g}+ tradeova koji gubi dobiva manje ulaza, nikad manje od {v.get('keep_frac', 0.1) * 100:.0f}%"
    if k == "dca" and isinstance(v, dict):
        return "uključeno" if v.get("enabled") else "isključeno"
    if isinstance(v, (int, float)):
        if unit == "%":
            return f"{v * 100:+.0f}%" if k == "sl" else f"{v * 100:.0f}%"
        if unit == "$":
            return f"${v:,.0f}"
        return f"{v:g}{(' ' + unit) if unit else ''}"
    return str(v)


def cfg_name(k):
    return CFG.get(k, (str(k).replace("_", " "), ""))[0]


def cfg_change(ch):
    """{'min_score': 55, 'sl': -0.3} -> 'Najmanja hype ocjena za ulaz 55, Stop loss -30%'"""
    return ", ".join(f"{cfg_name(k)} {cfg_value(k, v)}" for k, v in (ch or {}).items())


_CODE = re.compile(r"`[^`]*`|<code>.*?</code>")
_DEV = re.compile(r"\brun_\w+|[\w/.-]+\.(py|json|db|md|txt|log)\b|\b[A-Z][A-Z0-9]*_[A-Z0-9_]{2,}\b|\s--[a-z]")
_FEAT = re.compile(r"\b(" + "|".join(sorted(map(re.escape, FEATURE), key=len, reverse=True)) + r")\b")


# phrases of daily reviews written before 2026-10-31 that asked for a manual step
LEGACY = [
    (r"Ne kupuj u padu po ovim pravilima;.*?isključi\.", "Kupnja u padu se po ovim pravilima ne isplati; bot je zato samo bilježi, ne izvršava."),
    (r"Vrijedi ga slijediti \(ručno ili automatski\)\.", "Bot ga i dalje samo bilježi; vrijedi ga uključiti u demo."),
    (r"Pogledaj pravila ispod \(lažni alarmi\) i olabavi najčešće\.", "Najčešći lažni alarmi su popisani u izvještaju."),
    (r"\bPrag ulaza\b", "Najmanja ocjena za ulaz"), (r"Minimalna likvidnost", "Najmanja likvidnost"),
    (r"\bBlokiraj i '([^']+)'", r"Ne kupovati ni tokene s rug presudom „\1”"),
    (r"\s->\s", " → "), (r"\bPnL\b(?= [+-]\d)", "demo rezultat"),
]


def plain(text):
    """Old stored texts (daily reviews, notes) may still carry commands and file names: drop those sentences and
    turn feature keys into their names. New texts are written plain at the source."""
    text = str(text or "")
    for a, b in LEGACY:
        text = re.sub(a, b, text)
    t = _CODE.sub(lambda m: "" if _DEV.search(m.group(0)) or "." in m.group(0) else m.group(0).strip("`"), str(text or ""))
    t = re.sub(r"\(\s*[,;]?\s*\)|,\s*\)", lambda m: "" if m.group(0).startswith("(") else ")", t)
    keep = [x for x in re.split(r"(?<=[.!?])\s+", t) if x.strip() and not _DEV.search(x)]
    t = " ".join(keep)
    t = _FEAT.sub(lambda m: feat_low(m.group(1)), t)
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([.,;:)])", r"\1", t)).strip(" ;")


EXIT_REASON = {"stop_loss": "stop loss", "trailing": "trailing stop", "breakeven": "na ulaznoj cijeni nakon prvog TP-a",
               "time": "isteklo vrijeme", "rug": "rug (likvidnost nestala)", "open": "otvoreno",
               "stale": "nema rasta (mirovanje)", "moonbag_trailing": "moonbag: trailing od vrha",
               "moonbag_time": "moonbag: isteklo vrijeme", "take_profit": "take profit", "manual": "ručno",
               "auto": "automatska prodaja"}


def exit_reason(k):
    return EXIT_REASON.get(k) or str(k or "–").replace("_", " ")


def reason(t):
    """Decision reason as stored by the paper loop ("score 74 < 75") in words."""
    t = str(t or "")
    t = re.sub(r"\bscore (\d+(?:\.\d+)?) < (\d+)", r"ocjena \1, za ulaz treba \2", t)
    t = re.sub(r"\bscore (\d+(?:\.\d+)?)", r"ocjena \1", t)
    return t


EVENT_SOURCE = {"manual": "ručno dodan", "polymarket": "Polymarket", "rocketlaunch.live": "RocketLaunch",
                "wikipedia_mostread": "Wikipedia (najčitanije)", "wikipedia": "Wikipedia", "news": "vijesti"}


def event_source(k):
    return EVENT_SOURCE.get(k) or str(k or "–")


def report_name(rel, syms=None):
    """output/ path -> what the report is, e.g. 'paper/review-2026-10-31.md' -> 'Dnevni pregled demo tradinga 31.10.2026.'"""
    base = rel.rsplit("/", 1)[-1]
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", base)
    d = f" {m.group(3)}.{m.group(2)}.{m.group(1)}." if m else ""
    if rel.startswith("rug/"):
        mint = base.rsplit(".", 1)[0]
        return f"Rug provjera: {(syms or {}).get(mint) or mint[:6] + '…'}"
    for pre, name in (("review-", "Dnevni pregled demo tradinga"), ("calendar-", "Kalendar događaja"),
                      ("dex-", "Tokeni za evente (DexScreener)"), ("rug-", "Rug provjere"),
                      ("wallets-copy-", "Copy lista walleta"), ("watch-", "Praćenje prije eventa"),
                      ("radar-", "Zadnji sken"), ("lessons", "Što je bot naučio, dan po dan"),
                      ("jutarnji-izvjestaj-", "Jutarnji izvještaj"), ("retro", "Retrospektiva")):
        if base.startswith(pre):
            return name + d
    return base.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").capitalize() + d


def plain_md(txt):
    """A stored markdown report for reading: markdown marks stay (they read fine), commands and file names go.
    Headings and table rows lose just the technical bit; in prose the whole sentence with it goes."""
    out = []
    for line in str(txt or "").splitlines():
        if _DEV.search(line):
            if line.lstrip().startswith(("#", "|")):
                line = re.sub(r"\s*\(?[^()|]*\b[\w/.-]+\.(py|json|db|md|txt|log)\b[^()|]*\)?", "", line)
                line = _CODE.sub("", line)
            else:
                lead = re.match(r"^\s*([-*>]+\s*|\d+\.\s*)", line)
                cleaned = plain(line[lead.end():] if lead else line)
                if not cleaned.strip() or cleaned.rstrip().endswith(":"):
                    continue
                line = (lead.group(0) if lead else "") + cleaned
        line = re.sub(r"\blift\b", "puta češće", line)
        out.append(_FEAT.sub(lambda m: feat_low(m.group(1)), line))
    return "\n".join(out)


def profile(name):
    """Exit rule set a trade uses ("moonshot/us@3", "paper/config.json") in words."""
    n = str(name or "")
    if not n or n.endswith(".json"):
        return "osnovna pravila"
    m = re.match(r"([a-z]+)(?:/([a-z]+))?@(\d+)", n)
    if not m:
        return n
    kl = {"moonshot": "Moonshot", "rizican": "Rizičan", "event": "Event", "stabilni": "Stabilni", "default": "svi tokeni"}
    ss = {"asia": "Azija", "eu": "Europa", "us": "SAD"}
    return f"naučena pravila: {kl.get(m.group(1), m.group(1))}" + (f", {ss.get(m.group(2), m.group(2))} sesija" if m.group(2) else "") \
        + f" (verzija {m.group(3)})"


WALLET_LABEL = {"bot": "bot", "rugger": "ruger", "bundler": "bundler", "insider": "insajder", "dev": "dev", "cex": "burza",
                "mev": "MEV bot", "sniper": "snajper", "funder_of_rugger": "financirao rugera", "smart": "smart money",
                "kol": "KOL", "fresh": "novi wallet"}


def wallet_label(k):
    return WALLET_LABEL.get(k) or str(k).replace("_", " ")
