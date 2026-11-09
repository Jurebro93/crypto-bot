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
KEEP_DAYS = 14          # 8.11.: chain_trades / chain_transfers retention (was 30; readers look hours to a day back)
MAX_TRADES_DAY = 60     # 8.11.: a wallet trading more than this a day is a bot, not a trader worth a webhook slot
BUSY_LABELS = {"bundler", "mev", "cex", "rugger"}


def too_busy(wallets, wallet_db=None, max_tpd=MAX_TRADES_DAY):
    """Wallets among `wallets` that our own scoring (wallets.db stats) shows as bots: more than max_tpd trades a day
    or a bundler/MEV/exchange/rugger label. 8.11.: 15 such wallets (600-6,900 trades a day, tier D or S, in the
    webhook through the insider and signal groups) produced 57% of all chain events: a Helius credit each, a
    PumpPortal trade each, a pseudo-call each in kol.db, and no signal anyone could trade on."""
    try:
        from wallets import store as wstore
    except ImportError:
        return set()
    path = wallet_db or wstore.DB
    if not wallets or not os.path.exists(path):
        return set()
    try:
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return set()
    out = set()
    try:
        ws = list(wallets)
        for i in range(0, len(ws), 500):
            chunk = ws[i:i + 500]
            q = ",".join("?" * len(chunk))
            for w, st, lab in src.execute(f"SELECT wallet, stats, labels FROM wallets WHERE wallet IN ({q})", chunk):
                s = json.loads(st or "{}")
                if (s.get("trades_per_day") or 0) > max_tpd or set(json.loads(lab or "[]")) & BUSY_LABELS:
                    out.add(w)
    except sqlite3.Error:
        pass
    finally:
        src.close()
    return out


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
    try:   # 9.11.: the proven-twice copyable wallets (wallets/dokazani.py) come before every leaderboard group
        from wallets import dokazani as _dok
        proven = sorted(_dok.current(wallet_db))
    except Exception:  # noqa: BLE001
        proven = []
    for w in proven[:max(1, cap // 2)]:
        if w not in seen:
            seen.add(w)
            out.append(w)
    busy = too_busy(set(ids) | set(copy) | set(signal) | set(ins), wallet_db) - set(followed)
    groups = [([w for w in ws if w not in busy], sh) for ws, sh in
              ((ids, share["ids"]), (copy, share["copy"]), (signal, share["signal"]), (ins, share.get("insajderi", 0)))]
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


PRUNE_EVERY_S = 3600   # 9.11. (audit P21): retention DELETEs at most hourly, not in every webhook handler
_PRUNED = {"ts": 0.0}


def spool_dir(hype_db=None):
    """9.11. (audit P21): payloads that could not be written (hype.db locked: VACUUM, slim, other writers) wait here,
    next to the real hype.db file (realpath: start.sh symlinks it into $DATA_DIR); drain() copies them in."""
    return os.path.join(os.path.dirname(os.path.realpath(hype_db or HYPE_DB)), "chain_spool")


def spool(payload, hype_db=None, now=None, log=print):
    try:
        d = spool_dir(hype_db)
        os.makedirs(d, exist_ok=True)
        # pid + random tail: two dashboard threads in the same millisecond must not overwrite each other (review izvori)
        path = os.path.join(d, f"{int((now or time.time()) * 1000)}-{os.getpid()}-{os.urandom(4).hex()}.json")
        with open(path, "w") as f:
            json.dump(payload, f)
        log(f"chain: hype.db zauzet, event čeka u spoolu ({os.path.basename(path)})", flush=True)
        return path
    except OSError as e:
        log(f"chain: spool nije uspio: {e}", flush=True)
        return None


def drain(hype_db=None, log=print, max_files=200, timeout=None):
    """Spooled webhook payloads -> hype.db (the next successful ingest and run_kol collect). Returns rows written;
    a file stays when hype.db is still locked. `timeout`: sqlite busy wait (the webhook handler passes a short one)."""
    d = spool_dir(hype_db)
    try:
        names = sorted(os.listdir(d))[:max_files]
    except OSError:
        return 0
    n = 0
    for name in names:
        path = os.path.join(d, name)
        try:
            with open(path) as f:
                payload = json.load(f)
        except (OSError, ValueError):
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        try:
            n += ingest(payload, hype_db, _spool=False, timeout=timeout)
        except sqlite3.OperationalError:
            break
        try:
            os.remove(path)
        except OSError:
            pass
    if n:
        log(f"chain: {n} redaka iz spoola", flush=True)
    return n


def ingest(payload, hype_db=None, _spool=True, timeout=None):
    """Called by the dashboard for each POST to /hook/chain. 9.11. (audit P21): on 'database is locked' the payload
    goes to the spool and the count comes back, so the dashboard answers 200 and the event is written later."""
    rows = parse(payload)
    transfers = parse_transfers(payload)
    if not rows and not transfers:
        return 0
    try:
        con = sqlite3.connect(hype_db or HYPE_DB, timeout=timeout or (60 if not _spool else 10))
        con.execute("""CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER,
                       sol REAL, PRIMARY KEY (sig, mint))""")
        con.execute("""CREATE TABLE IF NOT EXISTS chain_transfers (sig TEXT, src TEXT, dst TEXT, mint TEXT, amount REAL,
                       ts INTEGER, PRIMARY KEY (sig, src, dst, mint))""")
        con.execute("CREATE INDEX IF NOT EXISTS chain_trades_ts ON chain_trades (ts)")   # 9.11.: the live callers box reads by time
        con.executemany("INSERT OR IGNORE INTO chain_trades VALUES (?,?,?,?,?,?)", rows)
        con.executemany("INSERT OR IGNORE INTO chain_transfers VALUES (?,?,?,?,?,?)", transfers)
        now = time.time()
        if now - _PRUNED["ts"] >= PRUNE_EVERY_S:
            con.execute("DELETE FROM chain_trades WHERE ts < ?", (int(now) - KEEP_DAYS * 86400,))
            con.execute("DELETE FROM chain_transfers WHERE ts < ?", (int(now) - KEEP_DAYS * 86400,))
            _PRUNED["ts"] = now
        con.commit()
        con.close()
    except sqlite3.OperationalError:
        if _spool and spool(payload, hype_db) is not None:
            return len(rows) + len(transfers)
        raise
    if _spool:
        try:   # the file is free now: earlier spooled events go in too (short wait: this is the webhook thread)
            drain(hype_db, timeout=10)
        except Exception:  # noqa: BLE001
            pass
    if rows:
        try:
            from league import copy as _copy   # 9.11.: the copy loop runs now, not at its next tick
            _copy.wake()
        except Exception:  # noqa: BLE001
            pass
    return len(rows) + len(transfers)
