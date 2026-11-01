"""Daily review of the paper trades: what went wrong, what the filters cost or saved, and which changes
would have done better. Every number comes from replaying stored price ticks with paper/sim.py.

A change is only suggested when it has at least MIN_N trades behind it and beats the current setting on
both the older and the newer half of the data (a cheap guard against fitting yesterday's noise).
"""
import itertools
import json
import os
import time

from hype import evaluate

from . import dca, sim

MIN_N = 10
LEARN_DAYS = 14
BIG = 1.0  # max return that counts as a winner (2x)


def _mc(x):
    if not x:
        return "?"
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if x >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:.0f}"


def _feat(k):
    try:
        from ui.labels import feat_low
        return feat_low(k)
    except Exception:
        return k


def _lab(name, k):
    try:
        from ui import labels
        return getattr(labels, name)(k)
    except Exception:
        return k


def _reason(k):
    return _lab("reason", k)


def _decision(k):
    return _lab("decision", k)


def _source(k):
    return _lab("source", k)


def _exit(k):
    try:
        from ui.labels import exit_reason
        return exit_reason(k)
    except Exception:
        return k


def _cfg_change(ch):
    try:
        from ui.labels import cfg_change
        return cfg_change(ch)
    except Exception:
        return ", ".join(f"{k} {v}" for k, v in ch.items())


def _pct(x):
    return f"{x:+.0%}" if x is not None else "?"


def load(con, cfg, since):
    """Every tracked candidate since `since` with its replayed outcome under cfg."""
    rows = []
    for (token, sym, ts, origin, sources, score, feats, price, liq, mcap, decision, reason, verdict, rscore,
         flags, trade_id, url) in con.execute("SELECT * FROM candidates WHERE first_ts>=? AND decision!='ignored' "
                                              "AND price>0 AND liquidity>0", (since,)):
        path = con.execute("SELECT ts, price, liquidity FROM ticks WHERE token=? AND ts>? AND ts<=? ORDER BY ts",
                           (token, ts, ts + cfg["track_h"] * 3600)).fetchall()
        prices = [p for _, p, _ in path if p]
        last_liq = path[-1][2] if path else liq
        rugged = bool(path) and ((last_liq or 0) < cfg["rug_liq"] * (liq or 0) or not path[-1][1])
        rows.append({"token": token, "symbol": sym, "ts": ts, "origin": origin, "url": url,
                     "sources": [s for s in (sources or "").split(",") if s], "score": score or 0,
                     "features": json.loads(feats or "{}"), "price": price, "liquidity": liq, "mcap": mcap,
                     "decision": decision, "reason": reason, "verdict": verdict, "rug_score": rscore,
                     "flags": json.loads(flags or "[]"), "trade_id": trade_id, "path": path,
                     "done": bool(path) and path[-1][0] - ts >= cfg["track_h"] * 3600 * 0.9,
                     "raw_max": max(prices) / price - 1 if prices else 0.0, "rugged": rugged})
    for r in rows:
        r["sim"] = sim.replay(r["price"], r["liquidity"], r["ts"], r["path"], cfg) if r["path"] else None
    return [r for r in rows if r["sim"]]


def would_take(r, cfg):
    need = cfg["dex_min_score"] if r["origin"] == "event" else cfg["min_score"]
    return (r["score"] >= need and r["liquidity"] >= cfg["min_liq"] and r["mcap"] <= cfg["max_mcap"]
            and r["verdict"] not in cfg["block_verdicts"])


def pnl(rows, cfg):
    res = [sim.replay(r["price"], r["liquidity"], r["ts"], r["path"], cfg) for r in rows]
    if not res:
        return {"n": 0, "pnl": 0.0, "win": 0.0, "avg": 0.0}
    return {"n": len(res), "pnl": round(sum(x["pnl_usd"] for x in res), 2),
            "win": round(sum(x["ret"] > 0 for x in res) / len(res), 2),
            "avg": round(sum(x["ret"] for x in res) / len(res), 3)}


def _halves(rows, cut):
    return [r for r in rows if r["ts"] < cut], [r for r in rows if r["ts"] >= cut]


def _robust(rows_fn, cfg_now, cfg_new):
    """New setting must beat the current one overall and on both time halves."""
    rows_now, rows_new = rows_fn(cfg_now), rows_fn(cfg_new)
    a, b = pnl(rows_now, cfg_now), pnl(rows_new, cfg_new)
    if b["n"] < MIN_N or b["pnl"] <= a["pnl"]:
        return None
    ts = sorted(r["ts"] for r in rows_now + rows_new)
    cut = ts[len(ts) // 2]  # same calendar split for both, or the halves would hold different days
    for h_now, h_new in zip(_halves(rows_now, cut), _halves(rows_new, cut)):
        if pnl(h_new, cfg_new)["pnl"] < pnl(h_now, cfg_now)["pnl"]:
            return None
    return a, b


def mistakes(trades, cands_by_trade):
    out = []
    for t in trades:
        c = cands_by_trade.get(t["id"], {})
        top = ", ".join(_feat(k) for k, v in sorted(c.get("features", {}).items(), key=lambda kv: -kv[1])[:3] if v >= 0.5)
        tag = f"{t['symbol']} (#{t['id']}, MC {_mc(t.get('entry_mcap'))} -> {_mc(t.get('exit_mcap'))})"
        rug = c.get("verdict") or "nije provjeren"
        if t["exit_reason"] == "rug":
            out.append({"kind": "rug", "text": f"{tag}: rug, {_pct(t['ret'])}. Rug filter: {rug}. Jaki signali: {top or '-'}."})
        elif t["exit_reason"] == "stop_loss" and (t["max_ret"] or 0) < 0.15:
            late = c.get("features", {}).get("momentum", 0) >= 0.5
            out.append({"kind": "late_entry" if late else "bad_entry",
                        "text": f"{tag}: stop loss {_pct(t['ret'])}, nikad iznad {_pct(t['max_ret'])}. "
                                + ("Kupljen nakon velikog skoka u zadnjem satu (momentum), kupili smo vrh. " if late else "")
                                + f"Jaki signali: {top or '-'}; rug filter: {rug}."})
        elif (t["max_ret"] or 0) >= 0.5 and (t["ret"] or 0) <= 0.05:
            out.append({"kind": "gave_back", "text": f"{tag}: bio {_pct(t['max_ret'])}, zatvoren {_pct(t['ret'])} "
                                                     f"({_exit(t['exit_reason'])}). Profit vraćen."})
        elif t["exit_reason"] == "time" and abs(t["ret"] or 0) < 0.1:
            out.append({"kind": "dead", "text": f"{tag}: ništa se nije dogodilo u {t['hold_h']:.0f} h ({_pct(t['ret'])})."})
    return out


def scoreboard(rows, key):
    groups = {}
    for r in rows:
        for k in key(r):
            groups.setdefault(k, []).append(r)
    out = []
    for k, g in groups.items():
        out.append({"key": k, "n": len(g), "avg_ret": round(sum(r["sim"]["ret"] for r in g) / len(g), 3),
                    "pnl_if_all": round(sum(r["sim"]["pnl_usd"] for r in g), 2),
                    "winners": sum(r["raw_max"] >= BIG for r in g), "rug_rate": round(sum(r["rugged"] for r in g) / len(g), 2)})
    return sorted(out, key=lambda x: -x["n"])


def suggest(learn, cfg):
    sugg, new = [], dict(cfg)

    # 1. entry threshold
    hype_rows = [r for r in learn if r["origin"] == "hype"]
    grid = range(int(cfg["shadow_min_score"] // 5 * 5), 90, 5)
    best = None
    for th in grid:
        c2 = {**cfg, "min_score": th}
        res = _robust(lambda c: [r for r in hype_rows if would_take(r, c)], cfg, c2)
        if res and (best is None or res[1]["pnl"] > best[2]["pnl"]):
            best = (th, res[0], res[1])
    if best and best[0] != cfg["min_score"]:
        new["min_score"] = best[0]
        sugg.append({"change": {"min_score": best[0]}, "n": best[2]["n"],
                     "text": f"Najmanja ocjena za ulaz {cfg['min_score']} → {best[0]}: na {best[2]['n']} tokena demo "
                             f"rezultat {best[1]['pnl']:+.0f} → {best[2]['pnl']:+.0f} USD, pogodak {best[2]['win']:.0%}."})

    # 2. exits, on what the (possibly new) entry rules would take
    taken = [r for r in learn if would_take(r, new)]
    if len(taken) >= MIN_N:
        base = pnl(taken, new)
        best = None
        for sl_, tp1, tr, hold in itertools.product([-0.2, -0.3, -0.35, -0.5], [0.5, 1.0, 2.0], [0.2, 0.3, 0.4],
                                                    [6, 12, 24]):
            c2 = {**new, "sl": sl_, "tp": [[tp1, 0.5]] + [x for x in new["tp"][1:] if x[0] > tp1],
                  "trail": tr, "max_hold_h": min(hold, new["track_h"])}
            res = _robust(lambda c: taken, new, c2)
            if res and (best is None or res[1]["pnl"] > best[1]["pnl"]):
                best = (c2, res[1])
        if best and best[1]["pnl"] > base["pnl"] + max(5, abs(base["pnl"]) * 0.1):
            ch = {k: best[0][k] for k in ("sl", "tp", "trail", "max_hold_h") if best[0][k] != new[k]}
            new.update(ch)
            sugg.append({"change": ch, "n": best[1]["n"],
                         "text": f"Drugačiji izlazi ({_cfg_change(ch)}): demo rezultat {base['pnl']:+.0f} → "
                                 f"{best[1]['pnl']:+.0f} USD na {best[1]['n']} tokena."})

    # 3. rug filter verdicts
    for v in scoreboard([r for r in learn if r["verdict"]], lambda r: [r["verdict"]]):
        if v["key"] not in new["block_verdicts"] and v["n"] >= 5 and v["rug_rate"] >= 0.5:
            new["block_verdicts"] = new["block_verdicts"] + [v["key"]]
            sugg.append({"change": {"block_verdicts": new["block_verdicts"]}, "n": v["n"],
                         "text": f"Ne kupovati ni tokene s rug presudom „{v['key']}”: {v['rug_rate']:.0%} od {v['n']} "
                                 "takvih je rugalo."})
        if v["key"] in new["block_verdicts"] and v["n"] >= 8 and v["rug_rate"] < 0.2 and v["avg_ret"] > 0.1:
            sugg.append({"change": {}, "text": f"Rug filter je prestrog za '{v['key']}': od {v['n']} blokiranih rugalo "
                                               f"je samo {v['rug_rate']:.0%}, prosjek da smo ušli {_pct(v['avg_ret'])}. "
                                               "Najčešći lažni alarmi su popisani u izvještaju."})

    # 4. liquidity floor
    for lo in (5000, 20000, 30000):
        c2 = {**new, "min_liq": lo}
        res = _robust(lambda c: [r for r in learn if would_take(r, c)], new, c2)
        if res:
            new["min_liq"] = lo
            sugg.append({"change": {"min_liq": lo}, "n": res[1]["n"],
                         "text": f"Najmanja likvidnost ${cfg['min_liq']:,.0f} → ${lo:,}: demo rezultat "
                                 f"{res[0]['pnl']:+.0f} → {res[1]['pnl']:+.0f} USD na {res[1]['n']} tokena."})
            break
    return sugg, new


def dca_verdict(rows):
    """Judge the DCA rule only on closed trades, same two-halves guard as the other suggestions."""
    done = sorted([r for r in rows if r["done"]], key=lambda r: r["ts"])
    if len(done) < MIN_N:
        return None
    halves = [done[:len(done) // 2], done[len(done) // 2:]]
    avg = [sum(r["ret_to_exit"] for r in h) / len(h) for h in halves]
    s = dca.summary(done)
    if min(avg) > 0.05:
        return (f"DCA signal se isplatio: {s['closed']} signala, dokup bi u prosjeku dao {_pct(s['avg'])} do izlaza "
                f"({s['pnl']:+.0f} USD), pozitivno u obje polovice podataka. Bot ga i dalje samo bilježi; vrijedi ga uključiti u demo.")
    if max(avg) < 0:
        return (f"DCA signal gubi: {s['closed']} signala, dokup bi u prosjeku dao {_pct(s['avg'])} ({s['pnl']:+.0f} USD), "
                f"rug {s['rug']:.0%}. Kupnja u padu se po ovim pravilima ne isplati; bot je zato samo bilježi, ne izvršava.")
    return None


def run(con, cfg, hours=24, now=None):
    now = now or time.time()
    since = now - hours * 3600
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    cols = ["id", "token", "symbol", "opened_ts", "closed_ts", "status", "exit_reason", "size_usd", "ret",
            "pnl_usd", "max_ret", "min_ret", "entry_mcap", "exit_mcap"]
    trades = [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {','.join(cols)} FROM trades WHERE status='closed' AND closed_ts>=?", (since,))]
    for t in trades:
        t["hold_h"] = ((t["closed_ts"] or now) - t["opened_ts"]) / 3600
    open_n = con.execute("SELECT COUNT(*), COALESCE(SUM(pnl_usd),0) FROM trades WHERE status='open'").fetchone()
    learn = load(con, cfg, now - LEARN_DAYS * 86400)
    today = [r for r in learn if r["ts"] >= since - cfg["track_h"] * 3600]
    by_trade = {r["trade_id"]: r for r in learn if r["trade_id"]}
    skipped = [r for r in today if r["decision"].startswith("skip")]
    missed = sorted([r for r in skipped if r["sim"]["ret"] >= 0.5 or r["raw_max"] >= BIG],
                    key=lambda r: -r["raw_max"])
    saved = [r for r in skipped if r["rugged"] or r["sim"]["ret"] <= -0.3]
    rug_fp = {}
    for r in learn:
        if r["decision"] == "skip_rug" and not r["rugged"] and r["sim"]["ret"] > 0.3:
            for f in r["flags"]:
                rug_fp[f.split(":")[0][:60]] = rug_fp.get(f.split(":")[0][:60], 0) + 1
    hit_rows = [{**r, "hit": r["raw_max"] >= BIG} for r in learn if r["origin"] == "hype" and r["features"]]
    lift = evaluate.feature_lift(hit_rows) if hit_rows else []
    fit = evaluate.fit_weights(hit_rows)
    sugg, new_cfg = suggest(learn, cfg)
    dca_rows = [r for r in dca.outcomes(con, cfg["fee"], now) if r["ts"] >= now - LEARN_DAYS * 86400]
    dca_sum = dca.summary(dca_rows)
    dca_note = dca_verdict(dca_rows)
    if dca_note:
        sugg.append({"change": {}, "text": dca_note})
    n = len(trades)
    return {
        "day": day, "hours": hours, "generated": int(now),
        "summary": {"closed": n, "pnl_usd": round(sum(t["pnl_usd"] or 0 for t in trades), 2),
                    "win_rate": round(sum((t["ret"] or 0) > 0 for t in trades) / n, 2) if n else None,
                    "avg_ret": round(sum(t["ret"] or 0 for t in trades) / n, 3) if n else None,
                    "open": open_n[0], "open_pnl": round(open_n[1], 2),
                    "by_exit": {k: sum(t["exit_reason"] == k for t in trades) for k in {t["exit_reason"] for t in trades}},
                    "best": max(trades, key=lambda t: t["pnl_usd"] or 0, default=None),
                    "worst": min(trades, key=lambda t: t["pnl_usd"] or 0, default=None)},
        "mistakes": mistakes(trades, by_trade),
        "missed": [{"symbol": r["symbol"], "token": r["token"], "decision": r["decision"], "reason": r["reason"],
                    "raw_max": round(r["raw_max"], 2), "sim_ret": r["sim"]["ret"], "url": r["url"]} for r in missed[:10]],
        "saved": len(saved), "saved_pnl": round(sum(r["sim"]["pnl_usd"] for r in saved), 2),
        "filters": scoreboard(skipped + [r for r in today if r["decision"] == "taken"], lambda r: [r["decision"]]),
        "verdicts": scoreboard([r for r in learn if r["verdict"]], lambda r: [r["verdict"]]),
        "sources": scoreboard([r for r in learn if would_take(r, cfg) or r["decision"] == "taken"], lambda r: r["sources"]),
        "rug_false_alarms": sorted(rug_fp.items(), key=lambda kv: -kv[1])[:8],
        "lift": sorted([x for x in lift if x["lift"] is not None], key=lambda x: -x["lift"]),
        "learn_n": len(learn), "learn_done": sum(r["done"] for r in learn),
        "dca": {"summary": dca_sum, "signals": dca_rows[-20:]},
        "suggestions": sugg, "suggested_config": new_cfg, "weights": fit["weights"] if fit else None,
        "weights_n": fit["n"] if fit else 0,
    }


def to_md(rep, cfg):
    s, e = rep["summary"], rep.get("equity") or {}
    L = [f"# Demo trading, dnevni pregled {rep['day']}", ""]
    if e:
        L.append(f"Demo račun **${e['equity']:.2f}** (start ${e['bankroll']:.0f}, ostvareno {e['realized']:+.2f}, "
                 f"otvoreno {e['unrealized']:+.2f} USD).")
    if s["closed"]:
        L.append(f"Zadnja {rep['hours']:.0f} h: zatvoreno {s['closed']} trejdova, PnL **{s['pnl_usd']:+.2f} USD**, "
                 f"pogodak {s['win_rate']:.0%}, prosjek {_pct(s['avg_ret'])}. Izlazi: {', '.join(f'{_exit(k)} {v}' for k, v in s['by_exit'].items())}.")
        L.append(f"Najbolji {s['best']['symbol']} {s['best']['pnl_usd']:+.2f} USD (MC {_mc(s['best'].get('entry_mcap'))} -> "
                 f"{_mc(s['best'].get('exit_mcap'))}), najgori {s['worst']['symbol']} {s['worst']['pnl_usd']:+.2f} USD "
                 f"(MC {_mc(s['worst'].get('entry_mcap'))} -> {_mc(s['worst'].get('exit_mcap'))}).")
    else:
        L.append(f"Zadnja {rep['hours']:.0f} h: nema zatvorenih trejdova.")
    L.append(f"Otvoreno sada: {s['open']} ({s['open_pnl']:+.2f} USD). Podaci za učenje: {rep['learn_n']} tokena, "
             f"od toga {rep['learn_done']} s punim praćenjem od {cfg['track_h']} h.")
    L += ["", "## Što je bot naučio i promijenio", ""]
    auto = rep.get("auto")
    if auto:
        L += [f"- {x['text']}" for x in auto]
    if rep["suggestions"]:
        L += [f"- Opažanje: {x['text']}" for x in rep["suggestions"] if not x.get("change")]
        if auto is None:  # review run on its own (test, manual): changes it would make
            L += [f"- Moguća promjena: {x['text']}" for x in rep["suggestions"] if x.get("change")]
    if rep.get("weights_n"):
        L.append(f"- Težine hype ocjene bot sam ažurira jednom dnevno po klasi tokena, uz zaštite (stranica Učenje); "
                 f"danas je usporedba napravljena na {rep['weights_n']} tokena.")
    if not auto and not rep["suggestions"] and not rep.get("weights_n"):
        L.append(f"Nijedna promjena nije dovoljno sigurna (treba barem {MIN_N} tokena i bolji rezultat u obje "
                 "polovice podataka). Ostavljam postavke kako jesu.")
    d = rep.get("dca") or {}
    ds = d.get("summary") or {}
    if ds.get("n"):
        L += ["", "## DCA prijedlozi (kupnja u padu, samo zapis, ne izvršava se)", ""]
        if ds.get("closed"):
            L.append(f"{ds['n']} signala, {ds['closed']} s zatvorenim trejdom: dokup bi dao prosječno {_pct(ds['avg'])}, "
                     f"pogodak {ds['win']:.0%}, ukupno {ds['pnl']:+.2f} USD, rug {ds['rug']:.0%}.")
        L += [f"- {x['symbol']}: {x['reason']}; MC {_mc(x['mcap'])}, do izlaza {_pct(x['ret_to_exit'])}"
              + ("" if x["done"] else " (još otvoreno)") for x in d.get("signals", [])[-8:]]
    L += ["", "## Greške", ""]
    L += [f"- {m['text']}" for m in rep["mistakes"]] or ["- Nema zabilježenih grešaka."]
    L += ["", "## Propušteni pobjednici", ""]
    if rep["missed"]:
        L += [f"- {m['symbol']}: max {_pct(m['raw_max'])}, naša strategija bi dala {_pct(m['sim_ret'])}. "
              f"Preskočen jer: {_reason(m['reason'])}. {m['url'] or ''}" for m in rep["missed"]]
    else:
        L.append("- Nijedan preskočeni token nije napravio 2x.")
    L.append(f"\nFilteri su izbjegli {rep['saved']} loših tokena (da smo ušli u sve: {rep['saved_pnl']:+.2f} USD).")
    L += ["", "## Filteri (zadnja 24 h)", "", "| Odluka | n | prosjek da smo ušli | PnL da smo ušli | 2x+ | rug |",
          "| --- | --- | --- | --- | --- | --- |"]
    L += [f"| {_decision(f['key'])} | {f['n']} | {_pct(f['avg_ret'])} | {f['pnl_if_all']:+.2f} | {f['winners']} | {f['rug_rate']:.0%} |"
          for f in rep["filters"]]
    if rep["verdicts"]:
        L += ["", "## Rug filter: presuda vs. ishod (14 dana)", "", "| Presuda | n | rugalo | prosjek |", "| --- | --- | --- | --- |"]
        L += [f"| {v['key']} | {v['n']} | {v['rug_rate']:.0%} | {_pct(v['avg_ret'])} |" for v in rep["verdicts"]]
    if rep["rug_false_alarms"]:
        L += ["", "Pravila rug filtera koja su blokirala tokene koji nisu rugali i porasli su 30%+ (lažni alarmi):"]
        L += [f"- {k}: {n}x" for k, n in rep["rug_false_alarms"]]
    if rep["sources"]:
        L += ["", "## Izvori signala (14 dana, tokeni koje bismo uzeli)", "", "| Izvor | n | prosjek | 2x+ | rug |",
              "| --- | --- | --- | --- | --- |"]
        L += [f"| {_source(x['key'])} | {x['n']} | {_pct(x['avg_ret'])} | {x['winners']} | {x['rug_rate']:.0%} |"
              for x in rep["sources"][:12]]
    if rep["lift"]:
        L += ["", "## Koji signali pomažu (iznad 1 = kad je signal jak, 2x dolazi češće)", ""]
        L += [f"- {_feat(x['feature'])}: {x['lift']} puta češće (jak u {x['n_strong']} tokena)" for x in rep["lift"]]
    return "\n".join(L) + "\n"


def write(rep, out_dir, suggested_path, cfg):
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"review-{rep['day']}")
    md = to_md(rep, cfg)
    with open(base + ".md", "w") as f:
        f.write(md)
    with open(base + ".json", "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False, default=str)
    with open(suggested_path, "w") as f:
        json.dump(rep["suggested_config"], f, indent=1, ensure_ascii=False)
    with open(os.path.join(out_dir, "lessons.md"), "a") as f:  # running log of what was learned, day by day
        f.write(f"\n## {rep['day']}\n" + "".join(f"- {m['text']}\n" for m in rep["mistakes"][:5])
                + "".join(f"- {x['text']}\n" for x in rep.get("auto") or []))
    return {"md": base + ".md", "json": base + ".json"}


def telegram_summary(rep):
    s, e = rep["summary"], rep.get("equity") or {}
    lines = [f"📊 Demo pregled {rep['day']}: račun ${e.get('equity', 0):.2f}, 24 h PnL {s['pnl_usd']:+.2f} USD "
             f"({s['closed']} trejdova" + (f", pogodak {s['win_rate']:.0%})" if s["closed"] else ")")]
    lines += [f"⚠️ {m['text']}" for m in rep["mistakes"][:3]]
    lines += [f"👀 Propušten {m['symbol']} max {_pct(m['raw_max'])} ({m['reason']})" for m in rep["missed"][:2]]
    lines += [f"💡 {x['text']}" for x in (rep.get("auto") or [])[:3]] or ["💡 Bez promjena danas."]
    return "\n".join(lines)
