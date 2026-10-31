"""Wallet registry, scoring, PnL tracking and the copytrading shortlist.

    python3 run_wallets.py harvest                 # wallets from all analyses (hype, DexScreener, events) into the registry
    python3 run_wallets.py score --credits 3000    # score / recheck wallets from the queue within a Helius budget
    python3 run_wallets.py top                     # ranking (--style sniper, --by score)
    python3 run_wallets.py top --signals           # profitable bots/snipers: followed as a signal, not copied
    python3 run_wallets.py copy --n 5              # copytrading shortlist, writes output/wallets-copy-<date>.md
    python3 run_wallets.py wallet <address>        # score one wallet now, with open/closed positions
    python3 run_wallets.py history <address>       # score and PnL over time
    python3 run_wallets.py label <address> rugger  # manual label (--off to remove)
    python3 run_wallets.py credits                 # Helius credits used by this module this month
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time

from dexscreener import client
from wallets import pnl, rpc
from wallets import store as wstore

HERE = os.path.dirname(os.path.abspath(__file__))
HYPE_DB = os.path.join(HERE, "hype.db")
OUT = os.path.join(HERE, "output")
LOOKBACK_D = 30
MONTHLY = int(os.environ.get("HELIUS_MONTHLY_CREDITS", "10000000"))
SHARE = float(os.environ.get("WALLET_CREDIT_SHARE", "0.15"))  # 1.5M of Helius Developer's 10M; rest: rug, hype


def _month_start():
    d = dt.datetime.now(dt.timezone.utc)
    return int(dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp())


def _credit_logger(con, method, wallet=None):
    spent = []

    def log(n):
        spent.append(n)
        wstore.log_credits(con, method, n, wallet)
    log.spent = spent
    return log


# ---------- harvest ----------

def _harvest_tokens(con, a):
    toks = {}
    since = int(time.time()) - a.days * 86400
    if os.path.exists(HYPE_DB):
        h = sqlite3.connect(HYPE_DB)
        try:
            for (t,) in h.execute("SELECT DISTINCT token FROM hype_signals WHERE ts >= ? AND score >= ?",
                                  (since, a.min_signal)):
                toks.setdefault(t, set()).add("hype_signal")
        except sqlite3.OperationalError:
            pass
    try:
        for (t,) in con.execute("SELECT DISTINCT token FROM event_tokens WHERE chain='solana'"):
            toks.setdefault(t, set()).add("event")
    except sqlite3.OperationalError:
        pass
    if a.feeds:
        from run_hype import candidates
        for t in candidates({}, use_metas=True):
            toks.setdefault(t, set()).add("dex_feed")
    for t in a.mints:
        toks.setdefault(t, set()).add("manual")
    return toks


def cmd_harvest(a):
    con = wstore.connect()
    n = wstore.import_hype(con, HYPE_DB)
    con.commit()
    print(f"iz hype.db smart_wallets: {n} viđenja")
    n = wstore.import_seed(con)
    print(f"seed_retro.json: {n} walleta")
    n = wstore.import_kol(con)
    con.commit()
    m = wstore.import_corr(con)
    con.commit()
    print(f"iz corr.db praćene grupe walleta (Korelacije): {m} walleta")
    print(f"iz kol.db rotacijski devovi (prodaju u KOL pozive na 3+ tokena): {n} walleta")
    toks = _harvest_tokens(con, a)
    now_ms = time.time() * 1000
    winners = {}
    for p in client.tokens("solana", list(toks)):
        t = p["baseToken"]["address"]
        age_d = (now_ms - (p.get("pairCreatedAt") or now_ms)) / 8.64e7
        mc = p.get("marketCap") or p.get("fdv") or 0
        if mc >= a.min_mcap and age_d <= a.max_age_d:
            winners[t] = max(winners.get(t, 0), mc)
    picked = sorted(winners, key=lambda t: -winners[t])[:a.tokens]
    print(f"{len(toks)} tokena iz analiza, {len(winners)} pobjednika (mcap >= ${a.min_mcap:,.0f}); "
          f"uzimam rane kupce za {len(picked)}")
    log = _credit_logger(con, "early_buyers")
    for t in picked:
        try:
            buyers = rpc.early_buyers(t, a.buyers, a.pages, on_credits=log)
        except Exception as e:
            print(f"  {t}: {e}", file=sys.stderr)
            continue
        for b in buyers:
            if b["creator_tx"]:
                role = "dev"
            elif b["same_slot"] or b["secs_after_first"] <= a.sniper_secs:
                role = "sniper"
            elif b["sol_in"] < a.min_sol:
                role = "dust"
            else:
                role = "early_buyer"
            wstore.observe(con, b["wallet"], t, "harvest", role, b["ts"], b["sol_in"],
                           {"secs_after_first": b["secs_after_first"], "mcap_now": winners[t]})
        con.commit()
        print(f"  {t}  {len(buyers)} kupaca  mcap ${winners[t]:,.0f}")
    print(f"potrošeno {sum(log.spent)} Helius kredita")
    tot = con.execute("SELECT COUNT(*), SUM(scored_at IS NOT NULL) FROM wallets").fetchone()
    print(f"registar: {tot[0]} walleta, ocijenjeno {tot[1] or 0}")


# ---------- scoring ----------

def score_one(con, wallet, max_pages=3, now=None, verbose=False):
    now = int(now or time.time())
    row = con.execute("SELECT last_tx_ts, history_from FROM wallets WHERE wallet=?", (wallet,)).fetchone()
    log = _credit_logger(con, "wallet_history", wallet)
    if row and row[0]:  # recheck: only what's new since the last tx we stored
        rows, complete, newest, _ = rpc.wallet_swaps(wallet, since_ts=row[0], max_pages=max_pages + 2,
                                                     oldest_first=True, on_credits=log)
        history_from = None
    else:
        rows, complete, newest, oldest = rpc.wallet_swaps(wallet, since_ts=now - LOOKBACK_D * 86400,
                                                          max_pages=max_pages, on_credits=log)
        history_from = now - LOOKBACK_D * 86400 if complete else oldest
    wstore.save_trades(con, wallet, rows)
    hist = con.execute("SELECT history_from FROM wallets WHERE wallet=?", (wallet,)).fetchone()[0] or history_from or 0
    trades = wstore.trades(con, wallet, since=max(hist, now - 2 * LOOKBACK_D * 86400))
    pos = pnl.positions(trades)
    open_mints = [m for m, p in pos.items() if p["status"] == "open"]
    prices, _ = pnl.prices_sol(open_mints, client) if open_mints else ({}, 150.0)
    pos = pnl.positions(trades, prices)
    s = pnl.score(pos, trades, now, wstore.labels(con, wallet))
    wins = {t for (t,) in con.execute("SELECT DISTINCT token FROM wallet_sightings WHERE wallet=? AND role IN "
                                      "('early_buyer','smart','top_trader')", (wallet,))}
    s["early_in_winners"] = len(wins)
    if s["copy_score"] and len(wins) > 1:  # early in several winners: +5 per extra winner, max +15
        s["copy_score"] = min(100, s["copy_score"] + 5 * min(3, len(wins) - 1))
    if s["bot"]:
        wstore.label(con, wallet, "bot")
    t, nxt = pnl.tier(s)
    s["credits"] = sum(log.spent)
    wstore.save_score(con, wallet, s, t, now + nxt if nxt else None, newest, history_from, s["credits"])
    con.commit()
    return s, t, pos


def _fmt(w, s, t):
    return (f"{t} {s['copy_score']:>3} {s['score']:>3}  {w}  pnl {s['closed_pnl_sol']:+8.2f} SOL  "
            f"roi {s['roi_on_cost']:+.0%}  win {s['win_rate']:.0%} ({s['closed']})  2x+ {s['big_wins']}  "
            f"open {s['unrealized_sol']:+.2f}  hold {s['median_hold_min']}m  {s['trades_per_day']}/d")


def cmd_score(a):
    con = wstore.connect()
    used = wstore.credits_since(con, _month_start())
    left = min(a.credits, MONTHLY * SHARE - used)
    if left <= 0:
        print(f"mjesečni budžet potrošen ({used} kredita)")
        return
    q = wstore.queue(con, a.max)
    print(f"u redu {len(q)} walleta, budžet {left:.0f} kredita (ovaj mjesec potrošeno {used})")
    spent = 0
    for w, scored in q:
        if spent + 10 * (a.pages + 2) > left:
            print("budžet za ovaj prolaz potrošen")
            break
        try:
            s, t, _ = score_one(con, w, a.pages)
        except Exception as e:
            print(f"  {w}: {e}", file=sys.stderr)
            continue
        spent += s["credits"]
        print(("  re " if scored else "  new ") + _fmt(w, s, t))
    print(f"potrošeno {spent} kredita")


def _rows(con, order, n, where="1=1"):
    cur = con.execute(f"SELECT wallet, tier, stats, labels, sources FROM wallets WHERE stats IS NOT NULL AND {where} "
                      f"ORDER BY {order} DESC LIMIT ?", (n,))
    return [(w, t, json.loads(s), json.loads(lab or "[]"), json.loads(src or "{}")) for w, t, s, lab, src in cur]


def cmd_top(a):
    con = wstore.connect()
    print("tier copy score")
    where = "tier='S'" if a.signals else "1=1"
    rows = _rows(con, "score" if a.signals or a.by == "score" else "copy_score", 1000, where)
    if a.style:
        rows = [r for r in rows if r[2].get("style") == a.style]
    for w, t, s, lab, _ in rows[:a.n]:
        print(_fmt(w, s, t) + f"  {s.get('style', '?')}" + (f"  [{','.join(lab)}]" if lab else ""))


def cmd_copy(a):
    con = wstore.connect()
    picks = []
    for w, t, s, lab, src in _rows(con, "copy_score", 200, "copy_score > 0"):
        if set(lab) & wstore.BAD_LABELS or s["closed"] < a.min_closed or s["copy_score"] < a.min_score:
            continue
        picks.append((w, t, s, src))
        if len(picks) >= a.n:
            break
    today = dt.date.today().isoformat()
    lines = [f"# Kandidati za copytrading ({today})", "",
             f"Uvjeti: copy ocjena >= {a.min_score}, barem {a.min_closed} zatvorenih pozicija u zadnjih "
             f"{LOOKBACK_D}-60 dana, bez oznaka {', '.join(sorted(wstore.BAD_LABELS))}.", "",
             "| # | Wallet | Copy | Ocjena | PnL (SOL) | ROI | Win | 2x+ | Drži (min) | Kupnja (SOL) | Trejd/dan | Pobjednici | Napomene |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, (w, t, s, src) in enumerate(picks, 1):
        lines.append(f"| {i} | [`{w[:6]}…{w[-4:]}`](https://gmgn.ai/sol/address/{w}) | {s['copy_score']} | {s['score']} | "
                     f"{s['closed_pnl_sol']:+.1f} | {s['roi_on_cost']:+.0%} | {s['win_rate']:.0%} ({s['closed']}) | "
                     f"{s['big_wins']} | {s['median_hold_min']} | {s['median_buy_sol']} | {s['trades_per_day']} | "
                     f"{s.get('early_in_winners', 0)} | {', '.join(s.get('copy_notes') or []) or '-'} |")
    if not picks:
        lines.append("| - | još nema walleta koji prolaze uvjete | | | | | | | | | | | |")
    lines += ["", "Puna adresa: " + ", ".join(f"`{w}`" for w, *_ in picks) if picks else ""]
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"wallets-copy-{today}.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n-> {path}")


def cmd_wallet(a):
    con = wstore.connect()
    wstore.observe(con, a.address, None, "manual", "manual")
    s, t, pos = score_one(con, a.address, a.pages)
    print(_fmt(a.address, s, t))
    print(json.dumps({k: v for k, v in s.items()}, indent=1, ensure_ascii=False))
    rows = sorted((p for p in pos.values() if p["status"] in ("open", "closed")), key=lambda p: -(p["last_ts"] or 0))
    for p in rows[:a.show]:
        print(f"  {p['status']:<6} {p['mint']}  ulog {p['cost']:.3f}  realiz. {p['realized']:+.3f}  "
              f"nerealiz. {p['unrealized'] if p['unrealized'] is None else round(p['unrealized'], 3)}  "
              f"roi {p['roi']:+.0%}")


def cmd_history(a):
    con = wstore.connect()
    for ts, r, u, wr, c, sc, cs in con.execute("SELECT ts, realized_sol, unrealized_sol, win_rate, closed, score, "
                                               "copy_score FROM wallet_pnl WHERE wallet=? ORDER BY ts", (a.address,)):
        print(f"{dt.datetime.fromtimestamp(ts, dt.timezone.utc):%Y-%m-%d %H:%M}  realiz. {r:+.2f}  nerealiz. {u:+.2f}  "
              f"win {wr:.0%} ({c})  ocjena {sc}  copy {cs}")


def cmd_label(a):
    con = wstore.connect()
    wstore.label(con, a.address, a.name, not a.off)
    con.commit()
    print(sorted(wstore.labels(con, a.address)))


def cmd_credits(a):
    con = wstore.connect()
    ms = _month_start()
    used = wstore.credits_since(con, ms)
    day = max(1, (time.time() - ms) / 86400)
    print(f"ovaj mjesec: {used} kredita ({used / MONTHLY:.1%} od {MONTHLY:,}), tempo {used / day * 30:,.0f}/mj")
    for m, c, n in con.execute("SELECT method, SUM(credits), COUNT(*) FROM helius_credits WHERE ts>=? GROUP BY method",
                               (ms,)):
        print(f"  {m:<16} {c:>8} kredita  {n} poziva")
    tiers = dict(con.execute("SELECT tier, COUNT(*) FROM wallets WHERE tier IS NOT NULL GROUP BY tier"))
    print(f"tierovi: {tiers}; walleta ukupno {con.execute('SELECT COUNT(*) FROM wallets').fetchone()[0]}")
    per_day = 10 * (4 * tiers.get("A", 0) + tiers.get("B", 0) + tiers.get("C", 0) / 7)
    print(f"procjena: rechecks ~{per_day:,.0f} kredita/dan (A 4x dnevno, B dnevno, C tjedno, po 10 kredita)")


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("harvest")
    h.add_argument("mints", nargs="*")
    h.add_argument("--days", type=int, default=7, help="hype signals from the last N days")
    h.add_argument("--min-signal", type=float, default=40)
    h.add_argument("--feeds", action="store_true", help="also DexScreener feeds (profiles, boosts, metas)")
    h.add_argument("--min-mcap", type=float, default=1e6)
    h.add_argument("--max-age-d", type=float, default=14)
    h.add_argument("--tokens", type=int, default=10, help="winners to pull buyers for (~10-20 credits each)")
    h.add_argument("--buyers", type=int, default=60)
    h.add_argument("--pages", type=int, default=2)
    h.add_argument("--sniper-secs", type=int, default=3)
    h.add_argument("--min-sol", type=float, default=0.1)
    s = sub.add_parser("score")
    s.add_argument("--credits", type=int, default=20000, help="Helius credits for this run")
    s.add_argument("--max", type=int, default=100)
    s.add_argument("--pages", type=int, default=3, help="first look: up to N x 100 txs (10 credits per page)")
    t = sub.add_parser("top")
    t.add_argument("--n", type=int, default=30)
    t.add_argument("--by", choices=("copy", "score"), default="copy")
    t.add_argument("--style", choices=("bot", "sniper", "scalper", "swing"))
    t.add_argument("--signals", action="store_true", help="tier S: profitable bots/snipers, signal not copy")
    c = sub.add_parser("copy")
    c.add_argument("--n", type=int, default=5)
    c.add_argument("--min-score", type=float, default=50)
    c.add_argument("--min-closed", type=int, default=10)
    w = sub.add_parser("wallet")
    w.add_argument("address")
    w.add_argument("--pages", type=int, default=3)
    w.add_argument("--show", type=int, default=15)
    hi = sub.add_parser("history")
    hi.add_argument("address")
    lb = sub.add_parser("label")
    lb.add_argument("address")
    lb.add_argument("name")
    lb.add_argument("--off", action="store_true")
    sub.add_parser("credits")
    a = p.parse_args(argv)
    {"harvest": cmd_harvest, "score": cmd_score, "top": cmd_top, "copy": cmd_copy, "wallet": cmd_wallet,
     "history": cmd_history, "label": cmd_label, "credits": cmd_credits}[a.cmd](a)


if __name__ == "__main__":
    main()
