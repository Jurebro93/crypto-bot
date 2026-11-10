#!/usr/bin/env python3
"""Skener tržišta (scan/, flag market_scan, G11): tokens found without a caller, measured in shadow.

    python3 run_scan.py once     # one pass (start.sh: every SCAN_EVERY_S, default 150 s); flag off: ends at once
    python3 run_scan.py stats    # per source (caller, wallet, scan, beta): shadow outcomes, EV, the paper gate (JSON)

A short process per pass (its memory goes back when it ends). It never buys, in any mode: it writes scan.db and the
xfeat.db x_momentum rows; get_market_signals, the MCP tool get_source_stats and the daily report read them.
"""
import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("once", "stats"))
    a = ap.parse_args(argv)
    if a.cmd == "stats":
        from scan import shadow
        print(json.dumps(shadow.report_data(), ensure_ascii=False, indent=1))
        return 0
    from scan import market
    out = market.pass_once()
    if out.get("off"):
        return 0   # flag off: nothing read, nothing written, nothing logged
    if not (any(out["passed"].values()) or out["finished"] or out["credits"] or out["x_usd"] or out["gt"]):
        return 0   # a quiet pass (every 150 s) leaves no line; the cap messages are logged where they happen
    passed = ", ".join(f"{k} {v}" for k, v in sorted(out["passed"].items()) if v) or "nitko"
    market.log(f"{out['candidates']} kandidata, provjereno {out['checked']}, u sjenu: {passed}; Helius "
               f"{out['credits']} kr., GeckoTerminal {out['gt']} poziva, X {out['x_usd']:.4f} $; zatvoreno ishoda "
               f"{out['finished']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
