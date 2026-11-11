#!/usr/bin/env python3
"""range_dca's data job (rangedca/, flag range_dca, 10.11. Jure). One short process a minute (start.sh), so it holds no
memory between passes; flag off: it reads the flag and ends, nothing is fetched.

    python3 run_range.py once        poll + (every 5 min) detect; start.sh runs it every RANGE_EVERY_S (60 s)
    python3 run_range.py backtest [--days 14] [--gt N] [--force]   the backtest over the data we have (nightly)
    python3 run_range.py status      the computed ranges, best first

A pass: the candidates (rangedca/data.candidates), one DexScreener snapshot of those the hype scan does not snapshot
itself; every 5 minutes the range of every candidate from its minute series (detect.analyze), the exclusions
(rules.exclusions; for a token with an open range position also the transfer-holders check, rangedca/holders.py),
and at most 3 GeckoTerminal seeds for a candidate that meets the minimums but has < 6 h of history; between those
passes the active ranges get fresh 5-minute numbers (buys share, volume, change) every minute. Writes range.db only.

11.11. (Jure: "širi range watchlist + event tokeni"): while the flag range_market (G20) or event_tokens (G19) is on,
the same pass also runs the market watchlist (rangedca/market.py: up to RANGE_MARKET_MAX 400 bonded tokens of the
whole market and the event topics' tokens, 5 / 15-minute DexScreener snapshots inside per-source day caps) and
computes their ranges with the signal pass's (which keeps its 40 tokens and its rules unchanged). Every range carries
its source (signal > event > market). A market / event token gets a GeckoTerminal seed only when it is close to an
entry (an active range in the bottom 40 % without minute candles, or 2 h+ of snapshots that already show a range
with the price in the bottom 30 %), inside RANGE_GT_DAY and RANGE_MKT_SEED_DAY. range_dca off with both of them on:
only the market watchlist's data is collected (nothing trades).
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DETECT_EVERY_S = 290   # "recomputed every 5 min" (a pass a minute; 10 s of slack for the pass's own run time)
PRUNE_EVERY_S = 3600


def _mode(name="range_dca"):
    try:
        from league import flags
        return flags.mode(name)
    except Exception:  # noqa: BLE001 - unreadable flag: off
        return "off"


def _minimums_met(snap):
    return bool(snap and snap.get("bonded", True) and (snap.get("mcap") or 0) >= 30_000 and (snap.get("liq") or 0) >= 20_000
                and (snap.get("vol_h1") or 0) >= 10_000)


def _near_entry(res, candles, snap, now, has_gt):
    """A market / event token close to an entry, worth a GeckoTerminal seed: an active range in the bottom 40 % still
    without minute candles, or (under 6 h of snapshots) 2 h+ of them already showing an active range with the price in
    the bottom 30 %."""
    from rangedca import detect
    if res.get("active"):
        return not has_gt and res.get("pos_pct") is not None and res["pos_pct"] <= 40
    if res.get("status") != "premalo podataka" or not candles or candles[-1][0] - candles[0][0] < 2 * 3600:
        return False
    proto = detect.analyze(candles, now, snap, {"min_hist_h": 2})
    return bool(proto.get("active") and proto.get("pos_pct") is not None and proto["pos_pct"] <= 30)


def once(now=None, log=print, fetch=None, gt_fetch=None, post=None, extra=(), net=None):
    """One pass. Returns a short summary text ("off" when range_dca, range_market and event_tokens are all off).
    net: rangedca/market.Net stand-in (tests); fetch also serves the market pass when net is not given."""
    m_dca, m_mkt, m_evt = _mode(), _mode("range_market"), _mode("event_tokens")
    if m_dca == "off" and m_mkt == "off" and m_evt == "off":
        return "off"
    from rangedca import data, detect, holders, market, rules, view
    now = int(now or time.time())
    con = data.connect()
    try:
        sig = data.candidates(con, now, extra) if m_dca != "off" else []
        pools = {r[0] for r in con.execute("SELECT token FROM pools")}
        pulse_all = data.pulse_recent(now)
        pulse = pulse_all - (set(sig) - pools)   # a token without a known pool is polled once for it
        if sig:
            data.poll(con, sig, now, fetch=fetch, pulse_fresh=pulse)
        open_toks = set(data.open_round_tokens())
        srcs = {t: ["signal"] for t in sig}
        mk = {"tokens": [], "src": {}, "stats": {}}
        if m_mkt != "off" or m_evt != "off":
            mk = market.pass_once(con, now, net or market.Net(fetch), log, signal=sig, pulse=pulse_all,
                                  market_on=m_mkt != "off", event_on=m_evt != "off", open_toks=open_toks)
            for t in mk["tokens"]:
                srcs.setdefault(t, []).append(mk["src"].get(t, "market"))
        cands = sig + [t for t in mk["tokens"] if t not in set(sig)]
        full = now - (data.kv_get(con, "last_detect") or 0) >= DETECT_EVERY_S
        seeds, n_act, n_ok = 0, 0, 0
        for tok in cands:
            prev, st = data.load_range(con, tok)
            if not full and not (prev and (prev.get("active") or tok in open_toks)):
                continue
            candles, snap = data.series(con, tok, now)
            if not candles:
                continue
            sym = (snap or {}).get("symbol") or (prev or {}).get("symbol")
            src, src_all = view.source_of(srcs.get(tok) or ["signal"])
            if full:
                res = detect.analyze(candles, now, snap)
                pool = (snap or {}).get("pool")
                if src == "signal":
                    want = res["status"] == "premalo podataka" and _minimums_met(snap)
                else:   # 11.11.: a market / event token only close to an entry, inside its own day cap
                    has_gt = con.execute("SELECT 1 FROM gt_candles WHERE token=?", (tok,)).fetchone() is not None
                    want = (data.day_used(con, "mkt_seed_day", now) < market.SEED_DAY and _minimums_met(snap)
                            and _near_entry(res, candles, snap, now, has_gt))
                if want and seeds < data.GT_PER_PASS and pool:
                    if data.seed(con, tok, pool, now, fetch=gt_fetch):
                        seeds += 1
                        if src != "signal":
                            data.day_add(con, "mkt_seed_day", 1, now)
                        candles, snap = data.series(con, tok, now)
                        res = detect.analyze(candles, now, snap)
                hw = None
                if tok in open_toks:
                    hw = holders.check(con, tok, (snap or {}).get("pool"), (snap or {}).get("supply"), now, post)
                new_st = rules.exclusions(st, res, now, hw)
                res = rules.apply_exclusion(res, new_st, now)
                res["mts"] = now
                if (prev or {}).get("status") != res["status"] and (res["active"] or res["status"] == "isključen"):
                    note = (f"raspon {res['zones']['mc']['range_low_low'] or 0:,.0f}-{res['zones']['mc']['range_high_top'] or 0:,.0f}, "
                            f"ocjena {res['score']:.2f}" if res["active"] else res["why"])
                    data.event(con, tok, res["status"], note, now)
                    log(f"range {sym or tok[:6]}: {res['status']} ({note})")
                st = new_st
            else:   # between the 5-minute passes: the active range keeps its zones, its 5-minute numbers are renewed
                res = dict(prev)
                cs = [c for c in candles if c[0] >= now - 6 * 3600]
                res["metrics"] = detect.metrics(cs, now, snap)
                px = res["metrics"].get("price")
                z = res.get("zones")
                if px and z and z["range_high_top"] > z["range_low_low"]:
                    res["pos_pct"] = round((px - z["range_low_low"]) / (z["range_high_top"] - z["range_low_low"]) * 100, 1)
                res["mts"] = now
            res.pop("symbol", None)
            res.pop("state", None)
            res["source"], res["sources"] = src, src_all
            data.save_range(con, tok, res, st, sym)
            n_act += int(bool(res.get("active")))
            n_ok += int(bool(res.get("active")) and (res.get("score") or 0) >= rules.RULES["score_min"])
        if full:
            data.kv_put(con, "last_detect", now)
        if now - (data.kv_get(con, "last_prune") or 0) >= PRUNE_EVERY_S:
            data.prune(con, now)
            _prune_holders(con, now, open_toks)
            market.prune(con, now, keep_tokens=set(sig) | open_toks)
            data.kv_put(con, "last_prune", now)
        con.commit()
        ms = mk.get("stats") or {}
        text = (f"range: {len(cands)} kandidata (signal {len(sig)}, tržište {len(mk['tokens']) - ms.get('events', 0)}, "
                f"eventi {ms.get('events', 0)}), aktivnih {n_act}, ocjena >= {rules.RULES['score_min']}: {n_ok}; "
                f"GeckoTerminal danas {data.day_used(con, 'gt_day', now)}/{data.GT_DAY}, Helius danas "
                f"{data.day_used(con, 'helius_day', now)}/{holders.CREDITS_DAY} kredita"
                + (f"; tržište: DexScreener danas {data.day_used(con, 'mkt_dex_day', now)}/{market.DEX_DAY}, osvježeno "
                   f"{ms.get('refreshed', 0)}, iz hype skena {ms.get('reused', 0)}, preskočeno zbog stropa "
                   f"{ms.get('dropped', 0)}, primljeno {ms.get('admitted', 0)}" if ms else ""))
        if full:
            log(text)
        return text
    finally:
        con.close()


def _prune_holders(con, now, open_toks):
    from rangedca import data, holders
    con.execute(holders.SCHEMA)
    for (k,) in con.execute("SELECT k FROM kv WHERE k LIKE 'hold:%'").fetchall():
        tok = k[5:]
        st = data.kv_get(con, k) or {}
        if tok not in open_toks and now - (st.get("checked") or 0) > 3 * 86400:
            con.execute("DELETE FROM holder_ledger WHERE token=?", (tok,))
            con.execute("DELETE FROM kv WHERE k=?", (k,))


def status(log=print):
    from rangedca import data, market
    con = data.ro()
    if con is not None:
        try:
            cost = market.cost_today(con, time.time())
            log("trošak danas: " + ", ".join(f"{k} {v['used']}" + (f"/{v['cap']}" if v["cap"] else "") for k, v in cost.items()))
            log(f"tržišna lista: {market.counts(con)}")
        except Exception:  # noqa: BLE001 - no market table yet
            pass
        finally:
            con.close()
    rs = data.read_ranges()
    for tok, r in sorted(rs.items(), key=lambda kv: (-(kv[1].get("active") or 0), -(kv[1].get("score") or 0))):
        z = (r.get("zones") or {}).get("mc") or {}
        log(f"{r.get('symbol') or tok[:6]:10} {r['status']:16} ocjena {r.get('score') or 0:.2f} pozicija "
            f"{r.get('pos_pct') if r.get('pos_pct') is not None else '-'} % dno {z.get('range_low_low') or 0:,.0f}-"
            f"{z.get('range_low_top') or 0:,.0f} vrh {z.get('range_high_low') or 0:,.0f}-{z.get('range_high_top') or 0:,.0f}")
    return rs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    b = sub.add_parser("backtest")
    b.add_argument("--days", type=int, default=14)
    b.add_argument("--gt", type=int, default=int(os.environ.get("RANGE_BT_GT", "30")),
                   help="GeckoTerminal requests for history at most (inside the range day cap)")
    b.add_argument("--force", action="store_true", help="also while the flag is off")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "once":
        once()
    elif a.cmd == "backtest":
        if _mode() == "off" and not a.force:
            print("range backtest: zastavica range_dca je isključena, ništa se ne radi", flush=True)
            return 0
        from rangedca import backtest
        backtest.run_server(days=a.days, gt=a.gt)
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
