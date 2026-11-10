"""Daily morning report by e-mail: what the bot learned, KOLs to follow, tokens for today's sessions, sustained
holder/volume growth, ideas for the algorithm. Claude writes the interpretation (ANTHROPIC_API_KEY).

    python3 run_report.py build             # build today's report -> output/report-YYYY-MM-DD.html, no e-mail
    python3 run_report.py send              # build and e-mail now (REPORT_EMAIL_TO + SMTP_* or RESEND_API_KEY)
    python3 run_report.py send --no-ai      # same, without the Claude call
    python3 run_report.py loop              # every day at REPORT_HOUR (default 7) Europe/Zagreb; catches up after a deploy
    python3 run_report.py status

Writes only output/report-*.html (keeps the last REPORT_KEEP, default 14, ~50 kB each) and output/report-state.json.
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import ai, collect, dump, mail, render  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
STATE = os.path.join(OUT, "report-state.json")


def local_now(now=None):
    now = now or time.time()
    try:
        from zoneinfo import ZoneInfo
        import datetime
        return datetime.datetime.fromtimestamp(now, ZoneInfo(os.environ.get("REPORT_TZ", "Europe/Zagreb")))
    except Exception:
        import datetime
        return datetime.datetime.utcfromtimestamp(now + 3600)


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(OUT, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE)


def report_files():
    return sorted(glob.glob(os.path.join(OUT, "report-????-??-??.html")))


def prune(keep=None):
    keep = keep or int(os.environ.get("REPORT_KEEP", "14"))
    for p in report_files()[:-keep]:
        try:
            os.remove(p)
        except OSError:
            pass


def build(use_ai=True, now=None):
    now = now or time.time()
    data = collect.collect(now)
    interp, source = ai.interpret(data) if use_ai else (ai.fallback(data), "pravila")
    html = render.render(data, interp, source)
    day = local_now(now).strftime("%Y-%m-%d")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"report-{day}.html")
    with open(path, "w") as f:
        f.write(html)
    prune()
    return day, path, html, interp, source


def subject(day, interp):
    d = "{2}.{1}.".format(*day.split("-"))
    head = (interp.get("naslov") or "").strip()
    return f"Crypto bot {d}: {head}"[:150] if head else f"Crypto bot: jutarnji izvještaj {d}"


def send_today(use_ai=True, now=None):
    st = load_state()
    day, path, html, interp, source = build(use_ai, now)
    st["built"] = day
    st["source"] = source
    try:
        how = mail.send(subject(day, interp), html)
        st.update(sent=day, sent_ts=int(time.time()), error=None, how=how)
        print(f"izvještaj {day} poslan ({how}) na {', '.join(mail.recipients())}")
    except Exception as e:
        st["error"] = f"{type(e).__name__}: {e}"
        print(f"izvještaj {day} spremljen ({path}), e-mail nije poslan: {st['error']}")
        dump.emit(day, html)    # the daily Claude routine sends it from the connected Gmail (report/dump.py)
    save_state(st)
    return st


def loop(every_min=5):
    hour = int(os.environ.get("REPORT_HOUR", "7"))
    tries = {}
    try:  # after a restart: put today's already built, unsent report back into the log for the Gmail routine
        st, day = load_state(), local_now().strftime("%Y-%m-%d")
        p = os.path.join(OUT, f"report-{day}.html")
        if st.get("sent") != day and os.path.exists(p):
            with open(p) as f:
                dump.emit(day, f.read())
    except Exception as e:
        print(f"report dump: {type(e).__name__}: {e}")
    while True:
        try:
            ln = local_now()
            day = ln.strftime("%Y-%m-%d")
            st = load_state()
            due = ln.hour >= hour and st.get("sent") != day
            # without e-mail settings: build once a day so /izvjestaj has it, re-check when settings appear (redeploy)
            if due and not mail.method() and st.get("built") == day:
                due = False
            n, last = tries.get(day, (0, 0))
            if due and n < 5 and time.time() - last > 1800:
                tries[day] = (n + 1, time.time())
                send_today()
        except Exception as e:  # the loop must not die (start.sh restarts the whole service)
            print(f"report loop: {type(e).__name__}: {e}")
        time.sleep(every_min * 60)


def main():
    try:   # 10.11. (Jure): errors go to Sentry (ops/sentry.py); a no-op without SENTRY_DSN, never stops the start
        from ops import sentry
        sentry.init("report")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "send", "loop", "status"])
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--every", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "build":
        day, path, _, _, source = build(not a.no_ai)
        print(f"{path} ({source})")
    elif a.cmd == "send":
        send_today(not a.no_ai)
    elif a.cmd == "loop":
        loop(a.every)
    else:
        print(json.dumps({"state": load_state(), "missing": mail.missing(), "files": report_files()[-3:]}, indent=1))


if __name__ == "__main__":
    main()
