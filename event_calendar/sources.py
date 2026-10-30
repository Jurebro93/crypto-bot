"""Event sources. Each returns a list of Event dicts:

    {"date": "YYYY-MM-DD", "title": str, "kind": str, "subject": str,
     "source": str, "url": str, "signals": {...}}

All sources are free and need no API key.
"""
import datetime as dt
import json
import os
import re
import time

from . import http

WIKI_FEED = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/{kind}/{mm:02d}/{dd:02d}"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
PAGEVIEWS = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
             "en.wikipedia/all-access/user/{title}/daily/{start}/{end}")
POLYMARKET = "https://gamma-api.polymarket.com/events"
LAUNCHES = "https://fdo.rocketlaunch.live/json/launches/next/5"
MANUAL_FILE = os.path.join(os.path.dirname(__file__), "events_manual.json")


def _days(start, days_ahead):
    return [start + dt.timedelta(days=i) for i in range(days_ahead + 1)]


def _sitelink_counts(qids, deadline=None):
    """Number of Wikipedia language editions per Wikidata item: a cheap fame proxy."""
    counts = {}
    for i in range(0, len(qids), 50):
        if deadline and time.monotonic() > deadline:
            break
        batch = qids[i:i + 50]
        data = http.get_json(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(batch),
                                            "props": "sitelinks", "format": "json"}, ttl=7 * 86400)
        for qid, ent in data.get("entities", {}).items():
            counts[qid] = len(ent.get("sitelinks", {}))
    return counts


def pageviews_30d(title, today):
    """Total and last-7-day English Wikipedia views; trend = last 7 days vs prior 23 days rate."""
    start = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
    end = (today - dt.timedelta(days=1)).strftime("%Y%m%d")
    url = PAGEVIEWS.format(title=title.replace(" ", "_"), start=start, end=end)
    try:
        items = http.get_json(url).get("items", [])
    except Exception:
        return {"views_30d": 0, "trend": 1.0}
    views = [it["views"] for it in items]
    if not views:
        return {"views_30d": 0, "trend": 1.0}
    last7, prior = views[-7:], views[:-7] or views
    trend = (sum(last7) / len(last7)) / max(1.0, sum(prior) / len(prior))
    return {"views_30d": sum(views), "trend": round(trend, 2)}


def wikipedia_anniversaries(start, days_ahead, min_sitelinks=60, kinds=("births", "deaths"),
                            max_days=14, recent_deaths_years=10, budget_s=90):
    """Birthdays and death anniversaries of well-known people in the window.

    Wikidata rate-limits hard, so: only the next `max_days` days (big names far ahead belong in
    events_manual.json), only deaths from the last `recent_deaths_years` years, one batched fame
    lookup for all days, and a 90 s budget after which it returns what it has.
    """
    t0 = time.monotonic()
    people = []  # (day, kind, item, page)
    for day in _days(start, min(days_ahead, max_days)):
        for kind in kinds:
            if time.monotonic() - t0 > budget_s:
                break
            # births/deaths per calendar day barely change: cache a week to spare Wikimedia's rate limit
            feed = http.get_json(WIKI_FEED.format(kind=kind, mm=day.month, dd=day.day), ttl=7 * 86400)
            for item in feed.get(kind, []):
                page = (item.get("pages") or [{}])[0]
                if not page.get("wikibase_item"):
                    continue
                if kind == "deaths" and int(item.get("year") or 0) < start.year - recent_deaths_years:
                    continue
                people.append((day, kind, item, page))
    fame = _sitelink_counts(sorted({p["wikibase_item"] for _, _, _, p in people}),
                            deadline=t0 + budget_s)
    events = []
    for day, kind, item, page in people:
        sl = fame.get(page["wikibase_item"], 0)
        if sl < min_sitelinks:
            continue
        name = page.get("normalizedtitle") or page.get("title", "").replace("_", " ")
        label = "birthday" if kind == "births" else "death anniversary"
        events.append({
            "date": day.isoformat(),
            "title": f"{name} {label} ({day.year - int(item.get('year', day.year))} yrs)",
            "kind": "birthday" if kind == "births" else "death_anniversary",
            "subject": name,
            "source": "wikipedia",
            "url": page.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "signals": {"sitelinks": sl, "wiki_title": page.get("title", ""),
                        "description": page.get("description", "")},
        })
    return events


# Single matches and recurring price/sport markets flood the list and never get their own memecoin.
PM_SKIP_TAGS = {"sports", "esports", "nba", "nfl", "soccer", "tennis", "hit-price", "crypto-prices",
                "finance-updown", "up-or-down"}


# Recurring markets that repeat weekly and never get a memecoin of their own.
PM_SKIP_TITLE = re.compile(r"(# ?tweets|\bprice\b|above _+|up or down|\bvs\.? |\bhit\b.*\b(in|on|by)\b|"
                           r"largest company|best ai model|AI company|temperature|\bBO\d\b)", re.I)
RELEASE_TITLE = re.compile(r"\b(release[ds]?|launch(es|ed)?|unveil(s|ed)?|announce[ds]?|reveal(s|ed)?|delay(ed)?)\b", re.I)


PM_LEAD = {"will", "who", "what", "which", "when", "how", "does", "is", "the", "next", "new"}
MONTH_WORDS = {"january", "february", "march", "april", "may", "june", "july", "august", "september",
               "october", "november", "december"}


def pm_subject(title):
    """First run of capitalised words, minus question words and months: 'Will Kanye West perform
    in Russia by October 31?' -> 'Kanye West'."""
    cap = r"\b[A-Z0-9][\w'.&-]*\b"
    for run in re.findall(rf"{cap}(?:\s+(?:of|de|the|and)\s+{cap}|\s+{cap})*", title):
        if run.isdigit():
            continue
        words = [w for w in run.split() if w.lower() not in PM_LEAD | MONTH_WORDS]
        if words:
            return " ".join(words)
    return title


def polymarket_events(start, days_ahead, limit=100, min_volume=250_000):
    """Open Polymarket events resolving in the window, highest volume first (sports and price markets skipped)."""
    end = start + dt.timedelta(days=days_ahead)
    data = http.get_json(POLYMARKET, {
        "closed": "false", "limit": limit, "order": "volume", "ascending": "false",
        "end_date_min": f"{start.isoformat()}T00:00:00Z", "end_date_max": f"{end.isoformat()}T23:59:59Z",
    })
    events = []
    for ev in data if isinstance(data, list) else data.get("data", []):
        end_date = (ev.get("endDate") or "")[:10]
        tags = {t.get("slug") for t in ev.get("tags") or []}
        if (not end_date or tags & PM_SKIP_TAGS or float(ev.get("volume") or 0) < min_volume
                or PM_SKIP_TITLE.search(ev.get("title", ""))):
            continue
        events.append({
            "date": end_date,
            "title": ev.get("title", ""),
            # "GTA VI released by ...?" -> the end date is a deadline, not the event day
            "kind": "launch_deadline" if RELEASE_TITLE.search(ev.get("title", "")) else "prediction_market",
            # proper nouns only, so keywords are names rather than "WILL", "TIMES"
            "subject": pm_subject(ev.get("title", "")),
            "source": "polymarket",
            "url": f"https://polymarket.com/event/{ev.get('slug', '')}",
            "signals": {"pm_volume": float(ev.get("volume") or 0), "pm_volume_24h": float(ev.get("volume24hr") or 0),
                        "pm_tags": sorted(t for t in tags if t)},
        })
    return events


def rocket_launches(start, days_ahead):
    data = http.get_json(LAUNCHES)
    end = start + dt.timedelta(days=days_ahead)
    events = []
    for l in data.get("result", []):
        ts = l.get("sort_date")
        if not ts:
            continue
        day = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date()
        if not start <= day <= end:
            continue
        provider = (l.get("provider") or {}).get("name", "")
        events.append({
            "date": day.isoformat(),
            "title": f"{provider} {l.get('name', '')} launch".strip(),
            "kind": "rocket_launch",
            "subject": f"{provider} {l.get('name', '')}".strip(),
            "source": "rocketlaunch.live",
            "url": f"https://www.rocketlaunch.live/launch/{l.get('slug', '')}",
            "signals": {},
        })
    return events


def manual_events(start, days_ahead, path=MANUAL_FILE):
    """Hand-curated events. "recurring": true repeats every year on MM-DD."""
    with open(path) as f:
        items = json.load(f)
    end = start + dt.timedelta(days=days_ahead)
    events = []
    for it in items:
        if not it.get("date"):
            continue  # date not known yet (e.g. product launch "TBD")
        if it.get("recurring"):
            mm, dd = map(int, it["date"][-5:].split("-"))
            dates = [dt.date(y, mm, dd) for y in (start.year, start.year + 1)]
        else:
            dates = [dt.date.fromisoformat(it["date"])]
        for d in dates:
            if start <= d <= end:
                events.append({
                    "date": d.isoformat(), "title": it["title"], "kind": it.get("kind", "manual"),
                    "subject": it.get("subject", it["title"]), "source": "manual",
                    "url": it.get("url", ""), "signals": {"keywords": it.get("keywords", [])},
                })
    return events
