"""Phase 0 and the data items of PR 1 (10.11.2026, Jure: "Specifikacija za Claudea"):

- flags in trade/settings (off / shadow / paper / live), the live gate (backtest pass + 7 days of paper in the plus),
  the owner-only form on /pravi-trade, the shadow log and the paper account that copies the Autopilot's follows and
  is never mirrored into real money;
- the owner-approval lock of execute_trade (both MCP entry points);
- plan 1.3: minute levels -60/-70 and +150/+200, old rows re-measured, never guessed in our favour;
- plan 1.5: the demo's exit price next to the real one;
- plan 4.4 data: call_candles kept from the same request, topped up later without touching the measured paths.

    python3 -m unittest tests.test_zastavice_offline
"""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from kol import minute, preskoceni, store as kstore, tpsl  # noqa: E402
from league import auto, copy, flags, store  # noqa: E402
from trade import executor, settings  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "kol", "config.json")))
NIGHT = dict(CFG, minute=dict(CFG.get("minute") or {}, extra_hours=[0, 24]))   # the night extras at any hour
DAY = dict(CFG, minute=dict(CFG.get("minute") or {}, extra_hours=[0, 0]))      # ... and never
NOW = int(time.time()) // 60 * 60
MINT = "So1aNaMint1111111111111111111111111111111pump"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, os.environ.get("TRADE_OWNER"))
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        settings._FLAG_CACHE.clear()
        os.environ["TRADE_OWNER"] = "Jure"
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)

    def tearDown(self):
        run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, owner = self._saved
        if owner is None:
            os.environ.pop("TRADE_OWNER", None)
        else:
            os.environ["TRADE_OWNER"] = owner
        settings._FLAG_CACHE.clear()
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def pass_backtest(self, name):
        settings.put(self.con, f"backtest:{name}", {"pass": True, "ev_lo": 1.2, "n": 60, "ts": NOW})


class Flags(Base):
    def test_every_flag_is_off_by_default_and_unknown_names_are_refused(self):
        self.assertTrue(all(v["mode"] == "off" for v in settings.flag_state(self.con).values()))
        self.assertEqual(settings.flag("dca_guard"), "off")
        for name in ("auto_exit_data", "sl_default_v2", "dca_guard", "caller_ev_rank", "latency_entry", "runup_default",
                     "holder_hard", "proof_v2", "survivor_fix", "xhook_fast", "helius_streams", "holder_snap",
                     "clusters_ext", "x_features_ingest", "junk_skip", "junk_flags", "event_flags", "grok_predictions",
                     "grok_features_fit", "regime_sizing", "time_filter", "caller_decay", "ladder_exit",
                     "zombie_guard", "organic_volume", "early_score", "early_persist", "smart_discovery",
                     "wallet_stream", "sender_exec", "demo_grok", "stop_grace"):
            self.assertIn(name, settings.FLAGS)
        with self.assertRaises(KeyError):
            settings.flag("nema_je")
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, "nema_je", "shadow")
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, "dca_guard", "turbo")

    def test_shadow_and_paper_are_free_live_needs_backtest_and_seven_days_of_paper_in_the_plus(self):
        settings.set_flag(self.con, "dca_guard", "shadow", "Jure", now=NOW)
        self.assertEqual(settings.flag("dca_guard", con=self.con), "shadow")
        with self.assertRaisesRegex(ValueError, "backtest"):
            settings.set_flag(self.con, "dca_guard", "live", "Jure", now=NOW)
        self.pass_backtest("dca_guard")
        with self.assertRaisesRegex(ValueError, "paper"):
            settings.set_flag(self.con, "dca_guard", "live", "Jure", now=NOW)
        settings.set_flag(self.con, "dca_guard", "paper", "Jure", now=NOW)
        with self.assertRaisesRegex(ValueError, "od 7 dana"):
            settings.set_flag(self.con, "dca_guard", "live", "Jure", paper={"n": 5, "pnl": 3.0}, now=NOW + 3 * 86400)
        later = NOW + 8 * 86400
        with self.assertRaisesRegex(ValueError, "minusu"):
            settings.set_flag(self.con, "dca_guard", "live", "Jure", paper={"n": 9, "pnl": -1.0}, now=later)
        with self.assertRaisesRegex(ValueError, "zatvoren"):
            settings.set_flag(self.con, "dca_guard", "live", "Jure", paper={"n": 0, "pnl": 0.0}, now=later)
        settings.set_flag(self.con, "dca_guard", "live", "Jure", paper={"n": 9, "pnl": 4.5}, now=later)
        self.assertEqual(settings.flag("dca_guard", con=self.con), "live")
        settings.set_flag(self.con, "dca_guard", "off", "Jure", now=later)   # going down is always allowed
        self.assertEqual(settings.flag("dca_guard", con=self.con), "off")

    def test_a_backtest_that_did_not_pass_is_no_pass(self):
        settings.put(self.con, "backtest:proof_v2", {"pass": False, "ev_lo": -0.4, "n": 70})
        self.assertIn("backtest", settings.live_refusal(self.con, "proof_v2", {"n": 20, "pnl": 9}, NOW))

    def test_a_data_flag_is_on_in_any_mode_and_needs_no_backtest(self):
        settings.set_flag(self.con, "grok_predictions", "live", "Jure", now=NOW)
        self.assertTrue(settings.flag_on("grok_predictions"))
        self.assertFalse(settings.flag_on("x_features_ingest"))

    def test_the_read_only_flag_is_cached_briefly_and_a_change_clears_it(self):
        self.assertEqual(settings.flag("ladder_exit"), "off")
        settings.set_flag(self.con, "ladder_exit", "shadow", "Jure")
        self.assertEqual(settings.flag("ladder_exit"), "shadow")
        settings.put(self.con, "flag:ladder_exit", {"mode": "paper"})   # a write that skips set_flag
        self.assertEqual(settings.flag("ladder_exit"), "shadow")       # ... is seen after FLAG_CACHE_S
        settings._FLAG_CACHE.clear()
        self.assertEqual(settings.flag("ladder_exit"), "paper")
        self.assertTrue(settings.any_paper())

    def test_a_missing_database_reads_as_off(self):
        self.assertEqual(settings.flag("dca_guard", path=os.path.join(self.tmp.name, "nema.db")), "off")


class WhoGetsTheNewRule(Base):
    def test_live_is_both_autopilot_accounts_paper_only_the_paper_account_players_never(self):
        au, pu = settings.LEAGUE_USER, settings.PAPER_USER
        self.assertEqual([flags.applies("dca_guard", u, "live") for u in (au, pu, "Ivan")], [True, True, False])
        self.assertEqual([flags.applies("dca_guard", u, "paper") for u in (au, pu, "Ivan")], [False, True, False])
        self.assertEqual([flags.applies("dca_guard", u, "shadow") for u in (au, pu, "Ivan")], [False, False, False])
        self.assertEqual([flags.shadowing("dca_guard", u, m) for u, m in ((au, "shadow"), (au, "paper"), (au, "live"),
                                                                          (au, "off"), (pu, "shadow"))],
                         [True, True, False, False, False])

    def test_shadow_logs_only_a_different_decision(self):
        self.assertFalse(flags.shadow(self.lg, "runup_default", 4, MINT, "ulaz", "ulaz"))
        self.assertTrue(flags.shadow(self.lg, "runup_default", 4, MINT, "ulaz", "preskočeno", {"runup": 0.31}, NOW))
        self.assertEqual(flags.shadow_summary(self.lg, NOW - 60), {"runup_default": {"n": 1, "last": NOW}})
        r = flags.shadow_rows(self.lg, "runup_default")[0]
        self.assertEqual((r[4], r[5], json.loads(r[6])), ("ulaz", "preskočeno", {"runup": 0.31}))
        flags.prune(self.lg, NOW + 31 * 86400)
        self.assertEqual(flags.shadow_rows(self.lg), [])


class PaperAccount(Base):
    def follow(self, target, tp="30%"):
        return copy.follow(self.lg, settings.LEAGUE_USER, "kol", target, target, 25, 5, "tpsl", tp, "")

    def paper_follows(self):
        return [(f["target"], f["exit"].get("tp")) for f in copy.follows(self.lg, settings.PAPER_USER)]

    def test_paper_follows_exist_only_while_a_flag_is_in_paper(self):
        self.follow("ansem")
        self.assertEqual(flags.sync_paper(self.lg, NOW), (0, 0, 0))
        self.assertEqual(self.paper_follows(), [])
        settings.set_flag(self.con, "runup_default", "paper", "Jure")
        self.assertEqual(flags.sync_paper(self.lg, NOW), (1, 0, 0))
        self.assertEqual(self.paper_follows(), [("ansem", "30%")])
        self.assertEqual(flags.sync_paper(self.lg, NOW), (0, 0, 0))   # nothing changed: nothing written
        self.follow("ansem", "50%")                                    # the owner changes the exit
        self.follow("cupsey")
        self.assertEqual(flags.sync_paper(self.lg, NOW), (1, 1, 0))
        self.assertEqual(sorted(self.paper_follows()), [("ansem", "50%"), ("cupsey", "30%")])
        fid = [f["id"] for f in copy.follows(self.lg, settings.LEAGUE_USER) if f["target"] == "cupsey"][0]
        copy.unfollow(self.lg, settings.LEAGUE_USER, fid)
        self.assertEqual(flags.sync_paper(self.lg, NOW), (0, 0, 1))
        self.assertEqual(self.paper_follows(), [("ansem", "50%")])
        settings.set_flag(self.con, "runup_default", "shadow", "Jure")
        flags.sync_paper(self.lg, NOW)
        self.assertEqual(self.paper_follows(), [])

    def test_the_paper_account_takes_the_autopilot_default_stop(self):
        self.assertEqual(copy.default_sl(settings.PAPER_USER), copy.default_sl(settings.LEAGUE_USER))
        self.assertEqual(copy.default_sl("Ivan"), copy.DEFAULT_SL)

    def test_paper_result_counts_only_the_paper_account_since_the_flag(self):
        for user, pnl, ts in ((settings.PAPER_USER, 4.0, NOW), (settings.PAPER_USER, -1.5, NOW + 10),
                              (settings.PAPER_USER, 9.0, NOW - 86400), (settings.LEAGUE_USER, 50.0, NOW)):
            self.lg.execute("INSERT INTO trades (user, token, opened_ts, status, pnl_usd, size_usd) VALUES (?,?,?,?,?,25)",
                            (user, MINT, ts, "closed", pnl))
        self.lg.execute("INSERT INTO trades (user, token, opened_ts, status, size_usd) VALUES (?,?,?,'open',25)",
                        (settings.PAPER_USER, MINT, NOW))
        self.assertEqual(flags.paper_result(self.lg, NOW), {"n": 2, "pnl": 2.5, "open": 1})

    def test_run_trade_never_mirrors_the_paper_account(self):
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, qty, "
                        "source) VALUES (?,?,?,?,'open',25,1,1,25,'copy KOL ansem')",
                        (settings.PAPER_USER, MINT, "PAPER", NOW))
        self.lg.commit()
        self.assertEqual(run_trade._league_fresh(self.lg, NOW - 60), [])
        cfg = executor.load_config() if hasattr(executor, "load_config") else {}
        cfg = {**cfg, "max_signal_age_s": 600, "on": False}
        run_trade.follow_league_once(self.con, cfg, NOW - 60, now=NOW + 1, quiet=True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)

    def test_the_one_second_exits_watch_both_autopilot_accounts(self):
        seen = []

        def market(toks):
            seen.extend(toks)
            return {t: (2.0, 1e6, None, 1e5) for t in toks}
        for user in (settings.LEAGUE_USER, settings.PAPER_USER, "Ivan"):
            tid = store.buy(self.lg, user, MINT, "T", 25, 1.0, 1e6)
            auto.set_auto(self.lg, user, tid, "tpsl", "50%", "-60%")
        done = auto.fast_once(self.lg, market, (settings.LEAGUE_USER, settings.PAPER_USER))
        self.assertEqual(sorted(u for u, _, _ in done), sorted([settings.LEAGUE_USER, settings.PAPER_USER]))
        self.assertEqual(len(store.trades(self.lg, "Ivan", "open")), 1)   # a player's trade is not this loop's


class ApprovalLock(unittest.TestCase):
    def test_the_standalone_server_refuses_a_trade_without_approval(self):
        here = os.path.join(ROOT, "mcp_server")
        stubs = {}
        for name in ("httpx", "config"):
            if name not in sys.modules:
                stubs[name] = types.ModuleType(name)
        stubs.get("config", types.ModuleType("x")).__dict__.update(
            {"API_BASE": "http://x", "API_KEY": "k", "TIMEOUT": 5, "MEMESONAR_URL": "http://x", "MEMESONAR_KEY": "k"})
        sys.modules.update(stubs)
        try:
            spec = importlib.util.spec_from_file_location("ms_tools_test", os.path.join(here, "tools.py"))
            tools = importlib.util.module_from_spec(spec)
            sys.path.insert(0, here)
            try:
                spec.loader.exec_module(tools)
            finally:
                sys.path.remove(here)
            out = tools.execute_trade(MINT, 0.05, "buy", require_approval=False)
            self.assertIn("error", out)
            self.assertIn("approval", out["error"])
        finally:
            for name in stubs:
                sys.modules.pop(name, None)


def candles(start, mins, moves=None, price=1.0):
    out = []
    for k in range(mins):
        o, h, l, c = (moves or {}).get(k, (price, price, price, price))
        out.append((start + k * 60, o, h, l, c, 100.0))
    return out


class WideLevels(unittest.TestCase):
    def test_path_stores_minus_60_and_70_and_plus_150_and_200_with_the_version(self):
        t0 = NOW - 6 * 3600
        m = {5: (1.0, 3.2, 1.0, 3.1), 20: (3.1, 3.1, 0.25, 0.3)}
        o = minute.path(candles(t0 - 120, 120, m), t0 - 60)
        self.assertEqual(o["lv"]["v"], minute.LV_VERSION)
        self.assertIn("150", o["lv"]["u"])
        self.assertIn("200", o["lv"]["u"])
        self.assertIn("60", o["lv"]["d"])
        self.assertIn("70", o["lv"]["d"])

    def test_the_grid_has_the_wide_pairs_and_decide_still_chooses_among_the_old_ones(self):
        rows = [{"tweet_id": str(i), "token": f"T{i}", "handle": "a", "ts": NOW + i, "r60": 0.0, "lo60": -0.65,
                 "lv": json.dumps({"u": {"10": 1}, "d": {"10": 3, "50": 4, "60": 5}, "v": 2})} for i in range(12)]
        g = tpsl.grid(rows)
        self.assertIn((15, 60), g)
        self.assertIn((100, 50), g)
        self.assertEqual(g[(10, 60)]["tp"], 1.0)
        d = tpsl.decide(rows)
        self.assertIn(d["tp"], tpsl.CHOICE_TPS)
        self.assertIn(d["sl"], tpsl.CHOICE_SLS)

    def test_an_old_row_is_stopped_at_minus_60_no_later_than_its_deepest_stored_level(self):
        old = {"u": {"10": 9}, "d": {"10": 1, "20": 2, "50": 4}}             # before 10.11.: no "v", no "60"
        r = {"ts": NOW, "r60": -0.2, "lo60": -0.65, "lv": json.dumps(old)}
        self.assertEqual(tpsl.outcome(dict(r), 10, 60), ("sl", -60.0))      # target at 9 came after minute 4
        r_shallow = {"ts": NOW, "r60": -0.2, "lo60": -0.55, "lv": json.dumps(old)}
        self.assertEqual(tpsl.outcome(dict(r_shallow), 10, 60), ("tp", 10.0))   # never went down 60 %
        new = {"u": {"10": 9}, "d": {"10": 1, "20": 2, "50": 4, "60": 12}, "v": 2}
        self.assertEqual(tpsl.outcome({"ts": NOW, "r60": 0, "lo60": -0.65, "lv": json.dumps(new)}, 10, 60), ("tp", 10.0))
        old_up = {"u": {"10": 2, "100": 5}, "d": {}}
        self.assertEqual(tpsl.outcome({"ts": NOW, "r60": 2.5, "lo60": 0, "lv": json.dumps(old_up)}, 100, 60)[0], "tp")

    def test_a_skipped_buy_measured_before_does_not_claim_the_new_levels(self):
        old = {"entry": 1.0, "lv": json.dumps({"u": {"10": 2}, "d": {"50": 4}})}
        self.assertEqual(preskoceni._first(old, "d", 60, 20, "sl_min"), (None, False))
        self.assertEqual(preskoceni._first(old, "d", 50, 20, "sl_min"), (4, True))
        new = {"entry": 1.0, "lv": json.dumps({"u": {}, "d": {"60": 7}, "v": 2})}
        self.assertEqual(preskoceni._first(new, "d", 60, 20, "sl_min"), (7, True))


class Remeasure(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kc = kstore.connect(os.path.join(self.d, "kol.db"))
        self.mc = minute.connect(os.path.join(self.d, "minute.db"))
        self.t0 = NOW - 10 * 3600
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('OLD', 'PAIR2', 1e6)")
        self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('9', 'OLD', 'ansem', ?, 'call')",
                        (self.t0,))
        self.kc.commit()
        self.mc.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, lag_s, lo60, r60, t10, sl_min, "
                        "first_caller, measured_ts) VALUES ('9','OLD','ansem',?,1.0,10,-0.65,-0.2,2,4,1,?)",
                        (self.t0, NOW - 9 * 3600))
        self.old_lv = json.dumps({"u": {"10": 2}, "d": {"10": 1, "20": 4, "50": 6}})
        self.mc.execute("INSERT INTO call_lv VALUES ('9','OLD',?,?)", (self.t0, self.old_lv))
        self.mc.commit()

    def tearDown(self):
        self.kc.close()
        self.mc.close()

    def test_rows_with_the_old_levels_are_measured_again(self):
        self.assertEqual(minute.relevel_due(self.mc, minute.config(CFG), NOW, upgrade=False), {})   # by day: not yet
        day_asked = []
        minute.run(self.kc, self.mc, DAY, NOW, fetch=lambda p, s, e: day_asked.append(p) or [])
        self.assertEqual(day_asked, [])
        due = minute.relevel_due(self.mc, minute.config(CFG), NOW)
        self.assertEqual(list(due), ["OLD"])
        m = {3: (1.0, 1.12, 1.0, 1.1), 8: (1.1, 1.1, 0.3, 0.32)}
        got = []

        def fetch(pool, start, end):
            got.append((pool, end))
            return candles(self.t0 - 600, 400, {k + 10: v for k, v in m.items()})
        minute.run(self.kc, self.mc, NIGHT, NOW, fetch=fetch)
        lv = json.loads(self.mc.execute("SELECT lv FROM call_lv WHERE tweet_id='9'").fetchone()[0])
        self.assertEqual(lv["v"], minute.LV_VERSION)
        self.assertEqual(lv["d"]["60"], 8)
        self.assertEqual(self.mc.execute("SELECT t10, sl_min FROM call_path WHERE tweet_id='9'").fetchone(), (2, 4))
        self.assertGreaterEqual(got[0][1], self.t0 + minute.CANDLE_MIN * 60)   # the request reaches 240 min after the call
        self.assertEqual(minute.relevel_due(self.mc, minute.config(CFG), NOW), {})

    def test_a_second_measurement_that_finds_nothing_keeps_the_old_levels(self):
        minute.run(self.kc, self.mc, NIGHT, NOW, fetch=lambda p, s, e: candles(self.t0 + 7200, 30))
        lv = json.loads(self.mc.execute("SELECT lv FROM call_lv WHERE tweet_id='9'").fetchone()[0])
        self.assertEqual(lv["d"], {"10": 1, "20": 4, "50": 6})               # kept, not replaced by "x"
        self.assertEqual(lv["stuck"], minute.LV_VERSION)
        self.assertEqual(minute.relevel_due(self.mc, minute.config(CFG), NOW), {})


class Candles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.kc = kstore.connect(os.path.join(self.d, "kol.db"))
        self.mc = minute.connect(os.path.join(self.d, "minute.db"))
        self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES ('TOK', 'P1', 1e6)")
        self.kc.commit()

    def tearDown(self):
        self.kc.close()
        self.mc.close()

    def call(self, tid, ts):
        self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?, 'TOK', 'ansem', ?, 'call')",
                        (tid, ts))
        self.kc.commit()

    def test_a_late_measurement_keeps_240_minutes_of_candles_from_the_same_request(self):
        t0 = NOW - 6 * 3600
        self.call("1", t0)
        n = []

        def fetch(pool, start, end):
            n.append(1)
            return candles(start, int((end - start) // 60))
        minute.run(self.kc, self.mc, CFG, NOW, fetch=fetch)
        self.assertEqual(len(n), 1)
        got = minute.call_candles(self.mc, "TOK", t0)
        self.assertEqual(min(got), 0)
        self.assertEqual(max(got), minute.CANDLE_MIN)
        self.assertEqual(self.mc.execute("SELECT full FROM call_candles WHERE token='TOK'").fetchone()[0], 1)
        n.clear()
        minute.run(self.kc, self.mc, NIGHT, NOW + 600, fetch=fetch)
        self.assertEqual(n, [])                                              # full: never asked again

    def test_a_fresh_call_is_topped_up_later_and_a_gone_pool_never_touches_the_path(self):
        t0 = NOW - 75 * 60
        self.call("1", t0)

        def fetch(pool, start, end):
            return candles(start, int((end - start) // 60))
        minute.run(self.kc, self.mc, CFG, NOW, fetch=fetch)
        self.assertEqual(self.mc.execute("SELECT full FROM call_candles WHERE token='TOK'").fetchone()[0], 0)
        self.assertEqual(minute.run(self.kc, self.mc, DAY, NOW + 4 * 3600, fetch=fetch), (0, 0, 0))   # by day: waits
        path = self.mc.execute("SELECT * FROM call_path WHERE tweet_id='1'").fetchone()
        later = NOW + 4 * 3600
        self.assertEqual(list(minute.candles_due(self.mc, minute.config(CFG), later)), ["TOK"])
        asked = []

        def topup(pool, start, end):
            asked.append(end)
            return candles(start, int((end - start) // 60))
        minute.run(self.kc, self.mc, NIGHT, later, fetch=topup)
        self.assertEqual(len(asked), 1)
        self.assertEqual(max(minute.call_candles(self.mc, "TOK", t0)), minute.CANDLE_MIN)
        self.assertEqual(self.mc.execute("SELECT * FROM call_path WHERE tweet_id='1'").fetchone(), path)
        self.assertEqual(minute.candles_due(self.mc, minute.config(CFG), later), {})
        # a token whose pool is gone (404) only stops being asked; its measured path stays
        self.mc.execute("UPDATE call_candles SET full = 0")
        self.mc.commit()

        class Gone(Exception):
            code = 404

        def gone(pool, start, end):
            raise Gone("404")
        minute.run(self.kc, self.mc, NIGHT, later + 60, fetch=gone, log=lambda *a: None)
        self.assertEqual(self.mc.execute("SELECT * FROM call_path WHERE tweet_id='1'").fetchone(), path)
        self.assertEqual(self.mc.execute("SELECT full FROM call_candles WHERE token='TOK'").fetchone()[0], 1)

    def test_the_night_extras_stop_at_their_request_budget(self):
        for i in range(3):
            self.kc.execute("INSERT INTO tokens (token, pair, supply) VALUES (?, ?, 1e6)", (f"T{i}", f"P{i + 2}"))
            self.mc.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, lag_s, first_caller, measured_ts) "
                            "VALUES (?, ?, 'a', ?, 1.0, 10, 1, ?)", (str(i + 10), f"T{i}", NOW - 6 * 3600, NOW))
            self.mc.execute("INSERT INTO call_lv VALUES (?, ?, ?, ?)", (str(i + 10), f"T{i}", NOW - 6 * 3600,
                                                                       json.dumps({"u": {}, "d": {"10": 3}})))
        self.kc.commit()
        self.mc.commit()
        cfg = dict(NIGHT, minute=dict(NIGHT["minute"], night_requests=2))
        asked = []
        minute.run(self.kc, self.mc, cfg, NOW, fetch=lambda p, s, e: asked.append(p) or candles(s, 60))
        self.assertEqual(len(asked), 2)
        minute.run(self.kc, self.mc, cfg, NOW + 60, fetch=lambda p, s, e: asked.append(p) or candles(s, 60))
        self.assertEqual(len(asked), 2)                                      # spent for tonight

    def test_one_request_never_reaches_past_its_1000_candles(self):
        calls = [("a", "h", NOW - 14 * 3600), ("b", "h", NOW - 6 * 3600)]
        start = calls[0][2] - 600
        end = minute._fetch_end(calls, start, NOW)
        self.assertLessEqual((end - start) / 60, minute.CANDLE_LIMIT)
        self.assertGreaterEqual(end, calls[1][2] + 65 * 60)                # the measured hour is always covered


class ExitSlip(Base):
    def test_the_real_exit_is_compared_with_the_demos(self):
        self.lg.execute("INSERT INTO trades (id, user, token, opened_ts, closed_ts, status, size_usd, entry_px, exit_px) "
                        "VALUES (7, ?, ?, ?, ?, 'closed', 25, 0.0001, 0.00012)", (settings.LEAGUE_USER, MINT, NOW - 600, NOW - 30))
        self.lg.commit()
        self.con.execute("INSERT INTO positions (id, token, symbol, opened_ts, mode, status, sol_in, qty_raw, qty_left, "
                         "sol_back, closed_ts, league_id) VALUES (3, ?, 'T', ?, 'live', 'closed', 0.1, 1000000000000, 0, "
                         "0.11, ?, 7)", (MINT, NOW - 600, NOW - 20))
        # 1,000,000 tokens (6 decimals) sold for 0.11 SOL at $100/SOL = $11 -> $0.000011 per token... x10 below
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status) "
                         "VALUES (?, 3, ?, 'sell', 'live', 1000000000000, 1100000000, 'ok')", (NOW - 20, MINT))
        self.con.commit()
        n = executor.exit_reconcile(self.con, self.lg, lambda m: 6, lambda: 100.0, now=NOW)
        self.assertEqual(n, 1)
        demo, real, slip = self.con.execute("SELECT demo_exit_px, real_exit_px, exit_slip_pct FROM positions WHERE id=3").fetchone()
        self.assertAlmostEqual(demo, 0.00012)
        self.assertAlmostEqual(real, 1.1 * 100 / 1_000_000)               # 0.00011 USD per token
        self.assertAlmostEqual(slip, (0.00011 / 0.00012 - 1) * 100)
        self.assertEqual(executor.exit_reconcile(self.con, self.lg, lambda m: 6, lambda: 100.0, now=NOW), 0)

    def test_without_a_sol_price_or_for_an_old_close_nothing_is_guessed(self):
        self.con.execute("INSERT INTO positions (id, token, opened_ts, mode, status, sol_in, closed_ts, league_id) "
                         "VALUES (4, ?, ?, 'dry', 'closed', 0.1, ?, 8)", (MINT, NOW - 9000, NOW - 8000))
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status) "
                         "VALUES (?, 4, ?, 'sell', 'dry', 5, 5, 'dry')", (NOW - 8000, MINT))
        self.con.commit()
        self.assertEqual(executor.exit_reconcile(self.con, self.lg, lambda m: 6, lambda: None, now=NOW), 0)
        self.assertEqual(executor.exit_reconcile(self.con, self.lg, lambda m: 6, lambda: 100.0, now=NOW), 0)


class Page(Base):
    def setUp(self):
        super().setUp()
        from ui import pravitrade
        pravitrade._LIVE_CACHE.clear()
        pravitrade._LIVE_FAIL.clear()

    def test_the_owner_sets_a_flag_and_live_is_refused_with_the_reason(self):
        from ui import pravitrade
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Zastavice plana", body)
        self.assertIn("sve isključeno", body)
        self.assertIn("action=/pravi-trade/flag", body)
        self.assertIn("Demo naspram pravog izlaza", body)
        loc = pravitrade.post("/pravi-trade/flag", {"name": "dca_guard", "mode": "shadow"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(settings.flag("dca_guard", con=self.con), "shadow")
        loc = unquote(pravitrade.post("/pravi-trade/flag", {"name": "dca_guard", "mode": "live"}, "Jure"))
        self.assertIn("err=", loc)
        self.assertIn("backtest", loc)
        self.assertIn("err=", pravitrade.post("/pravi-trade/flag", {"name": "dca_guard", "mode": "live"}, "netko"))
        self.assertEqual(settings.flag("dca_guard", con=self.con), "shadow")
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("1 od", body)

    def test_others_see_the_modes_but_no_form(self):
        from ui import pravitrade
        settings.put(self.con, "invited", ["Ivan"])
        _, body = pravitrade.page({}, "Ivan")
        if "Zastavice plana" in body:
            self.assertNotIn("action=/pravi-trade/flag", body)


class McpTrades(Base):
    def test_get_autopilot_trades_carries_the_exit_slip(self):
        from ui import mcpdata
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, sol_in, sol_back, closed_ts, "
                         "league_id, demo_exit_px, real_exit_px, exit_slip_pct) VALUES (?, 'T', ?, 'live', 'closed', 0.1, "
                         "0.09, ?, NULL, 0.00012, 0.00011, -8.33)", (MINT, NOW - 600, NOW - 60))
        self.con.commit()
        out = mcpdata.autopilot_trades()
        t = out["rows"][0]
        self.assertEqual(t["exit_slip_pct"], -8.33)
        self.assertEqual(t["lots"][0]["real_exit_px"], 0.00011)


if __name__ == "__main__":
    unittest.main()
