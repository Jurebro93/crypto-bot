"""One full pass: universe -> DexScreener -> candles -> features -> both lists -> demo book. Used by run_dugo.py."""
import json
import os
import sys
import time

from dugo import features, holders, learn, score as sc, sources, store

KINDS = sc.KINDS

HERE = os.path.dirname(os.path.abspath(__file__))
D = 86400


def config():
    with open(os.path.join(HERE, "config.json")) as f:
        return json.load(f)


def _log(msg):
    print(f"dugo: {msg}", file=sys.stderr)


def collect(con, cfg, now=None, candle_budget=None):
    """Refresh DexScreener stats for the universe and daily candles for tokens that could qualify."""
    now = int(now or time.time())
    n_seed = store.import_seed(con, now=now)
    if n_seed:
        _log(f"uvezeno {n_seed} tokena s poviješću cijena iz početnog paketa")
    uni = sources.universe(cfg, now)
    try:
        for m in sources.gecko_top(cfg["gecko_top_pages"], cfg["gecko_gap_s"]):
            uni.setdefault(m, "gecko")
    except sources.GeckoBusy:
        _log("gecko top: besplatni GeckoTerminal trenutno zauzet, popis najprometnijih u sljedećem prolazu")
    except Exception as e:
        _log(f"gecko top: {e}")
    known = {r[0] for r in con.execute("SELECT mint FROM tokens")}
    for m, src in uni.items():
        if m not in known:
            con.execute("INSERT OR IGNORE INTO tokens (mint, source, first_seen) VALUES (?,?,?)", (m, src, now))
    pairs = sources.dex_best(set(uni) | known)
    for m, p in pairs.items():
        t = p.get("txns", {}).get("h24", {})
        con.execute("""UPDATE tokens SET symbol=?, name=?, pair=?, created_ts=?, last_dex=?, liquidity=?, mcap=?, vol24=?,
            buys24=?, sells24=?, ch24=?, url=? WHERE mint=?""",
                    (p["baseToken"].get("symbol"), p["baseToken"].get("name"), p.get("pairAddress"),
                     int((p.get("pairCreatedAt") or now * 1000) / 1000), now, (p.get("liquidity") or {}).get("usd"),
                     p.get("marketCap") or p.get("fdv"), (p.get("volume") or {}).get("h24"), t.get("buys"),
                     t.get("sells"), (p.get("priceChange") or {}).get("h24"), p.get("url"), m))
    con.commit()
    # candles: tokens old enough with liquidity, most liquid first, each refreshed about once a day
    lo = min(cfg[k]["min_likvidnost"] for k in KINDS)
    min_age = min(cfg[k]["min_starost_d"] for k in KINDS)
    todo = con.execute("""SELECT mint, pair, candles_ts FROM tokens WHERE liquidity >= ? AND created_ts <= ?
        AND (candles_ts IS NULL OR candles_ts < ?) ORDER BY source='uzor' DESC, candles_ts IS NOT NULL, liquidity DESC""",
                       (lo, now - min_age * D, now - cfg["candles_refresh_h"] * 3600)).fetchall()
    n = 0
    for mint, pair, cts in todo[:candle_budget or cfg["candles_per_run"]]:
        try:
            rows = sources.candles(pair, cfg["gecko_gap_s"], limit=40 if cts else 400)
        except sources.GeckoBusy:   # free limit used up (shared with the KOL module): not an error, next pass
            _log(f"svijeće: besplatni GeckoTerminal trenutno zauzet, {len(todo[:candle_budget or cfg['candles_per_run']]) - n} "
                 "tokena čeka sljedeći prolaz")
            break
        except Exception as e:
            _log(f"svijeće {mint[:6]}: {e}")
            continue
        store.put_candles(con, mint, rows)
        con.execute("UPDATE tokens SET candles_ts=? WHERE mint=?", (now, mint))
        con.commit()        # keep progress if the service restarts mid-pass
        n += 1
        h = sources.holders_birdeye(mint)
        if h:
            con.execute("INSERT OR REPLACE INTO holders VALUES (?,?,?)", (mint, now // D * D, h))
    # references: SOL from its deepest pool (SOL is a quote token, so it is never in the universe), BTC from CoinGecko
    sol = cfg["temelj"]["SOL"]
    last_sol = con.execute("SELECT MAX(day) FROM ref WHERE name='SOL'").fetchone()[0] or 0
    if last_sol < now // D * D - D:
        try:
            p = sources.dex_best({sol}).get(sol)
            if p:
                rows = sources.candles(p["pairAddress"], cfg["gecko_gap_s"], limit=40 if last_sol else 400)
                con.executemany("INSERT OR REPLACE INTO ref VALUES ('SOL',?,?)", [(r[0], r[4]) for r in rows])
        except sources.GeckoBusy:
            _log("SOL: besplatni GeckoTerminal trenutno zauzet, sljedeći prolaz")
        except Exception as e:
            _log(f"SOL: {e}")
    try:
        con.executemany("INSERT OR REPLACE INTO ref VALUES ('BTC',?,?)", list(sources.btc_closes().items()))
    except Exception as e:
        _log(f"BTC: {e}")
    store.prune(con, now)
    con.commit()
    _log(f"{len(uni)} u svemiru, {len(pairs)} na DexScreeneru, {n} tokena dobilo svijeće")
    return n


# stablecoins, wrapped coins and liquid-staking SOL move like their underlying, they are not memecoin picks
NOT_PICKS = {"SOL", "WSOL", "USDC", "USDT", "PYUSD", "USDG", "USDS", "USDE", "EURC", "WETH", "ETH", "WBTC", "CBBTC", "ZBTC",
             "TBTC", "XBTC", "JITOSOL", "MSOL", "BSOL", "JUPSOL", "INF", "BNSOL", "HSOL", "DSOL", "STSOL", "JSOL"}


def not_a_pick(sym, f):
    s = (sym or "").upper().replace(" ", "")
    return s in NOT_PICKS or "USD" in s or (f.get("volatilnost") is not None and f["volatilnost"] < 0.015)


def _growth(con, table, col, mint, ratio=True):
    """Change of `col` scaled to 30 days, newest reading vs the oldest one 7-60 days before it (None without two)."""
    r = con.execute(f"SELECT day, {col} FROM {table} WHERE mint=? AND {col} IS NOT NULL ORDER BY day DESC LIMIT 1",
                    (mint,)).fetchone()
    if not r:
        return None
    o = con.execute(f"""SELECT day, {col} FROM {table} WHERE mint=? AND {col} IS NOT NULL AND day <= ? AND day >= ?
        ORDER BY day LIMIT 1""", (mint, r[0] - 7 * D, r[0] - 60 * D)).fetchone()
    if not o or (ratio and not o[1]):
        return None
    ch = r[1] / o[1] - 1 if ratio else r[1] - o[1]
    return ch * 30 / ((r[0] - o[0]) / D)


def _holders_growth(con, mint, now):
    """Organic growth of holders per 30 days: GeckoTerminal count (free), else Birdeye (paid key)."""
    g = _growth(con, "holder_info", "n", mint)
    return g if g is not None else _growth(con, "holders", "n", mint)


def _listing(con, mint):
    """(top exchanges now, 1 if it got a new exchange vs a reading at least 7 days older else 0) or (None, None)."""
    rows = con.execute("SELECT day, top_cex, all_cex FROM listings WHERE mint=? ORDER BY day DESC", (mint,)).fetchall()
    if not rows:
        return None, None
    old = next((r for r in rows[1:] if r[0] <= rows[0][0] - 7 * D), None)
    new = None if old is None else int(rows[0][2] > old[2] or rows[0][1] > old[1])
    return rows[0][1], new


def rank(con, cfg, now=None):
    """Score both lists for today and write them to snap. Returns {kind: [(mint, score)]}."""
    now = int(now or time.time())
    day = now // D * D
    sol, btc = store.ref(con, "SOL"), store.ref(con, "BTC")
    toks = con.execute("""SELECT mint, symbol, liquidity, mcap, vol24, buys24, sells24, ch24, created_ts FROM tokens
        WHERE candles_ts IS NOT NULL AND last_dex > ?""", (now - 2 * D,)).fetchall()
    soc = sources.social([t[0] for t in toks], now)
    feats, meta = {}, {}
    for mint, sym, liq, mcap, vol, b, s, ch, created in toks:
        cs = store.candles(con, mint)
        f = features.compute(cs, sol, btc)
        if not f:
            continue
        if created:     # free daily candles reach back ~6 months; the pool's age tells how old the token really is
            f["starost_d"] = max(f["starost_d"], (now - created) / D)
        if not_a_pick(sym, f):
            continue
        dead = (ch is not None and ch / 100 <= cfg["mrtav"]["pad_24h"]) or (liq or 0) < cfg["mrtav"]["min_likvidnost"]
        con.execute("UPDATE tokens SET status=? WHERE mint=?", ("mrtav" if dead else "ok", mint))
        if dead:
            continue
        feats[mint] = sc.derive(f, liq, mcap, vol, b, s, soc.get(mint), _holders_growth(con, mint, now))
        meta[mint] = (sym, liq, mcap, cs[-1][4])
    whales = holders.whale_buys(con, now=now)
    for m, f in feats.items():
        f["veliki_kupuju"] = whales.get(m, {}).get("n", 0) if whales else None
        f["burze_velike"], f["nova_burza"] = _listing(con, m)
        f["udio_burzi"], f["rast_udjela_burzi"] = holders.exchange_share(con, m, now)
        # ownership spreading out: share held outside the top 40 wallets going up (percentage points per 30 days)
        f["sirenje_vlasnistva"] = _growth(con, "holder_info", "rest", m, ratio=False)
        hi = con.execute("SELECT n FROM holder_info WHERE mint=? ORDER BY day DESC LIMIT 1", (m,)).fetchone()
        f["holderi"] = hi[0] if hi else None
    refs = list(cfg["uzori"].values())
    sim = sc.similarity(feats, refs)
    for m, f in feats.items():
        f["slicnost_uzoru"] = sim.get(m)
    W = learn.current(cfg)
    out = {}
    con.execute("DELETE FROM snap WHERE day=?", (day,))
    for kind in KINDS:
        el = {m: f for m, f in feats.items() if sc.eligible(kind, f, meta[m][1], meta[m][2], cfg)}
        s = sc.score(el, W[kind]) if el else {}
        order = sorted(s, key=lambda m: -s[m][0])
        for i, m in enumerate(order, 1):
            sym, liq, mcap, px = meta[m]
            con.execute("INSERT OR REPLACE INTO snap VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (day, m, kind, s[m][0], i, px, liq, mcap, store.dumps({k: (round(v, 4) if isinstance(v, float) else v)
                                                                               for k, v in feats[m].items()}),
                         sc.why(s[m][1], feats[m])))
        out[kind] = [(m, s[m][0]) for m in order]
    con.commit()
    _log(", ".join(f"{k}: {len(v)}" for k, v in out.items()))
    return out


def book(con, cfg, now=None):
    """Demo long-term book (no real money, separate from demo trading): every `svaki_d` days the top N of each list
    gets $usd; a position closes when the token has been out of the top 15 for `drzi_izvan_top_d` days, when it is
    marked dead, or (revival list) at `stop_budjenje` from entry. Each position also records SOL's price, so the
    page can show "better or worse than just holding SOL"."""
    now = int(now or time.time())
    k = cfg["knjiga"]
    day = now // D * D
    sol = store.ref(con, "SOL")
    sol_now = sol.get(day) or (sol[max(sol)] if sol else None)
    price = {m: p for m, p in con.execute("SELECT mint, price FROM snap WHERE day=(SELECT MAX(day) FROM snap)")}
    for mint, px in con.execute("SELECT mint, c FROM candles WHERE (mint, day) IN (SELECT mint, MAX(day) FROM candles GROUP BY mint)"):
        price.setdefault(mint, px)
    status = dict(con.execute("SELECT mint, status FROM tokens"))
    for pid, mint, kind, ep, ets in con.execute("SELECT id, mint, kind, entry_price, entry_ts FROM book WHERE exit_ts IS NULL").fetchall():
        px = price.get(mint)
        reason = None
        if status.get(mint) == "mrtav":
            reason = "token umro (likvidnost nestala ili −70% u danu)"
        elif kind == "budjenje" and px and ep and px / ep - 1 <= k["stop_budjenje"]:
            reason = f"stop {k['stop_budjenje']:.0%}"
        else:
            last_top = con.execute("SELECT MAX(day) FROM snap WHERE mint=? AND kind=? AND rank<=15", (mint, kind)).fetchone()[0]
            if (last_top or ets) < now - k["drzi_izvan_top_d"] * D:
                reason = f"ispao s liste na {k['drzi_izvan_top_d']} dana"
        if reason:
            con.execute("UPDATE book SET exit_ts=?, exit_price=?, reason=?, sol_exit=? WHERE id=?",
                        (now, px, reason, sol_now, pid))
    last = con.execute("SELECT MAX(entry_ts) FROM book").fetchone()[0]
    if not last or last < now - k["svaki_d"] * D + 3600:
        mx = cfg["mix"]
        for kind in KINDS:
            ranked = con.execute("""SELECT s.mint, t.symbol, s.price, s.mcap FROM snap s JOIN tokens t ON t.mint=s.mint
                WHERE s.day=? AND s.kind=? ORDER BY s.rank""", (day, kind)).fetchall()
            if kind == "dugorocni":     # healthy mix: the best big, mid and small caps, not only the riskiest small ones
                quota = {"veliki": mx["veliki"], "srednji": mx["srednji"], "mali": mx["mali"]}
                top = []
                for mint, sym, px, mc in ranked:
                    b = "veliki" if (mc or 0) >= mx["veliki_mcap"] else "srednji" if (mc or 0) >= mx["srednji_mcap"] else "mali"
                    if quota[b] > 0:
                        quota[b] -= 1
                        top.append((mint, sym, px))
            else:
                top = [(m, sym, px) for m, sym, px, _ in ranked[:k["top"]]]
            for mint, sym, px in top:
                if not px or con.execute("SELECT 1 FROM book WHERE mint=? AND kind=? AND exit_ts IS NULL",
                                         (mint, kind)).fetchone():
                    continue
                con.execute("""INSERT INTO book (mint, symbol, kind, entry_ts, entry_price, usd, sol_entry)
                    VALUES (?,?,?,?,?,?,?)""", (mint, sym, kind, now, px, k["usd"], sol_now))
    con.commit()


def once(con=None, cfg=None, now=None, learn_too=False):
    cfg = cfg or config()
    own = con is None
    con = con or store.connect()
    try:
        collect(con, cfg, now)
        if learn_too:
            for kind in KINDS:
                r = learn.fit(con, cfg, kind, now)
                _log(f"učenje {kind}: {r['note']}")
        rank(con, cfg, now)
        try:    # top holders, organic holder counts, exchange listings: weekly per token, small Helius sample
            holders.refresh(con, cfg, now, log=_log)
            rank(con, cfg, now)
        except Exception as e:
            _log(f"holderi: {type(e).__name__}: {e}")
        book(con, cfg, now)
    finally:
        if own:
            con.close()
