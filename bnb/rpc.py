"""BSC JSON-RPC over the free public endpoints (stdlib urllib, no key, a generic User-Agent).

Measured 19.11. (bnb/izvori.md): bsc-rpc.publicnode.com serves eth_getLogs over <= 50,000 blocks a call, <= 20,000
results a call ("query exceeds max results 20000, retry with the range A-B"), logs back ~24 days (older: "Archive
requests require a personal token"), every log carries blockTimestamp, JSON-RPC batches of 200 work, and a filter
without an address is refused. rpc-bsc.48.club: 5,000 blocks, ~6 days, but a filter WITHOUT an address works (the
tracking poller: Transfer logs to watched addresses across all tokens). bsc.drpc.org: 100 blocks a call. The official
bsc-dataseed list refuses eth_getLogs ("limit exceeded").

Politeness: one call at a time per endpoint, at least rpc_gap_s between calls, backoff on 429 / 5xx (2, 4, 8 ... 60 s),
the next endpoint of the list on a refusal. Every call is counted (CALLS, per host and method) for the run line and
usage/ (usage.meter.record service "bsc-rpc", amount 0: free).
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

UA = "chain-research/0.1 (public data, low rate)"
CALLS = Counter()
LOCK = threading.Lock()
_LAST = {}


class RpcError(Exception):
    def __init__(self, msg, code=None, data=None):
        super().__init__(msg)
        self.code, self.data = code, data


def _meter(host, method, error=False):
    CALLS[(host, method)] += 1
    try:
        from usage import meter
        meter.record("bsc-rpc", f"{host}:{method}", 0.0, error=error)
    except Exception:  # noqa: BLE001 - counting never breaks a read
        pass


def _post(url, body, timeout, gap):
    host = urllib.parse.urlsplit(url).hostname or url
    with LOCK:
        wait = _LAST.get(host, 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _LAST[host] = time.monotonic()
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Rpc:
    """call(method, params) / batch([(method, params)]) against the first endpoint that answers; post: the transport
    (tests pass a fake: post(url, body) -> parsed JSON)."""

    def __init__(self, urls, gap=0.35, timeout=60, retries=4, post=None, sleep=time.sleep):
        self.urls = list(urls)
        self.gap, self.timeout, self.retries = gap, timeout, retries
        self.post = post or (lambda url, body: _post(url, body, self.timeout, self.gap))
        self.sleep = sleep
        self.n = 0

    def _send(self, body, method):
        last = None
        for url in self.urls:
            host = urllib.parse.urlsplit(url).hostname or url
            for attempt in range(self.retries + 1):
                try:
                    out = self.post(url, body)
                    self.n += 1
                    _meter(host, method)
                    return out
                except urllib.error.HTTPError as e:
                    _meter(host, method, error=True)
                    try:
                        txt = e.read()[:300].decode("utf-8", "replace")
                        payload = json.loads(txt)
                    except Exception:  # noqa: BLE001
                        payload = None
                    if isinstance(payload, dict) and payload.get("error"):   # a JSON-RPC error over HTTP 4xx
                        return payload
                    last = RpcError(f"HTTP {e.code}", e.code)
                    if e.code == 429 or e.code >= 500:
                        try:
                            ra = float(e.headers.get("Retry-After") or 0)
                        except (TypeError, ValueError):
                            ra = 0
                        self.sleep(min(60, max(ra, 2 ** (attempt + 1))))
                        continue
                    break
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                    _meter(host, method, error=True)
                    last = RpcError(f"{type(e).__name__}: {e}"[:160])
                    self.sleep(min(30, 2 ** attempt))
        raise last or RpcError("nema endpointa")

    def call(self, method, params):
        out = self._send({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, method)
        if isinstance(out, dict) and out.get("error"):
            err = out["error"]
            raise RpcError(str(err.get("message"))[:300], err.get("code"), err.get("data"))
        return out.get("result") if isinstance(out, dict) else None

    def batch(self, calls, size=200):
        """[(method, params)] -> [result or None] in order, size calls a request."""
        res = []
        for i in range(0, len(calls), size):
            ch = calls[i:i + size]
            body = [{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(ch)]
            out = self._send(body, ch[0][0] + "[batch]") if ch else []
            by = {}
            if isinstance(out, list):
                for r in out:
                    if isinstance(r, dict):
                        by[r.get("id")] = r.get("result")
            res += [by.get(k) for k in range(len(ch))]
        return res

    def head(self):
        return int(self.call("eth_blockNumber", []), 16)

    def block_ts(self, n):
        b = self.call("eth_getBlockByNumber", [hex(int(n)), False])
        return int(b["timestamp"], 16) if b else None

    def logs(self, flt, lo, hi, max_range=50_000, min_range=50, stats=None):
        """Every log of filter flt in blocks [lo, hi], split on "range / too many results" refusals (the endpoint's
        hint range is used when it gives one). -> [log]. Raises RpcError when a range cannot be read (archive)."""
        out = []
        todo = [(int(lo), min(int(hi), int(lo) + max_range - 1))]
        nxt = todo[0][1] + 1
        while todo or nxt <= hi:
            if not todo:
                todo.append((nxt, min(int(hi), nxt + max_range - 1)))
                nxt = todo[-1][1] + 1
            a, b = todo.pop(0)
            keep = self.retries
            try:
                # 19.11. 23:15: a heavy range timed out 4 x 60 s on 48.club; one retry, then the range is halved
                self.retries = min(keep, 1)
                got = self.call("eth_getLogs", [dict(flt, fromBlock=hex(a), toBlock=hex(b))]) or []
                out += got
                if stats is not None:
                    stats["calls"] = stats.get("calls", 0) + 1
            except RpcError as e:
                msg = str(e)
                if ("max results" in msg or "range" in msg or "too many" in msg.lower() or "timed out" in msg.lower()
                        or "timeout" in msg.lower() or "limit" in msg.lower()) and "archive" not in msg.lower() \
                        and b - a + 1 > min_range:
                    mid = (a + b) // 2
                    hint = _hint(msg)
                    if hint and a <= hint[1] < b:
                        mid = hint[1]
                    todo[:0] = [(a, mid), (mid + 1, b)]
                    continue
                raise
            finally:
                self.retries = keep
        return out


def _hint(msg):
    """(a, b) of "retry with the range A-B" in an error message, or None."""
    import re
    m = re.search(r"range (\d+)-(\d+)", msg)
    return (int(m.group(1)), int(m.group(2))) if m else None


def calls_line():
    by = Counter()
    for (host, method), n in CALLS.items():
        by[host] += n
    return ", ".join(f"{h} {n}" for h, n in by.most_common()) or "0"
