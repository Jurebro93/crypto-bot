"""The entries we would have taken, per source, with the price path after each (read-only on every database, no API
call, no cost): izlazi/learn replays the exit grid over them.

SOURCES (kind, id) and their entries (one per source and token: the first, as kol/minute and kol/zadnjih5 count them)
  kol       minute.db call_path: every real X / Telegram call of the last DAYS days (bots, shillers, wallet pseudo-calls
            "w:" out), entered after our measured lag
  ekipa     a followed crew (league follows kind ekipa): the first call of any member per token
  wallet    a wallet we follow or could copy (league follows of any player, wallets/dokazani's proven list, the
            copyable top TOP_WALLETS of wallets/rang): its first buy of a token (wallets.db wallet_trades, hype.db
            chain_trades, events.db wallet_buy) + our lag; its first sale after it (the same three) is the mirror sale
  strategy  our own automatic entries (league.db trades of the Autopilot accounts, apply.strategy_of: fast, proposals,
            insider, copy, zadnjih5, simianx, momentum, ostalo): the entry at its own time, the mirror sale of a copy
            from copy_log (the source's sale + our lag)
LAG: per source the median of its follow's measured copy_log delays (3+), else kol/zadnjih5.lag_of per kind (league
copy_log, else fast.db latency, else 60 s / 30 s; never under 30 s).
RULES (kol/zadnjih5._rules): only what the live system would buy: MC >= 30k, pool >= 15k (unknown: kept), not on the
pump.fun curve, not in the rug archive at that moment.

PATH (up to 24 h): 1-minute candles from the best store that has the entry (kol/zadnjih5._entry: the close of the
entry's minute, else the open of the first candle within 5 min), in this order: minute.db call_candles ("svijeće", 4 h
after every KOL call), range.db / momentum.db gt_candles ("gt"), hype.db live_trades prints ("printovi", kept 48 h),
hype.db token_pulse / hype_snapshots ("puls", one DexScreener price a minute); then extended past that store's end with
the next store that has a point within JOIN_S of it, rescaled at the join (SOL and USD prices, slightly different
quotes): the same order, then events.db price ticks ("tikovi", ~20 min) and fast.db / proposals.db px ("px"). A path
whose entry is only in the coarse stores (tikovi, px) is NOT used: a 10 % stop cannot be judged on 20-minute points.
The rug flag: hype.db rug_archive's archive time, or the pool's liquidity (kol.db snaps, hype.db token_pulse /
hype_snapshots) under LIQ_RUG of the entry's.
COST of one round trip (a fraction, never under MIN_COST): the higher of the real account's model (kol/zadnjih5
.round_trip: pool fee + Jupiter route + AMM impact of 0.1 SOL + the measured network fees) and trade/cost.round_trip
(the fee side calibrated from trade.db orders' cost_pct, + impact). The stop's slippage: trade.db exit_fills (live
stop / trailing sales, the fill against the level, minus the fee side), else izlazi/sim.SLIP_STOP (5 %).

The source's own behaviour (behaviour()): a wallet's realized losers from wallets/pnl.positions (at what loss it sells
them), hold time and win rate; for every source, from the paths: how deep its winners dip first (MAE before the peak),
how long they take to come back, the MFE.
"""
import bisect
import json
import os
import statistics
import time

from izlazi import apply, sim
from kol import zadnjih5 as z5

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = 30
HORIZON_S = sim.HORIZON_S
STAKE_SOL = z5.STAKE_SOL
MIN_COST = 0.02          # never a round trip under 2 % (the owner: real costs 2-6 %)
LIQ_RUG = 0.5
JOIN_S = 600             # a store continues a path only with a point this close to where the path stopped
FINE = ("svijeće", "gt", "printovi", "puls")
COARSE = ("tikovi", "px")
TOP_WALLETS = 300
MAX_PER_SOURCE = 400     # the newest entries of one source
MAX_ENTRIES = int(os.environ.get("IZLAZI_MAX_ENTRIES", "30000"))
# the share of MAX_ENTRIES each kind may take (the newest first), so one kind's volume never crowds out the others
KIND_SHARE = {"kol": 0.4, "wallet": 0.4, "ekipa": 0.08, "strategy": 0.12}
BUDGET_S = int(os.environ.get("IZLAZI_DATA_BUDGET_S", "1200"))
STRATEGY_USERS = None    # (LEAGUE_USER, PAPER_USER) from trade/settings


def _ro(path):
    return z5._ro(path)


def _q(con, sql, args=()):
    return z5._q(con, sql, args)


def paths(over=None):
    """Every database read here (kol/zadnjih5.paths + range.db, momentum.db, proposals.db); `over` replaces any."""
    p = z5.paths(over)
    for k, mod, attr in (("range", "rangedca.data", "db_path"), ("momentum", "momentum.data", "db_path"),
                         ("proposals", "proposals.store", "db_path")):
        if k not in p:
            try:
                p[k] = getattr(__import__(mod, fromlist=[attr]), attr)()
            except Exception:  # noqa: BLE001 - a missing module is a missing source
                p[k] = None
    return p


class Reader(z5.Data):
    """kol/zadnjih5.Data (minute.db, kol.db, hype.db, events.db) + the GeckoTerminal candles of range.db and
    momentum.db, hype.db's minute snapshots and the strategies' own price points."""

    def __init__(self, p, now):
        super().__init__(p, now)
        self.rg = _ro(p.get("range"))
        self.mo = _ro(p.get("momentum"))
        self.fa = _ro(p.get("fast"))
        self.pr = _ro(p.get("proposals"))

    def close(self):
        super().close()
        for c in (self.rg, self.mo, self.fa, self.pr):
            if c is not None:
                c.close()

    def gt(self, tok):
        """1-minute GeckoTerminal candles of range.db / momentum.db gt_candles (zlib JSON), sorted; [] none."""
        import zlib
        out = {}
        for con in (self.rg, self.mo):
            for (blob,) in _q(con, "SELECT data FROM gt_candles WHERE token = ?", (tok,)):
                try:
                    for c in json.loads(zlib.decompress(blob).decode()):
                        out.setdefault(int(c[0]), tuple(c))
                except (ValueError, zlib.error, TypeError):
                    continue
        return [out[k] for k in sorted(out)]

    def pulse(self, tok, lo, hi):
        """[(ts, price USD)] of hype.db token_pulse and hype_snapshots."""
        out = []
        for table in ("token_pulse", "hype_snapshots"):
            out += _q(self.h, f"SELECT ts, price FROM {table} WHERE token = ? AND ts >= ? AND ts <= ? AND price > 0 "
                              "ORDER BY ts LIMIT 5000", (tok, int(lo), int(hi)))
        return out

    def px(self, tok, lo, hi):
        out = []
        for con, table in ((self.fa, "px"), (self.fa, "x_call_px"), (self.pr, "px")):
            out += _q(con, f"SELECT ts, price FROM {table} WHERE token = ? AND ts >= ? AND ts <= ? AND price > 0 "
                           "ORDER BY ts LIMIT 5000", (tok, int(lo), int(hi)))
        return out


def token_stores(rd, tok, times, horizon=HORIZON_S):
    """{name: candles sorted} of one token around the entry times (read once per token)."""
    out = {}
    cs, _cto = rd.candles(tok)
    if cs:
        out["svijeće"] = cs
    g = rd.gt(tok)
    if g:
        out["gt"] = g
    pr, pu, tk, px = [], [], [], []
    for lo, hi in z5._merge(times, 600, horizon + 600):
        pr += [(t, p) for t, p, _mc, _pool in rd.prints(tok, lo, hi)]
        pu += rd.pulse(tok, lo, hi)
        tk += [(t, p) for t, p, _mc in rd.ticks(tok, lo, hi)]
        px += rd.px(tok, lo, hi)
    for name, pts in (("printovi", pr), ("puls", pu), ("tikovi", tk), ("px", px)):
        if pts:
            out[name] = z5.to_candles(pts)
    return out


ORDER = FINE + COARSE


def assemble(stores, t, horizon=HORIZON_S, order=ORDER):
    """(bars, t0, cover_s, how) of an entry at t from the token's stores (see the module text), or None: the best FINE
    store with an entry, extended past its end by the next store with a point within JOIN_S, rescaled at the join."""
    prim = None
    for name in order:
        if name in COARSE:
            break
        got = sim.bars_from_candles(stores[name], t, horizon) if stores.get(name) else None
        if got and got[2]:
            prim = (name, got)
            break
    if prim is None:
        return None
    name, (entry, t0, bars) = prim
    used = [name]
    last_t = t0 + bars[-1][0]
    last_abs = bars[-1][3] * entry
    for other in order:
        if other == name or not stores.get(other) or last_t >= t0 + horizon - 60:
            continue
        cs = stores[other]
        tss = [c[0] + 60 for c in cs]
        k = bisect.bisect_right(tss, last_t) - 1
        ref = None
        if k >= 0 and last_t - tss[k] <= JOIN_S:
            ref = cs[k][4]
        elif k + 1 < len(cs) and tss[k + 1] - last_t <= JOIN_S:
            ref = cs[k + 1][1]
        if not ref or ref <= 0:
            continue
        scale = last_abs / ref
        add = []
        for c in cs[k + 1:]:
            dt = c[0] + 60 - t0
            if dt <= last_t - t0:
                continue
            if dt > horizon:
                break
            hi = z5._capped(c)
            if not (hi and c[3] and c[4]) or c[3] <= 0:
                continue
            add.append((int(dt), hi * scale / entry, c[3] * scale / entry, c[4] * scale / entry))
        if add:
            bars += add
            used.append(other)
            last_t = t0 + add[-1][0]
            last_abs = add[-1][3] * entry
    return bars, t0, last_t - t0, "+".join(used)


def rug_time(rd, tok, t0, liq0, lq, horizon=HORIZON_S):
    """Seconds after t0 of the first rug flag within the horizon (the rug archive's time, the pool under LIQ_RUG of
    the entry's), or None."""
    out = None
    a = rd.archive().get(tok)
    if a and a[0] and t0 < a[0] <= t0 + horizon:
        out = a[0] - t0
    if liq0 and lq:
        for ts, v in lq:
            if t0 < ts <= t0 + horizon and v < LIQ_RUG * liq0:
                out = min(out, ts - t0) if out is not None else ts - t0
                break
    return out


# ---------- costs -------------------------------------------------------------------------------------------------------

class Costs:
    """The round trip of our stake at a pool (see the module text) and the stop's measured slippage."""

    def __init__(self, p):
        try:
            self.tx_sol, self.tx_src = z5.tx_fee()
        except Exception:  # noqa: BLE001
            self.tx_sol, self.tx_src = 0.0005, "zadano 0.0005 SOL"
        try:
            from trade import cost as tcost
            self.cal = tcost.calibration(p.get("trade"))
        except Exception:  # noqa: BLE001
            self.cal = {"fee_side": 0.01, "calibrated": False, "n": 0, "from": "league/store.FEE"}
        self.slip_stop, self.slip_src = slip_stop(p.get("trade"), self.cal.get("fee_side") or 0.0)
        self.seen = []

    def round_trip(self, liq, tok, sol_usd):
        from trade import cost as tcost
        try:
            real = z5.round_trip(liq, tok, sol_usd, self.tx_sol)
        except Exception:  # noqa: BLE001
            real = 0.0
        cal = tcost.round_trip(STAKE_SOL * (sol_usd or z5.SOL_USD_DEFAULT), liq, fee=self.cal.get("fee_side"))
        c = max(MIN_COST, real, cal)
        if len(self.seen) < 20000:
            self.seen.append(c)
        return c

    def info(self):
        return {"median_pct": round(statistics.median(self.seen) * 100, 2) if self.seen else None,
                "p90_pct": round(sim.quantile(self.seen, 0.9) * 100, 2) if self.seen else None,
                "min_pct": MIN_COST * 100, "fee_side": self.cal.get("fee_side"), "fee_from": self.cal.get("from"),
                "tx": self.tx_src, "slip_stop_pct": round(self.slip_stop * 100, 2), "slip_from": self.slip_src,
                "slip_mkt_pct": sim.SLIP_MKT * 100}


def slip_stop(trade_db, fee_side=0.0, min_n=5):
    """(slip fraction, where from): the median shortfall of the live stop / trailing sales against their level
    (trade.db exit_fills.slip_level_pct, the fill includes the swap's fee: fee_side off), else sim.SLIP_STOP."""
    con = _ro(trade_db)
    rows = _q(con, "SELECT slip_level_pct FROM exit_fills WHERE trigger IN ('stop', 'trailing') AND mode = 'live' AND "
                   "slip_level_pct IS NOT NULL ORDER BY id DESC LIMIT 60")
    if con is not None:
        con.close()
    xs = [max(0.0, -float(r[0]) / 100 - fee_side) for r in rows if r[0] is not None]
    if len(xs) >= min_n:
        v = min(0.15, max(0.005, statistics.median(xs)))
        return v, f"trade.db exit_fills, medijan {len(xs)} živih stop/trailing prodaja"
    return sim.SLIP_STOP, f"zadano {sim.SLIP_STOP:.0%} (izmjereno vlasnik 13.11.; živih stop prodaja {len(xs)})"


# ---------- who: sources and their lags ---------------------------------------------------------------------------------

def follows(p, now, days=DAYS):
    """[{id, user, kind, target, label, exit, active}] of every league follow that was active in the window."""
    con = _ro(p.get("league"))
    out = []
    for fid, user, kind, target, label, ex, active, stopped in _q(
            con, "SELECT id, user, kind, target, label, exit, active, stopped FROM follows"):
        if not active and stopped and stopped < now - days * 86400:
            continue
        try:
            ex = json.loads(ex or "{}")
        except ValueError:
            ex = {}
        out.append({"id": fid, "user": user, "kind": kind, "target": target, "label": label, "exit": ex,
                    "active": bool(active)})
    if con is not None:
        con.close()
    return out


def source_lags(p, now, days=DAYS, min_n=3):
    """{(kind, target): median seconds} of our measured copy delays per followed source (league copy_log)."""
    con = _ro(p.get("league"))
    xs = {}
    for kind, target, d in _q(con, "SELECT f.kind, f.target, c.ts - c.ev_ts FROM copy_log c JOIN follows f ON f.id = "
                                   "c.follow_id WHERE c.action = 'ulaz' AND c.ts >= ? AND c.ev_ts > 0",
                              (now - days * 86400,)):
        if d is not None and 0 <= d <= 3600:
            xs.setdefault((kind, target), []).append(float(d))
    if con is not None:
        con.close()
    return {k: max(z5.LAG_MIN_S, statistics.median(v)) for k, v in xs.items() if len(v) >= min_n}


def candidate_wallets(p, now, fl, top=TOP_WALLETS):
    """{wallet: why} of the wallets we follow or could copy (see the module text), bad labels out."""
    out = {}
    for f in fl:
        if f["kind"] == "wallet" and f["target"]:
            out.setdefault(f["target"], "praćen")
    try:
        from wallets import dokazani
        for w in dokazani.current(p.get("wallets")):
            out.setdefault(w, "dokazan")
    except Exception:  # noqa: BLE001
        pass
    try:
        from wallets import rang
        for r in rang.ranked("wallet", path=p.get("wallets"), copyable=True)[:top]:
            out.setdefault(r["target"], "rang")
    except Exception:  # noqa: BLE001
        pass
    if out:
        labels, owner_bad = z5.wallet_labels(p, set(out))
        for w in list(out):
            if (labels.get(w, set()) & z5.BAD_WALLET) or w in owner_bad:
                if out[w] != "praćen":
                    out.pop(w)
    return out


# ---------- the entries -------------------------------------------------------------------------------------------------

def kol_calls(p, now, days=DAYS):
    """[(handle, token, ts, mcap_e, tweet_id)] first call per (handle, token) in the window (bots, shillers out)."""
    from kol import shillers
    mcon = _ro(p.get("minute"))
    kcon = _ro(p.get("kol"))
    rows = _q(mcon, "SELECT handle, token, ts, mcap_e, tweet_id FROM call_path WHERE entry IS NOT NULL AND bad IS NULL "
                    "AND ts >= ? AND ts <= ?", (now - days * 86400, now))
    bots = {h.lower() for (h,) in _q(kcon, "SELECT handle FROM kols WHERE bot = 1")}
    for c in (mcon, kcon):
        if c is not None:
            c.close()
    try:
        shill = {h.lower() for h in shillers.handles()}
    except Exception:  # noqa: BLE001
        shill = set()
    first = {}
    for h, tok, ts, mc, tid in rows:
        if not h or not tok or h.startswith("w:") or h.lower() in bots or h.lower() in shill or tok in z5.STABLE:
            continue
        k = (h, tok)
        if k not in first or ts < first[k][2]:
            first[k] = (h, tok, int(ts), mc, tid)
    return sorted(first.values(), key=lambda r: r[2])


def wallet_trades(p, wallets, now, days=DAYS):
    """{(wallet, mint): (first buy ts, first sale ts after it or None)} of the candidate wallets in the window, and
    their own trade rows (for wallets/pnl) {wallet: [rows]}."""
    since = now - days * 86400
    buys, sells, own = {}, {}, {}
    wcon = _ro(p.get("wallets"))
    for w in wallets:
        rows = []
        for sig, ts, mint, tokens, sol, kind in _q(wcon, "SELECT sig, ts, mint, tokens, sol, kind FROM wallet_trades "
                                                         "WHERE wallet = ? AND ts >= ? ORDER BY ts", (w, since)):
            rows.append({"sig": sig, "ts": ts, "mint": mint, "tokens": tokens or 0.0, "sol": sol or 0.0, "kind": kind})
            if mint in z5.STABLE or not ts:
                continue
            if kind == "buy":
                buys.setdefault((w, mint), []).append(int(ts))
            elif kind == "sell":
                sells.setdefault((w, mint), []).append(int(ts))
        if rows:
            own[w] = rows
    if wcon is not None:
        wcon.close()
    hcon = _ro(p.get("hype"))
    want = set(wallets)
    for w, mint, side, ts in _q(hcon, "SELECT wallet, mint, side, ts FROM chain_trades WHERE ts >= ? AND ts <= ?",
                                (since, now)):
        if w in want and mint not in z5.STABLE and ts:
            (buys if side == "buy" else sells if side == "sell" else {}).setdefault((w, mint), []).append(int(ts))
    if hcon is not None:
        hcon.close()
    econ = _ro(p.get("events"))
    for w in wallets:
        for typ, mint, ts in _q(econ, "SELECT type, mint, ts / 1000 FROM events WHERE actor = ? AND type IN "
                                      "('wallet_buy', 'wallet_sell') AND ts >= ?", (w, since * 1000)):
            if mint and mint not in z5.STABLE and ts:
                (buys if typ == "wallet_buy" else sells).setdefault((w, mint), []).append(int(ts))
    if econ is not None:
        econ.close()
    out = {}
    for k, bs in buys.items():
        b = min(bs)
        after = [s for s in sells.get(k, ()) if s > b]
        out[k] = (b, min(after) if after else None)
    return out, own


def behaviour_wallet(rows):
    """A wallet's own exits from its trades (wallets/pnl.positions, closed positions of 0.02 SOL+): {own_stop_p50,
    own_stop_p75 (the loss % it sells its losers at, positive), hold_min_p50, win_rate, closed}."""
    from wallets import pnl
    try:
        pos = pnl.positions(rows)
    except Exception:  # noqa: BLE001
        return {}
    closed = [x for x in pos.values() if x.get("status") == "closed" and (x.get("cost") or 0) >= 0.02]
    if not closed:
        return {"closed": 0}
    losses = [-x["realized"] / x["cost"] * 100 for x in closed if x["realized"] < 0 and x["cost"] > 0]
    holds = [x["hold_min"] for x in closed if x.get("hold_min") is not None]
    return {"closed": len(closed), "win_rate": round(sum(1 for x in closed if x["realized"] > 0) / len(closed), 3),
            "own_stop_p50": round(statistics.median(losses), 1) if losses else None,
            "own_stop_p75": round(sim.quantile(losses, 0.75), 1) if losses else None,
            "hold_min_p50": round(statistics.median(holds), 1) if holds else None}


def strategy_trades(p, now, days=DAYS):
    """[{tok, ts, strategy, follow_id, sell_ev}] our own automatic entries (both Autopilot accounts, the first per
    strategy and token), with a copy's source sale from copy_log."""
    from trade import settings as ts
    users = (ts.LEAGUE_USER, ts.PAPER_USER)
    con = _ro(p.get("league"))
    fl = {}
    for fid, kind, target, label, ex in _q(con, "SELECT id, kind, target, label, exit FROM follows"):
        try:
            ex = json.loads(ex or "{}")
        except ValueError:
            ex = {}
        fl[fid] = {"kind": kind, "target": target, "label": label, "exit": ex}
    cols = {r[1] for r in _q(con, "PRAGMA table_info(trades)")}
    fcol = "follow_id" if "follow_id" in cols else "NULL"
    rows = _q(con, f"SELECT token, opened_ts, source, {fcol}, size_usd, entry_px, entry_eff FROM trades WHERE user IN "
                   f"(?, ?) AND opened_ts >= ? ORDER BY opened_ts", (*users, now - days * 86400))
    sells = {}
    for fid, tok, ev in _q(con, "SELECT follow_id, token, ev_ts FROM copy_log WHERE side = 'sell' AND ev_ts >= ?",
                           (now - days * 86400,)):
        sells.setdefault((fid, tok), []).append(int(ev))
    if con is not None:
        con.close()
    seen, out = set(), []
    for tok, ots, src, fid, size, px, eff in rows:
        st = apply.strategy_of(src, fl.get(fid))
        if not st or not tok or not ots:
            continue
        if (st, tok) in seen:
            continue
        seen.add((st, tok))
        sv = [s for s in sells.get((fid, tok), ()) if s > ots] if fid else []
        liq = None
        try:
            imp = 1 - px * 1.01 / eff
            if size and 1e-6 < imp < 0.9:
                liq = 2 * size * (1 - imp) / imp
        except (TypeError, ZeroDivisionError):
            pass
        out.append({"tok": tok, "ts": int(ots), "strategy": st, "follow_id": fid, "sell_ev": min(sv) if sv else None,
                    "liq": liq, "kind": (fl.get(fid) or {}).get("kind")})
    return out


def _mcap(rd, tok, t, sol):
    """The market cap near t from events.db ticks (USD) or hype.db prints (SOL), None."""
    tk = rd.ticks(tok, t - 1800, t + 1800)
    v = z5.nearest([(a, c) for a, _b, c in tk if c], t, 1800)
    if v:
        return v
    pr = rd.prints(tok, t - 300, t + 300)
    v = z5.nearest([(a, c) for a, _b, c, _d in pr if c], t, 300)
    return v * sol if v else None


def build(p=None, now=None, log=print, budget_s=BUDGET_S, max_entries=MAX_ENTRIES, days=DAYS, kinds=None, share=None):
    """(entries, coverage, meta). An entry: {kind, src, tok, ts (path start), arrs (izlazi/sim.pack), cover, cost,
    sell_s, rug_s, how, stats (izlazi/sim.path_stats), sig_ts (the source's own call / buy time), lag (s), mcap, liq
    (at the signal, None unknown)}; coverage per kind: sources, entries tried / with a path / ruled out (why) / without
    a path, the stores used, the hours covered. 15.11. (konsenzus/): kinds = only these kinds (default all four),
    share = {kind: share of max_entries} instead of KIND_SHARE."""
    p = paths(p)
    now = int(now or time.time())
    t_start = time.monotonic()
    costs = Costs(p)
    fl = follows(p, now, days)
    lags = source_lags(p, now, days)
    kind_lag = {}
    for k in ("kol", "wallet"):
        try:
            kind_lag[k] = z5.lag_of(k, p, now, days)
        except Exception:  # noqa: BLE001
            kind_lag[k] = (float(z5.LAG_DEFAULT_S[k]), "zadano")
    cov = {k: {"izvori": 0, "ulazi": 0, "s_putom": 0, "pravila": {}, "bez_puta": 0, "samo_grubo": 0, "izvori_puta": {},
               "sati": {"1h": 0, "4h": 0, "24h": 0}} for k in ("kol", "ekipa", "wallet", "strategy")}
    wanted = []   # (kind, src, tok, t_src, lag, sell_ts, mcap, liq_hint)
    want_kinds = set(kinds or ("kol", "ekipa", "wallet", "strategy"))
    # KOL calls (and the crews made of them)
    calls = kol_calls(p, now, days) if want_kinds & {"kol", "ekipa"} else []
    per = {}
    for h, tok, ts, mc, _tid in calls:
        per.setdefault(h, []).append((tok, ts, mc))
    for h, xs in (per.items() if "kol" in want_kinds else ()):
        lag = lags.get(("kol", h), kind_lag["kol"][0])
        for tok, ts, mc in xs[-MAX_PER_SOURCE:]:
            wanted.append(("kol", h, tok, ts, lag, None, mc, None))
    cov["kol"]["izvori"] = len(per) if "kol" in want_kinds else 0
    crews = [f for f in fl if f["kind"] == "ekipa" and f["target"]] if "ekipa" in want_kinds else []
    for f in {f["target"]: f for f in crews}.values():
        mem = {m.lower().lstrip("@") for m in f["target"].split(",") if m.strip()}
        first = {}
        for h, tok, ts, mc, _tid in calls:
            if h.lower().lstrip("@") in mem and (tok not in first or ts < first[tok][0]):
                first[tok] = (ts, mc)
        lag = lags.get(("ekipa", f["target"]), kind_lag["kol"][0])
        for tok, (ts, mc) in sorted(first.items(), key=lambda x: x[1][0])[-MAX_PER_SOURCE:]:
            wanted.append(("ekipa", f["target"], tok, ts, lag, None, mc, None))
        cov["ekipa"]["izvori"] += 1
    # wallets
    cands = candidate_wallets(p, now, fl) if "wallet" in want_kinds else {}
    wt, own = wallet_trades(p, sorted(cands), now, days) if cands else ({}, {})
    perw = {}
    for (w, mint), (b, s) in wt.items():
        perw.setdefault(w, []).append((b, mint, s))
    for w, xs in perw.items():
        lag = lags.get(("wallet", w), kind_lag["wallet"][0])
        for b, mint, s in sorted(xs)[-MAX_PER_SOURCE:]:
            wanted.append(("wallet", w, mint, b, lag, s, None, None))
    cov["wallet"]["izvori"] = len(perw)
    cov["wallet"]["kandidati"] = {k: sum(1 for v in cands.values() if v == k) for k in ("praćen", "dokazan", "rang")}
    # our own strategies
    for s in (strategy_trades(p, now, days) if "strategy" in want_kinds else ()):
        sell = s["sell_ev"] + kind_lag["wallet"][0] if s["sell_ev"] and s["kind"] == "wallet" else None
        wanted.append(("strategy", s["strategy"], s["tok"], s["ts"], 0.0, sell, None, s["liq"]))
    cov["strategy"]["izvori"] = len({w[1] for w in wanted if w[0] == "strategy"})
    if len(wanted) > max_entries:   # the newest first, every kind within its share
        keep = []
        for kind, sh in (share or KIND_SHARE).items():
            ws = sorted((w for w in wanted if w[0] == kind), key=lambda w: -w[3])
            keep += ws[:int(max_entries * sh)]
            if len(ws) > int(max_entries * sh):
                cov[kind]["skraćeno_na"] = int(max_entries * sh)
        wanted = keep
    by_tok = {}
    for w in wanted:
        by_tok.setdefault(w[2], []).append(w)
    rd = Reader(p, now)
    entries = []
    stopped = None
    try:
        for n_done, (tok, ws) in enumerate(sorted(by_tok.items(), key=lambda x: -len(x[1]))):
            if time.monotonic() - t_start > budget_s:
                stopped = f"stalo nakon {budget_s} s: {n_done} od {len(by_tok)} tokena"
                break
            times = [w[3] + w[4] for w in ws]
            stores = token_stores(rd, tok, times)
            lq = rd.liqs(tok, min(times), max(times) + HORIZON_S)
            for kind, src, _tok, t_src, lag, sell_ts, mc, liq_hint in ws:
                c = cov[kind]
                c["ulazi"] += 1
                t = int(t_src + lag)
                sol = rd.sol_usd(t)
                liq = z5.nearest(lq, t) or liq_hint
                mcap = mc if mc else None
                if mcap is None and (stores.get("tikovi") or stores.get("printovi")):
                    mcap = _mcap(rd, tok, t, sol)
                ev = {"tok": tok, "ts": t_src, "mcap": mcap, "liq": liq}
                why = z5._rules(ev, rd, sol) if kind != "strategy" else None   # our own entries passed them live
                if why:
                    c["pravila"][why] = c["pravila"].get(why, 0) + 1
                    continue
                got = assemble(stores, t)
                if got is None:
                    if any(stores.get(x) for x in COARSE):
                        c["samo_grubo"] += 1
                    else:
                        c["bez_puta"] += 1
                    continue
                bars, t0, cover, how = got
                c["s_putom"] += 1
                for part in how.split("+"):
                    c["izvori_puta"][part] = c["izvori_puta"].get(part, 0) + 1
                for lab, s_ in (("1h", 3600), ("4h", 4 * 3600), ("24h", HORIZON_S)):
                    c["sati"][lab] += int(cover >= s_ - sim.TOL_S)
                rug_s = rug_time(rd, tok, t0, liq, lq)
                sell_s = (sell_ts + lag - t0) if sell_ts and kind == "wallet" else (
                    sell_ts - t0 if sell_ts else None)
                fitted = sim.fit(bars)
                entries.append({"kind": kind, "src": src, "tok": tok, "ts": t0, "arrs": sim.pack(fitted),
                                "cover": int(cover), "cost": costs.round_trip(liq, tok, sol),
                                "sell_s": sell_s if sell_s is not None and sell_s >= 0 else None, "rug_s": rug_s,
                                "how": how, "stats": sim.path_stats(fitted), "sig_ts": int(t_src),
                                "lag": round(float(lag), 1), "mcap": mcap, "liq": liq})
    finally:
        rd.close()
    entries.sort(key=lambda e: e["ts"])
    beh = {w: behaviour_wallet(rows) for w, rows in own.items()}
    meta = {"now": now, "days": days, "lag": {k: {"s": round(v[0]), "from": v[1]} for k, v in kind_lag.items()},
            "lags_measured": len(lags), "costs": costs.info(), "wallet_own": beh, "stopped": stopped,
            "s": round(time.monotonic() - t_start, 1), "follows": len(fl)}
    log(f"naučeni izlazi: {len(entries)} ulaza s putanjom ("
        + ", ".join(f"{k} {v['s_putom']}/{v['ulazi']}" for k, v in cov.items()) + f") za {meta['s']:.0f} s"
        + (f"; {stopped}" if stopped else ""))
    return entries, cov, meta
