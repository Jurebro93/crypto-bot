"""What the program has learned from the midcaps: which combination of facts known before an entry, under which
exit, made money on days it had NOT seen (18.11., owner: "radi ih onoliko koliko je potrebno da program što više
nauči iz tih mid-capova, njihove kretnje, da nauči pogađati range i uz kritičara i grok analitičara i makrotržište,
da nauči kombinirati te faktore ... i raditi profitabilne tradeove. Želim da demo što prije bude profitabilan").

Two sources of the same kind of row (veliki/sjena: an imagined entry under one of five exits, with what was known
before it and its net result):
  history   backfill(): the shadow book replayed over the 15m candles of every midcap collector member (midcap.db,
            ~45 days), so the learning does not wait for days of live rows. On candles a stop fills at its level less
            0.5 %, a target at the level or the bar's close when that is lower (a wick is not a sale), both in one bar
            = the stop. Stored in its OWN file nauceno.db (veliki_sjena_h), rebuilt at every run: midcap.db is only
            read, in short reads, so the collector that writes it all day never waits for this job. Known before the entry there: place
            in the zone, calm bars, zone validity and width, BTC's regime, the day's macro regime, the hour.
  live      league.db veliki_sjena (closed rows): the same plus the dip reason, holder caution and Grok's verdict.

The model is deliberately simple and readable: per exit profile, the mean net return of all its rows plus one
adjustment per fact (how much rows with that fact did better or worse than the profile's mean, shrunk towards zero
while the fact has few rows: n / (n + SHRINK)). A candidate's prediction under a profile is that sum; the choice is
the profile with the highest prediction, taken only when it is above THR.

The proof is walk-forward, day by day: a day's candidates are predicted from the days BEFORE it only, then the day
is added to what is known. The first MIN_TRAIN_DAYS are learning only. What counts is the result of the chosen
trades on those unseen days (mean net return, hit, 90 % interval over token-days) next to all trades of the same
days. "kandidat" needs at least MIN_CLUSTERS token-days and the interval's low above zero. Anything less is said as
it is: no proven plus yet.

Costs are the real account's: the round trip is never under replay.RT_FLOOR (3 %), as measured on real swaps at
0.1 SOL. A demo that is profitable at an imagined cost would teach the wrong thing.

Nothing here trades or changes a rule. The result is nauceno.db kv "nauceno", the line "veliki naučeno: ..." and the
`learned` block of the MCP tool get_shadow_book, so the critic and Grok can argue with it.
"""
import bisect
import json
import os
import sqlite3
import time

H, D, M15 = 3600, 86400, 900
PREFIX = "veliki naučeno: "
KV = "nauceno"
TABLE_H = "veliki_sjena_h"
SHRINK = 150
THR = 0.0
MIN_TRAIN_DAYS = 7
MIN_CLUSTERS = 30
STOP_SLIP = 0.005
BUDGET_S = 150
FEATS = ("band", "calm", "zone_ok", "btc", "makro", "hour6", "sirina", "dip", "oprez", "grok")
FEAT_HR = {"band": "mjesto u zoni", "calm": "svijeće", "zone_ok": "zona", "btc": "BTC", "makro": "makro",
           "hour6": "doba dana", "sirina": "širina zone", "dip": "razlog pada", "oprez": "holderi", "grok": "Grok"}
COLS = ("token", "symbol", "opened_ts", "entry_px", "profil", "tp_px", "stop_px", "rt", "pos", "band", "calm", "zone_ok",
        "zone_why", "width", "btc", "makro", "dip", "oprez", "grok", "mcap", "liq", "status", "closed_ts", "exit_px",
        "reason", "ret")
SCHEMA_H = (f"CREATE TABLE IF NOT EXISTS {TABLE_H} (" + ", ".join(
    f"{c} {'TEXT' if c in ('token', 'symbol', 'profil', 'band', 'zone_why', 'btc', 'makro', 'dip', 'grok', 'status', 'reason') else 'INTEGER' if c in ('opened_ts', 'calm', 'zone_ok', 'oprez', 'closed_ts') else 'REAL'}"
    for c in COLS) + ")")


def db_path(path=None):
    """nauceno.db: NAUCENO_DB, else next to midcap.db (the persistent disk). Derived data only: safe to delete."""
    if path:
        return path
    if os.environ.get("NAUCENO_DB"):
        return os.environ["NAUCENO_DB"]
    from veliki import midcap
    return os.path.join(os.path.dirname(os.path.abspath(midcap.db_path())), "nauceno.db")


def connect(path=None):
    con = sqlite3.connect(db_path(path), timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return con


# ---------- the facts of a row --------------------------------------------------------------------------------------

def facts(r):
    """{fact: value} of one book row, the same words for history and live rows; an unknown fact is "?"."""
    w = r.get("width")
    h = time.gmtime(int(r.get("opened_ts") or 0)).tm_hour // 6 * 6
    return {"band": r.get("band") or "?",
            "calm": "smirilo se" if r.get("calm") else "još pada",
            "zone_ok": "valjana" if r.get("zone_ok") else (r.get("zone_why") or "nevaljana"),
            "btc": r.get("btc") or "?",
            "makro": (str(r.get("makro") or "?").split("/")[0]) or "?",
            "hour6": f"{h:02d}-{h + 6:02d} UTC",
            "sirina": "?" if not w else "do 20 %" if w < 0.20 else "20-35 %" if w < 0.35 else "preko 35 %",
            "dip": r.get("dip") or "?", "oprez": "oprez" if r.get("oprez") else "bez", "grok": r.get("grok") or "?"}


# ---------- history: the shadow book over candles ---------------------------------------------------------------------

def simulate(b15, h1, rt, token, symbol, liq, crash=None, macro_days=None, cfg=None, max_h=None, rounds=None):
    """The closed shadow rows of one token from its 15m bars (start ts, o, h, l, c, ...) and 1h candles."""
    from veliki import intra, rule, sjena
    c = intra.cfg_of(cfg)
    max_s = (max_h or sjena.MAX_H) * H
    rounds = rounds or sjena.ROUNDS
    hts = [x[0] for x in h1]
    zc, open_, out, per_day = {}, {}, [], {}
    for i, b in enumerate(b15):
        t = int(b[0]) + M15                                   # the bar is complete: what a live pass would see
        lo_, hi_, cl = b[3], b[2], b[4]
        for prof, p in list(open_.items()):                  # exits on this bar (it started after the entry)
            px = reason = None
            if lo_ <= p["stop_px"]:
                px, reason = p["stop_px"] * (1 - STOP_SLIP), "stop"
            elif hi_ >= p["tp_px"]:
                px, reason = min(p["tp_px"], cl), "tp"
            elif t - p["opened_ts"] >= max_s:
                px, reason = cl, "vrijeme"
            if reason:
                p.update(status="closed", closed_ts=t, exit_px=px, reason=reason, ret=rule.net_ret(p["entry_px"], px, rt))
                out.append(p)
                del open_[prof]
        hk = t // H
        if hk not in zc:
            a, e = bisect.bisect_left(hts, t - c["look_h"] * H), bisect.bisect_right(hts, t - H)
            zc[hk] = intra.zone(h1[a:e], t, c)
        z = zc[hk]
        band, pos = sjena.band_of(cl, z)
        if band is None or i < 2:
            continue
        free = [p for p in sjena.PROFILES if p not in open_]
        if not free:
            continue
        day = t // D
        calm = 1 if intra.calm(b15[max(0, i - int(c["calm"])):i + 1], c)[0] else 0
        btc = crash.regime(t)[0] if crash is not None else None
        for prof in free:
            if per_day.get((day, prof), 0) >= rounds:
                continue
            per_day[(day, prof)] = per_day.get((day, prof), 0) + 1
            tp, stop = sjena.PROFILES[prof]
            open_[prof] = {"token": token, "symbol": symbol, "opened_ts": t, "entry_px": cl, "profil": prof,
                           "tp_px": rule.tp_price(cl, tp, rt, None, {"exit_slip": 0.0}), "stop_px": cl * (1 - stop),
                           "rt": rt, "pos": round(pos, 4), "band": band, "calm": calm, "zone_ok": 1 if z.get("ok") else 0,
                           "zone_why": sjena.why_class(z.get("why")), "width": z.get("width"), "btc": btc,
                           "makro": (macro_days or {}).get(day), "dip": None, "oprez": 0, "grok": None, "mcap": None,
                           "liq": liq}
    return out


def backfill(mcon, wcon, now, btc_h, budget_s=BUDGET_S, max_tokens=300, sol=None):
    """Rebuild veliki_sjena_h (wcon: nauceno.db) from midcap.db's candles (mcon, read-only). {"rows", "tokens",
    "days", "partial"}."""
    from veliki import intra, replay, rule, walk
    t_end = time.time() + budget_s
    sol = float(sol or walk.sol_now())
    tx = rule.tx_sol()[0]
    crash = rule.crash_of(btc_h)
    try:
        macro_days = replay.daily_macro(mcon, crash)
    except Exception:  # noqa: BLE001 - no market.db: the macro fact is "?"
        macro_days = {}
    toks, _short, _gone = replay.tokens(mcon)
    wcon.execute(f"DROP TABLE IF EXISTS {TABLE_H}")
    wcon.execute(SCHEMA_H)
    n = used = 0
    days, partial = set(), False
    q = f"INSERT INTO {TABLE_H} ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})"
    for row in toks[:int(max_tokens)]:
        if time.time() > t_end:
            partial = True
            break
        b15 = replay.bars(mcon, "c15", row["mint"])
        if len(b15) < 2 * intra.MIN_H * 4:
            continue
        h1 = rule.h1_from_15m(b15, replay.bars(mcon, "c1h", row["mint"]))
        f = replay.facts_of(mcon, row, b15, now)
        liqs = [v for v in list(f["liq_day"].values()) + [f.get("liq")] if v]
        liq = min(liqs) if liqs else None
        rt = replay.round_trip(liq, row.get("dex"), sol, tx)
        rows = simulate(b15, h1, rt, row["mint"], row.get("symbol") or row["mint"][:6], liq, crash, macro_days)
        wcon.executemany(q, [tuple(r.get(k) for k in COLS) for r in rows])
        n += len(rows)
        used += 1
        days |= {r["opened_ts"] // D for r in rows}
    wcon.execute(f"CREATE INDEX IF NOT EXISTS {TABLE_H}_t ON {TABLE_H} (opened_ts)")
    wcon.commit()
    return {"rows": n, "tokens": used, "tokens_all": len(toks), "days": len(days), "partial": partial}


# ---------- the learner -----------------------------------------------------------------------------------------------

def load(mcon, lcon, now, days=60):
    """The closed rows with a result: history (nauceno.db) + live (league.db), oldest first, each marked with its src."""
    out = []
    for con, table, src in ((mcon, TABLE_H, "povijest"), (lcon, "veliki_sjena", "uzivo")):
        if con is None:
            continue
        try:
            cur = con.execute(f"SELECT {', '.join(COLS)} FROM {table} WHERE status='closed' AND ret IS NOT NULL AND "
                              "opened_ts>=?", (int(now) - days * D,))
        except sqlite3.Error:   # the table does not exist yet
            continue
        for r in cur:
            d = dict(zip(COLS, r))
            d["src"] = src
            out.append(d)
    out.sort(key=lambda r: r["opened_ts"])
    return out


def _stat(pairs):
    """n, token-days, mean, hit and the 90 % interval of [(cluster key, ret)]. ev is the mean over TOKEN-DAYS (each
    token-day counts once, however many shadows it had), the same thing the interval is about; ev_trade is the plain
    mean of the trades."""
    n = len(pairs)
    if not n:
        return {"n": 0, "clusters": 0, "ev": None, "ev_trade": None, "hit": None, "lo": None, "hi": None}
    cl = {}
    for k, x in pairs:
        cl.setdefault(k, []).append(x)
    means = [sum(v) / len(v) for v in cl.values()]
    k = len(means)
    lo = hi = None
    if k >= 2:
        m = sum(means) / k
        sd = (sum((x - m) ** 2 for x in means) / (k - 1)) ** 0.5
        lo, hi = m - 1.645 * sd / k ** 0.5, m + 1.645 * sd / k ** 0.5
    return {"n": n, "clusters": k, "ev": sum(means) / k, "ev_trade": sum(x for _k, x in pairs) / n,
            "hit": sum(1 for _k, x in pairs if x > 0) / n, "lo": lo, "hi": hi}


class Model:
    """Running sums: per profile, and per (profile, fact, value)."""

    def __init__(self, shrink=SHRINK):
        self.tot, self.cell, self.shrink = {}, {}, shrink

    def add(self, r, f=None):
        p, x = r["profil"], r["ret"]
        t = self.tot.setdefault(p, [0, 0.0])
        t[0] += 1
        t[1] += x
        for k, v in (f or facts(r)).items():
            c = self.cell.setdefault((p, k, v), [0, 0.0])
            c[0] += 1
            c[1] += x

    def base(self, p):
        t = self.tot.get(p)
        return t[1] / t[0] if t and t[0] else None

    def effect(self, p, k, v):
        c, b = self.cell.get((p, k, v)), self.base(p)
        if not c or not c[0] or b is None:
            return 0.0
        return (c[1] / c[0] - b) * c[0] / (c[0] + self.shrink)

    def predict(self, p, f):
        b = self.base(p)
        return None if b is None else b + sum(self.effect(p, k, v) for k, v in f.items() if v != "?")


def learn(rows, min_train_days=MIN_TRAIN_DAYS, thr=THR, shrink=SHRINK):
    """The walk-forward result (see the module text) of book rows sorted by opened_ts."""
    from veliki import sjena
    m = Model(shrink)
    by_day = {}
    for r in rows:
        by_day.setdefault(r["opened_ts"] // D, []).append(r)
    days = sorted(by_day)
    picks, every, prof_all, prof_pick = [], [], {}, {}
    seen = 0
    for d in days:
        batch = [(r, facts(r)) for r in by_day[d]]
        if seen >= min_train_days:
            cand = {}
            for r, f in batch:
                key = (r["token"], d)
                every.append((key, r["ret"]))
                prof_all.setdefault(r["profil"], []).append((key, r["ret"]))
                pr = m.predict(r["profil"], f)
                if pr is None:
                    continue
                c = cand.get((r["token"], r["opened_ts"]))
                if c is None or pr > c[0]:
                    cand[(r["token"], r["opened_ts"])] = (pr, r, key)
            for pr, r, key in cand.values():
                if pr > thr:
                    picks.append((key, r["ret"]))
                    prof_pick.setdefault(r["profil"], []).append((key, r["ret"]))
        for r, f in batch:
            m.add(r, f)
        seen += 1
    eff = []
    for (p, k, v), c in m.cell.items():
        if v != "?" and c[0] >= 100:
            eff.append({"profil": p, "fact": k, "value": v, "n": c[0], "effect": m.effect(p, k, v),
                        "mean": c[1] / c[0]})
    eff.sort(key=lambda e: e["effect"])
    res = {"rows": len(rows), "live_rows": sum(1 for r in rows if r.get("src") == "uzivo"), "days": len(days),
           "test_days": max(0, len(days) - min_train_days), "thr": thr,
           "picked": _stat(picks), "all": _stat(every),
           "by_profile": {p: {"all": _stat(prof_all.get(p, [])), "picked": _stat(prof_pick.get(p, [])),
                              "base": m.base(p)} for p in sjena.PROFILES},
           "worst": eff[:6], "best": eff[-6:][::-1]}
    pk = res["picked"]
    if pk["clusters"] >= MIN_CLUSTERS and pk["lo"] is not None and pk["lo"] > 0:
        res["verdict"] = "kandidat"
    elif pk["clusters"] < MIN_CLUSTERS:
        res["verdict"] = "premalo"
    else:
        res["verdict"] = "nema_plusa"
    return res


# ---------- running it and saying it ----------------------------------------------------------------------------------

def _s(st):
    if not st or not st.get("n"):
        return "nema tradeova"
    ci = f", raspon 90 % [{st['lo']:+.1%}; {st['hi']:+.1%}]" if st.get("lo") is not None else ""
    return f"n={st['n']} ({st['clusters']} token-dana), prosjek po token-danu {st['ev']:+.1%}, pogodak {st['hit']:.0%}{ci}"


def _e(e):
    return (f"{FEAT_HR.get(e['fact'], e['fact'])} {e['value']} × {e['profil']} {e['effect']:+.1%} "
            f"(prosjek {e['mean']:+.1%}, n={e['n']})")


VERDICT_HR = {"kandidat": "KANDIDAT: odabrani tradeovi su na neviđenim danima u plusu i donja granica raspona je iznad nule",
              "premalo": f"premalo podataka za presudu (treba {MIN_CLUSTERS} token-dana odabranih tradeova)",
              "nema_plusa": "nema dokazanog plusa: odabir na neviđenim danima ne prelazi nulu"}


def line(res):
    if not res or not res.get("ts"):
        return PREFIX + "još nema rezultata"
    bf = res.get("backfill") or {}
    best = "; ".join(_e(e) for e in (res.get("best") or [])[:3]) or "—"
    worst = "; ".join(_e(e) for e in (res.get("worst") or [])[:3]) or "—"
    return (f"{PREFIX}{res['rows']} zamišljenih tradeova ({bf.get('rows', 0)} iz povijesti {bf.get('tokens', 0)} tokena"
            f"{' (djelomično)' if bf.get('partial') else ''}, {res.get('live_rows', 0)} uživo), {res['days']} dana, "
            f"provjera na zadnjih {res['test_days']} neviđenih; presuda: {VERDICT_HR.get(res.get('verdict'), '?')}; "
            f"odabrani: {_s(res.get('picked'))}; svi tih dana: {_s(res.get('all'))}; najviše pomaže: {best}; "
            f"najviše šteti: {worst} ({res.get('secs', 0)} s)")


def latest(path=None):
    p = db_path(path)
    if not os.path.exists(p):
        return {}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        r = con.execute("SELECT v FROM kv WHERE k=?", (KV,)).fetchone()
        return json.loads(r[0]) if r else {}
    except (sqlite3.Error, ValueError, TypeError):
        return {}
    finally:
        con.close()


def summary(res=None):
    """The compact block for the MCP tool and the report: the verdict, the numbers, what helps and what hurts."""
    res = res if res is not None else latest()
    if not res or not res.get("ts"):
        return None

    def rnd(st):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in (st or {}).items()}
    return {"ts": res["ts"], "verdict": res.get("verdict"), "verdict_text": VERDICT_HR.get(res.get("verdict")),
            "rows": res.get("rows"), "live_rows": res.get("live_rows"), "days": res.get("days"),
            "test_days": res.get("test_days"), "picked": rnd(res.get("picked")), "all": rnd(res.get("all")),
            "by_profile": {p: {"all": rnd(v.get("all")), "picked": rnd(v.get("picked"))}
                           for p, v in (res.get("by_profile") or {}).items()},
            "helps": [_e(e) for e in res.get("best") or []], "hurts": [_e(e) for e in res.get("worst") or []],
            "how": ("Per exit profile: the profile's mean net return plus one shrunken adjustment per fact known before "
                    "the entry; a candidate takes its best-predicted profile when the prediction is above zero. Tested "
                    "day by day on days the model had not seen. Costs: the real round trip, never under 3 %.")}


def run(now=None, log=print, path=None, lpath=None, budget_s=BUDGET_S, btc=None, save=True, hpath=None):
    """Backfill the history, learn from history + live, store and say the result. path: midcap.db (read), hpath:
    nauceno.db (written), lpath: league.db (read). Never raises: {} and a line."""
    from league import store as lstore
    from veliki import midcap, store
    now = int(now or time.time())
    t0 = time.time()
    try:
        mcon = midcap.ro(path)
        if mcon is None:
            log(PREFIX + "nema podataka (midcap.db još ne postoji)")
            return {}
        wcon = lcon = None
        try:
            wcon = connect(hpath or (os.path.join(os.path.dirname(os.path.abspath(path)), "nauceno.db") if path else None))
            bf = backfill(mcon, wcon, now, store.btc_hourly() if btc is None else btc, budget_s)
            try:
                lp = lpath or lstore.DB
                lcon = sqlite3.connect(f"file:{lp}?mode=ro", uri=True, timeout=10) if os.path.exists(lp) else None
            except sqlite3.Error:
                lcon = None
            res = learn(load(wcon, lcon, now))
            res.update(ts=now, backfill=bf, secs=round(time.time() - t0, 1))
            if save:
                wcon.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (KV, json.dumps(res, ensure_ascii=False, default=str)))
                wcon.commit()
        finally:
            for c in (mcon, wcon, lcon):
                if c is not None:
                    c.close()
        log(line(res))
        return res
    except Exception as e:  # noqa: BLE001 - a measurement: it never takes its caller down
        try:
            log(PREFIX + f"nije uspio ({type(e).__name__}: {str(e)[:160]})")
        except Exception:  # noqa: BLE001
            pass
        return {}
