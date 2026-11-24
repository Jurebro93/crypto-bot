"""momentum_scalp's data pass (run_momentum.py once, a short process every MOM_EVERY_S = 60 s; writes momentum.db
only). Flag off: nothing is fetched, except the open Grok EV gate calibration rows (their tokens only, free).

One pass:
  1. the watched tokens (data.candidates): open signals, open momentum trades and open calibration rows first (their
     price path decides an outcome), then tokens with a signal in the last 2 h, the scanner's migrated candidates,
     the live list (hype pulse, PumpPortal migrations of the last 6 h) and launches that reached 10k
  2. one DexScreener snapshot of each (free); under 30k / on the curve: put aside for an hour, not stored
  3. the open signals and calibration rows get their outcome from the stored snapshots
  4. every token without an open signal (and 45 min after its last one) through the entry rules, free first:
     DexScreener's numbers (rules.cheap_check) -> unique buyers and anti-wash (PumpPortal trades; GeckoTerminal
     /pools/multi in ONE request for the rest, within MOM_GT_DAY) -> rug verdict (ui/kandidati.rug_view) -> shill
     network -> top 10 (free tables, then Helius within MOM_HELIUS_DAY). All pass: a signal row (the base rate);
     the paper trader (momentum/trade.py, league/auto) buys fresh signals on the demo account.
  5. the near misses of this pass (passed DexScreener's numbers, failed a later check) in kv "last_pass" for the MCP
"""
import time

from . import data, evgate, rules

FLAG = "momentum_scalp"
PRUNE_EVERY_S = 3600


def mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001 - unreadable flag: off
        return "off"


def _sol_usd():
    try:
        from rangedca import trade as rtrade
        return rtrade.sol_usd() or 150.0
    except Exception:  # noqa: BLE001
        return 150.0


def _fee_cfg():
    try:
        from scan import store as sstore
        return sstore.config()
    except Exception:  # noqa: BLE001
        return {"fee_rates": {"curve": 0.0125, "pumpswap": 0.003, "other": 0.0025}}


def fee_rate(dex, cfg):
    """The pool's fee as a share of volume (scan/filters.fee_rate: the scanner's own table)."""
    try:
        from scan import filters
        return filters.fee_rate({"curve": False, "dex": dex}, cfg)
    except Exception:  # noqa: BLE001
        return None


def market_features(s, cfg):
    """The DexScreener part of the features of one snapshot."""
    vx = rules.vol_x(s.get("vol_m5"), s.get("vol_h1"))
    bs = rules.buy_share(s.get("buys_m5"), s.get("sells_m5"))
    liq = s.get("liq") or 0
    return {"price": s.get("price"), "mcap": s.get("mcap"), "liq": liq, "ch_m5": s.get("ch_m5"), "bonded": s.get("bonded"),
            "vol_m5": s.get("vol_m5"), "vol_h1": s.get("vol_h1"), "buys_m5": s.get("buys_m5"),
            "sells_m5": s.get("sells_m5"), "buy_share": round(bs, 3) if bs is not None else None,
            "vol_x": round(vx, 2) if vx is not None else None, "dex": s.get("dex"),
            "fee_rate": fee_rate(s.get("dex"), cfg),
            "turnover_h1": round((s.get("vol_h1") or 0) / liq, 2) if liq else None}


def resolve_signals(con, now):
    """Outcome of every open signal whose simulated trade is over (stop, trailing after TP1, or the 45 minutes):
    first / hit (+15 % before -10 %) and the exit rules' result after cost. Returns the number resolved."""
    n = 0
    end_s = rules.RULES["time_s"]
    for s in data.open_signals(con):
        path = rules.clean_path(data.snap_rows(con, s["token"], s["ts"] + 1, s["ts"] + end_s), s["price"])   # 14.11.
        over = now >= s["ts"] + end_s
        if over and (not path or path[-1][0] < s["ts"] + end_s):
            path = path + [(s["ts"] + end_s, path[-1][1] if path else s["price"])]   # the last price we saw stands
        sim, _why = rules.simulate(path, s["price"], s["ts"], s.get("liq"))
        if sim is None and not over:
            continue
        o = rules.outcome(path, s["price"], s["ts"], now)
        con.execute("UPDATE signals SET status='done', first=?, hit=?, resolved_ts=?, max_pct=?, min_pct=?, sim_ret=? "
                    "WHERE id=?", (o["first"], o["hit"], o["resolved_ts"], o["max_pct"], o["min_pct"], sim, s["id"]))
        n += 1
    con.commit()
    return n


class Ctx:
    """What one pass shares: the scanner's config, SOL price, rug tables, the shill set (each read once, lazily)."""

    def __init__(self, con, now, gt_fetch=None, helius=None, rug_src=None):
        self.con, self.now = con, now
        self.gt_fetch, self.helius = gt_fetch, helius
        self.cfg = _fee_cfg()
        self.sol_usd = _sol_usd()
        self._rug = rug_src
        self._shill = None
        self.gt_calls = 0

    def rug(self, tok, mcap, liq):
        if self._rug is None:
            from scan import filters
            from ui import kandidati
            S = kandidati.Sources()
            try:
                archived = S.archived()
            except Exception:  # noqa: BLE001
                archived = frozenset()
            tables = filters.rug_tables()
            self._rug = lambda t, m, l_: kandidati.rug_view(t, m, l_, S, tables, archived)
        return self._rug(tok, mcap, liq)

    def shill(self, tok):
        if self._shill is None:
            self._shill = data.shill_handles()
        return sorted(data.shill_calls(tok, self.now, self._shill))


def flow_features(ctx, pre, snaps):
    """{token: (buyers_in, wash_in)} for the prequalified tokens: PumpPortal first, then ONE GeckoTerminal request for
    the rest (within the day cap)."""
    out, need = {}, []
    for tok in pre:
        s = snaps[tok]
        b, w = data.pp_features(data.pp_trades(tok, ctx.now), ctx.now, (s.get("buys_m5") or 0) + (s.get("sells_m5") or 0),
                                ctx.sol_usd)
        if b is None:
            need.append(tok)
        else:
            out[tok] = (b, w)
    pools = {snaps[t].get("pool"): t for t in need if snaps[t].get("pool")}
    if pools and data.gt_take(ctx.con, ctx.now):
        ctx.gt_calls += 1
        try:
            got = data.gt_multi(list(pools), ctx.gt_fetch)
        except Exception as e:  # noqa: BLE001
            print(f"momentum: GeckoTerminal {type(e).__name__}", flush=True)
            got = None
        for pool, a in (got or {}).items():
            tok = pools.get(pool)
            if tok:
                out[tok] = data.gt_features(a, snaps[tok].get("vol_h1"))
    return out


def evaluate(ctx, tok, s, flow):
    """(features, (key, why) or None) of one prequalified token, the paid top 10 lookup only when all else passed."""
    f = market_features(s, ctx.cfg)
    b, w = flow or (None, None)
    f["buyers_in"], f["wash_in"] = b, w
    for key, fn in rules.CHECKS[:3]:
        why = fn(f, None)
        if why:
            return f, (key, why)
    rv = ctx.rug(tok, s.get("mcap"), s.get("liq"))
    f["rug_in"] = {"level": (rv or {}).get("level"), "hard": (rv or {}).get("hard"), "risk": (rv or {}).get("risk")}
    why = rules.rug_check(f["rug_in"])
    if why:
        return f, ("rug", why)
    f["shill_in"] = ctx.shill(tok)
    why = rules.shill_check(f["shill_in"])
    if why:
        return f, ("shill", why)
    t10, src = data.top10(ctx.con, tok, ctx.now, ctx.helius)
    f["top10"], f["top10_src"] = t10, src
    res = rules.entry_check(f)
    return f, res


def once(now=None, log=print, fetch=None, gt_fetch=None, helius=None, rug_src=None):
    """One pass. Returns a short summary text ("off" when the flag is off and nothing waits for an outcome)."""
    now = int(now or time.time())
    m = mode()
    if m == "off":
        return _calib_only(now, fetch, log)
    con = data.connect()
    try:
        open_sig = data.open_signals(con)
        keep = [s["token"] for s in open_sig] + data.open_trade_tokens() + evgate.open_tokens(con)
        cands = data.candidates(con, now, keep)
        snaps = data.poll(con, cands, now, fetch, keep)
        n_res = resolve_signals(con, now)
        n_cal = evgate.resolve(con, now)
        ctx = Ctx(con, now, gt_fetch, helius, rug_src)
        busy = {s["token"] for s in open_sig}
        pre = []
        for tok, s in snaps.items():
            if tok in busy or now - data.last_signal_ts(con, tok) < rules.RULES["cooldown_s"]:
                continue
            if rules.cheap_check(market_features(s, ctx.cfg)) is None:
                pre.append(tok)
        flows = flow_features(ctx, pre, snaps) if pre else {}
        near, new = [], []
        for tok in pre:
            s = snaps[tok]
            f, res = evaluate(ctx, tok, s, flows.get(tok))
            if res:
                near.append({"token": tok, "symbol": s.get("symbol"), "ts": now, "mcap": s.get("mcap"),
                             "ch_m5": s.get("ch_m5"), "vol_x": f.get("vol_x"), "buy_share": f.get("buy_share"),
                             "failed": res[0], "why": res[1]})
                continue
            cost = rules.round_trip_cost(rules.LOT_USD, s.get("liq"))
            sid = data.add_signal(con, tok, s.get("symbol"), now, s, f, cost)
            new.append(tok)
            log(f"momentum signal #{sid} {s.get('symbol') or tok[:6]}: MC ${s.get('mcap') or 0:,.0f}, "
                f"{(s.get('ch_m5') or 0):+.1f} % u 5 min, volumen {f.get('vol_x')}x, kupnje {f.get('buy_share'):.0%}, "
                f"kupci {(f.get('buyers_in') or {}).get('now')} ({(f.get('buyers_in') or {}).get('how')})")
        data.kv_put(con, "last_pass", {"ts": now, "watched": len(snaps), "prequalified": len(pre), "signals": new,
                                       "near": near[:30], "gt_calls": ctx.gt_calls})
        if now - (data.kv_get(con, "last_prune") or 0) >= PRUNE_EVERY_S:
            data.prune(con, now)
            data.kv_put(con, "last_prune", now)
        con.commit()
        text = (f"momentum: {len(snaps)} tokena, prošlo DexScreener uvjete {len(pre)}, signala {len(new)}, riješeno "
                f"{n_res} signala i {n_cal} Grok zahtjeva; GeckoTerminal danas {data.day_used(con, 'gt_day', now)}/"
                f"{data.GT_DAY}, Helius danas {data.day_used(con, 'helius_day', now)}/{data.HELIUS_DAY} kredita")
        if new or now % 900 < 60:
            log(text)
        return text
    finally:
        con.close()


def _calib_only(now, fetch, log):
    """Flag off: only the Grok calibration rows that wait for an outcome (their tokens, one free DexScreener read)."""
    ro = data.ro()
    if ro is None:
        return "off"
    try:
        has = ro.execute("SELECT 1 FROM calib WHERE status='open' LIMIT 1").fetchone() is not None
    except Exception:  # noqa: BLE001
        has = False
    finally:
        ro.close()
    if not has:
        return "off"
    con = data.connect()
    try:
        toks = evgate.open_tokens(con)
        data.poll(con, [], now, fetch, toks)
        n = evgate.resolve(con, now)
        return f"off (kalibracija Groka: {len(toks)} tokena, riješeno {n})"
    finally:
        con.close()
