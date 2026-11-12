"""12.11. (Jure, točka 4: "Missed-movers mjerenje: kad token ima manje od 3 točke cijene u prozoru, označi rezultat
kao 'nepouzdano' i ne računaj ga u statistiku propuštenih"): every measurement of what a skipped / missed token did
afterwards counts the price points of its window; with fewer than 3 the result is "nepouzdano" (no number, never
propušteno, in no count, hit rate or EV of the missed), every such statistic says how many it left out, and a row
measured before 12.11. without a count is judged as before. Covered: kol/preskoceni (skip_path.n_pts, the box),
fast/outcomes + fast/report + fast/live + fast/view (MCP), rangedca/missed (the range list's label, info, the EV
report's missed vs ostali note), proposals (outcomes.score, view, report.zone_miss_one / zone_lines, risers),
learn/outcomes.missed, paper/review. No network, databases in a temp dir.

    python3 -m unittest tests.test_missed_nepouzdano_offline
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fast import live as flive, outcomes as fout, report as freport, store as fstore, view as fview  # noqa: E402
from kol import preskoceni  # noqa: E402
from rangedca import missed  # noqa: E402
from tests.test_preskoceni_offline import CFG, NOW as PNOW, Base as PBase, skip  # noqa: E402
from tests.test_range_missed_offline import Env as RangeEnv, NOW as RNOW  # noqa: E402

NOTE1 = "nepouzdano: 1 (manje od 3 točke cijene)"
# a fixed Zagreb noon: the fast report's day holds every row below
T0 = int(dt.datetime(2026, 11, 12, 12, 0, tzinfo=ZoneInfo("Europe/Zagreb")).timestamp())


def tok(c):
    return c * 40 + "pump"


# ---------- the shared rule ------------------------------------------------------------------------------------------
class Rule(unittest.TestCase):
    def test_three_points_count_two_do_not_unknown_is_as_before(self):
        self.assertEqual(missed.MIN_POINTS, 3)
        self.assertIs(missed.reliable(2), False)
        self.assertIs(missed.reliable(3), True)
        self.assertIsNone(missed.reliable(None))             # a row measured before 12.11.: counted as before
        self.assertTrue(missed.unreliable(0))
        self.assertFalse(missed.unreliable(None))
        self.assertEqual(missed.note(2), "nepouzdano: 2 (manje od 3 točke cijene)")
        self.assertEqual(missed.detail(2), "samo 2 točke cijene u 60 min (treba 3)")
        self.assertEqual(missed.detail(1), "samo 1 točka cijene u 60 min (treba 3)")
        self.assertEqual(missed.detail(0), "nijedna točka cijene u 60 min (treba 3)")


# ---------- kol/preskoceni: the Autopilot's skips, 1-minute candles ------------------------------------------------
def sparse(m0, after):
    """The skip minute's candle (the entry, 1.0) and one candle at each minute k of `after` {k: high}."""
    out = [(m0, 1.0, 1.0, 1.0, 1.0, 100.0)]
    for k, hi in sorted(after.items()):
        out.append((m0 + k * 60, 1.0, hi, 0.98, 1.0, 100.0))
    return out


class Preskoceni(PBase):
    def measure(self, after):
        self.kc.execute("INSERT OR REPLACE INTO tokens (token, pair) VALUES ('TOK', 'POOL1')")
        self.kc.commit()
        t = PNOW - 3 * 3600 + 20
        m0 = t - t % 60
        n = preskoceni.run(self.mc, self.kc, CFG, PNOW, fetch=self.fetch({"POOL1": sparse(m0, after)}),
                           entries=[skip("TOK", t)])
        self.assertEqual(n[1], 1)
        return t, preskoceni.lookup(self.mc, [("TOK", m0)])[("TOK", m0)]

    def test_two_candles_in_the_hour_is_nepouzdano_not_propusteno(self):
        t, row = self.measure({5: 1.30, 40: 1.0})               # +30 % at minute 5, but only 2 minutes traded
        self.assertEqual((row["n_pts"], row["t15"]), (2, 5))
        v = preskoceni.verdict(row, t, PNOW)
        self.assertEqual((v["kind"], v["word"]), ("unrel", "nepouzdano"))
        self.assertEqual(v["detail"], "samo 2 točke cijene u 60 min (treba 3)")
        self.assertNotIn("%", v["detail"])                      # no number that would mislead
        self.assertIsNone(preskoceni.hit(row))                  # nothing claimed for the Autopilot's own target

    def test_three_candles_count(self):
        t, row = self.measure({5: 1.30, 20: 1.0, 40: 1.0})
        self.assertEqual(row["n_pts"], 3)
        self.assertEqual(preskoceni.verdict(row, t, PNOW)["kind"], "miss")
        self.assertTrue(preskoceni.hit(row))

    def test_window_points_are_the_candles_of_the_60_minutes_after_the_decision_minute(self):
        m0 = PNOW - PNOW % 60
        cs = [(m0 - 60, 1, 1, 1, 1, 1), (m0, 1, 1, 1, 1, 1), (m0 + 60, 1, 1, 1, 1, 1), (m0 + 3600, 1, 1, 1, 1, 1),
              (m0 + 3660, 1, 1, 1, 1, 1)]
        self.assertEqual(preskoceni.window_points(cs, m0 + 30), 2)

    def test_sentence_leaves_it_out_and_says_how_many(self):
        ts = PNOW - 3 * 3600
        base = {"entry": 1.0, "t15": 4, "sl_min": None, "hi60": 0.4, "lo60": 0.0, "r60": 0.1, "lv": "{}", "bad": None}
        vs = [preskoceni.verdict({**base, "n_pts": 2}, ts, PNOW),
              preskoceni.verdict({**base, "n_pts": 9}, ts, PNOW),
              preskoceni.verdict({**base, "n_pts": None}, ts, PNOW)]   # measured before 12.11.: as before
        self.assertEqual([v["kind"] for v in vs], ["unrel", "miss", "miss"])
        s = preskoceni.sentence(vs, [])
        self.assertEqual(s, f"Od 3 preskočena: 2 bi dosegla +15 % prije −20 %, {NOTE1}.")

    def test_box_shows_the_word_and_the_rule(self):
        from ui import pravitrade
        ts = PNOW - 3 * 3600
        m0 = preskoceni.minute_of(ts)
        e = skip("TOKU", ts)
        row = {"token": "TOKU", "ts": m0, "entry": 1.0, "t15": 4, "sl_min": None, "hi60": 0.4, "lo60": 0.0,
               "r60": 0.1, "lv": "{}", "bad": None, "n_pts": 1}
        html = pravitrade._skip_html([e], {("TOKU", m0): row}, PNOW, False, 15)
        self.assertIn("nepouzdano", html)
        self.assertIn("samo 1 točka cijene u 60 min", html)
        self.assertIn(NOTE1, html)
        self.assertNotIn("Propušteni po razlogu", html)        # not a skip that would have paid
        self.assertNotIn("+40", html)


# ---------- fast/: the fast_check skips, fast.db px points ---------------------------------------------------------
class Fast(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fp = os.path.join(self.tmp.name, "fast.db")
        self.fc = fstore.connect(self.fp)
        self.addCleanup(self.fc.close)

    def skip_row(self, token, t0=T0 - 7200, key="holders"):
        cur = self.fc.execute("INSERT INTO signals (token, symbol, kind, source_id, source_label, sig_ts, enq_ts, "
                              "status, decided_ts, decision, reason, price0, checks, latency_s, cost_pct) VALUES "
                              "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (token, token[:4], "wallet_follow", "W", "HODL", t0 - 3, t0 - 2, "done", t0, "SKIP",
                               "holderi: top10 62 % > 45 %", 1.0, json.dumps({"key": key, "res": {}}), 3.2, 3.0))
        return cur.lastrowid

    def points(self, token, t0, prices):
        for off, px in prices:
            fout.put_px(self.fc, token, px, None, t0 + off)

    def test_two_points_nepouzdano_three_count(self):
        t0 = T0 - 7200
        a, b = self.skip_row(tok("A"), t0), self.skip_row(tok("B"), t0)
        self.points(tok("A"), t0, ((300, 1.30), (900, 1.10)))                     # +30 %, but 2 points
        self.points(tok("B"), t0, ((300, 1.30), (900, 1.10), (1800, 1.05)))       # +30 % on 3 points
        fout.measure(self.fc, t0 + 1000)                                           # open window: 2 points so far
        ra = fstore.one(self.fc, a)
        self.assertIsNone(ra["missed"])                                            # not labelled while thin
        self.assertEqual(flive.skip_verdict(flive.one(ra, t0 + 1000), t0 + 1000)["kind"], "wait")
        fout.measure(self.fc, t0 + fout.HORIZON_S + fout.GRACE_S + 1)
        self.fc.commit()
        ra, rb = fstore.one(self.fc, a), fstore.one(self.fc, b)
        self.assertEqual((ra["missed"], ra["out"]["reliable"], ra["out"]["quality"], ra["out"]["n_points"]),
                         (None, False, "nepouzdano", 2))
        self.assertEqual((rb["missed"], rb["out"]["reliable"], rb["out"]["n_points"]), (1, True, 3))
        self.assertNotIn("quality", rb["out"])
        now = t0 + fout.HORIZON_S + 400
        rows = {r["id"]: r for r in flive.skip_rows(now, self.fp)}
        va, vb = flive.skip_verdict(rows[a], now), flive.skip_verdict(rows[b], now)
        self.assertEqual((va["kind"], va["word"], va["detail"]),
                         ("unrel", "nepouzdano", "samo 2 točke cijene u 60 min (treba 3)"))
        self.assertEqual((vb["kind"], vb["word"]), ("miss", "propušteno"))
        html = flive.skip_html(list(rows.values()), lambda x: x, now)
        self.assertIn("propušteno 1 (", html)
        self.assertIn(NOTE1, html)
        # the pop-up's line and the MCP answer: the word instead of the numbers, missed null
        self.assertEqual(fview._outcome(ra), "nakon: nepouzdano, samo 2 točke cijene u 60 min (treba 3)")
        self.assertIn("PROPUŠTENO", fview._outcome(rb))
        oa, ob = fview._row_out(ra), fview._row_out(rb)
        self.assertEqual((oa["missed"], oa["outcome"]["reliable"], oa["outcome"]["quality"]),
                         (None, False, "nepouzdano"))
        self.assertEqual((ob["missed"], ob["outcome"]["reliable"]), (1, True))

    def test_report_leaves_the_thin_ones_out_and_says_how_many(self):
        t0 = T0 - 7200
        thin_old = self.skip_row(tok("O"), t0)            # measured before 12.11.: missed = 1 stored, 2 points
        thin_new = self.skip_row(tok("N"), t0 + 5)        # 12.11.: missed NULL, quality nepouzdano
        good = self.skip_row(tok("G"), t0 + 9)
        self.fc.execute("UPDATE signals SET out_done=1, max60=40.0, missed=1, hit=1, out=? WHERE id=?",
                        (json.dumps({"max60": 40.0, "min60": -1.0, "n_points": 2}), thin_old))
        self.fc.execute("UPDATE signals SET out_done=1, max60=35.0, missed=NULL, hit=1, out=? WHERE id=?",
                        (json.dumps({"max60": 35.0, "min60": -1.0, "n_points": 1, "reliable": False,
                                     "quality": "nepouzdano"}), thin_new))
        self.fc.execute("UPDATE signals SET out_done=1, max60=30.0, missed=1, hit=1, out=? WHERE id=?",
                        (json.dumps({"max60": 30.0, "min60": -2.0, "n_points": 50}), good))
        self.fc.commit()
        rep = freport.daily(T0, con=self.fc)
        h = rep["per_check"]["holders"]
        self.assertEqual((h["rejected"], h["measured"], h["false_reject"], h["unreliable"]), (3, 1, 1, 2))
        self.assertEqual((rep["missed"], rep["missed_unreliable"]), (1, 2))
        ln = freport.lines(rep)
        self.assertIn("propušteno (SKIP pa +20 % u 60 min): 1, nepouzdano: 2 (manje od 3 točke cijene)", ln[0])
        self.assertTrue(any("izmjereno 1, nepouzdano: 2 (manje od 3 točke cijene))" in x for x in ln), ln)
        rows = freport.ev_rows(T0, "paper", path=self.fp, log=lambda s: None)
        r = [x for x in rows if x["part"] == "fast:odbio holderi"][0]
        self.assertEqual((r["n_outcomes"], r["hit_rate"]), (1, 1.0))
        self.assertIn("nepouzdano: 2 (manje od 3 točke cijene)", r["note"])


# ---------- rangedca/missed: the range list's label, info, the EV report ----------------------------------------------
class RangeLabel(RangeEnv):
    """The three journals of tests/test_range_missed_offline (A, B, C: no counts, labelled as before) plus rows with
    counts: 2 points = nepouzdano (U*), 3 or more = propušteno (R*), a token with both = labelled by the good one."""
    U1, U2, U3, U4, R1, R2, R3, MIX, W = (tok(c) for c in "QRSTUVWXY")

    def setUp(self):
        super().setUp()
        t = RNOW - 2 * 3600
        mc = sqlite3.connect(self.paths["minute"])
        for token, hi, n in ((self.U1, 0.40, 2), (self.R1, 0.30, 3), (self.MIX, 0.50, 1)):
            mc.execute("INSERT INTO skip_path (token, ts, entry, hi60, done_ts, n_pts) VALUES (?,?,?,?,?,?)",
                       (token, t, 1e-4, hi, t + 3900, n))
        mc.commit()
        mc.close()
        fc = sqlite3.connect(self.paths["fast"])
        for token, mx, miss, done, out in ((self.U2, 35.0, 1, 1, {"n_points": 2}),          # stored before 12.11.
                                           (self.U3, 40.0, None, 1, {"n_points": 1, "quality": "nepouzdano"}),
                                           (self.R2, 25.0, 1, 1, {"n_points": 3}),
                                           (self.MIX, 22.0, 1, 1, {"n_points": 30}),
                                           (self.W, 30.0, None, 0, {"n_points": 2})):        # window still open
            fc.execute("INSERT INTO signals (token, source_id, sig_ts, decided_ts, decision, max60, missed, out_done, "
                       "out, status) VALUES (?,?,?,?,?,?,?,?,?, 'done')",
                       (token, "s" + token[:3], t, t, "SKIP", mx, miss, done, json.dumps(out)))
        fc.commit()
        fc.close()
        pc = sqlite3.connect(self.paths["proposals"])
        for token, st, g, n in ((self.U4, "isteklo", 50.0, 2), (self.R3, "odbijeno", 22.0, 3)):
            pc.execute("INSERT INTO proposals (token, created_ts, status, after) VALUES (?,?,?,?)",
                       (token, t, st, json.dumps({"1h": {"status": "ok", "max_gain_pct": g, "n_points": n}})))
        pc.commit()
        pc.close()

    def test_label_only_on_three_points_and_the_excluded_count(self):
        ex = {}
        got = missed.labelled(RNOW, excluded=ex)
        A, B, C = (tok(c) for c in "ABC")
        self.assertEqual(set(got), {A, B, C, self.R1, self.R2, self.R3, self.MIX})
        self.assertEqual(got[self.MIX]["via"], {"brzi_put"})                 # its 1-point skip_path rise is not used
        self.assertEqual(set(ex), {self.U1, self.U2, self.U3, self.U4})      # W: open window, its points decide
        self.assertEqual((ex[self.U1]["n_points"], ex[self.U1]["via"]), (2, {"preskoceni"}))
        self.assertEqual(missed.labelled(RNOW), got)                        # the old call is unchanged

    def test_from_missed_info_and_the_ev_report_say_how_many(self):
        logs = []
        self.assertEqual(missed.from_missed(self.con, RNOW, logs.append), 7)
        self.assertIsNone(self.row(self.U1))                                 # nepouzdano: never on the list
        self.assertIsNotNone(self.row(self.R1))
        self.assertTrue(any("nepouzdano: 4 (manje od 3 točke cijene)" in x and "nisu na listi" in x for x in logs),
                        logs)
        info = missed.info(self.con, RNOW)
        self.assertEqual(info["unreliable"], 4)
        self.assertIn("manje od 3 točke cijene", info["unreliable_why"])
        n = len(logs)
        missed.from_missed(self.con, RNOW + 600, logs.append)                # the same four: said once
        self.assertFalse(any("nepouzdano" in x for x in logs[n:]), logs[n:])
        self.con.commit()
        from events import evreport
        from rangedca import gate
        lc = sqlite3.connect(":memory:")
        self.addCleanup(lc.close)
        lc.execute("CREATE TABLE range_rounds (user TEXT, status TEXT, closed_ts INTEGER, ret REAL, pnl_usd REAL, "
                   "levels TEXT)")
        from trade import settings
        lc.execute("INSERT INTO range_rounds VALUES (?,?,?,?,?,?)",
                   (settings.PAPER_USER, "closed", RNOW - 60, 0.1, 1.0, json.dumps({"src": "missed"})))
        with mock.patch.object(gate, "missed_refusal", lambda *a, **k: None):
            rows = evreport.range_source_rows(RNOW, "paper", lc)
        m = [r for r in rows if r["part"] == "range:missed"][0]
        self.assertEqual(m["n"], 1)
        self.assertIn("nepouzdano: 4 (manje od 3 točke cijene)", m["note"])


# ---------- proposals ----------------------------------------------------------------------------------------------
class Proposals(unittest.TestCase):
    def test_score_marks_a_horizon_on_two_minutes(self):
        from proposals import outcomes
        t0 = 1_800_000_000
        two = [(t0, 1.0, 1.3, 1.0, 1.2), (t0 + 600, 1.2, 1.2, 1.1, 1.1)]
        three = two + [(t0 + 1200, 1.1, 1.1, 1.0, 1.05)]
        a, b = outcomes.score(two, 1.0, t0, 3600, 0.15, 0.1, 0.0), outcomes.score(three, 1.0, t0, 3600, 0.15, 0.1, 0.0)
        self.assertEqual((a["n_points"], a["reliable"], a["quality"]), (2, False, "nepouzdano"))
        self.assertEqual((b["n_points"], b["reliable"]), (3, True))
        self.assertNotIn("quality", b)

    def test_view_shows_the_word_for_an_expired_one_and_mcp_marks_it(self):
        from proposals import view
        a1 = {"status": "ok", "max_gain_pct": 60.0, "max_dd_pct": -1.0, "first": "tp", "n_points": 2}
        a3 = dict(a1, n_points=3)
        self.assertEqual(view._after_text({"status": "isteklo", "after": {"1h": a1}}),
                         "1 h: nepouzdano, samo 2 točke cijene u 1 h (treba 3)")
        self.assertIn("najviše", view._after_text({"status": "isteklo", "after": {"1h": a3}}))
        self.assertIn("najviše", view._after_text({"status": "kupljeno", "after": {"1h": a1}}))   # not a missed one
        m = view._after_mcp({"status": "odbijeno", "after": {"1h": a1, "4h": dict(a1, n_points=40)}})
        self.assertEqual((m["1h"]["reliable"], m["1h"]["quality"]), (False, "nepouzdano"))
        self.assertNotIn("quality", m["4h"])

    def test_zone_miss_on_two_minutes_is_nepouzdano_and_left_out_of_the_outcomes(self):
        from proposals import report, store
        from tests.test_prijedlozi_offline import mint, prow
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        con = store.connect(os.path.join(tmp.name, "proposals.db"))
        self.addCleanup(con.close)
        T = 1_794_000_000 - 1_794_000_000 % 60
        now = T + 30 * 3600

        def one(token, pts):
            r = prow(token, exp=T + 900)
            r.update(entry_zone={"mcap_low": 100_000, "mcap_high": 105_000}, mcap0=100_000, price0=100_000 / 1e9)
            pid = store.insert(con, r, T)
            p = store.read(con, "id=?", (pid,))[0]
            cs = [(T + d - (T + d) % 60, mc / 1e9, mc / 1e9, mc / 1e9, mc / 1e9) for d, mc in pts]
            return report.zone_miss_one(p, cs, now, {}, {}, None, None, 1200, 200.0)
        thin = one(mint(51), [(60, 101_000), (300, 89_000), (600, 88_000)])                 # 2 minutes after the entry
        good = one(mint(52), [(60, 101_000), (300, 89_000), (600, 88_000), (900, 87_000)])  # 3 minutes
        self.assertEqual((thin["kind"], thin["quality"], thin["outcome"], thin["ret_pct"], thin["n_points"]),
                         ("missed", "nepouzdano", None, None, 2))
        self.assertEqual((good["kind"], good["outcome"], good.get("quality"), good["n_points"]),
                         ("missed", "sl", None, 3))
        rep = report.summarize([thin, good], now)
        self.assertEqual((rep["missed"], rep["outcomes"]["sl"], rep["unreliable"]), (2, 1, 1))
        self.assertAlmostEqual(rep["avg_ret_pct"], good["ret_pct"])
        ln = report.zone_lines(rep)
        self.assertIn(f"SL prvi 1, vrijeme 0, otvoreno 0, {NOTE1}", ln[0])
        self.assertTrue(any("-> nepouzdano, samo 2 točke cijene u 24 h (treba 3)" in x for x in ln), ln)

    def test_a_momentum_riser_on_two_snapshots_is_no_missed_riser(self):
        from proposals import report
        start = 1_800_000_000
        now = start + 6 * 3600
        sc = sqlite3.connect(":memory:")
        sc.execute("CREATE TABLE cand (token TEXT, symbol TEXT, mcap REAL, ch_h24 REAL, last_seen INTEGER)")
        mc = sqlite3.connect(":memory:")
        mc.execute("CREATE TABLE snaps (token TEXT, ts INTEGER, mcap REAL)")
        for i, m in enumerate((40_000, 120_000)):                               # 3x on two snapshots
            mc.execute("INSERT INTO snaps VALUES (?,?,?)", (tok("P"), start + 60 + i * 600, m))
        for i, m in enumerate((40_000, 90_000, 100_000)):                       # 2.5x on three
            mc.execute("INSERT INTO snaps VALUES (?,?,?)", (tok("Q"), start + 60 + i * 600, m))
        thin = []
        rs = report.risers(now, start, sc, mc, thin)
        self.assertEqual([r["token"] for r in rs], [tok("Q")])
        self.assertEqual([(r["token"], r["n_points"]) for r in thin], [(tok("P"), 2)])
        rep = {"day": "2026-11-12", "all": {"proposals": 0, "bought": 0, "rejected": 0, "expired": 0, "measured": 0,
                                            "hit_rate": None, "ev_pct": None, "ev_expected_pct": None},
               "per_strategy": {}, "missed_risers": [], "missed_risers_unreliable": 1}
        self.assertIn(f"  Propušten rast, {NOTE1} u snimkama dana: nije na popisu.", report.lines(rep))
        sc.close()
        mc.close()


# ---------- learn/outcomes and paper/review ------------------------------------------------------------------------
class LearnMissed(unittest.TestCase):
    def test_a_pump_on_two_snapshots_is_left_out_and_counted(self):
        from learn import outcomes
        now = 1_800_000_000
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        con.execute("CREATE TABLE token_tier (token TEXT, symbol TEXT, klasa TEXT, razina INTEGER, t0 TEXT, "
                    "t0_razlog TEXT, razlog TEXT, mcap REAL, first_ts INTEGER, last_ts INTEGER)")
        con.execute("CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL)")
        for token, prices in ((tok("T"), (1.0, 3.0)), (tok("H"), (1.0, 2.0, 2.5))):
            con.execute("INSERT INTO token_tier VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (token, token[:3], "mid", 0, "nije", None, None, 50_000, now - 3600, now - 60))
            for i, p in enumerate(prices):
                con.execute("INSERT INTO hype_snapshots VALUES (?,?,?)", (token, now - 3600 + i * 600, p))
        ex = []
        got = outcomes.missed(con, {"mid": 0.5}, now=now, excluded=ex)
        self.assertEqual([m["token"] for m in got], [tok("H")])
        self.assertEqual([(m["token"], m["quality"], m["n_points"], m["max_ret"]) for m in ex],
                         [(tok("T"), "nepouzdano", 2, None)])
        self.assertEqual([m["token"] for m in outcomes.missed(con, {"mid": 0.5}, now=now)], [tok("H")])


class ShadowMissed(unittest.TestCase):
    def test_the_learn_page_counts_only_paths_of_three_prices(self):
        from learn import shadow
        from ui import learnpage
        now = 1_800_000_000
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = os.path.join(tmp.name, "shadow.db")
        con = shadow.connect(db)
        for i, (ret, n) in enumerate(((0.9, 2), (0.8, 3), (0.1, 30), (0.7, None))):   # None: unknown, as before
            con.execute("INSERT INTO points (id, token, point, ts, decision, kupljeno, status, ret, n_pts) VALUES "
                        "(?,?,?,?,?,?,?,?,?)", (f"p{i}", tok("K"), "kandidat", now - 3600, "skip_score", 0, "gotovo",
                                                ret, n))
        con.commit()
        con.close()
        with mock.patch.object(shadow, "DB", db):
            html = learnpage.missed_shadow_html(now)
        self.assertIn("Zadnjih 7 dana: 2 od 3 preskočenih bi zaradilo +50% ili više; " + NOTE1 + ", nisu u brojkama.",
                      html)


class PaperReviewMissed(unittest.TestCase):
    def test_a_winner_on_two_ticks_is_no_missed_winner(self):
        from paper import review, sim, store
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        con = store.connect(os.path.join(tmp.name, "p.db"))
        self.addCleanup(con.close)
        cfg = {**sim.load_config(), "min_score": 50}
        t0 = 1_800_000_000
        for i, (name, rets) in enumerate((("TWO", (2.0, 2.5)), ("THREE", (1.0, 2.0, 2.5)))):
            c = {"token": name, "symbol": name, "ts": t0 + i * 60, "origin": "hype", "sources": ["profile"],
                 "score": 30, "features": {}, "price": 1.0, "liquidity": 50_000, "mcap": 1e5,
                 "decision": "skip_score", "reason": "score 30"}
            store.add_candidate(con, c)
            for k, r in enumerate(rets):
                store.tick(con, name, c["ts"] + 600 * (k + 1), 1.0 + r, 50_000, 1e5)
        con.commit()
        rep = review.run(con, cfg, hours=48, now=t0 + 30 * 3600)
        self.assertEqual([m["symbol"] for m in rep["missed"]], ["THREE"])
        self.assertEqual(rep["missed_unreliable"], 1)
        self.assertIn("- Nepouzdano: 1 (manje od 3 točke cijene): nisu na popisu.", review.to_md(rep, cfg))


if __name__ == "__main__":
    unittest.main()
