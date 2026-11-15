"""15.11. (vlasnik: "Useless, Troll i slično: kad nađu dno ... 5-10 % ... hvataj range velikih tokena"; "NE računajući
velike padove Bitcoina"): veliki/ on synthetic data, no network.

  - a token oscillating in a range gets a valid zone and profitable trades; a trending one gets no zone (ER)
  - the ticker resolution picks the real mint (the most REAL liquidity), never the copycat with a fake $100M pool
  - BTC: three states (slobodan pad: no entry; dno se potvrđuje: the bounce with inflow buys; normalno), the ban variant
    and no filter reported too; after a crash only a fresh range (>= 24 h since its end); a broken range is not re-used
  - point-in-time universe (MC 5-150M and age > 15 d at the signal), trailing after the target, stops fixed at entry
  - costs: never zero, the network fee's share falls with the size, a deep pool has ~no impact
  - walk-forward / zones: no look-ahead (changing the future never changes an earlier zone or the trades before it)
  - the switch off means never real money (gate, live tick, run_trade); the owner order puts the flag in paper last
    and never the switch

    python3 -m unittest tests.test_veliki_range_offline
"""
import math
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import PU, SwitchBase, tok  # noqa: E402
from trade import settings  # noqa: E402
from veliki import gate, live, rule, store as vstore, universe, walk  # noqa: E402

T0 = 1_790_000_000 // 86400 * 86400
M15, H = 900, 3600


def bars1h(kind, days=20, base=1.0, amp=0.10, period_h=48.0, t0=T0, vol=1000.0):
    """1h bars: "range" (a sine +-amp around base), "trend" (+4 % a day, small noise)."""
    out = []
    prev = base
    for i in range(int(days * 24)):
        t = t0 + i * H
        if kind == "range":
            c = base * (1 + amp * math.sin(2 * math.pi * i / period_h))
        else:
            c = base * (1.04 ** (i / 24)) * (1 + 0.002 * math.sin(i))
        o = prev
        out.append((t, o, max(o, c) * 1.002, min(o, c) * 0.998, c, vol))
        prev = c
    return out


def flat_btc(t0=T0 - 40 * 86400, hours=80 * 24, px=80_000.0):
    return [(t0 + i * H, px) for i in range(hours)]


def series_of(**kinds):
    out = {}
    for name, kind in kinds.items():
        b = bars1h(kind, days=30)
        out[name] = {"bars": b, "h1": b, "daily": [], "liq": 2e6, "dex": "raydium", "symbol": name, "row": {},
                     "dead": False}
    return out


class Zones(unittest.TestCase):
    def test_range_valid_trend_rejected(self):
        t = T0 + 15 * 86400
        zr = rule.Zones(bars1h("range")).at(t, 7)
        zt = rule.Zones(bars1h("trend")).at(t, 7)
        self.assertTrue(zr["ok"], zr)
        self.assertLess(zr["s_hi"], zr["r_lo"])
        self.assertFalse(zt["ok"])
        self.assertIn("trend", zt["why"])

    def test_broken_range_not_reused(self):
        b = bars1h("range", days=20)
        cut = 15 * 24
        broken = b[:cut] + [(x[0], x[1] * 0.7, x[2] * 0.7, x[3] * 0.7, x[4] * 0.7, x[5]) for x in b[cut:]]
        z = rule.Zones(broken).at(b[cut + 6][0], 7)
        self.assertFalse(z["ok"])
        self.assertIn("probijen", z["why"])

    def test_range_trades_profit_trend_none(self):
        cfg = {"tp": 8.0, "time_h": 72, "look_d": 7, "btc_mode": "bez", "crash_filter": False}
        for kind, want in (("range", True), ("trend", False)):
            b = bars1h(kind, days=30)
            zs = rule.Zones(b)
            cands = rule.candidates(b, zs, 7, None, cfg)
            rt = rule.cost_at(0.5, 2_000_000, 150.0, 0.0035, 0.0005)["rt"]
            trs = rule.simulate(b, cands, 75.0, rt, cfg)
            if want:
                self.assertGreaterEqual(len(trs), 3, kind)
                self.assertGreater(rule.summary(trs)["ev_pct"], 0)
                self.assertIn("tp", {x["reason"] for x in trs})
                self.assertTrue(all(x["mae"] <= 0 <= x["mfe"] + 1e-9 for x in trs))
            else:
                self.assertEqual(trs, [])

    def test_trailing_after_target(self):
        pos = {"entry": 1.0, "ts": T0, "tp_px": 1.10, "stop_px": 0.8}
        cfg = {"trail": 0.05, "time_h": 1000}
        self.assertIsNone(rule.exit_on_bar(pos, (T0 + H, 1.0, 1.15, 1.0, 1.14, 0), cfg))   # target hit: trailing armed
        self.assertAlmostEqual(pos["peak"], 1.15)
        hit = rule.exit_on_bar(pos, (T0 + 2 * H, 1.12, 1.13, 1.05, 1.06, 0), cfg)
        self.assertEqual(hit[0], "trail")
        self.assertGreater(hit[1], 1.08)

    def test_stops_fixed_and_atr_capped(self):
        z = {"ok": True, "s_lo": 0.95, "atr": 0.2}
        self.assertAlmostEqual(rule.stop_px(1.0, z, {"stop": "pct20"}), 0.8)
        self.assertAlmostEqual(rule.stop_px(1.0, z, {"stop": "pct10"}), 0.9)
        self.assertAlmostEqual(rule.stop_px(1.0, z, {"stop": "atr"}), 0.8)          # 0.95 - 0.4 capped at -20 %
        self.assertAlmostEqual(rule.stop_px(1.0, dict(z, atr=0.01), {"stop": "atr"}), 0.93)

    def test_no_look_ahead(self):
        b = bars1h("range", days=30)
        cut = len(b) - 24 * 5
        changed = b[:cut] + [(x[0], x[1] * 0.5, x[2] * 0.5, x[3] * 0.5, x[4] * 0.5, x[5]) for x in b[cut:]]
        t = b[cut - 1][0] + H
        za = rule.Zones(b).at(t, 7)
        zb = rule.Zones(changed).at(t, 7)
        self.assertEqual({k: za.get(k) for k in ("s_lo", "s_hi", "r_lo", "r_hi")},
                         {k: zb.get(k) for k in ("s_lo", "s_hi", "r_lo", "r_hi")})
        cfg = {"tp": 8.0, "time_h": 72, "look_d": 7, "btc_mode": "bez", "crash_filter": False}
        ta = [x for x in rule.simulate(b, rule.candidates(b, rule.Zones(b), 7, None, cfg), 75, 0.01, cfg)
              if x["out_ts"] <= t]
        tb = [x for x in rule.simulate(changed, rule.candidates(changed, rule.Zones(changed), 7, None, cfg), 75, 0.01,
                                       cfg) if x["out_ts"] <= t]
        self.assertEqual([(x["ts"], round(x["ret"], 9)) for x in ta], [(x["ts"], round(x["ret"], 9)) for x in tb])

    def test_walk_forward_picks_on_older_days(self):
        series = series_of(A="range", B="trend")
        with mock.patch.object(rule, "tx_sol", lambda: (0.0005, "test")), mock.patch.object(walk, "MIN_ALL_N", 3), \
                mock.patch.object(walk, "MIN_TRAIN_N", 2):
            d = walk.compute(series, flat_btc(), [], now=T0 + 31 * 86400, log=lambda s: None, sol_usd=150.0,
                             sizes=(0.5,), grid={"tp": (8.0,), "trail": (0.0,), "time_h": (72,), "look_d": (7,)},
                             stops=("pct20", "pct10"))
        st = d["variants"]["dno"]["0.5"]
        self.assertTrue(st["folds"])
        for f in st["folds"]:
            self.assertGreaterEqual(f["from"], T0 + walk.TRAIN_D * 86400)
        self.assertGreater(st["n"], 0)
        self.assertGreater(st["ev_pct"], 0)
        self.assertEqual(set(st["per_token"]), {"A"})
        for k in ("ci95_day_pct", "ev_2x_cost_pct", "loto_min_pct", "profit_factor", "worst5_pct", "mae_med_pct",
                  "hold_med_h"):
            self.assertIn(k, st)
        self.assertLess(st["ev_2x_cost_pct"], st["ev_pct"])
        self.assertIn("0.5", d["proof"]["sizes"])
        self.assertIn("pct10", d["stops"])
        self.assertEqual(set(d["variants"]), {"dno", "zabrana", "bez_filtra"})
        self.assertTrue(d["live_rule"])

    def test_point_in_time_universe(self):
        b = bars1h("range", days=30)
        ok = walk.pit_of({"mcap": 6e6, "created_ts": T0 - 5 * 86400}, b)
        self.assertFalse(ok(T0 + 5 * 86400, b[-1][4]))            # 10 days old then: not yet in the universe
        self.assertTrue(ok(T0 + 20 * 86400, b[-1][4]))
        self.assertFalse(ok(T0 + 20 * 86400, b[-1][4] * 0.5))     # MC $3M then: under the floor


class Btc(unittest.TestCase):
    def btc_with_crash(self, at, rebound=True):
        pts = []
        for i in range(40 * 24):
            t = T0 + i * H
            if t < at:
                px = 80_000.0
            elif t < at + 3 * H:
                px = 75_000.0 - 500 * (t - at) / H   # -6 % and new lows for 3 h
            else:
                px = 74_000.0 + (30 * (t - at - 3 * H) / H if rebound else 0)
            pts.append((t, px))
        return pts

    def test_three_states(self):
        at = T0 + 10 * 86400
        cr = rule.crash_of(self.btc_with_crash(at))
        self.assertEqual(cr.regime(at + 3600)[0], "slobodan_pad")
        self.assertEqual(cr.regime(at - 5 * H)[0], "normalno")
        self.assertEqual(cr.regime(at + 12 * H)[0], "dno_se_potvrduje")
        self.assertTrue(cr.active(at + 600))

    def test_entries_by_btc_mode(self):
        at = T0 + 15 * 86400
        cr = rule.crash_of(self.btc_with_crash(at))
        b = bars1h("range", days=30)
        z = {"ok": True, "s_lo": 0.85, "s_hi": 0.95, "r_lo": 1.05, "r_hi": 1.1, "mid": 1.0}
        i = next(k for k, x in enumerate(b) if x[0] + H >= at + 1800)
        self.assertIn("slobodan pad", rule.base_signal(b, i, z, {"btc_mode": "dno"}, cr))
        self.assertIn("zabrana", rule.base_signal(b, i, z, {"btc_mode": "zabrana"}, cr))
        # bottom forming: a green bar with volume over its 6 h average buys even without a valid zone
        j = next(k for k, x in enumerate(b) if x[0] + H >= at + 12 * H)
        bb = list(b)
        bb[j] = (b[j][0], b[j - 1][4], b[j - 1][4] * 1.03, b[j - 1][4] * 0.999, b[j - 1][4] * 1.02, 5000.0)
        self.assertIsNone(rule.base_signal(bb, j, {"ok": False, "why": "raspon probijen"}, {"btc_mode": "dno"}, cr))
        self.assertIsNotNone(rule.base_signal(bb, j, {"ok": False, "why": "x"}, {"btc_mode": "normal_only"}, cr))

    def test_fresh_range_after_crash(self):
        at = T0 + 10 * 86400
        cr = rule.crash_of(self.btc_with_crash(at))
        end = cr.last_end(at + 3 * 86400)
        self.assertIsNotNone(end)
        zs = rule.Zones(bars1h("range", days=25), cr)
        early = zs.at(end + 10 * H, 7)
        self.assertFalse(early["ok"])
        self.assertIn("novi raspon", early["why"])
        later = zs.at(end + 30 * H, 7)
        self.assertTrue(later.get("fresh"))

    def test_btc_variants_reported(self):
        at = T0 + 18 * 86400
        series = series_of(A="range")
        with mock.patch.object(rule, "tx_sol", lambda: (0.0005, "test")):
            d = walk.compute(series, self.btc_with_crash(at), [], now=T0 + 31 * 86400, log=lambda s: None,
                             sol_usd=150.0, sizes=(0.5,), grid={"tp": (8.0,), "trail": (0.0,), "time_h": (72,),
                                                                "look_d": (7,)}, stops=("pct20",))
        self.assertLessEqual(d["variants"]["zabrana"]["0.5"]["n"], d["variants"]["bez_filtra"]["0.5"]["n"])
        self.assertTrue(d["crash_periods"])


class Costs(unittest.TestCase):
    def test_costs_never_zero_and_fall_with_size(self):
        with mock.patch("trade.cost.fee_side", lambda path=None: 0.01):
            small = rule.cost_at(0.1, 2_000_000, 150.0, 0.0035, 0.0005)
            mid = rule.cost_at(0.5, 2_000_000, 150.0, 0.0035, 0.0005)
            big = rule.cost_at(1.0, 2_000_000, 150.0, 0.0035, 0.0005)
        self.assertGreater(big["rt"], 0.007)                       # 2 x (0.25 % pool + 0.1 % route) at least
        self.assertGreater(small["rt"], mid["rt"])
        self.assertGreater(mid["rt"], big["rt"])
        self.assertAlmostEqual(small["parts"]["net"], 0.01, places=4)   # 2 x 0.0005 SOL of 0.1 SOL
        self.assertLess(big["parts"]["impact"], 0.001)                # $150 in a $2M pool
        thin = rule.cost_at(0.5, 30_000, 150.0, 0.0035, 0.0005)
        self.assertGreater(thin["rt"], mid["rt"] + 0.005)
        self.assertGreater(rule.demo_rt(75.0, 2_000_000, fee=0.01), mid["rt"])


class Resolve(unittest.TestCase):
    @staticmethod
    def pair(mint, sym, liq, mcap, vol, created_ms, dex="raydium", addr=None):
        return {"chainId": "solana", "dexId": dex, "pairAddress": addr or (mint[:8] + dex), "url": f"https://x/{dex}",
                "baseToken": {"address": mint, "symbol": sym, "name": sym}, "liquidity": {"usd": liq},
                "marketCap": mcap, "volume": {"h24": vol}, "pairCreatedAt": created_ms}

    def test_real_troll_not_the_fake_pool(self):
        real, fake, dead = "5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2", "TDtNdhCcJcarSCiLzYVGiJFcQnHFJcGijVsK6nNiEN1", \
            "HDLCFjQ65QjupYFqUatHx4ynUUrpQNWaHKksfncgpump"
        pairs = [self.pair(fake, "TROLL", 106_719_598, 106_897_141, 1, 1_779_274_401_000),
                 self.pair(real, "TROLL", 1_500_000, 23_419_191, 900_000, 1_745_173_826_000, "pumpswap"),
                 self.pair(real, "TROLL", 518_000, 23_419_191, 367_000, 1_745_200_000_000, "orca"),
                 self.pair(dead, "TROLL", 0, 2585, 2144, 1_794_656_979_000, "pumpfun"),
                 self.pair("Other111111111111111111111111111111111111", "TROLLX", 9e6, 5e7, 9e6, 1_745_000_000_000)]
        m, how, refused = universe.resolve("TROLL", pairs, known=None)
        self.assertEqual(m, real)
        self.assertIn("najveća prava likvidnost", how)
        self.assertIn(fake, [x[0] for x in refused])
        self.assertIn("lažni pool", dict(refused)[fake])

    def test_select_rules(self):
        now = T0 + 400 * 86400
        old = (T0 - 100 * 86400) * 1000

        def g(m, sym, mcap, liq, vol, created=old, dex="raydium", jup=None):
            gg = universe.group([self.pair(m, sym, liq, mcap, vol, created, dex)])[m]
            if jup:
                gg["jup"] = jup
            return gg
        groups = {"A": g("A", "AAA", 50e6, 2e6, 1e6), "B": g("B", "BBB", 3e6, 1e6, 1e6),
                  "C": g("C", "CCC", 50e6, 100e3, 1e6), "D": g("D", "DDD", 50e6, 2e6, 50e3),
                  "J": g("J", "JJJ", 300e6, 5e6, 5e6),
                  "E": g("E", "EEE", 50e6, 2e6, 1e6, created=(now - 3 * 86400) * 1000),
                  "F": g("F", "FFF", 50e6, 2e6, 1e6, dex="pumpfun"), "G": g("G", "USDC", 50e6, 2e6, 1e6),
                  "H": g("H", "HHH", 50e6, 2e6, 1e6), "I": g("I", "III", 50e6, 2e6, 5e6, jup={"tags": ["defi"]}),
                  "S": g("S", "TROLL", 23e6, 1.5e6, 0.9e6)}
        rows, refused = universe.select(groups, now, seeds={"S"}, archived={"H"}, curve_dex=("pumpfun",))
        self.assertEqual([r["mint"] for r in rows], ["S", "A"])   # the seed first
        for k, word in (("B", "ispod"), ("J", "iznad"), ("C", "likvidnost"), ("D", "volumen"), ("E", "premlad"),
                        ("F", "krivulja"),
                        ("G", "memecoin"), ("H", "arhivi"), ("I", "memecoin")):
            self.assertIn(word, refused[k][1], k)


class Switch(SwitchBase):
    def setUp(self):
        super().setUp()
        self.vdb = os.path.join(self.tmp.name, "veliki.db")
        p = mock.patch.dict(os.environ, {"VELIKI_DB": self.vdb})
        p.start()
        self.addCleanup(p.stop)
        vstore.reset_cache()
        live._ST.update(tick=0.0, bar={}, said={}, gt={}, gt_ts=0.0, btc=None, btc_ts=0.0, q={})
        live._LIVE.clear()
        con = vstore.connect(self.vdb)
        vstore.save_list(con, [{"mint": tok(31), "symbol": "BIG", "pool": "P", "dex": "raydium", "mcap": 5e7,
                                "liq": 2e6, "liq_total": 3e6, "vol24": 1e6, "age_d": 100}], self.now)
        con.executemany("INSERT INTO btc_h VALUES (?,?)", [(int(self.now) // H * H - i * H, 80_000.0) for i in range(48)])
        con.commit()
        con.close()
        self.zone = {"ok": True, "s_lo": 0.9e-4, "s_hi": 1.0e-4, "r_lo": 1.15e-4, "r_hi": 1.2e-4, "mid": 1.07e-4}
        for obj, name, val in ((live, "_sol", lambda: 150.0),
                               (live, "series", lambda t, now: ([(0, 1, 1, 1, 1, 0)] * 30, [])),
                               (rule.Zones, "at", lambda self_, t, look: dict(self.zone)),
                               (rule, "signal", lambda *a, **k: None)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)

    def mk(self, toks):
        return {t: (1.0e-4, 2_000_000.0, "https://dexscreener.com/solana/raydium", 5e7, "BIG", {"m5": 0.0})
                for t in toks}

    def test_switch_off_demo_only(self):
        self.flag("veliki_range", "paper")
        good = {"sizes": {"0.1": {"n": 500, "ev_pct": 3.0, "ci90_ev_pct": [1.0, 5.0]}}}
        self.assertIn("isključen", gate.real_refusal(con=self.con, proof=good))
        out = live.tick(self.lg, self.mk, now=self.now, force=True)
        rows = self.lg.execute("SELECT user, status, size_sol FROM veliki_trades").fetchall()
        self.assertEqual({r[0] for r in rows}, {PU}, out)
        self.assertEqual(rows[0][2], live.DEMO_SOL)
        self.assertTrue(any("veliki demo ulaz BIG" in x for x in out))
        src = self.lg.execute("SELECT source FROM trades WHERE user=? AND token=?", (PU, tok(31))).fetchone()[0]
        self.assertTrue(src.startswith("veliki:"))

    def test_flag_off_no_entry(self):
        self.flag("veliki_range", "off")
        self.assertEqual(live.tick(self.lg, self.mk, now=self.now, force=True), [])

    def test_switch_on_needs_proof_and_calm_btc(self):
        settings.set_flag(self.con, gate.SWITCH, "live", "Jure")
        settings._FLAG_CACHE.clear()
        self.assertIn("treba 40", gate.real_refusal(con=self.con, proof={"sizes": {"0.1": {"n": 10}}}))
        bad = {"sizes": {"0.1": {"n": 100, "ev_pct": 1.0, "ci90_ev_pct": [-0.2, 2.0]}}}
        self.assertIn("intervala", gate.real_refusal(con=self.con, proof=bad))
        loto = {"sizes": {"0.1": {"n": 100, "ev_pct": 1.0, "ci95_day_pct": [0.2, 2.0], "ev_2x_cost_pct": 0.5,
                                  "loto_min_pct": -0.3}}}
        self.assertIn("jednog tokena", gate.real_refusal(con=self.con, proof=loto))
        dbl = {"sizes": {"0.1": {"n": 100, "ev_pct": 1.0, "ci95_day_pct": [0.2, 2.0], "ev_2x_cost_pct": -0.5}}}
        self.assertIn("dvostruki", gate.real_refusal(con=self.con, proof=dbl))
        good = {"sizes": {"0.1": {"n": 100, "ev_pct": 1.0, "ci90_ev_pct": [0.2, 2.0]}}}
        self.assertIsNone(gate.real_refusal(con=self.con, proof=good, now=self.now))
        with mock.patch.object(gate, "btc_refusal", lambda now=None: "BTC slobodan pad"):
            self.assertEqual(gate.real_refusal(con=self.con, proof=good), "BTC slobodan pad")
        self.assertIn("demo", gate.real_refusal(con=self.con, proof=good, stats={"n": 5},
                                                cfg={gate.SWITCH: {"dokaz": "demo"}}))

    def test_caps_owner_size_up_to_half(self):
        self.assertEqual(gate.real_caps({})["size_sol"], 0.1)
        self.assertEqual(gate.real_caps({gate.SWITCH: {"size_sol": 0.4}})["size_sol"], 0.4)
        self.assertEqual(gate.real_caps({gate.SWITCH: {"size_sol": 2.0}})["size_sol"], 0.5)
        self.assertEqual(gate.real_caps({gate.SWITCH: {"max_open": 50}})["max_open"], 5)

    def test_run_trade_refuses_without_switch(self):
        tid = self.demo(tok(32), "veliki: podrška 1-2, cilj +5.0%, stop -5%")
        self.assertTrue(tid)
        self.mirror()
        r = self.con.execute("SELECT status, reason FROM positions WHERE token=?", (tok(32),)).fetchone()
        self.assertEqual(r[0], "blocked")
        self.assertIn("pravi_novac_veliki", r[1])
        self.assertEqual(self.swaps, [])

    def test_settings_and_order(self):
        from ui import apterm, assistnotes
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, gate.SWITCH, "live", "Grok")
        with self.assertRaises(ValueError):
            settings.set_flag(self.con, "veliki_range", "live", "Jure")
        self.assertIn(gate.SWITCH, settings.OWNER_SWITCHES)
        self.assertIn("veliki_range", settings.NEVER_LIVE)
        self.assertEqual(settings.flag(gate.SWITCH, con=self.con), "off")
        # 15.11. navečer: fokus_midcap's order (ops/fokus.py) came after it
        mine = tuple(o for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == "veliki_range")
        self.assertEqual([o[:2] for o in mine], [("veliki_range", "paper")])
        self.assertNotIn(gate.SWITCH, [n for n, _m, _w in assistnotes.OWNER_FLAG_ORDERS])
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", mine):
            assistnotes.owner_flag_orders(self.con)
        self.assertEqual(settings.flag_state(self.con)["veliki_range"]["mode"], "paper")
        self.assertEqual(settings.flag_state(self.con)[gate.SWITCH]["mode"], "off")
        h = apterm.owner_switches_html(self.con, True)
        self.assertIn(gate.SWITCH, h)
        self.assertIn("5 otvorenih", h)


class Views(unittest.TestCase):
    def test_mcp_and_card_without_data(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"VELIKI_DB": os.path.join(d, "v.db")}):
            vstore.reset_cache()
            from veliki import view
            view._C.update(ts=0.0, v=None)
            r = view.mcp({})
            self.assertNotIn("error", r)
            self.assertFalse(r["available"])
            self.assertIn("real_money", r)
            from ui import mcpapi
            self.assertIn("get_big_ranges", [t["name"] for t in mcpapi.TOOLS])
            self.assertIn("Veliki", walk.markdown(None))


if __name__ == "__main__":
    unittest.main()
