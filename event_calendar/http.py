"""Minimal HTTP helper (stdlib only) with a small on-disk cache."""
import contextlib
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from usage import meter
except ImportError:  # module copied without usage/: no spend tracking
    meter = None

# Wikimedia asks for a descriptive UA with contact info; set CAL_USER_AGENT to add yours.
USER_AGENT = os.environ.get("CAL_USER_AGENT", "crypto-event-calendar/0.2 (personal research tool)")
RETRIES = int(os.environ.get("CAL_HTTP_RETRIES", "4"))
MIN_GAP = {"wikimedia.org": 1.0, "wikidata.org": 1.0, "wikipedia.org": 1.0}  # seconds between calls per host
_last_call = {}
CACHE_DIR = os.environ.get("CAL_CACHE_DIR", os.path.join(os.path.dirname(__file__), "..", ".cache"))
CACHE_TTL = int(os.environ.get("CAL_CACHE_TTL", "21600"))  # 6 h
# The cache lives on the same small disk as the databases (Render: 1 GB) and grew ~1 GB a day with nothing
# deleting it. Entries older than the longest TTL in use (a week) are useless; above the size cap the oldest go first.
# 12.11. 12:42: 250 -> 120 MB: the expiry by TTL class freed nothing at start-up (the cache at its cap only holds the
# last hours); over the cap the cheap answers go first, paid Helius ones last (prune)
CACHE_MAX_MB = float(os.environ.get("CAL_CACHE_MAX_MB", "120"))
CACHE_MAX_AGE = int(os.environ.get("CAL_CACHE_MAX_AGE", str(7 * 86400)))
SHORT_LIVED = {"rpc-": 3600}   # wallets/rpc.py caches Helius RPC for 10 min; those files are dead after that
# 12.11. (Jure: "Očisti cache (oko 250 MB): snapshote i DexScreener/rangedca cache starije od 24 h"): a file's name
# starts with its TTL class, so prune() deletes it once no reader can use it any more (a reader only takes a file
# younger than its own TTL): s <= 1 h (DexScreener 20 s, rangedca, zonewatch, GeckoTerminal), m <= 6 h (the default
# TTL, rugcheck), l <= 24 h (Helius dev creations), w = longer (Helius first transactions, a week: paid credits).
# A file from before (no class in its name) goes after LEGACY_MAX_AGE, except paid Helius answers (kept to the
# week CACHE_MAX_AGE, so no credits are spent again).
TTL_CLASSES = (("s", 3600), ("m", 6 * 3600), ("l", 86400), ("w", 7 * 86400))
# 12.11. 12:18: the start-up prune after the deploy freed nothing: at its 250 MB cap the cache only holds the last
# hours, all younger than 24 h. A file from before older than the default TTL (6 h) is useless to every reader
# whose TTL is at most that (DexScreener, rangedca, zonewatch, GeckoTerminal, rugcheck); the longer ones are the
# free calendar / Wikipedia feeds (fetched again once) and paid Helius answers (kept, below).
LEGACY_MAX_AGE = int(os.environ.get("CAL_CACHE_LEGACY_MAX_AGE", str(6 * 3600)))
PAID_MARKS = (b'"feePayer"', b'"nativeTransfers"', b'"tokenTransfers"')   # Helius Enhanced / first-transactions
PRUNE_EVERY = 200   # writes between automatic prunes
_writes = 0


# Hosts whose free limit is per IP, shared by every process on the server (GeckoTerminal: ~30 calls a minute for
# the KOL measurements, the Dugoročni candles and holder counts together). One file per host under /tmp holds
# "next call allowed at" and "paused until" so the processes queue behind each other instead of each pacing alone
# and all of them hitting 429 together. After a 429 everyone pauses SHARED_COOLDOWN seconds.
# 9.11. 14:18: 2.5 s (24/min) across our processes still drew 429s from the free API (30/min, shared egress);
# 3.5 s (~17/min) leaves room for the odd retry and whoever shares the IP
SHARED_GAP = {"geckoterminal.com": float(os.environ.get("GECKO_SHARED_GAP", "3.5"))}
SHARED_COOLDOWN = float(os.environ.get("GECKO_COOLDOWN_S", "60"))
SHARED_403_PAUSE = float(os.environ.get("GECKO_403_PAUSE_S", "300"))   # 9.11. (audit P24)
GATE_DIR = os.environ.get("HTTP_GATE_DIR") or os.path.join(tempfile.gettempdir(), "crypto-bot-gate")


# 10.11. (Jure kupio CoinGecko plaćeni API): GeckoTerminal's data through CoinGecko's paid on-chain API, the same
# paths and the same JSON under https://pro-api.coingecko.com/api/v3/onchain with the key in a header. With the key
# (Render env COINGECKO_API_KEY; COINGECKO_DEMO=1 for a free demo key) every GeckoTerminal URL the jobs build is sent
# there, paced at CG_GAP seconds (default 0.25 s = 240 calls a minute, under the smallest paid plan's 250) instead of
# 3.5 s, and no job reserves the host for itself any more. Without the key nothing changes. The key is never logged.
GT_BASE = "https://api.geckoterminal.com/api/v2"


def _cg_key_raw():
    return (os.environ.get("COINGECKO_API_KEY") or "").strip()


# 10.11. (CLAUDE.md: "prije svakog troška izmjeri"): a paid plan has a MONTHLY number of calls; at 240 a minute the
# jobs that waited behind the free limit (all KOL calls, Dugoročni, trending) could use a month's calls in days.
# CG_DAILY_CALLS (default 3000 a day, ~90k a month, under the smallest paid plan) is the day's budget for the key;
# past it, the calls go to the free GeckoTerminal again (and its pace) until midnight UTC. Counted across processes.
#
# 11.11. (Jure, preporuka 1 iz analize troška: "Može sve"): the 3000 were gone by 03:38 CET every day (01:00-03:38 the
# night book "masovno" ~60 % and the minute backlog ~27 %), so from early morning to midnight - when the market is
# busiest - the live jobs ran on the free API with ~27 HTTP 429 an hour and the minute queue grew 59 -> 106 tokens by
# 13:00. Now the key is spent by the hour, cumulatively over the UTC day: by the end of hour h at most
# cap x (h + 1) / 24 (as the scanner's own caps, scan/store.allowance); unused hours roll over. The live jobs
# (CG_PRIORITY: the minute loop, range, momentum, the scanner) may use the whole slice; every other job stops
# CG_RESERVE of an hour's share earlier, so the last part of each slice is theirs. The night book "masovno" uses the
# key only in the night window (01-06 Zagreb) and at most CG_MASOVNO_NIGHT (1000) calls a night; the rest of its
# calls and all of its day calls go to the free GeckoTerminal. The day file also counts, per job, the calls that went
# free, and the HTTP 429 per UTC hour (the daily cost line, usage/daily.py; the hourly line, kol/minute.loop).
# 15.11. navečer (coordinator: veliki's 1h candles never arrived, GeckoTerminal 429 all day): veliki (run_veliki.py list
# / candles: the demo's and the real money's zones) is a live job too, so the key's whole hourly slice is its. The midcap
# collector (job "midcap", up to its own gt_day) is not: it stops CG_RESERVE of each hour's share earlier, so that part
# of every slice always stays for veliki
CG_PRIORITY = ("veliki", "minute", "range", "momentum", "scan")
_CG_JOB = [None]
_CG_LOCAL = threading.local()   # 14.11.: one thread's job inside a process that serves others (cg_job_as)


def _env_f(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _now():
    return time.time()


CG_BASE_CAP = 3000          # the day's budget when the plan is unknown (and the floor of the measured one)
CG_ACCOUNT_EVERY = 6 * 3600   # 20.11.: GET /key at most once in 6 h
CG_ACCOUNT_VALID = 36 * 3600  # a reading older than this no longer sets the cap (back to CG_BASE_CAP)
CG_PLAN_SHARE = 0.9           # of the monthly credit spread over 31 days
CG_MONTH_RESERVE = 0.05       # of the monthly credit kept back at the end of the calendar month


def cg_cap(now=None):
    """The key's day budget. CG_DAILY_CALLS when set (the env wins); else 20.11. (CLAUDE.md: izmjeri pa koristi) from the
    measured plan (cg_account(): CoinGecko's own GET /key, cached): cg_cap_from(); 3000 while it is unknown."""
    if (os.environ.get("CG_DAILY_CALLS") or "").strip():
        return int(_env_f("CG_DAILY_CALLS", CG_BASE_CAP))
    now = now or _now()
    return cg_cap_from(cg_account_cached(now), now)


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _days_left_in_month(now):
    """Days of the calendar month (UTC) from today to its end, today included."""
    import calendar
    t = time.gmtime(now)
    return calendar.monthrange(t.tm_year, t.tm_mon)[1] - t.tm_mday + 1


def cg_cap_from(info, now):
    """Pure: the day budget from a /key reading (cg_account's dict) at `now`.
    max(3000, floor(0.9 x monthly_call_credit / 31)), but never more than what the month has left above a 5 % reserve,
    spread over the days left in the calendar month (today included; the calls the day had already spent when the
    reading was taken are added back, they are in its "remaining" already). No reading, an old one (36 h) or no credit
    figure: 3000. A reading from another calendar month sets only the plan part (its "remaining" is not this month's)."""
    if not isinstance(info, dict) or not info.get("ts") or now - info["ts"] > CG_ACCOUNT_VALID:
        return CG_BASE_CAP
    credit = _int(info.get("credit"))
    if not credit or credit <= 0:
        return CG_BASE_CAP
    cap = max(CG_BASE_CAP, int(CG_PLAN_SHARE * credit / 31))
    remaining = _int(info.get("remaining"))
    if remaining is None and _int(info.get("used")) is not None:
        remaining = credit - _int(info.get("used"))
    if remaining is not None and time.strftime("%Y-%m", time.gmtime(info["ts"])) == time.strftime("%Y-%m", time.gmtime(now)):
        spent_then = int(info.get("n_at") or 0) if info.get("day") == _day(now) else 0
        spare = max(0.0, remaining - CG_MONTH_RESERVE * credit) / _days_left_in_month(now)
        cap = min(cap, int(spent_then + spare))
    return max(0, cap)


def _cg_account_file():
    """Next to the day file (the persistent disk when there is one)."""
    return os.path.join(os.path.dirname(_cg_day_file()), "coingecko.key.json")


_CG_ACC_MEMO = [None, None]   # (path, mtime) -> parsed file: cg_cap() runs on every call


def _cg_account_load():
    path = _cg_account_file()
    try:
        mt = os.path.getmtime(path)
        if _CG_ACC_MEMO[0] == (path, mt):
            return _CG_ACC_MEMO[1]
        with open(path) as f:
            d = json.load(f)
        d = d if isinstance(d, dict) else {}
        _CG_ACC_MEMO[0], _CG_ACC_MEMO[1] = (path, mt), d
        return d
    except (OSError, ValueError):
        return {}


def cg_account_cached(now=None):
    """The last /key reading (dict: ts, plan, rate, credit, used, remaining, n_at, day) or None; never a network call."""
    d = _cg_account_load()
    return d if d.get("ts") else None


def _cg_parse_key(data):
    """CoinGecko GET /key -> our fields (docs.coingecko.com/reference/api-usage, checked 20.11.: plan,
    rate_limit_request_per_minute, monthly_call_credit, current_total_monthly_calls, current_remaining_monthly_calls;
    account-level values). Missing fields stay None."""
    if not isinstance(data, dict):
        return None
    out = {"plan": str(data.get("plan"))[:40] if data.get("plan") is not None else None,
           "rate": _int(data.get("rate_limit_request_per_minute")),
           "credit": _int(data.get("monthly_call_credit")),
           "used": _int(data.get("current_total_monthly_calls")),
           "remaining": _int(data.get("current_remaining_monthly_calls"))}
    return out if any(v is not None for v in out.values()) else None


def cg_account(now=None, fetch=None):
    """20.11.: the plan as CoinGecko counts it, read at most once in CG_ACCOUNT_EVERY (6 h, failures included) with one
    call to GET https://pro-api.coingecko.com/api/v3/key (counted in the day file as job "racun"), cached in
    coingecko.key.json next to coingecko.day. Only with a paid key (a demo key has no /key). Never raises; returns the
    cached reading (or None). fetch(url, headers) -> dict replaces the network (tests)."""
    now = now or _now()
    try:
        d = _cg_account_load()
        key = _cg_key_raw()
        if not key or os.environ.get("COINGECKO_DEMO") == "1":
            return d if d.get("ts") else None
        if now - float(d.get("tried") or 0) < CG_ACCOUNT_EVERY:
            return d if d.get("ts") else None
        new = dict(d, tried=int(now))
        _cg_account_save(new)   # the attempt first: a failing endpoint is asked again only in 6 h

        def count(st):
            st["n"] += 1
            st["jobs"]["racun"] = st["jobs"].get("racun", 0) + 1
            return st["n"]
        n_at = _cg_update(count, now)
        url = "https://pro-api.coingecko.com/api/v3/key"
        hdr = {"x-cg-pro-api-key": key}
        try:
            if fetch is not None:
                data = fetch(url, hdr)
            else:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **hdr})
                data = _fetch(req, 15, retries=0)
        except Exception as e:  # noqa: BLE001 - the budget falls back to 3000, the reason goes to the line
            new["err"] = f"{type(e).__name__}"[:60] + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else "")
            _cg_account_save(new)
            return new if new.get("ts") else None
        info = _cg_parse_key(data)
        if not info:
            new["err"] = "nepoznat odgovor"
            _cg_account_save(new)
            return new if new.get("ts") else None
        new = {**info, "ts": int(now), "tried": int(now), "day": _day(now), "n_at": int(n_at or 0)}
        _cg_account_save(new)
        return new
    except Exception:  # noqa: BLE001 - never raises
        try:
            d = _cg_account_load()
            return d if d.get("ts") else None
        except Exception:  # noqa: BLE001
            return None


def _cg_account_save(d):
    try:
        path = _cg_account_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass


def cg_account_line(now=None):
    """'coingecko račun: plan Analyst, ovaj mjesec 87.412 od 500.000 poziva, 500/min; dnevni strop 14.516 (iz plana)'
    from the cached reading; "" without a key."""
    now = now or _now()
    if not _cg_key_raw():
        return ""
    d = _cg_account_load()
    env = bool((os.environ.get("CG_DAILY_CALLS") or "").strip())
    cap = cg_cap(now)
    fresh = bool(d.get("ts")) and now - d["ts"] <= CG_ACCOUNT_VALID and _int(d.get("credit"))
    how = "CG_DAILY_CALLS" if env else ("iz plana" if fresh else "plan nepoznat")
    if not d.get("ts"):
        why = f" ({d['err']})" if d.get("err") else ""
        return f"coingecko račun: nije očitan{why}; dnevni strop {_fmt(cap)} ({how})"
    q = lambda v: _fmt(v) if v is not None else "?"  # noqa: E731
    age = time.strftime("%d.%m. %H:%M UTC", time.gmtime(d["ts"]))
    return (f"coingecko račun: plan {d.get('plan') or '?'}, ovaj mjesec {q(d.get('used'))} od {q(d.get('credit'))} "
            f"poziva, {q(d.get('rate'))}/min (očitano {age}); dnevni strop {_fmt(cap)} ({how})")


def set_cg_job(name):
    """Name this process's job for the CoinGecko budget (overrides the command line)."""
    _CG_JOB[0] = name or None


def _job_from_argv(argv):
    script = os.path.basename((argv or [""])[0] or "")
    sub = argv[1] if len(argv or []) > 1 else ""
    if script == "run_kol.py" and sub == "minute-loop":
        return "minute"
    if script == "run_learn.py" and sub == "masovno":
        return "masovno"
    fixed = {"run_range.py": "range", "run_momentum.py": "momentum", "run_scan.py": "scan"}
    if script in fixed:
        return fixed[script]
    if script.endswith(".py"):
        script = script[:-3]
    if script.startswith("run_"):
        script = script[4:]
    return script or "python"


def cg_job():
    """The job this process spends the CoinGecko budget for: the thread's cg_job_as(), else set_cg_job(), else
    CG_JOB, else the command line (run_kol.py minute-loop -> minute, run_learn.py masovno -> masovno, run_range.py ->
    range, ...)."""
    import sys
    return (getattr(_CG_LOCAL, "job", None) or _CG_JOB[0] or os.environ.get("CG_JOB")
            or _job_from_argv(sys.argv))


@contextlib.contextmanager
def cg_job_as(name):
    """14.11.: the calls of this thread inside the block count for `name` (the Autopilot chart's history in run_ui:
    "graf"), the rest of the process keeps its job; the day file then shows them apart."""
    old = getattr(_CG_LOCAL, "job", None)
    _CG_LOCAL.job = name or None
    try:
        yield
    finally:
        _CG_LOCAL.job = old


def zagreb_night(now=None):
    """01:00-06:00 Europe/Zagreb (the window of the heavy night jobs, ops/heavy.NIGHT)."""
    import datetime as _dt
    try:
        import zoneinfo
        h = _dt.datetime.fromtimestamp(now or _now(), zoneinfo.ZoneInfo("Europe/Zagreb")).hour
    except Exception:  # noqa: BLE001 - no tz data: CET
        h = (time.gmtime(now or _now()).tm_hour + 1) % 24
    return 1 <= h < 6


def _cg_day_file():
    """10.11. (Jure: "postavljen je, što se ne koristi?"): the day's count lived in GATE_DIR (/tmp), which every deploy
    empties, so the budget started again from 0 after each of today's 9 deploys and the cap held nothing. It is kept
    on the persistent disk (DATA_DIR) when there is one; GATE_DIR (tests, a laptop) otherwise."""
    data = os.environ.get("DATA_DIR")
    base = data if data and os.path.isdir(data) else GATE_DIR
    return os.path.join(base, "coingecko.day")


def _cg_blank(day):
    return {"day": day, "n": 0, "jobs": {}, "free": {}, "e429": {}, "last429": 0}


def _cg_parse(text, day):
    """The day file -> state dict for `day` (a new day starts blank). Before 11.11. the file was "YYYY-MM-DD n"."""
    text = (text or "").strip()
    st = None
    if text.startswith("{"):
        try:
            st = json.loads(text)
        except ValueError:
            st = None
    elif text:
        try:
            d, n = text.split()[:2]
            st = {"day": d, "n": int(n), "jobs": {}}
        except ValueError:
            st = None
    if not isinstance(st, dict) or st.get("day") != day:
        return _cg_blank(day)
    out = _cg_blank(day)
    out.update({k: v for k, v in st.items() if k in out})
    return out


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _cg_read(now=None):
    now = now or _now()
    try:
        with open(_cg_day_file()) as f:
            return _cg_parse(f.read(), _day(now))
    except OSError:
        return _cg_blank(_day(now))


def _cg_update(fn, now=None):
    """Read-modify-write the day file under an exclusive lock: fn(state) -> result. None when the file cannot be used."""
    now = now or _now()
    try:
        os.makedirs(os.path.dirname(_cg_day_file()), exist_ok=True)
        with open(_cg_day_file(), "a+") as f:
            try:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            f.seek(0)
            st = _cg_parse(f.read(), _day(now))
            res = fn(st)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(st, separators=(",", ":")))
            return res
    except OSError:
        return None


def allowance(cap, now):
    """Key calls the whole bot may have spent by now: cap x (UTC hours begun) / 24."""
    return cap * min(1.0, (time.gmtime(now).tm_hour + 1) / 24)


def cg_allow(st, job, now, cap=None, night=None):
    """(True, "") when `job` may spend one paid call now, else (False, why). Pure: st is the day state."""
    cap = cg_cap(now) if cap is None else cap
    n = st.get("n", 0)
    if n >= cap:
        return False, "dnevni strop"
    if job == "masovno":
        night = zagreb_night(now) if night is None else night
        if not night:
            return False, "masovno danju ide na besplatni GeckoTerminal"
        if (st.get("jobs") or {}).get("masovno", 0) >= int(_env_f("CG_MASOVNO_NIGHT", 1000)):
            return False, "masovno: noćni strop ključa"
    limit = allowance(cap, now)
    if job not in CG_PRIORITY:
        limit -= cap / 24 * _env_f("CG_RESERVE", 0.5)
    if n >= limit:
        return False, "satni dio potrošen"
    return True, ""


def cg_night_cap(cap=None):
    """Calls the key may serve to a night job before 06:00 Zagreb: CG_NIGHT_SHARE (0.4) of the day's budget
    (11.11., Jure: the 3000 were gone by 02:38 UTC to the night jobs; PR #133). events/remeasure.cap_left reads it."""
    cap = cg_cap() if cap is None else cap
    return int(cap * _env_f("CG_NIGHT_SHARE", 0.4))


def cg_used(today=None):
    """(calls through the key today (UTC), the day's budget)."""
    st = _cg_read() if today is None else _cg_read_day(today)
    return st["n"], cg_cap()


def _cg_read_day(day):
    try:
        with open(_cg_day_file()) as f:
            return _cg_parse(f.read(), day)
    except OSError:
        return _cg_blank(day)


def _cg_take(now=None, job=None):
    """One call from today's budget for this job: True when the key may be used for it."""
    now = now or _now()
    job = job or cg_job()
    cap = cg_cap(now)

    def take(st):
        ok, _ = cg_allow(st, job, now, cap)
        if not ok:
            return False
        st["n"] += 1
        st["jobs"][job] = st["jobs"].get(job, 0) + 1
        return st["n"]
    n = _cg_update(take, now)
    if n is None:   # the disk said no: the call goes through, as before
        return True
    if n and (n % 500 == 0 or n == cap):   # for the weekly cost report (CLAUDE.md: cost per source)
        print(f"coingecko: {n} poziva danas od {cap}", flush=True)
    return bool(n)


def _cg_free(job=None, now=None):
    """A GeckoTerminal call that went to the free API although the key is set (the daily cost line counts them)."""
    job = job or cg_job()

    def add(st):
        st["free"][job] = st["free"].get(job, 0) + 1
    _cg_update(add, now)


def note_429(url, now=None):
    """An HTTP 429 from GeckoTerminal or CoinGecko: counted per UTC hour, and its time (learn/masovno pauses on it)."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if not (host.endswith("geckoterminal.com") or host.endswith("coingecko.com")):
        return
    now = now or _now()
    hour = time.strftime("%H", time.gmtime(now))

    def add(st):
        st["e429"][hour] = st["e429"].get(hour, 0) + 1
        st["last429"] = int(now)
    _cg_update(add, now)


def gt_last_429(now=None):
    """Unix time of today's (UTC) last 429 from GeckoTerminal / CoinGecko, 0 when none."""
    return int(_cg_read(now).get("last429") or 0)


def cg_status(now=None):
    """The day state plus cap and the allowance by now (the hourly line and the daily cost line)."""
    now = now or _now()
    st = _cg_read(now)
    cap = cg_cap(now)
    return {**st, "cap": cap, "allowed": int(allowance(cap, now)), "key": bool(_cg_key_raw())}


def _fmt(n):
    return f"{int(n):,}".replace(",", ".")


def cg_hour_line(now=None, queue=None, account=False):
    """One log line a UTC hour (kol/minute.loop): the key spent vs allowed by now, the 429 of the last hour, the
    minute queue and the spend per job (11.11., Jure: preporuka 1). account=True (the loop; 20.11.): first refresh the
    plan reading (cg_account: one GET /key at most every 6 h) and append its line."""
    now = now or _now()
    if account and _cg_key_raw():
        cg_account(now)
        acc = cg_account_line(now)
        return _cg_hour_line(now, queue) + (f" | {acc}" if acc else "")
    return _cg_hour_line(now, queue)


def _cg_hour_line(now, queue):
    st = cg_status(now)
    h = time.gmtime(now).tm_hour
    prev = st["e429"].get(f"{(h - 1) % 24:02d}", 0) if h else 0
    jobs = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(st["jobs"].items(), key=lambda kv: -kv[1])) or "-"
    free = sum(st["free"].values())
    q = f"; red minutnih svijeća {queue} tokena" if queue is not None else ""
    if not st["key"]:
        return f"coingecko sat {h:02d} UTC: ključ nije postavljen; 429 prošli sat {prev} (ovaj sat {st['e429'].get(f'{h:02d}', 0)}){q}"
    return (f"coingecko sat {h:02d} UTC: ključem {_fmt(st['n'])} / dopušteno {_fmt(st['allowed'])} do sad "
            f"(dnevni strop {_fmt(st['cap'])}), 429 prošli sat {prev} (ovaj sat {st['e429'].get(f'{h:02d}', 0)}), "
            f"besplatno {_fmt(free)}{q}; po poslu: {jobs}")


def cg_key():
    """The CoinGecko key when this job may spend a call of it now (today's budget, the hour's slice), else ""."""
    key = _cg_key_raw()
    if not key:
        return ""
    return key if cg_allow(_cg_read(), cg_job(), _now())[0] else ""


def cg_configured():
    """True when a CoinGecko key is set at all (whatever is left of today's budget)."""
    return bool(_cg_key_raw())


def _cg_route(url, headers):
    """(url, headers) for a GeckoTerminal URL when the CoinGecko key is set and this job may spend a call of it,
    else unchanged (the free GeckoTerminal; counted per job when the key is set)."""
    if not url.startswith(GT_BASE) or not _cg_key_raw():
        return url, headers
    if not _cg_take():
        _cg_free()
        return url, headers
    key = _cg_key_raw()
    demo = os.environ.get("COINGECKO_DEMO") == "1"
    base = "https://api.coingecko.com/api/v3/onchain" if demo else "https://pro-api.coingecko.com/api/v3/onchain"
    return base + url[len(GT_BASE):], {**(headers or {}), ("x-cg-demo-api-key" if demo else "x-cg-pro-api-key"): key}


def _shared(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    # 11.11.: the paid host is always on the paid gate; a GeckoTerminal URL only when this job may spend the key now
    # (with the hourly budget one job can be on the key while another one runs on the free API at its pace)
    if (host.endswith("coingecko.com") and _cg_key_raw()) or (host.endswith("geckoterminal.com") and cg_key()):
        return "coingecko.com", float(os.environ.get("CG_GAP", "0.25"))
    for suffix, gap in SHARED_GAP.items():
        if host.endswith(suffix):
            return suffix, gap
    return None, 0


def _gate(suffix, fn):
    """Run fn(state) -> state under an exclusive lock on the host's gate file; state = [next_ok, paused_until]."""
    os.makedirs(GATE_DIR, exist_ok=True)
    with open(os.path.join(GATE_DIR, suffix), "a+") as f:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        f.seek(0)
        try:
            state = [float(x) for x in f.read().split()[:3]]
        except ValueError:
            state = []
        state = (state + [0.0, 0.0, 0.0])[:3]   # [next_ok, paused_until, gap learned from 429s (0 = default)]
        new = fn(state)
        f.seek(0)
        f.truncate()
        f.write(f"{new[0]} {new[1]} {new[2] if len(new) > 2 else 0.0}")
        return new


def _reserve_path(suffix):
    return os.path.join(GATE_DIR, suffix + ".reserved")


def reserve(url, seconds):
    """9.11.: hold a shared-limit host for this process for `seconds`: other processes' calls there return None at
    once (and cooling() tells them how long), so the job that matters most (the KOL call measurement, 0 tokens all
    morning behind masovno/status/dugo/sessions) gets the whole free limit for its budget. Reserving again extends."""
    suffix, _ = _shared(url)
    if not suffix:
        return
    try:
        os.makedirs(GATE_DIR, exist_ok=True)
        with open(_reserve_path(suffix), "w") as f:
            f.write(f"{time.time() + seconds} {os.getpid()}")
    except OSError:
        pass


def release(url):
    suffix, _ = _shared(url)
    if not suffix:
        return
    try:
        with open(_reserve_path(suffix)) as f:
            _, pid = f.read().split()[:2]
        if int(pid) == os.getpid():
            os.remove(_reserve_path(suffix))
    except (OSError, ValueError, IndexError):
        pass


def reserved_by_other(url):
    """Seconds another process still holds this shared host for (0 = free, or ours)."""
    suffix, _ = _shared(url)
    if not suffix or (cg_key() and suffix == "coingecko.com"):   # paid capacity: nobody needs it to themselves
        return 0.0
    try:
        with open(_reserve_path(suffix)) as f:
            until, pid = f.read().split()[:2]
    except (OSError, ValueError, IndexError):
        return 0.0
    if int(pid) == os.getpid():
        return 0.0
    return max(0.0, float(until) - time.time())


def cooling(url):
    """Seconds until a shared-limit host may be called again: after a 429, or while another process holds it
    (reserve()). 0 = go."""
    suffix, _ = _shared(url)
    if not suffix:
        return 0.0
    try:
        st = _gate(suffix, lambda s: s)
    except OSError:
        return 0.0
    return max(0.0, st[1] - time.time(), reserved_by_other(url))


GAP_GROW, GAP_SHRINK, GAP_MAX = 1.5, 0.97, 20.0   # 9.11.: the limit we really get on Render's shared egress is
                                                   # below the documented 30/min; the gap learns it (AIMD)


def limited(url, retry_after=0):
    """Note a 429 from a shared-limit host: every process pauses before its next call there, and the shared gap
    between calls grows by GAP_GROW (up to GAP_MAX s) so the pause does not just repeat."""
    suffix, gap = _shared(url)
    if suffix:
        until = time.time() + max(SHARED_COOLDOWN, retry_after or 0)
        try:
            _gate(suffix, lambda s: [max(s[0], until), max(s[1], until), min(GAP_MAX, max(s[2] or gap, gap) * GAP_GROW)])
        except OSError:
            pass


def eased(url):
    """A successful call: the learned gap shrinks back slowly towards the default."""
    suffix, gap = _shared(url)
    if suffix:
        try:
            _gate(suffix, lambda s: [s[0], s[1], (max(gap, s[2] * GAP_SHRINK) if s[2] else 0.0)])
        except OSError:
            pass


def current_gap(url):
    suffix, gap = _shared(url)
    if not suffix:
        return 0.0
    try:
        st = _gate(suffix, lambda s: s)
    except OSError:
        return gap
    return max(gap, st[2] or 0.0)


def _pace_shared(url):
    suffix, gap = _shared(url)
    if not suffix:
        return

    def take(s):
        now = time.time()
        start = max(now, s[0], s[1])
        g = max(gap, s[2] or 0.0)
        return [start + g, s[1], s[2], start]   # the fourth value is only for us: when this call may go (not stored)
    try:
        st = _gate(suffix, take)
    except OSError:
        return
    wait = st[3] - time.time() if len(st) > 3 else 0
    if wait > 0:
        time.sleep(min(wait, 180))


def _pace(url):
    _pace_shared(url)
    host = urllib.parse.urlsplit(url).hostname or ""
    for suffix, gap in MIN_GAP.items():
        if host.endswith(suffix):
            wait = _last_call.get(suffix, 0) + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_call[suffix] = time.monotonic()


def _fetch(req, timeout, retries=None):
    """GET with retries on 429/5xx, honouring Retry-After (capped at 60 s)."""
    retries = RETRIES if retries is None else retries
    for attempt in range(retries + 1):
        _pace(req.full_url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
            if meter:
                meter.helius(req.full_url, req.data, data)
            eased(req.full_url)
            return data
        except urllib.error.HTTPError as e:
            if meter:
                meter.helius(req.full_url, req.data, error=True)
            try:
                delay = float(e.headers.get("Retry-After") or 0)
            except (ValueError, AttributeError):
                delay = 0
            if e.code == 429:
                limited(req.full_url, delay)
                note_429(req.full_url)
            elif e.code == 403 and _shared(req.full_url)[0]:   # 9.11. (audit P24): GeckoTerminal's 403 burst is a
                limited(req.full_url, SHARED_403_PAUSE)        # block too: every process pauses, not just this call
            if attempt == retries or not (e.code == 429 or e.code >= 500):
                raise
            time.sleep(min(60, max(delay, 2 ** attempt)))


def ttl_class(ttl):
    t = ttl or 0
    return next((c for c, lim in TTL_CLASSES if t <= lim), TTL_CLASSES[-1][0])


def _named(digest, ext, ttl):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{ttl_class(ttl)}-{digest}{ext}")


def _fresh(digest, ext, ttl):
    """The cached file a reader with this TTL may use (its class name, else the name from before 12.11.), or None."""
    if not ttl:
        return None
    for p in (_named(digest, ext, ttl), os.path.join(CACHE_DIR, digest + ext)):
        try:
            if time.time() - os.path.getmtime(p) < ttl:
                return p
        except OSError:
            pass
    return None


def _cache_path(key, ttl=None):
    return _named(hashlib.sha1(key.encode()).hexdigest(), ".json", ttl)


_CLASS_AGE = dict(TTL_CLASSES)


def _limit(path, max_age, age=None):
    """How old this file may get (seconds): its TTL class, the rpc- prefix, or for a file from before 12.11.
    LEGACY_MAX_AGE (paid Helius answers: max_age; the file is read only once it is that old)."""
    name = os.path.basename(path)
    pre = next((a for p, a in SHORT_LIVED.items() if name.startswith(p)), None)
    if pre is not None:
        return min(pre, max_age)
    if len(name) > 2 and name[1] == "-" and name[0] in _CLASS_AGE:
        return min(_CLASS_AGE[name[0]], max_age)
    if age is not None and age < min(LEGACY_MAX_AGE, max_age):
        return min(LEGACY_MAX_AGE, max_age)
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        if any(m in head for m in PAID_MARKS):
            return max_age
    except OSError:
        pass
    return min(LEGACY_MAX_AGE, max_age)


def _kind(path):
    """The file's kind for the log and the eviction order: s / m / l / w (TTL class), rpc, paid (a Helius answer from
    before 12.11.), stari (another file from before)."""
    name = os.path.basename(path)
    if name.startswith("rpc-"):
        return "rpc"
    if len(name) > 2 and name[1] == "-" and name[0] in _CLASS_AGE:
        return name[0]
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        return "paid" if any(m in head for m in PAID_MARKS) else "stari"
    except OSError:
        return "stari"


EVICT_ORDER = {"rpc": 0, "s": 0, "stari": 0, "m": 1, "l": 2, "w": 3, "paid": 3}   # cheapest to fetch again first


def prune(max_mb=None, max_age=None):
    """Delete cache files older than their limit (_limit: no reader can use them); then, while the cache is over
    max_mb, the cheapest to fetch again first (EVICT_ORDER: short TTL and old-format files, then 6 h, 24 h, finally
    the week-long and paid Helius answers), oldest first within each. Returns (files, MB) removed."""
    max_mb = CACHE_MAX_MB if max_mb is None else max_mb
    max_age = CACHE_MAX_AGE if max_age is None else max_age
    if not os.path.isdir(CACHE_DIR):
        return 0, 0.0
    files = []
    for e in os.scandir(CACHE_DIR):
        try:
            st = e.stat()
            files.append((st.st_mtime, st.st_size, e.path))
        except OSError:
            pass
    files.sort()
    total, now, gone, freed = sum(f[1] for f in files), time.time(), 0, 0
    left = []
    for mtime, size, path in files:
        if now - mtime < _limit(path, max_age, now - mtime):
            left.append((mtime, size, path))
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        gone, freed = gone + 1, freed + size
    if total > max_mb * 1e6:
        for mtime, size, path in sorted(left, key=lambda f: (EVICT_ORDER.get(_kind(f[2]), 0), f[0])):
            if total <= max_mb * 1e6:
                break
            try:
                os.remove(path)
            except OSError:
                continue
            total -= size
            gone, freed = gone + 1, freed + size
    return gone, freed / 1e6


def breakdown():
    """{kind: MB} of what the cache holds now (the hourly log line: what fills it)."""
    out = {}
    if not os.path.isdir(CACHE_DIR):
        return out
    for e in os.scandir(CACHE_DIR):
        try:
            k = _kind(e.path)
            out[k] = out.get(k, 0.0) + e.stat().st_size / 1e6
        except OSError:
            pass
    return {k: round(v, 1) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}


def _write(path, text):
    """Write a cache file; never let a full disk break the caller (the data is already in hand)."""
    global _writes
    _writes += 1
    if _writes % PRUNE_EVERY == 1:
        prune()
    from ops import disk
    if disk.low("HTTP cache"):
        return
    try:
        with open(path, "w") as f:
            f.write(text)
    except OSError:
        try:
            os.remove(path)
        except OSError:
            pass


def cache_get(key, ttl):
    path = _fresh(hashlib.sha1(key.encode()).hexdigest(), ".json", ttl)
    if path:
        with open(path) as f:
            return json.load(f)
    return None


def cache_put(key, data, ttl=None):
    """ttl: the TTL its readers use (names the file's class, so prune keeps it as long as it is useful)."""
    _write(_cache_path(key, ttl), json.dumps(data))


def get_json(url, params=None, ttl=CACHE_TTL, timeout=30, headers=None, retries=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    digest = hashlib.sha1(url.encode()).hexdigest()
    hit = _fresh(digest, ".json", ttl)
    if hit:
        with open(hit) as f:
            return json.load(f)
    path = _named(digest, ".json", ttl)
    if reserved_by_other(url):   # another job holds this shared host: no call, the caller retries next round
        return None
    url, headers = _cg_route(url, headers)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    data = _fetch(req, timeout, retries)
    _write(path, json.dumps(data))
    return data


CG_PUBLIC = "https://api.coingecko.com/api/v3"


def cg_get_json(url, params=None, ttl=CACHE_TTL, timeout=30, retries=None):
    """20.11.: a public CoinGecko REST URL (https://api.coingecko.com/api/v3/...) the way makroinf/prices does it: with
    the key set and while this job may spend a call of it (_cg_take: the day budget, the hour's slice, counted per job),
    the same path on the paid host with the key in a header; else, or when the paid call fails, the public endpoint
    (with the key set that call is counted as free). Cached under the public URL either way, so a cache hit costs
    nothing and never takes from the budget. Without the key this is exactly get_json(url, ...)."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    key = _cg_key_raw()
    if not key or not url.startswith(CG_PUBLIC):
        return get_json(url, None, ttl=ttl, timeout=timeout, retries=retries)
    digest = hashlib.sha1(url.encode()).hexdigest()
    hit = _fresh(digest, ".json", ttl)
    if hit:
        with open(hit) as f:
            return json.load(f)
    data = None
    if _cg_take():
        demo = os.environ.get("COINGECKO_DEMO") == "1"
        base = CG_PUBLIC if demo else "https://pro-api.coingecko.com/api/v3"
        hdr = {("x-cg-demo-api-key" if demo else "x-cg-pro-api-key"): key}
        req = urllib.request.Request(base + url[len(CG_PUBLIC):],
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json", **hdr})
        try:
            data = _fetch(req, timeout, retries)
        except Exception:  # noqa: BLE001 - the public endpoint below
            data = None
    if data is None:
        _cg_free()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        data = _fetch(req, timeout, retries)
    _write(_named(digest, ".json", ttl), json.dumps(data))
    return data


def get_text(url, params=None, ttl=CACHE_TTL, timeout=30):
    """Like get_json, for RSS/XML; cached as text."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    digest = hashlib.sha1(url.encode()).hexdigest()
    hit = _fresh(digest, ".txt", ttl)
    if hit:
        with open(hit) as f:
            return f.read()
    path = _named(digest, ".txt", ttl)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(RETRIES + 1):
        _pace(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if attempt == RETRIES or not (e.code == 429 or e.code >= 500):
                raise
            time.sleep(min(60, 2 ** attempt))
    _write(path, text)
    return text
