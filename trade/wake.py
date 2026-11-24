"""13.11. (owner's order point 2: "Slippage na stop i trailing izlazima ... smanji ga (brži polling za otvorene pozicije
ili brže slanje ...)"): the dashboard process (league/auto.fast_loop, league/exitplan.run_once) sells a demo lot of the
real Autopilot account the second a stop / trailing / TP fires; run_trade.py (its own process) mirrors that sale into
the real swap. Until 13.11. run_trade noticed it only at its next pass (poll_s = 1 s, plus whatever the pass was busy
with). Now the exit rings this file and run_trade's nap between passes ends within STEP_S.

Only a file's modification time: no database, no network, nothing to lose when it is missing (run_trade then sleeps
its normal poll_s). trade/WAKE is in .gitignore; TRADE_WAKE_FILE moves it (tests).
"""
import os
import time

PATH = os.environ.get("TRADE_WAKE_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "WAKE")
STEP_S = 0.1   # how often run_trade's nap looks at the file (an os.stat: microseconds)


def ring(why=""):
    """Tell run_trade that a demo exit of the real account just happened. Never raises (an exit never waits on it)."""
    try:
        with open(PATH, "w") as f:
            f.write(f"{time.time():.3f} {why}\n")
    except OSError:
        pass


def stamp():
    """The file's modification time (ns), 0 when there is none."""
    try:
        return os.stat(PATH).st_mtime_ns
    except OSError:
        return 0


def nap(seconds, since=None, step=STEP_S, sleep=time.sleep, clock=time.monotonic):
    """Sleep up to `seconds`; True as soon as the file changed after `since` (a stamp() taken when the pass began, so
    a ring during the pass starts the next one at once), False when the time ran out."""
    since = stamp() if since is None else since
    end = clock() + max(0.0, float(seconds))
    while True:
        if stamp() != since:
            return True
        left = end - clock()
        if left <= 0:
            return False
        sleep(min(step, left))
