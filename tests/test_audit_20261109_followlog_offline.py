"""9.11. (Jure: "walleti, influenceri i ekipe koje pratim imali su samo jedan trade - zašto?"): the Autopilot page
shows, per follow, what happened in the last 24 h (signals, entries, skips with reasons) from copy_log, and the real
trade loop logs every blocked order instead of writing the reason only into the positions table.

    python3 -m unittest tests.test_audit_20261109_followlog_offline
"""
import contextlib
import io
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from trade import executor, settings  # noqa: E402
from tests.test_trade_offline import CFG  # noqa: E402

NOW = time.time()


class FollowLogSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = store.DB
        store.DB = os.path.join(self.tmp.name, "league.db")
        self.con = store.connect(store.DB)
        copy.ensure(self.con)

    def tearDown(self):
        self.con.close()
        store.DB = self.saved
        self.tmp.cleanup()

    def _log(self, fid, token, action, note, ago=600):
        self.con.execute("INSERT OR IGNORE INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                         (fid, token, "buy", int(NOW - ago), int(NOW - ago), token[:4], action, note, None))

    def test_counts_entries_and_groups_skip_reasons_without_numbers(self):
        self._log(1, "TOKA", "ulaz", "kupljeno za $25 na MC $120,000, ...")
        self._log(1, "TOKB", "preskočeno", "vidjeli smo ga tek 12 min nakon objave; prekasno")
        self._log(1, "TOKC", "preskočeno", "vidjeli smo ga tek 37 min nakon objave; prekasno")
        self._log(1, "TOKD", "preskočeno", "MC $21,500 ispod 30k")
        self._log(1, "TOKE", "info", "prodao je token koji nismo kopirali")        # not a buy decision
        self._log(1, "TOKF", "preskočeno", "stari", ago=3 * 86400)                   # outside the window
        self._log(2, "TOKG", "preskočeno", "token je rugan (pad 80 %)")
        self.con.commit()
        s = copy.follow_log_summary(self.con, NOW - 86400)
        self.assertEqual((s[1]["signali"], s[1]["ulaz"], s[1]["preskočeno"]), (4, 1, 3))
        self.assertEqual(s[1]["razlozi"][0], ("vidjeli smo ga tek N min nakon objave", 2))   # 12 and 37 min grouped
        self.assertEqual(s[1]["razlozi"][1], ("MC $N ispod Nk", 1))
        self.assertEqual((s[2]["signali"], s[2]["ulaz"], s[2]["preskočeno"]), (1, 0, 1))
        self.assertEqual(s[2]["razlozi"], [("token je rugan", 1)])
        self.assertNotIn(3, s)

    def test_page_shows_the_last_24h_per_follow(self):
        from ui import pravitrade
        copy.follow(self.con, settings.LEAGUE_USER, "kol", "prvi", "", 25, 5)
        fid = copy.follows(self.con, settings.LEAGUE_USER)[0]["id"]
        self._log(fid, "TOKA", "preskočeno", "vidjeli smo ga tek 12 min nakon objave; prekasno")
        self._log(fid, "TOKB", "preskočeno", "vidjeli smo ga tek 40 min nakon objave; prekasno")
        self.con.commit()
        html = pravitrade._follows(self.con, True)
        self.assertIn("Zadnjih 24 h: 2 signala · 0 ulaza · preskočeno 2 (vidjeli smo ga tek N min nakon objave ×2)", html)
        copy.follow(self.con, settings.LEAGUE_USER, "kol", "drugi", "", 25, 5)
        html = pravitrade._follows(self.con, True)
        self.assertIn("nijedan signal koji bi prošao pravila kopiranja", html)


class BlockedOrderIsLogged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB)
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB) = self._saved
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def test_stale_copy_is_blocked_and_said_in_the_log(self):
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, 0))
        tid = store.buy(self.lg, settings.LEAGUE_USER, "OLDTOKEN", "OLD", 25, 1.0, 1e6, "copy wallet X")
        self.lg.execute("UPDATE trades SET opened_ts=? WHERE id=?", (int(NOW - 1000), tid))
        self.lg.commit()
        cfg = settings.merged(CFG, self.con)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=False)
        status, reason = self.con.execute("SELECT status, reason FROM positions WHERE token='OLDTOKEN'").fetchone()
        self.assertEqual(status, "blocked")
        self.assertIn("signal star", reason)
        self.assertIn("trade: DRY PRESKOČENO OLD (copy wallet X): signal star", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:   # the next second: the same block is not logged again
            run_trade.follow_league_once(self.con, cfg, since=0, now=NOW + 1, quiet=False)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.con.execute("SELECT count(*) FROM positions WHERE token='OLDTOKEN'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
