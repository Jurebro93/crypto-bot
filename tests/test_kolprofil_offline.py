"""Influenceri in the calm design (10.11., Jure, prijedlog 3.3, 4.4 i 4.5): the leaderboard /kol (verdict, 1 h and 24 h,
"Premalo poziva", Upravo zvali, Analize one tap away), the profile /kol/<ime> (verdict and four numbers, chart and
strips from the same calls the verdict counts) and the public leaderboard's verdict columns. No network."""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import minute, store  # noqa: E402
from ui import kol as ukol, kolchart, kolsummary as ks  # noqa: E402

DAY = 86400


class Fixture(unittest.TestCase):
    """kol.db + minute.db in a temp dir: @fast (10 calls, 8 hit +10 % before the stop, 1 of 10 up a day later),
    @steady (6 calls, all hit, 4 of 6 up a day later), @Rare (2 calls), @old (only calls older than 30 days)."""

    def setUp(self):
        ks._VCACHE.clear()
        self.d = tempfile.mkdtemp()
        self.kdb = os.path.join(self.d, "kol.db")
        self.mdb = os.path.join(self.d, "minute.db")
        self.now = int(time.time())
        con = store.connect(self.kdb)
        mcon = minute.connect(self.mdb)
        for i in range(10):
            ts = self.now - (2 + i % 8) * DAY - i * 60
            self._call(con, f"f{i}", f"T{i}", "fast", ts, r24=0.3 if i == 0 else -0.5, mcap=80000)
            mcon.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, t10, sl_min, r60) VALUES (?,?,?,?,?,?,?,?)",
                         (f"f{i}", f"T{i}", "fast", ts, 1.0, 3 + i if i < 8 else None, None if i < 8 else 5, -0.3))
        for i in range(6):
            ts = self.now - (3 + i) * DAY
            self._call(con, f"s{i}", f"S{i}", "steady", ts, r24=0.4 if i < 4 else -0.2, mcap=60000)
            mcon.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, t10, sl_min, r60) VALUES (?,?,?,?,?,?,?,?)",
                         (f"s{i}", f"S{i}", "steady", ts, 1.0, 2, None, 0.1))
        self._call(con, "f_low", "LOW", "fast", self.now - 3 * DAY, r24=5.0, mcap=12000)   # under 30k $: not counted
        for i in range(2):
            self._call(con, f"r{i}", f"R{i}", "Rare", self.now - 3 * DAY, r24=0.5, mcap=50000)
        self._call(con, "o1", "O1", "old", self.now - 40 * DAY, r24=0.5, mcap=50000)
        stats = {"fast": {"measured": 12, "rug_rate": 0.35}, "steady": {"measured": 6, "rug_rate": 0.0},
                 "Rare": {"measured": 2}, "old": {"measured": 1}}
        for h, sc in (("fast", 58), ("steady", 61), ("Rare", 40), ("old", 50)):
            con.execute("INSERT INTO kols (handle, name, followers, score, stats) VALUES (?,?,?,?,?)",
                        (h, h.title(), 34047 if h == "fast" else 900, sc, json.dumps(stats[h])))
        con.execute("INSERT INTO tokens (token, symbol) VALUES ('T0', 'GIGA<FROG>')")
        con.commit()
        mcon.commit()
        con.close()
        mcon.close()
        self._old_db = store.DB
        store.DB = self.kdb
        self._env = mock.patch.dict(os.environ, {"MINUTE_DB": self.mdb})
        self._env.start()

    def tearDown(self):
        store.DB = self._old_db
        self._env.stop()
        ks._VCACHE.clear()

    def _call(self, con, tid, tok, handle, ts, r24, mcap, kind="call"):
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, r24h, mcap0, first_by_kol, url, text) "
                    "VALUES (?,?,?,?,?,?,?,1,?,?)", (tid, tok, handle, ts, kind, r24, mcap,
                                                     f"https://x.com/{handle}/status/{tid}", "gem"))


class Counts(unittest.TestCase):
    def test_counts_sentence_per_verdict(self):
        base = {"n1": 30, "hits1": 21, "n24": 30, "plus24": 2}
        s = ks.verdict_counts({**base, "key": "samo_brzo", "sentence": "x"})
        self.assertIn("21 od 30 poziva dođe do +10 %", s)
        self.assertIn("28 od 30 završi u minusu", s)
        self.assertIn("16 od 30 je u plusu", ks.verdict_counts({**base, "plus24": 16, "key": "drzi_se", "sentence": ""}))
        self.assertTrue(ks.verdict_counts({**base, "hits1": 9, "key": "ne_isplati_se", "sentence": ""}).startswith("Samo 9 od 30"))
        self.assertIn("još se ne zna", ks.verdict_counts({**base, "n24": 3, "key": "samo_brzo", "sentence": ""}))
        self.assertEqual(ks.verdict_counts({"key": "premalo", "sentence": "Samo 2 izmjerena poziva"}), "Samo 2 izmjerena poziva")
        self.assertEqual(set(ks.VERDICT_WORD_EN), set(ks.VERDICT_WORD))


class Series(Fixture):
    def test_same_calls_as_the_verdict(self):
        v = ks.kol_verdict("fast")
        sr = kolchart.series("fast", 14, self.now)
        self.assertEqual((sr["n1"], sr["hits1"]), (v["n1"], v["hits1"]))
        self.assertEqual((sr["n24"], sr["plus24"]), (v["n24"], v["plus24"]))
        self.assertEqual((sr["n1"], sr["hits1"], sr["n24"], sr["plus24"]), (10, 8, 10, 1))
        # fast exit: 8 × +10 % and 2 stops × −20 % of 10 $; hold 24 h: +30 % once and −50 % nine times
        self.assertAlmostEqual(sr["fast_usd"], 8 * 1.0 - 2 * 2.0)
        self.assertAlmostEqual(sr["hold_usd"], 3.0 - 9 * 5.0)
        self.assertEqual(sr["med_t10"], 6.5)                       # t10 of the hits: 3..10
        self.assertEqual(sr["h1"][-1]["ts"] >= sr["h1"][0]["ts"], True)
        self.assertEqual(kolchart.series("nobody", 14, self.now)["fast_usd"], None)

    def test_chart_and_strips(self):
        sr = kolchart.series("fast", 14, self.now)
        ch = kolchart.chart(sr)
        self.assertEqual(ch.count("<path "), 2)
        self.assertIn("brzi izlaz", ch)
        self.assertIn("+4 $", ch)                              # legend values
        self.assertIn("−42 $", ch)
        self.assertIn("0 $", ch)                               # zero line labelled
        st = kolchart.strips(sr)
        self.assertEqual(st.count('class="kc-sq"'), 8 + 1)          # 8 hits in 1 h, 1 plus in 24 h
        self.assertEqual(st.count('class="kc-sq n"'), 2 + 9)
        self.assertIn("GIGA&lt;FROG&gt;", st)                       # symbol escaped in the tooltip
        empty = kolchart.series("nobody", 14, self.now)
        self.assertEqual(kolchart.chart(empty), "")
        self.assertEqual(kolchart.strips(empty), "")

    def test_axis_and_money(self):
        top, bot, ticks = kolchart._axis([-185.0, 3.0])
        self.assertLessEqual(bot, -185)
        self.assertGreaterEqual(top, 3)
        self.assertIn(0.0, ticks)
        self.assertEqual(kolchart.money(-185.4), "−185 $")
        self.assertEqual(kolchart.money(3), "+3 $")


class Board(Fixture):
    def _kols(self):
        con = store.ro()
        try:
            ks_ = ukol._rows(con, "SELECT handle, name, followers, score, stats FROM kols")
        finally:
            con.close()
        for k in ks_:
            k["s"] = json.loads(k["stats"])
        return ks_

    def test_ranked_by_first_hour_few_apart(self):
        ranked, few = ukol.board(self._kols(), ks.verdict_stats(14))
        self.assertEqual([r["k"]["handle"] for r in ranked], ["steady", "fast"])
        self.assertEqual([r["k"]["handle"] for r in few], ["Rare"])     # @old has no call in the window: not listed
        self.assertEqual(ranked[0]["v"]["key"], "drzi_se")
        row = ukol.board_row(ranked[1], 2, self.now)
        self.assertIn("rug 35", row)                                   # 30 %+ rugs replace the call count, in orange
        self.assertIn('data-h1="0.8"', row)
        self.assertIn('class="c1">80', row)
        few_row = ukol.board_row(few[0], None, self.now)
        self.assertIn("2 poziva · premalo", few_row)
        self.assertIn("c1 mut", few_row)

    def test_page(self):
        with mock.patch("ui.kol.ap_follows", return_value={"steady": "kol"}):
            title, body = ukol.page({})
        self.assertEqual(title, "Influenceri")
        hero = body.split('class="ms-seg"')[0]
        self.assertIn("@steady", hero)                                 # best first hour, holds up a day later
        self.assertIn("4 od 6 je u plusu", hero)
        self.assertIn("<span class=adm-only> · Autopilot ga prati</span>", hero)
        self.assertNotIn("Drže se i 24 h", hero)                      # nobody else holds up: no foot line
        self.assertEqual(body.count("class=kl-set "), 2 * len(ukol.BOARD_DAYS))
        self.assertEqual(len(re.findall(r"class=kl-set data-g=\w+ data-d=\d+>", body)), 1)   # one visible list
        self.assertIn("Premalo poziva", body)
        self.assertIn('data-pane=pozivi id=pozivi hidden', body)       # Upravo zvali: second half of the segment
        self.assertIn("/kol/analize#zajedno", body)
        self.assertIn('"provjera"', body)                              # old /kol#<id> links go to /kol/analize
        self.assertNotIn("<h2 class=\"ms-h2\"", body)                  # no section chips (nosec) on the calm page
        self.assertIsNone(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", re.sub(r"<style>.*?</style>", "", body, flags=re.S)))

    def test_profile(self):
        with mock.patch("ui.kol.ap_follows", return_value={}):
            title, body = ukol.kol_page("fast", {})
        self.assertEqual(title, "@fast")
        self.assertIn("Samo za brzi izlaz", body)
        self.assertIn("U prvom satu 8 od 10 poziva", body)
        self.assertIn("9 od 10 završi u minusu", body)
        for t in ("Nakon 60 min", "Nakon 24 h", "10 $ u svaki poziv", "Stižemo li ga"):
            self.assertIn(t, body)
        self.assertIn("8 od 10", body)
        self.assertIn("1 od 10", body)
        self.assertIn("9 u minusu", body)
        self.assertIn("Sporije", body)                                 # not on the webhook nor the hot list
        self.assertIn("<div class=adm-only><a class=kl-sw", body)      # Autopilot switch: admin only, to /pravi-trade
        self.assertIn("Autopilot ga ne prati", body)
        self.assertIn("/kol/fast/pozivi", body)
        self.assertIn("/kol/fast/vise#ocjena", body)
        self.assertIn("34 tis. pratitelja", body)
        self.assertIn("GIGA&lt;FROG&gt;", body)
        self.assertIn("ne broji se", body)                             # the 12k $ call in "Zadnji pozivi"
        self.assertIn("kc-chart", body)
        with mock.patch("ui.kol.ap_follows", return_value={"fast": "ekipa"}):
            self.assertIn("kao dio ekipe", ukol.kol_page("fast", {})[1])
        self.assertIn("Kako je dobio ocjenu", ukol.kol_page("fast/vise", {})[1])
        self.assertIn("Nema poziva", ukol.kol_page("nobody", {})[1])


    def test_telegram_and_bot_profiles(self):
        con = store.connect(self.kdb)
        con.execute("INSERT INTO kols (handle, name, followers, score, stats) VALUES ('tg:kanal', 'Kanal', 500, 50, '{}')")
        con.execute("INSERT INTO kols (handle, name, followers, score, stats, bot, bot_why) VALUES "
                    "('spam1', 'S', 10, NULL, '{\"bot_score\": 30}', 1, 'objavljuje svaki novi token')")
        self._call(con, "t1", "TG1", "tg:kanal", self.now - DAY, r24=0.2, mcap=70000)
        con.commit()
        con.close()
        with mock.patch("ui.kol.ap_follows", return_value={}):
            title, body = ukol.kol_page("tg:kanal", {})
            self.assertEqual(title, "kanal")
            self.assertIn("kanal na Telegramu", body)
            self.assertIn("https://t.me/kanal", body)
            title, body = ukol.kol_page("spam1", {})
        self.assertIn("Bot, spam, promo ili dev račun", body)
        self.assertIn("Premalo poziva za presudu", body)
        self.assertIn("Kako je dobio ocjenu 30", body)


class Routes(unittest.TestCase):
    def test_analize_is_heavy_and_snapshotted(self):
        import run_ui
        self.assertIn("/kol/analize", run_ui.HEAVY)
        self.assertIn("/kol/analize", run_ui.SNAPSHOT_ONLY)
        with mock.patch("ui.kol.analize_page", return_value=("A", "x")) as a, \
                mock.patch("ui.kol.kol_page", return_value=("B", "y")) as k:
            self.assertEqual(run_ui.route("/kol/analize", {}), ("A", "x"))
            self.assertEqual(run_ui.route("/kol/fast/pozivi", {}), ("B", "y"))
        a.assert_called_once()
        k.assert_called_once_with("fast/pozivi", {})


class Public(Fixture):
    def test_leaderboard_verdict_columns(self):
        from ui import public
        with mock.patch.dict(os.environ, {"KOL_DB": self.kdb}):
            public._cache.clear()
            ks._VCACHE.clear()
            en = public.leaderboard("en")
            hr = public.leaderboard("hr")
        self.assertIn("<th>Verdict</th><th class=n>1 h</th><th class=n>24 h</th>", en)
        self.assertIn("holds up", en)
        self.assertIn("quick exit only", en)
        self.assertIn("drži se", hr)
        self.assertIn("<th>Presuda</th>", hr)
        self.assertIn("1 h 50%", hr)                                   # thresholds from kolsummary in the explanation


if __name__ == "__main__":
    unittest.main()
