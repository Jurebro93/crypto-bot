"""15.11. (vlasnik: "Useless, Troll i slično: kad nađu dno ... 5-10 % ... hvataj range velikih tokena"; "NE računajući
velike padove Bitcoina"): veliki/ on synthetic data, no network.

  - a token oscillating in a range gets a valid zone and profitable trades; a trending one gets no zone (ER)
  - the ticker resolution picks the real mint (the most REAL liquidity), never the copycat with a fake $100M pool
  - BTC crash: detected (4 h / 24 h), no entry while it lasts, after it only a fresh range (>= 24 h since its end)
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


def bars15(kind, days=12, base=1.0, amp=0.06, period_h=20.0, t0=T0):
    """15m bars: "range" (a sine +-amp around base, period period_h), "trend" (+4 % a day, small noise)."""
    out = []
    prev = base
    for i in range(int(days * 96)):
        t = t0 + i * M15
        x = i / 4.0
        if kind == "range":
            c = base * (1 + amp * math.sin(2 * math.pi * x / period_h))
        else:
            c = base * (1.04 ** (x / 24)) * (1 + 0.002 * math.sin(x))
        o = prev
        out.append((t, o, max(o, c) * 1.001, min(o, c) * 0.999, c, 1000.0))
        prev = c
    return out


def flat_btc(t0=T0 - 40 * 86400, hours=60 * 24, px=80_000.0):
    return [(t0 + i * H, px) for i in range(hours)]


class Zones(unittest.TestCase):
    def test_range_valid_trend_rejected(self):
        r = rule.h1_from_15m(bars15("range"))
        tr = rule.h1_from_15m(bars15("trend"))
        t = T0 + 10 * 86400
        zr = rule.Zones(r).at(t, 3)
        zt = rule.Zones(tr).at(t, 3)
        self.assertTrue(zr["ok"], zr)
        self.assertLess(zr["s_hi"], zr["r_lo"])
        self.assertFalse(zt["ok"])
        self.assertIn("trend", zt["why"])

    def test_range_trades_profit_trend_none(self):
        cfg = {"tp": 5.0, "stop_pct": 0.05, "time_h": 24, "look_d": 3}
        for kind, want in (("range", True), ("trend", False)):
            b = bars15(kind, days=14)
            zs = rule.Zones(rule.h1_from_15m(b))
            cands = rule.candidates(b, zs, 3)
            rt = rule.cost_at(0.5, 2_000_000, 150.0, 0.0035, 0.0005)["rt"]
            trs = rule.simulate(b, cands, 75.0, rt, cfg)
            if want:
                self.assertGreaterEqual(len(trs), 3, kind)
                self.assertGreater(rule.summary(trs)["ev_pct"], 0)
                self.assertIn("tp", {x["reason"] for x in trs})
            else:
                self.assertEqual(trs, [])

    def test_no_look_ahead(self):
        b = bars15("range", days=14)
        cut = len(b) - 96 * 3
        changed = b[:cut] + [(x[0], x[1] * 0.5, x[2] * 0.5, x[3] * 0.5, x[4] * 0.5, x[5]) for x in b[cut:]]
        t = b[cut - 1][0] + M15
        za = rule.Zones(rule.h1_from_15m(b)).at(t, 3)
        zb = rule.Zones(rule.h1_from_15m(changed)).at(t, 3)
        self.assertEqual({k: za.get(k) for k in ("s_lo", "s_hi", "r_lo", "r_hi")},
                         {k: zb.get(k) for k in ("s_lo", "s_hi", "r_lo", "r_hi")})
        cfg = {"tp": 5.0, "stop_pct": 0.05, "time_h": 12, "look_d": 3}
        rt = 0.01
        ta = [x for x in rule.simulate(b, rule.candidates(b, rule.Zones(rule.h1_from_15m(b)), 3), 75, rt, cfg)
              if x["out_ts"] <= t]
        tb = [x for x in rule.simulate(changed, rule.candidates(changed, rule.Zones(rule.h1_from_15m(changed)), 3),
                                       75, rt, cfg) if x["out_ts"] <= t]
        self.assertEqual([(x["ts"], round(x["ret"], 9)) for x in ta], [(x["ts"], round(x["ret"], 9)) for x in tb])

    def test_walk_forward_picks_on_older_days(self):
        series = {"A": {"bars": bars15("range", days=24), "liq": 2e6, "dex": "raydium", "symbol": "A"},
                  "B": {"bars": bars15("trend", days=24), "liq": 2e6, "dex": "raydium", "symbol": "B"}}
        for s in series.values():
            s["h1"] = rule.h1_from_15m(s["bars"])
        with mock.patch.object(rule, "tx_sol", lambda: (0.0005, "test")), mock.patch.object(walk, "MIN_ALL_N", 5):
            d = walk.compute(series, flat_btc(), [], now=T0 + 30 * 86400, log=lambda s: None, sol_usd=150.0,
                             sizes=(0.5,), grid={"tp": (5.0, "mid"), "stop_pct": (0.05,), "time_h": (24,),
                                                 "look_d": (3,)})
        st = d["variants"]["bez_padova"]["0.5"]
        self.assertTrue(st["folds"])
        for f in st["folds"]:
            self.assertGreaterEqual(f["from"], T0 + walk.TRAIN_D * 86400)
        self.assertGreater(st["n"], 0)
        self.assertGreater(st["ev_pct"], 0)
        self.assertEqual(set(st["per_token"]), {"A"})
        self.assertIsNotNone(st["ci90_ev_pct"])
        self.assertIn("0.5", d["proof"]["sizes"])
        self.assertTrue(d["live_rule"])


class Crash(unittest.TestCase):
    def btc_with_crash(self, at):
        pts = []
        for i in range(30 * 24):
            t = T0 + i * H
            px = 80_000.0 if t < at else 75_000.0   # -6.25 % in one hour
            pts.append((t, px))
        return pts

    def test_crash_detected_and_entries_blocked(self):
        at = T0 + 10 * 86400
        cr = rule.Crash(rule.crash_hours(self.btc_with_crash(at)))
        self.assertTrue(cr.active(at + 600))
        self.assertFalse(cr.active(at - H))
        self.assertTrue(cr.periods)
        end = cr.last_end(at + 3 * 86400)
        self.assertIsNotNone(end)
        self.assertGreater(end, at)
        b = bars15("range", days=14)
        z = rule.Zones(rule.h1_from_15m(b)).at(at + 1800, 3)
        z = z if z.get("ok") else {"ok": True, "s_lo": 0.9, "s_hi": 1.0, "r_lo": 1.1, "r_hi": 1.2, "mid": 1.05}
        i = next(k for k, x in enumerate(b) if x[0] + M15 >= at + 600)
        self.assertIn("BTC pada", rule.base_signal(b, i, z, crash=cr))

    def test_fresh_range_after_crash(self):
        at = T0 + 10 * 86400
        cr = rule.Crash(rule.crash_hours(self.btc_with_crash(at)))
        end = cr.last_end(at + 3 * 86400)
        h1 = rule.h1_from_15m(bars15("range", days=20))
        zs = rule.Zones(h1, cr)
        early = zs.at(end + 10 * H, 7)
        self.assertFalse(early["ok"])
        self.assertIn("novi raspon", early["why"])
        later = zs.at(end + 30 * H, 7)
        self.assertTrue(later.get("fresh"))
        self.assertGreaterEqual(later.get("t0", end), end)

    def test_crash_variants_differ(self):
        at = T0 + 14 * 86400
        btc = self.btc_with_crash(at)
        series = {"A": {"bars": bars15("range", days=24), "liq": 2e6, "dex": "raydium", "symbol": "A"}}
        series["A"]["h1"] = rule.h1_from_15m(series["A"]["bars"])
        with mock.patch.object(rule, "tx_sol", lambda: (0.0005, "test")):
            d = walk.compute(series, btc, [], now=T0 + 30 * 86400, log=lambda s: None, sol_usd=150.0, sizes=(0.5,),
                             grid={"tp": (5.0,), "stop_pct": (0.05,), "time_h": (24,), "look_d": (3,)})
        self.assertLessEqual(d["variants"]["bez_padova"]["0.5"]["n"], d["variants"]["s_padovima"]["0.5"]["n"])
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
        groups = {"A": g("A", "AAA", 50e6, 2e6, 1e6), "B": g("B", "BBB", 10e6, 2e6, 1e6),
                  "C": g("C", "CCC", 50e6, 200e3, 1e6), "D": g("D", "DDD", 50e6, 2e6, 100e3),
                  "E": g("E", "EEE", 50e6, 2e6, 1e6, created=(now - 3 * 86400) * 1000),
                  "F": g("F", "FFF", 50e6, 2e6, 1e6, dex="pumpfun"), "G": g("G", "USDC", 50e6, 2e6, 1e6),
                  "H": g("H", "HHH", 50e6, 2e6, 1e6), "I": g("I", "III", 50e6, 2e6, 5e6, jup={"tags": ["defi"]}),
                  "S": g("S", "TROLL", 23e6, 1.5e6, 0.9e6)}
        rows, refused = universe.select(groups, now, seeds={"S"}, archived={"H"}, curve_dex=("pumpfun",))
        self.assertEqual([r["mint"] for r in rows], ["S", "A"])   # the seed first
        for k, word in (("B", "MC"), ("C", "likvidnost"), ("D", "volumen"), ("E", "premlad"), ("F", "krivulja"),
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
                               (live, "series", lambda t, now: ([(0, 1, 1, 1, 1, 0)] * 20, [])),
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
        self.assertIn("90 %", gate.real_refusal(con=self.con, proof=bad))
        good = {"sizes": {"0.1": {"n": 100, "ev_pct": 1.0, "ci90_ev_pct": [0.2, 2.0]}}}
        self.assertIsNone(gate.real_refusal(con=self.con, proof=good, now=self.now))
        with mock.patch.object(gate, "btc_refusal", lambda now=None: "BTC pada"):
            self.assertEqual(gate.real_refusal(con=self.con, proof=good), "BTC pada")
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
        self.assertEqual(assistnotes.OWNER_FLAG_ORDERS[-1][:2], ("veliki_range", "paper"))
        self.assertNotIn(gate.SWITCH, [n for n, _m, _w in assistnotes.OWNER_FLAG_ORDERS])
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", assistnotes.OWNER_FLAG_ORDERS[-1:]):
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
