"""The fast path's day (Zagreb), written at 23:30 by the worker (fast.db reports + the log) and as rows of
events/evreport's EV table:

  decisions     how many BUY_PAPER / BUY_LIVE / SKIP / CHECK_FAILED, the latency from the wallet's buy (or the call)
                to the decision: median, p90, the share under 10 s
  per check     how often each check (a-e, and "ev" = the EV rule, "proof" never rejects) rejected a signal (it was the
                first failing check of a SKIP), how many of those did >= +20 % within 60 min afterwards (false
                rejects, "propušteno") and how many would have lost (-10 % before +15 %: saved a loss); the check that
                most often rejects wrongly is named
  buys          the measured outcome of the BUY decisions (TP before SL share, the mean of the exits' rough result:
                +15 % hit, else the 60-min move capped at -10 %, after the cost), the demo account's closed fast trades
  cost          one line "fast_check trošak (dan): ..." per source: calls and Helius credits, and how many decisions
                and trades that day had (CLAUDE.md: cost per source and what it brought)
"""
import json
import statistics
import time

from . import store

MISS_PCT = 20.0


def _bounds(day):
    import datetime as dt
    from zoneinfo import ZoneInfo
    z = ZoneInfo(store.TZ)
    d = dt.date.fromisoformat(day)
    t0 = dt.datetime(d.year, d.month, d.day, tzinfo=z).timestamp()
    return t0, t0 + 86400


def daily(now=None, path=None, con=None, day=None):
    """The report of one Zagreb day (today by default); stored in fast.db reports when a connection is given."""
    now = int(now or time.time())
    day = day or store.day_of(now)
    own = con is None
    if own:
        con = store.ro(path)
        if con is None:
            return {"day": day, "n": 0, "decisions": {}, "per_check": {}, "costs": {}, "latency": {}, "buys": {}}
    try:
        rows = [r for r in store.read(con, "decided_ts >= ? AND decided_ts < ?", _bounds(day), order="id", limit=100_000)]
        costs = store.costs(con, day)
    finally:
        if own:
            con.close()
    dec = {}
    for r in rows:
        dec[r["decision"]] = dec.get(r["decision"], 0) + 1
    lat = sorted(r["latency_s"] for r in rows if r["latency_s"] is not None and r["decision"] != "CHECK_FAILED")
    latency = {"n": len(lat), "median_s": round(statistics.median(lat), 2) if lat else None,
               "p90_s": round(lat[min(len(lat) - 1, int(len(lat) * 0.9))], 2) if lat else None,
               "under_10s": round(sum(1 for x in lat if x < 10) / len(lat), 3) if lat else None}
    per = {}
    for r in rows:
        if r["decision"] != "SKIP":
            continue
        key = (r.get("checks") or {}).get("key") or "?"
        p = per.setdefault(key, {"rejected": 0, "measured": 0, "false_reject": 0, "saved": 0, "examples": []})
        p["rejected"] += 1
        o = r.get("out") or {}
        if r.get("out_done") and o.get("max60") is not None:
            p["measured"] += 1
            if (r.get("max60") or 0) >= MISS_PCT:
                p["false_reject"] += 1
                if len(p["examples"]) < 3:
                    p["examples"].append(f"{r.get('symbol') or r['token'][:6]} ({r.get('source_label')}): "
                                         f"{(r.get('reason') or '')[:80]} → max +{r['max60']:.0f} %")
            elif r.get("hit") == 0 and (o.get("min60") or 0) <= -10:
                p["saved"] += 1
    worst = max(per.items(), key=lambda kv: (kv[1]["false_reject"], kv[1]["rejected"]), default=(None, None))
    buys = [r for r in rows if r["decision"] in ("BUY_PAPER", "BUY_LIVE") and r.get("out_done")]
    res = []
    for r in buys:
        o = r.get("out") or {}
        if r.get("hit") == 1:
            g = 15.0
        else:
            g = max(-10.0, o.get("60m") if o.get("60m") is not None else (o.get("min60") or 0))
        res.append(g - (r.get("cost_pct") or 0))
    bought = {"n": sum(1 for r in rows if r["decision"] in ("BUY_PAPER", "BUY_LIVE")), "measured": len(buys),
              "hit_rate": round(sum(1 for r in buys if r.get("hit") == 1) / len(buys), 3) if buys else None,
              "ev_pct": round(sum(res) / len(res), 2) if res else None,
              "traded": sum(1 for r in rows if (r.get("traded") or {}).get("trade_id"))}
    try:
        from . import paper
        bought["paper"] = paper.proof()
    except Exception:  # noqa: BLE001
        bought["paper"] = None
    rep = {"day": day, "ts": now, "n": len(rows), "decisions": dec, "latency": latency, "per_check": per,
           "worst_check": worst[0] if worst[1] and worst[1]["false_reject"] else None, "buys": bought, "costs": costs,
           "missed": sum(1 for r in rows if r.get("missed"))}
    if not own:
        con.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (day, now, json.dumps(rep, ensure_ascii=False)))
    return rep


NAMES = {"rug": "rug", "holders": "holderi", "flow": "tok", "price": "cijena", "source": "izvor", "ev": "EV",
         "explore": "istraživanje"}


def _c(x, nd=1):
    return "–" if x is None else f"{x:.{nd}f}".replace(".", ",")


def cost_line(rep):
    c = rep.get("costs") or {}

    def part(k, label, free=True):
        v = c.get(k) or {}
        if not v:
            return None
        return f"{label} {v['calls']} poziva" + (" (besplatno)" if free else f", {_c(v['credits'], 0)} kredita")
    parts = [p for p in (part("helius", "Helius", False), part("rugcheck", "RugCheck"),
                         part("dexscreener", "DexScreener"), part("dexscreener_ishodi", "DexScreener ishodi")) if p]
    b = rep.get("buys") or {}
    return (f"fast_check trošak (dan): {rep['day']} · " + ("; ".join(parts) if parts else "nema poziva")
            + f"; donijelo {rep['n']} odluka, {b.get('n', 0)} BUY, {b.get('traded', 0)} tradeova")


def lines(rep):
    d = rep.get("decisions") or {}
    lat = rep.get("latency") or {}
    out = [f"fast_check (dan {rep['day']}): {rep['n']} odluka (" + ", ".join(f"{k} {v}" for k, v in sorted(d.items()))
           + f"), latencija medijan {_c(lat.get('median_s'))} s, p90 {_c(lat.get('p90_s'))} s, ispod 10 s "
           + (f"{lat['under_10s']:.0%}" if lat.get("under_10s") is not None else "–")
           + f"; propušteno (SKIP pa +20 % u 60 min): {rep.get('missed', 0)}"]
    per = rep.get("per_check") or {}
    if per:
        out.append("fast_check odbijanja po provjeri: " + "; ".join(
            f"{NAMES.get(k, k)} {v['rejected']} (krivo {v['false_reject']}, spašen gubitak {v['saved']}, izmjereno "
            f"{v['measured']})" for k, v in sorted(per.items(), key=lambda kv: -kv[1]["rejected"])))
        w = rep.get("worst_check")
        if w:
            ex = (per[w].get("examples") or [])[:2]
            out.append(f"fast_check najčešće krivo odbija: {NAMES.get(w, w)} ({per[w]['false_reject']} od "
                       f"{per[w]['rejected']})" + (f", npr. {'; '.join(ex)}" if ex else ""))
    b = rep.get("buys") or {}
    if b.get("n"):
        pp = b.get("paper") or {}
        out.append(f"fast_check BUY: {b['n']}, izmjereno {b['measured']}, TP prije SL-a "
                   + (f"{b['hit_rate']:.0%}" if b.get("hit_rate") is not None else "–")
                   + f", grubi EV {_c(b.get('ev_pct'))} %; demo zatvorenih {pp.get('n', 0)}, EV {_c(pp.get('ev_pct'))} %")
    out.append(cost_line(rep))
    return out


def ev_rows(now, mode, path=None, log=print):
    """events/evreport: today's report as rows of the EV table (BUY outcomes, and each check's rejections). The lines
    themselves are logged once, by the worker at 23:30 (not again here)."""
    rep = daily(now, path)
    rows = []
    b = rep.get("buys") or {}
    if b.get("n"):
        rows.append({"flag": "fast_path", "phase": mode, "part": "fast:BUY", "n": b["n"], "n_outcomes": b["measured"],
                     "hit_rate": b.get("hit_rate"), "avg_pnl_pct": b.get("ev_pct"), "ev_pct": b.get("ev_pct"),
                     "max_dd_pct": None, "baseline_ev_pct": None, "baseline_n": None, "delta_ev_pct": None,
                     "note": cost_line(rep), "proposal": None})
    for k, v in (rep.get("per_check") or {}).items():
        rows.append({"flag": "fast_path", "phase": mode, "part": f"fast:odbio {NAMES.get(k, k)}", "n": v["rejected"],
                     "n_outcomes": v["measured"],
                     "hit_rate": round(v["false_reject"] / v["measured"], 3) if v["measured"] else None,
                     "avg_pnl_pct": None, "ev_pct": None, "max_dd_pct": None, "baseline_ev_pct": None,
                     "baseline_n": None, "delta_ev_pct": None,
                     "note": f"krivo odbijeno (+20 % u 60 min) {v['false_reject']}, spašen gubitak {v['saved']}",
                     "proposal": None})
    return rows
