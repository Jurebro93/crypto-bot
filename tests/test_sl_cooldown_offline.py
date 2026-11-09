"""9.11.: no demo re-entry right after a stop loss (JENSEN hit the stop 3 times in a row: first entry plus two
"povratak" comebacks an hour apart). 8 h pause, doubled for each further stop loss within 48 h, at most 48 h.

    python3 -m unittest tests.test_sl_cooldown_offline
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper import rules, store  # noqa: E402

NOW = 1_794_200_000


def closed(con, tok, ts, reason="stop_loss"):
    tid = store.open_trade(con, tok, "S", {"opened_ts": ts - 600, "size_usd": 20, "entry_px": 1, "entry_eff": 1}, {})
    con.execute("UPDATE trades SET status='closed', closed_ts=?, exit_reason=?, ret=-0.3 WHERE id=?", (ts, reason, tid))


class SlCooldown(unittest.TestCase):
    def test_pause_grows_with_each_stop(self):
        con = store.connect(":memory:")
        closed(con, "ONE", NOW - 7 * 3600)                 # one stop 7 h ago: 1 h left
        closed(con, "OLD", NOW - 9 * 3600)                 # 9 h ago: free again
        closed(con, "TP", NOW - 600, "trailing")           # not a stop: no pause
        closed(con, "JENSEN", NOW - 20 * 3600)             # three stops: 32 h after the last
        closed(con, "JENSEN", NOW - 18 * 3600)
        closed(con, "JENSEN", NOW - 10 * 3600)
        p = rules.sl_paused(con, NOW)
        self.assertEqual(set(p), {"ONE", "JENSEN"})
        self.assertIn("još 1.0 h", p["ONE"])
        self.assertIn("3× stop loss", p["JENSEN"])
        self.assertIn("još 22.0 h", p["JENSEN"])
        self.assertEqual(rules.sl_paused(con, NOW, {"rules": {"sl_cooldown": {"enabled": False}}}), {})


if __name__ == "__main__":
    unittest.main()
