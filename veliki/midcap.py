"""Midcap data collector (15.11. navečer, vlasnik: "Sve resurse prebaci na midcapove ... 2M do 200M ... sve skupi,
posebno TRENDING tokene na DexScreeneru. Kreni s njima, osvježavaj i troši što više resursa da skupimo što više podataka").
Runs only while the owner switch fokus_midcap is on (ops/fokus.py); off: the pass ends at once (no database, no network).

One short process a pass (start.sh: run_veliki.py midcap every MIDCAP every_s, 90 s), low priority, outside the heavy lock:

  discover   every discover_every_s (15 min): DexScreener top / latest boosts, latest token profiles, community takeovers
             (free, 60/min), GeckoTerminal trending pools 1h + 24h (gt_trend_pages each, the shared GT budget), Jupiter's
             toptraded / toptrending / toporganicscore lists (free), the veliki list, dugo.db; new mints are candidates
  snapshot   EVERY pass: DexScreener /tokens (free, 30 mints a request, ~20 requests for 600 tokens) for the members and
             the new candidates; grouped by mint (the deepest pool, fake-liquidity copies refused: veliki/universe.group
             and data_judge, MC data_min_mcap-data_max_mcap 2M-200M, bonded only); one compact row per member per pass
             (snap: price, MC, liquidity, volume m5/h1/h6/h24, buys/sells m5/h1/h24, price change m5/h1/h6/h24)
  candles    GeckoTerminal 15m / 1h / 1d (veliki/store.fill, the same tables as veliki.db) within gt_pass a pass and
             gt_day a day, by 24 h volume: the top_n every c15_every_h_top (1 h), the rest every c15_every_h (6 h); 1h
             every 6 h, daily every 24 h; first fill ~31 d 15m, 41 d 1h, 180 d 1d
  safety     RugCheck (free) top-10 share, holders, LP locked, insiders, dev %, authorities, danger flags:
             safety_pass tokens a pass, each every safety_every_h (24 h), by volume
  X          scan/xmom (twitterapi.io): the trending members first, x_pass a pass, each every x_every_min, inside the
             scanner's own day cap (scan/config.json x_usd_day, $0.30; the scanner itself is off under the switch)
  priority   veliki/prioritet.py on every pass (kv prio: the live loop's order), the top 10 in the log every hour

Membership: a mint joins when data_judge passes; it leaves after leave_after_h (24 h) out of range or unseen; at most
data_max_tokens (600) members, the largest 24 h volume first. Retention: snap rows older than snap_keep_days (14 d).
midcap.db (MIDCAP_DB, else DATA_DIR/midcap.db): ~80 B a snap row: 600 tokens x 960 passes a day ~ 45 MB a day at most,
~0.6 GB at the 14-day cap; the hourly line logs the measured MB a day.
"""
import json
import os
import sqlite3
import time

from veliki import store, universe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "midcap: "
SOURCES_TEXT = ("DexScreener boost top/latest, profili, CTO; GeckoTerminal trending 1h/24h; Jupiter toptraded/"
                "toptrending/toporganicscore; veliki lista; dugo.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (mint TEXT PRIMARY KEY, id INTEGER UNIQUE, symbol TEXT, pool TEXT, dex TEXT,
    mcap REAL, liq REAL, vol24 REAL, created_ts INTEGER, first_ts INTEGER, last_ts INTEGER, out_since INTEGER,
    src TEXT, trend INTEGER, member INTEGER DEFAULT 0, why TEXT);
CREATE TABLE IF NOT EXISTS snap (id INTEGER, ts INTEGER, px REAL, mc INTEGER, liq INTEGER, v5 INTEGER, v1h INTEGER,
    v6 INTEGER, v24 INTEGER, b5 INTEGER, s5 INTEGER, b1h INTEGER, s1h INTEGER, b24 INTEGER, s24 INTEGER, c5 REAL,
    c1h REAL, c6 REAL, c24 REAL, PRIMARY KEY (id, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS safety (mint TEXT, ts INTEGER, top10 REAL, holders INTEGER, lp_locked REAL, insiders REAL,
    dev_pct REAL, mint_auth INTEGER, freeze_auth INTEGER, danger TEXT, PRIMARY KEY (mint, ts));
CREATE TABLE IF NOT EXISTS fill_ts (mint TEXT, tbl TEXT, ts INTEGER, PRIMARY KEY (mint, tbl));
CREATE TABLE IF NOT EXISTS xmom_ts (mint TEXT PRIMARY KEY, ts INTEGER);
CREATE TABLE IF NOT EXISTS c15 (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS c1h (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS c1d (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (token, ts));
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
DEFAULTS = {"every_s": 90, "discover_every_s": 900, "leave_after_h": 24, "gt_day": 4000, "gt_pass": 40,
            "gt_trend_pages": 2, "top_n": 100, "c15_every_h_top": 1, "c15_every_h": 6, "c1h_every_h": 6,
            "c1d_every_h": 24, "safety_every_h": 24, "safety_pass": 4, "x_pass": 2, "x_every_min": 120,
            "snap_keep_days": 14, "prio_top": 10}
FETCH = {}   # tests: "dex_tokens" (mints) -> pairs, "discover" () -> {mint: {src: rank}}, "rugcheck" (mint) -> report,
_MEM = {"ts": 0.0, "rows": []}


def config(path=None):
    c = dict(DEFAULTS)
    c.update(universe.config(path))
    c["min_mcap"], c["max_mcap"] = universe.DATA_MIN_MCAP, universe.DATA_MAX_MCAP
    c["min_liq"], c["max_tokens"] = universe.DATA_MIN_LIQ, int(c.get("data_max_tokens") or 600)
    return c


def db_path():
    if os.environ.get("MIDCAP_DB"):
        return os.environ["MIDCAP_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "midcap.db")
    return os.path.join(ROOT, "midcap.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM tokens LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    try:
        return json.loads(r[0]) if r else default
    except (TypeError, ValueError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


def members(path=None, max_age_s=60):
    """[{"mint", "symbol", "mcap", "liq", "vol24", "trend", "pool", "src"}] of the current members, by 24 h volume
    (read-only, cached max_age_s)."""
    if path is None and _MEM["ts"] and time.monotonic() - _MEM["ts"] < max_age_s:
        return list(_MEM["rows"])
    con = ro(path)
    rows = []
    if con is not None:
        try:
            cur = con.execute("SELECT mint, symbol, mcap, liq, vol24, trend, pool, src FROM tokens WHERE member=1 "
                              "ORDER BY vol24 DESC")
            rows = [dict(zip(("mint", "symbol", "mcap", "liq", "vol24", "trend", "pool", "src"), r)) for r in cur]
        except sqlite3.Error:
            rows = []
        finally:
            con.close()
    if path is None:
        _MEM.update(ts=time.monotonic(), rows=rows)
    return list(rows)


# ---------- sources ------------------------------------------------------------------------------------------------------

def discover(c, log=print):
    """{mint: {source: rank}} of every free list (see the module text). Never raises."""
    if "discover" in FETCH:
        return FETCH["discover"]()
    out = {}

    def add(d, name=None):
        for m, v in (d or {}).items():
            e = out.setdefault(m, {})
            if isinstance(v, dict):
                for k, r in v.items():
                    e.setdefault(k, r)
            else:
                e.setdefault(name, 1)
    for name, fn in (("dex", universe._dex_trending_candidates),
                     ("gt_trend", lambda: universe._gt_trending_candidates(int(c["gt_trend_pages"]))),
                     ("jup", universe._jup_candidates), ("dugo", universe._dugo_candidates)):
        try:
            d = fn()
            add({m: (v if name in ("dex", "gt_trend") else {name: 1}) for m, v in (d or {}).items()})
        except Exception as e:  # noqa: BLE001 - one source missing: the others
            log(PREFIX + f"izvor {name} nije stigao ({type(e).__name__})")
    try:
        for x in (store.the_list() or {}).get("tokens") or []:
            if x.get("mint"):
                out.setdefault(x["mint"], {}).setdefault("veliki", x.get("rank") or 1)
    except Exception:  # noqa: BLE001
        pass
    return out


def _dex(mints):
    if "dex_tokens" in FETCH:
        return FETCH["dex_tokens"](mints)
    from dexscreener import client
    return client.tokens("solana", list(mints))


def _i(x):
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


def _r(x, n=2):
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def snap_row(tid, now, deep, g):
    """One compact row of the deepest pool's numbers (volume summed over the token's pools)."""
    v = deep.get("volume") or {}
    t = deep.get("txns") or {}
    pc = deep.get("priceChange") or {}

    def bs(k):
        x = t.get(k) or {}
        return _i(x.get("buys")), _i(x.get("sells"))
    b5, s5 = bs("m5")
    b1, s1 = bs("h1")
    b24, s24 = bs("h24")
    return (tid, int(now), _r(deep.get("priceUsd"), 12), _i(g.get("mcap")), _i((deep.get("liquidity") or {}).get("usd")),
            _i(v.get("m5")), _i(v.get("h1")), _i(v.get("h6")), _i(g.get("vol24") or v.get("h24")), b5, s5, b1, s1, b24,
            s24, _r(pc.get("m5")), _r(pc.get("h1")), _r(pc.get("h6")), _r(pc.get("h24")))


def _archived():
    try:
        from rugfilter import archive
        return archive.blocked()
    except Exception:  # noqa: BLE001
        return frozenset()


def _curve():
    try:
        from rangedca import market as rmarket
        return tuple(rmarket.CURVE_DEX)
    except Exception:  # noqa: BLE001
        return ("pumpfun", "pump-fun", "moonshot", "launchlab", "meteora-dbc")


def _trend_rank(src):
    """The best trending rank among the trending / promoted sources (lower = hotter), None when none."""
    rs = [r for k, r in (src or {}).items() if k in ("dex_boost_top", "dex_boost", "dex_profile", "dex_cto", "gt_trend")
          and isinstance(r, (int, float))]
    return int(min(rs)) if rs else None


def snapshot(con, c, now, cand=None, log=print):
    """Members (+ new candidates) through DexScreener; membership, token rows and one snap row per member.
    Returns {"requests", "members", "joined", "left", "snaps"}."""
    have = {r[0]: r[1:] for r in con.execute("SELECT mint, id, member, out_since, src FROM tokens")}
    mem = [m for m, x in have.items() if x[1]]
    new = [m for m in (cand or {}) if m not in have or not have[m][1]]
    want = list(dict.fromkeys(mem + new))
    if not want:
        return {"requests": 0, "members": 0, "joined": 0, "left": 0, "snaps": 0}
    try:
        pairs = _dex(want)
    except Exception as e:  # noqa: BLE001 - DexScreener down: next pass
        log(PREFIX + f"DexScreener nije odgovorio ({type(e).__name__})")
        return {"requests": (len(want) + 29) // 30, "members": len(mem), "joined": 0, "left": 0, "snaps": 0}
    groups = universe.group(pairs)
    arch, curve = _archived(), _curve()
    nid = (con.execute("SELECT MAX(id) FROM tokens").fetchone()[0] or 0) + 1
    ok_rows, out_rows = [], []
    for m in want:
        g = groups.get(m)
        why = universe.data_judge(g, arch, curve, c["min_mcap"], c["max_mcap"], c["min_liq"]) if g else "nema poola"
        (ok_rows if why is None else out_rows).append((m, g, why))
    ok_rows.sort(key=lambda x: -(universe.vol_of(x[1]) or 0))
    cap = int(c["max_tokens"])
    keep, over = ok_rows[:cap], ok_rows[cap:]
    joined = left = snaps = 0
    rows = []
    for m, g, _w in keep:
        deep = g.get("deep") or {}
        old = have.get(m)
        src = json.loads(old[3]) if old and old[3] else {}
        src.update((cand or {}).get(m) or {})
        if old is None:
            tid = nid
            nid += 1
            con.execute("INSERT INTO tokens (mint, id, first_ts) VALUES (?,?,?)", (m, tid, int(now)))
        else:
            tid = old[0]
        if not (old and old[1]):
            joined += 1
        con.execute("UPDATE tokens SET symbol=?, pool=?, dex=?, mcap=?, liq=?, vol24=?, created_ts=?, last_ts=?, "
                    "out_since=NULL, src=?, trend=?, member=1, why=NULL WHERE mint=?",
                    ((g.get("symbol") or "").strip() or m[:6], deep.get("pairAddress"), deep.get("dexId"),
                     round(g.get("mcap") or 0), round(universe.liq_of(g)[1]), round(universe.vol_of(g)),
                     g.get("created_ts"), int(now), json.dumps(src), _trend_rank(src), m))
        rows.append(snap_row(tid, now, deep, g))
    leave_s = float(c["leave_after_h"]) * 3600
    for m, g, why in out_rows + [(m, g, "izvan prvih data_max_tokens") for m, g, _w in over]:
        old = have.get(m)
        if not old or not old[1]:
            continue   # a candidate that did not pass: not stored
        since = old[2] or int(now)
        if now - since >= leave_s:
            con.execute("UPDATE tokens SET member=0, out_since=?, why=? WHERE mint=?", (since, why, m))
            left += 1
        else:
            con.execute("UPDATE tokens SET out_since=?, why=? WHERE mint=?", (since, why, m))
            if g and (g.get("deep") or {}).get("priceUsd"):   # still a member inside its grace: measured on
                rows.append(snap_row(old[0], now, g["deep"], g))
    con.executemany("INSERT OR REPLACE INTO snap VALUES (" + ",".join("?" * 19) + ")", rows)
    snaps = len(rows)
    con.commit()
    _MEM["ts"] = 0.0
    n = con.execute("SELECT COUNT(*) FROM tokens WHERE member=1").fetchone()[0]
    return {"requests": (len(want) + 29) // 30, "members": n, "joined": joined, "left": left, "snaps": snaps}


# ---------- candles, safety, X ---------------------------------------------------------------------------------------------

def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def gt_left(con, c, now):
    """GeckoTerminal requests this collector may still make today (gt_day, sliced by the UTC hour like the other jobs)."""
    used = int(kv_get(con, f"gt:{_day(now)}", 0) or 0)
    hour = time.gmtime(now).tm_hour
    return max(0, min(int(c["gt_day"]), int(c["gt_day"] * (hour + 1) / 24)) - used)


def candles(con, c, now, log=print):
    """Top the members' candles up by 24 h volume within gt_pass / gt_left. Returns requests used."""
    budget = min(int(c["gt_pass"]), gt_left(con, c, now))
    if budget <= 0:
        return 0
    try:
        from event_calendar import http
        http.set_cg_job("midcap")
    except Exception:  # noqa: BLE001
        pass
    last = {(m, t): ts for m, t, ts in con.execute("SELECT mint, tbl, ts FROM fill_ts")}
    mem = con.execute("SELECT mint, pool FROM tokens WHERE member=1 AND pool IS NOT NULL ORDER BY vol24 DESC").fetchall()
    plan = []
    for k, (m, pool) in enumerate(mem):
        every = {"c15": c["c15_every_h_top"] if k < int(c["top_n"]) else c["c15_every_h"], "c1h": c["c1h_every_h"],
                 "c1d": c["c1d_every_h"]}
        for t in ("c1h", "c15", "c1d"):
            if now - (last.get((m, t)) or 0) >= float(every[t]) * 3600:
                plan.append((0 if (m, t) not in last else 1, k, m, pool, t))   # never filled first, then by volume
    plan.sort()
    used = 0
    for _new, _k, m, pool, t in plan:
        if used >= budget:
            break
        n = store.fill(con, m, pool, now, budget - used, tables=(t,))
        used += n
        con.execute("INSERT OR REPLACE INTO fill_ts VALUES (?,?,?)", (m, t, int(now)))
        con.commit()
        if n == 0:
            continue
    if used:
        kv_put(con, f"gt:{_day(now)}", int(kv_get(con, f"gt:{_day(now)}", 0) or 0) + used)
        con.commit()
    return used


def _rugcheck(mint):
    if "rugcheck" in FETCH:
        return FETCH["rugcheck"](mint)
    from rugfilter import rugcheck
    return rugcheck.report(mint, ttl=3600)


def safety(con, c, now, log=print):
    """RugCheck top-10 / holders / LP for safety_pass members whose last check is older than safety_every_h."""
    from topcheck import safety as tsafety
    last = dict(con.execute("SELECT mint, MAX(ts) FROM safety GROUP BY mint"))
    due = [(m, p) for m, p in con.execute("SELECT mint, pool FROM tokens WHERE member=1 ORDER BY vol24 DESC")
           if now - (last.get(m) or 0) >= float(c["safety_every_h"]) * 3600][:int(c["safety_pass"])]
    n = 0
    for m, pool in due:
        try:
            sm = tsafety.summarize_rc(_rugcheck(m), extra_pools=[pool] if pool else ())
        except Exception:  # noqa: BLE001 - RugCheck busy: the next pass
            sm = None
        if not sm:
            continue
        con.execute("INSERT OR REPLACE INTO safety VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (m, int(now), sm.get("top10"), sm.get("holders"), sm.get("lp_locked"), sm.get("insiders"),
                     sm.get("dev_pct"), 1 if sm.get("mint_auth") else 0, 1 if sm.get("freeze_auth") else 0,
                     json.dumps((sm.get("danger") or [])[:5], ensure_ascii=False)))
        n += 1
    con.commit()
    return n


def safety_latest(con, mints):
    out = {}
    for m, ts, top10, holders, lp, ins, dev, ma, fa, danger in con.execute(
            "SELECT mint, MAX(ts), top10, holders, lp_locked, insiders, dev_pct, mint_auth, freeze_auth, danger "
            "FROM safety GROUP BY mint"):
        if m in mints:
            out[m] = {"ts": ts, "top10": top10, "holders": holders, "lp_locked": lp, "insiders": ins, "dev_pct": dev,
                      "mint_auth": ma, "freeze_auth": fa, "danger": json.loads(danger or "[]")}
    return out


def xmom_pass(con, c, now, log=print):
    """X momentum (scan/xmom, twitterapi.io) for the hottest members, inside the scanner's own day cap. USD spent."""
    if int(c["x_pass"]) <= 0:
        return 0.0
    try:
        from kol import twapi
        from scan import store as sstore, xmom
        if not twapi.key():
            return 0.0
        scfg = sstore.config()
    except Exception:  # noqa: BLE001 - no X: nothing spent
        return 0.0
    last = dict(con.execute("SELECT mint, ts FROM xmom_ts"))
    due = [(m, s) for m, s in con.execute(
        "SELECT mint, symbol FROM tokens WHERE member=1 ORDER BY (trend IS NULL), trend, vol24 DESC")
        if now - (last.get(m) or 0) >= float(c["x_every_min"]) * 60][:int(c["x_pass"])]
    if not due:
        return 0.0
    usd = 0.0
    scon = kcon = None
    try:
        scon = sstore.connect()
        kcon = sqlite3.connect(os.path.join(ROOT, "kol.db"), timeout=30)
        kcon.executescript("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);")
        known, bots = xmom.known_handles(kcon)
        for m, sym in due:
            r = xmom.measure(m, sym, now, scon, kcon, scfg, known=known, bots=bots, log=log)
            con.execute("INSERT OR REPLACE INTO xmom_ts VALUES (?,?)", (m, int(now)))
            if r is None:
                break
            usd += float(r.get("usd") or 0)
    except Exception as e:  # noqa: BLE001
        log(PREFIX + f"X momentum: {type(e).__name__}")
    finally:
        for x in (scon, kcon):
            if x is not None:
                x.close()
    con.commit()
    return usd


def prune(con, c, now):
    """Snap rows older than snap_keep_days, the candles as veliki/store keeps them; once an hour."""
    if now - int(kv_get(con, "prune_ts", 0) or 0) < 3600:
        return 0
    n = con.execute("DELETE FROM snap WHERE ts < ?", (int(now - float(c["snap_keep_days"]) * 86400),)).rowcount
    store.prune(con, now)
    gone = [m for (m,) in con.execute("SELECT mint FROM tokens WHERE member=0 AND COALESCE(out_since, 0) < ?",
                                      (int(now - 30 * 86400),))]
    for m in gone:   # 30 days out of the universe: its candles go (its snap rows went with the 14 days)
        for t in ("c15", "c1h", "c1d"):
            con.execute(f"DELETE FROM {t} WHERE token=?", (m,))
    kv_put(con, "prune_ts", int(now))
    con.commit()
    return n


# ---------- one pass -------------------------------------------------------------------------------------------------------

def _count(con, now, **add):
    k = f"cnt:{_day(now)}"
    d = kv_get(con, k, {}) or {}
    for a, v in add.items():
        d[a] = round((d.get(a) or 0) + (v or 0), 5)
    kv_put(con, k, d)
    h = kv_get(con, "cnt_hour", {}) or {}
    for a, v in add.items():
        h[a] = round((h.get(a) or 0) + (v or 0), 5)
    kv_put(con, "cnt_hour", h)


def mb_day(con, path, now):
    """(size MB, growth MB a day measured over the kept hourly samples, or None)."""
    try:
        size = os.path.getsize(path) + (os.path.getsize(path + "-wal") if os.path.exists(path + "-wal") else 0)
    except OSError:
        return None, None
    hist = [x for x in (kv_get(con, "size_hist", []) or []) if now - x[0] <= 3 * 86400]
    if not hist or now - hist[-1][0] >= 3500:
        hist.append([int(now), size])
    kv_put(con, "size_hist", hist[-80:])
    if len(hist) < 2 or hist[-1][0] - hist[0][0] < 3000:
        return size / 1e6, None
    return size / 1e6, (hist[-1][1] - hist[0][1]) / 1e6 / ((hist[-1][0] - hist[0][0]) / 86400)


def hour_line(con, c, now, path, prio=None):
    h = kv_get(con, "cnt_hour", {}) or {}
    d = kv_get(con, f"cnt:{_day(now)}", {}) or {}
    n = con.execute("SELECT COUNT(*) FROM tokens WHERE member=1").fetchone()[0]
    nt = con.execute("SELECT COUNT(*) FROM tokens WHERE member=1 AND trend IS NOT NULL").fetchone()[0]
    size, grow = mb_day(con, path, now)
    kv_put(con, "cnt_hour", {})
    s = (PREFIX + f"sat: {n} midcap tokena ({c['min_mcap'] / 1e6:,.0f}M–{c['max_mcap'] / 1e6:,.0f}M, {nt} s trending "
         f"rangom), prolaza {int(h.get('passes') or 0)}, snimki {int(h.get('snaps') or 0)}, DexScreener "
         f"{int(h.get('dex') or 0)} zahtjeva (besplatno), GeckoTerminal {int(h.get('gt') or 0)} (danas "
         f"{int(d.get('gt') or 0)}/{int(c['gt_day'])}), RugCheck {int(h.get('rc') or 0)}, X {h.get('x_usd') or 0:.3f} $ "
         f"(danas {d.get('x_usd') or 0:.3f} $); midcap.db {size or 0:,.0f} MB" +
         (f", rast ~{grow:,.1f} MB/dan" if grow is not None else ", rast: još se mjeri"))
    return s


def run_pass(now=None, log=print, path=None, force=False):
    """One collector pass (see the module text); {} when the switch is off (unless force)."""
    now = int(now or time.time())
    if not force:
        try:
            from ops import fokus
            if not fokus.on():
                return {}
        except Exception:  # noqa: BLE001
            return {}
    c = config()
    path = path or db_path()
    con = connect(path)
    out = {}
    try:
        cand = None
        if now - int(kv_get(con, "disc_ts", 0) or 0) >= float(c["discover_every_s"]):
            cand = discover(c, log)
            kv_put(con, "disc_ts", now)
            kv_put(con, "disc_n", {k: sum(1 for v in cand.values() if k in v) for k in
                                   ("dex_boost_top", "dex_boost", "dex_profile", "dex_cto", "gt_trend", "jup", "dugo",
                                    "veliki")})
            out["discovered"] = len(cand)
        out.update(snapshot(con, c, now, cand, log))
        out["gt"] = candles(con, c, now, log)
        out["rc"] = safety(con, c, now, log)
        out["x_usd"] = xmom_pass(con, c, now, log)
        prune(con, c, now)
        prio = None
        try:
            from veliki import prioritet
            prio = prioritet.refresh(con, now)
        except Exception as e:  # noqa: BLE001 - the order is a help, the data is the job
            log(PREFIX + f"prioritet: {type(e).__name__}: {e}")
        _count(con, now, passes=1, snaps=out.get("snaps"), dex=out.get("requests"), gt=out.get("gt"), rc=out.get("rc"),
               x_usd=out.get("x_usd"))
        con.commit()
        first = not kv_get(con, "start_said", 0) or now - int(kv_get(con, "start_said", 0)) > 6 * 3600
        if now - int(kv_get(con, "hour_ts", 0) or 0) >= 3600:
            kv_put(con, "hour_ts", now)
            log(hour_line(con, c, now, path, prio))
            if prio:
                log(prioritet.line(prio, int(c["prio_top"])))
            if first:
                kv_put(con, "start_said", now)
                dn = kv_get(con, "disc_n", {}) or {}
                log(PREFIX + "izvori (zadnje otkrivanje): " + ", ".join(f"{k} {v}" for k, v in dn.items()))
            con.commit()
        return out
    finally:
        con.close()
