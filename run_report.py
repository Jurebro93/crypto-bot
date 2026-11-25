"""Daily morning report by e-mail. 16.11. (vlasnik: "Sada idemo s mid cap tokenima"): the midcap trading (demo and real
by rule, the rules' out-of-sample EV, the wallet, the caps), the market (BTC, the macro regime, the macro influencers,
the midcap universe), the research (Insajderi 2.0, holders / listing, the critic), yesterday's cost per source; the old
microcap sections only while the switch fokus_midcap is off; 19.11.: every Monday, and in the first report after a
deploy when none went out for 7 days, the weekly cost per source and what it brought (report/tjedni.py). Claude writes the interpretation (ANTHROPIC_API_KEY).

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

from report import ai, collect, dump, mail, render, tjedni  # noqa: E402

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


def build(use_ai=True, now=None, weekly=None):
    """weekly (19.11.): add the section "Tjedni trošak po izvoru" (report/tjedni.py); None = decide by tjedni.due."""
    now = now or time.time()
    data = collect.collect(now)
    if weekly is None:
        weekly = tjedni.due(now, load_state(), local_now(now).weekday())[0]
    if weekly:
        data["tjedni_trosak"] = tjedni.collect(now)
    interp, source = ai.interpret(data) if use_ai else (ai.fallback(data), "pravila")
    # 25.11. (vlasnik: the attachment opened from the Gmail app on Android shows „nov?anika", „stop ?20 %"): what
    # leaves the builder is plain ASCII, every other letter a numeric reference (č -> &#269;, − -> &#8722;), so
    # whatever a carrier does with the charset reads the same: the saved file (and so /izvjestaj/raw and any attachment
    # made from it), the REPORT-B64 dump, the e-mail. One place, so no way out can forget it; <meta charset="utf-8">
    # stays. The plain-text part of the e-mail (mail.plain) stays UTF-8 (it unescapes the references).
    html = mail.ascii_html(render.render(data, interp, source))
    day = local_now(now).strftime("%Y-%m-%d")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"report-{day}.html")
    with open(path, "w", encoding="ascii") as f:
        f.write(html)
    prune()
    return day, path, html, interp, source


def subject(day, interp):
    d = "{2}.{1}.".format(*day.split("-"))
    head = (interp.get("naslov") or "").strip()
    return f"Crypto bot {d}: {head}"[:150] if head else f"Crypto bot: jutarnji izvještaj {d}"


def send_today(use_ai=True, now=None):
    st = load_state()
    weekly, why = tjedni.due(now or time.time(), st, local_now(now).weekday())
    day, path, html, interp, source = build(use_ai, now, weekly=weekly)
    st["built"] = day
    st["source"] = source
    try:
        how = mail.send(subject(day, interp), html)
        st.update(sent=day, sent_ts=int(time.time()), error=None, how=how)
        # 19.11.: the weekly cost section and the deploy it was built under count only once the e-mail went out
        st["report_commit"] = tjedni.commit()
        if weekly and mail.ascii_html("Tjedni trošak po izvoru") in mail.ascii_html(html):   # built HTML is ASCII (25.11.)
            st.update(tjedni_ts=int(now or time.time()), tjedni_zasto=why)
        print(f"izvještaj {day} poslan ({how}) na {', '.join(mail.recipients())}")
    except Exception as e:
        st["error"] = f"{type(e).__name__}: {e}"
        print(f"izvještaj {day} spremljen ({path}), e-mail nije poslan: {st['error']}")
        dump.emit(day, html)    # the daily Claude routine sends it from the connected Gmail (report/dump.py)
    save_state(st)
    return st


# 16.11. (vlasnik, gleda jutarnji izvještaj: "Zašto izvještaj nije osvježen onda"): after the deploy of the midcap
# report, today's report is built and sent ONCE more when the loop starts, so the owner sees the new version today;
# then the normal schedule (REPORT_HOUR) continues (state "sent" = today: no second send today). Each key once, ever
# (output/report-state.json "once"). Before REPORT_HOUR nothing extra is sent: that morning's report is already the new
# version; the key is marked done all the same. One line in the log either way.
OWNER_ONCE = (("midcap_1611", "nova midcap verzija jutarnjeg izvještaja (vlasnik 16.11.)"),)


def owner_once(now=None, log=print, send=None):
    """Apply each OWNER_ONCE step once. Returns the keys that sent (or dumped) a report now."""
    sent = []
    for key, why in OWNER_ONCE:
        if key in (load_state().get("once") or {}):
            continue
        hour = int(os.environ.get("REPORT_HOUR", "7"))
        if local_now(now).hour < hour:
            text = (f"izvještaj: nalog vlasnika {key}: prije {hour}:00, ne šaljem posebno (redovni jutarnji izvještaj "
                    "već je nova verzija)")
        else:
            res = (send or send_today)(now=now) or {}
            how = res.get("how") if not res.get("error") else ("e-mail nije poslan (" + str(res["error"])[:120]
                                                               + "), HTML u logu za Gmail rutinu i na /izvjestaj")
            text = f"izvještaj: nalog vlasnika {key}: {why} poslana odmah nakon deploya ({how})"
            sent.append(key)
        st = load_state()   # send_today saved its own state: add the mark to that
        st.setdefault("once", {})[key] = int(time.time())
        save_state(st)
        log(text)
    return sent


def loop(every_min=5):
    hour = int(os.environ.get("REPORT_HOUR", "7"))
    tries = {}
    resent = []
    try:   # 16.11.: the owner's one-time resend after the deploy (OWNER_ONCE)
        resent = owner_once(log=lambda t: print(t, flush=True))
    except Exception as e:  # noqa: BLE001 - never stops the loop
        print(f"report nalog vlasnika: {type(e).__name__}: {e}", flush=True)
    try:  # after a restart: put today's already built, unsent report back into the log for the Gmail routine
        st, day = load_state(), local_now().strftime("%Y-%m-%d")
        p = os.path.join(OUT, f"report-{day}.html")
        if not resent and st.get("sent") != day and os.path.exists(p):
            with open(p, encoding="utf-8") as f:   # a file from before 25.11. may be UTF-8; dump makes it ASCII
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
