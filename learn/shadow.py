"""Shadow book: a virtual demo trade at every decision point, so learning sees ~20-50x more examples than the real
demo book and also learns from the tokens we did not buy.

A decision point is a moment the bot could have bought: the first signal of a token (hype scan), the first crossing
of $100k / $1M market cap (tiers tier_events) and every paper-trading candidate (taken or skipped, with its
decision). The features are the ones stored at that moment (hype_signals / tier_events / candidates keep them as
they were then), copied once into shadow.db, so nothing measured later can leak into a lesson.

After the horizon has passed, the point is labelled by replaying its price path through paper/sim.py with the exit
rules the class would trade with (exits/profiles.py), the same code the demo trades with: `ret` is the return the
bot could actually have taken, after fees, slippage and price impact. A path comes from the paper minute ticks when
the token has them, else from the coarser hype snapshots (then a stop fills where the minute checks would have
caught it, sim coarse). Single bogus prints (one point 3x above both neighbours, see dexscreener.client.sane) are
dropped before the replay, so a fake price never becomes a "winner".

Labelled points are also appended to one gzip JSON-lines file per day (DATA_DIR/shadow/YYYY-MM-DD.jsonl.gz):
the point-in-time snapshot later models and backtests train on.

shadow.db has one writer: this module (run_learn.py shadow, hourly from run_sched). Everything else reads it.
"""
import gzip
import json
import os
import sqlite3
import statistics
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "shadow.db")
HYPE_DB = os.path.join(ROOT, "hype.db")
PAPER_DB = os.path.join(ROOT, "paper.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS points (
    id TEXT PRIMARY KEY, token TEXT, symbol TEXT, point TEXT, ts INTEGER, klasa TEXT, sess TEXT,
    price REAL, liq REAL, mcap REAL, score REAL, decision TEXT, kupljeno INTEGER, features TEXT,
    status TEXT DEFAULT 'ceka', src TEXT, n_pts INTEGER, ret REAL, max2_ret REAL, min_ret REAL, hit INTEGER,
    rug INTEGER, exit_reason TEXT, exit_profile TEXT, path TEXT, labeled_ts INTEGER);
CREATE INDEX IF NOT EXISTS points_status ON points (status, ts);
CREATE INDEX IF NOT EXISTS points_point ON points (point, ts);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
POINTS = {"prvi_signal": "prvi signal", "mc100k": "prelazak $100k", "mc1m": "prelazak $1M", "kandidat": "demo kandidat"}
EVENT_POINT = {"B100000": "mc100k", "B1000000": "mc1m"}
DEFAULT = {"horizon_h": 24, "hit_ret": 0.10, "min_ticks": 5, "max_new": 20000, "max_label": 4000,
           "lookback_h": 72, "spike_x": 3.0, "rug_liq": 0.2, "keep_days": 30, "export": True}


def config():
    from learn import outcomes
    return {**DEFAULT, **(outcomes.config().get("shadow") or {})}


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    return con


def _kv(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default


def _set_kv(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))


def _klasa(tiers, token, mcap, origin=None):
    from tiers import classify
    if origin == "event":
        return "event"
    return tiers.get(token) or classify.klasa(mcap, None)


def _session(ts):
    from exits import paths
    return paths.session_of(ts)


# ---------------------------------------------------------------- collect

def collect(con, hype_db=HYPE_DB, paper_db=PAPER_DB, now=None, cfg=None):
    """Copy new decision points (with their features as they were) into shadow.db. Idempotent: id = point:token
    (a candidate keeps its own id), INSERT OR IGNORE. Returns {point: n_new}."""
    cfg = cfg or config()
    now = now or time.time()
    since = now - cfg["lookback_h"] * 3600
    new = {}
    h = _ro(hype_db)
    tiers = {}
    if h is not None:
        try:
            tiers = dict(h.execute("SELECT token, klasa FROM token_tier WHERE klasa IS NOT NULL"))
        except sqlite3.OperationalError:
            tiers = {}

    def add(pid, token, symbol, point, ts, price, liq, mcap, score, feats, decision=None, kupljeno=0, origin=None):
        if not price or price <= 0 or sum(new.values()) >= cfg["max_new"]:
            return
        cur = con.execute(
            "INSERT OR IGNORE INTO points (id, token, symbol, point, ts, klasa, sess, price, liq, mcap, score, decision, "
            "kupljeno, features) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, token, symbol, point, int(ts), _klasa(tiers, token, mcap, origin), _session(ts), price, liq, mcap,
             score, decision, int(bool(kupljeno)), feats if isinstance(feats, str) else json.dumps(feats or {})))
        if cur.rowcount:
            new[point] = new.get(point, 0) + 1

    if h is not None:
        try:
            for token, symbol, ts, price, mcap, liq, score, feats in h.execute(
                    "SELECT s.token, s.symbol, s.ts, s.price, s.mcap, s.liquidity, s.score, s.features FROM hype_signals s "
                    "JOIN (SELECT token, MIN(ts) ts FROM hype_signals GROUP BY token) f ON s.token=f.token AND s.ts=f.ts "
                    "WHERE s.ts >= ?", (since,)):
                add(f"prvi_signal:{token}", token, symbol, "prvi_signal", ts, price, liq, mcap, score, feats)
            sym = {}
            for token, point, ts, mcap, price, score, feats in h.execute(
                    "SELECT token, point, ts, mcap, price, score, features FROM tier_events WHERE ts >= ?", (since,)):
                p = EVENT_POINT.get(point)
                if not p:
                    continue
                # liquidity as known AT the event (audit 4.11. C06: was the newest value, also from after it)
                r = h.execute("SELECT symbol, liquidity FROM hype_signals WHERE token=? AND ts<=? ORDER BY ts DESC "
                              "LIMIT 1", (token, ts)).fetchone() or (None, None)
                add(f"{p}:{token}", token, r[0], p, ts, price, r[1], mcap, score, feats)
        except sqlite3.OperationalError as e:
            print(f"shadow: hype.db: {e}")
        finally:
            h.close()
    p = _ro(paper_db)
    if p is not None:
        try:
            for token, symbol, ts, origin, score, feats, price, liq, mcap, decision, trade_id in p.execute(
                    "SELECT token, symbol, first_ts, origin, score, features, price, liquidity, mcap, decision, trade_id "
                    "FROM candidates WHERE first_ts >= ? AND decision != 'ignored'", (since,)):
                add(f"kandidat:{token}", token, symbol, "kandidat", ts, price, liq, mcap, score, feats, decision,
                    trade_id is not None, origin)
            # trigger evaluations (paper/store.trigger_points, 4.11.): one point per look, so a comeback after a loss
            # ("povratak") or a second $100k crossing is its own lesson, bought or not
            for token, ts, mode, symbol, score, feats, price, liq, mcap, decision, trade_id in p.execute(
                    "SELECT token, ts, mode, symbol, score, features, price, liquidity, mcap, decision, trade_id "
                    "FROM trigger_points WHERE ts >= ?", (since,)):
                add(f"{mode}:{token}:{ts}", token, symbol, mode, ts, price, liq, mcap, score, feats, decision,
                    trade_id is not None, mode)
        except sqlite3.OperationalError as e:
            print(f"shadow: paper.db: {e}")
        finally:
            p.close()
    con.commit()
    return new


# ---------------------------------------------------------------- label

def clean(path, spike_x=3.0):
    """Drop single bogus prints: a point spike_x above (or below 1/spike_x of) BOTH neighbours. A real pump has a
    neighbour near it; one dust print or a wrong DexScreener price does not (pairless 1.11.: one 70x reading)."""
    out = []
    for i, (ts, price, liq) in enumerate(path):
        if not price or price <= 0:
            continue
        prev = path[i - 1][1] if i > 0 else None
        nxt = path[i + 1][1] if i + 1 < len(path) else None
        if prev and nxt and prev > 0 and nxt > 0:
            if price > spike_x * prev and price > spike_x * nxt:
                continue
            if price * spike_x < prev and price * spike_x < nxt:
                continue
        out.append((ts, price, liq))
    return out


def _path(token, ts, horizon_s, paper, hype, min_ticks):
    """(src, [(ts, price, liq)]): paper minute ticks when there are enough of them, else hype snapshots."""
    if paper is not None:
        rows = paper.execute("SELECT ts, price, liquidity FROM ticks WHERE token=? AND ts>? AND ts<=? ORDER BY ts",
                             (token, ts, ts + horizon_s)).fetchall()
        if len(rows) >= min_ticks:
            return "tick", rows
    if hype is not None:
        rows = hype.execute("SELECT ts, price, liquidity FROM hype_snapshots WHERE token=? AND ts>? AND ts<=? ORDER BY ts",
                            (token, ts, ts + horizon_s)).fetchall()
        if rows:
            return "snap", rows
    return None, []


def _compress(entry, ts0, path, max_points=100):
    """[(seconds after entry, price/entry, liquidity)] thinned like exits/paths.compress: every move over 3%, every
    new high and LOW (the dips decide where a stop loss should sit) and the last point. Exit learning
    (exits/fit, stop loss table on Učenje) replays these paths."""
    from exits import paths as epaths
    return epaths.compress([(t - ts0, p / entry, liq) for t, p, liq in path if p], 0.03, max_points)


def exit_paths(since, skip_tokens=(), path=None, points=("kandidat", "mc100k")):
    """Labelled points as exit-learning paths (exits/paths format, src 'shadow'), one per token and point type;
    kol=True when an influencer signal was present at the decision."""
    con = _ro(path or DB)
    if con is None:
        return []
    out, seen = [], set(skip_tokens)
    try:
        q = ",".join("?" * len(points))
        for token, ts, point, klasa, liq, mcap, pth, feats in con.execute(
                f"SELECT token, ts, point, klasa, liq, mcap, path, features FROM points WHERE status='gotovo' "
                f"AND ts>=? AND point IN ({q}) AND path IS NOT NULL ORDER BY ts", (int(since), *points)):
            if (token, point) in seen or token in seen:
                continue
            seen.add((token, point))
            try:
                pts = json.loads(pth or "[]")
                f = json.loads(feats or "{}")
            except ValueError:
                continue
            if len(pts) < 3:
                continue
            liq0 = liq or 0
            pts = [(int(x[0]), float(x[1]), float(x[2]) if len(x) > 2 and x[2] else liq0) for x in pts]
            kol = any((f.get(k) or 0) > 0 for k in ("kol_x", "kol_group", "kol_wallets"))
            out.append({"src": "shadow", "klasa": klasa or "default", "ts": int(ts), "liq0": round(liq0),
                        "mcap0": round(mcap or 0), "pts": pts, "token": token, "point": point, "kol_sig": kol})
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return out


def simulate(price, liq, ts, path, klasa, src, base=None):
    """paper/sim replay with the exit rules the class trades with now; coarse stop fill on snapshot paths."""
    from exits import fit as efit, profiles
    from paper import sim
    base = base or sim.load_config()
    cfg = profiles.for_trade(base, klasa, now=ts)
    if src == "snap":
        cfg = {**cfg, "coarse": {"secs": 300, **efit.COARSE_DEFAULT}}
    else:
        cfg = {k: v for k, v in cfg.items() if k != "coarse"}
    res = sim.replay(price, liq or 0, ts, path, cfg)
    return res, cfg.get("exit_profile") or "paper/config.json"


def label(con, hype_db=HYPE_DB, paper_db=PAPER_DB, now=None, cfg=None):
    """Label every point whose horizon has passed. Returns the number labelled and writes the day's snapshot file."""
    from paper import sim
    cfg = cfg or config()
    now = now or time.time()
    horizon_s = cfg["horizon_h"] * 3600
    due = con.execute("SELECT * FROM points WHERE status='ceka' AND ts <= ? ORDER BY ts LIMIT ?",
                      (now - horizon_s, cfg["max_label"])).fetchall()
    if not due:
        return 0
    paper, hype = _ro(paper_db), _ro(hype_db)
    from learn import postai
    ai = _ro(postai.DB)  # AI labels of posts written BEFORE the point (learn/postai.py), joined into its features
    base = sim.load_config()
    done, export = 0, []
    try:
        for r in due:
            src, raw = _path(r["token"], r["ts"], horizon_s, paper, hype, cfg["min_ticks"])
            path = clean(raw, cfg["spike_x"])
            if not path or not r["price"]:   # 5.11.: a point saved without a price crashed the whole hourly run
                con.execute("UPDATE points SET status='bez_cijene', labeled_ts=? WHERE id=?", (int(now), r["id"]))
                continue
            feats = json.loads(r["features"] or "{}")
            if ai is not None:
                extra = postai.features(r["token"], r["ts"], con=ai)
                if extra:
                    feats.update(extra)
                    con.execute("UPDATE points SET features=? WHERE id=?", (json.dumps(feats), r["id"]))
            res, prof = simulate(r["price"], r["liq"], r["ts"], path, r["klasa"], src, base)
            rets = sorted(p / r["price"] - 1 for _, p, _ in path)
            max2 = rets[-2] if len(rets) >= 2 else rets[-1]
            liq_end = path[-1][2] or 0
            rug = int(bool(r["liq"]) and liq_end < cfg["rug_liq"] * r["liq"])
            hit = int(res["ret"] >= cfg["hit_ret"])
            comp = _compress(r["price"], r["ts"], path)
            con.execute("UPDATE points SET status='gotovo', src=?, n_pts=?, ret=?, max2_ret=?, min_ret=?, hit=?, rug=?, "
                        "exit_reason=?, exit_profile=?, path=?, labeled_ts=? WHERE id=?",
                        (src, len(path), res["ret"], round(max2, 4), round(rets[0], 4), hit, rug, res["exit_reason"],
                         prof, json.dumps(comp), int(now), r["id"]))
            done += 1
            export.append({**{k: r[k] for k in ("id", "token", "symbol", "point", "ts", "klasa", "sess", "price", "liq",
                                                 "mcap", "score", "decision", "kupljeno")},
                           "features": feats, "src": src, "ret": res["ret"],
                           "max2_ret": round(max2, 4), "hit": hit, "rug": rug, "exit_reason": res["exit_reason"],
                           "exit_profile": prof, "path": comp})
    finally:
        for c in (paper, hype, ai):
            if c is not None:
                c.close()
    con.commit()
    if cfg["export"] and export:
        _export(export, now)
    return done


def export_dir():
    return os.path.join(os.environ.get("DATA_DIR") or ROOT, "shadow")


def _export(rows, now):
    """Append to today's gzip JSON-lines file (gzip members concatenate, so appending is safe)."""
    try:
        d = export_dir()
        os.makedirs(d, exist_ok=True)
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with gzip.open(os.path.join(d, f"{day}.jsonl.gz"), "at", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"shadow: izvoz nije uspio: {e}")


def prune(con, now=None, cfg=None):
    """Points older than keep_days go (the daily export files keep them); unlabelled points that never got a price
    in 3 horizons are marked bez_cijene."""
    cfg = cfg or config()
    now = now or time.time()
    n = con.execute("DELETE FROM points WHERE ts < ?", (now - cfg["keep_days"] * 86400,)).rowcount
    con.execute("UPDATE points SET status='bez_cijene' WHERE status='ceka' AND ts < ?", (now - 3 * cfg["horizon_h"] * 3600,))
    con.commit()
    return n


def run(path=None, hype_db=HYPE_DB, paper_db=PAPER_DB, now=None):
    """One hourly pass: collect new points, label the due ones, prune. Returns a summary dict."""
    cfg = config()
    con = connect(path)
    try:
        new = collect(con, hype_db, paper_db, now, cfg)
        n = label(con, hype_db, paper_db, now, cfg)
        pruned = prune(con, now, cfg)
        _set_kv(con, "last_run", {"ts": int(now or time.time()), "new": new, "labeled": n, "pruned": pruned})
        con.commit()
        return {"new": new, "labeled": n, "pruned": pruned}
    finally:
        con.close()


# ---------------------------------------------------------------- read side

def rows(path=None, point=None, since=None, klasa=None):
    """Labelled points as dicts (features parsed); read-only."""
    con = _ro(path or DB)
    if con is None:
        return []
    con.row_factory = sqlite3.Row
    sql, args = "SELECT * FROM points WHERE status='gotovo'", []
    if point:
        sql += " AND point=?"
        args.append(point)
    if since:
        sql += " AND ts>=?"
        args.append(int(since))
    if klasa:
        sql += " AND klasa=?"
        args.append(klasa)
    try:
        out = []
        for r in con.execute(sql + " ORDER BY ts", args):
            d = dict(r)
            d["features"] = json.loads(d["features"] or "{}")
            d.pop("path", None)
            out.append(d)
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def stats(rs, cap=3.0):
    """Book numbers for a set of labelled points: n, mean (returns capped at +cap so one 50x does not decide),
    median, win share, profit factor, mean without the top 1% (the "one ANSEM" check)."""
    if not rs:
        return {"n": 0}
    ret = [min(cap, r["ret"]) for r in rs]
    wins = sum(x for x in ret if x > 0)
    losses = -sum(x for x in ret if x < 0)
    s = sorted(ret)
    trimmed = s[:max(1, len(s) - max(1, len(s) // 100))] if len(s) >= 20 else s
    return {"n": len(rs), "mean": round(sum(ret) / len(ret), 4), "median": round(statistics.median(ret), 4),
            "win": round(sum(x > 0 for x in ret) / len(ret), 3), "hit": round(sum(r["hit"] for r in rs) / len(rs), 3),
            "pf": round(wins / losses, 2) if losses else None, "mean_trim": round(sum(trimmed) / len(trimmed), 4),
            "rug": round(sum(r["rug"] or 0 for r in rs) / len(rs), 3)}


def light_rows(path=None, since=None, point=None):
    """Only (point, kupljeno, decision, ret, hit, rug) of labelled points: no features, no path. For the dashboard,
    which lives 24/7 (Python keeps the memory a big read once took), so it never parses thousands of JSON blobs."""
    con = _ro(path or DB)
    if con is None:
        return []
    sql, args = "SELECT point, kupljeno, decision, ret, hit, rug, ts FROM points WHERE status='gotovo'", []
    if since:
        sql += " AND ts>=?"
        args.append(int(since))
    if point:
        sql += " AND point=?"
        args.append(point)
    try:
        return [{"point": a, "kupljeno": b, "decision": c, "ret": d, "hit": e, "rug": f, "ts": g}
                for a, b, c, d, e, f, g in con.execute(sql, args)]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def summary(path=None, days=7, now=None):
    """Per point type and bought/not bought over the last `days` days, plus counts by status; for the Učenje page
    and the morning report."""
    now = now or time.time()
    rs = light_rows(path, since=now - days * 86400)
    out = {"days": days, "by_point": {}, "kandidat": {}, "status": {}, "last_run": None}
    for p in POINTS:
        out["by_point"][p] = stats([r for r in rs if r["point"] == p])
    k = [r for r in rs if r["point"] == "kandidat"]
    out["kandidat"] = {"kupljeno": stats([r for r in k if r["kupljeno"]]), "preskoceno": stats([r for r in k if not r["kupljeno"]])}
    con = _ro(path or DB)
    if con is not None:
        try:
            out["status"] = dict(con.execute("SELECT status, COUNT(*) FROM points GROUP BY status").fetchall())
            r = con.execute("SELECT v FROM kv WHERE k='last_run'").fetchone()
            out["last_run"] = json.loads(r[0]) if r else None
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    return out
