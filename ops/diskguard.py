"""Disk guard (12.11., Jure: "Health check: upozorenje kad je disk >= 75 % ili ostane < 3 dana, i automatski pokreni
korake b) i d) (ne a/c) kad prijeđe 85 %").

Called every minute by ops/health (the memory watchdog's pass); cheap: one statvfs and two small state files.
  warning   used >= WARN_USED or runway < WARN_RUNWAY_D days: one log line "disk UPOZORENJE ..." at most every
            WARN_EVERY_S, and a Telegram message to the owner (only when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set)
            at most every TG_EVERY_S. get_hourly_brief shows it too (ops/diskreport.brief_part, alarm at 75 %).
  automatic above AUTO_USED, at most every AUTO_EVERY_S: b) the HTTP cache pruned (event_calendar/http.prune: files
            no reader can use any more, then down to AUTO_CACHE_MB) and d) log rotation (ops/logrot, forced). Never a
            database VACUUM (a) or a row deletion (c): those stay in the night window under the owner's switches.
The runway is the free space over the growth per day measured by ops/diskreport (net growth between its runs at
least 20 h apart, else the rows' inflow); without a measurement only the percentage counts.
"""
import json
import os
import shutil
import threading
import time
import urllib.parse
import urllib.request

from ops import disk

WARN_USED = 0.75
WARN_RUNWAY_D = 3.0
AUTO_USED = 0.85
WARN_EVERY_S = 3600
TG_EVERY_S = 6 * 3600
AUTO_EVERY_S = 1800
AUTO_CACHE_MB = 50
STATE = ".diskguard.json"


def _path(data_dir=None):
    return os.path.join(data_dir or disk.DATA_DIR, STATE)


def _load(data_dir=None):
    try:
        with open(_path(data_dir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st, data_dir=None):
    p = _path(data_dir)
    try:
        with open(p + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def growth_mb_day(data_dir=None):
    """MB a day from ops/diskreport's last report (None before its first)."""
    try:
        from ops import diskreport
        g = diskreport.load_state(data_dir or disk.DATA_DIR).get("growth") or {}
        v = g.get("used_mb_day")
        return float(v) if v else None
    except Exception:  # noqa: BLE001 - only the percentage counts then
        return None


def usage(data_dir=None):
    try:
        u = shutil.disk_usage(data_dir or disk.DATA_DIR)
        return u.used, u.free, u.total
    except OSError:
        return None, None, None


def _telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False

    def send():
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": f"MemeSonar · {text}",
                                           "disable_web_page_preview": "true"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15).read()
        except Exception as e:  # noqa: BLE001 - the log line is there anyway
            print(f"disk UPOZORENJE: Telegram nije poslan ({type(e).__name__})", flush=True)
    threading.Thread(target=send, daemon=True).start()
    return True


def auto_clean(log=print):
    """b) + d): the HTTP cache and the logs. -> (cache MB freed, logs MB freed)."""
    cache_mb = logs_mb = 0.0
    try:
        from event_calendar import http
        _n, cache_mb = http.prune(max_mb=AUTO_CACHE_MB)
    except Exception as e:  # noqa: BLE001
        log(f"disk: čišćenje cachea nije uspjelo: {type(e).__name__}: {str(e)[:120]}")
    try:
        from ops import logrot
        logs_mb = logrot.rotate(force=True, log=log)["freed_mb"]
    except Exception as e:  # noqa: BLE001
        log(f"disk: rotacija logova nije uspjela: {type(e).__name__}: {str(e)[:120]}")
    return cache_mb, logs_mb


def check(now=None, log=print, data_dir=None, use=None, growth=None, clean=None, telegram=None):
    """One pass. -> {"used_pct", "free_mb", "runway_days", "warn", "auto"}. use / growth / clean / telegram: tests."""
    now = now or time.time()
    used, free, total = use if use is not None else usage(data_dir)
    if not total or used is None or free is None:
        return {}
    frac, free_mb = used / total, free / 1e6
    g = growth_mb_day(data_dir) if growth is None else growth
    runway = round(free_mb / g, 1) if g and g > 0 else None
    warn = frac >= WARN_USED or (runway is not None and runway < WARN_RUNWAY_D)
    st = _load(data_dir)
    out = {"used_pct": round(frac * 100, 1), "free_mb": round(free_mb), "runway_days": runway, "warn": warn, "auto": None}
    if warn:
        text = (f"disk {frac:.0%} pun, slobodno {free_mb:.0f} MB"
                + (f", pun za ~{runway:.1f} dana (rast {g:.0f} MB/dan)" if runway is not None else "")
                + f" | prag upozorenja {WARN_USED:.0%} ili {WARN_RUNWAY_D:g} dana; iznad {AUTO_USED:.0%} se sam čisti "
                  "cache i rotiraju logovi")
        if now - (st.get("warned") or 0) >= WARN_EVERY_S:
            log(f"disk UPOZORENJE: {text}")
            st["warned"] = int(now)
        if now - (st.get("tg") or 0) >= TG_EVERY_S and (telegram or _telegram)(f"Disk upozorenje: {text}"):
            st["tg"] = int(now)
    if frac > AUTO_USED and now - (st.get("auto") or 0) >= AUTO_EVERY_S:
        cache_mb, logs_mb = (clean or auto_clean)(log)
        after = (use if use is not None else usage(data_dir))[1]
        out["auto"] = {"cache_mb": round(cache_mb, 1), "logs_mb": round(logs_mb, 1)}
        log(f"disk: iznad {AUTO_USED:.0%} ({frac:.0%}): automatski očišćen cache ({cache_mb:.0f} MB) i rotirani logovi "
            f"({logs_mb:.0f} MB); slobodno sada {(after or 0) / 1e6:.0f} MB")
        st["auto"] = int(now)
    _save(st, data_dir)
    return out
