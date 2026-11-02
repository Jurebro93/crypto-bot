"""One pass of the KOL copy replay (run_kolcopy.py run, every KOLCOPY_EVERY_MIN from run_sched).

1. Events: every KOL wallet's first buy of a token in hype.db chain_trades (Helius webhook, seconds after the
   swap) becomes an event (wallet, token, t0). Its first sell of that token within mirror_max_h is its exit.
   chain_trades only says that the wallet sold, not how much: the first sell counts as the whole exit.
2. Points: the token's price at t0 (the KOL's own price), at t0 + every delay (our entry), at every horizon after
   t0, and at sell + every delay (our exit when we mirror the sell). A point is measured once it is lag_s old, so
   an event fills in over a day; each pass stops at credits_per_run / credits_per_day.
3. Returns (returns()): per delay, entry at t0 + d; exits 'mirror' (sell + d; no sell within mirror_max_h = the
   horizon at mirror_max_h) and h1/h6/h24. A KOL that sold before our entry would have been seen selling first:
   no trade. Net = gross - round_trip_pct - 2 tips / stake.
"""
import datetime as dt
import json
import os
import sqlite3
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
HYPE_DB = os.path.join(os.path.dirname(HERE), "hype.db")
SUPPLY = 1e9  # pump.fun / bonk tokens: market cap in SOL = price * 1e9


def load_config(path=None):
    with open(path or CONFIG) as f:
        return json.load(f)


def _hype_ro(path):
    if not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    except sqlite3.OperationalError:
        return None


def sync_events(con, cfg, now, hype_path=None):
    """New events from chain_trades and the first sell of every open one. Returns how many events were added."""
    h = _hype_ro(hype_path or HYPE_DB)
    if h is None:
        return 0
    cut = int(now - cfg["max_age_d"] * 86400)
    try:
        # SQLite: with MIN() the bare column (sol) comes from the row holding the minimum, i.e. the first buy
        buys = h.execute("SELECT wallet, mint, MIN(ts), sol FROM chain_trades WHERE side='buy' AND ts >= ? "
                         "GROUP BY wallet, mint", (cut,)).fetchall()
        sell_ts = {}
        for w, m, ts in h.execute("SELECT wallet, mint, ts FROM chain_trades WHERE side='sell' AND ts >= ? ORDER BY ts",
                                  (cut,)):
            sell_ts.setdefault((w, m), []).append(int(ts))
    except sqlite3.OperationalError:  # no chain_trades yet (webhook not set up)
        return 0
    finally:
        h.close()
    sells = {}
    for e in con.execute("SELECT id, wallet, mint, t0 FROM events WHERE status='open' AND sell_ts IS NULL"):
        end = e["t0"] + cfg["mirror_max_h"] * 3600
        first = next((t for t in sell_ts.get((e["wallet"], e["mint"]), []) if e["t0"] < t <= end), None)
        if first:
            sells[e["id"]] = first
    ignore, added = set(cfg.get("ignore_mints") or []), 0
    seen = set()
    for wallet, mint, ts, sol in buys:
        if (wallet, mint) in seen or mint in ignore:
            continue
        seen.add((wallet, mint))
        if sol is None or sol < cfg["min_kol_sol"]:
            continue
        cur = con.execute("INSERT OR IGNORE INTO events (wallet, mint, t0, kol_sol, created, updated) VALUES (?,?,?,?,?,?)",
                          (wallet, mint, int(ts), float(sol), int(now), int(now)))
        added += cur.rowcount
    for eid, ts in sells.items():
        con.execute("UPDATE events SET sell_ts=?, updated=? WHERE id=?", (ts, int(now), eid))
    con.commit()
    return added


def plan(ev, cfg):
    """[(name, t)] of every point this event needs (some may not be due yet)."""
    t0, out = ev["t0"], [("kol", ev["t0"])]
    out += [(f"e{d}", t0 + d) for d in cfg["delays_s"]]
    out += [(f"h{h}", t0 + h * 3600) for h in cfg["horizons_h"]]
    if ev["sell_ts"]:
        out += [(f"s{d}", ev["sell_ts"] + d) for d in cfg["delays_s"] if ev["sell_ts"] >= t0 + d]
    return out


def _resolved(ev, cfg, now):
    return bool(ev["sell_ts"]) or now >= ev["t0"] + cfg["mirror_max_h"] * 3600 + cfg["lag_s"]


def _spent_today(con, now):
    day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
    from kolcopy import store
    return day, float(store.kv_get(con, f"credits:{day}", 0) or 0)


def step(con, cfg, prices, now=None, hype_path=None, credits=None, log=None):
    """Sync events, then fill due points oldest event first until the credit budget is used. Returns a summary."""
    from kolcopy import store
    now = int(now or time.time())
    added = sync_events(con, cfg, now, hype_path)
    day, spent = _spent_today(con, now)
    budget = min(float(credits if credits is not None else cfg["credits_per_run"]),
                 max(0.0, cfg["credits_per_day"] - spent))
    start_credits, filled, done, skipped, stopped = prices.credits, 0, 0, 0, False
    for ev in con.execute("SELECT * FROM events WHERE status='open' ORDER BY t0, id").fetchall():
        pts = json.loads(ev["points"] or "{}")
        for name, t in plan(ev, cfg):
            if name in pts or t > now - cfg["lag_s"]:
                continue
            if prices.credits - start_credits >= budget:
                stopped = True
                break
            r = prices.price_at(ev["mint"], t)
            if r is None:
                continue
            pts[name] = [r[0], r[1]]
            filled += 1
            if name == "kol" and r[0] * SUPPLY > cfg["max_mcap_sol"]:
                con.execute("UPDATE events SET status='skip', skip_reason='velik token', points=?, updated=? WHERE id=?",
                            (json.dumps(pts), now, ev["id"]))
                skipped += 1
                break
        else:
            status = "done" if _resolved(ev, cfg, now) and all(n in pts for n, _ in plan(ev, cfg)) else "open"
            done += status == "done"
            con.execute("UPDATE events SET points=?, status=?, updated=? WHERE id=?",
                        (json.dumps(pts), status, now, ev["id"]))
            con.commit()
            continue
        con.execute("UPDATE events SET points=?, updated=? WHERE id=? AND status='open'", (json.dumps(pts), now, ev["id"]))
        con.commit()
        if stopped:
            break
    used = prices.credits - start_credits
    store.kv_set(con, f"credits:{day}", spent + used)
    store.kv_set(con, "last_run", now)
    prices.prune(now - cfg["max_age_d"] * 86400 - 2 * 86400)
    con.commit()
    res = {"added": added, "points": filled, "done": done, "skipped": skipped, "credits": used, "stopped": stopped}
    if log:
        log(res)
    return res


def cost(cfg):
    return cfg["round_trip_pct"] / 100 + 2 * cfg["tip_sol"] / cfg["stake_sol"]


def returns(ev, cfg, now=None):
    """{delay: {exit: net return | 'skip'}} with only the exits whose prices are known. Delay 0 is the KOL's own
    entry price (reference: what the KOL made, before our delay)."""
    pts = ev["points"] if isinstance(ev["points"], dict) else json.loads(ev["points"] or "{}")
    now = now or time.time()
    c, t0, sell = cost(cfg), ev["t0"], ev["sell_ts"]
    resolved = bool(sell) or now >= t0 + cfg["mirror_max_h"] * 3600 + cfg["lag_s"]
    out = {}
    for d in [0] + list(cfg["delays_s"]):
        entry = (pts.get("kol") if d == 0 else pts.get(f"e{d}")) or [None]
        if not entry[0]:
            continue
        r = {}
        for h in cfg["horizons_h"]:
            x = pts.get(f"h{h}")
            if x and x[0]:
                r[f"h{h}"] = max(-1.0, x[0] / entry[0] - 1) - c
        if resolved:
            if sell and sell < t0 + d:
                r["mirror"] = "skip"
            else:
                ex = pts.get(f"s{d or min(cfg['delays_s'])}") if sell else pts.get(f"h{cfg['mirror_max_h']}")
                if ex and ex[0]:
                    r["mirror"] = max(-1.0, ex[0] / entry[0] - 1) - c
        out[d] = r
    return out
