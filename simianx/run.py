"""One SimianX pass (run_simianx.py once, every SIMIANX_EVERY_MIN):

1. demo book: close positions at SimianX's stop / target (mapped to the Solana price), after max_hold_d days, or when
   a newer opinion turns against it;
2. tokens from today's long-term lists (dugo.db) are mapped to a SimianX instrument once a week: exact symbol and the
   exchange price within max_price_gap of our Solana price, so a pump.fun token that shares a ticker with a big coin
   (our "BTC" meme) never gets Bitcoin's analysis;
3. up to max_per_pass quick reads on the 1D chart for mapped tokens without a fresh opinion, best rank first, while
   the day's points last (daily_points of the Free plan's 20, the rest stays for Nicholas's own chats);
4. a long view opens a $book.usd demo position and a signal for the real-trade account (used only while the owner's
   switch is on, league/simianx_feed.py).
No key -> nothing happens."""
import json
import os
import time

from . import client, store

D = 86400
SOL_MINT = "So11111111111111111111111111111111111111112"
HERE = os.path.dirname(os.path.abspath(__file__))
EMPTY_NOTE = "SimianX ga ne analizira na Free planu (prazan odgovor); treba plaćeni plan (Starter $7/mj)"


def config():
    with open(os.path.join(HERE, "config.json")) as f:
        return json.load(f)


def _log(msg):
    print(f"simianx: {msg}", flush=True)


def candidates(cfg, dugo_con):
    """[(mint, symbol, name, dex_price)] from today's lists, best rank first, each mint once."""
    day = dugo_con.execute("SELECT MAX(day) FROM snap").fetchone()[0]
    if not day:
        return []
    out, seen = [], set()
    rows = dugo_con.execute(
        f"""SELECT s.mint, t.symbol, t.name, s.price, s.rank FROM snap s JOIN tokens t ON t.mint=s.mint
            WHERE s.day=? AND s.kind IN ({','.join('?' * len(cfg['lists']))}) AND s.rank<=? ORDER BY s.rank""",
        (day, *cfg["lists"], cfg["top_per_list"])).fetchall()
    for m, sym, name, px, _ in rows:
        if m in seen or not sym:
            continue
        seen.add(m)
        out.append((m, sym.strip().upper(), name or "", px))
    return out


def map_token(con, cfg, mint, sym, dex_px, now, day_start, api=client):
    """-> SimianX symbol or None; cached in `instruments` for map_ttl_d days."""
    r = con.execute("SELECT * FROM instruments WHERE mint=?", (mint,)).fetchone()
    if r and r["ts"] > now - cfg["map_ttl_d"] * D:
        return r["sx_symbol"] if r["ok"] else None
    ok, note, sx = 0, "", None
    items = api.search(sym)
    time.sleep(getattr(api, "SEARCH_GAP_S", 0))
    if not items:
        note = "nije na OKX/Bybit"
    else:
        sx = items[0]["symbol"]
        close = api.last_close(sx)
        store.add_map_points(con, day_start, 0.2)
        time.sleep(getattr(api, "SEARCH_GAP_S", 0))
        if not close or not dex_px:
            note = "nema cijene za usporedbu"
        elif abs(close / dex_px - 1) > cfg["max_price_gap"]:
            note = f"isti ticker, druga cijena (${close:g} na burzi vs ${dex_px:g} na Solani): drugi token"
        else:
            ok, note = 1, f"burza ${close:g} ≈ Solana ${dex_px:g}"
    con.execute("INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?)", (mint, sym, sx, ok, note, int(now)))
    con.commit()
    return sx if ok else None


def _levels(op, cfg):
    """SimianX stop/target as % from its entry (exchange price), so they can be put on the Solana price."""
    b = cfg["book"]
    e = op.get("entry")
    sp = op["stop"] / e - 1 if e and op.get("stop") else b["default_stop"]
    tp = op["target"] / e - 1 if e and op.get("target") else b["default_target"]
    if not -0.9 < sp < 0:
        sp = b["default_stop"]
    if not 0 < tp < 10:
        tp = b["default_target"]
    return sp, tp


def prices(mints):
    from dugo import sources
    best = sources.dex_best(set(mints) | {SOL_MINT})
    return {m: float(p.get("priceUsd") or 0) or None for m, p in best.items()}


def book_step(con, cfg, now, px):
    sol = px.get(SOL_MINT)
    newest = store.latest(con)
    for r in con.execute("SELECT * FROM book WHERE exit_ts IS NULL").fetchall():
        p = px.get(r["mint"])
        why = None
        if p and r["stop_px"] and p <= r["stop_px"]:
            why = f"stop {r['stop_pct']:+.0%} (SimianX)"
        elif p and r["target_px"] and p >= r["target_px"]:
            why = f"cilj {r['target_pct']:+.0%} (SimianX)"
        elif now - r["entry_ts"] > cfg["book"]["max_hold_d"] * D:
            why = f"{cfg['book']['max_hold_d']} dana prošlo"
        else:
            o = newest.get(r["mint"])
            if o is not None and o["id"] != r["opinion_id"] and o["view"] == "short":
                why = "SimianX okrenuo mišljenje (short)"
        if why and p:
            con.execute("UPDATE book SET exit_ts=?, exit_price=?, reason=?, sol_exit=? WHERE id=?",
                        (int(now), p, why, sol, r["id"]))
    con.commit()


def open_long(con, cfg, op_id, mint, sym, op, px_now, sol, now):
    sp, tp = _levels(op, cfg)
    if op.get("confidence") is not None and op["confidence"] < cfg["book"]["min_confidence"]:
        return False
    if con.execute("SELECT 1 FROM book WHERE mint=? AND exit_ts IS NULL", (mint,)).fetchone() or not px_now:
        return False
    con.execute("""INSERT INTO book (opinion_id, mint, symbol, entry_ts, entry_price, usd, stop_px, target_px, stop_pct,
        target_pct, sol_entry) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (op_id, mint, sym, int(now), px_now, cfg["book"]["usd"], px_now * (1 + sp), px_now * (1 + tp), sp, tp, sol))
    con.execute("INSERT INTO signals (opinion_id, mint, symbol, ts, stop_pct, target_pct) VALUES (?,?,?,?,?,?)",
                (op_id, mint, sym, int(now), sp, tp))
    return True


def once(con=None, cfg=None, now=None, api=client, dugo_con=None, price_fn=None):
    cfg = cfg or config()
    if not api.key():
        _log("nema SIMIANX_API_KEY, preskačem")
        return {"skipped": "no key"}
    now = now or time.time()
    day_start = int(now) // D * D
    own = con is None
    con = con or store.connect()
    from dugo import store as dstore
    dcon = dugo_con or dstore.ro()
    done = {"reads": 0, "opened": 0, "mapped": 0}
    try:
        cands = candidates(cfg, dcon) if dcon is not None else []
        px = (price_fn or prices)([m for m, *_ in cands] + [r["mint"] for r in con.execute(
            "SELECT mint FROM book WHERE exit_ts IS NULL")])
        book_step(con, cfg, now, px)
        fresh = {m for (m,) in con.execute("SELECT mint FROM opinions WHERE ts>?", (now - cfg["refresh_h"] * 3600,))}
        for mint, sym, name, snap_px in cands:
            if done["reads"] >= cfg["max_per_pass"]:
                break
            if mint in fresh:
                continue
            left = cfg["daily_points"] - store.spent_today(con, day_start)
            if left < cfg["min_points_left"] or api.points_left() < cfg["min_points_left"]:
                _log("dnevni bodovi potrošeni, nastavljam sutra")
                break
            dex_px = px.get(mint) or snap_px
            sx = map_token(con, cfg, mint, sym, dex_px, now, day_start, api)
            done["mapped"] += 1
            if not sx:
                continue
            run = api.quick(sx, cfg["timeframe"], cfg["tier"])
            op = api.parse(run)
            if op.get("empty"):
                con.execute("UPDATE instruments SET ok=0, note=?, ts=? WHERE mint=?", (EMPTY_NOTE, int(now), mint))
                con.commit()
                _log(f"{sym}: SimianX ga ne analizira na ovom planu (0 bodova, bez analize); ostali vjerojatno isto, stajem")
                break
            if op["status"] not in ("done", "partial"):
                _log(f"{sym}: analiza nije završila ({op['status']})")
                continue
            cur = con.execute("""INSERT INTO opinions (mint, symbol, ts, timeframe, view, action, entry, stop, target,
                confidence, reason, says, points, run_id, dex_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (mint, sym, int(now), cfg["timeframe"], op["view"], op["action"], op["entry"], op["stop"],
                               op["target"], op["confidence"], op["reason"], json.dumps(op["says"], ensure_ascii=False),
                               op["points"], op["run_id"], dex_px))
            done["reads"] += 1
            if op["view"] == "long" and open_long(con, cfg, cur.lastrowid, mint, sym, op, px.get(mint), px.get(SOL_MINT), now):
                done["opened"] += 1
            con.commit()
            _log(f"{sym}: {op['view']} (sigurnost {op['confidence']}), {op['points']:.2f} bodova")
        return done
    finally:
        if own:
            con.close()
        if dugo_con is None and dcon is not None:
            dcon.close()
