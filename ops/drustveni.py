"""Društveni izvori jednom u 5 dana (19.11.2026., vlasnik: "From now on I want the tool to stop spending resources on
scraping influencers and Telegram channels. That can be refreshed once every 5 days. What I want every day is
wallets.").

ONE gate that every influencer / Telegram job asks before it spends anything (an API call, an AI call, CPU of note or
the heavy-job lock): social_open(now) is True only inside a refresh window.

  window   every SOCIAL_EVERY_D days (5) for SOCIAL_WINDOW_H hours (6). The first window starts at the first start
           after this deploy (start.sh runs "python3 -m ops.drustveni" once a start; any job asking first does the
           same), so the lists are fresh once; then every 5 days from that start.
  state    DATA_DIR/drustveni.json (the persistent disk, like run_sched's sched_state.json; survives deploys):
           {"prvi": the first window's start (unix s), "log": {job: UTC day of its last "closed" line}}. Written under
           an flock, so two processes asking at once agree on one start. SOCIAL_STATE overrides the path (tests).
           Without DATA_DIR and SOCIAL_STATE (a laptop, the offline tests) there is no persistent place: the gate is
           open, i.e. today's behaviour.
  always   SOCIAL_ALWAYS=1 restores today's behaviour (the gate is always open).

Outside the window a gated job does nothing that costs and says so in ONE line a day per job:
  "<job>: osvježavanje influencera i Telegrama je jednom u 5 dana; sljedeće 24.11.2026. 14:05 UTC"

Who asks (see JOBS for the command lines; tests/test_social_offline.py checks every one):
  ops/heavy.main, run_sched.run   skip_cmd(argv) before the lock / the child (like ops/fokus)
  runners started directly        gate_main() at the top of their __main__ (run_makroinf, run_konsenzus, ...)
  loops / parts of a job          gate(job) where the social part starts (run_kol round, minute loop,
                                  X momentum, the AI detective)

python3 -m ops.drustveni     the start line (and the first window's start, once)
"""
import datetime as dt
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINCE = "19.11.2026."          # the owner's order (the notice on the cards says it)
SINCE_EN = "19 Nov 2026"
DEFAULT_EVERY_D = 5.0
DEFAULT_WINDOW_H = 6.0

# (canonical script / module, first sub-command or None = any) -> (job key, what it does, what it cost a day before)
# The cost column is the job's own caps in the code and start.sh (Pretpostavka: caps, not a measured day).
JOBS = (
    (("run_kol", "search-round"), "kol_pretraga",
     "KOL timelineovi, otkrivanje, trending pretrage (twitterapi.io, Apify)", "twitterapi timeline_twapi strop + rezerva otkrivanja, svakih 20 min"),
    (("run_kol", "search"), "kol_pretraga", "isto, ručno", "isto"),
    (("run_kol", "live"), "kol_live", "xquik monitor KOL-ova (Apify)", "0,0045 $ po računu-satu"),
    (("run_kol", "snap"), "kol_snap", "DexScreener snimke pozvanih tokena", "besplatno, CPU"),
    (("run_kol", "measure"), "kol_mjerenje", "cijena nakon poziva (GeckoTerminal)", "GeckoTerminal besplatni limit"),
    (("run_kol", "score"), "kol_ocjena", "ocjene KOL-ova", "40+ min CPU noću pod teškom bravom"),
    (("run_kol", "converge"), "kol_konvergencija", "konvergencija izvora", "CPU"),
    (("run_kol", "backfill"), "kol_backfill", "povijest poziva (Apify, plaćeno)", "samo uz KOL_BACKFILL_USD"),
    (("kol.backfill_calls", None), "kolfill", "nemjereni pozivi noću", "GeckoTerminal 300/noć"),
    (("run_learn", "postai"), "postai", "AI oznake objava KOL/TG (Claude Haiku)", "svakih 30 min, Anthropic API"),
    (("kol.zadnjih5", None), "zadnjih5", "walk-forward zadnjih 5 poziva", "CPU pod teškom bravom nakon deploya i noću"),
    (("run_konsenzus", None), "konsenzus", "konsenzus izvora (walk-forward)", "20 min CPU nakon deploya i noću"),
    (("run_makroinf", "krug"), "makroinf", "makro influenceri (twitterapi, OpenAI)", "do 1,50 $ + 0,50 $ dnevno, krug svakih 10 min"),
    (("run_makroinf", "noc"), "makroinf", "makro influenceri: noćni izračun", "CPU pod teškom bravom noću"),
    (("run_makroinf", "provjera"), "makroinf", "makro influenceri: provjera uzoraka", "kritičar do 1 $"),
    (("run_makroinf", "prosiri"), "makroinf", "makro influenceri: proširenje", "twitterapi / OpenAI jednokratni stropovi"),
    (("run_veliki", "moc"), "moc", "moć poziva midcapova (X pretraga)", "strop 4 $ dnevno, ~2,50 $ po prolazu, svaka 3 h"),
)
# 19.11. kasnije (vlasnik: "Makni Telegram KOL-ove iz izračuna"): the Telegram reader, discovery, history, TGStat and
# Telethon are gone (not gated: removed); run_tg.py only counts followers once a week on its own cadence
# (tg/pratitelji.py, TG_FOLLOWERS_EVERY_D), outside this gate.
# parts of a job that keeps running (the gate is asked inside it): key -> what stops outside the window
PARTS = (
    ("kol_krug", "KOL krug: X webhook pravila (twitterapi), xquik monitor, snimke, konvergencija, ekipe, ocjene, "
                 "mjerenje, provjera obrisanih; ostaju novčanici (popis i Helius webhook /hook/chain), tokovi i tragovi"),
    ("kol_minute", "minutne svijeće nakon poziva (GeckoTerminal) i provjera tpsl; ostaju preskočene kupnje Autopilota"),
    ("brzo_obrisane", "provjera brzo obrisanih X objava svakih 30 s (twitterapi)"),
    ("xmom", "X momentum za midcapove i skener (twitterapi)"),
    ("detektiv", "AI detektiv (Claude Opus) u dnevnom učenju"),
)
KEPT = ("pozicije i izlazi (league/auto, planovi izlaza)", "pravi novac (run_trade)", "novčanici (run_wallets, "
        "run_holderi, Helius webhook /hook/chain, popis KOL novčanika)", "midcap svijeće i pravilo (run_veliki "
        "candles/once/night/replay/nauceno/midcap bez X dijela)", "vijeće (run_vijece)", "kritičar", "zdravlje i ops",
        "javna stranica")


# ---------- settings ---------------------------------------------------------------------------------------------------

def _env_float(name, default, lo):
    try:
        v = float(os.environ.get(name, default))
        return v if math.isfinite(v) and v >= lo else default
    except (TypeError, ValueError):
        return default


def every_d():
    return _env_float("SOCIAL_EVERY_D", DEFAULT_EVERY_D, 1 / 24)


def window_h():
    return _env_float("SOCIAL_WINDOW_H", DEFAULT_WINDOW_H, 0.0)


def always():
    return os.environ.get("SOCIAL_ALWAYS", "").strip() == "1"


def path():
    """The state file on the persistent disk, or None when there is none (then the gate is open)."""
    p = os.environ.get("SOCIAL_STATE")
    if p:
        return p
    d = os.environ.get("DATA_DIR")
    return os.path.join(d, "drustveni.json") if d else None


def days_word(d=None):
    """5 -> "5", 2.5 -> "2,5"."""
    d = every_d() if d is None else d
    return f"{d:g}".replace(".", ",")


# ---------- the state file ---------------------------------------------------------------------------------------------

def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _update(p, fn):
    """Read-modify-write under an flock (the scheduler's threads and a dozen processes share the file). Returns what
    fn returned; the state is written only when fn says so ((result, changed))."""
    import fcntl
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            st = _read(p)
            res, changed = fn(st)
            if changed:
                tmp = f"{p}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(st, f)
                os.replace(tmp, p)
            return res
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def first_start(now=None, create=True):
    """The first window's start (unix s); created at `now` when missing and create. None without a state file."""
    p = path()
    if not p:
        return None
    if not create:
        v = _read(p).get("prvi")
        return float(v) if isinstance(v, (int, float)) else None
    t = float(now if now is not None else time.time())

    def fn(st):
        if isinstance(st.get("prvi"), (int, float)):
            return float(st["prvi"]), False
        st["prvi"] = int(t)
        return float(int(t)), True
    try:
        return _update(p, fn)
    except OSError:
        v = _read(p).get("prvi")
        return float(v) if isinstance(v, (int, float)) else None


def state(now=None, create=False):
    """{"open", "mode", "last", "end", "next", "every_d", "window_h"}:
    mode  "always" (SOCIAL_ALWAYS=1), "nopersist" (no state file: open), "first" (no window has run yet: the first
          starts at the next start or the first job that asks), "open", "closed"
    last  the start of the newest window (unix s, None before the first); end = last + window; next = the next start."""
    t = float(now if now is not None else time.time())
    P, W = every_d() * 86400, window_h() * 3600
    out = {"open": True, "mode": "always", "last": None, "end": None, "next": None, "every_d": every_d(),
           "window_h": window_h()}
    a = first_start(t, create=create) if path() else None
    if a is not None:
        k = max(0, math.floor((t - a) / P))
        last = a + k * P
        out.update(last=int(last), end=int(last + W), next=int(last + P))
    if always():
        return out
    if not path():
        out["mode"] = "nopersist"
        return out
    if a is None:
        out["mode"] = "first"
        return out
    is_open = t < a or t < out["end"] or W >= P
    out.update(open=is_open, mode="open" if is_open else "closed")
    return out


def social_open(now=None):
    """True inside a refresh window (or with SOCIAL_ALWAYS=1, or without a persistent state file). The first call
    after a deploy that finds no state starts the first window."""
    return state(now, create=True)["open"]


def when(ts, en=False):
    """24.11.2026. 14:05 UTC / 24 Nov 2026 14:05 UTC."""
    if not ts:
        return ""
    d = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    if en:
        return f"{d.day} {d:%b %Y %H:%M} UTC"
    return f"{d:%d.%m.%Y. %H:%M} UTC"


def closed_line(job, st):
    return (f"{job}: osvježavanje influencera i Telegrama je jednom u {days_word(st.get('every_d'))} dana; sljedeće "
            f"{when(st.get('next')) or '?'}")


def _log_once(job, st, now, log):
    """The closed line at most once a UTC day per job (the day kept in the state file, so short processes that ask
    every 30 min say it once too)."""
    day = dt.datetime.fromtimestamp(float(now), dt.timezone.utc).date().isoformat()
    p = path()

    def fn(s):
        lg = s.get("log") if isinstance(s.get("log"), dict) else {}
        if lg.get(job) == day:
            return False, False
        lg[job] = day
        s["log"] = lg
        return True, True
    try:
        say = _update(p, fn) if p else True
    except OSError:
        say = True
    if say:
        if log is None or log is print:
            print(closed_line(job, st), flush=True)
        else:
            log(closed_line(job, st))
    return say


def gate(job, now=None, log=None):
    """True: the social part of `job` may run now. False (outside the window): one line a day, and the caller does
    nothing that costs. Never raises (an unreadable state = open, today's behaviour)."""
    try:
        t = float(now if now is not None else time.time())
        st = state(t, create=True)
        if st["open"]:
            return True
        _log_once(job, st, t, log)
        return False
    except Exception:  # noqa: BLE001
        return True


def job_of(argv):
    """The JOBS key of a command line, else None."""
    from ops import fokus
    mod, sub = fokus.canon(argv)
    for (m, s), key, _what, _cost in JOBS:
        if m == mod and (s is None or s == sub):
            return key
    return None


def skip_cmd(argv, now=None, log=None):
    """The job key when this command is a social job and the window is closed (its line said once a day), else None."""
    try:
        key = job_of(argv)
    except Exception:  # noqa: BLE001
        return None
    if key and not gate(key, now, log):
        return key
    return None


def gate_main(argv=None):
    """At the top of a runner's __main__: exit 0 at once outside the window when this is a social job."""
    if skip_cmd(sys.argv if argv is None else argv):
        sys.exit(0)


# ---------- the lines and the notice ----------------------------------------------------------------------------------

def line(now=None):
    """The start line / the part of the daily cost line."""
    st = state(now, create=False)
    m = st["mode"]
    if m == "always":
        return "društveni izvori: uvijek otvoreno (SOCIAL_ALWAYS=1)"
    if m == "nopersist":
        return "društveni izvori: otvoreno (nema trajnog stanja: DATA_DIR nije postavljen)"
    if m == "first":
        return "društveni izvori: prvo osvježavanje počinje pri ovom startu"
    if m == "open":
        return f"društveni izvori: prozor otvoren (do {when(st['end'])}, sljedeći {when(st['next'])})"
    return f"društveni izvori: prozor zatvoren (sljedeći {when(st['next'])})"


def notice_dates(now=None):
    """(last, next) for the cards: unix s or None (no window has run yet: "first refresh in progress")."""
    st = state(now, create=False)
    if st.get("last") is None:
        return None, None
    return st["last"], st["next"]


NOTICE = {
    "hr": ("Od {since} ovi se podaci osvježavaju jednom u {d} dana. Sve resurse usmjerili smo na pronalaženje "
           "profitabilnih novčanika, jer smatramo da je tu najveća poluga koju ovi podaci daju. "),
    "en": ("Since {since} this data is refreshed once every {d} days. All resources now go to finding profitable "
           "wallets, because we believe that is where this data gives the most leverage. "),
}
NOTICE_DATES = {"hr": "Zadnje osvježavanje: {last}. Sljedeće: {next}.", "en": "Last refresh: {last}. Next: {next}."}
NOTICE_FIRST = {"hr": "Prvo osvježavanje je u tijeku.", "en": "First refresh in progress."}


def _day(ts, en):
    d = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    return f"{d.day} {d:%b %Y}" if en else f"{d.day}.{d.month}.{d.year}."


def notice_text(lang="hr", now=None):
    """The plain text of the notice (no HTML; the callers escape it). Dates only (no hour, no internal names)."""
    en = lang == "en"
    d = every_d()
    head = NOTICE["en" if en else "hr"].format(since=SINCE_EN if en else SINCE, d=days_word(d) if not en else f"{d:g}")
    last, nxt = notice_dates(now)
    if last is None:
        return head + NOTICE_FIRST["en" if en else "hr"]
    tail = NOTICE_DATES["en" if en else "hr"].format(last=_day(last, en), next=_day(nxt, en))
    return head + tail.replace("..", ".")


# the public notices' one look (the influencer / Telegram notice and ui/pauza's "Autopilot is paused"): a light card
PUBLIC_STYLE = ("margin:0 0 20px;padding:14px 16px;font-size:14px;line-height:1.5;border:1px solid #e5e7eb;"
                "border-radius:18px;background:#fff;color:#111827")


def block_html(text, cls="ms-hint", style="", notr=True):
    """One small notice block of the family (class soc-note), the text escaped. notr: marked translate=no (a public
    page already in its language); the app's Croatian pages are translated on the way out (ui/i18n): notr=False."""
    from html import escape
    st = f" style=\"{escape(style)}\"" if style else ""
    return f'<div class="{escape(cls)} soc-note"{" translate=no" if notr else ""} role=note{st}>{escape(text)}</div>'


def notice_html(lang="hr", now=None, cls="ms-hint", style="", notr=True):
    """The influencer / Telegram notice (block_html of notice_text)."""
    return block_html(notice_text(lang, now), cls, style, notr)


def public_notice(lang="hr", now=None):
    """The notice on the public pages (influencers, Telegram channels, influencer calls): the site's own card style,
    already in the page's language. Dates only; no env name, key, address, cost or internal service in it."""
    try:
        return notice_html(lang, now, cls="card", style=PUBLIC_STYLE)
    except Exception:  # noqa: BLE001 - a notice never costs the page
        return ""


def main(argv=None):
    if path() and not always():
        first_start()
    print(line(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
