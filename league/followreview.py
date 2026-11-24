"""Pregled praćenja (10.11., Jure: "isključi influencere koje sam ja stavio da autopilot prati ako nema smisla da ih
se prati"; on the question he chose "Isključi ih sam"): once an hour the owner's OWN influencer and crew follows of
the Autopilot account are judged on their measured calls (minute.db through kol/tpsl), and a follow that clearly does
not pay is paused (follows.active = 0), with the reason, listed on /pravi-trade under "Pregled influencera" with
"Vrati". A follow the owner brings back is never paused by this again (settings review_keep).

Who is judged: active follows of settings.LEAGUE_USER of kind kol / ekipa that are NOT tool picks (settings
auto_follows; the auto pick drops its own picks itself). Wallet follows are judged elsewhere (wallets/dokazani).

"Clearly does not pay" = ALL of these, so a thin or mixed record is never a reason:
  - at least MIN_N measured calls (one per token, the first) in tpsl.DAYS days; for a crew, the calls its entry
    rule would have entered on (tpsl.crew_rows with its min_callers);
  - its own exit (the follow's TP and stop in percent, the owner's default stop when none is set, the nearest pair
    the grid measures) loses after cost on those calls: mean result per trade < 0;
  - no TP/SL pair is proven on them either (kol/tpsl.decide ok is not True), so no other exit would rescue it;
  - its demo copies, once DEMO_MIN or more are closed, are not in the plus.
A follow with an exit in market cap ($100k) has no percent pair: only the last three rules apply to it.

Nothing here buys or sells: pausing a follow only stops NEW entries; open positions keep their exits.
"""
import json
import os
import sqlite3
import time

MIN_N = 10
DEMO_MIN = 3
EVERY_S = 3600
LOG_N = 50
_LAST = {"ts": 0.0}


def _pct(text):
    """"15%" -> 15.0, "-60%" -> 60.0; None for empty, a market-cap level or anything else."""
    t = (text or "").strip().replace(",", ".").replace("−", "-")
    if not t.endswith("%"):
        return None
    try:
        return abs(float(t[:-1]))
    except ValueError:
        return None


def _nearest(v, choices):
    return min(choices, key=lambda c: (abs(c - v), c))


def judge(f, rws, pool=None, demo=None, sl_default=60.0, tp_default=15.0):
    """Verdict for one follow from its measured calls rws (kol/tpsl rows, already crew-filtered).
    Returns {"pause": bool, "why": Croatian sentence, "n", "ev_own", "pair", "best"}."""
    from kol import tpsl
    n = len(rws)
    out = {"pause": False, "n": n, "ev_own": None, "pair": None, "best": None}
    if n < MIN_N:
        out["why"] = f"premalo izmjerenih poziva ({n} od {MIN_N}), ostaje"
        return out
    ex = f.get("exit") or {}
    tp, sl = _pct(ex.get("tp")), _pct(ex.get("sl"))
    mode = ex.get("mode") or "smart"
    if mode == "tpsl" and (tp is not None or not (ex.get("tp") or "").strip()):
        tp = tp if tp is not None else float(tp_default)
        sl = sl if sl is not None else float(sl_default)
        pair = (_nearest(tp, tpsl.TPS), _nearest(sl, tpsl.SLS))
        out["pair"] = pair
        out["ev_own"] = tpsl.grid(rws, tps=(pair[0],), sls=(pair[1],))[pair]["ev"]
    d = tpsl.decide(rws, pool)
    out["best"] = {k: d.get(k) for k in ("ok", "tp", "sl", "ev", "lo") if k in d}
    if out["ev_own"] is not None and out["ev_own"] >= 0:
        out["why"] = f"njegov izlaz TP +{out['pair'][0]} % / SL −{out['pair'][1]} % je u plusu ({out['ev_own']:+.1f} % po tradeu), ostaje"
        return out
    if d.get("ok") is True:
        out["why"] = f"po podacima postoji izlaz koji se isplati ({d.get('base') or ''}), ostaje"
        return out
    if demo and demo.get("closed", 0) >= DEMO_MIN and demo.get("pnl", 0) > 0:
        out["why"] = f"u demu je u plusu ({demo['pnl']:+.0f} $ na {demo['closed']} zatvorenih), ostaje"
        return out
    own = (f"njegov izlaz TP +{out['pair'][0]} % / SL −{out['pair'][1]} % gubi {out['ev_own']:+.1f} % po tradeu; "
           if out["ev_own"] is not None else "")
    demo_txt = (f"; u demu {demo['pnl']:+.0f} $ na {demo['closed']} zatvorenih" if demo and demo.get("closed") else "")
    out["pause"] = True
    out["why"] = (f"na {n} izmjerenih poziva {own}nijedan TP/SL par se ne isplati nakon troška"
                  f" (najbolji {d.get('base') or 'nije dokazan'}){demo_txt}")
    return out


def _mcon(path=None):
    from kol import minute
    p = path or minute.db_path()
    if not os.path.exists(p) or not os.path.getsize(p):
        return None
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def review(lcon, tcon, now=None, mcon=None, apply=True):
    """Judge every owner follow; pause the ones that clearly do not pay (apply=True). Returns [(follow, verdict)]."""
    from kol import tpsl
    from league import copy
    from trade import settings
    now = int(now or time.time())
    raw = settings.raw(tcon)
    auto_ids = {int(i) for i in raw.get("auto_follows") or []}
    keep = {int(i) for i in raw.get("review_keep") or []}
    sl0 = _pct(settings.sl_text(raw.get("sl_default") or settings.SL_DEFAULT)) or 60.0
    own_m = mcon is None
    mcon = mcon or _mcon()
    if mcon is None:
        return []
    try:
        pool = tpsl.load_pool(mcon).get("pairs")
        res = copy.follow_results(lcon)
        out, log = [], list(raw.get("review_log") or [])
        for f in copy.follows(lcon, settings.LEAGUE_USER):
            if f["kind"] not in ("kol", "ekipa") or f["id"] in auto_ids:
                continue
            hs = copy.members_of(f["target"]) if f["kind"] == "ekipa" else [f["target"]]
            rws = tpsl.rows(mcon, hs, tpsl.DAYS, now)
            k = int((f.get("exit") or {}).get("min_callers") or 1)
            if len(hs) > 1 or k > 1:
                rws = tpsl.crew_rows(rws, max(1, min(k, len(hs))), copy.CFG["crew_window_min"] * 60)
            v = judge(f, rws, pool, res.get(f["id"]), sl0, float(raw.get("tp_default") or 15))
            out.append((f, v))
            if apply and v["pause"] and f["id"] not in keep:
                try:
                    copy.unfollow(lcon, settings.LEAGUE_USER, f["id"])
                except ValueError:
                    continue
                log.insert(0, {"ts": now, "fid": f["id"], "kind": f["kind"], "target": f["target"],
                               "label": f.get("label") or f["target"], "why": v["why"], "n": v["n"],
                               "ev_own": v["ev_own"], "back": False})
                print(f"pregled influencera: isključen {f['kind']} {f.get('label') or f['target']}: {v['why']}",
                      flush=True)
        if apply:
            settings.put(tcon, "review_log", log[:LOG_N], "alat")
            settings.put(tcon, "review_last", {"ts": now, "judged": len(out),
                                               "paused": sum(1 for _, v in out if v["pause"])}, "alat")
        return out
    finally:
        if own_m:
            mcon.close()


def restore(lcon, tcon, fid, user):
    """The owner's "Vrati": the follow is active again (same id, so its log and demo results stay together) and
    is never paused by the review again."""
    from trade import settings
    raw = settings.raw(tcon)
    log = list(raw.get("review_log") or [])
    row = next((x for x in log if x.get("fid") == fid and not x.get("back")), None)
    if row is None:
        raise ValueError("to praćenje nije isključio pregled")
    n = lcon.execute("UPDATE follows SET active=1, stopped=NULL WHERE id=? AND user=? AND active=0",
                     (fid, settings.LEAGUE_USER)).rowcount
    lcon.commit()
    if not n:
        raise ValueError("to praćenje više ne postoji")
    row["back"] = int(time.time())
    keep = sorted({int(i) for i in raw.get("review_keep") or []} | {int(fid)})
    settings.put(tcon, "review_log", log, user)
    settings.put(tcon, "review_keep", keep, user)
    return row


def maybe_review(now=None):
    """Once an hour from the UI process (ui/pravitrade.dca_loop). Never raises."""
    now = now or time.time()
    if now - _LAST["ts"] < EVERY_S:
        return None
    _LAST["ts"] = now
    from league import store
    from trade import settings
    lcon = tcon = None
    try:
        lcon, tcon = store.connect(), settings.connect()
        return review(lcon, tcon, now)
    except Exception as e:  # noqa: BLE001 - a review that fails waits for the next hour
        print(f"pregled influencera: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        for c in (lcon, tcon):
            if c is not None:
                c.close()


def summary_json(tcon):
    from trade import settings
    raw = settings.raw(tcon)
    return json.dumps({"last": raw.get("review_last"), "log": raw.get("review_log") or []}, ensure_ascii=False)
