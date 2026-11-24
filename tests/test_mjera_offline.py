"""19.11. (vlasnik: "Demo money maybe no longer makes sense, since for every entry one can simply measure whether it was
profitable or not in percent ... Yes, start with both steps."): league/mjera.py, its three hooks, ui/novmjera.py.

    python3 -m unittest tests.test_mjera_offline
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import mjera, store as lstore  # noqa: E402
from trade import settings  # noqa: E402

NOW = 1_795_000_000
TOK = "TokA111111111111111111111111111111111pump"
GOOD = (0.01, 400_000.0, "u", 30e6, "AAA")          # price, liquidity, url, mcap, symbol


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "league.db")
        self.tdb = os.path.join(self.d, "trade.db")
        for p in (mock.patch.object(lstore, "DB", self.db), mock.patch.object(settings, "DB", self.tdb),
                  mock.patch.object(mjera, "_guard", side_effect=self.guard),
                  mock.patch.object(mjera, "_sol_usd", return_value=150.0),
                  mock.patch.object(mjera, "_hype_db", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.blocked = {}
        self.con = lstore.connect(self.db)
        self.addCleanup(self.con.close)
        mjera.ensure(self.con)
        mjera._LAST.update(pass_=0.0, line_day=None)
        mjera._LAST["pass"] = 0.0

    def guard(self, tok, q):
        if not q or not q[0]:
            return "nema žive cijene"
        return self.blocked.get(tok)

    def rows(self):
        self.con.row_factory = None
        try:
            return [dict(zip([c[0] for c in self.con.execute("SELECT * FROM signal_mjera LIMIT 0").description], r))
                    for r in self.con.execute("SELECT * FROM signal_mjera ORDER BY id")]
        finally:
            self.con.row_factory = sqlite3.Row


class Record(Base):
    def test_one_row_per_source_group_token_and_day(self):
        a = mjera.record(self.con, "prije_pumpe", "g1", "w1", TOK, NOW - 5, NOW, GOOD)
        self.assertIsNotNone(a)
        self.assertIsNone(mjera.record(self.con, "prije_pumpe", "g1", "w2", TOK, NOW + 60, NOW + 60, GOOD))   # dedup
        self.assertIsNotNone(mjera.record(self.con, "bundle", "b1", "w1", TOK, NOW, NOW + 60, GOOD))        # other source
        self.assertIsNotNone(mjera.record(self.con, "prije_pumpe", "g1", "w1", TOK, NOW, NOW + mjera.DEDUP_S + 1, GOOD))
        r = self.rows()[0]
        self.assertEqual((r["status"], r["guard"], r["mc_bucket"], r["delay_s"]), ("open", "ok", "15-200M", 5))
        self.assertEqual(r["entry_price"], 0.01)                     # our quote, never their price
        self.assertEqual(r["token_day"], time.strftime("%Y-%m-%d", time.gmtime(NOW)))

    def test_misses_are_kept_with_their_reason_and_never_in_the_mean(self):
        self.blocked[TOK] = "MC ispod 30k"
        mjera.record(self.con, "kopija", "w9", "w9", TOK, NOW - 3, NOW, GOOD)
        r = self.rows()[0]
        self.assertEqual((r["status"], r["guard"]), ("miss", "MC ispod 30k"))
        s = mjera.summary(self.con, NOW + 10)
        self.assertEqual((s["svi"]["misses"], s["svi"]["measured"]), (1, 0))
        self.assertIsNone(s["svi"]["mean01"])
        self.assertEqual(s["misses"], {"MC ispod 30k": 1})

    def test_no_quote_waits_then_the_pass_enters_at_its_own_quote_or_misses(self):
        rid = mjera.record(self.con, "insajderi2", "o1", "w1", TOK, NOW - 2, NOW, None)
        self.assertEqual(self.rows()[0]["entry_price"], None)
        mjera.pass_(self.con, lambda toks: {TOK: (0.02, 4e5, "", 30e6)}, now=NOW + 30, force=True)
        r = self.rows()[0]
        self.assertEqual((r["id"], r["status"], r["entry_price"], r["entry_ts"]), (rid, "open", 0.02, NOW + 30))
        mjera.record(self.con, "kopija", "w5", "w5", "TokB", NOW, NOW, None)
        mjera.pass_(self.con, lambda toks: {}, now=NOW + mjera.ENTRY_WAIT_S + 1, force=True)
        r = [x for x in self.rows() if x["token"] == "TokB"][0]
        self.assertEqual((r["status"], r["guard"]), ("miss", "bez cijene"))


class Exits(Base):
    def open_row(self, tok=TOK, members=("w1",)):
        mjera.record(self.con, "prije_pumpe", "g-" + tok, "w1", tok, NOW - 5, NOW, (0.01, 4e5, "", 30e6), members=members)

    def test_their_sale_stop_time_and_no_price(self):
        for t in ("T1", "T2", "T3", "T4"):
            self.open_row(t)
        sold = {"T1": NOW + 100}
        with mock.patch.object(mjera, "_sold", side_effect=lambda h, tok, since, ms: sold.get(tok)):
            px = {"T1": (0.012, 4e5, "", 3e7), "T2": (0.0074, 4e5, "", 3e7), "T3": (0.0105, 4e5, "", 3e7)}
            mjera.pass_(self.con, lambda toks: {t: px[t] for t in toks if t in px}, now=NOW + 600, force=True)
            mjera.pass_(self.con, lambda toks: {t: px[t] for t in toks if t in px}, now=NOW + mjera.HOLD_S + 5,
                        force=True)
            mjera.pass_(self.con, lambda toks: {}, now=NOW + mjera.HOLD_S + mjera.NO_PRICE_S + 10, force=True)
        r = {x["token"]: x for x in self.rows()}
        self.assertEqual((r["T1"]["status"], r["T1"]["exit_reason"]), ("closed", "prodali su"))
        self.assertAlmostEqual(r["T1"]["ret_gross"], 0.2)
        self.assertEqual(r["T2"]["exit_reason"], "stop")
        self.assertEqual(r["T3"]["exit_reason"], "vrijeme")
        self.assertEqual((r["T4"]["status"], r["T4"]["exit_reason"]), ("miss", "bez cijene"))

    def test_cost_floor_and_both_stakes(self):
        with mock.patch("trade.cost.round_trip", side_effect=lambda usd, liq: 0.01 if usd < 50 else 0.08):
            c1, c5 = mjera.costs(4e5, 150.0)
        self.assertEqual((c1, c5), (mjera.rt_floor(), 0.08))          # never under the 3 % floor
        self.open_row()
        with mock.patch.object(mjera, "_sold", return_value=NOW + 1), \
                mock.patch("trade.cost.round_trip", side_effect=lambda usd, liq: 0.01 if usd < 50 else 0.08):
            mjera.pass_(self.con, lambda toks: {TOK: (0.011, 4e5, "", 3e7)}, now=NOW + 60, force=True)
        r = self.rows()[0]
        self.assertAlmostEqual(r["ret_net_01"], 0.1 - 0.03)
        self.assertAlmostEqual(r["ret_net_05"], 0.1 - 0.08)

    def test_the_pass_is_bounded(self):
        for i in range(5):
            self.open_row(f"X{i}")
        out = mjera.pass_(self.con, lambda toks: {t: (0.01, 4e5, "", 3e7) for t in toks}, now=NOW + 60, force=True,
                          max_rows=2)
        self.assertEqual((out["priced"], out["left"]), (2, 3))
        ticks = iter([0.0, 0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
        out = mjera.pass_(self.con, lambda toks: {t: (0.01, 4e5, "", 3e7) for t in toks}, now=NOW + 120, force=True,
                          max_s=1.0, clock=lambda: next(ticks, 100.0))
        self.assertLess(out["priced"], 5)


class Numbers(Base):
    def closed(self, tok, day_ts, net, seen=None, entry=None, exit_=None, src="prije_pumpe", bucket="15-200M"):
        self.con.execute("INSERT INTO signal_mjera (source, gid, token, status, mc_bucket, ret_net_01, ret_net_05, "
                         "ret_gross, token_day, seen_ts, entry_ts, exit_ts, delay_s, guard) VALUES "
                         "(?,?,?,?,?,?,?,?,?,?,?,?,?,'ok')",
                         (src, "g", tok, "closed", bucket, net, net - 0.02, net + 0.03, mjera.day(day_ts),
                          seen or day_ts, entry or day_ts, exit_ or day_ts + 3600, 4))
        self.con.commit()

    def test_bootstrap_by_token_day_and_verdicts(self):
        for k in range(3):    # three rows of one token on one day are ONE token-day
            self.closed("T1", NOW, 0.1)
        self.closed("T2", NOW, -0.05)
        m, lo, hi, n = mjera.boot_td([dict(r) for r in mjera._rows(self.con)], "net01")
        self.assertEqual(n, 2)
        self.assertAlmostEqual(m, (0.3 - 0.05) / 4)
        st = mjera.stats(mjera._rows(self.con))
        self.assertEqual(mjera.verdict(st), "premalo podataka: n=2 od potrebnih 100 token-dana")
        self.assertEqual(mjera.verdict({"token_days": 120, "lo": 0.01, "hi": 0.2}), "u plusu")
        self.assertEqual(mjera.verdict({"token_days": 120, "lo": -0.3, "hi": -0.01}), "u minusu")
        self.assertEqual(mjera.verdict({"token_days": 120, "lo": -0.1, "hi": 0.2}), "još nije dokazano: interval dira nulu")
        p = mjera.proof(self.con, "prije_pumpe")
        self.assertFalse(p["ok"])
        self.assertEqual(p["n"], 2)

    def test_proof_rule(self):
        for i in range(110):
            self.closed(f"T{i}", NOW + (i % 30) * 86400, 0.05 + (i % 7) / 100)
        p = mjera.proof(self.con, "prije_pumpe")
        self.assertTrue(p["ok"], p)
        self.assertGreater(p["lo"], 0)

    def test_capacity_takes_signals_in_time_order_when_a_slot_is_free(self):
        self.closed("A", NOW, 0.10, entry=NOW, exit_=NOW + 100)
        self.closed("B", NOW, 0.20, seen=NOW + 10, entry=NOW + 10, exit_=NOW + 200)     # overlaps A
        self.closed("C", NOW, -0.10, seen=NOW + 150, entry=NOW + 150, exit_=NOW + 300)  # A has closed
        rows = mjera._rows(self.con)
        self.assertEqual(mjera.capacity(rows, 1)[:2], (2, 0.0))
        n, m, sol = mjera.capacity(rows, 5)
        self.assertEqual(n, 3)
        self.assertAlmostEqual(sol, 0.02)

    def test_log_line(self):
        self.closed("A", NOW, 0.10)
        mjera.record(self.con, "kopija", "w", "w", "Z", NOW, NOW, None)
        line = mjera.line(self.con, NOW + 60)
        self.assertTrue(line.startswith("mjerenje praćenja novčanika: 2 signala, 1 mjereno (promašeno 0 %), otvoreno 1; "
                                        "prije pumpe 15-200M: n=1, srednje +10,0 %; 2-15M: n=0; kandidati: n=0; "
                                        "bundle: n=0; kopija dokazanih: n=0; insajderi2: n=0; uz najviše 5 pozicija: "
                                        "n=1, +10,0 %"), line)


class Parity(Base):
    def demo(self, kind, tok, opened, ep, xp, table="pp_trades"):
        from insajderi import pp_live
        from wallets import kopija_demo
        pp_live.ensure(self.con)
        self.con.executescript(kopija_demo.SCHEMA)
        cur = self.con.execute("INSERT INTO trades (user, token, opened_ts, status, entry_px, exit_px, size_usd) "
                               "VALUES ('d', ?, ?, 'closed', ?, ?, 15)", (tok, opened, ep, xp))
        if table == "pp_trades":
            self.con.execute("INSERT INTO pp_trades (user, token, kind, trade_id, status) VALUES ('d',?,?,?, 'closed')",
                             (tok, kind, cur.lastrowid))
        else:
            self.con.execute("INSERT INTO kopija_trades (user, token, trade_id, status) VALUES ('d',?,?,'closed')",
                             (tok, cur.lastrowid))
        self.con.commit()

    def meas(self, src, tok, entry, gross):
        self.con.execute("INSERT INTO signal_mjera (source, gid, token, status, entry_ts, ret_gross, seen_ts) VALUES "
                         "(?,?,?,'closed',?,?,?)", (src, "g", tok, entry, gross, entry))
        self.con.commit()

    def test_parity_math_and_the_auto_switch_flips_once(self):
        for i in range(19):
            self.demo("prije_pumpe", f"T{i}", NOW, 1.0, 1.10)
            self.meas("prije_pumpe", f"T{i}", NOW + 120, 0.10 + (0.01 if i % 2 else -0.005))
        self.demo("prije_pumpe", "FAR", NOW, 1.0, 1.5)
        self.meas("prije_pumpe", "FAR", NOW + mjera.PARITY_WINDOW_S + 1, 0.5)    # entry too far: not matched
        p = mjera.parity(self.con)
        self.assertEqual((p["n"], p["word"]), (19, "premalo"))
        self.assertTrue(mjera.demo_entries_ok(self.con))
        self.demo("kopija", "K1", NOW, 1.0, 0.9, table="kopija_trades")
        self.meas("kopija", "K1", NOW + 30, -0.1)
        lines = []
        p = mjera.check_switch(self.con, NOW + 5, lines.append)
        self.assertEqual((p["n"], p["word"]), (20, "slaže se"))
        self.assertLessEqual(p["median_pp"], 1.5)
        self.assertTrue(lines and "POTVRĐENO" in lines[0])
        self.assertTrue(mjera.demo_entries_ok(self.con))      # 23.11. (vlasnik): parity no longer stops the demos
        self.assertIsNotNone(mjera.switched(self.con))
        mjera.check_switch(self.con, NOW + 10, lines.append)
        self.assertEqual(len(lines), 1)                                      # once
        self.assertEqual(mjera.parity_line(p), "mjerenje vs demo: upareno 20, medijan razlike 0,50 pp: slaže se")
        n_trades = self.con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        self.assertEqual(n_trades, 21)                                       # nothing deleted
        tcon = settings.connect(self.tdb)
        settings.put(tcon, mjera.MODE_KEY, "demo", "Jure")
        tcon.close()
        self.assertTrue(mjera.demo_entries_ok(self.con))                     # the owner keeps the demo running
        tcon = settings.connect(self.tdb)
        settings.put(tcon, mjera.MODE_KEY, "mjera", "Jure")
        tcon.close()
        self.assertFalse(mjera.demo_entries_ok(lstore.connect(os.path.join(self.d, "empty.db"))))   # forced

    def test_disagreement(self):
        for i in range(25):
            self.demo("bundle", f"T{i}", NOW, 1.0, 1.10)
            self.meas("bundle", f"T{i}", NOW, 0.05)
        p = mjera.parity(self.con)
        self.assertEqual(p["word"], "ne slaže se")
        self.assertIsNone(mjera.switched(self.con))


class Hooks(Base):
    def test_a_signal_refused_by_a_full_demo_is_still_measured_and_open_demo_trades_still_exit(self):
        from insajderi import live as ilive, pp_live, store as istore
        c = dict(istore.config(), pp_demo_max_open=0, pp_demo_per_day=0)
        exits = mock.Mock(return_value=[])
        with mock.patch.object(pp_live, "watched", return_value=[("prije_pumpe", "g1", ["w1", "w2"])]), \
                mock.patch.object(ilive, "fresh_buys", return_value=[(TOK, NOW - 3, "w1")]), \
                mock.patch.object(ilive, "mode", return_value="paper"), \
                mock.patch.object(istore, "config", return_value=c), \
                mock.patch.object(pp_live, "exits", exits), \
                mock.patch("veliki.symbols.resolve", return_value="AAA"):
            pp_live.ensure(self.con)
            self.con.execute("INSERT INTO pp_trades (user, token, status) VALUES ('x','OLD','open')")
            done = pp_live.run_once(self.con, market_fn=lambda toks: {TOK: GOOD}, now=NOW, sol=150.0, force=True)
            self.assertTrue(exits.called)
        self.assertEqual(done, [])                                           # the demo refused (cap 0)
        r = self.rows()
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["source"], r[0]["gid"], r[0]["wallet"], r[0]["status"]), ("prije_pumpe", "g1", "w1", "open"))
        self.assertEqual(json.loads(r[0]["members"]), ["w1", "w2"])
        # 23.11. (vlasnik: "Demo tradanje nikad ne treba prestati"): after parity held in "auto" the demo still enters
        mjera._kv(self.con, "prebaceno", {"ts": NOW})
        self.con.commit()
        with mock.patch.object(pp_live, "watched", return_value=[("prije_pumpe", "g1", ["w1"])]), \
                mock.patch.object(ilive, "fresh_buys", return_value=[("TokNEW", NOW + 9, "w1")]), \
                mock.patch.object(ilive, "mode", return_value="paper"), \
                mock.patch.object(pp_live, "exits", exits), \
                mock.patch.object(pp_live, "enter", return_value=(None, "test")) as enter:
            pp_live.run_once(self.con, market_fn=lambda toks: {t: GOOD for t in toks}, now=NOW + 10, sol=150.0,
                             force=True)
        self.assertTrue(enter.called)
        self.assertEqual(len(self.rows()), 2)
        # only the owner's own mode "mjera" holds the demo's new trades; the measurement goes on, open rows still exit
        tcon = settings.connect(self.tdb)
        settings.put(tcon, mjera.MODE_KEY, "mjera", "Jure")
        tcon.close()
        pp_live._TRIED.clear()
        with mock.patch.object(pp_live, "watched", return_value=[("prije_pumpe", "g1", ["w1"])]), \
                mock.patch.object(ilive, "fresh_buys", return_value=[("TokNEW2", NOW + 19, "w1")]), \
                mock.patch.object(ilive, "mode", return_value="paper"), \
                mock.patch.object(pp_live, "exits", exits), \
                mock.patch.object(pp_live, "enter") as enter:
            pp_live.run_once(self.con, market_fn=lambda toks: {t: GOOD for t in toks}, now=NOW + 20, sol=150.0,
                             force=True)
        self.assertFalse(enter.called)
        self.assertEqual(len(self.rows()), 3)

    def test_every_source_is_hooked_before_its_caps(self):
        for path, src in (("insajderi/pp_live.py", "mjera.record(con, kind"), ("insajderi/live.py", 'mjera.record(con, "insajderi2"'),
                          ("wallets/kopija_demo.py", 'mjera.record(con, "kopija"')):
            with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                txt = f.read()
            run = txt[txt.index("def run_once"):]
            self.assertIn(src, run, path)
            self.assertLess(run.index("mjera.record("), run.index("enter(con"), path)
            self.assertIn("demo_entries_ok(con)", run, path)

    def test_no_real_money_path_imports_the_measurement(self):
        for path in ("run_trade.py", "trade/executor.py", "trade/settings.py", "trade/capgate.py", "trade/gates.py"):
            p = os.path.join(ROOT, path)
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    self.assertIsNone(re.search(r"(import|from)\s+[\w.]*mjera|league\.mjera|import .*\bmjera\b", f.read()),
                                      path)


class Pages(Base):
    def seed(self):
        sym = "<script>alert(1)</script>"
        for i in range(6):
            self.con.execute("INSERT INTO signal_mjera (source, gid, wallet, token, symbol, status, mc_bucket, "
                             "ret_net_01, ret_net_05, ret_gross, token_day, seen_ts, entry_ts, exit_ts, exit_reason, "
                             "delay_s, guard) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (mjera.SOURCES[i % 5], "o:groupid12", "walletAAAA", f"T{i}", sym, "closed",
                              "15-200M", 0.04, 0.02, 0.07, mjera.day(NOW), NOW, NOW, NOW + 3600, "prodali su", 3, "ok"))
        self.con.commit()

    def test_autopilot_section_with_data_empty_and_missing(self):
        from ui import novmjera, pauza
        with mock.patch.object(pauza, "on", return_value=True), \
                mock.patch("ui.novpodaci.league_db", return_value=self.db):
            empty = novmjera.autopilot_html(True, NOW)
            self.assertIn("Mjerenje još nije zabilježilo nijednu kupnju", empty)
            self.seed()
            html = novmjera.autopilot_html(True, NOW + 60)
        self.assertIn("Praćenje novčanika: mjerenje po ulazu (bez pravog novca)", html)
        self.assertIn('title="premalo: 1 od potrebnih 100 dana s kupnjama">premalo</span>', html)
        self.assertIn("<details class=nm-det><summary>Detalji</summary>", html)   # 20.11.: the answer first
        self.assertRegex(html, r"<p class=nm-ans>Od \d+\.\d+\. smo izmjerili \d+ kupnj[aeiu] praćenih novčanika: u prosjeku "
                               r"[+−][\d,]+\xa0% po kupnji nakon troška\. Premalo je za zaključak")
        self.assertIn("Koliko bismo stigli", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn(" $</td>", html.split("Zadnje kupnje")[1])      # no demo dollars in the rows
        self.assertIn('action=/pravi-trade/mjera-nacin', html)
        with mock.patch.object(pauza, "on", return_value=False):
            self.assertEqual(novmjera.autopilot_html(True, NOW), "")
        with mock.patch.object(pauza, "on", return_value=True), \
                mock.patch("ui.novpodaci.league_db", return_value=os.path.join(self.d, "nema.db")):
            self.assertIn("nijednu kupnju", novmjera.autopilot_html(False, NOW))

    def test_admin_section(self):
        from ui import novmjera
        with mock.patch("ui.novpodaci.league_db", return_value=os.path.join(self.d, "nema.db")):
            self.assertIn("Još nema mjerenja", novmjera.admin_html(NOW))
        self.seed()
        with mock.patch("ui.novpodaci.league_db", return_value=self.db):
            html = novmjera.admin_html(NOW + 60)
        for s in ("Dokaz za pravi novac", "promašaji), po razlogu", "Mjerenje i demo:", "Po skupini i novčaniku",
                  "uparenih kupnji 0", "način auto"):
            self.assertIn(s, html)
        self.assertNotIn("<script>alert", html)

    def test_public_sentence_both_languages(self):
        from ui import pauza
        self.assertEqual(pauza.DEMO["hr"], "U međuvremenu mjerimo svaki ulaz praćenih novčanika u postocima, bez pravog "
                                           "novca.")
        self.assertEqual(pauza.DEMO["en"], "Meanwhile we measure every entry of the followed wallets in percent, with no "
                                           "real money.")

    def test_the_owner_sets_the_mode(self):
        from ui import pravitrade
        with mock.patch.object(settings, "is_owner", return_value=True):
            to = pravitrade.post("/pravi-trade/mjera-nacin", {"nacin": "demo"}, "Jure")
            self.assertIn("ok=", to)
            self.assertEqual(mjera.mode(), "demo")
            self.assertIn("err=", pravitrade.post("/pravi-trade/mjera-nacin", {"nacin": "x"}, "Jure"))


if __name__ == "__main__":
    unittest.main()
