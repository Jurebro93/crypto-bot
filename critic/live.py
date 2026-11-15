"""Kritičar (OpenAI): a comment on every real-money fill (15.11. navečer, vlasnik: "live komentar na svaki live trade").
ADVICE ONLY: it reads trade.db, it never places, changes or closes a trade.

The watcher (python3 run_critic.py loop, a supervised low-priority process from start.sh) reads trade.db orders every
POLL_S seconds by id: a new row with mode live, status ok and side buy / sell is an executed real-money trade (a buy, a
partial sale or a close). DEBOUNCE_S after the newest fill (fills close together, e.g. a TP that sells two lots, go
in one call) it runs ONE short child process (python3 run_critic.py live --od A --do B) that comments every fill in
(A, B] and ends (its memory goes back; the watcher itself only holds a SQLite connection). The first start remembers
the newest order and comments nothing older. Owner switch off or no key: the watcher looks again every IDLE_S.

The child: per fill the order (side, SOL, the swap's cost, the reason / strategy), the position as the Pozicije card has
it (or, after a close, its realized PnL and times), the path since the entry, the strategy's 30-day record, what the
critic said about the position before, the macro state; ONE call (OPENAI_MODEL_LIVE, gpt-6-astra, the cheap model
once 70 % of the day is used or when the strong one does not fit; budget priority 1). Every comment is a trade_review
note on the position (the card's "Kritičar (OpenAI)" line) and, while the position is open, a critic_verdicts row
(measured like the re-checks). Log: "kritičar: live komentar <SIMBOL> <kupnja|prodaja>: ...".
"""
import json
import os
import subprocess
import sys
import time

from critic import data as cdata
from critic import notes as cnotes
from critic import openai_api, privacy, prompts
from critic import store

POLL_S = 5
DEBOUNCE_S = 20
MAX_WAIT_S = 60   # fills that keep coming are commented at the latest this long after the first
IDLE_S = 60
MAX_FILLS = 12
MAX_OUT = 3000
EFFORT = "low"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILL_SQL = ("SELECT id, ts, position_id, token, side, amount_in, amount_out, cost_pct, reason FROM orders WHERE id > ? "
            "AND id <= ? AND mode='live' AND status='ok' AND side IN ('buy','sell') ORDER BY id LIMIT ?")
SIDE = {"buy": "kupnja", "sell": "prodaja"}
OCJENA_NOTE = {"dobar": "dobar", "los": "loš", "neutralan": "neutralan"}
LAMPORTS = 1_000_000_000


def newest_order(tcon):
    r = tcon.execute("SELECT MAX(id) FROM orders").fetchone()
    return int(r[0] or 0)


def pending_fills(tcon, after_id):
    """(newest fill id, its order ts) of the live fills after after_id, or (None, None)."""
    r = tcon.execute("SELECT MAX(id), MAX(ts) FROM orders WHERE id > ? AND mode='live' AND status='ok' AND side IN "
                     "('buy','sell')", (int(after_id),)).fetchone()
    return (int(r[0]), int(r[1] or 0)) if r and r[0] else (None, None)


def _closed_summary(tcon, pid):
    r = tcon.execute("SELECT token, symbol, opened_ts, closed_ts, status, sol_in, sol_back, COALESCE(fees_sol, 0), mode "
                     "FROM positions WHERE id=?", (int(pid),)).fetchone()
    if not r:
        return None
    tok, sym, ots, cts, st, sin, sback, fees, mode = r
    return {"token": tok, "simbol": sym, "status": st, "starost_min": int(((cts or time.time()) - (ots or 0)) // 60),
            "ulog_sol": round(sin or 0, 4), "vraceno_sol": round(sback or 0, 4), "fee_sol": round(fees or 0, 5),
            "ostvareni_pnl_pct": round(((sback or 0) - (sin or 0) - (fees or 0)) / sin * 100, 2) if sin else None,
            "ostvareni_pnl_sol": round((sback or 0) - (sin or 0) - (fees or 0), 5), "mode": mode, "opened_ts": ots}


def _past(tcon, pid, now, n=3):
    return [{"verdict": v, "prije_min": int((now - ts) // 60), "pnl_tada_pct": round(p, 1) if p is not None else None}
            for ts, v, p in tcon.execute("SELECT ts, verdict, pnl_pct FROM critic_verdicts WHERE pid=? ORDER BY id DESC "
                                         "LIMIT ?", (int(pid), n))]


def validate(d, ids):
    if not isinstance(d, dict) or not isinstance(d.get("tradeovi"), list):
        raise ValueError("nema popisa tradeovi")
    out, seen = [], set()
    for x in d["tradeovi"]:
        if not isinstance(x, dict):
            continue
        try:
            oid = int(x.get("id"))
            c = float(x.get("confidence"))
        except (TypeError, ValueError):
            continue
        o, v = str(x.get("ocjena") or ""), str(x.get("verdict") or "")
        kom = [str(k).strip()[:300] for k in (x.get("komentar") or []) if str(k or "").strip()][:3]
        if oid not in ids or oid in seen or o not in prompts.OCJENE or v not in prompts.LIVE_VERDICTS \
                or not 0 <= c <= 1 or not kom:
            continue
        seen.add(oid)
        out.append({"id": oid, "ocjena": o, "verdict": v, "confidence": round(c, 3), "komentar": kom,
                    "promijenilo_bi": str(x.get("promijenilo_bi") or "").strip()[:300]})
    if not out:
        raise ValueError("nijedan komentar nije valjan")
    return out


def note_text(side, c):
    bits = [f"{SIDE.get(side, side).upper()}: {c['ocjena'].upper()}"] + c["komentar"]
    if c["verdict"] != "zatvoreno":
        bits.append("dalje: " + cnotes.WORDS.get(c["verdict"], c["verdict"]))
    if c.get("promijenilo_bi"):
        bits.append("promijenilo bi: " + c["promijenilo_bi"])
    return " · ".join(bits)


def run(from_id, to_id, now=None, log=print, tcon=None, positions_fn=None, call=None, series_fn=None):
    """Comment the live fills with from_id < id <= to_id in one call. Returns a small dict."""
    from critic import trades as ctrades
    now = int(now or time.time())
    own = tcon is None
    if own:
        from trade import executor, settings
        tcon = executor.connect(settings.DB)
    try:
        store.ensure(tcon)
        done = lambda: store.kv_put(tcon, "live_last_order", int(to_id))   # noqa: E731
        if not ctrades.enabled(tcon):
            return {"skip": "isključen"}
        if not openai_api.has_key():
            ctrades.nokey_line(tcon, now, log)
            return {"skip": "nema ključa"}
        fills = tcon.execute(FILL_SQL, (int(from_id), int(to_id), MAX_FILLS)).fetchall()
        if not fills:
            done()
            return {"skip": "nema novih tradeova"}
        positions, live, sol = (positions_fn or ctrades.load_positions)(tcon, now)
        by_id = {}
        for p in positions:
            for i in p.get("ids") or [p["pid"]]:
                by_id[int(i)] = p
        last = store.last_verdicts(tcon, [p["pid"] for p in positions])
        hist = cdata.strategy_stats(tcon, now, detail=False)
        open_items = {row["pid"]: (it, row) for it, row in
                      ctrades.build_items(tcon, positions, live, sol, now, last, hist, series_fn)}
        items, meta, mints = [], {}, set()
        for oid, ts, pid, tok, side, a_in, a_out, cost_pct, reason in fills:
            p = by_id.get(int(pid or 0))
            pair = open_items.get(p["pid"]) if p else None
            closed = None if pair else _closed_summary(tcon, pid or 0)
            strat = ctrades._strategy(tcon, pid or 0)
            sol_amt = (a_in if side == "buy" else a_out) or 0
            item = {"id": int(oid), "vrsta": SIDE[side], "prije_s": int(now - (ts or now)),
                    "sol": round(sol_amt / LAMPORTS, 5), "trosak_swapa_pct": cost_pct, "strategija": strat,
                    "razlog": str(reason or "")[:200], "povijest_strategije_30d": hist.get(strat),
                    "pozicija": pair[0] if pair else None, "zatvorena_pozicija": closed,
                    "prosle_presude": _past(tcon, p["pid"] if p else (pid or 0), now)}
            if closed and closed.get("opened_ts"):
                item["kretanje_od_ulaza"] = ctrades.path_summary(
                    tok, closed["opened_ts"], now, None,
                    series_fn(tok, closed["opened_ts"], now) if series_fn else None).get("kretanje")
            items.append(item)
            meta[int(oid)] = {"side": side, "pid": p["pid"] if p else int(pid or 0), "row": pair[1] if pair else None,
                              "sym": (p or {}).get("sym") or (closed or {}).get("simbol") or "?"}
            mints.add(tok)
        payload = {"vrijeme_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), "makro": cdata.makro(now),
                   "sol_usd": round(sol, 2) if sol else None, "tradeovi": items}
        text = prompts.LIVE_TRADE + "\n\nPodaci (JSON):\n" + json.dumps(payload, ensure_ascii=False,
                                                                       separators=(",", ":"), default=str)
        wallets = privacy.owner_wallets(tcon)
        text = privacy.scrub(text, mints, extra=wallets)
        if privacy.leaks(text, mints, extra=wallets):
            done()
            log("kritičar: live komentar nije poslan (privatnost)", flush=True)
            return {"skip": "privatnost"}
        model, _est = store.pick(tcon, "live", openai_api.MODEL_LIVE, len(text) + len(prompts.SYSTEM), MAX_OUT, now, log)
        if model is None:
            done()
            return {"skip": "budžet"}
        fn = call or openai_api.call_json
        try:
            res = fn(model, prompts.SYSTEM, text, prompts.LIVE_SCHEMA, "kriticar_live", MAX_OUT, EFFORT)
        except openai_api.ApiError as e:
            c = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
            store.book(tcon, "live", e.model or model, e.usage, c, False, str(e), text, now=now)
            done()
            log(f"kritičar: live komentar nije uspio ({e})", flush=True)
            return {"skip": "greška API-ja", "greska": str(e)}
        try:
            comments = validate(res["data"], set(meta))
        except ValueError as e:
            store.book(tcon, "live", res["model"], res["usage"], res["cost_usd"], False, f"neispravan odgovor: {e}",
                       text, now=now)
            done()
            log(f"kritičar: live komentar neispravan ({e}), trošak {res['cost_usd']:.4f} $", flush=True)
            return {"skip": "neispravan odgovor", "greska": str(e)}
        call_id = store.book(tcon, "live", res["model"], res["usage"], res["cost_usd"], True, None, text,
                             n=len(comments), now=now)
        from ui import assistnotes
        share = res["cost_usd"] / max(1, len(comments))
        for c in comments:
            m = meta[c["id"]]
            ev = {"kriticar": "openai", "vrsta": "live", "strana": SIDE[m["side"]], "verdict": c["verdict"],
                  "ocjena": c["ocjena"], "order_id": c["id"], "model": res["model"], "call_id": call_id}
            nid = None
            try:
                nid = assistnotes.submit_trade_review(tcon, cnotes.KID, m["pid"], OCJENA_NOTE[c["ocjena"]],
                                                      c["confidence"], note_text(m["side"], c), None, ev)["id"]
            except ValueError as e:
                log(f"kritičar: live bilješka za poziciju {m['pid']} nije zapisana ({e})", flush=True)
            if m["row"] and c["verdict"] != "zatvoreno":
                store.add_verdict(tcon, call_id, nid, m["row"], c, now)
            log(f"kritičar: live komentar {m['sym']} {SIDE[m['side']]}: {c['ocjena']}, dalje "
                f"{cnotes.WORDS.get(c['verdict'], c['verdict'])}, sigurnost {c['confidence']:.2f}, trošak "
                f"{share:.4f} $ ({res['model']})", flush=True)
        tcon.commit()
        done()
        return {"komentara": len(comments), "cost_usd": res["cost_usd"], "call_id": call_id}
    finally:
        if own:
            tcon.close()


def _spawn(a, b, log):
    cmd = [sys.executable, os.path.join(ROOT, "run_critic.py"), "live", "--od", str(a), "--do", str(b)]
    try:
        subprocess.run(cmd, cwd=ROOT, timeout=600)
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"kritičar: live komentar (dijete) nije završio ({type(e).__name__})", flush=True)


def loop(log=print, spawn=None, sleep=time.sleep, once=False, tcon=None, debounce=DEBOUNCE_S):
    """The watcher: every POLL_S a look at trade.db orders by id; `debounce` s after the newest new live fill one
    child. once (tests): one look and return what it did."""
    from critic import trades as ctrades
    own = tcon is None
    if own:
        from trade import executor, settings
        tcon = executor.connect(settings.DB)
    store.ensure(tcon)
    spawn = spawn or _spawn
    last = store.kv_get(tcon, "live_last_order")
    if last is None:
        last = newest_order(tcon)
        store.kv_put(tcon, "live_last_order", last)
        log(f"kritičar: live komentari od naloga #{last} nadalje", flush=True)
    seen_at, seen_id, first_at = None, None, None
    try:
        while True:
            did = None
            if not ctrades.enabled(tcon) or not openai_api.has_key():
                if once:
                    return "mirujem"
                sleep(IDLE_S)
                continue
            last = int(store.kv_get(tcon, "live_last_order", last) or last)
            newest, _ts = pending_fills(tcon, last)
            if newest is not None:
                t = time.monotonic()
                if newest != seen_id:
                    seen_id, seen_at = newest, t
                    first_at = first_at or t
                # quiet for `debounce` s, or fills keep coming for MAX_WAIT_S: one child for all of them
                if t - seen_at >= debounce or t - first_at >= MAX_WAIT_S:
                    spawn(last, newest, log)
                    if (store.kv_get(tcon, "live_last_order", last) or last) < newest:   # the child died early
                        store.kv_put(tcon, "live_last_order", newest)
                    seen_id = seen_at = first_at = None
                    did = "komentirao"
                else:
                    did = "čekam"
            tcon.commit()   # no read transaction left open between looks
            if once:
                return did
            sleep(POLL_S)
    finally:
        if own:
            tcon.close()
