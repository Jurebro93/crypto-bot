"""16.11. (vlasnik, na mobitelu): "Makni paper trading sa stranice uživo i provjeri točnost portfolija ... Onda ovo
prekidači, kad otvorim, ima 15 kartica ovih, svaka se može dodatno proširiti. Ne razumijem šta koja znači, kao da na
kineskom piše ... Ovo jednostavno treba biti toliko jednostavnije. Onda ovo settings, rules, isto."

1. the live page has no Uživo / Paper switch: Portfelj is real money only, with a link to the demo results
2. Portfelj says whether the numbers add up ("Brojevi se slažu" / what differs and by how much) and how they are summed;
   the span's number is its result net of deposits (the total PnL when the span covers the whole history)
3. "Prekidači": at most five top rows, in plain Croatian: no internal codes (P14, MK3), no flag names, no jargon; every
   other switch is a closed row of the searchable list "Napredno"; every form still posts where it did
4. "Postavke": at most four blocks (Limiti, Izlazi, Obavijesti, Napredno); what Prekidači shows is not repeated; what
   does nothing while the bot trades midcaps only is left out (hidden, not deleted)
5. the public /autopilot statistics per token, the best token's share, and "Kako se zbraja"

    python3 -m unittest tests.test_jednostavno_offline
"""
import os
import re
import sys
import unittest
from html.parser import HTMLParser
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.test_apterm_offline as at  # noqa: E402  (module import: its own test classes are not rerun here)
from trade import executor, settings, uskladi  # noqa: E402
from ui import apjed, apjavno, apterm, mcpapi, pravitrade  # noqa: E402

NOW = at.NOW
REQ = "Reqq1111111111111111111111111111111111pump"
# internal codes of the plan (P14, MK3, MI2, G18, A1, 3e.4) and English / test jargon the owner does not read
CODES = re.compile(r"\b(P\d{1,2}|MK\d|MI\d|G\d{1,2}|A1|\d[a-e]?\.\d)\b")
JARGON = re.compile(r"\b(EV|holdout|walk-forward|backtest|flag|shadow|paper|live|zastavic\w*|sjena)\b", re.I)


def setUpModule():
    at.setUpModule()


def tearDownModule():
    at.tearDownModule()


class _Text(HTMLParser):
    """The words a card shows while it is open and nothing inside it is: text outside every nested <details>, plus the
    <summary> of each nested one (its closed row). script / style are skipped."""
    VOID = {"br", "wbr", "img", "input", "hr", "meta", "link"}

    def __init__(self, with_summaries=True):
        super().__init__()
        self.stack, self.out, self.with_summaries = [], [], with_summaries

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop() == tag:
                break

    def handle_data(self, data):
        if "script" in self.stack or "style" in self.stack:
            return
        n = self.stack.count("details")
        if n == 0 or (self.with_summaries and n == 1 and "summary" in self.stack
                      and self.stack.index("summary") > self.stack.index("details")):
            self.out.append(data)


def shown(html, with_summaries=True):
    p = _Text(with_summaries)
    p.feed(html)
    return " ".join(" ".join(p.out).split())


class Page(at.Env):
    def page(self, user="Jure", qs=None):
        apterm.reset()
        return pravitrade.page(qs or {}, user)[1]

    def body_of(self, body):
        """The inside of the Prekidači card (after its own summary)."""
        sw = body[body.index("<section class=apx-swsec id=prekidaci"):body.index("id=apx-ostalo")]
        return sw[sw.index("</summary>") + len("</summary>"):sw.rindex("</details>")]

    def midcap(self):
        """The owner's switches as they stand 16.11.: midcaps only, the midcap rule with real money."""
        for name, mode in ((settings.FOKUS, "live"), (settings.MIKROKAP, "live"), (settings.VELIKI, "paper"),
                           (settings.VEL_SWITCH, "live"), (settings.INSAJDERI2, "paper"), (settings.ARHIVA, "live")):
            settings.set_flag(self.con, name, mode, "Jure")
        settings.put(self.con, "on", True, "Jure")


class Portfelj(Page):
    def test_no_paper_switch_on_the_live_page(self):
        self.seed()
        body = self.page()
        self.assertNotIn("data-pm=", body)
        port = body[body.index("id=apx-port"):body.index("id=kupiti")]
        self.assertNotIn(">Paper<", port)
        self.assertNotIn(">Uživo<", port)
        self.assertIn('<span class="apx-badge live">pravi novac</span>', port)
        self.assertIn(f'<p class=apx-demolink><a href="{apterm.DEMO_URL}">Demo rezultati →</a></p>', port)
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertNotIn("apx.pm", js)                                         # no remembered Paper choice either
        self.assertNotIn("PN.m = b.dataset.pm", js)
        # the paper account's numbers stay reachable for their own page (the endpoint is not removed)
        self.assertEqual(apterm.portfelj("Jure", "paper", 30, NOW)["mode"], "paper")

    def test_the_card_says_whether_the_numbers_add_up(self):
        self.seed()
        port = self.page()
        port = port[port.index("id=apx-port"):port.index("id=kupiti")]
        self.assertIn("<div class=apx-uskl id=apx-uskl><details class=\"apx-uskd ", port)
        self.assertRegex(port, r"<summary><b>(Brojevi se slažu|Novčanik se slaže · zbroj pojedinih tradeova je [\d,]+\s?SOL "
                               r"(niži|viši))</b><span class=apx-lnkb>Kako se zbraja</span></summary>")
        for k in ("Novčanik, izmjereno na lancu: vrijednost <b>1,815</b> = slobodno 1,772 + u pozicijama 0,043",
                  "Zatvorene pozicije (1)", "Otvorene pozicije (1), po cijeni sada",
                  "Ukupni PnL novčanika (vrijednost − uplate)", "<b>Po tokenu</b>", "<b>Po tradeu</b>"):
            self.assertIn(k, port, k)
        self.assertNotIn("✓", port)                                            # the page carries no emoji (a green dot)
        self.assertNotRegex(port, r"<details class=\"apx-uskd[^>]* open")       # one line until he taps it
        # the rent of an empty token account, as one line; nothing closes by itself
        self.assertIn("Moguće vratiti ~0,002\xa0SOL zatvaranjem 1 praznog token računa", port)
        self.assertIn("ništa se ne zatvara samo", port)

    def test_inner_from_a_report_that_agrees_and_one_that_does_not(self):
        r = {"have": True, "ok": True, "text": "Brojevi se slažu", "diff_sol": 0.0, "notes": ["nije prikazano"],
             "wallet": {"value_sol": 1.372, "free_sol": 1.111, "pos_sol": 0.261, "usdc_sol": 0.0, "deposits_sol": 1.045,
                        "pnl_sol": 0.327, "sum_ok": True},
             "closed": {"n": 67, "wins": 28, "pnl_sol": 0.188, "best": {"symbol": "Hope", "token": "H" * 44, "pnl": 0.211},
                        "worst": {"symbol": "HAOBIBI", "token": "B" * 44, "pnl": -0.15}},
             "lines": [("Zatvorene pozicije (67)", 0.188), ("Otvorene pozicije (3), po cijeni sada", 0.139),
                       ("Ukupni PnL novčanika (vrijednost − uplate)", 0.327)],
             "by_token": {"n": 38, "plus": 12, "rest_n": 37, "rest_sol": -0.66, "sum_sol": 0.283,
                          "best": {"symbol": "Hope", "token": "H" * 44, "pnl_sol": 0.943, "buys": 21, "sells": 27}},
             "rent": {"n": 35, "sol": 0.071375}}
        h = apterm.uskl_inner(r)
        self.assertIn('<details class="apx-uskd ok"><summary><b>Brojevi se slažu</b>', h)
        self.assertIn("38 zatvorenih tokena, 12 u plusu. Najbolji <span translate=no>Hope</span> <b class=\"up\">+0,943\xa0SOL"
                      "</b> (21 kupnja, 27 prodaja); svi ostali tokeni zajedno <b class=\"dn\">−0,660\xa0SOL</b>.", h)
        self.assertIn("67 zatvorenih, 28 dobitnih. Najbolji <span translate=no>Hope</span> +0,211\xa0SOL, najgori "
                      "<span translate=no>HAOBIBI</span> −0,150\xa0SOL.", h)
        self.assertIn("Moguće vratiti ~0,071\xa0SOL zatvaranjem 35 praznih token računa", h)
        self.assertIn("<tr class=tot><td>=</td><td>Ukupni PnL novčanika (vrijednost − uplate)</td>", h)
        self.assertNotIn("nije prikazano", h)                                  # the reasons only while it differs
        r.update(ok=False, text="Novčanik se slaže · zbroj pojedinih tradeova je 0,095 SOL niži",
                 notes=["Naknade u knjizi su procjena."])
        h = apterm.uskl_inner(r)
        self.assertIn('<details class="apx-uskd warn"><summary><b>Novčanik se slaže · zbroj pojedinih tradeova je 0,095 SOL '
                      'niži</b>', h)
        self.assertIn("Mjerodavan je novčanik", h)
        self.assertIn("<li>Naknade u knjizi su procjena.</li>", h)
        self.assertEqual(apterm.uskl_inner({"have": False, "why": "x"}), "")

    def test_span_result_is_net_of_deposits_and_the_api_carries_it(self):
        self.seed()
        apterm.reset()
        with mock.patch.object(uskladi, "period", lambda con, days, now, s: {"base_sol": 0.0, "result_sol": s["pnl_sol"],
                                                                              "whole": True}):
            d = apterm.portfelj("Jure", "live", 30, NOW)
        k = d["kpi"]
        self.assertEqual(k["period_sol"], k["total_sol"])                      # the whole history: exactly the total PnL
        self.assertTrue(k["period_whole"])
        self.assertEqual(k["period_base"], 0.0)
        self.assertIn("apx-uskd", d["uskl"])                                   # the same line, refreshed with the numbers
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        for needle in ("k.period_sol", "k.period_whole ? 'rezultat od početka (bez uplata)'", "p.kpi.period_base",
                       "ub.innerHTML = p.uskl"):
            self.assertIn(needle, js, needle)
        self.assertNotIn("promjena vrijednosti", js)                           # last point - first point is gone


class Prekidaci(Page):
    def test_at_most_five_top_rows_in_plain_words(self):
        self.midcap()
        body = self.body_of(self.page("Jure", {"sve": "1"}))
        self.assertLessEqual(body.count("apx-jtop"), 5)
        tops = re.findall(r'<(?:div|details) class="[^"]*apx-jtop[^"]*" id=([\w-]+)', body)
        self.assertEqual(tops, ["fl-pravi_novac_veliki", "sw-trguje", "sw-istr", "sw-autopilot", "sw-napredno"])
        text = shown(body)
        for name in ("Pravi novac", "Što bot trguje", "Midcap dnevni raspon", "Midcap 7 dana", "Istraživanje (samo demo)",
                     "Hitno zaustavi sve", "Napredno ("):
            self.assertIn(name, text, name)
        self.assertIsNone(CODES.search(text), CODES.search(text))
        self.assertIsNone(JARGON.search(text), JARGON.search(text))
        for flag in settings.FLAGS:                                            # no flag name anywhere a row shows
            if "_" in flag:
                self.assertNotIn(flag, text, flag)
        self.assertLess(len(text), 1100)                                       # one screen of words, not a manual
        self.assertNotRegex(body, r"<details[^>]*\sopen[\s>]")                  # nothing inside comes open

    def test_pravi_novac_row_says_caps_and_today(self):
        self.midcap()
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                         "qty_left, sol_back, fees_sol) VALUES ('M','M',?, 'live','open','veliki: dnevni raspon',0.1,1,1,0,0)",
                         (NOW - 30,))
        self.con.commit()
        cfg = pravitrade._cfg(self.con)
        ns = apjed.novac_state(self.con, cfg, NOW)
        self.assertTrue(ns["on"])
        self.assertEqual(apjed.caps_text(ns), "0,2 SOL po kupnji · 5 otvorenih · 20 kupnji dnevno · dnevni gubitak 0,3 SOL · "
                                              "staje ako novčanik padne pod 1 SOL")
        self.assertEqual(apjed.today_text(ns), "danas 1 kupnja, otvoreno 1 od 5, rezultat 0")
        row = self.body_of(self.page())
        row = row[row.index("id=fl-pravi_novac_veliki"):row.index("id=sw-trguje")]
        for k in ("<b>Pravi novac</b>", '<span class="apx-jst on">uključen</span>', "<b>Stropovi:</b> 0,2 SOL po kupnji",
                  "<b>Danas:</b> 1 kupnja, otvoreno 1 od 5", "action=/pravi-trade/flag",
                  "name=name value=pravi_novac_veliki", "name=mode value=off", 'class="ap-sw on apx-jbig" role=switch'):
            self.assertIn(k, row, k)
        settings.set_flag(self.con, settings.VEL_SWITCH, "off", "Jure")
        row = self.body_of(self.page())
        row = row[row.index("id=fl-pravi_novac_veliki"):row.index("id=sw-trguje")]
        self.assertIn('<span class="apx-jst">isključen</span>', row)
        self.assertIn("name=mode value=live", row)
        self.assertIn("return confirm(", row)                                  # turning the real money on asks first

    def test_closed_card_says_the_state_of_the_real_money(self):
        self.midcap()
        sw = self.page()
        sw = sw[sw.index("id=prekidaci"):sw.index("id=apx-ostalo")]
        self.assertRegex(sw, r'<span class="apx-mut apx-swsum">Pravi novac: uključen[^<]*</span>')
        settings.set_flag(self.con, settings.VEL_SWITCH, "off", "Jure")
        self.assertIn('<span class="apx-mut apx-swsum">Pravi novac: isključen</span>', self.page())
        settings.put(self.con, "on", False, "Jure")
        body = self.page()
        self.assertIn('<span class="apx-mut apx-swsum">Zaustavljeno: ništa se ne kupuje pravim novcem</span>', body)
        stop = self.body_of(body)
        stop = stop[stop.index("id=sw-autopilot"):stop.index("id=sw-napredno")]
        for k in ('<span class="apx-jst bad">zaustavljeno</span>', "action=/pravi-trade/switch", "name=on value=1",
                  ">Pokreni ponovno</button>"):
            self.assertIn(k, stop, k)

    def test_stop_row_is_red_and_always_there(self):
        self.midcap()
        stop = self.body_of(self.page())
        stop = stop[stop.index("id=sw-autopilot"):stop.index("<details", stop.index("id=sw-autopilot"))]
        for k in ("<b>Hitno zaustavi sve</b>", "action=/pravi-trade/switch", "name=on value=0",
                  "<button class=apx-jstop>Zaustavi sve</button>", "return confirm("):
            self.assertIn(k, stop, k)
        self.assertNotIn("<details", stop)                                     # never folded
        self.assertIn(".ap button.apx-jstop{background:var(--bad", apterm.CSS)

    def test_rules_and_research_rows(self):
        self.midcap()
        body = self.body_of(self.page())
        rules = body[body.index("id=sw-trguje"):body.index("<details", body.index("id=sw-trguje"))]
        self.assertEqual(rules.count("class=apx-jr2"), 2)                      # two rows, no more
        self.assertNotIn("<form", rules)
        self.assertNotIn("<details", rules)
        ist = body[body.rindex("<details", 0, body.index("id=sw-istr")):body.index("id=sw-autopilot")]
        self.assertIn("radi: insajderi, listing signali", ist)
        self.assertEqual(ist.count("class=apx-jr2"), 3)                        # insajderi, listing signali, makro
        for k in ("name=name value=insajderi2", "name=mode value=off", "name=name value=makroinf_indeks",
                  "name=mode value=paper", ">Listing signali<"):
            self.assertIn(k, ist, k)
        self.assertEqual(ist.count("<details"), 1)                             # the row itself: no card inside it

    def test_rules_say_demo_and_real_money_only_while_real_money_can_buy(self):
        from veliki import gate
        self.midcap()
        cfg = pravitrade._cfg(self.con)
        with mock.patch.object(executor, "armed", lambda: True), \
                mock.patch.object(gate, "real_refusal", lambda **k: None), \
                mock.patch.object(gate, "wf_proof", lambda *a, **k: (False, "holdout EV -3,9 %", None)):
            ns = apjed.novac_state(self.con, cfg, NOW)
            self.assertTrue(ns["running"])
            self.assertEqual(apjed.midcap_state(self.con, ns), {"demo": True, "intra_real": True, "range_real": False})
            rules = apjed._rules_block(apjed.midcap_state(self.con, ns))
            self.assertIn('<b>Midcap dnevni raspon</b>', rules)
            self.assertEqual(re.findall(r'<span class="apx-jst[^"]*">([^<]+)</span>', rules), ["demo + pravi novac", "samo demo"])
            with mock.patch.object(gate, "real_refusal", lambda **k: "BTC slobodan pad (-6 % u 4 h): bez novih pravih ulaza"):
                ns = apjed.novac_state(self.con, cfg, NOW)
                self.assertEqual((ns["on"], ns["running"], ns["why"]), (True, False, "BTC naglo pada: bot čeka da se smiri"))
                self.assertFalse(apjed.midcap_state(self.con, ns)["intra_real"])
        ns = apjed.novac_state(self.con, cfg, NOW)                              # no key in the test: a trial only
        self.assertEqual((ns["running"], ns["why"]), (False, "ključ novčanika nije postavljen, kupnje su samo proba"))
        settings.set_flag(self.con, settings.SWITCH_ALL, "live", "Jure")       # another real-money buyer is named
        self.assertEqual(apjed.novac_state(self.con, cfg, NOW)["others"], ["kopiranje"])
        self.assertIn("Pravim novcem kupuje i: kopiranje (pod Napredno).", self.body_of(self.page()))

    def test_napredno_is_one_closed_searchable_list_with_every_other_switch(self):
        self.midcap()
        body = self.body_of(self.page("Jure", {"sve": "1"}))
        adv = body[body.index("id=sw-napredno"):]
        rows = re.findall(r'<details class="ap-it apx-jn" id=([\w-]+) data-jn', adv)
        self.assertIn(f">Napredno ({len(rows)})<", adv)
        self.assertIn("<input type=search data-jq", adv)
        for iid in ["sw-pravi", "sw-grok"] + [f"fl-{n}" for n in apjed.NAPREDNO if n != settings.SWITCH_ALL]:
            self.assertIn(iid, rows, iid)
        # every owner switch is somewhere in Prekidači, by its own form
        for name in settings.OWNER_SWITCHES:
            self.assertIn(f"name=name value={name}>", body, name)
        for k in ("action=/pravi-trade/grokon", "action=/pravi-trade/groklimits", "name=max_round_trips_per_token_day",
                  "id=fl-pravi-novac", "id=grok-auto"):
            self.assertIn(k, adv, k)
        text = shown(adv)                                                      # the closed rows: names and sentences
        self.assertIsNone(CODES.search(text), CODES.search(text))
        for flag in settings.FLAGS:
            if "_" in flag:
                self.assertNotIn(flag, text, flag)
        for k in ("Samo midcapovi", "Bez malih tokena", "AI kritičar", "Arhiva malih tokena", "Brisanje starih tradeova",
                  "Grok autotrade", "Pravi novac: kopiranje"):
            self.assertIn(k, text, k)
        self.assertIn("Ne radi dok bot trguje samo midcapove.", text)          # the old strategies say so
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("e.target.matches('[data-jq]')", js)
        self.assertIn("for (const r of $$('[data-jn]', box))", js)

    def test_every_plain_name_is_short_and_every_switch_has_one(self):
        for name in settings.OWNER_SWITCHES:
            self.assertIn(name, apjed.PLAIN, name)
        for name, (nm, what, mode) in apjed.PLAIN.items():
            self.assertIn(name, settings.FLAGS, name)
            self.assertLessEqual(len(nm.split()), 4, nm)
            self.assertLessEqual(len(what), 120, what)
            self.assertTrue(what.endswith("."), what)
            self.assertIn(mode, ("live", "paper"))
            self.assertIsNone(CODES.search(nm + " " + what), nm)
            self.assertIsNone(JARGON.search(nm + " " + what), nm)

    def test_a_waiting_request_is_a_row_above_the_five(self):
        code, out = mcpapi.trade_request({"token": REQ, "side": "buy", "amount": 0.1, "require_approval": True,
                                          "reason": "range dno"})
        self.assertEqual(out["status"], "pending_approval", out)
        body = self.page()
        sw = body[body.index("id=prekidaci"):body.index("id=apx-ostalo")]
        self.assertIn('<b class=apx-swbadge title="Grokov zahtjev čeka tvoje Odobri / Odbij">1 čeka</b>', sw)
        inner = self.body_of(body)
        self.assertTrue(inner.lstrip().startswith('<div class="ap apx-acc-in apx-jed"><details class=ap-it id=sw-mcp>'),
                        inner[:120])
        self.assertLessEqual(inner.count("apx-jtop"), 5)
        self.assertIn("action=/pravi-trade/mcpok", inner)

    def test_a_viewer_reads_the_states_and_gets_no_button(self):
        settings.put(self.con, "invited", ["Ivan"])
        self.midcap()
        body = self.body_of(self.page("Ivan", {"sve": "1"}))
        self.assertNotIn("<form", body)
        self.assertNotIn("<button", body)
        self.assertIn('<span class="apx-jst on">uključen</span>', body)
        self.assertLessEqual(body.count("apx-jtop"), 5)

    def test_a_switch_answers_in_plain_words(self):
        self.midcap()
        back = pravitrade.post("/pravi-trade/flag", {"name": "pravi_novac_veliki", "mode": "off"}, "Jure")
        self.assertEqual(back, "/pravi-trade?ok=Isklju%C4%8Deno%3A%20Pravi%20novac.#fl-pravi_novac_veliki")
        self.assertEqual(settings.flag("pravi_novac_veliki", con=self.con), "off")
        self.assertEqual(apjed.flag_toast("pravi_novac_veliki", "live"), "Uključeno: Pravi novac.")
        self.assertEqual(apjed.flag_toast("mikrokap_moonshot", "paper"), "Uključeno: Iznimka za male tokene.")
        self.assertEqual(apjed.flag_toast("makroinf_indeks", "shadow"), "Samo mjeri: Makro influenceri.")
        self.assertIsNone(apjed.flag_toast("range_dca", "paper"))               # a plan's rule keeps the old line
        back = pravitrade.post("/pravi-trade/flag", {"name": "dca_guard", "mode": "shadow"}, "Jure")
        self.assertIn("Zastavica%20dca_guard", back)
        self.assertIn("samo%20vlasnik", pravitrade.post("/pravi-trade/flag", {"name": "pravi_novac_veliki",
                                                                                 "mode": "live"}, "Ivan"))
        self.assertEqual(settings.flag("pravi_novac_veliki", con=self.con), "off")


class Postavke(Page):
    def blocks(self, html):
        """The top rows of Postavke: (id, name) of every details directly under the group."""
        inner = html[html.index('<div class="ap-grp apx-jpost">') + len('<div class="ap-grp apx-jpost">'):]
        out, depth = [], 0
        for m in re.finditer(r"<(/?)details\b([^>]*)>", inner):
            if m.group(1):
                depth -= 1
            else:
                if depth == 0:
                    name = re.search(r'<div class="ms-t">(.*?)</div>', inner[m.end():]).group(1)
                    out.append((re.search(r"id=([\w-]+)", m.group(2)).group(1), name))
                depth += 1
        return out

    def test_at_most_four_blocks(self):
        self.midcap()
        html = apterm.lazy("ostalo", "Jure")
        b = self.blocks(html)
        self.assertLessEqual(len(b), 4)
        self.assertEqual([i for i, _n in b], ["limiti-b", "izlazi-b", "obavijesti", "napredno"])
        self.assertEqual([n for _i, n in b][:3], ["Limiti", "Izlazi", "Obavijesti"])
        self.assertRegex(b[3][1], r"^Napredno \(\d+\)$")
        text = shown(html)                                                     # the four closed rows
        self.assertIsNone(CODES.search(text), CODES.search(text))
        self.assertLess(len(text), 520)
        self.assertNotRegex(html, r"<details[^>]*\sopen[\s>]")
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("<span class=apx-mut>limiti, izlazi, obavijesti, napredno</span>", body)

    def test_limiti_the_four_and_the_rest_in_one_form(self):
        self.midcap()
        html = apterm.lazy("ostalo", "Jure")
        lim = html[html.index("id=limiti-b"):html.index("id=izlazi-b")]
        self.assertIn("ulog 0,2 SOL · 5 otvorenih · dnevni gubitak 0,3 SOL · pod 1 SOL", lim)
        self.assertIn("pod novčanika <b>1 SOL</b>: ispod toga bot ne kupuje", lim)
        self.assertEqual(lim.count("action=/pravi-trade/limits"), 1)
        form = lim[lim.index("<form"):lim.index("</form>")]
        first = form[:form.index("<details")]
        for k in ("name=size_sol", "name=max_open", "name=max_loss_day", "name=min_sol_reserve"):
            self.assertIn(k, first, k)                                         # the four he changes
        for k in ("name=max_sol_per_day", "name=max_cost_pct", "name=owner_token_cap", "name=dca_cap_owner",
                  "name=use_pump"):
            self.assertIn(k, form[form.index("<details"):], k)                 # the rest under "Još limita"
        # the range scalp's two limits do nothing while the range does not run: carried hidden, never lost
        for k in apjed.IDLE_LIMITS:
            self.assertIn(f"<input type=hidden name={k} value=", form, k)
        for k in apjed.LOCKED_BOXES:
            self.assertNotIn(f"name={k}", form, k)
        # the same form saves as before, and the hidden ones keep their value
        fields = dict(re.findall(r'name=(\w+) value="([^"]*)"', form))
        fields.update(max_open="7", use_pump="1")
        settings.put(self.con, "range_scalp_trades_day", 55, "Jure")
        fields["range_scalp_trades_day"] = "55"
        self.assertIn("Limiti%20spremljeni", pravitrade.post("/pravi-trade/limits", fields, "Jure"))
        cfg = pravitrade._cfg(self.con)
        self.assertEqual((cfg["max_open"], cfg["range_scalp_trades_day"], cfg["use_pump"]), (7, 55, True))
        # without the midcap focus the two fields are ordinary fields again
        settings.set_flag(self.con, settings.FOKUS, "off", "Jure")
        self.assertIn("name=range_scalp_trades_day value=", apterm.lazy("ostalo", "Jure").replace("type=hidden ", ""))
        self.assertNotIn("type=hidden name=range_scalp_trades_day", apterm.lazy("ostalo", "Jure"))

    def test_izlazi_say_the_midcap_rules_as_they_are_in_the_code(self):
        from veliki import intra, rule
        self.assertEqual(apjed.exit_rules(), (float(intra.cfg_of()["tp"]), float(rule.RULE["tp"]),
                                              rule.OWNER_EXIT["be_at"] * 100, rule.OWNER_EXIT["time_h"]))
        self.assertEqual(apjed.exit_text(), "cijeli profit na +10 do 15 % · stop na ulaz od +5 % · bez vremenskog stopa")
        html = apterm.lazy("ostalo", "Jure")
        izl = html[html.index("id=izlazi-b"):html.index("id=obavijesti")]
        for k in ("proda cijelu poziciju na +10 do 15 %", "kad pozicija dođe na +5 %, stop se diže na cijenu ulaza",
                  "nema vremenskog stopa", "id=cilj", "id=stop", "action=/pravi-trade/tp", "action=/pravi-trade/sl"):
            self.assertIn(k, izl, k)
        self.assertEqual(izl.count("<details"), 1)                             # text and buttons, no card inside
        self.assertIn("Cilj%20izlaza", pravitrade.post("/pravi-trade/tp", {"tp": "10"}, "Jure"))

    def test_napredno_holds_the_rest_and_nothing_prekidaci_shows(self):
        self.midcap()
        html = apterm.lazy("ostalo", "Jure")
        adv = html[html.index("id=napredno"):]
        for k in (">Koga bot kopira<", ">Pravila u testiranju<", ">Grok (MCP)<", ">Wallet i uplata<", "Tko vidi stranicu",
                  "Kako je zaštićeno", "id=zastavice", "id=postavljanje", "action=/pravi-trade/mcpkey",
                  "action=/pravi-trade/triggerprobe", 'href="/pravi-trade?stari=1"'):
            self.assertIn(k, adv, k)
        for name in list(settings.OWNER_SWITCHES) + [settings.VELIKI, settings.INSAJDERI2, settings.MAKROINF]:
            self.assertNotIn(f"id=fl-{name}", html, name)                      # in Prekidači, once on the page
        for k in ("action=/pravi-trade/groklimits", "action=/pravi-trade/switch", "id=grok-auto"):
            self.assertNotIn(k, html, k)
        self.assertIn('su u sekciji <a href="#prekidaci">Prekidači</a>', adv)

    def test_rules_of_strategies_that_do_not_run_are_left_out_not_deleted(self):
        self.midcap()
        settings.set_flag(self.con, "momentum_scalp", "shadow", "Jure")       # one of them is on: it stays listed
        html = apterm.lazy("ostalo", "Jure")
        self.assertIn("id=fl-momentum_scalp", html)
        self.assertIn("Ne radi dok bot trguje samo midcapove.", html)
        for name in ("range_dca", "range_market", "proposals", "konsenzus", "oscilator", "fast_path"):
            self.assertNotIn(f"id=fl-{name}", html, name)
            self.assertEqual(settings.flag(name, con=self.con), settings.FLAG_DEFAULTS.get(name, "off"))   # untouched
        self.assertRegex(html, r"Skriveno \d+ pravila? starih strategija")
        self.assertIn("id=fl-dca_guard", html)                                 # a rule that still means something
        self.assertIn("name=name value=dca_guard", html)
        # without the focus every rule is listed again
        settings.set_flag(self.con, settings.FOKUS, "off", "Jure")
        full = apterm.lazy("ostalo", "Jure")
        for name in ("range_dca", "konsenzus", "fast_path"):
            self.assertIn(f"id=fl-{name}", full, name)
        self.assertNotIn("Skriveno", full)
        for name in apjed.IDLE_FLAGS:
            self.assertIn(name, settings.FLAGS, name)

    def test_a_viewer_gets_no_form(self):
        settings.put(self.con, "invited", ["Ivan"])
        html = apterm.lazy("ostalo", "Ivan")
        self.assertEqual(len(self.blocks(html)), 4)
        for k in ("action=/pravi-trade/limits", "action=/pravi-trade/tp", "action=/pravi-trade/flag", "Spremi limite"):
            self.assertNotIn(k, html, k)


class Javno(unittest.TestCase):
    ST = {"mode": "live", "n": 67, "wins": 28, "pnl": 0.188, "open": 3,
          "best": {"symbol": "Hope", "pnl": 0.211}, "worst": {"symbol": "HAOBIBI", "pnl": -0.15},
          "usk": {"ok": False, "diff_sol": 0.1,
                  "lines": [("Zatvorene pozicije (67)", 0.188), ("Otvorene pozicije (3), po cijeni sada", 0.039),
                            ("Razlika knjige i novčanika", 0.1), ("Ukupni PnL novčanika (vrijednost − uplate)", 0.327)],
                  "wallet": {"value_sol": 1.372, "deposits_sol": 1.045},
                  "by_token": {"n": 38, "plus": 12, "rest_n": 37, "rest_sol": -0.66, "sum_sol": 0.283,
                               "best": {"symbol": "Hope", "token": "H" * 44, "pnl_sol": 0.943, "buys": 21, "sells": 27}}}}

    def test_statistics_per_token_and_how_they_add_up(self):
        h = apjavno._stats_html(self.ST)
        self.assertLess(h.index("Po tokenu"), h.index("Po tradeu"))
        for k in (">38</b><span>Zatvoreni tokeni<", "<span>U plusu<", "+0.943 SOL</b><span>Najbolji token · <i translate=no>Hope",
                  "-0.660 SOL</b><span>Svi ostali zajedno<",
                  "Najbolji token <b translate=no>Hope</b> donio je <b class=\"pos\">+0.943 SOL</b> u 21 kupnji; ostali zatvoreni "
                  "tokeni (37) zajedno <b class=\"neg\">-0.660 SOL</b>.",
                  ">67</b><span>Zatvoreni tradeovi<", "+0.188 SOL</b><span>Zbroj zatvorenih<", "Najbolji trade",
                  "<b>Kako se zbraja:</b> zatvorene pozicije (67) <b class=\"pos\">+0.188</b> + otvorene pozicije (3), po cijeni "
                  "sada <b class=\"pos\">+0.039</b> + razlika knjige i novčanika <b class=\"pos\">+0.100</b> = ukupni rezultat "
                  "novčanika <b class=\"pos\">+0.327 SOL</b> (vrijednost 1.372 − uplaćeno 1.045)",
                  "Mjerodavan je novčanik, izmjeren na lancu"):
            self.assertIn(k, h, k)
        self.assertNotIn("Ukupni rezultat<", h)                                # the sum of the lots is not "the total"

    def test_without_the_reconciliation_the_old_tiles_stay(self):
        st = {k: v for k, v in self.ST.items() if k != "usk"}
        h = apjavno._stats_html(st)
        self.assertNotIn("Po tokenu", h)
        self.assertNotIn("Kako se zbraja", h)
        self.assertIn(">67</b><span>Zatvoreni tradeovi<", h)


class Fokus(unittest.TestCase):
    def test_what_is_called_idle_is_off_in_ops_fokus(self):
        """IDLE_FLAGS / IDLE_CARDS name only what ops/fokus.py really stops or retargets while the switch is on."""
        from ops import fokus
        keys = {k for _m, k, _w in fokus.OFF} | {k for k, _w in fokus.RETARGET}
        for k in ("range", "momentum", "prijedlozi", "skener", "eventi", "insajderi", "shill", "grupe", "konsenzus",
                  "oscilator", "zadnjih5", "fast", "live"):
            self.assertIn(k, keys, k)
        self.assertTrue(executor.equity_floor({}) > 0)


if __name__ == "__main__":
    unittest.main()
