"""Read-only analysis tools of the MemeSonar MCP endpoint (/mcp), 10.11. (Jure: an external AI assistant analyses
the full dataset). Every tool reads the databases read-only (file:...?mode=ro), pages its rows (limit 1..500,
offset >= 0, "next_offset" when more rows exist) and gives times as unix seconds. The one write is
submit_caller_weights: suggestions go to trade.db table assistant_suggestions with status 'pending'; nothing reads
them for live scoring, the owner approves or rejects them on the Autopilot page.

Data (see the map in the 10.11. PR): kol.db (calls, kols, kol_ids), minute.db (call_path), tg.db, hype.db
(chain_trades, live_trades, hype_snapshots, rug_archive), wallets.db (wallets, wallet_trades), rug.db (rug_reports),
topcheck.db (top_check), corr.db (snapshots), league.db (trades, follows, copy_log), trade.db (positions, settings).
"""
import json
import os
import sqlite3
import statistics
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_LIMIT = 500
DEFAULT_LIMIT = 100
_CACHE = {}          # key -> (ts, value): the leaderboard aggregates, 5 min
_LOCK = threading.Lock()
CACHE_S = 300
CO_CALL_S = 900      # "other callers within 15 min before / after"
X2 = 1.0             # max24 >= +100 % = reached 2x
HIT = 0.5            # the project's hit: max24 >= +50 % (kol/score.py hit_rate)
BRAG_MIN, BRAG_SHARE = 3, 0.3


# ---------- plumbing -------------------------------------------------------------------------------------------------

def _path(name):
    from league import store
    from trade import settings
    env = {"kol": "KOL_DB", "hype": "HYPE_DB", "tg": "TG_DB", "wallets": "WALLET_DB", "rug": "RUG_DB",
           "topcheck": "TOPCHECK_DB", "corr": "CORR_DB"}.get(name)
    if env and os.environ.get(env):
        return os.environ[env]
    if name == "minute":
        from kol import minute
        return minute.db_path()
    if name == "league":
        return store.DB
    if name == "trade":
        return settings.DB
    if name == "kol":
        from kol import store as kstore
        return kstore.DB
    if name == "wallets":
        from wallets import store as wstore
        return wstore.DB
    if name == "topcheck":
        from topcheck import store as tstore
        return tstore.DB
    if name == "corr":
        from corr import store as cstore
        return cstore.DB
    if name in ("hype", "tg"):
        from league import copy
        return copy._paths()[name]
    return os.path.join(ROOT, f"{name}.db")


def _ro(name):
    p = _path(name)
    if not p or not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _close(*cons):
    for c in cons:
        if c is not None:
            c.close()


def _page(limit, offset):
    try:
        limit = int(limit if limit is not None else DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(offset or 0)
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(MAX_LIMIT, limit)), max(0, offset)


def _paged(rows, limit, offset, total=None, **extra):
    """rows: the whole list (sliced here) or, with total given, the page the query already cut."""
    page = rows[offset:offset + limit] if total is None else rows
    total = len(rows) if total is None else total
    out = {"ts": int(time.time()), "limit": limit, "offset": offset, "total": total, "rows": page}
    if offset + limit < total:
        out["next_offset"] = offset + limit
    out.update(extra)
    return out


def _f(x, nd=6):
    try:
        return round(float(x), nd) if x is not None else None
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def _cached(key, build):
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_S:
            return hit[1]
    val = build()
    with _LOCK:
        _CACHE[key] = (now, val)
    return val


def platform_of(handle):
    h = handle or ""
    return "telegram" if h.startswith("tg:") else "wallet" if h.startswith("w:") else "x"


def _handle(handle, platform=None):
    h = (handle or "").strip().lstrip("@")
    if (platform or "").lower() == "telegram" and not h.startswith("tg:"):
        h = "tg:" + h
    return h


# ---------- 1. caller leaderboard --------------------------------------------------------------------------------

SORTS = ("score", "hit_rate", "calls", "avg_r24h", "x2_share", "followers", "last_call_ts", "power_rel")


def _leaderboard_rows():
    """Every caller (X and Telegram) with its aggregates; cached CACHE_S per kol.db file."""
    def build():
        kc = _ro("kol")
        try:
            kols = {h: (name, fol, score, prel, stats, bot) for h, name, fol, score, prel, stats, bot in _q(
                kc, "SELECT handle, name, followers, score, power_rel, stats, COALESCE(bot, 0) FROM kols")}
            if not kols:   # an older kol.db without the bot column
                kols = {h: (name, fol, score, prel, stats, 0) for h, name, fol, score, prel, stats in _q(
                    kc, "SELECT handle, name, followers, score, power_rel, stats FROM kols")}
            agg = {}
            for h, ts, kind, r1h, r24h, max24, rug, mcap0, fol in _q(
                    kc, "SELECT handle, ts, kind, r1h, r24h, max24, rug, mcap0, followers FROM calls "
                        "WHERE kind IN ('call', 'brag') AND handle NOT LIKE 'w:%'"):
                a = agg.setdefault(h, {"calls": 0, "brags": 0, "first": None, "last": None, "r1h": [], "r24h": [],
                                       "max24": [], "rug": 0, "mcap0": [], "fol": None})
                if kind == "brag":
                    a["brags"] += 1
                    continue
                a["calls"] += 1
                a["first"] = ts if a["first"] is None else min(a["first"], ts)
                a["last"] = ts if a["last"] is None else max(a["last"], ts)
                a["r1h"].append(r1h)
                a["r24h"].append(r24h)
                a["max24"].append(max24)
                a["rug"] += 1 if rug else 0
                if mcap0:
                    a["mcap0"].append(mcap0)
                if fol:
                    a["fol"] = fol
        finally:
            _close(kc)
        try:
            from ui import public
            stars = public.star_handles()
        except Exception:  # noqa: BLE001
            stars = set()
        try:
            good = json.load(open(os.path.join(ROOT, "kol", "config.json"))).get("good_score", 50)
        except (OSError, ValueError):
            good = 50
        rows = []
        for h in set(agg) | {k for k in kols if not k.startswith("w:")}:
            a = agg.get(h) or {"calls": 0, "brags": 0, "first": None, "last": None, "r1h": [], "r24h": [], "max24": [],
                               "rug": 0, "mcap0": [], "fol": None}
            name, fol, score, prel, stats, bot = kols.get(h, (None, None, None, None, None, 0))
            fol = fol or a["fol"]
            measured = [m for m in a["max24"] if m is not None]
            big = (fol or 0) >= 100_000 or h.lower() in stars
            posts = a["calls"] + a["brags"]
            rows.append({
                "handle": h, "platform": platform_of(h), "name": name, "followers": _i(fol),
                "first_call_ts": _i(a["first"]), "last_call_ts": _i(a["last"]), "calls": a["calls"],
                "measured_calls": len(measured),
                "hit_rate": round(sum(1 for m in measured if m >= HIT) / len(measured), 4) if measured else None,
                "avg_r1h": _avg(a["r1h"]), "median_r1h": _med(a["r1h"]),
                "avg_r24h": _avg(a["r24h"]), "median_r24h": _med(a["r24h"]),
                "x2_share": round(sum(1 for m in measured if m >= X2) / len(measured), 4) if measured else None,
                "rug_count": a["rug"], "avg_mcap_at_call": _avg(a["mcap0"]),
                "call_power": _f(score, 2), "power_rel": _f(prel, 4), "bot": bool(bot),
                "big_name": big, "rising_star": (not big) and (score or 0) >= good,
                "bragger": a["brags"] >= BRAG_MIN and posts > 0 and a["brags"] / posts >= BRAG_SHARE, "brags": a["brags"]})
        return rows
    return _cached(("lb", _path("kol")), build)


def caller_leaderboard(platform=None, min_calls=None, sort=None, limit=None, offset=None):
    limit, offset = _page(limit, offset)
    rows = list(_leaderboard_rows())
    if platform in ("x", "telegram"):
        rows = [r for r in rows if r["platform"] == platform]
    if min_calls:
        rows = [r for r in rows if r["calls"] >= int(min_calls)]
    key = sort if sort in SORTS else "score"
    field = "call_power" if key == "score" else key
    rows.sort(key=lambda r: (r.get(field) is None, -(r.get(field) or 0), r["handle"]))
    return _paged(rows, limit, offset, sort=key,
                  definitions={"hit_rate": f"share of measured calls whose 24 h high reached +{int(HIT * 100)} %",
                               "x2_share": "share of measured calls whose 24 h high reached 2x",
                               "r1h/r24h": "price change 1 h / 24 h after the call, as a fraction (0.25 = +25 %)",
                               "rug_count": "calls whose price fell 90 %+ within 24 h",
                               "call_power": "MemeSonar caller score 0-100 (kol/score.py)",
                               "big_name": "100k+ followers or on the stars list",
                               "rising_star": "not a big name, call_power >= good_score (kol/config.json)",
                               "bragger": f">= {BRAG_MIN} 'brag' posts and >= {int(BRAG_SHARE * 100)} % of their posts"})


# ---------- 2. caller history ------------------------------------------------------------------------------------

def caller_history(handle, platform=None, since_ts=None, limit=None, offset=None):
    limit, offset = _page(limit, offset)
    h = _handle(handle, platform)
    if not h:
        return {"error": "handle is required"}
    since = int(since_ts or 0)
    kc, mc = _ro("kol"), _ro("minute")
    try:
        total = (_q(kc, "SELECT COUNT(*) FROM calls WHERE handle=? COLLATE NOCASE AND kind='call' AND ts>=?",
                    (h, since)) or [(0,)])[0][0]
        rows = []
        for tid, tok, sym, ts, p0, mcap0, r1h, r24h, max24, rug, url in _q(
                kc, "SELECT tweet_id, token, symbol, ts, p0, mcap0, r1h, r24h, max24, rug, url FROM calls "
                    "WHERE handle=? COLLATE NOCASE AND kind='call' AND ts>=? ORDER BY ts DESC LIMIT ? OFFSET ?",
                (h, since, limit, offset)):
            path = _q(mc, "SELECT hi60, lo60, r60, entry FROM call_path WHERE tweet_id=? AND token=?", (tid, tok))
            hi60, lo60, r60, entry = path[0] if path else (None, None, None, None)
            before = (_q(kc, "SELECT COUNT(DISTINCT handle) FROM calls WHERE token=? AND kind='call' AND handle!=? "
                             "AND ts>=? AND ts<?", (tok, h, ts - CO_CALL_S, ts)) or [(0,)])[0][0]
            after = (_q(kc, "SELECT COUNT(DISTINCT handle) FROM calls WHERE token=? AND kind='call' AND handle!=? "
                            "AND ts>=? AND ts<=?", (tok, h, ts, ts + CO_CALL_S)) or [(0,)])[0][0]
            rows.append({"token": tok, "symbol": sym, "call_ts": _i(ts), "url": url, "price_at_call": _f(p0, 12),
                         "market_cap_at_call": _f(mcap0, 0),
                         "max_1h": _f(hi60, 4), "min_1h": _f(lo60, 4),
                         "max_24h": _f(max24, 4), "min_24h": None,
                         "price_1h": _f(p0 * (1 + r1h), 12) if p0 and r1h is not None else None,
                         "price_24h": _f(p0 * (1 + r24h), 12) if p0 and r24h is not None else None,
                         "change_1h": _f(r1h, 4), "change_24h": _f(r24h, 4), "rug": bool(rug),
                         "other_callers_15m_before": before, "other_callers_15m_after": after})
    finally:
        _close(kc, mc)
    return _paged(rows, limit, offset, total=total, handle=h, platform=platform_of(h),
                  definitions={"max_1h/min_1h": "highest / lowest move in the first 60 min after the minute of the call "
                                                "(minute candles, fraction of the entry; null = not measured)",
                               "max_24h": "highest move within 24 h (fraction); min_24h is not measured"})


# ---------- 3. token history -------------------------------------------------------------------------------------

def _thin(points, n=MAX_LIMIT):
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n - 1)] + [points[-1]]


def token_history(token_address):
    from trade import settings
    tok = (token_address or "").strip()
    if not tok or len(tok) < 32:
        return {"error": "token_address must be a Solana token address"}
    kc, hc, rc, tc, lc, trc = _ro("kol"), _ro("hype"), _ro("rug"), _ro("topcheck"), _ro("league"), _ro("trade")
    try:
        calls = [{"handle": h, "platform": platform_of(h), "ts": _i(ts), "kind": kind, "market_cap_at_call": _f(mc, 0),
                  "followers": _i(fol), "url": url}
                 for h, ts, kind, mc, fol, url in _q(kc, "SELECT handle, ts, kind, mcap0, followers, url FROM calls "
                                                         "WHERE token=? ORDER BY ts LIMIT 500", (tok,))]
        series = {}
        for ts, price, mcap, liq in _q(hc, "SELECT ts, price, mcap, liquidity FROM hype_snapshots WHERE token=? "
                                           "ORDER BY ts", (tok,)):
            series[int(ts)] = {"ts": int(ts), "price": _f(price, 12), "market_cap": _f(mcap, 0), "liquidity": _f(liq, 0)}
        for ts, price, mcap, liq in _q(kc, "SELECT ts, price, mcap, liq FROM snaps WHERE token=? ORDER BY ts", (tok,)):
            series.setdefault(int(ts), {"ts": int(ts), "price": _f(price, 12), "market_cap": _f(mcap, 0),
                                        "liquidity": _f(liq, 0)})
        rug = [{"checked_ts": _i(ts), "verdict": v, "score": _f(sc, 1), "top10_pct": _f(t10, 1), "bundle_pct": _f(b, 1),
                "sniper_pct": _f(s, 1), "cluster_pct": _f(cl, 1), "dev": dev}
               for ts, v, sc, t10, b, s, cl, dev in _q(rc, "SELECT checked_at, verdict, score, top10_pct, bundle_pct, "
                                                           "sniper_pct, cluster_pct, dev FROM rug_reports WHERE mint=? "
                                                           "ORDER BY checked_at DESC LIMIT 20", (tok,))]
        top = _q(tc, "SELECT ts, verdict, mcap, liq, rc_ts FROM top_check WHERE token=?", (tok,))
        arch = _q(hc, "SELECT archived_ts, kind, reason, peak_mcap, last_mcap FROM rug_archive WHERE token=?", (tok,))
        trades = [{"league_trade_id": i, "opened_ts": _i(o), "closed_ts": _i(c), "status": st, "source": src,
                   "entry_market_cap": _f(emc, 0), "exit_market_cap": _f(xmc, 0), "exit_note": note,
                   "demo_pnl_usd": _f(pnl, 2)}
                  for i, o, c, st, src, emc, xmc, note, pnl in _q(
                      lc, "SELECT id, opened_ts, closed_ts, status, source, entry_mcap, exit_mcap, note, pnl_usd FROM trades "
                          "WHERE user=? AND token=? ORDER BY opened_ts", (settings.LEAGUE_USER, tok))]
        real = [{"position_id": i, "league_trade_id": lid, "opened_ts": _i(o), "closed_ts": _i(c), "mode": m,
                 "status": st, "sol_in": _f(si, 4), "sol_back": _f(sb, 4), "fees_sol": _f(fe, 5)}
                for i, lid, o, c, m, st, si, sb, fe in _q(
                    trc, "SELECT id, league_id, opened_ts, closed_ts, mode, status, sol_in, sol_back, fees_sol FROM positions "
                         "WHERE token=? ORDER BY id", (tok,))]
    finally:
        _close(kc, hc, rc, tc, lc, trc)
    pts = _thin([series[k] for k in sorted(series)])
    return {"ts": int(time.time()), "token": tok, "calls": calls, "price_series": pts,
            "rug_checks": rug,
            "top_check": ({"ts": _i(top[0][0]), "verdict": top[0][1], "market_cap": _f(top[0][2], 0),
                           "liquidity": _f(top[0][3], 0), "rugcheck_ts": _i(top[0][4])} if top else None),
            "rug_archive": ({"archived_ts": _i(arch[0][0]), "kind": arch[0][1], "reason": arch[0][2],
                             "peak_market_cap": _f(arch[0][3], 0), "last_market_cap": _f(arch[0][4], 0)} if arch else None),
            "autopilot_demo_trades": trades, "autopilot_real_positions": real,
            "notes": "price_series: hype_snapshots (every 20 min) + kol snaps, thinned to at most 500 points"}


# ---------- 4. wallets -------------------------------------------------------------------------------------------

def _kol_ids():
    kc = _ro("kol")
    try:
        return {w: {"name": n, "twitter": tw, "telegram": tg, "pnl": p, "wins": wi, "losses": lo}
                for w, n, tw, tg, p, wi, lo in _q(kc, "SELECT wallet, name, twitter, telegram, pnl, wins, losses FROM kol_ids")}
    finally:
        _close(kc)


def wallet_leaderboard(kind=None, limit=None, offset=None):
    limit, offset = _page(limit, offset)
    ids = _kol_ids()
    wc = _ro("wallets")
    try:
        rows = []
        for w, tier, score, cscore, stats, labels, last_tx in _q(
                wc, "SELECT wallet, tier, score, copy_score, stats, labels, last_tx_ts FROM wallets "
                    "WHERE stats IS NOT NULL ORDER BY COALESCE(score, 0) DESC"):
            try:
                st = json.loads(stats or "{}") or {}
            except ValueError:
                st = {}
            link = ids.get(w) or {}
            rows.append({"wallet": w, "kind": "influencer" if w in ids else ("smart" if tier in ("S", "A", "B") else "other"),
                         "tier": tier, "score": _f(score, 2), "copy_score": _f(cscore, 2),
                         "realized_pnl_sol": _f(st.get("realized_sol"), 4), "unrealized_pnl_sol": _f(st.get("unrealized_sol"), 4),
                         "win_rate": _f(st.get("win_rate"), 4), "median_hold_min": _f(st.get("median_hold_min"), 1),
                         "style": st.get("style"), "last_trade_ts": _i(last_tx),
                         "linked_handle": link.get("twitter") or link.get("name")})
        seen = {r["wallet"] for r in rows}
        for w, link in ids.items():   # influencer wallets the wallet scorer has not reached yet
            if w not in seen:
                wins, losses = link.get("wins") or 0, link.get("losses") or 0
                rows.append({"wallet": w, "kind": "influencer", "tier": None, "score": None, "copy_score": None,
                             "realized_pnl_sol": _f(link.get("pnl"), 4), "unrealized_pnl_sol": None,
                             "win_rate": round(wins / (wins + losses), 4) if wins + losses else None,
                             "median_hold_min": None, "style": None, "last_trade_ts": None,
                             "linked_handle": link.get("twitter") or link.get("name")})
    finally:
        _close(wc)
    if kind in ("influencer", "smart"):
        rows = [r for r in rows if r["kind"] == kind]
    return _paged(rows, limit, offset,
                  definitions={"kind": "influencer = a known influencer's wallet (kol_ids); smart = wallet tier S/A/B",
                               "pnl": "SOL; realized from closed positions, unrealized at the last scoring"})


def wallet_history(address, limit=None, offset=None):
    limit, offset = _page(limit, offset)
    w = (address or "").strip()
    if len(w) < 32:
        return {"error": "address must be a Solana wallet address"}
    wc, hc = _ro("wallets"), _ro("hype")
    try:
        trades = {}
        for sig, ts, mint, tokens, sol, kind in _q(wc, "SELECT sig, ts, mint, tokens, sol, kind FROM wallet_trades "
                                                        "WHERE wallet=? ORDER BY ts DESC LIMIT 5000", (w,)):
            trades[(sig, mint)] = {"sig": sig, "ts": _i(ts), "token": mint, "side": kind, "sol": _f(sol, 4),
                                   "tokens": _f(tokens, 4), "market_cap_sol": None}
        for sig, mint, side, ts, sol in _q(hc, "SELECT sig, mint, side, ts, sol FROM chain_trades WHERE wallet=? "
                                               "ORDER BY ts DESC LIMIT 5000", (w,)):
            trades.setdefault((sig, mint), {"sig": sig, "ts": _i(ts), "token": mint, "side": side, "sol": _f(sol, 4),
                                            "tokens": None, "market_cap_sol": None})
        for sig, mint, side, sol, tokens, mcs, ts in _q(hc, "SELECT sig, mint, side, sol, tokens, mcap_sol, ts FROM live_trades "
                                                            "WHERE wallet=? ORDER BY ts DESC LIMIT 5000", (w,)):
            row = trades.setdefault((sig, mint), {"sig": sig, "ts": _i(ts), "token": mint, "side": side,
                                                  "sol": _f(sol, 4), "tokens": _f(tokens, 4), "market_cap_sol": None})
            row["market_cap_sol"] = _f(mcs, 2)
        info = _q(wc, "SELECT tier, score, stats FROM wallets WHERE wallet=?", (w,))
    finally:
        _close(wc, hc)
    rows = sorted(trades.values(), key=lambda r: -(r["ts"] or 0))
    st = {}
    if info:
        try:
            st = json.loads(info[0][2] or "{}") or {}
        except ValueError:
            st = {}
    link = _kol_ids().get(w) or {}
    return _paged(rows, limit, offset, wallet=w, tier=info[0][0] if info else None,
                  realized_pnl_sol=_f(st.get("realized_sol"), 4), win_rate=_f(st.get("win_rate"), 4),
                  linked_handle=link.get("twitter") or link.get("name"),
                  notes="sides: buy / sell; sol is the SOL size (sells from webhooks may have none); market_cap_sol "
                        "only for trades seen live (48 h)")


def wallet_clusters():
    """Groups of wallets that buy together (corr/analyze: same funder, same rug cluster, same-second buys) and the
    callers' clusters that call together, from the newest corr.db snapshot."""
    try:
        from corr import store as cstore
        ts, data, _ai = cstore.latest(_path("corr"))
    except Exception:  # noqa: BLE001
        ts, data = None, None
    data = data or {}
    groups = [{"id": g.get("id"), "wallets": (g.get("wallets") or [])[:100], "handles": (g.get("handles") or [])[:50],
               "tokens": (g.get("tokens") or g.get("shared_tokens") or [])[:100] if isinstance(g.get("tokens"), list) else g.get("tokens"),
               "why": g.get("why") or g.get("reasons"), "score": g.get("score"), "callers_clusters": g.get("clusters")}
              for g in (data.get("groups") or [])[:MAX_LIMIT]]
    clusters = [{"id": c.get("id"), "callers": (c.get("members") or [])[:50], "wallets": (c.get("wallets") or [])[:50],
                 "tokens_together": c.get("tokens"), "score": c.get("score"), "leader": c.get("leader")}
                for c in (data.get("clusters") or [])[:MAX_LIMIT]]
    return {"ts": int(time.time()), "snapshot_ts": _i(ts), "wallet_groups": groups, "caller_clusters": clusters,
            "notes": "wallet_groups: wallets joined by a common funder, the same rug cluster or repeated same-second "
                     "buys; caller_clusters: accounts that call the same tokens together (tokens_together = count)"}


# ---------- 6. autopilot trades ----------------------------------------------------------------------------------

def _exit_kind(note):
    n = (note or "").lower()
    if "auto tp" in n:
        return "TP"
    if "auto sl" in n:
        return "SL"
    if "vrijeme" in n:
        return "time"
    if "je prodao" in n:
        return "mirror (followed wallet sold)"
    if n.startswith("auto"):
        return "smart sell"
    return "manual" if n else None


def autopilot_trades(since_ts=None, limit=None, offset=None):
    from trade import settings
    limit, offset = _page(limit, offset)
    since = int(since_ts or 0)
    tc, lc = _ro("trade"), _ro("league")
    try:
        total = (_q(tc, "SELECT COUNT(*) FROM positions WHERE status IN ('open','closed') AND opened_ts>=?", (since,))
                 or [(0,)])[0][0]
        pos = _q(tc, "SELECT id, token, symbol, opened_ts, closed_ts, mode, status, reason, sol_in, sol_back, fees_sol, league_id "
                     "FROM positions WHERE status IN ('open','closed') AND opened_ts>=? ORDER BY id DESC LIMIT ? OFFSET ?",
                 (since, limit, offset))
        rows = []
        for pid, tok, sym, o, c, mode, st, reason, sin, sback, fees, lid in pos:
            lt = _q(lc, "SELECT entry_mcap, exit_mcap, note, source, score, follow_id, auto FROM trades WHERE id=?", (lid,)) if lid else []
            emc, xmc, note, src, score, fid, auto = lt[0] if lt else (None, None, None, None, None, None, None)
            fol = _q(lc, "SELECT kind, target, label FROM follows WHERE id=?", (fid,)) if fid else []
            sig = _q(lc, "SELECT ev_ts, note FROM copy_log WHERE trade_id=? AND action='ulaz' LIMIT 1", (lid,)) if lid else []
            lots = (_q(tc, "SELECT COUNT(*) FROM positions WHERE token=? AND status IN ('open','closed') AND id<=? AND opened_ts>=?",
                       (tok, pid, (o or 0) - 86400)) or [(1,)])[0][0]
            try:
                rule = json.loads(auto) if auto else None
            except ValueError:
                rule = None
            pnl = (sback or 0) - (sin or 0) - (fees or 0) if st == "closed" else None
            rows.append({"position_id": pid, "token": tok, "symbol": sym, "mode": mode, "status": st,
                         "entry_ts": _i(o), "exit_ts": _i(c), "entry_market_cap": _f(emc, 0), "exit_market_cap": _f(xmc, 0),
                         "sol_in": _f(sin, 4), "sol_out": _f(sback, 4), "fees_sol": _f(fees, 5), "pnl_sol": _f(pnl, 4),
                         "pnl_pct": _f(100 * pnl / sin, 2) if pnl is not None and sin else None,
                         "exit_reason": _exit_kind(note) if st == "closed" else None, "exit_note": note if st == "closed" else None,
                         "dca_lot": lots > 1, "exit_rule": {k: rule.get(k) for k in ("mode", "tp", "sl")} if rule else None,
                         "signal": {"source": (src or reason), "follow": ({"kind": fol[0][0], "target": fol[0][1], "label": fol[0][2]}
                                                                         if fol else None),
                                    "signal_ts": _i(sig[0][0]) if sig else None, "entry_note": sig[0][1] if sig else None,
                                    "score_at_entry": _f(score, 2)}})
    finally:
        _close(tc, lc)
    return _paged(rows, limit, offset, total=total, account=settings.LEAGUE_USER,
                  notes="real-money (mode live) and trial (dry) positions of the Autopilot; market caps from the demo "
                        "trade it mirrors; pnl_sol = sol_out - sol_in - fees for closed positions")


# ---------- 7. scoring config ------------------------------------------------------------------------------------

SAFE_SETTINGS = ("size_sol", "max_sol_per_trade", "max_sol_per_day", "max_loss_day", "max_open", "min_sol_reserve",
                 "max_cost_pct", "max_signal_age_s", "tp_default", "sl_default", "on", "use_pump", "auto_pick",
                 "auto_days", "auto_n")


def scoring_config():
    from league import copy
    from trade import executor, settings
    from ui import autopilot, kolsummary
    out = {"ts": int(time.time())}
    try:
        cfg = json.load(open(os.path.join(ROOT, "kol", "config.json")))
        out["caller_score"] = {k: cfg.get(k) for k in ("weights", "hit_x", "rug_x", "prepump_x", "prior_calls",
                                                         "prior_score", "good_score", "watch", "valid", "minute")}
    except (OSError, ValueError):
        out["caller_score"] = None
    out["caller_verdict"] = {"min_hit_1h": kolsummary.VERDICT_H1, "min_down_24h": kolsummary.VERDICT_D24,
                             "min_calls": kolsummary.VERDICT_MIN_N}
    out["autopilot_pick"] = {k: getattr(autopilot, k) for k in ("HIT", "MIN_CALLS", "MIN_CLOSED", "MIN_MINUTE",
                                                                "OLD_MIN_MINUTE", "WILSON_Z", "HOT_HIT10", "HOT_MAX_SL",
                                                                "MAX_OPEN_SHARE", "MAX_RUG", "TOP", "MOON_MIN_LIQ")
                             if hasattr(autopilot, k)}
    out["copy_filters"] = {**copy.CFG, "DEFAULT_SL_players": copy.DEFAULT_SL, "DATA_TP": copy.DATA_TP,
                           "DATA_MAX_LATE_S": copy.DATA_MAX_LATE_S, "DATA_MAX_RUNUP": copy.DATA_MAX_RUNUP}
    try:
        import run_trade
        out["real_money_proof_gate"] = dict(run_trade.PROOF)
    except Exception:  # noqa: BLE001
        out["real_money_proof_gate"] = None
    tcon = _ro("trade")   # read-only: this tool never creates or writes trade.db
    try:
        m = settings.merged(executor.load_config(), tcon) if tcon is not None else executor.load_config()
        raw = settings.raw(tcon) if tcon is not None else {}
    except sqlite3.Error:
        m, raw = executor.load_config(), {}
    finally:
        _close(tcon)
    out["autopilot_settings"] = {k: m.get(k, raw.get(k)) for k in SAFE_SETTINGS}
    try:
        from rugfilter import score as rscore
        out["rug_filter_thresholds"] = dict(getattr(rscore, "T", {}))
    except Exception:  # noqa: BLE001
        out["rug_filter_thresholds"] = None
    try:
        out["hype_weights"] = json.load(open(os.path.join(ROOT, "hype", "weights.json")))
    except (OSError, ValueError):
        out["hype_weights"] = None
    out["notes"] = ("Read-only. Proposals go through submit_caller_weights (owner review); nothing here changes by "
                    "this API.")
    return json.loads(json.dumps(out, default=str))


# ---------- 8. caller weight suggestions -------------------------------------------------------------------------

SUGG_SCHEMA = ("CREATE TABLE IF NOT EXISTS assistant_suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, "
               "kind TEXT, handle TEXT, platform TEXT, weight REAL, reason TEXT, status TEXT DEFAULT 'pending', "
               "decided_ts INTEGER, source TEXT)")


def submit_caller_weights(weights, source="mcp"):
    """Store suggested per-caller weights (0-2) for the owner's review; changes no live scoring."""
    from trade import settings
    if not isinstance(weights, list) or not weights:
        return {"error": "weights must be a non-empty list of {handle, platform, weight, reason}"}
    if len(weights) > 200:
        return {"error": "at most 200 suggestions per call"}
    clean = []
    for i, w in enumerate(weights):
        if not isinstance(w, dict):
            return {"error": f"item {i} is not an object"}
        plat = str(w.get("platform") or "x").lower()
        if plat not in ("x", "telegram"):
            return {"error": f"item {i}: platform must be x or telegram"}
        h = _handle(w.get("handle"), plat)
        try:
            wt = float(w.get("weight"))
        except (TypeError, ValueError):
            return {"error": f"item {i}: weight must be a number 0-2"}
        if not h or not 0 <= wt <= 2:
            return {"error": f"item {i}: handle required and weight must be between 0 and 2"}
        clean.append((h, plat, round(wt, 3), str(w.get("reason") or "")[:300]))
    now = int(time.time())
    con = settings.connect()
    try:
        con.execute(SUGG_SCHEMA)
        ids = [con.execute("INSERT INTO assistant_suggestions (ts, kind, handle, platform, weight, reason, source) "
                           "VALUES (?,?,?,?,?,?,?)", (now, "caller_weight", h, p, wt, r, source)).lastrowid
               for h, p, wt, r in clean]
        con.commit()
    finally:
        con.close()
    print(f"mcp: {len(ids)} prijedloga težina čeka pregled vlasnika", flush=True)
    return {"ts": now, "stored": len(ids), "ids": ids, "status": "pending",
            "message": "Stored for the owner's review on the MemeSonar Autopilot page; live scoring is unchanged."}


def suggestions(tcon, status="pending", limit=50):
    try:
        tcon.execute(SUGG_SCHEMA)
        return [{"id": i, "ts": ts, "handle": h, "platform": p, "weight": wt, "reason": r, "status": st}
                for i, ts, h, p, wt, r, st in tcon.execute(
                    "SELECT id, ts, handle, platform, weight, reason, status FROM assistant_suggestions WHERE status=? "
                    "ORDER BY id DESC LIMIT ?", (status, limit))]
    except sqlite3.Error:
        return []


def decide_suggestion(tcon, sid, status):
    tcon.execute(SUGG_SCHEMA)
    n = tcon.execute("UPDATE assistant_suggestions SET status=?, decided_ts=? WHERE id=? AND status='pending'",
                     (status, int(time.time()), int(sid))).rowcount
    tcon.commit()
    return n
