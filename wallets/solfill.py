"""Sale amounts missing in hype.db chain_trades, filled from the transaction itself (one getTransaction each).

10.11. (Grok MCP audit 9): get_wallet_history showed sells with sol null. kol/chainwatch.parse wrote every sell that
came through the Helius webhook with sol None: it summed only the SOL a wallet SPENT, so a sale had nothing to sum.
The writer now keeps what the payload shows (chainwatch.sol_received); this job fills the rows written before that
and the few a payload could not price:

  rows    chain_trades with sol NULL and a signature, newest first, never a signature looked at before (chain_solfill)
  RPC     getTransaction (jsonParsed, maxSupportedTransactionVersion 0) once per signature through wallets/rpc._rpc
          (Helius; event_calendar/http counts it in usage.db like every Helius call: usage/meter.py)
  SOL     the wallet's lamports after minus before (its index in accountKeys) plus its wSOL token balance change: the
          net SOL it got for a sale, a positive number as chainwatch writes it, split evenly over the tokens the same
          transaction sold (a buy row, none of which is NULL today, would get the SOL it spent)
  left    not found, failed, a token-for-token swap (no RPC call for those), the token did not move, no SOL leg: sol
          stays NULL and the signature goes to chain_solfill with the reason, so it is never paid for again
  cost    at most SOLFILL_MAX_NIGHT (200) getTransaction calls per Zagreb night, only inside the night window
          (ops/heavy.NIGHT, 01-06 Zagreb, CLAUDE.md). start.sh runs it hourly through "ops.heavy --night": a deploy
          in the night does not cost a second budget, the night's calls are counted in chain_solfill_runs.

    python3 -m wallets.solfill                     one pass (start.sh)
    python3 -m wallets.solfill --dry               only count what is missing, no RPC call
    python3 -m wallets.solfill --force --max 20    by hand, outside the night window too
"""
import argparse
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HYPE_DB = os.path.join(ROOT, "hype.db")   # the same file kol/chainwatch.HYPE_DB writes (start.sh symlinks it)
WSOL = "So11111111111111111111111111111111111111112"
DUST_SOL = 0.001          # wallets/rpc.DUST_SOL: a smaller SOL leg is a fee or rent, not a price
MAX_NIGHT = int(os.environ.get("SOLFILL_MAX_NIGHT", "200"))   # getTransaction calls per Zagreb night
MAX_ERRORS = 3            # this many failed calls in a row: the RPC is down or limiting us, try again next night
KEEP_DAYS = 15            # chain_trades keeps 14 days (kol/chainwatch.KEEP_DAYS, ops/prune.CHAIN_KEEP_DAYS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS chain_solfill (sig TEXT PRIMARY KEY, ts INTEGER, tried INTEGER, why TEXT);
CREATE TABLE IF NOT EXISTS chain_solfill_runs (night TEXT PRIMARY KEY, calls INTEGER, filled INTEGER, ts INTEGER);
"""


def fetch_tx(sig):
    """The jsonParsed transaction of `sig` from Helius (None when the node does not know it)."""
    from wallets import rpc
    res, _cached = rpc._rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                                                     "commitment": "confirmed"}])
    return res


def _keys(tx):
    keys = (((tx.get("transaction") or {}).get("message") or {}).get("accountKeys")) or []
    return [k.get("pubkey") if isinstance(k, dict) else k for k in keys]


def _token_change(meta, wallet, mint):
    """Change of `wallet`'s balance of `mint` (whole tokens) from pre/postTokenBalances; a closed account counts 0."""
    d = 0.0
    for sign, side in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(side) or []:
            if b.get("owner") != wallet or b.get("mint") != mint:
                continue
            ui = b.get("uiTokenAmount") or {}
            try:
                d += sign * int(ui.get("amount") or 0) / 10 ** int(ui.get("decimals") or 0)
            except (TypeError, ValueError):
                continue
    return d


def sol_change(tx, wallet):
    """Net SOL change of `wallet` in a jsonParsed transaction: lamports after minus before at its index in
    accountKeys, plus its wSOL token balance change (a swap that settled in wSOL). None when the transaction failed
    or the wallet is not in it."""
    if not isinstance(tx, dict):
        return None
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return None
    keys = _keys(tx)
    if wallet not in keys:
        return None
    i = keys.index(wallet)
    try:
        lamports = meta["postBalances"][i] - meta["preBalances"][i]
    except (KeyError, IndexError, TypeError):
        return None
    return lamports / 1e9 + _token_change(meta, wallet, WSOL)


def connect(hype_db=None):
    con = sqlite3.connect(hype_db or HYPE_DB, timeout=30)
    con.executescript(SCHEMA)
    return con


def _night_key(now=None):
    """The Zagreb date of `now`: the night's budget is counted under it (01-06 Zagreb falls on one date)."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    from ops import heavy
    return dt.datetime.fromtimestamp(now or time.time(), dt.timezone.utc).astimezone(ZoneInfo(heavy.NIGHT_TZ)).date().isoformat()


def used_tonight(con, night):
    row = con.execute("SELECT calls FROM chain_solfill_runs WHERE night=?", (night,)).fetchone()
    return int(row[0] or 0) if row else 0


def pending(con, limit=None):
    """[(sig, wallet, ts)] of transactions with a sale (or buy) whose sol is NULL and that were never looked at,
    newest first."""
    q = ("SELECT c.sig, c.wallet, MAX(c.ts) FROM chain_trades c WHERE c.sol IS NULL AND c.sig IS NOT NULL AND c.sig != '' "
         "AND c.wallet IS NOT NULL AND c.wallet != '' AND NOT EXISTS (SELECT 1 FROM chain_solfill f WHERE f.sig = c.sig) "
         "GROUP BY c.sig, c.wallet ORDER BY MAX(c.ts) DESC")
    return con.execute(q + (" LIMIT ?" if limit is not None else ""), (() if limit is None else (int(limit),))).fetchall()


def _leave(con, sig, ts, why, now):
    con.execute("INSERT OR REPLACE INTO chain_solfill VALUES (?,?,?,?)", (sig, ts, int(now), why))


def fill_one(con, sig, wallet, ts, fetch, now):
    """Look at one signature. Returns (calls made, rows filled, reason it stays NULL or None). Raises what `fetch`
    raises (the caller counts it as an RPC error and does not mark the signature)."""
    rows = con.execute("SELECT mint, side, sol FROM chain_trades WHERE sig=? AND wallet=?", (sig, wallet)).fetchall()
    sides = {side for _, side, _ in rows}
    if "buy" in sides and "sell" in sides:   # chainwatch: it got a token and gave one: no SOL price for the sale
        _leave(con, sig, ts, "zamjena token za token", now)
        return 0, 0, "zamjena token za token"
    side = "sell" if "sell" in sides else "buy"
    mine = [(m, sol) for m, s, sol in rows if s == side]
    tx = fetch(sig)
    if not tx:
        _leave(con, sig, ts, "transakcija nije pronađena", now)
        return 1, 0, "transakcija nije pronađena"
    meta = tx.get("meta") or {}
    if meta.get("err"):
        _leave(con, sig, ts, "neuspjela transakcija", now)
        return 1, 0, "neuspjela transakcija"
    delta = sol_change(tx, wallet)
    if delta is None:
        _leave(con, sig, ts, "novčanik nije u transakciji", now)
        return 1, 0, "novčanik nije u transakciji"
    sign = -1 if side == "sell" else 1   # a sale lowers the token balance, a buy raises it
    if not any(sign * _token_change(meta, wallet, m) > 0 for m, _ in mine):
        _leave(con, sig, ts, "token se nije pomaknuo", now)
        return 1, 0, "token se nije pomaknuo"
    amount = delta if side == "sell" else -delta   # positive: SOL in for a sale, SOL out for a buy
    if amount <= DUST_SOL:
        _leave(con, sig, ts, "bez SOL-a u transakciji", now)
        return 1, 0, "bez SOL-a u transakciji"
    per = round(amount / len(mine), 4)
    n = con.execute("UPDATE chain_trades SET sol=? WHERE sig=? AND wallet=? AND side=? AND sol IS NULL",
                    (per, sig, wallet, side)).rowcount
    return 1, n, None


def run(hype_db=None, fetch=None, max_calls=None, now=None, force=False, dry=False, log=print):
    """One pass. Returns {calls, filled, sigs, left, errors, pending} (pending: signatures still waiting after it)."""
    from ops import heavy
    path = hype_db or HYPE_DB
    out = {"calls": 0, "filled": 0, "sigs": 0, "left": 0, "errors": 0, "pending": 0}
    if not os.path.exists(path):
        return out
    if not force and not dry and not heavy.night_now():
        win = heavy.night_hours() or (1, 6)
        log(f"solfill: izvan noćnog prozora ({win[0]:02d}-{win[1]:02d} Zagreb), preskačem", flush=True)
        return out
    fetch = fetch or fetch_tx
    t = now or time.time()
    con = connect(path)
    try:
        try:
            con.execute("SELECT sig, wallet, mint, side, ts, sol FROM chain_trades LIMIT 0")
        except sqlite3.OperationalError:   # no webhook swap yet on this install
            return out
        con.execute("DELETE FROM chain_solfill WHERE ts < ?", (int(t - KEEP_DAYS * 86400),))
        con.commit()
        night = _night_key(t)
        budget = MAX_NIGHT - used_tonight(con, night)
        if max_calls is not None:
            budget = min(budget, int(max_calls))
        todo = pending(con)
        if dry:
            out["pending"] = len(todo)
            rows = con.execute("SELECT COUNT(*) FROM chain_trades WHERE sol IS NULL").fetchone()[0]
            log(f"solfill: {len(todo)} transakcija ({rows} redaka) čeka iznos SOL-a; ove noći potrošeno "
                f"{used_tonight(con, night)}/{MAX_NIGHT} poziva", flush=True)
            return out
        errors_in_row = 0
        for sig, wallet, ts in todo:
            if out["calls"] >= budget or errors_in_row >= MAX_ERRORS:
                break
            if not force and not heavy.night_now():   # the night window closed while we were working
                log("solfill: noćni prozor je završio, nastavljam sljedeće noći", flush=True)
                break
            try:
                calls, n, why = fill_one(con, sig, wallet, ts, fetch, t)
            except Exception as e:  # noqa: BLE001 - network, RPC error: not marked, tried again next night
                out["calls"] += 1
                out["errors"] += 1
                errors_in_row += 1
                log(f"solfill: {sig[:12]}…: {type(e).__name__}: {str(e)[:120]}", flush=True)
                continue
            errors_in_row = 0
            out["calls"] += calls
            if n:
                out["filled"] += n
                out["sigs"] += 1
            elif why:
                out["left"] += 1
            con.commit()
        if out["calls"]:
            con.execute("""INSERT INTO chain_solfill_runs VALUES (?,?,?,?) ON CONFLICT (night) DO UPDATE SET
                calls=calls+excluded.calls, filled=filled+excluded.filled, ts=excluded.ts""",
                        (night, out["calls"], out["filled"], int(t)))
            con.commit()
        out["pending"] = len(pending(con))
    finally:
        con.close()
    if out["calls"] or out["pending"]:
        log(f"solfill: popunjeno {out['filled']} redaka iz {out['sigs']} transakcija, {out['left']} ostaje bez iznosa, "
            f"{out['errors']} grešaka, {out['calls']} RPC poziva (ove noći najviše {MAX_NIGHT}); još čeka "
            f"{out['pending']}", flush=True)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Popuni iznos SOL-a prodaja u hype.db chain_trades iz transakcije.")
    p.add_argument("--max", type=int, default=None, help="najviše toliko RPC poziva u ovom prolazu")
    p.add_argument("--dry", action="store_true", help="samo prebroji što čeka, bez RPC poziva")
    p.add_argument("--force", action="store_true", help="i izvan noćnog prozora (ručno)")
    a = p.parse_args(argv)
    if not a.dry and not os.environ.get("HELIUS_API_KEY"):
        print("solfill: HELIUS_API_KEY nije postavljen, preskačem", flush=True)
        return 0
    try:
        run(max_calls=a.max, force=a.force, dry=a.dry)
    except Exception as e:  # noqa: BLE001
        print(f"solfill: nije uspjelo: {type(e).__name__}: {e}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
