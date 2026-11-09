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
GATE_DIR = os.environ.get("HTTP_GATE_DIR") or os.path.join(tempfile.gettempdir(), "crypto-bot-gate")


def _shared(url):
    host = urllib.parse.urlsplit(url).hostname or ""
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
    if not suffix:
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
