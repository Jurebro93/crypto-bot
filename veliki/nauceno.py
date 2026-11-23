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

The proof is walk-forward, day by day: a day's candidates are predicted from what was KNOWN before that day began.
The first MIN_TRAIN_DAYS are learning only. What counts is the result of the chosen trades on those unseen days (mean
net return, hit, 90 % interval over token-days) next to all trades of the same days. "kandidat" needs at least
MIN_CLUSTERS token-days and the interval's low above zero. Anything less is said as it is: no proven plus yet.

The purge (18.11., found by the audit): a row's result is fixed only at its closed_ts, up to sjena.MAX_H (72 h) after
it opened. The first version added a day's rows to the model right after scoring that day, with their FINAL result, so
the model that predicted day d+1 already held outcomes decided by the prices of days d+1..d+3: a look-ahead leak that
flatters every number. Now a row enters the model only once it is CLOSED before the START of the day being scored
(closed_ts < d * 86400); a row without closed_ts never enters it. The result carries "purge": true, so nothing can
mistake a number of the leaky version for this one. The stored live model (below) holds only rows closed by the time
it is stored.

Survivorship (18.11.): the history is replayed over TODAY's token list with candles ~45 days back, so a token that was
outside the collector's 2M-200M range then (or has left it since for the better) would be counted as if it had been a
candidate. backfill() applies replay.pit_of (the point-in-time filter of the historical replay: market cap from the
price and today's supply inside 2M-200M, liquidity at least the demo's floor, at the row's open; the macro block of
that filter is NOT applied, the macro regime stays a fact). Tokens that left the list and were dropped by the
collector are still missing: that part of the bias cannot be measured from midcap.db.

Costs are the real account's: the round trip is never under replay.RT_FLOOR (3 %), as measured on real swaps at
0.1 SOL. A demo that is profitable at an imagined cost would teach the wrong thing.

Nothing here trades or changes a rule. The result is nauceno.db kv "nauceno", the line "veliki naučeno: ..." and the
`learned` block of the MCP tool get_shadow_book, so the critic and Grok can argue with it.

The model itself (18.11.): after the walk-forward, the same sums over ALL rows (history + live) are stored as
nauceno.db kv "model", so a live candidate can be predicted with what the test measured: load_model() (read-only,
None when missing or older than MODEL_MAX_AGE_S) and predict_best(model, facts(row)). The only reader that acts on it
is the demo account veliki/ucenik (never the rule's account, never real money).
"""
import bisect
import json
import os
import sqlite3
import time

H, D, M15 = 3600, 86400, 900
PREFIX = "veliki naučeno: "
KV = "nauceno"
KV_MODEL = "model"
MODEL_MAX_AGE_S = 24 * H    # the learner runs every 6 h: a model older than a day means it stopped, and nobody trades on it
MODEL_RELOAD_S = 60         # the stored model is looked at again at most this often (a process keeps it by its ts)
TABLE_H = "veliki_sjena_h"
SHRINK = 150
THR = 0.0
MIN_TRAIN_DAYS = 7
MIN_CLUSTERS = 30
STOP_SLIP = 0.005
BUDGET_S = 150
VAR_THR = (0.01, 0.02, 0.03)     # stricter choices: a prediction above +1 / +2 / +3 %
VAR_RT = (0.02, 0.015)           # what the same choices would have made at a cheaper round trip (a bigger stake)
VAR_FIXED = (("ispod", "siroko"), ("ispod", "pravilo"))   # the plain rules the first result (18.11.) pointed at
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


def gated(f):
    """23.11. (vlasnik: "Dokaz za pravi novac broji samo ulaze koje bi i pravi novac uzeo"): True when a market gate
    held REAL money at this row's entry (the macro regime risk_off or BTC's free fall: veliki/live.market_gates). The
    model still learns from such rows (makro and BTC are facts); the walk-forward's proof leaves them out and reports
    them apart (res["u_filtru"])."""
    return (f or {}).get("makro") == "risk_off" or (f or {}).get("btc") == "slobodan_pad"


# ---------- history: the shadow book over candles ---------------------------------------------------------------------

def simulate(b15, h1, rt, token, symbol, liq, crash=None, macro_days=None, cfg=None, max_h=None, rounds=None, pit=None):
    """The closed shadow rows of one token from its 15m bars (start ts, o, h, l, c, ...) and 1h candles.
    pit(t, px) False = no shadow opens at that close (replay.pit_of: the token was outside the universe then)."""
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
        if pit is not None and not pit(t, cl):               # 18.11.: outside the 2M-200M universe at that time
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
        rows = simulate(b15, h1, rt, row["mint"], row.get("symbol") or row["mint"][:6], liq, crash, macro_days,
                        pit=replay.pit_of(f, macro_days, block_macro=False))
        wcon.executemany(q, [tuple(r.get(k) for k in COLS) for r in rows])
        n += len(rows)
        used += 1
        days |= {r["opened_ts"] // D for r in rows}
    wcon.execute(f"CREATE INDEX IF NOT EXISTS {TABLE_H}_t ON {TABLE_H} (opened_ts)")
    wcon.commit()
    return {"rows": n, "tokens": used, "tokens_all": len(toks), "days": len(days), "partial": partial, "pit": True}


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
        self.ts = self.rows = self.days = None    # set on a stored model (dump / from_dict)

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

    def dump(self, ts, rows=None, days=None):
        """The stored form (kv "model"): the sums, not the predictions, so a reader computes exactly what this does."""
        return {"ts": int(ts), "shrink": self.shrink, "tot": {p: [t[0], t[1]] for p, t in self.tot.items()},
                "cell": [[p, k, v, c[0], c[1]] for (p, k, v), c in self.cell.items()], "rows": rows, "days": days}

    @classmethod
    def from_dict(cls, d):
        m = cls(d.get("shrink", SHRINK))
        m.tot = {p: [int(t[0]), float(t[1])] for p, t in (d.get("tot") or {}).items()}
        m.cell = {(p, k, v): [int(n), float(x)] for p, k, v, n, x in d.get("cell") or []}
        m.ts, m.rows, m.days = int(d["ts"]), d.get("rows"), d.get("days")
        return m


def predict_best(model, f):
    """(profile, prediction) of the exit profile the model predicts best for a candidate's facts (facts() of the row
    veliki/sjena.known builds), over sjena.PROFILES; (None, None) when no profile has a base yet."""
    from veliki import sjena
    best = (None, None)
    for p in sjena.PROFILES:
        pr = model.predict(p, f)
        if pr is not None and (best[1] is None or pr > best[1]):
            best = (p, pr)
    return best


def learn(rows, min_train_days=MIN_TRAIN_DAYS, thr=THR, shrink=SHRINK, model=None, now=None):
    """The walk-forward result (see the module text) of book rows sorted by opened_ts, with the purge of 18.11.: a row
    enters the model only when its closed_ts is before the start of the day being scored. model: an empty Model to
    fill; after the last day it also takes every row that is closed by `now` (default: every closed row), which is the
    model run() stores for live predictions; a row without closed_ts is in neither."""
    import heapq
    from veliki import sjena
    m = model if model is not None else Model(shrink)
    by_day = {}
    for r in rows:
        by_day.setdefault(r["opened_ts"] // D, []).append(r)
    days = sorted(by_day)
    picks, every, prof_all, prof_pick = [], [], {}, {}
    g_picks, g_every = [], []   # 23.11.: candidates real money would not have taken (gated()): apart from the proof
    detail, fixed = [], {k: [] for k in VAR_FIXED}   # detail: (token-day, ret, prediction, rt) of every choice above thr
    seen = 0
    pending, seq = [], 0      # (closed_ts, seq, row, facts): scored already, their result not yet known to the model
    for d in days:
        while pending and pending[0][0] < d * D:      # the purge: only what was closed before this day began
            _c, _s, r0, f0 = heapq.heappop(pending)
            m.add(r0, f0)
        batch = [(r, facts(r)) for r in by_day[d]]
        if seen >= min_train_days:
            cand = {}
            for r, f in batch:
                key = (r["token"], d)
                if gated(f):   # still learned from (the model takes every closed row), never scored as proof
                    g_every.append((key, r["ret"]))
                    pr = m.predict(r["profil"], f)
                    if pr is not None:
                        c = cand.get((r["token"], r["opened_ts"]))
                        if c is None or pr > c[0]:
                            cand[(r["token"], r["opened_ts"])] = (pr, r, key)
                    continue
                every.append((key, r["ret"]))
                prof_all.setdefault(r["profil"], []).append((key, r["ret"]))
                if (f["band"], r["profil"]) in fixed:
                    fixed[(f["band"], r["profil"])].append((key, r["ret"]))
                pr = m.predict(r["profil"], f)
                if pr is None:
                    continue
                c = cand.get((r["token"], r["opened_ts"]))
                if c is None or pr > c[0]:
                    cand[(r["token"], r["opened_ts"])] = (pr, r, key)
            for pr, r, key in cand.values():
                if pr > thr and gated(facts(r)):
                    g_picks.append((key, r["ret"]))
                elif pr > thr:
                    picks.append((key, r["ret"]))
                    prof_pick.setdefault(r["profil"], []).append((key, r["ret"]))
                    detail.append((key, r["ret"], pr, r.get("rt")))
        for r, f in batch:
            if r.get("closed_ts") is not None:
                heapq.heappush(pending, (r["closed_ts"], seq, r, f))
                seq += 1
        seen += 1
    late = 0
    for c_ts, _s, r0, f0 in sorted(pending, key=lambda x: x[:2]):   # after the last scored day: the live model's rows
        if now is None or c_ts <= now:
            m.add(r0, f0)
        else:
            late += 1                                                # not closed by `now`: never in a model
    in_model = sum(t[0] for t in m.tot.values())
    eff = []
    for (p, k, v), c in m.cell.items():
        if v != "?" and c[0] >= 100:
            eff.append({"profil": p, "fact": k, "value": v, "n": c[0], "effect": m.effect(p, k, v),
                        "mean": c[1] / c[0]})
    eff.sort(key=lambda e: e["effect"])
    res = {"rows": len(rows), "live_rows": sum(1 for r in rows if r.get("src") == "uzivo"), "days": len(days),
           "test_days": max(0, len(days) - min_train_days), "thr": thr, "purge": True, "model_rows": in_model,
           "not_closed": len(rows) - in_model - late, "closed_later": late,
           "picked": _stat(picks), "all": _stat(every),
           "u_filtru": {"picked": _stat(g_picks), "all": _stat(g_every)},
           "by_profile": {p: {"all": _stat(prof_all.get(p, [])), "picked": _stat(prof_pick.get(p, [])),
                              "base": m.base(p)} for p in sjena.PROFILES},
           "worst": eff[:6], "best": eff[-6:][::-1], "variants": _variants(detail, fixed)}
    pk = res["picked"]
    if pk["clusters"] >= MIN_CLUSTERS and pk["lo"] is not None and pk["lo"] > 0:
        res["verdict"] = "kandidat"
    elif pk["clusters"] < MIN_CLUSTERS:
        res["verdict"] = "premalo"
    else:
        res["verdict"] = "nema_plusa"
    return res


def _variants(detail, fixed):
    """The same unseen days, looked at a few more ways (18.11., after the first result: chosen +0.6 % against -4.5 %
    for all, interval across zero). thr: only the choices predicted above +1 / +2 / +3 %. rt: the choices at a
    cheaper round trip, APPROXIMATE: the saved cost is added to the result, the exit levels stay where the 3 % cost
    put them. fixed: plain rules without the model (a band under one exit). All of them were looked at on the SAME
    days as the main result, so a plus here is a hypothesis for the days to come, never a proof."""
    out = {"thr": {}, "rt": {}, "fixed": {}}
    for t in VAR_THR:
        out["thr"][f"{t:.2f}"] = _stat([(k, x) for k, x, pr, _rt in detail if pr > t])
    for alt in VAR_RT:
        out["rt"][f"{alt:.3f}"] = _stat([(k, x + max(0.0, (rt or 0.0) - alt)) for k, x, _pr, rt in detail])
    for (band, prof), pairs in fixed.items():
        out["fixed"][f"{band} × {prof}"] = _stat(pairs)
    return out


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
    uf = res.get("u_filtru") or {}
    return (f"{PREFIX}{res['rows']} zamišljenih tradeova ({bf.get('rows', 0)} iz povijesti {bf.get('tokens', 0)} tokena"
            f"{' (djelomično)' if bf.get('partial') else ''}, {res.get('live_rows', 0)} uživo), {res['days']} dana, "
            f"provjera na zadnjih {res['test_days']} neviđenih"
            f"{', rezultat ulazi u učenje tek kad je trade zatvoren' if res.get('purge') else ''}; presuda: "
            f"{VERDICT_HR.get(res.get('verdict'), '?')}; "
            f"odabrani: {_s(res.get('picked'))}; svi tih dana: {_s(res.get('all'))}; "
            + (f"u filtru tržišta (risk-off / BTC slobodan pad, pravi novac bi stajao, izvan presude): odabrani "
               f"{_s(uf.get('picked'))}, svi {_s(uf.get('all'))}; " if (uf.get("all") or {}).get("n") else "")
            + f"najviše pomaže: {best}; "
            f"najviše šteti: {worst} ({res.get('secs', 0)} s)")


def line_variants(res):
    """The second line: the choices by exit, stricter thresholds, cheaper round trips and the plain rules."""
    v = (res or {}).get("variants")
    if not v:
        return None

    def short(st):
        if not st or not st.get("n"):
            return "nema"
        ci = f" [{st['lo']:+.1%}; {st['hi']:+.1%}]" if st.get("lo") is not None else ""
        return f"{st['ev']:+.1%}{ci}, n={st['n']} ({st['clusters']} token-dana)"
    prof = "; ".join(f"{p} {short(d.get('picked'))} (svi {short(d.get('all')).split(',')[0]})"
                     for p, d in (res.get("by_profile") or {}).items() if (d.get("picked") or {}).get("n"))
    thr = "; ".join(f"iznad {float(t):+.0%}: {short(st)}" for t, st in v["thr"].items())
    rt = "; ".join(f"uz trošak {float(a):.1%}: {short(st)}" for a, st in v["rt"].items())
    fx = "; ".join(f"{k}: {short(st)}" for k, st in v["fixed"].items())
    return (f"{PREFIX}varijante na istim neviđenim danima (hipoteze za nove dane, nisu dokaz): odabrani po izlazu: "
            f"{prof or 'nema'}; stroži prag prognoze: {thr}; isti odabir uz niži trošak (približno): {rt}; "
            f"jednostavna pravila bez modela: {fx}")


def _kv(path, key):
    """One stored value of nauceno.db, read-only; {} when the file, the table or the key is missing."""
    p = db_path(path)
    if not os.path.exists(p):
        return {}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        r = con.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return json.loads(r[0]) if r else {}
    except (sqlite3.Error, ValueError, TypeError):
        return {}
    finally:
        con.close()


def latest(path=None):
    return _kv(path, KV)


_MODEL = {}     # nauceno.db path -> {"at": when it was last read, "m": the Model or None}


def _stored_model(path=None, now=None):
    """The stored model whatever its age (None when there is none), re-read at most every MODEL_RELOAD_S and rebuilt
    only when the stored ts changed."""
    now = time.time() if now is None else now
    p = db_path(path)
    hit = _MODEL.get(p)
    if hit is None or abs(now - hit["at"]) >= MODEL_RELOAD_S:
        d = _kv(p, KV_MODEL)
        m = hit["m"] if hit else None
        try:
            if not d or not d.get("ts"):
                m = None
            elif m is None or m.ts != int(d["ts"]):
                m = Model.from_dict(d)
        except (KeyError, TypeError, ValueError):   # a stored value this code cannot read is no model
            m = None
        hit = _MODEL[p] = {"at": now, "m": m}
    return hit["m"]


def load_model(path=None, now=None):
    """The model run() stored (read-only, kept in memory by its ts), or None when there is none or it is older than
    MODEL_MAX_AGE_S: nothing may trade on a learner that stopped running."""
    now = time.time() if now is None else now
    m = _stored_model(path, now)
    return m if m is not None and now - m.ts <= MODEL_MAX_AGE_S else None


def model_ts(path=None, now=None):
    """When the stored model was trained (None: no model), whatever its age: for the line that says why nobody enters."""
    m = _stored_model(path, now)
    return m.ts if m is not None else None


def summary(res=None):
    """The compact block for the MCP tool and the report: the verdict, the numbers, what helps and what hurts."""
    res = res if res is not None else latest()
    if not res or not res.get("ts"):
        return None

    def rnd(st):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in (st or {}).items()}
    return {"ts": res["ts"], "verdict": res.get("verdict"), "verdict_text": VERDICT_HR.get(res.get("verdict")),
            "purge": bool(res.get("purge")), "history_point_in_time": bool((res.get("backfill") or {}).get("pit")),
            "rows": res.get("rows"), "live_rows": res.get("live_rows"), "days": res.get("days"),
            "test_days": res.get("test_days"), "picked": rnd(res.get("picked")), "all": rnd(res.get("all")),
            "by_profile": {p: {"all": rnd(v.get("all")), "picked": rnd(v.get("picked"))}
                           for p, v in (res.get("by_profile") or {}).items()},
            "helps": [_e(e) for e in res.get("best") or []], "hurts": [_e(e) for e in res.get("worst") or []],
            "variants": {g: {k: rnd(st) for k, st in d.items()} for g, d in (res.get("variants") or {}).items()},
            "variants_note": ("Looked at on the same unseen days as the main result: hypotheses for the days to come, "
                              "not proof. rt variants are approximate (saved cost added, exit levels unchanged)."),
            "how": ("Per exit profile: the profile's mean net return plus one shrunken adjustment per fact known before "
                    "the entry; a candidate takes its best-predicted profile when the prediction is above zero. Tested "
                    "day by day on days the model had not seen. Costs: the real round trip, never under 3 %. purge = "
                    "true: a trade's result enters the model only once the trade is closed before the scored day "
                    "began (a result computed before 18.11. had a look-ahead leak and reads too well). "
                    "history_point_in_time: a history row exists only when the token was inside the 2M-200M universe "
                    "at its open (by price x today's supply).")}


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
            rows = load(wcon, lcon, now)
            m = Model()
            # the walk-forward (purged: a row enters once it is closed before the scored day); after the last day m
            # takes every row closed by now: the live model never holds a result that is not final yet
            res = learn(rows, model=m, now=now)
            res.update(ts=now, backfill=bf, secs=round(time.time() - t0, 1))
            if save:
                wcon.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (KV, json.dumps(res, ensure_ascii=False, default=str)))
                wcon.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)",
                             (KV_MODEL, json.dumps(m.dump(now, res["model_rows"], res["days"]), ensure_ascii=False)))
                wcon.commit()
        finally:
            for c in (mcon, wcon, lcon):
                if c is not None:
                    c.close()
        log(line(res))
        lv = line_variants(res)
        if lv:
            log(lv)
        return res
    except Exception as e:  # noqa: BLE001 - a measurement: it never takes its caller down
        try:
            log(PREFIX + f"nije uspio ({type(e).__name__}: {str(e)[:160]})")
        except Exception:  # noqa: BLE001
            pass
        return {}
