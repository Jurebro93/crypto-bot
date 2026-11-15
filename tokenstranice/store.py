"""tokenstranice.db (TOKENSTRANICE_DB, inače DATA_DIR/tokenstranice.db, inače uz kod): mala baza, jedan pisac
(run_tokenstranice.py sat); stranice je samo čitaju (read-only).

    pages     jedan redak po tokenu: slug, simbol, ime, izvor (midcap / veliki / top), aktivan ili zamrznut (out_ts,
              out_why), dovoljno podataka (enough), MC i volumen za redoslijed, kategorija, data = JSON svih brojki
              stranice s javnim odgodom (podaci.sections), updated
    slugs     svaki slug ikad dan -> mint (stari slugovi uvijek rade)
    opinions  zadnje AI mišljenje tokena (JSON en / hr / rizici), model, trošak, osnova (sažetak ulaznih brojki)
    ai_calls  svaki poziv OpenAI-ja: tokeni, trošak, uspjeh (dnevni strop se računa odavde)
    kv        sitno stanje (zadnji red loga, strop rečen jednom na dan)
"""
import json
import os
import re
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (mint TEXT PRIMARY KEY, slug TEXT UNIQUE, symbol TEXT, name TEXT, src TEXT,
    first_ts INTEGER, last_ts INTEGER, active INTEGER DEFAULT 1, out_ts INTEGER, out_why TEXT, enough INTEGER DEFAULT 0,
    mcap REAL, vol24 REAL, cat TEXT, data TEXT, updated INTEGER);
CREATE INDEX IF NOT EXISTS pages_list ON pages (active, enough, mcap);
CREATE TABLE IF NOT EXISTS slugs (slug TEXT PRIMARY KEY, mint TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS opinions (mint TEXT PRIMARY KEY, ts INTEGER, model TEXT, data TEXT, cost_usd REAL, basis TEXT);
CREATE TABLE IF NOT EXISTS ai_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, mint TEXT, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, ok INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS ai_calls_ts ON ai_calls (ts);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
SLUG = re.compile(r"[a-z0-9\-]{1,40}")
_C = {}   # (what, path) -> (ts, value): the slug maps, read by the coin list refresh and the router


def db_path():
    if os.environ.get("TOKENSTRANICE_DB"):
        return os.environ["TOKENSTRANICE_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "tokenstranice.db")
    return os.path.join(ROOT, "tokenstranice.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.executescript(SCHEMA)
    return con


def ro(path=None):
    path = path or db_path()
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM pages LIMIT 1")
        return con
    except sqlite3.Error:
        return None


def kv_get(con, k, default=None):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    try:
        return json.loads(r[0]) if r else default
    except (TypeError, ValueError):
        return default


def kv_put(con, k, v):
    con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))


def reset_cache():
    _C.clear()


# ---------- slugs ---------------------------------------------------------------------------------------------------

def slug_base(sym, mint):
    """The same rule as ui/coins._slug: the symbol lowercased, anything else a dash; the mint's start without one."""
    s = re.sub(r"[^a-z0-9]+", "-", (sym or "").lower().replace("$", "")).strip("-")[:30].strip("-")
    return s or (mint or "x")[:6].lower()


def make_slug(sym, mint, taken):
    """A slug no other mint holds: the symbol, else symbol-<4 of the mint>, else -<6>, else -<n>. Always fits
    ui/public.coin_page's [a-z0-9-]{1,40}."""
    base = slug_base(sym, mint)
    tail = re.sub(r"[^a-z0-9]", "", (mint or "").lower())
    for s in (base, f"{base}-{tail[:4]}", f"{base}-{tail[:6]}"):
        if s and s not in taken and SLUG.fullmatch(s):
            return s
    n = 2
    while f"{base}-{tail[:6]}-{n}" in taken:
        n += 1
    return f"{base}-{tail[:6]}-{n}"


def _cached(what, path, fn, ttl=60):
    key = (what, path or db_path())
    hit = _C.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _C[key] = (time.time(), v)
    return v


def slugs_by_mint(path=None):
    """{mint: its current page slug} (ui/coins.store gives a coin that already has a token page the same slug)."""
    def load():
        con = ro(path)
        if con is None:
            return {}
        try:
            return {m: s for m, s in con.execute("SELECT mint, slug FROM pages")}
        except sqlite3.Error:
            return {}
        finally:
            con.close()
    return _cached("by_mint", path, load)


def all_slugs(path=None):
    """Every slug ever given (pages + old ones): ui/coins.store never hands one of them to another mint."""
    def load():
        con = ro(path)
        if con is None:
            return frozenset()
        try:
            return frozenset(s for (s,) in con.execute("SELECT slug FROM slugs UNION SELECT slug FROM pages"))
        except sqlite3.Error:
            return frozenset()
        finally:
            con.close()
    return _cached("all", path, load)


def mint_of_slug(con, slug):
    r = con.execute("SELECT mint FROM pages WHERE slug=?", (slug,)).fetchone()
    if r:
        return r[0]
    r = con.execute("SELECT mint FROM slugs WHERE slug=?", (slug,)).fetchone()
    return r[0] if r else None


# ---------- reading -------------------------------------------------------------------------------------------------

COLS = ("mint", "slug", "symbol", "name", "src", "first_ts", "last_ts", "active", "out_ts", "out_why", "enough",
        "mcap", "vol24", "cat", "data", "updated")


def _row(r):
    if not r:
        return None
    d = dict(zip(COLS, r))
    try:
        d["data"] = json.loads(d["data"] or "{}")
    except ValueError:
        d["data"] = {}
    return d


def page(con, mint=None, slug=None):
    """The page row of a mint (or of a slug, old slugs included) with data parsed, or None."""
    if slug is not None:
        mint = mint_of_slug(con, slug)
        if not mint:
            return None
    r = con.execute(f"SELECT {', '.join(COLS)} FROM pages WHERE mint=?", (mint,)).fetchone()
    return _row(r)


def opinion(con, mint):
    r = con.execute("SELECT ts, model, data, cost_usd FROM opinions WHERE mint=?", (mint,)).fetchone()
    if not r:
        return None
    try:
        d = json.loads(r[2] or "{}")
    except ValueError:
        return None
    return {"ts": r[0], "model": r[1], **d}


def day_start(now):
    return int(now) // 86400 * 86400


def spent(con, since):
    return float(con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls WHERE ts >= ?", (int(since),))
                 .fetchone()[0] or 0)


def book(con, mint, model, usage, cost_usd, ok, error=None, now=None):
    u = usage or {}
    con.execute("INSERT INTO ai_calls (ts, mint, model, tokens_in, tokens_out, cost_usd, ok, error) "
                "VALUES (?,?,?,?,?,?,?,?)", (int(now or time.time()), mint, model, int(u.get("in") or 0),
                                             int(u.get("out") or 0), round(float(cost_usd or 0), 6), 1 if ok else 0,
                                             (str(error)[:200] if error else None)))
    con.commit()
