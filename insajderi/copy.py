"""Copyability (the key question): when a CONFIRMED insider group buys a NEW token, (a) does a call follow within
1 / 3 / 7 days, and (b) what would OUR trade return, entering after their buy with a realistic delay and costs, at OUR
constraints (bonded; MC >= 5M separately from smaller), exiting when they sell / at the stop / after hold_h.

Walk-forward, no look-ahead: for every UTC day D after warmup_days, the confirmed set is classified (score.classify)
from the events whose window ended BEFORE D only; their buys of tokens they had not bought before, made during D,
are the trades (one per token: the first confirmed buy; we can only enter once).

Our trade: entry at buy + delay_s (60 s) at the first price we know from then on (within price_gap_s), else their own
buy price x (1 + slip_entry) (Pretpostavka: 5 % worse after a minute); exit at the first of: a price at or below
entry x (1 - stop) (filled at the stop less slip_exit), their first sell (any member of the group) + delay_s at the
price then (else their sell price x (1 - slip_exit)), entry + hold_h; cost: trade/cost.round_trip at size_usd. The
price series is the token's trades (SOL per token, from every source: ours, early.db, wallets.db, PumpPortal) or,
for the midcaps, midcap.db candles (USD); a return is a ratio inside one series. MC at entry: USD candles x the
collector's MC, else price x supply (1e9 for pump.fun) x SOL/USD (DefiLlama day close, else sol_usd). Bonded: MC at
entry >= bond_mcap, a migration before the entry, or a midcap.db token (Pretpostavka for the first).
"""
import bisect
import sqlite3
import time
from collections import defaultdict

from insajderi import score, store

BUCKETS = (("<1M", 0, 1e6), ("1M-5M", 1e6, 5e6), ("5M+", 5e6, float("inf")))


def bucket_of(mcap):
    if mcap is None:
        return "?"
    for name, lo, hi in BUCKETS:
        if lo <= mcap < hi:
            return name
    return "?"


def _in(xs):
    return ",".join("?" * len(xs))


def _chunks(xs, n=400):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ---------- data ------------------------------------------------------------------------------------------------------

def wallet_trades(con, p, wallets):
    """[(wallet, mint, ts, side, sol, tokens)] of `wallets` from every source we keep."""
    ws = sorted(set(wallets))
    out = []
    for ch in _chunks(ws):
        out += store.q(con, f"SELECT wallet, mint, ts, side, sol, tokens FROM i2_trades WHERE wallet IN ({_in(ch)})", ch)
    ec = store.ro(p.get("early_db"))
    wc = store.ro(p.get("wallet_db"))
    hc = store.ro(p.get("hype_db"))
    for ch in _chunks(ws):   # tables with a wallet index: by chunks
        out += store.q(ec, f"SELECT wallet, mint, ts, side, sol, tokens FROM group_buys WHERE wallet IN ({_in(ch)})", ch)
        out += [(w, m, ts, k, abs(s) if s is not None else None, abs(tk) if tk is not None else None)
                for w, m, ts, k, s, tk in store.q(wc, f"SELECT wallet, mint, ts, kind, sol, tokens FROM wallet_trades "
                                                      f"WHERE kind IN ('buy', 'sell') AND wallet IN ({_in(ch)})", ch)]
    want = set(ws)   # without one: ONE streaming scan each, filtered here (not one full scan per chunk)
    for c_, sql in ((ec, "SELECT wallet, mint, ts, side, sol, tokens FROM precall_trades"),
                    (hc, "SELECT wallet, mint, ts, side, sol, tokens FROM live_trades"),
                    (hc, "SELECT wallet, mint, ts, side, sol, NULL FROM chain_trades")):
        if c_ is None:
            continue
        try:
            for r in c_.execute(sql):
                if r[0] in want:
                    out.append(r)
        except sqlite3.Error:
            pass
    for x in (ec, wc, hc):
        if x is not None:
            x.close()
    seen, res = set(), []
    for r in out:
        if not r[0] or not r[1] or r[2] is None or r[3] not in ("buy", "sell"):
            continue
        k = (r[0], r[1], int(r[2]), r[3])
        if k not in seen:
            seen.add(k)
            res.append((r[0], r[1], int(r[2]), r[3], r[4], r[5]))
    return sorted(res, key=lambda r: r[2])


class Prices:
    """Price series per token, read LAZILY (only the tokens a trade is simulated on, the 512 MB server):
    ("usd", [(ts, px)]) from midcap.db candles around the trade, else ("sol", [(ts, px)]) from the token's trades."""

    def __init__(self, con, p, c, tokens=None):
        self.con, self.p, self.c = con, p, c
        self.mc_now, self.supply, self.mig, self._sol, self._sol_usd = {}, {}, {}, {}, None
        self._meta = set()

    def _load_meta(self, tok):
        if tok in self._meta:
            return
        self._meta.add(tok)
        mc = store.ro(self.p.get("midcap_db"))
        r = store.q(mc, "SELECT mcap FROM tokens WHERE mint = ?", (tok,))
        if mc is not None:
            mc.close()
        if r and r[0][0]:
            self.mc_now[tok] = r[0][0]
        hc, kc = store.ro(self.p.get("hype_db")), store.ro(self.p.get("kol_db"))
        r = store.q(hc, "SELECT MIN(ts) FROM live_launches WHERE pool = 'migration' AND mint = ?", (tok,))
        if r and r[0][0]:
            self.mig[tok] = int(r[0][0])
        r = store.q(kc, "SELECT supply FROM tokens WHERE supply > 0 AND token = ?", (tok,))
        if r:
            self.supply[tok] = float(r[0][0])
        for x in (hc, kc):
            if x is not None:
                x.close()

    def _usd(self, tok, ts):
        mc = store.ro(self.p.get("midcap_db"))
        lo, hi = int(ts) - 3600, int(ts) + int(float(self.c["hold_h"]) * 3600) + 2 * 3600
        rows = store.q(mc, "SELECT ts, c FROM c15 WHERE token = ? AND ts BETWEEN ? AND ? ORDER BY ts", (tok, lo, hi)) or \
            store.q(mc, "SELECT ts, c FROM c1h WHERE token = ? AND ts BETWEEN ? AND ? ORDER BY ts", (tok, lo, hi))
        last = store.q(mc, "SELECT c FROM c1h WHERE token = ? ORDER BY ts DESC LIMIT 1", (tok,)) if rows else []
        if mc is not None:
            mc.close()
        return [(int(t), float(px)) for t, px in rows if px], (float(last[0][0]) if last and last[0][0] else None)

    def _sol_series(self, tok):
        if tok in self._sol:
            return self._sol[tok]
        pts = [(int(ts), sol / tk) for ts, sol, tk in store.q(self.con, "SELECT ts, sol, tokens FROM i2_trades WHERE mint = ? "
                                                                       "AND sol > 0 AND tokens > 0", (tok,))]
        ec, hc = store.ro(self.p.get("early_db")), store.ro(self.p.get("hype_db"))
        for t in ("precall_trades", "group_buys"):
            pts += [(int(ts), sol / tk) for ts, sol, tk in store.q(ec, f"SELECT ts, sol, tokens FROM {t} WHERE mint = ? AND "
                                                                      f"sol > 0 AND tokens > 0", (tok,))]
        pts += [(int(ts), px) for ts, px in store.q(hc, "SELECT ts, price_sol FROM live_trades WHERE mint = ? AND "
                                                        "price_sol > 0", (tok,))]
        pts += [(int(h) + 3599, px) for h, px in store.q(hc, "SELECT hour, close_px FROM live_trades_hourly WHERE mint = ? "
                                                             "AND close_px > 0", (tok,))]
        for x in (ec, hc):
            if x is not None:
                x.close()
        self._sol[tok] = sorted(pts)
        if len(self._sol) > 2000:   # bounded: the oldest token's series goes first
            self._sol.pop(next(iter(self._sol)))
        return self._sol[tok]

    def series(self, tok, ts):
        self._load_meta(tok)
        if tok in self.mc_now:
            u, last = self._usd(tok, ts)
            if u and u[0][0] <= ts <= u[-1][0] + 3600 and last:
                self._last_usd = getattr(self, "_last_usd", {})
                self._last_usd[tok] = last
                return "usd", u
        return "sol", self._sol_series(tok)

    @staticmethod
    def at(series, ts, gap):
        """The first price at or after ts within gap seconds, else None."""
        i = bisect.bisect_left(series, (ts, -1.0))
        if i < len(series) and series[i][0] - ts <= gap:
            return series[i][1]
        return None

    @staticmethod
    def before(series, ts, gap):
        i = bisect.bisect_right(series, (ts, float("inf"))) - 1
        if i >= 0 and ts - series[i][0] <= gap:
            return series[i][1]
        return None

    def sol_usd(self, ts):
        if self._sol_usd is None and not self.c.get("sol_usd_hist", True):
            self._sol_usd = lambda _ts: None
        if self._sol_usd is None:
            try:
                from wallets import rpc
                self._sol_usd = rpc.sol_usd_history()
            except Exception:  # noqa: BLE001
                self._sol_usd = lambda _ts: None
        try:
            return self._sol_usd(ts) or float(self.c["sol_usd"])
        except Exception:  # noqa: BLE001
            return float(self.c["sol_usd"])

    def mcap(self, tok, kind, series, px, ts):
        if kind == "usd":
            last = getattr(self, "_last_usd", {}).get(tok)
            return self.mc_now.get(tok) * px / last if last and self.mc_now.get(tok) else None
        return px * self.supply.get(tok, float(self.c["supply"])) * self.sol_usd(ts)

    def bonded(self, tok, mcap, ts):
        self._load_meta(tok)
        if tok in self.mc_now:
            return True
        if tok in self.mig and self.mig[tok] <= ts:
            return True
        return mcap is not None and mcap >= self.c["bond_mcap"]


def cost_rt(c):
    try:
        from trade import cost
        return cost.round_trip(float(c["size_usd"]))
    except Exception:  # noqa: BLE001
        return 0.04


# ---------- one trade -----------------------------------------------------------------------------------------------

def simulate(buy, sells, pr, c, rt):
    """buy (wallet, mint, ts, side, sol, tokens), sells [same shape] of the group after it -> {"entry_ts", "mcap",
    "bonded", "ret", "exit"} or None when no exit can be priced."""
    _w, tok, bts, _s, bsol, btk = buy
    gap, delay = int(c["price_gap_s"]), int(c["delay_s"])
    et = bts + delay
    kind, ser = pr.series(tok, et)
    px = pr.at(ser, et, gap)
    if px is None and kind == "sol" and bsol and btk:
        px = bsol / btk * (1 + float(c["slip_entry"]))
    if not px:
        return None
    mcap = pr.mcap(tok, kind, ser, px, et)
    stop_px = px * (1 - float(c["stop"]))
    end = et + int(float(c["hold_h"]) * 3600)
    sell = next((s for s in sells if s[2] > bts), None)
    exits = []
    if sell is not None:
        st = sell[2] + delay
        spx = pr.at(ser, st, gap)
        if spx is None and kind == "sol" and sell[4] and sell[5]:
            spx = sell[4] / sell[5] * (1 - float(c["slip_exit"]))
        if spx and st <= end:
            exits.append((st, spx, "prodali su"))
    hp = pr.at(ser, end, gap) or pr.before(ser, end, gap)
    if hp:
        exits.append((end, hp, "vrijeme"))
    if not exits:
        return None
    ex_ts, ex_px, why = min(exits, key=lambda x: x[0])
    i = bisect.bisect_right(ser, (et, float("inf")))
    for ts, p_ in ser[i:]:
        if ts > ex_ts:
            break
        if p_ <= stop_px:
            ex_ts, ex_px, why = ts, stop_px * (1 - float(c["slip_exit"])), "stop"
            break
    return {"entry_ts": et, "mcap": mcap, "bonded": pr.bonded(tok, mcap, et), "ret": ex_px / px - 1 - rt, "exit": why,
            "exit_ts": ex_ts}


# ---------- the walk-forward ----------------------------------------------------------------------------------------

def calls_after(p, toks):
    """{token: [call ts]} of tracked callers (bots and wallets out), sorted."""
    kc = store.ro(p.get("kol_db"))
    out = defaultdict(list)
    for ch in _chunks(sorted(toks)):
        for t, ts in store.q(kc, f"SELECT token, ts FROM calls WHERE kind = 'call' AND handle NOT LIKE 'w:%' AND token IN "
                                 f"({_in(ch)})", ch):
            if ts:
                out[t].append(int(ts))
    if kc is not None:
        kc.close()
    for t in out:
        out[t].sort()
    return out


def walk(con, p, c, events, parts, now, bad=frozenset(), first_trade=None, trades=None, prices=None):
    """The walk-forward rows [dict] (one per token: the first confirmed buy of a day) and the confirmed sets per day."""
    if not events:
        return [], {}
    start = min(e["t0"] for e in events) + int(c["warmup_days"]) * 86400
    d0 = start - start % 86400 + 86400
    days = list(range(d0, int(now) - int(now) % 86400 + 86400, 86400))
    conf_by_day = {}
    members = set()
    for d in days:
        st = score.classify(parts, events, d, c, bad, first_trade)
        conf_by_day[d] = score.confirmed(st)
        for ms in conf_by_day[d].values():
            members |= set(ms)
    if not members:
        return [], conf_by_day
    trades = trades if trades is not None else wallet_trades(con, p, members)
    by_w = defaultdict(list)
    for r in trades:
        by_w[r[0]].append(r)
    toks = {r[1] for r in trades}
    pr = prices or Prices(con, p, c, toks)
    ca = calls_after(p, toks)
    rt = cost_rt(c)
    rows, taken = [], set()
    for d in days:
        for owner, ms in conf_by_day[d].items():
            own = sorted((r for m in ms for r in by_w.get(m, [])), key=lambda r: r[2])
            before = {r[1] for r in own if r[2] < d}
            for r in own:
                if not d <= r[2] < d + 86400 or r[3] != "buy" or r[1] in before or r[1] in taken:
                    continue
                if r[2] > now:
                    continue
                taken.add(r[1])
                sells = [s for s in own if s[1] == r[1] and s[3] == "sell" and s[2] > r[2]]
                sim = simulate(r, sells, pr, c, rt)
                nxt = [t for t in ca.get(r[1], []) if t > r[2]]
                row = {"owner": owner, "token": r[1], "buy_ts": r[2], "day": store.day(d),
                       "call_after_s": (nxt[0] - r[2]) if nxt else None}
                if sim:
                    row.update(entry_ts=sim["entry_ts"], mcap=sim["mcap"], bucket=bucket_of(sim["mcap"]),
                               bonded=int(sim["bonded"]), ret=round(sim["ret"], 4), exit=sim["exit"])
                else:
                    row.update(entry_ts=None, mcap=None, bucket="?", bonded=None, ret=None, exit="bez cijene")
                rows.append(row)
    return rows, conf_by_day


def summarize(rows):
    """{"svi", "bondani", "nasa_pravila" (bonded, MC 5M+), "<1M", "1M-5M", "5M+": stats; "poziv_nakon": {...}}."""
    from trade import edge

    def stats(xs):
        rets = [x["ret"] for x in xs if x.get("ret") is not None]
        s = edge.ev_stats(rets)
        pct = (lambda v: None if v is None else round(v * 100, 2))
        return {"n": s["n"], "hit_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1) if rets else None,
                "ev_pct": pct(s["ev"]), "ci90_lo_pct": pct(s["lo90"]), "ci90_hi_pct": pct(s["hi90"])}
    out = {"svi": stats(rows), "bondani": stats([r for r in rows if r.get("bonded")]),
           "nasa_pravila": stats([r for r in rows if r.get("bonded") and r.get("bucket") == "5M+"])}
    for name, _lo, _hi in BUCKETS:
        out[name] = stats([r for r in rows if r.get("bucket") == name and r.get("bonded")])
    n = len(rows)
    out["poziv_nakon"] = {"n": n, **{f"{d}d_pct": (round(100 * sum(1 for r in rows if r.get("call_after_s") is not None
                                                                     and r["call_after_s"] <= d * 86400) / n, 1)
                                                   if n else None) for d in (1, 3, 7)}}
    out["bez_cijene"] = sum(1 for r in rows if r.get("ret") is None)
    out["izlazi"] = {k: sum(1 for r in rows if r.get("exit") == k) for k in ("prodali su", "stop", "vrijeme")}
    return out


def verdict(summary, n_min=20):
    """(copyable at our constraints, why in Croatian)."""
    s = summary.get("nasa_pravila") or {}
    if (s.get("n") or 0) < n_min:
        return False, (f"na našim pravilima (bondani, MC ≥ 5M) samo n={s.get('n') or 0} kopija (treba {n_min}+): insajderi "
                       "kupuju ispod naših pravila")
    if (s.get("ev_pct") or 0) <= 0:
        return False, f"EV {s['ev_pct']:+.1f} % po kopiji nakon troška (n={s['n']}): ne isplati se"
    if (s.get("ci90_lo_pct") or 0) <= 0:
        return False, f"EV {s['ev_pct']:+.1f} %, ali donja granica 90 % intervala {s['ci90_lo_pct']:+.1f} % nije iznad nule"
    return True, f"EV {s['ev_pct']:+.1f} % (CI90 od {s['ci90_lo_pct']:+.1f} %), n={s['n']}: kopirati u demu"


def save(con, rows):
    con.execute("DELETE FROM i2_copy")
    con.executemany("INSERT OR REPLACE INTO i2_copy VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(r["owner"], r["token"], r["buy_ts"], r.get("entry_ts"), r.get("mcap"), r.get("bucket"),
                      r.get("bonded"), r.get("ret"), r.get("exit"), r.get("call_after_s"), r["day"]) for r in rows])
    con.commit()


def _now():
    return int(time.time())
