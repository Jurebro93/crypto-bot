"""Kopirljivost svakog novčanika i influencera (27.11.2026, vlasnik: "Izmjeri kopirljivost svakog walleta i
influencera s kašnjenjem 5, 30 i 120 s i stvarnim troškom").

wallets/kopija.py replays the copier over the wallets a RULE picks (the account's view); wallets/rang.py estimates the
lag with one assumed number. This module asks the per-source question: had we copied THIS source, every one of its
signals, `delay` seconds late, at the prices we stored, after the real cost, would it have paid? Local databases only
(read-only), no network, no paid call; the result goes into its own kopirljivost.db.

Sources (the window: the last MAX_DAYS)
  novčanik   wallets.db wallet_trades of every scored wallet (wallets.scored_at set), plus hype.db chain_trades (the
             Helius wallet webhook) of the wallets that have no wallets.db trades, plus insajderi.db i2_trades of the
             tracked insider wallets (i2_smart). One position = his first buy while he holds none (kopija.episodes;
             chain_trades carries no token amount, so there: a buy opens, his first sale closes)
  influencer kol.db calls kind 'call' (no Telegram: kol/tgout), the FIRST call of each (account, token)
The copier (pre-declared, the same for every source)
  entry      the first stored price point at or after signal + delay (5 / 30 / 120 s), at most ENTRY_TOL_S later;
             kopija.Prices: real swap prints to the second first, then 1-min candles (call_candles: open, close) and
             pool snapshots. No point = a MISSED trade (counted, never dropped silently; also a price that cannot be
             real, kopija.price_flag, or an exit without a price)
  exit       a wallet: his first sale + the same delay (kopija.simulate rule "on"); still held at the end of the data:
             marked at the last point, unless the buy is younger than YOUNG_S (then "još otvoreno", not counted).
             A call: the "podaci" follow's default exit (league/copy DATA_TP / DEFAULT_SL / DATA_HOLD_S): +15 % target
             (filled AT the target), -20 % stop (filled at the point that crossed it), else out 1 h after entry
  cost       trade/cost.round_trip(0.1 SOL in USD, the pool's liquidity at our entry): the fee a side calibrated on our
             own measured swaps (trade.db) + the price impact of our size in that pool, never under RT_FLOOR (3 %)
  30k        a trade whose entry market cap is known to be under 30k $ is counted apart and in no number (the owner's
             rule for every automatic buy)
Numbers per (source, delay): signals, missed, under 30k, priced n, median / mean net return, share in plus, the 90 %
interval of the mean (kopija.boot_ci: the cluster bootstrap over token x day), the mean of the NEWER third of the
priced trades. Verdict: "kopirljivo" = at least MIN_N priced, at most half missed, the interval's low end above zero,
the median above zero and the newer third in the plus (it has to hold on later days too); "premalo podataka" below
those counts; else "nije kopirljivo". Nothing here selects sources for trading and no real-money path reads it.

Heavy (every stored price of every source's tokens): run_wallets.py kopirljivost --night, 01-06 Zagreb, once a day,
bounded by BUDGET_S; a cut pass is a fixed pseudo-random sample of tokens and says "djelomično".
"""
import bisect
import json
import os
import sqlite3
import statistics
import time
import zlib

from wallets import kopija

PREFIX = "kopirljivost: "
D, H = 86400, 3600
DELAYS = (5, 30, 120)
MAX_DAYS = 60
ENTRY_TOL_S = 60            # the price point may be at most this much later than signal + delay (one 1-min candle)
YOUNG_S = 24 * H            # an unsold buy younger than this at the end of the data is not judged yet
MIN_N = 20
MAX_MISSED = 0.5
CALL_TP, CALL_SL, CALL_HOLD_S = 0.15, 0.20, 3600   # league/copy DATA_TP 15 %, DEFAULT_SL -20 %, DATA_HOLD_S
EXIT_GAP_S = kopija.EXIT_GAP_S
SIZE_SOL = kopija.SIZE_SOL
RT_FLOOR = kopija.RT_FLOOR
MIN_MC = kopija.MIN_MC
BUDGET_S = int(os.environ.get("KOPIRLJIVOST_BUDGET_S", "1800"))
B = 500
VERDICT_HR = {"kopirljivo": "kopirljivo", "nije": "nije kopirljivo", "malo": "premalo podataka"}
DELAY_HR = {5: "5 s", 30: "30 s", 120: "2 min"}

SCHEMA = """CREATE TABLE IF NOT EXISTS kopirljivost (
    kind TEXT, source TEXT, delay INTEGER, n_sig INTEGER, n_missed INTEGER, n_under INTEGER, n_open INTEGER,
    n INTEGER, med REAL, mean REAL, win REAL, ci_lo REAL, ci_hi REAL, newer_mean REAL, cost_med REAL, lag_med REAL,
    verdict TEXT, updated INTEGER, PRIMARY KEY (kind, source, delay));
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);"""


def db_path():
    """kopirljivost.db on the persistent disk (DATA_DIR), else next to wallets.db."""
    if os.environ.get("KOPIRLJIVOST_DB"):
        return os.environ["KOPIRLJIVOST_DB"]
    data = os.environ.get("DATA_DIR")
    if data and os.path.isdir(data):
        return os.path.join(data, "kopirljivost.db")
    from wallets import store as wstore
    return os.path.join(os.path.dirname(os.path.abspath(wstore.DB)), "kopirljivost.db")


def connect(path=None):
    con = sqlite3.connect(path or db_path(), timeout=30)
    con.executescript(SCHEMA)
    return con


# ---------- the signals -----------------------------------------------------------------------------------------------

def _ep(mint, t0, sell_ts=None, px0=None, sell_px=None):
    return {"mint": mint, "t0": int(t0), "px0": px0, "sell_ts": sell_ts, "sell_px": sell_px, "ret": None, "sol0": None}


def simple_episodes(rows):
    """[(ts, mint, side)] oldest first, no token amounts (hype.db chain_trades) -> positions: a buy opens one while
    none is open on that token, his first sale after it closes it."""
    out, cur = [], {}
    for ts, m, side in rows:
        if side == "buy" and m not in cur:
            cur[m] = _ep(m, ts)
            out.append(cur[m])
        elif side == "sell" and m in cur:
            cur.pop(m)["sell_ts"] = int(ts)
    return out


def wallet_signals(p, lo, hi):
    """{wallet: [position]} of every tracked wallet inside [lo, hi] (see the module text)."""
    out = {}
    con = kopija._ro(p.get("wallets"))
    if con is not None:
        try:
            scored = [r[0] for r in kopija._q(con, "SELECT wallet FROM wallets WHERE scored_at IS NOT NULL")]
            for w in scored:
                tr = kopija.trades_of(con, w, lo - 30 * D, hi + 1)
                eps = [e for e in kopija.episodes(tr) if lo <= e["t0"] <= hi and e["sol0"] >= kopija.MIN_SOL]
                if eps:
                    out[w] = eps
        finally:
            con.close()
    con = kopija._ro(p.get("hype"))
    if con is not None:
        try:
            by = {}
            for w, ts, m, side, sol in kopija._q(
                    con, "SELECT wallet, ts, mint, side, sol FROM chain_trades WHERE ts BETWEEN ? AND ? ORDER BY ts",
                    (lo, hi)):
                if w in out or (side == "buy" and (sol or 0) < kopija.MIN_SOL):
                    continue
                by.setdefault(w, []).append((ts, m, side))
            for w, rows in by.items():
                eps = simple_episodes(rows)
                if eps:
                    out[w] = eps
        finally:
            con.close()
    con = kopija._ro(p.get("insajderi"))
    if con is not None:
        try:
            for (w,) in kopija._q(con, "SELECT wallet FROM i2_smart"):
                if w in out:
                    continue
                rows = kopija._q(con, "SELECT ts, mint, side, sol, tokens FROM i2_trades WHERE wallet = ? AND ts BETWEEN "
                                      "? AND ? ORDER BY ts", (w, lo - 30 * D, hi))
                tr = [{"ts": ts, "mint": m, "kind": side, "tokens": (tok or 0) * (1 if side == "buy" else -1),
                       "sol": (sol or 0) * (-1 if side == "buy" else 1)} for ts, m, side, sol, tok in rows]
                eps = [e for e in kopija.episodes(tr) if lo <= e["t0"] <= hi and e["sol0"] >= kopija.MIN_SOL]
                if eps:
                    out[w] = eps
        finally:
            con.close()
    return out


def call_signals(p, lo, hi):
    """{handle: [(token, ts)]}: the first call of each (account, token) inside [lo, hi], no Telegram."""
    from kol import tgout
    con = kopija._ro(p.get("kol"))
    if con is None:
        return {}
    try:
        rows = kopija._q(con, "SELECT handle, token, MIN(ts) FROM calls WHERE kind = 'call' AND ts BETWEEN ? AND ? "
                              f"AND token IS NOT NULL AND {tgout.sql('handle')} GROUP BY handle, token", (lo, hi))
    finally:
        con.close()
    out = {}
    for h, tok, ts in rows:
        if h and not h.startswith("w:"):
            out.setdefault(h, []).append((tok, int(ts)))
    return out


# ---------- one copied call --------------------------------------------------------------------------------------------

def simulate_call(t0, delay, ser, hi, tp=CALL_TP, sl=CALL_SL, hold=CALL_HOLD_S, tol=ENTRY_TOL_S):
    """The copier of one call on one series, before cost: None = no price near our entry; else {"ts", "e_px", "x_px"
    (None = no exit price), "why" ("tp" / "stop" / "vrijeme"), "lag", "_i", "_j"}; "young" when the hour is not over
    by the end of the data."""
    et = t0 + delay
    i = ser.first_from(et, tol)
    if i is None:
        return None
    ts, px = ser.ts, ser.px
    e = px[i]
    out = {"ts": et, "e_px": e, "lag": ts[i] - t0, "x_px": None, "why": None, "_i": i, "_j": None, "young": False,
           "src": ser.src[i]}
    end = et + hold
    if end > hi:
        out["young"] = True
        return out
    for j in range(i + 1, len(ts)):
        if ts[j] > end:
            break
        if px[j] <= e * (1 - sl):
            out.update(x_px=px[j], why="stop", _j=j)
            return out
        if px[j] >= e * (1 + tp):
            out.update(x_px=e * (1 + tp), why="tp", _j=j)
            return out
    j = ser.first_from(end, EXIT_GAP_S)
    if j is None or j <= i:   # nobody traded right after the hour: the last point before it, if it is that recent
        k = bisect.bisect_right(ts, end) - 1
        j = k if k > i and end - ts[k] <= EXIT_GAP_S else None
    if j is not None:
        out.update(x_px=px[j], why="vrijeme", _j=j)
    return out


def call_trade(mint, t0, delay, tok, sol_usd, hi, fee=None, size=SIZE_SOL, floor=RT_FLOOR):
    """One call as copied: {"token", "ts", "ret" (None = missed), "missed", "under", "young", "cost", "lag"}."""
    from trade import cost
    best = None
    for kind in ("sol", "usd"):
        s = simulate_call(t0, delay, tok[kind], hi)
        if s is None:
            continue
        s["kind"] = kind
        if best is None or (best["x_px"] is None and s["x_px"] is not None):
            best = s
        if s["x_px"] is not None or s["young"]:
            break
    if best is None:
        return {"token": mint, "ts": t0 + delay, "ret": None, "missed": True}
    if best["young"]:
        return {"token": mint, "ts": best["ts"], "ret": None, "young": True}
    ser = tok[best["kind"]]
    liq, mc, _sup = kopija.entry_liq_mc(mint, best["kind"], best["e_px"], best["ts"], tok, sol_usd)
    rt = max(floor, cost.round_trip(size * sol_usd, liq, fee))
    t = {"token": mint, "ts": best["ts"], "cost": rt, "lag": best["lag"], "mc": mc, "ret": None}
    bad = any(k is not None and kopija.isolated(ser.px, k) for k in (best["_i"], best["_j"]))
    if mc is not None and mc < MIN_MC:
        t["under"] = True
    elif best["x_px"] is None or bad:
        t["missed"] = True
    else:
        t["ret"] = best["x_px"] / best["e_px"] - 1 - rt
    return t


def wallet_trade(w, ep, delay, tok, sol_usd, hi, fee=None):
    """One wallet position as copied, the same shape as call_trade (kopija.copy_trade, his exit: rule "on")."""
    t = kopija.copy_trade(w, ep, delay, "on", tok, sol_usd, fee, SIZE_SOL, RT_FLOOR, hi, gap=ENTRY_TOL_S)
    if t is None:
        return {"token": ep["mint"], "ts": ep["t0"] + delay, "ret": None, "missed": True}
    if t["open"] and hi - ep["t0"] < YOUNG_S:
        return {"token": ep["mint"], "ts": t["ts"], "ret": None, "young": True}
    out = {"token": ep["mint"], "ts": t["ts"], "cost": t["cost"], "lag": t["lag"], "mc": t["mc"], "ret": None}
    if t["mc"] is not None and t["mc"] < MIN_MC:
        out["under"] = True
    elif t["ret"] is None:
        out["missed"] = True
    else:
        out["ret"] = t["ret"]
    return out


# ---------- the numbers ------------------------------------------------------------------------------------------------

def stats(trs, min_n=MIN_N, b=B):
    """One (source, delay): the counts, the numbers and the verdict (see the module text). Returns in fractions."""
    young = sum(1 for t in trs if t.get("young"))
    under = sum(1 for t in trs if t.get("under"))
    missed = sum(1 for t in trs if t.get("missed"))
    ok = sorted((t for t in trs if t.get("ret") is not None), key=lambda t: t["ts"])
    n_sig = len(trs) - young - under
    r = [t["ret"] for t in ok]
    s = {"n_sig": n_sig, "n_missed": missed, "n_under": under, "n_open": young, "n": len(ok),
         "med": statistics.median(r) if r else None, "mean": statistics.fmean(r) if r else None,
         "win": sum(1 for x in r if x > 0) / len(r) if r else None, "ci_lo": None, "ci_hi": None, "newer_mean": None,
         "cost_med": statistics.median(t["cost"] for t in ok) if ok else None,
         "lag_med": statistics.median(t["lag"] for t in ok) if ok else None}
    if len(ok) >= 3:
        new = r[len(r) - max(1, len(r) // 3):]
        s["newer_mean"] = statistics.fmean(new)
        ci = kopija.boot_ci(ok, b=b)
        if ci:
            s["ci_lo"], s["ci_hi"] = ci[0] / 100, ci[1] / 100
    if len(ok) < min_n or (n_sig and missed / n_sig > MAX_MISSED):
        s["verdict"] = "malo"
    elif (s["ci_lo"] is not None and s["ci_lo"] > 0 and s["med"] > 0 and (s["newer_mean"] or 0) > 0):
        s["verdict"] = "kopirljivo"
    else:
        s["verdict"] = "nije"
    return s


def headline(by_delay):
    """{delay: verdict} -> one plain sentence for the page."""
    v = {d: by_delay.get(d) for d in DELAYS}
    good = [d for d in DELAYS if v[d] == "kopirljivo"]
    if good == list(DELAYS):
        return "Kopirljivo, i uz kašnjenje od 2 minute"
    if good == [5, 30]:
        return "Kopirljivo ako kopiramo unutar 30 sekundi"
    if good == [5]:
        return "Kopirljivo samo uz vrlo brzo kopiranje"
    if good:
        return "Kopirljivo uz neka kašnjenja: " + ", ".join(DELAY_HR[d] for d in good)
    if any(v[d] == "nije" for d in DELAYS):
        return "Nije kopirljivo"
    return "Premalo podataka"


# ---------- the pass ---------------------------------------------------------------------------------------------------

def compute(p, now, budget_s=BUDGET_S, fee=None, max_days=MAX_DAYS, log=None):
    """{(kind, source): {delay: stats}} plus the pass's meta. p: kopija.paths()."""
    from wallets import rang
    t0 = time.time()
    deadline = t0 + budget_s if budget_s else None
    hi, lo = int(now), int(now) - max_days * D
    wal = wallet_signals(p, lo, hi)
    calls = call_signals(p, lo, hi)
    by_mint = {}
    for w, eps in wal.items():
        for e in eps:
            by_mint.setdefault(e["mint"], []).append(("novcanik", w, e))
    for h, lst in calls.items():
        for tok, ts in lst:
            by_mint.setdefault(tok, []).append(("influencer", h, ts))
    sols = rang.sol_usd_days(p.get("market"))
    pr = kopija.Prices(p, lo - 60, hi)
    trades = {}
    meta = {"ts": hi, "partial": False, "wallets": len(wal), "influencers": len(calls), "tokens_all": len(by_mint)}
    done = 0
    try:
        wcon = kopija._ro(p.get("wallets"))
        if wcon is not None:
            try:
                if not pr.load_prints(wcon, by_mint, deadline):
                    meta["partial"] = True
            finally:
                wcon.close()
        for mint in sorted(by_mint, key=lambda m: zlib.crc32(m.encode())):
            if deadline and time.time() > deadline:
                meta["partial"] = True
                break
            tok = pr.token(mint)
            for kind, src, sig in by_mint[mint]:
                for d in DELAYS:
                    if kind == "novcanik":
                        t = wallet_trade(src, sig, d, tok, rang.sol_at(sols, sig["t0"] + d), hi, fee)
                    else:
                        t = call_trade(mint, sig, d, tok, rang.sol_at(sols, sig + d), hi, fee)
                    trades.setdefault((kind, src), {}).setdefault(d, []).append(t)
            done += 1
    finally:
        pr.close()
    meta["tokens"] = done
    res = {k: {d: stats(v.get(d, [])) for d in DELAYS} for k, v in trades.items()}
    meta["secs"] = round(time.time() - t0, 1)
    return res, meta


def save(res, meta, path=None):
    """The pass into kopirljivost.db: a cut pass only adds and replaces rows; a full one replaces the table."""
    con = connect(path)
    try:
        if not meta.get("partial"):
            con.execute("DELETE FROM kopirljivost")
        now = meta["ts"]
        for (kind, src), by in res.items():
            for d, s in by.items():
                con.execute("INSERT OR REPLACE INTO kopirljivost VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (kind, src, d, s["n_sig"], s["n_missed"], s["n_under"], s["n_open"], s["n"], s["med"],
                             s["mean"], s["win"], s["ci_lo"], s["ci_hi"], s["newer_mean"], s["cost_med"], s["lag_med"],
                             s["verdict"], now))
        con.execute("INSERT OR REPLACE INTO kv VALUES ('zadnji', ?)", (json.dumps(meta),))
        con.commit()
    finally:
        con.close()


def summary_line(res, meta):
    cnt = {}
    for (kind, _s), by in res.items():
        for d in DELAYS:
            v = by[d]["verdict"]
            cnt[(kind, d, v)] = cnt.get((kind, d, v), 0) + 1
    parts = []
    for kind in ("novcanik", "influencer"):
        n = sum(1 for k in res if k[0] == kind)
        per = "; ".join(f"{DELAY_HR[d]} {cnt.get((kind, d, 'kopirljivo'), 0)} kopirljivo / "
                        f"{cnt.get((kind, d, 'nije'), 0)} nije / {cnt.get((kind, d, 'malo'), 0)} premalo"
                        for d in DELAYS)
        parts.append(f"{'novčanika' if kind == 'novcanik' else 'influencera'} {n} ({per})")
    return (PREFIX + ", ".join(parts) + f"; tokena {meta.get('tokens')}/{meta.get('tokens_all')}"
            + (" (djelomično)" if meta.get("partial") else "") + f", {meta.get('secs')} s")


def run(now=None, log=print, p=None, budget_s=None, fee=None, path=None, save_=True):
    """One pass; never raises. -> (res, meta) or ({}, {})."""
    now = int(now or time.time())
    try:
        res, meta = compute(kopija.paths(p), now, BUDGET_S if budget_s is None else budget_s, fee)
        if save_:
            save(res, meta, path)
        log(summary_line(res, meta))
        return res, meta
    except Exception as e:  # noqa: BLE001 - a measurement never takes its caller down
        try:
            log(PREFIX + f"nije uspio ({type(e).__name__}: {e})")
        except Exception:  # noqa: BLE001
            pass
        return {}, {}


def last_run(path=None):
    con = kopija._ro(path or db_path())
    if con is None:
        return {}
    try:
        r = kopija._q(con, "SELECT value FROM kv WHERE key = 'zadnji'")
        return json.loads(r[0][0]) if r else {}
    except ValueError:
        return {}
    finally:
        con.close()


def for_source(kind, source, path=None):
    """{delay: row dict} stored for one source, {} when none."""
    con = kopija._ro(path or db_path())
    if con is None:
        return {}
    try:
        con.row_factory = sqlite3.Row
        rows = kopija._q(con, "SELECT * FROM kopirljivost WHERE kind = ? AND source = ?", (kind, source))
        return {int(r["delay"]): dict(r) for r in rows}
    finally:
        con.close()


# ---------- the page box -----------------------------------------------------------------------------------------------

def box(kind, source, path=None):
    """The small "Kopirljivost" box for the wallet / influencer page (ui/redak Html), "" when nothing is stored.
    Plain words: per delay the median after cost and the verdict; no formulas, weights or thresholds."""
    try:
        by = for_source(kind, source, path)
    except Exception:  # noqa: BLE001 - a page never breaks on this box
        return ""
    if not by:
        return ""
    from ui import redak as rd
    items = []
    for d in DELAYS:
        r = by.get(d)
        if not r:
            continue
        v = r["verdict"]
        n = r["n"] or 0
        reason = (f"{n} {'kopiranje' if n % 10 == 1 and n % 100 != 11 else 'kopiranja'} s cijenom"
                  + (f", {r['n_missed']} bez cijene" if r.get("n_missed") else ""))
        med = r.get("med")
        items.append({"name": f"Kasnimo {DELAY_HR[d]}", "reason": reason,
                      "value": rd.pct(med, 1, frac=True) if med is not None else "–",
                      "value_tone": rd.tone(med) if med is not None else None,
                      "sub": VERDICT_HR.get(v, v),
                      "sub_tone": {"kopirljivo": "pos", "nije": "neg"}.get(v, "mut")})
    if not items:
        return ""
    word = headline({d: (by.get(d) or {}).get("verdict") for d in DELAYS})
    return (rd.section("Kopirljivost")
            + rd.raw(f'<p class="ms-hint">{rd.h(word)}. Što bismo zaradili po tradeu (medijan) da ga kopiramo s '
                     "kašnjenjem, nakon stvarnog troška kupnje i prodaje.</p>")
            + rd.rows(items))
