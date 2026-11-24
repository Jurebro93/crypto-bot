"""Tržište i tokeni (20.11., vlasnik: "kad se gledaju povijesni podaci tokena, gledaj Fear & Greed i cijenu BTC-a i
poravnaj rast i pad na vremenskoj crti ... prate li tokeni tržište? Ako idu protiv tržišta, to je moguća manipulacija
... to treba napraviti za sve postojeće skokove i padove ... Koreliraj volumen meme platformi s rastom.").

ANALYSIS ONLY (shadow): nothing here is read by an entry, an exit, a cap, the demo or real money. A gate would be a
later, separate decision of the owner.

One command (run_market.py trziste, run_sched every TRZISTE_EVERY_MIN, light) does:

  backfill  once (market.db trziste_kv "backfill"), free sources only: BTC daily CLOSES for 400 days (DefiLlama coins,
            one call; market.db `btc` holds the price at the hour of the fetch, not the close), Fear & Greed since 2018
            (alternative.me ?limit=0, one call, into the existing `fng` table) and, only for a meme platform whose
            `daily` history is shorter than HISTORY_D days, its DefiLlama summary/dexs/<slug> (one call a slug).
            A normal run: one call (the last 15 BTC closes); F&G and the platform volumes come from the hourly
            collector (run_market.py collect) that already stores them.
  days      market.db trziste_dan, one row a UTC day: BTC close and its 1 / 7 day change, the 10-day average, the
            BTC colour, F&G value and class, the meme platforms' volume (pump.fun + PumpSwap + LaunchLab/bonk.fun +
            Meteora DBC), its 7-day change and trend. trziste_4h: the same colour on 4-hour BTC closes (the hourly
            BTC of veliki.db / market.db, 60 days), so recent charts are finer.
  tokens    every token of midcap.db and veliki.db with daily candles (c1d) and a market cap >= MIN_MCAP (30k): its
            daily returns against BTC's (correlation, beta, the whole history and the last 30 days), the share of days
            it moved in BTC's direction, its "against the market" days. Table trziste_tok.
  events    every stored jump (insajderi.db i2_events with a pump tier, read-only; without that database the same jump
            rule on the daily candles) and every DROP (no drop table exists: derived here from the daily candles with
            the mirror of insajderi/events.daily_events' rule: a close <= 1 / 1.5 of a high close within one day, i.e.
            -33 %, or <= 1 / 2 of it within 3 days, -50 %; insajderi.events.find_jumps on 1 / price). Table
            trziste_dog. Tagged with the market state of the start day and of the day before.
  trades    the existing trades with their real result after cost (never under the 3 % round trip): the day rule's
            replay (midcap.db kv "replay_trades", written by veliki/replay.run), the shadow book (league.db
            veliki_sjena, profile "pravilo"), the demo of the midcap day rule (league.db veliki_trades of PAPER_USER)
            and the wallet-following measurement (league.db signal_mjera, net at 0.1 SOL). Each entry is tagged with
            the state KNOWN at its entry (state_at: BTC colour and volume trend of the day before, F&G of the day,
            published at 00:00 UTC). Mean per entry, 90 % interval over TOKEN-DAYS (as veliki/sjena.table), n.
  filters   the owner's hypothesis as pre-declared filters (FILTERS); chosen on the first two thirds of the days,
            reported on the last third (out of sample), with how many entries the filter removes.
  lead/lag  the daily change of the meme platforms' volume against the number of jumps and the median midcap return
            on the same day and 1-3 days before / after.

The BTC colour of a day (point in time: only closes up to that day's close; the close of day d is the price at the
next UTC midnight):
  zeleno (raste)   7-day change >= +3 % and the close at or above its 10-day average
  crveno (pada)    7-day change <= -3 % and the close below its 10-day average
  zuto (konsolidira) everything else
(+3 % is market/makro's up7; the 10-day average is the "short moving average".)
Fear & Greed classes as alternative.me labels them (checked against its value_classification 20.11.2026: Extreme
Fear 0-25, Fear 26-46, Neutral 47-54, Greed 55-75, Extreme Greed 76-100). Volume trend: rising >= +10 % over its
7-day sum against the 7 days before, falling <= -10 %, else flat.

Wording rule (the page, the MCP tool, the council): a token that often moves against the market "kreće se neovisno o
tržištu: mogući vlastiti katalizator ili umjetno održavana cijena (statistika, ne tvrdnja)". Never an accusation.
"""
import json
import math
import os
import sqlite3
import statistics
import time
from collections import defaultdict

from market import store

PREFIX = "tržište i tokeni: "
D = 86400
H4 = 4 * 3600
HISTORY_D = 200            # the daily market table must cover at least this (the pump history is 180 days)
EVENT_D = 180
KEEP_D = 400
MEME_SLUGS = ("pump.fun", "pumpswap", "launchlab", "meteora-dynamic-bonding-curve")
MEME_NAMES = {"pump.fun": "pump.fun", "pumpswap": "PumpSwap", "launchlab": "LaunchLab (bonk.fun)",
              "meteora-dynamic-bonding-curve": "Meteora DBC"}
UP7 = 0.03                 # market/makro.DEFAULT["up7"]
MA_D = 10
VOL_TREND = 0.10
FNG_CLASSES = ((25, "ekstremni_strah"), (46, "strah"), (54, "neutralno"), (75, "pohlepa"), (100, "ekstremna_pohlepa"))
FNG_HR = {"ekstremni_strah": "ekstremni strah", "strah": "strah", "neutralno": "neutralno", "pohlepa": "pohlepa",
          "ekstremna_pohlepa": "ekstremna pohlepa"}
FNG_API = {"Extreme Fear": "ekstremni_strah", "Fear": "strah", "Neutral": "neutralno", "Greed": "pohlepa",
           "Extreme Greed": "ekstremna_pohlepa"}
BOJE = ("zeleno", "zuto", "crveno")
BOJA_HR = {"zeleno": "zeleno (raste)", "zuto": "žuto (konsolidira)", "crveno": "crveno (pada)"}
BOJA_ADJ = {"zeleno": "zelen", "zuto": "žut", "crveno": "crven"}
VOL_HR = {"raste": "raste", "ravno": "ravno", "pada": "pada"}
MIN_MCAP = 30_000          # CLAUDE.md: tokens under 30k are not analysed here
MIN_TD = 20                # token-days before a cell is spoken of (veliki/sjena.MIN_CLUSTERS)
MIN_DAYS_CORR = 20         # a token's correlation needs this many paired days
MIN_TOKENS = 10            # "Prate li tokeni tržište?" needs this many tokens
STRONG_K = 2.0             # a strong move = at least STRONG_K x the token's median absolute daily move
FLAG_SHARE = 0.08          # flag "ide protiv tržišta": against days >= FLAG_SHARE of its green / red days,
FLAG_MIN = 4               # ... at least this many, and at least as many as its strong moves WITH the market
FOLLOW_CORR = 0.3          # a token "follows" the market at a correlation >= this
TIER_15, TIER_2 = 15_000_000, 2_000_000
TIERS = ("15-200M", "2-15M")
DROP_X1D, DROP_X3D = 0.50, 1.00   # in 1 / price: the mirror of insajderi mkt_x1d / mkt_x3d (-33 % / -50 %)
RT_FLOOR = 0.03
TRAIN_FRAC = 2 / 3
LAGS = (-3, -2, -1, 0, 1, 2, 3)
ONCE_KEY = "vijece_claude_rezim_2011"
SOURCE_LINE = ("Izvori: BTC i volumen platformi DefiLlama, Fear & Greed alternative.me, svijeće tokena GeckoTerminal "
               "(ono što alat već sprema).")
WORDING = ("Kreće se neovisno o tržištu: mogući vlastiti katalizator ili umjetno održavana cijena "
           "(statistika, ne tvrdnja).")
RULE_HR = ("BTC je zelen kad je u 7 dana porastao barem 3 % i nije ispod prosjeka zadnjih 10 dana, crven kad je pao "
           "barem 3 % i ispod je tog prosjeka, a žut u svim ostalim danima.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trziste_btc (day INTEGER PRIMARY KEY, close REAL);
CREATE TABLE IF NOT EXISTS trziste_plat (day INTEGER, slug TEXT, volume REAL, PRIMARY KEY (day, slug));
CREATE TABLE IF NOT EXISTS trziste_dan (day INTEGER PRIMARY KEY, btc REAL, btc_chg1 REAL, btc_chg7 REAL, btc_ma REAL,
    boja TEXT, fng INTEGER, fng_klasa TEXT, vol REAL, vol_chg7 REAL, vol_trend TEXT);
CREATE TABLE IF NOT EXISTS trziste_4h (ts INTEGER PRIMARY KEY, btc REAL, boja TEXT);
CREATE TABLE IF NOT EXISTS trziste_tok (token TEXT PRIMARY KEY, symbol TEXT, src TEXT, mcap REAL, n INTEGER,
    corr REAL, beta REAL, n30 INTEGER, corr30 REAL, beta30 REAL, isti_smjer REAL, obojanih INTEGER, protiv INTEGER,
    uz INTEGER, protiv_udio REAL, tipicno REAL, oznaka INTEGER);
CREATE TABLE IF NOT EXISTS trziste_dog (token TEXT, day INTEGER, kind TEXT, size REAL, tier TEXT, src TEXT,
    t0 INTEGER, PRIMARY KEY (token, t0, kind));
CREATE INDEX IF NOT EXISTS trziste_dog_day ON trziste_dog (day);
CREATE TABLE IF NOT EXISTS trziste_kv (k TEXT PRIMARY KEY, v TEXT);
"""


def ensure(con):
    con.executescript(SCHEMA)


def kv_get(con, k, default=None):
    try:
        r = con.execute("SELECT v FROM trziste_kv WHERE k=?", (k,)).fetchone()
    except sqlite3.Error:
        return default
    try:
        return json.loads(r[0]) if r else default
    except (TypeError, ValueError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO trziste_kv VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


# ---------- the paths (tests pass their own) -------------------------------------------------------------------------

def paths():
    """{name: path} of the databases read here (all read-only but market.db)."""
    out = {"market": store.DB}
    for name, fn in (("midcap", lambda: __import__("veliki.midcap", fromlist=["x"]).db_path()),
                     ("veliki", lambda: __import__("veliki.store", fromlist=["x"]).db_path()),
                     ("insajderi", lambda: __import__("insajderi.store", fromlist=["x"]).db_path()),
                     ("league", lambda: __import__("league.store", fromlist=["x"]).DB)):
        try:
            out[name] = fn()
        except Exception:  # noqa: BLE001 - a missing module means no such data
            out[name] = None
    return out


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


# ---------- small statistics -----------------------------------------------------------------------------------------

def corr(xs, ys):
    """Pearson correlation of paired lists, None under 3 pairs or without variance."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def beta(ys, xs):
    """Slope of ys on xs (the token's beta against BTC), None without variance."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def stats(rows):
    """{n, k, mean, lo, hi, hit, dovoljno} of entries [{token, ts, ret}]: mean net return a trade, the 90 % interval
    over TOKEN-DAYS (one token's entries of one UTC day are one cluster; the interval of the cluster means, as
    veliki/sjena.table), dovoljno = at least MIN_TD token-days."""
    if not rows:
        return {"n": 0, "k": 0, "mean": None, "lo": None, "hi": None, "hit": None, "dovoljno": False}
    cl = defaultdict(list)
    for r in rows:
        cl[(r["token"], int(r["ts"]) // D)].append(r["ret"])
    means = [sum(v) / len(v) for v in cl.values()]
    k, n = len(means), len(rows)
    mean = sum(r["ret"] for r in rows) / n
    lo = hi = None
    if k >= 2:
        m = sum(means) / k
        sd = (sum((x - m) ** 2 for x in means) / (k - 1)) ** 0.5
        lo, hi = m - 1.645 * sd / k ** 0.5, m + 1.645 * sd / k ** 0.5
    rnd = lambda x: None if x is None else round(x, 5)  # noqa: E731
    return {"n": n, "k": k, "mean": rnd(mean), "lo": rnd(lo), "hi": rnd(hi),
            "hit": round(sum(1 for r in rows if r["ret"] > 0) / n, 4), "dovoljno": k >= MIN_TD}


# ---------- the market day ---------------------------------------------------------------------------------------------

def fng_class(v):
    """alternative.me's class of a Fear & Greed value (0-100), None for None."""
    if v is None:
        return None
    for top, name in FNG_CLASSES:
        if v <= top:
            return name
    return FNG_CLASSES[-1][1]


def colour_rule(chg7, close, ma):
    """The BTC colour from the 7-day change and the close against its 10-day average (see the module text)."""
    if chg7 is None or close is None or ma is None:
        return None
    if chg7 >= UP7 and close >= ma:
        return "zeleno"
    if chg7 <= -UP7 and close < ma:
        return "crveno"
    return "zuto"


def colours(closes):
    """{day: {"close", "chg1", "chg7", "ma", "boja"}} from {day: close}: day d uses only the closes of days <= d (point in
    time); a day without the close 7 days before or without all 10 closes of its average has no colour."""
    out = {}
    for d in sorted(closes):
        c = closes[d]
        prev, wk = closes.get(d - D), closes.get(d - 7 * D)
        win = [closes.get(d - i * D) for i in range(MA_D)]
        ma = sum(win) / MA_D if all(v is not None for v in win) else None
        chg7 = c / wk - 1 if wk else None
        out[d] = {"close": c, "chg1": c / prev - 1 if prev else None, "chg7": chg7, "ma": ma,
                  "boja": colour_rule(chg7, c, ma)}
    return out


def vol_trends(vol):
    """{day: (chg7, trend)} of the meme platforms' daily volume {day: usd}: the 7 days ending on d against the 7 before;
    needs all 14 days."""
    out = {}
    for d in vol:
        a = [vol.get(d - i * D) for i in range(7)]
        b = [vol.get(d - i * D) for i in range(7, 14)]
        if any(v is None for v in a + b) or not sum(b):
            continue
        chg = sum(a) / sum(b) - 1
        out[d] = (chg, "raste" if chg >= VOL_TREND else "pada" if chg <= -VOL_TREND else "ravno")
    return out


def meme_volume(con):
    """{day: summed volume of MEME_SLUGS}: market.db daily (the hourly collector) first, trziste_plat (the backfill)
    for a slug-day daily does not have. A day counts when at least one slug reported."""
    per = defaultdict(dict)
    for day, slug, v in _q(con, "SELECT day, slug, volume FROM trziste_plat"):
        per[day][slug] = v
    marks = ",".join("?" * len(MEME_SLUGS))
    for day, slug, v in _q(con, f"SELECT day, slug, volume FROM daily WHERE slug IN ({marks})", MEME_SLUGS):
        per[day][slug] = v
    return {d: sum(float(v or 0) for v in s.values()) for d, s in per.items() if s}


def build_days(con, now):
    """Recompute market.db trziste_dan from trziste_btc, fng and the platform volumes. Returns {day: row dict}."""
    today = int(now) // D * D
    closes = {d: c for d, c in _q(con, "SELECT day, close FROM trziste_btc WHERE day < ?", (today,)) if c}
    col = colours(closes)
    fng = {d: v for d, v in _q(con, "SELECT day, value FROM fng WHERE day <= ?", (today,))}
    vol = {d: v for d, v in meme_volume(con).items() if d < today}
    vt = vol_trends(vol)
    days = sorted(set(col) | set(fng) | set(vol))
    days = [d for d in days if d >= today - KEEP_D * D]
    rows, out = [], {}
    for d in days:
        c = col.get(d) or {}
        f = fng.get(d)
        chg, tr = vt.get(d, (None, None))
        r = {"day": d, "btc": c.get("close"), "btc_chg1": c.get("chg1"), "btc_chg7": c.get("chg7"), "btc_ma": c.get("ma"),
             "boja": c.get("boja"), "fng": f, "fng_klasa": fng_class(f), "vol": vol.get(d), "vol_chg7": chg,
             "vol_trend": tr}
        out[d] = r
        rows.append(tuple(r.values()))
    con.execute("DELETE FROM trziste_dan")
    con.executemany("INSERT INTO trziste_dan VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return out


def load_days(con):
    keys = ("day", "btc", "btc_chg1", "btc_chg7", "btc_ma", "boja", "fng", "fng_klasa", "vol", "vol_chg7", "vol_trend")
    return {r[0]: dict(zip(keys, r)) for r in _q(con, f"SELECT {', '.join(keys)} FROM trziste_dan ORDER BY day")}


def state_at(days, ts):
    """The market state KNOWN at ts (for an entry): the BTC colour and the volume trend of the day before (a day's close
    is known only at its end), the F&G of the day (published at 00:00 UTC), and the colour of the day before that (to
    see "BTC just turned up"). Values None when unknown."""
    d = int(ts) // D * D
    y = days.get(d - D) or {}
    yy = days.get(d - 2 * D) or {}
    f = (days.get(d) or {}).get("fng")
    if f is None:
        f = y.get("fng")
    return {"boja": y.get("boja"), "boja_prije": yy.get("boja"), "fng": f, "fng_klasa": fng_class(f),
            "vol_trend": y.get("vol_trend")}


def zajedno(s):
    """One combined label: BTC colour / F&G group (strah = below 47, else bez straha)."""
    if not s.get("boja") or s.get("fng") is None:
        return None
    return f"{s['boja']}/{'strah' if s['fng'] < 47 else 'bez_straha'}"


def build_4h(con, hourly, now):
    """trziste_4h from hourly BTC [(ts, usd)]: the 4-hour close and the colour on 4-hour bars (7 days = 42 bars, the
    average of the last 60 bars = 10 days); point in time like the daily rule. Returns the rows."""
    b = {}
    for ts, px in sorted(hourly):
        if px:
            b[int(ts) // H4 * H4] = float(px)   # the last hourly close inside a 4 h bar closes it
    cur = int(now) // H4 * H4
    keys = sorted(k for k in b if k < cur)
    rows = []
    for i, k in enumerate(keys):
        prev = b.get(k - 42 * H4)
        win = [b.get(k - j * H4) for j in range(60)]
        ma = sum(win) / 60 if all(v is not None for v in win) else None
        rows.append((k, b[k], colour_rule(b[k] / prev - 1 if prev else None, b[k], ma)))
    con.execute("DELETE FROM trziste_4h")
    con.executemany("INSERT INTO trziste_4h VALUES (?,?,?)", rows)
    return rows


def hourly_btc(p):
    """[(ts, usd)] hourly BTC: veliki.db btc_h (60 days) else market.db btc_h (14 days)."""
    for name in ("veliki", "market"):
        con = _ro(p.get(name))
        try:
            rows = _q(con, "SELECT ts, usd FROM btc_h ORDER BY ts")
        finally:
            if con is not None:
                con.close()
        if rows:
            return rows
    return []


# ---------- backfill (free sources, once) -----------------------------------------------------------------------------

def need_backfill(con, now):
    """{"btc": bool, "fng": bool, "slugs": [slug]} of what the stored history lacks for HISTORY_D days."""
    since = int(now) // D * D - HISTORY_D * D
    n = lambda sql, a=(): (_q(con, sql, a) or [[0]])[0][0] or 0  # noqa: E731
    out = {"btc": n("SELECT COUNT(*) FROM trziste_btc WHERE day >= ?", (since,)) < HISTORY_D - 5,
           "fng": n("SELECT COUNT(*) FROM fng WHERE day >= ?", (since,)) < HISTORY_D - 5, "slugs": []}
    for s in MEME_SLUGS:
        have = n("SELECT COUNT(*) FROM (SELECT day FROM daily WHERE slug=? AND day>=? UNION SELECT day FROM trziste_plat "
                 "WHERE slug=? AND day>=?)", (s, since, s, since))
        if have < HISTORY_D - 5:
            out["slugs"].append(s)
    return out


def btc_closes(days, now=None, fetch=None):
    """[(day, close)] BTC daily closes (DefiLlama, free): the price at a UTC midnight closes the day before."""
    from market import sources
    return sources.daily_closes("bitcoin", days, now, fetch=fetch)


def update(con, now, fetch=None, log=print):
    """The network part: once the backfill (what need_backfill lists), then each run the last 15 BTC closes.
    fetch: {"btc": fn(days), "fng": fn(limit), "slug": fn(slug)} (tests: no network). Returns the calls made."""
    from market import collect, sources
    f = {"btc": lambda days: btc_closes(days, now), "fng": sources.fear_greed, "slug": sources.protocol_daily,
         **(fetch or {})}
    calls, done = 0, kv_get(con, "backfill")
    need = need_backfill(con, now)
    today = int(now) // D * D
    big = not done or need["btc"]
    try:
        pts = f["btc"](KEEP_D if big else 15)
        calls += 1
        con.executemany("INSERT OR REPLACE INTO trziste_btc VALUES (?,?)", [(int(d) // D * D, float(c)) for d, c in pts
                                                                            if c and int(d) < today])
    except Exception as e:  # noqa: BLE001 - one failed source never stops the analysis
        log(PREFIX + f"BTC zatvaranja nisu dohvaćena ({type(e).__name__}: {e})")
    retry = bool(done) and now - int(done.get("ts") or 0) >= D and bool(need["fng"] or need["slugs"])
    if not done or retry:   # the backfill once; what it could not get is tried again at most once a day
        if need["fng"]:
            try:
                collect.fng(con, f["fng"](0), now)
                calls += 1
            except Exception as e:  # noqa: BLE001
                log(PREFIX + f"Fear & Greed povijest nije dohvaćena ({type(e).__name__}: {e})")
        for s in need["slugs"]:
            try:
                # yesterday may still be filling up on DefiLlama: the hourly collector's `daily` brings it complete
                rows = [(int(d) // D * D, s, float(v)) for d, v in f["slug"](s) if int(d) < today - D]
                calls += 1
                con.executemany("INSERT OR REPLACE INTO trziste_plat VALUES (?,?,?)", rows)
            except Exception as e:  # noqa: BLE001
                log(PREFIX + f"povijest {s} nije dohvaćena ({type(e).__name__}: {e})")
        after = need_backfill(con, now)
        kv_put(con, "backfill", {"ts": int(now), "calls": calls, "missing": after})
    con.execute("DELETE FROM trziste_plat WHERE day < ?", (today - KEEP_D * D,))
    con.execute("DELETE FROM trziste_btc WHERE day < ?", (today - KEEP_D * D,))
    return calls


# ---------- the tokens ------------------------------------------------------------------------------------------------

def load_tokens(p, now, days=HISTORY_D):
    """({mint: {"symbol", "mcap", "src", "closes": [(day, close)]}}, skipped {"ispod_30k", "bez_svijeca"}) of the
    midcap collector's and the veliki list's tokens with daily candles; midcap.db first (its market cap)."""
    since = int(now) // D * D - days * D
    out, skip = {}, {"ispod_30k": 0, "bez_svijeca": 0}
    seen = set()
    for label in ("midcap", "veliki"):
        con = _ro(p.get(label))
        if con is None:
            continue
        try:
            sql = ("SELECT mint, symbol, mcap FROM tokens" if label == "midcap" else
                   "SELECT mint, symbol, mcap FROM tokens UNION SELECT mint, symbol, mcap FROM hist")
            for mint, sym, mcap in _q(con, sql):
                if mint in seen:
                    continue
                seen.add(mint)
                if mcap is not None and mcap < MIN_MCAP:
                    skip["ispod_30k"] += 1
                    continue
                cl = [(int(ts) // D * D, float(c)) for ts, c in _q(con, "SELECT ts, c FROM c1d WHERE token=? AND ts>=? "
                                                                        "ORDER BY ts", (mint, since)) if c]
                if len(cl) < 3:
                    skip["bez_svijeca"] += 1
                    continue
                out[mint] = {"symbol": sym, "mcap": mcap, "src": label, "closes": cl}
        finally:
            con.close()
    return out, skip


def token_returns(closes):
    """{day: daily return} of consecutive daily closes [(day, close)]: the close of day d against day d-1."""
    out = {}
    for (d0, c0), (d1, c1) in zip(closes, closes[1:]):
        if d1 - d0 == D and c0 > 0:
            out[d1] = c1 / c0 - 1
    return out


def follow(rets, days, now):
    """A token's following of the market from its daily returns {day: r} and the market days: correlation and beta
    against BTC's daily return (the whole history and the last 30 days), the share of moving days in BTC's direction,
    the against-the-market days (up >= STRONG_K x its typical move on a red day, down as much on a green day), the flag.
    None under MIN_DAYS_CORR paired days."""
    pairs = [(d, r, days[d]["btc_chg1"]) for d, r in sorted(rets.items())
             if d in days and days[d].get("btc_chg1") is not None]
    if len(pairs) < MIN_DAYS_CORR:
        return None
    ys, xs = [r for _d, r, _b in pairs], [b for _d, _r, b in pairs]
    last = [(r, b) for d, r, b in pairs if d >= int(now) // D * D - 30 * D]
    moving = [(r, b) for r, b in zip(ys, xs) if r and b]
    typ = _med([abs(r) for r in ys]) or 0.0
    against = coloured = with_ = 0
    for d, r, _b in pairs:
        c = days[d].get("boja")
        if c not in ("zeleno", "crveno"):
            continue
        coloured += 1
        if typ and ((c == "crveno" and r >= STRONG_K * typ) or (c == "zeleno" and r <= -STRONG_K * typ)):
            against += 1
        elif typ and ((c == "zeleno" and r >= STRONG_K * typ) or (c == "crveno" and r <= -STRONG_K * typ)):
            with_ += 1
    share = against / coloured if coloured else None
    rnd = lambda x, n=4: None if x is None else round(x, n)  # noqa: E731
    return {"n": len(pairs), "corr": rnd(corr(ys, xs)), "beta": rnd(beta(ys, xs), 3), "n30": len(last),
            "corr30": rnd(corr([a for a, _ in last], [b for _, b in last])) if len(last) >= 10 else None,
            "beta30": rnd(beta([a for a, _ in last], [b for _, b in last]), 3) if len(last) >= 10 else None,
            "isti_smjer": rnd(sum(1 for r, b in moving if (r > 0) == (b > 0)) / len(moving)) if moving else None,
            "obojanih": coloured, "protiv": against, "uz": with_, "protiv_udio": rnd(share), "tipicno": rnd(typ),
            "oznaka": bool(share is not None and against >= FLAG_MIN and share >= FLAG_SHARE and against >= with_)}


# ---------- jumps and drops -------------------------------------------------------------------------------------------

def tier_of(mc):
    if mc is None:
        return None
    return "15-200M" if mc >= TIER_15 else "2-15M" if mc >= TIER_2 else None


def jumps_stored(p, now):
    """[event] of insajderi.db i2_events with a pump tier (pumpa15 / pumpa2) of the last EVENT_D days, read-only;
    the Telegram call events are left out as insajderi.events.load does."""
    con = _ro(p.get("insajderi"))
    if con is None:
        return None
    try:
        try:
            from insajderi.events import NOT_TG_EVENT
        except Exception:  # noqa: BLE001
            NOT_TG_EVENT = "1"
        rows = _q(con, "SELECT token, symbol, t0, peak_x, tier, src FROM i2_events WHERE tier IN ('pumpa15', 'pumpa2') "
                       f"AND t0 >= ? AND {NOT_TG_EVENT}", (int(now) - EVENT_D * D,))
    finally:
        con.close()
    tmap = {"pumpa15": "15-200M", "pumpa2": "2-15M"}
    return [{"token": t, "symbol": s, "t0": int(t0), "kind": "skok", "size": px, "tier": tmap.get(tier),
             "src": "insajderi " + (src or "")} for t, s, t0, px, tier, src in rows]


def _find(closes, x1, x3):
    from insajderi.events import find_jumps
    return find_jumps(closes, x1, x3, D, 3 * D, ("1d", "3d"))


def derive(tokens, now, drops=True):
    """[event] from the daily closes: drops (the mirror rule on 1 / price) or, with drops False, jumps by the same rule
    as insajderi.events.daily_events (+50 % in a day / +100 % in 3 days). The tier by the market cap at the start
    (today's MC x the start close / the last close); a start under MIN_MCAP is left out."""
    since = int(now) - EVENT_D * D
    out = []
    for mint, t in tokens.items():
        cl = [(d, c) for d, c in t["closes"] if d >= since]
        if len(cl) < 3:
            continue
        last = cl[-1][1]
        series = [(d, 1.0 / c) for d, c in cl] if drops else cl
        x1, x3 = (DROP_X1D, DROP_X3D) if drops else (0.50, 1.00)
        for t0, base, _pk_ts, pk, _k in _find(series, x1, x3):
            start = 1.0 / base if drops else base
            mc0 = t["mcap"] * start / last if t.get("mcap") and last else None
            if mc0 is not None and mc0 < MIN_MCAP:
                continue
            x = pk / base - 1
            out.append({"token": mint, "symbol": t.get("symbol"), "t0": int(t0), "kind": "pad" if drops else "skok",
                        "size": round(x / (1 + x), 4) if drops else round(x, 4), "tier": tier_of(mc0), "src": "c1d"})
    return out


def tag(events, days):
    """Each event gets the state of its start day (boja, fng_klasa, vol_trend) and of the day before (*_prije)."""
    for e in events:
        d = e["t0"] // D * D
        a, b = days.get(d) or {}, days.get(d - D) or {}
        e["day"] = d
        for k in ("boja", "fng_klasa", "vol_trend"):
            e[k] = a.get(k)
            e[k + "_prije"] = b.get(k)
    return events


def token_days(tokens, days, now):
    """{(dim, value, tier): token-days} of the daily candles of the last EVENT_D days in each market state (dim boja /
    fng_klasa / vol_trend, the day itself and *_prije the day before); tier "svi" and by the day's estimated MC."""
    since = int(now) // D * D - EVENT_D * D
    out = defaultdict(int)
    for t in tokens.values():
        last = t["closes"][-1][1] if t["closes"] else None
        for d, c in t["closes"]:
            if d < since:
                continue
            mc = t["mcap"] * c / last if t.get("mcap") and last else None
            tiers = ("svi", tier_of(mc)) if tier_of(mc) else ("svi",)
            a, b = days.get(d) or {}, days.get(d - D) or {}
            for k in ("boja", "fng_klasa", "vol_trend"):
                for dim, src in ((k, a), (k + "_prije", b)):
                    v = src.get(k)
                    if v:
                        for ti in tiers:
                            out[(dim, v, ti)] += 1
    return out


def event_tables(events, td):
    """{dim: [{"stanje", "tier", "skokova", "padova", "token_dana", "skok_na_100", "pad_na_100", "skok_med", "pad_med"}]}
    for dim in boja / fng_klasa / vol_trend and their *_prije."""
    out = {}
    for dim in ("boja", "fng_klasa", "vol_trend", "boja_prije", "fng_klasa_prije", "vol_trend_prije"):
        cells = defaultdict(lambda: {"skok": [], "pad": []})
        for e in events:
            v = e.get(dim)
            if not v:
                continue
            for ti in ("svi", e.get("tier")):
                if ti:
                    cells[(v, ti)][e["kind"]].append(e["size"])
        vals = sorted({v for (d, v, _t) in td if d == dim} | {v for v, _t in cells})
        rows = []
        for ti in ("svi",) + TIERS:
            for v in vals:
                c = cells.get((v, ti), {"skok": [], "pad": []})
                n = td.get((dim, v, ti), 0)
                rows.append({"stanje": v, "tier": ti, "skokova": len(c["skok"]), "padova": len(c["pad"]),
                             "token_dana": n,
                             "skok_na_100": round(100 * len(c["skok"]) / n, 3) if n else None,
                             "pad_na_100": round(100 * len(c["pad"]) / n, 3) if n else None,
                             "skok_med": round(_med(c["skok"]), 4) if c["skok"] else None,
                             "pad_med": round(_med(c["pad"]), 4) if c["pad"] else None})
        out[dim] = rows
    return out


# ---------- the existing trades ---------------------------------------------------------------------------------------

def _floor(ret, rt):
    """ret net of the trade's own round trip, lowered to the RT_FLOOR when that round trip was cheaper."""
    try:
        rt = float(rt)
    except (TypeError, ValueError):
        return ret
    if rt > 0.5:   # stored in percent
        rt /= 100
    return ret - max(0.0, RT_FLOOR - rt)


def load_sets(p):
    """{set: [{"token", "ts", "ret"}]}: replay (midcap.db kv replay_trades), sjena (league.db veliki_sjena "pravilo"),
    demo (league.db veliki_trades of the day rule's demo account), novcanici (league.db signal_mjera, net at 0.1 SOL).
    Every ret is net after cost, never under the 3 % round trip."""
    out = {"replay": [], "sjena": [], "demo": [], "novcanici": []}
    con = _ro(p.get("midcap"))
    try:
        r = _q(con, "SELECT v FROM kv WHERE k='replay_trades'")
        if r:
            try:
                for tok, ts, ret in (json.loads(r[0][0]) or {}).get("trades") or []:
                    out["replay"].append({"token": tok, "ts": int(ts), "ret": float(ret)})
            except (TypeError, ValueError):
                pass
    finally:
        if con is not None:
            con.close()
    con = _ro(p.get("league"))
    try:
        for tok, ts, ret, rt in _q(con, "SELECT token, opened_ts, ret, rt FROM veliki_sjena WHERE status='closed' AND "
                                        "ret IS NOT NULL AND profil='pravilo'"):
            out["sjena"].append({"token": tok, "ts": int(ts), "ret": _floor(float(ret), rt)})
        try:
            from trade import settings as tset
            user = tset.PAPER_USER
        except Exception:  # noqa: BLE001
            user = "autopilot-paper"
        demo = _q(con, "SELECT token, opened_ts, ret, rt FROM veliki_trades WHERE user=? AND status='closed' AND ret IS "
                       "NOT NULL AND COALESCE(varijanta, '') NOT LIKE 'nauceno:%'", (user,))
        if not demo:   # an older league.db without the varijanta column
            demo = _q(con, "SELECT token, opened_ts, ret, rt FROM veliki_trades WHERE user=? AND status='closed' AND "
                           "ret IS NOT NULL", (user,))
        for tok, ts, ret, rt in demo:
            out["demo"].append({"token": tok, "ts": int(ts), "ret": _floor(float(ret), rt)})
        for tok, ts, ret, mc in _q(con, "SELECT token, entry_ts, ret_net_01, entry_mcap FROM signal_mjera WHERE "
                                        "status='closed' AND ret_net_01 IS NOT NULL AND entry_ts IS NOT NULL"):
            if mc is None or mc >= MIN_MCAP:
                out["novcanici"].append({"token": tok, "ts": int(ts), "ret": float(ret)})
    finally:
        if con is not None:
            con.close()
    return out


SET_HR = {"replay": "povijesni test dnevnog pravila", "sjena": "knjiga sjene (profil pravilo)",
          "demo": "demo dnevnog pravila", "novcanici": "mjerenje praćenja novčanika"}

# the owner's hypothesis as pre-declared filters: keep(state) -> True when the entry is taken
FILTERS = {
    "bez_ekstremnog_straha": ("mirovati u ekstremnom strahu (F&G do 25)", lambda s: s["fng"] is not None and s["fng"] > 25),
    "bez_straha": ("mirovati u strahu (F&G ispod 47)", lambda s: s["fng"] is not None and s["fng"] >= 47),
    "samo_zeleno": ("kupovati samo kad je BTC zelen", lambda s: s["boja"] == "zeleno"),
    "prvi_zeleni": ("kupovati samo prvi zeleni dan nakon žutog ili crvenog",
                    lambda s: s["boja"] == "zeleno" and s["boja_prije"] in ("zuto", "crveno")),
    "zeleno_bez_straha": ("BTC zelen i F&G barem 47", lambda s: s["boja"] == "zeleno" and s["fng"] is not None
                          and s["fng"] >= 47),
    "zeleno_bez_ekstremnog": ("BTC zelen i F&G iznad 25", lambda s: s["boja"] == "zeleno" and s["fng"] is not None
                              and s["fng"] > 25),
}


def by_state(rows):
    """{dim: {value: stats}} for boja / fng_klasa / vol_trend / zajedno of tagged entries."""
    out = {}
    for dim in ("boja", "fng_klasa", "vol_trend", "zajedno"):
        g = defaultdict(list)
        for r in rows:
            v = r["s"].get(dim) if dim != "zajedno" else zajedno(r["s"])
            g[v or "nepoznato"].append(r)
        out[dim] = {k: stats(v) for k, v in sorted(g.items())}
    return out


def split(rows, frac=TRAIN_FRAC):
    """(train, test, split_day): the first `frac` of the distinct entry days train, the rest test (out of sample)."""
    days = sorted({int(r["ts"]) // D for r in rows})
    if len(days) < 3:
        return rows, [], None
    cut = days[min(len(days) - 1, max(1, int(math.ceil(len(days) * frac))))]
    return [r for r in rows if int(r["ts"]) // D < cut], [r for r in rows if int(r["ts"]) // D >= cut], cut * D


def oos(rows):
    """The filters chosen on the train days, reported on the test days: {"split", "train_n", "test_n", "base": stats,
    "filtri": {name: {"train", "test", "maknuto"}}, "odabran", "odabran_test", "razlika"}. A filter is chosen only
    with >= MIN_TD token-days on train after filtering and a train mean above the unfiltered one."""
    tr, te, cut = split(rows)
    out = {"split": cut, "train_dana": len({r["ts"] // D for r in tr}), "test_dana": len({r["ts"] // D for r in te}),
           "base_train": stats(tr), "base": stats(te), "filtri": {}, "odabran": None}
    for name, (_hr, keep) in FILTERS.items():
        a = [r for r in tr if keep(r["s"])]
        b = [r for r in te if keep(r["s"])]
        out["filtri"][name] = {"train": stats(a), "test": stats(b),
                               "maknuto": len(te) - len(b), "maknuto_udio": round(1 - len(b) / len(te), 4) if te else None}
    bt = out["base_train"]["mean"]
    best = None
    for name, f in out["filtri"].items():
        s = f["train"]
        if s["k"] >= MIN_TD and s["mean"] is not None and bt is not None and s["mean"] > bt:
            if best is None or s["mean"] > out["filtri"][best]["train"]["mean"]:
                best = name
    out["odabran"] = best
    if best:
        t = out["filtri"][best]["test"]
        out["odabran_test"] = t
        out["razlika"] = (round(t["mean"] - out["base"]["mean"], 5)
                          if t["mean"] is not None and out["base"]["mean"] is not None else None)
        out["dovoljno"] = bool(t["dovoljno"] and out["base"]["dovoljno"])
    else:
        out["dovoljno"] = bool(out["base"]["dovoljno"] and out["base_train"]["dovoljno"])
    return out


def trade_analysis(sets, days):
    """{set: {"svi": stats, "po_stanju": by_state, "filtri_svi": {name: stats}, "oos": oos}}."""
    out = {}
    for name, rows in sets.items():
        tagged = [{**r, "s": state_at(days, r["ts"])} for r in rows]
        out[name] = {"svi": stats(tagged), "po_stanju": by_state(tagged),
                     "filtri_svi": {f: {**stats([r for r in tagged if keep(r["s"])]),
                                        "maknuto": sum(1 for r in tagged if not keep(r["s"]))}
                                    for f, (_hr, keep) in FILTERS.items()},
                     "oos": oos(tagged)}
    return out


# ---------- lead / lag of the platforms' volume ------------------------------------------------------------------------

def lead_lag(days, events, tokens, now):
    """{"skokovi": {lag: corr}, "povrat": {lag: corr}, "n": days}: the daily change of the meme platforms' volume on day
    d against the number of jumps (t0 day) and the median midcap daily return on day d + lag (lag > 0: the volume moves
    first)."""
    since = int(now) // D * D - EVENT_D * D
    vchg = {}
    for d, r in days.items():
        p = days.get(d - D) or {}
        if d >= since and r.get("vol") and p.get("vol"):
            vchg[d] = r["vol"] / p["vol"] - 1
    jumps = defaultdict(int)
    for e in events:
        if e["kind"] == "skok":
            jumps[e["t0"] // D * D] += 1
    per = defaultdict(list)
    for t in tokens.values():
        for d, r in token_returns(t["closes"]).items():
            per[d].append(r)
    med = {d: statistics.median(v) for d, v in per.items() if len(v) >= 5}
    out = {"skokovi": {}, "povrat": {}, "n": len(vchg)}
    for lag in LAGS:
        xs, ys = [], []
        for d, v in vchg.items():
            xs.append(v)
            ys.append(jumps.get(d + lag * D, 0))
        out["skokovi"][str(lag)] = None if (c := corr(xs, ys)) is None else round(c, 3)
        xs, ys = [], []
        for d, v in vchg.items():
            if d + lag * D in med:
                xs.append(v)
                ys.append(med[d + lag * D])
        out["povrat"][str(lag)] = None if (c := corr(xs, ys)) is None else round(c, 3)
    return out


# ---------- the run --------------------------------------------------------------------------------------------------

def follow_summary(rows):
    ok = [r for r in rows if r.get("corr") is not None]
    if len(ok) < MIN_TOKENS:
        return {"tokena": len(ok), "dovoljno": False}
    c = [r["corr"] for r in ok]
    return {"tokena": len(ok), "dovoljno": True, "corr_med": round(statistics.median(c), 3),
            "prate": sum(1 for x in c if x >= FOLLOW_CORR), "prate_udio": round(sum(1 for x in c if x >= FOLLOW_CORR) / len(c), 3),
            "beta_med": round(_med([r["beta"] for r in ok]) or 0, 3),
            "isti_smjer_med": round(_med([r["isti_smjer"] for r in ok]) or 0, 3),
            "protiv": sum(1 for r in ok if r.get("oznaka")),
            "corr30_med": round(_med([r["corr30"] for r in ok]) or 0, 3)}


def compute(con, p, now, log=print):
    """Everything after the network part, from the stored data (market.db `con` is written). Returns the result dict
    (also kept in trziste_kv "rezultat")."""
    t0 = time.time()
    days = build_days(con, now)
    try:
        build_4h(con, hourly_btc(p), now)
    except Exception as e:  # noqa: BLE001
        log(PREFIX + f"4-satno stanje nije izračunato ({type(e).__name__}: {e})")
    tokens, skip = load_tokens(p, now)
    rows = []
    for mint, t in tokens.items():
        f = follow(token_returns(t["closes"]), days, now)
        if f is None:
            skip.setdefault("malo_dana", 0)
            skip["malo_dana"] += 1
            continue
        rows.append({"token": mint, "symbol": t.get("symbol"), "src": t["src"], "mcap": t.get("mcap"), **f})
    con.execute("DELETE FROM trziste_tok")
    con.executemany("INSERT INTO trziste_tok VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(r["token"], r["symbol"], r["src"], r["mcap"], r["n"], r["corr"], r["beta"], r["n30"], r["corr30"],
                      r["beta30"], r["isti_smjer"], r["obojanih"], r["protiv"], r["uz"], r["protiv_udio"], r["tipicno"],
                      int(r["oznaka"])) for r in rows])
    stored = jumps_stored(p, now)
    jumps = stored if stored else derive(tokens, now, drops=False)
    jsrc = ("zapisani skokovi midcap liste (pumpe do 2-15 M $ i do 15 M $ i više)" if stored else
            "iz dnevnih svijeća (zapisanih skokova još nema)")
    drops = derive(tokens, now, drops=True)
    events = tag(jumps + drops, days)
    con.execute("DELETE FROM trziste_dog")
    con.executemany("INSERT OR REPLACE INTO trziste_dog VALUES (?,?,?,?,?,?,?)",
                    [(e["token"], e["day"], e["kind"], e["size"], e.get("tier"), e["src"], e["t0"]) for e in events])
    td = token_days(tokens, days, now)
    sets = load_sets(p)
    since = int(now) // D * D - HISTORY_D * D
    cnt = defaultdict(int)
    for d, r in days.items():
        if d >= since:
            cnt[r.get("boja") or "nepoznato"] += 1
    per_day = defaultdict(lambda: [0, 0])
    for e in events:
        per_day[e["day"]][0 if e["kind"] == "skok" else 1] += 1
    last = max((d for d, r in days.items() if r.get("btc") is not None), default=None)
    res = {"ts": int(now), "dani": sum(1 for d in days if d >= since), "boje_dana": dict(cnt),
           "danas": days.get(last) if last else None, "sada": state_at(days, now) if days else None,
           "slijede": follow_summary(rows), "preskoceno": skip, "tokena_sa_svijecama": len(tokens),
           "skokova": len(jumps), "padova": len(drops), "skokovi_izvor": jsrc,
           "dogadaji": event_tables(events, td), "pravilo": trade_analysis(sets, days),
           "vodi": lead_lag(days, events, tokens, now), "po_danu": {str(d): v for d, v in sorted(per_day.items())},
           "fng_provjera": fng_check(con)}
    res["secs"] = round(time.time() - t0, 1)
    kv_put(con, "rezultat", res)
    con.commit()
    return res


def fng_check(con):
    """{"n", "razlicito"}: stored F&G rows whose API label disagrees with fng_class (should be 0)."""
    n = bad = 0
    for v, lab in _q(con, "SELECT value, label FROM fng WHERE label IS NOT NULL AND label != ''"):
        if lab in FNG_API:
            n += 1
            bad += FNG_API[lab] != fng_class(v)
    return {"n": n, "razlicito": bad}


def latest(path=None):
    """The stored result, or None (read-only)."""
    con = store.ro(path)
    if con is None:
        return None
    try:
        return kv_get(con, "rezultat")
    finally:
        con.close()


# ---------- words -----------------------------------------------------------------------------------------------------

def _f(x, dec=1, sign=False):
    """A number with a decimal comma."""
    if x is None:
        return "–"
    s = f"{x:+.{dec}f}" if sign else f"{x:.{dec}f}"
    return s.replace(".", ",").replace("-", "−")


def _p(x, dec=1, sign=True):
    return "–" if x is None else _f(100 * x, dec, sign) + " %"


def rate_row(res, dim, tier="svi"):
    """{state: row} of one event table."""
    return {r["stanje"]: r for r in (res.get("dogadaji") or {}).get(dim) or [] if r["tier"] == tier}


def answers(res):
    """The three plain answers of the page (and the log line's core): {"slijede", "kada", "pravilo"}."""
    s = res.get("slijede") or {}
    if s.get("dovoljno"):
        a1 = (f"Većina ne prati: medijan korelacije dnevnih promjena s BTC-om je {_f(s['corr_med'], 2)} "
              if s["corr_med"] < FOLLOW_CORR else
              f"Uglavnom prate: medijan korelacije dnevnih promjena s BTC-om je {_f(s['corr_med'], 2)} ")
        a1 += (f"(n={s['tokena']} tokena; {s['prate']} ih ima korelaciju barem {_f(FOLLOW_CORR, 1)}). "
               f"Često protiv tržišta: {s['protiv']} tokena.")
    else:
        a1 = f"Nedovoljno podataka (tokena s barem {MIN_DAYS_CORR} dana svijeća: {s.get('tokena', 0)})."
    rows = rate_row(res, "boja")
    parts = []
    for b in BOJE:
        r = rows.get(b)
        if r and r["token_dana"] >= 100:
            parts.append(f"kad je BTC {BOJA_ADJ[b]}: {_f(r['skok_na_100'], 2)} skokova i {_f(r['pad_na_100'], 2)} "
                         f"padova na 100 token-dana (n={r['token_dana']})")
    a2 = ("; ".join(parts) + ".") if parts else "Nedovoljno podataka."
    a2 = a2[:1].upper() + a2[1:]
    a3 = []
    for name in ("replay", "sjena", "demo", "novcanici"):
        o = ((res.get("pravilo") or {}).get(name) or {}).get("oos") or {}
        b = o.get("base") or {}
        if not o.get("split") or not b.get("dovoljno"):
            continue
        if o.get("odabran"):
            t = o["odabran_test"]
            a3.append(f"{SET_HR[name]}: odabrani filtar „{FILTERS[o['odabran']][0]}” na kasnijim danima "
                      + (f"{_p(t['mean'])} po ulazu (n={t['n']}, {t['k']} token-dana) prema {_p(b['mean'])} bez filtra"
                         if t.get("dovoljno") else f"ima premalo ulaza ({t['k']} token-dana): nedovoljno podataka")
                      + f"; filtar miče {o['filtri'][o['odabran']]['maknuto']} od {b['n']} ulaza")
        else:
            a3.append(f"{SET_HR[name]}: nijedan filtar nije bio bolji na ranijim danima; bez filtra na kasnijim danima "
                      f"{_p(b['mean'])} po ulazu (n={b['n']})")
    a3 = ("; ".join(a3) + ".") if a3 else "Nedovoljno podataka."
    a3 = a3[:1].upper() + a3[1:]
    return {"slijede": a1, "kada": a2, "pravilo": a3}


def line(res):
    """ONE log line in Croatian with the key numbers."""
    if not res:
        return PREFIX + "nema rezultata"
    c = res.get("boje_dana") or {}
    d = res.get("danas") or {}
    s = res.get("slijede") or {}
    out = (f"{res.get('dani', 0)} dana (BTC zeleno {c.get('zeleno', 0)}, žuto {c.get('zuto', 0)}, crveno "
           f"{c.get('crveno', 0)})")
    if d:
        out += (f"; zadnji dan BTC {BOJA_HR.get(d.get('boja'), '?').split(' ')[0]}, strah i pohlepa {d.get('fng') if d.get('fng') is not None else '?'}"
                f" ({FNG_HR.get(d.get('fng_klasa'), '?')}), meme volumen {d.get('vol_trend') or '?'}")
    sk = res.get("preskoceno") or {}
    out += (f"; {res.get('tokena_sa_svijecama', 0)} tokena sa svijećama, bez svijeća {sk.get('bez_svijeca', 0)}, "
            f"ispod 30k {sk.get('ispod_30k', 0)}")
    if s.get("dovoljno"):
        out += f"; medijan korelacije s BTC-om {_f(s['corr_med'], 2)} (n={s['tokena']}), protiv tržišta {s['protiv']}"
    rows = rate_row(res, "boja")
    out += f"; skokova {res.get('skokova', 0)}, padova {res.get('padova', 0)}"
    rr = [f"{BOJA_HR[b].split(' ')[0]} {_f(rows[b]['skok_na_100'], 2)}" for b in BOJE if rows.get(b) and rows[b]["skok_na_100"] is not None]
    if rr:
        out += " (skokova na 100 token-dana: " + ", ".join(rr) + ")"
    parts = []
    for name, a in (res.get("pravilo") or {}).items():
        o = a.get("oos") or {}
        parts.append(f"{name} n={a['svi']['n']}" + (f" filtar {o['odabran']} {_p((o.get('odabran_test') or {}).get('mean'))}"
                                                    f" prema {_p((o.get('base') or {}).get('mean'))}" if o.get("odabran")
                                                    else ""))
    if parts:
        out += "; ulazi: " + ", ".join(parts)
    return PREFIX + out + f"; {_f(res.get('secs') or 0, 1)} s"


# ---------- the council (once) ----------------------------------------------------------------------------------------

def ready(res):
    """True when the numbers are worth a proposal: some trade set with >= 2 x MIN_TD token-days and an out-of-sample
    split, and event tables with jumps."""
    if not res or not res.get("skokova"):
        return False
    for a in (res.get("pravilo") or {}).values():
        o = a.get("oos") or {}
        if a["svi"]["k"] >= 2 * MIN_TD and o.get("split") and (o.get("base") or {}).get("k", 0) >= MIN_TD:
            return True
    return False


def proposal(res, now):
    """(title, interpretation, improvement, evidence) built from the result at this moment."""
    ans = answers(res)
    ev = {"vijece": "rezim_trzista", "izracunato": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(res["ts"])),
          "dana": res.get("dani"), "pravilo_boje": RULE_HR, "prate_li_trziste": res.get("slijede"),
          "skokovi_padovi_po_boji": {b: {k: r.get(k) for k in ("skokova", "padova", "token_dana", "skok_na_100",
                                                               "pad_na_100")}
                                     for b, r in rate_row(res, "boja").items()},
          "skokovi_padovi_po_fng": {b: {k: r.get(k) for k in ("skokova", "padova", "token_dana", "skok_na_100",
                                                              "pad_na_100")}
                                    for b, r in rate_row(res, "fng_klasa").items()},
          "vodi_volumen": res.get("vodi"), "skupovi": {}}
    supported = []
    for name, a in (res.get("pravilo") or {}).items():
        o = a.get("oos") or {}
        ev["skupovi"][name] = {"svi": a["svi"], "po_boji": a["po_stanju"]["boja"], "po_fng": a["po_stanju"]["fng_klasa"],
                               "oos": {k: o.get(k) for k in ("split", "train_dana", "test_dana", "base", "odabran",
                                                             "odabran_test", "razlika")},
                               "filtri_test": {f: {"mean": v["test"]["mean"], "n": v["test"]["n"], "k": v["test"]["k"],
                                                   "lo": v["test"]["lo"], "hi": v["test"]["hi"],
                                                   "maknuto": v["maknuto"]} for f, v in (o.get("filtri") or {}).items()}}
        t = o.get("odabran_test") or {}
        if o.get("odabran") and t.get("dovoljno") and (o.get("razlika") or 0) > 0 and (t.get("lo") or -1) > (
                (o.get("base") or {}).get("mean") or 0):
            supported.append(name)
    verdict = ("podržano na kasnijim danima u: " + ", ".join(SET_HR[s] for s in supported) if supported else
               "nije podržano: nijedan filtar nije na kasnijim danima jasno (donja granica iznad prosjeka bez filtra) "
               "bolji od ulaženja uvijek")
    title = "Režim tržišta: mirovati u strahu, kupovati kad BTC krene gore"
    interp = (f"Vlasnikova hipoteza provjerena na postojećim ulazima (trošak barem 3 %). Prate li tokeni tržište: "
              f"{ans['slijede']} Kad se događaju skokovi: {ans['kada']} Filtri: {ans['pravilo']} Zaključak: {verdict}. "
              "Ovo je statistika na kratkoj povijesti (jedan tržišni ciklus), ne dokaz.")
    until = time.strftime("%d.%m.%Y.", time.gmtime(now + 21 * D))
    improve = ("Prvo SAMO sjena: svaki novi ulaz (demo, knjiga sjene, mjerenje novčanika) bilježi bi li ga filtar "
               "„mirovati u strahu / kupovati kad BTC krene gore” pustio, bez ikakvog utjecaja na trgovanje. "
               f"Kriterij uspjeha do {until}: filtrirani ulazi na novim danima imaju prosjek po ulazu viši od svih ulaza, "
               f"s donjom granicom 90 % intervala iznad nule, uz barem {2 * MIN_TD} token-dana; tek tada vlasnik "
               "odlučuje o pravim vratima. Ako nije tako, hipoteza se odbacuje i ništa se ne mijenja.")
    ev["predlozena_promjena"] = {"vrsta": "samo_sjena", "filtri": list(FILTERS), "do": until,
                                 "kriterij": "prosjek filtriranih > prosjek svih, donja granica > 0, >= 40 token-dana"}
    ev["zakljucak"] = verdict
    return title, interp, improve, ev


def council_once(res, now, con=None, log=print):
    """Submit ONE proposal by Claude to the council (trade settings ONCE_KEY guards it), built from the result now.
    Nothing while the numbers are too small (retried on later runs). Returns the note id or None."""
    if not ready(res):
        return None
    from trade import settings
    from ui import assistnotes
    from vijece import store as vstore
    own = con is None
    con = con or vstore.connect()
    try:
        if settings.raw(con).get(ONCE_KEY):
            return None
        vstore.ensure(con)
        title, interp, improve, ev = proposal(res, now)
        d = assistnotes.submit_suggestion(con, vstore.CLAUDE_KID, title, interp, improve, ev, None)
        settings.put(con, ONCE_KEY, {"ts": int(now), "id": d["id"]}, "vijeće")
        log(PREFIX + f"prijedlog vijeću zapisan (#{d['id']}); ocjenjuju ga OpenAI i Grok")
        return d["id"]
    finally:
        if own:
            con.close()


# ---------- the run ---------------------------------------------------------------------------------------------------

def run(now=None, p=None, fetch=None, log=print, council=True, network=True):
    """One pass: the network part (backfill once, then one BTC call), the recomputation, one log line, the council
    proposal once when ready. Never raises. Returns the result dict ({} when it could not run)."""
    now = int(now or time.time())
    p = p or paths()
    try:
        con = store.connect(p.get("market"))
        try:
            ensure(con)
            calls = update(con, now, fetch, log) if network else 0
            con.commit()
            res = compute(con, p, now, log)
        finally:
            con.close()
        res["pozivi"] = calls
        log(line(res) + f"; mrežnih poziva {calls}")
        if council:
            try:
                nid = council_once(res, now, log=log)
                if nid is None and not ready(res):
                    log(PREFIX + "vijeće: čekam dovoljno podataka za prijedlog")
            except Exception as e:  # noqa: BLE001
                log(PREFIX + f"vijeće: {type(e).__name__}: {e}")
        return res
    except Exception as e:  # noqa: BLE001 - analysis only: it never takes its caller down
        log(PREFIX + f"nije uspjelo ({type(e).__name__}: {e})")
        return {}


# ---------- readers for the page, the MCP tool and the critic ----------------------------------------------------------

def token_stats(mint, path=None):
    con = store.ro(path)
    if con is None:
        return None
    try:
        r = con.execute("SELECT * FROM trziste_tok WHERE token=?", (mint,)).fetchone()
        if not r:
            return None
        cols = [c[0] for c in con.execute("SELECT * FROM trziste_tok LIMIT 0").description]
        d = dict(zip(cols, r))
        d["oznaka"] = bool(d["oznaka"])
        return d
    except sqlite3.Error:
        return None
    finally:
        con.close()


def mcp(args=None, path=None):
    """get_market_regime: the current state, the per-state tables, a token's stats (read-only)."""
    args = args or {}
    res = latest(path)
    if not res:
        return {"error": "nema izračuna još (run_market.py trziste)", "pravilo_boje": RULE_HR}
    con = store.ro(path)
    h4 = None
    if con is not None:
        try:
            r = con.execute("SELECT ts, btc, boja FROM trziste_4h ORDER BY ts DESC LIMIT 1").fetchone()
            h4 = {"ts": r[0], "btc": r[1], "boja": r[2]} if r else None
        except sqlite3.Error:
            h4 = None
        finally:
            con.close()
    out = {"ts": res["ts"], "pravilo_boje": RULE_HR, "zadnji_dan": res.get("danas"), "stanje_sada": res.get("sada"),
           "zadnja_4h": h4, "odgovori": answers(res), "prate_li_trziste": res.get("slijede"),
           "dogadaji": {k: v for k, v in (res.get("dogadaji") or {}).items() if k in ("boja", "fng_klasa", "vol_trend")},
           "skokovi_izvor": res.get("skokovi_izvor"), "vodi_volumen": res.get("vodi"),
           "ulazi": {k: {"svi": v["svi"], "po_stanju": v["po_stanju"], "oos": {kk: v["oos"].get(kk) for kk in (
               "split", "train_dana", "test_dana", "base", "odabran", "odabran_test", "razlika", "dovoljno")},
               "filtri_test": {f: x["test"] for f, x in v["oos"]["filtri"].items()}}
               for k, v in (res.get("pravilo") or {}).items()},
           "filtri": {k: v[0] for k, v in FILTERS.items()},
           "napomena": ("Samo analiza (sjena): ništa ovdje ne mijenja trgovanje. Token koji često ide protiv tržišta: "
                        + WORDING)}
    tok = args.get("token") or args.get("mint")
    if tok:
        out["token"] = token_stats(str(tok), path) or {"error": "token nema dovoljno dnevnih svijeća ili nije praćen"}
    return out


def critic_summary(path=None):
    """A compact block for the daily critic's data pack (critic/data.py reports())."""
    res = latest(path)
    if not res:
        return None
    return {"ts": res["ts"], "zadnji_dan": res.get("danas"), "stanje_sada": res.get("sada"), "odgovori": answers(res),
            "skokovi_na_100_po_boji": {b: (r.get("skok_na_100"), r.get("pad_na_100"), r.get("token_dana"))
                                       for b, r in rate_row(res, "boja").items()},
            "filtri_oos": {k: {kk: v["oos"].get(kk) for kk in ("odabran", "razlika", "dovoljno")} | {
                "base": {kk: (v["oos"].get("base") or {}).get(kk) for kk in ("n", "k", "mean", "lo", "hi")}}
                for k, v in (res.get("pravilo") or {}).items()},
            "napomena": "samo analiza; ništa ne mijenja trgovanje"}
