"""Old tables -> events: one mapping per source table, used three ways.

  sync()      every 5 min (run_events.py tick, light): the rows added since the source's watermark (its last rowid,
              keyset pagination on the rowid b-tree: no table scan) become events. It fills whatever a collector's
              direct emit() lost and is the only writer for the sources without a direct hook (trades, signals, the
              demo's price ticks): the trading code itself is not touched.
  backfill()  the last 14 days, once (night batch, or run_events.py backfill): estimate() first (rows per source in
              the window, events kept after the filters, MB at the measured bytes per row of each type) and one log
              line per source, then batches of BATCH rows, a commit each; it stops when events.db reaches its budget.
  parity()    events vs the old tables over the last N hours, row by row (the uid of every source row): what is
              missing in events and what events has that the source no longer has.

Every source is optional: a missing file or table is skipped (a fresh install, a test).
"""
import json
import os
import re
import sqlite3
import time

from events import store

ROOT = store.ROOT
BATCH = 5000
TICK_MAX_ROWS = 20_000   # per source per sync: a long outage catches up over several ticks, the tick stays light
INIT_S = 24 * 3600       # a source the sync has never seen starts this far back (the backfill does the rest)
BACKFILL_DAYS = 14
TRANSFER_MIN_SOL = store._env_num("EVENTS_TRANSFER_MIN_SOL", 0.5)
MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
# measured 10.11. on synthetic rows (events/store.py schema, 100k rows each, time-ordered): bytes per event incl. indexes
BYTES = {"call": 290, "wallet_buy": 335, "wallet_sell": 335, "transfer": 390, "x_post": 420, "price_tick": 255,
         "trade": 360, "signal": 380}


def db_paths():
    """name -> path of every source database (env overrides as in the rest of the bot)."""
    def env(name, default):
        return os.environ.get(name) or os.path.join(ROOT, default)
    p = {"kol": env("KOL_DB", "kol.db"), "hype": env("HYPE_DB", "hype.db"), "paper": env("PAPER_DB", "paper.db"),
         "scan": env("SCAN_DB", "scan.db"), "early": env("EARLY_DB", "early.db")}
    try:
        from ui import xfeat
        p["xfeat"] = xfeat.db_path()
    except Exception:  # noqa: BLE001
        p["xfeat"] = env("XFEAT_DB", "xfeat.db")
    try:
        from league import store as lstore
        p["league"] = lstore.DB
    except Exception:  # noqa: BLE001
        p["league"] = env("LEAGUE_DB", "league.db")
    try:
        from trade import settings
        p["trade"] = settings.DB
    except Exception:  # noqa: BLE001
        p["trade"] = env("TRADE_DB", "trade.db")
    return p


def _ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


def _mint(x):
    return x if isinstance(x, str) and MINT.fullmatch(x) else None


def _autopilot_users():
    try:
        from trade import settings
        return (settings.LEAGUE_USER, settings.PAPER_USER)
    except Exception:  # noqa: BLE001
        return ("pravi-trade", "autopilot-paper")


# ---------- one mapper per source: a source row -> [events rows] ----------------------------------------------------

def map_call(r):
    _rid, tid, tok, handle, ts, _kind, src, fol, mcap0 = r
    if not tok or not ts:
        return []
    tg = (handle or "").startswith("tg:") or src in ("tg", "tgstat")
    return [store.row("call", ts, tok, "telegram" if tg else "x", handle, None, mcap0,
                      {"tweet_id": tid, "followers": fol or None}, key=f"call|{tid}|{tok}")]


def map_wallet(r, source="helius"):
    _rid, sig, wallet, mint, side, ts, sol = r
    if not sig or not mint or not ts or side not in ("buy", "sell"):
        return []
    return [store.row("wallet_buy" if side == "buy" else "wallet_sell", ts, mint, source, wallet, sol, None, None,
                      key=f"wallet|{sig}|{mint}")]


def map_transfer(r):
    _rid, sig, src, dst, mint, amount, ts = r
    if not sig or not ts:
        return []
    if mint == "SOL":
        if (amount or 0) < TRANSFER_MIN_SOL:
            return []
        return [store.row("transfer", ts, None, "helius", src, amount, None, {"to": dst},
                          key=f"transfer|{sig}|{src}|{dst}|{mint}")]
    return [store.row("transfer", ts, mint, "helius", src, None, None, {"to": dst, "amount": amount},
                      key=f"transfer|{sig}|{src}|{dst}|{mint}")]


def map_price(r, source="dexscreener"):
    _rid, tok, ts, price, mcap = r
    if not tok or not ts or not price:
        return []
    if mcap is not None and mcap < store.MIN_MCAP:
        return []
    return [store.row("price_tick", ts, tok, source, None, None, mcap, {"p": float(f"{price:.6g}")},
                      key=f"price|{tok}|{int(ts) // 60}")]


GROK_X_KEYS = 12


def map_xfeat(r):
    rid, kind, subj, ts, feats, _src, backfill = r
    try:
        f = json.loads(feats or "{}")
    except ValueError:
        f = {}
    keep = {k: v for k, v in list(f.items())[:40] if isinstance(v, (int, float, bool))}
    keep = dict(list(keep.items())[:GROK_X_KEYS])
    if backfill:
        keep["backfill"] = 1
    return [store.row("x_post", ts, subj if kind == "token" else None, "grok", None if kind == "token" else subj,
                      None, None, keep or None, key=f"xf|{rid}")]


def map_xmom(r):
    rid, tok, ts, p15, p60, a15, a60, o15, bot, score, early, called = r
    return [store.row("x_post", ts, tok, "x", None, None, None,
                      {"posts15": p15, "posts60": p60, "authors15": a15, "authors60": a60, "organic15": o15,
                       "bot_share": bot, "score": score, "x_early": early, "caller_called": called},
                      key=f"xm|{rid}")]


def map_trade_open(r):
    rid, user, tok, ts, _closed, _status, size, src, emc, _xmc, _pnl, _ret = r
    if not ts:
        return []
    return [store.row("trade", ts, tok, "autopilot", user, None, emc,
                      {"side": "buy", "id": rid, "size_usd": size, "via": (src or "")[:60] or None},
                      key=f"lt|{rid}|open")]


def map_trade_close(r):
    rid, user, tok, _ts, closed, status, _size, _src, _emc, xmc, pnl, ret = r
    if status != "closed" or not closed:
        return []
    return [store.row("trade", closed, tok, "autopilot", user, None, xmc,
                      {"side": "sell", "id": rid, "pnl_usd": pnl, "ret": ret}, key=f"lt|{rid}|close")]


def _pos_source(reason):
    return "grok" if "grok" in (reason or "").lower() else "autopilot"


def map_pos_open(r):
    rid, tok, ts, _closed, _status, mode, reason, sin, _back = r
    if not ts:
        return []
    return [store.row("trade", ts, tok, _pos_source(reason), "real", sin, None,
                      {"side": "buy", "position_id": rid, "mode": mode, "why": (reason or "")[:80] or None},
                      key=f"pos|{rid}|open")]


def map_pos_close(r):
    rid, tok, _ts, closed, status, mode, reason, sin, back = r
    if status != "closed" or not closed:
        return []
    pnl = (back or 0) - (sin or 0) if sin is not None else None
    return [store.row("trade", closed, tok, _pos_source(reason), "real", back, None,
                      {"side": "sell", "position_id": rid, "mode": mode, "pnl_sol": pnl}, key=f"pos|{rid}|close")]


def map_shadow_dec(r):
    rid, ts, flag, follow_id, tok, old, new = r
    m = _mint(tok)
    return [store.row("signal", ts, m, "autopilot", flag, None, None,
                      {"old": old, "new": new, "follow_id": follow_id, "subject": None if m else tok},
                      key=f"sd|{rid}")]


def map_scan(r):
    _rid, tok, src, stage, found, mcap0 = r
    if not tok or not found:
        return []
    return [store.row("signal", found, tok, "scan", src, None, mcap0, {"stage": stage},
                      key=f"scan|{tok}|{src}|{stage}")]


def map_group(r):
    _rid, ts, src, gid, tok, mcap = r
    if not tok or not ts:
        return []
    return [store.row("signal", ts, tok, "groups", gid, None, mcap, {"kind": src}, key=f"grp|{src}|{gid}|{tok}")]


def map_note(r):
    rid, ts, tok, verdict, conf = r
    if not ts:
        return []
    return [store.row("signal", ts, _mint(tok), "grok", "grok", None, None,
                      {"verdict": verdict, "confidence": conf}, key=f"note|{rid}")]


class Source:
    def __init__(self, name, db, table, cols, mapper, types, ts="ts", where="", ordered=True, ts_index=False,
                 kind="tail"):
        self.name, self.db, self.table, self.cols, self.mapper = name, db, table, cols, mapper
        self.types, self.ts, self.where, self.ordered, self.ts_index, self.kind = (types, ts, where, ordered,
                                                                                  ts_index, kind)

    def low_value(self):
        return all(t in store.LOW_VALUE for t in self.types)


def _users_sql():
    return "user IN (" + ",".join(f"'{u}'" for u in _autopilot_users()) + ")"


def sources():
    users = _users_sql()
    trade_cols = ("id, user, token, opened_ts, closed_ts, status, size_usd, source, entry_mcap, exit_mcap, pnl_usd, "
                  "ret")
    pos_cols = "id, token, opened_ts, closed_ts, status, mode, reason, sol_in, sol_back"
    return [
        # calls: X and Telegram posts in kol.db (kol/collect.save; Telegram via tg.db on the KOL round). kol.db calls
        # are not inserted in time order (the history backfill adds old tweets), hence ordered=False for the backfill
        Source("calls", "kol", "calls", "rowid, tweet_id, token, handle, ts, kind, source, followers, mcap0", map_call,
               ("call",), where="kind = 'call' AND COALESCE(source, '') != 'chain' AND handle NOT LIKE 'w:%'",
               ordered=False, ts_index=True),
        # the wallet feed: Helius webhook (kol/chainwatch) and PumpPortal's followed wallets (live/store.mirror_chain)
        Source("chain_trades", "hype", "chain_trades", "rowid, sig, wallet, mint, side, ts, sol", map_wallet,
               ("wallet_buy", "wallet_sell"), ts_index=True),
        Source("chain_transfers", "hype", "chain_transfers", "rowid, sig, src, dst, mint, amount, ts", map_transfer,
               ("transfer",)),
        Source("x_features", "xfeat", "x_features", "id, subject_kind, subject, ts_asof, features, source, backfill",
               map_xfeat, ("x_post",), ts="ts_asof"),
        Source("x_momentum", "xfeat", "x_momentum", "id, token, ts, posts15, posts60, authors15, authors60, organic15, "
               "bot_share, score, x_early, caller_called", map_xmom, ("x_post",)),
        Source("snaps", "kol", "snaps", "rowid, token, ts, price, mcap", map_price, ("price_tick",)),
        Source("hype_snapshots", "hype", "hype_snapshots", "rowid, token, ts, price, mcap", map_price, ("price_tick",)),
        Source("paper_ticks", "paper", "ticks", "rowid, token, ts, price, mcap", map_price, ("price_tick",)),
        Source("league_trades", "league", "trades", trade_cols, map_trade_open, ("trade",), ts="opened_ts",
               where=users),
        Source("league_closes", "league", "trades", trade_cols, map_trade_close, ("trade",), ts="closed_ts",
               where=users + " AND status = 'closed'", kind="closes"),
        Source("positions", "trade", "positions", pos_cols, map_pos_open, ("trade",), ts="opened_ts"),
        Source("position_closes", "trade", "positions", pos_cols, map_pos_close, ("trade",), ts="closed_ts",
               where="status = 'closed'", kind="closes"),
        Source("shadow_decisions", "league", "shadow_decisions",
               "id, ts, flag, follow_id, token, old_action, new_action", map_shadow_dec, ("signal",)),
        Source("scan_shadow", "scan", "shadow", "rowid, token, source, stage, found_ts, mcap0", map_scan, ("signal",),
               ts="found_ts", ordered=False),
        Source("group_signals", "early", "group_signals", "id, ts, source, gid, token, mcap_usd", map_group,
               ("signal",)),
        Source("grok_opinions", "trade", "assistant_notes", "id, ts, token, verdict, confidence", map_note, ("signal",),
               where="kind = 'signal_opinion'"),
    ]


# ---------- reading a source ----------------------------------------------------------------------------------------

def _has(con, table):
    try:
        return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
    except sqlite3.Error:
        return False


def _cols_ok(con, src):
    have = {r[1] for r in con.execute(f"PRAGMA table_info({src.table})")}
    want = {c.strip().split()[-1] for c in src.cols.split(",")} - {"rowid"}
    return want <= have


def _max_rowid(con, table):
    r = con.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()
    return int(r[0] or 0)


def rowid_at(con, table, ts_col, since):
    """The first rowid whose ts is >= since, by binary search over the rowid b-tree (about 30 lookups, no scan); for
    tables appended in time order. 0 when the table is empty."""
    lo = con.execute(f"SELECT MIN(rowid) FROM {table}").fetchone()[0]
    hi = con.execute(f"SELECT MAX(rowid) FROM {table}").fetchone()[0]
    if lo is None:
        return 0
    lo, hi = int(lo), int(hi) + 1
    while lo < hi:
        mid = (lo + hi) // 2
        r = con.execute(f"SELECT {ts_col} FROM {table} WHERE rowid >= ? ORDER BY rowid LIMIT 1", (mid,)).fetchone()
        if r is None or (r[0] or 0) >= since:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _page(con, src, after, limit, since=None, upto=None):
    w = [f"rowid > {int(after)}"]
    args = []
    if upto is not None:
        w.append(f"rowid <= {int(upto)}")
    if src.where:
        w.append(f"({src.where})")
    if since is not None:
        w.append(f"{src.ts} >= ?")
        args.append(int(since))
    return con.execute(f"SELECT {src.cols} FROM {src.table} WHERE {' AND '.join(w)} ORDER BY rowid LIMIT {int(limit)}",
                       args).fetchall()


def _open(src, paths):
    con = _ro(paths.get(src.db))
    if con is None:
        return None
    try:
        if not _has(con, src.table) or not _cols_ok(con, src):
            con.close()
            return None
    except sqlite3.Error:
        con.close()
        return None
    return con


def _map(src, rows):
    out = []
    for r in rows:
        try:
            out += src.mapper(r)
        except (TypeError, ValueError, IndexError):
            continue
    return out


# ---------- sync: by day only append, a watermark per source --------------------------------------------------------

def _sync_closes(econ, src, scon, now, max_rows):
    """Closed trades since the watermark on the close time (an UPDATE does not move the rowid); small tables."""
    key = f"wm:{src.name}"
    wm = store.kv_get(econ, key)
    since = int(wm["ts"]) - 600 if isinstance(wm, dict) else int(now) - INIT_S
    rows = scon.execute(f"SELECT {src.cols} FROM {src.table} WHERE ({src.where}) AND {src.ts} >= ? ORDER BY {src.ts} "
                        f"LIMIT {int(max_rows)}", (since,)).fetchall()
    n = store.insert(econ, _map(src, rows))
    top = max([since + 600] + [int(r[4 if src.db == "league" else 3] or 0) for r in rows])
    store.kv_put(econ, key, {"ts": top})
    return n, len(rows)


def sync_source(econ, src, paths, now=None, max_rows=TICK_MAX_ROWS):
    """(events written, source rows read) for one source."""
    now = int(now or time.time())
    if src.low_value() and store.tight():
        return 0, 0
    scon = _open(src, paths)
    if scon is None:
        return 0, 0
    try:
        if src.kind == "closes":
            return _sync_closes(econ, src, scon, now, max_rows)
        key = f"wm:{src.name}"
        wm = store.kv_get(econ, key)
        top = _max_rowid(scon, src.table)
        if not isinstance(wm, dict):
            start = rowid_at(scon, src.table, src.ts, now - INIT_S) - 1 if src.ordered else top - 2000
            wm = {"rowid": max(0, start), "ts": now - INIT_S}
        elif top < wm["rowid"]:
            # the table was rebuilt (VACUUM renumbers a table without an INTEGER PRIMARY KEY): start again from the
            # rowid of the watermark's time; the uid keeps the rows already in events from doubling
            wm = {"rowid": max(0, rowid_at(scon, src.table, src.ts, int(wm.get("ts") or now) - 600) - 1),
                  "ts": wm.get("ts")}
        after, n, read = int(wm["rowid"]), 0, 0
        while read < max_rows:
            rows = _page(scon, src, after, min(BATCH, max_rows - read), upto=top)
            if not rows:
                after = top   # the rest up to top did not match the filter
                break
            read += len(rows)
            after = int(rows[-1][0])
            n += store.insert(econ, _map(src, rows))
            if len(rows) < BATCH:
                after = top
                break
        store.kv_put(econ, key, {"rowid": after, "ts": int(now)})
        return n, read
    finally:
        scon.close()


def sync(econ=None, now=None, log=print, names=None):
    """One pass over every source; returns {source: events written}."""
    own = econ is None
    econ = econ or store.connect()
    paths = db_paths()
    out = {}
    try:
        for src in sources():
            if names and src.name not in names:
                continue
            try:
                n, _read = sync_source(econ, src, paths, now)
                econ.commit()
            except sqlite3.Error as e:
                econ.rollback()
                log(f"događaji: sinkronizacija {src.name} nije uspjela ({type(e).__name__}: {e})")
                continue
            if n:
                out[src.name] = n
        return out
    finally:
        if own:
            econ.close()


# ---------- backfill: estimate first, then batches ------------------------------------------------------------------

def _window_start(scon, src, since):
    if not src.ordered:
        return 0
    return max(0, rowid_at(scon, src.table, src.ts, since) - 1)


def _count(scon, src, since, start):
    """Rows of the source in the window: COUNT over the ts index where there is one, else the rowid span."""
    if src.ts_index or src.kind == "closes" or not src.ordered:
        where = f"{src.ts} >= ?" + (f" AND ({src.where})" if src.where else "")
        return int(scon.execute(f"SELECT COUNT(*) FROM {src.table} WHERE {where}", (int(since),)).fetchone()[0])
    return max(0, _max_rowid(scon, src.table) - start)


def _kept_share(scon, src, since, start, sample=2000):
    """Share of source rows that become events (filters: SOL transfers under the minimum, price under 30k, ...),
    from a sample at the end of the window."""
    rows = scon.execute(f"SELECT {src.cols} FROM {src.table} WHERE rowid > ? {'AND (' + src.where + ')' if src.where else ''} "
                        f"AND {src.ts} >= ? ORDER BY rowid DESC LIMIT {sample}", (start, int(since))).fetchall()
    if not rows:
        return 1.0, 0
    ev = _map(src, rows)
    if src.types == ("price_tick",):   # one per mint per minute: duplicates in the sample collapse
        ev = list({r[-1]: r for r in ev}.values())
    return len(ev) / len(rows), len(rows)


def estimate(days=BACKFILL_DAYS, now=None, paths=None, log=print):
    """{source: {"rows", "events", "mb", "types"}} for the last `days` days, plus a "_total" entry; one log line per
    source and a total with the current events.db size and the free disk."""
    now = int(now or time.time())
    since = now - int(days * 86400)
    paths = paths or db_paths()
    out, tot_ev, tot_mb = {}, 0, 0.0
    for src in sources():
        scon = _open(src, paths)
        if scon is None:
            continue
        try:
            start = _window_start(scon, src, since)
            n = _count(scon, src, since, start)
            share, _ = _kept_share(scon, src, since, start)
        except sqlite3.Error as e:
            log(f"događaji: procjena {src.name} nije uspjela ({e})")
            continue
        finally:
            scon.close()
        ev = int(n * share)
        mb = ev * max(BYTES.get(t, 350) for t in src.types) / 1e6
        out[src.name] = {"rows": n, "events": ev, "mb": round(mb, 1), "types": list(src.types)}
        tot_ev += ev
        tot_mb += mb
        log(f"događaji: procjena {src.name}: {n} redaka u {days} d -> ~{ev} događaja, ~{mb:.1f} MB")
    out["_total"] = {"events": tot_ev, "mb": round(tot_mb, 1), "events_db_mb": round(store.size_mb(), 1),
                     "free_mb": store.free_mb(), "budget_mb": store.MAX_MB}
    log(f"događaji: procjena ukupno ~{tot_ev} događaja, ~{tot_mb:.0f} MB (events.db sada {store.size_mb():.0f} MB, "
        f"budžet {store.MAX_MB:.0f} MB, disk slobodno {out['_total']['free_mb'] or 0:.0f} MB)")
    return out


# the order the backfill fills in when the budget does not allow everything: the cheap, valuable ones first
PRIORITY = ("calls", "chain_trades", "league_trades", "league_closes", "positions", "position_closes",
            "shadow_decisions", "scan_shadow", "group_signals", "grok_opinions", "x_features", "x_momentum", "snaps",
            "hype_snapshots", "paper_ticks", "chain_transfers")


def backfill(days=BACKFILL_DAYS, now=None, econ=None, log=print, est=None, budget_mb=None):
    """Copy the last `days` days of every source into events.db, in PRIORITY order, BATCH rows a commit; a source
    whose estimate does not fit into what is left of the budget is skipped (logged). Returns {source: written}."""
    now = int(now or time.time())
    since = now - int(days * 86400)
    paths = db_paths()
    est = est or estimate(days, now, paths, log)
    own = econ is None
    econ = econ or store.connect()
    left = (budget_mb if budget_mb is not None else store.MAX_MB) - store.size_mb()
    free = store.free_mb()
    if free is not None:
        left = min(left, free - store.MIN_FREE_MB)
    out = {}
    by = {s.name: s for s in sources()}
    try:
        for name in PRIORITY:
            src = by.get(name)
            e = est.get(name)
            if src is None or e is None:
                continue
            if e["mb"] > left:
                log(f"događaji: backfill {name} preskočen: ~{e['mb']:.0f} MB, u budžetu ostaje {max(0, left):.0f} MB")
                continue
            scon = _open(src, paths)
            if scon is None:
                continue
            n = 0
            try:
                if src.kind == "closes":
                    rows = scon.execute(f"SELECT {src.cols} FROM {src.table} WHERE ({src.where}) AND {src.ts} >= ?",
                                        (since,)).fetchall()
                    n = store.insert(econ, _map(src, rows))
                    econ.commit()
                else:
                    after = _window_start(scon, src, since)
                    top = _max_rowid(scon, src.table)
                    while True:
                        rows = _page(scon, src, after, BATCH, since=since, upto=top)
                        if not rows:
                            break
                        after = int(rows[-1][0])
                        n += store.insert(econ, _map(src, rows))
                        econ.commit()
                        if len(rows) < BATCH:
                            break
                    # the sync goes on from here: the window up to now is in
                    wm = store.kv_get(econ, f"wm:{name}")
                    if not isinstance(wm, dict) or int(wm.get("rowid") or 0) < top:
                        store.kv_put(econ, f"wm:{name}", {"rowid": top, "ts": now})
                        econ.commit()
            finally:
                scon.close()
            out[name] = n
            left -= n * max(BYTES.get(t, 350) for t in src.types) / 1e6
            log(f"događaji: backfill {name}: {n} novih događaja")
        store.kv_put(econ, "backfill", {"ts": now, "days": days, "written": out})
        econ.commit()
        return out
    finally:
        if own:
            econ.close()


# ---------- parity: events vs the old tables ------------------------------------------------------------------------

def parity(hours=24, now=None, econ=None, sample=5):
    """{source: {"expected", "in_events", "missing", "extra", "missing_sample"}} over the last `hours`: every source
    row of the window mapped to its uid and looked up in events (and the events of the source's types and source
    tag in the window that no source row explains, for the sources that own a type alone)."""
    now = int(now or time.time())
    since = now - int(hours * 3600)
    own = econ is None
    econ = econ or store.ro()
    if econ is None:
        return {}
    paths = db_paths()
    out = {}
    try:
        for src in sources():
            scon = _open(src, paths)
            if scon is None:
                continue
            try:
                rows = scon.execute(f"SELECT {src.cols} FROM {src.table} WHERE {src.ts} >= ? AND {src.ts} <= ?"
                                    + (f" AND ({src.where})" if src.where else ""), (since, now)).fetchall()
            except sqlite3.Error:
                continue
            finally:
                scon.close()
            want = {r[-1]: r for r in _map(src, rows)}
            have = set()
            ids = list(want)
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                have |= {u for (u,) in econ.execute(f"SELECT uid FROM events WHERE uid IN ({','.join('?' * len(part))})",
                                                    part)}
            missing = [want[u] for u in ids if u not in have]
            out[src.name] = {"expected": len(want), "in_events": len(have), "missing": len(missing),
                             "missing_sample": [{"ts": m[0], "mint": m[2], "actor": m[5]} for m in missing[:sample]]}
        # calls own the type 'call' alone: an event the source no longer has (the post became a bot's, or ambiguous)
        if "calls" in out:
            n_ev = econ.execute("SELECT COUNT(*) FROM events WHERE type='call' AND ts >= ? AND ts <= ?",
                                (since * 1000, now * 1000)).fetchone()[0]
            out["calls"]["extra"] = max(0, n_ev - out["calls"]["in_events"])
        return out
    finally:
        if own:
            econ.close()
