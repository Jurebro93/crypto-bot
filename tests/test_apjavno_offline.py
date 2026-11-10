"""Public Autopilot page (ui/apjavno.py): chat rules, what the page may and may not show, the banner, and that the
SERVER lets a visitor read /autopilot on both hosts while only a logged-in player can write (run_ui.py).

The modules of the other groups (trade.equity, trade.aplog, ui.apchart) are pinned in every test: "not installed" by
default, or a small stand-in, so the tests say the same thing before and after the night's branches are merged.
"""
import contextlib
import importlib
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, members, profiles, roles, store  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import apjavno, autopilot  # noqa: E402

WALLET = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
SECRET = "OVO-SE-NE-SMIJE-VIDJETI"
RAW_ERROR = f"HTTPError 429 https://rpc.primjer.invalid/?api-key={SECRET}"
OTHERS = ("trade.equity", "trade.aplog", "ui.apchart")
_MISSING = object()


@contextlib.contextmanager
def module(name, mod):
    """`name` importable as `mod` for the block; mod=None = as if the module were not in the tree."""
    pkg_name, _, attr = name.rpartition(".")
    pkg = importlib.import_module(pkg_name)
    old_mod, old_attr = sys.modules.get(name, _MISSING), getattr(pkg, attr, _MISSING)
    sys.modules[name] = mod
    if mod is None:
        if old_attr is not _MISSING:
            delattr(pkg, attr)
    else:
        setattr(pkg, attr, mod)
    try:
        yield
    finally:
        if old_mod is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = old_mod
        if old_attr is _MISSING:
            if hasattr(pkg, attr):
                delattr(pkg, attr)
        else:
            setattr(pkg, attr, old_attr)


def fake(name, **fns):
    m = types.ModuleType(name)
    for k, v in fns.items():
        setattr(m, k, v)
    return m


class Base(unittest.TestCase):
    ENV = ("DATA_DIR", "SOLANA_PUBLIC_KEY", "TRADE_LIVE", "TRADE_OWNER", "UI_ADMINS", "APP_URL")

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.old_db = (settings.DB, store.DB)
        settings.DB, store.DB = os.path.join(self.d, "trade.db"), os.path.join(self.d, "league.db")
        self.old_env = {k: os.environ.get(k) for k in self.ENV}
        os.environ["DATA_DIR"] = self.d
        for k in self.ENV[1:]:
            os.environ.pop(k, None)
        self.stack = contextlib.ExitStack()
        for name in OTHERS:
            self.stack.enter_context(module(name, None))
        self.stack.enter_context(mock.patch.dict(autopilot._CACHE, {}, clear=True))
        apjavno.reset_cache()
        apjavno._RW.update(need=False, retry=False)
        apjavno._WARNED.clear()
        roles.reset_cache()
        profiles.reset_cache()

    def tearDown(self):
        self.stack.close()
        settings.DB, store.DB = self.old_db
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        apjavno.reset_cache()
        roles.reset_cache()

    def trade(self, on=False, wallet=WALLET):
        """A trade.db with the owner's switch and the saved public address."""
        con = executor.connect(settings.DB)
        settings.put(con, "on", on, "Jure")
        if wallet:
            settings.put(con, "wallet_pub", wallet, "Jure")
        return con

    def live(self):
        """Real money is on: the owner's switch + (patched) the key and the env switch."""
        self.trade(on=True).close()
        self.stack.enter_context(mock.patch.object(executor, "armed", return_value=True))
        apjavno.reset_cache()


class Chat(Base):
    def test_post_limits_and_votes(self):
        con = apjavno._lcon()
        now = 1_800_000_000
        with self.assertRaises(apjavno.ChatError) as e:
            apjavno.add_message(con, None, "bok")
        self.assertEqual(e.exception.code, "login")           # only a logged-in player writes
        for text, code in (("   \n ", "empty"), ("x" * 501, "long")):
            with self.assertRaises(apjavno.ChatError) as e:
                apjavno.add_message(con, "Ivan", text, now)
            self.assertEqual(e.exception.code, code)
        first = apjavno.add_message(con, "Ivan", "x" * 500, now)   # exactly 500 is fine
        with self.assertRaises(apjavno.ChatError) as e:
            apjavno.add_message(con, "Ivan", "x" * 500, now + 1)
        self.assertEqual(e.exception.code, "dup")
        for i in range(4):
            apjavno.add_message(con, "Ivan", f"poruka {i}", now + 2 + i)
        with self.assertRaises(apjavno.ChatError) as e:          # the 6th inside 10 minutes
            apjavno.add_message(con, "Ivan", "još jedna", now + 30)
        self.assertEqual(e.exception.code, "rate")
        apjavno.add_message(con, "Panda", "ja smijem", now + 30)     # the limit is per player
        apjavno.add_message(con, "Ivan", "nakon stanke", now + apjavno.RATE_S + 10)
        # +1: on, counted once per player, off again
        self.assertTrue(apjavno.toggle_vote(con, "Panda", first, now))
        self.assertTrue(apjavno.toggle_vote(con, "Jure", first, now))
        rows = apjavno.messages(con, "Panda")
        self.assertEqual([r["id"] for r in rows], sorted((r["id"] for r in rows), reverse=True))   # newest first
        row = next(r for r in rows if r["id"] == first)
        self.assertEqual((row["votes"], row["mine"]), (2, True))
        self.assertFalse(next(r for r in apjavno.messages(con, "Ivan") if r["id"] == first)["mine"])
        self.assertFalse(apjavno.toggle_vote(con, "panda", first, now))    # same player, other case: his +1 goes off
        self.assertEqual(next(r for r in apjavno.messages(con) if r["id"] == first)["votes"], 1)
        with self.assertRaises(apjavno.ChatError) as e:
            apjavno.toggle_vote(con, "Panda", 9999, now)
        self.assertEqual(e.exception.code, "gone")
        self.assertEqual(len(apjavno.messages(con, limit=3)), 3)
        self.assertTrue(all(r["id"] < first + 2 for r in apjavno.messages(con, before=first + 2)))
        con.close()

    def test_vote_taps_are_limited(self):
        con = apjavno._lcon()
        mid = apjavno.add_message(con, "Ivan", "glasajte", 1_800_000_000)
        for _ in range(apjavno.VOTE_N):
            apjavno.toggle_vote(con, "Panda", mid, 1_800_000_100)
        with self.assertRaises(apjavno.ChatError) as e:
            apjavno.toggle_vote(con, "Panda", mid, 1_800_000_101)
        self.assertEqual(e.exception.code, "votes")
        apjavno.toggle_vote(con, "Panda", mid, 1_800_000_100 + apjavno.VOTE_S + 5)   # a minute later it works again
        con.close()

    def test_only_owner_hides(self):
        con = apjavno._lcon()
        mid = apjavno.add_message(con, "Ivan", "ružna poruka")
        with self.assertRaises(apjavno.ChatError) as e:
            apjavno.set_hidden(con, "Ivan", mid)
        self.assertEqual(e.exception.code, "no")
        with self.assertRaises(apjavno.ChatError):
            apjavno.set_hidden(con, None, mid)
        apjavno.set_hidden(con, "Jure", mid)                       # TRADE_OWNER default
        self.assertEqual(apjavno.messages(con), [])               # nobody else sees it
        self.assertEqual(len(apjavno.messages(con, with_hidden=True)), 1)
        with self.assertRaises(apjavno.ChatError):                 # and it takes no more +1
            apjavno.toggle_vote(con, "Panda", mid)
        frag = apjavno.chat_fragment("Jure")
        self.assertIn("ružna poruka", frag)                        # the owner still sees it, marked, with "Vrati"
        self.assertIn("Vrati", frag)
        self.assertNotIn("ružna poruka", apjavno.chat_fragment("Ivan"))
        self.assertNotIn("ružna poruka", apjavno.chat_fragment(None))
        apjavno.set_hidden(con, "Jure", mid, False)
        self.assertEqual(len(apjavno.messages(con)), 1)
        con.close()

    def test_text_is_escaped_and_never_a_link(self):
        con = apjavno._lcon()
        evil = ('<script>alert(1)</script> <a href="https://zlo.invalid">klik</a> "navodnici" https://zlo.invalid/x?a=1&b=2 '
                'pisi.mi@primjer.hr\nnovi red ' + "5" * 88)
        apjavno.add_message(con, "Ivan", evil)
        con.close()
        for who in (None, "Panda", "Jure"):
            frag = apjavno.chat_fragment(who)
            self.assertNotIn("<script>alert", frag)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", frag)
            self.assertNotIn('href="https://zlo.invalid', frag)     # no link is made from the text
            self.assertNotIn("<a href=&quot;", frag)
            self.assertIn("https://zlo.invalid/x?a=1&amp;b=2", frag)   # the address stays readable as plain text
            self.assertNotIn("pisi.mi@primjer.hr", frag)            # e-mail addresses are not shown
            self.assertNotIn("5" * 88, frag)                        # nor a string as long as a secret key
            self.assertIn("<br>novi red", frag)
        guest, player = apjavno.chat_fragment(None), apjavno.chat_fragment("Panda")
        self.assertNotIn("<form", guest)                            # a guest gets no form at all
        self.assertIn(f'action="{apjavno.PATH}/plus"', player)
        self.assertNotIn("/sakrij", player)                         # only the owner gets the hide button
        self.assertIn("/sakrij", apjavno.chat_fragment("Jure"))

    def test_clean_text(self):
        self.assertEqual(apjavno.clean_text("  a\r\n\r\n\r\n\r\nb\x00‮​ c  "), "a\n\nb c")

    def test_forms(self):
        self.assertEqual(apjavno.post("/autopilot/poruka", {"text": "bok"}, None), "/autopilot?e=login#chat")
        self.assertEqual(apjavno.post("/autopilot/poruka", {"text": "prijedlog"}, "Ivan"), "/autopilot#chat")
        self.assertEqual(apjavno.post("/autopilot/poruka", {"text": ""}, "Ivan"), "/autopilot?e=empty#chat")
        self.assertEqual(apjavno.post("/autopilot/plus", {"id": "abc"}, "Ivan"), "/autopilot?e=gone#chat")
        self.assertEqual(apjavno.post("/autopilot/plus", {"id": "1"}, "Ivan"), "/autopilot#chat")
        self.assertEqual(apjavno.post("/autopilot/sakrij", {"id": "1"}, "Ivan"), "/autopilot?e=no#chat")
        self.assertEqual(apjavno.post("/autopilot/nesto", {}, "Ivan"), "/autopilot?e=what#chat")
        # the refusal on the page is one of our own sentences, whatever the address says
        _, body = apjavno.page({"e": "rate"}, "Ivan")
        self.assertIn(apjavno.ERR["rate"], body)
        _, body = apjavno.page({"e": "<b>x</b> bilo što"}, "Ivan")
        self.assertNotIn("bilo što", body)

    def test_guest_list_is_kept_a_few_seconds_and_refreshed_on_change(self):
        apjavno.post("/autopilot/poruka", {"text": "prva"}, "Ivan")
        self.assertIn("prva", apjavno.chat_fragment(None))
        with mock.patch.object(apjavno, "_lcon", side_effect=AssertionError("čitanje baze")):
            self.assertIn("prva", apjavno.chat_fragment(None))      # served from memory, no database read
        apjavno.post("/autopilot/poruka", {"text": "druga"}, "Ivan")
        self.assertIn("druga", apjavno.chat_fragment(None))          # a new message drops the kept copy


class State(Base):
    def test_live_only_when_executor_says_so(self):
        self.assertEqual(apjavno.live_state(), {"live": False, "on": False, "since": None})   # no trade.db at all
        self.trade(on=True).close()
        apjavno.reset_cache()
        st = apjavno.live_state()
        self.assertEqual((st["live"], st["on"]), (False, True))    # switch on, but no key and env switch: trial
        self.assertEqual(apjavno.banner_html(), "")
        self.assertEqual(apjavno.landing_strip("hr"), "")
        with mock.patch.object(executor, "armed", return_value=True):
            apjavno.reset_cache()
            st = apjavno.live_state()
            self.assertTrue(st["live"])
            self.assertAlmostEqual(st["since"], time.time(), delta=60)
        apjavno.reset_cache()
        con = executor.connect(settings.DB)
        settings.put(con, "on", False, "Jure")
        con.close()
        with mock.patch.object(executor, "armed", return_value=True):
            self.assertFalse(apjavno.live_state()["live"])          # key there, switch off: not live

    def test_state_is_cached_30_s(self):
        self.trade(on=True).close()
        with mock.patch.object(executor, "is_live", return_value=True) as is_live:
            for _ in range(50):
                self.assertTrue(apjavno.live_state()["live"])
                apjavno.banner_html(path="/tokens")
            self.assertEqual(is_live.call_count, 1)
            apjavno._LIVE["ts"] -= apjavno.LIVE_TTL_S + 1
            apjavno.live_state()
            self.assertEqual(is_live.call_count, 2)

    def test_error_reads_as_not_live(self):
        self.trade(on=True).close()
        with mock.patch.object(executor, "is_live", side_effect=RuntimeError(RAW_ERROR)):
            self.assertFalse(apjavno.live_state()["live"])
            self.assertEqual(apjavno.banner_html(), "")

    def test_banner(self):
        from ui import html
        self.assertEqual(apjavno.banner_html(), "")
        self.assertNotIn("apj-ban", html.page("Tokeni", "<h1>Tokeni</h1>", "/tokens"))
        self.live()
        ban = apjavno.banner_html(path="/tokens")
        self.assertIn("Autopilot je live:", ban)
        self.assertIn("podacima alata tradamo pravim novcem.", ban)
        self.assertIn("Uđi, pogledaj statistiku i dodaj svoj prijedlog.", ban)
        self.assertIn('href="/autopilot"', ban)
        self.assertNotIn("—", ban)
        self.assertEqual(apjavno.banner_html(path="/autopilot"), "")    # not on the page it leads to
        page = html.page("Tokeni", "<h1>Tokeni</h1>", "/tokens")
        self.assertIn("apj-ban", page)
        self.assertLess(page.index("apj-ban"), page.index("<main>"))     # on top: right under the top bar
        self.assertNotIn("<a class=apj-ban", html.page("Autopilot", "<h1>x</h1>", "/autopilot"))
        with mock.patch.object(apjavno, "banner_html", side_effect=RuntimeError("pad")):
            self.assertIn("<h1>Tokeni</h1>", html.page("Tokeni", "<h1>Tokeni</h1>", "/tokens"))   # a page survives it

    def test_landing_strip(self):
        self.assertEqual(apjavno.landing_strip("hr"), "")
        self.assertEqual(apjavno.landing_strip("en"), "")
        self.live()
        hr, en = apjavno.landing_strip("hr"), apjavno.landing_strip("en")
        self.assertIn("Tradanje pravim sredstvima je live", hr)
        self.assertIn("Provjeri kako nam ide", hr)
        self.assertIn('href="/autopilot"', hr)
        self.assertIn("Real-money trading is live", en)
        self.assertIn('href="/en/autopilot"', en)
        with mock.patch.object(apjavno, "snapshot", side_effect=RuntimeError("pad")):
            self.assertEqual(apjavno.landing_strip("hr"), "")           # the front page never fails because of it


class Page(Base):
    def seed(self, on=True):
        con = self.trade(on=on)
        rows = [("BONK", "live", "closed", 0.1, 0.141, 0.0), ("WIF", "live", "closed", 0.1, 0.079, 0.001),
                ("MEW", "live", "closed", 0.1, 0.11, 0.0), ("PNUT", "live", "open", 0.1, 0.0, 0.0),
                ("STARI", "dry", "closed", 0.1, 0.9, 0.0), ("NE", "live", "blocked", None, None, 0.0)]
        for i, (sym, mode, status, sin, sback, fees) in enumerate(rows):
            con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, sol_back, closed_ts, "
                        "fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (MINT, sym, int(time.time()) - 7200 + i, mode, status, RAW_ERROR, sin, sback,
                         int(time.time()) - 3600 + i if status == "closed" else None, fees))
        con.execute("INSERT INTO orders (ts, token, side, mode, status, error, reason) VALUES (?,?,?,?,?,?,?)",
                    (int(time.time()), MINT, "buy", "live", "failed", RAW_ERROR, RAW_ERROR))
        con.commit()
        con.close()

    def test_trial_mode_is_said_plainly(self):
        self.seed(on=True)       # the switch alone is not real money
        title, body = apjavno.page({}, None)
        self.assertIn("Probni rad", body)
        self.assertIn("bez pravog novca", body)
        self.assertIn("ne troši pravi novac", body)
        self.assertNotIn("apj-state live", body)
        self.assertNotIn("Uživo · pravi novac", body)
        self.assertIn("probni rad", title)

    def test_live_page_numbers_and_wallet(self):
        self.seed()
        self.live()
        title, body = apjavno.page({}, None)
        self.assertEqual(title, "Autopilot uživo")
        self.assertIn("Uživo · pravi novac", body)
        self.assertIn(WALLET, body)
        self.assertIn(f"https://solscan.io/account/{WALLET}", body)
        self.assertIn("apj-copy", body)
        st = apjavno.snapshot()["stats"]
        self.assertEqual((st["mode"], st["n"], st["wins"], st["open"]), ("live", 3, 2, 1))   # the trial trade is not counted
        self.assertAlmostEqual(st["pnl"], 0.041 - 0.022 + 0.01)
        self.assertEqual((st["best"]["symbol"], st["worst"]["symbol"]), ("BONK", "WIF"))
        self.assertIn("+0.029 SOL", body)
        self.assertIn("Zatvoreni tradeovi", body)
        self.assertIn("Najbolji trade", body)
        self.assertIn("Najgori trade", body)
        self.assertNotIn("STARI", body)

    def test_stats_fall_back_to_trial_trades_only_without_real_ones(self):
        con = self.trade(on=False)
        con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, sol_in, sol_back, closed_ts) VALUES "
                    "(?,?,?,?,?,?,?,?)", (MINT, "PROBA", 1, "dry", "closed", 0.1, 0.12, 2))
        con.commit()
        con.close()
        _, body = apjavno.page({}, None)
        self.assertEqual(apjavno.snapshot()["stats"]["mode"], "dry")
        self.assertIn("probno, bez pravog novca", body)

    def test_no_raw_error_text_anywhere(self):
        self.seed()
        self.live()
        con = store.connect()
        copy.follow(con, settings.LEAGUE_USER, "kol", "dobar_kol")
        con.close()
        rows = [{"ts": int(time.time()) - 60, "kind": "kupio", "token": MINT, "symbol": "BONK", "source": "@dobar_kol",
                 "why": RAW_ERROR, "why_short": "", "sol": 0.1, "pnl_pct": None, "mode": "live", "stage": "pravi",
                 "sig": "5" * 88, "trebao": None},
                {"ts": int(time.time()) - 50, "kind": "prodao", "token": MINT, "symbol": "BONK", "source": RAW_ERROR,
                 "why": RAW_ERROR, "why_short": RAW_ERROR, "sol": 0.12, "pnl_pct": 20.0, "mode": "live", "stage": "pravi",
                 "sig": RAW_ERROR, "trebao": None},
                {"ts": int(time.time()) - 40, "kind": "prodao", "token": "nije adresa", "symbol": "WIF", "source": "",
                 "why": "stop", "why_short": "stop", "sol": 0.08, "pnl_pct": -20.0, "mode": "dry", "stage": "pravi",
                 "sig": None, "trebao": None},
                {"ts": int(time.time()) - 30, "kind": "nije_proslo", "token": MINT, "symbol": "MEW", "source": "",
                 "why": RAW_ERROR, "why_short": RAW_ERROR, "sol": None, "pnl_pct": None, "mode": "live", "stage": "pravi",
                 "sig": None, "trebao": True}]
        summ = {"signali": 9, "kupio": 1, "prodao": 2, "preskocio": 5, "nije_proslo": 1,
                "razlozi": [("signal star", 3), (RAW_ERROR, 2)]}
        aplog = fake("trade.aplog", entries=lambda tcon, lcon=None, limit=80, since=None: rows,
                     summary=lambda r, now=None: summ)
        for mod in (aplog, None):     # with the decision log (even a sloppy one) and with the plain fallback
            with module("trade.aplog", mod):
                apjavno.reset_cache()
                for html in (apjavno.page({}, None)[1], apjavno.guest_html({}), apjavno.page({}, "Jure")[1]):
                    for bad in (SECRET, "api-key", "rpc.primjer", "HTTPError", "429"):
                        self.assertNotIn(bad, html, f"{bad} ({'aplog' if mod else 'fallback'})")
        with module("trade.aplog", aplog):
            apjavno.reset_cache()
            _, body = apjavno.page({}, None)
            self.assertIn(apjavno.NEUTRAL_REASON, body)          # a bad reason is replaced, the row stays
            self.assertIn("izvor: @dobar_kol", body)
            self.assertIn("stop", body)
            self.assertIn("+20.0 %", body)
            self.assertIn(f"https://solscan.io/tx/{'5' * 88}", body)
            self.assertIn("3 signal star", body)
            self.assertIn("9 signala", body)
            self.assertNotIn("MEW", body)                         # only entries and exits are listed
            self.assertIn("<span class=apj-tag>probno</span>", body)   # a trial row among real ones is marked

    def test_reason_filter(self):
        for ok in ("signal star", "MC ispod 30k", "bez dokaza u demu", "kasni poziv", "likvidnost", "rug", "limit", "TP +15 %",
                   "zapis nije stigao"):
            self.assertEqual(apjavno.reason(ok), ok)
        for bad in (RAW_ERROR, "Traceback (most recent call last)", "KeyError: 'x'", "connection timed out", "x" * 60,
                    "GET /v2?mint=abc", "{'error': 1}", "see www.primjer.invalid"):
            self.assertEqual(apjavno.reason(bad), apjavno.NEUTRAL_REASON, bad)
        self.assertEqual(apjavno.reason(None), "")

    def test_who_is_followed_and_who_chose(self):
        con = self.trade(on=True)
        lcon = store.connect()
        tool_id = copy.follow(lcon, settings.LEAGUE_USER, "kol", "alatov_kol", "", 25, 5, "tpsl", "15%", "-20%")
        copy.follow(lcon, settings.LEAGUE_USER, "kol", "vlasnikov_kol")
        copy.follow(lcon, settings.LEAGUE_USER, "wallet", WALLET, "Kit 7")
        copy.follow(lcon, settings.LEAGUE_USER, "kol", "preporuceni_kol")
        copy.follow(lcon, "Ivan", "kol", "ivanov_privatni_kol")     # another player's follow is nobody's business
        lcon.close()
        settings.put(con, "auto_follows", [tool_id], "alat")
        con.close()
        by = {f["target"]: f["by"] for f in apjavno.snapshot()["follows"]}
        self.assertEqual(by, {"alatov_kol": "alat", "vlasnikov_kol": "vlasnik", WALLET: "vlasnik", "preporuceni_kol": "vlasnik"})
        # a target the tool's own lists hold (already in memory, nothing is computed for it) also reads as its pick
        with mock.patch.dict(autopilot._CACHE, {"kol": (time.time(), {7: [{"handle": "Preporuceni_KOL"}], 14: [], 30: []}),
                                                "proven": (time.time(), [{"wallet": WALLET}]),
                                                "tok": (time.time(), {"dugo": [], "moon": []})}):
            apjavno.reset_cache()
            by = {f["target"]: f["by"] for f in apjavno.snapshot()["follows"]}
            self.assertEqual(by["preporuceni_kol"], "alat")
            self.assertEqual(by[WALLET], "alat")
            self.assertEqual(by["vlasnikov_kol"], "vlasnik")
        with mock.patch.object(autopilot, "kol_recs", side_effect=AssertionError("skupo")), \
                mock.patch.object(autopilot, "wallet_recs", side_effect=AssertionError("skupo")):
            apjavno.reset_cache()
            _, body = apjavno.page({}, None)     # the public page never computes the recommendation lists
        self.assertIn("preporuka alata", body)
        self.assertIn("odabir vlasnika", body)
        self.assertIn("https://x.com/alatov_kol", body)
        self.assertIn("cilj 15%, stop -20%", body)
        self.assertIn("Kit 7", body)
        self.assertNotIn("ivanov_privatni_kol", body)

    def test_value_from_equity_and_chart_from_apchart(self):
        self.seed()
        self.live()
        summ = {"value_sol": 3.21, "value_usd": 489.0, "value_eur": 450.0, "net_in_sol": 3.0, "pnl_sol": 0.21,
                "pnl_pct": "nešto krivo", "pnl_24h_sol": -0.02, "last_ts": int(time.time()) - 120, "n": 2}
        ser = [{"ts": 1, "value_sol": 3.0}, {"ts": 2, "value_sol": 3.21}]
        seen = {}

        def chart_html(series, summary, deposits=(), ident="ap", compact=False, lang="hr"):
            seen.update(series=series, deposits=list(deposits), ident=ident, compact=compact)
            return "<svg id=pravi-graf></svg>"
        equity = fake("trade.equity", summary=lambda con, now=None: summ, series=lambda con, since=None, max_points=600: ser,
                      deposits=lambda con: [{"ts": 1, "sol": 3.0}])
        with module("trade.equity", equity), module("ui.apchart", fake("ui.apchart", chart_html=chart_html)):
            apjavno.reset_cache()
            _, body = apjavno.page({}, None)
        self.assertIn("3.210 <small>SOL</small>", body)
        self.assertIn("489 $ · 450 €", body)
        self.assertIn("+0.210 SOL (+7.0 %)", body)                 # the share is worked out from the SOL amounts
        self.assertIn("-0.020 SOL", body)
        self.assertIn("<svg id=pravi-graf></svg>", body)
        self.assertEqual((seen["ident"], seen["compact"], seen["series"], seen["deposits"]),
                         ("apj", True, ser, [{"ts": 1, "sol": 3.0}]))
        # the chart module failing (or missing) leaves the page up with the plain line
        boom = fake("ui.apchart", chart_html=mock.Mock(side_effect=RuntimeError(RAW_ERROR)))
        with module("trade.equity", equity), module("ui.apchart", boom):
            apjavno.reset_cache()
            _, body = apjavno.page({}, None)
        self.assertIn("apj-spark", body)
        self.assertNotIn(SECRET, body)
        apjavno.reset_cache()
        _, body = apjavno.page({}, None)                            # no equity module at all
        self.assertIn("Prva snimka još nije stigla", body)

    def test_readonly_helper_gets_the_normal_handle(self):
        """A helper of another group that must create its table first fails on the read-only handle once; the page then
        uses the handle the Autopilot page uses and shows the value in the same request."""
        import sqlite3
        self.seed()

        def summary(con, now=None):
            con.execute("CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, sol REAL)")
            return {"value_sol": 1.5, "net_in_sol": 1.0, "pnl_sol": 0.5}
        equity = fake("trade.equity", summary=summary, series=lambda con, since=None, max_points=600: [],
                      deposits=lambda con: [])
        con = apjavno._tcon()
        with self.assertRaises(sqlite3.OperationalError):          # the public page's own handle cannot write
            con.execute("INSERT INTO settings VALUES ('x','1',1,'')")
        con.close()
        with module("trade.equity", equity):
            _, body = apjavno.page({}, None)
        self.assertIn("1.500 <small>SOL</small>", body)
        self.assertTrue(apjavno._RW["need"])

    def test_snapshot_is_kept_and_guest_page_too(self):
        self.seed()
        self.live()
        apjavno.guest_html({})
        with mock.patch.object(apjavno, "_read", side_effect=AssertionError("čitanje baza")), \
                mock.patch.object(apjavno, "_lcon", side_effect=AssertionError("čitanje baze")):
            for _ in range(20):
                apjavno.guest_html({})       # the whole guest page from memory
            apjavno.snapshot()
        apjavno._SNAP["ts"] -= apjavno.SNAP_TTL_S + 1
        with mock.patch.object(apjavno, "_read", side_effect=RuntimeError("pad")):
            self.assertIsNotNone(apjavno.snapshot()["stats"])       # a failed rebuild keeps the last good one

    def test_public_page_shows_nothing_private(self):
        self.seed()
        self.live()
        os.environ["SOLANA_PUBLIC_KEY"] = WALLET
        apjavno.post("/autopilot/poruka", {"text": "javi se na ivan@primjer.hr"}, "Ivan")
        html = apjavno.guest_html({})
        for bad in ("SOLANA_", "TRADE_LIVE", "TRADE_OWNER", "UI_PASS", "Render", "Helius", "PumpPortal", "Jupiter",
                    "/pravi-trade", "<form", "ivan@primjer.hr", "Uključi", "Prodaj sve", "—"):
            self.assertNotIn(bad, html, bad)
        self.assertIn("Prijavi se", html)
        self.assertIn("Zatraži pristup", html)
        self.assertIn("/autopilot?prijava=1", html)
        self.assertIn(f'data-src="{apjavno.CHAT_PATH}"', html)
        self.assertIn("15000", html)                                # the list refreshes every 15 s, not every second
        # a player's copy has the chat form, still no trading control
        _, body = apjavno.page({}, "Ivan")
        self.assertIn(f'action="{apjavno.PATH}/poruka"', body)
        self.assertIn("maxlength=500", body)
        self.assertNotIn("/pravi-trade", body)

    def test_address_must_look_like_an_address(self):
        self.assertEqual(apjavno._address({"wallet_pub": WALLET}), WALLET)
        self.assertIsNone(apjavno._address({"wallet_pub": "5" * 88}))    # as long as a secret key: never printed
        self.assertIsNone(apjavno._address({"wallet_pub": "<b>nije</b>"}))
        self.assertIsNone(apjavno._address({}))


class Http(unittest.TestCase):
    """The server: who gets the page, who may write, and where each host sends /autopilot."""

    def setUp(self):
        self.old_env = dict(os.environ)
        self.old_db = (settings.DB, store.DB)
        d = tempfile.mkdtemp()
        settings.DB, store.DB = os.path.join(d, "trade.db"), os.path.join(d, "league.db")
        os.environ.update(DATA_DIR=d, UI_USERS="Ivan,Jure", UI_PASS_IVAN="ivanpw", UI_PASS_JURE="jurepw",
                          UI_PASSWORD="shared", UI_TEST_PASSWORD="gledam")
        for k in ("UI_ADMINS", "TRADE_OWNER", "SITE_URL", "APP_URL", "TRADE_LIVE", "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        self.stack = contextlib.ExitStack()
        for name in OTHERS:
            self.stack.enter_context(module(name, None))
        profiles.reset_cache()
        roles.reset_cache()
        apjavno.reset_cache()
        apjavno._RW.update(need=False, retry=False)
        self.srv = None

    def tearDown(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
        self.stack.close()
        settings.DB, store.DB = self.old_db
        os.environ.clear()
        os.environ.update(self.old_env)
        roles.reset_cache()
        apjavno.reset_cache()
        import run_ui
        importlib.reload(run_ui)

    def start(self):
        import run_ui
        importlib.reload(run_ui)
        self.ui = run_ui
        self.srv = run_ui.ThreadingHTTPServer(("127.0.0.1", 0), run_ui.Handler)
        self.srv.verbose = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        self.opener = urllib.request.build_opener(NoRedirect)

    def call(self, path, data=None, cookie="", host=None, origin="same", token=True):
        headers = {"Cookie": cookie} if cookie else {}
        if host:
            headers["Host"] = host
        if data is not None:   # like a browser: Origin of the page and the form token the page script adds
            if origin:
                headers["Origin"] = (("https://" + host) if host else self.base) if origin == "same" else origin
            sess = cookie.split("=", 1)[1] if cookie.startswith(self.ui.COOKIE + "=") else ""
            if token:
                data = {**data, "_csrf": self.ui.csrf_token(sess)}
        req = urllib.request.Request(self.base + path, data=urllib.parse.urlencode(data).encode() if data is not None else None,
                                     headers=headers)
        try:
            r = self.opener.open(req)
        except urllib.error.HTTPError as e:
            r = e
        return r.code, r.headers, r.read().decode("utf-8", "replace")

    def login(self, name, pw):
        code, hdr, _ = self.call("/prijava", {"name": name, "pw": pw, "next": "/autopilot"})
        self.assertEqual(code, 303, name)
        return hdr["Set-Cookie"].split(";")[0]

    def test_read_without_login_write_only_logged_in(self):
        self.start()
        ivan, jure, viewer = self.login("Ivan", "ivanpw"), self.login("Jure", "jurepw"), self.login("Claude", "gledam")
        # a visitor reads the page and the list; no login form, no app cookies, not offered to search engines yet
        code, hdr, body = self.call("/autopilot")
        self.assertEqual(code, 200)
        self.assertIn("<h1>Autopilot</h1>", body)
        self.assertIn("Probni rad", body)
        self.assertNotIn("name=pw", body)
        self.assertNotIn("<form", body)
        self.assertNotIn("<aside", body)                       # the public frame, not the app with its menu
        self.assertIsNone(hdr.get_all("Set-Cookie"))
        self.assertIn("noindex", hdr.get("X-Robots-Tag", ""))
        self.assertEqual(self.call("/autopilot/chat")[0], 200)
        self.assertEqual(self.call("/tokens")[0], 401)          # the app itself still needs the login
        # ... and can write nothing
        self.assertEqual(self.call("/autopilot/poruka", {"text": "gost"})[0], 401)
        self.assertEqual(self.call("/autopilot/plus", {"id": "1"})[0], 401)
        self.assertNotIn("gost", self.call("/autopilot/chat")[2])
        # "Prijavi se" on the public copy: a visitor goes to the login form and comes back here
        code, hdr, _ = self.call("/autopilot?prijava=1")
        self.assertEqual((code, hdr["Location"]), (303, "/prijava?next=/autopilot"))
        # a player gets the page inside the app, with the form and the token cookie
        code, hdr, body = self.call("/autopilot", cookie=ivan)
        self.assertEqual(code, 200)
        self.assertIn('action="/autopilot/poruka"', body)
        self.assertIn("<aside", body)
        self.assertIn("cb_csrf=", " ".join(hdr.get_all("Set-Cookie") or []))
        self.assertEqual(self.call("/autopilot?prijava=1", cookie=ivan)[0], 200)
        code, hdr, _ = self.call("/en/autopilot", cookie=ivan)
        self.assertEqual((code, hdr["Location"]), (303, "/autopilot"))
        # he writes: back to the chat, and everybody sees it
        code, hdr, _ = self.call("/autopilot/poruka", {"text": "Prijedlog: <b>manji</b> stop"}, ivan)
        self.assertEqual((code, hdr["Location"]), (303, "/autopilot#chat"))
        for cookie in ("", ivan, jure):
            body = self.call("/autopilot", cookie=cookie)[2]
            self.assertIn("Prijedlog: &lt;b&gt;manji&lt;/b&gt; stop", body)
            self.assertNotIn("<b>manji</b>", body)
        # the form token and the Origin are both needed
        self.assertEqual(self.call("/autopilot/poruka", {"text": "bez tokena"}, ivan, token=False)[0], 403)
        self.assertEqual(self.call("/autopilot/poruka", {"text": "tuđi origin"}, ivan, origin="https://zlo.invalid")[0], 403)
        self.assertEqual(self.call("/autopilot/poruka", {"text": "bez origina"}, ivan, origin=None)[0], 403)
        self.assertEqual(self.call("/autopilot/plus", {"id": "1"}, ivan, token=False)[0], 403)
        body = self.call("/autopilot/chat")[2]
        for text in ("bez tokena", "tuđi origin", "bez origina"):
            self.assertNotIn(text, body)
        # the view-only account and the shared password have no player: no writing
        code, hdr, _ = self.call("/autopilot/poruka", {"text": "gledatelj"}, viewer)
        self.assertEqual((code, hdr["Location"]), (303, "/autopilot?e=login#chat"))
        self.assertNotIn('action="/autopilot/poruka"', self.call("/autopilot", cookie=viewer)[2])
        # +1 on and off (the page script: the refreshed list comes straight back)
        code, _, frag = self.call("/autopilot/plus", {"id": "1", "ajax": "1"}, jure)
        self.assertEqual(code, 200)
        self.assertIn("apj-plus on", frag)
        self.assertIn("<b>1</b>", frag)
        self.assertNotIn("<html", frag)
        self.assertIn("<b>1</b>", self.call("/autopilot/chat")[2])            # a guest sees the count
        self.assertNotIn("apj-plus on", self.call("/autopilot/chat", cookie=ivan)[2])   # Ivan did not vote
        code, _, frag = self.call("/autopilot/plus", {"id": "1", "ajax": "1"}, jure)
        self.assertNotIn("apj-plus on", frag)
        # hiding: not a player's, the owner's
        code, hdr, _ = self.call("/autopilot/sakrij", {"id": "1"}, ivan)
        self.assertEqual(hdr["Location"], "/autopilot?e=no#chat")
        self.assertIn("Prijedlog:", self.call("/autopilot/chat")[2])
        code, hdr, _ = self.call("/autopilot/sakrij", {"id": "1"}, jure)
        self.assertEqual(hdr["Location"], "/autopilot#chat")
        self.assertNotIn("Prijedlog:", self.call("/autopilot/chat")[2])
        self.assertNotIn("Prijedlog:", self.call("/autopilot", cookie=ivan)[2])
        self.assertIn("Prijedlog:", self.call("/autopilot", cookie=jure)[2])
        # the limit holds on the server: the 6th message of 10 minutes is refused with our own sentence
        for i in range(4):
            self.assertEqual(self.call("/autopilot/poruka", {"text": f"poruka {i}"}, ivan)[1]["Location"], "/autopilot#chat")
        code, hdr, _ = self.call("/autopilot/poruka", {"text": "previše"}, ivan)
        self.assertEqual(hdr["Location"], "/autopilot?e=rate#chat")
        code, _, frag = self.call("/autopilot/poruka", {"text": "previše", "ajax": "1"}, ivan)
        self.assertIn("Previše poruka", frag)
        self.assertNotIn("previše</div>", self.call("/autopilot/chat")[2])
        self.assertEqual(self.call("/autopilot/nepoznato", {"x": "1"}, ivan)[1]["Location"], "/autopilot?e=what#chat")

    def test_registered_member_writes_too(self):
        self.start()
        con = members.connect()
        try:
            tok = members.renew(con, "Jure")
            members.register(con, tok, "Novi", "novipw1novipw1", "novipw1novipw1", ["Ivan", "Jure", "Claude"])
        finally:
            con.close()
        novi = self.login("Novi", "novipw1novipw1")
        self.assertEqual(self.call("/autopilot/poruka", {"text": "bok svima"}, novi)[1]["Location"], "/autopilot#chat")
        self.assertIn("bok svima", self.call("/autopilot/chat")[2])

    def test_english_copy_for_a_visitor(self):
        self.start()
        code, _, body = self.call("/en/autopilot")
        self.assertEqual(code, 200)
        self.assertIn("<html lang=en>", body)
        self.assertIn('data-src="/autopilot/chat?l=en"', body)
        self.assertEqual(self.call("/autopilot/chat?l=en")[0], 200)
        self.assertIn("<html lang=hr>", self.call("/autopilot")[2])

    def test_two_hosts(self):
        os.environ.update(SITE_URL="https://memesonar.app", APP_URL="https://app.memesonar.app",
                          RENDER_EXTERNAL_URL="https://crypto-bot-ylvn.onrender.com")
        self.start()
        m, S, A = self.ui.moved_to_site, "https://memesonar.app", "https://app.memesonar.app"
        site, app, old = "memesonar.app", "app.memesonar.app", "crypto-bot-ylvn.onrender.com"
        for path in ("/autopilot", "/en/autopilot", "/autopilot/chat"):
            for logged_in in (False, True):
                self.assertIsNone(m(site, path, logged_in), path)       # a visitor reads it on the site
                self.assertIsNone(m(app, path, logged_in), path)        # a player is NOT sent away from the app host
                self.assertEqual(m(old, path, logged_in), S + path)     # the old address moves to the site
        self.assertEqual(m(site, "/autopilot/poruka", False), A + "/autopilot/poruka")   # only reading is shared
        self.assertEqual(m(site, "/pravi-trade", True), A + "/pravi-trade")              # the admin page stays an app page
        self.assertEqual(m(app, "/coin/pengu", False), S + "/coin/pengu")                # other public pages as before
        # through the server, with the Host a browser would send
        ivan = self.login("Ivan", "ivanpw")
        code, _, body = self.call("/autopilot", host=site)
        self.assertEqual(code, 200)
        self.assertIn(f'href="{A}/autopilot?prijava=1"', body)          # the login lives on the app host
        self.assertIn(f'<link rel=canonical href="{S}/autopilot">', body)
        self.assertEqual(self.call("/autopilot/chat", host=site)[0], 200)
        code, _, body = self.call("/autopilot", host=app)
        self.assertEqual(code, 200)                                     # a guest on the app host reads it too
        code, _, body = self.call("/autopilot", cookie=ivan, host=app)
        self.assertEqual(code, 200)
        self.assertIn('action="/autopilot/poruka"', body)
        code, hdr, _ = self.call("/autopilot", host=old)
        self.assertEqual((code, hdr["Location"]), (301, S + "/autopilot"))
        code, hdr, _ = self.call("/autopilot?prijava=1", host=app)
        self.assertEqual((code, hdr["Location"]), (303, "/prijava?next=/autopilot"))
        # a form sent to the site host goes on to the app host (where the login is), keeping the method
        code, hdr, _ = self.call("/autopilot/poruka", {"text": "sa sitea"}, ivan, host=site)
        self.assertEqual((code, hdr["Location"]), (308, A + "/autopilot/poruka"))
        code, hdr, _ = self.call("/autopilot/poruka", {"text": "s app hosta"}, ivan, host=app)
        self.assertEqual((code, hdr["Location"]), (303, "/autopilot#chat"))
        self.assertIn("s app hosta", self.call("/autopilot/chat", host=site)[2])

    def test_one_host(self):
        os.environ.update(SITE_URL="https://memesonar.app", RENDER_EXTERNAL_URL="https://crypto-bot-ylvn.onrender.com")
        os.environ.pop("APP_URL", None)
        self.start()
        m = self.ui.moved_to_site
        for logged_in in (False, True):
            self.assertIsNone(m("memesonar.app", "/autopilot", logged_in))
            # the old address keeps the app (and the login cookie): the player stays and can write there
            self.assertIsNone(m("crypto-bot-ylvn.onrender.com", "/autopilot", logged_in))
        self.assertFalse(self.ui.is_public("/autopilot"))     # shared, not public: see the note at SHARED_PATH
        self.assertEqual(self.call("/autopilot", host="memesonar.app")[0], 200)


if __name__ == "__main__":
    unittest.main()
