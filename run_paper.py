#!/usr/bin/env python3
"""Paper trading (demo, no real money) of the tokens the bot picks, and a daily review that learns from it.

    python3 run_paper.py run --scan                # everything in one loop: hype scan, entries, prices, daily review
    python3 run_paper.py run                       # same, but signals come from a separate `run_hype.py watch`
    python3 run_paper.py status                    # open positions, demo balance
    python3 run_paper.py review                    # daily report: mistakes, missed winners, changes the bot applied
    python3 run_paper.py apply                     # (old, optional) write the suggested config into paper/config.json

The daily review applies safe entry-rule changes itself (paper/auto.py: guardrails + rollback), nothing manual.

Picks come from hype.db (run_hype.py signals) and the newest output/dex-*.json (canonical event tokens).
Every candidate is decided once: taken, or skipped with a reason. Skipped ones keep being tracked for
track_h hours so the review can see what the filters cost and what they saved. Rules live in paper/config.json.
Buys, sells and review summaries are logged to output/paper/journal.log; Telegram is off unless PAPER_TELEGRAM=1.
"""
import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sqlite3
import sys
import time

from dexscreener import client
from exits import profiles as exits_profiles
from paper import auto, dca, review, sim, store, arms

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "paper.db")  # own file, see run_hype.DB
HYPE_DB = os.path.join(HERE, "hype.db")
RUG_DB = os.environ.get("RUG_DB", os.path.join(HERE, "rug.db"))
OUT = os.path.join(HERE, "output", "paper")
SUGGESTED = os.path.join(HERE, "paper", "config.suggested.json")


def _usd(x):
    x = x or 0
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:.2f}" if abs(x) < 100 else f"${x:.0f}"


def _today(ts=None):
    return dt.datetime.fromtimestamp(ts or time.time()).strftime("%Y-%m-%d")


def notify(text, telegram=False):
    """Every buy, sell and review summary goes to output/paper/journal.log; Telegram only when asked for."""
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "journal.log"), "a") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
    if not (telegram or os.environ.get("PAPER_TELEGRAM") == "1"):
        return
    try:
        import run_hype
        run_hype.alert(text)
    except Exception as e:
        print(f"  telegram: {e}", file=sys.stderr)


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) if os.path.exists(path) else None


def hype_signals(fresh_min=30, now=None):
    """Newest signal per token from the last fresh_min minutes."""
    con = _ro(HYPE_DB)
    if con is None:
        return []
    try:
        rows = con.execute("""SELECT s.token, s.symbol, s.ts, s.score, s.price, s.liquidity, s.mcap, s.features,
                                     s.sources, s.url
                              FROM hype_signals s JOIN (SELECT token, MAX(ts) ts FROM hype_signals WHERE ts >= ?
                              GROUP BY token) l ON s.token = l.token AND s.ts = l.ts""",
                           ((now or time.time()) - fresh_min * 60,)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [{"token": t, "symbol": sym, "ts": ts, "score": sc, "features": json.loads(f or "{}"),
             "sources": set((src or "").split(",")) - {""}, "url": url, "origin": "hype"}
            for t, sym, ts, sc, _p, _l, _m, f, src, url in rows]


def event_tokens(cfg, now=None):
    """Canonical tokens of events from the newest DexScreener scan that are happening in the next event_days."""
    files = sorted(glob.glob(os.path.join(HERE, "output", "dex-2*.json")))
    if not files:
        return []
    with open(files[-1]) as f:
        data = json.load(f)
    today = dt.date.fromtimestamp(now or time.time())
    out = []
    for e in data.get("events", []):
        try:
            days = (dt.date.fromisoformat(e.get("date") or "") - today).days
        except ValueError:
            continue
        if not 0 <= days <= cfg["event_days"]:
            continue
        for t in e.get("tokens", []):
            if t.get("role") == "canonical" and t.get("chain") == "solana":
                out.append({"token": t["token"], "symbol": t.get("symbol"), "ts": now or time.time(),
                            "score": t.get("score"), "features": {}, "sources": {f"event:{e['event'][:40]}"},
                            "url": t.get("url"), "origin": "event", "min_score": cfg["dex_min_score"]})
    return out


def market(tokens):
    """token -> (price, liquidity, mcap, url) from its deepest pair; None if DexScreener failed."""
    try:
        pairs = client.tokens("solana", list(tokens))
    except Exception as e:
        print(f"  dexscreener: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    best = {}
    for p in pairs:
        t, liq = p["baseToken"]["address"], (p.get("liquidity") or {}).get("usd") or 0
        if liq >= best.get(t, (0, -1))[1]:
            best[t] = (float(p.get("priceUsd") or 0), liq, p.get("marketCap") or p.get("fdv") or 0, p.get("url"))
    return best


def rug_verdict(con, mint, cfg, now, paid=True):
    """(verdict, score, flags): a rug report from the last 6 h, else a fresh check while the Helius budget lasts.
    paid=False (exploration entries): only an existing report, no new Helius credits."""
    cal = _ro(RUG_DB)
    if cal is not None:
        try:
            row = cal.execute("SELECT verdict, score, data FROM rug_reports WHERE mint=? AND checked_at>=? "
                              "ORDER BY checked_at DESC LIMIT 1", (mint, now - 6 * 3600)).fetchone()
        except sqlite3.OperationalError:
            row = None
        cal.close()
        if row:
            d = json.loads(row[2] or "{}")
            return row[0], row[1], d.get("hard_fails", []) + d.get("flags", [])
    if not (paid and cfg["rug_check"] and os.environ.get("HELIUS_API_KEY")):
        return None, None, []
    if not store.rug_budget_take(con, _today(now), cfg["rug_budget_per_day"]):
        return "BUDŽET", None, []
    con.commit()
    try:
        from rugfilter.check import check
        import run_rug
        r = check(mint)
        run_rug.save(r)
        try:  # the token reached T2: remember it and what it cost (~525 Helius credits per full check)
            from tiers import store as tstore
            tcon = tstore.connect()
            tstore.reach(tcon, mint, 2, 525, f"rug filter {r['verdict']}", now)
            tcon.commit()
            tcon.close()
        except Exception as e:
            print(f"  token_tier {mint}: {e}", file=sys.stderr)
        return r["verdict"], r.get("score"), r["hard_fails"] + r["flags"]
    except Exception as e:
        print(f"  rug check {mint}: {type(e).__name__}: {e}", file=sys.stderr)
        return None, None, []


def klasa_of(tokens):
    """token -> class from token_tier (hype.db, read-only); event tokens are tagged by the caller."""
    con = _ro(HYPE_DB)
    if con is None or not tokens:
        return {}
    try:
        q = ",".join("?" * len(tokens))
        return dict(con.execute(f"SELECT token, klasa FROM token_tier WHERE token IN ({q}) AND klasa IS NOT NULL",
                                list(tokens)))
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


def kol_calls(tokens, since):
    """token -> newest influencer call timestamp (kol.db, read-only), for the KOL hold in the exit rules."""
    path = os.path.join(HERE, "kol.db")
    con = _ro(path) if os.path.exists(path) and os.path.getsize(path) else None
    if con is None or not tokens:
        return {}
    try:
        q = ",".join("?" * len(tokens))
        return dict(con.execute(f"SELECT token, MAX(ts) FROM calls WHERE kind='call' AND ts>=? AND token IN ({q}) "
                                "GROUP BY token", [since] + list(tokens)))
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


def kol_sells(tokens, since):
    """token -> newest sell by a tracked KOL wallet (kol.db calls kind 'sell', from the Helius webhook)."""
    path = os.path.join(HERE, "kol.db")
    con = _ro(path) if os.path.exists(path) and os.path.getsize(path) else None
    if con is None or not tokens:
        return {}
    try:
        q = ",".join("?" * len(tokens))
        return dict(con.execute(f"SELECT token, MAX(ts) FROM calls WHERE kind='sell' AND ts>=? AND token IN ({q}) "
                                "GROUP BY token", [since] + list(tokens)))
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


def _n_open(con):
    """Open trades that take a core slot; a moonbag (stake already back, small rest riding) and exploration
    trades (own cap, explore.max_open) do not."""
    n = 0
    for state, cfg in con.execute("SELECT state, config FROM trades WHERE status='open'"):
        if not json.loads(state or "{}").get("bag") and json.loads(cfg or "{}").get("entry_mode") not in ("explore", "konv"):
            n += 1
    return n


def explore_need(con, cfg, now):
    """Score an exploration entry needs: the top `top_pct`% of the last 24 h's candidates, never below min_score.
    Relative, so the bot keeps trading (and learning) even when the scores of a whole day are low."""
    ex = cfg.get("explore") or {}
    if not ex.get("enabled"):
        return None
    scores = sorted(s for (s,) in con.execute("SELECT score FROM candidates WHERE first_ts>=? AND origin='hype' "
                                              "AND score IS NOT NULL", (now - 86400,)))
    if len(scores) < 20:
        return max(ex["min_score"], cfg["min_score"] * 0.6)
    pct = scores[min(len(scores) - 1, int(len(scores) * (1 - ex["top_pct"] / 100)))]
    return max(ex["min_score"], pct)


def _n_explore(con, since=None):
    q = ("SELECT COUNT(*) FROM trades WHERE (config LIKE '%\"entry_mode\": \"explore\"%' "
         "OR config LIKE '%\"entry_mode\": \"konv\"%')")
    if since is None:
        return con.execute(q + " AND status='open'").fetchone()[0]
    return con.execute(q + " AND opened_ts>=?", (since,)).fetchone()[0]


def intake(cfg, now=None, quiet=False):
    """Decide every new candidate once; a skipped one is taken later if its hype score climbs over min_score."""
    now = now or time.time()
    con = store.connect(DB)
    seen = {t: d for t, d in con.execute("SELECT token, decision FROM candidates")}
    cands = {}
    for c in event_tokens(cfg, now) + hype_signals(now=now):
        if c["token"] not in seen or (seen[c["token"]] == "skip_score" and c["origin"] == "hype"
                                      and (c["score"] or 0) >= cfg["min_score"]):
            cands[c["token"]] = c
    if not cands:
        return []
    mk = market(cands) or {}
    n_open = _n_open(con)
    klase = klasa_of(cands)
    ex_state = exits_profiles.load()
    day0 = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0).timestamp()
    n_today = con.execute("SELECT COUNT(*) FROM trades WHERE opened_ts>=?", (day0,)).fetchone()[0]
    ex = cfg.get("explore") or {}
    ex_need = explore_need(con, cfg, now)
    ex_open, ex_today = _n_explore(con), _n_explore(con, day0)
    kc = cfg.get("konv") or {}
    try:  # multi-source convergence (X + Telegram + KOL wallets), kol.db read-only
        from kol import store as kstore
        conv = kstore.converge(list(cands), max_age_min=60) if kc.get("enabled") else {}
    except Exception as e:
        print(f"  konvergencija: {e}", file=sys.stderr)
        conv = {}
    arm_st = arms.stats(con, cfg.get("arms"))
    from rugfilter import collapse
    pk = collapse.peaks(HYPE_DB, list(cands), now=now)
    opened = []
    for t, c in sorted(cands.items(), key=lambda kv: -(kv[1]["score"] or 0)):
        if t not in mk:
            continue
        price, liq, mcap, url = mk[t]
        c.update(price=price, liquidity=liq, mcap=mcap, url=c.get("url") or url, ts=now)
        s, need = c["score"] or 0, c.get("min_score", cfg["min_score"])
        # exploration: below the bar but in today's top scores -> small demo trade, so the bot learns faster
        explore = (ex_need is not None and c["origin"] == "hype" and ex_need <= s < need
                   and price > 0 and liq >= ex.get("min_liq", cfg["min_liq"]) and mcap <= cfg["max_mcap"])
        cv = conv.get(t)
        # convergence: several good sources on it in the last minutes -> small early entry, whatever the score
        konv = bool(cv and c["origin"] == "hype" and cv["score"] >= kc.get("min_score", 101) and s < need
                    and now - cv["first_ts"] <= kc.get("max_age_min", 10) * 60 and not cv.get("kol_selling")
                    and price > 0 and liq >= ex.get("min_liq", cfg["min_liq"]) and mcap <= cfg["max_mcap"])
        explore = explore or konv
        if explore and (ex_open >= ex["max_open"] or ex_today >= ex["max_per_day"]):
            explore = konv = False
        arm = arms.arm_of(c, cv, now)
        if explore and not konv:  # Thompson sampling: arms that keep losing get fewer exploration trades
            ok, theta = arms.allow(arm, arm_st, cfg.get("arms"))
            band = arms.band_of(s)
            ok_b, theta_b = arms.allow(band, arm_st, cfg.get("arms"))
            if not ok:
                explore = False
                c["arm_note"] = f"krak {arm} gubi (θ {theta})"
            elif not ok_b:
                explore = False
                c["arm_note"] = f"{band} u istraživanju gubi (θ {theta_b})"
        if explore:
            need = s
        if s < cfg["shadow_min_score"] and c["origin"] == "hype" and not explore:
            c["decision"], c["reason"] = "ignored", f"score {s:.0f}"
        elif price <= 0 or (liq < cfg["min_liq"] and not explore):
            c["decision"], c["reason"] = "skip_liq", f"likvidnost {_usd(liq)}"
        elif mcap > cfg["max_mcap"]:
            c["decision"], c["reason"] = "skip_mcap", f"mcap {_usd(mcap)}"
        elif collapse.check(pk.get(t), mcap, liq):  # already dumped: never enter after the fact
            c["decision"], c["reason"] = "skip_rug", "rugan: " + collapse.check(pk.get(t), mcap, liq)["text"]
        elif s < need:
            c["decision"], c["reason"] = "skip_score", f"score {s:.0f} < {need}" + (
                f"; {c['arm_note']}" if c.get("arm_note") else "")
            if s >= cfg.get("rug_shadow_min_score", 101):  # verdicts on skips too, so the review can judge the filter
                c["rug_verdict"], c["rug_score"], c["rug_flags"] = rug_verdict(con, t, cfg, now)
        elif not explore and (n_open >= cfg["max_open"] or n_today >= cfg["max_entries_per_day"]):
            c["decision"], c["reason"] = "skip_full", f"{n_open} otvorenih, {n_today} danas"
        else:
            c["rug_verdict"], c["rug_score"], c["rug_flags"] = rug_verdict(con, t, cfg, now, paid=not explore)
            if c["rug_verdict"] in cfg["block_verdicts"]:
                c["decision"], c["reason"] = "skip_rug", "; ".join(c["rug_flags"][:3]) or c["rug_verdict"]
            else:
                k = "event" if c["origin"] == "event" else klase.get(t) or "default"
                cfg_t = exits_profiles.for_trade(cfg, k, state=ex_state, now=now)  # learned exits of its class
                cfg_t["entry_mode"] = "konv" if konv else "explore" if explore else "core"
                cfg_t["arm"] = arm
                if konv:  # quick +40% target for most of it, out in 45 min if the crowd does not come
                    cfg_t.update(tp=kc["tp"], stale_min=kc["stale_min"], stale_ret=kc["stale_ret"],
                                 max_hold_h=kc["max_hold_h"])
                size = ex["size_usd"] if explore else cfg["size_usd"]
                c["size_usd"] = size
                pos = sim.open_position(price, liq, now, size, cfg_t)
                c["trade_id"] = store.open_trade(con, t, c.get("symbol"), pos, cfg_t, mcap)
                c["decision"] = "taken"
                c["reason"] = (f"konvergencija {cv['score']:.0f}: {'+'.join(cv['platforms'])}, "
                               f"{cv['n_x']} X / {cv['n_tg']} TG / {cv['n_chain']} novčanika" if konv else
                               f"istraživanje: score {s:.0f} u vrhu dana (prag {ex_need:.0f})" if explore else
                               f"score {s:.0f}") + f" [{arm}]" + (f", rug {c['rug_verdict']}" if c.get("rug_verdict") else "")
                if explore:
                    ex_open, ex_today = ex_open + 1, ex_today + 1
                else:
                    n_open, n_today = n_open + 1, n_today + 1
                opened.append(c)
        if t in seen:  # upgrade of an earlier skip: keep the shadow's original entry, record the trade
            if c["decision"] == "taken":
                con.execute("UPDATE candidates SET decision='taken', reason=?, trade_id=?, rug_verdict=?, "
                            "rug_score=? WHERE token=?", (c["reason"] + " (kasnije)", c["trade_id"],
                                                         c.get("rug_verdict"), c.get("rug_score"), t))
        else:
            store.add_candidate(con, c)
        if c["decision"] != "ignored":
            store.tick(con, t, now, price, liq, mcap)
    con.commit()
    for c in opened:
        msg = (f"📝 DEMO KUPNJA {c.get('symbol')}  {_usd(c.get('size_usd', cfg['size_usd']))} @ {c['price']:.3g}  mcap {_usd(c['mcap'])}"
               f"  liq {_usd(c['liquidity'])}  ({c['reason']})  {c.get('url') or ''}")
        if not quiet:
            print(msg)
        notify(msg)
    return opened


def tick(cfg, now=None, quiet=False):
    """Price every open trade and every candidate still inside track_h; apply exit rules."""
    now = now or time.time()
    con = store.connect(DB)
    trades = store.open_trades(con)
    tracked = {t for (t,) in con.execute("SELECT token FROM candidates WHERE decision!='ignored' AND first_ts>=?",
                                         (now - cfg["track_h"] * 3600,))}
    # a moonbag can ride for days: price it every 10 minutes instead of every minute (fewer ticks on the 1 GB disk)
    bags = {t for _, t, _, pos in trades if pos.get("bag")} - tracked - {t for _, t, _, p in trades if not p.get("bag")}
    asked = set(store.pending_exits(con))  # a hand sale goes through on the next minute, moonbag or not
    if int(now // 60) % 10:
        trades = [x for x in trades if x[1] not in bags or x[0] in asked]
    tokens = tracked | {t for _, t, _, _ in trades}
    con.close()
    if not tokens:
        return []
    mk = market(tokens)
    if mk is None:
        return []
    con = store.connect(DB)
    for t in tokens:
        price, liq, mcap, _ = mk.get(t, (0, 0, 0, None))  # vanished pair = liquidity 0 = rug
        store.tick(con, t, now, price, liq, mcap)
    closed = []
    manual = store.pending_exits(con)  # sales asked for by hand on the Demo trading page
    calls = kol_calls({t for _, t, _, _ in trades}, now - 6 * 3600)
    sells = kol_sells({t for _, t, _, _ in trades}, now - 6 * 3600)
    for tid, t, sym, pos in trades:
        price, liq, mcap, _ = mk.get(t, (0, 0, 0, None))
        cfg_t = {**cfg, **json.loads(con.execute("SELECT config FROM trades WHERE id=?", (tid,)).fetchone()[0])}
        if t in calls:
            pos["kol_until"] = sim.kol_until([calls[t]], now, cfg_t)
        n_fills = len(pos["fills"])
        if (cfg_t.get("entry_mode") == "konv" and (cfg.get("konv") or {}).get("exit_on_kol_sell") and pos["open"]
                and sells.get(t, 0) > pos["opened_ts"] and price > 0):  # a KOL wallet that bought is selling
            sim.sell(pos, pos["left"], price, liq, now, "kol_prodaje", cfg_t)
        for rid, frac in manual.pop(tid, []):
            if pos["open"] and price > 0:
                sim.sell(pos, pos["left"] * frac, price, liq, now, store.MANUAL, cfg_t)
                store.exit_done(con, rid, f"prodano {frac:.0%} ostatka @ {price:.3g}", now)
            elif not pos["open"]:
                store.exit_done(con, rid, "pozicija je već zatvorena", now)
            # price 0 / missing: the request waits for the next tick
        sim.step(pos, price, liq, now, cfg_t)
        for f in pos["fills"][n_fills:]:
            f["mcap"] = mcap
        res = sim.result(pos, price, liq, cfg_t)
        store.save_trade(con, tid, pos, res, mcap)
        for f in pos["fills"][n_fills:]:
            msg = (f"📝 DEMO PRODAJA {sym} {f['frac']:.0%} @ {f['price']:.3g} mcap {_usd(mcap)} ({f['reason']})"
                   + (f"  zatvoreno {res['pnl_usd']:+.2f} USD ({res['ret']:+.0%})" if not pos["open"] else ""))
            if not quiet:
                print(msg)
            notify(msg)
        why = dca.check(pos, price, liq, now, cfg)  # current rules, not the trade's: it is only a suggestion
        if why and dca.log(con, tid, t, sym, pos, price, liq, mcap, now, why, cfg):
            msg = (f"💡 DCA PRIJEDLOG (demo, ne izvršava se) {sym} @ {price:.3g} mcap {_usd(mcap)}: {why}; "
                   f"dokup {_usd(pos['size_usd'] * dca.rules(cfg)['size_frac'])}")
            if not quiet:
                print(msg)
            notify(msg)
        if not pos["open"]:
            closed.append((sym, res))
    for reqs in manual.values():  # requests for trades that are no longer open
        for rid, _ in reqs:
            if not con.execute("SELECT 1 FROM trades WHERE id=(SELECT trade_id FROM manual_exits WHERE id=?) "
                               "AND status='open'", (rid,)).fetchone():
                store.exit_done(con, rid, "pozicija je već zatvorena", now)
    con.commit()
    return closed


def equity(con, cfg, mk=None):
    closed = con.execute("SELECT COALESCE(SUM(pnl_usd),0), COUNT(*) FROM trades WHERE status='closed'").fetchone()
    opened = con.execute("SELECT COALESCE(SUM(pnl_usd),0), COUNT(*) FROM trades WHERE status='open'").fetchone()
    return {"bankroll": cfg["bankroll_usd"], "realized": round(closed[0], 2), "unrealized": round(opened[0], 2),
            "equity": round(cfg["bankroll_usd"] + closed[0] + opened[0], 2), "closed": closed[1], "open": opened[1]}


def cmd_status(a):
    cfg = sim.load_config(a.config)
    con = store.connect(DB)
    e = equity(con, cfg)
    print(f"Demo račun: {_usd(e['equity'])} (start {_usd(e['bankroll'])}, ostvareno {e['realized']:+.2f}, "
          f"otvoreno {e['unrealized']:+.2f}); zatvorenih {e['closed']}, otvorenih {e['open']}\n")
    for tid, t, sym, pos in store.open_trades(con):
        row = con.execute("SELECT pnl_usd, ret, max_ret, entry_mcap FROM trades WHERE id=?", (tid,)).fetchone()
        age = (time.time() - pos["opened_ts"]) / 3600
        print(f"  #{tid:<4} {sym or '?':<12} {age:4.1f} h  PnL {row[0] or 0:+7.2f} USD ({row[1] or 0:+.0%})  "
              f"max {row[2] or 0:+.0%}  ostalo {pos['left']:.0%}  ulaz mcap {_usd(row[3])}  {t}")
    n = con.execute("SELECT decision, COUNT(*) FROM candidates GROUP BY decision").fetchall()
    print(f"\nKandidati: {dict(n)}")


def cmd_tick(a):
    cfg = sim.load_config(a.config)
    intake(cfg)
    closed = tick(cfg)
    print(f"tick gotov, zatvoreno {len(closed)}")


def cmd_review(a):
    cfg = sim.load_config(a.config)
    con = store.connect(DB)
    rep = review.run(con, cfg, hours=a.hours, now=time.time())
    e = equity(con, cfg)
    rep["equity"] = e
    if not a.config:  # learned rules only for the real config, not a test file
        try:
            from exits import learn as exits_learn
            exl = bool(exits_learn.load_config().get("enabled"))
        except Exception:
            exl = False
        try:
            rows = review.load(con, cfg, time.time() - review.LEARN_DAYS * 86400)
            rep["auto"] = auto.apply(rep, cfg, rows, exits_learned=exl)
        except Exception as ex:
            print(f"auto primjena nije uspjela: {type(ex).__name__}: {ex}", file=sys.stderr)
            rep["auto"] = []
    paths = review.write(rep, OUT, SUGGESTED, cfg)
    print(open(paths["md"]).read())
    con = store.connect(DB)
    con.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?)", (rep["day"], int(time.time()), json.dumps(rep)))
    n = store.prune_ticks(con, cfg.get("ticks_keep_days", 30))
    con.commit()
    if n:
        print(f"obrisano {n} starih cijena (starije od {cfg.get('ticks_keep_days', 30)} dana)")
    notify(review.telegram_summary(rep), telegram=a.telegram)
    return rep


def cmd_apply(a):
    if not os.path.exists(SUGGESTED):
        print("Nema prijedloga (paper/config.suggested.json). Pokreni `review`.")
        return
    with open(SUGGESTED) as f:
        sug = json.load(f)
    cfg = sim.load_config()
    changes = {k: v for k, v in sug.items() if cfg.get(k) != v}
    if not changes:
        print("Prijedlog je isti kao trenutna konfiguracija.")
        return
    backup = sim.CONFIG_PATH.replace(".json", f".{_today()}.bak.json")
    shutil.copy(sim.CONFIG_PATH, backup)
    cfg.update(changes)
    with open(sim.CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    print(f"Primijenjeno: {changes}\nStara konfiguracija: {backup}")


def cmd_run(a):
    last_scan = last_review = 0
    hype_args = ["scan", "--top", "0"] + (a.hype_args.split() if a.hype_args else [])
    while True:
        cfg = sim.load_config(a.config)  # re-read each loop, so `apply` takes effect without a restart
        now = time.time()
        try:
            if a.scan and now - last_scan >= a.scan_every:
                import run_hype
                run_hype.main(hype_args)
                last_scan = now
            intake(cfg)
            closed = tick(cfg)
            con = store.connect(DB)
            e = equity(con, cfg)
            print(f"{dt.datetime.now():%H:%M:%S}  demo {_usd(e['equity'])}  otvorenih {e['open']}  "
                  f"zatvoreno sad {len(closed)}")
            hh, mm = map(int, a.review_at.split(":"))
            due = dt.datetime.now().replace(hour=hh, minute=mm, second=0).timestamp()
            done = con.execute("SELECT 1 FROM reviews WHERE day=?", (_today(),)).fetchone()
            con.close()
            if now >= due and not done and now - last_review > 3600:
                last_review = now
                cmd_review(argparse.Namespace(config=a.config, hours=24, telegram=False))
        except Exception as e:
            print(f"greška u prolazu: {type(e).__name__}: {e}", file=sys.stderr)
        from ops import mem
        mem.trim()   # give this round's memory back before sleeping
        time.sleep(a.interval)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="strategy JSON, default paper/config.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--interval", type=int, default=60, help="seconds between price checks")
    r.add_argument("--scan", action="store_true", help="also run the hype scan here (then don't run hype watch)")
    r.add_argument("--scan-every", type=int, default=120)
    r.add_argument("--hype-args", help='extra args for run_hype.py scan, e.g. "--min-liq 8000"')
    r.add_argument("--review-at", default="08:00", help="local time of the daily review")
    sub.add_parser("tick")
    sub.add_parser("status")
    v = sub.add_parser("review")
    v.add_argument("--hours", type=float, default=24)
    v.add_argument("--telegram", action="store_true", help="also send the summary to Telegram")
    sub.add_parser("apply")
    a = p.parse_args(argv)
    {"run": cmd_run, "tick": cmd_tick, "status": cmd_status, "review": cmd_review, "apply": cmd_apply}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
