"""Audit 9.11., integration of the cross-group handoffs (what one group needed in another group's files):
P2/P26 league/copy.market prices through the DexScreener live cache; P79 overview rows carry signal_ts;
P50/P51 latest_picks ranks 'uživo' with 'visoka'; P33 "Što kupiti sada" says 'učitavam…' (uncached) before the
zivo thread's first pass; P12/P15/P16 the Influenceri cards show the minute measure; P56 the scan falls back to the
holder shares topcheck/rug.db already know; P76 the fresh-check card shows the RugCheck data time; P11 start.sh
forwards SIGTERM to the supervised process."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dexscreener import client  # noqa: E402
from league import copy, store  # noqa: E402

NOW = int(time.time())
TOK = "Tok1" + "x" * 40


class CopyMarketLive(unittest.TestCase):
    def test_market_uses_the_live_cache(self):
        seen = {}
        pair = {"baseToken": {"address": TOK, "symbol": "A"}, "priceUsd": "0.5", "liquidity": {"usd": 50_000}, "marketCap": 100_000}
        with mock.patch.object(client, "tokens_live", lambda chain, mints, ttl=None: seen.setdefault("live", list(mints)) and [pair]):
            m = copy.market([TOK])
        self.assertEqual(seen["live"], [TOK])
        self.assertEqual(m[TOK][0], 0.5)

    def test_two_argument_stand_in_still_works(self):
        """The offline tests replace client.tokens with a 2-argument lambda; that seam keeps working."""
        pair = {"baseToken": {"address": TOK, "symbol": "A"}, "priceUsd": "2", "liquidity": {"usd": 10_000}, "marketCap": 50_000}
        with mock.patch.object(client, "tokens", lambda chain, mints: [pair]), \
                mock.patch.object(client, "tokens_live", lambda *a, **k: self.fail("tokens_live called with a stand-in")):
            m = copy.market([TOK])
        self.assertEqual(m[TOK][0], 2.0)


class LatestPicksOrder(unittest.TestCase):
    def test_zivo_rows_rank_with_visoka(self):
        from ui import data, pravitrade, prijedlog_log
        d = tempfile.mkdtemp()
        db = os.path.join(d, "hype.db")
        con = sqlite3.connect(db)
        con.executescript(prijedlog_log.SCHEMA)
        for tok, raz, conf, ts in (("N" * 44, "niska", 0.9, NOW - 10), ("Z" * 44, "uživo", 0.5, NOW - 20),
                                   ("V" * 44, "visoka", 0.4, NOW - 30)):
            con.execute("INSERT INTO prijedlog_log (token, day, ts, kind, razina, mcap0, conf) VALUES (?,?,?,?,?,?,?)",
                        (tok, "2026-11-09", ts, "zivo" if raz == "uživo" else "pick", raz, 100_000, conf))
        con.commit()
        con.close()
        with mock.patch.object(data, "HYPE_DB", db):
            picks = pravitrade.latest_picks(NOW, limit=5)
        self.assertEqual([p["razina"] for p in picks], ["uživo", "visoka", "niska"])


class IdeasLoading(unittest.TestCase):
    def test_empty_before_first_pass_is_loading_and_not_cached(self):
        from ui import pravitrade, zivo
        pravitrade._IDEAS_CACHE.clear()
        with mock.patch.object(zivo, "rows", lambda now=None, **k: []), \
                mock.patch.dict(zivo._ROWS, {"ts": 0.0, "rows": []}):
            html = pravitrade.ideas_inner({}, True, now=NOW, force=True)
        self.assertIn("učitavam", html)
        self.assertEqual(pravitrade._IDEAS_CACHE, {})
        with mock.patch.object(zivo, "rows", lambda now=None, **k: []), \
                mock.patch.dict(zivo._ROWS, {"ts": float(NOW), "rows": []}):
            html = pravitrade.ideas_inner({}, True, now=NOW, force=True)
        self.assertEqual(html, "")   # a real empty list: cached and hidden as before
        self.assertIn(True, pravitrade._IDEAS_CACHE)
        pravitrade._IDEAS_CACHE.clear()


class KolCardsMinuteMeasure(unittest.TestCase):
    def test_minute_measure_shown_first_old_measure_marked(self):
        from ui import autopilot, pravitrade
        d = tempfile.mkdtemp()
        lg = store.connect(os.path.join(d, "league.db"))
        copy.ensure(lg)
        rows = [{"handle": "fast", "live": True, "why": "w", "s": {"hit": 0.0, "n": 0, "score": 0.5, "mjera": "minutna",
                                                                   "minute": {"n": 7, "hit10": 0.57, "hit15": 0.4, "sl": 0.2}}},
                {"handle": "old", "live": False, "why": "w", "s": {"hit": 0.5, "n": 4, "score": 0.3, "mjera": "fitilj"}}]
        with mock.patch.object(autopilot, "kol_recs", lambda now=None: {14: rows}), \
                mock.patch.object(pravitrade, "followed_targets", lambda con: set()):
            html = pravitrade._kol_section(lg, True)
        lg.close()
        self.assertIn("57% +10 % prije stopa · 7 poziva", html)
        self.assertIn("50% pogodaka · 4 callova (stara mjera)", html)
        self.assertIn("Minutna provjera = +10 % prije stopa", html)
        self.assertNotIn("Pogodak = cijena je u 24 h", html)


class OverviewSignalTs(unittest.TestCase):
    def test_token_rows_carry_signal_ts(self):
        import inspect
        from ui import overview
        src = inspect.getsource(overview._token_rows)
        self.assertIn('"signal_ts": s["last"]["ts"] if s else 0', src)


class ScanHolderFallback(unittest.TestCase):
    def test_pumpfun_extra(self):
        import run_hype
        shape = {"top10HoldersPercent": 41.0, "bundlerOwnedPercent": None, "snipersOwnedPercent": 3.0,
                 "devHoldingsPercent": None, "insidersPercent": None, "izvor": "RugCheck + rug filter"}
        self.assertEqual(run_hype._pumpfun_extra({}, shape), shape)
        self.assertIsNone(run_hype._pumpfun_extra(None, None))
        pf = run_hype._pumpfun_extra({"kolCount": 2, "top10HoldersPercent": 12.0}, shape)
        self.assertEqual((pf["kolCount"], pf["top10HoldersPercent"], pf.get("insidersPercent", "absent")), (2, 12.0, "absent"))
        self.assertEqual(set(pf), set(run_hype.PF_KEYS))


class FreshCheckDataTime(unittest.TestCase):
    def test_rc_ts_before_pass_time(self):
        from ui import topcheckui
        top = {"verdict": "prolazi", "ts": NOW - 60, "rc_ts": NOW - 3 * 3600, "safety": {"checks": {}}}
        html = topcheckui.token_box(top)
        self.assertIn("Podatak od", html)
        self.assertIn("prolaz provjere", html)
        html = topcheckui.token_box({"verdict": "prolazi", "ts": NOW - 60, "safety": {"checks": {}}})
        self.assertNotIn("prolaz provjere", html)


class StartShForwardsTerm(unittest.TestCase):
    def test_keep_traps_term_and_forwards_it(self):
        with open(os.path.join(ROOT, "start.sh")) as f:
            sh = f.read()
        keep = next(l for l in sh.splitlines() if l.startswith("keep() {"))
        self.assertIn("trap 'kill -TERM $pid", keep)
        self.assertIn('"$@" & pid=$!; wait $pid', keep)
        self.assertIn("trap 'kill -TERM $(jobs -p)", sh)


class NightWindowDefault(unittest.TestCase):
    """Review 9.11. (noć): the code window was 00-06 Zagreb while CLAUDE.md, learn/masovno.py and DNEVNIK say 01-06;
    the default is now "1-6" (deploys still come at 00:xx). The proven-twice list and the copy list (DB reads) get
    their own daytime loop in start.sh instead of sitting behind harvest/score --night once a night."""

    def test_default_window_is_01_06_zagreb(self):
        import inspect
        from ops import heavy
        self.assertIn('os.environ.get("HEAVY_NIGHT", "1-6")', inspect.getsource(heavy))
        with mock.patch.object(heavy, "NIGHT", "1-6"):
            self.assertEqual(heavy.night_hours(), (1, 6))

    def test_start_sh_has_a_daytime_dokazani_loop(self):
        sh = open(os.path.join(ROOT, "start.sh"), encoding="utf-8").read()
        lines = [ln for ln in sh.splitlines() if "run_wallets.py dokazani" in ln and not ln.strip().startswith("#")]
        self.assertEqual(len(lines), 2)   # once right after the nightly scores, once in its own WALLETS_EVERY_H loop
        self.assertTrue(all("--night" not in ln for ln in lines))


class IdeasFragmentBackground(unittest.TestCase):
    """Review: on the background path (BG_REFRESH=1 in production) an empty _IDEAS_CACHE returned "" (box hidden)
    instead of 'učitavam…', and the stamp showed the HTML assembly time rather than the DexScreener data time."""

    def setUp(self):
        from ui import pravitrade
        self.pt = pravitrade
        self.saved = (pravitrade.BG_REFRESH, pravitrade._BG["thread"], dict(pravitrade._IDEAS_CACHE))
        pravitrade._IDEAS_CACHE.clear()

        class Fake:
            def is_alive(self):
                return True
        pravitrade.BG_REFRESH, pravitrade._BG["thread"] = True, Fake()
        self.patches = [mock.patch.object(pravitrade, "_tcon", lambda: mock.MagicMock()),
                        mock.patch.object(pravitrade.settings, "can_view", lambda con, user: True),
                        mock.patch.object(pravitrade.settings, "is_owner", lambda user: True),
                        mock.patch.object(pravitrade, "_cfg", lambda con: {})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.pt.BG_REFRESH, self.pt._BG["thread"] = self.saved[0], self.saved[1]
        self.pt._IDEAS_CACHE.clear()
        self.pt._IDEAS_CACHE.update(self.saved[2])

    def test_empty_cache_says_loading_and_stamp_uses_data_time(self):
        self.assertIn("učitavam", self.pt.ideas_fragment("Jure"))
        with self.pt._LOCK:
            self.pt._IDEAS_CACHE[True] = (NOW, "<div class=ap-row>IDEJA</div>", NOW - 40)
        html = self.pt.ideas_fragment("Jure")
        self.assertIn("IDEJA", html)
        self.assertIn("podaci od " + time.strftime("%H:%M:%S", time.gmtime(NOW - 40)) + " UTC", html)
        with self.pt._LOCK:
            self.pt._IDEAS_CACHE[True] = (NOW, "<div class=ap-row>STARO</div>")   # a 2-tuple still works
        self.assertIn("podaci od " + time.strftime("%H:%M:%S", time.gmtime(NOW)) + " UTC", self.pt.ideas_fragment("Jure"))
        with self.pt._LOCK:
            self.pt._IDEAS_CACHE[True] = (NOW, "", NOW)
        self.assertEqual(self.pt.ideas_fragment("Jure"), "")   # a real empty list after the first pass: hidden

    def test_ideas_inner_keeps_the_oldest_checked_time(self):
        from ui import zivo
        rows = [{"token": TOK, "symbol": "A", "src": "x", "reasons": ["zove"], "checked": NOW - 7,
                 "live": {"mcap": 50_000, "ch_m5": 1.0, "ch_h1": 2.0}},
                {"token": "B" * 44, "symbol": "B", "src": "x", "reasons": [], "checked": NOW - 3,
                 "live": {"mcap": 60_000, "ch_m5": None, "ch_h1": None}}]
        with mock.patch.object(zivo, "rows", lambda now=None, **k: rows):
            html = self.pt.ideas_inner({}, True, now=NOW, force=True)
        self.assertIn("MC $50k", html)
        self.assertEqual(self.pt._IDEAS_CACHE[True][0], NOW)        # compute time: the TTL
        self.assertEqual(self.pt._IDEAS_CACHE[True][2], NOW - 7)    # data time: the oldest row shown


class LiveNegativeCache(unittest.TestCase):
    """Review: prijedlog.live_market -> None (DexScreener 429/5xx) cached nothing, so each 1-s poll of an open pop-up
    fetched again in the request thread; the failure is now remembered for LIVE_TTL_S and the old slot (< 60 s) or
    None is returned meanwhile."""

    def setUp(self):
        from ui import pravitrade, prijedlog
        self.pt, self.pr = pravitrade, prijedlog
        self.saved = (pravitrade._BG["thread"], dict(pravitrade._LIVE_CACHE), dict(pravitrade._LIVE_WANT),
                      dict(pravitrade._LIVE_FAIL), prijedlog.live_market)
        pravitrade._BG["thread"] = None   # no refresher: the synchronous path fetches
        for d in (pravitrade._LIVE_CACHE, pravitrade._LIVE_WANT, pravitrade._LIVE_FAIL):
            d.clear()

    def tearDown(self):
        self.pt._BG["thread"], c, w, f, self.pr.live_market = self.saved
        for d, v in ((self.pt._LIVE_CACHE, c), (self.pt._LIVE_WANT, w), (self.pt._LIVE_FAIL, f)):
            d.clear()
            d.update(v)

    def test_failure_is_remembered_for_the_ttl(self):
        calls = []
        self.pr.live_market = lambda toks, fetch=None: calls.append(1) and None
        self.assertIsNone(self.pt._live_cached([TOK], NOW))
        self.assertIsNone(self.pt._live_cached([TOK], NOW + 1))
        self.assertIsNone(self.pt._live_cached([TOK], NOW + 2.5))
        self.assertEqual(len(calls), 1)                              # one request per LIVE_TTL_S, not per poll
        self.assertIsNone(self.pt._live_cached([TOK], NOW + 3.1))
        self.assertEqual(len(calls), 2)

    def test_old_slot_is_served_while_dexscreener_fails(self):
        self.pr.live_market = lambda toks, fetch=None: {TOK: {"mcap": 1.0}}
        self.assertEqual(self.pt._live_cached([TOK], NOW), {TOK: {"mcap": 1.0}})
        self.pr.live_market = lambda toks, fetch=None: None
        self.assertEqual(self.pt._live_cached([TOK], NOW + 4), {TOK: {"mcap": 1.0}})     # 4 s old: kept
        self.assertEqual(self.pt._live_cached([TOK], NOW + 5), {TOK: {"mcap": 1.0}})     # within the negative TTL
        self.assertIsNone(self.pt._live_cached([TOK], NOW + 70))                         # too old to show: None
        self.pr.live_market = lambda toks, fetch=None: {TOK: {"mcap": 2.0}}
        self.assertEqual(self.pt._live_cached([TOK], NOW + 74), {TOK: {"mcap": 2.0}})    # recovered: fetched again
        self.assertNotIn((TOK,), self.pt._LIVE_FAIL)


class WarmSkipsFreshPages(unittest.TestCase):
    """Review (run_ui.warm_build): a build that returned the stored bytes was re-packed with ts=now, so the page's
    age restarted every pass; pagecache.warm now skips a page younger than skip_fresh_s before rendering."""

    def test_fresh_page_is_not_rendered_and_keeps_its_time(self):
        import gzip
        from ui import pagecache
        saved = dict(pagecache._store)
        pagecache._store.clear()
        built = []
        try:
            fresh = (time.time() - 10, 200, None, gzip.compress(b"<html>a</html>"))
            pagecache._store[("/warm-a", "", None)] = fresh
            pagecache._store[("/warm-b", "", None)] = (time.time() - 1000, 200, None, gzip.compress(b"<html>b0</html>"))
            pagecache.warm(["/warm-a", "/warm-b"], lambda p: built.append(p) or (200, b"<html>" + p.encode() + b"</html>"),
                           skip_fresh_s=240)
            for _ in range(100):
                if built:
                    break
                time.sleep(0.02)
            time.sleep(0.05)
            self.assertEqual(built, ["/warm-b"])
            self.assertIs(pagecache._store[("/warm-a", "", None)], fresh)
            self.assertEqual(gzip.decompress(pagecache._store[("/warm-b", "", None)][3]), b"<html>/warm-b</html>")
        finally:
            pagecache._store.clear()
            pagecache._store.update(saved)


if __name__ == "__main__":
    unittest.main()
