"""Minimal HTTP helper (stdlib only) with a small on-disk cache."""
import hashlib
import json
import os
import tempfile
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
CACHE_MAX_MB = float(os.environ.get("CAL_CACHE_MAX_MB", "250"))
CACHE_MAX_AGE = int(os.environ.get("CAL_CACHE_MAX_AGE", str(7 * 86400)))
SHORT_LIVED = {"rpc-": 3600}   # wallets/rpc.py caches Helius RPC for 10 min; those files are dead after that
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
def _cg_day_file():
    """10.11. (Jure: "postavljen je, što se ne koristi?"): the day's count lived in GATE_DIR (/tmp), which every deploy
    empties, so the budget started again from 0 after each of today's 9 deploys and the cap held nothing. It is kept
    on the persistent disk (DATA_DIR) when there is one; GATE_DIR (tests, a laptop) otherwise."""
    data = os.environ.get("DATA_DIR")
    base = data if data and os.path.isdir(data) else GATE_DIR
    return os.path.join(base, "coingecko.day")


# 11.11. (Jure: the 3000 were gone by 02:38 UTC to the night jobs): from the UTC day's start until CG_NIGHT_END_H
# (06:00 Zagreb, the end of the heavy night window, CLAUDE.md 01-06) the key serves at most CG_NIGHT_SHARE (40 %) of
# the day; past it the night's calls go to the free GeckoTerminal at its pace, and the rest of the day's calls is kept
# for the range list and the day's rounds.
CG_NIGHT_END_H = 6


def cg_night(now=None):
    """True from the UTC day's start until 06:00 Zagreb (the evening hour(s) before midnight UTC are not night here:
    they belong to the previous paid day)."""
    now = time.time() if now is None else now
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        z = _dt.datetime.fromtimestamp(now, ZoneInfo("Europe/Zagreb"))
    except Exception:  # noqa: BLE001 - no tz data: no night cap
        return False
    return z.hour < CG_NIGHT_END_H and time.gmtime(now).tm_hour < 12


def cg_night_cap(cap=None):
    """The calls the key may serve before 06:00 Zagreb: CG_NIGHT_SHARE (0.4) of the day's budget."""
    cap = cap if cap is not None else int(float(os.environ.get("CG_DAILY_CALLS", "3000")))
    return int(cap * float(os.environ.get("CG_NIGHT_SHARE", "0.4")))


def cg_limit(cap=None, now=None):
    """The key's limit right now: the night cap at night, else the day's budget."""
    cap = cap if cap is not None else int(float(os.environ.get("CG_DAILY_CALLS", "3000")))
    return cg_night_cap(cap) if cg_night(now) else cap


def cg_used(today=None):
    """(calls through the key today (UTC), the day's budget)."""
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    cap = int(float(os.environ.get("CG_DAILY_CALLS", "3000")))
    try:
        with open(_cg_day_file()) as f:
            day, n = f.read().split()[:2]
        return (int(n) if day == today else 0), cap
    except (OSError, ValueError):
        return 0, cap


CG_TALLY = "coingecko_kljuc"   # usage.db service: the key's calls per script and kind (who spends the 3000)


def _cg_kind(url):
    """The kind of a GeckoTerminal call for the per-script tally: ohlcv, pools, trending_pools, tokens, ..."""
    path = urllib.parse.urlsplit(url or "").path
    if "/ohlcv/" in path:
        return "ohlcv"
    parts = [x for x in path.split("/") if x]
    i = parts.index("solana") + 1 if "solana" in parts else len(parts) - 1
    return parts[i] if 0 <= i < len(parts) else "?"


def cg_by_script(day0=None):
    """[(script, calls)] of the key today (UTC) from usage.db, most first. 11.11. (Jure: "javi koliko od 3.000 dnevno
    trošimo"): on 11.11. the whole day was gone by 02:38 UTC, before the range list's first real round."""
    if meter is None:
        return []
    day0 = int(day0 if day0 is not None else time.time() // 86400 * 86400)
    try:
        meter.flush()
        con = meter.connect()
        try:
            return [(s, int(n)) for s, n in con.execute(
                "SELECT script, SUM(calls) FROM usage WHERE service=? AND hour>=? AND hour<? GROUP BY script "
                "ORDER BY 2 DESC", (CG_TALLY, day0, day0 + 86400))]
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - a missing usage.db loses only the breakdown
        return []


def _cg_take(url=None):
    """One call from today's budget: True when the key may be used for it."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    cap = int(float(os.environ.get("CG_DAILY_CALLS", "3000")))
    try:
        os.makedirs(os.path.dirname(_cg_day_file()), exist_ok=True)
        with open(_cg_day_file(), "a+") as f:
            try:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            f.seek(0)
            try:
                day, n = f.read().split()[:2]
                n = int(n) if day == today else 0
            except ValueError:
                n = 0
            if n >= cg_limit(cap):
                return False
            f.seek(0)
            f.truncate()
            f.write(f"{today} {n + 1}")
        if meter is not None:
            meter.record(CG_TALLY, _cg_kind(url))
        night = cg_night()
        if night and n + 1 == cg_night_cap(cap):
            print(f"coingecko: noćni strop {n + 1}/{cap} ({(n + 1) / cap:.0%} dana) dosegnut u "
                  f"{time.strftime('%H:%M', time.gmtime())} UTC: do 06:00 (Zagreb) besplatni GT, ostatak za dan", flush=True)
        if (n + 1) % 500 == 0 or n + 1 == cap:   # for the weekly cost report (CLAUDE.md: cost per source)
            by = ", ".join(f"{s} {c}" for s, c in cg_by_script()[:6])
            print(f"coingecko: {n + 1} poziva danas od {cap}" + (f" (po skripti: {by})" if by else "")
                  + (f", ključ potrošen u {time.strftime('%H:%M', time.gmtime())} UTC" if n + 1 == cap else ""),
                  flush=True)
        return True
    except OSError:
        return True


def cg_key():
    """The CoinGecko key while today's budget lasts, else "" (the free API and its pace)."""
    key = _cg_key_raw()
    if not key:
        return ""
    used, cap = cg_used()
    return key if used < cg_limit(cap) else ""   # 11.11.: at night only up to the night cap (then the free API's pace)


def _cg_route(url, headers):
    """(url, headers) for a GeckoTerminal URL when the CoinGecko key is set, else unchanged."""
    key = cg_key()
    if not key or not url.startswith(GT_BASE) or not _cg_take(url):
        return url, headers
    demo = os.environ.get("COINGECKO_DEMO") == "1"
    base = "https://api.coingecko.com/api/v3/onchain" if demo else "https://pro-api.coingecko.com/api/v3/onchain"
    return base + url[len(GT_BASE):], {**(headers or {}), ("x-cg-demo-api-key" if demo else "x-cg-pro-api-key"): key}


def _shared(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if cg_key() and (host.endswith("geckoterminal.com") or host.endswith("coingecko.com")):
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
            elif e.code == 403 and _shared(req.full_url)[0]:   # 9.11. (audit P24): GeckoTerminal's 403 burst is a
                limited(req.full_url, SHARED_403_PAUSE)        # block too: every process pauses, not just this call
            if attempt == retries or not (e.code == 429 or e.code >= 500):
                raise
            time.sleep(min(60, max(delay, 2 ** attempt)))


def _cache_path(key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest() + ".json")


def prune(max_mb=None, max_age=None):
    """Delete expired cache files, then the oldest until the cache is under max_mb. Returns (files, MB) removed."""
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
    short = lambda p: next((age for pre, age in SHORT_LIVED.items()  # noqa: E731
                             if os.path.basename(p).startswith(pre)), None)
    for mtime, size, path in files:
        age = short(path)
        if now - mtime < max_age and total <= max_mb * 1e6 and (age is None or now - mtime < age):
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        gone, freed = gone + 1, freed + size
    return gone, freed / 1e6


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
    path = _cache_path(key)
    if ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as f:
            return json.load(f)
    return None


def cache_put(key, data):
    _write(_cache_path(key), json.dumps(data))


def get_json(url, params=None, ttl=CACHE_TTL, timeout=30, headers=None, retries=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as f:
            return json.load(f)
    if reserved_by_other(url):   # another job holds this shared host: no call, the caller retries next round
        return None
    url, headers = _cg_route(url, headers)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    data = _fetch(req, timeout, retries)
    _write(path, json.dumps(data))
    return data


def get_text(url, params=None, ttl=CACHE_TTL, timeout=30):
    """Like get_json, for RSS/XML; cached as text."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as f:
            return f.read()
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
