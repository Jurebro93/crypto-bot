"""Token icons from our own address: /img/t/<mint>.webp (15.11., vlasnik: "slike se ne učitavaju").

Why: the home page boards and the coin pages linked every icon straight to where Jupiter's list points
(static.datapi.jup.ag, DexScreener's CDN, IPFS gateways). Checked in Chromium on 15.11.: ipfs.io answers an embedded
image with 403 + Cross-Origin-Resource-Policy: same-origin (net::ERR_BLOCKED_BY_RESPONSE; servers get 429), and
gateway.pinata.cloud blocks it the same way, so 41 of the top 100 icons were hidden by onerror without a trace.
Some originals are 2.6 MB PNGs shown at 22 px.

Now the server fetches an icon once, shrinks it to PX x PX webp (a few kB) and keeps it on disk (DATA_DIR/imgcache/t,
at most ICON_CACHE_MAX_MB, oldest out first); browsers and Cloudflare keep it a week. Sources, in this order:
  1. the icon link we already hold (public.db coins.icon = Jupiter's list), IPFS links tried on several gateways;
  2. Jupiter's token search by mint (lite-api.jup.ag, free, no key): icon (usually the token's metadata image);
  3. DexScreener's token API by mint (free, no key): info.imageUrl (imagedelivery.net / cdn.dexscreener.com).
When nothing works: a small SVG, the symbol's initials on a brand-coloured circle (never an empty hole), cached for
15 min; the miss is remembered for MISS_RETRY_S so a dead icon does not cost a fetch on every visit.
Only https on port 443 (certificate checked), never a private address, at most MAX_IN bytes, at most FETCHES at once.
deploy_wait.py serves the cached files (or the placeholder) during a deploy without fetching anything (cached()).
"""
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
ROUTE = re.compile(r"^/img/t/([1-9A-HJ-NP-Za-km-z]{32,44})\.webp$")
PX = int(os.environ.get("ICON_PX", "96"))                       # 22-44 px on the pages, sharp on a 2x phone screen
MAX_MB = float(os.environ.get("ICON_CACHE_MAX_MB", "40"))      # ~4 kB each: room for ~10k icons
MAX_IN = 6_000_000            # biggest original we read (bytes)
TIMEOUT_S = 6                 # one source
BUDGET_S = 14                 # all sources of one icon together
WAIT_S = 10                   # a visitor's request waits at most this long for a free fetch slot
FETCHES = int(os.environ.get("ICON_FETCHES", "2"))   # fetches at the same time (each may hold a decoded image)
MAX_PIXELS = 12_000_000       # a bigger original is skipped (decoded RGBA ~48 MB; the server has 512 MB)
MISS_RETRY_S = 6 * 3600
CACHE_OK = "public, max-age=604800, stale-while-revalidate=86400"
CACHE_PLACEHOLDER = "public, max-age=900"
CACHE_BUSY = "public, max-age=60"
UA = "MemeSonar/1.0 (+https://memesonar.app)"
JUP_SEARCH = "https://lite-api.jup.ag/tokens/v2/search?query={mint}"
DEX_TOKEN = "https://api.dexscreener.com/tokens/v1/solana/{mint}"
# Public IPFS gateways, first to last. 15.11. from the server: ipfs.filebase.io, quicknode and both Pinata gateways
# answered 200; dweb.link and ipfs.io 429 (ipfs.io is being retired, Sunset header); nftstorage.link only redirects
# to ipfs.io; cloudflare-ipfs.com no longer answers (Cloudflare closed it), so it is not on the list.
GATEWAYS = ("https://ipfs.filebase.io/ipfs/", "https://quicknode.quicknode-ipfs.com/ipfs/",
            "https://dweb.link/ipfs/", "https://ipfs.io/ipfs/", "https://pump.mypinata.cloud/ipfs/",
            "https://gateway.pinata.cloud/ipfs/", "https://nftstorage.link/ipfs/")
_PUBLIC_GW = {"ipfs.io", "dweb.link", "nftstorage.link", "w3s.link", "cloudflare-ipfs.com", "cf-ipfs.com",
              "gateway.pinata.cloud", "gateway.ipfs.io"}
COLORS = ("#4f46e5", "#0fb5a0", "#7c3aed", "#0ea5e9", "#db2777", "#f59e0b", "#16a34a", "#0b1220")

_slots = threading.BoundedSemaphore(FETCHES)
_locks = {}
_locks_lock = threading.Lock()
_size = {"bytes": None, "writes": 0}


def cache_dir():
    if os.environ.get("ICON_CACHE_DIR"):
        return os.environ["ICON_CACHE_DIR"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "imgcache", "t")
    return os.path.join(ROOT, "output", "imgcache", "t")


def url(mint):
    """Our address of a token's icon ("" for something that is not a mint)."""
    return f"/img/t/{mint}.webp" if MINT.fullmatch(str(mint or "")) else ""


def img(mint, size=22, style=""):
    """<img> of a token icon through our endpoint ("" when the mint is not valid)."""
    u = url(mint)
    if not u:
        return ""
    st = f" style=\"{style}\"" if style else ""
    return (f'<img src="{u}" alt="" width={size} height={size} loading=lazy decoding=async{st} '
            "onerror=\"this.style.visibility='hidden'\">")


# ---------- placeholder ---------------------------------------------------------------------------------------------
def _initials(sym, mint):
    s = re.sub(r"[^A-Za-z0-9]", "", str(sym or ""))
    return (s or str(mint or "?"))[:2].upper()


def placeholder(mint, sym=""):
    """Initials on a brand-coloured circle, as SVG bytes."""
    c = COLORS[int(hashlib.sha1(str(mint).encode()).hexdigest(), 16) % len(COLORS)]
    t = _initials(sym, mint)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{PX}" height="{PX}" viewBox="0 0 96 96">'
            f'<circle cx="48" cy="48" r="48" fill="{c}"/><text x="48" y="48" dy=".35em" text-anchor="middle" '
            f'font-family="Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif" font-size="{40 if len(t) < 2 else 36}" '
            f'font-weight="700" fill="#fff">{t}</text></svg>').encode("utf-8")


# ---------- fetching ------------------------------------------------------------------------------------------------
def _proxied():
    return bool(urllib.request.getproxies().get("https"))


def _safe(u):
    """True for an https link on the default port whose host is not a private, loopback or link-local address.
    Behind an outgoing proxy (a sandbox) the proxy resolves names, so only literal addresses are checked there."""
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return False
    if p.scheme != "https" or not p.hostname or p.port not in (None, 443) or p.username or p.password:
        return False
    host = p.hostname
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            return False
        if _proxied():
            return True
        try:
            ips = [ipaddress.ip_address(a[4][0].split("%")[0]) for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]
        except (OSError, ValueError):
            return False
    return bool(ips) and all(ip.is_global and not ip.is_multicast for ip in ips)


class _CheckRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _safe(newurl):
            raise urllib.error.HTTPError(newurl, code, "redirect to a link we do not fetch", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_CheckRedirects)


def _get(u, accept="image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.5", cap=MAX_IN, timeout=TIMEOUT_S):
    """Body bytes of an https link (None on any failure, an unsafe link or a body bigger than cap)."""
    if not _safe(u):
        return None
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": accept})
    try:
        with _opener.open(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            body = r.read(cap + 1)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return body if 0 < len(body) <= cap else None


def ipfs_candidates(u):
    """Links to try for one icon link: IPFS content (ipfs://, /ipfs/<cid>, <cid>.ipfs.<host>) on several gateways;
    a link on a dedicated gateway (e.g. <name>.myfilebase.com) is tried as it is first. Anything else: just itself."""
    u = str(u or "").strip()
    if not u:
        return []
    cid_path = None
    if u.startswith("ipfs://"):
        cid_path = u[7:].lstrip("/")
        if cid_path.startswith("ipfs/"):
            cid_path = cid_path[5:]
        u = ""
    else:
        try:
            p = urllib.parse.urlsplit(u)
        except ValueError:
            return []
        m = re.match(r"^/ipfs/(.+)$", p.path or "")
        sub = re.match(r"^([a-z0-9]{40,})\.ipfs\.", p.hostname or "")
        if m:
            cid_path = m.group(1)
        elif sub:
            cid_path = sub.group(1) + (p.path if p.path not in ("", "/") else "")
        if cid_path and (p.hostname or "") in _PUBLIC_GW:
            u = ""   # a crowded public gateway: our own order instead (ipfs.io first would be a 429 every time)
    out = [u] if u else []
    if cid_path:
        cid_path = cid_path.split("?", 1)[0].split("#", 1)[0]
        out += [g + cid_path for g in GATEWAYS]
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def to_webp(raw):
    """Square PX x PX webp of an image (first frame of a GIF); None when it is not an image Pillow reads."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        im = Image.open(io.BytesIO(raw))   # reads the header only: the size is known before anything is decoded
        if im.width * im.height > MAX_PIXELS:   # a decompression bomb or a poster: next source, memory stays free
            return None
        if im.format == "JPEG":
            im.draft("RGB", (PX * 2, PX * 2))   # JPEG decodes straight at a smaller scale
        im.seek(0)
        im.thumbnail((PX * 3, PX * 3))
        im = ImageOps.fit(im.convert("RGBA"), (PX, PX), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "WEBP", quality=82, method=4)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - SVG, HTML error pages, truncated files: try the next source
        return None


def known(mint):
    """(icon link, symbol) we already hold for a mint: the public coin list (public.db)."""
    try:
        from ui import coins as K
        con = K._ro(K.DB)
        if con is None:
            return "", ""
        try:
            r = con.execute("SELECT icon, symbol FROM coins WHERE mint = ?", (mint,)).fetchone()
        finally:
            con.close()
        return (r[0] or "", r[1] or "") if r else ("", "")
    except Exception:  # noqa: BLE001
        return "", ""


def _jupiter(mint):
    body = _get(JUP_SEARCH.format(mint=mint), accept="application/json", cap=2_000_000)
    try:
        for t in json.loads(body or b"[]"):
            if isinstance(t, dict) and t.get("id") == mint:
                return t.get("icon") or "", t.get("symbol") or ""
    except ValueError:
        pass
    return "", ""


def _dexscreener(mint):
    body = _get(DEX_TOKEN.format(mint=mint), accept="application/json", cap=2_000_000)
    try:
        for p in json.loads(body or b"[]"):
            if isinstance(p, dict) and (p.get("baseToken") or {}).get("address") == mint:
                return ((p.get("info") or {}).get("imageUrl") or "", (p.get("baseToken") or {}).get("symbol") or "")
    except ValueError:
        pass
    return "", ""


def fetch(mint, link="", sym=""):
    """(webp bytes or None, symbol): every source in turn within BUDGET_S."""
    t0 = time.time()
    tried = set()

    def attempt(u):
        for c in ipfs_candidates(u):
            if c in tried or time.time() - t0 > BUDGET_S:
                continue
            tried.add(c)
            raw = _get(c)
            out = to_webp(raw) if raw else None
            if out:
                return out
        return None

    if link:
        out = attempt(link)
        if out:
            return out, sym
    for src in (_jupiter, _dexscreener):
        if time.time() - t0 > BUDGET_S:
            break
        u, s = src(mint)
        sym = sym or s
        if u:
            out = attempt(u)
            if out:
                return out, sym
    return None, sym


# ---------- disk cache ----------------------------------------------------------------------------------------------
def _files(mint):
    d = cache_dir()
    return os.path.join(d, f"{mint}.webp"), os.path.join(d, f"{mint}.miss")


def cached(mint):
    """(status, headers, body) from the disk only, never fetching: the icon, or the placeholder (deploy_wait.py)."""
    if not MINT.fullmatch(str(mint or "")):
        return 404, {"Content-Type": "text/plain", "Cache-Control": "no-store"}, b""
    fp, miss = _files(mint)
    try:
        with open(fp, "rb") as f:
            return 200, {"Content-Type": "image/webp", "Cache-Control": CACHE_OK}, f.read()
    except OSError:
        pass
    sym = ""
    try:
        with open(miss, encoding="utf-8") as f:
            sym = json.load(f).get("sym") or ""
    except (OSError, ValueError, AttributeError):
        pass
    return 200, {"Content-Type": "image/svg+xml", "Cache-Control": CACHE_BUSY}, placeholder(mint, sym)


def _write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path)


def trim(max_bytes=None):
    """Oldest icons out until the folder is under 90 % of the cap; returns the bytes kept."""
    cap = int((max_bytes if max_bytes is not None else MAX_MB * 1e6))
    d = cache_dir()
    try:
        files = [(e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(d) if e.is_file()]
    except OSError:
        return 0
    total = sum(s for _, s, _ in files)
    if total > cap:
        for _, s, p in sorted(files):
            try:
                os.remove(p)
                total -= s
            except OSError:
                pass
            if total <= cap * 0.9:
                break
    _size["bytes"] = total
    return total


def _account(n):
    """Keep a running total of the folder size and trim when it passes the cap (a full scan every 200 writes)."""
    _size["writes"] += 1
    if _size["bytes"] is None or _size["writes"] % 200 == 0:
        trim()
    else:
        _size["bytes"] += n
        if _size["bytes"] > MAX_MB * 1e6:
            trim()


def _lock(mint):
    with _locks_lock:
        if len(_locks) > 2000:
            _locks.clear()
        return _locks.setdefault(mint, threading.Lock())


def get(mint, now=None):
    """(status, headers, body) for GET /img/t/<mint>.webp: the cached icon, a fresh fetch, or the placeholder."""
    if not MINT.fullmatch(str(mint or "")):
        return 404, {"Content-Type": "text/plain", "Cache-Control": "no-store"}, b""
    fp, miss = _files(mint)
    now = now or time.time()
    lk = _lock(mint)
    with lk:   # one fetch per icon: the other requests for it wait here, then read the file
        if os.path.isfile(fp):
            return cached(mint)
        try:
            with open(miss, encoding="utf-8") as f:
                m = json.load(f)
            if now - float(m.get("ts") or 0) < MISS_RETRY_S:
                return 200, {"Content-Type": "image/svg+xml", "Cache-Control": CACHE_PLACEHOLDER}, \
                    placeholder(mint, m.get("sym") or "")
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        link, sym = known(mint)
        if not _slots.acquire(timeout=WAIT_S):   # every slot busy for long: the initials now, the icon next time
            return 200, {"Content-Type": "image/svg+xml", "Cache-Control": CACHE_BUSY}, placeholder(mint, sym)
        try:
            body, sym = fetch(mint, link, sym)
        finally:
            _slots.release()
        try:
            if body:
                _write(fp, body)
                _account(len(body))
                try:
                    os.remove(miss)
                except OSError:
                    pass
            else:
                _write(miss, json.dumps({"ts": now, "sym": sym}).encode("utf-8"))
        except OSError as e:   # a full or read-only disk: still answer
            print(f"ikone tokena: ne mogu spremiti {mint[:6]}: {e}", flush=True)
    if body:
        return 200, {"Content-Type": "image/webp", "Cache-Control": CACHE_OK}, body
    return 200, {"Content-Type": "image/svg+xml", "Cache-Control": CACHE_PLACEHOLDER}, placeholder(mint, sym)


def warm(mints, pause_s=0.3):
    """Fetch the icons not on disk yet (after a coin list refresh), one at a time, so visitors find them ready."""
    n = 0
    for m in mints:
        if not MINT.fullmatch(str(m or "")) or os.path.isfile(_files(m)[0]):
            continue
        try:
            if get(m)[1].get("Content-Type") == "image/webp":
                n += 1
        except Exception as e:  # noqa: BLE001
            print(f"ikone tokena: {m[:6]}: {type(e).__name__}: {e}", flush=True)
        time.sleep(pause_s)
    return n
