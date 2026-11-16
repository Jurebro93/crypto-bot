"""16.11. (vlasnik, jutarnji izvještaj: "zašto u strategijama nema tradeova? Treba maknuti strategije koje ne doprinose
učenju i ove s micro capovima ... Sada idemo s mid cap tokenima"; "Zašto izvještaj nije osvježen onda"), offline:

  - the morning report while fokus_midcap is on: Midcap trgovanje (yesterday / 7 days per account and rule, on chain,
    open positions, the rules' proof and real money, the wallet, the caps, the 1 SOL floor), Tržište, Istraživanje,
    Troškovi po izvoru, one microcap line with the archive link; none of the old microcap sections; the AI gets the
    midcap block (and not the microcap keys), the rule-based fallback writes midcap lines
  - the switch off: the old sections come back (one tap undoes it)
  - strat/: the microcap accounts take no new and no pending entry while the switch is on, the open ones keep exits
  - /strategije: one midcap table (demo, real, measurement, backtest) and the collapsed read-only archive
  - run_report: the owner's one-time resend after the deploy (once, logged; before REPORT_HOUR nothing extra)

make_dbs() also feeds the screenshots (scratchpad izvjestaj/shot.py).

    python3 -m unittest tests.test_izvjestaj_midcap_offline
"""
import contextlib
import io
import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NOW = 1794821400   # 2026-11-16 09:30 UTC (10:30 Zagreb); yesterday = 15.11. (Zagreb day: 14.11. 23:00 - 15.11. 23:00 UTC)
Y0 = 1794697200    # 15.11. 00:00 Zagreb
D0 = Y0 + 86400    # 16.11. 00:00 Zagreb
H = 3600
WORDS = ("ORBIT", "MOCHI", "GLINT", "TANGO", "PIXEL", "RUMBA", "COBALT", "NIMBUS", "QUARK", "ZEPHYR", "LUMEN",
         "SALSA", "FABLE", "GECKO", "HALO", "IVORY", "JUNO", "KOALA", "LOTUS", "MANGO")


def mint(i):
    return f"Mid{i:04d}" + "x" * 36


def env_for(d):
    return {"REPORT_DB_DIR": d, "VELIKI_DB": os.path.join(d, "veliki.db"), "MIDCAP_DB": os.path.join(d, "midcap.db"),
            "HOLDERI_DB": os.path.join(d, "holderi.db"), "INSAJDERI_DB": os.path.join(d, "insajderi.db")}


def _vt(lg, user, i, kind, opened, closed=None, ret=None, reason=None, half=False, size_sol=0.1, trade_id=None,
        entry=1.0, stop=0.94, tp=1.105):
    sol_usd = 150.0
    size_usd = size_sol * sol_usd
    lg.execute(
        "INSERT INTO veliki_trades (user, token, symbol, opened_ts, trade_id, size_sol, size_usd, entry_px, tp_px, "
        "stop_px, rt, drt, status, closed_ts, ret, pnl_usd, reason, kind, half_frac, half_ts, half_px, be_px, first_px, "
        "lots, why) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        (user, mint(i), WORDS[i % len(WORDS)], int(opened), trade_id, size_sol, size_usd, entry, tp, stop, 0.012, 0.01,
         "closed" if closed else "open", int(closed) if closed else None, ret,
         (ret * size_usd) if ret is not None else None, reason, kind, 0.5 if half else 0.0,
         int(opened + 2 * H) if half else None, entry * 1.11 if half else None, entry * 1.012, entry, "test"))


def make_dbs(d, now=NOW):
    """Synthetic databases of one midcap day (no network): league.db (veliki and insajderi2 demo / real trades, own
    bars), trade.db (switches, equity, live positions, the critic), veliki.db (BTC, the list, the proof, the run with
    the replay and the walk-forward variants), midcap.db (members, snapshots, the macro regime), holderi.db, insajderi.db,
    usage.db (yesterday's cost row), strat.db (the paused microcap accounts)."""
    from critic import notes as cnotes, store as cstore
    from insajderi import live as ilive, store as istore
    from holderi import store as hstore
    from trade import equity, executor, settings
    from ui import assistnotes
    from usage import daily
    from veliki import live, makro, midcap, store as vstore
    rnd = random.Random(7)
    P, L = settings.PAPER_USER, settings.LEAGUE_USER
    # ---- league.db
    lg = sqlite3.connect(os.path.join(d, "league.db"))
    live.ensure(lg)
    lg.executescript(ilive.SCHEMA)
    k = 0
    # yesterday, demo intraday: 3 whole TPs, 2 break-even, 2 stops, 1 half + trailing; 1 still open from yesterday
    for ret, why, half in ((0.104, "tp", False), (0.112, "tp", False), (0.101, "tp", False), (-0.004, "be", False),
                           (-0.003, "be", False), (-0.061, "stop", False), (-0.058, "stop", False),
                           (0.071, "trail", True)):
        k += 1
        o = Y0 + 2 * H + k * 1800
        _vt(lg, P, k, "intra", o, o + 3 * H, ret, why, half)
    # the last 7 days before yesterday, demo intraday
    for j in range(26):
        k += 1
        o = now - 7 * 86400 + 3 * H + j * 4 * H
        if o >= Y0:
            break
        ret, why = rnd.choice(((0.105, "tp"), (-0.004, "be"), (-0.07, "stop"), (0.11, "tp"), (0.06, "trail")))
        _vt(lg, P, k, "intra", o, o + 2 * H, ret, why, why == "trail")
    # demo 7-day rule (0.5 SOL): yesterday 1 stop, the week 7 more
    k += 1
    _vt(lg, P, k, "range", Y0 + 4 * H, Y0 + 20 * H, -0.2, "stop", size_sol=0.5, stop=0.8, tp=1.09)
    for j in range(7):
        k += 1
        o = now - 6 * 86400 + j * 16 * H
        ret, why = rnd.choice(((0.08, "tp"), (-0.2, "stop"), (0.0, "be"), (0.09, "tp")))
        _vt(lg, P, k, "range", o, o + 30 * H, ret, why, size_sol=0.5, stop=0.8, tp=1.09)
    # real money, intraday only: yesterday 3 entries (2 bought on chain, 1 refused by the executor), 2 closed
    real = []
    for j, (ret, why) in enumerate(((0.101, "tp"), (-0.052, "stop"), (None, None))):
        k += 1
        o = Y0 + 9 * H + j * H
        _vt(lg, L, k, "intra", o, (o + 4 * H) if ret is not None else None, ret, why, trade_id=900 + j)
        real.append((900 + j, "closed" if ret is not None else "blocked", o))
    # open now: demo intraday 3, demo 7-day 1, real 1
    for j, (entry, stop, tp) in enumerate(((1.0, 0.95, 1.106), (2.0, 1.88, 2.21), (0.5, 0.47, 0.553))):
        k += 1
        _vt(lg, P, k, "intra", now - (j + 2) * H, entry=entry, stop=stop, tp=tp)
        lg.execute("INSERT INTO veliki_bars VALUES (?,?,?,?,?,?)", (mint(k), now - 1800, entry, entry, entry,
                                                                     entry * (1.04, 0.97, 1.07)[j]))
    k += 1
    _vt(lg, P, k, "range", now - 30 * H, size_sol=0.5, entry=3.0, stop=3.04, tp=3.27)   # stop already on BE
    lg.execute("UPDATE veliki_trades SET be_px=3.03 WHERE token=?", (mint(k),))
    lg.execute("INSERT INTO veliki_bars VALUES (?,?,?,?,?,?)", (mint(k), now - 1800, 3.0, 3.0, 3.0, 3.12))
    k += 1
    _vt(lg, L, k, "intra", now - 5 * H, trade_id=950, entry=0.8, stop=0.76, tp=0.885)
    real.append((950, "open", now - 5 * H))
    lg.execute("INSERT INTO veliki_bars VALUES (?,?,?,?,?,?)", (mint(k), now - 1800, 0.8, 0.8, 0.8, 0.82))
    # Insajderi 2.0 demo: 14 closed, 2 open
    for j in range(16):
        st = "open" if j >= 14 else "closed"
        ret = rnd.uniform(-0.12, 0.25) if st == "closed" else None
        lg.execute("INSERT INTO insajderi2_trades (user, token, symbol, owner, wallet, buy_ts, opened_ts, size_usd, "
                   "status, closed_ts, pnl_usd, ret, exit_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (P, f"Ins{j:03d}" + "y" * 38, f"IN{j}", "o", "w", now - (20 - j) * 9 * H, now - (20 - j) * 9 * H,
                    50.0, st, (now - (19 - j) * 9 * H) if st == "closed" else None,
                    ret * 50 if ret is not None else None, ret, "prodali" if st == "closed" else None))
    lg.commit()
    lg.close()
    # ---- trade.db
    tp = os.path.join(d, "trade.db")
    tc = executor.connect(tp)
    for st in equity.SCHEMA:
        tc.execute(st)
    for key, mode in (("pravi_novac_veliki", "live"), ("fokus_midcap", "live"), ("insajderi2", "paper"),
                      ("veliki_range", "paper")):
        settings.put(tc, f"flag:{key}", {"mode": mode, "since": now - 86400, "who": "Jure"})
    settings.put(tc, "veliki_dokaz", "nalog_vlasnika")
    tc.execute("INSERT INTO equity VALUES (?,?,?,?,?,?,?,?)", (now - 30 * H, 3.2, 0.0, 0.0, 150.0, 0.86, 3.2, "live"))
    tc.execute("INSERT INTO equity VALUES (?,?,?,?,?,?,?,?)", (now - 300, 3.25, 0.0, 0.1, 151.0, 0.86, 0.0, "live"))
    for lid, st, o in real:
        tc.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, league_id) "
                   "VALUES (?,?,?,?,?,?,?,?)", ("t", "T", o, "live", st, "veliki: dnevni", 0.1, lid))
    cstore.ensure(tc)
    assistnotes.ensure(tc)
    cstore.book(tc, "daily", "gpt-5.4", {"in": 9000, "out": 3000}, 0.07, True, now=now - 20 * H)
    with contextlib.redirect_stdout(io.StringIO()):   # assistnotes logs every note ("mcp: asistent je zapisao ...")
        assistnotes.submit_daily_summary(tc, cnotes.KID, "Kritičar (OpenAI): dnevni pregled 16.11.",
                                         "Dnevni raspon u demu: n=34, EV +1,1 % s intervalom -0,6 do +2,8 %: edge još "
                                         "nije dokazan, ali je jedini pozitivan. Raspon 7 d gubi i u holdoutu.\n\nDrugi "
                                         "odlomak.")
        assistnotes.submit_suggestion(tc, cnotes.KID, "Kritičar: break-even prerano",
                                      "2 od 8 jučerašnjih izlaza su break-even na +5 %, a cijena je kasnije dosegla cilj.",
                                      "izmjeri BE na +6 % u replayu prije promjene")
    tc.commit()
    tc.close()
    # ---- veliki.db
    vc = vstore.connect(os.path.join(d, "veliki.db"))
    px = 91000.0
    for t in range(now // H * H - 12 * 86400, now // H * H + 1, H):
        px *= 1 + rnd.uniform(-0.004, 0.0045)
        vc.execute("INSERT OR REPLACE INTO btc_h VALUES (?,?)", (t, px))
    vstore.kv_put(vc, "list", {"ts": now - 2 * H, "tokens": [{"mint": mint(i), "symbol": WORDS[i % 20]} for i in range(24)]})
    proof = {"ts": now - 8 * H, "days": 41, "sizes": {"0.1": {"n": 181, "ev_pct": -3.9, "ci95_day_pct": [-6.1, -1.2],
                                                              "hit": 0.41, "usd_day": -0.8}}}
    vstore.kv_put(vc, "proof", proof)
    vh = {"osnovno": (152, 0.42, -1.1), "cijeli_trailing": (152, 0.39, -1.6), "dca_10_bez_uvjeta": (152, 0.44, -2.4),
          "dca_10": (152, 0.43, -0.7), "dca_zona": (152, 0.43, -0.9), "dca_atr": (152, 0.42, -1.0),
          "razlozi": (152, 0.45, -0.4), "makro_filter": (118, 0.47, 0.3), "makro_indeks": (104, 0.48, 0.6),
          "sve": (118, 0.46, 0.2), "siri_ulaz": (236, 0.40, -1.4), "stop_na_dnu_svijece": (152, 0.41, -1.3),
          "btc_okrenut_gore": (61, 0.49, 0.9)}
    run = {"days": 41, "live_rule": {"key": "tp8%+tr5/pct20/3d/z7d"}, "proof": proof,
           "intra": {"n": 412, "per_day": 10.1, "hit": 0.56, "ev_pct": 1.15, "usd_day": 0.6, "ci95_day_pct": [-0.4, 2.7],
                     "ten_n": 133, "half_n": 40},
           "variants": {"dno": {"0.5": {"n": 152, "variants_holdout": {
               k2: {"n": n, "hit": h, "ev_pct": ev, "ci95_day_pct": [round(ev - 2.4, 2), round(ev + 2.1, 2)],
                    "max_dd_usd": 30 + i * 3, "dca_n": 12 if "dca" in k2 or k2 == "sve" else 0}
               for i, (k2, (n, h, ev)) in enumerate(vh.items())}}}}}
    vc.execute("INSERT INTO runs VALUES (?,?)", (now - 8 * H, json.dumps(run)))
    vc.commit()
    vc.close()
    vstore.reset_cache()
    # ---- midcap.db
    mc = midcap.connect(os.path.join(d, "midcap.db"))
    mc.executescript(makro.SCHEMA)
    for i in range(160):
        mc.execute("INSERT INTO tokens (mint, id, symbol, mcap, liq, vol24, member, trend) VALUES (?,?,?,?,?,?,1,?)",
                   (mint(1000 + i), i + 1, WORDS[i % 20] + ("" if i < 20 else str(i)), 2e6 + i * 9e5, 2e5 + i * 1e4,
                    5e6 - i * 2e4, (i % 4) if i % 3 == 0 else None))
        mc.execute("INSERT INTO snap (id, ts, px, mc, c24) VALUES (?,?,?,?,?)",
                   (i + 1, now - 120, 1.0, int(2e6 + i * 9e5), round(rnd.uniform(-35, 70), 1)))
    snap = {"ts": now - 1800, "platforms": {"meme": {"chg": 0.12}, "pump.fun": {"chg": 0.18}, "PumpSwap": {"chg": 0.09},
                                           "Raydium": {"chg": -0.04}, "Meteora": {"chg": 0.21}},
            "sector": {"mcap": 8.4e9, "mcap_chg24": 2.1, "vol24": 1.2e9}, "midcaps": {"chg": 0.07},
            "btc_state": "normalno", "btc24": 0.012, "regime": "neutral",
            "why": "volumen meme platformi +12 %, midcapovi +7 %", "src": "market.db"}
    mc.execute("INSERT INTO makro_h VALUES (?,?,?)", (now // H * H, "neutral", json.dumps(snap)))
    mc.commit()
    mc.close()
    # ---- holderi.db
    hc = hstore.connect(os.path.join(d, "holderi.db"))
    for j, (kind, ex, sc, p24, c24, ago) in enumerate((("pre_listing", "binance", 82, 1.14, 1.5, 5),
                                                       ("pre_listing", "bybit", 71, 1.05, -0.5, 30),
                                                       ("deposit_sell", "mexc", 64, 0.91, 0.3, 50),
                                                       ("pre_listing", "okx", 66, None, None, 2),
                                                       ("pre_listing", "gate", 61, 0.97, 0.2, 90))):
        hc.execute("INSERT INTO signals (mint, symbol, ts, kind, exchange, score, reasons, mcap, px, px_24h, ctl_24h) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (mint(j + 30), WORDS[(j + 30) % 20], now - ago * H, kind, ex, sc,
                                                       "[]", 9e6, 1.0, p24, c24))
    hc.commit()
    hc.close()
    # ---- insajderi.db
    ic = istore.connect(os.path.join(d, "insajderi.db"))
    ic.execute("INSERT OR REPLACE INTO i2_kv VALUES ('summary', ?)", (json.dumps({
        "ts": now - 6 * H, "events": 182, "call_events": 61, "jump_events": 121, "confirmed": 4, "copyable": False,
        "verdict": "kopiranje MC ≥ 5M: EV -1,2 % (n=38), donja granica ispod nule",
        "copy": {"nasa_pravila": {"n": 38, "ev_pct": -1.2}}}),))
    ic.commit()
    ic.close()
    # ---- usage.db: yesterday's (UTC) cost row
    import time as _t
    daily.save({"day": _t.strftime("%Y-%m-%d", _t.gmtime(now - 86400)), "ts": now - 10 * H,
                "coingecko": {"kljuc": 3120, "strop": 16000, "besplatno_ukupno": 2210, "e429_ukupno": 14},
                "twitterapi": {"usd": 0.41, "dijelovi": {"twtl": 0.2, "xmom": 0.21}},
                "apify": {"usd_bot": 0.0}, "pumpportal": {"tradeova": 0, "sol": 0.0},
                "helius": {"krediti_bot": 3400, "racun": {"dan": 41000, "used": 9.1e6, "lim": 1e7, "ts": now - 11 * H}},
                "ai": {"usd": 0.0, "objava": 0},
                "openai": {"poziva": 41, "usd": 0.38, "presuda": 37, "odluke_vlasnika": {"odbijeno": 1}}},
               os.path.join(d, "usage.db"))
    # ---- strat.db: the paused microcap accounts
    from paper import sim
    from strat import store as sstore
    sc_ = sstore.connect(os.path.join(d, "strat.db"))
    for j, (key, ret) in enumerate((("kol", -0.4), ("kol", 0.3), ("kol_potvrdjen", -0.25), ("dokazani", 0.12),
                                    ("dokazani", 0.05), ("alat_veliki", -0.1))):
        sc_.execute("INSERT INTO positions (strat, token, symbol, status, size_usd, pnl_usd, ret, state, entry_ts, "
                    "closed_ts, seen_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (key, f"S{j}", f"S{j}", "closed", 50, ret * 50, ret, "{}", now - 5 * 86400, now - 4 * 86400,
                     now - 5 * 86400))
    pos = sim.open_position(1.0, 50000, now - 86400, 50, {"fee": 0.01})
    sc_.execute("INSERT INTO positions (strat, token, symbol, status, size_usd, pnl_usd, ret, state, entry_ts, last_px, "
                "last_liq, seen_ts) VALUES ('kol', 'S9', 'S9', 'open', 50, 0, 0, ?, ?, 0.9, 50000, ?)",
                (json.dumps(pos), now - 86400, now - 86400))
    sc_.execute("INSERT INTO kv VALUES ('start_ts', ?)", (str(now - 12 * 86400),))
    sc_.commit()
    sc_.close()
    return env_for(d)


class Base(unittest.TestCase):
    def setUp(self):
        from strat import store as sstore
        from trade import settings
        from veliki import live, store as vstore
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = make_dbs(self.tmp.name)
        for p in (mock.patch.dict(os.environ, env), mock.patch.object(settings, "DB", os.path.join(self.tmp.name, "trade.db")),
                  mock.patch.object(sstore, "DB", os.path.join(self.tmp.name, "strat.db"))):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("FOKUS_MIDCAP_FORCE", None)
        settings._FLAG_CACHE.clear()
        self.addCleanup(settings._FLAG_CACHE.clear)
        live._ST["btc"] = None
        vstore.reset_cache()
        self.addCleanup(vstore.reset_cache)

    def collect(self, fokus=True):
        from report import collect
        return collect.collect(NOW, fokus=fokus)


class Report(Base):
    def test_midcap_numbers(self):
        d = self.collect()
        self.assertTrue(d["fokus"])
        t = d["midcap"]["trgovanje"]
        self.assertEqual(t["jucer"]["dan"], "15.11.")
        rows = {(r["racun"], r["pravilo"]): r for r in t["rows"]}
        y = rows[("demo", "intra")]["jucer"]
        self.assertEqual((y["ulaza"], y["zatvoreno"], y["cilj"], y["be"], y["tp_cijeli"], y["tp_pola"], y["stop"]),
                         (8, 8, 4, 2, 3, 1, 2))
        self.assertAlmostEqual(y["pnl_usd"], round((0.104 + 0.112 + 0.101 - 0.004 - 0.003 - 0.061 - 0.058 + 0.071) * 15, 2))
        self.assertAlmostEqual(y["pnl_sol"], round((0.104 + 0.112 + 0.101 - 0.004 - 0.003 - 0.061 - 0.058 + 0.071) * 0.1, 4))
        self.assertEqual(y["pogodak"], round(4 / 8, 3))
        r = rows[("pravi", "intra")]
        self.assertEqual((r["jucer"]["ulaza"], r["jucer"]["zatvoreno"]), (3, 2))
        self.assertEqual(r["lanac"]["jucer"], {"kupljeno": 2, "odbijeno": 1, "bez_zapisa": 0})
        self.assertEqual(rows[("pravi", "range")]["7d"]["zatvoreno"], 0)
        op = t["otvoreno"]
        self.assertEqual(len(op), 6)
        self.assertEqual([x["racun"] for x in op[:2]], ["pravi", "pravi"])   # the real positions first
        on = {x["lanac"]: x for x in op[:2]}
        self.assertAlmostEqual(on["open"]["sada_pct"], 2.5)
        self.assertIsNone(on["blocked"]["sada_pct"])                   # refused on chain: only in the book, no price
        be = [x for x in op if x["pravilo"] == "range"][0]
        self.assertTrue(be["be"])
        pr = d["midcap"]["pravila"]
        self.assertTrue(pr["intra"]["pravi"])                          # owner's order + BTC known
        self.assertFalse(pr["range"]["pravi"])                         # holdout -3.9 %: demo only
        self.assertIn("samo demo", pr["range"]["pravi_zasto"])
        self.assertEqual((pr["range"]["n"], pr["intra"]["n"]), (181, 412))
        w = d["midcap"]["novcanik"]
        self.assertAlmostEqual(w["value_sol"], 3.35)
        self.assertTrue(w["pod_ok"])
        self.assertEqual(w["pod_sol"], 1.0)
        self.assertEqual(w["stropovi"]["max_open"], 5)
        m = d["midcap"]["trziste"]
        self.assertEqual(m["makro"]["rezim"], "neutral")
        self.assertEqual(m["svemir"]["clanova"], 160)
        self.assertEqual(m["svemir"]["lista"], 24)
        self.assertEqual(len(m["gore"]), 5)
        self.assertGreater(m["gore"][0]["chg24"], m["gore"][-1]["chg24"])
        self.assertTrue(m["btc"]["poznato"])
        self.assertEqual(d["midcap"]["insajderi2"]["demo"]["n"], 14)
        self.assertEqual(d["midcap"]["holderi"]["novi_24h"], {"pre_listing": 2})
        self.assertEqual(d["midcap"]["troskovi"]["openai"]["poziva"], 41)
        mk = d["midcap"]["mikrokap"]
        self.assertEqual((mk["zatvoreno"], mk["otvoreno"]), (6, 1))
        for k in ("paper", "kols", "today", "pulse", "koltest", "strategije", "skener", "rules", "momentum"):
            self.assertNotIn(k, d)                                     # the microcap data is not even collected

    def test_render_sections_present_and_absent(self):
        from report import ai, render
        d = self.collect()
        html = render.render(d, ai.fallback(d), "pravila")
        for s in ("Midcap trgovanje", "Jučer (15.11.)", "Zadnjih 7 dana", "Na lancu: kupljeno / odbijeno",
                  "Break-even", "TP cijeli / pola", "Otvorene pozicije (6)", "na lancu odbijeno: samo u knjizi", "Pravila: dokaz izvan uzorka",
                  "Pravi novac: DA", "Pravi novac: NE", "Pod 1 SOL: iznad", "Stropovi pravog novca", "Tržište",
                  "Makro režim: neutralno", "Midcap svemir: 160 tokena", "Najviše gore 24 h", "Istraživanje",
                  "Insajderi 2.0", "Holderi i listing", "Kritičar (OpenAI)", "break-even prerano", "Troškovi po izvoru",
                  "OpenAI kritičar", "Mikrokap strategije pauzirane od 15.11.", "/strategije#arhiva",
                  "Usporedba midcap strategija"):
            self.assertIn(s, html)
        for s in ("Usporedba strategija</div>", "KOL test", "Demo trading (7 dana)", "Influenceri (KOL)",
                  "Tokeni za danas", "Konstantan rast", "Što sam naučio", "Skener tržišta", "Momentum scalp",
                  "Insajderi prije poziva", "Nova pravila ulaza", "Arhiva mikrokapova"):
            self.assertNotIn(s, html)
        self.assertNotIn("<script", html)
        self.assertNotIn("<svg", html)

    def test_ai_gets_midcap_not_microcap(self):
        from report import ai
        d = self.collect(fokus=False)
        self.assertIn("paper", d)                                      # the switch off: the old data is collected
        d["fokus"] = True
        c = ai.compact(d)
        self.assertIn("midcap", c)
        for k in ai.MIKRO_KEYS:
            self.assertNotIn(k, c)
        self.assertLessEqual(len(c["midcap"]["trgovanje"]["otvoreno"]), 15)
        self.assertIn("raspon 7 d", ai.SYSTEM)
        self.assertNotIn("pump.fun)", ai.SYSTEM.split("\n")[0])
        fb = ai.fallback(d)
        self.assertEqual(set(fb), set(ai.SCHEMA["required"]))
        self.assertTrue(any("dnevni raspon" in x for x in fb["trgovanje"]))
        self.assertTrue(fb["naslov"].startswith("Midcap jučer: demo"))
        os.environ.pop("ANTHROPIC_API_KEY", None)
        out, src = ai.interpret(d)
        self.assertEqual(src, "pravila")

    def test_switch_off_brings_the_old_sections_back(self):
        from report import ai, render
        d = self.collect(fokus=False)
        html = render.render(d, ai.fallback(d), "pravila")
        self.assertIn("Midcap trgovanje", html)
        self.assertIn("Demo trading (7 dana)", html)
        self.assertNotIn("Mikrokap strategije pauzirane", html)


class Strategije(Base):
    def test_midcap_table_and_archive(self):
        from ui import strategije
        with mock.patch.dict(os.environ, {"FOKUS_MIDCAP_FORCE": "1"}), \
                mock.patch("strat.run.exit_rules", lambda now: {"fee": 0.01}):
            title, body = strategije.page({})
        self.assertEqual(title, "Usporedba strategija")
        for s in ("Midcap strategije (MC 2M–200M)", "Midcap dnevni raspon", "Midcap raspon 7 d", ">demo<",
                  ">pravi novac<", ">backtest<", ">mjerenje<", "Insajderi 2.0", "Signal holdera: prije listinga",
                  "Raspon 7 d: walk-forward holdout", "Dnevni raspon: replay", "Walk-forward: pametni DCA",
                  "Walk-forward: makro filtar + indeks influencera", "CI 95 % po danu", "CI 90 %",
                  "<details id=arhiva>", "Arhiva: mikrokap strategije", "pauzirane od 15.11.", "KOL pozivi"):
            self.assertIn(s, body)
        self.assertNotIn("<details id=arhiva open>", body)            # collapsed while the switch is on
        self.assertNotIn("Što bih ja napravio", body)                 # no verdict for paused accounts
        from report import midcap
        rows = midcap.strategies(NOW)
        vr = {r["vrsta"] for r in rows}
        self.assertEqual(vr, {"demo", "pravi", "mjerenje", "backtest"})
        demo = [r for r in rows if r["naziv"] == "Midcap dnevni raspon" and r["vrsta"] == "demo"][0]
        self.assertGreaterEqual(demo["n"], 20)
        self.assertEqual(demo["d24"]["n"], 0)                          # yesterday's closes are older than 24 h at 09:30
        self.assertEqual(rows[-1]["vrsta"], "backtest")
        with mock.patch.dict(os.environ, {"FOKUS_MIDCAP_FORCE": "0"}), \
                mock.patch("strat.run.exit_rules", lambda now: {"fee": 0.01}):
            _t, body = strategije.page({})
        self.assertIn("<details id=arhiva open>", body)


class StratPaused(unittest.TestCase):
    """strat/: no new and no pending entry while fokus_midcap is on; the open ones keep their exits."""

    def test_no_entries_while_switch_on(self):
        from ops import fokus
        from strat import run, store
        A, B = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump", "8uBobWMhu6hRUn4jaA4kjcgWCjTxgHwHJtPgBePXpump"
        T0 = 1793390000
        ex = {"fee": 0.01, "sl": -0.35, "tp": [[1.0, 0.5]], "trail_after": 0.5, "trail": 0.3, "max_hold_h": 24,
              "rug_liq": 0.2}
        cfg = run.load_config()
        cfg["strategies"] = [{k: v for k, v in s.items() if k not in ("frozen", "topups")} for s in cfg["strategies"]]
        px = {A: 1.0, B: 1.0}

        class Src:
            data = {"kol": [], "novcanici": [], "alat": [], "scored": []}

            def read(self, now, window_s):
                return {k: [e for e in v if e[1] <= now] for k, v in self.data.items()}

        src = Src()
        db = os.path.join(tempfile.mkdtemp(), "strat.db")
        mk = lambda toks: {t: (px[t], 50000, px[t] * 1e6, "SYM", "u") for t in toks if t in px}  # noqa: E731
        st = lambda now, **kw: run.step(now=now, cfg=cfg, path=db, market_fn=mk, sources=src, ex=ex, quiet=True, **kw)  # noqa: E731
        st(T0, fokus_on=False)
        src.data["kol"] = [(A, T0 + 30, "kolA", 50)]
        self.assertEqual(st(T0 + 60, fokus_on=False)["entered"], 1)
        # a signal seen before the switch (pending: no price yet), then the switch goes on
        src.data["kol"].append((B, T0 + 90, "kolB", 50))
        del px[B]
        st(T0 + 120, fokus_on=False)
        con = store.connect(db)
        self.assertEqual(con.execute("SELECT status FROM positions WHERE token=?", (B,)).fetchone()[0], "pending")
        con.close()
        px[B] = 1.0
        with mock.patch.dict(os.environ, {"FOKUS_MIDCAP_FORCE": "1"}):
            self.assertTrue(fokus.skip(run.FOKUS_KEY))
            self.assertTrue(run.paused())
            src.data["kol"].append((B[:-6] + "99pump", T0 + 150, "kolC", 50))
            px[B[:-6] + "99pump"] = 1.0
            r = st(T0 + 180)
            self.assertEqual(r["entered"], 0)
            px[A] = 0.5                                                # the open one still exits by its stop
            r = st(T0 + 240)
            self.assertEqual((r["entered"], r["closed"]), (0, 1))
        con = store.connect(db)
        rows = dict(con.execute("SELECT token, status || ':' || COALESCE(close_reason, '') FROM positions"))
        con.close()
        self.assertEqual(rows[B], "skip:" + run.FOKUS_SKIP)
        self.assertEqual(rows[A], "closed:")
        self.assertNotIn(B[:-6] + "99pump", rows)
        self.assertIn("strategije", [k for k, _w in fokus.RETARGET])


class Resend(unittest.TestCase):
    """run_report: the owner's one-time resend after the deploy (OWNER_ONCE), then the normal schedule."""

    def setUp(self):
        import run_report
        self.rr = run_report
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(run_report, "OUT", self.tmp.name),
                  mock.patch.object(run_report, "STATE", os.path.join(self.tmp.name, "report-state.json"))):
            p.start()
            self.addCleanup(p.stop)
        self.sent, self.logs = [], []

    def send(self, now=None):
        self.sent.append(now)
        st = self.rr.load_state()
        st.update(sent="2026-11-16", how="smtp smtp.gmail.com")
        self.rr.save_state(st)
        return st

    def test_once_after_the_deploy(self):
        self.rr.save_state({"sent": "2026-11-16", "built": "2026-11-16"})   # this morning's old version went out
        got = self.rr.owner_once(NOW, log=self.logs.append, send=self.send)
        self.assertEqual(got, ["midcap_1611"])
        self.assertEqual(self.sent, [NOW])
        self.assertIn("nalog vlasnika midcap_1611", self.logs[0])
        self.assertIn("poslana odmah nakon deploya (smtp smtp.gmail.com)", self.logs[0])
        st = self.rr.load_state()
        self.assertIn("midcap_1611", st["once"])
        self.assertEqual(st["sent"], "2026-11-16")                     # the normal schedule: nothing more today
        self.assertEqual(self.rr.owner_once(NOW + 600, log=self.logs.append, send=self.send), [])
        self.assertEqual(len(self.sent), 1)

    def test_before_the_morning_hour_nothing_extra(self):
        early = NOW - 7 * H                                            # 03:30 Zagreb
        with mock.patch.dict(os.environ, {"REPORT_HOUR": "7"}):
            self.assertEqual(self.rr.owner_once(early, log=self.logs.append, send=self.send), [])
        self.assertEqual(self.sent, [])
        self.assertIn("prije 7:00", self.logs[0])
        self.assertIn("midcap_1611", self.rr.load_state()["once"])

    def test_mail_error_is_logged(self):
        def fail(now=None):
            st = {"error": "RuntimeError: e-mail nije podešen"}
            self.rr.save_state(st)
            return st
        self.rr.owner_once(NOW, log=self.logs.append, send=fail)
        self.assertIn("e-mail nije poslan", self.logs[0])
        self.assertIn("/izvjestaj", self.logs[0])


if __name__ == "__main__":
    unittest.main()
