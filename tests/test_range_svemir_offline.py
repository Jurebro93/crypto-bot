"""14.11. večer (owner: "Želim više tradeova"; svemir): the range market list's universe. The number of range trades
follows the number of LIVE tokens watched (the backtest: a token is in an active range ~6 % of the time), so the
discovery is wider inside the free budgets: Jupiter's token lists (one list a pass, JUP_DAY), the GeckoTerminal round
re-planned by measured yield (trending 1 h / 6 h / 24 h first, the same 16 requests), asked a few pages a pass and
resumed, charged only for the requests that went out, waiting for the next hour while the CoinGecko key's hour slice
is spent; GeckoTerminal seeds for a new high-volume token without 6 h of history (inside SEED_DAY); the watched tokens
and active ranges by source in the hourly universe line. No network.

    python3 -m unittest tests.test_range_svemir_offline
"""
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rangedca import data, market  # noqa: E402
from tests.test_range_dca_offline import TradeBase, tri  # noqa: E402
from tests.test_range_market_offline import Net, RDB, pair, snaps  # noqa: E402

D = 86400
DAY0 = 1_794_355_200            # 2026-11-14 00:00 UTC
ISO_OLD = "2026-11-10T00:00:00Z"


def jtok(tok, mc=200_000.0, liq=40_000.0, buy=4_000.0, sell=3_000.0, launchpad="pump.fun", graduated=True,
         tags=("unknown",), created=ISO_OLD):
    """A Jupiter tokens/v2 list row."""
    t = {"id": tok, "symbol": tok[:4], "usdPrice": mc / 1e9, "mcap": mc, "fdv": mc, "liquidity": liq,
         "stats1h": {"buyVolume": buy, "sellVolume": sell}, "firstPool": {"createdAt": created}, "tags": list(tags)}
    if launchpad:
        t["launchpad"] = launchpad
        if graduated:
            t["graduatedPool"] = "Pool" + tok[:6]
            t["graduatedAt"] = created
    return t


def gpool(tok, mc=150_000, liq=40_000, v1=9_000, dex="pumpswap", created=ISO_OLD):
    return {"attributes": {"base_token_price_usd": str(mc / 1e9), "fdv_usd": str(mc), "reserve_in_usd": str(liq),
                           "volume_usd": {"h1": str(v1)}, "pool_created_at": created, "name": f"{tok[:4]} / SOL"},
            "relationships": {"base_token": {"data": {"id": f"solana_{tok}"}}, "dex": {"data": {"id": dex}}}}


class JNet(Net):
    """market.Net stand-in with Jupiter lists (by name) and a resumable GeckoTerminal round."""

    def __init__(self, pairs=None, jup=None, gt=None, jup_err=None):
        super().__init__(pairs)
        self.jup, self.jup_asked, self.jup_err = dict(jup or {}), [], jup_err
        self.gt, self.gt_asked = list(gt or []), []

    def pairs(self, tokens, deadline=None):
        return super().pairs(tokens)

    def jup_list(self, name):
        self.jup_asked.append(name)
        if self.jup_err:
            raise self.jup_err
        return self.jup.get(name, [])

    def gt_pools(self, n_req=None, start=0, deadline=None):
        self.gt_asked.append((start, n_req))
        out = market.Fetched(self.gt[start:start + n_req])
        out.sent = out.done = n_req
        return out


class JupRow(unittest.TestCase):
    def test_numbers_bonded_and_skipped_tags(self):
        tok, sym, created, s = market.jup_row(jtok("A" * 44, mc=150_000, liq=30_000, buy=6_000, sell=2_500))
        self.assertEqual((tok, sym), ("A" * 44, "AAAA"))
        self.assertEqual(s["vol_h1"], 8_500)                                   # buy + sell volume of the hour
        self.assertEqual((s["mcap"], s["liq"]), (150_000, 30_000))
        self.assertTrue(s["bonded"])
        self.assertEqual(created, market._iso_ts(ISO_OLD))
        self.assertFalse(market.jup_row(jtok("B" * 44, graduated=False))[3]["bonded"])   # still on the curve
        self.assertTrue(market.jup_row(jtok("C" * 44, launchpad=None))[3]["bonded"])     # no launchpad: a pool token
        self.assertFalse(market.jup_row(jtok("D" * 44, liq=0))[3]["bonded"])
        # a tokenized stock / RWA / staked SOL is not a meme: never stored
        self.assertIsNone(market.jup_row(jtok("E" * 44, launchpad=None, tags=("verified", "stocks", "rwa"))))
        self.assertIsNone(market.jup_row({"symbol": "X"}))

    def test_the_market_filter_reads_them_like_any_source(self):
        now = DAY0 + 12 * 3600
        ok = market.jup_row(jtok("F" * 44))[3]
        self.assertTrue(market.check(ok, now - 7 * 3600, "market", now)[0])
        curve = market.jup_row(jtok("G" * 44, graduated=False))[3]
        self.assertFalse(market.check(curve, now - 7 * 3600, "market", now)[0])   # bonded only (CLAUDE.md)
        low = market.jup_row(jtok("H" * 44, mc=29_000))[3]
        self.assertFalse(market.check(low, now - 7 * 3600, "market", now)[0])     # never under 30k


class Jupiter(RDB):
    def setUp(self):
        super().setUp()
        data.kv_put(self.con, "mkt_lists_ts", DAY0 + 10 * D)     # the DexScreener lists are not due
        data.kv_put(self.con, "mkt_gt_ts", DAY0 + 10 * D)        # nor the GeckoTerminal round

    def row(self, tok):
        return self.con.execute("SELECT via, next_ts, watched, vol_h1 FROM mkt WHERE token=?", (tok,)).fetchone()

    def test_one_list_a_pass_in_turn_inside_the_day_cap(self):
        now = DAY0 + 12 * 3600
        net = JNet()
        market.discover_lists(self.con, now, net, print)
        market.discover_lists(self.con, now + 60, net, print)                      # not due yet: 900 / 7 = 128 s
        self.assertEqual(net.jup_asked, [market.JUP_LISTS[0]])
        step = int(market.JUP_EVERY_S / len(market.JUP_LISTS))
        for k in range(1, len(market.JUP_LISTS) + 1):
            market.discover_lists(self.con, now + k * step, net, print)
        self.assertEqual(net.jup_asked, list(market.JUP_LISTS) + [market.JUP_LISTS[0]])   # every list, then again
        self.assertEqual(data.day_used(self.con, "mkt_jup_day", now), len(market.JUP_LISTS) + 1)
        # the whole set every JUP_EVERY_S fits the day's cap
        self.assertLessEqual(len(market.JUP_LISTS) * 86400 // market.JUP_EVERY_S, market.JUP_DAY)

    def test_the_hour_slice_holds_the_lists(self):
        now = DAY0 + 600                                                             # hour 0: 700 / 24 = 29
        data.day_add(self.con, "mkt_jup_day", 29, now)
        net = JNet()
        market.discover_lists(self.con, now, net, print)
        self.assertEqual(net.jup_asked, [])

    def test_a_passing_token_is_due_now_a_quiet_one_later_the_rest_is_not_stored(self):
        now = DAY0 + 12 * 3600
        ok, quiet, big, young, curve, known = ("J" * 44, "Q" * 44, "B" * 44, "Y" * 44, "C" * 44, "K" * 44)
        young_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 2 * 3600))
        market.add(self.con, known, "migracija", now - D, due=now - D)
        self.con.execute("UPDATE mkt SET next_ts=?, checked_ts=? WHERE token=?", (now + D, now - 4 * 3600, known))
        rows = [jtok(ok), jtok(quiet, buy=2_000, sell=1_500), jtok(big, mc=9e6), jtok(young, created=young_iso),
                jtok(curve, graduated=False), jtok(known)]
        net = JNet(jup={market.JUP_LISTS[0]: rows})
        n = market.discover_lists(self.con, now, net, print)
        self.assertEqual(n, 3)                                                       # ok, quiet, young (known exists)
        self.assertEqual(self.row(ok)[:3], ("jup", now, 0))                          # due now
        self.assertEqual(self.row(ok)[3], 7_000)                                     # its volume orders the admission
        self.assertEqual(self.row(quiet)[1], now + 3600)                             # volume 1 h $3.5k: in an hour
        self.assertGreater(self.row(young)[1], now + 3 * 3600)                       # 6 h old first
        self.assertIsNone(self.row(big))                                             # MC 9M: not stored
        self.assertIsNone(self.row(curve))                                           # on the curve: not stored
        self.assertEqual(self.row(known)[:2], ("jup,migracija", now))                # promoted: due now

    def test_the_admission_takes_a_jupiter_token_in_the_same_pass(self):
        now = DAY0 + 12 * 3600
        tok = "N" * 40 + "pump"
        net = JNet({tok: pair(tok, px=1e-4, mc=200_000, liq=40_000, vol_h1=7_000, created=now - 4 * D)},
                   jup={market.JUP_LISTS[0]: [jtok(tok)]})
        out = market.pass_once(self.con, now, net, print, pulse=set(), event_on=False)
        self.assertIn(tok, out["tokens"])
        self.assertEqual(out["stats"]["admitted"], 1)
        self.assertEqual(net.asked, [[tok]])                                         # 1/30 of a DexScreener request

    def test_an_error_rests_the_lists_and_the_hour_has_one_line(self):
        now = DAY0 + 12 * 3600
        logs = []
        net = JNet(jup_err=RuntimeError("429"))
        market.discover_lists(self.con, now, net, logs.append)
        self.assertEqual(data.kv_get(self.con, "mkt_jup_pause"), now + market.JUP_PAUSE_S)
        self.assertEqual(data.kv_get(self.con, "mkt_jup_i") or 0, 0)                # the same list next time
        market.discover_lists(self.con, now + 300, net, logs.append)                 # resting: not asked
        self.assertEqual(len(net.jup_asked), 1)
        net.jup_err = None
        net.jup = {market.JUP_LISTS[0]: [jtok("L" * 44)]}
        market.discover_lists(self.con, now + market.JUP_PAUSE_S, net, logs.append)
        self.assertFalse([x for x in logs if "Jupiter" in x])                        # one line an hour, not a list
        market.discover_lists(self.con, now + 3600, net, logs.append)
        line = [x for x in logs if x.startswith("range tržište Jupiter")]
        self.assertEqual(len(line), 1, logs)
        self.assertIn("(sat 12 UTC): 2 upita, 1 tokena, novih 1, prolazi filter 1, greške 1", line[0])
        self.assertIn(f"/{market.JUP_DAY} (besplatno)", line[0])

    def test_the_cost_lines_carry_jupiter(self):
        now = DAY0 + 12 * 3600
        market.discover_lists(self.con, now, JNet(), print)
        self.assertEqual(market.cost_today(self.con, now)["jupiter"], {"used": 1, "cap": market.JUP_DAY})
        logs = []
        data.kv_put(self.con, "mkt_spend_day", data._day(now))
        market.spend_line(self.con, now + D, logs.append)
        self.assertIn(f"jupiter 1/{market.JUP_DAY}", logs[0])
        self.assertIn("od toga rano 0", logs[0])

    def test_the_real_net_never_sends_the_swap_key(self):
        from event_calendar import http
        seen = []
        with mock.patch.dict(os.environ, {"JUP_API_KEY": "secret"}), \
                mock.patch.object(http, "get_json", lambda url, params=None, **k: seen.append((url, params, k)) or
                                  [jtok("Z" * 44), "junk"]):
            got = market.Net().jup_list("toptraded/1h")
        self.assertEqual([t["id"] for t in got], ["Z" * 44])
        url, params, k = seen[0]
        self.assertEqual(url, f"{market.JUP_URL}/toptraded/1h")
        self.assertEqual(params, {"limit": 100})
        self.assertNotIn("secret", repr(k))
        self.assertEqual(k.get("retries"), 0)


class GtRound(RDB):
    def setUp(self):
        super().setUp()
        data.kv_put(self.con, "mkt_lists_ts", DAY0 + 10 * D)
        self.route = mock.patch.object(market, "gt_route", lambda: "key")
        self.route.start()
        self.addCleanup(self.route.stop)

    def test_the_plan_puts_the_trending_lists_first_and_keeps_16(self):
        plan = market.gt_plan()
        self.assertEqual(len(plan), market.gt_requests())
        self.assertEqual(market.gt_requests(), 16)
        self.assertEqual([p.get("duration") for _u, p in plan[:12]], ["1h"] * 4 + ["6h"] * 4 + ["24h"] * 4)
        self.assertEqual([u for u, _p in plan[12:]], ["/pools"] * 2 + [f"/dexes/{market.GT_DEX}/pools"] * 2)
        self.assertLessEqual(market.gt_requests() * 86400 // market.GT_EVERY_S, market.GT_DAY)

    def test_a_few_pages_a_pass_resumed_one_line_when_done(self):
        now = DAY0 + 12 * 3600
        pools = [gpool(f"T{i:02d}" + "x" * 41) for i in range(16)]
        net = JNet(gt=pools)
        logs = []
        for k in range(3):
            market.discover_lists(self.con, now + 60 * k, net, logs.append)
        self.assertEqual(net.gt_asked, [(0, 6), (6, 6), (12, 4)])
        self.assertEqual(data.day_used(self.con, "mkt_gt_day", now), 16)
        line = [x for x in logs if x.startswith("range tržište GT:")]
        self.assertEqual(len(line), 1, logs)
        self.assertIn("16 upita, 16 poolova, novih 16, prolazi filter 16", line[0])
        self.assertEqual(data.kv_get(self.con, "mkt_gt_ts"), now + 120)
        market.discover_lists(self.con, now + 180, net, logs.append)                   # the next round in 2 h
        self.assertEqual(len(net.gt_asked), 3)

    def test_the_free_host_two_pages_a_pass(self):
        now = DAY0 + 12 * 3600
        net = JNet(gt=[gpool("F" * 44)] * 16)
        with mock.patch.object(market, "gt_route", lambda: "free"):
            market.discover_lists(self.con, now, net, print)
        self.assertEqual(net.gt_asked, [(0, market.GT_REQ_PASS_FREE)])

    def test_the_spent_hour_slice_waits_for_the_next_hour(self):
        now = DAY0 + 12 * 3600
        net = JNet(gt=[gpool("H" * 44)] * 16)
        logs = []
        with mock.patch.object(market, "gt_route", lambda: "hour"):
            market.discover_lists(self.con, now, net, logs.append)
            market.discover_lists(self.con, now + 60, net, logs.append)
        self.assertEqual(net.gt_asked, [])
        self.assertEqual(data.day_used(self.con, "mkt_gt_day", now), 0)
        self.assertEqual(len([x for x in logs if "satni dio CoinGecko ključa potrošen" in x]), 1)

    def test_only_what_went_out_is_charged_and_a_held_page_is_asked_again(self):
        now = DAY0 + 12 * 3600

        class Stop(JNet):
            def gt_pools(self, n_req=None, start=0, deadline=None):
                self.gt_asked.append((start, n_req))
                out = market.Fetched([gpool("S" * 44)])
                out.sent, out.done, out.stop = 1, 1, "zauzet"          # page 1 answered, page 2 held by another job
                return out
        net = Stop()
        logs = []
        market.discover_lists(self.con, now, net, logs.append)
        self.assertEqual(data.day_used(self.con, "mkt_gt_day", now), 1)               # not 6
        self.assertEqual(data.kv_get(self.con, "mkt_gt_idx"), 1)                      # resumes at the held page
        self.assertFalse([x for x in logs if x.startswith("range tržište GT:")])

    def test_a_failing_page_is_charged_and_skipped(self):
        now = DAY0 + 12 * 3600

        class Fail(JNet):
            def gt_pools(self, n_req=None, start=0, deadline=None):
                self.gt_asked.append((start, n_req))
                out = market.Fetched()
                out.sent, out.done, out.stop = 1, 0, "greška 429"
                return out
        market.discover_lists(self.con, now, Fail(), print)
        self.assertEqual(data.day_used(self.con, "mkt_gt_day", now), 1)
        self.assertEqual(data.kv_get(self.con, "mkt_gt_idx"), 1)                      # never stalls on one page

    def test_the_real_net_stops_at_a_held_host_an_error_or_a_pause(self):
        from event_calendar import http
        calls = []

        def gj(url, params=None, **k):
            calls.append(params)
            if len(calls) == 3:
                return None                                                           # another job took the host
            return {"data": [gpool("R" * 44)]}
        with mock.patch.object(http, "reserved_by_other", lambda url: 0), mock.patch.object(http, "cooling", lambda url: 0), \
                mock.patch.object(http, "get_json", gj):
            got = market.Net().gt_pools(6, start=0)
        self.assertEqual((got.sent, got.done, got.stop, len(got)), (2, 2, "zauzet", 2))

        def boom(url, params=None, **k):
            raise RuntimeError("429")
        with mock.patch.object(http, "reserved_by_other", lambda url: 0), mock.patch.object(http, "cooling", lambda url: 0), \
                mock.patch.object(http, "get_json", boom):
            got = market.Net().gt_pools(6, start=4)
        self.assertEqual((got.sent, got.done, got.stop), (1, 0, "greška RuntimeError"))
        with mock.patch.object(http, "reserved_by_other", lambda url: 0), mock.patch.object(http, "cooling", lambda url: 30), \
                mock.patch.object(http, "get_json", lambda *a, **k: self.fail("asked during a 429 pause")):
            got = market.Net().gt_pools(6)
        self.assertEqual((got.sent, got.stop), (0, "pauza nakon 429"))
        with mock.patch.object(http, "reserved_by_other", lambda url: 0), mock.patch.object(http, "cooling", lambda url: 0), \
                mock.patch.object(http, "get_json", lambda *a, **k: self.fail("asked after the deadline")):
            got = market.Net().gt_pools(6, deadline=time.monotonic() - 1)
        self.assertEqual((got.sent, got.stop), (0, "vrijeme prolaza"))

    def test_gt_route(self):
        from event_calendar import http
        self.route.stop()
        try:
            with mock.patch.object(http, "cg_configured", lambda: False):
                self.assertEqual(market.gt_route(), "free")
            with mock.patch.object(http, "cg_configured", lambda: True), mock.patch.object(http, "cg_key", lambda: "k"):
                self.assertEqual(market.gt_route(), "key")
            with mock.patch.object(http, "cg_configured", lambda: True), mock.patch.object(http, "cg_key", lambda: ""), \
                    mock.patch.object(http, "cg_used", lambda today=None: (1125, 3000)):
                self.assertEqual(market.gt_route(), "hour")                           # the Render log of 14.11.
            with mock.patch.object(http, "cg_configured", lambda: True), mock.patch.object(http, "cg_key", lambda: ""), \
                    mock.patch.object(http, "cg_used", lambda today=None: (3000, 3000)):
                self.assertEqual(market.gt_route(), "free")                           # the day is gone: free host
        finally:
            self.route.start()


class BySource(RDB):
    def test_the_universe_line_counts_watched_and_active_by_source(self):
        now = DAY0 + 12 * 3600
        for tok, via, active in (("A" * 44, "jup", 1), ("B" * 44, "gt,jup", 0), ("C" * 44, "hype", 1)):
            self.con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched) VALUES (?,?,?,?,?,1)",
                             (tok, via, "market", now, now))
            self.con.execute("INSERT INTO ranges (token, ts, status, active) VALUES (?,?,?,?)",
                             (tok, now, "aktivan" if active else "nema raspona", active))
        self.con.commit()
        self.assertEqual(market.by_source(self.con), ({"jup": 2, "gt": 1, "hype": 1}, {"jup": 1, "hype": 1}))
        line = market.universe_line(self.con, now, log=lambda *_: None)
        self.assertIn("prati po izvoru: jup 2, gt 1, hype 1", line)
        self.assertIn("aktivni rasponi po izvoru: hype 1, jup 1", line)


class EarlySeed(RDB):
    def test_a_new_high_volume_token_gets_its_history_inside_the_seed_day(self):
        import run_range
        now = DAY0 + 12 * 3600
        res = {"status": "premalo podataka"}
        snap = {"vol_h1": 25_000}
        with mock.patch.object(market, "gt_route", lambda: "key"):
            self.assertTrue(run_range._early_seed(self.con, res, snap, now, False))
            data.day_add(self.con, "mkt_seed_early_day", 6, now)                       # 12:xx UTC: 12 x 13 / 24 = 6
            self.assertFalse(run_range._early_seed(self.con, res, snap, now, False))   # the hour's share is used
            self.assertTrue(run_range._early_seed(self.con, res, snap, now + 3600, False))
            data.day_add(self.con, "mkt_seed_early_day", -6, now)
            self.assertFalse(run_range._early_seed(self.con, res, snap, now, True))                 # seeded already
            self.assertFalse(run_range._early_seed(self.con, res, {"vol_h1": 15_000}, now, False))  # quieter: waits
            self.assertFalse(run_range._early_seed(self.con, {"status": "aktivan"}, snap, now, False))
            data.day_add(self.con, "mkt_seed_day", market.SEED_DAY - market.SEED_NEAR_RESERVE, now)
            self.assertFalse(run_range._early_seed(self.con, res, snap, now, False))   # the rest is for near entries
        data.day_add(self.con, "mkt_seed_day", -market.SEED_DAY, now)
        with mock.patch.object(market, "gt_route", lambda: "hour"):
            self.assertFalse(run_range._early_seed(self.con, res, snap, now, False))   # never on the minute loop's host




class EarlySeedJob(TradeBase):
    """run_range.once: a newly watched market token with 2 h of snapshots and $60k an hour gets its GeckoTerminal seed
    in the pass, so its range is computed now, not 6 h later; the seed is counted in the market's seed day."""

    def test_the_range_is_there_in_the_first_pass(self):
        import run_range
        now = self.now - self.now % 60
        tok = "W" * 40 + "pump"
        con = data.connect()
        market.ensure(con)
        for s in snaps(now, hours=2):
            data.save_snap(con, tok, dict(s, pool="Pool" + tok[:8], dex="pumpswap", symbol="WWW"))
        con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, last_snap, vol_h1, liq, created_ts) "
                    "VALUES (?,?,?,?,?,1,?,?,?,?)", (tok, "jup", "market", now - 3600, now, now, 60_000.0, 50_000.0,
                                                     now - 3 * D))
        data.kv_put(con, "mkt_lists_ts", now + D)
        data.kv_put(con, "mkt_gt_ts", now + D)
        con.commit()
        con.close()
        self.mode("shadow", "range_market")
        last = snaps(now, hours=2)[-1]
        asked = []

        def gt(pool, start, end):
            asked.append(pool)
            return [c[:6] for c in tri(end - 16 * 3600, hours=16)]
        with mock.patch.object(market, "_meter", lambda *a, **k: None), \
                mock.patch.object(market, "gt_route", lambda: "key"), \
                mock.patch.multiple(market, from_graduates=lambda c, n: 0, from_scanner=lambda c, n, scan_db=None: 0):
            run_range.once(now=now, log=lambda *_: None, fetch=lambda toks: [], gt_fetch=gt, post=lambda *a: {},
                           net=Net({tok: pair(tok, px=last["price"], mc=last["mcap"], liq=50_000, vol_h1=60_000,
                                              created=now - 3 * D)}))
        con = data.connect()
        r = data.load_range(con, tok)[0]
        early, seeds = data.day_used(con, "mkt_seed_early_day", now), data.day_used(con, "mkt_seed_day", now)
        con.close()
        self.assertEqual(asked, ["Pool" + tok[:8]])
        self.assertEqual((early, seeds), (1, 1))
        self.assertNotEqual(r["status"], "premalo podataka", r.get("why"))
        self.assertEqual(r["status"], "aktivan", r.get("why"))


if __name__ == "__main__":
    unittest.main()
