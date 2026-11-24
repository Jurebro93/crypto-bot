"""Grok's X calls: the MCP tool submit_watch_token (12.11., Jure, nalog točka 1). Buys nothing.

Grok reads X; when an account posts a token (a "call") it sends mint, author, followers, post_id, post_ts, the
engagement at that moment (likes, replies, reposts, views) and velocity. submit():
  1. validates every field (validate(): the mint base58 32-44, the handle, integers and their ranges, the post's time
     not in the future and at most 24 h old, the engagement keys), at most RATE_PER_HOUR rows an hour per key (the
     key's fingerprint, as ui/xfeat), one row per (mint, author) per DEDUPE_S (a repeat answers the stored row);
  2. stores the call in fast.db x_calls (every field, submitted_ts, the author class of fast/xscalp: followers x
     velocity) - the watch list of x_call_scalp: the row is watched (price points, then the measurement) for 65 min;
  3. runs a fast_check on it AT ONCE in this process (the same checks.run_all / decide.decide / worker.process the
     fast path runs: rug, holders, flow, price, source = the author's caller record), as fast.db signal kind "x_call"
     with the source id "x:<handle>" (the author's caller record is read by the handle; a check of the same token
     and author in the last 10 min is reused, no second cost), in a thread (at most PARALLEL at once, retried like
     the worker on CHECK_FAILED: 3, 8, 15 s);
  4. waits at most WAIT_S (10 s) and answers what it has: the decision (BUY_PAPER | BUY_LIVE | SKIP | CHECK_FAILED)
     with its checks, or state "u tijeku" with the fast_check id, to ask later with get_fast_checks(id=...).
The check's decision only labels: fast/paper never trades an x_call, fast/live.kupi_rows never proposes it. What
x_call_scalp does with it (a paper entry when the hard blocks pass): fast/xscalp.on_check.
Cost per call: one DexScreener read (free), one RugCheck report (free), Helius only when RugCheck fails (4 credits,
under the fast path's day cap); counted in fast.db costs like every fast_check.
"""
import json
import math
import re
import threading
import time

from . import store, xscalp

SOURCES = ("x_call",)
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
POST_ID = re.compile(r"[0-9]{1,25}")
STATUS_URL = re.compile(r"/status(?:es)?/([0-9]{1,25})")
ENGAGEMENT_KEYS = ("likes", "replies", "reposts", "views")
ENGAGEMENT_REQUIRED = ("likes", "replies", "reposts")
MAX_FOLLOWERS = 1_000_000_000
MAX_COUNT = 100_000_000_000
MAX_VELOCITY = 10_000_000.0
POST_MAX_AGE_S = 24 * 3600
FUTURE_S = 300
OLDEST_TS = 1_600_000_000
RATE_PER_HOUR = 60
DEDUPE_S = 600
WAIT_S = 10.0
PARALLEL = 2
CTX_S = 600
SRC_PREFIX = "x:"   # fast.db source id of an x_call: "x:<handle>", apart from a followed influencer's own "<handle>"
_SEM = threading.BoundedSemaphore(PARALLEL)
_CTX = {"ts": 0.0, "priors": None, "rates": None, "path": None}
_NET = {"net": None}


# ---------- validation ---------------------------------------------------------------------------------------------

def _int(x, name, lo=0, hi=None):
    if isinstance(x, bool) or x is None or x == "":
        raise ValueError(f"{name} must be an integer")
    try:
        v = float(str(x).strip()) if isinstance(x, str) else float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if not math.isfinite(v) or v != int(v):
        raise ValueError(f"{name} must be an integer")
    v = int(v)
    if v < lo or (hi is not None and v > hi):
        raise ValueError(f"{name} must be between {lo} and {hi}" if hi is not None else f"{name} must be >= {lo}")
    return v


def _num(x, name, lo=0.0, hi=None):
    if isinstance(x, bool) or x is None or x == "":
        raise ValueError(f"{name} must be a number")
    try:
        v = float(str(x).strip()) if isinstance(x, str) else float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(v) or v < lo or (hi is not None and v > hi):
        raise ValueError(f"{name} must be a number between {lo:g} and {hi:g}" if hi is not None
                         else f"{name} must be >= {lo:g}")
    return v


def _engagement(x):
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except ValueError:
            raise ValueError("engagement_baseline must be a JSON object {likes, replies, reposts, views}")
    if not isinstance(x, dict):
        raise ValueError("engagement_baseline must be an object {likes, replies, reposts, views}")
    extra = [k for k in x if k not in ENGAGEMENT_KEYS]
    if extra:
        raise ValueError(f"engagement_baseline: unknown key {str(extra[0])[:20]} (allowed: {', '.join(ENGAGEMENT_KEYS)})")
    out = {}
    for k in ENGAGEMENT_KEYS:
        if x.get(k) in (None, ""):
            if k in ENGAGEMENT_REQUIRED:
                raise ValueError(f"engagement_baseline.{k} is required (an integer >= 0)")
            out[k] = None
            continue
        out[k] = _int(x[k], f"engagement_baseline.{k}", 0, MAX_COUNT)
    return out


def validate(args, now=None):
    """The checked call {"mint", "source", "author", "followers", "post_id", "post_ts", "likes", "replies",
    "reposts", "views", "velocity", "velocity_src"}; ValueError with the reason for the client."""
    now = float(now or time.time())
    a = args if isinstance(args, dict) else {}
    mint = str(a.get("mint") or a.get("token") or "").strip()
    if not MINT.fullmatch(mint):
        raise ValueError("mint must be a Solana token address (base58, 32-44 characters)")
    from . import enqueue
    if mint in enqueue.STABLE:
        raise ValueError("mint is SOL or a stablecoin, not a meme token")
    src = str(a.get("source") or "x_call").strip().lower()
    if src not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    author = str(a.get("author") or "").strip().lstrip("@")
    if not HANDLE.fullmatch(author):
        raise ValueError("author must be an X handle (letters, digits, _; 1-15 characters)")
    followers = _int(a.get("followers"), "followers", 0, MAX_FOLLOWERS)
    pid = str(a.get("post_id") if a.get("post_id") is not None else "").strip()
    m = STATUS_URL.search(pid)
    if m:
        pid = m.group(1)
    if not POST_ID.fullmatch(pid):
        raise ValueError("post_id must be the X post id (digits, at most 25) or its status URL")
    pts = _int(a.get("post_ts"), "post_ts", 0)
    if pts > 100_000_000_000:   # milliseconds
        pts //= 1000
    if pts < OLDEST_TS or pts > now + FUTURE_S:
        raise ValueError("post_ts must be unix seconds of the post, not in the future")
    if pts < now - POST_MAX_AGE_S:
        raise ValueError(f"post_ts is more than {POST_MAX_AGE_S // 3600} h old: only fresh calls are watched")
    eng = _engagement(a.get("engagement_baseline"))
    if a.get("velocity") not in (None, ""):
        vel, vsrc = _num(a.get("velocity"), "velocity", 0.0, MAX_VELOCITY), "client"
    else:   # interactions per minute since the post, from the baseline
        mins = max(1.0, (now - pts) / 60)
        vel, vsrc = (eng["likes"] + eng["replies"] + eng["reposts"]) / mins, "computed"
    return {"mint": mint, "source": src, "author": author.lower(), "followers": followers, "post_id": pid,
            "post_ts": pts, **eng, "velocity": round(vel, 4), "velocity_src": vsrc}


# ---------- the fast_check ---------------------------------------------------------------------------------------------

def _signal(con, a, now):
    """(signal id, new?): a check of this token and author of the last DEDUPE_S that did not fail is reused (an
    x_call's, or the followed influencer's own from the X webhook: no second cost); else a new fast.db signal kind
    x_call, source id "x:<handle>" (never the followed influencer's "<handle>", so enqueue's dedupe cannot swallow his
    own fast path signal), status running (this process runs it; the worker never takes a running job)."""
    from . import sources
    r = con.execute("SELECT id FROM signals WHERE token=? AND lower(source_id) IN (?, ?) AND sig_ts > ? AND "
                    "COALESCE(status, '') != 'failed' ORDER BY id DESC LIMIT 1",
                    (a["mint"], a["author"], SRC_PREFIX + a["author"], int(now) - DEDUPE_S)).fetchone()
    if r:
        return int(r[0]), False
    cur = con.execute("INSERT INTO signals (token, kind, source_id, source_label, via, sig_ts, enq_ts, priority, status, "
                      "started_ts, next_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (a["mint"], "x_call", SRC_PREFIX + a["author"], "@" + a["author"], f"x_call {a['post_id']} (Grok)",
                       int(now), now, sources.PRIORITY.get("x_call", 1), "running", now, now))
    return int(cur.lastrowid), True


def _net():
    if _NET["net"] is None:
        from . import checks
        _NET["net"] = checks.Net()
    return _NET["net"]


def _context(con, now, path=None):
    """(priors, rates) for decide: the worker's fast.db kv "priors" (10 min), else estimate.priors_read (cached
    CTX_S in this process)."""
    from . import estimate, outcomes
    if _CTX["priors"] is not None and _CTX["path"] == path and now - _CTX["ts"] < CTX_S:
        return _CTX["priors"], _CTX["rates"]
    kv = store.kv_get(con, "priors") or {}
    try:
        rates = outcomes.base_rates(con, now)
    except Exception:  # noqa: BLE001
        rates = {}
    if kv.get("priors") and now - (kv.get("ts") or 0) < 2 * 3600:
        pri = kv["priors"]
    else:
        try:
            pri, rates, _pooled = estimate.priors_read(con, now)
        except Exception:  # noqa: BLE001 - the no-edge prior then
            pri = None
    _CTX.update(ts=now, priors=pri, rates=rates, path=path)
    return pri, rates


def _src_rate(con, sid, now):
    try:
        r = con.execute("SELECT COALESCE(SUM(hit), 0), COUNT(*) FROM signals WHERE lower(source_id)=? AND out_done=1 AND "
                        "hit IS NOT NULL AND decided_ts >= ?", (str(sid).lower(), now - 30 * 86400)).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return (int(r[0]), int(r[1])) if r and r[1] else None


def run_check(sid, xid, net=None, path=None, now_fn=time.time, cache=None, lim=None, log=print):
    """The fast_check of one x_call's signal (status running), its retries on CHECK_FAILED (BACKOFF_S, claimed back
    from 'retry' only while nobody else took it), then x_call_scalp's entry (xscalp.on_check). Never raises."""
    from . import checks, worker
    net = net or _net()
    try:
        with _SEM:
            for _ in range(1 + len(worker.BACKOFF_S)):
                now = now_fn()
                con = store.connect(path)
                try:
                    sig = store.one(con, sid)
                    if not sig or sig.get("status") != "running":
                        break
                    pri, rates = _context(con, now, path)
                    sr = _src_rate(con, sig.get("source_id"), now)
                    net.meter.load(con, now)
                finally:
                    con.close()
                try:
                    dec = worker.process(sig, net, path, rates, now_fn, cache if cache is not None else checks.CACHE,
                                         "x_call", lim, log, priors=pri,
                                         src_rates={sig.get("source_id"): sr} if sr else None)
                except Exception as e:  # noqa: BLE001 - the worker's rule: CHECK_FAILED, retried, never lost
                    dec = _failed(sig, e, now_fn(), path)
                con = store.connect(path)
                try:
                    net.meter.flush(con, now_fn())
                    con.commit()
                finally:
                    con.close()
                if dec.get("status") != "retry":
                    break
                con = store.connect(path)
                try:
                    nxt = (store.one(con, sid) or {}).get("next_ts") or now_fn()
                finally:
                    con.close()
                time.sleep(max(0.0, min(30.0, float(nxt) - now_fn())))
                con = store.connect(path)
                try:
                    got = con.execute("UPDATE signals SET status='running', started_ts=? WHERE id=? AND status='retry'",
                                      (now_fn(), sid)).rowcount
                    con.commit()
                finally:
                    con.close()
                if got != 1:
                    break   # the worker took the retry: its decision comes through the tick
    except Exception as e:  # noqa: BLE001
        log(f"x_call: provjera #{sid} pala ({type(e).__name__}: {e})")
    try:
        xscalp.on_check(xid, path, now_fn(), cache=cache)
    except Exception as e:  # noqa: BLE001 - the tick tries again
        log(f"x_call: ulaz x_call_scalp #{xid} nije zapisan ({type(e).__name__}: {e})")


def _failed(sig, e, now, path):
    from . import worker
    att = int(sig.get("attempts") or 0) + 1
    st = "retry" if att <= len(worker.BACKOFF_S) else "failed"
    con = store.connect(path)
    try:
        con.execute("UPDATE signals SET status=?, attempts=?, next_ts=?, decision='CHECK_FAILED', reason=?, decided_ts=? "
                    "WHERE id=?", (st, att, now + worker.BACKOFF_S[min(att, len(worker.BACKOFF_S)) - 1],
                                   f"provjera pala ({type(e).__name__}: {str(e)[:120]})", now, sig["id"]))
        con.commit()
    finally:
        con.close()
    return {"status": st, "decision": "CHECK_FAILED"}


# ---------- the tool -------------------------------------------------------------------------------------------------

def _x(con, xid):
    cur = con.execute("SELECT * FROM x_calls WHERE id=?", (int(xid),))
    r = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], r)) if r else None


def _check_out(sig, now):
    """The fast_check part of the answer: its state, decision and checks (what get_fast_checks shows of it)."""
    if not sig:
        return {"state": "missing"}
    st = sig.get("status")
    state = ("in_progress" if st in ("queued", "running") else "retrying" if st == "retry" else
             "failed" if st == "failed" or sig.get("decision") == "CHECK_FAILED" else "done")
    c = sig.get("checks") or {}
    res = c.get("res") or {}
    pv = (res.get("price") or {}).get("values") or {}
    out = {"id": sig["id"], "state": state, "kind": sig.get("kind"), "source": sig.get("source_label"),
           "query": f"get_fast_checks with id={sig['id']}"}
    if state == "in_progress":
        out["label"] = f"provjera u tijeku ({max(0, int(now - (sig.get('enq_ts') or now)))} s)"
        return out
    out.update(decision=sig.get("decision"), label=c.get("label") or sig.get("decision"), reason=sig.get("reason"),
               decided_by=c.get("key"), ev_pct=sig.get("ev_pct"), p_tp=sig.get("p_tp"), cost_pct=sig.get("cost_pct"),
               latency_s=sig.get("latency_s"), decided_ts=int(sig["decided_ts"]) if sig.get("decided_ts") else None,
               market={"price_usd": pv.get("price") or sig.get("price0"),
                       "market_cap_usd": pv.get("mcap") or sig.get("mcap0"), "liquidity_usd": pv.get("liq")},
               checks={k: {"status": (res.get(k) or {}).get("status"), "text": (res.get(k) or {}).get("text")}
                       for k in ("rug", "holders", "flow", "price", "source")} if res else None,
               note="a label only: an x_call is never traded (x_call_scalp measures a paper entry)")
    return out


def result(xid, path=None, now=None):
    """The answer of submit_watch_token for one stored x_call (also what a repeat gets)."""
    now = float(now or time.time())
    con = store.connect(path)
    try:
        x = _x(con, xid)
        sig = store.one(con, x["signal_id"]) if x and x.get("signal_id") else None
    finally:
        con.close()
    if not x:
        return {"error": "x_call not found"}
    es = x.get("entry_status")
    return {"x_call_id": x["id"], "status": "stored", "mint": x["mint"], "source": x["source"],
            "author": x["author"], "followers": x["followers"], "post_id": x["post_id"], "post_ts": x["post_ts"],
            "engagement_baseline": {k: x.get(k) for k in ENGAGEMENT_KEYS}, "velocity": x["velocity"],
            "velocity_src": x["velocity_src"], "submitted_ts": x["submitted_ts"],
            "class": {"followers_band": x["fol_band"], "velocity_band": x["vel_band"], "class": x["cls"]},
            "watch": {"until_ts": int((x.get("entry_ts") or x["submitted_ts"]) + xscalp.HORIZON_S + xscalp.GRACE_S),
                      "note": "watched 65 min: price points from the cheap sources, then max gain before -8 %, +15 min, "
                              "+1 h net of cost (get_x_call_stats)"},
            "fast_check": _check_out(sig, now),
            "x_call_scalp": {"mode": x["xmode"], "entry": es, "why": x.get("entry_why"),
                             "entry_mcap_usd": x.get("mcap0"), "entry_ts": int(x["entry_ts"]) if x.get("entry_ts") else None,
                             "cost_pct": round(x["cost"] * 100, 2) if x.get("cost") is not None else None,
                             "rule": "paper entry at the detection's market cap when no hard block applies (rug hard, "
                                     "honeypot, liquidity < $15k, MC < $30k, bonding curve); never a real or demo trade"},
            "trading": "none: submit_watch_token never buys"}


def submit(args, kid="local", now=None, net=None, path=None, wait_s=WAIT_S, cache=None, run=True, log=print, lim=None):
    """MCP submit_watch_token (see the module text). ValueError with the reason for the client."""
    now = float(now or time.time())
    a = validate(args, now)
    fb, vb, cls = xscalp.classify(a["followers"], a["velocity"])
    xmode = xscalp.mode()
    con = store.connect(path)
    try:
        n = con.execute("SELECT COUNT(*) FROM x_calls WHERE kid=? AND submitted_ts > ?",
                        (kid, int(now) - 3600)).fetchone()[0]
        if n >= RATE_PER_HOUR:
            raise ValueError(f"rate limit: at most {RATE_PER_HOUR} submit_watch_token calls an hour per key")
        dup = con.execute("SELECT id FROM x_calls WHERE mint=? AND author=? AND submitted_ts > ? ORDER BY id DESC LIMIT 1",
                          (a["mint"], a["author"], int(now) - DEDUPE_S)).fetchone()
        if dup:
            con.close()
            con = None
            return dict(result(dup[0], path, now), duplicate=True,
                        message=f"the same token and author came in the last {DEDUPE_S // 60} min: the stored call")
        sid, new = _signal(con, a, now)
        cur = con.execute("INSERT INTO x_calls (mint, source, author, followers, post_id, post_ts, likes, replies, reposts, "
                          "views, velocity, velocity_src, fol_band, vel_band, cls, submitted_ts, kid, signal_id, xmode, "
                          "entry_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (a["mint"], a["source"], a["author"], a["followers"], a["post_id"], a["post_ts"], a["likes"],
                           a["replies"], a["reposts"], a["views"], a["velocity"], a["velocity_src"], fb, vb, cls,
                           int(now), kid, sid, xmode, "off" if xmode == "off" else "pending"))
        xid = int(cur.lastrowid)
        if xmode == "off":
            con.execute("UPDATE x_calls SET entry_why=? WHERE id=?", ("x_call_scalp isključen: bez papirnatog ulaza", xid))
        con.commit()
    finally:
        if con is not None:
            con.close()
    log(f"x_call: #{xid} {a['mint'][:8]} od @{a['author']} ({cls}), fast_check #{sid}" + ("" if new else " (postojeći)"))
    if run:
        kw = ({"net": net, "path": path, "cache": cache, "log": log, "lim": lim} if new
              else {"path": path, "cache": cache})
        th = threading.Thread(target=run_check if new else _entry_only, name=f"xcall-{xid}", daemon=True,
                              args=(sid, xid), kwargs=kw)
        th.start()
        th.join(max(0.0, float(wait_s)))
    return result(xid, path)


def _entry_only(sid, xid, path=None, cache=None):
    """A reused check: the entry as soon as it is decided (polled up to WAIT_S; the tick does the rest)."""
    end = time.time() + WAIT_S
    while time.time() < end:
        if xscalp.on_check(xid, path, cache=cache) != "pending":
            return
        time.sleep(0.25)
