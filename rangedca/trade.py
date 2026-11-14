"""range_dca on the Autopilot's demo accounts (flag range_dca; league.db's only writer, run_ui.py, runs this):

  run_once    every pass of league/auto.loop (20 s): lot 1 and lot 2 entries from the ranges run_range.py computed
  exits_once  every second in league/auto.fast_loop: the round's exits (rules.exit_step) and the give-ups

Modes (league/flags): off nothing new (rounds already open keep their exits: a stop is never dropped; looked for once
a minute); shadow: the real account LEAGUE_USER only logs what it would buy (league.db shadow_decisions); paper: the
demo account PAPER_USER trades (run_trade.py never mirrors it), LEAGUE_USER logs; live: both trade, and LEAGUE_USER
only while rangedca/gate.refusal() is None (>= 20 closed paper rounds passing trade/edge.live_proof), checked again
every minute.
11.11.: a token only the market watchlist or an event topic brought (ranges.src market / event, rangedca/market.py)
is entered only by the demo account PAPER_USER and only while its own flag (range_market / event_tokens) is paper;
the real account never buys one and never logs one (allowed()).
11.11. (flag range_missed G27, rangedca/missed.py): a token on the list because it was skipped and then rose >= 20 %
within 60 min (ranges.src missed) is entered by the range rules only (the range from detect, never the skip's price):
the demo account while range_missed is paper; the real account only while it is live and gate.missed_refusal() is
None. Every round keeps its source in levels "src" (the EV report and get_range_candidates split missed vs the rest).

A round = lot 1 (+ lot 2) until everything is sold; table range_rounds (league.db) keeps its levels (frozen at the
entry; the take-profit levels follow the newest range, the stop only tightens), its state (tp1, top touched, peak)
and at the end its PnL from the closed trades (partial sales included). The lots are ordinary demo trades with
source "range lot 1" / "range lot 2" and no auto TP/SL of their own; run_trade.py mirrors LEAGUE_USER's like any
other trade (lot 2 as one more lot of the same position, held by every real limit).

Limits (spec 3): a lot is trade settings size_sol (in USD at the current SOL price), lot 1 + lot 2 at most
dca_token_cap SOL; 11.11. (owner's rules B / C, trade/cost.size_sol): never more than the stake whose buy impact stays
<= 2 %, and x volume 1 h / $10k under $10k (the range itself needs $3k); on the demo account max_open counts its open range rounds and max_sol_per_day its range lots of
the Zagreb day (run_trade.py holds the real account to every real limit again). Grok does not trade through this; a
Grok trade in the same token goes through ui/grokauto and its own limits, and Grok may TIGHTEN a range position's
exits with set_exit_plan (league/exitplan; "accounts": ["autopilot-paper"] keeps the plan off the real account).

11.11. (Jure: "rangedca flip / pauza / stop", flag range_flip G26, flip_roles): off: today's rules exactly (nothing of
the flip state is read). shadow: every account trades today's rules; league.db shadow_decisions (flag range_flip)
gets a row when the new rules would decide an entry otherwise (blocked by a pause / a flip candidate, or added on
the range that formed after a break), the would-be stop at every lot 1 (levels flip_stop_px, which only tightens like
the stop) and the moment either stop would have sold where the other did not. paper: the demo account PAPER_USER
trades the new rules (rules.new_range: no lot 1 / lot 2 while paused or a flip candidate, the range after a break once
flipped / resumed, the volatility stop; its rounds carry levels rules = "flip"); the real account never. live:
LEAGUE_USER too, but only while gate.flip_refusal() is None (the nightly backtest's new max drawdown <= today's) and
only where range_dca itself trades it (range_dca stays paper: then it never does).

11.11. (the owner's decision 1, "range stopovi", rules.atr_range / reclaim_*): no flag changes. The hard stop of every
round, on every account, is the ATR stop (stop variant b: range_low_low - 1.5 x ATR, 5-20 % under it; x 0.85 only while
ATR is unknown); x 0.85 is no longer the live stop of today's rules. On top of it:
  real account LEAGUE_USER (only where range_dca trades it: live past gate.refusal)  the ATR stop; a reclaim only while
                gate.reclaim_refusal() is None (>= 7 nights of the nightly stop comparison and >= 20 closed demo
                reclaim rounds with EV > 0 after cost), asked again before every reclaim; never a market / event token
  demo account PAPER_USER  the ATR stop + reclaim. A stop-out (or the "range broken downward" give-up) of a round that
                was no reclaim arms its closed row's state "reclaim" {until (+30 min), rl (range_low), low, atr}; every
                20-s pass lowers `low` to the lowest price it sees and buys lot 1 of a new round (levels "reclaim": true,
                "reclaim_of", the stopped round's take-profit levels) once the price is above range_low with buys >=
                60 % of 5 minutes (fresh numbers); its stop = rules.reclaim_stop(low, ATR), kept as it is (only the
                take-profit levels follow the newest range). Not after 30 min; one reclaim per stopped round; the
                cooldown and range_flip's pause do not apply to it (the stop comparison's variant "be" measured it so);
                the guards and the limits do. Counted apart (gate.reclaim_proof); range_dca's own proof leaves them out.

14.11. (owner: "želim da danas otvoriš barem 5 tradeova ... otvaraj pozicije ... u donjem dijelu range-a. Testiraj sa
stop loss ... da se uzima barem 10-15% profita"; flag range_demo G32, default paper, never live): while range_demo is
paper the DEMO account PAPER_USER trades the demo profile rules.DEMO (profile()): its candidates and lot 1 by DEMO's
entry thresholds (never a token the crash took > 45 % under its level 24 h ago; crash survivors, rangedca/survivor,
tried first: _order), its round's levels from rules.demo_levels (TP1 half at +10 % net, the rest at +15 % net / the
top zone, a 15 % trailing or break-even after TP1, the ATR stop held at -12..-25 % from the entry; levels "profile":
"demo"), no lot 2. The real account LEAGUE_USER keeps RULES exactly, and
the real-money gates (gate.refusal, gate.missed_refusal) never count a demo-profile round. Every pass also records,
once per token and reason a day, why each fresh active range was no demo entry (league.db range_blocks), and
demo_today() is the daily counter "range demo danas: N tradeova (cilj 5)" with the 3 reasons that held off the most
tokens (logged when N changes and once an hour; get_range_candidates "demo_today").
"""
import json
import os
import sqlite3
import time

from league import store
from trade import cost as _cost
from . import data, gate, market, rules

FLAG = "range_dca"
FLIP_FLAG = "range_flip"    # 11.11. (G26): flip / pause / volatility stop, the new rules (rules.new_range)
DEMO_FLAG = "range_demo"    # 14.11. (G32): the demo account's profile rules.DEMO (entry, survivor, TP / stop)
DEMO_LOG_S = 3600           # 14.11.: the daily counter's log line at least this often (and whenever N changes)
SRC1, SRC2 = "range lot 1", "range lot 2"
RANGE_FRESH_S = 15 * 60     # a range computed longer ago is not traded
# 12.11. popodne (owner, točka 1: "prag svježine ~5 min, jednak intervalu, pa svako kašnjenje stavi entry_ready=false na
# sve"): two limits instead of one 4-minute limit for everything. The hard one holds every automatic buy (lot 1, lot 2,
# reclaim) of this module: 5 minutes, because "5-minute" numbers computed at t describe t-5..t, and from t+5 on that
# window shares no minute with the 5 minutes being traded (run_range renews them every pass, ~60 s, so 5 minutes is
# four missed passes or a deploy). The readiness limit is what entry_ready / entry_now (get_range_candidates), the
# owner's pin and zonewatch's range zones read: 9 minutes, so one late or lost cycle (a restart) no longer turns every
# candidate into "5-minutni podaci nisu svježi"; past either limit the real reason (zone, score, breakout) stays in
# front and the staleness is added after it (entry_view).
METRICS_FRESH_S = int(os.environ.get("RANGE_METRICS_TRADE_S", "300"))   # hard: an automatic entry (trade gate)
METRICS_READY_S = int(os.environ.get("RANGE_METRICS_READY_S", "540"))   # entry_ready / pin / range zones
METRICS_NOTE_S = 150        # numbers older than this (two missed passes) carry a note on the row
STALE_S = 60                # league/exitplan.STALE_S: an older price fires only the hard stop
RNG_TTL_S = 10              # the 1-s exit loop reads range.db at most this often
OFF_CHECK_S = 60
SHADOW_EVERY_S = 20 * 60
EXIT_RULE = {"tp1": "tp", "top": "tp", "trailing": "tp", "stop": "sl", "time": "time", "odustajanje": "sl", "rug": "rug",
             "tp2": "tp", "breakeven": "sl"}
REASON_HR = {"tp1": "pola u gornjoj zoni", "top": "ostatak na vrhu raspona", "trailing": "trailing 10 % od vrha",
             "stop": "tvrdi stop (range_low_low × 0,85)", "time": "6 h bez gornje zone, izlaz na nuli",
             "odustajanje": "odustajanje", "rug": "tvrdi blok (rug): pin i oznaka poništeni",
             "tp2": "ostatak na +15 % neto", "breakeven": "break-even stop ostatka nakon TP1"}
DEMO_HR = {"tp1": "pola na +10 % neto (demo 14.11.)", "time": "6 h bez TP1, izlaz na nuli",
           "stop": "tvrdi stop demo (ATR, -12 do -25 % od ulaza)", "trailing": "trailing 15 % od vrha (demo)",
           "tp2": "ostatak na +15 % neto ili gornjoj zoni (demo)"}
STOP_ATR_HR = "tvrdi stop (range_low_low − 1,5 × ATR)"   # 11.11.: the ATR stop (every account, decision 1)
STOP_RECLAIM_HR = "tvrdi stop reclaim runde (novo dno − 1,5 × ATR)"


def _hr(reason, levels=None):
    """The reason in Croatian; the stop of a round with the volatility stop (or a reclaim round's) says so."""
    k = reason.split(":")[0]
    kind = (levels or {}).get("stop_kind")
    if (levels or {}).get("profile") == "demo" and k in DEMO_HR:   # 14.11.: the demo profile's own exits
        return DEMO_HR[k]
    if k == "stop" and kind == "atr":
        return STOP_ATR_HR
    if k == "stop" and kind in ("reclaim", "reclaim_fixed"):
        return STOP_RECLAIM_HR
    return REASON_HR.get(k, reason)

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


def flip_roles(act, now=None):
    """(range_flip's mode, the accounts of `act` that trade the new rules, the accounts of `act` whose today's-rules
    entries and stops get range_flip shadow rows). off: nobody and nothing; shadow: nobody trades them, every trading
    account is logged; paper: PAPER_USER trades them; live: LEAGUE_USER too, only past gate.flip_refusal (checked
    again here, so a hand edit of the flag never moves the real account onto them)."""
    from trade import settings as ts
    fl = _flags()
    m = fl.mode(FLIP_FLAG)
    if m == "off":
        return m, set(), set()
    new = {u for u in act if fl.applies(FLIP_FLAG, u, m)}
    if ts.LEAGUE_USER in new:
        why = gate.flip_refusal(now=now, cached=True)
        if why:
            new.discard(ts.LEAGUE_USER)
            t = now or time.time()
            if t - _CACHE.get("flip_gate_log", 0.0) > 3600:
                _CACHE["flip_gate_log"] = t
                print(f"range_flip live: pravi račun ostaje na starim pravilima ({why})", flush=True)
    return m, new, set(act) - new


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
    never trade real money); never LEAGUE_USER, whatever the flags say. 11.11. (range_missed G27): a token whose first
    source is "missed" (rangedca/missed.py): the demo account while range_missed is paper or live; LEAGUE_USER only
    while range_missed is live AND gate.missed_refusal() is None (>= 20 closed demo rounds of source missed, EV
    proof), checked again here (a hand edit of the flag never buys with real money)."""
    srcs = (rng or {}).get("sources") or [(rng or {}).get("source") or "signal"]
    if "signal" in srcs:
        return True
    from trade import settings as ts
    if user != ts.PAPER_USER:
        first = next((s for s in market.SRC_ORDER if s in srcs), None)
        return user == ts.LEAGUE_USER and first == "missed" and missed_live(now)
    fl = _flags()
    return any(fl.mode(market.WATCH_FLAG[s]) in ("paper", "live") for s in srcs if s in market.WATCH_FLAG)


def missed_live(now=None):
    """True while range_missed (G27) is live AND its own proof passes (gate.missed_refusal); logged once an hour when
    the flag is live but the proof refuses."""
    if _flags().mode(market.WATCH_FLAG["missed"]) != "live":
        return False
    try:
        why = gate.missed_refusal(now=now, cached=True)
    except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
        why = f"dokaz izvora missed nije čitljiv ({type(e).__name__})"
    if why:
        t = now or time.time()
        if t - _CACHE.get("missed_gate_log", 0.0) > 3600:
            _CACHE["missed_gate_log"] = t
            print(f"range_missed live: pravi račun ne kupuje propuštene tokene ({why})", flush=True)
        return False
    return True


def profile(user, m=None):
    """14.11. (flag range_demo G32): the rule set `user` trades range_dca by: rules.DEMO for the demo account
    PAPER_USER while range_demo is paper (live is paper for it: NEVER_LIVE), else None (RULES, the real account
    always)."""
    from trade import settings as ts
    if user != ts.PAPER_USER:
        return None
    try:
        m = m or _flags().mode(DEMO_FLAG)
    except Exception:  # noqa: BLE001 - unreadable: today's rules
        return None
    return rules.DEMO if m in ("paper", "live") else None


def _fresh_levels(rng, now, new=False):
    """The levels of the newest range when it is active and fresh. new: True = of the new rules' range
    (rules.new_range), or the parts of them to apply (("atr",): today's range with the volatility stop)."""
    rx = (rules.new_range(rng, rules.FLIP_PARTS if new is True else new) if new and rng else rng)
    rx = rules.atr_range(rx)   # 11.11. (decision 1): the ATR stop on every account's levels
    if rx and rx.get("zones") and rx.get("active") and now - (rng.get("ts") or 0) <= RANGE_FRESH_S:
        return rules.levels_of(rx)
    return None


def _levels_now(r, rng, now):
    """The levels in force for an open round (rules.merge_levels with the newest range). A reclaim round keeps its
    own stop (under the new low): only its take-profit levels follow the range."""
    lv = rules.levels_in_force(r["levels"], _fresh_levels(rng, now, _is_new(r)))   # 14.11.: a demo round's own TP
    if r["levels"].get("reclaim"):
        lv["stop_px"] = r["levels"]["stop_px"]
        lv["stop_kind"] = r["levels"].get("stop_kind")
    return lv


def may_reclaim(user, now=None):
    """11.11. (decision 1): may this account buy a reclaim? The demo account yes; the real account only while
    gate.reclaim_refusal() is None (asked again here; logged once an hour when it refuses); nobody else."""
    from trade import settings as ts
    if user == ts.PAPER_USER:
        return True
    if user != ts.LEAGUE_USER:
        return False
    try:
        why = gate.reclaim_refusal(now=now, cached=True)
    except Exception as e:  # noqa: BLE001 - a proof that cannot be read is no proof
        why = f"dokaz reclaima nije čitljiv ({type(e).__name__})"
    if why:
        t = now or time.time()
        if t - _CACHE.get("reclaim_gate_log", 0.0) > 3600:
            _CACHE["reclaim_gate_log"] = t
            print(f"range reclaim: pravi račun ne kupuje reclaim ({why})", flush=True)
        return False
    return True


def _is_new(r):
    """True for a round opened under the new rules (range_flip)."""
    return (r.get("levels") or {}).get("rules") == "flip"


def _spent_today(con, user, now, sol):
    """SOL of the range lots the account bought today (Zagreb day), at today's SOL price. A partial sale splits a lot
    into rows whose sizes add up to the lot's cost, so the sum over all rows is what was bought."""
    usd = con.execute("SELECT COALESCE(SUM(size_usd), 0) FROM trades WHERE user=? AND opened_ts>=? AND source IN (?,?)",
                      (user, _day_start(now), SRC1, SRC2)).fetchone()[0] or 0
    return usd / sol if sol else 0.0


ARCHIVE_LOG_S = 3600
_ARCH_SAID = {}


def archived_why(tok):
    """12.11. popodne (owner, točka 4: "tokene iz arhive rugova (NOBUSHIBA, Leonida) ne naoružavaj i ne tradaj"): the
    reason when the token is in the rug archive (rugfilter/archive.blocked, any kind: the archive's own contract is
    "never tracked again"), else None (also when the archive cannot be read: then the other rug guards decide).
    league/copy._rugged alone misses them: the archive deletes the token's history from hype.db, so the collapse
    check has no peak left to compare with. Read by every automatic range buy (_guards), get_range_candidates
    (rangedca/view.one), zonewatch's range zones and arm_zone, and the range job (no polling, no range)."""
    try:
        from rugfilter import archive
        if tok not in archive.blocked():
            return None
        kind = None
        try:
            kind = archive.kinds(log=None).get(tok)
        except Exception:  # noqa: BLE001 - the kind only names it
            pass
    except Exception:  # noqa: BLE001
        return None
    return f"token je u arhivi rugova ({kind or 'rug'}): ne prati se, ne trguje i ne naoružava"


def _guards(tok, m):
    """The rug / pool guards of the Autopilot's copies (league/copy) at the entry; the reason or None. 12.11.: the
    rug archive first (archived_why), logged once an hour per token."""
    from league import copy
    arch = archived_why(tok)
    if arch:
        now = time.time()
        if now - _ARCH_SAID.get(tok, 0) >= ARCHIVE_LOG_S:
            _ARCH_SAID[tok] = now
            print(f"range {tok[:6]}: ulaz blokiran, {arch}", flush=True)
        return arch
    price, liq, _url, mcap = m[:4]
    if copy._bonding_curve(m) or copy._dex_pair_empty(m):
        return "token je još na pump.fun krivulji ili bez DexScreener para (uzimaju se bondani)"
    if (mcap or 0) < copy.CFG["min_mcap"]:
        return "MC ispod 30k (ispod 30k se ne kupuje)"
    lb = _cost.liq_block(liq or 0)   # 11.11. owner's rule B: the only liquidity block, under $15k
    if lb:
        return lb
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


def busy(con, user, tok, now, rng=None):
    """11.11. (the owner after HAOBIBI: one position per token, a second buy is a lot of the same round or nothing):
    why another strategy (proposals/paper.py) may not enter `tok` on `user` because of range_dca, or None. An open
    range round (its second lot is range's own lot 2), a round closed within the cooldown (rules cooldown_s, 20 min:
    HAOBIBI's round closed on its stop 2 s before the proposal bought), or the token's range paused by range_flip
    (rules.flip_block: paused / flip candidate). rng: the token's range (range.db) when the caller has it."""
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='range_rounds'").fetchone() is None:
            return None
        if con.execute("SELECT 1 FROM range_rounds WHERE status='open' AND user=? AND token=?", (user, tok)).fetchone():
            return "range runda je otvorena (drugi ulaz bio bi lot iste runde)"
        if _cooldown(con, user, tok, now):
            return f"range runda zatvorena prije manje od {rules.RULES['cooldown_s'] // 60} min (cooldown)"
    except sqlite3.Error:
        return None
    why = rules.flip_block(rng) if rng else None
    return f"range je u pauzi ({why})" if why else None


def _buy(con, user, tok, sym, usd, price, liq, mcap, src, allow_open):
    tid = store.buy(con, user, tok, sym, usd, price, liq, src, None, mcap, allow_open=allow_open)
    # the round's executor sells these lots; a player's "also for new buys" rule must not put its own TP/SL on them
    con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE id=?", (tid,))
    con.commit()
    return tid


def numbers_age(rng, now):
    """Seconds since the range's 5-minute numbers were renewed (mts; the computation's ts for an older row)."""
    return int(now - ((rng or {}).get("mts") or (rng or {}).get("ts") or 0))


def stale_why(rng, now, limit=None):
    """None while the range (RANGE_FRESH_S) and its 5-minute numbers (limit, default the trade gate's METRICS_FRESH_S)
    are fresh enough, else why in Croatian, with the age and the limit."""
    limit = METRICS_FRESH_S if limit is None else limit
    age_r = int(now - ((rng or {}).get("ts") or 0))
    if age_r > RANGE_FRESH_S:
        return f"raspon nije svjež (izračunat prije {age_r / 60:.0f} min, granica {RANGE_FRESH_S // 60} min)"
    age = numbers_age(rng, now)
    if age > limit:
        return f"5-minutni podaci nisu svježi (stari {age / 60:.1f} min, granica {limit / 60:g} min)"
    return None


def entry_view(rng, price, now, limit=None, cfg=None):
    """The entry decision on a range: None (would enter) or the reason. 12.11. (owner, točka 1): the real rule's
    reason (zone, score, floor, 5-minute numbers) first and the staleness after it ("<real> · <stale>"), so a late
    cycle never hides why a token is or is not an entry. limit: the numbers' age limit, default the hard trade gate's
    METRICS_FRESH_S (every automatic buy here); the readiness views pass METRICS_READY_S. cfg (14.11.): the rule set
    (rules.DEMO for the demo profile), None = RULES."""
    if not rng:
        return "nema raspona"
    real = rules.entry_check(rules.atr_range(rng), price, cfg)   # 11.11.: the floor never under the ATR stop (variant b)
    stale = stale_why(rng, now, limit)
    if real and stale:
        return f"{real} · {stale}"
    return real or stale


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
    armed = [r for r in _armed(con, now) if r["user"] in act] if act else []   # 11.11.: open reclaim windows
    mflip, new_u, flip_sh = flip_roles(act, now)
    if ranges is not None:
        rngs = ranges
    else:   # 11.11.: the active ranges and the open rounds' ranges only (range.db holds the whole market watchlist)
        rngs = data.read_ranges(since=now - RANGE_FRESH_S, active_only=True)
        rest = ({r["token"] for r in open_r} | {r["token"] for r in armed}) - set(rngs)
        if mflip != "off":   # range_flip: the tokens whose range after a break is active (today's may not be)
            rest |= set(data.flip_rows(since=now - RANGE_FRESH_S, alt_active=True)) - set(rngs)
        if rest:
            rngs.update(data.read_ranges(since=now - RANGE_FRESH_S, tokens=sorted(rest)))
    cand = {t for t, r in rngs.items() if _candidate(r)}
    cand_new = {t for t, r in rngs.items() if _candidate(rules.new_range(r))} if mflip != "off" else set()
    # 14.11. (range_demo G32): the demo profile's own candidates (score >= 0.6) for the accounts that trade it
    demo_u = {u for u in act if profile(u)}
    cand_d = {t for t, r in rngs.items() if _candidate(r, rules.DEMO)} if demo_u else set()
    cand_dn = ({t for t, r in rngs.items() if _candidate(rules.new_range(r), rules.DEMO)}
               if demo_u and mflip != "off" else set())
    toks = sorted(cand | cand_new | cand_d | cand_dn | {r["token"] for r in open_r if r["user"] in act}
                  | {r["token"] for r in armed})
    if not toks:
        for user in demo_u:   # 14.11.: no candidate at all is a reason too (the daily counter)
            _note_blocks(con, user, _demo_blocks(rngs, now, new=user in new_u), now)
            _demo_log(con, user, now)
        return []
    from league import copy
    mk = (market_fn or copy.market)(toks) or {}
    lim = lim or limits(now)
    sol = sol or sol_usd()
    done = []
    if not sol:
        return done
    for user in act:
        new = user in new_u
        cfg = profile(user)   # 14.11.: rules.DEMO on the demo account while range_demo is paper
        blocks = {} if cfg else None
        mine = [r for r in open_r if r["user"] == user]
        for r in mine:
            done += _lot2(con, user, r, rngs.get(r["token"]), mk.get(r["token"]), lim, sol, now)
        n_open = len(mine)
        for r in armed:   # 11.11. (decision 1): a reclaim within 30 min of the stop-out, before any new lot 1
            if r["user"] == user and not any(x["token"] == r["token"] for x in mine):
                got = _reclaim(con, user, r, rngs.get(r["token"]), mk.get(r["token"]), lim, sol, now, n_open)
                if got:
                    n_open += 1
                    mine.append({"token": r["token"]})
                    done += got
        pool = (cand_dn if new else cand_d) if cfg else (cand_new if new else cand)
        for tok in (sorted(pool, key=lambda t: (_order(rngs.get(t)), t)) if cfg else sorted(pool)):
            if any(r["token"] == tok for r in mine):
                continue
            if n_open >= lim["max_open"]:
                if blocks is not None:
                    blocks[tok] = f"najviše otvorenih range rundi ({lim['max_open']})"
                    continue
                break
            if not allowed(rngs[tok], user, now):
                if blocks is not None:
                    blocks[tok] = "izvor tokena nije dopušten ovom računu (zastavica izvora)"
                continue
            got = _lot1(con, user, tok, rngs[tok], mk.get(tok), lim, sol, now, new=new,
                        flip_log=mflip if user in flip_sh else None, cfg=cfg, blocks=blocks)
            if got:
                n_open += 1
                done += got
        if blocks is not None:   # 14.11.: why every other fresh active range was no demo entry (the daily counter)
            held = {r["token"] for r in mine}
            rest = _demo_blocks({t: r for t, r in rngs.items() if t not in pool and t not in held}, now, new=new)
            _note_blocks(con, user, {**rest, **blocks}, now)
            _demo_log(con, user, now)
    if flip_sh:
        _flip_shadow(con, sorted(flip_sh), cand | cand_new, rngs, mk, now, mflip)
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


# ---------- 14.11. the demo profile's daily counter (owner: "barem 5 tradeova danas") ------------------------------------
BLOCKS_SCHEMA = ("CREATE TABLE IF NOT EXISTS range_blocks (day INTEGER, user TEXT, token TEXT, reason TEXT, ts INTEGER, "
                 "PRIMARY KEY (day, user, token, reason))")
# the reason's key: the first entry whose text is in the reason (the numbers of a reason differ token to token)
BLOCK_KEYS = (("arhivi rugova", "rug arhiva"), ("rug (", "rug"), ("lažni pool", "lažni pool"),
              ("ocjena raspona", "ocjena raspona ispod praga"), ("preživljavanje pada nepoznato", "preživljavanje nepoznato"),
              ("premlad za pad", "mlađi od 24 h (nije prošao pad)"), ("starost nepoznata", "starost nepoznata"),
              ("razina prije pada", "razina prije pada nepoznata"), ("nije preživio pad", "nije preživio pad (> 45 %)"),
              ("nije u rasponu", "nije opet u rasponu"), ("cijena na ", "cijena nije u donjem dijelu raspona"),
              ("ispod range_low_low", "cijena ispod dna raspona"), ("pada ", "pad u zadnjih 5 min"),
              ("promjena 5 min", "pad u zadnjih 5 min"), ("kupnje ", "premalo kupnji u 5 min"),
              ("udio kupnji", "premalo kupnji u 5 min"), ("volumen 15 min", "slab volumen 15 min"),
              ("volumen nepoznat", "slab volumen 15 min"), ("nije svjež", "podaci nisu svježi"),
              ("već drži", "već drži token / pauza nakon runde"), ("dnevni limit", "dnevni limit SOL-a"),
              ("najviše otvorenih", "najviše otvorenih range rundi"), ("krivulji", "još na krivulji"),
              ("MC ispod 30k", "MC ispod 30k"), ("likvidnost", "likvidnost"), ("koncentr", "koncentracija supplyja"),
              ("volumen 1 h", "volumen 1 h ispod $3k"), ("nema tržišne cijene", "nema tržišne cijene"),
              ("izvor tokena", "izvor nije dopušten"), ("pauz", "pauza nakon proboja"), ("proboj", "pauza nakon proboja"),
              ("volumen zadnjeg sata", "volumen sata pao (isključen)"), ("niža dna", "dva niža dna (isključen)"),
              ("probijen dolje", "raspon probijen dolje"), ("kupnja nije prošla", "kupnja nije prošla"))
_BLOCKS_SEEN = {}   # {(day, user): {(token, key)}} already in range_blocks (one write per token, reason and day)
BLOCKS_KEEP_DAYS = 14


def block_key(why):
    """A reason as the counter's key (Croatian, without the token's numbers)."""
    w = why or "nepoznato"
    for part, key in BLOCK_KEYS:
        if part in w:
            return key
    head = "".join(ch for ch in w.split(" (")[0].split(" · ")[0] if not ch.isdigit())
    return " ".join(head.split())[:60] or "nepoznato"


def _demo_blocks(rngs, now, new=False):
    """{token: why} for the fresh active ranges that were no demo candidate this pass (their score / place / range;
    the market price is not asked for them: the range's own numbers say why)."""
    out = {}
    for t, r in (rngs or {}).items():
        if not r or not r.get("active"):
            continue
        rx = rules.new_range(r) if new else r
        why = entry_view(rx, (r.get("metrics") or {}).get("price"), now, cfg=rules.DEMO)
        if why is None and (r.get("pos_pct") or 0) > 40:
            why = f"cijena na {r['pos_pct']:.0f} % raspona"
        out[t] = why or "nije kandidat ovog prolaza"
    return out


def _note_blocks(con, user, blocks, now):
    """One league.db range_blocks row per (Zagreb day, account, token, reason key) the first time it is seen."""
    if not blocks:
        return 0
    day = _day_start(now)
    fresh_day = (day, user) not in _BLOCKS_SEEN
    seen = _BLOCKS_SEEN.setdefault((day, user), set())
    for k in [k for k in _BLOCKS_SEEN if k[0] != day]:
        _BLOCKS_SEEN.pop(k, None)
    new = [(t, block_key(w)) for t, w in blocks.items()]
    new = [x for x in new if x not in seen]
    if not new:
        return 0
    try:
        con.execute(BLOCKS_SCHEMA)
        if fresh_day:   # the first write of a day (or of a process): the rows older than BLOCKS_KEEP_DAYS go
            con.execute("DELETE FROM range_blocks WHERE day < ?", (day - BLOCKS_KEEP_DAYS * 86400,))
        con.executemany("INSERT OR IGNORE INTO range_blocks VALUES (?,?,?,?,?)",
                        [(day, user, t, k, int(now)) for t, k in new])
        con.commit()
    except sqlite3.Error:
        return 0
    seen.update(new)
    return len(new)


def demo_today(con, now=None, user=None):
    """The daily counter (14.11.): {"day_start", "trades" (lot 1 of a round opened today, Zagreb day; reclaims
    included and counted apart), "reclaims", "goal", "open", "closed", "pnl_usd", "tokens_seen", "top_blocks"
    [{"reason", "tokens"}] (the 3 reasons that held off the most tokens today), "text"}."""
    from trade import settings as ts
    now = int(now or time.time())
    user = user or ts.PAPER_USER
    day = _day_start(now)
    out = {"day_start": day, "user": user, "goal": rules.DEMO_GOAL, "trades": 0, "reclaims": 0, "open": 0, "closed": 0,
           "pnl_usd": 0.0, "tokens_seen": 0, "top_blocks": []}
    try:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                                          "('range_rounds', 'range_blocks')")}
        if "range_rounds" in have:
            for st, lv, pnl in con.execute("SELECT status, levels, pnl_usd FROM range_rounds WHERE user=? AND "
                                           "opened_ts>=?", (user, day)):
                out["trades"] += 1
                out["reclaims"] += int('"reclaim": true' in (lv or ""))
                out["open" if st == "open" else "closed"] += 1
                out["pnl_usd"] += pnl or 0.0
        if "range_blocks" in have:
            out["top_blocks"] = [{"reason": k, "tokens": n} for k, n in con.execute(
                "SELECT reason, COUNT(DISTINCT token) n FROM range_blocks WHERE day=? AND user=? GROUP BY reason "
                "ORDER BY n DESC, reason LIMIT 3", (day, user))]
            out["tokens_seen"] = con.execute("SELECT COUNT(DISTINCT token) FROM range_blocks WHERE day=? AND user=?",
                                             (day, user)).fetchone()[0]
    except sqlite3.Error:
        pass
    out["pnl_usd"] = round(out["pnl_usd"], 2)
    blk = ", ".join(f"{b['reason']} {b['tokens']}" for b in out["top_blocks"]) or "-"
    out["text"] = (f"range demo danas: {out['trades']} tradeova (cilj {out['goal']})"
                   + (f", od toga reclaim {out['reclaims']}" if out["reclaims"] else "")
                   + f"; otvoreno {out['open']}, zatvoreno {out['closed']} ({out['pnl_usd']:+.2f} $); "
                   f"najviše blokira (tokena): {blk}; pregledano tokena {out['tokens_seen']}")
    return out


def _demo_log(con, user, now):
    """The counter's log line when the day's count changed and at least once every DEMO_LOG_S."""
    try:
        d = demo_today(con, now, user)
    except Exception:  # noqa: BLE001 - the counter never stops an entry pass
        return None
    key = (user, d["day_start"], d["trades"])
    last = _CACHE.get("demo_log") or (None, 0.0)
    if last[0] == key and now - last[1] < DEMO_LOG_S:
        return None
    _CACHE["demo_log"] = (key, now)
    print(d["text"], flush=True)
    return d["text"]


def _sized(lot, liq, sol, rng):
    """11.11. (owner's rules B / C): the lot within the 2 % slippage stake and x the 1 h volume factor (trade/cost)."""
    if lot <= 0:
        return lot
    vol = ((rng or {}).get("metrics") or {}).get("vol_h1")
    return round(_cost.size_sol(lot, liq, sol, vol), 6)


def _candidate(r, cfg=None):
    """An active range with score >= score_min and the price in the lower 40 % (or unknown): worth a look this pass.
    cfg (14.11.): the rule set's score_min (rules.DEMO: 0.6)."""
    return bool(r and r.get("active") and (r.get("score") or 0) >= rules._r(cfg)["score_min"] - 1e-9
                and (r.get("pos_pct") is None or r["pos_pct"] <= 40))


def _order(r):
    """14.11. (DEMO): the order the demo candidates are tried in (max_open may not leave room for all): a token that
    survived the crash first (rangedca/survivor ok), then the lowest place in the range, then the best score."""
    r = r or {}
    return (not (r.get("survivor") or {}).get("ok"), r.get("pos_pct") if r.get("pos_pct") is not None else 100.0,
            -(r.get("score") or 0))


def _flip_shadow(con, users, toks, rngs, mk, now, mflip):
    """range_flip's shadow rows for accounts that trade today's rules: one row when the new rules decide a lot 1
    otherwise than today's (blocked by a pause / a flip candidate, or added on the range after a break), at most once
    per token and account every SHADOW_EVERY_S."""
    n = 0
    for user in users:
        for tok in sorted(toks):
            mq = mk.get(tok)
            if not mq or not mq[0] or now - _SHADOWED.get((FLIP_FLAG, user, tok), 0) < SHADOW_EVERY_S:
                continue
            rng = rngs.get(tok)
            if not rng or not allowed(rng, user, now):
                continue
            nr = rules.new_range(rng)
            old, new = entry_view(rng, mq[0], now), entry_view(nr, mq[0], now)
            if (old is None) == (new is None):
                continue
            _SHADOWED[(FLIP_FLAG, user, tok)] = now
            fl = rng.get("flip") or {}
            z = rng.get("zones") or {}
            _flags().shadow(con, FLIP_FLAG, None, tok, "range ulaz lot 1" if old is None else f"bez ulaza ({old})",
                            "range ulaz lot 1 (raspon nakon proboja)" if new is None else f"blokirano ({new})",
                            {"user": user, "state": fl.get("state"), "mc": mq[3], "mode": mflip,
                             "stop_old_px": rules.levels_of(rules.atr_range(rng))["stop_px"] if z.get("range_low_low")
                             else None,
                             "stop_new_px": (rules.new_range(rng, ("atr",)) or {}).get("stop_px"), "zone": fl.get("zone")},
                            now)
            n += 1
    if n:
        con.commit()
    return n


def _lot1(con, user, tok, rng, mq, lim, sol, now, new=False, flip_log=None, cfg=None, blocks=None):
    """Lot 1 of a new round. new: the account trades range_flip's new rules (rules.new_range); flip_log (range_flip's
    mode): the account trades today's rules and the would-be stop is kept and logged next to the round's. cfg
    (14.11.): rules.DEMO for the demo profile (its entry, the round's levels rules.demo_levels); blocks: {token: why}
    gets the reason when no lot is bought (the daily counter)."""
    if not mq or not mq[0]:
        if blocks is not None:
            blocks[tok] = "nema tržišne cijene (DexScreener)"
        return []
    price, liq, _url, mcap = mq[:4]
    base = rng
    rng = rules.atr_range(rules.new_range(rng) if new else rng)   # 11.11. (decision 1): the ATR stop, every account
    why = entry_view(rng, price, now, cfg=cfg)
    if why is None and (_held(con, user, tok) or _cooldown(con, user, tok, now)):
        why = "već drži token ili je u pauzi nakon runde"
    if why is None:
        why = _guards(tok, mq)
    lot = rules.lot_sizes(lim["size_sol"], lim["dca_token_cap"])
    if why is None and lot <= 0:
        why = "dca_cap manji od pola uloga"
    lot = _sized(lot, liq, sol, rng)
    if why is None and lot <= 0:
        why = "volumen 1 h ispod $3k"
    if why is None and _spent_today(con, user, now, sol) + lot > lim["max_sol_per_day"] + 1e-9:
        why = "dnevni limit SOL-a za range ulaze"
    if why:
        if blocks is not None:
            blocks[tok] = why
        return []
    sym = (mq[4] if len(mq) > 4 else None) or rng.get("symbol")
    try:
        tid = _buy(con, user, tok, sym, lot * sol, price, liq, mcap, SRC1, False)
    except ValueError as e:
        print(f"range {user} {tok[:6]}: ulaz nije prošao ({e})", flush=True)
        if blocks is not None:
            blocks[tok] = f"kupnja nije prošla ({e})"
        return []
    lv = rules.levels_of(rng)
    if cfg:   # 14.11. (DEMO): TP +10 / +15 % net from this entry, the stop held at -12..-25 % from it
        lv = rules.demo_levels(lv, price, _cost.round_trip(lot * sol, liq), cfg)
    lv["supply"] = (mcap / price) if mcap and price else (rng.get("metrics") or {}).get("supply")
    srcs = base.get("sources") or [base.get("source") or "signal"]   # 11.11.: the round's source (EV per source, gate)
    lv["src"] = next((s for s in market.SRC_ORDER if s in srcs), "signal")
    if (rng.get("zones") or {}).get("range_low"):   # 11.11.: range_low (the bottom zone's average): a reclaim's line
        lv["rl"] = rng["zones"]["range_low"]
    nr = None
    if new:   # range_flip: the round follows the new rules to its end (fresh levels from rules.new_range)
        lv["rules"] = "flip"
        lv["flip_state"] = (base.get("flip") or {}).get("state")
        if (base.get("zones") or {}).get("range_low_low"):
            lv["old_stop_px"] = base["zones"]["range_low_low"] * rules.RULES["stop_x"]
    elif flip_log and lv.get("stop_kind") != "atr":   # the would-be volatility stop on today's zones (also while the
        # new rules would block); 11.11.: not when today's stop already IS the ATR stop (decision 1), nothing differs
        nr = rules.new_range(base, ("atr",))
        if nr and nr.get("stop_px"):
            lv["flip_stop_px"] = nr["stop_px"]
    con.execute("INSERT INTO range_rounds (user, token, symbol, opened_ts, status, lot1_id, lot1_sol, entry_mc, score, "
                "levels, state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user, tok, sym, now, "open", tid, lot, mcap, rng.get("score"), json.dumps(lv), json.dumps({})))
    if lv.get("flip_stop_px"):
        _flags().shadow(con, FLIP_FLAG, None, tok, f"stop {lv['stop_px']:.6g} (range_low_low × 0,85)",
                        f"stop {lv['flip_stop_px']:.6g} (range_low_low − 1,5 × ATR, {nr.get('stop_kind')})",
                        {"user": user, "lot1_id": tid, "mc": mcap, "supply": lv["supply"], "mode": flip_log}, now)
    con.commit()
    extra = ""
    if cfg and lv.get("supply"):
        sup = lv["supply"]
        extra = (f"; demo 14.11.: TP1 MC ${lv['tp1_px'] * sup:,.0f} (+{cfg['tp1_net']:.0%} neto), ostatak MC "
                 f"${rules.tp2_of(lv) * sup:,.0f}, stop MC ${lv['stop_px'] * sup:,.0f} ({lv['stop_px'] / price - 1:+.0%}); "
                 f"{(base.get('survivor') or {}).get('why') or ''}")
    return [(user, f"range lot 1 {sym or tok[:6]}: {lot:g} SOL na MC ${mcap or 0:,.0f} (raspon "
                   f"{rng.get('pos_pct') or 0:.0f} %, ocjena {rng.get('score') or 0:.2f}){extra}")]


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
    if _is_new(r) and rules.flip_block(rng):   # range_flip: no lot 2 while paused or a flip candidate
        return []
    pc = rules.profile_cfg(r["levels"])
    if pc and pc.get("lot2") is False:   # 14.11. (DEMO): one lot, no DCA under the clamped stop
        return []
    lv = _levels_now(r, rng, now)
    mets = (rng or {}).get("metrics") if rng and now - (rng.get("mts") or rng.get("ts") or 0) <= METRICS_FRESH_S else None
    why = rules.lot2_check(t1[0], price, lv, mets)
    lot = rules.lot_sizes(lim["size_sol"], lim["dca_token_cap"], held_sol=r["lot1_sol"] or 0)
    if why is None and lot <= 0:
        why = "dca_cap: nema mjesta za lot 2"
    lot = _sized(lot, liq, sol, rng)
    if why is None and lot <= 0:
        why = "volumen 1 h ispod $3k"
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
    note = f"range: {_hr(reason, r.get('levels'))}"
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


def _flip_stop_shadow(con, r, rng, st, price, mcap, age, now):
    """range_flip shadow on a round that trades today's rules: its would-be volatility stop (levels flip_stop_px)
    only tightens with the newer range like the real stop, and the first time the price is at or under it while
    today's stop has not sold, one shadow row (state flip_stop_seen)."""
    fresh = _fresh_levels(rng, now, ("atr",)) if rng and rng.get("flip") else None
    fsp = max(r["levels"]["flip_stop_px"], (fresh or {}).get("stop_px") or 0)
    if fsp != r["levels"]["flip_stop_px"]:
        r["levels"]["flip_stop_px"] = fsp
        con.execute("UPDATE range_rounds SET levels=? WHERE id=?", (json.dumps(r["levels"]), r["id"]))
        con.commit()
    stop = max(r["levels"].get("stop_px") or 0, ((_fresh_levels(rng, now) or {}).get("stop_px") or 0))
    if price <= fsp and price > stop and age <= STALE_S and not st.get("flip_stop_seen"):
        st["flip_stop_seen"] = int(now)
        _flags().shadow(con, FLIP_FLAG, None, r["token"], f"drži (stop {stop:.6g})", f"ATR stop {fsp:.6g} bi prodao",
                        {"user": r["user"], "round_id": r["id"], "px": price, "mcap": mcap}, now)
        con.commit()


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
    try:   # 11.11. (Jure: HAOBIBI rugged): a hard block ends a pin, a counterfactual win and the token's open round
        from . import owner
        owner.auto_check(con, market_fn, now)
    except Exception as e:  # noqa: BLE001 - the exits below never wait for it
        print(f"range: provjera pinova / oznaka: {type(e).__name__}: {e}", flush=True)
    open_r = rounds(con)
    if not open_r:
        return []
    from league import exitplan
    q = exitplan.quote(market_fn, {r["token"] for r in open_r}, now)
    flip_on = _flags().mode(FLIP_FLAG) != "off"
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
        lv = _levels_now(r, rng, now)
        st = r["state"]
        before = json.dumps(st, sort_keys=True)
        if flip_on and r["levels"].get("flip_stop_px"):   # range_flip shadow: the would-be stop of a today's-rules round
            _flip_stop_shadow(con, r, rng, st, price, mcap, age, now)
        gu = ((rng or {}).get("state") or {}).get("give_up")
        hit = None
        if gu and gu.get("ts", 0) >= r["opened_ts"] and age <= STALE_S:
            hit = (f"odustajanje: {gu.get('why')}", 1.0)
        else:
            hit = rules.exit_step(lv, st, price, now, r["opened_ts"], _be_px(lots, liq), stale=age > STALE_S,
                                  cfg=rules.profile_cfg(r["levels"]))   # 14.11.: a demo round by DEMO's exits
        if lv["stop_px"] != r["levels"].get("stop_px"):   # the stop tightened with the newer range: kept
            r["levels"]["stop_px"] = lv["stop_px"]
            if lv.get("stop_kind"):   # 11.11.: the kind of the stop that won (an old x 0.85 round under the ATR stop)
                r["levels"]["stop_kind"] = lv["stop_kind"]
            con.execute("UPDATE range_rounds SET levels=? WHERE id=?", (json.dumps(r["levels"]), r["id"]))
        if hit:
            reason, frac = hit
            st["last"] = reason
            try:
                pnl = _sell(con, r, lots, reason, frac, price, liq, mcap)
            except ValueError as e:   # closed in the same second by another path: next pass
                print(f"range {r['token'][:6]}: {e}", flush=True)
                continue
            if flip_on and reason == "stop" and r["levels"].get("flip_stop_px") and price > r["levels"]["flip_stop_px"] \
                    and not st.get("flip_stop_seen"):   # range_flip shadow: today's stop sold, the volatility stop not
                st["flip_stop_seen"] = int(now)
                _flags().shadow(con, FLIP_FLAG, None, r["token"], "tvrdi stop prodao (range_low_low × 0,85)",
                                f"drži (ATR stop {r['levels']['flip_stop_px']:.6g} niže)",
                                {"user": r["user"], "round_id": r["id"], "px": price, "mcap": mcap,
                                 "stop_px": lv["stop_px"], "flip_stop_px": r["levels"]["flip_stop_px"]}, now)
            con.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(st), r["id"]))
            con.commit()
            text = (f"range {r['user']} {r['symbol'] or r['token'][:6]}: {_hr(reason, r['levels'])}"
                    f"{reason[len('odustajanje'):] if reason.startswith('odustajanje') else ''}, prodano {frac:.0%} "
                    f"na MC ${mcap or 0:,.0f}, {pnl:+.2f} $")
            if not _lots(con, r):
                tot = _finish(con, r, reason, now)
                text += f"; runda gotova {tot:+.2f} $"
                arm = _arm_reclaim(r, rng, lv, reason, price, now)
                if arm:   # 11.11. (decision 1): the stopped round's reclaim window (run_once buys it, or not)
                    st["reclaim"] = arm
                    con.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(st), r["id"]))
                    con.commit()
                    text += f"; reclaim moguć do {time.strftime('%H:%M', time.gmtime(arm['until']))} UTC"
            out.append(text)
        elif json.dumps(st, sort_keys=True) != before:
            con.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(st), r["id"]))
            con.commit()
    return out


# ---------- 11.11. reclaim (the owner's decision 1) -----------------------------------------------------------------
def _stopped(reason):
    """A stop-out: the hard stop, or the "range broken downward" give-up (a stop in effect, as backtest.simulate)."""
    return reason == "stop" or (reason.startswith("odustajanje") and "probijen dolje" in reason)


def _arm_reclaim(r, rng, lv, reason, price, now):
    """The reclaim window of a round that just ended (state "reclaim"), None when it is no stop-out or the round was a
    reclaim itself (one reclaim per stopped round). rl: range_low at lot 1 (levels "rl"), else the range's now, else
    range_low_low; low: the stop-out price (run_once lowers it); atr: the range's ATR now (None: x 0.85)."""
    if not _stopped(reason) or r["levels"].get("reclaim"):
        return None
    rl = r["levels"].get("rl") or ((rng or {}).get("zones") or {}).get("range_low") or lv.get("rll") \
        or r["levels"].get("rll")
    if not rl:
        return None
    return {"until": int(now) + rules.RECLAIM["window_s"], "rl": rl, "low": price, "atr": rules.atr_of(rng),
            "levels": {k: lv.get(k) for k in ("rll", "rlt", "rhl", "rht", "floor_px")}, "done": None}


def _armed(con, now):
    """[closed round dicts] whose reclaim window is open (state "reclaim", not done, until >= now)."""
    try:
        rows = con.execute("SELECT * FROM range_rounds WHERE status='closed' AND closed_ts >= ? AND state LIKE "
                           "'%\"reclaim\"%'", (int(now) - rules.RECLAIM["window_s"] - 60,))
    except sqlite3.Error:
        return []
    cols = [c[0] for c in rows.description]
    out = []
    for row in rows.fetchall():
        d = dict(zip(cols, row))
        d["levels"], d["state"] = json.loads(d["levels"] or "{}"), json.loads(d["state"] or "{}")
        a = d["state"].get("reclaim")
        if a and not a.get("done") and now <= (a.get("until") or 0):
            out.append(d)
    return out


def _reclaim(con, user, r, rng, mq, lim, sol, now, n_open):
    """One armed reclaim of `user` (the stopped round r): lowers its `low`, buys lot 1 of the reclaim round when
    rules.reclaim_check passes and the guards and limits hold. [(user, text)]."""
    a = r["state"]["reclaim"]
    tok = r["token"]
    if not mq or not mq[0]:
        return []
    price, liq, _url, mcap = mq[:4]
    if price < (a.get("low") or price):   # the new low: the lowest price the loops saw since the stop-out
        a["low"] = price
        con.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(r["state"]), r["id"]))
        con.commit()
    if n_open >= lim["max_open"] or not may_reclaim(user, now):
        return []
    if not allowed(rng or {"source": r["levels"].get("src") or "signal"}, user, now):
        return []   # a market / event token never on the real account (paper_only)
    fresh = rng and now - (rng.get("mts") or rng.get("ts") or 0) <= METRICS_FRESH_S
    why = rules.reclaim_check(a, price, (rng or {}).get("metrics") if fresh else None, now)
    if why is None and (_held(con, user, tok) or
                        con.execute("SELECT 1 FROM range_rounds WHERE status='open' AND user=? AND token=?",
                                    (user, tok)).fetchone()):
        why = "već drži token"
    if why is None:
        why = _guards(tok, mq)
    lot = rules.lot_sizes(lim["size_sol"], lim["dca_token_cap"])
    lot = _sized(lot, liq, sol, rng)
    if why is None and lot <= 0:
        why = "ulog 0 (dca_cap ili volumen 1 h)"
    if why is None and _spent_today(con, user, now, sol) + lot > lim["max_sol_per_day"] + 1e-9:
        why = "dnevni limit SOL-a za range ulaze"
    if why:
        return []
    stop, kind = rules.reclaim_stop(a["low"], a.get("atr") or rules.atr_of(rng))
    if not stop or price <= stop:
        return []
    sym = (mq[4] if len(mq) > 4 else None) or r.get("symbol")
    try:
        tid = _buy(con, user, tok, sym, lot * sol, price, liq, mcap, SRC1, False)
    except ValueError as e:
        print(f"range {user} {tok[:6]}: reclaim nije prošao ({e})", flush=True)
        return []
    lv = {k: v for k, v in (a.get("levels") or {}).items() if v is not None}
    lv.update(stop_px=stop, stop_kind=kind, reclaim=True, reclaim_of=r["id"], low_px=a["low"], rl=a["rl"],
              src=r["levels"].get("src") or "signal",
              supply=(mcap / price) if mcap and price else r["levels"].get("supply"))
    lv["floor_px"] = max(lv.get("floor_px") or 0, stop)
    cur = con.execute("INSERT INTO range_rounds (user, token, symbol, opened_ts, status, lot1_id, lot1_sol, entry_mc, "
                      "score, levels, state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (user, tok, sym, int(now), "open", tid, lot, mcap, r.get("score"), json.dumps(lv), json.dumps({})))
    a["done"], a["round_id"] = int(now), cur.lastrowid
    con.execute("UPDATE range_rounds SET state=? WHERE id=?", (json.dumps(r["state"]), r["id"]))
    con.commit()
    sup = lv.get("supply")
    return [(user, f"range reclaim {sym or tok[:6]}: lot 1 {lot:g} SOL na MC ${mcap or 0:,.0f} (natrag iznad range_low "
                   f"{(a['rl'] * sup) if sup else 0:,.0f}, kupnje {((rng or {}).get('metrics') or {}).get('buy_share_5m') or 0:.0%}"
                   f"), stop ispod novog dna MC ${(stop * sup) if sup else 0:,.0f}")]


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
