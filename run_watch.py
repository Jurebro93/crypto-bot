#!/usr/bin/env python3
"""Pre-event token watch: from ~14 days before a big event, snapshot its tokens and look for correlation
between the event getting closer, volume, and which wallets buy.

    python3 run_watch.py sync                 # newest output/dex-*.json -> watch list (events in the next 14 days)
    python3 run_watch.py snap                 # one DexScreener snapshot of every watched token (free)
    python3 run_watch.py snap --wallets       # + new buyers from Helius (~10 credits per token), tiers from wallets.db
    python3 run_watch.py analyze              # correlations -> watch_correlation + output/watch-YYYY-MM-DD.md
    python3 run_watch.py run                  # loop: sync + snap every hour, wallets every 6 h, analyze each time

Writes only watch.db (own file). Reads output/dex-*.json and, read-only, wallets.db.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys
import time

from dexscreener import client
from eventwatch import analyze, store

HERE = os.path.dirname(os.path.abspath(__file__))
WALLET_DB = os.environ.get("WALLET_DB", os.path.join(HERE, "wallets.db"))
GOOD_TIERS = {"A", "B", "S"}
BAD_LABELS = {"bot", "rugger", "bundler", "insider", "dev", "cex", "mev", "sniper", "funder_of_rugger"}


def _now():
    return int(time.time())


def days_to(event_date, now=None):
    """Days from now to noon UTC of the event day (negative after it)."""
    t = dt.datetime.fromisoformat(event_date).replace(hour=12, tzinfo=dt.timezone.utc).timestamp()
    return round((t - (now or time.time())) / 86400, 3)


def newest_dex():
    files = sorted(glob.glob(os.path.join(HERE, "output", "dex-20*.json")), key=os.path.getmtime)
    return files[-1] if files else None


def sync(con, dex, days=14, per_event=3, min_likelihood=0.4, now=None):
    """Add tokens of events in the next `days` days; deactivate tokens whose event ended more than a day ago."""
    now = now or _now()
    added = 0
    for ev in dex.get("events", []):
        d = days_to(ev["date"], now)
        lik = ev.get("token_likelihood")
        if not (-1 <= d <= days) or (lik is not None and lik < min_likelihood):
            continue
        for t in ev["tokens"][:per_event]:
            cur = con.execute("INSERT OR IGNORE INTO watch_tokens (token, event, event_date, symbol, name, role, url, "
                              "likelihood, added_ts, active) VALUES (?,?,?,?,?,?,?,?,?,1)",
                              (t["token"], ev["event"], ev["date"], t["symbol"], t["name"], t["role"], t["url"], lik, now))
            added += cur.rowcount
    for r in con.execute("SELECT token, event, event_date FROM watch_tokens WHERE active=1").fetchall():
        if days_to(r["event_date"], now) < -1:
            con.execute("UPDATE watch_tokens SET active=0 WHERE token=? AND event=? AND event_date=?", tuple(r))
    con.commit()
    return added


def _wallet_info(wallets):
    """{wallet: (tier, labels)} from wallets.db, read-only; empty if the registry isn't there."""
    if not wallets or not os.path.exists(WALLET_DB):
        return {}
    ro = sqlite3.connect(f"file:{WALLET_DB}?mode=ro", uri=True, timeout=10)
    out = {}
    try:
        ws = list(wallets)
        for i in range(0, len(ws), 500):
            chunk = ws[i:i + 500]
            for w, tier, labels in ro.execute(
                    f"SELECT wallet, tier, labels FROM wallets WHERE wallet IN ({','.join('?' * len(chunk))})", chunk):
                out[w] = (tier, set(json.loads(labels or "[]")))
    except sqlite3.OperationalError:
        pass
    finally:
        ro.close()
    return out


def recent_buyers(mint, since_ts, on_credits=None):
    """{wallet: (first_ts, sol_in, n_buys)} of wallets that bought `mint` after since_ts (one cheap Helius page)."""
    from wallets import rpc
    txs, _ = rpc.fetch(mint, since_ts=since_ts, max_pages=1, on_credits=on_credits)
    out = {}
    for tx in txs:
        payer = rpc._keys(tx)[0]
        for r in rpc.parse(tx, payer):
            if r["mint"] == mint and r["kind"] == "buy":
                ts0, sol, n = out.get(payer, (r["ts"], 0.0, 0))
                out[payer] = (min(ts0, r["ts"]), sol - r["sol"], n + 1)
    return out


def snap(con, with_wallets=False, credits=3000, now=None, lookback_h=6):
    """One snapshot per active token. Returns (rows written, credits spent, errors)."""
    now = now or _now()
    watch = [dict(r) for r in con.execute("SELECT * FROM watch_tokens WHERE active=1")]
    if not watch:
        return 0, 0, {}
    pairs = {}
    for p in client.tokens("solana", sorted({w["token"] for w in watch})):
        tok = p["baseToken"]["address"]
        if tok not in pairs or (p.get("liquidity") or {}).get("usd", 0) > (pairs[tok].get("liquidity") or {}).get("usd", 0):
            pairs[tok] = p
    spent, errors, written = [0], {}, 0
    for w in watch:
        p = pairs.get(w["token"])
        if not p:
            errors[w["symbol"]] = "nema para na DexScreeneru"
            continue
        tx, vol = p.get("txns") or {}, p.get("volume") or {}
        row = {"token": w["token"], "event_date": w["event_date"], "ts": now,
               "days_to_event": days_to(w["event_date"], now), "price": float(p.get("priceUsd") or 0),
               "mcap": p.get("marketCap") or p.get("fdv") or 0, "liquidity": (p.get("liquidity") or {}).get("usd") or 0,
               "vol_h1": vol.get("h1") or 0, "vol_h24": vol.get("h24") or 0,
               "buys_h1": (tx.get("h1") or {}).get("buys", 0), "sells_h1": (tx.get("h1") or {}).get("sells", 0),
               "buys_h24": (tx.get("h24") or {}).get("buys", 0), "sells_h24": (tx.get("h24") or {}).get("sells", 0),
               "new_buyers": None, "smart_buyers": None, "bad_buyers": None, "buyer_sol": None}
        if with_wallets and spent[0] < credits:
            try:
                since = w["wallets_ts"] or now - lookback_h * 3600
                buyers = recent_buyers(w["token"], since, on_credits=lambda c: spent.__setitem__(0, spent[0] + c))
                known = {r["wallet"] for r in con.execute("SELECT wallet FROM watch_buyers WHERE token=?", (w["token"],))}
                info = _wallet_info(buyers)
                new = {b: v for b, v in buyers.items() if b not in known}
                smart = [b for b in new if (info.get(b) or (None,))[0] in GOOD_TIERS]
                bad = [b for b in new if (info.get(b) or (None, set()))[1] & BAD_LABELS]
                row.update(new_buyers=len(new), smart_buyers=len(smart), bad_buyers=len(bad),
                           buyer_sol=round(sum(v[1] for v in new.values()), 3))
                for b, (ts0, sol, n) in buyers.items():
                    tier, labels = info.get(b, (None, set()))
                    con.execute("INSERT INTO watch_buyers VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(token, wallet) DO UPDATE "
                                "SET sol_in=sol_in+excluded.sol_in, buys=buys+excluded.buys, tier=excluded.tier, "
                                "labels=excluded.labels",
                                (w["token"], b, ts0, round(sol, 4), n, tier, json.dumps(sorted(labels)),
                                 days_to(w["event_date"], ts0)))
                con.execute("UPDATE watch_tokens SET wallets_ts=? WHERE token=?", (now, w["token"]))
            except Exception as e:
                errors[w["symbol"]] = f"{type(e).__name__}: {e}"
        con.execute(f"INSERT OR REPLACE INTO watch_snapshots ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                    list(row.values()))
        written += 1
    con.commit()
    return written, spent[0], errors


def run_analysis(con, now=None):
    now = now or _now()
    results = []
    for w in con.execute("SELECT DISTINCT token, event, event_date, symbol FROM watch_tokens").fetchall():
        snaps = [dict(r) for r in con.execute("SELECT * FROM watch_snapshots WHERE token=? AND event_date=? ORDER BY ts",
                                              (w["token"], w["event_date"]))]
        if not snaps:
            continue
        c = analyze.correlate(snaps)
        row = {"token": w["token"], "event": w["event"], "event_date": w["event_date"], "symbol": w["symbol"], **c,
               "updated_ts": now}
        con.execute(f"INSERT OR REPLACE INTO watch_correlation ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                    list(row.values()))
        results.append(row)
    con.commit()
    return results


def _c(x):
    return "–" if x is None else f"{x:+.2f}"


def report(results):
    lines = ["# Praćenje tokena prije eventa", "",
             "Za svaki token vezan uz event u sljedećih 14 dana: korelacija (Spearman, -1 do +1) između približavanja "
             "eventa i volumena, broja kupnji, novih kupaca i smart walleta. +1 znači da raste kako se event bliži.", "",
             "| Event | Datum | Token | Snimki | Volumen | Kupnje | Novi kupci | Smart | Cijena | Promjena vol. | Smart/loši | Zaključak |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(results, key=lambda r: (r["event_date"], -(r["corr_volume"] or -2))):
        vc = "–" if r["vol_change"] is None else f"{r['vol_change']:+.0f}%"
        lines.append(f"| {r['event']} | {r['event_date']} | {r['symbol']} | {r['n']} | {_c(r['corr_volume'])} | "
                     f"{_c(r['corr_buys'])} | {_c(r['corr_buyers'])} | {_c(r['corr_smart'])} | {_c(r['corr_price'])} | "
                     f"{vc} | {r['smart_total']}/{r['bad_total']} | {r['verdict']} |")
    return "\n".join(lines) + "\n"


def cmd_analyze(con):
    results = run_analysis(con)
    md = report(results)
    out = os.path.join(HERE, "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"watch-{dt.date.today()}.md"), "w") as f:
        f.write(md)
    return md


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--days", type=int, default=14)
    s.add_argument("--per-event", type=int, default=3)
    s.add_argument("--min-likelihood", type=float, default=0.4)
    n = sub.add_parser("snap")
    n.add_argument("--wallets", action="store_true")
    n.add_argument("--credits", type=int, default=3000, help="Helius credit cap for this run")
    sub.add_parser("analyze")
    r = sub.add_parser("run")
    r.add_argument("--every-min", type=int, default=60)
    r.add_argument("--wallets-every-h", type=int, default=6)
    r.add_argument("--credits", type=int, default=3000)
    a = p.parse_args(argv)
    con = store.connect()

    def do_sync():
        f = newest_dex()
        if f:
            with open(f) as fh:
                print(f"sync: {sync(con, json.load(fh))} novih tokena iz {os.path.basename(f)}")

    if a.cmd == "sync":
        f = newest_dex()
        if not f:
            sys.exit("Nema output/dex-*.json: prvo pokreni python3 run_dex.py scan")
        with open(f) as fh:
            print(f"{sync(con, json.load(fh), a.days, a.per_event, a.min_likelihood)} novih tokena na praćenju")
    elif a.cmd == "snap":
        n_rows, spent, errors = snap(con, a.wallets, a.credits)
        print(f"{n_rows} snimki, {spent} Helius kredita" + (f", greške: {errors}" if errors else ""))
    elif a.cmd == "analyze":
        print(cmd_analyze(con))
    else:
        last_wallets = 0
        while True:
            try:
                do_sync()
                wallets = bool(os.environ.get("HELIUS_API_KEY")) and time.time() - last_wallets >= a.wallets_every_h * 3600
                n_rows, spent, errors = snap(con, wallets, a.credits)
                if wallets:
                    last_wallets = time.time()
                print(f"watch: {n_rows} snimki, {spent} kredita" + (f", greške: {len(errors)}" if errors else ""))
                cmd_analyze(con)
            except Exception as e:
                print(f"watch nije uspio: {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(a.every_min * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
