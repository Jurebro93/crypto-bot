#!/usr/bin/env python3
"""DexScreener lookups for the event calendar.

    python3 run_dex.py scan                 # tokens tied to each calendar event, canonical first
    python3 run_dex.py scan --calendar output/calendar-2026-10-30.json --min-liq 5000
    python3 run_dex.py trending             # top boosts, new profiles, trending metas
    python3 run_dex.py token <address>      # all pairs of one token + paid orders

scan writes output/dex-YYYY-MM-DD.md and .json and upserts rows into calendar.db (table event_tokens).
"""
import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys

from dexscreener import client
from dexscreener.match import best_pairs, event_terms, rank_event_tokens, summarize, weak_terms

HERE = os.path.dirname(os.path.abspath(__file__))


def _usd(x):
    x = x or 0
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:.0f}"


def latest_calendar():
    files = sorted(glob.glob(os.path.join(HERE, "output", "calendar-*.json")))
    if not files:
        sys.exit("Nema kalendara: prvo pokreni python3 run_calendar.py")
    return files[-1]


def scan(events, chain="solana", min_liq=1000, per_event=8):
    """Event -> tokens. Searches each event's specific terms once, ranks canonical token vs copycats."""
    try:
        cto = {c["tokenAddress"] for c in client.community_takeovers()}
    except Exception:
        cto = set()
    cache, errors, out = {}, {}, []
    for ev in events:
        weak = weak_terms(ev)
        terms = [t for t in event_terms(ev) if t.upper() not in weak]
        rows = {}
        for t in terms:
            if t not in cache:
                try:
                    cache[t] = best_pairs(client.search(t), chain, min_liq)
                except Exception as e:
                    errors[t] = f"{type(e).__name__}: {e}"
                    cache[t] = []
            for r in cache[t]:
                rows.setdefault(r["token"], r)
        tokens = rank_event_tokens(list(rows.values()), terms, cto)[:per_event]
        out.append({"event": ev["title"], "date": ev["date"], "kind": ev.get("kind"), "hype": ev.get("hype"),
                    "token_likelihood": ev.get("token_likelihood"), "terms": terms, "tokens": tokens})
    return out, errors


def save_db(results, path):
    con = sqlite3.connect(path)
    con.execute("DROP TABLE IF EXISTS dex_tokens")  # replaced by event_tokens
    con.execute("""CREATE TABLE IF NOT EXISTS event_tokens (
        event_date TEXT, event TEXT, chain TEXT, token TEXT, role TEXT, score REAL, keyword TEXT,
        symbol TEXT, name TEXT, url TEXT, mcap REAL, liquidity REAL, vol_24h REAL, age_h REAL,
        cto INTEGER, data TEXT, seen_at TEXT,
        PRIMARY KEY (event_date, event, chain, token))""")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.executemany(
        "INSERT OR REPLACE INTO event_tokens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(ev["date"], ev["event"], r["chain"], r["token"], r["role"], r["score"], r["keyword"], r["symbol"],
          r["name"], r["url"], r["mcap"], r["liquidity"], r["vol_24h"], r["age_h"], int(r["cto"]),
          json.dumps(r), now) for ev in results for r in ev["tokens"]])
    con.commit()
    con.close()


def report(results, errors, title):
    lines = [f"# {title}", "",
             "Prvi token u svakom događaju je najvjerojatnije pravi (stariji, organski promet, CTO, društvene mreže); "
             "ostali su kopije. Ocjena 0-100 je samo iz DexScreener podataka, bez holdera i walleta.", ""]
    if errors:
        lines += ["Upiti koji nisu radili: " + "; ".join(f"{k} ({v})" for k, v in errors.items()), ""]
    for ev in results:
        lik = f", vjerojatnost tokena {ev['token_likelihood']}" if ev.get("token_likelihood") is not None else ""
        lines += [f"## {ev['event']} ({ev['date']}, hype {ev['hype']}{lik})", "",
                  f"Traženo: {', '.join(ev['terms']) or 'ništa specifično'}", ""]
        if not ev["tokens"]:
            lines += ["Nema tokena.", ""]
            continue
        lines += ["| Uloga | Ocjena | Token | Ime | MCap | Likvidnost | Vol 24h | 1h % | Kupnje/prodaje | Starost | CTO |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in ev["tokens"]:
            age = f"{r['age_h'] / 24:.1f} d" if r["age_h"] is not None else "?"
            lines.append(f"| {'pravi' if r['role'] == 'canonical' else 'kopija'} | {r['score']} | "
                         f"[{r['symbol']}]({r['url']}) | {r['name']} | {_usd(r['mcap'])} | {_usd(r['liquidity'])} | "
                         f"{_usd(r['vol_24h'])} | {r['chg_1h']} | {r['buys_24h']}/{r['sells_24h']} | {age} | "
                         f"{'da' if r['cto'] else ''} |")
        lines.append("")
    return "\n".join(lines)


def cmd_scan(a):
    path = a.calendar or latest_calendar()
    with open(path) as f:
        cal = json.load(f)
    # 11.11. (owner's events rule): a regime label (kind "regime") is never searched for event tokens
    events = [e for e in cal["events"] if (e.get("hype") or 0) >= a.min_hype and e.get("kind") != "regime"]
    events.sort(key=lambda e: -(e.get("token_likelihood") or 0))  # stable: hype order when absent
    events = events[:a.events]
    results, errors = scan(events, a.chain, a.min_liq, a.per_event)
    day = cal.get("date") or dt.date.today().isoformat()
    out = os.path.join(HERE, "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"dex-{day}.json"), "w") as f:
        json.dump({"calendar": os.path.basename(path), "chain": a.chain, "errors": errors, "events": results},
                  f, indent=1, ensure_ascii=False)
    md = report(results, errors, f"Tokeni po događaju, kalendar {day} ({a.chain})")
    with open(os.path.join(out, f"dex-{day}.md"), "w") as f:
        f.write(md)
    save_db(results, os.path.join(HERE, "calendar.db"))
    print(md)
    return 0


def cmd_trending(a):
    def chain_ok(x):
        return not a.chain or x.get("chainId") == a.chain

    print("## Top boostovi")
    for b in [b for b in client.top_boosts() if chain_ok(b)][:a.limit]:
        print(f"- {b.get('totalAmount', 0):>5} boost  {b['tokenAddress']}  {b['url']}")
    print("\n## Novi token profili")
    for p in [p for p in client.latest_token_profiles() if chain_ok(p)][:a.limit]:
        print(f"- {p['tokenAddress']}  {(p.get('description') or '')[:70]!r}")
    print("\n## Trending teme (metas)")
    for m in client.trending_metas()[:a.limit]:
        print(f"- {m.get('name')} ({m.get('slug')}): mcap {_usd(m.get('marketCap'))}, vol {_usd(m.get('volume'))}, "
              f"h24 {m.get('marketCapChange', {}).get('h24', 0):+.1f}%")
    return 0


def cmd_token(a):
    rows = [summarize(p) for p in client.token_pairs(a.chain, a.address)]
    for r in sorted(rows, key=lambda r: -r["liquidity"]):
        print(f"{r['symbol']:<10} {r['dex']:<10} liq {_usd(r['liquidity']):>8}  vol24 {_usd(r['vol_24h']):>8}  "
              f"mcap {_usd(r['mcap']):>8}  age {r['age_h']}h  {r['url']}")
    for o in client.orders(a.chain, a.address):
        print(f"order: {o.get('type')} {o.get('status')} "
              f"{dt.datetime.fromtimestamp(o.get('paymentTimestamp', 0) / 1000, dt.timezone.utc):%Y-%m-%d}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--calendar", help="calendar JSON, default the newest in output/")
    s.add_argument("--chain", default="solana", help="'' = all chains")
    s.add_argument("--min-liq", type=float, default=1000)
    s.add_argument("--min-hype", type=float, default=0)
    s.add_argument("--events", type=int, default=40)
    s.add_argument("--per-event", type=int, default=8)
    t = sub.add_parser("trending")
    t.add_argument("--chain", default="solana")
    t.add_argument("--limit", type=int, default=10)
    k = sub.add_parser("token")
    k.add_argument("address")
    k.add_argument("--chain", default="solana")
    a = p.parse_args(argv)
    return {"scan": cmd_scan, "trending": cmd_trending, "token": cmd_token}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
