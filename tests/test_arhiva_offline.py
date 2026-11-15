"""ops/arhiva (15.11., Jure: "Makni mikrokapove i rugove i sve njihove povijesne podatke ... one koji su od početka
zadržali volumen, njih zadrži"; "Arhiviraj onda dok ima prostora na disku"): the keep rules (midcap lists, MC >= 2M
now, kept volume, open positions, real money, the owner's trades, the rug archive list), copy -> verify -> gzip ->
verify -> delete (a failed check deletes nothing, a row changed after the copy stays), the disk guard stops the night,
restore round trip, switch off = the plan only, outside the night nothing runs. Synthetic databases, no network."""
import contextlib
import datetime as dt
import glob
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import arhiva  # noqa: E402
from trade import settings  # noqa: E402

Z = ZoneInfo("Europe/Zagreb")
D = 86400
NIGHT = int(dt.datetime(2026, 11, 16, 2, 0, tzinfo=Z).timestamp())
DAY = int(dt.datetime(2026, 11, 16, 12, 0, tzinfo=Z).timestamp())
OLD = NIGHT - 12 * D


def m(name):
    return name.ljust(44, "1")


MICRO, RUG, DEAD, MID, MIDC, REAL, OPEN, VOL, DEXBIG, YOUNG, OWN = (m(x) for x in (
    "MICRO", "RUGG", "DEAD", "MIDLIST", "MIDCAP", "REALMONEY", "OPENPOS", "VOLKEPT", "DEXBIG", "YOUNG", "OWNER"))


def fake_dex(mints):
    now = {MICRO: (150_000, 4_000, 1), DEXBIG: (3_000_000, 900_000, 1), VOL: (600_000, 120_000, 1), DEAD: (0, 0, 0),
           OWN: (90_000, 1_000, 1)}
    return {x: now.get(x, (100_000, 2_000, 1)) for x in mints}


@contextlib.contextmanager
def free_slot(_label):
    yield True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.p = arhiva.paths(self.d)
        self.out = os.path.join(self.d, "output")
        self.logs = []
        self.saved = (arhiva.MIN_FREE_B, arhiva.PAUSE_S, os.environ.get("HEAVY_NIGHT"), os.environ.get("TRADE_OWNER"))
        arhiva.MIN_FREE_B, arhiva.PAUSE_S = 0, 0
        os.environ.pop("HEAVY_NIGHT", None)
        os.environ["TRADE_OWNER"] = "Jure"
        settings._FLAG_CACHE.clear()
        self.tc = settings.connect(self.p["trade"])
        self.tc.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, token TEXT, status TEXT)")
        self.tc.execute("INSERT INTO positions (token, status) VALUES (?, 'closed')", (REAL,))
        self.tc.execute("CREATE TABLE mikrokap_log (token TEXT, ts INTEGER)")   # refused by the gate: no keep
        self.tc.execute("INSERT INTO mikrokap_log VALUES (?, 1)", (MICRO,))
        self.tc.commit()
        self.build()

    def tearDown(self):
        self.tc.close()
        arhiva.MIN_FREE_B, arhiva.PAUSE_S = self.saved[0], self.saved[1]
        for k, v in (("HEAVY_NIGHT", self.saved[2]), ("TRADE_OWNER", self.saved[3])):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings._FLAG_CACHE.clear()
        self.tmp.cleanup()

    def log(self, s):
        self.logs.append(s)

    def db(self, key, script, rows=()):
        con = sqlite3.connect(self.p[key])
        con.executescript(script)
        for sql, args in rows:
            con.executemany(sql, args)
        con.commit()
        con.close()

    def build(self):
        every = (MICRO, RUG, DEAD, MID, MIDC, REAL, OPEN, VOL, DEXBIG, OWN)
        sig = [(OLD + i * 3600, t, 400_000 if t != DEXBIG else 500_000, 0.5 + i, f"f{i}") for t in every for i in range(6)]
        sig += [(NIGHT - 3600, YOUNG, 50_000, 1.0, "y")]
        self.db("hype", """CREATE TABLE hype_signals (ts INTEGER, token TEXT, symbol TEXT, mcap REAL, score REAL,
                               features TEXT, PRIMARY KEY (token, ts));
                           CREATE TABLE rug_archive (token TEXT PRIMARY KEY, kind TEXT);
                           CREATE TABLE rug_recovered (token TEXT PRIMARY KEY);
                           CREATE TABLE live_state (key TEXT PRIMARY KEY, value TEXT);
                           CREATE TABLE kol_mentions (ts INTEGER, handle TEXT, ca TEXT, text TEXT);""",
                [("INSERT INTO hype_signals (ts, token, mcap, score, features) VALUES (?,?,?,?,?)", sig),
                 ("INSERT INTO rug_archive VALUES (?, 'srusen')", [(RUG,)]),
                 ("INSERT INTO kol_mentions VALUES (?, 'h', ?, 'x')", [(OLD, MICRO), (OLD, MID), (OLD, MICRO)])])
        # VOL: 24 h volume >= 50k every day since first seen (24 x mean 1 h volume), MC 600k
        snaps = [(VOL, OLD + k * D + 600, 600_000, 3000.0) for k in range(12)]
        snaps += [(MICRO, OLD + k * D + 600, 150_000, 100.0) for k in range(12)]
        self.db("range", "CREATE TABLE snaps (token TEXT, ts INTEGER, mcap REAL, vol_h1 REAL, PRIMARY KEY (token, ts));",
                [("INSERT INTO snaps VALUES (?,?,?,?)", snaps)])
        self.db("veliki", "CREATE TABLE tokens (mint TEXT PRIMARY KEY, mcap REAL);",
                [("INSERT INTO tokens VALUES (?, 2e7)", [(MID,)])])
        self.db("midcap", "CREATE TABLE tokens (mint TEXT PRIMARY KEY, member INTEGER);",
                [("INSERT INTO tokens VALUES (?, 1)", [(MIDC,)])])
        self.db("league", """CREATE TABLE trades (id INTEGER PRIMARY KEY, user TEXT, token TEXT, status TEXT);""",
                [("INSERT INTO trades (user, token, status) VALUES (?,?,?)",
                  [("jure", OWN, "closed"), ("demo", MICRO, "closed")])])
        self.db("paper", """CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, opened_ts INTEGER,
                               status TEXT);
                            CREATE TABLE reviews (day TEXT PRIMARY KEY, data TEXT);""",
                [("INSERT INTO trades (token, opened_ts, status) VALUES (?,?,?)",
                  [(OPEN, OLD, "open"), (MICRO, OLD, "closed"), (MICRO, OLD + 5, "closed")]),
                 ("INSERT INTO reviews VALUES (?, ?)", [("2026-11-10", "{}")])])
        self.db("wallets", """CREATE TABLE wallet_trades (wallet TEXT, sig TEXT, ts INTEGER, mint TEXT, sol REAL,
                                 PRIMARY KEY (sig, wallet, mint));
                              CREATE TABLE wallets (wallet TEXT PRIMARY KEY, score REAL);""",
                [("INSERT INTO wallet_trades VALUES (?,?,?,?,?)",
                  [("W1", f"s{i}", OLD + i, t, 0.1) for i, t in enumerate((MICRO, MICRO, DEAD, MID, OPEN))]),
                 ("INSERT INTO wallets VALUES ('W1', 1.0)", [()])])
        self.db("tg", """CREATE TABLE posts (channel TEXT, post INTEGER, ts INTEGER, text TEXT, cas TEXT,
                            PRIMARY KEY (channel, post));""",
                [("INSERT INTO posts VALUES (?,?,?,?,?)",
                  [("c", 1, OLD, "micro", MICRO), ("c", 2, OLD, "both", f"{MICRO},{MID}"), ("c", 3, OLD, "none", ""),
                   ("c", 4, OLD, "rug", f"{RUG},{DEAD}")])])
        self.db("rug", """CREATE TABLE rug_reports (mint TEXT, checked_at INTEGER, verdict TEXT,
                             PRIMARY KEY (mint, checked_at));""",
                [("INSERT INTO rug_reports VALUES (?,?,?)",
                  [(RUG, OLD, "ODBAČEN"), (MICRO, OLD, "PROLAZI"), (MICRO, OLD + 1, "VISOK RIZIK")])])

    def on(self):
        settings.set_flag(self.tc, arhiva.SWITCH, "live", "Jure")
        settings._FLAG_CACHE.clear()

    def run_night(self, **kw):
        kw.setdefault("fetch", fake_dex)
        kw.setdefault("slot", free_slot)
        return arhiva.run(self.p, NIGHT, self.log, data_dir=self.d, out_dir=self.out, **kw)

    def rows(self, key, sql, args=()):
        con = sqlite3.connect(self.p[key])
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def tokens(self, key="hype", table="hype_signals", col="token"):
        return {r[0] for r in self.rows(key, f"SELECT DISTINCT {col} FROM {table}")}

    def verdicts(self):
        con = sqlite3.connect(os.path.join(self.d, "archive", "arhiva_stanje.sqlite"))
        try:
            return {mint: (act, why) for mint, act, why in con.execute("SELECT mint, action, why FROM verdict")}
        finally:
            con.close()


class KeepRules(Base):
    def test_verdicts_follow_the_owner_rules(self):
        self.on()
        self.run_night()
        v = self.verdicts()
        for t, why in ((MID, "veliki.db"), (MIDC, "midcap.db"), (REAL, "trade.db"), (OPEN, "otvorena pozicija"),
                       (OWN, "vlasnikovi tradeovi (league)"), (DEXBIG, "MC ≥ 2M sada (DexScreener)"),
                       (VOL, "zadržao volumen od početka")):
            self.assertEqual(v[t], ("zadrži", why), t)
        self.assertEqual(v[YOUNG][0], "zadrži")
        self.assertEqual(v[MICRO], (arhiva.ARCHIVE, "mikrokap (MC < 2M sada)"))
        self.assertEqual(v[RUG], (arhiva.ARCHIVE, "rug"))
        self.assertEqual(v[DEAD], (arhiva.ARCHIVE, "mrtav (nema para na DexScreeneru)"))
        self.assertTrue(any("zadržao volumen od početka" in ln and ": 1 tokena" in ln for ln in self.logs), self.logs)

    def test_rows_move_and_every_kept_thing_stays(self):
        self.on()
        out = self.run_night()
        self.assertIsNone(out["stopped"], self.logs)
        left = self.tokens()
        self.assertFalse({MICRO, RUG, DEAD} & left)
        self.assertTrue({MID, MIDC, REAL, OPEN, VOL, DEXBIG, YOUNG, OWN} <= left)
        self.assertEqual(self.rows("hype", "SELECT token FROM rug_archive"), [(RUG,)])   # the never-buy list stays
        self.assertEqual(sorted(self.rows("rug", "SELECT mint, verdict FROM rug_reports")),
                         sorted([(RUG, "ODBAČEN"), (MICRO, "VISOK RIZIK")]))           # rejections stay
        self.assertEqual(self.rows("paper", "SELECT token, status FROM trades"), [(OPEN, "open")])
        self.assertEqual(self.rows("paper", "SELECT COUNT(*) FROM reviews"), [(1,)])     # no token key: untouched
        self.assertEqual(sorted(r[0] for r in self.rows("tg", "SELECT post FROM posts")), [2, 3])
        self.assertEqual(self.tokens("wallets", "wallet_trades", "mint"), {MID, OPEN})
        self.assertEqual(self.tokens("hype", "kol_mentions", "ca"), {MID})
        gz = glob.glob(os.path.join(self.d, "archive", "hype", "hype_signals_20261116.sqlite.gz"))
        self.assertEqual(len(gz), 1)
        self.assertFalse(glob.glob(os.path.join(self.d, "archive", "*", "*.sqlite")))   # only .gz stay
        self.assertTrue(any(ln.startswith("arhiva: hype.db hype_signals: premješteno 18 redaka (") and "MB gz), ostaje "
                            in ln for ln in self.logs), self.logs)
        self.assertTrue(any(ln.startswith("arhiva: oslobođeno ") and "disk slobodno" in ln for ln in self.logs))
        self.assertTrue(any(ln.startswith("arhiva: plan (prekidač uključen") for ln in self.logs))
        with open(os.path.join(self.out, "arhiva_plan.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("| hype.db | hype_signals | token |", md)
        self.assertIn("| paper.db | reviews | bez ključa tokena |", md)
        self.assertIn("| hype.db | rug_archive | zadržana tablica |", md)
        self.assertEqual(self.run_night(), {})   # once a night


class Mechanics(Base):
    def test_failed_copy_check_deletes_nothing(self):
        self.on()
        before = self.rows("hype", "SELECT COUNT(*) FROM hype_signals")
        self.run_night(verify_hook=lambda stage, path: "simulirano" if stage == "copy" else None)
        self.assertEqual(self.rows("hype", "SELECT COUNT(*) FROM hype_signals"), before)
        self.assertEqual(self.rows("wallets", "SELECT COUNT(*) FROM wallet_trades"), [(5,)])
        self.assertFalse(glob.glob(os.path.join(self.d, "archive", "*", "*.sqlite*")))
        self.assertTrue(any("provjera kopije nije prošla (simulirano), ništa nije obrisano" in ln for ln in self.logs))

    def test_failed_gz_check_deletes_nothing(self):
        self.on()
        self.run_night(verify_hook=lambda stage, path: "simulirano" if stage == "gz" else None)
        self.assertIn(MICRO, self.tokens())
        self.assertFalse(glob.glob(os.path.join(self.d, "archive", "*", "*.sqlite*")))
        self.assertTrue(any("provjera .gz nije prošla" in ln for ln in self.logs))

    def test_row_changed_after_the_copy_stays_live(self):
        self.on()

        def touch(stage, path):
            if stage == "gz" and "hype_signals" in path:
                c = sqlite3.connect(self.p["hype"])
                c.execute("UPDATE hype_signals SET score = 99 WHERE token = ? AND ts = ?", (MICRO, OLD))
                c.commit()
                c.close()
        self.run_night(verify_hook=touch)
        self.assertEqual(self.rows("hype", "SELECT score FROM hype_signals WHERE token = ?", (MICRO,)), [(99.0,)])
        self.assertTrue(any("1 se promijenilo nakon kopije" in ln for ln in self.logs), self.logs)

    def test_disk_guard_stops_the_night(self):
        self.on()
        arhiva.MIN_FREE_B = 1e9
        with mock.patch.object(arhiva, "free_b", return_value=0.4e9):
            out = self.run_night()
        self.assertIn(MICRO, self.tokens())
        self.assertTrue(out["stopped"].startswith("arhiva: stala, premalo prostora (slobodno 0.40 GB"), out["stopped"])
        self.assertIn("arhiva: stala, premalo prostora", "\n".join(self.logs))
        self.assertNotEqual(arhiva.load_state(self.d).get("done"), "2026-11-16")   # the next night goes on
        self.assertFalse(glob.glob(os.path.join(self.d, "archive", "*", "*.sqlite*")))

    def test_restore_round_trip(self):
        self.on()
        orig = sorted(self.rows("hype", "SELECT * FROM hype_signals"))
        orig_paper = sorted(self.rows("paper", "SELECT * FROM trades"))
        self.run_night()
        self.assertNotEqual(sorted(self.rows("hype", "SELECT * FROM hype_signals")), orig)
        ins, skip = arhiva.restore(self.p, "hype", "hype_signals", "20261116", self.log, data_dir=self.d)
        self.assertEqual((ins, skip), (18, 0))
        self.assertEqual(sorted(self.rows("hype", "SELECT * FROM hype_signals")), orig)
        self.assertEqual(arhiva.restore(self.p, "hype", "hype_signals", None, self.log, data_dir=self.d), (0, 18))
        arhiva.restore(self.p, "paper", "trades", None, self.log, data_dir=self.d)
        self.assertEqual(sorted(self.rows("paper", "SELECT * FROM trades")), orig_paper)   # same ids back
        self.assertTrue(glob.glob(os.path.join(self.d, "archive", "hype", "*.gz")))       # the archive stays
        self.assertFalse(glob.glob(os.path.join(self.d, "archive", "hype", "*.vrati")))


class Switch(Base):
    def test_switch_off_is_the_plan_only(self):
        out = self.run_night()
        self.assertTrue(out["dry"])
        self.assertIn(MICRO, self.tokens())
        self.assertFalse(glob.glob(os.path.join(self.d, "archive", "*", "*")))
        self.assertTrue(any(ln.startswith("arhiva: plan (prekidač arhiva_mikrokapova isključen: samo plan") for ln in self.logs))
        with open(os.path.join(self.out, "arhiva_plan.md"), encoding="utf-8") as f:
            self.assertIn("**isključen**", f.read())
        self.assertGreater(out["plan_rows"], 0)
        self.assertEqual(self.run_night(), {})   # the plan once a night ...
        self.on()
        self.assertFalse(self.run_night()["dry"])   # ... a switch turned on later the same night still moves
        self.assertNotIn(MICRO, self.tokens())

    def test_outside_the_night_nothing_runs(self):
        self.on()
        self.assertEqual(arhiva.run(self.p, DAY, self.log, data_dir=self.d, out_dir=self.out, fetch=fake_dex,
                                    slot=free_slot), {})
        self.assertIn(MICRO, self.tokens())
        self.assertEqual(self.logs, [])

    def test_owner_switch_and_his_order_last(self):
        from ui import assistnotes
        self.assertIn(arhiva.SWITCH, settings.OWNER_SWITCHES)
        self.assertIn(arhiva.SWITCH, settings.FLAGS)
        self.assertIn(arhiva.SWITCH, settings.OWNER_SWITCH_NOTES)
        name, mode, why = assistnotes.OWNER_FLAG_ORDERS[-1]
        self.assertEqual((name, mode), (arhiva.SWITCH, "live"))
        self.assertIn("Arhiviraj onda dok ima prostora na disku", why)
        self.assertFalse(arhiva.switch_on(self.p["trade"]))   # never set: off (plan only)
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", assistnotes.OWNER_FLAG_ORDERS[-1:]):
            self.assertEqual(assistnotes.owner_flag_orders(self.tc), [f"zastavica {arhiva.SWITCH}: off → live"])
        settings._FLAG_CACHE.clear()
        self.assertTrue(arhiva.switch_on(self.p["trade"]))

    def test_morning_report_line(self):
        from report import render
        self.on()
        self.run_night()
        s = arhiva.summary(self.d, now=NIGHT + 3600)
        self.assertGreater(s["moved"], 0)
        self.assertIn("Premješteno", render.arhiva_text(s))


if __name__ == "__main__":
    unittest.main()
