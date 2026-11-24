"""The walk-forward persistence test (the owner's question: does a token that oscillated today oscillate tomorrow, and
does the scalp pay after costs?), its report and the run after a deploy / at night.

For every token with minute bars (scan.load_server on the server, tests/fixtures range_*.json.gz locally):
  1. per Zagreb day D: scan.day_metrics from day D's bars ONLY, and the rule (rule.simulate) on day D's bars with the
     previous hour as the window's warm-up, at every size (0.1 / 0.3 / 0.5 / 1.0 SOL) x target (1 $ / 2 $ net),
     the cost at the token's liquidity (rule.cost_at; demo fee alongside, rule.demo_rt)
  2. walk-forward: for every day D with a day D+1, the eligible tokens of D ranked by score (swings x (1 - er), ties
     by liquidity) -> the TOP K (10) -> their day-D+1 results (nothing of D+1 is read to pick; a pick without D+1
     bars counts as a token-day with no trade and "nestao"); next to it every eligible token of D on D+1 ("svi"), so
     the ranking's value shows
  3. per size and target: trades a token-day, hit rate, EV net a trade (% and $), $ a day for the K tokens, max
     drawdown of the daily sum, worst day, the share of picked token-days that broke (scan breakdown on D+1 or no
     data) and their PnL, the bootstrap 90 % interval by token-days (B 1000): EV % a trade (sum ret / sum n) and $ a day
  4. persistence: the mean Spearman rank correlation of score(D) with swings(D+1) over the tokens present both days
  5. the range scalp (rangedca/backtest.simulate with rules.SCALP at the real cost, backtest.real_cfg) on the SAME
     picked token-days, at every size: rounds, EV, $ a day (time-bounded: the range timeline is the heavy part)
Outputs: oscilator.db (store.save: the run, today's top K, the proof numbers), output/oscilator.md and the log lines
"oscilator: velicina S SOL $T: n=..., EV ...", "oscilator: top 10 danas: ...".
"""
import glob
import gzip
import json
import os
import random
import statistics
import time

from . import rule, scan

PREFIX = "oscilator: "
TOP_K = 10
DAYS = 10
BUDGET_S = int(os.environ.get("OSC_BUDGET_S", "900"))
BOOT_B = 1000
REF_TARGET = 1.0
SENS = {"osnovno": {}, "pojas 20 %": {"band": 0.20}, "pojas 33 %": {"band": 0.33}, "prozor 30 min": {"win_s": 1800},
        "prozor 120 min": {"win_s": 7200}, "stop 5 %": {"stop_pct": 0.05}, "stop 12 %": {"stop_pct": 0.12},
        "vrijeme 30 min": {"time_s": 1800}, "stop puni na razini": {"stop_fill": "level"},
        "bez stopa, 60 min": {"stop_pct": 0.99}, "bez stopa, 24 h": {"stop_pct": 0.99, "time_s": 86400}}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def _key(s, t):
    return f"{s:g}@{t:g}"


def costs(sol_usd):
    """The cost inputs of the run: the real fee a side, the network fee a swap (measured or default), the demo fee."""
    tx, tx_src = rule.tx_sol()
    return {"fee_side": rule.real_fee_side(), "tx_sol": tx, "tx_src": tx_src, "demo_fee_side": rule.demo_fee_side(),
            "sol_usd": sol_usd}


def token_days(candles, supply, liq, cst, sizes=rule.SIZES_SOL, targets=rule.TARGETS_USD, cfg=None, keep=False):
    """{day: {"m": day metrics, "r": {size@target: [n, wins, sum ret, sum pnl, sum ret_demo, sum pnl_demo]},
    "t": trades (keep only)}} of one token."""
    c = {**rule.RULE, **(cfg or {})}
    su = cst["sol_usd"]
    days = scan.split_days(candles)
    win = rule.windows(candles, c["win_s"])
    ts = [b[0] for b in candles]
    import bisect
    rts = {s: rule.cost_at(s, liq, su, cst["fee_side"], cst["tx_sol"])["rt"] for s in sizes}
    drts = {s: rule.demo_rt(s * su, liq, cst["demo_fee_side"]) for s in sizes}
    out = {}
    for d, bars in sorted(days.items()):
        m = scan.day_metrics(bars, liq, supply, su, sizes, cst["fee_side"], cst["tx_sol"])
        d0 = scan.day_start(d)
        lo = bisect.bisect_left(ts, d0 - c["win_s"])
        hi = bisect.bisect_left(ts, d0 + 86400)
        rec = {"m": m, "r": {}}
        if keep:
            rec["t"] = {}
        for s in sizes:
            for tg in targets:
                tr = rule.simulate(candles[lo:hi], s * su, liq, tp_usd=tg, rt=rts[s], t0=d0, t1=d0 + 86400, cfg=c,
                                   win=win[lo:hi], drt=drts[s])
                rec["r"][_key(s, tg)] = [len(tr), sum(1 for x in tr if x["pnl"] > 0), sum(x["ret"] for x in tr),
                                         sum(x["pnl"] for x in tr), sum(x["ret_demo"] for x in tr),
                                         sum(x["pnl_demo"] for x in tr),
                                         min((x["ret"] for x in tr), default=None),
                                         sum(1 for x in tr if x["reason"] in ("stop", "rug"))]
                if keep:
                    rec["t"][_key(s, tg)] = tr
        out[d] = rec
    return out, rts, drts


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        o = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    a, b = ranks(xs), ranks(ys)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    return cov / (va * vb) ** 0.5 if va > 0 and vb > 0 else None


def pick(per, day, k=TOP_K, exclude=()):
    """The top k tokens of day `day` by its metrics only: [(token, metrics)]."""
    c = [(rec[day]["m"]["score"], rec[day]["m"].get("liq") or 0, tok) for tok, rec in per.items()
         if day in rec and rec[day]["m"].get("eligible") and tok not in exclude]
    c.sort(reverse=True)
    return [(tok, per[tok][day]["m"]) for sc, _l, tok in c[:k] if sc > 0]


def broke(m0, m1):
    """A picked token-day that broke: no bars on D+1 (gone), scan's breakdown inside D+1, or against the price it was
    picked at (day D's close): D+1's low under half of it or its close under 60 % of it."""
    if not m1 or not m1.get("bars"):
        return True
    if m1.get("breakdown"):
        return True
    c0 = (m0 or {}).get("close")
    return bool(c0 and ((m1.get("low") or c0) < 0.5 * c0 or (m1.get("close") or c0) < 0.6 * c0))


def agg(units, key, n_days, k=TOP_K, boot=BOOT_B, seed=7):
    """Stats of token-day units [(day, token, r or None, metrics_d1 or None, metrics_d)] for one size@target."""
    rows = []
    for d, tok, r, m1, m0 in units:
        x = (r or {}).get(key) or [0, 0, 0.0, 0.0, 0.0, 0.0, None, 0]
        rows.append((d, tok, x, broke(m0, m1)))
    n = sum(x[0] for _d, _t, x, _b in rows)
    out = {"token_days": len(rows), "n": n, "days": n_days}
    if not rows:
        return out
    wins = sum(x[1] for _d, _t, x, _b in rows)
    sr, sp, srd, spd = (sum(x[i] for _d, _t, x, _b in rows) for i in (2, 3, 4, 5))
    daily = {}
    for d, _t, x, _b in rows:
        daily[d] = daily.get(d, 0.0) + x[3]
    eq = peak = dd = 0.0
    for d in sorted(daily):
        eq += daily[d]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    br = [x for _d, _t, x, b in rows if b]
    out.update(per_token_day=round(n / len(rows), 2), hit=round(wins / n, 3) if n else None,
               ev_pct=round(sr / n * 100, 3) if n else None, ev_usd=round(sp / n, 4) if n else None,
               pnl_usd=round(sp, 2), usd_day=round(sp / n_days, 2) if n_days else None,
               ev_demo_pct=round(srd / n * 100, 3) if n else None, usd_day_demo=round(spd / n_days, 2) if n_days else None,
               max_dd_usd=round(dd, 2), worst_day_usd=round(min(daily.values()), 2) if daily else None,
               worst_trade_pct=round(min((x[6] for _d, _t, x, _b in rows if x[6] is not None), default=0) * 100, 2),
               stops=sum(x[7] for _d, _t, x, _b in rows),
               broke_share=round(len(br) / len(rows), 3), broke_pnl_usd=round(sum(x[3] for x in br), 2))
    if boot and n:
        rnd = random.Random(seed)
        L = len(rows)
        evs, usd = [], []
        for _ in range(boot):
            sn = s_r = s_p = 0.0
            for _i in range(L):
                x = rows[rnd.randrange(L)][2]
                sn += x[0]
                s_r += x[2]
                s_p += x[3]
            if sn:
                evs.append(s_r / sn * 100)
            usd.append(s_p / L * min(k, L / max(1, n_days)))
        evs.sort()
        usd.sort()
        if evs:
            out["ci90_ev_pct"] = [round(evs[int(0.05 * len(evs))], 3), round(evs[int(0.95 * len(evs)) - 1], 3)]
        out["ci90_usd_day"] = [round(usd[int(0.05 * len(usd))], 2), round(usd[int(0.95 * len(usd)) - 1], 2)]
    return out


def walk(per, sizes=rule.SIZES_SOL, targets=rule.TARGETS_USD, k=TOP_K, exclude=(), today=None):
    """The walk-forward over per {token: token_days}: {"picks", "top", "all", "persistence", "days"}."""
    days = sorted({d for rec in per.values() for d in rec})
    picks, units_top, units_all, rhos = {}, [], [], []
    for d in days:
        d1 = d + 1
        if d1 not in days:
            continue
        top = pick(per, d, k, exclude)
        if not top:
            continue
        picks[d1] = [t for t, _m in top]
        for tok, m0 in top:
            r1 = per[tok].get(d1)
            units_top.append((d1, tok, (r1 or {}).get("r"), (r1 or {}).get("m"), m0))
        for tok, rec in per.items():
            if d in rec and rec[d]["m"].get("eligible") and tok not in exclude:
                r1 = rec.get(d1)
                units_all.append((d1, tok, (r1 or {}).get("r"), (r1 or {}).get("m"), rec[d]["m"]))
        both = [(rec[d]["m"]["score"], rec[d1]["m"]["swings"].get(f"{scan.REF_SOL:g}", 0)) for rec in per.values()
                if d in rec and d1 in rec and rec[d]["m"].get("bars", 0) >= scan.MIN_DAY_BARS]
        rho = spearman([a for a, _b in both], [b for _a, b in both])
        if rho is not None:
            rhos.append(rho)
    nd = len(picks)
    out = {"picks": {str(d): v for d, v in picks.items()}, "days": nd, "top": {}, "all": {},
           "persistence": {"spearman_mean": round(statistics.mean(rhos), 3) if rhos else None, "days": len(rhos)}}
    for s in sizes:
        for tg in targets:
            key = _key(s, tg)
            out["top"][key] = agg(units_top, key, nd, k)
            out["all"][key] = agg(units_all, key, nd, k, boot=0)
    return out


def range_compare(get, picks, sizes, cst, deadline):
    """The range scalp (rules.SCALP at the real cost) on the picked token-days: {size: stats} and how many tokens."""
    from rangedca import backtest as bt, rules as rr
    want = {}
    for d, toks in picks.items():
        for t in toks:
            want.setdefault(t, set()).add(int(d))
    res = {f"{s:g}": [] for s in sizes}
    done = 0
    for tok, ds in want.items():
        if time.time() > deadline:
            break
        candles, supply, liq, _sym = get(tok) or (None, None, None, None)
        if not candles or not supply or candles[-1][0] - candles[0][0] < 6 * 3600:
            continue
        tl = bt.timeline(candles, supply, liq, flip=True)
        for s in sizes:
            cfg = bt.real_cfg(sol_usd=cst["sol_usd"], tx_sol=cst["tx_sol"])
            rs = bt.simulate(candles, supply, tl, rr._r(cfg)["score_min"], True, liq, lot_usd=s * cst["sol_usd"],
                             new=("atr",), ticks="wick", cfg=cfg)
            for r in rs:
                if r.get("closed") and scan.day_of(r["opened"]) in ds:
                    pnl = bt.priced(r, liq, cfg)[0]
                    res[f"{s:g}"].append((pnl, pnl / r["cost"] if r["cost"] else 0.0))
        done += 1
    nd = len(picks)
    td = sum(len(v) for v in want.values())
    out = {"tokens": done, "tokens_wanted": len(want), "token_days": td}
    for s, v in res.items():
        n = len(v)
        out[s] = {"n": n, "per_token_day": round(n / td, 2) if td else None,
                  "hit": round(sum(1 for p, _r in v if p > 0) / n, 3) if n else None,
                  "ev_pct": round(statistics.mean(r for _p, r in v) * 100, 3) if n else None,
                  "ev_usd": round(statistics.mean(p for p, _r in v), 4) if n else None,
                  "usd_day": round(sum(p for p, _r in v) / nd, 2) if nd else None}
    return out


def sensitivity(series, cst, deadline, size=scan.REF_SOL, tp=REF_TARGET):
    """A few neighbours of the rule on every token-day (not walk-forward; to show it is not a knife-edge)."""
    out = {}
    for name, over in SENS.items():
        if time.time() > deadline:
            break
        tot = [0, 0, 0.0, 0.0]
        for tok, (candles, supply, liq, _sym) in series.items():
            if not candles:
                continue
            per, _r, _d = token_days(candles, supply, liq, cst, (size,), (tp,), cfg=over)
            for rec in per.values():
                x = rec["r"][_key(size, tp)]
                for i in range(4):
                    tot[i] += x[i]
        n = tot[0]
        out[name] = {"n": n, "hit": round(tot[1] / n, 3) if n else None,
                     "ev_pct": round(tot[2] / n * 100, 3) if n else None, "pnl_usd": round(tot[3], 2)}
    return out


def fee_table(sol_usd, liqs=(20_000, 40_000, 100_000, 250_000), tx=None, targets=rule.TARGETS_USD):
    """The honest fee math: per size and liquidity the real round trip (%, $) and the move a 1 $ / 2 $ net trade needs."""
    rows = []
    for s in rule.SIZES_SOL:
        for lq in liqs:
            c = rule.cost_at(s, lq, sol_usd, None, tx)
            rows.append({"sol": s, "usd": round(c["size_usd"], 2), "liq": lq, "rt_pct": round(c["rt"] * 100, 2),
                         "rt_usd": round(c["rt"] * c["size_usd"], 3),
                         **{f"need_{tg:g}_pct": round(rule.need_move(rule.target_frac(c["size_usd"], tg), c["rt"])
                                                      * 100, 2) for tg in targets}})
    return rows


# ---------- the data -------------------------------------------------------------------------------------------------

def fixture_series(path=None):
    """{token: (candles, supply, None, symbol)} of every tests/fixtures/range_*.json.gz (the newest file a token)."""
    from rangedca import data
    out = {}
    for f in sorted(glob.glob(os.path.join(path or FIXTURES, "range_*.json.gz"))):
        try:
            with gzip.open(f, "rt") as fh:
                fx = json.load(fh)
        except (OSError, ValueError):
            continue
        if fx.get("token") and fx.get("candles"):
            out[fx["token"]] = (data.merge([tuple(r) for r in fx["candles"]], []), fx.get("supply"), None,
                                fx.get("symbol"))
    return out


class _ServerSeries:
    """{token: series} loaded one token at a time (memory), with per-source coverage."""

    def __init__(self, rcon, toks, now, days):
        self.rcon, self.toks, self.now, self.days = rcon, toks, now, days

    def items(self):
        for t in sorted(self.toks):
            yield t, scan.load_server(self.rcon, t, self.now, self.days)

    def get(self, t, default=None):
        """One token again (never kept: the range comparison reloads only the picked tokens)."""
        return scan.load_server(self.rcon, t, self.now, self.days) if t in self.toks else default


def sol_now():
    try:
        from trade import equity
        v = equity.sol_usd_cached()
        if v and v > 0:
            return float(v)
    except Exception:  # noqa: BLE001
        pass
    return rule.SOL_USD


# ---------- the run --------------------------------------------------------------------------------------------------

def compute(series, now=None, log=print, budget_s=BUDGET_S, sol_usd=None, exclude=(), names=None, sens=None,
            src=None, compare=True):
    """The whole computation over series {token: (candles, supply, liq, symbol)} -> the run's data dict."""
    t_start = time.time()
    deadline = t_start + budget_s
    now = int(now or time.time())
    su = sol_usd or sol_now()
    cst = costs(su)
    per, meta, syms, skipped = {}, {"tokens_seen": 0, "token_days": 0, "token_days_minute": 0, "liq_known": 0}, {}, 0
    local = isinstance(series, dict)
    for tok, (candles, supply, liq, sym) in series.items():
        if time.time() > deadline:
            skipped += 1
            continue
        meta["tokens_seen"] += 1
        if not candles or not supply:
            continue
        syms[tok] = sym or (names or {}).get(tok) or tok[:6]
        meta["liq_known"] += 1 if liq else 0
        per[tok], _r, _d = token_days(candles, supply, liq, cst)
        meta["token_days"] += len(per[tok])
        meta["token_days_minute"] += sum(1 for r in per[tok].values()
                                         if r["m"]["bars"] >= scan.MIN_DAY_BARS and r["m"].get("med_gap_s", 1e9)
                                         <= scan.MAX_GAP_S)
    meta["tokens_used"] = len(per)
    meta["skipped_budget"] = skipped
    meta["eligible_token_days"] = sum(1 for rec in per.values() for r in rec.values() if r["m"].get("eligible"))
    if src:
        meta["sources"] = src
    wf = walk(per, exclude=exclude)
    rc = None
    if compare and wf["picks"] and time.time() < deadline:
        try:
            rc = range_compare(series.get, wf["picks"], rule.SIZES_SOL, cst, deadline)
        except Exception as e:  # noqa: BLE001 - the comparison never stops the run
            rc = {"error": f"{type(e).__name__}: {e}"}
    sv = None
    if (sens if sens is not None else local and len(series) <= 30) and time.time() < deadline:
        sv = sensitivity(series, cst, deadline)
    # today's list: the newest COMPLETE day's metrics (the walk-forward's D); else the newest day with data
    today = scan.day_of(now)
    days = sorted({d for rec in per.values() for d in rec})
    dref = max((d for d in days if d < today), default=max(days) if days else None)
    top = []
    if dref is not None:
        for tok, m in pick(per, dref, TOP_K, exclude):
            top.append({"token": tok, "symbol": syms.get(tok), "score": m["score"], "swings": m["swings"],
                        "er": m["er"], "range_pct": m.get("range_pct"), "drift_pct": m.get("drift_pct"),
                        "liq": m.get("liq"), "mcap": m.get("mcap"), "vol_usd": m.get("vol_usd"), "bars": m["bars"]})
    data = {"ts": now, "cpu_s": round(time.time() - t_start, 1), "cost": cst, "rule": rule.RULE, "k": TOP_K,
            "coverage": meta, "walk": wf, "range_scalp": rc, "sensitivity": sv, "top": top, "top_day": dref,
            "fees": fee_table(su, tx=cst["tx_sol"]), "budget_hit": time.time() > deadline,
            "symbols": {t: syms[t] for d in wf["picks"].values() for t in d if t in syms}}
    return data


def lines(data):
    """The compact log lines of a run."""
    out = []
    wf = data.get("walk") or {}
    cv = data.get("coverage") or {}
    out.append(PREFIX + f"pokrivenost: {cv.get('tokens_used', 0)} tokena s minutnim podacima, {cv.get('token_days', 0)} "
               f"token-dana ({cv.get('token_days_minute', 0)} s gustim minutama, {cv.get('eligible_token_days', 0)} "
               f"prihvatljivih), walk-forward {wf.get('days', 0)} dana, perzistencija (Spearman ocjena D vs swingovi "
               f"D+1) {(wf.get('persistence') or {}).get('spearman_mean')}"
               + (f", izvori {cv['sources']}" if cv.get("sources") else ""))
    for key, x in (wf.get("top") or {}).items():
        s, tg = key.split("@")
        if not x.get("n"):
            out.append(PREFIX + f"velicina {s} SOL cilj ${tg}: n=0 ({x.get('token_days', 0)} token-dana)")
            continue
        a = (wf.get("all") or {}).get(key) or {}
        ci = x.get("ci90_ev_pct") or [None, None]
        out.append(PREFIX + f"velicina {s} SOL cilj ${tg}: n={x['n']} ({x['per_token_day']}/token-dan), pogodak "
                   f"{x['hit'] * 100:.0f} %, EV {x['ev_pct']:+.2f} % ({x['ev_usd']:+.3f} $), $/dan {x['usd_day']:+.2f}, "
                   f"CI90 EV [{ci[0]}; {ci[1]}] %, max pad {x['max_dd_usd']:.2f} $, najgori dan "
                   f"{x['worst_day_usd']:+.2f} $, slomljeni {x['broke_share'] * 100:.0f} % ({x['broke_pnl_usd']:+.2f} $); "
                   f"uz demo naknadu {data['cost']['demo_fee_side'] * 100:.1f} %/strani EV {x['ev_demo_pct']:+.2f} % "
                   f"($/dan {x['usd_day_demo']:+.2f}); svi prihvatljivi EV "
                   f"{a.get('ev_pct') if a.get('ev_pct') is not None else '-'} % n={a.get('n', 0)}")
    rc = data.get("range_scalp") or {}
    if rc and "error" not in rc:
        out.append(PREFIX + "range scalp na istim token-danima: " + "; ".join(
            f"{s} SOL n={v['n']} EV {v['ev_pct'] if v['ev_pct'] is not None else '-'} % $/dan {v['usd_day']}"
            for s, v in rc.items() if isinstance(v, dict)) + f" ({rc.get('tokens')}/{rc.get('tokens_wanted')} tokena)")
    top = data.get("top") or []
    out.append(PREFIX + "top 10 danas: " + (", ".join(
        f"{x['symbol'] or x['token'][:6]} ({x['swings'].get(f'{scan.REF_SOL:g}', 0)} sw, er {x['er']:.2f}, liq "
        f"{(x['liq'] or 0) / 1000:.0f}k)" for x in top) or "nema prihvatljivih tokena"))
    return out


def markdown(data):
    if not data:
        return "# Oscilator\n\nJoš nema izračuna.\n"
    c = data["cost"]
    wf = data["walk"]
    L = ["# Oscilator: walk-forward skalpiranja tokena koji osciliraju", "",
         f"Izračun {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(data['ts']))}, {data['cpu_s']} s CPU"
         + (" (vremenski budžet potrošen: djelomično)" if data.get("budget_hit") else "") + ".", "",
         "## Trošak (pravi model)", "",
         f"Naknada po strani {c['fee_side'] * 100:.2f} % (bazen PumpSwap 0,3 % + ruta 0,1 %), mreža {c['tx_sol']:g} SOL po "
         f"swapu ({c['tx_src']}), SOL ${c['sol_usd']:.0f}; utjecaj na pool = veličina / (likvidnost / 2 + veličina) po "
         f"strani. Demo račun knjiži {c['demo_fee_side'] * 100:.1f} % po strani (trade/cost.fee_side).", "",
         "| SOL | $ | likvidnost | trošak runde % | trošak $ | potreban pomak za 1 $ neto | za 2 $ neto |",
         "|---|---|---|---|---|---|---|"]
    for r in data.get("fees") or []:
        L.append(f"| {r['sol']:g} | {r['usd']:.0f} | {r['liq'] / 1000:.0f}k | {r['rt_pct']:.2f} | {r['rt_usd']:.2f} | "
                 f"{r['need_1_pct']:.2f} % | {r['need_2_pct']:.2f} % |")
    cv = data["coverage"]
    L += ["", "## Podaci", "", f"Tokena s podacima {cv.get('tokens_used')} (viđeno {cv.get('tokens_seen')}), token-dana "
          f"{cv.get('token_days')}, od toga s gustim minutama {cv.get('token_days_minute')}, prihvatljivih "
          f"{cv.get('eligible_token_days')}, likvidnost poznata za {cv.get('liq_known')} tokena."
          + (f" Izvori: {cv['sources']}." if cv.get("sources") else ""), "",
          f"## Walk-forward: top {data['k']} po danu D, trguje se dan D+1 ({wf['days']} dana)", "",
          f"Perzistencija: Spearman(ocjena D, swingovi D+1) = {wf['persistence']['spearman_mean']} "
          f"({wf['persistence']['days']} dana).", "",
          "| SOL@$ | n | /token-dan | pogodak | EV % | EV $ | CI90 EV % | $/dan | CI90 $/dan | max pad $ | najgori dan $ "
          "| slomljeni | EV % uz demo naknadu | svi prihvatljivi EV % (n) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, x in wf["top"].items():
        a = wf["all"].get(key) or {}
        if not x.get("n"):
            L.append(f"| {key} | 0 | | | | | | | | | | | | {a.get('ev_pct')} ({a.get('n', 0)}) |")
            continue
        L.append(f"| {key} | {x['n']} | {x['per_token_day']} | {x['hit'] * 100:.0f} % | {x['ev_pct']:+.2f} | "
                 f"{x['ev_usd']:+.3f} | {x.get('ci90_ev_pct')} | {x['usd_day']:+.2f} | {x.get('ci90_usd_day')} | "
                 f"{x['max_dd_usd']:.2f} | {x['worst_day_usd']:+.2f} | {x['broke_share'] * 100:.0f} % "
                 f"({x['broke_pnl_usd']:+.2f} $) | {x['ev_demo_pct']:+.2f} | {a.get('ev_pct')} ({a.get('n', 0)}) |")
    rc = data.get("range_scalp")
    if rc:
        L += ["", "## Range scalp (rules.SCALP, pravi trošak) na istim token-danima", ""]
        if "error" in rc:
            L.append(f"Greška: {rc['error']}")
        else:
            L += [f"Tokena {rc['tokens']}/{rc['tokens_wanted']}, token-dana {rc['token_days']}.", "",
                  "| SOL | runde | /token-dan | pogodak | EV % | EV $ | $/dan |", "|---|---|---|---|---|---|---|"]
            for s, v in rc.items():
                if isinstance(v, dict):
                    L.append(f"| {s} | {v['n']} | {v['per_token_day']} | {v['hit']} | {v['ev_pct']} | {v['ev_usd']} | "
                             f"{v['usd_day']} |")
    sv = data.get("sensitivity")
    if sv:
        L += ["", f"## Osjetljivost pravila ({scan.REF_SOL:g} SOL, cilj ${REF_TARGET:g}, svi token-dani, nije walk-forward)",
              "", "| varijanta | n | pogodak | EV % | PnL $ |", "|---|---|---|---|---|"]
        for k, v in sv.items():
            L.append(f"| {k} | {v['n']} | {v['hit']} | {v['ev_pct']} | {v['pnl_usd']} |")
    L += ["", f"## Top {data['k']} danas (metrike dana {data.get('top_day')})", "",
          "| token | ocjena | swingovi 0,1/0,3/0,5/1 SOL | er | raspon % | trend % | likvidnost | MC |",
          "|---|---|---|---|---|---|---|---|"]
    for x in data.get("top") or []:
        sw = "/".join(str(x["swings"].get(f"{s:g}", 0)) for s in rule.SIZES_SOL)
        L.append(f"| {x['symbol'] or x['token'][:6]} | {x['score']} | {sw} | {x['er']} | {x['range_pct']} | "
                 f"{x['drift_pct']} | {x['liq']} | {x['mcap']} |")
    r = data["rule"]
    L += ["", "## Pravilo", "", f"Ulaz: zatvaranje u donjih {r['band']:.0%} raspona zadnjih {r['win_s'] // 60} min, iznad "
          f"prethodnog zatvaranja, cilj nakon troška ispod vrha prozora; punjenje na otvaranju sljedećeg bara +"
          f"{r['entry_slip']:.1%}. Izlaz: cilj neto (punjenje −{r['exit_slip']:.1%}), stop −{r['stop_pct']:.0%} (punjenje "
          f"na dnu bara −{r['stop_slip']:.1%}), vremenski stop {r['time_s'] // 60} min, pauza {r['cooldown_s'] // 60} min."]
    return "\n".join(L) + "\n"


def run(now=None, log=print, mode="once", days=DAYS, budget_s=BUDGET_S, series=None, write=True, out_dir=None,
        db_path=None):
    """The run after a deploy / at night: server data (or `series`) -> compute -> oscilator.db, output/oscilator.md,
    the log lines. Returns the data dict."""
    from . import store
    now = int(now or time.time())
    rcon, src, exclude = None, None, ()
    if series is None:
        from rangedca import data as rdata
        rcon = rdata.ro() if hasattr(rdata, "ro") else None
        if rcon is None:
            log(PREFIX + "range.db nije čitljiv: nema podataka")
            series = {}
        else:
            toks = scan.server_tokens(rcon, now, days)
            src = {}
            for t, s in toks.items():
                for x in s:
                    src[x] = src.get(x, 0) + 1
            keep = {t for t, s in toks.items() if scan.bonded(rcon, t, s)}
            exclude = tuple(sorted(t for t in keep if scan.archived(t)))
            series = _ServerSeries(rcon, keep, now, days)
    else:
        exclude = tuple(sorted(t for t in series if scan.archived(t)))
    try:
        data = compute(series, now, log, budget_s, exclude=exclude, src=src)
    finally:
        if rcon is not None:
            rcon.close()
    data["mode"], data["days_window"] = mode, days
    data["excluded_rug"] = len(exclude)
    for ln in lines(data):
        log(ln)
    if write:
        store.save(data, now, path=db_path)
        od = out_dir or os.path.join(ROOT, "output")
        try:
            os.makedirs(od, exist_ok=True)
            with open(os.path.join(od, "oscilator.md"), "w") as f:
                f.write(markdown(data))
        except OSError as e:
            log(PREFIX + f"izvještaj nije zapisan ({e})")
    return data
