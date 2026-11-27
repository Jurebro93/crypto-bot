"""27.11. (vlasnik: "Izmjeri kopirljivost svakog walleta i influencera s kašnjenjem 5, 30 i 120 s i stvarnim
troškom"; wallets/kopirljivost.py), offline, synthetic databases only (no network, no real database):

  - one call copied: target first, stop first, out after the hour, no price near our entry = missed, the hour not
    over = not judged yet
  - positions without token amounts (the webhook's chain_trades)
  - the numbers and the verdict: enough priced trades in the plus = "kopirljivo", too few = "premalo podataka", in
    the minus = "nije kopirljivo", more than half missed = "premalo podataka"; missed trades are counted, never dropped
  - the whole pass on a synthetic market: the returns per delay computed by hand, after the 3 % cost floor; the
    source databases are not changed (read-only); the table holds every (source, delay)
  - the page box: plain words, empty without a result; the CLI's night gate

    python3 -m unittest tests.test_kopirljivost_offline
"""
import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import minute  # noqa: E402
from wallets import kopija, kopirljivost as K, store as wstore  # noqa: E402

D, H = 86400, 3600
NOW = 1795600000 // H * H
NOPATHS = {k: None for k in ("hype", "kol", "league", "market", "fast", "minute", "events", "early", "insajderi",
                             "range", "momentum", "midcap")}
MM = "Market" + "m" * 38


def wal(name):
    return (name + "w" * 44)[:44]


def tok(k):
    return f"Tok{k:05d}" + "x" * 33      # not a pump.fun mint: no supply, no estimated pool -> the 3 % floor


def ser(points):
    return kopija.Series([(t, p, 0) for t, p in points])


class OneCall(unittest.TestCase):
    def test_target_stop_time_missed_young(self):
        t0 = 1000
        up = ser([(t0 + 10, 1.0), (t0 + 300, 1.2)])
        s = K.simulate_call(t0, 5, up, hi=10 ** 6)
        self.assertEqual((s["why"], s["e_px"]), ("tp", 1.0))
        self.assertAlmostEqual(s["x_px"], 1.15)           # filled AT the target, never above it
        down = ser([(t0 + 10, 1.0), (t0 + 300, 0.7)])
        s = K.simulate_call(t0, 5, down, hi=10 ** 6)
        self.assertEqual((s["why"], s["x_px"]), ("stop", 0.7))   # filled at the point that crossed
        flat = ser([(t0 + 10, 1.0), (t0 + 600, 1.05), (t0 + 10 + 3600 + 30, 1.02)])
        s = K.simulate_call(t0, 5, flat, hi=10 ** 6)
        self.assertEqual((s["why"], s["x_px"]), ("vrijeme", 1.02))
        self.assertIsNone(K.simulate_call(t0, 120, ser([(t0 + 10, 1.0), (t0 + 400, 1.0)]), hi=10 ** 6))
        self.assertTrue(K.simulate_call(t0, 5, up, hi=t0 + 100)["young"])

    def test_call_trade_missed_and_cost_floor(self):
        empty = {"sol": ser([]), "usd": ser([]), "liq": [], "supply": None}
        t = K.call_trade(tok(1), 1000, 30, empty, 150.0, 10 ** 6, fee=0.0)
        self.assertTrue(t["missed"])
        self.assertIsNone(t["ret"])
        full = {"sol": ser([]), "usd": ser([(1040, 1.0), (1400, 1.3)]), "liq": [], "supply": None}
        t = K.call_trade(tok(1), 1000, 30, full, 150.0, 10 ** 6, fee=0.0)
        self.assertGreaterEqual(t["cost"], 0.03)
        self.assertAlmostEqual(t["ret"], 0.15 - 0.03)

    def test_under_30k_apart(self):
        full = {"sol": ser([]), "usd": ser([(1040, 1.0), (1400, 1.3)]), "liq": [], "supply": 10_000}
        t = K.call_trade(tok(1), 1000, 30, full, 150.0, 10 ** 6, fee=0.0)
        self.assertTrue(t["under"])
        self.assertIsNone(t["ret"])


class Episodes(unittest.TestCase):
    def test_simple(self):
        eps = K.simple_episodes([(1, "A", "buy"), (2, "A", "buy"), (5, "A", "sell"), (9, "A", "buy"), (3, "B", "sell")])
        self.assertEqual([(e["t0"], e["sell_ts"]) for e in eps], [(1, 5), (9, None)])


class Numbers(unittest.TestCase):
    def trs(self, rets, missed=0):
        out = [{"token": tok(k), "ts": NOW - (30 - k) * D, "ret": r, "cost": 0.03, "lag": 10}
               for k, r in enumerate(rets)]
        return out + [{"token": tok(100 + k), "ts": NOW, "ret": None, "missed": True} for k in range(missed)]

    def test_verdicts(self):
        s = K.stats(self.trs([0.1, 0.2, 0.05, 0.15] * 6))
        self.assertEqual((s["verdict"], s["n"], s["n_sig"]), ("kopirljivo", 24, 24))
        self.assertGreater(s["ci_lo"], 0)
        self.assertEqual(K.stats(self.trs([0.1] * 10))["verdict"], "malo")
        self.assertEqual(K.stats(self.trs([-0.1, 0.02, -0.2, 0.01] * 6))["verdict"], "nije")
        s = K.stats(self.trs([0.1] * 24, missed=30))
        self.assertEqual((s["verdict"], s["n_missed"], s["n_sig"]), ("malo", 30, 54))   # counted, not dropped

    def test_headline(self):
        self.assertEqual(K.headline({5: "kopirljivo", 30: "kopirljivo", 120: "kopirljivo"}),
                         "Kopirljivo, i uz kašnjenje od 2 minute")
        self.assertEqual(K.headline({5: "kopirljivo", 30: "nije", 120: "nije"}), "Kopirljivo samo uz vrlo brzo kopiranje")
        self.assertEqual(K.headline({5: "nije", 30: "malo", 120: "malo"}), "Nije kopirljivo")
        self.assertEqual(K.headline({5: "malo", 30: "malo", 120: "malo"}), "Premalo podataka")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Pass(unittest.TestCase):
    """Wallet "good" buys 1 SOL of a fresh token and sells 2 h later; the market prints every 5 s for 5 min after his
    buy at +0.1 % a second and flat at 1.5x after his sale. "bad" the same, sold at 0.8x. "dark" has no prints at all.
    Influencer "@good" calls tokens whose candles stay at 1.0 for 5 minutes and then 1.3 (target), "@bad" 0.7 (stop)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.wdb, self.kdb, self.mdb = (os.path.join(d, n) for n in ("wallets.db", "kol.db", "minute.db"))
        self.out = os.path.join(d, "kopirljivost.db")
        con = wstore.connect(self.wdb)
        rows, k = [], 0
        for name, mult in (("good", 1.5), ("bad", 0.8), ("dark", 1.5)):
            w = wal(name)
            con.execute("INSERT INTO wallets (wallet, first_seen, last_seen, scored_at) VALUES (?,?,?,?)",
                        (w, NOW - 40 * D, NOW, NOW - D))
            for j in range(24):
                k += 1
                m, t0 = tok(k), NOW - 30 * D + j * D + 3600
                rows += [(w, f"s{k}b", t0, m, 1e6, -1.0, "buy"), (w, f"s{k}s", t0 + 2 * H, m, -1e6, mult, "sell")]
                if name == "dark":
                    continue
                for s in range(5, 305, 5):
                    rows.append((MM, f"s{k}m{s}", t0 + s, m, 1e5, -0.1 * (1 + 0.001 * s), "buy"))
                    rows.append((MM, f"s{k}x{s}", t0 + 2 * H + s, m, -1e5, 0.1 * mult, "sell"))
        con.executemany("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()
        kc = sqlite3.connect(self.kdb)
        kc.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT)")
        mc = minute.connect(self.mdb)
        for h, after in (("good", 1.3), ("bad", 0.7)):
            for j in range(22):
                k += 1
                m, m0 = tok(k), (NOW - 25 * D + j * D) // 60 * 60
                kc.execute("INSERT INTO calls VALUES (?,?,?,?,?)", (f"t{k}", m, h, m0 + 10, "call"))
                kc.execute("INSERT INTO calls VALUES (?,?,?,?,?)", (f"t{k}r", m, h, m0 + 900, "call"))   # a repeat
                cs = [(m0 + i * 60, 1.0, 1.0, 1.0, 1.0, 1.0) if i < 5 else (m0 + i * 60, after, after, after, after, 1.0)
                      for i in range(80)]
                mc.execute("INSERT INTO call_candles VALUES (?,?,?,?,?,?,?)",
                           (m, cs[0][0], cs[-1][0], len(cs), minute._pack(cs), 1, NOW))
        kc.execute("INSERT INTO calls VALUES ('tg1', ?, 'tg:kanal', ?, 'call')", (tok(1), NOW - 5 * D))
        kc.commit()
        kc.close()
        mc.commit()
        mc.close()
        self.p = dict(NOPATHS, wallets=self.wdb, kol=self.kdb, minute=self.mdb)

    def tearDown(self):
        self.tmp.cleanup()

    def test_whole_pass(self):
        before = [sha(x) for x in (self.wdb, self.kdb, self.mdb)]
        logs = []
        res, meta = K.run(now=NOW, log=logs.append, p=self.p, budget_s=0, fee=0.0, path=self.out)
        self.assertEqual([sha(x) for x in (self.wdb, self.kdb, self.mdb)], before)   # read-only
        self.assertFalse(meta["partial"])
        self.assertIn("kopirljivost: ", logs[-1])
        g = res[("novcanik", wal("good"))]
        for d in K.DELAYS:
            first = (d + 4) // 5 * 5                       # the first print at or after his buy + d
            want = 1.5 / (1 + 0.001 * first) - 1 - 0.03
            self.assertEqual(g[d]["n"], 24)
            self.assertAlmostEqual(g[d]["med"], want, places=6)
            self.assertEqual(g[d]["verdict"], "kopirljivo")
        b = res[("novcanik", wal("bad"))]
        self.assertTrue(all(b[d]["verdict"] == "nije" for d in K.DELAYS))
        dk = res[("novcanik", wal("dark"))]
        self.assertEqual((dk[5]["n_missed"], dk[5]["n_sig"], dk[5]["verdict"]), (24, 24, "malo"))
        self.assertNotIn(("novcanik", MM), res)            # an unscored wallet is a price, not a source
        gi = res[("influencer", "good")]
        for d in K.DELAYS:
            self.assertEqual(gi[d]["n"], 22)               # one call per (account, token)
            self.assertAlmostEqual(gi[d]["med"], 0.15 - 0.03, places=6)
            self.assertEqual(gi[d]["verdict"], "kopirljivo")
        self.assertAlmostEqual(res[("influencer", "bad")][30]["med"], -0.30 - 0.03, places=6)
        self.assertNotIn(("influencer", "tg:kanal"), res)  # Telegram out of every calculation
        # stored: every (source, delay), and the page box reads it
        row = K.for_source("influencer", "good", self.out)
        self.assertEqual(sorted(row), list(K.DELAYS))
        self.assertEqual(row[30]["verdict"], "kopirljivo")
        html = str(K.box("novcanik", wal("good"), self.out))
        self.assertIn("Kopirljivost", html)
        self.assertIn("Kasnimo 2 min", html)
        self.assertIn("kopirljivo", html)
        for word in ("interval", "bootstrap", "MIN_N", "20 "):
            self.assertNotIn(word, html)
        self.assertEqual(K.box("novcanik", wal("nobody"), self.out), "")
        self.assertEqual(K.box("novcanik", wal("good"), os.path.join(self.tmp.name, "none.db")), "")

    def test_budget_cut_is_partial(self):
        with mock.patch.object(K.time, "time", side_effect=[0.0] + [10 ** 9] * 10 ** 6):
            _res, meta = K.compute(kopija.paths(self.p), NOW, budget_s=1, fee=0.0)
        self.assertTrue(meta["partial"])

    def test_cli_night_gate(self):
        import run_wallets
        a = argparse.Namespace(force=False, ako_nema=False, night=True)
        with mock.patch.object(run_wallets, "_in_night", return_value=False), \
                mock.patch.object(K, "run") as r:
            run_wallets.cmd_kopirljivost(a)
        r.assert_not_called()


if __name__ == "__main__":
    unittest.main()
