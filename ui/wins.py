"""Veliki pogoci: the biggest winning trades of the last days, shown at the top of Pregled and on Natjecanje so
everyone sees what the tool caught, with how much more selling at the very top would have made.

Sources (read-only): paper.db (the bot's own demo trades: ret, max_ret) and league.db (players' trades:
ret, peak_px recorded every 15 min by league/history.snapshot). Nicholas 1.11.: "ako je bio neki veliki win
da se pokaže svima da svi vide da alat radi; napisati koliki je maksimalni povrat mogao biti da se prodalo na vrhu".
"""
import os
import sqlite3
import time

MIN_RET = 0.5      # +50% or better counts as a big win
MIN_PNL = 5.0      # and at least $5


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def collect(days=7, n=5, paper_db=None, league_db=None, now=None):
    """[{who, symbol, token, ret, pnl, peak, closed_ts}] best first by dollars, at most n."""
    from ui import data
    from league import store
    now = now or time.time()
    since = now - days * 86400
    out = []
    con = _ro(paper_db or data.PAPER_DB)
    if con:
        try:
            for sym, tok, ret, pnl, mx, ts, state in con.execute(
                    "SELECT symbol, token, ret, pnl_usd, max_ret, closed_ts, state FROM trades WHERE status='closed' "
                    "AND closed_ts>=? AND ret>=? AND pnl_usd>=?", (since, MIN_RET, MIN_PNL)):
                if '"rucno"' in (state or ""):
                    continue
                out.append({"who": "bot", "symbol": sym, "token": tok, "ret": ret, "pnl": pnl,
                            "peak": max(mx or 0, ret), "closed_ts": ts})
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    con = _ro(league_db or store.DB)
    if con:
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
            peak = "peak_px" if "peak_px" in cols else "NULL"
            for u, sym, tok, ret, pnl, ts, ep, xp, pk in con.execute(
                    f"SELECT user, symbol, token, ret, pnl_usd, closed_ts, entry_px, exit_px, {peak} FROM trades "
                    "WHERE status='closed' AND closed_ts>=? AND ret>=? AND pnl_usd>=?", (since, MIN_RET, MIN_PNL)):
                top = max(pk or 0, xp or 0)
                out.append({"who": u, "symbol": sym, "token": tok, "ret": ret, "pnl": pnl,
                            "peak": (top / ep - 1) if ep and top else ret, "closed_ts": ts})
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    return sorted(out, key=lambda w: -(w["pnl"] or 0))[:n]


def html(days=7, n=5):
    """The 🏆 box; '' when there is no big win in the window."""
    from ui.html import esc, tlink
    try:
        ws = collect(days, n)
    except Exception:  # noqa: BLE001 - never break the page
        return ""
    if not ws:
        return ""
    cards = []
    for w in ws:
        who = "Bot (demo)" if w["who"] == "bot" else esc(w["who"])
        miss = w["peak"] - w["ret"]
        top = (f'<div class=s>Na samom vrhu bilo bi <b>{w["peak"]:+.0%}</b>'
               + (f' (još {miss:+.0%})' if miss >= 0.05 else ' (prodano gotovo na vrhu)') + '</div>')
        cards.append(f'<div class=stat><div class=l>{who} · {esc(time.strftime("%d.%m.", time.localtime(w["closed_ts"])))}</div>'
                     f'<div class="v pos">{tlink(w["token"], w["symbol"])} {w["ret"]:+.0%}</div>'
                     f'<div class=s>zarada {w["pnl"]:+,.2f} $</div>{top}</div>')
    return (f'<h2 id=pogoci>🏆 Veliki pogoci <span class=mut style="font-weight:400">· zadnjih {days} dana</span></h2>'
            '<p class=tdesc>Najveći zatvoreni dobitni tradeovi bota i igrača (+50% i više). „Na samom vrhu” je koliko bi '
            'bilo da se sve prodalo na najvišoj cijeni koju je alat vidio dok je pozicija bila otvorena; Smart sell zato '
            'prodaje usput dok token raste.</p>'
            '<div class=grid style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">' + "".join(cards) + '</div>')
