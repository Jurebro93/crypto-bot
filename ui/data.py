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


def tables():
    """[(db, table, rows)] for the data-status box."""
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
    for r in hype_signals(limit=20000):
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
