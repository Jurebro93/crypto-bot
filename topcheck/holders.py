"""9.11. (audit P56): concentration facts in the pump.fun shape the pages already read (ui/confidence.holders_ok,
ui/evidence 'Holderi', ui/radar.risks), built from data the system already has: the RugCheck summary stored by
topcheck (top10 without pools, insiders, dev share) and the newest full rug filter row in rug.db (bundle and sniper
share). The Apify pump.fun source that used to fill extra.pumpfun has budget 0 since 7.11., so every token showed
"nema pump.fun podataka" although the numbers were paid for or free. Read-only; None when nothing is known, and a
field stays None when that source has no number (never a 0 that would read as "healthy")."""
import json
import os
import sqlite3

from topcheck import store

RUG_DB = os.environ.get("RUG_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rug.db"))

KEYS = ("top10HoldersPercent", "bundlerOwnedPercent", "snipersOwnedPercent", "devHoldingsPercent", "insidersPercent")


def _rug_rows(mints, path=None):
    """mint -> (bundle_pct, sniper_pct, top10_pct) of the newest rug.db report."""
    path = path or RUG_DB
    if not mints or not os.path.exists(path):
        return {}
    out = {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            for mint in mints:
                r = con.execute("SELECT bundle_pct, sniper_pct, top10_pct FROM rug_reports WHERE mint=? "
                                "ORDER BY checked_at DESC LIMIT 1", (mint,)).fetchone()
                if r:
                    out[mint] = r
        finally:
            con.close()
    except sqlite3.Error:
        return out
    return out


def pumpfun_shape(mints, tc=None, rug=None, rug_db=None, tc_db=None):
    """mint -> {top10HoldersPercent, bundlerOwnedPercent, snipersOwnedPercent, devHoldingsPercent, insidersPercent,
    'izvor': 'rugcheck'/'rug filter'...} for the mints something is known about. `tc` = topcheck.store.read_all()
    (read here when None), `rug` = mint -> (bundle, sniper, top10) (rug.db when None)."""
    mints = list(mints or ())
    if not mints:
        return {}
    tc = store.read_all(tc_db) if tc is None else tc
    rug = _rug_rows(mints, rug_db) if rug is None else rug
    out = {}
    for m in mints:
        rc = (tc.get(m) or {}).get("rc") or {}
        if isinstance(rc, str):
            try:
                rc = json.loads(rc) or {}
            except ValueError:
                rc = {}
        rr = rug.get(m) or (None, None, None)
        d = {"top10HoldersPercent": rc.get("top10") if rc.get("top10") is not None else rr[2],
             "bundlerOwnedPercent": rr[0], "snipersOwnedPercent": rr[1],
             "devHoldingsPercent": rc.get("dev_pct"), "insidersPercent": rc.get("insiders") if rc else None}
        if all(v is None for v in d.values()):
            continue
        src = [s for s, ok in (("RugCheck", bool(rc)), ("rug filter", m in rug)) if ok]
        d["izvor"] = " + ".join(src)
        out[m] = d
    return out
