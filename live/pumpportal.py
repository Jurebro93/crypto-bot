"""PumpPortal data feed (wss://pumpportal.fun/api/data, free, no key): every trade on pump.fun and PumpSwap for the
tokens we watch and the wallets we follow, plus every new pump.fun token. One connection per process, reconnect with
backoff (PumpPortal bans clients that reconnect in a loop).

Messages (fields we use):
  create: signature, mint, traderPublicKey, txType='create', initialBuy, solAmount, marketCapSol, name, symbol, pool
  trade:  signature, mint, traderPublicKey, txType='buy'|'sell', tokenAmount, solAmount, marketCapSol, pool
No timestamp is sent: the receive time is the trade time (sub-second behind the chain).
"""
import json
import os
import sqlite3
import time

URL = os.environ.get("PUMPPORTAL_WS", "wss://pumpportal.fun/api/data")


def ws_url():
    """5.11.: PumpPortal answered "'subscribeTokenTrade' and 'subscribeAccountTrade' methods are only available when
    connecting with an API key funded with at least 0.02 SOL". New-token events are free; trades of chosen tokens
    and wallets need PUMPPORTAL_API_KEY (pumpportal.fun -> API key, its wallet topped up with >= 0.02 SOL)."""
    key = os.environ.get("PUMPPORTAL_API_KEY")
    return f"{URL}?api-key={key}" if key else URL
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_TOKENS, MAX_WALLETS = 40, 200
# 6.11.: 150 tokens pulled ~45,000 trades an hour and burned the 0.1 SOL in two hours (PumpPortal: 0.01 SOL per 10k
# trades), then the feed went silent ("funded with at least 0.02 SOL"). Token trades now stop for the day once the
# budget is spent; wallets (few trades) and migrations (free) stay on. 100k trades = 0.1 SOL = about $9 a day.
MAX_TRADES_DAY = int(os.environ.get("LIVE_MAX_TRADES_DAY", "100000"))


def parse(msg, now=None):
    """One feed message -> ("trade", row) | ("launch", row) | (None, None). Rows match live/store.py tables."""
    now = int(now or time.time())
    if isinstance(msg, (str, bytes)):
        try:
            msg = json.loads(msg)
        except ValueError:
            return None, None
    if not isinstance(msg, dict):
        return None, None
    kind, mint, sig, w = msg.get("txType"), msg.get("mint"), msg.get("signature"), msg.get("traderPublicKey")
    if not mint or not sig:
        return None, None
    try:
        sol = float(msg.get("solAmount") or 0)
    except (TypeError, ValueError):
        sol = 0.0
    pool = msg.get("pool") or "pump"
    if kind == "create":
        return "launch", (mint, now, w, (msg.get("name") or "")[:60], (msg.get("symbol") or "")[:20],
                          round(sol, 4), sig, pool)
    if kind == "migrate" or msg.get("migration") or kind == "migration":   # bonded: pool becomes pump-amm
        return "launch", (mint, now, w, (msg.get("name") or "")[:60], (msg.get("symbol") or "")[:20],
                          round(sol, 4), sig, "migration")
    if kind in ("buy", "sell"):
        try:
            toks = float(msg.get("tokenAmount") or 0)
        except (TypeError, ValueError):
            toks = 0.0
        px = sol / toks if toks > 0 and sol > 0 else None
        try:
            mcap = float(msg.get("marketCapSol") or 0) or None
        except (TypeError, ValueError):
            mcap = None
        try:
            bal = float(msg["newTokenBalance"]) if msg.get("newTokenBalance") is not None else None
        except (TypeError, ValueError):
            bal = None
        return "trade", (sig, mint, w, kind, round(sol, 6), toks, px, mcap, pool, now, bal)
    return None, None


def _ro(path):
    if not path or not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _q(con, sql, args=()):
    if con is None:
        return []
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def wanted(now=None, paper_db=None, strat_db=None, hype_db=None, kol_db=None, league_db=None, min_mcap=30000):
    """(tokens, wallets, open_tokens): what to subscribe to. Tokens: open demo and strategy positions first, then the
    freshest scored candidates (last 2 h, mcap >= min_mcap). Wallets: the Helius webhook list (KOLs, copy, insiders)
    and every wallet a player follows. Capped so one subscription message stays small."""
    now = now or int(time.time())
    tokens, open_tokens = [], set()
    pc = _ro(paper_db or os.path.join(ROOT, "paper.db"))
    for (t,) in _q(pc, "SELECT token FROM trades WHERE status='open'"):
        open_tokens.add(t)
    sc = _ro(strat_db or os.path.join(ROOT, "strat.db"))
    for (t,) in _q(sc, "SELECT DISTINCT token FROM positions WHERE status='open'"):
        open_tokens.add(t)
    tokens += sorted(open_tokens)
    hc = _ro(hype_db or os.path.join(ROOT, "hype.db"))
    for (t,) in _q(hc, "SELECT mint FROM live_launches WHERE pool = 'migration' AND ts >= ? ORDER BY ts DESC LIMIT 60",
                   (now - 7200,)):   # bonded in the last 2 h: the moment worth watching
        if t not in open_tokens and t not in tokens:
            tokens.append(t)
    for (t,) in _q(hc, "SELECT token FROM hype_signals WHERE ts >= ? AND COALESCE(mcap, 0) >= ? "
                       "GROUP BY token ORDER BY MAX(ts) DESC LIMIT ?", (now - 7200, min_mcap, MAX_TOKENS)):
        if t not in open_tokens and t not in tokens:
            tokens.append(t)
    wallets = []
    kc = _ro(kol_db or os.path.join(ROOT, "kol.db"))
    for (v,) in _q(kc, "SELECT value FROM kv WHERE key='chain_hook'"):
        try:
            wallets += json.loads(v).get("wallets") or []
        except ValueError:
            pass
    lc = _ro(league_db or os.path.join(ROOT, "league.db"))
    for (w,) in _q(lc, "SELECT DISTINCT target FROM follows WHERE kind='wallet' AND active=1"):
        if w not in wallets:
            wallets.insert(0, w)
    for c in (pc, sc, hc, kc, lc):
        if c is not None:
            c.close()
    return tokens[:MAX_TOKENS], wallets[:MAX_WALLETS], open_tokens


def subscribe_msgs(tokens, wallets, prev=(set(), set())):
    """Messages to send so the feed matches (tokens, wallets): unsubscribe what is gone, subscribe what is new."""
    out = []
    old_t, old_w = prev
    gone_t, new_t = sorted(old_t - set(tokens)), sorted(set(tokens) - old_t)
    gone_w, new_w = sorted(old_w - set(wallets)), sorted(set(wallets) - old_w)
    if gone_t:
        out.append({"method": "unsubscribeTokenTrade", "keys": gone_t})
    if new_t:
        out.append({"method": "subscribeTokenTrade", "keys": new_t})
    if gone_w:
        out.append({"method": "unsubscribeAccountTrade", "keys": gone_w})
    if new_w:
        out.append({"method": "subscribeAccountTrade", "keys": new_w})
    return out


class Feed:
    """Collects parsed rows and writes them in batches (one commit a second, not one per trade)."""

    def __init__(self, con, followed=frozenset(), log=print):
        self.con, self.followed, self.log = con, set(followed), log
        self.trades, self.launches = [], []
        self.n_trades = self.n_launches = self.n_other = 0
        self.balance_error = False
        self.last_flush = time.time()

    def take(self, msg, now=None):
        kind, row = parse(msg, now)
        if kind == "trade":
            self.trades.append(row)
        elif kind == "launch":
            self.launches.append(row)
        else:
            text = str(msg)
            if "Minimum balance" in text or "only available when connecting with an API key" in text:
                self.balance_error = True   # unfunded key: resubscribe everything at the next refresh (no restart)
            if self.n_other < 20:   # subscription acks and errors: the first few go to the log (5.11.: 0 trades?)
                self.n_other += 1
                self.log(f"live: poruka {text[:200]}")
        return kind

    MAX_BUFFER = 20000   # rows kept in memory while the database is busy (a VACUUM at start-up can hold it ~20 s)

    def flush(self, now=None, force=False):
        """Writes the buffers in one IMMEDIATE transaction. 5.11.: 'database is locked' (another process compacting
        hype.db) crashed the whole worker twice; now the rows stay buffered and the next flush retries."""
        import sqlite3
        from live import store
        now = now or time.time()
        if not force and now - self.last_flush < 1.0:
            return 0
        n = len(self.trades) + len(self.launches)
        if not n:
            self.last_flush = now
            return 0
        try:
            self.con.execute("BEGIN IMMEDIATE")
            store.add_trades(self.con, self.trades)
            store.mirror_chain(self.con, self.trades, self.followed)
            store.add_launches(self.con, self.launches)
            self.con.commit()
        except sqlite3.OperationalError as e:
            try:
                self.con.rollback()
            except sqlite3.Error:
                pass
            if now - getattr(self, "_lock_logged", 0) > 60:
                self._lock_logged = now
                self.log(f"live: baza zauzeta ({str(e)[:60]}), {n} redaka čeka sljedeći pokušaj")
            if len(self.trades) > self.MAX_BUFFER:
                self.trades = self.trades[-self.MAX_BUFFER:]
            if len(self.launches) > self.MAX_BUFFER:
                self.launches = self.launches[-self.MAX_BUFFER:]
            self.last_flush = now
            return 0
        self.n_trades += len(self.trades)
        self.n_launches += len(self.launches)
        self.trades, self.launches = [], []
        self.last_flush = now
        return n


def _day_count(con, feed, now):
    """Trades received today (UTC), kept in the live state so a restart does not reset the budget."""
    from live import store
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    try:
        st = json.loads(store.state(con, "trades_day", "{}") or "{}")
    except ValueError:
        st = {}
    if st.get("day") != day:
        st = {"day": day, "base": 0, "seen": 0}
    seen = st.get("seen", 0)
    n = st.get("base", 0) + (feed.n_trades - seen if feed.n_trades >= seen else feed.n_trades)   # < seen: restarted
    st["base"], st["seen"] = n, feed.n_trades
    store.set_state(con, "trades_day", json.dumps(st))
    return n


async def run(con, log=print, refresh_s=60, new_tokens=False, migrations=True, stop=None):
    """The live loop: connect, subscribe, read forever; resubscribe when the watched lists change."""
    import asyncio
    import websockets
    from live import pulse, store
    backoff = 5
    while not (stop and stop()):
        tokens, wallets, open_tokens = wanted()
        feed = Feed(con, followed=set(wallets), log=log)
        cur = (set(), set())
        try:
            async with websockets.connect(ws_url(), ping_interval=20, ping_timeout=20, max_queue=4096) as ws:
                backoff = 5
                if new_tokens:   # every new pump.fun launch: 99% die in minutes (Nicholas 5.11.), off by default
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                if migrations:   # tokens that bonded (graduated to PumpSwap): free, and these are the ones worth a look
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                for m in subscribe_msgs(tokens, wallets, cur):
                    await ws.send(json.dumps(m))
                cur = (set(tokens), set(wallets))
                store.set_state(con, "connected_ts", int(time.time()))
                store.set_state(con, "subscribed", json.dumps({"tokens": len(tokens), "wallets": len(wallets)}))
                con.commit()
                log(f"live: spojen na PumpPortal, pratim {len(tokens)} tokena i {len(wallets)} novčanika"
                    + ("" if os.environ.get("PUMPPORTAL_API_KEY") else
                       " (BEZ PUMPPORTAL_API_KEY: samo novi tokeni; kupnje/prodaje traže ključ s 0.02 SOL)"))
                last_refresh = last_prune = last_check = time.time()
                over_budget = False
                while not (stop and stop()):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        feed.take(raw)
                    except asyncio.TimeoutError:
                        pass
                    now = time.time()
                    try:
                        if feed.flush(now):
                            store.set_state(con, "last_trade_ts", int(now))
                            con.commit()
                        if now - last_check >= 2:
                            last_check = now
                            pulse.check_dumps(con, open_tokens, now)
                    except sqlite3.OperationalError as e:   # busy database: skip this pass, never die
                        log(f"live: baza zauzeta ({str(e)[:60]}), preskačem prolaz")
                        try:
                            con.rollback()
                        except sqlite3.Error:
                            pass
                        await asyncio.sleep(1)
                        continue
                    if now - last_refresh >= refresh_s:
                        last_refresh = now
                        tokens, wallets, open_tokens = wanted()
                        day_n = _day_count(con, feed, now)
                        if day_n >= MAX_TRADES_DAY:   # budget for today spent: only open positions keep their feed
                            if not over_budget:
                                log(f"live: {day_n} tradeova danas, dnevni strop {MAX_TRADES_DAY} potrošen; do ponoći "
                                    "UTC pratim samo otvorene pozicije i novčanike")
                            over_budget = True
                            tokens = sorted(open_tokens)
                        elif over_budget:
                            over_budget = False
                            log("live: novi dan, živi tok tokena ponovno uključen")
                        feed.followed = set(wallets)
                        if feed.balance_error:   # the key had no SOL: once it is funded, resubscribe everything
                            feed.balance_error = False
                            cur = (set(), set())
                        for m in subscribe_msgs(tokens, wallets, cur):
                            await ws.send(json.dumps(m))
                        cur = (set(tokens), set(wallets))
                        store.set_state(con, "subscribed", json.dumps({"tokens": len(tokens), "wallets": len(wallets)}))
                        store.set_state(con, "counts", json.dumps({"trades": feed.n_trades, "launches": feed.n_launches}))
                        con.commit()
                    if now - last_prune >= 600:
                        last_prune = now
                        store.prune(con, int(now))
                        con.commit()
                        log(f"live: {feed.n_trades} tradeova i {feed.n_launches} novih tokena od spajanja; "
                            f"pratim {len(tokens)} tokena i {len(wallets)} novčanika")
        except Exception as e:  # noqa: BLE001 - network or database: back off and reconnect, never exit
            try:
                feed.flush(force=True)
            except Exception:  # noqa: BLE001
                pass
            log(f"live: {type(e).__name__}: {str(e)[:120]}; ponovno za {backoff} s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
