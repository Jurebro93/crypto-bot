"""Live buys and sells of KOL wallets through one Helius enhanced webhook (SWAP transactions of up to
`chain.max_wallets` addresses). Helius pushes each swap to the dashboard's /hook/chain within seconds; the
dashboard writes it to hype.db chain_trades and run_kol copies it into calls (kind 'buy' / 'sell').
Cost: about 1 Helius credit per delivered event (~1-2k events a day for 100 active wallets).
"""
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request

from kol import store

API = "https://api.helius.xyz/v0/webhooks"
SOL = "So11111111111111111111111111111111111111112"
STABLE = {SOL, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
HYPE_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hype.db")


def hook_url():
    base = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KOL_HOOK_BASE")
    key = store.chain_key()
    if not base or not key:
        return None
    return f"{base.rstrip('/')}/hook/chain?key={urllib.parse.quote(key)}"


def _api(method, path="", body=None):
    key = os.environ["HELIUS_API_KEY"]
    url = f"{API}{path}?api-key={key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else None


def wanted(con, cfg):
    """Wallets to follow: KOLs ranked by PnL from the identity lists, FOMO traders after them."""
    rows = con.execute("""SELECT wallet FROM kol_ids ORDER BY (source = 'fomo'), COALESCE(rank, 999),
                          COALESCE(pnl, 0) DESC""").fetchall()
    return [w for w, in rows][:cfg["max_wallets"]]


def sync(con, cfg, now=None, api=None, log=print):
    """Create or update the webhook when the wallet list changed or every resync_h. False when nothing to do,
    None when it cannot run (no HELIUS_API_KEY or no public URL)."""
    api = api or _api
    now = now or int(time.time())
    url = hook_url()
    if not url or not os.environ.get("HELIUS_API_KEY") and api is _api:
        return None
    wallets = wanted(con, cfg)
    state = json.loads((con.execute("SELECT value FROM kv WHERE key='chain_hook'").fetchone() or ("{}",))[0])
    if not wallets or (sorted(wallets) == sorted(state.get("wallets", [])) and now - state.get("ts", 0) < cfg["resync_h"] * 3600):
        return False
    body = {"webhookURL": url, "transactionTypes": ["SWAP"], "accountAddresses": wallets, "webhookType": "enhanced"}
    hid = state.get("id")
    if not hid:  # reuse one we made before (same URL) instead of piling up webhooks
        for h in api("GET") or []:
            if (h.get("webhookURL") or "").split("?")[0] == url.split("?")[0]:
                hid = h.get("webhookID")
    res = api("PUT", f"/{hid}", body) if hid else api("POST", "", body)
    hid = (res or {}).get("webhookID") or hid
    con.execute("INSERT OR REPLACE INTO kv VALUES ('chain_hook', ?)",
                (json.dumps({"id": hid, "wallets": wallets, "ts": now}),))
    con.commit()
    log(f"chain: Helius webhook prati {len(wallets)} KOL novčanika")
    return True


def parse(events, wallets=None):
    """Enhanced webhook payload -> [(sig, wallet, mint, side, ts, sol)]: what the signing wallet got (buy) or gave
    (sell) other than SOL/stables; SOL amount from its native and wSOL transfers."""
    out = []
    for tx in events if isinstance(events, list) else [events]:
        w, sig, ts = tx.get("feePayer"), tx.get("signature"), tx.get("timestamp")
        if not w or not sig or (wallets and w not in wallets):
            continue
        got, gave, sol = {}, {}, 0.0
        for t in tx.get("tokenTransfers") or []:
            amt, mint = float(t.get("tokenAmount") or 0), t.get("mint")
            if mint == SOL:
                sol += amt if t.get("fromUserAccount") == w else 0
                continue
            if mint in STABLE:
                continue
            if t.get("toUserAccount") == w:
                got[mint] = got.get(mint, 0) + amt
            elif t.get("fromUserAccount") == w:
                gave[mint] = gave.get(mint, 0) + amt
        sol += sum(float(n.get("amount") or 0) / 1e9 for n in tx.get("nativeTransfers") or []
                   if n.get("fromUserAccount") == w) if not sol else 0
        for mint in got:
            out.append((sig, w, mint, "buy", ts, round(sol, 4)))
        for mint in gave:
            if mint not in got:
                out.append((sig, w, mint, "sell", ts, None))
    return out


def ingest(payload, hype_db=None):
    """Called by the dashboard for each POST to /hook/chain."""
    rows = parse(payload)
    con = sqlite3.connect(hype_db or HYPE_DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER,
                   sol REAL, PRIMARY KEY (sig, mint))""")
    con.executemany("INSERT OR IGNORE INTO chain_trades VALUES (?,?,?,?,?,?)", rows)
    con.execute("DELETE FROM chain_trades WHERE ts < ?", (int(time.time()) - 30 * 86400,))
    con.commit()
    con.close()
    return len(rows)
