"""The live entries of the source consensus strategy (flag konsenzus, trade/settings). Runs inside league/auto.loop
(run_ui.py, league.db's only writer), right after the fast path; the copy loop's wake-up on a fresh call / wallet buy
brings it within a second, else every pass (at most every RUN_EVERY_S).

  off / shadow   no entry (the research still runs and is shown); open konsenzus trades keep their exits
  paper          the DEMO account PAPER_USER (autopilot-paper; run_trade.py never mirrors it) enters whenever the
                 CURRENTLY best candidate (konsenzus.db kv best, written by run_konsenzus.py after a deploy and
                 nightly) fires on a fresh signal: a call of a selected X influencer / Telegram channel (kol.db calls,
                 tg.db posts) or a buy of a selected wallet (hype.db chain_trades), with the candidate's rule (one
                 selected group; 2+ independent groups within W min; a wallet + an X/Telegram group)
  real money     ON TOP of the demo entry, the same signal also opens on the real account LEAGUE_USER (source
                 "konsenzus ...", run_trade mirrors it) ONLY while konsenzus/gate.real_refusal is None: the owner's
                 switch pravi_novac_izvori on AND the candidate's holdout proof. run_trade asks the gate and the hard
                 rules again on the real buy; trade/executor holds it to IZVORI_CAPS. pravi_novac_sve never routes
                 these signals (it has nothing to do with this strategy).
Hard rules on every entry (demo too): bonded only (a DexScreener pair, never the pump.fun curve), MC >= 30k, liquidity
>= 15k and not above the MC, the pool >= 3 % of the MC, not rugged, not in the rug archive, the account not holding the
token, the first entry per token only (konsenzus_trades is unique per account and token), the signal at most FRESH_S
old. Exit: the candidate's exit (konsenzus/research.EXITS): the lot's own stop and time stop (league/auto tpsl, every
second) and a plan (league/exitplan) for the take profit share, break-even and trailing: on the demo account a
quick-profit-tagged plan (it executes there 24/7), on the real account a switch-tagged plan (it executes there).
league.db konsenzus_trades: one row per (account, token), closed with the sum of its lots.
"""
import os
import sqlite3
import time

FLAG = "konsenzus"
SRC = "konsenzus"
FRESH_S = 180
RUN_EVERY_S = 15
DEMO_SOL = 0.1
DEMO_MAX_OPEN = 15
DEMO_PER_DAY = 60
REAL_MAX_OPEN = 5
REAL_PER_DAY = 30
MAX_WINDOW_MIN = 120
STABLE = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
          "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
SCHEMA = """CREATE TABLE IF NOT EXISTS konsenzus_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, cand TEXT, why TEXT, fire_ts INTEGER,
    opened_ts INTEGER, trade_id INTEGER, plan_id INTEGER, size_usd REAL, entry_px REAL, entry_mcap REAL, liq REAL,
    status TEXT, closed_ts INTEGER, pnl_usd REAL, ret REAL, exit_reason TEXT, UNIQUE (user, token));
CREATE INDEX IF NOT EXISTS konsenzus_trades_status ON konsenzus_trades (status, user);"""
_LAST = {"ts": 0.0}
_TRIED = {}   # (user, token) -> ts of an entry that could not be taken (logged once an hour)


def ensure(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='konsenzus_trades'").fetchone() is None:
        con.executescript(SCHEMA)


def mode():
    try:
        from trade import settings
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def _ok(tok):
    return bool(tok) and 32 <= len(tok) <= 50 and tok not in STABLE


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


# ---------- signals --------------------------------------------------------------------------------------------------

def read_signals(now, window_s, paths=None):
    """[{ts, token, src, kind}] of the last window_s: X / Telegram calls (kol.db calls kind 'call', tg.db posts that are
    not forwards) and wallet buys (hype.db chain_trades). Read-only, never raises."""
    from konsenzus.research import norm
    if paths is None:
        from league import copy as lcopy
        paths = lcopy._paths()
    since = int(now - window_s)
    out = []
    kc = _ro(paths.get("kol"))
    for tok, ts, h in _q(kc, "SELECT token, ts, handle FROM calls WHERE kind='call' AND ts >= ?", (since,)):
        if h and not str(h).startswith("w:") and _ok(tok) and ts:
            out.append({"ts": int(ts), "token": tok, "src": norm(h), "kind": "tg" if str(h).startswith("tg:") else "x"})
    tc = _ro(paths.get("tg"))
    for ch, ts, cas, fwd in _q(tc, "SELECT channel, ts, cas, fwd_from FROM posts WHERE ts >= ? AND cas != ''", (since,)):
        if fwd or not ts:
            continue
        for ca in (cas or "").split(","):
            if _ok(ca.strip()):
                out.append({"ts": int(ts), "token": ca.strip(), "src": norm("tg:" + str(ch)), "kind": "tg"})
    hc = _ro(paths.get("hype"))
    for w, m, ts in _q(hc, "SELECT wallet, mint, ts FROM chain_trades WHERE side='buy' AND ts >= ?", (since,)):
        if w and _ok(m) and ts:
            out.append({"ts": int(ts), "token": m, "src": norm(w), "kind": "wallet"})
    for c in (kc, tc, hc):
        if c is not None:
            c.close()
    return out


def earlier(src, kind, token, ts, paths=None):
    """True when this source already signalled this token before ts (more than a minute earlier): the research counts
    only a source's FIRST call / buy of a token, so a repeat is no signal. Never raises (unreadable: False)."""
    if paths is None:
        from league import copy as lcopy
        paths = lcopy._paths()
    cut = int(ts) - 60
    if kind == "wallet":
        con, sql, args = _ro(paths.get("hype")), ("SELECT 1 FROM chain_trades WHERE mint=? AND wallet=? AND "
                                                  "side='buy' AND ts < ? LIMIT 1"), (token, src, cut)
        hit = bool(_q(con, sql, args))
    else:
        con = _ro(paths.get("kol"))
        hit = bool(_q(con, "SELECT 1 FROM calls WHERE token=? AND LOWER(handle) IN (?, ?) AND kind='call' AND ts < ? "
                           "LIMIT 1", (token, src, "@" + src, cut)))
        if not hit and kind == "tg":
            if con is not None:
                con.close()
            con = _ro(paths.get("tg"))
            hit = bool(_q(con, "SELECT 1 FROM posts WHERE LOWER(channel)=? AND cas LIKE ? AND ts < ? LIMIT 1",
                          (src[3:], f"%{token}%", cut)))
    if con is not None:
        con.close()
    return hit


def decide(spec, sigs, now, fresh_s=FRESH_S):
    """[(token, fire ts, why, group ids)] the candidate fires on now (pure): its selection (spec["selection"]: members
    {source: group}, any = every source counts) and its rule; only fires at most fresh_s old."""
    sel = (spec or {}).get("selection") or {}
    members = sel.get("members") or {}
    anyg = bool(sel.get("any"))
    fam, params = spec.get("family"), spec.get("params") or {}
    first = {}   # (group, token) -> (ts, kind, src)
    for s in sorted(sigs, key=lambda s: s["ts"]):
        g = members.get(s["src"])
        if g is None:
            if not anyg:
                continue
            g = s["src"]
        if fam == "S4" and s["kind"] != "tg":
            continue
        first.setdefault((g, s["token"]), (s["ts"], s["kind"], s["src"]))
    by_tok = {}
    for (g, tok), (ts, kind, src) in first.items():
        by_tok.setdefault(tok, []).append((ts, g, kind, src))
    out = []
    for tok, xs in by_tok.items():
        xs.sort()
        fire = None
        if fam in ("S1", "S4"):
            ts, g, kind, src = xs[0]
            fire = (ts, f"{src}", [g], (src, kind))
        else:
            w = int(params.get("w") or 30) * 60
            for i, (ts, g, kind, src) in enumerate(xs):
                prev = [p for p in xs[:i] if ts - p[0] <= w and p[1] != g]
                if fam == "S3":
                    mine = kind == "wallet"
                    prev = [p for p in prev if (p[2] == "wallet") != mine]
                if prev:
                    fire = (ts, f"{prev[0][3]} + {src}", [prev[0][1], g], (src, kind))
                    break
        if fire and 0 <= now - fire[0] <= fresh_s:
            out.append((tok, fire[0], fire[1], fire[2], fire[3]))
    return out


# ---------- entries ------------------------------------------------------------------------------------------------

def guards(tok, mq):
    """Why this token may not be entered on this quote (Croatian), or None."""
    from league import copy as lcopy
    from trade import cost
    if not mq or not mq[0]:
        return "nema žive cijene"
    _price, liq, _url, mcap = mq[:4]
    if lcopy._bonding_curve(mq) or lcopy._dex_pair_empty(mq):
        return "token je još na pump.fun krivulji ili bez DexScreener para (uzimaju se bondani)"
    if (mcap or 0) < lcopy.CFG["min_mcap"]:
        return "MC ispod 30k"
    why = cost.liq_block(liq)
    if why:
        return why
    if mcap and liq and liq > mcap:
        return "lažni pool (likvidnost veća od MC-a)"
    if mcap and liq and liq < lcopy.CFG["min_liq_mcap"] * mcap:
        return f"likvidnost samo {liq / mcap:.1%} MC-a"
    try:
        from rangedca import trade as rtrade
        why = rtrade.archived_why(tok)
    except Exception:  # noqa: BLE001 - the archive unreadable: the collapse check below decides
        why = None
    if why:
        return why
    col = lcopy._rugged(tok, mcap, liq)
    if col:
        return f"rug ({col['text']})"
    return None


def _day_start(now):
    from league import copy as lcopy
    return lcopy._day_start(int(now))


def plan_of(spec, user, tp_pct):
    """The exit plan (league/exitplan.set_plan shape) of the candidate's exit for one account."""
    ex = (spec or {}).get("exit_params") or {}
    sl, share, trail, tmax = float(ex.get("sl", 10)), float(ex.get("share", 0.5)), float(ex.get("trail") or 0), \
        float(ex.get("tmax", 1440))
    plan = {"accounts": [user], "take_profits": [{"at_pct": round(tp_pct, 2), "sell_share": min(1.0, share)}],
            "stop": {"at_pct": -sl},
            "reason": f"konsenzus {spec.get('key')}: {spec.get('exit_words') or ''}"[:200]}
    if share < 0.999:
        plan["breakeven_after_tp1"] = True
        if trail:
            plan["trailing"] = {"activate_pct": round(tp_pct, 2), "trail_pct": trail}
    if tmax < 1440:
        plan["time_stop"] = {"after_min": int(tmax), "if_pnl_below_pct": 1000}
    return plan


def tp_of(spec, size_usd, liq):
    """TP1 as a price move in percent: the exit's own when it is gross (E), else its net target + the round trip."""
    from trade import cost
    ex = (spec or {}).get("exit_params") or {}
    tp = float(ex.get("tp1", 15))
    if spec.get("tp_gross"):
        return tp
    return tp + cost.round_trip(size_usd, liq) * 100


def enter(con, spec, user, tok, fire_ts, why, mq, now, sol):
    """One entry on `user`; (text or None, why not or None)."""
    from league import auto, copy as lcopy, exitplan
    from league import store as lstore
    from trade import settings
    if con.execute("SELECT 1 FROM konsenzus_trades WHERE user=? AND token=?", (user, tok)).fetchone():
        return None, None   # the first entry per token only
    if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone():
        return None, "račun već drži token: ne udvostručuje se"
    real = user == settings.LEAGUE_USER
    cap_open, cap_day = (REAL_MAX_OPEN, REAL_PER_DAY) if real else (DEMO_MAX_OPEN, DEMO_PER_DAY)
    n_open = con.execute("SELECT COUNT(*) FROM konsenzus_trades WHERE user=? AND status='open'", (user,)).fetchone()[0]
    if n_open >= cap_open:
        return None, f"već {n_open} otvorenih konsenzus tradeova (strop {cap_open})"
    n_day = con.execute("SELECT COUNT(*) FROM konsenzus_trades WHERE user=? AND opened_ts >= ?",
                        (user, _day_start(now))).fetchone()[0]
    if n_day >= cap_day:
        return None, f"dnevni strop konsenzus ulaza ({cap_day}) potrošen"
    why_not = guards(tok, mq)
    if why_not:
        return None, why_not
    price, liq, _url, mcap = mq[:4]
    from veliki import symbols   # 16.11.: run_ui's quote has no symbol; the mint's prefix only as the last resort
    sym = symbols.resolve(tok, mq[4] if len(mq) > 4 else None) or tok[:6]
    size_usd = DEMO_SOL * sol
    src = f"{SRC} {spec.get('key')}: {why}"[:200]
    from trade import capgate   # 15.11. (vlasnik): MC >= 5M, below only the demo's moonshot (half, tagged)
    gw, src, size_usd = capgate.check(tok, mcap, src, user, size_usd, now, sol=sol, liq=liq, symbol=sym)
    if gw:
        return None, gw
    try:
        tid = lstore.buy(con, user, tok, sym, size_usd, price, liq, src, None, mcap)
    except ValueError as e:
        return None, f"ulaz nije prošao ({e})"
    ex = spec.get("exit_params") or {}
    sl, tmax = float(ex.get("sl", 10)), float(ex.get("tmax", 1440))
    try:   # the lot's own stop and time stop: league/auto checks them every second (a server-side stop always)
        auto.set_auto(con, user, tid, "tpsl", "", f"-{sl:g}%", hold_s=int(min(tmax, 1440) * 60))
    except ValueError as e:
        print(f"konsenzus {tok[:6]}: stop lota nije postavljen ({e})", flush=True)
    tp = tp_of(spec, size_usd, liq)
    client = (f"{exitplan.SWITCH_SRC} {exitplan.QUICK_TAG} {SRC} {spec.get('key')}" if real
              else f"{exitplan.QUICK_SRC} {SRC} {spec.get('key')}")
    plan_id = None
    try:
        if exitplan.active(con, tok) is None:
            plan_id = exitplan.set_plan(con, tok, plan_of(spec, user, tp), exitplan.sl_floor(), client=client,
                                        now=int(now))["plan_id"]
        else:   # one plan per token: join it with this strategy's own numbers
            plan_id = exitplan.quick_cover(con, tok, user, now=int(now), liq=liq, client=f"{SRC} {spec.get('key')}",
                                           own={"stop_pct": -sl, "trail_pct": float(ex.get("trail") or 8),
                                                "tp_max_pct": tp})
    except (ValueError, sqlite3.Error) as e:
        print(f"konsenzus {tok[:6]}: plan izlaza nije postavljen ({e}); vrijedi stop lota", flush=True)
    row = con.execute("SELECT opened_ts, size_usd, entry_px FROM trades WHERE id=?", (tid,)).fetchone()
    con.execute("INSERT OR IGNORE INTO konsenzus_trades (user, token, symbol, cand, why, fire_ts, opened_ts, trade_id, "
                "plan_id, size_usd, entry_px, entry_mcap, liq, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'open')",
                (user, tok, sym, spec.get("key"), why[:300], int(fire_ts), row[0], tid, plan_id, row[1], row[2], mcap,
                 liq))
    con.commit()
    lcopy.wake()
    return (f"konsenzus {'PRAVI' if real else 'demo'} ulaz {sym} ({spec.get('key')}: {why[:80]}) "
            f"{DEMO_SOL:g} SOL na MC ${mcap or 0:,.0f}, signal prije {int(now - fire_ts)} s"), None


def run_once(con, market_fn=None, now=None, spec=None, sigs=None, sol=None, force=False, check_earlier=None):
    """One pass: the closed rows, then the entries. [(user, text)]."""
    now = int(now or time.time())
    ensure(con)
    done = []
    if con.execute("SELECT 1 FROM konsenzus_trades WHERE status='open' LIMIT 1").fetchone():
        sync_closed(con)
    if mode() not in ("paper", "live"):
        return done
    if not force and time.monotonic() - _LAST["ts"] < RUN_EVERY_S:
        from league import copy as lcopy
        if not lcopy.woke_since(time.time() - RUN_EVERY_S):
            return done
    _LAST["ts"] = time.monotonic()
    if spec is None:
        from konsenzus import store
        spec = store.best()
    if not spec or not (spec.get("selection") or {}).get("members"):
        return done
    window = max(int((spec.get("params") or {}).get("w") or 0), 0) * 60 + FRESH_S
    sigs_given = sigs
    sigs = sigs if sigs is not None else read_signals(now, min(window, MAX_WINDOW_MIN * 60 + FRESH_S))
    from trade import settings
    fires = [f for f in decide(spec, sigs, now) if ("*", f[0]) not in _TRIED and not con.execute(
        "SELECT 1 FROM konsenzus_trades WHERE user=? AND token=?", (settings.PAPER_USER, f[0])).fetchone()]
    if not fires:
        return done
    if check_earlier is None:
        check_earlier = sigs_given is None
    if check_earlier:   # a repeat call / buy of the firing source is no signal (the research counts the first only)
        keep = []
        for f in fires:
            if earlier(f[4][0], f[4][1], f[0], f[1]):
                _TRIED[("*", f[0])] = now
                print(f"konsenzus {f[0][:6]}: {f[4][0][:12]} ga je već javio ranije (ponovljeni signal), preskačem",
                      flush=True)
            else:
                keep.append(f)
        fires = keep
    from konsenzus import gate
    real_why = gate.real_refusal(spec)
    users = [settings.PAPER_USER] + ([settings.LEAGUE_USER] if real_why is None else [])
    fires = [f for f in fires if ("*", f[0]) not in _TRIED and any((u, f[0]) not in _TRIED for u in users)]
    if not fires:
        return done
    if sol is None:
        from rangedca import trade as rtrade
        sol = rtrade.sol_usd()
    if not sol:
        return done
    from league import copy as lcopy
    mk = (market_fn or lcopy.market)(sorted({f[0] for f in fires})) or {}
    for tok, fire_ts, why, _groups, _first in fires:
        for user in users:
            if (user, tok) in _TRIED:
                continue
            text, why_not = enter(con, spec, user, tok, fire_ts, why, mk.get(tok), now, sol)
            if text:
                done.append((user, text))
            elif why_not:
                _TRIED[(user, tok)] = now
                print(f"konsenzus {tok[:6]} ({user}): nije kupljen ({why_not})", flush=True)
    for k in [k for k, ts in _TRIED.items() if now - ts > 3600]:
        _TRIED.pop(k, None)
    return done


def sync_closed(con):
    """Close the konsenzus_trades rows whose lots are all sold: PnL = the sum of every closed row of that entry."""
    for kid, user, tok, tid, size in con.execute(
            "SELECT id, user, token, trade_id, size_usd FROM konsenzus_trades WHERE status='open'").fetchall():
        t = con.execute("SELECT status, opened_ts, source, closed_ts, exit_rule FROM trades WHERE id=?", (tid,)).fetchone()
        if not t or t[0] != "closed":
            continue
        if con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND opened_ts=? AND source=? AND status='open'",
                       (user, tok, t[1], t[2])).fetchone():
            continue   # a part is still held (a plan's partial sale is its own closed row)
        pnl = con.execute("SELECT COALESCE(SUM(pnl_usd), 0) FROM trades WHERE user=? AND token=? AND opened_ts=? AND "
                          "source=? AND status='closed'", (user, tok, t[1], t[2])).fetchone()[0] or 0.0
        con.execute("UPDATE konsenzus_trades SET status='closed', closed_ts=?, pnl_usd=?, ret=?, exit_reason=? WHERE id=?",
                    (t[3], pnl, pnl / size if size else None, t[4], kid))
    con.commit()


def demo_stats(lcon=None):
    """{"n", "open", "wins", "pnl_usd", "ev_pct", "ci90_lo_pct"} of the demo account's closed konsenzus trades, net of
    the calibrated cost (trade/cost.demo_adjust); also the real account's counts."""
    from league import store as lstore
    from trade import cost, edge, settings
    own = lcon is None
    rows, n_open, real = [], 0, {"n": 0, "open": 0, "pnl_usd": 0.0}
    try:
        if own:
            lcon = _ro(lstore.DB)
        if lcon is not None:
            rows = lcon.execute("SELECT pnl_usd, ret FROM konsenzus_trades WHERE user=? AND status='closed'",
                                (settings.PAPER_USER,)).fetchall()
            n_open = lcon.execute("SELECT COUNT(*) FROM konsenzus_trades WHERE user=? AND status='open'",
                                  (settings.PAPER_USER,)).fetchone()[0]
            r = lcon.execute("SELECT COUNT(*), SUM(status='open'), COALESCE(SUM(pnl_usd), 0) FROM konsenzus_trades "
                             "WHERE user=?", (settings.LEAGUE_USER,)).fetchone()
            real = {"n": r[0] or 0, "open": r[1] or 0, "pnl_usd": round(r[2] or 0, 2)}
    except sqlite3.Error:
        pass
    finally:
        if own and lcon is not None:
            lcon.close()
    adj = cost.demo_adjust()
    rets = [r + adj for _p, r in rows if r is not None]
    s = edge.ev_stats(rets)
    return {"n": len(rows), "open": n_open, "wins": sum(1 for p, _r in rows if (p or 0) > 0),
            "pnl_usd": round(float(sum(p or 0 for p, _r in rows)), 2),
            "ev_pct": round(s["ev"] * 100, 2) if s["ev"] is not None else None,
            "ci90_lo_pct": round(s["lo90"] * 100, 2) if s["lo90"] is not None else None, "real": real}
