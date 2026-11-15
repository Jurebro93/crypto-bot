"""Kritičar (OpenAI): the open-trade critic (15.11., vlasnik). ADVICE ONLY: it never places, changes or closes a trade
and never changes a setting; the verdict is a note the owner reads on the Pozicije card ("Kritičar (OpenAI)").

A pass (run_critic.py trades, every KRITICAR_EVERY_MIN minutes from run_sched; a short process):
  1. the owner switch openai_kritika (trade/settings; "uživo" = on, the default) - off: the pass ends at once
  2. the measurement of earlier verdicts (+30 / +60 min, at the close; critic/store.evaluate) - needs no key
  3. without OPENAI_API_KEY one line an hour "kritičar: nema OPENAI_API_KEY, preskačem" and the end
  4. the open positions exactly as the Pozicije card shows them (ui/apterm.positions_data: real money and the
     program's / Grok's positions, live first), their market from one free DexScreener request
  5. a call only when something changed: a new position, PnL moved >= PNL_MOVE_PP points since its last verdict, or
     its last verdict is older than KRITICAR_MAX_MIN (15) minutes while a real-money position is open, else
     KRITICAR_PAPER_MAX_MIN (30); ONE batched call for every open position (at most MAX_POSITIONS), OPENAI_MODEL
     (gpt-6-astra; OPENAI_MODEL_CHEAP once 70 % of the day's budget is used) with reasoning effort low; after a
     failed call FAIL_BACKOFF_S without a call. A real-money fill gets its own comment at once (critic/live.py).
  6. the budget (critic/store.refusal), the privacy scrub (critic/privacy), the answer validated field by field;
     every verdict is a critic_verdicts row and a trade_review note (critic/notes.py), one log line per batch
"""
import json
import os
import time

from critic import data as cdata
from critic import notes as cnotes
from critic import openai_api, privacy, prompts
from critic import store

FLAG = "openai_kritika"
PNL_MOVE_PP = 10.0
MAX_LIVE_S = int(float(os.environ.get("KRITICAR_MAX_MIN") or 15) * 60)
MAX_PAPER_S = int(float(os.environ.get("KRITICAR_PAPER_MAX_MIN") or 30) * 60)
MAX_POSITIONS = 12
MAX_OUT = 4000
EFFORT = "low"
FAIL_BACKOFF_S = 600
NOKEY_LOG_S = 3600
PATH_H = 6


def enabled(tcon):
    """The owner switch openai_kritika: "uživo" (its default) = on; any other mode = off."""
    from trade import settings
    return settings.flag(FLAG, con=tcon) == "live"


def nokey_line(tcon, now, log=print):
    last = store.kv_get(tcon, "nokey_ts", 0) or 0
    if now - last >= NOKEY_LOG_S:
        store.kv_put(tcon, "nokey_ts", int(now))
        log("kritičar: nema OPENAI_API_KEY, preskačem", flush=True)


# ---------- the positions and their data -----------------------------------------------------------------------------

def _r(x, n=2):
    return round(float(x), n) if x is not None else None


def load_positions(tcon, now):
    """(positions as the Pozicije card has them, {token: live row}, SOL USD). Imports the page code only when
    positions are open."""
    toks = [r[0] for r in tcon.execute("SELECT DISTINCT token FROM positions WHERE status='open'")]
    if not toks:
        return [], {}, None
    live, sol = cdata.live_market(toks)
    from ui import apterm
    from ui import pravitrade as pt
    cfg = pt._cfg(tcon)
    pos = apterm.positions_data(tcon, cfg, now, live=live or {})
    return pos, live, sol


def _series(token, t0, now):
    """Minute candles (ts, o, h, l, c, v, buys, sells) and the snapshots of a token since t0 from our own data."""
    try:
        from rangedca import data as rdata
        con = rdata.ro()
        try:
            snaps = (rdata.own_rows(con, token, t0) if con is not None else []) + rdata.pulse_rows(token, t0)
            true = (rdata.gt_rows(con, token, t0, now) if con is not None else []) + rdata.call_candles(token, t0, now)
        finally:
            if con is not None:
                con.close()
        return rdata.merge(true, snaps), snaps
    except Exception:  # noqa: BLE001 - no stored data: the payload says so
        return [], []


def path_summary(token, opened_ts, now, supply, series=None):
    """The price path since the entry (at most PATH_H hours), compact, in market cap: peak and trough since the
    entry, MC 60 / 30 / 15 / 5 min ago, 8 points; the last 15 min's buys / sells; the liquidity at the entry."""
    t0 = int(max(opened_ts or now, now - PATH_H * 3600)) - 600
    cs, snaps = series if series is not None else _series(token, t0, now)
    out = {}
    liq0 = min((s for s in snaps if s.get("liq") and opened_ts and abs(s["ts"] - opened_ts) <= 900),
               key=lambda s: abs(s["ts"] - opened_ts), default=None)
    if liq0:
        out["likvidnost_na_ulazu_usd"] = round(liq0["liq"])
    if not cs or not supply:
        out["kretanje"] = "nema spremljenih snimki za ovaj token"
        return out
    pts = [(int(c[0]), float(c[4]) * supply) for c in cs if c[4]]
    after = [p for p in pts if p[0] >= (opened_ts or 0)] or pts
    if after:
        hi = max(after, key=lambda p: p[1])
        lo = min(after, key=lambda p: p[1])
        out["vrh_od_ulaza"] = {"mc": round(hi[1]), "prije_min": int((now - hi[0]) // 60)}
        out["dno_od_ulaza"] = {"mc": round(lo[1]), "prije_min": int((now - lo[0]) // 60)}
    ago = {}
    for m in (60, 30, 15, 5):
        t = now - m * 60
        best = min(pts, key=lambda p: abs(p[0] - t))
        if abs(best[0] - t) <= 600:
            ago[str(m)] = round(best[1])
    if ago:
        out["mc_prije_min"] = ago
    step = max(1, len(after) // 8)
    out["tocke_min_mc"] = [[int((now - p[0]) // 60), round(p[1])] for p in after[::step][-8:]]
    last15 = [c for c in cs if c[0] >= now - 900]
    b = sum(c[6] or 0 for c in last15 if c[6] is not None)
    s = sum(c[7] or 0 for c in last15 if c[7] is not None)
    if last15 and (b or s):
        out["m15"] = {"kupnje": int(b), "prodaje": int(s), "volumen_usd": round(sum(c[5] or 0 for c in last15))}
    return out


def _value_sol(p):
    if not p.get("mc_now"):
        return None
    tot = 0.0
    for sin, held, lmc, _sback in p.get("lots") or []:
        base = lmc or p.get("avg_mc")
        if base:
            tot += (sin or 0) * (held or 0) * p["mc_now"] / base
    return tot


def _strategy(tcon, pid):
    from trade import executor
    r = tcon.execute("SELECT reason FROM positions WHERE id=?", (int(pid),)).fetchone()
    return executor.strategy_of(r[0] if r else "")


def _rug(token, mcap, liq):
    try:
        from ui import apterm
        return apterm._rug(token, mcap, liq).get("text")
    except Exception:  # noqa: BLE001
        return None


def build_items(tcon, positions, live, sol, now, last, hist, series_fn=None):
    """[(item for the payload, row for the store)] of the positions with a price (live first, MAX_POSITIONS)."""
    from trade import cost
    out = []
    for p in positions:
        if not p.get("mc_now") or not p.get("avg_mc"):
            continue
        tok = p["token"]
        lv = (live or {}).get(tok) or {}
        liq = lv.get("liq")
        size_usd = (p.get("sol_in") or 0) * sol if sol else None
        rt = cost.round_trip(size_usd, liq)
        strat = _strategy(tcon, p["pid"])
        supply = (p["mc_now"] / lv["price"]) if lv.get("price") else None
        ps = path_summary(tok, p.get("opened_ts"), now, supply,
                          series_fn(tok, p.get("opened_ts"), now) if series_fn else None)
        liq0 = ps.pop("likvidnost_na_ulazu_usd", None)
        w = lv.get("w") or {}
        tok_flow = {k: {"kupnje": (w.get(k) or {}).get("buys"), "prodaje": (w.get(k) or {}).get("sells"),
                        "volumen_usd": _r((w.get(k) or {}).get("vol"), 0), "promjena_cijene_pct": (w.get(k) or {}).get("ch")}
                    for k in ("m5", "h1", "h6") if w.get(k)}
        if ps.get("m15"):
            tok_flow["m15"] = ps.pop("m15")
        b = p.get("by") or {}
        prev = last.get(p["pid"])
        h = (hist.get(strat) or {})
        item = {
            "id": int(p["pid"]), "simbol": p.get("sym"), "novac": "pravi" if p.get("mode") == "live" else "demo",
            "strategija": strat, "izvor": b.get("tag") or p.get("src"),
            "grok": p.get("grok"), "ulaz_mc": _r(p["avg_mc"], 0), "sada_mc": _r(p["mc_now"], 0),
            "pnl_bruto_pct": _r(p.get("pnl_pct"), 1), "trosak_kruga_pct": _r(rt * 100, 1),
            "pnl_nakon_fija_pct": _r((p.get("pnl_pct") or 0) - rt * 100, 1),
            "starost_min": int((now - (p.get("opened_ts") or now)) // 60),
            "ulog_sol": _r(p.get("sol_in"), 4), "drzi_udio": p.get("held"), "lotova": p.get("n_lots"),
            "plan_izlaza": {"tp_pct": p.get("tp_pct"), "tp_mc": _r(p.get("tp_mc"), 0), "sl_pct": p.get("sl_pct"),
                            "sl_mc": _r(p.get("sl_mc"), 0), "trailing": p.get("trail"), "opis": p.get("exit"),
                            "plan": (p.get("plan") or {}).get("summary") or None},
            "likvidnost_usd": _r(liq, 0), "likvidnost_na_ulazu_usd": liq0,
            "promjena_likvidnosti_pct": _r((liq / liq0 - 1) * 100, 1) if liq and liq0 else None,
            "protok": tok_flow or None, "kretanje": ps, "rug": _rug(tok, p["mc_now"], liq),
            "povijest_strategije_30d": h or None,
            "prosla_presuda": ({"verdict": prev[2], "prije_min": int((now - prev[0]) // 60), "pnl_tada_pct": _r(prev[1], 1)}
                               if prev else None)}
        vs = _value_sol(p)
        row = {"pid": int(p["pid"]), "token": tok, "sym": p.get("sym"), "mode": p.get("mode"), "strategy": strat,
               "pnl_pct": _r(p.get("pnl_pct"), 2), "mc_now": p["mc_now"],
               "value_usd": _r(vs * sol, 2) if vs is not None and sol else None}
        out.append((item, row))
        if len(out) >= MAX_POSITIONS:
            break
    return out


def due(positions, last, now):
    """(any position needs a critique, why) by the change rules."""
    live_open = any(p.get("mode") == "live" for p in positions)
    gap = MAX_LIVE_S if live_open else MAX_PAPER_S
    for p in positions:
        if not p.get("mc_now"):
            continue
        prev = last.get(p["pid"])
        if prev is None:
            return True, f"nova pozicija {p.get('sym')}"
        if p.get("pnl_pct") is not None and prev[1] is not None and abs(p["pnl_pct"] - prev[1]) >= PNL_MOVE_PP:
            return True, f"{p.get('sym')} PnL {prev[1]:+.0f} -> {p['pnl_pct']:+.0f} %"
        if now - prev[0] >= gap:
            return True, f"{p.get('sym')} zadnja presuda prije {int((now - prev[0]) // 60)} min"
    return False, None


# ---------- the answer -----------------------------------------------------------------------------------------------

def _num_or_none(x):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 1e12 else None


def validate(d, ids):
    """[clean verdict] of the model's answer for the asked ids; raises ValueError when the answer is unusable."""
    if not isinstance(d, dict) or not isinstance(d.get("pozicije"), list):
        raise ValueError("nema popisa pozicije")
    out, seen = [], set()
    for x in d["pozicije"]:
        if not isinstance(x, dict):
            continue
        try:
            pid = int(x.get("id"))
        except (TypeError, ValueError):
            continue
        if pid not in ids or pid in seen:
            continue
        v = str(x.get("verdict") or "").strip().lower()
        if v not in prompts.VERDICTS:
            continue
        try:
            c = float(x.get("confidence"))
        except (TypeError, ValueError):
            continue
        if not 0 <= c <= 1:
            continue
        reasons = [str(r).strip()[:300] for r in (x.get("razlozi") or []) if str(r or "").strip()][:3]
        if not reasons:
            continue
        seen.add(pid)
        out.append({"id": pid, "verdict": v, "confidence": round(c, 3), "razlozi": reasons,
                    "promijenilo_bi": str(x.get("promijenilo_bi") or "").strip()[:300],
                    "predlozeni_sl_mc": _num_or_none(x.get("predlozeni_sl_mc")),
                    "predlozeni_tp_mc": _num_or_none(x.get("predlozeni_tp_mc"))})
    if not out:
        raise ValueError("nijedna presuda nije valjana")
    opce = d.get("opce")
    return out, (str(opce).strip()[:400] if opce else None)


# ---------- the pass -------------------------------------------------------------------------------------------------

def run(now=None, log=print, tcon=None, positions_fn=None, live_fn=None, call=None, series_fn=None, force=False):
    """One pass. Returns a small dict of what happened (tests and the CLI print it)."""
    now = int(now or time.time())
    own = tcon is None
    if own:
        from trade import executor, settings
        tcon = executor.connect(settings.DB)
    try:
        store.ensure(tcon)
        if not enabled(tcon):
            return {"skip": "isključen"}
        try:
            n_eval = store.evaluate(tcon, now, live_fn=live_fn or (lambda toks: {t: (r or {}).get("mcap") for t, r in
                                                                               cdata.live_market(toks)[0].items()}))
        except Exception as e:  # noqa: BLE001 - the measurement never costs the critique
            log(f"kritičar: mjerenje presuda nije uspjelo ({type(e).__name__}: {e})", flush=True)
            n_eval = 0
        if not openai_api.has_key():
            nokey_line(tcon, now, log)
            return {"skip": "nema ključa", "ocijenjeno": n_eval}
        if not tcon.execute("SELECT 1 FROM positions WHERE status='open' LIMIT 1").fetchone():
            return {"skip": "nema otvorenih pozicija", "ocijenjeno": n_eval}
        fail = store.kv_get(tcon, "trades_fail_ts", 0) or 0
        if not force and now - fail < FAIL_BACKOFF_S:
            return {"skip": "pauza nakon neuspjelog poziva", "ocijenjeno": n_eval}
        positions, live, sol = (positions_fn or load_positions)(tcon, now)
        last = store.last_verdicts(tcon, [p["pid"] for p in positions])
        go, why = due(positions, last, now)
        if not go and not force:
            return {"skip": "ništa se nije promijenilo", "ocijenjeno": n_eval}
        hist = cdata.strategy_stats(tcon, now, detail=False)
        pairs = build_items(tcon, positions, live, sol, now, last, hist, series_fn)
        if not pairs:
            return {"skip": "nijedna pozicija nema cijenu", "ocijenjeno": n_eval}
        payload = {"vrijeme_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), "makro": cdata.makro(now),
                   "sol_usd": _r(sol, 2), "pozicije": [it for it, _row in pairs]}
        mints = {row["token"] for _it, row in pairs}
        text = prompts.OPEN_TRADES + "\n\nPodaci (JSON):\n" + json.dumps(payload, ensure_ascii=False,
                                                                         separators=(",", ":"), default=str)
        text = privacy.scrub(text, mints, extra=privacy.owner_wallets(tcon))
        bad = privacy.leaks(text, mints, extra=privacy.owner_wallets(tcon))
        if bad:
            log(f"kritičar: podaci za pozicije nisu poslani (privatnost: {', '.join(bad)})", flush=True)
            return {"skip": "privatnost", "ocijenjeno": n_eval}
        model, _est = store.pick(tcon, "trades", openai_api.MODEL, len(text) + len(prompts.SYSTEM), MAX_OUT, now, log)
        if model is None:
            return {"skip": "budžet", "ocijenjeno": n_eval}
        fn = call or openai_api.call_json
        try:
            res = fn(model, prompts.SYSTEM, text, prompts.TRADES_SCHEMA, "kriticar_pozicije", MAX_OUT, EFFORT)
        except openai_api.ApiError as e:
            c = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
            store.book(tcon, "trades", e.model or model, e.usage, c, False, str(e), text, now=now)
            store.kv_put(tcon, "trades_fail_ts", now)
            log(f"kritičar: poziv za pozicije nije uspio ({e}); sljedeći pokušaj za {FAIL_BACKOFF_S // 60} min",
                flush=True)
            return {"skip": "greška API-ja", "greska": str(e), "ocijenjeno": n_eval}
        ids = {row["pid"] for _it, row in pairs}
        try:
            verdicts, opce = validate(res["data"], ids)
        except ValueError as e:
            store.book(tcon, "trades", res["model"], res["usage"], res["cost_usd"], False, f"neispravan odgovor: {e}",
                       text, now=now)
            store.kv_put(tcon, "trades_fail_ts", now)
            log(f"kritičar: odgovor za pozicije neispravan ({e}), trošak {res['cost_usd']:.4f} $", flush=True)
            return {"skip": "neispravan odgovor", "greska": str(e), "ocijenjeno": n_eval}
        call_id = store.book(tcon, "trades", res["model"], res["usage"], res["cost_usd"], True, None, text,
                             n=len(verdicts), now=now)
        rows = {row["pid"]: row for _it, row in pairs}
        counts = {}
        for v in verdicts:
            pos = rows[v["id"]]
            nid = cnotes.store_review(tcon, pos, v, res["model"], call_id, now, log)
            store.add_verdict(tcon, call_id, nid, pos, v, now)
            counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        if opce:
            store.kv_put(tcon, "trades_opce", {"ts": now, "text": opce})
        tcon.commit()
        words = ", ".join(f"{cnotes.WORDS.get(k, k)} {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        log(f"kritičar: {len(verdicts)} pozicija ({why}), presude {words}, trošak {res['cost_usd']:.4f} $ "
            f"({res['usage'].get('in')} ulaz / {res['usage'].get('out')} izlaz tokena, {res['model']})", flush=True)
        return {"pozicija": len(verdicts), "presude": counts, "cost_usd": res["cost_usd"], "ocijenjeno": n_eval,
                "call_id": call_id}
    finally:
        if own:
            tcon.close()
