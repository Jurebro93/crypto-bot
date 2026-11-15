"""One holderi pass (run_holderi.py pass; start.sh every HOLDERI_EVERY_S, 10 min; only with the owner switch fokus_midcap,
like the midcap collector whose list it reads).

  lists      each exchange's public market list once a day (free, no keys; holderi/burze.refresh_lists)
  snapshot   the top 20 holders of the midcaps (veliki/midcap members by 24 h volume): the top watch_top (50) every
             watch_every_h (6 h) = the transfer watch, the rest every snap_every_h (24 h); RugCheck first (free, its 1 h
             cache file is the collector's), Helius getTokenLargestAccounts only when RugCheck has nothing (3 credits);
             at most rc_pass reports a pass. Classified (holderi/klasa), stored with the profile; diff vs the previous
  trace      a holder (not a pool / exchange / burn) that lost >= min_move_pct (0.5 %) of supply since the previous
             snapshot: its transactions since then (10 credits) -> where the tokens went: an exchange wallet (known or a
             deposit address that sweeps into one: +10 credits; or exchange-like by behaviour: +2) / a swap (sell) /
             another wallet; at most trace_pass a pass
  mm         new top holders funded by an exchange wallet (their first funder, 10 credits, cached a week): market-maker-
             like distribution; at most mm_pass a pass
  xbal       every xbal_every_h (6 h): each known exchange wallet's balances of the midcaps (2 credits a wallet): a new
             non-zero balance or a jump is itself evidence
  evaluate   holderi/signal per token x exchange in the window (72 h): PRE-LISTING (not listed there) or deposit to sell
             (listed there); the loud log line + Telegram from min_score; every signal stored with the price then; the
             caution per token; kv "pri" for veliki/prioritet (components "listing" and "oprez")
  outcomes   the price 1 h / 24 h / 7 d after every signal and the median midcap over the same window (midcap.db snap,
             free; DexScreener when the token is not a member)
  profit     holderi/profit (profitable diamond holders of established midcaps, what they buy, clusters), by its own clock
Every Helius call is inside the daily cap (helius_credits_day, sliced by the hour) and metered by usage/meter.
"""
import json
import os
import statistics
import time

from holderi import burze, chain, klasa, signal, store

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = "holderi: "
CFG = os.path.join(HERE, "config.json")


def config(path=None):
    c = dict(signal.DEFAULTS)
    try:
        with open(path or CFG, encoding="utf-8") as f:
            c.update(json.load(f))
    except (OSError, ValueError):
        pass
    return c


def members(path=None):
    """[{mint, symbol, mcap, liq, vol24, pool}] by 24 h volume: the midcap collector's members, else the veliki list."""
    try:
        from veliki import midcap
        rows = midcap.members(path)
        if rows:
            return rows
    except Exception:  # noqa: BLE001
        pass
    try:
        from veliki import store as vstore
        return [{"mint": x["mint"], "symbol": x.get("symbol"), "mcap": x.get("mcap"), "liq": x.get("liq"),
                 "vol24": x.get("vol24"), "pool": x.get("pool")} for x in (vstore.the_list() or {}).get("tokens") or []]
    except Exception:  # noqa: BLE001
        return []


def _labels(owners, wallet_db=None):
    """{wallet: set(labels)} from wallets.db (read-only), {} without it."""
    import sqlite3
    p = wallet_db or os.environ.get("WALLET_DB", os.path.join(os.path.dirname(HERE), "wallets.db"))
    owners = [o for o in owners if o]
    if not owners or not os.path.exists(p):
        return {}
    out = {}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        try:
            for i in range(0, len(owners), 400):
                part = owners[i:i + 400]
                for w, lab in con.execute(f"SELECT wallet, labels FROM wallets WHERE wallet IN ({','.join('?' * len(part))})",
                                          part):
                    out[w] = set(json.loads(lab or "[]"))
        finally:
            con.close()
    except (sqlite3.Error, ValueError):
        return {}
    return out


def _funders(con, owners, now):
    return {w: f for w, f, ts in con.execute(
        f"SELECT wallet, funder, ts FROM funders WHERE wallet IN ({','.join('?' * len(owners))})", list(owners))
        if f and now - ts < 30 * 86400} if owners else {}


def get_funder(con, wallet, budget, now):
    r = con.execute("SELECT funder, ts FROM funders WHERE wallet=?", (wallet,)).fetchone()
    if r and now - r[1] < 30 * 86400:
        return r[0]
    try:
        f = chain.funder(wallet, budget)
    except Exception:  # noqa: BLE001
        return None
    if f is None and budget.left() <= 0:
        return None
    con.execute("INSERT OR REPLACE INTO funders VALUES (?,?,?)", (wallet, f, int(now)))
    return f


# ---------- snapshot ---------------------------------------------------------------------------------------------------

def snapshot(con, c, tok, now, budget, reg, cross, log=print, rc=None):
    """One token's top holders -> snap + profile rows. (ts, rows, profile, pools, supply) or None when no source
    answered."""
    mint = tok["mint"]
    src = "rugcheck"
    if rc is None:
        try:
            rc = chain.rugcheck(mint)
        except Exception:  # noqa: BLE001 - RugCheck busy: Helius below (within the cap)
            rc = None
        store.count(con, now, rc=1)
    hs, pools, creator, known, supply = klasa.from_rugcheck(rc, [tok.get("pool")] if tok.get("pool") else ())
    if not hs:
        src = "helius"
        try:
            rows = chain.largest(mint, budget)
        except Exception:  # noqa: BLE001
            rows = None
        if not rows:
            return None
        supply = supply or _supply(con, mint, budget, now)
        if not supply:
            return None
        hs = [{"owner": r["owner"], "acct": r["acct"], "amount": r["amount"], "pct": r["amount"] / supply * 100,
               "program_owner": r.get("program_owner")} for r in rows]
    elif supply:
        store.kv_put(con, f"sup:{mint}", {"ts": int(now), "v": supply})
    owners = [h["owner"] for h in hs]
    rows = klasa.classify(hs[:20], pools=pools, creator=creator, reg=reg, cross=cross, labels=_labels(owners),
                          funders=_funders(con, owners, now), known=known, whale_pct=float(c["whale_pct"]),
                          cross_min=int(c["cross_min"]))
    prof = klasa.metrics(rows)
    prof["creator"] = creator
    ts = int(now)
    con.executemany("INSERT OR REPLACE INTO snap VALUES (?,?,?,?,?,?,?,?,?)",
                    [(mint, ts, k, r["owner"], r["acct"], r["amount"], r["pct"], r["cls"], r.get("why"))
                     for k, r in enumerate(rows)])
    con.execute("INSERT OR REPLACE INTO profile VALUES (?,?,?,?,?,?)",
                (mint, ts, tok.get("symbol"), tok.get("mcap"), src, json.dumps(prof, ensure_ascii=False)))
    return ts, rows, prof, pools, supply


def _supply(con, mint, budget, now):
    s = store.kv_get(con, f"sup:{mint}") or {}
    if s.get("v") and now - int(s.get("ts") or 0) < 7 * 86400:
        return float(s["v"])
    try:
        v = chain.supply(mint, budget)
    except Exception:  # noqa: BLE001
        v = None
    if v:
        store.kv_put(con, f"sup:{mint}", {"ts": int(now), "v": v})
    return v


def due(con, c, toks, now):
    """The tokens whose snapshot is due, the watch (top watch_top) first, oldest first."""
    last = dict(con.execute("SELECT mint, MAX(ts) FROM profile GROUP BY mint"))
    out = []
    for k, t in enumerate(toks):
        every = float(c["watch_every_h"] if k < int(c["watch_top"]) else c["snap_every_h"]) * 3600
        age = now - (last.get(t["mint"]) or 0)
        if age >= every:
            out.append((0 if k < int(c["watch_top"]) else 1, -age, k, t))
    out.sort(key=lambda x: x[:3])
    return [x[3] for x in out]


# ---------- trace ------------------------------------------------------------------------------------------------------

def check_dest(con, c, dest, mint, after_ts, budget, reg, rows, pools=(), now=None):
    """(dest class, exchange, confidence, kind) of a destination wallet (see the module text)."""
    if dest is None:
        return "nepoznat", None, 0.0, "transfer"
    if dest in reg:
        e = reg[dest]
        return "exchange", e["exchange"], e["confidence"], "to_exchange"
    if dest in set(pools or ()):
        return "lp", None, 0.0, "sell"
    snap_cls = {r["owner"]: r["cls"] for r in rows or []}
    if snap_cls.get(dest) == "exchange":
        r = next(x for x in rows if x["owner"] == dest)
        return "exchange", r.get("exchange") or "nepoznata", float(r.get("conf") or 0.5), "to_exchange"
    try:
        dtx = chain.txs(dest, after_ts - 60, budget)
    except Exception:  # noqa: BLE001
        dtx = None
    for tx in dtx or []:
        for d2, _amt, _k in chain.outflows(tx, dest, mint):
            if d2 in reg:
                e = reg[d2]
                return "exchange", e["exchange"], round(e["confidence"] * 0.9, 2), "deposit_sweep"
    try:
        b = chain.busy(dest, budget)
    except Exception:  # noqa: BLE001
        b = None
    conf = burze.behaviour(*b, busy_sol=float(c.get("busy_sol") or 5000), busy_h=float(c.get("busy_h") or 24)) if b else None
    if conf:
        burze.add(con, dest, "nepoznata", "hot", conf, f"heuristika: {b[0]:,.0f} SOL, {b[1]} tx u {b[2]:.1f} h",
                  "heuristika", now)
        return "exchange", "nepoznata", conf, "to_exchange"
    return snap_cls.get(dest) or "wallet", None, 0.0, "transfer"


def trace(con, c, mint, sender, sender_cls, supply, since_ts, now, budget, reg, rows, pools=()):
    """The sender's outflows of `mint` since since_ts -> moves rows. n recorded, or None over the cap."""
    txs = chain.txs(sender, since_ts, budget)
    if txs is None:
        return None
    agg = {}
    for tx in txs:
        for dest, amt, kind in chain.outflows(tx, sender, mint):
            a = agg.setdefault((dest, kind), {"amt": 0.0, "ts": chain.tx_ts(tx), "sig": chain.tx_sig(tx)})
            a["amt"] += amt
            a["ts"] = min(a["ts"], chain.tx_ts(tx)) if a["ts"] else chain.tx_ts(tx)
    n = 0
    for (dest, kind), a in sorted(agg.items(), key=lambda x: -x[1]["amt"]):
        pct = a["amt"] / supply * 100 if supply else None
        if pct is None or pct < float(c["min_move_pct"]) / 2:
            continue
        if kind == "sell":
            dcls, ex, conf, k = "lp", None, 0.0, "sell"
        else:
            dcls, ex, conf, k = check_dest(con, c, dest, mint, a["ts"] or since_ts, budget, reg, rows, pools, now)
        con.execute("INSERT OR IGNORE INTO moves (mint, ts, sender, sender_cls, dest, dest_cls, exchange, pct, kind, sig, "
                    "conf, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mint, int(a["ts"] or now), sender, sender_cls, dest, dcls, ex, round(pct, 4), k, a["sig"], conf, None))
        n += 1
    return n


def record_diff(con, c, tok, d, ts, now, budget, reg, rows, pools, supply, prev_ts, counters):
    """Moves from one snapshot diff: traced outflows (within trace_pass), exchange balance jumps / new exchange holders,
    new top holders funded by an exchange (within mm_pass)."""
    mint = tok["mint"]
    cls = {r["owner"]: r for r in rows}
    for o, ocls, dp in d["out"]:
        if ocls in ("lp", "exchange", "burn"):
            continue
        if counters["trace"] >= int(c["trace_pass"]):
            break
        counters["trace"] += 1
        try:
            trace(con, c, mint, o, ocls, supply, prev_ts, now, budget, reg, rows, pools)
        except Exception:  # noqa: BLE001 - one trace costs only itself
            pass
    for o, ocls, dp in d["in"]:
        if ocls == "exchange":
            r = cls.get(o) or {}
            con.execute("INSERT OR IGNORE INTO moves (mint, ts, sender, sender_cls, dest, dest_cls, exchange, pct, kind, "
                        "sig, conf, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (mint, ts, None, "untraced", o, "exchange", r.get("exchange") or "nepoznata", dp,
                         "new_balance" if o in d["new"] else "balance_jump", None, float(r.get("conf") or 0.5), None))
    for o in d["new"]:
        r = cls.get(o) or {}
        if r.get("cls") not in ("normal", "whale") or (r.get("pct") or 0) < 0.3 or counters["mm"] >= int(c["mm_pass"]):
            continue
        counters["mm"] += 1
        f = get_funder(con, o, budget, now)
        if f and f in reg:
            e = reg[f]
            con.execute("INSERT OR IGNORE INTO moves (mint, ts, sender, sender_cls, dest, dest_cls, exchange, pct, kind, "
                        "sig, conf, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (mint, ts, f, "exchange", o, r["cls"], e["exchange"], r["pct"], "mm_funded", None,
                         e["confidence"], None))


# ---------- exchange balances --------------------------------------------------------------------------------------------

def xbal_pass(con, c, toks, now, budget, reg):
    """Each exchange wallet's balances of the midcaps (see the module text). n wallets checked."""
    if now - int(store.kv_get(con, "xbal_ts", 0) or 0) < float(c["xbal_every_h"]) * 3600:
        return 0
    mints = [t["mint"] for t in toks]
    sup = {m: (store.kv_get(con, f"sup:{m}") or {}).get("v") for m in mints}
    n = 0
    for w, e in sorted(reg.items(), key=lambda x: -x[1]["confidence"]):
        if e["confidence"] < float(c["xbal_min_conf"]) or e["exchange"] == "nepoznata":
            continue
        try:
            bal = chain.token_accounts(w, mints, budget)
        except Exception:  # noqa: BLE001
            bal = None
        if bal is None:
            break
        n += 1
        checked = store.kv_get(con, f"xchk:{w}")
        prev = {m: p for m, p in con.execute(
            "SELECT x.mint, x.pct FROM xbal x JOIN (SELECT mint, MAX(ts) mts FROM xbal WHERE wallet=? GROUP BY mint) y "
            "ON y.mint = x.mint AND y.mts = x.ts WHERE x.wallet=?", (w, w))}
        for m in set(bal) | {m for m, p in prev.items() if p}:
            amt = bal.get(m, 0.0)
            pct = round(amt / sup[m] * 100, 4) if sup.get(m) else None
            con.execute("INSERT OR REPLACE INTO xbal VALUES (?,?,?,?,?)", (w, m, int(now), amt, pct))
            if not checked or pct is None:
                continue
            old = prev.get(m)
            if (not old) and pct >= float(c["min_move_pct"]) / 5:
                kind, dp = "new_balance", pct
            elif old and pct - old >= float(c["min_move_pct"]):
                kind, dp = "balance_jump", round(pct - old, 4)
            else:
                continue
            con.execute("INSERT OR IGNORE INTO moves (mint, ts, sender, sender_cls, dest, dest_cls, exchange, pct, kind, "
                        "sig, conf, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (m, int(now), None, "untraced", w, "exchange", e["exchange"], dp, kind, None, e["confidence"], None))
        store.kv_put(con, f"xchk:{w}", int(now))
    store.kv_put(con, "xbal_ts", int(now))
    return n


def growth(con, mint, wallets):
    """How many times in a row (the newest readings) the exchange's summed balance of `mint` grew."""
    if not wallets:
        return 0
    q = ",".join("?" * len(wallets))
    by = {}
    for ts, pct in con.execute(f"SELECT ts, SUM(COALESCE(pct, 0)) FROM xbal WHERE mint=? AND wallet IN ({q}) GROUP BY ts "
                               "ORDER BY ts", (mint, *wallets)):
        by[ts] = pct
    vals = [by[t] for t in sorted(by)][-4:]
    n = 0
    for a, b in zip(vals[::-1][1:], vals[::-1][:-1]):
        if b > a + 1e-9:
            n += 1
        else:
            break
    return n


# ---------- evaluate ---------------------------------------------------------------------------------------------------

def grok_listing(mints, now, trade_db=None):
    """{mint: {"verdict", "confidence", "exchange"}} of Grok's newest listing_check answer (48 h)."""
    import sqlite3
    mints = list(mints)
    if not mints:
        return {}
    try:
        from trade import settings
        p = trade_db or settings.DB
        if not os.path.exists(p):
            return {}
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    try:
        for tok, v, cf, ev in con.execute(
                f"SELECT token, verdict, confidence, evidence FROM assistant_notes WHERE kind='signal_opinion' AND "
                f"token IN ({','.join('?' * len(mints))}) AND ts >= ? AND evidence LIKE '%listing_check%' ORDER BY ts, id",
                (*mints, int(now) - 48 * 3600)):
            try:
                e = json.loads(ev or "{}")
            except ValueError:
                e = {}
            out[tok] = {"verdict": v, "confidence": cf, "exchange": e.get("exchange")}
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return out


def px_now(mints, path=None):
    """{mint: (price, mcap)} of the newest midcap.db snap row (free), DexScreener for the rest (free)."""
    out = {}
    try:
        from veliki import midcap
        mc = midcap.ro(path)
        if mc is not None:
            try:
                q = ",".join("?" * len(mints))
                for m, px, mcap in mc.execute(
                        f"SELECT t.mint, s.px, s.mc FROM tokens t JOIN snap s ON s.id = t.id WHERE t.mint IN ({q}) AND "
                        f"s.ts = (SELECT MAX(ts) FROM snap WHERE id = t.id)", list(mints)):
                    if px:
                        out[m] = (px, mcap)
            finally:
                mc.close()
    except Exception:  # noqa: BLE001
        pass
    rest = [m for m in mints if m not in out]
    if rest:
        try:
            from dexscreener import client
            best = {}
            for p in client.tokens("solana", rest):
                m = ((p or {}).get("baseToken") or {}).get("address")
                liq = ((p or {}).get("liquidity") or {}).get("usd") or 0
                if m in rest and liq >= (best.get(m) or (0, 0))[1]:
                    best[m] = ((float(p.get("priceUsd") or 0), float(p.get("marketCap") or p.get("fdv") or 0)), liq)
            out.update({m: v[0] for m, v in best.items() if v[0][0]})
        except Exception:  # noqa: BLE001
            pass
    return out


def _telegram(text):
    import threading
    import urllib.parse
    import urllib.request
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False

    def send():
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": f"MemeSonar · {text}",
                                           "disable_web_page_preview": "true"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=15).read()
        except Exception as e:  # noqa: BLE001 - the log line is there anyway
            print(PREFIX + f"Telegram nije poslan ({type(e).__name__})", flush=True)
    t = threading.Thread(target=send, daemon=True)
    t.start()
    t.join(20)
    return True


NOTIFY = {"fn": None}   # tests: a function(text) instead of Telegram


def notify(text):
    """The owner, the way urgent events already reach him: the loud server log line always, Telegram when
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set (ops/diskguard, ui/grokauto use the same path)."""
    if NOTIFY["fn"]:
        return NOTIFY["fn"](text)
    return _telegram(text)


def evaluate(con, c, toks, now, log=print, use_cg=True):
    """Signals per token x exchange, the caution per token, kv "pri" (see the module text). [new signal dicts]."""
    win = int(now) - int(float(c["window_h"]) * 3600)
    by_mint = {t["mint"]: t for t in toks}
    profs = store.latest_profiles(con, set(by_mint), now=now)
    moves = {}
    for r in con.execute("SELECT mint, ts, sender, sender_cls, dest, dest_cls, exchange, pct, kind, conf FROM moves "
                         "WHERE ts >= ?", (win,)):
        m = dict(zip(("mint", "ts", "sender", "sender_cls", "dest", "dest_cls", "exchange", "pct", "kind", "conf"), r))
        if m["mint"] in by_mint:
            moves.setdefault(m["mint"], []).append(m)
    reg = burze.registry()
    gk = grok_listing([m for m in moves], now)
    pri, new = {}, []
    px = None
    for mint, t in by_mint.items():
        ms = moves.get(mint) or []
        sym = t.get("symbol") or mint[:6]
        groups = {}
        for m in ms:
            if m["dest_cls"] == "exchange" and m["kind"] in ("to_exchange", "deposit_sweep", "new_balance",
                                                             "balance_jump"):
                groups.setdefault(m["exchange"] or "nepoznata", []).append(m)
        sigs, caution_moves = [], [m for m in ms if m["kind"] == "sell"]
        for ex, g in groups.items():
            traced = [m for m in g if m["kind"] in ("to_exchange", "deposit_sweep")]
            ev = traced or [max(g, key=lambda m: m["pct"] or 0)]
            mm = len({m["dest"] for m in ms if m["kind"] == "mm_funded" and m["exchange"] == ex})
            wl = [w for w, e in reg.items() if e["exchange"] == ex] if ex != "nepoznata" else \
                list({m["dest"] for m in g if m["dest"]})
            status, why = burze.listed(con, mint, sym, ex, now, use_cg=use_cg)
            gg = gk.get(mint) if (gk.get(mint) or {}).get("exchange") in (None, "", ex) else None
            s = signal.score_group(ev, ex, status, growth(con, mint, wl), mm, gg)
            s["listed_why"] = why
            s["listed"] = status
            sigs.append(s)
            if s["kind"] == "deposit_sell":
                caution_moves += [{**m, "kind": "deposit_sell"} for m in ev]
        cau = signal.caution(profs.get(mint), caution_moves, c)
        best = max((s for s in sigs if s["kind"] == "pre_listing"), key=lambda s: s["score"], default=None)
        bonus = 0.0
        if best and best["score"] >= float(c["bonus_min_score"]):
            bonus = round(min(float(c["bonus_max"]), 0.5 * best["score"]), 1)
        if bonus or cau["pts"] or cau["block"]:
            pri[mint] = {"symbol": sym, "listing": bonus, "listing_score": best["score"] if best else None,
                         "listing_ex": best["exchange"] if best else None, "oprez": cau["pts"], "block": cau["block"],
                         "why": ((best["reasons"][:3] if best and bonus else []) + cau["why"])}
        for s in sigs:
            old = con.execute("SELECT MAX(score) FROM signals WHERE mint=? AND exchange=? AND kind=? AND ts >= ?",
                              (mint, s["exchange"], s["kind"], int(now) - 86400)).fetchone()[0]
            if old is not None and s["score"] < old + 10:
                continue
            if s["score"] < 20:
                continue
            if px is None:
                px = px_now(list({m for m in moves}))
            p, mc = (px.get(mint) or (None, None))
            mc = mc or t.get("mcap")
            loud = s["kind"] == "pre_listing" and s["score"] >= float(c["min_score"])
            cur = con.execute("INSERT INTO signals (mint, symbol, ts, kind, exchange, score, reasons, mcap, px, listed, "
                              "notified) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                              (mint, sym, int(now), s["kind"], s["exchange"], s["score"],
                               json.dumps(s["reasons"] + [s["listed_why"]], ensure_ascii=False), mc, p, s["listed"],
                               1 if loud and c.get("notify", True) else 0))
            s.update(id=cur.lastrowid, mint=mint, symbol=sym, mcap=mc)
            new.append(s)
            if loud:
                line = signal.loud(sym, mc, s)
                log(line)
                if c.get("notify", True):
                    try:
                        notify(line + f" · CA {mint}")
                    except Exception:  # noqa: BLE001
                        pass
            elif s["kind"] == "deposit_sell" and s["score"] >= 30:
                log(PREFIX + f"{sym}: depozit na {burze.NAMES.get(s['exchange'], s['exchange'])} gdje je VEĆ listan "
                    f"({s['pct']:.2f} % ponude) — moguća prodaja, oprez")
    store.kv_put(con, "pri", {"ts": int(now), "rows": pri})
    con.commit()
    return new


# ---------- outcomes ---------------------------------------------------------------------------------------------------

HORIZONS = (("1h", 3600), ("24h", 86400), ("7d", 7 * 86400))


def _snap_px(mc, ts, slack=1800):
    """{mint: px} of every midcap member's snap row nearest after ts (within slack)."""
    out = {}
    for m, px in mc.execute("SELECT t.mint, s.px FROM snap s JOIN tokens t ON t.id = s.id WHERE s.ts BETWEEN ? AND ? "
                            "ORDER BY s.ts DESC", (int(ts), int(ts + slack))):
        if px:
            out[m] = px
    return out


def outcomes(con, now, midcap_path=None):
    """Fills px_1h / 24h / 7d and the control (median midcap return) of the signals that are due. n filled."""
    rows = con.execute("SELECT id, mint, ts, px, px_1h, px_24h, px_7d FROM signals WHERE px IS NOT NULL AND "
                       "(px_1h IS NULL OR px_24h IS NULL OR px_7d IS NULL) AND ts >= ?", (int(now) - 9 * 86400,)).fetchall()
    if not rows:
        return 0
    mc = None
    try:
        from veliki import midcap
        mc = midcap.ro(midcap_path)
    except Exception:  # noqa: BLE001
        mc = None
    n = 0
    try:
        for sid, mint, ts, px0, *have in rows:
            for (name, h), v in zip(HORIZONS, have):
                if v is not None or now < ts + h:
                    continue
                p1 = ctl = None
                if mc is not None:
                    a, b = _snap_px(mc, ts), _snap_px(mc, ts + h)
                    p1 = b.get(mint)
                    rets = [b[m] / a[m] - 1 for m in a if m in b and m != mint and a[m]]
                    ctl = round(statistics.median(rets) * 100, 2) if len(rets) >= 5 else None
                if p1 is None and now - (ts + h) <= 2 * 3600:
                    p1 = (px_now([mint], midcap_path).get(mint) or (None,))[0]
                if p1 is None and now - (ts + h) <= 2 * 3600:
                    continue   # not yet readable: the next pass
                con.execute(f"UPDATE signals SET px_{name}=?, ctl_{name}=? WHERE id=?",
                            (p1 if p1 is not None else -1, ctl, sid))   # -1 = never readable (no price then)
                n += 1
    finally:
        if mc is not None:
            mc.close()
    con.commit()
    return n


# ---------- one pass ---------------------------------------------------------------------------------------------------

def run_pass(now=None, log=print, path=None, force=False, toks=None):
    """One pass (see the module text); {} when the owner switch fokus_midcap is off (unless force)."""
    now = int(now or time.time())
    if not force:
        try:
            from ops import fokus
            if not fokus.on():
                return {}
        except Exception:  # noqa: BLE001
            return {}
    c = config()
    con = store.connect(path)
    out = {"snaps": 0, "traced": 0, "signals": 0}
    budget = chain.Budget(con, c["helius_credits_day"], now)
    try:
        toks = members() if toks is None else toks
        if not toks:
            return out
        if now - int(store.kv_get(con, "lists_ts", 0) or 0) >= float(c["lists_every_h"]) * 3600:
            out["lists"] = burze.refresh_lists(con, now, log=log)
            store.kv_put(con, "lists_ts", now)
            store.count(con, now, lists=out["lists"])
        reg = burze.registry(fresh=True)
        cross = burze.cross_token(con, now, int(c["cross_min"]))
        counters = {"trace": 0, "mm": 0, "rc": 0, "helius": 0}
        for tok in due(con, c, toks, now):
            if counters["rc"] >= int(c["rc_pass"]):
                break
            counters["rc"] += 1
            mint = tok["mint"]
            pts = store.prev_ts(con, mint, now + 1)
            prev = store.snap_rows(con, mint, pts) if pts else []
            try:
                r = snapshot(con, c, tok, now, budget, reg, cross, log)
            except Exception as e:  # noqa: BLE001 - one token costs only itself
                log(PREFIX + f"{tok.get('symbol') or mint[:6]}: snimka nije uspjela ({type(e).__name__})")
                r = None
            if not r:
                continue
            out["snaps"] += 1
            ts, rows, _prof, pools, supply = r
            if prev:
                d = klasa.diff(prev, rows, float(c["min_move_pct"]))
                if d["out"] or d["in"] or d["new"]:
                    supply = supply or _supply(con, mint, budget, now)
                    record_diff(con, c, tok, d, ts, now, budget, reg, rows, pools, supply, pts, counters)
            con.commit()
        out["traced"] = counters["trace"]
        out["xbal"] = xbal_pass(con, c, toks, now, budget, reg)
        new = evaluate(con, c, toks, now, log)
        out["signals"] = len(new)
        out["outcomes"] = outcomes(con, now)
        try:
            from holderi import profit
            out["profit"] = profit.run(con, c, now, budget, reg, log)
        except Exception as e:  # noqa: BLE001 - the holder research never costs the listing watch
            log(PREFIX + f"profitabilni holderi: {type(e).__name__}: {e}")
        store.prune(con, now)
        out["helius"] = budget.close()
        con.commit()
        if now - int(store.kv_get(con, "hour_ts", 0) or 0) >= 3600:
            store.kv_put(con, "hour_ts", now)
            log(hour_line(con, c, now))
            try:
                from holderi import view
                view.write_md(con, now)
            except Exception as e:  # noqa: BLE001
                log(PREFIX + f"output/holderi.md: {type(e).__name__}")
            con.commit()
        return out
    finally:
        con.close()


def hour_line(con, c, now):
    d = store.kv_get(con, f"cnt:{store.day(now)}", {}) or {}
    n = con.execute("SELECT COUNT(DISTINCT mint) FROM profile WHERE ts >= ?", (int(now) - 86400,)).fetchone()[0]
    s = con.execute("SELECT kind, COUNT(*) FROM signals WHERE ts >= ? GROUP BY kind", (int(now) - 86400,)).fetchall()
    reg = burze.registry()
    pot = sum(1 for e in reg.values() if e["status"] == "potvrđeno")
    return (PREFIX + f"sat: {n} midcapova s profilom holdera (24 h), signali 24 h: "
            + (", ".join(f"{k} {v}" for k, v in s) or "nema")
            + f"; Helius danas {d.get('helius') or 0:,.0f}/{int(c['helius_credits_day']):,} kredita, RugCheck "
            f"{int(d.get('rc') or 0)} (besplatno), liste burzi {int(d.get('lists') or 0)} (besplatno); poznatih adresa "
            f"burzi {len(reg)} ({pot} potvrđenih)")
