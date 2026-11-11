"""get_hourly_brief (MCP, read-only, 11.11., Jure point 5): everything an hourly look needs in one call.

    portfolio          ui/mcpapi.portfolio() (positions with entry, market cap now, PnL %, exit plan; wallet SOL;
                       grok_autotrade with what is left today), each position marked live / trial, plus the paper
                       account's open demo trades (league.db, PAPER_USER) marked paper; at most PORTFOLIO_S seconds
                       (it asks DexScreener's shared cache), else the positions without the live price
    trade_requests     the MCP trade requests still pending; with include_closed=true the last 20 with their real
                       status (pending / expired / obsolete / ...); trade_requests_closed_hidden counts the rest
    signals            tokens with calls, followed wallets' buys or signals (scanner, groups, Autopilot, Grok) since
                       `since` (default 60 min), from events.db, with what is already computed: rug verdict and
                       snipers % (rug.db), stage final_stretch / migrated, fees and volume (scan.db), run-up since
                       first seen and market cap now (events.db price ticks), X numbers (xfeat.db, the scanner's and
                       Grok's), the brag share of the token's X posts in the hour (kol.db), each caller's score and
                       n_measured and each wallet's early-buyer record (events.db, the night batch)
    groups             kol/groupdisc.group_activity since `since` (hidden_group, caller groups)
    range_candidates   rangedca/view.candidates (range_score >= 0.7): tokens inside their range with entry_ready;
                       a price above 100 % of the range is a breakout, listed apart, never a range entry candidate
    momentum_candidates  momentum/view.candidates: the newest momentum_scalp signals (every entry rule met), near
                       misses, the 7-day base rate and the paper proof (11.11.)
    event_topics       topics/view.brief_part: the active event topics (flag event_tokens), buzz trend, token count,
                       main token, the measured price run-up into the event and the move after it (11.11.)
    zonewatch          zonewatch/view.brief_part: zones in force (armed, by source), alarms of the last 24 h (by event
                       and status), last_post_ok, last_error, configured (the Grok Bot webhook env) and the flag (11.11.);
                       positions (the real account's positions and levels watched), position_alerts_24h by level
                       (sl_near, sl_hit, tp_hit, dca_hit) and range_off_24h
    grok_calibration   momentum/evgate.report: Grok's p_tp on execute_trade against what happened (Brier, buckets)
    grok_predictions   events/predictions.brief_part: Grok's predictions scored since `since` and the calibration
                       per p_tp bucket, Grok's and MemeSonar's
    health             the feeds' gap alerts (events/health), last night's batch (start, duration, calls processed,
                       Helius credits, errors) and the alert when it had not finished by 04:30 Zagreb
Nothing is fetched or recomputed per call beyond reading these stores; every part has its own try and its time in
"timing_ms", so one broken store never costs the rest.
"""
import json
import re
import sqlite3
import threading
import time

from events import health, outcomes, sources, store

DEFAULT_SINCE_S = 3600
LIMIT_DEFAULT, LIMIT_MAX = 30, 100
PORTFOLIO_S = 2.0
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def parse_since(since, now):
    """ISO 8601 or unix seconds / milliseconds -> unix seconds; None -> now - 60 min. ValueError on garbage."""
    if since is None or since == "":
        return now - DEFAULT_SINCE_S
    if isinstance(since, (int, float)) or (isinstance(since, str) and re.fullmatch(r"\d{9,14}(\.\d+)?", since.strip())):
        v = float(since)
        return int(v / 1000 if v > 1e12 else v)
    import datetime as dt
    try:
        d = dt.datetime.fromisoformat(str(since).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("since must be ISO 8601 (2026-11-11T08:00:00Z) or unix seconds / milliseconds")
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp())


def _timed(out, name, fn, *a):
    t = time.perf_counter()
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001 - one part never costs the brief
        return {"error": f"{type(e).__name__}: {e}"[:200]}
    finally:
        out.setdefault("timing_ms", {})[name] = round((time.perf_counter() - t) * 1000, 1)


def _with_timeout(fn, seconds):
    box = {}

    def run():
        try:
            box["v"] = fn()
        except Exception as e:  # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=run, name="brief-part", daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        raise TimeoutError(f"duže od {seconds:.0f} s")
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _latest_mcap(econ, mints, now, max_age_s=6 * 3600):
    """{mint: (mcap, ts)} of the newest price tick per mint."""
    out = {}
    if econ is None:
        return out
    for m in mints:
        r = econ.execute("SELECT mcap_usd, ts FROM events WHERE mint = ? AND type = 'price_tick' AND ts >= ? "
                         "ORDER BY ts DESC LIMIT 1", (m, (now - max_age_s) * 1000)).fetchone()
        if r and r[0]:
            out[m] = (r[0], r[1] // 1000)
    return out


def portfolio_part(econ, now):
    from ui import mcpapi
    try:
        p = _with_timeout(lambda: mcpapi.portfolio(now), PORTFOLIO_S)
    except Exception as e:  # noqa: BLE001 - the positions without the live price
        p = {"error": f"{type(e).__name__}: {e}", "open_positions": _positions_plain()}
    mode = p.get("mode")
    for g in p.get("open_positions") or []:
        g["account"] = "live" if mode == "live" else ("trial" if mode == "trial" else "off")
    p["paper_positions"] = _paper_positions(econ, now)
    return p


def _positions_plain():
    from trade import settings
    tcon = settings.connect()
    try:
        return [{"token": t, "symbol": s, "opened_ts": ts, "sol_in": sin} for t, s, ts, sin in tcon.execute(
            "SELECT token, symbol, opened_ts, sol_in FROM positions WHERE status='open' ORDER BY id")]
    except sqlite3.Error:   # no positions table yet
        return []
    finally:
        tcon.close()


def _paper_positions(econ, now):
    """Open demo trades of the paper account (league.db), market cap now from the newest price tick."""
    from trade import settings
    lcon = sources._ro(sources.db_paths()["league"])
    if lcon is None:
        return []
    try:
        rows = lcon.execute("SELECT id, token, symbol, opened_ts, size_usd, entry_mcap, source FROM trades WHERE user = ? "
                            "AND status = 'open' ORDER BY opened_ts", (settings.PAPER_USER,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        lcon.close()
    mc = _latest_mcap(econ, {r[1] for r in rows}, now)
    out = []
    for rid, tok, sym, ts, size, emc, src in rows:
        now_mc, mts = mc.get(tok, (None, None))
        out.append({"id": rid, "token": tok, "symbol": sym, "account": "paper", "opened_ts": ts, "size_usd": size,
                    "entry_market_cap_usd": emc, "market_cap_now_usd": now_mc, "price_ts": mts,
                    "pnl_pct": round((now_mc / emc - 1) * 100, 2) if now_mc and emc else None, "via": src})
    return out


def requests_part(now, include_closed=False):
    """(the requests shown, how many of the last 20 were left out because they no longer wait)."""
    from trade import settings
    from ui import mcpapi
    tcon = settings.connect()
    try:
        every = mcpapi.requests_view(tcon, now, 20)
    finally:
        tcon.close()
    shown = every if include_closed else [r for r in every if r["status"] == "pending"]
    return shown, len(every) - len(shown)


def _group_events(econ, since, now):
    """{mint: {...}} of calls, wallet buys and signals since `since`, from the (type, ts) index."""
    by = {}
    for t, mint, typ, src, actor, sol, mc in econ.execute(
            "SELECT ts, mint, type, source, actor, sol_amount, mcap_usd FROM events WHERE type IN ('call', 'wallet_buy', "
            "'signal') AND ts >= ? AND ts <= ? AND mint IS NOT NULL ORDER BY ts DESC LIMIT 20000",
            (since * 1000, now * 1000)):
        g = by.setdefault(mint, {"token": mint, "first_ts": t, "last_ts": t, "callers": {}, "wallets": {},
                                 "signals": {}})
        g["first_ts"], g["last_ts"] = min(g["first_ts"], t), max(g["last_ts"], t)
        if typ == "call":
            g["callers"].setdefault(actor, {"who": actor, "platform": "tg" if src == "telegram" else "x", "ts": t // 1000})
        elif typ == "wallet_buy":
            w = g["wallets"].setdefault(actor, {"wallet": actor, "ts": t // 1000, "sol": 0.0, "via": src})
            w["sol"] = round(w["sol"] + (sol or 0), 4)
        else:
            g["signals"].setdefault(f"{src}:{actor}", {"source": src, "who": actor, "ts": t // 1000,
                                                      "mcap_usd": mc})
    return by


def _first_seen(econ, mints, now):
    """{mint: first event ts (s) of any kind} over the last 7 days (the run-up's starting point)."""
    out = {}
    for m in mints:
        r = econ.execute("SELECT MIN(ts) FROM events WHERE mint = ? AND ts >= ?",
                         (m, int((now - 7 * 86400) * 1000))).fetchone()
        if r and r[0]:
            out[m] = r[0] // 1000
    return out


def _price_near(econ, mint, ts, after_s=3600):
    r = econ.execute("SELECT ts, payload, mcap_usd FROM events WHERE mint = ? AND type = 'price_tick' AND ts >= ? AND "
                     "ts <= ? ORDER BY ts LIMIT 1", (mint, (ts - 600) * 1000, (ts + after_s) * 1000)).fetchone()
    if not r:
        return None
    try:
        return json.loads(r[1] or "{}").get("p"), r[2]
    except ValueError:
        return None


def _rug(mints):
    con = sources._ro(sources.db_paths().get("rug") or _rug_path())
    out = {}
    if con is None:
        return out
    try:
        q = ",".join("?" * len(mints))
        for m, ts, v, sc, sn, t10, b in con.execute(
                f"SELECT mint, checked_at, verdict, score, sniper_pct, top10_pct, bundle_pct FROM rug_reports "
                f"WHERE mint IN ({q}) ORDER BY checked_at", list(mints)):
            out[m] = {"verdict": v, "score": sc, "sniper_pct": sn, "top10_pct": t10, "bundle_pct": b, "checked_ts": ts}
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def _rug_path():
    import os
    return os.environ.get("RUG_DB") or os.path.join(store.ROOT, "rug.db")


def _scan(mints):
    con = sources._ro(sources.db_paths()["scan"])
    out = {}
    if con is None:
        return out
    try:
        q = ",".join("?" * len(mints))
        cur = con.execute(f"SELECT token, symbol, stage, tradeable, fees_paid_sol, vol_h1, mcap, liq, buy_share, holders, "
                          f"top10_pct, first_seen, checked_ts FROM cand WHERE token IN ({q})", list(mints))
        cols = [d[0] for d in cur.description]
        for r in cur:
            d = dict(zip(cols, r))
            out[d["token"]] = d
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def _brag(mints, now):
    con = sources._ro(sources.db_paths()["kol"])
    out = {}
    if con is None:
        return out
    try:
        for m in mints:
            c = dict(con.execute("SELECT kind, COUNT(*) FROM calls WHERE token = ? AND ts >= ? AND handle NOT LIKE 'w:%' "
                                 "GROUP BY kind", (m, now - 3600)).fetchall())
            n = (c.get("call") or 0) + (c.get("brag") or 0)
            if n:
                out[m] = {"posts_1h": sum(c.values()), "brag_ratio": round((c.get("brag") or 0) / n, 3)}
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def _x(mints, now):
    try:
        from scan import xmom
        return xmom.latest(list(mints), since=now - 6 * 3600, now=now)
    except Exception:  # noqa: BLE001
        return {}


def _early(econ, wallets):
    out = {}
    ws = sorted(w for w in wallets if w)
    for i in range(0, len(ws), 400):
        part = ws[i:i + 400]
        for w, n, wins, wr, lead, src in econ.execute(
                f"SELECT wallet, n_early, n_wins, win_rate, median_lead_min, source FROM early_wallets WHERE wallet IN "
                f"({','.join('?' * len(part))})", part):
            out[w] = {"n_early": n, "n_wins": wins, "win_rate": wr, "median_lead_min": lead, "source": src}
    return out


def signals_part(econ, since, now, limit):
    if econ is None:
        return {"items": [], "note": "events.db još ne postoji"}
    by = _group_events(econ, since, now)
    ranked = sorted(by.values(), key=lambda g: (-(len(g["callers"]) + len(g["wallets"]) + len(g["signals"])),
                                                -g["last_ts"]))[:limit]
    mints = [g["token"] for g in ranked]
    if not mints:
        return {"items": [], "total": 0}
    first = _first_seen(econ, mints, now)
    mcap = _latest_mcap(econ, mints, now)
    rug, scan, brag, xm = _rug(mints), _scan(mints), _brag(mints, now), _x(mints, now)
    sc = outcomes.score_of(econ, {a for g in ranked for a in list(g["callers"]) + list(g["wallets"])})
    early = _early(econ, {w for g in ranked for w in g["wallets"]})
    items = []
    for g in ranked:
        m = g["token"]
        s = scan.get(m) or {}
        f0 = first.get(m)
        p0 = _price_near(econ, m, f0) if f0 else None
        pn = econ.execute("SELECT payload FROM events WHERE mint = ? AND type = 'price_tick' ORDER BY ts DESC LIMIT 1",
                          (m,)).fetchone()
        try:
            p_now = json.loads(pn[0] or "{}").get("p") if pn else None
        except ValueError:
            p_now = None
        run_up = round((p_now / p0[0] - 1) * 100, 1) if p0 and p0[0] and p_now else None
        stage = s.get("stage")
        x = xm.get(m) or {}
        items.append({
            "token": m, "symbol": s.get("symbol"), "first_seen_ts": f0, "first_ts": g["first_ts"] // 1000,
            "last_ts": g["last_ts"] // 1000,
            "callers": [dict(c, score=sc.get(c["who"])) for c in g["callers"].values()],
            "wallets": [dict(w, score=sc.get(w["wallet"]), early=early.get(w["wallet"])) for w in g["wallets"].values()],
            "signals": list(g["signals"].values()),
            "n_callers": len(g["callers"]), "n_wallets": len(g["wallets"]),
            "market_cap_usd": (mcap.get(m) or (None,))[0], "price_ts": (mcap.get(m) or (None, None))[1],
            "under_30k": bool(mcap.get(m) and mcap[m][0] < store.MIN_MCAP),
            "features": {
                "rug": rug.get(m), "snipers_pct": (rug.get(m) or {}).get("sniper_pct"),
                "fees_paid_sol": s.get("fees_paid_sol"), "volume_1h_usd": s.get("vol_h1"),
                "run_up_since_first_seen_pct": run_up,
                "phase": stage,
                "x": {"posts_per_h": x.get("posts60"), "unique_authors_15m": x.get("authors15"),
                      "template_share": x.get("bot_share"), "x_momentum_score": x.get("x_momentum_score"),
                      "x_early": x.get("x_early"), "source": x.get("source"), **(brag.get(m) or {})}}})
    return {"items": items, "total": len(by)}


def groups_part(since, now):
    from kol import groupdisc
    d = groupdisc.group_activity(since, 30, now=now)
    return {k: d.get(k) for k in ("flag_mode", "activity", "signals", "total", "note") if k in d}


def range_part():
    from rangedca import view
    d = view.candidates(None)
    if "error" in d:
        return d
    keep = ("token", "symbol", "status", "range_score", "position_in_range_pct", "entry_ready", "entry_now")

    def row(c):
        z = (c.get("zones") or {}).get("market_cap_usd") or {}
        return {**{k: c.get(k) for k in keep if k in c}, "range_low_low_mc": z.get("range_low_low"),
                "range_high_top_mc": z.get("range_high_top")}
    return {"flag_mode": d.get("flag_mode"), "watched": d.get("watched"),
            "candidates": [row(c) for c in (d.get("candidates") or [])[:15]],
            "breakouts": [{k: c.get(k) for k in ("token", "symbol", "status", "position_in_range_pct") if k in c}
                          for c in (d.get("breakouts") or [])[:10]]}


def momentum_part(now):
    """11.11. (flag momentum_scalp, momentum/view.py): the newest signals and near misses for Grok to rate."""
    from momentum import view
    d = view.candidates(now, minutes=60, limit=15)
    d.pop("positions", None)   # get_portfolio_status has them
    return d


def event_part(now):
    """11.11. (flag event_tokens, topics/view.py): the active event topics with buzz trend, token count, main token
    and the measured run-up / after-event summary (one read of topics.db)."""
    from topics import view
    return view.brief_part(now)


def zonewatch_part(now):
    """11.11. (flag zonewatch, zonewatch/view.py): zones in force, alarms of 24 h, the last good POST and the last error,
    whether the Grok Bot webhook is configured (one read-only look at zonewatch.db)."""
    from zonewatch import view
    return view.brief_part(now)


def calibration_part(now):
    """11.11. (flag grok_ev_gate, momentum/evgate.py): Brier score and reliability of Grok's p_tp, 30 days."""
    from momentum import evgate
    return evgate.report(now)


def predictions_part(econ, since, now):
    from events import predictions
    return predictions.brief_part(econ, since, now)


def health_part(econ, now=None):
    from events import night
    now = int(now or time.time())
    h = health.latest(econ)
    rep = night.report(econ) if econ is not None else {}
    start = (store.kv_get(econ, "night_start") or {}) if econ is not None else {}
    alert = (store.kv_get(econ, "night_alert") or {}) if econ is not None else {}
    today = night.zagreb(now).date().isoformat()
    if alert.get("day") == today:   # 11.11.: the night batch had not finished by 04:30 Zagreb
        h["alerts"] = list(h.get("alerts") or []) + [alert]
    if not rep and not start:
        h["last_night"] = None
        return h
    errs = rep.get("errors")
    if errs is None:   # a report from before 11.11. (no errors field)
        errs = {k: v["result"]["error"] for k, v in (rep.get("steps") or {}).items()
                if isinstance(v.get("result"), dict) and "error" in v["result"]}
    running = bool(start) and (start.get("ts") or 0) > (rep.get("started_ts") or rep.get("ts") or 0)
    status = ("running" if running and alert.get("day") != start.get("day") else
              "not_finished_by_0430" if running else "errors" if errs else "ok")
    h["last_night"] = {"day": start.get("day") if running else rep.get("day"),
                       "started_ts": start.get("ts") if running else rep.get("started_ts") or rep.get("ts"),
                       "finished_ts": None if running else rep.get("finished_ts"),
                       "duration_s": None if running else rep.get("s"),
                       "calls_processed": None if running else (rep.get("calls_processed") or night.calls_processed(rep)),
                       "helius_credits": None if running else rep.get("helius_credits"),
                       "helius_cap": rep.get("helius_cap"), "errors": {} if running else errs, "status": status,
                       "alert": alert if alert.get("day") == today else None}
    if running and rep:
        h["last_night"]["previous"] = {"day": rep.get("day"), "finished_ts": rep.get("finished_ts"),
                                       "duration_s": rep.get("s"), "errors": errs}
    return h


def build(since=None, limit_signals=None, now=None, include_closed=False):
    now = int(now or time.time())
    try:
        since_s = parse_since(since, now)
    except ValueError as e:
        return {"error": str(e)}
    try:
        limit = max(1, min(LIMIT_MAX, int(limit_signals or LIMIT_DEFAULT)))
    except (TypeError, ValueError):
        return {"error": "limit_signals must be an integer 1-100"}
    t0 = time.perf_counter()
    out = {"ts": now, "since_ts": since_s}
    econ = store.ro()
    try:
        out["portfolio"] = _timed(out, "portfolio", portfolio_part, econ, now)
        req = _timed(out, "trade_requests", requests_part, now, include_closed)
        if isinstance(req, tuple):
            out["trade_requests"], out["trade_requests_closed_hidden"] = req
        else:
            out["trade_requests"] = req
        out["signals"] = _timed(out, "signals", signals_part, econ, since_s, now, limit)
        out["groups"] = _timed(out, "groups", groups_part, since_s, now)
        out["range_candidates"] = _timed(out, "range_candidates", range_part)
        out["momentum_candidates"] = _timed(out, "momentum_candidates", momentum_part, now)
        out["event_topics"] = _timed(out, "event_topics", event_part, now)
        out["zonewatch"] = _timed(out, "zonewatch", zonewatch_part, now)
        out["grok_calibration"] = _timed(out, "grok_calibration", calibration_part, now)
        out["grok_predictions"] = _timed(out, "grok_predictions", predictions_part, econ, since_s, now)
        out["health"] = _timed(out, "health", health_part, econ, now)
    finally:
        if econ is not None:
            econ.close()
    out["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
    return out
