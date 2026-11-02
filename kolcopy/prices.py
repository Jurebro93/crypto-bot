"""Price of a token at a moment, from its own swaps on chain (Helius getTransactionsForAddress on the mint, 10
credits per page of up to 100 transactions).

The price of a swap is read from the pool's side, so it works on the pump.fun curve, PumpSwap and other SOL pools
alike: in every swap one account that did not sign gives tokens and takes SOL (or the reverse); its SOL change
(lamports + wSOL) over its token change is the price in SOL per token, before the trader's fees. Swaps routed
through a non-SOL pool (USDC) have no such account and are skipped.

"Price at t" = the first swap at or after t within window_s, else the last swap before t (a quiet token is still
sellable at its last price on the curve). Every fetched page is kept in kolcopy.db (px + cover), so several KOLs on
the same token and the points of one event close together share pages.
"""
from retro import chain

CREDITS_PER_PAGE = 10


def _signers(tx):
    out = set()
    for k in tx["transaction"]["message"]["accountKeys"]:
        if isinstance(k, dict) and k.get("signer"):
            out.add(k["pubkey"])
    if not out:
        out.add(chain.keys(tx)[0])
    return out


def swap_price(tx, mint):
    """SOL per token of the swap in tx, or None (failed tx, transfer, non-SOL route)."""
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return None
    ks = chain.keys(tx)
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    lam = {k: (post[i] - pre[i]) / 1e9 for i, k in enumerate(ks) if i < len(pre) and i < len(post)}
    tok, wsol = {}, {}
    for sign, side in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(side) or []:
            ui = b.get("uiTokenAmount") or {}
            try:
                amt = int(ui["amount"]) / 10 ** int(ui["decimals"])
            except (KeyError, TypeError, ValueError):
                continue
            owner = b.get("owner")
            if b.get("mint") == mint:
                tok[owner] = tok.get(owner, 0.0) + sign * amt
            elif b.get("mint") == chain.WSOL:
                wsol[owner] = wsol.get(owner, 0.0) + sign * amt
    signers = _signers(tx)
    best = None
    for owner, d in tok.items():
        if owner in signers or abs(d) < 1e-9:
            continue
        s = wsol.get(owner, 0.0) + lam.get(owner, 0.0)
        if abs(s) < 1e-7 or (d > 0) == (s > 0):
            continue
        if best is None or abs(d) > abs(best[0]):
            best = (d, s)
    if not best:
        return None
    return abs(best[1]) / abs(best[0])


def _sig(tx):
    sigs = (tx.get("transaction") or {}).get("signatures") or []
    return sigs[0] if sigs else f"{tx.get('slot')}:{tx.get('blockTime')}"


class Prices:
    """price_at(mint, t) -> (price, trade_ts) or None, cached in kolcopy.db. page(address, since, until, asc, limit)
    is retro.chain.page (tests pass a fake). credits counts what this object spent."""

    def __init__(self, con, cfg, page=None):
        self.con, self.cfg = con, cfg
        self.page = page or chain.page
        self.credits = 0

    def _fetch(self, mint, **kw):
        txs, _ = self.page(mint, **kw)
        self.credits += CREDITS_PER_PAGE
        rows = []
        for tx in txs:
            p = swap_price(tx, mint)
            if p and tx.get("blockTime"):
                rows.append((mint, _sig(tx), int(tx["blockTime"]), p))
        self.con.executemany("INSERT OR IGNORE INTO px VALUES (?,?,?,?)", rows)
        return txs, rows

    def _covered(self, mint, t):
        return self.con.execute("SELECT a, b FROM cover WHERE mint=? AND a<=? AND b>=? ORDER BY b DESC LIMIT 1",
                                (mint, t, t)).fetchone()

    def _first_from(self, mint, t, b):
        return self.con.execute("SELECT price, ts FROM px WHERE mint=? AND ts>=? AND ts<=? ORDER BY ts, sig LIMIT 1",
                                (mint, t, b)).fetchone()

    def _last_before(self, mint, t):
        cov = self.con.execute("SELECT a FROM cover WHERE mint=? AND a<? AND b>=? ORDER BY a LIMIT 1",
                               (mint, t, t - 1)).fetchone()
        if cov:
            r = self.con.execute("SELECT price, ts FROM px WHERE mint=? AND ts>=? AND ts<? ORDER BY ts DESC, sig DESC "
                                 "LIMIT 1", (mint, cov[0], t)).fetchone()
            if r:
                return tuple(r)
        _, rows = self._fetch(mint, until=t, asc=False, limit=20)
        rows = [r for r in rows if r[2] < t]
        if not rows:
            return None
        best = max(rows, key=lambda r: r[2])
        return best[3], best[2]

    def price_at(self, mint, t):
        t, w = int(t), int(self.cfg["window_s"])
        cov = self._covered(mint, t)
        if cov:
            r = self._first_from(mint, t, cov[1])
            if r:
                return tuple(r)
            if cov[1] >= t + w:  # no swap in the whole window after t: the token is quiet, last price stands
                return self._last_before(mint, t)
        limit = int(self.cfg["page_limit"])
        txs, _ = self._fetch(mint, since=t, until=t + w, asc=True, limit=limit)
        times = [int(x["blockTime"]) for x in txs if x.get("blockTime")]
        # a full page stops at its last transaction; a short one saw everything up to t + window
        b = max(times) - 1 if len(txs) >= limit and times else t + w
        if b >= t:
            self.con.execute("INSERT INTO cover VALUES (?,?,?)", (mint, t, b))
        r = self._first_from(mint, t, max(b, t))
        if r:
            return tuple(r)
        if len(txs) >= limit:
            return None  # a full page of transfers and no swap: unknown, try again next run
        return self._last_before(mint, t)

    def prune(self, before_ts):
        self.con.execute("DELETE FROM px WHERE ts < ?", (before_ts,))
        self.con.execute("DELETE FROM cover WHERE b < ?", (before_ts,))
