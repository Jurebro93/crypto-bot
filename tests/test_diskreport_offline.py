"""ops/diskreport (11.11., Jure: "NIŠTA ne briši bez moje potvrde"): sizes, growth, candidates, KEEP, runway alarm,
when it runs, and that it changes no database file."""
import datetime as dt
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import diskreport as dr  # noqa: E402

NOW = 1794400000          # 2026-11-11 ~ 15:00 Zagreb
D = 86400


def zagreb(y, m, d, h, mi=0):
    return int(dt.datetime(y, m, d, h, mi, tzinfo=ZoneInfo("Europe/Zagreb")).timestamp())


def fixture(d, now=NOW):
    """hype.db (WAL): hype_signals (ts index, raw), chain_trades (append log without index, raw, 14 d), hype_snapshots
    (KEEP); events.db: events in ms with gaps in rowid; wallets.db: wallet_trades filled back in time (KEEP);
    kol.db: tg-like ISO time text; paper.db with free pages; a cache folder."""
    h = sqlite3.connect(os.path.join(d, "hype.db"))
    h.execute("PRAGMA journal_mode=WAL")
    h.execute("CREATE TABLE hype_signals (ts INTEGER, token TEXT, features TEXT, PRIMARY KEY (token, ts))")
    h.execute("CREATE INDEX hype_signals_cover ON hype_signals (ts, token)")
    h.execute("CREATE TABLE chain_trades (ts INTEGER, wallet TEXT, sig TEXT)")
    h.execute("CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, PRIMARY KEY (token, ts))")
    sig = [(int(now - 40 * D + i * 40 * D / 60000), f"T{i % 700}", "f" * 150) for i in range(60000)]
    h.executemany("INSERT INTO hype_signals VALUES (?,?,?)", sig)
    h.executemany("INSERT INTO chain_trades VALUES (?,?,?)", [(ts, "w", "s" * 88) for ts, _, _ in sig])
    h.executemany("INSERT INTO hype_snapshots VALUES (?,?,?)", [(t, ts, 1.0) for ts, t, _ in sig[:8000]])
    h.commit()
    h.close()
    e = sqlite3.connect(os.path.join(d, "events.db"))
    e.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts INTEGER, type TEXT, data TEXT)")
    e.execute("CREATE INDEX events_type_ts ON events (type, ts)")
    e.executemany("INSERT INTO events (ts, type, data) VALUES (?,?,?)",
                  [(int((now - 20 * D + i * 20 * D / 80000) * 1000), "price_tick", "y" * 60) for i in range(80000)])
    e.execute("DELETE FROM events WHERE id % 3 = 0")
    e.commit()
    e.close()
    w = sqlite3.connect(os.path.join(d, "wallets.db"))
    w.execute("CREATE TABLE wallet_trades (wallet TEXT, ts INTEGER, sig TEXT)")
    rows = []
    for k in range(60):   # each wallet's history fetched at once, back in time: rowid does not follow ts
        rows += [(f"W{k}", int(now - (j % 30) * D - k * 600), "t" * 40) for j in range(1000)]
    w.executemany("INSERT INTO wallet_trades VALUES (?,?,?)", rows)
    w.commit()
    w.close()
    k = sqlite3.connect(os.path.join(d, "kol.db"))
    k.execute("CREATE TABLE seen_cache (time TEXT, post TEXT)")
    k.executemany("INSERT INTO seen_cache VALUES (?,?)",
                  [(dt.datetime.fromtimestamp(now - i * 3600, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "p" * 30)
                   for i in range(24 * 40)])
    k.commit()
    k.close()
    p = sqlite3.connect(os.path.join(d, "paper.db"))
    p.execute("CREATE TABLE ticks (ts INTEGER, token TEXT, price REAL, pad TEXT)")
    p.executemany("INSERT INTO ticks VALUES (?,?,?,?)", [(int(now - 20 * D + i * 10), "A", 1.0, "z" * 400)
                                                         for i in range(20000)])
    p.commit()
    p.execute("DELETE FROM ticks WHERE ts < ?", (int(now - 10 * D),))   # free pages: what VACUUM would give back
    p.commit()
    p.close()
    os.makedirs(os.path.join(d, "cache"))
    with open(os.path.join(d, "cache", "x.json"), "w") as f:
        f.write("c" * 6_000_000)
    os.makedirs(os.path.join(d, "learned"))
    with open(os.path.join(d, "learned", "w.json"), "w") as f:
        f.write("{}")


def fingerprint(d):
    out = {}
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[n] = (hashlib.sha256(f.read()).hexdigest(), os.stat(p).st_mtime_ns)
    return out


class Env(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = cls.tmp.name
        fixture(cls.d)
        cls.before = fingerprint(cls.d)
        cls.rep = dr.build(cls.d, NOW, extra_dirs=[])
        cls.after = fingerprint(cls.d)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def table(self, db, name):
        for x in self.rep["dbs"]:
            if x["name"] == db:
                for t in x["tables"]:
                    if t["table"] == name:
                        return t
        self.fail(f"{db}.{name} nije u izvještaju")

    def db(self, name):
        return next(x for x in self.rep["dbs"] if x["name"] == name)


class Sizes(Env):
    def test_files_tables_and_folders(self):
        h = self.db("hype.db")
        self.assertEqual(h["file_b"], os.path.getsize(os.path.join(self.d, "hype.db")))
        self.assertIsNotNone(h["page_size"])
        total = sum(t["bytes"] for t in h["tables"])
        self.assertLessEqual(total, h["file_b"])
        self.assertGreater(total, 0.8 * h["file_b"])                       # tables + their indexes (dbstat)
        self.assertGreater(self.table("hype.db", "hype_signals")["bytes"], self.table("hype.db", "chain_trades")["bytes"])
        self.assertEqual(self.table("hype.db", "hype_signals")["rows"], 60000)
        dirs = {x["path"]: x["b"] for x in self.rep["dirs"]}
        self.assertEqual(dirs["cache/"], 6_000_000)
        self.assertIn("learned/", dirs)
        self.assertGreater(self.db("paper.db")["free_b"], 1e6)            # the deleted ticks: free pages

    def test_no_dbstat_falls_back_to_a_sample(self):
        g = dr.Guard(30, 10)
        real = dr.Guard.q

        def no_dbstat(self_, con, sql, args=(), limit_s=None):
            if "dbstat" in sql:
                raise sqlite3.OperationalError("no such table: dbstat")
            return real(self_, con, sql, args, limit_s)
        with mock.patch.object(dr.Guard, "q", no_dbstat):
            r = dr.db_report(os.path.join(self.d, "hype.db"), g, NOW)
        self.assertIn("bez dbstat", r["note"])
        t = next(t for t in r["tables"] if t["table"] == "hype_signals")
        self.assertTrue(t["est"])
        real_b = self.table("hype.db", "hype_signals")["bytes"]
        self.assertTrue(0.4 * real_b < t["bytes"] < 2.5 * real_b, (t["bytes"], real_b))


class Growth(Env):
    def test_indexed_counts_are_exact(self):
        t = self.table("hype.db", "hype_signals")
        self.assertEqual((t["ts_col"], t["unit"], t["est"]), ("ts", "s", False))
        self.assertEqual(t["n24"], 1500)                                    # 60000 rows over 40 days
        self.assertEqual(t["n7"], 10500)
        self.assertAlmostEqual(t["oldest_ts"], NOW - 40 * D, delta=1)
        per = t["bytes"] / t["rows"]
        self.assertAlmostEqual(t["growth_b_day"], 1500 * per, delta=per)
        self.assertAlmostEqual(t["old_b"][30], 15000 * per, delta=2 * per)

    def test_append_log_without_index_is_bisected(self):
        t = self.table("hype.db", "chain_trades")
        self.assertTrue(t["est"])
        self.assertAlmostEqual(t["n24"], 1500, delta=30)
        self.assertAlmostEqual(t["n7"], 10500, delta=60)
        ev = self.table("events.db", "events")                             # ms, a third of the rowids deleted
        self.assertEqual(ev["unit"], "ms")
        self.assertAlmostEqual(ev["n7"], 80000 * 7 / 20 * 2 / 3, delta=500)

    def test_history_filled_back_in_time_is_scanned_not_bisected(self):
        t = self.table("wallets.db", "wallet_trades")
        self.assertFalse(t["est"])
        c = sqlite3.connect(os.path.join(self.d, "wallets.db"))
        want = c.execute("SELECT COUNT(*) FROM wallet_trades WHERE ts >= ?", (NOW - 7 * D,)).fetchone()[0]
        c.close()
        self.assertEqual(t["n7"], want)

    def test_iso_text_time(self):
        t = self.table("kol.db", "seen_cache")
        self.assertEqual(t["unit"], "iso")
        self.assertAlmostEqual(t["n24"], 25, delta=1)
        self.assertAlmostEqual(t["n7"], 24 * 7 + 1, delta=1)

    def test_net_growth_and_runway_from_the_state(self):
        rep = dict(self.rep, used_b=3_140_000_000, free_b=2_070_000_000, total_b=5_210_000_000)
        st = {"hist": [{"ts": NOW - 2 * D, "used_b": 2_940_000_000}, {"ts": NOW - 3600, "used_b": 3_139_000_000}]}
        g = dr.growth(rep, st, NOW)
        self.assertAlmostEqual(g["net_mb_day"], 100.0, places=1)         # the run >= 20 h back, not the one an hour ago
        self.assertAlmostEqual(g["runway_days"], 20.7, places=1)
        self.assertIn("neto", g["basis"])
        g = dr.growth(rep, {}, NOW)                                       # no earlier run: the rows' inflow
        self.assertEqual(g["used_mb_day"], g["inflow_mb_day"])
        self.assertIn("priljev", g["basis"])


class Candidates(Env):
    def test_only_raw_tables_from_their_safe_age(self):
        c = self.rep["candidates"]
        rows = {(x["db"], x["table"]): x for x in c if x["what"] == "redovi"}
        self.assertEqual(rows[("hype.db", "chain_trades")]["days"], 14)  # its readers: never under 14 days
        self.assertEqual(rows[("hype.db", "hype_signals")]["days"], 7)
        self.assertIn("PRVI red po tokenu", rows[("hype.db", "hype_signals")]["note"])
        self.assertNotIn(("hype.db", "hype_snapshots"), rows)             # KEEP
        self.assertNotIn(("wallets.db", "wallet_trades"), rows)           # KEEP
        self.assertEqual([x["b"] for x in c], sorted((x["b"] for x in c), reverse=True))
        self.assertTrue(any(x["what"] == "cache" and x["path"] == "cache/" for x in c))
        self.assertTrue(any(x["what"] == "vacuum" and x["db"] == "paper.db" for x in c))
        t = self.table("hype.db", "chain_trades")
        per = t["bytes"] / t["rows"]
        self.assertAlmostEqual(rows[("hype.db", "chain_trades")]["b"], 26 * 1500 * per, delta=60 * per)

    def test_keep_marking(self):
        self.assertIn("learn/outcomes", self.table("hype.db", "hype_snapshots")["keep"])
        self.assertIn("ocjene i dokaze", self.table("wallets.db", "wallet_trades")["keep"])
        self.assertIsNone(self.table("hype.db", "chain_trades")["keep"])
        self.assertEqual(dr.classify("trade.db", "orders")[0], "keep")      # real money: the whole file
        self.assertEqual(dr.classify("x.db", "foo", {"foo": ["learn/shadow", "ui/x"]})[0], "keep")
        self.assertIn("learn/shadow", dr.classify("x.db", "foo", {"foo": ["learn/shadow"]})[1])
        self.assertEqual(dr.classify("x.db", "call_outcomes_v2", {})[0], "keep")   # by name
        k = dr.classify("x.db", "raw_feed", {"raw_feed": ["ui/radar"]})
        self.assertEqual((k[0], k[2]), ("raw", dr.MIN_DAYS_DEFAULT))
        self.assertIn("ui/radar", k[1])
        rd = dr.readers()                                                  # the real grep of this repo
        self.assertIn("learn/shadow", rd.get("points", []))
        for db, tables in dr.KEEP.items():
            for name, why in tables.items():
                self.assertGreater(len(why), 10, name)
                self.assertNotIn("—", why)

    def test_log_block(self):
        ls = dr.lines(self.rep)
        self.assertTrue(all(x.startswith("disk izvještaj") for x in ls))
        self.assertIn("samo mjerenje, ništa nije obrisano", ls[0])
        txt = "\n".join(ls)
        self.assertIn("top 15 tablica", txt)
        self.assertIn("kandidati za čišćenje", txt)
        self.assertIn("hype.db chain_trades: redovi stariji od 14 d", txt)
        self.assertIn("KEEP: ishodi cijena za učenje", txt)
        self.assertLessEqual(sum(1 for x in ls if ". " in x[:22]), dr.TOP + dr.TOP_CAND)


class ReadOnly(Env):
    def test_no_database_file_changes(self):
        for n, fp in self.before.items():
            self.assertEqual(self.after[n], fp, n)                        # bytes and mtime of every file
        for n in set(self.after) - set(self.before):                      # SQLite's empty -wal/-shm of a WAL file
            self.assertRegex(n, r"\.db-(wal|shm)$")
            if n.endswith("-wal"):
                self.assertEqual(os.path.getsize(os.path.join(self.d, n)), 0)
        for name in ("hype.db", "wallets.db"):
            c = sqlite3.connect(os.path.join(self.d, name))
            self.assertGreater(c.execute("SELECT COUNT(*) FROM " + ("hype_signals" if name == "hype.db" else
                                                                     "wallet_trades")).fetchone()[0], 50000)
            c.close()

    def test_run_writes_only_its_state(self):
        with tempfile.TemporaryDirectory() as d:
            fixture(d)
            before = fingerprint(d)
            logs = []
            rep = dr.run(d, NOW, logs.append, reason="ručno", commit="abc", extra_dirs=[])
            after = fingerprint(d)
            new = set(after) - set(before)
            self.assertIn(dr.STATE, new)
            self.assertFalse({n for n in new if not n.endswith(("-wal", "-shm"))} - {dr.STATE})
            for n in before:
                self.assertEqual(after[n], before[n], n)
            st = dr.load_state(d)
            self.assertEqual((st["commit"], st["hist"][-1]["used_b"]), ("abc", rep["used_b"]))
            self.assertTrue(logs[0].startswith("disk izvještaj (samo mjerenje"))

    def test_locked_table_is_skipped_others_measured(self):
        with tempfile.TemporaryDirectory() as d:
            fixture(d)
            lock = sqlite3.connect(os.path.join(d, "paper.db"), isolation_level=None)
            lock.execute("BEGIN EXCLUSIVE")                                # rollback journal: readers wait, then give up
            try:
                with mock.patch.object(dr, "BUSY_MS", 50):
                    rep = dr.build(d, NOW, extra_dirs=[])
            finally:
                lock.execute("ROLLBACK")
                lock.close()
            p = next(x for x in rep["dbs"] if x["name"] == "paper.db")
            self.assertIn("paper.db", rep["skipped"])
            self.assertIn("locked", p["note"])
            self.assertTrue(next(x for x in rep["dbs"] if x["name"] == "hype.db")["tables"])

    def test_budget_bounds_the_run(self):
        rep = dr.build(self.d, NOW, extra_dirs=[], budget_s=0)
        self.assertTrue(all(x.get("note") == "vrijeme izvještaja isteklo" for x in rep["dbs"]))
        self.assertTrue(dr.lines(rep))


class WhenAndAlarm(unittest.TestCase):
    def test_due_after_deploy_daily_and_never_at_night(self):
        self.assertEqual(dr.due({}, zagreb(2026, 11, 11, 10), "c1"), "deploy")
        self.assertEqual(dr.due({"commit": "c0", "daily": "2026-11-11"}, zagreb(2026, 11, 11, 10), "c1"), "deploy")
        self.assertIsNone(dr.due({}, zagreb(2026, 11, 11, 3), "c1"))                    # 01-06: heavy window
        st = {"commit": "c1", "daily": "2026-11-10"}
        self.assertIsNone(dr.due(st, zagreb(2026, 11, 11, 6, 20), "c1"))
        self.assertEqual(dr.due(st, zagreb(2026, 11, 11, 6, 35), "c1"), "dnevno")
        self.assertIsNone(dr.due({"commit": "c1", "daily": "2026-11-11"}, zagreb(2026, 11, 11, 12), "c1"))

    def test_deploy_after_0630_counts_as_the_daily(self):
        with tempfile.TemporaryDirectory() as d:
            rep = {"ts": zagreb(2026, 11, 11, 9), "used_b": 1, "total_b": 10, "free_b": 9, "dbs": [], "candidates": []}
            st = dr.save_state(rep, {}, d, "c1", "deploy")
            self.assertEqual(st["daily"], "2026-11-11")
            self.assertIsNone(dr.due(dr.load_state(d), zagreb(2026, 11, 11, 10), "c1"))
            rep["ts"] = zagreb(2026, 11, 12, 0, 30)
            self.assertEqual(dr.save_state(rep, {}, d, "c2", "deploy")["daily"], None)

    def test_alarm_on_80_percent_or_three_days(self):
        self.assertEqual(dr.alarm({"total_b": 100, "used_b": 70, "growth": {"runway_days": 10}}), [])
        self.assertIn("81%", dr.alarm({"total_b": 100, "used_b": 81, "growth": {}})[0])
        self.assertIn("2.5 dana", dr.alarm({"total_b": 100, "used_b": 50, "growth": {"runway_days": 2.5}})[0])

    def test_brief_part(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("još nije radio", dr.brief_part(NOW, d)["note"])
            rep = {"ts": NOW, "used_b": 3_140_000_000, "total_b": 5_210_000_000, "free_b": 2_070_000_000, "dbs": [],
                   "growth": {"used_mb_day": 900.0, "basis": "neto"}, "alarm": [],
                   "candidates": [{"what": "redovi", "db": "hype.db", "table": "chain_trades", "days": 14, "b": 4e8}]}
            dr.save_state(rep, {}, d, "c1", "deploy")
            u = {"total_b": 5_210_000_000, "used_b": 3_140_000_000, "free_b": 2_070_000_000}
            with mock.patch.object(dr, "disk_usage", lambda _d: u):
                b = dr.brief_part(NOW, d)
            self.assertEqual((b["runway_days"], b["alarm"]), (2.3, True))     # 2070 MB / 900 MB a day
            self.assertEqual(b["alerts"][0]["type"], "disk")
            self.assertEqual(b["top_candidates"][0]["mb"], 400.0)
            with mock.patch.object(dr, "disk_usage", lambda _d: {**u, "used_b": 4_300_000_000, "free_b": 900_000_000}):
                self.assertIn("83%", dr.brief_part(NOW, d)["alerts"][0]["title"])

    def test_brief_health_carries_the_disk(self):
        from events import brief
        with tempfile.TemporaryDirectory() as d, mock.patch.object(dr.disk, "DATA_DIR", d), \
                mock.patch.object(dr, "disk_usage", lambda _d: {"total_b": 100, "used_b": 90, "free_b": 10}):
            h = brief.health_part(None, NOW)
        self.assertTrue(h["disk"]["alarm"])
        self.assertTrue(any(a.get("type") == "disk" for a in h["alerts"]))


if __name__ == "__main__":
    unittest.main()
