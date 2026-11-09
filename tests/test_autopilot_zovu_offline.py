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
        self.assertIn("Što kupiti sada", body)
        self.assertIn('value=10%', pravitrade._buy_form("TOK", settings.merged(CFG, self.con), "tpsl", True))   # TP/SL forms take it
        self.assertNotIn('value=10%', pravitrade._buy_form("TOK", settings.merged(CFG, self.con), "smart", True))
        self.assertIn("/pravi-trade/zovu", body)  # polled every LOG_EVERY_S seconds
        self.assertIn("/pravi-trade/ideje", body)
        # the top order: positions and the exit target before the log and the recommendations
        self.assertLess(body.index("id=cilj"), body.index("Zovu sada"))
        self.assertLess(body.index("Zovu sada"), body.index("Što kupiti sada"))
        self.assertLess(body.index("Što kupiti sada"), body.index("Koga bot prati"))

    def test_follow_all_callers_uses_the_target_and_skips_known(self):
        pravitrade.post("/pravi-trade/tp", {"tp": "20"}, "Jure")
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "100%", "")
        self.lg.commit()
        self.assertIn("err=", pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha"}, "Ivan"))
        loc = pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha,@murad"}, "Jure")
        self.assertIn("ok=", loc)
        fl = {f["target"]: f for f in copy.follows(self.lg, settings.LEAGUE_USER) if f["kind"] == "kol"}
        self.assertEqual(sorted(fl), ["ansem", "murad", "tg:alpha"])
        self.assertEqual(fl["ansem"]["exit"]["tp"], "100%")   # the existing follow keeps its own exit
        self.assertEqual(fl["tg:alpha"]["exit"], {"mode": "tpsl", "tp": "20%", "sl": ""})
        self.assertIn("Sve", pravitrade.post("/pravi-trade/followall", {"handles": "ansem"}, "Jure"))

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
