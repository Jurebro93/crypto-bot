"""The passes of Insajderi 2.0 (run_insajderi.py).

  once    ~10 min after a deploy (start.sh, under ops.heavy, nice): the existing data first (no Helius for what our
          databases already hold), Helius for at most deploy_share (40 %) of the day's cap
  night   01-06 Zagreb (ops.heavy --night), at most once in night_gap_h: the rest of the day's cap
  incr    every 3 h, light: new events of the last 2 days, Helius at most incr_share (10 %) of the cap, the groups
          (the demo's watched set), catalysts and the trending log; the walk-forwards keep the last full pass's numbers
  report  the reports and the log line only

Each pass ends with the log line (report.line) and output/insajderi.md + output/pametni_novac.md. Everything runs
under the owner switch fokus_midcap as an explicit, budgeted exception (ops/fokus.EXCEPTIONS).
"""
import json
import time

from insajderi import chain, copy, events as ev, score, store


def _log(log, msg):
    log(store.PREFIX + msg)


def run(kind="once", now=None, cfg=None, credits=None, fetch=None, log=print, **over):
    """One pass. Returns the summary dict (also stored as i2_kv summary)."""
    now = int(now or time.time())
    c = store.config(cfg)
    p = store.paths(**over)
    con = store.connect(p.get("insajderi_db"))
    try:
        if kind == "night":
            last = int(float(store.kv(con, "night_last") or 0))
            if now - last < float(c["night_gap_h"]) * 3600:
                _log(log, f"noćni prolaz već odrađen prije {(now - last) / 3600:.1f} h, preskačem")
                return json.loads(store.kv(con, "summary") or "{}")
        if kind == "once" and credits is None:   # a deploy a few times a day must not redo it (nor eat the cap)
            last = max(int(float(store.kv(con, "once_last") or 0)), int(float(store.kv(con, "night_last") or 0)))
            if now - last < float(c["once_gap_h"]) * 3600:
                _log(log, f"prolaz nakon deploya već odrađen prije {(now - last) / 3600:.1f} h, preskačem")
                return json.loads(store.kv(con, "summary") or "{}")
        since = now - (2 * 86400 if kind == "incr" else int(c["days"]) * 86400)
        if kind != "report":
            calls = ev.call_events(p, c, now, since)
            jumps = ev.market_events(p, c, now, max(since, now - int(c["mkt_days"]) * 86400))
            new = ev.save(con, ev.merge(calls, jumps), now)
            evs = ev.load(con, now - int(c["days"]) * 86400)
            todo = [e for e in evs if e["t0"] >= since or not e.get("n_part")]
            chain.build(con, p, c, todo)
            cap, how = store.helius_cap(c, now, p.get("usage_db"))
            left = store.helius_left(con, c, now, p.get("usage_db"))
            if credits is not None:
                budget = min(int(credits), left)
            elif kind == "once":
                budget = min(left, int(cap * float(c["deploy_share"])))
            elif kind == "night":
                budget = left
            else:   # incr: a small share of the cap for the new calls
                budget = min(left, int(cap * float(c["incr_share"])))
            n_f, spent = (0, 0)
            if budget > 0:
                evs = ev.load(con, now - int(c["days"]) * 86400)
                n_f, spent = chain.fetch_due(con, p, c, evs, now, budget, fetch=fetch, log=log)
                if n_f:
                    chain.build(con, p, c, [e for e in ev.load(con, now - int(c["days"]) * 86400) if e.get("fetched")])
            con.execute("INSERT INTO i2_runs VALUES (?,?,?,?)",
                        (now, kind, spent, json.dumps({"new_events": new, "fetched": n_f, "budget": budget, "cap": cap,
                                                       "cap_how": how})))
            con.commit()
            _log(log, f"Helius {spent:,} kr. ({n_f} događaja), danas {store.helius_spent(con, now):,} od {cap:,} "
                      f"({how})")
        summary = analyze(con, p, c, now, log=log, light=(kind == "incr"))
        if kind in ("night", "once"):
            store.kv(con, f"{kind}_last", now)
            con.commit()
        try:
            from insajderi import report
            report.write(summary)
        except Exception as e:  # noqa: BLE001 - the report never breaks the pass
            _log(log, f"izvještaj nije napisan ({type(e).__name__}: {e})")
        try:
            from insajderi import report
            for line in report.lines(summary):
                log(line)
        except Exception as e:  # noqa: BLE001
            _log(log, f"log linija ({type(e).__name__}: {e})")
        return summary
    finally:
        con.close()


def analyze(con, p, c, now, log=print, light=False):
    """Owners, classification, catalysts, the copy walk-forward, trending and smart money -> the summary. light: the
    walk-forwards (copy, smart money, trending score) keep the last full pass's numbers."""
    evs = ev.load(con, now - int(c["days"]) * 86400)
    own, relay = chain.assign_owners(con, p, c)
    parts = score.load_parts(con)
    ft = score.first_trades(p, {e["token"] for e in evs})
    owners_hit = {r[2] or r[1] for r in parts if r[8] and r[9]}
    cand = {r[1] for r in parts if (r[2] or r[1]) in owners_hit}
    bad = score.bots(con, p, c, cand, now - int(c["days"]) * 86400)
    stats = score.classify(parts, evs, now + 1, c, bad, ft)
    n_groups = score.save(con, stats, now)
    cats = ev.catalyze(con, p, evs, chain.waves(con, c))
    prev = json.loads(store.kv(con, "summary") or "{}") if light else {}
    if light and prev.get("copy"):
        cs, ok, why = prev["copy"], prev.get("copyable"), prev.get("verdict")
    else:
        rows, _conf = copy.walk(con, p, c, evs, parts, now, bad, ft)
        copy.save(con, rows)
        cs = copy.summarize(rows)
        ok, why = copy.verdict(cs)
    sellers = {r[1] for r in parts if r[9]}
    before = {r[1] for r in parts if r[9] and r[8]}
    conf = score.confirmed(stats)
    cls = {}
    for s in stats.values():
        cls[s["cls"]] = cls.get(s["cls"], 0) + 1
    summary = {"ts": now, "events": len(evs), "call_events": sum(1 for e in evs if e["kind"] == "call"),
               "jump_events": sum(1 for e in evs if e["kind"] == "jump"),
               "covered": sum(1 for e in evs if e.get("n_part")), "fetched": sum(1 for e in evs if e.get("fetched")),
               "sellers": len(sellers), "bought_before": len(before), "groups_stored": n_groups,
               "confirmed": len(conf), "classes": cls, "relayers": len(relay), "bots": len(bad),
               "catalysts": cats, "copy": cs, "copyable": ok, "verdict": why,
               "helius_today": store.helius_spent(con, now),
               "helius_cap": store.helius_cap(c, now, p.get("usage_db"))[0]}
    try:
        from insajderi import trending
        if light and prev.get("trending"):
            summary["trending"] = {**prev["trending"], "new": trending.log_entries(con, p, now)}
        else:
            summary["trending"] = trending.run(con, p, c, now)
    except Exception as e:  # noqa: BLE001 - one part costs only itself
        _log(log, f"trending ({type(e).__name__}: {e})")
    try:
        from insajderi import smart
        summary["smart"] = prev["smart"] if light and prev.get("smart") else smart.run(con, p, c, now, stats, evs, parts)
    except Exception as e:  # noqa: BLE001
        _log(log, f"pametni novac ({type(e).__name__}: {e})")
    store.kv(con, "summary", json.dumps(summary, ensure_ascii=False, default=str))
    con.commit()
    return summary


def summary(path=None):
    """The last pass's summary ({} before the first)."""
    con = store.ro(path or store.db_path())
    rows = store.q(con, "SELECT value FROM i2_kv WHERE key = 'summary'")
    if con is not None:
        con.close()
    try:
        return json.loads(rows[0][0]) if rows else {}
    except (ValueError, TypeError):
        return {}
