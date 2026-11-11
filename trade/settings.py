"""Settings of the real-money trader that the owner changes on the page /pravi-trade, kept in trade.db (on the
persistent disk, so a redeploy keeps them). trade/config.json holds the defaults.

Who may change them: TRADE_OWNER (Render env, default "Jure", Nicholas's account). Other players see the page only
when the owner invites them, and only to look.
"""
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADE_DB", os.path.join(HERE, "trade.db"))
LEAGUE_USER = "pravi-trade"   # the competition account whose follows (KOL/wallet) drive the real trades
# 10.11. (Jure: "default stop loss treba biti na minus 60 %, a to moram na stranici Autopilota moći promijeniti"): the
# stop of every Autopilot entry with "moj TP/SL" and no stop of its own (copies, auto picks, crews, manual buys), in
# percent below the entry; the owner picks one of SL_CHOICES under "Pravila". Players keep league/copy.DEFAULT_SL.
SL_DEFAULT = 60
SL_CHOICES = (20, 30, 40, 50, 60, 70)

# 10.11. (Jure, "Specifikacija za Claudea", Phase 0): every new rule of the profitability plan ships behind a flag.
#   off     the rule does nothing (default; behaviour exactly as before)
#   shadow  the new decision is computed and logged (league.db shadow_decisions), nothing changes
#   paper   the new rule runs on the demo account PAPER_USER, which copies LEAGUE_USER's follows; run_trade.py never
#           mirrors PAPER_USER, so no real money moves
#   live    the rule runs on LEAGUE_USER (real money through run_trade). Allowed only with a passed backtest
#           (settings "backtest:<flag>" = {"pass": true, ...} from run_backtest.py) after PAPER_DAYS in paper with
#           the paper account in the plus (live_refusal)
# Data flags (DATA_FLAGS) only switch a collector or an MCP inbox on: any mode but off means "on".
PAPER_USER = "autopilot-paper"
FLAG_MODES = ("off", "shadow", "paper", "live")
PAPER_DAYS = 7
FLAGS = {   # name -> (item of the plan, what it does, in Croatian for the page)
    "auto_exit_data": ("1.1", "Auto praćenja influencera izlaze po podacima (kol/tpsl), rok 60 min"),
    "sl_default_v2": ("1.2", "Zadani stop −25 % i izlaz nakon 1 h"),
    "dca_guard": ("1.4", "DCA dokup samo bez dumpa i prodaje insajdera; stop ostaje na prvom ulazu"),
    "caller_ev_rank": ("2.1", "Calleri po donjoj granici EV-a, samo iz poziva prije signala"),
    "latency_entry": ("2.2", "Mjerenje ulaza s pravim kašnjenjem"),
    "runup_default": ("2.3", "Preskok kad je cijena više od 10 % iznad prvog poziva"),
    "holder_hard": ("2.4", "Bez podataka o holderima nema auto kupnje; blok na prodaju deva i insajdera"),
    "proof_v2": ("2.5", "Pravi novac tek nakon 25 zatvorenih i donje granice EV-a iznad nule"),
    "survivor_fix": ("2.6", "Poziv bez para ili svijeće broji se kao gubitak, ne ispada"),
    "zombie_guard": ("2.7", "Zombie token (više od 7 dana na krivulji prije migracije): manji ulog ili preskok, "
                            "bez kasnog ulaza i DCA-a"),
    "organic_volume": ("2.8", "Volumen bez weba, socijala i praćenog callera nije organski: jedinstveni kupci i "
                              "udio sitnih tradeova"),
    "xhook_fast": ("3.1", "Brži X webhook za 15 najboljih callera (plaćeno)"),
    "helius_streams": ("3.2", "Helius streamovi za walletove i devove (plaćeno)"),
    "holder_snap": ("3.3", "Snimka holdera u trenutku signala"),
    "clusters_ext": ("3.4", "Klasteri holdera i povlačenje likvidnosti"),
    "x_features_ingest": ("3.6", "X značajke od Groka (MCP upis)"),
    "junk_skip": ("3b.1", "Meko preskakanje smeća (računi, kanali, walleti, tokeni)"),
    "junk_flags": ("3b.2", "Oznake smeća od Groka na pregled"),
    "event_flags": ("3c", "Rane oznake događaja i Polymarketa od Groka"),
    "grok_predictions": ("3d", "Grok predviđanja (nepromjenjiva) za usporedbu s MemeSonarom"),
    "grok_features_fit": ("3d.4", "Grok značajke kao kandidati u učenju"),
    "regime_sizing": ("4.1", "Ulog i broj ulaza prema režimu tržišta"),
    "time_filter": ("4.2", "Bez ulaza u satima s negativnim EV-om"),
    "caller_decay": ("4.3", "Novija forma callera vrijedi više (poluživot 14 dana)"),
    "ladder_exit": ("4.4", "Izlaz u koracima: pola na +30 %, stop na ulaz, trailing 25 %"),
    # 10.11. (addendum, Phase 3e)
    "early_score": ("3e.1", "Rana ocjena tokena iz PumpPortal streama (0-100)"),
    "early_persist": ("3e.2", "Rani tokovi tradeova spremljeni dulje od 48 h"),
    "smart_discovery": ("3e.3", "Otkrivanje novčanika koji rano ulaze u pobjednike"),
    "wallet_stream": ("3e.4", "Novčanici u stvarnom vremenu (Helius WebSocket)"),
    "sender_exec": ("3e.4", "Slanje swapa preko Helius Sendera (napojnica)"),
    "demo_grok": ("3e.5", "Demo strategije MemeSonar, Grok i oboje zajedno"),
    # 10.11. (Grok MCP audit 4): a proven caller's copy is not stopped out in the first minutes (league/auto.grace)
    "stop_grace": ("G4", "Prve 3 min bez stopa za dokazane callere (osim kod ruga)"),
    # 10.11. (Jure: "Primijeni" na Grokov prijedlog mijenja ove postavke, svaku iza zastavice, prvo sjena)
    "caller_weights": ("G6", "Težine callera iz prijedloga u automatskom izboru influencera"),
    "dca_cap": ("G7", "Najviše SOL-a ukupno po tokenu (zadano 0,3)"),
    "require_signal": ("G8", "Bez ulaza bez signala: barem jedan caller ili kupnja novčanika s tierom"),
    # 10.11. ~21:00 (Grok, "Prihvaćeno, ali nije primijenjeno", Jure: "Primijeni ovo"): TP +10 % / stop -20 % pays only
    # at ~73 % hits and the best callers have 50-60 %, so an entry needs 2+ callers AND a tiered wallet's buy
    "confluence": ("G9", "Ulaz tek kad se poklope 2+ callera i kupnja novčanika s tierom"),
    # 10.11. ~21:45 (Jure): the MCP client's exit plan per position, executed by the server (league/exitplan.py)
    "exit_plans": ("G10", "Planovi izlaza s MCP-a (set_exit_plan): TP-ovi, trailing, stop, time stop"),
    # 10.11. (Jure: skener tržišta bez callera, scan/): never buys; shadow = measured per source, paper only through
    # paper_refusal (>= 30 shadow outcomes and EV > 0 of the scanner's own sources)
    "market_scan": ("G11", "Skener tržišta bez callera (final stretch, migrirani, beta mete, rani X), mjeri u sjeni"),
    # 10.11. (Jure, kol/groupdisc.py): caller crews and hidden wallet lists; in paper only past PAPER_GATES
    "group_discovery": ("G12", "Ekipe callera i skriveni popisi novčanika: ekipa unutar 10 min = jedan signal, "
                               "ekipa izlazne likvidnosti negativno"),
    # 10.11. (Jure, range_dca): range + DCA on bonded tokens (rangedca/); live only after >= 20 paper rounds, EV > 0
    "range_dca": ("G13", "Raspon + DCA: ulaz na dnu raspona, lot 2 na -10 do -15 %, pola van u gornjoj zoni"),
    # 10.11. (Jure, kol/precall.py): wallets that buy before the callers' calls; copied only in paper, live only past
    # live_refusal + LIVE_GATES
    "insider_copy": ("G14", "Insajderi prije poziva: novčanici koji kupuju prije poziva callera, kopiranje u demo"),
    # 11.11. (Jure, kol/preshill.py): wallets that buy before the paid shill network calls; shadow only, never buys
    "pre_shill": ("G15", "Kupci prije shill mreže: novčanici koji kupe prije plaćene mreže callera, poziv mreže je "
                         "znak za izlaz"),
    # 11.11. (Jure, momentum/): the +20-30 % jumps without callers; paper on the demo account, live only past
    # LIVE_GATES (>= 50 paper trades, EV > 0, hit rate >= 45 %)
    "momentum_scalp": ("G16", "Momentum scalp: ulaz na početku skoka (+5 do +15 % u 5 min, volumen 3x, kupci rastu), "
                              "pola van na +15 %, ostatak trailing 8 %, stop -10 %, 45 min"),
    # 11.11. (Jure, momentum/evgate.py): Grok's autotrade buy only with EV = p x TP - (1 - p) x SL - cost > 0
    "grok_ev_gate": ("G17", "Grokova vrata po EV-u: kupnja samo kad je p(TP prije SL-a) x TP - (1 - p) x SL - trošak "
                            "iznad nule"),
    # 11.11. (Jure: GTA's plan was only logged, the real exit went through the default TP): an owner switch, uživo =
    # Grok's exit plans run on the REAL account for Grok autotrade positions (league/exitplan.grok_live), whatever
    # exit_plans' mode; it only sells, never buys; default off, only the owner moves it
    "exit_plan_live": ("G18", "Grokovi planovi izlaza na pravom računu za Grok autotrade pozicije (samo prodaja)"),
    # 11.11. (Jure: "event tokeni s Grokom", topics/): Grok's event topics, their matching tokens (main / clone / rug),
    # the price 24 h before / at / after the event; shadow = measure only, paper = range_dca may trade them on the demo
    # account; never real money (NEVER_LIVE)
    "event_tokens": ("G19", "Event tokeni: teme događaja od Groka (npr. GTA6), tokeni koji im odgovaraju (glavni, klon, "
                            "rug) i cijena 24 h prije, u trenutku i 24 h nakon događaja"),
    # 11.11. (Jure: "širi range watchlist", rangedca/market.py): up to 400 bonded tokens of the whole market in the range
    # watchlist (5 / 15-min DexScreener snapshots inside daily caps); shadow = data, paper = range_dca may trade them on
    # the demo account; never real money (NEVER_LIVE)
    "range_market": ("G20", "Range lista cijelog tržišta: do 400 bondanih tokena (MC 50k-5M, likvidnost 20k+, volumen "
                            "1 h 10k+, stariji od 6 h), snimke svakih 5/15 min unutar dnevnih stropova"),
    # 11.11. (Jure, proposals/): one list of proposals from every strategy on the Autopilot card and in get_proposals;
    # shadow = list and measure, paper = the demo account takes every shown proposal; never live (LIVE_GATES)
    "proposals": ("G21", "Prijedlozi svih strategija na Autopilotu: sjena = popis i mjerenje, paper = demo račun uzima "
                         "svaki prikazani prijedlog s planom izlaza; pravi račun kupuje samo na tvoj dodir"),
}
# 11.11.: flags that never go live, whatever the proofs say (their tokens are traded at most on the demo account)
NEVER_LIVE = {"event_tokens": "event tokeni nikad ne trguju pravim novcem (najviše paper na demo računu)",
              "range_market": "tržišna range lista nikad ne trguje pravim novcem (najviše paper na demo računu)"}
# 11.11.: owner switches: "live" means on, without a backtest or paper days (live_refusal lets them through); they
# never move on their own, only the owner's tap on the page sets them
OWNER_SWITCHES = frozenset({"exit_plan_live"})
# 10.11. (group_discovery): flags whose move to paper needs a proof of their own, "module:function"(con, now=) -> None
# or the reason in Croatian. Asked only by set_flag (the owner's tap), so it is enforced and never automatic.
PAPER_GATES = {"group_discovery": "kol.groupdisc:paper_refusal"}
PAPER_GATES["pre_shill"] = "kol.preshill:paper_refusal"   # 11.11.: 7 days of shadow, >= 30 measured signals, EV > 0
# 10.11. (insider_copy): flags whose move to live needs a proof of their own on top of live_refusal's (same shape)
LIVE_GATES = {"insider_copy": "kol.precall:live_refusal",
              "momentum_scalp": "momentum.gate:live_refusal"}   # 11.11.: >= 50 paper trades, EV > 0, hit >= 45 %
LIVE_GATES["proposals"] = "proposals.paper:live_refusal"   # 11.11.: never live (no automatic path to the real account)
DCA_TOKEN_CAP = 0.3   # SOL in one token at most under dca_cap, until the owner applies another (settings "dca_token_cap")
DATA_FLAGS = frozenset({"holder_snap", "x_features_ingest", "junk_flags", "event_flags", "grok_predictions",
                        "early_persist"})
_FLAG_CACHE = {}       # db path -> (monotonic read time, {name: mode})
FLAG_CACHE_S = 2.0     # loops ask every second; a change on the page holds within this

# key -> (label, type, min, max); the owner edits these on the page
LIMITS = {
    "size_sol": ("Ulog po kupnji (SOL)", float, 0.005, 5.0),
    "max_sol_per_day": ("Najviše potrošeno na automatske kupnje u danu (SOL)", float, 0.01, 50.0),
    "max_loss_day": ("Najveći gubitak u danu, onda stop (SOL)", float, 0.01, 50.0),
    "max_open": ("Najviše otvorenih pozicija", int, 1, 50),
    "min_sol_reserve": ("Uvijek ostavi u walletu (SOL)", float, 0.01, 10.0),
    "max_cost_pct": ("Najveći trošak swapa (%)", float, 0.5, 20.0),
}

# Audit 4.11. §14.4/§22: switches that stay off whatever is saved, until the proof the audit asks for exists.
# The page shows them greyed out with this reason; run_trade and the SimianX job read the effective value.
LOCKED = {
    "follow_paper": "zaključano: demo strategija smije u pravi novac tek kad dobije status „kandidat” "
                    "(bije kontrolu nakon troška, na obje polovice, i bez 5 najboljih trejdova)",
    "simianx": "zaključano: SimianX signali nemaju isti dokaz kao praćeni influenceri i novčanici "
               "(odgođena kopija koja bije kontrolu), pa ne idu u pravi novac",
}

SCHEMA = "CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT, ts INTEGER, who TEXT)"


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.execute(SCHEMA)
    return con


def owner():
    return (os.environ.get("TRADE_OWNER") or "Jure").strip().lower()


def is_owner(user):
    return bool(user) and user.lower() == owner()


def raw(con):
    return {k: json.loads(v) for k, v in con.execute("SELECT k, v FROM settings")}


def put(con, key, value, who=""):
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)", (key, json.dumps(value), int(time.time()), who))
    con.commit()


def merged(cfg, con):
    """config.json defaults + what the owner set on the page. The switch ("on") lives only here: off by default."""
    s = raw(con)
    out = dict(cfg)
    for k in LIMITS:
        if k in s:
            out[k] = s[k]
    out["max_sol_per_trade"] = max(out.get("max_sol_per_trade", 0), out["size_sol"])
    out["on"] = bool(s.get("on", False))
    out["follow_paper"] = bool(s.get("follow_paper", False)) and "follow_paper" not in LOCKED
    out["use_pump"] = bool(s.get("use_pump", True))
    out["simianx"] = bool(s.get("simianx", False)) and "simianx" not in LOCKED
    out["dca_cap_owner"] = bool(s.get("dca_cap_owner", False))     # 10.11. ~21:00: the owner's per-token SOL cap
    out["dca_token_cap"] = s.get("dca_token_cap", DCA_TOKEN_CAP)
    out.setdefault("day_tz", "Europe/Zagreb")
    out["sell_all"] = s.get("sell_all") or 0
    out["sell_req"] = s.get("sell_req") or {}
    out["manual_size"] = s.get("manual_size") or {}
    out["heartbeat"] = s.get("heartbeat") or 0
    out["tp_default"] = int(s.get("tp_default") or 15)   # 9.11. (Jure): the exit target for new copies, set at the top of the page
    out["sl_default"] = int(s.get("sl_default") or SL_DEFAULT)
    out["last_exit"] = s.get("last_exit") or {}   # 10.11. (Jure): the TP / SL the owner used last, for the next order
    out["buy_orders"] = s.get("buy_orders") or []   # 10.11. (Jure): buy orders at a market cap (ui/pravitrade.limit_once)
    out["buy_log"] = s.get("buy_log") or []
    return out


def sl_text(pct):
    """60 -> "-60%": the stop as a level league/auto.parse_level reads."""
    return f"-{int(pct)}%"


def sl_default(path=None):
    """The Autopilot's default stop as a level ("-60%"), read-only from trade.db (league/copy asks it at every
    entry, in another process than the page). SL_DEFAULT when the database or the key is not there."""
    path = path or DB
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT v FROM settings WHERE k='sl_default'").fetchone()
        finally:
            con.close()
        v = int(json.loads(row[0])) if row else SL_DEFAULT
    except (sqlite3.Error, ValueError, TypeError):
        v = SL_DEFAULT
    return sl_text(v if v in SL_CHOICES else SL_DEFAULT)


def _flag_value(v):
    """Stored flag value -> {"mode", "since", "who"} (a bare string from a hand edit counts too)."""
    if isinstance(v, str):
        v = {"mode": v}
    v = v if isinstance(v, dict) else {}
    mode = v.get("mode") if v.get("mode") in FLAG_MODES else "off"
    return {"mode": mode, "since": int(v.get("since") or 0), "who": v.get("who") or ""}


def flag_state(con):
    """{name: {"mode", "since", "who"}} of every flag in FLAGS ("off" when never set)."""
    s = raw(con)
    return {n: _flag_value(s.get(f"flag:{n}")) for n in FLAGS}


def _flags_ro(path):
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT k, v FROM settings WHERE k LIKE 'flag:%'").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    out = {}
    for k, v in rows:
        try:
            out[k[5:]] = _flag_value(json.loads(v))["mode"]
        except (ValueError, TypeError):
            continue
    return out


def flag(name, con=None, path=None):
    """The mode of one flag: "off" | "shadow" | "paper" | "live". With con: read now; without: read-only from
    trade.db, cached FLAG_CACHE_S per process (the copy and exit loops ask every pass). Never raises: a flag that
    cannot be read is "off", i.e. the old behaviour."""
    if name not in FLAGS:
        raise KeyError(f"nepoznata zastavica {name}")
    if con is not None:
        try:
            return _flag_value(raw(con).get(f"flag:{name}"))["mode"]
        except (sqlite3.Error, ValueError, TypeError):
            return "off"
    path = path or DB
    now = time.monotonic()
    hit = _FLAG_CACHE.get(path)
    if hit is None or now - hit[0] > FLAG_CACHE_S:
        hit = (now, _flags_ro(path))
        _FLAG_CACHE[path] = hit
    return hit[1].get(name, "off")


def flag_on(name, con=None, path=None):
    """A data flag (DATA_FLAGS) collects or accepts input in every mode but off."""
    return flag(name, con, path) != "off"


def any_paper(con=None, path=None):
    """True while at least one flag is in paper mode (only then the paper account follows anybody)."""
    if con is not None:
        return any(v["mode"] == "paper" for v in flag_state(con).values())
    return any(flag(n, path=path) == "paper" for n in FLAGS)


def live_refusal(con, name, paper=None, now=None):
    """None when `name` may go live, else the reason in Croatian. paper: {"n": closed trades, "pnl": USD} of the
    paper account since the flag went to paper (league/flags.paper_result); None = not known."""
    now = int(now or time.time())
    if name in NEVER_LIVE:
        return NEVER_LIVE[name]
    if name in DATA_FLAGS or name in OWNER_SWITCHES:
        return None
    bt = raw(con).get(f"backtest:{name}") or {}
    if not (isinstance(bt, dict) and bt.get("pass") is True):
        return f"nema prolaza backtesta (python3 run_backtest.py --flag {name})"
    st = flag_state(con)[name]
    if st["mode"] == "live":
        return None
    if name == "range_dca":   # 10.11. (Jure): >= 20 closed paper rounds with EV > 0 (rangedca/gate.py), on top
        try:
            from rangedca import gate as _range_gate
            why = _range_gate.refusal(now=now)
        except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
            why = f"dokaz range_dca nije čitljiv ({type(e).__name__})"
        if why:
            return why
    if st["mode"] != "paper" or not st["since"]:
        return f"prvo najmanje {PAPER_DAYS} dana u paper modu"
    days = (now - st["since"]) / 86400
    if days < PAPER_DAYS:
        return f"u paper modu tek {days:.1f} od {PAPER_DAYS} dana"
    if not paper or not paper.get("n"):
        return "paper račun još nema nijedan zatvoren trade"
    if (paper.get("pnl") or 0) <= 0:
        return f"paper račun je u minusu ({paper['pnl']:+.2f} $ na {paper['n']} tradeova)"
    spec = LIVE_GATES.get(name)
    if spec:   # 10.11.: e.g. insider_copy also needs >= 20 closed paper copies of its own with EV > 0
        try:
            import importlib
            mod, fn = spec.split(":")
            return getattr(importlib.import_module(mod), fn)(con, now=now)
        except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
            return f"dokaz za live se ne može pročitati ({type(e).__name__})"
    return None


def paper_refusal(con, name, now=None):
    """None when `name` may go from off / shadow to paper, else the reason in Croatian. Most flags may (paper moves
    no real money); market_scan only with its sources' measured proof (scan/shadow.flag_paper_refusal: >= 30 finished
    shadow outcomes and EV > 0); the flags in PAPER_GATES through their own proof (e.g. group_discovery). A proof that
    cannot be read refuses. Nothing calls set_flag on its own."""
    if name == "market_scan":
        try:
            from scan import shadow
            return shadow.flag_paper_refusal(now=now)
        except Exception as e:  # noqa: BLE001 - no proof readable: no paper
            return f"dokaz iz sjene nije čitljiv ({type(e).__name__})"
    spec = PAPER_GATES.get(name)
    if not spec:
        return None
    try:
        import importlib
        mod, fn = spec.split(":")
        return getattr(importlib.import_module(mod), fn)(con, now=now)
    except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
        return f"dokaz se ne može pročitati ({type(e).__name__})"


def set_flag(con, name, mode, who="", paper=None, now=None):
    """Owner's change of one flag (the page checks is_owner). Raises ValueError with the reason when refused.
    Going down (to off or shadow) is always allowed, and to paper from live; up to paper only past paper_refusal;
    "since" restarts on every change of mode."""
    if name not in FLAGS:
        raise ValueError("nepoznata zastavica")
    if mode not in FLAG_MODES:
        raise ValueError("nepoznat mod (off, shadow, paper, live)")
    now = int(now or time.time())
    cur = flag_state(con)[name]
    if mode == cur["mode"]:
        return cur
    if mode == "live":
        why = live_refusal(con, name, paper, now)
        if why:
            raise ValueError(f"{name} ne može u live: {why}")
    if mode == "paper" and cur["mode"] in ("off", "shadow"):
        why = paper_refusal(con, name, now)
        if why:
            raise ValueError(f"{name} ne može u paper: {why}")
    val = {"mode": mode, "since": now, "who": who}
    put(con, f"flag:{name}", val, who)
    _FLAG_CACHE.clear()
    return val


def parse_limits(form):
    """Form -> {key: value}; raises ValueError with a Croatian message on a bad number."""
    out = {}
    for k, (label, typ, lo, hi) in LIMITS.items():
        txt = (form.get(k) or "").strip().replace(",", ".")
        if not txt:
            continue
        try:
            v = typ(float(txt))
        except ValueError:
            raise ValueError(f"{label}: upiši broj")
        if not lo <= v <= hi:
            raise ValueError(f"{label}: mora biti između {lo:g} i {hi:g}")
        out[k] = v
    return out


def invited(con):
    return [u for u in raw(con).get("invited", []) if u]


def can_view(con, user):
    return is_owner(user) or bool(user) and user.lower() in {u.lower() for u in invited(con)}


def simianx_on(con=None):
    """The owner's approval for SimianX long signals on the real-trade account (off by default). The SimianX job
    opens its demo trades on LEAGUE_USER only while this is on (league.store.buy + auto.set_auto with its stop and
    target); run_trade.py then mirrors them like any copy trade, inside the same limits."""
    own = con is None
    con = con or connect()
    try:
        return bool(raw(con).get("simianx", False)) and "simianx" not in LOCKED
    finally:
        if own:
            con.close()
