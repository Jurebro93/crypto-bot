"""5.11.: 'čekaj povlačenje' with proof (run_paper.pullbacks): a dip from the high since the signal, a followed
wallet buying during it, never into a tiny cap."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_paper  # noqa: E402
from paper import rules, store  # noqa: E402

NOW = 1_800_000_000
R = rules.DEFAULT["povlacenje"]


class Pullbacks(unittest.TestCase):
    def test_dip_with_a_followed_buyer(self):
        tmp = tempfile.mkdtemp()
        hype, kol, paper = (os.path.join(tmp, n) for n in ("hype.db", "kol.db", "paper.db"))
        h = sqlite3.connect(hype)
        h.executescript("""CREATE TABLE hype_signals (token TEXT, symbol TEXT, ts INTEGER, score REAL, price REAL, liquidity REAL, mcap REAL, features TEXT, sources TEXT, url TEXT);
                           CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, PRIMARY KEY (token, ts));
                           CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);""")
        # DIP: signalled 2 h ago at 1.0, peaked 1.5, now 1.2 (-20 %), mcap 120k, followed wallet bought 5 min ago
        for ts, px in ((NOW - 7200, 1.0), (NOW - 5400, 1.5), (NOW - 1800, 1.3)):
            h.execute("INSERT INTO hype_snapshots VALUES ('DIP', ?, ?, 120000, 30000)", (ts, px))
        h.execute("INSERT INTO hype_signals VALUES ('DIP','DIP',?,60,1.2,30000,120000,'{}','p','u')", (NOW - 60,))
        h.execute("INSERT INTO chain_trades VALUES ('b1','FOLLOWED','DIP','buy',?,1.0)", (NOW - 300,))
        # NOPROOF: same dip, buyer is not a followed wallet
        h.execute("INSERT INTO hype_snapshots VALUES ('NOPROOF', ?, 1.5, 120000, 30000)", (NOW - 5400,))
        h.execute("INSERT INTO hype_signals VALUES ('NOPROOF','NP',?,60,1.2,30000,120000,'{}','p','u')", (NOW - 60,))
        h.execute("INSERT INTO chain_trades VALUES ('b2','RANDOM','NOPROOF','buy',?,1.0)", (NOW - 300,))
        # TINY: dip with proof but mcap 20k
        h.execute("INSERT INTO hype_snapshots VALUES ('TINY', ?, 1.5, 20000, 5000)", (NOW - 5400,))
        h.execute("INSERT INTO hype_signals VALUES ('TINY','T',?,60,1.2,5000,20000,'{}','p','u')", (NOW - 60,))
        h.execute("INSERT INTO chain_trades VALUES ('b3','FOLLOWED','TINY','buy',?,1.0)", (NOW - 300,))
        # NODIP: still at the high
        h.execute("INSERT INTO hype_snapshots VALUES ('NODIP', ?, 1.2, 120000, 30000)", (NOW - 5400,))
        h.execute("INSERT INTO hype_signals VALUES ('NODIP','N',?,60,1.2,30000,120000,'{}','p','u')", (NOW - 60,))
        h.execute("INSERT INTO chain_trades VALUES ('b4','FOLLOWED','NODIP','buy',?,1.0)", (NOW - 300,))
        h.commit(); h.close()
        from kol import store as kstore
        k = kstore.connect(kol)
        k.execute("INSERT INTO kv VALUES ('chain_hook', ?)", (json.dumps({"wallets": ["FOLLOWED"]}),))
        k.commit(); k.close()
        con = store.connect(paper)
        old = run_paper.HYPE_DB
        run_paper.HYPE_DB = hype
        try:
            got = run_paper.pullbacks(con, R, NOW, hype_db=hype, kol_db=kol)
        finally:
            run_paper.HYPE_DB = old
        self.assertEqual(set(got), {"DIP"})
        self.assertAlmostEqual(got["DIP"]["drop"], -0.2)
        self.assertEqual(got["DIP"]["buyers"], 1)
        # an open trade on the token blocks a second entry
        con.execute("INSERT INTO trades (token, symbol, opened_ts, status, size_usd, entry_px, state, config) VALUES "
                    "('DIP','DIP',?,'open',25,1.2,'{}',?)", (NOW - 100, json.dumps({"entry_mode": "povlacenje"})))
        con.commit()
        run_paper.HYPE_DB = hype
        try:
            self.assertEqual(run_paper.pullbacks(con, R, NOW, hype_db=hype, kol_db=kol), {})
        finally:
            run_paper.HYPE_DB = old
        con.close()
        self.assertIn("povlacenje", run_paper.TRIGGER_MODES)


if __name__ == "__main__":
    unittest.main()
