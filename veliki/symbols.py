"""Token names for the trades the strategies open, and the one-time repair of the rows stored without one.

16.11. (owner, on the Autopilot page: "Kliknem na otvorenu poziciju GTA V6 ... otvori graf nekog tokena koji se zove
Umbra", the rows were listed as "Ce2gx9" and "PRVT6T"): run_ui.py hands league/auto.fast_loop the market of
ui/paper.py, whose quote is (price, liquidity, url, mcap) with NO symbol, so veliki/live.enter (and oscilator,
konsenzus, insajderi the same way) stored the mint's first six characters as the trade's name; run_trade.py mirrored
that into the real position. A name now comes, in this order, from

  the quote      when it carries one (league/copy.market does)
  midcap.db      tokens.symbol of the midcap collector (veliki/midcap.py)
  veliki.db      the list "veliki" (tokens, then hist)
  the page       what DexScreener called the token in a live row the Autopilot page already fetched (learn())

and only then the mint's prefix, which the page shows as an address ("PRVT6T…"), never as if it were a name. A source
that itself holds the prefix (both collectors store it when DexScreener sends no symbol) counts as no name.

fix(): every row whose stored symbol EQUALS its mint's first six characters gets the resolved name, in league.db
(trades, veliki_trades) and trade.db (positions, exit_fills). Nothing else is touched: no amount, price or status;
a row with any other symbol is left alone; a token nobody can name keeps its prefix. Safe to run again and again.
"""
import os
import sqlite3
import time

PREFIX_N = 6
TTL_S = 300
MAX_LEN = 20
TABLES = {"league": ("trades", "veliki_trades"), "trade": ("positions", "exit_fills")}
_C = {}       # mint -> (ts, symbol or None) from the two databases
_SEEN = {}    # mint -> symbol the page saw on DexScreener (in this process only)
_ST = {"fix": 0.0}


def is_prefix(sym, mint):
    """True when `sym` is no name: empty, or the mint's own first six characters."""
    s = (sym or "").strip()
    return not s or (bool(mint) and len(s) == PREFIX_N and s == mint[:PREFIX_N])


def clean(sym, mint):
    """The symbol as stored and shown (trimmed, at most MAX_LEN), or None when it is no name."""
    s = " ".join(str(sym or "").split())[:MAX_LEN]
    return None if is_prefix(s, mint) else s


def learn(mint, sym):
    """Remember what DexScreener calls a token (the page's live rows): used by known() after the two databases."""
    s = clean(sym, mint)
    if mint and s:
        if len(_SEEN) > 5000:
            _SEEN.clear()
        _SEEN[mint] = s


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _read(mints, mid_path=None, vel_path=None):
    """{mint: symbol} of the listed mints from midcap.db tokens, then veliki.db tokens and hist. Read-only."""
    from veliki import midcap, store
    out = {}
    q = ",".join("?" * len(mints))
    for path, tables in ((mid_path or midcap.db_path(), ("tokens",)), (vel_path or store.db_path(), ("tokens", "hist"))):
        con = _ro(path)
        if con is None:
            continue
        try:
            for tbl in tables:
                try:
                    for mint, sym in con.execute(f"SELECT mint, symbol FROM {tbl} WHERE mint IN ({q})", list(mints)):
                        s = clean(sym, mint)
                        if s and mint not in out:
                            out[mint] = s
                except sqlite3.Error:   # no such table yet
                    continue
        finally:
            con.close()
    return out


def known(mints, now=None, mid_path=None, vel_path=None):
    """{mint: symbol} of the mints somebody can name (midcap.db, veliki.db, then the page's live rows); a mint
    nobody knows is not in the answer. Cached TTL_S per mint (the answer "unknown" too)."""
    now = now or time.time()
    mints = [m for m in dict.fromkeys(mints or ()) if m]
    ask = [m for m in mints if m not in _C or now - _C[m][0] >= TTL_S]
    if ask:
        try:
            got = _read(ask, mid_path, vel_path)
        except Exception:  # noqa: BLE001 - a name is never worth an error
            got = {}
        if len(_C) > 5000:
            _C.clear()
        for m in ask:
            _C[m] = (now, got.get(m))
    out = {}
    for m in mints:
        s = (_C.get(m) or (0, None))[1] or _SEEN.get(m)
        if s:
            out[m] = s
    return out


def resolve(mint, quote_sym=None, now=None):
    """The token's symbol for a new trade: the quote's, else what known() says, else None (the caller then stores
    the mint's prefix, which every reader treats as "no name")."""
    return clean(quote_sym, mint) or known([mint], now).get(mint)


def name(mint, stored=None, now=None):
    """(text, is_address) for a page: the stored symbol when it is a name, else the resolved one, else the mint's
    prefix marked as an address ("PRVT6T…", True)."""
    s = clean(stored, mint) or known([mint], now).get(mint)
    return (s, False) if s else ((mint or "")[:PREFIX_N] + "…", True)


def reset():
    _C.clear()
    _SEEN.clear()
    _ST["fix"] = 0.0


def _fix_db(con, tables, names_fn):
    """Rows of `tables` whose symbol is their token's prefix -> the resolved symbol. {table: rows changed}."""
    out = {}
    for tbl in tables:
        try:
            toks = [r[0] for r in con.execute(
                f"SELECT DISTINCT token FROM {tbl} WHERE token IS NOT NULL AND length(symbol)=? AND "
                f"symbol=substr(token, 1, ?)", (PREFIX_N, PREFIX_N))]
        except sqlite3.Error:   # no such table / column in this database
            continue
        if not toks:
            continue
        names = names_fn(toks)
        n = 0
        for tok in toks:
            sym = names.get(tok)
            if not sym or is_prefix(sym, tok):
                continue
            n += con.execute(f"UPDATE {tbl} SET symbol=? WHERE token=? AND symbol=substr(token, 1, ?)",
                             (sym, tok, PREFIX_N)).rowcount
        if n:
            out[tbl] = n
    if out:
        con.commit()
    return out


def fix(lcon=None, tcon=None, now=None, names_fn=None):
    """The repair (see the module text). lcon / tcon: open connections to league.db / trade.db (None = skipped).
    {"league.trades": n, ...} of the rows renamed; {} when there was nothing to do."""
    names_fn = names_fn or (lambda toks: known(toks, now))
    out = {}
    for label, con in (("league", lcon), ("trade", tcon)):
        if con is None:
            continue
        for tbl, n in _fix_db(con, TABLES[label], names_fn).items():
            out[f"{label}.{tbl}"] = n
    return out


def fix_once(lcon, now=None, every_s=3600, log=print):
    """fix() from the process that owns league.db (veliki/live.tick, run_ui.py): at its first pass and then every
    every_s (a token the collectors learn to name later is repaired then). Opens trade.db itself. AP_SYMBOL_FIX=0
    turns it off (the local "before" copy of the page). Never raises."""
    now = now or time.time()
    if os.environ.get("AP_SYMBOL_FIX", "1") == "0" or (_ST["fix"] and now - _ST["fix"] < every_s):
        return {}
    _ST["fix"] = now
    tcon = None
    try:
        from trade import settings
        if os.path.exists(settings.DB):
            tcon = sqlite3.connect(settings.DB, timeout=10)
        out = fix(lcon, tcon, now)
        if out and log:
            log("nazivi tokena: popravljen simbol (bio je početak adrese) u " + ", ".join(f"{k} {v}" for k, v in out.items()))
        return out
    except Exception as e:  # noqa: BLE001 - a repair of names must never stop the exits
        if log:
            log(f"nazivi tokena: popravak nije uspio ({type(e).__name__}: {e})")
        return {}
    finally:
        if tcon is not None:
            tcon.close()
