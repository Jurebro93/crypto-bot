"""Morning report: collect from synthetic DBs, fallback interpretation, email-safe render, no network."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOW = 1793433600  # 2026-10-31 08:00 UTC (eu session)


def make_dbs(d):
    from hype import pulse
    from kol import store as kstore
    from learn import store as lstore
    from paper import store as pstore
    from tiers import store as tstore
    h = sqlite3.connect(os.path.join(d, "hype.db"))
    h.executescript(lstore.SCHEMA + tstore.SCHEMA + pulse.SCHEMA)
    h.execute("INSERT INTO learn_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
              (NOW - 3600, "moonshot", 420, 0.8, 1, 0.61, 0.64, json.dumps({"kol_group": 10, "rast_holdera": 8}),
               json.dumps({"kol_group": 12, "rast_holdera": 9.5}), "ok"))
    for i, (tok, sym) in enumerate([("MintAaaa", "AAA"), ("MintBbbb", "BBB")]):
        h.execute("INSERT INTO token_tier (token, symbol, first_ts, last_ts, razina, klasa, t0, score, mcap) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (tok, sym, NOW - 20000, NOW - 600, 1, "moonshot", "prolaz", 60 - i * 10,
                                                 150000))
        for k in range(10):
            h.execute("INSERT INTO token_pulse (token, ts, vol_h1, holders, mcap, buys_h1, sells_h1) VALUES (?,?,?,?,?,?,?)",
                      (tok, NOW - (10 - k) * 3600, 1000 + k * 300, 100 + k * 20 * (1 - i), 150000, 50, 20))
    h.execute("INSERT INTO token_tier (token, symbol, last_ts, razina, t0, score) VALUES ('MintRug', 'RUG', ?, 2, 'pad', 99)",
              (NOW,))
    # dead dust token that never passed T0: not a candidate for today (2.11. report listed 6 of these)
    h.execute("INSERT INTO token_tier (token, symbol, last_ts, razina, t0, score, mcap) "
              "VALUES ('MintDust', 'DUST', ?, 1, NULL, 98, 2000)", (NOW - 5 * 3600,))
    h.commit()
    h.close()
    k = sqlite3.connect(os.path.join(d, "kol.db"))
    k.executescript(kstore.SCHEMA)
    k.execute("INSERT INTO kols (handle, followers, score, stats, first_seen) VALUES (?,?,?,?,?)",
              ("alpha", 5000, 62, json.dumps({"measured": 12, "hit_rate": 0.75, "med_max24": 1.2, "prepump_rate": 0.1}),
               NOW - 100))
    k.execute("INSERT INTO kols (handle, followers, score, stats) VALUES ('tiny', 10, 70, '{\"measured\": 1}')")
    k.execute("INSERT INTO watch VALUES ('alpha', 62, ?, 'top')", (NOW,))
    k.execute("INSERT INTO calls (tweet_id, token, handle, ts, url, kind, first_by_kol, max24, mcap0, symbol) "
              "VALUES ('1','MintAaaa','alpha',?,'https://x.com/a/1','call',1,2.5,40000,'AAA')", (NOW - 30000,))
    k.execute("INSERT INTO sessions VALUES ('signal:us', 41, 33, 1.1, 1.25, ?)", (NOW,))
    k.execute("INSERT INTO sessions VALUES ('call:asia', 15, 10, 0.6, 1.0, ?)", (NOW,))
    for hr in range(24):
        ts = (NOW // 3600 - 24 + hr) * 3600
        k.execute("INSERT INTO token_hours VALUES ('MintAaaa', ?, ?, ?)", (ts, 900 if time.gmtime(ts).tm_hour >= 14 else 50, NOW))
    k.execute("INSERT INTO signals VALUES ('MintAaaa', ?, 1, 2, 'alpha,beta', 0, 0.8)", (NOW,))
    k.commit()
    k.close()
    p = sqlite3.connect(os.path.join(d, "paper.db"))
    p.executescript(pstore.SCHEMA)
    for i, r in enumerate([0.8, -0.3, 0.1]):
        p.execute("INSERT INTO trades (token, symbol, opened_ts, closed_ts, status, ret, pnl_usd, exit_reason) "
                  "VALUES (?,?,?,?,?,?,?,?)", (f"T{i}", f"S{i}", NOW - 9000, NOW - 3600 * (i + 1), "closed", r, r * 100,
                                               "tp"))
    p.commit()
    p.close()


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        make_dbs(self.tmp.name)
        os.environ["REPORT_DB_DIR"] = self.tmp.name
        os.environ["LEARNED_DIR"] = self.tmp.name
        with open(os.path.join(self.tmp.name, "exits.json"), "w") as f:
            json.dump({"profiles": {"moonshot/us": {"v": 2, "params": {"tp": 1.0}, "ts": NOW - 100,
                                                    "eval": {"win": 0.4, "median": -0.2}}}, "runs": []}, f)

    def tearDown(self):
        os.environ.pop("REPORT_DB_DIR", None)
        self.tmp.cleanup()

    def test_collect_render(self):
        from report import ai, collect, render
        import report.collect as c
        c._learned_dir = lambda: self.tmp.name
        d = collect.collect(NOW)
        self.assertEqual(d["weights"]["runs"][0]["top"][0]["feature"], "kol_group")
        self.assertEqual(d["exits"]["changed"][0]["profil"], "moonshot/us")
        self.assertAlmostEqual(d["sessions"]["us"]["signal"]["hit"], 33 / 41)
        self.assertEqual([x["handle"] for x in d["kols"]["top"]], ["alpha"])   # 1 measured call is not enough
        toks = [t["symbol"] for t in d["today"]["tokens"]]
        self.assertNotIn("RUG", toks)
        self.assertNotIn("DUST", toks)
        self.assertEqual(toks[0], "AAA")                                        # US-heavy volume x factor 1.25 + KOL
        self.assertEqual(d["today"]["tokens"][0]["dominant"], "us")
        self.assertEqual([x["symbol"] for x in d["pulse"]], ["AAA"])            # BBB holders flat -> not growing
        self.assertEqual(d["paper"]["closed"], 3)
        self.assertEqual(d["paper"]["wins"], 2)
        interp = ai.fallback(d)
        out = render.render(d, interp, "pravila")
        for s in ("Što sam naučio", "Influenceri", "Tokeni za danas", "Konstantan rast", "Demo trading", "/token/MintAaaa",
                  "/kol/alpha", "kol_group"):
            self.assertIn(s, out)
        self.assertNotIn("<script", out)
        self.assertNotIn("<svg", out)
        json.dumps(ai.compact(d))
        self.assertNotIn("Hitno: potrošnja", out)
        d["spend"] = [{"level": "bad", "key": "helius:x", "service": "helius", "title": "Helius krediti nestaju",
                       "detail": "budžet do 14.11."}]
        out = render.render(d, interp, "pravila")
        self.assertIn("Hitno: potrošnja", out)
        self.assertIn("budžet do 14.11.", out)

    def test_empty_dbs(self):
        from report import ai, collect, render
        os.environ["REPORT_DB_DIR"] = tempfile.mkdtemp()
        d = collect.collect(NOW)
        self.assertEqual(d["today"]["tokens"], [])
        render.render(d, ai.fallback(d), "pravila")

    def test_mail_config(self):
        from report import mail
        env = {k: os.environ.pop(k) for k in ("REPORT_EMAIL_TO", "SMTP_USER", "SMTP_PASSWORD", "RESEND_API_KEY")
               if k in os.environ}
        try:
            self.assertEqual(len(mail.missing()), 2)
            os.environ.update(REPORT_EMAIL_TO="a@b.c, d@e.f", SMTP_USER="x@gmail.com", SMTP_PASSWORD="abcd efgh")
            self.assertEqual(mail.missing(), [])
            self.assertEqual(mail.recipients(), ["a@b.c", "d@e.f"])
            self.assertEqual(mail.method(), "smtp")
            self.assertIn("Naslov", mail.plain("<div>Naslov</div><p>tekst</p>"))
        finally:
            for k in ("REPORT_EMAIL_TO", "SMTP_USER", "SMTP_PASSWORD"):
                os.environ.pop(k, None)
            os.environ.update(env)

    def test_no_key_uses_rules(self):
        from report import ai, collect
        os.environ.pop("ANTHROPIC_API_KEY", None)
        d = collect.collect(NOW)
        out, src = ai.interpret(d)
        self.assertEqual(src, "pravila")
        self.assertTrue(out["naucio"])


class DumpTest(unittest.TestCase):
    def test_roundtrip(self):
        from report import dump
        html = ('<html><head><title>x</title></head><body><p style="color:red;font-size:13px">a</p> '
                '<p style="color:red;font-size:13px">b</p></body></html>')
        ls = dump.lines("2026-11-02", html * 50)
        self.assertTrue(all(l.startswith("REPORT-B64 2026-11-02 ") for l in ls))
        b = "".join(l.split(" ", 3)[3] for l in ls)
        out = dump.decode(b)
        self.assertIn("<style>.c0{color:red;font-size:13px}", out)
        self.assertIn('<p class="c0">a</p>', out)


if __name__ == "__main__":
    unittest.main()
