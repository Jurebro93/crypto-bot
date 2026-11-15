"""The big-token range's demo trades (flag veliki_range, trade/settings: paper = the DEMO account PAPER_USER; never live
by the flag, NEVER_LIVE). Runs inside league/auto.fast_loop (run_ui.py, league.db's only writer), at most every TICK_S.

Price: the same `market` the range rounds' 1-s exits use (league/copy.market: DexScreener /tokens through the 3-s live
cache) for the list (veliki.db kv list, run_veliki.py list) and the open trades: ONE batched request a tick, free, no
new paid call. Bars: the list's 15m GeckoTerminal candles from veliki.db (read-only, re-read every BARS_RELOAD_S) and,
after the newest of them, this module's own 15m bars built from those quotes (league.db veliki_bars); the 1h candles
the zones read are rebuilt from the 15m bars (rule.h1_from_15m), as in the backtest.

  rule    store.live_rule() (the walk-forward's best configuration of the rule "dno" on every day at the demo size),
          else rule.RULE (+15 % net, the owner's stop -20 %, 7 days, 7-day zone, 1h bars; DCA off)
  entry   at the first tick after an hour completes, for every listed token not held and not cooling down:
          rule.signal on the completed 1h bars (support touched, bounce confirmed, stop below the support; BTC: never in
          a free fall, and while its bottom forms also a bounce with inflow: DexScreener buys >= 55 % of the hour and the
          hour's volume over its 6 h average, inflow_live) -> bought at the quote of that tick; hard
          rules (guards: bonded, MC >= 30k, liquidity >= 15k, not a fake pool, the rug archive, a rug collapse)
  exit    every tick: the take profit (tp_px: the net target at the trade's real cost, or the zone's mid / top frozen
          at the entry), the stop, the time stop, a rug
  caps    demo: DEMO_MAX_OPEN (30) open, DEMO_PER_DAY (120) a Zagreb day (x 1.5 while BTC's bottom forms), the open
          positions' stress loss (stop + 8 pp) at most DEMO_RISK_TOTAL (25 %) of the demo account, cooldown 6 h a
          token; size DEMO_SOL (0.5 SOL). Real (gate.REAL): 0.1 SOL, 5 open, 20 a day, a day's loss 0.3 SOL, MC 5-150M,
          liquidity >= $500k, round-trip cost <= 6 %, no DCA; the real trade carries the demo trade's id (link_id)
          and the proof's state (proof); every trade carries BTC's state (btc_state)
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
DEMO_MAX_OPEN = int(os.environ.get("VEL_DEMO_MAX_OPEN", "30"))     # 15.11. popodne: many demo trades on the midcaps
DEMO_PER_DAY = int(os.environ.get("VEL_DEMO_PER_DAY", "120"))
DOWN_BONUS = 1.5     # while BTC's bottom forms (the owner's preferred window) the demo's caps x this
# the critic: the stress loss of a position = its stop + STRESS_PP of slippage; all memecoins move together, so the sum
# over the open positions is capped (demo: DEMO_RISK_TOTAL of the demo account's equity)
STRESS_PP = 0.08
DEMO_RISK_TOTAL = float(os.environ.get("VEL_DEMO_RISK_TOTAL", "0.25"))
LIST_MAX_AGE_S = 72 * 3600
BARS_RELOAD_S = 600
BTC_RELOAD_S = 600
STALE_S = 60
SCHEMA = """CREATE TABLE IF NOT EXISTS veliki_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, opened_ts INTEGER, trade_id INTEGER,
    size_sol REAL, size_usd REAL, entry_px REAL, tp_px REAL, stop_px REAL, rt REAL, drt REAL, liq REAL, mcap REAL,
    cfg TEXT, zone TEXT, regime TEXT, status TEXT, closed_ts INTEGER, exit_px REAL, reason TEXT, ret REAL, pnl_usd REAL,
    ret_demo REAL, pnl_booked REAL, why TEXT, btc_state TEXT, proof TEXT, link_id INTEGER, peak REAL, trail REAL,
    time_h REAL);
CREATE INDEX IF NOT EXISTS veliki_trades_st ON veliki_trades (status, user);
CREATE TABLE IF NOT EXISTS veliki_bars (token TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, PRIMARY KEY (token, ts));"""
M15 = 900
_ST = {"tick": 0.0, "bar": {}, "said": {}, "gt": {}, "gt_ts": 0.0, "btc": None, "btc_ts": 0.0, "q": {}}
_LIVE = {}      # token -> [[ts, o, h, l, c], ...] own 15m bars (the last may be in progress)


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='veliki_bars'").fetchone() is None:
        con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(veliki_trades)")}
    for col, typ in (("btc_state", "TEXT"), ("proof", "TEXT"), ("link_id", "INTEGER"), ("peak", "REAL"),
                     ("trail", "REAL"), ("time_h", "REAL"), ("prio", "TEXT"), ("dip", "TEXT")):
        if col not in have:
            con.execute(f"ALTER TABLE veliki_trades ADD COLUMN {col} {typ}")


def mode():
    try:
        from trade import settings
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def _day_start(now):
    from league import copy as lcopy
    return lcopy._day_start(int(now))


# 15.11. navečer (coordinator: "if no backtest-picked rule exists yet, let veliki/live use a documented DEFAULT rule ...
# so demo and real start as soon as zones exist"): zone from the last 7 days, TP +8 % net then a 5 % trailing (the
# grid's trailing), the owner's stop -20 %, time stop 3 days. Used only while store.live_rule() is None; the log says so
# ("veliki: zadano pravilo (backtest još nema podataka)") once an hour; each trade carries its cfg key.
DEFAULT_RULE = {"tp": 8.0, "trail": 0.05, "time_h": 72, "look_d": 7}


def cfg_now():
    """The live rule: store.live_rule() merged over rule.RULE (crash filter always on); without a backtest-picked
    rule, DEFAULT_RULE over rule.RULE (c["default"] True)."""
    from veliki import rule, store
    lr = store.live_rule() or {}
    picked = {k: lr[k] for k in ("tp", "trail", "time_h", "look_d") if lr.get(k) is not None}
    c = {**rule.RULE, **(picked or DEFAULT_RULE)}
    c["default"] = not picked
    c["crash_filter"], c["btc_mode"], c["dca"] = True, "dno", 0.0   # the owner's -20 % stop stays; DCA off (critic)
    return c


# ---------- BTC ------------------------------------------------------------------------------------------------------

def btc_state(now=None):
    """{"known", "crash", "crash_obj"} from BTC hourly (veliki.db + market.db, cached BTC_RELOAD_S)."""
    from veliki import rule, store
    now = now or time.time()
    if _ST["btc"] is None or now - _ST["btc_ts"] > BTC_RELOAD_S:
        try:
            _ST["btc"] = rule.crash_of(store.btc_hourly())
        except Exception:  # noqa: BLE001
            _ST["btc"] = rule.NO_CRASH
        _ST["btc_ts"] = now
    cr = _ST["btc"]
    st, why = cr.regime(now)
    return {"known": cr.known(now), "crash": st == "slobodan_pad", "crash_obj": cr, "last_end": cr.last_end(now),
            "state": st, "why": why}


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
                b15 = []
                b1h = store.candles(con, "c1h", tok, now - 16 * 86400)
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
    """(completed 1h bars, the same as the zones' 1h candles): GeckoTerminal's 1h, then this module's own 15m bars
    (from the live quotes) rebuilt into hours after the newest of them (rule.h1_from_15m)."""
    from veliki import rule
    _b15, b1h = _gt(tok, now)
    last = b1h[-1][0] if b1h else 0
    h = int(now) - int(now) % 3600
    own = [tuple(b) + (0.0,) for b in _LIVE.get(tok) or [] if b[0] >= last + 3600 and b[0] < h]
    bars = [b for b in rule.h1_from_15m(own, b1h) if b[0] < h]
    return bars, bars


def inflow_live(tok, now):
    """DexScreener's buy share of the last hour (>= 0.55) and the hour's volume over its 6 h hourly average (one
    batched request an hour for the list, free): (ok, why)."""
    pairs = _ST.setdefault("dex", {})
    if now - _ST.get("dex_ts", 0) > 3600:
        _ST["dex"], _ST["dex_ts"] = {}, now
        try:
            from dexscreener import client
            lst = _list_tokens(now)
            for p in client.tokens("solana", lst) if lst else []:
                m = (p.get("baseToken") or {}).get("address")
                lq = (p.get("liquidity") or {}).get("usd") or 0
                if m and lq >= ((_ST["dex"].get(m) or {}).get("liquidity") or {}).get("usd", 0):
                    _ST["dex"][m] = p
        except Exception:  # noqa: BLE001 - no flow data: the bottom-forming entry waits
            pass
        pairs = _ST["dex"]
    p = pairs.get(tok)
    if not p:
        return False, "nema podataka o kupnjama"
    tx = (p.get("txns") or {}).get("h1") or {}
    b, sl = tx.get("buys") or 0, tx.get("sells") or 0
    v1, v6 = (p.get("volume") or {}).get("h1") or 0, (p.get("volume") or {}).get("h6") or 0
    share = b / (b + sl) if b + sl else 0.0
    ok = share >= 0.55 and v1 > v6 / 6
    return ok, f"kupnje {share:.0%} zadnji sat, volumen 1 h ${v1:,.0f} prema prosjeku 6 h ${v6 / 6:,.0f}"


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


def caps(user, btc_state=None):
    from trade import settings
    from veliki import gate
    if user == settings.LEAGUE_USER:
        c = gate.real_caps()
        return {"size_sol": c["size_sol"], "max_open": c["max_open"], "per_day": c["max_buys_day"],
                "loss_day_sol": c["max_loss_day_sol"], "real": True}
    k = DOWN_BONUS if btc_state == "dno_se_potvrduje" else 1.0
    return {"size_sol": DEMO_SOL, "max_open": int(DEMO_MAX_OPEN * k), "per_day": int(DEMO_PER_DAY * k),
            "loss_day_sol": None, "real": False}


def stress_room(con, user, add_usd, stop_frac):
    """None when one more position of add_usd still keeps the open positions' stress loss (stop + STRESS_PP) within the
    account's cap, else why (the critic: correlated exposure). Demo: DEMO_RISK_TOTAL of the account's equity; real:
    the gate's max_open x size already is the cap."""
    from league import store as lstore
    try:
        acc = lstore.account(con, user)
        eq = float((acc.get("start") or 0) + (acc.get("realized") or 0))
    except Exception:  # noqa: BLE001
        return None
    if eq <= 0:
        return None
    rows = con.execute("SELECT size_usd, entry_px, stop_px FROM veliki_trades WHERE user=? AND status='open'",
                       (user,)).fetchall()
    risk = sum(u * (1 - (sp or 0) / (e or 1) + STRESS_PP) for u, e, sp in rows) + add_usd * (stop_frac + STRESS_PP)
    if risk > DEMO_RISK_TOTAL * eq:
        return f"rizik otvorenih pozicija ${risk:,.0f} iznad {DEMO_RISK_TOTAL:.0%} računa (${eq:,.0f})"
    return None


def enter(con, user, tok, mq, now, sol, zone, cfg, regime=None, btc=None, link_id=None, meta=None):
    """One entry; (text or None, why not or None, veliki_trades id or None)."""
    import json
    from league import store as lstore
    from trade import settings
    from veliki import gate, rule, universe
    st = (btc or {}).get("state")
    cp = caps(user, st)
    real = user == settings.LEAGUE_USER
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token", None
    n_open = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
    if n_open >= cp["max_open"]:
        return None, f"već {n_open} otvorenih (strop {cp['max_open']})", None
    n_day = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND opened_ts>=?",
                        (user, _day_start(now))).fetchone()[0]
    if n_day >= cp["per_day"]:
        return None, f"dnevni strop ulaza ({cp['per_day']}) potrošen", None
    if cp.get("loss_day_sol"):
        lost = con.execute("SELECT COALESCE(SUM(pnl_usd), 0) FROM veliki_trades WHERE user=? AND status='closed' "
                           "AND closed_ts>=?", (user, _day_start(now))).fetchone()[0]
        if lost <= -cp["loss_day_sol"] * sol:
            return None, f"dnevni gubitak {lost:.2f} $ dosegao strop {cp['loss_day_sol']:g} SOL", None
    g = guards(tok, mq)
    if g:
        return None, g, None
    price, liq, url, mcap = mq[:4]
    if not (universe.MIN_MCAP <= (mcap or 0) <= universe.MAX_MCAP):
        return None, f"MC ${(mcap or 0) / 1e6:,.1f}M izvan 5-150M", None
    if real and (liq or 0) < universe.REAL_MIN_LIQ:
        return None, f"likvidnost ${(liq or 0) / 1e3:,.0f}k ispod ${universe.REAL_MIN_LIQ / 1e3:,.0f}k za pravi novac", None
    sym = (mq[4] if len(mq) > 4 else None) or tok[:6]
    size_usd = cp["size_sol"] * sol
    c = rule.cost_at(cp["size_sol"], liq, sol, rule.fee_side_of(url=url), rule.tx_sol()[0])
    if real and c["rt"] > 0.06:
        return None, f"trošak runde {c['rt']:.1%} iznad 6 %", None
    drt = rule.demo_rt(size_usd, liq)
    tp = rule.tp_price(price, cfg["tp"], c["rt"], zone, cfg)
    if tp <= price:
        return None, "cilj nije iznad ulaza", None
    stop = rule.stop_px(price, zone, cfg)
    if not real:
        why = stress_room(con, user, size_usd, 1 - stop / price)
        if why:
            return None, why, None
    proof = None
    if real:
        ok, pw, _x = gate.wf_proof(size_sol=cp["size_sol"])
        proof = "dokaz prošao" if ok else f"bez dokaza ({pw})"
    zt = (f"podrška {zone['s_lo']:.6g}-{zone['s_hi']:.6g}" if zone and zone.get("ok") else "bez raspona")
    why = (f"{SRC}: {zt}, cilj {tp / price - 1:+.1%}{' + trailing' if cfg.get('trail') else ''}, stop "
           f"{stop / price - 1:+.0%}, BTC {st or '?'}" + (", novi raspon nakon pada BTC-a" if (zone or {}).get("fresh") else ""))
    try:
        tid = lstore.buy(con, user, tok, sym, size_usd, price, liq, why[:200], None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})", None
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))   # this module sells it
    zj = {k: round(zone[k], 10) for k in ("s_lo", "s_hi", "r_lo", "r_hi", "mid") if (zone or {}).get(k) is not None}
    zj["fresh"] = bool((zone or {}).get("fresh"))
    cur = con.execute(
        "INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, tp_px, "
        "stop_px, rt, drt, liq, mcap, cfg, zone, regime, status, why, btc_state, proof, link_id, trail, time_h, prio, "
        "dip) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?,?,?,?,?,?,?)",
        (user, tok, sym, int(now), tid, cp["size_sol"], size_usd, price, tp, stop, c["rt"], drt, liq, mcap,
         rule.cfg_key(cfg), json.dumps(zj), regime, why[:200], st, proof, link_id, cfg.get("trail") or 0.0,
         cfg["time_h"], (meta or (None, None))[0], (meta or (None, None))[1]))
    con.commit()
    head = "veliki PRAVI NOVAC: kupnja" if real else "veliki demo ulaz"
    return (f"{head} {sym} {cp['size_sol']:g} SOL na MC ${(mcap or 0) / 1e6:,.1f}M, zona {zt}, stop {stop:.6g} "
            f"({stop / price - 1:+.0%}), TP {tp:.6g} ({tp / price - 1:+.1%}"
            f"{', trailing ' + format(cfg['trail'], '.0%') if cfg.get('trail') else ''}), {cfg['time_h'] / 24:g} d; "
            f"BTC {st or '?'}; pravi trošak runde {c['rt']:.2%}" + (f"; {proof}" if proof else "")), None, cur.lastrowid


def exit_why(r, price, age, now, mq, time_h):
    """(reason or None, new peak): stop, trailing after the target (trail > 0), the target, the time stop, a rug."""
    trail = r.get("trail") or 0.0
    peak = r.get("peak")
    if price <= r["stop_px"]:
        return "stop", peak
    if age > STALE_S:
        return None, peak
    if trail:
        if price >= r["tp_px"]:
            peak = max(peak or 0.0, price)
        if peak and price <= max(peak * (1 - trail), r["tp_px"] * (1 - trail)):
            return "trail", peak
    elif price >= r["tp_px"]:
        return "tp", peak
    if now - r["opened_ts"] >= (r.get("time_h") or time_h) * 3600:
        return ("trail" if peak else "time"), peak
    if mq is not None:
        from league import copy as lcopy
        try:
            col = lcopy._rugged(r["token"], mq[3], mq[1])
        except Exception:  # noqa: BLE001
            col = None
        if col:
            return "rug", peak
    return None, peak


def close(con, r, price, liq, mcap, reason, now):
    from league import store as lstore
    from trade import settings
    from veliki import rule
    booked = None
    t = con.execute("SELECT status FROM trades WHERE id=?", (r["trade_id"],)).fetchone()
    if t and t[0] == "open":
        rr = {"tp": "tp", "trail": "trailing", "stop": "sl", "time": "time", "rug": "rug"}.get(reason, "sl")
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
    head = "veliki PRAVI NOVAC" if r["user"] == settings.LEAGUE_USER else "veliki"
    return (f"{head} {r['symbol']}: {rule.REASON_HR.get(reason, reason)}, {ret * r['size_usd']:+.2f} $ pravim troškom "
            f"({ret:+.1%}), uz izmjerenu naknadu {rd:+.1%}, knjiženo {booked or 0:+.2f} $")


def _list_tokens(now):
    from veliki import store
    lst = store.the_list() or {}
    if now - (lst.get("ts") or 0) > LIST_MAX_AGE_S:
        return []
    return [x["mint"] for x in lst.get("tokens") or [] if x.get("mint")]


def day_line(con, day_start):
    """The day summary: demo and real veliki trades opened / closed and their PnL since day_start."""
    from trade import settings
    parts = []
    for user, name in ((settings.PAPER_USER, "demo"), (settings.LEAGUE_USER, "pravi")):
        n_o = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND opened_ts>=?", (user, day_start)).fetchone()[0]
        n_c, pnl = con.execute("SELECT COUNT(*), COALESCE(SUM(pnl_usd), 0) FROM veliki_trades WHERE user=? AND "
                               "status='closed' AND closed_ts>=?", (user, day_start)).fetchone()
        n_open = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
        parts.append(f"{name} {n_o} ulaza, {n_c} zatvorenih ({pnl:+.2f} $ pravim troškom), {n_open} otvorenih")
    return "veliki: dan: " + "; ".join(parts)


def tick(con, market_fn, now=None, force=False, toks=None):
    """One pass: exits of the open trades, then (after an hour completed) the entries. [text]."""
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
    out = []
    day = _day_start(now)
    if _ST.get("day") is not None and day != _ST["day"]:
        out.append(day_line(con, _ST["day"]))
    _ST["day"] = day
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
        return out
    mk = market_fn(all_t) or {}
    for tok in all_t:
        q = mk.get(tok)
        if q and q[0]:
            add_price(con, tok, q[0], now)
            _ST["q"][tok] = (q, now)
    con.commit()
    cfg = cfg_now()
    if cfg.get("default") and now - _ST.get("default_said", 0) >= 3600:
        _ST["default_said"] = now
        out.append("veliki: zadano pravilo (backtest još nema podataka): zona zadnjih 7 d, TP +8 % neto pa trailing 5 %, "
                   "stop −20 %, vremenski stop 3 d")
    for r in opened:
        q, ts = _ST["q"].get(r["token"], (None, 0))
        if not q:
            continue
        why, peak = exit_why(r, q[0], now - ts, now, q if now - ts <= STALE_S else None, cfg["time_h"])
        if peak != r.get("peak"):
            con.execute("UPDATE veliki_trades SET peak=? WHERE id=?", (peak, r["id"]))
        if why:
            out.append(close(con, r, q[0], q[1], q[3] if len(q) > 3 else None, why, now))
    con.commit()
    if not users:
        return out
    hour = int(now) - int(now) % 3600
    btc = btc_state(now)
    if _ST.get("btc_said") != btc["state"]:
        _ST["btc_said"] = btc["state"]
        out.append(f"veliki BTC: {btc['state'].replace('_', ' ')} — {btc['why']}")
    sol = _sol()
    tx = rule.tx_sol()[0]
    held = {(r["user"], r["token"]) for r in open_rows(con)}
    # 15.11. navečer (vlasnik: "kreni od TRENDING i najvećeg VOLUMENA, usporedi BUZZ ... posebno one koji su malo PALI;
    # istraži ZAŠTO"; veliki/prioritet.py): candidates in priority order; a dip with a bad reason is skipped; every
    # trade stores its priority components and its dip reason (prio, dip) for the critic / backtest
    try:
        from veliki import prioritet
        pr = prioritet.cached()
        lst = prioritet.order(lst, pr)
        real_rank = {t: k for k, t in enumerate(prioritet.order(lst, pr, real=True))}
    except Exception:  # noqa: BLE001 - no priority: the list order
        prioritet, pr = None, {}
        real_rank = {t: k for k, t in enumerate(lst)}
    deferred = []   # 15.11. (holderi/): the real account's entries, taken after the loop in its own order (no listing bonus)
    for tok in lst:
        if _ST["bar"].get(tok) == hour:
            continue
        dip = (pr.get(tok) or {}).get("dip") or {}
        if dip.get("kind") == "los":
            if now - _ST["said"].get(("dip", tok), 0) > 3600:
                _ST["said"][("dip", tok)] = now
                out.append(f"veliki {(pr[tok].get('symbol') or tok[:6])}: preskočen, pad iz lošeg razloga ({dip.get('why')})")
            continue
        blk = (pr.get(tok) or {}).get("block")
        if blk:   # 15.11. (holderi/): insiders hold too much / the team is selling: no entry (demo or real)
            if now - _ST["said"].get(("blk", tok), 0) > 3600:
                _ST["said"][("blk", tok)] = now
                out.append(f"veliki {(pr[tok].get('symbol') or tok[:6])}: preskočen, oprez ({blk})")
            continue
        q = mk.get(tok)
        if not q or not q[0]:
            continue
        _ST["bar"][tok] = hour
        bars, h1 = series(tok, now)
        if len(bars) < 24:
            continue
        last = con.execute("SELECT MAX(closed_ts) FROM veliki_trades WHERE token=?", (tok,)).fetchone()[0]
        if last and now - last < cfg["cooldown_s"]:
            continue
        zone = rule.Zones(h1, btc["crash_obj"]).at(hour, cfg["look_d"])
        i = len(bars) - 1
        if btc["state"] == "dno_se_potvrduje" and not (zone or {}).get("ok"):
            ok, _w = inflow_live(tok, now)
            if not ok:
                continue
        regime = _regime(now)
        link = None
        for user in users:   # the demo first: the real trade of the same signal carries its id (link_id)
            if (user, tok) in held:
                continue
            if user != settings.PAPER_USER:
                deferred.append((real_rank.get(tok, len(real_rank)), tok, user, q, zone, regime, bars, i, link))
                continue
            link = _try_enter(con, out, user, tok, q, now, sol, zone, cfg, regime, btc, link, bars, i, tx, rule,
                              prioritet, pr) or link
    for _k, tok, user, q, zone, regime, bars, i, link in sorted(deferred, key=lambda x: x[0]):
        _try_enter(con, out, user, tok, q, now, sol, zone, cfg, regime, btc, link, bars, i, tx, rule, prioritet, pr)
    if int(now) % 3600 < TICK_S:
        con.execute("DELETE FROM veliki_bars WHERE ts < ?", (int(now - 10 * 86400),))
        con.commit()
    return out


def _try_enter(con, out, user, tok, q, now, sol, zone, cfg, regime, btc, link, bars, i, tx, rule, prioritet, pr):
    """One user's entry on one token when the rule signals (the cost at its size). The new trade id or None."""
    cp = caps(user, btc["state"])
    c = rule.cost_at(cp["size_sol"], q[1], sol, rule.fee_side_of(url=q[2] if len(q) > 2 else None), tx)
    why = rule.signal(bars, i, zone, c["rt"], cfg, btc["crash_obj"])
    if why is not None:
        return None
    text, no, vid = enter(con, user, tok, q, now, sol, zone, cfg, regime, btc, link,
                          meta=prioritet.meta(tok, pr) if prioritet else None)
    if text:
        out.append(text)
    elif no and now - _ST["said"].get((user, tok), 0) > 3600:
        _ST["said"][(user, tok)] = now
        out.append(f"veliki {(q[4] if len(q) > 4 else None) or tok[:6]}: signal bez ulaza ({no})")
    return vid


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
            b15 = store.candles(con, "c1h", x["mint"], now - 16 * 86400)
            h1 = b15
            z = rule.Zones(h1, btc["crash_obj"]).at(now, cfg["look_d"])
            q = (_ST["q"].get(x["mint"]) or (None, 0))[0]
            px = (q[0] if q else None) or (b15[-1][4] if b15 else None)
            pos = None
            if z.get("ok") and px:
                pos = round((px - z["s_lo"]) / (z["r_hi"] - z["s_lo"]) * 100, 1) if z["r_hi"] > z["s_lo"] else None
            out.append({"symbol": x.get("symbol"), "mint": x["mint"], "price": px, "zone_ok": bool(z.get("ok")),
                        "why": z.get("why"), "fresh": z.get("fresh"), "pos_pct": pos, "cat": x.get("cat"),
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
