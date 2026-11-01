"""Public top Solana meme coins: leaderboard + one analysis page per coin (English main, Croatian), indexable.

- List: Jupiter's verified token list (lite-api.jup.ag, free, no key), tokens tagged 'meme', with real liquidity and
  holders, sorted by market cap. Refreshed every REFRESH_S in a background thread of the dashboard process and kept in
  public.db (coins + coin_hist, one row per coin per refresh, so our own price / holder history grows over time).
- Each page joins what MemeSonar itself measured: daily candles and holder counts (dugo.db), influencer calls and
  their outcome older than 24 h (kol.db), plus Jupiter's audit (mint/freeze authority, top holders, dev balance).
  Live signals (Šansa za skok, smart-money flows, fresh calls) are teased and stay members-only.
"""
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request

from ui.html import esc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PUBLIC_DB") or os.path.join(ROOT, "public.db")
SRC = "https://lite-api.jup.ag/tokens/v2/tag?query=verified"
REFRESH_S = int(os.environ.get("COINS_REFRESH_S", str(3 * 3600)))
TOP = 100
MIN_LIQ, MIN_HOLDERS, MIN_MCAP, MIN_VOL = 50_000, 1_000, 300_000, 10_000
MIN_LIQ_SHARE = 0.002          # liquidity below 0.2% of market cap = the market cap is not real (thin pool, fake price)
NOT_MEME = {"stable", "stocks", "rwa", "major", "defi", "xstocks", "equities", "lst"}
BAD = re.compile(r"nigg|fag|hitler|retard|nazi|rape|porn|fuck|cunt|dick|cock|pussy|dojk|fap|cum\b|sex|scam", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS coins (mint TEXT PRIMARY KEY, slug TEXT UNIQUE, symbol TEXT, name TEXT, icon TEXT,
    rank INTEGER, mcap REAL, fdv REAL, price REAL, liq REAL, holders INTEGER, vol24 REAL, chg1h REAL, chg24h REAL,
    buys24 INTEGER, sells24 INTEGER, traders24 INTEGER, organic REAL, created TEXT, audit TEXT, updated INTEGER,
    win TEXT);
CREATE TABLE IF NOT EXISTS coin_hist (mint TEXT, ts INTEGER, price REAL, mcap REAL, holders INTEGER, liq REAL,
    PRIMARY KEY (mint, ts));
"""
_lock = threading.Lock()


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        con.execute("ALTER TABLE coins ADD COLUMN win TEXT")   # tables made before the column existed
    except sqlite3.OperationalError:
        pass
    return con


def _slug(sym, mint, taken):
    s = re.sub(r"[^a-z0-9]+", "-", (sym or "").lower().replace("$", "")).strip("-") or mint[:6].lower()
    if s in taken:
        s = f"{s}-{mint[:4].lower()}"
    return s


def _vol(t):
    s = t.get("stats24h") or {}
    return (s.get("buyVolume") or 0) + (s.get("sellVolume") or 0)


def _win(t):
    """Price and holder change over the last 5 min / 1 h / 6 h / 24 h (percent), for the 24-hour chart."""
    out = {}
    for k in ("5m", "1h", "6h", "24h"):
        s = t.get(f"stats{k}") or {}
        out[k] = [s.get("priceChange"), s.get("holderChange")]
    return out


SECS = {"5m": 300, "1h": 3600, "6h": 6 * 3600, "24h": 86400}


def day_series(row, idx, value):
    """[(ts, value)] for the last 24 hours, rebuilt from the window changes: value then = now / (1 + change)."""
    try:
        win = json.loads(row.get("win") or "{}")
    except ValueError:
        return []
    now = row.get("updated") or int(time.time())
    if not value or not win:
        return []
    pts = []
    for k in ("24h", "6h", "1h", "5m"):
        ch = (win.get(k) or [None, None])[idx]
        if ch is not None and ch > -100:
            pts.append((now - SECS[k], value / (1 + ch / 100)))
    return pts + [(now, value)] if len(pts) >= 2 else []


def pick(tokens):
    """Meme tokens worth listing, biggest first: tagged meme or launched on pump.fun / bonk.fun, real pool, traded today."""
    out = []
    for t in tokens:
        tags = set(t.get("tags") or [])
        if tags & NOT_MEME or not ("meme" in tags or str(t.get("id", "")).endswith(("pump", "bonk"))):
            continue
        liq, mcap = t.get("liquidity") or 0, t.get("mcap") or 0
        if liq < MIN_LIQ or (t.get("holderCount") or 0) < MIN_HOLDERS or mcap < MIN_MCAP or _vol(t) < MIN_VOL:
            continue
        if liq < mcap * MIN_LIQ_SHARE or BAD.search(f"{t.get('symbol', '')} {t.get('name', '')}"):
            continue
        out.append(t)
    out.sort(key=lambda t: -(t.get("mcap") or 0))
    return out[:TOP]


def store(tokens, con=None, now=None):
    """Write the picked tokens; slugs stay stable once given."""
    now = int(now or time.time())
    own = con is None
    con = con or connect()
    try:
        old = {r["mint"]: r["slug"] for r in con.execute("SELECT mint, slug FROM coins")}
        taken = set(old.values())
        con.execute("UPDATE coins SET rank = NULL")
        for i, t in enumerate(tokens, 1):
            mint = t["id"]
            slug = old.get(mint) or _slug(t.get("symbol"), mint, taken)
            taken.add(slug)
            s24 = t.get("stats24h") or {}
            s1 = t.get("stats1h") or {}
            con.execute("""INSERT INTO coins (mint, slug, symbol, name, icon, rank, mcap, fdv, price, liq, holders, vol24,
                chg1h, chg24h, buys24, sells24, traders24, organic, created, audit, updated, win)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET symbol=excluded.symbol,
                name=excluded.name, icon=excluded.icon, rank=excluded.rank, mcap=excluded.mcap, fdv=excluded.fdv,
                price=excluded.price, liq=excluded.liq, holders=excluded.holders, vol24=excluded.vol24,
                chg1h=excluded.chg1h, chg24h=excluded.chg24h, buys24=excluded.buys24, sells24=excluded.sells24,
                traders24=excluded.traders24, organic=excluded.organic, created=excluded.created,
                audit=excluded.audit, updated=excluded.updated, win=excluded.win""",
                        (mint, slug, (t.get("symbol") or "").strip(), (t.get("name") or "").strip(), t.get("icon"), i,
                         t.get("mcap"), t.get("fdv"), t.get("usdPrice"), t.get("liquidity"), t.get("holderCount"),
                         (s24.get("buyVolume") or 0) + (s24.get("sellVolume") or 0), s1.get("priceChange"),
                         s24.get("priceChange"), s24.get("numBuys"), s24.get("numSells"), s24.get("numTraders"),
                         t.get("organicScore"), t.get("createdAt") or (t.get("firstPool") or {}).get("createdAt"),
                         json.dumps(t.get("audit") or {}), now, json.dumps(_win(t))))
            con.execute("INSERT OR REPLACE INTO coin_hist VALUES (?,?,?,?,?,?)",
                        (mint, now, t.get("usdPrice"), t.get("mcap"), t.get("holderCount"), t.get("liquidity")))
        con.execute("DELETE FROM coin_hist WHERE ts < ?", (now - 400 * 86400,))
        con.commit()
    finally:
        if own:
            con.close()
    return len(tokens)


def refresh():
    req = urllib.request.Request(SRC, headers={"User-Agent": "MemeSonar/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    picked = pick(data)
    del data
    if len(picked) < 10:
        raise RuntimeError(f"premalo tokena ({len(picked)})")
    with _lock:
        n = store(picked)
    print(f"javni tokeni: osvježeno {n} meme tokena", flush=True)
    return n


def start():
    def loop():
        time.sleep(int(os.environ.get("COINS_DELAY_S", "90")))
        while True:
            try:
                refresh()
            except Exception as e:  # noqa: BLE001
                print(f"javni tokeni: osvježavanje nije uspjelo: {e}", flush=True)
            time.sleep(REFRESH_S)
    threading.Thread(target=loop, daemon=True, name="coins-refresh").start()


# ---------- reading -------------------------------------------------------------------------------------------------

def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def top():
    con = _ro(DB)
    if con is None:
        return []
    try:
        return [dict(r) for r in con.execute("SELECT * FROM coins WHERE rank IS NOT NULL ORDER BY rank")]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def coin(slug):
    con = _ro(DB)
    if con is None:
        return None, []
    try:
        r = con.execute("SELECT * FROM coins WHERE slug = ?", (slug,)).fetchone()
        if not r:
            return None, []
        hist = [dict(h) for h in con.execute("SELECT ts, price, mcap, holders, liq FROM coin_hist WHERE mint = ? "
                                             "ORDER BY ts", (r["mint"],))]
        return dict(r), hist
    except sqlite3.OperationalError:
        return None, []
    finally:
        con.close()


def ours(mint, delay_s=86400):
    """What MemeSonar measured about this coin: candles, holders, influencer calls (older than delay_s)."""
    out = {"candles": [], "holders": [], "calls": [], "callers": [], "fresh": 0, "top10": None, "cex": None}
    dugo = _ro(os.environ.get("DUGO_DB") or os.path.join(ROOT, "dugo.db"))
    if dugo is not None:
        try:
            out["candles"] = [dict(r) for r in dugo.execute(
                "SELECT day, c, v FROM candles WHERE mint = ? ORDER BY day DESC LIMIT 180", (mint,))][::-1]
            out["holders"] = [dict(r) for r in dugo.execute(
                "SELECT day, n FROM holders WHERE mint = ? ORDER BY day DESC LIMIT 180", (mint,))][::-1]
            hi = dugo.execute("SELECT top10 FROM holder_info WHERE mint = ? ORDER BY day DESC LIMIT 1", (mint,)).fetchone()
            out["top10"] = hi[0] if hi else None
            li = dugo.execute("SELECT all_cex, names FROM listings WHERE mint = ? ORDER BY day DESC LIMIT 1",
                              (mint,)).fetchone()
            out["cex"] = (li[0], li[1]) if li else None
        except sqlite3.OperationalError:
            pass
        finally:
            dugo.close()
    kol = _ro(os.environ.get("KOL_DB") or os.path.join(ROOT, "kol.db"))
    if kol is not None:
        cut = int(time.time()) - delay_s
        try:
            out["calls"] = [dict(r) for r in kol.execute(
                "SELECT c.handle, c.ts, c.url, c.mcap0, c.r1h, c.r24h, c.max24, k.score FROM calls c LEFT JOIN kols k "
                "ON k.handle = c.handle WHERE c.token = ? AND c.kind = 'call' AND c.ts < ? AND COALESCE(k.bot, 0) = 0 "
                "ORDER BY c.ts DESC LIMIT 20", (mint, cut))]
            out["fresh"] = kol.execute("SELECT COUNT(*) FROM calls WHERE token = ? AND kind = 'call' AND ts >= ?",
                                       (mint, cut)).fetchone()[0]
        except sqlite3.OperationalError:
            try:
                out["calls"] = [dict(r) for r in kol.execute(
                    "SELECT handle, ts, url, mcap0, r1h, r24h, max24, NULL score FROM calls WHERE token = ? AND "
                    "kind = 'call' AND ts < ? ORDER BY ts DESC LIMIT 20", (mint, cut))]
            except sqlite3.OperationalError:
                pass
        finally:
            kol.close()
    return out


# ---------- charts (plain SVG, no JS) -----------------------------------------------------------------------------

def svg_line(points, w=720, h=220, color="#4f46e5", fill=True, label=None):
    """points: [(x, y)] sorted by x. A smooth-ish line with a soft area under it."""
    pts = [(x, y) for x, y in points if y is not None]
    if len(pts) < 2:
        return ""
    x0, x1 = pts[0][0], pts[-1][0]
    lo, hi = min(y for _, y in pts), max(y for _, y in pts)
    if hi == lo:
        hi, lo = hi * 1.01 + 1e-12, lo * 0.99
    pad = 8

    def X(x):
        return pad + (x - x0) / ((x1 - x0) or 1) * (w - 2 * pad)

    def Y(y):
        return pad + (1 - (y - lo) / (hi - lo)) * (h - 2 * pad)
    d = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for i, (x, y) in enumerate(pts))
    gid = f"g{abs(hash((color, len(pts), pts[0])))%99999}"
    area = (f"<path d=\"{d} L{X(x1):.1f},{h - pad} L{X(x0):.1f},{h - pad} Z\" fill=\"url(#{gid})\"/>" if fill else "")
    up = pts[-1][1] >= pts[0][1]
    col = color or ("#16a34a" if up else "#dc2626")
    return (f"<svg viewBox=\"0 0 {w} {h}\" width=100% role=img aria-label=\"{esc(label or '')}\" "
            f"preserveAspectRatio=none style='display:block;height:{h}px'><defs><linearGradient id={gid} x1=0 y1=0 x2=0 "
            f"y2=1><stop offset=0 stop-color=\"{col}\" stop-opacity=.18 /><stop offset=1 stop-color=\"{col}\" "
            f"stop-opacity=0 /></linearGradient></defs>{area}<path d=\"{d}\" fill=none stroke=\"{col}\" "
            f"stroke-width=2.2 stroke-linejoin=round stroke-linecap=round vector-effect=non-scaling-stroke /></svg>")
