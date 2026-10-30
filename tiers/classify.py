"""Token class (moonshot / rizican / event / stabilni) and the shape of the path that got it to its mcap."""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
KLASE = ("moonshot", "rizican", "event", "stabilni")
KLASA_HR = {"moonshot": "Moonshot", "rizican": "Rizičan", "event": "Event", "stabilni": "Stabilni"}


def config():
    with open(os.path.join(HERE, "config.json")) as f:
        return json.load(f)


def klasa(mcap, age_h, event_role=None, cfg=None):
    """Class from size, age and the calendar link. A real event token is always 'event'; the rest by mcap."""
    c = (cfg or config())["klase"]
    if event_role == "canonical":
        return "event"
    mcap, age_h = mcap or 0, age_h if age_h is not None else 999
    if mcap < c["moonshot"]["mcap_max"] and age_h < c["moonshot"]["age_max_h"]:
        return "moonshot"
    if mcap >= c["stabilni"]["mcap_min"] and age_h >= c["stabilni"]["age_min_h"]:
        return "stabilni"
    return "rizican"


def put(snaps):
    """Shape of the mcap path from [(ts, mcap)] snapshots, oldest first; None values when there is too little.

    brzina: log growth per hour from the first snapshot (0 = flat, 0.7 = doubled every hour).
    skokovitost: share of the total rise that came in the single biggest step (1 = one jump, ~0 = steady).
    zadrzavanje: current mcap as a share of the peak (1 = at the top, 0.3 = gave back 70%).
    """
    pts = [(ts, m) for ts, m in snaps if m and m > 0]
    if len(pts) < 3:
        return {"put_brzina": None, "put_skokovitost": None, "put_zadrzavanje": None}
    pts.sort()
    first, last = pts[0], pts[-1]
    hours = max((last[0] - first[0]) / 3600, 1 / 60)
    brzina = math.log(last[1] / first[1]) / hours
    rise = last[1] - first[1]
    steps = [b[1] - a[1] for a, b in zip(pts, pts[1:])]
    skok = max(steps) / rise if rise > 0 and max(steps) > 0 else 0.0
    peak = max(m for _, m in pts)
    return {"put_brzina": round(brzina, 4), "put_skokovitost": round(min(1.0, skok), 3),
            "put_zadrzavanje": round(last[1] / peak, 3)}


def put_features(shape):
    """0-1 features for the hype score (weight 0 until the fit learns them)."""
    if shape.get("put_skokovitost") is None:
        return {}
    return {"put_brzina": max(0.0, min(1.0, shape["put_brzina"] / 0.7)),
            "put_skokovitost": shape["put_skokovitost"],
            "put_zadrzavanje": shape["put_zadrzavanje"]}
