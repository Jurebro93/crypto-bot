"""How often does kol/tpsl.decide say "enter" for a source with NO edge (random walk), and how often for one with
a real edge? Minute paths are simulated the way kol/minute.path measures them (first minute each level is touched)."""
import json, random, sys
sys.path.insert(0, "/home/user/crypto-bot")
from kol import minute, tpsl

def call(rng, sigma, drift=0.0, pump=None):
    p, up, dn = 1.0, {}, {}
    for k in range(1, 61):
        d = drift + (pump[0] if pump and k <= pump[1] else 0.0)
        r = rng.gauss(d, sigma)
        hi = p * (1 + max(r, 0) + abs(rng.gauss(0, sigma / 2)))
        lo = p * (1 + min(r, 0) - abs(rng.gauss(0, sigma / 2)))
        p = max(1e-9, p * (1 + r))
        for u in minute.UPS:
            if u not in up and hi >= 1 + u / 100: up[u] = k
        for dd in minute.DOWNS:
            if dd not in dn and lo <= 1 - dd / 100: dn[dd] = k
    return {"u": {str(a): b for a, b in up.items()}, "d": {str(a): b for a, b in dn.items()}}, p - 1

def source(rng, n, sigma, edge_share=0.0, pump=(0.02, 10)):
    rows = []
    for i in range(n):
        lv, r60 = call(rng, sigma, pump=pump if rng.random() < edge_share else None)
        rows.append({"tweet_id": str(i), "token": f"T{i}", "handle": "h", "ts": i, "hi60": None, "lo60": None, "r60": r60,
                     "t5": None, "t10": None, "t15": None, "t20": None, "t30": None, "sl_min": None, "lv": json.dumps(lv)})
    return rows

rng = random.Random(7)
for sigma in (0.02, 0.04):
    for n in (10, 20, 40):
        fp = sum(1 for _ in range(1500) if tpsl.decide(source(rng, n, sigma)).get("ok")) / 1500
        tp_ = sum(1 for _ in range(600) if tpsl.decide(source(rng, n, sigma, edge_share=0.6)).get("ok")) / 600
        print(f"sigma {sigma:.0%}/min  n={n:>2}:  no edge -> enters {fp:.1%}   |  60 % of calls pump +2 %/min x 10 min -> enters {tp_:.1%}")
# what the pool says for a no-edge crowd (sanity: every pair should lose about the cost)
rows = source(rng, 4000, 0.03)
g = tpsl.grid(rows)
print("no-edge pool EV per pair (should be near -2):", {f"{a}/{b}": round(v["ev"], 1) for (a, b), v in list(g.items())[::6]})
