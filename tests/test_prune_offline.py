"""Unused data goes, usable data stays (ops/prune.py, 8.11.2026), and the sources stop producing the junk in the first
place: no 'w:' pseudo-calls, no GeckoTerminal measuring of swaps and bot posts, no bot wallets in the webhook."""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import chainwatch, collect, measure, store as kstore  # noqa: E402
from ops import prune  # noqa: E402
from wallets import store as wstore  # noqa: E402

NOW = 1_800_000_000
D = 86400


def _kol_db(tmp):
    con = kstore.connect(os.path.join(tmp, "kol.db"))
    con.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind, source) VALUES (?,?,?,?,?,?)", [
        ("s1", "T1", "w:abc123", NOW - 10 * D, "buy", "chain"),     # old pseudo-call: goes
        ("s2", "T1", "w:abc123", NOW - 1 * D, "buy", "chain"),      # recent pseudo-call: stays (W_KEEP_DAYS)
        ("s3", "T2", "ansem", NOW - 10 * D, "buy", "chain"),        # known KOL wallet buy: stays
        ("t1", "T3", "oldguy", NOW - 40 * D, "call", "backfill"),   # inactive, never measured: goes with the account
        ("t2", "T4", "active", NOW - 2 * D, "call", "kol_timeline"),
        ("t3", "T5", "oldstar", NOW - 40 * D, "call", "backfill"),  # inactive but measured: stays
    ])
    con.executemany("INSERT INTO kols (handle, last_seen, stats) VALUES (?,?,?)", [
        ("oldguy", NOW - 40 * D, json.dumps({"measured": 0, "calls": 1})),
        ("active", NOW - 2 * D, json.dumps({"measured": 0})),
        ("oldstar", NOW - 40 * D, json.dumps({"measured": 7})),
        ("tg:oldchan", NOW - 40 * D, None),
    ])
    con.commit()
    con.close()
    return os.path.join(tmp, "kol.db")


def _wallet_db(tmp):
    path = os.path.join(tmp, "wallets.db")
    con = wstore.connect(path)
    rows = [  # wallet, first_seen, last_seen, tier, stats
        ("LOSER_D", NOW - 40 * D, NOW - 1 * D, "D", {"closed": 12, "realized_sol": -3.0, "trades_per_day": 400}),
        ("LOSER_C", NOW - 40 * D, NOW - 1 * D, "C", {"closed": 15, "realized_sol": -0.5}),
        ("SLEEPER", NOW - 60 * D, NOW - 35 * D, "C", {"closed": 2, "realized_sol": 0.1}),
        ("WINNER", NOW - 60 * D, NOW - 35 * D, "B", {"closed": 9, "realized_sol": 4.2}),
        ("YOUNG", NOW - 3 * D, NOW - 1 * D, "C", {"closed": 11, "realized_sol": -1.0}),
    ]
    for w, fs, ls, tier, st in rows:
        con.execute("INSERT INTO wallets (wallet, first_seen, last_seen, scored_at, next_check, tier, stats, labels) "
                    "VALUES (?,?,?,?,?,?,?,'[]')", (w, fs, ls, NOW - D, NOW + D, tier, json.dumps(st)))
        con.executemany("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)",
                        [(w, f"{w}-{i}", NOW - 5 * D + i, "MINT", 1.0, 0.1, "buy") for i in range(4)])
    con.execute("INSERT INTO wallets (wallet, first_seen, last_seen) VALUES ('UNSCORED', ?, ?)", (NOW - 40 * D, NOW - 40 * D))
    con.commit()
    con.close()
    return path


def _hype_db(tmp):
    path = os.path.join(tmp, "hype.db")
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL, PRIMARY KEY (sig, mint));
        CREATE TABLE chain_transfers (sig TEXT, src TEXT, dst TEXT, mint TEXT, amount REAL, ts INTEGER, PRIMARY KEY (sig, src, dst, mint));
        CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL, PRIMARY KEY (token, ts));
        CREATE TABLE hype_details (token TEXT, ts INTEGER, extra TEXT, PRIMARY KEY (token, ts));
        CREATE TABLE token_status (token TEXT PRIMARY KEY, has_pair INTEGER, pair_url TEXT, dex_id TEXT, price REAL,
            mcap REAL, liq REAL, gt_price REAL, gt_fdv REAL, gt_vol24 REAL, checked_ts INTEGER, gt_checked_ts INTEGER);
    """)
    con.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)",
                    [("a", "W", "M", "buy", NOW - 20 * D, 1.0), ("b", "W", "M", "buy", NOW - 2 * D, 1.0)])
    con.execute("INSERT INTO chain_transfers VALUES ('c', 'A', 'B', 'M', 1.0, ?)", (NOW - 20 * D,))
    for tok, ts in (("DEAD", NOW - 20 * D), ("DEAD", NOW - 1 * D), ("ALIVE", NOW - 20 * D)):
        con.execute("INSERT INTO hype_snapshots VALUES (?,?,1,1,1)", (tok, ts))
        con.execute("INSERT INTO hype_details VALUES (?,?,'{}')", (tok, ts))
    con.execute("INSERT INTO token_status (token, has_pair) VALUES ('DEAD', 0)")
    con.execute("INSERT INTO token_status (token, has_pair) VALUES ('ALIVE', 1)")
    con.commit()
    con.close()
    return path


def _paper_db(tmp):
    path = os.path.join(tmp, "paper.db")
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE ticks (token TEXT, ts INTEGER, price REAL, liquidity REAL, mcap REAL, PRIMARY KEY (token, ts));
                         CREATE TABLE trades (token TEXT, status TEXT);""")
    con.execute("INSERT INTO trades VALUES ('TRADED', 'closed')")
    con.executemany("INSERT INTO ticks VALUES (?,?,1,1,1)", [("TRADED", NOW - 10 * D), ("NEVER", NOW - 10 * D),
                                                              ("NEVER", NOW - 1 * D)])
    con.commit()
    con.close()
    return path


class Dry(unittest.TestCase):
    def test_default_counts_without_deleting(self):
        tmp = tempfile.mkdtemp()
        path = _kol_db(tmp)
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "dry"}):
            self.assertFalse(prune.on())
            out = prune.kol(path, NOW)
        self.assertEqual(out, {"w_pozivi": 1, "minutne": 0, "neaktivni_x": 1, "neaktivni_x_pozivi": 1})
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 6)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM kols").fetchone()[0], 4)

    def test_run_all_logs_one_line(self):
        tmp = tempfile.mkdtemp()
        _kol_db(tmp); _wallet_db(tmp); _hype_db(tmp); _paper_db(tmp)
        lines = []
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "dry"}):
            out = prune.run_all(NOW, data_dir=tmp, log=lines.append)
        self.assertEqual(out["w_pozivi"], 1)
        self.assertEqual(out["gubitnici"], 3)
        self.assertEqual(out["chain"], 2)
        self.assertEqual(out["mrtvi_tokeni"], 2)
        self.assertEqual(out["tikovi"], 1)
        self.assertTrue(lines[0].startswith("čišćenje (suho brojanje"), lines)
        self.assertIn("w_pozivi 1", lines[0])

    def test_count_only_never_deletes_even_when_on(self):
        tmp = tempfile.mkdtemp()
        path = _kol_db(tmp)
        lines = []
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "on"}):
            out = prune.run_all(NOW, data_dir=tmp, log=lines.append, count_only=True)
            self.assertTrue(prune.on())   # the environment is back as it was
        self.assertEqual(out["w_pozivi"], 1)
        self.assertTrue(lines[0].startswith("čišćenje (brojanje pri startu"), lines)
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 6)


class Kol(unittest.TestCase):
    def test_on_deletes_pseudo_calls_and_inactive_accounts(self):
        tmp = tempfile.mkdtemp()
        path = _kol_db(tmp)
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "on"}):
            out = prune.kol(path, NOW)
        self.assertEqual(out, {"w_pozivi": 1, "minutne": 0, "neaktivni_x": 1, "neaktivni_x_pozivi": 1})
        con = sqlite3.connect(path)
        left = {r[0] for r in con.execute("SELECT tweet_id FROM calls")}
        self.assertEqual(left, {"s2", "s3", "t2", "t3"})
        kols = {r[0] for r in con.execute("SELECT handle FROM kols")}
        self.assertEqual(kols, {"active", "oldstar", "tg:oldchan"})   # Telegram channels are not touched here


class Wallets(unittest.TestCase):
    def test_losers_lose_their_trades_and_leave_the_queue(self):
        tmp = tempfile.mkdtemp()
        path = _wallet_db(tmp)
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "on"}):
            out = prune.wallets(path, NOW)
        self.assertEqual(out, {"gubitnici": 3, "gubitnici_tradeovi": 12})
        con = wstore.connect(path)
        left = {r[0] for r in con.execute("SELECT DISTINCT wallet FROM wallet_trades")}
        self.assertEqual(left, {"WINNER", "YOUNG"})   # profitable and young keep everything
        row = con.execute("SELECT labels, next_check, last_tx_ts, history_from FROM wallets WHERE wallet='LOSER_D'").fetchone()
        self.assertIn("izbačen", json.loads(row[0]))
        self.assertEqual(row[1:], (None, None, None))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM wallets").fetchone()[0], 6)   # summary rows stay
        # the scoring queue never spends Helius credits on them again, even after a new sighting
        wstore.observe(con, "LOSER_C", "TOK", "hype_learn", "early_buyer", NOW)
        con.commit()
        queued = {w for w, _ in wstore.queue(con, 50, NOW + 10)}
        self.assertNotIn("LOSER_C", queued)
        # a second pass finds nothing new
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "on"}):
            self.assertEqual(prune.wallets(path, NOW)["gubitnici"], 0)


class Hype(unittest.TestCase):
    def test_chain_and_dead_tokens(self):
        tmp = tempfile.mkdtemp()
        path = _hype_db(tmp)
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "on"}):
            out = prune.hype(path, NOW)
        self.assertEqual(out, {"chain": 2, "mrtvi_tokeni": 2})
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT sig FROM chain_trades").fetchall(), [("b",)])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM chain_transfers").fetchone()[0], 0)
        snaps = con.execute("SELECT token, ts FROM hype_snapshots ORDER BY token, ts").fetchall()
        self.assertEqual(snaps, [("ALIVE", NOW - 20 * D), ("DEAD", NOW - 1 * D)])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM hype_details").fetchone()[0], 2)


class Paper(unittest.TestCase):
    def test_untraded_ticks(self):
        tmp = tempfile.mkdtemp()
        path = _paper_db(tmp)
        with mock.patch.dict(os.environ, {"DATA_PRUNE": "on"}):
            self.assertEqual(prune.paper(path, NOW), {"tikovi": 1})
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("SELECT token, ts FROM ticks ORDER BY token").fetchall(),
                         [("NEVER", NOW - 1 * D), ("TRADED", NOW - 10 * D)])


class Growth(unittest.TestCase):
    def test_fast_growing_table_is_named(self):
        tmp = tempfile.mkdtemp()
        path = _paper_db(tmp)
        state = os.path.join(tmp, ".rows.json")
        self.assertEqual(prune.growth(tmp, NOW, state), [])            # first run: nothing to compare with
        con = sqlite3.connect(path)
        con.executemany("INSERT INTO ticks VALUES (?,?,1,1,1)", [("X", NOW + i) for i in range(50)])
        con.commit(); con.close()
        with mock.patch.object(prune, "GROWTH_WARN", 40):
            warn = prune.growth(tmp, NOW + 3600, state)
        self.assertEqual([(k, n) for k, n, _ in warn], [("paper.db.ticks", 53)])
        self.assertEqual(warn[0][2], 50)


class Sources(unittest.TestCase):
    """The junk is no longer produced."""

    def test_from_chain_skips_unknown_wallets(self):
        tmp = tempfile.mkdtemp()
        kcon = kstore.connect(os.path.join(tmp, "kol.db"))
        from kol import idents
        idents.save(kcon, [{"wallet": "KOLWALLET", "name": "Ansem", "twitter": "blknoiz06", "telegram": None, "pnl": 1,
                            "wins": 1, "losses": 0, "rank": 1},
                           {"wallet": "ANONWALLET", "name": "anon", "twitter": None, "telegram": None, "pnl": 1,
                            "wins": 1, "losses": 0, "rank": 2}], "kolscan")
        hype = os.path.join(tmp, "hype.db")
        hc = sqlite3.connect(hype)
        hc.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL)")
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", [
            ("s1", "KOLWALLET", "M1", "buy", NOW, 1.0), ("s2", "ANONWALLET", "M2", "buy", NOW + 1, 1.0),
            ("s3", "UNKNOWN", "M3", "sell", NOW + 2, None)])
        hc.commit(); hc.close()
        n = collect.from_chain(kcon, hype)
        self.assertEqual(n, 1)
        self.assertEqual(kcon.execute("SELECT handle, kind FROM calls").fetchall(), [("blknoiz06", "buy")])
        # the cursor still moved past the skipped rows
        self.assertEqual(kcon.execute("SELECT ts FROM seen_cache WHERE key='chain:trades'").fetchone()[0], NOW + 2)

    def test_due_skips_swaps_and_bot_posts(self):
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        con.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,?)", [
            ("1", "SWAP", "w:abc", 1000, "buy"), ("2", "KOLBUY", "ansem", 1000, "buy"), ("3", "BOT", "scanner", 1000, "bot"),
            ("4", "CALL", "ansem", 1000, "call"), ("5", "TG", "tg:chan", 1000, "call")])
        self.assertEqual(sorted(measure.due(con, 100000, 10)), ["CALL", "TG"])

    def test_busy_wallets_leave_the_webhook(self):
        tmp = tempfile.mkdtemp()
        wpath = _wallet_db(tmp)   # LOSER_D trades 400 times a day
        wcon = wstore.connect(wpath)
        wcon.execute("UPDATE wallets SET labels='[\"bundler\"]' WHERE wallet='SLEEPER'")
        wcon.commit(); wcon.close()
        self.assertEqual(chainwatch.too_busy(["LOSER_D", "SLEEPER", "WINNER", "NEW"], wpath), {"LOSER_D", "SLEEPER"})
        self.assertEqual(chainwatch.too_busy(["LOSER_D"], os.path.join(tmp, "none.db")), set())
        kcon = kstore.connect(os.path.join(tmp, "kol.db"))
        from kol import idents
        idents.save(kcon, [{"wallet": w, "name": w, "twitter": None, "telegram": None, "pnl": 1, "wins": 1, "losses": 0,
                            "rank": i} for i, w in enumerate(["LOSER_D", "WINNER", "SLEEPER", "NEW"])], "kolscan")
        got = chainwatch.wanted(kcon, {"max_wallets": 10}, wallet_db=wpath)
        self.assertEqual(got, ["WINNER", "NEW"])


if __name__ == "__main__":
    unittest.main()
