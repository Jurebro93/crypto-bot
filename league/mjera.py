"""Mjerenje praćenja novčanika po ulazu (19.11., vlasnik: "Demo money maybe no longer makes sense, since for every
entry one can simply measure whether it was profitable or not in percent, not in demo money ... Yes, start with both
steps.").

STEP 1, the measurement: every wallet-following SIGNAL (a watched group / bundle / proven wallet buys a token) is one
row of league.db `signal_mjera`, in percent, with no account, no cash, no caps, no one-position-per-token. The sources
call record() where they SEE the buy, BEFORE their demo caps decide, so nothing is lost to a cap:

  prije_pumpe, prije_pumpe_kandidat, bundle   insajderi/pp_live.run_once
  insajderi2                                  insajderi/live.run_once
  kopija                                      wallets/kopija_demo.run_once

  entry   the first quote we get at or after seen_ts (the same league/copy.market quote the demo uses in that pass;
          a row without one is priced by the next pass, at most ENTRY_WAIT_S, else a miss "bez cijene"); never their
          own price. guard = veliki/live.guards on that quote ("ok" or why it could not be copied: such rows are
          MISSES, kept and counted, never in a mean)
  exit    the copy test's pre-declared rule (insajderi/copy.simulate): their sale (any member of the group, any wallet
          of a bundle, the wallet itself) seen by a pass -> "prodali su" at that pass's quote; else the price at or
          below -STOP (25 %) -> "stop"; else HOLD_S (24 h) after the entry -> "vrijeme"; a row that gets no quote for
          NO_PRICE_S closes as "bez cijene" (a miss). The pass sees prices every EVERY_S, so a stop fills at the
          pass's price, not exactly at -25 % (the demo's own stop is checked the same way by league/auto)
  cost    trade/cost.round_trip at 0.1 SOL and at 0.5 SOL with the row's liquidity, never under the round-trip floor
          (insajderi/prijepumpe.rt_floor: veliki/replay.RT_FLOOR, 3 %): ret_net = ret_gross - cost
  dedup   (source, gid, token) within DEDUP_S (24 h) is one row; another source on the same token is its own row

pass_() runs inside league/auto.loop (run_ui.py, league.db's only writer), at most every EVERY_S, pricing at most
MAX_ROWS open rows (oldest price first) within MAX_PASS_S seconds of wall clock.

summary() / line(): per source x MC bucket: signals, measured, misses, open, mean net % at 0.1 and 0.5 SOL, the 95 %
bootstrap interval BY TOKEN-DAY (a token's rows of one UTC day are one draw), the winners' share, the median real
delay (seen_ts - their_buy_ts); the capacity view ("at most N open at once", N = 5, 10, 20, signals in time order).

STEP 2, retiring the demo money for wallet following: parity() compares the measurement with the three demos on the
SAME closed trades (source + token + entry within PARITY_WINDOW_S); mode() is the trade.db settings key MODE_KEY
(auto / demo / mjera, default auto). In "auto" the moment parity holds is remembered ONCE (mjera_kv "prebaceno").
23.11. (vlasnik: "Demo tradanje nikad ne treba prestati ... demo u pozadini non stop radi tradeove"): that moment no
longer stops the demos; they go on next to the measurement in "auto" and "demo", and only the owner's own choice
"mjera" holds their NEW trades (open trades exit by their own rules; nothing is deleted). demo_entries_ok() is what
the three sources ask before an entry.

proof(): the rule a FUTURE real-money wallet-copy switch must ask (>= 100 measured token-days, mean net at 0.1 SOL
> 0 and the interval's low > 0). Nothing reads it for real money today (real money is paused and no wallet-copy real
switch exists); run_trade / trade/executor never import this module (a test checks it).
"""
import json
import random
import statistics
import time

SOURCES = ("prije_pumpe", "prije_pumpe_kandidat", "bundle", "kopija", "insajderi2")
LABEL = {"prije_pumpe": "prije pumpe", "prije_pumpe_kandidat": "kandidati", "bundle": "bundle",
         "kopija": "kopija dokazanih", "insajderi2": "insajderi2"}
BUCKETS = ("15-200M", "2-15M", "<2M", ">200M", "?")
STOP = 0.25
HOLD_S = 24 * 3600
DEDUP_S = 24 * 3600
ENTRY_WAIT_S = 600
NO_PRICE_S = 6 * 3600
EVERY_S = 60
MAX_ROWS = 120
MAX_PASS_S = 20.0
SIZES_SOL = (0.1, 0.5)
SOL_USD_FALLBACK = 150.0
MIN_TOKEN_DAYS = 100
BOOT_N = 1000
CAPACITY = (5, 10, 20)
PARITY_WINDOW_S = 600
PARITY_MIN_N = 20
PARITY_MAX_PP = 1.5
MODE_KEY = "mjera_nacin"
MODES = ("auto", "demo", "mjera")
PREFIX = "mjerenje praćenja novčanika: "

SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_mjera (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, kind TEXT, gid TEXT, wallet TEXT, members TEXT, token TEXT,
    symbol TEXT, their_buy_ts INTEGER, seen_ts INTEGER, delay_s INTEGER, entry_ts INTEGER, entry_price REAL,
    entry_mcap REAL, mc_bucket TEXT, liq REAL, guard TEXT, status TEXT, exit_ts INTEGER, exit_price REAL,
    exit_reason TEXT, ret_gross REAL, cost_01 REAL, cost_05 REAL, ret_net_01 REAL, ret_net_05 REAL, token_day TEXT,
    last_px_ts INTEGER, last_px REAL);
CREATE INDEX IF NOT EXISTS signal_mjera_status ON signal_mjera (status, last_px_ts);
CREATE INDEX IF NOT EXISTS signal_mjera_key ON signal_mjera (source, gid, token, seen_ts);
CREATE TABLE IF NOT EXISTS mjera_kv (k TEXT PRIMARY KEY, v TEXT);
"""
_LAST = {"pass": 0.0, "line_day": None}


def ensure(con):
    con.executescript(SCHEMA)


def _kv(con, k, v=None):
    if v is None:
        r = con.execute("SELECT v FROM mjera_kv WHERE k=?", (k,)).fetchone()
        try:
            return json.loads(r[0]) if r else None
        except (ValueError, TypeError):
            return None
    con.execute("INSERT OR REPLACE INTO mjera_kv VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))


def bucket(mcap):
    """The MC bucket at entry, the same as the demo of insajderi/pp_live."""
    if mcap is None:
        return "?"
    if mcap < 2e6:
        return "<2M"
    if mcap < 15e6:
        return "2-15M"
    if mcap <= 200e6:
        return "15-200M"
    return ">200M"


def day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))


def _guard(tok, q):
    """veliki/live.guards on the quote: None (ok) or why it could not be copied; "nema žive cijene" = no quote."""
    try:
        from veliki import live as vlive
        return vlive.guards(tok, q)
    except Exception as e:  # noqa: BLE001 - a guard that cannot run is no reason to lose the signal
        return None if q and q[0] else f"nema žive cijene ({type(e).__name__})"


def _enter(con, rid, tok, q, now):
    """Fill the entry of a pending row from quote q; True when entered or turned into a miss."""
    why = _guard(tok, q)
    if why and why.startswith("nema žive cijene"):
        return False
    price, liq, _url, mcap = q[:4]
    sym = q[4] if len(q) > 4 and q[4] else None
    if why:
        con.execute("UPDATE signal_mjera SET status='miss', guard=?, entry_mcap=?, mc_bucket=?, liq=?, "
                    "symbol=COALESCE(symbol, ?), exit_reason='nije kopirljivo' WHERE id=?",
                    (why, mcap, bucket(mcap), liq, sym, rid))
        return True
    con.execute("UPDATE signal_mjera SET guard='ok', entry_ts=?, entry_price=?, entry_mcap=?, mc_bucket=?, liq=?, "
                "symbol=COALESCE(symbol, ?), token_day=?, last_px_ts=?, last_px=? WHERE id=?",
                (int(now), float(price), mcap, bucket(mcap), liq, sym, day(now), int(now), float(price), rid))
    return True


def is_new(con, source, gid, token, now=None):
    """True when (source, gid, token) has no row in the last DEDUP_S (a source asks before it fetches a quote)."""
    try:
        ensure(con)
        now = int(now or time.time())
        return con.execute("SELECT 1 FROM signal_mjera WHERE source=? AND gid=? AND token=? AND seen_ts > ?",
                           (source, str(gid or ""), token, now - DEDUP_S)).fetchone() is None
    except Exception:  # noqa: BLE001
        return False


def record(con, source, gid, wallet, token, their_buy_ts, seen_ts=None, quote=None, members=None, symbol=None):
    """One signal (called by the sources where they SEE the buy, before any cap). Returns the new row id, or None for
    a duplicate ((source, gid, token) within DEDUP_S). Never raises into the caller's loop."""
    try:
        ensure(con)
        now = int(seen_ts or time.time())
        gid = str(gid or wallet or "")
        if con.execute("SELECT 1 FROM signal_mjera WHERE source=? AND gid=? AND token=? AND seen_ts > ?",
                       (source, gid, token, now - DEDUP_S)).fetchone():
            return None
        ms = sorted({str(m) for m in (members or []) if m} | ({wallet} if wallet else set()))
        cur = con.execute("INSERT INTO signal_mjera (source, kind, gid, wallet, members, token, symbol, their_buy_ts, "
                          "seen_ts, delay_s, status, mc_bucket) VALUES (?,?,?,?,?,?,?,?,?,?,'open','?')",
                          (source, LABEL.get(source, source), gid, wallet, json.dumps(ms[:200]), token, symbol,
                           int(their_buy_ts) if their_buy_ts else None, now,
                           int(now - their_buy_ts) if their_buy_ts else None))
        rid = cur.lastrowid
        if quote:
            _enter(con, rid, token, quote, now)
        con.commit()
        return rid
    except Exception as e:  # noqa: BLE001 - a measurement never stops a demo
        print(f"{PREFIX}zapis nije uspio ({type(e).__name__}: {e})", flush=True)
        return None


# ---------- costs and exits ------------------------------------------------------------------------------------------

def rt_floor():
    try:
        from insajderi import prijepumpe
        return float(prijepumpe.rt_floor())
    except Exception:  # noqa: BLE001
        return 0.03


def costs(liq, sol_usd=None):
    """(cost at 0.1 SOL, cost at 0.5 SOL) as fractions, never under the floor."""
    sol = sol_usd or _sol_usd()
    floor = rt_floor()
    out = []
    for s in SIZES_SOL:
        try:
            from trade import cost
            c = cost.round_trip(s * sol, liq)
        except Exception:  # noqa: BLE001
            c = floor
        out.append(max(float(c), floor))
    return tuple(out)


def _sol_usd():
    try:
        from rangedca import trade as rtrade
        return rtrade.sol_usd() or SOL_USD_FALLBACK
    except Exception:  # noqa: BLE001
        return SOL_USD_FALLBACK


def _close(con, rid, entry, liq, px, now, reason, sol_usd=None):
    if reason == "bez cijene" or not px or not entry:
        con.execute("UPDATE signal_mjera SET status='miss', exit_ts=?, exit_reason='bez cijene' WHERE id=?", (int(now), rid))
        return
    g = px / entry - 1
    c1, c5 = costs(liq, sol_usd)
    con.execute("UPDATE signal_mjera SET status='closed', exit_ts=?, exit_price=?, exit_reason=?, ret_gross=?, "
                "cost_01=?, cost_05=?, ret_net_01=?, ret_net_05=? WHERE id=?",
                (int(now), float(px), reason, g, c1, c5, g - c1, g - c5, rid))


def _hype_db():
    try:
        from insajderi import live as ilive
        return ilive._hype_db()
    except Exception:  # noqa: BLE001
        return None


def _sold(hype_db, tok, since, members):
    try:
        from kol import insiders
        return insiders.sold_since(hype_db, tok, since, list(members))
    except Exception:  # noqa: BLE001
        return None


def pass_(con, market_fn=None, hype_db=None, now=None, force=False, max_rows=MAX_ROWS, max_s=MAX_PASS_S,
          clock=time.monotonic, sol_usd=None):
    """Price the open rows (at most max_rows, oldest price first, within max_s): entries of pending rows, the three
    exits. {"priced", "entered", "closed", "missed", "left"}."""
    out = {"priced": 0, "entered": 0, "closed": 0, "missed": 0, "left": 0}
    ensure(con)
    if not force and clock() - _LAST["pass"] < EVERY_S:
        return out
    _LAST["pass"] = clock()
    now = int(now or time.time())
    rows = con.execute("SELECT id, token, members, seen_ts, entry_ts, entry_price, liq, COALESCE(last_px_ts, seen_ts) "
                       "FROM signal_mjera WHERE status='open' ORDER BY COALESCE(last_px_ts, seen_ts) LIMIT ?",
                       (int(max_rows),)).fetchall()
    out["left"] = max(0, con.execute("SELECT COUNT(*) FROM signal_mjera WHERE status='open'").fetchone()[0] - len(rows))
    if not rows:
        return out
    t0 = clock()
    if market_fn is None:
        from league import copy as lcopy
        market_fn = lcopy.market
    mk = {}
    toks = sorted({r[1] for r in rows})
    for i in range(0, len(toks), 30):
        if clock() - t0 > max_s:
            break
        try:
            mk.update(market_fn(toks[i:i + 30]) or {})
        except Exception:  # noqa: BLE001 - no prices this pass: the rows wait
            pass
    hdb = hype_db or _hype_db()
    for rid, tok, ms, seen, ets, epx, liq, last in rows:
        if clock() - t0 > max_s:
            out["left"] += 1
            continue
        q = mk.get(tok)
        if ets is None:   # pending entry
            if q and q[0] and _enter(con, rid, tok, q, now):
                st = con.execute("SELECT status FROM signal_mjera WHERE id=?", (rid,)).fetchone()[0]
                out["entered" if st == "open" else "missed"] += 1
            elif now - seen > ENTRY_WAIT_S:
                con.execute("UPDATE signal_mjera SET status='miss', guard='bez cijene', exit_reason='bez cijene' "
                            "WHERE id=?", (rid,))
                out["missed"] += 1
            continue
        px = q[0] if q and q[0] else None
        if px:
            out["priced"] += 1
            con.execute("UPDATE signal_mjera SET last_px_ts=?, last_px=? WHERE id=?", (now, float(px), rid))
        try:
            members = json.loads(ms or "[]")
        except ValueError:
            members = []
        sold = _sold(hdb, tok, ets, members) if members else None
        reason = None
        if sold and px:
            reason = "prodali su"
        elif px and px <= epx * (1 - STOP):
            reason = "stop"
        elif px and now - ets >= HOLD_S:
            reason = "vrijeme"
        elif not px and now - (last or ets) >= NO_PRICE_S:
            reason = "bez cijene"
        if reason:
            _close(con, rid, epx, liq, px, now, reason, sol_usd)
            out["missed" if reason == "bez cijene" else "closed"] += 1
    con.commit()
    return out


# ---------- the numbers ----------------------------------------------------------------------------------------------

def _rows(con, source=None, gid=None, since=None):
    sql = ("SELECT source, gid, token, token_day, status, guard, mc_bucket, ret_net_01, ret_net_05, ret_gross, delay_s, "
           "entry_ts, exit_ts, exit_reason, seen_ts FROM signal_mjera WHERE 1=1")
    args = []
    if source:
        sql += " AND source=?"
        args.append(source)
    if gid:
        sql += " AND gid=?"
        args.append(gid)
    if since:
        sql += " AND seen_ts >= ?"
        args.append(int(since))
    keys = ("source", "gid", "token", "token_day", "status", "guard", "mc_bucket", "net01", "net05", "gross", "delay",
            "entry_ts", "exit_ts", "exit_reason", "seen_ts")
    try:
        return [dict(zip(keys, r)) for r in con.execute(sql, args)]
    except Exception:  # noqa: BLE001 - no table yet
        return []


def boot_td(rows, key="net01", n=BOOT_N, seed=11):
    """(mean, lo, hi, n_token_days) of the mean net return a trade, the 95 % interval by a bootstrap over TOKEN-DAYS
    (all of one token's rows of one UTC day are drawn together)."""
    by = {}
    for r in rows:
        if r.get(key) is not None:
            by.setdefault((r["token"], r["token_day"]), []).append(r[key])
    xs = [x for v in by.values() for x in v]
    if not xs:
        return None, None, None, 0
    mean = sum(xs) / len(xs)
    cl = list(by.values())
    if len(cl) < 2:
        return mean, None, None, len(cl)
    rng = random.Random(seed)
    ms = []
    for _ in range(int(n)):
        pick = [cl[rng.randrange(len(cl))] for _ in cl]
        ms.append(sum(sum(v) for v in pick) / sum(len(v) for v in pick))
    ms.sort()
    return mean, ms[int(0.025 * len(ms))], ms[min(len(ms) - 1, int(0.975 * len(ms)))], len(cl)


def stats(rows):
    closed = [r for r in rows if r["status"] == "closed"]
    misses = [r for r in rows if r["status"] == "miss"]
    m1, lo, hi, ntd = boot_td(closed, "net01")
    m5, _l, _h, _n = boot_td(closed, "net05", n=1)
    delays = [r["delay"] for r in rows if r.get("delay") is not None]
    return {"signals": len(rows), "measured": len(closed), "misses": len(misses), "open": sum(
        1 for r in rows if r["status"] == "open"), "miss_share": round(len(misses) / len(rows), 3) if rows else None,
        "mean01": m1, "lo": lo, "hi": hi, "token_days": ntd, "mean05": m5,
        "win_share": round(sum(1 for r in closed if (r["net01"] or 0) > 0) / len(closed), 3) if closed else None,
        "delay_med": statistics.median(delays) if delays else None}


def capacity(rows, n_slots, sol=SIZES_SOL[0]):
    """At most n_slots open at once, signals in time order (seen_ts), a slot taken from entry to exit: (n taken,
    mean net %, sum SOL at `sol` per trade) over the closed measured rows."""
    rs = sorted((r for r in rows if r["status"] == "closed" and r.get("entry_ts") and r.get("exit_ts")),
                key=lambda r: (r["seen_ts"], r["entry_ts"]))
    busy, taken = [], []
    for r in rs:
        busy = [e for e in busy if e > r["entry_ts"]]
        if len(busy) < n_slots:
            busy.append(r["exit_ts"])
            taken.append(r["net01"])
    if not taken:
        return 0, None, 0.0
    return len(taken), sum(taken) / len(taken), round(sum(taken) * sol, 4)


def verdict(st, need=MIN_TOKEN_DAYS):
    """Croatian verdict words from the numbers (never hard-coded)."""
    n = st.get("token_days") or 0
    if n < need:
        return f"premalo podataka: n={n} od potrebnih {need} token-dana"
    lo, hi = st.get("lo"), st.get("hi")
    if lo is None or hi is None:
        return "još nije dokazano: nema intervala"
    if lo > 0:
        return "u plusu"
    if hi < 0:
        return "u minusu"
    return "još nije dokazano: interval dira nulu"


def summary(con, now=None, days=30):
    """{"svi", (source, bucket) and (source, "svi") -> stats, "capacity": {N: (n, mean, sol)}, "misses": {reason: n}}."""
    now = int(now or time.time())
    rows = _rows(con, since=now - days * 86400)
    out = {"svi": stats(rows), "by": {}, "capacity": {n: capacity(rows, n) for n in CAPACITY}, "misses": {},
           "ts": now}
    for s in SOURCES:
        rs = [r for r in rows if r["source"] == s]
        out["by"][(s, "svi")] = stats(rs)
        for b in BUCKETS:
            rb = [r for r in rs if r["mc_bucket"] == b]
            if rb:
                out["by"][(s, b)] = stats(rb)
    for r in rows:
        if r["status"] == "miss":
            k = (r["guard"] or r["exit_reason"] or "?").split(" (")[0]
            out["misses"][k] = out["misses"].get(k, 0) + 1
    return out


def per_group(con, now=None, days=30):
    """{(source, gid): {"n", "measured", "mean01"}}: every group's / wallet's own signal quality."""
    now = int(now or time.time())
    out = {}
    for r in _rows(con, since=now - days * 86400):
        d = out.setdefault((r["source"], r["gid"]), {"n": 0, "measured": 0, "_s": 0.0})
        d["n"] += 1
        if r["status"] == "closed" and r["net01"] is not None:
            d["measured"] += 1
            d["_s"] += r["net01"]
    for d in out.values():
        d["mean01"] = d["_s"] / d["measured"] if d["measured"] else None
        d.pop("_s")
    return out


def proof(con=None, source=None, gid=None, now=None):
    """The proof a FUTURE real-money wallet-copy switch must ask (nothing reads it for real money today):
    {"ok", "why", "n" (token-days), "mean", "lo", "hi"}: >= MIN_TOKEN_DAYS measured token-days, mean net at 0.1 SOL
    > 0 and the 95 % token-day interval's low > 0."""
    own = con is None
    if own:
        from league import store as lstore
        con = lstore.connect()
    try:
        st = stats(_rows(con, source, gid))
    finally:
        if own:
            con.close()
    n, m, lo, hi = st["token_days"], st["mean01"], st["lo"], st["hi"]
    if n < MIN_TOKEN_DAYS:
        why = f"premalo podataka: {n} od {MIN_TOKEN_DAYS} token-dana"
    elif m is None or m <= 0:
        why = "prosjek nije u plusu"
    elif lo is None or lo <= 0:
        why = "donja granica intervala nije iznad nule"
    else:
        why = "dokazano"
    return {"ok": why == "dokazano", "why": why, "n": n, "mean": m, "lo": lo, "hi": hi}


def _p(x):
    return "—" if x is None else f"{x * 100:+.1f} %".replace(".", ",")


def _part(st):
    if not st or not st.get("measured"):
        return "n=0"
    ci = f" [{_p(st['lo'])}; {_p(st['hi'])}]" if st.get("lo") is not None else ""
    return f"n={st['measured']}, srednje {_p(st['mean01'])}{ci}"


def line(con, now=None):
    """"mjerenje praćenja novčanika: <signala> signala, <mjereno> mjereno (promašeno x %), otvoreno y; prije pumpe
    15-200M: n=.., srednje .. % [..; ..]; 2-15M: ..; kandidati: ..; bundle: ..; kopija dokazanih: ..; insajderi2: ..;
    uz najviše 5 pozicija: n=.., .. %"."""
    s = summary(con, now)
    a = s["svi"]
    by = s["by"]
    cap = s["capacity"][5]
    miss = f"{a['miss_share'] * 100:.0f} %" if a["miss_share"] is not None else "0 %"
    return (f"{PREFIX}{a['signals']} signala, {a['measured']} mjereno (promašeno {miss}), otvoreno {a['open']}; "
            f"prije pumpe 15-200M: {_part(by.get(('prije_pumpe', '15-200M')))}; "
            f"2-15M: {_part(by.get(('prije_pumpe', '2-15M')))}; kandidati: {_part(by.get(('prije_pumpe_kandidat', 'svi')))}; "
            f"bundle: {_part(by.get(('bundle', 'svi')))}; kopija dokazanih: {_part(by.get(('kopija', 'svi')))}; "
            f"insajderi2: {_part(by.get(('insajderi2', 'svi')))}; uz najviše 5 pozicija: n={cap[0]}, {_p(cap[1])}")


# ---------- step 2: parity with the demos and the switch -----------------------------------------------------------------

DEMO_TABLES = (("pp_trades", "kind", "('prije_pumpe','prije_pumpe_kandidat','bundle')"),
               ("kopija_trades", "'kopija'", None), ("insajderi2_trades", "'insajderi2'", None))


def parity(con):
    """{"n", "median_pp", "word", "by": {source: n}} on the SAME closed trades: a demo row (source + token) and a
    measurement row of that source and token whose entry is within PARITY_WINDOW_S; the demo's gross price return
    (exit / entry - 1 of its league trade) against the measurement's ret_gross. Parity: n >= PARITY_MIN_N and the
    median absolute difference <= PARITY_MAX_PP percentage points."""
    diffs, by = [], {}
    for table, kcol, _ in DEMO_TABLES:
        try:
            rows = con.execute(f"SELECT {kcol}, x.token, t.opened_ts, t.entry_px, t.exit_px FROM {table} x JOIN trades t "
                               f"ON t.id = x.trade_id WHERE t.status='closed' AND t.entry_px > 0 AND t.exit_px > 0"
                               ).fetchall()
        except Exception:  # noqa: BLE001 - a table that does not exist yet
            continue
        for src, tok, opened, ep, xp in rows:
            m = con.execute("SELECT ret_gross FROM signal_mjera WHERE source=? AND token=? AND status='closed' AND "
                            "ABS(entry_ts - ?) <= ? ORDER BY ABS(entry_ts - ?) LIMIT 1",
                            (src, tok, opened, PARITY_WINDOW_S, opened)).fetchone()
            if m and m[0] is not None:
                diffs.append(abs((xp / ep - 1) - m[0]) * 100)
                by[src] = by.get(src, 0) + 1
    med = statistics.median(diffs) if diffs else None
    if len(diffs) < PARITY_MIN_N:
        word = "premalo"
    elif med <= PARITY_MAX_PP:
        word = "slaže se"
    else:
        word = "ne slaže se"
    return {"n": len(diffs), "median_pp": med, "word": word, "by": by}


def parity_line(p):
    med = "—" if p["median_pp"] is None else f"{p['median_pp']:.2f}".replace(".", ",")
    return f"mjerenje vs demo: upareno {p['n']}, medijan razlike {med} pp: {p['word']}"


def mode(tcon=None):
    """The owner's setting (trade.db settings MODE_KEY): auto (default) / demo / mjera. Read-only; never raises."""
    import os
    import sqlite3
    try:
        own = tcon is None
        if own:
            from trade import settings
            if not os.path.exists(settings.DB):
                return "auto"
            tcon = sqlite3.connect(f"file:{settings.DB}?mode=ro", uri=True, timeout=5)
        try:
            r = tcon.execute("SELECT v FROM settings WHERE k=?", (MODE_KEY,)).fetchone()
        finally:
            if own:
                tcon.close()
        v = json.loads(r[0]) if r else None
        return v if v in MODES else "auto"
    except Exception:  # noqa: BLE001
        return "auto"


def switched(con):
    """The stored flip ({"ts", "n", "median_pp"}) once parity held in auto, else None."""
    try:
        ensure(con)
        return _kv(con, "prebaceno")
    except Exception:  # noqa: BLE001
        return None


def demo_entries_ok(con, tcon=None):
    """False when the three wallet-following demos must not open NEW trades: only the owner's own mode "mjera".
    23.11. (vlasnik: demo never stops): "auto" after parity held (switched()) no longer holds them; production had
    stood still since 21.11. 16:07 UTC because of it. Their open trades exit by their own rules either way."""
    return mode(tcon) != "mjera"


def check_switch(con, now=None, log=print):
    """In "auto": once parity holds, remember the flip (once) and say so with the numbers. The parity result."""
    p = parity(con)
    if mode() == "auto" and p["word"] == "slaže se" and not switched(con):
        _kv(con, "prebaceno", {"ts": int(now or time.time()), "n": p["n"], "median_pp": p["median_pp"]})
        con.commit()
        log(f"{PREFIX}mjerenje POTVRĐENO na istim tradeovima (način auto): {parity_line(p)}; demo tradeovi praćenja "
            "novčanika idu dalje usporedno (nalog vlasnika 23.11.: demo nikad ne staje)")
    return p


def tick(con, market_fn=None, now=None, log=print):
    """league/auto.loop: one bounded pass; once a UTC day the summary line, the parity line and the switch check."""
    out = pass_(con, market_fn, now=now)
    t = int(now or time.time())
    d = t // 86400
    if _LAST.get("line_day") != d:
        _LAST["line_day"] = d
        try:
            log(line(con, t))
            p = check_switch(con, t, log)
            log(parity_line(p))
            _kv(con, "summary", {"ts": t, "line": line(con, t)})
            con.commit()
        except Exception as e:  # noqa: BLE001
            log(f"{PREFIX}dnevna linija ({type(e).__name__}: {e})")
    return out
