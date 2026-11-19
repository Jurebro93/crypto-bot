"""The demo strategy of Insajderi 2.0 (flag insajderi2, trade/settings: paper on a demo account only: since 19.11. the
wallet-following demo account league/store.WALLET_DEMO_USER "autopilot-novcanici", before PAPER_USER, whose open rows
still exit there; 19.11. rule change: from MC 2M the midcap guards, wallets/kopija_demo.guards;
NEVER_LIVE, no owner switch: real money is the owner's decision later, with the numbers). Runs inside league/auto.loop
(run_ui.py, league.db's only writer) next to the source consensus, at most every RUN_EVERY_S.

  watched   the CONFIRMED insider groups (insajderi.db i2_groups, score.watched), all their wallets (the owner merge
            follows a rotation); chainwatch.wanted() adds up to max_webhook of them to the Helius webhook while the
            flag is paper / live (each webhook event costs ~1 credit: inside the tool's share)
  entry     a fresh buy (hype.db chain_trades, at most fresh_s old) of a watched wallet -> a demo entry of demo_sol,
            behind every hard rule of konsenzus/live.guards (bonded, MC >= 30k, liquidity, not rugged, the rug
            archive) AND trade/capgate (MC >= 5M; below only the demo's moonshot exception); first entry per token
  exit      when any wallet of that group sells (kol/insiders.sold_since on chain_trades), else the lot's own stop
            -stop and time stop hold_h (league/auto tpsl, every second)
league.db insajderi2_trades: one row per (account, token).
"""
import json
import os
import sqlite3
import time

from insajderi import store

FLAG = store.FLAG
SRC = "insajderi2"
RUN_EVERY_S = 15
SCHEMA = """CREATE TABLE IF NOT EXISTS insajderi2_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, owner TEXT, wallet TEXT, buy_ts INTEGER,
    opened_ts INTEGER, trade_id INTEGER, size_usd REAL, entry_mcap REAL, liq REAL, status TEXT, closed_ts INTEGER,
    pnl_usd REAL, ret REAL, exit_reason TEXT, UNIQUE (user, token));
CREATE INDEX IF NOT EXISTS insajderi2_trades_status ON insajderi2_trades (status, user);"""
_LAST = {"ts": 0.0}
_WATCH = {"ts": 0.0, "v": []}
_TRIED = {}


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='insajderi2_trades'").fetchone() is None:
        con.executescript(SCHEMA)


def mode():
    try:
        from trade import settings
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def watched(path=None, max_age_s=60):
    """[(owner, [wallets])] of the confirmed groups (cached a minute)."""
    if time.monotonic() - _WATCH["ts"] < max_age_s and _WATCH["ts"] and path is None:
        return _WATCH["v"]
    con = store.ro(path or store.db_path())
    v = []
    if con is not None:
        try:
            from insajderi import score
            v = score.watched(con)
        finally:
            con.close()
    if path is None:
        _WATCH.update(ts=time.monotonic(), v=v)
    return v


def webhook_wallets(limit=None, path=None):
    """Wallets for the Helius webhook (kol/chainwatch.wanted), ONLY while the flag is paper / live ([] otherwise), at
    most max_webhook (19.11.: 10 -> 135): the confirmed "kupuje prije pumpe" groups, the bundles, the candidate groups
    (insajderi/pp_live.watched), then the old confirmed insider groups, best group first."""
    if mode() not in ("paper", "live"):
        return []
    lim = int(limit if limit is not None else store.config()["max_webhook"])
    out = []
    try:
        from insajderi import pp_live
        for _k, _g, ms in pp_live.watched(path):
            for w in ms:
                if w not in out:
                    out.append(w)
    except Exception:  # noqa: BLE001 - the old groups still go
        pass
    for _o, ms in watched(path):
        for w in ms:
            if w not in out:
                out.append(w)
    return out[:lim]


def _hype_db():
    return os.environ.get("HYPE_DB") or os.path.join(store.ROOT, "hype.db")


def fresh_buys(members, now, fresh_s, hype_db=None):
    """[(token, ts, wallet)] of the watched wallets' buys in the last fresh_s seconds (hype.db chain_trades)."""
    if not members:
        return []
    hc = store.ro(hype_db or _hype_db())
    ws = sorted(members)
    out = []
    for i in range(0, len(ws), 400):
        ch = ws[i:i + 400]
        out += store.q(hc, f"SELECT mint, MIN(ts), wallet FROM chain_trades WHERE side = 'buy' AND ts >= ? AND wallet IN "
                           f"({','.join('?' * len(ch))}) GROUP BY mint, wallet", (int(now - fresh_s), *ch))
    if hc is not None:
        hc.close()
    return sorted(out, key=lambda r: r[1])


def enter(con, user, tok, owner, wallet, buy_ts, mq, now, sol, c):
    """One demo entry; (text or None, why not or None)."""
    from league import auto, copy as lcopy, store as lstore
    from trade import capgate
    if con.execute("SELECT 1 FROM insajderi2_trades WHERE user=? AND token=?", (user, tok)).fetchone():
        return None, None
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token"
    n_open = con.execute("SELECT COUNT(*) FROM insajderi2_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
    if n_open >= int(c["demo_max_open"]):
        return None, f"već {n_open} otvorenih (strop {c['demo_max_open']})"
    n_day = con.execute("SELECT COUNT(*) FROM insajderi2_trades WHERE user=? AND opened_ts >= ?",
                        (user, lcopy._day_start(int(now)))).fetchone()[0]
    if n_day >= int(c["demo_per_day"]):
        return None, f"dnevni strop ({c['demo_per_day']}) potrošen"
    from wallets import kopija_demo   # 19.11.: from MC 2M the midcap guards (see kopija_demo.guards)
    why = kopija_demo.guards(tok, mq)
    if why:
        return None, why
    price, liq, _url, mcap = mq[:4]
    from veliki import symbols   # 16.11.: run_ui's quote has no symbol; the mint's prefix only as the last resort
    sym = symbols.resolve(tok, mq[4] if len(mq) > 4 else None) or tok[:6]
    size_usd = float(c["demo_sol"]) * sol
    src = f"{SRC}: grupa {owner[:6]} ({wallet[:4]}… kupio prije {int(now - buy_ts)} s)"[:200]
    gw, src, size_usd = capgate.check(tok, mcap, src, user, size_usd, now, sol=sol, liq=liq, symbol=sym)
    if gw:
        return None, gw
    try:
        tid = lstore.buy(con, user, tok, sym, size_usd, price, liq, src, None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})"
    try:
        auto.set_auto(con, user, tid, "tpsl", "", f"-{float(c['stop']) * 100:g}%", hold_s=int(float(c["hold_h"]) * 3600))
    except ValueError as e:
        print(f"{store.PREFIX}{tok[:6]}: stop lota nije postavljen ({e})", flush=True)
    row = con.execute("SELECT opened_ts, size_usd FROM trades WHERE id=?", (tid,)).fetchone()
    con.execute("INSERT OR IGNORE INTO insajderi2_trades (user, token, symbol, owner, wallet, buy_ts, opened_ts, trade_id, "
                "size_usd, entry_mcap, liq, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,'open')",
                (user, tok, sym, owner, wallet, int(buy_ts), row[0], tid, row[1], mcap, liq))
    con.commit()
    return f"insajderi2 demo ulaz {sym} (grupa {owner[:6]}) na MC ${mcap or 0:,.0f}", None


def exits(con, market_fn=None, hype_db=None):
    """Sell the open demo rows whose group sold since our entry. [(user, text)]."""
    from kol import insiders
    from league import copy as lcopy, store as lstore
    rows = con.execute("SELECT id, user, token, owner, trade_id, opened_ts FROM insajderi2_trades WHERE status='open'"
                       ).fetchall()
    if not rows:
        return []
    groups = dict(watched())
    done = []
    todo = []
    for kid, user, tok, owner, tid, opened in rows:
        ms = groups.get(owner) or []
        if not ms:
            continue
        ts = insiders.sold_since(hype_db or _hype_db(), tok, opened, list(ms))
        if ts:
            todo.append((kid, user, tok, tid, ts))
    if not todo:
        return done
    mk = (market_fn or lcopy.market)(sorted({t[2] for t in todo})) or {}
    for kid, user, tok, tid, ts in todo:
        q = mk.get(tok)
        if not q or not q[0]:
            continue
        try:
            lstore.sell(con, user, tid, q[0], q[1], note="insajderi2: grupa prodaje", mcap=q[3], exit_rule="wallet_sold")
        except ValueError:
            pass   # already closed by its stop / time stop
        done.append((user, f"insajderi2 demo izlaz {tok[:6]}: grupa je prodala"))
    con.commit()
    return done


def sync_closed(con):
    for kid, user, tok, tid, size in con.execute(
            "SELECT id, user, token, trade_id, size_usd FROM insajderi2_trades WHERE status='open'").fetchall():
        t = con.execute("SELECT status, closed_ts, pnl_usd, exit_rule FROM trades WHERE id=?", (tid,)).fetchone()
        if not t or t[0] != "closed":
            continue
        con.execute("UPDATE insajderi2_trades SET status='closed', closed_ts=?, pnl_usd=?, ret=?, exit_reason=? WHERE id=?",
                    (t[1], t[2], (t[2] or 0) / size if size else None, t[3], kid))
    con.commit()


def run_once(con, market_fn=None, now=None, sol=None, force=False, hype_db=None):
    """One pass: exits of open rows, the closed rows, then entries (paper / live mode only). [(user, text)]."""
    now = int(now or time.time())
    ensure(con)
    done = []
    if con.execute("SELECT 1 FROM insajderi2_trades WHERE status='open' LIMIT 1").fetchone():
        done += exits(con, market_fn, hype_db)
        sync_closed(con)
    if mode() not in ("paper", "live"):
        return done
    if not force and time.monotonic() - _LAST["ts"] < RUN_EVERY_S:
        return done
    _LAST["ts"] = time.monotonic()
    groups = watched()
    if not groups:
        return done
    c = store.config()
    owner_of = {w: o for o, ms in groups for w in ms}
    buys = [b for b in fresh_buys(set(owner_of), now, int(c["fresh_s"]), hype_db) if ("*", b[0]) not in _TRIED]
    if not buys:
        return done
    from trade import settings
    from league import store as lstore   # 19.11.: the wallet-following demo account (before: PAPER_USER, whose open
    user = lstore.WALLET_DEMO_USER        # rows still exit by their own rules); never LEAGUE_USER (NEVER_LIVE)
    if sol is None:
        from rangedca import trade as rtrade
        sol = rtrade.sol_usd()
    if not sol:
        return done
    from league import copy as lcopy
    mk = (market_fn or lcopy.market)(sorted({b[0] for b in buys})) or {}
    for tok, ts, w in buys:
        text, why = enter(con, user, tok, owner_of[w], w, ts, mk.get(tok), now, sol, c)
        if text:
            done.append((user, text))
        elif why:
            _TRIED[("*", tok)] = now
            print(f"{store.PREFIX}{tok[:6]}: demo nije kupio ({why})", flush=True)
    for k in [k for k, t in _TRIED.items() if now - t > 3600]:
        _TRIED.pop(k, None)
    return done


def demo_stats(lcon=None):
    """{"n", "open", "pnl_usd", "ev_pct", "ci90_lo_pct"} of the demo's closed rows, net of the calibrated cost."""
    from league import store as lstore
    from trade import cost, edge, settings
    own = lcon is None
    rows, n_open = [], 0
    try:
        if own:
            lcon = store.ro(lstore.DB)
        if lcon is not None:
            us = (settings.PAPER_USER, lstore.WALLET_DEMO_USER)   # 19.11.: both accounts (see run_once)
            rows = lcon.execute("SELECT pnl_usd, ret FROM insajderi2_trades WHERE user IN (?, ?) AND status='closed'",
                                us).fetchall()
            n_open = lcon.execute("SELECT COUNT(*) FROM insajderi2_trades WHERE user IN (?, ?) AND status='open'",
                                  us).fetchone()[0]
    except sqlite3.Error:
        pass
    finally:
        if own and lcon is not None:
            lcon.close()
    rets = [r + cost.demo_adjust() for _p, r in rows if r is not None]
    s = edge.ev_stats(rets)
    return {"n": len(rows), "open": n_open, "pnl_usd": round(float(sum(p or 0 for p, _r in rows)), 2),
            "ev_pct": round(s["ev"] * 100, 2) if s["ev"] is not None else None,
            "ci90_lo_pct": round(s["lo90"] * 100, 2) if s["lo90"] is not None else None,
            "groups": len(watched()), "flag": mode(), "detail": json.dumps({"real_money": "NEVER_LIVE"})}
