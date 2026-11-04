"""Paid shillers: Telegram channels and X accounts Nicholas paid to promote tokens (kol/shillers.json, his own table).

They are tracked like every other caller (tg/discover reads the channels, kol/collect.timeline_handles reads the X
accounts), but a paid shill is not a "good KOL" just because one lucky call went up: kol/discover.annotate keeps it
on trial until it has proven itself on many measured calls (shill.min_calls in kol/config.json, default 20) with the
lower end of its score range at good_score or more. Until then it never enters the live watch, copy trading or the
"good KOL" part of the group signal, and the dashboard marks it "plaćeni shill".
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "shillers.json")
DEFAULTS = {"min_calls": 20}
_cache = {}


def entries(path=None):
    path = path or PATH
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return []
    if _cache.get(path, (None,))[0] != mt:
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        _cache[path] = (mt, d.get("entries", []) if isinstance(d, dict) else [])
    return _cache[path][1]


def tg_channels(path=None):
    """Lowercase channel names (the tg.db / kol.db 'tg:<name>' spelling)."""
    return list(dict.fromkeys(c.lower() for e in entries(path) for c in e.get("tg", []) if c))


def x_handles(path=None):
    return list(dict.fromkeys(h for e in entries(path) for h in e.get("x", []) if h))


def handles(path=None):
    """Every kol.db handle of a paid shill, lowercased: X handles and 'tg:<channel>'."""
    return {h.lower() for h in x_handles(path)} | {"tg:" + c for c in tg_channels(path)}


def is_shill(handle, path=None):
    return bool(handle) and handle.lower() in handles(path)


def info(handle, path=None):
    """The table row of one handle ({} if not listed): price, note, followers, linked accounts."""
    h = (handle or "").lower()
    for e in entries(path):
        names = {x.lower() for x in e.get("x", [])} | {"tg:" + c.lower() for c in e.get("tg", [])}
        if h in names:
            return e
    return {}


def cfg(kol_cfg):
    return dict(DEFAULTS, **((kol_cfg or {}).get("shill") or {}))
