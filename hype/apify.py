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


_month = {"ts": 0, "usage": 0.0, "cap": 0.0}


def monthly():
    """(used_usd, cap_usd) for the account this billing cycle, cached 10 min."""
    if time.time() - _month["ts"] > 600:
        d = _api("/users/me/limits")["data"]
        _month.update(ts=time.time(), usage=d["current"].get("monthlyUsageUsd") or 0,
                      cap=d["limits"].get("maxMonthlyUsageUsd") or 0)
    return _month["usage"], _month["cap"]


def check(source):
    cfg = config()
    budget = cfg["daily_usd"].get(source, 0)
    if spent(source) >= budget:
        raise BudgetExceeded(f"{source}: dnevni budžet ${budget} potrošen")
    used, cap = monthly()
    if cap and used >= cap - cfg.get("monthly_reserve_usd", 3):
        raise BudgetExceeded(f"Apify račun: ${used:.2f} od ${cap:.0f} ovaj mjesec, čuvam rezervu")


def run(source, actor, actor_input, cache_secs=0, max_usd=None, wait=60, max_wait=180):
    """Dataset items of one actor run, or the cached items of an identical call within cache_secs."""
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
    cost = (r.get("usageTotalUsd") or 0) + unit * (1 if source == "gmgn" else len(items))
    con = _db()
    con.execute("INSERT INTO apify_runs VALUES (?,?,?,?,?,?,?)",
                (int(time.time()), source, actor, r["id"], len(items), cost, r["status"]))
    con.execute("INSERT OR REPLACE INTO apify_cache VALUES (?,?,?)", (key, int(time.time()), json.dumps(items)))
    con.commit()
    con.close()
    if r["status"] != "SUCCEEDED" and not items:
        raise RuntimeError(f"{actor}: {r['status']}")
    return items
