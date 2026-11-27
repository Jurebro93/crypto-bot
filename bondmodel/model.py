"""Model vjerojatnosti bondanja (27.11.): podaci, značajke, logistička regresija, walk-forward provjera, spremanje.

Izvor: baza jednokratnog mjerenja (live/pumpmjerenje.py, pump_mjerenje.db u DATA_DIR) i/ili njezine arhive
pump_mjerenje_arhiva_*.json.gz (pišu se prije brisanja baze). Više izvora se spaja po mintu, pa svako novo mjerenje
(isti zapis) model samo produžuje.

Ciljevi (ishod s DexScreenera na kontrolnim točkama +1 h i +12 h; +24 h mjerenje nema):
  bond    token je migrirao (bondan) do +12 h
  30k     najviši viđeni mcap ≥ 30k $ do +12 h (donja granica vrha: trenutni i izvedeni iz promjene cijene m5/h1/h6)
  10k     isto, ≥ 10k $
Uključen je samo token s ishodom +12 h (uzorak mjerenja); DexScreener ga ne zna = nije uspio.

Značajke: samo ono što postoji u trenutku lansiranja (poruka `create`) i ishodi ranijih tokena koji su bili VIĐENI prije
tog trenutka (vrijeme upisa ishoda < vrijeme lansiranja). Rani kupci, isti-slot kupnje i slika/metapodaci se ne
spremaju u mjerenju, pa ih model nema (vidi prijedlog toka u izvještaju).

Provjera: blokovi od BLOCK_S; za blok koji počinje u T model se uči samo na lansiranjima čiji je ishod +12 h upisan
prije T (i lansiranje prije T): ni jedan redak iz testnog razdoblja, ni ishod koji se u T još nije znao.
"""
import bisect
import glob
import gzip
import json
import math
import os
import sqlite3
import time

TARGETS = ("bond", "30k", "10k")
TARGET_NAMES = {"bond": "bondan do +12 h", "30k": "dosegnuo 30k $ do +12 h", "10k": "dosegnuo 10k $ do +12 h"}
BLOCK_S = 6 * 3600
MIN_TRAIN = 500
MIN_TRAIN_POS = 5
L2 = 1.0
NO_BUY_SOL = 0.001
BUSY_S = 600
KEEP_RUNS = 5

FEATURES = ("kupnja_log", "bez_kupnje", "kupnja_velika", "dev_24h_log", "dev_ranijih_s_ishodom_log",
            "dev_ranije_bondao", "dev_ranije_10k", "mayhem", "sezonsko_ime", "sat_sin", "sat_cos", "pool_drugi",
            "guzva_log")
# Opisi za vlasnika (bez formula)
FEATURE_WORDS = {"kupnja_log": "veličina devove vlastite kupnje", "bez_kupnje": "dev nije ništa kupio",
                 "kupnja_velika": "dev kupio više od 2 SOL", "dev_24h_log": "koliko je tokena dev lansirao u 24 h",
                 "dev_ranijih_s_ishodom_log": "koliko devovih ranijih tokena ima poznat ishod",
                 "dev_ranije_bondao": "devov raniji token se već bondao",
                 "dev_ranije_10k": "devov raniji token je već dosegnuo 10k $", "mayhem": "Mayhem Mode",
                 "sezonsko_ime": "sezonsko ime (blagdani)", "sat_sin": "doba dana (1)", "sat_cos": "doba dana (2)",
                 "pool_drugi": "lansiran izvan običnog pump.fun poola",
                 "guzva_log": "koliko je lansiranja bilo u zadnjih 10 min"}


# ---------- podaci ------------------------------------------------------------------------------------------------------

def _data_dir():
    try:
        from ops import disk
        return disk.DATA_DIR
    except Exception:  # noqa: BLE001
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_sources(data_dir=None):
    d = data_dir or _data_dir()
    db = os.environ.get("PUMP_MJERENJE_DB") or os.path.join(d, "pump_mjerenje.db")
    out = sorted(glob.glob(os.path.join(d, "pump_mjerenje_arhiva_*.json.gz")))
    if os.path.exists(db):
        out.append(db)
    return out


def _tables_db(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        out = {"stanje": dict(con.execute("SELECT key, value FROM stanje"))}
        for t in ("launches", "ishod", "imena"):
            cur = con.execute(f"SELECT * FROM {t}")
            cols = [c[0] for c in cur.description]
            out[t] = [dict(zip(cols, r)) for r in cur]
        return out
    finally:
        con.close()


def _tables_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        d = json.load(f)
    out = {"stanje": d.get("stanje") or {}}
    for t in ("launches", "ishod", "imena"):
        x = d.get(t) or {"cols": [], "rows": []}
        out[t] = [dict(zip(x["cols"], r)) for r in x["rows"]]
    return out


def load(sources=None):
    """Spojeni podaci iz svih izvora: (launches {mint: dict}, ishod [dict], imena {mint: dict}, udio po mintu).
    Udio uzorka je po izvoru (stanje 'udio'): token je u uzorku kad mu je u < udio."""
    launches, ishod, imena, seen = {}, {}, {}, []
    for src in sources if sources is not None else default_sources():
        try:
            t = _tables_gz(src) if src.endswith(".gz") else _tables_db(src)
        except (OSError, ValueError, sqlite3.Error, KeyError):
            continue
        seen.append(src)
        rate = float(t["stanje"].get("udio") or 1)
        for r in t["launches"]:
            r = dict(r)
            r["in_sample"] = (r.get("u") if r.get("u") is not None else 0) < rate
            launches.setdefault(r["mint"], r)
        for r in t["ishod"]:
            ishod[(r["mint"], r["k"])] = r
        for r in t["imena"]:
            imena.setdefault(r["mint"], r)
    return launches, list(ishod.values()), imena, seen


def _peak(r):
    return max(r.get("max_mcap_usd") or 0, r.get("mcap_usd") or 0)


def build_rows(launches, ishod, imena):
    """Jedan red po lansiranju s ishodom +12 h: {mint, ts, label_ts, x: {značajka: vrijednost}, y: {cilj: 0/1}}.
    Povijest deva i gužva iz SVIH lansiranja; ishodi ranijih tokena samo kad su upisani prije lansiranja."""
    obs = {}
    for r in ishod:
        if (r.get("found") is None) or r["found"] < 0:
            continue
        obs.setdefault(r["mint"], []).append(r)
    by_dev = {}
    order = sorted(launches.values(), key=lambda r: (r["ts"], r["mint"]))
    for r in order:
        if r.get("creator"):
            by_dev.setdefault(r["creator"], []).append(r)
    # dev events: (ts kada je ishod viđen, bondan?, ≥10k?) po devu
    dev_events = {}
    for dev, ls in by_dev.items():
        ev = []
        for l in ls:
            for o in obs.get(l["mint"], []):
                ev.append((o["ts"], l["mint"], int(bool(o.get("migrated"))), int(_peak(o) >= 10_000)))
        dev_events[dev] = sorted(ev)
    all_ts = [r["ts"] for r in order]
    rows = []
    for r in order:
        if not r.get("in_sample"):
            continue
        os_ = obs.get(r["mint"], [])
        o12 = [o for o in os_ if o["k"] == 12]
        if not o12:
            continue
        ts = int(r["ts"])
        mig = any(o.get("migrated") for o in os_)
        peak = max(_peak(o) for o in os_)
        sol = float(r.get("initial_sol") or 0)
        dev = r.get("creator")
        prior = [l for l in by_dev.get(dev, []) if l["ts"] < ts and l["mint"] != r["mint"]] if dev else []
        n24 = sum(1 for l in prior if l["ts"] >= ts - 86400)
        ev = [e for e in dev_events.get(dev, []) if e[0] < ts and e[1] != r["mint"]] if dev else []
        ev_mints = {e[1] for e in ev}
        hour = (ts % 86400) / 3600
        nm = imena.get(r["mint"]) or {}
        busy = bisect.bisect_left(all_ts, ts) - bisect.bisect_left(all_ts, ts - BUSY_S)
        x = {"kupnja_log": math.log1p(sol), "bez_kupnje": float(sol < NO_BUY_SOL), "kupnja_velika": float(sol > 2),
             "dev_24h_log": math.log1p(n24), "dev_ranijih_s_ishodom_log": math.log1p(len(ev_mints)),
             "dev_ranije_bondao": float(any(e[2] for e in ev)), "dev_ranije_10k": float(any(e[3] for e in ev)),
             "mayhem": float(bool(r.get("mayhem"))), "sezonsko_ime": float(bool(nm.get("tema"))),
             "sat_sin": math.sin(2 * math.pi * hour / 24), "sat_cos": math.cos(2 * math.pi * hour / 24),
             "pool_drugi": float((r.get("pool") or "pump") != "pump"), "guzva_log": math.log1p(busy)}
        rows.append({"mint": r["mint"], "ts": ts, "label_ts": int(min(o["ts"] for o in o12)), "x": x,
                     "y": {"bond": int(mig), "30k": int(peak >= 30_000), "10k": int(peak >= 10_000)}})
    return rows


# ---------- logistička regresija (stdlib) -------------------------------------------------------------------------------

def _sig(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def _solve(a, b):
    """Gaussova eliminacija s djelomičnim pivotiranjem (mala, simetrična pozitivno definitna matrica)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        piv = m[c][c] or 1e-12
        for r in range(c + 1, n):
            f = m[r][c] / piv
            if f:
                mr, mc = m[r], m[c]
                for k in range(c, n + 1):
                    mr[k] -= f * mc[k]
    x = [0.0] * n
    for c in range(n - 1, -1, -1):
        x[c] = (m[c][n] - sum(m[c][k] * x[k] for k in range(c + 1, n))) / (m[c][c] or 1e-12)
    return x


def fit(rows, target, features=FEATURES, l2=L2, iters=25, tol=1e-7):
    """Model {features, mean, sd, w (prvi je presjek), target, n, pos}. Standardizacija samo iz redaka za učenje."""
    d = len(features)
    n = len(rows)
    mean = [sum(r["x"][f] for r in rows) / n for f in features]
    sd = [math.sqrt(sum((r["x"][f] - mean[i]) ** 2 for r in rows) / n) or 1.0 for i, f in enumerate(features)]
    X = [[1.0] + [(r["x"][f] - mean[i]) / sd[i] for i, f in enumerate(features)] for r in rows]
    y = [r["y"][target] for r in rows]
    pos = sum(y)
    w = [0.0] * (d + 1)
    w[0] = math.log((pos + 0.5) / (n - pos + 0.5))
    prev = None
    for _ in range(iters):
        g = [0.0] * (d + 1)
        H = [[0.0] * (d + 1) for _ in range(d + 1)]
        ll = 0.0
        for xi, yi in zip(X, y):
            p = _sig(sum(a * b for a, b in zip(w, xi)))
            ll += math.log(p if yi else 1 - p) if 0 < p < 1 else -50.0
            e = p - yi
            s = p * (1 - p)
            for i in range(d + 1):
                g[i] += e * xi[i]
                si = s * xi[i]
                Hi = H[i]
                for j in range(i, d + 1):
                    Hi[j] += si * xi[j]
        for i in range(d + 1):
            for j in range(i):
                H[i][j] = H[j][i]
        for i in range(1, d + 1):
            g[i] += l2 * w[i]
            H[i][i] += l2
        H[0][0] += 1e-9
        step = _solve(H, g)
        w = [a - b for a, b in zip(w, step)]
        if prev is not None and abs(ll - prev) < tol * max(1.0, abs(prev)):
            break
        prev = ll
    return {"features": list(features), "mean": mean, "sd": sd, "w": w, "target": target, "n": n, "pos": pos}


def predict(model, x):
    z = model["w"][0] + sum(model["w"][i + 1] * (x[f] - model["mean"][i]) / model["sd"][i]
                            for i, f in enumerate(model["features"]))
    return _sig(z)


# ---------- mjere ------------------------------------------------------------------------------------------------------

def auc(scores, labels):
    """AUC (Mann-Whitney, izjednačeni rang = prosjek); None bez obje klase."""
    pos = sum(labels)
    neg = len(labels) - pos
    if not pos or not neg:
        return None
    pairs = sorted(zip(scores, labels))
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        r = (i + j + 1) / 2   # prosječni rang (1-based)
        rank_sum += r * sum(l for _, l in pairs[i:j])
        i = j
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def auc_se(a, pos, neg):
    """Hanley-McNeil standardna greška."""
    if a is None or not pos or not neg:
        return None
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    v = (a * (1 - a) + (pos - 1) * (q1 - a * a) + (neg - 1) * (q2 - a * a)) / (pos * neg)
    return math.sqrt(max(v, 0.0))


def precision_at(scores, labels, q):
    """(preciznost, broj odabranih, pogodaka) u gornjih q udjela po procjeni."""
    n = len(scores)
    if not n:
        return None, 0, 0
    k = max(1, math.ceil(n * q))
    top = sorted(zip(scores, labels), key=lambda t: -t[0])[:k]
    hits = sum(l for _, l in top)
    return hits / k, k, hits


def calibration(scores, labels, bins=10):
    """[(decil 1..10, n, prosječna procjena, stvarna stopa)] po rastućoj procjeni."""
    pairs = sorted(zip(scores, labels))
    n = len(pairs)
    out = []
    for b in range(bins):
        part = pairs[b * n // bins:(b + 1) * n // bins]
        if part:
            out.append((b + 1, len(part), sum(s for s, _ in part) / len(part), sum(l for _, l in part) / len(part)))
    return out


def brier(scores, labels):
    return sum((s - l) ** 2 for s, l in zip(scores, labels)) / len(labels) if labels else None


def verdict(m):
    """Riječima: pobjeđuje li model osnovnu stopu izvan uzorka."""
    if m["pos_test"] < 10:
        return "premalo pozitivnih u provjeri: ne može se reći"
    lo = (m["auc"] or 0.5) - 1.96 * (m["auc_se"] or 0)
    if lo > 0.6 and (m["lift5"] or 0) >= 2 and m["hits5"] >= 5:
        return "jasno bolji od osnovne stope na danima koje nije vidio"
    if lo > 0.5 and (m["lift5"] or 0) > 1.2:
        return "malo bolji od osnovne stope; premalo za odluke"
    return "ne pobjeđuje osnovnu stopu značajno"


# ---------- walk-forward ------------------------------------------------------------------------------------------------

def walk_forward(rows, target, block_s=BLOCK_S, min_train=MIN_TRAIN, min_pos=MIN_TRAIN_POS, on_block=None):
    """Izvan-uzorka procjene: [(mint, ts, blok_start, p, y)] i opis blokova. on_block(start, train, test) za testove."""
    if not rows:
        return [], []
    rows = sorted(rows, key=lambda r: r["ts"])
    t0, t1 = rows[0]["ts"], rows[-1]["ts"]
    preds, blocks = [], []
    start = t0 + block_s
    while start <= t1:
        end = start + block_s
        train = [r for r in rows if r["ts"] < start and r["label_ts"] < start]
        test = [r for r in rows if start <= r["ts"] < end]
        pos = sum(r["y"][target] for r in train)
        if test and len(train) >= min_train and pos >= min_pos:
            if on_block:
                on_block(start, train, test)
            m = fit(train, target)
            for r in test:
                preds.append((r["mint"], r["ts"], start, predict(m, r["x"]), r["y"][target]))
            blocks.append({"start": start, "n_train": len(train), "pos_train": pos, "n_test": len(test),
                           "pos_test": sum(r["y"][target] for r in test)})
        start = end
    return preds, blocks


def evaluate(preds):
    s = [p[3] for p in preds]
    y = [p[4] for p in preds]
    n, pos = len(y), sum(y)
    a = auc(s, y)
    p1, k1, h1 = precision_at(s, y, 0.01)
    p5, k5, h5 = precision_at(s, y, 0.05)
    base = pos / n if n else None
    m = {"n_test": n, "pos_test": pos, "base": base, "auc": a, "auc_se": auc_se(a, pos, n - pos),
         "brier": brier(s, y), "brier_base": brier([base] * n, y) if n else None,
         "p1": p1, "k1": k1, "hits1": h1, "p5": p5, "k5": k5, "hits5": h5,
         "lift1": (p1 / base) if base else None, "lift5": (p5 / base) if base else None,
         "kalibracija": calibration(s, y) if n else []}
    m["verdict"] = verdict(m)
    return m


def factors(model):
    """Najjači čimbenici konačnog modela riječima: [(opis, smjer, jačina)] po jačini."""
    out = []
    for i, f in enumerate(model["features"]):
        w = model["w"][i + 1]
        if f.startswith("sat_"):
            continue
        strength = "jako" if abs(w) >= 0.5 else "umjereno" if abs(w) >= 0.2 else "slabo"
        out.append((FEATURE_WORDS.get(f, f), "povećava" if w > 0 else "smanjuje", strength, abs(w)))
    return sorted(out, key=lambda t: -t[3])


# ---------- spremanje --------------------------------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, cilj TEXT, izvori TEXT,
    od_ts INTEGER, do_ts INTEGER, n_rows INTEGER, n_test INTEGER, pos_test INTEGER, base REAL, auc REAL, auc_se REAL,
    p1 REAL, p5 REAL, lift1 REAL, lift5 REAL, verdict TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS predictions (run_id INTEGER, cilj TEXT, mint TEXT, ts INTEGER, blok INTEGER, p REAL,
    y INTEGER, PRIMARY KEY (run_id, mint)) WITHOUT ROWID;
"""


def db_path():
    return os.environ.get("BOND_MODEL_DB") or os.path.join(_data_dir(), "bond_model.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30, isolation_level=None)
    con.execute("PRAGMA busy_timeout = 30000")
    con.executescript(SCHEMA)
    return con


def save(con, target, sources, rows, preds, blocks, m, final_model, now=None):
    detail = {"blokovi": blocks, "kalibracija": m["kalibracija"], "brier": m["brier"], "brier_base": m["brier_base"],
              "k1": m["k1"], "hits1": m["hits1"], "k5": m["k5"], "hits5": m["hits5"],
              "cimbenici": factors(final_model) if final_model else [], "model": final_model and
              {k: final_model[k] for k in ("features", "mean", "sd", "w", "n", "pos")}}
    con.execute("BEGIN IMMEDIATE")
    cur = con.execute("INSERT INTO runs (ts, cilj, izvori, od_ts, do_ts, n_rows, n_test, pos_test, base, auc, auc_se, "
                      "p1, p5, lift1, lift5, verdict, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (int(now or time.time()), target, json.dumps([os.path.basename(s) for s in sources]),
                       min((r["ts"] for r in rows), default=None), max((r["ts"] for r in rows), default=None),
                       len(rows), m["n_test"], m["pos_test"], m["base"], m["auc"], m["auc_se"], m["p1"], m["p5"],
                       m["lift1"], m["lift5"], m["verdict"], json.dumps(detail)))
    rid = cur.lastrowid
    con.executemany("INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?)",
                    [(rid, target, p[0], p[1], p[2], round(p[3], 6), p[4]) for p in preds])
    old = [r[0] for r in con.execute("SELECT id FROM runs WHERE cilj=? ORDER BY id DESC LIMIT -1 OFFSET ?",
                                     (target, KEEP_RUNS))]
    for o in old:   # stare procjene se ne gomilaju (sažetak runa ostaje)
        con.execute("DELETE FROM predictions WHERE run_id=?", (o,))
    con.commit()
    return rid


def latest(path=None):
    """{cilj: zadnji run (dict)} ili {} (nema baze). Samo čita."""
    p = path or db_path()
    if not os.path.exists(p):
        return {}
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    try:
        cur = con.execute("SELECT * FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY cilj)")
        cols = [c[0] for c in cur.description]
        out = {}
        for r in cur:
            d = dict(zip(cols, r))
            d["detail"] = json.loads(d["detail"] or "{}")
            out[d["cilj"]] = d
        return out
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def run(sources=None, path=None, now=None, log=print, targets=TARGETS):
    """Cijeli prolaz: učitaj, walk-forward po cilju, konačni model na svim recima, spremi. Vraća {cilj: mjere}."""
    launches, ishod, imena, seen = load(sources)
    rows = build_rows(launches, ishod, imena)
    if not rows:
        log("model bondanja: nema podataka s ishodom (baza mjerenja ni arhiva)")
        return {}
    con = connect(path)
    out = {}
    try:
        for t in targets:
            preds, blocks = walk_forward(rows, t)
            if not preds:
                log(f"model bondanja ({t}): premalo podataka za provjeru po vremenu ({len(rows)} redaka)")
                continue
            m = evaluate(preds)
            final = fit(rows, t) if sum(r["y"][t] for r in rows) >= MIN_TRAIN_POS else None
            save(con, t, seen, rows, preds, blocks, m, final, now)
            out[t] = m
            log(f"model bondanja ({TARGET_NAMES[t]}): provjera {m['n_test']} lansiranja, osnovna stopa "
                f"{(m['base'] or 0) * 100:.2f} %, AUC {m['auc'] if m['auc'] is None else round(m['auc'], 3)}, "
                f"gornjih 5 % pogađa {(m['p5'] or 0) * 100:.1f} % ({m['lift5'] or 0:.1f}× osnovne); {m['verdict']}")
    finally:
        con.close()
    return out
