"""Public API with a key per user (27.11., vlasnik: "Make a public API with a key per user that returns only results,
with a request cap and hidden control rows").

    GET /api/v1/token/<address>      risk verdict of one Solana token, short plain reasons, market cap / liquidity
    GET /api/v1/wallet/<address>     label(s), grade, copy verdict, copyable yes / no, short plain reasons
    GET /api/v1/influencer/<handle>  outcomes of an account's clean measured calls (X handle or tg:<channel>)
    GET /api/v1/signals?limit=       recent signals (fresh for a plan with "fresh", else 24 h delayed)
    GET /api/v1/usage                the key's own plan, cap and today's count (not counted)

Key in "Authorization: Bearer <key>" or "X-API-Key: <key>". Only results and plain reasons leave here: never
weights, thresholds, formulas, internal source or table names (tests/test_javniapi_offline.py checks the answers).

Keys (league.db, written only by the dashboard process like the rest of league.db):
  api_keys   one row per key: the user it belongs to, a label, plan, optional own daily cap, sha256 of the key (the key
             itself is shown once, at creation, and never stored), revoked flag
  api_usage  (key_id, UTC day) -> requests answered and requests refused (429)
  api_meta   the canary secret (random, made on first use; owner-only, never in an answer)
Plans are labels the owner sets (no payment yet): PLANS below, JAVNIAPI_PLANS (JSON) overrides or adds plans.
Limits: the daily cap per key (UTC day; 429 with Retry-After until midnight UTC) and a burst limit BURST_N requests
per BURST_S seconds per key (429 with Retry-After in seconds).

Canaries (hidden control rows), so a leaked copy can be traced to the key that fetched it:
  1. every signals answer carries one plausible but fake token per key and UTC day (address, symbol, numbers all from
     HMAC(secret, key id, day)); it exists nowhere else: it is made while the answer is serialised, never stored, so
     nothing of ours (pages, MCP, trading, learning) can read it back;
  2. the seconds of every first_seen_ts in signals are a per-key watermark: ts - ts % 60 + HMAC(secret, key, token) %
     60 (under a minute off, a field no decision uses).
  trace(text) (owner only, /api-kljucevi "Provjeri procurjeli uzorak") finds both in a pasted sample: canary
  addresses name the key outright; watermark seconds that match one key on most rows point at it (1 in 60 by chance
  per row).
The owner MCP (ui/mcpapi.py, MCP_API_KEY) stays separate: these keys never open /api/mcp/* or /mcp, and its key never
opens /api/v1/*.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import deque

PREFIX = "/api/v1/"
KEY_PREFIX = "msk_"
PLANS = {"free": {"daily": 200, "fresh": False}, "pro": {"daily": 5000, "fresh": True}}
BURST_N = int(os.environ.get("JAVNIAPI_BURST_N", "10"))
BURST_S = int(os.environ.get("JAVNIAPI_BURST_S", "10"))
DELAY_S = 86400                 # = ui/public.PUBLIC_DELAY_S: what a plan without "fresh" sees
SIGNALS_MAX = 50
CACHE_S = 60
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
HANDLE = re.compile(r"(tg:)?[A-Za-z0-9_]{1,40}")
USER = re.compile(r"[A-Za-zČčĆćĐđŠšŽž0-9_\-]{2,30}")
LABEL = re.compile(r"[^\x00-\x1f<>]{0,60}")
MIN_MCAP = 30_000               # CLAUDE.md: tokens under $30k are not offered as signals

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, label TEXT, plan TEXT,
    daily_cap INTEGER, prefix TEXT, hash TEXT UNIQUE, created INTEGER, created_by TEXT, revoked INTEGER DEFAULT 0,
    revoked_ts INTEGER, last_used INTEGER);
CREATE TABLE IF NOT EXISTS api_usage (key_id INTEGER, day TEXT, n INTEGER DEFAULT 0, refused INTEGER DEFAULT 0,
    PRIMARY KEY (key_id, day));
CREATE TABLE IF NOT EXISTS api_meta (k TEXT PRIMARY KEY, v TEXT);
"""
_lock = threading.Lock()
_burst = {}          # key id -> deque of request times (this process)
_cache = {}          # name -> (ts, value): the shared result reads, before any per-key canary
_cache_lock = threading.Lock()


# ---------- store ------------------------------------------------------------------------------------------------------

def connect():
    from league import store
    con = store.connect()
    con.executescript(SCHEMA)
    return con


def plans():
    out = {k: dict(v) for k, v in PLANS.items()}
    try:
        extra = json.loads(os.environ.get("JAVNIAPI_PLANS") or "{}")
    except ValueError:
        extra = {}
    for name, p in (extra or {}).items() if isinstance(extra, dict) else ():
        if isinstance(p, dict) and re.fullmatch(r"[a-z0-9_]{1,20}", str(name)):
            base = out.get(name, {"daily": PLANS["free"]["daily"], "fresh": False})
            out[name] = {"daily": int(p.get("daily", base["daily"])), "fresh": bool(p.get("fresh", base["fresh"]))}
    return out


def _hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create(con, owner, plan, label="", daily_cap=None, by="", now=None):
    """(key id, the key): the key is returned once and only its hash is stored. ValueError with a plain reason."""
    owner = (owner or "").strip()
    if not USER.fullmatch(owner):
        raise ValueError("upiši ime korisnika (2-30 slova, brojeva, _ ili -)")
    if plan not in plans():
        raise ValueError("nepoznat plan: " + ", ".join(plans()))
    label = (label or "").strip()
    if not LABEL.fullmatch(label):
        raise ValueError("oznaka do 60 znakova, bez < >")
    cap = None
    if daily_cap not in (None, ""):
        try:
            cap = int(daily_cap)
        except (TypeError, ValueError):
            raise ValueError("dnevni strop mora biti cijeli broj") from None
        if not 1 <= cap <= 1_000_000:
            raise ValueError("dnevni strop između 1 i 1.000.000")
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    cur = con.execute("INSERT INTO api_keys (owner, label, plan, daily_cap, prefix, hash, created, created_by) "
                      "VALUES (?,?,?,?,?,?,?,?)", (owner, label, plan, cap, key[:len(KEY_PREFIX) + 6], _hash(key),
                                                   int(now or time.time()), by or ""))
    con.commit()
    return cur.lastrowid, key


def revoke(con, key_id, now=None):
    n = con.execute("UPDATE api_keys SET revoked=1, revoked_ts=? WHERE id=? AND revoked=0",
                    (int(now or time.time()), int(key_id))).rowcount
    con.commit()
    return n == 1


def set_plan(con, key_id, plan, daily_cap=None):
    if plan not in plans():
        raise ValueError("nepoznat plan")
    cap = int(daily_cap) if daily_cap not in (None, "") else None
    if cap is not None and not 1 <= cap <= 1_000_000:
        raise ValueError("dnevni strop između 1 i 1.000.000")
    con.execute("UPDATE api_keys SET plan=?, daily_cap=? WHERE id=?", (plan, cap, int(key_id)))
    con.commit()


def keys(con, now=None):
    """Every key with today's and the last 7 days' usage (owner page)."""
    today = day(now)
    week = [day((now or time.time()) - i * 86400) for i in range(7)]
    use = {}
    for kid, d, n, ref in con.execute("SELECT key_id, day, n, refused FROM api_usage WHERE day >= ?", (min(week),)):
        u = use.setdefault(kid, {"today": 0, "refused_today": 0, "week": 0})
        u["week"] += n or 0
        if d == today:
            u["today"], u["refused_today"] = n or 0, ref or 0
    tot = dict(con.execute("SELECT key_id, SUM(n) FROM api_usage GROUP BY key_id").fetchall())
    out = []
    pl = plans()
    for r in con.execute("SELECT id, owner, label, plan, daily_cap, prefix, created, created_by, revoked, revoked_ts, "
                         "last_used FROM api_keys ORDER BY revoked, id DESC"):
        k = dict(zip(("id", "owner", "label", "plan", "daily_cap", "prefix", "created", "created_by", "revoked",
                      "revoked_ts", "last_used"), r))
        k["cap"] = k["daily_cap"] or (pl.get(k["plan"]) or {}).get("daily") or 0
        k.update(use.get(k["id"], {"today": 0, "refused_today": 0, "week": 0}))
        k["total"] = tot.get(k["id"]) or 0
        out.append(k)
    return out


def day(ts=None):
    return time.strftime("%Y-%m-%d", time.gmtime(ts or time.time()))


def lookup(con, key):
    """The key's row as a dict, or None (unknown, revoked, or its user removed from the app)."""
    if not key or not key.startswith(KEY_PREFIX) or len(key) > 100:
        return None
    r = con.execute("SELECT id, owner, plan, daily_cap, revoked FROM api_keys WHERE hash=?", (_hash(key),)).fetchone()
    if not r or r[4]:
        return None
    try:
        from league import izbaceni
        if izbaceni.is_out(r[1]):
            return None
    except Exception:  # noqa: BLE001 - league/ without the removed list
        pass
    p = plans().get(r[2]) or plans()["free"]
    return {"id": r[0], "owner": r[1], "plan": r[2] if r[2] in plans() else "free", "cap": r[3] or p["daily"],
            "fresh": p["fresh"]}


def key_from(headers):
    got = (headers.get("X-API-Key") or "").strip()
    if not got:
        a = (headers.get("Authorization") or "").strip()
        got = a[7:].strip() if a.lower().startswith("bearer ") else ""
    return got


# ---------- limits -----------------------------------------------------------------------------------------------------

def admit(con, k, now=None):
    """(True, remaining today) or (False, retry_after_s, why): the burst limit, then the daily cap; counts the
    request (answered or refused) in api_usage."""
    now = now or time.time()
    d = day(now)
    with _lock:
        q = _burst.setdefault(k["id"], deque())
        while q and q[0] <= now - BURST_S:
            q.popleft()
        if len(q) >= BURST_N:
            _count(con, k["id"], d, refused=True)
            return False, max(1, int(q[0] + BURST_S - now) + 1), "burst"
        row = con.execute("SELECT n FROM api_usage WHERE key_id=? AND day=?", (k["id"], d)).fetchone()
        used = (row[0] if row else 0) or 0
        if used >= k["cap"]:
            _count(con, k["id"], d, refused=True)
            midnight = (int(now) // 86400 + 1) * 86400
            return False, max(1, midnight - int(now)), "daily"
        q.append(now)
        _count(con, k["id"], d)
        con.execute("UPDATE api_keys SET last_used=? WHERE id=?", (int(now), k["id"]))
        con.commit()
        return True, k["cap"] - used - 1


def _count(con, kid, d, refused=False):
    col = "refused" if refused else "n"
    con.execute(f"INSERT INTO api_usage (key_id, day, {col}) VALUES (?,?,1) "
                f"ON CONFLICT(key_id, day) DO UPDATE SET {col} = {col} + 1", (kid, d))
    con.commit()


def used_today(con, kid, now=None):
    r = con.execute("SELECT n FROM api_usage WHERE key_id=? AND day=?", (kid, day(now))).fetchone()
    return (r[0] if r else 0) or 0


def reset_burst():
    with _lock:
        _burst.clear()


# ---------- canaries ---------------------------------------------------------------------------------------------------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_SYL = ("ba", "zo", "ki", "mu", "ra", "po", "ne", "fi", "lu", "ta", "go", "shi", "do", "ve", "ri", "pe", "mo", "ka")


def b58(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def secret(con):
    r = con.execute("SELECT v FROM api_meta WHERE k='canary_secret'").fetchone()
    if r:
        return bytes.fromhex(r[0])
    s = secrets.token_bytes(32)
    con.execute("INSERT OR IGNORE INTO api_meta VALUES ('canary_secret', ?)", (s.hex(),))
    con.commit()
    return bytes.fromhex(con.execute("SELECT v FROM api_meta WHERE k='canary_secret'").fetchone()[0])


def _mac(sec, *parts):
    return hmac.new(sec, "|".join(str(p) for p in parts).encode(), hashlib.sha256).digest()


def canary_row(sec, kid, d, now):
    """The fake signal of key `kid` on UTC day `d`: deterministic (address, symbol, kind, numbers per key and day; its
    first_seen_ts per key, day and hour, so it looks recent), plausible, in no table of ours."""
    h = _mac(sec, "tok", kid, d)
    mint = b58(h[:32])
    sym = ("".join(_SYL[b % len(_SYL)] for b in h[:2 + h[2] % 2])).upper()
    mcap = 40_000 + int.from_bytes(h[3:6], "big") % 2_500_000
    hour = int(now) // 3600 * 3600   # the address, symbol and numbers hold for the UTC day; the time for the hour
    ts = hour - 300 - int.from_bytes(h[6:8], "big") % 3000
    return {"token": mint, "symbol": sym, "kind": ("social_call", "wallet_buy", "market_scan")[h[8] % 3],
            "callers": 1 + h[9] % 3, "first_seen_ts": ts - ts % 60 + h[10] % 60, "market_cap_usd": float(mcap),
            "risk": ("low_risk", "caution", "unknown")[h[11] % 3]}


def wm_second(sec, kid, token):
    return _mac(sec, "ts", kid, token)[0] % 60


def watermark(rows, sec, kid, d, now):
    """Rows with the key's seconds watermark and its canary row inserted (a copy; the shared rows stay as they were)."""
    out = []
    for r in rows:
        r = dict(r)
        ts = r.get("first_seen_ts")
        if isinstance(ts, int):
            r["first_seen_ts"] = ts - ts % 60 + wm_second(sec, kid, r["token"])
        out.append(r)
    c = canary_row(sec, kid, d, now if d == day(now) else time.mktime(time.strptime(d, "%Y-%m-%d")))
    pos = _mac(sec, "pos", kid, d)[0] % (len(out) + 1)
    out.insert(pos, c)
    return out


def trace(con, text, days=120, now=None):
    """Owner only: which keys a leaked sample points at. text: pasted JSON or any text with addresses.
    [{key_id, owner, label, canaries: [(day, address)], wm_rows, wm_match}] best first; [] when nothing matches."""
    now = now or time.time()
    sec = secret(con)
    found = set(MINT.findall(text or ""))
    pairs = []   # (token, ts) of rows carrying first_seen_ts
    try:
        js = json.loads(text)
    except (TypeError, ValueError):
        js = None

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("token"), str) and isinstance(x.get("first_seen_ts"), int):
                pairs.append((x["token"], x["first_seen_ts"]))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(js)
    ks = con.execute("SELECT id, owner, label, created FROM api_keys").fetchall()
    out = []
    for kid, owner, label, created in ks:
        hits = []
        start = max(int(created or now) - 86400, int(now) - days * 86400)
        t = start
        while t <= now + 86400:
            d = day(t)
            m = canary_row(sec, kid, d, now)["token"]
            if m in found:
                hits.append((d, m))
            t += 86400
        canary_tokens = {m for _d, m in hits}
        real = [(tok, ts) for tok, ts in pairs if tok not in canary_tokens]
        wm = sum(1 for tok, ts in real if ts % 60 == wm_second(sec, kid, tok))
        if hits or (real and wm >= max(3, 0.8 * len(real))):
            out.append({"key_id": kid, "owner": owner, "label": label, "canaries": hits, "wm_rows": len(real),
                        "wm_match": wm})
    out.sort(key=lambda r: (-len(r["canaries"]), -r["wm_match"]))
    return out


# ---------- results ----------------------------------------------------------------------------------------------------

def _cached(name, build, ttl=CACHE_S):
    t = time.time()
    with _cache_lock:
        hit = _cache.get(name)
        if hit and t - hit[0] < ttl:
            return hit[1]
    v = build()
    with _cache_lock:
        if len(_cache) > 2000:   # per-token market reads: arbitrary addresses must not grow memory
            _cache.clear()
        _cache[name] = (t, v)
    return v


def reset_cache():
    with _cache_lock:
        _cache.clear()


RISK = {"ok": "low_risk", "unknown": "unknown", "oprez": "caution", "risk": "high_risk", "hard": "avoid"}
_REASONS = (   # (words in our own wording, the plain reason given out); first match wins, unknown words say less
    (("arhiv",), "listed as a past rug"),
    (("honeypot",), "selling may be blocked"),
    (("freeze",), "freeze authority is still active"),
    (("mint",), "mint authority is still active"),
    (("rugan", "kolaps", "izvuč", "likvidnost"), "price and liquidity collapsed"),
    (("dump",), "dumped hard after a pump"),
    (("koncentr", "drž", "top", "holder", "supply"), "supply held by few wallets"),
    (("oprez",), "some warning signs"),
)


def plain_reasons(raw):
    out = []
    for s in raw or []:
        low = str(s).lower()
        txt = next((say for words, say in _REASONS if any(w in low for w in words)), "other risk signs")
        if txt not in out:
            out.append(txt)
    return out[:3]


def _market(address):
    from ui import prijedlog
    lv = prijedlog.live_market([address]) or {}
    return lv.get(address)


def token_result(address, fresh, now=None, market=None):
    now = now or time.time()
    if not MINT.fullmatch(address or ""):
        return 400, {"error": "not a Solana token address"}
    m = market if market is not None else _cached(("m", address), lambda: _market(address))
    mk = {"market_cap_usd": (m or {}).get("mcap"), "liquidity_usd": (m or {}).get("liq"),
          "change_1h_pct": (m or {}).get("ch_h1"), "change_24h_pct": (m or {}).get("ch_h24")}
    row = {"token": address, "market": mk}
    try:
        from ui import mcpapi
        vis, hid = mcpapi._hygiene([row], now, {}, cached=True)
        r = (vis or hid or [row])[0]
    except Exception as e:  # noqa: BLE001 - the answer says "unknown" rather than fail
        print(f"javniapi: token: {type(e).__name__}", flush=True)
        r = row
    reasons = plain_reasons(r.get("rug_reasons"))
    level = RISK.get(r.get("rug_verdict"), "unknown")
    late = r.get("runup_x") is not None and r["runup_x"] >= mcpapi_runup()
    if late:
        reasons.append("late: price already far above where it was first signalled")
    if not m:
        reasons.append("no live market found")
    out = {"token": address, "risk": level, "late": bool(late), "reasons": reasons,
           "market_cap_usd": _round(mk["market_cap_usd"]), "liquidity_usd": _round(mk["liquidity_usd"]),
           "as_of": int(now)}
    if fresh:
        out["calls_last_hour"] = _cached(("c", address), lambda: _calls_last_hour(address, now))
    return 200, out


def mcpapi_runup():
    try:
        from ui import mcpapi
        return mcpapi.RUNUP_HIDE_X
    except Exception:  # noqa: BLE001
        return 4.0


def _round(x, nd=0):
    try:
        return round(float(x), nd) if x is not None else None
    except (TypeError, ValueError):
        return None


def _calls_last_hour(address, now):
    try:
        from ui import pravitrade
        for tok, callers, *_ in pravitrade.gather_callers(now, limit=40):
            if tok == address:
                return len(callers)
    except Exception as e:  # noqa: BLE001
        print(f"javniapi: pozivi: {type(e).__name__}", flush=True)
        return None
    return 0


VERDICT = ("worth_copying", "do_not_copy_with_real_money", "do_not_copy", "not_proven_yet", "not_proven", "not_rated")
LABELS = ("bot", "rugger", "bundler", "insider", "dev", "cex", "mev", "sniper", "funder_of_rugger", "smart", "fresh")


def wallet_result(address, w=None, row=None):
    """The wallet page's own judgement (ui/pages._verdict: wallets/dokazani + the copy ranking), as a word and plain
    reasons, without its numbers or limits."""
    from wallets import dokazani
    if not MINT.fullmatch(address or ""):
        return 400, {"error": "not a Solana wallet address"}
    if w is None:
        from ui import data
        w = data.wallet(address)
        row = dokazani.for_wallet(address) if w else None
    if not w:
        return 404, {"error": "wallet not known to us"}
    s, labs = w.get("stats") or {}, [x for x in (w.get("labels") or []) if x in LABELS]
    rk = w.get("rang")
    reasons, copyable, proven = [], None, bool(row and row.get("passed"))
    if not s:
        verdict = "not_rated"
        reasons.append("not rated yet")
    else:
        miss = dokazani.not_copyable(s, w.get("labels") or [])
        rk_no = rk is not None and not miss and (not rk.get("copyable") or not rk.get("proven"))
        copyable = not miss and not rk_no
        if rk_no:
            verdict = "do_not_copy_with_real_money"
            reasons.append("trades cannot be followed reliably" if not rk.get("copyable") else
                           "too few closed trades recently")
        elif proven:
            verdict = "worth_copying"
            reasons.append("in profit in both an earlier and a later period")
        elif miss:
            verdict = "do_not_copy"
            say = {"hold": "holds too briefly to follow", "tpd": "trades too often to follow",
                   "bags": "keeps many old losing positions", "labels": "flagged wallet type"}
            reasons += [say.get(k, "not copyable") for k, _h, _n in miss]
        elif not row:
            verdict = "not_proven_yet"
            reasons.append("not enough closed trades yet to test it twice")
        else:
            verdict = "not_proven"
            reasons.append("did not stay in profit in both periods")
    return 200, {"wallet": address, "grade": w.get("tier") if w.get("tier") in ("S", "A", "B", "C", "D") else None,
                 "labels": labs, "verdict": verdict, "copyable": copyable, "proven_twice": proven,
                 "reasons": list(dict.fromkeys(reasons))[:3]}


def influencer_result(handle):
    from ui import kolstats as KS
    from ui import public
    h = (handle or "").strip().lstrip("@")
    if not HANDLE.fullmatch(h):
        return 400, {"error": "handle: an X handle or tg:<channel>"}
    con = public._con()
    if con is None:
        return 404, {"error": "account not known to us"}
    try:
        try:
            r = con.execute("SELECT handle, COALESCE(bot, 0) FROM kols WHERE handle = ? COLLATE NOCASE", (h,)).fetchone()
        except sqlite3.OperationalError:
            r = None
        if not r or r[1] or public.BAD.search(r[0] or ""):
            return 404, {"error": "account not known to us"}
        h = r[0]
        s = KS.stats(KS.clean_calls(con, h))
        base = _cached("base", lambda: KS.baseline(con), ttl=3600)
    finally:
        con.close()
    pct = (lambda x: round(x, 3) if x is not None else None)
    return 200, {"handle": h, "measured_calls": s["n"], "enough_data": s["enough"],
                 "price_up_after_1h_share": pct(s["up1h"]), "reached_plus_15pct_in_24h_share": pct(s["hit15"]),
                 "median_24h_return": pct(s["med24"]), "fell_90pct_share": pct(s["rug"]),
                 "vs_median_account": KS.compare(s, base) if s["enough"] else None,
                 "measured_since": s["since"], "note": "clean calls older than 24 hours; past results, not a prediction"}


_KIND = {"caller": "social_call", "wallet": "wallet_buy", "scan": "market_scan", "beta": "market_scan"}


def _fresh_signals():
    from ui import mcpapi
    res = mcpapi.signals()
    out = []
    for r in res.get("signals") or []:
        kind = _KIND.get(r.get("source"))
        mk = r.get("market") or {}
        mc = mk.get("market_cap_usd")
        if not kind or r.get("under_30k") or not mc or mc < MIN_MCAP:
            continue
        ts = r.get("first_call_ts") or r.get("scan_found_ts")
        out.append({"token": r["token"], "symbol": r.get("symbol"), "kind": kind, "callers": r.get("n_callers") or 0,
                    "first_seen_ts": int(ts) if ts else None, "market_cap_usd": _round(mc),
                    "risk": RISK.get(r.get("rug_verdict"), "unknown")})
    return out[:SIGNALS_MAX]


def _delayed_signals(now=None):
    """Calls 24-48 h old (clean, as the public pages count them), one row per token, with what happened after."""
    from ui import kolstats as KS
    from ui import public
    now = int(now or time.time())
    con = public._con()
    if con is None:
        return []
    q = ",".join("?" * len(KS.BIASED_SOURCES))
    try:
        rows = con.execute(f"""SELECT c.token, c.symbol, c.handle, c.ts, c.mcap0, c.r24h FROM calls c
            LEFT JOIN kols k ON k.handle = c.handle
            WHERE c.kind = 'call' AND c.bad IS NULL AND c.ts < ? AND c.ts >= ? AND COALESCE(k.bot, 0) = 0
              AND COALESCE(c.source, '') NOT IN ({q}) ORDER BY c.ts""",
                           (now - DELAY_S, now - 2 * DELAY_S, *KS.BIASED_SOURCES)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    by = {}
    for tok, sym, handle, ts, mc0, r24 in rows:
        if not tok or not MINT.fullmatch(tok):
            continue
        d = by.setdefault(tok, {"token": tok, "symbol": sym, "kind": "social_call", "callers": set(),
                                "first_seen_ts": int(ts), "market_cap_usd": _round(mc0),
                                "change_24h_after_first_call": _round(r24, 3) if r24 is not None else None})
        d["callers"].add(handle)
    out = []
    for d in sorted(by.values(), key=lambda d: -d["first_seen_ts"]):
        if not d["market_cap_usd"] or d["market_cap_usd"] < MIN_MCAP:
            continue
        d["callers"] = len(d["callers"])
        out.append(d)
    return out[:SIGNALS_MAX]


def signals_result(k, con, limit=None, now=None, rows=None):
    now = now or time.time()
    try:
        lim = max(1, min(SIGNALS_MAX, int(limit))) if limit not in (None, "") else SIGNALS_MAX
    except ValueError:
        return 400, {"error": "limit: a whole number 1-50"}
    if rows is None:
        rows = (_cached("fresh", _fresh_signals) if k["fresh"] else _cached("delayed", _delayed_signals, ttl=300))
    rows = watermark(rows[:lim], secret(con), k["id"], day(now), now)
    return 200, {"as_of": int(now), "delayed": not k["fresh"], "count": len(rows), "signals": rows}


# ---------- the request ------------------------------------------------------------------------------------------------

def handle(path, qs, headers, now=None):
    """(code, dict, extra headers) for GET /api/v1/...; never a traceback."""
    now = now or time.time()
    con = connect()
    try:
        k = lookup(con, key_from(headers))
        if not k:
            return 401, {"error": "missing or wrong API key (Authorization: Bearer <key> or X-API-Key)"}, {}
        sub = path[len(PREFIX):].strip("/")
        if sub == "usage":
            used = used_today(con, k["id"], now)
            return 200, {"plan": k["plan"], "daily_cap": k["cap"], "used_today": used,
                         "remaining_today": max(0, k["cap"] - used), "delayed": not k["fresh"]}, {}
        part, _, arg = sub.partition("/")
        if part not in ("token", "wallet", "influencer", "signals") or (part != "signals" and not arg) or \
                (part == "signals" and arg):
            return 404, {"error": "unknown endpoint; see /api"}, {}
        a = admit(con, k, now)
        if not a[0]:
            why = "too many requests in a short time" if a[2] == "burst" else "daily request cap reached"
            return 429, {"error": why, "retry_after_s": a[1]}, {"Retry-After": str(a[1]),
                                                                 "X-RateLimit-Limit": str(k["cap"])}
        extra = {"X-RateLimit-Limit": str(k["cap"]), "X-RateLimit-Remaining": str(max(0, a[1]))}
        try:
            if part == "token":
                code, out = token_result(arg, k["fresh"], now)
            elif part == "wallet":
                code, out = wallet_result(arg)
            elif part == "influencer":
                code, out = influencer_result(arg)
            else:
                code, out = signals_result(k, con, (qs or {}).get("limit"), now)
        except Exception as e:  # noqa: BLE001
            print(f"javniapi: {part}: {type(e).__name__}: {e}", flush=True)
            code, out = 500, {"error": "temporary error, try again later"}
        return code, out, extra
    finally:
        con.close()
