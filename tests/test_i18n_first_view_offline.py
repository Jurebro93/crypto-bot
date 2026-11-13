"""English app on the first view (13.11., Jure: the token page "bude na engleskom, a tekst je i sav kontent na
hrvatskom"): token names and short addresses as {n}, sentence-by-sentence lookup, the visitor's wait for new text,
no cached partial copy, English number formats, the token page fully English from the checked-in dictionary.
No network, no API key (the model is a stub)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["I18N_OFF"] = "1"

from ui import i18n, pagecache  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        os.environ["DATA_DIR"] = tempfile.mkdtemp()
        i18n._static = {"Kupi {0} odmah": "Buy {0} now", "Natjecanje": "Competition",
                        "Prva rečenica je ovdje.": "The first sentence is here.",
                        "Druga rečenica {0} puta.": "The second sentence {0} times.",
                        "<1>Stanje:</1> token je star {0} h;": "<1>Now:</1> the token is {0} h old;",
                        "mcap ${0}k.": "mcap ${0}k."}
        i18n._auto = {}
        i18n._pending.clear()
        i18n._failed.clear()
        i18n._inflight.clear()
        i18n._day.update(d=None, n=0)
        self.tok = i18n.LANG.set("en")

    def tearDown(self):
        i18n.LANG.reset(self.tok)
        i18n._static = i18n._auto = None
        i18n._pending.clear()


class Templating(Base):
    def test_page_names_are_placeholders(self):
        out = i18n.translate('<h1 translate=no>GIGAFROG</h1><p>Kupi GIGAFROG odmah</p><p>Prodaj GIGAFROG sutra ujutro</p>')
        self.assertIn("<p>Buy GIGAFROG now</p>", out)
        self.assertIn("Prodaj {0} sutra ujutro", i18n._pending)          # one entry for every token
        self.assertNotIn("Prodaj GIGAFROG sutra ujutro", i18n._pending)

    def test_plain_entry_wins_over_the_name(self):
        out = i18n.translate("<b translate=no>Natjecanje</b><h2>Natjecanje</h2>")
        self.assertIn("<h2>Competition</h2>", out)

    def test_short_addresses_are_values(self):
        i18n.translate("<p>Novčanik 7xKX…9fGh je kupio rano</p><p>Novčanik Ab3d…Zz12 je kupio rano</p>")
        self.assertEqual(list(i18n._pending), ["Novčanik {0} je kupio rano"])


class Sentences(Base):
    def test_paragraph_from_known_sentences(self):
        out = i18n.translate("<p>Prva rečenica je ovdje. Druga rečenica 5 puta.</p>")
        self.assertIn("<p>The first sentence is here. The second sentence 5 times.</p>", out)
        self.assertEqual(i18n.last_missing(), 0)

    def test_only_the_missing_sentence_is_queued(self):
        i18n.translate("<p>Prva rečenica je ovdje. Treća rečenica je nova.</p>")
        self.assertEqual(list(i18n._pending), ["Treća rečenica je nova."])
        self.assertEqual(i18n.last_missing(), 1)

    def test_placeholders_renumbered_per_sentence(self):
        out = i18n.translate("<p><b>Stanje:</b> token je star 11 h; mcap $412k.</p>")
        self.assertIn("<p><b>Now:</b> the token is 11 h old; mcap $412k.</p>", out)

    def test_no_cut_inside_brackets_or_after_a_number(self):
        self.assertEqual(i18n._pieces("Ovo je (npr. X buzz) rečenica."), ["Ovo je (npr. X buzz) rečenica."])
        self.assertEqual(i18n._pieces("Sloj 1. je prvi sloj"), ["Sloj 1. je prvi sloj"])
        self.assertEqual(i18n._pieces("Jedan: dva tri. Četiri pet"), ["Jedan:", "dva tri.", "Četiri pet"])

    def test_a_lone_label_is_sent_a_lone_word_is_not(self):
        i18n.translate("<p>Kupnja: nešto posve novo ovdje.</p>")
        self.assertIn("Kupnja:", i18n._pending)
        i18n._pending.clear()
        i18n.translate("<p>Prva rečenica je ovdje. Dobro.</p>")
        self.assertEqual(list(i18n._pending), ["Prva rečenica je ovdje. Dobro."])   # the whole segment instead


class Waiting(Base):
    def test_first_view_waits_for_new_text(self):
        seen = []

        def model(keys):
            seen.append(list(keys))
            return ["EN " + k for k in keys]
        out = i18n.translate("<p>Posve nova rečenica ovdje</p><p>Još jedna nova rečenica</p>", wait=2, call=model)
        self.assertIn("<p>EN Posve nova rečenica ovdje</p>", out)
        self.assertIn("<p>EN Još jedna nova rečenica</p>", out)
        self.assertEqual(i18n.last_missing(), 0)
        self.assertEqual(len(seen), 1)
        with open(os.path.join(os.environ["DATA_DIR"], "i18n", "en.json"), encoding="utf-8") as f:
            self.assertIn("Posve nova rečenica ovdje", json.load(f))

    def test_slow_model_page_stays_croatian_then_next_view_is_english(self):
        go = threading.Event()

        def model(keys):
            go.wait(5)
            return ["EN " + k for k in keys]
        out = i18n.translate("<p>Spora nova rečenica ovdje</p>", wait=0.2, call=model)
        self.assertIn("Spora nova rečenica ovdje", out)
        self.assertEqual(i18n.last_missing(), 1)
        # a second visitor while it is still being translated: waits for that request, sends nothing twice
        self.assertFalse(i18n.translate_now(["Spora nova rečenica ovdje"], 0.1, call=lambda k: self.fail("sent twice")))
        go.set()
        for _ in range(50):
            if "Spora nova rečenica ovdje" in i18n._auto:
                break
            time.sleep(0.05)
        self.assertIn("<p>EN Spora nova rečenica ovdje</p>", i18n.translate("<p>Spora nova rečenica ovdje</p>"))

    def test_batches_in_parallel(self):
        calls = []
        keys = [f"Rečenica broj {chr(97 + i)} je nova" for i in range(30)]
        i18n.translate("".join(f"<p>{k}</p>" for k in keys), wait=2,
                       call=lambda ks: calls.append(len(ks)) or ["EN " + k for k in ks])
        self.assertEqual(sorted(calls), [6, 12, 12])

    def test_daily_cap(self):
        i18n._day.update(d=time.strftime("%Y-%m-%d"), n=i18n.DAILY_MAX)
        out = i18n.translate("<p>Nova rečenica preko dnevnog stropa</p>", wait=1,
                             call=lambda k: self.fail("over the cap"))
        self.assertIn("Nova rečenica preko dnevnog stropa", out)
        self.assertEqual(i18n.last_missing(), 0)   # nothing more comes today: the copy may be cached

    def test_croatian_costs_nothing(self):
        i18n.LANG.set("hr")
        h = "<p>Posve nova rečenica</p>"
        self.assertIs(i18n.translate(h, wait=5, call=lambda k: self.fail("called")), h)


class Figures(unittest.TestCase):
    def test_english_number_formats(self):
        nb = " "
        self.assertEqual(i18n.figures(f"<td>412k{nb}$</td><td>0,000412{nb}$</td>"), "<td>$412k</td><td>$0.000412</td>")
        self.assertEqual(i18n.figures(f"<b>+142{nb}%</b> 23,5{nb}% 3{nb}638"), "<b>+142%</b> 23.5% 3,638")
        self.assertEqual(i18n.figures(f"<script>var a='5{nb}$'</script>"), f"<script>var a='5{nb}$'</script>")
        self.assertEqual(i18n.figures('<a title="5 $">x</a>'), '<a title="5 $">x</a>')


class Cache(unittest.TestCase):
    def test_partial_english_copy_is_not_kept(self):
        pagecache.clear()
        n = []

        def build():
            n.append(1)
            return 200, b"<p>pola</p>", False
        pagecache.get(("/x", "", None, "en"), build, light=True)
        pagecache.get(("/x", "", None, "en"), build, light=True)
        self.assertEqual(len(n), 2)
        pagecache.get(("/y", "", None, "en"), lambda: (n.append(1) or 200, b"<p>sve</p>", True), light=True)
        pagecache.get(("/y", "", None, "en"), lambda: (n.append(1) or 200, b"<p>sve</p>", True), light=True)
        self.assertEqual(len(n), 3)
        pagecache.clear()

    def test_autopilot_json_tables_translated(self):
        import run_ui
        i18n._static, i18n._auto = {"Otvorene pozicije": "Open positions"}, {}
        tok = i18n.LANG.set("en")
        try:
            out = json.loads(run_ui.english_json_html(json.dumps({"x": 1, "html": {"pos": "<h3>Otvorene pozicije</h3>"}})))
        finally:
            i18n.LANG.reset(tok)
            i18n._static = i18n._auto = None
        self.assertEqual(out, {"x": 1, "html": {"pos": "<h3>Open positions</h3>"}})
        self.assertEqual(run_ui.english_json_html("nije json"), "nije json")

    def test_search_json_words(self):
        import run_ui
        from ui import html as H
        i18n._static, i18n._auto = None, None
        tok = i18n.LANG.set("en")
        try:
            out = json.loads(run_ui.english_search_json(json.dumps(
                {"pages": [{"name": "Natjecanje", "desc": "x", "sec": "Glavno"}],
                 "tokens": [{"sym": "BONK", "name": "Bonk", "src": ["skener", "dugoročni"]}]})))
            js = i18n.js(H.NAV_JS)
        finally:
            i18n.LANG.reset(tok)
            i18n._static = i18n._auto = None
        self.assertEqual(out["pages"][0]["name"], "Competition")
        self.assertEqual(out["pages"][0]["sec"], "Main")
        self.assertEqual(out["tokens"][0]["src"], ["scanner", "long-term"])
        self.assertEqual(out["tokens"][0]["name"], "Bonk")
        for w in ("'Pages'", "'Tokens'", "'Nothing found'", "'All results for'"):
            self.assertIn(w, js)


class TokenPage(unittest.TestCase):
    """The page of the owner's complaint, every variant: English from ui/i18n_en.json alone (no model call)."""

    def test_token_page_fully_english_without_the_model(self):
        import test_tokeni_offline as T
        from ops import seoaudit
        from ui.html import page
        os.environ["DATA_DIR"] = tempfile.mkdtemp()
        i18n._static = i18n._auto = None
        i18n._pending.clear()
        tp = T.TokenPage()
        tok = i18n.LANG.set("en")
        try:
            for kw in ({}, {"verdict": "ODBAČEN", "fails": ["dev je izvukao likvidnost"]}, {"verdict": "OPREZ"},
                       {"verdict": "VISOK RIZIK"}):
                title, body = tp._render(**kw)
                out = i18n.translate(page(title, body, "/token/" + T.MINT),
                                     call=lambda k: self.fail("the token page needed the model"))
                hr = [w for w, _ in seoaudit.foreign_words(seoaudit.parse(out).text, "en")]
                self.assertEqual(hr, [], kw)
                self.assertIn("<html lang=en>", out)
                self.assertIn("$412k", out)
        finally:
            i18n.LANG.reset(tok)
            i18n._static = i18n._auto = None


if __name__ == "__main__":
    unittest.main()
