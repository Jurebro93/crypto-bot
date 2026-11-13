"""Wallet value over time: table `equity` in trade.db, the big number and the chart on /pravi-trade and /autopilot.

10.11. (Jure: "graf preko cijele širine: vrijednost walleta kroz vrijeme, uplate označene na grafu; uz iznos u SOL-u
živa pretvorba u USD i EUR; PnL kroz vrijeme u istom grafu"). One row every EVERY_S seconds:

    equity (ts, sol, usdc, tokens_sol, sol_usd, usd_eur, flow_sol, src)

    sol, usdc     what the wallet holds (RPC); USDC is asked once an hour, it only moves when the owner moves it
    tokens_sol    open REAL positions (mode 'live') at the DexScreener price, one batched request for all of them;
                  no price = the stake still in the position. Dry-run positions are never counted: in dry mode the
                  chart is simply the real wallet balance
    sol_usd       SOL price from that same DexScreener request; usd_eur: how many EUR one USD is (ECB reference
                  rate through frankfurter.app, free, no key)
    flow_sol      deposit (+) or withdrawal (-) found on this snapshot; the first snapshot books the whole value as
                  the opening deposit, so PnL starts at 0
    src           'live' = measured, 'recon' = rebuilt from the orders ledger by backfill()

    value_sol = sol + tokens_sol + usdc / sol_usd;  net_in_sol = sum of flow_sol so far;  pnl_sol = value_sol - net_in_sol

Who writes: run_trade.cmd_follow calls start(), a daemon thread with its OWN connection, so the 1-second trade loop
never waits for RPC, DexScreener or the exchange rate. Nothing here raises towards the caller: a snapshot that fails
is one log line and the next try comes TICK_S later.
What it costs (CLAUDE.md: measure before spending): 1 RPC call per snapshot (getBalance), 1 an hour (USDC) and 1 per
new mint (decimals), about 310 standard Helius credits a day; DexScreener and the rate are free and keyless.
"""
import json
import re
import sqlite3
import threading
import time

from event_calendar import http
from trade import settings, wallet

EVERY_S = 300           # one snapshot at most this often
FLOW_MIN_SOL = 0.02     # a balance change the orders do not explain counts as a deposit / withdrawal above this
TICK_S = 20             # how often the thread looks whether a snapshot is due (and retries one that failed)
USDC_EVERY_S = 3600     # the USDC balance is asked this often (and at once when the SOL balance jumps)
SETTLE_S = 45           # no snapshot this soon after a real swap: the RPC node may not show its balance change yet
SOL_TTL_S = 60          # SOL/USD cache
EUR_TTL_S = 6 * 3600    # USD->EUR cache (the ECB publishes one rate a working day)
EUR_RETRY_S = 600       # after a failed rate request
NET_TIMEOUT_S = 5       # DexScreener and the rate: short, a page may be waiting for rates()
MAX_MINTS = 29          # DexScreener takes 30 addresses per request; one is SOL itself
LAMPORTS = 1_000_000_000
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
EUR_URLS = ("https://api.frankfurter.app/latest?from=USD&to=EUR",          # {"base":"USD","rates":{"EUR":0.86}}
            "https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR")  # the same service's newer address
RECONCILED = "usklađeno s lancem"   # executor.reconcile_pending: a real buy that has a position but no orders row
INTERRUPTED = "prekinuto usred swapa"   # executor._reconcile_pending_sells: a real sale cut off, SOL back unknown

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, sol REAL, usdc REAL, tokens_sol REAL, sol_usd REAL, "
    "usd_eur REAL, flow_sol REAL DEFAULT 0, src TEXT DEFAULT 'live')",
    # deposits() and the running sum of flows read a handful of rows from here instead of the whole history
    "CREATE INDEX IF NOT EXISTS equity_flow ON equity (ts) WHERE flow_sol != 0",
    settings.SCHEMA,   # the "how far the ledger is accounted for" mark lives in the settings table
)
COLS = "ts, sol, usdc, tokens_sol, sol_usd, usd_eur, flow_sol, src"

_RATES = {"sol": None, "sol_ts": 0, "sol_next": 0, "eur": None, "eur_ts": 0, "eur_next": 0, "stored": None,
          "stored_next": 0}
_NET = threading.Lock()     # one thread at a time asks the network for a rate; the others answer from the cache
_USDC = {"addr": None, "ts": 0, "val": None}
_DEC = {}                   # mint -> decimals, for the life of the process
_CACHE = {}                 # (database file, what, args) -> (stamp, value): series() and summary() between snapshots
_LOGGED = {}
_THREAD = {"t": None, "stop": None}


def _log_once(key, text, every=600):
    """One log line per `every` seconds for the same kind of failure (the thread retries every TICK_S)."""
    now = time.time()
    if now - _LOGGED.get(key, 0) >= every:
        _LOGGED[key] = now
        print(f"equity: {text}", flush=True)


def _err(e):
    """Exception as a short log text without any URL (an RPC address carries the API key)."""
    return f"{type(e).__name__}: " + re.sub(r"https?://\S+", "<url>", str(e))[:160]


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def ensure(con):
    """The table and its small index (also called from executor.connect). Statement by statement: executescript
    would commit a transaction the caller has open."""
    for sql in SCHEMA:
        con.execute(sql)


# ---------- rates ---------------------------------------------------------------------------------------------------

def _pairs(mints):
    """DexScreener pairs of these mints, one request (free, no key; the address list is the cache key, 60 s)."""
    from dexscreener import client
    url = f"{client.BASE}/tokens/v1/solana/{','.join(mints)}"
    return http.get_json(url, ttl=SOL_TTL_S, timeout=NET_TIMEOUT_S, retries=0) or []


def _pick(pairs):
    """The pool to believe for one token (dexscreener.client.pick_pool: trusted quote, median price), after the
    client's price sanity check; the deepest pool when the client is not there."""
    if not pairs:
        return None
    try:
        from dexscreener import client
        return client.pick_pool([client.sane(p) for p in pairs])[0]
    except Exception:  # noqa: BLE001
        return max(pairs, key=lambda p: _f((p.get("liquidity") or {}).get("usd")))


def _market(mints):
    """({mint: (price in SOL per whole token, pool liquidity in SOL or None)}, SOL/USD or None) from ONE DexScreener
    request (the open positions' mints plus SOL itself). A mint without a priced pool is left out (unknown)."""
    mints = list(dict.fromkeys(m for m in mints if m and m != WSOL))[:MAX_MINTS]
    by = {}
    for p in _pairs(mints + [WSOL]):
        base = (p.get("baseToken") or {}).get("address") if isinstance(p, dict) else None
        if base and p.get("chainId") in (None, "solana"):
            by.setdefault(base, []).append(p)
    sol_usd = _f((_pick(by.get(WSOL)) or {}).get("priceUsd"))
    sol_usd = sol_usd if 1 < sol_usd < 100_000 else None
    out = {}
    for m in mints:
        best = _pick(by.get(m))
        if not best:
            continue
        px = None
        # priceNative is exact when the pool is quoted in SOL; a reading the sanity check corrected has only its
        # priceUsd corrected, so that one goes through the dollar price
        if (best.get("quoteToken") or {}).get("address") == WSOL and _f(best.get("priceNative")) > 0 and not best.get("sumnjivo"):
            px = _f(best["priceNative"])
        elif _f(best.get("priceUsd")) > 0 and sol_usd:
            px = _f(best["priceUsd"]) / sol_usd
        if px:
            liq = _f((best.get("liquidity") or {}).get("usd"))
            out[m] = (px, liq / sol_usd if liq > 0 and sol_usd else None)
    return out, sol_usd


def _usd_eur_fetch():
    """EUR for one USD from the ECB reference rate (frankfurter.app, free, no key), or None."""
    for url in EUR_URLS:
        try:
            data = http.get_json(url, ttl=EUR_TTL_S, timeout=NET_TIMEOUT_S, retries=0) or {}
            r = _f((data.get("rates") or {}).get("EUR"))
            if 0.3 < r < 3:
                return r
        except Exception:  # noqa: BLE001 - the next address, then the stored rate
            continue
    return None


def _note_sol(px, now):
    """A SOL/USD reading (or a failed try) from snapshot()'s own DexScreener request: rates() does not ask again."""
    _RATES["sol_next"] = now + SOL_TTL_S
    if px:
        _RATES.update(sol=px, sol_ts=int(now))


def _stored(now):
    """The last rates a snapshot wrote, for when the network gives nothing (also right after a restart). Looks at the
    newest 500 rows only and at most once a minute."""
    if _RATES["stored"] is not None and now < _RATES["stored_next"] and now >= _RATES["stored_next"] - SOL_TTL_S:
        return _RATES["stored"]
    out = {"sol": None, "sol_ts": 0, "eur": None}
    try:
        con = sqlite3.connect(f"file:{settings.DB}?mode=ro", uri=True, timeout=2)
        try:
            for col, key in (("sol_usd", "sol"), ("usd_eur", "eur")):
                r = con.execute(f"SELECT {col}, ts FROM (SELECT {col}, ts FROM equity ORDER BY ts DESC LIMIT 500) "
                                f"WHERE {col} IS NOT NULL ORDER BY ts DESC LIMIT 1").fetchone()
                if r:
                    out[key] = r[0]
                    if key == "sol":
                        out["sol_ts"] = r[1]
        finally:
            con.close()
    except sqlite3.Error:
        pass
    _RATES.update(stored=out, stored_next=now + SOL_TTL_S)
    return out


def sol_usd_cached(now=None):
    """13.11. (owner's order point 2, run_trade._exit_fill): the SOL price this process already knows (rates()' cache,
    else the last snapshot's), never a network call: the measurement of an exit must not delay the next one."""
    try:
        return _RATES["sol"] or _stored(time.time() if now is None else now)["sol"]
    except Exception:  # noqa: BLE001
        return None


def rates(now=None):
    """{"sol_usd", "usd_eur", "ts"}: SOL price in USD (DexScreener, cached 60 s) and EUR for one USD (ECB rate, cached
    6 h); ts = when the SOL price was read. A source that does not answer is asked again only after its cache time
    (10 min for the rate), so a page calling this every second never waits twice; until then the last value stays,
    and before any value exists the last rate a snapshot stored is returned. Values are None only when nothing was
    ever known. Never raises."""
    now = time.time() if now is None else now
    try:
        if _NET.acquire(blocking=False):
            try:
                if now >= _RATES["sol_next"] or now < _RATES["sol_next"] - SOL_TTL_S:
                    px = None
                    try:
                        px = _market([])[1]
                    except Exception as e:  # noqa: BLE001
                        _log_once("sol", f"cijena SOL-a nije dohvaćena ({_err(e)})")
                    _note_sol(px, now)
                if now >= _RATES["eur_next"] or now < _RATES["eur_next"] - EUR_TTL_S:
                    try:
                        r = _usd_eur_fetch()
                    except Exception:  # noqa: BLE001 - counted as "no answer": asked again in EUR_RETRY_S, not now
                        r = None
                    _RATES["eur_next"] = now + (EUR_TTL_S if r else EUR_RETRY_S)
                    if r:
                        _RATES.update(eur=r, eur_ts=int(now))
                    else:
                        _log_once("eur", "tečaj USD/EUR nije dohvaćen, vrijedi zadnji poznati")
            finally:
                _NET.release()
        sol, ts, eur = _RATES["sol"], _RATES["sol_ts"], _RATES["eur"]
        if sol is None or eur is None:
            st = _stored(now)
            if sol is None:
                sol, ts = st["sol"], st["sol_ts"]
            eur = st["eur"] if eur is None else eur
        return {"sol_usd": sol, "usd_eur": eur, "ts": int(ts or 0)}
    except Exception as e:  # noqa: BLE001
        _log_once("rates", f"tečajevi: {_err(e)}")
        return {"sol_usd": _RATES["sol"], "usd_eur": _RATES["eur"], "ts": int(_RATES["sol_ts"] or 0)}


# ---------- one snapshot --------------------------------------------------------------------------------------------

def _sol_balance(addr):
    """SOL in the wallet at 'confirmed' (wallet.READ_COMMITMENT): a swap Jupiter just confirmed is in it (the default
    'finalized' lags ~15 s, and the swap's order row would then look like money that never arrived)."""
    return wallet.sol_balance(addr)


def _usdc_balance(addr):
    return wallet.token_raw_balance(addr, USDC) / 1e6


def _decimals(mint):
    if mint not in _DEC:
        _DEC[mint] = wallet.token_decimals(mint)
    return _DEC[mint]


def _tokens_value(rows, prices, decimals):
    """SOL value of the open real positions [(token, sol_in, qty_raw, qty_left)]. With a price: quantity x price, cut
    by what selling it would move the pool (constant-product, the same haircut league/store.impact uses), so a thin
    pool with a fantasy price cannot paint a profit. Without a price or decimals: the stake still in the position."""
    total = 0.0
    for token, sol_in, qty, left in rows:
        left = left or 0
        share = (left / qty) if qty else 0.0
        stake = (sol_in or 0.0) * share
        p = prices.get(token)
        dec = None
        if p:
            try:
                dec = decimals(token)
            except Exception:  # noqa: BLE001 - RPC down: counted at cost this time
                dec = None
        if not p or dec is None:
            total += stake
            continue
        px, liq = p
        v = (left or 0) / 10 ** dec * px
        if liq:
            v = v * (liq / 2) / (liq / 2 + v)
        total += v
    return total


def _delta(side, status, amount_in, amount_out, fee, signature):
    """SOL one orders row moved in the wallet. A buy takes its amount_in, a sale brings its amount_out, both pay the
    network fee the row carries; the rent row of a closed token account carries a negative fee (money back); a
    failed order cost its fee only when it reached the chain (it has a signature)."""
    lam = 0
    if status == "ok":
        if side == "buy":
            lam -= amount_in or 0
        elif side == "sell":
            lam += amount_out or 0
        lam -= fee or 0
    elif status == "failed" and signature and (fee or 0) > 0:
        lam -= fee
    return lam / LAMPORTS


def _mark(con, key="equity_oid"):
    """Id of the last orders row an earlier snapshot accounted for (settings 'equity_oid'), or None. 'equity_oid0'
    is the one of the very first snapshot: backfill() rebuilds exactly the orders before it."""
    r = con.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    try:
        return int(json.loads(r[0])) if r else None
    except (TypeError, ValueError):
        return None


def _atomic(con, write):
    """write(con) and commit as one transaction, so a half-written snapshot is never committed by whoever commits on
    this connection next. On a failure only a transaction opened here is rolled back (a caller's own stays theirs)."""
    mine = not con.in_transaction
    try:
        write(con)
        con.commit()
    except Exception:
        if mine:
            try:
                con.rollback()
            except sqlite3.Error:
                pass
        raise


def _explained(con, after_id, after_ts, upto_id):
    """(SOL the bot's own real orders moved since the previous snapshot, how many real sales in that window were
    cut off mid-swap). Counted by order id, not by time: a row is written when its swap finishes but carries the time
    the swap started, so a window by time could miss it. upto_id: the newest order the measured balance contains (a
    row booked after it belongs to the next snapshot, which starts counting there). No LIMIT: the id range holds only
    the rows since the last snapshot, and a cut list would turn the missing orders into a fake deposit."""
    sql = ("SELECT side, status, amount_in, amount_out, fee_lamports, signature, error FROM orders WHERE {} "
           "AND id <= ? AND mode='live' AND status IN ('ok','failed') ORDER BY id")
    rows = (con.execute(sql.format("id > ?"), (after_id, upto_id)) if after_id is not None
            else con.execute(sql.format("ts > ?"), (after_ts, upto_id)))
    total, cut = 0.0, 0
    for side, status, a_in, a_out, fee, sig, err in rows:
        total += _delta(side, status, a_in, a_out, fee, sig)
        # 10.11. (review novac): executor._reconcile_pending_sells marks a sale the process was killed in the middle
        # of as failed, without a signature or an amount; it may have gone through, and the SOL it brought is unknown
        cut += side == "sell" and status == "failed" and (err or "").startswith(INTERRUPTED)
    # a buy the process died in the middle of: reconcile_pending opened the position from the wallet, but no orders
    # row was ever written for it; the stake it was sent with left the wallet all the same
    total -= con.execute("SELECT COALESCE(SUM(sol_in),0) FROM positions WHERE opened_ts > ? AND mode='live' "
                         "AND status IN ('open','closed') AND reason LIKE ?", (after_ts, RECONCILED + "%")).fetchone()[0]
    return total, cut


def _busy(con, now):
    """True while a real swap is in flight (buy() and sell() commit a 'pending' row before they send anything) or
    one landed in the last SETTLE_S: the balance and the ledger would not describe the same moment."""
    if con.execute("SELECT 1 FROM positions WHERE status='pending' AND mode='live' LIMIT 1").fetchone():
        return True
    if con.execute("SELECT 1 FROM orders WHERE side='sell' AND status='pending' AND mode='live' LIMIT 1").fetchone():
        return True
    return bool(con.execute("SELECT 1 FROM orders WHERE ts >= ? AND mode='live' AND (status='ok' OR (status='failed' "
                            "AND signature IS NOT NULL)) LIMIT 1", (int(now - SETTLE_S),)).fetchone())


def _max_oid(con):
    return con.execute("SELECT COALESCE(MAX(id),0) FROM orders").fetchone()[0]


def _usdc(addr, now, last, inject, fresh=False):
    """(USDC in the wallet, was it measured just now). Asked once an hour; in between the last reading stands."""
    if "usdc" in inject:
        return float(inject["usdc"](addr)), True
    if not fresh and _USDC["addr"] == addr and _USDC["val"] is not None and 0 <= now - _USDC["ts"] < USDC_EVERY_S:
        return _USDC["val"], False
    try:
        val = _usdc_balance(addr)
    except Exception as e:  # noqa: BLE001
        if last is None:
            raise           # the opening deposit must not be booked without knowing the USDC
        _log_once("usdc", f"USDC stanje nije dohvaćeno ({_err(e)}), vrijedi zadnje poznato")
        return (last[2] or 0.0), False
    _USDC.update(addr=addr, ts=now, val=val)
    return val, True


def snapshot(con, now=None, force=False, **inject):
    """Measure the wallet once and write one row; returns the row as a dict (with value_sol) or None when nothing
    was written: not due yet (one row per EVERY_S; force=True skips only that wait), no wallet address, a real swap
    in flight or just landed, or the RPC did not answer. Never raises.

    Deposit / withdrawal: the SOL balance moved by more than FLOW_MIN_SOL beyond what the bot's own real orders
    since the previous snapshot explain (buys, sales, network fees, rent of closed token accounts). USDC that
    arrived or left counts the same way, in SOL at the current price, so the owner swapping USDC for SOL by hand is
    no deposit. The first snapshot books the whole value as the opening deposit. What it cannot see: tokens sold or
    sent by hand outside the bot look like a deposit of the SOL they brought; SOL that arrives in a window with a
    sale cut off mid-swap (its proceeds are unknown) is taken for that sale, not for a deposit.
    No row while the clock is behind the newest row, or while USDC moved and no SOL price was ever known.

    inject (tests, callers that already hold the numbers): addr, balance(addr) -> SOL, usdc(addr) -> USDC,
    market(mints) -> ({mint: (price in SOL, liquidity in SOL)}, sol_usd), rates(now) -> {"sol_usd", "usd_eur"},
    decimals(mint) -> int."""
    try:
        return _snapshot(con, int(time.time() if now is None else now), force, inject)
    except Exception as e:  # noqa: BLE001 - the thread tries again in TICK_S
        _log_once("snap", f"snimka vrijednosti walleta nije uspjela ({_err(e)})")
        return None


def _snapshot(con, now, force, inject):
    ensure(con)
    last = con.execute("SELECT ts, sol, usdc, tokens_sol, sol_usd, usd_eur FROM equity WHERE src='live' "
                       "ORDER BY ts DESC LIMIT 1").fetchone()
    if last and now < last[0]:
        # 10.11. (review novac): the clock went back. No row until it has passed the newest one again, so the time
        # axis never folds back on itself; said in the log because the chart stands still meanwhile
        _log_once("clock", f"sat je {last[0] - now} s iza zadnje snimke, nova snimka kad ga stigne")
        return None
    if last and (now == last[0] or (not force and now - last[0] < EVERY_S)):
        return None
    addr = inject.get("addr") or wallet.addresses(con)[0]
    if not addr:
        return None
    oid = _max_oid(con)
    if _busy(con, now):
        return None
    # everything slow first (prices, rates, USDC); the SOL balance last, between two looks at the ledger
    pos = con.execute("SELECT token, sol_in, qty_raw, qty_left FROM positions WHERE status='open' AND mode='live' "
                      "LIMIT 200").fetchall()
    try:
        prices, sol_usd = (inject.get("market") or _market)([p[0] for p in pos])
    except Exception as e:  # noqa: BLE001 - no prices this time: positions at their stake, the stored SOL price
        _log_once("market", f"cijene nisu dohvaćene ({_err(e)}), pozicije se broje po ulogu")
        prices, sol_usd = {}, None
    if "market" not in inject:
        _note_sol(sol_usd, now)
    r = (inject.get("rates") or rates)(now) or {}
    sol_usd = sol_usd or r.get("sol_usd") or (last[4] if last else None)
    usd_eur = r.get("usd_eur") or (last[5] if last else None)
    tokens = _tokens_value(pos, prices, inject.get("decimals") or _decimals)
    usdc, fresh = _usdc(addr, now, last, inject)
    sol = float((inject.get("balance") or _sol_balance)(addr))
    if _busy(con, now) or _max_oid(con) != oid:
        return None   # a swap started or was booked while we were measuring: next tick
    if last is None:
        if usdc and not sol_usd:
            return None   # USDC cannot be valued in SOL yet; the opening deposit would be wrong for good
        flow = sol + tokens + (usdc / sol_usd if usdc and sol_usd else 0.0)
    else:
        explained, cut = _explained(con, _mark(con), last[0], oid)
        d_sol = sol - last[1] - explained
        if abs(d_sol) > FLOW_MIN_SOL and not fresh:
            usdc, fresh = _usdc(addr, now, last, inject, fresh=True)   # a hand swap USDC <-> SOL moves both
        if abs(usdc - (last[2] or 0.0)) > 1e-6 and not sol_usd:
            return None   # 10.11. (review novac): USDC moved and cannot be valued in SOL; booked once a price is back
        if cut and d_sol > 0:
            # a sale the process was killed in the middle of went through after all: what it brought is trading,
            # not a deposit (a real deposit in the same 5 minutes is the price of not knowing)
            _log_once("cut", f"prekinuta prodaja: {d_sol:+.4f} SOL knjiženo kao njezin utržak, ne kao uplata", 0)
            d_sol = 0.0
        d_usdc = (usdc - (last[2] or 0.0)) / sol_usd if sol_usd else 0.0
        flow = d_sol + d_usdc
        flow = flow if abs(flow) > FLOW_MIN_SOL else 0.0
    row = (now, round(sol, 9), round(usdc, 6), round(tokens, 9), sol_usd, usd_eur, round(flow, 9), "live")

    def write(c):
        c.execute(f"INSERT INTO equity ({COLS}) VALUES (?,?,?,?,?,?,?,?)", row)
        c.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)", ("equity_oid", json.dumps(oid), now, "bot"))
        if last is None:   # the first snapshot's mark stays for good: backfill() rebuilds the orders up to it
            c.execute("INSERT OR IGNORE INTO settings VALUES (?,?,?,?)", ("equity_oid0", json.dumps(oid), now, "bot"))
    _atomic(con, write)
    out = dict(zip(COLS.split(", "), row))
    out["value_sol"] = round(sol + tokens + (usdc / sol_usd if usdc and sol_usd else 0.0), 9)
    return out


# ---------- reading -------------------------------------------------------------------------------------------------

def _db_key(con):
    try:
        return con.execute("PRAGMA database_list").fetchone()[2] or id(con)
    except sqlite3.Error:
        return id(con)


def _stamp(con):
    """(oldest ts, newest ts): changes with every snapshot and with backfill. Two queries on purpose: SQLite reads
    one end of the key for a lone MIN or MAX, but walks the whole table when both are asked for at once."""
    return (con.execute("SELECT MIN(ts) FROM equity").fetchone()[0], con.execute("SELECT MAX(ts) FROM equity").fetchone()[0])


def _cached(con, what, args, build):
    """series() and summary() are asked far more often than a snapshot is written (the page refreshes every second,
    a row arrives every 5 min): the answer is kept until the table's first or last row changes."""
    stamp = _stamp(con)
    key = (_db_key(con), what, args)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    val = build(stamp)
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = (stamp, val)
    return val


def _point(ts, sol, usdc, tokens, sol_usd, usd_eur, flow, src, net):
    value = (sol or 0.0) + (tokens or 0.0) + ((usdc / sol_usd) if usdc and sol_usd else 0.0)
    usd = value * sol_usd if sol_usd else None
    return {"ts": ts, "sol": sol or 0.0, "usdc": usdc or 0.0, "tokens_sol": tokens or 0.0, "value_sol": round(value, 9),
            "value_usd": round(usd, 4) if usd is not None else None,
            "value_eur": round(usd * usd_eur, 4) if usd is not None and usd_eur else None,
            "sol_usd": sol_usd, "usd_eur": usd_eur, "flow_sol": round(flow or 0.0, 9), "net_in_sol": round(net, 9),
            "pnl_sol": round(value - net, 9), "src": src}


def _net_before(con, ts, inclusive=False):
    """Sum of the deposits and withdrawals before `ts` (through the small flow index, not the whole history)."""
    op = "<=" if inclusive else "<"
    return con.execute(f"SELECT COALESCE(SUM(flow_sol),0) FROM equity WHERE ts {op} ? AND flow_sol != 0", (ts,)).fetchone()[0]


def _series(con, since, max_points, stamp):
    lo, hi = stamp
    if hi is None:
        return []
    first = max(int(since), lo) if since else lo
    net = _net_before(con, first)
    max_points = max(2, int(max_points))
    if con.execute("SELECT COUNT(*) FROM equity WHERE ts >= ?", (first,)).fetchone()[0] <= max_points:
        rows = con.execute(f"SELECT {COLS} FROM equity WHERE ts >= ? ORDER BY ts", (first,))
    else:
        bucket = -(-(hi - first + 1) // max_points)
        # one point per `bucket` seconds: the LAST row of the bucket (SQLite gives the bare columns of the row that
        # holds MAX(ts)), with the deposits of the whole bucket summed so that no marker is lost
        rows = con.execute("SELECT MAX(ts), sol, usdc, tokens_sol, sol_usd, usd_eur, SUM(flow_sol), src FROM equity "
                           "WHERE ts >= ? GROUP BY (ts - ?) / ? ORDER BY 1", (first, first, bucket))
    out = []
    for ts, sol, usdc, tokens, sol_usd, usd_eur, flow, src in rows:
        net += flow or 0.0
        out.append(_point(ts, sol, usdc, tokens, sol_usd, usd_eur, flow, src, net))
    return out


def series(con, since=None, max_points=600):
    """The chart's points, oldest first: [{ts, sol, usdc, tokens_sol, value_sol, value_usd, value_eur, sol_usd,
    usd_eur, flow_sol, net_in_sol, pnl_sol, src}]. since: unix time of the first point wanted (None = everything);
    net_in_sol still counts every deposit before it. More rows than max_points are thinned to one per equal slice of
    time (its last row; flow_sol = the deposits of the whole slice). [] without data or on any error."""
    try:
        # whole minutes: a caller asking for "the last 24 h" every second then hits the same cached answer for a
        # minute (rows are EVERY_S apart, so a minute decides nothing)
        since = int(since) // 60 * 60 if since else None
        return [dict(p) for p in _cached(con, "series", (since, int(max_points)),
                                         lambda stamp: _series(con, since, max_points, stamp))]
    except Exception as e:  # noqa: BLE001 - the page shows its empty state
        _log_once("series", f"niz za graf: {_err(e)}")
        return []


def _summary(con, now, stamp):
    lo, hi = stamp
    if hi is None:
        return {}
    last = con.execute(f"SELECT {COLS} FROM equity WHERE ts=?", (hi,)).fetchone()
    p = _point(*last, _net_before(con, hi, inclusive=True))
    # 24 h ago: the newest row at least a day old, else the very first row (a history shorter than a day)
    ref = (con.execute(f"SELECT {COLS} FROM equity WHERE ts <= ? ORDER BY ts DESC LIMIT 1", (int(now) - 86400,)).fetchone()
           or con.execute(f"SELECT {COLS} FROM equity WHERE ts=?", (lo,)).fetchone())
    p0 = _point(*ref, _net_before(con, ref[0], inclusive=True))
    net = p["net_in_sol"]
    return {"value_sol": p["value_sol"], "value_usd": p["value_usd"], "value_eur": p["value_eur"], "sol": p["sol"],
            "usdc": p["usdc"], "tokens_sol": p["tokens_sol"], "net_in_sol": net, "pnl_sol": p["pnl_sol"],
            "pnl_pct": round(100 * p["pnl_sol"] / net, 2) if net > 1e-9 else None,
            "pnl_24h_sol": round(p["pnl_sol"] - p0["pnl_sol"], 9), "first_ts": lo, "last_ts": hi,
            "sol_usd": p["sol_usd"], "usd_eur": p["usd_eur"],
            "n": con.execute("SELECT COUNT(*) FROM equity").fetchone()[0]}


def summary(con, now=None):
    """The header's numbers from the newest snapshot: {value_sol, value_usd, value_eur, sol, usdc, tokens_sol,
    net_in_sol, pnl_sol, pnl_pct, pnl_24h_sol, first_ts, last_ts, sol_usd, usd_eur, n}; {} without data or on any
    error. pnl_pct is against the money put in (None when nothing is in, e.g. everything was withdrawn); pnl_24h_sol
    is the change of PnL against the newest snapshot at least 24 h old (the first one when history is shorter).
    The $ and EUR values use the rates stored with that snapshot (at most EVERY_S old while the trade process runs);
    rates() gives the live ones."""
    try:
        now = int(time.time() if now is None else now)
        return dict(_cached(con, "summary", now // 60, lambda stamp: _summary(con, now, stamp)))
    except Exception as e:  # noqa: BLE001
        _log_once("summary", f"sažetak vrijednosti: {_err(e)}")
        return {}


def deposits(con):
    """[{ts, sol, kind}] of every snapshot with a flow, oldest first: sol > 0 a deposit, < 0 a withdrawal; kind is
    'pocetni' for the opening deposit (the first row of the history), else 'uplata' / 'isplata'. [] on any error."""
    try:
        lo = _stamp(con)[0]
        return [{"ts": ts, "sol": round(flow, 9), "kind": "pocetni" if ts == lo else "uplata" if flow > 0 else "isplata"}
                for ts, flow in con.execute("SELECT ts, flow_sol FROM equity WHERE flow_sol != 0 ORDER BY ts LIMIT 2000")]
    except Exception as e:  # noqa: BLE001
        _log_once("deposits", f"uplate: {_err(e)}")
        return []


# ---------- the past, rebuilt once ----------------------------------------------------------------------------------

def _backfilled(con):
    return bool(con.execute("SELECT 1 FROM settings WHERE k='equity_backfill'").fetchone()
                or con.execute("SELECT 1 FROM equity WHERE src='recon' LIMIT 1").fetchone())


def backfill(con, now=None):
    """One-off: rebuild the wallet's past from the orders ledger, as rows with src='recon' in front of the first
    measured snapshot. Returns the number of rows written; 0 when it already ran, when there is no measured snapshot
    to anchor on yet (it then runs on a later call), or when there were no real orders before it. Never raises.

    What a reconstruction knows: every real order the bot booked before the first snapshot, with the SOL it took or
    brought, its network fee and the rent that came back. Walking those backwards from the first measured balance
    gives the SOL balance after each of them, and the realised result of the bot's own trading over time.
    What it cannot know, and how the row says so:
    - deposits and withdrawals before the first snapshot: none are assumed. Everything the wallet held before the
      first order is one opening deposit. Only when the orders alone would make the balance negative is the missing
      amount booked, as a withdrawal on the first measured snapshot (it happened somewhere before it);
    - what the open positions were worth between a buy and its sale: they stand at cost (the stake still in), so
      the dashed part of the chart shows realised profit only and moves at sales, not with the market;
    - the SOL and EUR rates of those days and the USDC balance: the first measured snapshot's values are used, so
      the $ and EUR lines of the dashed part are that day's money, only the SOL line is the record;
    - fees are the quotes' estimates, and a buy that only the wallet check found after a crash has no order at all.
    Idempotent: a second call finds the recon rows (or the mark in settings) and writes nothing."""
    try:
        return _backfill(con, int(time.time() if now is None else now))
    except Exception as e:  # noqa: BLE001 - _atomic rolled back what this call had written
        _log_once("backfill", f"rekonstrukcija povijesti nije uspjela ({_err(e)})")
        return 0


def _backfill(con, now):
    ensure(con)
    if _backfilled(con):
        return 0
    first = con.execute("SELECT ts, sol, usdc, sol_usd, usd_eur FROM equity WHERE src='live' ORDER BY ts LIMIT 1").fetchone()
    if not first:
        return 0
    f_ts, f_sol, f_usdc, sol_usd, usd_eur = first
    # 10.11. (review novac): the orders the first snapshot's balance already contains are those booked before it
    # (id <= its mark). By time alone, a buy that started a few seconds before the first snapshot (its row carries
    # the start time) but was booked after it would be counted twice: here and by the next live snapshot.
    oid0 = _mark(con, "equity_oid0")
    by = ("id <= ? AND ts < ?", (oid0, f_ts)) if oid0 is not None else ("ts < ?", (f_ts,))
    cost, qty, steps = {}, {}, []   # position -> stake still in / raw quantity still held; (ts, SOL moved, cost of all)
    for ts, pid, side, status, a_in, a_out, fee, sig in con.execute(
            "SELECT ts, position_id, side, status, amount_in, amount_out, fee_lamports, signature FROM orders "
            # only rows that moved money, and no LIMIT (one-off): a cut ledger would rebuild a wrong past; failed
            # sells without a signature (one a second while the key is missing) can outnumber the real ones
            f"WHERE {by[0]} AND mode='live' AND (status='ok' OR (status='failed' AND signature IS NOT NULL "
            "AND fee_lamports > 0)) ORDER BY ts, id", by[1]):
        moved = _delta(side, status, a_in, a_out, fee, sig)
        if status == "ok" and side == "buy":
            cost[pid] = cost.get(pid, 0.0) + (a_in or 0) / LAMPORTS
            qty[pid] = qty.get(pid, 0) + (a_out or 0)
        elif status == "ok" and side == "sell":
            share = min(1.0, (a_in or 0) / qty[pid]) if qty.get(pid) else 1.0
            cost[pid] = cost.get(pid, 0.0) * (1 - share)
            qty[pid] = max(0, qty.get(pid, 0) - (a_in or 0))
        elif not moved:
            continue
        steps.append((ts, moved, sum(cost.values())))
    rows, lift = {}, 0.0
    if steps:
        usdc_sol = (f_usdc / sol_usd) if f_usdc and sol_usd else 0.0
        bal = f_sol - sum(s[1] for s in steps)      # before the first order
        low, run = bal, bal
        for _, moved, _ in steps:
            run += moved
            low = min(low, run)
        lift = -low if low < 0 else 0.0             # the orders alone cannot go below an empty wallet
        bal += lift
        rows = {steps[0][0] - 1: (bal, 0.0, bal + usdc_sol)}   # ts -> (sol, positions at cost, flow)
        for ts, moved, held in steps:
            bal += moved
            rows[ts] = (bal, held, 0.0)             # several orders in one second: the state after the last
    n = len(rows)

    def write(c):
        if rows:
            c.executemany(f"INSERT OR IGNORE INTO equity ({COLS}) VALUES (?,?,?,?,?,?,?,'recon')",
                          [(ts, round(s, 9), f_usdc, round(held, 9), sol_usd, usd_eur, round(flow, 9))
                           for ts, (s, held, flow) in sorted(rows.items())])
            # the opening deposit now sits on the first rebuilt row; the first measured one keeps only what the
            # ledger cannot explain (a withdrawal somewhere before it), else nothing
            c.execute("UPDATE equity SET flow_sol=? WHERE ts=?", (round(-lift, 9), f_ts))
        c.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)",
                  ("equity_backfill", json.dumps({"ts": now, "n": n}), now, "bot"))
    _atomic(con, write)
    if n:
        print(f"equity: povijest prije prve snimke rekonstruirana iz naloga ({n} točaka, označeno 'recon')", flush=True)
    return n


# ---------- the thread ----------------------------------------------------------------------------------------------

def _moved_since(con, after_id):
    """A real order that moved money was booked after this id (the range since the thread's previous look only)."""
    return bool(con.execute("SELECT 1 FROM orders WHERE id > ? AND mode='live' AND (status='ok' OR (status='failed' "
                            "AND signature IS NOT NULL)) LIMIT 1", (after_id,)).fetchone())


def _tick(con, st, now=None):
    """One look of the thread: a snapshot when one is due, the one-off backfill until it is done. Returns the
    snapshot (or None). st: the thread's memory between looks {"oid", "quiet", "filled"}.

    10.11. (review novac): a swap's orders row carries the time the swap STARTED; one that took a minute (quotes,
    Jupiter landing it, the rent coming back) is older than SETTLE_S the moment it is booked, so _busy() alone would
    let a snapshot read the balance in the same second, from an RPC node that may not show the swap yet (a fake
    deposit, then a fake withdrawal). The thread therefore also waits SETTLE_S from the moment IT first sees a new
    real order, whatever time the row carries."""
    now = time.time() if now is None else now
    top = _max_oid(con)
    if st.get("oid") is not None and top > st["oid"] and _moved_since(con, st["oid"]):
        st["quiet"] = now + SETTLE_S
        st["after_trade"] = True
    st["oid"] = top
    out = None
    if now >= st.get("quiet", 0):
        # 10.11. (Jure: "nakon svakog tradea bi se trebala osvježiti stranica"): the first snapshot after a real swap
        # is taken as soon as the balance has settled, not up to EVERY_S later, so the public page shows the new value
        out = snapshot(con, now=now, force=bool(st.get("after_trade")))
        if out is not None:
            st["after_trade"] = False
    if not st.get("filled"):
        backfill(con, now=now)
        st["filled"] = _backfilled(con)
    return out


def _loop(path, tick, stop):
    from trade import executor   # here, not at the top: executor.connect calls ensure() of this module
    st = {}
    while not stop.is_set():
        try:
            con = executor.connect(path)
            try:
                _tick(con, st)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001 - never the reason the trade process stops
            _log_once("loop", f"dretva snimanja: {_err(e)}")
        stop.wait(tick)


def start(path=None, tick=None):
    """Start the snapshot thread (daemon, its own connection to trade.db) and return at once; a second call while it
    runs returns the same thread. Called by run_trade.cmd_follow: the trade loop itself never touches the network
    for this."""
    t = _THREAD["t"]
    if t is not None and t.is_alive():
        return t
    stop = threading.Event()
    t = threading.Thread(target=_loop, args=(path or settings.DB, TICK_S if tick is None else tick, stop),
                         name="equity", daemon=True)
    _THREAD.update(t=t, stop=stop)
    t.start()
    return t


def stop(timeout=5):
    """Stop the thread: no new look starts, and a snapshot being written is given `timeout` seconds to commit.
    run_trade.cmd_follow calls it on its way out (SIGTERM). A thread still waiting for the RPC then simply ends with
    the process (it is a daemon, and it never holds a write transaction while it waits for the network)."""
    t, ev = _THREAD["t"], _THREAD["stop"]
    if ev is not None:
        ev.set()
    if t is not None:
        t.join(timeout)
    _THREAD.update(t=None, stop=None)
