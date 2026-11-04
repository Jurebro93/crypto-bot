#!/usr/bin/env python3
"""Telegram call channels: find them, read them, hand their calls to the KOL module.

  python3 run_tg.py loop        # 24/7 on the server: read due channels every tick, discover every hour
  python3 run_tg.py once        # one discovery + one read round (local test)
  python3 run_tg.py status      # counts per status, best channels
  python3 run_tg.py telethon    # optional live listener (TG_API_ID, TG_API_HASH, TG_SESSION)
  python3 run_tg.py login       # once, on your computer: makes TG_SESSION

Free: t.me/s web preview. Paid: TGStat search by CA (TGSTAT_TOKEN), Telethon account (phone number).
Calls end up in kol.db (run_kol.py copies them, source 'tg', author 'tg:<channel>') and hype.db tg_mentions.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

from tg import discover, poll, store, tgstat

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "tg", "config.json")
KOL_DB = os.path.join(HERE, "kol.db")


def config():
    with open(CONFIG) as f:
        return json.load(f)


def kol_view(path=KOL_DB):
    """({channel: KOL score}, {channel: measured calls}, [strong tokens for TGStat]) from kol.db, read-only."""
    con = store.ro(path)
    if con is None:
        return {}, {}, []
    scores, calls, tokens = {}, {}, []
    try:
        for h, sc, st in con.execute("SELECT handle, score, stats FROM kols WHERE handle LIKE 'tg:%'"):
            scores[h[3:]] = sc or 0
            calls[h[3:]] = (json.loads(st or "{}")).get("measured", 0)
        since = int(time.time()) - 6 * 3600
        tokens = [t for t, in con.execute("SELECT token FROM signals WHERE ts>=? ORDER BY feature DESC", (since,))]
        try:
            tokens = [t for t, in con.execute("SELECT token FROM converge WHERE ts>=? ORDER BY score DESC",
                                              (since,))] + tokens
        except sqlite3.OperationalError:
            pass
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    return scores, calls, list(dict.fromkeys(tokens))


def history_round(con, cfg, now=None):
    """Older posts (tg/history.py) for a few channels per hour: paid shillers from kol/shillers.json first, then
    active channels that have fewer than history.target_calls (50) CA posts, the most CA posts first. At most history.pages_per_round t.me pages per round (free)."""
    from kol import shillers
    from tg import history
    hc = cfg.get("history") or {}
    budget = hc.get("pages_per_round", 30)
    now = now or int(time.time())
    since = now - hc.get("days", 365) * 86400
    shill = set(shillers.tg_channels())
    rows = con.execute("SELECT name, n_ca FROM channels WHERE status IN ('active','quiet','slow')").fetchall()
    # shills first, then channels that still have fewer than 50 calls with a CA (the page scores the last 50),
    # most active first; channels that already have 50 go last
    target = hc.get("target_calls", 50)
    order = sorted(rows, key=lambda r: (r[0] not in shill, (r[1] or 0) >= target, -(r[1] or 0)))
    pages = posts = 0
    for name, _ in order:
        if pages >= budget:
            break
        try:
            p, n, _done = history.backfill(con, name, max_pages=min(hc.get("pages_per_channel", 15), budget - pages),
                                           since_ts=since, now=now)
        except Exception as e:  # noqa: BLE001  (a 429 or a broken page: try again next round)
            print(f"tg povijest @{name}: {type(e).__name__}: {e}")
            break
        pages += p
        posts += n
    return pages, posts


def housekeeping(con, cfg, log=print):
    found = discover.run(con)
    scores, calls, tokens = kol_view()
    poll.rebalance(con, cfg, scores, calls)
    r = tgstat.run(con, tokens, cfg["tgstat"]) if tgstat.enabled() else (0, 0, 0)
    h = history_round(con, cfg)
    n = store.prune(con, cfg["prune_days"])
    store.kv_set(con, "last_discover", int(time.time()))
    con.commit()
    log(f"tg otkrivanje: novi kandidati {found}, tgstat upiti/kandidati/objave {r}, povijest stranica/objava {h}, "
        f"obrisano {n} starih")
    return scores


def cmd_loop(a):
    cfg = config()
    con = store.connect()
    scores, last_disc = {}, 0
    while True:
        now = int(time.time())
        try:
            if now - last_disc >= cfg["discover_every_min"] * 60:
                scores = housekeeping(con, cfg)
                last_disc = now
            visited, new = poll.tick(con, cfg, scores, now)
            if new:
                print(f"tg: {visited} kanala pročitano, {new} novih objava s CA")
        except Exception as e:
            print(f"tg: {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(30)
        time.sleep(cfg["tick_s"])


def cmd_once(a):
    cfg = config()
    con = store.connect()
    scores = housekeeping(con, cfg)
    cfg = dict(cfg, validate_per_tick=a.validate, max_fetch_per_tick=a.validate + 10)
    print("pročitano / nove CA objave:", poll.tick(con, cfg, scores))
    cmd_status(a)


def cmd_status(a):
    s = store.summary()
    if not s:
        print("nema tg.db")
        return
    print("statusi:", s["status"])
    for r in s["channels"][:20]:
        print(f"  @{r[0]:<24} {r[3]:<7} pretplatnika {r[2] or 0:>7}  objava {r[5]:>4}  s CA {r[6]:>4}  izvor {r[4]}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("loop")
    op = sub.add_parser("once")
    op.add_argument("--validate", type=int, default=10)
    sub.add_parser("status")
    sub.add_parser("telethon")
    sub.add_parser("login")
    a = p.parse_args(argv)
    if a.cmd == "telethon":
        from tg import live
        return live.run(config())
    if a.cmd == "login":
        from tg import live
        return live.login()
    {"loop": cmd_loop, "once": cmd_once, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
