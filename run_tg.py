#!/usr/bin/env python3
"""Telegram kanali: samo informativni popis s brojem pratitelja (19.11.2026., vlasnik: "Makni Telegram KOL-ove iz
izračuna. Ali zadrži popis kanala, osvježen jednom tjedno, samo za broj pratitelja.").

  python3 run_tg.py pratitelji     # the weekly follower count of the due channels (tg/pratitelji.py); start.sh
                                   # starts it once a day, a channel is read at most once in TG_FOLLOWERS_EVERY_D (7)
  python3 run_tg.py status         # the list: channels, followers, the last pass

Until 19.11. this was the 24/7 Telegram call reader (t.me/s every 30 s, discovery every hour, history backfill, TGStat
search, the Telethon listener) whose calls went into kol.db. All of that is gone: no message is read, no call parsed,
no channel discovered, nothing paid is asked. Its free source (the channel's public web page) is read once a week for
the header's subscriber count only. Calculations leave the stored Telegram calls out (kol/tgout.py).
"""
import argparse
import sys

from tg import pratitelji


def cmd_pratitelji(a):
    pratitelji.run()
    return 0


def cmd_status(a):
    rows = pratitelji.pregled()
    if not rows:
        print("nema tg.db ili nema kanala")
        return 0
    last = pratitelji.zadnji() or {}
    print(f"kanala {len(rows)}; zadnji prolaz {last.get('ts') or '–'}: {last.get('rows', 0)} osvježeno")
    for r in rows[:30]:
        d7 = "–" if r["d7"] is None else f"{r['d7']:+d}"
        print(f"  {r['kanal']:<32} pratitelja {r['pratitelji'] or 0:>9}  7 dana {d7:>7}")
    return 0


def main(argv=None):
    try:   # 10.11. (Jure): errors go to Sentry (ops/sentry.py); a no-op without SENTRY_DSN, never stops the start
        from ops import sentry
        sentry.init("tg")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pratitelji")
    sub.add_parser("status")
    a = p.parse_args(argv)
    return {"pratitelji": cmd_pratitelji, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
