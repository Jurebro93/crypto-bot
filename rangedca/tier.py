"""Adaptive stake per token for range_dca (11.11., Jure: "adaptivni ulog po tokenu (token_tier)").

PAPER ONLY until the backtest (rangedca/backtest.py, tier comparison) and 20 paper rounds confirm it: the stake of
a tier is used only on the demo account PAPER_USER and only while RANGE_TIER=paper (default). The real account
LEAGUE_USER keeps the fixed size_sol whatever its tier says (its tier is still kept and shown, so the two can be
compared). Grok never trades through this (ui/grokauto keeps its own 0.1 SOL limits); get_range_candidates shows
grok_size_sol = min(size_sol, grok_max_sol_per_trade) next to it.

Tiers (RANGE_TIER_SIZES, SOL per lot): T0 0.15 (base), T1 0.2, T2 0.25, T3 0.3. The trader's T0 is the base stake
of trade settings (size_sol) and no tier is ever under it, so the demo account's T0 round is the same as before.

Up one tier (max T3) after a closed PROFITABLE round, only when ALL of these hold at the close:
  - higher lows: the round's low > the previous round's low (last_bottom > prev_bottom, market cap);
  - the median hourly volume of the last 6 h >= 10k $ and the transactions of the last hour not down more than 30 %
    from the hourly average of 24 h (unique traders are not in our data; DexScreener gives transactions);
  - range_score >= 0.7 and rug clean (no collapse, no exclusion of the token);
  - at least 3 profitable rounds on the token in total.
Down to T0 at once, with a cooldown of 1 round (no step up after the next round): one losing round, a hard stop,
a give-up (the range broken down / excluded) or the range broken down at the close, or lower highs twice in a row
(each round's high under the previous round's high).
A round that ends at zero (time stop at break-even) moves nothing.

No "house money": the stake grows only from the conditions above, never from realized_pnl_sol, which is only shown.

Size of a lot: min(tier stake, 1.5 % of the pool's liquidity in SOL), then smaller while the simulated price impact
of the buy (league/store.impact, the demo account's AMM model) is over 2 %. The lot 1 + lot 2 cap per token
(dca_token_cap) scales with the stake on the demo account (cap * stake / T0), so a T3 round still has room for lot 2.

Table token_tier in league.db (one row per account and token), written by the 1-second exit loop at a round's close.
"""
import os
import statistics
import time

SIZES_DEFAULT = (0.15, 0.2, 0.25, 0.3)
UP = {"vol_h1_med6_min": 10_000.0, "tx_drop_max": 0.30, "score_min": 0.7, "wins_min": 3}
LIQ_SHARE = 0.015
SLIP_MAX = 0.02
MAX_TIER = 3

SCHEMA = """CREATE TABLE IF NOT EXISTS token_tier (
    user TEXT, mint TEXT, tier INTEGER DEFAULT 0, wins_streak INTEGER DEFAULT 0, rounds INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0, realized_pnl_sol REAL DEFAULT 0, last_bottom REAL, prev_bottom REAL, last_top REAL,
    prev_top REAL, lower_highs INTEGER DEFAULT 0, cooldown INTEGER DEFAULT 0, reason TEXT, updated_at INTEGER,
    PRIMARY KEY (user, mint));"""
COLS = ("tier", "wins_streak", "rounds", "wins", "realized_pnl_sol", "last_bottom", "prev_bottom", "last_top",
        "prev_top", "lower_highs", "cooldown", "reason", "updated_at")


def sizes(env=None):
    """The stake of T0..T3 in SOL (RANGE_TIER_SIZES "0.15,0.2,0.25,0.3"); a bad value falls back to the default."""
    raw = (env if env is not None else os.environ.get("RANGE_TIER_SIZES", "")).strip()
    if raw:
        try:
            xs = tuple(float(x) for x in raw.split(","))
            if len(xs) == 4 and all(x > 0 for x in xs) and list(xs) == sorted(xs):
                return xs
        except ValueError:
            pass
    return SIZES_DEFAULT


def mode():
    """paper (default): the tier stake on the demo account only; off: everybody keeps size_sol."""
    return "off" if os.environ.get("RANGE_TIER", "paper").strip().lower() == "off" else "paper"


def applies(user):
    """Does this account trade with the tier stake? Only the demo account, and only in mode paper."""
    from trade import settings as ts
    return mode() == "paper" and user == ts.PAPER_USER


def blank():
    return {"tier": 0, "wins_streak": 0, "rounds": 0, "wins": 0, "realized_pnl_sol": 0.0, "last_bottom": None,
            "prev_bottom": None, "last_top": None, "prev_top": None, "lower_highs": 0, "cooldown": 0,
            "reason": "početni ulog", "updated_at": None}


def _k(x):
    """Market cap the short way: 95000 -> 95k, 1250000 -> 1.25M."""
    if x is None:
        return "?"
    if x >= 1e6:
        return f"{x / 1e6:.2f}M".replace(".00M", "M")
    return f"{x / 1e3:.0f}k"


# ---------- the market numbers the step up asks for (pure, also the backtest's) ---------------------------------------
def activity(candles, now):
    """From minute candles [(ts, o, h, l, c, v, buys, sells)]: vol_h1_med6 (median of the 6 hourly volume sums of the
    last 6 h), tx_h1 (transactions of the last hour) and tx_h1_avg24 (hourly average of the last 24 h, over the hours
    the series covers). Transactions are None where the candles have no counts (GeckoTerminal history)."""
    now = int(now)
    hours = [0.0] * 6
    for c in candles:
        age = now - c[0]
        if 0 <= age < 6 * 3600:
            hours[int(age // 3600)] += float(c[5] or 0)
    cs24 = [c for c in candles if 0 <= now - c[0] < 24 * 3600]
    first = min((c[0] for c in cs24), default=now)
    span_h = max(1.0, min(24.0, (now - first) / 3600))
    tx = [c for c in cs24 if len(c) > 7 and c[6] is not None and c[7] is not None]
    tx1 = sum(c[6] + c[7] for c in tx if now - c[0] < 3600) if tx else None
    tx24 = (sum(c[6] + c[7] for c in tx) / span_h) if tx else None
    return {"vol_h1_med6": statistics.median(hours) if candles else None, "tx_h1": tx1, "tx_h1_avg24": tx24}


def up_checks(st, ctx, cfg=None):
    """[(ok, text)] of the step-up conditions; st: the tier state AFTER this round was counted."""
    c = {**UP, **(cfg or {})}
    act = (ctx or {}).get("activity") or {}
    lb, pb = st.get("last_bottom"), st.get("prev_bottom")
    v6 = act.get("vol_h1_med6")
    t1, t24 = act.get("tx_h1"), act.get("tx_h1_avg24")
    sc = (ctx or {}).get("score")
    out = [(lb is not None and pb is not None and lb > pb, f"higher lows {_k(pb)}→{_k(lb)}"),
           (v6 is not None and v6 >= c["vol_h1_med6_min"], f"volumen 1 h medijan 6 h {v6 or 0:,.0f} $"),
           (t1 is not None and t24 and t1 >= (1 - c["tx_drop_max"]) * t24,
            f"transakcije 1 h {t1 if t1 is not None else '?'} vs prosjek 24 h {t24 or 0:.0f}"),
           (sc is not None and sc >= c["score_min"] - 1e-9, f"range_score {sc if sc is not None else '?'}"),
           (bool((ctx or {}).get("rug_clean")), "rug čist"),
           (st.get("wins", 0) >= c["wins_min"], f"{st.get('wins', 0)} profitabilne runde")]
    return out


def step(state, rnd, ctx, cfg=None):
    """The tier after one closed round (pure; the trader and the backtest use it). state: the token's row (or None);
    rnd: {pnl_sol, reason, low_mc, high_mc}; ctx: {score, rug_clean, broken_down, activity}. Returns the new state
    with "reason" (shown) and "moved" (+1, 0, -n)."""
    s = dict(blank(), **{k: v for k, v in (state or {}).items() if k in COLS and v is not None})
    old = s["tier"]
    pnl = float(rnd.get("pnl_sol") or 0)
    s["rounds"] += 1
    s["realized_pnl_sol"] = round(s["realized_pnl_sol"] + pnl, 6)
    if rnd.get("low_mc"):
        s["prev_bottom"], s["last_bottom"] = s["last_bottom"], rnd["low_mc"]
    hi = rnd.get("high_mc")
    if hi:
        if s["last_top"] and hi < s["last_top"]:
            s["lower_highs"] += 1
        else:
            s["lower_highs"] = 0
        s["prev_top"], s["last_top"] = s["last_top"], hi
    win = pnl > 0
    if win:
        s["wins"] += 1
        s["wins_streak"] += 1
    elif pnl < 0:
        s["wins_streak"] = 0
    why = (rnd.get("reason") or "").split(":")[0]
    down = None
    if pnl < 0:
        down = "gubitak u rundi"
    elif why == "stop":
        down = "tvrdi stop"
    elif why == "odustajanje" or (ctx or {}).get("broken_down"):
        down = "probijeno dno zone"
    elif s["lower_highs"] >= 2:
        down = "lower highs 2× zaredom"
    if down:
        s.update(tier=0, cooldown=1, wins_streak=0 if pnl < 0 else s["wins_streak"],
                 reason=f"pad na T0: {down} (pauza 1 runda)")
    elif not win:
        s["reason"] = "runda na nuli: ulog ostaje"
    elif s["cooldown"] > 0:
        s["cooldown"] -= 1
        s["reason"] = "pauza 1 runda nakon pada: bez penjanja"
    else:
        checks = up_checks(s, ctx, cfg)
        miss = [t for ok, t in checks if not ok]
        if s["tier"] >= MAX_TIER:
            s["reason"] = f"T3 (najviši): {s['wins']} runde +"
        elif miss:
            s["reason"] = f"ostaje T{s['tier']}: nije ispunjeno {miss[0]}"
        else:
            s["tier"] += 1
            s["reason"] = f"{s['wins']} runde +, higher lows {_k(s['prev_bottom'])}→{_k(s['last_bottom'])}"
    s["moved"] = s["tier"] - old
    return s


def ladder(base=None, szs=None):
    """The stakes T0..T3: RANGE_TIER_SIZES, with T0 = base (size_sol) when given and no tier under it."""
    szs = tuple(szs or sizes())
    if base:
        szs = (float(base),) + tuple(max(float(base), x) for x in szs[1:])
    return szs


def size(tier, liq_usd, sol_usd, szs=None, impact=None, base=None):
    """(SOL of a lot, note): the tier stake, at most 1.5 % of the pool's liquidity in SOL, smaller while the
    simulated impact (impact(usd, liq) -> fraction) is over 2 %."""
    szs = ladder(base, szs)
    s = szs[max(0, min(MAX_TIER, int(tier or 0)))]
    note = None
    if liq_usd and sol_usd:
        cap = LIQ_SHARE * liq_usd / sol_usd
        if cap < s:
            s, note = cap, f"1,5 % likvidnosti ({cap:.3f} SOL)"
    if impact and liq_usd and sol_usd:
        n = 0
        while s > 0 and impact(s * sol_usd, liq_usd) > SLIP_MAX and n < 40:
            s *= 0.9
            n += 1
        if n:
            note = f"slippage > 2 %: smanjeno na {s:.3f} SOL"
    return round(s, 4), note


def label(st, size_sol=None, base=None):
    """ "Tier T2 · ulog 0.25 · razlog: 4 runde +, higher lows 95k→103k" """
    st = st or blank()
    szs = ladder(base)
    s = size_sol if size_sol is not None else szs[st.get("tier") or 0]
    return f"Tier T{st.get('tier') or 0} · ulog {s:g} · razlog: {st.get('reason') or 'početni ulog'}"


# ---------- league.db ---------------------------------------------------------------------------------------------
def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='token_tier'").fetchone() is None:
        con.executescript(SCHEMA)


def get(con, user, mint):
    """The row as a dict (blank() when the token has none or the table does not exist yet)."""
    try:
        r = con.execute(f"SELECT {', '.join(COLS)} FROM token_tier WHERE user=? AND mint=?", (user, mint)).fetchone()
    except Exception:  # noqa: BLE001 - a read-only connection before the table exists
        r = None
    return dict(zip(COLS, r)) if r else blank()


def all_for(con, mints=None):
    """{(user, mint): row} of these tokens (all when None); {} without the table."""
    try:
        sql, args = f"SELECT user, mint, {', '.join(COLS)} FROM token_tier", []
        if mints:
            sql += f" WHERE mint IN ({','.join('?' * len(mints))})"
            args = list(mints)
        return {(r[0], r[1]): dict(zip(COLS, r[2:])) for r in con.execute(sql, args)}
    except Exception:  # noqa: BLE001
        return {}


def save(con, user, mint, st, now=None):
    ensure(con)
    st = dict(st, updated_at=int(now or time.time()))
    con.execute(f"INSERT OR REPLACE INTO token_tier (user, mint, {', '.join(COLS)}) VALUES (?,?,{','.join('?' * len(COLS))})",
                (user, mint, *[st.get(k) for k in COLS]))


def on_close(con, r, pnl_usd, sol_usd, rng, now=None, rug_fn=None):
    """Count a closed range round (trade.exits_once calls this right after the round's PnL is known). r: the round
    row (user, token, state with lo / hi prices, levels with supply); rng: the token's range now (or None)."""
    lv, st = r.get("levels") or {}, r.get("state") or {}
    sup = lv.get("supply")
    rnd = {"pnl_sol": (pnl_usd or 0) / sol_usd if sol_usd else 0.0, "reason": r.get("exit_reason") or st.get("last") or "",
           "low_mc": st["lo"] * sup if sup and st.get("lo") else None,
           "high_mc": st["hi"] * sup if sup and st.get("hi") else None}
    rng = rng or {}
    rst = rng.get("state") or {}
    excluded = (rst.get("excluded_until") or 0) > (now or time.time())
    rug = None
    if rug_fn:
        try:
            rug = rug_fn(r["token"])
        except Exception:  # noqa: BLE001
            rug = "nepoznato"
    ctx = {"score": rng.get("score"), "broken_down": bool((rng.get("signals") or {}).get("broken_down")),
           "rug_clean": bool(rng) and not excluded and not rug,
           "activity": (rng.get("metrics") or {}).get("activity")}
    new = step(get(con, r["user"], r["token"]), rnd, ctx)
    save(con, r["user"], r["token"], new, now)
    return new
