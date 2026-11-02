"""Market state of a token right now, from DexScreener's price changes (m5, h1, h6, h24) and the last hour's buys
and sells. Pure function, no network: tested in tests/test_topcheck_offline.py.

Nicholas 2.11.: "je li token u padu uz šansu oporavka ili je trenutno pumpa, jer na pumpu se ne kupuje. Pa onda
nekakav savjet možda da se ipak pričeka."

    pumpa      rose hard in the last minutes/hour: buying the top of a pump is how most people lose; wait for a pullback
    oporavak   fell a lot in the last hours, but the last hour is green and buyers outnumber sellers: possible entry
    pada       falling and no sign of a turn yet: wait until it stops making new lows
    stabilno   no sharp move: enter by plan, with a stop loss
"""

# thresholds in percent (DexScreener priceChange is in percent)
PUMP_M5, PUMP_H1, PUMP_H6 = 12.0, 30.0, 80.0
DIP_H6, DIP_H24, DIP_H1 = -20.0, -30.0, -15.0

STATES = {
    "pumpa": ("🚀 Pumpa", "bad",
              "Ne kupuj sad: cijena je naglo skočila i kupnja na vrhu pumpe najčešće završi gubitkom. Pričekaj povlačenje "
              "i par mirnijih minuta."),
    "oporavak": ("↗ Pad, kreće oporavak", "good",
                 "Pao je pa se okreće: zadnji sat raste i kupaca je više nego prodavača. Moguća prilika, uđi manjim "
                 "ulogom i postavi stop loss."),
    "pada": ("📉 Pada", "warn",
             "Još pada i nema znakova okreta. Pričekaj da prestane raditi nova dna (barem 15-30 min mira)."),
    "stabilno": ("➖ Stabilno", "",
                 "Bez naglih pomaka. Ulaz po planu, uz postavljen stop loss."),
}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def classify(pair):
    """(state, label, css, advice, why) for a DexScreener pair dict, or None without price change data."""
    if not pair:
        return None
    ch = pair.get("priceChange") or {}
    m5, h1, h6, h24 = (_f(ch.get(k)) for k in ("m5", "h1", "h6", "h24"))
    if m5 is None and h1 is None and h6 is None and h24 is None:
        return None
    tx = (pair.get("txns") or {}).get("h1") or {}
    buys, sells = tx.get("buys") or 0, tx.get("sells") or 0

    def pct(x):
        return "?" if x is None else f"{x:+.0f}%"
    why = f"5 min {pct(m5)} · 1 h {pct(h1)} · 6 h {pct(h6)} · 24 h {pct(h24)}"
    if buys or sells:
        why += f" · zadnji sat {buys} kupnji / {sells} prodaja"

    if (m5 or 0) >= PUMP_M5 or (h1 or 0) >= PUMP_H1 or (h6 or 0) >= PUMP_H6:
        st = "pumpa"
    elif (h6 or 0) <= DIP_H6 or (h24 or 0) <= DIP_H24 or (h1 or 0) <= DIP_H1:
        turning = (h1 or 0) >= 0 and (m5 or 0) >= -2 and buys >= sells
        st = "oporavak" if turning else "pada"
    else:
        st = "stabilno"
    label, css, advice = STATES[st]
    return {"state": st, "label": label, "css": css, "advice": advice, "why": why}
