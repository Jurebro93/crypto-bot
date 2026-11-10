"""Tokeni i jedan token u mirnom izgledu (10.11., Jure: "Ostalo mi se sviđa"; ui-prijedlozi.md 3.2, 4.2, 4.3; makete
tokeni.html, tokeni-popis.html, token.html): reci popisa, skupina "U zoni ulaza", stanja popisa, graf mcap-a s točkama
poziva, presuda tokena, provjera ruga kao reci, list "Kupi" i Stupci za redove u mreži. Bez mreže i bez baza."""
import os
import re
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import cols, narrative, quickbuy, tokenchart, tokens, topcheckui  # noqa: E402
from ui import redak as R  # noqa: E402

NOW = 1_800_000_000
NB = R.NBSP
MINT = "Q9CzZ4iT5XTkrMq18opv2WB1PFEmtu7yJZ1Sr4sTpump"
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


def row(tok, sym, conf=60, sansa=50, last=NOW - 180, mcap=200_000, liq=40_000, rug=None, top=None, feats=None, det=None,
        hard=False, events=(), collapse=None):
    return {"token": tok, "symbol": sym, "conf": conf, "sansa": sansa, "last_seen": last, "signal_ts": last, "mcap": mcap,
            "liq": liq, "rug": {"verdict": rug, "data": {}} if rug else None, "top": top, "features": feats or {},
            "det": det or {}, "conf_parts": [], "checks": [], "hard": hard, "events": list(events), "collapse": collapse,
            "tier": {}, "hype": 50}


class Words(unittest.TestCase):
    def test_plural_and_subtitle(self):
        self.assertEqual(tokens.plural(21, "token", "tokena", "tokena"), "token")
        self.assertEqual(tokens.plural(11, "token", "tokena", "tokena"), "tokena")
        self.assertEqual(tokens.plural(3, "a", "b", "c"), "b")
        self.assertEqual(tokens.plural(13, "a", "b", "c"), "c")
        self.assertEqual(tokens.analysed_line(21, 3), "21 token analiziran u zadnja 24 h · 3 u zoni ulaza")
        self.assertEqual(tokens.analysed_line(23, 0), "23 tokena analizirana u zadnja 24 h")
        self.assertEqual(tokens.analysed_line(5, 0), "5 tokena analizirano u zadnja 24 h")

    def test_short_reason_from_radar_sentences(self):
        self.assertEqual(tokens.shorten("Novac ulazi brzo: volumen u zadnjem satu je 3x ili više likvidnosti."), "Novac ulazi brzo")
        self.assertEqual(tokens.shorten("3 provjerenih smart walleta je među prvim kupcima."), "3 smart walleta")
        self.assertEqual(tokens.shorten("1 provjerenih smart walleta je među prvim kupcima."), "1 smart wallet")
        self.assertEqual(tokens.shorten("Praćeni influenceri su ga objavili na X-u."), "Zvali influenceri na X-u")
        self.assertEqual(tokens.shorten("Cijena raste: oko +118% u zadnjem satu."), f"Cijena +118{NB}% u 1 h")
        self.assertEqual(tokens.shorten("KOL walleti ga trejdaju (3 na pump.fun)."), "KOL walleti ga trejdaju")
        self.assertEqual(tokens.shorten("Objavljen u Telegram call kanalima."), "Objavljen u Telegram call kanalima")
        r = row("A", "A", feats={"turnover": 1.0, "smart_money": 1}, det={"smart_buyers": ["w1", "w2", "w3"]})
        self.assertIn(tokens.short_reason(r), ("Novac ulazi brzo", "3 smart walleta"))

    def test_rug_word_and_fresher_mcap(self):
        self.assertEqual(tokens.rug_word(row("A", "A", rug="OPREZ")), "oprez")
        self.assertEqual(tokens.rug_word(row("A", "A", top={"verdict": "oprez"})), "oprez")
        self.assertEqual(tokens.rug_word(row("A", "A", rug="PROLAZI")), "prolazi")
        self.assertEqual(tokens.rug_word(row("A", "A")), "")
        r = row("A", "A", mcap=100_000, liq=10_000, last=NOW - 600)
        self.assertEqual(tokens.mcap_now(r, {"has_pair": 1, "mcap": 120_000, "liq": 20_000, "checked_ts": NOW - 60}), (120_000, 20_000))
        self.assertEqual(tokens.mcap_now(r, {"has_pair": 1, "mcap": 120_000, "checked_ts": NOW - 3600}), (100_000, 10_000))
        self.assertEqual(tokens.mcap_now(r, None), (100_000, 10_000))

    def test_zone_same_rule_as_pregled(self):
        self.assertTrue(tokens.in_zone(412_000, 412_000))
        self.assertTrue(tokens.in_zone(480_000, 412_000))
        self.assertFalse(tokens.in_zone(520_000, 412_000))     # +26 %: wait for a pullback
        self.assertFalse(tokens.in_zone(320_000, 412_000))     # −22 %: falling
        self.assertFalse(tokens.in_zone(None, 412_000))
        self.assertEqual(tokens.zone_tokens(None, NOW, picks={"A": 1.0}), {"A": 1.0})


class ListPage(unittest.TestCase):
    def _page(self, rows, picks=None, view="novi"):
        with mock.patch("ui.data.stage"):
            return tokens.page({}, view=view, now=NOW, rows=rows, st={}, picks=picks or {})[1]

    def test_rows_groups_and_no_repeated_box(self):
        rows = [row("GIGA", "GIGAFROG", conf=94, mcap=412_000, feats={"turnover": 1.0}),
                row("ARIA", "ARIA", conf=83, mcap=268_000),
                row("TURB", "TURBOX", conf=73, mcap=734_000, rug="OPREZ"),
                row("LOW", "WEAK", conf=20),                                       # below 35: not listed
                row("BAD", "RUGGED", conf=80, rug="ODBAČEN"),                     # rejected: one tap below
                row("OLD", "OLDIE", conf=70, last=NOW - 3 * 86400)]               # older: one tap below
        html = self._page(rows, picks={"GIGA": 412_000})
        self.assertIn("U zoni ulaza", html)
        self.assertIn("današnji prijedlog", html)
        self.assertIn('id="tk-ostali"', html)
        self.assertLess(html.index("GIGAFROG"), html.index("TURBOX"))
        self.assertIn("Rug: oprez", html)
        self.assertNotIn(">WEAK<", html)
        self.assertIn("Odbačeni · 1", html)
        self.assertIn("RUGGED", html.split('id="tk-odb"')[1])
        self.assertIn("OLDIE", html.split('id="tk-st"')[1])
        self.assertIn("5 tokena analizirano u zadnja 24 h · 1 u zoni ulaza", html)
        self.assertIn('href="/token/GIGA"', html)
        self.assertIn('data-cf="94"', html)
        self.assertIn("Simbol ili adresa", html)
        self.assertIn("Poredaj i filtriraj", html)
        self.assertIn("Što znači pouzdanost", html)
        # 10.11. (Jure, prijedlog 3.2): no "Prijedlog za danas", no "Dobro došao", no "Confidence", no ⓘ, no emoji
        for gone in ("Prijedlog za danas", "Dobro došao", "Confidence", "ⓘ", "📋"):
            self.assertNotIn(gone, html)
        self.assertFalse(EMOJI.search(html.split("<script>")[0]))

    def test_small_mcap_is_marked(self):
        html = self._page([row("S", "SMALL", conf=60, mcap=25_000)])
        self.assertIn("Ispod 30k $", html)

    def test_empty_states(self):
        html = self._page([])
        self.assertIn("Trenutno nema novih tokena", html)
        self.assertIn('href="/tokens/jaki"', html)
        self.assertIn("Zalijepi adresu", html)              # search without a match (shown by the script)
        with mock.patch.object(tokens, "_strong_rows", return_value=[]):
            html = self._page([], view="jaki")
        self.assertIn("Popis jakih tokena još se slaže", html)
        with mock.patch.object(tokens, "_strong_rows", return_value=[("M1", "JUP", 81.4, 2.5e9, "stalan volumen")]):
            html = self._page([], view="jaki")
        self.assertIn("JUP", html)
        self.assertIn(f"2,5B{NB}$", html)
        self.assertIn('href="/token/M1"', html)

    def test_switch_is_the_calm_segment(self):
        html = tokens.switch("/dugorocno")
        self.assertIn('class="ms-seg"', html)
        self.assertIn('href="/dugorocno" class="on"', html)


class Chart(unittest.TestCase):
    def test_series_pulse_wins_near_snapshots(self):
        snaps = [{"ts": NOW - 7200, "mcap": 100.0, "price": 1.0}, {"ts": NOW - 600, "mcap": 999.0, "price": 9.99}]
        pulse = [{"ts": NOW - 700, "mcap": 200.0, "price": 2.0}, {"ts": NOW - 60, "mcap": 210.0, "price": 2.1}]
        pts = tokenchart.series("x", snaps=snaps, pulse=pulse)
        self.assertEqual(pts, [(NOW - 7200, 100.0), (NOW - 700, 200.0), (NOW - 60, 210.0)])
        # a snapshot without mcap is scaled from its price
        pts = tokenchart.series("x", snaps=[{"ts": NOW - 9000, "mcap": None, "price": 1.0}], pulse=pulse)
        self.assertEqual(pts[0], (NOW - 9000, 100.0))

    def test_ticks_and_labels(self):
        self.assertEqual(tokenchart.ticks(180_000, 420_000), [200_000, 300_000])
        self.assertEqual(tokenchart.ticks(5, 5), [])
        self.assertEqual(tokenchart.short_usd(200_000), "200k")
        self.assertEqual(tokenchart.short_usd(1_500_000), "1,5M")
        self.assertEqual(tokenchart.short_usd(2_000_000), "2M")

    def test_chart_with_call_dots_and_ranges(self):
        pts = [(NOW - 86400 + i * 1200, 200_000 + i * 2500) for i in range(73)]
        marks = [(NOW - 3000, "bitecong", 330_000), (NOW - 600, "tg:kanal", 380_000), (NOW - 30 * 86400, "old", 1)]
        html = tokenchart.chart_html("x", "GIGA", NOW, pts=pts, marks=marks)
        self.assertIn('data-r="24h"', html)
        self.assertIn("<svg", html)
        self.assertIn("@bitecong, prvi poziv", html)
        self.assertIn("kanal (Telegram)", html)
        self.assertIn("poziv influencera", html)
        self.assertIn(">sada<", html)
        self.assertEqual(html.count('class="tc-fig" data-r='), 1)          # only the 24 h figure is visible
        self.assertIn('class="tc-fig" data-r="24h"', html)
        self.assertEqual(tokenchart.chart_html("x", "", NOW, pts=[(NOW - 60, 1.0)], marks=[]), "")

    def test_figure_needs_two_points(self):
        self.assertEqual(tokenchart.figure([(NOW - 60, 5.0)], [], 3600, NOW, "1h"), "")


class Verdict(unittest.TestCase):
    def test_order_of_what_stops_a_buy(self):
        self.assertEqual(narrative.token_verdict(90, 400_000, locked="token je rugan"), ("Rugan, ne ulazi", "bad"))
        self.assertEqual(narrative.token_verdict(90, 400_000, rug_verdict="ODBAČEN"), ("Ne ulazi: rug", "bad"))
        self.assertEqual(narrative.token_verdict(90, 400_000, top_verdict="pao"), ("Pao na provjeri ruga", "bad"))
        self.assertEqual(narrative.token_verdict(90, 400_000, h1=-60), ("Pada, ne ulazi sada", "bad"))
        self.assertEqual(narrative.token_verdict(90, 25_000), ("Ispod 30k $", ""))
        self.assertEqual(narrative.token_verdict(90, 400_000, zone_x=1.0), ("U zoni ulaza", "good"))
        self.assertEqual(narrative.token_verdict(90, 400_000, zone_x=1.3), ("Pričekaj povlačenje", "warn"))
        self.assertEqual(narrative.token_verdict(90, 400_000, zone_x=0.7), ("Pada, ne juri", "warn"))
        self.assertEqual(narrative.token_verdict(90, 400_000), ("Dobra šansa", "good"))
        self.assertEqual(narrative.token_verdict(40, 400_000), ("Umjerena šansa", "warn"))
        self.assertEqual(narrative.token_verdict(10, 400_000), ("Premalo dokaza", ""))

    def test_za_protiv_short_names(self):
        keyed = [("hype", 30.0, "Hype ocjena 50/100"), ("ozbiljan", 12, "Ozbiljan"), ("smart_money", 10, "Smart"),
                 ("rug_ok", 10, "Rug ok"), ("liq_low", -10, "Mala"), ("holders_nepoznato", 0, "nepoznato")]
        za, protiv = narrative.za_protiv(keyed)
        self.assertEqual(za, ["ozbiljan projekt", "smart walleti", "rug prolazi"])   # hype is the base, not a "za"
        self.assertEqual(protiv, ["mala likvidnost"])
        # a learned model's points win (matched by text)
        za, protiv = narrative.za_protiv(keyed, scored=[(-3.0, "Smart")])
        self.assertIn("smart walleti", protiv)
        self.assertEqual(narrative.za_protiv_line([], []), ("ništa izmjereno.", "ništa zabilježeno."))

    def test_one_sentence(self):
        self.assertEqual(narrative.zone_sentence(1.01), "Cijena je ista kao kod analize.")
        self.assertEqual(narrative.zone_sentence(1.12), f"Cijena je 12{NB}% iznad analize.")
        self.assertEqual(narrative.zone_sentence(None), "")
        s = narrative.token_sentence(["Novac ulazi brzo: volumen je 3x likvidnosti."], "U zoni ulaza", 1.0)
        self.assertEqual(s, "Novac ulazi brzo: volumen je 3x likvidnosti. Cijena je ista kao kod analize.")
        self.assertEqual(narrative.token_sentence([], "x", why_bad="Rugan: pao 90 %"), "Rugan: pao 90 %.")
        self.assertIn("pala 60", narrative.token_sentence([], "x", h1=-60))


class RugRows(unittest.TestCase):
    TOP = {"verdict": "prolazi", "ts": NOW - 120, "rc_ts": NOW - 100,
           "safety": {"fails": [], "warns": [], "oks": [], "checks": {
               "mint": ["ok", "mint authority ugašen"], "lp": ["ok", "likvidnost na launchpadu (pump.fun), tvorac je ne može izvući"],
               "holderi": ["ok", "top 10 holdera drži 21%"], "honeypot": ["ok", "testna prodaja prolazi (97% vrijednosti)"],
               "dev": ["warn", "dev drži 7%"]}}}

    def test_check_rows_short_values(self):
        rows = dict((k, (v, kind)) for k, v, kind in topcheckui.check_rows(self.TOP))
        self.assertEqual(rows["Mint authority"], ("ugašen", ""))
        self.assertEqual(rows["Likvidnost"], ("na launchpadu", ""))
        self.assertEqual(rows["Top 10 holdera"], ("21 %", ""))
        self.assertEqual(rows["Probna prodaja"], ("prolazi, vraća 97 %", ""))
        self.assertEqual(rows["Dev"], ("drži 7 %", "warn"))
        self.assertEqual(topcheckui.check_state(self.TOP), ("good", "Prolazi sve provjere", NOW - 100))
        bad = {"verdict": "pao", "ts": NOW, "safety": {"fails": ["mint authority aktivan"], "checks": {}}}
        self.assertEqual(topcheckui.check_state(bad)[:2], ("bad", "Pao: mint authority aktivan"))
        self.assertIsNone(topcheckui.check_state(None))
        self.assertEqual(topcheckui.check_rows(None), [])

    def test_rug_report_rows(self):
        rug = {"verdict": "OPREZ", "checked_at": NOW - 600, "data": {"flags": ["bundle 18%"], "authorities": {},
               "holders": {"top10_pct": 23.5}, "dev": {"hold_pct": 1.8, "sold_pct": 10}, "launch": {"bundle_pct": 18}}}
        rows = {k: (v, kind) for k, v, kind in topcheckui.rug_rows(rug)}
        self.assertEqual(rows["Mint authority"], ("ugašen", ""))
        self.assertEqual(rows["Top 10 holdera"], ("23,5 %", ""))
        self.assertEqual(rows["Bundle"], ("18 %", "warn"))
        self.assertEqual(topcheckui.rug_state(rug), ("warn", "Oprez: bundle 18%", NOW - 600))
        self.assertEqual(topcheckui.rug_state({"verdict": "ODBAČEN", "data": {"hard_fails": ["dev rug"]}})[:2],
                         ("bad", "Odbačen: dev rug"))
        self.assertEqual(topcheckui.rug_rows(None), [])


class BuySheetAndColumns(unittest.TestCase):
    def test_buy_sheet(self):
        html = quickbuy.buy_sheet(MINT, "GIGAFROG")
        self.assertIn('action="/natjecanje/buy"', html)
        self.assertIn(f'value="/token/{MINT}"', html)
        self.assertIn("Kupi na Natjecanju", html)
        self.assertIn(f"/natjecanje?dca={MINT}#dca", html)
        self.assertIn('class="tk-o adm-only" href="/pravi-trade#kupi-odmah"', html)   # real money: owner only, a link
        self.assertNotIn("/pravi-trade/buy", html)
        locked = quickbuy.buy_sheet(MINT, "GIGAFROG", "token je rugan")
        self.assertIn("Kupnja je zaključana: token je rugan.", locked)
        self.assertNotIn("<form", locked)
        self.assertEqual(quickbuy.buy_sheet("../x", "X"), "")
        from ui import admstrip
        self.assertNotIn("Autopilot, ručno", admstrip.strip(html))

    def test_grid_chooser(self):
        html = cols.grid_chooser("tk-root", [("l", "Likv.", "92px"), ("t", "Zadnji signal", "112px")], fixed_left="1fr 96px")
        self.assertIn('data-gc="tk-root"', html)
        self.assertIn('#tk-root.gc-hide-l [data-col="l"]{display:none!important}', html)
        self.assertIn('"l":"92px"', html)
        self.assertIn("Stupci", html)


class TokenPage(unittest.TestCase):
    """pages.token with every source mocked: the calm order and nothing of the old look."""

    def _render(self, **kw):
        from ui import data, evidence, pages
        sig = {"ts": NOW - 300, "token": MINT, "symbol": "GIGAFROG", "name": "Giga Frog", "score": 60, "price": 0.000412,
               "mcap": 412_000, "liquidity": 61_000, "features": '{"turnover": 1.0, "smart_money": 1}', "weights": "{}",
               "sources": "dex", "url": None}
        rug = {"mint": MINT, "symbol": "GIGAFROG", "verdict": kw.get("verdict", "PROLAZI"), "score": 94, "checked_at": NOW - 600,
               "top10_pct": 23.5, "data": {"name": "Giga Frog", "hard_fails": kw.get("fails", []), "flags": [], "positives": [],
                                           "authorities": {}, "holders": {"top10_pct": 23.5}}}
        pair = {"url": "https://dexscreener.com/solana/pair", "dexId": "pumpswap", "baseToken": {"name": "Giga Frog", "symbol": "GIGAFROG"},
                "priceUsd": "0.000412", "marketCap": 412_000, "liquidity": {"usd": 61_000}, "volume": {"h1": 41_000},
                "txns": {"h1": {"buys": 166, "sells": 78}}, "priceChange": {"m5": 3.7, "h1": 18.4, "h6": 59.2, "h24": 142.0},
                "pairCreatedAt": (time.time() - 11 * 3600) * 1000}
        with mock.patch.object(data, "event_tokens", return_value=[]), \
                mock.patch.object(data, "hype_signals", return_value=[sig]), \
                mock.patch.object(data, "rug_reports", return_value=[rug]), \
                mock.patch.object(data, "paper_candidates", return_value=[]), \
                mock.patch.object(data, "sightings", return_value=[]), \
                mock.patch.object(data, "token_pulse", return_value=[]), \
                mock.patch.object(data, "hype_snapshots", return_value=[]), \
                mock.patch.object(data, "token_tier", return_value=None), \
                mock.patch.object(data, "q", return_value=[]), \
                mock.patch.object(evidence, "live_pair", return_value=pair), \
                mock.patch.object(evidence, "details", return_value=(0, {"smart_buyers": ["a", "b", "c"]})), \
                mock.patch.object(evidence, "tweets", return_value=(0, [])), \
                mock.patch.object(tokenchart, "calls", return_value=[]), \
                mock.patch("ui.kol.token_section", return_value=""), \
                mock.patch("ui.quickbuy.dugo_info", return_value=(None, None)), \
                mock.patch("topcheck.store.read_all", return_value={}), \
                mock.patch("rugfilter.archive.get", return_value=None), \
                mock.patch("rugfilter.archive.recovered", return_value=None), \
                mock.patch("rugfilter.collapse.peaks", return_value={}), \
                mock.patch("live.pulse.token_html", return_value=""):
            return pages.token(MINT, kw.get("qs", {}))

    def test_order_and_words(self):
        title, html = self._render()
        self.assertEqual(title, "GIGAFROG")
        order = ['class="tkp-back"', ">GIGAFROG<", "ms-panel ms-verdict", 'class="tkp-btns"', ">Tržište<", ">Tko ga je zvao<",
                 ">Smart walleti<", ">Provjera ruga<", ">Kako je dobio ocjenu<"]
        pos = [html.index(x) for x in order]
        self.assertEqual(pos, sorted(pos))
        self.assertIn("Giga Frog · ", html)
        self.assertIn(f"412k{NB}$", html)
        self.assertIn(f"+142{NB}%", html)
        self.assertIn("da, PumpSwap", html)
        self.assertIn(f"0,000412{NB}$", html)
        self.assertIn("166 / 78", html)
        self.assertIn("Za:</b> ", html)
        self.assertIn(">DexScreener</a> · ", html)
        self.assertIn('id="qb-sheet"', html)
        self.assertIn("Slojevi analize", html)
        self.assertIn('<h2 data-sec=""', html)
        top = html.split("Kako je dobio ocjenu")[0]
        for gone in ("Confidence", "Šansa <", "ⓘ", "💀", "🏆", "Natjecanje</h2>", "Svježa provjera"):
            self.assertNotIn(gone, top)

    def test_rejected_token_is_locked_in_words(self):
        _, html = self._render(verdict="ODBAČEN", fails=["dev je izvukao likvidnost"])
        self.assertIn("Ne ulazi: rug", html)
        self.assertIn("Rug filter ga je odbacio: dev je izvukao likvidnost.", html)

    def test_league_message_on_top(self):
        _, html = self._render(qs={"ok": "Kupljeno"})
        self.assertIn('class="tkp-msg"', html)
        self.assertLess(html.index("Kupljeno"), html.index('class="tkp-back"'))


if __name__ == "__main__":
    unittest.main()
