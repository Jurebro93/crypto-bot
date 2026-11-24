"""19.11. (vlasnik: "make sure the UI is perfect ... the admin must have a dashboard with more data about the wallets
than an ordinary user ... the ordinary user should only be informed: follow this wallet because of this and this ...
on the Autopilot page, while real money is off, as many demo trades as possible with wallet following"): ui/novadmin.py
(/novcanici-admin), ui/novkartice.py (the card on /wallets, the Autopilot's demo section), ui/novpodaci.py (the reads),
ui/pauza.py's extra sentence. The fixture is scripts/seed_novcanici.py (made-up data, never production).

    python3 -m unittest tests.test_novcanici_ui_offline
"""
import importlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import seed_novcanici as SEED  # noqa: E402
from league import roles, store as lstore  # noqa: E402
from trade import settings  # noqa: E402
from ui import novadmin, novkartice, novpodaci as P, pauza  # noqa: E402
from wallets import rang, store as wstore  # noqa: E402

HOSTILE = re.compile(r"<script>alert|<img src=x|\"><img")
SECTIONS = ("Koga smo izbacili i zašto", "Stanje pretraživanja", "Koliko smo duboko gledali", "Sve skupine u tablici",
            "Skupine koje kupuju zajedno", "Test kopiranja na prošlim podacima", "Mjerenje uživo, kupnja po kupnja",
            "Povijest trgovanja novčanika", "Veliki dugoročni vlasnici tokena", "Druga provjera (Birdeye)")
ADMIN_ONLY = ("Ostvareno", "Test kopiranja", "Isključeni", "95 % interval", "SOL", "PnL", "insajder", "Insajder")


class Base(unittest.TestCase):
    EMPTY = False
    PAUSED = True

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.paths = SEED.paths_in(self.d)
        self.patches = [mock.patch.dict(os.environ, {"INSAJDERI_DB": self.paths["insajderi"],
                                                     "HOLDERI_DB": self.paths["holderi"]}),
                        mock.patch.object(wstore, "DB", self.paths["wallets"]),
                        mock.patch.object(lstore, "DB", self.paths["league"]),
                        mock.patch.object(settings, "DB", self.paths["trade"])]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        rang._CACHE.clear()
        self.addCleanup(rang._CACHE.clear)
        pauza.reset()
        self.addCleanup(pauza.reset)
        self.now = int(time.time())
        self.seed = SEED.seed(self.paths, empty=self.EMPTY, now=self.now, paused=self.PAUSED)
        pauza.reset()


class Admin(Base):
    def test_every_section_with_data_confirmed_first_and_escaped(self):
        title, html = novadmin.page({}, "Jure", self.now)
        self.assertEqual(title, "Novčanici: administracija")
        for s in SECTIONS:
            self.assertIn(f"<span>{s}</span>", html, s)
        self.assertIsNone(HOSTILE.search(html))                      # hostile symbol, address and reason escaped
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("Evil&quot;&gt;&lt;img", html)
        # confirmed first: the first row's status is "potvrđeno", and a candidate comes after every confirmed one
        rows = re.findall(r'<tr class=rt-r [^>]*data-st="(\d)"', html.split('id="grupe"')[1].split('id="bundle"')[0])
        self.assertEqual(rows[:8], ["2"] * 8)
        self.assertNotIn("2", rows[8:])
        # the status strip from the stored numbers; what is not stored says so
        self.assertIn("29 pregledano od 40", html)
        self.assertIn("skinuti podaci: nije još izmjereno", html)     # fetched for 2-15M is not stored
        self.assertIn("trajala 757 s; prekinuta jer je isteklo vrijeme: da", html)   # i2_kv stage_s
        self.assertIn("pauziran", html)
        visible = re.sub(r"<style>.*?</style>|<script>.*?</script>|<[^>]+>", " ", html, flags=re.S)
        for raw in ("helius_day", "i2_", "holder_pos", ".db", "first_ts", "night ·"):
            self.assertNotIn(raw, visible, raw)
        self.assertIn("dnevni strop", visible)
        # the copy test's verdict computed from the stored interval
        self.assertIn("Zasad da: u prosjeku +3,4\xa0% po kupnji nakon troška, ali raspon još dira nulu.", html)
        self.assertIn("kupnja 2 sekunde nakon njih (pretpostavka: 1 % lošija cijena)", html)
        # exclusions: counts per reason incl. the one-time wallets that are not stored one by one
        self.assertRegex(html, r"<b>pojavili se samo jednom</b> · 1\xa0234")
        self.assertIn("<b>market makeri (kupuju i prodaju cijelo vrijeme)</b> · 2", html)
        # a group's detail: its pumps, its wallets with copy + Solscan in a new tab, what links them
        self.assertIn("min prije skoka", html)
        self.assertIn('target=_blank rel="noopener noreferrer">Solscan ↗', html)
        self.assertIn("isti novčanik plaća naknade", html)
        # list rows: the short address (6 … 6) with the full one in the title and the copy payload; the detail keeps it
        part = html.split('id="grupe"')[1].split('id="bundle"')[0]
        full = self.seed["members"][0]
        self.assertIn(f'<code translate=no title="{full}">{full[:6]}…{full[-6:]}</code>', part)
        self.assertIn(f'data-cp="{full}"', part)
        self.assertIn(f"<li><code translate=no>{full}</code>", part)
        self.assertIn('.na.ms-page{max-width:none}', html)
        self.assertIn('data-cp="', html)
        # history and holders
        self.assertRegex(html, r"\d+ od \d+ navedenih novčanika ima izračunatu povijest, \d+ čeka")
        self.assertIn("Udio u svim tokenima", html)
        self.assertIn("naše snimke vlasnika sežu oko 45 dana unatrag", html)
        # the history job's status and the groups' members' own history (i2_pp_hist), neutral wording
        self.assertIn("Čeka po izvoru:</b> skupine koje kupuju prije skoka", html)
        self.assertIn("rani kupci tokena od 15 M $", html)
        self.assertIn("Zadnja obrada povijesti</span><b>noćna", html)
        self.assertIn("trajala 1\xa0830 s; prekinuta jer je isteklo vrijeme: da", html)
        self.assertIn("5\xa0400 od 60\xa0000 jedinica", html)
        self.assertRegex(html, r"Povijest novčanika u skupini:</b> izračunata za \d+ od \d+, u plusu \d+\xa0% njih, "
                               r"zaradili [+−][\d,]+\xa0SOL; (slaže se|ne slaže se) s rezultatom na skokovima\.")
        self.assertIn("<span class=mut>još nema povijesti</span>", html)          # a group without a history row
        holders = html.split('id="holderi"')[1]
        self.assertLess(holders.index("15–200 M $"), holders.index("2–15 M $"))   # 15-200M first
        self.assertIn("zatvorenih ·", holders)                                    # a holder's own scored history
        self.assertIn("još se računa", holders)

    def test_filter_and_pagination(self):
        _t, conf = novadmin.page({"f": "potvrdeni"}, "Jure", self.now)
        part = conf.split('id="grupe"')[1].split('id="bundle"')[0]
        self.assertEqual(set(re.findall(r'data-st="(\d)"', part)), {"2"})
        with mock.patch.object(novadmin, "PAGE_N", 7):
            _t, p2 = novadmin.page({"p": "2"}, "Jure", self.now)
        part = p2.split('id="grupe"')[1].split('id="bundle"')[0]
        self.assertIn("Stranica 2 od 5 · 30 skupina", part)
        self.assertEqual(len(re.findall(r"<tr class=rt-r ", part)), 7)
        _t, bad = novadmin.page({"p": "x' OR 1=1", "f": "<b>", "t": "99"}, "Jure", self.now)   # junk in the query
        self.assertIn("Stranica 1 od", bad)

    def test_render_is_fast_on_5000_groups(self):
        con = sqlite3.connect(self.paths["insajderi"])
        con.executemany("INSERT INTO i2_pp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(f"own{i:05d}", json.dumps([f"w{i}a", f"w{i}b"]), 2, "prije_pumpe" if i % 3 else "kandidat",
                          "x", i % 4, 2, 3 + i % 5, 12.5, 1.0, None, self.now - i, self.now) for i in range(5000)])
        con.commit()
        con.close()
        novadmin.page({}, "Jure", self.now)
        t = time.time()
        _t, html = novadmin.page({}, "Jure", self.now)
        self.assertLess(time.time() - t, 1.5)                        # ~0.1 s here; the bound leaves room for a busy CI
        self.assertIn("5\xa0030 skupina", html)


class AdminEmpty(Base):
    EMPTY = True

    def test_every_section_has_an_honest_empty_state(self):
        _t, html = novadmin.page({}, "Jure", self.now)
        for s in SECTIONS:
            self.assertIn(f"<span>{s}</span>", html, s)
        self.assertGreaterEqual(html.count("još nema podataka: puni ih prva noćna obrada"), 2)
        self.assertIn("Još ne znamo: test kopiranja još nije napravljen", html)
        self.assertIn("Zadnja obrada</span><b>nije još izmjereno", html)
        self.assertNotIn("Traceback", html)

    def test_no_database_at_all(self):
        with mock.patch.dict(os.environ, {"INSAJDERI_DB": os.path.join(self.d, "nema.db"),
                                          "HOLDERI_DB": os.path.join(self.d, "nema2.db")}), \
                mock.patch.object(wstore, "DB", os.path.join(self.d, "nema3.db")):
            _t, html = novadmin.page({}, "Jure", self.now)
            card = novkartice.card_html()
        self.assertIn("(baza još ne postoji)", html)
        self.assertIn("Popis velikih vlasnika još ne postoji", html)
        self.assertIn("Red za povijest novčanika još ne postoji", html)
        self.assertIn(novkartice.CARD_EMPTY, card)


class Access(unittest.TestCase):
    """The server: the owner gets the page, an ordinary user a 403, a visitor the login."""

    def setUp(self):
        self.old_env = dict(os.environ)
        d = tempfile.mkdtemp()
        self.old_db = (settings.DB, lstore.DB)
        settings.DB, lstore.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        os.environ.update(DATA_DIR=d, UI_USERS="Ivan,Jure", UI_PASS_IVAN="ivanpw", UI_PASS_JURE="jurepw",
                          TRADE_OWNER="Jure", UI_ADMINS="Jure", INSAJDERI_DB=os.path.join(d, "insajderi.db"),
                          UI_SNAP_DIR=os.path.join(d, "snap"))
        roles.reset_cache()
        import run_ui
        importlib.reload(run_ui)
        self.ui = run_ui
        self.srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        self.srv.verbose = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        settings.DB, lstore.DB = self.old_db
        os.environ.clear()
        os.environ.update(self.old_env)
        roles.reset_cache()
        importlib.reload(self.ui)

    def call(self, path, cookie=""):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        req = urllib.request.Request(self.base + path, headers={"Cookie": cookie} if cookie else {})
        try:
            r = urllib.request.build_opener(NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.code, r.read().decode("utf-8", "replace")

    def login(self, name, pw):
        data = urllib.parse.urlencode({"name": name, "pw": pw, "next": "/"}).encode()
        req = urllib.request.Request(self.base + "/prijava", data=data, headers={"Origin": self.base})

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        try:
            r = urllib.request.build_opener(NoRedirect).open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.headers["Set-Cookie"].split(";")[0]

    def test_owner_only(self):
        jure, ivan = self.login("Jure", "jurepw"), self.login("Ivan", "ivanpw")
        code, html = self.call("/novcanici-admin", jure)
        self.assertEqual(code, 200)
        self.assertIn("Novčanici: administracija", html)
        code, html = self.call("/novcanici-admin", ivan)
        self.assertEqual(code, 403)
        self.assertNotIn("Kupuje prije pumpe", html)
        code, html = self.call("/novcanici-admin")
        self.assertEqual(code, 401)
        self.assertNotIn("Kupuje prije pumpe", html)
        self.assertEqual(roles.deny_get("/novcanici-admin", "osnovni"), "admin")


class UserCard(Base):
    def test_confirmed_only_one_sentence_and_nothing_admin_only(self):
        card = novkartice.card_html()
        n = card.count("class=nk-row")
        self.assertEqual(n, len(self.seed["confirmed"]))               # 8 confirmed, the 22 others never
        self.assertLessEqual(n, novkartice.CARD_N)
        self.assertIn("Kupio je prije skoka na 3 tokena (3 od 15 M $ naviše) i prodao u rast; potvrđeno na novijim "
                      "podacima.", card)
        self.assertIn("Skupina od 70 povezanih novčanika kupila je prije skoka na", card)
        self.assertRegex(card, r"Skupina od 3 povezanih novčanika koja je u \d+ skok\w* kupila zajedno prije rasta")
        self.assertIn(novkartice.CARD_FOOT, card)
        # 24.11. (vlasnik: "raširiti i dobiti konkretnije podatke"): a fold per wallet with the jumps and the history;
        # amounts and the SOL result are adm-only, so the copy a non-admin gets (admstrip) carries none of the words
        from ui import admstrip
        self.assertEqual(card.count("<details class=nk-more>"), n)
        self.assertRegex(card, r"Više podataka · \d+ skok")
        self.assertRegex(card, r"kupio \d+ min prije skoka · prodao u rastu: (da|ne)")
        self.assertIn("adm-only", card)
        plain = admstrip.strip(card)
        for w in ADMIN_ONLY:
            self.assertNotIn(w, re.sub(r"<style>.*?</style>|<script>.*?</script>", "", plain, flags=re.S), w)

        self.assertIsNone(HOSTILE.search(card))
        self.assertIn('target=_blank rel="noopener noreferrer">Solscan ↗', card)
        self.assertIn("data-cp=", card)

    def test_the_wallets_page_carries_the_card_and_the_admin_link_only_for_admins(self):
        from ui import admstrip, pages
        _t, html = pages.wallets({})
        self.assertIn("Novčanici koje vrijedi pratiti", html)
        self.assertIn('href="/novcanici-admin"', html)
        stripped = admstrip.strip(html) if hasattr(admstrip, "strip") else None
        if stripped is not None:
            self.assertNotIn('href="/novcanici-admin"', stripped)
            self.assertIn("Novčanici koje vrijedi pratiti", stripped)

    def test_plurals(self):
        self.assertEqual(novkartice._na_tokenu(21), "tokenu")
        self.assertEqual(novkartice._na_tokenu(11), "tokena")
        self.assertEqual(novkartice._u_skoku(3), "skoka")
        self.assertEqual(novkartice._u_skoku(5), "skokova")
        self.assertEqual(novkartice._u_skoku(12), "skokova")


class UserCardEmpty(Base):
    EMPTY = True

    def test_honest_empty_card(self):
        card = novkartice.card_html()
        self.assertIn("Još skupljamo dokaze. Prvi popis objavit ćemo kad novčanici budu potvrđeni na novijim podacima.",
                      card)
        self.assertNotIn("class=nk-row", card)


class Demo(Base):
    def test_shown_while_paused_with_the_followed_wallet_and_its_sentence(self):
        html = novkartice.demo_html(True, self.now)
        self.assertIn("Demo praćenje novčanika (bez pravog novca)", html)
        self.assertIn("Otvoreno: 7; zatvoreno u 14 dana: 12", html)            # both demo accounts, by source prefix
        self.assertRegex(html, r"Zatvoreni, neto nakon stvarnog troška \(nikad ispod 3 %\): prije pumpe 15–200 M \$ "
                               r"n=\d+, [+−][\d,]+\xa0%; 2–15 M \$ n=\d+.*; kandidati n=\d+.*; bundle n=\d+.*; "
                               r"kopija dokazanih n=\d+.*; insajderi2 n=\d+")
        self.assertIn("kandidat · 2–15\xa0M $".replace("\xa0", " "), html)
        self.assertIn("prije pumpe · 15–200 M $", html)
        self.assertIn("bundle ", html)
        self.assertIn("grupa ", html)
        self.assertIn("novčanik ", html)
        self.assertIn("povezanih novčanika kupila je prije skoka", html)
        self.assertIsNone(HOSTILE.search(html))

    def test_any_source_with_a_listed_prefix_is_picked_up(self):
        con = sqlite3.connect(self.paths["league"])
        con.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, source) VALUES (?,?,?,?,?,?,?)",
                    (settings.PAPER_USER, "NEWTOKENmint", "NOVI", self.now, "open", 15, "prije pumpe: grupa abc"))
        con.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, source) VALUES (?,?,?,?,?,?,?)",
                    (settings.PAPER_USER, "OTHERmint", "DRUGI", self.now, "open", 15, "veliki_range"))
        con.commit()
        con.close()
        html = novkartice.demo_html(True, self.now)
        self.assertIn("NOVI", html)
        self.assertNotIn("DRUGI", html)
        with mock.patch.object(P, "DEMO_SOURCES", ("veliki_range",)):
            opened, _c = P.demo_trades(P.DEMO_SOURCES, now=self.now)
        self.assertEqual([t["symbol"] for t in opened], ["DRUGI"])     # one tuple entry is the whole change

    def test_display_only(self):
        def count():
            c = sqlite3.connect(self.paths["league"])
            try:
                return c.execute("SELECT COUNT(*), SUM(id) FROM trades").fetchone()
            finally:
                c.close()
        before = count()
        novkartice.demo_html(True, self.now)
        from ui import apterm
        self.assertIn("demonov", apterm.LAZY)
        after = count()
        self.assertEqual(before, after)
        with open(os.path.join(ROOT, "ui", "novkartice.py"), encoding="utf-8") as f:
            src = f.read()
        for w in ("lstore.buy", "INSERT", "UPDATE", "DELETE", "executor"):
            self.assertNotIn(w, src)

    def test_the_public_sentence_under_the_notice(self):
        from ui import apjavno
        apjavno.reset_cache()
        with mock.patch.dict(sys.modules, {"trade.equity": None, "trade.aplog": None, "ui.apchart": None}):
            html = apjavno.guest_html({}, "hr")
        self.assertIn("U međuvremenu mjerimo svaki ulaz praćenih novčanika u postocima, bez pravog novca.", html)
        self.assertLess(html.index("pauziran zbog promjene strategije"), html.index("U međuvremenu mjerimo"))
        self.assertEqual(pauza.DEMO["en"], "Meanwhile we measure every entry of the followed wallets in percent, with no real money.")


class MissingTables(Base):
    """The data job's tables may not exist yet on the server (an older database): every page still renders."""

    def test_pages_render_without_the_new_tables(self):
        for db, tables in ((self.paths["insajderi"], ("i2_pp_hist",)),
                           (self.paths["wallets"], ("povijest_queue", "povijest_runs", "veliki_holderi")),
                           (self.paths["league"], ("pp_trades",))):
            con = sqlite3.connect(db)
            for t in tables:
                con.execute(f"DROP TABLE {t}")
            con.execute("DELETE FROM i2_kv WHERE key='stage_s'") if db == self.paths["insajderi"] else None
            con.commit()
            con.close()
        _t, html = novadmin.page({}, "Jure", self.now)
        for s in SECTIONS:
            self.assertIn(f"<span>{s}</span>", html, s)
        self.assertIn("Popis velikih vlasnika još ne postoji", html)
        self.assertIn("<span class=mut>još nema povijesti</span>", html)
        self.assertIn("trajala nije još izmjereno", html)
        demo = novkartice.demo_html(True, self.now)
        self.assertIn("Demo praćenje novčanika", demo)
        self.assertIn("insajderi2", demo)


class DemoNotPaused(Base):
    PAUSED = False

    def test_hidden_without_the_pause(self):
        self.assertEqual(novkartice.demo_html(True, self.now), "")
        self.assertEqual(pauza.demo_html("hr"), "")


if __name__ == "__main__":
    unittest.main()
