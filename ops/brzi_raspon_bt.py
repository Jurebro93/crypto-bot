"""Offline povijesni test bržih ulaza dnevnog raspona (23.11.2026., vlasnik: "Tokeni su skočili, ali su se i povukli.
Nećemo čekati danima da se napravi range."). Unaprijed zadane varijante, bez podešavanja nakon rezultata.

Ulaz: direktorij s 15m svijećama (bars/<SYM>.json = [[ts, o, h, l, c, v], ...], GeckoTerminal) i BTC 1h (Kraken OHLC
JSON). Ništa ne čita bazu, ništa ne šalje van, ne mijenja proizvod.

    python3 ops/brzi_raspon_bt.py <data_dir>

Motor: veliki/intra.zone / signal / calm / position i rule.exit_on_bar / intra.owner_stop_bar (isti kod kao live), uz
izlaze risk-off iznimke (riskoff.py): trošak rt = 4 % (bez dodatnog slippagea), cijeli profit na cilju (full_tp),
bez vremenskog stopa, široki stop -20 % (owner_stop, BTC uži stop kad BTC padne 1,5 % u 4 h), break-even = zaključan
+1 % neto, naoružan na +5 % neto (riskoff.lock_px / be_at). Petlja je napisana ovdje (ne intra.simulate) da bi se
isti signali mogli voditi i pod portfeljnim ograničenjem "najviše 2 otvorene"; za V0 bez ograničenja provjerava se da
daje iste tradeove kao intra.simulate.
"""
import bisect
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from veliki import intra, povlacenje, rule  # noqa: E402

H, M15, DAY = 3600, 900, 86400
RT = 0.04
MIN_IZLAZ = 0.01
BE_AT = 1.05 / 1.01 - 1          # riskoff.be_at(): +5 % neto mjereno od +1 % brave
EXIT = {"time_h": None, "be_at": BE_AT, "full_tp": True, "owner_stop": True,
        "entry_slip": 0.0, "exit_slip": 0.0, "stop_slip": 0.0}
VARIANTS = {
    "V0": {"kind": "zona", "look_h": 48, "bottom": 0.25},
    "V1": {"kind": "zona", "look_h": 24, "bottom": 0.25},
    "V2": {"kind": "zona", "look_h": 12, "bottom": 0.25},
    "V3": {"kind": "zona", "look_h": 48, "bottom": 0.50},
    "V4": {"kind": "zona", "look_h": 24, "bottom": 0.40},
    "V5": {"kind": "povlacenje", "leg": 0.12, "ret": (0.40, 0.70), "min_tp": 0.07, "stop_under": 0.02, "cap": 0.12},
    "V6": {"kind": "povlacenje", "leg": 0.12, "ret": (0.30, 0.60), "min_tp": 0.07, "stop_under": 0.02, "cap": 0.12},
}


def lock_px(entry):
    return entry * (1 + MIN_IZLAZ) / (1 - RT)


def cfg_for(v):
    c = dict(EXIT)
    if v["kind"] == "zona":
        c.update(look_h=v["look_h"], bottom=v["bottom"])
        if v["look_h"] < intra.MIN_H:
            c["min_h"] = v["look_h"]
    return intra.cfg_of(c)


def zone_signal(b15, hh, hts, i, c, crash):
    """(entry_plan or None): today's rule with cfg c at the close of bar i."""
    t = b15[i][0] + M15
    z = intra.zone(hh[bisect.bisect_left(hts, t - c["look_h"] * H):bisect.bisect_right(hts, t - H)], t, c)
    st = crash.regime(t)[0] if crash is not None else None
    k = int(c["calm"])
    if intra.signal(b15[i][4], z, b15[i - k - 1:i + 1], c, st) is not None:
        return None
    e = b15[i + 1][1]
    tp = rule.tp_price(e, c["tp"], RT, z, c)
    if tp / e * (1 - RT) - 1 < 0.03:           # riskoff.target_refusal (uz 4 % uvijek prolazi: cilj je +10 % neto)
        return None
    return {"tp_px": tp, "stop_px": rule.wide_stop(e), "zone": (z["lo"], z["hi"])}


def pull_signal(b15, i, v, crash):
    """V5 / V6: povlačenje nakon skoka u zadnja 24 h. Isti kod kao demo (veliki/povlacenje.plan_at): ulaz na otvaranju
    svijeće i+1, BTC slobodan pad ovdje odbija (filtar tržišta pravog novca; live demo ga ne pita)."""
    st = crash.regime(b15[i][0] + M15)[0] if crash is not None else None
    v = {k: v[k] for k in povlacenje.V6 if k in v}
    return povlacenje.plan_at(b15, i, b15[i + 1][1], v, st)


def run_trade(b15, i, plan, c, crash):
    """Fill at bar i+1's open; walk the bars with the owner's exits. -> trade dict."""
    b = b15[i + 1]
    e = b[1]
    pos = {"entry": e, "first": e, "ts": b[0], "tp_px": plan["tp_px"], "stop_px": plan["stop_px"],
           "be_px": lock_px(e)}
    if crash is not None and rule.btc_down(crash, b[0])[0]:
        pos["wide_prev"], pos["stop_px"], pos["tight"] = pos["stop_px"], rule.tight_stop(e, None), True
    j, hit = i + 1, None
    while j < len(b15):
        if crash is not None and j > i + 1:
            intra.owner_stop_bar(pos, b15[j], crash)
        hit = rule.exit_on_bar(pos, b15[j], c)
        if hit:
            break
        j += 1
    if not hit:
        j = len(b15) - 1
        hit = ("kraj", b15[-1][4])
    r = rule.blend_ret(pos, hit[1], RT, c)
    out_ts = b15[j][0] + M15
    return {"ts": b[0], "out_ts": out_ts, "ret": r, "reason": hit[0], "hours": (out_ts - b[0]) / H, "j": j}


def signals(b15, v, crash):
    """Every bar index i where the variant would enter (ignoring position state) -> {i: plan}."""
    c = cfg_for(v)
    out = {}
    if v["kind"] == "zona":
        hh = rule.h1_from_15m(b15, None)
        hts = [x[0] for x in hh]
        for i in range(int(c["calm"]) + 1, len(b15) - 1):
            p = zone_signal(b15, hh, hts, i, c, crash)
            if p:
                out[i] = p
    else:
        for i in range(3, len(b15) - 1):
            p = pull_signal(b15, i, v, crash)
            if p:
                out[i] = p
    return out


def portfolio(data, v, crash, max_open=None):
    """All tokens in time order: one position a token, cooldown, MAX_ROUNDS a UTC day (intra.simulate's caps), and at
    most max_open positions at once across tokens (None: unlimited)."""
    c = cfg_for(v)
    sig = {s: signals(b, v, crash) for s, b in data.items()}
    ev = sorted((data[s][i][0] + M15, s, i) for s in sig for i in sig[s])
    free_at, day_n, open_until, trades = {}, {}, [], []
    for t, s, i in ev:
        if t < free_at.get(s, 0):
            continue
        d = t // DAY
        if day_n.get((s, d), 0) >= intra.MAX_ROUNDS:
            continue
        open_until = [x for x in open_until if x > t]
        if max_open is not None and len(open_until) >= max_open:
            continue
        tr = run_trade(data[s], i, sig[s][i], c, crash)
        tr["sym"] = s
        day_n[(s, d)] = day_n.get((s, d), 0) + 1
        free_at[s] = tr["out_ts"] + intra.COOLDOWN_S
        open_until.append(tr["out_ts"])
        trades.append(tr)
    return trades


def btc_days(btc):
    """{utc day: daily close change} from 1h closes; the 'bounce' set = days with >= +2 % and the day after."""
    close = {}
    for t, p in btc:
        close[t // DAY] = p          # the last hour's close of the day
    ds = sorted(close)
    chg = {d: close[d] / close[ds[k - 1]] - 1 for k, d in enumerate(ds) if k}
    up = {d for d, x in chg.items() if x >= 0.02}
    return up | {d + 1 for d in up}, chg


def boot(trades, n=2000, seed=7):
    """90 % bootstrap interval of the mean net per trade, resampling token-days."""
    g = {}
    for x in trades:
        g.setdefault((x["sym"], x["ts"] // DAY), []).append(x["ret"])
    keys = list(g)
    if len(keys) < 2:
        return None, None
    rnd = random.Random(seed)
    ms = []
    for _ in range(n):
        rs = [r for k in (rnd.choice(keys) for _ in keys) for r in g[k]]
        ms.append(sum(rs) / len(rs))
    ms.sort()
    return ms[int(0.05 * n)], ms[int(0.95 * n) - 1]


def stats(trades, days):
    if not trades:
        return {"n": 0}
    rs = [x["ret"] for x in trades]
    lo, hi = boot(trades)
    return {"n": len(rs), "per_day": len(rs) / days, "mean": statistics.mean(rs), "median": statistics.median(rs),
            "hit": sum(r > 0 for r in rs) / len(rs), "sol": sum(rs) * 0.1, "worst": min(rs),
            "hours": statistics.mean(x["hours"] for x in trades), "lo": lo, "hi": hi}


def sub(trades, f):
    rs = [x["ret"] for x in trades if f(x)]
    return (len(rs), statistics.mean(rs) if rs else None)


def main(dd):
    btc_raw = json.load(open(os.path.join(dd, "btc_kraken.json")))["result"]
    btc_raw = next(v for k, v in btc_raw.items() if k != "last")
    btc = [(int(r[0]), float(r[4])) for r in btc_raw]
    crash = rule.crash_of(btc)
    bounce, _ = btc_days(btc)
    data = {}
    for f in sorted(os.listdir(os.path.join(dd, "bars"))):
        b = [tuple(x) for x in json.load(open(os.path.join(dd, "bars", f)))]
        if len(b) >= 400:            # >= ~4 days of 15m bars
            data[f[:-5]] = b
    t0 = min(b[0][0] for b in data.values())
    t1 = max(b[-1][0] for b in data.values())
    days = (t1 - t0) / DAY
    last7 = t1 - 7 * DAY
    print(f"tokena {len(data)}: {', '.join(data)}; razdoblje {days:.1f} dana; BTC sati {len(btc)}; "
          f"BTC dani skoka+sutra {len(bounce)}")
    # sanity: V0 unconstrained == intra.simulate per token (same cfg)
    c0 = cfg_for(VARIANTS["V0"])
    n_sim = sum(len(intra.simulate(b, None, RT, 15.0, c0, crash=crash)) for b in data.values())
    print(f"provjera: intra.simulate V0 = {n_sim} tradeova (isti cfg; be_px tamo je 0 % neto, ne +1 % brava)")
    res = {}
    for name, v in VARIANTS.items():
        for lab, mo in (("bez", None), ("max2", 2)):
            tr = portfolio(data, v, crash, mo)
            s = stats(tr, days)
            if tr:
                s["btc_skok"] = sub(tr, lambda x: x["ts"] // DAY in bounce)
                s["btc_ostali"] = sub(tr, lambda x: x["ts"] // DAY not in bounce)
                s["zadnjih7"] = sub(tr, lambda x: x["ts"] >= last7)
                s["ranije"] = sub(tr, lambda x: x["ts"] < last7)
                s["razlozi"] = {r: sum(x["reason"] == r for x in tr) for r in {x["reason"] for x in tr}}
            res[(name, lab)] = s
            print(name, lab, json.dumps(s, default=str))
    json.dump({f"{k[0]}_{k[1]}": v for k, v in res.items()}, open(os.path.join(dd, "result.json"), "w"), indent=1,
              default=str)
    def pct(x):
        return "   -  " if x is None else f"{x * 100:+6.2f}"

    print("\nvar  okvir   n  /dan  srednje medijan  pog%   SOL   najgori  sati   90%[lo,hi]      BTCskok(n,sr) ostali"
          "(n,sr) zadnjih7(n,sr) ranije(n,sr)")
    for (name, lab), s in res.items():
        if not s.get("n"):
            print(f"{name}  {lab:5} 0")
            continue
        print(f"{name}  {lab:5} {s['n']:3d} {s['per_day']:5.2f} {pct(s['mean'])} {pct(s['median'])} {s['hit'] * 100:4.0f}"
              f" {s['sol']:+6.3f} {pct(s['worst'])} {s['hours']:5.1f} [{pct(s['lo'])},{pct(s['hi'])}]"
              + "".join(f"  {s[k][0]:3d},{pct(s[k][1])}" for k in ("btc_skok", "btc_ostali", "zadnjih7", "ranije")))
    v0 = res[("V0", "max2")].get("mean")
    print("\nPRESUDA (max 2 otvorene; mean > 0, donja granica 90 % > V0 mean, n >= 30):")
    for name in VARIANTS:
        s = res[(name, "max2")]
        ok = s.get("n", 0) >= 30 and s["mean"] > 0 and s["lo"] is not None and v0 is not None and s["lo"] > v0
        print(name, "BOLJE I UPOTREBLJIVO" if ok else "nije dokazano")


if __name__ == "__main__":
    main(sys.argv[1])
