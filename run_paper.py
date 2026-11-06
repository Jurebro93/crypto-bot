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
from paper import auto, dca, review, sim, store, arms, rules, liga, aktivni

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "paper.db")  # own file, see run_hype.DB
HYPE_DB = os.path.join(HERE, "hype.db")
RUG_DB = os.environ.get("RUG_DB", os.path.join(HERE, "rug.db"))
OUT = os.path.join(HERE, "output", "paper")
SUGGESTED = os.path.join(HERE, "paper", "config.suggested.json")



def _over(n, cap):
    """Demo caps: None (or 0) means no cap. Nicholas 2.11.: demo is paper money, so there is no daily limit on
    entries; every opportunity in the afternoon and evening is traded too, so the bot learns from all of them.
    Only the number of positions open at once keeps a high safety cap (price checks per minute)."""
    return bool(cap) and n >= cap

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


def t0_of(tokens, col="t0"):
    """token -> T0 verdict from token_tier (hype.db, read-only): 'prolaz' / 'pad' / 'nije'; missing = no row.
    col="symbol" gives the ticker instead."""
    con = _ro(HYPE_DB)
    if con is None or not tokens:
        return {}
    try:
        q = ",".join("?" * len(tokens))
        return dict(con.execute(f"SELECT token, {col} FROM token_tier WHERE token IN ({q})", list(tokens)))
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


_T0_CACHE = {}


def t0_check(token, now):
    """Free T0 check (RugCheck, cached 6 h) for a mint the scan never checked, e.g. a non-pump.fun token that came in
    through a KOL trigger. Returns 'prolaz' / 'pad' / None (failed)."""
    hit = _T0_CACHE.get(token)
    if hit and now - hit[1] < 6 * 3600:
        return hit[0]
    try:
        from tiers import sieve
        t0, _why = sieve.check(token)
    except Exception as e:  # noqa: BLE001
        print(f"  T0 {token}: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    if len(_T0_CACHE) > 500:
        _T0_CACHE.clear()
    _T0_CACHE[token] = (t0, now)
    return t0


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
        if not json.loads(state or "{}").get("bag") and json.loads(cfg or "{}").get("entry_mode") not in (
                "explore", "konv", "mc100k", "mc100k2", "kol3"):
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


_MODEL_NEED = {"ts": 0, "p": None}


def _model_p(mdl, c, now):
    from learn import champion
    try:
        return champion.candidate_p(mdl, c, now)
    except Exception:  # noqa: BLE001 - a broken model must never stop the demo
        return 0.0


def model_need(con, cfg, now):
    """(model, p a candidate needs) when the learned model is champion: the same top `top_pct`% of the last 24 h's
    candidates as explore_need, measured in model probability. Cached 10 min. (None, None) otherwise."""
    from learn import champion
    ex = cfg.get("explore") or {}
    try:
        mdl = champion.live(now)
    except Exception:  # noqa: BLE001
        mdl = None
    if mdl is None or not ex.get("enabled"):
        return None, None
    if now - _MODEL_NEED["ts"] > 600 or _MODEL_NEED["p"] is None:
        ps = []
        for feats, score, mcap, liq in con.execute("SELECT features, score, mcap, liquidity FROM candidates WHERE first_ts>=? "
                                                   "AND origin='hype'", (now - 86400,)):
            c = {"features": json.loads(feats or "{}"), "score": score, "mcap": mcap, "liquidity": liq}
            ps.append(_model_p(mdl, c, now))
        ps.sort()
        _MODEL_NEED.update(ts=now, p=ps[min(len(ps) - 1, int(len(ps) * (1 - ex["top_pct"] / 100)))] if len(ps) >= 20 else None)
    return mdl, _MODEL_NEED["p"]


def _n_explore(con, since=None):
    q = ("SELECT COUNT(*) FROM trades WHERE (config LIKE '%\"entry_mode\": \"explore\"%' "
         "OR config LIKE '%\"entry_mode\": \"konv\"%')")
    if since is None:
        return con.execute(q + " AND status='open'").fetchone()[0]
    return con.execute(q + " AND opened_ts>=?", (since,)).fetchone()[0]


def konv_now(tokens, now):
    """{token: convergence} for these tokens: kol.db's stored copy (refreshed each run_kol round) overlaid with a live
    computation from kol.db / tg.db / hype.db (read-only), so a cluster that formed in the last minutes counts now."""
    if not tokens:
        return {}
    out = {}
    try:
        from kol import store as kstore
        out = kstore.converge(list(tokens), max_age_min=60)
    except Exception as e:  # noqa: BLE001
        print(f"  konvergencija: {e}", file=sys.stderr)
    try:
        from kol import converge
        with open(os.path.join(HERE, "kol", "config.json")) as f:
            kcfg = json.load(f)
        live = converge.compute(now=int(now), cfg=kcfg.get("converge"), good=kcfg.get("good_score", 50))
        out.update({t: v for t, v in live.items() if t in tokens})
    except Exception as e:  # noqa: BLE001
        print(f"  konvergencija (live): {type(e).__name__}: {e}", file=sys.stderr)
    return out


def konv_fresh(cv, kc, now):
    """Strong enough, still happening (newest call/buy within max_age_min), the whole cluster within window_min of
    its first event (not a slow drip over hours), and no tracked wallet selling."""
    if not cv or cv.get("kol_selling") or cv.get("score", 0) < kc.get("min_score", 101):
        return False
    if not (cv.get("n_x") or cv.get("n_tg")) and (cv.get("n_chain") or 0) < kc.get("chain_only_min", 6):
        return False  # wallets only, not one post: 1.11. night 11 such entries ended at -100% (fake pools)
    last = cv.get("last_ts") or cv.get("ts") or cv.get("first_ts") or 0
    return (now - last <= kc.get("max_age_min", 10) * 60
            and now - (cv.get("first_ts") or last) <= kc.get("window_min", 30) * 60)


def _announce(opened, cfg, quiet):
    for c in opened:
        msg = (f"📝 DEMO KUPNJA {c.get('symbol')}  {_usd(c.get('size_usd', cfg['size_usd']))} @ {c['price']:.3g}  mcap {_usd(c['mcap'])}"
               f"  liq {_usd(c['liquidity'])}  ({c['reason']})  {c.get('url') or ''}")
        if not quiet:
            print(msg)
        notify(msg)


TRIGGER_MODES = ("mc100k", "mc100k2", "kol3", "aktivni", "povratak", "povlacenje")


def _n_mode(con, mode, since=None):
    q = f"SELECT COUNT(*) FROM trades WHERE config LIKE '%\"entry_mode\": \"{mode}\"%'"
    if since is None:
        return con.execute(q + " AND status='open'").fetchone()[0]
    return con.execute(q + " AND opened_ts>=?", (since,)).fetchone()[0]


def reentries(con, band, now, dip=0.8):
    """{token: {low, closed_ts}}: tokens whose $100k demo trade (mc100k) closed in the last 24 h, that fell under
    dip x band after the exit and are crossing band again right now (last tick at/above, the one before below).
    1.11. 'pairless': entry at $116k, out at +16% in 8 min, fell to ~$73k, then went past $1M; a person in the
    competition bought the dip. One re-entry per token (mode mc100k2), measured as its own arm."""
    out = {}
    rows = con.execute("SELECT token, MAX(closed_ts) FROM trades WHERE status='closed' AND closed_ts>=? AND "
                       "config LIKE '%\"entry_mode\": \"mc100k\"%' GROUP BY token", (now - 86400,)).fetchall()
    for tok, closed in rows:
        if con.execute("SELECT 1 FROM trades WHERE token=? AND (status='open' OR config LIKE "
                       "'%\"entry_mode\": \"mc100k2\"%')", (tok,)).fetchone():
            continue
        low = con.execute("SELECT MIN(mcap) FROM ticks WHERE token=? AND ts>? AND mcap>0", (tok, closed)).fetchone()[0]
        last = con.execute("SELECT mcap FROM ticks WHERE token=? AND ts>? ORDER BY ts DESC LIMIT 2",
                           (tok, closed)).fetchall()
        if low and low <= dip * band and len(last) == 2 and (last[0][0] or 0) >= band > (last[1][0] or 0):
            out[tok] = {"low": low, "closed_ts": closed}
    return out


def comebacks(con, r, now, hype_db=None):
    """{token: info} for the "povratak" trigger: tokens whose demo trade closed with a loss (ret <= r.lost) in the
    last r.days days, no open trade, cooldown passed, fewer than max_per_token comebacks so far, that are alive
    again NOW: a hype signal in the last fresh_min minutes with turnover >= min_turnover, and in the last buyers_min
    minutes either smart wallets among the buyers (feature smart_money) or a tracked KOL / copy wallet buying
    (hype.db chain_trades). A token that fell 90% is not finished when the money comes back (Nicholas 4.11.)."""
    out = {}
    rows = con.execute("SELECT token, MAX(closed_ts), MIN(ret) FROM trades WHERE status='closed' AND closed_ts>=? "
                       "GROUP BY token", (now - r["days"] * 86400,)).fetchall()
    lost = {t: (closed, ret) for t, closed, ret in rows if ret is not None and ret <= r["lost"]}
    if not lost:
        return out
    fresh = {c["token"]: c for c in hype_signals(r["fresh_min"], now)}
    hc = _ro(hype_db or HYPE_DB)
    try:
        for tok, (closed, ret) in lost.items():
            if tok not in fresh or now - closed < r["cooldown_min"] * 60:
                continue
            if con.execute("SELECT 1 FROM trades WHERE token=? AND status='open'", (tok,)).fetchone():
                continue
            n_back = con.execute("SELECT COUNT(*) FROM trades WHERE token=? AND config LIKE "
                                 "'%\"entry_mode\": \"povratak\"%'", (tok,)).fetchone()[0]
            if n_back >= r["max_per_token"]:
                continue
            c = fresh[tok]
            f = c.get("features") or {}
            turnover = f.get("turnover") or 0
            buyers = 0
            if hc is not None:
                try:
                    buyers = hc.execute("SELECT COUNT(DISTINCT wallet) FROM chain_trades WHERE mint=? AND side='buy' "
                                        "AND ts>=?", (tok, now - r["buyers_min"] * 60)).fetchone()[0]
                except sqlite3.OperationalError:
                    buyers = 0
            smart = f.get("smart_money") or 0
            if turnover < r["min_turnover"] or not (smart > 0 or buyers > 0):
                continue
            out[tok] = {"score": c.get("score"), "symbol": c.get("symbol"), "features": f, "ret": ret,
                        "closed_ts": closed, "buyers": buyers, "smart": smart, "turnover": turnover, "n_back": n_back}
    finally:
        if hc is not None:
            hc.close()
    return out


def pullbacks(con, r, now, hype_db=None, kol_db=None):
    """{token: info} for the "povlacenje" trigger: a token signalled in the last r.fresh_min minutes whose price now
    is r.pullback or more below its high since the first signal (hype_snapshots), still worth >= r.min_mcap, with a
    followed wallet buying in the last r.buyers_min minutes (chain_trades / live_trades, wallets of the Helius
    webhook list). No open trade, at most r.max_per_token such entries per token."""
    out = {}
    hc = _ro(hype_db or HYPE_DB)
    if hc is None:
        return out
    try:   # newest signal per token with its price and mcap (hype_signals() drops those)
        fresh = {t: {"token": t, "symbol": sym, "ts": ts, "score": sc, "price": px, "mcap": mc,
                     "features": json.loads(f or "{}")}
                 for t, sym, ts, sc, px, mc, f in hc.execute(
                     "SELECT s.token, s.symbol, s.ts, s.score, s.price, s.mcap, s.features FROM hype_signals s JOIN "
                     "(SELECT token, MAX(ts) ts FROM hype_signals WHERE ts >= ? GROUP BY token) l ON s.token = l.token AND s.ts = l.ts",
                     (now - r["fresh_min"] * 60,))}
    except (sqlite3.OperationalError, ValueError):
        fresh = {}
    if not fresh:
        hc.close()
        return out
    followed = set()
    kc = _ro(kol_db or os.path.join(HERE, "kol.db"))
    if kc is not None:
        try:
            row = kc.execute("SELECT value FROM kv WHERE key='chain_hook'").fetchone()
            followed = set((json.loads(row[0]).get("wallets") or []) if row else [])
        except (sqlite3.OperationalError, ValueError):
            followed = set()
        finally:
            kc.close()
    try:
        for tok, c in fresh.items():
            if (c.get("mcap") or 0) < r["min_mcap"] or not c.get("price"):
                continue
            if con.execute("SELECT 1 FROM trades WHERE token=? AND status='open'", (tok,)).fetchone():
                continue
            n_pb = con.execute("SELECT COUNT(*) FROM trades WHERE token=? AND config LIKE '%\"entry_mode\": \"povlacenje\"%'",
                               (tok,)).fetchone()[0]
            if n_pb >= r["max_per_token"]:
                continue
            try:
                # the high-water mark over the whole fresh window (the peak is usually before the newest signal)
                high = hc.execute("SELECT MAX(price) FROM hype_snapshots WHERE token=? AND ts>=? AND ts<=?",
                                  (tok, now - r["fresh_min"] * 60, now)).fetchone()[0]
            except sqlite3.OperationalError:
                high = None
            high = max(high or 0, c["price"])
            if not high or c["price"] / high - 1 > r["pullback"]:
                continue
            buyers = set()
            for table in ("chain_trades", "live_trades"):
                try:
                    for (w,) in hc.execute(f"SELECT DISTINCT wallet FROM {table} WHERE mint=? AND side='buy' AND ts>=?",
                                           (tok, now - r["buyers_min"] * 60)):
                        if not followed or w in followed:
                            buyers.add(w)
                except sqlite3.OperationalError:
                    continue
            if not buyers:
                continue
            out[tok] = {"score": c.get("score"), "symbol": c.get("symbol"), "features": c.get("features") or {},
                        "high": high, "drop": c["price"] / high - 1, "buyers": len(buyers), "mcap": c.get("mcap")}
    finally:
        hc.close()
    return out


def trigger_entries(con, cfg, rst, now):
    """Entries that do not come from a hype score (paper/rules.py): B of the entry A/B = first crossing of $100k MC
    with T0 passed, and >= 3 different KOL authors within 15 minutes. Same hard rug gate, same session stake, own
    small caps; one trade per token a day. Returns the opened candidates."""
    R = rules.config(cfg)
    R["aktivni"] = aktivni.config(cfg)
    if not (R["ab"]["enabled"] or R["kol3"]["enabled"] or R["aktivni"]["enabled"] or R["povratak"]["enabled"]
            or R.get("povlacenje", {}).get("enabled")):
        return []
    from exits.paths import session_of
    from rugfilter import collapse
    want = {}
    if R["ab"]["enabled"]:
        if now - (rst.get("ab") or {}).get("ts", 0) >= 3600:
            rules.ab_judge(con, rst, cfg, now)
        for tok, ts, mc, px, sc in rules.ab_events(HYPE_DB, R["ab"]["band"], R["ab"]["fresh_min"], now):
            want.setdefault(tok, ("mc100k", {"score": sc, "mcap_cross": mc}))
    tight = {}
    if R["kol3"]["enabled"]:
        for tok, k in rules.kol3(os.path.join(HERE, "kol.db"), now, cfg).items():
            want.setdefault(tok, ("kol3", k))
        # 5.11.: were the 3+ authors within 10 minutes? Stored on the trade (grupa10) so the two can be compared
        tight = rules.kol3(os.path.join(HERE, "kol.db"), now, cfg, window_min=10) if want else {}
    if R["aktivni"]["enabled"]:  # older tokens with the most buys and sells today (paper/aktivni.py)
        for tok, k in aktivni.wanted(cfg, now).items():
            want.setdefault(tok, ("aktivni", k))
    traded = {t for (t,) in con.execute("SELECT token FROM trades WHERE status='open' OR opened_ts>=?",
                                        (now - 86400,))}
    from rugfilter import archive
    gone = archive.blocked(HYPE_DB)   # rugged earlier and archived: no entry, no market lookup
    want = {t: v for t, v in want.items() if t not in traded and t not in gone}
    if R["ab"]["enabled"] and R["ab"].get("reentry", True):
        for tok, info in reentries(con, R["ab"]["band"], now).items():
            if tok not in gone:
                want.setdefault(tok, ("mc100k2", info))
    if R["povratak"]["enabled"]:   # after the 24 h "traded" filter on purpose: a comeback is a second trade
        for tok, info in comebacks(con, R["povratak"], now).items():
            if tok not in gone:
                want.setdefault(tok, ("povratak", info))
    if R.get("povlacenje", {}).get("enabled"):   # 5.11.: a dip with proof (a followed wallet buying it), never into a tiny cap
        for tok, info in pullbacks(con, R["povlacenje"], now).items():
            if tok not in gone and tok not in traded:
                want.setdefault(tok, ("povlacenje", info))
    if not want:
        return []
    mk = market(want) or {}
    t0s = t0_of(want)
    syms = t0_of(want, "symbol")
    klase = klasa_of(want)
    pk = collapse.peaks(HYPE_DB, list(want), now=now)
    known_c = store.known(con)
    ex_state = exits_profiles.load()
    day0 = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0).timestamp()
    cnt = {m: [_n_mode(con, m), _n_mode(con, m, day0)] for m in TRIGGER_MODES}
    act = {t for t, (m, _) in want.items() if m == "aktivni"}
    live_act = aktivni.live_pairs(act) if act else {}
    arm_st = arms.stats(con, cfg.get("arms"))
    kc = cfg.get("konv") or {}
    t0_left = R["gate"]["t0_checks_per_pass"]
    sess = session_of(now)
    out = []
    for tok, (mode, info) in want.items():
        if tok not in mk:
            continue
        r = R["ab" if mode in ("mc100k", "mc100k2") else mode]
        if _over(cnt[mode][0], r.get("max_open")) or _over(cnt[mode][1], r.get("max_per_day")):
            continue
        price, liq, mcap, url = mk[tok]
        # aktivni: still trading now and not mid-pump; checked before the T0 lookup so a dead token costs nothing
        pre = aktivni.live_check(live_act.get(tok), r) if mode == "aktivni" else None
        t0 = t0s.get(tok)
        if not pre and t0 in (None, "nije") and not (t0 is None and rules.is_pump(tok)) and t0_left > 0:
            t0_left -= 1
            t0 = t0_check(tok, now) or t0
        c = {"token": tok, "symbol": syms.get(tok) or info.get("symbol"), "ts": now, "origin": mode, "sources": {mode},
             "score": info.get("score"), "features": info.get("features") or {}, "price": price, "liquidity": liq,
             "mcap": mcap, "url": url}
        why = pre or rules.gate(tok, price, liq, mcap, t0, None, cfg)
        if not why and mode not in ("mc100k2", "povratak", "povlacenje"):  # market-cap band that keeps losing gets fewer entries (paper/arms.py)
            band = arms.mc_band(mcap)
            ok_b, theta_b = arms.allow(band, arm_st, cfg.get("arms"))
            if not ok_b:
                why = f"{band} gubi (θ {theta_b})"
        if not why and collapse.check(pk.get(tok), mcap, liq):
            why = "rugan: " + collapse.check(pk.get(tok), mcap, liq)["text"]
        size, note = rules.size_for(rst, tok, r["size_usd"], now, cfg)
        if why:
            c["decision"], c["reason"] = "skip_gate", why
        elif mode == "mc100k" and not rules.ab_allow(rst, mode, tok, cfg):
            c["decision"], c["reason"] = "skip_ab", "A/B: uobičajeni ulaz se pokazao boljim od čekanja 100k $"
        elif mode == "kol3" and not rules.kol3_allow(con, tok, now, cfg):
            c["decision"], c["reason"] = "skip_sesija", "okidač 3 KOL-a u ovoj sesiji gubi"
        elif size <= 0:
            c["decision"], c["reason"] = "skip_sesija", note
        else:
            c["rug_verdict"], c["rug_score"], c["rug_flags"] = rug_verdict(con, tok, cfg, now, paid=False)
            if c["rug_verdict"] in cfg["block_verdicts"]:
                c["decision"], c["reason"] = "skip_rug", "; ".join(c["rug_flags"][:3]) or c["rug_verdict"]
        if not c.get("decision"):
            size = rules.high_risk_size(c.get("rug_verdict"), size, r["size_usd"])
            cfg_t = exits_profiles.for_trade(cfg, klase.get(tok) or "default", state=ex_state, now=now)
            cfg_t["entry_mode"], cfg_t["arm"] = mode, f"{mode}|{sess}"
            if mode == "kol3":
                cfg_t["grupa10"] = tok in tight
            liga.flag(con, cfg_t, cfg, now)  # counts in the league round only if this kind of trade proved itself
            if mode == "kol3" and kc.get("tp"):  # a KOL wave: quick target, out if the crowd does not come
                cfg_t.update(tp=kc["tp"], stale_min=kc["stale_min"], stale_ret=kc["stale_ret"],
                             max_hold_h=kc["max_hold_h"])
            pos = sim.open_position(price, liq, now, size, cfg_t)
            c["trade_id"] = store.open_trade(con, tok, c["symbol"], pos, cfg_t, mcap)
            c["size_usd"], c["decision"] = size, "taken"
            c["reason"] = ((f"prvi prelazak 100k $ (A/B test, ulaz B)" if mode == "mc100k" else
                            f"ponovni prelazak 100k $ nakon pada na {_usd(info['low'])}" if mode == "mc100k2" else
                            f"povratak nakon gubitka {info['ret']:+.0%}: promet {info['turnover']:.0%}, "
                            f"{info['buyers']} praćenih novčanika kupuje, smart {info['smart']:.0%}" if mode == "povratak" else
                            f"povlačenje {info['drop']:+.0%} od vrha uz dokaz: {info['buyers']} praćenih novčanika kupuje, "
                            f"mcap {_usd(info['mcap'])}" if mode == "povlacenje" else
                            f"aktivan stariji token: {info['tx24']:,} kupnji i prodaja u 24 h, star "
                            f"{info.get('age_d') or 0:.0f} dana".replace(",", ".") if mode == "aktivni" else
                            f"{info['n']} KOL autora u " + ("10" if tok in tight else "15") + " min: "
                            + ", ".join(info["handles"][:5]))
                           + f" [{cfg_t['arm']}]" + (f", rug {c['rug_verdict']}" if c.get("rug_verdict") else "")
                           + (f"; {note}" if note else ""))
            cnt[mode][0] += 1
            cnt[mode][1] += 1
            out.append(c)
        if tok in known_c:
            if c["decision"] == "taken":
                con.execute("UPDATE candidates SET trade_id=? WHERE token=? AND trade_id IS NULL", (c["trade_id"], tok))
        else:
            store.add_candidate(con, c)
            known_c.add(tok)
        store.add_trigger_point(con, c, mode)   # every look, taken or not: a shadow point (learn/shadow.py)
        store.tick(con, tok, now, price, liq, mcap)
    return out


RETRY_DECISIONS = ("skip_score", "skip_liq", "skip_mcap", "ignored")   # earlier verdicts a better score can overturn


def reconsider(decision, c, cfg):
    """A token decided earlier gets a new look when it is a hype candidate whose score now clears min_score and the
    old verdict was one a better score can overturn (not taken, not rug, not gate)."""
    return decision in RETRY_DECISIONS and c["origin"] == "hype" and (c["score"] or 0) >= cfg["min_score"]


def intake(cfg, now=None, quiet=False):
    """Decide every new candidate once; a skipped one is taken later if its hype score climbs over min_score."""
    now = now or time.time()
    con = store.connect(DB)
    seen = {t: d for t, d in con.execute("SELECT token, decision FROM candidates")}
    cands = {}
    sigs = event_tokens(cfg, now) + hype_signals(now=now)
    for c in sigs:
        # a token decided once is looked at again only when its hype score now clears the bar; until 4.11. only an
        # earlier "skip_score" qualified, so a token first seen with a thin pool ("skip_liq") or a tiny score
        # ("ignored") could later score 60 with a $45k pool and never be considered (AMD 55.7 in the scan, no entry)
        if c["token"] not in seen or reconsider(seen[c["token"]], c, cfg):
            cands[c["token"]] = c
    kc = cfg.get("konv") or {}
    conv = {}
    if kc.get("enabled"):
        # Convergence builds up over minutes (one KOL wallet buys, then a second, then a Telegram call), so a token
        # that was skipped when it first showed up is looked at again once its convergence is strong now. Computed
        # live here: kol.db's stored copy is refreshed only every 20-45 min (run_kol round), far too late for a
        # 10-minute entry window (31.10.: 68 convergence tokens at 17:21, 0 convergence trades all day).
        again = {c["token"]: c for c in sigs if c["origin"] == "hype" and c["token"] in seen
                 and c["token"] not in cands and seen[c["token"]] in ("skip_score", "ignored", "skip_liq")}
        conv = konv_now(set(cands) | set(again), now)
        for t, c in again.items():
            if konv_fresh(conv.get(t), kc, now):
                cands[t] = c
    if not cands:
        rst = rules.load()
        opened = trigger_entries(con, cfg, rst, now)
        rules.save(rst)
        con.commit()
        _announce(opened, cfg, quiet)
        return opened
    mk = market(cands) or {}
    n_open = _n_open(con)
    klase = klasa_of(cands)
    ex_state = exits_profiles.load()
    day0 = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0).timestamp()
    n_today = con.execute("SELECT COUNT(*) FROM trades WHERE opened_ts>=?", (day0,)).fetchone()[0]
    ex = cfg.get("explore") or {}
    ex_need = explore_need(con, cfg, now)
    mdl, p_need = model_need(con, cfg, now)
    ex_open, ex_today = _n_explore(con), _n_explore(con, day0)
    arm_st = arms.stats(con, cfg.get("arms"))
    from rugfilter import archive, collapse
    pk = collapse.peaks(HYPE_DB, list(cands), now=now)
    archived = archive.blocked(HYPE_DB)
    t0s = t0_of(cands)
    rst = rules.load()
    rules.since(rst, "gate", now)
    rules.session_sizes(con, rst, cfg, now)
    t0_left = rules.config(cfg)["gate"]["t0_checks_per_pass"]
    opened = []
    # strong convergence first: when the exploration slots are nearly full, KOL/wallet clusters get them first
    for t, c in sorted(cands.items(), key=lambda kv: (not konv_fresh(conv.get(kv[0]), kc, now), -(kv[1]["score"] or 0))):
        if t not in mk:
            continue
        price, liq, mcap, url = mk[t]
        c.update(price=price, liquidity=liq, mcap=mcap, url=c.get("url") or url, ts=now)
        s, need = c["score"] or 0, c.get("min_score", cfg["min_score"])
        # exploration: below the bar but in today's top scores -> small demo trade, so the bot learns faster
        explore = (ex_need is not None and c["origin"] == "hype" and ex_need <= s < need
                   and price > 0 and liq >= ex.get("min_liq", cfg["min_liq"]) and mcap <= cfg["max_mcap"])
        if mdl is not None and p_need is not None and c["origin"] == "hype":
            # the learned model passed its trial (learn/champion.py): it, not the score percentile, picks exploration
            c["model_p"] = round(_model_p(mdl, c, now), 4)
            explore = (c["model_p"] >= p_need and s < need and price > 0
                       and liq >= ex.get("min_liq", cfg["min_liq"]) and mcap <= cfg["max_mcap"])
        cv = conv.get(t)
        # convergence: several good sources on it in the last minutes -> small early entry, whatever the score
        konv = bool(c["origin"] == "hype" and konv_fresh(cv, kc, now) and s < need
                    and price > 0 and liq >= ex.get("min_liq", cfg["min_liq"]) and mcap <= cfg["max_mcap"])
        explore = explore or konv
        if explore and (_over(ex_open, ex.get("max_open")) or _over(ex_today, ex.get("max_per_day"))):
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
            else:  # market-cap band (Nicholas 4.11.): a band that keeps losing gets fewer entries
                mb = arms.mc_band(mcap)
                ok_m, theta_m = arms.allow(mb, arm_st, cfg.get("arms"))
                if not ok_m:
                    explore = False
                    c["arm_note"] = f"{mb} gubi (θ {theta_m})"
        if explore:
            need = s
        if s < cfg["shadow_min_score"] and c["origin"] == "hype" and not explore:
            c["decision"], c["reason"] = "ignored", f"score {s:.0f}"
        elif price <= 0 or (liq < cfg["min_liq"] and not explore):
            c["decision"], c["reason"] = "skip_liq", f"likvidnost {_usd(liq)}"
        elif mcap > cfg["max_mcap"]:
            c["decision"], c["reason"] = "skip_mcap", f"mcap {_usd(mcap)}"
        elif t in archived:  # rugged earlier and archived (rugfilter/archive.py)
            c["decision"], c["reason"] = "skip_rug", "rugan ranije, izbačen iz praćenja"
        elif collapse.check(pk.get(t), mcap, liq):  # already dumped: never enter after the fact
            c["decision"], c["reason"] = "skip_rug", "rugan: " + collapse.check(pk.get(t), mcap, liq)["text"]
        elif s < need:
            c["decision"], c["reason"] = "skip_score", f"score {s:.0f} < {need}" + (
                f"; {c['arm_note']}" if c.get("arm_note") else "")
            if s >= cfg.get("rug_shadow_min_score", 101):  # verdicts on skips too, so the review can judge the filter
                c["rug_verdict"], c["rug_score"], c["rug_flags"] = rug_verdict(con, t, cfg, now)
        elif not explore and (_over(n_open, cfg.get("max_open")) or _over(n_today, cfg.get("max_entries_per_day"))):
            c["decision"], c["reason"] = "skip_full", f"{n_open} otvorenih, {n_today} danas"
        else:
            t0 = t0s.get(t)
            if t0 in (None, "nije") and not (t0 is None and rules.is_pump(t)) and t0_left > 0:
                t0_left -= 1  # never checked (non-pump.fun mint, or outside the scan): the free check first
                t0 = t0_check(t, now) or t0
            gate = rules.gate(t, price, liq, mcap, t0, c.get("features"), cfg)
            mode = "konv" if konv else "explore" if explore else "core"
            size = ex["size_usd"] if explore else cfg["size_usd"]
            ex_size = ex.get("size_usd", cfg["size_usd"])
            size_note = None
            if not gate:
                size, size_note = rules.size_for(rst, t, size, now, cfg)
                if explore and not konv and c.get("model_p") and p_need:
                    # stake by the model's chance (learn/champion.py): twice the bar = twice the stake, capped 0.5x-2x
                    mult = max(0.5, min(2.0, c["model_p"] / p_need))
                    size = round(size * mult, 2)
                    size_note = ((size_note + "; ") if size_note else "") + f"ulog ×{mult:.1f} po šansi modela"
            if gate:
                c["decision"], c["reason"] = "skip_gate", gate
            elif mode != "konv" and (mcap or 0) < rules.config(cfg)["ab"]["band"] and not rules.ab_allow(rst, mode, t, cfg):
                c["decision"], c["reason"] = "skip_ab", "A/B: ulaz na prvom prelasku 100k $ se pokazao boljim"
            elif size <= 0:
                c["decision"], c["reason"] = "skip_sesija", size_note
            else:
                c["rug_verdict"], c["rug_score"], c["rug_flags"] = rug_verdict(con, t, cfg, now, paid=not explore)
            if c.get("decision"):
                pass
            elif c["rug_verdict"] in cfg["block_verdicts"]:
                c["decision"], c["reason"] = "skip_rug", "; ".join(c["rug_flags"][:3]) or c["rug_verdict"]
            else:
                k = "event" if c["origin"] == "event" else klase.get(t) or "default"
                cfg_t = exits_profiles.for_trade(cfg, k, state=ex_state, now=now)  # learned exits of its class
                cfg_t["entry_mode"] = mode
                cfg_t["arm"] = arm
                liga.flag(con, cfg_t, cfg, now)  # league round 2: only proven kinds of trades count (paper/liga.py)
                if konv:  # quick +40% target for most of it, out in 45 min if the crowd does not come
                    cfg_t.update(tp=kc["tp"], stale_min=kc["stale_min"], stale_ret=kc["stale_ret"],
                                 max_hold_h=kc["max_hold_h"])
                size = rules.high_risk_size(c.get("rug_verdict"), size, ex_size)
                c["size_usd"] = size
                pos = sim.open_position(price, liq, now, size, cfg_t)
                c["trade_id"] = store.open_trade(con, t, c.get("symbol"), pos, cfg_t, mcap)
                c["decision"] = "taken"
                c["reason"] = (f"konvergencija {cv['score']:.0f}: {'+'.join(cv['platforms'])}, "
                               f"{cv['n_x']} X / {cv['n_tg']} TG / {cv['n_chain']} novčanika" if konv else
                               f"istraživanje: score {s:.0f} u vrhu dana (prag {ex_need:.0f})" if explore else
                               f"score {s:.0f}") + f" [{arm}]" + (f", rug {c['rug_verdict']}" if c.get("rug_verdict") else "") + (
                               f"; {size_note}" if size_note else "")
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
    global LAST_INTAKE
    LAST_INTAKE = _intake_summary(cands, cfg, ex_need)
    opened += trigger_entries(con, cfg, rst, now)
    rules.save(rst)
    con.commit()
    _announce(opened, cfg, quiet)
    return opened


LAST_INTAKE = None   # one line on why the last pass bought nothing (the loop prints it; 4.11.: "demo otvorenih 0" all day)


def _intake_summary(cands, cfg, ex_need):
    """'7 kandidata: skip_score 5 (najbolji 41 < 50), skip_liq 1, bez cijene 1; prag 50, istraživanje od 38'."""
    if not cands:
        return None
    by, best = {}, {}
    for c in cands.values():
        d = c.get("decision") or "bez cijene"
        by[d] = by.get(d, 0) + 1
        best[d] = max(best.get(d, 0), c.get("score") or 0)
    parts = [f"{d} {n}" + (f" (najbolji {best[d]:.0f} < {cfg['min_score']})" if d == "skip_score" else "")
             for d, n in sorted(by.items(), key=lambda kv: -kv[1])]
    ex = f", istraživanje od {ex_need:.0f}" if ex_need is not None else ", istraživanje isključeno"
    return f"{len(cands)} kandidata: {', '.join(parts)}; prag {cfg['min_score']}{ex}"


import threading as _threading
POS_LOCK = _threading.Lock()   # 5.11.: tick() and live_exits() both load, mutate and save open positions


def live_exits(cfg, now=None, quiet=False):
    """5.11.: the live feed (run_live.py, PumpPortal) flagged a dump on an open demo token: sell what is left now, at
    the DexScreener price, instead of at the next minute tick. Returns [(symbol, result)] closed."""
    from live import pulse, store as lstore
    c = pulse.config(cfg)
    if not c.get("dump_exit"):
        return []
    now = now or time.time()
    lc = lstore.ro()
    if lc is None:
        return []
    try:
        hits = pulse.alerts(lc, now - 180)
    finally:
        lc.close()
    if not hits:
        return []
    with POS_LOCK:
        con = store.connect(DB)
        trades = {t: (tid, sym, pos) for tid, t, sym, pos in store.open_trades(con)}
        todo = {t: d for t, _ts, d in hits if t in trades and trades[t][2].get("open")}
        if not todo:
            con.close()
            return []
        mk = market(set(todo)) or {}
        closed = []
        for t, d in todo.items():
            tid, sym, pos = trades[t]
            price, liq, mcap, _ = mk.get(t, (0, 0, 0, None))
            if price <= 0:
                continue
            cfg_t = {**cfg, **json.loads(con.execute("SELECT config FROM trades WHERE id=?", (tid,)).fetchone()[0])}
            n_fills = len(pos["fills"])
            sim.sell(pos, pos["left"], price, liq, now, "zivi_dump", cfg_t)
            for f in pos["fills"][n_fills:]:
                f["mcap"] = mcap
            res = sim.result(pos, price, liq, cfg_t)
            store.save_trade(con, tid, pos, res, mcap)
            msg = (f"⚡ DEMO PRODAJA {sym} 100% @ {price:.3g} mcap {_usd(mcap)} (živi tok: dump; {d.get('why', '')})"
                   + (f"  zatvoreno {res['pnl_usd']:+.2f} USD ({res['ret']:+.0%})" if not pos["open"] else ""))
            if not quiet:
                print(msg, flush=True)
            notify(msg)
            if not pos["open"]:
                closed.append((sym, res))
        con.commit()
        con.close()
    return closed


def _live_loop(every=5):
    """Dump exits within seconds of the live feed's alert, in its own thread of the demo process."""
    while True:
        try:
            live_exits(sim.load_config())
        except Exception as e:  # noqa: BLE001 - must never stop the main demo
            print(f"živi izlaz: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(every)


def tick(cfg, now=None, quiet=False):
    """Price every open trade and every candidate still inside track_h; apply exit rules."""
    now = now or time.time()
    POS_LOCK.acquire()
    try:
        return _tick(cfg, now, quiet)
    finally:
        POS_LOCK.release()


def _tick(cfg, now, quiet):
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


def _koltest_loop(every=30):
    """Separate 7-day KOL test book (koltest/, own koltest.db) in its own thread of this process: every 30 s, so an
    entry follows a call within a minute even while a hype scan holds the main loop for minutes."""
    from koltest import run as koltest
    while True:
        try:
            koltest.step()
        except Exception as e:  # noqa: BLE001 - the test must never stop the main demo
            print(f"KOL test: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(every)


def _strat_loop(every=60):
    """Strategy comparison (strat/, own strat.db): five $1000 demo accounts buying from different sources, in its own
    thread of this process every minute. Never stops the main demo."""
    from strat import run as strat
    while True:
        try:
            strat.step()
        except Exception as e:  # noqa: BLE001 - the comparison must never stop the main demo
            print(f"strategije: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(every)


def _aktivni_loop(every=600):
    """Refreshes the "aktivni" list (paper/aktivni.py: older tokens with the most buys and sells) every refresh_h
    hours in its own thread: about 15 GeckoTerminal calls spaced a few seconds apart must not hold the main loop."""
    while True:
        try:
            cfg = sim.load_config()
            c = aktivni.config(cfg)
            if c["enabled"] and aktivni.due(aktivni.load(), c, time.time()):
                st = aktivni.refresh(cfg, force=True)
                print(f"aktivni: {len(st.get('tokens') or [])} tokena od {st.get('n_seen', 0)} najaktivnijih",
                      file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001 - the list must never stop the main demo
            print(f"aktivni: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(every)


def cmd_run(a):
    last_scan = last_review = 0
    import threading
    threading.Thread(target=_koltest_loop, name="koltest", daemon=True).start()
    threading.Thread(target=_strat_loop, name="strategije", daemon=True).start()
    threading.Thread(target=_live_loop, name="zivi", daemon=True).start()
    threading.Thread(target=_aktivni_loop, name="aktivni", daemon=True).start()
    # --top 3: the 3 best scores with their features go to the log, so a day of "demo otvorenih 0" explains itself (4.11.)
    hype_args = ["scan", "--top", "3"] + (a.hype_args.split() if a.hype_args else [])
    while True:
        cfg = sim.load_config(a.config)  # re-read each loop, so `apply` takes effect without a restart
        now = time.time()
        try:
            if a.scan and now - last_scan >= a.scan_every:
                # in its own short process (1.11.: the scan in this loop kept ~65 MB on the 512 MB server)
                # skipped (tried again next loop) while another heavy job runs, so exits/ticks never wait (2.11.)
                # (after 10 min without a scan it runs anyway, so new tokens are never held back for long)
                import subprocess
                from ops import heavy
                cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_hype.py")] + hype_args
                if now - last_scan < 600:
                    done = heavy.run(cmd, wait=0, timeout=1800)
                else:
                    done = subprocess.run(cmd, timeout=1800)
                if done is not None:
                    last_scan = now
            opened = intake(cfg)
            if not opened and LAST_INTAKE:
                print(f"  ulazi 0: {LAST_INTAKE}", flush=True)
            t_tick = time.time()
            closed = tick(cfg)
            t_tick = time.time() - t_tick
            con = store.connect(DB)
            e = equity(con, cfg)
            took = time.time() - now
            # 6.11.: up to 100 open positions (#184); a pass over 60 s means prices are stale before the next one
            print(f"{dt.datetime.now():%H:%M:%S}  demo {_usd(e['equity'])}  otvorenih {e['open']}  "
                  f"zatvoreno sad {len(closed)}  prolaz {took:.0f} s (cijene/izlazi {t_tick:.0f} s)"
                  + ("  SPORO: cijene kasne" if took > 60 else ""), flush=True)
            hh, mm = map(int, a.review_at.split(":"))
            due = dt.datetime.now().replace(hour=hh, minute=mm, second=0).timestamp()
            done = con.execute("SELECT 1 FROM reviews WHERE day=?", (_today(),)).fetchone()
            con.close()
            if now >= due and not done and now - last_review > 3600:
                last_review = now
                cmd_review(argparse.Namespace(config=a.config, hours=24, telegram=False))
        except Exception as e:
            import traceback
            where = " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
                                for f in reversed(traceback.extract_tb(e.__traceback__)[-3:]))
            print(f"greška u prolazu: {type(e).__name__}: {e} ({where})", file=sys.stderr)
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
