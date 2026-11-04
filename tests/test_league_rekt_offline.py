"""Natjecanje rekt + new rounds (4.11.): a player under $10 gets a fresh $1,000 and 💀×N, the bot plays round 2. No network."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import fixes, rekt, store  # noqa: E402
from ui import data, leaguedash  # noqa: E402

MINT = "So11111111111111111111111111111111111111112"
T0 = 1793300000   # 29.10.2026, before the bot's round-2 fix date


def bot_trade(i, opened, closed, pnl, reason="stop_loss", status="closed"):
    return {"id": i, "token": f"t{i}", "symbol": f"T{i}", "opened_ts": opened, "closed_ts": closed, "status": status,
            "pnl_usd": pnl, "ret": pnl / 50, "exit_reason": reason, "size_usd": 50, "state": {}}


class Rekt(unittest.TestCase):
    def setUp(self):
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        os.environ["UI_USERS"] = "Ivan,Mario"
        rekt._LAST["ts"] = 0

    def test_player_rekt_gets_new_round(self):
        con = store.connect()
        store.account(con, "Ivan")
        tid = store.buy(con, "Mario", MINT, "SOL", 1000, 1.0, 1e9)
        self.assertLess(store.account(con, "Mario")["cash"], 1)
        price = {"p": 1.0}
        market = lambda toks: {t: (price["p"], 1e9, None, 1e6) for t in toks}  # noqa: E731
        self.assertEqual(rekt.check_players(con, market), [])        # still worth ~$1000: not rekt
        price["p"] = 0.001
        self.assertEqual(rekt.check_players(con, lambda toks: {}), [])  # no price at all: never rekt on an outage
        con.execute("UPDATE trades SET opened_ts=opened_ts-60")   # bought a minute before the rekt
        out = rekt.check_players(con, market)
        self.assertEqual([u for u, _, _ in out], ["Mario"])
        acc = store.account(con, "Mario")
        self.assertAlmostEqual(acc["cash"], store.START_USD)        # fresh $1,000
        self.assertEqual(store.trades(con, "Mario", "open"), [])    # the rest was sold at the rekt
        self.assertEqual(store.trades(con, "Mario", "closed")[0]["id"], tid)
        board = {r["user"]: r for r in store.leaderboard(con, {})}
        self.assertAlmostEqual(board["Mario"]["profit"], 0, places=2)
        self.assertLess(board["Mario"]["total"], -990)               # every round together
        self.assertEqual(rekt.counts(con), {"Mario": 1})
        self.assertIn("💀×1", rekt.skulls(1))
        self.assertIn("comeback", rekt.skulls(1, 5.0))
        store.buy(con, "Mario", MINT, "SOL", 100, 1.0, 1e9)         # plays on with the new money
        self.assertAlmostEqual(store.account(con, "Mario")["cash"], 900)

    def test_bot_round_two_and_page(self):
        con = store.connect()
        con.execute("INSERT INTO accounts VALUES ('Ivan', 1000, ?)", (T0,))
        con.commit()
        self.assertTrue(fixes.bot_round2(con))
        self.assertFalse(fixes.bot_round2(con))                       # once
        r2 = rekt.since(con, "bot")
        trs = [bot_trade(1, T0 + 10, T0 + 100, -600), bot_trade(2, T0 + 20, T0 + 200, -450, "rug"),
               bot_trade(3, r2 - 50, r2 + 10, -40),                  # opened in round 1: not round 2's loss
               bot_trade(4, r2 + 5, r2 + 20, 30, "trailing")]
        data.paper_trades = lambda token=None: trs
        b = leaguedash._bot(T0, [r2])
        self.assertEqual(b["round"], 2)
        self.assertAlmostEqual(b["equity"], 1030)
        self.assertAlmostEqual(b["rounds"][0]["end_eq"], -50)
        lessons = leaguedash.round_lessons(b)
        self.assertIn("1. krug", lessons[0])
        self.assertIn("stop loss", lessons[0])
        mk = {}
        html = leaguedash.dashboard(con, mk, "Ivan")
        self.assertIn("Bot: 2. krug", html)
        self.assertIn("2. krug", leaguedash.api(con, mk))            # chart series name
        self.assertIn("Rekt klub", html)
        self.assertIsNone(rekt.check_bot(con, 500))
        self.assertEqual(rekt.check_bot(con, 3.0), 3)                 # under $10 again: round 3


if __name__ == "__main__":
    unittest.main()
