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


if __name__ == "__main__":
    unittest.main()
