"""A small, bounded pool for Helius calls (19.11. navečer (2), coordinator: "make the deep read several times faster
without breaking the rate limit or the box"). Used by insajderi/chain.fetch_event_deep and wallets/povijest.run.

Threads run ONLY the network call and pure parsing (the caller's `call`); every SQLite read / write stays on the
calling thread (on_result runs there). Credits are reserved before a call is dispatched (its "cost": the most it can
cost) and the unused part comes back when it returns, so a cap is never overshot, also when workers race. The rate
is wallets/rpc.LIMIT (one token bucket for every thread of the process); when the 429s it counts grow by shrink_429
during the pool's life, the pool goes down to ONE worker and says so once. No new process: threads of the job's own
process, which keeps its nice level (ops/cpuguard is unchanged).
"""
import time


class Pool:
    """19.11. navečer: the network side of one pass's deep reads. workers threads (config pump_fetch_workers, 1 = the
    sequential read of before) run ONLY the Helius calls and the pure parsing (_rows_of); every SQLite read and write
    stays on the calling thread. Credits are reserved before a call is dispatched (10 credits x its max pages, the
    most it can cost) and the unused part comes back when it returns, so the event and pass caps hold exactly. The
    rate is wallets/rpc.LIMIT (shared by every thread of the process). When the 429s counted by wallets/rpc grow by
    shrink_429 (3) during the pass, the pool goes down to ONE worker for the rest of the pass and says so once.
    Stats for the pass line: calls, seconds, the 429s, the workers."""

    def __init__(self, workers=6, log=print, shrink_429=3, stats=None, prefix=""):
        from concurrent.futures import ThreadPoolExecutor
        self.workers = max(1, int(workers))
        self.prefix = prefix
        self.log = log
        self.shrink_429 = int(shrink_429)
        self.stats = stats if stats is not None else _rpc_stats()
        self.e0 = self.stats.get("e429", 0)
        self.c0 = self.stats.get("calls", 0)
        self.t0 = time.monotonic()
        self.shrunk = False
        self.n_calls = 0
        self.ex = ThreadPoolExecutor(max_workers=self.workers) if self.workers > 1 else None

    def width(self):
        if not self.shrunk and self.stats.get("e429", 0) - self.e0 >= self.shrink_429:
            self.shrunk = True
            self.log(f"{self.prefix}Helius 429 x{self.stats.get('e429', 0) - self.e0}: dohvat na 1 radnika do kraja "
                     "prolaza")
        return 1 if self.shrunk or self.ex is None else self.workers

    def run(self, tasks, call, budget, spent, stop=None, on_result=None):
        """Run call(task) -> (result, credits) for tasks (each a dict with "cost": its reservation) within budget -
        spent[0] credits; on_result(task, result, error) on THIS thread as each finishes. No task is dispatched after
        stop() or when its reservation does not fit. -> True when every task ran (none left for lack of budget, time
        or an error)."""
        from concurrent.futures import FIRST_COMPLETED, wait
        todo = list(tasks)
        reserved = [0]
        running = {}
        complete = True

        def submit(t):
            reserved[0] += t["cost"]
            self.n_calls += 1
            if self.ex is None:
                f = _Done(call, t)
            else:
                f = self.ex.submit(call, t)
            running[f] = t

        while todo or running:
            while todo and len(running) < self.width():
                if stop is not None and stop():
                    complete = False
                    todo = []
                    break
                if spent[0] + reserved[0] + todo[0]["cost"] > budget:
                    if running:   # the reservations in flight come back (less what they cost): wait for them
                        break
                    complete = False
                    todo = []
                    break
                submit(todo.pop(0))
            if not running:
                break
            done, _ = wait(list(running), return_when=FIRST_COMPLETED) if self.ex is not None else (list(running), None)
            for f in done:
                t = running.pop(f)
                reserved[0] -= t["cost"]
                try:
                    res, cr = f.result()
                    err = None
                except Exception as e:  # noqa: BLE001 - a failed call is the caller's to retry or leave due
                    res, cr, err = None, getattr(e, "credits", 0), e
                spent[0] += cr
                if on_result is not None:
                    again = on_result(t, res, err)
                    if again:
                        todo.insert(0, again)
                elif err is not None:
                    complete = False
        return complete

    def close(self):
        if self.ex is not None:
            self.ex.shutdown(wait=True)

    def line(self):
        secs = max(1e-6, time.monotonic() - self.t0)
        calls = self.stats.get("calls", 0) - self.c0
        n = calls if calls else self.n_calls
        return (f"dohvat: {n} poziva, {n / secs:.1f}/s prosjek, radnika {self.width()}, 429: "
                f"{self.stats.get('e429', 0) - self.e0}")


class _Done:
    """A synchronous 'future' (workers = 1: the call runs here, at submit)."""

    def __init__(self, call, t):
        try:
            self._r, self._e = call(t), None
        except Exception as e:  # noqa: BLE001
            self._r, self._e = None, e

    def result(self):
        if self._e is not None:
            raise self._e
        return self._r


def _rpc_stats():
    try:
        from wallets import rpc
        return rpc.STATS
    except Exception:  # noqa: BLE001
        return {"calls": 0, "e429": 0}
