"""Copy trading for the competition: a player follows a KOL (enters on their next call) or a wallet (mirrors its buys
and sells) and the tool trades that player's own demo account for them.

Runs every minute inside the auto sell thread of the dashboard process (league.db's only writer). It only reads
data the bot already collects, so it costs no extra API credits:
- KOL calls: kol.db calls (kind 'call'), hype.db kol_mentions (live X webhook, seconds), tg.db posts (Telegram).
- Wallets: hype.db chain_trades (Helius webhook on the KOL wallets, buys and sells within seconds).
Prices: one DexScreener request for the new tokens of the minute (free, the same as the rest of the page).

A call or buy is entered only while it is fresh (max_delay_min): entering a pump 40 minutes late is not copying.
Every decision (entered, skipped and why, sold) goes to the copy_log table, so the page can show what happened.
"""
import json
import os
import sqlite3
import time

from . import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOL = "So11111111111111111111111111111111111111112"
STABLE = {SOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}

CFG = {"max_delay_min": 10,      # call/buy older than this when we see it: not entered
       "price_wait_min": 5,      # a brand-new token often has no DexScreener pair for a few minutes
       "sell_lookback_min": 120,  # a wallet sale is retried this long when there is no price
       "min_liq": 5000, "max_mcap": 50e6, "min_size": 5, "max_size": 500, "max_per_day": 50,
       "keep_log_days": 30,
       "crew_window_min": 30,     # ekipa: members' calls on one token within this window count together
       # 9.11. (audit, CLAUDE.md): tokens under $30k are never bought automatically; a pool thinner than 3 % of the
       # market cap cannot absorb one big holder selling, so the -20 % stop would never fill (P1/P5/P7, P41)
       "min_mcap": 30_000, "min_liq_mcap": 0.03}
DEFAULT_SL = "-20%"   # 9.11. (audit): every TP/SL copy without an explicit stop gets this one (kol/minute.py SL)
# 10.11. (Jure: zadani stop Autopilota −60 %, mijenja se na stranici): the Autopilot account's follows keep their stop
# empty when none was typed and get trade.settings.sl_default() at the entry (default_sl); the players keep DEFAULT_SL
DAY_TZ = "Europe/Zagreb"   # 9.11. (audit P58/P62): the per_day counter uses the same day as trade/executor.DAY_TZ

SCHEMA = """
CREATE TABLE IF NOT EXISTS follows (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, kind TEXT, target TEXT, label TEXT, size_usd REAL,
    per_day INTEGER, exit TEXT, created INTEGER, active INTEGER DEFAULT 1, stopped INTEGER);
CREATE INDEX IF NOT EXISTS follows_active ON follows (active);
CREATE TABLE IF NOT EXISTS copy_log (
    follow_id INTEGER, token TEXT, side TEXT, ev_ts INTEGER, ts INTEGER, symbol TEXT, action TEXT, note TEXT,
    trade_id INTEGER, PRIMARY KEY (follow_id, token, side));
CREATE INDEX IF NOT EXISTS copy_log_ts ON copy_log (ts);
"""

# 10.11. (Jure: dnevnik Autopilota, čita se svake sekunde dok je otvoren): trade/aplog.py takes each follow's newest
# skips and entries straight from (follow_id, action, ts), one action at a time, and the account's follows from
# (user, active), instead of walking copy_log. With the action in the key a wallet follow's many "info" rows (every
# sale of a coin we never copied) are never walked past. _today() counts a follow's entries through it as well.
# Outside SCHEMA and guarded in ensure(): building an index writes, and a full disk must not stop the copy loop.
INDEXES = ("CREATE INDEX IF NOT EXISTS copy_log_follow_action ON copy_log (follow_id, action, ts)",
           "CREATE INDEX IF NOT EXISTS follows_user ON follows (user, active)")

KIND_HR = {"kol": "KOL", "wallet": "wallet", "ekipa": "ekipa"}
EXIT_HR = {"smart": "Smart sell", "tpsl": "moj TP/SL", "manual": "prodajem sam", "mirror": "prodaj kad on proda",
           "mirror_smart": "prodaj kad on proda + Smart sell",
           # 9.11. (Jure: "neka alat dinamički odluči kad može biti profitabilno"): kol/tpsl.py picks TP/SL from the
           # account's (crew's) measured calls at every entry and skips the entry when no pair is in the plus
           "podaci": "TP/SL po podacima (alat bira, ne ulazi kad se ne isplati)"}
DATA_TP = "15%"   # exit of a "podaci" follow while the account has too few measured calls to decide (with DEFAULT_SL)
DATA_HOLD_S = 3600   # a data exit is known for the measured hour after the call (kol/tpsl.HOLD_MIN): closed after it
# 10.11. (review): kol/minute.py measures an entry at the close of the minute the call was posted in. A copy that
# enters minutes later, or after the price already ran, is a different trade than the one the pair was chosen on, so
# a "podaci" follow enters only this soon after the call and only while the price has not already moved this much.
DATA_MAX_LATE_S = 120
DATA_MAX_RUNUP = 0.10


WAKE = os.path.join(os.environ.get("DATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".copy_wake")


def wake():
    """9.11. (Jure: every second is money): a followed wallet's swap or a KOL post just arrived (Helius webhook,
    PumpPortal feed, X webhook). The auto-sell loop in the dashboard sees the file and runs copy.run_once at once
    instead of at its next 20-second tick."""
    try:
        with open(WAKE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def woke_since(ts):
    try:
        return os.path.getmtime(WAKE) > ts
    except OSError:
        return False


def ensure(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    if "follow_id" not in have:
        try:
            con.execute("ALTER TABLE trades ADD COLUMN follow_id INTEGER")
        except sqlite3.OperationalError:
            pass
    try:   # 10.11.: the market cap a skip saw (_log mcap), read by the Autopilot's skipped-buy pop-up
        con.execute("CREATE TABLE IF NOT EXISTS copy_mc (follow_id INTEGER, token TEXT, side TEXT, ts INTEGER, "
                    "mcap REAL, PRIMARY KEY (follow_id, token, side))")
    except sqlite3.OperationalError:
        pass
    for sql in INDEXES:
        try:
            con.execute(sql)
        except sqlite3.OperationalError:   # full disk, read-only file: the log still reads, only slower
            pass


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _paths():
    return {"kol": os.environ.get("KOL_DB") or os.path.join(ROOT, "kol.db"),
            "hype": os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db"),
            "tg": os.environ.get("TG_DB") or os.path.join(ROOT, "tg.db")}


# ---------- follows -----------------------------------------------------------------------------------------------

def members_of(target):
    """An 'ekipa' target is its members' handles joined by commas (X handles and tg:channels)."""
    return [m.strip().lstrip("@") for m in (target or "").split(",") if m.strip().lstrip("@")]


def follow(con, user, kind, target, label="", size_usd=25, per_day=10, exit_mode="", tp="", sl="", once=False,
           max_mcap=None, max_runup=None, min_callers=1):
    """Start following (or update an existing follow of the same target). Returns the follow id.
    once (KOLs only): enter their next call, then stop following by itself.
    9.11. (Jure): kind 'ekipa' = a crew of X/Telegram accounts (target 'a,b,tg:c'): one entry per token as soon as
    min_callers of them have called it (1 = the first caller), only while the token is under max_mcap and the price is
    not more than max_runup above where it was at the call. max_mcap / max_runup also work on a single KOL."""
    from . import auto
    ensure(con)
    if kind not in KIND_HR:
        raise ValueError("nepoznata vrsta praćenja")
    target = (target or "").strip()
    if kind == "ekipa":
        mem = sorted(set(members_of(target)))
        if not mem:
            raise ValueError("upiši račune ekipe odvojene zarezom (npr. tg:kanal1, tg:kanal2, @ime)")
        target = ",".join(mem)
        label = label or "ekipa: " + " + ".join(m[3:] if m.startswith("tg:") else "@" + m for m in mem)
    if not target:
        raise ValueError("koga pratiš?")
    size = float(size_usd or 0)
    if not CFG["min_size"] <= size <= CFG["max_size"]:
        raise ValueError(f"ulog po ulazu mora biti između ${CFG['min_size']} i ${CFG['max_size']}")
    per_day = int(per_day or 0)
    if not 1 <= per_day <= CFG["max_per_day"]:
        raise ValueError(f"broj ulaza na dan mora biti između 1 i {CFG['max_per_day']}")
    exit_mode = exit_mode or ("mirror" if kind == "wallet" else "smart")
    allowed = ("mirror", "mirror_smart", "tpsl") if kind == "wallet" else ("smart", "tpsl", "manual", "podaci")
    if exit_mode == "podaci" and kind == "wallet":
        raise ValueError("izlaz po podacima postoji za influencere i ekipe (njihovi se pozivi mjere po minutama); "
                         "wallet se kopira s „prodaj kad on proda” ili s tvojim TP/SL")
    if exit_mode not in allowed:
        raise ValueError("nepoznat način izlaza")
    ex = {"mode": exit_mode}
    if once and kind == "kol":
        ex["once"] = True
    if kind in ("kol", "ekipa"):
        if max_mcap:
            ex["max_mcap"] = float(max_mcap)
        if max_runup is not None and max_runup != "":
            ex["max_runup"] = float(max_runup)
        if kind == "ekipa":
            ex["min_callers"] = max(1, min(int(min_callers or 1), len(members_of(target))))
        if exit_mode == "podaci" and "max_runup" not in ex:
            ex["max_runup"] = DATA_MAX_RUNUP
    if exit_mode == "tpsl":
        # checked now on a made-up entry so a typo shows here and not silently on the first copied trade
        tp_px, _ = auto.parse_level(tp, 1.0, 1e6, "tp")
        sl_px, _ = auto.parse_level(sl, 1.0, 1e6, "sl")
        if tp_px is None and sl_px is None:
            raise ValueError("upiši barem TP ili SL (npr. 100% i -30%)")
        ex.update(tp=tp or "", sl=sl or "")
    row = con.execute("SELECT id FROM follows WHERE user=? AND kind=? AND target=? AND active=1",
                      (user, kind, target)).fetchone()
    if row:
        con.execute("UPDATE follows SET size_usd=?, per_day=?, exit=?, label=? WHERE id=?",
                    (size, per_day, json.dumps(ex), label or target, row[0]))
        con.commit()
        return row[0]
    cur = con.execute("INSERT INTO follows (user, kind, target, label, size_usd, per_day, exit, created) "
                      "VALUES (?,?,?,?,?,?,?,?)", (user, kind, target, label or target, size, per_day, json.dumps(ex),
                                                   int(time.time())))
    con.commit()
    return cur.lastrowid


def set_exit(con, user, follow_id, tp="", sl=""):
    """10.11. (Jure: "za svakog influencera mogu odabrati poseban take profit ili stop loss"): the follow's exit becomes
    "moj TP/SL" with this target and stop for every new entry ("" stop = the account's default stop at the entry,
    default_sl); its entry conditions (MC cap, run-up, crew size, once) stay. Returns the new exit."""
    from . import auto
    ensure(con)
    r = con.execute("SELECT exit FROM follows WHERE id=? AND user=? AND active=1", (follow_id, user)).fetchone()
    if not r:
        raise ValueError("to praćenje ne postoji")
    tp, sl = (tp or "").strip(), (sl or "").strip()
    auto.parse_level(tp, 1.0, 1e6, "tp")   # a typo shows now, not on the next entry
    auto.parse_level(sl, 1.0, 1e6, "sl")
    ex = json.loads(r[0] or "{}")
    ex.update(mode="tpsl", tp=tp, sl=sl)
    con.execute("UPDATE follows SET exit=? WHERE id=?", (json.dumps(ex), follow_id))
    con.commit()
    return ex


def unfollow(con, user, follow_id):
    ensure(con)
    n = con.execute("UPDATE follows SET active=0, stopped=? WHERE id=? AND user=? AND active=1",
                    (int(time.time()), follow_id, user)).rowcount
    con.commit()
    if not n:
        raise ValueError("to praćenje ne postoji")


def follows(con, user=None, active=True):
    ensure(con)
    where, args = ["1=1"], []
    if user:
        where.append("user=?")
        args.append(user)
    if active is not None:
        where.append("active=?")
        args.append(1 if active else 0)
    out = []
    for r in con.execute(f"SELECT * FROM follows WHERE {' AND '.join(where)} ORDER BY created DESC", args):
        d = dict(r)
        d["exit"] = json.loads(d["exit"] or "{}")
        out.append(d)
    return out


def describe_exit(ex, sl0=None):
    """sl0: the default stop to name when the follow has none of its own (the Autopilot page passes default_sl)."""
    base = _describe_exit(ex, sl0)
    cond = []
    if ex.get("min_callers", 1) > 1:
        cond.append(f"ulaz kad zovu {ex['min_callers']}+ iz ekipe")
    if ex.get("max_mcap"):
        cond.append(f"samo do MC ${ex['max_mcap'] / 1e6:g}M" if ex["max_mcap"] >= 1e6 else f"samo do MC ${ex['max_mcap'] / 1e3:g}k")
    if ex.get("max_runup") is not None:
        cond.append(f"ne ako je već +{ex['max_runup']:.0%} od poziva")
    return " · ".join([x for x in [base] if x] + cond)


def _describe_exit(ex, sl0=None):
    s = ("samo sljedeći call, " if ex.get("once") else "") + EXIT_HR.get(ex.get("mode"), "")
    if ex.get("mode") == "tpsl":   # no stop typed: the default one at the entry (default_sl)
        s += " (" + ", ".join(p for p in (f"TP {ex.get('tp')}" if ex.get("tp") else "",
                                          f"SL {ex.get('sl')}" if ex.get("sl") else
                                          f"SL {sl0} zadani" if sl0 else "SL zadani") if p) + ")"
    return s


def log(con, follow_id=None, user=None, limit=100):
    ensure(con)
    sql = ("SELECT l.*, f.user, f.kind, f.label FROM copy_log l JOIN follows f ON f.id = l.follow_id WHERE 1=1"
           + (" AND l.follow_id=?" if follow_id else "") + (" AND f.user=?" if user else "")
           + " ORDER BY l.ts DESC LIMIT ?")
    args = [a for a in (follow_id, user) if a] + [limit]
    return [dict(r) for r in con.execute(sql, args)]


def follow_log_summary(con, since, top=3):
    """follow_id -> {'signali', 'ulaz', 'preskočeno', 'razlozi': [(razlog, n), ...]} from copy_log since `since`
    (buy side only: what the followed account called or bought, what we entered, what we skipped and why).
    9.11. (Jure: "voleti i influenceri koje pratim imali su jedan trade - zašto?"): the reasons lived only in the
    table; now every follow on the page shows its last 24 h. Reasons are grouped with numbers blanked, so
    "vidjeli smo ga tek 12 min nakon objave" and "... 37 min ..." count as one reason."""
    import re as _re
    ensure(con)
    out = {}
    rows = con.execute("SELECT follow_id, action, note FROM copy_log WHERE side='buy' AND ts>=? AND action IN "
                       "('ulaz', 'preskočeno')", (int(since),)).fetchall()
    for fid, action, note in rows:
        r = out.setdefault(fid, {"signali": 0, "ulaz": 0, "preskočeno": 0, "_why": {}})
        r["signali"] += 1
        if action == "ulaz":
            r["ulaz"] += 1
        else:
            r["preskočeno"] += 1
            key = _re.sub(r"\d[\d.,]*", "N", (note or "bez razloga").split(";")[0].split(" (")[0]).strip()[:70]
            r["_why"][key] = r["_why"].get(key, 0) + 1
    for r in out.values():
        r["razlozi"] = sorted(r.pop("_why").items(), key=lambda kv: -kv[1])[:top]
    return out


def follow_results(con):
    """follow_id -> {'n', 'open', 'closed', 'wins', 'pnl'} of the trades it opened (closed PnL only)."""
    ensure(con)
    out = {}
    for fid, status, pnl in con.execute("SELECT follow_id, status, pnl_usd FROM trades WHERE follow_id IS NOT NULL"):
        r = out.setdefault(fid, {"n": 0, "open": 0, "closed": 0, "wins": 0, "pnl": 0.0})
        r["n"] += 1
        if status == "open":
            r["open"] += 1
        else:
            r["closed"] += 1
            r["pnl"] += pnl or 0
            r["wins"] += 1 if (pnl or 0) > 0 else 0
    return out


# ---------- events ------------------------------------------------------------------------------------------------

def events(kol_handles, wallets, since, paths=None):
    """[(target, token, side, ts)] of the followed KOLs ('buy' = a call) and wallets ('buy' / 'sell') since `since`."""
    p = paths or _paths()
    out = []
    if kol_handles:
        x = [h for h in kol_handles if not h.startswith("tg:")]
        tg = [h[3:] for h in kol_handles if h.startswith("tg:")]
        kc, hc, tc = _ro(p["kol"]), _ro(p["hype"]), _ro(p["tg"])
        try:
            if kol_handles:
                q = ",".join("?" * len(kol_handles))
                for h, tok, ts in _q(kc, f"SELECT handle, token, ts FROM calls WHERE kind='call' AND ts >= ? "
                                         f"AND handle IN ({q})", (since, *kol_handles)):
                    out.append((h, tok, "buy", ts))
            if x:
                q = ",".join("?" * len(x))
                for h, ca, ts in _q(hc, f"SELECT handle, ca, ts FROM kol_mentions WHERE ts >= ? AND ca != '' "
                                        f"AND handle IN ({q})", (since, *x)):
                    out.append((h, ca, "buy", ts))
            if tg:
                q = ",".join("?" * len(tg))
                for ch, ts, cas, fwd in _q(tc, f"SELECT channel, ts, cas, fwd_from FROM posts WHERE ts >= ? "
                                               f"AND cas != '' AND channel IN ({q})", (since, *tg)):
                    if not fwd:   # a forward is somebody else's call
                        out.extend((f"tg:{ch}", ca, "buy", ts) for ca in cas.split(",") if ca)
        finally:
            for c in (kc, hc, tc):
                if c is not None:
                    c.close()
    if wallets:
        hc = _ro(p["hype"])
        try:
            q = ",".join("?" * len(wallets))
            for w, mint, side, ts in _q(hc, f"SELECT wallet, mint, side, ts FROM chain_trades WHERE ts >= ? "
                                            f"AND wallet IN ({q})", (since, *wallets)):
                out.append((w, mint, side, ts))
        finally:
            if hc is not None:
                hc.close()
    return [(t, tok, side, int(ts)) for t, tok, side, ts in out if tok and len(tok) >= 32 and ts]


def _logged(con, fid, token, side):
    return con.execute("SELECT 1 FROM copy_log WHERE follow_id=? AND token=? AND side=?", (fid, token, side)).fetchone()


def _log(con, f, token, side, ev_ts, now, action, note, symbol=None, trade_id=None, mcap=None):
    """mcap (10.11., Jure: "u tablici treba biti koliko je token u tom momentu bio vrijedan"): the market cap the
    decision saw, kept with a skip so the Autopilot's pop-up has it at once, before any candle is measured."""
    con.execute("INSERT OR IGNORE INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                (f["id"], token, side, ev_ts, int(now), symbol, action, note, trade_id))
    if mcap:   # its own small table: copy_log keeps its nine columns (older readers insert by position)
        try:
            con.execute("INSERT OR IGNORE INTO copy_mc VALUES (?,?,?,?,?)", (f["id"], token, side, int(now), float(mcap)))
        except sqlite3.OperationalError:
            pass


def _day_start(now, tz=None):
    """Unix time of the last midnight in DAY_TZ (same logic as trade/executor._day_start; not imported so that
    league/ does not pull in trade/wallet + jupiter)."""
    import datetime
    from zoneinfo import ZoneInfo
    z = ZoneInfo(tz or DAY_TZ)
    d = datetime.datetime.fromtimestamp(now, z)
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=z).timestamp())


def _today(con, fid, now):
    day0 = _day_start(int(now))   # 9.11. (audit P58/P62): was UTC midnight, 1-2 h off the real-money day limits
    return con.execute("SELECT COUNT(*) FROM copy_log WHERE follow_id=? AND side='buy' AND action='ulaz' AND ts>=?",
                       (fid, day0)).fetchone()[0]


def _rugged(token, mcap, liq):
    try:
        from rugfilter import collapse
        from ui import data
        return collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
    except Exception:  # noqa: BLE001 - the check is a guard, never the reason the copy loop stops
        return None


def _live_pairs(client, tokens):
    """9.11. (audit P2/P26): the copy loop prices through the short live cache (dexscreener/client.tokens_live,
    DEX_LIVE_TTL 3 s, never 1 s), not the scanners' 60-s cache, so a TP/SL exit and a copy entry see prices seconds
    old. client.tokens stays the seam the offline tests replace with a 2-argument stand-in (same rule as
    ui/paper.live_pairs: decided by the signature, not by catching TypeError)."""
    import inspect
    try:
        legacy = "ttl" not in inspect.signature(client.tokens).parameters
    except (TypeError, ValueError):
        legacy = False
    if legacy:
        return client.tokens("solana", list(tokens))
    return client.tokens_live("solana", list(tokens))


def market(tokens):
    """token -> (price, liquidity, url, mcap, symbol) from the deepest DexScreener pair; {} when unreachable."""
    if not tokens:
        return {}
    try:
        from dexscreener import client
        pairs = _live_pairs(client, tokens)
    except Exception:  # noqa: BLE001 - no price this minute, retried next minute
        return {}
    best = {}
    for p in pairs:
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= best.get(t, (0, -1))[1]:
            ch = p.get("priceChange") or {}
            best[t] = (float(p.get("priceUsd") or 0), liq, p.get("url"), p.get("marketCap") or p.get("fdv"),
                       p["baseToken"].get("symbol"), {"m5": ch.get("m5"), "h1": ch.get("h1")})
    # fresh pump.fun tokens on the bonding curve: DexScreener has no liquidity for them, Jupiter does
    missing = [m for m in tokens if not best.get(m) or not best[m][1] or not best[m][0]]
    if missing:
        try:
            from ui.paper import jup_prices
            jp = jup_prices(missing)
        except Exception:  # noqa: BLE001
            jp = {}
        for m, (px, liq) in jp.items():
            had_pair = m in best   # 9.11. (review novac): DexScreener knows the pair, it just has no price / liquidity now
            _, _, url, mc, sym = best.get(m, (0, 0, None, None, None, None))[:5]
            # 9.11. (audit P1/P5/P8): the 6th element marks the source so run_once can tell "priced only by Jupiter
            # on the bonding curve" (not bonded) from a real DexScreener pair; _runup reads no change out of it
            best[m] = (px, liq, url, mc or (px * 1e9 if m.endswith("pump") else None), sym,
                       {"src": "jup", "dex_pair": True} if had_pair else {"src": "jup"})
    return best


def _bonding_curve(m):
    """True when the market row came from the Jupiter fallback in market(): a pump.fun token still on the bonding
    curve (no DexScreener pair with liquidity). CLAUDE.md: new pump.fun tokens are not taken, bonded ones are."""
    ch = m[5] if len(m) > 5 else None
    return bool(isinstance(ch, dict) and ch.get("src") == "jup")


def _dex_pair_empty(m):
    """9.11. (review novac): True when DexScreener HAS a pair for the token but returned no price / liquidity this
    minute, so market() fell back to Jupiter: not "still on the bonding curve", just no usable quote right now."""
    ch = m[5] if len(m) > 5 else None
    return bool(isinstance(ch, dict) and ch.get("src") == "jup" and ch.get("dex_pair"))


_CONC_CACHE = None   # 9.11. (review novac): per-run_once pass cache of the topcheck / rug tables; None outside a pass


def _conc_tables():
    """(topcheck rows by token, rug_latest rows by token); each {} when the reader is missing or fails."""
    tc, rug = {}, {}
    try:
        from topcheck import store as tstore
        tc = tstore.read_all() or {}
    except Exception:  # noqa: BLE001 - a guard, never the reason the copy loop stops
        pass
    try:
        from ui import data as udata
        rug = udata.rug_latest() or {}
    except Exception:  # noqa: BLE001
        pass
    return tc, rug


def _concentration(token):
    """9.11. (audit P6/P41): supply concentration of the token from data the bot already has (topcheck.db RugCheck
    summary, rug.db full report). Returns (why_block, shown): why_block is set ONLY on known bad values (top10 above
    topcheck.safety.TOP10_FAIL, cluster / bundle / insiders / dev above rugfilter.score hard thresholds, a topcheck
    verdict 'pao'); no row = (None, 'nepoznato'), never a reason to skip a fresh KOL copy. Any error = unknown.
    Inside run_once both tables are read once per pass (_CONC_CACHE), not once per candidate (review novac)."""
    top10 = cluster = bundle = insiders = dev = None
    verdict = None
    try:
        from topcheck import safety as tsafety
        t10_fail, dev_fail = tsafety.TOP10_FAIL, tsafety.DEV_FAIL
    except Exception:  # noqa: BLE001
        t10_fail, dev_fail = 60.0, 20.0
    try:
        from rugfilter import score as rscore
        cl_hard, bu_hard, in_hard = rscore.T["cluster_hard"], rscore.T["bundle_hard"], rscore.T["insider_hard"]
    except Exception:  # noqa: BLE001
        cl_hard, bu_hard, in_hard = 25, 20, 25
    if _CONC_CACHE is None:
        tc, rug = _conc_tables()
    else:
        if "tc" not in _CONC_CACHE:
            _CONC_CACHE["tc"], _CONC_CACHE["rug"] = _conc_tables()
        tc, rug = _CONC_CACHE["tc"], _CONC_CACHE["rug"]
    try:
        row = tc.get(token)
        if row:
            verdict = row.get("verdict")
            rc = row.get("rc") or {}
            top10, insiders, dev = rc.get("top10"), rc.get("insiders"), rc.get("dev_pct")
    except Exception:  # noqa: BLE001 - a guard, never the reason the copy loop stops
        pass
    try:
        r = rug.get(token)
        if r:
            if top10 is None:
                top10 = r.get("top10_pct")
            cluster, bundle = r.get("cluster_pct"), r.get("bundle_pct")
            if insiders is None:
                insiders = ((r.get("data") or {}).get("rugcheck") or {}).get("insider_pct")
    except Exception:  # noqa: BLE001
        pass

    def num(x):
        try:
            return float(x) if x is not None else None
        except (TypeError, ValueError):
            return None

    top10, cluster, bundle, insiders, dev = map(num, (top10, cluster, bundle, insiders, dev))
    why = None
    if verdict == "pao":
        why = "rug check: pao (topcheck)"
    elif top10 is not None and top10 > t10_fail:
        why = f"koncentriran supply: top 10 holdera drži {top10:.0f}% (granica {t10_fail:g}%)"
    elif cluster is not None and cluster > cl_hard:
        why = f"koncentriran supply: jedan klaster walleta drži {cluster:.0f}% (granica {cl_hard:g}%)"
    elif bundle is not None and bundle > bu_hard:
        why = f"koncentriran supply: bundle {bundle:.0f}% u bloku kreacije (granica {bu_hard:g}%)"
    elif insiders is not None and insiders > in_hard:
        why = f"koncentriran supply: insajderi drže {insiders:.0f}% (granica {in_hard:g}%)"
    elif dev is not None and dev > dev_fail:
        why = f"koncentriran supply: dev drži {dev:.0f}% (granica {dev_fail:g}%)"
    shown = f"top10 {top10:.0f}%" if top10 is not None else "nepoznato"
    return why, shown


def _runup(m, age_s):
    """How far the price already moved by the time we see the call, from DexScreener's 5-min / 1-h change (fraction):
    a call seen within 5 min uses m5 (it includes a few minutes before the call: conservative), within an hour h1;
    None when unknown. The exact per-minute path comes later from kol/minute.py; this is the gate at entry time."""
    ch = m[5] if len(m) > 5 else None
    if not ch:
        return None
    v = ch.get("m5") if age_s <= 300 else (ch.get("h1") if age_s <= 3600 else None)
    try:
        return float(v) / 100 if v is not None else None
    except (TypeError, ValueError):
        return None


def _runup_window(age_s):
    """9.11. (audit P59/P60): what _runup really measured, for the log: DexScreener's last-5-min or last-60-min
    change, which is not "since the call" (h1 mostly covers the hour before a 5-10 min old call)."""
    return "zadnjih 5 min" if age_s <= 300 else "zadnjih 60 min"


def followed_handles(user=None, path=None):
    """X handles and tg:channels of every active KOL and crew follow (of `user`, or everyone): the accounts the bot
    must hear from within seconds (tg/poll.py reads them every 2 s, kol/xhook.py puts them in the X webhook)."""
    from . import store as lstore
    p = path or lstore.DB
    if not os.path.exists(p):
        return set()
    con = _ro(p)
    if con is None:
        return set()
    try:
        rows = _q(con, "SELECT kind, target FROM follows WHERE active = 1 AND kind IN ('kol', 'ekipa')" + (" AND user = ?" if user else ""),
                  (user,) if user else ())
    finally:
        con.close()
    out = set()
    for kind, target in rows:
        out |= set(members_of(target)) if kind == "ekipa" else {target}
    return out


def data_exit(f, now=None):
    """9.11. (Jure): the TP/SL kol/tpsl.py picks for this KOL / crew follow from its measured calls, as the dict
    tpsl.decide returns (ok True / False / None), or None when minute.db cannot be read. A crew is judged on the
    call of its min_callers-th member, the moment a crew follow enters. Reads minute.db only; no API call."""
    try:
        from kol import tpsl
        hs = members_of(f["target"]) if f["kind"] == "ekipa" else [f["target"]]
        return tpsl.for_handles(hs, k=int(f["exit"].get("min_callers") or 1), window_s=CFG["crew_window_min"] * 60,
                                now=now)
    except Exception:  # noqa: BLE001 - an unreadable statistic is "unknown", never a block and never a crash
        return None


def _autopilot_user():
    try:
        from trade import settings as ts
        return ts.LEAGUE_USER, ts
    except Exception:  # noqa: BLE001 - league/ without trade/ (tests, a copy of the module): players only
        return None, None


def default_sl(user):
    """The stop of a TP/SL entry that has none of its own: the Autopilot account's setting (trade.settings, "-60%"
    unless the owner changed it on the page), DEFAULT_SL for every player."""
    au, ts = _autopilot_user()
    # 10.11. (Phase 0): the paper account copies the Autopilot account's follows, so it takes the same default stop
    if au is None or user not in (au, getattr(ts, "PAPER_USER", au)):
        return DEFAULT_SL
    try:
        return ts.sl_default()
    except Exception:  # noqa: BLE001
        return ts.sl_text(ts.SL_DEFAULT)


_BASE_CFG = dict(CFG)


def apply_cfg_overrides():
    """10.11.: CFG values the owner moved into trade settings ("copy_cfg", set only by his "Primijeni" on an
    assistant's suggestion, ui/assistnotes.APPLY) hold from the next pass; min_mcap never under 30k (CLAUDE.md)."""
    au, ts = _autopilot_user()
    over = {}
    if ts is not None:
        try:
            con = sqlite3.connect(f"file:{ts.DB}?mode=ro", uri=True, timeout=5)
            try:
                row = con.execute("SELECT v FROM settings WHERE k='copy_cfg'").fetchone()
            finally:
                con.close()
            over = json.loads(row[0]) if row else {}
        except (sqlite3.Error, ValueError, TypeError):
            over = {}
    CFG.clear()
    CFG.update(_BASE_CFG)
    for k, v in (over or {}).items():
        if k in _BASE_CFG and isinstance(v, (int, float)):
            CFG[k] = type(_BASE_CFG[k])(v) if isinstance(_BASE_CFG[k], int) and float(v).is_integer() else v
    CFG["min_mcap"] = max(30_000, CFG.get("min_mcap") or 30_000)
    return CFG


_ADOPTED = set()


def adopt_default_sl(con):
    """Once per database: the Autopilot account's active TP/SL follows whose stop is the old stored default
    (DEFAULT_SL, written by the page's forms since 9.11. when no stop was typed) get an empty stop, i.e. the
    owner's default from now on (10.11., Jure: "default stop loss treba biti −60 %"). A stop typed as anything else
    stays. Marked in copy_meta, so a stop the owner types as "-20%" later is never touched again."""
    au, _ts = _autopilot_user()
    key = (au, _db_file(con))
    if au is None or key in _ADOPTED:
        return 0
    n = 0
    try:
        con.execute("CREATE TABLE IF NOT EXISTS copy_meta (k TEXT PRIMARY KEY, v TEXT)")
        if con.execute("SELECT 1 FROM copy_meta WHERE k='sl_default_1011'").fetchone() is None:
            for fid, ex in con.execute("SELECT id, exit FROM follows WHERE user=? AND active=1", (au,)).fetchall():
                d = json.loads(ex or "{}")
                if d.get("mode") == "tpsl" and (d.get("sl") or "").strip() == DEFAULT_SL:
                    d["sl"] = ""
                    con.execute("UPDATE follows SET exit=? WHERE id=?", (json.dumps(d), fid))
                    n += 1
            con.execute("INSERT OR REPLACE INTO copy_meta VALUES ('sl_default_1011', ?)", (str(int(time.time())),))
            con.commit()
        _ADOPTED.add(key)
    except (sqlite3.Error, ValueError) as e:   # locked or full: tried again on the next pass
        print(f"copy: zadani stop nije prenesen na praćenja ({type(e).__name__}: {e})", flush=True)
    return n


def _db_file(con):
    try:
        return con.execute("PRAGMA database_list").fetchone()[2]
    except sqlite3.Error:
        return ""


def run_once(con, market_fn=None, now=None, paths=None):
    """One pass: enter new calls/buys of followed KOLs and wallets, sell when a followed wallet sells.
    Returns [(user, text)] for the log."""
    from . import auto
    ensure(con)
    adopt_default_sl(con)
    apply_cfg_overrides()
    now = int(now or time.time())
    try:   # 10.11. (Phase 0): the paper account follows what the Autopilot follows while a flag is in paper mode
        from . import flags
        flags.sync_paper(con, now)
    except Exception as e:  # noqa: BLE001 - never stops the copy pass
        print(f"copy: paper račun nije usklađen ({type(e).__name__}: {e})", flush=True)
    fl = follows(con)
    if not fl:
        return []
    by_target = {}
    for f in fl:
        by_target.setdefault((f["kind"], f["target"]), []).append(f)
    crews = [(f, set(members_of(f["target"]))) for f in fl if f["kind"] == "ekipa"]
    kols = sorted({f["target"] for f in fl if f["kind"] == "kol"} | {m for _, mem in crews for m in mem})
    wals = sorted({f["target"] for f in fl if f["kind"] == "wallet"})
    since = now - max(CFG["max_delay_min"], CFG["sell_lookback_min"]) * 60
    evs = sorted(events(kols, wals, since, paths), key=lambda e: e[3])
    todo = []   # (follow, token, side, ts)
    win = CFG["crew_window_min"] * 60
    for target, tok, side, ev_ts in evs:
        kind = "wallet" if target in wals else "kol"
        cands = [(f, ev_ts) for f in by_target.get((kind, target), [])]
        if kind == "kol":
            for f, mem in crews:   # a crew member called: enough of the crew on this token within the window?
                if target in mem:
                    hits = [(t, t2) for t, tk, sd, t2 in evs if tk == tok and sd == "buy" and t in mem and abs(t2 - ev_ts) <= win]
                    if len({t for t, _ in hits}) >= int(f["exit"].get("min_callers") or 1):
                        # 9.11. (audit P4): the crew's signal is the NEWEST member's call in the window, not the first
                        # one; otherwise an old first call made the fresh second call "too late" and blocked it
                        cands.append((f, max(t2 for _, t2 in hits)))
        for f, ts in cands:
            if ts < f["created"] - 60 or tok in STABLE:
                continue   # calls from before the follow started are not copied
            if side == "buy" and now - ts > CFG["max_delay_min"] * 60:
                if not _logged(con, f["id"], tok, "buy") and ts >= f["created"]:
                    _log(con, f, tok, "buy", ts, now, "preskočeno", f"vidjeli smo ga tek {(now - ts) // 60} min nakon "
                         "poziva, prekasno za ulaz")
                continue
            if not _logged(con, f["id"], tok, side):
                todo.append((f, tok, side, ts))
    if not todo:
        con.commit()
        return []
    mk = (market_fn or market)({t for _, t, _, _ in todo}) or {}
    global _CONC_CACHE
    _CONC_CACHE = {}   # 9.11. (review novac): topcheck / rug tables read once for this pass (see _concentration)
    try:
        done = _enter(con, auto, mk, todo, now)
    finally:
        _CONC_CACHE = None
    con.execute("DELETE FROM copy_log WHERE ts < ?", (now - CFG["keep_log_days"] * 86400,))
    from . import flags
    flags.prune(con, now)
    con.commit()
    return done


def _enter(con, auto, mk, todo, now):
    """The second half of run_once: sells and gated buys for the candidates in todo. Returns [(user, text)]."""
    done = []
    stopped = set()   # "only the next call" follows that already entered this minute
    for f, tok, side, ts in todo:
        if f["id"] in stopped:
            continue
        if _logged(con, f["id"], tok, side):
            continue   # the same token twice in this minute (X post + live webhook)
        m = mk.get(tok)
        name = f["label"] or f["target"][:6]
        if side == "sell":
            opened = con.execute("SELECT * FROM trades WHERE follow_id=? AND token=? AND status='open'",
                                 (f["id"], tok)).fetchall()
            if not opened:
                _log(con, f, tok, side, ts, now, "info", "prodao je token koji nismo kopirali")
                continue
            if f["exit"].get("mode") not in ("mirror", "mirror_smart", "tpsl"):
                continue
            if not m or not m[0]:
                if now - ts > CFG["sell_lookback_min"] * 60:
                    _log(con, f, tok, side, ts, now, "preskočeno", "nema cijene za prodaju; prodaj ručno")
                continue   # retried next minute
            for t in opened:
                pnl = store.sell(con, f["user"], t["id"], m[0], m[1], f"copy: {name} je prodao", mcap=m[3])
                _log(con, f, tok, side, ts, now, "izlaz", f"{name} je prodao, i mi: {pnl:+.2f} $", t["symbol"], t["id"])
                done.append((f["user"], f"copy {name}: prodano {t['symbol'] or tok[:6]} {pnl:+.2f} $"))
            continue
        # buy / call
        if not m or not m[0]:
            if now - ts > CFG["price_wait_min"] * 60:
                _log(con, f, tok, side, ts, now, "preskočeno", "DexScreener nema cijenu tog tokena")
            continue
        if _dex_pair_empty(m):   # 9.11. (review novac): a bonded token DexScreener has a pair for, but no quote this
            if now - ts > CFG["price_wait_min"] * 60:   # minute: retry, do not call it "still on the bonding curve"
                _log(con, f, tok, side, ts, now, "preskočeno", "DexScreener ima par, ali trenutno bez cijene/likvidnosti")
            continue
        price, liq, _, mcap = m[:4]
        sym = m[4] if len(m) > 4 else None
        why = None
        age_s = now - ts
        if (liq or 0) < CFG["min_liq"]:
            why = f"premala likvidnost (${liq or 0:,.0f}), ne bi se moglo izaći"
        elif _bonding_curve(m):   # 9.11. (audit P1/P5/P8): CLAUDE.md "novi pump.fun tokeni se ne uzimaju; uzimaju se bondani"
            why = "token je još na pump.fun krivulji (nema DexScreener para), uzimaju se bondani"
        elif (mcap or 0) < CFG["min_mcap"]:   # 9.11. (audit P1/P5/P7): CLAUDE.md "tokeni ispod 30k $ mcapa se ne analiziraju"
            why = (f"MC ${mcap:,.0f} ispod 30k (pravilo: ispod 30k se ne kupuje)" if mcap
                   else "MC nepoznat, a ispod 30k se ne kupuje")
        elif mcap and mcap > CFG["max_mcap"]:
            why = "velik token (preko $50M), to nije poziv na memecoin"
        elif mcap and liq and liq > mcap:
            why = "lažni pool (likvidnost veća od market capa), tipičan rug"
        elif _today(con, f["id"], now) >= f["per_day"]:
            why = f"već {f['per_day']} ulaza danas (tvoj limit)"
        elif con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (f["user"], tok)).fetchone():
            why = "već imaš otvorenu poziciju u tom tokenu"
        elif f["exit"].get("max_mcap") and mcap and mcap > f["exit"]["max_mcap"]:
            why = f"token je već na MC ${mcap:,.0f} (tvoj strop ${f['exit']['max_mcap']:,.0f})"
        elif f["exit"].get("max_runup") is not None and (_runup(m, age_s) or 0) > f["exit"]["max_runup"]:
            # 9.11. (audit P59/P60): say what was measured (DexScreener m5/h1), not "od poziva"
            why = (f"cijena je već +{_runup(m, age_s):.0%} u {_runup_window(age_s)} "
                   f"(tvoj prag +{f['exit']['max_runup']:.0%} od poziva)")
        elif mcap and liq and liq < CFG["min_liq_mcap"] * mcap:   # 9.11. (audit P41): one big holder would empty the pool
            why = (f"likvidnost ${liq:,.0f} je samo {liq / mcap:.1%} MC-a (granica {CFG['min_liq_mcap']:.0%}): "
                   "najveći holder bi srušio cijenu prije stopa")
        else:
            col = _rugged(tok, mcap, liq)
            if col:
                why = f"token je rugan ({col['text']})"
        conc_shown = "nepoznato"
        if not why:   # 9.11. (audit P6): supply concentration, blocks only on KNOWN bad data
            why, conc_shown = _concentration(tok)
        dx = None
        if not why and f["exit"].get("mode") == "podaci":
            if now - ts > DATA_MAX_LATE_S:
                why = (f"poziv je star {now - ts} s: izlaz po podacima mjeren je za ulaz u prvoj minuti nakon poziva "
                       f"(najviše {DATA_MAX_LATE_S} s)")
            else:
                # 9.11. (Jure): the tool decides from the measured calls; "no pair in the plus" is a skip like any gate
                dx = data_exit(f, now)
                if dx and dx.get("ok") is False:
                    why = dx["why"]
        if why:
            _log(con, f, tok, side, ts, now, "preskočeno", why, sym, mcap=mcap)
            continue
        src = f"copy {KIND_HR[f['kind']]} {name}"
        try:
            tid = store.buy(con, f["user"], tok, sym, f["size_usd"], price, liq, src, None, mcap)
        except ValueError as e:
            _log(con, f, tok, side, ts, now, "preskočeno", str(e), sym)
            continue
        con.execute("UPDATE trades SET follow_id=? WHERE id=?", (f["id"], tid))
        mode = f["exit"].get("mode")
        exit_note = ""
        try:
            if mode in ("smart", "mirror_smart"):
                auto.set_auto(con, f["user"], tid, "smart")
            elif mode == "tpsl":
                # 9.11. (audit): no explicit stop -> DEFAULT_SL; levels from the effective entry (fee + impact)
                auto.set_auto(con, f["user"], tid, "tpsl", f["exit"].get("tp", ""),
                              f["exit"].get("sl") or default_sl(f["user"]), from_eff=True)
            elif mode == "podaci" and dx and dx.get("ok"):
                # the pair was measured over the hour after the call: the position is closed at the end of that hour
                auto.set_auto(con, f["user"], tid, "tpsl", f"{dx['tp']}%", f"-{dx['sl']}%", from_eff=True,
                              hold_s=DATA_HOLD_S)
                exit_note = "; " + dx["why"]
            elif mode == "podaci":   # too few measured calls (or minute.db unreadable): the default pair until then
                sl0 = default_sl(f["user"])
                auto.set_auto(con, f["user"], tid, "tpsl", DATA_TP, sl0, from_eff=True)
                exit_note = (f"; {(dx or {}).get('why') or 'minutna provjera nije dostupna'}: zadani izlaz "
                             f"TP +{DATA_TP.rstrip('%')} % / SL {sl0.rstrip('%')} %")
        except ValueError as e:   # 9.11. (audit P28): e.g. TP "$500k" on a token already at $600k: never leave the
            try:                  # position (mirrored into real money) without an exit; fall back to Smart sell
                auto.set_auto(con, f["user"], tid, "smart")
                exit_note = f"; izlaz: Smart sell (TP/SL nije primjenjiv: {e})"
            except ValueError as e2:
                exit_note = f"; BEZ automatskog izlaza ({e2})"
        late = max(0, now - ts)
        _log(con, f, tok, side, ts, now, "ulaz", f"kupljeno za ${f['size_usd']:,.0f} na MC ${mcap or 0:,.0f}, "
             f"{late // 60} min {late % 60} s nakon {'poziva' if f['kind'] in ('kol', 'ekipa') else 'njegove kupnje'}"
             f", koncentracija: {conc_shown}{exit_note}", sym, tid)
        done.append((f["user"], f"copy {name}: kupljeno {sym or tok[:6]} za ${f['size_usd']:,.0f}"))
        if f["exit"].get("once"):
            con.execute("UPDATE follows SET active=0, stopped=? WHERE id=?", (now, f["id"]))
            stopped.add(f["id"])
    return done
