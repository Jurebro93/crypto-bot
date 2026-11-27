"""27.11. (vlasnik: nitko se ne smije prijaviti, otvoriti stranicu ili izvor stranice i iz toga s AI-jem složiti recept
obrade podataka). Users see results and plain reasons; weights, thresholds, formulas, internal services, env names and
file names stay in admin copies (class adm-only, stripped server-side by ui/admstrip) or out of user text entirely."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import roles  # noqa: E402
from ui import admstrip  # noqa: E402

# words that name how the data is processed or where it comes from internally; none may reach a non-admin
INTERNAL = re.compile(r"\b(Helius|Apify|PumpPortal|twitterapi|apidojo|tweet-scraper|kol_group|BNB_ON|"
                      r"[A-Z][A-Z0-9]{2,}_(?:KEY|ON|DB|URL|TOKEN|SECRET|ID)\b)|\w+\.(?:py|db)\b|"
                      r"log\(|P × 0,7|× pokrivenost|Σ\(|ponderirani|\bprior\b")
RECIPE = re.compile(r"(?i)težin[aeiu]?\s+\d|\d+\s*%\s+težin|×\s*0,\d|= puni bodovi|punih \d+ bodova|"
                    r"\bdo \d+ bodova\b|\(\d+ ?× ")


def _text(html):
    html = re.sub(r"(?s)<script.*?</script>", "", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class Gating(unittest.TestCase):
    def test_basic_role_hole_closed(self):
        for p in ("/strategije", "/trziste", "/market", "/dugorocno", "/ekipe", "/izlazi", "/korelacije",
                  "/strategije/x"):
            self.assertEqual(roles.deny_get(p, "osnovni"), "prijatelj", p)
            self.assertIsNone(roles.deny_get(p, "prijatelj"), p)
        for p in ("/criteria", "/learn"):
            self.assertEqual(roles.deny_get(p, "prijatelj"), "admin", p)
        for p in ("/wallets", "/tokens", "/kol", "/pregled", "/pojmovnik", "/token/x", "/wallet/x"):
            self.assertIsNone(roles.deny_get(p, "osnovni"), p)

    def test_menu_marks_them_like_the_server(self):
        from ui import html as H
        self.assertIn("r-pri", H._role_cls("/strategije"))
        self.assertIn("r-pri", H._role_cls("/dugorocno"))
        self.assertIn("r-adm", H._role_cls("/criteria"))


class UserText(unittest.TestCase):
    def test_column_tips_have_no_recipe(self):
        from ui.help import HELP
        for label, text in HELP.items():
            self.assertIsNone(INTERNAL.search(text), (label, text))
            self.assertIsNone(RECIPE.search(text), (label, text))
            self.assertNotIn("Šansa za skok 0-100: confidence ×", text)

    def test_glossary_page_for_non_admins(self):
        from ui import glossarypage
        _, body = glossarypage.page({})
        self.assertIn("adm-only", body)                       # the admin's copy still has the details
        user = _text(admstrip.strip(body))
        for m in INTERNAL.finditer(user):
            # "RPC čvor (npr. Helius)" is the general crypto glossary (public too), not our data mix
            self.assertIn("npr. Helius", user[max(0, m.start() - 12):m.end()], m.group(0))
        self.assertIsNone(RECIPE.search(user), RECIPE.search(user) and user[RECIPE.search(user).start() - 80:][:200])
        self.assertNotIn("Učenje i sustav", user)
        self.assertNotIn("smart_sell_eksplozija", user)

    def test_glossary_popup(self):
        from ui import glossary as G, glossarypage
        k = G.lookup("Moć poziva")
        full = glossarypage.fragment(k, full=True)
        plain = glossarypage.fragment(k, full=False)
        self.assertIn("Sastoji se od", full)
        self.assertNotIn("Sastoji se od", plain)
        self.assertIn(G.get(k)["short"], plain)
        sk = next(t["k"] for t in G.all_terms() if t["cat"] == "sustav")
        self.assertNotIn(G.get(sk)["name"], glossarypage.fragment(sk, "x", "y", full=False))

    def test_score_tables_are_admin_only(self):
        from ui import html as H, rangtable, sansa, confidence
        parts = [("Pogodak", 20.0, 30, "a"), ("Rast 24 h", 5.0, 20, "b"), ("Kasni pozivi", -4.0, 10, "c")]
        b = H.breakdown(parts, "Izmjereno")
        self.assertIn("Bodovi", b)
        u = admstrip.strip(b)
        self.assertNotIn("Bodovi", u)
        self.assertNotIn("/ 30", u)
        self.assertIn("Pogodak", u)                            # the plain reasons stay
        self.assertIn("Kasni pozivi", u)
        note = admstrip.strip(str(rangtable.note("wallet")))
        self.assertNotRegex(note, r"\d+ %")
        self.assertNotIn("×", note)
        sh = admstrip.strip(sansa.explain_html(42, 60, 5, 4, 1))
        self.assertNotIn("×", sh)
        self.assertIn("42", sh)
        ch = admstrip.strip(confidence.explain_html(55, [(12, "X buzz"), (-8, "rizik")]))
        self.assertNotIn("+12", ch)
        self.assertIn("X buzz", ch)

    def test_evidence_sources_are_honest_level(self):
        from ui import evidence
        for name, url in evidence.SOURCES.values():
            self.assertIsNone(INTERNAL.search(name), name)
            self.assertNotRegex(name, r"(?i)apify|dexscreener api|rugcheck")

    def test_page_source_has_no_file_names(self):
        from ui import html as H
        for n in ("CSS", "LIGHT_CSS", "MS_CSS", "BAR_CSS", "NAV_CSS", "SIMPLE_CSS"):
            self.assertNotIn("/*", getattr(H, n), n)
        menu = H._pages_json()
        for sec, items in H.SECTIONS:
            for p in items:
                self.assertIsNone(re.search(r"(?i)helius|apify|težin|pragov", p["desc"] + " " + p["kw"]), p["href"])
        self.assertNotIn("helius", menu.lower())

    def test_public_glossary_has_no_data_mix(self):
        from ui import glossary_public as P, glossary as G
        e = P.BY_EN["crypto-api"]
        self.assertNotIn("uses Helius", " ".join(str(v) for v in e.values()))
        self.assertNotIn("koristi Helius", G.TERMS["api"]["primjer"])
        self.assertNotIn("close to 35", " ".join(str(v) for v in P.BY_EN["call-power"].values()))

    def test_news_feed_has_no_service_or_cost(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "share", "novosti.json"), encoding="utf-8") as f:
            s = f.read()
        for w in ("twitterapi", "Call Analyser", "SpyDefi", "+30 bodova", "2,5× kupnje", "$0,70"):
            self.assertNotIn(w, s)


if __name__ == "__main__":
    unittest.main()
