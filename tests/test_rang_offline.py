"""Rang za kopiranje (11.11., Jure; wallets/rang.py): the copy ranking of wallets and influencers that replaces the old
copy ocjena. Pure parts (Wilson lower bound, median not mean, profit factor, concentration, recency, no SOL PnL in the
score), the fixture ranking with the owner's example (8xiS…aftH: 63 % of PnL from one trade, entries at ~$2.5k market
cap), influencers, the real-money gates (Autopilot auto pick, webhook copy group, league copy), the table and the
one-time before/after log block. No network: every database is a temp file."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wallets import rang, store as wstore  # noqa: E402

NOW = 1_800_000_000
D = 86400
SOL = 150.0
W8 = "8xiS" + "Q" * 36 + "aftH"


def good(i):
    """A decent fixture wallet's address: distinct in the short form too (GD05…w005)."""
    return f"GD{i:02d}" + "g" * 36 + f"w{i:03d}"


def _mint(tag, i, pump=True):
    return f"{tag}{i:03d}" + "x" * 30 + ("pump" if pump else "zzzz")


def _wallet(con, w, copy_score, closed, labels=()):
    con.execute("INSERT INTO wallets (wallet, first_seen, last_seen, scored_at, stats, labels, score, copy_score, tier, "
                "last_tx_ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (w, NOW - 40 * D, NOW, NOW - 3600, json.dumps({"closed": closed, "median_hold_min": 60,
                                                               "trades_per_day": 5}),
                 json.dumps(list(labels)), copy_score, copy_score, "A", NOW - 3600))


def _positions(con, w, pos, tag):
    """pos: [(t0, cost_sol, ret, mcap_usd_at_entry, pump)] -> buy at t0 at that market cap, full sell 2 h later."""
    rows = []
    for i, (t0, c, ret, mc, pump) in enumerate(pos):
        m = _mint(tag, i, pump)
        px = mc / SOL / 1e9
        tok = c / px
        rows.append((w, f"{w}-b{i}", t0, m, tok, -c, "buy"))
        rows.append((w, f"{w}-s{i}", t0 + 7200, m, -tok, c * (1 + ret), "sell"))
    con.executemany("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", rows)
    return rows


def _spread(n, days=25):
    return [NOW - int(days * D * (k + 1) / (n + 1)) for k in range(n)]


def make_fixture(tmp):
    """wallets.db with 12 decent wallets, the 8xiS pattern, one with unknown entry liquidity, one with a pool
    snapshot, one unproven and one bot; kol.db / events.db with three influencers; market.db SOL price; fast.db and
    league.db lags; hype.db live trades after one entry. Returns (wallets.db path, paths)."""
    path = os.path.join(tmp, "wallets.db")
    con = wstore.connect(path)
    # the owner's example: 12 closed, 8 won, one +323 % trade = 63 % of the PnL, every entry at ~$2.5k market cap
    rets = [0.5] * 7 + [-0.4] * 4 + [3.235]
    _wallet(con, W8, 92, 40)
    _positions(con, W8, [(t, 1.0, r, 2500, True) for t, r in zip(_spread(12), rets)], "E")
    # twelve decent wallets: profitable on many small wins (a smaller median than 8xiS), entries at $60k-$500k
    good_rows = []
    for i in range(12):
        w = good(i)
        n = 12 + i
        wins = int(round(n * (0.62 + 0.02 * i)))
        rr = [0.2 + 0.02 * i] * wins + [-0.15] * (n - wins)
        _wallet(con, w, 50 + 3 * i, n)
        rows_ = _positions(con, w, [(t, 0.5 + 0.1 * (k % 3), r, 60_000 + 40_000 * i, True)
                                    for k, (t, r) in enumerate(zip(_spread(n), rr))], f"G{i:02d}")
        if i == 11:
            good_rows = rows_
    # entries in non-pump tokens without any stored pool snapshot: liquidity unknown
    _wallet(con, "UNKNOWNLIQ" + "u" * 34, 70, 15)
    _positions(con, "UNKNOWNLIQ" + "u" * 34, [(t, 1.0, 0.3 if k % 4 else -0.2, 200_000, False)
                                              for k, t in enumerate(_spread(15))], "U")
    # non-pump tokens with a kol.db pool snapshot near each entry (liquidity $80k)
    snapw = "SNAPLIQ" + "s" * 37
    _wallet(con, snapw, 40, 14)
    snap_rows = _positions(con, snapw, [(t, 1.0, 0.25 if k % 3 else -0.2, 300_000, False)
                                        for k, t in enumerate(_spread(14))], "S")
    # great but only five closed: not proven
    _wallet(con, "FEWTRADES" + "f" * 35, 65, 5)
    _positions(con, "FEWTRADES" + "f" * 35, [(t, 1.0, 0.6, 200_000, True) for t in _spread(5)], "F")
    # a bot: never ranked
    _wallet(con, "BOTWALLET" + "b" * 35, 99, 30, labels=["bot"])
    _positions(con, "BOTWALLET" + "b" * 35, [(t, 1.0, 0.4, 200_000, True) for t in _spread(30)], "B")
    con.commit()
    con.close()
    paths = {k: os.path.join(tmp, f"{k}.db") for k in ("hype", "kol", "league", "market", "fast", "minute", "events")}
    m = sqlite3.connect(paths["market"])
    m.execute("CREATE TABLE price (day INTEGER PRIMARY KEY, usd REAL)")
    m.executemany("INSERT INTO price VALUES (?, ?)", [((NOW // D - k) * D, SOL) for k in range(40)])
    m.commit()
    m.close()
    newest = max((r for r in good_rows if r[6] == "buy"), key=lambda r: r[2])
    hc = sqlite3.connect(paths["hype"])
    hc.execute("CREATE TABLE live_trades (sig TEXT, mint TEXT, wallet TEXT, side TEXT, sol REAL, tokens REAL, price_sol REAL, "
               "mcap_sol REAL, pool TEXT, ts INTEGER, balance_after REAL, PRIMARY KEY (sig, mint))")
    px0 = -newest[5] / newest[4]
    hc.executemany("INSERT INTO live_trades (sig, mint, wallet, side, price_sol, ts) VALUES (?,?,?,?,?,?)",
                   [(f"lt{k}", newest[3], "other", "buy", px0 * f, newest[2] + dt)
                    for k, (dt, f) in enumerate(((10, 1.1), (40, 1.3), (300, 1.6), (3000, 1.2)))])
    hc.commit()
    hc.close()
    from kol import store as kstore
    kc = kstore.connect(paths["kol"])
    kc.executemany("INSERT INTO snaps (token, ts, price, vol_h1, liq, mcap) VALUES (?,?,?,?,?,?)",
                   [(r[3], r[2] + 300, 1.0, 0.0, 80_000.0, 300_000.0) for r in snap_rows if r[6] == "buy"])
    # influencers: twelve calls at $100k with a 4-h close measured (events.db) and a flash row that must not count;
    # twelve calls at $3k (not copyable); four calls (not proven)
    calls, outs = [], []
    for i, t in enumerate(_spread(12)):
        tok = _mint("K", i)
        calls.append((f"t{i}", tok, "goodcaller", t, "call", 100_000.0, 0.05))
        outs.append((i + 1, "call", tok, "goodcaller", "x", t, f"t{i}", 0.20 if i % 3 else -0.10))
        calls.append((f"f{i}", tok, "goodcaller", t + 60, "flash", 100_000.0, -0.9))
    for i, t in enumerate(_spread(12)):
        calls.append((f"s{i}", _mint("L", i), "microcaps", t, "call", 3_000.0, 0.4 if i % 2 else -0.2))
    for i, t in enumerate(_spread(4)):
        calls.append((f"w{i}", _mint("N", i), "fewcalls", t, "call", 200_000.0, 0.3))
    kc.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind, mcap0, r1h) VALUES (?,?,?,?,?,?,?)", calls)
    kc.commit()
    kc.close()
    from events import store as estore
    ec = estore.connect(paths["events"])
    ec.executemany("INSERT INTO call_outcomes (uid, kind, mint, actor, source, ts, tweet_id, change_4h, status) "
                   "VALUES (?,?,?,?,?,?,?,?,'ok')", outs)
    ec.commit()
    ec.close()
    from fast import store as fstore
    fc = fstore.connect(paths["fast"])
    for k, lat in enumerate((8.0, 12.0, 20.0)):
        fc.execute("INSERT INTO signals (token, source_id, sig_ts, decided_ts, latency_s, status) VALUES (?,?,?,?,?,'done')",
                   (f"T{k}", good(0), NOW - 3600 * (k + 1), NOW - 3600 * (k + 1) + lat, lat))
    fc.commit()
    fc.close()
    from league import copy as lcopy
    lc = sqlite3.connect(paths["league"])
    lc.executescript(lcopy.SCHEMA)
    lc.execute("INSERT INTO follows (id, user, kind, target, created, active) VALUES (1, 'x', 'kol', 'goodcaller', ?, 1)",
               (NOW - 20 * D,))
    lc.executemany("INSERT INTO copy_log (follow_id, token, side, ev_ts, ts, action) VALUES (1, ?, 'buy', ?, ?, 'ulaz')",
                   [(f"C{k}", NOW - D * (k + 1), NOW - D * (k + 1) + 45) for k in range(3)])
    lc.commit()
    lc.close()
    return path, paths


class Pure(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(rang.WEIGHTS.values()), 1.0)
        self.assertEqual(set(rang.WEIGHTS), set(rang.components({"n": 0})))

    def test_wilson_lower_bound(self):
        self.assertAlmostEqual(rang.wilson_low(5, 5), 0.649, places=2)
        self.assertLess(rang.wilson_low(5, 5), rang.wilson_low(45, 55))    # 100 % of 5 ranks below 82 % of 55
        self.assertEqual(rang.wilson_low(0, 10), 0.0)
        self.assertEqual(rang.wilson_low(0, 0), 0.0)
        self.assertLess(rang.wilson_low(6, 10), 0.6)                        # always under the raw share
        self.assertEqual(rang.Z90, 1.645)

    def _items(self, rets, cost=1.0, liq=50_000, age_d=1):
        return [{"ret": r, "pnl": r * cost, "cost": cost, "t0": NOW - age_d * D, "t1": NOW - age_d * D, "liq": liq,
                 "liq_src": "model", "avail": None, "hold_min": 60} for r in rets]

    def test_median_not_mean(self):
        m = rang.metrics(self._items([-0.1, 0.05, 0.1, 9.0]), NOW)
        self.assertAlmostEqual(m["median"], 0.075)
        a = rang.score(rang.metrics(self._items([-0.1, 0.05, 0.1, 0.2]), NOW))[1]["median"]
        b = rang.score(rang.metrics(self._items([-0.1, 0.05, 0.1, 9.0]), NOW))[1]["median"]
        self.assertEqual(a, b)                                              # a +900 % outlier does not move it

    def test_profit_factor(self):
        m = rang.metrics(self._items([0.5, 0.5, -0.25]), NOW)
        self.assertAlmostEqual(m["pf"], 4.0)
        self.assertEqual(rang.metrics(self._items([0.5, 0.2]), NOW)["pf"], rang.PF_CAP)
        self.assertEqual(rang.metrics(self._items([-0.5]), NOW)["pf"], 0.0)

    def test_concentration_penalty(self):
        m = rang.metrics(self._items([0.5] * 7 + [-0.4] * 4 + [3.235]), NOW)
        self.assertAlmostEqual(m["conc"], 0.63, places=2)
        self.assertAlmostEqual(m["pnl_ex_top"], m["pnl"] - 3.235)
        sc, comp, pen = rang.score(m)
        self.assertEqual(pen, rang.CONC_MULT)
        raw = 100 * sum(rang.WEIGHTS[k] * comp[k] for k in rang.WEIGHTS)
        self.assertAlmostEqual(sc, round(raw * 0.6, 1))
        self.assertEqual(rang.score(rang.metrics(self._items([0.3] * 10), NOW))[2], 1.0)   # 10 % each: no penalty
        neg = rang.metrics(self._items([0.4, -0.3, -0.3]), NOW)              # in minus: without its best trade worse
        self.assertIsNone(neg["conc"])                                       # no share of a negative total shown
        self.assertEqual(rang.score(neg)[2], rang.CONC_MULT)                 # never punished less than a small plus

    def test_proven_and_copyable_flags(self):
        m = rang.metrics(self._items([0.2] * 9), NOW)
        self.assertEqual(rang.copy_flags(m)[:2], (False, True))            # n 9: not proven
        m = rang.metrics(self._items([0.2] * 10, liq=12_000), NOW)
        proven, cp, why = rang.copy_flags(m)
        self.assertEqual((proven, cp), (True, False))
        self.assertIn("ispod $15k", why)
        m = rang.metrics(self._items([0.2] * 10, liq=None), NOW)
        self.assertEqual(rang.copy_flags(m)[1:], (False, "likvidnost na ulazu nepoznata"))
        self.assertEqual(rang.score(m)[1]["copy"], 0.0)

    def test_recency_decay(self):
        self.assertAlmostEqual(rang.decay(7 * D), 0.5)
        self.assertAlmostEqual(rang.decay(14 * D), 0.25)
        fresh = rang.metrics(self._items([0.2] * 10, age_d=0), NOW)
        old = rang.metrics(self._items([0.2] * 10, age_d=21), NOW)
        self.assertEqual((fresh["n7"], old["n7"]), (10, 0))
        self.assertAlmostEqual(old["rec"], 10 * 0.125)
        self.assertGreater(rang.score(fresh)[1]["recency"], rang.score(old)[1]["recency"])

    def test_no_sol_pnl_in_the_score(self):
        small = rang.evaluate(self._items([0.3, -0.1, 0.2, 0.25] * 3, cost=0.1), NOW)
        big = rang.evaluate(self._items([0.3, -0.1, 0.2, 0.25] * 3, cost=100.0), NOW)
        self.assertNotAlmostEqual(small["pnl"], big["pnl"])
        self.assertEqual(small["score"], big["score"])
        m = rang.metrics(self._items([0.3] * 10), NOW)
        self.assertEqual(rang.components(dict(m, pnl=1e9, pnl_ex_top=1e9, stake=1e6)), rang.components(m))

    def test_cost_and_pool_model(self):
        self.assertAlmostEqual(rang.cost(100, 20_000), 2 * rang.FEE_SIDE + 2 * 100 / 10_100)
        self.assertIsNone(rang.cost(100, None))
        liq = rang.pool_liq_usd(2500 / SOL, SOL)              # $2.5k market cap
        self.assertLess(liq, rang.MIN_LIQ_USD)
        self.assertGreater(rang.pool_liq_usd(300_000 / SOL, SOL), 40_000)
        self.assertTrue(rang.is_pump("abcpump"))
        self.assertFalse(rang.is_pump("abc"))

    def test_gain_left_after_the_lag(self):
        pts = [(100, 1.0, 1.0), (130, 1.5, 1.5), (160, 2.0, 2.0), (400, 1.2, 1.2)]
        self.assertAlmostEqual(rang.avail_share(pts, 100, 1.0, 30, 1000), 0.5)   # (2.0 - 1.5) / (2.0 - 1.0)
        self.assertIsNone(rang.avail_share(pts, 100, 1.0, 1000, 2000))          # nothing after the lag
        self.assertIsNone(rang.avail_share([(110, 0.9, 0.9)], 100, 1.0, 5, 200))  # no gain at all


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path, self.paths = make_fixture(self.tmp)
        self.logs = []
        con = wstore.connect(self.path)
        self.out = rang.run(con, NOW, self.paths, log=self.logs.append)
        con.close()
        rang.clear()

    def tearDown(self):
        rang.clear()

    def test_8xis_drops_and_is_not_copyable(self):
        con = sqlite3.connect(self.path)
        before = [w for w, _ in rang.old_top(con, 10)]
        con.close()
        self.assertEqual(before[0], W8)                                       # the old copy ocjena put it first
        rows = rang.ranked("wallet", self.path)
        r = rang.get("wallet", W8, self.path)
        self.assertFalse(r["copyable"])
        self.assertTrue(r["proven"])
        self.assertAlmostEqual(r["conc"], 0.63, places=2)
        self.assertEqual(r["pen"], rang.CONC_MULT)
        self.assertLess(r["liq"], rang.MIN_LIQ_USD)
        after = [x["target"] for x in rows if x["proven"]][:10]
        self.assertNotIn(W8, after)                                           # out of the new top 10
        self.assertEqual(rang.gate("wallet", W8, self.path)[0], False)
        self.assertIn("nije kopirljivo", rang.gate("wallet", W8, self.path)[1])

    def test_coverage_and_sources(self):
        r = rang.get("wallet", "UNKNOWNLIQ" + "u" * 34, self.path)
        self.assertIsNone(r["liq"])
        self.assertFalse(r["copyable"])
        s = rang.get("wallet", "SNAPLIQ" + "s" * 37, self.path)
        self.assertEqual(s["liq_src"], {"snimka": 14})
        self.assertTrue(s["copyable"])
        g = rang.get("wallet", good(0), self.path)
        self.assertEqual((g["lag_src"], g["lag_s"]), ("fast", 12.0))
        g11 = rang.get("wallet", good(11), self.path)
        self.assertEqual(g11["avail_n"], 1)                                   # live trades after his newest entry
        self.assertAlmostEqual(g11["avail"], (1.6 - 1.3) / (1.6 - 1.0))     # 30 s lag: entry at 1.3, top 1.6
        self.assertEqual(rang.get("wallet", good(1), self.path)["lag_src"], "zadano")
        self.assertFalse(rang.get("wallet", "FEWTRADES" + "f" * 35, self.path)["proven"])
        self.assertIsNone(rang.get("wallet", "BOTWALLET" + "b" * 35, self.path))
        cov = self.out["coverage"]["wallet"]
        self.assertEqual(cov["liq_unknown_sources"], 1)
        self.assertEqual(cov["liq_src"]["snimka"], 14)

    def test_influencers(self):
        k = {r["target"]: r for r in self.out["kols"]}
        self.assertEqual(set(k), {"goodcaller", "microcaps", "fewcalls"})
        g = k["goodcaller"]
        self.assertEqual(g["n"], 12)                                          # flash rows are not calls
        self.assertAlmostEqual(g["median"], 0.20)                             # the 4-h close where measured
        self.assertEqual(g["hold_min"], 240)
        self.assertEqual((g["lag_src"], g["lag_s"]), ("copy_log", 45.0))
        self.assertTrue(g["copyable"] and g["proven"])
        self.assertFalse(k["microcaps"]["copyable"])
        self.assertEqual(k["microcaps"]["hold_min"], 60)                      # only the 1-h result
        self.assertFalse(k["fewcalls"]["proven"])
        self.assertEqual(rang.gate("kol", "@GoodCaller", self.path), (True, ""))
        self.assertFalse(rang.gate("kol", "microcaps", self.path)[0])

    def test_before_after_logged_once(self):
        blocks = [x for x in self.logs if x.startswith("rang za kopiranje: prije")]
        self.assertEqual(len(blocks), 1)
        self.assertIn("8xiS…aftH: prije #1, poslije #", blocks[0])
        self.assertIn("nije kopirljiv", blocks[0])
        self.assertIn("likvidnost na ulazu poznata", blocks[0])
        logs = []
        con = wstore.connect(self.path)
        rang.run(con, NOW + 60, self.paths, log=logs.append)
        con.close()
        self.assertEqual([x for x in logs if x.startswith("rang za kopiranje: prije")], [])
        self.assertEqual(len(logs), 1)                                        # only the summary line
        con = sqlite3.connect(self.path)
        kv = con.execute("SELECT v FROM copy_rank_kv WHERE k=?", (rang.KV_BEFORE_AFTER,)).fetchone()
        con.close()
        self.assertIn("poslije", json.loads(kv[0])["text"])

    def test_no_ranking_no_verdict(self):
        empty = os.path.join(self.tmp, "empty.db")
        wstore.connect(empty).close()
        self.assertEqual(rang.gate("wallet", W8, empty), (None, ""))


class Gates(unittest.TestCase):
    """liq < 15k / n < 10: never copied with real money (Autopilot auto pick, webhook copy group, league copy)."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path, self.paths = make_fixture(self.tmp)
        con = wstore.connect(self.path)
        rang.run(con, NOW, self.paths, log=None)
        con.close()
        rang.clear()

    def tearDown(self):
        rang.clear()

    def test_autopilot_auto_pick(self):
        from ui import autopilot
        rows = [{"wallet": W8}, {"wallet": good(5)}, {"wallet": "FEWTRADES" + "f" * 35}, {"wallet": "NOBODY"}]
        with mock.patch.object(wstore, "DB", self.path):
            kept = autopilot._rang_gate("wallet", rows)
            kk = autopilot._rang_gate("kol", [{"handle": "goodcaller"}, {"handle": "microcaps"}, {"handle": "fewcalls"}])
        self.assertEqual([r["wallet"] for r in kept], [good(5)])
        self.assertEqual([r["handle"] for r in kk], ["goodcaller"])

    def test_webhook_copy_group(self):
        from kol import chainwatch
        copy, _sig = chainwatch.own_wallets(30, 5, min_copy=0, wallet_db=self.path)
        self.assertNotIn(W8, copy)
        self.assertNotIn("UNKNOWNLIQ" + "u" * 34, copy)
        self.assertNotIn("FEWTRADES" + "f" * 35, copy)
        self.assertIn("SNAPLIQ" + "s" * 37, copy)
        scores = [rang.get("wallet", w, self.path)["score"] for w in copy]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_league_copy_real_money_only(self):
        from league import copy as lcopy
        from trade import settings
        f = {"kind": "wallet", "target": W8, "user": settings.LEAGUE_USER}
        with mock.patch.object(wstore, "DB", self.path):
            self.assertIn("nije kopirljivo", lcopy._rang_gate(f))
            self.assertIsNone(lcopy._rang_gate(dict(f, user="igrac")))                     # players: not gated
            self.assertIsNone(lcopy._rang_gate(dict(f, user=settings.PAPER_USER)))        # demo keeps collecting n
            self.assertIsNone(lcopy._rang_gate(dict(f, target=good(5))))
            self.assertIn("nije dokazan", lcopy._rang_gate(dict(f, target="FEWTRADES" + "f" * 35)))
            self.assertIsNone(lcopy._rang_gate(dict(f, kind="ekipa", target="a,b")))
            self.assertIn("nije kopirljivo", lcopy._rang_gate({"kind": "kol", "target": "microcaps",
                                                                "user": settings.LEAGUE_USER}))


class Table(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path, self.paths = make_fixture(self.tmp)
        con = wstore.connect(self.path)
        rang.run(con, NOW, self.paths, log=None)
        con.close()
        rang.clear()

    def tearDown(self):
        rang.clear()

    def test_columns_sort_and_details(self):
        from ui import rangtable
        rows = rang.ranked("wallet", self.path, proven=True)
        html = str(rangtable.table(rows, "wallet", NOW))
        heads = [t for _, t, _ in rangtable.COLS][1:]
        self.assertEqual(heads, ["Ocjena", "ROI %", "Medijan/trade", "Win (donja granica)", "n", "Koncentracija",
                                 "Kopirljivo", "Drži", "Zadnji trade"])
        pos = [html.index(f">{t}</th>") for t in heads]
        self.assertEqual(pos, sorted(pos))
        self.assertIn('data-k="sc" data-t="n"', html)
        th = html[html.index('data-k="sc"'):]
        self.assertIn('aria-sort="descending"', th[:th.index(">")])
        scs = [float(x.split('"')[0]) for x in html.split('data-sc="')[1:]]
        self.assertEqual(scs, sorted(scs, reverse=True))                       # default order: Ocjena
        self.assertIn("Zarada ukupno", html)                                   # SOL PnL only in the details row
        self.assertIn("prosječan ulog", html)
        self.assertIn("th[data-k]", html)                                      # client-side sort, no new request
        self.assertNotIn("SOL PnL</th>", html)
        kol = str(rangtable.table(rang.ranked("kol", self.path), "kol", NOW))
        self.assertIn("@goodcaller", kol)
        self.assertIn("Zbroj povrata", kol)
        self.assertIn("Drži (mjereno)", kol)

    def test_wallets_page_uses_the_table(self):
        import run_ui  # noqa: F401
        from ui import data, pages
        groups = dict(data.GROUPS)
        try:
            data.GROUPS["wallets"] = [self.path]
            with mock.patch.object(data, "WALLET_DB", self.path), mock.patch.object(wstore, "DB", self.path), \
                    mock.patch("ui.preporuka.copies_from_strat", return_value={}), \
                    mock.patch("ui.jobs.status", return_value=(None, None, "")), \
                    mock.patch.object(pages, "_last_buy", return_value=None), \
                    mock.patch.object(pages, "autopilot_marks",
                                      return_value={"proven": {}, "followed": set(), "recs": {}, "as_of": None}):
                title, html = pages.wallets({})
                _, svi = pages.wallets({"v": "svi"})
        finally:
            data.GROUPS.update(groups)
        self.assertEqual(title, "Novčanici")
        self.assertIn("table class=rt data-rt", html)
        tbl = html[html.index("table class=rt data-rt"):]
        self.assertIn("8xiS…aftH", tbl)                                        # shown, marked "ne"
        self.assertLess(tbl.index("GD11…w011"), tbl.index("8xiS…aftH"))
        self.assertIn("Još nisu dokazani", html)
        self.assertNotIn("BOTW", tbl)
        self.assertIn(">Ocjena</span>", svi)                                   # Svi: the column is the new Ocjena

    def test_influencer_pane(self):
        from ui import kol
        with mock.patch.object(wstore, "DB", self.path):
            html = kol.rang_pane(NOW)
        top = html[:html.index("Još nisu dokazani")]
        self.assertIn("@goodcaller", top)
        self.assertIn("@microcaps", top)                                      # shown, marked "ne"
        self.assertNotIn("@fewcalls", top)                                    # four calls: one tap below
        self.assertIn(">Win (donja granica)</th>", top)
        self.assertLess(top.index("@goodcaller"), top.index("@microcaps"))

    def test_autopilot_box(self):
        from ui import rangtable
        html = rangtable.autopilot_box("wallet", 3, NOW, self.path)
        self.assertIn("GD11…w011", html)
        self.assertNotIn("8xiS", html)
        self.assertIn("nije kopirljivo", html)


if __name__ == "__main__":
    unittest.main()
