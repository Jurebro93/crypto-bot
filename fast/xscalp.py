"""x_call_scalp: the paper strategy of Grok's X calls (12.11., Jure, nalog točka 2; flag x_call_scalp G31, default
shadow, never live). Every submit_watch_token (fast/xcall.py) that passes the HARD blocks gets a virtual paper entry at
the market cap of the detection, and what the price did afterwards is measured net of cost, per author class. No
account buys (not even the demo one): shadow and paper do the same here; live is refused (trade/settings.NEVER_LIVE).

Entry (on_check, when the token's fast_check has decided): the hard blocks of the owner's rule B / CLAUDE.md, read from
that fast_check's own checks (no second read):
    rug_hard    ui/kandidati.rug_view level "hard" (collapse rug, rug archive, mint / freeze authority, RugCheck
                "rugged", a failed sell test = honeypot); rug_unknown = the rug check could not be read (CHECK_FAILED)
    honeypot    topcheck/safety's sell test failed
    curve       no bonded pool with liquidity (DexScreener pair missing or a launchpad curve: rugfilter/collapse.CURVES)
    liq_low     liquidity under $15k (trade/cost.liq_block)
    under_30k   market cap under $30k (CLAUDE.md)
The fast_check's own decision (SKIP on holders, flow, the 30k-5M band, EV) is NOT a block here: the strategy measures
every X call that could be bought at all. Entry = the check's market cap / price / liquidity and its time (entry_ts,
seconds after the detection); stake = STAKE_SOL x the SOL price; cost = trade/cost.round_trip(stake, liquidity).

Measurement (tick, run_fast.py every TICK_S; final at entry_ts + 60 min + GRACE_S). Ratios to the entry (mcap / mcap0,
or price / price0 for a USD price series of the same pool), from the cheap sources we already have, merged by time:
    x_call_px          our own DexScreener points (batches of 30 tokens, only when no other source has a point in the
                       last PX_EVERY_S, at most XCALL_DEX_DAY requests a Zagreb day; fast.db costs "dexscreener_xcall")
    fast.db px         the fast path's outcome points (DexScreener batches the worker reads anyway)
    hype.db token_pulse, range.db snaps    the hype scan's and the range engine's DexScreener snapshots
    minute.db call_candles                 GeckoTerminal 1-minute candles of a called token (high capped at 3x the
                                           body, as kol/minute)
    hype.db live_trades                    PumpPortal prints (per minute: high, low, close), SOL price over the median
                                           print of [entry - 2 min, entry + 1 min] (no print there: not used)
Results (fractions; net = gross - cost):
    max_net     the highest high before the price first touched -8 % (the stop candle's own high excluded), net
    r15, r60    the close nearest +15 min / +60 min, net (None without a point near it)
    hit         +10 % NET (gross >= +10 % + cost) came before the -8 % stop within 60 min (same candle: the stop)
    net         the x_call_scalp trade: +10 % at the target; -8 % - cost at the stop; else r60 (else the last close)
    dump        the first sale in the window by the dev (live_launches / rug.db creator) of >= DEV_SHARE of supply or
                by a top-10 holder (the fast_check's RugCheck holders, else rug.db) of >= HOLDER_SHARE (hype.db
                live_trades); else a rug.db report in the window saying "dev je prodao / prebacio" or rangedca/holders
                (range.db kv hold:) seeing the transfer holders sell (rugfilter/collapse's rug_evidence sources). dump_low
                = the lowest low after it within the window (gross, from the entry)
Classes (author): followers <10k | 10-50k | 50-200k | 200k+ x velocity (interactions = likes + replies + reposts per
minute since the post) niska < 2 | srednja 2-20 | visoka >= 20. Pretpostavka: the velocity cut points are a first guess
(no measured X calls yet); move them once a class has n >= 30.
Per class (get_x_call_stats, class_records for ui/kandidati.live_eligible): n, hit rate, median net, EV net (mean net),
and "ev" net of the fee part only (the records' convention in ui/kandidati.ev_estimate, which takes the impact of its
own size off itself). A class is a live record only with n >= 10 and EV net >= +3 % (LIVE_N_MIN, LIVE_EV_MIN).
"""
import json
import os
import sqlite3
import statistics
import time

from . import store

FLAG = "x_call_scalp"
SL = 0.08
TP_NET = 0.10
HORIZON_S = 3600
GRACE_S = 300
TICK_S = 30
PX_EVERY_S = 60
DEX_TOKENS = 30
XCALL_DEX_DAY = int(os.environ.get("XCALL_DEX_DAY", "1500"))
STAKE_SOL = float(os.environ.get("XCALL_STAKE_SOL", "0.1"))
SOL_USD_DEFAULT = 150.0
PENDING_MAX_S = 2 * 3600       # an entry whose fast_check never decided is given up after this
DEV_SHARE = 0.001               # a dev sale of >= 0.1 % of supply is a dump
HOLDER_SHARE = 0.005            # a top-10 holder's sale of >= 0.5 % of supply is a dump
WICK_X = 3.0
MIN_MCAP = 30_000
LIVE_N_MIN = 10
LIVE_EV_MIN = 0.03
FOLLOWER_BANDS = ((10_000, "<10k"), (50_000, "10-50k"), (200_000, "50-200k"), (None, "200k+"))
VEL_LOW, VEL_HIGH = 2.0, 20.0
VELOCITY_BANDS = ("niska", "srednja", "visoka")
FOL_NAMES = tuple(b for _x, b in FOLLOWER_BANDS)
CLASSES = tuple(f"{f}/{v}" for f in FOL_NAMES for v in VELOCITY_BANDS)
THRESHOLDS = {"followers": {"<10k": "< 10 000", "10-50k": "10 000 - 49 999", "50-200k": "50 000 - 199 999",
                            "200k+": ">= 200 000"},
              "velocity": {"unit": "interakcije (likes + replies + reposts) po minuti od objave",
                           "niska": f"< {VEL_LOW:g}", "srednja": f"{VEL_LOW:g} - {VEL_HIGH:g}",
                           "visoka": f">= {VEL_HIGH:g}"},
              "note": "Pretpostavka: pragovi brzine su prva procjena; pomaknuti kad razred ima n >= 30"}
SOURCES_TEXT = ("x_call_px (vlastiti DexScreener u paketima po 30, samo bez svježe točke), fast.db px, hype.db "
                "token_pulse, range.db snaps, minute.db call_candles, hype.db live_trades")
DEFINITIONS = ("ulaz: MC u trenutku detekcije (fast_check submit_watch_token); trošak: trade/cost.round_trip(ulog, "
               "likvidnost); max_net: najviši high prije prvog dodira -8 % (bruto), minus trošak; r15 / r60: close "
               "najbliži +15 / +60 min, neto; hit: +10 % neto prije -8 % u 60 min (ista svijeća: stop); net (rezultat "
               "tradea): +10 % na cilju, -8 % - trošak na stopu, inače r60; dump: prva prodaja deva (>= 0,1 % supplyja) "
               "ili top-10 holdera (>= 0,5 %) u prozoru, dno nakon njega bruto od ulaza")


def mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


# ---------- classes -------------------------------------------------------------------------------------------------

def fol_band(followers):
    f = int(followers or 0)
    for lim, name in FOLLOWER_BANDS:
        if lim is None or f < lim:
            return name
    return FOLLOWER_BANDS[-1][1]


def vel_band(velocity):
    v = float(velocity or 0)
    return "niska" if v < VEL_LOW else ("srednja" if v < VEL_HIGH else "visoka")


def classify(followers, velocity):
    """(follower band, velocity band, class "10-50k/srednja")."""
    fb, vb = fol_band(followers), vel_band(velocity)
    return fb, vb, f"{fb}/{vb}"


# ---------- the entry -------------------------------------------------------------------------------------------------

def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def hard_blocks(sig):
    """[(key, text)] of the hard blocks in the fast_check row `sig` (fast/store.read dict); [] = it may be entered."""
    from trade import cost as tcost
    res = ((sig or {}).get("checks") or {}).get("res") or {}
    rug, price = res.get("rug") or {}, res.get("price") or {}
    rv, pv = rug.get("values") or {}, price.get("values") or {}
    out = []
    if not rug or rug.get("status") == "error":
        out.append(("rug_unknown", f"rug provjera nije pročitana ({rug.get('text') or (sig or {}).get('reason') or '?'})"))
    elif rv.get("level") == "hard":
        out.append(("rug_hard", rug.get("text") or "rug (tvrdo)"))
    hp = (rv.get("checks") or {}).get("honeypot")
    if isinstance(hp, (list, tuple)) and len(hp) >= 2 and hp[0] == "fail":
        out.append(("honeypot", f"honeypot: {hp[1]}"))
    if not price or price.get("status") == "error":
        out.append(("market_unknown", f"tržište nije pročitano ({price.get('text') or '?'})"))
        return out
    mc, liq = _f(pv.get("mcap")), _f(pv.get("liq"))
    dex = str(pv.get("dex") or "").split("/")[0].lower()
    try:
        from rugfilter import collapse
        curves = collapse.CURVES
    except Exception:  # noqa: BLE001
        curves = {"pumpfun", "launchlab", "moonshot", "boop", "believe"}
    if not _f(pv.get("price")) or not liq or dex in curves:
        out.append(("curve", "nema bondanog poola s likvidnošću (krivulja ili nema DexScreener para): uzimaju se bondani"))
        return out
    lb = tcost.liq_block(liq)
    if lb:
        out.append(("liq_low", f"likvidnost: {lb}"))
    if (mc or 0) < MIN_MCAP:
        out.append(("under_30k", f"MC ${mc or 0:,.0f} ispod 30k"))
    return out


def _decided(sig):
    return bool(sig) and sig.get("status") in ("done", "failed") and bool(sig.get("decision"))


def dev_wallet(token, hype_db=None, rug_db=None):
    """The token's dev: hype.db live_launches.creator (PumpPortal), else the newest rug.db report's dev. None."""
    try:
        from live import store as lv
        hc = lv.ro(hype_db)
        if hc is not None:
            try:
                r = hc.execute("SELECT creator FROM live_launches WHERE mint=?", (token,)).fetchone()
            except sqlite3.Error:
                r = None
            finally:
                hc.close()
            if r and r[0]:
                return r[0]
    except Exception:  # noqa: BLE001
        pass
    rc = _ro(rug_db or _rug_db())
    if rc is None:
        return None
    try:
        r = rc.execute("SELECT dev, data FROM rug_reports WHERE mint=? ORDER BY checked_at DESC LIMIT 1",
                       (token,)).fetchone()
    except sqlite3.Error:
        r = None
    finally:
        rc.close()
    if not r:
        return None
    if r[0] and len(str(r[0])) >= 32:
        return str(r[0])
    try:
        d = json.loads(r[1] or "{}") or {}
    except ValueError:
        d = {}
    return ((d.get("dev") or {}).get("wallet")) or None


def top_holders(token, now, cache=None, rug_db=None):
    """[{"owner", "pct"}] of the top 10 holders: the fast_check's RugCheck holders (checks.CACHE, 60 s), else the
    newest rug.db report's top."""
    try:
        from . import checks
        d = (cache or checks.CACHE).get(token, now) or {}
        hs = d.get("holders") or []
        if hs:
            return [{"owner": h.get("owner"), "pct": h.get("pct")} for h in hs[:10] if h.get("owner")]
    except Exception:  # noqa: BLE001
        pass
    rc = _ro(rug_db or _rug_db())
    if rc is None:
        return []
    try:
        r = rc.execute("SELECT data FROM rug_reports WHERE mint=? ORDER BY checked_at DESC LIMIT 1", (token,)).fetchone()
    except sqlite3.Error:
        r = None
    finally:
        rc.close()
    try:
        top = ((json.loads(r[0] or "{}") or {}).get("holders") or {}).get("top") or [] if r else []
    except ValueError:
        top = []
    return [{"owner": h.get("wallet"), "pct": h.get("pct")} for h in top[:10] if h.get("wallet")]


def _sol_usd():
    try:
        from rangedca import trade as rtrade
        return rtrade.sol_usd()
    except Exception:  # noqa: BLE001
        return None


def on_check(xid, path=None, now=None, cache=None, sol_usd=None):
    """The x_call's entry once its fast_check decided (from the check thread, and the tick as backup). Returns the
    entry status (pending | entered | blocked | off | expired)."""
    now = float(now or time.time())
    con = store.connect(path)
    try:
        x = con.execute("SELECT mint, signal_id, xmode, entry_status, submitted_ts FROM x_calls WHERE id=?",
                        (int(xid),)).fetchone()
        if not x:
            return None
        tok, sid, xmode, st, sub = x
        if st not in (None, "pending"):
            return st
        sig = store.one(con, sid) if sid else None
        if not _decided(sig):
            if now - (sub or now) > PENDING_MAX_S:
                con.execute("UPDATE x_calls SET entry_status='expired', entry_why=? WHERE id=?",
                            ("fast_check nije završio u 2 h", int(xid)))
                con.commit()
                return "expired"
            return "pending"
        upd = {"decision": sig.get("decision"), "fast_reason": (sig.get("reason") or "")[:300],
               "ev_pct": sig.get("ev_pct")}
        if xmode == "off":
            upd.update(entry_status="off", entry_why="x_call_scalp isključen: bez papirnatog ulaza")
        else:
            blocks = hard_blocks(sig)
            if blocks:
                upd.update(entry_status="blocked", entry_why="; ".join(f"{k}: {t}" for k, t in blocks)[:300])
            else:
                from trade import cost as tcost
                pv = ((sig.get("checks") or {}).get("res") or {}).get("price", {}).get("values") or {}
                su = sol_usd or _f(pv.get("sol_usd")) or _sol_usd() or SOL_USD_DEFAULT
                stake = STAKE_SOL * su
                liq = _f(pv.get("liq"))
                c = tcost.round_trip(stake, liq)
                hs = top_holders(tok, now, cache)
                upd.update(entry_status="entered", entry_why=None, entry_ts=float(sig.get("decided_ts") or now),
                           mcap0=_f(pv.get("mcap")), price0=_f(pv.get("price")), liq0=liq, stake_usd=round(stake, 2),
                           cost=round(c, 5), dev=dev_wallet(tok), holders=json.dumps(hs) if hs else None)
        cols = ", ".join(f"{k}=?" for k in upd)
        n = con.execute(f"UPDATE x_calls SET {cols} WHERE id=? AND COALESCE(entry_status, 'pending')='pending'",
                        (*upd.values(), int(xid))).rowcount   # the check thread and the tick: the first one writes
        con.commit()
        if not n:
            r = con.execute("SELECT entry_status FROM x_calls WHERE id=?", (int(xid),)).fetchone()
            return r[0] if r else None
        return upd["entry_status"]
    finally:
        con.close()


# ---------- the price path --------------------------------------------------------------------------------------------

def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _rug_db():
    try:
        from rugfilter import collapse
        return collapse._rug_db()
    except Exception:  # noqa: BLE001
        return None


def paths():
    """The cheap price sources' files (each may be missing)."""
    out = {}
    try:
        from live import store as lv
        out["hype"] = lv.HYPE_DB
    except Exception:  # noqa: BLE001
        pass
    try:
        from rangedca import data as rdata
        out["range"] = rdata.db_path()
    except Exception:  # noqa: BLE001
        pass
    try:
        from kol import minute
        out["minute"] = minute.db_path()
    except Exception:  # noqa: BLE001
        pass
    out["rug"] = _rug_db()
    return out


def _snap_events(rows, mcap0, price0, src):
    out = []
    for ts, price, mcap in rows:
        r = (mcap / mcap0) if mcap and mcap0 else (price / price0 if price and price0 else None)
        if r and r > 0:
            out.append((int(ts), r, r, r, src))
    return out


def points(con, token, t0, t1, mcap0, price0, srcs=None, snaps_only=False):
    """[(ts, high, low, close, source)] ratios to the entry within (t0, t1], oldest first (see the module text).
    snaps_only: only the snapshot sources (fast.db, token_pulse, range snaps): the tick's "is there a fresh point?"
    (the candles come ~70 min late, the PumpPortal prints are no snapshot)."""
    srcs = paths() if srcs is None else srcs
    ev = []
    for table, src in (("x_call_px", "x_call_px"), ("px", "fast.db px")):
        try:
            rows = con.execute(f"SELECT ts, price, mcap FROM {table} WHERE token=? AND ts > ? AND ts <= ? ORDER BY ts",
                               (token, int(t0), int(t1))).fetchall()
        except sqlite3.Error:
            rows = []
        ev += _snap_events(rows, mcap0, price0, src)
    for key, table, src in (("hype", "token_pulse", "hype.db token_pulse"), ("range", "snaps", "range.db snaps")):
        c = _ro(srcs.get(key))
        if c is None:
            continue
        try:
            rows = c.execute(f"SELECT ts, price, mcap FROM {table} WHERE token=? AND ts > ? AND ts <= ? ORDER BY ts",
                             (token, int(t0), int(t1))).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            c.close()
        ev += _snap_events(rows, mcap0, price0, src)
    if snaps_only:
        ev.sort(key=lambda e: e[0])
        return ev
    mc = _ro(srcs.get("minute"))
    if mc is not None and price0:
        try:
            from kol import minute
            m0 = int(t0) - int(t0) % 60
            for ts, o, h, lo, cl, _v in minute.candles_for(mc, token, m0 + 60, int(t1)):
                if cl and cl > 0:
                    cap = min(h, max(o, cl) * WICK_X)
                    ev.append((int(ts) + 60, cap / price0, lo / price0, cl / price0, "minute.db call_candles"))
        except Exception:  # noqa: BLE001 - an old minute.db without call_candles
            pass
        finally:
            mc.close()
    hc = _ro(srcs.get("hype"))
    if hc is not None:
        try:
            ref = [p for (p,) in hc.execute("SELECT price_sol FROM live_trades WHERE mint=? AND ts BETWEEN ? AND ? AND "
                                            "price_sol > 0", (token, int(t0) - 120, int(t0) + 60))]
            if ref:
                p0 = statistics.median(ref)
                by = {}
                for ts, p in hc.execute("SELECT ts, price_sol FROM live_trades WHERE mint=? AND ts > ? AND ts <= ? AND "
                                        "price_sol > 0 ORDER BY ts", (token, int(t0), int(t1))):
                    m = int(ts) - int(ts) % 60
                    hi, lo, _c, last = by.get(m, (p, p, p, 0))
                    by[m] = (max(hi, p), min(lo, p), p, ts)
                for m, (hi, lo, cl, last) in sorted(by.items()):
                    ev.append((int(last), hi / p0, lo / p0, cl / p0, "hype.db live_trades"))
        except sqlite3.Error:
            pass
        finally:
            hc.close()
    ev.sort(key=lambda e: e[0])
    return ev


def _near(ev, ts, lo_s, hi_s):
    best = None
    for e in ev:
        d = e[0] - ts
        if lo_s <= d <= hi_s and (best is None or abs(d) < abs(best[0] - ts)):
            best = e
    return best


def measure(ev, t0, cost, done=True):
    """The results of one entry from its events (see the module text); fractions, net of cost."""
    tp_gross = 1 + TP_NET + cost
    sl_ratio = 1 - SL
    best, tp_ts, sl_ts = 1.0, None, None
    inside = [e for e in ev if t0 < e[0] <= t0 + HORIZON_S]
    for ts, hi, lo, _cl, _s in inside:
        if sl_ts is not None:
            break
        if lo <= sl_ratio:   # the stop first, also when the same candle reached the target (cautious)
            sl_ts = ts
            break
        best = max(best, hi)
        if tp_ts is None and hi >= tp_gross:
            tp_ts = ts
    hit = 1 if tp_ts is not None and (sl_ts is None or tp_ts < sl_ts) else (0 if (sl_ts is not None or done) else None)
    p15 = _near(ev, t0 + 900, -90, 180)
    p60 = _near(ev, t0 + HORIZON_S, -180, GRACE_S)
    r15 = (p15[3] - 1 - cost) if p15 else None
    r60 = (p60[3] - 1 - cost) if p60 else None
    if hit == 1:
        net = TP_NET
    elif sl_ts is not None:
        net = -SL - cost
    elif r60 is not None:
        net = r60
    elif inside and done:
        net = inside[-1][3] - 1 - cost
    else:
        net = None
    return {"max_net": round(best - 1 - cost, 5), "r15": None if r15 is None else round(r15, 5),
            "r60": None if r60 is None else round(r60, 5), "hit": hit, "net": None if net is None else round(net, 5),
            "tp_ts": tp_ts, "sl_ts": sl_ts, "n_points": len(inside),
            "sources": sorted({e[4] for e in inside})}


def dump_of(srcs, token, t0, t1, dev, holders, mcap0, price0, ev):
    """{"ts", "who", "via", "low", "low_ts"} of the first dev / top-holder dump in (t0, t1], or None."""
    supply = (mcap0 / price0) if mcap0 and price0 else None
    found = []
    hs = {h["owner"]: h.get("pct") for h in holders or [] if h.get("owner")}
    who = ([dev] if dev else []) + [w for w in hs if w != dev]
    hc = _ro(srcs.get("hype"))
    if hc is not None and who:
        try:
            q = ",".join("?" * len(who))
            for w, ts, tokens in hc.execute(f"SELECT wallet, ts, tokens FROM live_trades WHERE mint=? AND side='sell' "
                                            f"AND ts > ? AND ts <= ? AND wallet IN ({q}) ORDER BY ts",
                                            (token, int(t0), int(t1), *who)):
                share = (tokens / supply) if tokens and supply else None
                lim = DEV_SHARE if w == dev else HOLDER_SHARE
                if share is None or share >= lim:
                    found.append((int(ts), "dev" if w == dev else f"top holder {w[:4]}…{w[-4:]}",
                                  "hype.db live_trades" + (f", {share:.1%} supplyja" if share is not None else "")))
                    break
        except sqlite3.Error:
            pass
        finally:
            hc.close()
    rc = _ro(srcs["rug"] if "rug" in srcs else _rug_db())
    if rc is not None:
        try:
            from rugfilter import collapse
            for ts, data in rc.execute("SELECT checked_at, data FROM rug_reports WHERE mint=? AND checked_at > ? AND "
                                       "checked_at <= ? ORDER BY checked_at", (token, int(t0), int(t1))):
                try:
                    d = json.loads(data or "{}") or {}
                except ValueError:
                    d = {}
                txt = [str(x) for x in (d.get("hard_fails") or []) + (d.get("flags") or []) if x]
                if any(w in t for t in txt for w in collapse.DEV_SELLS):
                    found.append((int(ts), "dev", "rug.db izvještaj (dev je prodao / prebacio)"))
                    break
        except Exception:  # noqa: BLE001
            pass
        finally:
            rc.close()
    rg = _ro(srcs.get("range"))
    if rg is not None:
        try:
            r = rg.execute("SELECT v FROM kv WHERE k=?", (f"hold:{token}",)).fetchone()
            st = json.loads(r[0]) if r and r[0] else {}
            if st.get("why") and t0 < (st.get("checked") or 0) <= t1:
                found.append((int(st["checked"]), "top holderi", f"rangedca/holders: {st['why']}"))
        except (sqlite3.Error, ValueError, TypeError):
            pass
        finally:
            rg.close()
    if not found:
        return None
    ts, w, via = min(found)
    after = [e for e in ev if ts <= e[0] <= t1]
    low = min(after, key=lambda e: e[2]) if after else None
    return {"ts": ts, "who": w, "via": via, "low": round(low[2] - 1, 5) if low else None,
            "low_ts": low[0] if low else None}


# ---------- the tick (run_fast.py) ----------------------------------------------------------------------------------------

def _day_used(con, now):
    day = store.day_of(now)
    used = store.kv_get(con, "dex_xcall_day", {}) or {}
    return day, (used.get("n") or 0) if used.get("day") == day else 0


def fetch_points(con, tokens, now, fetch=None):
    """One DexScreener point per token (batches of DEX_TOKENS) into x_call_px, inside XCALL_DEX_DAY. Returns how
    many tokens were priced."""
    day, n_used = _day_used(con, now)
    priced = 0
    for i in range(0, len(tokens), DEX_TOKENS):
        if n_used >= XCALL_DEX_DAY:
            break
        part = tokens[i:i + DEX_TOKENS]
        try:
            if fetch is None:
                from dexscreener import client
                from .checks import parse_pairs
                got = parse_pairs(client.tokens("solana", part, ttl=30))
            else:
                got = fetch(part) or {}
        except Exception:  # noqa: BLE001 - DexScreener down: the next tick tries again
            got = {}
        n_used += 1
        store.add_cost(con, "dexscreener_xcall", 1, 0, now)
        for t in part:
            m = got.get(t)
            if m and m.get("price"):
                con.execute("INSERT OR IGNORE INTO x_call_px VALUES (?,?,?,?)", (t, int(now), float(m["price"]),
                                                                                  m.get("mcap")))
                priced += 1
    store.kv_put(con, "dex_xcall_day", {"day": day, "n": n_used})
    return priced


def tick(now=None, path=None, fetch=None, srcs=None, log=print):
    """Pending entries, the price points of the open ones, the final measurement. {"pending", "priced", "measured"}."""
    now = float(now or time.time())
    out = {"mode": mode(), "pending": 0, "priced": 0, "measured": 0}
    if out["mode"] == "off":
        return out
    srcs = paths() if srcs is None else srcs
    con = store.connect(path)
    try:
        pend = [i for (i,) in con.execute("SELECT id FROM x_calls WHERE entry_status='pending'").fetchall()]
    finally:
        con.close()
    for xid in pend:
        if on_check(xid, path, now) == "entered":
            out["pending"] += 1
    con = store.connect(path)
    try:
        rows = con.execute("SELECT id, mint, entry_ts, mcap0, price0, cost, dev, holders FROM x_calls WHERE "
                           "entry_status='entered' AND measured=0 ORDER BY id").fetchall()
        need = []
        for xid, tok, t0, mc0, p0, c, dev, hs in rows:
            if now < t0 + HORIZON_S + 60:
                ev = points(con, tok, max(t0, now - PX_EVERY_S - 5), now, mc0, p0, srcs, snaps_only=True)
                if not ev and tok not in need:
                    need.append(tok)
        if need:
            out["priced"] = fetch_points(con, need, now, fetch)
            con.commit()
        for xid, tok, t0, mc0, p0, c, dev, hs in rows:
            if now < t0 + HORIZON_S + GRACE_S:
                continue
            t1 = t0 + HORIZON_S + GRACE_S
            ev = points(con, tok, t0, t1, mc0, p0, srcs)
            m = measure(ev, t0, c or 0.0, done=True)
            try:
                holders = json.loads(hs) if hs else []
            except ValueError:
                holders = []
            d = dump_of(srcs, tok, t0, t0 + HORIZON_S, dev, holders, mc0, p0, ev)
            res = dict(m, dump=d)
            con.execute("UPDATE x_calls SET measured=1, measured_ts=?, max_net=?, r15=?, r60=?, hit=?, net=?, dump_ts=?, "
                        "dump_who=?, dump_low=?, res=? WHERE id=?",
                        (int(now), m["max_net"], m["r15"], m["r60"], m["hit"], m["net"], d["ts"] if d else None,
                         d["who"] if d else None, d["low"] if d else None, json.dumps(res, ensure_ascii=False), xid))
            out["measured"] += 1
        con.commit()
    finally:
        con.close()
    if out["measured"] or out["priced"]:
        log(f"x_call_scalp: izmjereno {out['measured']} ulaza, {out['priced']} tokena s vlastitom DexScreener točkom")
    return out


# ---------- statistics ------------------------------------------------------------------------------------------------

def _pct(x, nd=2):
    return None if x is None else round(x * 100, nd)


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _rows(con, since):
    try:
        cur = con.execute("SELECT id, mint, author, followers, velocity, fol_band, vel_band, cls, submitted_ts, "
                          "entry_status, entry_why, entry_ts, mcap0, cost, measured, max_net, r15, r60, hit, net, "
                          "dump_ts, dump_who, dump_low, decision, post_id FROM x_calls WHERE submitted_ts >= ? "
                          "ORDER BY id DESC", (int(since),))
    except sqlite3.Error:
        return []
    names = [c[0] for c in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def summarize(rows, cls=None):
    """The class statistics of x_calls rows (see the module text)."""
    from trade import cost as tcost
    done = [r for r in rows if r["entry_status"] == "entered" and r["measured"] and r["net"] is not None]
    n = len(done)
    nets = [r["net"] for r in done]
    ev_net = sum(nets) / n if n else None
    gross = [r["net"] + (r["cost"] or 0) for r in done]
    dumps = [r for r in done if r["dump_ts"]]
    blocked = {}
    for r in rows:
        if r["entry_status"] == "blocked":
            k = (r["entry_why"] or "?").split(":")[0][:40]
            blocked[k] = blocked.get(k, 0) + 1
    ok = n >= LIVE_N_MIN and ev_net is not None and ev_net >= LIVE_EV_MIN - 1e-12
    why = None if ok else (f"n = {n}, treba {LIVE_N_MIN}" if n < LIVE_N_MIN else
                           f"EV neto {ev_net * 100:+.2f} % ispod +{LIVE_EV_MIN * 100:g} %")
    fb, _s, vb = (cls or "").partition("/")
    return {"class": cls, "followers_band": fb or None, "velocity_band": vb or None, "calls": len(rows),
            "n": n, "hit_rate": round(sum(1 for r in done if r["hit"] == 1) / n, 3) if n else None,
            "median_net_pct": _pct(_median(nets)), "ev_net_pct": _pct(ev_net),
            "ev_fee_only_pct": _pct(sum(gross) / n - tcost.FEE_ROUND_TRIP) if n else None,
            "median_r15_net_pct": _pct(_median([r["r15"] for r in done])),
            "median_r60_net_pct": _pct(_median([r["r60"] for r in done])),
            "median_max_gain_before_stop_pct": _pct(_median([r["max_net"] for r in done])),
            "dumps": len(dumps), "median_low_after_dump_pct": _pct(_median([r["dump_low"] for r in dumps])),
            "open": sum(1 for r in rows if r["entry_status"] == "entered" and not r["measured"]),
            "pending": sum(1 for r in rows if r["entry_status"] == "pending"),
            "blocked": sum(blocked.values()), "blocked_reasons": blocked,
            "live_record_ok": ok, "live_why": why}


def class_records(now=None, days=30, path=None):
    """{class: {"n", "ev" (net of the fee part only, ui/kandidati's record convention), "ev_net", "hit", "from"}} of
    the measured entries of the last `days` (ui/kandidati.live_eligible). {} without fast.db."""
    now = int(now or time.time())
    con = store.ro(path)
    if con is None:
        return {}
    try:
        rows = _rows(con, now - days * 86400)
    finally:
        con.close()
    out = {}
    for cls in CLASSES:
        s = summarize([r for r in rows if r["cls"] == cls], cls)
        if s["n"]:
            out[cls] = {"n": s["n"], "ev": round(s["ev_fee_only_pct"] / 100, 5), "ev_net": round(s["ev_net_pct"] / 100, 5),
                        "hit": s["hit_rate"], "median_net": s["median_net_pct"], "live_record_ok": s["live_record_ok"],
                        "from": f"fast.db x_calls ({cls}, x_call_scalp: +10 % neto prije -8 %, 60 min, {days} dana)"}
    return out


def live_gate(classes, records):
    """12.11. (owner): an x_call candidate is live only when the class of one of its calls has n >= 10 and EV net >=
    +3 %. {"ok", "why", "class", "n", "ev_net_pct"}."""
    best = None
    for cls in dict.fromkeys(c for c in classes or () if c):
        rec = (records or {}).get(cls) or {}
        n, e = int(rec.get("n") or 0), rec.get("ev_net")
        if n >= LIVE_N_MIN and e is not None and e >= LIVE_EV_MIN - 1e-12:
            return {"ok": True, "why": None, "class": cls, "n": n, "ev_net_pct": _pct(e)}
        if best is None or (n, e if e is not None else -9) > (best[1], best[2] if best[2] is not None else -9):
            best = (cls, n, e)
    if best is None:
        return {"ok": False, "why": "samo papir: x_call bez razreda autora", "class": None, "n": 0, "ev_net_pct": None}
    cls, n, e = best
    why = (f"samo papir: x_call razred {cls} ima n = {n} izmjerenih ulaza, treba {LIVE_N_MIN}" if n < LIVE_N_MIN else
           f"samo papir: x_call razred {cls} EV neto {e * 100:+.2f} % ispod +{LIVE_EV_MIN * 100:g} %")
    return {"ok": False, "why": why, "class": cls, "n": n, "ev_net_pct": _pct(e)}


def kandidati_rows(now=None, window=3600, path=None):
    """[{"token", "ts", "author", "followers", "class", "velocity", "post_id", "mcap", "x_call_id", "entry"}] of the
    X calls Grok sent in the last `window` (ui/kandidati source x_call), newest first."""
    now = int(now or time.time())
    con = store.ro(path)
    if con is None:
        return []
    try:
        rows = _rows(con, now - window)
    finally:
        con.close()
    return [{"token": r["mint"], "ts": int(r["submitted_ts"]), "author": r["author"], "followers": r["followers"],
             "class": r["cls"], "velocity": r["velocity"], "post_id": r["post_id"], "mcap": r["mcap0"],
             "x_call_id": r["id"], "entry": r["entry_status"]} for r in rows]


def _int(x, default, lo, hi):
    try:
        if isinstance(x, bool):
            raise ValueError
        return max(lo, min(hi, int(x)))
    except (TypeError, ValueError):
        return default


def stats(followers_band=None, velocity_band=None, cls=None, days=None, limit=None, now=None, path=None):
    """MCP get_x_call_stats."""
    now = int(now or time.time())
    days = _int(days if days not in (None, "") else 30, 30, 1, 90)
    lim = _int(limit if limit not in (None, "") else 20, 20, 0, 100)
    fb = (followers_band or "").strip() or None
    vb = (velocity_band or "").strip().lower() or None
    c = (cls or "").strip() or None
    if fb and fb not in FOL_NAMES:
        return {"error": f"followers_band must be one of {', '.join(FOL_NAMES)}"}
    if vb and vb not in VELOCITY_BANDS:
        return {"error": f"velocity_band must be one of {', '.join(VELOCITY_BANDS)}"}
    if c and c not in CLASSES:
        return {"error": f"class must be one of {', '.join(CLASSES)} (followers/velocity)"}
    keep = [k for k in CLASSES if (not fb or k.startswith(fb + "/")) and (not vb or k.endswith("/" + vb))
            and (not c or k == c)]
    con = store.ro(path)
    rows, dex = [], {}
    if con is not None:
        try:
            rows = _rows(con, now - days * 86400)
            day, n_used = _day_used(con, now)
            dex = {"dexscreener_requests_today": n_used, "cap": XCALL_DEX_DAY,
                   "fast_check_costs_today": store.costs(con, day)}
        finally:
            con.close()
    rows = [r for r in rows if r["cls"] in keep]
    out = {"ts": now, "mode": mode(), "days": days,
           "filter": {"followers_band": fb, "velocity_band": vb, "class": c},
           "classes": [summarize([r for r in rows if r["cls"] == k], k) for k in keep],
           "all": summarize(rows, None), "thresholds": THRESHOLDS,
           "live_rule": (f"a class is a live record with n >= {LIVE_N_MIN} and EV net >= +{LIVE_EV_MIN * 100:g} % "
                         "(ui/kandidati live_eligible, source x_call); x_call_scalp itself never trades"),
           "definitions": DEFINITIONS, "price_sources": SOURCES_TEXT, "cost": dex}
    out["all"].pop("class", None)
    out["recent"] = [{"x_call_id": r["id"], "mint": r["mint"], "author": r["author"], "followers": r["followers"],
                      "velocity": r["velocity"], "class": r["cls"], "post_id": r["post_id"],
                      "submitted_ts": r["submitted_ts"], "fast_check": r["decision"], "entry": r["entry_status"],
                      "entry_why": r["entry_why"], "entry_mcap_usd": r["mcap0"], "cost_pct": _pct(r["cost"]),
                      "measured": bool(r["measured"]), "max_gain_before_stop_pct": _pct(r["max_net"]),
                      "r15_net_pct": _pct(r["r15"]), "r60_net_pct": _pct(r["r60"]), "hit": r["hit"],
                      "net_pct": _pct(r["net"]),
                      "dump": ({"ts": r["dump_ts"], "who": r["dump_who"], "low_after_pct": _pct(r["dump_low"])}
                               if r["dump_ts"] else None)} for r in rows[:lim]]
    return out


def ev_rows(now, mode, path=None, log=print, days=7):
    """events/evreport: x_call_scalp's last `days` as rows of the EV table, one per author class with a measured
    entry plus the total; the note carries today's own DexScreener requests (CLAUDE.md: cost per source and what it
    brought)."""
    d = stats(days=days, limit=0, now=now, path=path)
    cost = d.get("cost") or {}
    note = (f"vlastiti DexScreener zahtjevi danas {cost.get('dexscreener_requests_today', 0)} / {cost.get('cap')}; "
            f"fast_check trošak danas {cost.get('fast_check_costs_today') or {}}")
    rows = []
    for c in [dict(d["all"], **{"class": "sve"})] + [c for c in d["classes"] if c["n"]]:
        if not c["calls"]:
            continue
        rows.append({"flag": FLAG, "phase": mode, "part": f"x_call:{c['class']}", "n": c["calls"],
                     "n_outcomes": c["n"], "hit_rate": c["hit_rate"], "avg_pnl_pct": c["median_net_pct"],
                     "ev_pct": c["ev_net_pct"], "max_dd_pct": None, "baseline_ev_pct": None, "baseline_n": None,
                     "delta_ev_pct": None, "note": note if c["class"] == "sve" else (c["live_why"] or "live zapis: da"),
                     "proposal": None})
    return rows
