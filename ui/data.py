"""Read-only access to everything the bot writes: calendar.db, hype.db and output/*.json|md.

Every query tolerates a missing table or database (another module may not have run yet) and returns [].
Connections are opened read-only, so the dashboard never blocks or corrupts the bot's own writes.
"""
import glob
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL_DB = os.path.join(HERE, "calendar.db")
HYPE_DB = os.path.join(HERE, "hype.db")
WALLET_DB = os.environ.get("WALLET_DB", os.path.join(HERE, "wallets.db"))
RUG_DB = os.environ.get("RUG_DB", os.path.join(HERE, "rug.db"))
PAPER_DB = os.path.join(HERE, "paper.db")
OUT = os.path.join(HERE, "output")

# Each module writes its own SQLite file; older runs left the same tables in calendar.db.
# Reads go through every file in order and the first one that has a row wins (newest file first).
GROUPS = {"wallets": [WALLET_DB, CAL_DB], "rug": [RUG_DB, CAL_DB], "hype": [HYPE_DB, CAL_DB],
          "cal": [CAL_DB], "paper": [PAPER_DB]}


def _connect(path):
    if not os.path.exists(path):
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def q(path, sql, args=()):
    con = _connect(path)
    if con is None:
        return []
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def cal(sql, args=()):
    return q(CAL_DB, sql, args)


def multi(group, sql, args=(), key=None):
    """Same query on every file of a group; rows with an already-seen key are dropped."""
    seen, out = set(), []
    for path in GROUPS[group]:
        for r in q(path, sql, args):
            k = key(r) if key else None
            if k is not None:
                if k in seen:
                    continue
                seen.add(k)
            out.append(r)
    return out


_TTL = {}   # name -> (ts, value): slow-changing results shared by page builds (small values only)


TTL_DIR = os.environ.get("UI_TTL_DIR", "/tmp/memesonar-ttl")


def _enc(v):
    """Plain JSON with tags for what JSON has no type for (tuple, set, dict with non-text keys, bytes, float inf/nan),
    so the cache round-trips the same Python values the old pickle did, without pickle's "load = run code" risk
    (audit 4.11. §4.3: unpickling from a shared /tmp dir)."""
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else {"__f": repr(v)}
    if isinstance(v, tuple):
        return {"__t": [_enc(x) for x in v]}
    if isinstance(v, (set, frozenset)):
        return {"__s": [_enc(x) for x in v]}
    if isinstance(v, (bytes, bytearray)):
        return {"__b": bytes(v).hex()}
    if isinstance(v, dict):
        if all(isinstance(k, str) for k in v) and not any(k.startswith("__") for k in v):
            return {k: _enc(x) for k, x in v.items()}
        return {"__d": [[_enc(k), _enc(x)] for k, x in v.items()]}
    if isinstance(v, list):
        return [_enc(x) for x in v]
    if hasattr(v, "keys"):                     # sqlite3.Row and friends
        return {k: _enc(v[k]) for k in v.keys()}
    raise TypeError(f"ttl_cache: {type(v).__name__} not cacheable")


def _dec(v):
    if isinstance(v, list):
        return [_dec(x) for x in v]
    if isinstance(v, dict):
        if len(v) == 1:
            (k, x), = v.items()
            if k == "__t":
                return tuple(_dec(y) for y in x)
            if k == "__s":
                return {_dec(y) for y in x}
            if k == "__b":
                return bytes.fromhex(x)
            if k == "__f":
                return float(x)
            if k == "__d":
                return {_dec(a): _dec(b) for a, b in x}
        return {k: _dec(x) for k, x in v.items()}
    return v


def _dumps(val):
    import json
    return json.dumps(_enc(val), separators=(",", ":")).encode()


def _loads(blob):
    import json
    return _dec(json.loads(blob))


def ttl_cache(name, seconds, fn):
    """fn() at most once per `seconds` (counts over whole tables, wallet clusters, the token list: they change slowly,
    but each read scans hundreds of MB). Kept in this process and, since the heavy pages are built by short child
    processes (run_ui.build_in_child) where a process cache would be empty every time, also as a file in TTL_DIR
    that the next child reads instead of computing it again (2.11.: "/" and "/tokens" each took 60+ s).
    Stored as tagged JSON (4.11. audit: unpickling from a shared dir is code execution); kept as one bytes
    block so small objects that outlive a page build do not pin whole heap arenas."""
    hit = _TTL.get(name)
    if hit and time.time() - hit[0] < seconds:
        return _loads(hit[1])
    import hashlib
    path = os.path.join(TTL_DIR, name.split(":")[0] + "-" + hashlib.sha1(name.encode()).hexdigest()[:12] + ".json")
    try:
        age = time.time() - os.path.getmtime(path)
        if age < seconds and os.stat(path).st_uid == os.getuid():   # only our own files
            with open(path, "rb") as f:
                blob = f.read()
            val = _loads(blob)
            _TTL[name] = (time.time() - age, blob)
            return val
    except (OSError, ValueError, TypeError, KeyError):
        pass
    val = fn()
    try:
        blob = _dumps(val)
    except TypeError:
        return val                             # something JSON cannot hold: just do not cache it
    _TTL[name] = (time.time(), blob)
    try:
        os.makedirs(TTL_DIR, mode=0o700, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
    except OSError:
        pass
    return val


def stage(label, t0):
    """One "ui-tijek" line on stderr for a slow part of a page build (run_ui forwards a child's lines to the log)."""
    import sys
    d = time.time() - t0
    if d >= 1.0:
        print(f"ui-tijek: {label} {d:.1f} s", file=sys.stderr, flush=True)
    return time.time()


def tables():
    """[(db, table, rows)] for the data-status box (counted at most every 30 min)."""
    return ttl_cache(f"tables:{WALLET_DB}:{HYPE_DB}", 1800, _tables)


def _tables():
    out = []
    for path in (CAL_DB, HYPE_DB, WALLET_DB, RUG_DB, PAPER_DB):
        for r in q(path, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            n = q(path, f"SELECT COUNT(*) n FROM [{r['name']}]")
            out.append((os.path.basename(path), r["name"], n[0]["n"] if n else 0))
    return out


def js(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


# ---------- hype signals: hype.db is current, calendar.db holds older rows from before the split ----------

def hype_signals(where="1=1", args=(), order="ts DESC", limit=5000):
    return multi("hype", f"SELECT * FROM hype_signals WHERE {where} ORDER BY {order} LIMIT ?", (*args, limit),
                 lambda r: (r["token"], r["ts"]))


SIG_COLS = "ts, token, symbol, name, pair, url, score, price, mcap, liquidity, features, sources"


def signal_summary(limit=50000, recent_since=None):
    """Per token over the newest `limit` hype signals of each file (same window as hype_signals(limit=...)):
    {"last": newest row without the weights column, "first_ts", "max": highest score (0 floor)}, plus the
    (token, ts, mcap, liquidity) rows since `recent_since`. The grouping runs in SQLite, so only one row per
    token reaches Python instead of every signal with its JSON (the Pregled page used to hold all of them)."""
    sigs, recent, first = {}, [], None
    win = "(SELECT ts, token, score, mcap, liquidity FROM hype_signals ORDER BY ts DESC LIMIT ?)"
    for path in GROUPS["hype"]:
        con = _connect(path)
        if con is None:
            continue
        try:
            if first is None:  # newest file: aggregated in SQL
                try:   # one read transaction: both windows below see the same signals (WAL snapshot)
                    con.execute("BEGIN")
                except sqlite3.OperationalError:
                    pass
                agg = {r["token"]: r for r in con.execute(
                    f"SELECT token, MIN(ts) f, MAX(COALESCE(score, 0)) m, MAX(ts) l FROM {win} GROUP BY token", (limit,))}
                for r in con.execute(f"SELECT {', '.join('h.' + c.strip() for c in SIG_COLS.split(','))} FROM hype_signals h "
                                     f"JOIN (SELECT token, MAX(ts) l FROM {win} GROUP BY token) a "
                                     "ON h.token = a.token AND h.ts = a.l", (limit,)):
                    # 9.11. 17:58: the two windows are read one after the other; a signal written in between put a
                    # token in the second that the first had not seen -> KeyError on every /natjecanje build for
                    # minutes (the UI process grew to 883 MB rebuilding). Such a token takes its own row as the whole.
                    a = agg.get(r["token"]) or {"f": r["ts"], "m": r["score"]}
                    sigs[r["token"]] = {"last": dict(r), "first_ts": a["f"], "max": max(0, a["m"] or 0)}
                if recent_since is not None:
                    recent += [tuple(r) for r in con.execute(
                        f"SELECT token, ts, mcap, liquidity FROM {win} WHERE ts >= ? ORDER BY ts DESC", (limit, recent_since))]
                first = path
                continue
            # older files (calendar.db from before the split): few rows, folded one by one like before
            rows = [dict(r) for r in con.execute(f"SELECT {SIG_COLS} FROM hype_signals ORDER BY ts DESC LIMIT ?", (limit,))]
        except sqlite3.OperationalError:
            continue
        finally:
            con.close()
        dup = set()
        toks = sorted({r["token"] for r in rows})
        if toks and first:
            c0 = _connect(first)
            try:
                for i in range(0, len(toks), 500):
                    part = toks[i:i + 500]
                    dup |= {(t, ts) for t, ts in c0.execute(
                        f"SELECT token, ts FROM {win} WHERE token IN ({','.join('?' * len(part))})", (limit, *part))}
            except sqlite3.OperationalError:
                pass
            finally:
                c0.close()
        for s in rows:
            if (s["token"], s["ts"]) in dup:
                continue
            dup.add((s["token"], s["ts"]))
            if recent_since is not None and s["ts"] >= recent_since:
                recent.append((s["token"], s["ts"], s["mcap"], s["liquidity"]))
            r = sigs.setdefault(s["token"], {"last": s, "first_ts": s["ts"], "max": 0})
            r["first_ts"] = min(r["first_ts"], s["ts"])
            r["max"] = max(r["max"], s["score"] or 0)
            if s["ts"] > r["last"]["ts"]:
                r["last"] = s
    return sigs, recent


def latest_details():
    """token -> parsed `extra` of its newest hype_details row (grouped in SQL, one JSON parse per token)."""
    out = {}
    for d in q(HYPE_DB, "SELECT token, extra, MAX(ts) ts FROM hype_details GROUP BY token"):
        out[d["token"]] = js(d["extra"], {}) or {}
    return out


def rug_latest():
    """mint -> newest rug report (same as the first per mint of rug_reports()), picked in SQL."""
    best = {}
    for path in GROUPS["rug"]:
        for r in q(path, "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY mint ORDER BY checked_at DESC) rn "
                         "FROM rug_reports) WHERE rn = 1"):
            r.pop("rn", None)
            cur = best.get(r["mint"])
            if cur is None or (r["checked_at"] or 0) > (cur["checked_at"] or 0):
                best[r["mint"]] = r
    for r in best.values():
        r["data"] = js(r["data"], {}) or {}
    return best


def hype_snapshots(token):
    out = multi("hype", "SELECT ts, price, mcap, liquidity FROM hype_snapshots WHERE token=? ORDER BY ts", (token,),
                lambda r: r["ts"])
    return sorted(out, key=lambda r: r["ts"])


def token_pulse(token, hours=24, limit=400):
    try:
        out = multi("hype", "SELECT ts, price, mcap, liquidity, vol_m5, vol_h1, buys_m5, sells_m5, buys_h1, sells_h1, holders, "
                            "holders_src FROM token_pulse WHERE token=? AND ts >= ? ORDER BY ts DESC LIMIT ?",
                    (token, int(time.time() - hours * 3600), limit), lambda r: r["ts"])
    except Exception:
        return []
    return sorted(out, key=lambda r: r["ts"])


def token_tiers():
    """token -> token_tier row (class, tier reached, T0 verdict, path shape); {} when the table does not exist yet."""
    try:
        return {r["token"]: r for r in multi("hype", "SELECT * FROM token_tier", key=lambda r: r["token"])}
    except Exception:
        return {}


def tier_summary(hours=24):
    try:
        from tiers import store as tstore
        con = _connect(HYPE_DB)
        if con is None:
            return None
        con.row_factory = __import__("sqlite3").Row
        return tstore.summary(con, hours)
    except Exception:
        return None


def smart_wallets():
    return multi("hype", "SELECT * FROM smart_wallets", key=lambda r: r["wallet"])


# ---------- wallets ----------

def wallets(scored_only=True):
    where = "stats IS NOT NULL" if scored_only else "1=1"
    rows = multi("wallets", f"SELECT * FROM wallets WHERE {where} ORDER BY COALESCE(copy_score,-1) DESC, "
                 f"COALESCE(score,-1) DESC, priority DESC", key=lambda r: r["wallet"])
    for r in rows:
        r["stats"] = js(r["stats"], {}) or {}
        r["labels"] = js(r["labels"], []) or []
        r["sources"] = js(r["sources"], {}) or {}
    return rows


def wallet(addr):
    rows = multi("wallets", "SELECT * FROM wallets WHERE wallet=?", (addr,))
    if not rows:
        return None
    r = rows[0]
    r["stats"] = js(r["stats"], {}) or {}
    r["labels"] = js(r["labels"], []) or []
    r["sources"] = js(r["sources"], {}) or {}
    return r


def sightings(wallet=None, token=None):
    col, val = ("wallet", wallet) if wallet else ("token", token)
    rows = multi("wallets", f"SELECT * FROM wallet_sightings WHERE {col}=? ORDER BY ts DESC", (val,),
                 lambda r: (r["wallet"], r["token"], r["source"], r["role"]))
    for r in rows:
        r["extra"] = js(r["extra"], {}) or {}
    return rows


def wallet_trades(wallet):
    rows = multi("wallets", "SELECT sig, ts, mint, tokens, sol, kind FROM wallet_trades WHERE wallet=? ORDER BY ts",
                 (wallet,), lambda r: (r["sig"], r["mint"]))
    return sorted(rows, key=lambda r: r["ts"])


def wallet_pnl(wallet):
    return sorted(multi("wallets", "SELECT * FROM wallet_pnl WHERE wallet=? ORDER BY ts", (wallet,),
                        lambda r: r["ts"]), key=lambda r: r["ts"])


# ---------- tokens ----------

def event_tokens(token=None):
    if token:
        rows = cal("SELECT * FROM event_tokens WHERE token=? ORDER BY event_date", (token,))
    else:
        rows = cal("SELECT * FROM event_tokens ORDER BY event_date, score DESC")
    for r in rows:
        r["data"] = js(r["data"], {}) or {}
    return rows


def rug_reports(mint=None):
    where, args = ("mint=?", (mint,)) if mint else ("1=1", ())
    rows = multi("rug", f"SELECT * FROM rug_reports WHERE {where} ORDER BY checked_at DESC", args,
                 lambda r: (r["mint"], r["checked_at"]))
    rows.sort(key=lambda r: -(r["checked_at"] or 0))
    for r in rows:
        r["data"] = js(r["data"], {}) or {}
    return rows


def symbols():
    """mint -> symbol from every table that knows one (for readable links)."""
    m = {}
    for r in cal("SELECT token, symbol FROM event_tokens"):
        m.setdefault(r["token"], r["symbol"])
    for path in GROUPS["hype"]:   # symbol of each token's newest signal among the newest 20000 (covering index)
        for r in q(path, "SELECT token, symbol FROM (SELECT ts, token, symbol FROM hype_signals ORDER BY ts DESC "
                         "LIMIT 20000) ORDER BY ts DESC"):
            m.setdefault(r["token"], r["symbol"])
    for r in multi("rug", "SELECT mint, symbol FROM rug_reports"):
        m.setdefault(r["mint"], r["symbol"])
    for r in multi("paper", "SELECT token, symbol FROM candidates"):
        m.setdefault(r["token"], r["symbol"])
    return m


def tokens():
    """One row per token, merged from the three token layers (event match, hype, rug filter)."""
    t = {}

    def row(mint):
        return t.setdefault(mint, {"token": mint, "symbol": None, "name": None, "events": [], "hype_max": None,
                                   "hype_last": None, "hype_n": 0, "hype_ts": None, "rug": None, "mcap": None,
                                   "liquidity": None, "url": None, "seen": 0, "paper": None})

    for e in event_tokens():
        r = row(e["token"])
        r["events"].append(e)
        r["symbol"] = r["symbol"] or e["symbol"]
        r["name"] = r["name"] or e["name"]
        r["mcap"], r["liquidity"], r["url"] = e["mcap"], e["liquidity"], r["url"] or e["url"]
    for s in sorted(hype_signals(limit=50000), key=lambda s: s["ts"]):
        r = row(s["token"])
        r["symbol"] = s["symbol"] or r["symbol"]
        r["name"] = s["name"] or r["name"]
        r["hype_n"] += 1
        r["hype_last"], r["hype_ts"] = s["score"], s["ts"]
        r["hype_max"] = max(r["hype_max"] or 0, s["score"] or 0)
        r["mcap"], r["liquidity"], r["url"] = s["mcap"], s["liquidity"], s["url"] or r["url"]
    for g in rug_reports():
        r = row(g["mint"])
        if r["rug"] is None:  # newest first
            r["rug"] = g
            r["symbol"] = r["symbol"] or g["symbol"]
            m = g["data"].get("market") or {}
            r["mcap"] = r["mcap"] or m.get("mcap")
            r["liquidity"] = r["liquidity"] or m.get("liquidity")
            r["url"] = r["url"] or m.get("url")
    seen = {}
    for s in multi("wallets", "SELECT DISTINCT token, wallet FROM wallet_sightings"):
        seen.setdefault(s["token"], set()).add(s["wallet"])
    for mint, ws in seen.items():
        if mint in t:
            t[mint]["seen"] = len(ws)
    for c in paper_candidates():
        r = row(c["token"])
        r["paper"] = r["paper"] or c  # newest first
        r["symbol"] = r["symbol"] or c["symbol"]
        r["url"] = r["url"] or c["url"]
    return list(t.values())


# ---------- paper trading (run_paper.py) ----------

def paper_candidates(token=None):
    where, args = ("token=?", (token,)) if token else ("1=1", ())
    rows = multi("paper", f"SELECT * FROM candidates WHERE {where} ORDER BY first_ts DESC", args)
    for r in rows:
        r["features"] = js(r["features"], {}) or {}
        r["rug_flags"] = js(r["rug_flags"], []) or []
    return rows


def paper_trades(token=None):
    where, args = ("token=?", (token,)) if token else ("1=1", ())
    rows = multi("paper", f"SELECT * FROM trades WHERE {where} ORDER BY opened_ts DESC", args)
    for r in rows:
        r["state"] = js(r["state"], {}) or {}
    return rows


def paper_dca():
    """DCA suggestions on bot trades with their outcome (paper/dca.py), oldest first."""
    con = _connect(PAPER_DB)
    if con is None:
        return []
    try:
        from paper import dca
        con.row_factory = None
        return dca.outcomes(con)
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def paper_reviews():
    rows = multi("paper", "SELECT * FROM reviews ORDER BY day DESC")
    for r in rows:
        r["data"] = js(r["data"], {}) or {}
    return rows


# ---------- events ----------

def latest_calendar_json():
    files = sorted(glob.glob(os.path.join(OUT, "calendar-*.json")))
    if not files:
        return {}
    try:
        with open(files[-1]) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def events():
    rows = cal("SELECT * FROM events ORDER BY date, hype DESC")
    extra = {(e.get("date"), e.get("title")): e for e in latest_calendar_json().get("events", [])}
    for r in rows:
        r["signals"] = js(r["signals"], {}) or {}
        r["keywords"] = js(r["keywords"], []) or []
        x = extra.get((r["date"], r["title"]), {})
        r["token_likelihood"] = x.get("token_likelihood")
        r["event_score"] = x.get("score")
    return rows


# ---------- markdown/json outputs ----------

def outputs():
    files = []
    for p in sorted(glob.glob(os.path.join(OUT, "*.md")) + glob.glob(os.path.join(OUT, "*", "*.md"))):
        files.append((os.path.relpath(p, OUT), os.path.getmtime(p), os.path.getsize(p)))
    return sorted(files, key=lambda f: -f[1])


def read_output(rel):
    path = os.path.realpath(os.path.join(OUT, rel))
    if not path.startswith(os.path.realpath(OUT) + os.sep) or not path.endswith(".md") or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()
