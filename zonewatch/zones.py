"""The zone state machine (pure: no database, no clock of its own; the tests give it any series).

A zone is a dict with zone_type (bottom | dca | top | stop | custom | team_catalyst), lo, hi (market cap USD) and
source (manual | range | event). What "inside" means:
    bottom, dca, custom   lo <= mcap <= hi
    top                   mcap >= lo (top_lo): above top_hi is still the top reached
    stop                  mcap <= hi (a stop given as one number has lo = hi)
Hysteresis HYST (0.5 %): once inside, the zone is left only HYST beyond its edge, so a price jittering on an edge
does not flap enter / exit / enter.

Events per (mint, zone):
    outside -> inside   zone_enter (bottom, dca, custom), top_hit (top), stop_hit (stop)
    inside -> outside   zone_exit (bottom, dca, custom, top); a stop has none (back above the stop is not an alarm)
The first observation of a zone only sets its state; a hand-armed zone (manual / event) whose price is already
inside alarms once then (initial=True: the arm was meant to catch it), a range zone never (it moves every 5 min).
Debounce (job.py): the same mint + zone_type + event at most once in DEBOUNCE_S (30 min); stop_hit at most once in
STOP_DEBOUNCE_S (60 s) and never held back longer.
"""
import os


def _env_f(name, default, lo, hi):
    try:
        v = float(os.environ.get(name) or default)
    except ValueError:
        v = float(default)
    return min(hi, max(lo, v))


HYST = _env_f("ZONEWATCH_HYST", 0.005, 0.0, 0.05)
NEAR = _env_f("ZONEWATCH_NEAR", 0.10, 0.01, 0.5)   # within 10 % of a zone: the fast poll
DEBOUNCE_S = int(_env_f("ZONEWATCH_DEBOUNCE_S", 1800, 60, 86400))
STOP_DEBOUNCE_S = 60
ENTER = {"top": "top_hit", "stop": "stop_hit"}
EVENTS = ("zone_enter", "zone_exit", "stop_hit", "top_hit", "team_catalyst")
HAND = ("manual", "event")   # sources armed by a person or by Grok


def interval(z):
    """(lower, upper) bound of "inside", None = open on that side."""
    t = z["zone_type"]
    if t == "stop":
        return None, float(z["hi"] if z.get("hi") is not None else z["lo"])
    if t == "top":
        return float(z["lo"]), None
    return float(z["lo"]), float(z["hi"])


def is_inside(z, mcap, was_inside=False, hyst=HYST):
    """Inside the zone at this market cap; once inside, it takes `hyst` beyond an edge to be outside."""
    lo, hi = interval(z)
    if was_inside:
        return (lo is None or mcap >= lo * (1 - hyst)) and (hi is None or mcap <= hi * (1 + hyst))
    return (lo is None or mcap >= lo) and (hi is None or mcap <= hi)


def distance(z, mcap):
    """(distance as a share of mcap, side): 0.0 "inside", else how far the nearest edge is ("below" = the zone is
    below the price, the price has to fall to it; "above" = it has to rise). (None, None) without a price."""
    if not mcap or mcap <= 0:
        return None, None
    lo, hi = interval(z)
    if lo is not None and mcap < lo:
        return (lo - mcap) / mcap, "above"
    if hi is not None and mcap > hi:
        return (mcap - hi) / mcap, "below"
    return 0.0, "inside"


def near(zs, mcap, share=NEAR):
    """The smallest distance of any of these zones, and whether it is within `share` (the fast poll)."""
    ds = [d for d, _ in (distance(z, mcap) for z in zs) if d is not None]
    if not ds:
        return None, False
    d = min(ds)
    return d, d <= share


def step(z, prev, mcap, ts, hyst=HYST):
    """One observation. prev: the zone's last state {"inside", "since_ts", "last_mcap", "last_ts"} or None (never
    seen). Returns (new state, event or None, extra) with extra {"initial", "direction"}."""
    first = prev is None or prev.get("inside") is None
    was = bool(prev and prev.get("inside"))
    now_in = is_inside(z, mcap, was and not first, hyst)
    last = (prev or {}).get("last_mcap")
    direction = None if not last else ("down" if mcap < last else "up" if mcap > last else "flat")
    st = {"inside": now_in, "since_ts": (prev or {}).get("since_ts") if (not first and now_in == was) else int(ts),
          "last_mcap": float(mcap), "last_ts": int(ts)}
    ev = None
    if first:
        if now_in and z.get("source") in HAND:
            ev = ENTER.get(z["zone_type"], "zone_enter")
        return st, ev, {"initial": True, "direction": direction}
    if now_in and not was:
        ev = ENTER.get(z["zone_type"], "zone_enter")
    elif was and not now_in and z["zone_type"] != "stop":
        ev = "zone_exit"
    return st, ev, {"initial": False, "direction": direction}


def debounce_s(event):
    return STOP_DEBOUNCE_S if event == "stop_hit" else DEBOUNCE_S
