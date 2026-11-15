"""The big-token range's demo trades (flag veliki_range, trade/settings: paper = the DEMO account PAPER_USER; never live
by the flag, NEVER_LIVE). Runs inside league/auto.fast_loop (run_ui.py, league.db's only writer), at most every TICK_S.

Price: the same `market` the range rounds' 1-s exits use (league/copy.market: DexScreener /tokens through the 3-s live
cache) for the list (veliki.db kv list, run_veliki.py list) and the open trades: ONE batched request a tick, free, no
new paid call. Bars: the list's 15m GeckoTerminal candles from veliki.db (read-only, re-read every BARS_RELOAD_S) and,
after the newest of them, this module's own 15m bars built from those quotes (league.db veliki_bars); the 1h candles
the zones read are rebuilt from the 15m bars (rule.h1_from_15m), as in the backtest.

  rule    store.live_rule() (the walk-forward's best configuration of the rule "bez_padova" on every day at the demo
          size), else rule.RULE (+5 % net, stop -5 %, 24 h, 3-day zone)
  entry   at the first tick after a 15m bar completes, for every listed token not held and not cooling down:
          rule.signal on the completed bars (support touched, bounce confirmed, stop below the support, target inside
          the range, NO BTC crash active: btc_state) -> bought at the quote of that tick (the next bar's open); hard
          rules (guards: bonded, MC >= 30k, liquidity >= 15k, not a fake pool, the rug archive, a rug collapse)
  exit    every tick: the take profit (tp_px: the net target at the trade's real cost, or the zone's mid / top frozen
          at the entry), the stop, the time stop, a rug
  caps    DEMO_MAX_OPEN (8) open, DEMO_PER_DAY (40) entries a Zagreb day, cooldown 1 h a token; size DEMO_SOL
          (VEL_DEMO_SOL, default 0.5 SOL)
  cost    each trade carries ret / pnl_usd at the REAL cost model (rule.cost_at: pool + route fee, the network fee,
          the impact at the quoted liquidity), ret_demo at the measured fee a side, and pnl_booked (league/store)
Real money (owner switch pravi_novac_veliki, veliki/gate): the same entries ALSO on the real account LEAGUE_USER only
while gate.real_refusal() is None, at its caps (0.1 SOL default, 5 open, day loss 0.3 SOL); run_trade.py asks again.
"""
import os
import time

FLAG = "veliki_range"
SRC = "veliki"
TICK_S = int(os.environ.get("VEL_TICK_S", "10"))
DEMO_SOL = float(os.environ.get("VEL_DEMO_SOL", "0.5"))
DEMO_MAX_OPEN = int(os.environ.get("VEL_DEMO_MAX_OPEN", "8"))
DEMO_PER_DAY = int(os.environ.get("VEL_DEMO_PER_DAY", "40"))
LIST_MAX_AGE_S = 72 * 3600
BARS_RELOAD_S = 600
BTC_RELOAD_S = 600
STALE_S = 60
SCHEMA = """CREATE TABLE IF NOT EXISTS veliki_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, opened_ts INTEGER, trade_id INTEGER,
    size_sol REAL, size_usd REAL, entry_px REAL, tp_px REAL, stop_px REAL, rt REAL, drt REAL, liq REAL, mcap REAL,
    cfg TEXT, zone TEXT, regime TEXT, status TEXT, closed_ts INTEGER, exit_px REAL, reason TEXT, ret REAL, pnl_usd REAL,
    ret_demo REAL, pnl_booked REAL, why TEXT);
CREATE INDEX IF NOT EXISTS veliki_trades_st ON veliki_trades (status, user);
CREATE TABLE IF NOT EXISTS veliki_bars (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, PRIMARY KEY (token, ts));"""
M15 = 900
_ST = {"tick": 0.0, "bar": {}, "said": {}, "gt": {}, "gt_ts": 0.0, "btc": None, "btc_ts": 0.0, "q": {}}
_LIVE = {}      # token -> [[ts, o, h, l, c], ...] own 15m bars (the last may be in progress)


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='veliki_bars'").fetchone() is None:
        con.executescript(SCHEMA)


def mode():
    try:
        from trade import settings
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def _day_start(now):
    from league import copy as lcopy
    return lcopy._day_start(int(now))


def cfg_now():
    """The live rule: store.live_rule() merged over rule.RULE (crash filter always on)."""
    from veliki import rule, store
    lr = store.live_rule() or {}
    c = {**rule.RULE, **{k: lr[k] for k in ("tp", "stop_pct", "time_h", "look_d") if lr.get(k) is not None}}
    c["crash_filter"] = True
    return c


# ---------- BTC ------------------------------------------------------------------------------------------------------

def btc_state(now=None):
    """{"known", "crash", "crash_obj"} from BTC hourly (veliki.db + market.db, cached BTC_RELOAD_S)."""
    from veliki import rule, store
    now = now or time.time()
    if _ST["btc"] is None or now - _ST["btc_ts"] > BTC_RELOAD_S:
        try:
            _ST["btc"] = rule.Crash(rule.crash_hours(store.btc_hourly()))
        except Exception:  # noqa: BLE001
            _ST["btc"] = rule.NO_CRASH
        _ST["btc_ts"] = now
    cr = _ST["btc"]
    return {"known": cr.known(now), "crash": cr.active(now), "crash_obj": cr, "last_end": cr.last_end(now)}


# ---------- bars -----------------------------------------------------------------------------------------------------

def _gt(tok, now):
    """(15m GeckoTerminal bars, 1h candles) of the token from veliki.db, cached BARS_RELOAD_S."""
    if now - _ST["gt_ts"] > BARS_RELOAD_S:
        _ST["gt"].clear()
        _ST["gt_ts"] = now
    hit = _ST["gt"].get(tok)
    if hit is None:
        from veliki import store
        con = store.ro()
        b15, b1h = [], []
        if con is not None:
            try:
                b15 = store.candles(con, "c15", tok, now - 9 * 86400)
                b1h = store.candles(con, "c1h", tok, now - 9 * 86400)
            finally:
                con.close()
        hit = _ST["gt"][tok] = (b15, b1h)
    return hit


def add_price(con, tok, px, now):
    if not px or px <= 0:
        return
    bars = _LIVE.get(tok)
    if bars is None:
        bars = _LIVE[tok] = [list(r) for r in con.execute(
            "SELECT ts, o, h, l, c FROM veliki_bars WHERE token=? AND ts>=? ORDER BY ts", (tok, int(now - 9 * 86400)))]
    m = int(now) - int(now) % M15
    if bars and bars[-1][0] == m:
        b = bars[-1]
        b[2], b[3], b[4] = max(b[2], px), min(b[3], px), px
        return
    if bars and bars[-1][0] < m:
        b = bars[-1]
        con.execute("INSERT OR REPLACE INTO veliki_bars (token, ts, o, h, l, c) VALUES (?,?,?,?,?,?)",
                    (tok, int(b[0]), b[1], b[2], b[3], b[4]))
    bars.append([m, px, px, px, px])
    while bars and bars[0][0] < now - 9 * 86400:
        bars.pop(0)


def series(tok, now):
    """(completed 15m bars, 1h candles): GeckoTerminal's, then own bars after the newest of them."""
    from veliki import rule
    b15, b1h = _gt(tok, now)
    last = b15[-1][0] if b15 else 0
    m = int(now) - int(now) % M15
    own = [tuple(b) + (0.0,) for b in _LIVE.get(tok) or [] if last < b[0] < m]
    bars = [b for b in b15 if b[0] < m] + own
    return bars, rule.h1_from_15m(bars, b1h)


# ---------- entries and exits ----------------------------------------------------------------------------------------

def guards(tok, mq):
    """Why this big token may not be entered on this quote (Croatian), or None. The liquidity / MC ratio floor of the
    small tokens (league/copy min_liq_mcap 3 %) does not apply: a $100M token's $2M pool is 2 % and deep."""
    from league import copy as lcopy
    from trade import cost
    if not mq or not mq[0]:
        return "nema žive cijene"
    _price, liq, _url, mcap = mq[:4]
    if lcopy._bonding_curve(mq) or lcopy._dex_pair_empty(mq):
        return "token je na krivulji ili bez DexScreener para (uzimaju se bondani)"
    if (mcap or 0) < lcopy.CFG["min_mcap"]:
        return "MC ispod 30k"
    why = cost.liq_block(liq)
    if why:
        return why
    if mcap and liq and liq > mcap:
        return "lažni pool (likvidnost veća od MC-a)"
    try:
        from rangedca import trade as rtrade
        why = rtrade.archived_why(tok)
    except Exception:  # noqa: BLE001
        why = None
    if why:
        return why
    col = lcopy._rugged(tok, mcap, liq)
    if col:
        return f"rug ({col['text']})"
    return None


def open_rows(con, user=None):
    sql = "SELECT * FROM veliki_trades WHERE status='open'" + (" AND user=?" if user else "")
    cur = con.execute(sql, (user,) if user else ())
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def caps(user):
    from trade import settings
    from veliki import gate
    if user == settings.LEAGUE_USER:
        c = gate.real_caps()
        return {"size_sol": c["size_sol"], "max_open": c["max_open"], "per_day": c["max_buys_day"],
                "loss_day_sol": c["max_loss_day_sol"]}
    return {"size_sol": DEMO_SOL, "max_open": DEMO_MAX_OPEN, "per_day": DEMO_PER_DAY, "loss_day_sol": None}


def enter(con, user, tok, mq, now, sol, zone, cfg, regime=None):
    """One entry; (text or None, why not or None)."""
    import json
    from league import store as lstore
    from trade import settings
    from veliki import rule
    cp = caps(user)
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token"
    n_open = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
    if n_open >= cp["max_open"]:
        return None, f"već {n_open} otvorenih (strop {cp['max_open']})"
    n_day = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND opened_ts>=?",
                        (user, _day_start(now))).fetchone()[0]
    if n_day >= cp["per_day"]:
        return None, f"dnevni strop ulaza ({cp['per_day']}) potrošen"
    if cp.get("loss_day_sol"):
        lost = con.execute("SELECT COALESCE(SUM(pnl_usd), 0) FROM veliki_trades WHERE user=? AND status='closed' "
                           "AND closed_ts>=?", (user, _day_start(now))).fetchone()[0]
        if lost <= -cp["loss_day_sol"] * sol:
            return None, f"dnevni gubitak {lost:.2f} $ dosegao strop {cp['loss_day_sol']:g} SOL"
    g = guards(tok, mq)
    if g:
        return None, g
    price, liq, url, mcap = mq[:4]
    sym = (mq[4] if len(mq) > 4 else None) or tok[:6]
    size_usd = cp["size_sol"] * sol
    c = rule.cost_at(cp["size_sol"], liq, sol, rule.fee_side_of(url=url), rule.tx_sol()[0])
    drt = rule.demo_rt(size_usd, liq)
    tp = rule.tp_price(price, cfg["tp"], c["rt"], zone, cfg)
    if tp <= price:
        return None, "cilj nije iznad ulaza"
    stop = price * (1 - cfg["stop_pct"])
    why = (f"{SRC}: podrška {zone['s_lo']:.6g}-{zone['s_hi']:.6g}, cilj {tp / price - 1:+.1%}, stop -{cfg['stop_pct']:.0%}"
           + (", novi raspon nakon pada BTC-a" if zone.get("fresh") else ""))
    try:
        tid = lstore.buy(con, user, tok, sym, size_usd, price, liq, why[:200], None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})"
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))   # this module sells it
    zj = {k: round(zone[k], 10) for k in ("s_lo", "s_hi", "r_lo", "r_hi", "mid") if zone.get(k) is not None}
    zj["fresh"] = bool(zone.get("fresh"))
    con.execute("INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, tp_px, "
                "stop_px, rt, drt, liq, mcap, cfg, zone, regime, status, why) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",
                (user, tok, sym, int(now), tid, cp["size_sol"], size_usd, price, tp, stop, c["rt"], drt, liq, mcap,
                 rule.cfg_key(cfg), json.dumps(zj), regime, why[:200]))
    con.commit()
    return (f"veliki {'PRAVI' if user == settings.LEAGUE_USER else 'demo'} ulaz {sym} {cp['size_sol']:g} SOL na MC "
            f"${(mcap or 0) / 1e6:,.1f}M: podrška {zone['s_lo']:.6g}-{zone['s_hi']:.6g}, cilj {tp / price - 1:+.1%} "
            f"({cfg['tp'] if isinstance(cfg['tp'], str) else str(cfg['tp']) + ' % neto'}), stop -{cfg['stop_pct']:.0%}, "
            f"{cfg['time_h']} h; pravi trošak runde {c['rt']:.2%}"), None


def exit_why(r, price, age, now, mq, time_h):
    if price <= r["stop_px"]:
        return "stop"
    if age > STALE_S:
        return None
    if price >= r["tp_px"]:
        return "tp"
    if now - r["opened_ts"] >= time_h * 3600:
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
    from veliki import rule
    booked = None
    t = con.execute("SELECT status FROM trades WHERE id=?", (r["trade_id"],)).fetchone()
    if t and t[0] == "open":
        rr = {"tp": "tp", "stop": "sl", "time": "time", "rug": "rug"}.get(reason, "sl")
        booked = lstore.sell(con, r["user"], r["trade_id"], price, liq, f"veliki: {rule.REASON_HR.get(reason, reason)}",
                             mcap=mcap, exit_rule=rr)
    else:
        row = con.execute("SELECT pnl_usd, exit_px FROM trades WHERE id=?", (r["trade_id"],)).fetchone()
        booked = row[0] if row else None
        price = (row[1] if row and row[1] else price)
        reason = reason if t else "nestalo"
    ret = rule.net_ret(r["entry_px"], price, r["rt"])
    rd = rule.net_ret(r["entry_px"], price, r["drt"])
    con.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, exit_px=?, reason=?, ret=?, pnl_usd=?, "
                "ret_demo=?, pnl_booked=? WHERE id=?",
                (int(now), price, reason, ret, ret * r["size_usd"], rd, booked, r["id"]))
    con.commit()
    return (f"veliki {r['symbol']}: {rule.REASON_HR.get(reason, reason)}, {ret * r['size_usd']:+.2f} $ pravim troškom "
            f"({ret:+.1%}), uz izmjerenu naknadu {rd:+.1%}, knjiženo {booked or 0:+.2f} $")


def _list_tokens(now):
    from veliki import store
    lst = store.the_list() or {}
    if now - (lst.get("ts") or 0) > LIST_MAX_AGE_S:
        return []
    return [x["mint"] for x in lst.get("tokens") or [] if x.get("mint")]


def tick(con, market_fn, now=None, force=False, toks=None):
    """One pass: exits of the open trades, then (after a 15m bar completed) the entries. [text]."""
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
    from veliki import rule
    users = []
    if m in ("paper", "live"):
        users.append(settings.PAPER_USER)
        try:
            from veliki import gate
            if gate.real_refusal(con=None, now=now) is None:
                users.append(settings.LEAGUE_USER)
        except Exception:  # noqa: BLE001 - an unreadable gate is no real money
            pass
    lst = _list_tokens(now) if toks is None else list(toks)
    all_t = sorted(set(lst if users else []) | {r["token"] for r in opened})
    if not all_t:
        return []
    mk = market_fn(all_t) or {}
    for tok in all_t:
        q = mk.get(tok)
        if q and q[0]:
            add_price(con, tok, q[0], now)
            _ST["q"][tok] = (q, now)
    con.commit()
    cfg = cfg_now()
    out = []
    for r in opened:
        q, ts = _ST["q"].get(r["token"], (None, 0))
        if not q:
            continue
        th = cfg["time_h"]
        try:
            th = int(str(r.get("cfg") or "").split("/")[2].rstrip("h"))
        except (IndexError, ValueError):
            pass
        why = exit_why(r, q[0], now - ts, now, q if now - ts <= STALE_S else None, th)
        if why:
            out.append(close(con, r, q[0], q[1], q[3] if len(q) > 3 else None, why, now))
    if not users:
        return out
    bar = int(now) - int(now) % M15
    btc = btc_state(now)
    sol = _sol()
    tx = rule.tx_sol()[0]
    held = {(r["user"], r["token"]) for r in open_rows(con)}
    for tok in lst:
        if _ST["bar"].get(tok) == bar:
            continue
        q = mk.get(tok)
        if not q or not q[0]:
            continue
        _ST["bar"][tok] = bar
        bars, h1 = series(tok, now)
        if len(bars) < 10:
            continue
        last = con.execute("SELECT MAX(closed_ts) FROM veliki_trades WHERE token=?", (tok,)).fetchone()[0]
        if last and now - last < cfg["cooldown_s"]:
            continue
        zone = rule.Zones(h1, btc["crash_obj"]).at(bar, cfg["look_d"])
        i = len(bars) - 1
        regime = _regime(now)
        for user in users:
            if (user, tok) in held:
                continue
            cp = caps(user)
            c = rule.cost_at(cp["size_sol"], q[1], sol, rule.fee_side_of(url=q[2] if len(q) > 2 else None), tx)
            why = rule.signal(bars, i, zone, c["rt"], cfg, btc["crash_obj"])
            if why is not None:
                continue
            text, no = enter(con, user, tok, q, now, sol, zone, cfg, regime)
            if text:
                out.append(text)
            elif no and now - _ST["said"].get((user, tok), 0) > 3600:
                _ST["said"][(user, tok)] = now
                out.append(f"veliki {(q[4] if len(q) > 4 else None) or tok[:6]}: signal bez ulaza ({no})")
    if int(now) % 3600 < TICK_S:
        con.execute("DELETE FROM veliki_bars WHERE ts < ?", (int(now - 10 * 86400),))
        con.commit()
    return out


def _sol():
    from veliki import walk
    return walk.sol_now()


def _regime(now):
    try:
        from market import makro
        s = makro.snapshot(now)
        return (s or {}).get("btc")
    except Exception:  # noqa: BLE001
        return None


def zones_now(now=None):
    """For the card / MCP: per listed token the zone of the live rule and where the price is (read-only)."""
    from veliki import rule, store
    now = now or time.time()
    cfg = cfg_now()
    lst = store.the_list() or {}
    con = store.ro()
    if con is None:
        return []
    btc = btc_state(now)
    out = []
    try:
        for x in lst.get("tokens") or []:
            b15 = store.candles(con, "c15", x["mint"], now - 9 * 86400)
            b1h = store.candles(con, "c1h", x["mint"], now - 9 * 86400)
            h1 = rule.h1_from_15m(b15, b1h)
            z = rule.Zones(h1, btc["crash_obj"]).at(now, cfg["look_d"])
            q = (_ST["q"].get(x["mint"]) or (None, 0))[0]
            px = (q[0] if q else None) or (b15[-1][4] if b15 else None)
            pos = None
            if z.get("ok") and px:
                pos = round((px - z["s_lo"]) / (z["r_hi"] - z["s_lo"]) * 100, 1) if z["r_hi"] > z["s_lo"] else None
            out.append({"symbol": x.get("symbol"), "mint": x["mint"], "price": px, "zone_ok": bool(z.get("ok")),
                        "why": z.get("why"), "fresh": z.get("fresh"), "pos_pct": pos,
                        **{k: z.get(k) for k in ("s_lo", "s_hi", "r_lo", "r_hi", "width", "er")}})
    finally:
        con.close()
    return out


def demo_stats(lcon=None, user=None):
    """The closed veliki trades of the demo account: n, open, today, hit, ev_pct (real cost), ev_demo_pct, pnl_usd,
    pnl_booked_usd, ci90_lo_pct (bootstrap of the mean), by_regime."""
    from trade import settings
    user = user or settings.PAPER_USER
    own = lcon is None
    if own:
        import sqlite3
        from league import store as lstore
        if not os.path.exists(lstore.DB):
            return {"n": 0, "open": 0}
        lcon = sqlite3.connect(f"file:{lstore.DB}?mode=ro", uri=True, timeout=5)
    try:
        if lcon.execute("SELECT 1 FROM sqlite_master WHERE name='veliki_trades'").fetchone() is None:
            return {"n": 0, "open": 0, "size_sol": DEMO_SOL}
        rows = lcon.execute("SELECT ret, pnl_usd, ret_demo, pnl_booked, reason, regime FROM veliki_trades WHERE "
                            "user=? AND status='closed' AND ret IS NOT NULL", (user,)).fetchall()
        n_open = lcon.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
        n_day = lcon.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND opened_ts>=?",
                             (user, _day_start(time.time()))).fetchone()[0]
    finally:
        if own:
            lcon.close()
    n = len(rows)
    out = {"n": n, "open": n_open, "today": n_day, "size_sol": DEMO_SOL}
    if n:
        import random
        rets = [r[0] for r in rows]
        out.update(hit=round(sum(1 for r in rows if r[1] > 0) / n, 3), ev_pct=round(sum(rets) / n * 100, 3),
                   ev_demo_pct=round(sum(r[2] for r in rows) / n * 100, 3), pnl_usd=round(sum(r[1] for r in rows), 2),
                   pnl_booked_usd=round(sum(r[3] or 0 for r in rows), 2),
                   reasons={k: sum(1 for r in rows if r[4] == k) for k in sorted({r[4] for r in rows})},
                   by_regime={k or "nepoznato": sum(1 for r in rows if r[5] == k) for k in {r[5] for r in rows}})
        rnd = random.Random(3)
        ms = sorted(sum(rnd.choice(rets) for _ in range(n)) / n for _ in range(500))
        out["ci90_lo_pct"] = round(ms[25] * 100, 3)
    return out
