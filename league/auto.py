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
import time

from . import store

EVERY_S = 60


def parse_level(text, entry_px, entry_mcap, kind):
    """'+100%', '100', '-30%', '30' (percent) or '$500k', '1.2M mc' (market cap) -> (price, label).
    kind 'sl': a bare positive percent means a drop (SL 30 = -30%)."""
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
    return entry_px * (1 + pct / 100), f"{pct:+g}%"


def set_auto(con, user, trade_id, mode, tp="", sl=""):
    t = con.execute("SELECT * FROM trades WHERE id=? AND user=? AND status='open'", (trade_id, user)).fetchone()
    if not t:
        raise ValueError("nema te otvorene pozicije")
    if mode in ("", "off"):
        auto = None
    elif mode == "smart":
        auto = {"mode": "smart"}
    elif mode == "tpsl":
        tp_px, tp_l = parse_level(tp, t["entry_px"], t["entry_mcap"], "tp")
        sl_px, sl_l = parse_level(sl, t["entry_px"], t["entry_mcap"], "sl")
        if tp_px is None and sl_px is None:
            raise ValueError("upiši barem TP ili SL")
        if tp_px is not None and tp_px <= t["entry_px"]:
            raise ValueError("TP mora biti iznad ulazne cijene")
        if sl_px is not None and sl_px >= t["entry_px"] and tp_px is None:
            pass  # a stop above entry locks in a profit: allowed
        auto = {"mode": "tpsl", "tp_px": tp_px, "sl_px": sl_px, "tp": tp_l, "sl": sl_l,
                "tp_in": tp or "", "sl_in": sl or ""}   # typed text: a DCA buy re-reads a percent from the new average
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
            hit = ("TP " + a["tp"]) if a.get("tp_px") and price >= a["tp_px"] else \
                  ("SL " + a["sl"]) if a.get("sl_px") and price <= a["sl_px"] else None
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
            for user, name, what in run_once(con, market):
                print(f"natjecanje {user} {name}: {what}", flush=True)
            try:   # copy trading: followed KOLs' calls and wallets' buys/sells (league/copy.py)
                from . import copy
                for user, what in copy.run_once(con):
                    print(f"natjecanje {user} {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops auto sell
                print(f"copy trading: {type(e).__name__}: {e}", file=sys.stderr)
            try:   # automatic DCA: scheduled buys into the player's position (league/dca.py)
                from . import dca
                for user, what in dca.run_once(con):
                    print(f"natjecanje {user} {what}", flush=True)
            except Exception as e:  # noqa: BLE001 - never stops auto sell
                print(f"dca: {type(e).__name__}: {e}", file=sys.stderr)
            from . import history
            history.maybe_snapshot(con, market)  # account values for the Natjecanje chart, every 15 min
            con.close()
        except Exception as e:
            print(f"auto sell: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(every)
