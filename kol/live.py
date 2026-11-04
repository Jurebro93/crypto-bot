"""Real-time following of the watchlist through the xquik monitor (Apify actor xquik/x-twitter-crypto-tracker).

Each new post of a watched KOL arrives within seconds at the dashboard's /hook/kol, goes into hype.db kol_mentions,
and the next hype scan (every 2 min) sees it as feature kol_x and as a candidate. The monitor bills $0.0045 per
account-hour, charged when the actor runs; it pauses after 24 h without a run, so sync() runs it every resync_h
hours and whenever the watchlist changes (stop for removed accounts, start for new ones).
"""
import os
import time
import urllib.parse

from kol import store


def hook_url():
    base = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KOL_HOOK_BASE")
    key = store.hook_key()
    if not base or not key:
        return None
    return f"{base.rstrip('/')}/hook/kol?key={urllib.parse.quote(key)}"


def plan(watch, monitored, last_run, now, resync_h):
    """(changed, due): the watchlist differs from what the monitor watches, or the periodic run is due."""
    changed = set(watch) != set(monitored)
    due = bool(watch) and now - (last_run or 0) >= resync_h * 3600
    return changed, due


def sync(con, cfg, monitor=None, now=None, log=print):
    """Bring the xquik monitor in line with the watch table: one call updates the monitor to the current list and
    charges the hours watched since the call before. An empty watchlist stops it. None without a public URL."""
    from hype import apify, sources
    monitor = monitor or sources.kol_monitor
    now = now or int(time.time())
    url = hook_url()
    if not url or not apify.enabled():
        return None
    watch = [r[0] for r in con.execute("SELECT handle FROM watch ORDER BY score DESC")]
    rows = dict(con.execute("SELECT handle, last_run FROM monitor"))
    last = max(rows.values()) if rows else 0
    changed, due = plan(watch, list(rows), last, now, cfg["watch"]["resync_h"])
    import hashlib
    url_h = hashlib.sha256(url.encode()).hexdigest()[:16]
    try:
        old_h = (con.execute("SELECT value FROM kv WHERE key='kol_hook_url'").fetchone() or ("",))[0]
    except Exception:
        old_h = url_h
    if old_h != url_h and watch:      # new hook key (4.11.): the monitor must learn the new URL now
        changed = True
    if not changed and not due:
        return False
    hours = round((now - last) / 3600, 2) if rows else 0  # what this call charges for the accounts watched so far
    if watch:
        monitor(watch, url, hours=hours * len(rows) / max(len(watch), 1))
    else:
        monitor(list(rows), url, stop=True, hours=hours)
    con.execute("DELETE FROM monitor")
    con.executemany("INSERT INTO monitor VALUES (?,?,?)", [(h, now, now) for h in watch])
    try:
        con.execute("INSERT OR REPLACE INTO kv VALUES ('kol_hook_url', ?)", (url_h,))
    except Exception:
        pass
    con.commit()
    if changed:
        log(f"live: pratim uživo {len(watch)} KOL-ova: {', '.join('@' + h for h in watch) or '-'}")
    return True
