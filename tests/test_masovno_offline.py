"""5.11.: the mass shadow book (learn/masovno.py): points from the token filter, candles within a budget, exit
variants, history at night, stats against kontrola.

    python3 -m unittest tests.test_masovno_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import masovno  # noqa: E402

NOW = 1_800_000_000
WBTC = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"


def _dbs(tmp, now):
    hype = os.path.join(tmp, "hype.db")
    h = sqlite3.connect(hype)
    h.executescript("""CREATE TABLE live_launches (mint TEXT PRIMARY KEY, ts INTEGER, creator TEXT, name TEXT, symbol TEXT, initial_sol REAL, sig TEXT, pool TEXT);
                       CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, PRIMARY KEY (sig, mint));
                       CREATE TABLE hype_signals (ts INTEGER, token TEXT, symbol TEXT, score REAL, price REAL, mcap REAL, liquidity REAL, features TEXT);""")
    h.execute("INSERT INTO live_launches VALUES ('BOND', ?, 'd', 'Bond', 'BND', 1, 's', 'migration')", (now - 30 * 3600,))
    h.execute("INSERT INTO live_launches VALUES ('NEWONLY', ?, 'd', 'New', 'NEW', 1, 's2', 'pump')", (now - 30 * 3600,))
    h.execute("INSERT INTO chain_trades VALUES ('t1', 'W1', 'WBUY', 'buy', ?, 1.0)", (now - 29 * 3600,))
    h.execute("INSERT INTO chain_trades VALUES ('t2', 'W1', ?, 'buy', ?, 1.0)", (WBTC, now - 29 * 3600))
    for i in range(3):
        h.execute("INSERT INTO hype_signals VALUES (?, ?, ?, 50, 1.0, 60000, 20000, '{}')", (now - 28 * 3600, f"SCAN{i}", f"S{i}"))
    h.execute("INSERT INTO hype_signals VALUES (?, 'SMALL', 'SM', 50, 1.0, 9000, 2000, '{}')", (now - 28 * 3600,))
    h.commit(); h.close()
    from kol import store as kstore
    kol = os.path.join(tmp, "kol.db")
    k = kstore.connect(kol)
    k.execute("INSERT INTO kols (handle, bot) VALUES ('alice', 0)")
    k.execute("INSERT INTO kols (handle, bot) VALUES ('scanbot', 1)")
    k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, symbol) VALUES ('1', 'CALLED', 'alice', ?, 'call', 'C')", (now - 27 * 3600,))
    k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, symbol) VALUES ('2', 'BOTCALL', 'scanbot', ?, 'call', 'B')", (now - 27 * 3600,))
    k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, symbol) VALUES ('3', 'OLDCALL', 'alice', ?, 'call', 'O')", (now - 20 * 86400,))
    k.execute("INSERT INTO tokens (token, pair, liquidity) VALUES ('BOND', 'POOLB', 25000)")
    k.commit(); k.close()
    return hype, kol


def _candles(up=True):
    def fetch(pool, start, end):
        out, px = [], 1.0
        for i in range(0, int(end - start), 300):
            px = px * (1.02 if up else 0.97) if i else px
            t = int(start) + i
            out.append((t, px, px * 1.01, px * 0.99, px, 1000.0))
        return out
    return fetch


class Collect(unittest.TestCase):
    def test_filter_sources_and_night(self):
        tmp = tempfile.mkdtemp()
        hype, kol = _dbs(tmp, NOW)
        con = masovno.connect(os.path.join(tmp, "shadow.db"))
        with mock.patch.object(masovno, "_followed", return_value=["W1"]):
            new = masovno.collect(con, NOW, hype_db=hype, kol_db=kol)
        self.assertEqual(new, {"bondao": 1, "novcanik_kupio": 1, "kontrola": 3, "kol_poziv": 1})   # no pump launch, no WBTC, no bot, no SMALL
        self.assertEqual(masovno.collect(con, NOW, hype_db=hype, kol_db=kol), {})                   # idempotent
        self.assertEqual(masovno.history(con, NOW, kol_db=kol, wallets_db=os.path.join(tmp, "none.db")), 1)   # OLDCALL
        pts = {r[0]: r[1] for r in con.execute("SELECT token, point FROM points")}
        self.assertEqual(pts["OLDCALL"], "povijest_poziv")
        self.assertNotIn("NEWONLY", pts)
        self.assertNotIn(WBTC, pts)
        con.close()
        # the night window is Europe/Zagreb 01-06
        import datetime as dt, zoneinfo
        z = zoneinfo.ZoneInfo("Europe/Zagreb")
        self.assertTrue(masovno.is_night(dt.datetime(2026, 11, 6, 2, 30, tzinfo=z).timestamp()))
        self.assertFalse(masovno.is_night(dt.datetime(2026, 11, 6, 12, 0, tzinfo=z).timestamp()))


class Label(unittest.TestCase):
    def test_candles_budget_variants_and_stats(self):
        tmp = tempfile.mkdtemp()
        hype, kol = _dbs(tmp, NOW)
        con = masovno.connect(os.path.join(tmp, "shadow.db"))
        with mock.patch.object(masovno, "_followed", return_value=["W1"]):
            masovno.collect(con, NOW, hype_db=hype, kol_db=kol)
        pool_for = lambda tok: ("POOL" + tok, 20000.0)
        done, used = masovno.label(con, NOW, budget=4, fetch=_candles(up=True), pool_for=pool_for)
        self.assertEqual((done, used), (2, 4))                                          # 2 calls per token
        done2, used2 = masovno.label(con, NOW, budget=100, fetch=_candles(up=False), pool_for=pool_for)
        self.assertEqual(done2, 4)
        rows = con.execute("SELECT point, ret, varijante, status, price FROM points WHERE status='gotovo'").fetchall()
        self.assertEqual(len(rows), 6)
        for point, ret, var, st, price in rows:
            v = json.loads(var)
            self.assertEqual(set(v), set(masovno.VARIANTS))
            self.assertEqual(price, 1.0)
        ups = [json.loads(v)["sat"] for p, r, v, s, px in rows if r > 0]
        self.assertTrue(ups and all(x > 0 for x in ups))
        st = {s["point"]: s for s in masovno.stats(os.path.join(tmp, "shadow.db"), now=NOW)}
        self.assertIn("kontrola", st)
        self.assertEqual(sum(s["n"] for s in st.values()), 6)
        html = masovno.stats_html(os.path.join(tmp, "shadow.db"), now=NOW)
        self.assertIn("vs kontrola", html)
        self.assertIn("Nevidljivi tradeovi", html)
        # a token without a pool: no price, one call, never a winner by accident
        con.execute("INSERT INTO points (id, token, point, ts, status) VALUES ('kol_poziv:NOPOOL:x', 'NOPOOL', 'kol_poziv', ?, 'ceka')", (NOW - 2 * 86400,))
        con.commit()
        d3, u3 = masovno.label(con, NOW, budget=10, fetch=_candles(), pool_for=lambda t: (None, None))
        self.assertEqual((d3, u3), (0, 1))
        self.assertEqual(con.execute("SELECT status FROM points WHERE token='NOPOOL'").fetchone()[0], "bez_cijene")
        con.close()


if __name__ == "__main__":
    unittest.main()
