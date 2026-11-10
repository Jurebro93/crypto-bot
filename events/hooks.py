"""The collectors' one-line dual write into events.db. Each function takes what the collector already has in hand,
maps it with the same mapper the 5-min sync uses (events/sources.py, so both produce the same uid and never double),
and queues it with store.emit_rows(): no database wait, no exception ever reaches the collector (each caller also
wraps the call in its own try). Called from:

    kol/collect.save        calls (X and Telegram posts into kol.db)            calls_saved(con, calls)
    kol/chainwatch.ingest   Helius webhook swaps and transfers                 chain_ingested(payload, rows, transfers)
    live/store.mirror_chain PumpPortal trades of followed wallets               wallet_rows(rows, "pumpportal")
    ui/xfeat.submit         Grok's X features (MCP)                             xfeat_saved(...)
    kol/snap.take           DexScreener prices of called tokens                 prices(rows)
"""
import sys
import time

from events import sources, store

_ERR = {"at": 0.0}


def _quiet(e):
    now = time.time()
    if now - _ERR["at"] > 300:
        _ERR["at"] = now
        print(f"događaji: kuka nije uspjela ({type(e).__name__}: {e})", file=sys.stderr, flush=True)


def calls_saved(con, calls):
    """After kol/collect.save (same connection, before its commit): the saved posts of kind 'call' as they stand now
    (a bot's post or an ambiguous ticker match is no longer 'call' by then)."""
    try:
        if not calls or not store._on():
            return 0
        tids = sorted({c["tweet_id"] for c in calls if c.get("tweet_id")})
        want = {(c["tweet_id"], c["token"]) for c in calls if c.get("tweet_id") and c.get("token")}
        rows = []
        for i in range(0, len(tids), 400):
            part = tids[i:i + 400]
            rows += con.execute(
                "SELECT rowid, tweet_id, token, handle, ts, kind, source, followers, mcap0 FROM calls WHERE tweet_id IN "
                f"({','.join('?' * len(part))}) AND kind = 'call' AND COALESCE(source, '') != 'chain' "
                "AND handle NOT LIKE 'w:%'", part).fetchall()
        out = []
        for r in rows:
            if (r[1], r[2]) in want:
                out += sources.map_call(r)
        return store.emit_rows(out)
    except Exception as e:  # noqa: BLE001
        _quiet(e)
        return 0


def wallet_rows(rows, source="helius", slots=None):
    """rows: [(sig, wallet, mint, side, ts, sol)] as chain_trades stores them."""
    try:
        if not rows or not store._on():
            return 0
        out = []
        for sig, w, mint, side, ts, sol in rows:
            for ev in sources.map_wallet((None, sig, w, mint, side, ts, sol), source):
                slot = (slots or {}).get(sig)
                out.append(ev[:1] + (slot,) + ev[2:] if slot else ev)
        return store.emit_rows(out)
    except Exception as e:  # noqa: BLE001
        _quiet(e)
        return 0


def chain_ingested(payload, rows, transfers):
    """After kol/chainwatch.ingest wrote a webhook payload: swaps (with the slot from the payload) and transfers."""
    try:
        if not store._on():
            return 0
        txs = payload if isinstance(payload, list) else [payload]
        slots = {tx.get("signature"): tx.get("slot") for tx in txs if isinstance(tx, dict) and tx.get("slot")}
        n = wallet_rows(rows, "helius", slots)
        if transfers and not store.tight():
            out = []
            for sig, src, dst, mint, amount, ts in transfers:
                out += sources.map_transfer((None, sig, src, dst, mint, amount, ts))
            n += store.emit_rows(out)
        return n
    except Exception as e:  # noqa: BLE001
        _quiet(e)
        return 0


def xfeat_saved(rid, kind, subject, ts_asof, features, source, backfill):
    try:
        if not store._on():
            return 0
        return store.emit_rows(sources.map_xfeat((rid, kind, subject, ts_asof, features, source, int(bool(backfill)))))
    except Exception as e:  # noqa: BLE001
        _quiet(e)
        return 0


def prices(rows):
    """rows: [(token, ts, price, vol_h1, liq, mcap)] as kol/snap stores them."""
    try:
        if not rows or not store._on() or store.tight():
            return 0
        out = []
        for tok, ts, price, _vol, _liq, mcap in rows:
            out += sources.map_price((None, tok, ts, price, mcap))
        return store.emit_rows(out)
    except Exception as e:  # noqa: BLE001
        _quiet(e)
        return 0
