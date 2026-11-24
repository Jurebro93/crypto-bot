"""Tjedni trošak po izvoru (report/tjedni.py, 19.11.) on a fixed fortnight of usage rows, no network:

  - per source the last 7 UTC days in its own unit and in $ where known, the change against the week before, the jobs
  - "što je donijelo": the wallet-following entries for Helius / PumpPortal, the midcap entries for CoinGecko, the
    critic's verdicts, the owner's decisions and the council for OpenAI / Anthropic, else "nije mjerljivo"
  - Birdeye only when usage.db has it
  - when: Monday, or the first report after a deploy with no weekly section for 7 days; marked only after the send
  - the morning e-mail carries the section; no address, key or env name in it

    python3 -m unittest tests.test_tjedni_trosak_offline
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from report import tjedni  # noqa: E402
from usage import daily, meter  # noqa: E402

D = 86400
MON = 1795392000          # 2026-11-23 00:00 UTC, a Monday
NOW = MON + 6 * 3600 + 1800   # 07:30 Zagreb: the morning report
CUR = [MON - k * D for k in range(1, 8)]      # 22.11. ... 16.11.
PREV = [MON - k * D for k in range(8, 15)]    # 15.11. ... 9.11.


def day_row(ts, scale):
    """One usage/daily row; the previous week is `scale` times the current one."""
    return {"day": tjedni._day(ts), "ts": ts + D - 60,
            "coingecko": {"kljuc": 1000 * scale, "po_poslu": {"midcap": 700 * scale, "skener": 300 * scale},
                          "besplatno": {"graf": 100 * scale}, "besplatno_ukupno": 100 * scale},
            "twitterapi": {"usd": 0.5 * scale, "dijelovi": {"timeline": 0.4 * scale, "discover": 0.1 * scale}},
            "apify": {"usd_bot": 0.2 * scale, "po_izvoru": {"tiktok": 0.2 * scale}},
            "pumpportal": {"tradeova": 20000 * scale, "sol": 0.02 * scale},
            "helius": {"krediti_bot": 30000 * scale, "po_poslu": {"run_insajderi.py": 25000 * scale,
                                                                   "run_ui.py": 5000 * scale}},
            "ai": {"usd": 0.1 * scale, "po_poslu": {"postai": 0.1 * scale}, "objava": 50},
            "openai": {"usd": 0.3 * scale, "poziva": 10, "po_vrsti": {"presuda": 0.3 * scale}, "presuda": 4,
                       "odluke_vlasnika": {"accepted": 1}},
            "vijece": {"openai_usd": 0.1 * scale, "claude_usd": 0.2 * scale, "ocjena": 2, "odluka": 1}}


def league(path):
    con = sqlite3.connect(path)
    for t in ("insajderi2_trades", "pp_trades", "kopija_trades", "veliki_trades"):
        con.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, user TEXT, token TEXT, opened_ts INTEGER, "
                    "status TEXT, pnl_usd REAL)")
    rows = [("insajderi2_trades", "autopilot-novcanici", CUR[2], "closed", 2.0),
            ("pp_trades", "autopilot-novcanici", CUR[1], "closed", -0.5),
            ("pp_trades", "autopilot-novcanici", CUR[0], "open", None),
            ("pp_trades", "autopilot-novcanici", PREV[0], "closed", 9.0),       # the week before: not counted
            ("veliki_trades", "autopilot-paper", CUR[3], "closed", 1.25),
            ("veliki_trades", "pravi-trade", CUR[4], "closed", -0.75)]
    for i, (t, u, ts, st, pnl) in enumerate(rows):
        con.execute(f"INSERT INTO {t} (user, token, opened_ts, status, pnl_usd) VALUES (?,?,?,?,?)",
                    (u, f"T{i}", ts + 3600, st, pnl))
    con.commit()
    con.close()


class Week(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = {"usage": os.path.join(self.tmp.name, "usage.db"), "league": os.path.join(self.tmp.name, "league.db")}
        for ts in CUR:
            daily.save(day_row(ts, 1), self.p["usage"])
        for ts in PREV:
            daily.save(day_row(ts, 2), self.p["usage"])
        daily.save(day_row(MON, 50), self.p["usage"])                             # today (a partial row): left out
        league(self.p["league"])
        users = mock.patch("report.midcap.users", return_value={"demo": "autopilot-paper", "pravi": "pravi-trade"})
        users.start()
        self.addCleanup(users.stop)

    def by(self, t):
        return {r["kljuc"]: r for r in t["izvori"]}

    def test_fixed_week_per_source(self):
        t = tjedni.collect(NOW, self.p, sol_usd=150.0)
        self.assertEqual((t["od"], t["do"], t["dana"], t["dana_prije"]), ("2026-11-16", "2026-11-22", 7, 7))
        r = self.by(t)
        self.assertNotIn("birdeye", r)                                            # not there yet: no row
        self.assertEqual((r["helius"]["kolicina"], r["helius"]["usd"], r["helius"]["promjena"]), (210000, None, "-50%"))
        self.assertEqual(r["helius"]["poslovi"][0], ["run_insajderi.py", 175000])
        self.assertAlmostEqual(r["twitterapi"]["usd"], 3.5)
        self.assertEqual(r["twitterapi"]["poslovi"][0], ["timeline", 2.8])
        self.assertAlmostEqual(r["openai"]["usd"], 2.8)                           # critic 0.3 + council 0.1, a day
        self.assertAlmostEqual(r["anthropic"]["usd"], 2.1)                        # labels 0.1 + council 0.2
        self.assertEqual(r["coingecko"]["kolicina"], 7700)                        # key and free calls
        self.assertIsNone(r["coingecko"]["usd"])
        self.assertAlmostEqual(r["pumpportal"]["kolicina"], 0.14)
        self.assertAlmostEqual(r["pumpportal"]["usd"], 21.0)                      # at the SOL price given
        self.assertAlmostEqual(r["apify"]["usd"], 1.4)
        self.assertAlmostEqual(t["ukupno_usd"], 3.5 + 2.8 + 2.1 + 21.0 + 1.4)
        # what it brought
        self.assertIn("3 demo/pravih ulaza (insajderi2 1, prije pumpe / bundle 2)", r["helius"]["donijelo"])
        self.assertIn("zatvoreno 2, neto +1,50 $", r["helius"]["donijelo"])
        self.assertIn("nije mjerljivo", r["helius"]["donijelo"])                  # the split with PumpPortal
        self.assertEqual(r["pumpportal"]["donijelo"], r["helius"]["donijelo"])
        self.assertIn("2 demo/pravih ulaza (demo 1, pravi novac 1)", r["coingecko"]["donijelo"])
        self.assertIn("28 presuda", r["openai"]["donijelo"])
        self.assertIn("accepted 7", r["openai"]["donijelo"])
        self.assertIn("vijeće 7 odluka", r["openai"]["donijelo"])
        self.assertIn("vijeće 7 odluka", r["anthropic"]["donijelo"])
        self.assertIn("350 objava: trade iz njih nije mjerljivo", r["anthropic"]["donijelo"])
        for k in ("twitterapi", "apify"):
            self.assertEqual(r[k]["donijelo"], "nije mjerljivo")

    def test_birdeye_when_present_and_no_sol_price(self):
        con = meter.connect(self.p["usage"])
        con.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?)", (CUR[0], "birdeye", "run_insajderi.py", "povijest",
                                                                   40, 0, 4000.0))
        con.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?)", (PREV[0], "birdeye", "run_insajderi.py", "povijest",
                                                                   10, 0, 1000.0))
        con.commit()
        con.close()
        with mock.patch("trade.equity.rates", return_value={"sol_usd": None}):
            t = tjedni.collect(NOW, self.p)
        r = self.by(t)
        self.assertEqual((r["birdeye"]["kolicina"], r["birdeye"]["promjena"], r["birdeye"]["jedinica"]),
                         (4000.0, "+300%", "CU"))
        self.assertEqual(r["birdeye"]["donijelo"], "nije mjerljivo")
        self.assertIsNone(r["pumpportal"]["usd"])
        rows = tjedni.rows(t)
        pp = [x for x in rows if x[0] == "PumpPortal"][0]
        self.assertIn("$ po jedinici nepoznat", pp[1])
        self.assertIn("4.000 CU", [x for x in rows if x[0] == "Birdeye"][0][1])

    def test_no_saved_day_no_section(self):
        self.assertIsNone(tjedni.collect(NOW, {"usage": os.path.join(self.tmp.name, "x.db"), "league": None}))

    def test_in_the_morning_mail(self):
        from report import render
        t = tjedni.collect(NOW, self.p, sol_usd=150.0)
        body = tjedni.html(t, render)
        for s in ("Zadnjih 7 UTC dana (2026-11-16 do 2026-11-22)", "Što je donijelo", "210.000 kredita", "-50%",
                  "nije mjerljivo", "run_insajderi.py"):
            self.assertIn(s, body)
        for bad in ("RENDER_", "API_KEY", "SOLANA_", "@"):
            self.assertNotIn(bad, body)
        data = {"ts": NOW, "fokus": True, "midcap": {}, "tjedni_trosak": t}
        html = render.render(data, {}, "pravila")
        self.assertIn("Tjedni trošak po izvoru", html)
        self.assertNotIn("Tjedni trošak po izvoru", render.render({"ts": NOW, "fokus": True, "midcap": {}}, {}, "pravila"))


class When(unittest.TestCase):
    def test_monday_or_first_after_deploy(self):
        self.assertTrue(tjedni.due(NOW, {}, 0, "")[0])                                   # Monday
        st = {"report_commit": "aaa", "tjedni_ts": NOW - 3 * D}
        self.assertFalse(tjedni.due(NOW, st, 2, "aaa")[0])                               # Wednesday, same deploy
        self.assertFalse(tjedni.due(NOW, st, 2, "bbb")[0])                               # new deploy, sent 3 days ago
        ok, why = tjedni.due(NOW, {"report_commit": "aaa", "tjedni_ts": NOW - 8 * D}, 2, "bbb")
        self.assertTrue(ok)
        self.assertIn("nakon deploya", why)
        self.assertFalse(tjedni.due(NOW, {"report_commit": "aaa", "tjedni_ts": NOW - 8 * D}, 2, "aaa")[0])
        self.assertFalse(tjedni.due(NOW, {}, 2, "")[0])                                  # no deploy known: Mondays

    def test_send_marks_only_after_the_mail_went_out(self):
        import run_report
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        html = "<html>Tjedni trošak po izvoru</html>"
        with mock.patch.object(run_report, "OUT", tmp.name), \
                mock.patch.object(run_report, "STATE", os.path.join(tmp.name, "s.json")), \
                mock.patch.object(run_report, "build", return_value=("2026-11-25", "x", html, {}, "pravila")) as b, \
                mock.patch.dict(os.environ, {"RENDER_GIT_COMMIT": "bbb"}), \
                mock.patch.object(run_report.dump, "emit"):
            run_report.save_state({"report_commit": "aaa", "tjedni_ts": NOW - 9 * D})
            wed = NOW + 2 * D
            with mock.patch.object(run_report.mail, "send", side_effect=RuntimeError("nema")):
                run_report.send_today(False, wed)
            self.assertTrue(b.call_args.kwargs["weekly"])
            st = run_report.load_state()
            self.assertEqual((st["report_commit"], st["tjedni_ts"]), ("aaa", NOW - 9 * D))   # not sent: unchanged
            with mock.patch.object(run_report.mail, "send", return_value="smtp"):
                run_report.send_today(False, wed)
            st = run_report.load_state()
            self.assertEqual((st["report_commit"], st["tjedni_ts"]), ("bbb", wed))
            with mock.patch.object(run_report.mail, "send", return_value="smtp"):
                run_report.send_today(False, wed + D)                                    # Thursday: not again
            self.assertFalse(b.call_args.kwargs["weekly"])


if __name__ == "__main__":
    unittest.main()
