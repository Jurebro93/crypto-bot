"""Sources for big one-off events, beyond birthdays and prediction markets.

- wikipedia_viral_now: articles whose views just spiked (deaths, disasters, memes, scandals)
- news_dates: release/launch/unveil dates found in Google News headlines, plus dates for
  watchlist items whose date is still unknown (Tesla Roadster, a game, a product)
- earthquakes / asteroids: catastrophe triggers that regularly spawn "end of the world" tokens

All free, no API key. Same Event dict shape as sources.py.
"""
import datetime as dt
import json
import re
import statistics
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict

from . import http
from .sources import MANUAL_FILE

MOSTREAD = "https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{y}/{m:02d}/{d:02d}"
GNEWS = "https://news.google.com/rss/search"
USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson"
CNEOS = "https://ssd-api.jpl.nasa.gov/cad.api"

# Generic headline searches for scheduled big moments.
NEWS_QUERIES = [
    '"release date" announced', '"launch event" date', 'unveil event date', '"will be revealed on"',
    '"premieres on"', '"set to launch on"', '"keynote" date announced', '"livestream" "on November"',
]
BIG_WORDS = re.compile(r"\b(release|releases|launch|launches|unveil|unveils|reveal|premiere|debut|"
                       r"keynote|event|livestream|trailer|drops?|arrives?|coming)\b", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
DATE_RE = re.compile(r"\b(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
                     r"(?:,?\s+(20\d\d))?\b", re.I)
# Wikipedia pages that are always in the most-read list and say nothing about events.
WIKI_NOISE = re.compile(r"^(Main_Page|Special:|Wikipedia:|Portal:|File:|Deaths_in_|List_of_|.*\(TV_series\)$|"
                        r".*\(film\)$|.*season_\d+)", re.I)


def wikipedia_viral_now(today, days_back=2, min_spike=3.0, min_views=150_000):
    """Most-read English Wikipedia articles whose views jumped well above their recent median."""
    events = {}
    for back in range(1, days_back + 1):
        d = today - dt.timedelta(days=back)
        feed = http.get_json(MOSTREAD.format(y=d.year, m=d.month, d=d.day))
        for a in (feed.get("mostread") or {}).get("articles", []):
            title = a.get("title", "")
            if WIKI_NOISE.match(title) or a.get("views", 0) < min_views:
                continue
            history = [h["views"] for h in a.get("view_history", [])[:-1]] or [1]
            spike = a["views"] / max(1, statistics.median(history))
            if spike < min_spike:
                continue
            name = a.get("normalizedtitle") or title.replace("_", " ")
            prev = events.get(name)
            if prev and prev["signals"]["spike"] >= spike:
                continue
            events[name] = {
                "date": today.isoformat(),
                "title": f"Viral now: {name} ({a.get('description', '')})".replace(" ()", ""),
                "kind": "viral_now",
                "subject": name,
                "source": "wikipedia_mostread",
                "url": f"https://en.wikipedia.org/wiki/{title}",
                "signals": {"views_1d": a["views"], "spike": round(spike, 1), "wiki_title": title,
                            "description": a.get("description", "")},
            }
    return list(events.values())


def _parse_dates(text, today):
    """Dates mentioned in a headline that fall from today to ~13 months ahead."""
    out = []
    for mon, day, year in DATE_RE.findall(text):
        m = [x[:3] for x in MONTHS].index(mon[:3].lower()) + 1
        y = int(year) if year else (today.year if (m, int(day)) >= (today.month, today.day) else today.year + 1)
        try:
            d = dt.date(y, m, int(day))
        except ValueError:
            continue
        if today <= d <= today + dt.timedelta(days=400):
            out.append(d)
    return out


def _news(query):
    xml = http.get_text(GNEWS, {"q": f"{query} when:30d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    for item in ET.fromstring(xml).iter("item"):
        title = item.findtext("title") or ""
        yield re.sub(r"\s+-\s+[^-]+$", "", title), item.findtext("link") or ""


def news_dates(today, days_ahead, queries=NEWS_QUERIES, watchlist_file=MANUAL_FILE, min_articles=2):
    """Group headlines by (subject, date). A date needs `min_articles` headlines to count."""
    with open(watchlist_file) as f:
        watch = [w for w in json.load(f) if not w.get("date") and w.get("query")]
    jobs = [(q, None) for q in queries] + [(w["query"], w) for w in watch]
    end = today + dt.timedelta(days=days_ahead)
    groups = defaultdict(lambda: {"titles": [], "urls": []})
    for query, item in jobs:
        for title, link in _news(query):
            if item is None and not BIG_WORDS.search(title):
                continue
            if item and not _mentions(item, title):
                continue  # search engines return loosely related headlines
            for d in _parse_dates(title, today):
                if d > end:
                    continue
                subject = item["subject"] if item else _subject_from_headline(title)
                if not subject:
                    continue
                g = groups[(subject, d)]
                g["titles"].append(title)
                g["urls"].append(link)
                g["item"] = item
    events = []
    for (subject, d), g in groups.items():
        if len(set(g["titles"])) < min_articles:
            continue
        item = g.get("item")
        events.append({
            "date": d.isoformat(),
            "title": item["title"] if item else g["titles"][0],
            "kind": item.get("kind", "launch") if item else _kind_from_headline(g["titles"][0]),
            "subject": subject,
            "source": "news",
            "url": g["urls"][0],
            "signals": {"news_articles": len(set(g["titles"])), "headlines": sorted(set(g["titles"]))[:5],
                        "keywords": (item or {}).get("keywords", []), "date_from_news": True},
        })
    return events


def _mentions(item, title):
    words = re.findall(r"[a-z0-9]+", f"{item['subject']} {' '.join(item.get('keywords', []))}".lower())
    t = re.sub(r"[^a-z0-9]+", " ", title.lower())
    return any(re.search(rf"\b{w}\b", t) for w in words if len(w) >= 3)


def _subject_from_headline(title):
    """The leading run of capitalised words, e.g. 'GTA 6 trailer 3 drops on ...' -> 'GTA 6'."""
    m = re.match(r"^((?:[A-Z0-9][\w'’.&:-]*\s?){1,5})", title)
    subject = (m.group(1) if m else "").strip(" :-")
    return "" if len(subject) < 3 or subject.split()[0].lower() in {"the", "a", "how", "why", "when", "what"} else subject


def _kind_from_headline(title):
    t = title.lower()
    if re.search(r"\b(game|gta|playstation|xbox|nintendo|switch|trailer)\b", t):
        return "game_release"
    if re.search(r"\b(film|movie|premiere|season|series|album)\b", t):
        return "media_release"
    return "launch"


def earthquakes(today, min_mag=7.0):
    data = http.get_json(USGS, ttl=1800)
    events = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        if (p.get("mag") or 0) < min_mag:
            continue
        day = dt.datetime.fromtimestamp(p["time"] / 1000, dt.timezone.utc).date()
        events.append({
            "date": day.isoformat(), "title": f"M{p['mag']} earthquake, {p.get('place', '')}",
            "kind": "disaster", "subject": p.get("place", "earthquake"), "source": "usgs", "url": p.get("url", ""),
            "signals": {"magnitude": p["mag"], "tsunami": bool(p.get("tsunami")), "keywords": ["EARTHQUAKE", "QUAKE"]},
        })
    return events


def asteroids(today, days_ahead, max_dist_au=0.01, max_h=24):
    """Close asteroid approaches (inside ~4 lunar distances, large enough to make headlines)."""
    data = http.get_json(CNEOS, {"date-min": today.isoformat(),
                                 "date-max": (today + dt.timedelta(days=days_ahead)).isoformat(),
                                 "dist-max": str(max_dist_au), "h-max": str(max_h), "sort": "dist"})
    idx = {k: i for i, k in enumerate(data.get("fields", []))}
    events = []
    for row in data.get("data", []):
        name = row[idx["des"]]
        events.append({
            "date": dt.datetime.strptime(row[idx["cd"]][:11], "%Y-%b-%d").date().isoformat(),
            "title": f"Asteroid {name} close approach", "kind": "disaster", "subject": f"Asteroid {name}",
            "source": "nasa_cneos", "url": f"https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={urllib.parse.quote(name)}",
            "signals": {"dist_au": float(row[idx["dist"]]), "h": float(row[idx["h"]]), "keywords": ["ASTEROID", "DOOM"]},
        })
    return events
