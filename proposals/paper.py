"""Paper proof of the proposals (flag proposals G21 in paper): the demo account PAPER_USER (autopilot-paper) takes
every shown proposal with its exit, so each strategy gets its own paper record. Runs inside league/auto.loop (20 s;
run_ui.py is league.db's only writer). run_trade.py never mirrors PAPER_USER: no real money moves.

  off / shadow   nothing (shadow = the list and the measurements only)
  paper / live   one demo lot per proposal (status novo, made in the last FRESH_S), size = the proposal's size at the
                 SOL price, only when the demo account does not already hold the token; its exit = the proposal's TP /
                 SL as the lot's own TP/SL (league/auto "tpsl", MC levels or %, hold time for a time stop that takes
                 everything out) and the full exit plan (league/exitplan, accounts [PAPER_USER]) when no other plan is
                 active on the token. live is never set by code and is refused (live_refusal): the real account only
                 buys on the owner's tap (Kupi on the Autopilot card); Grok autotrade may read get_proposals and buy
                 through execute_trade within its own limits, as before.
league.db proposal_trades: one row per proposal and account, closed from the lot's own result (trades.ret).
"""
import json
import sqlite3
import time

from . import store

FLAG = "proposals"
SRC = "prijedlog (demo)"
FRESH_S = 600
SCHEMA = """CREATE TABLE IF NOT EXISTS proposal_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, proposal_id INTEGER, token TEXT, strategy TEXT, sources TEXT,
    trade_id INTEGER, opened_ts INTEGER, status TEXT, closed_ts INTEGER, ret REAL, UNIQUE (user, proposal_id));
CREATE INDEX IF NOT EXISTS proposal_trades_status ON proposal_trades (status, user);"""


def ensure(con):
    con.executescript(SCHEMA)


def mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def live_refusal(con, now=None):
    """trade/settings.LIVE_GATES: proposals never go live (no automatic path to the real account)."""
    return ("prijedlozi nemaju live: pravi račun kupuje prijedlog samo na tvoj dodir (Kupi), demo račun ih dokazuje "
            "u paper modu")


def _sl_default():
    """The owner's default stop (trade settings sl_default): a plan's stop may not be looser."""
    try:
        from trade import executor, settings
        tc = settings.connect()
        try:
            return float(settings.merged(executor.load_config(), tc).get("sl_default") or 60)
        finally:
            tc.close()
    except Exception:  # noqa: BLE001
        return 60.0


def fresh(now, path=None):
    """Proposals with status novo made in the last FRESH_S (proposals.db, read-only)."""
    con = store.ro(path)
    if con is None:
        return []
    try:
        return store.read(con, "status='novo' AND created_ts >= ?", (int(now) - FRESH_S,), order="id", limit=50)
    finally:
        con.close()


def sync_closed(con, user):
    """Close our rows whose demo lot was sold (trades.status closed): ret from the lot."""
    for pid_, tid in con.execute("SELECT id, trade_id FROM proposal_trades WHERE status='open' AND user=?", (user,)).fetchall():
        t = con.execute("SELECT status, ret, closed_ts FROM trades WHERE id=?", (tid,)).fetchone()
        if t and t[0] == "closed":
            con.execute("UPDATE proposal_trades SET status='closed', ret=?, closed_ts=? WHERE id=?", (t[1], t[2], pid_))


def run_once(con, market_fn=None, now=None, path=None, sol=None):
    """One entry pass: [(user, text)]. Only in paper / live, only on PAPER_USER."""
    m = mode()
    if m not in ("paper", "live"):
        return []
    from league import auto, copy, exitplan
    from league import store as lstore
    from trade import settings
    now = int(now or time.time())
    user = settings.PAPER_USER
    ensure(con)
    sync_closed(con, user)
    con.commit()
    ps = fresh(now, path)
    if not ps:
        return []
    taken = {p for (p,) in con.execute("SELECT proposal_id FROM proposal_trades WHERE user=?", (user,))}
    ps = [p for p in ps if p["id"] not in taken]
    if not ps:
        return []
    if sol is None:
        from rangedca import trade as rtrade
        sol = rtrade.sol_usd()
    if not sol:
        return []
    mk = (market_fn or copy.market)(sorted({p["token"] for p in ps})) or {}
    done = []
    for p in ps:
        tok, r = p["token"], p.get("row") or {}
        mq = mk.get(tok)
        if not mq or not mq[0]:
            continue
        if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
            continue   # already held by the demo account: never doubled
        price, liq, _url, mcap = mq[:4]
        if (mcap or 0) < 30_000 or (liq or 0) < 20_000 or copy._rugged(tok, mcap, liq):
            continue
        size = float(p.get("size_sol") or 0)
        if size < 0.005:
            continue
        b = r.get("buy") or {}
        try:
            tid = lstore.buy(con, user, tok, p.get("symbol"), size * sol, price, liq,
                             f"{SRC}: {p.get('strategy')}", None, mcap)
        except ValueError as e:
            print(f"prijedlozi paper {tok[:6]}: ulaz nije prošao ({e})", flush=True)
            continue
        try:
            auto.set_auto(con, user, tid, "tpsl", b.get("tp") or "", b.get("sl") or "", hold_s=b.get("hold_s"))
        except ValueError as e:   # e.g. an MC target already under the entry: the stop alone, then smart sell
            try:
                auto.set_auto(con, user, tid, "tpsl", "", b.get("sl") or "", hold_s=b.get("hold_s"))
            except ValueError:
                auto.set_auto(con, user, tid, "smart")
            print(f"prijedlozi paper {tok[:6]}: TP iz prijedloga nije postavljen ({e})", flush=True)
        plan = dict(r.get("exit_plan") or {})
        if plan and exitplan.active(con, tok) is None:
            plan["accounts"] = [user]
            sl_default = _sl_default()
            try:
                exitplan.set_plan(con, tok, plan, sl_default, client=f"prijedlog #{p['id']}", now=now)
            except ValueError as e:
                print(f"prijedlozi paper {tok[:6]}: plan izlaza nije postavljen ({e})", flush=True)
        con.execute("INSERT OR IGNORE INTO proposal_trades (user, proposal_id, token, strategy, sources, trade_id, "
                    "opened_ts, status) VALUES (?,?,?,?,?,?,?,?)",
                    (user, p["id"], tok, p.get("strategy"), json.dumps(p.get("sources") or []), tid, now, "open"))
        con.commit()
        done.append((user, f"prijedlog #{p['id']} ({p.get('strategy')}) {p.get('symbol') or tok[:6]}: {size:g} SOL na MC "
                           f"${mcap or 0:,.0f}, izlaz {b.get('tp')} / {b.get('sl')}"))
    return done


def proof(lcon=None):
    """{strategy: {"n", "hits", "hit_rate", "ev_pct"}} of the demo account's closed proposal trades (by the
    proposal's primary strategy), plus "all"."""
    from trade import settings
    own = lcon is None
    if lcon is None:
        try:
            from league import store as lstore
            lcon = sqlite3.connect(f"file:{lstore.DB}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return {}
    try:
        rows = lcon.execute("SELECT strategy, ret FROM proposal_trades WHERE user=? AND status='closed' AND ret IS NOT "
                            "NULL", (settings.PAPER_USER,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        if own:
            lcon.close()
    by = {}
    for s, r in rows:
        by.setdefault(s, []).append(r)
        by.setdefault("all", []).append(r)
    return {s: {"n": len(xs), "hits": sum(1 for x in xs if x > 0), "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3),
                "ev_pct": round(sum(xs) / len(xs) * 100, 2)} for s, xs in by.items()}
