"""The event set: when the price jumped, and why.

Call events (kind 'call'): every token called by a tracked caller (kol.db calls kind 'call': X accounts and Telegram
channels 'tg:<kanal>'; bot accounts and tracked wallets 'w:' out), the FIRST call of each caller per token within
late_call_h of the token's first call, its crew (kol/groupdisc caller groups, early.db group_member), the market cap
at the first call >= min_mcap (unknown: kept). The JUMP: the highest price within jump_h (6 h) after the first call
at least +jump_x (30 %) above the call price: minute.db call_candles (1-minute closes after the call, up to 4 h) and
the call_path entry first, else call_path hi60 (peak within 1 h), else kol.db r1h / r6h (Pretpostavka: the return
at 1 / 6 h is a lower bound of the peak). The window the sellers are looked for: the call .. the peak + 1 h.

Market jumps (kind 'jump', 15.11. extension): every token of the midcap collector (midcap.db 1h candles, 2M-200M and
the smaller tokens it saw) whose CLOSE rose >= mkt_x6 (+50 %) within 6 h or >= mkt_x24 (+100 %) within 24 h of a low
close (closes, not wicks); t0 = the hour of the low, peak = the highest close. A jump within 6 h of a call event of
the same token is that call event (one event, never two).

Catalysts (catalyze): what happened in [t0 - 2 h, t0 + 1 h]: an influencer / Telegram call or a crew (2+ callers of
one crew), an X momentum spike (xfeat.db x_momentum score >= 1, i.e. organic authors doubled), a DexScreener boost /
paid profile / community takeover (midcap.db tokens.src, Pretpostavka: the time the collector first saw it), a CEX /
listing signal (the listing agent's table when it exists), the migration off the pump.fun curve (hype.db
live_launches 'migration'), a buy wave of 3+ owners with >= 1 SOL each in the 6 h before (after chain.py), Grok's
catalyst_check answer (trade.db assistant_notes); else nepoznato. Each with its timestamp; the primary = the earliest.
"""
import json
import zlib
from collections import defaultdict

from insajderi import store
from kol import tgout

# 19.11. (vlasnik: Telegram out of every calculation): the stored call events of a Telegram first caller are skipped
NOT_TG_EVENT = "NOT (kind = 'call' AND COALESCE(handle, '') LIKE 'tg:%')"

CAT_HR = {"poziv_x": "poziv na X-u", "poziv_tg": "Telegram poziv", "ekipa": "ekipa callera", "x_momentum": "X momentum",
          "dex_boost": "DexScreener boost", "dex_profil": "plaćeni DexScreener profil", "cto": "community takeover",
          "listing": "listing / CEX signal", "migracija": "migracija s krivulje", "kitovi_prije": "val kupnji prije",
          "vijest": "vijest (Grok)", "nepoznato": "nepoznato"}


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _in(xs):
    return ",".join("?" * len(xs))


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# ===================================================================================================================
# call events
# ===================================================================================================================
def _crews(early_db):
    """{handle: crew id} of the caller groups (kol/groupdisc group_member kind 'caller')."""
    con = store.ro(early_db)
    out = {m: g for m, g in store.q(con, "SELECT member, gid FROM group_member WHERE kind = 'caller'")}
    if con is not None:
        con.close()
    return out


def _bots(kol_db):
    try:
        from kol import store as kstore
        return set(kstore.bot_handles(kol_db))
    except Exception:  # noqa: BLE001
        return set()


def candle_closes(blob):
    """call_candles.data (zlib JSON [[ts, o, h, l, c, v], ...]) -> [(ts, close)]."""
    try:
        rows = json.loads(zlib.decompress(blob))
    except Exception:  # noqa: BLE001
        try:
            rows = json.loads(blob)
        except Exception:  # noqa: BLE001
            return []
    out = []
    for r in rows or []:
        try:
            out.append((int(r[0]), float(r[4])))
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(out)


def call_jump(t0, entry, closes, hi60, r1h, r6h, c):
    """(peak_ts, peak_x) of the price after the first call, or (None, None) when nothing is known."""
    end = t0 + int(c["jump_h"]) * 3600
    if closes:
        win = [(ts, px) for ts, px in closes if t0 <= ts <= end and px]
        base = entry or (win[0][1] if win else None)
        if win and base:
            ts, px = max(win, key=lambda x: x[1])
            return ts, px / base - 1
    if hi60 is not None:
        return t0 + 3600, float(hi60)
    best = [(t0 + 3600, r1h), (t0 + 6 * 3600, r6h)]
    best = [(ts, x) for ts, x in best if x is not None]
    if best:
        return max(best, key=lambda x: x[1])
    return None, None


def call_events(p, c, now, since=None):
    """[event dict] of the calls since `since` (default: the last `days`) whose price jumped."""
    since = int(since if since is not None else now - int(c["days"]) * 86400)
    kc = store.ro(p.get("kol_db"))
    if kc is None:
        return []
    bots = _bots(p.get("kol_db"))
    crews = _crews(p.get("early_db"))
    # 19.11. (vlasnik, kol/tgout.py): a Telegram channel's call creates no call event any more (X callers only)
    rows = store.q(kc, f"""SELECT token, handle, MIN(ts), mcap0, tweet_id, r1h, r6h, symbol FROM calls WHERE kind = 'call'
        AND handle NOT LIKE 'w:%' AND {tgout.sql()} AND ts >= ? AND ts <= ? GROUP BY token, handle""", (since, now))
    by = defaultdict(list)
    for tok, h, ts, mc0, tid, r1h, r6h, sym in rows:
        if len(tok or "") >= 32 and h and h not in bots and ts:
            by[tok].append((int(ts), h, _f(mc0), tid, _f(r1h), _f(r6h), sym))
    mc = store.ro(p.get("minute_db"))
    out = []
    for ch in _chunks(list(by), 300):
        cand = dict(store.q(mc, f"SELECT token, data FROM call_candles WHERE token IN ({_in(ch)})", ch)) if mc else {}
        tids = [min(by[t])[3] for t in ch if min(by[t])[3]]
        paths = {}
        for tch in _chunks(tids):
            for tid, tok, entry, hi60 in store.q(mc, f"SELECT tweet_id, token, entry, hi60 FROM call_path WHERE tweet_id IN "
                                                     f"({_in(tch)})", tch):
                paths[(tid, tok)] = (_f(entry), _f(hi60))
        for tok in ch:
            calls = sorted(by[tok])
            t0, h0, mc0, tid0, r1h, r6h, sym = calls[0]
            calls = [x for x in calls if x[0] - t0 <= int(c["late_call_h"]) * 3600]
            if mc0 is not None and mc0 < c["min_mcap"]:
                continue
            entry, hi60 = paths.get((tid0, tok), (None, None))
            closes = candle_closes(cand[tok]) if tok in cand else []
            pk_ts, pk_x = call_jump(t0, entry, closes, hi60, r1h, r6h, c)
            if pk_x is None or pk_x < c["jump_x"]:
                continue
            callers = {h: ts for ts, h, *_r in calls}
            cr = sorted({crews[h] for h in callers if h in crews})
            prio = min(pk_x, 10.0) + 0.5 * len(callers) + (1.0 if (mc0 or 0) >= 1e6 else 0.0)
            out.append({"eid": f"c:{tok}:{t0}", "kind": "call", "token": tok, "symbol": sym, "t0": t0, "handle": h0,
                        "crew": ",".join(cr) or None, "n_callers": len(callers), "callers": callers, "mcap0": mc0,
                        "peak_ts": int(pk_ts), "peak_x": round(pk_x, 4),
                        "win_end": int(pk_ts) + int(c["after_peak_s"]), "src": "calls", "prio": round(prio, 3)})
    for x in (kc, mc):
        if x is not None:
            x.close()
    return out


# ===================================================================================================================
# market jumps
# ===================================================================================================================
def find_jumps(closes, x6, x24, wa=6 * 3600, wb=24 * 3600, names=("6h", "24h")):
    """closes [(ts, close)] sorted -> [(t0, base, peak_ts, peak, kind)]: the first close that is >= base x (1 + x6)
    within 6 h (or x (1 + x24) within 24 h) of the lowest close before it; then the scan goes on after the peak.
    19.11. navečer: the windows wa / wb (seconds) and their names are parameters (daily closes: 1 day / 3 days)."""
    out, i, n = [], 0, len(closes)
    while i < n:
        t_i, p_i = closes[i]
        if not p_i or p_i <= 0:
            i += 1
            continue
        hit = None
        for k in range(i + 1, n):
            t_k, p_k = closes[k]
            dt = t_k - t_i
            if dt > wb:
                break
            if p_k and ((dt <= wa and p_k >= p_i * (1 + x6)) or p_k >= p_i * (1 + x24)):
                hit = k
                break
            if p_k and p_k < p_i:   # a lower base: start from it
                break
        if hit is None:
            i += 1
            continue
        kind = names[0] if closes[hit][0] - t_i <= wa and closes[hit][1] >= p_i * (1 + x6) else names[1]
        # the jump starts where the price last sat at its base (within +5 %) before the rise
        s = max(m for m in range(i, hit) if closes[m][1] and closes[m][1] <= p_i * 1.05)
        t_s, p_s = closes[s]
        end = t_s + (wa if kind == names[0] else wb)
        j = max((m for m in range(hit, n) if closes[m][0] <= end), key=lambda m: closes[m][1])
        out.append((t_s, min(p_i, p_s), closes[j][0], closes[j][1], kind))
        i = j + 1
    return out


TIER_RANK = {"pumpa15": 0, "pumpa2": 1}
TIER_HR = {"pumpa15": "pumpa do ≥ 15M", "pumpa2": "pumpa do 2-15M"}


def tier_of(peak_mc, c):
    """19.11.: the pump tier of a market jump by its PEAK market cap: "pumpa15" (>= focus_mcap, 15M), "pumpa2"
    (>= pump2_mcap, 2M), else None."""
    if peak_mc is None:
        return None
    if peak_mc >= float(c["focus_mcap"]):
        return "pumpa15"
    if peak_mc >= float(c["pump2_mcap"]):
        return "pumpa2"
    return None


def _peak_tokens(con, c, since):
    """19.11.: [(mint, symbol, mcap)] of the collector's tokens whose highest 1h close since `since` puts them at a peak
    MC >= pump2_mcap (mcap now x max close / last close), whatever their 24 h volume: max_mkt_tokens never cuts a
    token that pumped into the tiers off."""
    return store.q(con, """SELECT t.mint, t.symbol, t.mcap FROM tokens t WHERE t.mcap IS NOT NULL AND
        t.mcap * (SELECT MAX(c) FROM c1h WHERE token = t.mint AND ts >= ?) /
        NULLIF((SELECT c FROM c1h WHERE token = t.mint AND ts >= ? ORDER BY ts DESC LIMIT 1), 0) >= ?""",
                   (since, since, float(c["pump2_mcap"])))


def market_events(p, c, now, since=None):
    """[event dict] of the market jumps of midcap.db tokens (1h closes) since `since` (default mkt_days). Each carries
    peak_mc (the MC at the peak close: today's MC x peak close / last close, = mcap0 x (1 + peak_x)) and its tier."""
    since = int(since if since is not None else now - int(c["mkt_days"]) * 86400)
    con = store.ro(p.get("midcap_db"))
    if con is None:
        return []
    toks = store.q(con, "SELECT mint, symbol, mcap FROM tokens WHERE mcap IS NOT NULL ORDER BY vol24 DESC LIMIT ?",
                   (int(c["max_mkt_tokens"]),))
    have = {t[0] for t in toks}
    toks += [t for t in _peak_tokens(con, c, since) if t[0] not in have]
    out = []
    for mint, sym, mcap in toks:
        closes = [(int(ts), float(cl)) for ts, cl in store.q(con, "SELECT ts, c FROM c1h WHERE token = ? AND ts >= ? "
                                                                   "ORDER BY ts", (mint, since)) if cl]
        if len(closes) < 3:
            continue
        last = closes[-1][1]
        for t0, base, pk_ts, pk, kind in find_jumps(closes, float(c["mkt_x6"]), float(c["mkt_x24"])):
            mc0 = (mcap * base / last) if mcap and last else None
            if mc0 is not None and mc0 < c["min_mcap"]:
                continue
            x = pk / base - 1
            peak_mc = (mcap * pk / last) if mcap and last else None
            out.append({"eid": f"j:{mint}:{t0}", "kind": "jump", "token": mint, "symbol": sym, "t0": t0, "handle": None,
                        "crew": None, "n_callers": 0, "callers": {}, "mcap0": mc0, "peak_ts": pk_ts,
                        "peak_x": round(x, 4), "win_end": pk_ts + int(c["after_peak_s"]), "src": f"midcap {kind}",
                        "prio": round(min(x, 10.0) + (1.0 if (mc0 or 0) >= 5e6 else 0.0), 3),
                        "peak_mc": peak_mc, "tier": tier_of(peak_mc, c)})
    con.close()
    return out


def res_of(e):
    """The resolution of an event's t0: "1d" for a pump from daily candles (src "c1d ..."), else "1h"."""
    return "1d" if str(e.get("src") or "").startswith("c1d") else "1h"


def _daily_sources(p):
    """[(label, con)] of the databases with daily candles: midcap.db c1d (the collector's 2M-200M members, GeckoTerminal
    1d) and veliki.db c1d (the veliki list and the tokens that fell out of it, up to 180 days). Read-only."""
    out = []
    for label, path in (("midcap", p.get("midcap_db")), ("veliki", p.get("veliki_db"))):
        con = store.ro(path)
        if con is not None:
            out.append((label, con))
    return out


def daily_events(p, c, now, avoid=None):
    """19.11. navečer: [event dict] of the pumps in the DAILY closes of the last pump_days_1d (180) days: a close >=
    +mkt_x1d (50 %) above a low close within one day, or >= +mkt_x3d (100 %) within 3 days (find_jumps on days). t0 =
    the start of the low day, the peak = the end of the peak day, win_end = that + after_peak_s; eid "d:<mint>:<t0>",
    src "c1d 1d" / "c1d 3d" (res_of). The peak MC and the tier are ESTIMATES like tier_of's (today's MC x the peak close
    / the last close: the supply is taken as today's). avoid: {token: [(t0, win_end)]} of the 1h / call events (new and
    stored): a daily pump whose window contains one of their t0 is the same pump and is dropped (the 1h one wins: a
    better t0). Tokens: midcap.db first (its MC), then veliki.db tokens / hist not in it."""
    since = int(now) - int(c["pump_days_1d"]) * 86400
    avoid = avoid or {}
    out, seen = [], set()
    for label, con in _daily_sources(p):
        try:
            if label == "midcap":
                toks = store.q(con, "SELECT mint, symbol, mcap FROM tokens WHERE mcap IS NOT NULL")
            else:
                toks = store.q(con, "SELECT mint, symbol, mcap FROM tokens WHERE mcap IS NOT NULL UNION SELECT mint, "
                                    "symbol, mcap FROM hist WHERE mcap IS NOT NULL")
            for mint, sym, mcap in toks:
                if mint in seen:
                    continue
                closes = [(int(ts), float(cl)) for ts, cl in store.q(con, "SELECT ts, c FROM c1d WHERE token = ? AND "
                                                                           "ts >= ? ORDER BY ts", (mint, since)) if cl]
                if len(closes) < 3:
                    continue
                seen.add(mint)
                last = closes[-1][1]
                for t0, base, pk_ts, pk, kind in find_jumps(closes, float(c["mkt_x1d"]), float(c["mkt_x3d"]),
                                                            86400, 3 * 86400, ("1d", "3d")):
                    mc0 = (mcap * base / last) if mcap and last else None
                    if mc0 is not None and mc0 < c["min_mcap"]:
                        continue
                    pk_end = pk_ts + 86400
                    win_end = pk_end + int(c["after_peak_s"])
                    if any(t0 <= t <= win_end for t, _we in avoid.get(mint, ())):
                        continue
                    x = pk / base - 1
                    peak_mc = (mcap * pk / last) if mcap and last else None
                    out.append({"eid": f"d:{mint}:{t0}", "kind": "jump", "token": mint, "symbol": sym, "t0": t0,
                                "handle": None, "crew": None, "n_callers": 0, "callers": {}, "mcap0": mc0,
                                "peak_ts": pk_end, "peak_x": round(x, 4), "win_end": win_end, "src": f"c1d {kind}",
                                "prio": round(min(x, 10.0) + (1.0 if (mc0 or 0) >= 5e6 else 0.0), 3),
                                "peak_mc": peak_mc, "tier": tier_of(peak_mc, c)})
        finally:
            con.close()
    return out


def avoid_map(events):
    """{token: [(t0, win_end)]} of events (the 1h jumps and the call events) for daily_events' dedup."""
    out = defaultdict(list)
    for e in events:
        if res_of(e) == "1h":
            out[e["token"]].append((int(e["t0"]), int(e["win_end"])))
    return out


def load_horizon(con, c, now):
    """19.11. navečer: the events a pass works on: the call / untiered events of the last `days` and every TIERED
    (pump) event of the last pump_days (180), oldest first."""
    since = int(now) - int(c["days"]) * 86400
    since_p = int(now) - int(c.get("pump_days") or c["days"]) * 86400
    return [e for e in load(con, min(since, since_p)) if e["t0"] >= since or (e.get("tier") and e["t0"] >= since_p)]


def merge(calls, jumps):
    """Calls first; a market jump within 6 h of a call event of the same token is dropped (the call event stands).
    19.11.: the call event takes the dropped jump's pump tier and peak MC (a pump stays a pump, before the call too)."""
    at = defaultdict(list)
    for e in calls:
        at[e["token"]].append(e)
    out = list(calls)
    for e in jumps:
        near = [x for x in at[e["token"]] if abs(e["t0"] - x["t0"]) <= 6 * 3600]
        if near:
            if e.get("tier"):
                for x in near:
                    if TIER_RANK.get(e["tier"], 9) < TIER_RANK.get(x.get("tier"), 9):
                        x["tier"], x["peak_mc"] = e["tier"], e.get("peak_mc")
            continue
        out.append(e)
    return out


def save(con, events, now):
    """Upsert the events (a stored event keeps its fetch state and catalysts). Returns how many are new."""
    n = 0
    for e in events:
        cur = con.execute("SELECT 1 FROM i2_events WHERE eid = ?", (e["eid"],)).fetchone()
        if cur:
            con.execute("""UPDATE i2_events SET n_callers = ?, callers = ?, crew = ?, peak_ts = ?, peak_x = ?, win_end = ?,
                prio = ?, symbol = COALESCE(symbol, ?), tier = COALESCE(?, tier), peak_mc = COALESCE(?, peak_mc)
                WHERE eid = ?""",
                        (e["n_callers"], json.dumps(e["callers"]), e["crew"], e["peak_ts"], e["peak_x"], e["win_end"],
                         e["prio"], e["symbol"], e.get("tier"), e.get("peak_mc"), e["eid"]))
            continue
        con.execute("""INSERT INTO i2_events (eid, kind, token, symbol, t0, handle, crew, n_callers, callers, mcap0, peak_ts,
            peak_x, win_end, src, prio, built_ts, tier, peak_mc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (e["eid"], e["kind"], e["token"], e["symbol"], e["t0"], e["handle"], e["crew"], e["n_callers"],
                     json.dumps(e["callers"]), e["mcap0"], e["peak_ts"], e["peak_x"], e["win_end"], e["src"], e["prio"],
                     int(now), e.get("tier"), e.get("peak_mc")))
        n += 1
    con.commit()
    return n


def mark_tiers(con, c):
    """19.11.: tier / peak_mc of the stored MARKET jumps from what is stored (mcap0 x (1 + peak_x): the same number
    market_events computes), so the events of an existing insajderi.db get their tier on the first pass after the
    migration. A call event keeps the tier it took from a merged jump (merge). -> {tier: n}."""
    rows = store.q(con, "SELECT eid, mcap0, peak_x FROM i2_events WHERE kind = 'jump'")
    upd = []
    for eid, mc0, px in rows:
        pk = mc0 * (1 + px) if mc0 is not None and px is not None else None
        upd.append((tier_of(pk, c), pk, eid))
    con.executemany("UPDATE i2_events SET tier = ?, peak_mc = ? WHERE eid = ?", upd)
    con.commit()
    out = defaultdict(int)
    for (t, n) in store.q(con, "SELECT tier, COUNT(*) FROM i2_events WHERE tier IS NOT NULL GROUP BY tier"):
        out[t] = n
    return dict(out)


def load(con, since=None, kind=None):
    """[event dict] stored, oldest first (19.11.: with tier and peak_mc). 19.11. (vlasnik, kol/tgout.py): a stored call
    event whose first caller is a Telegram channel stays in i2_events but is not loaded (NOT_TG_EVENT), and the
    Telegram callers of the other call events are left out of `callers`."""
    sql = ("SELECT eid, kind, token, symbol, t0, handle, crew, n_callers, callers, mcap0, peak_ts, peak_x, win_end, "
           f"catalyst, catalysts, src, prio, fetched, n_part, tier, peak_mc FROM i2_events WHERE t0 >= ? AND {NOT_TG_EVENT}")
    args = [int(since or 0)]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    keys = ("eid", "kind", "token", "symbol", "t0", "handle", "crew", "n_callers", "callers", "mcap0", "peak_ts",
            "peak_x", "win_end", "catalyst", "catalysts", "src", "prio", "fetched", "n_part", "tier", "peak_mc")
    out = []
    for r in store.q(con, sql + " ORDER BY t0", args):
        d = dict(zip(keys, r))
        for k in ("callers", "catalysts"):
            try:
                d[k] = json.loads(d[k]) if d[k] else ({} if k == "callers" else [])
            except ValueError:
                d[k] = {} if k == "callers" else []
        if isinstance(d["callers"], dict):
            d["callers"] = {h: ts for h, ts in d["callers"].items() if not tgout.is_tg(h)}
        out.append(d)
    return out


# ===================================================================================================================
# catalysts
# ===================================================================================================================
def _listing_rows(listing_db, toks):
    """[(token, ts, what)] from the listing agent's tables when they exist (any table with 'listing' in its name and a
    token / mint column and a ts column); [] otherwise. Read-only, never raises."""
    con = store.ro(listing_db)
    if con is None:
        return []
    out = []
    for (name,) in store.q(con, "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%listing%'"):
        cols = [r[1] for r in store.q(con, f"PRAGMA table_info({name})")]
        tc = "mint" if "mint" in cols else "token" if "token" in cols else None
        sc = "ts" if "ts" in cols else "detected_ts" if "detected_ts" in cols else None
        if not tc or not sc:
            continue
        what = "exchange" if "exchange" in cols else "kind" if "kind" in cols else None
        for ch in _chunks(toks):
            sel = f"{tc}, {sc}" + (f", {what}" if what else ", NULL")
            out += [(t, int(ts), w) for t, ts, w in store.q(con, f"SELECT {sel} FROM {name} WHERE {tc} IN ({_in(ch)})", ch)
                    if ts]
    con.close()
    return out


def _grok_answers(trade_db, toks):
    """{token: [(ts, text)]} of Grok's catalyst_check answers (submit_signal_opinion with evidence source
    catalyst_check)."""
    con = store.ro(trade_db)
    out = defaultdict(list)
    for ch in _chunks(toks):
        for tok, ts, txt in store.q(con, f"SELECT token, ts, interpretation FROM assistant_notes WHERE kind = "
                                         f"'signal_opinion' AND evidence LIKE '%catalyst_check%' AND token IN ({_in(ch)})",
                                    ch):
            out[tok].append((int(ts), (txt or "")[:240]))
    if con is not None:
        con.close()
    return out


def catalyze(con, p, events, waves=None):
    """Store the catalysts of `events` ([(name, ts, detail)], primary = the earliest). waves: {eid: (ts, n owners,
    SOL)} of the buy waves before t0 (chain.waves). Returns {catalyst: n}."""
    if not events:
        return {}
    toks = sorted({e["token"] for e in events})
    crews = _crews(p.get("early_db"))
    calls, xm, src, mig = defaultdict(list), defaultdict(list), {}, defaultdict(list)
    kc = store.ro(p.get("kol_db"))
    xc = store.ro(p.get("xfeat_db"))
    mc = store.ro(p.get("midcap_db"))
    hc = store.ro(p.get("hype_db"))
    for ch in _chunks(toks):
        for tok, h, ts in store.q(kc, f"SELECT token, handle, ts FROM calls WHERE kind = 'call' AND handle NOT LIKE 'w:%' "
                                      f"AND {tgout.sql()} AND token IN ({_in(ch)})", ch):
            if ts:
                calls[tok].append((int(ts), h))
        for tok, ts, sc in store.q(xc, f"SELECT token, ts, score FROM x_momentum WHERE score >= 1 AND token IN "
                                       f"({_in(ch)})", ch):
            xm[tok].append((int(ts), round(float(sc), 2)))
        for tok, s, fts in store.q(mc, f"SELECT mint, src, first_ts FROM tokens WHERE mint IN ({_in(ch)})", ch):
            try:
                src[tok] = (json.loads(s or "{}") or {}, fts)
            except ValueError:
                pass
        for tok, ts in store.q(hc, f"SELECT mint, ts FROM live_launches WHERE pool = 'migration' AND mint IN ({_in(ch)})",
                               ch):
            mig[tok].append(int(ts))
    for x in (kc, xc, mc, hc):
        if x is not None:
            x.close()
    lst = defaultdict(list)
    for tok, ts, w in _listing_rows(p.get("listing_db"), toks):
        lst[tok].append((ts, w))
    grok = _grok_answers(p.get("trade_db"), toks)
    counts = defaultdict(int)
    for e in events:
        tok, t0 = e["token"], e["t0"]
        lo, hi = t0 - 2 * 3600, t0 + 3600
        cats = []
        near = sorted((ts, h) for ts, h in calls[tok] if lo <= ts <= hi)
        for ts, h in near[:3]:
            cats.append(("poziv_tg" if str(h).startswith("tg:") else "poziv_x", ts, h))
        cr = defaultdict(set)
        for ts, h in near:
            if h in crews:
                cr[crews[h]].add(h)
        for g, hs in cr.items():
            if len(hs) >= 2:
                cats.append(("ekipa", min(ts for ts, h in near if h in hs), f"{g}: {', '.join(sorted(hs)[:4])}"))
        for ts, sc in sorted(xm[tok]):
            if lo <= ts <= hi:
                cats.append(("x_momentum", ts, f"ocjena {sc}"))
                break
        s, fts = src.get(tok, ({}, None))
        if fts and t0 - 6 * 3600 <= fts <= hi:
            for key, name in (("dex_boost_top", "dex_boost"), ("dex_boost", "dex_boost"), ("dex_profile", "dex_profil"),
                              ("dex_cto", "cto")):
                if key in s:
                    cats.append((name, int(fts), key))
                    break
        for ts, w in lst[tok]:
            if t0 - 24 * 3600 <= ts <= hi:
                cats.append(("listing", ts, w or "listing"))
        for ts in mig[tok]:
            if lo <= ts <= hi:
                cats.append(("migracija", ts, "pump.fun -> PumpSwap/Raydium"))
        wv = (waves or {}).get(e["eid"])
        if wv:
            cats.append(("kitovi_prije", wv[0], f"{wv[1]} vlasnika, {wv[2]:.1f} SOL"))
        for ts, txt in grok.get(tok, []):
            if ts >= t0:
                cats.append(("vijest", ts, txt))
                break
        cats.sort(key=lambda x: x[1])
        prim = cats[0][0] if cats else "nepoznato"
        counts[prim] += 1
        con.execute("UPDATE i2_events SET catalyst = ?, catalysts = ? WHERE eid = ?",
                    (prim, json.dumps([list(x) for x in cats][:12], ensure_ascii=False), e["eid"]))
    con.commit()
    return dict(counts)
