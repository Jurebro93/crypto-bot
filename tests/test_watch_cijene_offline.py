"""12.11. (Jure, nalog točka 3: "STC (mint Dcipe…pump) ima cijene samo do 10:55 CET, iako je likvidnost bila 16k.
Provjeri zašto tokeni s watch liste prestaju dobivati cijene i popravi to. Test: token na watch listi s likvidnošću
>= 15k dobiva cijenu barem svakih 5 min."). The range watchlist (rangedca/market.py mkt, rangedca/data.poll the signal pass):

  * a liquid watched token is priced at least every 5 min over a simulated 2 h of run_range passes (~62 s apart, with
    jitter), also as the quietest of 400 tokens on the list (it used to be "cold": every 15 min past HOT_N), and the
    DexScreener requests stay at one batch of 30 per ~4 passes
  * STC's case: a token whose MC falls under 30k with $16k of liquidity stays on the list and keeps its 5-minute
    price (it used to leave for 24 h, and the signal pass put it aside for 6 h while it stayed a call candidate);
    measured only: its range is "ispod 30k" (never active, never bought); under $15k of liquidity it leaves as before
  * the signal pass hands such a token to the market list, so the price goes on once it is no longer a candidate
  * the hype scan's fresh token_pulse row still saves the request, counted from its age
  * events.db: the 5-min tick logs the price ticks and transfers of the last 15 min (the confirmation after PR #149)

No network: DexScreener is a stub that answers from a dict.

    python3 -m unittest tests.test_watch_cijene_offline
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rangedca import data, detect, market  # noqa: E402

DAY0 = 1_794_355_200          # 12.11.2026 00:00 UTC
T0 = DAY0 + 9 * 3600          # 09:00 UTC: the hour slice is well open
STC = "Dcipe" + "s" * 34 + "pump"


def pair(tok, mc=60_000.0, liq=30_000.0, vol_h1=20_000.0, px=None, dex="pumpswap"):
    return {"chainId": "solana", "baseToken": {"address": tok, "symbol": tok[:4], "name": tok[:4]},
            "priceUsd": str(px if px is not None else mc / 1e9), "marketCap": mc, "dexId": dex,
            "pairAddress": "Pool" + tok[:8], "liquidity": {"usd": liq},
            "volume": {"m5": vol_h1 / 12, "h1": vol_h1, "h6": vol_h1 * 6},
            "txns": {"m5": {"buys": 6, "sells": 4}, "h1": {"buys": 60, "sells": 40}}, "priceChange": {"m5": 1.0},
            "pairCreatedAt": int((T0 - 3 * 86400) * 1000)}


class Net:
    """rangedca/market.Net stand-in: answers from `book` (token -> pair) and records every batch."""

    def __init__(self, book):
        self.book, self.asked = book, []

    def pairs(self, tokens):
        assert len(tokens) <= 30 * market.MAX_REQ_PASS
        self.asked.append(list(tokens))
        return [self.book[t] for t in tokens if t in self.book]

    def lists(self):
        return []

    def gt_pools(self):
        return []

    def birdeye_list(self):
        return None


def passes(start, minutes, gaps=(60, 62, 65, 61, 63)):
    """run_range.py once times: ~62 s apart (start.sh: 60 s sleep + the pass), with jitter."""
    t, i, out = start, 0, []
    while t <= start + minutes * 60:
        out.append(t)
        t += gaps[i % len(gaps)]
        i += 1
    return out


def max_gap(ts):
    ts = sorted(ts)
    return max(b - a for a, b in zip(ts, ts[1:])) if len(ts) > 1 else None


class RDB(unittest.TestCase):
    """A range.db of its own; no hype scan, no topics, no graduates / scanner (their reads are stubbed)."""

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
                               (market, "from_scanner", lambda con, now, scan_db=None: 0),
                               (market, "from_migrations", lambda con, now, hype_db=None: 0)):
            pm = mock.patch.object(obj, name, val)
            pm.start()
            self.addCleanup(pm.stop)
        self.con = data.connect()
        market.ensure(self.con)
        self.addCleanup(self.con.close)
        data.kv_put(self.con, "mkt_lists_ts", T0 + 10 ** 6)   # discovery lists / GT rounds not due in these tests
        data.kv_put(self.con, "mkt_gt_ts", T0 + 10 ** 6)

    def watch(self, tok, liq=30_000.0, vol_h1=20_000.0, mcap=60_000.0, src="market", last_snap=None):
        self.con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, watched_ts, last_snap, mcap, "
                         "liq, vol_h1, created_ts) VALUES (?,?,?,?,?,1,?,?,?,?,?,?)",
                         (tok, "gt", src, T0 - 86400, T0, T0 - 3600, last_snap, mcap, liq, vol_h1, T0 - 3 * 86400))
        self.con.commit()

    def snap_ts(self, tok):
        return [r[0] for r in self.con.execute("SELECT ts FROM snaps WHERE token=? ORDER BY ts", (tok,))]


# ---------------------------------------------------------------------------------------------------------------------
class FiveMinutes(RDB):
    def test_the_quietest_of_400_tokens_with_16k_liquidity_gets_a_price_at_least_every_5_min(self):
        others = [f"T{i:03d}" + "x" * 40 for i in range(market.MARKET_MAX - 1)]   # a full list with STC
        book = {t: pair(t, mc=200_000.0, liq=40_000.0, vol_h1=100_000.0 - i) for i, t in enumerate(others)}
        for i, t in enumerate(others):
            self.watch(t, liq=40_000.0, vol_h1=100_000.0 - i, mcap=200_000.0)
        self.watch(STC, liq=16_000.0, vol_h1=6_000.0, mcap=60_000.0)      # last in the order, far past HOT_N (100)
        book[STC] = pair(STC, mc=60_000.0, liq=16_000.0, vol_h1=6_000.0)
        net = Net(book)
        times = passes(T0, 120)
        for i, now in enumerate(times):
            if now >= T0 + 600:                                            # STC falls to MC $16k, liquidity $16k
                book[STC] = pair(STC, mc=16_000.0, liq=16_000.0, vol_h1=6_000.0)
            out = market.pass_once(self.con, now, net, log=lambda *_: None, pulse=set(), event_on=False)
            self.assertTrue(STC in out["tokens"], now - T0)                 # never leaves the list
            self.assertEqual(out["stats"]["dropped"], 0)
        got = self.snap_ts(STC)
        self.assertEqual(got[0], T0)
        self.assertLessEqual(max_gap(got + [times[-1]]), 300, got)       # at least every 5 min, up to the last pass
        self.assertLessEqual(max_gap(self.snap_ts(others[0]) + [times[-1]]), 300)
        # the price under 30k is in range.db (measured) and the token is flagged, not bought
        mc_last = self.con.execute("SELECT mcap FROM snaps WHERE token=? ORDER BY ts DESC LIMIT 1", (STC,)).fetchone()[0]
        self.assertEqual(mc_last, 16_000.0)
        self.assertEqual(self.con.execute("SELECT why FROM mkt WHERE token=?", (STC,)).fetchone()[0], market.MEASURE_WHY)
        # cost: 400 tokens = 14 batches of 30, about once every 4 passes (~248 s), never every pass
        reqs = data.day_used(self.con, "mkt_dex_day", times[-1])             # DexScreener requests (30 tokens each)
        rounds = (times[-1] - T0) / 248 + 1
        self.assertLessEqual(reqs, 14 * (rounds + 1))
        self.assertLess(len(net.asked), len(times) / 3)
        self.assertGreater(market.slice_left(self.con, "mkt_dex_day", market.DEX_DAY, times[-1]), 0)   # inside the cap

    def test_before_the_fix_the_token_would_leave_the_list_under_30k_and_under_15k_it_still_does(self):
        self.watch(STC, liq=30_000.0, vol_h1=20_000.0)
        net = Net({STC: pair(STC, mc=16_000.0, liq=16_000.0, vol_h1=20_000.0)})
        market.pass_once(self.con, T0, net, log=lambda *_: None, pulse=set(), event_on=False)
        self.assertEqual(self.con.execute("SELECT watched FROM mkt WHERE token=?", (STC,)).fetchone()[0], 1)
        self.assertEqual(self.snap_ts(STC), [T0])
        net.book[STC] = pair(STC, mc=12_000.0, liq=12_000.0, vol_h1=20_000.0)   # liquidity pulled under $15k
        market.pass_once(self.con, T0 + 300, net, log=lambda *_: None, pulse=set(), event_on=False)
        self.assertEqual(self.con.execute("SELECT watched FROM mkt WHERE token=?", (STC,)).fetchone()[0], 0)
        self.assertEqual(self.snap_ts(STC), [T0])                          # under 30k and under 15k: not stored

    def test_keep_rule(self):
        now = T0
        s = {"price": 1e-5, "bonded": True, "mcap": 16_000, "liq": 16_000, "vol_h1": 6_000}
        self.assertTrue(market.check(s, now - 86400, "market", now, keep=True)[0])      # watched: stays, measured
        self.assertTrue(market.check(s, now - 86400, "missed", now, keep=True)[0])
        self.assertTrue(market.check(dict(s, vol_h1=0), now - 86400, "event", now, keep=True)[0])
        self.assertTrue(market.check(dict(s, mcap=40_000), now - 86400, "market", now, keep=True)[0])   # under 50k
        self.assertFalse(market.check(s, now - 86400, "market", now)[0])                # never admitted under 30k
        self.assertFalse(market.check(dict(s, liq=14_000), now - 86400, "market", now, keep=True)[0])
        self.assertFalse(market.check(dict(s, vol_h1=4_000), now - 86400, "market", now, keep=True)[0])
        self.assertFalse(market.check(dict(s, mcap=6e6), now - 86400, "market", now, keep=True)[0])
        self.assertFalse(market.check(dict(s, bonded=False), now - 86400, "market", now, keep=True)[0])

    def test_measured_under_30k_is_never_an_active_range(self):
        tok = STC
        t1 = T0
        for i in range(12 * 12 + 1):                     # 12 h of a clean range between MC $12k and $20k, 5-min snaps
            k = i * 5
            ph = k % 120
            mc = 12_000 + 8_000 * (ph / 60 if ph < 60 else (120 - ph) / 60)
            data.save_snap(self.con, tok, {"ts": t1 - (144 - i) * 300, "price": mc / 1e9, "mcap": mc, "liq": 16_000.0,
                                           "vol_m5": 5_000.0, "vol_h1": 60_000.0, "vol_h6": 360_000.0, "buys_m5": 6,
                                           "sells_m5": 4, "buys_h1": 72, "sells_h1": 48, "ch_m5": None, "pool": None})
        candles, snap = data.series(self.con, tok, t1)
        r = detect.analyze(candles, t1, snap)
        self.assertEqual(r["status"], "ispod 30k", r.get("why"))
        self.assertFalse(r["active"])

    def test_the_hype_scans_fresh_row_is_reused_and_counted_from_its_age(self):
        self.watch(STC, liq=16_000.0, last_snap=T0 - 400)
        net = Net({STC: pair(STC, liq=16_000.0)})
        out = market.pass_once(self.con, T0, net, log=lambda *_: None, pulse={STC}, event_on=False)
        self.assertEqual((out["stats"]["reused"], net.asked), (1, []))
        last = self.con.execute("SELECT last_snap FROM mkt WHERE token=?", (STC,)).fetchone()[0]
        self.assertEqual(last, T0 - data.PULSE_FRESH_S)                    # the pulse row may be 150 s old
        market.pass_once(self.con, T0 + 100, net, log=lambda *_: None, pulse=set(), event_on=False)
        self.assertEqual(net.asked, [[STC]])                               # 250 s after that row: asked in time

    def test_a_short_hour_drops_the_tokens_without_liquidity_first(self):
        quiet = [f"Q{i:03d}" + "q" * 40 for i in range(40)]
        for i, t in enumerate(quiet):                                      # event tokens: no liquidity rule
            self.watch(t, liq=5_000.0, vol_h1=900_000.0 - i, src="event")
        self.watch(STC, liq=16_000.0, vol_h1=6_000.0)
        net = Net({t: pair(t, liq=5_000.0) for t in quiet} | {STC: pair(STC, liq=16_000.0, vol_h1=6_000.0)})
        with mock.patch.object(market, "MAX_REQ_PASS", 1):
            out = market.pass_once(self.con, T0, net, log=lambda *_: None, pulse=set(), event_on=True)
        self.assertIn(STC, net.asked[0])
        self.assertEqual(out["stats"]["dropped"], 11)


# ---------------------------------------------------------------------------------------------------------------------
class SignalPass(RDB):
    def test_poll_measures_a_liquid_token_under_30k_instead_of_putting_it_aside(self):
        thin = "Thin" + "t" * 40
        book = {STC: pair(STC, mc=16_000.0, liq=16_000.0), thin: pair(thin, mc=16_000.0, liq=9_000.0)}
        got = data.poll(self.con, [STC, thin], T0, fetch=lambda toks: [book[t] for t in toks], pulse_fresh=set())
        self.assertEqual(set(got), {STC})
        self.assertEqual(self.snap_ts(STC), [T0])
        cold = data.kv_get(self.con, "cold")
        self.assertIn(thin, cold)                                          # under 30k and $9k: aside for 6 h as before
        self.assertNotIn(STC, cold)

    def test_stc_called_then_out_of_the_candidates_keeps_its_price_every_5_min(self):
        """A call candidate is polled every minute; at 09:55 its MC falls to $16k (liquidity $16k); from 10:10 it is no
        longer a candidate (its range turned "ispod 30k"). Before the fix: no price from 09:55 for 6 h."""
        book = {STC: pair(STC, mc=60_000.0, liq=30_000.0, vol_h1=20_000.0)}
        net = Net(book)
        fetch = lambda toks: [book[t] for t in toks if t in book]   # noqa: E731
        times = passes(T0, 90)
        for now in times:
            if now >= T0 + 900:
                book[STC] = pair(STC, mc=16_000.0, liq=16_000.0, vol_h1=8_000.0)
            sig = [STC] if now < T0 + 1800 else []
            got = data.poll(self.con, sig, now, fetch=fetch, pulse_fresh=set()) if sig else {}
            market.adopt(self.con, got, now)
            market.pass_once(self.con, now, net, log=lambda *_: None, signal=sig, pulse=set(), event_on=False)
        got = self.snap_ts(STC)
        self.assertLessEqual(max_gap(got + [times[-1]]), 300, got)
        self.assertGreater(got[-1], T0 + 1800 + 3000)                      # still priced an hour after it left
        w, via, why = self.con.execute("SELECT watched, via, why FROM mkt WHERE token=?", (STC,)).fetchone()
        self.assertEqual((w, via, why), (1, "signal", market.MEASURE_WHY))

    def test_adopt_takes_only_liquid_trading_tokens_under_30k(self):
        def s(**k):
            return dict({"ts": T0, "price": 1e-5, "bonded": True, "mcap": 16_000, "liq": 16_000, "vol_h1": 8_000,
                         "symbol": "STC"}, **k)
        n = market.adopt(self.con, {STC: s(), "A" * 44: s(mcap=40_000), "B" * 44: s(liq=9_000), "C" * 44: s(vol_h1=100),
                                    "D" * 44: s(bonded=False)}, T0)
        self.assertEqual(n, 1)
        self.assertEqual(market.watched(self.con), [STC])
        self.assertEqual(market.adopt(self.con, {STC: s()}, T0 + 60), 0)    # already on the list


# ---------------------------------------------------------------------------------------------------------------------
class EventsLast15(unittest.TestCase):
    """The 5-min tick's log line carries the price ticks / transfers of the last 15 min (12.11.: the sync's own "+N"
    leaves out what kol/snap and the Helius webhook write directly)."""

    def setUp(self):
        from events import store
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"EVENTS_DB": os.path.join(self.tmp.name, "events.db")})
        p.start()
        self.addCleanup(p.stop)
        self.store = store
        con = store.connect()
        rows = [store.row("price_tick", T0 - 60 * i, STC, "dexscreener", mcap=60_000, key=f"p{i}") for i in range(20)]
        rows += [store.row("transfer", T0 - 120 * i, None, "helius", "W" * 44, sol=1.0, key=f"t{i}") for i in range(5)]
        rows += [store.row("wallet_buy", T0 - 60, STC, "helius", "W" * 44, sol=1.0, key="b")]
        store.insert(con, rows)
        con.commit()
        con.close()

    def test_counts_from_the_type_ts_index(self):
        from events import health
        con = self.store.connect()
        try:
            c = health.recent_counts(con, T0)
        finally:
            con.close()
        self.assertEqual(c, {"price_tick": 16, "transfer": 5})             # minutes 0..15 inclusive; 0..8 min
        self.assertEqual(health.recent_text(c), "zadnjih 15 min: cijene 16, transferi 5")

    def test_the_tick_logs_them_every_time(self):
        from events import health, night, predictions, sources
        from ui import mcpapi
        lines = []
        with mock.patch.object(sources, "sync", lambda *a, **k: {}), \
                mock.patch.object(health, "check", lambda *a, **k: []), \
                mock.patch.object(night, "_late_check", lambda *a, **k: None), \
                mock.patch.object(predictions, "score_due", lambda *a, **k: 0), \
                mock.patch.object(mcpapi, "tidy_requests", lambda *a, **k: 0):
            r = night.tick(T0, log=lines.append)
        self.assertEqual(r["recent"], {"price_tick": 16, "transfer": 5})
        self.assertEqual(lines, ["događaji: bez novih; zadnjih 15 min: cijene 16, transferi 5"])
        lines.clear()
        al = [{"key": "events:gap:transfer", "type": "transfer"}, {"key": "events:night:late"}]
        with mock.patch.object(sources, "sync", lambda *a, **k: {"hype_snapshots": 3}), \
                mock.patch.object(health, "check", lambda *a, **k: al), \
                mock.patch.object(night, "_late_check", lambda *a, **k: None), \
                mock.patch.object(predictions, "score_due", lambda *a, **k: 0), \
                mock.patch.object(mcpapi, "tidy_requests", lambda *a, **k: 0):
            night.tick(T0, log=lines.append)
        self.assertEqual(lines, ["događaji: hype_snapshots +3; zadnjih 15 min: cijene 16, transferi 5; upozorenja 2 "
                                 "(transferi novčanika, events:night:late)"])   # which feed is silent


if __name__ == "__main__":
    unittest.main()
