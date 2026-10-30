"""Confidence 0-100 that a token will do well, with every point explained.

Hype score is the base (what the market is doing now); independent confirmations add points, known risks take
them away. Weights are a hand-set starting point: `calibration()` shows how each confidence level actually did
in demo trading, which is the evidence for changing them.
"""

LEVELS = [(55, "visoka", "good"), (35, "srednja", "warn"), (0, "niska", "bad")]


def _pct(v):
    v = v or 0
    return v / 100 if v > 100 else v  # pump.fun reports some shares x100


def score(hype=None, features=None, extra=None, rug_verdict=None, event_role=None, liquidity=None, mcap=None):
    """(confidence, [(points, text)]): positive and negative parts, biggest first."""
    f, x = features or {}, extra or {}
    parts = []
    if rug_verdict == "ODBAČEN":
        return 0, [(-100, "Rug filter ga je odbacio (tvrdi pad): ne ulazi se bez obzira na ostalo.")]
    if hype is not None:
        parts.append((0.6 * hype, f"Hype ocjena {hype:.0f}/100 daje do 60 bodova (aktivnost, volumen, kupci, tema)."))
    xb = x.get("x") or {}
    if (f.get("x_buzz") or 0) >= 0.4 or xb.get("influencers"):
        parts.append((8, f"Na X-u ga spominje {xb.get('authors', 'više')} autora"
                         + (f", uključujući influencera @{xb['influencers'][0][0]}." if xb.get("influencers") else ".")))
    if f.get("smart_money") or x.get("smart_buyers"):
        parts.append((10, f"{len(x.get('smart_buyers') or []) or 'Neki'} smart walleti su ga kupili među prvima."))
    if (f.get("kol_wallets") or 0) >= 0.4 or f.get("kol_x"):
        parts.append((7, "KOL walleti ga trejdaju ili su ga objavili praćeni influenceri."))
    if f.get("telegram"):
        parts.append((4, "Objavljen u Telegram call kanalima."))
    if f.get("x_trend"):
        parts.append((5, "Ime je trenutno trending tema na X-u."))
    if event_role == "canonical":
        parts.append((6, "Pravi token nadolazećeg događaja iz kalendara."))
    pf = x.get("pumpfun") or {}
    if pf:
        top10, bund = _pct(pf.get("top10HoldersPercent")), _pct(pf.get("bundlerOwnedPercent"))
        if top10 < 35 and bund < 15:
            parts.append((6, f"Zdravi holderi: top 10 drži {top10:.0f}%, bundleri {bund:.0f}%."))
        else:
            parts.append((-10, f"Koncentrirani holderi: top 10 drži {top10:.0f}%, bundleri {bund:.0f}%."))
    if rug_verdict == "PROLAZI":
        parts.append((10, "Rug filter: PROLAZI (nema bundlea, klastera ni lažnog volumena iznad pragova)."))
    elif rug_verdict == "OPREZ":
        parts.append((3, "Rug filter: OPREZ (manje zastavice)."))
    elif rug_verdict == "VISOK RIZIK":
        parts.append((-25, "Rug filter: VISOK RIZIK."))
    if liquidity is not None and liquidity < 10000:
        parts.append((-10, f"Mala likvidnost (${liquidity:,.0f}): velik slippage, lako se izvuče."))
    if mcap and mcap > 1_000_000:
        parts.append((-5, f"Već velik (mcap ${mcap / 1e6:.1f}M): manje prostora za rast."))
    if (f.get("momentum") or 0) >= 0.9 and (f.get("buy_pressure") or 0) < 0.2:
        parts.append((-5, "Cijena je već jako skočila, a kupci više ne prevladavaju: rizik kupnje vrha."))
    total = max(0, min(100, round(sum(p for p, _ in parts))))
    return total, sorted(parts, key=lambda p: -abs(p[0]))


def level(c):
    for lo, name, kind in LEVELS:
        if c >= lo:
            return name, kind
    return LEVELS[-1][1:]


def badge_html(c):
    from ui.html import bar, badge
    name, kind = level(c)
    return f"{bar(c, 100, 50)} <b>{c}</b> {badge(name, kind)}"


def explain_html(c, parts):
    from ui.html import esc
    name, _ = level(c)
    return (f"<p>Confidence <b>{c}/100</b> ({name}).</p><ul class=r>"
            + "".join(f'<li class="{"good" if p > 0 else "bad"}"><b>{p:+.0f}</b> {esc(t)}</li>' for p, t in parts)
            + "</ul><p class=mut style='font-size:12px'>Težine su početna procjena. Kalibracija na demo trejdovima je "
              "na stranici Demo trading.</p>")


def for_candidate(c, det=None):
    """Confidence from a paper candidate row as it was at entry time."""
    return score(c.get("score"), c.get("features"), det, c.get("rug_verdict"), None, c.get("liquidity"), c.get("mcap"))


def calibration(trades, cands):
    """[(level, n, win_rate, avg_ret)] of closed demo trades grouped by confidence at entry."""
    by_id = {c.get("trade_id"): c for c in cands if c.get("trade_id")}
    out = {}
    for t in trades:
        if t["status"] != "closed" or t["id"] not in by_id:
            continue
        name, _ = level(for_candidate(by_id[t["id"]])[0])
        out.setdefault(name, []).append(t)
    rows = []
    for _, name, _ in LEVELS:
        g = out.get(name, [])
        rows.append((name, len(g), sum((t["ret"] or 0) > 0 for t in g) / len(g) if g else None,
                     sum(t["ret"] or 0 for t in g) / len(g) if g else None))
    return rows
