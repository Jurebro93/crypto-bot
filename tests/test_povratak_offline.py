"""4.11.: "povratak" = a second small demo entry into a token the demo lost on, when it is alive again (volume and
smart / tracked wallets buying), and trigger_points = every trigger evaluation as a shadow-book lesson.

    python3 -m unittest tests.test_povratak_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_paper  # noqa: E402
from learn import shadow  # noqa: E402
from paper import rules, store  # noqa: E402

NOW = 1793500000
R = rules.DEFAULT["povratak"]


def _hype_db(path, signals, buys):
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE hype_signals (token TEXT, symbol TEXT, ts INTEGER, score REAL, price REAL,
                            liquidity REAL, mcap REAL, features TEXT, sources TEXT, url TEXT);
                         CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);""")
    for tok, ts, score, feats in signals:
        con.execute("INSERT INTO hype_signals VALUES (?,?,?,?,1.0,20000,150000,?,'profile','u')",
                    (tok, tok, ts, score, json.dumps(feats)))
    for i, (tok, wallet, ts) in enumerate(buys):
        con.execute("INSERT INTO chain_trades VALUES (?,?,?,'buy',?,0.5)", (f"s{i}", wallet, tok, ts))
    con.commit()
    con.close()


def _closed_trade(con, tok, closed_ts, ret, mode="core"):
    con.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status, size_usd, entry_px, ret, config) "
                "VALUES (?,?,?,?,'closed',50,1.0,?,?)", (tok, tok, closed_ts - 1800, closed_ts, ret,
                                                        json.dumps({"entry_mode": mode})))


class Comebacks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.paper = os.path.join(self.tmp, "paper.db")
        self.hype = os.path.join(self.tmp, "hype.db")
        self.con = store.connect(self.paper)
        self.old = run_paper.HYPE_DB
        run_paper.HYPE_DB = self.hype

    def tearDown(self):
        run_paper.HYPE_DB = self.old
        self.con.close()

    def test_lost_token_alive_again_with_tracked_buyers(self):
        c = self.con
        _closed_trade(c, "BACK", NOW - 3 * 3600, -0.85)          # lost 85% three hours ago
        _closed_trade(c, "WON", NOW - 3 * 3600, 0.4)             # a winner: no comeback needed
        _closed_trade(c, "SOON", NOW - 600, -0.6)                # lost 10 min ago: cooldown
        _closed_trade(c, "DEAD", NOW - 3 * 3600, -0.9)           # lost, but no fresh signal
        _closed_trade(c, "QUIET", NOW - 3 * 3600, -0.9)          # fresh signal, but nobody buys
        _closed_trade(c, "TWICE", NOW - 3 * 3600, -0.9)          # already had two comebacks
        for _ in range(2):
            _closed_trade(c, "TWICE", NOW - 2 * 3600, -0.5, mode="povratak")
        c.commit()
        feats = {"turnover": 0.8, "smart_money": 0.0}
        _hype_db(self.hype, [("BACK", NOW - 300, 44, feats), ("WON", NOW - 300, 70, feats), ("SOON", NOW - 300, 60, feats),
                             ("QUIET", NOW - 300, 60, feats), ("TWICE", NOW - 300, 60, feats),
                             ("DEAD", NOW - 5 * 3600, 60, feats)],
                 [("BACK", "W1", NOW - 900), ("BACK", "W2", NOW - 600), ("TWICE", "W1", NOW - 600),
                  ("SOON", "W1", NOW - 60), ("QUIET", "W1", NOW - 5 * 3600)])
        got = run_paper.comebacks(c, R, NOW, hype_db=self.hype)
        self.assertEqual(set(got), {"BACK"})
        b = got["BACK"]
        self.assertEqual((b["buyers"], b["n_back"]), (2, 0))
        self.assertAlmostEqual(b["ret"], -0.85)
        self.assertAlmostEqual(b["turnover"], 0.8)

    def test_smart_money_feature_counts_without_chain_buys(self):
        _closed_trade(self.con, "SM", NOW - 3 * 3600, -0.7)
        self.con.commit()
        _hype_db(self.hype, [("SM", NOW - 300, 50, {"turnover": 0.5, "smart_money": 0.5})], [])
        self.assertIn("SM", run_paper.comebacks(self.con, R, NOW, hype_db=self.hype))
        _hype_db(self.hype + "2", [("SM", NOW - 300, 50, {"turnover": 0.1, "smart_money": 0.5})], [])
        run_paper.HYPE_DB = self.hype + "2"
        self.assertEqual(run_paper.comebacks(self.con, R, NOW, hype_db=self.hype + "2"), {})   # no volume

    def test_open_trade_blocks(self):
        _closed_trade(self.con, "OPEN", NOW - 3 * 3600, -0.7)
        self.con.execute("INSERT INTO trades (token, symbol, opened_ts, status, size_usd, entry_px, config) "
                         "VALUES ('OPEN','OPEN',?, 'open', 20, 1.0, '{}')", (NOW - 100,))
        self.con.commit()
        _hype_db(self.hype, [("OPEN", NOW - 300, 50, {"turnover": 0.9, "smart_money": 0.5})], [])
        self.assertEqual(run_paper.comebacks(self.con, R, NOW, hype_db=self.hype), {})


class TriggerPoints(unittest.TestCase):
    def test_every_look_becomes_a_shadow_point(self):
        tmp = tempfile.mkdtemp()
        paper = os.path.join(tmp, "paper.db")
        con = store.connect(paper)
        c = {"token": "T", "symbol": "T", "ts": NOW - 7200, "score": 55, "features": {"turnover": 0.9}, "price": 0.5,
             "liquidity": 30000, "mcap": 200000, "decision": "skip_gate", "reason": "T0 nije prošao"}
        store.add_trigger_point(con, c, "povratak")
        store.add_trigger_point(con, c, "povratak")                         # same look twice: one row
        c2 = {**c, "ts": NOW - 3600, "decision": "taken", "trade_id": 7, "reason": "povratak nakon gubitka"}
        store.add_trigger_point(con, c2, "povratak")
        con.commit()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM trigger_points").fetchone()[0], 2)
        con.close()
        sh = shadow.connect(os.path.join(tmp, "shadow.db"))
        new = shadow.collect(sh, hype_db=os.path.join(tmp, "none.db"), paper_db=paper, now=NOW)
        self.assertEqual(new.get("povratak"), 2)
        rows = sh.execute("SELECT id, point, decision, kupljeno, score FROM points ORDER BY ts").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(f"povratak:T:{NOW - 7200}", "povratak", "skip_gate", 0, 55),
                                                     (f"povratak:T:{NOW - 3600}", "povratak", "taken", 1, 55)])
        self.assertEqual(shadow.collect(sh, hype_db=os.path.join(tmp, "none.db"), paper_db=paper, now=NOW), {})


if __name__ == "__main__":
    unittest.main()
