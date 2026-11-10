"""Novčanici i jedan novčanik u mirnom jeziku (10.11., Jure, prijedlog 4.6 i 4.7): read-only helpers in
wallets/dokazani (one wallet's row with the cut, why it did not pass, why it is not copyable), the wallet chart with
the cut line (ui/walletchart) and the wallet pages (ui/pages: hero, rows, verdict, subpages). No network."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_ui  # noqa: E402,F401  (wires the page modules like the server does)
from ui import pages, walletchart  # noqa: E402
from wallets import dokazani, store as wstore  # noqa: E402

from tests.test_dokazani_offline import D, NOW, make_db  # noqa: E402


class DokazaniReadOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path, con = make_db(self.tmp)
        self.rows = {r["wallet"]: r for r in dokazani.evaluate(con, NOW)}
        dokazani.run(con, NOW, log=None)
        con.close()

    def test_for_wallet_gives_the_latest_row_and_its_cut(self):
        r = dokazani.for_wallet("PROVEN", self.path)
        self.assertEqual((r["passed"], r["closed_before"], r["as_of"]), (1, 6, NOW))
        self.assertEqual(r["cut"], NOW - dokazani.RULE["cut_days"] * D)
        self.assertEqual(dokazani.for_wallet("ONCE", self.path)["passed"], 0)    # judged, not passed: still shown
        self.assertIsNone(dokazani.for_wallet("BOT", self.path))                # not copyable: never judged
        self.assertIsNone(dokazani.for_wallet("PROVEN", os.path.join(self.tmp, "none.db")))
        self.assertIsNone(dokazani.for_wallet("", self.path))

    def test_misses_agree_with_passed(self):
        for r in self.rows.values():
            self.assertEqual(bool(dokazani.misses(r)), not r["passed"], r["wallet"])
        self.assertEqual(dokazani.misses(self.rows["ONCE"])[0][0], "realized_after")   # good before, lost after
        few = dict(self.rows["PROVEN"], closed_before=3)
        self.assertEqual(dokazani.misses(few)[0], ("closed_before", 3, dokazani.RULE["min_closed"]))

    def test_not_copyable_agrees_with_copyable(self):
        cases = [({"median_hold_min": 30, "trades_per_day": 5}, []), ({"median_hold_min": 1, "trades_per_day": 900}, ["bot"]),
                 ({"median_hold_min": 30, "trades_per_day": 5, "bag_share": 0.4}, []), ({}, []),
                 ({"median_hold_min": 30, "trades_per_day": 5}, ["sniper", "x"])]
        for s, lab in cases:
            self.assertEqual(dokazani.not_copyable(s, lab) == [], dokazani.copyable(s, lab), (s, lab))
        keys = [k for k, _, _ in dokazani.not_copyable({"median_hold_min": 1, "trades_per_day": 900}, ["bot"])]
        self.assertEqual(keys, ["hold", "tpd", "labels"])


class Chart(unittest.TestCase):
    def test_ticks_are_round_and_cover_the_range(self):
        self.assertEqual(walletchart.ticks(0, 11.86), [0, 5, 10])
        self.assertEqual(walletchart.ticks(-9.1, 11.2), [-5, 0, 5, 10])
        self.assertEqual(walletchart.ticks(-0.3, 0.2), [-0.2, 0, 0.2])

    def test_cut_line_only_inside_the_range(self):
        pts = [(NOW - 10 * D, 0), (NOW - 6 * D, 3.0), (NOW - 2 * D, 5.0), (NOW, 8.0)]
        html = walletchart.earnings(pts, cut=NOW - 5 * D)
        self.assertIn('class="cut"', html)
        self.assertIn("rez " + walletchart.day(NOW - 5 * D), html)
        self.assertIn('class="end"', html)
        self.assertNotIn('class="cut"', walletchart.earnings(pts, cut=NOW - 20 * D))
        self.assertNotIn('class="cut"', walletchart.earnings(pts))
        self.assertEqual(walletchart.earnings(pts[:1]), "")

    def test_strip_counts_and_wraps(self):
        html = walletchart.strip([True, False, True], NOW - D, NOW)
        self.assertEqual(html.count("<i"), 3)
        self.assertIn("2 u plusu · 1 u minusu", html)
        self.assertIn("repeat(3,", html)
        self.assertIn(f"repeat({walletchart.STRIP_COLS},", walletchart.strip([True] * 100))
        self.assertEqual(walletchart.strip([]), "")


def _w(addr, cs, labels=(), **st):
    s = {"closed_pnl_sol": 2.5, "win_rate": 0.6, "closed": 20, "median_hold_min": 240, "trades_per_day": 3,
         "roi_on_cost": 0.4, "top_trade_share": 0.2, "history_days": 18.6, "profit_factor": 3.1, "median_roi": 0.3,
         "big_wins": 4}
    s.update(st)
    return {"wallet": addr, "copy_score": cs, "score": cs, "tier": "A", "sources": {}, "labels": list(labels),
            "stats": s, "scored_at": NOW - 3600, "last_tx_ts": NOW - 7200}


class Words(unittest.TestCase):
    def test_plural_and_hold(self):
        self.assertEqual([pages._pl(n, "a", "b", "c") for n in (1, 2, 5, 11, 12, 21, 24, 31)],
                         ["a", "b", "c", "c", "c", "a", "b", "a"])
        self.assertEqual(pages._hold(264, full=True), "4 h 24 min")
        self.assertEqual(pages._hold(264), "4 h")
        self.assertEqual(pages._hold(5), "5 min")
        self.assertEqual(pages._hold(3 * 1440), "3 d")
        self.assertEqual(pages._hold(None), "–")

    def test_verdict_follows_the_autopilot_judgement(self):
        row = {"passed": 1, "closed_before": 16, "realized_before": 8.0, "win_before": 0.75, "closed_after": 15,
               "realized_after": 3.8, "win_after": 0.6, "cut": NOW - 5 * D, "as_of": NOW}
        word, kind, facts, say = pages._verdict(_w("P", 80), row, NOW)
        self.assertEqual((word, kind), ("Vrijedi kopirati", "good"))
        self.assertIn("dokazan dvaput · kopirljiv", facts)
        self.assertIn("+8,0 SOL na 16 zatvorenih, pa +3,8 SOL na 15", say)
        word, kind, _, say = pages._verdict(_w("O", 70), dict(row, passed=0, realized_after=-1.2), NOW)
        self.assertEqual((word, kind), ("Još nije dokazan", "warn"))
        self.assertIn("Poslije reza nije u plusu", say)
        word, kind, facts, say = pages._verdict(_w("S", 0, ["sniper"], median_hold_min=5), None, NOW)
        self.assertEqual((word, kind), ("Ne kopirati", "bad"))
        self.assertIn("nije kopirljiv", facts)
        self.assertIn("Drži medijan 5 min", say)
        self.assertIn("snajper", say)
        self.assertEqual(pages._verdict(_w("N", 70), None, NOW)[0], "Još nije dokazan")
        unscored = {"wallet": "U", "stats": {}, "labels": [], "copy_score": None}
        self.assertEqual(pages._verdict(unscored, None, NOW)[0], "Još nije ocijenjen")


class ListPage(unittest.TestCase):
    def setUp(self):
        self.ws = [_w("BEST", 90), _w("PROVEN", 60), _w("FOLLOWED", 55), _w("SNIPE", 0, ["sniper"], closed_pnl_sol=-6.3)]
        self.marks = {"proven": {"PROVEN": {"as_of": NOW - 3600, "bags": 2}}, "followed": {"FOLLOWED", "PROVEN"},
                      "recs": {"FOLLOWED": {"roi": 0.4, "win": 0.6, "closed": 5}}, "as_of": NOW - 3600}

    def render(self, qs):
        with mock.patch("ui.data.wallets", return_value=self.ws), \
                mock.patch("ui.preporuka.copies_from_strat", return_value={}), \
                mock.patch("ui.jobs.status", return_value=(None, None, "")), \
                mock.patch.object(pages, "_last_buy", return_value={"mint": "M1", "ts": NOW - 3600, "sol": 0.5, "sold": None}), \
                mock.patch.object(pages, "_syms_for", return_value={"M1": "GIGAFROG"}), \
                mock.patch.object(pages, "autopilot_marks", return_value=self.marks):
            return pages.wallets(qs)

    def test_hero_rows_and_columns(self):
        title, html = self.render({})
        self.assertEqual(title, "Novčanici")
        self.assertIn("Koga kopirati", html)
        hero = html[:html.index('class="ms-seg"')]
        self.assertIn("PROVEN", hero)                                  # the first proven of the recommendation order
        self.assertIn("<b>GIGAFROG</b>", hero)
        self.assertIn("još drži", hero)
        self.assertNotIn("Prijedlog za danas", html)                   # the box lives only on Pregled
        lst = html[html.index('class="ms-wl"'):]
        self.assertNotIn("SNIPE", lst)                                 # not on the copy list
        self.assertLess(lst.index("PROVEN"), lst.index("BEST"))        # 9.11. (P44): the bot's pick first
        self.assertIn("+40 %", lst)                               # Autopilot 14 d where it has a number
        self.assertIn('title="2 otvorenih gubitnika"', lst)
        self.assertIn('data-wf', html)                                 # the search field filters the rows
        self.assertIn('action=/run/wallets class="adm-only"', html)    # "Ocijeni sada" stays admin-only
        self.assertIn("/wallets?v=tablica", html)
        self.assertNotIn("ⓘ", html)

    def test_all_marks_bots_and_sorts(self):
        _, html = self.render({"v": "svi"})
        lst = html[html.index('class="ms-wl"'):]
        self.assertIn('<span class="warn">snajper</span>', lst)
        self.assertLess(lst.index("BEST"), lst.index("PROVEN"))        # Svi: copy_score order
        _, html = self.render({"v": "svi", "s": "zarada"})
        lst = html[html.index('class="ms-wl"'):]
        self.assertGreater(lst.index("SNIPE"), lst.index("BEST"))
        self.assertIn("Poredano po zaradi", html)

    def test_empty_copy_list(self):
        self.ws = [_w("SNIPE", 0, ["sniper"])]
        _, html = self.render({})
        self.assertIn("Trenutno nema koga kopirati", html)


class WalletPage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path, con = make_db(self.tmp)
        dokazani.run(con, NOW, log=None)
        con.execute("UPDATE wallets SET stats=?, score=70, copy_score=64, tier='A' WHERE wallet='PROVEN'",
                    (json.dumps(_w("PROVEN", 64)["stats"]),))
        con.commit()
        con.close()

    def render(self, addr, qs=None):
        from ui import data
        groups = dict(data.GROUPS)
        try:
            data.GROUPS["wallets"] = [self.path]
            data.GROUPS["hype"] = data.GROUPS["rug"] = data.GROUPS["paper"] = [os.path.join(self.tmp, "none.db")]
            with mock.patch.object(wstore, "DB", self.path), mock.patch("ui.pravitrade.followed_wallets", return_value={"PROVEN"}):
                return pages.wallet(addr, qs or {})
        finally:
            data.GROUPS.update(groups)

    def test_verdict_cut_and_more(self):
        title, html = self.render("PROVEN")
        self.assertTrue(title.startswith("Novčanik"))
        self.assertIn("Vrijedi kopirati", html)
        self.assertIn("rez " + walletchart.day(NOW - 5 * D), html)    # the cut line on the chart
        self.assertIn("prije reza", html)
        self.assertIn("Svaka zatvorena pozicija", html)
        self.assertIn("Zadnji tradeovi", html)
        self.assertIn("?v=pozicije", html)
        self.assertIn("Kako je dobio ocjenu 70", html)
        self.assertIn("copy ocjena 64", html)                          # the two scores differ: said once, one tap away
        self.assertIn('class="ms-h2 nosec"', html)                    # no section chips on this short page
        self.assertIn('data-m="PROVEN"', html)                         # copy the address
        self.assertNotIn("\U0001F4CB", html)                           # no emoji (the old clipboard icon)

    def test_not_copyable_and_unknown(self):
        _, html = self.render("BOT")
        self.assertIn("Ne kopirati", html)
        _, html = self.render("NOBODY")
        self.assertIn("nema u registru", html)

    def test_subpages(self):
        for v, words in (("ocjena", "Copy ocjena 64"), ("brojke", "medijan držanja"), ("registar", "Zašto je u registru"),
                         ("pozicije", "Sve pozicije"), ("povijest", "Povijest ocjena")):
            title, html = self.render("PROVEN", {"v": v})
            self.assertIn(words, html, v)
            self.assertIn('href="/wallet/PROVEN"', html, v)            # back to the wallet


if __name__ == "__main__":
    unittest.main()
