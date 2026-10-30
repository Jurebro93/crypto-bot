#!/usr/bin/env python3
"""Rug filter: is a Solana token a rug, a bundle, or fake volume?

    python3 run_rug.py token <mint>            # full report for one token
    python3 run_rug.py scan --top 10           # tokens from the newest DexScreener scan (output/dex-*.json)

Needs HELIUS_API_KEY. Writes output/rug/<mint>.md and .json, a summary output/rug-YYYY-MM-DD.md for scan,
and table rug_reports in rug.db. Wallets it looks at go to the shared wallet registry (wallets/store.py)
when that module is present.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys

from rugfilter.check import check

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
RUG_DB = os.environ.get("RUG_DB", os.path.join(HERE, "rug.db"))  # own file: one writer module per SQLite file


def _usd(x):
    x = x or 0
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:.0f}"


def _short(a):
    return f"`{a[:4]}…{a[-4:]}`" if a else "?"


def report_md(r):
    m, L, d, h, c, v = (r.get(k) or {} for k in ("market", "launch", "dev", "holders", "cluster", "volume"))
    head = f"{r['verdict']}" + (f" · {r['score']}/100" if r.get("score") is not None else "")
    lines = [f"# {r.get('symbol') or '?'} · {head}", "", f"Mint: `{r['mint']}`"]
    if m.get("url"):
        lines.append(f"[DexScreener]({m['url']}) · MCap {_usd(m.get('mcap'))} · likvidnost {_usd(m.get('liquidity'))} · "
                     f"vol 24h {_usd(m.get('vol_24h'))} · starost {m.get('age_h')} h · "
                     f"najveći ulaz za ~5% proklizavanja: {_usd(m.get('max_entry_usd_5pct'))}")
    lines.append(f"[RugCheck](https://rugcheck.xyz/tokens/{r['mint']}) · [Solscan](https://solscan.io/token/{r['mint']})")
    lines.append("")
    if r["hard_fails"]:
        lines += ["**Tvrdi filteri (odbačen):**"] + [f"- {x}" for x in r["hard_fails"]] + [""]
    if r["flags"]:
        lines += ["**Crvene zastave:**"] + [f"- {x}" for x in r["flags"]] + [""]
    if r["positives"]:
        lines += ["**Dobro:**"] + [f"- {x}" for x in r["positives"]] + [""]
    lines += ["## Detalji", "",
              "| Provjera | Vrijednost |", "| --- | --- |",
              f"| Mint / freeze authority | {r['authorities'].get('mintAuthority') or 'ugašena'} / {r['authorities'].get('freezeAuthority') or 'ugašena'} |",
              f"| Platforma | {L.get('platform') or r['rugcheck'].get('launchpad') or '?'} |",
              f"| Dev wallet | {_short(d.get('wallet'))}, tokena: {'≥' if d.get('history_capped') else ''}{d.get('tokens_created', '?')} (živih {d.get('tokens_alive', '?')}), financirao {_short(d.get('funder'))} |",
              f"| Dev na startu / prodao / prebacio / drži | {L.get('dev_initial_pct', '?')}% / {d.get('sold_pct', '?')}% / {d.get('moved_pct', '?')}% / {d.get('hold_pct', '?')}% |",
              f"| Bundle (blok kreacije) | {L.get('bundle_pct', '?')}% u {L.get('bundle_wallets', '?')} walleta |",
              f"| Snajperi (prvih ~8 s) | {L.get('sniper_pct', '?')}% u {L.get('sniper_wallets', '?')} walleta |",
              f"| Top 10 holdera (bez poola) | {h.get('top10_pct', '?')}% |",
              f"| Fresh walleti: rani kupci / top holderi | {h.get('fresh_early_pct', '?')}% / {h.get('fresh_holders_pct', '?')}% |",
              f"| Najveći klaster (isti izvor SOL-a) | {len(c.get('wallets', []))} walleta, drži {c.get('holding_pct', 0)}%, kupio na startu {c.get('early_pct', 0)}% |",
              f"| RugCheck insajderi | {r['rugcheck'].get('insider_pct')}% ({r['rugcheck'].get('insiders_detected')} walleta), holdera ukupno {r['rugcheck'].get('total_holders')} |",
              f"| Volumen (zadnjih {v.get('trades', 0)} tradeova, {v.get('span_min', 0)} min) | {v.get('wallets', 0)} walleta, wash score {r.get('wash_score')}, "
              f"kupi+prodaj isti wallet {v.get('round_trip_volume_pct')}%, top 5 {v.get('top5_volume_pct')}%, "
              f"iste veličine {v.get('repeated_size_pct')}%, botovski ritam {v.get('bot_timing_volume_pct')}% |",
              f"| Smart walleti | {len(r.get('smart_wallets', []))} |"]
    if r.get("errors"):
        lines += ["", "Izvori koji nisu radili: " + "; ".join(f"{k} ({e})" for k, e in r["errors"].items())]
    return "\n".join(lines) + "\n"


def save(r):
    os.makedirs(os.path.join(OUT, "rug"), exist_ok=True)
    base = os.path.join(OUT, "rug", r["mint"])
    with open(base + ".json", "w") as f:
        json.dump(r, f, indent=1, ensure_ascii=False)
    with open(base + ".md", "w") as f:
        f.write(report_md(r))
    con = sqlite3.connect(RUG_DB, timeout=30)
    con.execute("""CREATE TABLE IF NOT EXISTS rug_reports (
        mint TEXT, checked_at INTEGER, symbol TEXT, verdict TEXT, score REAL, wash_score REAL,
        bundle_pct REAL, sniper_pct REAL, cluster_pct REAL, top10_pct REAL, dev TEXT, data TEXT,
        PRIMARY KEY (mint, checked_at))""")
    L, c = r.get("launch") or {}, r.get("cluster") or {}
    con.execute("INSERT OR REPLACE INTO rug_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["mint"], r["checked_at"], r.get("symbol"), r["verdict"], r.get("score"), r.get("wash_score"),
                 L.get("bundle_pct"), L.get("sniper_pct"), max(c.get("holding_pct", 0), c.get("early_pct", 0)),
                 (r.get("holders") or {}).get("top10_pct"), (r.get("dev") or {}).get("wallet"), json.dumps(r)))
    con.commit()
    con.close()
    try:
        record_wallets(r)
    except sqlite3.Error as e:  # the shared registry is busy or locked: the report itself is saved
        print(f"registar walleta nije ažuriran: {e}", file=sys.stderr)


def record_wallets(r):
    """Shared wallet registry (wallets/store.py, built in the wallet-scoring thread). Skipped if absent."""
    try:
        from wallets import store as wstore
    except ImportError:
        return
    con = wstore.connect()
    # "rugger" only on hard evidence, not on every rejected token (a rejection can be low liquidity)
    d = r.get("dev") or {}
    serial = any(x.startswith("serijski kreator") for x in r["hard_fails"])
    rugger = bool((r.get("rugcheck") or {}).get("rugged") or serial or d.get("moved_pct", 0) > 20)
    bundled = (r.get("launch") or {}).get("bundle_pct", 0) > 10
    for w in r.get("wallets", []):
        wstore.observe(con, w["wallet"], token=r["mint"], source="rug", role=w["role"], ts=w.get("first_ts"),
                       extra={"funder": w.get("funder"), "fresh": w.get("fresh"), "cluster": w.get("cluster"),
                              "verdict": r["verdict"]})
        if w.get("funder"):
            wstore.observe(con, w["funder"], token=r["mint"], source="rug", role="funder", ts=w.get("first_ts"),
                           sol_in=None, extra={"funded": w["wallet"]})
        if w.get("funder") in r.get("hubs", []):
            wstore.label(con, w["funder"], "cex", True)
        if w["role"] == "dev":
            wstore.label(con, w["wallet"], "dev", True)
            if rugger:
                wstore.label(con, w["wallet"], "rugger", True)
                if w.get("funder") and w["funder"] not in r.get("hubs", []):
                    wstore.label(con, w["funder"], "funder_of_rugger", True)
        elif w["role"] == "bundler" and bundled:
            wstore.label(con, w["wallet"], "bundler", True)
        elif w.get("cluster") and rugger:
            wstore.label(con, w["wallet"], "insider", True)
    if r.get("helius_credits"):
        wstore.log_credits(con, "rug_check", r["helius_credits"])
    con.commit()
    con.close()


def scan(top, wallets, dex_file=None):
    files = [dex_file] if dex_file else sorted(glob.glob(os.path.join(OUT, "dex-[0-9]*.json")))
    if not files:
        sys.exit("Nema DexScreener skena: prvo pokreni python3 run_dex.py scan")
    with open(files[-1]) as f:
        data = json.load(f)
    # two layouts: flat "tokens" rows, or "events" each with its own ranked "tokens"
    rows = data.get("tokens") or [{**t, "event": ev.get("event")} for ev in data.get("events", [])
                                  for t in ev.get("tokens", [])]
    seen, mints = set(), []
    for row in sorted(rows, key=lambda x: (-(x.get("score") or 0), -(x.get("liquidity") or 0))):
        if row.get("chain") == "solana" and row["token"] not in seen:
            seen.add(row["token"])
            mints.append(row)
    results = []
    for row in mints[:top]:
        r = check(row["token"], wallets=wallets)
        save(r)
        r["event"] = row.get("event")
        results.append(r)
        print(f"{r['verdict']:12} {r.get('symbol', '')[:12]:12} {row['token']}", file=sys.stderr)
    order = {"PROLAZI": 0, "OPREZ": 1, "VISOK RIZIK": 2, "ODBAČEN": 3}
    results.sort(key=lambda r: (order[r["verdict"]], -(r.get("score") or 0)))
    lines = [f"# Rug filter {dt.date.today()} ({len(results)} tokena iz {os.path.basename(files[-1])})", "",
             "| Presuda | Token | Događaj | Likvidnost | Bundle | Snajperi | Klaster | Wash | Glavni razlog |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        L, c, m = r.get("launch") or {}, r.get("cluster") or {}, r.get("market") or {}
        why = (r["hard_fails"] or r["flags"] or r["positives"] or [""])[0]
        lines.append(f"| {r['verdict']}{' ' + str(r['score']) if r.get('score') is not None else ''} | "
                     f"[{r.get('symbol')}](rug/{r['mint']}.md) | {r.get('event') or ''} | {_usd(m.get('liquidity'))} | "
                     f"{L.get('bundle_pct', '?')}% | {L.get('sniper_pct', '?')}% | "
                     f"{max(c.get('holding_pct', 0), c.get('early_pct', 0))}% | {r.get('wash_score')} | {why} |")
    md = "\n".join(lines) + "\n"
    with open(os.path.join(OUT, f"rug-{dt.date.today()}.md"), "w") as f:
        f.write(md)
    return md


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("token")
    t.add_argument("mint")
    s = sub.add_parser("scan")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--dex", help="DexScreener scan file, default the newest output/dex-YYYY-MM-DD.json")
    for x in (t, s):
        x.add_argument("--wallets", type=int, default=20, help="how many early buyers + holders to profile")
    a = p.parse_args(argv)
    if a.cmd == "token":
        r = check(a.mint, wallets=a.wallets)
        save(r)
        print(report_md(r))
    else:
        print(scan(a.top, a.wallets, a.dex))
    return 0


if __name__ == "__main__":
    sys.exit(main())
