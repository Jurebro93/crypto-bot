"""Night backfill of calls that were never measured (10.11., Grok MCP audit 6: get_caller_history had no price 24 h
after the call for 79 of one caller's 83 calls).

Why they are missing: kol/measure.due() serves the NEWEST calls first, at most measure_tokens_per_run tokens a round,
and re-measures young calls at their 1 h / 6 h / 24 h checkpoints. On a busy day the free GeckoTerminal budget goes to
the fresh calls and an older call that missed its first rounds is never reached; kol/snap.py covers only calls younger
than 25 h (DexScreener snapshots are kept 3 days). Such a call keeps measured_ts NULL and p0 / r1h / r24h / max24 NULL
for good, and without a resolved pool (kol.db tokens.pair) the minute check (kol/minute.candidates) never takes it
either.

This job takes those calls, newest first among the ones whose 24 h checkpoint has passed (the young ones stay with
kol/measure), and measures them with the same code: kol/measure._run (DexScreener pair resolve + one GeckoTerminal
5-minute OHLCV request per token, outcome(), why_bad()). Nothing new is paid for: the free GeckoTerminal API, or the
CoinGecko key when event_calendar/http has one (then every request counts against the paid day, hence the caps).

Limits (CLAUDE.md: heavy jobs only 01-06 CET; spend measured before it grows):
  - runs only inside the night window (ops/heavy.NIGHT, Zagreb 01-06) unless force=True
  - at most `budget` tokens (= OHLCV requests) a run and NIGHT_CAP a night (kol.db kv backfill_calls_night)
  - holds GeckoTerminal (event_calendar/http.reserve) for its run only, like kol/measure.run
  - only real calls (kind 'call', no wallet pseudo-calls, no alert bots), at most MAX_AGE_D days old

Run:  python3 kol/backfill_calls.py [--budget 60] [--force]      (or: python3 -m kol.backfill_calls)
Schedule (run_sched.py JOBS, heavy lock, night only):
  ("kolfill", every, (["kol/backfill_calls.py", "--budget", "60"], 60, False, True)),
"""
import datetime as dt
import json
import os
import sys
import time

if __name__ == "__main__":   # run as a file: the repo root on the path, not kol/
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path = [_ROOT] + [p for p in sys.path if os.path.abspath(p or ".") != os.path.dirname(os.path.abspath(__file__))]

H = 3600
DEFAULT_BUDGET = 60      # tokens (one GeckoTerminal OHLCV request each) per run
NIGHT_CAP = 300          # requests a night; kol/minute's own night work takes up to 600 (its night_requests)
MIN_AGE_S = 25 * H       # younger calls are kol/measure's normal queue (checkpoints at 1 h / 6 h / 24 h)
MAX_AGE_D = 60           # older pools are mostly gone from GeckoTerminal; not worth a request
BUDGET_S = 600           # wall-clock limit of one run
KV_KEY = "backfill_calls_night"
TZ = "Europe/Zagreb"


def night_now(now=None):
    """Inside the heavy-job night window (ops/heavy.NIGHT, default 01-06 Zagreb)."""
    try:
        from ops import heavy
        return heavy.night_now(dt.datetime.fromtimestamp(now, dt.timezone.utc) if now else None)
    except Exception:  # noqa: BLE001 - ops/ missing (a copy of kol/): the CLAUDE.md window itself
        from zoneinfo import ZoneInfo
        h = dt.datetime.fromtimestamp(now or time.time(), ZoneInfo(TZ)).hour
        return 1 <= h < 6


def _night_key(now):
    """The date of the night (Zagreb): 01:00-06:00 belongs to that morning's date."""
    from zoneinfo import ZoneInfo
    return dt.datetime.fromtimestamp(now, ZoneInfo(TZ)).date().isoformat()


def night_used(con, now):
    try:
        r = con.execute("SELECT value FROM kv WHERE key=?", (KV_KEY,)).fetchone()
        d = json.loads(r[0]) if r else {}
    except Exception:  # noqa: BLE001
        d = {}
    return int(d.get("n") or 0) if d.get("day") == _night_key(now) else 0


def _spend(con, now, n):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)",
                (KV_KEY, json.dumps({"day": _night_key(now), "n": night_used(con, now) + n})))
    con.commit()


def due(con, now, limit, max_age_d=MAX_AGE_D):
    """Tokens with real calls that were never measured (no measure, no price at the call, not given up) and whose 24 h
    checkpoint has passed, newest first, at most `limit`."""
    if limit <= 0:
        return []
    return [r[0] for r in con.execute("""
        SELECT c.token FROM calls c LEFT JOIN kols k ON k.handle = c.handle
         WHERE c.kind = 'call' AND c.handle NOT LIKE 'w:%' AND COALESCE(k.bot, 0) = 0
           AND COALESCE(c.complete, 0) = 0 AND c.measured_ts IS NULL AND c.p0 IS NULL
           AND COALESCE(c.mtry, 0) <= :now AND c.ts BETWEEN :lo AND :hi
         GROUP BY c.token ORDER BY MAX(c.ts) DESC LIMIT :lim""",
                                      {"now": now, "lo": now - max_age_d * 86400, "hi": now - MIN_AGE_S, "lim": limit})]


def waiting(con, now, max_age_d=MAX_AGE_D):
    """How many such calls wait (for the log line and the page)."""
    return con.execute("""SELECT COUNT(*) FROM calls WHERE kind = 'call' AND handle NOT LIKE 'w:%'
        AND COALESCE(complete, 0) = 0 AND measured_ts IS NULL AND p0 IS NULL AND ts BETWEEN ? AND ?""",
                       (now - max_age_d * 86400, now - MIN_AGE_S)).fetchone()[0]


def run(budget=DEFAULT_BUDGET, con=None, cfg=None, now=None, fetch=None, force=False, log=print):
    """One capped pass. Returns {"ran", "why", "tokens", "calls", "requests", "left"}; never raises on an empty queue
    or outside the night (ran False with the reason)."""
    from kol import measure, store
    from event_calendar import http
    now = int(now or time.time())
    if not force and not night_now(now):
        return {"ran": False, "why": "izvan noćnog prozora (01-06 Zagreb)", "tokens": 0, "calls": 0, "requests": 0}
    own = con is None
    con = con or store.connect()
    try:
        if cfg is None:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as f:
                cfg = json.load(f)
        left = NIGHT_CAP - night_used(con, now)
        n = max(0, min(int(budget or 0), left))
        if n <= 0:
            return {"ran": False, "why": f"noćni strop {NIGHT_CAP} zahtjeva potrošen", "tokens": 0, "calls": 0,
                    "requests": 0}
        toks = due(con, now, n)
        if not toks:
            return {"ran": False, "why": "nema neizmjerenih poziva", "tokens": 0, "calls": 0, "requests": 0}
        fetch = fetch or measure.ohlcv
        live = fetch is measure.ohlcv
        if live and http.cooling(measure.GECKO) > 30:
            return {"ran": False, "why": "GeckoTerminal je zauzet (drugi posao ili 429)", "tokens": 0, "calls": 0,
                    "requests": 0}
        if live:
            http.reserve(measure.GECKO, BUDGET_S)
        try:
            n_tok, n_calls = measure._run(con, cfg, now, fetch, False, time.monotonic() + BUDGET_S, toks)
        finally:
            if live:
                http.release(measure.GECKO)
        # every token asked for counts against the night, measured or not (a 404 or an empty answer cost a request too)
        _spend(con, now, len(toks))
        out = {"ran": True, "why": "", "tokens": n_tok, "calls": n_calls, "requests": len(toks),
               "left": waiting(con, now)}
        log(f"kol backfill: {n_tok}/{len(toks)} tokena, {n_calls} poziva izmjereno; čeka još {out['left']}; "
            f"noćas {night_used(con, now)}/{NIGHT_CAP} zahtjeva")
        return out
    finally:
        if own:
            con.close()


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Noćno mjerenje poziva koji nikad nisu izmjereni (kol.db calls).")
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="najviše tokena (GeckoTerminal zahtjeva) po krugu")
    p.add_argument("--force", action="store_true", help="i izvan noćnog prozora (ručno)")
    a = p.parse_args(argv)
    out = run(a.budget, force=a.force)
    if not out["ran"]:
        print(f"kol backfill: preskočeno ({out['why']})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
