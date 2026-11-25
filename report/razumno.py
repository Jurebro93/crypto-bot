"""25.11. (vlasnik, jutarnji izvještaj: „Prvih 20 po ocjeni ... prosjek +48693144406.11 %, zbroj +88864988541.15 SOL"):
the guard every table of the report and /strategije passes a row of trade statistics through before it prints a
number. A row whose average, median or interval bound per trade is beyond PCT_MAX, or whose sum in SOL is more than
the stake could ever have returned at that bound, is not a result but broken data: the renderers print „sumnjivi
podaci, red izostavljen" and the trade count instead of the number, and a single percentage or SOL amount beyond the
bounds gets the mark SUMNJIVO next to it (pp / sol in report/render.py).

The bound is on a ROW (the average over its trades), not on a single trade: one real memecoin trade of +800 % passes
everywhere; an average of +1000 % a trade over 30+ copies is not a copier's result. The data module that computes the
row (wallets/kopija.py) drops single trades by the quality of their prices; this is the last line before the reader."""
import math

PCT_MAX = 1000.0     # % a trade: an average / median / interval bound beyond this is broken data, not a result
SOL_MAX = 100.0      # SOL: a single sum beyond this from 0.1 SOL stakes is broken data (the wallet holds a few SOL)
MARK = "SUMNJIVO"
OMIT = "sumnjivi podaci, red izostavljen"


def _bad(x, lim):
    return x is not None and (not isinstance(x, (int, float)) or not math.isfinite(x) or abs(x) > lim)


def sumnja(r, ulog=0.1):
    """None for a plausible row, else the reason (Croatian) why its numbers cannot be real. r: {"n", "ev_pct",
    "med_pct" | "medijan_pct", "ci" | "ci90", "zbroj_sol" | "sum_sol"} (any may be missing)."""
    if not r:
        return None
    for k in ("ev_pct", "med_pct", "medijan_pct"):
        if _bad(r.get(k), PCT_MAX):
            return f"prosjek ili medijan izvan ±{PCT_MAX:.0f} % po tradeu"
    ci = r.get("ci") or r.get("ci90")
    if ci and any(_bad(x, PCT_MAX) for x in ci if x is not None):
        return f"granica intervala izvan ±{PCT_MAX:.0f} %"
    s = r.get("zbroj_sol", r.get("sum_sol"))
    n = r.get("n") or 0
    if s is not None and (_bad(s, SOL_MAX) or abs(s) > max(1, n) * (ulog or 0.1) * PCT_MAX / 100):
        return "zbroj u SOL veći nego što ulog može vratiti"
    return None


def omit_text(r):
    """„sumnjivi podaci, red izostavljen (n tradeova)"."""
    return f"{OMIT} ({(r or {}).get('n') or 0} tradeova)"


def pct_ok(x):
    return not _bad(x, PCT_MAX)


def sol_ok(x):
    return not _bad(x, SOL_MAX)
