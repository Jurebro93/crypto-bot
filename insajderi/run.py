"""The passes of Insajderi 2.0 (run_insajderi.py).

  once    ~10 min after a deploy (start.sh, under ops.heavy, nice): the existing data first (no Helius for what our
          databases already hold), Helius for at most deploy_share (40 %) of the day's cap
  night   01-06 Zagreb (ops.heavy --night), at most once in night_gap_h: the rest of the day's cap
  incr    every 3 h, light: new events of the last 2 days, Helius at most incr_share (10 %) of the cap, the groups
          (the demo's watched set), catalysts and the trending log; the walk-forwards keep the last full pass's numbers
  report  the reports and the log line only

once / night / incr end with the pass of the influencers' probably linked wallets (insajderi/kolwallets.run_pass: its
own small share of the Helius day cap, a time bound, one log line "insajderi kol: ...").

Each pass ends with the log line (report.line) and output/insajderi.md + output/pametni_novac.md; 19.11.: also the
wallets that buy BEFORE a pump (insajderi/prijepumpe.py, output/novcanici_prije_pumpe.md, one line "novčanici prije
pumpe: ...") and the pump tiers first in the Helius order (chain.order_key). Everything runs
under the owner switch fokus_midcap as an explicit, budgeted exception (ops/fokus.EXCEPTIONS).
"""
import json
import time

from insajderi import chain, copy, events as ev, score, store


def _log(log, msg):
    log(store.PREFIX + msg)


STAGE_HR = (("dogadaji", "događaji"), ("lanac", "lanac"), ("popis", "popis"), ("birdeye", "birdeye"), ("kopija", "kopija"),
            ("ostalo", "ostalo"), ("kol", "kol"))


def _unfetched(con, c, now):
    """'N događaja (pumpa15 a, pumpa2 b, ostalo c)' of the events still due for Helius."""
    evs = chain.due_events(con, ev.load_horizon(con, c, now), now)   # 19.11. navečer: incl. shallow pumps to re-read
    t15 = sum(1 for e in evs if e.get("tier") == "pumpa15")
    t2 = sum(1 for e in evs if e.get("tier") == "pumpa2")
    return f"{len(evs)} događaja (pumpa15 {t15}, pumpa2 {t2}, ostalo {len(evs) - t15 - t2})"


def force_once(con):
    """19.11. navečer: the pass after a deploy runs even within once_gap_h while the pump list was never computed (no
    prije_pumpe in the stored summary) or the Helius depth version changed (store.FETCH_DEPTH; set after a full pass
    that computed the list). So it runs ONCE after this deploy, and again only if it did not get to the list."""
    try:
        s = json.loads(store.kv(con, "summary") or "{}")
    except ValueError:
        s = {}
    return not s.get("prije_pumpe") or str(store.kv(con, "depth_version") or "") != str(store.FETCH_DEPTH)


def pump_counts(evs):
    """'pumpe: ≥ 15M n (1h a, 1d b), 2-15M m (1h c, 1d d); pročitano do dubine k' of the events a pass works on."""
    n = {(t, r): 0 for t in ("pumpa15", "pumpa2") for r in ("1h", "1d")}
    for e in evs:
        if e.get("tier") in ("pumpa15", "pumpa2"):
            n[(e["tier"], ev.res_of(e))] += 1
    return (f"pumpe: ≥ 15M {n[('pumpa15', '1h')] + n[('pumpa15', '1d')]} (1h {n[('pumpa15', '1h')]}, 1d "
            f"{n[('pumpa15', '1d')]}), 2-15M {n[('pumpa2', '1h')] + n[('pumpa2', '1d')]} (1h {n[('pumpa2', '1h')]}, "
            f"1d {n[('pumpa2', '1d')]})")


def time_line(kind, clk):
    """19.11.: "insajderi2: prolaz <kind>: trajanje: događaji 3 s, lanac 210 s, ...[; prekinuto na vremenskoj granici
    900 s: <what was left>]"."""
    parts = [f"{hr} {clk.stages[k]:.0f} s" for k, hr in STAGE_HR if k in clk.stages]
    out = f"{store.PREFIX}prolaz {kind}: trajanje: " + (", ".join(parts) or "—")
    if clk.sub:   # 19.11. navečer: the list stage's steps ("popis: vlasnici 12 s, botovi 40 s, ...")
        out += "; popis: " + ", ".join(f"{k} {v:.0f} s" for k, v in clk.sub.items())
    if chain.LAST_POOL.get("line"):   # 19.11. navečer (2): "dohvat: N poziva, R/s prosjek, radnika W, 429: K"
        out += "; " + chain.LAST_POOL["line"]
    if clk.cuts:
        out += f"; prekinuto na vremenskoj granici {clk.max_s:.0f} s: " + "; ".join(clk.cuts)
    return out


def run(kind="once", now=None, cfg=None, credits=None, fetch=None, log=print, clock=None, **over):
    """One pass. Returns the summary dict (also stored as i2_kv summary). 19.11.: under a wall-clock budget
    (pass_max_s[kind], store.Clock; clock: a fake time.monotonic for tests). The order puts the cheap, valuable part
    first: events + tiers, Helius (pumpa15, pumpa2, the rest), the class list, the copy tests, the rest; a stage that
    meets the budget stops cleanly, what was done is saved, the rest waits for the next pass and the time line says
    what was left."""
    now = int(now or time.time())
    c = store.effective(store.config(cfg), now)   # 19.11. navečer: the backfill's once / incr values until its date
    p = store.paths(**over)
    con = store.connect(p.get("insajderi_db"))
    clk = store.Clock(kind, c, clock)
    chain.LAST_POOL["line"] = None
    del chain.LAST_FETCHED[:]
    try:   # 19.11. navečer (2): one rate for every thread of this process (wallets/rpc.LIMIT)
        from wallets import rpc
        rpc.LIMIT.set_rps(float(c.get("helius_rps") or 8))
    except Exception:  # noqa: BLE001
        pass
    try:
        if kind == "night":
            last = int(float(store.kv(con, "night_last") or 0))
            if now - last < float(c["night_gap_h"]) * 3600:
                _log(log, f"noćni prolaz već odrađen prije {(now - last) / 3600:.1f} h, preskačem")
                return json.loads(store.kv(con, "summary") or "{}")
        if kind == "once" and credits is None and not force_once(con):   # a deploy a few times a day must not redo
            last = max(int(float(store.kv(con, "once_last") or 0)), int(float(store.kv(con, "night_last") or 0)))
            if now - last < float(c["once_gap_h"]) * 3600:
                _log(log, f"prolaz nakon deploya već odrađen prije {(now - last) / 3600:.1f} h, preskačem")
                return json.loads(store.kv(con, "summary") or "{}")
        since = now - (2 * 86400 if kind == "incr" else int(c["days"]) * 86400)
        if kind != "report":
            with clk.stage("dogadaji"):
                calls = ev.call_events(p, c, now, since)
                jumps = ev.market_events(p, c, now, max(since, now - int(c["mkt_days"]) * 86400))
                merged = ev.merge(calls, jumps)
                if kind != "incr":   # 19.11. navečer: the pumps of the daily candles (180 days), the 1h ones win
                    old = ev.load(con, now - int(c["pump_days_1d"]) * 86400)
                    merged += ev.daily_events(p, c, now, ev.avoid_map(merged + old))
                new = ev.save(con, merged, now)
                ev.mark_tiers(con, c)   # 19.11.: the pump tiers (pumpa15 / pumpa2) of every stored market jump
                evs = ev.load_horizon(con, c, now)
                _log(log, pump_counts(evs))
                # 19.11. navečer (production: "događaji" 364 s): rebuilding the participants of EVERY event of 45 / 180
                # days on every pass is the night pass's job (the free sources, e.g. wallets/povijest's histories,
                # can add old trades); once / incr rebuild only the events never built and those still young
                if kind == "night":
                    todo = [e for e in evs if e["t0"] >= since or not e.get("n_part")]
                else:
                    todo = [e for e in evs if not e.get("n_part") or e["win_end"] >= now - 3 * 86400]
                todo = sorted(todo, key=chain.order_key)
                built = chain.build(con, p, c, todo, stop=clk.over)
                if built < len(todo):
                    clk.cut(f"{len(todo) - built} događaja još bez sudionika")
            with clk.stage("lanac"):
                cap, how = store.helius_cap(c, now, p.get("usage_db"))
                left = store.helius_left(con, c, now, p.get("usage_db"))
                if credits is not None:
                    budget = min(int(credits), left)
                elif kind == "once":
                    budget = min(left, int(cap * float(c["deploy_share"])))
                elif kind == "night":
                    budget = left
                    try:   # 16.11.: the influencers' linked wallets keep their own small share of the day cap
                        from insajderi import kolwallets
                        budget = max(0, left - kolwallets.reserve(con, p, c, now))
                    except Exception:  # noqa: BLE001
                        pass
                else:   # incr: a small share of the cap for the new calls
                    budget = min(left, int(cap * float(c["incr_share"])))
                n_f, spent = (0, 0)
                if budget > 0 and not clk.over():
                    evs = ev.load_horizon(con, c, now)
                    # 19.11. (the first production pass: all 900 s went to Helius for 972 untiered call events, so
                    # the list and the copy tests were never computed): the pump tiers get the whole deadline; the
                    # rest (call events) only rest_time_share of the pass time (and rest_credit_share of the budget, 1.0 = no cut:
                    # every pass serves the pumps first anyway),
                    # so the list and the copy tests always get their turn
                    pumps = [e for e in evs if e.get("tier")]
                    rest = [e for e in evs if not e.get("tier")]
                    # 19.11. 19:56 (the first deep pass: 1444 s of Helius for 79 pumps, the 1800 s were over and the
                    # list was again not computed): the pumps read until pump_time_share of the pass time, never to
                    # its end, so the list and the funnel are computed in EVERY pass from what has been read so far
                    share_p = float(c.get("pump_time_share", 0.65))

                    def pump_stop():
                        return clk.over() or (clk.max_s is not None and clk.elapsed() >= clk.max_s * share_p)
                    n_f, spent = chain.fetch_due(con, p, c, pumps, now, budget, fetch=fetch, log=log, stop=pump_stop)
                    if not clk.over() and pump_stop():
                        _log(log, f"Helius za pumpe stao na {share_p:.0%} vremena prolaza (ostatak vremena je za popis "
                                  f"i lijevak): ostaje {_unfetched(con, c, now)}")
                    share_t = float(c.get("rest_time_share", 0.5))

                    def rest_stop():
                        return clk.over() or (clk.max_s is not None and clk.elapsed() >= clk.max_s * share_t)
                    rb = min(budget - spent, int(budget * float(c.get("rest_credit_share", 1.0))))
                    if rb >= 10 and not rest_stop():
                        n2, s2 = chain.fetch_due(con, p, c, rest, now, rb, fetch=fetch, log=log, stop=rest_stop)
                        n_f, spent = n_f + n2, spent + s2
                    if not clk.over() and rest_stop():
                        _log(log, f"Helius za pozive stao na {share_t:.0%} vremena prolaza (pumpe imaju prednost): "
                                  f"ostaje {_unfetched(con, c, now)}")
                    if n_f:   # 19.11. navečer: only the events read in THIS pass (was: every fetched event)
                        just = set(chain.LAST_FETCHED)
                        chain.build(con, p, c, [e for e in ev.load_horizon(con, c, now) if e["eid"] in just],
                                    stop=clk.over)
                if clk.over():
                    clk.cut(f"Helius ostaje {_unfetched(con, c, now)} za sljedeći prolaz (istim redom)")
                con.execute("INSERT INTO i2_runs VALUES (?,?,?,?)",
                            (now, kind, spent, json.dumps({"new_events": new, "fetched": n_f, "budget": budget,
                                                           "cap": cap, "cap_how": how})))
                con.commit()
            _log(log, f"Helius {spent:,} kr. ({n_f} događaja), danas {store.helius_spent(con, now):,} od {cap:,} "
                      f"({how})")
        summary = analyze(con, p, c, now, log=log, light=(kind == "incr"), clk=clk)
        if kind != "report":   # 16.11.: the influencers' probably linked wallets (bounded, never raises into here)
            if clk.over():
                clk.cut("sporedni novčanici influencera preskočeni")
            else:
                with clk.stage("kol"):
                    try:
                        from insajderi import kolwallets
                        kolwallets.run_pass(con, p, c, now, kind=kind, fetch=fetch, credits=credits, log=log,
                                            left_s=clk.left_s())
                    except Exception as e:  # noqa: BLE001
                        log(f"insajderi kol: prolaz nije uspio ({type(e).__name__}: {e})")
        if kind in ("night", "once"):
            store.kv(con, f"{kind}_last", now)
            if (summary or {}).get("prije_pumpe"):   # 19.11. navečer: the forced once pass is done for this depth
                store.kv(con, "depth_version", store.FETCH_DEPTH)
            store.kv(con, "stage_s", json.dumps({**clk.stages, "ts": now, "kind": kind, "cut": bool(clk.cuts),
                                                 "popis_koraci": dict(clk.sub)}))
        summary["trajanje"] = dict(clk.stages)
        summary["prekinuto"] = list(clk.cuts)
        store.kv(con, "summary", json.dumps(summary, ensure_ascii=False, default=str))
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
            if kind == "report":
                log(report.kol_line())
            else:
                log(time_line(kind, clk))
        except Exception as e:  # noqa: BLE001
            _log(log, f"log linija ({type(e).__name__}: {e})")
        return summary
    finally:
        con.close()


def _list_ok(con, c, light):
    """Run the class list in this pass? Always in once / night; in incr only when the last full pass measured the
    list stage (popis) under incr_list_max_s (60 s). -> (ok, why not)."""
    if not light:
        return True, None
    try:
        st = json.loads(store.kv(con, "stage_s") or "{}")
    except ValueError:
        st = {}
    s = st.get("popis")
    if s is None:
        return False, "popis još nije izmjeren u punom prolazu"
    if s >= float(c["incr_list_max_s"]):
        return False, f"popis je u zadnjem punom prolazu trajao {s:.0f} s (granica {c['incr_list_max_s']} s)"
    return True, None


def analyze(con, p, c, now, log=print, light=False, clk=None):
    """Owners, classification, catalysts, the copy walk-forward, trending and smart money -> the summary. light (incr):
    the walk-forwards (copy, smart money, trending score) keep the last full pass's numbers, and the class list runs
    only when it was fast on the last full pass (_list_ok). clk: the pass's store.Clock (19.11.); the order: the list,
    the copy tests (the wallets' trades read ONCE for both), the rest."""
    clk = clk or store.Clock("report", c)
    stop = clk.over
    evs = ev.load_horizon(con, c, now)
    prev = json.loads(store.kv(con, "summary") or "{}")
    ok_list, why_not = _list_ok(con, c, light)
    if ok_list and clk.over():
        ok_list, why_not = False, "vremenska granica"
        clk.cut("popis i kopija nisu izračunati")
    if not ok_list:
        _log(log, f"popis i bundle preskočeni ({why_not}); ostaju brojke zadnjeg prolaza")
        summary = {**prev, "ts": now, "events": len(evs), "call_events": sum(1 for e in evs if e["kind"] == "call"),
                   "jump_events": sum(1 for e in evs if e["kind"] == "jump"),
                   "covered": sum(1 for e in evs if e.get("n_part")),
                   "fetched": sum(1 for e in evs if e.get("fetched")),
                   "helius_today": store.helius_spent(con, now),
                   "helius_cap": store.helius_cap(c, now, p.get("usage_db"))[0], "list_skipped": why_not}
        store.kv(con, "summary", json.dumps(summary, ensure_ascii=False, default=str))
        con.commit()
        return summary
    from insajderi import prijepumpe
    # 19.11. navečer (production: the list stage ran 21+ min past the deadline, holding the heavy lock): the funnel
    # FIRST from cheap SQL counts (the owner always gets it), then every step timed (clk.sub, the pass line "popis:
    # vlasnici 12 s, ...") and asked to stop between steps: at the pass deadline or when the list stage alone passed
    # list_max_s (600 s). A cut step keeps the stored result of what it did not compute and says which step.
    t_list = clk.fn()
    list_max = float(c.get("list_max_s") or 600)
    prev_pp = dict(prev.get("prije_pumpe") or {})
    try:
        prev_pp["lijevak"] = prijepumpe.funnel_sql(con, c, evs)
    except Exception as e:  # noqa: BLE001
        _log(log, f"lijevak ({type(e).__name__}: {e})")
    cut_at = []

    def lstop():
        return clk.over() or clk.fn() - t_list >= list_max

    def step(name, fn):
        if cut_at:
            return None
        if lstop():
            cut_at.append(name)
            return None
        t0 = clk.fn()
        try:
            return fn()
        finally:
            clk.sub[name] = round(clk.sub.get(name, 0.0) + clk.fn() - t0, 1)
    own = relay = parts = ft = bad = stats = cats = None
    n_groups = None
    pp, mm = {}, set()
    with clk.stage("popis"):
        r = step("vlasnici", lambda: chain.assign_owners(con, p, c))
        if r is not None:
            own, relay = r
        parts = step("dijelovi", lambda: score.load_parts(con))
        ft = step("prvi", lambda: score.first_trades(p, {e["token"] for e in evs}))

        def _bots():
            owners_hit = {r_[2] or r_[1] for r_ in parts if r_[8] and r_[9]}
            cand = {r_[1] for r_ in parts if (r_[2] or r_[1]) in owners_hit}
            return score.bots(con, p, c, cand, now - int(c["days"]) * 86400)
        bad = step("botovi", _bots)
        stats = step("klase", lambda: score.classify(parts, evs, now + 1, c, bad, ft))
        n_groups = step("spremanje", lambda: score.save(con, stats, now))
        cats = step("katalizatori", lambda: ev.catalyze(con, p, evs, chain.waves(con, c)))

        def _pp():
            return prijepumpe.run_list(con, c, now, evs, parts, bad, ft, prev_pp, lstop)
        try:   # 19.11. (vlasnik: "svi resursi u pronalaženje novčanika koji kupuju prije pumpe"): insajderi/prijepumpe
            r = step("prije_pumpe", _pp)
            if r is not None:
                pp, mm = r
                if pp.get("cut"):
                    cut_at.append(f"prije_pumpe ({pp['cut']})")
        except Exception as e:  # noqa: BLE001 - one part costs only itself
            _log(log, f"novčanici prije pumpe ({type(e).__name__}: {e})")
    if cut_at:
        why = "vremenska granica prolaza" if clk.over() else f"popis dulji od {list_max:.0f} s"
        clk.cut(f"popis: prekinuto u koraku {cut_at[0]} ({why}); ostaje zadnji izračun tog dijela")
        _log(log, f"popis: prekinuto u koraku {cut_at[0]} ({why})")
        if not pp:
            pp = prev_pp
    if stats is None:   # the class list was not computed: the stored numbers of the last pass stay
        summary = {**prev, "ts": now, "events": len(evs), "call_events": sum(1 for e in evs if e["kind"] == "call"),
                   "jump_events": sum(1 for e in evs if e["kind"] == "jump"),
                   "covered": sum(1 for e in evs if e.get("n_part")),
                   "fetched": sum(1 for e in evs if e.get("fetched")),
                   "helius_today": store.helius_spent(con, now),
                   "helius_cap": store.helius_cap(c, now, p.get("usage_db"))[0],
                   "list_skipped": f"prekinuto u koraku {cut_at[0] if cut_at else '?'}"}
        if pp:
            summary["prije_pumpe"] = pp
        store.kv(con, "summary", json.dumps(summary, ensure_ascii=False, default=str))
        con.commit()
        return summary
    cats = cats if cats is not None else prev.get("catalysts")
    n_groups = n_groups if n_groups is not None else prev.get("groups_stored")
    pp_fresh = bool(pp) and pp is not prev_pp   # the list was computed in this pass (the copy walk needs it)
    if not clk.over():   # 19.11. navečer: Birdeye, a bounded second source (report only; insajderi/birdeye.py)
        with clk.stage("birdeye"):
            try:
                from insajderi import birdeye
                b = birdeye.run(con, c, evs, now, stop=clk.over, log=log)
                pp = dict(pp or prev_pp or {}, birdeye=b)
            except Exception as e:  # noqa: BLE001 - a second source never costs the pass
                _log(log, f"birdeye ({type(e).__name__}: {e})")
    cs, ok, why = prev.get("copy"), prev.get("copyable"), prev.get("verdict")
    if not light and (clk.over() or cut_at or bad is None or ft is None):
        clk.cut("kopija nije izračunata (ostaju brojke zadnjeg punog prolaza)")
    elif not light:
        with clk.stage("kopija"):
            csel = copy.selection(c, evs, parts, now, bad, ft, stop)
            psel = prijepumpe.selection(c, evs, parts, now, bad, ft, mm, True, stop) if pp else None
            members = (csel[2] if csel else set()) | (psel[3] if psel else set())
            trades = copy.wallet_trades(con, p, members) if members and not stop() else []
            rows = copy.walk(con, p, c, evs, parts, now, bad, ft, trades=trades, sel=csel, stop=stop)[0] \
                if csel is not None else None
            if rows is None:
                clk.cut("kopija insajdera nije dovršena (ostaju zadnje brojke)")
            else:
                copy.save(con, rows)
                cs = copy.summarize(rows)
                ok, why = copy.verdict(cs)
            if pp_fresh and mm is not None:
                try:
                    res = prijepumpe.walk(con, p, c, evs, parts, now, bad, ft, mm, trades=trades, sel=psel,
                                          stop=stop)[0] if psel is not None else None
                    if res is None:
                        clk.cut("kopija novčanika prije pumpe nije dovršena (ostaju zadnje brojke)")
                    else:
                        pp = prijepumpe.run_copy(con, p, c, now, evs, parts, pp, res)
                except Exception as e:  # noqa: BLE001
                    _log(log, f"novčanici prije pumpe: kopija ({type(e).__name__}: {e})")
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
    if pp:
        summary["prije_pumpe"] = pp
    if light or clk.over():
        if clk.over() and not light:
            clk.cut("trending i pametni novac: ostaju zadnji")
        for k in ("trending", "smart"):
            if prev.get(k):
                summary[k] = prev[k]
        try:
            from insajderi import trending
            if light and prev.get("trending"):
                summary["trending"] = {**prev["trending"], "new": trending.log_entries(con, p, now)}
        except Exception as e:  # noqa: BLE001
            _log(log, f"trending ({type(e).__name__}: {e})")
    else:
        with clk.stage("ostalo"):
            try:
                from insajderi import trending
                summary["trending"] = trending.run(con, p, c, now)
            except Exception as e:  # noqa: BLE001 - one part costs only itself
                _log(log, f"trending ({type(e).__name__}: {e})")
            try:
                from insajderi import smart
                summary["smart"] = smart.run(con, p, c, now, stats, evs, parts)
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
