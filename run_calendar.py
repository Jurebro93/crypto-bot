#!/usr/bin/env python3
"""Upcoming-event calendar for memecoin research.

    python3 run_calendar.py --days 14 --top 30

Writes output/calendar-YYYY-MM-DD.md and .json, and upserts events into calendar.db (SQLite).
Each source is optional: if one fails (network, rate limit) the rest still run.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time

from event_calendar import discovery, enrich, sources

HERE = os.path.dirname(os.path.abspath(__file__))
TIMINGS = {}  # seconds per source, printed to stderr


def collect(start, days, min_sitelinks):
    jobs = {
        "manual": lambda: sources.manual_events(start, days),
        "wikipedia": lambda: sources.wikipedia_anniversaries(start, days, min_sitelinks),
        "polymarket": lambda: sources.polymarket_events(start, days),
        "launches": lambda: sources.rocket_launches(start, days),
        "viral_now": lambda: discovery.wikipedia_viral_now(start),
        "news": lambda: discovery.news_dates(start, days),
        "earthquakes": lambda: discovery.earthquakes(start),
        "asteroids": lambda: discovery.asteroids(start, days),
    }
    events, errors = [], {}
    for name, job in jobs.items():
        t0 = time.monotonic()
        try:
            events += job()
        except Exception as e:  # keep going with the other sources
            errors[name] = f"{type(e).__name__}: {e}"
        TIMINGS[name] = round(time.monotonic() - t0, 1)
    return events, errors


def dedupe(events):
    """Manual entries win over the same person/day from Wikipedia."""
    kept = {}
    for ev in sorted(events, key=lambda e: e["source"] != "manual"):
        key = (ev["date"], ev["kind"], ev["subject"].lower())
        if key in kept:  # keep the duplicate's signals (fame, pageviews)
            for k, v in ev["signals"].items():
                kept[key]["signals"].setdefault(k, v)
        else:
            kept[key] = ev
    return list(kept.values())


def enrich_all(events, today, pageviews_top):
    # Pageviews are one request per person, so only fetch them for the most famous.
    people = sorted((e for e in events if e["signals"].get("wiki_title") and "views_1d" not in e["signals"]),
                    key=lambda e: -e["signals"].get("sitelinks", 0))[:pageviews_top]
    for ev in people:
        ev["signals"].update(sources.pageviews_30d(ev["signals"]["wiki_title"], today))
    for ev in events:
        days_until = (dt.date.fromisoformat(ev["date"]) - today).days
        ev["days_until"] = days_until
        ev["keywords"] = enrich.keywords(ev)
        ev["token_likelihood"], ev["hype"] = enrich.event_score(ev, days_until)
    return sorted(events, key=lambda e: -e["hype"])


def save_db(events, path):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE IF NOT EXISTS events (
        date TEXT, kind TEXT, subject TEXT, title TEXT, source TEXT, url TEXT,
        keywords TEXT, hype REAL, signals TEXT, updated_at TEXT,
        PRIMARY KEY (date, kind, subject))""")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.executemany(
        "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(e["date"], e["kind"], e["subject"], e["title"], e["source"], e["url"],
          json.dumps(e["keywords"]), e["hype"], json.dumps(e["signals"]), now) for e in events])
    con.commit()
    con.close()


def report(events, errors, today, days):
    lines = [f"# Kalendar događaja {today} (+{days} dana)", ""]
    if errors:
        lines += ["Izvori koji nisu radili: " + "; ".join(f"{k} ({v})" for k, v in errors.items()), ""]
    header = ["| Ocjena | Tokeni | Datum | Za dana | Događaj | Ključne riječi | Izvor |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    now = [e for e in events if e["days_until"] <= 0]
    ahead = [e for e in events if e["days_until"] > 0]
    for name, group in (("Upravo se događa", now), ("Nadolazeće", ahead)):
        if not group:
            continue
        lines += [f"## {name}", ""] + header
        for e in group:
            title = f"[{e['title']}]({e['url']})" if e["url"] else e["title"]
            lines.append(f"| {e['hype']} | {round(100 * e['token_likelihood'])}% | {e['date']} | {e['days_until']} | "
                         f"{title} | {', '.join(e['keywords'][:6])} | {e['source']} |")
        lines.append("")
    lines.append("Ocjena = veličina događaja × vjerojatnost da će za njega nastati tokeni (stupac Tokeni).")
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--min-sitelinks", type=int, default=60, help="fame filter for Wikipedia people")
    p.add_argument("--pageviews-top", type=int, default=25)
    p.add_argument("--min-tokens", type=float, default=0.2, help="drop events below this token likelihood")
    p.add_argument("--start", help="YYYY-MM-DD, default today (useful for backtests)")
    a = p.parse_args(argv)

    today = dt.date.fromisoformat(a.start) if a.start else dt.date.today()
    events, errors = collect(today, a.days, a.min_sitelinks)
    events = [e for e in enrich_all(dedupe(events), today, a.pageviews_top)
              if e["token_likelihood"] >= a.min_tokens][:a.top]

    out = os.path.join(HERE, "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"calendar-{today}.json"), "w") as f:
        json.dump({"date": today.isoformat(), "errors": errors, "events": events}, f, indent=1, ensure_ascii=False)
    md = report(events, errors, today, a.days)
    with open(os.path.join(out, f"calendar-{today}.md"), "w") as f:
        f.write(md)
    save_db(events, os.path.join(HERE, "calendar.db"))
    print(md)
    print("Trajanje po izvoru (s): " + ", ".join(f"{k} {v}" for k, v in TIMINGS.items()), file=sys.stderr)
    return 0 if len(errors) < 8 else 1


if __name__ == "__main__":
    sys.exit(main())
