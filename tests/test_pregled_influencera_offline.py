"""Pregled influencera (league/followreview.py, 10.11., Jure: "isključi influencere koje sam ja stavio ako nema smisla
da ih se prati" -> "Isključi ih sam"): the owner's own KOL follows that clearly do not pay on their measured calls are
paused with the reason; thin records, winners, tool picks and follows the owner brought back stay.

    python3 -m unittest tests.test_pregled_influencera_offline
"""
import os
import sys
import tempfile
import time
import unittest
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import minute  # noqa: E402
from league import copy, followreview, store  # noqa: E402
from tests.test_tpsl_offline import LOSS, WIN, put  # noqa: E402
from trade import executor, settings  # noqa: E402

NOW = int(time.time())


class Review(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (settings.DB, store.DB, os.environ.get("TRADE_OWNER"))
        settings.DB, store.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        os.environ["TRADE_OWNER"] = "Jure"
        self.tc = executor.connect(settings.DB)
        self.lc = store.connect(store.DB)
        copy.ensure(self.lc)
        self.mc = minute.connect(os.path.join(d, "minute.db"))
        i = 0
        for handle, lv, n in (("gubitnik", LOSS, 12), ("pobjednik", WIN, 12), ("tanki", LOSS, 3), ("alatov", LOSS, 12)):
            for _ in range(n):
                i += 1
                put(self.mc, i, handle, lv)
        self.mc.commit()
        U = settings.LEAGUE_USER
        self.ids = {h: copy.follow(self.lc, U, "kol", h, h, 25, 5, "tpsl", "15%", "")
                    for h in ("gubitnik", "pobjednik", "tanki", "alatov")}
        settings.put(self.tc, "auto_follows", [self.ids["alatov"]], "alat")   # a tool pick: not the review's business

    def tearDown(self):
        settings.DB, store.DB, owner = self._saved
        if owner is None:
            os.environ.pop("TRADE_OWNER", None)
        else:
            os.environ["TRADE_OWNER"] = owner
        for c in (self.tc, self.lc, self.mc):
            c.close()
        self.tmp.cleanup()

    def active(self):
        return sorted(f["target"] for f in copy.follows(self.lc, settings.LEAGUE_USER))

    def test_only_the_owners_follow_that_clearly_loses_is_paused_with_the_reason(self):
        out = {f["target"]: v for f, v in followreview.review(self.lc, self.tc, NOW, mcon=self.mc)}
        self.assertTrue(out["gubitnik"]["pause"])
        self.assertIn("nijedan TP/SL par se ne isplati", out["gubitnik"]["why"])
        self.assertFalse(out["pobjednik"]["pause"])
        self.assertIn("u plusu", out["pobjednik"]["why"])
        self.assertFalse(out["tanki"]["pause"])
        self.assertIn("premalo", out["tanki"]["why"])
        self.assertNotIn("alatov", out)
        self.assertEqual(self.active(), ["alatov", "pobjednik", "tanki"])
        log = settings.raw(self.tc)["review_log"]
        self.assertEqual((log[0]["target"], log[0]["n"]), ("gubitnik", 12))
        self.assertEqual(settings.raw(self.tc)["review_last"]["paused"], 1)

    def test_vrati_brings_it_back_for_good(self):
        followreview.review(self.lc, self.tc, NOW, mcon=self.mc)
        followreview.restore(self.lc, self.tc, self.ids["gubitnik"], "Jure")
        self.assertIn("gubitnik", self.active())
        followreview.review(self.lc, self.tc, NOW + 3600, mcon=self.mc)
        self.assertIn("gubitnik", self.active())                    # the owner's choice holds
        with self.assertRaises(ValueError):
            followreview.restore(self.lc, self.tc, self.ids["pobjednik"], "Jure")   # never paused by the review

    def test_a_demo_in_the_plus_keeps_it(self):
        for k in range(3):
            self.lc.execute("INSERT INTO trades (user, token, opened_ts, status, pnl_usd, size_usd, follow_id) "
                            "VALUES (?,?,?,?,?,25,?)", (settings.LEAGUE_USER, f"D{k}", NOW, "closed", 5.0,
                                                         self.ids["gubitnik"]))
        self.lc.commit()
        out = {f["target"]: v for f, v in followreview.review(self.lc, self.tc, NOW, mcon=self.mc)}
        self.assertFalse(out["gubitnik"]["pause"])
        self.assertIn("u demu je u plusu", out["gubitnik"]["why"])

    def test_dry_run_changes_nothing(self):
        followreview.review(self.lc, self.tc, NOW, mcon=self.mc, apply=False)
        self.assertIn("gubitnik", self.active())
        self.assertIsNone(settings.raw(self.tc).get("review_log"))

    def test_the_page_lists_it_and_the_owner_brings_it_back(self):
        from ui import pravitrade
        pravitrade._LIVE_CACHE.clear()
        pravitrade._LIVE_FAIL.clear()
        followreview.review(self.lc, self.tc, NOW, mcon=self.mc)
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Pregled influencera", body)
        self.assertIn("action=/pravi-trade/reviewback", body)
        loc = unquote(pravitrade.post("/pravi-trade/reviewback", {"id": str(self.ids["gubitnik"])}, "Jure"))
        self.assertIn("ponovno uključeno", loc)
        self.assertIn("gubitnik", self.active())
        self.assertIn("err=", pravitrade.post("/pravi-trade/reviewback", {"id": str(self.ids["gubitnik"])}, "netko"))


if __name__ == "__main__":
    unittest.main()
