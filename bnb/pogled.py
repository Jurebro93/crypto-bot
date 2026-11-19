"""Read helpers for the UI (a BNB tab: the UI agents build it from these; read-only, never raises, stable shapes).

    summary()      -> {"chain": "bsc", "updated": int|None, "tokens": int, "pumps": int, "read": int,
                       "groups": int, "confirmed": int, "trades": int, "db_mb": float, "last_pass": str|None,
                       "calls": {"rpc": str, "free": {source: int}}|None}
    funnel()       -> {"pumpe15_1h", "pumpe15_1d", "pumpe2_1h", "pumpe2_1d", "duboko", "procitano", "izvan_dosega",
                       "rani", "rani_prodali", "blizu_praga", "grupe", "potvrdjeno": int,
                       "pokrivenost_pre_med", "pokrivenost_skok_med": float|None, "n_pokrivenost": int,
                       "klase": {cls: int}}   ({} before the first pass)
    groups(cls="prije_pumpe", limit=50)
                   -> [{"address": str, "cls": str, "why": str, "confirmed": bool, "n_tokens": int, "n_pumps15": int,
                        "n_pumps2": int, "med_lead_min": float|None, "pnl_usd": float|None, "last_seen": int|None,
                        "pumps": [{"symbol", "token", "t0", "tier", "lead_min", "usd_in", "usd_out"}]}]
                      confirmed first, then by pump tokens; cls=None: every stored class (exclusions too)
    measurement(limit=100)
                   -> {"by_source": {source: {"signals", "measured", "misses", "open": int, "mean_net_50_pct",
                       "mean_net_250_pct", "win_pct": float|None, "median_delay_s": float|None}},
                       "rows": [{"id", "source", "address", "token", "symbol", "seen_ts", "delay_s", "entry_ts",
                       "entry_price", "entry_mcap", "mc_bucket", "liq", "status", "exit_ts", "exit_reason",
                       "ret_gross", "cost_50", "cost_250", "ret_net_50", "ret_net_250"}]}  newest first

Statistics, never accusations: an address on the list bought before and sold into pumps more often than the rules
let pass; nothing says who it is or why.
"""
import json

from bnb import store

FUNNEL_KEYS = ("pumpe15_1h", "pumpe15_1d", "pumpe2_1h", "pumpe2_1d", "duboko", "procitano", "izvan_dosega", "rani",
               "rani_prodali", "blizu_praga", "grupe", "potvrdjeno", "pokrivenost_pre_med", "pokrivenost_skok_med",
               "n_pokrivenost", "klase")


def _con(path=None):
    return store.ro(path)


def _one(con, sql, args=()):
    r = store.q(con, sql, args)
    return r[0][0] if r and r[0][0] is not None else 0


def summary(path=None):
    con = _con(path)
    out = {"chain": store.CHAIN, "updated": None, "tokens": 0, "pumps": 0, "read": 0, "groups": 0, "confirmed": 0,
           "trades": 0, "db_mb": round(store.size_mb(path), 1), "last_pass": None, "calls": None}
    if con is None:
        return out
    try:
        out["tokens"] = _one(con, "SELECT COUNT(*) FROM bnb_tokens WHERE meme = 1")
        out["pumps"] = _one(con, "SELECT COUNT(*) FROM bnb_events WHERE tier IS NOT NULL")
        out["read"] = _one(con, "SELECT COUNT(*) FROM bnb_cover WHERE depth >= ?", (store.FETCH_DEPTH,))
        out["groups"] = _one(con, "SELECT COUNT(*) FROM bnb_pp WHERE cls = 'prije_pumpe'")
        out["confirmed"] = _one(con, "SELECT COUNT(*) FROM bnb_pp WHERE cls = 'prije_pumpe' AND confirmed_ts IS NOT NULL")
        out["trades"] = _one(con, "SELECT COUNT(*) FROM bnb_trades")
        r = store.q(con, "SELECT ts, kind, calls FROM bnb_runs ORDER BY ts DESC LIMIT 1")
        if r:
            out["updated"], out["last_pass"] = int(r[0][0]), r[0][1]
            try:
                out["calls"] = json.loads(r[0][2])
            except (TypeError, ValueError):
                out["calls"] = None
    finally:
        con.close()
    return out


def funnel(path=None):
    con = _con(path)
    if con is None:
        return {}
    try:
        f = (store.kv_json(con, "last", default={}) or {}).get("lijevak") or {}
    finally:
        con.close()
    return {k: f.get(k) for k in FUNNEL_KEYS} if f else {}


def groups(cls="prije_pumpe", limit=50, path=None):
    con = _con(path)
    if con is None:
        return []
    try:
        sql = ("SELECT owner, cls, why, confirmed_ts, n_tokens, n_pumps15, n_pumps2, med_lead_min, pnl_usd, last_seen, "
               "pumps FROM bnb_pp")
        args = []
        if cls:
            sql += " WHERE cls = ?"
            args.append(cls)
        rows = store.q(con, sql + " ORDER BY (confirmed_ts IS NULL), n_tokens DESC, n_pumps15 DESC LIMIT ?",
                       (*args, int(limit)))
    finally:
        con.close()
    out = []
    for o, cl, why, cts, nt, n15, n2, lead, pnl, last, pumps in rows:
        try:
            ps = json.loads(pumps or "[]")
        except ValueError:
            ps = []
        out.append({"address": o, "cls": cl, "why": why, "confirmed": cts is not None, "n_tokens": nt or 0,
                    "n_pumps15": n15 or 0, "n_pumps2": n2 or 0, "med_lead_min": lead, "pnl_usd": pnl,
                    "last_seen": last,
                    "pumps": [{k: p.get(k) for k in ("symbol", "token", "t0", "tier", "lead_min", "usd_in", "usd_out")}
                              for p in ps]})
    return out


MKEYS = ("id", "source", "address", "token", "symbol", "seen_ts", "delay_s", "entry_ts", "entry_price", "entry_mcap",
         "mc_bucket", "liq", "status", "exit_ts", "exit_reason", "ret_gross", "cost_50", "cost_250", "ret_net_50",
         "ret_net_250")


def measurement(limit=100, path=None):
    con = _con(path)
    if con is None:
        return {"by_source": {}, "rows": []}
    try:
        from bnb import prati
        by = prati.summary(con)
        rows = store.q(con, "SELECT id, source, wallet, token, symbol, seen_ts, delay_s, entry_ts, entry_price, "
                            "entry_mcap, mc_bucket, liq, status, exit_ts, exit_reason, ret_gross, cost_50, cost_250, "
                            "ret_net_50, ret_net_250 FROM bnb_mjera ORDER BY seen_ts DESC LIMIT ?", (int(limit),))
    finally:
        con.close()
    return {"by_source": by, "rows": [dict(zip(MKEYS, r)) for r in rows]}
