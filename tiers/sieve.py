"""T0: the free sieve. Fails a token only for rug mechanics the dev can pull in one move: an active mint or
freeze authority, or LP that is neither locked nor burned outside a launchpad curve. Liquidity, holders, dev share
and bundlers are features for the learning loop, never hard cuts here."""
import time

from tiers.classify import config


def pumpfun(mint, cfg=None):
    """pump.fun mints end in 'pump': authorities are revoked by the program and LP sits on the curve."""
    return mint.endswith((cfg or config())["t0"]["pumpfun_suffix"])


def verdict_from_report(rc, cfg=None):
    """('prolaz'|'pad', reason) from a RugCheck report dict."""
    cfg = cfg or config()
    if not rc:
        return "prolaz", "RugCheck nije odgovorio; nema dokaza o mehanici ruga"
    if rc.get("rugged"):
        return "pad", "RugCheck: token je već rugan"
    bad = []
    if rc.get("mintAuthority"):
        bad.append("aktivan mint authority")
    if rc.get("freezeAuthority"):
        bad.append("aktivan freeze authority")
    launchpad = ((rc.get("launchpad") or {}).get("name") or "").lower()
    if not launchpad:
        lps = [(m.get("lp") or {}).get("lpLockedPct") for m in rc.get("markets") or []]
        lps = [x for x in lps if x is not None]
        if lps and max(lps) < cfg["t0"]["lp_locked_min_pct"]:
            bad.append(f"LP zaključan samo {max(lps):.0f}%")
    if bad:
        return "pad", ", ".join(bad)
    return "prolaz", "authority povučen" + (", LP zaključan" if rc.get("markets") else "")


def check(mint, cfg=None, report=None):
    """(t0, reason). pump.fun tokens pass without a network call; others ask RugCheck (cached 6 h)."""
    cfg = cfg or config()
    if pumpfun(mint, cfg):
        return "prolaz", "pump.fun: authority povučen programom"
    if report is None:
        try:
            from rugfilter import rugcheck
            report = rugcheck.report(mint, ttl=21600)
        except Exception as e:  # one dead source must not stop the scan
            return "prolaz", f"RugCheck greška ({type(e).__name__}); propušten bez dokaza"
    return verdict_from_report(report, cfg)


def needs_check(row, cfg=None, now=None):
    cfg = cfg or config()
    if not row or not row.get("t0") or row["t0"] == "nije":
        return True
    return (now or time.time()) - (row.get("t0_ts") or 0) > cfg["t0"]["recheck_h"] * 3600
