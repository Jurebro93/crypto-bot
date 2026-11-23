"""Povlačenje nakon skoka: a faster midcap entry, measured in the DEMO only (23.11., vlasnik: "Tokeni su skočili, ali
su se i povukli. Nećemo čekati danima da se napravi range").

The signal (V6 of ops/brzi_raspon_bt.py, which imports plan_at from here, so the test and the live demo can never
drift apart), at the close of 15m bar i of the completed bars b15 ([ts, o, h, l, c, v]):

  skok      the highest high of the last 24 h (WIN bars, bar i included) is at least leg (12 %) above the lowest low
            BEFORE it inside the same window (at least MIN_BARS bars of window)
  povrat    the close of bar i gave back ret (30-60 %) of that leg
  smirenje  the last two bars made no lower low than the bar before them and the last close is not under the one
            before it (intra.calm, the day rule's own test)
  cilj      the leg's top, at least min_tp (7 %) above the entry price
  stop      2 % under the leg's low, at most cap (12 %) under the entry

The 30-day history (23 tokens >= 15 M $, 4 % cost) did NOT find it profitable: about 2.4 signals a day without a
position cap, roughly +4.6 % net at the target and -14 % net at the stop. So it is measured, never traded with real
money: only the explorer's demo account (veliki/istrazivac, varijanta TAG) and the shadow book (veliki/sjena, its own
table veliki_sjena_pov) read it. Nothing that decides real money (live's real entry, gate, riskoff, settings,
executor, nauceno / ucenik) imports this module. Pure: no I/O, no network, no database; the bars are the ones the
caller already holds.
"""
from veliki import intra

TAG = "povlacenje"
HR = "povlačenje nakon skoka"
KEY = "povlacenje/v6/cilj-vrh-skoka/stop-dno-skoka"
WIN = 96            # 24 h of 15m bars
MIN_BARS = 20       # the window must hold at least this many bars before bar i
V6 = {"leg": 0.12, "ret": (0.30, 0.60), "min_tp": 0.07, "stop_under": 0.02, "cap": 0.12}


def plan_at(b15, i, entry, v=None, btc_state=None):
    """The plan of an entry at price `entry` right after bar i closed, or None:
    {"tp_px", "stop_px", "zone": (leg_lo, leg_hi), "leg", "povrat", "hi_ts"}. btc_state "slobodan_pad" refuses (the
    history test's market gate; the live demo passes None: demo never stops, 23.11.)."""
    v = {**V6, **(v or {})}
    if btc_state == "slobodan_pad" or not entry or entry <= 0 or i < 0 or i >= len(b15):
        return None
    w0 = max(0, i - (WIN - 1))
    if i - w0 < MIN_BARS:
        return None
    hi_j = max(range(w0, i + 1), key=lambda j: b15[j][2])
    if hi_j <= w0:
        return None
    leg_hi = b15[hi_j][2]
    leg_lo = min(b15[j][3] for j in range(w0, hi_j))
    if leg_lo <= 0 or leg_hi / leg_lo - 1 < v["leg"]:
        return None
    r = (leg_hi - b15[i][4]) / (leg_hi - leg_lo)
    if not (v["ret"][0] <= r <= v["ret"][1]):
        return None
    ok, _ = intra.calm(b15[i - 2:i + 1], {"calm": 2})
    if not ok:
        return None
    if leg_hi / entry - 1 < v["min_tp"]:
        return None
    stop = max(leg_lo * (1 - v["stop_under"]), entry * (1 - v["cap"]))
    if stop >= entry:
        return None
    return {"tp_px": leg_hi, "stop_px": stop, "zone": (leg_lo, leg_hi), "leg": leg_hi / leg_lo - 1, "povrat": r,
            "hi_ts": b15[hi_j][0]}


def plan(b15, px, btc_state=None, v=None):
    """The live form: the completed bars b15 and the quote px now (the entry). None or plan_at's dict."""
    if not b15:
        return None
    return plan_at(b15, len(b15) - 1, px, v, btc_state)


def text(p, px):
    """One short Croatian description of a plan at the entry px (the league source and the log)."""
    return (f"{HR}: skok {p['leg']:+.0%} u 24 h, povrat {p['povrat']:.0%} skoka, cilj vrh skoka "
            f"{p['tp_px'] / px - 1:+.1%}, stop {p['stop_px'] / px - 1:+.1%}")
