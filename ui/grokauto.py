"""Grok autotrade (10.11. ~21:30, Jure: "autonomno trgovanje za Grok (MCP klijent), iza flaga grok_autotrade
(default off, uključujem ga ja)").

While the owner has switched it ON (Autopilot page, owner only; no MCP tool can switch it on or change its limits),
an MCP execute_trade with require_approval=false is executed at once instead of waiting for the owner's tap:

  buy   only within Grok's OWN limits (trade settings, the owner edits them on the page; get_scoring_config and
        get_portfolio_status show them read-only): grok_max_sol_per_trade 0.1, grok_max_sol_per_day 0.3,
        grok_max_open 3 (open Grok positions), grok_max_loss_day 0.15 SOL. Before every buy the rug check and the
        liquidity checks of the Autopilot's copies run again (league/copy: price, bonded only, liquidity, 30k MC,
        fake pool, pool vs MC, rug, supply concentration; 11.11.: liquidity at least $15k, trade/cost.LIQ_HARD_MIN,
        and never an event token of an active topic, trade/settings.NEVER_LIVE); a failed check rejects the buy. Then it goes
        through the owner's manual buy path (ui/pravitrade._post_buy): the same day-loss stop, wallet balance, the
        owner's per-token cap (dca_cap_owner) and the real swap by run_trade.py in the mode the Autopilot is in
        (dry / trial / live; CLAUDE.md: real money only when the Autopilot is live).
  sell  any open position (Grok's or the Autopilot's / the owner's), any share, no size limit, while the switch is on
        (also while paused by the day loss: a sale only lowers the risk).

11.11. (flag grok_ev_gate, momentum/evgate.py): a buy may carry p_tp (Grok's probability that TP comes before SL) and
strategy (momentum_scalp | range_dca | other). The gate prices EV = p_tp x TP - (1 - p_tp) x SL - cost with the
strategy's TP / SL; shadow logs what it would refuse, paper / live refuse (11.11., owner's rule D) an EV under +3 % or
a strategy without Grok's measured proof (n >= 10, the 90 % interval above 0), and a buy without p_tp, with the reason;
then the buy gets that strategy's TP / SL as its exit. Every request with p_tp is recorded for calibration.

When Grok's realized result today (Zagreb day, its positions closed today, fees included) reaches -grok_max_loss_day,
autotrade pauses itself until midnight Zagreb ("paused_until"); the owner's "Ugasi Grok autotrade" turns it off until
he switches it on again. Every autotrade is logged (trade settings "grok_auto_log": client grok_auto, reason, result),
shown on the Autopilot page labelled "Grok auto", and sent to the owner on Telegram when TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are set (the page shows it either way).

Why this is a risk and how it is bounded: the client is an LLM that reads public posts, and a crafted post has made
Grok order a transfer before (May 2026). There is no transfer tool; autotrade can only swap within the limits above.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from trade import settings

STATE_KEY = "grok_autotrade"
LOG_KEY = "grok_auto_log"
CLIENT = "grok_auto"
SRC = "Grok auto (MCP)"
LIMITS = {   # key: (default, label, lo, hi)
    "grok_max_sol_per_trade": (0.1, "Grok: najviše SOL po kupnji", 0.01, 1.0),
    "grok_max_sol_per_day": (0.3, "Grok: najviše SOL kupnji u danu", 0.01, 5.0),
    "grok_max_open": (3, "Grok: najviše otvorenih pozicija", 1, 10),
    "grok_max_loss_day": (0.15, "Grok: dnevni gubitak nakon kojeg staje do ponoći (SOL)", 0.01, 2.0),
    # 12.11. (owner's order point 4): rounds in ONE token per Zagreb day (round_info: a round = a buy while Grok holds
    # no open position in the token; a DCA lot into the open one is not a new round). Not a money cap: no "grok_"
    # prefix, so trade/executor.LIVE_CAPS (Grok's money limits) stays as it is
    "max_round_trips_per_token_day": (3, "Grok: najviše krugova (kupnja → izlaz) u istom tokenu u danu", 1, 20),
}
INT_LIMITS = ("grok_max_open", "max_round_trips_per_token_day")
# 12.11. (owner's order point 4): after this many stop-outs in one token in a Zagreb day, no new buy of it that day
MAX_STOP_OUTS_DAY = 2
# what closes a lot by a STOP (league trades exit_rule / note): the Autopilot's SL ("auto SL …" -> sl), the Smart sell's
# own stop (smart_sl), a stop the grace turned into a rug (rug) and an exit plan's hard stop ("plan izlaza: plan_stop",
# stored as exit_rule manual because plan_* is not in league/store.EXIT_RULES)
STOP_RULES = ("sl", "smart_sl", "rug")
STOP_NOTES = ("auto SL", "plan izlaza: plan_stop")
REAL_FIRST_S = 120   # a real position closed this long before its demo lot was sold first (a sell button / Grok's sell)
ROUND_KEY = "grok_round_marks"   # trade settings {league trade id: "new" | "dca"}: what each Grok buy opened (last 300)

TX_WAIT_S = float(os.environ.get("GROK_TX_WAIT_S", "20"))   # how long execute_trade waits for the swap's signature
TZ = "Europe/Zagreb"


def _day_start(now):
    from trade import executor
    return executor._day_start(now, TZ)


def limits(tcon):
    raw = settings.raw(tcon)
    out = {}
    for k, (d, _lab, lo, hi) in LIMITS.items():
        try:
            v = float(raw.get(k, d))
        except (TypeError, ValueError):
            v = d
        out[k] = int(v) if k in INT_LIMITS else v
        if not lo <= out[k] <= hi:
            out[k] = d
    return out


def set_limits(tcon, form, who):
    """The owner's form (Autopilot page): every key of LIMITS within its range, else ValueError."""
    for k, (_d, lab, lo, hi) in LIMITS.items():
        if k not in form:
            continue
        v = float(str(form[k]).replace(",", "."))
        if not lo <= v <= hi:
            raise ValueError(f"{lab}: mora biti {lo:g}-{hi:g}")
        settings.put(tcon, k, int(v) if k in INT_LIMITS else round(v, 4), who)


def state(tcon, now=None):
    """{"on", "active", "paused_until", "pause_reason", "since", "who"}: on = the owner's switch; active = on and not
    paused by the day loss (an expired pause is cleared here)."""
    now = now or time.time()
    s = settings.raw(tcon).get(STATE_KEY) or {}
    s = s if isinstance(s, dict) else {}
    on = bool(s.get("on"))
    pu = s.get("paused_until") or 0
    if pu and now >= pu:
        pu = 0
    return {"on": on, "active": on and not pu, "paused_until": int(pu) or None, "pause_reason": s.get("pause_reason") if pu else None,
            "since": s.get("since"), "who": s.get("who")}


def set_on(tcon, on, who, now=None):
    """The owner's switch (the page checks is_owner). Off is the kill switch: it stays off until he switches it on."""
    now = int(now or time.time())
    settings.put(tcon, STATE_KEY, {"on": bool(on), "since": now, "who": who, "paused_until": None}, who)
    _log(tcon, {"ts": now, "side": "switch", "status": "on" if on else "off", "reason": f"vlasnik ({who})"})
    print(f"grok auto: {'UKLJUČEN' if on else 'ugašen'} ({who})", flush=True)


def _log(tcon, row):
    log = list(settings.raw(tcon).get(LOG_KEY) or [])
    log.insert(0, dict(row, client=CLIENT))
    settings.put(tcon, LOG_KEY, log[:300], CLIENT)


def log_rows(tcon, limit=20):
    return list(settings.raw(tcon).get(LOG_KEY) or [])[:limit]


def _league_ids(tcon):
    return [r["league_id"] for r in log_rows(tcon, 300) if r.get("side") == "buy" and r.get("status") == "executed"
            and r.get("league_id")]


def usage(tcon, now=None, lcon=None):
    """Grok's day so far (Zagreb): {"spent_sol", "open", "pnl_sol", "start"}. spent = executed buys today (the log);
    open = Grok's open demo trades (league.db, the real positions follow them); pnl = realized SOL of Grok's
    positions closed today minus the fees of their orders today (trade.db), as executor.day_pnl does for all."""
    now = now or time.time()
    start = _day_start(now)
    rows = log_rows(tcon, 300)
    spent = sum(float(r.get("amount") or 0) for r in rows
                if r.get("side") == "buy" and r.get("status") == "executed" and (r.get("ts") or 0) >= start)
    ids = _league_ids(tcon)
    n_open, pnl = 0, 0.0
    if ids:
        q = ",".join("?" * len(ids))
        own = lcon is None
        try:
            from league import store as lstore
            lcon = lcon or lstore.connect()
            n_open = lcon.execute(f"SELECT COUNT(DISTINCT token) FROM trades WHERE status='open' AND id IN ({q})", ids).fetchone()[0]
        except Exception:  # noqa: BLE001 - league.db unreadable: counted as nothing open
            n_open = 0
        finally:
            if own and lcon is not None:
                lcon.close()
        pnl = tcon.execute(f"SELECT COALESCE(SUM(sol_back - sol_in), 0) FROM positions WHERE status='closed' AND closed_ts>=? "
                           f"AND league_id IN ({q})", (start, *ids)).fetchone()[0] or 0.0
        fees = tcon.execute(f"SELECT COALESCE(SUM(o.fee_lamports), 0) FROM orders o JOIN positions p ON p.id=o.position_id "
                            f"WHERE o.ts>=? AND p.league_id IN ({q})", (start, *ids)).fetchone()[0] or 0
        pnl -= fees / 1e9
    return {"spent_sol": round(spent, 6), "open": int(n_open), "pnl_sol": round(pnl, 6), "start": start}


def remaining(tcon, now=None, lcon=None):
    lim, u = limits(tcon), usage(tcon, now, lcon)
    return {"sol_today": round(max(0.0, lim["grok_max_sol_per_day"] - u["spent_sol"]), 6),
            "open_slots": max(0, lim["grok_max_open"] - u["open"]),
            "loss_left_sol": round(max(0.0, lim["grok_max_loss_day"] + min(0.0, u["pnl_sol"])), 6),
            "used": u}


def _mark_round(tcon, tid, new):
    marks = dict(settings.raw(tcon).get(ROUND_KEY) or {})
    marks[str(tid)] = "new" if new else "dca"
    settings.put(tcon, ROUND_KEY, dict(list(marks.items())[-300:]), CLIENT)


def _stop_exit(rule, note):
    n = note or ""
    return (rule or "") in STOP_RULES or n.startswith(STOP_NOTES)


def _lot_end(lot, real):
    """(closed at, closed by a stop) of one Grok lot, None while it is open. The demo lot is the book the exits run on
    (league auto TP/SL, the exit plan); run_trade sells the real position seconds after it closes. A real position
    sold FIRST (a sell button, Grok's execute_trade sell, Prodaj sve: the demo lot stays open) ends the lot when the
    real one closed, and that is no stop-out."""
    lc = lot["closed_ts"] if lot.get("status") == "closed" else None
    rc = real[1] if real and real[0] == "closed" else None
    if lc is not None and not (rc is not None and rc < lc - REAL_FIRST_S):
        return lc, _stop_exit(lot.get("exit_rule"), lot.get("note"))
    if rc is not None:
        return rc, False
    return None, False


def round_info(tcon, lcon, token, now=None):
    """12.11. (owner's order point 4: "više krugova na istom tokenu"): Grok autotrade's rounds in one token.
    A lot = one Grok autotrade buy (league trades of the real-trade account, source SRC). A ROUND starts with a lot
    bought while no earlier Grok lot of the token is open; a lot bought while one is open is a DCA lot of that round.
    A round ends when its last lot closes (_lot_end) and is a STOP-OUT when that last close was a stop (STOP_RULES /
    STOP_NOTES; a time stop, TP, trailing or a sale is not). Zagreb day as Grok's other day limits: a round counts on
    the day it STARTED, a stop-out on the day it HAPPENED.
    {"open": a round is open now, "rounds_today", "stop_outs_today", "rounds": [{start, end, stop, lots}]}."""
    now = now or time.time()
    start = _day_start(now)
    try:
        lots = [dict(r) for r in lcon.execute("SELECT * FROM trades WHERE user=? AND token=? AND source=? "
                                              "ORDER BY opened_ts, id", (settings.LEAGUE_USER, token, SRC))]
    except Exception:  # noqa: BLE001 - no league tables yet: no rounds
        lots = []
    real = {}
    if lots:
        ids = [t["id"] for t in lots]
        for lid, st, cts in tcon.execute(f"SELECT league_id, status, closed_ts FROM positions WHERE league_id IN "
                                         f"({','.join('?' * len(ids))}) ORDER BY id", ids):
            real[lid] = (st, cts)
    marks = settings.raw(tcon).get(ROUND_KEY) or {}
    rounds = []
    for t in lots:
        end, stop = _lot_end(t, real.get(t["id"]))
        cur = rounds[-1] if rounds else None
        mark = marks.get(str(t["id"]))   # what the buy itself saw (exact); older lots: their times
        if cur is None or (mark == "new" if mark in ("new", "dca")
                           else cur["end"] is not None and cur["end"] <= (t["opened_ts"] or 0)):
            rounds.append({"start": t["opened_ts"] or 0, "end": end, "stop": stop, "lots": [t["id"]],
                           "_ends": [(end, stop)]})
            continue
        cur["lots"].append(t["id"])
        cur["_ends"].append((end, stop))
        if any(e is None for e, _s in cur["_ends"]):
            cur["end"], cur["stop"] = None, False
        else:
            last = max(e for e, _s in cur["_ends"])
            cur["end"], cur["stop"] = last, any(s for e, s in cur["_ends"] if e == last)
    for r in rounds:
        r.pop("_ends", None)
    return {"open": bool(rounds) and rounds[-1]["end"] is None,
            "rounds_today": sum(1 for r in rounds if r["start"] >= start),
            "stop_outs_today": sum(1 for r in rounds if r["stop"] and r["end"] is not None and r["end"] >= start),
            "rounds": rounds}


def round_block(tcon, lcon, token, amount, now=None):
    """12.11.: (English reason for MCP, Croatian for the page and the log) when the round rules refuse this buy, else
    None: MAX_STOP_OUTS_DAY stop-outs in the token today (any buy, a DCA too), or a NEW round over
    max_round_trips_per_token_day. Grok's SOL in the token (dca_token_cap) is checked by token_cap_block."""
    ri = round_info(tcon, lcon, token, now)
    lim = limits(tcon)["max_round_trips_per_token_day"]
    if ri["stop_outs_today"] >= MAX_STOP_OUTS_DAY:
        return ((f"{ri['stop_outs_today']} stop-outs in this token today (Zagreb day): after {MAX_STOP_OUTS_DAY} "
                 "no new buy of it until midnight Zagreb"),
                (f"{ri['stop_outs_today']} izlaza stopom u ovom tokenu danas: nakon {MAX_STOP_OUTS_DAY} nova kupnja tog "
                 "tokena tek sutra (zagrebački dan)"))
    if not ri["open"] and ri["rounds_today"] >= lim:
        return ((f"max_round_trips_per_token_day: {ri['rounds_today']} rounds in this token today (Zagreb day), at "
                 f"most {lim}; a round starts with a buy while you hold no open position in the token (a DCA into an "
                 "open one is not a new round)"),
                (f"najviše {lim} krugova u istom tokenu u danu: danas ih je već {ri['rounds_today']} (krug počinje "
                 "kupnjom kad Grok u tokenu nema otvorenu poziciju; dokup u otvorenu nije novi krug)"))
    return None


def token_cap_block(tcon, lcon, token, amount):
    """12.11.: (English, Croatian) when this buy would put more than dca_token_cap SOL in the token (what is still held
    on the account the buy goes to, a fresh lot run_trade has not mirrored yet included: pravitrade.held_sol_now),
    else None. ui/pravitrade._grok_rules refuses the same again on the buy path (also for approved requests)."""
    from ui import pravitrade
    cap = float(settings.raw(tcon).get("dca_token_cap") or settings.DCA_TOKEN_CAP)
    held = pravitrade.held_sol_now(lcon, tcon, token)
    if held + amount > cap + 1e-9:
        return ((f"dca_token_cap: {held:.3f} SOL already in this token + {amount:g} = {held + amount:.3f}, at most "
                 f"{cap:g} SOL per token"),
                (f"u tokenu bi bilo {held + amount:.3f} SOL (otvoreno {held:.3f} + {amount:g}), najviše {cap:g} SOL po "
                 "tokenu (Grokov limit)"))
    return None


def close_stale(tcon, lcon, token, price, liq, mcap=None):
    """12.11. ("otvori, zatvori, ponovno otvori"): Grok's open demo lots in the token whose real position is already
    closed (sold by a button or by Grok's execute_trade sell: the demo lot stays open) are closed on the demo book
    before a new round, so the new round's exit (average entry, TP/SL, plan) is its own. Only demo bookkeeping: their
    real position is closed, run_trade has nothing left to sell. Returns how many lots were closed."""
    from league import store as lstore
    lots = lcon.execute("SELECT id FROM trades WHERE user=? AND token=? AND source=? AND status='open'",
                        (settings.LEAGUE_USER, token, SRC)).fetchall()
    n = 0
    for (lid,) in lots:
        r = tcon.execute("SELECT status FROM positions WHERE league_id=? ORDER BY id DESC LIMIT 1", (lid,)).fetchone()
        if not r or r[0] != "closed":
            continue
        try:
            lstore.sell(lcon, settings.LEAGUE_USER, lid, price, liq, "Grok auto: pravi račun već prodan (novi krug)",
                        mcap=mcap, exit_rule="manual")
            n += 1
        except ValueError:
            pass
    if n:
        print(f"grok auto: {token[:6]} {n} demo lot(a) zatvoreno (pravi račun već prodan), novi krug", flush=True)
    return n


def maybe_pause(tcon, now=None, lcon=None):
    """Pause until midnight Zagreb when today's realized loss reached grok_max_loss_day. Returns True when paused now."""
    now = now or time.time()
    st = state(tcon, now)
    if not st["active"]:
        return False
    lim, u = limits(tcon), usage(tcon, now, lcon)
    if u["pnl_sol"] > -lim["grok_max_loss_day"] + 1e-12:
        return False
    until = _day_start(now) + 86400
    until = _day_start(until + 3600) if until <= now else until   # a 23/25-hour day around the clock change
    s = dict(settings.raw(tcon).get(STATE_KEY) or {})
    why = f"dnevni gubitak {u['pnl_sol']:+.3f} SOL (granica −{lim['grok_max_loss_day']:g})"
    s.update(paused_until=int(until), pause_reason=why)
    settings.put(tcon, STATE_KEY, s, CLIENT)
    _log(tcon, {"ts": int(now), "side": "switch", "status": "paused", "reason": why})
    notify(f"Grok autotrade je stao do ponoći: {why}.")
    return True


def safety(token, market=None):
    """The checks of the Autopilot's copies (league/copy._enter) again, now: None when the token passes, else why
    (a rug risk rating included; execute() lets fresh Grok evidence override only that part, safety_ex)."""
    why, risk = safety_ex(token, market)
    return why or (risk[0] if risk else None)


def safety_ex(token, market=None):
    """(why, risk). why: a check nothing overrides (price, bonded, the pool gates, a collapse, the rug archive, mint /
    freeze authority, RugCheck rugged, honeypot). risk: the rug RISK ratings (supply concentration, the rug filter's
    ODBAČEN / VISOK RIZIK verdict; 10.11. BOXCAT: the verdict was not checked here before) that fresh Grok evidence
    may override at half size (ui/kandidati.py, the same rule get_trade_candidates shows)."""
    from league import copy
    mk = (market or copy.market)({token}) or {}
    m = mk.get(token)
    if not m or not m[0]:
        return "nema cijene tog tokena (DexScreener)", []
    if copy._dex_pair_empty(m):
        return "DexScreener ima par, ali trenutno bez cijene/likvidnosti", []
    price, liq, _, mcap = m[:4]
    c = copy.CFG
    if copy._bonding_curve(m):
        return "token je još na pump.fun krivulji; uzimaju se samo bondani", []
    from trade import cost as tcost
    floor = max(c["min_liq"], tcost.LIQ_HARD_MIN)   # 11.11. (owner's rule B): never under $15k
    if (liq or 0) < floor:
        return f"premala likvidnost (${liq or 0:,.0f}, treba ${floor:,.0f})", []
    if (mcap or 0) < c["min_mcap"]:
        return f"MC ${mcap or 0:,.0f} ispod 30k", []
    if mcap > c["max_mcap"]:
        return "velik token (preko $50M)", []
    if liq > mcap:
        return "lažni pool (likvidnost veća od market capa)", []
    if liq < c["min_liq_mcap"] * mcap:
        return f"likvidnost je samo {liq / mcap:.1%} MC-a (granica {c['min_liq_mcap']:.0%})", []
    col = copy._rugged(token, mcap, liq)
    if col:
        return f"token je rugan ({col['text']})", []
    ev_topic = event_topic(token)
    if ev_topic:   # 11.11. (trade/settings.NEVER_LIVE): event tokens are measured, at most paper, never real money
        return (f"event token (tema „{ev_topic}”): event tokeni nikad ne trguju pravim novcem (NEVER_LIVE), najviše "
                "paper na demo računu"), []
    from scan import filters
    from ui import kandidati
    src = kandidati.Sources()
    try:
        archived = src.archived()
    except Exception:  # noqa: BLE001
        archived = frozenset()
    rv = kandidati.rug_view(token, mcap, liq, src, filters.rug_tables(), archived)
    if rv["hard"]:
        return f"rug: {rv['hard'][0]}", []
    return None, rv["risk"]


def event_topic(token):
    """The name of an active event topic (topics.db, upcoming / live) the token belongs to, or None."""
    try:
        from topics import store as tstore
        con = tstore.ro()
    except Exception:  # noqa: BLE001 - no topics module / database: not an event token as far as we know
        return None
    if con is None:
        return None
    try:
        r = con.execute("SELECT t.name FROM topic_tokens tt JOIN event_topics t ON t.id = tt.topic_id WHERE tt.token = ? "
                        "AND t.status IN ('upcoming', 'live') LIMIT 1", (token,)).fetchone()
    except Exception:  # noqa: BLE001
        r = None
    finally:
        con.close()
    return r[0] if r else None


def notify(text):
    """The owner: Telegram when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set (in a thread: the MCP answer never
    waits on it); the server log always; the page shows the log anyway."""
    print(f"grok auto: {text}", flush=True)
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return

    def send():
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": f"MemeSonar · {text}",
                                           "disable_web_page_preview": "true"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15).read()
        except Exception as e:  # noqa: BLE001
            print(f"grok auto: telegram: {type(e).__name__}", flush=True)
    threading.Thread(target=send, daemon=True).start()


def _signature(tcon, league_id, side, since, wait_s):
    """The swap's signature for the real position behind league trade `league_id` ({"mode", "signature", "status"}),
    waiting up to wait_s for run_trade.py (it mirrors within seconds); None when nothing landed yet."""
    end = time.time() + max(0.0, wait_s)
    while True:
        r = tcon.execute("SELECT p.mode, o.signature, o.status FROM positions p JOIN orders o ON o.position_id=p.id "
                         "WHERE p.league_id=? AND o.side=? AND o.ts>=? ORDER BY o.id DESC LIMIT 1",
                         (league_id, side, int(since) - 5)).fetchone()
        if r and (r[1] or r[2] in ("failed", "error") or r[0] != "live"):
            return {"mode": r[0], "signature": r[1], "status": r[2]}
        if time.time() >= end:
            return None
        time.sleep(1.0)


def execute(body, now=None, wait_s=None, market=None):
    """(http status, answer) of an execute_trade with require_approval=false. The caller (ui/mcpapi.trade_request)
    has validated token / side / amount shape."""
    from league import copy, store as lstore
    from ui import pravitrade
    now = now or time.time()
    wait_s = TX_WAIT_S if wait_s is None else wait_s
    tok, side, amount = body["token"], body["side"], float(body["amount"])
    reason = str(body.get("reason") or "")[:300]
    tcon = settings.connect()
    try:
        st = state(tcon, now)
        if not st["on"]:
            return 403, {"status": "rejected", "reason": "grok_autotrade is off (the owner switches it on on the "
                         "Autopilot page); send require_approval=true to queue the trade for the owner"}
        row = {"ts": int(now), "side": side, "token": tok, "amount": amount, "reason": reason}

        def reject(why, code=409, hr=None):
            # 12.11.: why = the MCP's English reason; hr = the same in Croatian for the page and the log
            _log(tcon, dict(row, status="rejected", why=why, **({"why_hr": hr} if hr else {})))
            print(f"grok auto: odbijeno {side} {tok[:6]} {amount:g}: {hr or why}", flush=True)
            return code, {"status": "rejected", "reason": why}
        lcon = lstore.connect()
        try:
            copy.ensure(lcon)
            if side == "sell":
                ids = [str(i) for (i,) in tcon.execute("SELECT id FROM positions WHERE token=? AND status='open'", (tok,))]
                if not ids:
                    return reject("no open position in that token")
                req = dict(settings.raw(tcon).get("sell_req") or {})
                for pid in ids:
                    req[pid] = min(1.0, max(0.01, amount))
                settings.put(tcon, "sell_req", req, CLIENT)
                lids = [r[0] for r in tcon.execute(f"SELECT league_id FROM positions WHERE id IN ({','.join('?' * len(ids))})", ids)]
                _log(tcon, dict(row, status="executed", positions=ids))
                notify(f"Grok auto PRODAJA {tok[:6]}… {amount:.0%} ({len(ids)} lot.). Razlog: {reason or '—'}")
                tx = _signature(tcon, lids[0], "sell", now, wait_s) if lids and lids[0] else None
                return 200, {"status": "executed", "side": "sell", "share": amount, "positions": ids,
                             "mode": (tx or {}).get("mode"), "tx_signature": (tx or {}).get("signature"),
                             "tx_status": (tx or {}).get("status") or "submitted"}
            # buy
            if not st["active"]:
                return reject(f"paused until midnight Zagreb: {st['pause_reason']}")
            if maybe_pause(tcon, now, lcon):
                return reject("paused until midnight Zagreb: the day's loss limit was reached")
            lim, u = limits(tcon), usage(tcon, now, lcon)
            if not 0 < amount <= lim["grok_max_sol_per_trade"] + 1e-12:
                return reject(f"amount must be 0-{lim['grok_max_sol_per_trade']:g} SOL (grok_max_sol_per_trade)", 400)
            if u["spent_sol"] + amount > lim["grok_max_sol_per_day"] + 1e-9:
                return reject(f"day limit: {u['spent_sol']:g} SOL spent today, at most {lim['grok_max_sol_per_day']:g} "
                              "(grok_max_sol_per_day)")
            held = {r[0] for r in lcon.execute(
                f"SELECT DISTINCT token FROM trades WHERE status='open' AND id IN ({','.join('?' * len(_league_ids(tcon))) or 'NULL'})",
                _league_ids(tcon))}
            if tok not in held and u["open"] >= lim["grok_max_open"]:
                return reject(f"{u['open']} Grok positions open, at most {lim['grok_max_open']} (grok_max_open)")
            # 12.11. (owner's order point 4): more rounds in one token (open, close, open again, DCA lots) within
            # max_round_trips_per_token_day, none after MAX_STOP_OUTS_DAY stop-outs, the token at most dca_token_cap
            for blk in (round_block(tcon, lcon, tok, amount, now), token_cap_block(tcon, lcon, tok, amount)):
                if blk:
                    return reject(blk[0], hr=blk[1])
            why, risk = safety_ex(tok, market)
            if why:
                return reject(f"safety check failed: {why}")
            if risk:   # 10.11. (Jure: "ako je BOXCAT označen kao rug, ipak slušaj Groka"): a measured override
                from ui import kandidati
                ev = kandidati.override_now(tok, now)
                if not ev:
                    return reject(f"safety check failed: {risk[0]} (a rug risk rating: fresh evidence of yours from the "
                                  "last 30 min can override it at half size: submit_x_features naming known callers / "
                                  "large accounts or growing organic authors, or submit_signal_opinion kupi)")
                cap = round(lim["grok_max_sol_per_trade"] * kandidati.OVERRIDE_SIZE, 6)
                if amount > cap + 1e-12:
                    return reject(f"rug risk overridden by your fresh evidence, but only at half size: at most {cap:g} "
                                  f"SOL (rug: {risk[0]})", 400)
                row["override"] = {"rug_risk": risk[0], "strength": ev["strength"]}
                reason = row["reason"] = (f"[Grok nadjačao rug ocjenu: {risk[0]}] " + reason)[:300]
            # 11.11. (flag grok_ev_gate, momentum/evgate.py): EV = p_tp x TP - (1 - p_tp) x SL - cost > 0
            g, cal_id = _ev_gate(body, tok, amount, market, tcon, now)
            if g:
                row["ev_gate"] = {k: g.get(k) for k in ("mode", "p_tp", "strategy", "ev", "break_even_p")}
                if g.get("reject"):
                    evgate_mark(cal_id, "rejected")
                    return reject(g["reject"])
            opening = not round_info(tcon, lcon, tok, now)["open"]
            if opening:   # 12.11.: a new round starts from its own entry
                m = ((market or copy.market)({tok}) or {}).get(tok)
                if m and m[0]:
                    close_stale(tcon, lcon, tok, m[0], m[1], m[3] if len(m) > 3 else None)
            before = lcon.execute("SELECT COALESCE(MAX(id), 0) FROM trades").fetchone()[0]
            tp, sl = pravitrade._last_exit(pravitrade._cfg(tcon))
            ex = ((g or {}).get("levels") or {}).get("exit")
            if ex and (g or {}).get("mode") in ("paper", "live"):   # the strategy's TP / SL the gate priced
                tp, sl = ex
            try:
                pravitrade._post_buy(lcon, tcon, {"token": tok, "sol": f"{amount:g}", "exit": "tpsl", "tp": tp, "sl": sl},
                                     settings.owner(), src=SRC)
            except ValueError as e:
                evgate_mark(cal_id, "rejected")
                return reject(str(e))
            evgate_mark(cal_id, "executed")
            tid = lcon.execute("SELECT MAX(id) FROM trades WHERE user=? AND token=? AND id>?",
                               (settings.LEAGUE_USER, tok, before)).fetchone()[0]
            if tid:
                _mark_round(tcon, tid, opening)
            _log(tcon, dict(row, status="executed", league_id=tid, round="new" if opening else "dca"))
            left = remaining(tcon, now, lcon)
            notify(f"Grok auto KUPNJA {tok[:6]}… za {amount:g} SOL. Razlog: {reason or '—'}. Danas još "
                   f"{left['sol_today']:g} SOL, slobodnih mjesta {left['open_slots']}.")
            tx = _signature(tcon, tid, "buy", now, wait_s) if tid else None
            return 200, {"status": "executed", "side": "buy", "amount_sol": amount, "league_trade_id": tid,
                         "mode": (tx or {}).get("mode"), "tx_signature": (tx or {}).get("signature"),
                         "tx_status": (tx or {}).get("status") or "submitted",
                         "note": ("the swap is sent by the trade process within seconds; get_portfolio_status shows "
                                  "the position") if not (tx or {}).get("signature") else "",
                         "remaining_today": left}
        finally:
            lcon.close()
    finally:
        tcon.close()


def _ev_gate(body, tok, amount, market, tcon, now):
    """(gate result or None, calibration row id or None) of one autotrade buy (momentum/evgate.py). Without p_tp and
    with the gate off or in shadow there is nothing to check or record. A gate that fails to run refuses only while it
    enforces (paper / live: no proof, no buy)."""
    m = "off"
    try:
        from momentum import evgate
        m = evgate.mode()
        p = body.get("p_tp")
        if p is None and m not in ("paper", "live"):
            return None, None
        g = evgate.check(tok, amount, p, body.get("strategy") or "other", market, now, tcon=tcon, gate_mode=m)
        cid = evgate.record(g, tok, amount, "autotrade", now)
        if g.get("shadow_reject"):
            evgate.shadow_log(g, tok)
            print(f"grok auto: EV vrata (sjena) bi odbila {tok[:6]}: {g['shadow_reject']}", flush=True)
        return g, cid
    except Exception as e:  # noqa: BLE001
        print(f"grok auto: EV vrata nisu uspjela ({type(e).__name__}: {e})", flush=True)
        if m in ("paper", "live"):
            return {"mode": m, "reject": f"grok_ev_gate: the check failed ({type(e).__name__}), no buy without it"}, None
        return None, None


def evgate_mark(cal_id, status):
    if cal_id:
        try:
            from momentum import evgate
            evgate.mark(cal_id, status)
        except Exception:  # noqa: BLE001
            pass


def portfolio_part(tcon, now=None):
    """For get_portfolio_status: the switch, the limits and what is left today."""
    st = state(tcon, now)
    out = {"on": st["on"], "active": st["active"], "paused_until": st["paused_until"], "pause_reason": st["pause_reason"],
           "limits": limits(tcon)}
    try:
        out["remaining_today"] = remaining(tcon, now)
    except Exception as e:  # noqa: BLE001
        out["remaining_today"] = {"error": type(e).__name__}
    # 12.11. (owner's order point 4): per token Grok bought today, its rounds and stop-outs (Zagreb day)
    out["round_rules"] = (f"a round starts with a buy while you hold no open position in the token (a DCA lot into the "
                          f"open one is not a new round); at most max_round_trips_per_token_day rounds per token per "
                          f"Zagreb day; after {MAX_STOP_OUTS_DAY} stop-outs in a token no buy of it until midnight "
                          "Zagreb; your SOL in one token at most dca_token_cap")
    try:
        start = _day_start(now or time.time())
        toks = {r.get("token") for r in log_rows(tcon, 300) if r.get("side") == "buy" and r.get("status") == "executed"
                and (r.get("ts") or 0) >= start and r.get("token")}
        if toks:
            from league import store as lstore
            lcon = lstore.connect()
            try:
                out["tokens_today"] = {t: {k: v for k, v in round_info(tcon, lcon, t, now).items() if k != "rounds"}
                                       for t in sorted(toks)}
            finally:
                lcon.close()
    except Exception as e:  # noqa: BLE001
        out["tokens_today"] = {"error": type(e).__name__}
    return out
