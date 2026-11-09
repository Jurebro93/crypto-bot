"""Audit 9.11.2026, grupa 'zivo' (ui/zivo.py, ui/autopilot.py, ui/prijedlog.py, ui/prijedlog_log.py, ui/paper.py):
the auto pick ranks influencers by the minute check (P12/P15/P16), wallets by the proven-twice list and never by an
unknown return (P13/P14/P34), auto follows get the owner's TP and the default stop (P68); the live list refreshes in a
daemon thread, never in the 1-second request thread (P33, TTL 2+ s, P2); the dead 'prijedlog' source works (P53/P54);
dropped tool rows are skipped (P52); the Pregled box grades the live rows 'uživo' and logs them apart (P50/P51); the
band chance is KOL calls only (P81); crews need the module's own sample (P80); the expectation is pooled (P85).

    python3 -m unittest tests.test_audit_20261109_zivo_offline
"""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store as lstore  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import autopilot, paper, prijedlog, prijedlog_log, zivo  # noqa: E402

NOW = int(time.time())
D = 86400
A, B, C = ("4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi", "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
           "CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8")


def live(mcap=120_000, ch_m5=12.0, ch_h1=5.0, vol_h1=8_000.0, txns_h1=60, liq=50_000.0):
    return {"price": 0.001, "liq": liq, "mcap": float(mcap), "vol_h1": vol_h1, "vol_h24": 50_000.0, "txns_h1": txns_h1,
            "buys_h1": 30, "txns_h24": 500, "vol_m5": 2500.0, "txns_m5": 12, "ch_m5": ch_m5, "ch_h1": ch_h1, "ch_h24": 20.0}


def ms(n, hit10, sl, hit15=None):
    return {"n": n, "hit10": hit10, "hit15": hit10 if hit15 is None else hit15, "sl": sl, "rug": 0.0, "med_t10": 7.0}


class KolRank(unittest.TestCase):
    def test_calls_younger_than_24h_are_not_misses(self):   # P15
        now = 100 * D
        calls = [("a", now - 3 * D, 0.1, -0.3, 0), ("a", now - 2 * 3600, 0.1, None, 0)]   # the second is still being measured
        s = autopilot.kol_stats(calls, now, 7)
        self.assertEqual((s["a"]["n"], s["a"]["hits"]), (1, 0))

    def test_minute_check_is_primary_and_known_bad_never_falls_back(self):   # P12/P15/P16
        wick = {"n": 6, "hits": 5, "rugs": 0, "r24": [], "hit": 0.83, "rug": 0.0, "med24": 0.3, "score": 0.6}
        st = {"good_min": dict(wick), "bad_min": dict(wick), "fresh": dict(wick), "weak": {**wick, "n": 2}}
        mst = {"good_min": ms(7, 0.57, 0.14), "bad_min": ms(9, 0.22, 0.56), "fresh": ms(2, 1.0, 0.0),
               "only_min": ms(6, 0.67, 0.17)}
        r = autopilot.kol_rank(st, mst)
        self.assertEqual(set(r), {"good_min", "fresh", "only_min"})
        self.assertEqual(r["good_min"]["mjera"], "minutna")               # 5+ minute calls: the minute check decides
        self.assertAlmostEqual(r["good_min"]["score"], 0.57 - 0.14)
        self.assertNotIn("bad_min", r)                                     # hit10 22 % / stop first 56 %: out, whatever the wick says
        self.assertEqual(r["fresh"]["mjera"], "fitilj")                    # 2 minute calls: the old wick stands in, marked
        self.assertEqual(r["only_min"]["n"], 0)                            # no wick calls at all, still ranked by the minute check
        self.assertNotIn("weak", r)                                        # the wick fallback keeps its own MIN_CALLS bar
        why = autopilot._kol_why("good_min", r["good_min"], 14, True)
        self.assertIn("minutna provjera (14 d): 7 poziva, +10 % prije stopa u 57%", why)
        why2 = autopilot._kol_why("fresh", r["fresh"], 14, True)
        self.assertIn("stara mjera (fitilj +50 % u 24 h)", why2)
        self.assertIn("ima 2", why2)
        self.assertEqual((autopilot.MIN_MINUTE, autopilot.HOT_HIT10, autopilot.HOT_MAX_SL), (5, 0.5, 0.3))   # kol/minute.hot bar

    def test_known_rug_excludes_even_with_a_good_minute_check(self):   # review of P12/P16: the rug filter stays
        wick = {"n": 6, "hits": 5, "rugs": 0, "r24": [], "hit": 0.83, "rug": 0.0, "med24": 0.3, "score": 0.6}
        st = {"wick_rug": {**wick, "rugs": 3, "rug": 0.4}, "min_rug": dict(wick), "clean": dict(wick), "fresh_rug": dict(wick)}
        mst = {"wick_rug": ms(7, 0.71, 0.14), "min_rug": {**ms(7, 0.71, 0.14), "rug": 0.43}, "clean": ms(7, 0.71, 0.14),
               "fresh_rug": {**ms(2, 1.0, 0.0), "rug": 0.5}}
        r = autopilot.kol_rank(st, mst)
        self.assertEqual(set(r), {"clean"})
        self.assertNotIn("wick_rug", r)                                    # rug 40 % on the 24-h measure: out despite hit10 71 %
        self.assertNotIn("min_rug", r)                                     # rug 43 % seen by the minute check: out
        self.assertNotIn("fresh_rug", r)                                   # too few minute calls for the rank, but the rug it saw counts
        self.assertEqual(autopilot.MAX_RUG, 0.3)


class WalletRank(unittest.TestCase):
    def test_sell_without_sol_counts_as_closed_but_return_stays_unknown(self):   # P14
        now = 100 * D
        tr = [("w", "A", "buy", now - D, 1.0), ("w", "A", "sell", now - 80000, None),
              ("w", "B", "buy", now - D, 1.0), ("w", "B", "sell", now - 80000, None),
              ("w", "C", "buy", now - D, 1.0)]
        s = autopilot.wallet_stats(tr, now, 7)["w"]
        self.assertEqual((s["bought"], s["closed"], s["priced"], s["open"]), (3, 2, 0, 1))
        self.assertIsNone(s["roi"])                                        # never 'prolazi' on missing data
        self.assertIn("nepoznato", autopilot._wallet_why(s, 7))
        self.assertIn("još drži 1", autopilot._wallet_why(s, 7))

    def test_bags_cost_score_and_old_assertions_hold(self):   # P13/P34
        now = 100 * D
        tr = [("w", "A", "buy", now - D, 1.0), ("w", "A", "sell", now - 80000, 3.0),
              ("w", "B", "buy", now - D, 1.0), ("w", "B", "sell", now - 80000, 0.5),
              ("w", "C", "buy", now - D, 1.0)]
        s = autopilot.wallet_stats(tr, now, 7)["w"]
        self.assertEqual((s["bought"], s["closed"], s["wins"]), (3, 2, 1))
        self.assertAlmostEqual(s["roi"], 0.75)
        self.assertAlmostEqual(s["open_share"], 1 / 3)
        bags = tr + [("w", t, "buy", now - D, 1.0) for t in ("D", "E", "F", "G")]
        s2 = autopilot.wallet_stats(bags, now, 7)["w"]
        self.assertAlmostEqual(s2["roi"], 0.75)                            # same sales ...
        self.assertLess(s2["score"], s["score"])                           # ... but five bags out of seven rank lower
        self.assertGreater(s2["open_share"], autopilot.MAX_OPEN_SHARE)     # and wallet_recs drops such a wallet

    def test_auto_targets_take_proven_wallets_first(self):   # P13/P14
        st = {"hit": 0.5, "n": 4, "roi": 0.3, "win": 0.6, "score": 0.3, "mjera": "minutna"}
        saved = (autopilot.kol_recs, autopilot.wallet_recs, autopilot.proven_wallets)
        autopilot.kol_recs = lambda now=None: {14: [{"handle": "a", "live": True, "why": "ok", "s": st}]}
        autopilot.wallet_recs = lambda now=None: {14: [{"wallet": "W9", "name": "", "why": "roi", "s": st},
                                                       {"wallet": "P1", "name": "", "why": "dup", "s": st}]}
        autopilot.proven_wallets = lambda: [{"wallet": "P1", "name": "", "why": "dokazan", "s": {"score": 1}}]
        try:
            got = autopilot.auto_targets(14, 2)
            self.assertEqual([(k, t) for k, t, _, _ in got], [("kol", "a"), ("wallet", "P1"), ("wallet", "W9")])
            self.assertEqual(got[1][3], "dokazan")
        finally:
            autopilot.kol_recs, autopilot.wallet_recs, autopilot.proven_wallets = saved

    def test_proven_rows_skip_bag_heavy_wallets(self):
        rows = [{"wallet": "P1", "closed_before": 6, "win_before": 0.67, "realized_before": 1.2, "closed_after": 3,
                 "realized_after": 0.4, "hold_min": 35.0, "bags": 2, "bag_share": 0.1},
                {"wallet": "P2", "closed_before": 9, "win_before": 0.6, "realized_before": 2.0, "closed_after": 2,
                 "realized_after": 0.1, "hold_min": 20.0, "bags": 9, "bag_share": 0.45}]
        autopilot.clear()
        with mock.patch("wallets.dokazani.latest", lambda *a, **k: rows):
            got = autopilot.proven_wallets()
        autopilot.clear()
        self.assertEqual([r["wallet"] for r in got], ["P1"])
        self.assertIn("2 kupljenih tokena još drži (10% knjige)", got[0]["why"])
        self.assertIn("dokazan dvaput", got[0]["why"])


class AutoFollowExit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (settings.DB, lstore.DB)
        lstore.DB = os.path.join(d, "league.db")
        settings.DB = os.path.join(d, "trade.db")
        self.tcon = executor.connect(settings.DB)
        self.lg = lstore.connect(lstore.DB)
        copy.ensure(self.lg)

    def tearDown(self):
        settings.DB, lstore.DB = self._saved
        self.tcon.close()
        self.lg.close()
        self.tmp.cleanup()

    def test_auto_kol_follow_gets_tp_default_and_default_stop_wallet_mirrors(self):   # P68
        st = {"hit": 0.5, "n": 4, "roi": 0.3, "win": 0.6, "score": 0.3}
        saved = (autopilot.kol_recs, autopilot.wallet_recs, autopilot.proven_wallets)
        autopilot.kol_recs = lambda now=None: {14: [{"handle": "a", "live": True, "why": "ok", "s": st}]}
        autopilot.wallet_recs = lambda now=None: {14: [{"wallet": "W1", "name": "", "why": "ok", "s": st}]}
        autopilot.proven_wallets = lambda: []
        settings.put(self.tcon, "auto_pick", True, "Jure")
        settings.put(self.tcon, "tp_default", 20, "Jure")
        try:
            autopilot.sync_follows(self.lg, self.tcon, force=True)
            fs = {(f["kind"], f["target"]): f for f in copy.follows(self.lg, settings.LEAGUE_USER)}
            self.assertEqual(set(fs), {("kol", "a"), ("wallet", "W1")})
            self.assertEqual(fs[("kol", "a")]["exit"], {"mode": "tpsl", "tp": "20%", "sl": copy.DEFAULT_SL})
            self.assertEqual(fs[("wallet", "W1")]["exit"]["mode"], "mirror")
        finally:
            autopilot.kol_recs, autopilot.wallet_recs, autopilot.proven_wallets = saved


class ZivoSources(unittest.TestCase):
    def test_prijedlog_source_reads_the_log_and_alat_skips_unranked(self):   # P52/P53/P54
        picks = [{"token": A, "razina": "visoka", "mcap0": 90_000, "conf": None, "ts": NOW - 600},
                 {"token": B, "razina": "uživo", "mcap0": 90_000, "conf": None, "ts": NOW - 600},    # the live list's own rows: no loop
                 {"token": C, "razina": "visoka", "mcap0": 90_000, "conf": 61, "ts": NOW - 600}]
        top = {A: {"token": A, "symbol": "AAA", "verdict": "prolazi", "state": {"state": "ok"}, "rank": None, "ts": NOW, "mcap": 1e5},
               B: {"token": B, "symbol": "BBB", "verdict": "prolazi", "state": {"state": "ok"}, "rank": 2, "ts": NOW, "mcap": 1e5}}
        with mock.patch("ui.pravitrade.latest_picks", lambda now=None, limit=3: picks), \
             mock.patch("topcheck.store.read_all", lambda *a, **k: top), \
             mock.patch("ui.pravitrade.gather_callers", lambda *a, **k: []), \
             mock.patch.object(copy, "_ro", lambda path: None):
            src = zivo._sources(NOW)
        by = {(r["src"], r["token"]): r for r in src}
        self.assertIn(("prijedlog", A), by)
        self.assertEqual(by[("prijedlog", A)]["why"], ["prijedlog Pregleda"])          # no 'pouzdanost 0'
        self.assertEqual(by[("prijedlog", C)]["why"], ["prijedlog Pregleda, pouzdanost 61"])
        self.assertNotIn(("prijedlog", B), by)
        self.assertNotIn(("alat", A), by)                                                 # dropped from the top list
        self.assertIn(("alat", B), by)

    def test_expectation_is_pooled_and_the_wick_is_marked_old(self):   # P85
        txt, v = zivo.expectation(["a", "b"], {"a": ms(1, 0.9, 0.0), "b": ms(99, 0.1, 0.5)}, None)
        self.assertAlmostEqual(v, (0.9 + 99 * 0.1) / 100)
        self.assertIn("(100 izmjerenih poziva", txt)
        txt, v = zivo.expectation([], {}, (0.42, 300))
        self.assertTrue(txt.startswith("stara mjera: 42% sličnih tokena"))
        self.assertEqual(v, 0.42)


class ZivoBackground(unittest.TestCase):
    def setUp(self):
        self._saved = (zivo.candidates, zivo._recent_callers, zivo._smart_buys, zivo._minute_stats, zivo._chances,
                       prijedlog.live_market, zivo.LIVE_TTL, zivo.IDLE_STOP_S)
        self.calls = []
        cands = [{"token": A, "symbol": "AAA", "src": "zovu", "ts0": NOW - 300, "mcap0": 100_000, "why": ["zovu"]}]
        zivo.candidates = lambda now=None, sources=None: cands
        zivo._recent_callers = lambda now, toks: {A: ["ansem"]}
        zivo._smart_buys = lambda now, toks: {}
        zivo._minute_stats = lambda now: {}
        zivo._chances = lambda: {}

        def fetch(toks):
            self.calls.append(threading.current_thread().name)
            return {A: live()}
        prijedlog.live_market = fetch
        zivo._ROWS.update(ts=0.0, rows=[])
        zivo._BG.update(asked=0.0)
        zivo.LIVE_TTL = 0.05
        zivo.IDLE_STOP_S = 0

    def tearDown(self):
        zivo._BG.update(asked=0.0)   # let the refresh thread stop (idle) before the real TTLs come back
        t = zivo._BG.get("thread")
        if t is not None:
            t.join(timeout=2)
        (zivo.candidates, zivo._recent_callers, zivo._smart_buys, zivo._minute_stats, zivo._chances,
         prijedlog.live_market, zivo.LIVE_TTL, zivo.IDLE_STOP_S) = self._saved
        zivo._ROWS.update(ts=0.0, rows=[])

    def test_request_thread_never_fetches_the_daemon_does(self):   # P33
        first = zivo.rows(time.time())                                       # nothing cached yet: empty (or what the
        self.assertIn([r["token"] for r in first], ([], [A]))                # daemon managed in the meantime), at once
        self.assertNotIn(threading.current_thread().name, self.calls)        # no HTTP in the caller's thread
        for _ in range(100):
            if zivo._ROWS["rows"]:
                break
            time.sleep(0.02)
        self.assertEqual([r["token"] for r in zivo._ROWS["rows"]], [A])
        self.assertTrue(self.calls and all(n == "zivo-live" for n in self.calls))
        self.assertEqual([r["token"] for r in zivo.rows(time.time())], [A])   # the fragment reads the cache
        self.assertIn("checked", zivo._ROWS["rows"][0])                       # data time travels with the row

    def test_sync_computes_in_place_for_the_60s_box(self):
        zivo._ROWS.update(ts=0.0, rows=[])
        rs = zivo.rows(time.time(), sync=True)
        self.assertEqual([r["token"] for r in rs], [A])
        self.assertEqual(self.calls[0], threading.current_thread().name)

    def test_live_ttl_is_never_one_second(self):   # P2/P33
        self.assertGreaterEqual(self._saved[6], 2)


class PregledBox(unittest.TestCase):
    def test_live_rows_are_graded_uzivo_and_logged_apart(self):   # P50/P51
        from ui import data
        d = tempfile.mkdtemp()
        hype = os.path.join(d, "hype.db")
        sqlite3.connect(hype).close()   # an existing (empty) file: hype/tokenstatus retries a missing one for 6 s
        row = {"token": A, "symbol": "AAA", "src": "zovu", "why": ["zovu: ansem"], "ts0": NOW - 300, "live": live(),
               "callers10": ["ansem"], "smart10": 0, "expect": "još bez mjerenja", "expect_v": None, "age_s": 300, "heat": 4.0,
               "reasons": ["novi pozivatelj u 10 min: @ansem"], "checked": NOW}
        seen = {}

        def fake_rows(now=None, **k):
            seen.update(k)
            return [row]
        with mock.patch.object(zivo, "rows", fake_rows), mock.patch.object(data, "HYPE_DB", hype):
            html = prijedlog.box("tokeni", rows=[])
        self.assertTrue(seen.get("sync"))                                   # the 60-s box computes in its own process
        self.assertIn("uživo (Autopilot)", html)
        self.assertIn("ulog 25 $ ·", html)
        self.assertNotIn("SOL)", html)                                     # no hard-coded SOL amount: the rate moves
        self.assertNotIn("pouzdanost 0", html)
        self.assertNotIn("vjerojatnost", html)
        con = sqlite3.connect(hype)
        self.assertEqual(con.execute("SELECT kind, razina FROM prijedlog_log").fetchall(), [("zivo", "uživo")])
        con.close()
        summ = {"uživo": {"n": 4, "labelled": 3, "hit": 2, "stop_first": 1, "med_max": 0.2},
                "visoka": {"n": 4, "labelled": 3, "hit": 1, "stop_first": 2, "med_max": 0.1}}
        self.assertIn("uživo 2 od 3 dalo +15 % prije stopa", prijedlog_log.sentence(summ))
        self.assertIn("; visoka 1 od 3", prijedlog_log.sentence(summ))

    def test_item_grades_and_freshness_from_signal(self):   # P79
        p = {"token": A, "symbol": "AAA", "mcap0": 90_000.0, "conf": None, "why": ["x"], "chance": None}
        self.assertIn("svježina visoka", prijedlog._item({**p, "razina": "visoka"}))
        self.assertIn("uživo (Autopilot)", prijedlog._item({**p, "razina": "uživo"}))   # no KeyError on the new grade
        now = time.time()
        r = {"token": A, "symbol": "AAA", "conf": 70, "mcap": 150_000, "last_seen": now - 600, "signal_ts": now - 8 * 3600,
             "hard": False, "collapse": False, "rug": None, "sansa": 50, "hype": 10, "features": {}, "det": {},
             "conf_parts": [(5, "KOL pozvao")], "checks": [], "events": []}
        lv = {A: {**live(), "ch_h1": 6.0}}
        picks = prijedlog.token_picks(rows=[r], status={A: {"has_pair": 1, "mcap": 160_000}}, ch={}, live=lv)
        self.assertEqual(picks[0]["razina"], "srednja")                     # a rug re-check 10 min ago is not a signal
        picks = prijedlog.token_picks(rows=[{**r, "signal_ts": now - 600}], status={A: {"has_pair": 1, "mcap": 160_000}}, ch={}, live=lv)
        self.assertEqual(picks[0]["razina"], "visoka")


class CrewPick(unittest.TestCase):
    def test_crew_needs_the_modules_sample_and_passes_the_minute_check(self):   # P80
        from kol import together
        cl = lambda n, hit, members: {"members": members, "stats": {"n": n, "hit": hit, "rug": 0.1}, "tokens": n, "shill": False}
        small, big = cl(3, 1.0, ["a", "b", "c"]), cl(together.MIN_N, 0.6, ["d", "e", "f"])
        self.assertIsNone(prijedlog.pick_crew([small], []))                 # 3 joint calls: not enough any more
        self.assertEqual(prijedlog.pick_crew([small, big], [])["members"], ["d", "e", "f"])
        bad = [(("d", "e"), ms(6, 0.17, 0.67), 6, 0.0)]
        self.assertIsNone(prijedlog.pick_crew([big], bad))                  # known bad minute data: no crew
        good = [(("d", "e"), ms(3, 0.67, 0.33), 3, 0.0), (("e", "f"), ms(3, 0.67, 0.0), 3, 0.0)]
        self.assertTrue(prijedlog.pick_crew([big], good)["minute"])
        few = [(("d", "e"), ms(2, 0.0, 1.0), 2, 0.0)]
        self.assertIsNone(prijedlog.pick_crew([big], few)["minute"])        # under CREW_MIN_N: the old measure stands
        self.assertIsNone(prijedlog.crew_minute_ok(["d", "e", "f"], [(("d", "x"), ms(9, 0.9, 0.0), 9, 0.0)]))   # x is not a member


class LiveCache(unittest.TestCase):
    def test_live_market_and_paper_use_the_short_cache(self):   # P2
        from dexscreener import client
        seen = []

        def tokens_live(chain, mints, ttl=None):
            seen.append(("live", chain, tuple(mints)))
            return [{"baseToken": {"address": A, "symbol": "AAA"}, "priceUsd": "0.5", "liquidity": {"usd": 50000},
                     "marketCap": 500000, "volume": {"h1": 100}, "txns": {"h1": {"buys": 5, "sells": 5}}, "priceChange": {}}]
        with mock.patch.object(client, "tokens_live", tokens_live):
            lv = prijedlog.live_market([A])
            mk = paper.market({A})
        self.assertEqual([s[0] for s in seen], ["live", "live"])
        self.assertEqual(lv[A]["mcap"], 500000.0)
        self.assertEqual(mk[A][0], 0.5)
        # the offline tests' 2-argument stand-in for client.tokens still works through paper.market
        with mock.patch.object(client, "tokens", lambda chain, mints: tokens_live(chain, mints)):
            self.assertEqual(paper.market({A})[A][0], 0.5)

    def test_band_chance_counts_kol_calls_only(self):   # P81
        sql = []
        with mock.patch("ui.data.q", lambda path, s, args=(): sql.append(s) or []):
            prijedlog.chances()
        self.assertIn("kind = 'call' AND bad IS NULL", sql[0])
        self.assertNotIn("'bot'", sql[0])


if __name__ == "__main__":
    unittest.main()
