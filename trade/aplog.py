"""One decision log of the Autopilot: what it bought, what it sold, what it skipped and why, what did not go through.

10.11. (Jure: "log Autopilota na klik pri vrhu: kad je kupio, kad nije, što je preskočio i zašto"). The answer was
spread over three places: trade.db orders (every swap attempt), trade.db positions (a signal the real-money mirror
refused has only a 'blocked' row with the reason) and league.db copy_log (a call the demo copy stage skipped never
reaches trade.db at all). entries() reads the three and gives one list, newest first, one row per decision:

    kupio         a position was opened (real swap or dry-run quote)
    prodao        a sale went through (with pnl_pct when it closed the position)
    preskocio     a rule said no, in the demo copy stage (stage "demo") or in the real-money mirror (stage "pravi");
                  that is the bot working as told (trebao False)
    nije_proslo   the signal passed every rule and should have been bought (or the position sold), but the order did
                  not go through: no quote, network, a transaction that did not land (trebao True)

The same signal is never listed twice: a buy is ONE row however many routes were tried (the unit is the position,
not the orders row); a demo entry (copy_log 'ulaz') is not listed because its outcome is the trade.db row the mirror
wrote for it; failed tries to sell an open position are one row (the newest), gone once the sale goes through.

Read every second while the log is open: every query walks an index backwards and stops at LIMIT (ensure() adds the
indexes trade.db lacked; league/copy.py adds the ones on copy_log and follows), nothing reads a whole table.
`why` is the raw reason and may carry a route's error text; anything public shows `why_short` only, which is always
one of the fixed words below ("ostalo" for a reason nobody has named yet).
"""
import re
import sqlite3
import time

from trade import settings

KINDS = ("kupio", "prodao", "preskocio", "nije_proslo")
LAMPORTS = 1_000_000_000
MAX_LIMIT = 2000
DAY_LIMIT = 1000        # summary_24h reads up to this many decisions of the last day
MIRROR_GRACE_S = 120    # a demo entry this old without a trade.db row was never seen by the real-money mirror
MISSED = ("demo kopija je ušla, ali zrcaljenje pravim novcem nije obradilo signal "
          "(trade proces tada nije radio ili se ponovno pokretao)")

INDEXES = (
    "CREATE INDEX IF NOT EXISTS positions_opened ON positions (opened_ts)",
    "CREATE INDEX IF NOT EXISTS positions_status ON positions (status, opened_ts)",
    "CREATE INDEX IF NOT EXISTS positions_league ON positions (league_id)",
    "CREATE INDEX IF NOT EXISTS orders_pos ON orders (position_id, side)",
    "CREATE INDEX IF NOT EXISTS orders_side ON orders (side, status, ts)",
    "CREATE INDEX IF NOT EXISTS orders_ts ON orders (ts)",
)

# (pattern, short word, technical). The first match wins; technical = the order did not go through although the
# signal was good (trebao True), the rest are rules doing their job. Texts come from run_trade.follow_league_once,
# trade/executor.py (gate_buy, sell_check, swap routes), trade/jupiter.ERRORS_HR and league/copy.py (_enter).
REASONS = tuple((re.compile(p, re.I), short, tech) for p, short, tech in (
    (r"provjera prodaje nije uspjela|ne kupujem naslijepo", "provjera prodaje nije uspjela", True),
    (r"zrcaljenje pravim novcem", "trade proces nije radio", True),
    (r"rate limit|too many requests|\b429\b", "mreža", True),
    (r"signal star", "signal star", False),
    (r"ispod 30k|mc nepoznat", "MC ispod 30k", False),
    (r"bez dokaza|bez zapisa praćenja", "bez dokaza u demu", False),
    (r"prekasno za ulaz|vidjeli smo ga tek|poziv je star", "kasni poziv", False),
    (r"krivulj|uzimaju se bondani", "nije bondan", False),
    (r"honeypot|nema rute za prodaju", "honeypot", False),
    (r"\brug|lažni pool", "rug", False),
    (r"koncentriran", "koncentracija", False),
    (r"nema cijen|bez cijene|ne zna cijenu", "nema cijene", False),
    (r"likvidnost", "likvidnost", False),
    (r"velik token", "prevelik token", False),
    (r"tvoj strop", "MC iznad stropa", False),
    (r"cijena je već", "cijena već otišla", False),
    (r"po podacima", "ne isplati se po podacima", False),
    (r"trošak|gubi \d|nema ruba", "trošak swapa", False),
    (r"otvoren\w* pozicij\w* u (ovom|tom) tokenu", "već u poziciji", False),
    (r"dnevni gubitak|stop do ponoći", "dnevni stop", False),
    (r"limit|otvorenih pozicija|ulaza danas|slobodnih \$", "limit", False),
    (r"premalo sol|insufficient", "premalo SOL-a", False),
    (r"kill switch", "ručno zaustavljeno", False),
    (r"istraživački|konvergencijski|ne kopira se", "samo demo", False),
    (r"ne odgovara|urlerror|timeout|timed out|http ?\d{3}|http error|connection|neispravan odgovor", "mreža", True),
    (r"nema rute|no route|failed to get quotes", "nema rute", True),
    (r"klizanj|slippage", "klizanje cijene", True),
    (r"istek|nije stigla u blok|expired", "transakcija nije stigla na vrijeme", True),
    (r"nije potvrdi|nije potvrđen", "swap nije potvrđen", True),
    (r"prekinut", "prekid usred naloga", True),
    (r"ključ|nisu postavljeni|potpisan", "ključ nije spreman", True),
    (r"nije dao transakciju|nije prošla|odbio|greška|neispravn", "greška rute", True),
))
# why a position was sold or reduced (orders.reason of a sale: league/auto.py notes, paper/sim.py fills, the buttons)
EXITS = tuple((re.compile(p, re.I), short) for p, short in (
    # 10.11. (review novac): paper/sim.py also closes with "time", "breakeven" and "stale" (league/auto.py writes
    # them as "auto: time" ...); they were "ostalo"
    (r"vrijeme|moonbag_time|\btime\b", "istek vremena"),
    (r"breakeven", "stop na ulazu"),
    (r"\bstale\b", "bez pomaka"),
    (r"\btp\b|take_profit", "cilj (TP)"),
    (r"\bsl\b|stop_loss", "stop (SL)"),
    (r"je prodao", "prodao i praćeni"),
    (r"djelomičn", "djelomična prodaja"),
    (r"ručn|rucno|gumb|prodaj sve", "ručno"),
    (r"\brug", "rug"),
    (r"smart|trailing|eksplozij", "Smart sell"),
    (r"demo izlaz", "izlaz kao u demu"),
))
OTHER = "ostalo"

_LOGGED = {}
_DAY = {}   # database file -> (ts, summary): summary_24h for a few seconds


def _log_once(key, text, every=600):
    now = time.time()
    if now - _LOGGED.get(key, 0) >= every:
        _LOGGED[key] = now
        print(f"aplog: {text}", flush=True)


def ensure(con):
    """Indexes the log's queries walk (called from executor.connect). They also serve the trade loop's own
    every-second reads (pending buys and sells, open positions), which used to scan both tables."""
    for sql in INDEXES:
        con.execute(sql)


def scrub(text, n=300):
    """A reason as shown to the owner: no URL beyond its host (an RPC address carries the API key), no key-like
    token, at most n characters."""
    if not text:
        return None
    t = re.sub(r"(https?://[^/\s?'\"]+)[^\s'\")]*", r"\1/…", str(text))
    t = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "…", t, flags=re.I)
    # 10.11. (review novac): a key outside a URL ("api-key=…", "token: …" in an exception text)
    t = re.sub(r"(?i)\b(api[-_]?key|apikey|key|token|secret|password|auth(?:orization)?)(\s*[=:]\s*)(?:bearer\s+)?"
               r"[^\s,;&'\")]+", r"\1\2…", t)
    return t[:n]


def _classify(text):
    for rx, short, tech in REASONS:
        if rx.search(text):
            return short, tech
    return None, False


def _exit(text):
    for rx, short in EXITS:
        if rx.search(text):
            return short
    return None


def why_short(text, kind=None):
    """The reason as one of a fixed set of short words: "signal star", "MC ispod 30k", "bez dokaza u demu", "kasni
    poziv", "likvidnost", "rug", "limit", ... Safe to show to anyone: the text itself is never returned, a reason
    without a word yet is "ostalo", no reason is "". kind "prodao" reads the text as the reason of a sale first
    (a followed account's name inside "x je prodao" must not be read as a skip reason)."""
    if not text or not str(text).strip():
        return ""
    t = str(text)
    if kind == "prodao":
        return _exit(t) or _classify(t)[0] or OTHER
    return _classify(t)[0] or _exit(t) or OTHER


def _source(text):
    """"copy KOL ansem" -> "KOL ansem"; an attempt's suffix off; other sources (ručno, paper #12) as they are."""
    if not text:
        return None
    t = str(text).split(" · pokušaj")[0].strip()
    return (t[5:] if t.startswith("copy ") else t) or None


def _chunks(ids, n=400):
    ids = list(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _buy_orders(tcon, pids):
    """position id -> (source text, intended lamports, signature of the swap) from the buy's orders rows (the last
    row is the result, earlier ones are failed routes)."""
    out = {}
    for ch in _chunks(pids):
        q = ",".join("?" * len(ch))
        for pid, status, a_in, reason, sig in tcon.execute(
                f"SELECT position_id, status, amount_in, reason, signature FROM orders WHERE position_id IN ({q}) "
                "AND side='buy' ORDER BY id", ch):
            old = out.get(pid, (None, None, None))
            out[pid] = (reason or old[0], a_in or old[1], sig if status in ("ok", "dry") and sig else old[2])
    return out


def _entry(ts, kind, token, symbol, source, why, sol, pnl_pct, mode, stage, sig, trebao, side, key):
    return {"ts": int(ts or 0), "kind": kind, "token": token, "symbol": symbol, "source": source, "why": scrub(why),
            "why_short": why_short(why, kind), "sol": sol, "pnl_pct": pnl_pct, "mode": mode, "stage": stage,
            "sig": sig, "trebao": trebao, "side": side, "id": key}


def _buys(tcon, since, limit):
    """One row per position the mirror or a manual buy wrote: opened -> kupio, blocked by a rule -> preskocio,
    failed or blocked by something technical -> nije_proslo. Returns (entries, {position id: league_id} without a
    known source)."""
    rows = tcon.execute(
        "SELECT id, token, symbol, opened_ts, mode, status, reason, sol_in, league_id, paper_id FROM positions "
        # +status: keeps the planner on the opened_ts index (newest first, stops at LIMIT); on the status index it
        # would collect every position of the four states and sort them
        "WHERE opened_ts >= ? AND +status IN ('open','closed','blocked','failed') "
        "ORDER BY opened_ts DESC, id DESC LIMIT ?", (since, limit)).fetchall()
    orders = _buy_orders(tcon, [r[0] for r in rows])
    out = []
    for pid, token, symbol, ts, mode, status, reason, sol_in, lid, paper_id in rows:
        src, lam, sig = orders.get(pid, (None, None, None))
        source = _source(src) or ("demo strategija" if paper_id is not None else None)
        if status in ("open", "closed"):
            e = _entry(ts, "kupio", token, symbol, source, None, sol_in, None, mode, "pravi", sig, None, "buy", f"p{pid}")
        else:
            tech = status == "failed" or _classify(reason or "")[1]
            e = _entry(ts, "nije_proslo" if tech else "preskocio", token, symbol, source, reason,
                       lam / LAMPORTS if lam else None, None, mode, "pravi", None, bool(tech), "buy", f"p{pid}")
        e["_lid"] = lid if source is None else None
        out.append(e)
    return out


def _sells(tcon, since, limit):
    """Sales that went through (real 'ok' and dry-run), newest first; the newest sale of a closed position carries
    the position's result in percent of its stake, after network fees."""
    rows = []
    for status in ("ok", "dry"):   # one index walk each (side, status, ts): failed tries are never read
        rows += tcon.execute(
            "SELECT o.id, o.ts, o.position_id, o.token, o.mode, o.amount_out, o.reason, o.signature, p.symbol, p.status, "
            "p.sol_in, p.sol_back, COALESCE(p.fees_sol,0) FROM orders o LEFT JOIN positions p ON p.id = o.position_id "
            "WHERE o.side='sell' AND o.status=? AND o.ts >= ? ORDER BY o.ts DESC, o.id DESC LIMIT ?",
            (status, since, limit)).fetchall()
    rows.sort(key=lambda r: (r[1], r[0]), reverse=True)
    rows = rows[:limit]
    src = _buy_orders(tcon, {r[2] for r in rows if r[2] is not None})
    out, closed = [], set()
    for oid, ts, pid, token, mode, a_out, reason, sig, symbol, pstatus, sol_in, sol_back, fees in rows:
        pnl = None
        if pstatus == "closed" and pid not in closed and sol_in:
            closed.add(pid)
            pnl = round(100 * ((sol_back or 0) - sol_in - fees) / sol_in, 2)
        out.append(_entry(ts, "prodao", token, symbol, _source(src.get(pid, (None,))[0]), reason,
                          (a_out or 0) / LAMPORTS, pnl, mode, "pravi", sig, None, "sell", f"o{oid}"))
    return out


def _stuck_sells(tcon, since):
    """Open positions whose newest try to sell failed: one row each, however many tries there were."""
    rows = tcon.execute(
        "SELECT p.id, p.token, p.symbol, p.mode, o.id, o.ts, o.error FROM positions p JOIN orders o ON o.id = "
        "(SELECT id FROM orders WHERE position_id = p.id AND side='sell' ORDER BY id DESC LIMIT 1) "
        "WHERE p.status='open' AND o.status='failed' AND o.ts >= ? LIMIT 100", (since,)).fetchall()
    src = _buy_orders(tcon, [r[0] for r in rows])
    return [_entry(ts, "nije_proslo", token, symbol, _source(src.get(pid, (None,))[0]), err or "prodaja nije prošla",
                   None, None, mode, "pravi", None, True, "sell", f"o{oid}")
            for pid, token, symbol, mode, oid, ts, err in rows]


def _mode_now(tcon):
    """What the real-money mirror would trade in right now; demo-stage rows carry it (they never reached trade.db)."""
    try:
        import json
        from trade import executor   # here: executor.connect calls ensure() of this module
        row = tcon.execute("SELECT v FROM settings WHERE k='on'").fetchone()   # the switch alone, by its key
        return "live" if executor.is_live({"on": json.loads(row[0]) if row else False}) else "dry"
    except Exception:  # noqa: BLE001
        return "dry"


def _league(lcon):
    """(connection, ours to close). Without one, league.db is opened read-only (the dashboard is its only writer)."""
    if lcon is not None:
        return lcon, False
    import os
    from league import store
    if not os.path.exists(store.DB) or not os.path.getsize(store.DB):
        return None, False
    return sqlite3.connect(f"file:{store.DB}?mode=ro", uri=True, timeout=5), True


def _demo(tcon, lcon, since, limit, now):
    """Decisions of the demo copy stage for the follows of the real-trade account: calls and buys it skipped (with
    the reason league/copy.py wrote) and, as nije_proslo, demo entries the mirror never turned into a trade.db row."""
    from league import copy as lcopy
    follows = lcon.execute("SELECT id, kind, label, target FROM follows WHERE user=? AND (active=1 OR stopped >= ?)",
                           (settings.LEAGUE_USER, max(since, int(now) - lcopy.CFG["keep_log_days"] * 86400))).fetchall()
    rows = []
    for fid, kind, label, target in follows:
        name = f"{lcopy.KIND_HR.get(kind, kind)} {label or (target or '')[:6]}"
        # per follow and action: its newest rows straight from (follow_id, action, ts), never walking past the
        # follow's "info" and "izlaz" rows (a busy wallet writes one for every sale of a coin we never copied)
        for action in ("preskočeno", "ulaz"):
            rows += [(name, *r) for r in lcon.execute(
                "SELECT follow_id, token, side, ts, symbol, action, note, trade_id FROM copy_log WHERE follow_id=? "
                "AND action=? AND ts >= ? ORDER BY ts DESC LIMIT ?", (fid, action, since, limit))]
    rows.sort(key=lambda r: r[4], reverse=True)
    rows = rows[:limit]
    entered = {r[8] for r in rows if r[6] == "ulaz" and r[8] is not None}
    seen = set()
    for ch in _chunks(entered):
        seen |= {x[0] for x in tcon.execute(
            f"SELECT league_id FROM positions WHERE league_id IN ({','.join('?' * len(ch))})", ch)}
    mode, out = _mode_now(tcon), []
    for name, fid, token, side, ts, symbol, action, note, tid in rows:
        key = f"c{fid}:{token}:{side}"
        if action == "preskočeno":
            out.append(_entry(ts, "preskocio", token, symbol, name, note or "bez razloga", None, None, mode, "demo",
                              None, False, side, key))
        elif tid not in seen and now - ts > MIRROR_GRACE_S:
            out.append(_entry(ts, "nije_proslo", token, symbol, name, MISSED, None, None, mode, "pravi", None, True,
                              side, key))
    return out


def _league_sources(lcon, entries):
    """Source of a signal the mirror refused before any order existed: the demo trade's own source."""
    want = {e["_lid"] for e in entries if e.get("_lid") is not None}
    if not want or lcon is None:
        return
    src = {}
    for ch in _chunks(want):
        src.update(lcon.execute(f"SELECT id, source FROM trades WHERE id IN ({','.join('?' * len(ch))})", ch).fetchall())
    for e in entries:
        if e.get("_lid") in src:
            e["source"] = _source(src[e["_lid"]])


def _entries(tcon, lcon, limit, since, now):
    # in this order because the sort below is stable: in one second, a sale is listed above the buy it follows
    out = _stuck_sells(tcon, since) + _sells(tcon, since, limit) + _buys(tcon, since, limit)
    try:
        lg, own = _league(lcon)
    except Exception as e:  # noqa: BLE001 - league.db missing or locked: the real-money part still shows
        _log_once("league", f"league.db nije dostupan ({type(e).__name__})")
        lg, own = None, False
    if lg is not None:
        try:
            _league_sources(lg, out)
            out += _demo(tcon, lg, since, limit, now)
        except sqlite3.Error as e:   # no copy tables yet, or a locked file
            _log_once("demo", f"demo faza nije pročitana ({type(e).__name__}: {str(e)[:80]})")
        finally:
            if own:
                lg.close()
    for e in out:
        e.pop("_lid", None)
    out.sort(key=lambda e: e["ts"], reverse=True)
    return out[:limit]


def entries(tcon, lcon=None, limit=80, since=None, now=None):
    """The decision log, newest first: [{ts, kind, token, symbol, source, why, why_short, sol, pnl_pct, mode, stage,
    sig, trebao, side, id}].

    tcon: trade.db (executor.connect); lcon: league.db connection or None (opened read-only here); since: unix time
    of the oldest decision wanted (None = no bound; the queries stop at `limit` either way); now: for tests.
    kind: one of KINDS. source: who gave the signal ("KOL ansem", "wallet 7xKX…", "ručno"). why: the reason as
    written (owner only), why_short: its fixed short word (public). sol: SOL spent (kupio), received (prodao) or
    meant to be spent (nije_proslo), else None. pnl_pct: on the sale that closed a position. mode: "live" | "dry".
    stage: "demo" (decided in the demo copy stage) | "pravi" (in the real-money mirror). sig: transaction signature
    or None. trebao: True = should have gone through and did not, False = a rule said no, None = kupio / prodao.
    side: "buy" | "sell" (which half of a trade the row is about). id: a stable key of the row.
    [] on any error (one log line), never an exception towards the page."""
    try:
        return _entries(tcon, lcon, max(1, min(int(limit or 80), MAX_LIMIT)), int(since or 0),
                        time.time() if now is None else now)
    except Exception as e:  # noqa: BLE001
        _log_once("entries", f"dnevnik nije pročitan ({type(e).__name__}: {str(e)[:120]})")
        return []


def summary(rows, now=None):
    """The one-line summary of the last 24 h of `rows` (entries()): {"signali", "kupio", "prodao", "preskocio",
    "nije_proslo", "razlozi": [(why_short, n), ...], "razlozi_nije_proslo": [...], "prodaja_nije_prosla"}.
    signali = kupio + preskocio + nije_proslo, all three counted on the buy side only (a signal is a call or a buy
    of a followed account); prodao counts sales; a sale that keeps failing is prodaja_nije_prosla. razlozi are the
    skips' short reasons, most frequent first. Pass rows that cover the whole day (entries(limit=DAY_LIMIT,
    since=now - 86400), or use summary_24h): the default 80 rows can be less than a busy day."""
    now = time.time() if now is None else now
    out = {"signali": 0, "kupio": 0, "prodao": 0, "preskocio": 0, "nije_proslo": 0, "prodaja_nije_prosla": 0}
    why, why_fail = {}, {}
    for e in rows or ():
        if e.get("ts", 0) < now - 86400:
            continue
        kind, sell = e.get("kind"), e.get("side") == "sell"
        if kind == "prodao":
            out["prodao"] += 1
        elif kind == "nije_proslo" and sell:
            out["prodaja_nije_prosla"] += 1
        elif kind in ("kupio", "preskocio", "nije_proslo") and not sell:
            out[kind] += 1
            out["signali"] += 1
            if kind != "kupio":
                d = why if kind == "preskocio" else why_fail
                key = e.get("why_short") or OTHER
                d[key] = d.get(key, 0) + 1
    out["razlozi"] = sorted(why.items(), key=lambda kv: (-kv[1], kv[0]))
    out["razlozi_nije_proslo"] = sorted(why_fail.items(), key=lambda kv: (-kv[1], kv[0]))
    return out


def summary_24h(tcon, lcon=None, now=None, ttl=5):
    """summary() over the whole last day (up to DAY_LIMIT decisions), kept for `ttl` seconds per database: the line
    under the closed log is on every page view, the list itself only when somebody opens it."""
    now = time.time() if now is None else now
    try:
        key = tcon.execute("PRAGMA database_list").fetchone()[2] or id(tcon)
    except sqlite3.Error:
        key = id(tcon)
    hit = _DAY.get(key)
    if hit and 0 <= now - hit[0] < ttl:
        return dict(hit[1])
    val = summary(entries(tcon, lcon, limit=DAY_LIMIT, since=int(now) - 86400, now=now), now)
    if len(_DAY) > 16:
        _DAY.clear()
    _DAY[key] = (now, val)
    return dict(val)
