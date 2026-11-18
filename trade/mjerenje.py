"""Mjerenje troška kruga pri većem ulogu: JEDNOM, pravim novcem (18.11.2026., vlasnik).

Pitanje vlasniku: „Smijem li izmjeriti trošak jednim pravim krugom pri 0,3 i 0,5 SOL (oko 0,01 SOL)? O tome ovisi
ulog koji ima smisla kad bude dokaza.” Odgovor: „Smiješ.”

Why: the measured real round trip at 0.1 SOL is 3-3.5 % of the stake (the network fee alone about 1 %), and the
learner's chosen trades earn +0.8 % at a 3 % cost, about +1.8 % / +2.3 % at 2 % / 1.5 %. What a round trip really costs
at a bigger stake on OUR executor decides the stake. This module measures it and only reports: veliki/replay.RT_FLOOR
and the cost model (trade/cost) are not changed by it.

What it does, once: for 0.1, 0.3 and 0.5 SOL in turn (0.1 is the baseline on the same token, minutes apart) it buys the
stake of ONE midcap of the list "veliki" and sells the whole lot again, through trade/executor.buy and
trade/executor.sell: the same two functions run_trade.py calls for the owner's manual buy and for every sale. Nothing
here quotes, signs or sends anything itself.

    token      the member of veliki.db's list with the deepest real pool (DexScreener's deepest pair), and: liquidity
               >= 2,000,000 $, 24 h volume >= 500,000 $, a quote younger than 60 s, not held by any open real position
    buy        executor.buy(manual=True, reason "mjerenje troška: <ulog> SOL"); a stake above the automatic cap of
               0.1 SOL (or above the owner's own stake limit) carries override "vlasnik odobrio mjerenje troška 18.11."
               (positions.override keeps the text). No setting, cap, flag or switch is written: the only settings key
               this module ever writes is its own.
    sell       executor.sell(close=True) of that position in the next pass of the loop
    result     krug_pct = (potrošeno - vraćeno) / ulog, split into: mreža (signature, priority, the token account's
               deposit minus the deposit that came back), utjecaj (the price impact Jupiter quoted, both sides), pomak
               cijene (the move of DexScreener's price between the two fills x the SOL swapped: a market move is not
               booked as cost) and naknade poola i rute (what is left: route and pool fees, and whatever slipped past
               the quote)

A step machine (stanja/registar "cost_measurement"), advanced once per pass of run_trade.cmd_follow (the only process
that holds the key and swaps), persisted in trade.db settings "mjerenje_troska_1811" (JSON); the same key is the
once-key: with status "gotovo" or "odustalo" nothing ever runs again.

    ceka     waiting for the conditions of the next stake; a refusal = one line and the next try in 30 min, 24 h at most
    kupnja   written and committed BEFORE executor.buy is called; a pass that FINDS this state (a restart in the middle
             of a buy) never buys: it looks for the position that buy left and goes on from what it finds
    prodaja  the position is bought; it is sold in the next pass
    prodaja_kasni  the sale was not confirmed in its first 120 s: no stake is bought any more, and the same
             executor.sell(close=True) is tried once every 120 s, 15 times at most (30 min), each try one line
    gotovo   all three stakes measured          odustalo   given up (the reason and what is open are in the record)

Safety (tests/test_mjerenje_offline.py, one test per rule):
  1. a buy only while the Autopilot is on and live, no kill switch, no "Prodaj sve", and the wallet holds at least
     1 SOL (the equity floor) + the stake + 0.05 SOL; otherwise no trade, one line, later again;
  2. one measurement in flight (the state is moved by compare-and-swap; an open measurement position refuses the next
     buy), three stakes at most (the count of the measurement's filled buys must equal the stakes finished), one
     stake at risk at a time (buy, sell, then the next buy);
  3. the position is an ordinary real position (trade.db positions, mode 'live'): the owner's page lists it with its
     sell buttons, "Prodaj sve" sells it, reconcile_pending settles it after a crash. A sale that is not confirmed
     within 120 s of its first try (three tries at most, after a restart one) cancels the stakes left and moves to
     "prodaja_kasni" (18.11., the coordinator's order before the merge: a position is not left without anybody trying
     to sell it after only 120 s): one try every 120 s, 15 at most, the count and the time of the next try in the
     record (a restart goes on in the same rhythm). A sale confirmed there ends as "odustalo" with the stake's result
     recorded; a position somebody else closed meanwhile ("Prodaj sve", the owner's sell button) ends it with one
     line; after the 15th try: "odustalo", one line with exactly what is open, and the position is left to that
     management. The kill switch and "Prodaj sve" stop buys only, never these sales;
  4. the bigger stakes go through the owner's manual override with the logged reason, never by raising anything;
  5. a buy the executor refuses ends the measurement; a buy that failed and surely did not swap is tried once more;
  6. no strategy's numbers see it: trade/executor.OWN_REASONS (the day's automatic counts and spend),
     day_pnl(strategije=True) (the day's loss stops), strategy_of -> "mjerenje", critic/data skips it, trade/cost's
     calibration skips its orders, and it writes no league.db row (no demo account, learner or shadow book reads it).
     It IS in the wallet's real result of the day;
  7. env MJERENJE_TROSKA=0 switches it off.
"""
import json
import os
import sqlite3
import time

from trade import executor

KLJUC = "mjerenje_troska_1811"
ULOZI = (0.1, 0.3, 0.5)
PREFIX = "mjerenje troška: "
RAZLOG = executor.MJERENJE_SRC                       # "mjerenje troška": the start of positions.reason / orders.reason
NADJACAVANJE = "vlasnik odobrio mjerenje troška 18.11."
MIN_LIKVIDNOST = 2_000_000.0
MIN_VOLUMEN = 500_000.0
MAX_STAROST_S = 60
POD_SOL = 1.0            # the equity floor (CLAUDE.md 16.11.); the owner's own floor counts when it is higher
REZERVA_SOL = 0.05
PAUZA_S = 20             # between two stakes, and before the one retry of a failed buy
PONOVI_S = 1800          # after a refusal
ROK_S = 86400            # from the first call; then "odustalo"
PRODAJA_ROK_S = 120      # rule 3: the first phase of a sale
PRODAJA_POKUSAJA = 3
KASNI_SVAKIH_S = 120     # rule 3, "prodaja_kasni": one try of the sale this often ...
KASNI_POKUSAJA = 15      # ... this many times at most (30 min), then "odustalo"
KUPNJA_POKUSAJA = 2      # rule 5: a failed buy is tried once more, never twice
PENDING_ROK_S = 600      # a buy still 'pending' this long after a restart is not waited for any longer
GRESKA_SVAKIH_S = 60
_REKAO = {"iskljuceno": False, "greska": 0.0}
SOL = "So11111111111111111111111111111111111111112"   # = trade/jupiter.SOL
PROCES = f"{os.getpid()}-{int(time.time())}"   # this process: a sale found by another one is "after a restart"


class Zauzeto(Exception):
    """The record changed under this pass (another process moved it): this pass does nothing more."""


# ---------- the seams the tests replace (the real ones read the network or the wallet, never write) ----------------

def _sat():
    return time.time()


def lista():
    """The list "veliki" as run_veliki.py stored it (veliki.db tokens): [{"mint", "symbol", "liq", "vol24", ...}]."""
    from veliki import store
    con = store.ro()
    if con is None:
        return []
    try:
        return store.tokens(con)
    finally:
        con.close()


def kotacije(mints):
    """{mint: {"cijena" USD, "cijena_sol" (the same pair's price in SOL when it is quoted in SOL, else None),
    "likvidnost" USD of the deepest pair, "volumen24" USD over the token's pairs, "mcap", "simbol", "sumnjivo", "ts"}}
    from DexScreener's live cache (dexscreener/client.tokens_live: what league/copy.market and the Autopilot's page
    price with). ts = when this call read it. Raises when DexScreener does not answer."""
    from dexscreener import client
    out = {}
    ts = _sat()
    for p in client.tokens_live("solana", list(mints)) or []:
        base = p.get("baseToken") or {}
        m = base.get("address")
        if m not in mints:
            continue
        d = out.setdefault(m, {"cijena": 0.0, "cijena_sol": None, "likvidnost": -1.0, "volumen24": 0.0, "mcap": None,
                               "simbol": None, "sumnjivo": None, "ts": ts})
        d["volumen24"] += _f((p.get("volume") or {}).get("h24"))
        liq, px = _f((p.get("liquidity") or {}).get("usd")), _f(p.get("priceUsd"))
        if px > 0 and liq > d["likvidnost"]:
            u_sol = (p.get("quoteToken") or {}).get("address") == SOL and _f(p.get("priceNative")) > 0
            d.update(cijena=px, cijena_sol=_f(p.get("priceNative")) if u_sol else None, likvidnost=liq,
                     mcap=p.get("marketCap") or p.get("fdv"), simbol=base.get("symbol"), sumnjivo=p.get("sumnjivo"))
    return out


def stanje_sol():
    """The wallet's free SOL (one RPC read)."""
    from trade import wallet
    return wallet.sol_balance(wallet.address())


# ---------- words ------------------------------------------------------------------------------------------------

def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _hr(x, n=2):
    return f"{x:.{n}f}".replace(".", ",")


def _g(x):
    return f"{x:g}".replace(".", ",")


def _mil(usd):
    return f"{_hr(_f(usd) / 1e6, 1)}M $"


def _reci(lines, text):
    lines.append(PREFIX + text)
    print(PREFIX + text, flush=True)


# ---------- the record -------------------------------------------------------------------------------------------

def citaj(con):
    """(the record or None, its stored text). An unreadable record reads as given up: it never trades."""
    r = con.execute("SELECT v FROM settings WHERE k=?", (KLJUC,)).fetchone()
    if not r:
        return None, None
    try:
        st = json.loads(r[0])
    except (TypeError, ValueError):
        st = None
    if not isinstance(st, dict) or "status" not in st:
        return {"status": "odustalo", "razlog": "zapis mjerenja je nečitljiv", "rezultati": []}, r[0]
    return st, r[0]


def _spremi(con, st, staro):
    """Compare-and-swap of the record: written only when the stored text is still `staro` (None = no row yet).
    Returns the new text; Zauzeto when somebody else moved it meanwhile."""
    novo = json.dumps(st, ensure_ascii=False)
    if staro is None:
        cur = con.execute("INSERT OR IGNORE INTO settings (k, v, ts, who) VALUES (?,?,?,?)",
                          (KLJUC, novo, int(time.time()), "mjerenje"))
    else:
        cur = con.execute("UPDATE settings SET v=?, ts=?, who=? WHERE k=? AND v=?",
                          (novo, int(time.time()), "mjerenje", KLJUC, staro))
    con.commit()
    if cur.rowcount != 1:
        raise Zauzeto()
    return novo


def ukljuceno():
    return os.environ.get("MJERENJE_TROSKA", "1").strip() != "0"


# ---------- the arithmetic ---------------------------------------------------------------------------------------

def rastavi(ulog, sol_u_swap, naknade_k, sol_iz_swapa, naknade_p, depozit, mid_k=None, mid_p=None, ut_k=None, ut_p=None):
    """The round trip of one stake, in SOL and in percent of the stake.
    ulog          the stake asked for (SOL)
    sol_u_swap    SOL the buy's swap took (Jupiter's fee and the pools' are inside the amounts)
    naknade_k/_p  lamports the wallet paid on top, buy / sell (signature, priority, the new token account's deposit;
                  every try, also a failed one that landed)
    sol_iz_swapa  SOL the sale's swap gave
    depozit       lamports of the token account's deposit that came back after the full sale
    mid_k, mid_p  the token's price right before the buy and right after the sale (both in SOL, or both in USD)
    ut_k, ut_p    the price impact Jupiter quoted for each side, percent of that side's amount (None: not quoted)
    pomak cijene = the price's fall between the two fills on the SOL swapped (negative = it rose): a market move, not a
    cost. utjecaj = the quoted impact of both sides (None when a side has none: it is then inside "naknade").
    naknade = what is left of the round trip after mreža, utjecaj and pomak."""
    potroseno = sol_u_swap + naknade_k / executor.LAMPORTS
    vraceno = sol_iz_swapa - naknade_p / executor.LAMPORTS + depozit / executor.LAMPORTS
    krug = (potroseno - vraceno) / ulog * 100
    mreza = (naknade_k + naknade_p - depozit) / executor.LAMPORTS / ulog * 100
    pomak = (1 - mid_p / mid_k) * sol_u_swap / ulog * 100 if mid_k and mid_p else None
    utjecaj = (ut_k * sol_u_swap + ut_p * sol_iz_swapa) / ulog if ut_k is not None and ut_p is not None else None
    naknade = krug - mreza - (utjecaj or 0.0) - (pomak or 0.0)
    return {"potroseno": round(potroseno, 9), "vraceno": round(vraceno, 9), "krug_pct": round(krug, 4),
            "mreza_pct": round(mreza, 4), "naknade_pct": round(naknade, 4),
            "utjecaj_pct": None if utjecaj is None else round(utjecaj, 4),
            "pomak_pct": None if pomak is None else round(pomak, 4),
            "bez_pomaka_pct": None if pomak is None else round(krug - pomak, 4)}


def _nalozi(con, pid):
    """What trade.db's orders say of this position: the filled buy and sale, every fee of each side, the deposit back."""
    out = {"k": None, "p": None, "naknade_k": 0, "naknade_p": 0, "depozit": 0}
    for side, status, ain, aout, cost, fee, prio, route in con.execute(
            "SELECT side, status, amount_in, amount_out, cost_pct, fee_lamports, prio_lamports, route FROM orders "
            "WHERE position_id=? ORDER BY id", (pid,)):
        fee = int(fee or 0)
        if side == "rent":
            out["depozit"] += -fee
            continue
        key = "k" if side == "buy" else "p"
        out["naknade_" + key] += fee
        if status == "ok":
            out[key] = {"amount_in": int(ain or 0), "amount_out": int(aout or 0), "trosak_kotacije_pct": cost,
                        "prioritet_lamports": int(prio or 0), "ruta": route}
    return out


def rezultat(con, st, sekundi, mid_p, ut_p, novcanik=None):
    """The record of the stake just sold (st["kupnja"] holds what the buy pass kept), or None when the orders do not
    show one filled buy and one filled sale."""
    k = st["kupnja"]
    n = _nalozi(con, st["pozicija"])
    if not n["k"] or not n["p"]:
        return None
    ulog = k["ulog"]
    # the move in SOL when the pair is quoted in SOL at both ends (the round trip is in SOL), else in USD
    u_sol = bool(k.get("mid_sol") and (mid_p or {}).get("cijena_sol"))
    mk, mp = (k["mid_sol"], mid_p["cijena_sol"]) if u_sol else (k.get("mid"), (mid_p or {}).get("cijena"))
    r = rastavi(ulog, n["k"]["amount_in"] / executor.LAMPORTS, n["naknade_k"], n["p"]["amount_out"] / executor.LAMPORTS,
                n["naknade_p"], n["depozit"], mk, mp, k.get("utjecaj_pct"), ut_p)
    r.update({"ulog": ulog, "token": st["token"]["mint"], "simbol": st["token"]["simbol"],
              "likvidnost": k.get("likvidnost"), "pozicija": st["pozicija"], "sekundi": round(sekundi, 1),
              "tokena_kupljeno": n["k"]["amount_out"], "tokena_prodano": n["p"]["amount_in"],
              "depozit_vracen_lamports": n["depozit"],
              "kupnja": {"sol": n["k"]["amount_in"] / executor.LAMPORTS, "naknada_lamports": n["naknade_k"],
                         "prioritet_lamports": n["k"]["prioritet_lamports"], "utjecaj_pct": k.get("utjecaj_pct"),
                         "trosak_kotacije_pct": n["k"]["trosak_kotacije_pct"], "ruta": n["k"]["ruta"],
                         "mid": mk, "ts": k.get("gotovo_ts")},
              "prodaja": {"sol": n["p"]["amount_out"] / executor.LAMPORTS, "naknada_lamports": n["naknade_p"],
                          "prioritet_lamports": n["p"]["prioritet_lamports"], "utjecaj_pct": ut_p,
                          "trosak_kotacije_pct": n["p"]["trosak_kotacije_pct"], "ruta": n["p"]["ruta"],
                          "mid": mp, "ts": round(k.get("gotovo_ts", 0) + sekundi, 1) if k.get("gotovo_ts") else None},
              "mid_u": ("SOL" if u_sol else "USD") if mk and mp else None,
              "novcanik": novcanik or {}})
    if k.get("uskladjeno"):
        r["napomena"] = "kupnja usklađena s lancem nakon restarta: SOL ulog je zapisana namjera, ne izmjereni iznos"
    return r


def redak(r):
    """One stake's line (without the prefix)."""
    if r.get("utjecaj_pct") is None:
        dio = f"naknade poola i rute s utjecajem {_hr(r['naknade_pct'])} % (kotacija ne daje utjecaj)"
    else:
        dio = f"naknade poola i rute {_hr(r['naknade_pct'])} %, utjecaj {_hr(r['utjecaj_pct'])} %"
    pomak = f"pomak cijene {_hr(r['pomak_pct'])} %" if r.get("pomak_pct") is not None else "pomak cijene nepoznat"
    rep = ""
    if not r.get("depozit_vracen_lamports") and (r.get("kupnja") or {}).get("naknada_lamports", 0) >= 2_000_000:
        rep = "; depozit token računa (oko 0,002 SOL) još nije vraćen i ubrojen je u mrežu"
    if r.get("napomena"):
        rep += f"; {r['napomena']}"
    return (f"{_g(r['ulog'])} SOL na {r.get('simbol') or '?'} (likvidnost {_mil(r.get('likvidnost'))}): potrošeno "
            f"{_hr(r['potroseno'], 5)} SOL, vraćeno {_hr(r['vraceno'], 5)} SOL, krug {_hr(r['krug_pct'])} % (mreža "
            f"{_hr(r['mreza_pct'])} %, {dio}, {pomak}), {r['sekundi']:.0f} s{rep}")


def sazetak(rez):
    """The summary line of the stakes measured (without the prefix), None when there is none."""
    if not rez:
        return None
    bez = " / ".join(f"{_hr(r['bez_pomaka_pct'], 1)} %" if r.get("bez_pomaka_pct") is not None else "nepoznato" for r in rez)
    return (f"krug pri {' / '.join(_g(r['ulog']) for r in rez)} SOL: "
            f"{' / '.join(_hr(r['krug_pct'], 1) + ' %' for r in rez)} (bez pomaka cijene: {bez})")


def tekst(con):
    """What the council's direction brief says of it (vijece/smjer.IZVORI), None while nothing is measured."""
    st, _raw = citaj(con)
    rez = (st or {}).get("rezultati") or []
    if not rez:
        return None
    sim = rez[0].get("simbol") or "?"
    kraj = {"gotovo": "sva tri uloga izmjerena", "odustalo": f"prekinuto ({st.get('razlog') or 'bez razloga'})"}.get(
        st.get("status"), "u tijeku")
    dijelovi = "; ".join(
        f"{_g(r['ulog'])} SOL: mreža {_hr(r['mreza_pct'])} %, naknade poola i rute {_hr(r['naknade_pct'])} %"
        + (f", utjecaj {_hr(r['utjecaj_pct'])} %" if r.get("utjecaj_pct") is not None else "")
        + (f", pomak cijene {_hr(r['pomak_pct'])} %" if r.get("pomak_pct") is not None else "") for r in rez)
    return (f"jedan pravi krug (kupnja pa prodaja) na {sim}, likvidnost {_mil(rez[0].get('likvidnost'))}: {sazetak(rez)}; "
            f"{dijelovi}; {kraj}. Samo mjerenje: model troška i najmanji povratni trošak nisu promijenjeni")


# ---------- the conditions ---------------------------------------------------------------------------------------

def drzani(con):
    return {r[0] for r in con.execute("SELECT DISTINCT token FROM positions WHERE mode='live' AND status IN "
                                      "('open','pending')") if r[0]}


def otvorene(con):
    """The measurement's own positions that are still open (rule 2): [(id, symbol, qty_left, sol_in)]."""
    return con.execute("SELECT id, symbol, qty_left, sol_in FROM positions WHERE mode='live' AND status IN "
                       "('open','pending') AND COALESCE(reason, '') LIKE ?", (RAZLOG + "%",)).fetchall()


def kupljeno(con):
    """How many of the measurement's buys filled, ever (rule 2: never more than the three stakes)."""
    return con.execute("SELECT COUNT(*) FROM orders WHERE side='buy' AND mode='live' AND status='ok' "
                       "AND COALESCE(reason, '') LIKE ?", (RAZLOG + "%",)).fetchone()[0]


def uvjeti(con, cfg):
    """Rule 1 without the balance: why no buy may go out now, or None. The switch and "Prodaj sve" are read again from
    trade.db here (the loop's cfg is as old as its pass)."""
    try:
        from trade import settings
        cfg = settings.merged(cfg, con)
    except Exception:  # noqa: BLE001 - unreadable settings: nothing is bought
        return "postavke se ne mogu pročitati"
    if not executor.is_live(cfg):
        return "Autopilot nije uključen uživo (prekidač, TRADE_LIVE ili ključ)"
    if os.path.exists(executor.STOP_FILE):
        return "kill switch je aktivan (trade/STOP)"
    if cfg.get("sell_all"):
        return "„Prodaj sve” je u tijeku"
    return None


def potrebno(cfg, ulog):
    """The balance a buy of `ulog` needs: the equity floor (1 SOL, the owner's when higher) + the stake + 0.05."""
    return max(POD_SOL, executor.equity_floor(cfg)) + ulog + REZERVA_SOL


def ocijeni(q, now):
    """Why this quote does not qualify (a short key), or None."""
    if not q or not q.get("cijena") or q.get("sumnjivo"):
        return "bez pouzdane cijene"
    if now - (q.get("ts") or 0) >= MAX_STAROST_S:
        return "kotacija starija od 60 s"
    if q.get("likvidnost", 0) < MIN_LIKVIDNOST:
        return "likvidnost ispod 2M $"
    if q.get("volumen24", 0) < MIN_VOLUMEN:
        return "volumen 24 h ispod 500k $"
    if q.get("mcap") and q["likvidnost"] > _f(q["mcap"]):
        return "lažni pool (likvidnost veća od MC-a)"
    return None


def izbor(con, now):
    """(token {"mint", "simbol"}, its quote, None) for the list's member with the deepest pool that qualifies, or
    (None, None, why nothing does)."""
    red = [r for r in (lista() or []) if r.get("mint")]
    if not red:
        return None, None, "lista veliki je prazna ili se ne može pročitati"
    kv = kotacije([r["mint"] for r in red]) or {}
    ima = drzani(con)
    zasto, kand = {}, []
    for r in red:
        q = kv.get(r["mint"])
        w = "u otvorenoj pravoj poziciji" if r["mint"] in ima else ocijeni(q, now)
        if w:
            zasto[w] = zasto.get(w, 0) + 1
        else:
            kand.append((q["likvidnost"], r, q))
    if not kand:
        return None, None, (f"nijedan od {len(red)} tokena liste veliki ne zadovoljava ("
                            + ", ".join(f"{k}: {v}" for k, v in sorted(zasto.items())) + ")")
    _liq, r, q = max(kand, key=lambda x: x[0])
    return {"mint": r["mint"], "simbol": q.get("simbol") or r.get("symbol") or r["mint"][:6]}, q, None


def provjera(con, cfg, ulog, now, stanje, mint):
    """The executor's own gate, asked before anything is written (executor.buy_checks, as the page asks it for the
    owner's buy): (why the buy must wait or None, True when the stake itself is over the owner's limit: the one reason
    the override is for). Every other reason, hard or soft, makes the measurement wait."""
    ulog_preko, ostalo = False, []
    for _kind, key, text in executor.buy_checks(con, cfg, ulog, now, True, balance=stanje, token=mint, manual=True):
        if key == "stake" and ulog > 0:
            ulog_preko = True
        else:
            ostalo.append(text)
    return ("; ".join(ostalo) or None), ulog_preko


# ---------- the step machine -------------------------------------------------------------------------------------

def korak(con, cfg, now=None, stani=False):
    """One step, called once per pass of run_trade.cmd_follow. At most ONE swap a call (a buy or a sale). stani: the
    loop is stopping (SIGTERM): no new buy is started, a sale still goes out. Returns the lines it logged."""
    lines = []
    if not ukljuceno():
        if not _REKAO["iskljuceno"]:
            _REKAO["iskljuceno"] = True
            _reci(lines, "isključeno (MJERENJE_TROSKA=0)")
        return lines
    st, raw = citaj(con)
    if st is not None and st.get("status") in ("gotovo", "odustalo"):
        return lines
    now = now or _sat()
    try:
        if st is None:
            st = {"status": "ceka", "start_ts": int(now), "i": 0, "pokusaja": 0, "sljedeci_ts": 0, "token": None,
                  "rezultati": []}
            raw = _spremi(con, st, None)
        if st["status"] == "ceka":
            _ceka(con, cfg, st, raw, now, stani, lines)
        elif st["status"] == "kupnja":
            _nakon_prekida(con, st, raw, now, lines)
        elif st["status"] == "prodaja":
            _prodaja(con, cfg, st, raw, now, lines)
        elif st["status"] == "prodaja_kasni":
            _kasni(con, cfg, st, raw, now, lines)
        else:
            _kraj(con, st, raw, now, lines, "odustalo", f"nepoznato stanje zapisa ({st['status']})")
    except Zauzeto:
        _reci(lines, "zapis mjerenja je u međuvremenu promijenio drugi proces; ovaj prolaz ne radi ništa")
    return lines


def _kraj(con, st, raw, now, lines, status, razlog=None, tiho=False):
    """The end: "gotovo" or "odustalo", with the summary of what was measured and, when given up, why and what is open.
    tiho: the record only, no line (the caller says its own one line)."""
    st["status"] = status
    st["kraj_ts"] = int(now)
    if razlog:
        st["razlog"] = razlog
    s = sazetak(st.get("rezultati") or [])
    otv = otvorene(con)
    if st.get("pozicija") and st["pozicija"] not in {o[0] for o in otv}:   # a buy matched with the chain after a
        otv += con.execute("SELECT id, symbol, qty_left, sol_in FROM positions WHERE id=? AND mode='live' AND status "
                           "IN ('open','pending')", (st["pozicija"],)).fetchall()   # restart carries another reason
    if otv:
        st["otvoreno"] = [{"pozicija": i, "simbol": sym, "tokena": q, "ulozeno_sol": sin} for i, sym, q, sin in otv]
    raw = _spremi(con, st, raw)
    if tiho:
        return raw
    if status == "odustalo":
        _reci(lines, f"odustalo: {razlog}" + ("" if otv else "; nijedna pozicija mjerenja nije otvorena"))
        for i, sym, q, sin in otv:
            _reci(lines, f"otvoreno ostaje: pozicija #{i} {sym or '?'}, {q or 0} jedinica tokena, uloženo "
                         f"{_hr(sin or 0, 4)} SOL; prepuštena redovnom upravljanju (stranica Autopilot: gumbi za prodaju, "
                         "„Prodaj sve”); automatskog stopa nema, mjerenje je više ne dira")
    if s:
        _reci(lines, s + ("" if status == "gotovo" else " (nepotpuno)"))
    return raw


def _odgodi(con, st, raw, now, lines, razlog):
    ulog = ULOZI[st["i"]]
    st["sljedeci_ts"] = int(now) + PONOVI_S
    st["zadnje"] = razlog
    raw = _spremi(con, st, raw)
    _reci(lines, f"{_g(ulog)} SOL: bez kupnje: {razlog}; ponovno za {PONOVI_S // 60} min")
    return raw


def _ceka(con, cfg, st, raw, now, stani, lines):
    if now < (st.get("sljedeci_ts") or 0):
        return
    if st["i"] >= len(ULOZI):   # never more than the three stakes
        return _kraj(con, st, raw, now, lines, "gotovo")
    if now - st["start_ts"] >= ROK_S:
        return _kraj(con, st, raw, now, lines, "odustalo", "uvjeti za kupnju nisu se stekli u 24 h"
                     + (f" (zadnje: {st['zadnje']})" if st.get("zadnje") else ""))
    if stani:
        return
    ulog = ULOZI[st["i"]]
    why = uvjeti(con, cfg)
    if why:
        return _odgodi(con, st, raw, now, lines, why)
    otv = otvorene(con)
    if otv:   # rule 2: one stake at risk
        return _kraj(con, st, raw, now, lines, "odustalo",
                     f"pozicija mjerenja #{otv[0][0]} je još otvorena prije sljedeće kupnje")
    n = kupljeno(con)
    if n != st["i"]:   # rule 2: the books and the record must agree before any further buy
        return _kraj(con, st, raw, now, lines, "odustalo",
                     f"u nalozima je {n} ispunjenih kupnji mjerenja, a završenih uloga {st['i']}")
    if st.get("pokusaja", 0) >= KUPNJA_POKUSAJA:   # rule 5
        return _kraj(con, st, raw, now, lines, "odustalo", f"kupnja {_g(ulog)} SOL nije prošla ni drugi put")
    try:
        stanje = float(stanje_sol())
    except Exception as e:  # noqa: BLE001 - no balance, no buy
        return _odgodi(con, st, raw, now, lines, f"stanje novčanika se ne može pročitati ({type(e).__name__})")
    treba = potrebno(cfg, ulog)
    if stanje < treba - 1e-9:
        return _odgodi(con, st, raw, now, lines,
                       f"stanje {_hr(stanje, 4)} SOL, treba {_hr(treba, 2)} (pod {_g(max(POD_SOL, executor.equity_floor(cfg)))}"
                       f" + ulog {_g(ulog)} + {_g(REZERVA_SOL)})")
    try:
        if st.get("token"):   # the same token for every stake: asked again, never swapped for another
            tok = st["token"]
            q = (kotacije([tok["mint"]]) or {}).get(tok["mint"])
            why = "u otvorenoj pravoj poziciji" if tok["mint"] in drzani(con) else ocijeni(q, now)
            why = f"{tok['simbol']}: {why}" if why else None
        else:
            tok, q, why = izbor(con, now)
    except Exception as e:  # noqa: BLE001 - DexScreener or veliki.db did not answer
        return _odgodi(con, st, raw, now, lines, f"kotacije nisu dostupne ({type(e).__name__})")
    if why:
        return _odgodi(con, st, raw, now, lines, why)
    why, ulog_preko = provjera(con, cfg, ulog, now, stanje, tok["mint"])
    if why:
        return _odgodi(con, st, raw, now, lines, f"provjera kupnje: {why}")
    nadjacaj = ulog_preko or ulog > executor.auto_cap() + 1e-9
    pid_prije = con.execute("SELECT COALESCE(MAX(id), 0) FROM positions").fetchone()[0]
    st.update(status="kupnja", token=tok, pokusaja=st.get("pokusaja", 0) + 1, pozicija=None,
              kupnja={"ulog": ulog, "ts": int(now), "pid_prije": pid_prije, "mid": q["cijena"],
                      "mid_sol": q.get("cijena_sol"),
                      "likvidnost": q["likvidnost"], "volumen24": q["volumen24"], "stanje_prije": stanje,
                      "nadjacano": bool(nadjacaj), "proces": PROCES})
    raw = _spremi(con, st, raw)   # committed BEFORE the buy: a pass that finds "kupnja" never buys
    _reci(lines, f"kupujem {_g(ulog)} SOL {tok['simbol']} (likvidnost {_mil(q['likvidnost'])}, volumen 24 h "
                 f"{_mil(q['volumen24'])})"
                 + (f" ručnim nadjačavanjem limita uloga, razlog: {NADJACAVANJE}" if nadjacaj else
                    " unutar limita uloga, bez nadjačavanja"))
    r = executor.buy(con, cfg, tok["mint"], tok["simbol"], size_sol=ulog, now=now, reason=f"{RAZLOG}: {_g(ulog)} SOL",
                     manual=True, override=NADJACAVANJE if nadjacaj else None)
    _nakon_kupnje(con, st, raw, now, lines, r)


def _nakon_kupnje(con, st, raw, now, lines, r):
    """What executor.buy answered -> the next state. open = the swap is confirmed (Jupiter's /execute said Success, or
    the tokens are in the wallet); blocked = the executor's own checks refused it; failed = the swap did not go."""
    ulog = st["kupnja"]["ulog"]
    ishod, greska = r.get("status"), r.get("error")
    if ishod == "open" and r.get("mode") == "live":
        st["status"] = "prodaja"
        st["pozicija"] = r.get("id")
        st["prodaja_od"], st["prodaja_pokusaja"] = None, 0
        st["kupnja"].update(gotovo_ts=round(_sat(), 1), utjecaj_pct=r.get("impact_pct"),
                            nadjacani_limiti=list(r.get("overridden") or []))
        try:
            st["kupnja"]["stanje_poslije"] = float(stanje_sol())
        except Exception:  # noqa: BLE001 - the cross-check only
            st["kupnja"]["stanje_poslije"] = None
        try:
            _spremi(con, st, raw)
        except Zauzeto:
            _reci(lines, f"kupnja {_g(ulog)} SOL je prošla (pozicija #{r.get('id')}), ali je zapis mjerenja promijenio "
                         "drugi proces: pozicija ostaje redovnom upravljanju")
        return
    if ishod == "open":   # a probe row: the Autopilot went off between the check and the buy; no money moved
        return _kraj(con, st, raw, now, lines, "odustalo",
                     f"kupnja {_g(ulog)} SOL je prošla samo kao probna (Autopilot više nije uživo), pozicija #{r.get('id')}")
    if ishod == "blocked":   # rule 5: refused by the executor's own checks = the end
        return _kraj(con, st, raw, now, lines, "odustalo", f"izvršitelj je odbio kupnju {_g(ulog)} SOL: {greska}")
    if r.get("retry") and st.get("pokusaja", 0) < KUPNJA_POKUSAJA:   # surely no swap: once more, after the pause
        st["status"] = "ceka"
        st["sljedeci_ts"] = int(now) + PAUZA_S
        _spremi(con, st, raw)
        _reci(lines, f"kupnja {_g(ulog)} SOL nije prošla ({greska}); još jedan pokušaj za {PAUZA_S} s")
        return
    return _kraj(con, st, raw, now, lines, "odustalo",
                 f"kupnja {_g(ulog)} SOL nije prošla ({greska})"
                 + ("" if r.get("retry") else "; ishod swapa nije siguran: provjeri novčanik prije bilo čega"))


def _nakon_prekida(con, st, raw, now, lines):
    """A pass that finds "kupnja": the process stopped between the record and the end of executor.buy. Never buys:
    the position that buy left (written 'pending' before the swap went out; executor.reconcile_pending matches it
    with the wallet) decides."""
    k = st["kupnja"]
    r = con.execute("SELECT id, status, mode, reason FROM positions WHERE id>? AND token=? AND opened_ts=? ORDER BY id "
                    "LIMIT 1", (k.get("pid_prije") or 0, st["token"]["mint"], int(k["ts"]))).fetchone()
    ulog = k["ulog"]
    if r is None:   # stopped before buy() wrote anything: nothing was sent
        if st.get("pokusaja", 0) < KUPNJA_POKUSAJA:
            st["status"] = "ceka"
            st["sljedeci_ts"] = int(now) + PAUZA_S
            _spremi(con, st, raw)
            _reci(lines, f"kupnja {_g(ulog)} SOL prekinuta prije slanja (restart); još jedan pokušaj za {PAUZA_S} s")
            return
        return _kraj(con, st, raw, now, lines, "odustalo", f"kupnja {_g(ulog)} SOL prekinuta i drugi put")
    pid, stanje_poz, mode, why = r
    st["pozicija"] = pid
    if stanje_poz == "pending":
        if now - k["ts"] > PENDING_ROK_S:
            return _kraj(con, st, raw, now, lines, "odustalo",
                         f"kupnja {_g(ulog)} SOL (pozicija #{pid}) nije usklađena s lancem {PENDING_ROK_S // 60} min "
                         "nakon restarta")
        return   # reconcile_pending settles it (after 60 s); asked again in the next pass
    if stanje_poz == "open" and mode == "live":
        st["status"] = "prodaja"
        st["pozicija"] = pid
        st["prodaja_od"], st["prodaja_pokusaja"], st["nakon_restarta"] = None, 0, True
        k["proces"] = PROCES
        k.update(gotovo_ts=round(_sat(), 1), utjecaj_pct=None, uskladjeno=not executor.is_mjerenje(why))
        _spremi(con, st, raw)
        _reci(lines, f"nakon restarta: kupnja {_g(ulog)} SOL je u knjizi (pozicija #{pid}); prodajem jednom")
        return
    if stanje_poz == "closed":
        return _kraj(con, st, raw, now, lines, "odustalo",
                     f"pozicija #{pid} ({_g(ulog)} SOL) je zatvorena izvan mjerenja nakon restarta")
    return _kraj(con, st, raw, now, lines, "odustalo",
                 f"kupnja {_g(ulog)} SOL nije prošla prije restarta ({why}); ne ponavljam je naslijepo")


def _izmjeri(con, st, lines, gotovo, p):
    """After a confirmed sale: the price after it, the wallet's balance, and the stake's record, appended and logged.
    (the record or None when the orders do not show one filled buy and one filled sale, seconds from the buy)."""
    mid_p = None
    try:   # the price after the sale (the sale itself never waits for a price)
        q = (kotacije([st["token"]["mint"]]) or {}).get(st["token"]["mint"]) or {}
        mid_p = q if q.get("cijena") and not q.get("sumnjivo") else None
    except Exception:  # noqa: BLE001 - no price: the move is "nepoznat", the measurement stands
        mid_p = None
    sek = gotovo - (st["kupnja"].get("gotovo_ts") or st.get("prodaja_od") or gotovo)
    nov = {"prije_kupnje": st["kupnja"].get("stanje_prije"), "poslije_kupnje": st["kupnja"].get("stanje_poslije")}
    try:
        nov["poslije_prodaje"] = float(stanje_sol())
    except Exception:  # noqa: BLE001 - the cross-check only
        nov["poslije_prodaje"] = None
    rez = rezultat(con, st, sek, mid_p, p.get("impact_pct"), nov)
    if rez is not None:
        st["rezultati"].append(rez)
        _reci(lines, redak(rez))
    return rez, sek


def _u_kasni(con, st, raw, now, lines, zasto, odmah=False):
    """prodaja -> prodaja_kasni: the sale was not confirmed in its first phase. The stakes left are cancelled for good
    (no state after this one buys), and the sale is tried again every KASNI_SVAKIH_S, KASNI_POKUSAJA times at most.
    odmah: the first of those tries goes out in the next pass (the first phase ran out of time, not of tries)."""
    pid, ulog = st["pozicija"], st["kupnja"]["ulog"]
    st["status"] = "prodaja_kasni"
    st["kasni_od"] = round(now, 1)
    st["kasni_pokusaja"] = 0
    st["sljedeci_ts"] = int(now) if odmah else int(now) + KASNI_SVAKIH_S
    st["otkazano"] = list(ULOZI[st["i"] + 1:])
    st["zadnje"] = zasto
    raw = _spremi(con, st, raw)
    ostali = (" (" + ", ".join(_g(u) for u in st["otkazano"]) + " SOL)") if st["otkazano"] else ""
    _reci(lines, f"prodaja pozicije #{pid} ({_g(ulog)} SOL) {zasto}; preostali ulozi se više ne kupuju{ostali}; prodaju "
                 f"pokušavam svake {KASNI_SVAKIH_S // 60} min, najviše {KASNI_POKUSAJA} puta")
    return raw


def _prodaja(con, cfg, st, raw, now, lines):
    """The whole lot is sold with executor.sell(close=True). Rule 3, the first phase: three tries at most (one after a
    restart), all within 120 s of the first; a sale not confirmed by then goes on in "prodaja_kasni" (_kasni)."""
    pid, ulog = st["pozicija"], st["kupnja"]["ulog"]
    r = con.execute("SELECT status, symbol, qty_left FROM positions WHERE id=?", (pid,)).fetchone()
    if r is None or r[0] != "open":
        return _kraj(con, st, raw, now, lines, "odustalo",
                     f"pozicija #{pid} ({_g(ulog)} SOL) više nije otvorena prije prodaje mjerenja "
                     f"({'nema je' if r is None else r[0]}): zatvorilo ju je redovno upravljanje, ulog nije izmjeren")
    if st["kupnja"].get("proces") != PROCES and not st.get("nakon_restarta"):
        st["nakon_restarta"] = True   # bought by a process that is gone: one try of the sale, then rule 3
        st["kupnja"]["proces"] = PROCES   # (executor.sell asks the wallet first: a sale that landed is not sent twice)
        st["prodaja_pokusaja"] = 0
        _reci(lines, f"nakon restarta: pozicija #{pid} ({_g(ulog)} SOL) je kupljena, a nije prodana; prodajem jednom")
    if st.get("prodaja_od") is None:
        st["prodaja_od"] = round(now, 1)
    elif now - st["prodaja_od"] > PRODAJA_ROK_S:
        return _u_kasni(con, st, raw, now, lines, f"nije potvrđena u {PRODAJA_ROK_S} s", odmah=True)
    najvise = 1 if st.get("nakon_restarta") else PRODAJA_POKUSAJA
    if st.get("prodaja_pokusaja", 0) >= najvise:   # tries that ended in an error of the pass itself count too
        return _u_kasni(con, st, raw, now, lines, f"nije potvrđena nakon {st['prodaja_pokusaja']} pokušaja")
    st["prodaja_pokusaja"] = st.get("prodaja_pokusaja", 0) + 1
    raw = _spremi(con, st, raw)   # the try is counted BEFORE it goes out: an error or a restart here cannot add tries
    p = executor.sell(con, cfg, pid, close=True, now=now, reason=f"{RAZLOG}: prodaja")
    gotovo = _sat()
    ishod = p.get("status")
    if ishod == "ok":
        rez, _sek = _izmjeri(con, st, lines, gotovo, p)
        if rez is None:
            return _kraj(con, st, raw, now, lines, "odustalo",
                         f"prodaja pozicije #{pid} je prošla, ali nalozi ne daju iznose kupnje i prodaje: ulog "
                         f"{_g(ulog)} SOL nije izmjeren")
        kasno = gotovo - st["prodaja_od"] > PRODAJA_ROK_S
        st["i"] += 1
        st.update(pokusaja=0, pozicija=None, prodaja_od=None, prodaja_pokusaja=0, nakon_restarta=False, kupnja=None)
        if kasno:
            return _kraj(con, st, raw, now, lines, "odustalo",
                         f"prodaja {_g(ulog)} SOL potvrđena tek nakon {PRODAJA_ROK_S} s: sljedeći ulog se ne kupuje")
        if st["i"] >= len(ULOZI):
            return _kraj(con, st, raw, now, lines, "gotovo")
        st["status"] = "ceka"
        st["sljedeci_ts"] = int(now) + PAUZA_S
        _spremi(con, st, raw)
        return
    if ishod == "wait":   # the executor's own backoff after a failed try: not a try of ours
        st["prodaja_pokusaja"] -= 1
        _spremi(con, st, raw)
        return
    greska = p.get("error") or ishod
    if ishod == "noop":
        return _kraj(con, st, raw, now, lines, "odustalo",
                     f"pozicija #{pid} ({_g(ulog)} SOL): u novčaniku nema tokena za prodaju, izvršitelj ju je zatvorio; "
                     "ulog nije izmjeren")
    if st.get("nakon_restarta") or st["prodaja_pokusaja"] >= PRODAJA_POKUSAJA:
        return _u_kasni(con, st, raw, now, lines, f"nije prošla ({greska}), pokušaja {st['prodaja_pokusaja']}")
    _reci(lines, f"prodaja pozicije #{pid} ({_g(ulog)} SOL) nije prošla ({greska}); pokušaj {st['prodaja_pokusaja']} od "
                 f"{PRODAJA_POKUSAJA}, najdulje {PRODAJA_ROK_S} s od prvog")


def _kasni(con, cfg, st, raw, now, lines):
    """"prodaja_kasni" (rule 3, the second phase): never buys. One try of the same executor.sell(close=True) every
    KASNI_SVAKIH_S, KASNI_POKUSAJA at most, each one line. It is a sale: the kill switch and "Prodaj sve" do not hold
    it, and the executor's own conditions apply as to any sale (its backoff after failed tries answers "wait": that
    call is a try of ours all the same, so the phase ends after KASNI_POKUSAJA calls). The count and the time of the
    next try are written BEFORE the call, so an error or a restart goes on in the same rhythm, never in a burst.
    A position that is not open any more (sold by "Prodaj sve", the owner's button, or by hand) ends it with one line."""
    pid, ulog = st["pozicija"], st["kupnja"]["ulog"]

    def tudje(kako):
        s = sazetak(st.get("rezultati") or [])
        _kraj(con, st, raw, now, lines, "odustalo",
              f"pozicija #{pid} ({_g(ulog)} SOL) zatvorena izvan mjerenja ({kako}); ulog nije izmjeren", tiho=True)
        _reci(lines, f"pozicija #{pid} ({_g(ulog)} SOL) je već zatvorena izvan mjerenja ({kako}): mjerenje završeno, "
                     "ulog nije izmjeren" + (f"; {s} (nepotpuno)" if s else ""))

    r = con.execute("SELECT status FROM positions WHERE id=?", (pid,)).fetchone()
    if r is None or r[0] != "open":
        return tudje("„Prodaj sve” ili vlasnikova prodaja")
    if now < (st.get("sljedeci_ts") or 0):
        return
    k = st.get("kasni_pokusaja", 0)
    kraj = (f"prodaja pozicije #{pid} ({_g(ulog)} SOL) nije potvrđena ni nakon {KASNI_POKUSAJA} pokušaja u "
            f"{KASNI_POKUSAJA * KASNI_SVAKIH_S // 60} min")
    if k >= KASNI_POKUSAJA:   # the last try was cut off (an error, a restart): it counted, no further one
        return _kraj(con, st, raw, now, lines, "odustalo", kraj)
    k += 1
    st["kasni_pokusaja"] = k
    st["sljedeci_ts"] = int(now) + KASNI_SVAKIH_S
    raw = _spremi(con, st, raw)
    try:
        p = executor.sell(con, cfg, pid, close=True, now=now, reason=f"{RAZLOG}: prodaja")
    except Exception as e:  # noqa: BLE001 - e.g. the RPC of the wallet check: this try is spent, the next in 2 min
        p = {"error": f"{type(e).__name__}: {e}"[:200]}   # no answer of the executor: not confirmed
        try:
            con.rollback()
        except sqlite3.Error:
            pass
    gotovo = _sat()
    ishod = p.get("status")
    if ishod == "ok":
        rez, sek = _izmjeri(con, st, lines, gotovo, p)
        minuta = max(1, round(sek / 60))
        _reci(lines, f"pozicija #{pid} prodana nakon {minuta} min")
        if rez is not None:
            st["i"] += 1
        st.update(pokusaja=0, pozicija=None, prodaja_od=None, prodaja_pokusaja=0, nakon_restarta=False, kupnja=None)
        return _kraj(con, st, raw, now, lines, "odustalo",
                     f"prodaja {_g(ulog)} SOL potvrđena tek nakon {minuta} min"
                     + ("" if rez is not None else ", a nalozi ne daju iznose kupnje i prodaje (ulog nije izmjeren)")
                     + ": preostali ulozi se ne kupuju")
    if ishod == "noop":   # nothing of it in the wallet: the executor closed the record
        return tudje("u novčaniku više nema tokena")
    if k >= KASNI_POKUSAJA:
        return _kraj(con, st, raw, now, lines, "odustalo", kraj)
    greska = ("izvršitelj čeka svoj razmak nakon neuspjelih prodaja" if ishod == "wait" else p.get("error") or ishod)
    _reci(lines, f"prodaja pozicije #{pid} i dalje nije potvrđena (pokušaj {k}/{KASNI_POKUSAJA}); ponovno za "
                 f"{KASNI_SVAKIH_S // 60} min; razlog: {greska}")


def korak_sigurno(con, cfg, stani=False):
    """korak() for the trade loop: an error here is one line a minute and never the loop's. Whatever raised, the
    record keeps the last state written, and a pass that finds "kupnja" never buys."""
    try:
        return korak(con, cfg, stani=stani)
    except Exception as e:  # noqa: BLE001
        if time.time() - _REKAO["greska"] >= GRESKA_SVAKIH_S:
            _REKAO["greska"] = time.time()
            print(f"{PREFIX}greška koraka ({type(e).__name__}: {e}); sljedeći prolaz nastavlja od zapisanog stanja",
                  flush=True)
        try:
            con.rollback()
        except sqlite3.Error:
            pass
        return []
