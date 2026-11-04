"""One-time data corrections in league.db, applied on the first connect of a process (idempotent).

2.11. pairless (Nicholas chose "Ispravi na stvarnu cijenu"): on 1.11. DexScreener reported pairless at ~$0.0011
(MC ~$1.07M) while the pool's real trades (GeckoTerminal 15-min candles, pool 91Jcmk7q…) were at ~$0.0000136 around
20:43 UTC, when Jure's sale went through. Every sale of the token that evening above BAD_PX is re-priced at the real
price; partial auto sells inside the trade were at the same fake price, so the whole position is valued from scratch.
"""
import sqlite3

FEE = 0.01
PAIRLESS = {"symbol": "pairless", "since": 1793548800, "until": 1793577600,   # 1.11.2026 16:00-24:00 UTC
            "bad_px": 5e-4, "real_px": 1.36e-05, "liq": 20_000.0}
MARK = "ispravljeno 2.11.: kriva cijena DexScreenera"


def _impact(usd, liq):
    side = liq / 2
    return usd / (side + usd)


def pairless(con):
    """Returns the number of trades corrected."""
    f = PAIRLESS
    rows = con.execute(
        "SELECT id, size_usd, entry_px, entry_eff, entry_mcap, note FROM trades WHERE status='closed' "
        "AND lower(symbol)=? AND closed_ts BETWEEN ? AND ? AND exit_px>?",
        (f["symbol"], f["since"], f["until"], f["bad_px"])).fetchall()
    n = 0
    for tid, size, epx, eff, emc, note in rows:
        if not size or not eff or MARK in (note or ""):
            continue
        gross = size / eff * f["real_px"]
        proceeds = gross * (1 - FEE) * (1 - _impact(gross, f["liq"]))
        pnl = proceeds - size
        mcap = emc * f["real_px"] / epx if emc and epx else None
        con.execute("UPDATE trades SET exit_px=?, proceeds=?, pnl_usd=?, ret=?, exit_mcap=?, realized=0, note=? "
                    "WHERE id=?", (f["real_px"], proceeds, pnl, pnl / size, mcap,
                                   ((note + "; ") if note else "") + MARK, tid))
        n += 1
    if n:
        con.commit()
        print(f"league: ispravljeno {n} pairless prodaja na stvarnu cijenu", flush=True)
    return n


BOT_ROUND2_BEFORE = 1793664000   # competitions that started before 3.11.2026 00:00 UTC (the real one: 30.10.)


def bot_round2(con):
    """4.11. Nicholas: "Alat je došao do 0 ... započni drugi krug s budžetom od 1000$". The bot's 2nd round starts at
    the first start after deploy (once; the rekt check starts any later round by itself)."""
    row = con.execute("SELECT MIN(created) FROM accounts").fetchone()
    if not row or not row[0] or row[0] >= BOT_ROUND2_BEFORE:
        return False
    if con.execute("SELECT 1 FROM rekts WHERE user='bot'").fetchone():
        return False
    from league import rekt
    rekt.mark(con, rekt.BOT, None, "4.11.: Nicholas pokrenuo 2. krug (bot pao na nulu)")
    print("league: bot kreće 2. krug s $1,000", flush=True)
    return True


def apply(con):
    try:
        bot_round2(con)
    except sqlite3.OperationalError as e:
        print(f"league: 2. krug bota nije pokrenut ({e})", flush=True)
    try:
        pairless(con)
    except sqlite3.OperationalError as e:   # disk full / locked: try again next process start
        print(f"league: ispravak nije primijenjen ({e})", flush=True)
