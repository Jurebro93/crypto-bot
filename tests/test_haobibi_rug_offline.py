"""11.11. (Jure: "HAOBIBI je RUGAN u 12:51"): a hard block ends a pin and a counterfactual win; a reference for the
similarity must have stood 24 h without a rug."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rangedca import owner  # noqa: E402
from trade import settings  # noqa: E402

HAO = "8tbfkL8LZYUN3ygzWMKfffqVd7tLRpWkuh2fowsepump"
OTHER = "B" * 43


class Base(unittest.TestCase):
    def setUp(self):
        import sqlite3
        d = tempfile.mkdtemp()
        self._saved = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        self.tc = settings.connect()
        self.lpath = os.path.join(d, "league.db")
        self.lc = sqlite3.connect(self.lpath)
        owner.ensure_labels(self.lc)
        p = mock.patch.object(owner, "_league_db", lambda: self.lpath)
        p.start()
        self.addCleanup(p.stop)
        owner._CACHE["at"] = 0.0
        owner._CHK["at"] = 0.0
        self.now = int(time.time())
        settings.put(self.tc, owner.PINS_KEY, {HAO: {"symbol": "HAOBIBI", "ts": self.now}, OTHER: {"symbol": "OTH"}}, "t")
        for tok, ts in ((HAO, self.now - 2 * 3600), (OTHER, self.now - 30 * 3600)):
            self.lc.execute("INSERT INTO owner_labels (token, symbol, ts, label, kind, data, created_ts) VALUES "
                            "(?,?,?,?,?,?,?)", (tok, "X", ts, "win", "missed_win_stop_too_early",
                                                '{"features": {"ratio": 1.7}}', ts))
        self.lc.commit()

    def tearDown(self):
        self.tc.close()
        self.lc.close()
        settings.DB = self._saved


class Invalidate(Base):
    def test_one_time_order_unpins_and_turns_the_win_into_rug(self):
        logs = []
        with mock.patch.object(owner, "hard_block", lambda *a, **k: None), \
                mock.patch("league.exitplan.quote", lambda *a, **k: {}):
            done = owner.auto_check(self.lc, market_fn=lambda toks: {}, now=self.now, log=logs.append)
        self.assertIn("pin skinut", done)
        self.assertTrue(any("pobjeda → rug" in x for x in done))
        self.assertNotIn(HAO, settings.raw(self.tc).get(owner.PINS_KEY) or {})
        self.assertIn(OTHER, settings.raw(self.tc).get(owner.PINS_KEY) or {})
        lab = self.lc.execute("SELECT label, kind FROM owner_labels WHERE token=?", (HAO,)).fetchone()
        self.assertEqual(lab, ("rug", "rug_after_label"))
        owner._CHK["at"] = 0.0
        with mock.patch.object(owner, "hard_block", lambda *a, **k: None), \
                mock.patch("league.exitplan.quote", lambda *a, **k: {}):
            self.assertEqual(owner.auto_check(self.lc, market_fn=lambda toks: {}, now=self.now + 120, log=logs.append), [])

    def test_a_hard_block_on_a_pinned_token_unpins_it(self):
        owner.settings_marker = None
        settings.put(self.tc, f"owner_invalidate:{HAO}", self.now, "t")   # the one-time order already done
        q = {OTHER: (1.0, 50_000.0, 2_600.0, self.now)}
        with mock.patch("league.exitplan.quote", lambda *a, **k: q):
            done = owner.auto_check(self.lc, market_fn=lambda toks: {}, now=self.now, log=lambda s: None)
        self.assertIn("pin skinut", done)
        self.assertNotIn(OTHER, settings.raw(self.tc).get(owner.PINS_KEY) or {})

    def test_hard_block_reasons(self):
        with mock.patch("league.copy._rugged", lambda *a: None):
            self.assertIn("15k", owner.hard_block(OTHER, 50_000, 2_600))
            self.assertIsNone(owner.hard_block(OTHER, 50_000, 30_000))
        with mock.patch("league.copy._rugged", lambda *a: "pool povučen"):
            self.assertIn("rug", owner.hard_block(OTHER, 50_000, 30_000))


class References(Base):
    def test_a_reference_needs_24h_and_no_rug(self):
        ws = owner.wins(now=self.now)
        self.assertEqual([w["token"] for w in ws], [OTHER])          # HAOBIBI's label is only 2 h old
        self.lc.execute("UPDATE owner_labels SET label='rug' WHERE token=?", (OTHER,))
        self.lc.commit()
        self.assertEqual(owner.wins(now=self.now), [])


if __name__ == "__main__":
    unittest.main()
