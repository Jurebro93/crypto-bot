"""Moji tradeovi: each player logs the trades they really made (token, $ in, entry market cap) and follows them
live by market cap. Separate from the demo league; stored in league.db table real_trades.
"""
import re
import sqlite3
from urllib.parse import quote

from league import store
from ui.html import esc, num, signed, table, tlink, ts, usd
from ui.league import _err, _form, _who

ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
FIELD = 'style="width:150px"'


def parse_usd(s):
    """'26k', '1.2M', '$26,000' -> float; None if empty or unreadable."""
    s = (s or "").strip().lower().replace("$", "").replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmb]?)", s)
    if not m:
        return None
    return float(m[1]) * {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[m[2]]


def _best(pairs):
    """token -> (market cap, symbol, url) from the deepest pair."""
    out = {}
    for p in pairs:
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= out.get(t, (0, 0, 0, -1))[3]:
            out[t] = (p.get("marketCap") or p.get("fdv"), p["baseToken"].get("symbol"), p.get("url"), liq)
    return {t: v[:3] for t, v in out.items()}


def live(mints):
    if not mints:
        return {}
    try:
        from dexscreener import client
        return _best(client.tokens("solana", list(mints)))
    except Exception:
        return {}


def resolve(text):
    """Token address or DexScreener link (token or pair) -> (token, market cap, symbol)."""
    m = ADDR.search(text or "")
    if not m:
        raise ValueError("ne vidim Solana adresu ni DexScreener link")
    addr = m[0]
    got = live({addr})
    if addr in got:
        return addr, got[addr][0], got[addr][1]
    try:
        from dexscreener import client
        p = client.pair("solana", addr)
    except Exception:
        p = None
    if p:
        return p["baseToken"]["address"], p.get("marketCap") or p.get("fdv"), p["baseToken"].get("symbol")
    return addr, None, None


def page(qs, user):
    con = store.connect()
    try:
        allt = store.real_trades(con)
        now = live({t["token"] for t in allt if t["status"] == "open"})
        b = ["<h1>Moji tradeovi</h1><p class=mut>Pravi trejdovi s pravim novcem, upisani ručno i praćeni po market capu "
             "s DexScreenera. Odvojeno od demo natjecanja. PnL je procjena: ulog × (MC sada / ulazni MC − 1), "
             "bez fee-a i slippagea.</p>", _who(user), _err(qs)]
        if user:
            b.append('<form method=post action="/moji-tradeovi/add" class="card flt">'
                     '<input name=token placeholder="adresa tokena ili DexScreener link" size=46 required>'
                     f'<input name=size placeholder="ulog $ (npr. 22)" {FIELD} required>'
                     f'<input name=mcap placeholder="ulazni MC (npr. 26k)" {FIELD} title="prazno = trenutni MC">'
                     '<input name=note placeholder="napomena (neobavezno)" size=24><button>Dodaj trade</button></form>')

        def rows(trades, mine):
            out = []
            for t in trades:
                mc, _, url = now.get(t["token"], (None, None, None))
                if t["status"] == "open":
                    pnl, mc_show = store.real_pnl(t, mc), mc
                    act = _form("/moji-tradeovi/close", {"id": t["id"]}, "Zatvori",
                                f'<input name=mcap placeholder="izlazni MC" {FIELD} title="prazno = trenutni MC">') \
                        if mine else ""
                else:
                    pnl, mc_show, act = t["pnl_usd"], t["exit_mcap"], ""
                if mine:
                    act += (' <form method=post action="/moji-tradeovi/delete" style="display:inline;margin:0" '
                            "onsubmit=\"return confirm('Obrisati ovaj trade?')\">"
                            f'<input type=hidden name=id value="{t["id"]}"><button title="obriši (krivo upisano)">✕</button></form>')
                out.append(([] if mine else [esc(t["user"])]) + [
                    tlink(t["token"], t["symbol"]), ts(t["opened_ts"]), usd(t["size_usd"]), usd(t["entry_mcap"]),
                    usd(mc_show) if mc_show else ("–" if t["status"] == "open" else "$0", 0, "n"),
                    signed(mc_show / t["entry_mcap"] - 1 if mc_show is not None and t["entry_mcap"] else None, "{:+.0%}"),
                    signed(pnl), "otvoren" if t["status"] == "open" else f"zatvoren {ts(t['closed_ts'])[0]}",
                    esc(t["note"] or ""), act])
            return out

        head = ["Token", "Kupljeno", ("Ulog", "n"), ("Ulazni MC", "n"), ("MC sada / izlaz", "n"), ("Pomak", "n"),
                ("PnL $", "n"), "Status", "Napomena", ""]
        if user:
            mine = [t for t in allt if t["user"] == user]
            tot = sum((store.real_pnl(t, now.get(t["token"], (None,))[0]) or 0) if t["status"] == "open"
                      else (t["pnl_usd"] or 0) for t in mine)
            b.append(f"<h2>Tvoji ({esc(user)}) · ukupno <span class={'pos' if tot > 0 else 'neg' if tot < 0 else ''}>"
                     f"{tot:+,.2f} $</span></h2>" + table(head, rows(mine, True), empty="Još nisi upisao nijedan trade."))
        others = [t for t in allt if t["user"] != user]
        b.append("<h2>Ostali igrači</h2>" + table(["Tko"] + head[:-1], [r[:-1] for r in rows(others, False)],
                                                     empty="Nitko drugi još nije upisao trade."))
        return "Moji tradeovi", "".join(b)
    finally:
        con.close()


def post(path, form, user):
    back = "/moji-tradeovi"
    if not user:
        return f"{back}?err={quote('prijavi se svojim imenom')}"
    con = store.connect()
    try:
        if path == "/moji-tradeovi/add":
            token, mc, sym = resolve(form.get("token"))
            entry = parse_usd(form.get("mcap")) or mc
            if not entry:
                raise ValueError("DexScreener ne zna MC tog tokena, upiši ulazni MC ručno")
            store.add_real(con, user, token, sym, parse_usd(form.get("size")), entry, form.get("note"))
            msg = f"Dodano {sym or token[:6]}, ulaz ${entry:,.0f} MC"
        elif path == "/moji-tradeovi/close":
            tid = int(form.get("id") or 0)
            t = next((t for t in store.real_trades(con, user) if t["id"] == tid), None)
            if not t:
                raise ValueError("nema tog trejda")
            exit_mc = parse_usd(form.get("mcap"))
            if exit_mc is None:
                exit_mc = live({t["token"]}).get(t["token"], (None,))[0]
            pnl = store.close_real(con, user, tid, exit_mc)
            msg = f"Zatvoreno {t['symbol'] or t['token'][:6]}: {pnl:+.2f} $"
        elif path == "/moji-tradeovi/delete":
            store.delete_real(con, user, int(form.get("id") or 0))
            msg = "Obrisano."
        else:
            return back
        return f"{back}?ok={quote(msg)}"
    except (ValueError, KeyError, TypeError, sqlite3.OperationalError) as e:
        from ui.league import db_error, log_action
        log_action(user, path, f"NIJE PROŠLO: {e}")
        return f"{back}?err={quote(db_error(e))}"
    finally:
        con.close()
