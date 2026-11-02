"""One pass of the KOL test book, called every minute from the run_paper loop (no extra process, no extra RAM).

1. New calls: every fresh KOL event from kol/converge.events() (X calls incl. the live webhook, Telegram channel
   posts, buys by tracked KOL wallets), each (caller, token) once. A call seen more than max_delay_min after it was
   made is not entered (status skip 'kasno'): we would be measuring somebody else's pump. Caps per source per hour
   and per caller per day keep the book bounded (KOL wallets buy hundreds of tokens a day).
2. Prices: DexScreener (free, the same endpoint the main demo uses), batched 30 tokens per request, not cached on
   disk. Positions younger than fast_h every minute, older ones every slow_every_min minutes, until track_h.
3. Stores per position only the path summary (peak, trough, level hits, returns at fixed times, book), no ticks:
   a few hundred bytes per entry, so 7 days stay well under a few MB.
"""
import json
import os
import sys
import time
import urllib.request

from koltest import book, store

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")


def load_config(path=None):
    with open(path or CONFIG) as f:
        return json.load(f)


def market(tokens):
    """token -> (price, liquidity, mcap, symbol, url) from its deepest pair; None if DexScreener failed."""
    from dexscreener import client
    from event_calendar import http
    best = {}
    toks = sorted(tokens)
    try:
        for i in range(0, len(toks), 30):
            client._FAST.wait()
            req = urllib.request.Request(f"{client.BASE}/tokens/v1/solana/{','.join(toks[i:i + 30])}",
                                         headers={"User-Agent": http.USER_AGENT, "Accept": "application/json"})
            for p in http._fetch(req, 20, 2) or []:
                t = (p.get("baseToken") or {}).get("address")
                liq = (p.get("liquidity") or {}).get("usd") or 0
                if t and liq >= best.get(t, (0, -1))[1]:
                    best[t] = (float(p.get("priceUsd") or 0), liq, p.get("marketCap") or p.get("fdv") or 0,
                               (p.get("baseToken") or {}).get("symbol"), p.get("url"))
    except Exception as e:  # noqa: BLE001 - a failed pass just waits for the next minute
        print(f"  kol test dexscreener: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    return best


def _events(now, cfg):
    from kol import converge
    ev, scores, _ = converge.events(int(now), cfg["lookback_min"] * 60)
    out = []
    for tok, ts, plat, author, kind in ev:
        if (kind == "call" and plat in ("x", "tg")) or (kind == "buy" and plat == "chain"):
            if tok and len(tok) >= 32 and ts:
                out.append((tok, int(ts), plat, author, scores.get(author) or 0))
    return out


def _hour_counts(con, now):
    return dict(con.execute("SELECT source, COUNT(*) FROM positions WHERE status != 'skip' AND seen_ts >= ? "
                            "GROUP BY source", (int(now - 3600),)))


def _caller_counts(con, now):
    return dict(con.execute("SELECT caller, COUNT(*) FROM positions WHERE status != 'skip' AND seen_ts >= ? "
                            "GROUP BY caller", (int(now - 86400),)))


_SEEN = {}   # (caller, token) -> first time this process saw it skipped, so a skip is counted once


def _count_skip(con, now, plat, author, tok, reason):
    key = (author, tok)
    for k in [k for k, t in _SEEN.items() if now - t > 3 * 3600]:
        del _SEEN[k]
    if key in _SEEN:
        return
    _SEEN[key] = now
    k = f"skip:{time.strftime('%Y-%m-%d', time.gmtime(now))}:{plat}:{reason}"
    store.kv_set(con, k, int(store.kv_get(con, k, 0)) + 1)


def intake(con, cfg, now, events):
    """Insert new (caller, token) pairs as pending (priced and entered right after). Calls that are too old or over
    a cap are only counted per day and source (kv skip:<day>:<source>:<reason>), not stored one by one: KOL
    wallets alone buy well over a thousand tokens a day."""
    start, end = store.window(con, cfg, now)
    if now >= end or not events:
        return
    toks = list({e[0] for e in events})
    q = ",".join("?" * len(toks))
    known = {(c, t) for c, t in con.execute(f"SELECT caller, token FROM positions WHERE token IN ({q})", toks)}
    hour, per_caller = _hour_counts(con, now), _caller_counts(con, now)
    # best callers first when the hourly cap is tight; inside equal scores the NEWEST call first (oldest-first filled
    # the cap with calls just under the 10-min limit: median delay was ~580 s on 1.11.)
    # A call skipped once (late or over a cap) is never taken later: when a cap slot freed up, the next pass used to
    # pick a call that had waited up to 10 min (median entry 546 s after a KOL wallet buy on 2.11.), so the test
    # measured entries long after the call. Now a call is entered when first seen or not at all.
    for tok, ts, plat, author, score in sorted(events, key=lambda e: (-e[4], -e[1])):
        if (author, tok) in known or (author, tok) in _SEEN or ts < start:   # before the test began: not part of it
            continue
        known.add((author, tok))
        if now - ts > cfg["max_delay_min"] * 60:
            _count_skip(con, now, plat, author, tok, "kasno")
        elif hour.get(plat, 0) >= cfg["per_hour"].get(plat, 10):
            _count_skip(con, now, plat, author, tok, "limit po satu")
        elif per_caller.get(author, 0) >= cfg["per_caller_day"]:
            _count_skip(con, now, plat, author, tok, "limit po KOL-u")
        else:
            con.execute("INSERT OR IGNORE INTO positions (token, source, caller, score, call_ts, seen_ts, status) "
                        "VALUES (?,?,?,?,?,?,'pending')", (tok, plat, author, score, ts, int(now)))
            hour[plat] = hour.get(plat, 0) + 1
            per_caller[author] = per_caller.get(author, 0) + 1


def skips(con, since_day=None):
    """{(source, reason): n} over the test (or from since_day 'YYYY-MM-DD')."""
    out = {}
    for k, v in con.execute("SELECT key, value FROM kv WHERE key LIKE 'skip:%'"):
        _, day, plat, reason = k.split(":", 3)
        if since_day and day < since_day:
            continue
        out[(plat, reason)] = out.get((plat, reason), 0) + int(v)
    return out


def _save(con, rid, pos, status=None):
    con.execute("""UPDATE positions SET entry_ts=?, entry_px=?, entry_mcap=?, entry_liq=?, last_ts=?, last_px=?,
                   last_liq=?, last_mcap=?, peak=?, peak_ts=?, trough=?, trough_ts=?, hits=?, rets=?, book=?, pnl_usd=?,
                   book_closed_ts=?, book_reason=?, status=COALESCE(?, status) WHERE id=?""",
                (pos["entry_ts"], pos["entry_px"], pos["entry_mcap"], pos["entry_liq"], pos["last_ts"], pos["last_px"],
                 pos["last_liq"], pos["last_mcap"], pos["peak"], pos["peak_ts"], pos["trough"], pos["trough_ts"],
                 json.dumps(pos["hits"]), json.dumps(pos["rets"]), json.dumps(pos["book"]), pos["pnl_usd"],
                 pos["book_closed_ts"], pos["book_reason"], status, rid))


def _fix_gap_fills(con, cfg):
    """Once: ladder sales made before 1.11. at the market price of a jump far past the level (one fake +50,000% tick
    booked +$24k) are re-priced at the level, as a limit order there would have filled."""
    if store.kv_get(con, "fix_gap_fills"):
        return
    for p in store.rows(con):
        b = p["book"]
        changed = False
        for f in b.get("fills", []):
            r = f.get("reason") or ""
            if r.startswith("+") and r.endswith("%") and f.get("ret") is not None:
                lv = float(r[1:-1]) / 100
                if f["ret"] > lv:
                    f["usd"] = round(f["usd"] * (1 + lv) / (1 + f["ret"]), 4)
                    f["ret"] = lv
                    changed = True
        if changed:
            b["realized"] = sum(f["usd"] for f in b["fills"])
            pnl = book.value(p, cfg)
            con.execute("UPDATE positions SET book=?, pnl_usd=? WHERE id=?", (json.dumps(b), round(pnl, 4), p["id"]))
    store.kv_set(con, "fix_gap_fills", 1)
    con.commit()


def step(now=None, cfg=None, path=None, market_fn=None, events_fn=None, quiet=False):
    """One pass. Returns {'entered': n, 'open': n, 'done': n}."""
    cfg = cfg or load_config()
    if not cfg.get("enabled", True):
        return {}
    now = now or time.time()
    market_fn = market_fn or market
    con = store.connect(path)
    try:
        _fix_gap_fills(con, cfg)
        start, end = store.window(con, cfg, now)
        if now < end:
            intake(con, cfg, now, (events_fn or _events)(now, cfg))
        con.commit()
        pending = con.execute("SELECT id, token, seen_ts FROM positions WHERE status='pending'").fetchall()
        live = store.rows(con, "status='open'")
        fast = now - cfg["fast_h"] * 3600
        slow_turn = int(now // 60) % max(1, int(cfg["slow_every_min"])) == 0
        due = [p for p in live if p["entry_ts"] >= fast or slow_turn or now - p["entry_ts"] >= cfg["track_h"] * 3600]
        tokens = {t for _, t, _ in pending} | {p["token"] for p in due}
        mk = market_fn(tokens) if tokens else {}
        if mk is None:
            return {"entered": 0, "open": len(live), "done": 0}
        entered = done = 0
        for rid, tok, seen in pending:
            m = mk.get(tok)
            if m and m[0] > 0 and m[2] and (m[1] or 0) > m[2]:
                # liquidity above the whole market cap: a fake pool (price set by a tiny supply, 1.11. rugs)
                con.execute("UPDATE positions SET status='skip', close_reason='lažni pool', symbol=? WHERE id=?",
                            (m[3], rid))
            elif m and m[0] > 0 and (m[1] or 0) >= cfg["min_liq"] and (m[2] or 0) <= cfg.get("max_mcap", 5e7):
                pos = book.new_position(m[0], m[1], m[2], int(now), cfg)
                con.execute("UPDATE positions SET symbol=?, url=? WHERE id=?", (m[3], m[4], rid))
                _save(con, rid, pos, "open")
                entered += 1
            elif m and m[0] > 0 and (m[2] or 0) > cfg.get("max_mcap", 5e7):
                # wrapped BTC/ETH, stablecoins, big caps a KOL wallet parks money in: not a call, frees the slot
                con.execute("UPDATE positions SET status='skip', close_reason='velik token', symbol=? WHERE id=?",
                            (m[3], rid))
            elif m and m[0] > 0 and (m[1] or 0) < cfg["min_liq"]:
                con.execute("UPDATE positions SET status='skip', close_reason='premala likvidnost', symbol=? "
                            "WHERE id=?", (m[3], rid))
            elif now - seen > cfg["price_wait_min"] * 60:
                con.execute("UPDATE positions SET status='skip', close_reason='nema cijene' WHERE id=?", (rid,))
        for p in due:
            m = mk.get(p["token"])
            if m:
                book.update(p, m[0], m[1], m[2], int(now), cfg)
                p["missing_since"] = None
            elif not p.get("missing_since"):
                p["missing_since"] = int(now)
            status, reason = None, None
            if now - p["entry_ts"] >= cfg["track_h"] * 3600:
                status, reason = "done", f"{cfg['track_h']} h prošlo"
            elif p.get("missing_since") and now - p["missing_since"] >= cfg["missing_h"] * 3600:
                status, reason = "done", "nestao s DexScreenera"
            if status:
                book.finish(p, int(now), reason, cfg)
                done += 1
            _save(con, p["id"], p, status)
            con.execute("UPDATE positions SET missing_since=?, done_ts=?, close_reason=COALESCE(?, close_reason) "
                        "WHERE id=?", (p.get("missing_since"), int(now) if status else None, reason, p["id"]))
        con.execute("DELETE FROM positions WHERE status='skip' AND seen_ts < ?",
                    (int(now - cfg["keep_skips_days"] * 86400),))
        con.commit()
        n_open = len(live) - done + entered
        if entered and not quiet:
            print(f"KOL test: +{entered} ulaza, otvoreno {n_open}", flush=True)
        return {"entered": entered, "open": n_open, "done": done}
    finally:
        con.close()


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "status":
        con = store.ro()
        if con is None:
            print("KOL test još nije pokrenut.")
            return 0
        cfg = load_config()
        ps = store.rows(con)
        print(json.dumps(book.summary(ps, cfg), indent=1, default=str))
        return 0
    print(step())
    return 0


if __name__ == "__main__":
    sys.exit(main())
