"""What the providers themselves say was used this billing cycle (the source of truth; meter.py is our own count).

Helius: Admin API, needs HELIUS_PROJECT_ID (the id in the dashboard URL, dashboard.helius.dev/projects/<id>).
Docs: https://www.helius.dev/docs/api-reference/admin
Apify: GET /v2/users/me/limits (monthlyUsageUsd, maxMonthlyUsageUsd, monthlyUsageCycle).
"""
import datetime as dt
import json
import os
import time
import urllib.request


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _ts(s):
    if not s:
        return None
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int((d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp())


def helius():
    pid, key = os.environ.get("HELIUS_PROJECT_ID"), os.environ.get("HELIUS_API_KEY")
    if not (pid and key):
        return None
    d = _get(f"https://admin-api.helius.xyz/v0/admin/projects/{pid}/usage", {"X-Api-Key": key})
    cyc = d.get("creditCycle") or (d.get("subscriptionDetails") or {}).get("billingCycle") or {}
    lim = (d.get("subscriptionDetails") or {}).get("creditsLimit") or (d.get("creditsUsed", 0) + d.get("creditsRemaining", 0))
    return {"service": "helius", "used": d.get("creditsUsed") or 0, "lim": lim, "cycle_start": _ts(cyc.get("start")),
            "cycle_end": _ts(cyc.get("end")), "extra": {"credits": d.get("credits"), "requests": d.get("requests"),
                                                         "plan": (d.get("subscriptionDetails") or {}).get("plan"),
                                                         "remaining": d.get("creditsRemaining")}}


def apify():
    tok = os.environ.get("APIFY_TOKEN")
    if not tok:
        return None
    d = _get(f"https://api.apify.com/v2/users/me/limits?token={tok}")["data"]
    cyc = d.get("monthlyUsageCycle") or {}
    return {"service": "apify", "used": (d.get("current") or {}).get("monthlyUsageUsd") or 0,
            "lim": (d.get("limits") or {}).get("maxMonthlyUsageUsd") or 0, "cycle_start": _ts(cyc.get("startAt")),
            "cycle_end": _ts(cyc.get("endAt")), "extra": {}}


def snapshot(con):
    """Store one reading per service; returns {service: error text} for the ones that failed."""
    errs = {}
    for name, fn in (("helius", helius), ("apify", apify)):
        try:
            s = fn()
        except Exception as e:
            errs[name] = f"{type(e).__name__}: {e}"
            continue
        if s:
            con.execute("INSERT INTO account VALUES (?,?,?,?,?,?,?)", (int(time.time()), s["service"], s["used"], s["lim"],
                                                                     s["cycle_start"], s["cycle_end"], json.dumps(s["extra"])))
    con.commit()
    return errs
