"""Rekt and new rounds in the Natjecanje (Nicholas 4.11.: the bot and Mario fell to $0).

A player whose account falls under REKT_USD is "rekt": what is left in open positions is sold at the live price, the
player starts again with a fresh $1,000 and the leaderboard shows 💀×N next to the name (N = how many times). From then
on store.account counts only trades opened after the last rekt, so the ranking is by the current round; every older
trade stays in the lists and in the "Svi krugovi" total.

The bot (user "bot") has rounds the same way: its account on the board is paper.db's trades since its last rekt on a
$1,000 base. Rows live in league.db (table rekts, created by store.SCHEMA); only the dashboard process writes them,
from the auto sell loop.
"""
import time

from . import store

REKT_USD = 25.0          # account value under this (2.5% of the start) = rekt; 4.11. Mario sat at $12.61 = -98.7%, Nicholas: "pao na 0"
CHECK_EVERY_S = 300
BOT = "bot"
_LAST = {"ts": 0}


def rows(con, user=None):
    q, a = "SELECT * FROM rekts", ()
    if user:
        q, a = q + " WHERE user=?", (user,)
    try:
        return [dict(r) for r in con.execute(q + " ORDER BY ts", a)]
    except Exception:  # noqa: BLE001 - old db without the table: nobody was rekt
        return []


def counts(con):
    out = {}
    for r in rows(con):
        out[r["user"]] = out.get(r["user"], 0) + 1
    return out


def since(con, user):
    """Start of the user's current round (0 = never rekt, the whole history counts)."""
    try:
        row = con.execute("SELECT MAX(ts) FROM rekts WHERE user=?", (user,)).fetchone()
    except Exception:  # noqa: BLE001
        return 0
    return row[0] or 0 if row else 0


def mark(con, user, equity, note="", now=None):
    now = int(now or time.time())
    n = len(rows(con, user)) + 1
    con.execute("INSERT INTO rekts (user, ts, round, equity, note) VALUES (?,?,?,?,?)",
                (user, now, n + 1, equity, note))
    con.commit()
    return n


def skulls(n, profit=None):
    """Rekt badge for the board (empty for 0): 💀 rekt · N. krug; 🔄 comeback when the round after a rekt is in profit.
    10.11. (Jure: "uz znak rekt i da je ovo drugi krug"): the word and the round number, not only 💀×N."""
    if not n:
        return ""
    back = (' <span class=rekt title="Nakon rekta je ponovo u plusu">🔄 comeback</span>'
            if profit is not None and profit > 0 else "")
    times = f"×{n}" if n > 1 else ""
    return (f'<span class=rekt title="Pao na nulu {n}× i krenuo ispočetka s novih ${store.START_USD:,.0f}">'
            f'💀 rekt{times} · {n + 1}. krug</span>{back}')


# 10.11. (Jure: "dodaj igračima koji su pali na nulu novih $1000"): since 4.11. only Mario was ever rekt, because a
# player holding a token that has no price at all was skipped for good ("an outage must not wipe an account"), and a
# rugged token never gets a price again. A position counts as worth $0 when its token is in the rug archive
# (rugfilter/archive.py) or when it has had no price at every check for NO_PRICE_DEAD_S; a short outage still
# protects the account. The first moment without a price is kept in league.db, so deploys do not reset the clock.
NO_PRICE_DEAD_S = 6 * 3600
NOPRICE_SCHEMA = "CREATE TABLE IF NOT EXISTS rekt_noprice (trade_id INTEGER PRIMARY KEY, first_ts INTEGER)"


def _rugs():
    try:
        from rugfilter import archive
        return archive.blocked()
    except Exception:  # noqa: BLE001 - no archive: only the no-price clock decides
        return frozenset()


def _no_price_since(con, opened, mk, now):
    """trade id -> first time it was seen without a price (rows of trades that have a price again are dropped)."""
    con.execute(NOPRICE_SCHEMA)
    with_price = [t["id"] for t in opened if t["token"] in mk]
    without = [t["id"] for t in opened if t["token"] not in mk]
    if with_price:
        con.execute("DELETE FROM rekt_noprice WHERE trade_id IN (%s)" % ",".join("?" * len(with_price)), with_price)
    # 10.11. (pregled): clocks of trades that are no longer open (sold, rekt) go too, so the table stays small
    con.execute("DELETE FROM rekt_noprice WHERE trade_id NOT IN (SELECT id FROM trades WHERE status='open')")
    con.executemany("INSERT OR IGNORE INTO rekt_noprice VALUES (?, ?)", [(i, int(now)) for i in without])
    con.commit()
    if not without:
        return {}
    return dict(con.execute("SELECT trade_id, first_ts FROM rekt_noprice WHERE trade_id IN (%s)"
                            % ",".join("?" * len(without)), without))


def check_players(con, market, now=None, rugs=None):
    """Rekt every player whose account is under REKT_USD. Open positions are valued at the live price. A position
    without any price stops the check for that player (an outage must not wipe an account) unless the token is
    rug-archived or has had no price for NO_PRICE_DEAD_S: then it is worth $0 and is closed at 0 with the rekt.
    Returns [(user, equity, n)]."""
    now = now or time.time()
    out = []
    opened = store.trades(con, status="open")
    mk = market({t["token"] for t in opened}) if opened else {}
    # 10.11. (pregled): not one open token has a price = the price source is down, not every token dead: no clock
    # starts or runs (a 6-h outage would otherwise close every open position at $0); a rug-archived token stays dead
    outage = bool(opened) and not mk
    since = {} if outage or not opened else _no_price_since(con, opened, mk, now)
    if rugs is None:
        rugs = _rugs() if any(t["token"] not in mk for t in opened) else frozenset()   # the archive only when needed
    for u in store.users():
        acc = store.account(con, u)
        mine = [t for t in opened if t["user"] == u]
        priced, waiting = {}, False
        for t in mine:
            if t["token"] in mk:
                priced[t["id"]] = (mk[t["token"]][0], mk[t["token"]][1])
            elif t["token"] in rugs or (not outage and now - since.get(t["id"], now) >= NO_PRICE_DEAD_S):
                priced[t["id"]] = (0, 0)   # dead token: worth what auto sell already took out, nothing more
            else:
                waiting = True
        if waiting:
            continue
        val = sum(store.value(t, *priced[t["id"]]) for t in mine)
        equity = acc["cash"] + val
        if equity >= REKT_USD:
            continue
        for t in mine:
            price, liq = priced[t["id"]]
            store.sell(con, u, t["id"], price or 0, liq,
                       note="rekt: račun pao na nulu" if price else "rekt: token bez cijene (rug ili mrtav), vrijedi $0")
        n = mark(con, u, round(equity, 2), "račun pao ispod $%.0f" % REKT_USD, now)
        out.append((u, equity, n))
    return out


def check_bot(con, equity, now=None):
    """New round for the bot when its board account is under REKT_USD. Returns the new round number or None."""
    if equity is None or equity >= REKT_USD:
        return None
    mark(con, BOT, round(equity, 2), "bot pao ispod $%.0f" % REKT_USD, now)
    return len(rows(con, BOT)) + 1


def maybe_check(con, market, bot_equity=None, now=None):
    """Called from the auto sell loop; at most every CHECK_EVERY_S. Returns log lines."""
    now = now or time.time()
    if now - _LAST["ts"] < CHECK_EVERY_S:
        return []
    _LAST["ts"] = now
    lines = [f"{u} rekt ({n}×) na ${e:,.2f}, novi start ${store.START_USD:,.0f}" for u, e, n in check_players(con, market, now)]
    if bot_equity is not None:
        try:
            eq = bot_equity()
        except Exception as e:  # noqa: BLE001 - paper.db unreadable: no bot round this time
            eq = None
            lines.append(f"bot: stanje nije pročitano ({type(e).__name__})")
        r = check_bot(con, eq, now)
        if r:
            lines.append(f"bot rekt na ${eq:,.2f}, kreće {r}. krug")
    return lines
