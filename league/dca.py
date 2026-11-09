"""Automatic DCA (dollar-cost averaging) for the competition: a player picks a token, an amount per buy, how often
and how many buys, and the tool buys for them from their own demo account.

Every buy goes into the player's one open position in that token (bought by hand, by copy trading or by an earlier
DCA buy): the position grows and its entry price becomes the average of all buys. Selling stays one button, and
auto sell (league/auto.py) works on the whole position. If the player sells it, the next DCA buy opens a new one.

Runs every minute inside the auto sell thread of the dashboard process (league.db's only writer). Prices: one
DexScreener request for the plans that are due this minute (free). A plan stops by itself when it is done, when the
cash runs out or when the token collapses (rug), and says why in dca_log.
"""
import json
import time

from . import store

CFG = {"min_amount": 5, "max_amount": 500, "min_buys": 2, "max_buys": 100, "max_active": 10, "min_liq": 5000,
       "price_wait_min": 30,   # no price this long after a buy was due: that buy is skipped, the plan goes on
       "keep_log_days": 90}

EVERY = {15: "svakih 15 min", 60: "svaki sat", 240: "svaka 4 sata", 720: "svakih 12 sati", 1440: "jednom dnevno",
         10080: "jednom tjedno"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS dca_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, amount_usd REAL, every_min INTEGER,
    n_total INTEGER, n_done INTEGER DEFAULT 0, spent REAL DEFAULT 0, created INTEGER, next_ts INTEGER,
    active INTEGER DEFAULT 1, stopped INTEGER, why TEXT, last_note TEXT);
CREATE INDEX IF NOT EXISTS dca_plans_active ON dca_plans (active, next_ts);
CREATE TABLE IF NOT EXISTS dca_log (
    plan_id INTEGER, ts INTEGER, action TEXT, note TEXT, price REAL, mcap REAL, trade_id INTEGER);
CREATE INDEX IF NOT EXISTS dca_log_plan ON dca_log (plan_id, ts);
"""


def ensure(con):
    try:
        con.executescript(SCHEMA)
    except Exception:  # noqa: BLE001 - disk full: the tables usually exist already
        pass
    have = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
    if "dca_id" not in have:
        try:
            con.execute("ALTER TABLE trades ADD COLUMN dca_id INTEGER")
        except Exception:  # noqa: BLE001
            pass


def start(con, user, token, symbol, amount_usd, every_min, n_total, now=None):
    """New plan; the first buy happens within a minute. Returns the plan id."""
    ensure(con)
    now = int(now or time.time())
    amount = float(amount_usd or 0)
    if not CFG["min_amount"] <= amount <= CFG["max_amount"]:
        raise ValueError(f"iznos po kupnji mora biti između ${CFG['min_amount']} i ${CFG['max_amount']}")
    every = int(every_min or 0)
    if every not in EVERY:
        raise ValueError("odaberi koliko često kupovati")
    n = int(n_total or 0)
    if not CFG["min_buys"] <= n <= CFG["max_buys"]:
        raise ValueError(f"broj kupnji mora biti između {CFG['min_buys']} i {CFG['max_buys']}")
    acc = store.account(con, user)
    if amount > acc["cash"] + 1e-9:
        raise ValueError(f"nemaš dovoljno slobodnog novca ni za prvu kupnju (slobodno ${acc['cash']:,.2f})")
    if con.execute("SELECT 1 FROM dca_plans WHERE user=? AND token=? AND active=1", (user, token)).fetchone():
        raise ValueError("već imaš aktivan DCA za taj token; zaustavi ga pa pokreni novi")
    if con.execute("SELECT COUNT(*) FROM dca_plans WHERE user=? AND active=1", (user,)).fetchone()[0] >= CFG["max_active"]:
        raise ValueError(f"najviše {CFG['max_active']} aktivnih DCA planova")
    cur = con.execute("INSERT INTO dca_plans (user, token, symbol, amount_usd, every_min, n_total, created, next_ts) "
                      "VALUES (?,?,?,?,?,?,?,?)", (user, token, symbol, amount, every, n, now, now))
    con.commit()
    return cur.lastrowid


def stop(con, user, plan_id, why="zaustavio si ga"):
    ensure(con)
    n = con.execute("UPDATE dca_plans SET active=0, stopped=?, why=? WHERE id=? AND user=? AND active=1",
                    (int(time.time()), why, plan_id, user)).rowcount
    con.commit()
    if not n:
        raise ValueError("taj DCA nije aktivan")


def plans(con, user=None, active=True):
    ensure(con)
    where, args = ["1=1"], []
    if user:
        where.append("user=?")
        args.append(user)
    if active is not None:
        where.append("active=?")
        args.append(1 if active else 0)
    return [dict(r) for r in con.execute(f"SELECT * FROM dca_plans WHERE {' AND '.join(where)} "
                                         "ORDER BY active DESC, created DESC LIMIT 100", args)]


def log(con, plan_id, limit=20):
    ensure(con)
    return [dict(r) for r in con.execute("SELECT * FROM dca_log WHERE plan_id=? ORDER BY ts DESC LIMIT ?",
                                         (plan_id, limit))]


def describe(p):
    """'$20 svaki sat, obavljeno 3 od 10' for tables and the trade's source."""
    return f"${p['amount_usd']:,.0f} {EVERY.get(p['every_min'], str(p['every_min']) + ' min')}, " \
           f"obavljeno {p['n_done']} od {p['n_total']}"


def add_to(con, trade_id, size_usd, price, liq):
    """Buy more into an open position: the entry price becomes the average of all buys (weighted by dollars),
    entry MC moves with it, auto sell starts again from the new average."""
    t = con.execute("SELECT * FROM trades WHERE id=? AND status='open'", (trade_id,)).fetchone()
    if not t:
        raise ValueError("pozicija više nije otvorena")
    eff = price * (1 + store.FEE) / (1 - store.impact(size_usd, liq))
    old = t["size_usd"]
    total = old + size_usd
    entry_px = total / (old / t["entry_px"] + size_usd / price)
    entry_eff = total / (old / t["entry_eff"] + size_usd / eff)
    mcap = t["entry_mcap"] * entry_px / t["entry_px"] if t["entry_mcap"] else None
    auto = t["auto"]
    if auto and json.loads(auto).get("mode") == "smart":
        con.execute("UPDATE trades SET auto_state=NULL WHERE id=?", (trade_id,))  # smart exit restarts on the new average
    con.execute("UPDATE trades SET size_usd=?, qty=qty+?, entry_px=?, entry_eff=?, entry_mcap=? WHERE id=?",
                (total, size_usd / eff, entry_px, entry_eff, mcap, trade_id))
    a = json.loads(auto) if auto else None
    if a and a.get("mode") == "tpsl" and ("tp_in" in a or "sl_in" in a):
        from league import auto as autosell   # a TP/SL typed in percent follows the new average entry
        try:
            autosell.set_auto(con, t["user"], trade_id, "tpsl", a.get("tp_in", ""), a.get("sl_in", ""),
                              from_eff=bool(a.get("from_eff")))   # 9.11.: a copy's levels stay on the effective entry
        except ValueError:
            pass
    con.commit()


def _log(con, plan_id, now, action, note, price=None, mcap=None, trade_id=None):
    con.execute("INSERT INTO dca_log VALUES (?,?,?,?,?,?,?)", (plan_id, int(now), action, note, price, mcap, trade_id))
    con.execute("UPDATE dca_plans SET last_note=? WHERE id=?", (note, plan_id))


def _end(con, p, now, why):
    con.execute("UPDATE dca_plans SET active=0, stopped=?, why=? WHERE id=?", (int(now), why, p["id"]))


def _rugged(token, mcap, liq):
    try:
        from rugfilter import collapse
        from ui import data
        return collapse.check(collapse.peaks(data.HYPE_DB, [token]).get(token), mcap, liq)
    except Exception:  # noqa: BLE001 - a guard, never the reason the DCA loop stops
        return None


def _market(tokens):
    from . import copy
    return copy.market(tokens)


def run_once(con, market_fn=None, now=None):
    """Buy for every plan that is due. Returns [(user, text)] for the server log."""
    ensure(con)
    now = int(now or time.time())
    due = [dict(r) for r in con.execute("SELECT * FROM dca_plans WHERE active=1 AND next_ts<=?", (now,))]
    if not due:
        return []
    mk = (market_fn or _market)({p["token"] for p in due}) or {}
    done = []
    for p in due:
        name = p["symbol"] or p["token"][:6]
        step = p["every_min"] * 60
        m = mk.get(p["token"])
        if not m or not m[0]:
            if now - p["next_ts"] > CFG["price_wait_min"] * 60:
                _log(con, p["id"], now, "preskočeno", "DexScreener nije dao cijenu, ova kupnja je preskočena")
                con.execute("UPDATE dca_plans SET next_ts=? WHERE id=?", (p["next_ts"] + step, p["id"]))
            continue   # retried next minute
        price, liq, _, mcap = m[:4]
        sym = (m[4] if len(m) > 4 else None) or p["symbol"]
        if (liq or 0) < CFG["min_liq"]:
            why = f"premala likvidnost (${liq or 0:,.0f}), DCA je zaustavljen da ne kupuješ token iz kojeg se ne može izaći"
            _log(con, p["id"], now, "zaustavljeno", why, price, mcap)
            _end(con, p, now, why)
            continue
        col = _rugged(p["token"], mcap, liq)
        if col:
            why = f"token se srušio ({col['text']}), DCA je zaustavljen"
            _log(con, p["id"], now, "zaustavljeno", why, price, mcap)
            _end(con, p, now, why)
            done.append((p["user"], f"DCA {name}: zaustavljen, rug"))
            continue
        acc = store.account(con, p["user"])
        if acc["cash"] + 1e-9 < p["amount_usd"]:
            why = f"nema dovoljno slobodnog novca (${acc['cash']:,.2f}) za kupnju od ${p['amount_usd']:,.0f}"
            _log(con, p["id"], now, "zaustavljeno", why, price, mcap)
            _end(con, p, now, why)
            continue
        n_new = p["n_done"] + 1
        src = f"DCA kupnja {n_new}/{p['n_total']}"
        try:
            t = con.execute("SELECT id FROM trades WHERE user=? AND token=? AND status='open'",
                            (p["user"], p["token"])).fetchone()
            if t:
                add_to(con, t[0], p["amount_usd"], price, liq)
                tid = t[0]
                con.execute("UPDATE trades SET source=? WHERE id=? AND (dca_id=? OR source LIKE 'DCA %')",
                            (src, tid, p["id"]))
            else:
                tid = store.buy(con, p["user"], p["token"], sym, p["amount_usd"], price, liq, src, None, mcap)
                con.execute("UPDATE trades SET dca_id=? WHERE id=?", (p["id"], tid))
        except ValueError as e:
            _log(con, p["id"], now, "preskočeno", str(e), price, mcap)
            con.execute("UPDATE dca_plans SET next_ts=? WHERE id=?", (max(p["next_ts"] + step, now + 60), p["id"]))
            continue
        # the next buy keeps the rhythm (a late minute does not shift every later buy), but never piles up
        nxt = p["next_ts"] + step
        if nxt <= now:
            nxt = now + step
        con.execute("UPDATE dca_plans SET n_done=?, spent=spent+?, next_ts=?, symbol=COALESCE(symbol, ?) WHERE id=?",
                    (n_new, p["amount_usd"], nxt, sym, p["id"]))
        _log(con, p["id"], now, "kupnja", f"kupnja {n_new}/{p['n_total']}: ${p['amount_usd']:,.0f} na MC "
             f"${mcap or 0:,.0f}", price, mcap, tid)
        done.append((p["user"], f"DCA {name}: kupnja {n_new}/{p['n_total']} za ${p['amount_usd']:,.0f}"))
        if n_new >= p["n_total"]:
            _end(con, p, now, "gotovo: sve kupnje obavljene")
    con.execute("DELETE FROM dca_log WHERE ts < ?", (now - CFG["keep_log_days"] * 86400,))
    con.commit()
    return done
