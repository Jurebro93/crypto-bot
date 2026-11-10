"""The calm Autopilot page of 10.11. (Jure: "Ostalo mi se sviđa", prijedlog dizajna 3.4, maketa
audit/2026-11-10/makete/autopilot.html): the helpers that put this page into the shared language of ui/redak.py
(rows that open on a tap, a token row that opens the Autopilot's own pop-up, whom a position copies, settings with a
decimal comma), the title row with the switch, the state line with "Dovrši", positions as rows, the honest influencer
recommendations, five type sizes and no emoji. No network; trade.equity and trade.aplog are the fakes of
tests/test_apui_offline.py.

    python3 -m unittest tests.test_autopilot_izgled_offline
"""
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store  # noqa: E402
from tests.test_apui_offline import Base, SUMMARY, fake_aplog, fake_equity, history  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import pravitrade  # noqa: E402

NOW = int(time.time())
NB = " "
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():   # follows wake the copy loop; never the repo's own .copy_wake
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


class Helpers(unittest.TestCase):
    def test_who_a_position_copies(self):
        w = pravitrade._who
        self.assertEqual(w("copy KOL ansem"), "@ansem")
        self.assertEqual(w("copy KOL tg:alpha_calls · pokušaj 2"), "alpha_calls")
        self.assertEqual(w("copy wallet 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"), "wallet 7xKX…gAsU")
        self.assertEqual(w("copy ekipa murad, tg:alpha"), "ekipa murad, tg:alpha")
        self.assertEqual(w("ručno (pravi trade)"), "ručno")
        self.assertEqual(w("kopija @VELORA_GEMS"), "@VELORA_GEMS")
        self.assertEqual(w("paper #12"), "demo strategija")
        self.assertIsNone(w("transakcija nije stigla u blok"))   # an error is not a source: said in full instead
        self.assertIsNone(w(None))

    def test_settings_with_a_decimal_comma(self):
        self.assertEqual(pravitrade._g(0.05), "0,05")
        self.assertEqual(pravitrade._g(0.005), "0,005")
        self.assertEqual(pravitrade._g(1), "1")
        self.assertEqual(pravitrade._g(1.5), "1,5")
        self.assertEqual(pravitrade._fiat(311.2), "311")
        self.assertEqual(pravitrade._fiat(12.4), "12,40")
        self.assertEqual(pravitrade._fiat(1234), f"1{NB}234")

    def test_signed_numbers_carry_their_colour(self):
        self.assertEqual(pravitrade._signed(0.029), f'<span class="pos">+0,029{NB}SOL</span>')
        self.assertEqual(pravitrade._signed(-3.71, 1, "%"), f'<span class="neg">−3,7{NB}%</span>')
        self.assertEqual(pravitrade._signed(0), f"0,000{NB}SOL")

    def test_a_section_is_the_shared_row_with_the_arrow_and_no_link(self):
        html = pravitrade._sec("Koga prati", "@ansem i još 2", "<p>unutra</p>", sid="pratim", value="3")
        self.assertTrue(html.startswith('<details class=ap-sec id=pratim><summary><div class="ms-row">'))
        self.assertIn('<div class="ms-t">Koga prati</div><div class="ms-s">@ansem i još 2</div>', html)
        self.assertIn('<div class="ms-v mut">3</div>', html)
        self.assertIn('<span class="ms-chev" aria-hidden="true"></span></div></summary>', html)
        self.assertNotIn("<a ", html.split("</summary>")[0])   # the tap opens the section, it never leaves the page
        self.assertIn("<div class=in><p>unutra</p></div></details>", html)
        item = pravitrade._item("GIGA", "prije 3 h", "x", value="0,050 SOL", sub="drži 50 %", iid="poz-7")
        self.assertTrue(item.startswith("<details class=ap-it id=poz-7><summary>"))   # an id: it stays open on refresh

    def test_a_token_row_opens_the_autopilots_own_popup(self):
        html = pravitrade._prow("Tok1xyz", name="AAA", reason="zove @ansem", value="50k $")
        self.assertIn('data-pop="/pravi-trade/token?m=Tok1xyz"', html)
        self.assertNotIn("data-mint", html)                    # not the evidence pop-up of the other pages
        self.assertIn('class="ms-row ms-tap"', html)
        self.assertNotIn("data-pop", pravitrade._prow("", name="–"))

    def test_title_switch_keeps_its_form_and_confirmation(self):
        off, on = pravitrade._switch_html(False), pravitrade._switch_html(True)
        self.assertIn("<span>Isključen</span>", off)
        self.assertIn('<input type=hidden name=on value=1><button class=ap-sw role=switch aria-checked=false', off)
        self.assertIn("confirm('Uključiti Autopilot? Bot će SAM kupovati pravim SOL-om", off)
        self.assertIn("<span>Uključen</span>", on)
        self.assertIn('name=on value=0><button class="ap-sw on" role=switch aria-checked=true', on)
        self.assertIn("confirm('Isključiti Autopilot? Nove kupnje staju odmah", on)
        for h in (on, off):
            self.assertIn("action=/pravi-trade/switch", h)
        self.assertIn("confirm('Prodati SVE otvorene pozicije odmah i isključiti Autopilot?')", pravitrade.SELL_ALL)
        self.assertIn("action=/pravi-trade/sellall", pravitrade.SELL_ALL)

    def test_five_type_sizes_and_no_emoji_in_the_page_css(self):
        sizes = {int(x) for x in re.findall(r"font-size:(\d+)px", pravitrade.CSS)}
        self.assertLessEqual(sizes, {13, 15, 17, 22, 34})
        self.assertNotIn("✓", pravitrade.CSS)


class Page(Base):
    def _follow(self, kind="kol", target="ansem"):
        copy.follow(self.lg, settings.LEAGUE_USER, kind, target, "", 25, 5, "tpsl", "15%", "-20%")
        self.lg.commit()

    def test_order_of_the_mock_up_and_no_chip_bar(self):
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        _, body = pravitrade.page({}, "Jure")
        # 10.11. (Jure): the floating menu first, "Brza kupnja" right under the chart, not under "Kako trguje"
        nav_end = body.index("</nav>", body.index("class=ap-fn"))   # the menu's own words ("Pravila", "Još") come first
        at = [body.index(k, nav_end) for k in ('id="apc-ap"', ">Brza kupnja<", ">Dnevnik odluka<", ">Otvorene pozicije<",
                                      ">Kako trguje<", ">Koga prati<", ">Pravila<", ">Još<", ">Tko sada zove koji token<",
                                      ">Wallet i uplata<", ">Tko vidi stranicu<", ">Kako je zaštićeno<")]
        self.assertEqual(at, sorted(at))
        self.assertEqual(len(re.findall(r"<h2 class=ms-h2[^>]*>", body)), body.count('data-sec=""'))   # no secnav chips
        self.assertIn('class="ap ms-page"', body)

    def test_no_emoji_and_no_capital_shouting_on_the_page(self):
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        os.environ["TRADE_LIVE"] = "1"
        self.addCleanup(os.environ.pop, "TRADE_LIVE", None)
        _, body = pravitrade.page({"ok": "Spremljeno."}, "Jure")
        frag = pravitrade.dnevnik_fragment("Jure") + pravitrade.positions_fragment("Jure")
        for ch in ("✓", "✕", "🔒", "⚠", "⛔", "🟡", "🛑", "⏸", "ⓘ", "UKLJUČEN", "ISKLJUČEN", "PRESKOČIO", "KUPIO"):
            self.assertNotIn(ch, body + frag, ch)
        self.assertIn('<p class="ap-w ok">Spremljeno.</p>', body)   # the answer to a form, as a line with a dot

    def test_state_line_says_finish_the_setup_to_the_owner_only(self):
        self.mods(fake_equity(history(), SUMMARY), None)
        html = pravitrade.head_fragment("Jure")
        self.assertIn('<a href="#postavljanje">Dovrši 1/4</a>', html)   # SOL is there, address and key are not
        self.assertNotIn("Dovrši", pravitrade.head_fragment("Ivan"))
        settings.put(self.con, "wallet_pub", "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin")
        with mock.patch.object(executor, "armed", lambda: True):
            pravitrade._EQ.update(ts=0.0)
            self.assertNotIn("Dovrši", pravitrade.head_fragment("Jure"))   # address, SOL (1,772) and key: ready
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("<details class=ap-sec id=postavljanje>", body)
        self.assertIn("Postavljanje walleta", body)
        self.assertIn(f"1,772{NB}SOL · 9xQe", body)   # the wallet row: balance from the value history, short address

    def test_positions_are_rows_that_open_the_sell_buttons(self):
        cfg = settings.merged({"size_sol": 0.05, "max_open": 5, "on": True}, self.con)
        cfg["on"] = True
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                         "qty_left) VALUES ('MINTA','GIGA',?,'live','open','copy KOL ansem',0.05,100,50)", (NOW - 3 * 3600,))
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, sol_back, "
                         "qty_raw, qty_left, closed_ts, fees_sol) VALUES ('MINTB','WIF',?,'dry','closed',NULL,0.05,0.07,"
                         "100,0,?,0.002)", (NOW - 9 * 3600, NOW - 8 * 3600))
        self.con.commit()
        inner, meta, has_open = pravitrade.positions_inner(self.con, False, True, {}, cfg)
        self.assertEqual((meta, has_open), ("1 od 5", True))
        self.assertIn("<details class=ap-it id=poz-1><summary>", inner)
        self.assertIn(f'<div class="ms-v">0,050{NB}SOL</div><div class="ms-s">drži 50{NB}%</div>', inner)
        self.assertIn("@ansem · prije 3 h", inner)
        self.assertIn("name=frac value=0.2", inner)            # the sell buttons are inside the row
        self.assertIn('data-pop="/pravi-trade/token?m=MINTA"', inner)   # ... and the live check one more tap
        self.assertIn("<details class=ap-it id=zatvorene>", inner)
        self.assertIn(f'class="ms-v pos">+0,0180{NB}SOL', inner)
        self.assertIn("probno", inner)                          # live and trial listed together: the trial one says so
        self.assertTrue(inner.endswith(pravitrade.SELL_ALL))    # red, under the positions
        guest, _, _ = pravitrade.positions_inner(self.con, True, False, {}, cfg)
        self.assertNotIn("/pravi-trade/sell", guest)
        self.assertIn("Kupi i ti", guest)
        cfg["on"] = False
        self.con.execute("UPDATE positions SET status='closed' WHERE id=1")
        self.con.commit()
        off, meta, _ = pravitrade.positions_inner(self.con, False, True, {}, cfg)
        self.assertNotIn("/pravi-trade/sellall", off)           # off and nothing open: no red button (as before)
        self.assertEqual(meta, "0 od 5")
        self.assertIn('<span hidden data-meta="#ap-pos-n">', pravitrade.positions_fragment("Jure"))

    def test_rules_row_says_the_stake_target_and_todays_spend(self):
        cfg = settings.merged({"size_sol": 0.05, "max_sol_per_day": 1.0, "max_open": 5, "min_sol_reserve": 0.05,
                               "max_cost_pct": 6, "max_loss_day": 0.3}, self.con)
        html = pravitrade._rules(self.con, cfg, True)
        self.assertIn(f"ulog 0,05 SOL · cilj +15 % · stop −60 % · danas 0,00 od 1 SOL", html)
        self.assertLess(html.index("id=cilj"), html.index("id=limiti"))
        self.assertIn("Spremi limite", html)
        self.assertNotIn("Spremi limite", pravitrade._rules(self.con, cfg, False))


class KolRecommendations(unittest.TestCase):
    """Jure 10.11. (the influencer ranking made honest) with the shared verdict word on every row."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.lg = store.connect(os.path.join(d, "league.db"))
        copy.ensure(self.lg)

    def tearDown(self):
        self.lg.close()

    def section(self, rows):
        from ui import autopilot
        with mock.patch.object(autopilot, "kol_recs", lambda now=None: {14: rows}), \
                mock.patch.object(pravitrade, "followed_targets", lambda con: set()):
            return pravitrade._kol_section(self.lg, True)

    def test_the_rows_own_verdict_and_can_copy_win(self):
        rows = [{"handle": "slowpoke", "live": True, "can_copy": False, "verdict": "drži se", "verdict_key": "drzi_se",
                 "why": "w", "s": {"hit": 0, "n": 0, "score": 0.9, "mjera": "minutna", "minute": {"n": 12, "hit10": 0.7}}},
                {"handle": "quick", "live": True, "can_copy": True, "verdict": "samo brzo", "verdict_key": "samo_brzo",
                 "why": "w", "s": {"hit": 0, "n": 0, "score": 0.6, "mjera": "minutna", "minute": {"n": 11, "hit10": 0.55}}}]
        html = self.section(rows)
        self.assertIn("najbolji 14 d: @quick · samo brzo", html)   # never the one the bot cannot copy in time
        self.assertIn('<span class="ms-dot warn" aria-hidden="true"></span>samo brzo · 11 poziva · uživo', html)
        self.assertIn('<span class="ms-dot good" aria-hidden="true"></span>drži se', html)
        self.assertLess(html.index("Dobri, ali prespori"), html.index("@slowpoke"))
        self.assertEqual(html.count("Prati pravim novcem"), 1)

    def test_nobody_live_and_measured_says_so(self):
        rows = [{"handle": "wick", "live": True, "verdict": "premalo poziva", "verdict_key": "premalo", "why": "w",
                 "s": {"hit": 0.5, "n": 4, "score": 0.3, "mjera": "fitilj"}}]
        html = self.section(rows)
        self.assertIn("nijedan praćeni uživo još nema", html)
        self.assertNotIn("najbolji 14 d", html)
        self.assertIn("premalo minutnih poziva", html)
        self.assertNotIn('<div class="ms-v">', html.split("@wick")[1].split("</summary>")[0])   # no percentage


class QuickBuyAndMenu(Base):
    """10.11. (Jure): quick buy right under the chart, and a floating menu to the parts of the page."""

    def test_owner_sees_quick_buy_under_the_chart_and_the_menu(self):
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        _, body = pravitrade.page({}, "Jure")
        self.assertLess(body.index('id="apc-ap"'), body.index("id=kupi-odmah"))
        self.assertLess(body.index("id=kupi-odmah"), body.index(">Dnevnik odluka<"))
        nav = body[body.index("class=ap-fn"):body.index("</nav>", body.index("class=ap-fn"))]
        for sid in ("#ap-head", "#kupi-odmah", "#dnevnik", "#pozicije", "#pratim", "#pravila", "#jos"):
            self.assertIn(f'href="{sid}"', nav)
            self.assertIn(f"id={sid[1:]}", body)                   # every link has its target on the page
        self.assertEqual(body.count("action=/pravi-trade/buy"), 1)   # one buy form, not two

    def test_viewer_gets_the_menu_without_buy(self):
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        settings_mod = pravitrade.settings
        con = pravitrade._tcon()
        try:
            settings_mod.put(con, "viewers", ["Ivan"], "Jure")
        finally:
            con.close()
        _, body = pravitrade.page({}, "Ivan")
        if "class=ap-fn" in body:
            nav = body[body.index("class=ap-fn"):body.index("</nav>", body.index("class=ap-fn"))]
            self.assertNotIn("#kupi-odmah", nav)
        self.assertNotIn("action=/pravi-trade/buy", body)


if __name__ == "__main__":
    unittest.main()
