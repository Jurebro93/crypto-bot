"""The daily proposals report, 23:30 Zagreb, hooked into events/evreport (run_sched "evreport": the EV report per
feature phase calls ev_rows for the flag proposals while it is not off).

Per strategy, over the Zagreb day: proposals made, bought (Kupi), rejected, expired, hit rate (TP before SL within 4 h
of the proposal, outcomes.py), EV per proposal (the measured 4 h result of a trade on its exit after cost), the paper
proof of the demo account (proposals/paper.py: closed trades, hit = ret > 0, EV) and the reasons the owner gave.
The day's biggest risers we did NOT propose (market cap >= $30k): the scanner's universe (scan.db cand: 24 h change)
and the momentum universe (momentum.db snapshots: the day's highest market cap over the lowest before it), and per
strategy whether it saw the token (proposed it), nearly did (seen: blocked or EV <= 0, with the reason; momentum also
a token it watched without a signal) or never saw it. Stored in proposals.db reports (get_proposals "report") and as
log lines.
"""
import datetime as dt
import json
import sqlite3
import time
from zoneinfo import ZoneInfo

from . import store, strategies

TZ = "Europe/Zagreb"
RISERS = 10
RISE_MIN_X = 1.5
MIN_MCAP = 30_000


def day_bounds(now):
    d = dt.datetime.fromtimestamp(int(now), ZoneInfo(TZ))
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return d.date().isoformat(), int(start.timestamp())


def _summ(ps):
    meas = [p for p in ps if ((p.get("after") or {}).get("4h") or {}).get("status") == "ok"]
    hits = sum(1 for p in meas if p["after"]["4h"]["first"] == "tp")
    rets = [p["after"]["4h"]["ret_pct"] for p in meas]
    return {"proposals": len(ps), "bought": sum(1 for p in ps if p["status"] == "kupljeno"),
            "rejected": sum(1 for p in ps if p["status"] == "odbijeno"),
            "expired": sum(1 for p in ps if p["status"] == "isteklo"), "measured": len(meas),
            "hit_rate": round(hits / len(meas), 3) if meas else None,
            "ev_pct": round(sum(rets) / len(rets), 2) if rets else None,
            "ev_expected_pct": round(sum(p.get("ev_pct") or 0 for p in ps) / len(ps), 2) if ps else None}


def risers(now, start, scan_con=None, mom_con=None):
    """[{"token", "symbol", "rise_x", "mcap", "from"}] of the day, mcap >= 30k, rise >= RISE_MIN_X, biggest first."""
    by = {}
    own_s = scan_con is None
    try:
        if scan_con is None:
            from scan import store as sstore
            scan_con = sstore.ro()
    except Exception:  # noqa: BLE001
        scan_con = None
    if scan_con is not None:
        try:
            for tok, sym, mc, ch in scan_con.execute("SELECT token, symbol, mcap, ch_h24 FROM cand WHERE last_seen >= ? AND "
                                                     "mcap >= ? AND ch_h24 IS NOT NULL", (int(start), MIN_MCAP)):
                x = 1 + float(ch) / 100
                if x >= RISE_MIN_X:
                    by[tok] = {"token": tok, "symbol": sym, "rise_x": round(x, 2), "mcap": mc, "from": "skener (24 h)"}
        except sqlite3.Error:
            pass
        finally:
            if own_s:
                scan_con.close()
    own_m = mom_con is None
    try:
        if mom_con is None:
            from momentum import data as mdata
            mom_con = mdata.ro()
    except Exception:  # noqa: BLE001
        mom_con = None
    if mom_con is not None:
        try:
            lo, best, last = {}, {}, {}
            for tok, mc in mom_con.execute("SELECT token, mcap FROM snaps WHERE ts >= ? AND ts <= ? AND mcap > 0 ORDER BY "
                                           "token, ts", (int(start), int(now))):
                lo[tok] = min(lo.get(tok, mc), mc)
                x = mc / lo[tok]
                if mc >= MIN_MCAP and x > best.get(tok, (0, 0))[0]:
                    best[tok] = (x, mc)
                last[tok] = mc
            for tok, (x, mc) in best.items():
                if x >= RISE_MIN_X and x > (by.get(tok) or {}).get("rise_x", 0):
                    by[tok] = {"token": tok, "symbol": (by.get(tok) or {}).get("symbol"), "rise_x": round(x, 2), "mcap": mc,
                               "from": "momentum svemir (dan)"}
        except sqlite3.Error:
            pass
        finally:
            if own_m:
                mom_con.close()
    return sorted(by.values(), key=lambda r: -r["rise_x"])[:RISERS * 3]


def _momentum_seen(tokens, start, mom_con=None):
    """({tokens with a momentum signal today}, {tokens momentum watched today})."""
    own = mom_con is None
    try:
        if mom_con is None:
            from momentum import data as mdata
            mom_con = mdata.ro()
    except Exception:  # noqa: BLE001
        mom_con = None
    if mom_con is None or not tokens:
        return set(), set()
    try:
        q = ",".join("?" * len(tokens))
        sig = {t for (t,) in mom_con.execute(f"SELECT DISTINCT token FROM signals WHERE ts >= ? AND token IN ({q})",
                                             (int(start), *tokens))}
        watched = {t for (t,) in mom_con.execute(f"SELECT DISTINCT token FROM snaps WHERE ts >= ? AND token IN ({q})",
                                                 (int(start), *tokens))}
        return sig, watched
    except sqlite3.Error:
        return set(), set()
    finally:
        if own:
            mom_con.close()


def missed(con, rs, day, start, mom_con=None):
    """The risers we did not propose, each with per strategy vidio / skoro / nikad."""
    toks = [r["token"] for r in rs]
    if not toks:
        return []
    q = ",".join("?" * len(toks))
    proposed = {t for (t,) in con.execute(f"SELECT DISTINCT token FROM proposals WHERE created_ts >= ? AND token IN ({q})",
                                          (int(start), *toks))}
    seen = {}
    for tok, k, prop, why, ev in con.execute(f"SELECT token, strategy, proposed, why, best_ev FROM seen WHERE day = ? AND "
                                             f"token IN ({q})", (day, *toks)):
        seen.setdefault(tok, {})[k] = (prop, why, ev)
    sig, watched = _momentum_seen(toks, start, mom_con)
    out = []
    for r in rs:
        s = seen.get(r["token"]) or {}
        if r["token"] in proposed or any(v[0] for v in s.values()):
            continue   # we proposed it: not a missed riser
        per = {}
        for k in strategies.STRATEGIES:
            if k in s:
                per[k] = "skoro: " + (s[k][1] or f"EV {s[k][2]}")
            elif k == "momentum" and r["token"] in sig:
                per[k] = "vidio: momentum signal (nije prošao u prijedlog)"
            elif k == "momentum" and r["token"] in watched:
                per[k] = "skoro: praćen u momentum svemiru, bez signala"
            else:
                per[k] = "nikad"
        out.append({**r, "strategies": per})
        if len(out) >= RISERS:
            break
    return out


def daily(now=None, path=None, lcon=None, scan_con=None, mom_con=None):
    """The day's report dict (and stored in proposals.db reports)."""
    now = int(now or time.time())
    day, start = day_bounds(now)
    con = store.connect(path)
    try:
        ps = store.read(con, "created_ts >= ?", (start,), order="id", limit=10_000)
        per = {k: _summ([p for p in ps if k in (p.get("sources") or [])]) for k in strategies.STRATEGIES}
        reasons = {}
        for p in ps:
            if p["status"] == "odbijeno":
                reasons[p.get("reject_reason") or "drugo"] = reasons.get(p.get("reject_reason") or "drugo", 0) + 1
        try:
            from . import paper
            proof = paper.proof(lcon)
        except Exception:  # noqa: BLE001
            proof = {}
        rs = risers(now, start, scan_con, mom_con)
        rep = {"day": day, "ts": now, "all": _summ(ps), "per_strategy": per, "paper": proof,
               "reject_reasons": reasons, "missed_risers": missed(con, rs, day, start, mom_con),
               "how": ("hit = TP prije SL-a u 4 h od prijedloga; EV = izmjereni rezultat trejda po izlazu prijedloga "
                       "nakon troška (TP -> +TP, SL -> -SL, ništa -> zatvaranje); paper = demo račun (ret > 0)")}
        con.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (day, now, json.dumps(rep, ensure_ascii=False)))
        con.commit()
        return rep
    finally:
        con.close()


def latest(path=None):
    con = store.ro(path)
    if con is None:
        return None
    try:
        r = con.execute("SELECT data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
        return json.loads(r[0]) if r else None
    except (sqlite3.Error, ValueError):
        return None
    finally:
        con.close()


def lines(rep):
    """Croatian log lines of the report."""
    if not rep:
        return []

    def pct(x):
        return f"{x:.0%}" if x is not None else "-"

    def ev(x):
        return f"{x:+.2f} %" if x is not None else "-"
    a = rep["all"]
    out = [f"Prijedlozi {rep['day']}: {a['proposals']} prijedloga, kupljeno {a['bought']}, odbijeno {a['rejected']}, "
           f"isteklo {a['expired']}; izmjereno {a['measured']}, pogodak (TP prije SL u 4 h) {pct(a['hit_rate'])}, "
           f"EV {ev(a['ev_pct'])} (očekivani {ev(a['ev_expected_pct'])})."]
    for k, s in rep["per_strategy"].items():
        if s["proposals"]:
            pp = (rep.get("paper") or {}).get(k) or {}
            out.append(f"  {strategies.HR.get(k, k)}: {s['proposals']} prijedloga, kupljeno {s['bought']}, pogodak "
                       f"{pct(s['hit_rate'])} (n={s['measured']}), EV {ev(s['ev_pct'])}; paper {pp.get('n', 0)} "
                       f"zatvorenih, EV {ev(pp.get('ev_pct'))}.")
    if rep.get("reject_reasons"):
        out.append("  Odbijeno zbog: " + ", ".join(f"{k} {v}" for k, v in rep["reject_reasons"].items()) + ".")
    for m in (rep.get("missed_risers") or [])[:5]:
        saw = "; ".join(f"{strategies.HR.get(k, k)} {v}" for k, v in m["strategies"].items() if v != "nikad") or \
            "nijedna strategija ga nije vidjela"
        out.append(f"  Propušten rast: {m.get('symbol') or m['token'][:6]} {m['rise_x']:.1f}x (MC ${m.get('mcap') or 0:,.0f}, "
                   f"{m['from']}): {saw}.")
    return out


def ev_rows(now, mode, path=None, log=print):
    """events/evreport: build the day's report, log it, and return one ev_report row per strategy with proposals."""
    rep = daily(now, path)
    for ln in lines(rep):
        log(ln)
    rows = []
    for k, s in rep["per_strategy"].items():
        if not s["proposals"]:
            continue
        pp = (rep.get("paper") or {}).get(k) or {}
        rows.append({"flag": "proposals", "phase": mode, "part": f"prijedlozi:{k}", "n": s["proposals"],
                     "n_outcomes": s["measured"], "hit_rate": s["hit_rate"], "avg_pnl_pct": s["ev_pct"],
                     "ev_pct": s["ev_pct"], "max_dd_pct": None, "baseline_ev_pct": s["ev_expected_pct"],
                     "baseline_n": None, "delta_ev_pct": (round(s["ev_pct"] - s["ev_expected_pct"], 2)
                                                          if s["ev_pct"] is not None and s["ev_expected_pct"] is not None
                                                          else None),
                     "note": (f"kupljeno {s['bought']}, odbijeno {s['rejected']}, isteklo {s['expired']}; paper "
                              f"{pp.get('n', 0)} zatvorenih (EV {pp.get('ev_pct')}); osnovica = očekivani EV prijedloga"),
                     "proposal": None})
    return rows
