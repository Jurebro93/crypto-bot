"""Orchestration (start.sh: `run_makroinf.py krug` every ~10 min at low priority; `run_makroinf.py noc` 01-06
Zagreb under the heavy-job lock).

krug (a bounded round, krug_s seconds of work at most; resumable after every deploy):
  1. the seed and the owner's file; profiles of new accounts and the daily follower / statuses snapshot
  2. prices every 20 h (CoinGecko, ~25 calls a day, cached)
  3. PILOT: the backfill units round-robin under the pilot cap (5 $); when no unit is left (or the cap is reached)
     the pilot fetch is done and everything after runs under the daily cap (0,50 $): the day's macro posts once in
     20 h, deletion checks every 6 h, the backfill of accounts added later (the circle, a confirmed candidate)
  4. classification of the new posts (pilot 4 $, then 0,25 $ a day)
  5. the light scoring (episodes, outcomes, the three scores, today's prospective index, the DEMO input state); the
     first time the pilot's classification is complete also the quality check and the walk-forward (same day)
  6. once an hour the line "makroinf: sat: ..." and the spend per phase
15.11. navečer, the owner's order (makroinf/discover.py; recorded once, it overrides the quality gate): discovery of
  300-500 accounts, then the deep history of every account (the most regular first) under the expansion caps
  (twitterapi 40 $, OpenAI 15 $), the rest under the daily caps (1,50 $ / 0,50 $); the daily fetch of every active
  account every round (only the accounts not fetched in 20 h), the topics of the day every 6 h, the market mood after
  every scoring (makroinf/mood.py)
16.11., the owner's second order (discover.record_order2 / step2: 30k+ followers, the ceiling 800 accounts): recorded
  once after the first wave's discovery is done, its estimate logged before its first paid call; its discovery (the
  stored candidates first), the history of its accounts (the last 200 posts + up to 300 market posts over 12 months)
  and its classification run under ITS caps (twitterapi 25 $, OpenAI 8 $), separate from the first wave's; the daily
  caps are 2,00 $ / 0,60 $
noc: the full re-scoring: clusters, the walk-forward of the index (train -> validation -> locked test), the historic
index series, the quality check when it is missing, output/makroinf.md.
"""
import contextlib
import fcntl
import json
import time

from makroinf import (classify, deleted, discover, fetch, index, mood, prices, quality, racuni, report, rules, score,
                      store, teme, xapi)

D = 86400


@contextlib.contextmanager
def _lock(path=None, wait=0.0):
    """True once this process holds makroinf's run lock (a krug and the night's pass never write at the same time)."""
    f = open((path or store.db_path()) + ".lock", "a")
    got, t_end = False, time.time() + wait
    try:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.time() >= t_end:
                    break
                time.sleep(5)
        yield got
    finally:
        if got:
            fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _due(con, key, every_s, now):
    last = float(store.kv(con, key) or 0)
    return now - last >= every_s


def _calls_by_handle(con):
    n_macro, n_promo = {}, {}
    for h, n, p in store.q(con, "SELECT handle, COUNT(DISTINCT id), COUNT(DISTINCT CASE WHEN promo = 1 THEN id END) "
                                "FROM calls GROUP BY handle"):
        n_macro[h], n_promo[h] = n - p, p
    return n_macro, n_promo


def score_all(con, now=None, log=print, truth=None, write_index=True):
    """Episodes, outcomes, register, the three scores of every account and today's index (prospective + historic
    value now). Returns a summary dict (also kv summary)."""
    now = int(now or time.time())
    calls = index.load_calls(con)
    truth = truth or prices.load(con)
    eps, reg, skipped = rules.episodes(calls, now)
    outs = [o for ep in eps for o in rules.evaluate(ep, truth, now)]
    rv = rules.RULES_VERSION
    con.execute("DELETE FROM outcomes WHERE rules_v = ?", (rv,))
    con.executemany("""INSERT OR REPLACE INTO outcomes (eid, horizon, rules_v, handle, asset, direction, w, t_call,
        t_start, p0, thr, ret, res, level, follow, b_bull, b_rand_hit, b_rand_dec, b_trend, b_bull_follow,
        b_trend_follow, prob, done_ts, first_id, n_calls, hz) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(o["eid"], o["horizon"], rv, o["handle"], o["asset"], o["direction"], o["w"], o["t_call"],
                      o.get("t_start"), o.get("p0"), o.get("thr"), o.get("ret"), o["res"], o.get("level"),
                      o.get("follow"), o.get("b_bull"), o.get("b_rand_hit"), o.get("b_rand_dec"), o.get("b_trend"),
                      o.get("b_bull_follow"), o.get("b_trend_follow"), o.get("prob"), o.get("done_ts"), o["first_id"],
                      o["n_calls"], o["hz"]) for o in outs])
    con.execute("DELETE FROM register WHERE rules_v = ?", (rv,))
    con.executemany("INSERT INTO register VALUES (?,?,?,?,?,?,?)",
                    [(r["handle"], r["asset"], r["ts"], r["event"], r["eid"], None, rv) for r in reg])
    prior = score.pooled_rate(outs)
    by = {}
    for o in outs:
        by.setdefault(o["handle"], []).append(o)
    n_macro, n_promo = _calls_by_handle(con)
    dels = deleted.states(con)
    tw_h = {i: h for i, h in store.q(con, "SELECT id, handle FROM deletions")}
    del_by = {}
    for i, s in dels.items():
        del_by.setdefault(tw_h.get(i), {})[i] = s
    scores = {}
    for h, _cat, _src in racuni.active(con) + [(x, None, None) for (x,) in
                                                store.q(con, "SELECT handle FROM accounts WHERE status = 'neaktivan'")]:
        s = score.account(by.get(h, []), n_macro.get(h, 0), del_by.get(h, {}), n_promo.get(h, 0), prior)
        scores[h] = s
    con.execute("DELETE FROM scores")
    con.executemany("INSERT INTO scores VALUES (?,?,?,?)",
                    [(h, rv, now, json.dumps(s, ensure_ascii=False)) for h, s in scores.items()])
    summ = {"ts": now, "rules_v": rv, "rules_hash": rules.RULES_HASH, "calls": len(calls), "episodes": len(eps),
            "skipped": skipped, "outcomes": {k: sum(1 for o in outs if o["res"] == k) for k in
                                             ("hit", "miss", "flat", "ceka", "neaktiviran", "bez_podataka", "dugo")},
            "prior": round(prior, 4), "accounts_scored": len(scores),
            "enough": sum(1 for s in scores.values() if s["prediktivno"]["presuda"] != score.VERDICT_FEW),
            "rank": score.rank(scores)}
    if write_index:
        summ["index"] = index_now(con, calls, outs, truth, now)
    st = index.input_state(con, now=now)
    store.kv(con, "ulaz", st)
    summ["ulaz"] = st
    m = mood.refresh(con, now, calls)
    summ["raspolozenje"] = {k: b["presuda"] for k, b in m["okviri"].items()}
    store.kv(con, "summary", summ)
    con.commit()   # the pages' read-only connection (web.view) must not wait for this writer
    _refreshed(con, now, log)
    con.commit()
    return summ


def _refreshed(con, now, log):
    """15.11. (vlasnik: "... osvježavati i stranice koje vide korisnici i Google"): kv "javno" after every scoring; the
    UI process sees the new stamp and drops its cached macro pages (makroinf/web.sync). Returns (accounts, sitemap)."""
    try:
        from makroinf import web
        return web.refreshed(con, now)
    except Exception as e:  # noqa: BLE001 - the pages then refresh on their own cache times
        log(store.PREFIX + f"javne stranice: oznaka osvježavanja nije upisana: {type(e).__name__}: {e}"[:200])
        return None


def index_now(con, calls, outs, truth, now):
    """Today's index rows (t = now) per asset, prospective and historic availability, clusters from the last night."""
    cl = store.kv_json(con, "klasteri", {}) or {}
    w = store.kv_json(con, "walk", {}) or {}
    k = int(w.get("k") or index.INDEX_LOCKED["default_k"])
    contra = w.get("kontra_skup") or None
    act = index.activations(calls, truth)
    acc = index.accuracy_at(outs, now)
    top = set(index.top_set(acc, k))
    day = int(now) // D * D
    out = {}
    stav = {"ts": now, "sada": {}, "prije_7d": {}}
    for asset in index.INDEX_LOCKED["assets"]:
        by = index.group(calls, asset)
        for key, t in (("sada", now), ("prije_7d", now - 7 * D)):
            for h, cs in by.items():
                s = index.stance(cs, t, "prospektivno", act)
                if s is not None:
                    stav[key].setdefault(asset, {})[h] = {"s": s[0], "dir": s[1]["direction"], "ts": s[1]["ts"],
                                                          "id": str(s[1]["id"]), "hz": s[1].get("horizon_days")}
        for mode in ("prospektivno", "povijesno"):
            st = index.stances(by, now, mode, act)
            v_all, n_all, c_all = index.value(st, {h: 1.0 for h in st}, cl)
            v_top, n_top, c_top = index.value(st, {h: 1.0 for h in st if h in top}, cl)
            rows = [("svi", v_all, n_all, c_all), ("top", v_top, n_top, c_top)]
            if contra:
                inv = {h: -s for h, s in st.items() if h in contra}
                v_k, n_k, c_k = index.value(inv, {h: 1.0 for h in inv}, cl)
                rows.append(("kontra", v_k, n_k, c_k))
            for kind, v, n, ncl in rows:
                con.execute("INSERT OR REPLACE INTO index_d VALUES (?,?,?,?,?,?,?)",
                            (day, asset, mode, kind, v, n, json.dumps({"ts": now, "klastera": ncl, "k": k})))
            out[f"{asset}:{mode}"] = {"svi": v_all, "n_svi": n_all, "top": v_top, "n_top": n_top}
    store.kv(con, "stavovi", stav)
    store.kv(con, "top_sada", sorted(top))
    return out


def _texts_quotes(con):
    texts = {}
    for h, t in store.q(con, "SELECT handle, text FROM tweets WHERE macro = 1"):
        texts.setdefault(h, []).append(t)
    quotes = [(h, q, ts) for h, q, ts in store.q(con, "SELECT handle, quoted_handle, ts FROM tweets WHERE "
                                                      "quoted_handle IS NOT NULL")]
    return texts, quotes


def full(con, now=None, log=print, call=None, quality_check=True):
    """The night's (or the pilot's first) full pass: clusters, the walk-forward, the scores, the quality check."""
    now = int(now or time.time())
    truth = prices.load(con)
    calls = index.load_calls(con)
    texts, quotes = _texts_quotes(con)
    cl = index.clusters(calls, texts, quotes, now)
    store.kv(con, "klasteri", cl)
    summ = score_all(con, now, log, truth, write_index=False)
    outs = [dict(zip(("eid", "handle", "res", "w", "done_ts"), r)) for r in
            store.q(con, "SELECT eid, handle, res, w, done_ts FROM outcomes WHERE rules_v = ?", (rules.RULES_VERSION,))]
    t0 = time.time()
    w = index.walk(calls, outs, truth, texts, quotes, now, log=log)
    store.kv(con, "walk", w)
    if w.get("available"):
        for d, r in (w.get("dani") or {}).items():
            con.execute("INSERT OR REPLACE INTO index_d VALUES (?,?,?,?,?,?,?)",
                        (int(d), "BTC", "povijesno", "top", r.get("top"), r.get("n_top"), None))
            con.execute("INSERT OR REPLACE INTO index_d VALUES (?,?,?,?,?,?,?)",
                        (int(d), "BTC", "povijesno", "svi", r.get("svi"), r.get("n_svi"), None))
        log(store.PREFIX + f"walk-forward indeksa (povijesno, pristrano): K={w['k']}, prag {w['thr']}; validacija "
                           f"{report.pct(w['validacija'].get('pogodak'))} n={w['validacija']['n']} (uvijek-bik "
                           f"{report.pct(w['validacija'].get('uvijek_bik'))}); zaključani test "
                           f"{report.pct(w['test_zakljucan'].get('pogodak'))} n={w['test_zakljucan']['n']} "
                           f"(uvijek-bik {report.pct(w['test_zakljucan'].get('uvijek_bik'))}); "
                           f"{time.time() - t0:.0f} s")
    else:
        log(store.PREFIX + f"walk-forward indeksa: {w.get('why')}")
    summ["index"] = index_now(con, calls, outs, truth, now)
    if quality_check and store.kv(con, "pilot_openai_done") and not (store.kv_json(con, "provjera", {}) or {}).get("ts"):
        quality.run(con, store.config(), now, log, call=call)
    st = index.input_state(con, now=now)
    store.kv(con, "ulaz", st)
    summ["ulaz"] = st
    m = mood.refresh(con, now, calls)
    summ["raspolozenje"] = {k: b["presuda"] for k, b in m["okviri"].items()}
    store.kv(con, "summary", summ)
    con.commit()
    summ["javno"] = _refreshed(con, now, log)   # after the index of the night: the pages show this scoring
    con.commit()
    report.write(con)
    return summ


def krug(now=None, log=print, cfg=None, get=None, call=None, path=None, budget_s=None, refresh_prices=True):
    """One bounded round (see the module text). Returns a dict of what was done."""
    with _lock(path, 0) as got:
        if not got:
            log(store.PREFIX + "noćni izračun u tijeku, krug preskočen")
            return {"preskoceno": True}
        return _krug(now, log, cfg, get, call, path, budget_s, refresh_prices)


def _krug(now, log, cfg, get, call, path, budget_s, refresh_prices):
    c = store.config(cfg)
    now = int(now or time.time())
    deadline = time.time() + float(budget_s or c["krug_s"])
    con = store.connect(path)
    out = {}
    try:
        racuni.seed(con, now, log=log)
        if not xapi.has_key(get) and not store.kv(con, "rekao_kljuc"):
            log(store.PREFIX + "nema TWITTERAPI_IO_KEY: dohvat stoji (računi, cijene i ocjene rade)")
            store.kv(con, "rekao_kljuc", str(now))
        out["profili"] = racuni.resolve(con, c, now, get, log, limit=60)
        if refresh_prices and _due(con, "prices_ts", c["prices_every_s"], now):
            out["cijene"] = prices.refresh(con, now, log)
        pilot = not store.kv(con, "pilot_twapi_done")
        normal = [h for h, _c, s in racuni.active(con) if not (s or "").startswith("prosirenje")]
        # the owner's order of 15.11. navečer applies once the pilot is classified (its numbers are the baseline)
        order = bool(store.kv(con, "pilot_openai_done")) and discover.record_order(con, c, now, log)
        # 16.11.: his second order (30k+, the ceiling 800), once the first wave's discovery is done; the estimate is
        # in the log here, before the wave's first paid call
        order2 = order and discover.record_order2(con, c, now, log)
        if pilot:
            r = fetch.backfill(con, c, now, get, log, deadline, handles=normal)
            out["pilot"] = r
            if r.get("cap") and "nema ključa" not in r["cap"]:
                store.kv(con, "pilot_twapi_done", str(now))
                store.kv(con, "pilot_twapi_why", f"strop pilota: {r['cap']}; ostatak povijesti ide pod dnevni strop")
                log(store.PREFIX + f"pilot dohvat: {r['cap']}; ostatak ({r['left']} jedinica) pod dnevnim stropom")
            elif not r.get("cap") and r.get("left") == 0:
                store.kv(con, "pilot_twapi_done", str(now))
                store.kv(con, "pilot_twapi_why", "sve jedinice dohvaćene")
                log(store.PREFIX + f"pilot dohvat gotov: {store.spent(con, 'twitterapi', 'pilot'):.2f} $ od "
                                   f"{c['pilot_twapi_usd']:.2f} $")
        else:
            # the daily fetch first (the day's posts of every active account; only those not fetched in 20 h, the
            # most regular first), then the deletion checks, both under the daily cap
            out["dnevno"] = fetch.incremental(con, c, now, get, log, deadline)
            if _due(con, "deleted_ts", c["deleted_every_s"], now) and time.time() < deadline:
                out["brisanja"] = deleted.check(con, c, now, get, log)
                store.kv(con, "deleted_ts", str(now))
            if order:
                if time.time() < deadline:
                    out["otkrivanje"] = discover.step(con, c, now, get, log, deadline)
                if order2 and time.time() < deadline:
                    out["otkrivanje2"] = discover.step2(con, c, now, get, log, deadline)
                if time.time() < deadline:
                    out["povijest"] = _deep(con, c, now, get, log, deadline)
            else:
                if time.time() < deadline:
                    out["povijest"] = fetch.backfill(con, c, now, get, log, deadline, handles=normal)
                exp = [h for h, _c, s in racuni.active(con) if (s or "").startswith("prosirenje")]
                if exp and time.time() < deadline:
                    out["prosirenje"] = fetch.backfill(con, c, now, get, log, deadline, ph="prosirenje", handles=exp)
        racuni.circle(con, c, now, get, log)
        racuni.mark_inactive(con, c, now)
        racuni.languages(con)
        if time.time() < deadline and order:
            out["klasifikacija"] = _classify_order(con, c, now, log, deadline, call)
        elif time.time() < deadline:
            out["klasifikacija"] = classify.run(con, c, now, log, deadline, call)
            r = out["klasifikacija"]
            if store.kv(con, "pilot_twapi_done") and not store.kv(con, "pilot_openai_done"):
                left = classify.pending(con, 1, expansion=False)
                if not left or (r.get("cap") and "strop" in r["cap"]):
                    store.kv(con, "pilot_openai_done", str(now))
                    log(store.PREFIX + f"pilot klasifikacija gotova: {store.spent(con, 'openai', 'pilot'):.2f} $ od "
                                       f"{c['pilot_openai_usd']:.2f} $" + (f" ({r['cap']})" if r.get("cap") else ""))
            if store.kv(con, "prosirenje") and time.time() < deadline:
                out["klasifikacija_prosirenje"] = classify.run(con, c, now, log, deadline, call, ph="prosirenje",
                                                               expansion=True)
        if store.kv(con, "pilot_openai_done") and time.time() < deadline:
            out["teme"] = teme.run(con, c, now, log, call)
        con.commit()
        if store.kv(con, "pilot_openai_done") and not store.kv(con, "prvi_izracun"):
            log(store.PREFIX + "pilot klasificiran: prvi puni izračun (rang, indeks, provjera kvalitete)")
            out["prvi"] = full(con, now, log, call)
            store.kv(con, "prvi_izracun", str(now))
        elif _due(con, "score_ts", 1800, now) and store.q(con, "SELECT 1 FROM calls LIMIT 1"):
            out["ocjene"] = score_all(con, now, log)
            store.kv(con, "score_ts", str(now))
        hour = now // 3600
        if store.kv(con, "sat") != str(hour):
            store.kv(con, "sat", str(hour))
            fetch.update_regularity(con, now)
            log(report.hour_line(con, now, c))
            if order:
                log(discover.phase_line(con, now))
        # the pilot still has paid work to do (and the keys are there): run_makroinf.py answers 3, start.sh comes back in
        # a minute instead of ten (the owner: results the same day)
        out["pilot_u_tijeku"] = bool((not store.kv(con, "pilot_openai_done") or discover.in_progress(con, c))
                                     and xapi.has_key(get) and (call is not None or _openai_key()))
        con.commit()
    finally:
        con.close()
    return out


def _deep(con, c, now, get, log, deadline):
    """The deep history of every measured account by the owner's order (zadnjih 200 + up to depth_posts market posts
    over 18 months), the most regular first in tiers of 100: under the expansion cap, then (when it is reached) the
    rest under the daily cap after the day's fetch. kv prosirenje_dubina_gotova once no unit is left. 16.11.: the
    second wave's accounts (zadnjih 200 + up to 300 market posts over 12 months) after them, under the SECOND wave's
    cap (then the daily one), kv prosirenje2_*; its result is in the returned dict under "val2"."""
    hs = [h for h, _s in racuni.by_regularity(con, ("aktivan",))]
    w2 = discover.wave2_handles(con)
    r = _deep_wave(con, c, now, get, log, deadline, [h for h in hs if h not in w2], "prosirenje", "proširenje",
                   c["expand_twapi_usd"], discover._state(con).get("step") == "gotovo")
    if discover.ordered2(con, c) and time.time() < deadline:
        r["val2"] = _deep_wave(con, c, now, get, log, deadline, [h for h in hs if h in w2], "prosirenje2",
                               "2. val proširenja", c["expand2_twapi_usd"],
                               discover._state2(con).get("step") == "gotovo")
    return r


def _deep_wave(con, c, now, get, log, deadline, hs, name, label, cap_usd, discovered):
    """One wave's history under its own cap `name`, the rest under the daily cap; kv <name>_strop_twapi when the cap
    is reached, <name>_dubina_gotova when no unit is left and the wave's discovery is done."""
    left = store.left(con, "twapi", name, now, c)
    ph = name if left >= twapi_page(c) else None
    r = fetch.backfill(con, c, now, get, log, deadline, ph=ph, handles=hs, tier=100)
    if not store.kv(con, f"{name}_strop_twapi") and ((ph and r.get("cap") and "strop" in r["cap"]) or
                                                     (ph is None and (r.get("units") or r.get("left")))):
        store.kv(con, f"{name}_strop_twapi", str(now))
        log(store.PREFIX + f"{label}: strop twitterapi {float(cap_usd):.2f} $ dosegnut; ostatak povijesti "
                           f"({r['left']} jedinica) ide pod dnevni strop")
        log(discover.phase_line(con, now))
    if not r.get("cap") and r.get("left") == 0 and discovered and not store.kv(con, f"{name}_dubina_gotova"):
        store.kv(con, f"{name}_dubina_gotova", str(now))
        log(store.PREFIX + f"{label}: povijest svih računa dohvaćena")
        log(discover.phase_line(con, now))
    return r


def twapi_page(c):
    from kol import twapi
    return twapi.cost(int(c["page_posts"]))


def _classify_order(con, c, now, log, deadline, call):
    """By the owner's order: the day's new posts first under the daily cap, then the history under the expansion
    cap, and once that is reached the history under what is left of the daily cap. 16.11.: the history of the second
    wave's accounts the same way under the SECOND wave's cap ("povijest2", "povijest2_dan")."""
    out = {"dnevno": classify.run(con, c, now, log, deadline, call, ph="dan", expansion=None, which="dnevno")}
    waves = [("prosirenje", "proširenje", "expand_openai_usd", 1, "povijest")]
    if discover.ordered2(con, c):
        waves.append(("prosirenje2", "2. val proširenja", "expand2_openai_usd", 2, "povijest2"))
    for name, label, cap_key, wave, key in waves:
        if time.time() >= deadline:
            break
        r = classify.run(con, c, now, log, deadline, call, ph=name, expansion=None, which="povijest", wave=wave)
        out[key] = r
        if r.get("cap") and "strop" in r["cap"]:
            if not store.kv(con, f"{name}_strop_openai"):
                store.kv(con, f"{name}_strop_openai", str(now))
                log(store.PREFIX + f"{label}: strop OpenAI {c[cap_key]:.2f} $ dosegnut; ostatak "
                                   "povijesti se razvrstava pod dnevnim stropom")
            if time.time() < deadline:
                out[f"{key}_dan"] = classify.run(con, c, now, log, deadline, call, ph="dan", expansion=None,
                                                 which="povijest", wave=wave)
    return out


def _openai_key():
    try:
        from critic import openai_api
        return openai_api.has_key()
    except Exception:  # noqa: BLE001
        return False


def noc(now=None, log=print, path=None, call=None, gap_h=20):
    with _lock(path, 900) as got:
        if not got:
            log(store.PREFIX + "noćni izračun: krug ne pušta bravu 15 min, sljedeći sat")
            return None
        return _noc(now, log, path, call, gap_h)


def _noc(now, log, path, call, gap_h):
    now = int(now or time.time())
    con = store.connect(path)
    try:
        last = float(store.kv(con, "noc_ts") or 0)
        if now - last < gap_h * 3600:
            log(store.PREFIX + f"noćni izračun već odrađen prije {(now - last) / 3600:.1f} h, preskačem")
            return None
        s = full(con, now, log, call)
        store.kv(con, "noc_ts", str(now))
        con.commit()
        for ln in report.lines(con, now):
            log(ln)
        if s.get("javno"):   # 15.11.: the public pages and the app tab show the night's numbers from the next view
            from makroinf import web
            log(web.refreshed_line(*s["javno"]))
        return s
    finally:
        con.close()


GUESS_CAT = racuni.GUESS_CAT


def expand(con, c=None, force=False, who=None, now=None, get=None, log=print, target=None, twapi_usd=None,
           openai_usd=None):
    """The expansion to `expand_n` accounts: refuses unless the quality check passed (or the owner forces it). Finds
    candidates among the accounts the active ones follow (twitterapi followings, one page each), 100k+ followers,
    followed by 3+ of ours; adds them as source prosirenje (backfill and classification under their own caps).
    Returns (ok, text)."""
    import re as _re
    c = c or store.config()
    now = int(now or time.time())
    if force:
        quality.force(con, who or "vlasnik", now)
    why = quality.gate(con)
    if why:
        return False, f"proširenje odbijeno: {why}. Vlasnik može forsirati: run_makroinf.py prosiri --vlasnik-forsira"
    target = int(target or c["expand_n"])
    have = len(racuni.active(con, include_new=True))
    if have >= target:
        return False, f"već {have} računa (cilj {target})"
    store.kv(con, "prosirenje", {"ts": now, "twapi_usd": float(twapi_usd or c["expand_twapi_usd"]),
                                 "openai_usd": float(openai_usd or c["expand_openai_usd"]), "who": who or "vlasnik"})
    if not xapi.has_key(get):
        con.commit()
        return False, "nema TWITTERAPI_IO_KEY"
    cnt, info = {}, {}
    known = {h.lower() for (h,) in store.q(con, "SELECT handle FROM accounts")}
    for h, _cat, _src in racuni.active(con):
        try:
            fl = xapi.followings(con, h, "prosirenje", c, now, get)
        except xapi.CapReached:
            break
        except Exception:  # noqa: BLE001
            continue
        for u in fl:
            hh = u.get("userName") or u.get("screen_name")
            if not hh or hh.lower() in known:
                continue
            cnt[hh] = cnt.get(hh, 0) + 1
            info[hh] = u
    cands = [h for h, k in sorted(cnt.items(), key=lambda kv: -kv[1]) if k >= 3]
    added = 0
    for h in cands:
        if have + added >= target:
            break
        u = info[h]
        fol = racuni._f(u, "followers", "followersCount", "followers_count")
        if fol is not None and fol < int(c["min_followers"]):
            continue
        bio = u.get("description") or ""
        cat = next((k for k, pat in GUESS_CAT if _re.search(pat, bio, _re.I)), "ta")
        con.execute("INSERT OR IGNORE INTO accounts (handle, name, category, source, status, owner_seed, added_ts, note) "
                    "VALUES (?,?,?,?,?,?,?,?)", (h, u.get("name") or h, cat, "prosirenje", "novo", 0, now,
                                                 f"prati ga {cnt[h]} naših računa; kategorija iz opisa (Pretpostavka)"))
        added += 1
    con.commit()
    log(store.PREFIX + f"proširenje: dodano {added} kandidata (prati ih 3+ naših računa), cilj {target}; dohvat i "
                       f"klasifikacija pod stropom proširenja")
    return True, f"dodano {added} računa za proširenje"
