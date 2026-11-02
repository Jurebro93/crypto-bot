"""Pure logic of the KOL test book, no I/O: one position's price path after a call, the ladder book on it, and the
summaries the dashboard and the report show (levels reached, time to them, drop before them, exit grid)."""
import statistics

CHECKS = [("5m", 300), ("15m", 900), ("1h", 3600), ("6h", 21600), ("24h", 86400)]


def impact(usd, liq):
    """Constant-product price impact (same model as paper/sim.py)."""
    side = (liq or 0) / 2
    return usd / (side + usd) if side > 0 else 1.0


def lkey(level):
    return f"{level:g}"


def new_position(px, liq, mcap, ts, cfg):
    eff = px * (1 + cfg["fee"]) / (1 - impact(cfg["size_usd"], liq))
    return {"entry_px": px, "entry_liq": liq, "entry_mcap": mcap, "entry_ts": ts, "last_ts": ts, "last_px": px,
            "last_liq": liq, "last_mcap": mcap, "peak": 0.0, "peak_ts": ts, "trough": 0.0, "trough_ts": ts,
            "trough_late": 0.0,
            "hits": {}, "rets": {}, "pnl_usd": 0.0, "book_closed_ts": None, "book_reason": None,
            "book": {"qty": cfg["size_usd"] / eff, "left": 1.0, "realized": 0.0, "tp_done": 0, "open": True,
                     "fills": [], "size": cfg["size_usd"]}}


def _sell(book, frac, px, liq, ts, reason, cfg):
    frac = min(frac, book["left"])
    if frac <= 0:
        return
    gross = book["qty"] * frac * px
    net = gross * (1 - cfg["fee"]) * (1 - impact(gross, liq)) if px > 0 else 0.0
    book["left"] = round(book["left"] - frac, 9)
    book["realized"] += net
    book["fills"].append({"ts": int(ts), "ret": round(px / book["px0"] - 1, 4) if book.get("px0") else None,
                          "frac": frac, "usd": round(net, 4), "reason": reason})
    if book["left"] <= 1e-9:
        book["open"] = False


def value(pos, cfg, px=None, liq=None):
    """Book value now: realized + the rest at the last price after costs; minus stake = PnL."""
    b = pos["book"]
    px = pos["last_px"] if px is None else px
    liq = pos["last_liq"] if liq is None else liq
    rest = 0.0
    if b["open"] and b["left"] > 0 and px and px > 0:
        gross = b["qty"] * b["left"] * px
        rest = gross * (1 - cfg["fee"]) * (1 - impact(gross, liq))
    return b["realized"] + rest - b["size"]


def update(pos, px, liq, mcap, ts, cfg):
    """One price observation. px <= 0 or a pool drained below rug_liq counts as -100% (nothing to sell into)."""
    if px is None:
        return pos
    rug = (px <= 0) or (liq is not None and liq < cfg.get("rug_liq", 500)
                        and liq < 0.05 * (pos["entry_liq"] or 0))
    ret = -1.0 if rug else px / pos["entry_px"] - 1
    el = ts - pos["entry_ts"]
    # levels first, with the lowest point *before* this tick (a level reached on this tick had no drop on it)
    late = "trough_late" in pos  # positions opened before 2.11. have no late trough: left out of late-stop rules
    for lv in cfg["levels"]:
        k = lkey(lv)
        if k not in pos["hits"] and ret >= lv:
            pos["hits"][k] = [int(el), round(pos["trough"], 4)] + ([round(pos["trough_late"], 4)] if late else [])
    # lowest point after late_stop_min: what a stop that only switches on after the first wild minutes would see
    if late and el >= cfg.get("late_stop_min", 30) * 60 and ret < pos["trough_late"]:
        pos["trough_late"] = round(ret, 4)
    if ret > pos["peak"]:
        pos["peak"], pos["peak_ts"] = round(ret, 4), int(ts)
    if ret < pos["trough"]:
        pos["trough"], pos["trough_ts"] = round(ret, 4), int(ts)
    for name, secs in CHECKS:
        if name not in pos["rets"] and el >= secs:
            pos["rets"][name] = round(ret, 4)
    pos.update(last_ts=int(ts), last_px=0.0 if rug else px, last_liq=liq, last_mcap=mcap)
    b = pos["book"]
    b.setdefault("px0", pos["entry_px"])
    if b["open"]:
        if rug:
            _sell(b, b["left"], 0.0, 0, ts, "rug", cfg)
        else:
            lad = cfg["ladder"]
            while b["tp_done"] < len(lad) and ret >= lad[b["tp_done"]][0]:
                lv, frac = lad[b["tp_done"]]
                last = b["tp_done"] == len(lad) - 1
                # a limit order at the level: a jump far past it (thin pool, one wild tick) still fills at the level
                _sell(b, b["left"] if last else frac, min(px, b["px0"] * (1 + lv)), liq, ts, f"+{lv:.0%}", cfg)
                b["tp_done"] += 1
            if b["open"] and ret <= cfg["stop"]:
                _sell(b, b["left"], px, liq, ts, f"stop {cfg['stop']:.0%}", cfg)
        if not b["open"]:
            pos["book_closed_ts"], pos["book_reason"] = int(ts), b["fills"][-1]["reason"]
    pos["pnl_usd"] = round(value(pos, cfg), 4)
    return pos


def finish(pos, ts, reason, cfg):
    """End of the measuring window: the book sells what is left at the last price."""
    b = pos["book"]
    if b["open"]:
        _sell(b, b["left"], pos["last_px"] or 0.0, pos["last_liq"] or 0, ts, reason, cfg)
        pos["book_closed_ts"], pos["book_reason"] = int(ts), reason
    pos["pnl_usd"] = round(value(pos, cfg), 4)
    return pos


# ---- summaries -------------------------------------------------------------------------------------------------

def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def final_ret(p):
    """Return at the end of the window (24 h), or the last one seen."""
    r = p["rets"].get("24h")
    if r is not None:
        return r
    return (p["last_px"] / p["entry_px"] - 1) if p.get("entry_px") and p.get("last_px") is not None else None


def sl_parts(sl):
    """Stop rule from config: None, -0.3 (from the start) or [-0.3, 30] (only after 30 min) -> (level, late)."""
    if isinstance(sl, (list, tuple)):
        return sl[0], True
    return sl, False


def sl_label(sl, cfg=None):
    v, late = sl_parts(sl)
    if v is None:
        return "bez stopa"
    return f"{v:.0%}" + (f" tek nakon {sl[1]} min" if late else "")


def outcome(p, tp, sl, cfg):
    """Return of 'sell everything at +tp, or at sl' on this path (None = still open and undecided, or a late stop
    on a position from before late troughs were recorded)."""
    v, late = sl_parts(sl)
    h = p["hits"].get(lkey(tp))
    cost = 2 * cfg["fee"] + 2 * impact(cfg["size_usd"], p.get("entry_liq"))
    if late:
        if "trough_late" not in p or (h and len(h) < 3):
            return None
        trough, before = p["trough_late"], (h[2] if h else None)
    else:
        trough, before = p["trough"], (h[1] if h else None)
    if h and (v is None or before > v):
        return tp - cost
    if v is not None and trough <= v:
        return v - cost
    if p["status"] != "done":
        return None
    f = final_ret(p)
    return None if f is None else f - cost


def levels_table(ps, cfg):
    """Per level: how many reached it, median minutes to it, median and worst-quarter drop before it."""
    out = []
    n = len(ps)
    for lv in cfg["levels"]:
        hits = [p["hits"][lkey(lv)] for p in ps if lkey(lv) in p["hits"]]
        drops = sorted(h[1] for h in hits)
        out.append({"level": lv, "n": n, "hit": len(hits), "share": len(hits) / n if n else None,
                    "med_min": _med([h[0] / 60 for h in hits]),
                    "med_drop": _med(drops),
                    "q_drop": drops[len(drops) // 4] if drops else None,
                    "stopped_first": sum(1 for p in ps if p["trough"] <= cfg["stop"]
                                         and (lkey(lv) not in p["hits"] or p["hits"][lkey(lv)][1] <= cfg["stop"]))})
    return out


def grid(ps, cfg):
    """[(tp, sl, n, wins, avg_ret, usd_total)] over finished/decided positions."""
    out = []
    for tp in cfg["grid_tp"]:
        for sl in cfg["grid_sl"]:
            rs = [r for r in (outcome(p, tp, sl, cfg) for p in ps) if r is not None]
            out.append({"tp": tp, "sl": tuple(sl) if isinstance(sl, list) else sl, "n": len(rs), "wins": sum(1 for r in rs if r > 0),
                        "avg": sum(rs) / len(rs) if rs else None,
                        "usd": sum(rs) * cfg["size_usd"] if rs else 0.0})
    return out


def summary(ps, cfg):
    n = len(ps)
    k20 = lkey(cfg["levels"][0])
    pnl = [p["pnl_usd"] or 0 for p in ps]
    done = [p for p in ps if p["book_closed_ts"]]
    return {"n": n, "open": sum(1 for p in ps if p["status"] == "open"),
            "never20": sum(1 for p in ps if k20 not in p["hits"]),
            "hit20": sum(1 for p in ps if k20 in p["hits"]),
            "hit50": sum(1 for p in ps if "0.5" in p["hits"]),
            "med_peak": _med([p["peak"] for p in ps]),
            "med_min20": _med([p["hits"][k20][0] / 60 for p in ps if k20 in p["hits"]]),
            "med_delay": _med([(p["entry_ts"] or 0) - (p["call_ts"] or 0) for p in ps if p.get("entry_ts")]),
            "pnl": sum(pnl), "staked": n * cfg["size_usd"],
            "wins": sum(1 for p in done if (p["pnl_usd"] or 0) > 0), "closed": len(done),
            "rugs": sum(1 for p in ps if p["trough"] <= -0.999)}


def by(ps, key):
    g = {}
    for p in ps:
        g.setdefault(p[key], []).append(p)
    return g
