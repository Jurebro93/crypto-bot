"""Crash survivors (14.11., Jure: "Ako je neki token izdržao ovaj bloodbath što se dogodio noćas i ako se vratio u
range, pronađi ga"). Pure: run_range.py computes it at every full detection (ranges.data "survivor"), the backtest at
every entry, get_range_candidates shows it on every row, and the demo profile (rules.DEMO "survivor") enters only
a survivor.

A token survived the crash when all three hold:
  age      it existed before the crash: >= AGE_MIN_H (24 h) old (the pool's creation: rangedca/market's created_ts,
           the DexScreener pair's (range.db snap_ext) or the GeckoTerminal seed; unknown: its own series reaches back
           REF_MIN_H (22 h) of the 24 h window, so it traded before the window began)
  loss     its MC now is at most MAX_LOSS (45 %) under the level 24 h ago (before the crash): DexScreener's own 24 h
           price change of the pair when the snapshot has it (snaps.ch_h24), else the close of the series' candle at
           or before now - 24 h (the series must reach back at least REF_MIN_H, 22 h)
  range    it is back inside a range: the range detector's status is "aktivan" (not broken down / up, not excluded)
           and range_flip does not hold it in a pause after a break down or as a flip candidate
The deepest fall of the last 24 h against that level is shown next to it (trough), never a reason.
"""
AGE_MIN_H = 24.0
MAX_LOSS = 0.45
REF_MIN_H = 22.0
BLOCKED_FLIP = ("paused", "flip_candidate")


def _pct(x):
    return f"{x * 100:+.0f} %".replace("-", "−")


def _age_txt(h):
    return f"{h / 24:.1f} d".replace(".", ",") if h >= 48 else f"{h:.0f} h"


def check(candles, now, res, age_h=None, ch_h24=None, price=None):
    """{"ok", "age_h", "age_known", "loss_24h", "trough_24h", "ref_from", "in_range", "why"} of one token at `now`.
    candles: its series (oldest first, detect's tuples) reaching back 24 h when we have it; res: the range of now
    (detect.analyze, with its "flip" block when range_flip computed one); age_h: the pool's age when known; ch_h24:
    DexScreener's 24 h price change in % of the latest snapshot (None unknown); price: now (default the range's)."""
    now = int(now)
    res = res or {}
    cs = [c for c in candles or () if c[0] <= now and c[4] and c[4] > 0]
    px = price or ((res.get("metrics") or {}).get("price")) or (cs[-1][4] if cs else None)
    span_h = (now - cs[0][0]) / 3600 if cs else 0.0
    age_known = age_h is not None
    age = float(age_h) if age_known else span_h
    loss, ref_from, ref = None, None, None
    if ch_h24 is not None:
        try:
            loss, ref_from = float(ch_h24) / 100.0, "dexscreener 24 h"
            ref = px / (1 + loss) if px and loss > -1 else None
        except (TypeError, ValueError):
            loss = None
    if loss is None and px and cs and span_h >= REF_MIN_H:
        back = [c for c in cs if c[0] <= now - 24 * 3600] or [cs[0]]
        ref = back[-1][4]
        loss, ref_from = px / ref - 1, "serija 24 h"
    trough = None
    if ref:
        lows = [min(c[1], c[4]) for c in cs if c[0] >= now - 24 * 3600]
        if lows:
            trough = min(lows) / ref - 1
    fl = (res.get("flip") or {}).get("state")
    in_range = bool(res.get("active")) and res.get("status") == "aktivan" and fl not in BLOCKED_FLIP
    out = {"ok": False, "age_h": round(age, 1), "age_known": age_known, "loss_24h": round(loss, 4) if loss is not None
           else None, "trough_24h": round(trough, 4) if trough is not None else None, "ref_from": ref_from,
           "in_range": in_range, "crashed": loss is not None and loss < -MAX_LOSS}
    # unknown age: a series that fills the 24 h window (from REF_MIN_H back) means the token traded before it
    old_enough = age >= AGE_MIN_H or (not age_known and span_h >= REF_MIN_H)
    if not old_enough:
        out["why"] = (f"premlad za pad: star {_age_txt(age)} (treba {AGE_MIN_H:.0f} h)" if age_known else
                      f"starost nepoznata, podaci tek {span_h:.0f} h (treba {AGE_MIN_H:.0f} h)")
    elif loss is None:
        out["why"] = "razina prije pada nepoznata (nema promjene 24 h ni serije od 22 h)"
    elif loss < -MAX_LOSS:
        out["why"] = f"nije preživio pad: MC {_pct(loss)} od prije 24 h (granica {_pct(-MAX_LOSS)})"
    elif not in_range:
        why = ("u pauzi nakon proboja dolje" if fl == "paused" else "kandidat za flip nakon proboja gore"
               if fl == "flip_candidate" else (res.get("why") or res.get("status") or "nema aktivnog raspona"))
        out["why"] = f"preživio pad, ali nije u rasponu ({why})"
    else:
        out["ok"] = True
        out["why"] = (f"preživio pad: star {_age_txt(age)}, MC {_pct(loss)} od prije 24 h"
                      + (f" (najdublje {_pct(trough)})" if trough is not None else "") + ", opet u rasponu")
    return out
