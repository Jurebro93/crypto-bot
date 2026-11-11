"""What the MCP API, get_hourly_brief, ui/kandidati and the daily reports show of momentum_scalp. Read-only on
momentum.db and league.db; never fetches anything.

Base rate (base_rate): every signal (traded or not) after its 45 minutes: hit = +15 % before -10 %; EV per trade =
the mean result of the exit rules (TP1 half at +15 %, trailing 8 %, stop -10 %, 45 min) on the same minute path after
the round-trip cost (rules.round_trip_cost: 1 % fee each side + the measured pool impact of a $15 lot both ways).
"""
import glob
import json
import os
import sqlite3
import time

from . import data, evgate, gate, rules

FLAG = "momentum_scalp"
RULES_TEXT = ("entry: bonded, MC 30k-3M, liquidity >= $20k, 5m change +5..+15 %, buys >= 60 % of 5m transactions, 5m "
              "volume >= 3x the hour's 5m average, unique buyers rising, anti-wash (unique traders vs transactions and "
              "volume), rug verdict not risk/hard, top 10 < 35 %, no shill-network call in the last hour. exit: half at "
              "+15 %, rest trailing 8 % from the peak, stop -10 %, out after 45 min. The base rate counts every signal, "
              "traded or not: hit = +15 % before -10 % within 45 min.")


def _mode():
    try:
        from league import flags
        return flags.mode(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def _r(x, nd=4):
    return round(x, nd) if isinstance(x, float) else x


def summarize(rows):
    """{"n", "hits", "hit_rate", "sl_first", "ev_pct", "avg_cost_pct", "break_even_hit"} of resolved signals."""
    rows = [r for r in rows if r.get("status") == "done" and r.get("hit") is not None]
    n = len(rows)
    if not n:
        return {"n": 0, "hits": 0, "hit_rate": None, "sl_first": None, "ev_pct": None, "avg_cost_pct": None,
                "break_even_hit": None}
    hits = sum(int(r["hit"]) for r in rows)
    sims = [r["sim_ret"] for r in rows if r.get("sim_ret") is not None]
    costs = [r["cost"] for r in rows if r.get("cost") is not None]
    c = sum(costs) / len(costs) if costs else rules.round_trip_cost()
    return {"n": n, "hits": hits, "hit_rate": round(hits / n, 3),
            "sl_first": round(sum(1 for r in rows if r.get("first") == "sl") / n, 3),
            "ev_pct": round(sum(sims) / len(sims) * 100, 2) if sims else None, "avg_cost_pct": round(c * 100, 2),
            "break_even_hit": round(rules.break_even_p(rules.RULES["tp1"], rules.RULES["stop"], c), 3)}


def base_rate(now=None, days=7, path=None):
    now = int(now or time.time())
    return summarize(data.read_signals(now - days * 86400, path))


def _traded(signal_ids):
    """{signal_id: [accounts]} of the signals the Autopilot accounts bought (league.db momentum_trades)."""
    if not signal_ids:
        return {}
    con = data._league_ro()
    if con is None:
        return {}
    try:
        q = ",".join("?" * len(signal_ids))
        rows = con.execute(f"SELECT signal_id, user FROM momentum_trades WHERE signal_id IN ({q})", list(signal_ids)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    out = {}
    for sid, u in rows:
        out.setdefault(sid, []).append(u)
    return out


def signal_row(s, traded=None):
    f = s.get("features") or {}
    b, w = f.get("buyers_in") or {}, f.get("wash_in") or {}
    return {"signal_id": s["id"], "token": s["token"], "symbol": s.get("symbol"), "ts": s["ts"],
            "price_usd": s.get("price"), "market_cap_usd": s.get("mcap"), "liquidity_usd": s.get("liq"),
            "change_5m_pct": f.get("ch_m5"), "volume_5m_vs_hour_avg_x": f.get("vol_x"), "buy_share_5m": f.get("buy_share"),
            "unique_buyers_5m": b.get("now"), "buyers_source": b.get("how"),
            "wash": {k: _r(w.get(k), 2) for k in ("how", "wash", "traders_h1", "tx_per_trader", "usd_per_trader")},
            "top10_pct": f.get("top10"), "rug_level": (f.get("rug_in") or {}).get("level"),
            "outcome": ({"first": s.get("first"), "hit": s.get("hit"), "max_pct": s.get("max_pct"),
                         "min_pct": s.get("min_pct"), "strategy_result_pct": round(s["sim_ret"] * 100, 2)
                         if s.get("sim_ret") is not None else None} if s.get("status") == "done" else "open"),
            "traded_by": (traded or {}).get(s["id"], [])}


def latest(now=None, minutes=60, limit=15, path=None):
    """The newest signals (one per token) of the last `minutes`."""
    now = int(now or time.time())
    seen, rows = set(), []
    sigs = data.read_signals(now - minutes * 60, path)
    tr = _traded([s["id"] for s in sigs])
    for s in sigs:
        if s["token"] in seen:
            continue
        seen.add(s["token"])
        rows.append(signal_row(s, tr))
    return rows[:limit]


def near_misses(path=None, limit=10):
    con = data.ro(path)
    if con is None:
        return None
    try:
        lp = data.kv_get(con, "last_pass") or {}
    except sqlite3.Error:
        lp = {}
    finally:
        con.close()
    return {"ts": lp.get("ts"), "watched": lp.get("watched"), "prequalified": lp.get("prequalified"),
            "near": (lp.get("near") or [])[:limit]}


def positions(user=None):
    con = data._league_ro()
    if con is None:
        return {"open": [], "closed": []}
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='momentum_trades'").fetchone() is None:
            return {"open": [], "closed": []}
        from . import trade
        out = trade.view_trades(con, user, 10)
    except sqlite3.Error:
        out = {"open": [], "closed": []}
    finally:
        con.close()
    for r in out["open"]:
        st = r.pop("state", {}) or {}
        r["tp1_done"] = bool(st.get("tp1"))
        r["exit_levels_market_cap_usd"] = (
            {"tp1_half_at": round(r["entry_mc"] * 1.15), "stop": round(r["entry_mc"] * 0.9),
             "time_stop_ts": r["opened_ts"] + rules.RULES["time_s"]} if r.get("entry_mc") else None)
    return out


def candidates(now=None, minutes=60, limit=15):
    """The momentum part of get_portfolio_status and get_hourly_brief: the latest candidates for Grok to rate."""
    now = int(now or time.time())
    p = gate.proof()
    return {"flag_mode": _mode(), "signals": latest(now, minutes, limit), "near_misses": near_misses(),
            "base_rate_7d": base_rate(now, 7), "positions": positions(),
            "paper_proof": {**p, "live_gate": gate.refusal() or "prolazi (>= 50 tradeova, EV > 0, pogodak >= 45 %)"},
            "rules": RULES_TEXT,
            "rate_with": ("execute_trade with strategy momentum_scalp and p_tp = your probability that +15 % comes before "
                          "-10 % within 45 min; the EV gate needs p_tp above ~0.5 after costs")}


def kandidati_rows(now, window_s=900, path=None):
    """[{"token", "symbol", "ts", "mcap_usd", ...}] for ui/kandidati: the newest signal per token of the last 15 min."""
    out, seen = [], set()
    for s in data.read_signals(now - window_s, path):
        if s["token"] in seen:
            continue
        seen.add(s["token"])
        f = s.get("features") or {}
        out.append({"token": s["token"], "symbol": s.get("symbol"), "ts": s["ts"], "mcap_usd": s.get("mcap"),
                    "change_5m_pct": f.get("ch_m5"), "volume_x": f.get("vol_x"), "buy_share_5m": f.get("buy_share"),
                    "unique_buyers_5m": (f.get("buyers_in") or {}).get("now"), "signal_id": s["id"]})
    return out


def record(now=None):
    """The source record ui/kandidati scores with: the base rate of the last 30 days (EV after cost, fraction)."""
    b = base_rate(now, 30)
    return {"n": b["n"], "hit1h": None, "hit4h": None, "sl_first": b["sl_first"],
            "ev": round(b["ev_pct"] / 100, 4) if b["ev_pct"] is not None else None, "hit": b["hit_rate"],
            "from": "momentum.db signals (+15 % before -10 % in 45 min; EV of the exit rules after cost)"}


def backtest_latest():
    files = sorted(glob.glob(os.path.join(data.ROOT, "output", "momentum-backtest-*.json")))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None
    return {"file": os.path.basename(files[-1]), **{k: rep.get(k) for k in ("days", "tokens_with_data", "tokens_simulated",
                                                                            "variants", "note")}}


def report_data(now=None):
    """The daily report's momentum part: the last 24 h, the 7-day base rate, the paper proof, the backtest, the costs."""
    now = int(now or time.time())
    day = data.read_signals(now - 86400)
    con = data.ro()
    spend = {}
    if con is not None:
        try:
            spend = {"geckoterminal_calls_today": data.day_used(con, "gt_day", now), "geckoterminal_cap": data.GT_DAY,
                     "helius_credits_today": data.day_used(con, "helius_day", now), "helius_cap": data.HELIUS_DAY}
        except sqlite3.Error:
            spend = {}
        finally:
            con.close()
    tr = _traded([s["id"] for s in day])
    c = rules.round_trip_cost()
    return {"flag_mode": _mode(), "signals_24h": len(day), "traded_24h": sum(1 for s in day if tr.get(s["id"])),
            "day": summarize(day), "base_rate_7d": base_rate(now, 7), "paper": gate.proof(),
            "live_gate": gate.refusal() or "prolazi", "backtest": backtest_latest(), "spend": spend,
            "cost_assumption": (f"povratni trošak {c * 100:.2f} % (1 % naknada po strani + utjecaj lota $15 na pool "
                                "od $40k u oba smjera; stvarni pool iz signala)"),
            "break_even_note": ("S TP +15 % / SL -10 % i ~2-3 % povratnog troška prag isplativosti je pogodak ~50 % "
                                f"(npr. {rules.break_even_p(0.15, 0.10, 0.025):.0%} pri 2,5 %), ne 45 %."),
            "grok_calibration": evgate.report(now)}


def lines(rep):
    """Croatian lines of report_data for the daily reports."""
    if not rep:
        return []
    d, b, p = rep["day"], rep["base_rate_7d"], rep["paper"]

    def pct(x):
        return f"{x:.0%}" if x is not None else "-"

    def ev(x):
        return f"{x:+.2f} %" if x is not None else "-"
    out = [f"Momentum scalp ({rep['flag_mode']}): {rep['signals_24h']} signala u 24 h (kupljeno {rep['traded_24h']}), "
           f"riješeno {d['n']}, pogodak (+15 % prije -10 % u 45 min) {pct(d['hit_rate'])}, EV po tradeu nakon troška "
           f"{ev(d['ev_pct'])}; 7 dana: {b['n']} signala, pogodak {pct(b['hit_rate'])}, EV {ev(b['ev_pct'])}.",
           f"  {rep['cost_assumption']}. {rep['break_even_note']}",
           f"  Paper: {p['n']} zatvorenih, pogodak {pct(p['hit_rate'])}, EV {ev(p['ev_pct'])} po tradeu; live: "
           f"{rep['live_gate']}."]
    bt = rep.get("backtest")
    if bt and bt.get("variants"):
        v = bt["variants"].get("osnovno") or next(iter(bt["variants"].values()))
        out.append(f"  Backtest ({bt['file']}, {bt.get('days')} dana, {bt.get('tokens_simulated')} tokena): "
                   f"{v.get('signals')} signala, pogodak {pct(v.get('hit_rate'))}, EV {ev(v.get('ev_pct'))}.")
    s = rep.get("spend") or {}
    if s:
        out.append(f"  Trošak danas: GeckoTerminal {s.get('geckoterminal_calls_today')}/{s.get('geckoterminal_cap')} "
                   f"poziva, Helius {s.get('helius_credits_today')}/{s.get('helius_cap')} kredita, DexScreener besplatno.")
    out += evgate.lines(rep.get("grok_calibration"))
    return out
