"""When a proposal is published, and the EV it is shown with (11.11., the owner's decision 4, after HAOBIBI proposal #2).

The bug: proposal #2 (range) was made at ~$89k MC, under its entry zone $104-112k and 0.5 % above its stop $88.6k;
its EV came from the price now: TP +93 % against SL 0.5 %, EV +3.77 %, an artefact of a price outside the zone.

EV from the zone (build.finish -> at_mid): every strategy's TP / SL distances are measured from the MIDDLE of its
    entry_zone (mcap_low .. mcap_high): a level in market cap (range / catalyst / Grok: tp_mc, sl_mc) as tp_mc / mid - 1
    and 1 - sl_mc / mid; a level in percent (the signal exit, momentum, event, ...) is relative to the entry anyway and
    stays as it is. Cost: trade/cost.round_trip (build, unchanged); p: the strategy's record at those TP / SL. A strategy
    without an entry_zone keeps the market cap now (its zone is the market cap +- 5 % anyway, strategies.zone_of).
Publication (check): a proposal is shown ("Što kupiti", the Autopilot card) only while
      the market cap now is INSIDE its entry zone (strategies.zone_of), and
      market cap now - its stop (strategies.stop_of, exits_mcap sl) >= 1 x ATR in market cap
    ATR (atr_of): range (and any strategy of a token with a range row) = the range's ATR (14 x 15-minute bars, run_range
    ranges.data "atr"; rangedca/view row stop.atr_market_cap_usd); every other strategy keeps no volatility estimate of
    its own, so 5 % of the market cap now (ATR_FALLBACK).
    Else it is stored all the same (status novo, proposals.db wait_why = the reason, the state "čeka zonu"): not in "Što
    kupiti" nor on the card, but in get_proposals (entry_state "čeka zonu" with the reason) and in "prikaži skoro"
    (proposals/view.load puts it among the near misses). The pass decides it at creation / update with its market cap;
    the demo account's 20-s loop (proposals/paper.run_once, every mode but off: shadow publishes, paper also enters)
    decides it again with the market cap it reads, until expires_ts. A published proposal whose price leaves the zone
    (or comes within 1 ATR of the stop) waits again: shown means "buyable now".
#134's rules stay: the paper entry only inside the zone and above the stop, EV > 0 at the entry's market cap
(paper.ev_now), and the stop rule (under the stop after creation: isteklo; already under it at creation: it waits).
"""
from . import strategies

ATR_FALLBACK = 0.05        # strategies without an ATR of their own: 5 % of the market cap now
WAIT = "čeka zonu"


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def zone_mid(ez):
    """The middle of an entry_zone {"mcap_low", "mcap_high"} in market cap, None without a valid one."""
    lo, hi = _f((ez or {}).get("mcap_low")), _f((ez or {}).get("mcap_high"))
    if not lo or not hi or hi < lo:
        return None
    return (lo + hi) / 2


def at_mid(ev):
    """A copy of one strategy's evidence with tp / sl measured from the middle of its entry zone (see the module text);
    the evidence itself when it has no zone or no exit levels. Adds "zone_mid" (the market cap they are measured from)."""
    mid = zone_mid(ev.get("entry_zone"))
    lv = ev.get("levels") or {}
    tps, sl = lv.get("tp") or [], lv.get("sl") or {}
    if not mid or not tps or not sl:
        return ev
    t0 = tps[0]
    tp = (_f(t0["mc"]) / mid - 1) if "mc" in t0 else (_f(t0.get("pct")) or 0) / 100
    s = (1 - _f(sl["mc"]) / mid) if "mc" in sl else abs(_f(sl.get("pct")) or 0) / 100
    out = dict(ev, tp=tp, sl=s, zone_mid=round(mid))
    if s <= 0 and not out.get("invalid"):
        out["invalid"] = f"stop {strategies._usd(sl.get('mc'))} nije ispod sredine zone ulaza {strategies._usd(mid)}"
    return out


def atr_of(row, mcap):
    """(ATR in market cap, where from): the row's own (atr_mc: the range's), else ATR_FALLBACK x mcap."""
    a = _f((row or {}).get("atr_mc"))
    if a and a > 0:
        return a, (row.get("atr_from") or "ATR raspona")
    mc = _f(mcap) or 0.0
    return mc * ATR_FALLBACK, f"{ATR_FALLBACK * 100:.0f} % MC-a (strategija nema svoj ATR)"


def atr_for(rc):
    """(ATR in market cap, from) of a token's range row (rangedca/view: stop.atr_market_cap_usd), (None, None)."""
    a = _f(((rc or {}).get("stop") or {}).get("atr_market_cap_usd"))
    return (a, "ATR raspona (14 × 15 min)") if a and a > 0 else (None, None)


def check(row, mcap):
    """None when the proposal may be published at market cap mcap, else the reason in Croatian (see the module text)."""
    mc = _f(mcap)
    if not mc:
        return "nema tržišne kapitalizacije sada"
    z = strategies.zone_of(row)
    sl = strategies.stop_of(row)
    why = []
    if not z or not (z[0] * (1 - 1e-9) <= mc <= z[1] * (1 + 1e-9)):
        why.append(f"MC {strategies._usd(mc)} izvan zone ulaza {strategies.zone_text(z)}")
    if sl:
        a, src = atr_of(row, mc)
        d = mc - sl
        if d <= 0:
            why.append(f"MC ispod SL-a {strategies._usd(sl)}")
        elif d < a - 1e-9:
            why.append(f"do stopa {strategies._usd(sl)} samo {strategies._usd(d)} (< 1 × ATR {strategies._usd(a)}, "
                       f"{src})")
    return "; ".join(why) or None


def state_text(why):
    return f"{WAIT} · {why}" if why else None
