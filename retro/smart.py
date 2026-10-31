"""Smart-wallet seed from the retrospective: wallets that bought early in several tokens that later pumped.

Everything here comes from trades already in retro.db, so it costs no Helius credits. Writes
wallets/seed_retro.json (bounded: top N) which run_wallets.py harvest imports into wallets.db on the server.
"""
import json
import os
import sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "wallets", "seed_retro.json")
EARLY_S = 30 * 60  # "early" = bought within 30 min of creation, before the token proved itself


def winners(features_csv, min_mult=3.0, points=("A15", "G")):
    """mint -> best multiple from a decision point the bot could have acted on."""
    import csv
    out = {}
    with open(features_csv) as f:
        for r in csv.DictReader(f):
            if r["point"] in points and r["mult"] and r["known"] == "1":
                out[r["mint"]] = max(out.get(r["mint"], 0.0), float(r["mult"]))
    return {m: x for m, x in out.items() if x >= min_mult}, {m for m in out}


def wallet_stats(dbs, win, known):
    """Per wallet over all sampled tokens with a known outcome: tokens bought early, how many pumped,
    SOL in/out on the curves (realized), bundle/dev sightings (disqualify)."""
    st = defaultdict(lambda: {"tokens": 0, "wins": 0, "sol_in": 0.0, "sol_out": 0.0, "bundle": 0, "dev": 0,
                              "win_mints": []})
    for path in dbs:
        if not os.path.exists(path):
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        toks = {r[0]: r for r in con.execute("SELECT mint, t_create, slot_create, creator FROM tokens WHERE t_create IS NOT NULL")}
        for mint, t0, slot0, creator in toks.values():
            if mint not in known:
                continue
            seen = set()
            for w, side, tokens, sol, ts, slot in con.execute(
                    "SELECT wallet, side, tokens, sol, ts, slot FROM trades WHERE mint=?", (mint,)):
                s = st[w]
                if w == creator:
                    s["dev"] += 1
                    continue
                if side == "buy":
                    s["sol_in"] += -sol
                    if slot == slot0:
                        s["bundle"] += 1
                    if w not in seen and ts - t0 <= EARLY_S:
                        seen.add(w)
                        s["tokens"] += 1
                        if mint in win:
                            s["wins"] += 1
                            s["win_mints"].append(mint)
                elif side == "sell":
                    s["sol_out"] += sol
        con.close()
    return st


def rank(st, min_wins=2, min_tokens=2, top=300):
    rows = []
    for w, s in st.items():
        if s["wins"] < min_wins or s["tokens"] < min_tokens or s["dev"] or s["bundle"] > s["tokens"] / 2:
            continue
        hit = s["wins"] / s["tokens"]
        pnl = s["sol_out"] - s["sol_in"]
        rows.append({"wallet": w, "tokens": s["tokens"], "wins": s["wins"], "hit_rate": round(hit, 3),
                     "realized_sol": round(pnl, 3), "bundle_buys": s["bundle"],
                     # many tokens with a low hit rate is a spray bot; few tokens with a high rate is luck or skill
                     "score": round(100 * hit * min(1.0, s["wins"] / 4) * (1.0 if pnl > 0 else 0.5), 1),
                     "win_mints": s["win_mints"][:10]})
    rows.sort(key=lambda r: (-r["score"], -r["realized_sol"]))
    return rows[:top]


def write_seed(rows, path=SEED, note=""):
    with open(path, "w") as f:
        json.dump({"_comment": "Walleti koji su rano kupili u više tokena koji su kasnije skočili (retro/smart.py). "
                               "run_wallets.py harvest ih uvozi u wallets.db kao source=retro, role=smart. " + note,
                   "wallets": rows}, f, indent=1)
    return path
