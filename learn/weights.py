"""Learned weights per class live on the persistent disk (LEARNED_DIR, default $DATA_DIR/learned or ./learned), so
a redeploy keeps them. Without a learned file a class uses hype/weights.json."""
import json
import os
import shutil
import time

from hype import score

LEARNED_DIR = os.environ.get("LEARNED_DIR") or os.path.join(os.environ.get("DATA_DIR") or
                                                              os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "learned")


def path(klasa):
    return os.path.join(LEARNED_DIR, f"weights.{klasa}.json")


def load(klasa, base=None):
    """Weights for a class: learned file when it exists, else the base (hype/weights.json)."""
    try:
        with open(path(klasa)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return dict(base) if base is not None else score.load_weights()


def save(klasa, weights, now=None):
    """Write the new weights, keeping the previous file as .prev for a rollback."""
    os.makedirs(LEARNED_DIR, exist_ok=True)
    p = path(klasa)
    if os.path.exists(p):
        shutil.copy(p, p + ".prev")
    with open(p, "w") as f:
        json.dump(weights, f, indent=1)
    return p


def rollback(klasa):
    p = path(klasa)
    if os.path.exists(p + ".prev"):
        shutil.move(p + ".prev", p)
        return True
    return False


def for_rows(rows, base):
    """Per-class weight dicts for the classes present in scan rows; one file read per class."""
    out = {}
    for r in rows:
        k = (r.get("tier") or {}).get("klasa") or "rizican"
        if k not in out:
            out[k] = load(k, base)
    return out
