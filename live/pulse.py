"""What the live feed says about one token right now: buyers, sellers, volume and price by window, and the dump
signal the demo bot exits on (paper/config.json "live")."""
import json
import time

DEFAULT = {"dump_exit": True, "window_s": 60, "min_sellers": 5, "sell_ratio": 2.5, "drop": -0.08, "ref_s": 300,
           "cooldown_s": 120}


def config(cfg=None):
    return {**DEFAULT, **((cfg or {}).get("live") or {})}


def window(con, mint, now=None, secs=60):
    """{buys, sells, buyers, sellers, buy_sol, sell_sol, net_sol, last_px, first_px} for the last `secs` seconds."""
    now = now or time.time()
    rows = con.execute("SELECT side, wallet, sol, price_sol FROM live_trades WHERE mint=? AND ts>=? ORDER BY ts",
                       (mint, int(now - secs))).fetchall()
    out = {"buys": 0, "sells": 0, "buy_sol": 0.0, "sell_sol": 0.0, "n": len(rows)}
    buyers, sellers, pxs = set(), set(), []
    for side, w, sol, px in rows:
        if side == "buy":
            out["buys"] += 1
            out["buy_sol"] += sol or 0
            buyers.add(w)
        else:
            out["sells"] += 1
            out["sell_sol"] += sol or 0
            sellers.add(w)
        if px:
            pxs.append(px)
    out.update(buyers=len(buyers), sellers=len(sellers), net_sol=round(out["buy_sol"] - out["sell_sol"], 3),
               first_px=pxs[0] if pxs else None, last_px=pxs[-1] if pxs else None)
    out["buy_sol"], out["sell_sol"] = round(out["buy_sol"], 3), round(out["sell_sol"], 3)
    return out


def dump(con, mint, now=None, cfg=None):
    """(True, why) when the last window_s look like a dump: enough distinct sellers, sell volume >= sell_ratio x buy
    volume and the price down `drop` or more against ref_s seconds ago. (False, None) otherwise."""
    c = config(cfg)
    now = now or time.time()
    w = window(con, mint, now, c["window_s"])
    if w["sellers"] < c["min_sellers"] or w["sell_sol"] < c["sell_ratio"] * max(w["buy_sol"], 0.01):
        return False, None
    ref = con.execute("SELECT price_sol FROM live_trades WHERE mint=? AND ts<=? AND price_sol IS NOT NULL "
                      "ORDER BY ts DESC LIMIT 1", (mint, int(now - c["ref_s"]))).fetchone()
    ref_px = ref[0] if ref else w["first_px"]
    if not ref_px or not w["last_px"]:
        return False, None
    chg = w["last_px"] / ref_px - 1
    if chg > c["drop"]:
        return False, None
    return True, (f"{w['sellers']} prodavača i {w['sell_sol']:.1f} SOL prodaja prema {w['buy_sol']:.1f} SOL kupnja u "
                  f"{c['window_s']} s, cijena {chg:+.0%} prema prije {c['ref_s'] // 60} min")


def check_dumps(con, open_tokens, now=None, cfg=None):
    """Writes a live_alerts 'dump' row for every open demo token that looks like a dump (once per cooldown)."""
    c = config(cfg)
    now = now or time.time()
    n = 0
    for t in open_tokens:
        if con.execute("SELECT 1 FROM live_alerts WHERE token=? AND kind='dump' AND ts>=?",
                       (t, int(now - c["cooldown_s"]))).fetchone():
            continue
        hit, why = dump(con, t, now, cfg)
        if hit:
            con.execute("INSERT OR IGNORE INTO live_alerts VALUES (?,?,?,?)",
                        (t, int(now), "dump", json.dumps({"why": why, **window(con, t, now, c["window_s"])})))
            n += 1
    if n:
        con.commit()
    return n


def alerts(con, since, kind="dump"):
    """[(token, ts, detail dict)] alerts newer than `since`."""
    return [(t, ts, json.loads(d or "{}")) for t, ts, d in con.execute(
        "SELECT token, ts, detail FROM live_alerts WHERE kind=? AND ts>? ORDER BY ts", (kind, int(since)))]


def status(con, now=None):
    """Feed health for pages and the morning report: connected, last trade age, counts, subscriptions."""
    now = now or time.time()
    g = lambda k: con.execute("SELECT value FROM live_state WHERE key=?", (k,)).fetchone()
    last = g("last_trade_ts")
    try:
        subs = json.loads((g("subscribed") or ("{}",))[0])
    except ValueError:
        subs = {}
    n24 = con.execute("SELECT COUNT(*) FROM live_trades WHERE ts>=?", (int(now - 86400),)).fetchone()[0]
    l24 = con.execute("SELECT COUNT(*) FROM live_launches WHERE ts>=?", (int(now - 86400),)).fetchone()[0]
    a24 = con.execute("SELECT COUNT(*) FROM live_alerts WHERE ts>=?", (int(now - 86400),)).fetchone()[0]
    return {"last_trade_age_s": (now - int(last[0])) if last else None, "trades_24h": n24, "launches_24h": l24,
            "alerts_24h": a24, "tokens": subs.get("tokens", 0), "wallets": subs.get("wallets", 0)}


def token_html(mint, now=None, con=None):
    """The 'Uživo' card on the token page: buyers/sellers/volume for 1, 5 and 15 min, and the last dump alert."""
    from ui.html import esc
    from live import store
    own = con is None
    con = con or store.ro()
    if con is None:
        return ""
    now = now or time.time()
    try:
        ws = [(lab, window(con, mint, now, s)) for lab, s in (("1 min", 60), ("5 min", 300), ("15 min", 900))]
        if not any(w["n"] for _, w in ws):
            return ""
        last = con.execute("SELECT ts, detail FROM live_alerts WHERE token=? AND kind='dump' ORDER BY ts DESC LIMIT 1",
                           (mint,)).fetchone()
    finally:
        if own:
            con.close()
    rows = "".join(f"<tr><td>{lab}</td><td class=n>{w['buyers']}</td><td class=n>{w['sellers']}</td>"
                   f"<td class=n>{w['buy_sol']:.1f}</td><td class=n>{w['sell_sol']:.1f}</td>"
                   f"<td class={'pos' if w['net_sol'] >= 0 else 'neg'}>{w['net_sol']:+.1f}</td></tr>" for lab, w in ws)
    w5 = ws[1][1]
    if w5["buyers"] >= 2 * max(w5["sellers"], 1) and w5["net_sol"] > 0:
        verdict = "Kupci prevladavaju: više različitih kupaca nego prodavača i novac ulazi."
    elif w5["sellers"] >= 2 * max(w5["buyers"], 1) or w5["net_sol"] < -1:
        verdict = "Prodavači prevladavaju: novac izlazi. Ne ulazi se dok se ne okrene."
    else:
        verdict = "Izjednačeno: nema jasnog smjera u zadnjih 5 min."
    alert = ""
    if last and now - last[0] < 3600:
        try:
            why = json.loads(last[1] or "{}").get("why", "")
        except ValueError:
            why = ""
        alert = f'<p class=neg style="margin:6px 0 0">⚡ Dump prije {int((now - last[0]) // 60)} min: {esc(why)}</p>'
    return ('<div class=card style="margin:10px 0"><h3 style="margin:0 0 6px">Uživo (pump.fun / PumpSwap, sekundno)</h3>'
            f'<p style="margin:0 0 6px"><b>{verdict}</b></p>'
            '<table class=t><tr><th>prozor</th><th>kupaca</th><th>prodavača</th><th>kupnja SOL</th><th>prodaja SOL</th>'
            f'<th>neto</th></tr>{rows}</table>{alert}'
            '<p class=mut style="font-size:12px;margin:6px 0 0">Različiti novčanici po prozoru, iz živog toka PumpPortala '
            '(besplatno). Demo bot na dump (puno prodavača, prodaja ≥ 2,5× kupnje, cijena −8 %) proda u sekundama.</p></div>')
