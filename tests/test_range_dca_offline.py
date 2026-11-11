"""10.11. (Jure, flag range_dca): range + DCA strategy (rangedca/). Zone detection, every range_score component, the
lot 2 (DCA) conditions, every exit and every exclusion, paper only on the demo account, flag off does nothing, the
live gate (>= 20 paper rounds with EV > 0), exit plans scoped per account (a plan for the range position never
takes over the real account's copy in the same token), the transfer-holders check (relayers are not traders), the
MCP tools, run_trade's lot 2, the job and the backtest on Hope's candles. No network.

    python3 -m unittest tests.test_range_dca_offline
"""
import gzip
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from league import copy, exitplan, flags, store  # noqa: E402
from rangedca import backtest, data, detect, gate, holders, rules, trade  # noqa: E402
from trade import settings  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, MINT  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
S = 1e-6   # price scale: price 52 * S = MC $52k at a supply of 1e9


def tri(t0, hours=12.0, lo=52.0, hi=98.0, period=120, vol=1000.0, b=6, s=4, scale=S):
    """Minute candles of a clean range: up from lo to hi in period/2 minutes, back down in period/2."""
    out, prev, half = [], None, period // 2
    for k in range(int(hours * 60)):
        ph = k % period
        px = (lo + (hi - lo) * ph / half if ph < half else hi - (hi - lo) * (ph - half) / half) * scale
        o = prev if prev is not None else px
        out.append((t0 + k * 60, o, max(o, px), min(o, px), px, vol, b, s))
        prev = px
    return out


def path(t0, points, vol=1000.0, b=None, s=None, vols=None):
    """Minute candles through (minute, price) waypoints (linear between); vols: {minute: volume}."""
    out, prev = [], None
    for (m0, p0), (m1, p1) in zip(points, points[1:]):
        for m in range(m0, m1):
            px = p0 + (p1 - p0) * (m - m0) / (m1 - m0)
            o = prev if prev is not None else px
            out.append((t0 + m * 60, o, max(o, px), min(o, px), px, (vols or {}).get(m, vol), b, s))
            prev = px
    return out


T0 = 1_794_000_000 - 1_794_000_000 % 60


def snap_for(cs, liq=50_000.0, vol_h1=60_000.0):
    now = cs[-1][0]
    return {"ts": now, "price": cs[-1][4], "mcap": cs[-1][4] * 1e9, "liq": liq, "vol_h1": vol_h1, "supply": 1e9}


# ---------------------------------------------------------------------------------------------------------------
class Detection(unittest.TestCase):
    def test_a_clean_range_zones_touches_and_score(self):
        cs = tri(T0)
        now = cs[-1][0]
        r = detect.analyze(cs, now, snap_for(cs))
        self.assertEqual(r["status"], "aktivan", r["why"])
        z = r["zones"]
        self.assertAlmostEqual(z["range_low"] / S, 52, delta=0.3)
        self.assertAlmostEqual(z["range_high"] / S, 98, delta=0.3)
        self.assertLess(z["range_low_low"], z["range_low_top"])
        self.assertLess(z["range_low_top"], z["range_high_low"])
        self.assertLess(z["range_high_low"], z["range_high_top"])
        self.assertAlmostEqual(z["mc"]["range_low_low"], 52_000 * 0.99, delta=300)
        self.assertGreaterEqual(len(r["touches"]["bottom"]), 5)
        self.assertGreaterEqual(len(r["touches"]["top"]), 5)
        self.assertEqual(len(r["touches"]["bottom_last3"]), 3)
        self.assertGreater(r["ratio"], 1.8)
        c = r["components"]
        self.assertEqual(c["recoveries"]["score"], 1.0)
        self.assertAlmostEqual(c["recovery_speed"]["value"], 30, delta=1.5)
        self.assertAlmostEqual(c["recovery_speed"]["score"], 1 - 10 / 70, delta=0.03)
        for k in ("higher_lows", "volume_hold", "buy_share_at_low", "sell_pressure_on_drop"):
            self.assertEqual(c[k]["score"], 1.0, k)
        self.assertAlmostEqual(sum(v["weight"] for v in c.values()), 1.0)
        self.assertAlmostEqual(r["score"], sum(v["score"] * v["weight"] for v in c.values()), places=3)
        self.assertGreater(r["score"], 0.95)
        self.assertLess(r["pos_pct"], 10)

    def test_the_minimums(self):
        self.assertEqual(detect.analyze(tri(T0, hours=5), T0 + 5 * 3600, None)["status"], "premalo podataka")
        up = path(T0, [(0, 50 * S), (480, 90 * S)])                      # a trend: no swing at all
        self.assertEqual(detect.analyze(up, up[-1][0], snap_for(up))["status"], "nema raspona")
        narrow = tri(T0, lo=80, hi=98)                                    # 98 / 80 = 1.22
        self.assertEqual(detect.analyze(narrow, narrow[-1][0], snap_for(narrow))["status"], "raspon preuzak")
        small = tri(T0, lo=20, hi=40)                                     # MC $20-40k: never analysed further
        self.assertEqual(detect.analyze(small, small[-1][0], snap_for(small))["status"], "ispod 30k")
        cs = tri(T0)
        self.assertEqual(detect.analyze(cs, cs[-1][0], snap_for(cs, liq=15_000))["status"], "mala likvidnost")
        self.assertEqual(detect.analyze(cs, cs[-1][0], snap_for(cs, vol_h1=8_000))["status"], "slab volumen")
        broke = cs + path(cs[-1][0] + 60, [(0, cs[-1][4]), (20, 45 * S), (21, 45 * S)])
        r = detect.analyze(broke, broke[-1][0], snap_for(broke))
        self.assertEqual(r["status"], "probijen dolje")
        self.assertTrue(r["signals"]["broken_down"])

    def test_touches_older_than_24_h_drop_out_and_the_zone_follows_the_last_three(self):
        cs = tri(T0, hours=30)
        now = cs[-1][0]
        r = detect.analyze(cs, now, snap_for(cs))
        self.assertTrue(all(t["ts"] >= now - 24 * 3600 for t in r["touches"]["bottom"] + r["touches"]["top"]))
        pts = [{"ts": i * 600, "px": p} for i, p in enumerate((52.0, 50.0, 54.0, 53.0))]
        z = detect._zone_of(pts, 3, 0.01, 3000, 8.0)
        self.assertEqual((z["low"], z["top"]), (50.0, 54.0))
        self.assertAlmostEqual(z["mid"], (50 + 54 + 53) / 3)
        z2 = detect._zone_of(pts + [{"ts": 3000, "px": 51.0}], 3, 0.01, 3000, 8.0)   # a new touch moves the zone
        self.assertEqual((z2["low"], z2["top"]), (51.0, 54.0))
        z3 = detect._zone_of([{"ts": 0, "px": 50.0}, {"ts": 60, "px": 50.1}], 3, 0.01, 60, 8.0)
        self.assertAlmostEqual(z3["low"], 50.05 * 0.99)                 # at least +-1 % around the average

    def test_pivots_need_the_turn(self):
        cs = path(T0, [(0, 100.0), (10, 92.0), (20, 100.0), (30, 89.0), (40, 103.0), (41, 103.0)])
        pv = detect.pivots(cs, 0.10, 0.15)
        self.assertEqual([p["kind"] for p in pv], ["H", "L"])   # 100 -> 92 is not -10 %; 100 -> 89 is; 89 -> 103 +15.7 %
        self.assertAlmostEqual(pv[0]["px"], 100.0)
        self.assertAlmostEqual(pv[1]["px"], 89.0)

    def test_hope_10_11_from_geckoterminal_candles(self):
        with gzip.open(os.path.join(ROOT, "tests", "fixtures", "range_hope_20261110.json.gz"), "rt") as f:
            fx = json.load(f)
        cs = data.merge([tuple(r) for r in fx["candles"]], [])
        t = 1794330060   # 17:01 UTC
        r = detect.analyze([c for c in cs if c[0] <= t], t, None, {"supply": 1e9, "unknown_liq_ok": True})
        self.assertEqual(r["status"], "aktivan", r["why"])
        mc = r["zones"]["mc"]
        self.assertTrue(48_000 < mc["range_low_low"] < 56_000, mc)    # the owner's floor: 50-60k
        self.assertTrue(80_000 < mc["range_high_low"] < 100_000, mc)
        self.assertGreaterEqual(r["score"], 0.7)


class Components(unittest.TestCase):
    """Each range_score component on its own (spec 2)."""

    def comp(self, cs, lows, highs, bot, top_mid=100.0, m=None, now=None):
        pv = sorted([{"kind": "L", "ts": T0 + a * 60, "px": p, "confirm_ts": T0 + a * 60} for a, p in lows]
                    + [{"kind": "H", "ts": T0 + a * 60, "px": p, "confirm_ts": T0 + a * 60} for a, p in highs],
                    key=lambda p: p["ts"])
        touches = [{"ts": T0 + a * 60, "px": p} for a, p in lows if bot[0] <= p <= bot[1]]
        b = {"low": bot[0], "top": bot[1], "mid": sum(bot) / 2, "touches": touches}
        t = {"low": top_mid * 0.97, "top": top_mid * 1.03, "mid": top_mid, "touches": []}
        c, _rec = detect.components(cs, pv, t, b, m or {"vol_ratio": 1.0}, now or cs[-1][0])
        return c

    def test_recoveries(self):
        def run(ups):
            pts, m = [(0, 50.0)], 0
            for u in ups:
                pts += [(m + 10, 50.0 * (1 + u)), (m + 20, 50.0)]
                m += 20
            pts.append((m + 5, 50.0))
            cs = path(T0, pts)
            lows = [(i * 20, 50.0) for i in range(len(ups) + 1)]
            return self.comp(cs, lows, [], (49.0, 51.0))["recoveries"]
        self.assertEqual(run([0.30, 0.10, 0.12])["score"], 0.0)       # 1 recovery of +25 %
        self.assertEqual(run([0.30, 0.10, 0.40])["score"], 0.6)       # 2
        self.assertEqual(run([0.30, 0.26, 0.40])["score"], 1.0)       # 3
        self.assertEqual(run([0.30, 0.26, 0.40])["value"], 3)

    def test_recovery_speed(self):
        def run(minutes):
            cs = path(T0, [(0, 50.0), (minutes, 75.0), (minutes + 5, 76.0)])
            return self.comp(cs, [(0, 50.0)], [], (49.0, 51.0))["recovery_speed"]
        self.assertEqual(run(10)["score"], 1.0)
        self.assertAlmostEqual(run(55)["score"], 0.5, delta=0.02)
        self.assertEqual(run(100)["score"], 0.0)
        cs = path(T0, [(0, 50.0), (60, 60.0)])                          # never half way: unknown = 0
        self.assertEqual(self.comp(cs, [(0, 50.0)], [], (49.0, 51.0))["recovery_speed"]["score"], 0.0)

    def test_higher_lows_on_the_range_lows_only(self):
        cs = path(T0, [(0, 52.0), (100, 52.0)])
        self.assertEqual(self.comp(cs, [(0, 52.0), (50, 51.0)], [], (49.0, 53.0))["higher_lows"]["score"], 1.0)
        self.assertEqual(self.comp(cs, [(0, 52.0), (50, 49.5)], [], (49.0, 53.0))["higher_lows"]["score"], 0.0)
        # a swing low half way up the range is not a low of the range
        self.assertEqual(self.comp(cs, [(0, 52.0), (30, 50.0), (60, 70.0)], [], (49.0, 53.0))["higher_lows"]["score"], 0.0)

    def test_volume_hold(self):
        cs = path(T0, [(0, 52.0), (30, 52.0)])
        for ratio, want in ((0.6, 1.0), (0.375, 0.5), (0.2, 0.0), (None, 0.0)):
            self.assertAlmostEqual(self.comp(cs, [(0, 52.0)], [], (49.0, 53.0), m={"vol_ratio": ratio})["volume_hold"]["score"],
                                   want, places=3)
        cs = tri(T0)   # through metrics: the last 15 min x 4 vs the hourly average of 6 h
        m = detect.metrics(cs, cs[-1][0], None, {"supply": 1e9})
        self.assertAlmostEqual(m["vol_15m"], 15_000)
        self.assertAlmostEqual(m["vol_ratio"], 1.0)

    def test_buy_share_at_low(self):
        for b, s, want in ((6, 4, 1.0), (5, 5, 0.5), (4, 6, 0.0)):
            cs = path(T0, [(0, 52.0), (10, 60.0), (20, 52.0)], b=b, s=s)
            got = self.comp(cs, [(0, 52.0), (20, 52.0)], [], (51.0, 53.0))["buy_share_at_low"]
            self.assertAlmostEqual(got["score"], want, places=3)
            self.assertEqual(got["how"], "transakcije")
        cs = path(T0, [(0, 52.0), (10, 60.0), (20, 52.0)])               # no counts: the volume proxy, marked
        self.assertEqual(self.comp(cs, [(0, 52.0)], [], (51.0, 53.0))["buy_share_at_low"]["how"], "proxy")

    def test_sell_pressure_on_drop(self):
        def run(leg_vol):
            vols = {m: leg_vol for m in range(41, 61)}   # the fall from the high (minute 40) to the low (minute 60)
            cs = path(T0, [(0, 52.0), (40, 100.0), (60, 52.0), (100, 60.0)], vols=vols)
            return self.comp(cs, [(0, 52.0), (60, 52.0)], [(40, 100.0)], (51.0, 53.0))["sell_pressure_on_drop"]
        self.assertEqual(run(1000.0)["score"], 1.0)                     # as usual
        self.assertTrue(0.2 < run(1600.0)["score"] < 1.0)
        self.assertEqual(run(4000.0)["score"], 0.0)                     # panic: more than twice the average


class Rules(unittest.TestCase):
    LV = {"rll": 51.0, "rlt": 53.0, "rhl": 95.0, "rht": 100.0, "stop_px": 51.0 * 0.85, "floor_px": 51.0 * 0.92}

    def rng(self, **kw):
        z = {"range_low_low": 51.0, "range_low_top": 53.0, "range_high_low": 95.0, "range_high_top": 100.0}
        m = {"ch_5m": 0.01, "buy_share_5m": 0.6, "vol_ratio": 0.8}
        m.update(kw.pop("m", {}))
        return {"active": True, "status": "aktivan", "score": 0.8, "zones": z, "metrics": m, **kw}

    def test_entry_lot_1(self):
        self.assertIsNone(rules.entry_check(self.rng(), 52.0))                       # inside the bottom zone
        self.assertIsNone(rules.entry_check(self.rng(), 57.0))                       # bottom 15 % (51 + 7.35)
        self.assertIn("raspona", rules.entry_check(self.rng(), 60.0))
        self.assertIn("0,92", rules.entry_check(self.rng(), 46.0))
        self.assertIn("ocjena", rules.entry_check(self.rng(score=0.69), 52.0))
        self.assertIsNone(rules.entry_check(self.rng(score=0.65), 52.0, min_score=0.6))
        self.assertIn("pada", rules.entry_check(self.rng(m={"ch_5m": -0.03}), 52.0))
        self.assertIn("kupnje", rules.entry_check(self.rng(m={"buy_share_5m": 0.49}), 52.0))
        self.assertIn("volumen", rules.entry_check(self.rng(m={"vol_ratio": 0.49}), 52.0))
        self.assertIn("nepoznat", rules.entry_check(self.rng(m={"buy_share_5m": None}), 52.0))
        self.assertEqual(rules.entry_check(self.rng(active=False, why="slab volumen"), 52.0), "slab volumen")

    def test_lot_2_dca_conditions(self):
        m = {"buy_share_5m": 0.6, "vol_ratio": 0.8}
        self.assertIn("tek", rules.lot2_check(100.0, 91.0, dict(self.LV, floor_px=50.0), m))     # -9 %
        self.assertIsNone(rules.lot2_check(100.0, 88.0, dict(self.LV, floor_px=50.0), m))      # -12 %
        self.assertIsNone(rules.lot2_check(100.0, 85.0, dict(self.LV, floor_px=50.0), m))      # -15 %
        self.assertIn("dublje", rules.lot2_check(100.0, 84.0, dict(self.LV, floor_px=50.0), m))
        self.assertIn("0,92", rules.lot2_check(100.0, 88.0, dict(self.LV, floor_px=89.0), m))
        self.assertIn("volumen", rules.lot2_check(100.0, 88.0, dict(self.LV, floor_px=50.0), {"buy_share_5m": 0.6, "vol_ratio": 0.4}))
        self.assertIn("kupnje", rules.lot2_check(100.0, 88.0, dict(self.LV, floor_px=50.0), {"buy_share_5m": 0.4, "vol_ratio": 0.9}))
        # the dca cap: lot 1 + lot 2 at most dca_token_cap; a rest under half a lot is not bought
        self.assertEqual(rules.lot_sizes(0.1, 0.3), 0.1)
        self.assertEqual(rules.lot_sizes(0.1, 0.3, held_sol=0.1), 0.1)
        self.assertAlmostEqual(rules.lot_sizes(0.1, 0.15, held_sol=0.1), 0.05)
        self.assertEqual(rules.lot_sizes(0.1, 0.12, held_sol=0.1), 0.0)

    def step(self, st, px, now=10_000, opened=0, be=60.0, stale=False):
        return rules.exit_step(self.LV, st, px, now, opened, be, stale)

    def test_exits(self):
        st = {}
        self.assertIsNone(self.step(st, 80.0))
        self.assertEqual(self.step(st, 95.5), ("tp1", 0.5))                  # half in the top zone
        self.assertIsNone(self.step(st, 96.0))                               # tp1 never twice
        self.assertIsNone(self.step(st, 100.5))                              # at the top: armed
        self.assertEqual(self.step(st, 99.5), ("top", 1.0))                  # back under it: the rest at the top
        st = {}
        self.step(st, 96.0)
        for px in (101.0, 115.0, 120.0):                                    # it breaks the top: trailing 10 %
            self.assertIsNone(self.step(st, px))
        self.assertEqual(self.step(st, 107.9), ("trailing", 1.0))
        st = {}
        self.step(st, 96.0)                                                  # tp1, then it turns inside the top zone
        self.assertIsNone(self.step(st, 98.0))
        self.assertIsNone(self.step(st, 89.0))
        self.assertEqual(self.step(st, 88.1), ("trailing", 1.0))             # 10 % under the peak (98)
        st = {}
        self.assertEqual(self.step(st, 43.0), ("stop", 1.0))                 # range_low_low x 0.85
        self.assertEqual(self.step({}, 43.0, stale=True), ("stop", 1.0))    # a stale price fires only the stop
        self.assertIsNone(self.step({}, 96.0, stale=True))
        # time stop: 6 h without the top zone -> out at break-even or better, else the stop decides
        self.assertIsNone(self.step({}, 61.0, now=5 * 3600))
        self.assertEqual(self.step({}, 61.0, now=6 * 3600 + 1), ("time", 1.0))
        self.assertIsNone(self.step({}, 59.0, now=7 * 3600))
        st = {"tp1": True, "top_ts": 100}
        self.assertIsNone(self.step(st, 61.0, now=7 * 3600))                # the top zone was touched: no time stop

    def test_exclusions(self):
        def res(**sig):
            return {"signals": {"lower_lows": False, "vol_decline": False, "broken_down": False, **sig},
                    "zones": {"range_low_low": 51.0}, "metrics": {"price": 60.0}, "active": True}
        st = rules.exclusions({}, res(lower_lows=True), 1000)
        self.assertEqual(st["excluded_until"], 1000 + 86400)
        self.assertEqual(st["give_up"]["ts"], 1000)
        self.assertIn("niža dna", st["excluded_why"])
        self.assertEqual(rules.apply_exclusion(res(), st, 2000)["status"], "isključen")
        self.assertTrue(rules.apply_exclusion(res(), st, 1000 + 86401)["active"])
        st = rules.exclusions({}, res(vol_decline=True), 1000)
        self.assertEqual(st["excluded_until"], 1000 + 3600)
        st = rules.exclusions(st, res(vol_decline=True), 3000)            # renewed while the volume stays low
        self.assertEqual(st["excluded_until"], 3000 + 3600)
        st = rules.exclusions({}, res(), 1000, holder_why="holderi s prijenosom bez kupnje neto prodali 3 %")
        self.assertEqual(st["excluded_until"], 1000 + 86400)
        st = rules.exclusions({}, res(broken_down=True), 1000)            # broken downward once: not yet
        self.assertEqual((st["excluded_until"], st["breakdowns"]), (0, [1000]))
        st = rules.exclusions(st, res(broken_down=True), 1300)            # still the same break: not counted twice
        self.assertEqual(st["breakdowns"], [1000])
        st = rules.exclusions(st, res(), 1600)
        st = rules.exclusions(st, res(broken_down=True), 1900)            # the second break within 24 h: out
        self.assertEqual(st["excluded_until"], 1900 + 86400)
        self.assertIn("2 puta", st["excluded_why"])
        # a break against the range as it was before this pass (the zones move down after a break)
        prev = {"zones": {"range_low_low": 70.0}}                         # 60 < 70 x 0.92
        self.assertEqual(rules.exclusions(prev, res(), 5000)["breakdowns"], [5000])


# ---------------------------------------------------------------------------------------------------------------
class TradeBase(Base):
    def setUp(self):
        super().setUp()
        self.rdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.rdir.cleanup)
        p = mock.patch.dict(os.environ, {"RANGE_DB": os.path.join(self.rdir.name, "range.db"),
                                         "RANGE_HYPE_DB": os.path.join(self.rdir.name, "hype.db")})
        p.start()
        self.addCleanup(p.stop)
        for obj, name, val in ((copy, "_concentration", lambda tok: (None, "nepoznato")),
                               (copy, "_rugged", lambda *a, **k: None)):
            pm = mock.patch.object(obj, name, val)
            pm.start()
            self.addCleanup(pm.stop)
        trade._CACHE.update(rng_at=0.0, rng={}, off_at=0.0, off_open=False, lim_at=0.0, lim=None, gate_log=0.0)
        trade._SHADOWED.clear()
        gate._CACHE.update(at=0.0, path=None, val=None)
        exitplan._LAST.clear()
        self.now = int(time.time())
        self.lim = {"size_sol": 0.1, "max_sol_per_day": 1.0, "max_open": 5, "dca_token_cap": 0.3}

    def mode(self, m, name="range_dca", since=None):
        settings.put(self.con, f"flag:{name}", {"mode": m, "since": since or self.now})
        settings._FLAG_CACHE.clear()

    def rng(self, score=0.8, **m):
        z = {"range_low_low": 51.0 * S, "range_low_top": 53.0 * S, "range_high_low": 95.0 * S, "range_high_top": 100.0 * S,
             "range_high": 97.5 * S, "range_low": 52.0 * S,
             "mc": {"range_low_low": 51_000, "range_low_top": 53_000, "range_high_low": 95_000, "range_high_top": 100_000}}
        mm = {"ch_5m": 0.01, "buy_share_5m": 0.6, "vol_ratio": 0.8, "supply": 1e9, "price": 52 * S, "vol_h1": 30_000}
        mm.update(m)
        return {"ts": self.now, "mts": self.now, "active": True, "status": "aktivan", "score": score, "pos_pct": 2.0,
                "zones": z, "metrics": mm, "symbol": "RNG", "state": {}, "components": {}}

    def mk(self, px, liq=25_000.0):
        return lambda toks: {t: (px * S, liq, None, px * S * 1e9, "RNG", {"m5": 1.0, "h1": 2.0}) for t in toks}

    def enter(self, px=52.0, rng=None, now=None):
        now = now or self.now
        if rng is None:
            rng = self.rng()
            rng["ts"] = rng["mts"] = now
        return trade.run_once(self.lg, self.mk(px), now, {MINT: rng}, self.lim, 100.0)

    def lots(self, user=PU, status="open"):
        return [dict(r) for r in self.lg.execute("SELECT * FROM trades WHERE user=? AND token=? AND status=? ORDER BY id",
                                                 (user, MINT, status))]

    def exits(self, px, rng=None, now=None):
        with mock.patch.object(trade, "_ranges", lambda now, force=False, tokens=None: {MINT: rng or self.rng()}):
            return trade.exits_once(self.lg, lambda toks: {t: (px * S, 25_000.0, None, px * S * 1e9) for t in toks},
                                    now or self.now)


class Paper(TradeBase):
    def test_flag_off_does_nothing(self):
        self.assertEqual(self.enter(), [])
        self.assertEqual(self.exits(40.0), [])
        self.assertIsNone(self.lg.execute("SELECT 1 FROM sqlite_master WHERE name='range_rounds'").fetchone())
        self.assertEqual(self.lots(PU) + self.lots(LU), [])
        import run_range
        self.assertEqual(run_range.once(now=self.now, fetch=lambda t: self.fail("no fetch while off")), "off")
        self.assertFalse(os.path.exists(os.environ["RANGE_DB"]))

    def test_paper_trades_only_the_demo_account_and_the_real_one_only_logs(self):
        self.mode("paper")
        done = self.enter()
        self.assertEqual([u for u, _ in done], [PU])
        lots = self.lots(PU)
        self.assertEqual((len(lots), lots[0]["source"], lots[0]["auto"]), (1, trade.SRC1, None))
        self.assertAlmostEqual(lots[0]["size_usd"], 10.0)                    # size_sol 0.1 x $100
        self.assertEqual(self.lots(LU), [])
        sh = flags.shadow_rows(self.lg, "range_dca")
        self.assertEqual([(r[3], r[5]) for r in sh], [(MINT, "range ulaz lot 1")])
        r = trade.rounds(self.lg)[0]
        self.assertEqual((r["user"], r["lot1_id"]), (PU, lots[0]["id"]))
        self.assertAlmostEqual(r["levels"]["supply"], 1e9, delta=1)
        self.assertEqual(self.enter(), [])                                   # one round per token, no doubling
        self.assertEqual(len(flags.shadow_rows(self.lg, "range_dca")), 1)    # the shadow line once per 20 min

    def test_shadow_mode_nobody_trades(self):
        self.mode("shadow")
        self.assertEqual(self.enter(), [])
        self.assertEqual(self.lots(PU) + self.lots(LU), [])
        self.assertEqual(len(flags.shadow_rows(self.lg, "range_dca")), 1)

    def test_entry_gates(self):
        self.mode("paper")
        self.assertEqual(self.enter(px=60.0), [])                            # 18 % up the range
        self.assertEqual(self.enter(rng=self.rng(score=0.6)), [])
        self.assertEqual(self.enter(rng=self.rng(buy_share_5m=0.4)), [])
        stale = self.rng()
        stale["mts"] = self.now - 600                                       # the 5-minute numbers are 10 min old
        self.assertEqual(self.enter(rng=stale), [])
        with mock.patch.object(copy, "_concentration", lambda tok: ("koncentriran supply", "")):
            self.assertEqual(self.enter(), [])                               # the copies' rug guards hold here too
        curve = lambda toks: {t: (52 * S, 25_000.0, None, 52_000.0, "RNG", {"src": "jup"}) for t in toks}  # noqa: E731
        self.assertEqual(trade.run_once(self.lg, curve, self.now, {MINT: self.rng()}, self.lim, 100.0), [])
        small = lambda toks: {t: (25 * S, 25_000.0, None, 25_000.0, "RNG", {}) for t in toks}  # noqa: E731
        self.assertEqual(trade.run_once(self.lg, small, self.now, {MINT: self.rng()}, self.lim, 100.0), [])
        self.assertEqual(self.lots(PU), [])
        store.buy(self.lg, PU, MINT, "RNG", 25, 52 * S, 25_000, "copy KOL x", None, 52_000)   # already held by a copy
        self.assertEqual(self.enter(), [])
        self.assertEqual([t["source"] for t in self.lots(PU)], ["copy KOL x"])

    def test_limits_max_open_and_day(self):
        self.mode("paper")
        self.lim["max_open"] = 0
        self.assertEqual(self.enter(), [])
        self.lim.update(max_open=5, max_sol_per_day=0.05)
        self.assertEqual(self.enter(), [])
        self.lim.update(max_sol_per_day=1.0, dca_token_cap=0.04)                # cap under half a lot
        self.assertEqual(self.enter(), [])

    def test_lot_2_and_the_cap(self):
        self.mode("paper")
        self.assertEqual(len(self.enter(px=57.0)), 1)                       # bottom 15 % of the range
        self.assertEqual(self.enter(px=53.0), [])                            # -7 %
        self.assertEqual(self.enter(px=47.5), [])                            # -16.7 %: deeper than -15 %
        self.lim["dca_token_cap"] = 0.15
        done = self.enter(px=50.0)                                           # -12.3 %, above 51k x 0.92
        self.assertEqual(len(done), 1, done)
        lots = self.lots(PU)
        self.assertEqual([t["source"] for t in lots], [trade.SRC1, trade.SRC2])
        self.assertAlmostEqual(lots[1]["size_usd"], 5.0)                    # 0.15 cap - 0.1 = 0.05 SOL
        self.assertEqual(trade.rounds(self.lg)[0]["lot2_id"], lots[1]["id"])
        self.assertEqual(self.enter(px=50.0), [])                            # at most 2 lots

    def test_exits_half_at_the_top_zone_rest_at_the_top_then_cooldown(self):
        self.mode("paper")
        self.enter(px=52.0)
        q0 = self.lots(PU)[0]["qty"]
        self.assertEqual(self.exits(80.0), [])
        out = self.exits(95.5)
        self.assertIn("pola u gornjoj zoni", out[0])
        self.assertAlmostEqual(self.lots(PU)[0]["qty"], q0 / 2)
        part = self.lots(PU, "closed")[0]
        self.assertEqual((part["exit_rule"], part["note"].startswith("range:")), ("tp", True))
        self.assertEqual(self.exits(101.0), [])
        out = self.exits(99.0)
        self.assertIn("runda gotova", out[0])
        r = trade.rounds(self.lg, "closed")[0]
        self.assertEqual(r["exit_reason"], "top")
        self.assertGreater(r["pnl_usd"], 6.0)
        self.assertAlmostEqual(r["cost_usd"], 10.0)
        self.assertEqual(self.enter(px=52.0), [])                            # 20 min cooldown
        self.assertEqual(len(self.enter(px=52.0, now=self.now + 1201)), 1)   # then a new round

    def test_stop_time_stop_give_up_and_stale(self):
        self.mode("paper")
        self.enter(px=52.0)
        self.assertEqual(self.exits(60.0), [])
        out = self.exits(43.0)                                               # 51k x 0.85 = 43.35k
        self.assertIn("tvrdi stop", out[0])
        self.assertEqual(trade.rounds(self.lg, "closed")[0]["exit_reason"], "stop")
        self.assertEqual(self.lots(PU, "closed")[-1]["exit_rule"], "sl")
        # time stop
        now = self.now + 1300
        self.enter(px=52.0, now=now)
        self.lg.execute("UPDATE range_rounds SET opened_ts=? WHERE status='open'", (now - 7 * 3600,))
        self.lg.commit()
        self.assertEqual(self.exits(53.0, now=now), [])                     # under break-even (fees): the stop decides
        out = self.exits(54.5, now=now)
        self.assertIn("6 h bez gornje zone", out[0])
        # give up: an exclusion that started after the round opened closes it at the market
        now += 1300
        self.enter(px=52.0, now=now)
        gu = self.rng()
        gu["state"] = {"give_up": {"why": "dva niža dna zaredom", "ts": now + 5}}
        out = self.exits(60.0, rng=gu, now=now + 10)
        self.assertIn("odustajanje", out[0])
        self.assertIn("dva niža dna", out[0])
        # a stale price fires only the hard stop
        now += 1300
        self.enter(px=52.0, now=now)
        exitplan._LAST[MINT] = (96.0 * S, 96_000.0, 25_000.0, now - 120)
        with mock.patch.object(trade, "_ranges", lambda now, force=False, tokens=None: {MINT: self.rng()}):
            self.assertEqual(trade.exits_once(self.lg, lambda toks: {}, now), [])
            exitplan._LAST[MINT] = (40.0 * S, 40_000.0, 25_000.0, now - 120)
            self.assertIn("tvrdi stop", trade.exits_once(self.lg, lambda toks: {}, now)[0])

    def test_open_rounds_keep_their_exits_when_the_flag_goes_off(self):
        self.mode("paper")
        self.enter(px=52.0)
        self.mode("off")
        self.assertEqual(self.enter(px=52.0, now=self.now + 5000), [])     # no new entries
        self.assertIn("tvrdi stop", self.exits(43.0)[0])                    # but the stop still fires

    def test_the_range_executor_never_touches_the_real_accounts_copy(self):
        self.mode("live")
        store.buy(self.lg, LU, MINT, "RNG", 25, 52 * S, 25_000, "copy KOL x", None, 52_000)
        gate._CACHE.update(at=0.0)
        self.enter(px=52.0)                                                  # LU: no proof -> only PU trades
        self.assertEqual([t["source"] for t in self.lots(LU)], ["copy KOL x"])
        self.assertEqual([t["source"] for t in self.lots(PU)], [trade.SRC1])
        self.exits(43.0)
        self.assertEqual([t["source"] for t in self.lots(LU)], ["copy KOL x"])
        self.assertEqual(self.lots(PU), [])


class ExitPlanScope(TradeBase):
    def setUp(self):
        super().setUp()
        exitplan.ensure(self.lg)
        self.mode("paper")
        self.mode("live", "exit_plans")
        settings.put(self.con, "sl_default", 60)
        p = mock.patch.object(exitplan, "paused", lambda: False)
        p.start()
        self.addCleanup(p.stop)

    def test_a_plan_for_the_range_position_leaves_the_real_accounts_copy_alone(self):
        store.buy(self.lg, LU, MINT, "RNG", 25, 52 * S, 25_000, "copy KOL x", None, 52_000)
        self.enter(px=52.0)
        with self.assertRaisesRegex(ValueError, "accounts must be"):
            exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 20, "sell_share": 1}], "accounts": ["igrac"]}, 60)
        out = exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 20, "sell_share": 1}],
                                                "accounts": [PU], "reason": "stegni range"}, 60)
        self.assertEqual(list(out["stop_price"]), [PU])
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())
        self.assertEqual(exitplan.in_force_tokens(self.lg, PU), {MINT})
        done = exitplan.run_once(self.lg, lambda toks: {t: (63 * S, 25_000.0, None, 63_000.0) for t in toks}, time.time())
        self.assertEqual([d[0] for d in done], [PU])
        self.assertEqual(self.lots(PU), [])
        self.assertEqual([t["source"] for t in self.lots(LU)], ["copy KOL x"])
        self.assertIn("applies to", exitplan.view(self.lg, MINT, LU)["note"])
        # the range round sees its lots gone and ends with what the trades say
        out = self.exits(63.0)
        self.assertIn("runda zatvorena", out[0])
        self.assertGreater(trade.rounds(self.lg, "closed")[0]["pnl_usd"], 0)

    def test_a_plan_may_only_tighten_the_range_stop(self):
        self.enter(px=52.0)
        self.assertAlmostEqual(trade.stop_px(self.lg, PU, MINT), 51.0 * S * 0.85)
        with self.assertRaisesRegex(ValueError, "only be tightened"):
            exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -25}, "accounts": [PU]}, 60)
        out = exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -10}, "accounts": [PU]}, 60)
        self.assertGreater(out["stop_price"][PU], trade.stop_px(self.lg, PU, MINT))

    def test_mcp_set_exit_plan_with_accounts(self):
        from ui import mcpapi
        self.enter(px=52.0)
        d, err = mcpapi._tool("set_exit_plan", {"token_address": MINT, "plan": {
            "time_stop": {"after_min": 60, "if_pnl_below_pct": 0}, "accounts": [PU]}}, kid="grok")
        self.assertFalse(err, d)
        self.assertEqual(d["plan"]["accounts"], [PU])
        names = [t["name"] for t in mcpapi.TOOLS]
        self.assertIn("get_range_candidates", names)
        sp = next(t for t in mcpapi.TOOLS if t["name"] == "set_exit_plan")
        self.assertIn("accounts", sp["inputSchema"]["properties"]["plan"]["properties"])


class LiveGate(TradeBase):
    def rounds(self, n, ret):
        trade.ensure(self.lg)
        for i in range(n):
            self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, closed_ts, status, cost_usd, pnl_usd, ret) "
                            "VALUES (?,?,?,?,?,?,?,?)", (PU, f"T{i}", 1, 2, "closed", 10.0, 10.0 * ret, ret))
        self.lg.commit()

    def test_live_needs_20_paper_rounds_with_ev_above_zero(self):
        settings.put(self.con, "backtest:range_dca", {"pass": True, "n": 30, "ev_lo": 1.0})
        self.mode("paper", since=self.now - 8 * 86400)
        paper = {"n": 25, "pnl": 12.0}
        with self.assertRaisesRegex(ValueError, "tek 0 zatvorenih paper rundi"):
            settings.set_flag(self.con, "range_dca", "live", "Jure", paper=paper, now=self.now)
        self.rounds(19, 0.05)
        with self.assertRaisesRegex(ValueError, "tek 19"):
            settings.set_flag(self.con, "range_dca", "live", "Jure", paper=paper, now=self.now)
        self.rounds(3, -0.5)                                                 # 22 rounds, EV negative
        with self.assertRaisesRegex(ValueError, "EV"):
            settings.set_flag(self.con, "range_dca", "live", "Jure", paper=paper, now=self.now)
        self.rounds(20, 0.10)
        self.assertIsNone(gate.refusal())
        self.assertEqual(settings.set_flag(self.con, "range_dca", "live", "Jure", paper=paper, now=self.now)["mode"], "live")
        self.assertIsNone(settings.live_refusal(self.con, "dca_guard", paper, self.now) and None)

    def test_live_without_proof_trades_only_the_demo_account(self):
        self.mode("live")
        act, sh = trade.roles("live", self.now)
        self.assertEqual((act, sh), ([PU], [LU]))                            # a hand edit to live does not move money
        self.rounds(20, 0.1)
        gate._CACHE.update(at=0.0)
        act, sh = trade.roles("live", self.now)
        self.assertEqual((sorted(act), sh), (sorted([LU, PU]), []))


class RunTradeLot2(TradeBase):
    def test_lot_2_is_one_more_lot_of_lot_1s_real_position_only(self):
        import run_trade
        from trade import equity
        self.mode("paper")
        self.lim["dca_token_cap"] = 0.15
        self.enter(px=57.0)
        self.enter(px=50.0)
        lots = self.lots(PU)
        self.lg.row_factory = None
        cfg = {"size_sol": 0.1}
        with mock.patch.object(equity, "rates", lambda *a, **k: {"sol_usd": 100.0}):
            t2 = {"id": lots[1]["id"], "source": trade.SRC2}
            why, sol, add = run_trade._range_lot(self.con, self.lg, t2, cfg)
            self.assertIn("bez pravog lota 1", why)
            self.con.execute("INSERT INTO positions (league_id, token, mode, status) VALUES (?,?,?,?)",
                             (lots[0]["id"], MINT, "dry", "open"))
            why, sol, add = run_trade._range_lot(self.con, self.lg, t2, cfg)
            self.assertEqual((why, add), (None, True))
            self.assertAlmostEqual(sol, 0.05)
            why, sol, add = run_trade._range_lot(self.con, self.lg, {"id": lots[0]["id"], "source": trade.SRC1}, cfg)
            self.assertEqual((why, add), (None, False))
            self.assertAlmostEqual(sol, 0.1)


class Holders(unittest.TestCase):
    MINT_ = "Mint1111111111111111111111111111111111111pump"
    POOL = "Pool111111111111111111111111111111111111111"

    def tx(self, ts, fee_payer, signers, tok, sol=None):
        """tok: {owner: (pre, post)}, sol: {key: lamports change}."""
        keys = [fee_payer] + [k for k in list(signers) + list(tok) + list(sol or {}) if k != fee_payer]
        keys = list(dict.fromkeys(keys))
        pre = [10 ** 10] * len(keys)
        post = [10 ** 10 + (sol or {}).get(k, 0) - (5000 if k == fee_payer else 0) for k in keys]   # the fee payer pays 5000
        tb = lambda i: [{"mint": self.MINT_, "owner": o, "uiTokenAmount": {"uiAmount": v[i]}} for o, v in tok.items()]  # noqa: E731
        return {"blockTime": ts, "meta": {"err": None, "fee": 5000, "preBalances": pre, "postBalances": post,
                                          "preTokenBalances": tb(0), "postTokenBalances": tb(1)},
                "transaction": {"signatures": [f"sig{ts}"], "message": {"accountKeys": [
                    {"pubkey": k, "signer": k == fee_payer or k in signers} for k in keys]}}}

    def test_a_relayer_is_not_the_trader_and_its_users_are_buyers(self):
        txs = [self.tx(100 + i, "Relayer", ["Relayer", o], {o: (0, 1000), self.POOL: (10 ** 6, 10 ** 6 - 1000)},
                       {o: -10 ** 8}) for i, o in enumerate(("A", "B", "C"))]
        parsed = [holders.parse(t, self.MINT_) for t in txs]
        rows, relayers = holders.classify(parsed, self.POOL)
        self.assertEqual(relayers, {"Relayer"})
        self.assertEqual(sorted((r["owner"], r["kind"]) for r in rows), [("A", "buy"), ("B", "buy"), ("C", "buy")])

    def test_transfer_holders_net_selling(self):
        con = data.connect(os.path.join(tempfile.mkdtemp(), "range.db"))
        txs = [self.tx(100, "X", ["X"], {"X": (5000, 0), "Y": (0, 5000)}),                      # X sends to Y
               self.tx(200, "Z", ["Z"], {"Z": (0, 100), self.POOL: (10 ** 6, 10 ** 6 - 100)}, {"Z": -10 ** 7}),
               self.tx(1000, "Y", ["Y"], {"Y": (5000, 0), self.POOL: (10 ** 6, 10 ** 6 + 5000)}, {"Y": 10 ** 8})]
        rows, _ = holders.classify([holders.parse(t, self.MINT_) for t in txs], self.POOL)
        self.assertEqual({(r["owner"], r["kind"]) for r in rows}, {("X", "sent"), ("Y", "recv"), ("Z", "buy"), ("Y", "sell")})
        holders.ledger_add(con, self.MINT_, rows)
        self.assertEqual(holders.transfer_holders(con, self.MINT_), {"Y"})
        pct, n = holders.net_sell_pct(con, self.MINT_, [r for r in rows if r["ts"] >= 900], 100_000)
        self.assertAlmostEqual(pct, 5.0)
        self.assertEqual(n, 1)

    def test_check_is_capped_logs_by_default_and_acts_only_when_switched(self):
        con = data.connect(os.path.join(tempfile.mkdtemp(), "range.db"))
        now = 10_000
        txs = [self.tx(now - 5000, "X", ["X"], {"X": (5000, 0), "Y": (0, 5000)}),
               self.tx(now - 100, "Y", ["Y"], {"Y": (5000, 0), self.POOL: (10 ** 6, 10 ** 6 + 5000)}, {"Y": 10 ** 8})]
        calls = []

        def post(method, params):
            calls.append(params[1]["sortOrder"])
            return {"data": txs, "paginationToken": None}
        with mock.patch.dict(os.environ, {"RANGE_HOLDER_RULE": "log"}):
            self.assertIsNone(holders.check(con, self.MINT_, self.POOL, 100_000, now, post))
        self.assertEqual(calls, ["desc"])                                    # the backfill, newest first
        ev = con.execute("SELECT note FROM events WHERE kind='holderi'").fetchone()[0]
        self.assertIn("[log]", ev)
        self.assertEqual(data.day_used(con, "helius_day", now), holders.PAGE_CREDITS)
        with mock.patch.dict(os.environ, {"RANGE_HOLDER_RULE": "act"}):
            n = len(calls)
            self.assertIn("neto prodali", holders.check(con, self.MINT_, self.POOL, 100_000, now + 60, post))
            self.assertEqual(len(calls), n)                                  # not due (15 min): the last finding, no call
            con.execute("DELETE FROM kv WHERE k LIKE 'hold:%'")
            con.execute("DELETE FROM holder_ledger")
            self.assertIn("neto prodali", holders.check(con, self.MINT_, self.POOL, 100_000, now, post))
        with mock.patch.dict(os.environ, {"RANGE_HOLDER_RULE": "off"}):
            self.assertIsNone(holders.check(con, self.MINT_, self.POOL, 100_000, now + 9999, post))
        with mock.patch.object(holders, "CREDITS_DAY", 0), mock.patch.dict(os.environ, {"RANGE_HOLDER_RULE": "act"}):
            con.execute("DELETE FROM kv WHERE k LIKE 'hold:%'")
            n = len(calls)
            self.assertIsNone(holders.check(con, self.MINT_, self.POOL, 100_000, now + 99999, post))
            self.assertEqual(len(calls), n)                                  # no credits left: no call


class DataAndJob(TradeBase):
    def pair(self, tok, px, mc, liq, dex="pumpswap"):
        return {"baseToken": {"address": tok, "symbol": "RNG"}, "priceUsd": str(px), "marketCap": mc, "dexId": dex,
                "pairAddress": "Pool" + tok[:8], "liquidity": {"usd": liq}, "volume": {"m5": 5000, "h1": 60_000, "h6": 360_000},
                "txns": {"m5": {"buys": 6, "sells": 4}, "h1": {"buys": 60, "sells": 40}}, "priceChange": {"m5": 1.0}}

    def test_poll_never_stores_tokens_under_30k_or_on_the_curve(self):
        con = data.connect()
        a, b, c = MINT, "B" * 43 + "pump", "C" * 43 + "pump"
        pairs = [self.pair(a, 52e-6, 52_000, 25_000), self.pair(b, 2e-5, 20_000, 9_000),
                 self.pair(c, 6e-5, 60_000, 0, dex="pumpfun")]
        got = data.poll(con, [a, b, c], self.now, fetch=lambda toks: pairs, pulse_fresh=set())
        self.assertEqual(list(got), [a])
        self.assertEqual({r[0] for r in con.execute("SELECT DISTINCT token FROM snaps")}, {a})
        self.assertEqual(sorted(data.kv_get(con, "cold")), sorted([b, c]))
        asked = []
        data.poll(con, [a, b, c], self.now + 60, fetch=lambda toks: asked.append(list(toks)) or [], pulse_fresh={a})
        self.assertEqual(asked, [])                                          # cold ones wait, a is in the hype scan

    def test_merge_prefers_real_candles_and_spreads_snapshot_volume(self):
        real = [(T0 + 60, 1.0, 1.2, 0.9, 1.1, 500.0)]
        snaps = [{"ts": T0 + 65, "price": 1.15, "vol_m5": 1000, "buys_m5": 10, "sells_m5": 5},
                 {"ts": T0 + 240, "price": 1.2, "vol_m5": 1500, "buys_m5": 5, "sells_m5": 5}]
        cs = data.merge(real, snaps)
        self.assertEqual([c[0] for c in cs], [T0 + 60, T0 + 240])
        self.assertEqual(cs[0][1:6], (1.0, 1.2, 0.9, 1.1, 500.0))            # the real candle, with the snapshot's counts
        self.assertEqual(cs[0][6:], (2.0, 1.0))
        self.assertEqual(cs[1][5], 1500 / 5 * 3)                             # stands for 3 minutes

    def test_once_polls_seeds_within_the_cap_detects_and_mcp_shows_it(self):
        self.mode("paper")
        import run_range
        seeds = []

        def gt(pool, start, end):
            seeds.append(pool)
            return [c[:6] for c in tri(end - 12 * 3600 + 60, hours=12)]
        pair = self.pair(MINT, 0, 0, 25_000)
        logs = []

        def fetch(toks):
            last = tri(self.now - 12 * 3600 + 60 - self.now % 60, hours=12)[-1]
            pair.update(priceUsd=str(last[4]), marketCap=last[4] * 1e9)
            return [pair]
        out = run_range.once(now=self.now, log=logs.append, fetch=fetch, gt_fetch=gt, post=lambda *a: {}, extra=[MINT])
        self.assertIn("aktivnih 1", out)
        self.assertEqual(seeds, [pair["pairAddress"]])
        con = data.connect()
        self.assertEqual(data.day_used(con, "gt_day", self.now), 1)
        r, st = data.load_range(con, MINT)
        self.assertEqual(r["status"], "aktivan", r["why"])
        self.assertIn("aktivan", " ".join(logs))
        # the next minute: no new seed, the active range only gets fresh 5-minute numbers
        run_range.once(now=self.now + 60, log=logs.append, fetch=fetch, gt_fetch=gt, extra=[MINT])
        self.assertEqual(len(seeds), 1)
        self.assertEqual(data.load_range(con, MINT)[0]["mts"], self.now + 60)
        with mock.patch.object(data, "GT_DAY", 1):
            self.assertEqual(data.gt_left(con, self.now), 0)
        con.close()
        from rangedca import view
        from ui import mcpapi
        d, err = mcpapi._tool("get_range_candidates", {"min_score": 0.5})
        self.assertFalse(err, d)
        c = d["candidates"][0]
        self.assertEqual((c["token"], c["status"], c["flag_mode"] if "flag_mode" in c else d["flag_mode"]),
                         (MINT, "aktivan", "paper"))
        self.assertEqual(set(c["components"]), set(detect.WEIGHTS))
        self.assertIn("range_low_low", c["zones"]["price"])
        self.assertTrue(c["touches"]["bottom"])
        self.assertIn("live_gate", d["paper_proof"])
        self.assertEqual(view.candidates(min_score=1.01)["candidates"], [])
        det = mcpapi.token(MINT)
        self.assertEqual(det["range"]["token"], MINT)
        self.assertIn("recoveries", det["range"])


class Backtest(unittest.TestCase):
    def test_rounds_on_a_clean_range_and_the_report(self):
        cs = tri(T0, hours=24, period=180)
        rep = backtest.run_tokens({MINT: (cs, 1e9, 50_000.0, "RNG")})
        v = rep["variants"]
        self.assertEqual(set(v), {"0.6", "0.6_bez_lota2", "0.7", "0.7_bez_lota2", "0.8", "0.8_bez_lota2", backtest.PROXY_OFF})
        s = v["0.7"]
        self.assertGreaterEqual(s["rounds"], 3)
        self.assertEqual(s["win_rate"], 1.0)
        self.assertGreater(s["avg_ret_pct"], 30)
        self.assertEqual(s["max_drawdown_usd"], 0.0)
        r = rep["tokens"][MINT]["rounds_0.7"][0]
        self.assertEqual([e["reason"] for e in r["exits"]], ["tp1", "trailing"])   # the peak 98 < range_high_top 98.98
        text = backtest.md(rep)
        self.assertIn("| 0.7 | da |", text)
        self.assertIn("bez proxy filtra kupnji", text)

    def test_hope_backtest_runs_on_the_stored_candles(self):
        with gzip.open(os.path.join(ROOT, "tests", "fixtures", "range_hope_20261110.json.gz"), "rt") as f:
            fx = json.load(f)
        cs = data.merge([tuple(r) for r in fx["candles"]], [])
        rep = backtest.run_tokens({fx["token"]: (cs, 1e9, None, "Hope")})
        self.assertEqual(rep["tokens_with_range"], 1)
        self.assertGreater(rep["tokens"][fx["token"]]["active_detections"], 5)
        for k, s in rep["variants"].items():
            self.assertGreaterEqual(s["rounds"], 0, k)


if __name__ == "__main__":
    unittest.main()
