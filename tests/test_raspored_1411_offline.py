"""14.11. (Jure, the Autopilot's layout): "I ove grokove prekidače, sve napravi dolje na dnu kartice, ono prekidači, a
grokove sve pozicije ubaci dolje u pozicije samo uz tag da je pokrenuo sam program ili ručno. Dakle, na vrhu treba biti
odmah graf, brza kupovina i pozicije ... a svi prekidači i sve ostalo treba biti na dnu stranice ... I taj prekidač ...
želim da se nađe na dnu stranice u sekciji prekidači." 12:55: "nema nekakvog narančastog okvira" (a chip at the top
leads to the switches).

1. top to bottom: the chart, Brza kupnja (the order panel), Pozicije, Portfelj, the cards, Prekidači, Postavke last;
   nothing of Grok above the chart (a pending request is one line there that leads to its card at the bottom)
2. Pozicije is one list of collapsed rows, Grok's among them, each tagged who opened it (ui/apterm.opened_by):
   "program · Grok", "program · range scalp", "ručno", "ručno · Grok prijedlog"; Grok's thesis and MemeSonar's
   evidence inside the opened row, with the same Zatvori / Uredi SL-TP as every row
3. Prekidači: pravi_novac_sve, Grok's requests, Grok autotrade (state, Ugasi / Uključi, limits), the Autopilot, the
   owner's other switches (exit_plan_live ...) and the exit plans' kill switch; Postavke no longer carries them
4. a viewer sees the tags and the states, no button; a reload stays at the top, the phone's panel is on the page

    python3 -m unittest tests.test_raspored_1411_offline
"""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_grokcard_1311_offline import MINT, Card  # noqa: E402
from trade import settings  # noqa: E402
from ui import apterm, grokauto, mcpapi, pravitrade  # noqa: E402

MAN = "Manu1111111111111111111111111111111111pump"
APR = "Aprv1111111111111111111111111111111111pump"
RNG = "Rnge1111111111111111111111111111111111pump"
REQ = "Reqq1111111111111111111111111111111111pump"


class Layout(Card):
    def demo(self, tok, sym, mcap, src, rule=None):
        return self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, source, entry_px, "
                               "entry_eff, entry_mcap, qty, auto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (settings.LEAGUE_USER, tok, sym, int(time.time()) - 900, "open", 25, src, mcap / 1e9,
                                mcap / 1e9, mcap, 25.0, json.dumps(rule or {"mode": "tpsl", "tp": "+30%", "sl": "-40%",
                                                                            "tp_in": "30%", "sl_in": "-40%"}))).lastrowid

    def pos(self, tok, sym, src, lid, reason=None):
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                         "league_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (tok, sym, int(time.time()) - 600, "live", "open", reason or src, 0.1, 1000, 1000, lid))
        self.con.commit()

    def others(self):
        """The owner's manual buy, a Grok request he approved, a range scalp lot (its round's profile)."""
        from rangedca import trade as rtrade
        self.pos(MAN, "GIGA", "ručno (pravi trade)", self.demo(MAN, "GIGA", 340_000.0, "ručno (pravi trade)"))
        self.pos(APR, "APRV", grokauto.APPROVED_SRC, self.demo(APR, "APRV", 55_000.0, grokauto.APPROVED_SRC))
        rid = self.demo(RNG, "RANGE", 1_390_000.0, "range lot 1")
        self.lg.executescript(rtrade.SCHEMA)
        self.lg.execute("INSERT INTO range_rounds (user, token, symbol, opened_ts, status, lot1_id, levels) VALUES "
                        "(?,?,?,?,?,?,?)", (settings.LEAGUE_USER, RNG, "RANGE", int(time.time()) - 700, "open", rid,
                                            json.dumps({"profile": "scalp"})))
        self.lg.commit()
        # a restart's note in the reason: the demo trade's source still says who opened it
        self.pos(RNG, "RANGE", "range lot 1", rid, reason="usklađeno s lancem nakon restarta (SOL ulog = zapisana namjera)")

    def page(self, user="Jure", qs=None):
        apterm.reset()
        return pravitrade.page(qs or {}, user)[1]

    @staticmethod
    def row(body, tok):
        i = body.index(f'data-tok="{tok}"')
        start = body.rindex("<details", 0, i)
        return body[start:body.index("</details>", i)]

    # ---- 1. the order -------------------------------------------------------------------------------------------

    def test_chart_brza_kupnja_and_pozicije_on_top_switches_and_settings_at_the_bottom(self):
        self.scenario(time.time())
        body = self.page()
        at = [body.index(k) for k in ("<h1>Autopilot</h1>", "id=apx-chartbox", "id=kupi-odmah", ">Brza kupnja<",
                                      "id=pozicije", "id=nalozi", "id=apx-port", "id=kupiti", "id=pratimo",
                                      "id=prekidaci", ">Prekidači<", "id=fl-pravi-novac", "id=grok-auto",
                                      "id=sw-autopilot", "id=exit-planovi", "id=apx-ostalo")]
        self.assertEqual(at, sorted(at))
        top = body[:body.index("id=apx-chartbox")]
        for k in ("Grokove pozicije", "id=grok-auto", "Ugasi Grok autotrade", "id=mcp-zahtjevi", "id=fl-pravi-novac"):
            self.assertNotIn(k, top, k)                                   # nothing of the switches above the chart
        # 12:55: one chip in the title row leads down to the switches
        self.assertIn('href="#prekidaci" id=apx-swchip>Prekidači ↓</a>', top)
        self.assertEqual(body.count("action=/pravi-trade/buy"), 1)         # one panel: on the page and the phone's sheet
        self.assertIn("data-sheet-full>Wallet, tvoja pozicija, DCA razine i limiti</button>", body)
        self.assertIn('<div class=apx-side-ph aria-hidden=true></div>', body)
        self.assertLess(body.index("id=kupi-odmah"), body.index('class="apx-main apx-m2"'))

    def test_the_chip_says_while_the_real_money_switch_is_on(self):
        settings.set_flag(self.con, settings.SWITCH_ALL, "live", "Jure")
        top = self.page()
        top = top[:top.index("id=apx-chartbox")]
        self.assertIn('<a class="apx-state apx-swchip warn" href="#prekidaci" id=apx-swchip>Prekidači · pravi novac '
                      'uključen ↓</a>', top)

    # ---- 2. one list, tagged ------------------------------------------------------------------------------------

    def test_grok_position_is_a_row_of_pozicije_tagged_program_with_its_why_and_the_same_buttons(self):
        self.scenario(time.time())
        body = self.page()
        pos = body[body.index("id=pozicije"):body.index("id=nalozi")]
        row = self.row(pos, MINT)
        self.assertTrue(row.startswith('<details class="apx-pos apx-pr is-grok" id=poz-'), row[:80])   # closed till tapped
        summ = row[:row.index("</summary>")]
        self.assertIn('<span class="apx-by prog" data-by="program" title="Otvorio program sam (automatska strategija)">'
                      'program · Grok</span>', summ)
        self.assertIn(f'data-sel="{MINT}"', summ)                                     # a tap loads its chart
        self.assertIn("<i class=apx-pw>ulaz </i>$82.0k", summ)                        # the phone's line: entry MC,
        self.assertIn('data-l="PnL" data-f=pnl>+10,0', summ)                          # PnL (live by data-key)
        self.assertIn("<span class=apx-px>SL −12 % · TP +15 % · BE nakon TP1</span>", summ)   # and the exit in words
        opened = row[row.index("</summary>"):]
        for k in ("<h4>Grokova teza</h4>", "momentum, tri callera", "<h4>Što MemeSonar vidi", "<b>proturječi</b>",
                  "postavio Grok (set_exit_plan)", "<span>Krugovi danas</span>", "Zatvori 50 %", "Zatvori 100 %",
                  "Uredi SL-TP", "action=/pravi-trade/sell", "action=/pravi-trade/exit"):
            self.assertIn(k, opened, k)
        self.assertIn('<span>Izvor<span class="tip apx-i"', opened)
        self.assertNotIn('<details class="apx-gp"', body)                              # no second Grok list
        self.assertNotIn("Uredi SL-TP ili prodaj (u Pozicijama)", body)
        # the JSON's tables (what a refresh swaps in) carry the same row
        html = json.loads(apterm.first_json("Jure", MINT, with_html=True))["html"]["pos"]
        self.assertIn("<h4>Grokova teza</h4>", html)
        self.assertEqual(json.loads(apterm.first_json("Jure", MINT))["positions"][0]["by"]["tag"], "program · Grok")

    def test_manual_buy_and_an_approved_grok_request_are_rucno_a_range_scalp_lot_is_program(self):
        self.others()
        body = self.page()
        man, apr, rng = self.row(body, MAN), self.row(body, APR), self.row(body, RNG)
        self.assertIn('<span class="apx-by man" data-by="ručno" title="Otvorio si ručno">ručno</span>', man)
        self.assertIn('data-by="ručno" title="Otvorio si ručno (odobren Grokov prijedlog)">ručno · Grok prijedlog</span>', apr)
        self.assertIn("<h4>Grokova teza</h4>", apr)                                     # still Grok's why inside
        self.assertNotIn("<h4>Grokova teza</h4>", man)
        self.assertIn(">program · range scalp</span>", rng)                            # from league.db, not the note
        self.assertIn('data-by="ručno"', man[:man.index(">")])

    def test_tag_mapping(self):
        by = apterm.opened_by
        cases = {"ručno (pravi trade)": "ručno", "ručno": "ručno", grokauto.APPROVED_SRC: "ručno · Grok prijedlog",
                 "ručno: prijedlog range": "ručno · prijedlog", grokauto.SRC: "program · Grok",
                 "copy KOL ansem": "program · kopiranje", "copy wallet insajder prije poziva 7xKX": "program · insajderi",
                 "copy KOL ansem (fast)": "program · brzi put", "fast path buy_paper: @x": "program · brzi put",
                 "momentum scalp": "program · momentum", "range lot 2": "program · range",
                 "prijedlog: momentum": "program · prijedlog momentum", "prijedlog (demo): range": "program · prijedlog range",
                 "simianx": "program · SimianX", "DCA kupnja 1/3": "program · DCA plan", "": "program",
                 "usklađeno s lancem nakon restarta": "program"}
        for src, tag in cases.items():
            self.assertEqual(by(src)["tag"], tag, src)
        self.assertEqual(by("range lot 1", "scalp")["tag"], "program · range scalp")
        self.assertEqual(apterm.APPROVED_SRC, grokauto.APPROVED_SRC)

    # ---- 3. Prekidači ------------------------------------------------------------------------------------------

    def test_every_switch_is_in_prekidaci_and_postavke_no_longer_carries_them(self):
        self.scenario(time.time())   # Grok on, an exit plan on MINT
        body = self.page("Jure", {"sve": "1"})
        sw = body[body.index("id=prekidaci"):body.index("id=apx-ostalo")]
        for k in ("id=fl-pravi_novac_sve", "id=fl-pravi-novac", "name=name value=pravi_novac_sve", "id=grok-auto",
                  "Ugasi Grok autotrade", "action=/pravi-trade/grokoff", "action=/pravi-trade/groklimits",
                  "name=max_round_trips_per_token_day", "id=sw-autopilot", "action=/pravi-trade/switch",
                  "id=fl-exit_plan_live", "name=name value=exit_plan_live", "id=fl-rug_labels_v2_ok",
                  "Pauziraj exit planove", "s oznakom „program · Grok”"):
            self.assertIn(k, sw, k)
        ost = body[body.index("id=apx-ostalo"):]
        for k in ("id=grok-postavke", "id=fl-exit_plan_live", "id=fl-pravi_novac_sve", "action=/pravi-trade/groklimits"):
            self.assertNotIn(k, ost, k)
        self.assertIn('su u sekciji <a href="#prekidaci">Prekidači</a>', ost)
        self.assertIn("id=zastavice", ost)
        nal = body[body.index("id=nalozi"):body.index("id=povijest")]
        self.assertNotIn("id=exit-planovi", nal)                                        # moved from Otvoreni nalozi
        self.assertEqual(body.count("id=fl-exit_plan_live"), 1)                         # once on the page

    def test_a_pending_request_is_one_line_on_top_and_the_card_with_its_buttons_at_the_bottom(self):
        code, out = mcpapi.trade_request({"token": REQ, "side": "buy", "amount": 0.1, "require_approval": True,
                                          "reason": "range dno"})
        self.assertEqual(out["status"], "pending_approval", out)
        body = self.page()
        top = body[:body.index("id=apx-chartbox")]
        self.assertIn('<a class=apx-reqn href="#mcp-zahtjevi" id=apx-reqn><b>Grok čeka tvoje odobrenje</b>', top)
        self.assertIn("1 zahtjev · kupi 0,1 SOL", top)
        self.assertRegex(top, r"još 1[45] min")
        card = body[body.index("id=mcp-zahtjevi"):body.index("id=grok-auto")]
        self.assertGreater(body.index("id=mcp-zahtjevi"), body.index("id=prekidaci"))
        for k in ("action=/pravi-trade/mcpok", "action=/pravi-trade/mcpno", ">Odobri<", ">Odbij<"):
            self.assertIn(k, card, k)
        self.assertNotIn("id=apx-reqn", self.page("netko"))

    # ---- 4. a viewer, the browser --------------------------------------------------------------------------------

    def test_a_viewer_sees_the_tags_and_the_states_but_no_button(self):
        settings.put(self.con, "invited", ["Ivan"])
        self.scenario(time.time())
        self.others()
        mcpapi.trade_request({"token": REQ, "side": "buy", "amount": 0.1, "require_approval": True, "reason": "x"})
        body = self.page("Ivan", {"sve": "1"})
        self.assertIn(">program · Grok</span>", body)
        self.assertIn(">ručno · Grok prijedlog</span>", body)
        sw = body[body.index("id=prekidaci"):body.index("id=apx-ostalo")]
        self.assertNotIn("<form", sw)
        self.assertIn("id=fl-pravi-novac", sw)
        self.assertIn("id=fl-exit_plan_live", sw)
        for k in ("<h4>Grokova teza</h4>", "id=apx-reqn", "id=mcp-zahtjevi", "Zatvori 50", "Uredi SL-TP",
                  "action=/pravi-trade/", "data-sheet-full>"):
            self.assertNotIn(k, body, k)

    def test_reload_stays_on_top_and_the_phone_panel_is_on_the_page(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("S.hash = NAV === 'reload' ? '' :", js)
        self.assertIn("history.scrollRestoration = 'manual'", js)
        # the bar's Kupi: in place while the panel is in sight, the sheet only when it is not (its place kept)
        self.assertIn("if (!full && r.top < innerHeight - 120 && r.bottom > 120)", js)
        self.assertIn("if (ph) ph.style.height = sd.offsetHeight + 'px';", js)
        self.assertIn("if (g('[data-sheet-full]')) { openSheet(null, true); return; }", js)
        # an editor inside a closed row opens the row; the panel's link opens the row's editor on a phone
        self.assertIn("if (p.tagName === 'DETAILS' && !p.open) p.open = true;", js)
        self.assertIn("t.closest('.apx-mypos')) t = document.getElementById(b.dataset.edit.replace(/^pe-/, 'ed-'))", js)
        css = apterm.CSS
        self.assertIn(".apx:not(.sheet) .apx-side :is(.apx-mypos,.apx-wal,.apx-dca,.apx-lim){display:none}", css)
        self.assertIn(".apx-m1{grid-column:1;grid-row:1}", css)
        self.assertIn(".apx-side{grid-column:2;grid-row:1/4;position:sticky", css)


def load_tests(loader, standard_tests, pattern):
    """Only this file's tests (Layout reuses Card's setUp and scenario, not its tests; Card runs in its own file)."""
    return unittest.TestSuite(Layout(n) for n in loader.getTestCaseNames(Layout) if n in Layout.__dict__)


if __name__ == "__main__":
    unittest.main()
