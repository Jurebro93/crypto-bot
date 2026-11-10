"""Availability check: is the web app answering, asked every 30 seconds from inside the container.

10.11. (Jure: "aplikacija mora biti dostupna u svakom momentu"). On 9.11. the dashboard process was alive but
answered nothing for minutes and nobody knew until the owner opened the page. This loop asks the cheapest address
the app has and writes down every slow and every missing answer, so the log shows when and for how long.

    GET http://127.0.0.1:$PORT/healthz, at most TIMEOUT_S (5 s)
      200                       fine; slower than SLOW_S (2 s): one log line with the time it took
      503 from deploy_wait.py   the stand-in that holds the port while run_ui.py loads after a deploy (it marks its
                                answers with X-MemeSonar-Deploy): a deploy, not an outage
      anything else, or nothing a failure: one log line each, with the time of day

Failures in a row for FAIL_SPAN_S (150 s) or longer: SIGTERM to the run_ui.py process ONLY (never a page-build child,
never another loop); start.sh's keep brings it back 30 s later. Not in the first GRACE_S (5 min) after this check
or the dashboard process started (loading after a deploy or a restart takes time, and ending a process that is
still starting only starts the wait again), and at most once in COOLDOWN_S (15 min). UPTIME_RESTART=0: log only.

/healthz (run_ui.Handler.do_GET) answers "ok" before any page logic: no database, no cache, and of the login only the
cookie parsing, which finds nothing (this check sends no cookie). A test holds it to that, with every sqlite3.connect
failing (tests/test_uptime_offline.py): a health check that waits behind a locked database would end a healthy server.

    python3 -m ops.uptime            the loop (start.sh: keep uptime ..., web service only)
    python3 -m ops.uptime --once     one check, printed
"""
import http.client
import os
import signal
import sys
import time

from ops import cpuguard

EVERY_S, TIMEOUT_S, SLOW_S = 30, 5, 2
FAIL_SPAN_S, GRACE_S, COOLDOWN_S = 150, 300, 900
SUMMARY_EVERY_S = 3600
RESTART = os.environ.get("UPTIME_RESTART", "1") != "0"
DEPLOY_HEADER = "X-MemeSonar-Deploy"   # deploy_wait.py sets it on every answer


def check(port, timeout=TIMEOUT_S, clock=time.monotonic, connect=http.client.HTTPConnection):
    """("ok" | "deploy" | "fail", seconds it took, what came back in plain words). Straight to 127.0.0.1 with
    http.client: no proxy settings, no redirects, nothing but this one request."""
    t = clock()
    try:
        c = connect("127.0.0.1", port, timeout=timeout)
        try:
            c.request("GET", "/healthz")
            r = c.getresponse()
            r.read(64)
            code, deploy = r.status, r.getheader(DEPLOY_HEADER)
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001 - refused, reset, timed out, half an answer: all of them mean "no answer"
        return "fail", clock() - t, _why(e)
    took = clock() - t
    if code == 503 and deploy:
        return "deploy", took, "deploy u tijeku"
    if code != 200:
        return "fail", took, f"odgovor {code}"
    if took > timeout:   # the pieces each came inside the timeout, the whole did not
        return "fail", took, "isteklo vrijeme"
    return "ok", took, "u redu"


def _why(e):
    """A failed request in plain words."""
    if isinstance(e, TimeoutError):
        return "isteklo vrijeme"
    if isinstance(e, ConnectionRefusedError):
        return "na portu nitko ne sluša"
    if isinstance(e, ConnectionError):
        return "veza prekinuta"
    return f"{type(e).__name__}: {e}"[:80]


def ui_procs(proc=cpuguard.PROC):
    """[(pid, seconds since it started)] of the dashboard: run_ui.py without --render, started from our folder."""
    with open(os.path.join(proc, "uptime")) as f:
        up = float(f.read().split()[0])
    out = []
    for pid in os.listdir(proc):
        if not pid.isdigit():
            continue
        try:
            comm, _state, _ticks, start = cpuguard.proc_stat(pid, proc)
            if not comm.startswith("python"):
                continue
            got = cpuguard.classify(cpuguard.cmdline(pid, proc))
        except (OSError, ValueError, IndexError):
            continue
        if got and got[0] == "ui" and cpuguard.ours(pid, proc):
            out.append((int(pid), up - start / cpuguard.CLK_TCK))
    return out


def _stamp():
    return time.strftime("%H:%M:%S", time.gmtime()) + " UTC"


class Watch:
    def __init__(self, port, check=check, ui_procs=ui_procs, kill=os.kill, clock=time.monotonic, sleep=time.sleep,
                 log=None, restart=RESTART):
        self.port, self.check, self.ui_procs, self.kill = port, check, ui_procs, kill
        self.clock, self.sleep, self.restart = clock, sleep, restart
        self.log = log or (lambda s: print(s, flush=True))
        self.started = clock()
        self.fails, self.fail_since = 0, None   # the run of failures in a row: how many, and when the first was sent
        self.last_restart = None
        self.in_deploy = False
        self._reset_stats()

    def _reset_stats(self):
        self.n = self.n_slow = self.n_fail = 0
        self.slowest = 0.0
        self.t_summary = self.clock()

    def step(self):
        """One check. Returns its status."""
        status, took, what = self.check(self.port)
        now = self.clock()
        self.n += 1
        if status == "fail":
            self.n_fail += 1
            self._failed(now, took, what)
            return status
        if self.fails:
            self.log(f"dostupnost: /healthz opet odgovara nakon {now - self.fail_since:.0f} s bez odgovora "
                     f"(neuspjelih provjera zaredom: {self.fails}), {_stamp()}")
        self.fails, self.fail_since = 0, None
        if status == "deploy":
            if not self.in_deploy:   # once per deploy, not every 30 s of it
                self.log("dostupnost: deploy u tijeku, port drži zamjenska stranica dok se aplikacija ne upali, "
                         + _stamp())
            self.in_deploy = True
            return status
        self.in_deploy = False
        self.slowest = max(self.slowest, took)
        if took > SLOW_S:
            self.n_slow += 1
            self.log(f"dostupnost: /healthz spor, odgovor nakon {took:.1f} s, {_stamp()}")
        return status

    def _failed(self, now, took, what):
        self.fails += 1
        if self.fail_since is None:
            self.fail_since = now - took
        span = now - self.fail_since
        kill, note = self.decide(now, span)
        self.log(f"dostupnost: /healthz ne odgovara ({what}, {took:.1f} s), {self.fails}. put zaredom, već {span:.0f} s"
                 + (f"; {note}" if note else "") + f", {_stamp()}")
        for pid in kill:
            # the clear line first, the signal after it
            self.log(f"dostupnost: aplikacija ne odgovara već {span:.0f} s (neuspjelih provjera zaredom: {self.fails}): "
                     f"gasim samo proces sučelja (pid {pid}), nadzor ga vraća za 30 s; ostale petlje i trade se ne diraju")
            try:
                self.kill(pid, signal.SIGTERM)
            except OSError as e:
                self.log(f"dostupnost: proces sučelja (pid {pid}) nije ugašen: {e}")
        if kill:
            self.last_restart = now

    def decide(self, now, span):
        """([pids of the dashboard to end now], why not, in plain words). Every reason to wait comes before the pids."""
        if span < FAIL_SPAN_S:
            return [], ""
        if not self.restart:
            return [], "ponovno pokretanje je isključeno (UPTIME_RESTART=0), samo bilježim"
        if now - self.started < GRACE_S:
            return [], f"prvih {GRACE_S // 60} min nakon starta sučelje ne diram"
        if self.last_restart is not None and now - self.last_restart < COOLDOWN_S:
            return [], (f"sučelje je već ponovno pokrenuto prije {(now - self.last_restart) / 60:.0f} min, sljedeći put "
                        f"najranije za {(COOLDOWN_S - (now - self.last_restart)) / 60:.0f} min")
        try:
            procs = self.ui_procs()
        except OSError as e:
            return [], f"popis procesa se ne da pročitati ({e})"
        if not procs:
            return [], "procesa sučelja nema, nadzor ga upravo diže"
        old = [pid for pid, age in procs if age >= GRACE_S]
        if not old:
            return [], f"proces sučelja radi tek {max(age for _, age in procs):.0f} s, čekam da se upali"
        return old, ""

    def summary(self):
        if not self.n:
            return "dostupnost: u zadnjih sat vremena nijedna provjera"
        s = f"dostupnost: zadnjih {(self.clock() - self.t_summary) / 60:.0f} min, provjera: {self.n}, "
        s += "sve u redu" if not (self.n_fail or self.n_slow) else f"bez odgovora: {self.n_fail}, sporih: {self.n_slow}"
        return s + f", najsporiji odgovor {self.slowest:.2f} s"

    def run(self, steps=None):
        self.log(f"dostupnost: provjeravam 127.0.0.1:{self.port}/healthz svakih {EVERY_S} s; nakon {FAIL_SPAN_S} s bez "
                 "odgovora " + ("gasim samo proces sučelja (najviše jednom u 15 min)" if self.restart
                                else "samo bilježim (ponovno pokretanje isključeno)"))
        while steps is None or steps > 0:
            t = self.clock()
            try:
                self.step()
                if self.clock() - self.t_summary >= SUMMARY_EVERY_S:
                    self.log(self.summary())
                    self._reset_stats()
            except Exception as e:  # noqa: BLE001 - the check must outlive its own mistakes
                self.log(f"dostupnost: greška u provjeri, nastavljam ({type(e).__name__}: {e})")
            self.sleep(max(1.0, EVERY_S - (self.clock() - t)))
            steps = None if steps is None else steps - 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else int(os.environ.get("PORT") or 8050)
    if "--once" in argv:
        status, took, what = check(port)
        print(f"dostupnost: {status} ({what}), {took:.2f} s")
        return 0 if status != "fail" else 1
    Watch(port).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
