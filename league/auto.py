"""Auto sell for the competition: the tool sells your demo position while you sleep.

Two modes per open position (column trades.auto, JSON):
- {"mode": "smart"}: the learned exit rules of the token's class (exits/, same code as the bot's paper trading):
  partial take profits, trailing, moonbag, KOL hold. Partial sales are kept in trades.realized until the
  position closes (then the cash is back on the account).
- {"mode": "tpsl", "tp_px": .., "sl_px": .., "tp": "+100%", "sl": "$40k"}: your own take profit / stop loss,
  entered in percent or in market cap; converted to a price once (supply is fixed, so mcap moves with price).

Runs inside the dashboard process (run_ui.py starts a thread), which is the only writer of league.db.
"""
import json
import re
import sys
import os
import time

from . import store

# 20 s (was 60): copy trading also drives the real trades on /pravi-trade, where a minute of delay on a fresh
# memecoin call costs money; auto sell, DCA and the history snapshot are time-based and fine with more passes
EVERY_S = int(os.environ.get("LEAGUE_AUTO_EVERY_S", "20"))


def parse_level(text, entry_px, entry_mcap, kind, pct_base=None):
    """'+100%', '100', '-30%', '30' (percent) or '$500k', '1.2M mc' (market cap) -> (price, label).
    kind 'sl': a bare positive percent means a drop (SL 30 = -30%).
    pct_base (9.11., audit P38): the price a percent level is measured from when it is not entry_px, e.g. the
    effective entry after fee and impact; a market-cap level always maps through entry_px / entry_mcap."""
    s = (text or "").strip().lower().replace(",", ".").replace(" ", "")
    if not s:
        return None, None
    m = re.fullmatch(r"\$?([0-9.]+)([kmb])?(mc|mcap)?", s)
    is_mc = bool(m) and (s.startswith("$") or m.group(2) or m.group(3))
    if is_mc:
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(2) or "", 1)
        mc = float(m.group(1)) * mult
        if not entry_mcap:
            raise ValueError("za ovaj trade nije zapisan ulazni MC; upiši postotak")
        return entry_px * mc / entry_mcap, f"MC ${mc:,.0f}"
    m = re.fullmatch(r"([+-]?[0-9.]+)%?", s)
    if not m:
        raise ValueError(f"ne razumijem '{text}': upiši postotak (npr. 100% ili -30%) ili MC (npr. $500k)")
    pct = float(m.group(1))
    if kind == "sl" and pct > 0:
        pct = -pct
    if kind == "tp" and pct <= 0:
        raise ValueError("TP mora biti iznad ulazne cijene")
    if kind == "sl" and pct <= -100:
        raise ValueError("SL mora biti iznad -100%")
    return (pct_base or entry_px) * (1 + pct / 100), f"{pct:+g}%"


def set_auto(con, user, trade_id, mode, tp="", sl="", from_eff=False, hold_s=None, until=None):
    """from_eff (9.11., audit P38): percent TP/SL measured from the effective entry (entry_eff: fee + impact) instead
    of the raw entry price, so "+15 %" means +15 % on what was really paid. Copy trading (real money) uses it; the
    players' own rules keep the raw entry (their tests and pages count on it).
    hold_s (9.11., kol/tpsl.py): a TP/SL chosen from the measured hour after a call is only known for that hour, so
    the position is sold at the market hold_s seconds after it was opened if neither level was touched (stored as
    the unix time `until`; a DCA buy passes the stored `until` back so the limit does not restart)."""
    t = con.execute("SELECT * FROM trades WHERE id=? AND user=? AND status='open'", (trade_id, user)).fetchone()
    if not t:
        raise ValueError("nema te otvorene pozicije")
    if mode in ("", "off"):
        auto = None
    elif mode == "smart":
        auto = {"mode": "smart"}
    elif mode == "tpsl":
        base = (t["entry_eff"] or None) if from_eff else None
        tp_px, tp_l = parse_level(tp, t["entry_px"], t["entry_mcap"], "tp", base)
        sl_px, sl_l = parse_level(sl, t["entry_px"], t["entry_mcap"], "sl", base)
        if tp_px is None and sl_px is None:
            raise ValueError("upiši barem TP ili SL")
        if tp_px is not None and tp_px <= t["entry_px"]:
            raise ValueError("TP mora biti iznad ulazne cijene")
        if sl_px is not None and sl_px >= t["entry_px"] and tp_px is None:
            pass  # a stop above entry locks in a profit: allowed
        auto = {"mode": "tpsl", "tp_px": tp_px, "sl_px": sl_px, "tp": tp_l, "sl": sl_l,
                "tp_in": tp or "", "sl_in": sl or ""}   # typed text: a DCA buy re-reads a percent from the new average
        if from_eff:
            auto["from_eff"] = True
        if until or hold_s:
            auto["until"] = int(until or (t["opened_ts"] or time.time()) + hold_s)
    else:
        raise ValueError("nepoznat način")
    con.execute("UPDATE trades SET auto=?, auto_state=NULL WHERE id=?", (json.dumps(auto) if auto else None, trade_id))
    con.commit()
    return auto


# ---------- one rule for all positions -----------------------------------------------------------------------------
# Nicholas 1.11.: setting TP/SL position by position from a dropdown is slow. A player's rule (table auto_rules) is
# applied with one click to every open position and, if he ticks it, to every new buy as well. It writes the same
# per-position trades.auto entry as set_auto, so selling is unchanged (run_once below).

RULES = """CREATE TABLE IF NOT EXISTS auto_rules (user TEXT PRIMARY KEY, mode TEXT, tp TEXT, sl TEXT,
    apply_new INTEGER DEFAULT 0, ts INTEGER)"""


def _rules(con):
    con.execute(RULES)


def get_rule(con, user):
    try:
        _rules(con)
        r = con.execute("SELECT * FROM auto_rules WHERE user=?", (user,)).fetchone()
    except Exception:  # noqa: BLE001 - disk full / locked: no rule shown, nothing breaks
        return None
    return dict(r) if r else None


def check_rule(mode, tp="", sl=""):
    """Validate a rule before saving it (on a made-up entry, so a typo shows now and not on the next buy)."""
    if mode == "smart":
        return
    if mode != "tpsl":
        raise ValueError("nepoznat način")
    tp_px, _ = parse_level(tp, 1.0, 1e6, "tp")
    sl_px, _ = parse_level(sl, 1.0, 1e6, "sl")
    if tp_px is None and sl_px is None:
        raise ValueError("upiši barem TP ili SL")


def apply_all(con, user, mode, tp="", sl="", apply_new=False, all_open=True):
    """Save the player's rule and (all_open) put it on every open position.
    Returns (number of positions set, [(symbol, why skipped)])."""
    if mode in ("", "off"):
        _rules(con)
        con.execute("DELETE FROM auto_rules WHERE user=?", (user,))
        n = 0
        if all_open:
            n = con.execute("UPDATE trades SET auto=NULL, auto_state=NULL WHERE user=? AND status='open' AND auto IS NOT NULL",
                            (user,)).rowcount
        con.commit()
        return n, []
    check_rule(mode, tp, sl)
    _rules(con)
    if apply_new:
        con.execute("INSERT OR REPLACE INTO auto_rules VALUES (?,?,?,?,?,?)",
                    (user, mode, tp or "", sl or "", 1, int(time.time())))
    else:
        con.execute("DELETE FROM auto_rules WHERE user=?", (user,))
    con.commit()
    n, skipped = 0, []
    if all_open:
        for t in con.execute("SELECT id, symbol, token, entry_px, entry_mcap FROM trades WHERE user=? AND status='open' "
                             "ORDER BY id", (user,)).fetchall():
            try:
                if mode == "tpsl" and sl:   # one MC stop for all: on a token bought below it, it would sell at once
                    sl_px, _ = parse_level(sl, t["entry_px"], t["entry_mcap"], "sl")
                    if sl_px is not None and sl_px >= t["entry_px"]:
                        raise ValueError(f"SL {sl} je iznad ulaza ove pozicije")
                set_auto(con, user, t["id"], mode, tp, sl)
                n += 1
            except ValueError as e:   # e.g. TP $500k on a token bought at $1M
                skipped.append((t["symbol"] or t["token"][:6], str(e)))
    return n, skipped


def on_buy(con, user, trade_id, source=""):
    """A new position: put the player's rule on it if he chose 'also for new buys'. Copy trading entries keep the
    exit chosen for that follow (league/copy.py sets it right after the buy)."""
    if (source or "").startswith("copy"):
        return None
    r = get_rule(con, user)
    if not r or not r.get("apply_new"):
        return None
    try:
        return set_auto(con, user, trade_id, r["mode"], r["tp"], r["sl"])
    except ValueError:
        return None


def describe_rule(r):
    if not r:
        return ""
    if r["mode"] == "smart":
        return "Smart sell (prodaje kako raste)"
    return ", ".join(([f"TP {r['tp']}"] if r.get("tp") else []) + ([f"SL {r['sl']}"] if r.get("sl") else []))


def describe(auto_json):
    a = json.loads(auto_json) if isinstance(auto_json, str) and auto_json else auto_json
    if not a:
        return ""
    if a["mode"] == "smart":
        return "auto: Smart sell"
    parts = ([f"TP {a['tp']}"] if a.get("tp") else []) + ([f"SL {a['sl']}"] if a.get("sl") else [])
    if a.get("until"):   # 9.11.: a data exit (kol/tpsl.py) is closed at the end of the measured hour
        import datetime as _dt
        import zoneinfo
        parts.append("najdulje do " + _dt.datetime.fromtimestamp(a["until"], zoneinfo.ZoneInfo("Europe/Zagreb")).strftime("%H:%M"))
    return "auto: " + ", ".join(parts)


def _klasa(tokens):
    import os
    import sqlite3
    hype = os.path.join(os.path.dirname(store.DB), "hype.db")
    if not tokens or not os.path.exists(hype):
        return {}
    try:
        con = sqlite3.connect(f"file:{hype}?mode=ro", uri=True, timeout=10)
        q = ",".join("?" * len(tokens))
        out = dict(con.execute(f"SELECT token, klasa FROM token_tier WHERE token IN ({q})", list(tokens)))
        con.close()
        return out
    except sqlite3.OperationalError:
        return {}


def _tpsl_hit(a, price, liq, now):
    """What closes a TP/SL position at this price, or None."""
    return (("TP " + a["tp"]) if a.get("tp_px") and price >= a["tp_px"] else
            ("SL " + a["sl"]) if a.get("sl_px") and price <= a["sl_px"] else
            "vrijeme (ni TP ni SL u izmjerenom roku)" if a.get("until") and now >= a["until"] and (liq or 0) > 0
            else None)   # 10.11. (review): a liquidity read of 0 at the deadline would book -100 %: wait a pass


# 10.11. (Jure: "TP je bio +40 % od ulaza 84k, graf je dotakao 117k i malo preko, a automatska prodaja se nije
# napravila"): run_once below checks every player's positions once per loop pass (EVERY_S = 20 s, after the copy
# pass, the auto pick, SimianX, DCA and rekt), so a wick of a few seconds over the target was never seen. The
# Autopilot's real money follows its demo trades, so their TP/SL are checked here on their own, every FAST_EVERY_S,
# from the short live price cache (DexScreener 3 s, Jupiter's price when DexScreener has none).
FAST_EVERY_S = 1.0
FAST_BEAT_S = 600   # one line in the log this often: how many TP/SL positions are watched and whether prices come


def _fast_market(market, tokens):
    mk = dict(market(tokens) or {})
    missing = [t for t in tokens if t not in mk]
    if missing:
        try:
            from ui.paper import jup_prices
            for m, (px, liq) in jup_prices(missing).items():
                mk[m] = (px, liq, None, None)
        except Exception:  # noqa: BLE001 - no price: no sale this second
            pass
    return mk


def fast_once(con, market, user, now=None):
    """The TP/SL of one account's open positions at the current price: [(user, symbol, what happened)], plus the
    number watched and priced as the last item's stats via fast_once.last."""
    now = now or time.time()
    rows = [dict(r) for r in con.execute("SELECT * FROM trades WHERE status='open' AND user=? AND auto IS NOT NULL",
                                         (user,))]
    rows = [r for r in rows if (json.loads(r["auto"]) or {}).get("mode") == "tpsl"]
    fast_once.last = (len(rows), 0)
    if not rows:
        return []
    mk = _fast_market(market, sorted({r["token"] for r in rows}))
    fast_once.last = (len(rows), sum(1 for r in rows if r["token"] in mk))
    done = []
    for t in rows:
        if t["token"] not in mk:
            continue
        price, liq, _, mcap = mk[t["token"]]
        if not price or price <= 0:
            continue
        hit = _tpsl_hit(json.loads(t["auto"]), price, liq, now)
        if hit:
            try:
                pnl = store.sell(con, t["user"], t["id"], price, liq, f"auto {hit}", mcap=mcap)
            except ValueError:   # the main loop closed it in the same second
                continue
            done.append((t["user"], t["symbol"] or t["token"][:6], f"auto {hit}: {pnl:+.2f} $"))
    return done


fast_once.last = (0, 0)


def fast_loop(market, user=None, every=FAST_EVERY_S):
    """Background thread body for run_ui.py: the Autopilot account's TP/SL every `every` seconds."""
    if user is None:
        from trade import settings as tsettings
        user = tsettings.LEAGUE_USER
    con, beat = None, 0.0
    while True:
        try:
            if con is None:
                con = store.connect()
            for u, name, what in fast_once(con, market, user):
                print(f"natjecanje {u} {name}: {what}", flush=True)
            if time.time() - beat >= FAST_BEAT_S:
                beat = time.time()
                n, priced = fast_once.last
                print(f"autopilot izlazi: prati {n} TP/SL pozicija, cijena za {priced}", flush=True)
        except Exception as e:  # noqa: BLE001 - a bad second never stops the watch
            print(f"autopilot izlazi: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
            con = None
        time.sleep(every)


def run_once(con, market, now=None):
    """Check every open position with auto sell on; returns [(user, symbol, what happened)]."""
    from exits import profiles
    from paper import sim
    now = now or time.time()
    rows = [dict(r) for r in con.execute("SELECT * FROM trades WHERE status='open' AND auto IS NOT NULL")]
    if not rows:
        return []
    mk = market({r["token"] for r in rows}) or {}
    klase = _klasa({r["token"] for r in rows})
    base = sim.load_config()
    done = []
    for t in rows:
        if t["token"] not in mk:
            continue  # no price this minute: never sell blind
        price, liq, _, mcap = mk[t["token"]]
        a = json.loads(t["auto"])
        name = t["symbol"] or t["token"][:6]
        if a["mode"] == "tpsl":
            hit = _tpsl_hit(a, price, liq, now)
            if hit:
                pnl = store.sell(con, t["user"], t["id"], price, liq, f"auto {hit}", mcap=mcap)
                done.append((t["user"], name, f"auto {hit}: {pnl:+.2f} $"))
            continue
        st = json.loads(t["auto_state"]) if t["auto_state"] else None
        if st is None:  # rules of its class at the moment auto sell was switched on, kept for the whole trade
            cfg = profiles.for_trade(base, klase.get(t["token"]) or "default")
            pos = sim.open_position(t["entry_px"], liq, t["opened_ts"], t["size_usd"], cfg)
            st = {"cfg": cfg, "pos": pos}
        cfg, pos = st["cfg"], st["pos"]
        before_left, n_fills = pos["left"], len(pos["fills"])
        sim.step(pos, price, liq, now, cfg)
        for f in pos["fills"][n_fills:]:
            if not pos["open"] and f is pos["fills"][-1]:
                pnl = store.sell(con, t["user"], t["id"], price, liq, f"auto: {f['reason']}", mcap=mcap)
                done.append((t["user"], name, f"auto {f['reason']}: zatvoreno {pnl:+.2f} $"))
            else:
                share = f["frac"] / before_left if before_left > 0 else 0
                net = store.sell_part(con, t["id"], share, price, liq)
                before_left -= f["frac"]
                done.append((t["user"], name, f"auto {f['reason']}: prodano {f['frac']:.0%} za ${net:,.2f}"))
        if pos["open"]:
            con.execute("UPDATE trades SET auto_state=? WHERE id=?", (json.dumps(st), t["id"]))
    con.commit()
    return done


def loop(market, every=EVERY_S):
    """Background thread body for run_ui.py."""
    while True:
        try:
            con = store.connect()
            # 9.11. (audit P27): copy trading goes FIRST (the wake-up from a webhook is for it: every second of a fresh
            # call is money) and auto sell has its own try, so a DexScreener hiccup in one never skips the other
            try:   # copy trading: followed KOLs' calls and wallets' buys/sells (league/copy.py)
                from . import copy
                for user, what in copy.run_once(con):
                    print(f"natjecanje {user} {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops auto sell
                print(f"copy trading: {type(e).__name__}: {e}", file=sys.stderr)
            try:
                for user, name, what in run_once(con, market):
                    print(f"natjecanje {user} {name}: {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops the copies
                print(f"auto sell: {type(e).__name__}: {e}", file=sys.stderr)
            try:   # Autopilot: the tool picks whom the real-money account follows, hourly, only if the owner said so
                from ui import autopilot
                for what in autopilot.maybe_sync(con):
                    print(f"natjecanje {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops auto sell
                print(f"autopilot izbor: {type(e).__name__}: {e}", file=sys.stderr)
            try:   # SimianX long signals on the real-trade account, only with the owner's switch (simianx_feed.py)
                from . import simianx_feed
                for user, what in simianx_feed.run_once(con, market):
                    print(f"natjecanje {user} {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops auto sell
                print(f"simianx signali: {type(e).__name__}: {e}", file=sys.stderr)
            try:   # automatic DCA: scheduled buys into the player's position (league/dca.py)
                from . import dca
                for user, what in dca.run_once(con):
                    print(f"natjecanje {user} {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops auto sell
                print(f"dca: {type(e).__name__}: {e}", file=sys.stderr)
            try:   # rekt: a player (or the bot) under $25 starts a new round with $1,000 (league/rekt.py)
                from . import rekt
                from ui import leaguedash
                for what in rekt.maybe_check(con, market, lambda: leaguedash.bot_equity(con)):
                    print(f"natjecanje {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops auto sell
                print(f"rekt: {type(e).__name__}: {e}", file=sys.stderr)
            from . import history
            history.maybe_snapshot(con, market)  # account values for the Natjecanje chart, every 15 min
            con.close()
        except Exception as e:
            print(f"auto sell: {type(e).__name__}: {e}", file=sys.stderr)
        _nap(every)


def _nap(every):
    """Sleep up to `every` seconds, but wake within a second when a followed wallet or KOL just acted
    (league/copy.wake): the real-money copy must not wait for the next tick (9.11.)."""
    from . import copy
    t0 = time.time()
    while time.time() - t0 < every:
        time.sleep(1)
        if copy.woke_since(t0):
            return
