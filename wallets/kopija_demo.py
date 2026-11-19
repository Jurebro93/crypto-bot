"""Demo kopije dokazanih novčanika (16.11.2026, vlasnik: "Nađi mi profitabilnu strategiju ... sve resurse"): the
prospective half of wallets/kopija.py. The DEMO account (19.11.: league/store.WALLET_DEMO_USER "autopilot-novcanici",
the one account of every wallet-following demo; until 19.11. trade/settings.PAPER_USER, whose open copies still exit
there; hard-coded below: no switch, no order and no flag mode ever makes this module trade another account) copies every fresh buy of a wallet that is
"dokazan dvaput" and "kopirljiv" right now, and each copy keeps the wallet, his price and ours and the delay, so the
report can put his trade next to ours.

Flag kopija_dokazani (trade/settings: NEVER_LIVE, a PROFILE flag; default paper): paper = the demo account copies;
off / shadow = nothing is entered (open copies still close by their exits).

  whom      wallets/dokazani.current() ("dokazan dvaput", itself only wallets that pass dokazani.copyable) that the copy
            ranking calls copyable (wallets/rang: median entry liquidity 15k+), minus wallets/hygiene's bad labels and
            bots. The same list the Helius webhook already follows (kol/chainwatch.wanted), so NO new paid volume.
  entry     a buy of such a wallet in hype.db chain_trades (the webhook; PumpPortal's mirror) at most FRESH_S old, the
            first copy per token, behind the hard rules of konsenzus/live.guards (bonded, MC >= 30k, liquidity >= 15k,
            not rugged, not in the rug archive); 19.11. (rule change): from MC 2M veliki/live.guards instead (no
            "liquidity >= 3 % of MC"; guards() below). DEMO-ONLY EXCEPTION: trade/capgate (MC >= 5M) is NOT asked here, so
            the copy is measured under 5M too; the real account's gate and every real path are untouched (this module
            never calls them and never trades LEAGUE_USER).
  caps      DEMO_SOL (0.1 SOL, the real stake) a copy, MAX_OPEN open, PER_DAY a Zagreb day, one position a token
  exit      the copier's exit the replay found best (wallets/kopija.latest()["demo_exit"]); before any result: when he
            sells (his first sale in chain_trades), else our stop -20 %
  his price SOL per token of his own fill: the webhook payload's swap (note_fills, kept in this process), else
            hype.db live_trades, else wallets.db wallet_trades by signature (fill_his, when the scorer has read it);
            unknown stays NULL and the report says for how many copies it is known

league.db kopija_trades: one row per (account, token). Runs inside league/auto.loop (run_ui.py, league.db's only
writer), also under the owner switch fokus_midcap (a demo measurement with its own caps).
"""
import os
import sqlite3
import time

FLAG = "kopija_dokazani"
SRC = "kopija dokazanih"
PREFIX = "kopija dokazanih: "
DEMO_SOL = 0.1
# 19.11. (vlasnik: dok je pravi novac isključen "što više demo tradeova s praćenjem novčanika"): 10 / 30 -> 40 / 200
MAX_OPEN = 40
PER_DAY = 200
FRESH_S = 180          # the replay's largest delay: an older buy is somebody else's trade by now
STOP = 0.20
HOLD_H = 24
RUN_EVERY_S = 5
FILL_EVERY_S = 600
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = """CREATE TABLE IF NOT EXISTS kopija_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, wallet TEXT, buy_sig TEXT, buy_ts INTEGER,
    his_sol REAL, his_px_sol REAL, opened_ts INTEGER, delay_s INTEGER, our_px_usd REAL, sol_usd REAL, our_px_sol REAL,
    trade_id INTEGER, size_usd REAL, entry_mcap REAL, liq REAL, exit_plan TEXT, status TEXT, closed_ts INTEGER,
    pnl_usd REAL, ret REAL, exit_reason TEXT, his_sell_ts INTEGER, his_sell_px_sol REAL, exit_delay_s INTEGER,
    our_exit_px_usd REAL, UNIQUE (user, token));
CREATE INDEX IF NOT EXISTS kopija_trades_status ON kopija_trades (status, user);"""
_LAST = {"ts": 0.0, "fill": 0.0}
_WHO = {"ts": 0.0, "v": frozenset()}
_EXIT = {"ts": 0.0, "v": None}
_TRIED = {}
_SAID = {}
NO_PRICE = "nema žive cijene"   # konsenzus/live.guards' answer without a quote
_FILLS = {}            # (wallet, mint, side) -> (ts, SOL per token), newest only; bounded by FILLS_MAX
FILLS_MAX = 4000


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kopija_trades'").fetchone() is None:
        con.executescript(SCHEMA)


def mode():
    try:
        from trade import settings
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def demo_user():
    """The only account this module trades NEW copies on: the wallet-following demo account (19.11.: league/store.
    WALLET_DEMO_USER, autopilot-novcanici; before 19.11. the demo account PAPER_USER, where copies opened then still
    exit by their own rules: exits() and sync_closed() follow every open row whatever its user). Never LEAGUE_USER."""
    from league import store as lstore
    return lstore.WALLET_DEMO_USER


def demo_users():
    """Every account this module's rows can be on: the wallet demo account and, before 19.11., PAPER_USER."""
    from trade import settings
    return (demo_user(), settings.PAPER_USER)


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _hype_db():
    return os.environ.get("HYPE_DB") or os.path.join(ROOT, "hype.db")


def targets(now=None, wallet_db=None, max_age_s=60):
    """The wallets copied right now: proven twice AND copyable by the ranking, minus bad labels / bots (cached a
    minute; wallet_db given = no cache, tests)."""
    if wallet_db is None and _WHO["ts"] and time.monotonic() - _WHO["ts"] < max_age_s:
        return _WHO["v"]
    from wallets import dokazani, hygiene, rang
    proven = dokazani.current(wallet_db)
    ok = {r["target"] for r in rang.ranked("wallet", wallet_db, copyable=True)}
    ws = sorted(proven & ok)
    if ws:
        fs = hygiene.facts(ws, wallet_db, _hype_db())
        t = int(now or time.time())
        ws = [w for w in ws if (hygiene.why(fs.get(w) or {}, t) or ("", ""))[0] not in ("label", "bot")]
    v = frozenset(ws)
    if wallet_db is None:
        _WHO.update(ts=time.monotonic(), v=v)
    return v


def exit_plan(wallet_db=None, max_age_s=600):
    """The copier's exit in force: wallets/kopija's pick ("on" | "on_stop" | "on_stop_24h"), else its primary."""
    from wallets import kopija
    if wallet_db is None and _EXIT["v"] and time.monotonic() - _EXIT["ts"] < max_age_s:
        return _EXIT["v"]
    v = (kopija.latest(wallet_db) or {}).get("demo_exit")
    v = v if v in kopija.EXITS else kopija.PRIMARY[2]
    if wallet_db is None:
        _EXIT.update(ts=time.monotonic(), v=v)
    return v


# ---------- his own fill ------------------------------------------------------------------------------------------------

def note_fills(payload, rows):
    """kol/chainwatch.ingest (the same process as league/auto.loop): the SOL per token of each swap in a Helius
    enhanced payload, kept in memory for the copy made seconds later. rows: chainwatch.parse's [(sig, wallet, mint,
    side, ts, sol)]. Never raises; nothing is written."""
    try:
        qty = {}
        for tx in payload if isinstance(payload, list) else [payload]:
            if not isinstance(tx, dict):
                continue
            w, sig = tx.get("feePayer"), tx.get("signature")
            for t in tx.get("tokenTransfers") or []:
                m = t.get("mint")
                if w and m and w in (t.get("toUserAccount"), t.get("fromUserAccount")):
                    qty[(sig, w, m)] = qty.get((sig, w, m), 0.0) + abs(float(t.get("tokenAmount") or 0))
        for sig, w, mint, side, ts, sol in rows or ():
            q = qty.get((sig, w, mint))
            if sol and q and side in ("buy", "sell"):
                _FILLS[(w, mint, side)] = (int(ts or 0), float(sol) / q)
        while len(_FILLS) > FILLS_MAX:
            _FILLS.pop(next(iter(_FILLS)))
    except Exception:  # noqa: BLE001 - bookkeeping for a demo row: never the webhook's problem
        pass


def his_px(wallet, mint, side, ts, hype_db=None, tol_s=5):
    """His fill (SOL per token) of the swap at ts: the webhook's own numbers, else the PumpPortal row; None unknown."""
    f = _FILLS.get((wallet, mint, side))
    if f and abs(f[0] - int(ts)) <= tol_s:
        return f[1]
    hc = _ro(hype_db or _hype_db())
    try:
        r = _q(hc, "SELECT price_sol FROM live_trades WHERE wallet=? AND mint=? AND side=? AND ts BETWEEN ? AND ? AND "
                   "price_sol > 0 ORDER BY ABS(ts - ?) LIMIT 1",
               (wallet, mint, side, int(ts) - tol_s, int(ts) + tol_s, int(ts)))
    finally:
        if hc is not None:
            hc.close()
    return float(r[0][0]) if r else None


def fill_his(con, wallet_db=None):
    """Copies whose his price is still unknown: wallets.db wallet_trades by the buy's signature (exact, once the
    scorer has read that transaction). Returns how many were filled."""
    rows = con.execute("SELECT id, wallet, token, buy_sig FROM kopija_trades WHERE his_px_sol IS NULL AND buy_sig IS NOT "
                       "NULL ORDER BY id DESC LIMIT 200").fetchall()
    if not rows:
        return 0
    from wallets import store as wstore
    wc = _ro(wallet_db or wstore.DB)
    n = 0
    for kid, w, tok, sig in rows:
        r = _q(wc, "SELECT tokens, sol FROM wallet_trades WHERE sig=? AND wallet=? AND mint=? AND kind='buy'", (sig, w, tok))
        if r and r[0][0] and r[0][1]:
            con.execute("UPDATE kopija_trades SET his_px_sol=? WHERE id=?", (abs(r[0][1]) / abs(r[0][0]), kid))
            n += 1
    if wc is not None:
        wc.close()
    if n:
        con.commit()
    return n


# ---------- entries and exits ------------------------------------------------------------------------------------------

def fresh_buys(wallets, now, fresh_s=FRESH_S, hype_db=None):
    """[(token, ts, wallet, sig, sol)] the first buy per (token, wallet) of `wallets` in the last fresh_s seconds."""
    if not wallets:
        return []
    hc = _ro(hype_db or _hype_db())
    ws, out = sorted(wallets), []
    for i in range(0, len(ws), 400):
        ch = ws[i:i + 400]
        out += _q(hc, f"SELECT mint, MIN(ts), wallet, sig, sol FROM chain_trades WHERE side = 'buy' AND ts >= ? AND "
                      f"wallet IN ({','.join('?' * len(ch))}) GROUP BY mint, wallet", (int(now - fresh_s), *ch))
    if hc is not None:
        hc.close()
    return sorted(out, key=lambda r: r[1])


GUARD_MID_MC = 2e6   # 19.11.: from this MC the midcap guards (veliki/live.guards), under it konsenzus/live.guards


def guards(tok, mq):
    """19.11. (rule change; copies before and after differ): a token with MC >= GUARD_MID_MC (2M) gets
    veliki/live.guards (bonded, MC >= 30k, liquidity >= 15k, no fake pool, not rugged, not archived: no "liquidity
    >= 3 % of MC", which kept most midcaps out); under 2M konsenzus/live.guards as before. Shared with insajderi/live."""
    if mq and len(mq) > 3 and mq[0] and (mq[3] or 0) >= GUARD_MID_MC:
        from veliki import live as vlive
        return vlive.guards(tok, mq)
    from konsenzus import live as klive
    return klive.guards(tok, mq)


def enter(con, tok, wallet, sig, buy_ts, his_sol, mq, now, sol, plan, hype_db=None):
    """One demo copy on the demo account; (text or None, why not or None)."""
    from league import auto, copy as lcopy, store as lstore
    user = demo_user()
    if con.execute("SELECT 1 FROM kopija_trades WHERE user=? AND token=?", (user, tok)).fetchone():
        return None, None
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token"
    n_open = con.execute("SELECT COUNT(*) FROM kopija_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
    if n_open >= MAX_OPEN:
        return None, f"već {n_open} otvorenih (strop {MAX_OPEN})"
    n_day = con.execute("SELECT COUNT(*) FROM kopija_trades WHERE user=? AND opened_ts >= ?",
                        (user, lcopy._day_start(int(now)))).fetchone()[0]
    if n_day >= PER_DAY:
        return None, f"dnevni strop ({PER_DAY}) potrošen"
    why = guards(tok, mq)
    if why:
        return None, why
    price, liq, _url, mcap = mq[:4]
    sym = (mq[4] if len(mq) > 4 else None) or tok[:6]
    size_usd = DEMO_SOL * sol
    src = f"{SRC}: {wallet[:4]}…{wallet[-4:]} kupio prije {int(now - buy_ts)} s"[:200]
    try:   # the demo-only exception: trade/capgate (MC >= 5M) is deliberately not asked here (see the module text)
        tid = lstore.buy(con, user, tok, sym, size_usd, price, liq, src, None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})"
    if plan != "on":
        try:
            auto.set_auto(con, user, tid, "tpsl", "", f"-{STOP * 100:g}%",
                          hold_s=int(HOLD_H * 3600) if plan == "on_stop_24h" else None)
        except ValueError as e:
            print(f"{PREFIX}{tok[:6]}: stop nije postavljen ({e})", flush=True)
    row = con.execute("SELECT opened_ts, size_usd FROM trades WHERE id=?", (tid,)).fetchone()
    con.execute("INSERT OR IGNORE INTO kopija_trades (user, token, symbol, wallet, buy_sig, buy_ts, his_sol, his_px_sol, "
                "opened_ts, delay_s, our_px_usd, sol_usd, our_px_sol, trade_id, size_usd, entry_mcap, liq, exit_plan, "
                "status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open')",
                (user, tok, sym, wallet, sig, int(buy_ts), his_sol, his_px(wallet, tok, "buy", buy_ts, hype_db), row[0],
                 int(row[0] - buy_ts), price, sol, price / sol if sol else None, tid, row[1], mcap, liq, plan))
    con.commit()
    return (f"kopija dokazanog {wallet[:4]}… demo ulaz {sym} na MC ${mcap or 0:,.0f}, {int(row[0] - buy_ts)} s nakon "
            "njega"), None


def exits(con, market_fn=None, hype_db=None, now=None):
    """Sell the open demo copies whose wallet sold since his buy. [(user, text)]."""
    from kol import insiders
    from league import copy as lcopy, store as lstore
    rows = con.execute("SELECT id, user, token, wallet, trade_id, buy_ts FROM kopija_trades WHERE status='open'").fetchall()
    todo = []
    for kid, user, tok, w, tid, buy_ts in rows:
        ts = insiders.sold_since(hype_db or _hype_db(), tok, buy_ts, [w])
        if ts:
            todo.append((kid, user, tok, w, tid, ts))
    if not todo:
        return []
    done = []
    now = int(now or time.time())
    mk = (market_fn or lcopy.market)(sorted({t[2] for t in todo})) or {}
    for kid, user, tok, w, tid, ts in todo:
        q = mk.get(tok)
        if not q or not q[0]:
            continue
        con.execute("UPDATE kopija_trades SET his_sell_ts=?, his_sell_px_sol=?, exit_delay_s=?, our_exit_px_usd=? "
                    "WHERE id=?",
                    (int(ts), his_px(w, tok, "sell", ts, hype_db), now - int(ts), q[0], kid))
        try:
            lstore.sell(con, user, tid, q[0], q[1], note=f"{SRC}: novčanik je prodao", mcap=q[3], exit_rule="wallet_sold")
        except ValueError:
            pass   # already closed by its stop / time limit
        done.append((user, f"kopija dokazanog demo izlaz {tok[:6]}: novčanik je prodao"))
    con.commit()
    return done


def sync_closed(con):
    for kid, tid, size in con.execute("SELECT id, trade_id, size_usd FROM kopija_trades WHERE status='open'").fetchall():
        t = con.execute("SELECT status, closed_ts, pnl_usd, exit_rule FROM trades WHERE id=?", (tid,)).fetchone()
        if not t or t[0] != "closed":
            continue
        con.execute("UPDATE kopija_trades SET status='closed', closed_ts=?, pnl_usd=?, ret=?, exit_reason=? WHERE id=?",
                    (t[1], t[2], (t[2] or 0) / size if size else None, t[3], kid))
    con.commit()


def run_once(con, market_fn=None, now=None, sol=None, force=False, hype_db=None, wallet_db=None):
    """One pass: exits of the open copies, the closed rows, then entries (paper mode only). [(user, text)]."""
    now = int(now or time.time())
    ensure(con)
    done = []
    if con.execute("SELECT 1 FROM kopija_trades WHERE status='open' LIMIT 1").fetchone():
        done += exits(con, market_fn, hype_db, now)
        sync_closed(con)
    if force or time.monotonic() - _LAST["fill"] >= FILL_EVERY_S:
        _LAST["fill"] = time.monotonic()
        fill_his(con, wallet_db)
    if not force and time.monotonic() - _LAST["ts"] < RUN_EVERY_S:
        return done
    _LAST["ts"] = time.monotonic()
    who = targets(now, wallet_db)
    if not who:
        return done
    fresh = fresh_buys(who, now, FRESH_S, hype_db)
    # 19.11. (league/mjera.py): every buy we SEE is measured first, before the flag, caps and guards of the demo
    from league import copy as lcopy, mjera
    new = [b for b in fresh if mjera.is_new(con, "kopija", b[2], b[0], now)]
    if new:
        mq = (market_fn or lcopy.market)(sorted({b[0] for b in new})) or {}
        for tok, ts, w, _sig, _sol in new:
            mjera.record(con, "kopija", w, w, tok, ts, now, mq.get(tok))
    if mode() != "paper" or not mjera.demo_entries_ok(con):
        return done
    buys = [b for b in fresh if b[0] not in _TRIED]
    if not buys:
        return done
    if sol is None:
        from rangedca import trade as rtrade
        sol = rtrade.sol_usd()
    if not sol:
        return done
    from league import copy as lcopy
    mk = (market_fn or lcopy.market)(sorted({b[0] for b in buys})) or {}
    plan = exit_plan(wallet_db)
    for tok, ts, w, sig, his_sol in buys:
        text, why = enter(con, tok, w, sig, ts, his_sol, mk.get(tok), now, sol, plan, hype_db)
        if text:
            done.append((demo_user(), text))
        elif why:
            if why != NO_PRICE:      # a token without a quote this second is asked again while his buy is fresh
                _TRIED[tok] = now
            if tok not in _SAID:
                _SAID[tok] = now
                print(f"{PREFIX}{tok[:6]}: demo nije kupio ({why})", flush=True)
    for d in (_TRIED, _SAID):
        for k in [k for k, t in d.items() if now - t > 3600]:
            d.pop(k, None)
    return done


# ---------- the report's numbers ----------------------------------------------------------------------------------------

def stats(lcon=None, now=None, path=None):
    """The demo copies for the report: closed / open, EV % a copy net of the calibrated cost and its 90 % interval,
    the median delay, our entry price against his (where his is known), his own return on the copies he closed against
    ours. None without the table."""
    import statistics
    from league import store as lstore
    from trade import cost, edge
    now = int(now or time.time())
    own = lcon is None
    if own:
        lcon = _ro(path or lstore.DB)
    try:
        rows = _q(lcon, "SELECT status, pnl_usd, ret, closed_ts, delay_s, his_px_sol, our_px_sol, his_sell_px_sol, "
                        "exit_reason FROM kopija_trades WHERE user IN (?, ?)", demo_users())
        if not rows and not _q(lcon, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kopija_trades'"):
            return None
    finally:
        if own and lcon is not None:
            lcon.close()
    closed = [r for r in rows if r[0] == "closed"]
    try:
        adj = cost.demo_adjust()
    except Exception:  # noqa: BLE001
        adj = 0.0
    rets = [r[2] + adj for r in closed if r[2] is not None]
    s = edge.ev_stats(rets)
    pct = lambda v: None if v is None else round(v * 100, 2)   # noqa: E731
    slips = [r[6] / r[5] - 1 for r in rows if r[5] and r[6]]
    both = [(r[7] / r[5] - 1, r[2] + adj) for r in closed if r[5] and r[7] and r[2] is not None]
    wnd = lambda t0: {"n": sum(1 for r in closed if (r[3] or 0) >= t0),   # noqa: E731
                      "pnl_usd": round(sum(r[1] or 0 for r in closed if (r[3] or 0) >= t0), 2)}
    return {"n": len(closed), "otvoreno": sum(1 for r in rows if r[0] == "open"), "ev_pct": pct(s["ev"]),
            "ci": [pct(s["lo90"]), pct(s["hi90"])] if s.get("lo90") is not None else None,
            "pogodak": round(sum(1 for x in rets if x > 0) / len(rets), 3) if rets else None,
            "pnl_usd": round(sum(r[1] or 0 for r in closed), 2), "d24": wnd(now - 86400), "d7": wnd(now - 7 * 86400),
            "kasnjenje_med_s": statistics.median(r[4] for r in rows if r[4] is not None) if any(
                r[4] is not None for r in rows) else None,
            "ulaz_n": len(slips), "ulaz_med_pct": pct(statistics.median(slips)) if slips else None,
            "usporedba_n": len(both), "njegov_pct": pct(sum(b[0] for b in both) / len(both)) if both else None,
            "nas_pct": pct(sum(b[1] for b in both) / len(both)) if both else None,
            "zastavica": mode(), "ulog_sol": DEMO_SOL, "max_otvorenih": MAX_OPEN, "dnevno": PER_DAY}
