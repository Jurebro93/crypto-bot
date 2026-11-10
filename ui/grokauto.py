"""Grok autotrade (10.11. ~21:30, Jure: "autonomno trgovanje za Grok (MCP klijent), iza flaga grok_autotrade
(default off, uključujem ga ja)").

While the owner has switched it ON (Autopilot page, owner only; no MCP tool can switch it on or change its limits),
an MCP execute_trade with require_approval=false is executed at once instead of waiting for the owner's tap:

  buy   only within Grok's OWN limits (trade settings, the owner edits them on the page; get_scoring_config and
        get_portfolio_status show them read-only): grok_max_sol_per_trade 0.1, grok_max_sol_per_day 0.3,
        grok_max_open 3 (open Grok positions), grok_max_loss_day 0.15 SOL. Before every buy the rug check and the
        liquidity checks of the Autopilot's copies run again (league/copy: price, bonded only, liquidity, 30k MC,
        fake pool, pool vs MC, rug, supply concentration); a failed check rejects the buy with the reason. Then it goes
        through the owner's manual buy path (ui/pravitrade._post_buy): the same day-loss stop, wallet balance, the
        owner's per-token cap (dca_cap_owner) and the real swap by run_trade.py in the mode the Autopilot is in
        (dry / trial / live; CLAUDE.md: real money only when the Autopilot is live).
  sell  any open position (Grok's or the Autopilot's / the owner's), any share, no size limit, while the switch is on
        (also while paused by the day loss: a sale only lowers the risk).

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
}
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
        out[k] = int(v) if k == "grok_max_open" else v
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
        settings.put(tcon, k, int(v) if k == "grok_max_open" else round(v, 4), who)


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
    """The checks of the Autopilot's copies (league/copy._enter) again, now: None when the token passes, else why."""
    from league import copy
    mk = (market or copy.market)({token}) or {}
    m = mk.get(token)
    if not m or not m[0]:
        return "nema cijene tog tokena (DexScreener)"
    if copy._dex_pair_empty(m):
        return "DexScreener ima par, ali trenutno bez cijene/likvidnosti"
    price, liq, _, mcap = m[:4]
    c = copy.CFG
    if copy._bonding_curve(m):
        return "token je još na pump.fun krivulji; uzimaju se samo bondani"
    if (liq or 0) < c["min_liq"]:
        return f"premala likvidnost (${liq or 0:,.0f}, treba ${c['min_liq']:,.0f})"
    if (mcap or 0) < c["min_mcap"]:
        return f"MC ${mcap or 0:,.0f} ispod 30k"
    if mcap > c["max_mcap"]:
        return "velik token (preko $50M)"
    if liq > mcap:
        return "lažni pool (likvidnost veća od market capa)"
    if liq < c["min_liq_mcap"] * mcap:
        return f"likvidnost je samo {liq / mcap:.1%} MC-a (granica {c['min_liq_mcap']:.0%})"
    col = copy._rugged(token, mcap, liq)
    if col:
        return f"token je rugan ({col['text']})"
    why, _shown = copy._concentration(token)
    return why or None


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

        def reject(why, code=409):
            _log(tcon, dict(row, status="rejected", why=why))
            print(f"grok auto: odbijeno {side} {tok[:6]} {amount:g}: {why}", flush=True)
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
            why = safety(tok, market)
            if why:
                return reject(f"safety check failed: {why}")
            before = lcon.execute("SELECT COALESCE(MAX(id), 0) FROM trades").fetchone()[0]
            tp, sl = pravitrade._last_exit(pravitrade._cfg(tcon))
            try:
                pravitrade._post_buy(lcon, tcon, {"token": tok, "sol": f"{amount:g}", "exit": "tpsl", "tp": tp, "sl": sl},
                                     settings.owner(), src=SRC)
            except ValueError as e:
                return reject(str(e))
            tid = lcon.execute("SELECT MAX(id) FROM trades WHERE user=? AND token=? AND id>?",
                               (settings.LEAGUE_USER, tok, before)).fetchone()[0]
            _log(tcon, dict(row, status="executed", league_id=tid))
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


def portfolio_part(tcon, now=None):
    """For get_portfolio_status: the switch, the limits and what is left today."""
    st = state(tcon, now)
    out = {"on": st["on"], "active": st["active"], "paused_until": st["paused_until"], "pause_reason": st["pause_reason"],
           "limits": limits(tcon)}
    try:
        out["remaining_today"] = remaining(tcon, now)
    except Exception as e:  # noqa: BLE001
        out["remaining_today"] = {"error": type(e).__name__}
    return out
