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
    """💀×N badge for the board (empty for 0); 🔄 comeback when the round after a rekt is in profit."""
    if not n:
        return ""
    back = (' <span class=rekt title="Nakon rekta je ponovo u plusu">🔄 comeback</span>'
            if profit is not None and profit > 0 else "")
    return (f'<span class=rekt title="Pao na nulu {n}× i krenuo ispočetka s novih ${store.START_USD:,.0f}">'
            f'💀×{n}</span>{back}')


def check_players(con, market, now=None):
    """Rekt every player whose account is under REKT_USD. Open positions are valued at the live price; a player with
    an open position that has no price at all is skipped (an outage must not wipe an account). Returns
    [(user, equity)]."""
    out = []
    opened = store.trades(con, status="open")
    mk = market({t["token"] for t in opened}) if opened else {}
    for u in store.users():
        acc = store.account(con, u)
        mine = [t for t in opened if t["user"] == u]
        if any(t["token"] not in mk for t in mine):
            continue
        val = sum(store.value(t, mk[t["token"]][0], mk[t["token"]][1]) for t in mine)
        equity = acc["cash"] + val
        if equity >= REKT_USD:
            continue
        for t in mine:
            price, liq = mk[t["token"]][0], mk[t["token"]][1]
            store.sell(con, u, t["id"], price or 0, liq, note="rekt: račun pao na nulu")
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
