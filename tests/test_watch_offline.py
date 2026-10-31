"""Pre-event watch: sync, snapshots, buyers and correlation against canned data (no network).

    python3 -m unittest discover -s tests
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_watch  # noqa: E402
from dexscreener import client  # noqa: E402
from eventwatch import analyze, store  # noqa: E402

NOW = 1_793_000_000  # 2026-10-26 ~
DEX = {"events": [
    {"event": "GTA VI release", "date": "2026-11-05", "token_likelihood": 0.8, "tokens": [
        {"token": "GTA1", "symbol": "GTA6", "name": "GTA VI", "role": "canonical", "url": "u1"},
        {"token": "GTA2", "symbol": "GTA", "name": "GTA memes", "role": "copycat", "url": "u2"},
        {"token": "GTA3", "symbol": "VICE", "name": "Vice", "role": "copycat", "url": "u3"},
        {"token": "GTA4", "symbol": "LUCIA", "name": "Lucia", "role": "copycat", "url": "u4"}]},
    {"event": "Far away", "date": "2027-03-01", "token_likelihood": 0.9, "tokens": [
        {"token": "FAR", "symbol": "FAR", "name": "Far", "role": "canonical", "url": "u"}]},
    {"event": "Unlikely", "date": "2026-10-28", "token_likelihood": 0.1, "tokens": [
        {"token": "NOPE", "symbol": "NOPE", "name": "Nope", "role": "canonical", "url": "u"}]},
]}


def _pair(token, vol_h1, buys_h1, price=0.01):
    return {"baseToken": {"address": token}, "priceUsd": str(price), "marketCap": 1e5, "liquidity": {"usd": 5e4},
            "volume": {"h1": vol_h1, "h24": vol_h1 * 24}, "txns": {"h1": {"buys": buys_h1, "sells": 3},
                                                                  "h24": {"buys": buys_h1 * 24, "sells": 70}}}


class WatchOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = store.connect(os.path.join(self.tmp.name, "w.db"))
        self._tokens, self._buyers, self._wdb = client.tokens, run_watch.recent_buyers, run_watch.WALLET_DB
        wdb = os.path.join(self.tmp.name, "wallets.db")
        c = sqlite3.connect(wdb)
        c.execute("CREATE TABLE wallets (wallet TEXT PRIMARY KEY, tier TEXT, labels TEXT)")
        c.executemany("INSERT INTO wallets VALUES (?,?,?)", [("SMART", "A", "[]"), ("RUG", "D", '["rugger"]')])
        c.commit()
        c.close()
        run_watch.WALLET_DB = wdb

    def tearDown(self):
        client.tokens, run_watch.recent_buyers, run_watch.WALLET_DB = self._tokens, self._buyers, self._wdb
        self.con.close()
        self.tmp.cleanup()

    def test_sync_window_and_likelihood(self):
        self.assertEqual(run_watch.sync(self.con, DEX, per_event=3, now=NOW), 3)
        toks = {r[0] for r in self.con.execute("SELECT token FROM watch_tokens")}
        self.assertEqual(toks, {"GTA1", "GTA2", "GTA3"})  # far event, unlikely event and 4th token left out
        self.assertEqual(run_watch.sync(self.con, DEX, now=NOW), 0)  # idempotent
        run_watch.sync(self.con, DEX, now=NOW + 12 * 86400)  # event was 2 days ago
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM watch_tokens WHERE active=1").fetchone()[0], 0)

    def test_snapshots_buyers_and_correlation(self):
        run_watch.sync(self.con, DEX, per_event=1, now=NOW)
        calls = []

        def fake_buyers(mint, since, on_credits=None):
            calls.append(since)
            on_credits(10)
            k = len(calls)
            return {f"W{k}": (NOW, 0.5, 1), "SMART": (NOW, 1.0, 1), "RUG": (NOW, 2.0, 1)} if k == 1 else {f"W{k}": (NOW, 0.5, 1)}

        run_watch.recent_buyers = fake_buyers
        for i in range(8):  # volume and buys grow as the event nears
            client.tokens = lambda chain, addrs, i=i: [_pair("GTA1", 100 * (i + 1), 5 + i)]
            n, spent, errors = run_watch.snap(self.con, with_wallets=True, now=NOW + i * 3600)
            self.assertEqual((n, errors), (1, {}))
        first = dict(self.con.execute("SELECT * FROM watch_snapshots ORDER BY ts LIMIT 1").fetchone())
        self.assertEqual((first["new_buyers"], first["smart_buyers"], first["bad_buyers"]), (3, 1, 1))
        second = dict(self.con.execute("SELECT * FROM watch_snapshots ORDER BY ts LIMIT 1 OFFSET 1").fetchone())
        self.assertEqual(second["new_buyers"], 1)  # SMART/RUG not counted twice
        self.assertEqual(calls[1], NOW)  # next wallet check starts where the last one ended
        res = run_watch.run_analysis(self.con, now=NOW + 8 * 3600)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["corr_volume"], 1.0)
        self.assertEqual(res[0]["smart_total"], 1)
        self.assertEqual(res[0]["verdict"], "volumen raste prema eventu")  # 1 smart wallet is not enough
        self.assertIn("GTA VI release", run_watch.report(res))

    def test_spearman_and_verdicts(self):
        self.assertEqual(analyze.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertEqual(analyze.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(analyze.spearman([1, 2, 3], [1, 2, 3]))
        self.assertIsNone(analyze.spearman([1, 2, 3, 4], [5, 5, 5, 5]))
        base = {"n": 10, "corr_volume": -0.8, "corr_smart": 0, "corr_buyers": 0, "smart_total": 0, "bad_total": 0}
        self.assertEqual(analyze.verdict(base), "volumen pada (hype je možda već prošao)")
        self.assertEqual(analyze.verdict({**base, "bad_total": 4}), "ulaze loši walleti")
        self.assertEqual(analyze.verdict({**base, "n": 2}), "premalo podataka")


if __name__ == "__main__":
    unittest.main()
