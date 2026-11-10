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
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DETECT_EVERY_S = 290   # "recomputed every 5 min" (a pass a minute; 10 s of slack for the pass's own run time)
PRUNE_EVERY_S = 3600


def _mode():
    try:
        from league import flags
        return flags.mode("range_dca")
    except Exception:  # noqa: BLE001 - unreadable flag: off
        return "off"


def _minimums_met(snap):
    return bool(snap and snap.get("bonded", True) and (snap.get("mcap") or 0) >= 30_000 and (snap.get("liq") or 0) >= 20_000
                and (snap.get("vol_h1") or 0) >= 10_000)


def once(now=None, log=print, fetch=None, gt_fetch=None, post=None, extra=()):
    """One pass. Returns a short summary text ("off" when the flag is off)."""
    if _mode() == "off":
        return "off"
    from rangedca import data, detect, holders, rules
    now = int(now or time.time())
    con = data.connect()
    try:
        cands = data.candidates(con, now, extra)
        pools = {r[0] for r in con.execute("SELECT token FROM pools")}
        pulse = data.pulse_recent(now) - (set(cands) - pools)   # a token without a known pool is polled once for it
        data.poll(con, cands, now, fetch=fetch, pulse_fresh=pulse)
        full = now - (data.kv_get(con, "last_detect") or 0) >= DETECT_EVERY_S
        open_toks = set(data.open_round_tokens())
        seeds, n_act, n_ok = 0, 0, 0
        for tok in cands:
            prev, st = data.load_range(con, tok)
            if not full and not (prev and (prev.get("active") or tok in open_toks)):
                continue
            candles, snap = data.series(con, tok, now)
            if not candles:
                continue
            sym = (snap or {}).get("symbol") or (prev or {}).get("symbol")
            if full:
                res = detect.analyze(candles, now, snap)
                if (res["status"] == "premalo podataka" and seeds < data.GT_PER_PASS and _minimums_met(snap)
                        and (snap or {}).get("pool")):
                    if data.seed(con, tok, snap["pool"], now, fetch=gt_fetch):
                        seeds += 1
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
            data.save_range(con, tok, res, st, sym)
            n_act += int(bool(res.get("active")))
            n_ok += int(bool(res.get("active")) and (res.get("score") or 0) >= rules.RULES["score_min"])
        if full:
            data.kv_put(con, "last_detect", now)
        if now - (data.kv_get(con, "last_prune") or 0) >= PRUNE_EVERY_S:
            data.prune(con, now)
            _prune_holders(con, now, open_toks)
            data.kv_put(con, "last_prune", now)
        con.commit()
        text = (f"range: {len(cands)} kandidata, aktivnih {n_act}, ocjena >= {rules.RULES['score_min']}: {n_ok}; "
                f"GeckoTerminal danas {data.day_used(con, 'gt_day', now)}/{data.GT_DAY}, Helius danas "
                f"{data.day_used(con, 'helius_day', now)}/{holders.CREDITS_DAY} kredita")
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
    from rangedca import data
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
