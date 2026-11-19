"""Povijest novčanika (19.11., vlasnik: "dok je pravi novac isključen ... povijesni profit i gubitak za sve novčanike
... želim da se svi odabrani novčanici povijesno analiziraju, nađu im se transakcije, da se analizira što više
novčanika. Posebno rani kupci tokena koji su skočili").

A queue of wallets whose swap history is read from Helius (the scorer's own call: run_wallets.score_one, i.e.
wallets/rpc.wallet_swaps = getTransactionsForAddress, 10 credits a page of 100) and scored by the EXISTING scorer
(wallets/pnl.py), stored in wallets.db's own tables (wallets, wallet_trades, wallet_pnl, helius_credits method
"povijest"), so rang / dokazani / kopija pick them up unchanged.

Queue (povijest_queue, rebuilt every pass from what the other jobs stored; reads only), best first:
  0 prije_pumpe            members of a CONFIRMED "kupuje prije pumpe" group (insajderi.db i2_pp)
  1 prije_pumpe_kandidat   members of an unconfirmed prije_pumpe group, then of a "kandidat" group
  2 bundle                 members of a bundle (i2_bundle)
  3 rani_pumpa15           early buyers that SOLD into a pumpa15 event (i2_part bought_before and sold_into)
  4 rani_pumpa2            the same for pumpa2 events
  5 rani_bez_prodaje       early buyers of pump events that did not sell into them (pumpa15 first)
  6 holder                 "veliki holder s dugom poviješću" (veliki_holderi, built here from holderi.db)
  7 registar               the old registry's never-scored wallets with a sighting worth a score (wstore.SCORE_ROLES)
  skipped                  relayers (i2_part owner "relayer:"), wallets.db labels cex / mev / bot / rugger / izbačen,
                           a scored bot (stats.bot), exchanges / pools / programs / burn among holderi.db's classified
                           top holders (snap cls exchange / lp / burn) and its exchange registry (burze_dodane)
  fresh                    scored within refresh_d (7) days: not read again; older: score_one reads ONLY the new
                           signatures (since last_tx_ts, oldest first), as osvjezi does

Budget (wallets/config.json "povijest"): kredita_dan Helius credits a UTC day (method "povijest"), never past the
wallet tool's monthly share (run_wallets MONTHLY x SHARE, every wallet method together); najvise_stranica pages a
wallet (a first look: one page first, more only for a slow or profitable trader, rpc.wallet_swaps; a recheck at most
najvise_stranica + 2 pages), so one hyperactive wallet costs at most 10 x (pages + 2) credits; dan_udio of the day
cap for the day passes together (the night gets the rest); one wall-clock deadline a pass (pass_max_s day / night).
One line a pass:
  "novčanici povijest: obrađeno <n> (red <left>: prije pumpe <a>, rani kupci <b>, holderi <c>), u plusu <k> od
   <n ocijenjenih>, Helius <used>/<cap>, trajanje <s> s"

Veliki holderi (holders(), task 2 of 19.11.): holderi.db holder_pos (the top holders of the established midcaps
without pools, burn and exchanges, with the FIRST inflow of that token from the token account's oldest transactions:
holderi/profit.positions, its own Helius cap) and snap (every classified top-holder snapshot, kept 45 days) -> the
wallets holding >= holder_min_usd (50k) of a midcap for >= holder_min_days (30), not exchange / pool / program /
burn / team, the token's MC tier from the newest profile (15-200M first, then 2-15M). Stored in wallets.db
veliki_holderi; first_ts never moves later (the accumulation outlives snap's 45-day pruning). No paid call here.
"""
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "novčanici povijest: "
METHOD = "povijest"
DEFAULT = {"kredita_dan": 60000, "najvise_stranica": 5, "pass_max_s": {"day": 300, "night": 3600}, "refresh_d": 7,
           "lookback_d": 90, "dan_udio": 0.4, "holder_min_usd": 50000, "holder_min_days": 30, "red_max": 20000}
SOURCES = ("prije_pumpe", "prije_pumpe_kandidat", "bundle", "rani_pumpa15", "rani_pumpa2", "rani_bez_prodaje", "holder",
           "registar")
GROUP = {"prije_pumpe": "prije pumpe", "prije_pumpe_kandidat": "prije pumpe", "bundle": "prije pumpe",
         "rani_pumpa15": "rani kupci", "rani_pumpa2": "rani kupci", "rani_bez_prodaje": "rani kupci",
         "holder": "holderi", "registar": "registar"}
SKIP_LABELS = {"cex", "mev", "bot", "rugger", "izbačen"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS povijest_queue (wallet TEXT PRIMARY KEY, source TEXT, prio INTEGER, detail TEXT,
    added INTEGER, updated INTEGER, done_ts INTEGER, status TEXT, credits INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS povijest_queue_prio ON povijest_queue (prio, added);
CREATE TABLE IF NOT EXISTS povijest_runs (ts INTEGER, kind TEXT, n INTEGER, scored INTEGER, profitable INTEGER,
    credits INTEGER, secs REAL, cut INTEGER, line TEXT);
CREATE TABLE IF NOT EXISTS veliki_holderi (wallet TEXT, mint TEXT, symbol TEXT, tier TEXT, mcap REAL, value_usd REAL,
    pct REAL, first_ts INTEGER, held_days REAL, src TEXT, updated INTEGER, PRIMARY KEY (wallet, mint));
"""


def config(path=None):
    c = dict(DEFAULT)
    try:
        with open(path or os.path.join(ROOT, "wallets", "config.json"), encoding="utf-8") as f:
            c.update((json.load(f) or {}).get("povijest") or {})
    except (OSError, ValueError):
        pass
    return c


def ensure(con):
    con.executescript(SCHEMA)


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def paths(**over):
    p = {"insajderi_db": None, "holderi_db": None}
    try:
        from insajderi import store as istore
        p["insajderi_db"] = istore.db_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        from holderi import store as hstore
        p["holderi_db"] = hstore.db_path()
    except Exception:  # noqa: BLE001
        pass
    p.update({k: v for k, v in over.items() if v is not None})
    return p


# ---------- veliki holderi ---------------------------------------------------------------------------------------------

def tier_of(mcap):
    if mcap is None:
        return None
    if 15e6 <= mcap <= 200e6:
        return "15-200M"
    if 2e6 <= mcap < 15e6:
        return "2-15M"
    return None


def holders(con, c, now, holderi_db=None):
    """Rebuild veliki_holderi from holderi.db (read-only). -> {"n", "tokens", "since", "rows_pos", "rows_snap"}."""
    ensure(con)
    hc = _ro(holderi_db)
    out = {"n": 0, "tokens": 0, "since": None, "rows_pos": 0, "rows_snap": 0}
    if hc is None:
        return out
    try:
        prof = {}
        for m, ts, sym, mc in _q(hc, "SELECT p.mint, p.ts, p.symbol, p.mcap FROM profile p JOIN (SELECT mint, MAX(ts) mts "
                                     "FROM profile GROUP BY mint) x ON x.mint = p.mint AND x.mts = p.ts"):
            prof[m] = (sym, mc)
        first_snap = {(o, m): ts for o, m, ts in _q(hc, "SELECT owner, mint, MIN(ts) FROM snap WHERE cls NOT IN "
                                                        "('lp', 'burn', 'exchange', 'team') GROUP BY owner, mint")}
        out["since"] = (_q(hc, "SELECT MIN(ts) FROM snap") or [(None,)])[0][0]
        out["rows_snap"] = len(first_snap)
        latest = {}
        for m, ts in _q(hc, "SELECT mint, MAX(ts) FROM snap GROUP BY mint"):
            for o, pct, cls in _q(hc, "SELECT owner, pct, cls FROM snap WHERE mint = ? AND ts = ?", (m, ts)):
                latest[(o, m)] = (pct, cls)
        pos = {(w, m): (v, f, pct) for w, m, v, f, pct in _q(hc, "SELECT wallet, mint, value_usd, first_ts, pct FROM "
                                                                    "holder_pos")}
        out["rows_pos"] = len(pos)
    finally:
        hc.close()
    keys = set(pos) | {k for k in latest if latest[k][1] not in ("lp", "burn", "exchange", "team")}
    old = {(w, m): f for w, m, f in con.execute("SELECT wallet, mint, first_ts FROM veliki_holderi")}
    rows = []
    for (w, m) in keys:
        sym, mc = prof.get(m, (None, None))
        tier = tier_of(mc)
        if not tier:
            continue
        lp = latest.get((w, m))
        if lp and lp[1] in ("lp", "burn", "exchange", "team"):
            continue
        v, f_pos, pct_pos = pos.get((w, m), (None, None, None))
        pct = lp[0] if lp else pct_pos
        value = v if v is not None else (mc * pct / 100 if mc and pct is not None else None)
        firsts = [x for x in (f_pos, first_snap.get((w, m)), old.get((w, m))) if x]
        first = min(firsts) if firsts else None
        src = "holder_pos" if f_pos else "snap"
        if value is None or first is None:
            continue
        held = (now - first) / 86400
        if value >= float(c["holder_min_usd"]) and held >= float(c["holder_min_days"]):
            rows.append((w, m, sym, tier, mc, round(value, 2), pct, int(first), round(held, 1), src, int(now)))
        elif (w, m) in old:   # keeps its first_ts (the accumulation) even while under the floor
            con.execute("UPDATE veliki_holderi SET value_usd=?, updated=? WHERE wallet=? AND mint=?",
                        (value, int(now), w, m))
    con.executemany("INSERT OR REPLACE INTO veliki_holderi VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    out["n"] = len({r[0] for r in rows})
    out["tokens"] = len({r[1] for r in rows})
    return out


def holders_list(con, limit=100):
    ensure(con)
    keys = ("wallet", "mint", "symbol", "tier", "mcap", "value_usd", "pct", "first_ts", "held_days", "src")
    return [dict(zip(keys, r)) for r in con.execute(
        f"SELECT {', '.join(keys)} FROM veliki_holderi WHERE held_days >= ? ORDER BY (tier = '15-200M') DESC, "
        "value_usd DESC LIMIT ?", (DEFAULT["holder_min_days"], int(limit)))]


def holders_md(con, info=None, now=None):
    now = int(now or time.time())
    rows = holders_list(con, 200)
    L = ["# Veliki holderi s dugom poviješću", "",
         f"{time.strftime('%d.%m.%Y. %H:%M', time.gmtime(now))} UTC. Statistika, ne optužba: novčanici koji drže barem "
         f"${DEFAULT['holder_min_usd']:,.0f} midcapa (15-200M prvo, zatim 2-15M) barem {DEFAULT['holder_min_days']} dana; "
         "bez burzi, poolova, programa i tima.", ""]
    if info:
        since = info.get("since")
        L += [f"Izvor: holderi.db (holder_pos: prvi ulaz tokena iz najstarijih transakcija token računa; snap: snimke "
              f"top holdera, čuvaju se 45 dana, najstarija {time.strftime('%d.%m.%Y.', time.gmtime(since)) if since else '—'}). "
              f"Pozicija s poznatim prvim ulazom {info.get('rows_pos', 0)}, parova iz snimki {info.get('rows_snap', 0)}.", ""]
    L += ["| novčanik | token | MC razred | vrijednost $ | % ponude | drži dana | izvor |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['wallet'][:4]}…{r['wallet'][-4:]} | {r['symbol'] or r['mint'][:6]} | {r['tier']} | "
                 f"{(r['value_usd'] or 0):,.0f} | {r['pct'] if r['pct'] is not None else '—'} | {r['held_days']:.0f} | "
                 f"{r['src']} |")
    if not rows:
        L.append("| — | | | | | | |")
    return "\n".join(L) + "\n"


# ---------- the queue --------------------------------------------------------------------------------------------------

def skipped(con, p, wallets):
    """{wallet: why} of the wallets never read: relayers, bad labels, scored bots, exchanges / pools / programs."""
    out = {}
    ws = sorted(wallets)
    for i in range(0, len(ws), 400):
        ch = ws[i:i + 400]
        for w, lab, stats in con.execute(f"SELECT wallet, labels, stats FROM wallets WHERE wallet IN "
                                         f"({','.join('?' * len(ch))})", ch):
            bad = set(json.loads(lab or "[]")) & SKIP_LABELS
            if bad:
                out[w] = "oznaka " + ",".join(sorted(bad))
            elif stats and json.loads(stats).get("bot"):
                out[w] = "bot (ocjena)"
    hc = _ro(p.get("holderi_db"))
    if hc is not None:
        for (o,) in _q(hc, "SELECT DISTINCT owner FROM snap WHERE cls IN ('exchange', 'lp', 'burn')"):
            if o in wallets:
                out.setdefault(o, "burza / pool / program")
        for (a,) in _q(hc, "SELECT address FROM burze_dodane"):
            if a in wallets:
                out.setdefault(a, "burza")
        hc.close()
    return out


def sources(con, p, c):
    """[(wallet, source)] in priority order (a wallet keeps its best source)."""
    out, seen = [], set()

    def add(ws, src):
        for w in ws:
            if w and w not in seen and not str(w).startswith("relayer:"):
                seen.add(w)
                out.append((w, src))
    ic = _ro(p.get("insajderi_db"))
    if ic is not None:
        def members(sql):
            ws = []
            for (m,) in _q(ic, sql):
                try:
                    ws += json.loads(m or "[]")
                except ValueError:
                    continue
            return ws
        add(members("SELECT members FROM i2_pp WHERE cls = 'prije_pumpe' AND confirmed_ts IS NOT NULL "
                    "ORDER BY n_pumps15 DESC, n_tokens DESC"), "prije_pumpe")
        add(members("SELECT members FROM i2_pp WHERE (cls = 'prije_pumpe' AND confirmed_ts IS NULL) OR cls = 'kandidat' "
                    "ORDER BY (cls = 'prije_pumpe') DESC, n_pumps15 DESC, n_tokens DESC"), "prije_pumpe_kandidat")
        add(members("SELECT members FROM i2_bundle ORDER BY n_pumps15 DESC, n_pumps DESC"), "bundle")
        rel = {w for (w,) in _q(ic, "SELECT DISTINCT wallet FROM i2_part WHERE owner LIKE 'relayer:%'")}
        for tier, src in (("pumpa15", "rani_pumpa15"), ("pumpa2", "rani_pumpa2")):
            add([w for (w,) in _q(ic, "SELECT p.wallet FROM i2_part p JOIN i2_events e ON e.eid = p.eid WHERE e.tier = ? "
                                      "AND p.bought_before = 1 AND p.sold_into = 1 GROUP BY p.wallet "
                                      "ORDER BY COUNT(*) DESC, MAX(e.t0) DESC", (tier,)) if w not in rel], src)
        add([w for (w,) in _q(ic, "SELECT p.wallet FROM i2_part p JOIN i2_events e ON e.eid = p.eid WHERE e.tier IS NOT "
                                  "NULL AND p.bought_before = 1 AND p.sold_into = 0 GROUP BY p.wallet "
                                  "ORDER BY MAX(e.tier = 'pumpa15') DESC, COUNT(*) DESC") if w not in rel],
            "rani_bez_prodaje")
        ic.close()
    add([w for (w,) in con.execute("SELECT wallet FROM veliki_holderi GROUP BY wallet ORDER BY MAX(tier = '15-200M') "
                                   "DESC, MAX(value_usd) DESC")], "holder")
    from wallets import store as wstore
    roles = ",".join("?" * len(wstore.SCORE_ROLES))
    add([w for (w,) in con.execute(f"SELECT wallet FROM wallets w WHERE scored_at IS NULL AND EXISTS (SELECT 1 FROM "
                                   f"wallet_sightings s WHERE s.wallet = w.wallet AND s.role IN ({roles})) "
                                   f"ORDER BY priority DESC LIMIT ?", (*wstore.SCORE_ROLES, int(c["red_max"])))],
        "registar")
    return out[:int(c["red_max"])]


def build_queue(con, p, c, now):
    """Rewrite povijest_queue from sources() minus skipped(). -> {source: n due}."""
    ensure(con)
    src = sources(con, p, c)
    skip = skipped(con, p, {w for w, _s in src})
    old = {w: (a, d, st, cr) for w, a, d, st, cr in con.execute("SELECT wallet, added, done_ts, status, credits FROM "
                                                                "povijest_queue")}
    con.execute("DELETE FROM povijest_queue")
    rows = []
    for w, s in src:
        a, d, st, cr = old.get(w, (int(now), None, None, 0))
        status = "preskočen: " + skip[w] if w in skip else (st if st and not st.startswith("preskočen") else "čeka")
        rows.append((w, s, SOURCES.index(s), None, a, int(now), d, status, cr or 0))
    con.executemany("INSERT INTO povijest_queue VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return rows


def due(con, c, now, limit=None):
    """[(wallet, source)] to read now, best first: not skipped, not scored within refresh_d."""
    fresh = int(now) - int(float(c["refresh_d"]) * 86400)
    sql = ("SELECT q.wallet, q.source FROM povijest_queue q LEFT JOIN wallets w ON w.wallet = q.wallet WHERE "
           "q.status NOT LIKE 'preskočen%' AND (w.scored_at IS NULL OR w.scored_at < ?) ORDER BY q.prio, "
           "(w.scored_at IS NOT NULL), q.added")
    rows = con.execute(sql, (fresh,)).fetchall()
    return rows[:limit] if limit else rows


# ---------- the budget -------------------------------------------------------------------------------------------------

def _day0(now):
    return int(now) - int(now) % 86400


def credits_today(con, now):
    return con.execute("SELECT COALESCE(SUM(credits), 0) FROM helius_credits WHERE method = ? AND ts >= ?",
                       (METHOD, _day0(now))).fetchone()[0]


def month_left(con, now):
    import datetime as dt
    d = dt.datetime.fromtimestamp(int(now), dt.timezone.utc)
    ms = int(dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp())
    try:
        import run_wallets as rw
        cap = rw.MONTHLY * rw.SHARE
    except Exception:  # noqa: BLE001
        cap = 10_000_000 * 0.25
    return cap - con.execute("SELECT COALESCE(SUM(credits), 0) FROM helius_credits WHERE ts >= ?", (ms,)).fetchone()[0]


def budget(con, c, now, kind):
    """Credits this pass may spend: the day cap left (a day pass: at most dan_udio of the cap for all day passes of
    the UTC day), never past the monthly wallet share."""
    used = credits_today(con, now)
    cap = int(c["kredita_dan"])
    left = cap - used
    if kind == "day":
        left = min(left, int(cap * float(c["dan_udio"])) - con.execute(
            "SELECT COALESCE(SUM(credits), 0) FROM povijest_runs WHERE kind = 'day' AND ts >= ?",
            (_day0(now),)).fetchone()[0])
    return max(0, min(left, int(month_left(con, now))))


# ---------- the pass ---------------------------------------------------------------------------------------------------

class Clock:
    """One wall-clock deadline a pass (fn: time.monotonic; tests pass a fake)."""

    def __init__(self, max_s, fn=None):
        self.fn = fn or time.monotonic
        self.t0, self.max_s = self.fn(), max_s

    def elapsed(self):
        return self.fn() - self.t0

    def over(self):
        return self.max_s is not None and self.elapsed() >= self.max_s


def run(kind="day", now=None, con=None, cfg=None, score=None, clock=None, log=print, **over):
    """One pass. score(con, wallet, max_pages, method, lookback_d) -> (stats, tier, positions) (default:
    run_wallets.score_one). -> the run dict (also povijest_runs)."""
    from wallets import store as wstore
    now = int(now or time.time())
    c = cfg or config()
    p = paths(**over)
    own = con is None
    con = con or wstore.connect()
    ensure(con)
    clk = Clock(float((c.get("pass_max_s") or {}).get(kind) or 300), clock)
    try:
        hinfo = holders(con, c, now, p.get("holderi_db"))
        build_queue(con, p, c, now)
        todo = due(con, c, now)
        if score is None:
            import run_wallets as rw

            def score(con_, w, pages, method, lookback_d):
                return rw.score_one(con_, w, pages, now=now, method=method, lookback_d=lookback_d)
        left = budget(con, c, now, kind)
        per = 10 * (int(c["najvise_stranica"]) + 2)
        n = n_scored = n_plus = spent = 0
        cut = False
        for w, src in todo:
            if clk.over():
                cut = True
                break
            if spent + per > left:
                break
            before = con.execute("SELECT COALESCE(SUM(credits), 0) FROM helius_credits WHERE wallet = ? AND method = ?",
                                 (w, METHOD)).fetchone()[0]
            try:
                s, _t, _pos = score(con, w, int(c["najvise_stranica"]), METHOD, int(c["lookback_d"]))
            except Exception as e:  # noqa: BLE001 - one wallet never stops the rest
                con.execute("UPDATE povijest_queue SET status=?, done_ts=? WHERE wallet=?",
                            (f"greška: {type(e).__name__}"[:60], now, w))
                n += 1
                continue
            got = con.execute("SELECT COALESCE(SUM(credits), 0) FROM helius_credits WHERE wallet = ? AND method = ?",
                              (w, METHOD)).fetchone()[0] - before
            spent += got
            n += 1
            if s and s.get("closed"):
                n_scored += 1
                n_plus += int((s.get("realized_sol") or 0) > 0)
            con.execute("UPDATE povijest_queue SET status='ocijenjen', done_ts=?, credits=credits+? WHERE wallet=?",
                        (now, got, w))
            con.commit()
        rest = due(con, c, now)
        by = {}
        for _w, src in rest:
            g = GROUP[src]
            by[g] = by.get(g, 0) + 1
        secs = round(clk.elapsed(), 1)
        used = credits_today(con, now)
        ln = (f"{PREFIX}obrađeno {n} (red {len(rest)}: prije pumpe {by.get('prije pumpe', 0)}, rani kupci "
              f"{by.get('rani kupci', 0)}, holderi {by.get('holderi', 0)}), u plusu {n_plus} od {n_scored} ocijenjenih, "
              f"Helius {used:,}/{int(c['kredita_dan']):,}, trajanje {secs:.0f} s"
              + (f"; prekinuto na vremenskoj granici {clk.max_s:.0f} s" if cut else ""))
        con.execute("INSERT INTO povijest_runs VALUES (?,?,?,?,?,?,?,?,?)",
                    (now, kind, n, n_scored, n_plus, spent, secs, int(cut), ln))
        con.commit()
        log(ln)
        try:
            os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
            with open(os.path.join(ROOT, "output", "veliki_holderi.md"), "w", encoding="utf-8") as f:
                f.write(holders_md(con, hinfo, now))
        except OSError:
            pass
        return {"n": n, "scored": n_scored, "profitable": n_plus, "credits": spent, "left": len(rest), "by": by,
                "secs": secs, "cut": cut, "holders": hinfo, "line": ln}
    finally:
        if own:
            con.close()


def status(path=None, now=None):
    """For the UI (read-only): {"queue": {source: n waiting}, "skipped": n, "scored": n wallets with a score,
    "scored_povijest": n read by this job, "profitable": n of those with realized SOL > 0, "credits_today": int,
    "cap_day": int, "last": {"ts", "kind", "n", "scored", "profitable", "credits", "secs", "cut", "line"} or None,
    "holders": n wallets in veliki_holderi}. Empty numbers before the first pass."""
    from wallets import store as wstore
    now = int(now or time.time())
    c = config()
    out = {"queue": {s: 0 for s in SOURCES}, "skipped": 0, "scored": 0, "scored_povijest": 0, "profitable": 0,
           "credits_today": 0, "cap_day": int(c["kredita_dan"]), "last": None, "holders": 0}
    con = _ro(path or wstore.DB)
    if con is None:
        return out
    try:
        fresh = now - int(float(c["refresh_d"]) * 86400)
        for s, n in _q(con, "SELECT q.source, COUNT(*) FROM povijest_queue q LEFT JOIN wallets w ON w.wallet = q.wallet "
                            "WHERE q.status NOT LIKE 'preskočen%' AND (w.scored_at IS NULL OR w.scored_at < ?) "
                            "GROUP BY q.source", (fresh,)):
            out["queue"][s] = n
        out["skipped"] = (_q(con, "SELECT COUNT(*) FROM povijest_queue WHERE status LIKE 'preskočen%'") or [(0,)])[0][0]
        out["scored"] = (_q(con, "SELECT COUNT(*) FROM wallets WHERE scored_at IS NOT NULL") or [(0,)])[0][0]
        rows = _q(con, "SELECT w.stats FROM povijest_queue q JOIN wallets w ON w.wallet = q.wallet WHERE q.status = "
                       "'ocijenjen' AND w.stats IS NOT NULL")
        out["scored_povijest"] = len(rows)
        out["profitable"] = sum(1 for (s,) in rows if (json.loads(s or "{}").get("realized_sol") or 0) > 0)
        out["credits_today"] = (_q(con, "SELECT COALESCE(SUM(credits), 0) FROM helius_credits WHERE method = ? AND "
                                        "ts >= ?", (METHOD, _day0(now))) or [(0,)])[0][0]
        last = _q(con, "SELECT ts, kind, n, scored, profitable, credits, secs, cut, line FROM povijest_runs ORDER BY ts "
                       "DESC, rowid DESC LIMIT 1")
        if last:
            out["last"] = dict(zip(("ts", "kind", "n", "scored", "profitable", "credits", "secs", "cut", "line"), last[0]))
            out["last"]["cut"] = bool(out["last"]["cut"])
        out["holders"] = (_q(con, "SELECT COUNT(DISTINCT wallet) FROM veliki_holderi") or [(0,)])[0][0]
    finally:
        con.close()
    return out


def group_history(members, wallet_db=None):
    """19.11. (feed back, REPORT ONLY: never a selection rule): the members' own scored history -> {"n_members",
    "n_scored", "realized_sol", "profitable_share"}."""
    from wallets import store as wstore
    con = _ro(wallet_db or wstore.DB)
    out = {"n_members": len(members), "n_scored": 0, "realized_sol": 0.0, "profitable_share": None}
    if con is None or not members:
        if con is not None:
            con.close()
        return out
    try:
        ms = sorted(members)
        rows = []
        for i in range(0, len(ms), 400):
            ch = ms[i:i + 400]
            rows += _q(con, f"SELECT stats FROM wallets WHERE stats IS NOT NULL AND wallet IN ({','.join('?' * len(ch))})",
                       ch)
    finally:
        con.close()
    real = [json.loads(s or "{}").get("realized_sol") or 0.0 for (s,) in rows]
    out["n_scored"] = len(real)
    out["realized_sol"] = round(sum(real), 3)
    out["profitable_share"] = round(sum(1 for x in real if x > 0) / len(real), 3) if real else None
    return out
