"""Autopilot page additions of 9.11. (Jure): exit target at the top, "Zovu sada" (who called what in the last hour,
follow the whole crew), "Što kupiti sada", followed Telegram channels read every 2 s, time indexes."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from tests.test_trade_offline import CFG, FakeJup  # noqa: E402
from trade import executor, jupiter, settings  # noqa: E402
from ui import pravitrade  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = int(time.time())
# real-shaped Solana mints (32 bytes, base58) for the token checks
WBTC_M, COINX_M, BANK_M, MEME_M = ("4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi", "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
                                   "CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8", "GgBaCs3NCBuZN12kCJgAW63ydqohFkHEdfdEXBPzLHq")


class GroupCallers(unittest.TestCase):
    def test_groups_by_token_most_callers_first_and_first_caller_time(self):
        ev = [("TOK1", NOW - 600, "x", "ansem", "call"), ("TOK1", NOW - 300, "tg", "tg:alpha", "call"),
              ("TOK1", NOW - 100, "chain", "w:Abc123", "buy"), ("TOK1", NOW - 50, "x", "ansem", "call"),   # repeat: once
              ("TOK2", NOW - 10, "x", "murad", "call"), ("TOK3", NOW - 7200, "x", "old", "call"),             # too old
              ("TOK2", NOW - 5, "chain", "w:Abc123", "sell")]                                                 # sells don't count
        rows = pravitrade.group_callers(ev, NOW)
        self.assertEqual([r[0] for r in rows], ["TOK1", "TOK2"])
        tok, callers, first, last = rows[0]
        self.assertEqual([c[0] for c in callers], ["ansem", "tg:alpha", "w:Abc123"])
        self.assertEqual((first, last), (NOW - 600, NOW - 100))   # ansem's first call, not his repeat


class NotACall(unittest.TestCase):
    def test_majors_wrapped_and_xstocks_are_never_calls(self):
        from kol import converge
        self.assertIn("major", converge.not_a_memecoin("So11111111111111111111111111111111111111112"))
        self.assertIn("major", converge.not_a_memecoin("3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh", "WBTC"))
        self.assertIn("zamotana", converge.not_a_memecoin("SomeOtherWrapped", "cbBTC"))
        self.assertIn("xStock", converge.not_a_memecoin("Xc1", "COINx"))
        self.assertIn("xStock", converge.not_a_memecoin("Xc2", "TSLAx"))
        self.assertIn("likvidnost", converge.not_a_memecoin("Big1", "TRUMP", 9_000_000))
        self.assertIsNone(converge.not_a_memecoin("Meme1", "BANK", 35_000))
        self.assertIsNone(converge.not_a_memecoin("Meme2", "xdog", 35_000))   # lower-case ticker is not the pattern

    def test_gather_callers_filters_noise_and_counts_only_followed_wallets(self):
        from kol import store as kstore
        d = tempfile.mkdtemp()
        kp, hp, tp = os.path.join(d, "kol.db"), os.path.join(d, "hype.db"), os.path.join(d, "tg.db")
        kc = kstore.connect(kp)
        kc.executemany("INSERT INTO tokens (token, symbol, liquidity) VALUES (?,?,?)",
                       [(WBTC_M, "WBTC", 50e6), (COINX_M, "COINx", 3e6),
                        (BANK_M, "BANK", 35_000), (MEME_M, "MEME", 80_000)])
        kc.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')",
                       [("a", WBTC_M, "ansem", NOW - 300), ("b", BANK_M, "tg:alpha", NOW - 200),
                        ("c", MEME_M, "murad", NOW - 100)])
        kc.commit()
        kc.close()
        hc = sqlite3.connect(hp)
        hc.execute("CREATE TABLE chain_trades (wallet TEXT, mint TEXT, side TEXT, ts INTEGER)")
        hc.execute("CREATE TABLE kol_mentions (ts INTEGER, handle TEXT, ca TEXT)")
        hc.executemany("INSERT INTO chain_trades VALUES (?,?,?,?)",
                       [("FOLLOWEDWALLET", BANK_M, "buy", NOW - 150), ("RANDOMWALLET", COINX_M, "buy", NOW - 50),
                        ("RANDOMWALLET", MEME_M, "buy", NOW - 40), ("FOLLOWEDWALLET", MEME_M, "sell", NOW - 30)])
        hc.commit()
        hc.close()
        live = {t: {"price": 0.001, "liq": 40_000.0, "mcap": 90_000.0, "vol_h1": 3000.0, "vol_h24": 9000.0, "txns_h1": 30,
                    "buys_h1": 20, "txns_h24": 100, "ch_h1": 4.0, "ch_h24": 9.0, "txns_m5": 8, "vol_m5": 600.0}
                for t in (WBTC_M, COINX_M, BANK_M, MEME_M)}
        rows = pravitrade.gather_callers(NOW, kol_db=kp, tg_db=tp, hype_db=hp, followed={"FOLLOWEDWALLET"}, live=live)
        got = {r[4]: [c[0] for c in r[1]] for r in rows}
        self.assertEqual(set(got), {"BANK", "MEME"})                  # WBTC (wrapped) and COINx (xStock) are gone
        # 10.11. (Jure: "token s 0 volumena nema smisla da bude tu; u 5 minuta više od 5 transakcija"): a called token
        # nobody trades right now is not a line; it comes back when it wakes up
        quiet = {**live, MEME_M: {**live[MEME_M], "txns_m5": 0, "vol_m5": 0.0, "txns_h1": 1}}
        again = pravitrade.gather_callers(NOW, kol_db=kp, tg_db=tp, hype_db=hp, followed={"FOLLOWEDWALLET"}, live=quiet)
        self.assertEqual({r[4] for r in again}, {"BANK"})
        self.assertIn("samo 0 transakcija u zadnjih 5 min (treba 5+)", pravitrade.asleep(quiet[MEME_M]))
        self.assertIsNone(pravitrade.asleep(live[MEME_M]))
        self.assertEqual(got["BANK"], ["tg:alpha", "w:FOLLOWEDWALLET"])   # the followed wallet's buy counts
        self.assertEqual(got["MEME"], ["murad"])                      # a random webhook wallet's buy does not
        self.assertEqual(rows[0][4], "BANK")                          # most callers first
        self.assertEqual(rows[0][5]["mcap"], 90_000.0)                # the live state travels to the row
        # 9.11. 15:37 (Jure, robinhood_trending): no live pair, under 30k, archived, or not a Solana mint -> no row
        nopair = dict(live)
        del nopair[BANK_M]
        self.assertEqual([r[4] for r in pravitrade.gather_callers(NOW, kol_db=kp, tg_db=tp, hype_db=hp, followed=set(), live=nopair)], ["MEME"])
        small = {**live, MEME_M: {**live[MEME_M], "mcap": 12_000.0}}
        self.assertEqual([r[4] for r in pravitrade.gather_callers(NOW, kol_db=kp, tg_db=tp, hype_db=hp, followed=set(), live=small)], ["BANK"])
        self.assertEqual(pravitrade.gather_callers(NOW, kol_db=kp, tg_db=tp, hype_db=hp, followed=set(), live=None if False else {}), [])
        saved = pravitrade._live_cached
        pravitrade._live_cached = lambda toks, now, ttl=10: None     # DexScreener down: nothing is shown
        try:
            self.assertEqual(pravitrade.gather_callers(NOW, kol_db=kp, tg_db=tp, hype_db=hp, followed=set()), [])
        finally:
            pravitrade._live_cached = saved

    def test_evm_tails_are_not_tokens(self):
        from kol import collect
        self.assertTrue(collect.is_solana_mint("So11111111111111111111111111111111111111112"))
        self.assertTrue(collect.is_solana_mint("ANLEpx1hMMGJ2vHwENrVhH1gkysDNwf5p4uNKJxGpump"))
        self.assertFalse(collect.is_solana_mint("x47c8f3a2b1c9d4e5f6a7b8c9d0e1f2a3b4c5d6a396"))   # tail of 0x47c…a396
        self.assertFalse(collect.is_solana_mint("8699c4a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d64cd7"))
        self.assertFalse(collect.is_solana_mint("BANKTOKEN" + "1" * 32))                         # not a real key
        self.assertEqual(collect.cas_in("buy 0x47c8f3a2b1c9d4e5f6a7b8c9d0e1f2a3b4c5d6a396 now"), [])
        self.assertEqual(collect.cas_in("CA: ANLEpx1hMMGJ2vHwENrVhH1gkysDNwf5p4uNKJxGpump"), ["ANLEpx1hMMGJ2vHwENrVhH1gkysDNwf5p4uNKJxGpump"])
        from tg import reader
        page = ('<div class="tgme_widget_message_wrap"><div data-post="c/1"></div><div class="tgme_widget_message_text">'
                'ape 0x47c8f3a2b1c9d4e5f6a7b8c9d0e1f2a3b4c5d6a396 and ANLEpx1hMMGJ2vHwENrVhH1gkysDNwf5p4uNKJxGpump</div>'
                '<time datetime="2026-11-09T10:32:01+00:00"></time></div>')
        posts = reader.parse(page, "c")["posts"]
        self.assertEqual(posts[0]["cas"], ["ANLEpx1hMMGJ2vHwENrVhH1gkysDNwf5p4uNKJxGpump"])


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fake = FakeJup()
        self._saved = (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)
        os.environ["TRADE_OWNER"] = "Jure"
        # 10.11.: a pop-up starts the refresher thread itself now (the live lists are closed sections); never a real
        # one in the test process
        self._bg = pravitrade.BG_REFRESH
        pravitrade.BG_REFRESH = False

    def tearDown(self):
        pravitrade.BG_REFRESH = self._bg
        (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB) = self._saved
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()
        os.environ.pop("TRADE_OWNER", None)

    def test_tp_target_owner_only_and_prefills_buy_forms(self):
        self.assertEqual(settings.merged(CFG, self.con)["tp_default"], 15)
        self.assertIn("err=", pravitrade.post("/pravi-trade/tp", {"tp": "10"}, "Ivan"))
        self.assertIn("err=", pravitrade.post("/pravi-trade/tp", {"tp": "12"}, "Jure"))   # not one of the choices
        loc = pravitrade.post("/pravi-trade/tp", {"tp": "10"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(settings.merged(CFG, self.con)["tp_default"], 10)
        # 11.11. (ui/apterm): "Pravila" is under "Postavke", the callers' feed in "Koga pratimo" (which exists only
        # while somebody is followed) and the tool's live picks (EV not measured: one closed row) in "Što kupiti",
        # each loaded when it comes into view (sve=1: all in the page)
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")
        self.lg.commit()
        _, body = pravitrade.page({"sve": "1"}, "Jure")
        self.assertIn("Cilj izlaza za nove kopije", body)
        self.assertIn("sada +10 %", body)
        self.assertIn("Tko sada zove koji token", body)
        self.assertIn("pratiš i dokazani walleti", body)
        self.assertIn("Nema prijedloga s EV &gt; 0", body)
        self.assertIn('value="10%"', body)   # the order panel's TP starts from the target (the last TP used, else it)
        self.assertIn('value=10%', pravitrade._buy_form("TOK", settings.merged(CFG, self.con), "tpsl", True))   # TP/SL forms take it
        self.assertNotIn('value=10%', pravitrade._buy_form("TOK", settings.merged(CFG, self.con), "smart", True))
        self.assertIn("data-x-src=/pravi-trade/zovu data-x-every=15", body)   # the feed, every 15 s while on screen
        # 11.11. (ui/apterm): positions and the log (tabs), the order panel, "Što kupiti", "Koga pratimo" with its
        # feed, then "Postavke i dijagnostika" with Pravila (exit target + limits) and the recommendations
        order = [body.index(x) for x in ("id=pozicije", "id=dnevnik", "id=kupi-odmah", "id=kupiti", "id=pratimo", "id=ap-zovu",
                                         "id=apx-ostalo", "id=cilj", "id=limiti", "id=pratim>", "id=preporuke")]
        self.assertEqual(order, sorted(order))
        for sid in ("preporuke", "pravila"):   # closed until tapped
            self.assertIn(f"<details class=ap-sec id={sid}><summary>", body)

    def test_follow_all_callers_makes_one_crew_follow(self):
        pravitrade.post("/pravi-trade/tp", {"tp": "20"}, "Jure")
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "100%", "")
        self.lg.commit()
        self.assertIn("err=", pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha"}, "Ivan"))
        loc = pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha,@murad"}, "Jure")
        self.assertIn("ok=", loc)
        fl = {f["target"]: f for f in copy.follows(self.lg, settings.LEAGUE_USER)}
        self.assertEqual(sorted(fl), ["ansem", "ansem,murad,tg:alpha"])
        self.assertEqual(fl["ansem"]["exit"]["tp"], "100%")   # the existing single follow keeps its own exit
        crew = fl["ansem,murad,tg:alpha"]
        self.assertEqual(crew["kind"], "ekipa")
        # 9.11. (audit P10/P19): no position without a stop; 10.11.: "" = the owner's default stop at each entry
        self.assertEqual(crew["exit"], {"mode": "tpsl", "tp": "20%", "sl": "", "max_mcap": 1e6, "max_runup": 0.25, "min_callers": 1})
        self.assertIn("SL -60% zadani", copy.describe_exit(crew["exit"], copy.default_sl(settings.LEAGUE_USER)))
        self.assertIn("ve%C4%87%20prati", pravitrade.post("/pravi-trade/followall", {"handles": "murad, ansem, tg:alpha"}, "Jure"))

    def test_live_log_hides_stale_trial_orders(self):
        """9.11. (Jure): the log said "osvježeno sada" above skipped trial orders from 5.8 days ago."""
        old = NOW - 6 * 86400
        for i, tok in enumerate(("EYED", "GTAVI", "DAVID")):
            self.con.execute("INSERT INTO orders (ts, token, side, mode, amount_in, status, reason) VALUES (?,?,?,?,?,?,?)",
                             (old + i, tok, "buy", "dry", 50_000_000, "blocked", "dnevni limit: potrošeno 0.500 od 0.5 SOL"))
        self.con.commit()
        html = pravitrade.log_fragment("Jure")
        self.assertIn("Danas nema naloga", html)
        self.assertIn("Starije od 24 h: 3 naloga (3 preskočeno)", html)
        self.assertNotIn("EYED", html)                      # not listed as if it were live
        self.assertIn("probno = bez pravog novca", html)
        self.con.execute("INSERT INTO orders (ts, token, side, mode, amount_in, status) VALUES (?,?,?,?,?,?)",
                         (NOW - 2 * 86400, "REAL", "buy", "live", 50_000_000, "ok"))
        self.con.execute("INSERT INTO orders (ts, token, side, mode, amount_in, status) VALUES (?,?,?,?,?,?)",
                         (NOW - 60, "FRESH", "buy", "dry", 50_000_000, "dry"))
        self.con.commit()
        html = pravitrade.log_fragment("Jure")
        self.assertNotIn("Danas nema naloga", html)
        self.assertIn("FRESH", html)
        self.assertIn("REAL", html)                         # a real order stays visible for a week
        self.assertNotIn("GTAVI", html)

    def test_ideas_are_live_rows_and_never_build_token_rows(self):
        """9.11. 12:30: building the picks in the UI process ran the server out of memory; 15:40 (Jure): the box must be
        live (2 s), not "the same as Pregled every 60 s"."""
        from ui import overview, zivo
        saved = (overview.token_rows, zivo.rows)

        def boom(*a, **k):
            raise AssertionError("token_rows must not run in the UI process")
        overview.token_rows = boom
        row = {"token": "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi", "symbol": "AAA", "src": "zovu", "why": ["zovu: ansem"], "ts0": NOW - 300,
               "tier": 2, "live": {"price": 0.001, "liq": 50_000.0, "mcap": 120_000.0, "vol_h1": 8000.0, "txns_h1": 60, "vol_m5": 900.0,
                                   "txns_m5": 7, "ch_m5": 12.0, "ch_h1": 5.0}, "callers10": ["ansem"], "smart10": 1,
               "expect": "pozivatelji: +15 % prije stopa u 50% (6 izmjerenih poziva, minutna provjera)", "expect_v": 0.5,
               "age_s": 300, "heat": 9.0, "reasons": ["novi pozivatelj u 10 min: @ansem", "1 pametnih novčanika kupilo u 10 min"]}
        zivo.rows = lambda now=None, **k: [row]
        pravitrade._IDEAS_CACHE.clear()
        try:
            html = pravitrade.ideas_inner(settings.merged(CFG, self.con), True, NOW)
            self.assertIn("AAA", html)
            self.assertIn("5 min +12 %", html)
            self.assertIn("novi pozivatelj u 10 min: @ansem", html)                 # the first fresh reason, inline
            self.assertIn('data-pop="/pravi-trade/token?m=4vJ9JU1b', html)         # the rest lives in the pop-up
            self.assertNotIn("<form", html)                                          # compact rows, no inline forms
            self.assertIs(pravitrade.ideas_inner(settings.merged(CFG, self.con), True, NOW + 0.5), html)   # 1-s cache
            zivo.rows = lambda now=None, **k: []
            pravitrade._IDEAS_CACHE.clear()
            # 9.11. (audit P33 review): an empty list counts as "nothing to buy" only once the zivo thread has made its
            # first pass (zivo._ROWS ts > 0); before that the fragment says 'učitavam…' and caches nothing
            ts0 = zivo._ROWS["ts"]
            zivo._ROWS["ts"] = float(NOW + 5)
            self.assertEqual(pravitrade.ideas_inner(settings.merged(CFG, self.con), True, NOW + 5), "")
        finally:
            overview.token_rows, zivo.rows = saved
            zivo._ROWS["ts"] = ts0
            pravitrade._IDEAS_CACHE.clear()
        # 11.11. (Jure: "Što kupiti" = jedna lista): the live picks are rows of "Što kupiti", fetched with it when it
        # scrolls into view (every 30 s while on screen), never in the first HTML
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("data-x-src=/pravi-trade/l/kupiti data-x-every=30", body)
        self.assertNotIn("alat (živo)", body)
        from ui import apterm
        live = {"price": 0.001, "liq": 40_000.0, "mcap": 90_000.0, "ch_m5": 3.0, "ch_h1": 4.0, "symbol": "ZIVI"}
        with mock.patch.object(zivo, "rows", lambda now=None, **k: [{"token": "ZivToken1", "live": live, "src": "poziv",
                                                                      "reasons": ["novi poziv"], "checked": NOW}]), \
                mock.patch.object(overview, "token_rows", side_effect=AssertionError("token rows built")):
            frag = apterm.lazy("kupiti", "Jure")
        self.assertIn("alat (živo) · poziv · novi poziv", frag)
        # 11.11. (noc/sltp): the green "Kupi" of a proposal (fills token, SOL, TP, SL, trailing; never buys)
        self.assertIn('class="apx-b buy" data-pk="', frag)
        self.assertIn('data-pop="/pravi-trade/token?m=ZivToken1"', frag)

    def test_crew_rows_and_popups(self):
        m = {"price": 0.001, "liq": 40_000.0, "mcap": 90_000.0, "vol_h1": 3000.0, "vol_h24": 9000.0, "txns_h1": 30, "buys_h1": 20,
             "txns_h24": 100, "vol_m5": 400.0, "txns_m5": 4, "ch_m5": 3.0, "ch_h1": 4.0, "ch_h24": 9.0, "symbol": "AAA"}
        rows = [(WBTC_M, [("tg:robinhood_trending", "tg", NOW - 600)], NOW - 600, NOW - 600, "A1", m),
                (COINX_M, [("tg:robinhood_trending", "tg", NOW - 100)], NOW - 100, NOW - 100, "A2", m),
                (BANK_M, [("ansem", "x", NOW - 300), ("tg:alpha", "tg", NOW - 200)], NOW - 300, NOW - 200, "BANK", m)]
        crews = pravitrade.crew_rows(rows, NOW)
        self.assertEqual([c["name"] for c in crews], ["robinhood_trending", "ekipa @ansem +1"])   # one line per crew
        self.assertEqual(len(crews[0]["tokens"]), 2)
        self.assertEqual(crews[0]["tokens"][0]["symbol"], "A2")                                 # newest first
        html = pravitrade._crew_row(crews[0], NOW)
        self.assertIn("2 tokena u 60 min", html)
        self.assertIn('data-pop="/pravi-trade/ekipa?h=tg%3Arobinhood_trending"', html)
        # token pop-up: a rugged / falling token says NE KUPUJ and hides the buy form; a healthy one offers the buy
        saved = (pravitrade._live_cached,)
        dead = {**m, "mcap": 14_000.0, "ch_h1": -89.0, "txns_h1": 2, "vol_h1": 50.0}
        pravitrade._live_cached = lambda toks, now, ttl=1: {toks[0]: dead}
        try:
            html = pravitrade.token_popup("Jure", BANK_M, NOW)
            self.assertIn("NE KUPUJ", html)
            self.assertIn("ispod 30k", html)
            self.assertNotIn("<form method=post action=/pravi-trade/buy", html)
            pravitrade._live_cached = lambda toks, now, ttl=1: {toks[0]: {**m, "ch_m5": 7.0, "vol_m5": 2500.0, "txns_m5": 9}}
            html = pravitrade.token_popup("Jure", BANK_M, NOW)
            self.assertIn("U REDU ZA ULAZ", html)
            self.assertIn("+7 % u 5 min", html)
            self.assertIn("/pravi-trade/buy", html)
            self.assertIsNone(pravitrade.token_popup("Ivan", BANK_M, NOW))
            self.assertIn("nije Solana adresa", pravitrade.token_popup("Jure", "x47c8f3a2b1c9d4e5f6a7b8c9d0e1f2a3b4c5d6a396", NOW))
            pravitrade._live_cached = lambda toks, now, ttl=1: None
            self.assertIn("ne nudim ulaz", pravitrade.token_popup("Jure", BANK_M, NOW))
            html = pravitrade.crew_popup("Jure", "tg:robinhood_trending,ansem", NOW)
            self.assertIn("Uspjeh (minutna provjera)", html)
            self.assertIn("Zaprati kao ekipu (2)", html)
        finally:
            (pravitrade._live_cached,) = saved

    def test_manual_buy_refuses_a_token_that_fails_the_live_gate(self):
        from ui import prijedlog
        from ui import league as uil
        saved = (prijedlog.live_market, uil.market)
        uil.market = lambda toks: {t: (0.001, 30_000.0, None, 14_000.0) for t in toks}
        prijedlog.live_market = lambda toks, fetch=None: {t: {"price": 0.001, "liq": 30_000.0, "mcap": 14_000.0, "vol_h1": 50.0,
                                                               "vol_h24": 2000.0, "txns_h1": 2, "buys_h1": 0, "txns_h24": 20,
                                                               "vol_m5": 0.0, "txns_m5": 0, "ch_m5": -40.0, "ch_h1": -89.0, "ch_h24": -90.0} for t in toks}
        try:
            loc = pravitrade.post("/pravi-trade/buy", {"token": BANK_M, "sol": "0.1", "exit": "tpsl", "tp": "15%"}, "Jure")
        finally:
            prijedlog.live_market, uil.market = saved
        # 11.11. (owner: "Mogu se kupovati tokeni ispod 30.000 market capa uz dovoljno dobar razlog"): the owner's own
        # buy under 30k is a warning asking for his reason (tests/test_nadjacaj_offline), nothing bought before it
        self.assertIn("warn=", loc)
        self.assertTrue(pravitrade.fetch_answer(loc)["need_reason"])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)
        # 9.11. (audit P64): a token that trades fine but sits under $30k reaches the MC gate itself (the case above
        # is refused earlier, by the traffic check, so it never exercised the 30k line)
        healthy_small = {"price": 0.001, "liq": 30_000.0, "mcap": 20_000.0, "vol_h1": 20_000.0, "vol_h24": 1e5, "txns_h1": 80,
                         "buys_h1": 50, "txns_h24": 900, "vol_m5": 900.0, "txns_m5": 6, "ch_m5": 1.0, "ch_h1": 3.0, "ch_h24": 10.0}
        uil.market = lambda toks: {t: (0.001, 30_000.0, None, 20_000.0) for t in toks}
        prijedlog.live_market = lambda toks, fetch=None: {t: dict(healthy_small) for t in toks}
        try:
            loc = pravitrade.post("/pravi-trade/buy", {"token": BANK_M, "sol": "0.1", "exit": "tpsl", "tp": "15%"}, "Jure")
        finally:
            prijedlog.live_market, uil.market = saved
        self.assertIn("warn=", loc)
        self.assertIn("ispod 30k", pravitrade.fetch_answer(loc)["warn"][0])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_fragments_need_access(self):
        saved = pravitrade.BG_REFRESH
        pravitrade.BG_REFRESH = False   # no refresher thread in the test process: the synchronous path
        try:
            self.assertIsNone(pravitrade.callers_fragment("Ivan"))
            self.assertIsNone(pravitrade.ideas_fragment("Ivan"))
            self.assertIsInstance(pravitrade.callers_fragment("Jure"), str)
            self.assertIsInstance(pravitrade.ideas_fragment("Jure"), str)
        finally:
            pravitrade.BG_REFRESH = saved


class TelegramPolling(unittest.TestCase):
    def test_followed_channel_every_two_seconds_others_unchanged(self):
        from tg import poll
        cfg = json.load(open(os.path.join(ROOT, "tg", "config.json")))
        self.assertEqual(poll.interval(("alpha", "active", 0), cfg, {}, NOW, followed={"alpha"}), cfg["poll_followed_s"])
        self.assertEqual(cfg["poll_followed_s"], 2)
        cold = poll.interval(("cold", "active", 0), cfg, {}, NOW)
        self.assertGreaterEqual(cold, cfg["poll_hot_s"])   # a channel nobody follows keeps its slow schedule
        self.assertEqual(poll.interval(("hot", "active", NOW - 60), cfg, {}, NOW), cfg["poll_hot_s"])

    def test_due_reads_followed_channel_and_paces_validation(self):
        from tg import poll, store as tstore
        d = tempfile.mkdtemp()
        con = tstore.connect(os.path.join(d, "tg.db"))
        for name, st, lp, ca in (("alpha", "active", NOW - 3, 0), ("cold", "active", NOW - 3, 0), ("cand", "candidate", 0, 0)):
            con.execute("INSERT INTO channels (name, status, last_poll, last_ca_ts, found_via, found_ts) VALUES (?,?,?,?,?,?)",
                        (name, st, lp, ca, "channels.txt", NOW))
        con.commit()
        cfg = json.load(open(os.path.join(ROOT, "tg", "config.json")))
        saved = poll.followed_channels
        poll.followed_channels = lambda: {"alpha"}
        poll._PACE["validate_ts"] = 0
        try:
            validate, due = poll.due(con, cfg, {}, NOW)
            self.assertEqual(due, ["alpha"])
            self.assertEqual(validate, ["cand"])
            validate2, _ = poll.due(con, cfg, {}, NOW + 1)   # 1 s later: validation waits, polling does not
            self.assertEqual(validate2, [])
        finally:
            poll.followed_channels = saved
            poll._PACE["validate_ts"] = 0
            con.close()

    def test_no_league_db_means_nobody_followed(self):
        from league import store as lstore
        from tg import poll
        saved = lstore.DB
        lstore.DB = os.path.join(tempfile.mkdtemp(), "nema.db")
        try:
            self.assertEqual(poll.followed_channels(), set())
        finally:
            lstore.DB = saved


class Indexes(unittest.TestCase):
    def test_calls_have_a_time_index(self):
        from kol import store as kstore
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        names = {r[1] for r in con.execute("PRAGMA index_list(calls)")}
        self.assertIn("calls_ts", names)
        con.close()


if __name__ == "__main__":
    unittest.main()
