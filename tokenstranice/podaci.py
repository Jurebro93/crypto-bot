"""Brojke stranice tokena, samo iz naših baza (bez mreže, sve read-only).

universe(ctx)      {mint: osnovni redak} tokena koji danas imaju stranicu: midcap.db članovi (MC 2M-200M, bondani, nisu
                   rug, meme: veliki/universe.data_judge) + lista "veliki" + top 100 (public.db, MC >= 2M); ništa ispod
                   MIN_MCAP (vlasnik: nikakvi resursi na mikrokapove), ništa iz arhive rugova, ništa što nije meme
sections(m, ctx, delay_s)   sve brojke jedne stranice (dict, JSON-sigurno):
    now        cijena, MC, likvidnost, volumen 24 h, promjena 24 h (zadnja snimka midcap.db, inače public.db / lista)
    hist       dnevne cijene, MC (cijena x ponuda iz zadnje snimke), dnevni volumen (do 180 d), likvidnost (14 d, 4 h)
    chg        promjena 7 / 30 / 90 dana iz dnevnih zatvaranja
    range      tipičan dnevni raspon (medijan (high - low) / low zadnjih 30 dana, kvartili), raspon 30 d, položaj u njemu
    m          veliki/metrics.compute: dob, stalnost volumena, beta / korelacija s BTC-om, ponašanje nakon BTC +3 %
               dana, pad od ATH-a, odbijanja s dna 30-dnevnog raspona, kategorija A / B / C
    bounces    zadnjih 5 odbijanja (dan, najbolji vrh i najgori pad u 7 dana), isto pravilo kao metrics
    calls      pozivi influencera i Telegram kanala: ČISTI (ui/kolstats: kind 'call', izmjereni, nisu kasni, nisu iz
               pretraga pobjednika, nisu botovi ni novčanici) i stariji od delay_s; MC kod poziva i ishod; zbroj; broj
               svježih (mlađih od delay_s) samo kao broj
    holders    klase holdera (holderi.db: udjeli, insajderi bez burzi / LP, HHI, top 10 bez njih, udio po burzi),
               RugCheck (midcap.db safety), broj holdera kroz vrijeme (dugo.db); nikad adrese novčanika
    listing    status po burzi iz predmemorije (holderi.db kv: javne liste burzi, CoinGecko), s izvorom; bez mreže
    lsig       listing signali stariji od delay_s s ishodom, svježi samo kao broj
    ins        insajderi i pametni novac (insajderi.db): samo zbrojevi
    ours       (samo delay_s == 0, privatna stranica) zona ulaza dnevnog pravila (veliki/intra), naši tradeovi
    enough     dovoljno podataka za indeks i AI mišljenje (ENOUGH_DAYS dnevnih cijena)
"""
import json
import os
import re
import sqlite3
import statistics
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D, H = 86400, 3600
PUBLIC_DELAY_S = 86400
ENOUGH_DAYS = 7
CALLS_KEEP = 40
HANDLE = re.compile(r"[A-Za-z0-9_]{1,30}")
CHANNEL = re.compile(r"[A-Za-z0-9_]{3,40}")
POST_URL = re.compile(r"https://(?:x\.com|twitter\.com)/[A-Za-z0-9_]{1,30}/status/\d{5,25}|https://t\.me/[A-Za-z0-9_]{3,40}/\d{1,12}")


def _limits():
    try:
        from veliki import universe as U
        return U.DATA_MIN_MCAP, U.DATA_MAX_MCAP
    except Exception:  # noqa: BLE001
        return 2e6, 2e8


MIN_MCAP, MAX_MCAP = _limits()


# ---------- databases ---------------------------------------------------------------------------------------------

def default_paths():
    from holderi import store as hstore
    from insajderi import store as istore
    from league import store as lstore
    from trade import settings
    from ui import coins as K
    from veliki import midcap, store as vstore
    return {"midcap": midcap.db_path(), "veliki": vstore.db_path(),
            "dugo": os.environ.get("DUGO_DB") or os.path.join(ROOT, "dugo.db"),
            "kol": os.environ.get("KOL_DB") or os.path.join(ROOT, "kol.db"), "holderi": hstore.db_path(),
            "insajderi": istore.db_path(), "public": K.DB, "league": lstore.DB, "trade": settings.DB,
            "market": os.environ.get("MARKET_DB") or os.path.join(ROOT, "market.db")}


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect("file:" + quote(os.path.abspath(path)) + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def one(con, sql, args=()):
    r = q(con, sql, args)
    return r[0] if r else None


class Ctx:
    """What one pass (or one private view) shares: the read-only connections, BTC, the exchange lists, the bots."""

    def __init__(self, now=None, paths=None):
        self.now = int(now or time.time())
        self.p = paths or default_paths()
        self._con, self._cache = {}, {}

    def con(self, name):
        if name not in self._con:
            self._con[name] = _ro(self.p.get(name))
        return self._con[name]

    def close(self):
        for c in self._con.values():
            if c is not None:
                c.close()
        self._con.clear()

    def memo(self, k, fn):
        if k not in self._cache:
            self._cache[k] = fn()
        return self._cache[k]

    def btc(self):
        def load():
            v = self.con("veliki")
            hourly = {int(t): p for t, p in q(v, "SELECT ts, usd FROM btc_h") if p}
            daily = [(int(t), p) for t, p in q(v, "SELECT day, usd FROM btc_d ORDER BY day") if p]
            if self.p.get("market"):   # market/makro collects BTC every hour too (veliki/store.btc_hourly)
                mc = _ro(self.p["market"])
                hourly.update({int(t): p for t, p in q(mc, "SELECT ts, usd FROM btc_h") if p})
                if mc is not None:
                    mc.close()
            return sorted(hourly.items()), daily
        return self.memo("btc", load)

    def crash(self):
        def load():
            try:
                from veliki import rule
                h = self.btc()[0]
                return rule.crash_of(h) if h else None
            except Exception:  # noqa: BLE001
                return None
        return self.memo("crash", load)

    def archived(self):
        def load():
            try:
                from rugfilter import archive
                return archive.blocked()
            except Exception:  # noqa: BLE001
                return frozenset()
        return self.memo("arch", load)

    def bots(self):
        return self.memo("bots", lambda: {h for (h,) in q(self.con("kol"), "SELECT handle FROM kols WHERE "
                                                                          "COALESCE(bot, 0) = 1")})

    def lists(self):
        """{exchange key: {"symbols", "contracts", "alpha", "ok"}} of the exchanges' public market lists (holderi.db
        kv lst:<exchange>, refreshed daily by holderi/burze); read once a pass."""
        def load():
            out = {}
            h = self.con("holderi")
            try:
                from holderi import burze
                keys = list(burze.LISTERS)
            except Exception:  # noqa: BLE001
                keys = []
            for ex in keys:
                r = one(h, "SELECT v FROM kv WHERE k=?", (f"lst:{ex}",))
                try:
                    d = json.loads(r[0]) if r else {}
                except (TypeError, ValueError):
                    d = {}
                out[ex] = {"symbols": set(d.get("symbols") or []), "contracts": set(d.get("contracts") or []),
                           "alpha": set(d.get("alpha") or []), "ts": d.get("ts")}
            return out
        return self.memo("lists", load)


def _kv_json(con, table, k):
    r = one(con, f"SELECT v FROM {table} WHERE k=?", (k,))
    try:
        return json.loads(r[0]) if r else None
    except (TypeError, ValueError):
        return None


# ---------- who has a page ----------------------------------------------------------------------------------------

def _non_meme(sym, name):
    try:
        from veliki import universe as U
        return U.non_meme(sym, name)
    except Exception:  # noqa: BLE001
        return False


def names(ctx, mints):
    """{mint: name} from veliki.db (list + history), public.db and kol.db tokens (what is there)."""
    out = {}
    for con, sql in ((ctx.con("kol"), "SELECT token, name FROM tokens"),
                     (ctx.con("veliki"), "SELECT mint, name FROM hist"), (ctx.con("veliki"), "SELECT mint, name FROM tokens"),
                     (ctx.con("public"), "SELECT mint, name FROM coins")):
        for m, n in q(con, sql):
            if m in mints and n and str(n).strip():
                out[m] = str(n).strip()[:60]
    return out


def universe(ctx):
    """{mint: {"mint", "symbol", "name", "src", "mcap", "liq", "vol24", "created_ts", "top"}} (see the module text)."""
    out = {}
    for m, sym, mcap, liq, vol, created in q(ctx.con("midcap"), "SELECT mint, symbol, mcap, liq, vol24, created_ts FROM "
                                                                "tokens WHERE member=1"):
        out[m] = {"mint": m, "symbol": sym, "mcap": mcap, "liq": liq, "vol24": vol, "created_ts": created, "src": "midcap"}
    lst = _kv_json(ctx.con("veliki"), "kv", "list") or {}
    for x in lst.get("tokens") or []:
        m = x.get("mint")
        if m and m not in out:
            out[m] = {"mint": m, "symbol": x.get("symbol"), "mcap": x.get("mcap"), "liq": x.get("liq"),
                      "vol24": x.get("vol24"), "created_ts": x.get("created_ts"), "src": "veliki"}
    for m, sym, name, mcap, liq, vol, rank in q(ctx.con("public"), "SELECT mint, symbol, name, mcap, liq, vol24, rank "
                                                                   "FROM coins WHERE rank IS NOT NULL"):
        e = out.setdefault(m, {"mint": m, "symbol": sym, "mcap": mcap, "liq": liq, "vol24": vol, "created_ts": None,
                               "src": "top"})
        e["top"], e["name"] = rank, name
    arch = ctx.archived()
    nm = names(ctx, set(out))
    keep = {}
    for m, e in out.items():
        e.setdefault("name", None)
        e["name"] = e["name"] or nm.get(m)
        mc = e.get("mcap") or 0
        if m in arch or _non_meme(e.get("symbol"), e.get("name")):
            continue
        if mc < MIN_MCAP or (mc > MAX_MCAP and not e.get("top")):   # no microcaps; above 200M only the top 100
            continue
        keep[m] = e
    return keep


def out_why(ctx, mint):
    """Why a page stopped being refreshed, as a code the page words (never the collector's own text)."""
    if mint in ctx.archived():
        return "rug"
    r = one(ctx.con("midcap"), "SELECT member, why FROM tokens WHERE mint=?", (mint,))
    why = (r[1] or "") if r else ""
    if why.startswith("MC") and "ispod" in why:
        return "mc_low"
    if why.startswith("MC") and "iznad" in why:
        return "mc_high"
    if "arhiv" in why:
        return "rug"
    return "out"


# ---------- series --------------------------------------------------------------------------------------------------

def _bar(r):
    ts, o, h, l, c, v = r[:6]
    c = float(c or 0)
    if c <= 0:
        return None
    o, h, l = float(o or c), float(h or c), float(l or c)
    return (int(ts) // D * D, o, max(h, c, o), min(l, c, o), c, float(v or 0))


def daily_of(ctx, mint):
    """[(day ts, o, h, l, c, v)] oldest first: dugo.db, veliki.db, midcap.db daily candles (the later wins a day),
    with public.db snapshots grouped by day where no candle exists (top 100 coins)."""
    rows = {}
    for (day, px) in q(ctx.con("public"), "SELECT ts / 86400 * 86400, GROUP_CONCAT(price) FROM coin_hist WHERE mint=? "
                                          "AND price > 0 GROUP BY ts / 86400 ORDER BY 1", (mint,)):
        ps = [float(x) for x in str(px or "").split(",") if x]
        if ps:
            rows[int(day)] = (int(day), ps[0], max(ps), min(ps), ps[-1], 0.0)
    for name, sql in (("dugo", "SELECT day, o, h, l, c, v FROM candles WHERE mint=? ORDER BY day DESC LIMIT 400"),
                      ("veliki", "SELECT ts, o, h, l, c, v FROM c1d WHERE token=? ORDER BY ts DESC LIMIT 400"),
                      ("midcap", "SELECT ts, o, h, l, c, v FROM c1d WHERE token=? ORDER BY ts DESC LIMIT 400")):
        for r in q(ctx.con(name), sql, (mint,)):
            b = _bar(r)
            if b:
                rows[b[0]] = b
    return [rows[k] for k in sorted(rows)][-400:]


def hourly_of(ctx, mint, now):
    rows = {}
    for name in ("veliki", "midcap"):
        for r in q(ctx.con(name), "SELECT ts, o, h, l, c, v FROM c1h WHERE token=? AND ts >= ? ORDER BY ts",
                   (mint, now - 45 * D)):
            c = float(r[4] or 0)
            if c > 0:
                rows[int(r[0])] = (int(r[0]), float(r[1] or c), float(r[2] or c), float(r[3] or c), c, float(r[5] or 0))
    return [rows[k] for k in sorted(rows)]


def _tid(ctx, mint):
    r = one(ctx.con("midcap"), "SELECT id FROM tokens WHERE mint=?", (mint,))
    return r[0] if r else None


def now_of(ctx, mint, base=None):
    """The newest numbers: midcap.db snap, else public.db coins, else the universe row."""
    tid = _tid(ctx, mint)
    if tid is not None:
        r = one(ctx.con("midcap"), "SELECT ts, px, mc, liq, v24, c24, b24, s24, c1h FROM snap WHERE id=? "
                                   "ORDER BY ts DESC LIMIT 1", (tid,))
        if r and r[1]:
            return {"ts": r[0], "price": r[1], "mcap": r[2], "liq": r[3], "vol24": r[4], "chg24": r[5],
                    "buys24": r[6], "sells24": r[7], "chg1h": r[8], "src": "dex"}
    r = one(ctx.con("public"), "SELECT updated, price, mcap, liq, vol24, chg24h, buys24, sells24, chg1h, holders "
                               "FROM coins WHERE mint=?", (mint,))
    if r and r[1]:
        return {"ts": r[0], "price": r[1], "mcap": r[2], "liq": r[3], "vol24": r[4], "chg24": r[5], "buys24": r[6],
                "sells24": r[7], "chg1h": r[8], "holders": r[9], "src": "jup"}
    b = base or {}
    return {"ts": None, "price": None, "mcap": b.get("mcap"), "liq": b.get("liq"), "vol24": b.get("vol24"),
            "chg24": None, "src": "list"}


def liq_hist(ctx, mint, now):
    tid = _tid(ctx, mint)
    if tid is None:
        return []
    return [(int(t), int(liq or 0), int(v or 0)) for t, liq, v in
            q(ctx.con("midcap"), "SELECT MAX(ts), liq, v24 FROM snap WHERE id=? AND ts >= ? GROUP BY ts / 14400 "
                                 "ORDER BY 1", (tid, now - 14 * D)) if liq]


def _ago(daily, days):
    if not daily:
        return None
    t = daily[-1][0] - days * D
    old = [c for c in daily if c[0] <= t]
    if not old or old[-1][0] < t - 3 * D:
        return None
    return round((daily[-1][4] / old[-1][4] - 1) * 100, 2) if old[-1][4] else None


def _med(xs):
    xs = sorted(x for x in xs if x is not None)
    return statistics.median(xs) if xs else None


def _q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    i = int(k)
    return xs[i] if i + 1 >= len(xs) else xs[i] + (xs[i + 1] - xs[i]) * (k - i)


def range_of(daily, now):
    """Typical daily range of the last 30 completed days and where the price stands in the 30-day range."""
    done = [c for c in daily if c[0] + D <= now][-30:]
    rs = [(c[2] - c[3]) / c[3] * 100 for c in done if c[3] > 0]
    if len(rs) < 5:
        return None
    lo, hi = min(c[3] for c in done), max(c[2] for c in done)
    last = daily[-1][4]
    return {"n": len(rs), "med": round(_med(rs), 2), "p25": round(_q(rs, 0.25), 2), "p75": round(_q(rs, 0.75), 2),
            "lo30": lo, "hi30": hi, "pos30": round((last - lo) / (hi - lo) * 100, 1) if hi > lo else None,
            "width30": round((hi / lo - 1) * 100, 1) if lo > 0 else None}


def bounce_list(daily, crash=None, keep=5):
    """The last `keep` bounces from the bottom 20 % of the trailing 30-day range (veliki/metrics' rule)."""
    out = []
    for i in range(30, len(daily) - 1):
        t = daily[i][0]
        if crash is not None:
            try:
                if crash.overlaps(t, t + D - 1):
                    continue
            except Exception:  # noqa: BLE001
                pass
        w = daily[i - 30:i]
        lo, hi = min(c[3] for c in w), max(c[2] for c in w)
        c = daily[i][4]
        if hi <= lo or not (lo <= c <= lo + 0.2 * (hi - lo)):
            continue
        nxt = daily[i + 1:i + 8]
        if len(nxt) < 3:
            continue
        out.append({"ts": t, "up7": round((max(x[2] for x in nxt) / c - 1) * 100, 1),
                    "dn7": round((min(x[3] for x in nxt) / c - 1) * 100, 1)})
    return out[-keep:]


M_KEYS = ("age_d", "age_bucket", "pers30", "pers90", "cv30", "vol_day_avg30", "beta_d", "corr_d", "beta_4h", "corr_4h",
          "btc_up_n", "btc_up_hit", "btc_up_24h", "btc_up_72h", "dd_ath", "ath_ts", "days_history", "bounce_n", "hit15",
          "med_up7", "med_dn7", "cat", "score")


def metrics_of(ctx, daily, hourly, created_ts, now):
    if len(daily) < 5:
        return {}
    try:
        from veliki import metrics
        h, d = ctx.btc()
        m = metrics.compute(daily, hourly, d, h, created_ts, now, ctx.crash())
    except Exception as e:  # noqa: BLE001 - one token's bad data never stops the pass
        return {"error": type(e).__name__}
    return {k: m.get(k) for k in M_KEYS}


# ---------- calls -----------------------------------------------------------------------------------------------------

def caller_of(handle):
    """("x", handle) / ("tg", channel) for a public caller, None for anything else (wallets, internal names)."""
    h = str(handle or "")
    if h.startswith("tg:"):
        ch = h[3:]
        return ("tg", ch) if CHANNEL.fullmatch(ch) else None
    return ("x", h) if HANDLE.fullmatch(h) else None


def calls_of(ctx, mint, now, delay_s):
    """Clean, measured calls older than delay_s (+ the fresh ones' count); with delay_s 0 every call, clean marked."""
    from ui import kolstats as KS
    k = ctx.con("kol")
    cut = int(now - delay_s)
    bots = ctx.bots()
    qs = ",".join("?" * len(KS.BIASED_SOURCES))
    cols = {r[1] for r in q(k, "PRAGMA table_info(calls)")}
    if {"pre2h", "source", "bad"} <= cols:
        rows = q(k, f"""SELECT handle, ts, url, mcap0, r1h, r24h, max24, CASE WHEN max24 IS NOT NULL AND bad IS NULL
            AND COALESCE(pre2h, 0) < 1.0 AND COALESCE(source, '') NOT IN ({qs}) THEN 1 ELSE 0 END FROM calls
            WHERE token = ? AND kind = 'call' AND ts < ? ORDER BY ts DESC LIMIT 400""", (*KS.BIASED_SOURCES, mint, cut))
    else:   # an older kol.db without the cleanliness columns: a measured call counts as clean
        rows = q(k, "SELECT handle, ts, url, mcap0, r1h, r24h, max24, CASE WHEN max24 IS NOT NULL THEN 1 ELSE 0 END "
                    "FROM calls WHERE token = ? AND kind = 'call' AND ts < ? ORDER BY ts DESC LIMIT 400", (mint, cut))
    out = []
    for h, ts, url, mc0, r1, r24, mx, clean in rows:
        who = caller_of(h)
        if not who or h in bots:
            continue
        if delay_s and not clean:
            continue
        out.append({"kind": who[0], "who": who[1], "ts": int(ts), "url": url if url and POST_URL.fullmatch(url) else None,
                    "mcap0": mc0, "r1h": r1, "r24h": r24, "max24": mx, "clean": int(bool(clean))})
    cl = [c for c in out if c["clean"] and c["max24"] is not None]
    r1 = [c["r1h"] for c in cl if c["r1h"] is not None]
    r24 = [c["r24h"] for c in cl if c["r24h"] is not None]
    stats = {"n": len(cl), "callers": len({(c["kind"], c["who"]) for c in cl}),
             "up1h": round(sum(1 for x in r1 if x > 0) / len(r1), 3) if r1 else None,
             "hit15": round(sum(1 for c in cl if (c["max24"] or 0) >= KS.HIT) / len(cl), 3) if cl else None,
             "med24": round(_med(r24), 4) if r24 else None,
             "rug": round(sum(1 for x in r24 if x <= KS.RUG) / len(r24), 3) if r24 else None,
             "first": min((c["ts"] for c in cl), default=None), "tg": sum(1 for c in cl if c["kind"] == "tg")}
    fresh = one(k, "SELECT COUNT(*) FROM calls WHERE token = ? AND kind = 'call' AND ts >= ? AND handle NOT LIKE 'w:%'",
                (mint, cut)) if delay_s else None
    return {"list": out[:CALLS_KEEP], "stats": stats, "fresh": int(fresh[0]) if fresh else 0}


# ---------- holders, listings, insiders ---------------------------------------------------------------------------------

def _ex_name(k):
    try:
        from holderi import burze
        return burze.NAMES.get(k, k)
    except Exception:  # noqa: BLE001
        return k


def holders_of(ctx, mint):
    out = {}
    r = one(ctx.con("holderi"), "SELECT ts, data FROM profile WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
    if r:
        try:
            d = json.loads(r[1] or "{}")
        except ValueError:
            d = {}
        out.update(ts=r[0], shares={k: round(float(v or 0), 2) for k, v in (d.get("shares") or {}).items()},
                   insider_ex=d.get("insider_ex"), hhi=d.get("hhi"), top10_ex=d.get("top10_ex"), n_top=d.get("n"),
                   exchanges={_ex_name(k): round(float(v or 0), 2) for k, v in (d.get("exchanges") or {}).items()
                              if k != "nepoznata" and (v or 0) > 0})
        unk = (d.get("exchanges") or {}).get("nepoznata")
        if unk:
            out["exchange_unknown"] = round(float(unk), 2)
    s = one(ctx.con("midcap"), "SELECT ts, top10, holders, lp_locked, insiders, dev_pct, mint_auth, freeze_auth, danger "
                               "FROM safety WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
    if s:
        try:
            danger = json.loads(s[8] or "[]")[:5]
        except ValueError:
            danger = []
        out["rc"] = {"ts": s[0], "top10": s[1], "holders": s[2], "lp_locked": s[3], "insiders": s[4], "dev_pct": s[5],
                     "mint_auth": s[6], "freeze_auth": s[7], "danger": [str(x)[:80] for x in danger]}
    dugo = ctx.con("dugo")
    hist = [(int(dd), int(n)) for dd, n in q(dugo, "SELECT day, n FROM holders WHERE mint=? ORDER BY day DESC LIMIT 180",
                                            (mint,)) if n][::-1]
    if hist:
        out["hist"] = hist
    li = one(dugo, "SELECT all_cex, names FROM listings WHERE mint=? ORDER BY day DESC LIMIT 1", (mint,))
    if li and li[0]:
        out["cg_cex"] = int(li[0])
        try:
            from ui import coinseo
            out["cg_major"] = [lab for lab, _m in coinseo.cex_major(li[1])[:8]]
        except Exception:  # noqa: BLE001
            out["cg_major"] = []
    pr = one(ctx.con("public"), "SELECT holders, audit FROM coins WHERE mint=?", (mint,))
    if pr:
        out["n_holders_jup"] = pr[0]
        try:
            a = json.loads(pr[1] or "{}")
            out["jup"] = {"mint_off": a.get("mintAuthorityDisabled"), "freeze_off": a.get("freezeAuthorityDisabled"),
                          "top_pct": a.get("topHoldersPercentage"), "dev_pct": a.get("devBalancePercentage")}
        except ValueError:
            pass
    return out


def listing_of(ctx, mint, symbol):
    """[{"ex", "st": da | nesigurno | ne | nepoznato, "src"}] from the cached lists only (holderi/burze.listed's rules
    without its network steps)."""
    h = ctx.con("holderi")
    cg = (_kv_json(h, "kv", f"cg:{mint}") or {}).get("ex")
    sym = str(symbol or "").strip().upper()   # holderi/burze._sym: the lists keep symbols as the exchanges write them
    out = []
    for ex, lst in ctx.lists().items():
        name = _ex_name(ex)
        if cg and ex in cg:
            out.append({"ex": name, "st": "da", "src": "cg"})
        elif mint in lst["contracts"]:
            out.append({"ex": name, "st": "da", "src": "list", "alpha": int(mint in lst["alpha"])})
        elif not lst["symbols"]:
            out.append({"ex": name, "st": "nepoznato", "src": None})
        elif sym and sym in lst["symbols"]:
            res = (_kv_json(h, "kv", f"res:{ex}:{sym}") or {}).get("c")
            if res and mint in res:
                out.append({"ex": name, "st": "da", "src": "list"})
            elif res:
                out.append({"ex": name, "st": "ne", "src": "list"})
            else:
                out.append({"ex": name, "st": "nesigurno", "src": "list"})
        else:
            out.append({"ex": name, "st": "ne", "src": "list"})
    order = {"da": 0, "nesigurno": 1, "ne": 2, "nepoznato": 3}
    out.sort(key=lambda x: (order[x["st"]], x["ex"]))
    return out


def lsig_of(ctx, mint, now, delay_s):
    cut = int(now - delay_s)
    rows = q(ctx.con("holderi"), "SELECT ts, kind, exchange, score, px, px_1h, px_24h, px_7d, ctl_24h FROM signals "
                                 "WHERE mint=? ORDER BY ts DESC LIMIT 30", (mint,))
    pub, fresh = [], 0
    fcut = int(now - (delay_s or D))   # "fresh" = younger than the public delay (24 h on the private page too)
    for ts, kind, ex, sc, px, p1, p24, p7, c24 in rows:
        fresh += ts >= fcut
        if ts >= cut:
            continue
        def ret(p):
            return round((p / px - 1) * 100, 1) if p and px else None
        pub.append({"ts": int(ts), "kind": kind if kind in ("pre_listing", "deposit_sell") else "other",
                    "ex": _ex_name(ex) if ex else None, "score": round(sc or 0), "r1h": ret(p1), "r24h": ret(p24),
                    "r7d": ret(p7), "ctl24": c24})
    return {"list": pub[:10], "fresh": fresh}


def insiders_of(ctx, mint, now, delay_s):
    """Aggregated counts only: events, wallets that bought before / sold into them, confirmed groups, smart-money
    signals (older than delay_s; the fresh ones as a count)."""
    i = ctx.con("insajderi")
    if i is None:
        return {}
    cut = int(now - delay_s)
    fcut = int(now - (delay_s or D))
    ev = {k: (int(n), mx) for k, n, mx in q(i, "SELECT kind, COUNT(*), MAX(peak_x) FROM i2_events WHERE token=? AND "
                                               "t0 < ? GROUP BY kind", (mint, cut))}
    p = one(i, "SELECT COUNT(DISTINCT p.wallet), COUNT(DISTINCT CASE WHEN p.bought_before = 1 THEN p.wallet END), "
               "COUNT(DISTINCT CASE WHEN p.sold_into = 1 THEN p.wallet END) FROM i2_part p JOIN i2_events e ON "
               "e.eid = p.eid WHERE e.token=? AND e.t0 < ?", (mint, cut)) or (0, 0, 0)
    g = one(i, "SELECT COUNT(DISTINCT g.owner) FROM i2_part p JOIN i2_events e ON e.eid = p.eid JOIN i2_groups g ON "
               "g.owner = p.owner WHERE e.token=? AND e.t0 < ? AND g.confirmed_ts IS NOT NULL", (mint, cut)) or (0,)
    s = one(i, "SELECT COUNT(*), MAX(n_clusters) FROM i2_signals WHERE token=? AND ts < ?", (mint, cut)) or (0, None)
    fs = one(i, "SELECT COUNT(*) FROM i2_signals WHERE token=? AND ts >= ?", (mint, fcut)) or (0,)
    fe = one(i, "SELECT COUNT(*) FROM i2_events WHERE token=? AND t0 >= ?", (mint, fcut)) or (0,)
    out = {"events": sum(n for n, _m in ev.values()), "jumps": ev.get("jump", (0, None))[0],
           "call_events": ev.get("call", (0, None))[0],
           "peak_x": max((mx for _n, mx in ev.values() if mx is not None), default=None),
           "wallets": int(p[0] or 0), "before": int(p[1] or 0), "sold_into": int(p[2] or 0), "groups": int(g[0] or 0),
           "smart_sig": int(s[0] or 0), "smart_max_clusters": s[1], "fresh_sig": int(fs[0] or 0),
           "fresh_events": int(fe[0] or 0)}
    if not delay_s:
        w = one(i, "SELECT COUNT(*) FROM i2_smart WHERE last_token=? AND last_buy_ts >= ?", (mint, int(now - D))) or (0,)
        out["smart_buying_24h"] = int(w[0] or 0)
    return out


# ---------- ours (private page only) --------------------------------------------------------------------------------

def ours_of(ctx, mint, now, hourly):
    out = {"zone": None, "trades": []}
    try:
        from veliki import intra
        z = intra.zone([tuple(b[:6]) for b in hourly], now)
        out["zone"] = {k: (round(v, 12) if isinstance(v, float) else v) for k, v in z.items()
                       if k in ("ok", "why", "lo", "hi", "s_hi", "width", "n")}
    except Exception as e:  # noqa: BLE001
        out["zone"] = {"ok": False, "why": type(e).__name__}
    lg = ctx.con("league")
    for r in q(lg, "SELECT opened_ts, COALESCE(kind, 'range'), status, ret, reason, user FROM veliki_trades WHERE token=? "
                   "ORDER BY opened_ts DESC LIMIT 10", (mint,)):
        out["trades"].append({"ts": r[0], "what": f"midcap {r[1]}", "status": r[2], "ret": r[3], "why": r[4],
                              "who": r[5]})
    try:
        from trade import settings
        paper = settings.PAPER_USER
    except Exception:  # noqa: BLE001
        paper = "autopilot-paper"
    for r in q(lg, "SELECT opened_ts, source, status, ret, note FROM trades WHERE token=? AND user=? ORDER BY opened_ts "
                   "DESC LIMIT 10", (mint, paper)):
        out["trades"].append({"ts": r[0], "what": f"demo {r[1] or ''}".strip(), "status": r[2], "ret": r[3],
                              "why": None, "who": paper})
    for r in q(ctx.con("trade"), "SELECT opened_ts, mode, status, sol_in, sol_back, reason FROM positions WHERE token=? "
                                 "ORDER BY opened_ts DESC LIMIT 10", (mint,)):
        ret = (r[4] / r[3] - 1) if r[3] and r[4] is not None and r[2] == "closed" else None
        out["trades"].append({"ts": r[0], "what": f"Autopilot {r[1] or ''}".strip(), "status": r[2], "ret": ret,
                              "why": None, "who": "autopilot"})
    out["trades"].sort(key=lambda x: -(x["ts"] or 0))
    out["trades"] = out["trades"][:15]
    return out


# ---------- one page ------------------------------------------------------------------------------------------------

def sections(mint, ctx, delay_s=PUBLIC_DELAY_S, base=None):
    """Every number of one token page (see the module text)."""
    now = ctx.now
    base = base or {}
    nw = now_of(ctx, mint, base)
    daily = daily_of(ctx, mint)
    hourly = hourly_of(ctx, mint, now)
    sym = base.get("symbol") or one(ctx.con("midcap"), "SELECT symbol FROM tokens WHERE mint=?", (mint,))
    sym = (sym[0] if isinstance(sym, tuple) else sym) or mint[:6]
    created = base.get("created_ts") or (one(ctx.con("midcap"), "SELECT created_ts FROM tokens WHERE mint=?", (mint,))
                                         or (None,))[0]
    d = {"mint": mint, "symbol": str(sym).strip()[:20], "name": base.get("name"), "ts": now, "delay_s": delay_s,
         "src": base.get("src"), "top": base.get("top"), "now": nw}
    supply = (nw["mcap"] / nw["price"]) if nw.get("mcap") and nw.get("price") else None
    last = daily[-180:]
    d["hist"] = {"px": [(c[0], c[4]) for c in last], "vol": [(c[0], round(c[5])) for c in last if c[5]],
                 "mc": [(c[0], round(c[4] * supply)) for c in last] if supply else [],
                 "liq": [(t, liq) for t, liq, _v in liq_hist(ctx, mint, now)]}
    d["days"] = len(daily)
    d["chg"] = {"7d": _ago(daily, 7), "30d": _ago(daily, 30), "90d": _ago(daily, 90)}
    d["range"] = range_of(daily, now)
    d["m"] = metrics_of(ctx, daily, hourly, created, now)
    d["bounces"] = bounce_list(daily, ctx.crash())
    d["calls"] = calls_of(ctx, mint, now, delay_s)
    d["holders"] = holders_of(ctx, mint)
    d["listing"] = listing_of(ctx, mint, d["symbol"])
    d["lsig"] = lsig_of(ctx, mint, now, delay_s)
    d["ins"] = insiders_of(ctx, mint, now, delay_s)
    if not delay_s:
        d["ours"] = ours_of(ctx, mint, now, hourly)
    first = [x[0] for x in (one(ctx.con("midcap"), "SELECT first_ts FROM tokens WHERE mint=?", (mint,)),
                            one(ctx.con("public"), "SELECT MIN(ts) FROM coin_hist WHERE mint=?", (mint,))) if x and x[0]]
    d["since"] = min(first) if first else None   # since when MemeSonar has measured it itself
    d["enough"] = int(d["days"] >= ENOUGH_DAYS and bool(nw.get("mcap")))
    return d


def basis(d):
    """The numbers the AI opinion is given (no address, no internal name, no cost): a compact, rounded dict."""
    def r(x, n=2):
        return round(x, n) if isinstance(x, (int, float)) else x
    nw, m, rg, cs, h = d.get("now") or {}, d.get("m") or {}, d.get("range") or {}, (d.get("calls") or {}).get("stats") \
        or {}, d.get("holders") or {}
    listed = [x["ex"] for x in d.get("listing") or [] if x["st"] == "da"]
    ins = d.get("ins") or {}
    return {
        "symbol": d.get("symbol"), "name": d.get("name"), "market_cap_usd": r(nw.get("mcap"), 0),
        "liquidity_usd": r(nw.get("liq"), 0), "volume_24h_usd": r(nw.get("vol24"), 0), "change_24h_pct": r(nw.get("chg24")),
        "change_7d_pct": r((d.get("chg") or {}).get("7d")), "change_30d_pct": r((d.get("chg") or {}).get("30d")),
        "change_90d_pct": r((d.get("chg") or {}).get("90d")), "days_of_price_history": d.get("days"),
        "age_days": r(m.get("age_d"), 0), "typical_daily_range_pct": rg.get("med"),
        "daily_range_p25_p75_pct": [rg.get("p25"), rg.get("p75")] if rg else None,
        "position_in_30d_range_pct": rg.get("pos30"), "drawdown_from_ath_pct": r((m.get("dd_ath") or 0) * 100, 1)
        if m.get("dd_ath") is not None else None,
        "days_with_volume_over_50k_share_30d": m.get("pers30"), "same_share_90d": m.get("pers90"),
        "btc_daily_correlation": m.get("corr_d"), "btc_daily_beta": m.get("beta_d"),
        "share_higher_72h_after_btc_up_3pct_days": m.get("btc_up_hit"), "btc_up_days_measured": m.get("btc_up_n"),
        "bounces_from_30d_range_bottom": m.get("bounce_n"), "bounce_share_reaching_15pct_in_7d": m.get("hit15"),
        "bounce_median_best_7d_pct": m.get("med_up7"), "bounce_median_worst_7d_pct": m.get("med_dn7"),
        "category": m.get("cat"),
        "influencer_calls_clean": cs.get("n"), "calls_share_higher_1h_after": cs.get("up1h"),
        "calls_share_reaching_15pct_24h": cs.get("hit15"), "calls_median_24h_result": cs.get("med24"),
        "calls_share_rugged": cs.get("rug"),
        "holders_insider_share_pct_excl_exchanges_lp": h.get("insider_ex"), "holders_top10_share_pct_excl": h.get("top10_ex"),
        "holders_exchange_share_pct": (h.get("shares") or {}).get("exchange"), "holders_hhi": h.get("hhi"),
        "holder_count": (h.get("rc") or {}).get("holders") or h.get("n_holders_jup"),
        "mint_authority_active": bool((h.get("rc") or {}).get("mint_auth")) if h.get("rc") else None,
        "freeze_authority_active": bool((h.get("rc") or {}).get("freeze_auth")) if h.get("rc") else None,
        "listed_on_exchanges": listed, "insider_events_measured": ins.get("events"),
        "wallets_sold_into_jumps": ins.get("sold_into"), "smart_money_signals": ins.get("smart_sig"),
    }
