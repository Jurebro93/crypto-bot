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
from hype import apify, evaluate, onchain, score, sources, store, telegram, xbuzz

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


def candidates(tg_cas, use_metas=True, pump=None, kol_cas=()):
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
    for mint, t in (pump or {}).items():
        for b in t["boards"]:
            add(mint, f"pumpfun:{b}")
    for ca in kol_cas:
        add(ca, "kol_x")
    return found


def apify_context(a):
    """Everything the paid sources add to one scan; each part fails (or hits its budget) on its own."""
    ctx = {"pump": {}, "trend_keys": {}, "trends": [], "errors": {}}
    if not apify.enabled() or a.no_apify:
        return ctx
    for name, fn in (("pumpfun", sources.pumpfun_tokens), ("x_trends", sources.x_trends)):
        try:
            ctx["pump" if name == "pumpfun" else "trends"] = fn()
        except Exception as e:
            ctx["errors"][name] = f"{type(e).__name__}: {e}"
    ctx["trend_keys"] = sources.trend_keys(ctx["trends"])
    try:
        con = store.connect(DB)
        sources.gmgn_wallets(con)  # cached 24 h, so this is one paid run per day
        con.close()
    except Exception as e:
        ctx["errors"]["gmgn"] = f"{type(e).__name__}: {e}"
    return ctx


def early_buyers_cheap(mint, n=60):
    """getTransactionsForAddress (~10 credits per 100 tx) instead of the Enhanced API (~100 per call)."""
    try:
        from wallets import rpc
        return rpc.early_buyers(mint, n=n, max_pages=1)
    except ImportError:
        return onchain.early_buyers(mint, n=n, pages=1)


def scan(a, weights, smart, tg_count, now=None, kol=({}, {})):
    now_ms = (now or time.time()) * 1000
    ctx = apify_context(a)
    for k, v in ctx["errors"].items():
        print(f"  apify {k}: {v}", file=sys.stderr)
    kol_ca, kol_tk = kol
    found = candidates(tg_count, use_metas=not a.no_metas, pump=ctx["pump"], kol_cas=list(kol_ca))
    pairs = client.tokens("solana", list(found))
    best = {}
    for p in pairs:
        t = p["baseToken"]["address"]
        if t in found and ((p.get("liquidity") or {}).get("usd") or 0) > ((best.get(t, {}).get("liquidity") or {}).get("usd") or 0):
            best[t] = p
    cal = calendar_keywords()
    regime = market_regime(now_ms / 1000)  # same for every token in the scan: context, learned like any feature
    rows, skipped = [], []
    for t, p in best.items():
        liq, mcap = (p.get("liquidity") or {}).get("usd") or 0, p.get("marketCap") or p.get("fdv") or 0
        if liq < a.min_liq or mcap > a.max_mcap:
            # not scored, but remembered and price-tracked: the learning loop must see what the thresholds miss
            skipped.append((t, p["baseToken"].get("symbol", ""), mcap, liq, (now_ms - (p.get("pairCreatedAt") or now_ms)) / 3.6e6,
                            f"likvidnost {_usd(liq)} < {_usd(a.min_liq)}" if liq < a.min_liq else f"mcap {_usd(mcap)} > {_usd(a.max_mcap)}"))
            continue
        f = score.market_features(p, now_ms)
        sym, name = p["baseToken"].get("symbol", ""), p["baseToken"].get("name", "")
        f["takeover"] = 1.0 if {"takeover", "profile_update"} & found[t] and f["revival"] > 0 else 0.0
        f["calendar"] = 1.0 if {score._norm(sym), score._norm(name)} & cal else 0.0
        f["telegram"] = min(1.0, tg_count.get(t, 0) / 3)
        if regime is not None:
            f["market_regime"] = regime
        # narrative, smart_money, x_buzz and search_trend are only set for tokens the deep checks reach
        pf = ctx["pump"].get(t) or {}
        if pf:
            f["kol_wallets"] = min(1.0, (pf.get("kolCount") or 0) / 5)  # pump.fun: known KOL wallets traded it
        trend = sources.trend_match(sym, name, ctx["trend_keys"])
        if ctx["trend_keys"]:
            f["x_trend"] = 1.0 if trend else 0.0
        if kol_ca or kol_tk:
            f["kol_x"] = min(1.0, max(kol_ca.get(t, 0), kol_tk.get(sym.upper(), 0)) / 2)
        extra = {"x_trend": trend, "pumpfun": {k: pf.get(k) for k in (
            "boards", "kolCount", "holders", "top10HoldersPercent", "bundlerOwnedPercent", "snipersOwnedPercent",
            "devHoldingsPercent", "bondingCurveProgress", "twitterReuseCount", "pumpFunUrl")} if pf else None,
            "kol_x": kol_ca.get(t, 0)}
        rows.append({"token": t, "symbol": sym, "name": name, "pair": p.get("pairAddress"), "url": p.get("url"),
                     "price": float(p.get("priceUsd") or 0), "mcap": mcap, "liquidity": liq,
                     "sources": found[t], "features": f, "score": score.score(f, weights), "raw": p,
                     "extra": extra})
    tiers_for(rows, now_ms / 1000)  # class, path shape, T0 sieve
    wcls = class_weights(rows, weights)  # learned weights per class (learn/), else the base file
    for r in rows:
        r["score"] = score.score(r["features"], wcls[r["tier"]["klasa"]])
    rows.sort(key=lambda r: -r["score"])
    # expensive checks only for the best pre-scored candidates that passed the free sieve
    deep = [r for r in rows if r["tier"]["t0"] != "pad"][:a.deep]
    for r in deep:
        try:
            r["copycats"] = score.copycats(client.search(r["symbol"]), r["symbol"], r["name"], r["token"], now_ms)
            r["features"]["narrative"] = min(1.0, r["copycats"] / 8)
        except Exception as e:
            print(f"  search {r['symbol']}: {e}", file=sys.stderr)
        r["features"].setdefault("narrative", 0.0)
        if smart and os.environ.get("HELIUS_API_KEY"):
            try:
                buyers = early_buyers_cheap(r["token"])
                r["smart_buyers"] = [b["wallet"] for b in buyers if b["wallet"] in smart]
                r["features"]["smart_money"] = min(1.0, len(r["smart_buyers"]) / 4)
                r["tier"].update(razina=max(r["tier"]["razina"], 1), credits=r["tier"].get("credits", 0) + 10)
            except Exception as e:
                print(f"  helius {r['symbol']}: {e}", file=sys.stderr)
        r["score"] = score.score(r["features"], wcls[r["tier"]["klasa"]])
    if apify.enabled() and not a.no_apify:  # paid: only tokens that already look good and passed T0
        rows.sort(key=lambda r: -r["score"])
        ok = [r for r in rows if r["tier"]["t0"] != "pad"]
        for r in [r for r in ok if r["score"] >= a.x_min_score][:a.x_top]:
            try:
                r["x"] = xbuzz.token_buzz(r["token"], r["symbol"])
                r["features"]["x_buzz"] = r["x"]["feature"]
                r["tier"]["razina"] = max(r["tier"]["razina"], 2)
            except Exception as e:
                print(f"  x_buzz {r['symbol']}: {e}", file=sys.stderr)
        gt = apify.config()["google_trends"]
        for r in [r for r in ok if r["score"] >= gt["min_score"] and len(r["name"]) >= 3][:gt["per_scan"]]:
            try:
                rise = sources.search_rise(r["name"])
                r["extra"]["search_rise"] = rise
                r["features"]["search_trend"] = max(0.0, min(1.0, ((rise or 1) - 1) / 2))
            except Exception as e:
                print(f"  google_trends {r['symbol']}: {e}", file=sys.stderr)
        for r in rows:
            r["score"] = score.score(r["features"], wcls[r["tier"]["klasa"]])
    rows.sort(key=lambda r: -r["score"])
    con = store.connect(DB)  # fresh handle: a connection held across minutes of HTTP goes stale on the shared mount
    for r in rows:
        store.log_signal(con, r, wcls[r["tier"]["klasa"]])
        store.snapshot(con, r["token"], r["price"], r["mcap"], r["liquidity"])
        store.log_details(con, r)
    con.commit()
    save_tiers(rows, skipped, now_ms / 1000)
    return rows


def market_regime(now):
    """0-1 from market.db (how hot the launchpad/DEX market was yesterday), None when there is no data yet."""
    try:
        from market import regime
        return regime.feature(now)
    except Exception as e:
        print(f"  market regime: {e}", file=sys.stderr)
        return None


def class_weights(rows, base):
    try:
        from learn import weights as lw
        out = lw.for_rows(rows, base)
    except Exception as e:
        print(f"  learned weights: {e}", file=sys.stderr)
        out = {}
    return {**{r["tier"]["klasa"]: base for r in rows}, **out} if rows else {}


def tiers_for(rows, now=None):
    """Attach r["tier"] to every scored row: class, shape of the mcap path, T0 verdict (cached 24 h in token_tier)."""
    from tiers import classify, sieve
    from tiers import store as tstore
    cfg = classify.config()
    now = now or time.time()
    con = tstore.connect(DB)
    for r in rows:
        cur = tstore.get(con, r["token"]) or {}
        snaps = con.execute("SELECT ts, mcap FROM hype_snapshots WHERE token=? ORDER BY ts", (r["token"],)).fetchall()
        shape = classify.put([(s[0], s[1]) for s in snaps] + [(int(now or time.time()), r["mcap"])])
        age_h = (now * 1000 - (r["raw"].get("pairCreatedAt") or 0)) / 3.6e6 if r["raw"].get("pairCreatedAt") else None
        role = "canonical" if r["features"].get("calendar") else None
        t0, why, t0_ts = cur.get("t0"), cur.get("t0_razlog"), cur.get("t0_ts")
        if sieve.needs_check(cur, cfg, now):
            t0, why = sieve.check(r["token"], cfg)
            t0_ts = int(now or time.time())
        r["features"].update(classify.put_features(shape))
        r["tier"] = {"razina": cur.get("razina") or 0, "klasa": classify.klasa(r["mcap"], age_h, role, cfg),
                     "t0": t0, "t0_razlog": why, "t0_ts": t0_ts, "age_h": age_h, "credits": 0, **shape}
    con.close()


def save_tiers(rows, skipped=(), now=None):
    from tiers import store as tstore
    con = tstore.connect(DB)
    for r in rows:
        t = r["tier"]
        tstore.upsert(con, r["token"], now, symbol=r["symbol"], razina=t["razina"], klasa=t["klasa"], t0=t["t0"],
                      t0_razlog=t["t0_razlog"], t0_ts=t["t0_ts"], mcap=r["mcap"], liquidity=r["liquidity"],
                      age_h=t["age_h"], score=r["score"], credits=t["credits"], put_brzina=t["put_brzina"],
                      put_skokovitost=t["put_skokovitost"], put_zadrzavanje=t["put_zadrzavanje"])
    for t, sym, mcap, liq, age_h, why in skipped:
        tstore.upsert(con, t, now, symbol=sym, t0="nije", t0_razlog=why, mcap=mcap, liquidity=liq, age_h=age_h,
                      razlog=f"izvan skena: {why}")
    con.commit()
    con.close()


def track(hours=48):
    since = int(time.time() - hours * 3600)
    con = store.connect(DB)
    tokens = {t for (t,) in con.execute("SELECT DISTINCT token FROM hype_signals WHERE ts >= ?", (since,))}
    try:  # tokens the scan saw but did not score (too small, too big, T0 fail) are tracked too: outcomes for learning
        from tiers import store as tstore
        tokens |= set(tstore.recent_tokens(tstore.connect(DB), hours))
    except Exception as e:
        print(f"  token_tier: {e}", file=sys.stderr)
    tokens = sorted(tokens)
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
    if r.get("extra", {}).get("x_trend"):
        extra.append(f"X trend: {r['extra']['x_trend']}")
    if r["features"].get("kol_wallets"):
        extra.append(f"KOL walleti: {r['extra']['pumpfun']['kolCount']}")
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
    kol = sources.kol_counts(con)
    con.close()
    try:  # profitable wallets from the shared registry, bots and snipers included (they are a signal too)
        from wallets import store as wstore
        smart |= set(wstore.signal_wallets(wstore.connect(), a.smart_min))
    except Exception as e:
        print(f"wallets.db: {e}", file=sys.stderr)
    rows = scan(a, w, smart, tg, kol=kol)
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


def cmd_kol(a):
    """Start or stop the X KOL monitor (Apify xquik). Each account costs ~$3.24/month while it runs; the tweets
    arrive at run_ui.py's /hook/kol and feed the kol_x signal. Needs a daily budget for kol_monitor in apify.json."""
    handles = [h.strip().lstrip("@") for h in (a.handles or ",".join(apify.config().get("kol_handles", []))).split(",") if h.strip()]
    key = os.environ.get("KOL_HOOK_KEY")
    if not (handles or a.stop) or not key or not a.base_url:
        sys.exit("Treba: --handles (ili kol_handles u hype/apify.json), --base-url javnog dashboarda i KOL_HOOK_KEY.")
    hook = f"{a.base_url.rstrip('/')}/hook/kol?key={urllib.parse.quote(key)}"
    print(sources.kol_monitor(handles, hook, stop=a.stop))


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
        s.add_argument("--x-min-score", type=float, default=30)
        s.add_argument("--no-apify", action="store_true", help="skip every paid Apify source")
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
    k = sub.add_parser("kol")
    k.add_argument("--handles", help="X accounts, comma-separated (default kol_handles in hype/apify.json)")
    k.add_argument("--base-url", default=os.environ.get("PUBLIC_URL"), help="e.g. https://crypto-bot-ylvn.onrender.com")
    k.add_argument("--stop", action="store_true")
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
     "buyers": cmd_buyers, "learn": cmd_learn, "kol": cmd_kol}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
