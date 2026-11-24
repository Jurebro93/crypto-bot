"""How a midcap answers BTC's upticks (16.11., vlasnik: "mid capovi od 2, 3 do 200 milijuna ... dosta ovise o kretanju
makrotržišta i Bitcoinu. Bitcoin je čini se pronašao svoje dno ... prema tome treba graditi strategiju").

Pure (no database, no clock). From the token's and BTC's HOURLY closes of the last LOOK_D days, on the hours they share:
  up hours     BTC's hour >= +up_min (0.3 %); down hours: BTC's hour <= -up_min
  hit          the share of the up hours in which the token rose too
  beta_up      the token's summed return over the up hours / BTC's summed return over them (each token hour winsorized
               at +-win, 15 %: one candle is not the answer)
  beta_dn      the same over the down hours (how hard it falls with BTC)
  score        hit x min(max(beta_up, 0), cap) - 0.5 x max(0, beta_dn - beta_up): rises with BTC, often, and does not
               fall harder than it rises
None with fewer than min_up up hours (not enough evidence: such a token keeps its place after the measured ones).
veliki/prioritet stores the row per token (btc_up); veliki/live orders the candidates by score while the macro regime
is "oporavak" (veliki/makro.recovery) and stores the row with the trade, so the report can say whether it predicted.
"""
H = 3600
CFG = {"look_d": 7, "up_min": 0.003, "win": 0.15, "min_up": 8, "cap": 5.0}


def closes(rows):
    """{hour ts: price AT that time} of candle rows [(start ts, o, h, l, close, ...)] (the close is the price at start
    + 1 h) or of point prices [(ts, price)] (BTC hourly: veliki/store.btc_hourly). 16.11.: a candle used to be keyed by
    its start, one hour before its close, so the token's hour was compared with BTC's hour BEFORE it."""
    out = {}
    for r in rows or ():
        candle = len(r) > 4
        c = r[4] if candle else r[1]
        if c and c > 0:
            out[int(r[0]) // H * H + (H if candle else 0)] = float(c)
    return out


def btc_up(tok, btc, now, cfg=None):
    """{"n_up", "n_dn", "hit", "beta_up", "beta_dn", "score"} or None; tok, btc: {hour ts: close}."""
    c = {**CFG, **(cfg or {})}
    t0 = int(now) - int(c["look_d"]) * 86400
    up_t = up_b = dn_t = dn_b = 0.0
    n_up = n_dn = hits = 0
    for t in sorted(tok):
        if t < t0 or t > now or t - H not in tok or t not in btc or t - H not in btc:
            continue
        rb = btc[t] / btc[t - H] - 1
        rt = max(-c["win"], min(c["win"], tok[t] / tok[t - H] - 1))
        if rb >= c["up_min"]:
            n_up += 1
            up_t += rt
            up_b += rb
            hits += 1 if rt > 0 else 0
        elif rb <= -c["up_min"]:
            n_dn += 1
            dn_t += rt
            dn_b += rb
    if n_up < c["min_up"] or up_b <= 0:
        return None
    hit = hits / n_up
    b_up = up_t / up_b
    b_dn = dn_t / dn_b if n_dn >= 3 and dn_b < 0 else None
    sc = hit * min(max(b_up, 0.0), c["cap"]) - (0.5 * max(0.0, b_dn - b_up) if b_dn is not None else 0.0)
    return {"n_up": n_up, "n_dn": n_dn, "hit": round(hit, 2), "beta_up": round(b_up, 2),
            "beta_dn": None if b_dn is None else round(b_dn, 2), "score": round(sc, 2)}


def all_of(con, btc_rows, now, cfg=None):
    """{mint: row} for every member of midcap.db (con) with enough shared hours (c1h + BTC hourly)."""
    c = {**CFG, **(cfg or {})}
    btc = closes(btc_rows)
    if len(btc) < c["min_up"]:
        return {}
    since = int(now) - (int(c["look_d"]) * 86400 + H)
    by = {}
    for tok, ts, cl in con.execute("SELECT token, ts, c FROM c1h WHERE ts >= ? AND token IN (SELECT mint FROM tokens "
                                   "WHERE member=1)", (since,)):
        if cl and cl > 0 and int(ts) // H * H + H <= now:   # completed candles only; keyed by their close time
            by.setdefault(tok, {})[int(ts) // H * H + H] = float(cl)
    out = {}
    for tok, d in by.items():
        r = btc_up(d, btc, now, c)
        if r:
            out[tok] = r
    return out


def order(tokens, prio):
    """The tokens by their BTC-up score (highest first); the unmeasured ones after, in their given order."""
    idx = {t: i for i, t in enumerate(tokens)}

    def key(t):
        s = ((prio or {}).get(t) or {}).get("btc_up") or {}
        return (0, -s["score"], idx[t]) if s.get("score") is not None else (1, 0, idx[t])
    return sorted(tokens, key=key)


def text(r):
    if not r:
        return "odziv na BTC nepoznat"
    return (f"odziv na rast BTC-a {r['beta_up']:+.1f}x u {r['hit']:.0%} sati ({r['n_up']} sati rasta)"
            + (f", u padu {r['beta_dn']:+.1f}x" if r.get("beta_dn") is not None else ""))
