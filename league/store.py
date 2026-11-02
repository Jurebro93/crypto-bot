"""league.db: each user's own demo account (manual picks from the bot's suggestions) and the feature-idea box.

Separate from paper.db: the bot's automatic paper trading never reads or writes this file, and only the
dashboard process writes here, so there is a single writer.
Prices come in from the caller (live DexScreener in the UI); fills use the same fee + AMM impact as paper/sim.py.
"""
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("LEAGUE_DB", os.path.join(HERE, "league.db"))
START_USD = float(os.environ.get("LEAGUE_START_USD", "1000"))
FEE = 0.01

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (user TEXT PRIMARY KEY, start_usd REAL, created INTEGER);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, opened_ts INTEGER, closed_ts INTEGER,
    status TEXT, size_usd REAL, entry_px REAL, entry_eff REAL, qty REAL, exit_px REAL, proceeds REAL, pnl_usd REAL,
    ret REAL, source TEXT, score REAL, note TEXT);
CREATE TABLE IF NOT EXISTS real_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, opened_ts INTEGER, size_usd REAL,
    entry_mcap REAL, closed_ts INTEGER, exit_mcap REAL, pnl_usd REAL, status TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, ts INTEGER, text TEXT, status TEXT DEFAULT 'novo');
"""


def env_users():
    """Players set on the server: UI_USERS (default Ivan,Panda,Jure), each one's password in UI_PASS_<NAME>."""
    viewer = os.environ.get("UI_TEST_USER", "Claude").strip().lower()
    # the view-only test account (UI_TEST_USER) is no player unless it has its own UI_PASS_<NAME>: on 1.11. "Claude"
    # sat in UI_USERS and the banner listed it as a player whose password is missing
    return [u.strip() for u in os.environ.get("UI_USERS", "Ivan,Panda,Jure").split(",")
            if u.strip() and (u.strip().lower() != viewer or os.environ.get(f"UI_PASS_{u.strip().upper()}"))]


def users():
    """All players: the server's list first (their colours stay), then those who registered via an invite link."""
    base = env_users()
    have = {u.lower() for u in base}
    from league import members
    return base + [m for m in members.names() if m.lower() not in have]


def missing_passwords():
    """Players who cannot log in yet because their UI_PASS_<NAME> is not set."""
    return [u for u in env_users() if not os.environ.get(f"UI_PASS_{u.upper()}")]


def connect(path=None):
    con = sqlite3.connect(path or DB, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
    except sqlite3.OperationalError:   # disk full: the tables usually exist already, reads still work
        pass
    _migrate(con)
    return con


_MIGRATED = set()


def _migrate(con):
    """Columns added after the first release, once per process and only the missing ones (an ALTER on every
    connect failed with "database or disk is full" and took the loop down with it)."""
    key = con.execute("PRAGMA database_list").fetchone()[2]
    if key in _MIGRATED:
        return
    have = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    for col, typ in (("entry_mcap", "REAL"), ("exit_mcap", "REAL"),
                     ("realized", "REAL DEFAULT 0"), ("auto", "TEXT"), ("auto_state", "TEXT")):  # auto sell
        if col not in have:
            try:
                con.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as e:
                print(f"league: stupac {col} nije dodan ({e})", flush=True)
                return
    _MIGRATED.add(key)
    from league import fixes   # one-time corrections (2.11. pairless sale at a fake DexScreener price)
    fixes.apply(con)


def impact(usd, liq):
    side = (liq or 0) / 2
    return usd / (side + usd) if side > 0 else 1.0


def account(con, user):
    """Cash, money in open positions and realized PnL; creates the account on first use."""
    try:
        con.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (user, START_USD, int(time.time())))
    except sqlite3.OperationalError:   # disk full or locked: show the default account instead of failing the page
        pass
    row = con.execute("SELECT start_usd FROM accounts WHERE user=?", (user,)).fetchone()
    start = row[0] if row else START_USD
    realized, in_use = con.execute(
        "SELECT COALESCE(SUM(CASE WHEN status='closed' THEN pnl_usd END),0),"
        " COALESCE(SUM(CASE WHEN status='open' THEN size_usd END),0) FROM trades WHERE user=?", (user,)).fetchone()
    return {"user": user, "start": start, "realized": realized, "in_use": in_use, "cash": start + realized - in_use}


def buy(con, user, token, symbol, size_usd, price, liq, source="", score=None, mcap=None):
    if not price or price <= 0:
        raise ValueError("nema cijene za token")
    if not liq or liq < 1000:
        raise ValueError("likvidnost premala (< $1k)")
    acc = account(con, user)
    if size_usd <= 0 or size_usd > acc["cash"] + 1e-9:
        raise ValueError(f"ulog mora biti između $0 i slobodnih ${acc['cash']:,.2f}")
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, token)).fetchone():
        raise ValueError("već imaš otvorenu poziciju u tom tokenu")
    eff = price * (1 + FEE) / (1 - impact(size_usd, liq))
    cur = con.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, qty, "
                      "source, score, entry_mcap) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (user, token, symbol, int(time.time()), "open", size_usd, price, eff, size_usd / eff, source, score,
                       mcap))
    con.commit()
    try:   # the player's TP/SL rule for new buys (league/auto.py, "primijeni i na nove kupnje")
        from league import auto
        auto.on_buy(con, user, cur.lastrowid, source)
    except Exception as e:  # noqa: BLE001 - never fails the buy
        print(f"league: pravilo auto sell nije primijenjeno ({e})", flush=True)
    return cur.lastrowid


def _realized(t):
    try:
        return t["realized"] or 0.0
    except (KeyError, IndexError):
        return 0.0


def value(t, price, liq):
    """What the position is worth if the rest is sold now (after fee and impact), plus what auto sell already
    took out of it in partial sales. price 0 = rugged."""
    if not price or price <= 0:
        return _realized(t)
    gross = t["qty"] * price
    return _realized(t) + gross * (1 - FEE) * (1 - impact(gross, liq))


def sell_part(con, trade_id, frac_of_rest, price, liq):
    """Auto sell: sell a share of what is left; proceeds stay in the trade (realized) until it closes."""
    t = con.execute("SELECT * FROM trades WHERE id=? AND status='open'", (trade_id,)).fetchone()
    if not t or not price or price <= 0 or frac_of_rest <= 0:
        return 0.0
    q = t["qty"] * min(1.0, frac_of_rest)
    gross = q * price
    net = gross * (1 - FEE) * (1 - impact(gross, liq))
    con.execute("UPDATE trades SET qty=qty-?, realized=COALESCE(realized,0)+? WHERE id=?", (q, net, trade_id))
    con.commit()
    return net


def sell(con, user, trade_id, price, liq, note="", mcap=None):
    t = con.execute("SELECT * FROM trades WHERE id=? AND user=? AND status='open'", (trade_id, user)).fetchone()
    if not t:
        raise ValueError("nema te otvorene pozicije")
    proceeds = value(t, price, liq)
    pnl = proceeds - t["size_usd"]
    if mcap is None and price and t["entry_mcap"] and t["entry_px"]:  # supply is fixed: mcap moves with price
        mcap = t["entry_mcap"] * price / t["entry_px"]
    con.execute("UPDATE trades SET status='closed', closed_ts=?, exit_px=?, proceeds=?, pnl_usd=?, ret=?, note=?, "
                "exit_mcap=? WHERE id=?", (int(time.time()), price or 0, proceeds, pnl, pnl / t["size_usd"], note,
                                           mcap if price else 0, trade_id))
    con.commit()
    return pnl


def sell_partial(con, user, trade_id, frac, price, liq, mcap=None):
    """Manual partial sale (Nicholas 1.11.: "što ako sam htio zatvoriti dio pozicije"). The sold share becomes its own
    closed trade (so the money is back on the account at once and the sale shows in the closed list); the open
    position keeps the rest with the same entry, so its PnL % and auto sell rules stay the same. frac >= 0.999 or a
    remainder under $1 sells everything. Returns (pnl of the sold part, sold_all)."""
    t = con.execute("SELECT * FROM trades WHERE id=? AND user=? AND status='open'", (trade_id, user)).fetchone()
    if not t:
        raise ValueError("nema te otvorene pozicije")
    if not price or price <= 0:
        raise ValueError("nema cijene, ne mogu prodati dio")
    if not frac or frac <= 0:
        raise ValueError("upiši koliko želiš prodati")
    if frac >= 0.999 or t["size_usd"] * (1 - frac) < 1:
        return sell(con, user, trade_id, price, liq, mcap=mcap), True
    q = t["qty"] * frac
    gross = q * price
    part_real = _realized(t) * frac
    proceeds = part_real + gross * (1 - FEE) * (1 - impact(gross, liq))
    cost = t["size_usd"] * frac
    pnl = proceeds - cost
    if mcap is None and t["entry_mcap"] and t["entry_px"]:
        mcap = t["entry_mcap"] * price / t["entry_px"]
    con.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, entry_eff, qty, "
                "exit_px, proceeds, pnl_usd, ret, source, score, note, entry_mcap, exit_mcap, realized) "
                "VALUES (?,?,?,?,?,'closed',?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user, t["token"], t["symbol"], t["opened_ts"], int(time.time()), cost, t["entry_px"], t["entry_eff"], q,
                 price, proceeds, pnl, pnl / cost if cost else 0, t["source"], t["score"],
                 f"djelomična prodaja {frac:.0%}", t["entry_mcap"], mcap, part_real))
    con.execute("UPDATE trades SET size_usd=size_usd*?, qty=qty-?, realized=COALESCE(realized,0)*? WHERE id=?",
                (1 - frac, q, 1 - frac, trade_id))
    con.commit()
    return pnl, False


def trades(con, user=None, status=None):
    where, args = ["1=1"], []
    if user:
        where.append("user=?")
        args.append(user)
    if status:
        where.append("status=?")
        args.append(status)
    return [dict(r) for r in con.execute(f"SELECT * FROM trades WHERE {' AND '.join(where)} ORDER BY opened_ts DESC", args)]


def leaderboard(con, live):
    """One row per player, best first. live: token -> (price, liquidity, url); open positions without a live
    price count at what they cost, so a DexScreener outage does not reshuffle the table."""
    rows = []
    for u in users():
        acc = account(con, u)
        opened = trades(con, u, "open")
        closed = trades(con, u, "closed")
        unreal = 0.0
        for t in opened:
            if t["token"] in live:
                price, liq, _ = live[t["token"]]
                unreal += value(t, price, liq) - t["size_usd"]
        equity = acc["start"] + acc["realized"] + unreal
        best = max(closed, key=lambda t: t["pnl_usd"] or 0, default=None)
        rows.append({**acc, "unrealized": unreal, "equity": equity, "profit": equity - acc["start"],
                     "ret": (equity - acc["start"]) / acc["start"] if acc["start"] else 0, "open": len(opened),
                     "closed": len(closed), "wins": sum(1 for t in closed if (t["pnl_usd"] or 0) > 0), "best": best})
    try:
        con.commit()
    except sqlite3.OperationalError:
        pass
    return sorted(rows, key=lambda r: -r["profit"])


# real_trades table stays (old hand-logged rows kept); the page that wrote it was removed 2026-11-01.


def add_idea(con, user, text):
    text = (text or "").strip()[:4000]
    if not text:
        raise ValueError("prazan prijedlog")
    con.execute("INSERT INTO ideas (user, ts, text) VALUES (?,?,?)", (user, int(time.time()), text))
    con.commit()


def set_idea_status(con, idea_id, status):
    con.execute("UPDATE ideas SET status=? WHERE id=?", (status, idea_id))
    con.commit()


def ideas(con):
    return [dict(r) for r in con.execute("SELECT * FROM ideas ORDER BY id DESC")]
