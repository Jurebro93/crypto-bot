"""Daily update for the traders' WhatsApp group (share/).

    python3 run_whatsapp.py preview     # print today's message
    python3 run_whatsapp.py send        # send it now (needs WHATSAPP_* on Render, see share/send.py)
    python3 run_whatsapp.py due         # send only if today's daily message has not gone yet (run_sched calls this)
    python3 run_whatsapp.py status
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from share import digest, send as gateway  # noqa: E402


def local_day(now=None):
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        d = dt.datetime.fromtimestamp(now or time.time(), ZoneInfo("Europe/Zagreb"))
    except Exception:  # noqa: BLE001
        d = dt.datetime.utcfromtimestamp((now or time.time()) + 3600)
    return d.strftime("%Y-%m-%d"), d.hour


def send_now():
    text = digest.build()
    try:
        how = gateway.send(text)
        digest.mark_shared("sent")
        digest.save_state(sent_day=local_day()[0], error=None, how=how)
        print(f"whatsapp: poslano u grupu ({how})", flush=True)
        return True
    except Exception as e:  # noqa: BLE001
        digest.save_state(error=f"{type(e).__name__}: {e}"[:300], error_ts=int(time.time()))
        print(f"whatsapp: slanje nije uspjelo: {type(e).__name__}: {e}", flush=True)
        return False


def due(now=None):
    """Configured, past WHATSAPP_HOUR, not sent today, at most one try per 30 min."""
    if not gateway.configured():
        return False
    day, hour = local_day(now)
    st = digest.load_state()
    if hour < int(os.environ.get("WHATSAPP_HOUR", "19")) or st.get("sent_day") == day:
        return False
    return time.time() - (st.get("error_ts") or 0) > 1800


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["preview", "send", "due", "status"])
    a = ap.parse_args()
    if a.cmd == "preview":
        print(digest.build())
    elif a.cmd == "send":
        return 0 if send_now() else 1
    elif a.cmd == "due":   # exit 0 = today's message is done (sent, or sending is off), 1 = try again later
        if not gateway.configured() or digest.load_state().get("sent_day") == local_day()[0]:
            return 0
        if due():
            return 0 if send_now() else 1
        return 1
    else:
        print(json.dumps({"provider": gateway.provider(), "missing": gateway.missing(),
                          "state": {k: v for k, v in digest.load_state().items() if k != "sent_news"}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
