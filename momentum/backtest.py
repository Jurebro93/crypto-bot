"""Backtest of momentum_scalp over the last 7 days of minute candles we hold, with the live rules (momentum/rules.py).

Data, merged per token by rangedca/data.merge (real OHLCV wins; snapshot minutes carry their price and the
volume / transactions they stand for): momentum.db snaps (our own DexScreener minute), range.db snaps and its
GeckoTerminal candles, minute.db call_candles (GeckoTerminal OHLCV around calls), hype.db token_pulse, and
momentum.db gt_candles: at most `gt` (MOM_BT_GT, 60) GeckoTerminal OHLCV requests a night inside momentum's day cap
(data.GT_DAY), for signal tokens and called tokens that have no real candles yet.

At every minute's close: MC = price x supply in 30k-3M, liquidity >= $15k where the history knows it (unknown is not
refused: said in the report), 5-min change +5..+15 %, the 5-min volume >= 3x the average 5 min of the 55 before,
buys >= 60 % of the 5-min transactions (minutes without transaction counts: the share of volume in rising minutes,
"proxy"; the variant samo_s_transakcijama uses only minutes with real counts). 45 minutes' cooldown per token after
a signal. NOT simulated (no history of them): unique buyers rising, the anti-wash check, top 10, the rug verdict,
the shill network. They only remove signals; whether they remove more losers than winners is unknown, so the
backtest is the entry's price-and-volume edge, an upper bound on the signal count.
Exits on the following candles (rules.simulate): TP1 half at its level, trailing 8 %, stop -10 % (a candle that
touches both the stop and TP1 is a stop; a gap fills at the open), out at 45 min; cost: rules.round_trip_cost
(trade/cost: the fee each side + the pool impact of a $15 lot both ways). Base rate per signal: +15 % before -10 % within 45 min (rules.outcome).
Output: output/momentum-backtest-YYYYMMDD.{json,md} and the summary in the log ("momentum backtest | ...").
"""
import bisect
import json
import os
import statistics
import time

from . import data, rules

DAYS = 7
VARIANTS = {"osnovno": {"proxy": True}, "samo_s_transakcijama": {"proxy": False}}


def _prefix(xs):
    out = [0.0]
    for x in xs:
        out.append(out[-1] + (x or 0.0))
    return out


def signals_of(candles, supply, liq=None, proxy=True, cfg=None):
    """[(index, features)] of the minutes that meet the simulated entry conditions (45 min cooldown)."""
    c = rules._r(cfg)
    if not candles or not supply:
        return []
    ts = [x[0] for x in candles]
    vol = _prefix([x[5] for x in candles])
    out, cool = [], 0
    for i, row in enumerate(candles):
        t, px = row[0], row[4]
        if t < cool or not px:
            continue
        mcap = px * supply
        if not c["mcap_min"] <= mcap <= c["mcap_max"]:
            continue
        if liq is not None and liq < c["liq_min"]:
            continue
        j5 = bisect.bisect_right(ts, t - 300)          # first index inside (t-300, t]
        j60 = bisect.bisect_right(ts, t - 3600)
        if j5 >= i or j60 >= j5:
            continue
        k = bisect.bisect_right(ts, t - 300) - 1        # the close at or before t-5 min
        if k < 0 or not candles[k][4] or t - candles[k][0] > 420:
            continue
        ch = px / candles[k][4] - 1
        if not c["ch5_min"] - 1e-9 <= ch <= c["ch5_max"] + 1e-9:
            continue
        v5 = vol[i + 1] - vol[j5]
        base = (vol[j5] - vol[j60]) / 11
        if base <= 0 or v5 / base < c["vol_x_min"] - 1e-9:
            continue
        b = sum(x[6] or 0 for x in candles[j5:i + 1] if x[6] is not None)
        s = sum(x[7] or 0 for x in candles[j5:i + 1] if x[7] is not None)
        if b + s > 0:
            bs, how = b / (b + s), "transakcije"
        elif proxy:
            up = sum(x[5] or 0 for x in candles[j5:i + 1] if x[4] >= x[1])
            tot = sum(x[5] or 0 for x in candles[j5:i + 1])
            bs, how = (up / tot if tot else None), "proxy"
        else:
            continue
        if bs is None or bs < c["buy_share_min"] - 1e-9:
            continue
        out.append((i, {"ts": t, "price": px, "mcap": round(mcap), "ch_m5": round(ch * 100, 2),
                        "vol_x": round(v5 / base, 2), "buy_share": round(bs, 3), "buy_share_how": how}))
        cool = t + c["cooldown_s"]
    return out


def simulate_token(candles, supply, liq=None, proxy=True, cfg=None):
    """Every simulated signal of one token with its base-rate outcome and the exit rules' result after cost."""
    out = []
    for i, f in signals_of(candles, supply, liq, proxy, cfg):
        path = [(x[0], x[1], x[2], x[3], x[4]) for x in candles[i + 1:i + 1 + 60]]
        o = rules.outcome(path, f["price"], f["ts"], cfg=cfg)
        if o["first"] is None:
            continue   # the data ends inside the 45 minutes
        res, why = rules.simulate(path, f["price"], f["ts"], liq, cfg=cfg)
        out.append({**f, "first": o["first"], "hit": o["hit"], "max_pct": o["max_pct"], "min_pct": o["min_pct"],
                    "ret": res, "exits": why, "cost": rules.round_trip_cost(rules.LOT_USD, liq)})
    return out


def summary(sigs):
    n = len(sigs)
    if not n:
        return {"signals": 0, "hits": 0, "hit_rate": None, "sl_first": None, "ev_pct": None, "median_pct": None,
                "worst_pct": None, "break_even_hit": None, "exit_reasons": {}}
    rets = [s["ret"] for s in sigs if s["ret"] is not None]
    c = statistics.mean(s["cost"] for s in sigs)
    reasons = {}
    for s in sigs:
        k = (s["exits"] or ["?"])[-1]
        reasons[k] = reasons.get(k, 0) + 1
    hits = sum(s["hit"] for s in sigs)
    return {"signals": n, "hits": hits, "hit_rate": round(hits / n, 3),
            "sl_first": round(sum(1 for s in sigs if s["first"] == "sl") / n, 3),
            "ev_pct": round(statistics.mean(rets) * 100, 2) if rets else None,
            "median_pct": round(statistics.median(rets) * 100, 2) if rets else None,
            "worst_pct": round(min(rets) * 100, 2) if rets else None,
            "avg_cost_pct": round(c * 100, 2),
            "break_even_hit": round(rules.break_even_p(rules.RULES["tp1"], rules.RULES["stop"], c), 3),
            "exit_reasons": reasons}


def run_tokens(series, cfg=None):
    """series: {token: (candles, supply, liq, symbol)} -> the report dict."""
    t0 = time.time()
    var = {k: [] for k in VARIANTS}
    per = {}
    for tok, (candles, supply, liq, sym) in series.items():
        if not candles or not supply:
            continue
        per[tok] = {"symbol": sym, "minutes": len(candles), "liq": liq,
                    "tx_counts": any(c[6] is not None for c in candles)}
        for k, v in VARIANTS.items():
            sigs = simulate_token(candles, supply, liq, v["proxy"], cfg)
            for s in sigs:
                s["token"], s["symbol"] = tok, sym
            var[k] += sigs
            per[tok][f"signals_{k}"] = len(sigs)
    return {"generated_ts": int(time.time()), "tokens_with_data": len(series), "tokens_simulated": len(per),
            "cpu_s": round(time.time() - t0, 1), "lot_usd": rules.LOT_USD,
            "variants": {k: summary(v) for k, v in var.items()},
            "signals": {k: sorted(v, key=lambda s: s["ts"])[-200:] for k, v in var.items()},
            "tokens": per,
            "note": ("bez simulacije: rast jedinstvenih kupaca, provjera lažnog volumena, top 10, rug ocjena i mreža "
                     "shillera (nema povijesti); likvidnost nepoznata u povijesti se ne odbija")}


def md(rep):
    lines = [f"# Momentum scalp backtest ({rep.get('days', DAYS)} dana)", "",
             f"Tokena s podacima: {rep['tokens_with_data']}, simulirano: {rep['tokens_simulated']}. Lot ${rep['lot_usd']:.0f}, "
             "1 % naknada po strani + utjecaj na pool u oba smjera. " + rep["note"] + ".", "",
             "| varijanta | signala | pogodak (+15 % prije -10 %) | stop prvi | EV po tradeu % | medijan % | najgori % | "
             "prag isplativosti |", "|---|---|---|---|---|---|---|---|"]
    for k, s in rep["variants"].items():
        lines.append(f"| {k} | {s['signals']} | {s['hit_rate'] if s['hit_rate'] is not None else '-'} | "
                     f"{s['sl_first'] if s['sl_first'] is not None else '-'} | "
                     f"{s['ev_pct'] if s['ev_pct'] is not None else '-'} | "
                     f"{s['median_pct'] if s['median_pct'] is not None else '-'} | "
                     f"{s['worst_pct'] if s['worst_pct'] is not None else '-'} | "
                     f"{s.get('break_even_hit') if s.get('break_even_hit') is not None else '-'} |")
    lines += ["", "S TP +15 % / SL -10 % i ~2-3 % povratnog troška prag isplativosti je pogodak ~50 %, ne 45 %.", "",
              "## Zadnji signali (osnovno)", ""]
    for s in (rep["signals"].get("osnovno") or [])[-40:]:
        lines.append(f"- {s.get('symbol') or s['token'][:6]} {time.strftime('%d.%m. %H:%M', time.gmtime(s['ts']))} UTC: "
                     f"MC {s['mcap']:,.0f}, {s['ch_m5']:+.1f} % u 5 min, volumen {s['vol_x']}x, kupnje "
                     f"{s['buy_share']:.0%} ({s['buy_share_how']}); {s['first']}, izlazi {', '.join(s['exits'] or [])}, "
                     f"{(s['ret'] or 0) * 100:+.1f} %")
    return "\n".join(lines) + "\n"


def write(rep, log=print, name=None):
    out = os.path.join(data.ROOT, "output")
    os.makedirs(out, exist_ok=True)
    name = name or f"momentum-backtest-{time.strftime('%Y%m%d', time.gmtime())}"
    with open(os.path.join(out, name + ".json"), "w") as f:
        json.dump(rep, f, ensure_ascii=False)
    text = md(rep)
    with open(os.path.join(out, name + ".md"), "w") as f:
        f.write(text)
    for ln in text.splitlines()[:14]:
        if ln.strip():
            log(f"momentum backtest | {ln}")
    return os.path.join(out, name + ".md")


# ---------- the data we have (server) -------------------------------------------------------------------------------
def own_snaps(mcon, token, t0):
    return [{"ts": r[0], "price": r[1], "mcap": r[2], "liq": r[3], "vol_m5": r[4], "vol_h1": r[5], "buys_m5": r[6],
             "sells_m5": r[7]}
            for r in mcon.execute("SELECT ts, price, mcap, liq, vol_m5, vol_h1, buys_m5, sells_m5 FROM snaps WHERE token=? "
                                  "AND ts>=? ORDER BY ts", (token, int(t0)))]


def tokens_with_data(mcon, now, days=DAYS):
    from rangedca import backtest as rbt, data as rdata
    t0 = int(now - days * 86400)
    toks = {r[0] for r in mcon.execute("SELECT token FROM snaps WHERE ts >= ? GROUP BY token HAVING COUNT(*) >= 60", (t0,))}
    toks |= {r[0] for r in mcon.execute("SELECT token FROM gt_candles WHERE last_ts >= ?", (t0,))}
    rcon = rdata.ro()
    if rcon is not None:
        try:
            toks |= set(rbt.tokens_with_data(rcon, now, days))
        except Exception:  # noqa: BLE001
            pass
        finally:
            rcon.close()
    return sorted(toks)


def load(mcon, token, now, days=DAYS):
    """(candles, supply, liquidity, symbol) of one token from every store (rangedca/data.merge)."""
    from rangedca import backtest as rbt, data as rdata
    t0 = int(now - days * 86400)
    snaps = own_snaps(mcon, token, t0) + rdata.pulse_rows(token, t0)
    true = rdata.call_candles(token, t0, now)
    r = mcon.execute("SELECT data FROM gt_candles WHERE token=?", (token,)).fetchone()
    if r:
        true += [c for c in rdata.unpack(r[0]) if t0 <= c[0] <= now]
    rcon = rdata.ro()
    if rcon is not None:
        try:
            snaps += rdata.own_rows(rcon, token, t0)
            true += rdata.gt_rows(rcon, token, t0, now)
        except Exception:  # noqa: BLE001
            pass
        finally:
            rcon.close()
    candles = rdata.merge(true, snaps)
    liqs = [s["liq"] for s in snaps if s.get("liq")]
    p = mcon.execute("SELECT symbol FROM pools WHERE token=?", (token,)).fetchone()
    return candles, rbt._supply(token, snaps), (statistics.median(liqs) if liqs else None), (p[0] if p else None)


def top_up(mcon, now, n, days=DAYS, fetch=None, log=print):
    """At most n GeckoTerminal OHLCV requests (inside data.GT_DAY) for tokens with a momentum signal, then tokens
    called at MC >= 30k, in the last `days` that have no real candles here yet: 1000 minutes each. Returns the count."""
    if n <= 0:
        return 0
    want = [(r[0], r[1]) for r in mcon.execute(
        "SELECT s.token, MIN(s.ts) FROM signals s WHERE s.ts >= ? GROUP BY s.token ORDER BY MAX(s.ts) DESC",
        (int(now - days * 86400),))]
    try:
        from kol import store as kstore
        kc = data._ro_file(kstore.DB)
    except Exception:  # noqa: BLE001
        kc = None
    want += [(r[0], r[1]) for r in data._q(kc, "SELECT token, MIN(ts) FROM calls WHERE ts >= ? AND COALESCE(mcap0,0) >= ? "
                                                "GROUP BY token ORDER BY COUNT(*) DESC LIMIT 200",
                                           (int(now - days * 86400), data.MIN_MCAP))]
    if kc is not None:
        kc.close()
    from rangedca import data as rdata
    done, seen = 0, set()
    for tok, first in want:
        if done >= n:
            break
        if tok in seen:
            continue
        seen.add(tok)
        if mcon.execute("SELECT 1 FROM gt_candles WHERE token=?", (tok,)).fetchone() or rdata.call_candles(tok, first - 3600, first + 3600):
            continue
        p = mcon.execute("SELECT pool FROM pools WHERE token=?", (tok,)).fetchone()
        pool = p[0] if p else None
        if not pool:
            continue
        if not data.gt_take(mcon, now):
            break
        start = int(first - 3600)
        try:
            got = (fetch or rdata.gt_fetch)(pool, start, min(int(now), start + 998 * 60))
        except Exception:  # noqa: BLE001
            got = None
        if got is None:
            break   # GeckoTerminal busy or refused: the rest next night
        rows = [tuple(c[:6]) for c in got]
        if rows:
            mcon.execute("INSERT OR REPLACE INTO gt_candles VALUES (?,?,?,?,?,?,?)",
                         (tok, pool, rows[0][0], rows[-1][0], len(rows), rdata.pack(rows), int(now)))
        mcon.commit()
        done += 1
    if done:
        log(f"momentum backtest: {done} GeckoTerminal zahtjeva za povijest (dnevni strop {data.GT_DAY})")
    return done


def run_server(now=None, days=DAYS, gt=0, log=print, fetch=None):
    now = int(now or time.time())
    mcon = data.connect()
    try:
        top_up(mcon, now, gt, days, fetch, log)
        series = {tok: load(mcon, tok, now, days) for tok in tokens_with_data(mcon, now, days)}
    finally:
        mcon.close()
    rep = run_tokens(series)
    rep["days"] = days
    path = write(rep, log)
    v = rep["variants"]["osnovno"]
    log(f"momentum backtest: {rep['tokens_simulated']} tokena, {v['signals']} signala, pogodak {v['hit_rate']}, "
        f"EV {v['ev_pct']} % po tradeu, {rep['cpu_s']} s, izvještaj {path}")
    return rep
