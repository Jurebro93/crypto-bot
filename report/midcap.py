"""16.11. (vlasnik, jutarnji izvještaj: "zašto u strategijama nema tradeova? Treba maknuti strategije koje ne doprinose
učenju i ove s micro capovima ... Sada idemo s mid cap tokenima"): what the morning report and /strategije show about
the MIDCAP strategy, read-only from the databases the loops already fill (no network, no paid call, no write).

  trading     league.db veliki_trades (veliki/live.py): per account (demo PAPER_USER, real LEAGUE_USER) and rule
              ("dnevni raspon" = kind 'intra', "raspon 7 d" = the rest) for yesterday (the Zagreb day, the day the
              caps count) and the last 7 days: entries, closed, net PnL ($ and SOL at the real cost model), hit rate,
              target reached, break-even exits, whole vs half take-profits, stops; the real account's buys on chain
              (trade.db positions joined by league_id, the same join as veliki/live.chain_line, but per window); the
              open positions: entry, the price now (the newest 15m bar of league.db veliki_bars, else the midcap
              collector's snapshot), stop and target
  rules       each rule's out-of-sample EV (veliki.db: the 7-day rule's walk-forward proof at the real size, the
              intraday rule's 15m replay at 0.1 SOL) and whether real money may buy it now (veliki/gate, the same
              decision veliki/live.enter makes: the 7-day rule only with a passing holdout)
  replay      the intraday rule's historical test over every collector member (veliki/replay.py, midcap.db kv
              "replay"): the verdict in one sentence, a small table (all days, the holdout, the picked variant), the
              findings and the known biases
  wallet      trade/equity's newest snapshot (value, PnL 24 h), the real-money caps (veliki/gate.real_caps), the
              midcap real account's realized result today against its day-loss cap, the 1 SOL floor
              (trade/executor.equity_floor / equity_value)
  market      BTC (veliki.db hourly closes, rule.crash_of), the macro regime (midcap.db makro_h, veliki/makro), the
              midcap universe (collector members, trending, the veliki list) and the top movers (24 h change)
  research    Insajderi 2.0 (insajderi.db summary, league.db insajderi2_trades), the holders / listing signals
              (holderi.db signals and their 1 h / 24 h / 7 d measurement against the control)
  costs       usage.db daily_cost: yesterday's (UTC) row per source (usage/daily.py saves it at 23:59 UTC)
  kopija      the copier's walk-forward of the proven wallets (wallets/kopija.py, wallets.db copy_rank_kv "kopija"):
              the verdict, a small table, the gap between the wallet's own return and ours, what is stale under the
              midcap focus; and the demo copies (league.db kopija_trades, wallets/kopija_demo.py)
  strategies  one row per midcap strategy for /strategije and the report: demo / real / measurement / backtest with
              n, EV, CI, hit rate, 24 h and 7 d
Every part degrades on its own to None / {} / [] (a fresh deploy still gets a report). Database paths: the modules'
own (env VELIKI_DB, MIDCAP_DB, LEAGUE_DB, TRADE_DB ...), or REPORT_DB_DIR/<name>.db for every one (tests)."""
import json
import os
import sqlite3
import time

DAY = 86400
RULES = (("intra", "dnevni raspon"), ("range", "raspon 7 d"))
ACCOUNTS = (("demo", "demo"), ("pravi", "pravi novac"))
MIKROKAP_SINCE = "15.11."   # the day the owner switch fokus_midcap paused the microcap jobs (ops/fokus.py)
VARIANT_HR = {
    "osnovno": "osnovno (odabir na starijim danima)", "cijeli_trailing": "cijela pozicija trailing od cilja",
    "dca_10_bez_uvjeta": "DCA −10 % bez uvjeta", "dca_10": "pametni DCA −10 %", "dca_zona": "DCA na dnu zone",
    "dca_atr": "DCA 3× ATR", "razlozi": "izlazi s razlogom (BTC, makro, volumen)",
    "makro_filter": "makro filtar (bez ulaza u risk-off)", "makro_indeks": "makro filtar + indeks influencera",
    "sve": "DCA + razlozi + makro filtar", "siri_ulaz": "širi ulaz (više tradeova)",
    "stop_na_dnu_svijece": "stop na dnu svijeće", "btc_okrenut_gore": "ulaz tek kad BTC okrene gore"}


# ---------- paths and connections ------------------------------------------------------------------------------------

def _path(name, default):
    d = os.environ.get("REPORT_DB_DIR")
    return os.path.join(d, name) if d else default


def paths():
    """{"league", "trade", "veliki", "midcap", "holderi", "insajderi", "usage"}: the database files the report reads."""
    out = {}
    for key, name, fn in (("league", "league.db", lambda: __import__("league.store", fromlist=["DB"]).DB),
                          ("trade", "trade.db", lambda: __import__("trade.settings", fromlist=["DB"]).DB),
                          ("veliki", "veliki.db", lambda: __import__("veliki.store", fromlist=["x"]).db_path()),
                          ("midcap", "midcap.db", lambda: __import__("veliki.midcap", fromlist=["x"]).db_path()),
                          ("holderi", "holderi.db", lambda: __import__("holderi.store", fromlist=["x"]).db_path()),
                          ("insajderi", "insajderi.db", lambda: __import__("insajderi.store", fromlist=["x"]).db_path()),
                          ("usage", "usage.db", lambda: __import__("usage.meter", fromlist=["DB"]).DB),
                          ("wallets", "wallets.db", lambda: __import__("wallets.store", fromlist=["DB"]).DB)):
        try:
            default = fn()
        except Exception:  # noqa: BLE001 - a module that does not import: its file next to the code
            default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)
        out[key] = _path(name, default)
    return out


def ro(path):
    if not path or not os.path.exists(path) or not os.path.getsize(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        con.execute("PRAGMA busy_timeout = 10000")
        return con
    except sqlite3.Error:
        return None


def _has(con, table):
    try:
        return con is not None and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                               (table,)).fetchone() is not None
    except sqlite3.Error:
        return False


def day_start(now):
    """Midnight of the Zagreb day of `now` (the day veliki/live counts its caps in)."""
    try:
        import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.datetime.fromtimestamp(int(now), ZoneInfo("Europe/Zagreb"))
        return int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    except Exception:  # noqa: BLE001
        return int(now) // DAY * DAY


def users():
    try:
        from trade import settings
        return {"demo": settings.PAPER_USER, "pravi": settings.LEAGUE_USER}
    except Exception:  # noqa: BLE001
        return {"demo": "autopilot-paper", "pravi": "pravi-trade"}


def ev_ci(rets):
    """(EV %, [lo, hi] of the 90 % interval in %) of returns (fractions): trade/edge.ev_stats, the live proof's own
    formula; (None, None) without any."""
    try:
        from trade import edge
        s = edge.ev_stats(rets)
    except Exception:  # noqa: BLE001
        xs = [float(x) for x in rets or () if x is not None]
        s = {"ev": (sum(xs) / len(xs)) if xs else None, "lo90": None, "hi90": None}
    if s["ev"] is None:
        return None, None
    ci = [round(s["lo90"] * 100, 2), round(s["hi90"] * 100, 2)] if s.get("lo90") is not None else None
    return round(s["ev"] * 100, 2), ci


# ---------- trading --------------------------------------------------------------------------------------------------

VCOLS = ("id", "user", "token", "symbol", "opened_ts", "closed_ts", "status", "kind", "size_sol", "size_usd",
         "entry_px", "tp_px", "stop_px", "rt", "ret", "pnl_usd", "reason", "half_ts", "half_px", "be_px", "trade_id",
         "lots", "why", "makro", "prio")


def rule_of(r):
    return "intra" if (r.get("kind") or "") == "intra" else "range"


def vrows(lcon, since=None, closed_only=False):
    """league.db veliki_trades as dicts: open + opened / closed since `since`, or every closed row (closed_only)."""
    if not _has(lcon, "veliki_trades"):
        return []
    have = {r[1] for r in lcon.execute("PRAGMA table_info(veliki_trades)")}
    cols = [c for c in VCOLS if c in have]
    if closed_only:
        sql, args = f"SELECT {', '.join(cols)} FROM veliki_trades WHERE status='closed' AND ret IS NOT NULL", ()
    else:
        sql = (f"SELECT {', '.join(cols)} FROM veliki_trades WHERE status='open' OR opened_ts>=? OR closed_ts>=? "
               "OR half_ts>=?" if "half_ts" in have else
               f"SELECT {', '.join(cols)} FROM veliki_trades WHERE status='open' OR opened_ts>=? OR closed_ts>=?")
        args = (since, since, since) if "half_ts" in have else (since, since)
    from veliki import istrazivac   # 18.11.: the explorer's demo trades are not the rule's (its own hourly line)
    return [d for d in (dict(zip(cols, r)) for r in lcon.execute(sql, args)) if d.get("user") != istrazivac.USER]


def window(rows, t0, t1):
    """The numbers of rows (one account, one rule) in [t0, t1): entries, closed, PnL, hit, target, BE, TP, stops."""
    op = [r for r in rows if t0 <= (r.get("opened_ts") or 0) < t1]
    cl = [r for r in rows if r.get("status") == "closed" and r.get("ret") is not None
          and t0 <= (r.get("closed_ts") or 0) < t1]
    rets = [r["ret"] for r in cl]
    why = lambda r: r.get("reason") or ""  # noqa: E731
    return {"ulaza": len(op), "zatvoreno": len(cl),
            "pnl_usd": round(sum(r.get("pnl_usd") or 0.0 for r in cl), 2),
            "pnl_sol": round(sum((r["ret"] or 0.0) * (r.get("size_sol") or 0.0) for r in cl), 4),
            "pogodak": round(sum(1 for r in cl if (r.get("pnl_usd") or 0) > 0) / len(cl), 3) if cl else None,
            "ev_pct": round(sum(rets) / len(rets) * 100, 2) if rets else None,
            "cilj": sum(1 for r in cl if why(r) == "tp" or r.get("half_ts")),
            "deset": sum(1 for x in rets if x >= 0.10),
            "be": sum(1 for r in cl if why(r) == "be"),
            "tp_cijeli": sum(1 for r in cl if why(r) == "tp" and not r.get("half_ts")),
            "tp_pola": sum(1 for r in rows if r.get("half_ts") and t0 <= r["half_ts"] < t1),
            "stop": sum(1 for r in cl if why(r) == "stop"),
            "razlozi": {k: sum(1 for r in cl if why(r) == k) for k in sorted({why(r) for r in cl})}}


def chain(tpath, rows, t0, t1):
    """{"kupljeno", "odbijeno", "bez_zapisa"} of the real account's midcap buys opened in [t0, t1) on chain (trade.db
    positions mode 'live' by league_id: open / closed / pending = bought, blocked / failed = refused, no row = the
    executor never took it); None when trade.db is unreadable."""
    ids = [r["trade_id"] for r in rows if r.get("trade_id") and t0 <= (r.get("opened_ts") or 0) < t1]
    if not ids:
        return {"kupljeno": 0, "odbijeno": 0, "bez_zapisa": 0}
    tcon = ro(tpath)
    if tcon is None or not _has(tcon, "positions"):
        if tcon is not None:
            tcon.close()
        return None
    try:
        q = ",".join("?" * len(ids))
        st = {lid: s for lid, s in tcon.execute(f"SELECT league_id, status FROM positions WHERE mode='live' AND "
                                                 f"league_id IN ({q}) ORDER BY id", ids)}
    except sqlite3.Error:
        return None
    finally:
        tcon.close()
    return {"kupljeno": sum(1 for v in st.values() if v in ("open", "closed", "pending")),
            "odbijeno": sum(1 for v in st.values() if v in ("blocked", "failed")),
            "bez_zapisa": sum(1 for i in ids if i not in st)}


def price_now(lcon, mcon, tok, ids=None):
    """(price, ts) of a token now: the newest 15m bar of league.db veliki_bars (veliki/live's own quotes), else the
    collector's newest snapshot (midcap.db); (None, None) unknown."""
    best = (None, None)
    try:
        r = lcon.execute("SELECT ts, c FROM veliki_bars WHERE token=? ORDER BY ts DESC LIMIT 1", (tok,)).fetchone()
        if r and r[1]:
            best = (r[1], r[0] + 900)
    except sqlite3.Error:
        pass
    if mcon is not None:
        try:
            i = (ids or {}).get(tok)
            if i is None:
                x = mcon.execute("SELECT id FROM tokens WHERE mint=?", (tok,)).fetchone()
                i = x[0] if x else None
            if i is not None:
                r = mcon.execute("SELECT ts, px FROM snap WHERE id=? ORDER BY ts DESC LIMIT 1", (i,)).fetchone()
                if r and r[1] and (best[1] is None or r[0] > best[1]):
                    best = (r[1], r[0])
        except sqlite3.Error:
            pass
    return best


def chain_status(tpath, ids):
    """{league trade id: trade.db positions status} of the real account's rows (mode 'live'); {} unreadable."""
    ids = [i for i in ids if i]
    tcon = ro(tpath) if ids else None
    if tcon is None:
        return {}
    try:
        q = ",".join("?" * len(ids))
        return {lid: s for lid, s in tcon.execute(f"SELECT league_id, status FROM positions WHERE mode='live' AND "
                                                   f"league_id IN ({q}) ORDER BY id", ids)}
    except sqlite3.Error:
        return {}
    finally:
        tcon.close()


def open_positions(lcon, rows, mpath, now, limit=30, tpath=None):
    """The open midcap positions: account, rule, symbol, entry, price now and its %, stop %, target %, half sold; a
    real row whose buy the executor refused (trade.db blocked / failed, or no order) says so (lanac)."""
    u = users()
    acc = {v: k for k, v in u.items()}
    mcon = ro(mpath)
    out = []
    cs = chain_status(tpath, [r.get("trade_id") for r in rows if r.get("status") == "open" and r.get("user") == u["pravi"]])
    try:
        for r in rows:
            if r.get("status") != "open" or r.get("user") not in acc:
                continue
            e = r.get("entry_px") or 0
            px, pts = price_now(lcon, mcon, r["token"])
            out.append({"racun": acc[r["user"]], "pravilo": rule_of(r), "symbol": r.get("symbol") or r["token"][:6],
                        "token": r["token"], "ulaz": e, "sada": px, "sada_ts": pts,
                        "sada_pct": round((px / e - 1) * 100, 2) if px and e else None,
                        "stop_pct": round((r["stop_px"] / e - 1) * 100, 2) if r.get("stop_px") and e else None,
                        "cilj_pct": round((r["tp_px"] / e - 1) * 100, 2) if r.get("tp_px") and e else None,
                        "be": bool(r.get("be_px") and r.get("stop_px") and r["stop_px"] >= r["be_px"] * 0.999),
                        "pola": bool(r.get("half_ts")), "sati": round((now - (r.get("opened_ts") or now)) / 3600, 1),
                        "sol": r.get("size_sol"),
                        "lanac": (cs.get(r.get("trade_id"), "bez naloga") if acc[r["user"]] == "pravi" and tpath
                                  else None)})
    finally:
        if mcon is not None:
            mcon.close()
    out.sort(key=lambda x: (x["racun"] != "pravi", -(x["sada_pct"] if x["sada_pct"] is not None else -999)))
    return out[:limit]


def trading(now, p=None):
    """{"jucer": {"od", "do", "dan"}, "rows": [{"racun", "pravilo", "jucer": window, "7d": window, "lanac"}],
    "otvoreno": [...]} or None without league.db / veliki_trades."""
    p = p or paths()
    lcon = ro(p["league"])
    if lcon is None or not _has(lcon, "veliki_trades"):
        if lcon is not None:
            lcon.close()
        return None
    try:
        d0 = day_start(now)
        y0 = day_start(d0 - 3600)
        since = min(y0, now - 7 * DAY)
        rows = vrows(lcon, since)
        u = users()
        out_rows = []
        for acc, user in (("demo", u["demo"]), ("pravi", u["pravi"])):
            mine = [r for r in rows if r.get("user") == user]
            for rk, _name in RULES:
                rr = [r for r in mine if rule_of(r) == rk]
                x = {"racun": acc, "pravilo": rk, "jucer": window(rr, y0, d0), "7d": window(rr, now - 7 * DAY, now + 1),
                     "danas": window(rr, d0, now + 1), "otvoreno": sum(1 for r in rr if r.get("status") == "open")}
                if acc == "pravi":
                    x["lanac"] = {"jucer": chain(p["trade"], rr, y0, d0), "7d": chain(p["trade"], rr, now - 7 * DAY, now + 1)}
                out_rows.append(x)
        return {"jucer": {"od": y0, "do": d0, "dan": time.strftime("%d.%m.", time.gmtime(y0 + 7200))},
                "po_rezimu": by_regime(rows, u, now - 7 * DAY),
                "rows": out_rows, "otvoreno": open_positions(lcon, rows, p["midcap"], now, tpath=p["trade"]),
                "otvoreno_n": sum(1 for r in rows if r.get("status") == "open")}
    except sqlite3.Error:
        return None
    finally:
        lcon.close()


def by_regime(rows, u, t0):
    """16.11. (veliki/makro.tag): the trades closed since t0 by the macro label of their entry ("oporavak", risk_on,
    neutral; rows before the label: "bez oznake") and, inside "oporavak", by the influencers' mood and by the token's
    answer to BTC (veliki/odziv: the upper / lower half of the measured ones). [{racun, rezim, n, ev, ci, zbroj}]."""
    out = []
    for acc in ("demo", "pravi"):
        mine = [r for r in rows if r.get("user") == u[acc] and r.get("status") == "closed" and r.get("ret") is not None
                and (r.get("closed_ts") or 0) >= t0]
        groups = {}
        for r in mine:
            tg = (r.get("makro") or "bez oznake")
            base, _, mood = tg.partition("/")
            groups.setdefault(base, []).append(r)
            if base == "oporavak":
                groups.setdefault("oporavak, influenceri " + ("bikovski" if mood.endswith("_bik") else
                                                              "nisu bikovski" if mood else "nepoznato"), []).append(r)
                sc = _btc_up(r)
                if sc is not None:
                    groups.setdefault("oporavak, odziv na BTC " + ("jak" if sc >= 1.0 else "slab"), []).append(r)
        for k in sorted(groups, key=lambda x: (not x.startswith("oporavak"), x)):
            rr = groups[k]
            ev, ci = ev_ci([r["ret"] for r in rr])
            out.append({"racun": acc, "rezim": k, "n": len(rr), "ev": ev, "ci": ci,
                        "zbroj": round(sum(r.get("pnl_usd") or 0.0 for r in rr), 2)})
    return out


def _btc_up(r):
    try:
        return float(((json.loads(r.get("prio") or "{}") or {}).get("btc_up") or {}).get("score"))
    except (ValueError, TypeError):
        return None


# ---------- the rules: out-of-sample EV and real money ----------------------------------------------------------------

def rules(now, p=None):
    """{"range": {...}, "intra": {...}, "prekidac", "nacin", "zasto"}: each rule's holdout / replay (n, EV, CI 95 % by
    day, hit, the size) and whether real money may buy it now. None when veliki/ does not import."""
    p = p or paths()
    try:
        from veliki import gate, store as vstore
    except Exception:  # noqa: BLE001
        return None
    tcon = ro(p["trade"])
    try:
        proof = vstore.proof(p["veliki"]) or {}
        _ts, run = vstore.latest(p["veliki"])
        run = run or {}
        caps = gate.real_caps()
        ok7, why7, x7 = gate.wf_proof(proof, caps["size_sol"])
        if tcon is None:   # never gate.real_refusal(con=None): its proof_mode would open (create) trade.db
            refusal, mode, switch = "trade.db nije dostupan: bez pravog novca", "walk", False
        else:
            refusal = gate.real_refusal(con=tcon, proof=proof, now=now)
            mode, switch = gate.proof_mode(con=tcon), gate.switch_on(tcon)
    except Exception as e:  # noqa: BLE001 - never break the report on this part
        return {"greska": f"{type(e).__name__}"}
    finally:
        if tcon is not None:
            tcon.close()
    x7 = x7 or {}
    intra = run.get("intra") or {}
    lr = run.get("live_rule") or {}
    out = {"prekidac": switch, "nacin": mode, "zasto": refusal, "run_ts": _ts, "dana": run.get("days"),
           "range": {"naziv": "raspon 7 d", "kljuc": lr.get("key"), "izvor": ("walk-forward holdout "
                                                                                  f"{caps['size_sol']:g} SOL").replace(".", ","),
                     "n": x7.get("n"), "ev_pct": x7.get("ev_pct"), "ci": x7.get("ci95_day_pct"), "hit": x7.get("hit"),
                     "usd_dan": x7.get("usd_day"), "dokaz": ok7, "dokaz_zasto": why7,
                     "pravi": refusal is None and ok7,
                     "pravi_zasto": (refusal or ("" if ok7 else f"samo demo dok holdout nije pozitivan ({why7})"))},
           "intra": {"naziv": "dnevni raspon", "kljuc": "intra/tp10+pola/tr5/stop-zona/24h",
                     "izvor": "replay 15m svijeća, 0,1 SOL", "n": intra.get("n"), "ev_pct": intra.get("ev_pct"),
                     "ci": intra.get("ci95_day_pct"), "hit": intra.get("hit"), "usd_dan": intra.get("usd_day"),
                     "deset": intra.get("ten_n"), "pravi": refusal is None,
                     "pravi_zasto": refusal or "samo tokeni velike liste (starost 15+ d, MC 5-150M, likvidnost 500k+)"}}
    return out


def replay(now, p=None):
    """The intraday rule replayed over every midcap collector member (veliki/replay.summary of midcap.db kv "replay":
    {"presuda", "redovi", "nalazi", "napomene", "pristranosti", ...}); None before its first run."""
    p = p or paths()
    try:
        from veliki import replay as vreplay
        return vreplay.summary(vreplay.latest(p["midcap"]))
    except Exception:  # noqa: BLE001 - the test is one part of the report
        return None


REPLAY_NAME = "Dnevni raspon: povijesni test na svim midcapovima"


# ---------- the wallet, the caps, the 1 SOL floor ---------------------------------------------------------------------

def wallet(now, p=None, trade_rows=None):
    """{"value_sol", "value_usd", "pnl_24h_sol", "pnl_sol", "ts", "pod_sol", "pod_ok", "vrijednost", "izvor",
    "stropovi", "dan_pravi_sol"}; {} when nothing is known."""
    p = p or paths()
    out = {}
    tcon = ro(p["trade"])
    try:
        if _has(tcon, "equity"):
            from trade import equity
            s = equity.summary(tcon, now)
            if s:
                out.update(value_sol=s.get("value_sol"), value_usd=s.get("value_usd"), pnl_24h_sol=s.get("pnl_24h_sol"),
                           pnl_sol=s.get("pnl_sol"), ts=s.get("last_ts"), sol_usd=s.get("sol_usd"))
        try:
            from trade import executor
            fl = executor.equity_floor(executor.load_config())
            val, src = executor.equity_value(tcon, now) if tcon is not None else (None, "nepoznato")
        except Exception:  # noqa: BLE001 - executor unreadable: the owner's 1 SOL and the snapshot
            fl, val, src = 1.0, None, "nepoznato"
        if val is None and out.get("value_sol") is not None:
            val, src = out["value_sol"], "zadnja snimka (starija od 30 min)"
        out.update(pod_sol=fl, vrijednost=val, izvor=src, pod_ok=(None if val is None else val >= fl))
    except Exception:  # noqa: BLE001
        pass
    finally:
        if tcon is not None:
            tcon.close()
    try:
        from veliki import gate
        out["stropovi"] = gate.real_caps()
    except Exception:  # noqa: BLE001
        out["stropovi"] = None
    u = users()
    d0 = day_start(now)
    rr = [r for r in trade_rows or [] if r.get("user") == u["pravi"] and r.get("status") == "closed"
          and (r.get("closed_ts") or 0) >= d0 and r.get("ret") is not None]
    out["dan_pravi_sol"] = round(sum(r["ret"] * (r.get("size_sol") or 0) for r in rr), 4)
    out["dan_pravi_n"] = len(rr)
    return out


# ---------- the market ------------------------------------------------------------------------------------------------

def market(now, p=None, movers=5):
    """{"btc": {"stanje", "zasto", "chg24"}, "makro": {...} or None, "svemir": {...}, "gore": [...], "dolje": [...]}."""
    p = p or paths()
    out = {"btc": None, "makro": None, "svemir": {}, "gore": [], "dolje": []}
    try:
        from veliki import rule, store as vstore
        vcon = vstore.ro(p["veliki"])
        try:
            h = vstore.btc_hourly(vcon) if vcon is not None else []
        finally:
            if vcon is not None:
                vcon.close()
        cr = rule.crash_of(h)
        st, why = cr.regime(now)
        out["btc"] = {"stanje": st, "zasto": why, "chg24": cr.chg(now, 24), "poznato": cr.known(now),
                      "cijena": h[-1][1] if h else None}
    except Exception:  # noqa: BLE001
        pass
    try:
        from veliki import makro
        v = makro.current(now, path=p["midcap"], max_age_s=6 * 3600)
        if v:
            pl = v.get("platforms") or {}
            out["makro"] = {"rezim": v.get("regime"), "zasto": v.get("why"), "ts": v.get("ts"),
                            "meme_chg": (pl.get("meme") or {}).get("chg"),
                            "platforme": {k: (pl.get(k) or {}).get("chg") for k in ("pump.fun", "PumpSwap", "Raydium",
                                                                                    "Meteora", "trading appovi")
                                          if pl.get(k)},
                            "sektor_chg24": (v.get("sector") or {}).get("mcap_chg24"),
                            "sektor_mcap": (v.get("sector") or {}).get("mcap"),
                            "midcap_chg": (v.get("midcaps") or {}).get("chg"), "btc24": v.get("btc24")}
            ok, why = makro.bull(now, snap=v)
            out["makro"]["bull"], out["makro"]["bull_zasto"] = ok, why
            op = v.get("oporavak") or {}
            out["makro"]["oporavak"] = {"da": makro.is_recovery(v), "zasto": op.get("why"), "mood": op.get("mood")}
    except Exception:  # noqa: BLE001
        pass
    mcon = ro(p["midcap"])
    try:
        if mcon is not None and _has(mcon, "tokens"):
            mem = mcon.execute("SELECT mint, id, symbol, mcap, vol24, trend FROM tokens WHERE member=1 "
                               "ORDER BY vol24 DESC").fetchall()
            out["svemir"] = {"clanova": len(mem), "trending": sum(1 for m in mem if m[5] is not None)}
            ch = []
            for mint, i, sym, mc, v24, tr in mem[:300]:
                r = mcon.execute("SELECT ts, c24, mc FROM snap WHERE id=? ORDER BY ts DESC LIMIT 1", (i,)).fetchone()
                if r and r[1] is not None and now - r[0] <= 6 * 3600:
                    ch.append({"symbol": sym or mint[:6], "token": mint, "chg24": r[1], "mcap": r[2] or mc,
                               "trending": tr is not None})
            ch.sort(key=lambda x: -x["chg24"])
            out["gore"] = [x for x in ch[:movers] if x["chg24"] > 0]
            out["dolje"] = [x for x in ch[::-1][:movers] if x["chg24"] < 0]
    except sqlite3.Error:
        pass
    finally:
        if mcon is not None:
            mcon.close()
    try:
        from veliki import store as vstore
        out["svemir"]["lista"] = len((vstore.the_list(p["veliki"]) or {}).get("tokens") or [])
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------- research ----------------------------------------------------------------------------------------------------

def insajderi2(now, p=None):
    """Insajderi 2.0: the flag, the verdict, events / confirmed groups, the copy walk-forward at MC >= 5M and the demo
    (league.db insajderi2_trades, net of the calibrated cost). None before its first pass and without a demo."""
    p = p or paths()
    s = {}
    try:
        from insajderi import run as irun
        s = irun.summary(p["insajderi"]) or {}
    except Exception:  # noqa: BLE001
        s = {}
    demo = demo_insajderi(now, p)
    if not s and not (demo or {}).get("n") and not (demo or {}).get("otvoreno"):
        return None
    cp = (s.get("copy") or {}).get("nasa_pravila") or {}
    try:
        from trade import settings
        flag = settings.flag("insajderi2")
    except Exception:  # noqa: BLE001
        flag = None
    return {"zastavica": flag, "ts": s.get("ts"), "dogadaja": s.get("events"), "potvrdenih": s.get("confirmed"),
            "kopirati": bool(s.get("copyable")), "odluka": s.get("verdict"),
            "wf": {"n": cp.get("n"), "ev_pct": cp.get("ev_pct")}, "demo": demo}


def demo_insajderi(now, p=None):
    p = p or paths()
    lcon = ro(p["league"])
    if not _has(lcon, "insajderi2_trades"):
        if lcon is not None:
            lcon.close()
        return None
    try:
        from trade import settings
        user = settings.PAPER_USER
    except Exception:  # noqa: BLE001
        user = "autopilot-paper"
    try:
        rows = lcon.execute("SELECT pnl_usd, ret, closed_ts FROM insajderi2_trades WHERE user=? AND status='closed'",
                            (user,)).fetchall()
        n_open = lcon.execute("SELECT COUNT(*) FROM insajderi2_trades WHERE user=? AND status='open'",
                              (user,)).fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        lcon.close()
    try:
        from trade import cost
        adj = cost.demo_adjust()
    except Exception:  # noqa: BLE001
        adj = 0.0
    rets = [r + adj for _p, r, _t in rows if r is not None]
    ev, ci = ev_ci(rets)
    w = lambda t0: [x for x in rows if (x[2] or 0) >= t0]  # noqa: E731
    return {"n": len(rows), "otvoreno": n_open, "ev_pct": ev, "ci": ci,
            "pogodak": round(sum(1 for x in rets if x > 0) / len(rets), 3) if rets else None,
            "pnl_usd": round(sum(x[0] or 0 for x in rows), 2),
            "d24": {"n": len(w(now - DAY)), "pnl_usd": round(sum(x[0] or 0 for x in w(now - DAY)), 2)},
            "d7": {"n": len(w(now - 7 * DAY)), "pnl_usd": round(sum(x[0] or 0 for x in w(now - 7 * DAY)), 2)}}


def kopija(now, p=None):
    """16.11. (vlasnik: "kako ovdje postoji profitabilni wallet, a mi nemamo profitabilnu strategiju"): what WE would
    have earned copying the proven wallets (wallets/kopija.summary of wallets.db copy_rank_kv "kopija": the verdict, the
    small table, the decomposition, what is stale) and the demo copies so far (wallets/kopija_demo.stats, league.db
    kopija_trades); None before the first run and without a demo copy table."""
    p = p or paths()
    try:
        from wallets import kopija as wk
        out = wk.summary(wk.latest(p.get("wallets")), now)
    except Exception:  # noqa: BLE001
        out = None
    try:
        from wallets import kopija_demo
        demo = kopija_demo.stats(now=now, path=p["league"])
    except Exception:  # noqa: BLE001
        demo = None
    if out is None and demo is None:
        return None
    return {**(out or {}), "demo": demo}


KOPIJA_NAME = "Kopija dokazanih novčanika"
KIND_HR = {"pre_listing": "prije listinga", "deposit_sell": "depozit na burzu (prodaja)"}


def holderi(now, p=None):
    """The holders / listing signals: new in 24 h by kind, the 3 strongest, and per kind the measured 24 h move against
    the control (holderi/view.measure's rule: pre_listing from min_score, deposit_sell from 30). None without them."""
    p = p or paths()
    try:
        from holderi import burze, run as hrun
        min_score = hrun.config().get("min_score", 60)
        names = burze.NAMES
    except Exception:  # noqa: BLE001
        min_score, names = 60, {}
    con = ro(p["holderi"])
    if not _has(con, "signals"):
        if con is not None:
            con.close()
        return None
    try:
        new = con.execute("SELECT kind, COUNT(*) FROM signals WHERE ts >= ? GROUP BY kind", (now - DAY,)).fetchall()
        top = con.execute("SELECT symbol, mint, kind, exchange, score, mcap FROM signals WHERE ts >= ? ORDER BY score DESC "
                          "LIMIT 3", (now - DAY,)).fetchall()
        mj = {k: measure(con, k, min_score if k == "pre_listing" else 30, now) for k in KIND_HR}
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return {"novi_24h": {k: n for k, n in new}, "min_score": min_score,
            "top": [{"symbol": s or m[:6], "kind": k, "burza": names.get(x, x), "score": sc, "mcap": mc}
                    for s, m, k, x, sc, mc in top],
            "mjerenje": mj}


def measure(con, kind, min_score, now, h="24h"):
    """{"n", "ev_pct", "ci", "pogodak", "kontrola_pct", "d24", "d7"}: the token's move h after the signal."""
    rows = con.execute(f"SELECT px, px_{h}, ctl_{h}, ts FROM signals WHERE kind=? AND score >= ? AND px > 0 AND "
                       f"px_{h} > 0", (kind, min_score)).fetchall()
    rets = [b / a - 1 for a, b, _c, _t in rows]
    ev, ci = ev_ci(rets)
    ctl = [c for _a, _b, c, _t in rows if c is not None]
    cnt = lambda t0: con.execute("SELECT COUNT(*) FROM signals WHERE kind=? AND score >= ? AND ts >= ?",  # noqa: E731
                                 (kind, min_score, t0)).fetchone()[0]
    return {"n": len(rets), "ev_pct": ev, "ci": ci,
            "pogodak": round(sum(1 for x in rets if x > 0) / len(rets), 3) if rets else None,
            "kontrola_pct": round(sum(ctl) / len(ctl), 2) if ctl else None,
            "d24": {"n": cnt(now - DAY)}, "d7": {"n": cnt(now - 7 * DAY)}}


# ---------- costs ------------------------------------------------------------------------------------------------------

def costs(now, p=None):
    """Yesterday's (UTC) cost per source (usage.db daily_cost, usage/daily.py): the saved dict, or None."""
    p = p or paths()
    try:
        from usage import daily
        rows = daily.days(3, now, p["usage"])
    except Exception:  # noqa: BLE001
        return None
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    prev = [d for d in rows if (d.get("day") or "") < today]
    return (prev or rows or [None])[0]


# ---------- the microcap strategies' final result (archived) -----------------------------------------------------------

def mikrokap(now):
    """{"racuna", "zatvoreno", "otvoreno", "pnl_usd", "najbolji", "najgori", "od"} of the paused microcap comparison
    accounts (strat/), None before strat.db exists."""
    try:
        from strat import run as srun, store as sstore
        cfg = srun.load_config()
        con = sstore.ro()
        if con is None:
            return None
        try:
            summ = srun.summary(con, cfg, srun.exit_rules(now))
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - never break the report on the archive line
        return None
    acc = [s for s in summ if not s.get("baseline")]
    if not acc or not any(s["closed"] + s["open"] for s in acc):
        return None
    best = max(acc, key=lambda s: s["ret"])
    worst = min(acc, key=lambda s: s["ret"])
    return {"racuna": len(acc), "zatvoreno": sum(s["closed"] for s in acc), "otvoreno": sum(s["open"] for s in acc),
            "pnl_usd": round(sum(s["value"] - (cfg["bankroll_usd"] + (s.get("topup") or 0)) for s in acc), 2),
            "najbolji": {"name": best["name"], "ret": round(best["ret"], 4)},
            "najgori": {"name": worst["name"], "ret": round(worst["ret"], 4)}, "od": MIKROKAP_SINCE}


# ---------- one row per midcap strategy (/strategije and the report) ---------------------------------------------------

def _row(naziv, vrsta, n, ev, ci, hit, d24=None, d7=None, opis="", ci_label="90 %"):
    return {"naziv": naziv, "vrsta": vrsta, "n": n or 0, "ev_pct": ev, "ci": ci, "ci_label": ci_label, "pogodak": hit,
            "d24": d24, "d7": d7, "opis": opis}


def _wnd(rows, t0):
    cl = [r for r in rows if (r.get("closed_ts") or 0) >= t0]
    return {"n": len(cl), "pnl_usd": round(sum(r.get("pnl_usd") or 0 for r in cl), 2)}


def strategies(now=None, p=None, rinfo=None, hd=None, rp=None, kp=None):
    """[row] of every midcap strategy measured so far: the veliki demo and the real account by rule (closed trades at
    the real cost), the Insajderi 2.0 demo, the listing signals (measurement, no money), the 7-day rule's holdout at
    the real size, the intraday rule's replay (the veliki list, and veliki/replay.py's over every collector member:
    its holdout) and the walk-forward variants (holdout at the demo size)."""
    now = int(now or time.time())
    p = p or paths()
    out = []
    u = users()
    lcon = ro(p["league"])
    try:
        allc = vrows(lcon, closed_only=True) if lcon is not None else []
    except sqlite3.Error:
        allc = []
    finally:
        if lcon is not None:
            lcon.close()
    rinfo = (rules(now, p) if rinfo is None else rinfo) or {}
    for acc, vrsta in (("demo", "demo"), ("pravi", "pravi")):
        for rk, rname in RULES:
            rr = [r for r in allc if r.get("user") == u[acc] and rule_of(r) == rk]
            ev, ci = ev_ci([r["ret"] for r in rr])
            hit = round(sum(1 for r in rr if (r.get("pnl_usd") or 0) > 0) / len(rr), 3) if rr else None
            ri = rinfo.get(rk) or {}
            if acc == "demo":
                opis = ("0,1 SOL, cijeli profit na +10 % neto, BE na +5 %" if rk == "intra"
                        else "0,5 SOL, zona 7 d, stop −20 %, BE na +5 %")
            else:
                opis = "dopušten sada" if ri.get("pravi") else ("ne kupuje: " + (ri.get("pravi_zasto") or "?"))
            out.append(_row(f"Midcap {rname}", vrsta, len(rr), ev, ci, hit, _wnd(rr, now - DAY), _wnd(rr, now - 7 * DAY),
                            opis))
    di = demo_insajderi(now, p)
    if di is not None:
        out.append(_row("Insajderi 2.0 (kopija grupa)", "demo", di["n"], di["ev_pct"], di["ci"], di["pogodak"],
                        di["d24"], di["d7"], f"otvoreno {di['otvoreno']}; pravi novac nikad iz ovog alata"))
    kp = kopija(now, p) if kp is None else kp
    kd = (kp or {}).get("demo")
    if kd is not None:   # 16.11. (wallets/kopija_demo.py): the prospective copies of the proven wallets, demo only
        late = (f"; kašnjenje tipično {kd['kasnjenje_med_s']:.0f} s" if kd.get("kasnjenje_med_s") is not None else "")
        out.append(_row(f"{KOPIJA_NAME} (i ispod 5M)", "demo", kd["n"], kd["ev_pct"], kd["ci"], kd["pogodak"], kd["d24"],
                        kd["d7"], f"otvoreno {kd['otvoreno']}{late}; pravi novac nikad iz ovog alata"))
    if kp and kp.get("redovi"):   # the copier's walk-forward (wallets/kopija.py): the pre-declared primary rule
        x = kp["redovi"][0]
        if x.get("malo"):
            out.append(_row(f"{KOPIJA_NAME}: povijesni test", "backtest", x.get("n") or 0, None, None, None,
                            opis="premalo podataka (manje od 30 kopija s poznatom cijenom)"))
        else:
            out.append(_row(f"{KOPIJA_NAME}: povijesni test", "backtest", x["n"], x.get("ev_pct"), x.get("ci"),
                            x.get("pogodak"), opis=f"izvan uzorka (zadnjih {kp.get('dana_izvan')} d): ulaz 60 s nakon "
                            f"novčanika, njegov izlaz ili stop −20 %, {str(kp.get('ulog_sol')).replace('.', ',')} SOL, nakon "
                            f"troška; nekopirano {(x.get('nekopirano') or 0):.0%} njegovih kupnji"))
    hd = holderi(now, p) if hd is None else hd
    for k, x in ((hd or {}).get("mjerenje") or {}).items():
        out.append(_row(f"Signal holdera: {KIND_HR[k]}", "mjerenje", x["n"], x["ev_pct"], x["ci"], x["pogodak"],
                        x["d24"], x["d7"], "kretanje 24 h nakon signala, bez novca"
                        + (f"; kontrola {x['kontrola_pct']:+.1f} %" if x.get("kontrola_pct") is not None else "")))
    try:
        from veliki import store as vstore
        _ts, run = vstore.latest(p["veliki"])
    except Exception:  # noqa: BLE001
        run = None
    run = run or {}
    r7 = rinfo.get("range") or {}
    if r7.get("n") is not None:
        out.append(_row(f"Raspon 7 d: {r7['izvor']}", "backtest", r7["n"], r7.get("ev_pct"), r7.get("ci"), r7.get("hit"),
                        opis="dokaz za pravi novac: " + ("prolazi" if r7.get("dokaz") else (r7.get("dokaz_zasto") or "ne")),
                        ci_label="95 % po danu"))
    ri = rinfo.get("intra") or {}
    if ri.get("n") is not None:
        out.append(_row(f"Dnevni raspon: {ri['izvor']}", "backtest", ri["n"], ri.get("ev_pct"), ri.get("ci"),
                        ri.get("hit"), opis=f"≥ +10 %: {ri.get('deset') or 0}", ci_label="95 % po danu"))
    rp = replay(now, p) if rp is None else rp
    if rp:   # 16.11. (veliki/replay.py): the holdout row (the last 40 % of the days), else all days, else "premalo"
        rows_ = rp.get("redovi") or []
        ho = rows_[1] if len(rows_) > 1 else {}
        x = ho if not ho.get("malo") else (rows_[0] if rows_ and not rows_[0].get("malo") else {})
        what = ("izvan uzorka (zadnjih " + str(rp.get("dana_izvan")) + " d)" if x is ho and x else
                "svi dani (izvan uzorka premalo tradeova)" if x else "premalo podataka (manje od 30 tradeova)")
        out.append(_row(REPLAY_NAME, "backtest", x.get("n") or ho.get("n") or 0, x.get("ev_pct"), x.get("ci"),
                        x.get("pogodak"), opis=f"{what}; {rp.get('tokena')} tokena, {rp.get('dana')} dana svijeća od "
                        f"15 min, {str(rp.get('ulog_sol')).replace('.', ',')} SOL, trošak kruga "
                        f"{str(rp.get('trosak_pct')).replace('.', ',')} %; nalaza {rp.get('nalaza') or 0}"))
    try:
        from veliki import walk
        size = f"{walk.DEMO_SIZE:g}"
    except Exception:  # noqa: BLE001
        size = "0.5"
    vh = ((((run.get("variants") or {}).get("dno") or {}).get(size) or {}).get("variants_holdout") or {})
    var = sorted(vh.items(), key=lambda kv: (kv[0] != "osnovno", -(kv[1].get("ev_pct") if kv[1].get("ev_pct") is not None
                                                                     else -1e9)))
    for k, x in var:
        if not isinstance(x, dict) or x.get("n") is None:
            continue
        extra = []
        if x.get("dca_n"):
            extra.append(f"DCA lotova {x['dca_n']}")
        if x.get("max_dd_usd") is not None:
            extra.append(f"max pad {x['max_dd_usd']:.0f} $")
        out.append(_row(f"Walk-forward: {VARIANT_HR.get(k, k.replace('_', ' '))}", "backtest", x["n"], x.get("ev_pct"),
                        x.get("ci95_day_pct"), x.get("hit"), opis=f"holdout {size.replace('.', ',')} SOL, raspon 7 d"
                        + ("; " + ", ".join(extra) if extra else ""), ci_label="95 % po danu"))
    return out


# ---------- everything for the report -------------------------------------------------------------------------------------

def collect(now):
    """The report's midcap block (see the module text). Each part on its own; never raises."""
    p = paths()
    out = {}
    for key, fn in (("trgovanje", lambda: trading(now, p)), ("pravila", lambda: rules(now, p)),
                    ("trziste", lambda: market(now, p)), ("insajderi2", lambda: insajderi2(now, p)),
                    ("holderi", lambda: holderi(now, p)), ("troskovi", lambda: costs(now, p)),
                    ("replay", lambda: replay(now, p)),
                    ("kopija", lambda: kopija(now, p)),
                    ("strategije", lambda: strategies(now, p, out.get("pravila") or {}, out.get("holderi") or {},
                                                      out.get("replay") or {}, out.get("kopija") or {})),
                    ("mikrokap", lambda: mikrokap(now))):
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001 - one part costs only itself
            out[key] = None
            print(f"report midcap {key}: {type(e).__name__}: {e}", flush=True)
    try:
        lcon = ro(p["league"])
        rows = vrows(lcon, day_start(now)) if lcon is not None else []
        if lcon is not None:
            lcon.close()
    except sqlite3.Error:
        rows = []
    try:
        out["novcanik"] = wallet(now, p, rows)
    except Exception as e:  # noqa: BLE001
        out["novcanik"] = {}
        print(f"report midcap novcanik: {type(e).__name__}: {e}", flush=True)
    return out


def dumps(d):
    return json.dumps(d, ensure_ascii=False, default=str)
