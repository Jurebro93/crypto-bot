"""Where new channel candidates come from (all automatic):
- every X post / profile the bot already paid for (hype.db apify_cache: t.me links in text, bio, expanded urls),
- KOL identities with a Telegram link (kol.db kol_ids, from KOLscan / Solana Tracker / FOMO),
- hype/channels.txt (optional seeds),
- forwards and links inside channels we already read (tg/poll.visit, the snowball),
- TGStat post search by CA (paid, tg/tgstat.py).
"""
import os
import re
import sqlite3

from tg import reader, store

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RAW_LINK = re.compile(rb"(?:t\.me|telegram\.me)(?:\\?/)+(?:s(?:\\?/)+)?([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_]|\\u2026|\xe2\x80\xa6)")


def _ro(path):
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)


def names_in_blob(blob):
    """Channel names in raw JSON/HTML; truncated display links ('t.me/meme_raideralp…') are skipped."""
    b = blob if isinstance(blob, bytes) else (blob or "").encode("utf-8", "replace")
    out = {reader.channel_name(m.decode()) for m in _RAW_LINK.findall(b)}
    out.discard(None)
    return out


def from_x_cache(con, hype_db=None):
    path = hype_db or os.path.join(HERE, "hype.db")
    src = _ro(path)
    if src is None:
        return 0
    seen = store.kv_get(con, "disc_cache", {})
    n = 0
    try:
        for key, ts in src.execute("SELECT key, ts FROM apify_cache").fetchall():   # items only when new
            if seen.get(key) == ts:
                continue
            row = src.execute("SELECT ts, items FROM apify_cache WHERE key = ?", (key,)).fetchone()
            if row is None or seen.get(key) == row[0]:
                continue
            n += store.add_candidates(con, names_in_blob(row[1]), "x")
            seen[key] = row[0]
    except sqlite3.OperationalError:
        pass
    finally:
        src.close()
    store.kv_set(con, "disc_cache", {k: v for k, v in list(seen.items())[-3000:]})
    return n


def from_kol_ids(con, kol_db=None):
    src = _ro(kol_db or os.path.join(HERE, "kol.db"))
    if src is None:
        return 0
    n = 0
    try:
        for link, source in src.execute("SELECT telegram, source FROM kol_ids WHERE telegram IS NOT NULL"):
            n += store.add_candidates(con, names_in_blob(link) or {reader.channel_name(link)}, source)
    except sqlite3.OperationalError:
        pass
    finally:
        src.close()
    return n


def from_seed_file(con, path=None):
    path = path or os.path.join(HERE, "hype", "channels.txt")
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        names = {reader.channel_name(l.strip()) for l in f if l.strip() and not l.startswith("#")}
    names.discard(None)
    return store.add_candidates(con, names, "channels.txt")


def run(con, hype_db=None, kol_db=None):
    return {"x": from_x_cache(con, hype_db), "kol_ids": from_kol_ids(con, kol_db), "seed": from_seed_file(con)}
