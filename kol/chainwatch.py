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


AUTH_V = 3   # 4.11.: key in the Authorization header; 5.11.: TRANSFER events too (kol/traces.py), resync once


def hook_url():
    base = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KOL_HOOK_BASE")
    key = store.chain_key()
    if not base or not key:
        return None
    return f"{base.rstrip('/')}/hook/chain"


def _api(method, path="", body=None):
    key = os.environ["HELIUS_API_KEY"]
    url = f"{API}{path}?api-key={key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
    if method in ("POST", "PUT", "DELETE"):
        try:
            from usage import meter
            meter.helius_webhook(0, managed=True)
        except Exception:
            pass
    return json.loads(txt) if txt else None


SHARE = {"ids": 0.4, "copy": 0.3, "signal": 0.1, "insajderi": 0.2}   # of chain.max_wallets; a group's unused slots go to the next


def own_wallets(n_copy, n_signal, min_copy=35, wallet_db=None):
    """(copyable, signal) wallets from our own registry (wallets.db, run_wallets.py score): the best by copy_score
    (tier A/B, without bad labels) and tier S (profitable bots / snipers: a buy is a signal, not a copy). Until
    5.11. only the public leaderboards (kol_ids) were followed live; the wallets the bot scores itself were not."""
    try:
        from wallets import store as wstore
    except ImportError:
        return [], []
    path = wallet_db or wstore.DB
    if not os.path.exists(path):
        return [], []
    try:
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return [], []
    copy, signal = [], []
    try:
        for w, lab in src.execute("SELECT wallet, labels FROM wallets WHERE copy_score >= ? ORDER BY copy_score DESC, "
                                  "score DESC LIMIT ?", (min_copy, max(0, n_copy) * 3)):
            if not set(json.loads(lab or "[]")) & wstore.BAD_LABELS:
                copy.append(w)
            if len(copy) >= n_copy:
                break
        for w, in src.execute("SELECT wallet FROM wallets WHERE tier = 'S' AND score >= 40 ORDER BY score DESC LIMIT ?",
                              (max(0, n_signal),)):
            signal.append(w)
    except sqlite3.Error:   # no wallets table yet
        pass
    finally:
        src.close()
    return copy, signal


def wanted(con, cfg, wallet_db=None):
    """Wallets to follow (at most chain.max_wallets): public KOL leaderboards (kol_ids, by rank; FOMO traders last),
    then our own best copyable wallets, then our tier-S signal wallets (chain.share, chain.min_copy). Slots a group
    cannot fill go to the others, so an empty registry still means the full leaderboard list as before."""
    cap = cfg["max_wallets"]
    share = dict(SHARE, **(cfg.get("share") or {}))
    ids = [w for w, in con.execute("""SELECT wallet FROM kol_ids ORDER BY (source = 'fomo'), COALESCE(rank, 999),
                                      COALESCE(pnl, 0) DESC""")]
    copy, signal = own_wallets(cap, cap, cfg.get("min_copy", 35), wallet_db)
    from kol import insiders as _ins   # 5.11.: wallets that buy before KOL calls, minus snipers (kol/insiders.py)
    try:
        ins = [w for w, _n, _s in _ins.wallets(con, _ins.DEFAULT["min_tokens"], cap)]
    except Exception:  # noqa: BLE001
        ins = []
    # 4.11.: wallets a player follows in the competition (league.db follows) MUST be in the webhook, or the follow
    # never sees a buy ("pratim nekoliko walleta, nemam otvorenih pozicija"); they go first, outside the shares
    followed = []
    try:
        from league import copy as lcopy, store as lstore
        lcon = sqlite3.connect(f"file:{lstore.DB}?mode=ro", uri=True, timeout=5) if os.path.exists(lstore.DB) else None
        if lcon is not None:
            try:
                followed = [t for (t,) in lcon.execute("SELECT DISTINCT target FROM follows WHERE kind='wallet' AND active=1")]
            finally:
                lcon.close()
    except Exception:  # noqa: BLE001
        followed = []
    out, seen = [], set()
    for w in followed[:max(1, cap // 4)]:
        if w not in seen:
            seen.add(w)
            out.append(w)
    groups = [(ids, share["ids"]), (copy, share["copy"]), (signal, share["signal"]), (ins, share.get("insajderi", 0))]
    for second in (False, True):   # second pass: the slots a short group left over
        for ws, sh in groups:
            n = cap - len(out) if second else int(round(cap * sh))
            for w in ws:
                if n <= 0 or len(out) >= cap:
                    break
                if w not in seen:
                    seen.add(w)
                    out.append(w)
                    n -= 1
    return out


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
    if not wallets or (sorted(wallets) == sorted(state.get("wallets", [])) and now - state.get("ts", 0) < cfg["resync_h"] * 3600
                       and state.get("auth") == AUTH_V):
        return False
    body = {"webhookURL": url, "transactionTypes": ["SWAP", "TRANSFER"], "accountAddresses": wallets, "webhookType": "enhanced",
            "authHeader": store.chain_key()}
    hid = state.get("id")
    if not hid:  # reuse one we made before (same URL) instead of piling up webhooks
        for h in api("GET") or []:
            if (h.get("webhookURL") or "").split("?")[0] == url.split("?")[0]:
                hid = h.get("webhookID")
    res = api("PUT", f"/{hid}", body) if hid else api("POST", "", body)
    hid = (res or {}).get("webhookID") or hid
    con.execute("INSERT OR REPLACE INTO kv VALUES ('chain_hook', ?)",
                (json.dumps({"id": hid, "wallets": wallets, "ts": now, "auth": AUTH_V}),))
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


def parse_transfers(events, wallets=None):
    """TRANSFER transactions -> [(sig, src, dst, mint, amount, ts)]: token transfers (mint) and SOL transfers (mint
    'SOL', amount in SOL) that touch a tracked wallet; swaps are left to parse()."""
    out = []
    for tx in events if isinstance(events, list) else [events]:
        if not isinstance(tx, dict) or (tx.get("type") or "").upper() != "TRANSFER":
            continue
        sig, ts = tx.get("signature"), tx.get("timestamp")
        if not sig:
            continue
        for t in tx.get("tokenTransfers") or []:
            a, b, mint = t.get("fromUserAccount"), t.get("toUserAccount"), t.get("mint")
            if mint in STABLE or not mint or not (a or b):
                continue
            if wallets and a not in wallets and b not in wallets:
                continue
            out.append((sig, a, b, mint, float(t.get("tokenAmount") or 0), ts))
        for t in tx.get("nativeTransfers") or []:
            a, b = t.get("fromUserAccount"), t.get("toUserAccount")
            if wallets and a not in wallets and b not in wallets:
                continue
            amt = float(t.get("amount") or 0) / 1e9
            if amt >= 0.05:
                out.append((sig, a, b, "SOL", amt, ts))
    return out


def ingest(payload, hype_db=None):
    """Called by the dashboard for each POST to /hook/chain."""
    rows = parse(payload)
    transfers = parse_transfers(payload)
    con = sqlite3.connect(hype_db or HYPE_DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER,
                   sol REAL, PRIMARY KEY (sig, mint))""")
    con.execute("""CREATE TABLE IF NOT EXISTS chain_transfers (sig TEXT, src TEXT, dst TEXT, mint TEXT, amount REAL,
                   ts INTEGER, PRIMARY KEY (sig, src, dst, mint))""")
    con.executemany("INSERT OR IGNORE INTO chain_trades VALUES (?,?,?,?,?,?)", rows)
    con.executemany("INSERT OR IGNORE INTO chain_transfers VALUES (?,?,?,?,?,?)", transfers)
    con.execute("DELETE FROM chain_trades WHERE ts < ?", (int(time.time()) - 30 * 86400,))
    con.execute("DELETE FROM chain_transfers WHERE ts < ?", (int(time.time()) - 30 * 86400,))
    con.commit()
    con.close()
    return len(rows) + len(transfers)
