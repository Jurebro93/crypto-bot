"""Autopilot page additions of 9.11. (Jure): exit target at the top, "Zovu sada" (who called what in the last hour,
follow the whole crew), "Što kupiti sada", followed Telegram channels read every 2 s, time indexes."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from tests.test_trade_offline import CFG, FakeJup  # noqa: E402
from trade import executor, jupiter, settings  # noqa: E402
from ui import pravitrade  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = int(time.time())


class GroupCallers(unittest.TestCase):
    def test_groups_by_token_most_callers_first_and_first_caller_time(self):
        ev = [("TOK1", NOW - 600, "x", "ansem", "call"), ("TOK1", NOW - 300, "tg", "tg:alpha", "call"),
              ("TOK1", NOW - 100, "chain", "w:Abc123", "buy"), ("TOK1", NOW - 50, "x", "ansem", "call"),   # repeat: once
              ("TOK2", NOW - 10, "x", "murad", "call"), ("TOK3", NOW - 7200, "x", "old", "call"),             # too old
              ("TOK2", NOW - 5, "chain", "w:Abc123", "sell")]                                                 # sells don't count
        rows = pravitrade.group_callers(ev, NOW)
        self.assertEqual([r[0] for r in rows], ["TOK1", "TOK2"])
        tok, callers, first, last = rows[0]
        self.assertEqual([c[0] for c in callers], ["ansem", "tg:alpha", "w:Abc123"])
        self.assertEqual((first, last), (NOW - 600, NOW - 100))   # ansem's first call, not his repeat


class NotACall(unittest.TestCase):
    def test_majors_wrapped_and_xstocks_are_never_calls(self):
        from kol import converge
        self.assertIn("major", converge.not_a_memecoin("So11111111111111111111111111111111111111112"))
        self.assertIn("major", converge.not_a_memecoin("3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh", "WBTC"))
        self.assertIn("zamotana", converge.not_a_memecoin("SomeOtherWrapped", "cbBTC"))
        self.assertIn("xStock", converge.not_a_memecoin("Xc1", "COINx"))
        self.assertIn("xStock", converge.not_a_memecoin("Xc2", "TSLAx"))
        self.assertIn("likvidnost", converge.not_a_memecoin("Big1", "TRUMP", 9_000_000))
        self.assertIsNone(converge.not_a_memecoin("Meme1", "BANK", 35_000))
        self.assertIsNone(converge.not_a_memecoin("Meme2", "xdog", 35_000))   # lower-case ticker is not the pattern

    def test_gather_callers_filters_noise_and_counts_only_followed_wallets(self):
        from kol import store as kstore
        d = tempfile.mkdtemp()
        kp, hp, tp = os.path.join(d, "kol.db"), os.path.join(d, "hype.db"), os.path.join(d, "tg.db")
        kc = kstore.connect(kp)
        kc.executemany("INSERT INTO tokens (token, symbol, liquidity) VALUES (?,?,?)",
                       [("WBTCTOKEN" + "1" * 32, "WBTC", 50e6), ("COINXTOKEN" + "1" * 31, "COINx", 3e6),
                        ("BANKTOKEN" + "1" * 32, "BANK", 35_000), ("MEME" + "1" * 37, "MEME", 80_000)])
        kc.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')",
                       [("a", "WBTCTOKEN" + "1" * 32, "ansem", NOW - 300), ("b", "BANKTOKEN" + "1" * 32, "tg:alpha", NOW - 200),
                        ("c", "MEME" + "1" * 37, "murad", NOW - 100)])
        kc.commit()
        kc.close()
        hc = sqlite3.connect(hp)
        hc.execute("CREATE TABLE chain_trades (wallet TEXT, mint TEXT, side TEXT, ts INTEGER)")
        hc.execute("CREATE TABLE kol_mentions (ts INTEGER, handle TEXT, ca TEXT)")
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?)",
                       [("FOLLOWEDWALLET", "BANKTOKEN" + "1" * 32, "buy", NOW - 150), ("RANDOMWALLET", "COINXTOKEN" + "1" * 31, "buy", NOW - 50),
                        ("RANDOMWALLET", "MEME" + "1" * 37, "buy", NOW - 40), ("FOLLOWEDWALLET", "MEME" + "1" * 37, "sell", NOW - 30)])
        hc.commit()
        hc.close()
        rows = pravitrade.gather_callers(NOW, kol_db=kp, tg_db=tp, hype_db=hp, followed={"FOLLOWEDWALLET"})
        got = {r[4]: [c[0] for c in r[1]] for r in rows}
        self.assertEqual(set(got), {"BANK", "MEME"})                  # WBTC (wrapped) and COINx (xStock) are gone
        self.assertEqual(got["BANK"], ["tg:alpha", "w:FOLLOWEDWALLET"])   # the followed wallet's buy counts
        self.assertEqual(got["MEME"], ["murad"])                      # a random webhook wallet's buy does not
        self.assertEqual(rows[0][4], "BANK")                          # most callers first


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fake = FakeJup()
        self._saved = (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)
        os.environ["TRADE_OWNER"] = "Jure"

    def tearDown(self):
        (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB) = self._saved
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()
        os.environ.pop("TRADE_OWNER", None)

    def test_tp_target_owner_only_and_prefills_buy_forms(self):
        self.assertEqual(settings.merged(CFG, self.con)["tp_default"], 15)
        self.assertIn("err=", pravitrade.post("/pravi-trade/tp", {"tp": "10"}, "Ivan"))
        self.assertIn("err=", pravitrade.post("/pravi-trade/tp", {"tp": "12"}, "Jure"))   # not one of the choices
        loc = pravitrade.post("/pravi-trade/tp", {"tp": "10"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(settings.merged(CFG, self.con)["tp_default"], 10)
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Cilj izlaza za nove kopije", body)
        self.assertIn("sada +10 %", body)
        self.assertIn("Zovu sada", body)
        self.assertIn("tvoji i dokazani novčanici", body)
        self.assertIn("Što kupiti sada", body)
        self.assertIn('value=10%', pravitrade._buy_form("TOK", settings.merged(CFG, self.con), "tpsl", True))   # TP/SL forms take it
        self.assertNotIn('value=10%', pravitrade._buy_form("TOK", settings.merged(CFG, self.con), "smart", True))
        self.assertIn("/pravi-trade/zovu", body)  # polled every LOG_EVERY_S seconds
        self.assertIn("/pravi-trade/ideje", body)
        # the top order: positions and the exit target before the log and the recommendations
        self.assertLess(body.index("id=cilj"), body.index("Zovu sada"))
        self.assertLess(body.index("Zovu sada"), body.index("Što kupiti sada"))
        self.assertLess(body.index("Što kupiti sada"), body.index("Koga bot prati"))

    def test_follow_all_callers_makes_one_crew_follow(self):
        pravitrade.post("/pravi-trade/tp", {"tp": "20"}, "Jure")
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "100%", "")
        self.lg.commit()
        self.assertIn("err=", pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha"}, "Ivan"))
        loc = pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha,@murad"}, "Jure")
        self.assertIn("ok=", loc)
        fl = {f["target"]: f for f in copy.follows(self.lg, settings.LEAGUE_USER)}
        self.assertEqual(sorted(fl), ["ansem", "ansem,murad,tg:alpha"])
        self.assertEqual(fl["ansem"]["exit"]["tp"], "100%")   # the existing single follow keeps its own exit
        crew = fl["ansem,murad,tg:alpha"]
        self.assertEqual(crew["kind"], "ekipa")
        self.assertEqual(crew["exit"], {"mode": "tpsl", "tp": "20%", "sl": "", "max_mcap": 1e6, "max_runup": 0.25, "min_callers": 1})
        self.assertIn("ve%C4%87%20prati", pravitrade.post("/pravi-trade/followall", {"handles": "murad, ansem, tg:alpha"}, "Jure"))

    def test_live_log_hides_stale_trial_orders(self):
        """9.11. (Jure): the log said "osvježeno sada" above skipped trial orders from 5.8 days ago."""
        old = NOW - 6 * 86400
        for i, tok in enumerate(("EYED", "GTAVI", "DAVID")):
            self.con.execute("INSERT INTO orders (ts, token, side, mode, amount_in, status, reason) VALUES (?,?,?,?,?,?,?)",
                             (old + i, tok, "buy", "dry", 50_000_000, "blocked", "dnevni limit: potrošeno 0.500 od 0.5 SOL"))
        self.con.commit()
        html = pravitrade.log_fragment("Jure")
        self.assertIn("Danas nema naloga", html)
        self.assertIn("Starije od 24 h: 3 naloga (3 preskočeno)", html)
        self.assertNotIn("EYED", html)                      # not listed as if it were live
        self.assertIn("probno = bez pravog novca", html)
        self.con.execute("INSERT INTO orders (ts, token, side, mode, amount_in, status) VALUES (?,?,?,?,?,?)",
                         (NOW - 2 * 86400, "REAL", "buy", "live", 50_000_000, "ok"))
        self.con.execute("INSERT INTO orders (ts, token, side, mode, amount_in, status) VALUES (?,?,?,?,?,?)",
                         (NOW - 60, "FRESH", "buy", "dry", 50_000_000, "dry"))
        self.con.commit()
        html = pravitrade.log_fragment("Jure")
        self.assertNotIn("Danas nema naloga", html)
        self.assertIn("FRESH", html)
        self.assertIn("REAL", html)                         # a real order stays visible for a week
        self.assertNotIn("GTAVI", html)

    def test_ideas_read_the_suggestion_log_and_never_build_token_rows(self):
        """9.11. 12:30: building the picks in the UI process on every poll ran the server out of memory."""
        import sqlite3
        from ui import data, overview, prijedlog_log
        hp = os.path.join(self.tmp.name, "hype.db")
        con = sqlite3.connect(hp)
        con.execute(prijedlog_log.SCHEMA)
        con.executemany("INSERT INTO prijedlog_log (token, day, ts, kind, razina, mcap0, conf) VALUES (?,?,?,?,?,?,?)",
                        [("TOKA", "d", NOW - 600, "danas", "niska", 50000, 30), ("TOKB", "d", NOW - 300, "danas", "visoka", 120000, 70),
                         ("OLD", "d0", NOW - 2 * 86400, "danas", "visoka", 90000, 80)])
        con.commit()
        con.close()
        saved = (data.HYPE_DB, overview.token_rows)
        data.HYPE_DB = hp

        def boom(*a, **k):
            raise AssertionError("token_rows must not run in the UI process")
        overview.token_rows = boom
        pravitrade._IDEAS_CACHE.clear()
        try:
            picks = pravitrade.latest_picks(NOW)
            self.assertEqual([p["token"] for p in picks], ["TOKB", "TOKA"])   # best grade first, nothing older than a day
            html = pravitrade.ideas_inner(settings.merged(CFG, self.con), True, NOW)
            self.assertIn("TOKB", html)
            self.assertIn("dexscreener.com/solana/TOKB", html)
            self.assertIn("vjerojatnost visoka", html)
            self.assertIs(pravitrade.ideas_inner(settings.merged(CFG, self.con), True, NOW + 5), html)   # cached
        finally:
            data.HYPE_DB, overview.token_rows = saved
            pravitrade._IDEAS_CACHE.clear()

    def test_fragments_need_access(self):
        self.assertIsNone(pravitrade.callers_fragment("Ivan"))
        self.assertIsNone(pravitrade.ideas_fragment("Ivan"))
        self.assertIsInstance(pravitrade.callers_fragment("Jure"), str)
        self.assertIsInstance(pravitrade.ideas_fragment("Jure"), str)


class TelegramPolling(unittest.TestCase):
    def test_followed_channel_every_two_seconds_others_unchanged(self):
        from tg import poll
        cfg = json.load(open(os.path.join(ROOT, "tg", "config.json")))
        self.assertEqual(poll.interval(("alpha", "active", 0), cfg, {}, NOW, followed={"alpha"}), cfg["poll_followed_s"])
        self.assertEqual(cfg["poll_followed_s"], 2)
        cold = poll.interval(("cold", "active", 0), cfg, {}, NOW)
        self.assertGreaterEqual(cold, cfg["poll_hot_s"])   # a channel nobody follows keeps its slow schedule
        self.assertEqual(poll.interval(("hot", "active", NOW - 60), cfg, {}, NOW), cfg["poll_hot_s"])

    def test_due_reads_followed_channel_and_paces_validation(self):
        from tg import poll, store as tstore
        d = tempfile.mkdtemp()
        con = tstore.connect(os.path.join(d, "tg.db"))
        for name, st, lp, ca in (("alpha", "active", NOW - 3, 0), ("cold", "active", NOW - 3, 0), ("cand", "candidate", 0, 0)):
            con.execute("INSERT INTO channels (name, status, last_poll, last_ca_ts, found_via, found_ts) VALUES (?,?,?,?,?,?)",
                        (name, st, lp, ca, "channels.txt", NOW))
        con.commit()
        cfg = json.load(open(os.path.join(ROOT, "tg", "config.json")))
        saved = poll.followed_channels
        poll.followed_channels = lambda: {"alpha"}
        poll._PACE["validate_ts"] = 0
        try:
            validate, due = poll.due(con, cfg, {}, NOW)
            self.assertEqual(due, ["alpha"])
            self.assertEqual(validate, ["cand"])
            validate2, _ = poll.due(con, cfg, {}, NOW + 1)   # 1 s later: validation waits, polling does not
            self.assertEqual(validate2, [])
        finally:
            poll.followed_channels = saved
            poll._PACE["validate_ts"] = 0
            con.close()

    def test_no_league_db_means_nobody_followed(self):
        from league import store as lstore
        from tg import poll
        saved = lstore.DB
        lstore.DB = os.path.join(tempfile.mkdtemp(), "nema.db")
        try:
            self.assertEqual(poll.followed_channels(), set())
        finally:
            lstore.DB = saved


class Indexes(unittest.TestCase):
    def test_calls_have_a_time_index(self):
        from kol import store as kstore
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        names = {r[1] for r in con.execute("PRAGMA index_list(calls)")}
        self.assertIn("calls_ts", names)
        con.close()


if __name__ == "__main__":
    unittest.main()
