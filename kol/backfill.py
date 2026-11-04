"""One-off history for the KOL database, so call power does not need weeks of live data.

Phase "tokens": for tokens from the retrospective (winners and a same-size sample of tokens that did not pump),
search X for posts with the CA between launch and one day after the peak. Sort "Top" surfaces the accounts
with reach. Phase "timelines": then the full recent timelines of the KOLs found, so their stats include the
calls that went nowhere (searching only winners would make every caller look good).

Prices come from measure.run (GeckoTerminal 5-min candles), as for live calls. Spend goes through hype/apify.py
as source "kol_backfill" with the budget given on the command line.
"""
import datetime as dt
import random
import time

from hype.apify import BudgetExceeded

from kol import collect

ACTOR = collect.X_ACTOR


def _day(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def token_query(mint, launch_ts, peak_ts):
    end = max(peak_ts or launch_ts, launch_ts) + 86400
    return f"{mint} since:{_day(launch_ts)} until:{_day(end + 86400)}"


def pick(tokens, n_win, n_lose, seed=7):
    """tokens: [{mint, launch_ts, peak_ts, winner}] -> winners (biggest first) + random non-winners."""
    win = sorted([t for t in tokens if t["winner"]], key=lambda t: -(t.get("peak_mult") or 0))[:n_win]
    lose = [t for t in tokens if not t["winner"]]
    random.Random(seed).shuffle(lose)
    return win + lose[:n_lose]


def tokens_from_db(con, win_x=1.0, max_age_d=90, now=None):
    """Backfill token list from kol.db itself, when there is no retrospective file (5.11., on the server): every token
    with measured calls. launch = tokens.created_ts (else a day before its first call), peak = the time of the highest
    DexScreener snapshot (kol/snap.py) if there is one, else a day after the first call; winner = some call's best
    move within 24 h reached win_x (+100% by default). Searching X for these CAs finds the OTHER accounts that posted
    them, which is what call groups and pair tests need."""
    now = now or int(time.time())
    rows = con.execute("""SELECT c.token, MIN(c.ts), MAX(c.max24), t.created_ts, t.symbol FROM calls c
                          LEFT JOIN tokens t ON t.token = c.token
                          WHERE c.max24 IS NOT NULL AND c.bad IS NULL AND c.ts >= ? GROUP BY c.token""",
                       (now - max_age_d * 86400,)).fetchall()
    peak = {}
    for tok, ts, px in con.execute("SELECT token, ts, price FROM snaps WHERE price > 0 ORDER BY token, ts"):
        if tok not in peak or px > peak[tok][1]:
            peak[tok] = (ts, px)
    out = []
    for tok, first, best, created, sym in rows:
        launch = created or first - 86400
        out.append({"mint": tok, "symbol": sym, "launch_ts": int(launch), "peak_ts": int(peak.get(tok, (first + 86400,))[0]),
                    "peak_mult": 1 + best, "winner": best >= win_x})
    return out


def done_targets(con, kind):
    return {r[0] for r in con.execute("SELECT target FROM searches WHERE kind = ?", (kind,))}


def search_tokens(con, tokens, run, max_items=20, log=print):
    """One Apify run per token. Returns new calls."""
    seen = done_targets(con, "backfill_token")
    run, n = _safe(run, log), 0
    for i, t in enumerate(tokens):
        if t["mint"] in seen:
            continue
        items = run("kol_backfill", ACTOR, {"searchTerms": [token_query(t["mint"], t["launch_ts"], t.get("peak_ts"))],
                                            "maxItems": max_items, "sort": "Top"})
        k = collect.save(con, [c for it in items for c in collect.calls_from_tweet(it, t["mint"], t.get("symbol"),
                                                                                    "backfill")])
        con.execute("INSERT OR REPLACE INTO searches VALUES (?,?,?,1)", (t["mint"], "backfill_token", int(time.time())))
        con.commit()
        n += k
        if i % 25 == 0:
            log(f"  tokeni {i + 1}/{len(tokens)}: {n} novih poziva")
    return n


def top_handles(con, limit, min_followers=1000):
    """KOLs worth a timeline: most distinct tokens called, then followers."""
    return [r[0] for r in con.execute("""
        SELECT c.handle FROM calls c JOIN kols k ON k.handle = c.handle
        WHERE c.kind = 'call' AND COALESCE(k.followers, 0) >= ?
        GROUP BY c.handle ORDER BY COUNT(DISTINCT c.token) DESC, MAX(k.followers) DESC LIMIT ?""",
                                      (min_followers, limit))]


def search_timelines(con, handles, run, since_ts, max_items=100, log=print):
    seen = done_targets(con, "backfill_timeline")
    run, n = _safe(run, log), 0
    for i, h in enumerate(handles):
        if h in seen:
            continue
        items = run("kol_backfill", ACTOR, {"searchTerms": [f"from:{h} since:{_day(since_ts)}"],
                                            "maxItems": max_items, "sort": "Latest"})
        k = collect.save(con, [c for it in items for c in collect.calls_from_tweet(it, source="backfill_timeline")])
        con.execute("INSERT OR REPLACE INTO searches VALUES (?,?,?,1)", (h, "backfill_timeline", int(time.time())))
        con.commit()
        n += k
        if i % 10 == 0:
            log(f"  timelineovi {i + 1}/{len(handles)}: {n} novih poziva")
    return n


def _safe(run, log):
    """run() that retries a network error once and then skips the target instead of ending a night's backfill."""
    def call(*args, **kw):
        for attempt in range(2):
            try:
                return run(*args, **kw)
            except BudgetExceeded:
                raise
            except Exception as e:
                log(f"  greška ({type(e).__name__}: {e}), {'ponavljam' if attempt == 0 else 'preskačem'}")
                time.sleep(10)
        return []
    return call
