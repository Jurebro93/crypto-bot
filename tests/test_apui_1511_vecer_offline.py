"""15.11. navečer (owner, on his phone, the 3rd time): "Opet je stavka prekidači maksimizirana, a ne kako sam već 3 puta
rekao da se minimizira pa da se na klikom na karticu otvori tijela. Nestale su vrijednost voleta i ovo profit and
loss po danu. Kad kliknem na graf, otvori se preko cijelog ekrana na mobitelu kartica i onda ne mogu je zatvoriti, ne
mogu otvoriti drugi dan da vidim koliko sam zaradio, potrošio i tako dalje. I gdje mogu naći te nove liste
influencera velikih unutar alata."

1. "Prekidači" is ONE closed row (title, "N prekidača, X uključeno, Y čeka tebe", a badge while Grok waits); no
   open attribute, no address and no script opens it (data-tap); "Koga pratimo" is one closed row too
2. the wallet's value (SOL, $ and €, 24 h, danas, ukupno) and the PnL of the last days are back at the top, above the
   token's chart; a day's card has zarađeno / potrošeno / vraćeno / naknade / tradeovi (pnl-days per day)
3. the full-screen card always closes: × (44 px, top right, under the notch), the back button (history), Esc, the
   backdrop; a tap on the PnL chart opens the day's card under it, ‹ › move day by day
4. "Makro influenceri ↓" in the title row for the owner opens Postavke and the card (also before the pilot's data)

    python3 -m unittest tests.test_apui_1511_vecer_offline
"""
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.test_apterm_offline as at  # noqa: E402  (module import: its own test classes are not rerun here)
from league import copy  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import apterm, pravitrade  # noqa: E402

NOW = at.NOW
L = 1_000_000_000


def setUpModule():
    at.setUpModule()


def tearDownModule():
    at.tearDownModule()


def boot(body):
    return json.loads(re.search(r"<script type=application/json id=apx-first>(.*?)</script>", body, re.S).group(1)
                      .replace("<\\/", "</"))


class Page(at.Env):
    def page(self, user="Jure", qs=None):
        apterm.reset()
        return pravitrade.page(qs or {}, user)[1]

    def day0(self):
        return executor._day_start(NOW, "Europe/Zagreb")

    def closed(self, sin, back, fee, ts, sym):
        pid = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                               "qty_left, sol_back, closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (sym + "1" * (44 - len(sym)), sym, ts - 600, "live", "closed", "ručno", sin, 1000, 0, back,
                                ts, fee)).lastrowid
        return pid

    def order(self, ts, side, status, a_in, a_out, fee, pid=None):
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, "
                         "fee_lamports) VALUES (?,?,?,?,?,?,?,?,?)", (ts, pid, "T" * 44, side, "live", a_in, a_out,
                                                                      status, fee))

    def trades_today(self):
        """Today: a win (0,1 -> 0,13) and a loss (0,1 -> 0,08) closed, their buys and sales as orders, one failed buy
        that still paid its network fee; yesterday one more win."""
        t = max(self.day0() + 120, NOW - 60)
        w = self.closed(0.1, 0.13, 0.002, t, "WIN")
        lo = self.closed(0.1, 0.08, 0.001, t, "LOSS")
        self.closed(0.2, 0.25, 0.003, self.day0() - 7200, "YDAY")
        for pid in (w, lo):
            self.order(t - 30, "buy", "ok", int(0.1 * L), 1000, 500_000, pid)
        self.order(t - 20, "sell", "ok", 1000, int(0.13 * L), 1_000_000, w)
        self.order(t - 10, "sell", "ok", 1000, int(0.08 * L), 1_000_000, lo)
        self.order(t - 5, "buy", "failed", int(0.1 * L), None, 200_000)
        self.con.commit()


class Prekidaci(Page):
    def test_one_closed_row_by_default_with_a_summary(self):
        body = self.page("Jure", {"sve": "1"})
        sw = body[body.index("<section class=apx-swsec id=prekidaci"):body.index("id=apx-ostalo")]
        self.assertTrue(sw.startswith('<section class=apx-swsec id=prekidaci aria-label="Prekidači"><details '
                                      'class="apx-acc apx-sws" id=prekidaci-d data-tap><summary><h2 class=apx-swh '
                                      'data-sec="">Prekidači</h2>'), sw[:200])
        self.assertNotRegex(sw, r"<details[^>]*\sopen[\s>]")                 # nothing inside comes open either
        # 16.11.: the closed card says the state of the real money in words, not a count of switches
        self.assertRegex(sw, r'<span class="apx-mut apx-swsum">(Pravi novac: (uključen|isključen)|Zaustavljeno)[^<]*</span>')
        self.assertNotIn("apx-swbadge", sw)                                    # nothing waits for him
        for k in ("id=sw-pravi", "id=sw-autopilot", "name=name value=pravi_novac_sve"):   # the content is folded inside
            self.assertIn(k, sw, k)
        # the chip in the title row targets the section around the card (an address never opens a details there)
        self.assertIn('href="#prekidaci" id=apx-swchip>Prekidači ↓</a>', body)

    def test_counts(self):
        cfg = pravitrade._cfg(self.con)
        n, n_on, n_wait = apterm.switches_count(self.con, cfg, True, NOW)
        # every owner switch (the moonshot exception is part of the microcap row), Grok autotrade, the Autopilot
        self.assertEqual(n, len([x for x in settings.OWNER_SWITCHES if x in settings.FLAGS
                                 and x != settings.MIKROKAP_MOON]) + 2)
        settings.set_flag(self.con, settings.SWITCH_ALL, "live", "Jure")
        self.assertEqual(apterm.switches_count(self.con, cfg, True, NOW)[1], n_on + 1)
        self.assertEqual(n_wait, 0)
        self.assertEqual(apterm.switches_summary(16, 2, 1), "16 prekidača, 2 uključena, 1 čeka tebe")
        self.assertEqual(apterm.switches_summary(21, 1, 0), "21 prekidač, 1 uključen")
        self.assertEqual(apterm.switches_summary(5, 5, 0), "5 prekidača, 5 uključeno")

    def test_no_address_and_no_script_opens_it(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("details:not([data-tap])", pravitrade.TOGGLE_JS)        # TOGGLE_JS reveal()
        self.assertIn("details:not([data-tap])", js)                         # the same, inside the page's ap.js
        self.assertIn("p.tagName === 'DETAILS' && !p.hasAttribute('data-tap')", js)   # ap.js scrollHash
        self.assertIn("t.closest('details[data-tap]:not([open])')", js)       # scrolls to the closed row instead
        with open(apterm.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn(" open_=True", src.split("def switches_html")[1].split("def _fold")[0])

    def test_koga_pratimo_is_one_closed_row(self):
        copy.follow(self.lg, settings.LEAGUE_USER, "wallet", "W" * 44, "", 25, 5, "tpsl", "15%", "-20%")
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")
        self.lg.commit()
        html = apterm.lazy("pratimo", "Jure")
        self.assertTrue(html.startswith("<details class=apx-cd id=apx-pratimo-d><summary>"), html[:80])
        self.assertIn('<span class="apx-mut apx-cdsum">1 wallet, 1 influencer</span></summary>', html)
        self.assertNotIn("<details class=apx-cd id=apx-pratimo-d open", html)


class WalletAtTheTop(Page):
    def test_value_dollars_euros_and_pnl_by_day_above_the_chart(self):
        self.trades_today()
        body = self.page()
        top = body[body.index("id=apx-wtop"):body.index("id=apx-chartbox")]
        self.assertLess(body.index("id=apx-wtop"), body.index("id=apx-chartbox"))   # above the token's chart
        self.assertIn('<b class=apx-wbig data-w=value>1,815<small>SOL</small></b>', top)   # SUMMARY: 1,815 SOL
        self.assertIn("≈ 309 $ · 265 €", top)                                 # 1,815 × 170 $ × 0,86 €/$
        self.assertIn("<i>24 h</i><b class=\"up\">+0,029\xa0SOL</b>", top)
        self.assertIn("<i>Ukupno</i><b class=\"up\">+0,065\xa0SOL</b><small>+3,7\xa0%</small>", top)
        self.assertIn("<i>Danas</i>", top)
        self.assertEqual(top.count("class=apx-dchip"), apterm.WTOP_DAYS)      # the last 7 days, newest first
        first = re.search(r'class=apx-dchip data-day="([0-9-]+)"', top).group(1)
        self.assertEqual(first, apterm._pnl_day_of(NOW, "Europe/Zagreb"))
        self.assertIn("<span>danas</span><b class=\"up\">+0,0070\xa0SOL</b><small>2 tradea</small>", top)
        self.assertIn('data-fs-open=apx-port data-pv-set=days>Graf i svi dani</button>', top)
        self.assertIn("<div class=apx-dcard id=apx-hday hidden aria-live=polite></div>", top)
        # the day cards read the page's JSON: live, 30 days, with what was spent, came back and the fees
        days = boot(body)["days"]
        self.assertEqual((days["mode"], days["days"], len(days["rows"])), ("live", 30, 30))
        self.assertEqual(days["rows"][-1]["day"], first)

    def test_a_viewer_sees_the_value_too_the_owner_alone_the_makroinf_chip(self):
        body = self.page("Ivan")
        self.assertIn("id=apx-wtop", body)
        self.assertNotIn("id=apx-mkchip", body)

    def test_no_history_the_plain_balance_and_no_crash(self):
        self.mods(None, at.fake_aplog())                                        # no trade.equity at all
        with mock.patch.object(pravitrade, "_balance", lambda addr: 0.5):
            body = self.page()
        top = body[body.index("id=apx-wtop"):body.index("id=apx-chartbox")]
        self.assertIn("0,500<small>SOL</small>", top)


class DayCard(Page):
    def test_pnl_days_has_spent_back_fees_and_the_trades_of_each_day(self):
        self.trades_today()
        with mock.patch.object(apterm, "_sol_usd", lambda tcon: 200.0):
            d = apterm.pnl_days("Jure", "live", 30, now=NOW)
        t = d["rows"][-1]
        self.assertAlmostEqual(t["pnl_sol"], 0.007)                           # unchanged: back - in - fees
        self.assertEqual((t["n_buys"], t["n_sells"]), (2, 2))                 # the failed buy spent nothing
        self.assertAlmostEqual(t["spent_sol"], 0.2)
        self.assertAlmostEqual(t["back_sol"], 0.21)
        self.assertAlmostEqual(t["fees_all_sol"], 0.0032)                      # every order's fee, the failed one too
        self.assertAlmostEqual(t["spent_usd"], 40.0)
        self.assertEqual([x["sym"] for x in t["trades"]], ["WIN", "LOSS"])    # the biggest result first
        self.assertEqual((t["trades"][0]["in"], t["trades"][0]["back"], t["trades"][0]["pct"]), (0.1, 0.13, 28.0))
        y = d["rows"][-2]
        self.assertEqual((y["n"], y["n_buys"], [x["sym"] for x in y["trades"]]), (1, 0, ["YDAY"]))
        empty = d["rows"][0]
        self.assertEqual((empty["n"], empty["n_buys"], empty["trades"], empty["spent_sol"]), (0, 0, [], 0.0))

    def test_paper_days_spent_in_dollars(self):
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, ret, "
                        "source) VALUES (?,?,?,?,?,?,?,?,?,?)", (settings.LEAGUE_USER, "D" * 44, "DEMO", NOW - 300, NOW - 60,
                                                                 "closed", 25.0, 5.0, 0.2, "copy"))
        self.lg.commit()
        with mock.patch.object(apterm, "_sol_usd", lambda tcon: 200.0):
            t = apterm.pnl_days("Jure", "paper", 7, now=NOW)["rows"][-1]
        self.assertEqual((t["n_buys"], t["spent_usd"], t["back_usd"]), (1, 25.0, 30.0))
        self.assertEqual(t["trades"][0]["pnl"], 5.0)
        self.assertIsNone(t["fees_all_sol"])

    def test_the_card_in_the_page_script(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        for k in ("function dayHtml(", "'Zarađeno (neto)'", "'Potrošeno na kupnje'", "'Vraćeno iz prodaja'", "'Naknade'",
                  "data-dnav=-1 aria-label=\"Dan prije\"", "data-dnav=1 aria-label=\"Dan poslije\"",
                  "data-dclose aria-label=\"Zatvori dan\"", "function portDay(", "function dayList(",
                  "pick: i => { if (PN.j && PN.j.rows[i]) portDay(PN.j.rows[i].day); }"):
            self.assertIn(k, js, k)
        # a pinned box over the chart goes away with a tap outside it; a touch screen gets the day's card instead
        self.assertIn("document.addEventListener('pointerdown', away, true)", js)
        self.assertIn("const quiet = () => !!o.pick && coarse()", js)


class FullScreen(Page):
    def test_close_button_backdrop_back_button_and_esc(self):
        body = self.page()
        port = body[body.index("id=apx-port"):]
        port = port[:port.index("</section>")]
        self.assertIn('<button type=button class=apx-fsbtn data-fs-open=apx-port aria-label="Portfelj preko cijelog '
                      'zaslona">Cijeli zaslon</button>', port)
        self.assertIn('<button type=button class=apx-fsx data-fs-close aria-label="Zatvori cijeli zaslon" title="Zatvori '
                      '(Esc)">×</button>', port)
        self.assertIn("<div class=apx-dcard id=apx-day hidden aria-live=polite></div>", port)
        self.assertIn("<div class=apx-dlist id=apx-dlist hidden></div>", port)
        chart = body[body.index("id=apx-chartbox"):body.index("id=apx-chart ")]
        self.assertIn("data-fs-open=apx-chartbox", chart)
        self.assertIn("class=apx-fsx data-fs-close", chart)
        self.assertIn("<div class=apx-fsbg data-fs-close hidden></div>", body)  # the backdrop: a tap closes
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        for k in ("history.pushState(Object.assign({}, history.state || {}, { apxFs: id }), '')",
                  "addEventListener('popstate', () => {",
                  "if (FS.el && !(history.state && history.state.apxFs)) fsClose(true);",
                  "if (FS.pushed && !fromPop) history.back();",
                  "if (e.key === 'Escape' && FS.el) { e.preventDefault(); fsClose(); }",
                  "if ((b = g('[data-fs-close]'))) { fsClose(); return; }"):
            self.assertIn(k, js, k)
        css = apterm.CSS
        rule = css[css.index(".apx-card.is-fs .apx-fsx{"):]
        rule = rule[:rule.index("}")]
        for k in ("position:absolute", "top:8px", "right:0", "width:44px", "height:44px"):
            self.assertIn(k, rule, k)
        self.assertIn("top:max(48px,calc(env(safe-area-inset-top,0px) + 40px))", css)
        self.assertIn(".apx-card.is-fs>.apx-cbar:first-child{position:sticky;top:0", css)

    def test_the_pop_up_closes_with_the_back_button_too(self):
        # the other card that covers a phone's screen (dialog#ap-pop): one history entry while open, a sticky Zatvori
        js, css = pravitrade.POP_JS, pravitrade.POP_CSS
        self.assertIn("history.pushState(Object.assign({},history.state||{},{apPop:1}),'')", js)
        self.assertIn("addEventListener('popstate',()=>{if(d.open&&!(history.state&&history.state.apPop)){pushed=0;d.close()}})", js)
        self.assertIn("if(pushed){pushed=0;history.back()}", js)
        self.assertIn("d.addEventListener('click',e=>{if(e.target===d)d.close()})", js)   # a tap beside it
        self.assertIn("position:sticky;top:0", css)
        self.assertIn('class=ap-popx onclick="this.closest(\'dialog\').close()" aria-label="Zatvori">Zatvori ×</button>',
                      pravitrade.POP_HTML)


class MakroInfluenceri(Page):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"MAKROINF_DB": os.path.join(self.tmp.name, "nema", "makroinf.db")})
        p.start()
        self.addCleanup(p.stop)

    def test_chip_for_the_owner_and_the_card_under_postavke_before_any_data(self):
        body = self.page()
        top = body[:body.index("id=apx-wtop")]
        self.assertIn('<a class="apx-state apx-mkchip" href="#makroinf" id=apx-mkchip>Makro influenceri ↓</a>', top)
        ost = apterm.lazy("ostalo", "Jure")
        self.assertIn("<details class=ap-sec id=makroinf>", ost)
        self.assertIn("pilot: prvi krug još nije spremio račune", ost)
        self.assertNotIn("id=makroinf", apterm.lazy("ostalo", "Ivan"))
        # the public pages stay behind the owner switch (off): nothing here turns them on
        self.assertEqual(settings.flag_state(self.con)[settings.MAKROINF_JAVNO]["mode"], "off")


if __name__ == "__main__":
    unittest.main()
