"""Into the fast path's queue: one fast_check per signal of a followed source (fast/sources.py).

Where signals come in (each a guarded call that never raises and never waits more than a second; flag off: one
cached flag read and nothing else; fast.db not there yet: nothing, the worker creates it):
  kol/chainwatch.ingest      Helius webhook swaps of the webhook's wallets (hype.db chain_trades), with the wallet's
                             entry price in SOL from the swap itself (SOL spent / tokens received)
  live/store.mirror_chain    PumpPortal trades of followed wallets (price_sol of the trade)
  kol/xhook.ingest           X webhook calls (kol.db calls, source x_hook), kind 'call' only
  league/copy.run_once       the copy loop's fresh buys of followed wallets and calls of followed KOLs (kol.db calls,
                             hype.db kol_mentions, tg.db posts): the catch-all for every source the copy loop reads
  fast/worker.scan           the worker's own read of hype.db chain_trades and kol.db calls since its cursor (insider,
                             pre_shill and group wallets, and anything a hook missed)
Dedupe: one check per (token, source) per DEDUPE_S (10 min) of the signal's time; a signal older than MAX_AGE_S
(15 min) when it reaches us is not checked (the copy loop calls that "prekasno" too). Every new job touches WAKE, so
the worker starts it within its 0.5 s poll.
"""
import os
import sqlite3
import threading
import time

from . import sources, store

FLAG = "fast_path"
MAX_AGE_S = 900
DEDUPE_S = 600
SOL = "So11111111111111111111111111111111111111112"
STABLE = {SOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
WAKE = os.path.join(os.environ.get("DATA_DIR") or store.ROOT, ".fast_wake")
_RECENT = {}          # (token, source id) -> newest signal ts enqueued by this process
_LOCK = threading.Lock()


def mode():
    """The flag's mode; "off" when trade settings cannot be read (cached 2 s by trade/settings)."""
    try:
        from trade import settings
        return settings.flag(FLAG)
    except Exception:  # noqa: BLE001
        return "off"


def wake():
    try:
        with open(WAKE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def woke_since(ts):
    try:
        return os.path.getmtime(WAKE) > ts
    except OSError:
        return False


def _seen(token, sid, sig_ts):
    with _LOCK:
        prev = _RECENT.get((token, sid))
        return prev is not None and abs(sig_ts - prev) < DEDUPE_S


def _remember(token, sid, sig_ts):
    with _LOCK:
        _RECENT[(token, sid)] = max(sig_ts, _RECENT.get((token, sid)) or 0)
        if len(_RECENT) > 5000:
            cut = time.time() - 2 * DEDUPE_S
            for k in [k for k, v in _RECENT.items() if v < cut]:
                _RECENT.pop(k, None)


def enqueue(con, sig, src, now=None):
    """One job (dict with token, source_id, sig_ts, via and optional entry_px / entry_sol_px / entry_mcap / symbol)
    for a followed source src {"kind", "label", "follow_id"}. Its id, or None when deduped, stale or not a token."""
    tok, sid = sig.get("token"), sig.get("source_id")
    now = float(now or time.time())
    try:
        sig_ts = int(sig.get("sig_ts") or 0)
    except (TypeError, ValueError):
        return None
    if not tok or len(tok) < 32 or tok in STABLE or not sid or not sig_ts:
        return None
    sig_ts = min(sig_ts, int(now))
    if now - sig_ts > MAX_AGE_S or _seen(tok, sid, sig_ts):
        return None
    dup = con.execute("SELECT MAX(sig_ts) FROM signals WHERE token=? AND source_id=? AND sig_ts > ? AND sig_ts < ?",
                      (tok, sid, sig_ts - DEDUPE_S, sig_ts + DEDUPE_S)).fetchone()
    if dup and dup[0]:
        _remember(tok, sid, dup[0])   # the window stays anchored at the signal that was checked
        return None
    kind = src.get("kind")
    cur = con.execute("INSERT OR IGNORE INTO signals (token, symbol, kind, source_id, source_label, follow_id, via, "
                      "sig_ts, enq_ts, entry_px, entry_sol_px, entry_mcap, priority, status, next_ts) VALUES "
                      "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (tok, sig.get("symbol"), kind, sid, src.get("label"), src.get("follow_id"), sig.get("via"),
                       sig_ts, now, sig.get("entry_px"), sig.get("entry_sol_px"), sig.get("entry_mcap"),
                       sources.PRIORITY.get(kind, 5), "queued", now))
    _remember(tok, sid, sig_ts)
    return cur.lastrowid if cur.rowcount else None


def submit(sigs, now=None, path=None, con=None, timeout=1.0):
    """Candidate signals of any source -> jobs for the followed ones (buys only). Returns how many were enqueued.
    Never raises: the worker's own scan is the backup of every hook."""
    if not sigs:
        return 0
    try:
        if con is None and mode() == "off":
            return 0
        p = path or store.db_path()
        own = con is None
        if own:
            if not os.path.exists(p) or not os.path.getsize(p):
                return 0
            con = sqlite3.connect(p, timeout=timeout)
        try:
            ids = [s.get("source_id") for s in sigs if s.get("side", "buy") == "buy" and s.get("source_id")]
            got = sources.lookup(con, ids + [i.lower() for i in ids])
            n = 0
            for s in sigs:
                if s.get("side", "buy") != "buy" or not s.get("source_id"):
                    continue
                src = got.get(s["source_id"]) or got.get(s["source_id"].lower())
                if src and enqueue(con, s, src, now):
                    n += 1
            if n:
                con.commit()
                wake()
            return n
        finally:
            if own:
                con.close()
    except Exception as e:  # noqa: BLE001 - a hook never fails the webhook or the copy loop
        print(f"fast: upis u red nije uspio ({type(e).__name__}: {e})", flush=True)
        return 0


# ---------- the hooks ------------------------------------------------------------------------------------------------

def _bought(payload):
    """{(signature, wallet, mint): tokens received} of the swaps in a Helius enhanced payload."""
    out = {}
    for tx in payload if isinstance(payload, list) else [payload]:
        if not isinstance(tx, dict):
            continue
        w, sig = tx.get("feePayer"), tx.get("signature")
        for t in tx.get("tokenTransfers") or []:
            m = t.get("mint")
            if w and t.get("toUserAccount") == w and m and m not in STABLE:
                try:
                    out[(sig, w, m)] = out.get((sig, w, m), 0.0) + float(t.get("tokenAmount") or 0)
                except (TypeError, ValueError):
                    continue
    return out


def from_chain(payload, rows):
    """kol/chainwatch.ingest: rows [(sig, wallet, mint, side, ts, sol)]; the entry price in SOL per token from the
    swap (sol / tokens)."""
    if not rows or mode() == "off":
        return 0
    got = _bought(payload)
    sigs = []
    for sig, w, mint, side, ts, sol in rows:
        if side != "buy":
            continue
        q = got.get((sig, w, mint)) or 0
        sigs.append({"token": mint, "source_id": w, "sig_ts": ts, "via": "helius",
                     "entry_sol_px": (sol / q) if sol and q else None})
    return submit(sigs)


def from_live(rows, followed=None):
    """live/store.mirror_chain: PumpPortal rows (sig, mint, wallet, side, sol, tokens, price_sol, mcap_sol, pool, ts,
    balance_after) of followed wallets."""
    if not rows or mode() == "off":
        return 0
    sigs = [{"token": r[1], "source_id": r[2], "sig_ts": r[9], "via": "pumpportal", "entry_sol_px": r[6] or None}
            for r in rows if r[3] == "buy" and (followed is None or r[2] in followed)]
    return submit(sigs, timeout=0.2)   # inside the feed's hype.db transaction: never more than a moment


def from_calls(calls):
    """kol/xhook.ingest: kol/collect call dicts; only kind 'call' (a 'flash' or a brag is no entry signal)."""
    if not calls or mode() == "off":
        return 0
    return submit([{"token": c.get("token"), "source_id": (c.get("handle") or "").lstrip("@"), "sig_ts": c.get("ts"),
                    "via": c.get("source") or "x", "symbol": c.get("symbol")}
                   for c in calls if c.get("kind") == "call"])


def from_copy(evs, now=None):
    """league/copy.run_once: its events [(target, token, side, ts)] (followed wallets' buys and sells, followed KOLs'
    calls from kol.db, kol_mentions and Telegram). Only fresh buys go further; repeated passes are deduped in memory
    before any database read."""
    if not evs:
        return 0
    now = now or time.time()
    fresh = [(t, tok, ts) for t, tok, side, ts in evs if side == "buy" and now - ts <= MAX_AGE_S
             and not _seen(tok, t, int(ts))]
    if not fresh or mode() == "off":
        return 0
    return submit([{"token": tok, "source_id": t, "sig_ts": ts, "via": "copy"} for t, tok, ts in fresh], now=now)
