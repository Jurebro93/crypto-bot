"""Meta / beta detector (10.11., spec item 2; "beta_of_runner" did not exist in the repo, this is it).

Every meta_every_min (15) the top runners become the active metas: of the tokens the scanner priced in the last day
(DexScreener) plus GeckoTerminal's trending pools (one budgeted call), those with market cap >= runner_min_mcap,
the best half by 24 h rise and the best half by 1 h rise (runners, default 20). Each meta keeps its narrative
keywords from the name, the ticker and the DexScreener profile description when the token has one.

Every new scanner token and every new caller / wallet signal is compared with the metas once (beta_score, 0-1):
    0.6 * ticker_hit       the runner's ticker (3+ letters, not a filler word) inside the token's ticker or name
                           ("WIF" in "BABYWIF"): the classic beta
  + 0.4 * name_overlap     share of the runner's name keywords the token also carries
  + 0.2 * desc_overlap     Jaccard of all keywords (name, ticker, description) of the two
capped at 1. beta_score >= beta_min (0.6) makes the token a "beta" of that runner (beta_parent). A runner is never
its own beta. Then its result at 1 h / 4 h / 24 h is measured next to the parent's over the same time: a beta while
the meta keeps rising and a beta while it fades are reported apart (report_rows).
"""
import json
import re

STOP = {"the", "and", "for", "with", "this", "that", "coin", "token", "sol", "solana", "crypto", "meme", "memecoin",
        "pump", "fun", "official", "real", "new", "inu", "on", "of", "a", "an", "is", "it", "to", "in", "by", "my",
        "your", "our", "just", "only", "first", "best", "community", "cto", "ca", "dex", "x", "www", "com", "https",
        "http", "io", "app", "launch", "launched", "join", "telegram", "twitter", "website", "100x", "1000x"}
SHORT_OK = {"ai"}   # two-letter words that are a narrative on their own
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def words(text):
    """Lower-case keywords of a text: camelCase split ("BabyTrump" -> baby, trump), filler words and numbers out."""
    out = []
    for w in _WORD.findall(text or ""):
        for part in _CAMEL.split(w):
            p = part.lower()
            if (len(p) >= 3 or p in SHORT_OK) and p not in STOP and not p.isdigit():
                out.append(p)
    return out


def keywords(name, symbol, description=""):
    """{keyword: weight}: ticker 1.0, name 0.8, description 0.4 (the strongest place a word appears)."""
    kw = {}
    for text, wgt in ((description, 0.4), (name, 0.8), (symbol, 1.0)):
        for w in words(text):
            kw[w] = max(kw.get(w, 0.0), wgt)
    return kw


def _alnum(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def beta_score(cand, meta):
    """(score 0-1, matched keywords) of a candidate {token, symbol, name, description} against a meta {token, symbol,
    name, keywords}. See the module text for the formula."""
    if not meta or cand.get("token") == meta.get("token"):
        return 0.0, []
    ticker = _alnum(meta.get("symbol"))
    text = _alnum(cand.get("symbol")) + " " + _alnum(cand.get("name"))
    hit = 1.0 if len(ticker) >= 3 and ticker not in STOP and ticker in text else 0.0
    mkw = meta.get("keywords") or keywords(meta.get("name"), meta.get("symbol"))
    ckw = keywords(cand.get("name"), cand.get("symbol"), cand.get("description") or "")
    name_kw = set(words(meta.get("name")))   # the runner's name only: its ticker already counted in ticker_hit
    shared = sorted(set(mkw) & set(ckw))
    name_overlap = len(name_kw & set(ckw)) / len(name_kw) if name_kw else 0.0
    union = set(mkw) | set(ckw)
    jac = len(set(mkw) & set(ckw)) / len(union) if union else 0.0
    score = min(1.0, 0.6 * hit + 0.4 * name_overlap + 0.2 * jac)
    if hit and ticker not in shared:
        shared = [ticker] + shared
    return round(score, 3), shared


def best_parent(cand, metas):
    """(score, meta, matched) of the meta the candidate copies best; (0, None, []) without metas."""
    best = (0.0, None, [])
    for m in metas:
        s, matched = beta_score(cand, m)
        if s > best[0]:
            best = (s, m, matched)
    return best


def runners(rows, cfg):
    """Pick the active metas from market rows [{token, symbol, name, mcap, liq, ch_h1, ch_h24, price}]: market cap >=
    runner_min_mcap, half of `runners` by 24 h rise and the rest by 1 h rise (no token twice; one ranking short ->
    topped up from the other)."""
    n = int(cfg["runners"])
    ok = [r for r in rows if (r.get("mcap") or 0) >= float(cfg["runner_min_mcap"]) and r.get("price")]
    by24 = sorted((r for r in ok if r.get("ch_h24") is not None), key=lambda r: -float(r["ch_h24"]))
    by1 = sorted((r for r in ok if r.get("ch_h1") is not None), key=lambda r: -float(r["ch_h1"]))
    out, seen = [], set()

    def take(lst, k):
        got = 0
        for r in lst:
            if got >= k or len(out) >= n:
                return
            if r["token"] not in seen:
                seen.add(r["token"])
                out.append(r)
                got += 1
    take(by24, n // 2)
    take(by1, n - len(out))
    take(by24 + by1, n - len(out))
    return out


def store_metas(con, now, picked, descriptions=None):
    descriptions = descriptions or {}
    for r in picked:
        kw = keywords(r.get("name"), r.get("symbol"), descriptions.get(r["token"]) or "")
        con.execute("INSERT OR REPLACE INTO metas VALUES (?,?,?,?,?,?,?,?,?)",
                    (int(now), r["token"], r.get("symbol"), r.get("name"), r.get("ch_h1"), r.get("ch_h24"),
                     r.get("mcap"), r.get("price"), json.dumps(kw)))


def current(con):
    """The newest metas snapshot: [{token, symbol, name, keywords, ts, price}]."""
    row = con.execute("SELECT MAX(ts) FROM metas").fetchone()
    if not row or not row[0]:
        return []
    out = []
    for ts, tok, sym, name, kw, px in con.execute(
            "SELECT ts, token, symbol, name, keywords, price FROM metas WHERE ts=?", (row[0],)):
        try:
            k = json.loads(kw or "{}")
        except ValueError:
            k = {}
        out.append({"ts": ts, "token": tok, "symbol": sym, "name": name, "keywords": k, "price": px})
    return out


def record(con, cand, meta, score, matched, now, via, price, parent_price):
    """One beta row (first sighting wins: the parent and the start prices are not overwritten)."""
    con.execute("INSERT OR IGNORE INTO beta (token, parent, score, found_ts, via, symbol, parent_symbol, matched, p0, "
                "parent_p0) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cand["token"], meta["token"], score, int(now), via, cand.get("symbol"), meta.get("symbol"),
                 ",".join(matched)[:200], price, parent_price))


WINDOWS = (("r1h", "parent_r1h", 3600), ("r4h", "parent_r4h", 4 * 3600), ("r24h", "parent_r24h", 24 * 3600))


def track(con, prices, now):
    """Fill r1h / r4h / r24h of the beta and its parent from the prices of this pass ({token: price}). A window is
    filled by the first pass after it ends; a row is done once 24 h are measured or 26 h have passed (a token with no
    price any more stays unmeasured, not invented)."""
    n = 0
    for tok, parent, found, p0, pp0, r1, r4, r24 in con.execute(
            "SELECT token, parent, found_ts, p0, parent_p0, r1h, r4h, r24h FROM beta WHERE done=0").fetchall():
        have = {"r1h": r1, "r4h": r4, "r24h": r24}
        age = now - found
        sets = {}
        for col, pcol, secs in WINDOWS:
            if have[col] is None and age >= secs:
                px, ppx = prices.get(tok), prices.get(parent)
                if px and p0:
                    sets[col] = round(px / p0 - 1, 4)
                if ppx and pp0:
                    sets[pcol] = round(ppx / pp0 - 1, 4)
        done = age >= 26 * 3600 or (have["r24h"] is not None or "r24h" in sets)
        if sets or done:
            cols = ", ".join(f"{k}=?" for k in sets) + (", " if sets else "") + "done=?"
            con.execute(f"UPDATE beta SET {cols} WHERE token=? AND parent=?", (*sets.values(), int(done), tok, parent))
            n += 1
    return n


def pending_tokens(con):
    """Tokens (betas and their parents) that need a price this pass."""
    out = set()
    for tok, parent in con.execute("SELECT token, parent FROM beta WHERE done=0"):
        out.add(tok)
        out.add(parent)
    return out


def report_rows(con, since):
    """Beta results per window and per parent state: [{window, state, n, mean, hit}] where state is 'raste' (the
    parent was up over the same window) or 'pada' (flat or down); mean = mean result of the beta, hit = share up."""
    out = []
    for col, pcol, _ in WINDOWS:
        groups = {"raste": [], "pada": []}
        for r, pr in con.execute(f"SELECT {col}, {pcol} FROM beta WHERE found_ts >= ? AND {col} IS NOT NULL "
                                 f"AND {pcol} IS NOT NULL", (since,)):
            groups["raste" if pr > 0 else "pada"].append(r)
        for state, vals in groups.items():
            if vals:
                out.append({"window": col[1:], "state": state, "n": len(vals),
                            "mean": round(sum(vals) / len(vals), 4),
                            "hit": round(sum(1 for v in vals if v > 0) / len(vals), 3)})
    return out
