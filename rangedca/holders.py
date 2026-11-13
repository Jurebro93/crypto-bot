"""Spec 5, "holders that got the token by transfer without buying start net-selling > 2 % of supply in 15 min"
(flag range_dca). Only for tokens with an OPEN range position, and behind its own switch:

    RANGE_HOLDER_RULE=log   (default) measured and written to range.db events + the log; never closes a position
    RANGE_HOLDER_RULE=act   a hit gives the token up (open rounds out, excluded 24 h)
    RANGE_HOLDER_RULE=off   nothing is read

It stays log-only until the numbers are checked by hand (10.11., coordinator: research/hope.py's "received without
buying" took the fee payer, accountKeys[0], for the trader; on Hope most of those "receivers" were ordinary buyers
whose swaps a relayer paid for).

Attribution, per transaction: every owner whose balance of the token changed is looked at on its own. An owner
that SIGNED and whose token went up while its SOL + wSOL went down bought; token down and SOL up sold; token up
without paying received (a transfer to it, or a buy someone else made for it); token down without its signature is
a program-owned vault (the pool). The fee payer is never taken for the trader: a fee payer that pays for 3 or more
different trading owners in one batch is a relayer and is reported as such. Owners that appear unsigned in >= 30 %
of the batch (the pool's vault authority) and the pool address are left out.

The ledger (range.db holder_ledger: bought / sold / received / sent per owner) starts with up to BACKFILL_PAGES pages
of the pool's newest transactions when the first round in the token opens, then grows by the transactions since the
last check. A "transfer holder" is an owner with tokens received and nothing bought in the ledger, so a wallet that
bought before the ledger's first transaction looks like one: another reason the rule only logs.

Cost (CLAUDE.md, measured before spending): Helius getTransactionsForAddress, 100 full transactions a page at about
PAGE_CREDITS (10) credits (research/hope.py's measurement), backfill 10 pages (~100 credits) once per token, then
1-3 pages every 15 min while the position is open (~1-3k credits a day for a busy token), at most
RANGE_HELIUS_CREDITS_DAY (3000) a day for all tokens together; counted in range.db kv and by usage/meter.
"""
import os
import time

from . import data

PAGE_CREDITS = 10
CREDITS_DAY = int(os.environ.get("RANGE_HELIUS_CREDITS_DAY", "3000"))
BACKFILL_PAGES = int(os.environ.get("RANGE_HOLDER_BACKFILL_PAGES", "10"))
STEP_PAGES = 3
EVERY_S = 15 * 60
NET_SELL_PCT = 2.0
WSOL = "So11111111111111111111111111111111111111112"

SCHEMA = """CREATE TABLE IF NOT EXISTS holder_ledger (token TEXT, owner TEXT, bought REAL, sold REAL, recv REAL, sent REAL,
    PRIMARY KEY (token, owner))"""


def mode():
    m = (os.environ.get("RANGE_HOLDER_RULE") or "log").strip().lower()
    return m if m in ("off", "log", "act") else "log"


def _bal(rows, mint):
    out = {}
    for b in rows or []:
        if b.get("mint") == mint and b.get("owner"):
            out[b["owner"]] = out.get(b["owner"], 0.0) + float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
    return out


def parse(tx, mint):
    """One full jsonParsed transaction -> {"ts", "sig", "fee_payer", "rows": [{owner, d (token change), sol (SOL +
    wSOL change, the fee excluded), signed, kind: buy | sell | recv | sent | pool}]}; None for a failed one."""
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return None
    msg = (tx.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    pub = [k.get("pubkey") if isinstance(k, dict) else k for k in keys]
    if not pub:
        return None
    signers = {k.get("pubkey") for k in keys if isinstance(k, dict) and k.get("signer")} or {pub[0]}
    fee_payer = pub[0]
    pre, post = _bal(meta.get("preTokenBalances"), mint), _bal(meta.get("postTokenBalances"), mint)
    wpre, wpost = _bal(meta.get("preTokenBalances"), WSOL), _bal(meta.get("postTokenBalances"), WSOL)
    lam = {}
    for i, k in enumerate(pub):
        try:
            lam[k] = (meta["postBalances"][i] - meta["preBalances"][i]) / 1e9
        except (KeyError, IndexError, TypeError):
            pass
    rows = []
    for owner in set(pre) | set(post):
        d = post.get(owner, 0.0) - pre.get(owner, 0.0)
        if abs(d) < 1e-9:
            continue
        sol = lam.get(owner, 0.0) + wpost.get(owner, 0.0) - wpre.get(owner, 0.0)
        if owner == fee_payer:
            sol += (meta.get("fee") or 0) / 1e9   # the network fee is not a price paid for the token
        signed = owner in signers
        if signed and d > 0 and sol < -1e-6:
            kind = "buy"
        elif signed and d < 0 and sol > 1e-6:
            kind = "sell"
        elif d > 0:
            kind = "recv"
        else:
            kind = "sent" if signed else "pool"
        rows.append({"owner": owner, "d": d, "sol": sol, "signed": signed, "kind": kind})
    return {"ts": tx.get("blockTime") or 0, "sig": ((tx.get("transaction") or {}).get("signatures") or [None])[0],
            "fee_payer": fee_payer, "rows": rows}


def classify(parsed, pool=None):
    """(rows without the pool's vaults, relayers): drops the pool address and owners that sit unsigned in >= 30 % of
    the batch; a fee payer paying for >= 3 different trading owners is a relayer."""
    n = len(parsed)
    unsigned = {}
    paid_for = {}
    for p in parsed:
        for r in p["rows"]:
            if not r["signed"]:
                unsigned[r["owner"]] = unsigned.get(r["owner"], 0) + 1
            if r["kind"] in ("buy", "sell") and r["owner"] != p["fee_payer"]:
                paid_for.setdefault(p["fee_payer"], set()).add(r["owner"])
    vaults = {o for o, k in unsigned.items() if n >= 10 and k >= 0.3 * n}
    if pool:
        vaults.add(pool)
    relayers = {f for f, owners in paid_for.items() if len(owners) >= 3}
    out = []
    for p in parsed:
        for r in p["rows"]:
            if r["owner"] in vaults or r["kind"] == "pool" or r["owner"] in relayers:
                continue
            out.append({**r, "ts": p["ts"]})
    return out, relayers


def ledger_add(con, token, rows):
    con.execute(SCHEMA)
    for r in rows:
        col = {"buy": "bought", "sell": "sold", "recv": "recv", "sent": "sent"}[r["kind"]]
        amt = abs(r["d"])
        con.execute("INSERT OR IGNORE INTO holder_ledger VALUES (?,?,0,0,0,0)", (token, r["owner"]))
        con.execute(f"UPDATE holder_ledger SET {col}={col}+? WHERE token=? AND owner=?", (amt, token, r["owner"]))


def transfer_holders(con, token):
    con.execute(SCHEMA)
    return {r[0] for r in con.execute("SELECT owner FROM holder_ledger WHERE token=? AND recv>0 AND bought<=0", (token,))}


def net_sell_pct(con, token, window_rows, supply):
    """% of supply the transfer holders sold net in window_rows (their sales minus their buys)."""
    if not supply:
        return None, 0
    th = transfer_holders(con, token)
    net, who = 0.0, set()
    for r in window_rows:
        if r["owner"] not in th:
            continue
        if r["kind"] == "sell":
            net += abs(r["d"])
            who.add(r["owner"])
        elif r["kind"] == "buy":
            net -= abs(r["d"])
    return net / supply * 100, len(who)


def _pages(post, pool, since_ts, n, desc=False):
    flt = {"status": "succeeded", "tokenAccounts": "balanceChanged"}
    if since_ts:
        flt["blockTime"] = {"gt": int(since_ts)}
    out, token, used = [], None, 0
    for _ in range(n):
        opts = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                "limit": 100, "sortOrder": "desc" if desc else "asc", "filters": flt}
        if token:
            opts["paginationToken"] = token
        res = post("getTransactionsForAddress", [pool, opts]) or {}
        used += 1
        page = res.get("data") or []
        out += page
        token = res.get("paginationToken")
        if not token or not page:
            break
    return out, used


def _post():
    if not os.environ.get("HELIUS_API_KEY"):
        return None
    from research import hope   # the metered, uncached Helius call (event_calendar/http._fetch)
    return hope._post


def check(con, token, pool, supply, now=None, post=None):
    """One check of an open range token, at most every EVERY_S. Returns the reason to give the token up when the
    rule ACTS and the transfer holders sold > 2 % of supply net; None otherwise (log mode logs the same hit)."""
    m = mode()
    now = int(now or time.time())
    if m == "off" or not pool:
        return None
    st = data.kv_get(con, f"hold:{token}") or {}
    if now - st.get("checked", 0) < EVERY_S:
        return st.get("why") if m == "act" else None
    post = post or _post()
    if post is None:
        return None
    left = (CREDITS_DAY - data.day_used(con, "helius_day", now)) // PAGE_CREDITS
    first = not st.get("last_ts")
    want = BACKFILL_PAGES if first else STEP_PAGES
    if left < 1:
        return None
    try:
        txs, used = _pages(post, pool, None if first else st["last_ts"], min(want, left), desc=first)
    except Exception as e:  # noqa: BLE001 - a failed read: tried again in 15 min
        print(f"range: holderi {token[:6]}: {type(e).__name__}", flush=True)
        st["checked"] = now
        data.kv_put(con, f"hold:{token}", st)
        con.commit()
        return None
    data.day_add(con, "helius_day", used * PAGE_CREDITS, now)
    parsed = [p for p in (parse(t, token) for t in txs) if p]
    rows, relayers = classify(parsed, pool)
    ledger_add(con, token, rows)
    window = [r for r in rows if r["ts"] >= now - EVERY_S]
    pct, n = net_sell_pct(con, token, window, supply)
    why = None
    if pct is not None and pct > NET_SELL_PCT:
        why = f"holderi s prijenosom bez kupnje neto prodali {pct:.1f} % supplyja u 15 min ({n} novčanika)"
    note = (f"{len(parsed)} transakcija, {used} str. (~{used * PAGE_CREDITS} kredita), releji {len(relayers)}, "
            f"neto prodaja holdera s prijenosom {pct if pct is not None else 0:.2f} % [{m}]")
    data.event(con, token, "holderi", note, now)
    if why:
        print(f"range: {token[:6]} {why} ({'zatvaram' if m == 'act' else 'samo zapis'})", flush=True)
    st.update(checked=now, last_ts=max([st.get("last_ts") or 0] + [p["ts"] for p in parsed]), why=why)
    data.kv_put(con, f"hold:{token}", st)
    con.commit()
    return why if m == "act" else None
