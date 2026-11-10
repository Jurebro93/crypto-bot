"""One small scheduler for the loops that work only now and then (learning, exits, market volume, spend, correlations).

Before, each of them was its own Python process sleeping 24/7: ~18 MB each just to exist, and after its first
daily fit a process kept the fit's memory for good (Python does not hand it back). Here every run is a short
process that ends and gives its memory back; this process only keeps the clock. Same commands, same times:

  learn   run_learn.py fit      once a day after learn/config.json run_at_utc (UTC), checked every 5 min
  learn6  run_learn.py fit --samo-tezine  hype weights every learn/config.json every_h hours (default 6)
  exits   run_exits.py fit      once a day after exits/config.json run_at_utc (UTC), checked every 5 min
  exits_rb run_exits.py rollback every exits/config.json rollback_every_h hours: a losing exit profile goes back fast
  market  run_market.py collect every MARKET_EVERY_MIN minutes (default 60); light (no heavy lock, 9.11.)
  usage   run_usage.py tick     every USAGE_EVERY_MIN minutes (default 15); light (no heavy lock, 9.11.)
  corr    run_corr.py run       every CORR_EVERY_MIN minutes (default 60)
  postai  run_learn.py postai   every POSTAI_EVERY_MIN minutes (default 30): AI labels of KOL/TG posts (learn/postai.py)
  shadow  run_learn.py shadow   every SHADOW_EVERY_MIN minutes (default 60): shadow book points + labels (learn/shadow.py)
  whatsapp run_whatsapp.py due  daily digest to the WhatsApp group at WHATSAPP_HOUR, only with WHATSAPP_* set
  web     run_web.py daily      once a day at 02:00 Zagreb time (WEB_DAILY_HOUR): public tables fresh + site log row; light
"""
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(name, args, light=False):
    from ops import heavy   # one heavy job at a time (2.11.: overlapping jobs ran the 512 MB server out of memory)
    cmd = [sys.executable, os.path.join(ROOT, args[0]), *args[1:]]
    # 7.11. 10:45: a "light" job waits on an API (masovno: 500 GeckoTerminal calls at 30/min = 17 min), uses little
    # memory and would otherwise hold the lock most of the time: the token status, shadow, collect and the learning
    # fit all queued behind it for 12+ min after every deploy. Light jobs run without the lock.
    code = (subprocess.run(cmd, cwd=ROOT) if light else heavy.run(cmd, cwd=ROOT)).returncode
    if code:
        print(f"{name}: izlaz {code}", file=sys.stderr, flush=True)
    return code


LIGHT_START_DELAY_S = float(os.environ.get("SCHED_LIGHT_DELAY_S", "180"))


def night_ok(night):
    """9.11. (Jure: heavy jobs after midnight only): a job marked night runs only inside ops/heavy.NIGHT (Zagreb)."""
    if not night:
        return True
    from ops import heavy
    return heavy.night_now()


def every(name, args, minutes, light=False, night=False):
    # 7.11. 16:13: a light job starts the moment the scheduler does, i.e. in the middle of start.sh's database
    # maintenance (WAL, pruning: 67 s with hype.db write-locked); the token status died on "database is locked".
    # Light jobs now wait LIGHT_START_DELAY_S first.
    if light:
        time.sleep(LIGHT_START_DELAY_S)
    while True:
        if night_ok(night):
            run(name, args, light=light)
            time.sleep(minutes * 60)
        else:
            time.sleep(300)   # outside the night window: look again in 5 min


STATE = os.path.join(os.environ.get("DATA_DIR") or ROOT, "sched_state.json")


def _last_day(name):
    try:
        with open(STATE) as f:
            return json.load(f).get(name)
    except (OSError, ValueError):
        return None


def _set_last_day(name, day):
    try:
        try:
            with open(STATE) as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        state[name] = day
        with open(STATE + ".tmp", "w") as f:
            json.dump(state, f)
        os.replace(STATE + ".tmp", STATE)
    except OSError as e:
        print(f"{name}: stanje rasporeda nije spremljeno: {e}", file=sys.stderr, flush=True)


def daily(name, args, config, due=None):
    """After run_at_utc, once per UTC day. The day of the last run is kept on the disk (sched_state.json), so a
    restart does not run it again: before 1.11. every deploy (10+ a day) re-ran the daily learning, ~50 empty runs.
    due(): an extra reason to run now (at most once per process start), e.g. exit rules fitted under old mechanics."""
    last_day, forced = _last_day(name), False
    while True:
        try:
            with open(os.path.join(ROOT, config)) as f:
                hh, mm = map(int, json.load(f)["run_at_utc"].split(":"))
            now = dt.datetime.now(dt.timezone.utc)
            if not forced and due and due():
                forced = True
                print(f"{name}: pokrećem odmah ({due.__doc__ or 'potrebno'})", flush=True)
                run(name, args)
            elif (now.hour, now.minute) >= (hh, mm) and last_day != now.date().isoformat():
                run(name, args)
                last_day = now.date().isoformat()
                _set_last_day(name, last_day)
                if name == "learn":  # the daily fit also re-fits the weights: the 6-hourly one need not repeat it now
                    _set_last_day("learn6", time.time())
        except Exception as e:  # noqa: BLE001 - the scheduler must not die (start.sh restarts everything)
            print(f"{name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(300)


def _env_hour(name, default):
    """An hour 0-23 from the environment; a typo falls back to the default instead of stopping this whole process
    (it holds the clock of every job above, not only the one the variable is for)."""
    try:
        h = int(os.environ.get(name, default))
        return h if 0 <= h <= 23 else default
    except ValueError:
        return default


WEB_TZ = "Europe/Zagreb"
WEB_HOUR = _env_hour("WEB_DAILY_HOUR", 2)
LOCAL_RETRY_S, LOCAL_TRIES = 1800, 3


def local_due(hour, last_day, now=None, tz=WEB_TZ):
    """The local date (ISO) a once-a-day job is due for right now, or None: it is `hour`:00 or later in `tz` and the
    job has not run for that local date yet. Local time, not UTC (10.11., Jure: "zadatak u 2 po noći"): 02:00 in
    Zagreb is 01:00 UTC in winter and 00:00 UTC in summer. The night the clocks go back, 02:00 comes twice and the
    date keeps it to one run; the night they go forward there is no 02:00 and the job runs at 03:00."""
    from zoneinfo import ZoneInfo
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(tz))
    day = local.date().isoformat()
    return day if local.hour >= hour and last_day != day else None


def daily_local(name, args, hour, light=True):
    """Once per Zagreb day, at `hour`:00 or at the first check after it (a restart in the morning catches up), the
    day kept on the disk like daily(). 10.11.: the web refresh (run_web.py daily) only re-reads our own databases for
    a few seconds, so it runs light: under the heavy lock it would queue behind the night's long jobs (KOL history,
    the fits) and "02:00" would mean 05:00. A failed run is tried again LOCAL_RETRY_S later, LOCAL_TRIES times a day
    at most, then the day is given up with one line."""
    if light:
        time.sleep(LIGHT_START_DELAY_S)   # not in the middle of start.sh's database maintenance (see every())
    last_day, tries, tries_day = _last_day(name), 0, None
    while True:
        wait = 300
        try:
            day = local_due(hour, last_day)
            if day:
                if day != tries_day:   # failures count per day: two late failures must not cost the next night
                    tries, tries_day = 0, day
                ok = run(name, args, light=light) == 0
                tries = 0 if ok else tries + 1
                if ok or tries >= LOCAL_TRIES:
                    if not ok:
                        print(f"{name}: {LOCAL_TRIES} neuspjela pokušaja, sljedeći put sutra", file=sys.stderr, flush=True)
                    last_day, tries = day, 0
                    _set_last_day(name, day)
                else:
                    wait = LOCAL_RETRY_S
        except Exception as e:  # noqa: BLE001 - the scheduler must not die
            print(f"{name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(wait)


def every_hours(name, args, config, key="every_h", night=False):
    """Every config `key` hours, the last run's time kept on the disk like daily(), so 10+ deploys a day do not
    re-run it each time. night (9.11.): due or not, it waits for the night window (ops/heavy.NIGHT)."""
    while True:
        try:
            with open(os.path.join(ROOT, config)) as f:
                hours = float(json.load(f).get(key) or 0)
            last = _last_day(name)
            if hours and night_ok(night) and (not isinstance(last, (int, float)) or time.time() - last >= hours * 3600):
                run(name, args)
                _set_last_day(name, time.time())
        except Exception as e:  # noqa: BLE001
            print(f"{name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(300)


def exits_refit():
    """pravila izlaza naučena su pod starom mehanikom izlaza"""
    # reads the small JSON itself: this process lives 24/7, so it does not import the learning code
    try:
        from paper import sim
        d = os.environ.get("LEARNED_DIR") or os.path.join(os.environ.get("DATA_DIR") or ROOT, "learned")
        with open(os.path.join(d, "exits.json")) as f:
            state = json.load(f)
        return bool(state.get("profiles")) and state.get("sim_version", 1) != sim.SIM_VERSION
    except Exception:  # noqa: BLE001 - no file yet / unreadable: nothing to re-fit
        return False


def whatsapp(name, args, minutes):
    """Checks the clock itself so nothing starts while WhatsApp sending is not set up (no process every 10 min)."""
    while True:
        try:
            if os.environ.get("WHATSAPP_PROVIDER") and os.environ.get("WHATSAPP_TOKEN"):
                hour = int(os.environ.get("WHATSAPP_HOUR", "19"))
                try:
                    from zoneinfo import ZoneInfo
                    now = dt.datetime.now(ZoneInfo("Europe/Zagreb"))
                except Exception:  # noqa: BLE001
                    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
                if now.hour >= hour and _last_day(name) != now.date().isoformat():
                    if run(name, args) == 0:
                        _set_last_day(name, now.date().isoformat())
        except Exception as e:  # noqa: BLE001
            print(f"{name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(minutes * 60)


# 9.11. 21:40 (Jure: "brave zakaži za iza ponoć"): everything that recomputes or learns (learn6, exits rollback,
# shadow, corr) runs only in the night window (ops/heavy.NIGHT, 01-06 Zagreb); the daily fits moved into it
# (learn/config.json run_at_utc 02:30, exits/config.json 03:30). By day only the light, fresh jobs run: market,
# usage, masovno (light, night-aware itself), postai (API-bound, light since 9.11.), token status.
JOBS = [
    ("learn", daily, (["run_learn.py", "fit"], "learn/config.json")),
    ("learn6", every_hours, (["run_learn.py", "fit", "--samo-tezine"], "learn/config.json", "every_h", True)),
    ("exits", daily, (["run_exits.py", "fit"], "exits/config.json", exits_refit)),
    ("exits_rb", every_hours, (["run_exits.py", "rollback"], "exits/config.json", "rollback_every_h", True)),
    # 9.11. (audit P63): market and usage are small HTTP reads (tens of MB) and were queued behind the KOL round for up
    # to 42 min, so the macro gate (market/makro.py, 3 h window) and the spend warnings aged by an hour: light, no lock
    ("market", every, (["run_market.py", "collect"], float(os.environ.get("MARKET_EVERY_MIN", "60")), True)),
    ("usage", every, (["run_usage.py", "tick"], float(os.environ.get("USAGE_EVERY_MIN", "15")), True)),
    ("whatsapp", whatsapp, (["run_whatsapp.py", "due"], 10)),
    ("shadow", every, (["run_learn.py", "shadow"], float(os.environ.get("SHADOW_EVERY_MIN", "60")), False, True)),
    # 5.11.: mass shadow book (learn/masovno.py): thousands of invisible trades a day; history at night 01-06 Zagreb
    ("masovno", every, (["run_learn.py", "masovno"], float(os.environ.get("MASOVNO_EVERY_MIN", "30")), True)),
    # 9.11.: AI labels wait on the Haiku API (little CPU, little memory) and were queued behind the KOL round: light
    ("postai", every, (["run_learn.py", "postai"], float(os.environ.get("POSTAI_EVERY_MIN", "30")), True)),
    ("corr", every, (["run_corr.py", "run"], float(os.environ.get("CORR_EVERY_MIN", "60")), False, True)),
    # 7.11.: token status (DexScreener pair still there? exact pair page, fresh mcap, GeckoTerminal fallback)
    # light too (11:00): 30 DexScreener calls + up to 120 GeckoTerminal lookups; behind the KOL round it waited 12+ min
    # and never ran all morning. GeckoTerminal 429s are a shared cross-process cooldown (event_calendar/http).
    ("tokenstatus", every, (["run_hype.py", "status"], float(os.environ.get("TOKENSTATUS_EVERY_MIN", "360")), True)),
    # 10.11. (Grok MCP audit 6): calls that were never measured (price 1 h / 24 h empty) measured at night, capped per
    # night by kol/backfill_calls.py itself (300 GeckoTerminal requests); heavy lock, night window only
    ("kolfill", every, (["kol/backfill_calls.py", "--budget", "60"], 60, False, True)),
    # 10.11. (Jure: "podaci bi se trebali jednom dnevno osvježiti na cijelom webu ... zadatak u 2 po noći"): public
    # tables rebuilt from our own databases, blog data blocks counted again, one row in the site log (run_web.py)
    ("web", daily_local, (["run_web.py", "daily"], WEB_HOUR)),
]


def main():
    try:   # 10.11. (Jure): errors go to Sentry (ops/sentry.py); a no-op without SENTRY_DSN, never stops the start
        from ops import sentry
        sentry.init("sched")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    for name, fn, args in JOBS:
        threading.Thread(target=fn, args=(name, *args), name=name, daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
