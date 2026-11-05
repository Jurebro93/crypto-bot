"""5.11. (Nicholas): a big account followed by other big accounts is a signal before it has any measured calls.
Reach = followers (kols.followers) + how many of OUR proven KOLs follow it (kol.db follows, kol/discover.graph).
It sets the starting score (prior) of an account with few measured calls: a nobody starts at prior_score, a big
account starts higher, and the measured calls take over as they come (kol/score shrinkage). It is also the
"Veliki račun zove" strategy's filter (strat/signals)."""
import math

DEFAULT = {"min_followers": 20000, "min_followed_by": 2, "prior_cap": 70, "big_followers": 100000}


def config(cfg):
    return {**DEFAULT, **((cfg or {}).get("reach") or {})}


def followed_by(con):
    """{handle (lower): number of distinct proven KOLs that follow it} from the follow graph."""
    try:
        return {h.lower(): n for h, n in con.execute("SELECT dst, COUNT(DISTINCT src) FROM follows GROUP BY LOWER(dst)")}
    except Exception:  # noqa: BLE001 - no follows table yet
        return {}


def prior(base, followers, fb, cfg=None):
    """Starting score for an account by reach: base + up to +15 for followers (log scale from 5k) + up to +15 for
    being followed by proven KOLs (2 -> +8, 5+ -> +15), capped at prior_cap."""
    c = config(cfg)
    f = followers or 0
    bonus = 0.0
    if f >= 5000:
        bonus += min(15.0, 15.0 * (math.log10(f) - math.log10(5000)) / (math.log10(c["big_followers"] * 5) - math.log10(5000)))
    if fb >= c["min_followed_by"]:
        bonus += min(15.0, 8.0 + 7.0 * (fb - c["min_followed_by"]) / 3)
    return round(min(c["prior_cap"], base + bonus), 1)


def is_big(followers, fb, cfg=None):
    c = config(cfg)
    return (followers or 0) >= c["min_followers"] and fb >= c["min_followed_by"]
