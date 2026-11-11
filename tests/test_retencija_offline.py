"""ops/retencija (11.11., Jure: "ništa se stvarno ne briše bez moje potvrde nakon što vidim brojke"): the hourly
aggregate of live_trades is exact and built once, our swaps and the followed / scored wallets are never deleted, the
measurement (dry run) deletes nothing, only the owner's switch turns the deletion on (and only at night), and a
Telegram post whose calls are not fully measured keeps its text."""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kol import store as kstore  # noqa: E402
from live import store as lstore  # noqa: E402
from ops import cpuguard, heavy, retencija as rt  # noqa: E402
from tg import store as tstore  # noqa: E402
from trade import settings  # noqa: E402

Z = ZoneInfo("Europe/Zagreb")
H, D = 3600, 86400
NIGHT = int(dt.datetime(2026, 11, 12, 3, 0, tzinfo=Z).timestamp())    # inside the 01-06 window
DAY = int(dt.datetime(2026, 11, 12, 10, 0, tzinfo=Z).timestamp())     # after 06:30, outside the window
OLD = NIGHT - 3 * D            # older than 48 h
T0 = NIGHT - 5 * D             # a shill-network call 5 days ago (kol/preshill reads T0 - 6 h .. T0 + 24 h)
ENV = ("SOLANA_PUBLIC_KEY", "SOLANA_PRIVATE_KEY", "RENDER_GIT_COMMIT", "RETENCIJA_PRESHILL_DAYS", "HEAVY_NIGHT")


def trade(sig, mint, wallet, ts, side="buy", sol=1.0, px=0.001, mcap=30.0):
    return (sig, mint, wallet, side, sol, (sol / px) if px else 0.0, px, mcap, "pump", ts, None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.env = {k: os.environ.get(k) for k in ENV}
        for k in ENV:
            os.environ.pop(k, None)
        self.lock, heavy.LOCK = heavy.LOCK, os.path.join(d, "heavy.lock")
        self.pause, rt.PAUSE_S = rt.PAUSE_S, 0
        settings._FLAG_CACHE.clear()
        self.p = rt.paths(d)
        self.logs = []
        self.hc = lstore.connect(self.p["hype"])
        self.tc = settings.connect(self.p["trade"])
        self.tc.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, ts INTEGER, token TEXT, side TEXT, signature TEXT)")
        self.tc.execute("INSERT INTO orders (ts, token, side, signature) VALUES (?, 'MINTA', 'buy', 'OURSIG')", (OLD,))
        self.tc.commit()
        settings.put(self.tc, "wallet_pub", "OURWALLET")           # the address saved on /pravi-trade

    def tearDown(self):
        self.hc.close()
        self.tc.close()
        heavy.LOCK, rt.PAUSE_S = self.lock, self.pause
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings._FLAG_CACHE.clear()
        self.tmp.cleanup()

    def log(self, s):
        self.logs.append(s)

    def add(self, rows):
        lstore.add_trades(self.hc, rows)
        self.hc.commit()

    def switch(self, name, mode="live"):
        settings.set_flag(self.tc, name, mode, "Jure", now=NIGHT)

    def followed(self):
        """One wallet per kind of source the deletion must keep (KEEP_WALLET_SOURCES) and one stripped loser."""
        k = kstore.connect(self.p["kol"])
        k.execute("INSERT INTO kv VALUES ('chain_hook', ?)", (json.dumps({"wallets": ["HOOKED"], "ts": OLD}),))
        k.commit()
        k.close()
        lg = sqlite3.connect(self.p["league"])
        lg.execute("CREATE TABLE follows (id INTEGER PRIMARY KEY, user TEXT, kind TEXT, target TEXT, active INTEGER)")
        lg.execute("INSERT INTO follows (user, kind, target, active) VALUES ('pravi-trade', 'wallet', 'COPIED', 0)")
        lg.commit()
        lg.close()
        w = sqlite3.connect(self.p["wallets"])
        w.execute("CREATE TABLE wallets (wallet TEXT PRIMARY KEY, scored_at INTEGER, labels TEXT)")
        w.executemany("INSERT INTO wallets VALUES (?,?,?)", [("SCORED", OLD, "[]"), ("LOSER", OLD, '["izbačen"]'),
                                                             ("QUEUED", None, "[]")])
        w.execute("CREATE TABLE dokazani (wallet TEXT, as_of INTEGER, passed INTEGER)")
        w.execute("INSERT INTO dokazani VALUES ('PROVEN', ?, 1)", (OLD,))
        w.commit()
        w.close()
        e = sqlite3.connect(self.p["early"])
        e.execute("CREATE TABLE group_member (member TEXT, kind TEXT, gid TEXT, PRIMARY KEY (member, kind))")
        e.execute("INSERT INTO group_member VALUES ('CREW', 'wallet', 'g1'), ('somecaller', 'caller', 'g2')")
        e.execute("CREATE TABLE preshill_tokens (token TEXT PRIMARY KEY, t0 INTEGER, window_start INTEGER)")
        e.execute("INSERT INTO preshill_tokens VALUES ('SHILL', ?, ?)", (T0, T0 - 6 * H))
        e.commit()
        e.close()


class HourlyAggregate(Base):
    def test_counts_sol_wallets_and_ohlc_per_mint_and_hour_built_once(self):
        h0 = OLD - OLD % H
        self.add([trade("a1", "MINTA", "W1", h0 + 10, "buy", 1.0, 0.001, 30.0),
                  trade("a2", "MINTA", "W2", h0 + 20, "sell", 0.5, 0.002, 60.0),
                  trade("a3", "MINTA", "W1", h0 + 30, "buy", 2.0, None, None),        # no price: out of OHLC
                  trade("a4", "MINTA", "W3", h0 + 3000, "buy", 0.25, 0.0015, 45.0),
                  trade("b1", "MINTB", "W9", h0 + H + 5, "sell", 3.0, 0.01, 100.0),
                  trade("c1", "MINTA", "W1", NIGHT - 600, "buy", 1.0, 0.003, 90.0)])   # the hour is not over yet
        hours, rows = rt.build_hourly(self.p["hype"], NIGHT)
        self.assertGreaterEqual(hours, 2)
        self.assertEqual(rows, 2)
        got = {r[0]: r[1:] for r in self.hc.execute(
            "SELECT mint || '@' || (hour - ?), buys, sells, buy_sol, sell_sol, wallets, open_px, high_px, low_px, "
            "close_px, last_mcap_sol, trades FROM live_trades_hourly", (h0,))}
        self.assertEqual(set(got), {"MINTA@0", f"MINTB@{H}"})
        a = got["MINTA@0"]
        self.assertEqual(a[:2], (3, 1))
        self.assertAlmostEqual(a[2], 3.25)
        self.assertAlmostEqual(a[3], 0.5)
        self.assertEqual(a[4], 3)                                   # W1, W2, W3
        self.assertEqual(a[5:9], (0.001, 0.002, 0.001, 0.0015))     # open, high, low, close
        self.assertEqual(a[9:], (45.0, 4))                          # last mcap_sol, trades
        b = got[f"MINTB@{H}"]
        self.assertEqual((b[0], b[1], b[4], b[5], b[8], b[9]), (0, 1, 1, 0.01, 0.01, 100.0))
        upto = int(self.hc.execute("SELECT value FROM live_state WHERE key = 'hourly_upto'").fetchone()[0])
        self.assertLessEqual(upto, NIGHT - rt.LATE_S)
        # built once: rows deleted (or arriving late) in an aggregated hour never change it
        self.hc.execute("DELETE FROM live_trades WHERE sig IN ('a1', 'a2')")
        self.add([trade("a5", "MINTA", "W7", h0 + 40, "buy", 9.0, 0.5, 1.0)])
        self.assertEqual(rt.build_hourly(self.p["hype"], NIGHT + 60), (0, 0))
        again = self.hc.execute("SELECT buys, sells, wallets, high_px FROM live_trades_hourly WHERE mint = 'MINTA' "
                                "AND hour = ?", (h0,)).fetchone()
        self.assertEqual(again, (3, 1, 3, 0.002))
        # the marker lost: the aggregate's newest hour still bounds a rebuild from below
        self.hc.execute("DELETE FROM live_state WHERE key = 'hourly_upto'")
        self.hc.commit()
        rt.build_hourly(self.p["hype"], NIGHT + 120)
        self.assertEqual(self.hc.execute("SELECT buys FROM live_trades_hourly WHERE mint = 'MINTA' AND hour = ?",
                                         (h0,)).fetchone(), (3,))


class NeverDeleted(Base):
    def rows(self):
        os.environ["SOLANA_PUBLIC_KEY"] = "ENVWALLET"
        self.followed()
        self.add([trade("s1", "MINTA", "OURWALLET", OLD), trade("OURSIG", "MINTA", "SOMEBODY", OLD + 1),
                  trade("s3", "MINTA", "ENVWALLET", OLD + 2), trade("s4", "MINTA", "HOOKED", OLD + 3),
                  trade("s5", "MINTA", "COPIED", OLD + 4), trade("s6", "MINTA", "SCORED", OLD + 5),
                  trade("s7", "MINTA", "PROVEN", OLD + 6), trade("s8", "MINTA", "CREW", OLD + 7),
                  trade("s9", "SHILL", "NOBODY", T0 - 3 * H),         # inside the shill window: a long reader
                  trade("g1", "SHILL", "NOBODY", T0 - 7 * H),         # before the window
                  trade("g2", "MINTA", "LOSER", OLD + 8), trade("g3", "MINTA", "QUEUED", OLD + 9),
                  trade("g4", "MINTA", "STRANGER", OLD + 10), trade("g5", "MINTB", None, OLD + 11),
                  trade("n1", "MINTA", "STRANGER", NIGHT - 3 * H)])   # younger than 48 h
        return {"s1", "OURSIG", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "n1"}

    def test_our_swaps_followed_scored_and_long_reader_rows_stay(self):
        keep = self.rows()
        out = rt.delete_live(self.p, NIGHT, self.log, stop=lambda: False)
        self.assertEqual({r[0] for r in self.hc.execute("SELECT sig FROM live_trades")}, keep)
        self.assertEqual(out["gone"], 5)
        self.assertIn("retencija live_trades (brisanje): obrisano 5 redova", self.logs[-1])
        # the aggregate was built before: every deleted row's hour is in it
        for ts in (T0 - 7 * H, OLD + 8):
            self.assertTrue(self.hc.execute("SELECT 1 FROM live_trades_hourly WHERE hour = ?", (ts - ts % H,)).fetchone())
        # nothing else is touched: trade.db orders and the settings stay
        self.assertEqual(self.tc.execute("SELECT signature FROM orders").fetchall(), [("OURSIG",)])

    def test_the_measurement_counts_the_same_rows_and_deletes_nothing(self):
        keep = self.rows()
        m = rt.measure_live(self.p, NIGHT)
        self.assertEqual((m["old"], m["ours"], m["wallets"], m["readers"], m["gone"]), (14, 3, 5, 1, 5))
        self.assertGreater(m["gone_b"], 0)
        lines = rt.live_lines(m)
        self.assertRegex(lines[0], r"^retencija live_trades \(samo mjerenje\): redova stariji od 48 h 14 \(\S+ MB\), od "
                                   r"toga ostaje \(praćeni novčanici / naši swapovi\) 9 .*obrisalo bi 5 redova ≈ \S+ MB; "
                                   r"satni agregat 0 redova ≈ \S+ MB$")
        self.assertIn("praćeni (Helius webhook) 1", lines[1])
        self.assertIn("kupci prije shill mreže 1", lines[1])
        self.assertEqual(self.hc.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0], len(keep) + 5)


class Telegram(Base):
    def post(self, con, post, ts, text, cas="", tickers=""):
        con.execute("INSERT INTO posts VALUES ('kanal', ?, ?, ?, ?, ?, ?, 0, NULL, 'web')", (post, ts, ts, text, cas, tickers))

    def setUp(self):
        super().setUp()
        old, new = NIGHT - 20 * D, NIGHT - 2 * D
        tg = tstore.connect(self.p["tg"])
        self.post(tg, 1, old, "CA MINT1 ide", "MINT1")          # call measured on every field the tables have
        self.post(tg, 2, old, "$ABC na mjesec", "", "ABC")       # tickers only: no call
        self.post(tg, 3, old, "CA MINT3", "MINT3")               # a CA but no call row
        self.post(tg, 4, new, "svjež tekst", "", "XYZ")          # younger than 14 days
        self.post(tg, 5, old, "CA MINT5", "MINT5")               # call without r1h
        tg.commit()
        tg.close()
        k = kstore.connect(self.p["kol"])
        for post, mint, r1h in ((1, "MINT1", 0.2), (5, "MINT5", None)):
            k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, mcap0, r1h, r6h, r24h, max24) "
                      "VALUES (?, ?, 'tg:kanal', ?, 'call', 50000, ?, 0.1, -0.3, 0.5)",
                      (f"tg:kanal/{post}", mint, old, r1h))
        k.commit()
        k.close()
        e = sqlite3.connect(self.p["events"])
        e.execute("CREATE TABLE call_outcomes (uid INTEGER PRIMARY KEY, mint TEXT, tweet_id TEXT, ts INTEGER, "
                  "change_4h REAL, change_24h REAL)")
        e.execute("INSERT INTO call_outcomes (mint, tweet_id, ts, change_4h, change_24h) VALUES "
                  "('MINT1', 'tg:kanal/1', ?, 0.05, -0.3), ('MINT5', 'tg:kanal/5', ?, 0.01, -0.2)", (old, old))
        e.commit()
        e.close()

    def texts(self):
        con = sqlite3.connect(self.p["tg"])
        try:
            return dict(con.execute("SELECT post, text FROM posts ORDER BY post"))
        finally:
            con.close()

    def test_measurement_names_the_missing_fields_and_counts(self):
        m = rt.measure_tg(self.p, NIGHT)
        self.assertEqual((m["old"], m["done"], m["nocall"], m["waiting"]), (4, 0, 2, 2))
        self.assertEqual(m["missing"], ["r15m", "vrh 72h"])
        self.assertEqual(m["done_have"], 1)                     # post 1 would be done if r15m / 72-h peak existed
        self.assertEqual(m["bytes"], len("$ABC na mjesec".encode()) + len("CA MINT3".encode()))
        line = rt.tg_lines(m)[0]
        self.assertTrue(line.startswith("tg tekst (samo mjerenje): objava starijih od 14 d 4, s potpunim mjerenjima 0, "
                                        "bez poziva 2, čeka mjerenja 2; tekst bi se obrisao za 2 objava ≈ "), line)
        self.assertIn("(nakon VACUUM-a)", line)
        self.assertIn("u bazi nema polja: r15m, vrh 72h", line)

    def test_incompletely_measured_posts_keep_their_text_rows_stay(self):
        out = rt.delete_tg(self.p, NIGHT, self.log, stop=lambda: False, compact=False)
        self.assertEqual(out["done"], 2)
        t = self.texts()
        self.assertEqual(len(t), 5)                              # never a DELETE of a row
        self.assertIsNone(t[2])
        self.assertIsNone(t[3])
        self.assertEqual((t[1], t[4], t[5]), ("CA MINT1 ide", "svjež tekst", "CA MINT5"))
        # the two fields added and measured: post 1 is complete, post 5 still misses r1h
        k = sqlite3.connect(self.p["kol"])
        k.execute("ALTER TABLE calls ADD COLUMN r15m REAL")
        k.execute("ALTER TABLE calls ADD COLUMN max72h REAL")
        k.execute("UPDATE calls SET r15m = 0.03, max72h = 0.9")
        k.commit()
        k.close()
        m = rt.measure_tg(self.p, NIGHT)
        self.assertEqual((m["old"], m["done"], m["nocall"], m["waiting"], m["missing"]), (2, 1, 0, 1, []))
        rt.delete_tg(self.p, NIGHT, self.log, stop=lambda: False, compact=False)
        t = self.texts()
        self.assertIsNone(t[1])
        self.assertEqual((t[4], t[5]), ("svjež tekst", "CA MINT5"))
        self.assertIn("tg tekst (brisanje): tekst obrisan za 1 objava", self.logs[-1])

    def test_without_kol_db_a_post_with_a_ca_waits(self):
        os.remove(self.p["kol"])
        m = rt.measure_tg(self.p, NIGHT)
        self.assertEqual((m["done"], m["nocall"], m["waiting"]), (0, 1, 3))


class Switches(Base):
    def fill(self):
        self.followed()
        self.add([trade("k1", "MINTA", "HOOKED", OLD), trade("x1", "MINTA", "STRANGER", OLD + 1),
                  trade("x2", "MINTA", "STRANGER", OLD + 2)])
        tg = tstore.connect(self.p["tg"])
        tg.execute("INSERT INTO posts VALUES ('kanal', 1, ?, ?, '$ABC', '', 'ABC', 0, NULL, 'web')", (OLD - 20 * D,) * 2)
        tg.commit()
        tg.close()

    def count(self):
        return self.hc.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0]

    def tg_text(self):
        con = sqlite3.connect(self.p["tg"])
        try:
            return con.execute("SELECT text FROM posts").fetchone()[0]
        finally:
            con.close()

    def test_dry_run_deletes_nothing_even_at_night(self):
        self.fill()
        before = os.path.getsize(self.p["hype"])
        out = rt.run_auto(self.p, NIGHT, self.log, data_dir=self.tmp.name, commit="abc")
        self.assertEqual(out["night"], {})
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.tg_text(), "$ABC")
        self.assertGreater(os.path.getsize(self.p["hype"]), 0)
        self.assertTrue(before)
        self.assertFalse([s for s in self.logs if "mjerenje (" in s])   # never measured inside the night window
        out = rt.run_auto(self.p, DAY, self.log, data_dir=self.tmp.name, commit="abc")
        joined = "\n".join(self.logs)
        self.assertIn("retencija: mjerenje (prvi prolaz nakon deploya)", joined)
        self.assertIn("retencija live_trades (samo mjerenje): redova stariji od 48 h 3", joined)
        self.assertIn("obrisalo bi 2 redova", joined)
        self.assertIn("tg tekst (samo mjerenje): objava starijih od 14 d 1", joined)
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.tg_text(), "$ABC")
        self.logs.clear()
        rt.run_auto(self.p, DAY + 600, self.log, data_dir=self.tmp.name, commit="abc")   # once a day
        self.assertFalse([s for s in self.logs if "samo mjerenje" in s])
        rt.run_auto(self.p, DAY + D, self.log, data_dir=self.tmp.name, commit="abc")
        self.assertIn("retencija: mjerenje (dnevno od 06:30)", self.logs)

    def test_the_owner_switch_turns_the_deletion_on_only_at_night_once(self):
        self.fill()
        self.switch(rt.SWITCH_LIVE)
        rt.run_auto(self.p, DAY, self.log, data_dir=self.tmp.name, commit="abc")
        self.assertEqual(self.count(), 3)                            # by day: measured, not deleted
        self.assertIn("retencija live_trades (prekidač uključen, briše noću 01-06)", "\n".join(self.logs))
        out = rt.run_auto(self.p, NIGHT + D, self.log, data_dir=self.tmp.name, commit="abc")
        self.assertEqual(out["night"]["live"]["gone"], 2)
        self.assertEqual([r[0] for r in self.hc.execute("SELECT sig FROM live_trades")], ["k1"])
        self.assertEqual(self.tg_text(), "$ABC")                     # its own switch is still off
        out = rt.run_auto(self.p, NIGHT + D + H, self.log, data_dir=self.tmp.name, commit="abc")
        self.assertEqual(out["night"], {})                           # once a night
        self.switch(rt.SWITCH_TG)
        out = rt.run_auto(self.p, NIGHT + D + 2 * H, self.log, data_dir=self.tmp.name, commit="abc")
        self.assertEqual(out["night"]["tg"]["done"], 1)
        self.assertIsNone(self.tg_text())
        self.switch(rt.SWITCH_LIVE, "shadow")                       # any mode but live is off again
        self.add([trade("x3", "MINTA", "STRANGER", NIGHT)])
        out = rt.run_auto(self.p, NIGHT + 4 * D, self.log, data_dir=self.tmp.name, commit="abc")
        self.assertNotIn("live", out["night"])
        self.assertEqual(self.count(), 2)

    def test_a_busy_heavy_lock_postpones_the_deletion(self):
        self.fill()
        self.switch(rt.SWITCH_LIVE)
        rt.HEAVY_WAIT_S, wait = 0, rt.HEAVY_WAIT_S
        try:
            with heavy.slot(wait=0) as got:
                self.assertTrue(got)
                import subprocess
                code = ("import sys; sys.path.insert(0, %r); from ops import heavy, retencija as rt; heavy.LOCK = %r; "
                        "rt.HEAVY_WAIT_S = 0; print(rt.night(rt.paths(%r), %d, print, {}))"
                        % (ROOT, heavy.LOCK, self.tmp.name, NIGHT))
                env = dict(os.environ, TRADE_DB=self.p["trade"])
                res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
                self.assertIn("brava teških poslova zauzeta", res.stdout, res.stderr)
        finally:
            rt.HEAVY_WAIT_S = wait
        self.assertEqual(self.count(), 3)


class OldDeletesAndWiring(Base):
    def test_the_feed_and_the_tg_loop_no_longer_delete(self):
        self.add([trade("o1", "MINTA", "STRANGER", OLD)])
        lstore.prune(self.hc, NIGHT)
        self.assertEqual(self.count_live(), 1)
        tg = tstore.connect(self.p["tg"])
        tg.execute("INSERT INTO posts VALUES ('kanal', 1, ?, ?, 'tekst', '', '', 0, NULL, 'web')", (OLD - 60 * D,) * 2)
        self.assertEqual(tstore.prune(tg, 30, NIGHT), 0)
        self.assertEqual(tg.execute("SELECT COUNT(*), MAX(text) FROM posts").fetchone(), (1, "tekst"))
        tg.close()
        with open(os.path.join(ROOT, "tg", "config.json"), encoding="utf-8") as f:
            self.assertNotIn("prune_days", json.load(f))

    def count_live(self):
        return self.hc.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0]

    def test_owner_switches_off_by_default_live_without_backtest(self):
        for name, item in ((rt.SWITCH_LIVE, "G29"), (rt.SWITCH_TG, "G30")):
            self.assertEqual(settings.FLAGS[name][0], item)
            self.assertIn(name, settings.OWNER_SWITCHES)
            self.assertIn(name, settings.OWNER_SWITCH_NOTES)
            self.assertEqual(settings.flag(name, con=self.tc), "off")
            self.assertFalse(rt.switch_on(name, self.p["trade"]))
            self.assertIsNone(settings.live_refusal(self.tc, name))
        names = list(settings.FLAGS)
        self.assertEqual(names[names.index("rug_labels_v2_ok") + 1:names.index("rug_labels_v2_ok") + 3],
                         [rt.SWITCH_LIVE, rt.SWITCH_TG])
        self.switch(rt.SWITCH_TG)
        self.assertTrue(rt.switch_on(rt.SWITCH_TG, self.p["trade"]))

    def test_start_sh_runs_it_low_after_the_hourly_upkeep_and_the_guard_may_pause_it(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        line = next(ln for ln in sh.splitlines() if "ops.health --hourly" in ln and not ln.startswith("#"))
        self.assertLess(line.index("ops.diskreport --auto"), line.index("low python3 -m ops.retencija --auto"))
        self.assertEqual(cpuguard.classify(["python3", "-m", "ops.retencija", "--auto"])[:2], ("retencija", cpuguard.JOBS))
        from ops import dbs
        self.assertIn(("hype.db", "live_trades_ts", "live_trades (ts)"), dbs.TIME_INDEXES)
        plan = " ".join(r[3] for r in self.hc.execute("EXPLAIN QUERY PLAN SELECT COUNT(*) FROM live_trades WHERE ts < ?",
                                                      (NIGHT,)))
        self.assertIn("live_trades_ts", plan)


if __name__ == "__main__":
    unittest.main()
