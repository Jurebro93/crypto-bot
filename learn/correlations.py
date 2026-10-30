"""What the data says, for the Učenje page: lift per feature, hit rate along raw thresholds, feature pairs."""
import json

from hype import evaluate

# raw values worth a threshold curve: (label, getter(row, detail), bin edges)
CURVES = [
    ("Likvidnost ($)", lambda r, d: r.get("liquidity"), [0, 5e3, 10e3, 25e3, 50e3, 100e3, 1e9]),
    ("Mcap ($)", lambda r, d: r.get("mcap"), [0, 50e3, 150e3, 500e3, 2e6, 10e6, 1e12]),
    ("Top 10 holdera (%)", lambda r, d: _pct(((d or {}).get("pumpfun") or {}).get("top10HoldersPercent")), [0, 20, 35, 50, 70, 101]),
    ("Bundleri (%)", lambda r, d: _pct(((d or {}).get("pumpfun") or {}).get("bundlerOwnedPercent")), [0, 5, 15, 30, 101]),
    ("Smart kupaca", lambda r, d: len((d or {}).get("smart_buyers") or []) if d and "smart_buyers" in d else None, [0, 1, 2, 4, 99]),
    ("Skokovitost puta", lambda r, d: r.get("features", {}).get("put_skokovitost"), [0, 0.25, 0.5, 0.75, 1.01]),
]


def _pct(v):
    if v is None:
        return None
    return v / 100 if v > 100 else v


def with_details(con, rows):
    """Attach the first hype_details extra and the first signal's liquidity/mcap to each outcome row."""
    for r in rows:
        d = con.execute("SELECT extra FROM hype_details WHERE token=? ORDER BY ts LIMIT 1", (r["token"],)).fetchone()
        r["detail"] = json.loads(d[0]) if d and d[0] else {}
        m = con.execute("SELECT liquidity, mcap FROM hype_signals WHERE token=? ORDER BY ts LIMIT 1", (r["token"],)).fetchone()
        r["liquidity"], r["mcap"] = (m[0], m[1]) if m else (r.get("liquidity"), None)
    return rows


def lift(rows):
    return [x for x in evaluate.feature_lift(rows) if x["n_strong"] >= 5]


def curves(rows):
    """Per raw value: [(bin label, n, hit rate)] so the right threshold can be read off instead of guessed."""
    out = []
    for label, get, edges in CURVES:
        bins = []
        for lo, hi in zip(edges, edges[1:]):
            b = [r for r in rows if (v := get(r, r.get("detail"))) is not None and lo <= v < hi]
            if b:
                bins.append({"bin": _fmt(lo, hi, label), "n": len(b), "hit_rate": round(sum(r["hit"] for r in b) / len(b), 2),
                             "rug_rate": round(sum(r["rug"] for r in b) / len(b), 2)})
        if sum(x["n"] for x in bins) >= 10:
            out.append({"label": label, "bins": bins})
    return out


def _fmt(lo, hi, label):
    def f(x):
        if x >= 1e9:
            return "∞"
        if x >= 1e6:
            return f"{x / 1e6:g}M"
        if x >= 1e3:
            return f"{x / 1e3:g}k"
        return f"{x:g}"
    if "%" in label and hi > 100:
        return f"≥ {lo:g}"
    if hi >= 1e9 or (label.endswith("kupaca") and hi > 10):
        return f"≥ {f(lo)}"
    return f"{f(lo)}–{f(hi)}"


def pairs(rows, min_n=10, top=10):
    """Feature pairs that are both strong: hit rate vs what the two alone would predict (lift > 1 = they add up)."""
    feats = sorted({k for r in rows for k in r["features"]})
    base = sum(r["hit"] for r in rows) / len(rows) if rows else 0
    single = {}
    for f in feats:
        hi = [r for r in rows if r["features"].get(f, 0) >= 0.5]
        single[f] = sum(r["hit"] for r in hi) / len(hi) if hi else base
    out = []
    for i, a in enumerate(feats):
        for b in feats[i + 1:]:
            both = [r for r in rows if r["features"].get(a, 0) >= 0.5 and r["features"].get(b, 0) >= 0.5]
            if len(both) < min_n or not base:
                continue
            hr = sum(r["hit"] for r in both) / len(both)
            expect = min(1.0, single[a] * single[b] / base) if base else 0  # independence assumption
            out.append({"a": a, "b": b, "n": len(both), "hit_rate": round(hr, 2),
                        "lift": round(hr / expect, 2) if expect else None})
    return sorted([p for p in out if p["lift"]], key=lambda p: -p["lift"])[:top]
