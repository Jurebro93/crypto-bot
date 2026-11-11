"""11.11. (Jure, flags momentum_scalp G16 and grok_ev_gate G17): momentum scalp (momentum/) and Grok's EV gate.
Entry rules on synthetic fixtures, the real anti-wash check (the fee / volume rule alone passes wash), exits (TP1
half, trailing 8 %, stop -10 %, 45 min, a stale price fires only the stop), the base rate of every signal and its
outcome, paper only on the demo account (the real account's position in the same token untouched), the live gate
(>= 50 paper trades, EV > 0, hit >= 45 %) in set_flag, the trader and run_trade, the backtest on synthetic candles,
the EV gate math and its off / shadow / paper behaviour, calibration bookkeeping (Brier, buckets), the backwards
compatible execute_trade and the MCP / brief / kandidati / report parts. No network.

    python3 -m unittest tests.test_momentum_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_trade  # noqa: E402
from league import copy, flags, store  # noqa: E402
from momentum import backtest, data, evgate, gate, job, rules, trade, view  # noqa: E402
from trade import settings  # noqa: E402
from ui import grokauto, mcpapi  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, MINT  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
TOK = MINT
TOK2 = MINT[:-1] + "8"
P = 1e-4   # price: MC = P x 1e9 = $100k


def pair(tok, price=P, mcap=100_000.0, liq=50_000.0, vol_m5=6_000.0, vol_h1=20_000.0, buys=80, sells=30, ch=10.0,
         dex="pumpswap", pool=None):
    return {"chainId": "solana", "baseToken": {"address": tok, "symbol": "MOM"}, "priceUsd": str(price),
            "marketCap": mcap, "liquidity": {"usd": liq}, "volume": {"m5": vol_m5, "h1": vol_h1, "h6": vol_h1 * 3},
            "txns": {"m5": {"buys": buys, "sells": sells}, "h1": {"buys": buys * 4, "sells": sells * 4}},
            "priceChange": {"m5": ch}, "pairAddress": pool or ("POOL" + tok[:8]), "dexId": dex}


def mfeat(**kw):
    """A market feature dict that passes cheap_check."""
    f = {"price": P, "mcap": 100_000, "liq": 50_000, "ch_m5": 10.0, "bonded": True, "vol_m5": 6_000, "vol_h1": 20_000,
         "buys_m5": 80, "sells_m5": 30, "fee_rate": 0.003}
    f.update(kw)
    return f


ORGANIC_WASH = {"how": "pumpportal", "wash": 5.0, "traders_h1": 90, "tx_per_trader": 1.3, "usd_per_trader": 120.0}


def hype_db(path, now, tok=TOK, wash=False):
    """hype.db with live_trades: organic (many distinct buyers, rising) or wash (5 wallets round-tripping)."""
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE IF NOT EXISTS live_trades (sig TEXT, mint TEXT, wallet TEXT, side TEXT, sol REAL, "
                      "tokens REAL, price_sol REAL, mcap_sol REAL, pool TEXT, ts INTEGER, balance_after REAL, "
                      "PRIMARY KEY (sig, mint));"
                      "CREATE TABLE IF NOT EXISTS token_pulse (token TEXT, ts INTEGER, price REAL, mcap REAL, "
                      "liquidity REAL, vol_m5 REAL, vol_h1 REAL, buys_m5 INTEGER, sells_m5 INTEGER, buys_h1 INTEGER, "
                      "sells_h1 INTEGER, holders INTEGER, holders_src TEXT, PRIMARY KEY (token, ts));"
                      "CREATE TABLE IF NOT EXISTS live_launches (mint TEXT, ts INTEGER, pool TEXT, name TEXT, symbol TEXT)")
    rows, k = [], 0

    def add(w, side, sol, ts):
        nonlocal k
        k += 1
        rows.append((f"s{tok[:4]}{k}_{now}", tok, w, side, sol, 1000.0, 1e-6, 100.0, "pump-amm", ts, None))
    if wash:
        for i in range(60):
            add(f"WASH{i % 5}", "buy" if i % 2 == 0 else "sell", 2.0, now - 3000 + i * 50)
    else:
        for i in range(40):                       # last 5 min: 40 distinct buyers, 15 distinct sellers
            add(f"B{i}", "buy", 0.1 + i * 0.013, now - 280 + i * 6)
        for i in range(15):
            add(f"S{i}", "sell", 0.2 + i * 0.017, now - 270 + i * 15)
        for i in range(12):                       # 5-10 min ago: 12 distinct buyers
            add(f"E{i}", "buy", 0.15 + i * 0.011, now - 590 + i * 20)
        for i in range(20):                       # earlier in the hour
            add(f"H{i}", "buy", 0.12 + i * 0.019, now - 3300 + i * 120)
    con.executemany("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------------------------------------------
class EntryRules(unittest.TestCase):
    def test_a_clean_jump_passes_every_market_condition(self):
        self.assertIsNone(rules.cheap_check(mfeat()))
        self.assertAlmostEqual(rules.vol_x(6_000, 20_000), 6_000 / (14_000 / 11))
        self.assertIsNone(rules.vol_x(5_000, 5_000))                       # nothing traded in the hour before

    def test_each_market_condition(self):
        cases = {"krivulji": mfeat(bonded=False), "ispod 30k": mfeat(mcap=25_000), "iznad": mfeat(mcap=3_500_000),
                 "likvidnost": mfeat(liq=15_000), "već prošao": mfeat(ch_m5=22.0), "treba +5": mfeat(ch_m5=3.0),
                 "kupnje": mfeat(buys_m5=50, sells_m5=50), "x prosjeka": mfeat(vol_m5=2_000),
                 "osnovice": mfeat(vol_m5=5_000, vol_h1=5_000), "naknade": mfeat(fee_rate=0.0005),
                 "promet": mfeat(liq=20_000, vol_h1=600_000, vol_m5=200_000), "nepoznat": mfeat(ch_m5=None)}
        for word, f in cases.items():
            why = rules.cheap_check(f)
            self.assertIsNotNone(why, word)
            self.assertIn(word, why, word)

    def test_fees_over_volume_passes_wash_trading_so_the_real_check_is_the_traders(self):
        # PumpSwap takes ~0.3 % of every swap: a pure wash flow passes the fee rule and every market rule
        self.assertIsNone(rules.cheap_check(mfeat(fee_rate=job.fee_rate("pumpswap", job._fee_cfg()))))
        with tempfile.TemporaryDirectory() as d:
            now = 1_800_000_000
            hype_db(os.path.join(d, "h.db"), now, wash=True)
            rows = data.pp_trades(TOK, now, os.path.join(d, "h.db"))
            b, w = data.pp_features(rows, now, 5, 100.0)
            self.assertEqual(w["traders_h1"], 5)
            self.assertIn("jedinstvenih tradera", rules.wash_check(w, 50_000))
            w2 = dict(w, traders_h1=40)                                    # enough wallets, still wash
            self.assertIn("lažni volumen", rules.wash_check(w2, 50_000))
            hype_db(os.path.join(d, "o.db"), now, TOK2)
            rows = data.pp_trades(TOK2, now, os.path.join(d, "o.db"))
            b, w = data.pp_features(rows, now, 110, 100.0)
            self.assertIsNone(rules.wash_check(w, 50_000), w)
            self.assertEqual((b["now"], b["before"], b["how"]), (40, 12, "pumpportal"))
            self.assertIsNone(rules.buyers_check(b))
            self.assertEqual(data.pp_features(rows, now, 400, 100.0), (None, None))   # PumpPortal covers too little

    def test_wash_ratios_and_the_gecko_lower_bound(self):
        self.assertIsNone(rules.wash_check(ORGANIC_WASH, 50_000))
        self.assertIn("transakcija po traderu", rules.wash_check(dict(ORGANIC_WASH, tx_per_trader=6.0), 50_000))
        self.assertIn("po traderu u satu", rules.wash_check(dict(ORGANIC_WASH, usd_per_trader=4_000.0), 50_000))
        self.assertIsNone(rules.wash_check(dict(ORGANIC_WASH, usd_per_trader=4_000.0), 300_000))   # 2 % of a big pool
        self.assertIn("ne može provjeriti", rules.wash_check(None))
        a = {"transactions": {"m5": {"buys": 60, "sells": 20, "buyers": 30, "sellers": 15},
                              "h1": {"buys": 300, "sells": 200, "buyers": 80, "sellers": 40}}, "volume_usd": {"h1": "60000"}}
        b, w = data.gt_features(a)
        self.assertEqual(w["how"], "gecko")
        self.assertAlmostEqual(w["tx_per_trader"], 500 / 120)
        self.assertIn("transakcija po traderu (donja granica", rules.wash_check(w, 50_000))
        self.assertAlmostEqual(b["hour_rate"], 50 / 11)
        self.assertIsNone(rules.buyers_check(b))                           # 30 > 1.5 x 4.5
        self.assertIn("ne rastu", rules.buyers_check({"now": 10, "hour_rate": 8.0, "how": "gecko"}))
        self.assertIn("ne rastu", rules.buyers_check({"now": 12, "before": 11, "how": "pumpportal"}))
        self.assertIn("samo 5", rules.buyers_check({"now": 5, "before": 0}))
        self.assertIn("nepoznati", rules.buyers_check(None))

    def test_top10_rug_shill_and_the_order(self):
        self.assertIsNone(rules.top10_check(20))
        self.assertIn("35", rules.top10_check(36))
        self.assertIn("nepoznat", rules.top10_check(None))
        self.assertIn("rug rizik", rules.rug_check({"level": "risk", "risk": ["rug filter: visok rizik"]}))
        self.assertIn("rug:", rules.rug_check({"level": "hard", "hard": ["mint ovlast"]}))
        self.assertIsNone(rules.rug_check({"level": "oprez"}))
        self.assertIn("shillera", rules.shill_check(["paidguy"]))
        f = dict(mfeat(), wash_in=ORGANIC_WASH, buyers_in={"now": 30, "before": 10}, rug_in={"level": "ok"},
                 shill_in=[], top10=20)
        self.assertIsNone(rules.entry_check(f))
        self.assertEqual(rules.entry_check(dict(f, top10=50))[0], "top10")
        self.assertEqual(rules.entry_check(dict(f, shill_in=["x"], top10=None))[0], "shill")   # free checks first


class ExitAndBaseRate(unittest.TestCase):
    def test_tp1_half_then_trailing_from_the_peak(self):
        st, t0 = {}, 1000
        self.assertIsNone(rules.exit_step(st, 1.0, 1.10, t0 + 60, t0))
        self.assertEqual(rules.exit_step(st, 1.0, 1.15, t0 + 120, t0), ("tp1", 0.5))
        self.assertIsNone(rules.exit_step(st, 1.0, 1.30, t0 + 180, t0))
        self.assertIsNone(rules.exit_step(st, 1.0, 1.20, t0 + 240, t0))   # 1.30 x 0.92 = 1.196
        self.assertEqual(rules.exit_step(st, 1.0, 1.19, t0 + 300, t0), ("trailing", 1.0))

    def test_stop_time_and_stale(self):
        t0 = 1000
        self.assertEqual(rules.exit_step({}, 1.0, 0.90, t0 + 60, t0), ("stop", 1.0))
        self.assertEqual(rules.exit_step({}, 1.0, 0.85, t0 + 60, t0, stale=True), ("stop", 1.0))
        self.assertIsNone(rules.exit_step({}, 1.0, 1.20, t0 + 60, t0, stale=True))   # a stale price never takes profit
        self.assertEqual(rules.exit_step({}, 1.0, 1.02, t0 + 45 * 60, t0), ("time", 1.0))

    def test_outcome_tp_first_sl_first_time_and_a_candle_with_both(self):
        t0 = 6000
        self.assertEqual(rules.outcome([(t0 + 60, 1.05), (t0 + 120, 1.16), (t0 + 180, 0.8)], 1.0, t0)["first"], "tp")
        o = rules.outcome([(t0 + 60, 0.95), (t0 + 120, 0.89), (t0 + 180, 1.3)], 1.0, t0)
        self.assertEqual((o["first"], o["hit"]), ("sl", 0))
        self.assertIsNone(rules.outcome([(t0 + 60, 1.05)], 1.0, t0, now=t0 + 600)["first"])   # still open
        self.assertEqual(rules.outcome([(t0 + 60, 1.05)], 1.0, t0, now=t0 + 2700)["first"], "time")
        self.assertEqual(rules.outcome([(t0 + 46 * 60, 1.5)], 1.0, t0, now=t0 + 600)["first"], "time")   # too late
        self.assertEqual(rules.outcome([(t0 + 60, 1.0, 1.2, 0.85, 1.1)], 1.0, t0)["first"], "sl")   # pessimistic

    def test_simulate_and_the_cost(self):
        t0 = 6000
        res, why = rules.simulate([(t0 + 60, 1.16), (t0 + 120, 1.25), (t0 + 180, 1.14)], 1.0, t0, 40_000)
        self.assertEqual(why, ["tp1", "trailing"])
        imp = rules.impact(15.0, 40_000)
        self.assertAlmostEqual(res, (0.5 * 1.15 + 0.5 * 1.14) * (1 - imp) / 1.01 * 0.99 * (1 - imp) - 1, places=4)
        res, why = rules.simulate([(t0 + 60, 0.88)], 1.0, t0, 40_000)
        self.assertEqual(why, ["stop"])
        self.assertLess(res, -0.12)                                        # gapped under the stop, plus the cost
        self.assertEqual(rules.simulate([(t0 + 60, 1.05)], 1.0, t0)[0], None)   # not over yet

    def test_ev_math_and_the_break_even_is_50_not_45(self):
        self.assertAlmostEqual(rules.break_even_p(0.15, 0.10, 0.025), 0.5)
        self.assertAlmostEqual(rules.ev(0.5, 0.15, 0.10, 0.025), 0.0)
        self.assertLess(rules.ev(0.45, 0.15, 0.10, 0.025), 0)              # 45 % loses money after costs
        c = rules.round_trip_cost(15.0, 40_000)
        self.assertAlmostEqual(c, 0.02 + 2 * 15 / (20_000 + 15))
        self.assertTrue(0.02 < c < 0.03)


# ---------------------------------------------------------------------------------------------------------------
class DataJob(Base):
    def setUp(self):
        super().setUp()
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.hype = os.path.join(self.d.name, "hype.db")
        env = mock.patch.dict(os.environ, {"MOMENTUM_DB": os.path.join(self.d.name, "momentum.db"),
                                           "MOM_HYPE_DB": self.hype})
        env.start()
        self.addCleanup(env.stop)
        self.now = 1_800_000_000 - 1_800_000_000 % 60
        hype_db(self.hype, self.now, TOK)
        for obj, name, val in ((data, "candidates", lambda con, now, extra=(): list(extra) + [TOK, TOK2]),
                               (job, "_sol_usd", lambda: 100.0),
                               (data, "free_top10", lambda tok, now: (20.0, "test")),
                               (data, "shill_handles", lambda: set())):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.gt_calls = []

    def mode(self, m, name="momentum_scalp"):
        settings.put(self.con, f"flag:{name}", {"mode": m, "since": self.now})
        settings._FLAG_CACHE.clear()

    def gt(self, pools):
        self.gt_calls.append(list(pools))
        return {"data": [{"attributes": {"address": p, "transactions": {
            "m5": {"buys": 60, "sells": 20, "buyers": 8, "sellers": 6},
            "h1": {"buys": 900, "sells": 700, "buyers": 60, "sellers": 50}}, "volume_usd": {"h1": "20000"}}}
            for p in pools]}

    def pass_at(self, now, px=P, ch=10.0, rug=None):
        fetch = lambda toks: [pair(TOK, px, px * 1e9, ch=ch), pair(TOK2, px, px * 1e9)]  # noqa: E731
        return job.once(now=now, log=lambda s: None, fetch=fetch, gt_fetch=self.gt,
                        rug_src=rug or (lambda t, m, l_: {"level": "ok"}))

    def test_flag_off_fetches_nothing(self):
        self.assertEqual(job.once(now=self.now, fetch=lambda t: self.fail("no fetch while off")), "off")
        self.assertFalse(os.path.exists(os.environ["MOMENTUM_DB"]))

    def test_base_rate_logs_every_signal_and_its_outcome(self):
        self.mode("shadow")
        self.pass_at(self.now)
        con = data.connect()
        sig = data.open_signals(con)
        self.assertEqual([s["token"] for s in sig], [TOK])                  # TOK2: GeckoTerminal says bots
        f = json.loads(sig[0]["features"])
        self.assertEqual((f["buyers_in"]["how"], f["buyers_in"]["now"], f["top10"]), ("pumpportal", 40, 20.0))
        lp = data.kv_get(con, "last_pass")
        self.assertEqual([(n["token"], n["failed"]) for n in lp["near"]], [(TOK2, "wash")])
        self.assertEqual(self.gt_calls, [["POOL" + TOK2[:8]]])              # one request for the uncovered token
        self.assertEqual(data.day_used(con, "gt_day", self.now), 1)
        # the same jump a minute later is not a second signal; then +16 %, +25 %, back to +14 %: TP1 then trailing
        self.pass_at(self.now + 60)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 1)
        self.pass_at(self.now + 300, px=P * 1.16, ch=30.0)
        self.assertEqual(con.execute("SELECT status FROM signals").fetchone()[0], "open")   # trailing still running
        self.pass_at(self.now + 600, px=P * 1.25, ch=30.0)
        self.pass_at(self.now + 900, px=P * 1.14, ch=-8.0)
        r = con.execute("SELECT status, first, hit, sim_ret FROM signals").fetchone()
        self.assertEqual(r[:3], ("done", "tp", 1))
        self.assertGreater(r[3], 0.10)
        b = view.base_rate(self.now + 900)
        self.assertEqual((b["n"], b["hits"], b["hit_rate"]), (1, 1, 1.0))
        self.assertAlmostEqual(b["break_even_hit"], 0.5, delta=0.02)
        con.close()

    def test_a_stop_and_the_45_minutes(self):
        self.mode("shadow")
        self.pass_at(self.now)
        self.pass_at(self.now + 120, px=P * 0.89, ch=-11.0)
        con = data.connect()
        self.assertEqual(con.execute("SELECT first, hit FROM signals").fetchone(), ("sl", 0))
        con.execute("DELETE FROM signals")
        con.commit()
        hype_db(self.hype, self.now + 3000, TOK)                             # fresh buyers 50 min later
        self.pass_at(self.now + 3000)                                           # a new signal (cooldown over)
        self.pass_at(self.now + 3000 + 46 * 60, px=P * 1.02, ch=1.0)
        self.assertEqual(con.execute("SELECT first, hit FROM signals WHERE status='done'").fetchall(), [("time", 0)])
        con.close()

    def test_rug_risk_and_the_shill_network_are_near_misses(self):
        self.mode("shadow")
        self.pass_at(self.now, rug=lambda t, m, l_: {"level": "risk", "risk": ["rug filter: visok rizik"]})
        con = data.connect()
        lp = data.kv_get(con, "last_pass")
        self.assertIn((TOK, "rug"), [(n["token"], n["failed"]) for n in lp["near"]])
        with mock.patch.object(data, "shill_calls", lambda tok, now, h: {"paidguy"}):
            self.pass_at(self.now)
        lp = data.kv_get(con, "last_pass")
        self.assertIn((TOK, "shill"), [(n["token"], n["failed"]) for n in lp["near"]])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)
        con.close()

    def test_gecko_day_cap(self):
        self.mode("shadow")
        with mock.patch.object(data, "GT_DAY", 0):
            self.pass_at(self.now)
        self.assertEqual(self.gt_calls, [])
        con = data.connect()
        lp = data.kv_get(con, "last_pass")
        self.assertIn("ne može provjeriti", [n["why"] for n in lp["near"] if n["token"] == TOK2][0])
        con.close()


# ---------------------------------------------------------------------------------------------------------------
class TradeBase(Base):
    def setUp(self):
        super().setUp()
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        env = mock.patch.dict(os.environ, {"MOMENTUM_DB": os.path.join(self.d.name, "momentum.db")})
        env.start()
        self.addCleanup(env.stop)
        for obj, name, val in ((copy, "_concentration", lambda tok: (None, "nepoznato")),
                               (copy, "_rugged", lambda *a, **k: None)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        trade._CACHE.update(off_at=0.0, off_open=False, gate_log=0.0)
        trade._SHADOWED.clear()
        gate._CACHE.update(at=0.0, path=None, val=None)
        from league import exitplan
        exitplan._LAST.clear()
        self.now = int(time.time())
        self.lim = {"size_sol": 0.1, "max_sol_per_day": 1.0, "max_open": 5, "dca_token_cap": 0.3}

    def mode(self, m, name="momentum_scalp", since=None):
        settings.put(self.con, f"flag:{name}", {"mode": m, "since": since or self.now})
        settings._FLAG_CACHE.clear()

    def sig(self, sid=1, px=P, ts=None):
        return {TOK: {"id": sid, "token": TOK, "ts": ts or self.now, "price": px, "symbol": "MOM",
                      "features": {"ch_m5": 10.0}}}

    def mk(self, px, mcap=None, extra=None):
        return lambda toks: {t: (px, 50_000.0, None, mcap or px * 1e9, "MOM", extra or {"m5": 10.0}) for t in toks}

    def enter(self, px=P, sigs=None, **kw):
        return trade.run_once(self.lg, self.mk(px, **kw), self.now, sigs or self.sig(), self.lim, 100.0)

    def exits(self, px, now):
        return trade.exits_once(self.lg, lambda toks: {t: (px, 50_000.0, None, px * 1e9) for t in toks}, now)

    def lots(self, user=PU, status="open"):
        return [dict(r) for r in self.lg.execute("SELECT * FROM trades WHERE user=? AND token=? AND status=? ORDER BY id",
                                                 (user, TOK, status))]


class Paper(TradeBase):
    def test_flag_off_does_nothing(self):
        self.assertEqual(self.enter(), [])
        self.assertEqual(self.exits(P * 0.5, self.now), [])
        self.assertIsNone(self.lg.execute("SELECT 1 FROM sqlite_master WHERE name='momentum_trades'").fetchone())

    def test_paper_trades_only_the_demo_account_and_the_real_one_logs(self):
        self.mode("paper")
        done = self.enter()
        self.assertEqual([u for u, _ in done], [PU])
        lots = self.lots(PU)
        self.assertEqual((len(lots), lots[0]["source"], lots[0]["auto"]), (1, trade.SRC, None))
        self.assertAlmostEqual(lots[0]["size_usd"], 10.0)                    # size_sol 0.1 x $100
        self.assertEqual(self.lots(LU), [])
        self.assertEqual([(r[3], r[5]) for r in flags.shadow_rows(self.lg, "momentum_scalp")], [(TOK, "momentum ulaz")])
        self.assertEqual(self.enter(), [])                                   # one trade per signal and token

    def test_shadow_nobody_trades_and_the_entry_guards(self):
        self.mode("shadow")
        self.assertEqual(self.enter(), [])
        self.assertEqual(self.lots(PU) + self.lots(LU), [])
        self.mode("paper")
        self.assertEqual(self.enter(px=P * 1.06), [])                        # ran 6 % past the signal: no chase
        self.assertEqual(self.enter(mcap=25_000.0), [])                      # under 30k
        self.assertEqual(self.enter(extra={"src": "jup"}), [])               # the bonding curve
        old = self.sig(ts=self.now - 300)
        self.assertEqual(self.enter(sigs=old), [])                           # a stale signal
        with mock.patch.object(copy, "_concentration", lambda tok: ("koncentriran supply", "")):
            self.assertEqual(self.enter(), [])
        self.assertEqual(self.lots(PU), [])

    def test_exits_tp1_trailing_and_the_real_account_untouched(self):
        self.mode("paper")
        store.buy(self.lg, LU, TOK, "MOM", 25, P, 50_000, "copy KOL x", None, 100_000)   # the real account's own copy
        self.enter()
        t0 = trade.trades(self.lg)[0]["opened_ts"]
        out = self.exits(P * 1.16, t0 + 60)
        self.assertIn("pola van", out[0])
        self.assertEqual(len(self.lots(PU)), 1)                              # half still open
        self.assertEqual(self.exits(P * 1.30, t0 + 120), [])
        out = self.exits(P * 1.19, t0 + 180)
        self.assertIn("trailing", out[0])
        r = trade.trades(self.lg, "closed")[0]
        self.assertEqual((r["hit"], r["exit_reason"]), (1, "trailing"))
        self.assertGreater(r["ret"], 0.1)
        self.assertEqual(self.lots(PU), [])
        self.assertEqual(len(self.lots(LU)), 1)                              # never touched
        self.assertEqual(self.lots(LU)[0]["source"], "copy KOL x")

    def test_stop_and_time(self):
        self.mode("paper")
        self.enter()
        t0 = trade.trades(self.lg)[0]["opened_ts"]
        self.assertIn("stop", self.exits(P * 0.89, t0 + 30)[0])
        r = trade.trades(self.lg, "closed")[0]
        self.assertEqual((r["hit"], r["exit_reason"]), (0, "stop"))
        self.enter(sigs=self.sig(sid=2))
        t1 = trade.trades(self.lg)[0]["opened_ts"]
        self.assertEqual(self.exits(P * 1.03, t1 + 600), [])
        self.assertIn("45 min", self.exits(P * 1.03, t1 + 45 * 60)[0])

    def test_flag_off_keeps_the_exits_of_open_trades(self):
        self.mode("paper")
        self.enter()
        self.mode("off")
        trade._CACHE.update(off_at=0.0)
        self.assertIn("stop", self.exits(P * 0.8, self.now + 30)[0])


class LiveGate(TradeBase):
    def rows(self, n, ret, hit):
        trade.ensure(self.lg)
        for i in range(n):
            self.lg.execute("INSERT INTO momentum_trades (user, token, opened_ts, closed_ts, status, size_usd, pnl_usd, "
                            "ret, hit) VALUES (?,?,?,?,?,?,?,?,?)", (PU, f"T{i}", 1, 2, "closed", 10.0, 10 * ret, ret, hit))
        self.lg.commit()
        gate._CACHE.update(at=0.0)

    def test_50_trades_ev_and_hit_rate(self):
        self.assertIn("tek 0", gate.refusal())
        self.rows(49, 0.05, 1)
        self.assertIn("tek 49", gate.refusal())
        self.rows(1, 0.05, 1)
        self.assertIsNone(gate.refusal())
        self.rows(70, 0.01, 0)                                               # EV still > 0, hit 50/120 = 42 %
        self.assertIn("pogodak", gate.refusal())
        self.rows(200, -0.05, 1)
        self.assertIn("EV", gate.refusal())

    def test_set_flag_live_goes_through_live_gates(self):
        self.assertEqual(settings.LIVE_GATES["momentum_scalp"], "momentum.gate:live_refusal")
        settings.put(self.con, "backtest:momentum_scalp", {"pass": True, "n": 60, "ev_lo": 1.0})
        self.mode("paper", since=self.now - 8 * 86400)
        paper = {"n": 25, "pnl": 12.0}
        with self.assertRaisesRegex(ValueError, "tek 0 zatvorenih paper tradeova"):
            settings.set_flag(self.con, "momentum_scalp", "live", "Jure", paper=paper, now=self.now)
        self.rows(50, 0.04, 1)
        self.assertEqual(settings.set_flag(self.con, "momentum_scalp", "live", "Jure", paper=paper, now=self.now)["mode"],
                         "live")

    def test_live_without_proof_trades_only_the_demo_account_and_run_trade_refuses(self):
        self.mode("live")
        self.assertEqual(trade.roles("live", self.now), ([PU], [LU]))
        self.assertIn("tek 0", run_trade._momentum_gate())
        done = self.enter()
        self.assertEqual([u for u, _ in done], [PU])
        self.assertEqual(self.lots(LU), [])
        self.rows(50, 0.04, 1)
        self.assertEqual(sorted(trade.roles("live", self.now)[0]), sorted([LU, PU]))
        gate._CACHE.update(at=0.0)
        self.assertIsNone(run_trade._momentum_gate())

    def test_flags_are_at_the_end_with_croatian_labels(self):
        names = list(settings.FLAGS)
        self.assertLess(names.index("insider_copy"), names.index("momentum_scalp"))
        self.assertEqual(settings.FLAGS["momentum_scalp"][0], "G16")
        self.assertEqual(settings.FLAGS["grok_ev_gate"][0], "G17")
        self.assertIn("pola van", settings.FLAGS["momentum_scalp"][1])
        self.assertEqual(settings.flag("grok_ev_gate", con=self.con), "off")
        self.assertNotIn("grok_ev_gate", settings.DATA_FLAGS)


# ---------------------------------------------------------------------------------------------------------------
class Backtest(unittest.TestCase):
    def series(self, after):
        """60 quiet minutes, a 5-minute jump to +10 % on heavy buying, then `after` (minute, price multiple) points."""
        t0, out = 1_800_000_000, []
        px = 1e-4
        for k in range(60):
            out.append((t0 + k * 60, px, px, px, px, 200.0, 2, 2))
        for k in range(5):
            p2 = px * (1 + 0.02 * (k + 1))
            out.append((t0 + (60 + k) * 60, out[-1][4], p2, out[-1][4], p2, 1500.0, 9, 2))
        last = out[-1][4]
        for m, mult in after:
            p3 = last * mult
            out.append((t0 + (65 + m) * 60, out[-1][4], max(out[-1][4], p3), min(out[-1][4], p3), p3, 300.0, 3, 3))
        return out

    def test_a_jump_is_a_signal_and_its_outcome(self):
        cs = self.series([(1, 1.05), (2, 1.16), (3, 1.30), (4, 1.18)] + [(m, 1.18) for m in range(5, 50)])
        sigs = backtest.simulate_token(cs, 1e9, 50_000)
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual((s["first"], s["hit"], s["buy_share_how"]), ("tp", 1, "transakcije"))
        self.assertEqual(s["exits"], ["tp1", "trailing"])
        self.assertGreater(s["ret"], 0.1)
        rep = backtest.run_tokens({TOK: (cs, 1e9, 50_000, "MOM")})
        self.assertEqual(rep["variants"]["osnovno"]["signals"], 1)
        self.assertAlmostEqual(rep["variants"]["osnovno"]["break_even_hit"], 0.5, delta=0.02)
        self.assertIn("pogodak", backtest.md(rep))

    def test_a_loser_and_what_is_not_a_signal(self):
        cs = self.series([(1, 0.95), (2, 0.85)] + [(m, 0.9) for m in range(3, 50)])   # 0.85 x 1.10 < 1.06 x 0.9
        s = backtest.simulate_token(cs, 1e9, 50_000)[0]
        self.assertEqual((s["first"], s["hit"], s["exits"]), ("sl", 0, ["stop"]))
        self.assertEqual(backtest.simulate_token(cs, 1e7, 50_000), [])        # MC $1k: under 30k
        self.assertEqual(backtest.simulate_token(cs, 1e9, 10_000), [])        # liquidity $10k
        flat = [(c[0], c[1], c[2], c[3], c[4], 200.0, c[6], c[7]) for c in cs]
        self.assertEqual(backtest.simulate_token(flat, 1e9, 50_000), [])      # no volume spike
        no_tx = [(c[0], c[1], c[2], c[3], c[4], c[5], None, None) for c in cs]
        self.assertEqual(backtest.simulate_token(no_tx, 1e9, 50_000, proxy=False), [])
        self.assertEqual(backtest.simulate_token(no_tx, 1e9, 50_000)[0]["buy_share_how"], "proxy")


# ---------------------------------------------------------------------------------------------------------------
class EvGate(Base):
    def setUp(self):
        super().setUp()
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.mk = {}
        good = (1.0, 50_000.0, None, 100_000.0, "HOPE", {"src": "dex"})
        for p in (mock.patch.object(copy, "market", lambda toks: {t: self.mk.get(t, good) for t in toks}),
                  mock.patch.object(copy, "_rugged", lambda *a: None),
                  mock.patch.object(copy, "_concentration", lambda t: (None, "nepoznato")),
                  mock.patch.object(grokauto, "TX_WAIT_S", 0.0),
                  mock.patch("rangedca.trade.sol_usd", lambda: 100.0),
                  mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "",
                                               "MOMENTUM_DB": os.path.join(self.d.name, "momentum.db")})):
            p.start()
            self.addCleanup(p.stop)
        settings.put(self.con, "max_sol_per_trade", 0.5)
        settings.put(self.con, "size_sol", 0.1)
        self.post("/pravi-trade/grokon", {})

    def mode(self, m):
        settings.put(self.con, "flag:grok_ev_gate", {"mode": m, "since": int(time.time())})
        settings._FLAG_CACHE.clear()

    def ask(self, tok=MINT, amount=0.05, side="buy", **kw):
        return mcpapi.trade_request(dict({"token": tok, "side": side, "amount": amount, "require_approval": False,
                                          "reason": "test"}, **kw))

    def calib(self):
        con = data.ro()
        if con is None:
            return []
        try:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute("SELECT * FROM calib ORDER BY id")]
        finally:
            con.close()

    def test_backwards_compatible_and_off_records_only(self):
        code, out = self.ask()
        self.assertEqual((code, out["status"]), (200, "executed"))
        self.assertEqual(self.calib(), [])                                   # nothing sent, nothing recorded
        code, out = self.ask(MINT[:-1] + "8", p_tp=0.3, strategy="momentum_scalp")
        self.assertEqual(out["status"], "executed")                          # off never refuses
        c = self.calib()
        self.assertEqual((c[0]["strategy"], c[0]["p_tp"], c[0]["decision"], c[0]["request"]),
                         ("momentum_scalp", 0.3, "would_reject", "executed"))
        self.assertAlmostEqual(c[0]["tp_pct"], 15.0)
        self.assertAlmostEqual(c[0]["sl_pct"], 10.0)
        self.assertTrue(2.0 < c[0]["cost_pct"] < 3.0)

    def test_shadow_logs_what_it_would_refuse(self):
        self.mode("shadow")
        code, out = self.ask(p_tp=0.3, strategy="momentum_scalp")
        self.assertEqual(out["status"], "executed")
        self.assertEqual(self.calib()[0]["decision"], "shadow_reject")
        self.assertEqual([r[5] for r in flags.shadow_rows(self.lg, "grok_ev_gate")], ["odbij (EV <= 0)"])

    def test_paper_refuses_ev_at_or_under_zero_and_a_buy_without_p_tp(self):
        self.mode("paper")
        code, out = self.ask(p_tp=0.3, strategy="momentum_scalp")
        self.assertEqual(out["status"], "rejected")
        self.assertIn("grok_ev_gate: EV", out["reason"])
        self.assertRegex(out["reason"], r"break-even p_tp 0\.(4|5)")
        self.assertEqual(self.calib()[0]["request"], "rejected")
        code, out = self.ask()
        self.assertIn("send p_tp", out["reason"])
        code, out = self.ask(p_tp=0.7)                                        # other: +15 / -60 -> break-even ~0.83
        self.assertIn("EV", out["reason"])
        code, out = self.ask(p_tp=0.9, strategy="range_dca")
        self.assertIn("no active range", out["reason"])
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, qty) "
                        "VALUES (?,?,?,?,?,?,?,?)", (LU, MINT, "X", 1, "open", 10, 1.0, 10))
        self.lg.commit()
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                         (MINT, int(time.time()), "dry", "open", 0.1))
        self.con.commit()
        self.assertEqual(self.ask(side="sell", amount=1.0)[1]["status"], "executed")   # sells are never gated

    def test_paper_passes_positive_ev_with_the_strategys_exit(self):
        self.mode("paper")
        code, out = self.ask(p_tp=0.7, strategy="momentum_scalp")
        self.assertEqual((code, out["status"]), (200, "executed"))
        a = json.loads(self.lg.execute("SELECT auto FROM trades WHERE id=?", (out["league_trade_id"],)).fetchone()[0])
        self.assertEqual((a.get("tp_in") or a.get("tp"), a.get("sl_in") or a.get("sl")), ("15%", "-10%"))
        self.assertEqual(self.calib()[0]["decision"], "pass")
        log = grokauto.log_rows(self.con)[0]
        self.assertEqual(log["ev_gate"]["strategy"], "momentum_scalp")

    def test_bad_fields_and_the_queued_request(self):
        self.assertEqual(self.ask(p_tp=1.5)[0], 400)
        self.assertEqual(self.ask(p_tp="x")[0], 400)
        self.assertEqual(self.ask(p_tp=0.6, strategy="yolo")[0], 400)
        code, out = mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05, "p_tp": 0.6,
                                          "strategy": "momentum_scalp"})
        self.assertEqual(code, 202)
        self.assertTrue(out["ev_gate"]["would_pass"])
        self.assertAlmostEqual(out["ev_gate"]["break_even_p_tp"], 0.5, delta=0.02)
        req = settings.raw(self.con)["mcp_requests"][-1]
        self.assertEqual((req["p_tp"], req["strategy"]), (0.6, "momentum_scalp"))
        self.assertEqual(self.calib()[-1]["request"], "pending_approval")
        code, out = mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05})
        self.assertEqual(code, 202)
        self.assertNotIn("ev_gate", out)                                     # old calls unchanged

    def test_the_tool_schema_and_instructions(self):
        t = {x["name"]: x for x in mcpapi.TOOLS}["execute_trade"]
        props = t["inputSchema"]["properties"]
        self.assertEqual(props["strategy"]["enum"], ["momentum_scalp", "range_dca", "other"])
        self.assertEqual((props["p_tp"]["minimum"], props["p_tp"]["maximum"]), (0, 1))
        self.assertEqual(t["inputSchema"]["required"], ["token_address", "amount", "side"])
        self.assertIn("p_tp", t["description"])
        self.assertIn("p_tp", mcpapi.INSTRUCTIONS)
        self.assertIn("momentum_candidates", mcpapi.INSTRUCTIONS)
        d, err = mcpapi._tool("execute_trade", {"token_address": MINT, "amount": 0.05, "side": "buy", "p_tp": 2})
        self.assertTrue(err)


class Calibration(unittest.TestCase):
    def test_brier_and_buckets(self):
        c = evgate.calibration([(0.8, 1), (0.8, 0), (0.3, 0), (0.3, 0)])
        self.assertEqual(c["n"], 4)
        self.assertAlmostEqual(c["brier"], (0.04 + 0.64 + 0.09 + 0.09) / 4, places=4)
        self.assertEqual([(b["p_from"], b["n"], b["hit_rate"]) for b in c["buckets"]], [(0.3, 2, 0.0), (0.8, 2, 0.5)])
        self.assertEqual(evgate.calibration([])["n"], 0)

    def test_resolve_tp_first_sl_first_and_the_horizon(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"MOMENTUM_DB": os.path.join(d, "m.db")}):
            now = 1_800_000_000
            lv = {"tp": 0.15, "sl": 0.10, "horizon_s": 2700, "from": "test"}
            for tok, p in ((TOK, 0.7), (TOK2, 0.6), (MINT[:-1] + "9", 0.4)):
                g = {"p_tp": p, "levels": lv, "price": 1.0, "cost": 0.025, "ev": 0.01, "mode": "off", "strategy": "momentum_scalp"}
                self.assertTrue(evgate.record(g, tok, 0.1, "executed", now))
            con = data.connect()
            for tok, path in ((TOK, (1.05, 1.16)), (TOK2, (0.95, 0.89))):
                for k, px in enumerate(path):
                    data.save_snap(con, tok, {"ts": now + 60 * (k + 1), "price": px, "mcap": px * 1e9, "liq": 5e4,
                                              "vol_m5": 1, "vol_h1": 1, "buys_m5": 1, "sells_m5": 1})
            con.commit()
            self.assertEqual(evgate.open_tokens(con).__len__(), 3)
            self.assertEqual(evgate.resolve(con, now + 300), 2)
            self.assertEqual(evgate.resolve(con, now + 2800), 1)               # no price: the horizon ends it, 0
            rows = dict(con.execute("SELECT token, hit FROM calib").fetchall())
            self.assertEqual((rows[TOK], rows[TOK2], rows[MINT[:-1] + "9"]), (1, 0, 0))
            con.close()
            rep = evgate.report(now + 3000)
            self.assertEqual(rep["all"]["n"], 3)
            self.assertAlmostEqual(rep["all"]["brier"], ((0.3 ** 2) + (0.6 ** 2) + (0.4 ** 2)) / 3, places=3)
            self.assertIn("momentum_scalp", rep["by_strategy"])
            self.assertIn("Brier", evgate.lines(rep)[0])

    def test_levels_per_strategy(self):
        lv, why = evgate.levels("momentum_scalp", TOK, 1.0)
        self.assertEqual((lv["tp"], lv["sl"], lv["horizon_s"], lv["exit"]), (0.15, 0.10, 2700, ("15%", "-10%")))
        rng = {TOK: {"active": True, "zones": {"range_low_low": 0.9, "range_low_top": 0.95, "range_high_low": 1.3,
                                               "range_high_top": 1.4}, "metrics": {"supply": 1e9}}}
        lv, why = evgate.levels("range_dca", TOK, 1.0, 1e9, ranges=rng)
        self.assertAlmostEqual(lv["tp"], 0.3)
        self.assertAlmostEqual(lv["sl"], 1 - 0.9 * 0.85)
        self.assertEqual(lv["exit"], ("$1300000000", "$765000000"))
        self.assertIsNone(evgate.levels("range_dca", TOK, 1.35, ranges=rng)[0])   # already in the top zone


# ---------------------------------------------------------------------------------------------------------------
class ReadSide(TradeBase):
    def test_mcp_brief_kandidati_and_report(self):
        con = data.connect()
        f = {"ch_m5": 9.0, "vol_x": 4.2, "buy_share": 0.72, "buyers_in": {"now": 30, "how": "pumpportal"},
             "wash_in": ORGANIC_WASH, "top10": 22.0, "rug_in": {"level": "ok"}}
        sid = data.add_signal(con, TOK, "MOM", self.now - 60, {"price": P, "mcap": 100_000, "liq": 50_000}, f, 0.022)
        data.kv_put(con, "last_pass", {"ts": self.now, "watched": 40, "prequalified": 2,
                                       "near": [{"token": TOK2, "failed": "wash", "why": "lažni volumen"}]})
        con.commit()
        con.close()
        p = mcpapi._momentum_part(self.now)
        self.assertEqual(p["signals"][0]["signal_id"], sid)
        self.assertEqual(p["signals"][0]["unique_buyers_5m"], 30)
        self.assertEqual(p["near_misses"]["near"][0]["token"], TOK2)
        self.assertIn("tek 0", p["paper_proof"]["live_gate"])
        from events import brief
        b = brief.momentum_part(self.now)
        self.assertNotIn("positions", b)
        self.assertEqual(b["signals"][0]["token"], TOK)
        self.assertIn("n_requests", brief.calibration_part(self.now))
        from ui import kandidati
        rows = kandidati.Sources().momentum(self.now)
        self.assertEqual(rows[0]["signal_id"], sid)
        rec = view.record(self.now)
        self.assertEqual(rec["n"], 0)
        rep = view.report_data(self.now)
        self.assertEqual(rep["signals_24h"], 1)
        text = "\n".join(view.lines(rep))
        self.assertIn("Momentum scalp", text)
        self.assertIn("ne 45 %", text)
        self.assertIn("Grok EV vrata", text)
        from report import collect
        self.assertIsNotNone(collect.momentum(self.now))

    def test_kandidati_exit_plan_for_a_momentum_row(self):
        from ui import kandidati
        plan = kandidati.exit_plan({"sources": {"momentum": {}}}, None, {"sl_default": 60}, None)
        self.assertEqual(plan["stop"], {"at_pct": -10})
        self.assertEqual(plan["trailing"], {"activate_pct": 15, "trail_pct": 8})


if __name__ == "__main__":
    unittest.main()
