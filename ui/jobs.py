"""On-demand background runs started from the dashboard (one at a time per job, output to output/job-<name>.log)."""
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDITS = os.environ.get("WALLETS_RUN_CREDITS", "12000")
JOBS = {
    "wallets": [[sys.executable, "run_wallets.py", "harvest", "--feeds", "--tokens", "15"],
                [sys.executable, "run_wallets.py", "score", "--credits", CREDITS, "--max", "1000"],
                [sys.executable, "run_wallets.py", "copy"]],
}
_running = {}  # name -> start time
_last = {}     # name -> (start, end, exit code)
_lock = threading.Lock()


def _log(name):
    return os.path.join(ROOT, "output", f"job-{name}.log")


def _run(name):
    code = 0
    with open(_log(name), "w") as f:
        for cmd in JOBS[name]:
            f.write(f"$ {' '.join(cmd[1:])}\n")
            f.flush()
            code = subprocess.call(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
            if code:
                break
    with _lock:
        _last[name] = (_running.pop(name), time.time(), code)


def start(name):
    """Start job `name` in the background. False if it is already running."""
    with _lock:
        if name not in JOBS or name in _running:
            return False
        _running[name] = time.time()
    os.makedirs(os.path.dirname(_log(name)), exist_ok=True)
    threading.Thread(target=_run, args=(name,), daemon=True).start()
    return True


def status(name):
    """(running_since or None, last (start, end, code) or None, tail of the log)."""
    tail = ""
    if os.path.exists(_log(name)):
        with open(_log(name), errors="replace") as f:
            tail = "".join(f.readlines()[-15:])
    with _lock:
        return _running.get(name), _last.get(name), tail
