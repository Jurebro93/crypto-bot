"""Audit 9.11., group 'pravitrade' (ui/pravitrade.py): the manual buy ("Kupi") on the real-trade page.
N4  the exit rule and the stake are validated BEFORE the demo trade is written (no position without an exit rule,
    no error page with the buy already done behind it);
N10 a stake above max_sol_per_trade is refused on the page, not silently blocked later by gate_buy;
    a TP/SL buy without an explicit stop gets the default stop (league/copy.DEFAULT_SL), like copies do.
Wave 2 (findings P10/P17/P19, P39, P41, P45, P47, P48/P75, P49, P55, P72, P73, P74, P76, P77): the follow forms store
the default stop, the pop-up verdict needs a fresh reason, says when the rug check was not done and who holds the
supply ("nepoznato" when unknown), vetoes weak callers (minute check), and the 1-s fragments read caches a background
thread fills (DexScreener live TTL LIVE_TTL_S, never a fetch in the request thread while the thread runs).

    python3 -m unittest tests.test_audit_20261109_pravitrade_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from trade import executor, settings  # noqa: E402

MINT = "So11111111111111111111111111111111111111112"[:-1] + "3"
LIVE_ROW = {"price": 1.0, "liq": 1e6, "mcap": 5e5, "vol_h1": 20_000.0, "vol_h24": 1e5, "txns_h1": 80, "buys_h1": 50,
            "txns_h24": 900, "vol_m5": 900.0, "txns_m5": 6, "ch_m5": 1.0, "ch_h1": 3.0, "ch_h24": 10.0}


class ManualBuy(unittest.TestCase):
    def setUp(self):
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB,
                       uleague.market, collapse.check, uleague._symbol, prijedlog.live_market, os.environ.get("TRADE_OWNER"))
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        os.environ["TRADE_OWNER"] = "Jure"
        uleague.market = lambda toks: {t: (1.0, 1e6, None, 5e5) for t in toks}
        collapse.check = lambda *a, **k: None
        uleague._symbol = lambda t: "MAN"
        prijedlog.live_market = lambda toks, fetch=None: {t: dict(LIVE_ROW) for t in toks}

    def tearDown(self):
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB,
         uleague.market, collapse.check, uleague._symbol, prijedlog.live_market, owner) = self._saved
        if owner is None:
            os.environ.pop("TRADE_OWNER", None)
        else:
            os.environ["TRADE_OWNER"] = owner
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def _buy(self, **form):
        from ui import pravitrade
        base = {"token": MINT, "sol": "0,02", "exit": "tpsl", "tp": "100%", "sl": "-30%"}
        base.update(form)
        return pravitrade.post("/pravi-trade/buy", base, "Jure")

    def _open(self):
        return store.trades(self.lg, settings.LEAGUE_USER, "open")

    def test_bad_exit_rule_is_refused_before_anything_is_written(self):
        loc = self._buy(tp="abc")
        self.assertIn("err=", loc)
        self.assertEqual(self._open(), [])                       # no demo trade, so nothing for run_trade to mirror
        loc = self._buy(tp="$100k")                              # an MC target below the entry MC ($500k)
        self.assertIn("err=", loc)
        self.assertEqual(self._open(), [])
        loc = self._buy(exit="bilo-što")
        self.assertIn("err=", loc)
        self.assertEqual(self._open(), [])

    def test_stake_above_the_per_trade_limit_is_refused_on_the_page(self):
        lim = settings.merged(executor.load_config(), self.con)["max_sol_per_trade"]
        loc = self._buy(sol=str(lim * 3).replace(".", ","))
        self.assertIn("err=", loc)
        self.assertIn("iznad%20limita", loc)
        self.assertEqual(self._open(), [])
        self.assertEqual(settings.raw(self.con).get("manual_size"), None)   # no orphan stake record either

    def test_tpsl_without_a_stop_gets_the_default_stop(self):
        loc = self._buy(sl="")
        self.assertIn("ok=", loc)
        (t,) = self._open()
        a = json.loads(t["auto"])
        self.assertEqual(a["mode"], "tpsl")
        self.assertEqual(a["sl"], copy.DEFAULT_SL)                # "-20%", the same stop copies get
        self.assertAlmostEqual(a["sl_px"], 0.8)
        self.assertAlmostEqual(a["tp_px"], 2.0)

    def test_good_buy_still_goes_through_with_its_stake(self):
        loc = self._buy()
        self.assertIn("ok=", loc)
        (t,) = self._open()
        self.assertEqual(json.loads(t["auto"])["mode"], "tpsl")
        self.assertEqual(settings.raw(self.con)["manual_size"][str(t["id"])], 0.02)


MINT2 = "GgBaCs3NCBuZN12kCJgAW63ydqohFkHEdfdEXBPzLHq"
HEALTHY = {"price": 0.001, "liq": 40_000.0, "mcap": 90_000.0, "vol_h1": 3000.0, "vol_h24": 9000.0, "txns_h1": 30, "buys_h1": 20,
           "txns_h24": 100, "vol_m5": 400.0, "txns_m5": 6, "ch_m5": 3.0, "ch_h1": 4.0, "ch_h24": 9.0, "symbol": "AAA"}
MOVING = {**HEALTHY, "ch_m5": 7.0, "vol_m5": 2500.0, "txns_m5": 9}
NOW = int(time.time())


class PageBase(unittest.TestCase):
    """Temp trade.db / league.db, owner Jure, every live source of the pop-up patched (offline)."""

    def setUp(self):
        from kol import converge
        from rugfilter import archive
        from topcheck import holders, store as tstore
        from ui import pravitrade, zivo
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, os.environ.get("TRADE_OWNER"),
                       pravitrade._live_cached, converge.events, zivo._smart_buys, zivo._minute_stats, zivo._tiers, zivo._chances,
                       tstore.read_all, archive.blocked, holders.pumpfun_shape, pravitrade.BG_REFRESH, dict(pravitrade._BG))
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        os.environ["TRADE_OWNER"] = "Jure"
        self.live = {MINT2: dict(MOVING)}
        self.events = []
        self.mstats = {}
        self.top = {}
        self.shape = {}
        pravitrade._live_cached = lambda toks, now, ttl=1, wait=None: {t: self.live[t] for t in toks if t in self.live}
        converge.events = lambda now, window_s, **k: (list(self.events), {}, {})
        zivo._smart_buys = lambda now, toks: {}
        zivo._minute_stats = lambda now: dict(self.mstats)
        zivo._tiers = lambda: {}
        zivo._chances = lambda: {}
        tstore.read_all = lambda path=None, max_age_h=24: dict(self.top)
        archive.blocked = lambda path=None, ttl=300: frozenset()
        holders.pumpfun_shape = lambda mints, tc=None, rug=None, **k: {m: self.shape[m] for m in mints if m in self.shape}
        pravitrade.BG_REFRESH = False
        pravitrade._SUPPLY_CACHE.clear()
        pravitrade._LIVE_CACHE.clear()
        pravitrade._LIVE_WANT.clear()

    def tearDown(self):
        from kol import converge
        from rugfilter import archive
        from topcheck import holders, store as tstore
        from ui import pravitrade, zivo
        (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, owner, pravitrade._live_cached, converge.events, zivo._smart_buys,
         zivo._minute_stats, zivo._tiers, zivo._chances, tstore.read_all, archive.blocked, holders.pumpfun_shape,
         pravitrade.BG_REFRESH, bg) = self._saved
        pravitrade._BG.update(bg)
        if owner is None:
            os.environ.pop("TRADE_OWNER", None)
        else:
            os.environ["TRADE_OWNER"] = owner
        pravitrade._SUPPLY_CACHE.clear()
        pravitrade._LIVE_CACHE.clear()
        pravitrade._LIVE_WANT.clear()
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def popup(self):
        from ui import pravitrade
        return pravitrade.token_popup("Jure", MINT2, NOW)


class PopupVerdict(PageBase):
    def test_static_reasons_alone_do_not_make_a_buy(self):
        """P45: an hourly buyer share, a rug check and a tier are not fresh; the live list would drop the token, so
        the pop-up must not say U REDU ZA ULAZ on them alone."""
        self.live[MINT2] = dict(HEALTHY)                       # +3 % on $400: no move, no caller, no smart buy
        self.top = {MINT2: {"verdict": "prolazi", "ts": NOW - 60, "rc_ts": NOW - 900, "safety": {"checks": {"holderi": ["ok", "top 10 holdera drži 12%"]}, "warns": [], "fails": []}, "rc": {"top10": 12.0}}}
        html = self.popup()
        self.assertIn("NE KUPUJ", html)
        self.assertIn("nema svježeg razloga", html)
        self.assertIn("kupci prevladavaju", html)              # still described, in the static part
        self.assertNotIn("<form method=post action=/pravi-trade/buy", html)
        self.live[MINT2] = dict(MOVING)                        # +7 % in 5 min on $2,500 with 9 prints: fresh
        html = self.popup()
        self.assertIn("U REDU ZA ULAZ", html)
        self.assertIn("/pravi-trade/buy", html)

    def test_move_needs_prints_like_the_live_list(self):
        self.live[MINT2] = {**MOVING, "txns_m5": 2}            # +7 % on 2 prints: zivo.fresh_reasons would not count it
        self.assertIn("nema svježeg razloga", self.popup())

    def test_no_rug_check_is_said_and_supply_is_unknown_not_ok(self):
        """P49/P77: a token outside the top 20 has no topcheck row; the verdict says so instead of looking like a
        safety confirmation, the supply line says 'nepoznato', the buy form stays (no data is never a block)."""
        html = self.popup()
        self.assertIn("U REDU ZA ULAZ · rug check nije rađen, tko drži supply nepoznato", html)
        self.assertIn("rug check alata: nije rađen", html)
        self.assertIn("tko drži supply: nepoznato", html)
        self.assertNotIn("prolazi", html)
        self.assertIn("/pravi-trade/buy", html)

    def test_holders_unknown_is_oprez_without_blocking_but_other_warns_block(self):
        """P29/P36 handoff: 'oprez' now also means holders unknown -> shown as nepoznato, not NE KUPUJ without a
        reason; a real warn (top10 high, dev) is a reason against, with its text."""
        self.top = {MINT2: {"verdict": "oprez", "ts": NOW - 60, "rc_ts": NOW - 1800,
                            "safety": {"checks": {"holderi": ["warn", "nema podatka o holderima: koncentracija nepoznata"]},
                                       "warns": ["nema podatka o holderima: koncentracija nepoznata"], "fails": []}, "rc": {"top10": None}}}
        html = self.popup()
        self.assertIn("U REDU ZA ULAZ · holderi nepoznati", html)
        self.assertNotIn("NE KUPUJ", html)
        self.assertIn("tko drži supply: nepoznato", html)
        self.top[MINT2]["safety"] = {"checks": {"holderi": ["warn", "top 10 holdera drži 41%"]}, "warns": ["top 10 holdera drži 41%"], "fails": []}
        self.shape = {MINT2: {"top10HoldersPercent": 41.0, "bundlerOwnedPercent": None, "snipersOwnedPercent": 3.0,
                              "devHoldingsPercent": 2.0, "insidersPercent": None, "izvor": "RugCheck + rug filter"}}
        pravitrade_supply_cache_clear()   # the supply line is cached a minute per pop-up
        html = self.popup()
        self.assertIn("NE KUPUJ", html)
        self.assertIn("rug check alata: oprez (top 10 holdera drži 41%)", html)
        self.assertIn("top 10 41 % (bez poolova), insajderi nepoznato, dev 2 %, bundle nepoznato, snajperi 3 %", html)

    def test_rug_check_time_is_the_rugcheck_data_time(self):
        """P76: 'prošao prije 1 min' used to be the last run_top pass; the holder data may be 30 min old."""
        from ui.html import ago
        self.top = {MINT2: {"verdict": "prolazi", "ts": NOW - 60, "rc_ts": NOW - 1800, "safety": {"checks": {}, "warns": [], "fails": []}, "rc": {"top10": 9.0}}}
        self.shape = {MINT2: {"top10HoldersPercent": 9.0, "bundlerOwnedPercent": 1.0, "snipersOwnedPercent": 0.0,
                              "devHoldingsPercent": 0.0, "insidersPercent": 0.0, "izvor": "RugCheck"}}
        html = self.popup()
        self.assertIn(f"rug check alata prošao (RugCheck podatak {ago(NOW - 1800)[0]})", html)
        self.assertIn(f"RugCheck podatak {ago(NOW - 1800)[0]}", html)
        self.assertNotIn(ago(NOW - 60)[0] + ")", html.split("Holderi")[0].split("rug check")[-1])

    def test_thin_pool_against_mcap_is_a_reason_against(self):
        """P41: the pop-up and league/copy.run_once use the same liq/MC line (CFG min_liq_mcap)."""
        self.live[MINT2] = {**MOVING, "mcap": 2_000_000.0, "liq": 40_000.0}   # 2 % of MC
        html = self.popup()
        self.assertIn("NE KUPUJ", html)
        self.assertIn("samo 2.0% MC-a", html)
        self.assertIn(f"granica {copy.CFG['min_liq_mcap']:.0%}", html)
        self.assertIn("44% MC-a", pravitrade_popup_with(self, dict(MOVING)))   # the share is shown when healthy too

    def test_weak_callers_veto_the_verdict_and_the_manual_buy(self):
        """P47: the callers' own minute check (hit15 on 5+ calls) is the only measured outcome of copying them; when
        it is weak the pop-up says NE KUPUJ and the buy is refused; with no measurement nothing changes."""
        from ui import pravitrade
        self.events = [(MINT2, NOW - 120, "x", "weakguy", "call")]
        self.assertIn("U REDU ZA ULAZ", self.popup())                       # no measurement: no veto
        self.mstats = {"weakguy": {"hit10": 0.2, "hit15": 0.1, "sl": 0.8, "n": 12}}
        html = self.popup()
        self.assertIn("NE KUPUJ", html)
        self.assertIn("samo u 10% (12 izmjerenih poziva", html)
        self.assertIsNone(pravitrade._callers_veto(["weakguy"], {"weakguy": {"hit15": 0.1, "n": 3}}))    # too few calls
        self.assertIsNone(pravitrade._callers_veto(["weakguy"], {"weakguy": {"hit15": 0.5, "n": 30}}))   # good enough
        # the manual buy: same veto before anything is written
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        saved = (uleague.market, collapse.check, uleague._symbol, prijedlog.live_market)
        uleague.market = lambda toks: {t: (1.0, 1e6, None, 5e5) for t in toks}
        collapse.check = lambda *a, **k: None
        uleague._symbol = lambda t: "MAN"
        prijedlog.live_market = lambda toks, fetch=None: {t: dict(LIVE_ROW) for t in toks}
        try:
            loc = pravitrade.post("/pravi-trade/buy", {"token": MINT2, "sol": "0,02", "exit": "tpsl", "tp": "100%"}, "Jure")
            self.assertIn("err=", loc)
            self.assertIn("pozivatelji", loc)
            self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])
            self.mstats = {"weakguy": {"hit10": 0.6, "hit15": 0.5, "sl": 0.3, "n": 12}}
            loc = pravitrade.post("/pravi-trade/buy", {"token": MINT2, "sol": "0,02", "exit": "tpsl", "tp": "100%"}, "Jure")
            self.assertIn("ok=", loc)
        finally:
            uleague.market, collapse.check, uleague._symbol, prijedlog.live_market = saved

    def test_veto_is_pooled_over_calls_and_counts_an_account_once(self):
        """Review of P47: the veto used a plain mean of per-account rates and counted a handle once per call event;
        a noise account (n=3, 0 %) beside a strong one (n=50, 55 %) vetoed the buy while the pop-up's own
        'Očekivanje +15 %' said 52 %. Now: the zivo.expectation formula (pooled, weighted by n), one entry per account."""
        from ui import pravitrade
        self.events = [(MINT2, NOW - 120, "x", "noise", "call"), (MINT2, NOW - 600, "x", "strong", "call")]
        self.mstats = {"noise": {"hit10": 0.0, "hit15": 0.0, "sl": 1.0, "n": 3},
                       "strong": {"hit10": 0.7, "hit15": 0.55, "sl": 0.3, "n": 50}}
        html = self.popup()
        self.assertIn("U REDU ZA ULAZ", html)
        self.assertNotIn("samo u", html)
        self.assertIn("+15 % prije stopa u 52% (53 izmjerenih poziva", html)   # pooled: (0*3 + 0.55*50) / 53
        self.assertIsNone(pravitrade._callers_veto(["noise", "strong"], self.mstats))
        # the same account calling twice in the hour is one account: n stays 3, below WEAK_MIN_N, no veto
        self.events = [(MINT2, NOW - 120, "x", "noise", "call"), (MINT2, NOW - 1500, "x", "noise", "call")]
        html = self.popup()
        self.assertIn("U REDU ZA ULAZ", html)
        self.assertIn("(3 izmjerenih poziva", html)
        self.assertIsNone(pravitrade._callers_veto(["noise", "noise"], self.mstats))
        self.assertIsNone(pravitrade._callers_veto(["noise", "noise"], {"noise": {"hit15": 0.0, "n": 3}}))
        # pooled and weak: (0*3 + 0.2*50) / 53 = 19 % on 53 calls -> veto, with the pooled number
        veto = pravitrade._callers_veto(["noise", "strong", "noise"], {"noise": {"hit15": 0.0, "n": 3}, "strong": {"hit15": 0.2, "n": 50}})
        self.assertIn("samo u 19% (53 izmjerenih poziva", veto)
        # the manual buy agrees with the pop-up (both go through the same deduplicated, pooled rule)
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        saved = (uleague.market, collapse.check, uleague._symbol, prijedlog.live_market)
        uleague.market = lambda toks: {t: (1.0, 1e6, None, 5e5) for t in toks}
        collapse.check = lambda *a, **k: None
        uleague._symbol = lambda t: "MAN"
        prijedlog.live_market = lambda toks, fetch=None: {t: dict(LIVE_ROW) for t in toks}
        try:
            self.events = [(MINT2, NOW - 120, "x", "noise", "call"), (MINT2, NOW - 600, "x", "strong", "call")]
            loc = pravitrade.post("/pravi-trade/buy", {"token": MINT2, "sol": "0,02", "exit": "tpsl", "tp": "100%"}, "Jure")
            self.assertIn("ok=", loc)
        finally:
            uleague.market, collapse.check, uleague._symbol, prijedlog.live_market = saved

    def test_rugcheck_not_answering_is_told_apart_from_no_check(self):
        """Review: a topcheck row with verdict 'nepoznato' means the token was on the list but RugCheck did not
        answer; the verdict says that (not 'nije rađen'), the supply line still comes from what rug.db knows."""
        self.top = {MINT2: {"verdict": "nepoznato", "ts": NOW - 60, "rc_ts": None, "safety": {"checks": {}, "warns": [], "fails": []}, "rc": {}}}
        self.shape = {MINT2: {"top10HoldersPercent": None, "bundlerOwnedPercent": 55.0, "snipersOwnedPercent": None,
                              "devHoldingsPercent": None, "insidersPercent": None, "izvor": "rug filter"}}
        pravitrade_supply_cache_clear()
        html = self.popup()
        self.assertIn("U REDU ZA ULAZ · RugCheck nije odgovorio, tko drži supply nepoznato", html)
        self.assertNotIn("nije rađen", html)
        self.assertIn("bundle 55 %", html)


def pravitrade_supply_cache_clear():
    from ui import pravitrade
    pravitrade._SUPPLY_CACHE.clear()


def pravitrade_popup_with(t, live):
    t.live[MINT2] = live
    return t.popup()


class NoDuplicatesAndLiveTokens(PageBase):
    """10.11. (Jure, Autopilot): "koga već pratim ne prikazuj u prijedlozima ili ga zazeleni", "token s 0 volumena
    nema smisla da bude tu", "brojke stavi u tablicu kao na DexScreeneru"."""

    def test_followed_set_is_read_on_any_connection_and_in_any_case(self):
        from ui import pravitrade
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "Trade_titan1", "", 25, 5, "tpsl", "15%", "-20%")
        copy.follow(self.lg, settings.LEAGUE_USER, "wallet", "W" * 44, "", 25, 5)
        copy.follow(self.lg, settings.LEAGUE_USER, "ekipa", "tg:alpha, murad", "", 25, 5, "tpsl", "15%", "-20%")
        self.lg.commit()
        want = {"Trade_titan1", "W" * 44, "murad,tg:alpha", "murad", "tg:alpha"}
        self.assertEqual(pravitrade.followed_targets(self.lg), want)
        ro = copy._ro(store.DB)   # the plain read-only connection "Zovu sada" uses: this raised and the set was empty
        try:
            self.assertEqual(pravitrade.followed_targets(ro), want)
        finally:
            ro.close()
        self.assertTrue(pravitrade._is_followed("trade_titan1", want))        # typed in another letter case
        self.assertTrue(pravitrade._is_followed("w:" + "W" * 44, want))        # a wallet as "Zovu sada" names it
        self.assertFalse(pravitrade._is_followed("somebody", want))

    def test_zovu_sada_drops_fully_followed_rows_and_marks_the_followed_in_a_row_that_stays(self):
        from ui import pravitrade
        copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")
        self.lg.commit()
        m = dict(MOVING)
        rows = [("TOK1" + "1" * 40, [("ansem", "x", NOW - 60)], NOW - 60, NOW - 60, "ONE", m),
                ("TOK2" + "2" * 40, [("ansem", "x", NOW - 50), ("murad", "x", NOW - 40)], NOW - 50, NOW - 40, "TWO", m)]
        saved = pravitrade.gather_callers
        pravitrade.gather_callers = lambda now, **k: list(rows)
        try:
            html = pravitrade.callers_inner(None, True, NOW, force=True)
        finally:
            pravitrade.gather_callers = saved
        self.assertNotIn("ONE", html)                       # only ansem called it, and the bot follows him already
        self.assertIn("TWO", html)                          # murad is not followed: the row stays
        self.assertIn("već pratiš ✓ @ansem", html)          # ... with the followed one in green
        self.assertIn("5 min +7 % · 9 tx", html)            # and how awake the token is (transactions in 5 min)
        self.assertIn("ap-mine", html)

    def test_a_typed_handle_takes_the_spelling_the_database_has(self):
        import sqlite3
        from ui import pravitrade
        kp = os.path.join(self.tmp.name, "kol.db")
        k = sqlite3.connect(kp)
        k.execute("CREATE TABLE kols (handle TEXT)")
        k.executemany("INSERT INTO kols VALUES (?)", [("ansem",), ("tg:AlphaCalls",)])
        k.commit()
        k.close()
        self.assertEqual(pravitrade._canonical("Ansem", kp), "ansem")
        self.assertEqual(pravitrade._canonical("tg:alphacalls", kp), "tg:AlphaCalls")
        self.assertEqual(pravitrade._canonical("NewGuy", kp), "NewGuy")            # unknown: as typed
        self.assertEqual(pravitrade._canonical("W" * 44, kp), "W" * 44)            # an address is never touched

    def test_recommended_tokens_are_checked_live_and_the_sleeping_ones_are_left_out(self):
        from ui import autopilot, pravitrade
        awake, dead = "AWAKE" + "1" * 39, "DEAD" + "2" * 40
        saved = (autopilot.token_recs, pravitrade._live_cached)
        autopilot.token_recs = lambda now=None: {"dugo": [{"mint": dead, "symbol": "DEAD", "why": "preživio"},
                                                          {"mint": awake, "symbol": "AWAKE", "why": "preživio"}], "moon": []}
        state = {awake: dict(MOVING), dead: {**HEALTHY, "txns_m5": 0, "vol_m5": 0.0, "txns_h1": 1, "vol_h1": 3.0}}
        pravitrade._live_cached = lambda toks, now, ttl=1, wait=None: {t: state[t] for t in toks}
        try:
            html = pravitrade._token_section({}, True)
            self.assertIn("AWAKE", html)
            self.assertNotIn("DEAD", html)                                          # 0 tx in 5 min: not recommended
            self.assertIn("5 min 9 tx", html)
            pravitrade._live_cached = lambda toks, now, ttl=1, wait=None: None      # no live answer: nothing offered
            self.assertEqual(pravitrade._token_section({}, True), "")
        finally:
            autopilot.token_recs, pravitrade._live_cached = saved

    def test_popup_shows_the_market_as_a_table_and_says_why_a_quiet_token_is_not_offered(self):
        w = {"m5": {"ch": None, "vol": 0.0, "buys": 0, "sells": 0}, "h1": {"ch": -0.2, "vol": 3.0, "buys": 0, "sells": 1},
             "h6": {"ch": 1.5, "vol": 800.0, "buys": 4, "sells": 6}, "h24": {"ch": 9.0, "vol": 5200.0, "buys": 40, "sells": 31}}
        dead = {**HEALTHY, "mcap": 166_000.0, "liq": 86_000.0, "txns_m5": 0, "vol_m5": 0.0, "txns_h1": 1, "buys_h1": 0,
                "vol_h1": 3.0, "ch_m5": None, "w": w}
        html = pravitrade_popup_with(self, dead)
        self.assertIn("NE KUPUJ", html)
        self.assertIn("<table class=ap-mk>", html)
        for head in ("<th>5 min</th>", "<th>1 h</th>", "<th>6 h</th>", "<th>24 h</th>", "MARKET CAP", "LIKVIDNOST"):
            self.assertIn(head, html)
        self.assertIn("<b>$166.0k</b>", html)
        self.assertIn("<small>52% MC-a</small>", html)
        self.assertIn("<span class=pos>40</span> / <span class=neg>31</span>", html)   # buys / sells apart, as on DexScreener
        self.assertIn('<span class="pos">+9.0 %</span>', html)
        self.assertNotIn("Vol 5 min", html)                                           # the old two lines of text are gone
        self.assertIn("samo 1 transakcija u zadnjem satu", html)                      # the hourly rule speaks first
        quiet = {**MOVING, "txns_m5": 2, "vol_m5": 150.0, "ch_m5": 1.0}                # trades in the hour, asleep now
        html = pravitrade_popup_with(self, quiet)
        self.assertIn("samo 2 transakcije u zadnjih 5 min (treba 5+)", html)
        self.assertIn("NE KUPUJ", html)

    def test_many_accounts_posting_the_address_is_said_as_a_social_signal(self):
        self.events = [(MINT2, NOW - 60 * (i + 1), "x", f"acc{i}", "call") for i in range(6)]
        html = pravitrade_popup_with(self, dict(MOVING))
        self.assertIn("društveni signal: 6 različitih računa objavilo je adresu u zadnjih 60 min", html)
        self.events = self.events[:3]
        self.assertNotIn("društveni signal", pravitrade_popup_with(self, dict(MOVING)))


class FollowForms(PageBase):
    def test_data_exit_follow_through_the_form(self):
        """10.11. (Jure: "neka alat dinamički odluči"): exit=podaci is stored as its own mode; the typed TP means
        nothing, the run-up gate defaults to what the pair was measured for, a wallet is told why it cannot use it."""
        from ui import pravitrade
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "@ansem", "exit": "podaci", "tp": "40%", "per_day": "3"}, "Jure")
        self.assertIn("ok=", loc)
        f = copy.follows(self.lg, settings.LEAGUE_USER)[0]
        self.assertEqual((f["kind"], f["exit"]["mode"], f["exit"]["max_runup"]), ("kol", "podaci", copy.DATA_MAX_RUNUP))
        self.assertNotIn("tp", f["exit"])
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "tg:a, tg:b", "exit": "podaci", "per_day": "3"}, "Jure")
        self.assertIn("ok=", loc)
        f = next(x for x in copy.follows(self.lg, settings.LEAGUE_USER) if x["kind"] == "ekipa")
        self.assertEqual((f["exit"]["mode"], f["exit"]["max_runup"]), ("podaci", copy.DATA_MAX_RUNUP))   # not the crew's 25 %
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "@murad", "exit": "podaci", "max_runup": "20", "per_day": "3"}, "Jure")
        f = next(x for x in copy.follows(self.lg, settings.LEAGUE_USER) if x["target"] == "murad")
        self.assertAlmostEqual(f["exit"]["max_runup"], 0.20)                      # a typed limit wins
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "wallet", "target": "W" * 44, "exit": "podaci", "per_day": "3"}, "Jure")
        self.assertIn("err=", loc)
        self.assertIn("influencere", __import__("urllib.parse").parse.unquote(loc))
        html = pravitrade._follows(self.lg, True, settings.raw(self.con))
        self.assertIn("<option value=podaci>po podacima (alat bira TP/SL)</option>", html)
        self.assertIn("TP/SL po podacima", html)

    def test_tpsl_follow_without_stop_stores_the_default_and_the_card_says_so(self):
        """P10/P17/P19: no 'zadani' stop that does not exist: /follow, 'Zaprati sve' and the cards agree on DEFAULT_SL."""
        from ui import pravitrade
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "@ansem", "exit": "tpsl", "per_day": "3"}, "Jure")
        self.assertIn("ok=", loc)
        f = copy.follows(self.lg, settings.LEAGUE_USER)[0]
        self.assertEqual((f["exit"]["mode"], f["exit"]["tp"], f["exit"]["sl"]), ("tpsl", "15%", copy.DEFAULT_SL))
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "@murad", "exit": "tpsl", "sl": "-35%", "per_day": "3"}, "Jure")
        self.assertIn("ok=", loc)
        f = next(x for x in copy.follows(self.lg, settings.LEAGUE_USER) if x["target"] == "murad")
        self.assertEqual(f["exit"]["sl"], "-35%")                                # a typed stop wins
        cfg = settings.merged(executor.load_config(), self.con)
        card = pravitrade._tp_card(cfg, True)
        self.assertNotIn("ili zadani", card)
        self.assertIn(copy.DEFAULT_SL, card)
        self.assertIn(copy.DEFAULT_SL, pravitrade._buy_now_card(cfg, True))
        self.assertIn(copy.DEFAULT_SL, pravitrade._buy_form(MINT2, cfg, "tpsl", True))
        loc = pravitrade.post("/pravi-trade/followall", {"handles": "ansem,tg:alpha"}, "Jure")
        self.assertIn("stop%20-20%25", loc)

    def test_kol_with_mirror_exit_takes_the_default_instead_of_an_error(self):
        """P74: the form offers 'prodaj kad on proda' for any target; for a call it means the default exit."""
        from ui import pravitrade
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "@ansem", "exit": "mirror", "per_day": "3"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(copy.follows(self.lg, settings.LEAGUE_USER)[0]["exit"]["mode"], "smart")

    def test_crew_message_and_copyfollow_keep_the_conditions(self):
        """P72: the confirmation says the saved condition; a copied follow keeps cap, run-up and min_callers."""
        from ui import pravitrade
        loc = pravitrade.post("/pravi-trade/follow", {"kind": "auto", "target": "tg:a, tg:b, tg:c", "exit": "tpsl", "min_callers": "2",
                                                      "max_mcap": "800k", "per_day": "5"}, "Jure")
        self.assertIn("kad%20token%20zovu%202%2B", loc)
        self.assertNotIn("prvi%20od%20njih", loc)
        src = copy.follows(self.lg, settings.LEAGUE_USER)[0]
        self.assertEqual((src["exit"]["min_callers"], src["exit"]["max_mcap"]), (2, 800_000.0))
        copy.unfollow(self.lg, settings.LEAGUE_USER, src["id"])
        loc = pravitrade.post("/pravi-trade/copyfollow", {"id": str(src["id"])}, "Jure")
        self.assertIn("ok=", loc)
        cp = copy.follows(self.lg, settings.LEAGUE_USER)[0]
        self.assertEqual({k: cp["exit"][k] for k in ("min_callers", "max_mcap", "max_runup", "sl")},
                         {"min_callers": 2, "max_mcap": 800_000.0, "max_runup": 0.25, "sl": copy.DEFAULT_SL})

    def test_wallets_are_not_crew_members(self):
        """P73: a crew of followed wallets ('w:…') would never fire; 'Zaprati sve' drops them, a wallet-only crew
        row opens its token, the crew pop-up offers no crew button for wallets alone."""
        from ui import pravitrade
        loc = pravitrade.post("/pravi-trade/followall", {"handles": "w:ABC123,w:DEF456"}, "Jure")
        self.assertIn("err=", loc)
        self.assertIn("novčanike prati zasebno", unquote(loc))
        self.assertEqual(copy.follows(self.lg, settings.LEAGUE_USER), [])
        loc = pravitrade.post("/pravi-trade/followall", {"handles": "w:ABC123,ansem,tg:alpha"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual([f["target"] for f in copy.follows(self.lg, settings.LEAGUE_USER)], ["ansem,tg:alpha"])
        rows = [(MINT2, [("w:ABC123", "chain", NOW - 100)], NOW - 100, NOW - 100, "AAA", dict(MOVING))]
        g = pravitrade.crew_rows(rows, NOW)[0]
        self.assertEqual(g["key"], "")
        self.assertIn(f'data-pop="/pravi-trade/token?m={MINT2}"', pravitrade._crew_row(g, NOW))
        html = pravitrade.crew_popup("Jure", "w:ABC123", NOW)
        self.assertNotIn("Zaprati kao ekipu", html)
        self.assertIn("Samo novčanici", html)
        html = pravitrade.crew_popup("Jure", "w:ABC123,ansem", NOW)
        self.assertIn("Zaprati kao ekipu (1)", html)
        self.assertIn('name=handles value="ansem"', html)

    def test_follow_list_shows_the_demo_proof_the_live_gate_needs(self):
        """P39 (handoff novac): run_trade.PROOF per follow, so a LIVE 'blocked: praćenje bez dokaza u demu' is no surprise."""
        from ui import pravitrade
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "")
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, 0))
        for i, pnl in enumerate((5.0, -2.0)):
            tid = store.buy(self.lg, settings.LEAGUE_USER, f"T{i}" + "x" * 40, "T", 25, 1.0, 1e6, "copy")
            self.lg.execute("UPDATE trades SET follow_id=?, status='closed', pnl_usd=? WHERE id=?", (fid, pnl, tid))
        self.lg.commit()
        html = pravitrade._follows(self.lg, True)
        self.assertIn("Dokaz u demu: zatvorenih 2, dobitnih 1, PnL +3 $", html)
        self.assertIn("pravi novac: <b>još ne</b>", html)
        self.assertIn(f"treba {run_trade.PROOF['closed']}+ zatvorenih", html)
        line = pravitrade._proof_line({"closed": 12, "wins": 6, "pnl": 40.0})
        self.assertIn("pravi novac: <b>da</b>", line)

    def test_proven_wallets_show_their_bags(self):
        """P55 (handoff izvori): open losers the wallet never closed, next to its realized result."""
        from ui import pravitrade
        r = {"wallet": "W" * 40, "realized_before": 3.0, "closed_before": 6, "win_before": 0.6, "realized_after": 1.0,
             "closed_after": 3, "win_after": 0.67, "hold_min": 40.0, "tpd": 5.0, "style": "swing", "bags": 4, "bag_share": 0.2}
        html = pravitrade._dokazani_items([r], set(), True)
        self.assertIn("4 bagova", html)
        r["bags"] = None
        self.assertNotIn("bagova", pravitrade._dokazani_items([r], set(), True))


class LiveFragments(PageBase):
    """P48/P75/P33: DexScreener live TTL, per-set cache slots, and fragments that only read what the background
    thread filled (no fetch in the request thread)."""

    def test_live_cache_ttl_and_separate_slots(self):
        from ui import pravitrade, prijedlog
        pravitrade._live_cached = self._saved[5]        # the real one
        calls = []
        saved = prijedlog.live_market
        prijedlog.live_market = lambda toks, fetch=None: calls.append(tuple(toks)) or {t: dict(MOVING) for t in toks}
        try:
            self.assertEqual(pravitrade.LIVE_TTL_S, 3)
            self.assertGreaterEqual(pravitrade.LIVE_TTL_S, 2)   # owner 9.11.: 2-5 s, the IP limit is shared
            pravitrade._live_cached([MINT2], NOW)
            pravitrade._live_cached([MINT2], NOW + 2.5)         # within the TTL: no second request
            self.assertEqual(len(calls), 1)
            pravitrade._live_cached([MINT], NOW + 2.6)          # another set (a pop-up) does not evict the first
            pravitrade._live_cached([MINT2], NOW + 2.9)
            self.assertEqual(len(calls), 2)
            pravitrade._live_cached([MINT2], NOW + 3.1)         # past the TTL: fetched again
            self.assertEqual(len(calls), 3)
        finally:
            prijedlog.live_market = saved

    def test_fragments_read_the_cache_while_the_refresher_runs(self):
        from ui import pravitrade, prijedlog, zivo

        class Fake:
            def is_alive(self):
                return True
        saved = (prijedlog.live_market, zivo.rows, pravitrade.gather_callers)
        prijedlog.live_market = lambda toks, fetch=None: (_ for _ in ()).throw(AssertionError("fetch in the request thread"))
        zivo.rows = lambda now=None, **k: (_ for _ in ()).throw(AssertionError("zivo.rows in the request thread"))
        pravitrade.gather_callers = lambda now, **k: (_ for _ in ()).throw(AssertionError("gather in the request thread"))
        pravitrade.BG_REFRESH = True
        pravitrade._BG["thread"] = Fake()
        try:
            with pravitrade._LOCK:
                pravitrade._CALLERS_CACHE.update(ts=NOW - 2, html="<div class=ap-row>ZOVU</div>")
                pravitrade._IDEAS_CACHE[True] = pravitrade._IDEAS_CACHE[False] = (NOW - 1, "<div class=ap-row>IDEJA</div>")
            html = pravitrade.callers_fragment("Jure")
            self.assertIn("ZOVU", html)
            self.assertIn("podaci od " + time.strftime("%H:%M:%S", time.gmtime(NOW - 2)) + " UTC", html)   # data time, not render time
            html = pravitrade.ideas_fragment("Jure")
            self.assertIn("IDEJA", html)
            self.assertIn("podaci od", html)
            with pravitrade._LOCK:
                pravitrade._CALLERS_CACHE.update(ts=NOW, html="")
            self.assertEqual(pravitrade.callers_fragment("Jure"), "")          # empty stays empty: the section hides
            self.assertIsNone(pravitrade.callers_fragment("Ivan"))
        finally:
            prijedlog.live_market, zivo.rows, pravitrade.gather_callers = saved
            pravitrade._CALLERS_CACHE.update(ts=0, html="")
            pravitrade._IDEAS_CACHE.clear()

    def test_background_pass_fills_the_caches(self):
        from ui import pravitrade, zivo
        row = {"token": MINT2, "symbol": "AAA", "src": "zovu", "why": ["zovu: ansem"], "ts0": NOW - 300, "live": dict(MOVING),
               "callers10": ["ansem"], "smart10": 0, "expect": "x", "expect_v": None, "age_s": 300, "heat": 1.0,
               "reasons": ["novi pozivatelj u 10 min: @ansem"]}
        saved = (zivo.rows, pravitrade.gather_callers)
        zivo.rows = lambda now=None, **k: [row]
        pravitrade.gather_callers = lambda now, **k: [(MINT2, [("ansem", "x", NOW - 300)], NOW - 300, NOW - 300, "AAA", dict(MOVING))]
        pravitrade._IDEAS_CACHE.clear()
        pravitrade._CALLERS_CACHE.update(ts=0, html="")
        try:
            pravitrade._bg_pass(NOW)
            self.assertIn("AAA", pravitrade._CALLERS_CACHE["html"])
            self.assertEqual(pravitrade._CALLERS_CACHE["ts"], NOW)
            self.assertIn("AAA", pravitrade._IDEAS_CACHE[True][1])
            self.assertIs(pravitrade._IDEAS_CACHE[True][1], pravitrade._IDEAS_CACHE[False][1])   # one computation, both viewers
            self.assertEqual(pravitrade._BG["runs"], self._saved[-1]["runs"] + 1)
            # a failing source leaves the other cache alone
            zivo.rows = lambda now=None, **k: (_ for _ in ()).throw(RuntimeError("down"))
            pravitrade._bg_pass(NOW + 1)
            self.assertIn("AAA", pravitrade._CALLERS_CACHE["html"])
        finally:
            zivo.rows, pravitrade.gather_callers = saved
            pravitrade._IDEAS_CACHE.clear()
            pravitrade._CALLERS_CACHE.update(ts=0, html="")

    def test_refresher_forgets_old_wants_and_crew_key_is_stable(self):
        """Review: a set whose fetch returned None never entered _LIVE_CACHE, so its WANT entry lived for ever; the
        crew pop-up's cache key was ordered by 'last' and changed with every new call (a new slot, a synchronous
        fetch in the 1-s handler)."""
        from ui import pravitrade, zivo
        saved = (zivo.rows, pravitrade.gather_callers)
        zivo.rows = lambda now=None, **k: []
        pravitrade.gather_callers = lambda now, **k: []
        pravitrade._IDEAS_CACHE.clear()
        try:
            pravitrade._LIVE_WANT[(MINT,)] = NOW - 10 * pravitrade.BG_WANT_S - 1     # asked long ago, never cached
            pravitrade._LIVE_WANT[(MINT2,)] = NOW - 2
            pravitrade._bg_pass(NOW)
            self.assertNotIn((MINT,), pravitrade._LIVE_WANT)
            self.assertIn((MINT2,), pravitrade._LIVE_WANT)
        finally:
            zivo.rows, pravitrade.gather_callers = saved
            pravitrade._IDEAS_CACHE.clear()
            pravitrade._CALLERS_CACHE.update(ts=0, html="")
        # crew pop-up: the same two tokens called in either order ask the cache for one and the same key
        keys = []
        pravitrade._live_cached = lambda toks, now, ttl=1, wait=None: keys.append(tuple(toks)) or {}
        from kol import converge
        self.events = [(MINT, NOW - 100, "x", "ansem", "call"), (MINT2, NOW - 50, "x", "ansem", "call")]
        pravitrade.crew_popup("Jure", "ansem", NOW)
        self.events = [(MINT, NOW - 10, "x", "ansem", "call"), (MINT2, NOW - 50, "x", "ansem", "call")]
        pravitrade.crew_popup("Jure", "ansem", NOW)
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(set(keys[0]), {MINT, MINT2})

    def test_page_js_marks_stale_boxes(self):
        from ui import pravitrade
        self.assertIn("nema svježih podataka", pravitrade.POP_JS)
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("nema svježih podataka", body)
        self.assertIn("if(!r.ok){stale(box,true);return}", body)


if __name__ == "__main__":
    unittest.main()
