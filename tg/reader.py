"""Public Telegram channel pages (https://t.me/s/<channel>): posts with time, views, CAs, forwards and links.

The page lists the latest ~20 posts; a channel without a public web preview (private, group, user, bot) redirects
to t.me/<name> and has no channel info block, so `public` is False.
"""
import datetime as dt
import html
import re
import urllib.request

from event_calendar.http import USER_AGENT
from hype.telegram import _CA, _TICKER

_TAG = re.compile(r"<[^>]+>")
_POST_ID = re.compile(r'data-post="([A-Za-z0-9_]+)/(\d+)"')
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time datetime="([^"]+)"')
_VIEWS = re.compile(r'class="tgme_widget_message_views">([^<]*)<')
_FWD = re.compile(r'tgme_widget_message_forwarded_from_name"[^>]*href="https://t\.me/([A-Za-z0-9_]+)')
_SUBS = re.compile(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">(?:subscribers|members)')
_TITLE = re.compile(r'<div class="tgme_channel_info_header_title"[^>]*>(?:<span[^>]*>)?(.*?)</', re.S)
# t.me/<name> and @name mentions; names are 5-32 chars, letters, digits, underscore, starting with a letter
LINK = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})\b(?!/joinchat)", re.I)
_AT = re.compile(r"(?<![\w@.])@([A-Za-z][A-Za-z0-9_]{4,31})\b")
SKIP = {"joinchat", "share", "addlist", "iv", "proxy", "socks", "setlanguage", "addstickers", "addemoji",
        "contact", "login", "telegram", "durov", "c", "s"}


def k_num(s):
    """'1.2K' / '3.53K' / '12M' / '845' -> int."""
    s = (s or "").strip().upper().replace(",", "").replace(" ", "")
    mult = 1
    if s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def iso_ts(s):
    """t.me <time datetime="2026-11-09T10:32:01+00:00"> -> unix seconds. A value without an offset is read as UTC
    (never the server's local clock), so a call's minute matches the candle's minute (kol/minute.py)."""
    try:
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp())
    except (TypeError, ValueError):
        return None


def channel_name(name):
    """Normalised candidate name, or None for links that are not channels (bots, invite links, system pages)."""
    n = (name or "").strip().lstrip("@").split("?")[0].split("/")[0]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", n):
        return None
    low = n.lower()
    if low in SKIP or low.endswith("bot"):
        return None
    return low


def links_in(text):
    """Channel names linked or @mentioned in a text."""
    out = {channel_name(m) for m in LINK.findall(text or "")} | {channel_name(m) for m in _AT.findall(text or "")}
    out.discard(None)
    return out


def fetch(channel, timeout=20):
    req = urllib.request.Request(f"https://t.me/s/{channel}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse(page, channel):
    """{'public', 'title', 'subs', 'posts': [{post, ts, text, cas, tickers, views, fwd_from, links}]}"""
    info = {"public": "tgme_channel_info" in page, "title": None, "subs": 0, "posts": []}
    m = _TITLE.search(page)
    if m:
        info["title"] = html.unescape(_TAG.sub("", m.group(1))).strip()[:120]
    m = _SUBS.search(page)
    if m:
        info["subs"] = k_num(m.group(1))
    for chunk in page.split('class="tgme_widget_message_wrap')[1:]:
        pid = _POST_ID.search(chunk)
        when = _TIME.search(chunk)
        if not pid or not when:
            continue
        tm = _TEXT.search(chunk)
        body = tm.group(1) if tm else ""
        raw = html.unescape(body)  # links keep the CA in href, so search the markup too
        text = html.unescape(_TAG.sub(" ", body.replace("<br/>", "\n").replace("<br>", "\n")))
        text = re.sub(r"[ \t]+", " ", text).strip()
        cas = sorted({c for c in _CA.findall(raw) if any(ch.isdigit() for ch in c)})
        v = _VIEWS.search(chunk)
        f = _FWD.search(chunk)
        info["posts"].append({
            "post": int(pid.group(2)), "ts": iso_ts(when.group(1)), "text": text[:600], "cas": cas,
            "tickers": sorted({t.upper() for t in _TICKER.findall(text)}), "views": k_num(v.group(1)) if v else 0,
            "fwd_from": channel_name(f.group(1)) if f else None,
            "links": sorted(links_in(raw) - {channel})})
    return info


def read(channel):
    return parse(fetch(channel), channel)
