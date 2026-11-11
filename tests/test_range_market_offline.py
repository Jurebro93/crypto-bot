"""11.11. (Jure: "širi range watchlist", flag range_market G20): the market watchlist of range_dca
(rangedca/market.py). A range is found from 5-minute (and 15-minute) DexScreener snapshots, the per-source day cap
drops the lowest-volume tokens first and logs one cost line a day, the source of every range (signal > event >
market), market / event tokens traded only on the demo account, the flags never go live, get_range_candidates'
new fields. No network.

    python3 -m unittest tests.test_range_market_offline
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import flags  # noqa: E402
from rangedca import data, detect, market, trade, view  # noqa: E402
from trade import settings  # noqa: E402
from tests.test_range_dca_offline import LU, MINT, PU, S, TradeBase  # noqa: E402

D = 86400


def snaps(t1, hours=12.0, step_min=5, lo=52.0, hi=98.0, period=120, vol_m5=5000.0):
    """DexScreener-like snapshots every step_min minutes of a clean range (lo -> hi -> lo every `period` minutes),
    the last one at t1."""
    out, half = [], period // 2
    n = int(hours * 60 // step_min)
    for i in range(n + 1):
        k = i * step_min
        ph = k % period
        px = (lo + (hi - lo) * ph / half if ph < half else hi - (hi - lo) * (ph - half) / half) * S
        out.append({"ts": t1 - (n - i) * step_min * 60, "price": px, "mcap": px * 1e9, "liq": 50_000.0,
                    "vol_m5": vol_m5, "vol_h1": vol_m5 * 12, "vol_h6": vol_m5 * 72, "buys_m5": 6, "sells_m5": 4,
                    "buys_h1": 72, "sells_h1": 48, "ch_m5": None})
    return out


def pair(tok, px=60e-6, mc=60_000.0, liq=30_000.0, vol_h1=60_000.0, created=None, dex="pumpswap"):
    p = {"chainId": "solana", "baseToken": {"address": tok, "symbol": tok[:4], "name": tok[:4]}, "priceUsd": str(px),
         "marketCap": mc, "dexId": dex, "pairAddress": "Pool" + tok[:8], "liquidity": {"usd": liq},
         "volume": {"m5": vol_h1 / 12, "h1": vol_h1, "h6": vol_h1 * 6},
         "txns": {"m5": {"buys": 6, "sells": 4}, "h1": {"buys": 60, "sells": 40}}, "priceChange": {"m5": 1.0}}
    if created:
        p["pairCreatedAt"] = int(created * 1000)
    return p


class Net:
    """rangedca/market.Net stand-in: records every DexScreener batch it is asked."""

    def __init__(self, pairs=None):
        self.asked, self.pairs_by = [], dict(pairs or {})

    def pairs(self, tokens):
        self.asked.append(list(tokens))
        return [self.pairs_by[t] for t in tokens if t in self.pairs_by]

    def lists(self):
        return []

    def gt_pools(self):
        return []

    def birdeye_list(self):
        return None


class RDB(unittest.TestCase):
    """A range.db of its own, no network, no meter writes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"RANGE_DB": os.path.join(self.tmp.name, "range.db"),
               "RANGE_HYPE_DB": os.path.join(self.tmp.name, "hype.db"),
               "TOPICS_DB": os.path.join(self.tmp.name, "topics.db")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("BIRDEYE_API_KEY", None)
        for obj, name, val in ((market, "_meter", lambda *a, **k: None), (market, "from_graduates", lambda con, now: 0),
                               (market, "from_scanner", lambda con, now, scan_db=None: 0)):
            pm = mock.patch.object(obj, name, val)
            pm.start()
            self.addCleanup(pm.stop)
        self.con = data.connect()
        market.ensure(self.con)
        self.addCleanup(self.con.close)


# ---------------------------------------------------------------------------------------------------------------
class FiveMinuteSnapshots(RDB):
    def test_a_range_is_found_from_5_minute_snapshots(self):
        now = 1_794_400_000 - 1_794_400_000 % 60
        tok = "R" * 43 + "pump"
        for s in snaps(now):
            data.save_snap(self.con, tok, dict(s, pool=None))
        candles, snap = data.series(self.con, tok, now)
        self.assertEqual(len(candles), 12 * 12 + 1)                       # one candle per snapshot, not per minute
        self.assertEqual(candles[1][0] - candles[0][0], 300)
        self.assertAlmostEqual(candles[5][5], 5000.0)                    # a 5-minute candle carries 5 minutes
        self.assertAlmostEqual(snap["vol_15m"], 15_000.0)                # t, t-5, t-10
        r = detect.analyze(candles, now, snap)
        self.assertEqual(r["status"], detect.ACTIVE, r["why"])
        self.assertAlmostEqual(r["zones"]["range_low"] / S, 52, delta=1.5)
        self.assertAlmostEqual(r["zones"]["range_high"] / S, 98, delta=1.5)
        self.assertGreaterEqual(r["components"]["recoveries"]["score"], 0.6)
        self.assertGreaterEqual(r["components"]["volume_hold"]["score"], 1.0)
        self.assertGreater(r["score"], 0.7)

    def test_15_minute_snapshots_still_find_it_and_carry_the_volume_of_15_minutes(self):
        now = 1_794_400_000 - 1_794_400_000 % 60
        tok = "Q" * 43 + "pump"
        for s in snaps(now, step_min=15, period=240):
            data.save_snap(self.con, tok, dict(s, pool=None))
        candles, snap = data.series(self.con, tok, now)
        self.assertAlmostEqual(candles[3][5], 5000 + (60_000 - 5000) / 55 * 10)   # 15 minutes, not 5
        self.assertAlmostEqual(candles[3][6], (6 + (72 - 6) / 55 * 10))          # buys of 15 minutes
        self.assertAlmostEqual(snap["vol_15m"], 15_000.0)                         # the last 5 min + 10 at the hour's rate
        r = detect.analyze(candles, now, snap)
        self.assertEqual(r["status"], detect.ACTIVE, r["why"])

    def test_the_minute_series_is_unchanged(self):
        real = [(1000 * 60, 1.0, 1.2, 0.9, 1.1, 500.0)]
        sn = [{"ts": 1000 * 60 + 5, "price": 1.15, "vol_m5": 1000, "vol_h1": 9000, "buys_m5": 10, "sells_m5": 5},
              {"ts": 1003 * 60, "price": 1.2, "vol_m5": 1500, "vol_h1": 9000, "buys_m5": 5, "sells_m5": 5}]
        cs = data.merge(real, sn)
        self.assertEqual(cs[1][5], 1500 / 5 * 3)                       # gaps up to 5 minutes as before


# ---------------------------------------------------------------------------------------------------------------
class Budget(RDB):
    def watch(self, n, now):
        toks = [f"T{i:03d}" + "x" * 39 for i in range(n)]
        for i, t in enumerate(toks):
            self.con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, vol_h1) "
                             "VALUES (?,?,?,?,?,1,?)", (t, "gt", "market", now - D, now, 1000.0 * (i + 1)))
        self.con.commit()
        return toks

    def test_cap_drops_the_lowest_volume_first_and_logs_one_cost_line_a_day(self):
        day0 = 1_794_355_200                       # 00:00 UTC
        now = day0 + 23 * 3600 + 1800              # 23:30: the whole day's cap is open
        toks = self.watch(70, now)
        net = Net({t: pair(t, created=now - 3 * D) for t in toks})
        logs = []
        with mock.patch.object(market, "DEX_DAY", 1):
            out = market.pass_once(self.con, now, net, logs.append, pulse=set(), event_on=False)
        self.assertEqual(len(net.asked), 1)
        top30 = sorted(toks, key=lambda t: -int(t[1:4]))[:30]
        self.assertEqual(sorted(net.asked[0]), sorted(top30))              # the 30 most traded
        self.assertEqual(out["stats"]["dropped"], 40)
        self.assertTrue(any("preskočeno 40 tokena najmanjeg volumena" in x for x in logs), logs)
        self.assertEqual(data.day_used(self.con, "mkt_dex_day", now), 1)
        n_snaps = self.con.execute("SELECT COUNT(DISTINCT token) FROM snaps").fetchone()[0]
        self.assertEqual(n_snaps, 30)
        self.assertFalse([x for x in logs if "trošak" in x])                # no cost line before the day ends
        logs.clear()
        with mock.patch.object(market, "DEX_DAY", 1):
            market.pass_once(self.con, now + 3600, net, logs.append, pulse=set(), event_on=False)
        line = [x for x in logs if x.startswith("range watchlist trošak")]
        self.assertEqual(len(line), 1, logs)
        self.assertIn(time.strftime("%Y-%m-%d", time.gmtime(now)), line[0])
        gt = f"gt {market.gt_requests()}/{market.GT_DAY}"   # 11.11.: GT_TOP_PAGES + 2 x GT_TREND_PAGES a round
        for part in ("dexscreener 1/1", "dexscreener liste 3/300", gt, "birdeye 0/24 (bez ključa)"):
            self.assertIn(part, line[0])
        logs.clear()
        with mock.patch.object(market, "DEX_DAY", 1):
            market.pass_once(self.con, now + 3700, net, logs.append, pulse=set(), event_on=False)
        self.assertFalse([x for x in logs if x.startswith("range watchlist trošak")])   # once a day

    def test_the_budget_is_sliced_by_the_hour(self):
        day0 = 1_794_355_200
        self.assertEqual(market.slice_left(self.con, "mkt_dex_day", 2400, day0 + 60), 100)      # hour 0: 1/24
        data.day_add(self.con, "mkt_dex_day", 100, day0 + 60)
        self.assertEqual(market.slice_left(self.con, "mkt_dex_day", 2400, day0 + 1800), 0)
        self.assertEqual(market.slice_left(self.con, "mkt_dex_day", 2400, day0 + 3600 + 60), 100)

    def test_hot_tokens_every_5_min_the_rest_every_15_and_the_hype_scan_is_reused(self):
        now = 1_794_355_200 + 23 * 3600
        toks = self.watch(5, now)
        self.con.execute("UPDATE mkt SET last_snap=?", (now - 400,))      # 6.7 min ago
        self.con.commit()
        net = Net({t: pair(t, created=now - 3 * D) for t in toks})
        with mock.patch.object(market, "HOT_N", 2):
            out = market.pass_once(self.con, now, net, print, pulse={toks[4]}, event_on=False)
        self.assertEqual(sorted(net.asked[0]), sorted(toks[3:4]))           # toks[4] hot but in the hype scan
        self.assertEqual(out["stats"]["reused"], 1)

    def test_the_market_filter(self):
        now = 1_794_400_000
        ok = {"price": 1e-4, "bonded": True, "mcap": 200_000, "liq": 40_000, "vol_h1": 20_000}
        self.assertTrue(market.check(ok, now - 7 * 3600, "market", now)[0])
        for change, word in (({"mcap": 40_000}, "ispod $50,000"), ({"mcap": 6e6}, "iznad"), ({"liq": 14_000}, "likvidnost"),
                             ({"vol_h1": 5000}, "volumen"), ({"bonded": False}, "krivulji"), ({"mcap": 20_000}, "30k")):
            res = market.check({**ok, **change}, now - 7 * 3600, "market", now)
            self.assertFalse(res[0], change)
            self.assertIn(word, res[1])
        self.assertTrue(market.check({**ok, "liq": 15_000}, now - 7 * 3600, "market", now)[0])   # 11.11.: $15k is enough
        young = market.check(ok, now - 3 * 3600, "market", now)
        self.assertFalse(young[0])
        self.assertAlmostEqual(young[2], 3 * 3600 + 60, delta=1)            # back when 6 h old
        self.assertTrue(market.check({**ok, "mcap": 35_000, "vol_h1": 100}, now - 600, "event", now)[0])   # 30k rule
        self.assertFalse(market.check({**ok, "mcap": 25_000}, now - 600, "event", now)[0])

    def test_admission_from_gt_numbers_and_a_full_list_keeps_the_most_traded(self):
        now = 1_794_355_200 + 23 * 3600
        with mock.patch.object(market, "MARKET_MAX", 2):
            toks = self.watch(2, now)                                      # vol 1000, 2000
            self.con.execute("UPDATE mkt SET last_snap=?", (now,))
            new = "N" * 43 + "pump"
            market.add(self.con, new, "gt", now, nums={"vol_h1": 50_000})
            self.con.commit()
            net = Net({new: pair(new, vol_h1=50_000, created=now - 2 * D)})
            out = market.pass_once(self.con, now, net, print, pulse=set(), event_on=False)
        self.assertIn(new, out["tokens"])
        self.assertNotIn(toks[0], out["tokens"])                           # the quietest one made room
        self.assertEqual(len(out["tokens"]), 2)


# ---------------------------------------------------------------------------------------------------------------
class Sources(unittest.TestCase):
    def test_priority_signal_event_market(self):
        self.assertEqual(view.source_of(["market", "event"]), ("event", ["event", "market"]))
        self.assertEqual(view.source_of(["market", "signal", "event"]), ("signal", ["signal", "event", "market"]))
        self.assertEqual(view.source_of(["market"]), ("market", ["market"]))
        self.assertEqual(view.source_of([]), ("signal", ["signal"]))

    def test_breakout_and_entry_ready_names_from_main(self):
        self.assertEqual(view.BREAKOUT, "breakout")                      # noc/popravci (#117): above 100 % of the range
        self.assertTrue(view.is_breakout({"pos_pct": 138}))
        self.assertFalse(view.is_breakout({"pos_pct": 40}))


class Job(TradeBase):
    """run_range.once with the signal pass, the market list and an event topic together."""

    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"TOPICS_DB": os.path.join(self.rdir.name, "topics.db")})
        p.start()
        self.addCleanup(p.stop)
        for obj, name, val in ((market, "_meter", lambda *a, **k: None), (market, "from_graduates", lambda con, now: 0),
                               (market, "from_scanner", lambda con, now, scan_db=None: 0)):
            pm = mock.patch.object(obj, name, val)
            pm.start()
            self.addCleanup(pm.stop)
        self.addCleanup(settings._FLAG_CACHE.clear)

    def test_every_range_carries_its_source_and_get_range_candidates_shows_it(self):
        import run_range
        from topics import store as tstore
        now = self.now - self.now % 60
        SIG, MKT, EVT, BOTH = MINT, "M" * 43 + "pump", "E" * 43 + "pump", "B" * 43 + "pump"
        con = data.connect()
        market.ensure(con)
        for tok in (SIG, MKT, EVT, BOTH):
            for s in snaps(now):
                data.save_snap(con, tok, dict(s, pool="Pool" + tok[:8], dex="pumpswap", symbol=tok[:4]))
        for tok in (MKT, BOTH):
            con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, last_snap, vol_h1) VALUES "
                        "(?,?,?,?,?,1,?,?)", (tok, "gt", "market", now - D, now, now, 60_000.0))
        con.commit()
        con.close()
        tc = tstore.connect()
        tc.execute("INSERT INTO event_topics (name, name_key, keywords, status, created_ts, updated_ts) VALUES "
                   "('GTA6', 'gta6', '[\"GTA6\"]', 'upcoming', ?, ?)", (now, now))
        tc.execute("INSERT INTO topic_tokens (topic_id, token, first_seen, role) VALUES (1, ?, ?, 'other')", (EVT, now))
        tc.commit()
        tc.close()
        self.mode("paper")
        self.mode("shadow", "range_market")
        self.mode("shadow", "event_tokens")
        last = snaps(now)[-1]
        prs = {t: pair(t, px=last["price"], mc=last["mcap"], liq=50_000, created=now - 3 * D) for t in (SIG, MKT, EVT, BOTH)}
        net = Net(prs)
        out = run_range.once(now=now, log=lambda *_: None, fetch=lambda toks: [prs[t] for t in toks if t in prs],
                             gt_fetch=lambda *a: None, post=lambda *a: {}, extra=[SIG, BOTH], net=net)
        self.assertIn("eventi 1", out)
        con = data.connect()
        got = {t: data.load_range(con, t)[0] for t in (SIG, MKT, EVT, BOTH)}
        srcs = dict(con.execute("SELECT token, src FROM ranges"))
        con.close()
        self.assertEqual({t: (r["source"], r["sources"]) for t, r in got.items()},
                         {SIG: ("signal", ["signal"]), MKT: ("market", ["market"]), EVT: ("event", ["event"]),
                          BOTH: ("signal", ["signal", "market"])})
        self.assertEqual((srcs[MKT], srcs[EVT], srcs[BOTH]), ("market", "event", "signal"))
        for t, r in got.items():
            self.assertEqual(r["status"], detect.ACTIVE, (t, r["why"]))
        d = view.candidates(min_score=0.3, now=now)
        rows = {c["token"]: c for c in d["candidates"]}
        self.assertEqual(rows[EVT]["source"], "event")
        self.assertEqual(rows[BOTH]["sources"], ["signal", "market"])
        self.assertTrue(rows[MKT]["paper_only"])
        self.assertFalse(rows[BOTH]["paper_only"])
        for c in d["candidates"]:
            self.assertIn("entry_ready", c)
        ready = [c["entry_ready"] for c in d["candidates"]]
        self.assertEqual(ready, sorted(ready, reverse=True))               # entry-ready rows first
        self.assertEqual(d["watched_by_source"], {"signal": 2, "event": 1, "market": 1})
        self.assertIn("cost_today", d["watchlist"])
        only = view.candidates(min_score=0.3, now=now, source="market")
        self.assertEqual({c["token"] for c in only["candidates"]}, {MKT, BOTH})
        self.assertIn("error", view.candidates(source="nesto"))
        from ui import mcpapi
        t = {x["name"]: x for x in mcpapi.TOOLS}["get_range_candidates"]
        self.assertEqual(t["inputSchema"]["properties"]["source"]["enum"], ["signal", "market", "event"])
        res, err = mcpapi._tool("get_range_candidates", {"min_score": 0.3, "source": "event"})
        self.assertFalse(err, res)

    def test_all_three_flags_off_nothing_runs(self):
        import run_range
        self.assertEqual(run_range.once(now=self.now, net=Net(), fetch=lambda t: self.fail("no fetch")), "off")

    def test_market_flag_alone_collects_data_without_the_signal_pass(self):
        import run_range
        self.mode("shadow", "range_market")
        net = Net()
        out = run_range.once(now=self.now, log=lambda *_: None, fetch=lambda t: self.fail("no signal poll"), net=net,
                             gt_fetch=lambda *a: None)
        self.assertIn("signal 0", out)


class PaperOnly(TradeBase):
    def setUp(self):
        super().setUp()
        self.addCleanup(settings._FLAG_CACHE.clear)

    def test_market_and_event_tokens_never_on_the_real_account(self):
        self.mode("paper")
        mrng = dict(self.rng(), source="market", sources=["market"])
        self.assertFalse(trade.allowed(mrng, LU))
        self.assertFalse(trade.allowed(mrng, PU))                           # range_market off
        self.mode("shadow", "range_market")
        self.assertFalse(trade.allowed(mrng, PU))                           # shadow: data only
        self.mode("paper", "range_market")
        self.assertTrue(trade.allowed(mrng, PU))
        self.assertFalse(trade.allowed(mrng, LU))
        self.mode("live", "range_market")                                   # a hand edit: still never the real one
        self.assertFalse(trade.allowed(mrng, LU))
        erng = dict(self.rng(), sources=["event", "market"])
        self.mode("off", "range_market")
        self.mode("paper", "event_tokens")
        self.assertTrue(trade.allowed(erng, PU))
        self.assertTrue(trade.allowed(dict(self.rng(), sources=["signal", "market"]), LU))
        self.assertTrue(trade.allowed(self.rng(), LU))                       # a range without sources: the signal pass

    def test_paper_entry_of_a_market_token_on_the_demo_account_only(self):
        self.mode("paper")
        rng = dict(self.rng(), source="market", sources=["market"])
        self.assertEqual(self.enter(rng=dict(rng)), [])                     # range_market off: no entry
        self.assertEqual(flags.shadow_rows(self.lg, "range_dca"), [])       # and the real account logs nothing
        self.mode("paper", "range_market")
        done = self.enter(rng=dict(rng))
        self.assertEqual([u for u, _ in done], [PU])
        self.assertEqual(self.lots(LU), [])
        self.assertEqual(flags.shadow_rows(self.lg, "range_dca"), [])


class FlagsNeverLive(TradeBase):
    def test_g18_g19_off_by_default_paper_allowed_live_never(self):
        self.assertEqual(settings.FLAGS["event_tokens"][0], "G19")
        self.assertEqual(settings.FLAGS["range_market"][0], "G20")
        names = list(settings.FLAGS)
        self.assertLess(names.index("exit_plan_live"), names.index("event_tokens"))   # G18 is main's (#117)
        self.assertLess(names.index("event_tokens"), names.index("range_market"))
        for name in ("event_tokens", "range_market"):
            self.assertEqual(settings.flag(name, con=self.con), "off")
            settings.put(self.con, f"backtest:{name}", {"pass": True})
            settings.set_flag(self.con, name, "paper", "Jure", now=self.now - 30 * D)
            with self.assertRaisesRegex(ValueError, "nikad ne trguj"):
                settings.set_flag(self.con, name, "live", "Jure", paper={"n": 50, "pnl": 99.0}, now=self.now)
            self.assertNotIn(name, settings.DATA_FLAGS)


if __name__ == "__main__":
    unittest.main()


class Faza1(unittest.TestCase):
    """11.11. (faza 1, watchlist 300+): more GT pages a round, softer keep thresholds, the hourly universe line."""

    def test_keep_thresholds_are_softer_than_admission(self):
        now = 1794346000
        s = {"price": 1.0, "bonded": True, "mcap": 200_000, "liq": 18_000, "vol_h1": 7_000}
        self.assertFalse(market.check(s, now - 86400, "market", now)[0])            # not admitted at 18k / 7k
        self.assertTrue(market.check(s, now - 86400, "market", now, keep=True)[0])  # but a watched one stays
        s2 = dict(s, vol_h1=4_000)
        self.assertFalse(market.check(s2, now - 86400, "market", now, keep=True)[0])

    def test_gt_round_asks_every_page_within_the_day_cap(self):
        self.assertEqual(market.gt_requests(), 2 * market.GT_TREND_PAGES + market.GT_TOP_PAGES)
        self.assertLessEqual(market.gt_requests() * 86400 // market.GT_EVERY_S, market.GT_DAY)


class GtBusy(unittest.TestCase):
    """11.11.: a GeckoTerminal round while another job holds the host is not charged and is asked again."""

    def test_busy_host_is_not_charged(self):
        con = data.connect(os.path.join(tempfile.mkdtemp(), "range.db"))
        market.ensure(con)
        logs = []

        class Busy:
            def lists(self):
                return []

            def gt_pools(self, n_req=None):
                return None
        now = 1794346000
        data.kv_put(con, "mkt_lists_ts", now)        # lists not due
        market.discover_lists(con, now, Busy(), logs.append)
        self.assertIsNone(data.kv_get(con, "mkt_gt_ts"))
        self.assertEqual(data.day_used(con, "mkt_gt_day", now), 0)
        self.assertTrue(any("drži drugi posao" in x for x in logs))

    def test_round_line_tells_the_shared_coingecko_day(self):
        """11.11. (Jure): more GT pages only if the day has room after the first two real rounds: every round says
        how much of the shared CoinGecko day is gone."""
        from unittest import mock
        from event_calendar import http
        con = data.connect(os.path.join(tempfile.mkdtemp(), "range.db"))
        market.ensure(con)
        logs = []
        pool = {"attributes": {"name": "X / SOL"}, "relationships": {"base_token": {"data": {"id": "solana_M1"}}}}

        class Net:
            def lists(self):
                return []

            def gt_pools(self, n_req=None):
                return [pool]
        now = 1794346000 + 12 * 3600
        data.kv_put(con, "mkt_lists_ts", now)
        with mock.patch.dict(os.environ, {"COINGECKO_API_KEY": "k"}), \
                mock.patch.object(http, "cg_used", lambda today=None: (3000, 3000)), \
                mock.patch.object(market, "gt_row", lambda p: ("M1", "X", now - 86400, {"mcap": 1e5, "liq": 3e4, "vol_h1": 2e4})):
            market.discover_lists(con, now, Net(), logs.append)
        line = next(x for x in logs if x.startswith("range tržište GT:"))
        self.assertIn("(prava runda 1)", line)
        self.assertIn("CoinGecko ključ danas 3000/3000 (potrošen: ostatak dana besplatni GT)", line)
        self.assertIn(f"range lista {market.gt_requests()}/{market.GT_DAY}", line)

