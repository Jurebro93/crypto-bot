"""Copy trading for the competition: a player follows a KOL (enters on their next call) or a wallet (mirrors its buys
and sells) and the tool trades that player's own demo account for them.

Runs every minute inside the auto sell thread of the dashboard process (league.db's only writer). It only reads
data the bot already collects, so it costs no extra API credits:
- KOL calls: kol.db calls (kind 'call'), hype.db kol_mentions (live X webhook, seconds), tg.db posts (Telegram).
- Wallets: hype.db chain_trades (Helius webhook on the KOL wallets, buys and sells within seconds).
Prices: one DexScreener request for the new tokens of the minute (free, the same as the rest of the page).

A call or buy is entered only while it is fresh (max_delay_min): entering a pump 40 minutes late is not copying.
Every decision (entered, skipped and why, sold) goes to the copy_log table, so the page can show what happened.
"""
import json
import os
import sqlite3
import time

from . import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOL = "So11111111111111111111111111111111111111112"
STABLE = {SOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}

CFG = {"max_delay_min": 10,      # call/buy older than this when we see it: not entered
       "price_wait_min": 5,      # a brand-new token often has no DexScreener pair for a few minutes
       "sell_lookback_min": 120,  # a wallet sale is retried this long when there is no price
       "min_liq": 5000, "max_mcap": 50e6, "min_size": 5, "max_size": 500, "max_per_day": 50,
       "keep_log_days": 30}

SCHEMA = """
CREATE TABLE IF NOT EXISTS follows (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, kind TEXT, target TEXT, label TEXT, size_usd REAL,
    per_day INTEGER, exit TEXT, created INTEGER, active INTEGER DEFAULT 1, stopped INTEGER);
CREATE INDEX IF NOT EXISTS follows_active ON follows (active);
CREATE TABLE IF NOT EXISTS copy_log (
    follow_id INTEGER, token TEXT, side TEXT, ev_ts INTEGER, ts INTEGER, symbol TEXT, action TEXT, note TEXT,
    trade_id INTEGER, PRIMARY KEY (follow_id, token, side));
CREATE INDEX IF NOT EXISTS copy_log_ts ON copy_log (ts);
"""

KIND_HR = {"kol": "KOL", "wallet": "wallet"}
EXIT_HR = {"smart": "pametni izlaz", "tpsl": "moj TP/SL", "manual": "prodajem sam", "mirror": "prodaj kad on proda",
           "mirror_smart": "prodaj kad on proda + pametni izlaz"}


def ensure(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    if "follow_id" not in have:
        try:
            con.execute("ALTER TABLE trades ADD COLUMN follow_id INTEGER")
        except sqlite3.OperationalError:
            pass


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _paths():
    return {"kol": os.environ.get("KOL_DB") or os.path.join(ROOT, "kol.db"),
            "hype": os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db"),
            "tg": os.environ.get("TG_DB") or os.path.join(ROOT, "tg.db")}


# ---------- follows -----------------------------------------------------------------------------------------------

def follow(con, user, kind, target, label="", size_usd=25, per_day=10, exit_mode="", tp="", sl="", once=False):
    """Start following (or update an existing follow of the same target). Returns the follow id.
    once (KOLs only): enter their next call, then stop following by itself."""
    from . import auto
    ensure(con)
    if kind not in KIND_HR:
        raise ValueError("nepoznata vrsta praćenja")
    target = (target or "").strip()
    if not target:
        raise ValueError("koga pratiš?")
    size = float(size_usd or 0)
    if not CFG["min_size"] <= size <= CFG["max_size"]:
        raise ValueError(f"ulog po ulazu mora biti između ${CFG['min_size']} i ${CFG['max_size']}")
    per_day = int(per_day or 0)
    if not 1 <= per_day <= CFG["max_per_day"]:
        raise ValueError(f"broj ulaza na dan mora biti između 1 i {CFG['max_per_day']}")
    exit_mode = exit_mode or ("mirror" if kind == "wallet" else "smart")
    allowed = ("mirror", "mirror_smart", "tpsl") if kind == "wallet" else ("smart", "tpsl", "manual")
    if exit_mode not in allowed:
        raise ValueError("nepoznat način izlaza")
    ex = {"mode": exit_mode}
    if once and kind == "kol":
        ex["once"] = True
    if exit_mode == "tpsl":
        # checked now on a made-up entry so a typo shows here and not silently on the first copied trade
        tp_px, _ = auto.parse_level(tp, 1.0, 1e6, "tp")
        sl_px, _ = auto.parse_level(sl, 1.0, 1e6, "sl")
        if tp_px is None and sl_px is None:
            raise ValueError("upiši barem TP ili SL (npr. 100% i -30%)")
        ex.update(tp=tp or "", sl=sl or "")
    row = con.execute("SELECT id FROM follows WHERE user=? AND kind=? AND target=? AND active=1",
                      (user, kind, target)).fetchone()
    if row:
        con.execute("UPDATE follows SET size_usd=?, per_day=?, exit=?, label=? WHERE id=?",
                    (size, per_day, json.dumps(ex), label or target, row[0]))
        con.commit()
        return row[0]
    cur = con.execute("INSERT INTO follows (user, kind, target, label, size_usd, per_day, exit, created) "
                      "VALUES (?,?,?,?,?,?,?,?)", (user, kind, target, label or target, size, per_day, json.dumps(ex),
                                                   int(time.time())))
    con.commit()
    return cur.lastrowid


def unfollow(con, user, follow_id):
    ensure(con)
    n = con.execute("UPDATE follows SET active=0, stopped=? WHERE id=? AND user=? AND active=1",
                    (int(time.time()), follow_id, user)).rowcount
    con.commit()
    if not n:
        raise ValueError("to praćenje ne postoji")


def follows(con, user=None, active=True):
    ensure(con)
    where, args = ["1=1"], []
    if user:
        where.append("user=?")
        args.append(user)
    if active is not None:
        where.append("active=?")
        args.append(1 if active else 0)
    out = []
    for r in con.execute(f"SELECT * FROM follows WHERE {' AND '.join(where)} ORDER BY created DESC", args):
        d = dict(r)
        d["exit"] = json.loads(d["exit"] or "{}")
        out.append(d)
    return out


def describe_exit(ex):
    s = ("samo sljedeći call, " if ex.get("once") else "") + EXIT_HR.get(ex.get("mode"), "")
    if ex.get("mode") == "tpsl":
        s += " (" + ", ".join(p for p in (f"TP {ex.get('tp')}" if ex.get("tp") else "",
                                          f"SL {ex.get('sl')}" if ex.get("sl") else "") if p) + ")"
    return s


def log(con, follow_id=None, user=None, limit=100):
    ensure(con)
    sql = ("SELECT l.*, f.user, f.kind, f.label FROM copy_log l JOIN follows f ON f.id = l.follow_id WHERE 1=1"
           + (" AND l.follow_id=?" if follow_id else "") + (" AND f.user=?" if user else "")
           + " ORDER BY l.ts DESC LIMIT ?")
    args = [a for a in (follow_id, user) if a] + [limit]
    return [dict(r) for r in con.execute(sql, args)]


def follow_results(con):
    """follow_id -> {'n', 'open', 'closed', 'wins', 'pnl'} of the trades it opened (closed PnL only)."""
    ensure(con)
    out = {}
    for fid, status, pnl in con.execute("SELECT follow_id, status, pnl_usd FROM trades WHERE follow_id IS NOT NULL"):
        r = out.setdefault(fid, {"n": 0, "open": 0, "closed": 0, "wins": 0, "pnl": 0.0})
        r["n"] += 1
        if status == "open":
            r["open"] += 1
        else:
            r["closed"] += 1
            r["pnl"] += pnl or 0
            r["wins"] += 1 if (pnl or 0) > 0 else 0
    return out


# ---------- events ------------------------------------------------------------------------------------------------

def events(kol_handles, wallets, since, paths=None):
    """[(target, token, side, ts)] of the followed KOLs ('buy' = a call) and wallets ('buy' / 'sell') since `since`."""
    p = paths or _paths()
    out = []
    if kol_handles:
        x = [h for h in kol_handles if not h.startswith("tg:")]
        tg = [h[3:] for h in kol_handles if h.startswith("tg:")]
        kc, hc, tc = _ro(p["kol"]), _ro(p["hype"]), _ro(p["tg"])
        try:
            if kol_handles:
                q = ",".join("?" * len(kol_handles))
                for h, tok, ts in _q(kc, f"SELECT handle, token, ts FROM calls WHERE kind='call' AND ts >= ? "
                                         f"AND handle IN ({q})", (since, *kol_handles)):
                    out.append((h, tok, "buy", ts))
            if x:
                q = ",".join("?" * len(x))
                for h, ca, ts in _q(hc, f"SELECT handle, ca, ts FROM kol_mentions WHERE ts >= ? AND ca != '' "
                                        f"AND handle IN ({q})", (since, *x)):
                    out.append((h, ca, "buy", ts))
            if tg:
                q = ",".join("?" * len(tg))
                for ch, ts, cas, fwd in _q(tc, f"SELECT channel, ts, cas, fwd_from FROM posts WHERE ts >= ? "
                                               f"AND cas != '' AND channel IN ({q})", (since, *tg)):
                    if not fwd:   # a forward is somebody else's call
                        out.extend((f"tg:{ch}", ca, "buy", ts) for ca in cas.split(",") if ca)
        finally:
            for c in (kc, hc, tc):
                if c is not None:
                    c.close()
    if wallets:
        hc = _ro(p["hype"])
        try:
            q = ",".join("?" * len(wallets))
            for w, mint, side, ts in _q(hc, f"SELECT wallet, mint, side, ts FROM chain_trades WHERE ts >= ? "
                                            f"AND wallet IN ({q})", (since, *wallets)):
                out.append((w, mint, side, ts))
        finally:
            if hc is not None:
                hc.close()
    return [(t, tok, side, int(ts)) for t, tok, side, ts in out if tok and len(tok) >= 32 and ts]


def _logged(con, fid, token, side):
    return con.execute("SELECT 1 FROM copy_log WHERE follow_id=? AND token=? AND side=?", (fid, token, side)).fetchone()


def _log(con, f, token, side, ev_ts, now, action, note, symbol=None, trade_id=None):
    con.execute("INSERT OR IGNORE INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                (f["id"], token, side, ev_ts, int(now), symbol, action, note, trade_id))


def _today(con, fid, now):
    day0 = int(now) - int(now) % 86400
    return con.execute("SELECT COUNT(*) FROM copy_log WHERE follow_id=? AND side='buy' AND action='ulaz' AND ts>=?",
                       (fid, day0)).fetchone()[0]


def _rugged(token, mcap, liq):
    try:
        from rugfilter import collapse
        from ui import data
        return collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
    except Exception:  # noqa: BLE001 - the check is a guard, never the reason the copy loop stops
        return None


def market(tokens):
    """token -> (price, liquidity, url, mcap, symbol) from the deepest DexScreener pair; {} when unreachable."""
    if not tokens:
        return {}
    try:
        from dexscreener import client
        pairs = client.tokens("solana", list(tokens))
    except Exception:  # noqa: BLE001 - no price this minute, retried next minute
        return {}
    best = {}
    for p in pairs:
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= best.get(t, (0, -1))[1]:
            best[t] = (float(p.get("priceUsd") or 0), liq, p.get("url"), p.get("marketCap") or p.get("fdv"),
                       p["baseToken"].get("symbol"))
    return best


def run_once(con, market_fn=None, now=None, paths=None):
    """One pass: enter new calls/buys of followed KOLs and wallets, sell when a followed wallet sells.
    Returns [(user, text)] for the log."""
    from . import auto
    ensure(con)
    now = int(now or time.time())
    fl = follows(con)
    if not fl:
        return []
    by_target = {}
    for f in fl:
        by_target.setdefault((f["kind"], f["target"]), []).append(f)
    kols = sorted({f["target"] for f in fl if f["kind"] == "kol"})
    wals = sorted({f["target"] for f in fl if f["kind"] == "wallet"})
    since = now - max(CFG["max_delay_min"], CFG["sell_lookback_min"]) * 60
    evs = sorted(events(kols, wals, since, paths), key=lambda e: e[3])
    todo = []   # (follow, token, side, ts)
    for target, tok, side, ts in evs:
        kind = "wallet" if target in wals else "kol"
        for f in by_target.get((kind, target), []):
            if ts < f["created"] - 60 or tok in STABLE:
                continue   # calls from before the follow started are not copied
            if side == "buy" and now - ts > CFG["max_delay_min"] * 60:
                if not _logged(con, f["id"], tok, "buy") and ts >= f["created"]:
                    _log(con, f, tok, "buy", ts, now, "preskočeno", f"vidjeli smo ga tek {(now - ts) // 60} min nakon "
                         "poziva, prekasno za ulaz")
                continue
            if not _logged(con, f["id"], tok, side):
                todo.append((f, tok, side, ts))
    if not todo:
        con.commit()
        return []
    mk = (market_fn or market)({t for _, t, _, _ in todo}) or {}
    done = []
    stopped = set()   # "only the next call" follows that already entered this minute
    for f, tok, side, ts in todo:
        if f["id"] in stopped:
            continue
        if _logged(con, f["id"], tok, side):
            continue   # the same token twice in this minute (X post + live webhook)
        m = mk.get(tok)
        name = f["label"] or f["target"][:6]
        if side == "sell":
            opened = con.execute("SELECT * FROM trades WHERE follow_id=? AND token=? AND status='open'",
                                 (f["id"], tok)).fetchall()
            if not opened:
                _log(con, f, tok, side, ts, now, "info", "prodao je token koji nismo kopirali")
                continue
            if f["exit"].get("mode") not in ("mirror", "mirror_smart", "tpsl"):
                continue
            if not m or not m[0]:
                if now - ts > CFG["sell_lookback_min"] * 60:
                    _log(con, f, tok, side, ts, now, "preskočeno", "nema cijene za prodaju; prodaj ručno")
                continue   # retried next minute
            for t in opened:
                pnl = store.sell(con, f["user"], t["id"], m[0], m[1], f"copy: {name} je prodao", mcap=m[3])
                _log(con, f, tok, side, ts, now, "izlaz", f"{name} je prodao, i mi: {pnl:+.2f} $", t["symbol"], t["id"])
                done.append((f["user"], f"copy {name}: prodano {t['symbol'] or tok[:6]} {pnl:+.2f} $"))
            continue
        # buy / call
        if not m or not m[0]:
            if now - ts > CFG["price_wait_min"] * 60:
                _log(con, f, tok, side, ts, now, "preskočeno", "DexScreener nema cijenu tog tokena")
            continue
        price, liq, _, mcap = m[:4]
        sym = m[4] if len(m) > 4 else None
        why = None
        if (liq or 0) < CFG["min_liq"]:
            why = f"premala likvidnost (${liq or 0:,.0f}), ne bi se moglo izaći"
        elif mcap and mcap > CFG["max_mcap"]:
            why = "velik token (preko $50M), to nije poziv na memecoin"
        elif mcap and liq and liq > mcap:
            why = "lažni pool (likvidnost veća od market capa), tipičan rug"
        elif _today(con, f["id"], now) >= f["per_day"]:
            why = f"već {f['per_day']} ulaza danas (tvoj limit)"
        elif con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (f["user"], tok)).fetchone():
            why = "već imaš otvorenu poziciju u tom tokenu"
        else:
            col = _rugged(tok, mcap, liq)
            if col:
                why = f"token je rugan ({col['text']})"
        if why:
            _log(con, f, tok, side, ts, now, "preskočeno", why, sym)
            continue
        src = f"copy {KIND_HR[f['kind']]} {name}"
        try:
            tid = store.buy(con, f["user"], tok, sym, f["size_usd"], price, liq, src, None, mcap)
        except ValueError as e:
            _log(con, f, tok, side, ts, now, "preskočeno", str(e), sym)
            continue
        con.execute("UPDATE trades SET follow_id=? WHERE id=?", (f["id"], tid))
        mode = f["exit"].get("mode")
        try:
            if mode in ("smart", "mirror_smart"):
                auto.set_auto(con, f["user"], tid, "smart")
            elif mode == "tpsl":
                auto.set_auto(con, f["user"], tid, "tpsl", f["exit"].get("tp", ""), f["exit"].get("sl", ""))
        except ValueError:
            pass
        late = max(0, now - ts)
        _log(con, f, tok, side, ts, now, "ulaz", f"kupljeno za ${f['size_usd']:,.0f} na MC ${mcap or 0:,.0f}, "
             f"{late // 60} min {late % 60} s nakon {'poziva' if f['kind'] == 'kol' else 'njegove kupnje'}", sym, tid)
        done.append((f["user"], f"copy {name}: kupljeno {sym or tok[:6]} za ${f['size_usd']:,.0f}"))
        if f["exit"].get("once"):
            con.execute("UPDATE follows SET active=0, stopped=? WHERE id=?", (now, f["id"]))
            stopped.add(f["id"])
    con.execute("DELETE FROM copy_log WHERE ts < ?", (now - CFG["keep_log_days"] * 86400,))
    con.commit()
    return done
