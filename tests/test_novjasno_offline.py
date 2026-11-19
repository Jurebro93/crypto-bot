"""/novcanici-admin in plain words (20.11., vlasnik na mobitelu: "Nista ja ovdje ne razumijem..."; ui/novjasno.py):

  - the three headline answers for each data state (fixture, first night, empty), computed from the numbers
  - the copy verdict's variants (da / zasad da / zasad ne / premalo / not finished / not run) and the plurals
  - the cards' sentences, a line with no data simply absent; the measurement sentence's variants
  - no internal word in the rendered page, hostile strings escaped, the details collapsed under one block

    python3 -m unittest tests.test_novjasno_offline
"""
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_novcanici_ui_offline import Base  # noqa: E402
from ui import novadmin, novjasno as J, novpodaci as P  # noqa: E402

BANNED_ANYWHERE = ("pumpa15", "pumpa2", "i2_", "helius_day", "prije_pumpe", "Helius kr", "token-dan")
BANNED_WORDS = (r"\bCU\b", r"\bkandidat\b", r"\bkandidati\b", r"\bpumpe?\b", r"\bpumpi\b", r"\blijevak\b",
                r"\bvodstvo \(medijan\)", r"\bsignala\b", r"\bprolaz\b")


def visible(html):
    return re.sub(r"<style>.*?</style>|<script>.*?</script>|<[^>]+>", " ", html, flags=re.S)


def headline(now):
    con = P.ins_con()
    try:
        _s, pp = P.summary(con) if con is not None else ({}, {})
        return J.headline(con, pp, now, P.birdeye(con, pp, now) if con is not None else None)
    finally:
        if con is not None:
            con.close()


class Plain(unittest.TestCase):
    def check_page(self, html):
        for b in BANNED_ANYWHERE:
            self.assertNotIn(b, html, b)
        vis = visible(html)
        for rx in BANNED_WORDS:
            self.assertIsNone(re.search(rx, vis), rx)


class Fixture(Base, Plain):
    def test_three_answers(self):
        hd = headline(self.now)
        self.assertEqual(hd["found"]["text"],
                         "Našli smo 20 novčanika ili skupina novčanika koji su barem 3 puta kupili token prije nego što je "
                         "skočio i prodali dok je rastao. Za 8 od njih to se ponovilo i na novijim podacima. Još 10 "
                         "skupina ima dva takva tokena i čeka treći.")
        self.assertEqual(hd["found"]["tone"], "good")
        self.assertTrue(hd["pays"]["text"].startswith("Zasad da: u prosjeku +3,4\xa0% po kupnji nakon troška, ali raspon "
                                                      "još dira nulu. Od "))
        self.assertRegex(hd["pays"]["text"], r"smo uživo izmjerili \d+ kupnj[aeiu]: u prosjeku [+−][\d,]+\xa0% po kupnji "
                                             r"nakon troška\. Premalo je za zaključak")
        self.assertTrue(hd["pays"]["text"].endswith("Pravi novac ostaje pauziran dok ovo ne bude „Da”."))
        self.assertEqual(hd["pays"]["tone"], "warn")
        self.assertRegex(hd["next"]["text"], r"čita povijest još \d+ novčanika i traži nove skupine u tokenima koji su "
                                             r"skočili\. Cijelo vrijeme prati nove kupnje svih 30 skupina\. Svaku noć "
                                             r"ponovno provjerava odgovor s novim podacima\. Od tebe sada ne treba ništa\.")

    def test_first_screen_cards_and_details(self):
        _t, html = novadmin.page({}, "Jure", self.now)
        self.check_page(html)
        head = html.index("Što smo našli")
        self.assertLess(head, html.index("Deset najzanimljivijih novčanika"))
        self.assertLess(html.index("Kako čitati ovu stranicu: zeleno = dobro za nas"), html.index('id="najbolji"'))
        self.assertLess(html.index('id="iskljuceni"'), html.index("<summary>Detalji za provjeru</summary>"))
        self.assertNotIn("<table", html[:html.index("<details class=nj-det")].split('id="najbolji"')[0])   # no table first
        self.assertIn("<details class=nj-det><summary>Detalji za provjeru</summary>", html)       # collapsed
        self.assertEqual(html.count("<article class=nj-c>"), 10)
        self.assertIn("Prikaži sve (30)", html)
        self.assertIn('href="/novcanici-admin?tablica=1#grupe">Tablica za provjeru', html)
        cards = re.findall(r"<article class=nj-c>(.*?)</article>", html, re.S)
        self.assertIn("potvrđen</span>", cards[0])
        self.assertIn("čeka potvrdu</span>", cards[-1])
        first = visible(cards[0])
        self.assertRegex(first, r"Skupina je kupila prije skoka na \d+ tokena: ")
        self.assertRegex(first, r"U prosjeku su kupovali oko \d+ (minut[aeu]|sat[ai]?|dana?) prije skoka\.")
        self.assertRegex(first, r"Na tim su tokenima (zaradili|izgubili) oko [\d,]+ SOL\.")
        self.assertIn("Povezan s još 69 novčanika", first)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("Izbacili smo 1\xa0234 novčanika koji su se pojavili samo kod jednog skoka, 2 bota", html)
        self.assertIn("1 novčanik koji kupuje gotovo svaki token", html)
        for intro in novadmin.INTRO.values():
            self.assertIn(intro, html)
        _t, opened = novadmin.page({"tablica": "1"}, "Jure", self.now)
        self.assertIn("<details class=nj-det open><summary>Detalji za provjeru</summary>", opened)

    def test_show_all_pages_in_the_same_card_style(self):
        _t, html = novadmin.page({"sve": "1"}, "Jure", self.now)
        self.check_page(html)
        self.assertIn("Svi novčanici i skupine (30)", html)
        self.assertEqual(html.count("<article class=nj-c>"), J.ALL_N)
        self.assertIn("Stranica 1 od 2 · 30 ukupno", html)
        _t, p2 = novadmin.page({"sve": "1", "sp": "2"}, "Jure", self.now)
        self.assertEqual(p2.count("<article class=nj-c>"), 10)
        self.assertIn("← Samo deset najzanimljivijih", p2)
        _t, bad = novadmin.page({"sve": "1", "sp": "x' OR 1"}, "Jure", self.now)
        self.assertIn("Stranica 1 od 2", bad)


class FirstNight(Base, Plain):
    def setUp(self):
        super().setUp()
        import seed_novcanici as SEED
        SEED.seed(self.paths, now=self.now, first_night=True)

    def test_three_answers(self):
        hd = headline(self.now)
        self.assertTrue(hd["found"]["text"].startswith("Našli smo 20 novčanika ili skupina novčanika"))
        self.assertRegex(hd["pays"]["text"], r"^Još ne znamo: test još nije gotov \(izračunato do \d+\.\d+\.\)\. Uživo još "
                                             r"nismo zabilježili nijednu njihovu kupnju\. Pravi novac ostaje pauziran")
        self.assertIn("Sutra ujutro ovdje će pisati isplati li se kopirati ih.", hd["next"]["text"])
        self.assertIn("Što trebaš napraviti ti: ako želiš drugu provjeru novčanika iz drugog izvora (Birdeye), treba "
                      "postaviti njegov ključ na serveru.", hd["next"]["text"])
        _t, html = novadmin.page({}, "Jure", self.now)
        self.check_page(html)
        for c in re.findall(r"<article class=nj-c>(.*?)</article>", html, re.S):
            self.assertNotIn("Od kad ga pratimo", c)                       # no measurement yet: the line is absent
            self.assertNotIn("Od kad ih pratimo", c)
            self.assertNotIn("Druga provjera", c)                          # Birdeye read nothing yet
            self.assertNotIn("nije još izmjereno", c)


class Empty(Base, Plain):
    EMPTY = True

    def test_three_answers(self):
        hd = headline(self.now)
        self.assertEqual(hd["found"]["text"], "Još tražimo. Prvo pretraživanje je noćas, od 1 do 6 sati.")
        self.assertTrue(hd["pays"]["text"].startswith("Još ne znamo: test kopiranja još nije napravljen, prvi rezultat "
                                                      "stiže nakon noćne obrade."))
        self.assertIn("prvi put pregledava tokene koji su skočili", hd["next"]["text"])
        _t, html = novadmin.page({}, "Jure", self.now)
        self.check_page(html)
        self.assertIn("Najzanimljiviji novčanici", html)
        self.assertIn("Još nikoga nismo izbacili: prvo pretraživanje je noćas.", html)
        self.assertNotIn("<article", html)

    def test_still_searching_with_a_summary(self):
        found = J.found(None, {"covered15": 12, "covered2": 3, "pumps15": 40, "pumps2": 20, "min_tokens": 3})
        self.assertEqual(found["text"], "Još tražimo. Pregledali smo 15 od 60 tokena koji su skočili, i još nismo našli "
                                        "novčanik ili skupinu novčanika koja je barem 3 puta kupila prije skoka i prodala "
                                        "dok je rastao.")


class Words(unittest.TestCase):
    def test_copy_verdict_variants(self):
        def pp(n, ev, lo, hi, **kw):
            return {"copy": {"60s": {"svi": {"n": n, "ev_pct": ev, "lo_pct": lo, "hi_pct": hi}}}, "min_n": 20, **kw}
        self.assertEqual(J.copy_verdict(pp(64, 4.2, 0.6, 8.0))[1:],
                         ("Da: +4,2\xa0% po kupnji nakon troška, i u najlošijem slučaju iz raspona iznad nule.", "da"))
        self.assertEqual(J.copy_verdict(pp(64, 4.2, -0.6, 8.0))[1],
                         "Zasad da: u prosjeku +4,2\xa0% po kupnji nakon troška, ali raspon još dira nulu.")
        self.assertEqual(J.copy_verdict(pp(64, -3.1, -6.0, -0.2))[:2],
                         ("bad", "Zasad ne: kopiranje bi u prosjeku gubilo 3,1\xa0% po kupnji nakon troška."))
        self.assertEqual(J.copy_verdict(pp(64, -1.0, -5.0, 2.0))[2], "zasad ne")
        self.assertEqual(J.copy_verdict(pp(7, 4.2, 0.6, 8.0))[1], "Još ne znamo: premalo primjera (7, treba 20).")
        self.assertEqual(J.copy_verdict(pp(64, 4.2, 0.6, 8.0, copy_progress="kopija: izračunato do 05.11. (3 od 45 "
                                                                         "dana)"))[1],
                         "Još ne znamo: test još nije gotov (izračunato do 5.11.).")
        self.assertEqual(J.copy_verdict({})[2], "ne znamo")
        with mock.patch.object(P, "pause_on", return_value=True), mock.patch.object(J, "mjera_stats",
                                                                                  return_value=(None, None)):
            self.assertIn("kopiranje pravim novcem možeš uključiti samo ti", J.pays(pp(64, 4.2, 0.6, 8.0))["text"])
            self.assertIn("Pravi novac ostaje pauziran dok ovo ne bude „Da”.", J.pays(pp(64, -3, -6, -1))["text"])

    def test_plurals_and_units(self):
        self.assertEqual([J.cnt(n, "token", "tokena", "tokena") for n in (1, 2, 5, 11, 21, 22, 112)],
                         ["1 token", "2 tokena", "5 tokena", "11 tokena", "21 token", "22 tokena", "112 tokena"])
        self.assertEqual([J.when_lead(m) for m in (1, 3, 25, 60, 180, 300, 2 * 1440, None)],
                         ["oko 1 minutu", "oko 3 minute", "oko 25 minuta", "oko 60 minuta", "oko 3 sata", "oko 5 sati",
                          "oko 2 dana", None])
        with mock.patch.object(J, "_counts", return_value=(1, 1, 0)):
            self.assertTrue(J.found(object(), {"min_tokens": 3})["text"].startswith(
                "Našli smo 1 novčanik ili skupinu novčanika koji je barem 3 puta kupio token prije nego što je skočio i "
                "prodao dok je rastao."))
        with mock.patch.object(J, "_counts", return_value=(21, 0, 1)):
            t = J.found(object(), {"min_tokens": 3})["text"]
        self.assertTrue(t.startswith("Našli smo 21 novčanik ili skupinu novčanika koji su"))
        self.assertIn("Ni za jednu skupinu se to još nije ponovilo na novijim podacima.", t)
        self.assertIn("Još 1 skupina ima dva takva tokena", t)

    def test_card_sentences_and_absent_lines(self):
        g = {"owner": "o", "members": ["w1"], "cls": "prije_pumpe", "n_tokens": 4, "n_pumps15": 2, "med_lead_min": 190,
             "pnl_sol": 2.04, "confirmed_ts": 1}
        ps = [{"token": f"T{i}", "symbol": s, "tier": "pumpa15" if i < 2 else "pumpa2"}
              for i, s in enumerate(("WIF", "SPX", "GIGA", "MICHI"))]
        out = J.card_sentences(g, ps)
        self.assertEqual(out, ["Kupio je prije skoka na 4 tokena: SPX, WIF, GIGA, MICHI (2 od njih vrijedila su 15 M $ "
                               "ili više). U prosjeku je kupovao oko 3 sata prije skoka. Na tim je tokenima zaradio oko "
                               "2 SOL."])
        full = J.card_sentences(g, ps, hist=(1, 1, 68, 0.31, 1.2), be=(4, 3), mj={"n": 3, "measured": 3, "mean01": 0.04})
        self.assertEqual(full[1:], ["Njegova cijela povijest: 68 zatvorenih tradeova, 31\xa0% u plusu, ukupno +1,2\xa0SOL.",
                                    "Druga provjera (Birdeye): među najboljim trgovcima na 3 od 4 provjerena tokena.",
                                    "Od kad ga pratimo: 3 nove kupnje, prosjek +4,0\xa0% nakon troška."])
        g2 = dict(g, members=["a", "b"], pnl_sol=None, med_lead_min=None, cls="kandidat", n_tokens=2, n_pumps15=0)
        s = J.card_sentences(g2, [])[0]
        self.assertEqual(s, "Skupina je kupila prije skoka na 2 tokena. Treba joj još jedan takav token da uđe na popis. "
                            "Koliko su na tim tokenima zaradili, nepoznato je.")

    def test_measurement_sentence_variants(self):
        base = {"signals": 12, "measured": 9, "mean01": 0.052, "token_days": 9, "lo": -0.01, "hi": 0.1}
        self.assertEqual(J.mjera_sentence(base, 1794700000),
                         f"Od {J.day(1794700000)} smo izmjerili 9 kupnji praćenih novčanika: u prosjeku +5,2\xa0% po "
                         "kupnji nakon troška. Premalo je za zaključak (treba 100 dana s kupnjama, sada 9).")
        self.assertIn("To je dokazano: i u najlošijem slučaju iz raspona iznad nule.",
                      J.mjera_sentence(dict(base, token_days=140, lo=0.01), None))
        self.assertIn("raspon u kojem je pravi rezultat vjerojatno još dira nulu",
                      J.mjera_sentence(dict(base, token_days=140), None))
        self.assertIn("nijedna još nije zatvorena", J.mjera_sentence(dict(base, measured=0), None))
        self.assertEqual(J.mjera_sentence({"signals": 0}, None), "Uživo još nismo zabilježili nijednu kupnju praćenih "
                                                                 "novčanika.")


if __name__ == "__main__":
    unittest.main()
