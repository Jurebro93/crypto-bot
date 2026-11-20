"""Public Telegram channel page (https://t.me/s/<channel>): since 19.11.2026 only the channel header is read (title and
subscriber count) for the weekly follower list (tg/pratitelji.py). The posts, their texts, token addresses, links and
forwards are not parsed any more (vlasnik 19.11.: Telegram out of every calculation; the old reader, discovery,
history, TGStat and Telethon were removed with it).

A channel without a public web preview (private, group, user, bot) redirects to t.me/<name> and has no channel info
block, so `public` is False.
"""
import html
import re
import urllib.request

from event_calendar.http import USER_AGENT

_TAG = re.compile(r"<[^>]+>")
_SUBS = re.compile(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">(?:subscribers|members)')
_TITLE = re.compile(r'<div class="tgme_channel_info_header_title"[^>]*>(?:<span[^>]*>)?(.*?)</', re.S)
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")


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


def fetch(channel, timeout=20):
    if not NAME.fullmatch(channel or ""):
        raise ValueError("nije ime kanala")
    req = urllib.request.Request(f"https://t.me/s/{channel}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(400_000).decode("utf-8", "replace")


def parse_header(page):
    """{'public', 'title', 'subs'} from the channel header only."""
    info = {"public": "tgme_channel_info" in (page or ""), "title": None, "subs": 0}
    m = _TITLE.search(page or "")
    if m:
        info["title"] = html.unescape(_TAG.sub("", m.group(1))).strip()[:120]
    m = _SUBS.search(page or "")
    if m:
        info["subs"] = k_num(m.group(1))
    return info
