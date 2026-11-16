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

15.11. ~12:35 UTC (vlasnik: "lista od barem 100 tokena, do 100 tradeova dnevno s ~10 %, više tradeova po tokenu"):
  universe  the DEMO universe demo_tokens(): the veliki list + the midcap collector's members (2M-200M, liquidity and
            volume >= $100k, memecoins), the trending first; its quotes every UNIV_EVERY_S, the open trades every tick
  intraday  veliki/intra.py next to the 7-day rule: the zone of the last 48 h (1h candles, every hour with 15m bars
            rebuilt from GeckoTerminal's 15m / the collector's snapshots / this module's quotes), the entry in the
            bottom 25 % once the bars stopped falling, never in a BTC free fall; half at +10 % net, the rest's stop to
            break-even + 5 % trailing, the stop under the zone (at most -12 %), 24 h; cooldown 30 min, at most 3 rounds
            a token a day; demo 0.1 SOL (the real cost model), 30 open, 100 a day; REAL only on the veliki list's tokens
  exits     both rules (rule.on_price): with a trailing the target sells HALF (league sell_part: run_trade mirrors the
            share), the rest's stop moves to break-even and trails from its peak (the critic: no whole position at
            ~+2.6 % any more); every hour the report line (report_line) and the refused candidates by rule
"""
import os
import re
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
# 15.11. ~12:35 UTC (vlasnik: "lista od barem 100 tokena ... do 100 tradeova dnevno s ~10 %, više tradeova po tokenu";
# veliki/intra.py): the DEMO universe = the veliki list + the midcap collector's members (MC 2M-200M, liquidity and 24 h
# volume >= $100k, bonded AMM, a memecoin; no 15-day age floor for the demo), the trending ones first; the intraday rule
# trades it in the demo at INTRA_DEMO_SOL (0.1 SOL: the real cost model, honest numbers), INTRA_MAX_OPEN open and
# INTRA_PER_DAY a Zagreb day; REAL only on the veliki list's tokens (age >= 15 d, MC 5-150M, liquidity >= $500k) under
# the gate's caps (shared with the 7-day rule)
INTRA_DEMO_SOL = float(os.environ.get("VEL_INTRA_DEMO_SOL", "0.1"))
INTRA_MAX_OPEN = int(os.environ.get("VEL_INTRA_MAX_OPEN", "30"))
INTRA_PER_DAY = int(os.environ.get("VEL_INTRA_PER_DAY", "100"))
# 16.11. (vlasnik: "treba što više tradeova danas"): the DEMO's list from $50k liquidity / volume (was $100k: ~47
# tokens); the real account's own floors (veliki list, liquidity >= $500k, MC >= 5M) do not move
DEMO_MIN_LIQ = float(os.environ.get("VEL_DEMO_MIN_LIQ", "50000"))
DEMO_MIN_VOL = float(os.environ.get("VEL_DEMO_MIN_VOL", "50000"))
DEMO_UNIV_MAX = int(os.environ.get("VEL_DEMO_UNIV_MAX", "250"))
UNIV_EVERY_S = 30     # the demo universe's quotes this often (the open positions every tick)
# 15.11. (vlasnik: "uključi DCA: tokeni poput Uselessa su se puno puta oporavili na prvi znak oporavka Bitcoina"): one
# DCA lot per position (real 0.1 SOL -> at most 0.2 SOL a token; demo the same lot again) at DCA_PCT under the FIRST
# entry (VEL_DCA_MODE "zona" / "atr": the zone's low / 3 x ATR), only when rule.dca_refusal passes (BTC not in a free
# fall, the macro regime not risk_off, the dip's reason not bad, category A / B with a history of recovering after BTC
# +3 % days, the volume holding, the day's caps: the lot counts in the buys a day and the day's loss); VEL_DCA=0 off
DCA_PCT = float(os.environ.get("VEL_DCA", "0.10"))
DCA_MODE = os.environ.get("VEL_DCA_MODE", "pct")
MID_RELOAD_S = 300    # midcap.db's 15m / 1h candles and snapshots re-read this often (read-only)
LIST_MAX_AGE_S = 72 * 3600
BARS_RELOAD_S = 600
BTC_RELOAD_S = 600
STALE_S = 60
# 16.11. (vlasnik, jutarnji izvještaj: "demo pozicija zatvorena na -59,4 % dok je SL bio oko -20 %"): the 24 h liquidity
# signal (prioritet.dynamic_bad, -30 %, refreshed every collector pass) and the rug check (rugfilter/collapse on hype.db,
# which the midcaps no longer feed while fokus_midcap holds the hype scan) are too slow or blind for a pool pulled
# within the hour: the stop then fills far under its level. An open position (demo and real) also exits when the
# deepest pool's liquidity is at or under LIQ_EXIT_DROP of its highest in the last hour (this loop's own quotes every
# tick, the entry's liquidity counted inside the hour), seen on LIQ_CONFIRM fresh quotes in a row (one bad read is no
# exit). Price-only moves cannot do it: a constant-product pool's USD depth falls with the square root of the price,
# so -50 % of liquidity is -75 % of price, under every stop. The other exit rules are the owner's and unchanged.
LIQ_EXIT_DROP = 0.5
LIQ_CONFIRM = 2
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
                     ("trail", "REAL"), ("time_h", "REAL"), ("prio", "TEXT"), ("dip", "TEXT"), ("kind", "TEXT"),
                     ("half_frac", "REAL"), ("half_px", "REAL"), ("half_ts", "INTEGER"), ("be_px", "REAL"),
                     ("first_px", "REAL"), ("lots", "INTEGER"), ("dca_trade_id", "INTEGER"), ("dca_px", "REAL"),
                     ("dca_ts", "INTEGER"), ("dca_why", "TEXT"), ("exit_why", "TEXT"), ("makro", "TEXT")):
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
    picked = {k: lr[k] for k in ("tp", "trail", "time_h", "look_d", "near", "touch_bars") if lr.get(k) is not None}
    c = {**rule.RULE, **(picked or DEFAULT_RULE)}
    c["default"] = not picked
    # the owner's -20 % stop stays; 15.11. (vlasnik: "uključi DCA"): one smart DCA lot (rule.dca_refusal) at DCA_PCT
    c["crash_filter"], c["btc_mode"], c["dca"], c["dca_mode"] = True, "dno", DCA_PCT, DCA_MODE
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


def caps(user, btc_state=None, kind=None):
    """The caps of one account for one rule: real (gate.REAL, shared by both rules: 0.1 SOL, 5 open, 20 buys a day
    incl. the DCA lots, a day's loss 0.3 SOL); demo: the 7-day rule DEMO_* (x DOWN_BONUS while BTC's bottom forms),
    the intraday rule INTRA_* at INTRA_DEMO_SOL."""
    from trade import settings
    from veliki import gate
    if user == settings.LEAGUE_USER:
        c = gate.real_caps()
        return {"size_sol": c["size_sol"], "max_open": c["max_open"], "per_day": c["max_buys_day"],
                "loss_day_sol": c["max_loss_day_sol"], "real": True, "kind": None}
    # 15.11.: the macro regime risk_on -> more demo entries (never real); 16.11.: the same while "oporavak" holds
    on = _ST.get("macro") == "risk_on" or bool(_ST.get("oporavak"))
    if kind == "intra":
        k = 1.5 if on else 1.0
        return {"size_sol": INTRA_DEMO_SOL, "max_open": int(INTRA_MAX_OPEN * k), "per_day": int(INTRA_PER_DAY * k),
                "loss_day_sol": None, "real": False, "kind": "intra"}
    k = (DOWN_BONUS if btc_state == "dno_se_potvrduje" else 1.0) * (1.5 if on else 1.0)
    return {"size_sol": DEMO_SOL, "max_open": int(DEMO_MAX_OPEN * k), "per_day": int(DEMO_PER_DAY * k),
            "loss_day_sol": None, "real": False, "kind": "range"}


def _kind_sql(cp):
    """(SQL condition, args) of the rows a cap counts: real all; demo its own rule's rows."""
    if cp.get("kind") is None:
        return "", ()
    if cp["kind"] == "intra":
        return " AND kind='intra'", ()
    return " AND COALESCE(kind, 'range')<>'intra'", ()


def buys_today(con, user, now, cp=None):
    """Buys of the day (the entries + the DCA lots) of this account (and rule, demo)."""
    ks, ka = _kind_sql(cp or {})
    d0 = _day_start(now)
    n = con.execute(f"SELECT COUNT(*) FROM veliki_trades WHERE user=? AND opened_ts>=?{ks}", (user, d0, *ka)).fetchone()[0]
    n += con.execute(f"SELECT COUNT(*) FROM veliki_trades WHERE user=? AND dca_ts>=?{ks}", (user, d0, *ka)).fetchone()[0]
    return n


def room(con, user, now, sol, cp, new_position=True):
    """None when this account may buy once more now (a new position, or new_position False: a DCA lot), else why."""
    ks, ka = _kind_sql(cp)
    if new_position:
        n_open = con.execute(f"SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'{ks}",
                             (user, *ka)).fetchone()[0]
        if n_open >= cp["max_open"]:
            return f"već {n_open} otvorenih (strop {cp['max_open']})"
    n_day = buys_today(con, user, now, cp)
    if n_day >= cp["per_day"]:
        return f"dnevni strop kupnji ({cp['per_day']}, s DCA lotovima) potrošen"
    if cp.get("loss_day_sol"):
        lost = con.execute("SELECT COALESCE(SUM(pnl_usd), 0) FROM veliki_trades WHERE user=? AND status='closed' "
                           "AND closed_ts>=?", (user, _day_start(now))).fetchone()[0]
        if lost <= -cp["loss_day_sol"] * sol:
            return f"dnevni gubitak {lost:.2f} $ dosegao strop {cp['loss_day_sol']:g} SOL"
    return None


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


def enter(con, user, tok, mq, now, sol, zone, cfg, regime=None, btc=None, link_id=None, meta=None, kind="range"):
    """One entry; (text or None, why not or None, veliki_trades id or None). kind "range" (the 7-day rule, rule.py)
    or "intra" (veliki/intra.py: the stop under the intraday zone, half at +10 % net)."""
    import json
    from league import store as lstore
    from trade import settings
    from veliki import gate, intra, rule, universe
    st = (btc or {}).get("state")
    cp = caps(user, st, kind)
    real = user == settings.LEAGUE_USER
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token", None
    why = room(con, user, now, sol, cp)
    if why:
        return None, why, None
    g = guards(tok, mq)
    if g:
        return None, g, None
    price, liq, url, mcap = mq[:4]
    lo_mc, hi_mc = (universe.MIN_MCAP, universe.MAX_MCAP) if real else (universe.DATA_MIN_MCAP, universe.DATA_MAX_MCAP)
    if not (lo_mc <= (mcap or 0) <= hi_mc):
        return None, f"MC ${(mcap or 0) / 1e6:,.1f}M izvan {lo_mc / 1e6:g}-{hi_mc / 1e6:g}M", None
    if real and (liq or 0) < universe.REAL_MIN_LIQ:
        return None, f"likvidnost ${(liq or 0) / 1e3:,.0f}k ispod ${universe.REAL_MIN_LIQ / 1e3:,.0f}k za pravi novac", None
    if not real and kind == "intra" and (liq or 0) < DEMO_MIN_LIQ:
        return None, f"likvidnost ${(liq or 0) / 1e3:,.0f}k ispod ${DEMO_MIN_LIQ / 1e3:,.0f}k", None
    sym = (mq[4] if len(mq) > 4 else None) or tok[:6]
    if real and (meta is None or meta[0] is None):   # 15.11. popodne: no priority row = holder / safety facts unknown
        return None, "prioritet (holderi, sigurnost) još nije izračunat", None
    size_usd = cp["size_sol"] * sol
    c = rule.cost_at(cp["size_sol"], liq, sol, rule.fee_side_of(url=url), rule.tx_sol()[0])
    drt = rule.demo_rt(size_usd, liq)
    # 15.11. popodne: the model (pool + route fee, impact, network) said 0.72 % a round trip while the measured fee
    # (trade/cost calibration of the real swaps) gave 61V8vB -4.9 % against -2.2 %: every target, break-even and
    # result now uses the HIGHER of the two, so the demo and the real numbers are honest
    c = dict(c, rt=max(c["rt"], drt))
    if real and c["rt"] > 0.06:
        return None, f"trošak runde {c['rt']:.1%} iznad 6 %", None
    tp = rule.tp_price(price, cfg["tp"], c["rt"], zone, cfg)
    if tp <= price:
        return None, "cilj nije iznad ulaza", None
    stop = intra.stop_px(price, zone, cfg) if kind == "intra" else rule.stop_px(price, zone, cfg)
    # 16.11. (production: the real account bought Dz9mQ9 three times and sold it 9-11 s later each time, "razlog pada
    # postao loš: prijenos na burzu (depozit za prodaju)", -2.6 % .. -5.6 % a round: the exit read a reason the entry
    # never asked about). The entry now asks the EXIT's own question first: what manage() would sell at once
    # (rule.reasoned_exit on live.context: a bad reason, a volume collapse) is not bought, on either account.
    try:
        ctx = context(tok, now)
        rs, _tight = rule.reasoned_exit({"entry": price, "first": price, "stop_px": stop}, price, c["rt"], ctx,
                                        {**cfg, "exit_slip": 0.0})
    except Exception:  # noqa: BLE001 - an unreadable context is no reason to buy blind with real money
        rs, ctx = ("nepoznato" if real else None), {}
    if rs:
        return None, (f"izlaz bi odmah prodao ({rule.REASON_HR.get(rs, rs)}"
                      + (f": {ctx_text(ctx)}" if ctx else "") + ")"), None
    if not real:
        why = stress_room(con, user, size_usd, 1 - stop / price)
        if why:
            return None, why, None
    proof = None
    if real:
        ok, pw, _x = gate.wf_proof(size_sol=cp["size_sol"])
        proof = "dokaz prošao" if ok else f"bez dokaza ({pw})"
        # 15.11. navečer (vlasnik: "neka trguje s pravim novcem ... želim da pokušaš biti profitabilan s pravim novcem
        # što je više moguće"): the 7-day rule's holdout at the real size is EV -3.9 % with the whole 95 % interval under
        # 0 (n=181), so real money goes only to the intraday rule (no history against it yet) while the 7-day rule
        # trades the demo; the 7-day rule comes back to real money by itself once its holdout is positive
        if kind != "intra" and not ok:
            return None, f"pravilo 7 d samo u demu dok holdout nije pozitivan ({pw})", None
    half = rule.half_of(cfg)
    if kind == "intra":
        zt = f"dnevna zona {zone['lo']:.6g}-{zone['hi']:.6g} ({zone['width']:.0%})"
    else:
        zt = (f"podrška {zone['s_lo']:.6g}-{zone['s_hi']:.6g}" if zone and zone.get("ok") else "bez raspona")
    tail = (f" (cijeli profit; kad tržište raste pola, ostatak BE + trailing {cfg['trail']:.0%})" if half
            else (" + trailing" if cfg.get("trail") else ""))
    why = (f"{SRC}: {zt}, cilj {tp / price - 1:+.1%}{tail}, stop {stop / price - 1:+.0%}, BTC {st or '?'}"
           + (", novi raspon nakon pada BTC-a" if (zone or {}).get("fresh") else ""))
    try:
        tid = lstore.buy(con, user, tok, sym, size_usd, price, liq, why[:200], None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})", None
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))   # this module sells it
    zj = {k: round(zone[k], 10) for k in ("s_lo", "s_hi", "r_lo", "r_hi", "mid", "lo", "hi", "atr")
          if (zone or {}).get(k) is not None}
    zj["fresh"] = bool((zone or {}).get("fresh"))
    key = intra.KEY if kind == "intra" else rule.cfg_key(cfg)
    cur = con.execute(
        "INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, tp_px, "
        "stop_px, rt, drt, liq, mcap, cfg, zone, regime, status, why, btc_state, proof, link_id, trail, time_h, prio, "
        "dip, kind, half_frac, be_px, first_px, makro, lots) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?,?,?,?,?,"
        "?,?,?,?,?,?,?,1)",
        (user, tok, sym, int(now), tid, cp["size_sol"], size_usd, price, tp, stop, c["rt"], drt, liq, mcap,
         key, json.dumps(zj), regime, why[:200], st, proof, link_id, cfg.get("trail") or 0.0,
         cfg["time_h"], (meta or (None, None))[0], (meta or (None, None))[1], kind, half,
         rule.be_price(price, c["rt"], {"exit_slip": 0.0}), price, _ST.get("makro_tag")))
    con.commit()
    head = "veliki PRAVI NOVAC: kupnja" if real else "veliki demo ulaz"
    rname = "dnevni raspon" if kind == "intra" else "raspon 7 d"
    return (f"{head} {sym} ({rname}) {cp['size_sol']:g} SOL na MC ${(mcap or 0) / 1e6:,.1f}M, zona {zt}, stop "
            f"{stop:.6g} ({stop / price - 1:+.0%}), TP {tp:.6g} ({tp / price - 1:+.1%}"
            f"{', cijeli profit; pola pa BE + trailing ' + format(cfg['trail'], '.0%') + ' samo kad tržište raste' if half else ''}"
            f"{', trailing ' + format(cfg['trail'], '.0%') if cfg.get('trail') and not half else ''}), "
            f"{cfg['time_h'] / 24:g} d; BTC {st or '?'}; pravi trošak runde {c['rt']:.2%}"
            + (f"; {proof}" if proof else "")), None, cur.lastrowid


def pos_of(r):
    """The rule.on_price position of a veliki_trades row (the average entry, the half, the break-even)."""
    from veliki import rule
    be = r.get("be_px") or rule.be_price(r["entry_px"], r.get("rt") or 0.0, {"exit_slip": 0.0})
    pos = {"entry": r["entry_px"], "first": r.get("first_px") or r["entry_px"], "ts": r["opened_ts"],
           "tp_px": r["tp_px"], "stop_px": r["stop_px"], "be_px": be, "peak": r.get("peak")}
    if r.get("half_px"):
        pos["half_px"], pos["half"] = r["half_px"], r.get("half_frac") or 0.5
    if pos["stop_px"] >= be * 0.999:
        pos["be_armed"] = True
    return pos


def full_tp(now):
    """(take the whole profit at the target?, why): True unless veliki/makro.bull says the whole market rises (BTC up
    3 %+ in 24 h, the meme sector green, regime risk_on): then half at the target and the rest trails (15.11.)."""
    try:
        from veliki import makro
        b, why = makro.bull(now)
    except Exception:  # noqa: BLE001 - unknown: the whole profit
        return True, "makro nepoznat"
    return (not b), ("tržište raste (" + why + "): pola na cilju, ostatak trailing" if b else "BTC u rangeu (" + why + ")")


def row_cfg(r):
    """The exit config of a row: its trailing, its half (NULL on rows from before the fix: rule.RULE half), and live
    fills at the quote (no extra slippage: the cost is in rt)."""
    from veliki import rule
    h = r.get("half_frac")
    return {"trail": r.get("trail") or 0.0, "half": rule.RULE["half"] if h is None else h, "exit_slip": 0.0,
            "stop_slip": 0.0, "stop_fill": "level", "be_at": rule.OWNER_EXIT["be_at"]}


def half_sale(con, r, pos, price, liq, now):
    """The target's first touch with a trailing: sell pos["half"] of every lot (league store sell_part; run_trade
    mirrors the share on the real account), the rest's stop to break-even. Text for the log."""
    from league import store as lstore
    from veliki import rule
    h = pos.get("half") or 0.5
    for tid in (r["trade_id"], r.get("dca_trade_id")):
        if tid:
            lstore.sell_part(con, tid, h, price, liq)
    con.execute("UPDATE veliki_trades SET half_px=?, half_ts=?, stop_px=?, peak=?, be_px=? WHERE id=?",
                (pos["half_px"], int(now), pos["stop_px"], pos.get("peak"), pos.get("be_px"), r["id"]))
    con.commit()
    r.update(half_px=pos["half_px"], half_ts=int(now), stop_px=pos["stop_px"], peak=pos.get("peak"))
    got = rule.net_ret(r["entry_px"], pos["half_px"], r["rt"])
    head = "veliki PRAVI NOVAC" if r["user"] == _league_user() else "veliki"
    return (f"{head} {r['symbol']}: {h:.0%} prodano na cilju ({got:+.1%} neto), ostatak: stop na break-even "
            f"{pos['stop_px']:.6g}, trailing {r.get('trail') or 0:.0%} od vrha")


def _league_user():
    from trade import settings
    return settings.LEAGUE_USER


def _win():
    """The quotes' liquidity of the last hour per open token (trade/stopgap.Window, this process's memory)."""
    w = _ST.get("win")
    if w is None:
        from trade import stopgap
        w = _ST["win"] = stopgap.Window()
    return w


def liq_drop(r, q, now, q_ts=None):
    """16.11.: the reason text when the pool's liquidity is at or under LIQ_EXIT_DROP of its highest in the last hour
    on LIQ_CONFIRM fresh quotes in a row (the count kept per row; q_ts = the quote's time, the same quote twice is one
    confirmation), else None."""
    liq = q[1] if len(q) > 1 else None
    ref = _win().ref(r["token"], now, extra=(r.get("opened_ts"), r.get("liq")))
    low = _ST.setdefault("liq_low", {})
    if not liq or liq <= 0 or not ref or liq > LIQ_EXIT_DROP * ref:
        low.pop(r["id"], None)
        return None
    seen = low.get(r["id"]) or (0, None)
    qid = q_ts if q_ts is not None else now
    n = seen[0] if seen[1] == qid else seen[0] + 1
    low[r["id"]] = (n, qid)
    if n < LIQ_CONFIRM:
        return None
    low.pop(r["id"], None)
    return f"likvidnost ${liq / 1e3:,.0f}k, {liq / ref - 1:+.0%} od najviše u zadnjem satu (${ref / 1e3:,.0f}k)"


def manage(con, r, q, age, now, cfg):
    """The exits of one open row at the quote q (age seconds old): the stop (even on a stale quote), then the half at
    the target, the trailing / break-even of the rest, the plain target, the time stop, a rug. [text]."""
    from veliki import rule
    price = q[0]
    out = []
    pos = pos_of(r)
    rc = row_cfg(r)
    rc["full_tp"], bull_why = full_tp(now)
    peak0 = pos.get("peak")
    if price <= pos["stop_px"]:
        reason = "be" if pos["stop_px"] >= pos["be_px"] * 0.999 else "stop"
        return [close(con, r, price, q[1], q[3] if len(q) > 3 else None, reason, now)]
    if age > STALE_S:
        return out
    ld = liq_drop(r, q, now, now - age)   # 16.11.: the pool pulled within the hour: out before the stop is gapped
    if ld:
        return [close(con, r, price, q[1], q[3] if len(q) > 3 else None, "likvidnost", now, why=ld)]
    had_half = bool(pos.get("half_px"))
    hit = rule.on_price(pos, price, "t", price, rc)
    if pos.get("half_px") and not had_half:
        out.append(half_sale(con, r, pos, price, q[1], now))
    elif pos.get("peak") != peak0:
        con.execute("UPDATE veliki_trades SET peak=? WHERE id=?", (pos.get("peak"), r["id"]))
        r["peak"] = pos.get("peak")
    if hit:
        why = (("cijeli profit: " if rc["full_tp"] else "") + bull_why) if hit[0] == "tp" else None
        return out + [close(con, r, price, q[1], q[3] if len(q) > 3 else None, hit[0], now, why=why)]
    if rule.OWNER_EXIT.get("time_h") and now - r["opened_ts"] >= (r.get("time_h") or cfg["time_h"]) * 3600:
        return out + [close(con, r, price, q[1], q[3] if len(q) > 3 else None,
                            "trail" if pos.get("peak") else "time", now)]   # 15.11. navečer: no time stop (vlasnik)
    if pos.get("be_armed") and pos["stop_px"] > r["stop_px"]:   # +5 % net: the stop moved to break-even
        con.execute("UPDATE veliki_trades SET stop_px=?, be_px=? WHERE id=?", (pos["stop_px"], pos["be_px"], r["id"]))
        con.commit()
        r["stop_px"] = pos["stop_px"]
        out.append(f"veliki{' PRAVI NOVAC' if r['user'] == _league_user() else ''} {r['symbol']}: +5 % neto, stop na "
                   f"ulaz (break-even {pos['stop_px']:.6g})")
    from league import copy as lcopy
    try:
        col = lcopy._rugged(r["token"], q[3], q[1])
    except Exception:  # noqa: BLE001
        col = None
    if col:
        out.append(close(con, r, price, q[1], q[3], "rug", now))
        return out
    ctx = context(r["token"], now)
    rs, tight = rule.reasoned_exit(pos, price, r["rt"], ctx, {**rc, "exit_slip": 0.0})
    if rs:
        return out + [close(con, r, price, q[1], q[3] if len(q) > 3 else None, rs, now, why=ctx_text(ctx))]
    if tight and tight > r["stop_px"]:
        con.execute("UPDATE veliki_trades SET stop_px=? WHERE id=?", (tight, r["id"]))
        con.commit()
        r["stop_px"] = tight
        out.append(f"veliki {r['symbol']}: stop pooštren na {tight:.6g} ({tight / pos['first'] - 1:+.0%} od prvog ulaza): "
                   f"{ctx_text(ctx)}")
    out += dca(con, r, q, pos, now, cfg, ctx)
    return out


# ---------- the context of the DCA and the reasoned exits (cached, read-only) ----------------------------------------

def _holderi_bad(tok, now):
    """The listing agent's newest deposit-to-sell signal of the token (holderi.db signals, read-only, if the table
    exists: a transfer of supply to an exchange where the token is already listed) within 24 h, else None."""
    hit = _ST.get("holderi")
    if not hit or now - hit[0] > 300:
        sig = {}
        try:
            import sqlite3
            path = os.environ.get("HOLDERI_DB") or (os.path.join(os.environ["DATA_DIR"], "holderi.db")
                                                    if os.environ.get("DATA_DIR") else
                                                    os.path.join(os.path.dirname(os.path.dirname(
                                                        os.path.abspath(__file__))), "holderi.db"))
            if os.path.exists(path):
                hc = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
                try:
                    for mint, kind, ex, ts in hc.execute(
                            "SELECT mint, kind, exchange, ts FROM signals WHERE ts >= ? ORDER BY ts", (int(now - 86400),)):
                        k = (kind or "").lower()
                        if "deposit" in k or "prodaj" in k or "sell" in k or "depozit" in k:
                            sig[mint] = f"prijenos na burzu {ex or '?'} (depozit za prodaju)"
                finally:
                    hc.close()
        except Exception:  # noqa: BLE001 - no listing data: no such reason
            sig = {}
        hit = _ST["holderi"] = (now, sig)
    return hit[1].get(tok)


def vol_ratio_live(tok, now):
    """24 h volume (the newest priority facts / the collector's member row) against the mean of the last 7 complete
    daily candles (midcap.db / veliki.db c1d), None unknown. Cached an hour a token."""
    c = _ST.setdefault("vr", {})
    hit = c.get(tok)
    if hit and now - hit[0] < 3600:
        return hit[1]
    v24 = None
    try:
        from veliki import prioritet
        v24 = ((prioritet.cached().get(tok) or {}).get("facts") or {}).get("vol24")
    except Exception:  # noqa: BLE001
        v24 = None
    vals = []
    try:
        from veliki import midcap, store
        for opener in (midcap.ro, store.ro):
            con = opener()
            if con is None:
                continue
            try:
                d0 = int(now) // 86400 * 86400
                vals = [r[0] for r in con.execute("SELECT v FROM c1d WHERE token=? AND ts < ? AND ts >= ? ORDER BY ts",
                                                  (tok, d0, d0 - 7 * 86400)).fetchall() if r[0]]
            except Exception:  # noqa: BLE001
                vals = []
            finally:
                con.close()
            if len(vals) >= 5:
                break
    except Exception:  # noqa: BLE001
        vals = []
    r = (v24 / (sum(vals) / len(vals))) if v24 and len(vals) >= 5 and sum(vals) > 0 else None
    c[tok] = (now, r)
    return r


def context(tok, now):
    """The DCA's and the reasoned exits' view of one token now: BTC's state, the macro regime, the category and
    metrics (veliki.db kv cats of the newest backtest run), the dip's reason (veliki/prioritet, read-only), a bad
    reason (prioritet "los" or the listing agent's deposit to sell), the volume ratio."""
    from veliki import store
    st = btc_state(now)
    try:
        from veliki import makro
        mac = makro.regime_now(now)
    except Exception:  # noqa: BLE001
        mac = None
    try:
        from veliki import prioritet
        pr = prioritet.cached().get(tok) or {}
    except Exception:  # noqa: BLE001
        pr = {}
    dip = pr.get("dip") or {}
    m = store.cats().get(tok) or {}
    # 15.11. navečer (vlasnik: "ako odmah nakon ulaza krene u mali loss, onda čekaš"): only NEW danger closes a position
    # (prioritet.dynamic_bad + a deposit to sell); the facts known at the entry never do
    try:
        from veliki import prioritet as _pr
        dyn = _pr.dynamic_bad(pr)
    except Exception:  # noqa: BLE001
        dyn = None
    bad = _holderi_bad(tok, now) or dyn
    return {"btc_state": st.get("state"), "macro": mac, "cat": m.get("cat"), "metrics": m, "dip_kind": dip.get("kind"),
            "bad": bad, "vol_ratio": vol_ratio_live(tok, now)}


def ctx_text(ctx):
    vr = ctx.get("vol_ratio")
    return (f"BTC {ctx.get('btc_state') or '?'}, makro {ctx.get('macro') or 'nepoznat'}, pad "
            f"{ctx.get('dip_kind') or '—'}" + (f", loš razlog: {ctx['bad']}" if ctx.get("bad") else "")
            + (f", volumen {vr:.0%} prosjeka 7 d" if vr is not None else ""))


def dca(con, r, q, pos, now, cfg, ctx):
    """The one DCA lot of an open position (rule.dca_level / rule.dca_refusal; the same lot size again, counted in the
    day's buys and loss): the average entry, the target and the break-even recomputed on it at the two lots' cost, the
    stop stays the FIRST entry's. [text]."""
    import json
    from league import store as lstore
    from veliki import intra, rule
    if not cfg.get("dca") and cfg.get("dca_mode") not in ("zona", "atr"):
        return []
    if (r.get("lots") or 1) >= 2 or r.get("half_px"):
        return []
    if (r.get("kind") or "") == "intra":
        # 16.11.: the intraday rule has no DCA (vlasnik: "ako odmah nakon ulaza krene u mali loss, onda čekaš"; a new
        # entry comes at the range's bottom after the exit). It used to inherit the 7-day rule's lot at -10 % while
        # its own stop is at most -12 %: a second 0.1 SOL two points above the stop.
        return []
    price, liq = q[0], q[1]
    try:
        zone = json.loads(r.get("zone") or "{}")
    except (TypeError, ValueError):
        zone = {}
    lvl = rule.dca_level(pos["first"], zone, cfg)
    if lvl is None or price > lvl or price <= r["stop_px"] * 1.02:
        return []
    user = r["user"]
    sol = _sol()
    cp = caps(user, ctx.get("btc_state"), r.get("kind"))
    rm = room(con, user, now, sol, cp, new_position=False)
    if not rm and user == _league_user():
        try:
            from veliki import gate
            rm = gate.real_refusal(now=now)
        except Exception as e:  # noqa: BLE001 - an unreadable gate is no real money
            rm = f"vrata nečitljiva ({type(e).__name__})"
    full = {**ctx, "lots": r.get("lots") or 1, "room": rm}
    why = rule.dca_refusal(full, cfg)
    if why:
        if now - _ST["said"].get(("dca", r["id"]), 0) > 3600:
            _ST["said"][("dca", r["id"])] = now
            return [f"veliki DCA {r['symbol']} odbijen ({why})"]
        return []
    lot_usd = r["size_usd"] / (r.get("lots") or 1)
    dwhy = rule.dca_why(ctx, cfg)
    try:
        tid = lstore.buy(con, user, r["token"], r["symbol"], lot_usd, price, liq,
                         f"veliki: DCA {r['symbol']} {lot_usd / sol:.2g} SOL ({dwhy})"[:200], None,
                         q[3] if len(q) > 3 else None, allow_open=True)
    except ValueError as e:
        return [f"veliki DCA {r['symbol']} nije prošao ({e})"]
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))
    avg = 2 / (1 / r["entry_px"] + 1 / price)
    c2 = rule.cost_at(lot_usd / sol, liq, sol, rule.fee_side_of(url=q[2] if len(q) > 2 else None), rule.tx_sol()[0],
                      lots=2)
    tp_cfg = intra.cfg_of() if r.get("kind") == "intra" else cfg
    tp = rule.tp_price(avg, tp_cfg["tp"], c2["rt"], zone, tp_cfg) if not isinstance(tp_cfg["tp"], str) else r["tp_px"]
    be = rule.be_price(avg, c2["rt"], {"exit_slip": 0.0})
    con.execute("UPDATE veliki_trades SET dca_trade_id=?, dca_px=?, dca_ts=?, dca_why=?, lots=2, entry_px=?, size_usd=?, "
                "size_sol=?, tp_px=?, be_px=?, rt=? WHERE id=?",
                (tid, price, int(now), dwhy[:300], avg, lot_usd * 2, (r.get("size_sol") or 0) * 2, tp, be, c2["rt"],
                 r["id"]))
    con.commit()
    r.update(dca_trade_id=tid, lots=2, entry_px=avg, size_usd=lot_usd * 2, tp_px=tp, be_px=be, rt=c2["rt"])
    head = "veliki PRAVI NOVAC: DCA" if user == _league_user() else "veliki DCA"
    return [f"{head} {r['symbol']} {lot_usd / sol:.2g} SOL na {price:.6g} ({price / pos['first'] - 1:+.0%} od prvog "
            f"ulaza), prosjek {avg:.6g}, novi TP {tp:.6g} ({tp / avg - 1:+.1%}), stop ostaje {r['stop_px']:.6g} "
            f"({r['stop_px'] / pos['first'] - 1:+.0%} od prvog ulaza); razlog: {dwhy}"]


def exit_why(r, price, age, now, mq, time_h):
    """(reason or None, new peak) without side effects (the card / old callers): the stop, the trailing of the
    rest, the target, the time stop, a rug; the half sale itself is manage()'s."""
    from veliki import rule
    pos = pos_of(r)
    if price <= pos["stop_px"]:
        return ("be" if pos.get("half_px") else "stop"), pos.get("peak")
    if age > STALE_S:
        return None, pos.get("peak")
    hit = rule.on_price(pos, price, "t", price, row_cfg(r))
    if hit:
        return hit[0], pos.get("peak")
    if now - r["opened_ts"] >= (r.get("time_h") or time_h) * 3600:
        return ("trail" if pos.get("peak") else "time"), pos.get("peak")
    if mq is not None:
        from league import copy as lcopy
        try:
            col = lcopy._rugged(r["token"], mq[3], mq[1])
        except Exception:  # noqa: BLE001
            col = None
        if col:
            return "rug", pos.get("peak")
    return None, pos.get("peak")


def close(con, r, price, liq, mcap, reason, now, why=None):
    from league import store as lstore
    from trade import settings
    from veliki import rule
    booked = 0.0
    seen = False
    rr = {"tp": "tp", "trail": "smart_trail", "be": "smart_trail", "stop": "sl", "time": "time",
          "rug": "rug"}.get(reason, "smart_other")
    for tid in (r["trade_id"], r.get("dca_trade_id")):
        if not tid:
            continue
        t = con.execute("SELECT status FROM trades WHERE id=?", (tid,)).fetchone()
        if t and t[0] == "open":
            seen = True
            booked += lstore.sell(con, r["user"], tid, price, liq, f"veliki: {rule.REASON_HR.get(reason, reason)}",
                                  mcap=mcap, exit_rule=rr) or 0.0
        elif t:
            seen = True
            row = con.execute("SELECT pnl_usd, exit_px FROM trades WHERE id=?", (tid,)).fetchone()
            booked += (row[0] or 0.0) if row else 0.0
            if tid == r["trade_id"] and row and row[1]:
                price = row[1]
    if not seen:
        reason = "nestalo"
    lots = r.get("lots") or 1
    pos = pos_of(r)
    tx = rule.tx_sol()[0] * _sol() / max(1e-9, (r["size_usd"] or 1) / lots)
    ret = rule.blend_ret(pos, price, r["rt"], {"tx_frac": tx, "exit_slip": 0.0}, lots)
    rd = rule.blend_ret(pos, price, r["drt"], {"tx_frac": tx, "exit_slip": 0.0}, lots)
    con.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, exit_px=?, reason=?, ret=?, pnl_usd=?, "
                "ret_demo=?, pnl_booked=?, exit_why=? WHERE id=?",
                (int(now), price, reason, ret, ret * r["size_usd"], rd, booked, why, r["id"]))
    if reason != "nestalo":   # 16.11.: the planned stop against this exit, and why they differ (trade/stopgap)
        from trade import stopgap
        q_ts = (_ST["q"].get(r["token"]) or (None, None))[1]
        stopgap.record(con, "veliki", r["id"], r["user"], r["token"], r["symbol"], r["entry_px"], r["stop_px"], price,
                       reason, now, trade_id=r["trade_id"], q_age_s=(now - q_ts) if q_ts else None,
                       q_gap_s=_win().gap(r["token"]), liq_ref=_win().ref(r["token"], now,
                                                                         extra=(r.get("opened_ts"), r.get("liq"))),
                       liq_exit=liq, rug=reason == "rug")
    con.commit()
    head = "veliki PRAVI NOVAC" if r["user"] == settings.LEAGUE_USER else "veliki"
    return (f"{head} {r['symbol']}: {rule.REASON_HR.get(reason, reason)}{' (' + why + ')' if why else ''}, "
            f"{ret * r['size_usd']:+.2f} $ pravim troškom ({ret:+.1%}"
            f"{', pola na cilju' if r.get('half_px') else ''}{', s DCA lotom' if lots > 1 else ''}), uz izmjerenu "
            f"naknadu {rd:+.1%}, knjiženo {booked or 0:+.2f} $")


def _list_tokens(now):
    from veliki import store
    lst = store.the_list() or {}
    if now - (lst.get("ts") or 0) > LIST_MAX_AGE_S:
        return []
    return [x["mint"] for x in lst.get("tokens") or [] if x.get("mint")]


def demo_tokens(now, path=None):
    """(mints, sources) of the DEMO universe (15.11. ~12:35 UTC): the veliki list first, then the midcap collector's
    members (veliki/midcap.py, midcap.db) with MC 2M-200M, liquidity and 24 h volume >= DEMO_MIN_LIQ / DEMO_MIN_VOL
    ($100k), a memecoin (universe.non_meme; the collector already keeps bonded AMM pools only and refuses the rug
    archive; live.guards asks again at the entry), the trending ones first, then by 24 h volume; at most
    DEMO_UNIV_MAX. Cached 5 min."""
    hit = _ST.get("univ")
    if hit and now - hit[0] < 300 and path is None:
        return list(hit[1]), dict(hit[2])
    lst = _list_tokens(now)
    out, seen = list(lst), set(lst)
    mids = []
    try:
        from veliki import midcap, universe
        for r in midcap.members(path):
            m = r.get("mint")
            if not m or m in seen:
                continue
            if not (universe.DATA_MIN_MCAP <= (r.get("mcap") or 0) <= universe.DATA_MAX_MCAP):
                continue
            if (r.get("liq") or 0) < DEMO_MIN_LIQ or (r.get("vol24") or 0) < DEMO_MIN_VOL:
                continue
            if universe.non_meme(r.get("symbol")):
                continue
            mids.append(r)
    except Exception:  # noqa: BLE001 - no collector: the list alone
        mids = []
    mids.sort(key=lambda r: (0 if r.get("trend") is not None else 1, -(r.get("vol24") or 0)))
    mids = mids[:max(0, DEMO_UNIV_MAX - len(out))]
    out += [r["mint"] for r in mids]
    src = {"veliki lista": len(lst), "midcap sakupljač": len(mids),
           "od toga trending": sum(1 for r in mids if r.get("trend") is not None)}
    if path is None:
        _ST["univ"] = (now, list(out), dict(src))
    return out, src


def _mid(now, path=None):
    """midcap.db read-only, re-read every MID_RELOAD_S: GeckoTerminal's 15m / 1h candles of the last LOOK_H + 2 h and
    the collector's 90-s DexScreener snapshots folded into 15m bars (incrementally)."""
    from veliki import intra
    m = _ST.setdefault("mid", {"ts": 0.0, "c15": {}, "c1h": {}, "snap": {}, "snap_ts": 0})
    if now - m["ts"] < MID_RELOAD_S:
        return m
    m["ts"] = now
    try:
        from veliki import midcap
        con = midcap.ro(path)
    except Exception:  # noqa: BLE001
        con = None
    if con is None:
        return m
    import sqlite3
    since = int(now - (intra.LOOK_H + 2) * 3600)
    try:
        for tbl in ("c15", "c1h"):
            d = {}
            for tok, ts, o, h, lo, c, v in con.execute(f"SELECT token, ts, o, h, l, c, v FROM {tbl} WHERE ts >= ?",
                                                       (since,)):
                d.setdefault(tok, {})[int(ts)] = (int(ts), o, h, lo, c, v or 0.0)
            m[tbl] = d
        ids = {i: mint for mint, i in con.execute("SELECT mint, id FROM tokens")}
        last = max(int(m["snap_ts"] or 0), since)
        sn = m["snap"]
        for i, ts, px in con.execute("SELECT id, ts, px FROM snap WHERE ts > ? AND px > 0 ORDER BY ts", (last,)):
            mint = ids.get(i)
            if not mint:
                continue
            b = int(ts) - int(ts) % M15
            x = sn.setdefault(mint, {}).get(b)
            if x is None:
                sn[mint][b] = [b, px, px, px, px]
            else:
                x[2], x[3], x[4] = max(x[2], px), min(x[3], px), px
            last = max(last, int(ts))
        m["snap_ts"] = last
        for d in sn.values():
            for k in [k for k in d if k < since]:
                del d[k]
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return m


def bars_intra(tok, now):
    """(completed 15m bars, completed 1h candles) of the intraday rule: 15m = GeckoTerminal's (midcap.db c15), else
    this module's own quotes, else the collector's snapshots; 1h = midcap.db / veliki.db 1h, every hour with 15m bars
    rebuilt from them (rule.h1_from_15m)."""
    from veliki import intra, rule
    m = _mid(now)
    cur = int(now) - int(now) % M15
    since = now - (intra.LOOK_H + 2) * 3600
    by = {}
    for b in (m["snap"].get(tok) or {}).values():
        by[b[0]] = (b[0], b[1], b[2], b[3], b[4], 0.0)
    for b in _LIVE.get(tok) or []:
        if b[0] >= since:
            by[b[0]] = (b[0], b[1], b[2], b[3], b[4], 0.0)
    by.update(m["c15"].get(tok) or {})
    b15 = [by[k] for k in sorted(by) if since <= k < cur]
    h1 = dict((m["c1h"].get(tok) or {}))
    for c in _gt(tok, now)[1]:
        if c[0] >= since:
            h1.setdefault(int(c[0]), tuple(c[:6]))
    hh = rule.h1_from_15m(b15, [h1[k] for k in sorted(h1)])
    return b15, [c for c in hh if c[0] + 3600 <= now]


def report_line(con, now):
    """The hour's report (15.11., coordinator: "veliki demo: otvoreno X, zatvoreno Y (dobit Z, gubitak W), pravi:
    ..."): since the Zagreb day's start per account: opened, open now, closed with the sum of the wins and of the losses
    (real cost), how many closed at +10 % or more, by rule."""
    from trade import settings
    d0 = _day_start(now)
    parts = []
    for user, name in ((settings.PAPER_USER, "veliki demo"), (settings.LEAGUE_USER, "pravi")):
        n_o = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND opened_ts>=?", (user, d0)).fetchone()[0]
        n_open = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
        rows = con.execute("SELECT pnl_usd, ret, COALESCE(kind, 'range') FROM veliki_trades WHERE user=? AND "
                           "status='closed' AND closed_ts>=?", (user, d0)).fetchall()
        win = sum(r[0] for r in rows if (r[0] or 0) > 0)
        loss = sum(r[0] for r in rows if (r[0] or 0) < 0)
        ten = sum(1 for r in rows if (r[1] or 0) >= 0.10)
        kinds = {}
        for r in rows:
            kinds[r[2]] = kinds.get(r[2], 0) + 1
        half = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND half_ts>=?", (user, d0)).fetchone()[0]
        dca = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND dca_ts>=?", (user, d0)).fetchone()[0]
        parts.append(f"{name}: otvoreno {n_o} danas ({n_open} sada otvorenih), zatvoreno {len(rows)} (dobit "
                     f"{win:+.2f} $, gubitak {loss:+.2f} $, neto {win + loss:+.2f} $; ≥ +10 %: {ten}; dnevni raspon "
                     f"{kinds.get('intra', 0)}, raspon 7 d {kinds.get('range', 0)}), pola na cilju {half}, DCA {dca}"
                     + (chain_line(con, user, d0) if user == settings.LEAGUE_USER else ""))
    return "; ".join(parts)


def chain_line(con, user, d0, path=None):
    """15.11. popodne: what the real account's midcap buys did ON CHAIN today (trade.db positions joined by league_id
    to today's veliki trades of the real account): a veliki "pravi" trade whose buy the executor refused (ukHH6c at
    12:48: the day's spend cap) stays a league row, so the report says how many were really bought and how many were
    refused. "" when trade.db is unreadable or there was no real midcap trade today."""
    import sqlite3
    ids = [r[0] for r in con.execute("SELECT trade_id FROM veliki_trades WHERE user=? AND opened_ts>=? AND trade_id "
                                     "IS NOT NULL", (user, d0)).fetchall()]
    if not ids:
        return ""
    try:
        from trade import settings as tsettings
        db = path or tsettings.DB
        tc = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            q = ",".join("?" * len(ids))
            st = {lid: s_ for lid, s_ in tc.execute(f"SELECT league_id, status FROM positions WHERE mode='live' AND "
                                                    f"league_id IN ({q}) ORDER BY id", ids).fetchall()}
        finally:
            tc.close()
    except Exception:  # noqa: BLE001 - trade.db unreadable: no chain part
        return ""
    bought = sum(1 for v in st.values() if v in ("open", "closed", "pending"))
    refused = sum(1 for v in st.values() if v in ("blocked", "failed"))
    return f"; na lancu danas: kupljeno {bought}, odbijeno {refused}"


_NUM = re.compile(r"[-+]?\d[\d.,]*")


def _refused(why):
    """Count a refused candidate by its rule (the hour's line: which rule refuses how many)."""
    k = _NUM.sub("N", (why or "?").split(" (")[0])[:70]   # 16.11.: the whole reason (numbers folded), not its prefix
    r = _ST.setdefault("ref", {})
    r[k] = r.get(k, 0) + 1


def refusal_line():
    r = _ST.get("ref") or {}
    _ST["ref"] = {}
    top = sorted(r.items(), key=lambda kv: -kv[1])[:12]
    return "veliki odbijeni kandidati zadnji sat: " + ("; ".join(f"{k} {v}" for k, v in top) or "nijedan")


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


# 15.11. navečer (vlasnik o swarms, kupljenom pravim novcem u 15:30 dnevnim pravilom: "čini mi se ok. Samo treba duže
# držati poziciju. Jer mislim da na prvi znak da Bitcoin ide gore, da će i svi meme coinovi krenuli prema gore"): once,
# the open swarms trades (real and demo) get a 72 h time stop instead of 24 h; the stop and the half target stay
OWNER_ONCE = (("swarms_72h_1511", "74SBV4", 72.0),)


def owner_once(con, now=None):
    """Apply each OWNER_ONCE step once (league.db kv veliki_once:<key>): the open trades of that token prefix get the
    new time stop. [text]."""
    out = []
    try:
        con.execute("CREATE TABLE IF NOT EXISTS veliki_once (k TEXT PRIMARY KEY, ts INTEGER, n INTEGER)")
        for key, prefix, hours in OWNER_ONCE:
            if con.execute("SELECT 1 FROM veliki_once WHERE k=?", (key,)).fetchone():
                continue
            n = con.execute("UPDATE veliki_trades SET time_h=? WHERE status='open' AND token LIKE ?",
                            (float(hours), prefix + "%")).rowcount
            con.execute("INSERT INTO veliki_once VALUES (?,?,?)", (key, int(now or time.time()), n))
            con.commit()
            out.append(f"veliki: nalog vlasnika {key}: vremenski stop {hours:g} h za {n} otvorenih tradeova {prefix}…")
            print(out[-1], flush=True)
    except Exception as e:  # noqa: BLE001 - never stops the tick
        print(f"veliki: nalog vlasnika nije primijenjen ({type(e).__name__})", flush=True)
    return out


def tick(con, market_fn, now=None, force=False, toks=None):
    """One pass: exits of the open trades, then the entries: the 7-day rule after an hour completed (the veliki
    list), the intraday rule after a 15m bar completed (the demo universe). [text]."""
    now = now or time.time()
    if not force and now - _ST["tick"] < TICK_S:
        return []
    _ST["tick"] = now
    m = mode()
    ensure(con)
    owner_once(con, now)
    opened = open_rows(con)
    if m not in ("paper", "live") and not opened:
        return []
    from trade import settings
    from veliki import intra, rule
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
    lset = set(lst)
    univ, usrc = (demo_tokens(now) if toks is None else (list(toks), {"zadano": len(toks)})) if users else ([], {})
    hour = int(now) - int(now) % 3600
    if users and _ST.get("univ_said") != hour:
        _ST["univ_said"] = hour
        out.append(f"veliki demo lista: {len(univ)} tokena (izvori: " + ", ".join(f"{k} {v}" for k, v in usrc.items())
                   + ")")
    poll_all = now - _ST.get("univ_q", 0) >= UNIV_EVERY_S
    if poll_all:
        _ST["univ_q"] = now
    all_t = sorted((set(lst) | set(univ) if users and poll_all else set()) | {r["token"] for r in opened})
    if not all_t:
        return out
    mk = market_fn(all_t) or {}
    open_t = {r["token"] for r in opened}
    for tok in all_t:
        q = mk.get(tok)
        if q and q[0]:
            add_price(con, tok, q[0], now)
            _ST["q"][tok] = (q, now)
            if tok in open_t:   # 16.11.: the open positions' liquidity of the last hour (liq_drop, stop gaps)
                _win().note(tok, now, q[1] if len(q) > 1 else None)
    con.commit()
    cfg = cfg_now()
    if cfg.get("default") and now - _ST.get("default_said", 0) >= 3600:
        _ST["default_said"] = now
        out.append("veliki: zadano pravilo (backtest još nema podataka): zona zadnjih 7 d, TP +8 % neto pa pola + "
                   "break-even + trailing 5 %, stop −20 %, vremenski stop 3 d")
    for r in opened:
        q, ts = _ST["q"].get(r["token"], (None, 0))
        if not q:
            continue
        out += manage(con, r, q, now - ts, now, cfg)
    con.commit()
    if users and _ST.get("rep_h") != hour:
        if _ST.get("rep_h") is not None:
            out.append(report_line(con, now))
            out.append(refusal_line())
        _ST["rep_h"] = hour
    if not users or not poll_all:
        return out
    btc = btc_state(now)
    if _ST.get("btc_said") != btc["state"]:
        _ST["btc_said"] = btc["state"]
        out.append(f"veliki BTC: {btc['state'].replace('_', ' ')} — {btc['why']}")
    try:
        from veliki import makro
        snap = makro.current(now)
    except Exception:  # noqa: BLE001
        snap = None
    mac = (snap or {}).get("regime")
    _ST["macro"] = mac
    try:   # 16.11. ("oporavak": BTC holds its bottom + the platforms' volume comes back; veliki/makro.recovery)
        rec = makro.is_recovery(snap)
        _ST["makro_tag"] = makro.tag(snap, makro.mood_now(now))
        rec_why = ((snap or {}).get("oporavak") or {}).get("why")
    except Exception:  # noqa: BLE001 - no label: the old behaviour
        rec, rec_why = False, None
        _ST["makro_tag"] = mac
    _ST["oporavak"] = rec
    if _ST.get("oporavak_said") != rec:
        _ST["oporavak_said"] = rec
        if rec:
            out.append(f"veliki oporavak: DA — {rec_why}; kandidati redom po odzivu na rast BTC-a, ulaz i dalje samo "
                       "na dnu raspona, demo stropovi x1,5, pravi stropovi isti")
        elif rec_why:
            out.append(f"veliki oporavak: ne — {rec_why}")
    if _ST.get("macro_said") != mac:
        _ST["macro_said"] = mac
        out.append(f"veliki makro režim: {mac or 'nepoznat (neutralno)'}"
                   + (f" — {snap.get('why')}" if snap else "") + ("; bez novih ulaza i bez DCA" if mac == "risk_off"
                                                                 else "; demo stropovi x1,5" if mac == "risk_on" else ""))
    if mac == "risk_off":
        _refused("makro risk-off: bez novih ulaza")
        return out
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
        univ = prioritet.order(univ, pr)
        real_rank = {t: k for k, t in enumerate(prioritet.order(lst, pr, real=True))}
        if rec:   # 16.11.: while the recovery holds, the tokens that answer BTC's upticks first (both accounts)
            from veliki import odziv
            lst, univ = odziv.order(lst, pr), odziv.order(univ, pr)
            real_rank = {t: k for k, t in enumerate(odziv.order(sorted(real_rank, key=real_rank.get), pr))}
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
        blk = (pr.get(tok) or {}).get("block") or (pr.get(tok) or {}).get("risk")
        if blk:   # 15.11. (holderi/ + prioritet.static_risk): concentration / dev / authority / team selling: no entry
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
        last = con.execute("SELECT MAX(closed_ts) FROM veliki_trades WHERE token=? AND COALESCE(kind, 'range')<>'intra'",
                           (tok,)).fetchone()[0]
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
            if user != settings.PAPER_USER:   # 15.11. (holderi/): real entries after the loop, own order (no listing bonus)
                deferred.append((real_rank.get(tok, len(real_rank)), tok, user, q, zone, regime, bars, i, link))
                continue
            if _makroinf_blocks(now, out):   # 15.11. (makroinf/, flag makroinf_indeks): a DEMO input only
                continue
            link = _try_enter(con, out, held, user, tok, q, now, sol, zone, cfg, regime, btc, link, bars, i, tx,
                              prioritet, pr) or link
    for _k, tok, user, q, zone, regime, bars, i, link in sorted(deferred, key=lambda x: x[0]):
        _try_enter(con, out, held, user, tok, q, now, sol, zone, cfg, regime, btc, link, bars, i, tx, prioritet, pr)
    out += intra_entries(con, univ, lset, mk, users, held, btc, now, pr, prioritet)
    if int(now) % 3600 < TICK_S:
        con.execute("DELETE FROM veliki_bars WHERE ts < ?", (int(now - 10 * 86400),))
        con.commit()
    return out


def _makroinf_blocks(now, out):
    """True when the DEMO account must skip a new 7-day-rule entry because of makroinf's index (flag makroinf_indeks
    paper, the input active, the index of the most accurate accounts bearish beyond its threshold: veliki/makro.
    demo_regime). Shadow only logs "bi preskočio". Once an hour a line; never raises; never asked for the real account."""
    try:
        from veliki import makro
        blocks, why, mode = makro.demo_index(now)
    except Exception:  # noqa: BLE001 - unreadable: no effect
        return False
    if not blocks:
        return False
    hour = int(now) // 3600
    if _ST.get("mi_said") != hour:
        _ST["mi_said"] = hour
        out.append(f"veliki demo: {'bez novih ulaza' if mode == 'paper' else 'sjena, demo bi preskočio ulaze'} — {why}")
    if mode != "paper":
        return False
    _refused("makro influenceri: indeks najtočnijih medvjeđi")
    return True


def _try_enter(con, out, held, user, tok, q, now, sol, zone, cfg, regime, btc, link, bars, i, tx, prioritet, pr):
    """One user's entry on one token when the 7 d rule signals (the cost at its size). The new trade id or None."""
    from veliki import rule
    cp = caps(user, btc["state"])
    c = rule.cost_at(cp["size_sol"], q[1], sol, rule.fee_side_of(url=q[2] if len(q) > 2 else None), tx)
    why = rule.signal(bars, i, zone, c["rt"], cfg, btc["crash_obj"])
    if why is not None:
        _refused("7 d: " + why)
        return None
    text, no, vid = enter(con, user, tok, q, now, sol, zone, cfg, regime, btc, link,
                          meta=prioritet.meta(tok, pr) if prioritet else None)
    if text:
        out.append(text)
        held.add((user, tok))
    elif no and now - _ST["said"].get((user, tok), 0) > 3600:
        _ST["said"][(user, tok)] = now
        out.append(f"veliki {(q[4] if len(q) > 4 else None) or tok[:6]}: signal bez ulaza ({no})")
    return vid


def intra_entries(con, univ, lset, mk, users, held, btc, now, pr, prioritet=None):
    """The intraday rule's entries (veliki/intra.py) at the first pass after a 15m bar completed: the demo on the whole
    universe, the real account only on the veliki list's tokens (age >= 15 d; MC 5-150M and liquidity >= $500k in
    enter); one position a token, cooldown intra.COOLDOWN_S after an exit, at most intra.MAX_ROUNDS rounds a token a
    Zagreb day. [text]."""
    from trade import settings
    from veliki import intra
    out = []
    m15 = int(now) - int(now) % M15
    icfg = intra.cfg_of()
    d0 = _day_start(now)
    sol = _sol()
    for tok in univ:
        if _ST.setdefault("bar15", {}).get(tok) == m15:
            continue
        q = mk.get(tok)
        if not q or not q[0]:
            continue
        _ST["bar15"][tok] = m15
        dip = (pr.get(tok) or {}).get("dip") or {}
        if dip.get("kind") == "los":
            _refused("dnevni: pad iz lošeg razloga")
            continue
        if (pr.get(tok) or {}).get("block"):   # 15.11. (holderi/): insiders / the team selling: no entry
            _refused("dnevni: oprez (holderi)")
            continue
        if (pr.get(tok) or {}).get("risk"):   # 15.11. popodne (prioritet.static_risk): known before the buy
            _refused("dnevni: oprez (koncentracija / dev / ovlasti)")
            continue
        b15, h1 = bars_intra(tok, now)
        z = intra.zone(h1, m15, icfg)
        why = intra.signal(q[0], z, b15, icfg, btc["state"])
        if why:
            _refused("dnevni: " + why)
            continue
        last = con.execute("SELECT MAX(closed_ts) FROM veliki_trades WHERE token=?", (tok,)).fetchone()[0]
        if last and now - last < intra.COOLDOWN_S:
            _refused("dnevni: pauza 30 min nakon izlaza")
            continue
        link = None
        for user in users:
            if (user, tok) in held:
                continue
            if user == settings.LEAGUE_USER and tok not in lset:
                _refused("dnevni pravi: samo tokeni velike liste (starost >= 15 d)")
                continue
            n_r = con.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND token=? AND kind='intra' AND "
                              "opened_ts>=?", (user, tok, d0)).fetchone()[0]
            if n_r >= intra.MAX_ROUNDS:
                _refused(f"dnevni: {intra.MAX_ROUNDS} runde tokena danas")
                continue
            text, no, vid = enter(con, user, tok, q, now, sol, z, icfg, _regime(now), btc, link,
                                  meta=prioritet.meta(tok, pr) if prioritet else None, kind="intra")
            link = link or vid
            if text:
                out.append(text)
                held.add((user, tok))
            elif no:
                _refused("dnevni ulaz: " + no)
                if now - _ST["said"].get((user, tok, "i"), 0) > 3600:
                    _ST["said"][(user, tok, "i")] = now
                    out.append(f"veliki {(q[4] if len(q) > 4 else None) or tok[:6]}: dnevni signal bez ulaza ({no})")
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
