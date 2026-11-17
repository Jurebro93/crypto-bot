"""The oscillator's demo trades (flag oscilator, trade/settings: paper = the DEMO account PAPER_USER; never live by the
flag, NEVER_LIVE). Runs inside league/auto.fast_loop (run_ui.py, league.db's only writer), at most every TICK_S (5 s).

Price: the same `market` the range rounds' 1-s exits use (league/copy.market: DexScreener /tokens through the 3-s live
cache, Jupiter for a token without a pair) for today's top K (oscilator.db kv top, run_oscilator.py) and the open
trades: ONE batched request a tick, free, no new paid call. From those quotes this module builds its own 1-minute bars
(league.db oscilator_bars, the last BARS_KEEP_S; seeded at the first sight of a token from range.db's minute series,
rangedca/data.series, read-only), so the rule (oscilator/rule.signal) reads the same bars the backtest reads.

  entry   at the first tick of a new minute, for every top-K token not held and not cooling down: rule.signal on the
          completed minute bars (lower quarter of the last hour's range, momentum turned up, the target net of the
          REAL cost fits under the range's top) -> bought at the quote of that tick (the "next bar's open"); hard rules
          (konsenzus/live.guards: bonded, MC >= 30k, liquidity >= 15k, not a fake pool, rug archive, rug collapse)
  exit    every tick: the take profit (rule.tp_px: +DEMO_TARGET_USD net of the real cost at the trade's size and
          liquidity), the stop (-stop_pct), the time stop (time_s), a rug (the hard rules fail on an open trade)
  caps    DEMO_MAX_OPEN (10) open, DEMO_PER_DAY (300) entries a Zagreb day, cooldown 2 min a token; size DEMO_SOL
          (OSC_DEMO_SOL, default 0.5 SOL: the cost share of the size the scalp needs), target OSC_TARGET_USD (1 $)
  cost    each trade carries THREE results: ret / pnl_usd at the REAL cost model at its size (rule.cost_at: pool +
          route fee, network fee a swap, AMM impact at the quoted liquidity), ret_demo / pnl_demo at the demo
          account's flat fee a side (trade/cost.fee_side) + impact, and pnl_booked (what league/store booked)
Real money (owner switch pravi_novac_oscilator, oscilator/gate): the same entries ALSO on the real account
LEAGUE_USER only while gate.real_refusal() is None (switch on AND the walk-forward proof AND the demo proof), at
REAL_SOL with REAL_MAX_OPEN and the day loss cap; run_trade.py asks the gate again before the real buy.
league.db oscilator_trades: one row per trade.
"""
import os
import time

FLAG = "oscilator"
SRC = "oscilator"
TICK_S = int(os.environ.get("OSC_TICK_S", "5"))
DEMO_SOL = float(os.environ.get("OSC_DEMO_SOL", "0.5"))
DEMO_TARGET_USD = float(os.environ.get("OSC_TARGET_USD", "1.0"))
DEMO_MAX_OPEN = 10
DEMO_PER_DAY = 300
TOP_MAX_AGE_S = 48 * 3600
BARS_KEEP_S = 3 * 3600
STALE_S = 60
SEED_H = 2
SCHEMA = """CREATE TABLE IF NOT EXISTS oscilator_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, opened_ts INTEGER, trade_id INTEGER,
    size_sol REAL, size_usd REAL, entry_px REAL, tp_px REAL, stop_px REAL, rt REAL, drt REAL, liq REAL, mcap REAL,
    status TEXT, closed_ts INTEGER, exit_px REAL, reason TEXT, ret REAL, pnl_usd REAL, ret_demo REAL, pnl_demo REAL,
    pnl_booked REAL, why TEXT);
CREATE INDEX IF NOT EXISTS oscilator_trades_st ON oscilator_trades (status, user);
CREATE TABLE IF NOT EXISTS oscilator_bars (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL,
    PRIMARY KEY (token, ts));"""
_BARS = {}      # token -> [[ts, o, h, l, c], ...] (minute bars, oldest first; the last may be in progress)
_ST = {"tick": 0.0, "minute": {}, "said": {}}


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='oscilator_bars'").fetchone() is None:
        con.executescript(SCHEMA)


def mode():
    try:
        from trade import settings
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def _day_start(now):
    from oscilator import scan
    return scan.day_start(scan.day_of(now))


def _sol():
    from oscilator import walk
    return walk.sol_now()


# ---------- the minute bars ------------------------------------------------------------------------------------------

def _seed(con, tok, now):
    """The bars of a token seen for the first time: league.db oscilator_bars, else range.db's minute series."""
    rows = [list(r) for r in con.execute("SELECT ts, o, h, l, c FROM oscilator_bars WHERE token=? AND ts>=? ORDER BY ts",
                                         (tok, int(now - BARS_KEEP_S)))]
    if len(rows) < 10:
        try:
            from rangedca import data
            rcon = data.ro()
            if rcon is not None:
                try:
                    cs, _snap = data.series(rcon, tok, now, hours=SEED_H)
                finally:
                    rcon.close()
                have = {r[0] for r in rows}
                rows = sorted(rows + [[int(c[0]), c[1], c[2], c[3], c[4]] for c in cs if int(c[0]) not in have])
        except Exception:  # noqa: BLE001 - no seed: the bars start now
            pass
    _BARS[tok] = rows


def add_price(con, tok, px, now):
    """One quote into the token's minute bars; a bar completed by this quote is written to league.db."""
    if not px or px <= 0:
        return
    if tok not in _BARS:
        _seed(con, tok, now)
    bars = _BARS[tok]
    m = int(now) - int(now) % 60
    if bars and bars[-1][0] == m:
        b = bars[-1]
        b[2], b[3], b[4] = max(b[2], px), min(b[3], px), px
        return
    if bars and bars[-1][0] < m:
        b = bars[-1]
        con.execute("INSERT OR REPLACE INTO oscilator_bars (token, ts, o, h, l, c) VALUES (?,?,?,?,?,?)",
                    (tok, int(b[0]), b[1], b[2], b[3], b[4]))
    bars.append([m, px, px, px, px])
    cut = now - BARS_KEEP_S
    while bars and bars[0][0] < cut:
        bars.pop(0)


def completed(tok, now):
    """The token's completed minute bars (the bar in progress left out), as rule tuples."""
    m = int(now) - int(now) % 60
    return [tuple(b) for b in _BARS.get(tok) or [] if b[0] < m]


def window_of(bars, i, win_s):
    """rule.windows' entry for bar i only (lo, hi, span, n), O(window)."""
    t = bars[i][0]
    w = [b for b in bars[:i] if b[0] > t - win_s]
    if not w:
        return None, None, 0, 0
    return min(b[3] for b in w), max(b[2] for b in w), t - w[0][0], len(w)


# ---------- entries and exits ----------------------------------------------------------------------------------------

def guards(tok, mq):
    from konsenzus import live as klive
    return klive.guards(tok, mq)


def open_rows(con, user=None):
    sql = "SELECT * FROM oscilator_trades WHERE status='open'" + (" AND user=?" if user else "")
    cur = con.execute(sql, (user,) if user else ())
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def caps(user):
    from oscilator import gate
    from trade import settings
    if user == settings.LEAGUE_USER:
        c = gate.real_caps()
        return {"size_sol": c["size_sol"], "max_open": c["max_open"], "per_day": c["max_buys_day"],
                "loss_day_sol": c["max_loss_day_sol"]}
    return {"size_sol": DEMO_SOL, "max_open": DEMO_MAX_OPEN, "per_day": DEMO_PER_DAY, "loss_day_sol": None}


def enter(con, user, tok, mq, now, sol, why):
    """One entry; (text or None, why not or None)."""
    from league import store as lstore
    from oscilator import rule
    cp = caps(user)
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token"
    n_open = con.execute("SELECT COUNT(*) FROM oscilator_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
    if n_open >= cp["max_open"]:
        return None, f"već {n_open} otvorenih (strop {cp['max_open']})"
    n_day = con.execute("SELECT COUNT(*) FROM oscilator_trades WHERE user=? AND opened_ts>=?",
                        (user, _day_start(now))).fetchone()[0]
    if n_day >= cp["per_day"]:
        return None, f"dnevni strop ulaza ({cp['per_day']}) potrošen"
    if cp.get("loss_day_sol"):
        lost = con.execute("SELECT COALESCE(SUM(pnl_usd), 0) FROM oscilator_trades WHERE user=? AND status='closed' "
                           "AND closed_ts>=?", (user, _day_start(now))).fetchone()[0]
        if lost <= -cp["loss_day_sol"] * sol:
            return None, f"dnevni gubitak {lost:.2f} $ dosegao strop {cp['loss_day_sol']:g} SOL"
    g = guards(tok, mq)
    if g:
        return None, g
    price, liq, url, mcap = mq[:4]
    sym = (mq[4] if len(mq) > 4 else None) or tok[:6]
    from trade import capgate   # 15.11. (vlasnik): MC >= 5M; a price scalp takes no moonshot exception
    g = capgate.refusal(tok, mcap, f"{SRC}: {why}", user, now, liq=liq, symbol=sym)
    if g:
        return None, g
    size_usd = cp["size_sol"] * sol
    c = rule.cost_at(cp["size_sol"], liq, sol, rule.real_fee_side(url=url), rule.tx_sol()[0])
    drt = rule.demo_rt(size_usd, liq)
    t = rule.target_frac(size_usd, DEMO_TARGET_USD)
    try:
        tid = lstore.buy(con, user, tok, sym, size_usd, price, liq, f"{SRC}: {why}"[:200], None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})"
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))   # this module sells it
    tp, stop = rule.tp_px(price, t, c["rt"]), price * (1 - rule.RULE["stop_pct"])
    con.execute("INSERT INTO oscilator_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, "
                "tp_px, stop_px, rt, drt, liq, mcap, status, why) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",
                (user, tok, sym, int(now), tid, cp["size_sol"], size_usd, price, tp, stop, c["rt"], drt, liq, mcap,
                 why[:200]))
    con.commit()
    from trade import settings
    return (f"oscilator {'PRAVI' if user == settings.LEAGUE_USER else 'demo'} ulaz {sym} {cp['size_sol']:g} SOL na MC "
            f"${mcap or 0:,.0f}: cilj +${DEMO_TARGET_USD:g} neto (pomak {tp / price - 1:+.1%}, pravi trošak runde "
            f"{c['rt']:.1%}, uz demo naknadu {drt:.1%}), stop {stop / price - 1:+.0%}"), None


def exit_why(r, price, age, now, mq):
    from oscilator import rule
    if price <= r["stop_px"]:
        return "stop"
    if age > STALE_S:
        return None
    if price >= r["tp_px"]:
        return "tp"
    if now - r["opened_ts"] >= rule.RULE["time_s"]:
        return "time"
    if mq is not None:
        from league import copy as lcopy
        try:
            col = lcopy._rugged(r["token"], mq[3], mq[1])
        except Exception:  # noqa: BLE001
            col = None
        if col:
            return "rug"
    return None


def close(con, r, price, liq, mcap, reason, now):
    from league import store as lstore
    from oscilator import rule
    booked = None
    t = con.execute("SELECT status FROM trades WHERE id=?", (r["trade_id"],)).fetchone()
    if t and t[0] == "open":
        rule_ = {"tp": "tp", "stop": "sl", "time": "time", "rug": "rug"}.get(reason, "sl")
        booked = lstore.sell(con, r["user"], r["trade_id"], price, liq, f"oscilator: {rule.REASON_HR.get(reason, reason)}",
                             mcap=mcap, exit_rule=rule_)
    else:   # sold elsewhere (by hand, a rug path): its own close
        row = con.execute("SELECT pnl_usd, exit_px FROM trades WHERE id=?", (r["trade_id"],)).fetchone()
        booked = row[0] if row else None
        price = (row[1] if row and row[1] else price)
        reason = reason if t else "nestalo"
    ret = rule.net_ret(r["entry_px"], price, r["rt"])
    rd = rule.net_ret(r["entry_px"], price, r["drt"])
    con.execute("UPDATE oscilator_trades SET status='closed', closed_ts=?, exit_px=?, reason=?, ret=?, pnl_usd=?, "
                "ret_demo=?, pnl_demo=?, pnl_booked=? WHERE id=? AND status='open'",   # 17.11.: never re-close a closed row
                (int(now), price, reason, ret, ret * r["size_usd"], rd, rd * r["size_usd"], booked, r["id"]))
    con.commit()
    return (f"oscilator {r['symbol']}: {rule.REASON_HR.get(reason, reason)}, {ret * r['size_usd']:+.2f} $ pravim "
            f"troškom ({ret:+.1%}), uz demo naknadu {rd * r['size_usd']:+.2f} $, knjiženo {booked or 0:+.2f} $")


def tick(con, market_fn, now=None, force=False, top=None):
    """One pass: exits of the open trades, then (at a new minute) the entries. [text]."""
    now = now or time.time()
    if not force and now - _ST["tick"] < TICK_S:
        return []
    _ST["tick"] = now
    m = mode()
    ensure(con)
    opened = open_rows(con)
    if m not in ("paper", "live") and not opened:
        return []
    from trade import settings
    users = []
    if m in ("paper", "live"):
        users.append(settings.PAPER_USER)
        try:
            from oscilator import gate
            if gate.real_refusal(con=None) is None:
                users.append(settings.LEAGUE_USER)
        except Exception:  # noqa: BLE001 - an unreadable gate is no real money
            pass
    if top is None:
        from oscilator import store
        tp = store.top() or {}
        top = [x["token"] for x in tp.get("tokens") or []] if now - (tp.get("ts") or 0) <= TOP_MAX_AGE_S else []
    toks = sorted(set(top if users else []) | {r["token"] for r in opened})
    if not toks:
        return []
    mk = market_fn(toks) or {}
    for tok in toks:
        q = mk.get(tok)
        if q and q[0]:
            add_price(con, tok, q[0], now)
            _ST.setdefault("q", {})[tok] = (q, now)
    con.commit()
    out = []
    for r in opened:
        q, ts = (_ST.get("q") or {}).get(r["token"], (None, 0))
        if not q:
            continue
        why = exit_why(r, q[0], now - ts, now, q if now - ts <= STALE_S else None)
        if why:
            out.append(close(con, r, q[0], q[1], q[3] if len(q) > 3 else None, why, now))
    if not users:
        return out
    from oscilator import rule
    minute = int(now) - int(now) % 60
    sol = _sol()
    tx = rule.tx_sol()[0]
    held = {(r["user"], r["token"]) for r in open_rows(con)}
    for tok in top:
        if _ST["minute"].get(tok) == minute:
            continue
        _ST["minute"][tok] = minute
        q = mk.get(tok)
        if not q or not q[0]:
            continue
        bars = completed(tok, now)
        if len(bars) < rule.MIN_BARS:
            continue
        last = con.execute("SELECT MAX(closed_ts) FROM oscilator_trades WHERE token=?", (tok,)).fetchone()[0]
        if last and now - last < rule.RULE["cooldown_s"]:
            continue
        for user in users:
            if (user, tok) in held:
                continue
            cp = caps(user)
            c = rule.cost_at(cp["size_sol"], q[1], sol, rule.real_fee_side(url=q[2] if len(q) > 2 else None), tx)
            t = rule.target_frac(cp["size_sol"] * sol, DEMO_TARGET_USD)
            i = len(bars) - 1
            why = rule.signal(bars, i, window_of(bars, i, rule.RULE["win_s"]), t, c["rt"])
            if why is not None:
                continue
            text, no = enter(con, user, tok, q, now, sol, f"dno raspona {rule.RULE['win_s'] // 60} min, zaokret gore")
            if text:
                out.append(text)
            elif no and now - _ST["said"].get((user, tok), 0) > 3600:
                _ST["said"][(user, tok)] = now
                out.append(f"oscilator {tok[:6]}: signal bez ulaza ({no})")
    if int(now) % 600 < TICK_S:   # prune the stored bars every ~10 min
        con.execute("DELETE FROM oscilator_bars WHERE ts < ?", (int(now - 2 * BARS_KEEP_S),))
        con.commit()
    return out


def demo_stats(lcon=None, user=None):
    """The closed oscilator trades of the demo account: n, open, hit, ev_pct (real cost), ev_demo_pct, pnl_usd,
    pnl_demo_usd, pnl_booked_usd, ci90_lo_pct (bootstrap of the mean)."""
    from trade import settings
    user = user or settings.PAPER_USER
    own = lcon is None
    if own:
        from league import store as lstore
        import sqlite3
        if not os.path.exists(lstore.DB):
            return {"n": 0, "open": 0}
        lcon = sqlite3.connect(f"file:{lstore.DB}?mode=ro", uri=True, timeout=5)
    try:
        if lcon.execute("SELECT 1 FROM sqlite_master WHERE name='oscilator_trades'").fetchone() is None:
            return {"n": 0, "open": 0}
        rows = lcon.execute("SELECT ret, pnl_usd, ret_demo, pnl_demo, pnl_booked, reason FROM oscilator_trades WHERE "
                            "user=? AND status='closed' AND ret IS NOT NULL", (user,)).fetchall()
        n_open = lcon.execute("SELECT COUNT(*) FROM oscilator_trades WHERE user=? AND status='open'",
                              (user,)).fetchone()[0]
        n_day = lcon.execute("SELECT COUNT(*) FROM oscilator_trades WHERE user=? AND opened_ts>=?",
                             (user, _day_start(time.time()))).fetchone()[0]
    finally:
        if own:
            lcon.close()
    n = len(rows)
    out = {"n": n, "open": n_open, "today": n_day, "size_sol": DEMO_SOL, "target_usd": DEMO_TARGET_USD}
    if n:
        import random
        rets = [r[0] for r in rows]
        out.update(hit=round(sum(1 for r in rows if r[1] > 0) / n, 3), ev_pct=round(sum(rets) / n * 100, 3),
                   ev_demo_pct=round(sum(r[2] for r in rows) / n * 100, 3), pnl_usd=round(sum(r[1] for r in rows), 2),
                   pnl_demo_usd=round(sum(r[3] for r in rows), 2),
                   pnl_booked_usd=round(sum(r[4] or 0 for r in rows), 2),
                   reasons={k: sum(1 for r in rows if r[5] == k) for k in sorted({r[5] for r in rows})})
        rnd = random.Random(3)
        ms = sorted(sum(rnd.choice(rets) for _ in range(n)) / n for _ in range(500))
        out["ci90_lo_pct"] = round(ms[25] * 100, 3)
    return out
