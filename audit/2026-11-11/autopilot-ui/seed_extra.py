#!/usr/bin/env python3
"""Lokalni podaci za snimke i mjerenja novog Autopilota (11.11.2026.), NA VRH audit/2026-11-10/seed_app.py: NIJE dio
aplikacije i ne smije u produkciju (odbija se pokrenuti kad vidi RENDER / DATA_DIR / /var/data).

    UIPROP_ANYWHERE=1 python3 audit/2026-11-10/seed_app.py --reset
    python3 audit/2026-11-11/autopilot-ui/seed_extra.py --seed <seed.json koji je seed_app napisao>

Što dodaje (sve izmišljeno, bez ključeva i bez mreže):
  trade.db   GIGAFROG kao prava ("live") pozicija s demo parom (ulazni MC, TP +30 % / SL -40 %), ARIA s demo parom
             (Smart sell), DCA nalog i nalog za kupnju na MC, jedna danas zatvorena prava pozicija, zastavica proposals
  league.db  demo tradeovi iza tih pozicija (ulazni MC i pravilo izlaza)
  range.db   24 h snimki GIGAFROG-a (svake 2 min, raspon 300-430k) i izračunati raspon (zone u MC-u) + nekoliko redaka
             watchliste
  proposals.db  tri otvorena prijedloga i dva "skoro" (blokirana)
"""
import argparse
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
NOW = int(time.time())


def guard():
    if os.environ.get("RENDER") or os.environ.get("DATA_DIR") or os.path.exists("/var/data"):
        sys.exit("seed_extra: ovo izgleda kao produkcija (RENDER / DATA_DIR / /var/data). Ne pokrećem.")


def main():
    guard()
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True, help="seed.json koji je napisao seed_app.py")
    a = ap.parse_args()
    seed = json.load(open(a.seed, encoding="utf-8"))
    T = seed["tokens"]
    rng = random.Random(1111)
    from league import copy, store
    from trade import executor, settings
    giga, aria, moon = T["GIGAFROG"], T["ARIA"], T["MOONCAT"]

    # ---- league.db: the demo trades the real positions follow ----
    lg = store.connect(store.DB)
    copy.ensure(lg)
    lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, NOW))
    rule_g = {"mode": "tpsl", "tp": "+30%", "sl": "-40%", "tp_px": 1.3, "sl_px": 0.6, "tp_in": "30%", "sl_in": "-40%"}
    tid_g = lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, source, entry_px, entry_eff, "
                       "entry_mcap, qty, auto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (settings.LEAGUE_USER, giga, "GIGAFROG", NOW - 42 * 60, "open", 25, "ručno", 0.00034, 0.00034,
                        340_000.0, 25 / 0.00034, json.dumps(rule_g))).lastrowid
    tid_a = lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, source, entry_px, entry_eff, "
                       "entry_mcap, qty, auto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (settings.LEAGUE_USER, aria, "ARIA", NOW - 133 * 60, "open", 25, "copy", 0.000251, 0.000251,
                        251_000.0, 25 / 0.000251, json.dumps({"mode": "smart"}))).lastrowid
    lg.commit()
    lg.close()

    # ---- trade.db: GIGAFROG live, ARIA paper with its demo side, orders, a closed live trade today ----
    tc = executor.connect(settings.DB)
    tc.execute("UPDATE positions SET mode='live', league_id=?, reason='ručno (pravi trade)', sol_in=0.15 WHERE token=? "
               "AND status='open'", (tid_g, giga))
    tc.execute("UPDATE positions SET league_id=? WHERE token=? AND status='open'", (tid_a, aria))
    tc.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, sol_back, "
               "closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (T["BORK"], "BORK", NOW - 5 * 3600, "live", "closed", "copy KOL ansem", 0.1, 10 ** 12, 0, 0.1314,
                NOW - 3 * 3600, 0.0021))
    settings.put(tc, "dca_orders", [{"id": NOW * 1000, "token": giga, "sym": "GIGAFROG", "mc": 280_000.0, "sol": 0.05,
                                     "txt": "$280k", "made": NOW - 600}], "Jure")
    settings.put(tc, "buy_orders", [{"id": NOW * 1000 + 1, "token": moon, "sym": "MOONCAT", "mc": 130_000.0, "sol": 0.1,
                                     "exit": "tpsl", "tp": "40%", "sl": "-35%", "made": NOW - 900, "until": NOW + 23 * 3600,
                                     "mc_made": 186_000.0}], "Jure")
    settings.put(tc, "max_sol_per_trade", 0.2, "Jure")
    # one value snapshot (trade/equity): the panel's wallet and the SOL rate for the cost estimate, as on Render
    from trade import equity
    equity.ensure(tc)
    tc.execute("INSERT OR REPLACE INTO equity (ts, sol, usdc, tokens_sol, sol_usd, usd_eur, flow_sol, src) "
               "VALUES (?,?,?,?,?,?,?,?)", (NOW - 120, 1.842, 25.0, 0.38, 162.0, 0.862, 1.5, "live"))
    try:
        settings.set_flag(tc, "proposals", "shadow", "Jure")
    except Exception as e:  # noqa: BLE001
        print(f"  zastavica proposals: {e}")
    tc.commit()
    tc.close()

    # ---- range.db: 24 h of GIGAFROG snapshots in a range and the computed range ----
    from rangedca import data as rdata
    rc = rdata.connect()
    rc.execute("DELETE FROM snaps WHERE token=?", (giga,))
    sup = 1e9
    rows = []
    for i in range(24 * 30, -1, -1):
        ts = NOW - i * 120
        x = i / 30.0
        mc = 365_000 + 55_000 * math.sin(x / 2.1) + 12_000 * math.sin(x * 1.7) + rng.gauss(0, 4_000)
        if i < 30:   # the last hour climbs to the live 412k
            mc = mc + (412_000 - mc) * (1 - i / 30)
        rows.append((giga, ts, mc / sup, mc, 61_000.0, 9_000.0, 95_000.0, None, rng.randint(6, 20), rng.randint(4, 15),
                     rng.randint(60, 180), rng.randint(40, 150), None))
    rc.executemany("INSERT OR REPLACE INTO snaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    import sqlite3
    hc = sqlite3.connect(os.path.join(ROOT, "hype.db"))   # seed_app's 3 h of pulse rows would cross these snapshots
    hc.execute("DELETE FROM token_pulse WHERE token=?", (giga,))
    hc.commit()
    hc.close()
    zones = {"range_high_low": 0.000405, "range_high_top": 0.000428, "range_low_low": 0.000302, "range_low_top": 0.000322,
             "range_high": 0.000416, "range_low": 0.000312,
             "mc": {"range_high_low": 405_000, "range_high_top": 428_000, "range_low_low": 302_000, "range_low_top": 322_000}}
    res = {"ts": NOW - 240, "status": "aktivan", "active": True, "why": "", "zones": zones, "score": 0.78, "ratio": 1.33,
           "pos_pct": 87.4, "metrics": {"price": 0.000412, "mcap": 412_000, "supply": sup, "liq": 61_000}, "source": "signal"}
    rdata.save_range(rc, giga, res, {}, symbol="GIGAFROG")
    for sym, act, score, st in (("ARIA", True, 0.72, "aktivan"), ("MOCHI", False, 0.55, "slab volumen"),
                                ("NYAN", False, 0.41, "nema raspona"), ("BORK", True, 0.71, "aktivan")):
        r2 = {"ts": NOW - rng.randint(60, 900), "status": st, "active": act, "score": score, "zones": None,
              "pos_pct": round(rng.uniform(10, 90), 1), "metrics": {"mcap": rng.randint(80, 300) * 1000}, "source": "market"}
        rdata.save_range(rc, T[sym], r2, {}, symbol=sym)
    rc.commit()
    rc.close()

    # ---- proposals.db: open proposals and near misses ----
    from proposals import store as pstore
    pc = pstore.connect()
    pc.execute("DELETE FROM proposals")
    props = [("ARIA", aria, "range", ["range", "influencer"], 6.4, 0.58, 41, 268_000, (255_000, 272_000), 45),
             ("MOONCAT", moon, "momentum", ["momentum"], 3.1, 0.51, 64, 186_000, (176_000, 190_000), 30),
             ("MOCHI", T["MOCHI"], "influencer", ["influencer", "group"], 4.2, 0.47, 33, 96_000, (90_000, 99_000), 120)]
    for sym, tok, strat, srcs, ev, p, n, mcap, (lo, hi), tmin in props:
        row = {"token": tok, "symbol": sym, "strategy": strat, "sources": srcs, "n_independent": len(srcs), "ev_pct": ev,
               "p_tp": p, "n": n, "ci90": [p - 0.12, p + 0.11], "expires_ts": NOW + rng.randint(15, 80) * 60,
               "size_sol": 0.15, "buy": {"tp": "25%", "sl": "-20%"}, "entry_zone": {"mcap_low": lo, "mcap_high": hi},
               "exits_mcap": {"tp": [mcap * 1.25], "tp_share": [1], "sl": mcap * 0.8, "time_min": tmin,
                              "trailing_pct": 8 if strat == "range" else None},
               "market": {"market_cap_usd": mcap}, "cost_pct": 3.0, "why": f"{sym}: test prijedlog za lokalni pregled.",
               "risks": [], "tp_pct": 25, "sl_pct": 20}
        pstore.insert(pc, row, NOW - rng.randint(60, 900))
    pstore.kv_put(pc, "last_pass", {"ts": NOW - 120, "near": [
        {"token": T["NYAN"], "symbol": "NYAN", "strategies": ["momentum"], "why": "EV ispod nule", "blocks": ["run-up 5x+"],
         "ev_pct": -1.2, "mcap": 78_500},
        {"token": T["BORK"], "symbol": "BORK", "strategies": ["influencer"], "why": "", "blocks": ["likvidnost < $20k"],
         "ev_pct": 0.8, "mcap": 241_000}]})
    pc.commit()
    pc.close()
    print("seed_extra: gotovo (GIGAFROG uživo s rasponom, ARIA/MOONCAT paper, nalozi, prijedlozi).")


if __name__ == "__main__":
    main()
