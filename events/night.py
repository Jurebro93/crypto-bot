"""The night batch (11.11., Jure, point 2): at 03:00 Zagreb, once a night, inside the heavy-job window.

By day nothing here recomputes: the 5-min tick only APPENDS (events/sources.sync, a watermark per source). At night,
one pass under the heavy-job lock (start.sh: python3 -m ops.heavy --night run_events.py night, tried every 30 min;
it runs when it is 03:00 or later in Zagreb, still inside ops/heavy.NIGHT, and the batch has not run for this date):

  sync         catch up what the day's ticks left (a long outage)
  backfill     once: the last 14 days of the old tables (estimate printed first, events/sources.backfill)
  outcomes     call / wallet-buy outcomes since the watermark kv 'wm:outcomes' (events/outcomes.compute)
  remeasure    never-measured and bad:svijeca calls from GeckoTerminal minute candles (events/remeasure, at most
               600 requests a night and never past half of the CoinGecko day)
  scores       callers, channels, wallets from the measured outcomes (n_measured shown)
  groups       caller and wallet groups: kol/groupdisc.night (its own pass, not a copy); when its own start.sh loop
               already ran tonight it is not run again and its credits count against this night's Helius cap
  ranges       rangedca: the backtest over the data we have (rangedca/backtest.run_server), unless today's report is
               already written by run_range.py's own nightly loop; only while the flag range_dca is not off
  early        early / discovered wallets (events/outcomes.early_wallets + kol/insiders; EXTRA_EARLY for more)
  solfill      sale amounts that wallets/solfill wrote into chain_trades after the event was logged
  predictions  Grok's predictions the day's candles could not score, from GeckoTerminal minute candles inside the
               remeasure step's night cap (events/predictions.night)
  retention    price ticks 30 d (thinned after 3 d), the rest 90 d, the disk budget; one size line a day

11.11. (Jure: health.last_night was null): kv night_start {ts, day} when a full batch starts; the report holds
started_ts, finished_ts, s (duration), calls_processed, helius_credits and errors. The 5-min tick raises an alert
(usage.db alerts + kv night_alert, shown by get_hourly_brief) when the batch has not finished by 04:30 Zagreb.

Helius: at most HELIUS_NIGHT_CAP (5000) credits for the whole night run, counted from usage.db (the calls are
metered where they are made, usage/meter via event_calendar/http) and from groupdisc's own run log; only the groups
step uses Helius, with min(its own cap, what is left). Every step has its own try: one broken step costs only itself.
State: events.db kv night_day (the Zagreb date done), night_report (what each step did, for the brief and the log).
"""
import datetime as dt
import json
import os
import time
from zoneinfo import ZoneInfo

from events import health, outcomes, remeasure, sources, store

HOUR = int(store._env_num("EVENTS_NIGHT_HOUR", 3))
HELIUS_NIGHT_CAP = int(store._env_num("EVENTS_HELIUS_NIGHT_CAP", 5000))
GROUPS_CREDITS = int(store._env_num("GROUPS_NIGHT_CREDITS", 3000))
TZ = "Europe/Zagreb"


def zagreb(now):
    return dt.datetime.fromtimestamp(now, ZoneInfo(TZ))


def due(econ, now=None):
    """(True, "") when the batch should run now, else (False, why)."""
    now = int(now or time.time())
    try:
        from ops import heavy
        inside = heavy.night_now(dt.datetime.fromtimestamp(now, dt.timezone.utc))
    except Exception:  # noqa: BLE001
        inside = 1 <= zagreb(now).hour < 6
    z = zagreb(now)
    if not inside:
        return False, "izvan noćnog prozora"
    if z.hour < HOUR:
        return False, f"čeka {HOUR:02d}:00 (Zagreb)"
    if store.kv_get(econ, "night_day") == z.date().isoformat():
        return False, "noćas je već odrađeno"
    return True, ""


def helius_used(since, usage_db=None):
    """Helius credits metered since `since` by this process's script and groupdisc (usage.db, per hour)."""
    try:
        from usage import meter
        meter.flush()
        con = meter.connect(usage_db)
        try:
            r = con.execute("SELECT COALESCE(SUM(amount), 0) FROM usage WHERE service = 'helius' AND hour >= ? AND "
                            "script IN ('run_events.py', 'groupdisc.py')", (int(since) // 3600 * 3600,)).fetchone()
            return float(r[0] or 0)
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return 0.0


def _groups_spent_tonight(now):
    """Credits of a groupdisc night pass in the last 20 h (its own start.sh loop), from early.db group_runs."""
    con = sources._ro(sources.db_paths()["early"])
    if con is None:
        return 0, None
    try:
        r = con.execute("SELECT ts, credits FROM group_runs WHERE kind = 'night' AND ts >= ? ORDER BY ts DESC LIMIT 1",
                        (now - 20 * 3600,)).fetchone()
        return (int(r[1] or 0), int(r[0])) if r else (0, None)
    except Exception:  # noqa: BLE001
        return 0, None
    finally:
        con.close()


def step_groups(now, cap_left, log=print):
    spent, ran_at = _groups_spent_tonight(now)
    if ran_at:
        return {"ran": False, "why": f"već odrađeno u {zagreb(ran_at):%H:%M} (vlastita petlja)", "credits": spent}
    credits = max(0, min(GROUPS_CREDITS, int(cap_left)))
    from kol import groupdisc
    d = groupdisc.night(credits=credits, log=log)
    spent, _ = _groups_spent_tonight(now + 1)
    return {"ran": d is not None, "credits": spent, "cap": credits,
            "why": "" if d is not None else "zastavica isključena ili nedavno odrađeno"}


def step_ranges(now, log=print):
    try:
        from league import flags
        mode = flags.mode("range_dca")
    except Exception:  # noqa: BLE001
        mode = "off"
    if mode == "off":
        return {"ran": False, "why": "zastavica range_dca je isključena"}
    name = f"range-backtest-{time.strftime('%Y%m%d', time.gmtime(now))}"
    if os.path.exists(os.path.join(store.ROOT, "output", name + ".json")):
        return {"ran": False, "why": "današnji backtest već postoji (run_range.py backtest)"}
    from rangedca import backtest
    rep = backtest.run_server(now=now, days=14, gt=int(store._env_num("RANGE_BT_GT", 30)), log=log)
    return {"ran": True, "tokens": rep.get("tokens_simulated")}


def reconcile_sells(econ, now, days=2):
    """Sale amounts wallets/solfill wrote into chain_trades after the event was logged: events.sol_amount follows."""
    con = sources._ro(sources.db_paths()["hype"])
    if con is None:
        return 0
    try:
        rows = con.execute("SELECT sig, mint, sol FROM chain_trades WHERE ts >= ? AND side = 'sell' AND sol IS NOT NULL",
                           (now - days * 86400,)).fetchall()
    except Exception:  # noqa: BLE001
        return 0
    finally:
        con.close()
    n = 0
    for sig, mint, sol in rows:
        n += econ.execute("UPDATE events SET sol_amount = ? WHERE uid = ? AND sol_amount IS NULL",
                          (sol, store.uid(f"wallet|{sig}|{mint}"))).rowcount
    econ.commit()
    return n


def run(now=None, force=False, log=print, steps=None, econ=None):
    """The batch; returns the night report (None when not due)."""
    now = int(now or time.time())
    own = econ is None
    econ = econ or store.connect()
    try:
        ok, why = due(econ, now)
        if not ok and not force:
            log(f"događaji: noćna obrada preskočena ({why})")
            return None
        t0 = time.time()
        rep = {"ts": now, "steps": {}, "started_ts": int(t0), "day": zagreb(now).date().isoformat()}
        want = set(steps) if steps else None
        if not want:   # 11.11.: a start without an end by 04:30 is an alert (late_alert)
            store.kv_put(econ, "night_start", {"ts": int(t0), "day": rep["day"]})
            econ.commit()

        def do(name, fn):
            if want and name not in want:
                return
            s = time.time()
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001 - one broken step costs only itself
                res = {"error": f"{type(e).__name__}: {e}"}
                log(f"događaji: noćni korak {name} nije uspio ({res['error']})")
            rep["steps"][name] = {"s": round(time.time() - s, 1), "result": res}
            store.kv_put(econ, f"night:{name}", {"ts": now, "result": res})
            econ.commit()

        do("sync", lambda: sources.sync(econ, now, log))
        if not store.kv_get(econ, "backfill"):
            do("backfill", lambda: sources.backfill(now=now, econ=econ, log=log))
        do("outcomes", lambda: outcomes.compute(econ, now, log))
        do("remeasure", lambda: remeasure.run(econ, now, log=log, force=force))
        do("scores", lambda: outcomes.scores(econ, now, log=log))
        h0 = helius_used(t0)
        do("groups", lambda: step_groups(now, HELIUS_NIGHT_CAP - h0, log))
        do("ranges", lambda: step_ranges(now, log))
        do("early", lambda: outcomes.early_wallets(econ, now, log=log))
        do("solfill", lambda: reconcile_sells(econ, now))
        do("predictions", lambda: _predictions(econ, now, log))   # 11.11.: Grok's predictions, GeckoTerminal capped
        do("retention", lambda: store.retention(econ, now, log))
        do("size", lambda: store.log_size(econ, now, log))
        g = (rep["steps"].get("groups") or {}).get("result") or {}
        rep["helius_credits"] = max(helius_used(t0), float(g.get("credits") or 0) if isinstance(g, dict) else 0)
        rep["helius_cap"] = HELIUS_NIGHT_CAP
        rep["s"] = round(time.time() - t0, 1)
        rep["finished_ts"] = int(time.time())
        rep["calls_processed"] = calls_processed(rep)
        rep["errors"] = {k: v["result"]["error"] for k, v in rep["steps"].items()
                         if isinstance(v.get("result"), dict) and "error" in v["result"]}
        if not want:
            store.kv_put(econ, "night_day", zagreb(now).date().isoformat())
        store.kv_put(econ, "night_report", rep)
        econ.commit()
        log(f"događaji: noćna obrada gotova za {rep['s']:.0f} s; Helius {rep['helius_credits']:.0f}/{HELIUS_NIGHT_CAP} "
            "kredita; koraci: " + ", ".join(f"{k} {v['s']:.0f} s" + (" (greška)" if isinstance(v["result"], dict) and
                                                                     "error" in v["result"] else "")
                                            for k, v in rep["steps"].items()))
        return rep
    finally:
        if own:
            econ.close()


def _predictions(econ, now, log=print):
    from events import predictions
    return predictions.night(econ, now, log=log)


def calls_processed(rep):
    """{"outcomes", "remeasured", "total"}: call / wallet-buy outcomes written by the outcomes step and calls measured
    from GeckoTerminal candles by the remeasure step (0 for a step that did not run or failed)."""
    st = rep.get("steps") or {}
    o = (st.get("outcomes") or {}).get("result")
    r = (st.get("remeasure") or {}).get("result")
    n_o = sum(v for v in o.values() if isinstance(v, (int, float))) if isinstance(o, dict) and "error" not in o else 0
    n_r = int((r or {}).get("calls") or 0) if isinstance(r, dict) else 0
    return {"outcomes": int(n_o), "remeasured": n_r, "total": int(n_o) + n_r}


LATE = (4, 30)   # 11.11. (Jure): the night batch must be done by 04:30 Zagreb, else an alert


def late_alert(econ, now):
    """The alert when tonight's batch has not finished by 04:30 Zagreb (None otherwise): it started and did not end,
    or (once it has ever run) it did not start. Pure on events.db kv; the tick records it once a day."""
    z = zagreb(now)
    if (z.hour, z.minute) < LATE:
        return None
    day = z.date().isoformat()
    if store.kv_get(econ, "night_day") == day:
        return None
    start = store.kv_get(econ, "night_start") or {}
    if start.get("day") == day:
        why = f"počela je u {zagreb(start['ts']):%H:%M} i nije završila do {LATE[0]:02d}:{LATE[1]:02d}"
    elif store.kv_get(econ, "night_day"):
        why = f"nije ni počela do {LATE[0]:02d}:{LATE[1]:02d} (zadnja gotova {store.kv_get(econ, 'night_day')})"
    else:
        return None   # never ran yet (the first deploy by day): nothing to compare with
    return {"key": "events:night:late", "service": health.SERVICE, "level": "bad", "type": "night", "day": day,
            "ts": int(now), "title": f"Noćna obrada {day} {why}",
            "detail": "Noćna obrada (events/night.py) ide u 03:00 Zagreb pod zaključavanjem teških poslova "
                      "(ops.heavy --night, svakih 30 min do 06:00); vidi log 'događaji: noćn'."}


def _late_check(econ, now, log):
    a = late_alert(econ, now)
    if not a or (store.kv_get(econ, "night_alert") or {}).get("day") == a["day"]:
        return None
    store.kv_put(econ, "night_alert", a)
    econ.commit()
    health.record([a], now, log)
    return a


def tick(now=None, log=print):
    """The 5-min light job (run_sched.py "events"): append-only sync, the health check, the night batch's 04:30 check,
    Grok's predictions scored from the candles we have (no network), stale MCP requests."""
    now = int(now or time.time())
    econ = store.connect()
    out, al, late, scored, tidy = {}, [], None, 0, 0
    try:
        out = sources.sync(econ, now, log)
        al = health.check(econ, now, log)
        late = _late_check(econ, now, log)
        try:
            from events import predictions
            scored = predictions.score_due(econ, now, log=log)
        except Exception as e:  # noqa: BLE001 - scored at the next tick
            log(f"događaji: Grokova predviđanja nisu ocijenjena ({type(e).__name__}: {e})")
    finally:
        econ.close()
        # 11.11.: tidied even when the sync above failed (it used to sit after it, so a broken sync left them pending)
        try:
            from ui import mcpapi
            tidy = mcpapi.tidy_requests(now=now)
        except Exception as e:  # noqa: BLE001 - the requests are tidied at the next tick
            log(f"događaji: zahtjevi s Groka nisu pospremljeni ({type(e).__name__})")
    if out or al or tidy or late or scored:
        log("događaji: " + (", ".join(f"{k} +{v}" for k, v in out.items()) or "bez novih")
            + (f"; upozorenja {len(al)}" if al else "") + (f"; zahtjeva s Groka zastarjelo {tidy}" if tidy else "")
            + (f"; {late['title']}" if late else "") + (f"; ocijenjeno predviđanja {scored}" if scored else ""))
    return {"synced": out, "alerts": al, "tidied": tidy, "night_late": late, "predictions_scored": scored}


def report(econ=None):
    own = econ is None
    econ = econ or store.ro()
    if econ is None:
        return {}
    try:
        return store.kv_get(econ, "night_report") or {}
    finally:
        if own:
            econ.close()


def dumps(x):
    return json.dumps(x, ensure_ascii=False, indent=1, default=str)
