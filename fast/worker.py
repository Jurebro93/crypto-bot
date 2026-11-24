"""The fast path's worker (run_fast.py loop; start.sh: low keep fast, so nice'd but never under ops.heavy --night:
it is time-sensitive, ops/cpuguard pauses it last).

Every POLL_S (0.5 s), or at once when a hook touches fast/enqueue.WAKE or the copy loop's league/copy.WAKE:
  1. the flag: off -> nothing (one cached read), the loop sleeps; the process stays small (no thread pool until on)
  2. the followed sources into fast.db (fast/sources.refresh) every sources.REFRESH_S
  3. scan (backup of the hooks): hype.db chain_trades and kol.db calls since the last rowid -> enqueue (deduped)
  4. due jobs (queued, or retry whose next_ts passed), best priority first, then the oldest, into the pool of WORKERS
     (20) threads; a running job is never taken twice
  5. every SAMPLE_S the outcomes' price points and measurements (fast/outcomes.py), the base rates every 10 min
  6. the costs into fast.db, the 23:30 report and cost line once a Zagreb day, the hourly prune
  7. 12.11.: every TICK_S, whatever fast_path's mode, x_call_scalp's tick (fast/xscalp.tick: the entries of Grok's
     submit_watch_token calls, their price points, the measurement after 65 min) while the flag x_call_scalp is not off
A job: checks (fast/checks.run_all) -> decision (fast/decide.decide) -> fast.db; CHECK_FAILED is retried after
BACKOFF_S (3, 8, 15 s: three retries within 30 s) and stays CHECK_FAILED (status failed, its reason visible) after the
last; a BUY wakes the auto loop in run_ui.py (league/copy.wake), which trades it (fast/paper.py).
"""
import datetime as dt
import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from . import checks, decide, enqueue, estimate, outcomes, sources, store, xscalp

FLAG = "fast_path"
WORKERS = 20
POLL_S = 0.5
SCAN_S = 2.0
SAMPLE_S = 30
RATES_S = 600
BACKOFF_S = (3, 8, 15)
REPORT_AT = (23, 30)
TZ = "Europe/Zagreb"
SCAN_BACK_ROWS = 5000


def mode():
    return enqueue.mode()


def limits():
    """The demo account's stake for a BUY_LIVE label (trade settings size_sol), 0.1 SOL when unreadable."""
    try:
        from rangedca import trade as rtrade
        return rtrade.limits()
    except Exception:  # noqa: BLE001
        return {"size_sol": 0.1, "max_sol_per_day": 1.0, "max_open": 5}


def process(sig, net, path=None, rates=None, now_fn=time.time, cache=None, m=None, lim=None, log=print, priors=None,
            src_rates=None):
    """One fast_check: run every check, decide, write. Returns the stored row's decision dict. priors / src_rates:
    the worker's 10-min read (fast/estimate.priors_read, outcomes.source_rates)."""
    lim = lim or limits()
    now = now_fn()
    res, d, q = checks.run_all(sig, net, now, size_sol=lim.get("size_sol"), cache=cache)
    dec = decide.decide(res, q, rates, live_sol=lim.get("size_sol") or 0.1, priors=priors,
                        src_rate=(src_rates or {}).get(sig.get("source_id")))
    t1 = now_fn()
    attempts = int(sig.get("attempts") or 0) + 1
    status, next_ts = "done", None
    if dec["decision"] == "CHECK_FAILED":
        if attempts <= len(BACKOFF_S):
            status, next_ts = "retry", t1 + BACKOFF_S[attempts - 1]
            dec["reason"] += f" (ponovno za {BACKOFF_S[attempts - 1]} s, pokušaj {attempts + 1} od {len(BACKOFF_S) + 1})"
        else:
            status = "failed"
            dec["reason"] += f" (odustao nakon {attempts} pokušaja)"
    mk = (d or {}).get("market") or {}
    pr = (res.get("price") or {}).get("values") or {}
    payload = {"res": res, "key": dec.get("key"), "base": dec.get("base"), "fails": dec.get("fails"),
               "errors": dec.get("errors"), "cached": bool((d or {}).get("cached")), "fetch_ms": (d or {}).get("ms"),
               "est": dec.get("est"), "label": dec.get("label"), "lag": dec.get("lag")}
    latency = round(t1 - float(sig.get("sig_ts") or t1), 2)
    con = store.connect(path)
    try:
        con.execute("UPDATE signals SET status=?, attempts=?, next_ts=?, decided_ts=?, decision=?, reason=?, ev_pct=?, "
                    "p_tp=?, cost_pct=?, size_sol=?, latency_s=?, work_s=?, checks=?, quality=?, mode=?, price0=?, "
                    "mcap0=?, symbol=COALESCE(symbol, ?) WHERE id=?",
                    (status, attempts, next_ts, t1, dec["decision"], dec["reason"][:600], dec.get("ev_pct"),
                     dec.get("p_tp"), dec.get("cost_pct"), dec.get("size_sol"), latency,
                     round(t1 - float(sig.get("enq_ts") or t1), 2), json.dumps(payload, ensure_ascii=False, default=str),
                     json.dumps(q or {}, ensure_ascii=False, default=str), m or mode(), pr.get("price") or mk.get("price"),
                     pr.get("mcap") or mk.get("mcap"), mk.get("symbol"), sig["id"]))
        if mk.get("price"):
            outcomes.put_px(con, sig["token"], mk["price"], mk.get("mcap"), t1)
        con.commit()
    finally:
        con.close()
    if dec["decision"] in ("BUY_PAPER", "BUY_LIVE"):
        try:
            from league import copy as lcopy
            lcopy.wake()   # the auto loop in run_ui.py takes the trade within a second (fast/paper.py)
        except Exception:  # noqa: BLE001
            pass
    sym = mk.get("symbol") or sig["token"][:6]
    log(f"fast: {dec['decision']} {sym} ({sig.get('source_label') or sig.get('source_id', '')[:8]}, "
        f"{sources.KIND_HR.get(sig.get('kind'), sig.get('kind'))}) {latency:.1f} s od signala: {dec['reason'][:200]}")
    return dict(dec, status=status, latency_s=latency, attempts=attempts)


class Worker:
    """The loop's state: the thread pool, the jobs running, the cursors, the timers (see the module text)."""

    def __init__(self, path=None, net=None, workers=WORKERS, log=print, now_fn=time.time, cache=None):
        self.path, self.log, self.now_fn = path, log, now_fn
        self.net = net or checks.Net()
        self.cache = cache if cache is not None else checks.CACHE
        self.workers = workers
        self.pool = None
        self.running = set()
        self.lock = threading.Lock()
        self.t = {"sources": 0.0, "scan": 0.0, "sample": 0.0, "rates": 0.0, "prune": 0.0, "xcall": 0.0}
        self.rates = {}
        self.priors = None      # 11.11.: fast/estimate.priors of the pooled rates (the strategy prior per kind)
        self.src_rates = {}     # 11.11.: {source id: (hits, n)} of the measured fast.db outcomes
        self.max_parallel = 0
        self.lim = None

    def _con(self):
        return store.connect(self.path)

    def start_pool(self):
        if self.pool is None:
            self.pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="fast")
            con = self._con()
            try:
                self.net.meter.load(con, self.now_fn())
                # a job left "running" by a killed worker goes back to the queue
                con.execute("UPDATE signals SET status='queued' WHERE status='running'")
                con.commit()
                if self.priors is None:   # the first jobs already get the measured priors, not the no-edge one
                    self.refresh_rates(con, self.now_fn())
            finally:
                con.close()

    def refresh_rates(self, con, now):
        """The base rates, the strategy priors and every source's own outcomes (fast/estimate.priors_read; each
        part guarded), into the worker and fast.db kv "priors" (the report, MCP and the live list read it)."""
        self.t["rates"] = now
        try:
            self.priors, self.rates, pooled = estimate.priors_read(con, now)
            self.src_rates = outcomes.source_rates(con, now)
            store.kv_put(con, "priors", {"ts": int(now), "priors": self.priors, "pooled": pooled})
            con.commit()
            line = "; ".join(f"{k} {v['p']:.0%} (n={v['n']}, {v['strategy']})" for k, v in self.priors.items()
                             if k in ("wallet_follow", "proven", "influencer", "convergence", "tool"))
            if line != getattr(self, "_prior_line", None):   # logged when it changes, not every 10 min
                self._prior_line = line
                self.log(f"fast: priori po vrsti izvora: {line}")
        except Exception as e:  # noqa: BLE001 - the old numbers stay
            self.log(f"fast: priori nisu osvježeni ({type(e).__name__}: {e})")

    def stop(self, wait=True):
        if self.pool is not None:
            self.pool.shutdown(wait=wait)
            self.pool = None

    # ---- the steps ----
    def refresh_sources(self, con, now, got=None):
        if now - self.t["sources"] < sources.REFRESH_S and got is None:
            return None
        self.t["sources"] = now
        try:
            return sources.refresh(con, now, got)
        except Exception as e:  # noqa: BLE001 - the old list stays
            self.log(f"fast: popis izvora nije osvježen ({type(e).__name__}: {e})")
            return None

    def scan(self, con, now, paths=None):
        """hype.db chain_trades (buys) and kol.db calls (kind 'call') since the stored rowids -> enqueue."""
        from league import copy as lcopy
        p = paths or lcopy._paths()
        sigs = []
        for key, db, sql, conv in (
                ("chain", p["hype"], "SELECT rowid, wallet, mint, side, ts, sol FROM chain_trades WHERE rowid > ? "
                                     "ORDER BY rowid LIMIT 3000",
                 lambda r: {"token": r[2], "source_id": r[1], "sig_ts": r[4], "side": r[3], "via": "chain_trades"}),
                ("calls", p["kol"], "SELECT rowid, token, handle, ts, kind, source, p0, mcap0 FROM calls WHERE rowid > ? "
                                    "ORDER BY rowid LIMIT 3000",
                 lambda r: {"token": r[1], "source_id": (r[2] or "").lstrip("@"), "sig_ts": r[3],
                            "side": "buy" if r[4] == "call" else "x", "via": r[5] or "kol.db",
                            "entry_px": r[6] or None, "entry_mcap": r[7] or None})):
            c = _ro_quick(db)   # a locked file costs this pass at most a second, never the queue
            if c is None:
                continue
            try:
                cur = store.kv_get(con, f"cursor_{key}")
                if cur is None:   # first run: only the newest rows, never a full scan
                    top = c.execute(f"SELECT MAX(rowid) FROM {'chain_trades' if key == 'chain' else 'calls'}").fetchone()
                    cur = max(0, int((top or [0])[0] or 0) - SCAN_BACK_ROWS)
                rows = c.execute(sql, (int(cur),)).fetchall()
            except sqlite3.Error:
                rows = []
            finally:
                c.close()
            if rows:
                store.kv_put(con, f"cursor_{key}", int(rows[-1][0]))
                sigs += [conv(r) for r in rows if r[4 if key == "chain" else 3] and now - r[4 if key == "chain" else 3]
                         <= enqueue.MAX_AGE_S]
            elif cur is not None and store.kv_get(con, f"cursor_{key}") is None:
                store.kv_put(con, f"cursor_{key}", int(cur))
        sigs += self.scan_converge(con, now, p)
        n = enqueue.submit(sigs, now=now, con=con) if sigs else 0
        con.commit()
        return n

    def scan_converge(self, con, now, p):
        """11.11. (Jure: convergence is a live candidate too): kol.db converge rows the KOL round saved since the
        cursor (its `updated`) -> signals of the pseudo-source sources.CONVERGENCE (one check per token per 10 min:
        enqueue's dedupe), with the market cap of the first measured call since the convergence began as its entry."""
        c = _ro_quick(p.get("kol"))
        if c is None:
            return []
        try:
            cur = store.kv_get(con, "cursor_converge")
            if cur is None:   # first run: only what is still fresh
                cur = int(now) - enqueue.MAX_AGE_S
            rows = c.execute("SELECT token, ts, first_ts, updated FROM converge WHERE updated > ? ORDER BY updated "
                             "LIMIT 500", (int(cur),)).fetchall()
            out = []
            for tok, ts, first, _upd in rows:
                if not ts or now - ts > enqueue.MAX_AGE_S:
                    continue
                mc = c.execute("SELECT mcap0 FROM calls WHERE token=? AND ts >= ? AND mcap0 > 0 ORDER BY ts LIMIT 1",
                               (tok, int(first or ts))).fetchone()
                out.append({"token": tok, "source_id": sources.CONVERGENCE, "sig_ts": int(ts), "via": "converge",
                            "entry_mcap": (mc[0] if mc else None)})
        except sqlite3.Error:
            return []
        finally:
            c.close()
        if rows:
            store.kv_put(con, "cursor_converge", max(int(r[3] or 0) for r in rows))
        return out

    def due(self, con, now, n):
        with self.lock:
            busy = list(self.running)
        q = ",".join("?" * len(busy))
        extra = f" AND id NOT IN ({q})" if busy else ""
        return store.read(con, f"status IN ('queued', 'retry') AND COALESCE(next_ts, 0) <= ?{extra}", (now, *busy),
                          order="priority, enq_ts", limit=n)

    def dispatch(self, con, now, m):
        free = self.workers - len(self.running)
        if free <= 0:
            return 0
        jobs = self.due(con, now, free)
        for j in jobs:
            con.execute("UPDATE signals SET status='running', started_ts=? WHERE id=?", (now, j["id"]))
        con.commit()
        for j in jobs:
            with self.lock:
                self.running.add(j["id"])
                self.max_parallel = max(self.max_parallel, len(self.running))
            self.pool.submit(self._run, j, m)
        return len(jobs)

    def _run(self, sig, m):
        try:
            process(sig, self.net, self.path, self.rates, self.now_fn, self.cache, m, self.lim, self.log,
                    priors=self.priors, src_rates=self.src_rates)
        except Exception as e:  # noqa: BLE001 - the job goes back as CHECK_FAILED, never lost, never a skip
            try:
                con = self._con()
                try:
                    att = int(sig.get("attempts") or 0) + 1
                    st = "retry" if att <= len(BACKOFF_S) else "failed"
                    con.execute("UPDATE signals SET status=?, attempts=?, next_ts=?, decision='CHECK_FAILED', reason=?, "
                                "decided_ts=? WHERE id=?",
                                (st, att, self.now_fn() + BACKOFF_S[min(att, len(BACKOFF_S)) - 1],
                                 f"provjera pala ({type(e).__name__}: {str(e)[:120]})", self.now_fn(), sig["id"]))
                    con.commit()
                finally:
                    con.close()
            except sqlite3.Error:
                pass
            self.log(f"fast: provjera #{sig['id']} pala ({type(e).__name__}: {e})")
        finally:
            with self.lock:
                self.running.discard(sig["id"])

    def side_work(self, con, now):
        """Outcomes, base rates, costs, report, prune (never in the way of the jobs: errors only logged)."""
        try:
            if now - self.t["sample"] >= SAMPLE_S:
                self.t["sample"] = now
                outcomes.sample(con, now, meter=self.net.meter)
                outcomes.measure(con, now)
            if now - self.t["rates"] >= RATES_S:
                self.refresh_rates(con, now)
                self.lim = limits()
            self.net.meter.flush(con, now)
            con.commit()
            z = dt.datetime.fromtimestamp(now, ZoneInfo(TZ))
            if (z.hour, z.minute) >= REPORT_AT and store.kv_get(con, "report_day") != z.date().isoformat():
                from . import report
                rep = report.daily(now, con=con)
                for ln in report.lines(rep):
                    self.log(ln)
                store.kv_put(con, "report_day", z.date().isoformat())
                con.commit()
            if now - self.t["prune"] >= 3600:
                self.t["prune"] = now
                store.prune(con, now)
                con.commit()
        except Exception as e:  # noqa: BLE001
            self.log(f"fast: sporedni posao ({type(e).__name__}: {e})")

    def step(self, woke=False):
        """One pass (see the module text). Returns the mode."""
        m = mode()
        if m == "off":
            return m
        now = self.now_fn()
        self.start_pool()
        con = self._con()
        try:
            if self.lim is None:
                self.lim = limits()
            self.refresh_sources(con, now)
            self.dispatch(con, now, m)   # what already waits starts first, then the new signals
            if woke or now - self.t["scan"] >= SCAN_S:
                self.t["scan"] = now
                try:
                    self.scan(con, now)
                except Exception as e:  # noqa: BLE001
                    self.log(f"fast: pregled novih signala ({type(e).__name__}: {e})")
            self.dispatch(con, now, m)
            self.side_work(con, now)
        finally:
            con.close()
        return m

    def xcall_tick(self, now=None):
        """12.11.: fast/xscalp.tick every xscalp.TICK_S (its own flag; it runs while fast_path is off too)."""
        now = now or self.now_fn()
        if now - self.t["xcall"] < xscalp.TICK_S:
            return None
        self.t["xcall"] = now
        try:
            return xscalp.tick(now, self.path, log=self.log)
        except Exception as e:  # noqa: BLE001 - the queue never waits on the measurement
            self.log(f"fast: x_call_scalp ({type(e).__name__}: {e})")
            return None

    def loop(self, max_steps=None):
        last_wake, n = time.time(), 0
        while max_steps is None or n < max_steps:
            n += 1
            t0 = time.time()
            try:
                m = self.step(woke=enqueue.woke_since(last_wake) or _copy_woke(last_wake))
            except Exception as e:  # noqa: BLE001 - the loop never dies on one pass
                self.log(f"fast: prolaz nije uspio ({type(e).__name__}: {e})")
                m = "?"
            last_wake = t0
            self.xcall_tick()
            if m == "off":
                self.stop(wait=False)
                time.sleep(15)
                continue
            # 0.5 s, cut short by a wake-up
            end = time.time() + POLL_S
            while time.time() < end:
                time.sleep(0.05)
                if enqueue.woke_since(t0):
                    break


def _ro_quick(path, timeout=1.0):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout)
    except sqlite3.Error:
        return None


def _copy_woke(ts):
    try:
        from league import copy as lcopy
        return lcopy.woke_since(ts)
    except Exception:  # noqa: BLE001
        return False
