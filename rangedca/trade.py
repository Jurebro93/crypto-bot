"""range_dca on the Autopilot's demo accounts (flag range_dca; league.db's only writer, run_ui.py, runs this):

  run_once    every pass of league/auto.loop (20 s): lot 1 and lot 2 entries from the ranges run_range.py computed
  exits_once  every second in league/auto.fast_loop: the round's exits (rules.exit_step) and the give-ups

Modes (league/flags): off nothing new (rounds already open keep their exits: a stop is never dropped; looked for once
a minute); shadow: the real account LEAGUE_USER only logs what it would buy (league.db shadow_decisions); paper: the
demo account PAPER_USER trades (run_trade.py never mirrors it), LEAGUE_USER logs; live: both trade, and LEAGUE_USER
only while rangedca/gate.refusal() is None (>= 20 closed paper rounds with EV > 0), checked again every minute.
11.11.: a token only the market watchlist or an event topic brought (ranges.src market / event, rangedca/market.py)
is entered only by the demo account PAPER_USER and only while its own flag (range_market / event_tokens) is paper;
the real account never buys one and never logs one (allowed()).

A round = lot 1 (+ lot 2) until everything is sold; table range_rounds (league.db) keeps its levels (frozen at the
entry; the take-profit levels follow the newest range, the stop only tightens), its state (tp1, top touched, peak)
and at the end its PnL from the closed trades (partial sales included). The lots are ordinary demo trades with
source "range lot 1" / "range lot 2" and no auto TP/SL of their own; run_trade.py mirrors LEAGUE_USER's like any
other trade (lot 2 as one more lot of the same position, held by every real limit).

Limits (spec 3): a lot is trade settings size_sol (in USD at the current SOL price), lot 1 + lot 2 at most
dca_token_cap SOL; on the demo account max_open counts its open range rounds and max_sol_per_day its range lots of
the Zagreb day (run_trade.py holds the real account to every real limit again). Grok does not trade through this; a
Grok trade in the same token goes through ui/grokauto and its own limits, and Grok may TIGHTEN a range position's
exits with set_exit_plan (league/exitplan; "accounts": ["autopilot-paper"] keeps the plan off the real account).
"""
import json
import os
import sqlite3
import time

from league import store
from . import data, gate, market, rules

FLAG = "range_dca"
SRC1, SRC2 = "range lot 1", "range lot 2"
RANGE_FRESH_S = 15 * 60     # a range computed longer ago is not traded
METRICS_FRESH_S = 4 * 60    # the 5-minute numbers (buys share, volume, change) at most this old at an entry
STALE_S = 60                # league/exitplan.STALE_S: an older price fires only the hard stop
RNG_TTL_S = 10              # the 1-s exit loop reads range.db at most this often
OFF_CHECK_S = 60
SHADOW_EVERY_S = 20 * 60
EXIT_RULE = {"tp1": "tp", "top": "tp", "trailing": "tp", "stop": "sl", "time": "time", "odustajanje": "sl"}
REASON_HR = {"tp1": "pola u gornjoj zoni", "top": "ostatak na vrhu raspona", "trailing": "trailing 10 % od vrha",
             "stop": "tvrdi stop (range_low_low × 0,85)", "time": "6 h bez gornje zone, izlaz na nuli",
             "odustajanje": "odustajanje"}

SCHEMA = """CREATE TABLE IF NOT EXISTS range_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, token TEXT, symbol TEXT, opened_ts INTEGER, closed_ts INTEGER,
    status TEXT, lot1_id INTEGER, lot2_id INTEGER, lot1_sol REAL, lot2_sol REAL, entry_mc REAL, lot2_mc REAL,
    score REAL, levels TEXT, state TEXT, cost_usd REAL, pnl_usd REAL, ret REAL, exit_reason TEXT);
CREATE INDEX IF NOT EXISTS range_rounds_status ON range_rounds (status, user, token);"""

_CACHE = {"rng_at": 0.0, "rng": {}, "off_at": 0.0, "off_open": False, "lim_at": 0.0, "lim": None, "gate_log": 0.0}
_SHADOWED = {}


def ensure(con):
    """The table when missing (executescript commits: only then, never in the middle of a pass)."""
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='range_rounds'").fetchone() is None:
        con.executescript(SCHEMA)


def _flags():
    from league import flags
    return flags


def mode():
    return _flags().mode(FLAG)


def roles(m, now=None):
    """(accounts that trade, accounts that only log) in mode m. LEAGUE_USER trades only past the live gate."""
    from trade import settings as ts
    fl = _flags()
    act = [u for u in fl.autopilot_users() if fl.applies(FLAG, u, m)]
    sh = [u for u in fl.autopilot_users() if fl.shadowing(FLAG, u, m)]
    if ts.LEAGUE_USER in act:
        why = gate.refusal(now=now, cached=True)
        if why:
            act.remove(ts.LEAGUE_USER)
            sh.append(ts.LEAGUE_USER)
            t = now or time.time()
            if t - _CACHE["gate_log"] > 3600:
                _CACHE["gate_log"] = t
                print(f"range_dca live: pravi račun ne trguje ({why}); samo zapis u sjeni", flush=True)
    return act, sh


def limits(now=None):
    """size_sol, max_sol_per_day, max_open, dca_token_cap (trade settings over trade/config.json), once a minute."""
    now = now or time.time()
    if _CACHE["lim"] is None or now - _CACHE["lim_at"] > 60:
        from trade import settings as ts
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trade", "config.json")) as f:
            cfg = json.load(f)
        try:
            tcon = sqlite3.connect(f"file:{ts.DB}?mode=ro", uri=True, timeout=5)
            try:
                cfg = ts.merged(cfg, tcon)
            finally:
                tcon.close()
        except sqlite3.Error:
            cfg.setdefault("dca_token_cap", ts.DCA_TOKEN_CAP)
        _CACHE["lim"] = {"size_sol": float(cfg.get("size_sol") or 0.1), "max_sol_per_day": float(cfg.get("max_sol_per_day") or 1.0),
                         "max_open": int(cfg.get("max_open") or 5),
                         "dca_token_cap": float(cfg.get("dca_token_cap") or ts.DCA_TOKEN_CAP)}
        _CACHE["lim_at"] = now
    return _CACHE["lim"]


def sol_usd():
    try:
        from trade import equity
        return (equity.rates() or {}).get("sol_usd")
    except Exception:  # noqa: BLE001
        return None


def _day_start(now):
    from league import copy
    return copy._day_start(int(now))


def rounds(con, status="open", user=None, token=None):
    ensure(con)
    sql, args = "SELECT * FROM range_rounds WHERE status=?", [status]
    if user:
        sql += " AND user=?"
        args.append(user)
    if token:
        sql += " AND token=?"
        args.append(token)
    cur = con.execute(sql + " ORDER BY id", args)
    cols = [c[0] for c in cur.description]
    out = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        d["levels"], d["state"] = json.loads(d["levels"] or "{}"), json.loads(d["state"] or "{}")
        out.append(d)
    return out


def stop_px(con, user, token):
    """The hard stop of user's open range round in token (league/exitplan asks it), None when there is none."""
    try:
        r = con.execute("SELECT levels FROM range_rounds WHERE status='open' AND user=? AND token=?", (user, token)).fetchone()
    except sqlite3.Error:
        return None
    if not r:
        return None
    return (json.loads(r[0] or "{}") or {}).get("stop_px")


def _ranges(now, force=False, tokens=None):
    """The ranges of these tokens (the open rounds'), re-read at most every RNG_TTL_S. 11.11.: only those tokens,
    never every range of the day (the market watchlist keeps ~400; the 1-s exit loop needs a handful)."""
    key = tuple(sorted(tokens)) if tokens is not None else None
    if force or now - _CACHE["rng_at"] > RNG_TTL_S or _CACHE.get("rng_key") != key:
        _CACHE["rng"] = ({} if tokens is not None and not tokens else
                         data.read_ranges(since=now - 86400, tokens=list(key) if key is not None else None))
        _CACHE["rng_at"] = now
        _CACHE["rng_key"] = key
    return _CACHE["rng"]


def allowed(rng, user, now=None):
    """May range_dca enter this range's token for this account? A token of the signal pass: wherever range_dca trades.
    A token only the market watchlist or an event topic brought (11.11., flags range_market / event_tokens): only the
    demo account PAPER_USER, and only while that source's own flag is paper (or live, which is paper for them: they
    never trade real money); never LEAGUE_USER, whatever the flags say."""
    srcs = (rng or {}).get("sources") or [(rng or {}).get("source") or "signal"]
    if "signal" in srcs:
        return True
    from trade import settings as ts
    if user != ts.PAPER_USER:
        return False
    fl = _flags()
    return any(fl.mode(market.WATCH_FLAG[s]) in ("paper", "live") for s in srcs if s in market.WATCH_FLAG)


def _fresh_levels(rng, now):
    if rng and rng.get("zones") and rng.get("active") and now - (rng.get("ts") or 0) <= RANGE_FRESH_S:
        return rules.levels_of(rng)
    return None


def _spent_today(con, user, now, sol):
    """SOL of the range lots the account bought today (Zagreb day), at today's SOL price. A partial sale splits a lot
    into rows whose sizes add up to the lot's cost, so the sum over all rows is what was bought."""
    usd = con.execute("SELECT COALESCE(SUM(size_usd), 0) FROM trades WHERE user=? AND opened_ts>=? AND source IN (?,?)",
                      (user, _day_start(now), SRC1, SRC2)).fetchone()[0] or 0
    return usd / sol if sol else 0.0


def _guards(tok, m):
    """The rug / pool guards of the Autopilot's copies (league/copy) at the entry; the reason or None."""
    from league import copy
    price, liq, _url, mcap = m[:4]
    if copy._bonding_curve(m) or copy._dex_pair_empty(m):
        return "token je još na pump.fun krivulji ili bez DexScreener para (uzimaju se bondani)"
    if (mcap or 0) < copy.CFG["min_mcap"]:
        return "MC ispod 30k (ispod 30k se ne kupuje)"
    if (liq or 0) < 20_000:
        return f"likvidnost ${liq or 0:,.0f}, treba $20k"
    if mcap and liq and liq > mcap:
        return "lažni pool (likvidnost veća od MC-a)"
    if mcap and liq and liq < copy.CFG["min_liq_mcap"] * mcap:
        return f"likvidnost samo {liq / mcap:.1%} MC-a"
    col = copy._rugged(tok, mcap, liq)
    if col:
        return f"rug ({col['text']})"
    why, _shown = copy._concentration(tok)
    return why


def _held(con, user, tok):
    return con.execute("SELECT 1 FROM trades WHERE user=? AND token=? AND status='open'", (user, tok)).fetchone() is not None


def _cooldown(con, user, tok, now):
    r = con.execute("SELECT MAX(closed_ts) FROM range_rounds WHERE user=? AND token=? AND status='closed'", (user, tok)).fetchone()
    return bool(r and r[0] and now - r[0] < rules.RULES["cooldown_s"])


def _buy(con, user, tok, sym, usd, price, liq, mcap, src, allow_open):
    tid = store.buy(con, user, tok, sym, usd, price, liq, src, None, mcap, allow_open=allow_open)
    # the round's executor sells these lots; a player's "also for new buys" rule must not put its own TP/SL on them
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))
    con.commit()
    return tid


def entry_view(rng, price, now):
    """The entry decision on a range as the MCP API shows it: None (would enter) or the reason."""
    if not rng:
        return "nema raspona"
    if now - (rng.get("ts") or 0) > RANGE_FRESH_S:
        return "raspon nije svjež"
    if now - (rng.get("mts") or rng.get("ts") or 0) > METRICS_FRESH_S:
        return "5-minutni podaci nisu svježi"
    return rules.entry_check(rng, price)


def run_once(con, market_fn=None, now=None, ranges=None, lim=None, sol=None):
    """One entry pass: [(user, text)]. Off: nothing at all (one cached flag read)."""
    m = mode()
    if m == "off":
        return []
    now = int(now or time.time())
    act, sh = roles(m, now)
    if not act and not sh:
        return []
    ensure(con)
    open_r = rounds(con)
    if ranges is not None:
        rngs = ranges
    else:   # 11.11.: the active ranges and the open rounds' ranges only (range.db holds the whole market watchlist)
        rngs = data.read_ranges(since=now - RANGE_FRESH_S, active_only=True)
        rest = sorted({r["token"] for r in open_r} - set(rngs))
        if rest:
            rngs.update(data.read_ranges(since=now - RANGE_FRESH_S, tokens=rest))
    cand = {t for t, r in rngs.items() if r.get("active") and (r.get("score") or 0) >= rules.RULES["score_min"]
            and (r.get("pos_pct") is None or r["pos_pct"] <= 40)}
    toks = sorted(cand | {r["token"] for r in open_r if r["user"] in act})
    if not toks:
        return []
    from league import copy
    mk = (market_fn or copy.market)(toks) or {}
    lim = lim or limits(now)
    sol = sol or sol_usd()
    done = []
    if not sol:
        return done
    for user in act:
        mine = [r for r in open_r if r["user"] == user]
        for r in mine:
            done += _lot2(con, user, r, rngs.get(r["token"]), mk.get(r["token"]), lim, sol, now)
        n_open = len(mine)
        for tok in sorted(cand):
            if n_open >= lim["max_open"]:
                break
            if any(r["token"] == tok for r in mine) or not allowed(rngs[tok], user, now):
                continue
            got = _lot1(con, user, tok, rngs[tok], mk.get(tok), lim, sol, now)
            if got:
                n_open += 1
                done += got
    for user in sh:
        for tok in sorted(cand):
            mq = mk.get(tok)
            if not mq or not mq[0] or now - _SHADOWED.get((user, tok), 0) < SHADOW_EVERY_S:
                continue
            if not allowed(rngs[tok], user, now):   # the real account would never buy a market / event token
                continue
            why = entry_view(rngs[tok], mq[0], now) or _guards(tok, mq)
            if why is None:
                _SHADOWED[(user, tok)] = now
                _flags().shadow(con, FLAG, None, tok, "ništa", "range ulaz lot 1",
                                {"user": user, "mc": mq[3], "score": rngs[tok].get("score"),
                                 "pos_pct": rngs[tok].get("pos_pct")}, now)
                con.commit()
    return done


def _lot1(con, user, tok, rng, mq, lim, sol, now):
    if not mq or not mq[0]:
        return []
    price, liq, _url, mcap = mq[:4]
    why = entry_view(rng, price, now)
    if why is None and (_held(con, user, tok) or _cooldown(con, user, tok, now)):
        why = "već drži token ili je u pauzi nakon runde"
    if why is None:
        why = _guards(tok, mq)
    lot = rules.lot_sizes(lim["size_sol"], lim["dca_token_cap"])
    if why is None and lot <= 0:
        why = "dca_cap manji od pola uloga"
    if why is None and _spent_today(con, user, now, sol) + lot > lim["max_sol_per_day"] + 1e-9:
        why = "dnevni limit SOL-a za range ulaze"
    if why:
        return []
    sym = (mq[4] if len(mq) > 4 else None) or rng.get("symbol")
    try:
        tid = _buy(con, user, tok, sym, lot * sol, price, liq, mcap, SRC1, False)
    except ValueError as e:
        print(f"range {user} {tok[:6]}: ulaz nije prošao ({e})", flush=True)
        return []
    lv = rules.levels_of(rng)
    lv["supply"] = (mcap / price) if mcap and price else (rng.get("metrics") or {}).get("supply")
    con.execute("INSERT INTO range_rounds (user, token, symbol, opened_ts, status, lot1_id, lot1_sol, entry_mc, score, "
                "levels, state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user, tok, sym, now, "open", tid, lot, mcap, rng.get("score"), json.dumps(lv), json.dumps({})))
    con.commit()
    return [(user, f"range lot 1 {sym or tok[:6]}: {lot:g} SOL na MC ${mcap or 0:,.0f} (raspon "
                   f"{rng.get('pos_pct') or 0:.0f} %, ocjena {rng.get('score') or 0:.2f})")]


def _lot2(con, user, r, rng, mq, lim, sol, now):
    if r.get("lot2_id") or not mq or not mq[0]:
        return []
    # the 1-second exit thread (its own connection) may have taken profit or closed the round since it was read
    cur = con.execute("SELECT status, lot2_id, state FROM range_rounds WHERE id=?", (r["id"],)).fetchone()
    if not cur or cur[0] != "open" or cur[1] or (json.loads(cur[2] or "{}") or {}).get("tp1"):
        return []
    price, liq, _url, mcap = mq[:4]
    t1 = con.execute("SELECT entry_px FROM trades WHERE id=?", (r["lot1_id"],)).fetchone()
    if not t1 or not _held(con, user, r["token"]):
        return []
    lv = rules.merge_levels(r["levels"], _fresh_levels(rng, now))
    mets = (rng or {}).get("metrics") if rng and now - (rng.get("mts") or rng.get("ts") or 0) <= METRICS_FRESH_S else None
    why = rules.lot2_check(t1[0], price, lv, mets)
    lot = rules.lot_sizes(lim["size_sol"], lim["dca_token_cap"], held_sol=r["lot1_sol"] or 0)
    if why is None and lot <= 0:
        why = "dca_cap: nema mjesta za lot 2"
    if why is None and _spent_today(con, user, now, sol) + lot > lim["max_sol_per_day"] + 1e-9:
        why = "dnevni limit SOL-a za range ulaze"
    if why is None:
        why = _guards(r["token"], mq)
    if why:
        return []
    try:
        tid = _buy(con, user, r["token"], r["symbol"], lot * sol, price, liq, mcap, SRC2, True)
    except ValueError as e:
        print(f"range {user} {r['token'][:6]}: lot 2 nije prošao ({e})", flush=True)
        return []
    con.execute("UPDATE range_rounds SET lot2_id=?, lot2_sol=?, lot2_mc=? WHERE id=?", (tid, lot, mcap, r["id"]))
    con.commit()
    return [(user, f"range lot 2 {r['symbol'] or r['token'][:6]}: {lot:g} SOL na MC ${mcap or 0:,.0f} "
                   f"({price / t1[0] - 1:+.1%} od prvog)")]


# ---------- exits (every second) ------------------------------------------------------------------------------------
def _lots(con, r):
    """The round's lots still open, as dicts (the lot ids re-read: lot 2 may have been bought by the entry thread)."""
    row = con.execute("SELECT lot1_id, lot2_id FROM range_rounds WHERE id=?", (r["id"],)).fetchone()
    ids = [i for i in (row if row else (r["lot1_id"], r["lot2_id"])) if i]
    cur = con.execute(f"SELECT * FROM trades WHERE id IN ({','.join('?' * len(ids))}) AND status='open' ORDER BY id", ids)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _be_px(lots, liq):
    """The price at which selling every open lot returns its cost (league/store fee and AMM impact included)."""
    q = sum(t["qty"] or 0 for t in lots)
    cost = sum(t["size_usd"] or 0 for t in lots) - sum(t.get("realized") or 0 for t in lots)
    if q <= 0 or cost <= 0:
        return None
    return cost / q / ((1 - store.FEE) * (1 - store.impact(cost, liq)))


def _finish(con, r, reason, now):
    pnl, cost = con.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0), COALESCE(SUM(size_usd), 0) FROM trades WHERE user=? AND token=? AND id>=? "
        "AND status='closed' AND source IN (?,?) AND closed_ts>=?",
        (r["user"], r["token"], r["lot1_id"], SRC1, SRC2, r["opened_ts"])).fetchone()
    con.execute("UPDATE range_rounds SET status='closed', closed_ts=?, cost_usd=?, pnl_usd=?, ret=?, exit_reason=? "
                "WHERE id=? AND status='open'", (int(now), cost, pnl, (pnl / cost) if cost else None, reason, r["id"]))
    con.commit()
    return pnl


def _sell(con, r, lots, reason, frac, price, liq, mcap):
    """Sell frac of every open lot of the round (1 = all). Returns the PnL in USD of what was sold."""
    rule = EXIT_RULE.get(reason.split(":")[0], "sl")
    note = f"range: {REASON_HR.get(reason.split(':')[0], reason)}"
    pnl = 0.0
    for t in lots:
        if frac >= 0.999:
            pnl += store.sell(con, r["user"], t["id"], price, liq, note, mcap=mcap, exit_rule=rule)
        else:
            p, sold_all = store.sell_partial(con, r["user"], t["id"], frac, price, liq, mcap=mcap)
            pnl += p
            # the sold part is its own closed row (league/store.sell_partial marks it "manual"): name the range rule
            part = t["id"] if sold_all else con.execute("SELECT MAX(id) FROM trades WHERE user=? AND token=? AND "
                                                        "status='closed'", (r["user"], r["token"])).fetchone()[0]
            store.set_data(con, part, exit_rule=rule)
            con.execute("UPDATE trades SET note=? WHERE id=?", (f"{note} ({frac:.0%})", part))
    con.commit()
    return pnl


def exits_once(con, market_fn, now=None):
    """The exits of every open range round: [text]. Flag off: the open rounds still get their exits (looked for once
    a minute); none open: nothing."""
    now = now or time.time()
    m = mode()
    if m == "off":
        if now - _CACHE["off_at"] < OFF_CHECK_S and not _CACHE["off_open"]:
            return []
        _CACHE["off_at"] = now
        try:
            _CACHE["off_open"] = con.execute("SELECT 1 FROM sqlite_master WHERE name='range_rounds'").fetchone() is not None \
                and con.execute("SELECT 1 FROM range_rounds WHERE status='open' LIMIT 1").fetchone() is not None
        except sqlite3.Error:
            _CACHE["off_open"] = False
        if not _CACHE["off_open"]:
            return []
    elif con.execute("SELECT 1 FROM sqlite_master WHERE name='range_rounds'").fetchone() is None:
        return []
    open_r = rounds(con)
    if not open_r:
        return []
    from league import exitplan
    q = exitplan.quote(market_fn, {r["token"] for r in open_r}, now)
    rngs = _ranges(now, tokens={r["token"] for r in open_r})
    out = []
    for r in open_r:
        lots = _lots(con, r)
        if not lots:   # sold by an exit plan (Grok) or by hand: the round ends with what the trades say
            pnl = _finish(con, r, r["state"].get("last") or "prodano izvan runde", now)
            out.append(f"range {r['user']} {r['symbol'] or r['token'][:6]}: runda zatvorena ({pnl:+.2f} $)")
            continue
        if r["token"] not in q:
            continue
        price, mcap, liq, age = q[r["token"]]
        rng = rngs.get(r["token"])
        lv = rules.merge_levels(r["levels"], _fresh_levels(rng, now))
        st = r["state"]
        before = json.dumps(st, sort_keys=True)
        gu = ((rng or {}).get("state") or {}).get("give_up")
        hit = None
        if gu and gu.get("ts", 0) >= r["opened_ts"] and age <= STALE_S:
            hit = (f"odustajanje: {gu.get('why')}", 1.0)
        else:
            hit = rules.exit_step(lv, st, price, now, r["opened_ts"], _be_px(lots, liq), stale=age > STALE_S)
        if lv["stop_px"] != r["levels"].get("stop_px"):   # the stop tightened with the newer range: kept
            r["levels"]["stop_px"] = lv["stop_px"]
            con.execute("UPDATE range_rounds SET levels=? WHERE id=?", (json.dumps(r["levels"]), r["id"]))
        if hit:
            reason, frac = hit
            st["last"] = reason
            try:
                pnl = _sell(con, r, lots, reason, frac, price, liq, mcap)
            except ValueError as e:   # closed in the same second by another path: next pass
                print(f"range {r['token'][:6]}: {e}", flush=True)
                continue
            con.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(st), r["id"]))
            con.commit()
            text = (f"range {r['user']} {r['symbol'] or r['token'][:6]}: {REASON_HR.get(reason.split(':')[0], reason)}"
                    f"{reason[len('odustajanje'):] if reason.startswith('odustajanje') else ''}, prodano {frac:.0%} "
                    f"na MC ${mcap or 0:,.0f}, {pnl:+.2f} $")
            if not _lots(con, r):
                tot = _finish(con, r, reason, now)
                text += f"; runda gotova {tot:+.2f} $"
            out.append(text)
        elif json.dumps(st, sort_keys=True) != before:
            con.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(st), r["id"]))
            con.commit()
    return out


def view_rounds(con, user=None, limit=50):
    """Open rounds and the last closed ones, for the MCP API."""
    ensure(con)
    out = {"open": rounds(con, "open", user)}
    sql = "SELECT * FROM range_rounds WHERE status='closed'" + (" AND user=?" if user else "") + " ORDER BY id DESC LIMIT ?"
    cur = con.execute(sql, ((user,) if user else ()) + (int(limit),))
    cols = [c[0] for c in cur.description]
    out["closed"] = [dict(zip(cols, row)) for row in cur.fetchall()]
    for d in out["closed"]:
        d.pop("levels", None)
        d.pop("state", None)
    return out
