"""Demo praćenje novčanika koji kupuju prije pumpe i bundle novčanika (19.11., vlasnik: "dok je pravi novac isključen,
što više demo tradeova s praćenjem novčanika ... najvažniji su mi insajderski novčanici").

A DEMO source only: the account USER ("autopilot-novcanici", league.db) is hard-coded below; no flag mode, switch or
order makes this module trade another account, and nothing here calls the real executor. It runs under the flag
insajderi2 (trade/settings: NEVER_LIVE, paper on by default) inside league/auto.loop (run_ui.py, league.db's only
writer), next to insajderi/live.py.

  watched   insajderi.db: the "kupuje prije pumpe" groups (i2_pp cls prije_pumpe CONFIRMED: kind "prije_pumpe"; not yet
            confirmed, or cls kandidat: kind "prije_pumpe_kandidat") and the bundles (i2_bundle: kind "bundle"), all
            their wallets; insajderi/live.webhook_wallets puts them on the Helius webhook in that order (each event
            ~1 credit), before the old insider groups
  entry     a fresh buy (hype.db chain_trades, at most fresh_s old) of a watched wallet -> one entry of demo_sol (0.1 SOL)
            behind veliki/live.guards (bonded, not on the curve, MC >= 30k, liquidity >= 15k, no fake pool, not rugged,
            not in the rug archive; konsenzus/live.guards' liquidity >= 3 % of MC is left out, as for the midcaps: a
            20M token's 400k pool is deep). DEMO-ONLY EXCEPTION, as wallets/kopija_demo: trade/capgate (MC >= 5M) is NOT asked, so the
            owner's 2-15M band is copied too; 15-200M first: an entry under 15M MC only while open positions and
            today's entries are under pp_demo_low_share (60 %) of pp_demo_max_open / pp_demo_per_day
  exit      when any wallet of that group / bundle sells (kol/insiders.sold_since), else the lot's stop -stop and time
            stop hold_h (league/auto tpsl): the copy test's exit (insajderi/copy.simulate), so both measure one thing
  source    "prije pumpe: <group 6>" / "prije pumpe kandidat: <group 6>" / "bundle: <bundle 6>" + the wallet and delay
league.db pp_trades: one row per (account, token) with the MC bucket at entry (<2M, 2-15M, 15-200M, >200M).
"""
import json
import time

from insajderi import live as ilive, store

USER = "autopilot-novcanici"   # = league/store.WALLET_DEMO_USER (19.11.: also kopija dokazanih and insajderi2)
SRC = {"prije_pumpe": "prije pumpe", "prije_pumpe_kandidat": "prije pumpe kandidat", "bundle": "bundle"}
PREFIX = "demo praćenje novčanika: "
RUN_EVERY_S = 10
SCHEMA = """CREATE TABLE IF NOT EXISTS pp_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, kind TEXT, gid TEXT, wallet TEXT,
    buy_ts INTEGER, opened_ts INTEGER, trade_id INTEGER, size_usd REAL, entry_mcap REAL, mc_bucket TEXT, liq REAL,
    status TEXT, closed_ts INTEGER, pnl_usd REAL, ret REAL, exit_reason TEXT, UNIQUE (user, token));
CREATE INDEX IF NOT EXISTS pp_trades_status ON pp_trades (status, user);"""
_LAST = {"ts": 0.0}
_WATCH = {"ts": 0.0, "v": []}
_TRIED = {}


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pp_trades'").fetchone() is None:
        con.executescript(SCHEMA)


def bucket(mcap):
    """The MC bucket at entry of every wallet-following demo (19.11.)."""
    if mcap is None:
        return "?"
    if mcap < 2e6:
        return "<2M"
    if mcap < 15e6:
        return "2-15M"
    if mcap <= 200e6:
        return "15-200M"
    return ">200M"


def watched(path=None, max_age_s=60):
    """[(kind, gid, [wallets])] best first: confirmed pump groups, bundles, candidates (cached a minute)."""
    if path is None and _WATCH["ts"] and time.monotonic() - _WATCH["ts"] < max_age_s:
        return _WATCH["v"]
    con = store.ro(path or store.db_path())
    out = []
    if con is not None:
        try:
            def rows(sql, kind):
                for gid, m in store.q(con, sql):
                    try:
                        ms = json.loads(m or "[]")
                    except ValueError:
                        continue
                    if ms:
                        out.append((kind, gid, ms))
            rows("SELECT owner, members FROM i2_pp WHERE cls = 'prije_pumpe' AND confirmed_ts IS NOT NULL "
                 "ORDER BY n_pumps15 DESC, n_tokens DESC", "prije_pumpe")
            rows("SELECT bid, members FROM i2_bundle ORDER BY n_pumps15 DESC, n_pumps DESC", "bundle")
            rows("SELECT owner, members FROM i2_pp WHERE (cls = 'prije_pumpe' AND confirmed_ts IS NULL) OR cls = 'kandidat' "
                 "ORDER BY (cls = 'prije_pumpe') DESC, n_pumps15 DESC, n_tokens DESC", "prije_pumpe_kandidat")
        finally:
            con.close()
    if path is None:
        _WATCH.update(ts=time.monotonic(), v=out)
    return out


def _short(gid):
    g = str(gid or "?")
    return g[2:8] if g[:2] in ("o:", "p:") else g[:6]


def enter(con, tok, kind, gid, wallet, buy_ts, mq, now, sol, c):
    """One demo entry on USER; (text or None, why not or None)."""
    from league import auto, copy as lcopy, store as lstore
    from veliki import live as vlive
    if con.execute("SELECT 1 FROM pp_trades WHERE user=? AND token=?", (USER, tok)).fetchone():
        return None, None
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (USER, tok)).fetchone():
        return None, "račun već drži token"
    mx, per = int(c["pp_demo_max_open"]), int(c["pp_demo_per_day"])
    n_open = con.execute("SELECT COUNT(*) FROM pp_trades WHERE user=? AND status='open'", (USER,)).fetchone()[0]
    if n_open >= mx:
        return None, f"već {n_open} otvorenih (strop {mx})"
    n_day = con.execute("SELECT COUNT(*) FROM pp_trades WHERE user=? AND opened_ts >= ?",
                        (USER, lcopy._day_start(int(now)))).fetchone()[0]
    if n_day >= per:
        return None, f"dnevni strop ({per}) potrošen"
    why = vlive.guards(tok, mq)
    if why:
        return None, why
    price, liq, _url, mcap = mq[:4]
    b = bucket(mcap)
    low = float(c["pp_demo_low_share"])
    if b in ("<2M", "2-15M") and (n_open >= low * mx or n_day >= low * per):
        return None, f"MC ispod 15M: mjesta iznad {low:.0%} stropa čuvaju se za 15-200M"
    from veliki import symbols
    sym = symbols.resolve(tok, mq[4] if len(mq) > 4 else None) or tok[:6]
    size_usd = float(c["demo_sol"]) * sol
    src = f"{SRC[kind]}: {_short(gid)} ({wallet[:4]}… kupio prije {int(now - buy_ts)} s, MC {b})"[:200]
    try:   # the demo-only exception: trade/capgate is deliberately not asked here (see the module text)
        tid = lstore.buy(con, USER, tok, sym, size_usd, price, liq, src, None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})"
    try:
        auto.set_auto(con, USER, tid, "tpsl", "", f"-{float(c['stop']) * 100:g}%", hold_s=int(float(c["hold_h"]) * 3600))
    except ValueError as e:
        print(f"{PREFIX}{tok[:6]}: stop lota nije postavljen ({e})", flush=True)
    row = con.execute("SELECT opened_ts, size_usd FROM trades WHERE id=?", (tid,)).fetchone()
    con.execute("INSERT OR IGNORE INTO pp_trades (user, token, symbol, kind, gid, wallet, buy_ts, opened_ts, trade_id, "
                "size_usd, entry_mcap, mc_bucket, liq, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'open')",
                (USER, tok, sym, kind, gid, wallet, int(buy_ts), row[0], tid, row[1], mcap, b, liq))
    con.commit()
    return f"{SRC[kind]} demo ulaz {sym} ({_short(gid)}) na MC ${mcap or 0:,.0f} ({b})", None


def exits(con, market_fn=None, hype_db=None):
    from kol import insiders
    from league import copy as lcopy, store as lstore
    rows = con.execute("SELECT id, token, gid, trade_id, opened_ts FROM pp_trades WHERE status='open'").fetchall()
    if not rows:
        return []
    groups = {gid: ms for _k, gid, ms in watched()}
    todo = []
    for kid, tok, gid, tid, opened in rows:
        ms = groups.get(gid) or []
        if ms and insiders.sold_since(hype_db or ilive._hype_db(), tok, opened, list(ms)):
            todo.append((kid, tok, tid))
    if not todo:
        return []
    mk = (market_fn or lcopy.market)(sorted({t[1] for t in todo})) or {}
    done = []
    for kid, tok, tid in todo:
        q = mk.get(tok)
        if not q or not q[0]:
            continue
        try:
            lstore.sell(con, USER, tid, q[0], q[1], note="prije pumpe / bundle: grupa prodaje", mcap=q[3],
                        exit_rule="wallet_sold")
        except ValueError:
            pass
        done.append((USER, f"demo praćenje izlaz {tok[:6]}: grupa je prodala"))
    con.commit()
    return done


def sync_closed(con):
    for kid, tid, size in con.execute("SELECT id, trade_id, size_usd FROM pp_trades WHERE status='open'").fetchall():
        t = con.execute("SELECT status, closed_ts, pnl_usd, exit_rule FROM trades WHERE id=?", (tid,)).fetchone()
        if not t or t[0] != "closed":
            continue
        con.execute("UPDATE pp_trades SET status='closed', closed_ts=?, pnl_usd=?, ret=?, exit_reason=? WHERE id=?",
                    (t[1], t[2], (t[2] or 0) / size if size else None, t[3], kid))
    con.commit()


def run_once(con, market_fn=None, now=None, sol=None, force=False, hype_db=None):
    """One pass: exits, the closed rows, entries (flag insajderi2 paper / live only; the account is always USER, a
    demo account). [(user, text)]."""
    now = int(now or time.time())
    ensure(con)
    done = []
    day = now // 86400
    if _LAST.get("line_day") != day:   # the daily line over every wallet-following demo (first pass of a UTC day)
        _LAST["line_day"] = day
        try:
            print(line(con, now), flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{PREFIX}linija ({type(e).__name__}: {e})", flush=True)
    if con.execute("SELECT 1 FROM pp_trades WHERE status='open' LIMIT 1").fetchone():
        done += exits(con, market_fn, hype_db)
        sync_closed(con)
    if not force and time.monotonic() - _LAST["ts"] < RUN_EVERY_S:
        return done
    _LAST["ts"] = time.monotonic()
    groups = watched()
    if not groups:
        return done
    c = store.config()
    who, members = {}, {}
    for kind, gid, ms in groups:
        members[gid] = ms
        for w in ms:
            who.setdefault(w, (kind, gid))
    fresh = ilive.fresh_buys(set(who), now, int(c["fresh_s"]), hype_db)
    if not fresh:
        return done
    # 19.11. (vlasnik: "mjeri svaki ulaz u postocima"; league/mjera.py): every buy we SEE is measured first, before the
    # demo's flag, caps, one position per token and guards decide (its first quote is this pass's quote)
    from league import copy as lcopy, mjera
    new = [b for b in fresh if mjera.is_new(con, who[b[2]][0], who[b[2]][1], b[0], now)]
    entries_ok = ilive.mode() in ("paper", "live") and mjera.demo_entries_ok(con)
    buys = [b for b in fresh if b[0] not in _TRIED] if entries_ok else []
    toks = sorted({b[0] for b in new} | {b[0] for b in buys})
    mk = ((market_fn or lcopy.market)(toks) or {}) if toks else {}
    for tok, ts, w in new:
        kind, gid = who[w]
        mjera.record(con, kind, gid, w, tok, ts, now, mk.get(tok), members=members.get(gid))
    if not buys:
        return done
    if sol is None:
        from rangedca import trade as rtrade
        sol = rtrade.sol_usd()
    if not sol:
        return done
    for tok, ts, w in buys:
        kind, gid = who[w]
        text, why = enter(con, tok, kind, gid, w, ts, mk.get(tok), now, sol, c)
        if text:
            done.append((USER, text))
        elif why and why != "nema žive cijene":
            _TRIED[tok] = now
    for k in [k for k, t in _TRIED.items() if now - t > 3600]:
        _TRIED.pop(k, None)
    return done


# ---------- the daily line over every wallet-following demo -------------------------------------------------------------

def _net(trades_row, rt_floor=0.03):
    """Net return of one closed league trade after the REAL cost (trade/cost.round_trip at its size and pool, never
    under the 3 % floor), from its raw entry and exit prices; None without both."""
    entry_px, exit_px, size, liq = trades_row
    if not entry_px or not exit_px:
        return None
    try:
        from trade import cost
        rt = cost.round_trip(size, liq)
    except Exception:  # noqa: BLE001
        rt = rt_floor
    return exit_px / entry_px - 1 - max(rt, rt_floor)


def day_stats(con, now=None):
    """{source: {bucket or "svi": {"n", "mean_pct"}}} of the closed wallet-following demo trades, net of the real cost,
    plus "otvoreno" and "danas_zatvoreno". Sources: prije_pumpe, prije_pumpe_kandidat, bundle (pp_trades), kopija
    (kopija_trades), insajderi2 (insajderi2_trades)."""
    now = int(now or time.time())
    try:
        from veliki import replay
        floor = float(replay.RT_FLOOR)
    except Exception:  # noqa: BLE001
        floor = 0.03
    d0 = now - now % 86400
    out = {"otvoreno": 0, "danas_zatvoreno": 0}
    specs = (("pp_trades", "kind", "liq"), ("kopija_trades", "'kopija'", "liq"), ("insajderi2_trades", "'insajderi2'", "liq"))
    for table, kcol, lcol in specs:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
            continue
        out["otvoreno"] += con.execute(f"SELECT COUNT(*) FROM {table} WHERE status='open'").fetchone()[0]
        out["danas_zatvoreno"] += con.execute(f"SELECT COUNT(*) FROM {table} WHERE status='closed' AND closed_ts >= ?",
                                              (d0,)).fetchone()[0]
        for k, mc, ep, xp, size, liq in con.execute(
                f"SELECT {kcol}, x.entry_mcap, t.entry_px, t.exit_px, t.size_usd, x.{lcol} FROM {table} x JOIN trades t "
                f"ON t.id = x.trade_id WHERE x.status = 'closed'"):
            r = _net((ep, xp, size, liq), floor)
            if r is None:
                continue
            src = out.setdefault(k, {})
            for key in ("svi", bucket(mc)):
                s = src.setdefault(key, {"n": 0, "sum": 0.0})
                s["n"] += 1
                s["sum"] += r
    for k, v in out.items():
        if isinstance(v, dict):
            for s in v.values():
                s["mean_pct"] = round(100 * s.pop("sum") / s["n"], 2) if s["n"] else None
    return out


def line(con, now=None):
    """"demo praćenje novčanika: otvoreno <n>, danas zatvoreno <m>; prije pumpe 15-200M: n=.., srednje .. %; ..."."""
    st = day_stats(con, now)

    def part(src, key="svi"):
        s = (st.get(src) or {}).get(key) or {}
        return f"n={s.get('n', 0)}, srednje {s['mean_pct']:+.1f} %" if s.get("n") else "n=0"
    return (f"{PREFIX}otvoreno {st['otvoreno']}, danas zatvoreno {st['danas_zatvoreno']}; prije pumpe 15-200M: "
            f"{part('prije_pumpe', '15-200M')}; 2-15M: {part('prije_pumpe', '2-15M')}; kandidati: "
            f"{part('prije_pumpe_kandidat')}; bundle: {part('bundle')}; kopija dokazanih: {part('kopija')}; "
            f"insajderi2: {part('insajderi2')} (neto nakon stvarnog troška, nikad ispod 3 %; od 19.11. svi na računu "
            f"{USER}, kopija i insajderi2 od MC 2M s midcap čuvarima: ulazi prije i poslije se razlikuju)")
