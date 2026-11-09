"""Audit 9.11., group 'pravitrade' (ui/pravitrade.py): the manual buy ("Kupi") on the real-trade page.
N4  the exit rule and the stake are validated BEFORE the demo trade is written (no position without an exit rule,
    no error page with the buy already done behind it);
N10 a stake above max_sol_per_trade is refused on the page, not silently blocked later by gate_buy;
    a TP/SL buy without an explicit stop gets the default stop (league/copy.DEFAULT_SL), like copies do.

    python3 -m unittest tests.test_audit_20261109_pravitrade_offline
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from trade import executor, settings  # noqa: E402

MINT = "So11111111111111111111111111111111111111112"[:-1] + "3"
LIVE_ROW = {"price": 1.0, "liq": 1e6, "mcap": 5e5, "vol_h1": 20_000.0, "vol_h24": 1e5, "txns_h1": 80, "buys_h1": 50,
            "txns_h24": 900, "vol_m5": 900.0, "txns_m5": 6, "ch_m5": 1.0, "ch_h1": 3.0, "ch_h24": 10.0}


class ManualBuy(unittest.TestCase):
    def setUp(self):
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB,
                       uleague.market, collapse.check, uleague._symbol, prijedlog.live_market, os.environ.get("TRADE_OWNER"))
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        os.environ["TRADE_OWNER"] = "Jure"
        uleague.market = lambda toks: {t: (1.0, 1e6, None, 5e5) for t in toks}
        collapse.check = lambda *a, **k: None
        uleague._symbol = lambda t: "MAN"
        prijedlog.live_market = lambda toks, fetch=None: {t: dict(LIVE_ROW) for t in toks}

    def tearDown(self):
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB,
         uleague.market, collapse.check, uleague._symbol, prijedlog.live_market, owner) = self._saved
        if owner is None:
            os.environ.pop("TRADE_OWNER", None)
        else:
            os.environ["TRADE_OWNER"] = owner
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def _buy(self, **form):
        from ui import pravitrade
        base = {"token": MINT, "sol": "0,02", "exit": "tpsl", "tp": "100%", "sl": "-30%"}
        base.update(form)
        return pravitrade.post("/pravi-trade/buy", base, "Jure")

    def _open(self):
        return store.trades(self.lg, settings.LEAGUE_USER, "open")

    def test_bad_exit_rule_is_refused_before_anything_is_written(self):
        loc = self._buy(tp="abc")
        self.assertIn("err=", loc)
        self.assertEqual(self._open(), [])                       # no demo trade, so nothing for run_trade to mirror
        loc = self._buy(tp="$100k")                              # an MC target below the entry MC ($500k)
        self.assertIn("err=", loc)
        self.assertEqual(self._open(), [])
        loc = self._buy(exit="bilo-što")
        self.assertIn("err=", loc)
        self.assertEqual(self._open(), [])

    def test_stake_above_the_per_trade_limit_is_refused_on_the_page(self):
        lim = settings.merged(executor.load_config(), self.con)["max_sol_per_trade"]
        loc = self._buy(sol=str(lim * 3).replace(".", ","))
        self.assertIn("err=", loc)
        self.assertIn("iznad%20limita", loc)
        self.assertEqual(self._open(), [])
        self.assertEqual(settings.raw(self.con).get("manual_size"), None)   # no orphan stake record either

    def test_tpsl_without_a_stop_gets_the_default_stop(self):
        loc = self._buy(sl="")
        self.assertIn("ok=", loc)
        (t,) = self._open()
        a = json.loads(t["auto"])
        self.assertEqual(a["mode"], "tpsl")
        self.assertEqual(a["sl"], copy.DEFAULT_SL)                # "-20%", the same stop copies get
        self.assertAlmostEqual(a["sl_px"], 0.8)
        self.assertAlmostEqual(a["tp_px"], 2.0)

    def test_good_buy_still_goes_through_with_its_stake(self):
        loc = self._buy()
        self.assertIn("ok=", loc)
        (t,) = self._open()
        self.assertEqual(json.loads(t["auto"])["mode"], "tpsl")
        self.assertEqual(settings.raw(self.con)["manual_size"][str(t["id"])], 0.02)


if __name__ == "__main__":
    unittest.main()
