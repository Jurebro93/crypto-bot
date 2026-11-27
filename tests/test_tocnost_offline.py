"""Točnost ocjena (tocnost/, ui/tocnost.py) on synthetic databases: counting, the 30-day / tuning window, the
horizon, point-in-time loaders, no lookahead, read-only sources, the page line. No network."""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tocnost import izvori, noc, stat, store  # noqa: E402

DAY, H = 86400, 3600
NOW = 1_798_156_800          # 2026-12-25 00:00 UTC: 20+ days after every tuning date in SPECS


def spec(**kw):
    s = {"buckets": [("da", 1), ("ne", -1), ("x", 0)], "horizon_s": DAY, "since": None}
    s.update(kw)
    return s


def row(subj, ts, b, o, res=None):
    return {"subject": subj, "ts": ts, "bucket": b, "outcome": o, "resolved_ts": res if res is not None else ts + DAY}


def md5(p):
    with open(p, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


class Stat(unittest.TestCase):
    def test_wilson(self):
        lo, hi = stat.wilson(7, 10)
        self.assertTrue(0.4 < lo < 0.7 < hi < 0.9)
        self.assertEqual(stat.wilson(0, 0), (None, None))
        self.assertEqual(stat.wilson(0, 5)[0], 0.0)

    def test_buckets_base_and_direction(self):
        rows = [row(f"a{i}", NOW - 5 * DAY + i, "da", int(i < 7)) for i in range(10)]
        rows += [row(f"b{i}", NOW - 5 * DAY + i, "ne", int(i < 2)) for i in range(10)]
        rows += [row(f"c{i}", NOW - 5 * DAY + i, "x", 1) for i in range(3)]
        a = {r["bucket"]: r for r in stat.aggregate(rows, spec(), NOW)}
        self.assertEqual((a["da"]["n"], a["da"]["k"], a["da"]["correct"]), (10, 7, 7))
        self.assertEqual((a["ne"]["k"], a["ne"]["correct"]), (2, 8))
        self.assertIsNone(a["x"]["correct"])
        self.assertFalse(a["x"]["enough"])           # 3 < MIN_N: premalo podataka
        self.assertTrue(a["da"]["enough"])
        self.assertEqual(a["da"]["base_n"], 23)
        self.assertAlmostEqual(a["da"]["base"], 12 / 23)

    def test_window_since_and_dedup(self):
        rows = [row("a", NOW - 40 * DAY, "da", 1),           # older than 30 days
                row("b", NOW - 10 * DAY, "da", 1),           # before the tuning date
                row("c", NOW - 3 * DAY, "da", 0),
                row("c", NOW - 3 * DAY + 60, "da", 1),       # same subject, same day: the first counts
                row("d", NOW - 3 * DAY, "da", None)]         # unknown outcome: never counted
        a = stat.aggregate(rows, spec(since=NOW - 5 * DAY), NOW)[0]
        self.assertEqual((a["n"], a["k"]), (1, 0))

    def test_no_lookahead_horizon(self):
        """A row whose horizon has not passed, or whose outcome became known only after now, is not counted, even
        when its outcome is already in the row (e.g. an early stop)."""
        rows = [row("early", NOW - 2 * H, "da", 0, res=NOW - H),     # stopped out after 1 h, horizon still open
                row("late", NOW - 2 * DAY, "da", 1, res=NOW + 60),   # resolved in the future
                row("ok", NOW - 2 * DAY, "da", 1)]
        a = stat.aggregate(rows, spec(), NOW)[0]
        self.assertEqual((a["n"], a["k"]), (1, 1))


def hype_db(path, snaps, extra=None):
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL,"
                      " PRIMARY KEY (token, ts));"
                      "CREATE TABLE hype_signals (ts INTEGER, token TEXT, symbol TEXT, name TEXT, pair TEXT, url TEXT,"
                      " score REAL, price REAL, mcap REAL, liquidity REAL, features TEXT, sources TEXT, weights TEXT,"
                      " PRIMARY KEY (token, ts));"
                      "CREATE TABLE prijedlog_log (token TEXT, day TEXT, ts INTEGER, kind TEXT, razina TEXT, mcap0 REAL,"
                      " conf REAL, max24 REAL, r24 REAL, hit INTEGER, stop_first INTEGER, n_snap INTEGER,"
                      " labelled_ts INTEGER, PRIMARY KEY (token, day));"
                      "CREATE TABLE rug_archive (token TEXT PRIMARY KEY, archived_ts INTEGER, kind TEXT);")
    con.executemany("INSERT INTO hype_snapshots VALUES (?,?,0,?,0)", snaps)
    for sql, args in (extra or []):
        con.execute(sql, args)
    con.commit()
    con.close()


class PricePaths(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.h = os.path.join(self.d, "hype.db")

    def con(self):
        return sqlite3.connect(self.h)

    def test_tpsl_order_and_horizon(self):
        t = NOW - 3 * DAY
        # before the score the token had pumped (must not count), after it falls first, then pumps after 24 h
        snaps = [("T", t - 3 * H, 50_000), ("T", t - 10, 100_000), ("T", t + H, 90_000), ("T", t + 2 * H, 70_000),
                 ("T", t + 3 * H, 120_000), ("T", t + 30 * H, 500_000)]
        hype_db(self.h, snaps)
        c = self.con()
        self.assertEqual(izvori.tpsl(c, "T", t, None), 0)      # stop (-30 %) before +20 %; the +400 % is after 24 h
        self.assertEqual(izvori.ref_at(c, "T", t), 100_000)    # newest value at or before t, never a later one
        c.execute("INSERT INTO hype_snapshots VALUES ('T', ?, 0, 1, 0)", (t - 60,))   # data before t: no change
        self.assertEqual(izvori.tpsl(c, "T", t, 100_000), 0)
        c.close()

    def test_ref_never_from_the_future(self):
        t = NOW - 3 * DAY
        hype_db(self.h, [("T", t + 60, 100_000), ("T", t + H, 130_000), ("T", t + 2 * H, 130_000)])
        c = self.con()
        self.assertIsNone(izvori.ref_at(c, "T", t))
        self.assertIsNone(izvori.tpsl(c, "T", t, None))       # no start known at t: unknown, not a hit
        c.close()

    def test_collapse(self):
        t = NOW - 3 * DAY
        hype_db(self.h, [("R", t + H, 80_000), ("R", t + 2 * H, 20_000), ("R", t + 3 * H, 25_000),
                         ("S", t + H, 90_000), ("S", t + 2 * H, 95_000), ("S", t + 3 * H, 99_000)],
                [("INSERT INTO rug_archive VALUES ('Q', ?, 'srusen')", (t + 5 * H,))])
        c = self.con()
        self.assertEqual(izvori.collapsed(c, "R", t, 100_000), 1)
        self.assertEqual(izvori.collapsed(c, "S", t, 100_000), 0)
        self.assertEqual(izvori.collapsed(c, "Q", t, None), 1)
        self.assertEqual(izvori.collapsed(c, "Q", t + 6 * H, None), None)   # archived before that check: not its outcome
        c.close()


class EndToEnd(unittest.TestCase):
    """noc.run on a synthetic set of databases: kartica, pouzdanost, rug, kol (snapshot before the call), midcap;
    the sources stay byte-for-byte the same, and the result at a past `now` ignores everything that came later."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.P = {k: os.path.join(self.d, f"{k}.db") for k in ("hype", "rug", "kol", "wallets", "league", "tocnost")}
        t0 = NOW - 20 * DAY
        snaps, logs = [], []
        for i in range(12):
            ts = t0 + i * DAY
            up = i < 9
            tok = f"K{i}"
            snaps += [(tok, ts - 60, 100_000)] + [(tok, ts + j * H, 100_000 * (1 + (0.05 * j if up else -0.1 * j)))
                                                  for j in range(1, 6)]
            logs.append(("INSERT INTO prijedlog_log (token, day, ts, kind, razina, mcap0, conf) VALUES (?,?,?,?,?,?,?)",
                         (tok, str(i), ts, "zivo", "uživo", 100_000, 70)))
        hype_db(self.P["hype"], snaps, logs)
        con = sqlite3.connect(self.P["rug"])
        con.execute("CREATE TABLE rug_reports (mint TEXT, checked_at INTEGER, symbol TEXT, verdict TEXT, score REAL, "
                    "wash_score REAL, bundle_pct REAL, sniper_pct REAL, cluster_pct REAL, top10_pct REAL, dev TEXT, "
                    "data TEXT, PRIMARY KEY (mint, checked_at))")
        for i in range(12):
            con.execute("INSERT INTO rug_reports (mint, checked_at, verdict, data) VALUES (?,?,?,?)",
                        (f"K{i}", t0 + i * DAY, "PROLAZI", json.dumps({"market": {"mcap": 100_000}})))
        con.commit()
        con.close()
        con = sqlite3.connect(self.P["kol"])
        con.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT, r24h REAL, "
                    "mcap0 REAL, bad TEXT)")
        for i in range(12):
            con.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,NULL)",
                        (str(i), f"C{i}", "Ana", NOW - 15 * DAY + i * H * 3, "call", 0.2 if i < 10 else -0.1, 50_000))
        con.execute("INSERT INTO calls VALUES ('x','CX','Ana',?, 'call', 0.5, 50000, NULL)", (NOW - 15 * DAY - DAY,))
        con.commit()
        con.close()
        store.log_shown("kol", [("ana", "drzi_se", 0.6, None)], NOW - 15 * DAY - H, self.P["tocnost"], src="noc")
        con = sqlite3.connect(self.P["league"])
        con.execute("CREATE TABLE veliki_sjena (id INTEGER PRIMARY KEY, token TEXT, opened_ts INTEGER, profil TEXT, "
                    "band TEXT, grok TEXT, ret REAL, closed_ts INTEGER)")
        for i in range(12):
            ts = NOW - 10 * DAY + i * DAY // 2
            con.execute("INSERT INTO veliki_sjena (token, opened_ts, profil, band, grok, ret, closed_ts) VALUES "
                        "(?,?,?,?,?,?,?)", (f"M{i}", ts, "pravilo", "dno", "kupi", 0.05 if i % 3 else -0.1, ts + 5 * H))
            con.execute("INSERT INTO veliki_sjena (token, opened_ts, profil, band, grok, ret, closed_ts) VALUES "
                        "(?,?,?,?,?,?,?)", (f"M{i}", ts, "skalp", "dno", "kupi", -0.5, ts + H))   # other profile
        con.commit()
        con.close()
        self.before = {k: md5(p) for k, p in self.P.items() if k != "tocnost" and os.path.exists(p)}

    def latest(self):
        store.clear_cache()
        return store.latest(self.P["tocnost"], ttl=0)

    def test_run(self):
        logs = []
        noc.run(NOW, self.P, log=logs.append, snapshot=False)
        r = self.latest()
        k = r[("kartica", "kupi")]
        self.assertEqual((k["n"], k["k"], k["correct"]), (12, 9, 9))
        self.assertEqual(r[("pouzdanost", "visoka")]["n"], 12)
        rug = r[("rug", "PROLAZI")]
        self.assertEqual((rug["n"], rug["k"], rug["correct"]), (12, 0, 12))
        kol = r[("kol", "drzi_se")]
        self.assertEqual((kol["n"], kol["k"]), (12, 10))       # the call before the snapshot is not judged by it
        g = r[("midcap_grok", "kupi")]
        self.assertEqual((g["n"], g["k"]), (12, 8))            # profile pravilo only
        self.assertEqual({k: md5(p) for k, p in self.P.items() if k in self.before}, self.before)   # read-only

    def test_no_lookahead_past_now(self):
        """Measured at a past moment, the result equals the one on databases cut at that moment: nothing that came
        later (price points, calls, outcomes) leaks into it."""
        past = NOW - 8 * DAY
        full = {}
        for key in ("kartica", "rug", "kol"):
            full[key] = noc.measure(key, izvori.paths(self.P), past)[0]
        cut = {k: os.path.join(self.d, f"cut_{k}.db") for k in self.P}
        for k, p in self.P.items():
            src, dst = sqlite3.connect(p), sqlite3.connect(cut[k])
            src.backup(dst)
            src.close()
            for tbl, col in (("hype_snapshots", "ts"), ("prijedlog_log", "ts"), ("rug_reports", "checked_at"),
                             ("calls", "ts"), ("prikaz", "ts")):
                try:
                    dst.execute(f"DELETE FROM {tbl} WHERE {col} > ?", (past,))
                except sqlite3.Error:
                    pass
            try:   # an outcome known only after `past` must not exist yet either
                dst.execute("UPDATE calls SET r24h = NULL WHERE ts + 86400 > ?", (past,))
            except sqlite3.Error:
                pass
            dst.commit()
            dst.close()
        for key in full:
            got = noc.measure(key, izvori.paths(cut), past)[0]
            strip = lambda a: [{k: v for k, v in x.items()} for x in a]   # noqa: E731
            self.assertEqual(strip(got), strip(full[key]), key)
        self.assertGreater(sum(a["n"] for a in full["kartica"]), 0)

    def test_dokazani_entries(self):
        con = sqlite3.connect(self.P["wallets"])
        con.executescript("CREATE TABLE dokazani (wallet TEXT, as_of INTEGER, closed_before INTEGER, realized_before REAL,"
                          " win_before REAL, closed_after INTEGER, realized_after REAL, win_after REAL, passed INTEGER);"
                          "CREATE TABLE wallet_trades (wallet TEXT, sig TEXT, ts INTEGER, mint TEXT, tokens REAL, sol REAL,"
                          " kind TEXT);")
        a = NOW - 20 * DAY
        con.execute("INSERT INTO dokazani (wallet, as_of, passed) VALUES ('W', ?, 1)", (a,))
        con.execute("INSERT INTO dokazani (wallet, as_of, passed) VALUES ('V', ?, 0)", (a,))
        tr = [("W", a + H, "M1", -1.0, "buy"), ("W", a + 2 * H, "M1", 1.5, "sell"),             # +0.5 in a week
              ("W", a + 3 * H, "M2", -1.0, "buy"), ("W", a + 10 * DAY, "M2", 5.0, "sell"),      # sold after the week
              ("V", a + H, "M3", -1.0, "buy"), ("V", a + 2 * H, "M3", 0.4, "sell"),
              ("W", a - H, "M4", -1.0, "buy"), ("W", a + H, "M4", 3.0, "sell")]                # bought before the run
        con.executemany("INSERT INTO wallet_trades (wallet, ts, mint, sol, kind) VALUES (?,?,?,?,?)", tr)
        con.commit()
        con.close()
        rows = izvori.load_dokazani(izvori.paths(self.P), NOW - 30 * DAY, NOW)
        got = sorted((r["subject"], r["bucket"], r["outcome"]) for r in rows)
        self.assertEqual(got, [("V:M3", "nije dokazan", 0), ("W:M1", "dokazan", 1), ("W:M2", "dokazan", 0)])


class Shown(unittest.TestCase):
    def test_first_view_of_the_day_wins(self):
        p = os.path.join(tempfile.mkdtemp(), "t.db")
        store.log_shown("pouzdanost", [("A", "visoka", 70, 1.0)], NOW, p)
        store.log_shown("pouzdanost", [("A", "niska", 10, 2.0)], NOW + 60, p)
        con = sqlite3.connect(p)
        self.assertEqual(con.execute("SELECT bucket, value FROM prikaz").fetchall(), [("visoka", 70.0)])
        con.close()
        self.assertEqual(store.log_shown("x", [("A", "b", 1, 1)], NOW, "/nonexistent/dir/t.db"), 0)   # never raises

    def test_line_text(self):
        from ui import tocnost as T
        base = {"n": 10, "k": 7, "correct": 7, "acc_lo": 0.45, "acc_hi": 0.87, "lo": 0.45, "hi": 0.87, "base": 0.4,
                "enough": 1}
        t, tip = T.text("kartica", "kupi", base)
        self.assertEqual(t, "pogodila 7 od 10 zadnjih 30 dana (n=10)")
        self.assertNotIn("%", tip)
        self.assertNotIn("15", tip)                     # no threshold in user text
        t, _ = T.text("kartica", "kupi", {**base, "n": 4, "enough": 0})
        self.assertEqual(t, "premalo podataka za točnost (n=4)")
        t, _ = T.text("midcap_zona", "dno", {**base, "correct": None})
        self.assertTrue(t.startswith("7 od 10 ulaza u plusu"))
        self.assertIn("se još mjeri", T.text("rug", "OPREZ", None)[0])
        self.assertEqual(T.line("rug", None), "")

    def test_specs_cover_loaders(self):
        self.assertEqual(set(izvori.SPECS), set(izvori.LOADERS))
        for k, s in izvori.SPECS.items():
            self.assertIn(s["oos"], ("pit", "rule"), k)
            self.assertLessEqual(s["since"], NOW - 25 * DAY, k)


if __name__ == "__main__":
    unittest.main()
