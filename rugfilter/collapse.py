"""Rug / collapse after the fact: a token that has already been dumped (price crashed from its recent peak, often
with the liquidity pulled out too) must not be offered to anyone any more, whatever the rug filter said before.

The rug filter (rugfilter/check.py) judges a token *before* entry from its mechanics and wallets. This module
judges what *happened*: we compare the newest market cap and liquidity with the highest the bot has seen for that
token in the last `WINDOW_H` hours (hype scans and the 2-minute pulse). A pump.fun token that lost 70% from its
peak within a day almost never comes back (retrospective: median 0.06x after graduation), so the threshold is
deliberately simple and the same for every page and for the bot's own entries.

If a collapsed token later climbs back above `RECOVER` of its peak it is shown again (the check is recomputed on
every look, nothing is stored).
"""
import os
import sqlite3
import time

WINDOW_H = 24
DROP = 0.70          # market cap at least 70% below the peak seen in WINDOW_H -> collapsed
LIQ_DROP = 0.60      # or liquidity at least 60% below its peak ...
LIQ_PRICE_DROP = 0.50  # ... together with market cap at least 50% below its peak (liquidity pulled)
RECOVER = 0.50       # recomputed each time; above half of the peak it is no longer collapsed
MIN_PEAK_MCAP = 5000  # below this nothing meaningful to compare


def judge(peak_mcap, now_mcap, peak_liq=None, now_liq=None):
    """None, or {"drop", "liq_drop", "text"} when the token is collapsed. Plain Croatian text for the dashboard."""
    if not peak_mcap or peak_mcap < MIN_PEAK_MCAP or now_mcap is None or now_mcap < 0:
        return None
    drop = 1 - now_mcap / peak_mcap
    liq_drop = (1 - (now_liq or 0) / peak_liq) if peak_liq and now_liq is not None else None
    if drop < 1 - RECOVER:
        return None
    if drop >= DROP:
        text = f"srušio se {drop:.0%} od vrha (${peak_mcap / 1000:,.1f}k → ${now_mcap / 1000:,.1f}k)"
    elif liq_drop is not None and liq_drop >= LIQ_DROP and drop >= LIQ_PRICE_DROP:
        text = f"izvučena likvidnost ({liq_drop:.0%} manje) i pad {drop:.0%} od vrha"
    else:
        return None
    if liq_drop is not None and liq_drop >= LIQ_DROP and drop >= DROP:
        text += f", likvidnost {liq_drop:.0%} manja"
    return {"drop": round(drop, 3), "liq_drop": None if liq_drop is None else round(liq_drop, 3), "text": text}


def peaks(db_path, tokens, hours=WINDOW_H, now=None):
    """token -> (peak_mcap, peak_liq, last_mcap, last_liq, last_ts) from hype_signals + token_pulse in hype.db."""
    tokens = list(tokens)
    if not tokens or not os.path.exists(db_path):
        return {}
    since = int((now or time.time()) - hours * 3600)
    out = {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return {}
    try:
        for i in range(0, len(tokens), 400):
            part = tokens[i:i + 400]
            ph = ",".join("?" * len(part))
            for table in ("hype_signals", "token_pulse"):
                try:
                    rows = con.execute(f"SELECT token, ts, mcap, liquidity FROM {table} WHERE ts >= ? AND token IN ({ph})",
                                       (since, *part)).fetchall()
                except sqlite3.OperationalError:
                    continue
                for t, ts, mc, liq in rows:
                    add(out, t, ts, mc, liq)
    finally:
        con.close()
    return out


def add(acc, token, ts, mcap, liq):
    """Fold one observation into acc[token] = [peak_mcap, peak_liq, last_mcap, last_liq, last_ts]."""
    r = acc.setdefault(token, [0.0, 0.0, None, None, 0])
    if mcap:
        r[0] = max(r[0], mcap)
    if liq:
        r[1] = max(r[1], liq)
    if ts >= r[4] and mcap:
        r[2], r[3], r[4] = mcap, liq, ts
    return r


def check(peak_row, live_mcap=None, live_liq=None):
    """Judge a peaks() row, preferring a live market cap/liquidity when given (and counting it into the peak)."""
    if not peak_row:
        return None
    pm, pl, lm, ll, _ = peak_row
    now_m = live_mcap if live_mcap is not None else lm
    now_l = live_liq if live_liq is not None else ll
    return judge(max(pm or 0, now_m or 0), now_m, max(pl or 0, now_l or 0) or None, now_l)
