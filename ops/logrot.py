"""Log rotation (12.11., Jure: "Rotacija logova: najviše 7 dana ili 200 MB, gzip starijih").

The service's own log goes to stdout (Render keeps it, not our disk). What lands on the data disk are the files under
output/ (a symlink to DATA_DIR/output): job logs (ui/jobs: output/job-<name>.log), the demo journal
(output/paper/journal.log) and the other *.log files there. Each live *.log is rotated (copy, gzip, then truncated in
place, so a writer with the file open in append mode simply goes on) once a day or as soon as it passes ROTATE_MB;
archives (<name>.log.<YYYYmmdd-HHMM>.gz) older than KEEP_D days are deleted, and while all logs together are over
MAX_MB the oldest archives go first. The demo journal's archives are never deleted (only gzipped): it is a log of
demo buys and sells, and the owner's rule keeps trade history.

    python3 -m ops.logrot          rotate now (log line of what was done)
"""
import gzip
import json
import os
import shutil
import sys
import time

from ops import disk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = (os.path.join(ROOT, "output"),)
KEEP_D = float(os.environ.get("LOGROT_KEEP_D", "7"))
MAX_MB = float(os.environ.get("LOGROT_MAX_MB", "200"))
ROTATE_MB = float(os.environ.get("LOGROT_ROTATE_MB", "20"))
ROTATE_EVERY_S = 86400
KEEP_FOREVER = ("journal.log",)   # demo buys and sells: archives gzipped, never deleted
STATE = ".logrot.json"
D = 86400


def _state_path(data_dir=None):
    return os.path.join(data_dir or disk.DATA_DIR, STATE)


def _load(data_dir=None):
    try:
        with open(_state_path(data_dir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st, data_dir=None):
    p = _state_path(data_dir)
    try:
        with open(p + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def _walk(dirs):
    live, archives = [], []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _sub, names in os.walk(d):
            for n in names:
                p = os.path.join(root, n)
                if n.endswith(".log"):
                    live.append(p)
                elif ".log." in n and n.endswith(".gz"):
                    archives.append(p)
    return live, archives


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _rotate(path, now):
    """Copy the live log into a gzip archive, then truncate it in place. -> archive path or None."""
    stamp = time.strftime("%Y%m%d-%H%M", time.gmtime(now))
    arc = f"{path}.{stamp}.gz"
    n = 1
    while os.path.exists(arc):
        n += 1
        arc = f"{path}.{stamp}-{n}.gz"
    try:
        with open(path, "rb") as src, gzip.open(arc, "wb") as dst:
            shutil.copyfileobj(src, dst)
        with open(path, "r+b") as f:
            f.truncate(0)
        return arc
    except OSError:
        try:
            os.remove(arc)
        except OSError:
            pass
        return None


def _keep_forever(arc):
    return any(os.path.basename(arc).startswith(k + ".") for k in KEEP_FOREVER)


def rotate(now=None, dirs=None, data_dir=None, force=False, log=print):
    """One pass: rotate what is due (force: every non-empty live log), delete old / excess archives.
    -> {"rotated", "deleted", "freed_mb", "total_mb"}."""
    now = now or time.time()
    dirs = DIRS if dirs is None else dirs
    st = _load(data_dir)
    done = st.setdefault("rotated", {})
    live, archives = _walk(dirs)
    rotated = []
    before = sum(_size(p) for p in live + archives)
    for p in live:
        size = _size(p)
        if not size:
            continue
        last = done.get(p)
        if force or size > ROTATE_MB * 1e6 or (last is None and size > 1e6) or (last and now - last >= ROTATE_EVERY_S):
            arc = _rotate(p, now)
            if arc:
                rotated.append(arc)
                done[p] = int(now)
        elif last is None:
            done[p] = int(now)     # a small new log: its day starts now
    live, archives = _walk(dirs)
    deleted = []
    archives.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    for p in list(archives):
        if not _keep_forever(p) and now - os.path.getmtime(p) > KEEP_D * D:
            try:
                os.remove(p)
                deleted.append(p)
                archives.remove(p)
            except OSError:
                pass
    total = sum(_size(p) for p in live + archives)
    for p in list(archives):
        if total <= MAX_MB * 1e6:
            break
        if _keep_forever(p):
            continue
        size = _size(p)
        try:
            os.remove(p)
            deleted.append(p)
            total -= size
        except OSError:
            pass
    _save(st, data_dir)
    out = {"rotated": len(rotated), "deleted": len(deleted), "freed_mb": round(max(0, before - total) / 1e6, 1),
           "total_mb": round(total / 1e6, 1)}
    if rotated or deleted:
        log(f"logovi: rotirano {out['rotated']}, obrisano starih arhiva {out['deleted']}, oslobođeno "
            f"{out['freed_mb']} MB, logovi ukupno {out['total_mb']} MB (najviše {KEEP_D:g} dana / {MAX_MB:g} MB)")
    return out


def main(argv=None):
    rotate(force="--force" in (argv or []))


if __name__ == "__main__":
    main(sys.argv[1:])
