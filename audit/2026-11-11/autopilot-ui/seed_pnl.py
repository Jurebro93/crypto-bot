#!/usr/bin/env python3
"""Lokalni podaci za graf "PnL po danima" (11.11.2026.), NA VRH seed_app.py + seed_extra.py: NIJE dio aplikacije i ne
smije u produkciju (odbija se pokrenuti kad vidi RENDER / DATA_DIR / /var/data).

    python3 audit/2026-11-11/autopilot-ui/seed_pnl.py

Dodaje (sve izmišljeno, bez ključeva i bez mreže): ~30 zatvorenih pravih ("live") pozicija u trade.db kroz zadnjih 30
dana (neki dani bez tradea, mrežne naknade po poziciji) i ~60 zatvorenih demo tradeova računa Autopilota u league.db
kroz zadnjih 80 dana. Pokrene li se dvaput, doda još jednom (za čist početak: seed_app.py --reset).
"""
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
NOW = int(time.time())
SYMS = ("GIGAFROG", "ARIA", "MOONCAT", "CHADAI", "KEK", "LAMBO", "PEPEAI", "WIF2", "BONKZ", "SOLDOG", "NEKO", "TRUMPX")


def guard():
    if os.environ.get("RENDER") or os.environ.get("DATA_DIR") or os.path.exists("/var/data"):
        sys.exit("seed_pnl: ovo izgleda kao produkcija (RENDER / DATA_DIR / /var/data). Ne pokrećem.")


def mint(rng):
    alpha = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(rng.choice(alpha) for _ in range(40)) + "pump"


def main():
    guard()
    rng = random.Random(1111)
    from league import store
    from trade import executor, settings
    tc = executor.connect(settings.DB)
    n_live = 0
    for day in range(29, -1, -1):
        if rng.random() < 0.3:            # some days without a closed trade
            continue
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            sym = rng.choice(SYMS)
            closed = NOW - day * 86400 - rng.randint(600, 20 * 3600)
            if closed > NOW - 300:
                closed = NOW - 300
            sol_in = rng.choice((0.05, 0.1, 0.1, 0.15))
            ret = rng.choice((rng.uniform(0.12, 0.6), rng.uniform(-0.45, -0.1), rng.uniform(-0.05, 0.08)))
            fees = round(rng.uniform(0.0006, 0.0018), 6)
            reason = rng.choice(("copy @Humanevolvd", "copy wallet solshark", "ručno", "prijedlog EV"))
            tc.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                       "sol_back, fills_done, closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (mint(rng), sym, closed - rng.randint(300, 7200), "live", "closed", reason, sol_in, 1000, 0,
                        round(sol_in * (1 + ret), 6), 1, closed, fees))
            n_live += 1
    tc.commit()
    tc.close()
    lg = store.connect(store.DB)
    n_paper = 0
    for day in range(79, -1, -1):
        if rng.random() < 0.35:
            continue
        for _ in range(rng.choice((1, 1, 2))):
            sym = rng.choice(SYMS)
            closed = min(NOW - 300, NOW - day * 86400 - rng.randint(600, 20 * 3600))
            size = 15.0
            ret = rng.choice((rng.uniform(0.1, 0.7), rng.uniform(-0.4, -0.08), rng.uniform(-0.06, 0.06)))
            pnl = size * ret
            mc0 = rng.choice((120_000, 240_000, 410_000, 880_000))
            lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, entry_eff, "
                       "qty, exit_px, proceeds, pnl_usd, ret, source, entry_mcap, exit_mcap) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (settings.LEAGUE_USER, mint(rng), sym, closed - rng.randint(300, 7200), closed, "closed", size,
                        mc0 / 1e9, mc0 / 1e9, size / (mc0 / 1e9), mc0 * (1 + ret) / 1e9, size + pnl, pnl, ret,
                        "copy @Humanevolvd", float(mc0), mc0 * (1 + ret)))
            n_paper += 1
    lg.commit()
    lg.close()
    print(f"seed_pnl: gotovo ({n_live} zatvorenih pravih pozicija u 30 d, {n_paper} demo tradeova u 80 d).")


if __name__ == "__main__":
    main()
