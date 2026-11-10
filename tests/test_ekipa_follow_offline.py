"""Crew follows (league/copy kind 'ekipa', 9.11., Jure): "čekao bih da ova ekipa objavi token; ulaz čim objave, ako je
token ispod 1 M $ i još nije +25 % od poziva" — and how any crew is followed with real money from /pravi-trade."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import store as kstore  # noqa: E402
from league import copy, store  # noqa: E402

NOW = int(time.time())
CREW = ["tg:apewonecall", "tg:chinesewhalespump", "tg:kolclant", "tg:pandacallslonge3", "tg:whalespumpbank"]
TOK = "Tok1" + "x" * 40
TOK2 = "Tok2" + "x" * 40


class Crew(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.lg = store.connect(os.path.join(self.d, "league.db"))
        copy.ensure(self.lg)
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", ("pravi-trade", 1e6, 0))
        self.lg.commit()
        self.kc = kstore.connect(os.path.join(self.d, "kol.db"))
        self.paths = {"kol": os.path.join(self.d, "kol.db"), "hype": os.path.join(self.d, "no-hype.db"),
                      "tg": os.path.join(self.d, "no-tg.db")}

    def backdate(self):
        """Follows copy only calls after they were created; the tests' calls are a minute or two old."""
        self.lg.execute("UPDATE follows SET created = ?", (NOW - 3600,))
        self.lg.commit()

    def call(self, handle, tok, ts):
        self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')",
                        (f"{handle}-{tok[:4]}-{ts}", tok, handle, ts))
        self.kc.commit()

    def market(self, mcap, m5=0.0):
        return lambda toks: {t: (0.001, 50_000, None, mcap, "SYM", {"m5": m5, "h1": m5}) for t in toks}

    def test_follow_normalises_members_and_defaults(self):
        fid = copy.follow(self.lg, "pravi-trade", "ekipa", " @tg:whalespumpbank, tg:apewonecall ,tg:kolclant", "", 25, 5,
                          "tpsl", "15%", "", max_mcap=1e6, max_runup=0.25, min_callers=1)
        f = next(x for x in copy.follows(self.lg, "pravi-trade") if x["id"] == fid)
        self.assertEqual(f["target"], "tg:apewonecall,tg:kolclant,tg:whalespumpbank")
        self.assertEqual(f["label"], "ekipa: apewonecall + kolclant + whalespumpbank")
        self.assertEqual((f["exit"]["max_mcap"], f["exit"]["max_runup"], f["exit"]["min_callers"]), (1e6, 0.25, 1))
        self.assertIn("samo do MC $1M", copy.describe_exit(f["exit"]))
        self.assertIn("+25% od poziva", copy.describe_exit(f["exit"]).replace(" %", "%"))
        with self.assertRaises(ValueError):
            copy.follow(self.lg, "pravi-trade", "ekipa", " , ", "", 25, 5, "tpsl", "15%", "")
        self.assertEqual(copy.followed_handles("pravi-trade", os.path.join(self.d, "league.db")),
                         {"tg:apewonecall", "tg:kolclant", "tg:whalespumpbank"})

    def test_first_caller_enters_under_the_cap_and_before_the_runup(self):
        copy.follow(self.lg, "pravi-trade", "ekipa", ",".join(CREW), "", 25, 5, "tpsl", "15%", "",
                    max_mcap=1e6, max_runup=0.25)
        self.backdate()
        self.call("tg:kolclant", TOK, NOW - 60)                    # the first of the crew posts
        out = copy.run_once(self.lg, self.market(400_000, m5=8.0), NOW, self.paths)
        self.assertEqual(len(out), 1)
        self.assertIn("kupljeno", out[0][1])
        t = [tuple(r) for r in self.lg.execute("SELECT token, source, status FROM trades").fetchall()]
        self.assertEqual(t, [(TOK, "copy ekipa ekipa: apewonecall + chinesewhalespump + kolclant + pandacallslonge3 + whalespumpbank", "open")])
        # the second member calling the same token a minute later does not buy it again
        self.call("tg:apewonecall", TOK, NOW - 10)
        self.assertEqual(copy.run_once(self.lg, self.market(500_000), NOW + 5, self.paths), [])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 1)

    def test_skipped_over_the_cap_or_already_up(self):
        copy.follow(self.lg, "pravi-trade", "ekipa", ",".join(CREW), "", 25, 5, "tpsl", "15%", "",
                    max_mcap=1e6, max_runup=0.25)
        self.backdate()
        self.call("tg:kolclant", TOK, NOW - 60)
        self.call("tg:kolclant", TOK2, NOW - 90)
        mk = {TOK: (0.001, 50_000, None, 2_400_000, "BIG", {"m5": 3.0, "h1": 3.0}),
              TOK2: (0.001, 50_000, None, 300_000, "UP", {"m5": 41.0, "h1": 60.0})}
        self.assertEqual(copy.run_once(self.lg, lambda toks: mk, NOW, self.paths), [])
        notes = {r[0]: r[1] for r in self.lg.execute("SELECT token, note FROM copy_log WHERE action='preskočeno'")}
        self.assertIn("strop $1,000,000", notes[TOK])
        self.assertIn("+41% u zadnjih 5 min", notes[TOK2])   # 9.11. (audit P60): says what DexScreener measured
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_runup_of_a_5_to_10_min_old_call_reads_the_hour_change(self):
        """9.11. (audit P66): the only run_once path past 5 min (max_delay_min 10) gates on DexScreener's h1, not m5;
        the log says which window it measured. No linear scaling (verifier)."""
        copy.follow(self.lg, "pravi-trade", "ekipa", ",".join(CREW), "", 25, 5, "tpsl", "15%", "",
                    max_mcap=1e6, max_runup=0.25)
        self.backdate()
        self.call("tg:kolclant", TOK, NOW - 420)    # 7 min old: h1 decides
        self.call("tg:kolclant", TOK2, NOW - 400)
        mk = {TOK: (0.001, 50_000, None, 300_000, "A", {"m5": 2.0, "h1": 60.0}),
              TOK2: (0.001, 50_000, None, 300_000, "B", {"m5": 60.0, "h1": 2.0})}
        copy.run_once(self.lg, lambda toks: mk, NOW, self.paths)
        self.assertEqual({r[0] for r in self.lg.execute("SELECT token FROM trades")}, {TOK2})
        notes = {r[0]: r[1] for r in self.lg.execute("SELECT token, note FROM copy_log WHERE action='preskočeno'")}
        self.assertIn("+60% u zadnjih 60 min", notes[TOK])

    def test_min_callers_waits_for_the_second_member(self):
        copy.follow(self.lg, "pravi-trade", "ekipa", ",".join(CREW), "", 25, 5, "tpsl", "15%", "",
                    max_mcap=1e6, max_runup=0.25, min_callers=2)
        self.backdate()
        self.call("tg:kolclant", TOK, NOW - 120)
        self.assertEqual(copy.run_once(self.lg, self.market(400_000), NOW - 60, self.paths), [])
        self.call("tg:whalespumpbank", TOK, NOW - 30)
        out = copy.run_once(self.lg, self.market(400_000), NOW, self.paths)
        self.assertEqual(len(out), 1)
        # an outsider's call never counts for the crew
        self.call("tg:someone_else", TOK2, NOW - 20)
        self.assertEqual(copy.run_once(self.lg, self.market(400_000), NOW + 1, self.paths), [])

    def test_single_kol_follow_can_take_the_same_gates(self):
        copy.follow(self.lg, "pravi-trade", "kol", "ansem", "", 25, 5, "tpsl", "15%", "", max_mcap=500_000)
        self.backdate()
        self.call("ansem", TOK, NOW - 30)
        self.assertEqual(copy.run_once(self.lg, self.market(900_000), NOW, self.paths), [])
        self.assertIn("strop", self.lg.execute("SELECT note FROM copy_log").fetchone()[0])

    def test_runup_from_price_change(self):
        m = (0.001, 1, None, 1, "S", {"m5": 30.0, "h1": 80.0})
        self.assertAlmostEqual(copy._runup(m, 120), 0.30)
        self.assertAlmostEqual(copy._runup(m, 1800), 0.80)
        self.assertIsNone(copy._runup(m, 7200))
        self.assertIsNone(copy._runup((0.001, 1, None, 1, "S", None), 10))
        self.assertIsNone(copy._runup((0.001, 1, None, 1, "S"), 10))


class Page(unittest.TestCase):
    def setUp(self):
        import run_trade
        from trade import executor, settings
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB)
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        os.environ["TRADE_OWNER"] = "Jure"

    def tearDown(self):
        import run_trade
        from trade import settings
        (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB) = self._saved
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()
        os.environ.pop("TRADE_OWNER", None)

    def test_comma_list_becomes_a_crew_follow_with_jures_defaults(self):
        from trade import settings
        from ui import pravitrade
        self.assertEqual(pravitrade._detect_kind("tg:a, tg:b")[0], "ekipa")
        self.assertEqual(pravitrade._parse_usd("1,5M"), 1_500_000)
        self.assertEqual(pravitrade._parse_usd("800k"), 800_000)
        self.assertEqual(pravitrade._parse_pct("+25 %"), 0.25)
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": ", ".join("@" + c for c in CREW),
                                                      "exit": "tpsl", "per_day": "5"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertIn("ekipu", loc)
        fl = copy.follows(self.lg, settings.LEAGUE_USER)
        self.assertEqual([(f["kind"], f["target"]) for f in fl], [("ekipa", ",".join(CREW))])
        # 9.11. (audit P10/P17): "moj TP/SL" without a stop typed in gets the default stop (league/copy.DEFAULT_SL)
        self.assertEqual(fl[0]["exit"], {"mode": "tpsl", "tp": "15%", "sl": copy.DEFAULT_SL, "max_mcap": 1e6, "max_runup": 0.25, "min_callers": 1})
        _, body = pravitrade.page({"ekipa": "tg:x,tg:y"}, "Jure")
        # 10.11. (Jure: "čista, minimalistička"): the crew tag is the word "ekipa", without the 🤝 in front;
        # 10.11. (prijedlog dizajna, maketa autopilot.html): the follow is a shared row, the word starts its line
        self.assertIn('<div class="ms-s">ekipa · ', body)
        self.assertNotIn("🤝", body)
        self.assertIn('value="tg:x,tg:y"', body)       # prefilled from /ekipe "zaprati ekipu →"
        # "Zaprati sve" from "Zovu sada" makes ONE crew follow, not five single ones
        loc = pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha"}, "Jure")
        self.assertIn("ekipu", loc)
        fl = copy.follows(self.lg, settings.LEAGUE_USER)
        self.assertEqual(sorted(f["target"] for f in fl), sorted([",".join(CREW), "ansem,tg:alpha"]))
        self.assertIn("ve%C4%87%20prati", pravitrade.post("/pravi-trade/followall", {"handles": "tg:alpha, @ansem"}, "Jure"))

    def test_followed_handles_reach_polling_and_the_x_hook(self):
        from trade import settings
        copy.follow(self.lg, settings.LEAGUE_USER, "ekipa", "tg:alpha,bigx", "", 25, 5, "tpsl", "15%", "")
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "tg:solo", "", 25, 5, "tpsl", "15%", "")
        from tg import poll
        self.assertTrue({"alpha", "solo"} <= poll.followed_channels())
        from kol import xhook
        kc = kstore.connect(os.path.join(self.tmp.name, "kol.db"))
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")))
        self.assertEqual(xhook.handles(kc, cfg)[0], "bigx")
        kc.close()


if __name__ == "__main__":
    unittest.main()
