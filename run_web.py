"""Public web, once a day (10.11.2026., Jure: "podaci bi se trebali jednom dnevno osvježiti na cijelom webu, znači
da sve tablice na cijelom webu budu prikazane s novim podacima; možda napravi zadatak u 2 po noći").

    python3 run_web.py daily [--no-net]     # the 02:00 job (run_sched.py "web"): refresh + one site log row
    python3 run_web.py log [-n 7]           # print the last days of the site log

daily, in this order (every step is guarded: a failed step is one log line and the rest still runs):
  1. the top-100 meme coin list in public.db is read again from Jupiter's free list when it is older than an hour
     (the only network call, free and without a key; --no-net or WEB_DAILY_NO_NET=1 skips it; the web process
     reads the same list every 3 h anyway)
  2. the data blocks of the blog are counted again from our own databases (ui/bloglive.py)
  3. one row goes into public.db site_log: what is new since the previous night (ui/sitelog.py). That row is also
     the marker the web process watches: when it moves, the dashboard drops its in-memory copies of public pages,
     so the next view of every public table is built from the databases as they are now (ui/landing.refreshed).
No paid source is called: the job only re-reads our own databases. The influencer and Telegram tables, the coin
pages and the market pages are built from those databases on view; step 3 makes the web process forget its copies.
A short process, like every run_sched.py job: it ends and hands its memory back.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COINS_MAX_AGE_S = 3600
NAMES = {"kols": "influenceri na ljestvici", "calls": "izmjereni pozivi", "channels": "Telegram kanali",
         "wallets": "novčanici", "trades": "tradeovi novčanika", "coins": "meme coini", "tokens": "provjereni tokeni"}


def _step(name, fn):
    """fn() or None; a failure is one line and the job carries on with the next step."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"web dnevno: korak '{name}' nije uspio: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr, flush=True)
        return None


def _coins():
    from ui import coins
    age = coins.age_s()
    if age is not None and age < COINS_MAX_AGE_S:
        return 0
    return coins.refresh()


def _words(entry):
    """'influenceri na ljestvici +12, izmjereni pozivi +340; blogovi s novim podacima: 5' for the log line."""
    from ui import sitelog
    parts = [f"{NAMES[k]} +{entry['added'][k]}" for k in sitelog.KEYS if k in entry["added"]]
    if parts:
        out = ", ".join(parts)
    elif entry.get("first"):
        out = "prvi zapis, sutra se brojke uspoređuju s ovima"
    else:
        out = "brojke bez rasta"
    if entry["blogs"]:
        out += f"; blogovi s novim podacima: {len(entry['blogs'])}"
    if entry["posts"]:
        out += f"; novi članci: {len(entry['posts'])}"
    return out


def daily(now=None, net=True):
    """The whole daily refresh. Returns the stored site log entry, or None when the row could not be written
    (then the web process is not told anything and the scheduler tries again later)."""
    from ui import bloglive, sitelog
    t0 = time.time()
    if net and not os.environ.get("WEB_DAILY_NO_NET"):
        _step("coini", _coins)
    changed = _step("blog", lambda: bloglive.refresh(now)) or []
    entry = _step("dnevnik", lambda: sitelog.record(now, blogs=changed))
    if entry:
        print(f"web dnevno: {entry['day']} gotovo za {time.time() - t0:.1f} s: {_words(entry)}", flush=True)
    return entry


def cmd_daily(a):
    try:
        from ops import heavy
        os.nice(heavy.NICE)   # below the UI and the trade loop, like every background job (ops/heavy.py)
    except Exception:  # noqa: BLE001
        pass
    return 0 if daily(net=not a.no_net) else 1


def cmd_log(a):
    from ui import sitelog
    print(f"MemeSonar je live {sitelog.live_days()} dana (od {sitelog.start_date().isoformat()})")
    for e in sitelog.recent(a.n):
        print(f"{e['day']}: {_words(e)}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily")
    d.add_argument("--no-net", action="store_true", help="bez čitanja Jupiterove liste (samo naše baze)")
    lg = sub.add_parser("log")
    lg.add_argument("-n", type=int, default=7)
    a = p.parse_args(argv)
    try:   # another group's module (ops/sentry.py, 10.11.): errors of this job reach Sentry once it exists
        from ops import sentry
        sentry.init("web")
    except Exception:  # noqa: BLE001
        pass
    return {"daily": cmd_daily, "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
