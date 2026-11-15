"""Who traded each event: the wallets that bought before t0 (up to pre_days, 7 days: the owner's "danima prije") and
the ones that sold into the jump (t0 .. peak + 1 h), with how many sells and how much SOL.

Free sources first (kol/precall._sources: early.db precall_trades / group_buys / early_buyers, hype.db live_trades /
chain_trades, kol.db insiders; plus wallets.db wallet_trades, the scored wallets' whole histories, and our own
i2_trades). Helius (wallets/rpc.fetch, getTransactionsForAddress, 10 credits a page of 100) only within the day cap
(store.helius_left), each read once (i2_fetch):
  1) the mint in the jump window, oldest first (sell_pages) and the 6 h before t0, newest first (pre_pages)
  2) the TOKEN ACCOUNTS of the top sellers whose earlier buy we do not know (lookups_per_event, the wallets that sold
     into OTHER events first, then by SOL): their history of this one token 7 days before t0, usually one page. A
     token account carries only that wallet's trades of that mint, so "did the seller buy days before" costs ~10
     credits instead of the mint's whole week (Pretpostavka: getTransactionsForAddress on a token account returns
     the transactions that touched it; the docs list any address).
Every trade is attributed to the SIGNER whose balance of the mint changed (kol/groupdisc.owner_trades), never to a
relayer that paid the fee. Same-owner wallets (a shared non-hub funder, a non-relayer fee payer, corr.db owner
groups) are merged into one owner id (kol/groupdisc.owner_ids), so wallet rotation does not hide them.
"""
import json
from collections import Counter, defaultdict

from insajderi import store

DUST_SOL = 0.001


def _chunks(xs, n=100):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _in(xs):
    return ",".join("?" * len(xs))


# ---------- sources ---------------------------------------------------------------------------------------------------

def sources(con, p, toks):
    """{token: [(wallet, ts, side, sol, payer, src)]} from every free source + our own Helius rows (i2_trades)."""
    from kol import precall
    ec = store.ro(p.get("early_db"))
    by = defaultdict(list, precall._sources(ec if ec is not None else _Empty(), p, list(toks)))   # no early.db:
    if ec is not None:                                                                            # hype / kol still
        ec.close()
    for ch in _chunks(toks, 400):
        for m, w, ts, side, sol, payer in store.q(con, f"SELECT mint, wallet, ts, side, sol, payer FROM i2_trades WHERE "
                                                       f"mint IN ({_in(ch)})", ch):
            by[m].append((w, ts, side, sol, payer, "helius2"))
    wc = store.ro(p.get("wallet_db"))
    if wc is not None:
        for ch in _chunks(toks, 400):
            for w, m, ts, kind, sol in store.q(wc, f"SELECT wallet, mint, ts, kind, sol FROM wallet_trades WHERE kind IN "
                                                   f"('buy', 'sell') AND mint IN ({_in(ch)})", ch):
                by[m].append((w, ts, kind, abs(sol) if sol is not None else None, None, "wallets"))
        wc.close()
    return by


class _Empty:
    """A connection with no tables: precall._sources' early.db part reads nothing."""
    def execute(self, *_a, **_k):
        import sqlite3
        raise sqlite3.OperationalError("no early.db")


def participants(e, trades, c):
    """trades of one token -> {wallet: row} for event e: the first buy in [t0 - pre_days, t0) and its SOL, the sells in
    [t0, win_end] (count, SOL, first). Dust (known SOL under min_sol on both sides) out; duplicates of one trade from
    several sources are counted once (same wallet, side, second)."""
    t0, end = int(e["t0"]), int(e["win_end"])
    lo = t0 - int(c["pre_days"]) * 86400
    seen, out = set(), {}
    calls = sorted((ts, h) for h, ts in (e.get("callers") or {}).items())
    for w, ts, side, sol, _payer, src in sorted(trades, key=lambda x: x[1] or 0):
        if not w or ts is None or side not in ("buy", "sell"):
            continue
        k = (w, side, int(ts))
        if k in seen:
            continue
        seen.add(k)
        if side == "buy" and lo <= ts < t0:
            o = out.setdefault(w, _row())
            if o["buy_ts"] is None:
                o["buy_ts"] = int(ts)
            if sol is not None:
                o["sol_in"] = (o["sol_in"] or 0) + abs(sol)
            o["src"].add(src)
        elif side == "sell" and t0 <= ts <= end:
            o = out.setdefault(w, _row())
            o["n_sells"] += 1
            if sol is not None:
                o["sol_out"] = (o["sol_out"] or 0) + abs(sol)
            if o["first_sell_ts"] is None:
                o["first_sell_ts"] = int(ts)
            o["src"].add(src)
    res = {}
    for w, o in out.items():
        small_in = o["sol_in"] is not None and o["sol_in"] < c["min_sol"]
        small_out = o["sol_out"] is not None and o["sol_out"] < c["min_sol"]
        if (o["buy_ts"] is None or small_in) and (not o["n_sells"] or small_out):
            continue
        o["bought_before"] = int(o["buy_ts"] is not None and not small_in)
        o["sold_into"] = int(bool(o["n_sells"]) and not small_out)
        if o["bought_before"]:
            nxt = [ts for ts, _h in calls if ts > o["buy_ts"]]
            o["lead_s"] = (nxt[0] if nxt else t0) - o["buy_ts"]
        res[w] = o
    return res


def _row():
    return {"buy_ts": None, "sol_in": None, "n_sells": 0, "sol_out": None, "first_sell_ts": None, "src": set(),
            "bought_before": 0, "sold_into": 0, "lead_s": None}


def store_participants(con, eid, rows):
    con.execute("DELETE FROM i2_part WHERE eid = ?", (eid,))
    con.executemany("INSERT INTO i2_part VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(eid, w, None, o["buy_ts"], o["sol_in"], o["n_sells"], o["sol_out"], o["first_sell_ts"],
                      o["bought_before"], o["sold_into"], o["lead_s"], ",".join(sorted(o["src"]))) for w, o in rows.items()])
    con.execute("UPDATE i2_events SET n_part = ? WHERE eid = ?", (len(rows), eid))


def build(con, p, c, events):
    """i2_part of `events` from every source we have now. Returns the number of events built."""
    n = 0
    for ch in _chunks(events, 100):
        src = sources(con, p, sorted({e["token"] for e in ch}))
        for e in ch:
            store_participants(con, e["eid"], participants(e, src.get(e["token"]) or [], c))
            n += 1
        con.commit()
    return n


# ---------- Helius --------------------------------------------------------------------------------------------------

def token_accounts(tx, mint):
    """{owner: token account address} of `mint` in one raw transaction (pre/post token balances' accountIndex)."""
    meta = tx.get("meta") or {}
    raw = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in raw]
    out = {}
    for b in (meta.get("postTokenBalances") or []) + (meta.get("preTokenBalances") or []):
        if b.get("mint") != mint or not b.get("owner"):
            continue
        i = b.get("accountIndex")
        if isinstance(i, int) and 0 <= i < len(keys):
            out.setdefault(b["owner"], keys[i])
    return out


def _rows_of(txs, mint):
    from kol import groupdisc as gd
    rows = []
    for tx in txs or []:
        trades, payer, _s = gd.owner_trades(tx, mint)
        if not trades:
            continue
        accts = token_accounts(tx, mint)
        sig = ((tx.get("transaction") or {}).get("signatures") or ["?"])[0]
        for o, side, amount, sol in trades:
            if abs(sol) >= DUST_SOL:
                rows.append((mint, o, sig, tx.get("blockTime") or 0, tx.get("slot"), side, abs(sol), amount, payer,
                             accts.get(o)))
    return rows


def _fetched(con, key):
    return bool(store.q(con, "SELECT 1 FROM i2_fetch WHERE key = ?", (key,)))


def fetch_event(con, p, c, e, now, budget, fetch=None, seller_events=None, log=print):
    """Helius for one event within `budget` credits: the jump window, the 6 h before, then the token accounts of the
    top sellers without a known earlier buy. -> credits spent."""
    if fetch is None:
        from wallets import rpc
        fetch = rpc.fetch
    spent = [0]

    def on_credits(n):
        spent[0] += n

    def page_cost(pages):
        return int(pages) * 10

    tok, t0, end = e["token"], int(e["t0"]), int(e["win_end"])
    short = False   # the budget ran out inside this event: it stays due (what was read is never read again)
    steps = (("sell", t0, end, int(c["sell_pages"]), True), ("pre", t0 - 6 * 3600, t0, int(c["pre_pages"]), False))
    for name, since, until, pages, asc in steps:
        key = f"mint:{name}:{e['eid']}"
        if pages <= 0 or _fetched(con, key):
            continue
        if spent[0] + page_cost(pages) > budget:
            short = True
            continue
        before = spent[0]
        try:
            txs, complete = fetch(tok, since_ts=since, until_ts=until, max_pages=pages, oldest_first=asc,
                                  on_credits=on_credits)
        except Exception as e2:  # noqa: BLE001 - one event fails, the pass goes on
            log(f"{store.PREFIX}{tok[:6]}… Helius {type(e2).__name__}: {str(e2)[:80]}")
            continue
        con.executemany("INSERT OR IGNORE INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", _rows_of(txs, tok))
        con.execute("INSERT OR REPLACE INTO i2_fetch VALUES (?,?,?,?,?)",
                    (key, int(now), spent[0] - before, len(txs), int(bool(complete))))
        con.commit()
    # 2) the sellers' token accounts, 7 days back
    src = sources(con, p, [tok]).get(tok) or []
    part = participants(e, src, c)
    sellers = [(w, o) for w, o in part.items() if o["sold_into"] and not o["bought_before"]]
    acct = {w: a for w, a in store.q(con, "SELECT wallet, tacct FROM i2_trades WHERE mint = ? AND tacct IS NOT NULL",
                                     (tok,))}
    rec = seller_events or {}
    sellers.sort(key=lambda x: (-rec.get(x[0], 0), -(x[1]["sol_out"] or 0), -x[1]["n_sells"]))
    looked = 0
    for w, _o in sellers:
        if looked >= int(c["lookups_per_event"]):
            break
        a = acct.get(w)
        key = f"acct:{a}:{t0}"
        if not a or _fetched(con, key):
            continue
        if spent[0] + page_cost(c["acct_pages"]) > budget:
            short = True
            break
        before = spent[0]
        try:
            txs, complete = fetch(a, since_ts=t0 - int(c["pre_days"]) * 86400, until_ts=t0,
                                  max_pages=int(c["acct_pages"]), oldest_first=True, on_credits=on_credits)
        except Exception as e2:  # noqa: BLE001
            log(f"{store.PREFIX}{a[:6]}… Helius {type(e2).__name__}: {str(e2)[:80]}")
            continue
        con.executemany("INSERT OR IGNORE INTO i2_trades VALUES (?,?,?,?,?,?,?,?,?,?)", _rows_of(txs, tok))
        con.execute("INSERT OR REPLACE INTO i2_fetch VALUES (?,?,?,?,?)",
                    (key, int(now), spent[0] - before, len(txs), int(bool(complete))))
        con.commit()
        looked += 1
    if not short:
        con.execute("UPDATE i2_events SET fetched = 1 WHERE eid = ?", (e["eid"],))
    con.commit()
    return spent[0]


def fetch_due(con, p, c, events, now, budget, fetch=None, log=print):
    """Helius for the events not fetched yet, best first (prio), within `budget`. -> (events read, credits)."""
    todo = sorted((e for e in events if not e.get("fetched") and e["win_end"] <= now), key=lambda e: -(e.get("prio") or 0))
    rec = Counter(w for (w,) in store.q(con, "SELECT wallet FROM i2_part WHERE sold_into = 1"))
    total, n = 0, 0
    for e in todo[:int(c["max_events_pass"])]:
        left = budget - total
        if left < 10:
            break
        got = fetch_event(con, p, c, e, now, left, fetch=fetch, seller_events=rec, log=log)
        store.add_spent(con, now, got)
        total += got
        n += 1
    return n, total


# ---------- owners --------------------------------------------------------------------------------------------------

def paid_pairs(con, p):
    """[(payer, wallet)] where a fee payer paid for somebody else's trade (ours + early.db's)."""
    out = store.q(con, "SELECT DISTINCT payer, wallet FROM i2_trades WHERE payer IS NOT NULL AND payer != wallet")
    ec = store.ro(p.get("early_db"))
    for t in ("precall_trades", "group_buys"):
        out += store.q(ec, f"SELECT DISTINCT payer, wallet FROM {t} WHERE payer IS NOT NULL AND payer != wallet")
    if ec is not None:
        ec.close()
    return out


def corr_groups(corr_db):
    """[[wallet, ...]] of corr/analyze's owner groups in the newest corr.db snapshot (read-only; [] without one)."""
    con = store.ro(corr_db)
    rows = store.q(con, "SELECT data FROM snapshots ORDER BY ts DESC LIMIT 1")
    if con is not None:
        con.close()
    try:
        data = json.loads(rows[0][0]) if rows else {}
    except (ValueError, TypeError):
        return []
    out = []
    for g in (data or {}).get("owner_groups") or []:
        ms = g.get("members") if isinstance(g, dict) else g
        if isinstance(ms, list):
            ms = [m.get("wallet") if isinstance(m, dict) else m for m in ms]
            ms = [m for m in ms if isinstance(m, str) and m]
            if len(ms) >= 2:
                out.append(ms)
    return out


def owners(con, p, c, wallets, mints):
    """({wallet: owner id}, relayers): same funder (not a hub, not a relayer), a non-relayer fee payer, corr.db owner
    groups. A wallet without a tie is its own owner."""
    from kol import groupdisc as gd
    paid = paid_pairs(con, p)
    relay = gd.relayers(paid, int(c["relayer_min"]))
    ws = set(wallets) - relay
    funders = gd._funders(p, list(mints), ws) if ws else defaultdict(set)
    for pay, w in paid:
        if w in ws and pay not in relay:
            funders[w].add(pay)
    for grp in corr_groups(p.get("corr_db")):
        mem = [m for m in grp if m in ws]
        for m in mem[1:]:
            funders[m].add(mem[0])
    fan = Counter(f for fs in funders.values() for f in fs)
    hubs = {f for f, n in fan.items() if n > int(c["hub_min"])}
    own = gd.owner_ids(funders, hubs, relay)
    return {w: own.get(w, w) for w in ws}, relay


def assign_owners(con, p, c):
    """Write i2_part.owner for every participant. Returns (owner map, relayers)."""
    wallets = {w for (w,) in store.q(con, "SELECT DISTINCT wallet FROM i2_part")}
    mints = {m for (m,) in store.q(con, "SELECT DISTINCT token FROM i2_events")}
    own, relay = owners(con, p, c, wallets, mints)
    con.executemany("UPDATE i2_part SET owner = ? WHERE wallet = ?",
                    [(own.get(w, w) if w not in relay else "relayer:" + w, w) for w in wallets])
    con.commit()
    return own, relay


def waves(con, c, min_owners=3, min_sol=1.0):
    """{eid: (ts, n owners, SOL)}: 3+ owners that bought >= 1 SOL each in the 6 h before t0 (a whale / insider wave)."""
    out = {}
    rows = store.q(con, """SELECT p.eid, p.owner, p.buy_ts, p.sol_in, e.t0 FROM i2_part p JOIN i2_events e ON e.eid = p.eid
        WHERE p.bought_before = 1 AND p.sol_in >= ? AND p.buy_ts >= e.t0 - 21600""", (min_sol,))
    by = defaultdict(dict)
    for eid, o, bts, sol, _t0 in rows:
        cur = by[eid].get(o or "?")
        by[eid][o or "?"] = (min(bts, cur[0]) if cur else bts, (cur[1] if cur else 0) + sol)
    for eid, d in by.items():
        if len(d) >= min_owners:
            ts = sorted(v[0] for v in d.values())[min_owners - 1]
            out[eid] = (ts, len(d), sum(v[1] for v in d.values()))
    return out
