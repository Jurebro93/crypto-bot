"""Apify actors behind one budget guard.

Every run goes through `run()`: it refuses when today's spend for that source is over its daily budget
(hype/apify.json) or the account is near its monthly cap, records the real cost Apify reports, and caches
results per source so a fast `watch` loop does not pay twice.
"""
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request

API = "https://api.apify.com/v2"
CONFIG = os.path.join(os.path.dirname(__file__), "apify.json")
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hype.db")


class BudgetExceeded(Exception):
    pass


def enabled():
    return bool(os.environ.get("APIFY_TOKEN"))


def config():
    with open(CONFIG) as f:
        return json.load(f)


def _api(path, body=None, params=None, timeout=60):
    params = {"token": os.environ["APIFY_TOKEN"], **(params or {})}
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _db():
    con = sqlite3.connect(DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS apify_runs (
        ts INTEGER, source TEXT, actor TEXT, run_id TEXT, items INTEGER, cost_usd REAL, status TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS apify_cache (key TEXT PRIMARY KEY, ts INTEGER, items TEXT)")
    return con


def spent(source=None, since=None):
    since = since or time.time() - 86400
    con = _db()
    sql, args = "SELECT COALESCE(SUM(cost_usd), 0) FROM apify_runs WHERE ts >= ?", [since]
    if source:
        sql, args = sql + " AND source = ?", args + [source]
    v = con.execute(sql, args).fetchone()[0]
    con.close()
    return v


_month = {"ts": 0, "usage": 0.0, "cap": 0.0, "end": 0}


def _cycle_end(d):
    try:
        import datetime as dt
        s = ((d.get("monthlyUsageCycle") or {}).get("endAt") or "").replace("Z", "+00:00")
        return int(dt.datetime.fromisoformat(s).timestamp()) if s else 0
    except ValueError:
        return 0


def monthly():
    """(used_usd, cap_usd) for the account this billing cycle, cached 10 min."""
    if time.time() - _month["ts"] > 600:
        d = _api("/users/me/limits")["data"]
        _month.update(ts=time.time(), usage=d["current"].get("monthlyUsageUsd") or 0,
                      cap=d["limits"].get("maxMonthlyUsageUsd") or 0, end=_cycle_end(d))
    return _month["usage"], _month["cap"]


def pace_factor(cfg=None, used=None, cap=None, end=None, now=None):
    """Share (0-1) of the normal daily budget the throttled sources may use today, so the money left lasts until
    the cycle resets: (cap - reserve - used) / days left, against the sum of all daily budgets. 1 = no throttle."""
    cfg = cfg or config()
    if used is None:
        used, cap = monthly()
        end = _month["end"]
    now = now or time.time()
    if not cap or not end or end <= now:
        return 1.0
    allowed = max(0.0, cap - cfg.get("monthly_reserve_usd", 3) - used) / max(0.5, (end - now) / 86400)
    planned = sum(cfg["daily_usd"].values()) or 1
    return max(0.0, min(1.0, allowed / planned))


def off(source, cfg=None):
    """11.11.: why a source is switched off in hype/apify.json "ugaseno" (None = it runs). Reversible: delete the line."""
    try:
        return ((cfg or config()).get("ugaseno") or {}).get(source)
    except (OSError, ValueError):
        return None


def status_line(cfg=None):
    """One line for the start of the server log: which Apify sources are off and why, and which stay on and why."""
    cfg = cfg or config()
    off_ = cfg.get("ugaseno") or {}
    kept = cfg.get("zadrzano") or {}
    parts = [f"ugašeno {k}: {v}" for k, v in off_.items()] + [f"ostaje {k}: {v}" for k, v in kept.items()]
    return "apify: " + (" | ".join(parts) if parts else "svi izvori po dnevnim budžetima (hype/apify.json)")


def check(source):
    cfg = config()
    why = off(source, cfg)
    if why:
        raise BudgetExceeded(f"{source}: ugašeno u hype/apify.json ({why[:80]})")
    budget = cfg["daily_usd"].get(source, 0)
    if spent(source) >= budget:
        raise BudgetExceeded(f"{source}: dnevni budžet ${budget} potrošen")
    used, cap = monthly()
    if cap and used >= cap - cfg.get("monthly_reserve_usd", 3):
        raise BudgetExceeded(f"Apify račun: ${used:.2f} od ${cap:.0f} ovaj mjesec, čuvam rezervu")
    # automatic brake: when the month's money would not last at the normal daily budgets, the costly scanner checks
    # (X buzz, trends, pump.fun boards, GMGN) get a smaller daily budget; KOL tracking (and with it the KOL test) keeps its own
    if source not in cfg.get("bez_kocnice", []):
        k = pace_factor(cfg, used, cap, _month["end"])
        if k < 1 and spent(source) >= budget * k:
            raise BudgetExceeded(f"{source}: kočnica tempa, danas smije {k:.0%} dnevnog budžeta da novac potraje do kraja ciklusa")


def run(source, actor, actor_input, cache_secs=0, max_usd=None, wait=60, max_wait=180, units=None):
    """Dataset items of one actor run, or the cached items of an identical call within cache_secs.
    units: how many priced events the run charges when that is not one per result (monitor hours)."""
    key = f"{source}:{actor}:{json.dumps(actor_input, sort_keys=True)}"
    con = _db()
    hit = con.execute("SELECT ts, items FROM apify_cache WHERE key = ?", (key,)).fetchone()
    con.close()
    if hit and time.time() - hit[0] < cache_secs:
        return json.loads(hit[1])
    check(source)
    params = {"waitForFinish": wait, **config().get("run_options", {}).get(source, {})}  # memory/timeout cap compute
    if max_usd:
        params["maxTotalChargeUsd"] = max_usd
    r = _api(f"/acts/{actor.replace('/', '~')}/runs", actor_input, params, timeout=wait + 30)["data"]
    deadline = time.time() + max_wait
    while r["status"] in ("READY", "RUNNING"):  # waitForFinish caps at 60 s on some plans
        if time.time() > deadline:  # a slow actor must not stall the scan; keep what it saved so far
            r = _api(f"/actor-runs/{r['id']}/abort", {})["data"]
            break
        time.sleep(5)
        r = _api(f"/actor-runs/{r['id']}")["data"]
    items = _api(f"/datasets/{r['defaultDatasetId']}/items", params={"clean": "true", "format": "json"})
    # PPE charges are not in the run object; estimate from the per-result price, plus platform usage
    unit = config().get("unit_usd", {}).get(source, 0)
    cost = (r.get("usageTotalUsd") or 0) + unit * (units if units is not None else 1 if source == "gmgn" else len(items))
    con = _db()
    con.execute("INSERT INTO apify_runs VALUES (?,?,?,?,?,?,?)",
                (int(time.time()), source, actor, r["id"], len(items), cost, r["status"]))
    from ops import disk
    if not disk.low("sirovi Apify odgovor"):   # raw answer only; spend (apify_runs) is always recorded
        con.execute("INSERT OR REPLACE INTO apify_cache VALUES (?,?,?)", (key, int(time.time()), json.dumps(items)))
    con.commit()
    con.close()
    try:
        from usage import meter
        meter.record("apify", source, cost)
    except ImportError:
        pass
    if r["status"] != "SUCCEEDED" and not items:
        raise RuntimeError(f"{actor}: {r['status']}")
    return items


if __name__ == "__main__":   # start.sh: python3 -m hype.apify (one line: what is off and why)
    print(status_line(), flush=True)
