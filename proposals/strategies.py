"""The seven proposal sources, each with its own entry, exit, measured record and expiry (pure functions over one
ui/kandidati row and the pass's context; proposals/build.py merges them).

  range       rangedca's get_range_candidates rows with entry_ready (price in the bottom zone / bottom 15 %), volume 1 h
              >= $3k (11.11. owner's rule B: under $10k the size shrinks, trade/cost.vol_factor), buys >= 50 % of
              5 min, range_score >= 0.7. Exit: half at range_high_low, the rest at
              range_high_top or a 10 % trailing above it, stop range_low_low x 0.85, 6 h time stop at break-even; lot 2
              (DCA) at -10..-15 %. Record: the demo account's closed range rounds (wins of n). Valid 2 h from the
              proposal, or until the price leaves the bottom zone (it drops out of entry_ready). The token's tier
              (rangedca.tier.view of the tier work, guarded: None while it is not here) is shown as its reason line
              and, for a range proposal, its size_sol is the recommended stake (never above 0.15 SOL or the caps).
  momentum    momentum_scalp signals of the last 15 min (every entry rule met). Exit: half at +15 %, the rest on an 8 %
              trailing stop, stop -10 %, out after 45 min. Record: the base rate of every signal (+15 % before -10 %
              within 45 min, 30 days). Entry only up to 5 % above the signal's market cap. Valid 15 min from the signal.
  influencer  callers of the last hour with a measured quick-exit record: n >= 10 calls (11.11., owner's rule D; the
              shrink toward no edge stays) and EV > 0 on the SAME benchmark as the exit: +15 % before -10 % within
              45 min after the cost model's fee part (kol/tpsl over minute.db, cached nightly in proposals.db bench).
              Paid shillers and shill-network members never count (their call is exit liquidity). Entry only while the
              market cap is under 1.5x the first call's (run-up < 50 %). Exit: the signal exit (trade/edge, rule E):
              half at +15 %, trailing 8 %, stop -10 %, out after 45 min. Record: the qualifying callers' benchmark hits
              of n, pooled. Valid 30 min from the newest qualifying call.
  group       a quality wallet group (hidden_group) or a quality caller crew with n >= 8 measured events (kol/groupdisc),
              or a pre_shill signal (kol/preshill). Exit: the signal exit (rule E, as influencer). Record: early.db
              group_signals hit4h per kind, preshill_signals hit4h; NOTE: those are still measured as +20 % before
              -30 % in 4 h (kol/groupdisc / kol/preshill), not on the +15 / -10 / 45 min benchmark. Valid 60 min.
  insider     confirmed pre-call insiders (kol/precall copy_set) among the 2+ insider wallets that bought within the
              hour, nobody called yet. Exit: the signal exit (rule E). Record: the demo account's closed insider copies
              (ret > 0 of n). Valid 60 min.
  event       the canonical ("main") token of an event in the next 7 days (topics.view.proposal_rows of the event
              work; nothing while that module is not merged). Exit +30 % half, trailing 15 %, stop -25 %, everything
              out EVENT_MARGIN_S before the event. Record: topics.view.record() when it exists, else none (the prior:
              EV 0, never shown). Valid until event_ts - 6 h.
  catalyst    a team catalyst (paid DexScreener profile, new socials or site, boost, an X post after silence) while the
              price is in the bottom 30 % of its range (catalyst.view.proposal_rows(now, hours=2) of the catalyst work,
              team_catalyst G22; guarded: nothing while that module is not here or fails). Exit as range: half at
              range_high_low, the rest at range_high_top / 10 % trailing, stop range_low_low x 0.85 (the token's range
              from range.db); without a known range +50 % half / trailing 15 % / stop -25 %. Record: the measured rate
              of +50 % within 4 h (catalyst.view.record) when it exists, else the prior (EV 0, never shown). Valid 2 h
              from the catalyst, or until the price leaves the bottom 30 % (it drops out of proposal_rows).
  grok        Grok's submit_signal_opinion with verdict kupi and p_tp (optional strategy, entry_zone, exit_zone,
              valid_min). p = Grok's p_tp CALIBRATED on its measured predictions (proposals/calib.py). Exit: Grok's
              exit_zone (tp_mcap, sl_mcap, trailing_pct), else +20 % / -20 %. Valid valid_min (default 60 min).

Evidence (one strategy on one token): {"strategy", "ts", "expires_ts" | "expires_after_s", "tp", "sl" (fractions
from the market cap now), "levels" (the exit: tp [{"pct" | "mc", "share"}], sl {"pct" | "mc"}, trail, time), "hits",
"n", "record_from" | "p_fixed", "entry_zone", "why", "detail", "invalid"}.
"""
import math

from trade import cost as _cost, edge as _edge

STRATEGIES = ("range", "momentum", "influencer", "group", "insider", "event", "catalyst", "grok")
HR = {"range": "raspon", "momentum": "momentum", "influencer": "influenceri", "group": "skupina", "insider": "insajderi",
      "event": "događaj", "catalyst": "katalizator", "grok": "Grok"}
INFLUENCER_MIN_N = _edge.N_MIN   # 11.11. (owner's rule D): 20 -> 10, with the shrink toward no edge
INFLUENCER_RUNUP_MAX = 1.5
GROUP_MIN_N = 8
RANGE_MIN_VOL_H1 = _cost.VOL_FLOOR   # 11.11. (rule B): the hard floor $3k; $3k-$10k shrinks the size
RANGE_MIN_BUY_SHARE = 0.5
RANGE_MIN_SCORE = 0.7
MOMENTUM_CHASE = 0.05
EXPIRY_S = {"momentum": 15 * 60, "range": 2 * 3600, "influencer": 30 * 60, "group": 3600, "insider": 3600,
            "catalyst": 2 * 3600, "grok": 3600}
CATALYST_HOURS = 2
CATALYST_KINDS = {"dex_profile": "plaćen DexScreener profil", "profile": "plaćen DexScreener profil",
                  "socials": "nove društvene mreže", "site": "nov web", "website": "nov web", "boost": "boost na DexScreeneru",
                  "x_post": "X objava nakon tišine", "x": "X objava nakon tišine"}
EVENT_MARGIN_S = 6 * 3600
EVENT_DAYS = 7


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _usd(x):
    if x is None:
        return "?"
    x = float(x)
    if x >= 1e6:
        return f"${x / 1e6:.2f}M".replace(".", ",")
    if x >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:.0f}"


def _pct_levels(tp_pct, sl_pct, half=True, trail=None, time_min=None, out_all=False):
    """Exit levels in percent from the entry: TP (half or all), stop, trailing {activate, trail}, time stop."""
    lv = {"tp": [{"pct": tp_pct, "share": 0.5 if half else 1.0}], "sl": {"pct": -sl_pct}, "trail": None, "time": None}
    if trail:
        lv["trail"] = {"activate_pct": tp_pct, "trail_pct": trail}
    if time_min:
        lv["time"] = {"after_min": time_min, "if_pnl_below_pct": 1000 if out_all else 0}
    return lv


# ---------- range ------------------------------------------------------------------------------------------------------

def range_ready(rc):
    """None when a get_range_candidates row is a range entry now, else why not. 11.11. (the owner's pin,
    rangedca/owner.py): a pinned token the normal rules do not take is a range entry when its pin rule passes (the
    price in the range's lower zone and the volume holds); the hard blocks still apply (proposals/build)."""
    if not rc:
        return "nema raspona"
    if rc.get("pinned") and not rc.get("entry_ready"):
        if not rc.get("pin_ready"):
            return f"vlasnikov pin: {rc.get('pin_entry') or 'čeka donju zonu raspona i volumen'}"
        if (_f((rc.get("now") or {}).get("volume_1h_usd")) or 0) < RANGE_MIN_VOL_H1:
            return f"volumen 1 h {_usd((rc.get('now') or {}).get('volume_1h_usd'))} ispod {_usd(RANGE_MIN_VOL_H1)}"
        return None
    if not rc.get("entry_ready"):
        return rc.get("entry_now") or "ulaz u raspon ne bi prošao"
    now_ = rc.get("now") or {}
    if (_f(rc.get("range_score")) or 0) < RANGE_MIN_SCORE - 1e-9:
        return f"ocjena raspona {rc.get('range_score')} ispod {RANGE_MIN_SCORE}"
    if (_f(now_.get("volume_1h_usd")) or 0) < RANGE_MIN_VOL_H1:
        return f"volumen 1 h {_usd(now_.get('volume_1h_usd'))} ispod {_usd(RANGE_MIN_VOL_H1)}"
    bs = _f(now_.get("buy_share_5m"))
    if bs is None or bs < RANGE_MIN_BUY_SHARE:
        return "kupnje ispod 50 % transakcija u 5 min"
    return None


def range_ev(rc, mcap, rec, now):
    z = ((rc or {}).get("zones") or {}).get("market_cap_usd") or {}
    rll, rlt, rhl, rht = (_f(z.get(k)) for k in ("range_low_low", "range_low_top", "range_high_low", "range_high_top"))
    if not (rll and rhl and rht and mcap):
        return None
    stop = rll * 0.85
    ev = {"strategy": "range", "ts": int((rc or {}).get("computed_ts") or now), "expires_after_s": EXPIRY_S["range"],
          "tp": rhl / mcap - 1, "sl": 1 - stop / mcap, "hits": (rec or {}).get("wins") or 0, "n": (rec or {}).get("n") or 0,
          "record_from": "zatvorene paper runde raspona (dobitne od svih)",
          "entry_zone": {"mcap_low": round(rll), "mcap_high": round(rlt or rll)},
          "levels": {"tp": [{"mc": round(rhl), "share": 0.5}, {"mc": round(rht), "share": 0.5}], "sl": {"mc": round(stop)},
                     "trail": {"activate_pct": round((rht / mcap - 1) * 100, 1), "trail_pct": 10},
                     "time": {"after_min": 360, "if_pnl_below_pct": 0}},
          "dca": "lot 2 na -10 do -15 % od prvog ulaza (iznad range_low_low × 0,92), najviše 2 lota",
          "why": (f"Cijena je u donjoj zoni raspona koji se drži (ocjena {_f(rc.get('range_score')) or 0:.2f}), a "
                  f"zadnjih 5 minuta prevladavaju kupnje. Cilj je gornja zona oko {_usd(rhl)}."),
          "detail": {"range_score": rc.get("range_score"), "position_in_range_pct": rc.get("position_in_range_pct"),
                     "zones_mc": {k: z.get(k) for k in ("range_low_low", "range_low_top", "range_high_low",
                                                         "range_high_top")}},
          "invalid": None}
    if rc.get("pinned") and not rc.get("entry_ready"):   # 11.11.: the owner's pin made it (rangedca/owner.pin_check)
        vol = ((rc.get("pin") or {}).get("volume") or {})
        ev["why"] = (f"Vlasnikov pin: cijena je opet u donjoj zoni raspona ({_usd(rll)}-{_usd(rlt or rll)}) i volumen "
                     f"se drži (1 h {_usd(vol.get('vol_h1'))}, medijan 6 h {_usd(vol.get('vol_h1_med6'))}). Cilj je "
                     f"gornja zona oko {_usd(rhl)}.")
        ev["detail"]["pinned"] = True
        ev["detail"]["pin_notes"] = (rc.get("pin") or {}).get("notes") or []
    why = range_ready(rc)
    if why:
        ev["invalid"] = why
    elif ev["tp"] <= 0:
        ev["invalid"] = "cijena je već u gornjoj zoni raspona"
    return ev


# ---------- momentum ---------------------------------------------------------------------------------------------------

def momentum_ev(src, mcap, rec, now):
    if not src:
        return None
    mc0 = _f(src.get("mcap_usd")) or mcap
    ts = int(src.get("ts") or now)
    ev = {"strategy": "momentum", "ts": ts, "expires_ts": ts + EXPIRY_S["momentum"], "tp": 0.15, "sl": 0.10,
          "hits": (rec or {}).get("hits") or 0, "n": (rec or {}).get("n") or 0,
          "record_from": "svi momentum signali 30 dana (+15 % prije -10 % u 45 min)",
          "entry_zone": {"mcap_low": round(mc0), "mcap_high": round(mc0 * (1 + MOMENTUM_CHASE))},
          "levels": _pct_levels(15, 10, half=True, trail=8, time_min=45, out_all=True),
          "why": (f"Token je upravo krenuo: {_f(src.get('change_5m_pct')) or 0:+.0f} % u 5 minuta uz "
                  f"{_f(src.get('volume_x')) or 0:.0f}x uobičajeni volumen i većinom kupnje."),
          "detail": {k: src.get(k) for k in ("signal_id", "change_5m_pct", "volume_x", "buy_share_5m",
                                             "unique_buyers_5m", "mcap_usd")},
          "invalid": None}
    if mcap and mc0 and mcap > mc0 * (1 + MOMENTUM_CHASE):
        ev["invalid"] = f"cijena je već {mcap / mc0 - 1:+.0%} od signala (najviše +5 %)"
    if now >= ev["expires_ts"]:
        ev["invalid"] = "signal je stariji od 15 min"
    return ev


# ---------- influencer -------------------------------------------------------------------------------------------------

def bench_of(bench, who):
    b = (bench or {}).get(who)
    if b is None and isinstance(who, str):
        b = (bench or {}).get(who.lower())
    return b


def qualifies(b):
    """A caller's quick-exit benchmark (+15 % before -10 % within 45 min) is good enough: n >= 10 and EV > 0 after
    cost."""
    return bool(b) and (b.get("n") or 0) >= INFLUENCER_MIN_N and (b.get("ev_pct") or 0) > 0


def influencer_ev(cal, mcap, bench, first_call, shill, now):
    """cal: the kandidati row's caller evidence; shill: handles that never count (paid shillers, shill network)."""
    if not cal:
        return None
    shill = {str(h).lower() for h in shill or ()}
    good = []
    for c in cal.get("callers") or []:
        who = c.get("who")
        if not who or str(who).lower() in shill:
            continue
        b = bench_of(bench, who)
        if qualifies(b):
            good.append((c, b))
    if not good:
        return None
    hits = sum(int(b.get("hits") or 0) for _c, b in good)
    n = sum(int(b.get("n") or 0) for _c, b in good)
    last = max(int(c.get("ts") or now) for c, _b in good)
    first_mc = _f((first_call or (None, None))[1])
    names = ", ".join("@" + str(c["who"]).replace("tg:", "") for c, _b in good[:3])
    best = max(good, key=lambda x: x[1].get("ev_pct") or 0)[1]
    ev = {"strategy": "influencer", "ts": last, "expires_ts": last + EXPIRY_S["influencer"], "tp": _edge.TP, "sl": _edge.SL,
          "hits": hits, "n": n, "record_from": "brzi izlaz callera: +15 % prije -10 % u 45 min (minute.db, 30 dana)",
          "entry_zone": ({"mcap_low": round(min(mcap, first_mc)), "mcap_high": round(first_mc * INFLUENCER_RUNUP_MAX)}
                         if first_mc and mcap else None),
          "levels": _edge.signal_exit_levels(),
          "why": (f"{names} {'ga je zvao' if len(good) == 1 else 'su ga zvali'} prije "
                  f"{max(0, (now - last) // 60):.0f} min; u zadnjih 30 dana {'njegovi' if len(good) == 1 else 'njihovi'} "
                  f"pozivi češće donesu +15 % prije -10 % u 45 min nego obrnuto (najbolji: {best.get('hits')} od "
                  f"{best.get('n')})."),
          "detail": {"callers": [{"who": c["who"], "ts": c.get("ts"), "bench": {k: b.get(k) for k in ("n", "hits",
                                                                                                     "ev_pct")}}
                                 for c, b in good[:8]],
                     "first_call_mcap": first_mc},
          "handles": [c["who"] for c, _b in good], "calls": [(int(c.get("ts") or now), c["who"]) for c, _b in good],
          "invalid": None}
    if first_mc and mcap and mcap >= first_mc * INFLUENCER_RUNUP_MAX:
        ev["invalid"] = f"već {mcap / first_mc - 1:+.0%} od prvog poziva (granica +50 %)"
    if now >= ev["expires_ts"]:
        ev["invalid"] = "poziv je stariji od 30 min"
    return ev


# ---------- group ------------------------------------------------------------------------------------------------------

def _rec_hits(rec, key="hit4h"):
    """(hits, n) of a kandidati source record (hit rate x n)."""
    if not rec or not rec.get("n"):
        return 0, 0
    n = int(rec["n"])
    return int(round((rec.get(key) or 0) * n)), n


def group_ev(srcs, glist, records, preshill_rec, mcap, now):
    parts, hits, n, ts, handles = [], 0, 0, [], []
    hg = srcs.get("hidden_group")
    if hg and hg.get("grade") == "quality" and (hg.get("n_measured") or 0) >= GROUP_MIN_N:
        h, k = _rec_hits((records or {}).get("hidden_group"))
        hits, n = hits + h, n + k
        parts.append(f"kvalitetna skupina novčanika (n={hg.get('n_measured')}) kupila ga je bez javnog poziva")
        ts.append(int(hg.get("ts") or now))
    cal = srcs.get("caller") or {}
    crews = [c for c in cal.get("crews") or [] if c.get("grade") == "quality" and (c.get("n_measured") or 0) >= GROUP_MIN_N
             and not c.get("shill_network")]
    cf = cal.get("crew_first")
    if cf:
        kind, grade, _m, met = (glist or {}).get(cf.get("group_id"), ("caller", None, [], {}))
        try:
            from kol import groupdisc
            nm = groupdisc.n_measured_of(kind, met)
        except Exception:  # noqa: BLE001
            nm = (met or {}).get("n_measured")
        if grade == "quality" and (nm or 0) >= GROUP_MIN_N and not any(c.get("group_id") == cf.get("group_id")
                                                                        for c in crews):
            crews.append({"group_id": cf.get("group_id"), "handles": [cf.get("who")], "grade": grade, "n_measured": nm})
    if crews:
        h, k = _rec_hits((records or {}).get("caller_group_first"))
        hits, n = hits + h, n + k
        parts.append(f"kvalitetna ekipa callera (n={crews[0].get('n_measured')}) ga je zvala prva")
        ts.append(int(cal.get("first_ts") or now))
        for c in crews:
            handles += [h for h in c.get("handles") or [] if h]
    ps = srcs.get("pre_shill")
    if ps:
        hits, n = hits + int((preshill_rec or {}).get("hits") or 0), n + int((preshill_rec or {}).get("n") or 0)
        parts.append("novčanici koji kupuju prije plaćene shill mreže upravo su ga kupili")
        ts.append(int(ps.get("ts") or now))
    if not parts:
        return None
    t = max(ts)
    sig_mc = _f((hg or {}).get("mcap_usd")) or _f((ps or {}).get("mcap_usd")) or mcap
    return {"strategy": "group", "ts": t, "expires_ts": t + EXPIRY_S["group"], "tp": _edge.TP, "sl": _edge.SL,
            "hits": hits, "n": n,
            "record_from": ("signali skupina: +20 % prije -30 % u 4 h (early.db, preshill; staro mjerilo, izlaz je "
                            "+15/-10/45 min)"),
            "entry_zone": {"mcap_low": round(mcap * 0.9), "mcap_high": round(max(mcap, sig_mc or mcap) * 1.5)} if mcap else None,
            "levels": _edge.signal_exit_levels(),
            "why": parts[0][0].upper() + parts[0][1:] + "." + (f" Uz to: {parts[1]}." if len(parts) > 1 else ""),
            "detail": {"hidden_group": hg, "crews": crews[:3], "pre_shill": ps}, "crew_handles": handles,
            "invalid": None if now < t + EXPIRY_S["group"] else "signal skupine stariji od 60 min"}


# ---------- insider ----------------------------------------------------------------------------------------------------

def insider_ev(src, confirmed, rec, mcap, now):
    if not src:
        return None
    ws = [w for w in src.get("wallets") or [] if w in (confirmed or ())]
    if not ws:
        return None
    t = int(src.get("ts") or now)
    sig_mc = _f(src.get("mcap_usd")) or mcap
    return {"strategy": "insider", "ts": t, "expires_ts": t + EXPIRY_S["insider"], "tp": _edge.TP, "sl": _edge.SL,
            "hits": (rec or {}).get("hits") or 0, "n": (rec or {}).get("n") or 0,
            "record_from": "zatvorene demo kopije insajdera (dobitne od svih)",
            "entry_zone": {"mcap_low": round(mcap * 0.9), "mcap_high": round(max(mcap, sig_mc) * 1.5)} if mcap else None,
            "levels": _edge.signal_exit_levels(),
            "why": (f"{len(ws)} potvrđen{'' if len(ws) == 1 else 'a'} novčanik{'' if len(ws) == 1 else 'a'} koji inače kupuje "
                    "prije poziva callera upravo ga je kupio, a nitko ga još nije zvao."),
            "detail": {"wallets": ws[:8]}, "invalid": None if now < t + EXPIRY_S["insider"] else "kupnja starija od 60 min"}


# ---------- event ------------------------------------------------------------------------------------------------------

def event_ev(er, mcap, rec, now):
    if not er or (er.get("role") or "main") != "main":
        return None
    ets = int(er.get("event_ts") or 0)
    exp = ets - EVENT_MARGIN_S
    days = max(0.0, (ets - now) / 86400)
    out_min = max(1, int((exp - now) / 60))
    lv = _pct_levels(30, 25, half=True, trail=15)
    lv["time"] = {"after_min": min(out_min, 7 * 1440), "if_pnl_below_pct": 1000}
    ev = {"strategy": "event", "ts": int(now), "expires_ts": exp, "tp": 0.30, "sl": 0.25,
          "hits": (rec or {}).get("hits") or 0, "n": (rec or {}).get("n") or 0,
          "record_from": (rec or {}).get("from") or "nema izmjerenih događaja (prior: bez prednosti)",
          "entry_zone": {"mcap_low": round(mcap * 0.85), "mcap_high": round(mcap * 1.1)} if mcap else None,
          "levels": lv,
          "why": (f"Glavni token događaja „{er.get('topic') or '?'}” za {days:.0f} "
                  f"{'dan' if round(days) == 1 else 'dana'}; izlaz najkasnije 6 h prije događaja."),
          "detail": {k: er.get(k) for k in ("topic", "topic_id", "event_ts", "role")}, "invalid": None}
    if exp <= now:
        ev["invalid"] = "događaj je za manje od 6 h"
    elif ets - now > EVENT_DAYS * 86400:
        ev["invalid"] = "događaj je za više od 7 dana"
    return ev


# ---------- catalyst ---------------------------------------------------------------------------------------------------

def catalyst_ev(cr, zones, mcap, rec, now):
    """cr: a catalyst.view.proposal_rows row; zones: the token's range zones in market cap (range.db) or None."""
    if not cr:
        return None
    t = int(cr.get("ts") or now)
    kinds = [CATALYST_KINDS.get(str(k).lower(), str(k)) for k in cr.get("kinds") or []]
    z = zones or {}
    rll, rlt, rhl, rht = (_f(z.get(k)) for k in ("range_low_low", "range_low_top", "range_high_low", "range_high_top"))
    ev = {"strategy": "catalyst", "ts": t, "expires_ts": t + EXPIRY_S["catalyst"],
          "hits": (rec or {}).get("hits") or 0, "n": (rec or {}).get("n") or 0,
          "record_from": (rec or {}).get("from") or "izmjerena stopa +50 % u 4 h nakon katalizatora",
          "why": ((cr.get("why") or "").strip() or
                  f"Tim je upravo napravio korak ({', '.join(kinds) or 'katalizator'}), a cijena je još u donjih 30 % "
                  "raspona."),
          "detail": {"kinds": cr.get("kinds"), "pos_pct": cr.get("pos_pct"), "detail": cr.get("detail")},
          "invalid": None}
    if rll and rhl and rht and mcap:
        stop = rll * 0.85
        ev.update(tp=rhl / mcap - 1, sl=1 - stop / mcap,
                  entry_zone={"mcap_low": round(rll), "mcap_high": round(rll + 0.3 * (rht - rll))},
                  levels={"tp": [{"mc": round(rhl), "share": 0.5}, {"mc": round(rht), "share": 0.5}],
                          "sl": {"mc": round(stop)},
                          "trail": {"activate_pct": round((rht / mcap - 1) * 100, 1), "trail_pct": 10},
                          "time": {"after_min": 360, "if_pnl_below_pct": 0}})
        if ev["tp"] <= 0:
            ev["invalid"] = "cijena je već u gornjoj zoni raspona"
        elif ev["sl"] <= 0:
            ev["invalid"] = "cijena je već ispod stopa raspona"
    else:
        ev.update(tp=0.50, sl=0.25,
                  entry_zone={"mcap_low": round(mcap * 0.9), "mcap_high": round(mcap * 1.05)} if mcap else None,
                  levels=_pct_levels(50, 25, half=True, trail=15, time_min=240))
    pos = _f(cr.get("pos_pct"))
    if pos is not None and pos > 30:
        ev["invalid"] = f"cijena je na {pos:.0f} % raspona (katalizator vrijedi u donjih 30 %)"
    if now >= ev["expires_ts"]:
        ev["invalid"] = "katalizator je stariji od 2 h"
    return ev


# ---------- grok -------------------------------------------------------------------------------------------------------

def grok_ev(gp, mcap, model, now):
    """gp: {"ts", "proposal": {...}, "interpretation", "confidence"} of Grok's newest kupi with p_tp on the token."""
    from . import calib
    pr = (gp or {}).get("proposal") or {}
    if not gp or pr.get("p_tp") is None:
        return None
    raw = float(pr["p_tp"])
    p = calib.apply(model, raw)
    bn = calib.bucket_n(model, raw)
    ez, en = pr.get("exit_zone") or {}, pr.get("entry_zone") or {}
    tp_mc, sl_mc, tr = _f(ez.get("tp_mcap")), _f(ez.get("sl_mcap")), _f(ez.get("trailing_pct"))
    tp = (tp_mc / mcap - 1) if tp_mc and mcap else 0.20
    sl = (1 - sl_mc / mcap) if sl_mc and mcap else 0.20
    t = int(gp.get("ts") or now)
    valid = int(pr.get("valid_min") or 60) * 60
    lv = {"tp": [{"mc": round(tp_mc), "share": 0.5 if tr else 1.0}] if tp_mc else [{"pct": 20, "share": 0.5 if tr else 1.0}],
          "sl": {"mc": round(sl_mc)} if sl_mc else {"pct": -20},
          "trail": {"activate_pct": round(tp * 100, 1), "trail_pct": tr} if tr else None, "time": None}
    b = min(((model or {}).get("buckets") or [{}]), key=lambda x: abs((x.get("mean_p") or 0) - raw)) if bn else {}
    hr, nb = b.get("hit_rate"), b.get("n") or 0
    lo, hi = calib.wilson(int(round((hr or 0) * nb)), nb)
    note = (gp.get("interpretation") or "").strip().split(". ")[0][:160]
    ev = {"strategy": "grok", "ts": t, "expires_ts": t + valid, "tp": tp, "sl": sl,
          "p_fixed": {"p": p, "n": bn, "raw": raw, "ci90": [round(lo, 3), round(hi, 3)] if nb else [0.0, 1.0],
                      "from": "Grokov p_tp kalibriran na njegovim izmjerenim predviđanjima"},
          "entry_zone": en or ({"mcap_low": round(mcap * 0.95), "mcap_high": round(mcap * 1.05)} if mcap else None),
          "levels": lv, "why": "Grok predlaže kupnju" + (f": {note}." if note else "."),
          "detail": {"p_tp_grok": raw, "p_tp_calibrated": p, "strategy_named": pr.get("strategy"),
                     "confidence": gp.get("confidence"), "opinion_id": gp.get("id")},
          "invalid": None}
    if tp <= 0:
        ev["invalid"] = "cijena je već iznad Grokovog cilja"
    elif sl <= 0:
        ev["invalid"] = "cijena je već ispod Grokovog stopa"
    elif en and mcap and mcap > float(en.get("mcap_high") or 0) * 1.0001:
        ev["invalid"] = f"MC {_usd(mcap)} je iznad Grokove zone ulaza ({_usd(en.get('mcap_high'))})"
    elif now >= ev["expires_ts"]:
        ev["invalid"] = "Grokov prijedlog je istekao"
    return ev


# ---------- the exit in the formats the page and the trader need --------------------------------------------------------

def exit_plan(ev, reason=""):
    """The evidence's exit in set_exit_plan's format (league/exitplan.validate)."""
    lv = ev["levels"]
    tps = [({"at_mc_usd": t["mc"]} if "mc" in t else {"at_pct": t["pct"]}) | {"sell_share": t["share"]} for t in lv["tp"]]
    out = {"take_profits": tps, "stop": {"at_mc_usd": lv["sl"]["mc"]} if "mc" in lv["sl"] else {"at_pct": lv["sl"]["pct"]},
           "reason": (reason or f"prijedlog ({HR.get(ev['strategy'], ev['strategy'])})")[:300]}
    if lv.get("trail"):
        out["trailing"] = {"activate_pct": max(0.0, float(lv["trail"]["activate_pct"])),
                           "trail_pct": float(lv["trail"]["trail_pct"])}
    if lv.get("time"):
        out["time_stop"] = dict(lv["time"])
    return out


def mcaps(ev, mcap):
    """{"tp": [market caps], "sl", "trailing_pct", "time_min"}: the exit levels in market cap (from the market cap now
    for the percent levels)."""
    lv = ev["levels"]
    tp = [t["mc"] if "mc" in t else (round(mcap * (1 + t["pct"] / 100)) if mcap else None) for t in lv["tp"]]
    s = lv["sl"]
    sl = s["mc"] if "mc" in s else (round(mcap * (1 + s["pct"] / 100)) if mcap else None)
    return {"tp": tp, "tp_share": [t["share"] for t in lv["tp"]], "sl": sl,
            "trailing_pct": (lv.get("trail") or {}).get("trail_pct"), "time_min": (lv.get("time") or {}).get("after_min")}


def buy_form(ev):
    """(TP, SL) as the Brza kupnja form takes them (league/auto.parse_level): "$60k" market caps or "15%"."""
    lv = ev["levels"]
    t = lv["tp"][0]

    def mc(x):
        return f"${x / 1000:.1f}k".replace(".0k", "k") if x < 1e6 else f"${x / 1e6:.3f}m"
    tp = mc(t["mc"]) if "mc" in t else f"{t['pct']:g}%"
    s = lv["sl"]
    sl = mc(s["mc"]) if "mc" in s else f"{s['pct']:g}%"
    return tp, sl


def duration_min(ev):
    """The expected holding time of a proposal in minutes (11.11., owner's rule D: the ranking is EV per minute): the
    exit's time stop, else the strategy's validity (a Grok proposal without a time stop: its horizon, 4 h)."""
    t = (ev.get("levels") or {}).get("time") or {}
    if t.get("after_min"):
        return max(1.0, float(t["after_min"]))
    return 240.0


def hold_s(ev):
    """Seconds after which a paper position is sold at the market when neither level was touched (only for a time
    stop that takes everything out)."""
    t = ev["levels"].get("time")
    return int(t["after_min"] * 60) if t and t.get("if_pnl_below_pct", 0) >= 1000 else None


def fmt_pct(x):
    return f"{x * 100:+.1f} %".replace(".", ",") if x is not None and not math.isnan(x) else "-"


# ---------- waiting for the entry (11.11., the owner's rules after HAOBIBI) ----------------------------------------------
# A proposal (status novo) waits for its entry zone: the demo account enters only while the market cap is inside the
# zone and above the proposal's stop (proposals/paper.py), the view shows "čeka ulaz" / "u zoni". The stop rule: the
# price under the stop kills a proposal only when it fell there AFTER the proposal was computed (it was above the stop
# at creation, or it has been in its zone since); one made while the price was already under its stop waits for the
# zone (or its time expiry).

ZONE_BAND = 0.05   # a strategy without an entry zone: the proposal's market cap +- 5 % (see zone_of)
WAIT, IN_ZONE = "čeka ulaz", "u zoni"


def zone_of(row, mcap0=None):
    """(low, high) of a proposal's entry zone in market cap: its primary strategy's entry_zone (range / catalyst: the
    range's bottom zone; momentum: the signal's MC up to +5 %; influencer: up to 1.5x the first call; group / insider
    / event / grok: around the MC of the pass that last showed it). A strategy without one (influencer with no known
    first call): the proposal's market cap (the row's, else mcap0) +- ZONE_BAND. None without either."""
    row = row or {}
    ez = row.get("entry_zone") or {}
    lo, hi = _f(ez.get("mcap_low")), _f(ez.get("mcap_high"))
    if lo and hi and hi >= lo:
        return lo, hi
    mc = _f(row.get("mcap0")) or _f(mcap0) or _f((row.get("market") or {}).get("market_cap_usd"))
    return (mc * (1 - ZONE_BAND), mc * (1 + ZONE_BAND)) if mc else None


def stop_of(row):
    """The proposal's stop in market cap (exits_mcap sl: its MC level, or the percent stop from the MC of the pass
    that last showed it), None when unknown."""
    return _f(((row or {}).get("exits_mcap") or {}).get("sl"))


def below_stop(mcap, sl):
    """1 / 0 when the market cap is / is not under the stop, None when either is unknown."""
    mcap, sl = _f(mcap), _f(sl)
    return None if not mcap or not sl else int(mcap < sl)


def wait_check(p, mcap):
    """A waiting proposal p (a proposals.db row: "row", "mcap0", "below_sl_at_creation", "zone_seen_ts") at market
    cap mcap: {"state": IN_ZONE | WAIT, "zone": (low, high) | None, "sl", "dead": the stop rule's reason or None}.
    None without a market cap. IN_ZONE only inside the zone (inclusive) and above the stop."""
    mc = _f(mcap)
    if not mc:
        return None
    row = (p or {}).get("row") or {}
    z, sl = zone_of(row, p.get("mcap0")), stop_of(row)
    under = bool(sl and mc < sl)
    b0 = p.get("below_sl_at_creation")
    if b0 is None:   # a proposal made before the column existed: from its market cap at creation
        b0 = below_stop(p.get("mcap0"), sl)
    armed = b0 == 0 or bool(p.get("zone_seen_ts"))
    dead = (f"pao ispod SL-a: MC {_usd(mc)} pod stopom {_usd(sl)} nakon prijedloga" if under and armed else None)
    inside = bool(z and z[0] * (1 - 1e-9) <= mc <= z[1] * (1 + 1e-9) and (not sl or mc > sl))
    return {"state": IN_ZONE if inside else WAIT, "zone": z, "sl": sl, "dead": dead}


def zone_text(z):
    return f"{_usd(z[0])}–{_usd(z[1])}" if z else "?"
