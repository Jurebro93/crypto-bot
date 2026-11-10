"""Audit 9.11.2026, group "novac" (the path real money takes: league/copy.py -> run_trade.py -> trade/executor.py).
Offline: fake Jupiter, temp databases, no network.

    python3 -m unittest tests.test_audit_20261109_novac_offline
"""
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from kol import store as kstore  # noqa: E402
from league import auto, copy, store  # noqa: E402
from tests.test_trade_offline import CFG, FakeJup  # noqa: E402
from trade import executor, jupiter, settings  # noqa: E402

NOW = int(time.time())
CREW = ["tg:alpha", "tg:beta", "tg:gamma"]
TOK = "Tok1" + "x" * 40
TOK2 = "Tok2" + "x" * 40
PUMP = "6MZ5FU36NKP9CZ1JWR4FzUbmB9FgekpvJDSxvADJpump"


def row(mcap=400_000, liq=50_000, m5=0.0, h1=0.0, src=None):
    ch = {"src": src} if src else {"m5": m5, "h1": h1}
    return (0.001, liq, None, mcap, "SYM", ch)


class CopyGates(unittest.TestCase):
    """copy.run_once: the gates the real-money account goes through before any demo (and so real) entry."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.lg = store.connect(os.path.join(self.d, "league.db"))
        copy.ensure(self.lg)
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", ("pravi-trade", 1e6, 0))
        self.lg.commit()
        self.kc = kstore.connect(os.path.join(self.d, "kol.db"))
        self.paths = {"kol": os.path.join(self.d, "kol.db"), "hype": os.path.join(self.d, "no-hype.db"),
                      "tg": os.path.join(self.d, "no-tg.db")}
        self._conc = copy._concentration
        copy._concentration = lambda tok: (None, "nepoznato")   # no topcheck/rug rows in these tests

    def tearDown(self):
        copy._concentration = self._conc
        self.lg.close()
        self.kc.close()

    def follow(self, **kw):
        args = dict(kind="kol", target="ansem", exit_mode="tpsl", tp="15%", sl="")
        args.update(kw)
        fid = copy.follow(self.lg, "pravi-trade", args.pop("kind"), args.pop("target"), "", 25, 5,
                          args.pop("exit_mode"), args.pop("tp"), args.pop("sl"), **args)
        self.lg.execute("UPDATE follows SET created = ?", (NOW - 3600,))
        self.lg.commit()
        return fid

    def call(self, handle, tok, ts):
        self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,'call')",
                        (f"{handle}-{tok[:4]}-{ts}", tok, handle, ts))
        self.kc.commit()

    def notes(self):
        return {r[0]: (r[1], r[2]) for r in self.lg.execute("SELECT token, action, note FROM copy_log")}

    def run_once(self, mk, now=NOW):
        return copy.run_once(self.lg, lambda toks: {t: mk[t] for t in toks if t in mk}, now, self.paths)

    def test_under_30k_is_never_bought(self):   # P1 / P5 / P7
        self.follow()
        self.call("ansem", TOK, NOW - 30)
        self.call("ansem", TOK2, NOW - 30)
        self.assertEqual(self.run_once({TOK: row(mcap=20_000), TOK2: row(mcap=None)}), [])
        n = self.notes()
        self.assertEqual(n[TOK][0], "preskočeno")
        self.assertIn("ispod 30k", n[TOK][1])
        self.assertIn("MC nepoznat", n[TOK2][1])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_bonding_curve_token_is_not_bonded(self):   # P1 / P5 / P8
        self.follow()
        self.call("ansem", PUMP, NOW - 30)
        self.assertEqual(self.run_once({PUMP: row(mcap=60_000, liq=8_000, src="jup")}), [])
        self.assertIn("krivulji", self.notes()[PUMP][1])
        self.assertIn("bondani", self.notes()[PUMP][1])
        self.assertIsNone(copy._runup(row(src="jup"), 10))   # the marker is no price change

    def test_market_marks_the_jupiter_fallback(self):   # P8: the flag comes out of copy.market itself
        from dexscreener import client
        from ui import paper
        saved = (client.tokens, paper.jup_prices)
        client.tokens = lambda chain, mints: [{"baseToken": {"address": TOK, "symbol": "D"}, "priceUsd": "1",
                                               "liquidity": {"usd": 50_000}, "marketCap": 400_000, "url": "u",
                                               "priceChange": {"m5": 1, "h1": 2}}]
        paper.jup_prices = lambda mints: {m: (0.00001, 6000.0) for m in mints if m.endswith("pump")}
        try:
            mk = copy.market({TOK, PUMP})
        finally:
            client.tokens, paper.jup_prices = saved
        self.assertTrue(copy._bonding_curve(mk[PUMP]))
        self.assertFalse(copy._bonding_curve(mk[TOK]))
        self.assertEqual(mk[PUMP][3], 0.00001 * 1e9)
        self.assertAlmostEqual(copy._runup(mk[TOK], 60), 0.01)

    def test_dex_pair_without_a_quote_is_retried_not_called_bonding_curve(self):   # review novac (market fallback)
        from dexscreener import client
        from ui import paper
        saved = (client.tokens, paper.jup_prices)
        client.tokens = lambda chain, mints: [{"baseToken": {"address": TOK, "symbol": "D"}, "priceUsd": "0",
                                               "liquidity": {"usd": 0}, "marketCap": 400_000, "url": "u"}]
        paper.jup_prices = lambda mints: {m: (0.001, 50_000.0) for m in mints}
        try:
            mk = copy.market({TOK, PUMP})
        finally:
            client.tokens, paper.jup_prices = saved
        self.assertTrue(copy._bonding_curve(mk[PUMP]) and not copy._dex_pair_empty(mk[PUMP]))   # really on the curve
        self.assertTrue(copy._dex_pair_empty(mk[TOK]))                                          # DexScreener has the pair
        self.follow()
        self.call("ansem", TOK, NOW - 30)
        self.assertEqual(self.run_once({TOK: mk[TOK]}), [])
        self.assertEqual(self.notes(), {})                               # not skipped: retried next minute
        self.assertEqual(self.run_once({TOK: mk[TOK]}, NOW + copy.CFG["price_wait_min"] * 60 + 1), [])
        self.assertEqual(self.notes()[TOK][0], "preskočeno")
        self.assertIn("DexScreener ima par", self.notes()[TOK][1])
        self.assertNotIn("krivulji", self.notes()[TOK][1])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_concentration_tables_are_read_once_per_pass(self):   # review novac (race window in copy.run_once)
        copy._concentration = self._conc
        from topcheck import store as tstore
        from ui import data as udata
        saved = (tstore.read_all, udata.rug_latest)
        reads = []
        tstore.read_all = lambda path=None, max_age_h=24: reads.append("tc") or {}
        udata.rug_latest = lambda: reads.append("rug") or {}
        try:
            self.follow()
            toks = [TOK, TOK2, "Tok3" + "x" * 40]
            for t in toks:
                self.call("ansem", t, NOW - 30)
            out = self.run_once({t: row() for t in toks})
            self.assertEqual(len(out), 3)
            self.assertEqual(sorted(reads), ["rug", "tc"])             # once per pass, not once per candidate
            self.assertIsNone(copy._CONC_CACHE)                         # and nothing stale survives the pass
            copy._concentration(TOK)                                    # outside a pass: a fresh read
            self.assertEqual(len(reads), 4)
        finally:
            tstore.read_all, udata.rug_latest = saved

    def test_crew_old_first_call_and_fresh_second_call_enters(self):   # P4
        self.follow(kind="ekipa", target=",".join(CREW), min_callers=2, max_mcap=1e6, max_runup=0.25)
        self.call("tg:alpha", TOK, NOW - 900)                      # 15 min ago: alone it is too late
        self.assertEqual(self.run_once({TOK: row()}, NOW - 840), [])
        self.assertEqual(self.notes(), {})                          # one caller: nothing decided yet
        self.call("tg:beta", TOK, NOW - 30)                        # the second member, fresh
        out = self.run_once({TOK: row()})
        self.assertEqual(len(out), 1)
        self.assertIn("kupljeno", out[0][1])
        self.assertEqual(self.notes()[TOK][0], "ulaz")
        # both older than 10 min: still skipped as late, judged on the newest call
        self.call("tg:alpha", TOK2, NOW - 1500)
        self.call("tg:beta", TOK2, NOW - 1200)
        self.assertEqual(self.run_once({TOK2: row()}), [])
        self.assertIn("prekasno", self.notes()[TOK2][1])

    def test_concentration_blocks_only_known_bad(self):   # P6 / P65
        copy._concentration = self._conc
        from topcheck import store as tstore
        from ui import data as udata
        saved = (tstore.read_all, udata.rug_latest)
        rows = {TOK: {"verdict": "oprez", "rc": {"top10": 72.0, "insiders": 0, "dev_pct": 1}}}
        tstore.read_all = lambda path=None, max_age_h=24: rows
        udata.rug_latest = lambda: {TOK2: {"top10_pct": 20.0, "cluster_pct": 31.0, "bundle_pct": 5.0, "data": {}}}
        try:
            self.assertIn("top 10 holdera drži 72%", copy._concentration(TOK)[0])
            self.assertIn("klaster", copy._concentration(TOK2)[0])
            self.assertEqual(copy._concentration("nobody" * 7), (None, "nepoznato"))
            self.follow()
            for t in (TOK, TOK2, "Tok3" + "x" * 40):
                self.call("ansem", t, NOW - 30)
            out = self.run_once({t: row() for t in (TOK, TOK2, "Tok3" + "x" * 40)})
        finally:
            tstore.read_all, udata.rug_latest = saved
        self.assertEqual(len(out), 1)                               # only the token without bad data is bought
        n = self.notes()
        self.assertIn("koncentriran", n[TOK][1])
        self.assertIn("koncentriran", n[TOK2][1])
        self.assertEqual(n["Tok3" + "x" * 40][0], "ulaz")
        self.assertIn("koncentracija: nepoznato", n["Tok3" + "x" * 40][1])   # no data is shown, never "prolazi"

    def test_tpsl_default_stop_from_effective_entry_and_fallback(self):   # default SL (10.11.: -60 %), P28, P38
        self.follow(tp="$500k", sl="")                              # TP in market cap, no stop
        self.call("ansem", TOK, NOW - 30)
        self.call("ansem", TOK2, NOW - 30)
        out = self.run_once({TOK: row(mcap=400_000), TOK2: row(mcap=600_000)})
        self.assertEqual(len(out), 2)
        t = {r["token"]: r for r in store.trades(self.lg, "pravi-trade", "open")}
        a = json.loads(t[TOK]["auto"])
        self.assertEqual((a["mode"], a["sl"]), ("tpsl", "-60%"))      # the Autopilot's default stop (trade.settings)
        self.assertAlmostEqual(a["sl_px"], t[TOK]["entry_eff"] * 0.4)   # from what was really paid
        self.assertAlmostEqual(a["tp_px"], t[TOK]["entry_px"] * 500_000 / 400_000)
        self.assertTrue(a.get("from_eff"))
        b = json.loads(t[TOK2]["auto"])                              # TP $500k under the $600k entry: Smart sell instead
        self.assertEqual(b["mode"], "smart")
        self.assertIn("Smart sell (TP/SL nije primjenjiv", self.notes()[TOK2][1])

    def test_thin_pool_against_market_cap_is_skipped(self):   # P41
        self.follow()
        self.call("ansem", TOK, NOW - 30)
        self.assertEqual(self.run_once({TOK: row(mcap=5_000_000, liq=100_000)}), [])
        self.assertIn("najveći holder", self.notes()[TOK][1])

    def test_runup_text_says_what_was_measured(self):   # P59 / P60
        self.follow(max_runup=0.25)
        self.call("ansem", TOK, NOW - 420)                         # 7 min old: DexScreener h1 is all we have
        self.assertEqual(self.run_once({TOK: row(m5=2.0, h1=60.0)}), [])
        self.assertIn("+60% u zadnjih 60 min", self.notes()[TOK][1])
        self.assertNotIn("+60% od poziva", self.notes()[TOK][1])

    def test_per_day_counts_the_zagreb_day(self):   # P58 / P62
        z = ZoneInfo("Europe/Zagreb")
        midnight = int(datetime.datetime(2026, 11, 10, 0, 0, tzinfo=z).timestamp())   # = 9.11. 23:00 UTC
        self.assertEqual(copy._day_start(midnight + 3600), midnight)
        fid = copy.follow(self.lg, "pravi-trade", "kol", "ansem", "", 25, 1, "tpsl", "15%", "")
        self.lg.execute("UPDATE follows SET created = ?", (midnight - 86400,))
        self.lg.commit()
        first = midnight + 1800                                     # 00:30 Zagreb = 23:30 UTC the day before
        self.call("ansem", TOK, first - 30)
        self.assertEqual(len(self.run_once({TOK: row()}, first)), 1)
        second = midnight + 4200                                    # 01:10 Zagreb = 00:10 UTC: a new UTC day, same Zagreb day
        self.call("ansem", TOK2, second - 30)
        self.assertEqual(self.run_once({TOK2: row()}, second), [])
        self.assertIn("limit", self.notes()[TOK2][1])
        self.assertEqual(copy._today(self.lg, fid, second), 1)


class AutoLoop(unittest.TestCase):
    def test_copy_runs_first_and_survives_auto_sell_errors(self):   # P27
        calls = []
        saved = (store.connect, auto.run_once, copy.run_once, auto._nap)

        def boom(con, market):
            calls.append("sell")
            raise RuntimeError("DexScreener down")

        def stop(every):
            raise StopIteration

        store.connect = lambda: type("C", (), {"close": lambda self: None})()
        auto.run_once = boom
        copy.run_once = lambda con: (calls.append("copy"), [])[1]
        auto._nap = stop
        try:
            with self.assertRaises(StopIteration):
                auto.loop(lambda toks: {}, every=1)
        finally:
            store.connect, auto.run_once, copy.run_once, auto._nap = saved
        self.assertEqual(calls[:2], ["copy", "sell"])


class Executor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeJup()
        self._saved = (jupiter.order, jupiter.execute, executor.STOP_FILE)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        executor.STOP_FILE = os.path.join(self.tmp.name, "STOP")
        self.con = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        jupiter.order, jupiter.execute, executor.STOP_FILE = self._saved
        self.con.close()
        self.tmp.cleanup()

    def test_sell_intent_before_swap_and_reconcile(self):   # P11
        pos = executor.buy(self.con, CFG, "M", now=NOW)
        self.con.execute("UPDATE positions SET mode='live', qty_raw=1000, qty_left=1000 WHERE id=?", (pos["id"],))
        self.con.commit()
        seen = {}

        def swap(*a, **k):
            seen["orders"] = self.con.execute("SELECT side, status, amount_in FROM orders WHERE position_id=? AND side='sell'",
                                              (pos["id"],)).fetchall()
            raise SystemExit("killed mid-swap")
        saved = (executor.swap, executor.armed)
        executor.swap, executor.armed = swap, lambda: True
        try:
            with self.assertRaises(SystemExit):
                executor.sell(self.con, CFG, pos["id"], 0.5, now=NOW + 10)
        finally:
            executor.swap, executor.armed = saved
        self.assertEqual(seen["orders"], [("sell", "pending", 500)])
        # after the restart: the wallet says 500 are left -> the half was sold, the books follow the chain
        n = executor.reconcile_pending(self.con, now=NOW + 120, balance_of=lambda t: 500)
        self.assertEqual(n, 1)
        left, st = self.con.execute("SELECT qty_left, status FROM positions WHERE id=?", (pos["id"],)).fetchone()
        self.assertEqual((left, st), (500, "open"))
        self.assertEqual(self.con.execute("SELECT status FROM orders WHERE side='sell'").fetchone()[0], "failed")
        self.assertEqual(executor.reconcile_pending(self.con, now=NOW + 240, balance_of=lambda t: 500), 0)   # once

    def test_pending_buy_keeps_its_stake_in_the_day_limit(self):   # P11
        saved = executor.swap

        def swap(*a, **k):
            raise SystemExit("killed mid-swap")
        executor.swap = swap
        try:
            with self.assertRaises(SystemExit):
                executor.buy(self.con, CFG, "M", now=NOW)
        finally:
            executor.swap = saved
        self.assertAlmostEqual(self.con.execute("SELECT sol_in FROM positions").fetchone()[0], CFG["size_sol"])
        self.con.execute("UPDATE positions SET mode='live'")
        executor.reconcile_pending(self.con, now=NOW + 120, balance_of=lambda t: 1234)
        sol_in, st = self.con.execute("SELECT sol_in, status FROM positions").fetchone()
        self.assertEqual((round(sol_in, 3), st), (CFG["size_sol"], "open"))
        why = executor.gate_buy(self.con, {**CFG, "max_sol_per_day": 0.06}, 0.05, NOW + 130, True, balance=10)
        self.assertIn("dnevni limit", why)                          # the half-booked buy counts
        # a pending buy that never landed goes back to 0
        self.con.execute("INSERT INTO positions (token, mode, status, sol_in, opened_ts) VALUES ('N','live','pending',0.05,?)", (NOW,))
        executor.reconcile_pending(self.con, now=NOW + 120, balance_of=lambda t: 0)
        self.assertEqual(self.con.execute("SELECT sol_in, status FROM positions WHERE token='N'").fetchone(), (0, "failed"))

    def test_sell_check_treats_http_errors_as_no_answer(self):   # P40
        answers = iter([{"error": "rate limited", "http_status": 429}, {"error": "rate limited", "http_status": 429}])
        jupiter.order = lambda i, o, a, taker=None, route="v2": next(answers)
        why = executor.sell_check("M", 0.05, 6)
        self.assertIn("ne kupujem naslijepo", why)
        self.assertIn("HTTP 429", why)
        answers = iter([{"error": "x", "http_status": 429}])   # v2 limited, ultra answers: fine
        ok = {"outAmount": "50000000000", "inUsdValue": 100, "outUsdValue": 99}
        back = {"outAmount": str(int(0.05 * 1e9 * 0.98)), "inUsdValue": 99, "outUsdValue": 98}

        def order(i, o, a, taker=None, route="v2"):
            if route == "v2":
                return next(answers)
            return ok if i == jupiter.SOL else back
        jupiter.order = order
        self.assertIsNone(executor.sell_check("M", 0.05, 6))
        self.assertIsNone(executor.sell_check("M", 0.05, 6, tp_pct=15))

    def test_sell_check_keeps_the_honeypot_diagnosis(self):   # review novac: a 200 "No route found" is an answer
        ok = {"outAmount": "50000000000", "inUsdValue": 100, "outUsdValue": 99}
        jupiter.order = lambda i, o, a, taker=None, route="v2": ok if i == jupiter.SOL else {"error": "No route found"}
        why = executor.sell_check("M", 0.05, 6)
        self.assertIn("honeypot", why)
        self.assertNotIn("nije uspjela", why)

    def test_cost_against_target_gate(self):   # P38
        def order(i, o, a, taker=None, route="v2"):   # the round trip loses 4 % of the SOL, 2 % per leg
            out = a * 1000 if i == jupiter.SOL else int(a // 1000 * 0.96)
            return {"inAmount": str(a), "outAmount": str(out), "requestId": "rq", "inUsdValue": 100, "outUsdValue": 98,
                    "transaction": "dHg=", "error": None}
        jupiter.order = order
        self.assertIsNone(executor.sell_check("M", 0.1, 6, tp_pct=15))   # 4 % + 2 % fees against +15 %: fine
        why = executor.sell_check("M", 0.1, 6, tp_pct=10)                # 6 % >= half of +10 %: no edge
        self.assertIn("pola cilja", why)
        r = executor.buy(self.con, {**CFG, "tp_default": 10, "size_sol": 0.1}, "M", now=NOW)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("pola cilja", r["error"])
        self.assertEqual(executor.buy(self.con, {**CFG, "tp_default": 10, "size_sol": 0.1}, "M", now=NOW, tp_pct=100)["status"], "open")
        self.assertIn("pola cilja", executor.sell_check("M", 0.02, 6, tp_pct=15))   # 0.02 SOL: fees alone are 10 %

    def test_dry_keeps_the_estimated_network_fee(self):   # P67
        jupiter.order = lambda i, o, a, taker=None, route="v2": {
            "inAmount": str(a), "outAmount": str(a * 1000 if i == jupiter.SOL else a // 1000), "requestId": "rq",
            "inUsdValue": 100, "outUsdValue": 99, "signatureFeeLamports": 5000, "prioritizationFeeLamports": 100000,
            "transaction": "dHg=", "error": None}
        r = executor.buy(self.con, CFG, "M", now=NOW)
        self.assertEqual((r["status"], r["mode"]), ("open", "dry"))
        self.assertEqual(self.con.execute("SELECT fee_lamports FROM orders WHERE side='buy'").fetchone()[0], 105000)
        self.assertAlmostEqual(self.con.execute("SELECT fees_sol FROM positions").fetchone()[0], 0.000105)
        self.assertLess(executor.day_pnl(self.con, NOW, "dry"), 0)   # dry max_loss_day sees fees like live


class Mirror(unittest.TestCase):
    """run_trade.follow_league_once: the hop from the demo account to real money."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.fake = FakeJup()
        self._saved = (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB,
                       executor.is_live)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        self.lg.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", (settings.LEAGUE_USER, 1e9, 0))
        self.lg.commit()
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        (jupiter.order, jupiter.execute, run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB,
         executor.is_live) = self._saved
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def demo(self, token, opened=NOW - 30, mcap=None, follow_id=None, ev_ts=None):
        """A demo copy trade (source "copy kol x"), by default 30 s old: past the COPY_BOOK_WAIT_S bookkeeping wait."""
        tid = store.buy(self.lg, settings.LEAGUE_USER, token, token, 25, 1.0, 1e6, "copy kol x", None, mcap)
        self.lg.execute("UPDATE trades SET opened_ts=?, follow_id=? WHERE id=?", (int(opened), follow_id, tid))
        if ev_ts and follow_id:
            self.lg.execute("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                            (follow_id, token, "buy", int(ev_ts), int(opened), token, "ulaz", "kupljeno", tid))
        self.lg.commit()
        return tid

    def reasons(self):
        return dict(self.con.execute("SELECT token, reason FROM positions"))

    def test_fresh_is_measured_from_the_call(self):   # P30 / P31 / P32
        cfg = settings.merged(CFG, self.con)
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "")
        self.demo("LATE", opened=NOW - 5, follow_id=fid, ev_ts=NOW - 500)   # demo entered 8 min after the post
        self.demo("OK", opened=NOW - 5, follow_id=fid, ev_ts=NOW - 60)
        self.demo("NOLOG", opened=NOW - 30)                                  # no copy_log: the demo entry counts
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
        st = dict(self.con.execute("SELECT token, status FROM positions"))
        self.assertEqual(st, {"LATE": "blocked", "OK": "open", "NOLOG": "open"})
        self.assertIn("signal star", self.reasons()["LATE"])

    def test_copy_trade_waits_for_its_bookkeeping(self):   # review novac: store.buy commits before follow_id / copy_log
        cfg = settings.merged(CFG, self.con)
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "")
        tid = self.demo("RACE", opened=NOW - 1)                              # a copy, read in the gap: no follow_id yet
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)   # not judged yet
        self.lg.execute("UPDATE trades SET follow_id=? WHERE id=?", (fid, tid))
        self.lg.execute("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                        (fid, "RACE", "buy", NOW - 400, NOW - 1, "RACE", "ulaz", "kupljeno", tid))
        self.lg.commit()
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW + 1, quiet=True)
        self.assertEqual(dict(self.con.execute("SELECT token, status FROM positions")), {"RACE": "blocked"})
        self.assertIn("signal star", self.reasons()["RACE"])                 # judged on the call, not the demo entry
        # live: a copy that never got its follow_id is not a manual buy; it needs proof like any follow
        executor.is_live = lambda cfg: True
        self.demo("ORPHAN", opened=NOW - 30)
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW + 1, quiet=True)
        self.assertEqual(self.con.execute("SELECT status FROM positions WHERE token='ORPHAN'").fetchone()[0], "blocked")
        self.assertIn("bez dokaza", self.reasons()["ORPHAN"])
        self.assertEqual(self.fake.executed, [])

    def test_smart_demo_trade_gets_the_page_default_target(self):   # review novac: _tp_pct docstring vs code
        cfg = {**settings.merged(CFG, self.con), "tp_default": None}   # a config without the page setting
        seen = {}

        def fake_buy(con, cfg, token, symbol=None, **kw):
            seen[token] = kw.get("tp_pct")
            return {"status": "blocked", "error": "test"}
        saved = executor.buy
        executor.buy = fake_buy
        try:
            self.demo("SMART")
            tid = self.demo("RULE")
            self.lg.execute("UPDATE trades SET auto=? WHERE id=?", (json.dumps({"mode": "tpsl", "tp": "+40%"}), tid))
            self.lg.commit()
            run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
        finally:
            executor.buy = saved
        self.assertEqual(seen, {"SMART": 15, "RULE": 40.0})   # smart: the page default (ui/pravitrade shows 15 %)

    def test_under_30k_entry_mcap_is_the_last_line(self):   # P1 / P7 (known bad only)
        cfg = settings.merged(CFG, self.con)
        self.demo("SMALL", mcap=12_000)
        self.demo("UNKNOWN", mcap=None)
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
        st = dict(self.con.execute("SELECT token, status FROM positions"))
        self.assertEqual(st, {"SMALL": "blocked", "UNKNOWN": "open"})
        self.assertIn("ispod 30k", self.reasons()["SMALL"])

    def test_live_needs_demo_proof_per_follow(self):   # P39
        cfg = settings.merged(CFG, self.con)
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "")
        self.demo("NEW", follow_id=fid)
        # dry: no proof needed, the mirror collects real quotes
        run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
        self.assertEqual(self.con.execute("SELECT status FROM positions WHERE token='NEW'").fetchone()[0], "open")
        # live: the same follow has no closed demo trades yet -> blocked before any swap
        executor.is_live = lambda cfg: True
        bought = []
        saved_buy = executor.buy
        def fake_buy(con, cfg, token, symbol=None, **k):   # records the call and leaves the row executor.buy would
            bought.append(k.get("league_id"))
            con.execute("INSERT INTO positions (league_id, token, mode, status, reason, opened_ts) VALUES (?,?,?,?,?,?)",
                        (k.get("league_id"), token, "live", "blocked", "x", NOW))
            con.commit()
            return {"status": "blocked", "error": "x"}
        executor.buy = fake_buy
        try:
            self.demo("NEW2", follow_id=fid)
            run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
            self.assertIn("bez dokaza u demu", self.reasons()["NEW2"])
            self.assertEqual(bought, [])
            # a follow with 12 closed, 7 winning, positive PnL: real money allowed
            fid2 = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "proven", "", 25, 5, "tpsl", "15%", "")
            for i in range(12):
                self.lg.execute("INSERT INTO trades (user, token, status, follow_id, pnl_usd, size_usd, opened_ts) "
                                "VALUES (?,?,?,?,?,?,?)", (settings.LEAGUE_USER, f"T{i}", "closed", fid2,
                                                           5.0 if i < 7 else -3.0, 25, NOW - 1000))
            self.lg.commit()
            tid = self.demo("GOOD", follow_id=fid2)
            run_trade.follow_league_once(self.con, cfg, since=0, now=NOW, quiet=True)
            self.assertEqual(bought, [tid])
            # a manual tap ("Kupi ručno") is the owner's own decision: no proof gate
            tid3 = self.demo("MANUAL", follow_id=fid)
            run_trade.follow_league_once(self.con, {**cfg, "manual_size": {str(tid3): 0.02}}, since=0, now=NOW, quiet=True)
            self.assertEqual(bought, [tid, tid3])
        finally:
            executor.buy = saved_buy

    def test_config_mode_is_only_a_note(self):   # P37: nothing in the code reads it; the switch + env + key decide
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trade", "config.json")))
        self.assertEqual(cfg["mode"], "dry")
        self.assertIn("samo napomena", cfg["_mode"])
        self.assertFalse(executor.is_live({**settings.merged(cfg, self.con), "mode": "live"}))


if __name__ == "__main__":
    unittest.main()
