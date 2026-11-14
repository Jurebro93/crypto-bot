"""Zadnjih 5 (14.11., vlasnik; kol/zadnjih5.py): follow the influencers / wallets whose last 5 calls reached +10 %, exit
at +10 %, after fees. The selection (strict 5/5 and the variants), no look-ahead (an outcome counts only once it was
known, the nightly refresh), one trade's path (target, stop, both in one minute, time stop, lag, the stored levels),
the real account's cost, the simulation with one position per token and the switch caps, the gate (EV <= 0 or fewer
than 30 trades: no follow; EV > 0 on 30+: follows with tp 10%), unfollow when a source drops out, a follow the owner
stopped is not taken back, the wallet path from PumpPortal prints, the MCP tool, the flag and the wiring. No network:
every database is a temp file."""
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kol import minute, zadnjih5 as z  # noqa: E402
from kol import store as kstore  # noqa: E402
from league import copy as lcopy, store as lstore  # noqa: E402
from trade import settings  # noqa: E402

D = 86400
NOW = 1_800_000_000 - 1_800_000_000 % 86400 + 12 * 3600   # a UTC noon (13:00 Zagreb in winter)


def mint(tag, i, pump=False):
    return f"{tag}{i:04d}" + "x" * 30 + ("pump" if pump else "zzzz")


def ev(src, ts, gain, known=None, tok=None, **kw):
    e = {"src": src, "tok": tok or f"t{src}{ts}", "ts": ts, "known": ts + 4200 if known is None else known,
         "gain": gain, "why": None, "cost": 0.02, "usd": 15.0, "liq": None}
    e.update(kw)
    return e


def sim_ok(gross=0.10, kind="tp", t_in=None, t_out=None):
    return (kind, gross, t_in, t_out, True, "svijeće")


class Selection(unittest.TestCase):
    def test_variants(self):
        good = [0.12, 0.30, 0.10, 0.11, 0.50]
        self.assertTrue(z.qualifies(good, "strogo"))
        self.assertFalse(z.qualifies(good[:4], "strogo"))                    # fewer than 5 measured: no
        one_bad = [0.12, 0.02, 0.10, 0.11, 0.50]
        self.assertFalse(z.qualifies(one_bad, "strogo"))
        self.assertTrue(z.qualifies(one_bad, "4od5"))
        self.assertFalse(z.qualifies([0.12, 0.02, 0.0, 0.11, 0.50], "4od5"))
        self.assertTrue(z.qualifies([0.0, 0.0, 0.0, 0.0, 0.6], "prosjek"))   # the mean of 5 max gains >= +10 %
        self.assertFalse(z.qualifies([0.0, 0.0, 0.0, 0.0, 0.4], "prosjek"))
        self.assertTrue(z.qualifies([], "svi"))
        self.assertTrue(z.qualifies([0.0] * 3 + good, "strogo"))             # only the last 5 count

    def test_window_has_no_look_ahead(self):
        h = [ev("a", 1000 * i, 0.2, known=1000 * i + 500) for i in range(1, 7)]
        h[4]["known"] = 6500
        tss = [e["ts"] for e in h]
        # at the 6th call's own time: its own outcome never counts, the 5th is not known yet
        self.assertEqual(len(z.window(h, tss, 6000)), 4)
        h[4]["known"] = 5500
        self.assertEqual(len(z.window(h, tss, 6000)), 5)
        h[2]["gain"] = None   # unmeasured: skipped, the window reaches one further back
        self.assertEqual(z.window(h, tss, 6000), [0.2] * 4)

    def test_walk_per_call_and_nightly_refresh(self):
        # 2 h apart, outcomes known 70 min later: from the 6th call on the source is selected at every call
        base = z.refresh_cut(NOW - 5 * D) + 4 * 3600
        h = [ev("a", base + 7200 * i, 0.2, known=base + 7200 * i + 4200) for i in range(10)]
        srcs = z.by_source(h)
        sel = z.walk(srcs, "strogo", "poziv")
        self.assertEqual([e["ts"] for e in sel], [e["ts"] for e in h[5:]])
        # nightly: the window is frozen at the last 03:00 Zagreb before the call, so the same day enters nothing
        self.assertEqual(z.walk(srcs, "strogo", "noc"), [])
        late = ev("a", base + D, 0.0)
        sel = z.walk(z.by_source(h + [late]), "strogo", "noc")
        self.assertEqual([e["ts"] for e in sel], [late["ts"]])
        self.assertEqual(len(z.walk(srcs, "svi")), 10)

    def test_refresh_cut_is_the_last_3am_zagreb(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Zagreb")
        at = int(dt.datetime(2026, 11, 14, 2, 30, tzinfo=tz).timestamp())
        self.assertEqual(dt.datetime.fromtimestamp(z.refresh_cut(at), tz).strftime("%d. %H:%M"), "13. 03:00")
        at = int(dt.datetime(2026, 11, 14, 4, 0, tzinfo=tz).timestamp())
        self.assertEqual(dt.datetime.fromtimestamp(z.refresh_cut(at), tz).strftime("%d. %H:%M"), "14. 03:00")

    def test_ok_windows_and_selected_now(self):
        h = [ev("a", 1000 * i, g) for i, g in enumerate([0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.0, 0.2], 1)]
        self.assertEqual(z.ok_windows(h), 2)
        self.assertEqual(z.selected_now(z.by_source(h), 10 ** 6), {})          # the newest window has the miss
        self.assertEqual(list(z.selected_now(z.by_source(h[:6]), 10 ** 6)), ["a"])


def candles(m0, rows):
    """rows: [(minute offset, o, h, l, c)] -> candles from minute m0."""
    return [(m0 + 60 * k, o, hi, lo, c, 1.0) for k, o, hi, lo, c in rows]


class Path(unittest.TestCase):
    M0 = 1_800_000_000 - 1_800_000_000 % 60

    def test_target_stop_both_time_and_lag(self):
        cs = candles(self.M0, [(0, 1, 1, 1, 1), (1, 1, 1.02, 0.99, 1.0), (2, 1.0, 1.12, 1.0, 1.1), (3, 1.1, 1.1, 0.3, 0.3)])
        k, g, t_in, t_out, ok = z.sim(cs, self.M0 + 70, 0.10, 0.60)
        self.assertEqual((k, g, ok), ("tp", 0.10, True))
        self.assertEqual((t_in, t_out), (self.M0 + 120, self.M0 + 180))      # entry: the close of the minute of call+lag
        # entered a minute later (after the pump, at 1.1): the dump is the stop, under -70 % booked at the low itself
        k, g, *_ = z.sim(cs, self.M0 + 130, 0.10, 0.60)
        self.assertEqual((k, round(g, 4)), ("sl", round(0.3 / 1.1 - 1, 4)))
        both = candles(self.M0, [(0, 1, 1, 1, 1), (1, 1.0, 1.2, 0.35, 1.0)])
        self.assertEqual(z.sim(both, self.M0 + 10, 0.10, 0.60)[0], "sl")      # target and stop in one minute: the stop
        flat = candles(self.M0, [(0, 1, 1, 1, 1)] + [(k, 1.0, 1.05, 0.95, 1.03) for k in range(1, 70)])
        k, g, _ti, t_out, ok = z.sim(flat, self.M0 + 10, 0.10, 0.60)
        self.assertEqual((k, round(g, 4), ok, t_out), ("time", 0.03, True, self.M0 + 60 + 3600))
        # the data ends 20 min after the entry: incomplete (booked at the last close, counted apart)
        self.assertFalse(z.sim(flat, self.M0 + 10, 0.10, 0.60, covered_to=self.M0 + 1200)[4])
        self.assertIsNone(z.sim(cs, self.M0 + 3600, 0.10, 0.60))           # no candle near the entry: no trade

    def test_wick_cap_and_stop_levels(self):
        spike = candles(self.M0, [(0, 1, 1, 1, 1), (1, 1.0, 9.0, 1.0, 1.0)])
        self.assertEqual(z.max_gain(spike, self.M0 + 10), 2.0)               # a one-print wick counts up to 3x the body
        self.assertEqual(z.stop_booked(-0.62, 0.60), -0.60)
        self.assertEqual(z.stop_booked(-0.65, 0.20), -0.60)
        self.assertEqual(z.stop_booked(-0.95, 0.60), -0.95)
        self.assertEqual(z.stop_booked(-0.21, 0.20), -0.20)

    def test_prints_to_candles(self):
        cs = z.to_candles([(self.M0 + 5, 1.0), (self.M0 + 30, 1.3), (self.M0 + 50, 1.1), (self.M0 + 70, 0.9)])
        self.assertEqual(cs[0][:5], (self.M0, 1.0, 1.3, 1.0, 1.1))
        self.assertEqual(cs[1][:5], (self.M0 + 60, 0.9, 0.9, 0.9, 0.9))

    def test_levels_fallback(self):
        row = {"ts": self.M0 + 20, "hi60": 0.2, "lo60": -0.1, "r60": 0.05, "t5": 1, "t10": 3, "t15": 8, "t20": 20,
               "t30": None, "sl_min": None, "lv": json.dumps({"u": {"5": 1, "10": 3, "15": 8, "20": 20}, "d": {"10": 30},
                                                               "v": 2})}
        self.assertEqual(z.level_sim(dict(row), 0.10, 0.60)[:2], ("tp", 0.10))
        # +12 % (10 % after costs): taken only when the next stored level, +15, was reached before the stop
        self.assertEqual(z.level_sim(dict(row), 0.12, 0.60)[:2], ("tp", 0.12))
        row2 = dict(row, lv=json.dumps({"u": {"5": 1, "10": 3}, "d": {"10": 4, "60": 9}, "v": 2}), lo60=-0.65)
        self.assertEqual(z.level_sim(row2, 0.12, 0.60)[:2], ("sl", -0.60))


class Cost(unittest.TestCase):
    def test_real_account_round_trip(self):
        from rangedca import rules
        from trade import cost
        sol = 150.0
        usd = 0.1 * sol
        got = z.round_trip(40_000, mint("a", 1, pump=True), sol, 0.0005)
        imp = cost.impact(usd, 40_000)
        want = 2 * (0.003 + 0.001) + 2 * imp + 2 * 0.0005 * sol / usd
        self.assertAlmostEqual(got, want, 9)
        self.assertAlmostEqual(z.round_trip(None, mint("a", 1), sol, 0.0005),
                               2 * (0.0025 + 0.001) + 2 * cost.impact(usd, cost.DEFAULT_LIQ) + 0.01, 9)
        self.assertGreater(z.round_trip(15_000, mint("a", 1), sol, 0.0005), z.round_trip(200_000, mint("a", 1), sol, 0.0005))
        self.assertEqual(rules.ROUTE_FEE, 0.001)

    def test_curve_guess(self):
        self.assertTrue(z.curve_guess(mint("a", 1, True), 40_000, None, 150))     # a pump mint under the bond, no pool
        self.assertFalse(z.curve_guess(mint("a", 1, True), 40_000, 20_000, 150))  # DEX liquidity seen: bonded
        self.assertFalse(z.curve_guess(mint("a", 1, True), 80_000, None, 150))    # above the bonding market cap
        self.assertFalse(z.curve_guess(mint("a", 1), 40_000, None, 150))          # not a pump.fun mint
        self.assertTrue(z.curve_guess(mint("a", 1, True), 90_000, None, 150, pool="pump"))
        self.assertFalse(z.curve_guess(mint("a", 1, True), 40_000, None, 150, pool="pump-amm"))


class Simulate(unittest.TestCase):
    def cand(self, src, tok, t_in, t_out, gross, kind="tp", cost=0.02):
        e = ev(src, t_in - 60, 0.2, tok=tok)
        e["cost"] = cost
        e["sims"] = {"bruto": (kind, gross, t_in, t_out, True, "svijeće")}
        return e

    def test_one_position_per_token_and_rules(self):
        a = self.cand("a", "T", 1000, 2000, 0.10)
        b = self.cand("b", "T", 1500, 2500, -0.6, "sl")        # the same token while it is open: not a second trade
        c = self.cand("c", "U", 1600, 2600, -0.6, "sl")
        d = dict(self.cand("d", "V", 1700, 1800, 0.1), why="MC ispod 30k")
        tr, sk = z.simulate([a, b, c, d])
        self.assertEqual([t["src"] for t in tr], ["a", "c"])
        self.assertEqual((sk["token"], sk["pravila"]), (1, 1))
        self.assertAlmostEqual(tr[0]["net"], 0.08)

    def test_switch_caps(self):
        base = NOW
        cands = [self.cand("s", f"T{i}", base + i, base + 10_000, 0.1) for i in range(12)]
        tr, sk = z.simulate(cands, caps={"max_open": 10, "max_buys_day": 100, "max_loss_day": 0.5})
        self.assertEqual((len(tr), sk["otvoreno"]), (10, 2))
        cands = [self.cand("s", f"T{i}", base + 100 * i, base + 100 * i + 50, 0.1) for i in range(5)]
        tr, sk = z.simulate(cands, caps={"max_open": 10, "max_buys_day": 3, "max_loss_day": 0.5})
        self.assertEqual((len(tr), sk["dan"]), (3, 2))
        # -0.5 SOL realized in the day (9 stops of -0.6 x 0.1 SOL = -0.54): no more buys that day
        cands = [self.cand("s", f"L{i}", base + 100 * i, base + 100 * i + 50, -0.58, "sl") for i in range(12)]
        tr, sk = z.simulate(cands, caps={"max_open": 10, "max_buys_day": 100, "max_loss_day": 0.5})
        self.assertEqual((len(tr), sk["gubitak"]), (9, 3))

    def test_summary(self):
        tr, _ = z.simulate([self.cand("a", f"T{i}", NOW + 1000 * i, NOW + 1000 * i + 100, g, k)
                            for i, (g, k) in enumerate([(0.1, "tp"), (0.1, "tp"), (-0.6, "sl"), (0.1, "tp")])])
        s = z.summarize(tr, 2.0, 0.6)
        self.assertEqual((s["n"], s["hit"], s["per_day"]), (4, 0.75, 2.0))
        self.assertAlmostEqual(s["ev_gross_pct"], (0.3 - 0.6) / 4 * 100, 6)
        self.assertAlmostEqual(s["ev_net_pct"], (0.3 - 0.6) / 4 * 100 - 2, 6)
        self.assertAlmostEqual(s["pnl_sol"], (0.3 - 0.6 - 0.08) * 0.1, 6)
        self.assertAlmostEqual(s["max_dd_sol"], 0.062, 6)                     # the stop after two wins
        self.assertAlmostEqual(s["need_sl"], (0.6 + 0.02) / 0.7, 4)
        self.assertAlmostEqual(s["ev_net_usd"], s["ev_net_pct"] / 100 * 15, 4)


class Gate(unittest.TestCase):
    def test_gate(self):
        self.assertFalse(z.gate({"n": 29, "ev_net_pct": 5.0})[0])
        on, why = z.gate({"n": 40, "ev_net_pct": -0.1})
        self.assertFalse(on)
        self.assertIn("≤ 0", why)
        self.assertFalse(z.gate({"n": 40, "ev_net_pct": 0.0})[0])
        self.assertTrue(z.gate({"n": 30, "ev_net_pct": 0.01})[0])
        self.assertFalse(z.gate({"n": 0})[0])

    def test_plan(self):
        ours = {"a": 1, "b": 2}
        add, rem = z.plan(ours, {"a": 1, "b": 2, "m": 9}, ["a", "c", "m", "d"], True, skip={"d"})
        self.assertEqual(add, ["c"])          # m is the owner's own follow (never taken over), d he stopped himself
        self.assertEqual(rem, [("b", 2)])     # b dropped out of the selection
        self.assertEqual(z.plan(ours, {}, ["a"], False), ([], [("a", 1), ("b", 2)]))


class DbBase(unittest.TestCase):
    """Temp minute.db / kol.db / trade.db / league.db."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        j = lambda *n: os.path.join(self.tmp, *n)  # noqa: E731
        self.p = {"minute": j("minute.db"), "kol": j("kol.db"), "hype": j("hype.db"), "wallets": j("wallets.db"),
                  "events": j("nema-events.db"), "league": j("league.db"), "trade": j("trade.db"),
                  "fast": j("nema-fast.db"), "market": j("nema-market.db"), "out": j("output", "zadnjih5.json")}
        self._db, self._ldb = settings.DB, lstore.DB
        settings.DB, lstore.DB = self.p["trade"], self.p["league"]
        settings._FLAG_CACHE.clear()
        settings.connect(self.p["trade"]).close()
        lstore.connect(self.p["league"]).close()
        self.mc = minute.connect(self.p["minute"])
        self.kc = kstore.connect(self.p["kol"])
        self.patches = [mock.patch.object(z, "tx_fee", return_value=(0.0005, "test")),
                        mock.patch("wallets.rang.gate", return_value=(None, ""))]
        for pt in self.patches:
            pt.start()

    def tearDown(self):
        for pt in self.patches:
            pt.stop()
        self.mc.close()
        self.kc.close()
        settings.DB, lstore.DB = self._db, self._ldb
        settings._FLAG_CACHE.clear()

    def call(self, handle, i, ts, rows, hi60):
        """One measured call at ts with its 1-min candles (rows relative to the call minute) and stored path."""
        tok = mint(handle[:3], i)
        m0 = ts - ts % 60
        cs = candles(m0, rows)
        tid = f"{handle}-{i}"
        self.mc.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, lag_s, mcap_e, hi60, lo60, r60, "
                        "t10, sl_min, first_caller, measured_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                        (tid, tok, handle, ts, 1.0, m0 + 60 - ts, 100_000, hi60, -0.1, 0.0, None, None, ts + 4200))
        self.mc.execute("INSERT INTO call_lv VALUES (?,?,?,?)", (tid, tok, ts, json.dumps({"u": {}, "d": {}, "v": 2})))
        self.mc.execute("INSERT INTO call_candles VALUES (?,?,?,?,?,1,?)",
                        (tok, cs[0][0], cs[-1][0], len(cs), minute._pack(cs), ts))
        self.kc.execute("INSERT OR REPLACE INTO snaps (token, ts, price, liq, mcap) VALUES (?,?,?,?,?)",
                        (tok, ts, 1.0, 60_000, 100_000))
        return tok

    WIN = [(0, 1, 1, 1, 1), (1, 1, 1.01, 0.99, 1.0), (2, 1.0, 1.15, 1.0, 1.12)] + [(k, 1.1, 1.1, 1.05, 1.1) for k in range(3, 70)]
    # the pump is over before our entry (call + 60 s): the history says +15 %, the copy buys the top and is stopped
    LATE = [(0, 1, 1.15, 1, 1.15), (1, 1.15, 1.15, 1.1, 1.14), (2, 1.14, 1.14, 0.3, 0.35)] + \
           [(k, 0.35, 0.35, 0.3, 0.3) for k in range(3, 70)]

    def fill(self, path, n=60, handle="dobar", hi60=0.15):
        start = NOW - 25 * D
        for i in range(n):
            ts = start + i * 9 * 3600 + 20
            self.call(handle, i, ts, path, hi60)
        self.mc.commit()
        self.kc.commit()

    def follows(self, active=True):
        con = lstore.connect(self.p["league"])
        try:
            lcopy.ensure(con)
            return [dict(r) for r in con.execute("SELECT * FROM follows WHERE active = ?", (1 if active else 0,))]
        finally:
            con.close()

    def run_(self):
        logs = []
        out = z.run(NOW, self.p, log=logs.append)
        return out, logs


class Db(DbBase):
    """The whole run: walk-forward, gate, follows."""

    def test_ev_above_zero_follows_with_tp_10(self):
        self.fill(self.WIN)
        out, logs = self.run_()
        k = out["types"]["kol"]
        self.assertEqual(k["coverage"]["svijeće"], 60)
        g = k["variants"]["strogo"]["noc"]["bruto"]
        self.assertGreaterEqual(g["n"], 30)
        self.assertEqual(g["hit"], 1.0)
        self.assertGreater(g["ev_net_pct"], 7.0)
        self.assertLess(g["ev_net_pct"], g["ev_gross_pct"])                     # the fees are taken off
        self.assertTrue(out["gate"]["kol"]["on"])
        f = self.follows()
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["user"], f[0]["kind"], f[0]["target"]), (settings.LEAGUE_USER, "kol", "dobar"))
        ex = json.loads(f[0]["exit"])
        # exactly the measured exit: +10 % / the model's stop from the entry price, 60 min, no grace, out of the fast path
        self.assertEqual((ex["mode"], ex["tp"], ex["sl"], ex["hold_s"], ex["from_eff"], ex["no_grace"], ex["src"]),
                         ("tpsl", "10%", "-60%", 3600, False, True, "zadnjih5"))
        self.assertEqual(out["assumptions"]["sl_pct"], 60.0)
        self.assertTrue(all(ln.startswith("zadnjih 5: ") for ln in logs))
        self.assertTrue(any(ln.startswith("zadnjih 5: odluka: ") and "pratim" in ln for ln in logs))
        self.assertEqual(sum(1 for ln in logs if ln.startswith("zadnjih 5: influenceri ")), 4)
        self.assertEqual(out["types"]["kol"]["top"][0]["id"], "dobar")
        self.assertEqual(out["follow"]["wallet"]["changed"], False)             # no wallet data: nothing touched
        tcon = settings.connect(self.p["trade"])
        try:
            raw = settings.raw(tcon)
        finally:
            tcon.close()
        self.assertTrue(raw["zadnjih5_auto"]["kol"]["on"])
        self.assertEqual(raw["zadnjih5_follows"]["kol"], [f[0]["id"]])
        # dropped out: the newest call missed +10 %, so its window fails and the follow stops
        self.call("dobar", 99, NOW - 3 * 3600, [(0, 1, 1, 1, 1)] + [(k, 1, 1.02, 0.98, 1) for k in range(1, 70)], 0.02)
        self.mc.commit()
        self.kc.commit()
        out, logs = self.run_()
        self.assertEqual(out["types"]["kol"]["now"]["strogo"], 0)
        self.assertEqual(self.follows(), [])
        self.assertEqual(self.follows(False)[0]["target"], "dobar")
        self.assertEqual(out["follow"]["kol"]["removed"], ["dobar"])

    def test_ev_at_or_below_zero_follows_nobody(self):
        self.fill(self.LATE)
        out, logs = self.run_()
        g = out["types"]["kol"]["variants"]["strogo"]["noc"]["bruto"]
        self.assertGreaterEqual(g["n"], 30)
        self.assertLess(g["ev_net_pct"], 0)
        self.assertEqual(out["types"]["kol"]["now"]["strogo"], 1)              # the source qualifies on paper...
        self.assertFalse(out["gate"]["kol"]["on"])
        self.assertEqual(self.follows(), [])                                     # ... but nobody is followed
        self.assertTrue(any(ln.startswith("zadnjih 5: ne pratim: influenceri") and "≤ 0" in ln for ln in logs), logs)

    def test_too_few_trades_follow_nobody_and_the_owner_switch_overrides(self):
        self.fill(self.WIN, n=20)
        out, logs = self.run_()
        self.assertLess(out["types"]["kol"]["gate"]["n"], 30)
        self.assertFalse(out["gate"]["kol"]["on"])
        self.assertEqual(self.follows(), [])
        tcon = settings.connect(self.p["trade"])
        try:
            settings.set_flag(tcon, z.FLAG, "live", "Jure")
        finally:
            tcon.close()
        out, logs = self.run_()
        self.assertEqual([f["target"] for f in self.follows()], ["dobar"])
        self.assertTrue(out["follow"]["kol"]["manual"])

    def test_a_follow_the_owner_stopped_is_not_taken_back_and_manual_ones_stay(self):
        self.fill(self.WIN)
        con = lstore.connect(self.p["league"])
        try:
            own = lcopy.follow(con, settings.LEAGUE_USER, "kol", "netko", "", 25, 5)
        finally:
            con.close()
        self.run_()
        fid = next(f["id"] for f in self.follows() if f["target"] == "dobar")
        con = lstore.connect(self.p["league"])
        try:
            lcopy.unfollow(con, settings.LEAGUE_USER, fid)
        finally:
            con.close()
        out, _ = self.run_()
        self.assertEqual([f["id"] for f in self.follows()], [own])               # not re-added, the manual one stays
        self.assertEqual(out["follow"]["kol"]["skip"], 1)

    def test_bots_and_shills_are_never_selected(self):
        self.fill(self.WIN, handle="botko")
        self.kc.execute("INSERT INTO kols (handle, bot) VALUES ('botko', 1)")
        self.kc.commit()
        out, _ = self.run_()
        self.assertIn("error", out["types"]["kol"])
        self.assertEqual(self.follows(), [])

    def test_rug_archive_only_before_the_call_and_mcap(self):
        self.fill(self.WIN, n=8)
        hc = sqlite3.connect(self.p["hype"])
        hc.execute("CREATE TABLE rug_archive (token TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, last_ts INTEGER, "
                   "archived_ts INTEGER, klasa TEXT, kind TEXT, reason TEXT, peak_mcap REAL, last_mcap REAL, peak_liq REAL, "
                   "last_liq REAL, pad REAL, entry TEXT, removed TEXT)")
        hc.execute("CREATE TABLE rug_recovered (token TEXT PRIMARY KEY, recovered_ts INTEGER)")
        start = NOW - 25 * D
        hc.execute("INSERT INTO rug_archive (token, archived_ts, kind) VALUES (?,?,?)", (mint("dob", 6), start, "srusen"))
        hc.execute("INSERT INTO rug_archive (token, archived_ts, kind) VALUES (?,?,?)", (mint("dob", 7), NOW, "srusen"))
        hc.commit()
        hc.close()
        self.mc.execute("UPDATE call_path SET mcap_e = 20000 WHERE token = ?", (mint("dob", 5),))
        self.mc.commit()
        evs, cov = z.kol_events(self.p, NOW, 60, 0.6, 0.0005)
        why = {e["tok"]: e["why"] for e in evs}
        self.assertEqual(why[mint("dob", 5)], "MC ispod 30k")
        self.assertIn("rug arhiva", why[mint("dob", 6)])
        self.assertIsNone(why[mint("dob", 7)])                                # archived only after the call: a loss to take

    def test_mcp_tool(self):
        self.fill(self.WIN)
        out, _ = self.run_()
        z._write(self.p["out"], out)
        from ui import mcpapi
        with mock.patch.dict(os.environ, {"ZADNJIH5_OUT": self.p["out"]}):
            d, err = mcpapi._tool("get_last5", {"type": "kol", "top": 1})
            self.assertFalse(err)
            self.assertEqual(list(d["types"]), ["kol"])
            self.assertEqual(len(d["types"]["kol"]["top"]), 1)
            self.assertIn("gate", d)
            d, err = mcpapi._tool("get_last5", {"type": "x"})
            self.assertTrue(err)
        self.assertIn("get_last5", {t["name"] for t in mcpapi.TOOLS})


class LiveExit(DbBase):
    """14.11. review: a copy of a zadnjih 5 follow exits exactly as the walk-forward measured it."""

    def follow_now(self):
        self.fill(self.WIN)
        out, _ = self.run_()
        (f,) = self.follows()
        return out, f

    def copy_entry(self, f, switch=False):
        """One fresh call of the followed source through league/copy.run_once on the Autopilot account."""
        hc = sqlite3.connect(self.p["hype"])
        hc.executescript("CREATE TABLE IF NOT EXISTS chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, "
                         "sol REAL); CREATE TABLE IF NOT EXISTS kol_mentions (handle TEXT, ca TEXT, ts INTEGER);")
        hc.close()
        tok = mint("new", 1)
        now = int(__import__("time").time())
        con = lstore.connect(self.p["league"])
        try:
            con.execute("UPDATE follows SET created = ? WHERE id = ?", (now - 3600, f["id"]))
            con.commit()
            self.kc.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('nov', ?, ?, ?, 'call')",
                            (tok, f["target"], now - 20))
            self.kc.commit()
            if switch:
                tcon = settings.connect(self.p["trade"])
                try:
                    settings.set_flag(tcon, "pravi_novac_sve", "live", settings.owner())
                finally:
                    tcon.close()
            paths = {"kol": self.p["kol"], "hype": self.p["hype"], "tg": os.path.join(self.tmp, "nema-tg.db")}
            with mock.patch.object(lcopy, "_grace_at_entry", side_effect=AssertionError("grace")), \
                    mock.patch("sys.stdout", io.StringIO()):
                done = lcopy.run_once(con, lambda toks: {t: (2.0, 60_000, None, 2e6, "NOV") for t in toks}, now, paths)
            self.assertEqual(len(done), 1, done)
            t = dict(con.execute("SELECT * FROM trades WHERE token = ? AND status = 'open'", (tok,)).fetchone())
            return con, t, tok
        except Exception:
            con.close()
            raise

    def test_the_copy_gets_tp_10_the_models_stop_and_60_min(self):
        out, f = self.follow_now()
        con, t, _tok = self.copy_entry(f)
        try:
            a = json.loads(t["auto"])
            self.assertEqual((a["mode"], a["tp"], a["sl"]), ("tpsl", "+10%", "-60%"))
            self.assertAlmostEqual(a["tp_px"], t["entry_px"] * 1.10)               # from the entry price, as measured
            self.assertAlmostEqual(a["sl_px"], t["entry_px"] * (1 - out["assumptions"]["sl_pct"] / 100))
            self.assertEqual(a["until"], t["opened_ts"] + 3600)                     # the 60-min time exit
            self.assertNotIn("from_eff", a)
            self.assertNotIn("grace_until", a)
        finally:
            con.close()

    def test_under_the_switch_the_protective_stop_is_the_same_stop(self):
        _out, f = self.follow_now()
        con, t, tok = self.copy_entry(f, switch=True)
        try:
            from league import exitplan
            p = exitplan.active(con, tok)
            self.assertIsNotNone(p)
            self.assertAlmostEqual(p["plan"]["stop"]["v"], -60.0)                   # not the -30 % default
            self.assertAlmostEqual(p["state"]["stop_px"][settings.LEAGUE_USER], t["entry_px"] * 0.4)
            self.assertEqual(json.loads(t["auto"])["until"], t["opened_ts"] + 3600)  # the lot's TP / time keep running
        finally:
            con.close()

    def test_a_changed_default_stop_moves_the_model_and_the_follow_together(self):
        self.follow_now()
        tcon = settings.connect(self.p["trade"])
        try:
            settings.put(tcon, "sl_default", 30)
        finally:
            tcon.close()
        out, logs = self.run_()
        self.assertEqual(out["assumptions"]["sl_pct"], 30.0)
        (f,) = self.follows()
        self.assertEqual(json.loads(f["exit"])["sl"], "-30%")
        self.assertEqual(out["follow"]["kol"]["synced"], ["dobar"])
        self.assertTrue(any("izlaz usklađen" in ln for ln in logs))
        out, _ = self.run_()
        self.assertEqual(out["follow"]["kol"]["synced"], [])                       # nothing to sync any more

    def test_the_fast_path_leaves_these_follows_alone_and_the_page_shows_the_time(self):
        from fast import sources
        _out, f = self.follow_now()
        con = lstore.connect(self.p["league"])
        try:
            lcopy.follow(con, settings.LEAGUE_USER, "kol", "rucni", "", 25, 5, "tpsl", "20%", "")
        finally:
            con.close()
        got = sources.collect(league_db=self.p["league"], early_db=os.path.join(self.tmp, "nema-early.db"))
        self.assertIn("rucni", got)
        self.assertNotIn("dobar", got)
        self.assertIn("najdulje 60 min", lcopy.describe_exit(json.loads(f["exit"])))
        with self.assertRaises(ValueError):
            con = lstore.connect(self.p["league"])
            try:
                lcopy.follow(con, settings.LEAGUE_USER, "kol", "x", "", 25, 5, "tpsl", "10%", "", hold_s=10)
            finally:
                con.close()


class Wallets(DbBase):
    def test_wallet_buys_priced_from_prints(self):
        from live import store as live_store
        from wallets import store as wstore
        wc = wstore.connect(self.p["wallets"])
        hc = live_store.connect(self.p["hype"])
        start = NOW - 20 * D
        sol = 150.0
        for i in range(40):
            ts = start + i * 8 * 3600 + 30
            m = mint("wal", i, pump=True)
            wc.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", ("W" * 44, f"s{i}", ts, m, 1e6, -0.5, "buy"))
            px = 600 / 1e9   # 600 SOL market cap = $90k
            rows = []
            for k in range(0, 75):
                p = px * (1.0 if k < 2 else 1.14)
                rows.append((f"p{i}-{k}", m, "X" * 44, "buy", 0.1, 1.0, p, p * 1e9, "pump-amm", ts + 60 * k + 5, None))
            hc.executemany("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        wc.execute("INSERT INTO wallets (wallet, labels) VALUES (?, ?)", ("B" * 44, json.dumps(["bot"])))
        wc.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", ("B" * 44, "sb", start + 99, mint("wal", 0, True),
                                                                        1e6, -0.5, "buy"))
        wc.commit()
        wc.close()
        hc.close()
        evs, cov = z.wallet_events(self.p, NOW, 30, 0.6, 0.0005)
        self.assertEqual(cov["printovi"], 40)
        self.assertEqual(cov["izbačeni_novčanici"], 1)                          # a bot-labelled wallet: never in
        self.assertTrue(all(abs(e["gain"] - 0.14) < 1e-9 for e in evs))
        self.assertTrue(all(abs(e["mcap"] - 600 * sol) < 1 for e in evs))
        r = z.analyse(evs, "wallet", NOW, 0.6, span_days=30)
        s = r["variants"]["strogo"]["noc"]["bruto"]
        self.assertGreaterEqual(s["n"], 30)
        self.assertEqual(s["hit"], 1.0)
        self.assertEqual(r["now"]["strogo"], 1)

    def test_curve_prints_are_not_traded(self):
        from live import store as live_store
        from wallets import store as wstore
        wc = wstore.connect(self.p["wallets"])
        hc = live_store.connect(self.p["hype"])
        ts = NOW - D
        m = mint("cur", 1, pump=True)
        wc.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", ("W" * 44, "s1", ts, m, 1e6, -0.5, "buy"))
        hc.executemany("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       [(f"c{k}", m, "X" * 44, "buy", 0.1, 1.0, 3e-7, 300.0, "pump", ts + 60 * k, None) for k in range(70)])
        wc.commit()
        wc.close()
        hc.close()
        evs, cov = z.wallet_events(self.p, NOW, 30, 0.6, 0.0005)
        self.assertEqual(evs[0]["why"], "možda na pump.fun krivulji")
        self.assertEqual(cov["pravila"], {"možda na pump.fun krivulji": 1})


class Wiring(unittest.TestCase):
    def test_flag_is_an_owner_switch_off_by_default(self):
        self.assertIn(z.FLAG, settings.FLAGS)
        self.assertIn(z.FLAG, settings.OWNER_SWITCHES)
        self.assertIn(z.FLAG, settings.OWNER_SWITCH_NOTES)
        self.assertEqual(settings.FLAG_DEFAULTS.get(z.FLAG, "off"), "off")
        tmp = tempfile.mkdtemp()
        con = settings.connect(os.path.join(tmp, "trade.db"))
        try:
            self.assertEqual(settings.flag(z.FLAG, con=con), "off")
            self.assertIsNone(settings.live_refusal(con, z.FLAG))   # an owner switch: "uživo" needs no backtest
        finally:
            con.close()

    def test_start_sh_runs_it_after_a_start_and_nightly_under_the_heavy_lock(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn('sleep "${ZADNJIH5_FIRST_S:-300}"; python3 -m ops.heavy -m kol.zadnjih5 once', sh)
        self.assertIn("python3 -m ops.heavy --night -m kol.zadnjih5 night", sh)
        from ops import cpuguard
        self.assertEqual(cpuguard.classify(["python3", "-m", "kol.zadnjih5", "once"])[0], "zadnjih5")

    def test_once_skips_a_fresh_result_and_night_runs_once_a_day(self):
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "z.json")
        now = int(__import__("time").time())
        z._write(out, {"version": z.VERSION, "ts": now - 60, "night_day": z.day_of(now)})
        with mock.patch.dict(os.environ, {"ZADNJIH5_OUT": out}), mock.patch.object(z, "run") as run, \
                mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(z.main(["once"]), 0)
            self.assertEqual(z.main(["night"]), 0)
            run.assert_not_called()

    def test_log_lines_and_mcp_error_before_the_first_run(self):
        self.assertIn("error", z.mcp(path=os.path.join(tempfile.mkdtemp(), "nema.json")))
        with open(os.path.join(ROOT, "kol", "zadnjih5.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertTrue(re.search(r'say\(f"\{PREFIX\}ne pratim: ', src))


if __name__ == "__main__":
    unittest.main()
