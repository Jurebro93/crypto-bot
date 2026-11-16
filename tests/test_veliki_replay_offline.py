"""16.11. (vlasnik: "želim više podataka koji će pomoći da postanemo profitabilni"; veliki/replay.py), offline, synthetic
bars only (no network, no real database):

  - the hooks in intra.simulate / rule.exit_on_bar are off by default: the same trades as before the change
  - the live exits on bars: no time stop, the stop to break-even at +5 % net, the whole position at the target; a bar
    that touches both the stop and the target is a stop (conservative)
  - tagging without look-ahead: the BTC-up score reads only candles completed before the entry; "oporavak" reads only
    the macro snapshots taken before it; the whole pipeline: bars after a time never change a trade entered before it
  - the walk-forward split (60 % / 40 %), the pick on the train trades only, the n < 30 rule ("premalo podataka")
  - the findings list ("ne ulaziti" / "prednost") by plain rules, each with its numbers
  - run(): bounded by its budget, never raises, makes no network call, stores the result, one log line
  - the morning report's section and the strategies row; run_veliki.py replay (--ako-nema, --night)

    python3 -m unittest tests.test_veliki_replay_offline
"""
import math
import os
import random
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veliki import intra, makro, midcap, odziv, replay, rule  # noqa: E402

D, H, M15 = 86400, 3600, 900
NOW = 1794821400 // H * H     # 16.11.2026 09:00 UTC
RT = 0.03


def mint(k):
    return f"Rep{k:04d}" + "x" * 36


def ou_bars(seed, days, t_end=NOW, px0=1.0, sigma=0.018):
    """15m bars of a mean-reverting price (a range), oldest first, ending at t_end."""
    rnd = random.Random(seed)
    x, prev, out = 0.0, px0, []
    t0 = t_end - days * D
    for i in range(days * 96):
        x += -0.03 * x + rnd.gauss(0, sigma)
        c = px0 * math.exp(x)
        out.append((t0 + i * M15, prev, max(prev, c) * (1 + abs(rnd.gauss(0, 0.004))),
                    min(prev, c) * (1 - abs(rnd.gauss(0, 0.004))), c, 1000.0))
        prev = c
    return out


def btc_rows(days=30, seed=5, t_end=NOW):
    rnd = random.Random(seed)
    p, out = 100000.0, []
    for i in range(days * 24 + 1):
        p *= 1 + rnd.gauss(0, 0.004)
        out.append((t_end - days * D + i * H, p))
    return out


def make_db(path, n_tok=10, days=15, seed=1, cut=None, alt_seed=99):
    """A small midcap.db: n_tok members with `days` of 15m bars (c1h left empty: rebuilt from the 15m), one snapshot
    each (the supply). cut: the bars from that time on come from another random series (the look-ahead test)."""
    con = midcap.connect(path)
    for k in range(n_tok):
        b = ou_bars(seed * 1000 + k, days)
        if cut is not None:
            other = ou_bars(alt_seed * 1000 + k, days)
            b = [x if x[0] < cut else y for x, y in zip(b, other)]
        con.executemany("INSERT INTO c15 VALUES (?,?,?,?,?,?,?)", [(mint(k),) + x for x in b])
        mc = (3e6, 8e6, 30e6, 90e6)[k % 4]
        con.execute("INSERT INTO tokens (mint, id, symbol, dex, mcap, liq, vol24, created_ts, member) VALUES "
                    "(?,?,?,?,?,?,?,?,1)", (mint(k), k + 1, f"TOK{k}", "raydium", mc, (150e3, 800e3)[k % 2],
                                            1e6 - k, NOW - 60 * D))
        con.execute("INSERT INTO snap (id, ts, px, mc, liq) VALUES (?,?,?,?,?)",
                    (k + 1, NOW - 3600, 1.0, int(mc), int((150e3, 800e3)[k % 2])))
    con.commit()
    con.close()


def old_simulate(b15, h1, rt, size_usd, cfg=None, crash=None):
    """intra.simulate as it was before the replay's hooks (the reference of "defaults keep today's behaviour")."""
    c = intra.cfg_of(cfg)
    hh = rule.h1_from_15m(b15, h1)
    out, free_at, day_n = [], 0, {}
    i = c["calm"] + 1
    while i < len(b15) - 1:
        t = b15[i][0] + M15
        d = t // 86400
        if t < free_at or day_n.get(d, 0) >= intra.MAX_ROUNDS:
            i += 1
            continue
        z = intra.zone(hh, t, c)
        st = crash.regime(t)[0] if crash is not None else None
        if intra.signal(b15[i][4], z, b15[:i + 1], c, st) is not None:
            i += 1
            continue
        b = b15[i + 1]
        e = b[1] * (1 + c["entry_slip"])
        pos = intra.position(e, b[0], z, rt, c)
        day_n[d] = day_n.get(d, 0) + 1
        j, hit = i + 1, None
        while j < len(b15):
            hit = rule.exit_on_bar(pos, b15[j], c)
            if hit:
                break
            j += 1
        if not hit:
            j = len(b15) - 1
            hit = ("kraj", b15[-1][4] * (1 - c["exit_slip"]))
        out.append((b[0], b15[j][0] + M15, e, hit[1], hit[0], rule.blend_ret(pos, hit[1], rt, c)))
        free_at = b15[j][0] + M15 + intra.COOLDOWN_S
        i = j + 1
    return out


def trade(tok, ts, ret, out_ts=None, tags=None):
    return {"token": tok, "ts": ts, "out_ts": out_ts or ts + H, "ret": ret, "pnl": ret * 15.0, "ret_demo": ret,
            "reason": "tp" if ret > 0 else "stop", "fx": (1 + ret) / (1 - RT), "rt": RT, "mae": -0.02, "mfe": 0.03,
            "hours": 1.0, "tags": tags or {}}


class Hooks(unittest.TestCase):
    def test_defaults_keep_todays_trades(self):
        crash = rule.crash_of(btc_rows())
        for seed in (3, 4):
            b = ou_bars(seed, 12)
            new = intra.simulate(b, None, RT, 15.0, None, crash)
            self.assertGreater(len(new), 5)
            self.assertEqual([(x["ts"], x["out_ts"], x["entry"], x["exit"], x["reason"], x["ret"]) for x in new],
                             old_simulate(b, None, RT, 15.0, None, crash))
            hooked = intra.simulate(b, None, RT, 15.0, None, crash, pit=lambda t, px: True, zcache={}, ctx={})
            self.assertEqual([x["ts"] for x in hooked], [x["ts"] for x in new])
            self.assertTrue(all(x["z_lo"] < x["z_hi"] and x["px0"] > 0 for x in new))

    def test_pit_refuses_entries(self):
        b = ou_bars(3, 12)
        self.assertEqual(intra.simulate(b, None, RT, 15.0, pit=lambda t, px: False), [])

    def test_same_bar_stop_and_target_is_a_stop(self):
        pos = {"entry": 1.0, "first": 1.0, "ts": 0, "tp_px": 1.13, "stop_px": 0.90, "be_px": 1.033}
        falling = (900, 1.0, 1.20, 0.85, 0.95, 0.0)          # high first on the default path: the target
        self.assertEqual(rule.exit_on_bar(dict(pos), falling, intra.cfg_of({"full_tp": True}))[0], "tp")
        hit = rule.exit_on_bar(dict(pos), falling, intra.cfg_of(replay.LIVE))
        self.assertEqual(hit[0], "stop")
        self.assertAlmostEqual(hit[1], 0.90 * (1 - 0.005))
        gap = (900, 1.15, 1.20, 0.85, 0.95, 0.0)             # an open already at the target still sells there
        self.assertEqual(rule.exit_on_bar(dict(pos), gap, intra.cfg_of(replay.LIVE))[0], "tp")

    def test_live_exits_on_bars(self):
        c = intra.cfg_of(replay.LIVE)
        self.assertIsNone(c["time_h"])
        z = {"lo": 0.95, "hi": 1.2}
        # no time stop: a flat position is still open after 3 days of bars
        pos = intra.position(1.0, 0, z, RT, c)
        for k in range(3 * 96):
            self.assertIsNone(rule.exit_on_bar(pos, (k * M15, 1.0, 1.01, 0.99, 1.0, 0.0), c))
        # the whole position at the target: no half, the net result is the target
        pos = intra.position(1.0, 0, z, RT, c)
        hit = rule.exit_on_bar(pos, (0, 1.0, pos["tp_px"] * 1.01, 1.0, pos["tp_px"], 0.0), c)
        self.assertEqual(hit[0], "tp")
        self.assertFalse(pos.get("half_px"))
        self.assertAlmostEqual(rule.blend_ret(pos, hit[1], RT, c), 0.10, places=6)
        # +5 % net arms the break-even; the fall back through it in the SAME bar fills at that level (about 0 % net),
        # not at the bar's open
        pos = intra.position(1.0, 0, z, RT, c)
        arm = pos["be_px"] * 1.05
        hit = rule.exit_on_bar(pos, (0, 1.0, arm * 1.001, 0.99, 1.0, 0.0), c)
        self.assertEqual(hit[0], "be")
        r = rule.blend_ret(pos, hit[1], RT, c)
        self.assertTrue(-0.006 < r < 0.0, r)
        # under +5 % net nothing is armed: the original stop stays
        pos = intra.position(1.0, 0, z, RT, c)
        self.assertIsNone(rule.exit_on_bar(pos, (0, 1.0, arm * 0.995, 0.99, 1.0, 0.0), c))
        self.assertLess(pos["stop_px"], 1.0)

    def test_reasoned_exit_on_macro_risk_off(self):
        b = ou_bars(3, 12)
        base = intra.simulate(b, None, RT, 15.0, replay.LIVE, ctx={"macro": None})
        off = intra.simulate(b, None, RT, 15.0, replay.LIVE, ctx={"macro": lambda t: "risk_off"})
        self.assertTrue({x["reason"] for x in off} & {"makro_zastita", "makro_rez"})
        self.assertFalse({x["reason"] for x in base} & {"makro_zastita", "makro_rez"})


class NoLookAhead(unittest.TestCase):
    def test_btc_up_reads_only_completed_candles(self):
        btc = odziv.closes(btc_rows())
        h1 = rule.h1_from_15m(ou_bars(7, 12), None)
        t = NOW - 2 * D + 2 * M15            # half an hour into an hour
        a = replay.btc_up_before(h1, btc, t)
        self.assertIsNotNone(a)
        later = [c if c[0] + H <= t else (c[0], c[1], c[2] * 3, c[3], c[4] * 3, c[5]) for c in h1]
        self.assertNotEqual(later, h1)       # the hour in progress and every later one changed
        self.assertEqual(replay.btc_up_before(later, btc, t), a)
        earlier = [(c[0], c[1], c[2], c[3], c[4] * (1.5 if t - 3 * D < c[0] < t - 2 * D and k % 2 else 1.0), c[5])
                   for k, c in enumerate(h1)]
        self.assertNotEqual(replay.btc_up_before(earlier, btc, t), a)
        # 16.11.: odziv.closes keys a candle by its CLOSE time, so even the plain call on every candle up to t no
        # longer reads the hour in progress (its key is after t)
        self.assertEqual(odziv.btc_up(odziv.closes([c for c in later if c[0] <= t]), btc, t), a)

    def _snap(self, ts, chg, state="dno_se_potvrduje", regime="neutral"):
        return {"ts": ts, "btc_state": state, "btc24": 0.01, "regime": regime, "platforms": {"meme": {"chg": chg}}}

    def test_recovery_reads_only_earlier_snapshots(self):
        t = NOW - D
        rows = [self._snap(t - 12 * H, -0.10), self._snap(t - 6 * H, -0.05), self._snap(t - 600, 0.02)]
        self.assertTrue(replay.Makro(rows).recovery_at(t))
        self.assertTrue(makro.recovery(rows[-1], rows[:-1], rows[-1]["ts"])[0])
        # a later snapshot (risk_off, the volume falling) changes nothing at t
        self.assertTrue(replay.Makro(rows + [self._snap(t + 60, -0.30, regime="risk_off")]).recovery_at(t))
        self.assertIsNone(replay.Makro(rows).recovery_at(t + 4 * H))           # no snapshot within 3 h: untagged
        self.assertIsNone(replay.Makro([]).recovery_at(t))
        self.assertFalse(replay.Makro(rows[1:]).recovery_at(t))                 # one reading missing: not a recovery

    def test_later_bars_never_change_an_earlier_trade(self):
        cut = NOW - 6 * D
        btc = btc_rows()
        out = []
        for c in (None, cut):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "midcap.db")
                make_db(p, n_tok=4, days=15, cut=c)
                con = midcap.ro(p)
                try:
                    per = {}
                    for row in replay.tokens(con)[0]:
                        b15 = replay.bars(con, "c15", row["mint"])
                        f = replay.facts_of(con, row, b15, NOW)
                        h1 = rule.h1_from_15m(b15, None)
                        crash = rule.crash_of(btc)
                        sim = replay.simulate_token(b15, h1, RT, 15.0, crash, f, {})
                        for x in sim[replay.BASE_KEY]:
                            x["tags"] = replay.tags_of(x, f, crash, {}, replay.Makro([]), h1, [k[0] for k in h1],
                                                       odziv.closes(btc), row["symbol"])
                            if x["ts"] < cut:
                                per[(row["mint"], x["ts"])] = (x["entry"], x["px0"], x["tags"])
                    out.append(per)
                finally:
                    con.close()
        self.assertGreater(len(out[0]), 10)
        self.assertEqual(out[0], out[1])
        self.assertTrue(any(v[2]["odziv"] in ("jak", "slab") for v in out[0].values()))

    def test_tags(self):
        crash = rule.crash_of(btc_rows())
        f = {"supply": 1e7, "liq": 800e3, "liq_day": {}, "created_ts": NOW - 60 * D}
        x = {"ts": NOW - D + 13 * H, "px0": 1.02, "z_lo": 1.0, "z_hi": 1.25}
        tg = replay.tags_of(x, f, crash, {(NOW - D + 13 * H) // D: "risk_on"}, replay.Makro([]), symbol="AAA")
        self.assertEqual((tg["mc"], tg["sirina"], tg["dubina"], tg["makro"], tg["token"]),
                         ("5-20M", "20-35 %", "donjih 10 %", "risk_on", "AAA"))
        self.assertEqual(tg["sat"], f"{(x['ts'] % D) // (6 * H) * 6:02d}-{(x['ts'] % D) // (6 * H) * 6 + 6:02d} UTC")
        self.assertIn(tg["btc"], ("normalno", "dno_se_potvrduje"))
        self.assertIsNone(tg["oporavak"])                 # no macro snapshot at that time: untagged, not guessed
        self.assertEqual(tg["odziv"], "nepoznat")
        self.assertEqual(tg["pravi"], "ispunjeni")
        self.assertEqual(replay.tags_of({**x, "px0": 0.99}, f, crash)["dubina"], "ispod dna zone")
        self.assertEqual(replay.tags_of({**x, "px0": 0.3}, {**f, "liq": 200e3}, crash)["pravi"], "nisu ispunjeni")
        self.assertEqual(replay.tags_of(x, None, None)["makro"], "nepoznato")

    def test_point_in_time_filter(self):
        f = {"supply": 1e7, "liq": 800e3, "liq_day": {(NOW - D) // D: 50e3}}
        ok = replay.pit_of(f, {NOW // D: "risk_off"})
        self.assertTrue(ok(NOW - 3 * D, 1.0))
        self.assertFalse(ok(NOW - 3 * D, 0.1))            # MC 1M then: under the collector's range
        self.assertFalse(ok(NOW - 3 * D, 30.0))           # MC 300M
        self.assertFalse(ok(NOW - D, 1.0))                # that day's liquidity under the demo's floor
        self.assertFalse(ok(NOW, 1.0))                    # the macro block
        self.assertTrue(replay.pit_of(f, {NOW // D: "risk_off"}, block_macro=False)(NOW, 1.0))

    def test_macro_block_and_its_diagnostic(self):
        from market import store as mstore
        with tempfile.TemporaryDirectory() as d:
            mpath, p = os.path.join(d, "market.db"), os.path.join(d, "midcap.db")
            con = mstore.connect(mpath)
            con.execute("INSERT INTO platforms VALUES ('pumpswap','PumpSwap','Dexs','dex')")
            day0 = NOW // D * D - 30 * D
            for k in range(30):
                con.execute("INSERT INTO daily VALUES (?,?,?)", (day0 + k * D, "pumpswap", 100e6 if k < 22 else 40e6))
            con.commit()
            con.close()
            make_db(p, n_tok=1, days=4)
            mc = midcap.ro(p)
            try:
                days = replay.daily_macro(mc, None, mpath)
            finally:
                mc.close()
        off = {k for k, v in days.items() if v == "risk_off"}
        self.assertIn((day0 + 24 * D) // D, off)
        self.assertNotIn((day0 + 22 * D) // D, off)       # the fall of day 22 is known from day 23 on
        b = ou_bars(3, 15)
        f = {"supply": 1e7, "liq": 800e3, "liq_day": {}}
        sim = replay.simulate_token(b, None, RT, 15.0, None, f, days)
        self.assertEqual(len(sim), 19)
        self.assertTrue(sim["risk_off"])
        self.assertTrue(all(x["ts"] // D in off for x in sim["risk_off"]))
        for k, trs in sim.items():
            if k != "risk_off":
                self.assertFalse([x for x in trs if x["ts"] // D in off], k)
        free = replay.simulate_token(b, None, RT, 15.0, None, f, {})
        self.assertEqual(free["risk_off"], [])
        self.assertTrue([x for x in free[replay.BASE_KEY] if x["ts"] // D in off])

    def test_cost_never_under_the_floor(self):
        self.assertGreaterEqual(replay.round_trip(5e6, "raydium", 150.0, 0.0005), 0.03)
        self.assertGreaterEqual(replay.round_trip(5e6, "raydium", 150.0, 0.0005, floor=0.05), 0.05)
        self.assertGreater(replay.round_trip(20e3, "raydium", 150.0, 0.0005, floor=0.0),
                           replay.round_trip(5e6, "raydium", 150.0, 0.0005, floor=0.0))


class WalkForward(unittest.TestCase):
    def test_split_60_40(self):
        tr, ho, ts = replay.split_days(range(100, 110))
        self.assertEqual((tr, ho, ts), (list(range(100, 106)), list(range(106, 110)), 106 * D))
        tr, ho, ts = replay.split_days(range(31))
        self.assertEqual((len(tr), len(ho)), (18, 13))
        self.assertEqual(replay.split_days([5]), ([5], [], None))

    def test_pick_on_train_only(self):
        split = 106 * D
        base = [trade("a", 100 * D + k * H, 0.01) for k in range(40)]
        few = [trade("a", 100 * D + k * H, 0.50) for k in range(29)]                 # the best EV, under 30 trades
        good = [trade("a", 100 * D + k * H, 0.03) for k in range(40)]
        late = [trade("a", 100 * D + k * H, -0.02) for k in range(40)] + \
               [trade("a", 107 * D + k * H, 0.90) for k in range(40)]               # great only in the holdout
        straddle = [trade("a", 105 * D, 5.0, out_ts=107 * D)]                        # closed after the split: nobody's
        wf = replay.walk_forward({replay.BASE_KEY: base, "malo": few, "dobra": good + straddle, "kasna": late}, split)
        self.assertEqual((wf["n"], wf["pick"]), (4, "dobra"))
        row = {r["key"]: r for r in wf["table"]}
        self.assertEqual((row["dobra"]["train_n"], row["dobra"]["train_ev_pct"]), (40, 3.0))
        self.assertEqual(row["kasna"]["train_n"], 40)
        self.assertEqual(len(replay.hold_of(late, split)), 40)
        self.assertEqual(replay.hold_of(good + straddle, split), [])
        self.assertIsNone(replay.walk_forward({replay.BASE_KEY: base[:10], "malo": few}, split)["pick"])
        tie = replay.walk_forward({"x": [dict(t) for t in base], replay.BASE_KEY: base}, split)
        self.assertEqual(tie["pick"], replay.BASE_KEY)       # a tie keeps today's rule
        self.assertEqual(len(replay.variants()), 18)
        self.assertIn(replay.BASE_KEY, [replay.key_of(v) for v in replay.variants()])

    def test_under_30_is_too_little_data(self):
        neg = [trade(f"t{k % 7}", 107 * D + k * H, -0.05) for k in range(29)]
        self.assertEqual(replay.measured(neg), {"n": 29, "malo": True})
        m = replay.measured(neg + [trade("t9", 108 * D, -0.05)])
        self.assertEqual(m["n"], 30)
        self.assertLess(m["ci90"][1], 0)
        self.assertEqual(replay.full(neg, 4, 15.0, 150.0), {"n": 29, "malo": True})
        tags, _un = replay.by_tag([dict(t, tags={"mc": "2-5M"}) for t in neg], 106 * D)
        self.assertEqual(tags["mc"][0]["izvan"], {"n": 29, "malo": True})
        res = {"base_key": replay.BASE_KEY, "holdout": {"n": 29, "malo": True}, "tags": tags, "all": {"n": 29, "malo": True}}
        self.assertEqual(replay.findings(res), [])
        self.assertIn("Premalo podataka", replay.verdict({**res, "all": {"n": 29}}))


class Findings(unittest.TestCase):
    def _res(self):
        split = 106 * D
        rnd = random.Random(2)
        trs = []
        for k in range(60):      # early hours lose, late hours win, the middle is noise around zero
            trs.append(trade(f"t{k % 9}", 107 * D + k * 600, -0.04 + rnd.gauss(0, 0.01), tags={"sat": "00-06 UTC"}))
            trs.append(trade(f"t{k % 9}", 108 * D + k * 600, 0.05 + rnd.gauss(0, 0.01), tags={"sat": "18-24 UTC"}))
            trs.append(trade(f"t{k % 9}", 109 * D + k * 600, rnd.gauss(0, 0.05), tags={"sat": "06-12 UTC"}))
            trs.append(trade(f"t{k % 9}", 101 * D + k * 600, -0.01, tags={"sat": "00-06 UTC"}))
        for x in trs:
            x["tags"]["makro"] = "nepoznato"
        tags, un = replay.by_tag(trs, split)
        return {"base_key": replay.BASE_KEY, "hold_days": 4, "tags": tags, "untagged": un,
                "all": replay.measured(trs), "holdout": replay.measured(replay.hold_of(trs, split)),
                "variants": {"n": 18, "pick": replay.BASE_KEY}, "risk_off": {"izvan": {"n": 0, "malo": True}}}

    def test_buckets(self):
        res = self._res()
        fs = replay.findings(res)
        kinds = {f["tekst"].split(" (")[0]: f for f in fs}
        self.assertIn("ne ulaziti: doba dana: 00-06 UTC", kinds)
        self.assertIn("prednost: doba dana: 18-24 UTC", kinds)
        self.assertFalse(any("06-12" in f["tekst"] for f in fs))       # its interval straddles zero: not a finding
        self.assertFalse(any("nepoznato" in f["tekst"] for f in fs))   # an unknown label is no decision
        bad = kinds["ne ulaziti: doba dana: 00-06 UTC"]
        self.assertEqual((bad["vrsta"], bad["n"]), ("ne_ulaziti", 60))
        self.assertLess(bad["ci90"][1], 0)
        self.assertIn("60 tradeova", bad["tekst"])
        self.assertIn(f"{bad['ev_pct']:+.2f} %", bad["tekst"])
        self.assertIn("u prvom dijelu -1.00 % na 60 tradeova", bad["tekst"])
        self.assertGreater(kinds["prednost: doba dana: 18-24 UTC"]["ci90"][0], 0)
        self.assertIn("nije dokazano", replay.verdict(res))

    def test_variant_and_macro_block(self):
        res = self._res()
        win = replay.measured([trade(f"t{k % 9}", 107 * D + k * 600, 0.04 + 0.001 * (k % 5)) for k in range(50)])
        lose = replay.measured([trade(f"t{k % 9}", 107 * D + k * 600, -0.04 - 0.001 * (k % 5)) for k in range(50)])
        v = {"bottom": 0.15, "tp": 6.0, "stop_cap": 0.08}
        res["variants"] = {"n": 18, "pick": replay.key_of(v), "pick_text": replay.text_of(v), "pick_holdout": win}
        res["risk_off"] = {"izvan": lose}
        fs = replay.findings(res)
        self.assertEqual(fs[0]["vrsta"], "promjena")
        self.assertIn("ulaz u donjih 15 % zone, cilj +6 % neto, stop najviše −8 %", fs[0]["tekst"])
        self.assertEqual(fs[1]["vrsta"], "zadrzati")
        res["variants"]["pick_holdout"] = lose              # a picked variant that loses out of sample: no advice
        res["risk_off"] = {"izvan": win}
        fs = replay.findings(res)
        self.assertEqual(fs[0]["vrsta"], "promjena")
        self.assertIn("zabrana ulaza dok tržište pada košta", fs[0]["tekst"])
        self.assertFalse(any("vrijedilo bi promijeniti pravilo" in f["tekst"] for f in fs))

    def test_a_losing_rule_lists_only_the_worse_buckets(self):
        split = 106 * D
        trs = [trade(f"t{k % 9}", 107 * D + k * 600, -0.02 - 0.0001 * (k % 7), tags={"mc": "2-5M"}) for k in range(60)]
        trs += [trade(f"t{k % 9}", 108 * D + k * 600, -0.06 - 0.0001 * (k % 7), tags={"mc": "5-20M"}) for k in range(60)]
        tags, _un = replay.by_tag(trs, split)
        res = {"base_key": replay.BASE_KEY, "hold_days": 4, "tags": tags, "all": replay.measured(trs),
               "holdout": replay.measured(trs)}
        fs = replay.findings(res)
        self.assertEqual([f["tekst"].split(" (")[0] for f in fs], ["ne ulaziti: tržišna vrijednost: 5-20M"])
        self.assertIn("GUBI", replay.verdict(res))


class Run(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "midcap.db")
        make_db(cls.path, n_tok=10, days=15)
        cls.lines = []
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("mreža")), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("mreža")):
            cls.res = replay.run(NOW, cls.lines.append, cls.path, btc=btc_rows(), macro_days={}, sol=150.0)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_result(self):
        r = self.res
        self.assertEqual((r["tokens"], r["partial"], r["size_sol"], r["rt_floor"]), (10, False, 0.1, 0.03))
        self.assertGreaterEqual(r["rt_med_pct"], 3.0)
        self.assertEqual(r["train_days"] + r["hold_days"], r["days"])
        self.assertAlmostEqual(r["train_days"] / r["days"], 0.6, delta=0.07)
        self.assertEqual(r["variants"]["n"], 18)
        self.assertEqual(len(r["variants"]["table"]), 18)
        a, h = r["all"], r["holdout"]
        self.assertGreaterEqual(a["n"], 30)
        for k in ("ev_pct", "ci90", "hit", "hold_med_h", "max_dd_sol", "sum_sol", "per_day", "reasons"):
            self.assertIn(k, a)
        self.assertLessEqual(a["ci90"][0], a["ev_pct"])
        self.assertGreaterEqual(a["ci90"][1], a["ev_pct"])
        self.assertLess(h["n"], a["n"])
        self.assertFalse(set(a["reasons"]) & {"time", "trail"})          # no time stop, no half + trailing
        self.assertEqual(set(r["tags"]), set(replay.TAGS))
        self.assertEqual(sum(x["svi"]["n"] for x in r["tags"]["sat"]), a["n"])
        self.assertEqual(r["untagged"].get("oporavak"), a["n"])           # no macro snapshots: untagged and said
        for rows in r["tags"].values():
            for x in rows:
                self.assertTrue(x["izvan"].get("malo") or x["izvan"]["n"] >= 30)
        self.assertEqual(len(r["biases"]), 3)
        self.assertTrue(r["verdict"])
        for f in r["findings"]:
            self.assertGreaterEqual(f["n"], 30)
            self.assertTrue(f["ci90"][1] < 0 or f["ci90"][0] > 0)
        self.assertLess(len(replay.dumps(r)), 60_000)

    def test_stored_and_logged(self):
        self.assertEqual(replay.latest(self.path)["ts"], NOW)
        self.assertEqual(len(self.lines), 1)
        ln = self.lines[0]
        self.assertTrue(ln.startswith("veliki replay: 10 tokena"), ln)
        for s in (f"n={self.res['all']['n']}", "EV ", "interval 90 % [", "izvan uzorka", "varijanti isprobano 18",
                  "glavni nalaz: "):
            self.assertIn(s, ln)

    def test_bounded_by_budget_and_tokens(self):
        lines = []
        r = replay.run(NOW, lines.append, self.path, budget_s=0, btc=btc_rows(), macro_days={}, sol=150.0, save=False)
        self.assertEqual((r["tokens"], r["partial"]), (0, True))
        self.assertIn("djelomično", lines[0])
        self.assertIn("još nema nijedan trade", r["verdict"])
        r = replay.run(NOW, lines.append, self.path, max_tokens=2, btc=btc_rows(), macro_days={}, sol=150.0, save=False)
        self.assertEqual(r["tokens"], 2)
        self.assertEqual(replay.latest(self.path)["tokens"], 10)          # save=False left the stored result alone
        r = replay.run(NOW + 60, lines.append, self.path, budget_s=0, btc=btc_rows(), macro_days={}, sol=150.0)
        self.assertEqual(r["tokens"], 0)
        self.assertIn("zadnji spremljeni rezultat ostaje", lines[-1])
        self.assertEqual(replay.latest(self.path)["ts"], NOW)             # a cut pass never erases a full result

    def test_never_raises(self):
        lines = []
        self.assertEqual(replay.run(NOW, lines.append, os.path.join(self.tmp.name, "nema.db")), {})
        self.assertIn("nema podataka", lines[-1])
        with mock.patch.object(replay, "compute", side_effect=RuntimeError("puklo")):
            self.assertEqual(replay.run(NOW, lines.append, self.path, btc=[]), {})
        self.assertIn("veliki replay: nije uspio (RuntimeError: puklo)", lines[-1])

        def bad_log(_s):
            raise OSError("log")
        self.assertEqual(replay.run(NOW, bad_log, os.path.join(self.tmp.name, "nema.db")), {})
        r = replay.run(NOW, lines.append, self.path, btc=[], macro_days={}, sol=150.0, max_tokens=2, save=False)
        self.assertEqual(r["tokens"], 2)                                  # no BTC closes at all: still a result

    def test_short_history_is_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "midcap.db")
            make_db(p, n_tok=3, days=4)
            con = midcap.ro(p)
            try:
                rows, short, gone = replay.tokens(con)
            finally:
                con.close()
            self.assertEqual((rows, short, gone), ([], 3, 0))

    def test_report_section(self):
        from report import midcap as rmid, render
        p = {k: os.path.join(self.tmp.name, f"{k}-nema.db") for k in ("league", "trade", "veliki", "holderi",
                                                                      "insajderi", "usage")}
        p["midcap"] = self.path
        rp = rmid.replay(NOW, p)
        self.assertEqual(rp["presuda"], self.res["verdict"])
        self.assertEqual([r["naziv"] for r in rp["redovi"]][:2],
                         ["Svi dani", f"Izvan uzorka (zadnjih {self.res['hold_days']} dana)"])
        html = render.replay_block(rp)
        for s in ("Dnevni raspon: povijesni test na svim midcapovima", "Tradeova", "Prosjek po tradeu", "90 % interval",
                  "Svi dani", "Izvan uzorka", "Kako čitati i gdje test griješi", "Preživjeli tokeni", "Kratko razdoblje",
                  "Izvršenje na svijećama od 15 minuta", "Isprobano 18 unaprijed zadanih varijanti", "10 tokena"):
            self.assertIn(s, html)
        self.assertLess(html.index("Dnevni raspon: povijesni test"), html.index("Tradeova"))   # the verdict first
        self.assertIn(render.e(self.res["verdict"]), html)
        low = html.lower()
        for s in ("holdout", "walk-forward", "replay", "bucket", "risk_off", "risk_on", "dno25/", "none", "btc_up",
                  "<script", "<svg"):
            self.assertNotIn(s, low)
        self.assertEqual(render.replay_block(None), "")
        self.assertIsNone(rmid.replay(NOW, {**p, "midcap": os.path.join(self.tmp.name, "nema.db")}))
        # too little data reads "premalo podataka", never a number
        small = replay.summary({**self.res, "holdout": {"n": 7, "malo": True}, "findings": []})
        html = render.replay_block(small)
        self.assertIn("premalo podataka", html)
        self.assertIn("Nijedna skupina tradeova nema dovoljno jasan rezultat", html)
        # the strategies comparison row
        rows = rmid.strategies(NOW, p, rinfo={}, hd={})
        row = [r for r in rows if r["naziv"] == "Dnevni raspon: povijesni test na svim midcapovima"]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["vrsta"], "backtest")
        ho = self.res["holdout"]
        if not ho.get("malo"):
            self.assertEqual((row[0]["n"], row[0]["ev_pct"], row[0]["ci"], row[0]["ci_label"]),
                             (ho["n"], ho["ev_pct"], ho["ci90"], "90 %"))
            self.assertIn("izvan uzorka", row[0]["opis"])
        self.assertEqual([r for r in rmid.strategies(NOW, {**p, "midcap": p["league"]}, rinfo={}, hd={})
                          if r["naziv"].startswith("Dnevni raspon: povijesni")], [])

    def test_morning_report_has_the_section(self):
        from report import render
        m = {"replay": replay.summary(self.res), "pravila": None, "novcanik": {}}
        html = "".join(render.midcap_sections({"midcap": m}, {}))
        self.assertLess(html.index("Pravila: dokaz izvan uzorka i pravi novac"),
                        html.index("Dnevni raspon: povijesni test na svim midcapovima"))
        self.assertLess(html.index("Dnevni raspon: povijesni test na svim midcapovima"), html.index("Novčanik i stropovi"))


class Cli(unittest.TestCase):
    def _main(self, argv, last, night=True):
        import run_veliki
        with mock.patch.object(replay, "latest", return_value=last), mock.patch.object(replay, "run") as run, \
                mock.patch.object(run_veliki, "in_night", return_value=night), mock.patch("os.nice"):
            self.assertEqual(run_veliki.main(argv), 0)
        return run.call_count

    def test_replay_command(self):
        import time
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3600))
        self.assertEqual(self._main(["replay"], {"ts": 1, "day": today}), 1)               # asked for: runs
        self.assertEqual(self._main(["replay", "--ako-nema"], None), 1)                     # after a deploy, no result
        self.assertEqual(self._main(["replay", "--ako-nema"], {"ts": 1, "day": "2026-01-01"}), 0)
        self.assertEqual(self._main(["replay", "--night"], {"ts": 1, "day": "2026-01-01"}), 1)
        self.assertEqual(self._main(["replay", "--night"], {"ts": 1, "day": today}), 0)     # once a day
        self.assertEqual(self._main(["replay", "--night"], None, night=False), 0)           # only in the night window
        self.assertEqual(self._main(["replay", "--night", "--force"], {"ts": 1, "day": today}, night=False), 1)

    def test_start_sh_schedules_it_under_the_heavy_lock(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn("python3 -m ops.heavy run_veliki.py replay --ako-nema", sh)
        self.assertIn("python3 -m ops.heavy --night run_veliki.py replay --night", sh)


if __name__ == "__main__":
    unittest.main()
