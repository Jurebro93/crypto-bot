"""Paper-trade mechanics, no I/O: fill prices with fee + AMM price impact, and the exit rules.

The same `step` drives live paper trading (run_paper.py tick) and the replays in the daily review, so a
parameter the review suggests behaves exactly like the one that will trade tomorrow.
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config(path=None):
    with open(path or CONFIG_PATH) as f:
        return json.load(f)


def impact(usd, liq):
    """Constant-product price impact: half the pool's liquidity sits on each side."""
    side = (liq or 0) / 2
    return usd / (side + usd) if side > 0 else 1.0


def open_position(price, liq, ts, size_usd, cfg):
    """Buy size_usd at market price; effective price is worse by fee + impact."""
    eff = price * (1 + cfg["fee"]) / (1 - impact(size_usd, liq))
    return {"entry_px": price, "entry_eff": eff, "entry_liq": liq, "opened_ts": ts, "size_usd": size_usd,
            "qty": size_usd / eff, "left": 1.0, "realized": 0.0, "peak": 0.0, "low": 0.0,
            "tp_done": 0, "open": True, "fills": []}


def sell(pos, frac, price, liq, ts, reason, cfg):
    """Sell `frac` of the original quantity (capped at what is left)."""
    frac = min(frac, pos["left"])
    if frac <= 0:
        return
    gross = pos["qty"] * frac * price
    net = gross * (1 - cfg["fee"]) * (1 - impact(gross, liq)) if price > 0 else 0.0
    pos["left"] = round(pos["left"] - frac, 9)
    pos["realized"] += net
    pos["fills"].append({"ts": ts, "price": price, "frac": frac, "usd": round(net, 4), "reason": reason})
    if pos["left"] <= 1e-9:
        pos["open"] = False
        pos["exit_reason"] = reason
        pos["closed_ts"] = ts


def step(pos, price, liq, ts, cfg):
    """Apply one price observation. Fills at the observed price, so a gap through the stop costs extra,
    as it would for real."""
    if not pos["open"]:
        return pos
    if price <= 0 or liq < cfg["rug_liq"] * pos["entry_liq"]:
        sell(pos, 1.0, price, liq, ts, "rug", cfg)
        return pos
    ret = price / pos["entry_px"] - 1
    pos["peak"], pos["low"] = max(pos["peak"], ret), min(pos["low"], ret)
    if pos["tp_done"] == 0 and ret <= cfg["sl"]:
        sell(pos, 1.0, price, liq, ts, "stop_loss", cfg)
        return pos
    for i, (level, frac) in enumerate(cfg["tp"]):
        if i >= pos["tp_done"] and ret >= level:
            sell(pos, frac, price, liq, ts, f"take_profit_{level:g}x", cfg)
            pos["tp_done"] = i + 1
    if not pos["open"]:
        return pos
    if pos["tp_done"] and cfg.get("breakeven_after_tp") and ret <= 0:
        sell(pos, 1.0, price, liq, ts, "breakeven", cfg)
    elif pos["peak"] >= cfg["trail_after"] and (1 + ret) <= (1 + pos["peak"]) * (1 - cfg["trail"]):
        sell(pos, 1.0, price, liq, ts, "trailing", cfg)
    elif ts - pos["opened_ts"] >= cfg["max_hold_h"] * 3600:
        sell(pos, 1.0, price, liq, ts, "time", cfg)
    return pos


def result(pos, mark_price=None, mark_liq=None, cfg=None):
    """PnL in USD and as a return on size; an open position is marked at mark_price (as if sold now)."""
    value = pos["realized"]
    if pos["open"] and mark_price and cfg:
        gross = pos["qty"] * pos["left"] * mark_price
        value += gross * (1 - cfg["fee"]) * (1 - impact(gross, mark_liq))
    pnl = value - pos["size_usd"]
    return {"pnl_usd": round(pnl, 2), "ret": round(pnl / pos["size_usd"], 4), "max_ret": round(pos["peak"], 4),
            "min_ret": round(pos["low"], 4), "exit_reason": pos.get("exit_reason") or ("open" if pos["open"] else "")}


def replay(entry_price, entry_liq, entry_ts, path, cfg, size_usd=None):
    """Simulate a whole trade over [(ts, price, liq), ...]; unfinished trades are marked at the last tick."""
    pos = open_position(entry_price, entry_liq, entry_ts, size_usd or cfg["size_usd"], cfg)
    last = (entry_ts, entry_price, entry_liq)
    for ts, price, liq in path:
        if ts <= entry_ts:
            continue
        step(pos, price or 0, liq or 0, ts, cfg)
        last = (ts, price, liq)
        if not pos["open"]:
            break
    return result(pos, last[1], last[2], cfg)
