"""11.11. (Jure: "pokaži iz loga ili configa da su Grokovi limiti nepromijenjeni"): run_trade logs the limits in force
when the mode is logged (start and every change)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from trade import executor, settings  # noqa: E402


class LimitsLine(unittest.TestCase):
    def test_the_line(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        con = executor.connect(os.path.join(d.name, "trade.db"))
        self.addCleanup(con.close)
        settings.put(con, "owner_token_cap", 1.0, "t")
        settings.put(con, "dca_token_cap", 0.3, "t")
        line = run_trade.limits_line(con, {"max_sol_per_trade": 0.15})
        self.assertIn("Grok autotrade 0.1 SOL po tradeu, 0.3 SOL na dan, 3 otvorene, dnevni gubitak 0.15 SOL, 0.3 SOL po "
                      "tokenu", line)
        self.assertIn("LIVE_CAPS) 0.1/0.3 SOL, 3 otvorene, gubitak 0.15", line)
        self.assertIn("tvoje ručne kupnje: 1 SOL po tokenu, 0.15 SOL po tradeu", line)


if __name__ == "__main__":
    unittest.main()
