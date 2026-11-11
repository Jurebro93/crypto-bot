"""The proposals pass (run_proposals.py once, every PROPOSALS_EVERY_S = 150 s from start.sh, low priority, a short
process) and the night step (run_proposals.py night, 01-06 Zagreb under ops.heavy --night).

once: flag off -> ends at once (nothing read or written). Otherwise:
  1. Grok's calibration (proposals/calib.py) refreshed every CALIB_EVERY_S from momentum.db and events.db (read-only)
  2. the merged list (proposals/build.py): rows shown and near misses
  3. sync with proposals.db: a new token -> a new proposal (status novo); a token already proposed -> updated (EV,
     sources, exits, expiry); a proposal past its expiry, or no longer shown (blocked, EV <= 0, its source gone: the
     reason is kept) -> isteklo. A token decided recently is not proposed again for COOLDOWN_S[status] unless a new
     strategy proposes it. Never on a pass whose market read failed (only the time expiry then). 11.11. (the owner's
     rules after HAOBIBI, sync's text): a proposal WAITS for its entry zone: no longer shown only because the price is
     outside the zone (a range's source drops out exactly then) it stays novo until expires_ts; the price under its
     stop expires it only when it fell there after the proposal was made ("pao ispod SL-a"). 11.11. (the owner's
     decision 4, proposals/publish.py): every row's EV is measured from the middle of its entry zone, and a row is
     stored PUBLISHED only while the pass's market cap is inside the zone and >= 1 x ATR above the stop, else with
     wait_why ("čeka zonu"); the demo account's 20-s loop (proposals/paper.py) decides it again until expires_ts.
  4. the near misses and the shown rows of the day per (token, strategy) into seen (the daily report's "it saw it /
     near miss / never saw")
  5. our own price points for the after-outcomes: the market caps this pass already read (free), and one DexScreener
     batch (free, at most DEX_TOKENS tokens, every DEX_EVERY_S, DEX_DAY a day) for proposals whose 4 h window is open
     and that the pass no longer reads
  6. after-outcomes (proposals/outcomes.py) of every proposal 1 h and 4 h after it was made: max gain, max drawdown,
     TP before SL, from the minute data we already keep (events.db ticks, minute.db call candles, range.db, hype.db
     token_pulse, momentum.db snapshots) plus those points
  7. 11.11.: report.zone_misses (the proposals of the last 48 h that went through their entry zone without a paper
     entry, and what would have happened) into kv every ZONE_EVERY_S (get_proposals report.zone_misses); its block in
     the log once, at the first pass after the deploy (kv zone_misses_logged)
night: the callers' quick-exit benchmark (kol/tpsl over minute.db, one call per token, 30 days) into proposals.db bench,
at most once a Zagreb day. 11.11. (owner's rule E): the SAME benchmark as the signal exit: +15 % before -10 % within
45 min (BENCH_TP / BENCH_SL / BENCH_MIN), after the cost model's fee part (kol/tpsl.COST = trade/cost.FEE_ROUND_TRIP). The pass computes it once only when the
table is still empty (the first run after a deploy), never per request.
"""
import datetime as dt
import os
import time
from zoneinfo import ZoneInfo

from . import build, calib, outcomes, store, strategies

FLAG = "proposals"
TZ = "Europe/Zagreb"
CALIB_EVERY_S = 1800
COOLDOWN_S = {"kupljeno": 24 * 3600, "odbijeno": 6 * 3600, "isteklo": 1800}
DEX_EVERY_S = 300
DEX_TOKENS = 30
DEX_DAY = int(os.environ.get("PROPOSALS_DEX_DAY", "300"))
NEAR_KEEP = 40
BENCH_DAYS = 30
BENCH_TP, BENCH_SL, BENCH_MIN = 15, 10, 45   # = trade/edge TP / SL / TIME_MIN (the signal exit, rule E)
BENCH_RULE = f"{BENCH_TP}/{BENCH_SL}/{BENCH_MIN}"   # a bench stored under another rule is computed again once


def mode(trade_db=None):
    try:
        from trade import settings
        if trade_db:
            return settings.flag(FLAG, path=trade_db)
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def day_of(ts):
    return dt.datetime.fromtimestamp(int(ts), ZoneInfo(TZ)).date().isoformat()


def _mc(x):
    try:
        return float(x) if x else None
    except (TypeError, ValueError):
        return None


def sync(con, rows, near, now, market_ok=True, prices=None):
    """proposals.db after this pass: {"new", "updated", "expired", "waiting"}.

    11.11. (the owner's rules after HAOBIBI) a proposal waits for its entry zone (strategies.wait_check):
      - the stop rule: the market cap under the proposal's stop expires it ("pao ispod SL-a") only when it fell there
        after the proposal was made (above the stop at creation, or seen in its zone since); one made while the price
        was already under its stop keeps waiting for the zone or its time expiry
      - a vanished source no longer expires it when the only reason is the price outside the zone: a range (or
        catalyst) source drops out exactly when the price leaves the bottom zone, which would end every wait. Not shown
        this pass with its market cap known (the near miss's, the pass's prices, the paper loop's last_mcap or the px
        points of the last PRICE_FRESH_S) and outside the zone: it keeps waiting until expires_ts. A hard block of the
        near miss (rug, liquidity, volume, under 30k, curve, fake pool, ...) still expires it; so does a vanished source
        or an EV <= 0 / an invalid strategy while the price IS in the zone (not a price reason). No market cap at all
        this pass: only the time rule decides (as with a failed market read).
    prices: {token: (price, mcap)} the pass read (build meta)."""
    act = store.active(con)
    shown = {r["token"] for r in rows}
    last = store.last_by_token(con, [r["token"] for r in rows if r["token"] not in act])
    nearby = {n["token"]: n for n in near}
    prices = prices or {}
    out = {"new": 0, "updated": 0, "expired": 0, "waiting": 0}
    seen = []
    for r in rows:
        p = act.get(r["token"])
        if p:
            r["expires_ts"] = build.expiry(r, p["created_ts"])
            if now >= r["expires_ts"]:
                out["expired"] += store.set_status(con, p["id"], "isteklo", "vrijeme je isteklo", now)
                continue
            chk = strategies.wait_check({**p, "row": r}, (r.get("market") or {}).get("market_cap_usd"))
            if chk and chk["dead"]:
                out["expired"] += store.set_status(con, p["id"], "isteklo", chk["dead"], now)
                continue
            store.update(con, p["id"], r, now)
            if chk:
                seen.append((p["id"], (r.get("market") or {}).get("market_cap_usd"), chk["state"] == strategies.IN_ZONE))
            out["updated"] += 1
            continue
        prev = last.get(r["token"])
        if prev and prev["status"] in COOLDOWN_S and now - (prev["status_ts"] or 0) < COOLDOWN_S[prev["status"]] \
                and not set(r["sources"]) - set(prev.get("sources") or []):
            continue
        pid = store.insert(con, r, now)
        mc = (r.get("market") or {}).get("market_cap_usd")
        chk = strategies.wait_check({"row": r, "mcap0": r.get("mcap0"),
                                     "below_sl_at_creation": strategies.below_stop(r.get("mcap0"), strategies.stop_of(r))},
                                    mc)
        if chk:
            seen.append((pid, mc, chk["state"] == strategies.IN_ZONE))
        out["new"] += 1
    gone = [t for t in act if t not in shown]
    px = store.last_px(con, gone, now - store.PRICE_FRESH_S) if gone and market_ok else {}
    for tok in gone:
        p = act[tok]
        if now >= (p["expires_ts"] or 0):
            out["expired"] += store.set_status(con, p["id"], "isteklo", "vrijeme je isteklo", now)
            continue
        if not market_ok:
            continue
        n = nearby.get(tok)
        if n and any(b.get("key") == "market" for b in n.get("blocks") or []):
            continue   # no market reading this pass (DexScreener answered nothing): only the time rule decides
        stored = max([(p.get("last_mcap_ts") or 0, _mc(p.get("last_mcap"))), px.get(tok) or (0, None)],
                     key=lambda x: x[0])   # the newer of the paper loop's read and the pass's own px points
        mc = _mc((n or {}).get("mcap")) or _mc((prices.get(tok) or (None, None))[1]) or \
            (_mc(stored[1]) if now - stored[0] <= store.PRICE_FRESH_S else None)
        chk = strategies.wait_check(p, mc)
        if chk:
            seen.append((p["id"], mc, chk["state"] == strategies.IN_ZONE))
        if chk and chk["dead"]:
            out["expired"] += store.set_status(con, p["id"], "isteklo", chk["dead"], now)
            continue
        if n and n.get("blocks"):
            out["expired"] += store.set_status(con, p["id"], "isteklo", "više ne vrijedi: " + n["why"], now)
            continue
        if (chk and chk["state"] != strategies.IN_ZONE) or (chk is None and n is None):
            out["waiting"] += 1   # outside the zone (or no price this pass): it waits until expires_ts
            continue
        why = ("više ne vrijedi: " + n["why"]) if n else "više ne vrijedi: izvor prijedloga je nestao"
        out["expired"] += store.set_status(con, p["id"], "isteklo", why, now)
    store.mark_seen(con, seen, now)
    return out


def record_seen(con, rows, near, now):
    """seen (day, token, strategy): first / last time, best EV, proposed or why not."""
    day = day_of(now)
    for r in rows:
        for k in r.get("sources") or []:
            _seen(con, day, r["token"], k, r.get("symbol"), now, (r["strategies"].get(k) or {}).get("ev_pct"), 1, None,
                  (r.get("market") or {}).get("market_cap_usd"))
        for k, v in (r.get("strategies") or {}).items():
            if k not in (r.get("sources") or []):
                _seen(con, day, r["token"], k, r.get("symbol"), now, v.get("ev_pct"), 0,
                      v.get("why_not") or f"EV {v.get('ev_pct')}", (r.get("market") or {}).get("market_cap_usd"))
    for n in near:
        for k in n.get("strategies") or []:
            d = (n.get("strategy_detail") or {}).get(k) or {}
            _seen(con, day, n["token"], k, n.get("symbol"), now, d.get("ev_pct"), 0,
                  n.get("why") if not d.get("why_not") or n.get("blocks") else d["why_not"], n.get("mcap"))


def _seen(con, day, tok, k, sym, now, ev, proposed, why, mcap):
    con.execute("INSERT INTO seen (day, token, strategy, symbol, first_ts, last_ts, best_ev, proposed, why, mcap) VALUES "
                "(?,?,?,?,?,?,?,?,?,?) ON CONFLICT (day, token, strategy) DO UPDATE SET last_ts=excluded.last_ts, "
                "symbol=COALESCE(excluded.symbol, symbol), best_ev=MAX(COALESCE(best_ev, -1e9), COALESCE(excluded.best_ev, "
                "-1e9)), proposed=MAX(proposed, excluded.proposed), why=COALESCE(excluded.why, why), "
                "mcap=COALESCE(excluded.mcap, mcap)",
                (day, tok, k, sym, int(now), int(now), ev, int(proposed), (why or None) and str(why)[:300], mcap))


def open_window_tokens(con, now):
    """Tokens of proposals whose 4 h after-window is still open."""
    return sorted({t for (t,) in con.execute("SELECT DISTINCT token FROM proposals WHERE after_done = 0 AND created_ts "
                                             ">= ?", (int(now) - outcomes.HORIZONS[-1][1] - outcomes.GRACE_S,))})


def store_prices(con, prices, tokens, now):
    n = 0
    for t in tokens:
        pm = prices.get(t)
        if pm and pm[0]:
            con.execute("INSERT OR IGNORE INTO px VALUES (?,?,?,?)", (t, int(now), float(pm[0]), pm[1]))
            n += 1
    return n


def dex_batch(con, tokens, now, fetch=None):
    """One DexScreener read (free) for open-window tokens the pass no longer reads; capped (DEX_TOKENS a request,
    every DEX_EVERY_S, DEX_DAY a Zagreb day). Returns the number of tokens priced."""
    if not tokens:
        return 0
    last = store.kv_get(con, "dex_last", 0) or 0
    day = day_of(now)
    used = store.kv_get(con, "dex_day", {}) or {}
    if now - last < DEX_EVERY_S or (used.get("day") == day and (used.get("n") or 0) >= DEX_DAY):
        return 0
    toks = tokens[:DEX_TOKENS]
    try:
        if fetch is None:
            from ui import prijedlog
            got = prijedlog.live_market(toks) or {}
        else:
            got = fetch(toks) or {}
    except Exception:  # noqa: BLE001 - DexScreener down: the outcome uses what the other stores have
        got = {}
    store.kv_put(con, "dex_last", int(now))
    store.kv_put(con, "dex_day", {"day": day, "n": (used.get("n") or 0) + 1 if used.get("day") == day else 1})
    return store_prices(con, {t: (v.get("price"), v.get("mcap")) for t, v in got.items()}, toks, now)


def refresh_calib(con, now, pairs_fn=None):
    """Grok's calibration model in kv grok_calib, every CALIB_EVERY_S."""
    last = store.kv_get(con, "grok_calib_ts", 0) or 0
    if now - last < CALIB_EVERY_S and store.kv_get(con, "grok_calib") is not None:
        return None
    model = calib.fit((pairs_fn or calib.pairs)(now))
    model["ts"] = int(now)
    store.kv_put(con, "grok_calib", model)
    store.kv_put(con, "grok_calib_ts", int(now))
    return model


def bench_rows(now=None, minute_path=None, days=BENCH_DAYS):
    """{handle: {"n", "hits", "sl_first", "ev_pct"}} of every caller's quick-exit benchmark (TP +15 % before SL -10 %
    within 45 min after kol/tpsl.COST, one call per token): kol/tpsl.rows + outcome, read-only on minute.db."""
    import sqlite3
    from kol import minute, tpsl
    p = minute_path or minute.db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return {}
    mcon = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    try:
        rws = tpsl.rows(mcon, None, days, now)
    finally:
        mcon.close()
    by = {}
    for r in rws:
        by.setdefault(r["handle"], []).append(r)
    out = {}
    for h, xs in by.items():
        k = {"tp": 0, "sl": 0, "time": 0}
        tot = 0.0
        for r in xs:
            kind, g = tpsl.outcome(r, BENCH_TP, BENCH_SL, BENCH_MIN)
            k[kind] += 1
            tot += g - tpsl.COST
        out[h] = {"n": len(xs), "hits": k["tp"], "sl_first": k["sl"], "ev_pct": round(tot / len(xs), 3)}
    return out


def save_bench(con, rows, now):
    con.execute("DELETE FROM bench")
    con.executemany("INSERT INTO bench VALUES (?,?,?,?,?,?)",
                    [(h, b["n"], b["hits"], b["sl_first"], b["ev_pct"], int(now)) for h, b in rows.items()])
    store.kv_put(con, "bench_day", day_of(now))
    store.kv_put(con, "bench_ts", int(now))
    store.kv_put(con, "bench_rule", BENCH_RULE)


ZONE_EVERY_S = 3600          # report.zone_misses refreshed in kv this often (get_proposals report.zone_misses)
ZONE_LOG_VER = "zona-1"      # the log block once (the first pass after the deploy that brought it), kv marker


def zone_report(con, now, log=print, econ=None, lcon=None):
    """report.zone_misses of the last 48 h into kv zone_misses every ZONE_EVERY_S; its block in the log once (kv
    zone_misses_logged). Never stops the pass."""
    logged = store.kv_get(con, "zone_misses_logged") == ZONE_LOG_VER
    old = store.kv_get(con, "zone_misses") or {}
    if logged and now - (old.get("ts") or 0) < ZONE_EVERY_S:
        return None
    try:
        from . import report
        rep = report.zone_misses(now, con=con, econ=econ, lcon=lcon)
    except Exception as e:  # noqa: BLE001 - a missing store or a bad row never stops the pass
        log(f"prijedlozi: prolasci kroz zonu nisu izmjereni ({type(e).__name__}: {e})")
        store.kv_put(con, "zone_misses", {**old, "ts": int(now)})
        con.commit()
        return None
    store.kv_put(con, "zone_misses", rep)
    if not logged:
        log("\n".join(report.zone_lines(rep)))   # ONE block in the Render log
        store.kv_put(con, "zone_misses_logged", ZONE_LOG_VER)
    con.commit()
    return rep


def night(now=None, path=None, log=print, minute_path=None, force=False):
    """The callers' benchmark, at most once a Zagreb day (ops.heavy --night)."""
    now = int(now or time.time())
    if mode() == "off" and not force:
        log("prijedlozi (noć): zastavica proposals je isključena, ništa se ne radi")
        return None
    con = store.connect(path)
    try:
        if store.kv_get(con, "bench_day") == day_of(now) and not force:
            return None
        t0 = time.time()
        rows = bench_rows(now, minute_path)
        save_bench(con, rows, now)
        store.prune(con, now)
        con.commit()
        from . import strategies
        good = sum(1 for b in rows.values() if strategies.qualifies(b))
        log(f"prijedlozi (noć): brzi izlaz (+15 / -10 % / 45 min) za {len(rows)} callera, "
            f"{sum(b['n'] for b in rows.values())} izmjerenih poziva, {good} s n >= {strategies.INFLUENCER_MIN_N} i "
            f"EV > 0 ({time.time() - t0:.1f} s)")
        return rows
    finally:
        con.close()


def once(now=None, src=None, path=None, log=print, dex_fetch=None, pairs_fn=None, econ=None):
    """One pass (see the module text). {"off": True} while the flag is off."""
    if mode() == "off":
        return {"off": True}
    now = int(now or time.time())
    con = store.connect(path)
    try:
        refresh_calib(con, now, pairs_fn)
        stale = store.kv_get(con, "bench_rule") != BENCH_RULE   # 11.11.: a bench of the old +10 / -20 / 1 h rule
        if (con.execute("SELECT 1 FROM bench LIMIT 1").fetchone() is None and not store.kv_get(con, "bench_boot")) \
                or (stale and store.kv_get(con, "bench_boot_rule") != BENCH_RULE):
            store.kv_put(con, "bench_boot", int(now))   # once: the first run after a deploy, then the night step
            store.kv_put(con, "bench_boot_rule", BENCH_RULE)   # once per benchmark rule
            try:
                save_bench(con, bench_rows(now), now)
            except Exception as e:  # noqa: BLE001 - no benchmark: no influencer proposals until the night step
                log(f"prijedlozi: brzi izlaz callera nije izračunat ({type(e).__name__})")
        con.commit()
        S = src or build.Sources(path=path)
        if getattr(S, "path", None) is None:
            S.path = path
        rows, near, meta = build.build(now, S)
        ch = sync(con, rows, near, now, meta.get("market_ok", True), meta.get("prices"))
        record_seen(con, rows, near, now)
        toks = open_window_tokens(con, now)
        n_px = store_prices(con, meta.get("prices") or {}, toks, now)
        con.commit()   # 11.11.: not across the DexScreener read (the paper loop writes the waiting state too)
        rest = [t for t in toks if t not in (meta.get("prices") or {})]
        n_dex = dex_batch(con, rest, now, dex_fetch)
        store.kv_put(con, "last_pass", {"ts": now, "shown": len(rows), "near": near[:NEAR_KEEP],
                                        "sources_failed": meta.get("sources_failed") or []})
        con.commit()
        n_out = outcomes.measure_due(con, now, econ=econ, log=log)
        if now % 86400 < 200:
            store.prune(con, now)
        con.commit()
        zone_report(con, now, log, econ=econ)
    finally:
        con.close()
    n_wait = sum(1 for r in rows if r.get("wait_why"))   # 11.11. (decision 4): stored, not published ("čeka zonu")
    if ch["new"] or ch["expired"] or n_out:
        log(f"prijedlozi: prikazano {len(rows) - n_wait}, čeka zonu {n_wait}, novih {ch['new']}, isteklo "
            f"{ch['expired']}, skoro {len(near)}; "
            f"cijene {n_px} + DexScreener {n_dex}; ishodi {n_out}"
            + (f"; izvori s greškom: {', '.join(meta['sources_failed'][:4])}" if meta.get("sources_failed") else ""))
    return {"shown": len(rows), "near": len(near), **ch, "outcomes": n_out}
