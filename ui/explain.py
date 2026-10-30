"""Turns stored scores back into their parts, so the UI can show *why* a wallet or token got its number.

The formulas mirror wallets/pnl.py, dexscreener/match.py and event_calendar/enrich.py. If one of those changes,
the "izračunato" total in the UI stops matching the stored score, which is the hint to update this file.
"""
import datetime as dt
import math

try:
    from wallets.store import BAD_LABELS
except Exception:  # module missing or mid-edit: fall back to the list from the time of writing
    BAD_LABELS = {"bot", "rugger", "bundler", "insider", "dev", "cex", "mev", "sniper"}

# defaults of `run_wallets.py copy`
COPY_MIN_SCORE = 50
COPY_MIN_CLOSED = 10


def _clamp(x):
    return max(0.0, min(1.0, x))


def wallet_score(s):
    """[(name, points, max, explanation)] for the 0-100 wallet score, plus the evidence multiplier."""
    n = s.get("closed") or 0
    total = s.get("closed_pnl_sol") or 0
    roi = s.get("roi_on_cost") or 0
    wins = round((s.get("win_rate") or 0) * n)
    wr = (wins + 1) / (n + 2)
    pf = min(s.get("profit_factor") or 0, 5)
    big = s.get("big_wins") or 0
    top = s.get("top_trade_share")
    top = 1.0 if top is None else top
    parts = [
        ("Zatvoreni profit", 25 * _clamp(math.log10(1 + max(0, total)) / 2), 25,
         f"{total:+.2f} SOL na zatvorenim pozicijama; 100 SOL = puni bodovi (log skala)"),
        ("ROI na uloženo", 20 * _clamp(roi), 20, f"{roi:+.0%} na uloženi SOL; +100% = puni bodovi"),
        ("Win rate", 20 * _clamp((wr - 0.25) / 0.45), 20,
         f"{wins}/{n} dobitnih; korigirano prema 50% ({wr:.0%}) da 2/2 ne izgleda kao genij; 25% = 0, 70% = max"),
        ("Profit factor", 15 * _clamp((pf - 1) / 2), 15,
         f"dobici / gubici = {s.get('profit_factor')}; 1 = 0 bodova, 3+ = max"),
        ("2x+ trejdovi", 10 * _clamp(big / 5), 10, f"{big} pozicija s ROI >= +100%; 5 = max"),
        ("Raspršenost profita", 10 * (1 - _clamp(top)) * (total > 0), 10,
         f"najveći trejd nosi {top:.0%} dobiti; manje = profit nije jedna sretna oklada"),
    ]
    evidence = min(1.0, n / 10)
    return parts, evidence


def copy_multipliers(s, labels):
    """[(reason, multiplier)] exactly as wallets/pnl.score applies them."""
    out = []
    bad = set(labels) & BAD_LABELS
    if s.get("bot"):
        return [("bot (> 300 trejdova/dan ili drži < 30 s)", 0.0)]
    if bad:
        return [(f"oznaka: {', '.join(sorted(bad))}", 0.0)]
    h = s.get("median_hold_min")
    if h is not None and h < 2:
        out.append((f"drži < 2 min (medijan {h} min): teško ga je pratiti", 0.2))
    elif h is not None and h < 10:
        out.append((f"drži < 10 min (medijan {h} min)", 0.6))
    tpd = s.get("trades_per_day") or 0
    if tpd > 60:
        out.append((f"previše trejdova ({tpd}/dan)", 0.4))
    elif tpd < 0.3:
        out.append((f"rijetko trejda ({tpd}/dan)", 0.7))
    d = s.get("last_trade_days")
    if d is not None and d > 14:
        out.append((f"neaktivan {d} dana (14+)", 0.2))
    elif d is not None and d > 5:
        out.append((f"neaktivan {d} dana (5+)", 0.6))
    if (s.get("median_buy_sol") or 0) < 0.05:
        out.append((f"sitne kupnje (medijan {s.get('median_buy_sol')} SOL)", 0.5))
    if (s.get("free_token_ratio") or 0) > 0.3:
        out.append((f"{s['free_token_ratio']:.0%} tokena dobio besplatno (insider?)", 0.3))
    if (s.get("closed_pnl_sol") or 0) <= 0:
        out.append(("u minusu na zatvorenim pozicijama", 0.0))
    return out


def shortlist(w, min_score=COPY_MIN_SCORE, min_closed=COPY_MIN_CLOSED):
    """(passes, [reasons it does not]) for the copytrading list of `run_wallets.py copy`."""
    s = w.get("stats") or {}
    why = []
    if not s:
        return False, ["još nije ocijenjen (čeka `run_wallets.py score`)"]
    bad = set(w.get("labels") or []) & BAD_LABELS
    if bad:
        why.append(f"oznaka {', '.join(sorted(bad))}")
    if (s.get("closed") or 0) < min_closed:
        why.append(f"samo {s.get('closed', 0)} zatvorenih pozicija (treba {min_closed})")
    if (w.get("copy_score") or 0) < min_score:
        why.append(f"copy ocjena {w.get('copy_score') or 0} < {min_score}")
    return not why, why


def organic(d):
    """[(name, points, max, explanation)] for dexscreener.match.organic_score on one event_tokens.data row."""
    age_d = max(0, d.get("age_h") or 0) / 24
    liq_usd, vol_usd = d.get("liquidity") or 0, d.get("vol_24h") or 0
    buys, sells = d.get("buys_24h") or 0, d.get("sells_24h") or 0
    txs = buys + sells
    share = buys / txs if txs else 0
    turnover = vol_usd / liq_usd if liq_usd else 0
    return [
        ("Starost", min(15, 15 * math.log10(1 + age_d) / math.log10(31)), 15, f"{age_d:.1f} dana; 30+ = max"),
        ("Likvidnost", min(15, 15 * math.log10(1 + liq_usd) / 6), 15, f"${liq_usd:,.0f}; $1M = max"),
        ("Volumen 24h", min(25, 25 * math.log10(1 + vol_usd) / 6), 25, f"${vol_usd:,.0f}; $1M/dan = max"),
        ("Broj transakcija", min(15, 15 * math.log10(1 + txs) / 4), 15, f"{txs} tx/24h; 10k = max"),
        ("Omjer kupnji", 10 if 0.4 <= share <= 0.7 else 4 if 0.3 <= share <= 0.8 else 0, 10,
         f"{share:.0%} kupnji; 40-70% = zdravo"),
        ("Wash kazna", -15 if turnover > 30 else 0, 0, f"volumen = {turnover:.1f}x likvidnost; iznad 30x = -15"),
        ("Društvene mreže", min(10, 4 * (d.get("socials") or 0) + (3 if d.get("website") else 0)), 10,
         f"{d.get('socials') or 0} mreža, web {'da' if d.get('website') else 'ne'}"),
        ("Community takeover", 15 if d.get("cto") else 0, 15, "CTO na DexScreeneru"),
        ("Točan simbol", 10 if d.get("exact") else 0, 10, f"simbol = pojam '{d.get('keyword')}'"),
    ]


def event_hype(e):
    """[(name, points, max, explanation)] for event_calendar.enrich.hype_score."""
    s = e.get("signals") or {}
    try:
        from event_calendar.enrich import affinity
        aff = min(25, affinity(e))
    except Exception:
        aff = None
    try:
        days = (dt.date.fromisoformat(e["date"]) - dt.date.today()).days
    except (TypeError, ValueError):
        days = None
    parts = [
        ("Slavnost (Wikidata)", min(25, 25 * math.log10(1 + s.get("sitelinks", 0)) / math.log10(300)), 25,
         f"{s.get('sitelinks', 0)} Wikipedija; 300 = max"),
        ("Pregledi 30 dana", min(15, 15 * math.log10(1 + s.get("views_30d", 0)) / 7), 15,
         f"{s.get('views_30d', 0):,} pregleda; 10M = max"),
        ("Rast interesa", min(10, max(0, (s.get("trend", 1.0) - 1) * 10)), 10, f"trend {s.get('trend', 1.0)}x"),
        ("Polymarket volumen", min(20, 20 * math.log10(1 + s.get("pm_volume", 0)) / 8), 20,
         f"${s.get('pm_volume', 0):,.0f}; $100M = max"),
        ("Veza s kripto publikom", aff or 0, 25, "popis CRYPTO_AFFINITY u enrich.py (Elon, Trump, Doge...)"),
        ("Ručno dodan", 10 if e.get("source") == "manual" else 0, 10, "events_manual.json"),
        ("Blizina datuma", max(0, 5 - days * 0.5) if days is not None else 0, 5,
         f"za {days} dana" if days is not None else "datum nepoznat"),
    ]
    return parts
