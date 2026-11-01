"""nastoken.db: the players' token projects, the wallets they donate from, and snapshots of a live token's numbers.

Only the dashboard process writes this file (single writer, like league.db). No private keys, ever: a project
holds public data (name, ticker, links) and, once launched, the token's public mint address.
"""
import os
import re
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("NASTOKEN_DB", os.path.join(HERE, "nastoken.db"))
ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")   # base58 Solana address
LAUNCH = ("pumpfun", "meteora", "raydium")
STATUS = {"nacrt": "📝 Nacrt", "test": "🧪 Test (devnet)", "live": "🚀 Lansiran"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_ts INTEGER, updated_ts INTEGER, created_by TEXT,
    name TEXT, symbol TEXT, description TEXT, image_url TEXT, website TEXT, x_url TEXT, tg_url TEXT,
    supply INTEGER, decimals INTEGER, launch TEXT, liq_sol REAL, dev_buy_sol REAL, mkt_usd REAL,
    infl_pct REAL, team_pct REAL, status TEXT DEFAULT 'nacrt', mint TEXT);
CREATE TABLE IF NOT EXISTS donors (user TEXT PRIMARY KEY, address TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS stats (
    project_id INTEGER, ts INTEGER, price REAL, mcap REAL, liq REAL, vol24 REAL, buys24 INTEGER, sells24 INTEGER,
    top10 REAL, PRIMARY KEY (project_id, ts));
"""

FIELDS = ("name", "symbol", "description", "image_url", "website", "x_url", "tg_url", "supply", "decimals", "launch",
          "liq_sol", "dev_buy_sol", "mkt_usd", "infl_pct", "team_pct")
DEFAULTS = {"supply": 1_000_000_000, "decimals": 6, "launch": "pumpfun", "liq_sol": 0.0, "dev_buy_sol": 0.5,
            "mkt_usd": 500.0, "infl_pct": 3.0, "team_pct": 5.0}


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
    except sqlite3.OperationalError:   # disk full: tables usually exist, reads still work
        pass
    return con


def _url(v):
    v = (v or "").strip()
    if v and not v.startswith(("https://", "http://")):
        v = "https://" + v
    return v[:300]


def clean(form):
    """Form -> validated project fields; raises ValueError with a plain Croatian message."""
    name = (form.get("name") or "").strip()[:32]
    symbol = re.sub(r"[^A-Za-z0-9]", "", form.get("symbol") or "").upper()[:10]
    if len(name) < 2:
        raise ValueError("ime tokena treba barem 2 znaka")
    if not 2 <= len(symbol) <= 10:
        raise ValueError("oznaka (ticker) treba 2 do 10 slova ili brojki, npr. NASH")

    def f(k, lo, hi):
        try:
            x = float(form.get(k) if form.get(k) not in (None, "") else DEFAULTS[k])
        except ValueError:
            raise ValueError(f"neispravan broj u polju {k}") from None
        if not lo <= x <= hi:
            raise ValueError(f"{k} mora biti između {lo:g} i {hi:g}")
        return x

    launch = form.get("launch") or "pumpfun"
    if launch not in LAUNCH:
        raise ValueError("nepoznat način lansiranja")
    if launch == "pumpfun":   # fields pump.fun fixes itself: whatever the form holds there is ignored
        form = dict(form, supply="", decimals="", liq_sol="")
    out = {"name": name, "symbol": symbol, "description": (form.get("description") or "").strip()[:500],
           "image_url": _url(form.get("image_url")), "website": _url(form.get("website")),
           "x_url": _url(form.get("x_url")), "tg_url": _url(form.get("tg_url")),
           "supply": int(f("supply", 1_000, 1e15)), "decimals": int(f("decimals", 0, 9)), "launch": launch,
           "liq_sol": f("liq_sol", 0, 10_000), "dev_buy_sol": f("dev_buy_sol", 0, 1_000),
           "mkt_usd": f("mkt_usd", 0, 1_000_000), "infl_pct": f("infl_pct", 0, 20), "team_pct": f("team_pct", 0, 30)}
    if launch == "pumpfun":   # pump.fun always mints 1 B with 6 decimals and needs no own pool
        out.update(supply=1_000_000_000, decimals=6, liq_sol=0.0)
    elif out["liq_sol"] <= 0:
        raise ValueError("za vlastiti pool upiši koliko SOL-a ide u likvidnost (npr. 10)")
    if out["infl_pct"] + out["team_pct"] > 30:
        raise ValueError("influenceri + tim zajedno najviše 30% supplyja, inače kupci to vide kao rizik")
    return out


def save(con, user, form, pid=None, now=None):
    data = clean(form)
    now = int(now or time.time())
    if pid:
        con.execute(f"UPDATE projects SET {', '.join(k + '=?' for k in FIELDS)}, updated_ts=? WHERE id=?",
                    [data[k] for k in FIELDS] + [now, pid])
    else:
        cur = con.execute(f"INSERT INTO projects (created_ts, updated_ts, created_by, {', '.join(FIELDS)}) "
                          f"VALUES (?, ?, ?, {', '.join('?' * len(FIELDS))})", [now, now, user] + [data[k] for k in FIELDS])
        pid = cur.lastrowid
    con.commit()
    return pid


def set_mint(con, pid, mint, status="live"):
    mint = (mint or "").strip()
    if not ADDR.fullmatch(mint):
        raise ValueError("to nije Solana adresa tokena (32-44 znaka)")
    if status not in STATUS:
        raise ValueError("nepoznat status")
    con.execute("UPDATE projects SET mint=?, status=?, updated_ts=? WHERE id=?", (mint, status, int(time.time()), pid))
    con.commit()


def delete(con, pid, user):
    p = get(con, pid)
    if not p:
        raise ValueError("nema tog tokena")
    if p["created_by"] != user:
        raise ValueError(f"nacrt može obrisati samo onaj tko ga je napravio ({p['created_by']})")
    if p["status"] == "live":
        raise ValueError("lansirani token se ne briše, ostaje u praćenju")
    con.execute("DELETE FROM projects WHERE id=?", (pid,))
    con.execute("DELETE FROM stats WHERE project_id=?", (pid,))
    con.commit()


def projects(con):
    return [dict(r) for r in con.execute("SELECT * FROM projects ORDER BY status='live' DESC, updated_ts DESC")]


def get(con, pid):
    r = con.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def set_donor(con, user, address):
    address = (address or "").strip()
    if not ADDR.fullmatch(address):
        raise ValueError("to nije Solana adresa (32-44 znaka, iz Phantoma: Primi → kopiraj)")
    other = con.execute("SELECT user FROM donors WHERE address=? AND user<>?", (address, user)).fetchone()
    if other:
        raise ValueError(f"tu adresu je već upisao {other[0]}")
    con.execute("INSERT OR REPLACE INTO donors VALUES (?, ?, ?)", (user, address, int(time.time())))
    con.commit()


def donors(con):
    """user -> wallet address they donate from."""
    return {r["user"]: r["address"] for r in con.execute("SELECT user, address FROM donors")}


def add_stats(con, pid, s, now=None, every_s=900):
    """One snapshot per project at most every `every_s` (taken when someone opens the page)."""
    now = int(now or time.time())
    last = con.execute("SELECT MAX(ts) FROM stats WHERE project_id=?", (pid,)).fetchone()[0]
    if last and now - last < every_s:
        return False
    con.execute("INSERT OR REPLACE INTO stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, now, s.get("price"), s.get("mcap"), s.get("liq"), s.get("vol24"), s.get("buys24"),
                 s.get("sells24"), s.get("top10")))
    con.commit()
    return True


def history(con, pid, limit=200):
    return [dict(r) for r in con.execute("SELECT * FROM stats WHERE project_id=? ORDER BY ts DESC LIMIT ?", (pid, limit))]
