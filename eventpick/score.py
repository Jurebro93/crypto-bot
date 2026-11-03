"""Pump-pick score 0-100 for one event token, with plain-Croatian reasons.

Parts (max): organic trading 30, room to grow 15, rug check +10/-25, approach to event 20
(volume and smart wallets rising as the event nears, from eventwatch), KOL calls 12, real-name fit 8,
thin pool -10. A failed rug check ("ODBAČEN") or a pool under $2k removes the token from the pick.
Weights are a first guess; eventwatch outcomes after each event are what should tune them.
"""
import math

RUG_POINTS = {"PROLAZI": 10, "OPREZ": 0, "VISOK RIZIK": -25}


def _usd(x):
    x = x or 0
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}k" if x >= 1e3 else f"${x:.0f}"


def score_token(tok, rug=None, watch=None, kol_handles=0):
    """tok: an event_tokens row (score = organic 0-100, liquidity, mcap, role, keyword, symbol).
    rug: newest rug_reports row or None. watch: watch_correlation row or None.
    Returns {"pump": 0-100 or None if excluded, "reasons": [(points, text)], "excluded": text or None}."""
    reasons = []
    liq, mcap = tok.get("liquidity") or 0, tok.get("mcap") or 0
    if rug and rug.get("verdict") == "ODBAČEN":
        return {"pump": None, "reasons": [(0, "rug provjera ga je odbacila")], "excluded": "rug provjera: odbačen"}
    if liq < 2000:
        return {"pump": None, "reasons": [(0, f"likvidnost samo {_usd(liq)}")], "excluded": "premala likvidnost"}

    organic = 0.3 * (tok.get("score") or 0)
    reasons.append((organic, f"organsko trgovanje {tok.get('score') or 0:.0f}/100 (starost, volumen, transakcije, mreže)"))

    if 50_000 <= mcap <= 5_000_000:
        room = 15
        txt = f"mcap {_usd(mcap)}: ima prostora za rast"
    elif mcap < 50_000:
        room = 6
        txt = f"mcap {_usd(mcap)}: jako mali, može brzo narasti ali i nestati"
    else:
        room = max(0, 15 - 5 * math.log10(mcap / 5_000_000))
        txt = f"mcap {_usd(mcap)}: već velik, teže se udvostruči"
    reasons.append((room, txt))

    if rug:
        pts = RUG_POINTS.get(rug.get("verdict"), 0)
        reasons.append((pts, f"rug provjera: {rug.get('verdict', '?').lower()}"
                        + (f" (bundle {rug['bundle_pct']:.0f}%)" if rug.get("bundle_pct") else "")))
    else:
        reasons.append((0, "rug provjera još nije napravljena"))

    if watch and (watch.get("n") or 0) >= 6:
        vol = watch.get("corr_volume") or 0
        pts = 10 * max(-1, min(1, vol))
        pts += min(10, 3 * (watch.get("smart_total") or 0)) - min(10, 3 * (watch.get("bad_total") or 0))
        reasons.append((pts, f"prema eventu: {watch.get('verdict') or 'bez jasne veze'}"))
    else:
        reasons.append((0, "praćenje prije eventa još nema dovoljno podataka"))

    if kol_handles:
        reasons.append((min(12, 4 * kol_handles), f"{kol_handles} KOL-a ga je spomenulo u 7 dana"))

    fit = (5 if tok.get("role") == "canonical" else 0) + (3 if (tok.get("symbol") or "").upper() == (tok.get("keyword") or "").upper() else 0)
    if fit:
        reasons.append((fit, "najstariji/pravi token za ovo ime" if tok.get("role") == "canonical" else "simbol točno odgovara eventu"))

    if liq < 10_000:
        reasons.append((-10, f"tanak bazen {_usd(liq)}: veća kupnja ruši cijenu"))

    pump = round(max(0, min(100, sum(p for p, _ in reasons))), 1)
    return {"pump": pump, "reasons": sorted(reasons, key=lambda r: -abs(r[0])), "excluded": None}


def rank(tokens, rugs=None, watches=None, kol=None):
    """Score every token of one event; best first, excluded tokens last."""
    rugs, watches, kol = rugs or {}, watches or {}, kol or {}
    out = []
    for t in tokens:
        r = score_token(t, rugs.get(t["token"]), watches.get(t["token"]), kol.get(t["token"], 0))
        out.append({**t, **r})
    out.sort(key=lambda t: (t["pump"] is None, -(t["pump"] or 0)))
    return out
