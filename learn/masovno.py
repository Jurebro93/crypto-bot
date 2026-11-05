"""5.11.: the mass shadow book ("masovna sjenovita knjiga"): thousands of invisible trades a day, the real source of
learning. Demo trades are the shop window; this is the classroom.

Decision points (shadow.db points, same table as learn/shadow.py) come from the token filter Nicholas set:
  bondao          a pump.fun token that graduated to PumpSwap (hype.db live_launches, pool 'migration')
  trending        GeckoTerminal trending / DexScreener boosts (kol.db trending)
  kol_poziv       first call of the day on a token by a non-bot account (kol.db calls)
  novcanik_kupio  first buy of the day of a token by a followed wallet (hype.db chain_trades)
  kontrola        a random token the scanner saw at >= 30k mcap (the baseline every rule is judged against)
and, at night (01-06 Europe/Zagreb), history: calls up to history_days back and buys of our best wallets.
Never: fresh pump.fun launches before bonding, tokens under 30k, majors.

The price path comes from GeckoTerminal 5-min candles (kol/measure.ohlcv), which costs API calls: a run gets a
budget (day / night). Every point is replayed with the class's live exit rules (learn/shadow.simulate) AND with the
fixed exit variants below, so one token answers "which exit works for this kind of entry" (points.varijante).
"""
import datetime as dt
import json
import random
import sqlite3
import time

from learn import shadow

ROOT = shadow.ROOT
KOL_DB = __import__("os").path.join(ROOT, "kol.db")
WALLETS_DB = __import__("os").path.join(ROOT, "wallets.db")
DEFAULT = {"enabled": True, "min_mcap": 30000, "min_liq": 15000, "horizon_h": 24, "per_run_day": 300, "per_run_night": 500,
           "night": [1, 6], "history_days": 180, "history_per_night": 1200, "kontrola_per_day": 40,
           "max_points_per_source_day": 600}
VARIANTS = {
    "brzi": {"sl": -0.10, "trail_after": 0.10, "trail": 0.15, "max_hold_h": 6, "tp": [[0.5, 0.5]]},
    "srednji": {"sl": -0.20, "trail_after": 0.30, "trail": 0.25, "max_hold_h": 24},
    "spori": {"sl": -0.35, "trail_after": 0.50, "trail": 0.30, "max_hold_h": 24},
    "sat": {"sl": -0.50, "max_hold_h": 1, "tp": [], "trail_after": 9.0},
    "ljestvica": {"sl": -0.25, "tp": [[0.3, 0.34], [1.0, 0.33], [3.0, 0.33]], "trail_after": 3.0},
}
SOURCES = ("bondao", "trending", "kol_poziv", "novcanik_kupio", "kontrola", "povijest_poziv", "povijest_novcanik",
           "povijest_bondao")
MIGRATE = [("points", "varijante", "TEXT"), ("points", "izvor_detalj", "TEXT")]


def config():
    from learn import outcomes
    return {**DEFAULT, **(outcomes.config().get("masovno") or {})}


def connect(path=None):
    con = shadow.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(points)")}
    for table, col, typ in MIGRATE:
        if col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    con.commit()
    return con


def is_night(now=None, cfg=None):
    """01:00-06:00 Europe/Zagreb: the window for history and other heavy, uninterruptible work (Nicholas 5.11.)."""
    import zoneinfo
    c = cfg or config()
    t = dt.datetime.fromtimestamp(now or time.time(), zoneinfo.ZoneInfo("Europe/Zagreb"))
    return c["night"][0] <= t.hour < c["night"][1]


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _add(con, pid, token, point, ts, symbol=None, detail=None, feats=None):
    cur = con.execute(
        "INSERT OR IGNORE INTO points (id, token, symbol, point, ts, sess, features, status, izvor_detalj) "
        "VALUES (?,?,?,?,?,?,?,'ceka',?)",
        (pid, token, symbol, point, int(ts), shadow._session(ts), json.dumps(feats or {}), detail))
    return cur.rowcount


def collect(con, now=None, cfg=None, hype_db=None, kol_db=None):
    """Today's points from the five live sources. Idempotent (id = point:token:day). Returns {point: n}."""
    cfg = cfg or config()
    now = now or int(time.time())
    since = now - 36 * 3600
    skip = _majors()
    new = {}
    cap = cfg["max_points_per_source_day"]

    def put(point, token, ts, symbol=None, detail=None, feats=None):
        if not token or token in skip or new.get(point, 0) >= cap:
            return
        if _add(con, f"{point}:{token}:{_day(ts)}", token, point, ts, symbol, detail, feats):
            new[point] = new.get(point, 0) + 1

    h = shadow._ro(hype_db or shadow.HYPE_DB)
    if h is not None:
        try:
            for mint, ts, sym in h.execute("SELECT mint, MIN(ts), symbol FROM live_launches WHERE pool='migration' AND ts>=? "
                                           "GROUP BY mint", (since,)):
                put("bondao", mint, ts, sym, "bondao")
            try:
                followed = set(_followed())
                for mint, ts, w in h.execute("SELECT mint, MIN(ts), wallet FROM chain_trades WHERE side='buy' AND ts>=? "
                                             "GROUP BY mint", (since,)):
                    if not followed or w in followed:
                        put("novcanik_kupio", mint, ts, None, w[:8], {"novcanik": w})
            except sqlite3.OperationalError:
                pass
            # control: random tokens the scanner saw today at >= min_mcap (first sighting), the baseline
            rows = h.execute("SELECT token, MIN(ts), symbol, mcap, liquidity FROM hype_signals WHERE ts>=? AND "
                             "COALESCE(mcap,0)>=? GROUP BY token", (since, cfg["min_mcap"])).fetchall()
            random.Random(int(now // 86400)).shuffle(rows)
            for token, ts, sym, mcap, liq in rows[:cfg["kontrola_per_day"]]:
                put("kontrola", token, ts, sym, "nasumično", {"mcap0": mcap, "liq0": liq})
        except sqlite3.OperationalError as e:
            print(f"masovno: hype.db: {e}")
        finally:
            h.close()
    k = shadow._ro(kol_db or KOL_DB)
    if k is not None:
        try:
            try:
                for token, ts, sym, vol in k.execute("SELECT token, MIN(first_ts), symbol, MAX(vol24) FROM trending "
                                                     "WHERE first_ts>=? GROUP BY token", (since,)):
                    put("trending", token, ts, sym, "trending", {"vol24": vol})
            except sqlite3.OperationalError:
                pass
            for token, ts, handle, sym, foll, score in k.execute(
                    "SELECT c.token, MIN(c.ts), c.handle, c.symbol, c.followers, k.score FROM calls c "
                    "LEFT JOIN kols k ON k.handle=c.handle WHERE c.kind='call' AND c.ts>=? AND COALESCE(k.bot,0)=0 "
                    "AND c.handle NOT LIKE 'w:%' GROUP BY c.token", (since,)):
                put("kol_poziv", token, ts, sym, handle, {"kol_score": score, "followers": foll})
        except sqlite3.OperationalError as e:
            print(f"masovno: kol.db: {e}")
        finally:
            k.close()
    con.commit()
    return new


def history(con, now=None, cfg=None, kol_db=None, wallets_db=None, limit=None):
    """Night only: old calls (history_days back) and buys of our best wallets as points, oldest-unseen first.
    Returns the number added."""
    cfg = cfg or config()
    now = now or int(time.time())
    limit = limit or cfg["history_per_night"]
    since = now - cfg["history_days"] * 86400
    skip = _majors()
    n = 0
    k = shadow._ro(kol_db or KOL_DB)
    if k is not None:
        try:
            for token, ts, handle, sym, foll, score in k.execute(
                    "SELECT c.token, MIN(c.ts), c.handle, c.symbol, c.followers, k.score FROM calls c "
                    "LEFT JOIN kols k ON k.handle=c.handle WHERE c.kind='call' AND c.ts>=? AND c.ts<? AND COALESCE(k.bot,0)=0 "
                    "AND c.handle NOT LIKE 'w:%' GROUP BY c.token ORDER BY MIN(c.ts) DESC", (since, now - 36 * 3600)):
                if token in skip:
                    continue
                if _add(con, f"povijest_poziv:{token}:{_day(ts)}", token, "povijest_poziv", ts, sym, handle,
                        {"kol_score": score, "followers": foll}):
                    n += 1
                if n >= limit:
                    break
        except sqlite3.OperationalError as e:
            print(f"masovno: kol.db povijest: {e}")
        finally:
            k.close()
    if n < limit:   # graduated pump.fun tokens (kol.db graduates): entry = the graduation moment
        k = shadow._ro(kol_db or KOL_DB)
        if k is not None:
            try:
                from kol import graduates
                for token, pool, cts, sym, fdv in graduates.tokens(k, since_ts=since, limit=limit * 3):
                    if token in skip or not cts or cts >= now - 36 * 3600:
                        continue
                    if _add(con, f"povijest_bondao:{token}:{_day(cts)}", token, "povijest_bondao", cts, sym, "bondao",
                            {"fdv_now": fdv}):
                        n += 1
                    if n >= limit:
                        break
            except Exception as e:  # noqa: BLE001
                print(f"masovno: graduates: {e}")
            finally:
                k.close()
    if n < limit:
        w = shadow._ro(wallets_db or WALLETS_DB)
        if w is not None:
            try:
                for wallet, ts, mint in w.execute(
                        "SELECT t.wallet, MIN(t.ts), t.mint FROM wallet_trades t JOIN wallets w ON w.wallet=t.wallet "
                        "WHERE t.kind='buy' AND t.ts>=? AND t.ts<? AND w.tier IN ('A','B','S') GROUP BY t.mint "
                        "ORDER BY MIN(t.ts) DESC", (since, now - 36 * 3600)):
                    if mint in skip:
                        continue
                    if _add(con, f"povijest_novcanik:{mint}:{_day(ts)}", mint, "povijest_novcanik", ts, None, wallet[:8],
                            {"novcanik": wallet}):
                        n += 1
                    if n >= limit:
                        break
            except sqlite3.OperationalError as e:
                print(f"masovno: wallets.db: {e}")
            finally:
                w.close()
    con.commit()
    return n


def _followed():
    k = shadow._ro(KOL_DB)
    if k is None:
        return []
    try:
        r = k.execute("SELECT value FROM kv WHERE key='chain_hook'").fetchone()
        return (json.loads(r[0]).get("wallets") or []) if r else []
    except (sqlite3.OperationalError, ValueError):
        return []
    finally:
        k.close()


def _majors():
    try:
        from kol import converge
        return set(converge.majors())
    except Exception:  # noqa: BLE001
        return set()


def _pool_for(token, kol_db=None):
    """Pool address for the candles: kol.db tokens.pair, else one GeckoTerminal lookup."""
    k = shadow._ro(kol_db or KOL_DB)
    if k is not None:
        try:
            r = k.execute("SELECT pair, liquidity FROM tokens WHERE token=?", (token,)).fetchone()
            if r and r[0]:
                return r[0], r[1]
        except sqlite3.OperationalError:
            pass
        finally:
            k.close()
    from kol import measure
    p = measure.gecko_pool(token)
    return (p["address"], p.get("liquidity")) if p else (None, None)


def candles_path(token, ts, horizon_s, fetch=None, pool_for=None):
    """[(ts, price, liq)] from 5-min candles after ts, and the entry price (close of the first candle at/after ts).
    (None, None, calls_used) when the token has no pool or no candles."""
    pool, liq = (pool_for or _pool_for)(token)
    calls = 1
    if not pool:
        return None, None, calls
    from kol import measure
    try:
        rows = (fetch or measure.ohlcv)(pool, ts - 300, ts + horizon_s)
    except Exception:  # noqa: BLE001
        rows = []
    calls += 1
    rows = [c for c in rows if c[0] >= ts - 300]
    if not rows:
        return None, None, calls
    entry = rows[0][4]
    path = [(c[0] + 300, c[4], liq or 0) for c in rows if c[0] + 300 > ts]
    return path, entry, calls


def label(con, now=None, cfg=None, budget=None, fetch=None, pool_for=None, base=None):
    """Replay due points of this module's sources whose horizon has passed, within `budget` GeckoTerminal calls.
    Returns (labelled, calls_used)."""
    from paper import sim
    cfg = cfg or config()
    now = now or int(time.time())
    budget = budget if budget is not None else (cfg["per_run_night"] if is_night(now, cfg) else cfg["per_run_day"])
    horizon_s = cfg["horizon_h"] * 3600
    q = ",".join("?" * len(SOURCES))
    due = con.execute(f"SELECT * FROM points WHERE status='ceka' AND point IN ({q}) AND ts <= ? ORDER BY ts DESC LIMIT ?",
                      (*SOURCES, now - horizon_s, max(1, budget // 2))).fetchall()
    base = base or sim.load_config()
    done = used = 0
    for r in due:
        if used >= budget:
            break
        path, entry, calls = candles_path(r["token"], r["ts"], horizon_s, fetch, pool_for)
        used += calls
        if not path or not entry:
            con.execute("UPDATE points SET status='bez_cijene', labeled_ts=? WHERE id=?", (int(now), r["id"]))
            continue
        path = shadow.clean(path, shadow.config()["spike_x"])
        liq = path[0][2] if path else 0
        res, prof = shadow.simulate(entry, liq, r["ts"], path, r["klasa"] or "default", "snap", base)
        var = {}
        for name, over in VARIANTS.items():
            cfg_v = {**base, **over, "coarse": {"secs": 300, **__import__("exits.fit", fromlist=["COARSE_DEFAULT"]).COARSE_DEFAULT}}
            try:
                var[name] = round(sim.replay(entry, liq, r["ts"], path, cfg_v)["ret"], 4)
            except Exception:  # noqa: BLE001
                var[name] = None
        rets = sorted(p / entry - 1 for _, p, _ in path)
        max2 = rets[-2] if len(rets) >= 2 else rets[-1]
        hit = int(res["ret"] >= shadow.config()["hit_ret"])
        con.execute("UPDATE points SET status='gotovo', src='gecko', price=?, liq=?, n_pts=?, ret=?, max2_ret=?, min_ret=?, "
                    "hit=?, rug=0, exit_reason=?, exit_profile=?, varijante=?, path=?, labeled_ts=? WHERE id=?",
                    (entry, liq, len(path), res["ret"], round(max2, 4), round(rets[0], 4), hit, res["exit_reason"], prof,
                     json.dumps(var), json.dumps(shadow._compress(entry, r["ts"], path)), int(now), r["id"]))
        done += 1
    con.commit()
    return done, used


def run(path=None, now=None, budget=None, fetch=None, pool_for=None):
    """One pass: today's points, history at night, labels within the API budget. Returns a summary dict."""
    cfg = config()
    now = now or int(time.time())
    con = connect(path)
    try:
        if not cfg.get("enabled", True):
            return {"enabled": False}
        new = collect(con, now, cfg)
        hist = history(con, now, cfg) if is_night(now, cfg) else 0
        done, used = label(con, now, cfg, budget, fetch, pool_for)
        shadow._set_kv(con, "masovno_last", {"ts": now, "new": new, "history": hist, "labeled": done, "calls": used})
        con.commit()
        return {"new": new, "history": hist, "labeled": done, "calls": used, "night": is_night(now, cfg)}
    finally:
        con.close()


def stats(path=None, days=7, now=None):
    """[{point, n, hit, avg, med, pf, var: {name: avg}}] over labelled points of the last `days`, plus kontrola."""
    now = now or time.time()
    con = shadow._ro(path or shadow.DB)
    if con is None:
        return []
    out = []
    try:
        q = ",".join("?" * len(SOURCES))
        rows = con.execute(f"SELECT point, ret, hit, varijante FROM points WHERE status='gotovo' AND point IN ({q}) AND ts>=?",
                           (*SOURCES, int(now - days * 86400))).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    by = {}
    for point, ret, hit, var in rows:
        by.setdefault(point, []).append((ret or 0, hit or 0, json.loads(var or "{}")))
    for point, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        rets = sorted(x[0] for x in xs)
        wins = sum(r for r in rets if r > 0)
        loss = -sum(r for r in rets if r < 0)
        var = {}
        for name in VARIANTS:
            vs = [x[2].get(name) for x in xs if x[2].get(name) is not None]
            var[name] = round(sum(vs) / len(vs), 4) if vs else None
        out.append({"point": point, "n": len(xs), "hit": sum(x[1] for x in xs) / len(xs), "avg": sum(rets) / len(rets),
                    "med": rets[len(rets) // 2], "pf": (wins / loss) if loss else None, "var": var})
    return out


def stats_html(path=None, days=7, now=None):
    """Admin box for /usage: invisible trades per source, each exit variant, against kontrola."""
    from ui.html import esc
    rows = stats(path, days, now)
    if not rows:
        return ("<h2 id=masovno>Nevidljivi tradeovi</h2><p class=mut>Još nema označenih točaka iz masovne sjenovite knjige "
                "(prvi rezultati 24 h nakon prvog kruga).</p>")
    ctrl = next((r for r in rows if r["point"] == "kontrola"), None)
    names = {"bondao": "bondao (pump.fun → PumpSwap)", "trending": "trending", "kol_poziv": "KOL poziv",
             "novcanik_kupio": "praćeni novčanik kupio", "kontrola": "kontrola (nasumično)",
             "povijest_poziv": "povijest: pozivi", "povijest_novcanik": "povijest: novčanici",
             "povijest_bondao": "povijest: bondani tokeni"}
    head = "".join(f"<th>{v}</th>" for v in VARIANTS)
    body = []
    for r in rows:
        vs = "".join(f"<td class={'pos' if (v or 0) > 0 else 'neg'}>{v:+.1%}</td>" if v is not None else "<td>–</td>"
                     for v in r["var"].values())
        diff = (f" <small class={'pos' if r['avg'] > ctrl['avg'] else 'neg'}>({r['avg'] - ctrl['avg']:+.1%} vs kontrola)</small>"
                if ctrl and r["point"] != "kontrola" else "")
        body.append(f"<tr><td>{esc(names.get(r['point'], r['point']))}</td><td class=n>{r['n']:,}</td><td>{r['hit']:.0%}</td>"
                    f"<td class={'pos' if r['avg'] > 0 else 'neg'}>{r['avg']:+.1%}{diff}</td><td>{r['med']:+.1%}</td>"
                    f"<td>{(r['pf'] or 0):.2f}</td>{vs}</tr>")
    return ("<h2 id=masovno>Nevidljivi tradeovi (masovna sjenovita knjiga)</h2>"
            f"<p class=mut>Zadnjih {days} dana: svaki token iz filtera (bondao, trending, KOL poziv, praćeni novčanik, povijest) "
            "odigran s pravilima izlaza demo bota (stupci n, pogodak, prosjek, medijan, PF) i s fiksnim varijantama izlaza "
            "(zadnji stupci, prosječni povrat). Kontrola = nasumični token iz skena; pravilo vrijedi samo ako tuče kontrolu. "
            "Korisnici ovo ne vide.</p>"
            "<table class=t><tr><th>izvor</th><th>n</th><th>pogodak</th><th>prosjek</th><th>medijan</th><th>PF</th>"
            f"{head}</tr>{''.join(body)}</table>")
