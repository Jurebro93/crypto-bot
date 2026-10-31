"""Confidence 0-100 that a token will do well, with every point explained.

Hype score is the base (what the market is doing now); independent confirmations add points, known risks take
them away. Weights are a hand-set starting point: `calibration()` shows how each confidence level actually did
in demo trading, which is the evidence for changing them.
"""

LEVELS = [(55, "visoka", "good"), (35, "srednja", "warn"), (0, "niska", "bad")]


def _pct(v):
    v = v or 0
    return v / 100 if v > 100 else v  # pump.fun reports some shares x100


def parts_keyed(hype=None, features=None, extra=None, rug_verdict=None, event_role=None, liquidity=None, mcap=None):
    """Hand-set parts, each with a stable key so the learned model (learn/confmodel.py) can weigh the same facts:
    [(key, points, text)]. The hard rug rejection is the only part that is not learnable."""
    f, x = features or {}, extra or {}
    parts = []
    if rug_verdict == "ODBAČEN":
        return [("odbacen", -100, "Rug filter ga je odbacio (tvrdi pad): ne ulazi se bez obzira na ostalo.")]
    if hype is not None:
        parts.append(("hype", 0.6 * hype, f"Hype ocjena {hype:.0f}/100 daje do 60 bodova (aktivnost, volumen, kupci, tema)."))
    xb = x.get("x") or {}
    if (f.get("x_buzz") or 0) >= 0.4 or xb.get("influencers"):
        parts.append(("x_buzz", 8, f"Na X-u ga spominje {xb.get('authors', 'više')} autora"
                      + (f", uključujući influencera @{xb['influencers'][0][0]}." if xb.get("influencers") else ".")))
    if f.get("smart_money") or x.get("smart_buyers"):
        parts.append(("smart_money", 10, f"{len(x.get('smart_buyers') or []) or 'Neki'} smart walleti su ga kupili među prvima."))
    if (f.get("kol_wallets") or 0) >= 0.4 or f.get("kol_x"):
        parts.append(("kol", 7, "KOL walleti ga trejdaju ili su ga objavili praćeni influenceri."))
    if f.get("telegram"):
        parts.append(("telegram", 4, "Objavljen u Telegram call kanalima."))
    if f.get("x_trend"):
        parts.append(("x_trend", 5, "Ime je trenutno trending tema na X-u."))
    if event_role == "canonical":
        parts.append(("event", 6, "Pravi token nadolazećeg događaja iz kalendara."))
    pf = x.get("pumpfun") or {}
    if pf:
        top10, bund = _pct(pf.get("top10HoldersPercent")), _pct(pf.get("bundlerOwnedPercent"))
        if top10 < 35 and bund < 15:
            parts.append(("holders_ok", 6, f"Zdravi holderi: top 10 drži {top10:.0f}%, bundleri {bund:.0f}%."))
        else:
            # retrospective of 25k pump.fun tokens (31.10.): tokens with top10 > 45% went 5x MORE often (9,0% vs 4,2%)
            # and a bundle cut would have dropped 44% of winners, so concentration is noted, not punished; the
            # learned model decides its sign from outcomes
            parts.append(("holders_conc", 0, f"Koncentrirani holderi: top 10 drži {top10:.0f}%, bundleri {bund:.0f}%. "
                                              "Retrospektiva ne pokazuje da to škodi, pa ne oduzima bodove; težinu uči model."))
    if rug_verdict == "PROLAZI":
        parts.append(("rug_ok", 10, "Rug filter: PROLAZI (nema bundlea, klastera ni lažnog volumena iznad pragova)."))
    elif rug_verdict == "OPREZ":
        parts.append(("rug_oprez", 3, "Rug filter: OPREZ (manje zastavice)."))
    elif rug_verdict == "VISOK RIZIK":
        parts.append(("rug_rizik", -25, "Rug filter: VISOK RIZIK."))
    if liquidity is not None and liquidity < 10000:
        parts.append(("liq_low", -10, f"Mala likvidnost (${liquidity:,.0f}): velik slippage, lako se izvuče."))
    if mcap and mcap > 1_000_000:
        parts.append(("mcap_big", -5, f"Već velik (mcap ${mcap / 1e6:.1f}M): manje prostora za rast."))
    if (f.get("momentum") or 0) >= 0.9 and (f.get("buy_pressure") or 0) < 0.2:
        parts.append(("top_chase", -5, "Cijena je već jako skočila, a kupci više ne prevladavaju: rizik kupnje vrha."))
    for k in ("snaga_volumen", "rast_holdera", "organski"):
        if (f.get(k) or 0) >= 0.6:
            parts.append((k, 3, {"snaga_volumen": "Drži volumen blizu svog najboljeg sata.",
                                 "rast_holdera": "Broj holdera raste barem 6% na sat.",
                                 "organski": "Novi holderi prate transakcije: promet nije samo vrtnja botova."}[k]))
    return parts


def hand_total(parts):
    return max(0, min(100, round(sum(p for _, p, _ in parts))))


def score(hype=None, features=None, extra=None, rug_verdict=None, event_role=None, liquidity=None, mcap=None, klasa=None):
    """(confidence, [(points, text)]): positive and negative parts, biggest first.

    Hand-set points until the learned model (learn/confmodel.py, fitted daily on real outcomes with guardrails) is
    in place; then the same facts are weighed by what actually preceded a skok, and 50 means "an average token of
    its class", 75 three times the class's skok rate."""
    parts = parts_keyed(hype, features, extra, rug_verdict, event_role, liquidity, mcap)
    if parts and parts[0][0] == "odbacen":
        return 0, [(p, t) for _, p, t in parts]
    model = learned()
    if model:
        try:
            from learn import confmodel
            total, pts = confmodel.apply(model, parts, hype, klasa)
            out = [(pts.get(k, 0.0), t) for k, _, t in parts]
            return total, sorted(out, key=lambda p: -abs(p[0]))
        except Exception:
            pass
    return hand_total(parts), sorted([(p, t) for _, p, t in parts], key=lambda p: -abs(p[0]))


_MODEL = {"ts": 0, "m": None}


def learned(max_age_s=300):
    """The learned confidence model, re-read from disk every 5 minutes; None when none has been applied yet."""
    import time
    if time.time() - _MODEL["ts"] > max_age_s:
        try:
            from learn import confmodel
            _MODEL["m"] = confmodel.load()
        except Exception:
            _MODEL["m"] = None
        _MODEL["ts"] = time.time()
    return _MODEL["m"]


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
            + "</ul><p class=mut style='font-size:12px'>"
            + (f"Naučeni model: težine iz {learned()['n']} stvarnih ishoda (50 = prosječan token svoje klase, 75 = tri puta "
               "češći skok). Kalibracija je na stranici Učenje." if learned() else
               "Težine su početna procjena dok model ne nauči iz barem 200 ishoda (stranica Učenje); kalibracija na demo "
               "trejdovima je na stranici Demo trading.") + "</p>")


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
