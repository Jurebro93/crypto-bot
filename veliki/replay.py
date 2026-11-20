"""The intraday range rule (veliki/intra.py) replayed over EVERY member of the midcap collector (16.11., vlasnik: "želim
više podataka koji će pomoći da postanemo profitabilni"). The rule trades real money without historical evidence;
midcap.db already holds ~31 days of 15m / 1h candles of ~160 tokens, so this costs nothing new: local databases only,
no network call, one pass a night (run_veliki.py replay; start.sh under the heavy lock) and once after a deploy.

Data (midcap.db, read-only): every token with at least MIN_DAYS (5) days of 15m bars (the members and the tokens that
left within the last 30 days: their candles are still kept), its 1h candles (every hour with 15m bars rebuilt from
them: rule.h1_from_15m), BTC hourly (veliki/store.btc_hourly). MC at a time = the supply (the newest snapshot's MC /
price, else the tokens row's MC / the last close) x the price then; liquidity = the day's first snapshot, else the
tokens row. Cost: the round trip veliki/live.enter books at 0.1 SOL (the higher of the cost model and the measured fee a
side), never under RT_FLOOR (3 %, the measured round trip).

The rule replayed = the live rule as it is today (LIVE): the entry of intra.signal on a completed 15m bar's close
(never in a BTC free fall), no entry while the macro regime of the day is risk_off (veliki/makro.daily_regimes, when
market.db exists), only while MC is 2M-200M and liquidity >= the demo's floor; filled at the NEXT bar's open; the
owner's exits (rule.OWNER_EXIT): no time stop, the stop to break-even once +5 % net, the WHOLE position sold at the
target; the reasoned exits the candles can show (BTC free fall, macro risk_off: rule.reasoned_exit); a 15m bar that
touches both the stop and the target is a stop, a stop raised inside a bar fills at its own level (rule.exit_on_bar
same_bar). What the bars cannot show is listed in ASSUMPTIONS.

Every trade of the base rule is tagged (tags_of) with what was known BEFORE its entry: MC bucket, zone width, depth in
the zone, UTC hour block, BTC's state and 24 h change, the day's macro regime, whether "oporavak" held (veliki/makro.
recovery on the makro_h snapshots, only where they exist), the token's answer to BTC's upticks (veliki/odziv.btc_up on
the 7 days of 1h candles completed before the entry), whether the real account could have bought it.

Variants: the pre-declared GRID only (entry depth 15 / 25 / 40 % x target 6 / 10 / 15 % net x stop cap 8 / 12 % = 18).
Walk-forward: the variant with the best EV on the trades CLOSED inside the first TRAIN_FRAC (60 %) of the days is
picked; only its trades entered in the last 40 % (holdout) are reported, next to the base rule's. Interval: the cluster
bootstrap by token-day (walk.boot_ci). Under MIN_N (30) trades a bucket or a variant is "premalo podataka", never a
finding. findings() turns the holdout numbers into plain decisions ("ne ulaziti: ...", "prednost: ...").

Result: midcap.db kv "replay" (JSON; latest()); summary() = the morning report's and /strategije's view of it.
"""
import bisect
import json
import os
import sqlite3
import time

from veliki import intra, rule

PREFIX = "veliki replay: "
D, H = 86400, 3600
KV = "replay"
KV_TRADES = "replay_trades"   # 20.11.: the base rule's trades for market/trziste.py
SIZE_SOL = 0.1
RT_FLOOR = float(os.environ.get("REPLAY_RT_FLOOR", "0.03"))   # the measured round trip at 0.1 SOL (3-3.5 %): never less
MIN_DAYS = 5
MIN_N = 30
TRAIN_FRAC = 0.6
BUDGET_S = int(os.environ.get("REPLAY_BUDGET_S", "300"))
MAX_TOKENS = int(os.environ.get("REPLAY_MAX_TOKENS", "300"))
# the live exits of the intraday rule today (veliki/live.row_cfg + full_tp + manage), as far as 15m bars show them
LIVE = {**rule.OWNER_EXIT, "full_tp": True, "same_bar": "stop", "reasoned": True}
GRID = {"bottom": (0.15, 0.25, 0.40), "tp": (6.0, 10.0, 15.0), "stop_cap": (0.08, 0.12)}
BASE = {k: intra.CFG[k] for k in ("bottom", "tp", "stop_cap")}
# 16.11. popodne (vlasnik: wide stop -20 %, the tight stop only while BTC falls; rule.OWNER_STOP): the rule live trades
# NOW, replayed next to the old stop under the zone, at the base entry and three targets (all three are shown: no
# selection, three looks)
NOVO_TPS = (10.0, 15.0, 25.0)
NOVO = "novo:"
TAGS = ("mc", "sirina", "dubina", "sat", "btc", "btc24", "makro", "oporavak", "odziv", "pravi", "token")
TAG_HR = {"mc": "tržišna vrijednost", "sirina": "širina zone", "dubina": "dubina ulaza u zoni", "sat": "doba dana",
          "btc": "stanje Bitcoina", "btc24": "Bitcoin u 24 h", "makro": "makro režim dana",
          "oporavak": "oporavak tržišta", "odziv": "odziv tokena na rast Bitcoina",
          "pravi": "uvjeti pravog novca (vrijednost, likvidnost, starost)", "token": "token"}
BTC_HR = {"normalno": "normalno", "dno_se_potvrduje": "dno se potvrđuje", "slobodan_pad": "slobodan pad",
          "nepoznato": "nepoznato"}
MAKRO_HR = {"risk_on": "tržište raste", "neutral": "neutralno", "risk_off": "tržište pada", "nepoznato": "nepoznato"}
UNKNOWN = ("nepoznato", "nepoznat")
ODZIV_STRONG = 1.0       # the same split as report/midcap.by_regime ("jak" from 1.0)
TOKEN_ROWS = 20
ASSUMPTIONS = (
    "ulaz na otvaranju sljedeće svijeće od 15 minuta uz 0,2 % proklizavanja (uživo: cijena u trenutku signala)",
    "stop i cilj na svojoj razini uz proklizavanje 0,5 % / 0,2 %; svijeća koja dotakne i stop i cilj računa se kao stop",
    "cijeli profit na cilju uvijek (uživo se pola ostavlja samo kad cijelo tržište snažno raste)",
    "makro režim dana iz dnevnih volumena platformi (uživo se računa svaki sat i gleda još sektor i midcapove)",
    "nije simulirano: stropovi računa (broj otvorenih, kupnji dnevno, dnevni gubitak), DCA, izlazi zbog povlačenja "
    "likvidnosti, prodaje holdera i ruga, prioritet tokena, uvjet 24-satnog volumena",
    "do 3 ulaza po tokenu na UTC dan (uživo: zagrebački dan)",
    "pozicije još otvorene na kraju podataka vrednuju se po zadnjoj cijeni",
    "svijeće su uzete kakve jesu: pojedinačan ispis na krivoj cijeni može lažno pogoditi cilj ili stop",
    "tržišna vrijednost u prošlosti = današnja ponuda tokena x tadašnja cijena; likvidnost prije snimki sakupljača = "
    "današnja",
)


# ---------- the grid -------------------------------------------------------------------------------------------------

def variants(grid=None):
    g = {**GRID, **(grid or {})}
    return [{"bottom": b, "tp": tp, "stop_cap": sc} for b in g["bottom"] for tp in g["tp"] for sc in g["stop_cap"]]


def key_of(v):
    return f"dno{v['bottom'] * 100:g}/cilj{v['tp']:g}/stop{v['stop_cap'] * 100:g}"


def text_of(v):
    return (f"ulaz u donjih {v['bottom'] * 100:g} % zone, cilj +{v['tp']:g} % neto, stop najviše "
            f"−{v['stop_cap'] * 100:g} %")


BASE_KEY = key_of(BASE)


# ---------- data (midcap.db, read-only) ------------------------------------------------------------------------------

def tokens(con, min_days=MIN_DAYS):
    """(rows with at least min_days of 15m bars: the members by 24 h volume, then the tokens that left; how many
    tokens had too little history; how many of the rows are no longer members)."""
    from veliki import universe
    cols = ("mint", "id", "symbol", "dex", "mcap", "liq", "vol24", "created_ts", "member")
    rows = [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM tokens ORDER BY member DESC, vol24 DESC")]
    span = {t: (a, b) for t, a, b in con.execute("SELECT token, MIN(ts), MAX(ts) FROM c15 GROUP BY token")}
    out, short = [], 0
    for r in rows:
        s = span.get(r["mint"])
        if universe.non_meme(r.get("symbol")):
            continue
        if not s or s[1] - s[0] < min_days * D:
            short += 1 if r.get("member") else 0
            continue
        out.append(r)
    return out, short, sum(1 for r in out if not r.get("member"))


def bars(con, table, mint):
    from veliki import store
    return [b for b in store.candles(con, table, mint) if b[1] and b[2] and b[3] and b[4] and min(b[1:5]) > 0]


def facts_of(con, row, b15, now, keep_d=15):
    """{"supply", "liq" (the tokens row's), "liq_day": {UTC day: the day's first snapshot liquidity}, "created_ts"}."""
    supply, liq_day = None, {}
    try:
        r = con.execute("SELECT px, mc FROM snap WHERE id=? AND px>0 AND mc>0 ORDER BY ts DESC LIMIT 1",
                        (row.get("id"),)).fetchone()
        if r:
            supply = r[1] / r[0]
        d1 = int(now) // D
        for d in range(d1 - keep_d, d1 + 1):
            r = con.execute("SELECT liq FROM snap WHERE id=? AND ts>=? AND ts<? AND liq>0 ORDER BY ts LIMIT 1",
                            (row.get("id"), d * D, (d + 1) * D)).fetchone()
            if r:
                liq_day[d] = float(r[0])
    except sqlite3.Error:
        pass
    if supply is None and row.get("mcap") and b15:
        supply = row["mcap"] / b15[-1][4]
    return {"supply": supply, "liq": row.get("liq") or None, "liq_day": liq_day, "created_ts": row.get("created_ts")}


def mc_at(f, px):
    return f["supply"] * px if f.get("supply") and px else None


def liq_at(f, t):
    return f["liq_day"].get(int(t) // D) or f.get("liq")


def round_trip(liq, dex=None, sol=None, tx=None, size=SIZE_SOL, floor=RT_FLOOR):
    """The round trip veliki/live.enter books at `size` SOL (the higher of the cost model and the measured fee a
    side), never under `floor`."""
    c = rule.cost_at(size, liq, sol, rule.fee_side_of(dex), tx)
    return max(c["rt"], rule.demo_rt(c["size_usd"], liq), float(floor or 0.0))


def pit_of(f, macro_days=None, block_macro=True):
    """The point-in-time entry filter of intra.simulate: MC inside the collector's 2M-200M and liquidity at least the
    demo's floor AT that time (unknown: not refused), and no entry on a day the macro regime is risk_off."""
    from veliki import live, universe

    def ok(t, px):
        mc = mc_at(f, px)
        if mc is not None and not (universe.DATA_MIN_MCAP <= mc <= universe.DATA_MAX_MCAP):
            return False
        lq = liq_at(f, t)
        if lq is not None and lq < live.DEMO_MIN_LIQ:
            return False
        return not (block_macro and macro_days and macro_days.get(int(t) // D) == "risk_off")
    return ok


def daily_macro(con, crash, market_path=None):
    """{UTC day: regime} (veliki/makro.daily_regimes: market.db's daily platform volumes + the collector's tokens'
    daily volume, day d from the days before it); {} without market.db."""
    from veliki import makro
    try:
        daily = [(ts, 0.0, 0.0, 0.0, 0.0, v or 0.0) for ts, v in con.execute("SELECT ts, SUM(v) FROM c1d GROUP BY ts")]
    except sqlite3.Error:
        daily = []
    return makro.daily_regimes({"svi": {"daily": daily}} if daily else None, crash, market_path)


class Makro:
    """The hourly macro snapshots (midcap.db makro_h) as veliki/live read them: recovery_at(t)."""

    def __init__(self, rows):
        self.rows = sorted((r for r in rows or () if r.get("ts")), key=lambda r: r["ts"])
        self.ts = [int(r["ts"]) for r in self.rows]
        self._c = {}

    def recovery_at(self, t):
        """True / False: did "oporavak" hold at t (veliki/makro.recovery on the newest snapshot taken at or before t,
        at most 3 h old as veliki/makro.current, and the snapshots before it; never risk_off)? None without one."""
        from veliki import makro
        i = bisect.bisect_right(self.ts, int(t)) - 1
        if i < 0 or t - self.ts[i] > 3 * H:
            return None
        if i not in self._c:
            s = self.rows[i]
            a = bisect.bisect_left(self.ts, self.ts[i] - makro.RECOVERY["bottom_d"] * D)
            self._c[i] = bool(makro.recovery(s, self.rows[a:i], self.ts[i])[0] and s.get("regime") != "risk_off")
        return self._c[i]


def btc_up_before(h1, btc, t, hts=None):
    """veliki/odziv.btc_up at time t from the token's 1h candles COMPLETED by t (a candle that starts at ts closes at
    ts + 1 h) within the look_d days before: nothing at or after t is read. btc: {hour ts: close}."""
    from veliki import odziv
    hts = hts if hts is not None else [c[0] for c in h1]
    a = bisect.bisect_left(hts, int(t) - odziv.CFG["look_d"] * D - H)
    b = bisect.bisect_right(hts, int(t) - H)
    return odziv.btc_up(odziv.closes(h1[a:b]), btc, int(t))


# ---------- the simulation ---------------------------------------------------------------------------------------------

def simulate_token(b15, h1, rt, usd, crash=None, facts=None, macro_days=None, grid=None):
    """{variant key: [trade]} of one token (the live exits LIVE, the variant's entry depth / target / stop cap) and
    "risk_off": the base rule's entries on the days the macro block refuses (a diagnostic of that block)."""
    f = facts or {"supply": None, "liq": None, "liq_day": {}}
    zc = {}
    ctx = {"macro": (lambda t: macro_days.get(int(t) // D)) if macro_days else None}
    pit = pit_of(f, macro_days)
    out = {key_of(v): intra.simulate(b15, h1, rt, usd, {**LIVE, **v}, crash, pit=pit, zcache=zc, ctx=ctx)
           for v in variants(grid)}
    off = []
    d0, d1 = (b15[0][0] // D, b15[-1][0] // D + 1) if b15 else (0, 0)
    if macro_days and any(macro_days.get(d) == "risk_off" for d in range(d0, d1 + 1)):
        off = [x for x in intra.simulate(b15, h1, rt, usd, {**LIVE, **BASE}, crash,
                                         pit=pit_of(f, macro_days, block_macro=False), zcache=zc, ctx=ctx)
               if macro_days.get(x["ts"] // D) == "risk_off"]
    out["risk_off"] = off
    for tp in NOVO_TPS:
        out[f"{NOVO}{tp:g}"] = intra.simulate(b15, h1, rt, usd, {**LIVE, **BASE, "tp": tp, "owner_stop": True}, crash,
                                             pit=pit, zcache=zc, ctx=ctx)
    return out


def _bucket(x, edges):
    for lim, name in edges:
        if x <= lim:
            return name
    return edges[-1][1]


INF = float("inf")
MC_B = ((5e6, "2-5M"), (20e6, "5-20M"), (INF, "20-200M"))
WIDTH_B = ((0.20, "10-20 %"), (0.35, "20-35 %"), (INF, "35-80 %"))
DEPTH_B = ((0.10, "donjih 10 %"), (0.25, "10-25 %"), (INF, "25-40 %"))
BTC24_B = ((-0.02, "pad 2 % ili više"), (0.0, "blagi pad (do 2 %)"), (0.02, "blagi rast (do 2 %)"),
           (INF, "rast više od 2 %"))


def tags_of(x, f=None, crash=None, macro_days=None, makro=None, h1=None, hts=None, btc=None, symbol=None):
    """The labels of one base trade, each from what was known before its entry x["ts"] (the fill bar's open); None =
    untagged (unknown at that time)."""
    from veliki import universe
    t = int(x["ts"])
    f = f or {}
    lo, hi, px = x.get("z_lo"), x.get("z_hi"), x.get("px0")
    mc = mc_at(f, px) if f else None
    lq = liq_at(f, t) if f else None
    out = {"token": symbol, "mc": _bucket(mc, MC_B) if mc is not None else None,
           "sirina": _bucket(hi / lo - 1, WIDTH_B) if lo and hi else None,
           "sat": f"{t % D // (6 * H) * 6:02d}-{t % D // (6 * H) * 6 + 6:02d} UTC"}
    if lo and hi and hi > lo and px:
        dep = (px - lo) / (hi - lo)
        out["dubina"] = "ispod dna zone" if dep < 0 else _bucket(dep, DEPTH_B)
    else:
        out["dubina"] = None
    known = crash is not None and crash.known(t)
    out["btc"] = crash.regime(t)[0] if known else "nepoznato"
    ch = crash.chg(t, 24) if known else None
    out["btc24"] = _bucket(ch, BTC24_B) if ch is not None else "nepoznato"
    out["makro"] = (macro_days or {}).get(t // D) or "nepoznato"
    rec = makro.recovery_at(t) if makro is not None else None
    out["oporavak"] = None if rec is None else ("da" if rec else "ne")
    sc = btc_up_before(h1, btc, t, hts) if h1 and btc else None
    out["odziv"] = "nepoznat" if not sc else ("jak" if sc["score"] >= ODZIV_STRONG else "slab")
    age = (t - f["created_ts"]) / D if f.get("created_ts") else None
    if mc is None or lq is None or age is None:
        out["pravi"] = None
    else:
        out["pravi"] = "ispunjeni" if (universe.MIN_MCAP <= mc <= universe.MAX_MCAP and lq >= universe.REAL_MIN_LIQ
                                       and age > universe.MIN_AGE_D) else "nisu ispunjeni"
    return out


# ---------- the numbers ------------------------------------------------------------------------------------------------

def brief(trs, size=SIZE_SOL):
    n = len(trs)
    if not n:
        return {"n": 0}
    s = sum(x["ret"] for x in trs)
    return {"n": n, "ev_pct": round(s / n * 100, 3), "hit": round(sum(1 for x in trs if x["ret"] > 0) / n, 3),
            "sum_sol": round(s * size, 4)}


def measured(trs, min_n=MIN_N, size=SIZE_SOL):
    """brief() + the 90 % interval of EV by token-day (walk.boot_ci); under min_n trades only {"n", "malo": True}:
    "premalo podataka", never a finding."""
    from veliki import walk
    if len(trs) < min_n:
        return {"n": len(trs), "malo": True}
    s = brief(trs, size)
    s["ci90"] = walk.boot_ci(trs)
    return s


def full(trs, days, usd, sol, size=SIZE_SOL, names=None, min_n=MIN_N):
    """The headline numbers (walk.stats): n, a day, hit, EV, the 90 % interval by token-day and by day, the median
    hold, max drawdown, the sum, the worst trade, the exit reasons; under min_n trades {"n", "malo": True}."""
    from veliki import walk
    if len(trs) < min_n:
        return {"n": len(trs), "malo": True}
    st = walk.stats(trs, days, usd, names)
    out = {k: st.get(k) for k in ("n", "per_day", "hit", "ev_pct", "ci90_day_pct", "hold_med_h", "worst_pct",
                                  "worst5_pct", "profit_factor", "ev_2x_cost_pct", "loto_min_pct", "token_days",
                                  "reasons", "mae_med_pct", "mfe_med_pct")}
    out["ci90"] = st.get("ci90_ev_pct")
    out["sum_sol"] = round(sum(x["ret"] for x in trs) * size, 4)
    out["max_dd_sol"] = round((st.get("max_dd_usd") or 0.0) / sol, 4) if sol else None
    return out


def split_days(days, frac=TRAIN_FRAC):
    """(the first `frac` of the sorted UTC days, the rest = the holdout, the holdout's first second); with fewer than
    two days there is no holdout (split None)."""
    days = sorted(set(days))
    if len(days) < 2:
        return days, [], None
    k = max(1, min(len(days) - 1, int(len(days) * frac)))
    return days[:k], days[k:], days[k] * D


def train_of(trs, split_ts):
    """The trades CLOSED before the holdout starts (no trade that knows a holdout price)."""
    return [x for x in trs if split_ts is None or x["out_ts"] <= split_ts]


def hold_of(trs, split_ts):
    return [x for x in trs if split_ts is not None and x["ts"] >= split_ts]


def walk_forward(per, split_ts, base_key=BASE_KEY, min_n=MIN_N):
    """{"n" (variants tried), "pick" (the key with the best EV on the train trades, at least min_n of them; the base
    rule on a tie; None when no variant has enough), "table": [{key, train_n, train_ev_pct}]}."""
    table, best = [], None
    for key, trs in per.items():
        b = brief(train_of(trs, split_ts))
        table.append({"key": key, "train_n": b["n"], "train_ev_pct": b.get("ev_pct")})
        if split_ts is None or b["n"] < min_n:
            continue
        rank = (b["ev_pct"], key == base_key)
        if best is None or rank > best[0]:
            best = (rank, key)
    return {"n": len(per), "pick": best[1] if best else None, "table": table}


def by_tag(trades, split_ts, min_n=MIN_N, size=SIZE_SOL, token_rows=TOKEN_ROWS):
    """{tag: [{"k", "svi": all days, "rano": the train part (n, EV), "izvan": the holdout with its interval}]} and
    {tag: untagged trades}; buckets by size."""
    from veliki import walk
    out, untagged = {}, {}
    for tag in TAGS:
        have = [x for x in trades if (x.get("tags") or {}).get(tag) is not None]
        if len(have) < len(trades):
            untagged[tag] = len(trades) - len(have)
        key = lambda x: x["tags"][tag]  # noqa: E731
        early = walk.by_key(train_of(have, split_ts) if split_ts is not None else [], key)
        late = {}
        for x in hold_of(have, split_ts):
            late.setdefault(key(x), []).append(x)
        rows = []
        for k, s in walk.by_key(have, key).items():
            e = early.get(k) or {}
            rows.append({"k": k, "svi": ({"n": s["n"], "ev_pct": s["ev_pct"], "hit": s["hit"]} if s["n"] >= min_n
                                         else {"n": s["n"], "malo": True}),
                         "rano": {"n": e.get("n", 0), "ev_pct": e.get("ev_pct")},
                         "izvan": measured(late.get(k) or [], min_n, size)})
        out[tag] = rows[:token_rows] if tag == "token" else rows
    return out, untagged


def _sign(m):
    """-1 the whole 90 % interval under 0, +1 the whole of it above 0, 0 it straddles 0, None not measured."""
    ci = (m or {}).get("ci90")
    if not m or m.get("malo") or not ci:
        return None
    return -1 if ci[1] < 0 else 1 if ci[0] > 0 else 0


def _nums(m):
    ci = m["ci90"]
    return (f"{m['n']} tradeova, prosjek {m['ev_pct']:+.2f} % po tradeu, 90 % interval {ci[0]:+.2f} do "
            f"{ci[1]:+.2f} %")


def _bucket_hr(tag, k):
    k = {"btc": BTC_HR, "makro": MAKRO_HR}.get(tag, {}).get(k, k)
    return f"{TAG_HR.get(tag, tag)}: {k}"


def findings(res):
    """[{"vrsta", "tekst", "n", "ev_pct", "ci90"}]: what the HOLDOUT says is worth changing, by plain rules: a bucket
    (or the days the macro block refuses, or the picked variant) with at least MIN_N holdout trades whose whole 90 %
    interval is under 0 -> "ne ulaziti: ...", above 0 -> "prednost: ...". When the whole rule already loses (wins) on
    the holdout, only the buckets worse (better) than the rule's own average are listed on that side: the rest is the
    verdict said again. Order: the picked variant, the macro block, then the side that goes against the rule's
    verdict (the exceptions), then the other; the strongest first."""
    out = []

    def add(kind, text, m):
        out.append({"vrsta": kind, "tekst": text, "n": m["n"], "ev_pct": m["ev_pct"], "ci90": m["ci90"]})
    var = res.get("variants") or {}
    pick, pm, base = var.get("pick"), var.get("pick_holdout"), res.get("holdout") or {}
    sb, eb = _sign(base), base.get("ev_pct")
    if pick and pick != res.get("base_key") and _sign(pm) == 1 and (eb is None or pm["ev_pct"] > eb):
        add("promjena", f"vrijedilo bi promijeniti pravilo: {var.get('pick_text')} (izvan uzorka {_nums(pm)}; današnje "
                        "pravilo u istim danima: " + (_nums(base) if sb is not None else "premalo podataka") + ")", pm)
    off = (res.get("risk_off") or {}).get("izvan")
    if _sign(off) == -1:
        add("zadrzati", "zabranu ulaza dok tržište pada vrijedi zadržati: ti bi ulazi gubili (izvan uzorka "
                        f"{_nums(off)})", off)
    elif _sign(off) == 1:
        add("promjena", "zabrana ulaza dok tržište pada košta zaradu: ti bi ulazi zarađivali (izvan uzorka "
                        f"{_nums(off)})", off)
    bad, good = [], []
    for tag, rows in (res.get("tags") or {}).items():
        for r in rows:
            m = r.get("izvan")
            s = _sign(m)
            if not s or r["k"] in UNKNOWN or (s == sb and eb is not None and (m["ev_pct"] - eb) * s <= 0):
                continue    # an unknown label is no decision; a bucket no worse (better) than the rule itself neither
            e = r.get("rano") or {}
            tail = (f"; u prvom dijelu {e['ev_pct']:+.2f} % na {e['n']} tradeova" if e.get("n") and
                    e.get("ev_pct") is not None else "")
            text = f"{'ne ulaziti' if s < 0 else 'prednost'}: {_bucket_hr(tag, r['k'])} (izvan uzorka {_nums(m)}{tail})"
            (bad if s < 0 else good).append(("ne_ulaziti" if s < 0 else "prednost", text, m))
    bad.sort(key=lambda x: x[2]["ev_pct"])
    good.sort(key=lambda x: -x[2]["ev_pct"])
    for kind, text, m in (good + bad if (eb or 0) < 0 else bad + good):
        add(kind, text, m)
    return out


def verdict(res):
    """One Croatian sentence: does the rule as it is today make or lose money on the holdout?"""
    ho, al = res.get("holdout") or {}, res.get("all") or {}
    if not al.get("n"):
        return "Povijesni test dnevnog raspona još nema nijedan trade (premalo svijeća u bazi)."
    if ho.get("malo") or not ho.get("ci90"):
        return (f"Premalo podataka za presudu o dnevnom rasponu: izvan uzorka je samo {ho.get('n', 0)} tradeova "
                f"(treba barem {MIN_N}).")
    s = _sign(ho)
    head = f"Dnevni raspon kakav je danas u zadnjih {res.get('hold_days')} dana povijesti (izvan uzorka) "
    nums = _nums(ho).replace(" po tradeu,", " po tradeu nakon troška,")
    if s < 0:
        return head + f"GUBI: {nums}, cijeli interval je ispod nule."
    if s > 0:
        return head + f"ZARAĐUJE: {nums}, cijeli interval je iznad nule."
    return head + f"nije dokazano ni da zarađuje ni da gubi: {nums}, interval prelazi nulu."


def biases(res):
    return [
        "Preživjeli tokeni: test gleda tokene koji su danas na popisu (i one koji su s njega ispali u zadnjih 30 dana); "
        "tokeni koji su ranije propali nedostaju, pa je stvarni rezultat vjerojatno lošiji od ovog.",
        f"Kratko razdoblje: {res.get('days') or 0} dana (najviše oko 31) = jedan tržišni režim; u drugačijem tržištu "
        "rezultat može biti drugačiji.",
        "Izvršenje na svijećama od 15 minuta: ulaz na otvaranju sljedeće svijeće, stop i cilj na svojoj razini; kad "
        "ista svijeća dotakne i stop i cilj, računa se stop. Pravi nalozi mogu proći bolje ili lošije.",
    ]


# ---------- the computation ------------------------------------------------------------------------------------------

def compute(con, now, btc_h, macro_days=None, budget_s=BUDGET_S, max_tokens=MAX_TOKENS, floor=RT_FLOOR, size=SIZE_SOL,
            sol=None, tx=None, grid=None):
    """The whole result dict (see the module text) from midcap.db `con` (read-only use) and BTC hourly closes."""
    from veliki import makro as vmakro, odziv, walk
    t0 = time.time()
    t_end = t0 + 0.8 * float(budget_s)       # the rest of the budget is the statistics' (the bootstraps)
    sol = float(sol or walk.sol_now())
    tx = rule.tx_sol()[0] if tx is None else tx
    usd = size * sol
    crash = rule.crash_of(btc_h)
    btc = odziv.closes(btc_h)
    rows, short, gone = tokens(con)
    if macro_days is None:
        try:
            macro_days = daily_macro(con, crash)
        except Exception:  # noqa: BLE001 - no market.db: no macro block, the tag says "nepoznato"
            macro_days = {}
    try:
        mk = Makro(vmakro.history(con, now, days=60))
    except Exception:  # noqa: BLE001
        mk = Makro([])
    keys = [key_of(v) for v in variants(grid)]
    per = {k: [] for k in keys}
    off, names, days, rts = [], {}, set(), []
    novo = {f"{NOVO}{tp:g}": [] for tp in NOVO_TPS}
    used, partial = 0, False
    for row in rows[:int(max_tokens)]:
        if time.time() > t_end:
            partial = True
            break
        m = row["mint"]
        b15 = bars(con, "c15", m)
        if len(b15) < 2 * intra.MIN_H * 4:
            continue
        h1 = rule.h1_from_15m(b15, bars(con, "c1h", m))
        f = facts_of(con, row, b15, now)
        liqs = [v for v in list(f["liq_day"].values()) + [f.get("liq")] if v]
        rt = round_trip(min(liqs) if liqs else None, row.get("dex"), sol, tx, size, floor)
        sim = simulate_token(b15, h1, rt, usd, crash, f, macro_days, grid)
        hts = [c[0] for c in h1]
        names[m] = row.get("symbol") or m[:6]
        for k, trs in sim.items():
            for x in trs:
                x["token"] = m
            (off if k == "risk_off" else novo[k] if k.startswith(NOVO) else per[k]).extend(trs)
        for x in sim.get(BASE_KEY) or []:
            x["tags"] = tags_of(x, f, crash, macro_days, mk, h1, hts, btc, names[m])
        days |= {b[0] // D for b in b15}
        rts.append(rt)
        used += 1
    tr_days, ho_days, split_ts = split_days(days)
    base = per.get(BASE_KEY) or []
    wf = walk_forward(per, split_ts)
    pick = wf["pick"]
    pv = next((v for v in variants(grid) if key_of(v) == pick), None)
    wf.update(min_train_n=MIN_N, pick_text=text_of(pv) if pv else None,
              pick_train=brief(train_of(per[pick], split_ts), size) if pick else None,
              pick_holdout=(full(hold_of(per[pick], split_ts), len(ho_days), usd, sol, size, names) if pick else None))
    tags, untagged = by_tag(base, split_ts, MIN_N, size)
    res = {"ts": int(now), "day": time.strftime("%Y-%m-%d", time.gmtime(now + 3600)), "size_sol": size,
           "sol_usd": round(sol, 2), "rt_floor": floor,
           "rt_med_pct": round(sorted(rts)[len(rts) // 2] * 100, 2) if rts else None,
           "tokens": used, "tokens_all": len(rows), "tokens_short": short, "tokens_gone": gone, "partial": partial,
           "days": len(days), "from": min(days) * D if days else None, "to": (max(days) + 1) * D if days else None,
           "train_days": len(tr_days), "hold_days": len(ho_days), "split_ts": split_ts,
           "base_key": BASE_KEY, "base_text": text_of(BASE), "macro_known": bool(macro_days),
           "all": full(base, len(days), usd, sol, size, names),
           "train": brief(train_of(base, split_ts), size) if split_ts is not None else {"n": 0},
           "holdout": full(hold_of(base, split_ts), len(ho_days), usd, sol, size, names),
           "tags": tags, "untagged": untagged, "variants": wf,
           "risk_off": {"svi": measured(off, MIN_N, size), "izvan": measured(hold_of(off, split_ts), MIN_N, size)}}
    res["novo"] = {"tekst": (f"široki stop −{rule.OWNER_STOP['wide'] * 100:g} % od ulaza; kad Bitcoin padne "
                             f"{-rule.OWNER_STOP['btc4h'] * 100:g} % u 4 sata, stop {rule.OWNER_STOP['tight'] * 100:g} % "
                             "ispod cijene (ili na ulaz ako je pozicija u plusu)"),
                   "varijante": [{"tp": tp, "svi": full(novo[f"{NOVO}{tp:g}"], len(days), usd, sol, size, names),
                                  "izvan": full(hold_of(novo[f"{NOVO}{tp:g}"], split_ts), len(ho_days), usd, sol, size,
                                                names)} for tp in NOVO_TPS]}
    res["buckets_tested"] = sum(1 for rows_ in tags.values() for r in rows_
                                if _sign(r["izvan"]) is not None and r["k"] not in UNKNOWN)
    res["findings"] = findings(res)
    res["verdict"] = verdict(res)
    res["biases"] = biases(res)
    res["assumptions"] = list(ASSUMPTIONS)
    # 20.11. (market/trziste.py, analysis only): the base rule's closed trades [token, entry ts, net ret], kept apart
    # (kv KV_TRADES) so the market-regime analysis can tag each entry; run() pops it before the summary is stored
    res["_trades"] = [[x["token"], int(x["ts"]), round(float(x["ret"]), 5)] for x in base if x.get("reason") != "kraj"]
    res["secs"] = round(time.time() - t0, 1)
    return res


def line(res):
    """The one log line: n, EV, the interval, the top finding."""
    al, ho = res.get("all") or {}, res.get("holdout") or {}

    def part(m):
        if m.get("malo") or not m.get("n"):
            return f"n={m.get('n', 0)} (premalo podataka)"
        ci = m.get("ci90") or ["—", "—"]
        return f"n={m['n']}, EV {m['ev_pct']:+.2f} %, interval 90 % [{ci[0]}; {ci[1]}], pogodak {m['hit']:.0%}"
    top = (res.get("findings") or [{}])[0].get("tekst") or res.get("verdict") or "bez nalaza"
    nv = "; ".join(f"cilj +{v['tp']:g} %: svi dani {part(v.get('svi') or {})}, izvan uzorka {part(v.get('izvan') or {})}"
                   for v in (res.get("novo") or {}).get("varijante") or [])
    return (PREFIX + f"{res.get('tokens')} tokena, {res.get('days')} dana" + (" (djelomično: vremenski budžet)"
                                                                                if res.get("partial") else "")
            + f"; svi dani {part(al)}; izvan uzorka ({res.get('hold_days')} d) {part(ho)}; varijanti isprobano "
            f"{(res.get('variants') or {}).get('n')}; glavni nalaz: {top}"
            + (f"; NOVO pravilo stopa (široki −20 %, uži samo kad BTC pada): {nv}" if nv else "")
            + f" ({res.get('secs')} s)")


# ---------- the run, the stored result -----------------------------------------------------------------------------------

def latest(path=None):
    """The stored result (midcap.db kv "replay") or None."""
    from veliki import midcap
    con = midcap.ro(path)
    if con is None:
        return None
    try:
        return midcap.kv_get(con, KV)
    except sqlite3.Error:
        return None
    finally:
        con.close()


def run(now=None, log=print, path=None, budget_s=None, max_tokens=None, floor=RT_FLOOR, size=SIZE_SOL, btc=None,
        macro_days=None, sol=None, save=True):
    """One replay pass: compute() over midcap.db, the result into its kv "replay", one log line. Local databases only
    (no network), bounded by budget_s / max_tokens (the largest 24 h volume first; a cut pass says "djelomično").
    Never raises: {} and a log line when it cannot run."""
    from veliki import midcap, store
    now = int(now or time.time())
    try:
        con = midcap.ro(path)
        if con is None:
            log(PREFIX + "nema podataka (midcap.db još ne postoji)")
            return {}
        try:
            btc_h = store.btc_hourly() if btc is None else btc
            res = compute(con, now, btc_h, macro_days, BUDGET_S if budget_s is None else budget_s,
                          MAX_TOKENS if max_tokens is None else max_tokens, floor, size, sol)
        finally:
            con.close()
        trades = res.pop("_trades", None)
        kept = ""
        if save and not res.get("tokens") and (latest(path) or {}).get("tokens"):
            kept = "; nijedan token nije obrađen, zadnji spremljeni rezultat ostaje"   # a cut pass never erases one
        elif save:
            wcon = midcap.connect(path)
            try:
                midcap.kv_put(wcon, KV, res)
                if trades is not None:
                    midcap.kv_put(wcon, KV_TRADES, {"ts": int(now), "trades": trades})
                wcon.commit()
            finally:
                wcon.close()
        log(line(res) + kept)
        return res
    except Exception as e:  # noqa: BLE001 - a measurement: it never takes its caller down
        try:
            log(PREFIX + f"nije uspio ({type(e).__name__}: {e})")
        except Exception:  # noqa: BLE001
            pass
        return {}


# ---------- the report's view ------------------------------------------------------------------------------------------

def _row(name, m):
    if not m or m.get("malo") or not m.get("n"):
        return {"naziv": name, "n": (m or {}).get("n", 0), "malo": True}
    return {"naziv": name, "n": m["n"], "ev_pct": m.get("ev_pct"), "ci": m.get("ci90"), "pogodak": m.get("hit"),
            "zbroj_sol": m.get("sum_sol"), "max_pad_sol": m.get("max_dd_sol"), "drzanje_h": m.get("hold_med_h")}


def summary(res, top=6):
    """What the morning report and /strategije show (plain Croatian, no internal names): the verdict, the rows of the
    small table, the top findings, the known biases; None without a result."""
    if not res or not res.get("ts"):
        return None
    var = res.get("variants") or {}
    rows = [_row("Svi dani", res.get("all")),
            _row(f"Izvan uzorka (zadnjih {res.get('hold_days') or 0} dana)", res.get("holdout"))]
    if var.get("pick") and var["pick"] != res.get("base_key"):
        rows.append(_row("Najbolja od unaprijed zadanih varijanti (izvan uzorka)", var.get("pick_holdout")))
    if var.get("pick") is None:
        vtxt = (f"Isprobano {var.get('n') or 0} unaprijed zadanih varijanti; u prvom dijelu podataka nijedna nema barem "
                f"{MIN_N} tradeova, pa odabira nema.")
    elif var["pick"] == res.get("base_key"):
        vtxt = (f"Isprobano {var.get('n')} unaprijed zadanih varijanti (dubina ulaza, cilj, stop); u prvom dijelu "
                "podataka najbolje je bilo današnje pravilo.")
    else:
        vtxt = (f"Isprobano {var.get('n')} unaprijed zadanih varijanti (dubina ulaza, cilj, stop); odabrana na prvih "
                f"{res.get('train_days')} dana: {var.get('pick_text')}. U tablici je njezin rezultat samo na kasnijim "
                "danima.")
    for v in (res.get("novo") or {}).get("varijante") or []:
        rows.append(_row(f"Novo pravilo stopa, cilj +{v['tp']:g} % (izvan uzorka)", v.get("izvan")))
    fs = res.get("findings") or []
    notes = [vtxt]
    if (res.get("novo") or {}).get("varijante"):
        notes.append("Novo pravilo stopa (od 16.11.): " + res["novo"]["tekst"] + ". Prikazana su sva tri cilja, bez "
                     "odabira; redovi „Svi dani” i „Izvan uzorka” na vrhu mjere stari stop ispod raspona.")
    if res.get("buckets_tested"):
        notes.append(f"Provjereno skupina s dovoljno tradeova: {res['buckets_tested']}; uz interval od 90 % otprilike "
                     f"svaka deseta ({res['buckets_tested'] / 10:.0f}) može ispasti nalaz pukim slučajem.")
    if (res.get("untagged") or {}).get("oporavak"):
        notes.append(f"Oporavak tržišta nije se mogao odrediti za {res['untagged']['oporavak']} tradeova (satne snimke "
                     "makro stanja postoje tek od 15.11.).")
    if res.get("partial"):
        notes.append(f"Djelomičan prolaz: obrađeno {res.get('tokens')} od {res.get('tokens_all')} tokena (vremensko "
                     "ograničenje), najveći volumen prvi.")
    return {"ts": res["ts"], "presuda": res.get("verdict"), "redovi": rows,
            "nalazi": [f["tekst"] for f in fs[:top]], "nalaza": len(fs), "napomene": notes,
            "pristranosti": res.get("biases") or [], "tokena": res.get("tokens"), "dana": res.get("days"),
            "dana_izvan": res.get("hold_days"), "trosak_pct": res.get("rt_med_pct"), "ulog_sol": res.get("size_sol")}


def dumps(d):
    return json.dumps(d, ensure_ascii=False, default=str)
