"""Stranice nakon promjene fokusa (19.11., vlasnik: "Kome treba ova stranica... baš ništa na njoj nema"; "kompletna
aplikacija treba refurbish s obzirom na promjenu fokusa"): nova stranica Tokeni (midcap popis, skokovi, skupine
novčanika prije skoka), navigacija (Pregled, Novčanici, Tokeni, Influenceri, Više), umirovljene stranice mikrokap
strategija, Pregled (novčanici prvi, Autopilot sklopljen na dnu), filtar poziva na tokene ispod 30k $, stranica tokena
(bez "Kupi" ispod 30k kad ga ne pratimo, riječi pauze), Makro prva kartica Influencera, bez Telegram redaka.
Bez mreže; baze su privremene (scripts/seed_tokeni.py)."""
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import seed_tokeni as SEED  # noqa: E402
from ui import admstrip, html, midcaplist, pauza, tokens, umirovljeno  # noqa: E402
from ui import redak as R  # noqa: E402

NB = R.NBSP


class Base(unittest.TestCase):
    EMPTY = False

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.paths = SEED.paths_in(self.d)
        self.now = int(time.time())
        env = {"MIDCAP_DB": self.paths["midcap"], "INSAJDERI_DB": self.paths["insajderi"],
               "TOKENSTRANICE_DB": self.paths["tokenstranice"]}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        from kol import store as kstore
        p2 = mock.patch.object(kstore, "DB", self.paths["kol"])
        p2.start()
        self.addCleanup(p2.stop)
        self.seed = SEED.seed(self.paths, empty=self.EMPTY, now=self.now, paused=True)
        pauza.reset()
        self.addCleanup(pauza.reset)

    def page(self, qs=None):
        return tokens.page(qs or {}, now=self.now)[1]


class TokeniWithData(Base):
    def test_first_sentence_tabs_and_rows(self):
        d = midcaplist.load(self.now)
        self.assertEqual(len(d["tokens"]), 500)
        self.assertEqual(d["n15"] + d["n2"], 500)
        h = self.page()
        m = re.search(r'<p class="mc-ans">([^<]+)</p>', h)
        self.assertTrue(m.group(1).startswith(f"Pratimo 500 tokena: {d['n15']} vrijedi 15 M $ ili više, {d['n2']} između "
                                              "2 i 15 M $."), m.group(1))
        self.assertIn("U zadnjih 7 dana skočilo ih je", m.group(1))
        self.assertIn('href="/tokens" class="on" aria-current="page">Od 15 M $', h)
        self.assertIn('href="/tokens?t=2"', h)
        self.assertIn('href="/tokens?t=skok"', h)
        mcs = [int(x) for x in re.findall(r'data-mc="(\d+)"', h)]
        self.assertEqual(len(mcs), d["n15"])
        self.assertTrue(all(x >= 15e6 for x in mcs))
        self.assertEqual(mcs, sorted(mcs, reverse=True))                 # market cap first
        self.assertIn('href="/token/', h)
        self.assertIn("Simbol ili adresa", h)
        self.assertIn('href="/dugorocno"', h)                            # Dugoročni: a link (its job still runs)
        # gone: the old views and the false sentences
        for gone in ("Novi", "Jaki", "Uz evente", "Stariji od 24 h", "Skeniramo", "svake 2 min", "u zadnja 24 h",
                     "analizirano", "Trenutno nema novih tokena"):
            self.assertNotIn(gone, h)

    def test_tier_two_and_jumped_tab(self):
        h = self.page({"t": "2"})
        mcs = [int(x) for x in re.findall(r'data-mc="(\d+)"', h)]
        self.assertTrue(mcs and all(2e6 <= x < 15e6 for x in mcs))
        h = self.page({"t": "skok"})
        ts = [int(x) for x in re.findall(r'data-ts="(\d+)"', h)]
        self.assertEqual(len(ts), 20)
        self.assertEqual(ts, sorted(ts, reverse=True))                  # by date
        self.assertRegex(h, r"\+\d+" + NB + r"% u \d+ (h|dan|dana), \d+\.\d+\.")
        self.assertRegex(h, r"prije skoka kupil[aeo] \d+ skupin[ae] novčanika")

    def test_groups_count_matches_the_owner_link(self):
        pl = midcaplist.pumps(self.paths["insajderi"], self.now)
        con = sqlite3.connect(self.paths["insajderi"])
        for p in pl:
            want = con.execute("SELECT COUNT(DISTINCT p.owner) FROM i2_part p JOIN i2_pp g ON g.owner = p.owner "
                               "WHERE g.cls = 'prije_pumpe' AND p.bought_before = 1 AND p.eid = ?", (p["eid"],)).fetchone()[0]
            self.assertEqual(p["groups"], want)
        con.close()
        self.assertTrue(any(p["groups"] for p in pl))
        self.assertTrue(any(not p["groups"] for p in pl))             # no early buyers: the phrase is left out
        self.assertEqual(tokens.groups_phrase(0), "")

    def test_hostile_symbol_and_name_escaped(self):
        h = self.page() + self.page({"t": "2"}) + self.page({"t": "skok"})
        self.assertNotIn("<img src=x onerror=alert(7)>", h)
        self.assertNotIn("<b>name</b>", h)
        self.assertIn("&lt;img src=x onerror=alert(7)&gt;", h)

    def test_fast_with_600_tokens(self):
        SEED.seed(self.paths, n=600, now=self.now)
        t = time.time()
        for q in ({}, {"t": "2"}, {"t": "skok"}):
            self.page(q)
        self.assertLess((time.time() - t) / 3, 0.3)                    # ~0.02 s here

    def test_english(self):
        from ui import i18n
        tok = i18n.LANG.set("en")
        try:
            out = i18n.translate(html.page("Tokeni", self.page(), "/tokens"))
        finally:
            i18n.LANG.reset(tok)
        self.assertIn("We track 500 tokens:", out)
        self.assertIn("Jumped recently", out)
        self.assertIn("Symbol or address", out)
        self.assertNotIn("Pratimo", out)


class TokeniEmpty(Base):
    EMPTY = True

    def test_empty_state_never_claims_a_job(self):
        with mock.patch("ops.fokus.on", return_value=True):
            h = self.page()
        self.assertIn("Popis se puni: prvi podaci nakon sljedećeg osvježavanja.", h)
        with mock.patch("ops.fokus.on", return_value=False):
            h = self.page({"t": "skok"})
        self.assertIn("sakupljač je isključen", h)
        self.assertNotIn("Skeniramo", h)

    def test_databases_missing(self):
        for p in self.paths.values():
            if os.path.exists(p):
                os.remove(p)
        with mock.patch("ops.fokus.on", return_value=True):
            for q in ({}, {"t": "2"}, {"t": "skok"}):
                h = self.page(q)
                self.assertIn("Popis se puni", h)
        self.assertEqual(midcaplist.mcap_now(["x"]), {})


class Redirects(unittest.TestCase):
    def test_old_views_go_to_the_new_default(self):
        self.assertEqual(tokens.redirect_for("/tokens/jaki", {}), "/tokens")
        for qs in ({"view": "novi"}, {"v": "jaki"}, {"tab": "dugo"}, {"t": "novi"}, {"t": "15"}):
            self.assertEqual(tokens.redirect_for("/tokens", qs), "/tokens", qs)
        for qs in ({}, {"t": "2"}, {"t": "skok"}):
            self.assertIsNone(tokens.redirect_for("/tokens", qs))
        self.assertEqual(tokens.tab_of({"t": "nesto"}), "15")


class Navigation(unittest.TestCase):
    def test_bottom_bar_same_order_for_every_role(self):
        self.assertEqual([t for _h, _i, t in html.BOTTOM], ["Pregled", "Novčanici", "Tokeni", "Influenceri"])
        bar = html.bottom_bar("/pregled")
        for b in (bar, admstrip.strip(bar)):
            names = re.findall(r"</span>([^<]+)</a>", b)
            self.assertEqual(names, ["Pregled", "Novčanici", "Tokeni", "Influenceri", "Više"])
        self.assertNotIn("/pravi-trade", bar)
        self.assertIn('class="vise on"', html.bottom_bar("/pravi-trade"))   # the Autopilot lives under Više
        side = html.side_menu("/pregled", "/pregled")
        order = [side.index(f'href="{h}"') for h in ("/pregled", "/wallets", "/tokens", "/kol", "/vise")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('href="/pravi-trade"', side)

    def test_vise_groups_autopilot_and_telegram_link(self):
        with mock.patch.object(pauza, "on", return_value=True):
            _t, body = html.vise_page({})
        heads = re.findall(r"<div class=ms-gt>([^<]+)", body)
        self.assertEqual([h.strip() for h in heads][:5],
                         ["Novčanici i tokeni", "Influenceri", "Natjecanje", "Autopilot (pauzirano)", "Alati"])
        self.assertIn("Pauzirano: kupnje pravim novcem stoje, alat se preslaguje oko novčanika.", body)
        self.assertIn('href="/pravi-trade"', body)
        self.assertIn('href="/autopilot"', body)
        self.assertIn('href="/telegram-kanali"', body)
        self.assertIn("Telegram kanali (informativno)", body)
        self.assertIn("osvježava se jednom u 5 dana", body)
        with mock.patch.object(pauza, "on", return_value=False):
            _t, body2 = html.vise_page({})
        self.assertNotIn("Pauzirano:", body2)

    def test_retired_pages_left_the_navigation_and_still_answer(self):
        import run_ui
        hrefs = {p["href"] for _s, items in html.SECTIONS for p in items}
        _t, vise = html.vise_page({})
        for path in umirovljeno.PAGES:
            self.assertNotIn(path, hrefs)
            self.assertNotIn(f'href="{path}"', vise)
            title, body = run_ui.route(path, {})
            self.assertIn(umirovljeno.LINE, body)
            self.assertIn('href="/tokens"', body)
            self.assertIn('href="/wallets"', body)
        self.assertIsNone(umirovljeno.page("/radar", {"arhiva": "1"}))   # the owner's archive view
        self.assertNotIn("/izvori", hrefs)                              # Telegram: one quiet link under Influenceri

    def test_false_sentences_are_gone(self):
        from ui import criteria, glossary  # noqa: F401
        self.assertNotIn("Hype skener</b> (svake 2 min)", criteria.page({})[1])
        with open(os.path.join(os.path.dirname(html.__file__), "glossary.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('"Hype skener svake 2 minute gleda', src)
        self.assertNotIn("novi, jaki i dugoročni", str(html.SECTIONS))
        from ui import rangtable
        self.assertNotIn("svaka 3 h", rangtable.table([], "wallet", time.time()))


class TokenPage(Base):
    def _token(self, mint, mci, paused=True):
        from ui import pages
        with mock.patch.object(midcaplist, "mcap_now", return_value={mint: mci} if mci else {}), \
                mock.patch.object(pauza, "on", return_value=paused), \
                mock.patch("ui.evidence.live_pair", return_value=None), \
                mock.patch("ui.pages._token_status", return_value=None):
            return pages.token(mint, {})[1]

    def test_untracked_under_30k_has_no_buy(self):
        h = self._token(SEED.COOLDOG, (3100, False))
        self.assertIn("Ovaj token ne pratimo: vrijedi ispod 30.000 $ (pratimo tokene od 2 M $ naviše). Ispod su samo "
                      "podaci s tržišta i poveznice.", h)
        self.assertNotIn(">Kupi</button>", h)
        self.assertNotIn("Kupnja: demo", h)
        self.assertNotIn('id="qb-sheet"', h)

    def test_tracked_and_paused_wording(self):
        m = SEED.mint_of(0)
        h = self._token(m, (50e6, True), paused=True)
        self.assertIn("Na popisu midcap tokena", h)
        self.assertIn(">Kupi</button>", h)
        self.assertIn("Kupnja: demo 50 $ na Natjecanju. Pravi novac je pauziran.", h)
        self.assertNotIn("Autopilot (pravi novac)", h)
        self.assertIn("pauzirane", h)                                    # the owner's manual buy row says so
        h = self._token(m, (50e6, True), paused=False)
        self.assertIn("Autopilot (pravi novac)", h)

    def test_no_telegram_callers(self):
        from ui import pages
        with mock.patch("ui.tokenchart.calls", return_value=[(self.now - 60, "tg:kanal", 1e6), (self.now - 30, "abc", 2e6)]), \
                mock.patch("ui.kol.token_section", return_value=""):
            out = pages._callers_html("M", 3e6, self.now)
        self.assertIn("@abc", out)
        self.assertNotIn("kanal", out)
        self.assertNotIn("(TG)", out)


class Calls(Base):
    def _kol(self):
        from kol import store as kstore
        con = kstore.connect(self.paths["kol"])
        live, dead = SEED.mint_of(0), "Dead1111111111111111111111111111111111pump"
        con.execute("INSERT OR REPLACE INTO kols (handle, followers, score, stats) VALUES ('ana', 5000, 60, '{}')")
        con.execute("INSERT OR REPLACE INTO kols (handle, followers, score, stats) VALUES ('tg:kanal', 0, 70, '{}')")
        for i, (tok, h) in enumerate([(live, "ana"), (dead, "ana"), (SEED.COOLDOG, "ana"), (live, "tg:kanal")]):
            con.execute("INSERT OR REPLACE INTO calls (tweet_id, token, handle, ts, url, text, kind, first_by_kol, mcap0, "
                        "r1h, r24h) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (f"t{i}", tok, h, self.now - (i + 1) * 3600, "https://x.com/a/status/1", "x", "call", 1, 1e6,
                         0.1, 0.2))
        con.commit()
        con.close()
        return live, dead

    def test_split_keeps_tracked_first_and_counts_the_rest(self):
        mc = {"a": (40_000, False), "b": (20e6, True), "c": (10_000, False)}
        shown, hidden = midcaplist.split_calls(["a", "b", "c", "d"], lambda x: x, mc=mc)
        self.assertEqual(shown, ["b", "a"])
        self.assertEqual(hidden, ["c", "d"])
        self.assertEqual(midcaplist.hidden_line(3), "još 3 poziva na tokene koji danas vrijede ispod 30.000 $")
        self.assertEqual(midcaplist.hidden_line(21), "još 21 poziv na tokene koji danas vrijede ispod 30.000 $")

    def test_profile_lists_only_live_tokens_and_statistics_are_unchanged(self):
        from kol import store as kstore
        from ui import kol, kolsummary
        live, _dead = self._kol()
        before = kolsummary.verdict_stats(14, self.now, self.paths["kol"], os.path.join(self.d, "minute.db"))
        con = kstore.ro()
        con.row_factory = sqlite3.Row
        try:
            out = str(kol._last_calls(con, "ana", self.now))
            tab = kol.calls_table(con, "handle = ?", ("ana",), 500, "k", show_kol=False)
            rec = str(kol._recent_html(con, {}, self.now))
        finally:
            con.close()
        kolsummary._CACHE.clear() if hasattr(kolsummary, "_CACHE") else None
        after = kolsummary.verdict_stats(14, self.now, self.paths["kol"], os.path.join(self.d, "minute.db"))
        self.assertEqual(before, after)
        self.assertIn(f"/token/{live}", out.split("kl-dead")[0])
        self.assertIn("još 2 poziva na tokene koji danas vrijede ispod 30.000 $", out)
        self.assertIn("još 2 poziva na tokene koji danas vrijede ispod 30.000 $", tab)
        self.assertNotIn("tg:kanal", rec)
        self.assertNotIn("kanal", tab)

    def test_influenceri_makro_first_and_no_telegram(self):
        from ui import kol
        self.assertEqual(kol.TABS[0][0], "#makro")
        self.assertEqual(kol.DEFAULT_TAB, "makro")
        self.assertIn('href="#makro" class="on"', str(kol._tabs()))
        v = {"index": {"v": 0.42, "n": 6, "lean": "bull", "day": 0}, "ts": self.now - 3600}
        s = kol.makro_sentence(v, self.now)
        self.assertTrue(s.startswith("Konsenzus najtočnijih makro influencera o BTC-u je bikovski (+0,42, 6 računa sa "
                                     "stavom)."), s)
        old = kol.makro_sentence({"index": None, "ts": self.now - 10 * 86400}, self.now)
        self.assertIn("Podaci su stari: zadnji izračun", old)
        self._kol()
        with mock.patch("ui.kol.makro_pane", return_value="<div id=makro></div>"), \
                mock.patch("ui.kol.makro_sentence", return_value="Makro rečenica."):
            _t, page = kol.page({})
        self.assertLess(page.index("Makro rečenica."), page.index("kl-tabs"))
        self.assertIn('data-pane=ljestvica id=ljestvica hidden', page)
        self.assertNotIn("tg:kanal", page)
        self.assertNotIn("Telegram calleri", page)


class Pregled(Base):
    def test_wallets_first_autopilot_folded_last(self):
        from ui import pocetna
        with mock.patch.object(pocetna, "open_real", return_value=None), mock.patch.object(pauza, "on", return_value=True), \
                mock.patch.object(pocetna, "kol_later_row", return_value=R.rows([R.row("@ana")])), \
                mock.patch.object(pocetna, "makro_line", return_value=R.raw("<p>Makro.</p>")), \
                mock.patch.object(pocetna, "data_foot", return_value=""):
            _t, h = pocetna.page({}, now=self.now)
        i_w = h.index("Novčanici koji kupuju prije pumpe")
        i_s = h.index("Skočili nedavno")
        i_m = h.index("Makro influenceri")
        i_ap = h.index('id="pg-autopilot"')
        self.assertLess(i_w, i_s)
        self.assertLess(i_s, i_m)
        self.assertGreater(i_ap, i_m)
        self.assertIn('<details class="pg-ap"', h)                      # collapsed (no "open")
        self.assertNotIn('<details class="pg-ap" open', h)
        self.assertEqual(h.rindex("<details"), h.index('<details class="pg-ap"'))   # the last block
        self.assertIn("Autopilot (pauzirano)", h)
        self.assertNotIn('class="pg-open"', h)
        for gone in ("Najbolji ulaz sada", "Strategije u demu", "Najveći pogodak", "Telegram", "tg:", "uživo, pravi novac"):
            self.assertNotIn(gone, h)

    def test_open_real_position_line_stays_visible(self):
        from ui import pocetna
        tdb = os.path.join(self.d, "t.db")
        con = sqlite3.connect(tdb)
        con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, mode TEXT, status TEXT, sol_in REAL)")
        con.executemany("INSERT INTO positions (mode, status, sol_in) VALUES (?,?,?)",
                        [("live", "open", 0.1), ("live", "open", 0.1), ("dry", "open", 5), ("live", "closed", 1)])
        con.commit()
        con.close()
        self.assertEqual(pocetna.open_real(tdb), (2, 0.2))
        with mock.patch.object(pocetna, "open_real", return_value=(2, 0.2)), \
                mock.patch.object(pocetna, "kol_later_row", return_value=""), \
                mock.patch.object(pocetna, "makro_line", return_value=""), \
                mock.patch.object(pocetna, "data_foot", return_value=""):
            _t, h = pocetna.page({}, now=self.now)
        self.assertIn(f"Otvoreno pravim novcem: 2 pozicije, uloženo 0,200{NB}SOL", h)
        self.assertLess(h.index('class="pg-open"'), h.index("Novčanici koji kupuju prije pumpe"))   # near the top
        self.assertLess(h.index('class="pg-open"'), h.index('id="pg-autopilot"'))

    def test_wallet_answers_plain(self):
        from ui import pocetna
        f = pocetna.wallet_facts(self.paths["insajderi"])
        a = pocetna.wallet_answers(f)
        self.assertEqual(len(a), 3)
        self.assertTrue(a[0].startswith("Našli smo 5 skupina novčanika koje kupuju prije skoka cijene"), a[0])
        self.assertEqual(pocetna.wallet_answers(None)[0][:28], "Još tražimo novčanike koji k")


if __name__ == "__main__":
    unittest.main()
