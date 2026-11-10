"""ui/redak.py (10.11., Jure, prijedlog ui-prijedlozi.md odjeljak 2): Croatian numbers, escaping, the row, hero,
verdict panel, segment and dot; and the navigation of section 3.5 (bottom bar, "Više" page, no ☰, novo dot)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import admstrip, html, redak as r  # noqa: E402

NB = " "


class Numbers(unittest.TestCase):
    def test_num_comma_space_and_minus(self):
        self.assertEqual(r.num(3638), f"3{NB}638")
        self.assertEqual(r.num(0.1, 3), "0,100")
        self.assertEqual(r.num(-0.042, 3), "−0,042")
        self.assertEqual(r.num(18, sign=True), "+18")
        self.assertEqual(r.num(0, 2, sign=True), "0,00")           # zero has no sign
        self.assertEqual(r.num(-0.0004, 2), "0,00")                # rounds to zero: no "−0,00"
        self.assertEqual(r.num(None), "–")
        self.assertEqual(r.num("x"), "–")

    def test_units_after_the_number(self):
        self.assertEqual(r.sol(0.1), f"0,100{NB}SOL")
        self.assertEqual(r.sol(2, 2), f"2,00{NB}SOL")
        self.assertEqual(r.sol(-0.042, sign=True), f"−0,042{NB}SOL")
        self.assertEqual(r.usd(412000), f"412k{NB}$")
        self.assertEqual(r.usd(96400), f"96k{NB}$")
        self.assertEqual(r.usd(9500), f"9,5k{NB}$")
        self.assertEqual(r.usd(999700), f"1,0M{NB}$")             # no "1000k"
        self.assertEqual(r.usd(1234567), f"1,2M{NB}$")
        self.assertEqual(r.usd(850), f"850{NB}$")
        self.assertEqual(r.usd(-185, sign=True), f"−185{NB}$")
        self.assertEqual(r.usd(77, sign=True), f"+77{NB}$")
        self.assertEqual(r.usd(None), "–")
        self.assertEqual(r.pct(18), f"+18{NB}%")
        self.assertEqual(r.pct(-45.7, 1), f"−45,7{NB}%")
        self.assertEqual(r.pct(0.7, sign=False, frac=True), f"70{NB}%")
        self.assertEqual(r.share(21, 30), "21 od 30")
        self.assertEqual(r.share(1, 0), "–")

    def test_ago_and_tone(self):
        self.assertEqual(r.ago(1000, now=1030), "upravo sada")
        self.assertEqual(r.ago(1000, now=1000 + 180), "prije 3 min")
        self.assertEqual(r.ago(1000, now=1000 + 2 * 3600 + 5), "prije 2 h")
        self.assertEqual(r.ago(1000, now=1000 + 3 * 86400), "prije 3 d")
        self.assertEqual(r.ago(None), "–")
        self.assertEqual((r.tone(1), r.tone(-1), r.tone(0), r.tone(None)), ("pos", "neg", "", ""))


class Blocks(unittest.TestCase):
    def test_everything_is_escaped_once(self):
        out = r.row("<b>X</b>", "a & b", r.pct(5), "<i>", href="/token/x")
        self.assertIn("&lt;b&gt;X&lt;/b&gt;", out)
        self.assertIn("a &amp; b", out)
        self.assertIn("&lt;i&gt;", out)
        self.assertNotIn("<b>X", out)
        d = r.cat(r.dot("warn", "samo brzo"), " · <30> poziva")
        self.assertIn('<span class="ms-dot warn"', d)                # Html kept
        self.assertIn("&lt;30&gt;", d)                                # text escaped
        self.assertNotIn("&amp;lt;", r.row("A", d))                   # Html is not escaped twice
        self.assertNotIn("javascript", r.row("A", href="javascript:alert(1)"))   # only safe links

    def test_row_link_popup_and_plain(self):
        a = r.row("GIGAFROG", "3 smart walleta", "94", "412k $", href="/token/abc", value_tone="pos", rank=1)
        self.assertTrue(a.startswith('<a class="ms-row" href="/token/abc"'))
        self.assertIn('<div class="ms-v pos">94</div>', a)
        self.assertIn('<span class="ms-rk">1</span>', a)
        self.assertIn("ms-chev", a)
        p = r.row("ARIA", mint="Mint1", value="83")
        self.assertIn('data-mint="Mint1"', p)                          # opens the existing evidence pop-up
        self.assertIn('role="button"', p)
        plain = r.row("Nakon 60 min", "do +10 %", "21 od 30", "70 %")
        self.assertNotIn("ms-chev", plain)
        self.assertNotIn("href", plain)
        lst = r.rows([a, {"name": "MOCHI", "value": "76"}])
        self.assertEqual(lst.count("<li>"), 2)
        self.assertTrue(lst.startswith('<ul class="ms-list">'))
        self.assertEqual(r.rows([]), "")
        self.assertIn("Nema", r.rows([], empty="Nema tokena."))

    def test_hero_verdict_seg_section(self):
        hp = r.hero("GIGAFROG", "Novac ulazi brzo.", label="Najbolji ulaz sada", facts="pouzdanost 94", href="/token/a",
                    foot="Ulog u demu 25–50 $")
        self.assertTrue(hp.startswith('<a class="ms-panel" href="/token/a"'))
        for s in ("ms-lbl", "ms-name", "ms-facts", "ms-go", "ms-chev", "Novac ulazi brzo."):
            self.assertIn(s, hp)
        big = r.hero("2,00", "≈ 323 $", unit="SOL", big=True)
        self.assertIn('<div class="ms-big">2,00<small>SOL</small></div>', big)
        v = r.verdict("Samo za brzi izlaz", "U prvom satu ...", label="Presuda za zadnjih 14 dana",
                      facts="samo brzo · 30 poziva", kind="warn")
        self.assertIn("ms-verdict", v)
        self.assertIn('<span class="ms-dot warn"', v)
        sg = r.seg([("/tokens", "Novi"), ("/tokens/jaki", "Jaki")], "/tokens/jaki")
        self.assertIn('<a href="/tokens/jaki" class="on" aria-current="page">Jaki</a>', sg)
        self.assertIn('class="ms-seg"', sg)
        self.assertIn('<a href="/kol/x">Svih 76</a>', r.section("Zadnji pozivi", "Svih 76", "/kol/x"))
        self.assertIn("ms-h1", r.top("Pregled", "Utorak", icon_href="/trazi"))
        self.assertIn('class="ms-dot"', r.dot("nepoznato"))           # unknown kind -> grey

    def test_css_has_the_five_sizes_and_every_class(self):
        for size in ("34px", "22px", "17px", "15px", "13px", "48px"):
            self.assertIn(f"font-size:{size}", html.MS_CSS)
        for cls in (".ms-row", ".ms-hero", ".ms-panel", ".ms-seg", ".ms-dot", ".ms-chev", ".ms-list", ".ms-h2",
                    ".ms-hint", ".ms-colhead", ".ms-rk", "tabular-nums"):
            self.assertIn(cls, html.MS_CSS)
        self.assertIn(html.MS_CSS, html.page("x", "<h1>x</h1>", "/pregled"))


class Navigation(unittest.TestCase):
    def test_bottom_bar_autopilot_for_admins_wallets_for_the_rest(self):
        out = html.page("x", "<h1>x</h1>", "/pregled")
        bar = out[out.index("class=bbar"):]
        bar = bar[:bar.index("</nav>")]
        self.assertIn('href="/pravi-trade" class="adm-only', bar)
        self.assertIn('href="/wallets" class="nadm', bar)
        self.assertIn('href="/vise" class="vise', bar)
        self.assertNotIn("data-nav", bar)                              # Više is a page, not the drawer
        other = admstrip.strip(bar)
        self.assertNotIn("/pravi-trade", other)                        # a non-admin's copy has no trace of it
        self.assertIn('href="/wallets"', other)
        self.assertNotIn("menu-btn", out[out.index("<header"):out.index("</header>")])   # no ☰
        self.assertIn('class="on"><span class=bi>', html.bottom_bar("/tokens"))
        self.assertIn('class="vise on"', html.bottom_bar("/events"))          # pages under Više light it
        self.assertIn('class="adm-only on"', html.bottom_bar("/pravi-trade"))
        self.assertNotIn(" on", html.bottom_bar("/")[html.bottom_bar("/").index('href="/vise"'):][:30])

    def test_vise_has_17_rows_and_every_page_stays_reachable(self):
        _, body = html.vise_page({})
        rows = body[:body.index("ms-note")].count("<a href=")
        self.assertEqual(rows, 17)                                     # 4 + 5 + 3 + 2 + Sustav, Postavke, Odjava
        _, sub = html.vise_page({}, "sustav")
        sustav = next(items for s, items in html.SECTIONS if s == "Sustav")
        for p in sustav:
            self.assertIn(f'href="{p["href"]}"', sub)
        self.assertNotIn("/usage", admstrip.strip(sub))               # admins only
        self.assertNotIn("/vise/sustav", admstrip.strip(body))
        # every page of the old menu: on Više, in its Sustav sub-page, in the side menu, or on "Sve stranice"
        side = html.side_menu("/pregled", "/pregled")
        _, mapa = html.map_page({})
        self.assertIn('href="/mapa"', body)
        for _, items in html.SECTIONS:
            for p in items:
                h = f'href="{p["href"]}"'
                self.assertTrue(h in body or h in sub or h in side or h in mapa, p["href"])
        import run_ui
        self.assertEqual(run_ui.route("/vise", {})[0], "Više")
        self.assertEqual(run_ui.route("/vise/sustav", {})[0], "Sustav")

    def test_side_menu_is_short_and_lights_vise(self):
        side = html.side_menu("/tokens", "/token/abc")
        self.assertIn('<a href="/tokens" class="on">Tokeni</a>', side)
        self.assertNotIn("<h4>", side)                                 # no 37-link groups any more
        self.assertIn('class="vise on"', html.side_menu(None, "/events"))
        self.assertIn('class="vise"', side)


if __name__ == "__main__":
    unittest.main()
