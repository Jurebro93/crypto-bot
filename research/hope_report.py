"""The analysis lines of the Hope research (research/hope.py wrote DATA_DIR/research/hope-20261110.json; the whole JSON
is too big to read back from the log). Prints plain "HOPE-A | ..." lines, once (marker .report.done): today's
timeline, the biggest early wallets, who sold into Marko's call, the wallets that spread tokens to others, the top
holders and what we know about them, tiers and linked accounts, same-slot groups of today. READ ONLY.

    python3 -m research.hope_report [--force]
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SUPPLY = 1e9
TODAY0 = 1794268800   # 10.11.2026 00:00 UTC


def _t(ts):
    return time.strftime("%H:%M:%S", time.gmtime(ts + 3600)) if ts else "–"   # CET


def _w(w):
    return (w or "")[:6] + "…"


def lines(r):
    W = r["wallets"]
    by = {w["wallet"]: w for w in W}
    marko = (r.get("marko_call") or {}).get("ts") or 0
    migr = r["migration_ts"]
    out = [f"token {r['token']} · transakcija {r['n_trades']} · novčanika {r['n_wallets']} · SOL/USD {r['sol_usd']:.0f} · "
           f"migracija {_t(migr)} CET · Marko {_t(marko)} CET · potpuno {r.get('complete')}"]
    # 1) today's timeline in 15-min buckets (first buys)
    out.append("## Vremenska crta danas (prve kupnje po 15 min, CET): novih novčanika, SOL uloženo, medijan MC")
    buckets = {}
    for w in W:
        fb = w.get("first_buy_ts") or 0
        if fb >= TODAY0:
            b = fb - fb % 900
            x = buckets.setdefault(b, [0, 0.0, []])
            x[0] += 1
            x[1] += w["sol_in"]
            if w.get("first_buy_mc"):
                x[2].append(w["first_buy_mc"])
    for b in sorted(buckets):
        n, sol, mcs = buckets[b]
        mcs.sort()
        out.append(f"{_t(b)[:5]} novih {n} · {sol:.1f} SOL · MC {mcs[len(mcs) // 2] if mcs else 0:,.0f}")
    # 2) biggest early wallets (today, before Marko)
    early = [w for w in W if TODAY0 <= (w.get("first_buy_ts") or 0) < (marko or 9e12)]
    out.append(f"## Najveći rani novčanici danas prije Marka ({len(early)}), po uloženom SOL-u")
    for w in sorted(early, key=lambda w: -w["sol_in"])[:30]:
        held = w["net_tok"] / SUPPLY * 100
        fs = w.get("first_sell_ts")
        rel = f"{(fs - marko) / 60:+.0f} min od Marka" if fs and marko else "nije prodao"
        tags = " ".join(x for x in (f"tier {w['tier']}" if w.get("tier") else "",
                                    f"račun {(w.get('x_or_tg') or {}).get('x') or (w.get('x_or_tg') or {}).get('tg')}"
                                    if w.get("x_or_tg") else "",
                                    f"poslao na {len(w.get('sent_to') or [])}" if w.get("sent_to") else "",
                                    f"primio od {len(w.get('received_from') or [])}" if w.get("received_from") else "") if x)
        out.append(f"{_w(w['wallet'])} {_t(w['first_buy_ts'])} {w.get('first_buy_venue')} MC {w.get('first_buy_mc') or 0:,.0f} · "
                   f"uložio {w['sol_in']:.2f} · dobio {w['sol_out']:.2f} · {w['pnl_sol']:+.2f} SOL · prva prodaja {rel} · "
                   f"drži {held:.2f} % · {w['buys']}/{w['sells']} k/p {tags}")
    # 3) who sold into the call
    if marko:
        into = [w for w in early if w.get("first_sell_ts") and marko <= w["first_sell_ts"] <= marko + 3600]
        pre = [w for w in early if w.get("first_sell_ts") and w["first_sell_ts"] < marko]
        out.append(f"## Prodali u Markov poziv (prva prodaja 0-60 min nakon): {len(into)} novčanika, dobili "
                   f"{sum(w['sol_out'] for w in into):.1f} SOL, rezultat {sum(w['pnl_sol'] for w in into):+.1f}; prodali već prije "
                   f"poziva: {len(pre)}, {sum(w['pnl_sol'] for w in pre):+.1f} SOL")
        for w in sorted(into, key=lambda w: -w["sol_out"])[:15]:
            out.append(f"{_w(w['wallet'])} kupio {_t(w['first_buy_ts'])} MC {w.get('first_buy_mc') or 0:,.0f}, prodao "
                       f"{(w['first_sell_ts'] - marko) / 60:+.0f} min, {w['sol_in']:.2f} → {w['sol_out']:.2f} SOL")
    # 4) wallets that spread tokens
    send = sorted((w for w in W if len(w.get("sent_to") or []) >= 2), key=lambda w: -len(w["sent_to"]))
    recv = [w for w in W if w.get("received_from")]
    held_recv = sum(max(0, w["net_tok"]) for w in recv) / SUPPLY * 100
    out.append(f"## Raspodjela: {len(send)} novčanika poslalo tokene na 2+ druga, {len(recv)} primilo bez kupnje ili uz nju; "
               f"primatelji danas drže {held_recv:.2f} % supplyja")
    for w in send[:15]:
        rs = [by[x] for x in w["sent_to"] if x in by]
        still = sum(max(0, x["net_tok"]) for x in rs) / SUPPLY * 100
        sold = sum(1 for x in rs if x["sells"])
        out.append(f"{_w(w['wallet'])} faza {w['phase']} · prva kupnja {_t(w.get('first_buy_ts'))} · uložio {w['sol_in']:.2f} SOL · "
                   f"poslao {w['sent_tok'] / SUPPLY * 100:.2f} % na {len(w['sent_to'])} novčanika · primatelji drže {still:.2f} %, "
                   f"prodalo ih {sold}, primatelji dobili {sum(x['sol_out'] for x in rs):.2f} SOL")
    # 5) top holders
    out.append("## Top 20 holdera i što znamo o njima")
    for h in r.get("holders_top20") or []:
        w = by.get(h.get("owner"))
        if w:
            src = (f"faza {w['phase']}, uložio {w['sol_in']:.2f}, primio od {len(w.get('received_from') or [])}"
                   + (f", tier {w['tier']}" if w.get("tier") else ""))
        else:
            src = "nema ga među trgovcima krivulje/poola (pool, CEX ili samo prijenosi)"
        out.append(f"{_w(h.get('owner'))} {h.get('pct')} % · {src}")
    # 6) tiers and accounts
    known = [w for w in W if w.get("tier") or w.get("x_or_tg") or w.get("followed_live")]
    out.append(f"## Poznati novčanici (tier / račun / praćen): {len(known)}")
    for w in sorted(known, key=lambda w: w.get("first_buy_ts") or 9e12)[:30]:
        acc = w.get("x_or_tg") or {}
        out.append(f"{_w(w['wallet'])} tier {w.get('tier') or '–'} · {acc.get('x') or acc.get('tg') or ''} · faza {w['phase']} · "
                   f"prva kupnja {_t(w.get('first_buy_ts'))} MC {w.get('first_buy_mc') or 0:,.0f} · {w['pnl_sol']:+.2f} SOL"
                   + (" · praćen uživo" if w.get("followed_live") else ""))
    # 7) same-slot groups today
    today_slots = {}
    for w in W:
        if (w.get("first_buy_ts") or 0) >= TODAY0 and w.get("first_buy_slot"):
            today_slots.setdefault(w["first_buy_slot"], []).append(w)
    groups = sorted(((s, ws) for s, ws in today_slots.items() if len(ws) >= 3), key=lambda x: x[0])
    out.append(f"## Isti slot danas (3+ prvih kupnji): {len(groups)}")
    for s, ws in groups[:15]:
        out.append(f"slot {s} {_t(ws[0]['first_buy_ts'])}: {len(ws)} novčanika, {sum(x['sol_in'] for x in ws):.2f} SOL, "
                   f"rezultat {sum(x['pnl_sol'] for x in ws):+.2f}, drže {sum(max(0, x['net_tok']) for x in ws) / SUPPLY * 100:.2f} %")
    # 8) phase concentration
    out.append("## Tko drži supply po fazi (neto tokena / 1e9)")
    ph = {}
    for w in W:
        ph[w["phase"]] = ph.get(w["phase"], 0) + max(0, w["net_tok"])
    for k, v in sorted(ph.items(), key=lambda kv: -kv[1]):
        out.append(f"{k}: {v / SUPPLY * 100:.2f} %")
    return out


def main(argv=None, log=None):
    log = log or (lambda s: print(s, flush=True))
    p = argparse.ArgumentParser(description="Hope: analiza (samo čitanje)")
    p.add_argument("--force", action="store_true")
    a = p.parse_args(argv)
    from research import hope
    d = hope.out_dir()
    src = os.path.join(d, hope.NAME + ".json")
    marker = os.path.join(d, hope.NAME + ".report.done")
    if os.path.exists(marker) and not a.force:
        log("hope report: već napravljeno")
        return 0
    if not os.path.exists(src):
        log("hope report: nema datoteke istraživanja")
        return 1
    with open(src) as f:
        r = json.load(f)
    for line in lines(r):
        log(f"HOPE-A | {line}")
    with open(marker, "w") as f:
        f.write(str(int(time.time())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
