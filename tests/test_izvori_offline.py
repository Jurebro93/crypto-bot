"""Entry sources in the learning (learn/izvori.py): lift over the random control with a bootstrap range, "premalo
podataka" under 20 closed, point-in-time features (no lookahead), the shadow rows get them, and the Učenje card
renders."""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import izvori  # noqa: E402
from strat import store  # noqa: E402

DAY = 86400
T0 = 1793390000 // DAY * DAY


def add(con, strat, token, sig, ret, status="closed", entry=None, closed=None):
    con.execute("INSERT INTO positions (strat, token, signal_ts, seen_ts, entry_ts, status, ret, pnl_usd, closed_ts, "
                "state, size_usd) VALUES (?,?,?,?,?,?,?,?,?,?,50)",
                (strat, token, sig, sig, entry or sig, status, ret, (ret or 0) * 50, closed, json.dumps({})))


class Izvori(unittest.TestCase):
    def setUp(self):
        izvori._CACHE.update(ts=0, key=None, data=None)
        izvori._DAYS.clear()
        izvori._LIVE.update(ts=0, sigs=None, start=0)
        self.db = os.path.join(tempfile.mkdtemp(), "strat.db")
        self.con = store.connect(self.db)
        store.kv_set(self.con, "start_ts", T0)
        rnd = random.Random(1)
        for i in range(40):   # KOL clearly better than the control, alat_mali the same, insajderi too few
            ts = T0 + i * 3600
            add(self.con, "kol", f"K{i}", ts, 0.3 + rnd.uniform(-0.1, 0.1), closed=ts + 1800)
            add(self.con, "kontrola", f"R{i}", ts, -0.1 + rnd.uniform(-0.1, 0.1), closed=ts + 1800)
            add(self.con, "alat_mali", f"A{i}", ts, -0.1 + rnd.uniform(-0.1, 0.1), closed=ts + 1800)
        for i in range(5):
            add(self.con, "insajderi", f"I{i}", T0 + i * 3600, 1.0, closed=T0 + i * 3600 + 60)
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def test_lifts(self):
        now = T0 + 3 * DAY
        L = izvori.lifts(self.con, now)
        self.assertNotIn("kontrola", L)
        self.assertEqual(L["kol"]["status"], "bolje")
        self.assertGreater(L["kol"]["range"][0], 0)
        self.assertAlmostEqual(L["kol"]["weight"], L["kol"]["lift"], places=4)
        self.assertEqual(L["alat_mali"]["status"], "isto")
        self.assertEqual(L["alat_mali"]["weight"], 0.0)
        self.assertEqual(L["insajderi"]["status"], "premalo")
        self.assertIn("premalo podataka", L["insajderi"]["text"])
        self.assertEqual(L["top_novcanici"]["n"], 0)

    def test_no_lookahead(self):
        # before any trade closed every weight is 0, and a signal after the point is not seen
        self.assertTrue(all(v["weight"] == 0 for v in izvori.lifts(self.con, T0).values()))
        add(self.con, "kol", "X", T0 + 5 * DAY, 0.5, closed=T0 + 5 * DAY + 60)
        self.con.commit()
        sigs = izvori._signals(self.con)
        known = {k for k, _, _ in izvori.sources()}
        f = izvori.features_for("X", T0 + 4 * DAY, sigs, lambda d: {"kol": 0.4}, known, T0)
        self.assertEqual(f, {"izv_n": 0.0, "izv_tezina": 0.0})
        f = izvori.features_for("X", T0 + 5 * DAY, sigs, lambda d: {"kol": 0.4}, known, T0)
        self.assertEqual(f, {"izv_kol": 1.0, "izv_n": 1.0, "izv_tezina": 0.4})
        self.assertEqual(izvori.features_for("X", T0 - 10, sigs, lambda d: {}, known, T0), {})

    def test_alat_counts_from_entry_and_skip_ignored(self):
        add(self.con, "alat_srednji", "Y", T0 + 100, None, status="skip", entry=None)
        add(self.con, "alat_veliki", "Z", T0 + 100, None, status="open", entry=T0 + 900)
        self.con.commit()
        sigs = izvori._signals(self.con)
        self.assertNotIn("Y", sigs)
        self.assertEqual(sigs["Z"], [("alat_veliki", T0 + 900)])

    def test_enrich_point_in_time_weights(self):
        rs = [{"token": "K30", "ts": T0 + 30 * 3600 + 10, "features": {"a": 1}},
              {"token": "K39", "ts": T0 + 2 * DAY, "features": {}}, {"token": "Q", "ts": T0 - 5, "features": {}}]
        izvori.enrich(rs, self.db)
        self.assertEqual(rs[0]["features"]["a"], 1)
        self.assertEqual(rs[0]["features"]["izv_kol"], 1.0)
        # the first row's day: KOL trades closed before that day start exist (24 of them) -> weight > 0
        w_day1 = izvori.lifts(self.con, (T0 + 30 * 3600) // DAY * DAY)["kol"]
        self.assertAlmostEqual(rs[0]["features"]["izv_tezina"], w_day1["weight"], places=4)
        self.assertNotIn("izv_n", rs[2]["features"])

    def test_card(self):
        from ui import learnsources
        data = izvori.lifts(self.con, T0 + 3 * DAY)
        h = learnsources.card_html(data)
        self.assertIn("Bolji od nasumičnog ulaza", h)
        self.assertIn("premalo podataka", h)
        self.assertIn("ⓘ", h)
        self.assertIn("Izvori ulaza prema nasumičnom", learnsources.details_html(data))
        few = {k: {**v, "status": "premalo", "text": "premalo podataka (3 od 20 zatvorenih)"} for k, v in data.items()}
        self.assertIn("Još nema dovoljno", learnsources.card_html(few))

    def test_champion_rows_survive_without_db(self):
        from learn import champion
        old = os.environ.get("STRAT_DB")
        self.assertEqual(izvori.enrich([{"token": "a", "ts": 1}], os.path.join(tempfile.mkdtemp(), "none.db")),
                         [{"token": "a", "ts": 1}])
        self.assertTrue(callable(champion._rows))
        if old is not None:
            os.environ["STRAT_DB"] = old


if __name__ == "__main__":
    unittest.main()
