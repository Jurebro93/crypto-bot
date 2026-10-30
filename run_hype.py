#!/usr/bin/env python3
"""Early detection of hype / narrative tokens on Solana, smart-money wallets, and a feedback loop.

    python3 run_hype.py scan                       # one pass: candidates -> features -> score -> log
    python3 run_hype.py watch --interval 120       # scan + track in a loop, alerts to stdout / Telegram
    python3 run_hype.py track                      # price snapshots for logged tokens (feeds eval)
    python3 run_hype.py eval --fit                 # how good were the signals, suggested weights
    python3 run_hype.py learn <mint> [<mint>...]   # smart wallets = early buyers of winners, scored by PnL
    python3 run_hype.py wallet <address>           # score one wallet
    python3 run_hype.py buyers <mint>              # early buyers of a token, smart ones marked

Telegram call channels: hype/channels.txt (one public channel name per line) or --channels a,b.
Alerts to your own bot when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from dexscreener import client
from hype import evaluate, onchain, score, store, telegram, xbuzz

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "hype.db")  # own file: SQLite on the shared mount locks badly under concurrent writers
CHANNELS = os.path.join(HERE, "hype", "channels.txt")


def _usd(x):
    x = x or 0
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:.0f}"


def _channels(arg):
    if arg:
        return [c.strip() for c in arg.split(",") if c.strip()]
    if os.path.exists(CHANNELS):
        with open(CHANNELS) as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    return []


def calendar_keywords():
    files = sorted(glob.glob(os.path.join(HERE, "output", "calendar-*.json")))
    if not files:
        return set()
    with open(files[-1]) as f:
        return {score._norm(k) for e in json.load(f)["events"] for k in e.get("keywords", []) if len(k) >= 3}


def collect_tg(channels):
    posts, errors = telegram.mentions(channels)
    con = store.connect(DB)
    for p in posts:
        for ca in p["cas"] or [""]:
            con.execute("INSERT OR IGNORE INTO tg_mentions VALUES (?,?,?,?,?)",
                        (p["channel"], p["post"], p["time"], ca, ",".join(p["tickers"])))
    con.commit()
    return posts, errors


def candidates(tg_cas, use_metas=True):
    """token address -> set of sources that surfaced it."""
    found = {}

    def add(addr, src):
        found.setdefault(addr, set()).add(src)

    feeds = [("profile", client.latest_token_profiles), ("profile_update", client.recent_profile_updates),
             ("boost", client.latest_boosts), ("top_boost", client.top_boosts), ("takeover", client.community_takeovers)]
    for src, fn in feeds:
        try:
            for x in fn() or []:
                if x.get("chainId") == "solana":
                    add(x["tokenAddress"], src)
        except Exception as e:
            print(f"  {src}: {type(e).__name__}: {e}", file=sys.stderr)
    if use_metas:
        try:  # the 3 metas gaining fastest this hour
            hot = sorted(client.trending_metas(), key=lambda m: -(m.get("marketCapChange") or {}).get("h1", 0))[:3]
            for m in hot:
                for p in client.meta(m["slug"]).get("pairs") or []:
                    if p.get("chainId") == "solana":
                        add(p["baseToken"]["address"], f"meta:{m['slug']}")
        except Exception as e:
            print(f"  metas: {type(e).__name__}: {e}", file=sys.stderr)
    for ca in tg_cas:
        add(ca, "telegram")
    return found


def scan(a, weights, smart, tg_count, now=None):
    now_ms = (now or time.time()) * 1000
    found = candidates(tg_count, use_metas=not a.no_metas)
    pairs = client.tokens("solana", list(found))
    best = {}
    for p in pairs:
        t = p["baseToken"]["address"]
        if t in found and ((p.get("liquidity") or {}).get("usd") or 0) > ((best.get(t, {}).get("liquidity") or {}).get("usd") or 0):
            best[t] = p
    cal = calendar_keywords()
    rows = []
    for t, p in best.items():
        liq, mcap = (p.get("liquidity") or {}).get("usd") or 0, p.get("marketCap") or p.get("fdv") or 0
        if liq < a.min_liq or mcap > a.max_mcap:
            continue
        f = score.market_features(p, now_ms)
        sym, name = p["baseToken"].get("symbol", ""), p["baseToken"].get("name", "")
        f["takeover"] = 1.0 if {"takeover", "profile_update"} & found[t] and f["revival"] > 0 else 0.0
        f["calendar"] = 1.0 if {score._norm(sym), score._norm(name)} & cal else 0.0
        f["telegram"] = min(1.0, tg_count.get(t, 0) / 3)
        f["narrative"] = 0.0
        f["smart_money"] = 0.0
        f["x_buzz"] = 0.0
        rows.append({"token": t, "symbol": sym, "name": name, "pair": p.get("pairAddress"), "url": p.get("url"),
                     "price": float(p.get("priceUsd") or 0), "mcap": mcap, "liquidity": liq,
                     "sources": found[t], "features": f, "score": score.score(f, weights), "raw": p})
    rows.sort(key=lambda r: -r["score"])
    # expensive checks only for the best pre-scored candidates
    for r in rows[:a.deep]:
        try:
            r["copycats"] = score.copycats(client.search(r["symbol"]), r["symbol"], r["name"], r["token"], now_ms)
            r["features"]["narrative"] = min(1.0, r["copycats"] / 8)
        except Exception as e:
            print(f"  search {r['symbol']}: {e}", file=sys.stderr)
        if smart and os.environ.get("HELIUS_API_KEY"):
            try:
                buyers = onchain.early_buyers(r["token"], n=60, pages=1)
                r["smart_buyers"] = [b["wallet"] for b in buyers if b["wallet"] in smart]
                r["features"]["smart_money"] = min(1.0, len(r["smart_buyers"]) / 4)
            except Exception as e:
                print(f"  helius {r['symbol']}: {e}", file=sys.stderr)
        r["score"] = score.score(r["features"], weights)
    if xbuzz.enabled():  # paid: only tokens that already look good
        for r in [r for r in rows if r["score"] >= a.x_min_score][:a.x_top]:
            try:
                r["x"] = xbuzz.token_buzz(r["token"], r["symbol"])
                r["features"]["x_buzz"] = r["x"]["feature"]
                r["score"] = score.score(r["features"], weights)
            except Exception as e:
                print(f"  apify {r['symbol']}: {e}", file=sys.stderr)
    rows.sort(key=lambda r: -r["score"])
    con = store.connect(DB)  # fresh handle: a connection held across minutes of HTTP goes stale on the shared mount
    for r in rows:
        store.log_signal(con, r, weights)
        store.snapshot(con, r["token"], r["price"], r["mcap"], r["liquidity"])
    con.commit()
    return rows


def track(hours=48):
    since = int(time.time() - hours * 3600)
    con = store.connect(DB)
    tokens = [t for (t,) in con.execute("SELECT DISTINCT token FROM hype_signals WHERE ts >= ?", (since,))]
    con.close()
    best = {}
    for p in client.tokens("solana", tokens):
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= best.get(t, (0, 0, -1))[2]:
            best[t] = (float(p.get("priceUsd") or 0), p.get("marketCap") or 0, liq)
    con = store.connect(DB)
    for t in tokens:
        price, mcap, liq = best.get(t, (0, 0, 0))  # vanished pair = liquidity 0, counts as rug
        store.snapshot(con, t, price, mcap, liq)
    con.commit()
    return len(tokens)


def alert(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15).read()
    except Exception as e:
        print(f"  telegram alert: {e}", file=sys.stderr)


def fmt(r):
    f = r["features"]
    top = ", ".join(f"{k} {v:.1f}" for k, v in sorted(f.items(), key=lambda kv: -kv[1])[:4] if v > 0)
    extra = []
    if r.get("copycats"):
        extra.append(f"{r['copycats']} kopija")
    if r.get("x"):
        extra.append(f"X: {r['x']['authors']} autora, influenceri {[h for h, _ in r['x']['influencers']]}")
    if r.get("smart_buyers"):
        extra.append(f"{len(r['smart_buyers'])} smart walleta")
    return (f"{r['score']:5.1f}  {r['symbol']:<12} mcap {_usd(r['mcap']):>7} liq {_usd(r['liquidity']):>7}  "
            f"[{top}] {' | '.join(extra)}  izvori: {','.join(sorted(r['sources']))}  {r['url']}")


def cmd_scan(a):
    w = score.load_weights(a.weights)
    chans = _channels(a.channels)
    if chans:
        posts, errors = collect_tg(chans)
        print(f"Telegram: {len(posts)} postova s CA/tickerom iz {len(chans)} kanala; greške: {errors or 'nema'}")
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=6)).isoformat()
    con = store.connect(DB)
    smart, tg = store.smart_set(con, a.smart_min), store.tg_counts(con, since)
    con.close()
    try:  # profitable wallets from the shared registry, bots and snipers included (they are a signal too)
        from wallets import store as wstore
        smart |= set(wstore.signal_wallets(wstore.connect(), a.smart_min))
    except Exception as e:
        print(f"wallets.db: {e}", file=sys.stderr)
    rows = scan(a, w, smart, tg)
    print(f"\n{len(rows)} kandidata (liq >= {_usd(a.min_liq)}, mcap <= {_usd(a.max_mcap)}), top {a.top}:")
    for r in rows[:a.top]:
        print(fmt(r))
    return rows


def cmd_watch(a):
    alerted = set()
    while True:
        try:
            rows = cmd_scan(a)
            n = track()
            print(f"praćeno {n} tokena  {dt.datetime.now():%H:%M:%S}\n")
            for r in rows:
                if r["score"] >= a.alert and r["token"] not in alerted:
                    alerted.add(r["token"])
                    alert(f"🔥 {r['symbol']} score {r['score']}\n{fmt(r)}")
        except Exception as e:
            print(f"greška u prolazu: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(a.interval)


def cmd_track(a):
    print(f"snapshot za {track(a.hours)} tokena")


def cmd_eval(a):
    rows = evaluate.outcomes(store.connect(DB), a.horizon, a.hit)
    print(f"{len(rows)} signala s ishodom (horizont {a.horizon} h, pogodak = max rast >= {a.hit:.0%})\n")
    if not rows:
        print("Premalo podataka: pusti `watch` da radi barem jedan horizont.")
        return
    print("Po ocjeni:")
    for b in evaluate.by_bucket(rows):
        print(f"  {b['bucket']:>7}: n={b['n']:<4} pogodaka {b['hit_rate']:.0%}  rugova {b['rug_rate']:.0%}  "
              f"medijan na kraju {b['median_end']:+.0%}")
    print("\nKoliko svaki signal pomaže (lift > 1 = pomaže):")
    for f in sorted(evaluate.feature_lift(rows), key=lambda x: -(x["lift"] or 0)):
        print(f"  {f['feature']:<13} n={f['n_strong']:<4} jak {f['hit_strong']:.0%} / slab {f['hit_weak']:.0%}  lift {f['lift']}")
    pt = evaluate.paper_trade(rows, a.min_score, a.tp, a.sl)
    print(f"\nPaper trading (score >= {a.min_score}, TP {a.tp:+.0%}, SL {a.sl:+.0%}): {pt}")
    if a.fit:
        fit = evaluate.fit_weights(rows)
        if not fit:
            print("\nFit: treba barem 30 signala i barem jedan pogodak.")
            return
        path = os.path.join(HERE, "hype", "weights.suggested.json")
        with open(path, "w") as f:
            json.dump(fit["weights"], f, indent=1)
        print(f"\nPredložene težine (n={fit['n']}) u {path}:\n  {fit['weights']}\n"
              f"Isprobaj: python3 run_hype.py scan --weights {path}")


def cmd_wallet(a):
    trades, meta = onchain.wallet_trades(a.address, a.pages)
    s = onchain.score_wallet(trades, meta)
    print(json.dumps(s, indent=1))
    return s


def cmd_buyers(a):
    smart = store.smart_set(store.connect(DB), a.smart_min)
    for b in onchain.early_buyers(a.mint, a.n, pages=2):
        mark = "SMART" if b["wallet"] in smart else ""
        print(f"+{b['secs_after_first']:>6}s  {b['sol_in']:>8} SOL  {b['wallet']}  {b['source']}  {mark}")


def auto_winners(min_mcap=1e6, max_days=7):
    """Solana tokens on DexScreener's feeds that went from launch to >= min_mcap within max_days."""
    found = candidates({}, use_metas=True)
    now_ms = time.time() * 1000
    best = {}
    for p in client.tokens("solana", list(found)):
        age_d = (now_ms - (p.get("pairCreatedAt") or 0)) / 8.64e7
        if (p.get("marketCap") or 0) >= min_mcap and age_d <= max_days:
            best[p["baseToken"]["address"]] = max(best.get(p["baseToken"]["address"], 0), p.get("marketCap") or 0)
    return sorted(best, key=lambda t: -best[t])


def cmd_learn(a):
    """Wallets that were early in several winners are candidates; their own PnL decides who stays."""
    hits = {}
    mints = list(a.mints)
    if a.auto:
        mints += auto_winners(a.auto_mcap, a.auto_days)[:a.auto]
        print(f"pobjednici: {mints}")
    for mint in mints:
        for b in onchain.early_buyers(mint, a.n, pages=a.buyer_pages):
            # first seconds = dev bundle / snipers; dust buys = arbitrage bots
            if b["secs_after_first"] > a.skip_first_secs and b["sol_in"] >= a.min_sol:
                hits.setdefault(b["wallet"], []).append(mint)
    cands = sorted(hits, key=lambda w: -len(hits[w]))
    cands = [w for w in cands if len(hits[w]) >= a.min_overlap][:a.max_wallets]
    print(f"{len(hits)} ranih kupaca, {len(cands)} u >= {a.min_overlap} pobjednika; ocjenjujem ih po PnL-u...")
    for w in cands:
        try:
            trades, meta = onchain.wallet_trades(w, a.pages)
            s = onchain.score_wallet(trades, meta)
        except Exception as e:
            print(f"  {w}: {e}", file=sys.stderr)
            continue
        s["early_in"] = hits[w]
        con = store.connect(DB)
        store.save_wallet(con, w, s, ",".join(hits[w]))
        con.commit()
        print(f"  {s['score']:>3}  {w}  win {s['win_rate']:.0%}  pnl {s['pnl_sol']:+.1f} SOL  2x+ {s['big_wins']}  "
              f"zatvoreno {s['closed']}  {'BOT' if s['bot'] else ''}")
    con.commit()


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "watch"):
        s = sub.add_parser(name)
        s.add_argument("--min-liq", type=float, default=5000)
        s.add_argument("--max-mcap", type=float, default=5e6, help="ignore tokens already bigger than this")
        s.add_argument("--top", type=int, default=20)
        s.add_argument("--deep", type=int, default=10, help="copycat search + Helius check for this many")
        s.add_argument("--smart-min", type=float, default=50)
        s.add_argument("--channels", help="comma-separated public Telegram channels")
        s.add_argument("--weights", help="weights JSON, default hype/weights.json")
        s.add_argument("--no-metas", action="store_true")
        s.add_argument("--x-top", type=int, default=5, help="X buzz via Apify for this many (needs APIFY_TOKEN)")
        s.add_argument("--x-min-score", type=float, default=40)
        if name == "watch":
            s.add_argument("--interval", type=int, default=120)
            s.add_argument("--alert", type=float, default=60)
    t = sub.add_parser("track")
    t.add_argument("--hours", type=float, default=48)
    e = sub.add_parser("eval")
    e.add_argument("--horizon", type=float, default=24)
    e.add_argument("--hit", type=float, default=1.0, help="max return counted as a hit, 1.0 = 2x")
    e.add_argument("--min-score", type=float, default=60)
    e.add_argument("--tp", type=float, default=1.0)
    e.add_argument("--sl", type=float, default=-0.5)
    e.add_argument("--fit", action="store_true")
    w = sub.add_parser("wallet")
    w.add_argument("address")
    w.add_argument("--pages", type=int, default=3)
    b = sub.add_parser("buyers")
    b.add_argument("mint")
    b.add_argument("--n", type=int, default=40)
    b.add_argument("--smart-min", type=float, default=50)
    l = sub.add_parser("learn")
    l.add_argument("mints", nargs="*", help="tokens that already pumped (winners)")
    l.add_argument("--auto", type=int, default=0, help="also take N recent winners from DexScreener feeds")
    l.add_argument("--auto-mcap", type=float, default=1e6)
    l.add_argument("--auto-days", type=float, default=7)
    l.add_argument("--buyer-pages", type=int, default=4, help="pages of 100 oldest swaps per winner")
    l.add_argument("--min-sol", type=float, default=0.1)
    l.add_argument("--n", type=int, default=80, help="early buyers per winner")
    l.add_argument("--min-overlap", type=int, default=1)
    l.add_argument("--max-wallets", type=int, default=25, help="Helius budget: ~3 calls per wallet")
    l.add_argument("--pages", type=int, default=2)
    l.add_argument("--skip-first-secs", type=int, default=3)
    a = p.parse_args(argv)
    {"scan": cmd_scan, "watch": cmd_watch, "track": cmd_track, "eval": cmd_eval, "wallet": cmd_wallet,
     "buyers": cmd_buyers, "learn": cmd_learn}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
