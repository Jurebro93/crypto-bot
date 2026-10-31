"""Collect the retrospective sample into retro.db.

Two strata from one creation window, so winners and the population they came from can be compared:
  rand: random pump.fun creations (what the bot faces), sampled in many small time slices
  grad: random graduations (bonding curve -> PumpSwap), where almost all big winners are
Per token: every trade from creation until migration (or a page cap), creator history, DexScreener state,
and a GeckoTerminal 15 min price series for the outcome (peak after the decision point).
"""
import json
import os
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from event_calendar import http
from retro import chain

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (mint TEXT PRIMARY KEY, stratum TEXT, t_create INTEGER, slot_create INTEGER,
  creator TEXT, curve TEXT, name TEXT, symbol TEXT, uri TEXT, t_grad INTEGER, pool TEXT,
  pages INTEGER, complete INTEGER, n_tx INTEGER, fetched_at INTEGER, err TEXT);
CREATE TABLE IF NOT EXISTS trades (mint TEXT, n INTEGER, ts INTEGER, slot INTEGER, wallet TEXT, side TEXT,
  tokens REAL, sol REAL, price REAL, curve_sol REAL);
CREATE INDEX IF NOT EXISTS trades_mint ON trades (mint, n);
CREATE TABLE IF NOT EXISTS creators (wallet TEXT PRIMARY KEY, before_ts INTEGER, prior_creates INTEGER,
  prior_txs INTEGER, oldest_ts INTEGER, full INTEGER);
CREATE TABLE IF NOT EXISTS dex (mint TEXT PRIMARY KEY, ts INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS series (mint TEXT PRIMARY KEY, src TEXT, pool TEXT, ts INTEGER, candles TEXT, err TEXT);
CREATE TABLE IF NOT EXISTS meta (mint TEXT PRIMARY KEY, data TEXT, err TEXT);
"""


def connect(path):
    con = sqlite3.connect(path, timeout=300)
    con.executescript(SCHEMA)
    return con


def _is_create(tx):
    return chain.has_ix(tx, "CreateV2") or chain.has_ix(tx, "Create")


def sample_creations(con, start, end, slices, per_slice=20, seed=1):
    rnd = random.Random(seed)
    n = 0
    for _ in range(slices):
        ts = rnd.randint(start, end - 600)
        txs, _ = chain.page(chain.PUMP_MINT_AUTHORITY, since=ts, until=ts + 3600, limit=per_slice)
        for tx in txs:
            if not _is_create(tx):
                continue
            e = chain.create_event(tx) or chain.create_info(tx)
            if e and _add(con, "rand", e, tx):
                n += 1
        con.commit()
    return n


def sample_graduations(con, start, end, slices, per_slice=20, seed=2):
    rnd = random.Random(seed)
    n = 0
    for _ in range(slices):
        ts = rnd.randint(start, end - 600)
        txs, _ = chain.page(chain.PUMP_MIGRATION, since=ts, until=ts + 3600, limit=per_slice)
        for tx in txs:
            if not any(l.startswith("Program log: Instruction: Migrate") for l in chain.logs(tx)):
                continue
            mint, pool = _migration(tx)
            if mint and con.execute("INSERT OR IGNORE INTO tokens (mint, stratum, t_grad, pool) VALUES (?,?,?,?)",
                                    (mint, "grad", tx.get("blockTime"), pool)).rowcount:
                n += 1
        con.commit()
    return n


def _migration(tx):
    """(mint, PumpSwap pool) of a migration tx: the pool is the owner left holding the most tokens."""
    bal = [b for b in (tx.get("meta") or {}).get("postTokenBalances") or [] if b["mint"] != chain.WSOL]
    if not bal:
        return None, None
    big = max(bal, key=lambda b: float(b["uiTokenAmount"]["uiAmount"] or 0))
    return big["mint"], big.get("owner")


def _add(con, stratum, e, tx):
    return con.execute("""INSERT OR IGNORE INTO tokens (mint, stratum, t_create, slot_create, creator, curve,
        name, symbol, uri) VALUES (?,?,?,?,?,?,?,?,?)""",
                       (e["mint"], stratum, tx.get("blockTime"), tx.get("slot"), e.get("creator") or e.get("user"),
                        e["curve"], e["name"][:80], e["symbol"][:30], e["uri"][:300])).rowcount


# ---------- per-token trade history ----------

def fetch_token(mint, curve, max_pages):
    """All trades from creation to migration. Returns (info, rows)."""
    info = {"pages": 0, "complete": 0, "n_tx": 0}
    rows, token, n = [], None, 0
    for _ in range(max_pages):
        txs, token = chain.page(mint, asc=True, token=token)
        info["pages"] += 1
        for tx in txs:
            if info["n_tx"] == 0 and _is_create(tx):
                e = chain.create_event(tx) or chain.create_info(tx)
                if e and e["mint"] == mint:
                    curve = e["curve"]
                    info.update(t_create=tx.get("blockTime"), slot_create=tx.get("slot"),
                                creator=e.get("creator") or e.get("user"), curve=curve, name=e["name"][:80],
                                symbol=e["symbol"][:30], uri=e["uri"][:300])
            info["n_tx"] += 1
            if any(l.startswith("Program log: Instruction: Migrate") for l in chain.logs(tx)):
                m, pool = _migration(tx)
                info.update(t_grad=tx.get("blockTime"), pool=pool, complete=1)
                return info, rows
            if not curve:
                continue
            tr, curve_sol, curve_tok = chain.trades(tx, mint, curve)
            price = curve_sol / -curve_tok if curve_tok < 0 and curve_sol > 0 else (
                curve_sol / -curve_tok if curve_tok > 0 and curve_sol < 0 else None)
            if price is None and tr and tr[0][1] == "buy" and n == 0:  # create + dev buy: curve was just minted
                price = -tr[0][3] / tr[0][2]
            for w, side, d, sol in tr:
                rows.append((mint, n, tx.get("blockTime"), tx.get("slot"), w, side, d, sol, price, curve_sol))
            n += 1
        if not token or not txs:
            info["complete"] = 1
            return info, rows
    return info, rows


def fetch_all(con, stratum, max_pages, workers=int(os.environ.get("RETRO_WORKERS", "6")), limit=None):
    todo = con.execute("SELECT mint, curve FROM tokens WHERE stratum=? AND fetched_at IS NULL", (stratum,)).fetchall()
    todo = todo[:limit] if limit else todo
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch_token, m, c, max_pages): m for m, c in todo}
        for f in as_completed(futs):
            mint = futs[f]
            try:
                info, rows = f.result()
            except Exception as e:
                con.execute("UPDATE tokens SET err=?, fetched_at=? WHERE mint=?", (str(e)[:300], int(time.time()), mint))
                continue
            con.execute("DELETE FROM trades WHERE mint=?", (mint,))
            con.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            cols = ", ".join(f"{k}=COALESCE(?, {k})" for k in info)
            con.execute(f"UPDATE tokens SET {cols}, fetched_at=? WHERE mint=?", (*info.values(), int(time.time()), mint))
            done += 1
            if done % 50 == 0:
                con.commit()
                print(f"  {stratum}: {done}/{len(todo)}  credits so far {chain.credits_used()}", flush=True)
    con.commit()
    return done


# ---------- creator history: how many tokens did the deployer launch before this one ----------

def creator_history(wallet, before_ts, pages=3):
    creates = txs = 0
    oldest, token, full = None, None, 1
    for _ in range(pages):
        data, token = chain.page(wallet, until=before_ts, asc=False, token=token)
        for tx in data:
            txs += 1
            creates += _is_create(tx)
            oldest = tx.get("blockTime")
        if not token or not data:
            break
    else:
        full = 0
    return creates, txs, oldest, full


def creators_all(con, workers=int(os.environ.get("RETRO_WORKERS", "6"))):
    todo = con.execute("""SELECT creator, MIN(t_create) FROM tokens WHERE creator IS NOT NULL
        AND creator NOT IN (SELECT wallet FROM creators) GROUP BY creator""").fetchall()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(creator_history, w, ts): (w, ts) for w, ts in todo}
        for i, f in enumerate(as_completed(futs)):
            w, ts = futs[f]
            try:
                c, n, oldest, full = f.result()
            except Exception:
                continue
            con.execute("INSERT OR REPLACE INTO creators VALUES (?,?,?,?,?,?)", (w, ts, c, n, oldest, full))
            if i % 100 == 0:
                con.commit()
    con.commit()


# ---------- DexScreener current state (free, 30 tokens per call) ----------

def dex_all(con):
    from dexscreener import client
    todo = [m for (m,) in con.execute("SELECT mint FROM tokens WHERE mint NOT IN (SELECT mint FROM dex)")]
    for i in range(0, len(todo), 30):
        batch = todo[i:i + 30]
        try:
            pairs = client.tokens("solana", batch) or []
        except Exception as e:
            print("dex:", e)
            continue
        by = {}
        for p in pairs:
            by.setdefault(p["baseToken"]["address"], []).append(p)
        now = int(time.time())
        con.executemany("INSERT OR REPLACE INTO dex VALUES (?,?,?)",
                        [(m, now, json.dumps(by.get(m, []))) for m in batch])
        con.commit()


# ---------- GeckoTerminal price series (free, ~30 calls/min) ----------

_GT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/{}/ohlcv/minute"


def series(pool, before_ts):
    """15 min candles [ts, open, high, low, close, vol_usd] priced in SOL, the ~10 days before before_ts.
    Fetched directly (not via http.get_json) so no cache file is written per pool."""
    import urllib.parse
    import urllib.request
    url = _GT.format(pool) + "?" + urllib.parse.urlencode({"aggregate": 15, "limit": 1000, "before_timestamp": int(before_ts),
                                                          "currency": "token", "token": "base"})
    req = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]["attributes"]["ohlcv_list"]


def series_all(con, horizon_days=7, per_min=float(os.environ.get("RETRO_GT_PER_MIN", "12")), rounds=40):
    """Graduated tokens: PumpSwap pool. Not graduated but history cut off by the page cap: the curve itself.
    Skips instant graduations (bought out to the curve's end within a minute of creation: bundle launches).
    Repeats while the trade fetch is still adding tokens; on 429 waits a minute."""
    import urllib.error
    gap = 60.0 / per_min
    for _ in range(rounds):
        rows = con.execute("""SELECT t.mint, COALESCE(t.t_grad, t.t_create), t.pool, t.curve, t.complete, d.data
            FROM tokens t LEFT JOIN dex d ON d.mint=t.mint WHERE t.fetched_at IS NOT NULL AND t.err IS NULL
            AND NOT (t.t_grad IS NOT NULL AND t.t_grad - t.t_create < 60)
            AND t.mint NOT IN (SELECT mint FROM series) ORDER BY t.stratum, t.mint""").fetchall()
        todo = []
        for mint, t0, pool, curve, complete, dex in rows:
            if not pool:
                for p in json.loads(dex or "[]"):
                    if p.get("dexId") == "pumpswap":
                        pool = p["pairAddress"]
            if pool:
                todo.append((mint, t0, "pumpswap", pool))
            elif complete == 0 and curve:
                todo.append((mint, t0, "curve", curve))
        if not todo:
            if not con.execute("SELECT 1 FROM tokens WHERE fetched_at IS NULL LIMIT 1").fetchone():
                return
            time.sleep(120)
            continue
        for mint, t0, src, pool in todo:
            t = time.monotonic()
            for attempt in range(8):
                try:
                    c = series(pool, (t0 or 0) + horizon_days * 86400 + 3600)
                    con.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?,?,NULL)",
                                (mint, src, pool, int(time.time()), json.dumps([[x[0], x[2], x[4], round(x[5], 2)] for x in c])))
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt < 7:  # shared egress IP: others may be using the same limit
                        time.sleep(min(60, 5 * 2 ** attempt))
                        continue
                    con.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?,NULL,?)",
                                (mint, src, pool, int(time.time()), str(e)[:200]))
                    break
                except Exception as e:
                    con.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?,NULL,?)",
                                (mint, src, pool, int(time.time()), str(e)[:200]))
                    break
            con.commit()
            time.sleep(max(0, gap - (time.monotonic() - t)))


# ---------- token metadata JSON (socials) ----------

def meta_all(con, workers=8):
    import urllib.request
    todo = con.execute("SELECT mint, uri FROM tokens WHERE uri LIKE 'http%' AND mint NOT IN (SELECT mint FROM meta)").fetchall()

    def get(uri):
        if "/ipfs/" in uri:  # pump.fun's own gateway answers for every CID; ipfs.io/dweb.link refuse us
            uri = "https://pump.mypinata.cloud/ipfs/" + uri.split("/ipfs/", 1)[1]
        req = urllib.request.Request(uri, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read(200000))
        return {k: d.get(k) for k in ("twitter", "telegram", "website", "description", "showName", "createdOn")}

    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(get, u): m for m, u in todo}
        for f in as_completed(futs):
            m = futs[f]
            try:
                con.execute("INSERT OR REPLACE INTO meta VALUES (?,?,NULL)", (m, json.dumps(f.result())))
            except Exception as e:
                con.execute("INSERT OR REPLACE INTO meta VALUES (?,NULL,?)", (m, str(e)[:200]))
    con.commit()


# ---------- repair: tokens whose curve was mis-read as a protocol account ----------

def repair(con):
    """Older fetches took pump.fun's protocol ("mayhem") account for the bonding curve. Consequences in `trades`:
    the real curve appears as an in/out 'trader' (its SOL and token deltas are the exact curve legs), prices are
    missing, and the protocol account's own trades are missing (they were booked as 'the curve'). Fix offline:
    price per tx = |curve SOL| / |curve tokens|; the protocol's trade = whatever of the curve's legs the other
    wallets in that tx do not explain; then drop the curve rows. Idempotent."""
    protocol = next(iter(chain.PROTOCOL))
    bad = con.execute("""SELECT DISTINCT t.mint FROM tokens t JOIN trades tr ON tr.mint=t.mint
        WHERE tr.n=0 AND tr.side='in' AND tr.tokens > 5e8 AND tr.wallet NOT IN (%s)""" %
                      ",".join("'%s'" % p for p in chain.PROTOCOL)).fetchall()
    fixed = 0
    for (mint,) in bad:
        real = con.execute("SELECT wallet FROM trades WHERE mint=? AND n=0 AND side='in' AND tokens > 5e8 AND wallet NOT IN (%s) "
                           "ORDER BY tokens DESC LIMIT 1" % ",".join("'%s'" % p for p in chain.PROTOCOL), (mint,)).fetchone()
        if not real:
            continue
        real = real[0]
        rows = con.execute("SELECT n, ts, slot, wallet, side, tokens, sol FROM trades WHERE mint=? ORDER BY n", (mint,)).fetchall()
        by_n = {}
        for n, ts, slot, w, side, tokens, sol in rows:
            by_n.setdefault(n, {"ts": ts, "slot": slot, "curve": None, "o_tok": 0.0, "o_sol": 0.0})
            if w == real:
                by_n[n]["curve"] = (tokens, sol)
            else:
                by_n[n]["o_tok"] += tokens
                by_n[n]["o_sol"] += sol
        prices, proto_rows = [], []
        for n, d in by_n.items():
            if not d["curve"]:
                continue
            c_tok, c_sol = d["curve"]
            if n > 0 and abs(c_tok) >= 1000 and abs(c_sol) >= 0.003:
                prices.append((abs(c_sol) / abs(c_tok), mint, n))
            p_tok, p_sol = -(c_tok + d["o_tok"]), -(c_sol + d["o_sol"])
            if n > 0 and abs(p_tok) >= 1000 and abs(p_sol) >= 0.003:
                side = "buy" if p_tok > 0 and p_sol < 0 else "sell" if p_tok < 0 and p_sol > 0 else None
                if side:
                    proto_rows.append((mint, n, d["ts"], d["slot"], protocol, side, p_tok, p_sol,
                                       abs(c_sol) / abs(c_tok), -c_sol))
        con.execute("DELETE FROM trades WHERE mint=? AND wallet=?", (mint, real))
        con.execute("UPDATE trades SET price=NULL WHERE mint=?", (mint,))
        con.executemany("UPDATE trades SET price=? WHERE mint=? AND n=?", prices)
        con.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)", proto_rows)
        con.execute("UPDATE tokens SET curve=? WHERE mint=?", (real, mint))
        fixed += 1
    con.commit()
    return fixed


# ---------- price path from Helius when GeckoTerminal is throttled ----------

# slices after graduation: dense in the first hours (dump or pump decides there), coarser to day 7
SLICES_H = [0, 1, 2, 3, 4, 5, 6, 12, 18, 24, 36, 48, 72, 96, 120, 144, 168]


def pool_prices(pool, mint, t0, per_slice=100):
    """[ts, price, price, 0] points from the PumpSwap pool's own txs: in every tx touching the pool its post
    balances hold both reserves, so price = WSOL reserve / token reserve. Each slice costs 10 credits."""
    pts = []
    for a, b in zip(SLICES_H[:-1], SLICES_H[1:]):
        txs, _ = chain.page(pool, since=t0 + a * 3600, until=t0 + b * 3600, asc=False, limit=per_slice)
        for tx in txs:
            sol = tok = None
            for bal in (tx.get("meta") or {}).get("postTokenBalances") or []:
                if bal.get("owner") != pool:
                    continue
                amt = int(bal["uiTokenAmount"]["amount"]) / 10 ** int(bal["uiTokenAmount"]["decimals"])
                if bal["mint"] == chain.WSOL:
                    sol = amt
                elif bal["mint"] == mint:
                    tok = amt
            if sol and tok:
                pts.append([tx.get("blockTime") or 0, sol / tok, sol / tok, 0])
    pts.sort()
    return pts


def curve_more(mint, curve, n0, last_ts, extra_pages):
    """Not graduated and cut by the page cap: keep reading the curve (outcome = its own later trades).
    Pure fetch (no DB work) so it can run in a worker thread; returns trade rows."""
    rows, token, n = [], None, n0
    for _ in range(extra_pages):
        txs, token = chain.page(mint, since=last_ts + 1, asc=True, token=token)
        for tx in txs:
            tr, curve_sol, curve_tok = chain.trades(tx, mint, curve)
            price = curve_sol / -curve_tok if curve_tok and curve_sol and (curve_tok < 0) == (curve_sol > 0) else None
            for w, side, d, sol in tr:
                rows.append((mint, n, tx.get("blockTime"), tx.get("slot"), w, side, d, sol, price, curve_sol))
            n += 1
        if not token or not txs:
            break
    return rows


def series_helius(con, workers=8, limit=None, extra_curve_pages=20):
    """Fill `series` for graduated tokens from Helius (src='helius'), and extend cut-off curves."""
    rows = con.execute("""SELECT mint, COALESCE(t_grad, t_create), pool, curve, complete, t_grad FROM tokens
        WHERE fetched_at IS NOT NULL AND err IS NULL AND NOT (t_grad IS NOT NULL AND t_grad - t_create < 60)
        AND mint NOT IN (SELECT mint FROM series) ORDER BY stratum DESC, mint DESC""").fetchall()
    rows = rows[:limit] if limit else rows
    with ThreadPoolExecutor(workers) as ex:
        futs = {}
        for mint, t0, pool, curve, complete, grad in rows:
            if grad and pool:
                futs[ex.submit(pool_prices, pool, mint, t0)] = (mint, pool, "helius")
            elif not grad and complete == 0 and curve:
                n0 = con.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM trades WHERE mint=?", (mint,)).fetchone()[0]
                last_ts = con.execute("SELECT MAX(ts) FROM trades WHERE mint=?", (mint,)).fetchone()[0] or 0
                futs[ex.submit(curve_more, mint, curve, n0, last_ts, extra_curve_pages)] = (mint, curve, "curve_more")
        for i, f in enumerate(as_completed(futs)):
            mint, pool, src = futs[f]
            try:
                res = f.result()
            except Exception as e:
                con.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?,NULL,?)", (mint, src, pool, int(time.time()), str(e)[:200]))
                continue
            if src == "helius":
                con.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?,?,NULL)", (mint, src, pool, int(time.time()), json.dumps(res)))
            else:
                con.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)", res)
                con.execute("UPDATE tokens SET complete=1, pages=pages+? WHERE mint=?", (extra_curve_pages, mint))
                con.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?,?,NULL)", (mint, src, pool, int(time.time()), "[]"))
            if i % 25 == 0:
                con.commit()
                print(f"  series: {i}/{len(futs)} credits {chain.credits_used()}", flush=True)
    con.commit()
