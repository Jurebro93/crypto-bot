"""Who bought before a call and who sold into it, from the token's own Helius history (getTransactionsForAddress,
10 credits per 100 txs). Only for the calls that matter: group calls first, then calls by well-scored or big
accounts, at most flows_per_day per day.

Insider: a wallet that bought in the hour before the call and sold within 30 min after it. A wallet that does
this on rotation_min_tokens or more different tokens is a "rotation dev": it moves from token to token, buys
first, gets the calls made, and sells into them.
"""
import json
import time

H = 3600


def _swaps(txs, mint):
    """[(wallet, ts, kind, sol)] buys and sells of `mint` by the OWNER whose balance of the mint changed and who signed
    (kol/groupdisc.owner_trades). 10.11.: until now the first account key, i.e. the fee payer, was taken as the
    trader; a relayed / gasless swap is paid by a relayer for many different traders (Hope research: two relayers
    "bought" for 153 and 104 wallets), so the relayer became an "insider" and the real buyers were lost. SOL legs
    under wallets/rpc.DUST_SOL are fees or rent (a plain transfer), not a trade."""
    from kol.groupdisc import owner_trades
    from wallets import rpc
    out = []
    for tx in txs:
        try:
            trades, _payer, _signers = owner_trades(tx, mint)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        ts = tx.get("blockTime") or 0
        for owner, kind, _amount, sol in trades:
            if abs(sol) >= rpc.DUST_SOL:
                out.append((owner, ts, kind, abs(sol)))
    return out


def analyze(pre, post, cfg):
    """pre/post: swaps before and after the call. Returns (summary, {wallet: (bought_ts, sold_ts, sol_in, sol_out)})."""
    bought, sold = {}, {}
    for w, ts, k, sol in pre:
        if k == "buy":
            b = bought.setdefault(w, [ts, 0.0])
            b[0], b[1] = min(b[0], ts), b[1] + sol
    for w, ts, k, sol in post:
        if k == "sell":
            s = sold.setdefault(w, [ts, 0.0])
            s[0], s[1] = min(s[0], ts), s[1] + sol
    ins = {w: (bought[w][0], sold[w][0], bought[w][1], sold[w][1]) for w in bought
           if w in sold and bought[w][1] >= cfg["insider_min_sol"]}
    summ = {"pre_buy_sol": sum(s for _, _, k, s in pre if k == "buy"),
            "pre_sell_sol": sum(s for _, _, k, s in pre if k == "sell"),
            "post_buy_sol": sum(s for _, _, k, s in post if k == "buy"),
            "post_sell_sol": sum(s for _, _, k, s in post if k == "sell"),
            "buyers_pre": len(bought), "sellers_post": len(sold), "insiders": len(ins),
            "insider_sol": sum(v[3] for v in ins.values())}
    return summ, ins


def due(con, cfg, now):
    """Calls worth a Helius look, best first: first call of each group, then calls by good or big KOLs."""
    rows = con.execute("""
        SELECT c.tweet_id, c.token, c.ts,
               (SELECT 1 FROM groups g WHERE g.token = c.token AND g.start_ts = c.ts) AS grp,
               COALESCE(k.score, 0), COALESCE(c.followers, 0)
        FROM calls c LEFT JOIN kols k ON k.handle = c.handle
        LEFT JOIN flows f ON f.tweet_id = c.tweet_id AND f.token = c.token
        WHERE f.tweet_id IS NULL AND c.kind = 'call' AND c.first_by_kol = 1 AND c.ts < ? AND c.ts > ?
          AND c.p0 IS NOT NULL""", (now - cfg["flow_post_secs"] - 300, now - 7 * 86400)).fetchall()
    good = cfg["good_score"]
    picked = [r for r in rows if r[3] or r[4] >= good or r[5] >= 20000]
    picked.sort(key=lambda r: (-(r[3] or 0), -r[4], -r[5]))
    seen, out = set(), []
    for r in picked:  # one look per token and hour is enough
        k = (r[1], r[2] // H)
        if k not in seen:
            seen.add(k)
            out.append(r[:3])
    return out


def run(con, cfg, now=None, fetch=None, verbose=False):
    """Flows for due calls within today's quota. Returns (calls checked, credits)."""
    from wallets import rpc
    fetch = fetch or rpc.fetch
    now = now or int(time.time())
    done_today = con.execute("SELECT COUNT(*) FROM flows WHERE done_ts >= ?", (now - 86400,)).fetchone()[0]
    quota = max(0, cfg["flows_per_day"] - done_today)
    rot = {r[0] for r in con.execute("SELECT wallet FROM kol_wallets WHERE label = 'rotation_dev'")}
    n = credits = 0
    for tid, token, ts in due(con, cfg, now)[:quota]:
        spent = []
        try:
            pre, _ = fetch(token, since_ts=ts - cfg["flow_pre_secs"], until_ts=ts, max_pages=2,
                           on_credits=spent.append)
            post, _ = fetch(token, since_ts=ts, until_ts=ts + cfg["flow_post_secs"], max_pages=2, oldest_first=True,
                            on_credits=spent.append)
        except Exception as e:
            if verbose:
                print(f"  helius {token}: {type(e).__name__}: {e}")
            continue
        sw_pre, sw_post = _swaps(pre, token), _swaps(post, token)
        summ, ins = analyze(sw_pre, sw_post, cfg)
        rot_sell = len({w for w, _, k, _ in sw_post if k == "sell" and w in rot})
        con.execute("INSERT OR REPLACE INTO flows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, token, ts, summ["pre_buy_sol"], summ["pre_sell_sol"], summ["post_buy_sol"],
                     summ["post_sell_sol"], summ["buyers_pre"], summ["sellers_post"], summ["insiders"],
                     summ["insider_sol"], rot_sell, len(pre) + len(post), sum(spent), now))
        for w, (b_ts, s_ts, sin, sout) in ins.items():
            con.execute("INSERT OR IGNORE INTO insiders VALUES (?,?,?,?,?,?,?)", (w, token, ts, b_ts, s_ts, sin, sout))
        con.commit()
        n += 1
        credits += sum(spent)
    rotation(con, cfg, now)
    con.commit()
    return n, credits


def rotation(con, cfg, now=None):
    """Rebuild kol_wallets from insiders: rotation_dev at rotation_min_tokens tokens, insider below that."""
    now = now or int(time.time())
    rows = con.execute("""SELECT wallet, COUNT(DISTINCT token), SUM(sol_in), SUM(sol_out), GROUP_CONCAT(token),
        MIN(bought_ts), MAX(sold_ts) FROM insiders GROUP BY wallet""").fetchall()
    con.execute("DELETE FROM kol_wallets")
    for w, n, sin, sout, toks, first, last in rows:
        label = "rotation_dev" if n >= cfg["rotation_min_tokens"] else "insider"
        con.execute("INSERT INTO kol_wallets VALUES (?,?,?,?,?,?,?,?)",
                    (w, label, n, sin, sout, json.dumps(sorted(set(toks.split(","))), separators=(",", ":")), first, last))
    return len(rows)
