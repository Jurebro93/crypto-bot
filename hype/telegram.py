"""Public Telegram channels via the web preview (https://t.me/s/<channel>), no login or key.

Pulls the latest ~20 posts per channel and extracts Solana contract addresses and $TICKERs.
"""
import html
import re
import urllib.request

from event_calendar.http import USER_AGENT

_POST = re.compile(r'data-post="([^"]+)".*?<div class="tgme_widget_message_text[^>]*>(.*?)</div>.*?'
                   r'<time datetime="([^"]+)"', re.S)
_CA = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
_TICKER = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,11})\b")
_TAG = re.compile(r"<[^>]+>")


def fetch(channel, timeout=20):
    req = urllib.request.Request(f"https://t.me/s/{channel.lstrip('@')}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse(page, channel=""):
    posts = []
    for post_id, body, when in _POST.findall(page):
        raw = html.unescape(body)  # links keep the CA in href, so search markup too
        text = html.unescape(_TAG.sub(" ", body))
        cas = sorted({c for c in _CA.findall(raw) if any(ch.isdigit() for ch in c)})
        posts.append({"channel": channel, "post": post_id, "time": when, "text": text.strip()[:500],
                      "cas": cas, "tickers": sorted({t.upper() for t in _TICKER.findall(text)})})
    return posts


def mentions(channels):
    """All posts with a CA or ticker from the given channels; errors per channel are returned, not raised."""
    posts, errors = [], {}
    for ch in channels:
        try:
            posts += [p for p in parse(fetch(ch), ch) if p["cas"] or p["tickers"]]
        except Exception as e:
            errors[ch] = f"{type(e).__name__}: {e}"
    return posts, errors
