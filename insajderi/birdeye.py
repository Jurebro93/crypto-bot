"""Birdeye: provjera iz drugog izvora (19.11. navečer; the owner's key, free plan "Standard": 30,000 compute units a
month). A small, bounded second source for the pump-wallet discovery; REPORT ONLY: no selection rule and no class
threshold reads it.

Endpoint (verified live 19.11.): GET /defi/v2/tokens/top_traders?address=<mint>&time_frame=<7d|30d|90d>&sort_type=desc
&sort_by=realized_pnl&offset=<n>&limit=<1..10> (limit > 10 refused; 90d is the largest frame: "180d" / "1y" answer
"time_frame invalid format"; the frame is relative to NOW; sort_by=realized_pnl really sorts, desc and asc).
Documented cost 30 CU a call (no usage header: counted here); 300 requests a minute; a too-fast call answers
{"success": false, "message": "Too many requests"} with HTTP 200. firstTradeUnixTime is the wallet's first trade of
the token at all (older than the frame), lastTradeUnixTime its last.

  fetch     every tiered pump token (pumpa15 first, then pumpa2, newest pump first), at most once per refresh_d (14):
            the top pages x 10 traders by realized PnL for the smallest of 7d / 30d / 90d that still contains the
            pump's t0 (an older pump is skipped and counted) -> be_top; within cu_month a calendar month (be_usage,
            never above it), rps calls a second, max_s seconds a pass and the pass's own deadline
  uses      a. cross-check: per "kupuje prije pumpe" / kandidat group, of its pump tokens Birdeye has read, on how many
               one of its wallets is in Birdeye's top -> be_pp, summary prije_pumpe.birdeye
            b. new candidates: wallets in the top by realized PnL (realized_usd > 0) on >= 3 pumped tokens, never tagged
               bundler / sniper / dev on those rows -> be_cand (also smart_trader on >= 2 pumped tokens: smart_n),
               and the history queue (wallets/povijest.py source "birdeye")
            c. Birdeye's bundler / sniper / dev tags on our wallets next to our own exclusion reasons (be_pp.tags,
               agree / disagree counts)
  key       env BIRDEYE_API_KEY (header X-API-KEY); without it nothing is called and one line a day says so.
            BIRDEYE_PROXY_KEY=1: the call goes without the header (a network proxy injects the key; the developer
            sandbox only)
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from insajderi import store

BASE = "https://public-api.birdeye.so"
EP_TOP = "/defi/v2/tokens/top_traders"
PREFIX = "birdeye: "
FRAMES = (("7d", 7), ("30d", 30), ("90d", 90))
BAD_TAGS = {"bundler", "sniper", "dev"}
DEFAULT = {"cu_month": 25000, "cu_call": 30, "rps": 0.7, "pages": 3, "time_frame": "90d", "refresh_d": 14,
           "max_s": 120, "min_tokens": 3, "smart_min": 2}
SCHEMA = """
CREATE TABLE IF NOT EXISTS be_usage (month TEXT PRIMARY KEY, calls INTEGER, cu INTEGER);
CREATE TABLE IF NOT EXISTS be_tok (mint TEXT PRIMARY KEY, time_frame TEXT, rows INTEGER, status TEXT, fetched_ts INTEGER);
CREATE TABLE IF NOT EXISTS be_top (mint TEXT, owner TEXT, time_frame TEXT, rank INTEGER, tags TEXT, realized_usd REAL,
    total_usd REAL, trades INTEGER, buys INTEGER, sells INTEGER, vol_buy_usd REAL, vol_sell_usd REAL, avg_buy REAL,
    avg_sell REAL, first_ts INTEGER, last_ts INTEGER, fetched_ts INTEGER, PRIMARY KEY (mint, owner, time_frame));
CREATE INDEX IF NOT EXISTS be_top_owner ON be_top (owner);
CREATE TABLE IF NOT EXISTS be_cand (owner TEXT PRIMARY KEY, n_tokens INTEGER, n15 INTEGER, sum_realized_usd REAL,
    tags TEXT, last_ts INTEGER, smart_n INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS be_pp (owner TEXT PRIMARY KEY, cls TEXT, n_checked INTEGER, n_seen INTEGER, tags TEXT,
    agree INTEGER, updated INTEGER);
"""
_GATE = {"next": 0.0}


def config(c=None):
    return {**DEFAULT, **((c or {}).get("birdeye") or {})}


def ensure(con):
    con.executescript(SCHEMA)


def month(now):
    return time.strftime("%Y-%m", time.gmtime(int(now)))


def usage(con, now):
    r = store.q(con, "SELECT calls, cu FROM be_usage WHERE month = ?", (month(now),))
    return (int(r[0][0] or 0), int(r[0][1] or 0)) if r else (0, 0)


def _add_usage(con, now, cu):
    con.execute("INSERT INTO be_usage VALUES (?, 1, ?) ON CONFLICT (month) DO UPDATE SET calls = calls + 1, "
                "cu = cu + excluded.cu", (month(now), int(cu)))
    con.commit()


def key_mode():
    """"key" (BIRDEYE_API_KEY), "proxy" (BIRDEYE_PROXY_KEY=1: the sandbox's proxy injects it) or None."""
    if os.environ.get("BIRDEYE_API_KEY"):
        return "key"
    if os.environ.get("BIRDEYE_PROXY_KEY") == "1":
        return "proxy"
    return None


def http_get(url, headers, timeout=30):
    """(HTTP status, parsed JSON or None)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "null")
        except ValueError:
            return e.code, None


class Client:
    """One pass's client: the month budget (be_usage), the pace (rps), "Too many requests" -> wait and retry once,
    "lacks sufficient permissions" -> that endpoint off for the UTC day (i2_kv be_off:<endpoint>:<day>), said once."""

    def __init__(self, con, bc, now, get=None, sleep=None, clock=None, log=print):
        self.con, self.bc, self.now = con, bc, int(now)
        self.get = get or http_get
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self.log = log
        self.calls = 0

    def left_cu(self):
        return int(self.bc["cu_month"]) - usage(self.con, self.now)[1]

    def off(self, ep):
        return bool(store.kv(self.con, f"be_off:{ep}:{store.day(self.now)}"))

    def _pace(self):
        gap = 1.0 / max(0.01, float(self.bc["rps"]))
        wait = _GATE["next"] - self.clock()
        if wait > 0:
            self.sleep(wait)
        _GATE["next"] = self.clock() + gap

    def call(self, ep, params):
        """The data dict, or None (no budget, endpoint off, refused, an error)."""
        mode = key_mode()
        if mode is None or self.off(ep):
            return None
        headers = {"accept": "application/json", "x-chain": "solana"}
        if mode == "key":
            headers["X-API-KEY"] = os.environ["BIRDEYE_API_KEY"]
        url = BASE + ep + "?" + urllib.parse.urlencode(params)
        for attempt in range(2):
            if self.left_cu() < int(self.bc["cu_call"]):
                return None
            self._pace()
            try:
                st, body = self.get(url, headers)
            except Exception as e:  # noqa: BLE001 - the network: this call is lost, the pass goes on
                _add_usage(self.con, self.now, int(self.bc["cu_call"]))
                self.calls += 1
                self.log(f"{PREFIX}{ep}: {type(e).__name__}")
                return None
            _add_usage(self.con, self.now, int(self.bc["cu_call"]))   # every sent call counts (no usage header)
            self.calls += 1
            msg = str((body or {}).get("message") or "") if isinstance(body, dict) else ""
            if isinstance(body, dict) and body.get("success"):
                return body.get("data") or {}
            if "too many requests" in msg.lower() or st == 429:
                if attempt == 0:
                    self.sleep(2.0 * (1.0 / max(0.01, float(self.bc["rps"]))) + 1.0)
                    continue
                return None
            if "lacks sufficient permissions" in msg.lower() or st in (401, 403):
                store.kv(self.con, f"be_off:{ep}:{store.day(self.now)}", 1)
                self.con.commit()
                self.log(f"{PREFIX}{ep} nije dostupan s ovim ključem ({msg[:80] or st}); isključen do sutra")
                return None
            self.log(f"{PREFIX}{ep}: {msg[:80] or st}")
            return None
        return None


def frame_for(t0, now, max_frame="90d"):
    """The smallest of 7d / 30d / 90d (up to max_frame) that still contains t0, or None (older)."""
    age_d = (int(now) - int(t0)) / 86400
    for name, days in FRAMES:
        if age_d <= days:
            return name
        if name == max_frame:
            break
    return None


def tokens_due(con, events, now, bc):
    """[(mint, t0, tier)] of the tiered pump tokens to read now: pumpa15 first, then pumpa2, newest pump first; a token
    read within refresh_d is not due. -> (due, n older than the largest frame)."""
    newest = {}
    for e in events:
        if e.get("tier") not in ("pumpa15", "pumpa2"):
            continue
        m = e["token"]
        cur = newest.get(m)
        rank = 0 if e["tier"] == "pumpa15" else 1
        if cur is None or (rank, -e["t0"]) < (cur[2], -cur[1]):
            newest[m] = (m, int(e["t0"]), rank)
    fresh = int(now) - int(float(bc["refresh_d"]) * 86400)
    done = {m for (m,) in store.q(con, "SELECT mint FROM be_tok WHERE fetched_ts >= ?", (fresh,))}
    out, old = [], 0
    for m, t0, rank in sorted(newest.values(), key=lambda x: (x[2], -x[1])):
        if m in done:
            continue
        if frame_for(t0, now, bc["time_frame"]) is None:
            old += 1
            continue
        out.append((m, t0, "pumpa15" if rank == 0 else "pumpa2"))
    return out, old


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def fetch(con, c, events, now, stop=None, get=None, sleep=None, clock=None, log=print):
    """Read the due tokens within the month's CU, max_s seconds and stop(). -> {"tokens", "rows", "old", "calls",
    "no_key"}."""
    ensure(con)
    bc = config(c)
    out = {"tokens": 0, "rows": 0, "old": 0, "calls": 0, "no_key": False}
    if key_mode() is None:
        out["no_key"] = True
        if store.kv(con, "be_nokey_day") != store.day(now):
            store.kv(con, "be_nokey_day", store.day(now))
            con.commit()
            log(f"{PREFIX}ključ nije postavljen")
        return out
    cl = Client(con, bc, now, get, sleep, clock, log)
    t_end = cl.clock() + float(bc["max_s"])
    due, out["old"] = tokens_due(con, events, now, bc)
    for mint, t0, _tier in due:
        if (stop is not None and stop()) or cl.clock() >= t_end or cl.left_cu() < int(bc["cu_call"]) or cl.off(EP_TOP):
            break
        frame = frame_for(t0, now, bc["time_frame"])
        rows, ok = [], True
        for pg in range(int(bc["pages"])):
            if cl.left_cu() < int(bc["cu_call"]):
                ok = False
                break
            data = cl.call(EP_TOP, {"address": mint, "time_frame": frame, "sort_type": "desc",
                                    "sort_by": "realized_pnl", "offset": pg * 10, "limit": 10})
            if data is None:
                ok = False
                break
            items = data.get("items") or []
            for i, x in enumerate(items):
                rows.append((mint, x.get("owner"), frame, pg * 10 + i + 1, json.dumps(sorted(x.get("tags") or [])),
                             _f(x.get("realizedPnl")), _f(x.get("totalPnl")), x.get("trade"), x.get("tradeBuy"),
                             x.get("tradeSell"), _f(x.get("volumeBuyUSD")), _f(x.get("volumeSellUSD")),
                             _f(x.get("avgBuyPrice")), _f(x.get("avgSellPrice")), x.get("firstTradeUnixTime"),
                             x.get("lastTradeUnixTime"), int(now)))
            if len(items) < 10:
                break
        rows = [r for r in rows if r[1]]
        if rows:
            con.executemany("INSERT OR REPLACE INTO be_top VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        if ok or rows:
            con.execute("INSERT OR REPLACE INTO be_tok VALUES (?,?,?,?,?)",
                        (mint, frame, len(rows), "ok" if ok else "djelomično", int(now)))
            out["tokens"] += 1
            out["rows"] += len(rows)
        con.commit()
    out["calls"] = cl.calls
    return out


# ---------- the three uses (report only) -----------------------------------------------------------------------------

def _tags(s):
    try:
        return set(json.loads(s or "[]"))
    except ValueError:
        return set()


def analyze(con, c, events, now):
    """be_cand, be_pp and the summary block {"groups_checked", "groups_seen_in_top", "share", "candidates",
    "smart", "tag_agree", "tag_disagree", "tokens_read"}."""
    ensure(con)
    bc = config(c)
    tier = {}
    for e in events:
        if e.get("tier") in ("pumpa15", "pumpa2"):
            tier[e["token"]] = "pumpa15" if e["tier"] == "pumpa15" or tier.get(e["token"]) == "pumpa15" else "pumpa2"
    top = store.q(con, "SELECT mint, owner, tags, realized_usd, last_ts FROM be_top")
    by_owner = {}
    for m, o, tg, real, last in top:
        if m not in tier:
            continue
        by_owner.setdefault(o, []).append((m, _tags(tg), real or 0.0, last or 0))
    # b. candidates
    cand = []
    for o, rows in by_owner.items():
        good = {m for m, tg, real, _l in rows if real > 0 and not (tg & BAD_TAGS)}
        smart = {m for m, tg, _r, _l in rows if "smart_trader" in tg}
        if len(good) >= int(bc["min_tokens"]) or len(smart) >= int(bc["smart_min"]):
            tags = sorted(set().union(*(tg for _m, tg, _r, _l in rows)))
            cand.append((o, len(good), sum(1 for m in good if tier[m] == "pumpa15"),
                         round(sum(real for m, _tg, real, _l in rows if m in good), 2), json.dumps(tags),
                         max(l_ for *_x, l_ in rows), len(smart), int(now)))
    con.execute("DELETE FROM be_cand")
    con.executemany("INSERT INTO be_cand VALUES (?,?,?,?,?,?,?,?)", cand)
    # a. + c. our groups against Birdeye's top and tags
    read = {m for (m,) in store.q(con, "SELECT mint FROM be_tok")}
    in_top = {}
    for m, o, tg, _real, _last in top:
        in_top.setdefault(o, {})[m] = _tags(tg)
    pp_rows = []
    out = {"groups_checked": 0, "groups_seen_in_top": 0, "share": None, "tag_agree": 0, "tag_disagree": 0,
           "candidates": sum(1 for r in cand if r[1] >= int(bc["min_tokens"])),
           "smart": sum(1 for r in cand if r[6] >= int(bc["smart_min"])), "tokens_read": len(read)}
    toks_of = {}
    for o, m in store.q(con, "SELECT p.owner, e.token FROM i2_part p JOIN i2_events e ON e.eid = p.eid WHERE "
                             "e.tier IS NOT NULL AND p.bought_before = 1 AND p.sold_into = 1"):
        toks_of.setdefault(o, set()).add(m)
    for o, members, cls in store.q(con, "SELECT owner, members, cls FROM i2_pp"):
        try:
            ms = json.loads(members or "[]")
        except ValueError:
            ms = []
        tags, seen = set(), set()
        for w in ms:
            for m, tg in (in_top.get(w) or {}).items():
                tags |= tg
                seen.add(m)
        checked = (toks_of.get(o) or set()) & read
        n_seen = len(checked & seen)
        bad = tags & BAD_TAGS
        agree = None
        if cls in ("bot", "snajper") and seen:
            agree = int(bool(bad))
        elif cls in ("prije_pumpe", "kandidat") and bad:
            agree = 0
        if agree is not None:
            out["tag_agree" if agree else "tag_disagree"] += 1
        if cls in ("prije_pumpe", "kandidat") and checked:
            out["groups_checked"] += 1
            out["groups_seen_in_top"] += int(n_seen > 0)
        if checked or tags:
            pp_rows.append((o, cls, len(checked), n_seen, json.dumps(sorted(tags)), agree, int(now)))
    con.execute("DELETE FROM be_pp")
    con.executemany("INSERT INTO be_pp VALUES (?,?,?,?,?,?,?)", pp_rows)
    con.commit()
    if out["groups_checked"]:
        out["share"] = round(out["groups_seen_in_top"] / out["groups_checked"], 3)
    return out


def line(res, con, c, now):
    used = usage(con, now)
    return (f"{PREFIX}{res.get('tokens', 0)} tokena, {res.get('rows', 0)} trgovaca, CU ovaj mjesec "
            f"{used[1]:,}/{int(config(c)['cu_month']):,}")


def run(con, c, events, now, stop=None, log=print, **kw):
    """The pass's stage: fetch within its bounds, then the three uses. -> the summary block."""
    res = fetch(con, c, events, now, stop=stop, log=log, **kw)
    out = analyze(con, c, events, now)
    out.update(fetched=res)
    if not res.get("no_key"):
        log(line(res, con, c, now))
    return out


def md_section(con, limit=40):
    """The section of output/novcanici_prije_pumpe.md (empty list when nothing was read)."""
    L = ["## Birdeye: provjera iz drugog izvora", ""]
    if not store.q(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='be_tok'"):
        return L + ["Još nije pročitano (ključ BIRDEYE_API_KEY ili prvi prolaz).", ""]
    n_tok = (store.q(con, "SELECT COUNT(*) FROM be_tok") or [(0,)])[0][0]
    pp = store.q(con, "SELECT COUNT(*), SUM(n_seen > 0) FROM be_pp WHERE cls IN ('prije_pumpe', 'kandidat') AND "
                      "n_checked > 0")
    L.append(f"Pročitano tokena: {n_tok}. Grupa provjereno: {pp[0][0] if pp else 0}, od njih neki novčanik u Birdeyeovu "
             f"vrhu po ostvarenoj zaradi: {(pp[0][1] or 0) if pp else 0}. Samo izvještaj, nije pravilo odabira.")
    L += ["", "### Birdeye: u vrhu po ostvarenoj zaradi na N pumpi", "",
          "| novčanik | pumpi | od toga ≥ 15M | ostvareno $ | oznake |", "|---|---|---|---|---|"]
    rows = store.q(con, "SELECT owner, n_tokens, n15, sum_realized_usd, tags FROM be_cand WHERE n_tokens >= ? ORDER BY "
                        "n15 DESC, sum_realized_usd DESC LIMIT ?", (DEFAULT["min_tokens"], int(limit)))
    for o, n, n15, s, tg in rows:
        L.append(f"| {o[:4]}…{o[-4:]} | {n} | {n15} | {s:,.0f} | {', '.join(json.loads(tg or '[]')) or '—'} |")
    if not rows:
        L.append("| — | | | | |")
    sm = store.q(con, "SELECT owner, smart_n FROM be_cand WHERE smart_n >= ? ORDER BY smart_n DESC LIMIT ?",
                 (DEFAULT["smart_min"], int(limit)))
    L += ["", "Birdeye oznaka smart_trader na 2+ pumpe: " + (", ".join(f"{o[:4]}…{o[-4:]} ({n})" for o, n in sm) or "—"),
          ""]
    return L
