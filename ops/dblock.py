"""Who holds a SQLite file, and a retry for writes that meet "database is locked".

8.11.: the scanner died ~10 times a night on one locked INSERT (hype.db) although its connection waits 60 s, and the
log never said who held the file. retry() waits and tries again, and on every failure prints the processes that
have the file open (/proc, no lsof on the server), so the long writer gets a name.
"""
import os
import sqlite3
import time


def holders(path):
    """[(pid, short cmdline)] of processes with `path` (or its -wal / -journal) open, from /proc."""
    want = {os.path.realpath(path), os.path.realpath(path) + "-wal", os.path.realpath(path) + "-journal"}
    out = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    if os.readlink(f"/proc/{pid}/fd/{fd}") in want:
                        with open(f"/proc/{pid}/cmdline", "rb") as f:
                            cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
                        parts = [c for c in cmd.split() if not c.startswith("/")] or [cmd]
                        out.append((int(pid), " ".join(parts)[:80]))
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return out


def retry(fn, label, tries=4, wait=20, log=print, path=None):
    """Call fn(); on sqlite3.OperationalError 'database is locked' wait and try again, naming the holders."""
    for i in range(1, tries + 1):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or i == tries:
                if "locked" in str(e) and path:
                    log(f"baza zauzeta ({label}): odustajem nakon {tries} pokušaja; drže je: {holders(path)}", flush=True)
                raise
            log(f"baza zauzeta ({label}), pokušaj {i}/{tries}, čekam {wait} s; drže je: "
                f"{holders(path) if path else '?'}", flush=True)
            time.sleep(wait)
