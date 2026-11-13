#!/usr/bin/env python3
"""range_dca's data job (rangedca/, flag range_dca, 10.11. Jure). One short process a minute (start.sh), so it holds no
memory between passes; flag off: it reads the flag and ends, nothing is fetched.

    python3 run_range.py once        poll + (every 5 min) detect; start.sh runs it every RANGE_EVERY_S (60 s)
    python3 run_range.py backtest [--days 14] [--gt N] [--force]   the backtest over the data we have (nightly)
    python3 run_range.py status      the computed ranges, best first

A pass: the candidates (rangedca/data.candidates), one DexScreener snapshot of those the hype scan does not snapshot
itself; every 5 minutes the range of every candidate from its minute series (detect.analyze), the exclusions
(rules.exclusions; for a token with an open range position also the transfer-holders check, rangedca/holders.py),
and at most 3 GeckoTerminal seeds for a candidate that meets the minimums but has < 6 h of history; between those
passes the active ranges get fresh 5-minute numbers (buys share, volume, change) every minute. Writes range.db only.

11.11. (Jure: "širi range watchlist + event tokeni"): while the flag range_market (G20) or event_tokens (G19) is on,
the same pass also runs the market watchlist (rangedca/market.py: up to RANGE_MARKET_MAX 400 bonded tokens of the
whole market and the event topics' tokens, 5 / 15-minute DexScreener snapshots inside per-source day caps) and
computes their ranges with the signal pass's (which keeps its 40 tokens and its rules unchanged). Every range carries
its source (signal > event > missed > market; 11.11. flag range_missed G27: the skipped tokens labelled propušteno,
rangedca/missed.py, for 72 h). A market / event / missed token gets a GeckoTerminal seed only when it is close to an
entry (an active range in the bottom 40 % without minute candles, or 2 h+ of snapshots that already show a range
with the price in the bottom 30 %), inside RANGE_GT_DAY and RANGE_MKT_SEED_DAY. range_dca off with both of them on:
only the market watchlist's data is collected (nothing trades).

11.11. (Jure: "rangedca flip / pauza / stop", flag range_flip G26): while it is not off, every full detection also
computes the token's flip / pause state (rangedca/detect.flip_step: a confirmed break up makes the old top the
candidate for the new bottom, a confirmed break down pauses the token with the old bottom as resistance, the
volatility stop range_low_low - 1.5 x ATR), keeps it in range.db range_flip and in the range JSON ("flip", plus
zones.mc.stop / stop_flip / flip_low / flip_top / resistance_low / resistance_top), and logs every change of state
(range.db events kind range_flip). Off: nothing of it is computed or written. Today's range, its status and `active`
never change for it; only the trader's new rules (rangedca/rules.new_range) read the state.

11.11. (the owner's decision 1, "range stopovi"): every full detection also keeps the range's ATR (detect.atr, 14 x 15
min, whatever range_flip's mode) and "stop" (stop_block: the ATR stop every account trades, the old x 0.85 next to it,
in price and market cap), and logs ONE line per active range when a level moved (3 significant digits): "range stop
SYM: pravi račun ATR MC $X (range_low_low $Y, ATR $Z) · demo ATR+reclaim · staro 0,85 $W" (rules.stop_line).

12.11. popodne (owner, točka 1: the range compute and the 5-minute numbers late or skipped; 13:34 deploy #156): start.sh
runs the first pass RANGE_FIRST_S (30 s, was 270 s) after a start and the next ones every RANGE_EVERY_S counted from
the START of a pass (was 60 s after its end, so the period drifted to 60 s + the pass); a pass more than GAP_S after
the last one logs the gap and catches up at once (the full detection is due whenever last_detect is DETECT_EVERY_S
old). A failing fetch (502, overload, timeout) or one token's error costs that snapshot / that token, never the pass:
the market part falls back to the watched list, the detection commits every COMMIT_EVERY tokens. The readiness and
trade-gate freshness limits are rangedca/trade's (METRICS_READY_S 9 min, METRICS_FRESH_S 5 min).
12.11. popodne (točka 4): tokens in the rug archive (rugfilter/archive) are not polled, get no range and leave the
market list (rangedca/market.drop_archived); a token with an open range round keeps its numbers for its exits.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DETECT_EVERY_S = 290   # "recomputed every 5 min" (a pass a minute; 10 s of slack for the pass's own run time)
PRUNE_EVERY_S = 3600
# 12.11. popodne (owner, točka 1): a pass that comes more than GAP_S after the last one (a deploy / restart, a stuck
# pass) says so in the log; the first pass after a gap catches up at once (the full detection when last_detect is
# DETECT_EVERY_S old, the 5-minute numbers of every active range in any case). COMMIT_EVERY: the detection writes
# range.db every this many tokens, so a pass killed by a deploy keeps what it computed (and a failing token, a 502 of
# one fetch, costs that token only)
GAP_S = 150
COMMIT_EVERY = 25


def _mode(name="range_dca"):
    try:
        from league import flags
        return flags.mode(name)
    except Exception:  # noqa: BLE001 - unreadable flag: off
        return "off"


def _minimums_met(snap):
    return bool(snap and snap.get("bonded", True) and (snap.get("mcap") or 0) >= 30_000 and (snap.get("liq") or 0) >= 20_000
                and (snap.get("vol_h1") or 0) >= 10_000)


def _near_entry(res, candles, snap, now, has_gt):
    """A market / event token close to an entry, worth a GeckoTerminal seed: an active range in the bottom 40 % still
    without minute candles, or (under 6 h of snapshots) 2 h+ of them already showing an active range with the price in
    the bottom 30 %."""
    from rangedca import detect
    if res.get("active"):
        return not has_gt and res.get("pos_pct") is not None and res["pos_pct"] <= 40
    if res.get("status") != "premalo podataka" or not candles or candles[-1][0] - candles[0][0] < 2 * 3600:
        return False
    proto = detect.analyze(candles, now, snap, {"min_hist_h": 2})
    return bool(proto.get("active") and proto.get("pos_pct") is not None and proto["pos_pct"] <= 30)


def once(now=None, log=print, fetch=None, gt_fetch=None, post=None, extra=(), net=None):
    """One pass. Returns a short summary text ("off" when range_dca, range_market, event_tokens and range_missed are
    all off). net: rangedca/market.Net stand-in (tests); fetch also serves the market pass when net is not given."""
    m_dca, m_mkt, m_evt = _mode(), _mode("range_market"), _mode("event_tokens")
    m_mis = _missed_mode()   # 11.11. (G27, rangedca/missed.py): the missed tokens on the list for 72 h
    if m_dca == "off" and m_mkt == "off" and m_evt == "off" and m_mis == "off":
        return "off"
    from rangedca import data, holders, market, rules
    now = int(now or time.time())
    m_flip = _flip_mode()
    n_flip = {}
    t0, t_mkt_s = time.monotonic(), 0.0   # 11.11.: the pass's duration in the log (stale 5-minute numbers)
    pinned = _pins()   # 11.11. (owner's pins, rangedca/owner.py): always first in the signal pass, never capped out
    con = data.connect()
    try:
        last_pass, last_detect = data.kv_get(con, "last_pass") or 0, data.kv_get(con, "last_detect") or 0
        full = now - last_detect >= DETECT_EVERY_S
        if last_pass and now - last_pass > GAP_S:   # 12.11.: a restart / deploy or a stuck pass: caught up now
            log(f"range: rupa od {now - last_pass} s od zadnjeg prolaza (restart, deploy ili spor prolaz): odmah "
                f"svježi 5-minutni podaci" + (f" i puni izračun raspona (zadnji prije {now - last_detect} s)" if full
                                              else ""))
        open_toks = set(data.open_round_tokens())
        # 12.11. popodne (owner, točka 4): the rug archive's tokens are not polled, get no range and never trade; a
        # token with an open range round keeps its numbers (its exits)
        arch = _archived() - open_toks
        sig = data.candidates(con, now, tuple(extra) + tuple(t for t in pinned if t not in extra)) if m_dca != "off" else []
        if arch and sig:
            gone = [t for t in sig if t in arch]
            sig = [t for t in sig if t not in arch]
            if gone and set(gone) != set(data.kv_get(con, "arch_skip") or []):
                data.kv_put(con, "arch_skip", sorted(gone))
                log(f"range: {len(gone)} tokena iz arhive rugova preskočeno (ne prati se, ne trguje, ne naoružava): "
                    + ", ".join(t[:6] for t in gone[:8]))
        pools = {r[0] for r in con.execute("SELECT token FROM pools")}
        pulse_all = data.pulse_recent(now)
        pulse = pulse_all - (set(sig) - pools)   # a token without a known pool is polled once for it
        got = data.poll(con, sig, now, fetch=fetch, pulse_fresh=pulse) if sig else {}
        if got and m_mkt != "off":   # 12.11. (owner, nalog 3): a liquid token under 30k keeps a 5-minute price there
            market.adopt(con, got, now)
        con.commit()
        srcs = {t: ["signal"] for t in sig}
        mk = {"tokens": [], "src": {}, "stats": {}}
        if m_mkt != "off" or m_evt != "off" or m_mis != "off":
            t_mkt = time.monotonic()
            try:
                mk = market.pass_once(con, now, net or market.Net(fetch), log, signal=sig, pulse=pulse_all,
                                      market_on=m_mkt != "off", event_on=m_evt != "off", open_toks=open_toks,
                                      missed_on=m_mis != "off", archived=arch)
            except Exception as e:  # noqa: BLE001 - 12.11. (točka 1): the watched tokens still get their numbers
                con.commit()   # what the market part already stored (snapshots) stays
                log(f"range tržište: prolaz nije uspio ({type(e).__name__}: {str(e)[:120]}), rasponi se računaju sa "
                    "spremljenim snimkama")
                mk = _watched_fallback(con, arch)
            t_mkt_s = time.monotonic() - t_mkt
            for t in mk["tokens"]:
                srcs.setdefault(t, []).append(mk["src"].get(t, "market"))
        cands = sig + [t for t in mk["tokens"] if t not in set(sig) and t not in arch]
        seeds, n_act, n_ok, errs = 0, 0, 0, []
        for i, tok in enumerate(cands):
            if i and i % COMMIT_EVERY == 0:
                con.commit()   # 12.11.: a pass killed by a deploy keeps what it computed so far
            try:
                n_act, n_ok, seeds = _one_token(con, tok, now, full, open_toks, pinned, m_flip, n_flip, srcs, seeds,
                                                gt_fetch, post, log, n_act, n_ok)
            except Exception as e:  # noqa: BLE001 - 12.11. (točka 1): one token (a 502 of its fetch) never ends the pass
                errs.append(f"{tok[:6]} {type(e).__name__}")
        if errs:
            log(f"range: {len(errs)} tokena nije izračunato u ovom prolazu ({', '.join(errs[:5])}); ostali jesu")
        if full:
            data.kv_put(con, "last_detect", now)
        data.kv_put(con, "last_pass", now)
        if now - (data.kv_get(con, "last_prune") or 0) >= PRUNE_EVERY_S:
            data.prune(con, now)
            _prune_holders(con, now, open_toks)
            market.prune(con, now, keep_tokens=set(sig) | open_toks)
            data.kv_put(con, "last_prune", now)
        con.commit()
        ms = mk.get("stats") or {}
        text = (f"range: {len(cands)} kandidata (signal {len(sig)}, tržište "
                f"{len(mk['tokens']) - ms.get('events', 0) - ms.get('missed', 0)}, eventi {ms.get('events', 0)}, "
                f"propušteni {ms.get('missed', 0)}), aktivnih {n_act}, ocjena >= {rules.RULES['score_min']}: {n_ok}; "
                f"GeckoTerminal danas {data.day_used(con, 'gt_day', now)}/{data.GT_DAY}, Helius danas "
                f"{data.day_used(con, 'helius_day', now)}/{holders.CREDITS_DAY} kredita"
                + (f"; tržište: DexScreener danas {data.day_used(con, 'mkt_dex_day', now)}/{market.DEX_DAY}, osvježeno "
                   f"{ms.get('refreshed', 0)}, iz hype skena {ms.get('reused', 0)}, preskočeno zbog stropa "
                   f"{ms.get('dropped', 0)}, primljeno {ms.get('admitted', 0)}" if ms else "")
                + (f"; range_flip ({m_flip}): " + ", ".join(f"{k} {v}" for k, v in sorted(n_flip.items()))
                   if n_flip else "")
                + f"; prolaz {time.monotonic() - t0:.0f} s (tržište {t_mkt_s:.0f} s)")
        if full:
            log(text)
        return text
    finally:
        con.close()


def _one_token(con, tok, now, full, open_toks, pinned, m_flip, n_flip, srcs, seeds, gt_fetch, post, log, n_act, n_ok):
    """One token of a pass (12.11.: its own function, so a failure is that token's only): the full detection, or
    between the 5-minute detections the active range's fresh 5-minute numbers. Returns (n_act, n_ok, seeds)."""
    from rangedca import data, detect, holders, market, rules, view
    prev, st = data.load_range(con, tok)
    if not full and not (prev and (prev.get("active") or tok in open_toks or tok in pinned
                                   or (m_flip != "off" and _alt_active(prev)))):
        return n_act, n_ok, seeds
    candles, snap = data.series(con, tok, now)
    if not candles:
        return n_act, n_ok, seeds
    sym = (snap or {}).get("symbol") or (prev or {}).get("symbol")
    src, src_all = view.source_of(srcs.get(tok) or ["signal"])
    if full:
        res = detect.analyze(candles, now, snap)
        pool = (snap or {}).get("pool")
        if src == "signal":
            want = res["status"] == "premalo podataka" and _minimums_met(snap)
        else:   # 11.11.: a market / event token only close to an entry, inside its own day cap
            has_gt = con.execute("SELECT 1 FROM gt_candles WHERE token=?", (tok,)).fetchone() is not None
            want = (data.day_used(con, "mkt_seed_day", now) < market.SEED_DAY and _minimums_met(snap)
                    and _near_entry(res, candles, snap, now, has_gt))
        if want and seeds < data.GT_PER_PASS and pool:
            if data.seed(con, tok, pool, now, fetch=gt_fetch):
                seeds += 1
                if src != "signal":
                    data.day_add(con, "mkt_seed_day", 1, now)
                candles, snap = data.series(con, tok, now)
                res = detect.analyze(candles, now, snap)
        # 11.11. (the owner's decision 1): the ATR of every range, whatever range_flip's mode: the hard stop of
        # every account is range_low_low - 1.5 x ATR (rangedca/rules.atr_range)
        res["atr"] = detect.atr(candles, now)
        if m_flip != "off":   # 11.11. (range_flip G26): the flip / pause state next to today's range
            fprev = data.flip_load(con, tok)
            fst = detect.flip_step(fprev, res, candles, now, snap)
            data.flip_save(con, tok, fst)
            _flip_into(res, fst)
            n_flip[fst["state"]] = n_flip.get(fst["state"], 0) + 1
            if ((fprev or {}).get("state") or "normal") != fst["state"]:
                data.event(con, tok, "range_flip", f"{fst['state']}: {fst['why']}", now)
                log(f"range {sym or tok[:6]}: range_flip {fst['state']} ({fst['why']})")
        hw = None
        if tok in open_toks:
            hw = holders.check(con, tok, (snap or {}).get("pool"), (snap or {}).get("supply"), now, post)
        new_st = rules.exclusions(st, res, now, hw)
        res = rules.apply_exclusion(res, new_st, now)
        res["mts"] = now
        if (prev or {}).get("status") != res["status"] and (res["active"] or res["status"] == "isključen"):
            note = (f"raspon {res['zones']['mc']['range_low_low'] or 0:,.0f}-{res['zones']['mc']['range_high_top'] or 0:,.0f}, "
                    f"ocjena {res['score']:.2f}" if res["active"] else res["why"])
            data.event(con, tok, res["status"], note, now)
            log(f"range {sym or tok[:6]}: {res['status']} ({note})")
        res["stop"] = stop_block(res)
        if res.get("active"):   # 11.11. (decision 1): ONE line per active range, only when a level moved
            ln = rules.stop_line(sym or tok[:6], res)
            if ln:
                if ln != (prev or {}).get("stop_line"):
                    log(ln)
                res["stop_line"] = ln
        st = new_st
    else:   # between the 5-minute passes: the active range keeps its zones, its 5-minute numbers are renewed
        res = dict(prev)
        if m_flip == "off":
            res.pop("flip", None)
        cs = [c for c in candles if c[0] >= now - 6 * 3600]
        res["metrics"] = detect.metrics(cs, now, snap)
        px = res["metrics"].get("price")
        z = res.get("zones")
        if px and z and z["range_high_top"] > z["range_low_low"]:
            res["pos_pct"] = round((px - z["range_low_low"]) / (z["range_high_top"] - z["range_low_low"]) * 100, 1)
        res["mts"] = now
    if full and (res.get("active") or tok in pinned):   # 11.11.: the similarity's features (rangedca/owner)
        res["age_h"], res["holders"] = _age_h(con, tok, now), _holders(tok, now)
    if tok in pinned:   # 11.11.: the pin's "volume holds" rule (volume 1 h vs the median of 6 hourly volumes)
        res["pinned"] = True
        res["pin_vol"] = _pin_vol(candles, now, snap)
    res.pop("symbol", None)
    res.pop("state", None)
    res["source"], res["sources"] = src, src_all
    data.save_range(con, tok, res, st, sym)
    n_act += int(bool(res.get("active")))
    n_ok += int(bool(res.get("active")) and (res.get("score") or 0) >= rules.RULES["score_min"])
    return n_act, n_ok, seeds


def _archived():
    """12.11. popodne (owner, točka 4): the rug archive's tokens (rugfilter/archive.blocked, cached 5 min); empty when
    unreadable (then rangedca/trade's guards still refuse a rugged token at the entry)."""
    try:
        from rugfilter import archive
        return set(archive.blocked())
    except Exception:  # noqa: BLE001
        return set()


def _watched_fallback(con, arch=()):
    """The market part's answer when its pass failed (12.11.): the watched tokens as they stand, so their active
    ranges still get fresh 5-minute numbers from the snapshots range.db already holds."""
    try:
        rows = con.execute("SELECT token, src FROM mkt WHERE watched=1").fetchall()
    except Exception:  # noqa: BLE001 - no market table yet
        rows = []
    rows = [(t, s) for t, s in rows if t not in set(arch)]
    return {"tokens": [t for t, _s in rows], "src": {t: s or "market" for t, s in rows}, "stats": {}}


def _pins():
    """The owner's pinned tokens (trade settings range_pins, rangedca/owner.py); () when unreadable."""
    try:
        from rangedca import owner
        return tuple(owner.pin_tokens())
    except Exception:  # noqa: BLE001 - no pins readable: the pass as before
        return ()


def _pin_vol(candles, now, snap):
    try:
        from rangedca import owner
        return owner.vol_hold(candles, now, snap)
    except Exception:  # noqa: BLE001
        return None


def _age_h(con, tok, now):
    """The token's age in hours for the similarity (rangedca/owner.features): the market list's pool creation when
    known; else the GeckoTerminal seed's first candle when it starts after the requested start (the pool is younger
    than the request, so its first candle is its first trade); else None (unknown)."""
    try:
        r = con.execute("SELECT created_ts FROM mkt WHERE token=?", (tok,)).fetchone()
        if r and r[0]:
            return round((now - r[0]) / 3600, 2)
    except Exception:  # noqa: BLE001 - no market table
        pass
    r = con.execute("SELECT first_ts, fetched FROM gt_candles WHERE token=?", (tok,)).fetchone()
    if r and r[0] and r[1] and r[0] > r[1] - 998 * 60 + 1800:
        return round((now - r[0]) / 3600, 2)
    return None


def _holders(tok, now):
    """The newest holder count the hype scan stored for the token (hype.db token_pulse, last 24 h), None unknown."""
    from rangedca import data
    c = data._ro_file(data.hype_path())
    if c is None:
        return None
    try:
        r = c.execute("SELECT holders FROM token_pulse WHERE token=? AND ts>=? AND holders IS NOT NULL ORDER BY ts DESC "
                      "LIMIT 1", (tok, int(now - 86400))).fetchone()
        return int(r[0]) if r and r[0] else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        c.close()


def _flip_mode():
    """range_flip's mode (11.11., G26); "off" whenever it cannot be read."""
    try:
        return _mode("range_flip")
    except Exception:  # noqa: BLE001 - unreadable: off, today's rules
        return "off"


def _missed_mode():
    """range_missed's mode (11.11., G27); "off" whenever it cannot be read."""
    try:
        return _mode("range_missed")
    except Exception:  # noqa: BLE001 - unreadable: off, no missed list
        return "off"


def _alt_active(r):
    """True when the range's flip block (range_flip) has an active range after a break (flipped / resumed)."""
    fl = (r or {}).get("flip") or {}
    return fl.get("state") in ("flipped", "resumed") and bool((fl.get("alt") or {}).get("active"))


def stop_block(res):
    """11.11. (the owner's decision 1): the range JSON's "stop": the hard stop of every account (the ATR stop; x 0.85
    while ATR is unknown) and today's old x 0.85 next to it, in price and market cap (zonewatch's stop alarm, the MCP
    rows, proposals' range stop and ATR). None without zones."""
    from rangedca import rules
    sp = rules.stop_parts(res)
    if not sp:
        return None
    sup = (res.get("metrics") or {}).get("supply")

    def m(px):
        return round(px * sup) if sup and px else None
    return {"px": sp["stop_px"], "mc": m(sp["stop_px"]), "kind": sp["kind"], "atr_px": sp["atr_px"],
            "atr_mc": m(sp["atr_px"]), "old_mc": m(sp["old_px"]), "rule": "range_low_low - 1,5 × ATR (5-20 %)"
            if sp["kind"] == "atr" else "range_low_low × 0,85 (ATR nepoznat)"}


def _flip_into(res, fst):
    """The flip state into the range JSON: "flip" (detect.flip_public) and, for whoever reads the zones (zonewatch
    reads range.db), zones.flip_state and in zones.mc stop (today's range_low_low x 0.85), stop_flip (the stop of the
    range the new rules trade), flip_low / flip_top (the candidate zone) or resistance_low / resistance_top."""
    from rangedca import detect, rules
    supply = (res.get("metrics") or {}).get("supply")
    res["flip"] = detect.flip_public(fst, supply)
    z = res.get("zones")
    if not z:
        return
    mc = z.setdefault("mc", {})

    def m(px):
        return round(px * supply) if supply and px else None
    z["flip_state"] = fst["state"]
    mc["stop"] = m(z["range_low_low"] * rules.RULES["stop_x"])
    mc["stop_flip"] = m(fst.get("stop_px"))
    zone = fst.get("zone") or {}
    pre = "flip" if fst["state"] in ("flip_candidate", "flipped") else "resistance" if zone else None
    if pre:
        mc[f"{pre}_low"], mc[f"{pre}_top"] = m(zone.get("low")), m(zone.get("top"))


def _prune_holders(con, now, open_toks):
    from rangedca import data, holders
    con.execute(holders.SCHEMA)
    for (k,) in con.execute("SELECT k FROM kv WHERE k LIKE 'hold:%'").fetchall():
        tok = k[5:]
        st = data.kv_get(con, k) or {}
        if tok not in open_toks and now - (st.get("checked") or 0) > 3 * 86400:
            con.execute("DELETE FROM holder_ledger WHERE token=?", (tok,))
            con.execute("DELETE FROM kv WHERE k=?", (k,))


def status(log=print):
    from rangedca import data, market
    con = data.ro()
    if con is not None:
        try:
            cost = market.cost_today(con, time.time())
            log("trošak danas: " + ", ".join(f"{k} {v['used']}" + (f"/{v['cap']}" if v["cap"] else "") for k, v in cost.items()))
            log(f"tržišna lista: {market.counts(con)}")
        except Exception:  # noqa: BLE001 - no market table yet
            pass
        finally:
            con.close()
    rs = data.read_ranges()
    for tok, r in sorted(rs.items(), key=lambda kv: (-(kv[1].get("active") or 0), -(kv[1].get("score") or 0))):
        z = (r.get("zones") or {}).get("mc") or {}
        log(f"{r.get('symbol') or tok[:6]:10} {r['status']:16} ocjena {r.get('score') or 0:.2f} pozicija "
            f"{r.get('pos_pct') if r.get('pos_pct') is not None else '-'} % dno {z.get('range_low_low') or 0:,.0f}-"
            f"{z.get('range_low_top') or 0:,.0f} vrh {z.get('range_high_low') or 0:,.0f}-{z.get('range_high_top') or 0:,.0f}")
    return rs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    b = sub.add_parser("backtest")
    b.add_argument("--days", type=int, default=14)
    b.add_argument("--gt", type=int, default=int(os.environ.get("RANGE_BT_GT", "30")),
                   help="GeckoTerminal requests for history at most (inside the range day cap)")
    b.add_argument("--force", action="store_true", help="also while the flag is off")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "once":
        once()
    elif a.cmd == "backtest":
        if _mode() == "off" and not a.force:
            print("range backtest: zastavica range_dca je isključena, ništa se ne radi", flush=True)
            return 0
        from rangedca import backtest
        backtest.run_server(days=a.days, gt=a.gt)
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
