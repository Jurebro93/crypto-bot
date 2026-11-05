"""One pass of the strategy comparison, every minute in its own thread of run_paper (no extra process).

Five demo accounts of $1000 each buy from a different source: tracked wallets, KOL calls, the tool's own picks (what
the main demo bot buys), Mix (two of those three agree) and a random control. All five use the SAME exit rules as
the main demo (paper/config.json plus the learned exits), so the only difference between them is where the entry
came from. Never real money.

1. Signals (strat/signals.py), read-only from kol.db, tg.db, hype.db, paper.db. A signal older than max_delay_min
   when we see it does not enter (we would be buying somebody else's pump). Each strategy buys a token once.
2. Caps per strategy: max_open, per_hour, per_day, and the account's cash (size_usd, less when the cash is low).
3. Prices: DexScreener, one batched request for all five (koltest.run.market), the same free endpoint as the demo.
"""
import json
import os
import sys
import time

from strat import signals, store

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")


def load_config(path=None):
    with open(path or CONFIG) as f:
        return json.load(f)


def keys(cfg):
    return [s["key"] for s in cfg["strategies"]]


def exit_rules(now):
    """The main demo's exit rules right now, learned exits included (default class)."""
    from paper import sim
    cfg = sim.load_config()
    try:
        from exits import profiles
        cfg = profiles.for_trade(cfg, "default", state=profiles.load(), now=now)
    except Exception:  # noqa: BLE001 - no learned exits yet: the config ones
        pass
    return cfg


def market(tokens):
    from koltest import run as kt
    return kt.market(tokens)


def _paper_min_score():
    try:
        from paper import sim
        return sim.load_config().get("min_score", 50)
    except Exception:  # noqa: BLE001
        return 50


CAP = 3.0   # one copied trade counts at most +300% in the wallet ranking


def wallet_rank(con, cfg):
    """[(wallet label, closed copies, mean return capped +300%, pnl $)] of the tracked wallets by how OUR copies of
    their buys did (same exits as every strategy), best first. Only this is a proven result: chain_trades has no
    sell amounts, and wallet buys are not part of the KOL call score."""
    per = {}
    # the old all-wallets account ('novcanici', until 4.11.) and the top-wallets one both count: same copies
    for why, ret, pnl in con.execute("SELECT why, ret, pnl_usd FROM positions WHERE strat IN ('novcanici', "
                                     "'top_novcanici') AND status='closed'"):
        a = per.setdefault(why or "?", [0, 0.0, 0.0])
        a[0] += 1
        a[1] += min(CAP, ret or 0)
        a[2] += pnl or 0
    return sorted(((w, n, s / n, p) for w, (n, s, p) in per.items()), key=lambda r: (-r[2], -r[3]))


def wallets_allowed(con, cfg):
    """(top labels, proven-out labels): the top novcanici_top proven wallets with a positive mean are copied; a wallet
    with fewer than novcanici_min_n closed copies is still being measured (copied); every other measured one is not
    (Nicholas 4.11.: "nećemo pratiti neuspješne")."""
    min_n, top_n = cfg.get("novcanici_min_n", 3), cfg.get("novcanici_top", 10)
    proven = [r for r in wallet_rank(con, cfg) if r[1] >= min_n]
    top = [r[0] for r in proven if r[2] > 0][:top_n]
    return set(top), {r[0] for r in proven} - set(top)


def band_of(cfg, key, mcap):
    """Is this market cap inside the band of strategy `key` (alat_bands)? Strategies without a band take any."""
    b = (cfg.get("alat_bands") or {}).get(key)
    if not b:
        return True
    lo, hi = b
    return (mcap or 0) >= (lo or 0) and (hi is None or (mcap or 0) < hi)


def wanted(src, cfg, now, last_random, out_wallets=()):
    """{strategy: [(token, ts, who, score)]} for this pass. Every alat_* band gets the tool's picks; the band is
    checked when the token is priced (its market cap at entry)."""
    out = {"novcanici": src.get("novcanici", []), "kol": src.get("kol", []),
           "top_novcanici": [e for e in src.get("novcanici", []) if e[2] not in out_wallets],
           "alat": src.get("alat", []),
           "insajderi": src.get("insajderi", []),
           "mix": signals.mix(src, _paper_min_score(), cfg["mix_window_min"] * 60),
           "kontrola": signals.random_pick(src, now, last_random, cfg["kontrola_every_min"] * 60)}
    for k in cfg.get("alat_bands") or {}:
        out[k] = src.get("alat", [])
    frozen = {s["key"] for s in cfg["strategies"] if s.get("frozen")}   # no new entries (5.11.: Top novčanici)
    return {k: ([] if k in frozen else out.get(k, [])) for k in keys(cfg)}


def accounts(con, cfg, marks=None, ex=None):
    """{strategy: {cash, value, open, closed, wins, pnl_closed}}. Open positions are marked at marks[token] (price,
    liq) as if sold now, else at their last price."""
    from paper import sim
    marks = marks or {}
    out = {k: {"cash": cfg["bankroll_usd"], "value": cfg["bankroll_usd"], "open": 0, "closed": 0, "wins": 0,
               "pnl_closed": 0.0} for k in keys(cfg)}
    for p in store.rows(con):
        a = out.get(p["strat"])
        if a is None:
            continue
        if p["status"] == "closed":
            a["closed"] += 1
            a["wins"] += (p["pnl_usd"] or 0) > 0
            a["pnl_closed"] += p["pnl_usd"] or 0
            a["cash"] += p["pnl_usd"] or 0
            a["value"] += p["pnl_usd"] or 0
        else:
            pos = p["state"]
            a["open"] += 1
            a["cash"] += pos.get("realized", 0) - p["size_usd"]
            px, liq = marks.get(p["token"]) or (p["last_px"], p["last_liq"])
            r = sim.result(pos, px, liq, ex or {"fee": 0.01}) if pos else {"pnl_usd": 0}
            a["value"] += r["pnl_usd"]
    return out


def _save(con, rid, pos, res, px, liq, now, status=None, reason=None):
    con.execute("""UPDATE positions SET state=?, last_ts=?, last_px=?, last_liq=?, pnl_usd=?, ret=?,
                   status=COALESCE(?, status), closed_ts=?, exit_reason=? WHERE id=?""",
                (json.dumps(pos), int(now), px, liq, res["pnl_usd"], res["ret"], status,
                 int(now) if status == "closed" else None, reason or res.get("exit_reason"), rid))


def intake(con, cfg, now, want, start, acc):
    """Insert the new signals each strategy may take as pending (bought right after, once priced)."""
    n = 0
    for k, evs in want.items():
        if not evs:
            continue
        known = {t for (t,) in con.execute("SELECT token FROM positions WHERE strat=?", (k,))}
        busy = con.execute("SELECT COUNT(*) FROM positions WHERE strat=? AND status IN ('open','pending')",
                           (k,)).fetchone()[0]
        hour = con.execute("SELECT COUNT(*) FROM positions WHERE strat=? AND status!='skip' AND seen_ts>=?",
                           (k, int(now - 3600))).fetchone()[0]
        day = con.execute("SELECT COUNT(*) FROM positions WHERE strat=? AND status!='skip' AND seen_ts>=?",
                          (k, int(now - 86400))).fetchone()[0]
        cash = acc[k]["cash"] - cfg["size_usd"] * con.execute(
            "SELECT COUNT(*) FROM positions WHERE strat=? AND status='pending'", (k,)).fetchone()[0]
        for tok, ts, who, _sc in sorted(evs, key=lambda e: (-e[3], -e[1])):
            if tok in known or ts < start or now - ts > cfg["max_delay_min"] * 60:
                continue
            if (busy >= cfg["max_open"] or hour >= cfg["per_hour"] or day >= cfg["per_day"]
                    or (cfg.get("cash_limit", True) and cash < cfg["min_size_usd"])):
                break
            known.add(tok)
            con.execute("INSERT OR IGNORE INTO positions (strat, token, why, signal_ts, seen_ts, status) "
                        "VALUES (?,?,?,?,?,'pending')", (k, tok, who, int(ts), int(now)))
            busy, hour, day, cash, n = busy + 1, hour + 1, day + 1, cash - cfg["size_usd"], n + 1
    return n


def step(now=None, cfg=None, path=None, market_fn=None, sources=None, ex=None, quiet=False):
    """One pass. Returns {'entered': n, 'closed': n, 'open': n}."""
    from paper import sim
    cfg = cfg or load_config()
    if not cfg.get("enabled", True):
        return {}
    now = now or time.time()
    ex = ex or exit_rules(now)
    market_fn = market_fn or market
    srcs = sources or signals.Sources()
    src = srcs.read(int(now), (cfg["mix_window_min"] + cfg["max_delay_min"]) * 60)
    insider_set = getattr(srcs, "insiders", set())
    con = store.connect(path)
    try:
        start = store.start_ts(con, now)
        last_random = float(store.kv_get(con, "last_random", 0) or 0)
        _top, out_w = wallets_allowed(con, cfg) if "top_novcanici" in keys(cfg) else (set(), set())
        want = wanted(src, cfg, now, last_random, out_w)
        acc = accounts(con, cfg, ex=ex)
        intake(con, cfg, now, want, start, acc)
        if want.get("kontrola"):
            store.kv_set(con, "last_random", int(now))
        con.commit()
        pending = con.execute("SELECT id, strat, token, seen_ts FROM positions WHERE status='pending'").fetchall()
        live = store.rows(con, "status='open'")
        tokens = {t for _, _, t, _ in pending} | {p["token"] for p in live}
        mk = market_fn(tokens) if tokens else {}
        if mk is None:
            return {"entered": 0, "closed": 0, "open": len(live)}
        entered = closed = 0
        acc = accounts(con, cfg, ex=ex)
        for rid, k, tok, seen in pending:
            m = mk.get(tok)
            reason = None
            if m and m[0] > 0:
                px, liq, mcap = m[0], m[1] or 0, m[2] or 0
                if mcap and liq > mcap:
                    reason = "lažni pool"
                elif liq < cfg["min_liq"]:
                    reason = "premala likvidnost"
                elif mcap > cfg["max_mcap"]:
                    reason = "prevelik token"
                elif not band_of(cfg, k, mcap):
                    reason = "drugi razred market capa"
                elif cfg.get("cash_limit", True) and acc[k]["cash"] < cfg["min_size_usd"]:
                    reason = "nema novca na računu"
                else:   # cash_limit false (Nicholas 4.11.: "neograničeno tradeova"): always the full stake, cash may go < 0
                    size = (round(min(cfg["size_usd"], acc[k]["cash"]), 2) if cfg.get("cash_limit", True)
                            else cfg["size_usd"])
                    pos = sim.open_position(px, liq, int(now), size, ex)
                    con.execute("UPDATE positions SET symbol=?, url=?, entry_ts=?, entry_mcap=?, size_usd=?, "
                                "status='open', state=?, last_ts=?, last_px=?, last_liq=?, pnl_usd=0, ret=0 "
                                "WHERE id=?", (m[3], m[4], int(now), mcap, size, json.dumps(pos), int(now), px, liq,
                                               rid))
                    acc[k]["cash"] -= size
                    entered += 1
                    continue
                con.execute("UPDATE positions SET status='skip', close_reason=?, symbol=? WHERE id=?",
                            (reason, m[3], rid))
            elif now - seen > cfg["price_wait_min"] * 60:
                con.execute("UPDATE positions SET status='skip', close_reason='nema cijene' WHERE id=?", (rid,))
        for p in live:
            pos, m = p["state"], mk.get(p["token"])
            if m and m[0] > 0:
                px, liq = m[0], m[1] or 0
                con.execute("UPDATE positions SET missing_since=NULL WHERE id=?", (p["id"],))
            elif not p.get("missing_since"):
                con.execute("UPDATE positions SET missing_since=? WHERE id=?", (int(now), p["id"]))
                continue
            elif now - p["missing_since"] >= cfg["missing_h"] * 3600:
                px, liq = 0, 0   # pair gone for hours: a rug, worth nothing (as in the main demo)
            else:
                continue
            sim.step(pos, px, liq, int(now), ex)
            if pos["open"] and p["strat"] == "insajderi" and insider_set and p.get("entry_ts"):
                # the strategy's own exit: the insiders who bought before us are selling (hype.db chain_trades)
                from kol import insiders as _ins
                if _ins.sold_since(srcs.hype_db, p["token"], p["entry_ts"], insider_set):
                    sim.sell(pos, pos["left"] if pos.get("left") is not None else 1.0, px, liq, int(now), "insajderi prodaju", ex)
            res = sim.result(pos, px, liq, ex)
            status = None if pos["open"] else "closed"
            _save(con, p["id"], pos, res, px, liq, now, status)
            closed += status == "closed"
        last_eq = float(store.kv_get(con, "last_equity", 0) or 0)
        if now - last_eq >= cfg["equity_every_min"] * 60:
            marks = {t: (v[0], v[1]) for t, v in mk.items() if v and v[0] > 0}
            for k, a in accounts(con, cfg, marks, ex).items():
                con.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?)", (int(now), k, round(a["value"], 2)))
            store.kv_set(con, "last_equity", int(now))
        con.execute("DELETE FROM positions WHERE status='skip' AND seen_ts < ?", (int(now - 10 * 86400),))
        con.commit()
        n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
        if (entered or closed) and not quiet:
            print(f"strategije: +{entered} ulaza, {closed} zatvoreno, otvoreno {n_open}", flush=True)
        return {"entered": entered, "closed": closed, "open": n_open}
    finally:
        con.close()


def summary(con, cfg, ex=None):
    """Per strategy, for the page, the report and the learning: account, return, trades, hit rate, best/worst."""
    from strat import robust
    acc = accounts(con, cfg, ex=ex)
    out = []
    closed = {s["key"]: store.rows(con, "strat=? AND status='closed'", (s["key"],)) for s in cfg["strategies"]}
    ctrl = closed.get("kontrola") if "kontrola" in closed else None
    for s in cfg["strategies"]:
        k = s["key"]
        a = acc[k]
        done = closed[k]
        rets = sorted(p["ret"] or 0 for p in done)
        st = (("kontrola", "kontrola", "nasumični ulaz iz istog skenera; mjerilo za ostale") if k == "kontrola"
              else ("zamrznuto", "zamrznuto", s.get("frozen_why") or "bez novih ulaza") if s.get("frozen")
              else robust.status(done, ctrl))
        out.append({**s, **a, "ret": a["value"] / cfg["bankroll_usd"] - 1,
                    "robust": robust.without_top(done), "status": st,
                    "portfolio": robust.portfolio(done, cfg["bankroll_usd"]),
                    "hit": (a["wins"] / a["closed"]) if a["closed"] else None,
                    "avg_ret": (sum(rets) / len(rets)) if rets else None,
                    "med_ret": rets[len(rets) // 2] if rets else None,
                    "best": max(done, key=lambda p: p["pnl_usd"] or 0) if done else None,
                    "worst": min(done, key=lambda p: p["pnl_usd"] or 0) if done else None,
                    "x2": sum(1 for p in done if (p["state"].get("peak") or 0) >= 1.0)})
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cfg = load_config()
    if argv and argv[0] == "status":
        con = store.ro()
        if con is None:
            print("Usporedba strategija još nije pokrenuta.")
            return 0
        for s in summary(con, cfg):
            print(f"{s['name']:24} ${s['value']:8.2f} ({s['ret']:+.1%})  zatvoreno {s['closed']}  otvoreno {s['open']}")
        return 0
    print(step())
    return 0


if __name__ == "__main__":
    sys.exit(main())
