"""18.11. (vlasnik: "1000 demo tradeova treba raditi dnevno da bi program mogao naučiti što prolazi, a što ne"),
veliki/sjena.py, offline:

  - an entry: one shadow per exit profile per token, with what was known before it; the day's and the rounds' caps
  - an exit: the level crossed on one quote, filled at the NEXT quote (a spike books nothing it could not trade);
    the time limit; the net return after the round trip; open rows survive a restart
  - the table: grouped by a feature and the profile, the interval over token-days; the hour's line
  - live: every candidate of the bar goes into the book whatever the rule decides; no account, no league trade,
    nothing the rule or the real-money proof reads; VEL_SJENA=0

    python3 -m unittest tests.test_sjena_offline
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import LU, PU, tok  # noqa: E402
import tests.test_veliki_intra_offline as _it  # noqa: E402  (the module, so its own tests are not collected here)
from veliki import istrazivac, live, sjena  # noqa: E402

M15, calm15 = _it.M15, _it.calm15
Z = {"ok": True, "lo": 0.9e-4, "hi": 1.2e-4, "width": 0.33}


class _Base(_it.Live):
    """The fixtures of the intraday live tests without their tests."""


for _n in [n for n in dir(_it.Live) if n.startswith("test_")]:
    setattr(_Base, _n, None)


class Pure(unittest.TestCase):
    def test_band_and_why(self):
        self.assertEqual(sjena.band_of(0.95e-4, Z)[0], "dno")
        self.assertEqual(sjena.band_of(1.0e-4, Z)[0], "donja")
        self.assertEqual(sjena.band_of(1.1e-4, Z)[0], "sredina")
        self.assertEqual(sjena.band_of(1.19e-4, Z)[0], "vrh")
        self.assertEqual(sjena.band_of(0.8e-4, Z)[0], "ispod")
        self.assertEqual(sjena.band_of(1.3e-4, Z)[0], "iznad")
        self.assertEqual(sjena.band_of(1.0e-4, {"ok": False, "why": "premalo satnih svijeća"}), (None, None))
        self.assertEqual(sjena.band_of(0, Z), (None, None))
        self.assertEqual(sjena.why_class("raspon preuzak (4.1%)"), "uzak")
        self.assertEqual(sjena.why_class("trend, ne raspon (ER 0.71)"), "trend")
        self.assertIsNone(sjena.why_class(None))


class Book(_Base):
    def setUp(self):
        super().setUp()
        sjena.reset()
        self.addCleanup(sjena.reset)
        live.ensure(self.lg)
        self.q = (1.0e-4, 2_000_000.0, "https://dexscreener.com/solana/raydium", 5e7, "MID")

    def open(self, t=None, px=None, token=None, **kw):
        q = (px or self.q[0],) + self.q[1:]
        return sjena.consider(self.lg, token or tok(100), q, t or self.now, kw.pop("z", Z), calm15(t or self.now, q[0]),
                              kw.pop("prow", None), {"state": "normalno"}, None, 150.0)

    def rows(self, where="1=1"):
        cols = ("token", "profil", "status", "band", "calm", "zone_ok", "btc", "grok", "dip", "oprez", "entry_px", "tp_px",
                "stop_px", "rt", "exit_px", "reason", "ret")
        return [dict(zip(cols, r)) for r in self.lg.execute(
            f"SELECT {', '.join(cols)} FROM veliki_sjena WHERE {where} ORDER BY id")]

    def test_one_shadow_per_profile_with_what_was_known(self):
        prow = {"grok": {"verdict": "Kupi", "confidence": 0.7, "ts": self.now - 60}, "dip": {"kind": "trzisni"},
                "risk": "top 10 holdera 60 %"}
        self.assertEqual(self.open(prow=prow), 5)
        rows = self.rows()
        self.assertEqual([r["profil"] for r in rows], list(sjena.PROFILES))
        r = rows[3]                                                      # pravilo: +10 % net, stop -20 %
        self.assertEqual((r["band"], r["calm"], r["zone_ok"], r["btc"], r["grok"], r["dip"], r["oprez"]),
                         ("donja", 1, 1, "normalno", "kupi", "trzisni", 1))
        self.assertAlmostEqual(r["stop_px"] / r["entry_px"], 0.80, places=6)
        self.assertGreater(r["tp_px"] / r["entry_px"], 1.10)             # the target is net of the round trip
        self.assertGreater(r["rt"], 0.005)
        self.assertEqual(self.open(), 0)                                 # every profile already holds the token
        self.assertEqual(self.open(token=tok(101)), 5)                   # another token: its own five
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)      # no league trade
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades").fetchone()[0], 0)

    def test_no_zone_no_liquidity_and_the_caps(self):
        self.assertEqual(self.open(z={"ok": False, "why": "premalo satnih svijeća"}), 0)
        self.assertEqual(sjena.consider(self.lg, tok(100), (1.0e-4, 0, "u", 5e7), self.now, Z, [], None, None, None, 150.0), 0)
        with mock.patch.object(sjena, "PER_DAY", 7):
            self.assertEqual(self.open(), 5)
            self.assertEqual(self.open(token=tok(101)), 5)               # the cap is checked before a token's batch
            self.assertEqual(self.open(token=tok(102)), 0)
        with mock.patch.object(sjena, "MAX_OPEN", 10):
            self.assertEqual(self.open(token=tok(103)), 0)

    def test_an_invalid_zone_is_still_recorded_with_its_reason(self):
        self.open(z={**Z, "ok": False, "why": "raspon preuzak (4.1%)"})
        r = self.lg.execute("SELECT zone_ok, zone_why, band FROM veliki_sjena LIMIT 1").fetchone()
        self.assertEqual(tuple(r), (0, "uzak", "donja"))

    def test_a_crossed_level_fills_at_the_next_quote(self):
        self.open()
        t = self.now
        self.assertEqual(sjena.mark(self.lg, {tok(100): (0.955e-4,)}, t + 30), 0)       # -4.5 %: the scalp's stop is armed
        self.assertEqual([r["status"] for r in self.rows()], ["open"] * 5)
        self.assertEqual(sjena.mark(self.lg, {tok(100): (0.99e-4,)}, t + 32), 0)        # 2 s later: too soon to be a fill
        self.assertEqual(sjena.mark(self.lg, {tok(100): (0.97e-4,)}, t + 60), 1)        # filled at the next quote, not the level
        r = self.rows("profil='skalp'")[0]
        self.assertEqual((r["status"], r["reason"]), ("closed", "stop"))
        self.assertAlmostEqual(r["exit_px"], 0.97e-4)
        self.assertAlmostEqual(r["ret"], 0.97 * (1 - r["rt"]) - 1, places=9)
        self.assertEqual(sjena.mark(self.lg, {tok(100): (1.10e-4,)}, t + 90), 0)        # a spike: arms the +6 % net target
        self.assertGreaterEqual(self.rows("profil='kratko'")[0]["rt"], 0.03)            # (the real cost, never under 3 %)
        self.assertEqual(sjena.mark(self.lg, {tok(100): (1.00e-4,)}, t + 120), 1)       # back at the entry: booked there
        r = self.rows("profil='kratko'")[0]
        self.assertEqual(r["reason"], "tp")
        self.assertLess(r["ret"], 0)                                     # the spike was not a win it could have sold
        self.assertEqual(self.open(t=t + 900), 2)                        # the two free profiles open again next bar

    def test_time_limit_and_restart(self):
        self.open()
        sjena.reset()                                                    # a deploy: memory gone, the rows are not
        t = self.now + sjena.MAX_H * 3600 + 5
        self.assertEqual(sjena.mark(self.lg, {tok(100): (1.01e-4,)}, t), 5)
        self.assertEqual({r["reason"] for r in self.rows()}, {"vrijeme"})
        self.assertEqual(self.open(t=t + 900), 5)
        sjena.cleanup(self.lg, t + 900 + (sjena.MAX_H + 25) * 3600)      # nobody quotes the token any more
        got = self.rows("reason='bez_cijene'")
        self.assertEqual(len(got), 5)
        self.assertTrue(all(r["ret"] is None for r in got))

    def test_table_counts_token_days_and_the_line_waits_for_enough(self):
        self.assertIn("premalo podataka", sjena.line(self.lg, self.now))
        day = int(self.now) // 86400 * 86400
        n = 0
        for i in range(24):                                              # 24 tokens, two shadows each on the same day
            for ret in (0.03, 0.01):
                self.lg.execute("INSERT INTO veliki_sjena (token, opened_ts, profil, band, calm, zone_ok, status, closed_ts, "
                                "ret, rt, entry_px) VALUES (?,?,?,?,?,?,'closed',?,?,0.02,1)",
                                (tok(200 + i), day + 60 + n, "skalp", "dno", 1, 1, day + 600 + n, ret))
                self.lg.execute("INSERT INTO veliki_sjena (token, opened_ts, profil, band, calm, zone_ok, status, closed_ts, "
                                "ret, rt, entry_px) VALUES (?,?,?,?,?,?,'closed',?,?,0.02,1)",
                                (tok(200 + i), day + 60 + n, "siroko", "vrh", 0, 1, day + 600 + n, -0.05 - i * 0.001))
                n += 1
        self.lg.commit()
        t = day + 3600
        rows = {(r["group"], r["profil"]): r for r in sjena.table(self.lg, t)}
        a = rows[("dno", "skalp")]
        self.assertEqual((a["n"], a["clusters"]), (48, 24))              # 48 trades are 24 token-days
        self.assertAlmostEqual(a["ev"], 0.02)
        self.assertEqual(a["hit"], 1.0)
        self.assertAlmostEqual(a["lo"], 0.02, places=6)                  # every token-day's mean is the same
        self.assertLess(rows[("vrh", "siroko")]["hi"], 0)
        self.assertEqual({r["group"] for r in sjena.table(self.lg, t, by="calm")}, {"smirilo se", "još pada"})
        self.assertEqual({r["profil"] for r in sjena.table(self.lg, t, profil="skalp")}, {"skalp"})
        with self.assertRaises(ValueError):
            sjena.table(self.lg, t, by="nema")
        line = sjena.line(self.lg, t)
        self.assertIn("2 ćelija s dovoljno podataka, s donjom granicom iznad nule: 1", line)
        self.assertIn("najbolja dno × skalp: n=48 (24 token-dana), prosjek +2.0%, pogodak 100%", line)
        self.assertIn("najgora vrh × siroko", line)

    def test_mcp_and_registry(self):
        from league import store as lstore
        from stanja import provjera, registar
        from ui import mcpapi
        self.open()
        self.lg.commit()
        with mock.patch.object(lstore, "connect", lambda *a, **k: _NoClose(self.lg)):
            d, err = mcpapi._tool("get_shadow_book", {"by": "band", "days": 3})
            bad, err2 = mcpapi._tool("get_shadow_book", {"by": "nema"})
        self.assertFalse(err)
        self.assertEqual(d["today"]["opened"], 5)
        self.assertEqual(d["profiles"]["pravilo"], {"target_net_pct": 10.0, "stop_pct": 20.0})
        self.assertTrue(err2)
        self.assertIn("nepoznata značajka", bad["error"])
        tools = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(tools["get_shadow_book"]["annotations"]["readOnlyHint"])
        self.assertIn("shadow_trade", registar.BY_KEY)
        self.assertEqual(provjera.drift(registar.MACHINES), [])
        self.assertEqual(registar.exit_key("sjena", "vrijeme"), "time")


class _NoClose:
    def __init__(self, con):
        self._c = con

    def __getattr__(self, k):
        return getattr(self._c, k)

    def close(self):
        pass


class LiveBook(_Base):
    def setUp(self):
        super().setUp()
        sjena.reset()
        self.addCleanup(sjena.reset)
        self.sig.stop()
        self.px = 1.0e-4
        p = mock.patch.object(live, "bars_intra", lambda t, now: (calm15(now, self.px), []))
        p.start()
        self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")

    def tick(self, toks=(100,), now=None, px=None):
        want = {tok(i) for i in toks}
        return live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in want], px or self.px), now=now or self.now,
                         force=True)

    def n(self, where="1=1"):
        return self.lg.execute(f"SELECT COUNT(*) FROM veliki_sjena WHERE {where}").fetchone()[0]

    def test_every_candidate_of_the_bar_goes_into_the_book(self):
        with self._prio("top 10 holdera 60 %"):                         # the rule (and the explorer) refuse: oprez
            self.tick((31, 100))
        self.assertEqual(self.n(), 10)                                   # two tokens x five profiles all the same
        self.assertEqual(self.n("oprez=1"), 10)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades").fetchone()[0], 0)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)
        self.tick((31, 100), now=self.now + 30)                          # the same 15m bar: nothing new
        self.assertEqual(self.n(), 10)

    def test_the_rule_and_the_explorer_trade_as_before_next_to_it(self):
        out = self.tick(px=0.95e-4)                                      # the rule's own entry
        self.assertEqual([r[0] for r in self.lg.execute("SELECT user FROM veliki_trades")], [PU], out)
        self.assertEqual(self.n(), 5)
        self.assertEqual(live.demo_stats(self.lg)["n"], 0)
        users = {r[0] for r in self.lg.execute("SELECT DISTINCT user FROM trades")}
        self.assertEqual(users, {PU})
        self.assertNotIn(LU, users)
        self.assertNotIn(istrazivac.USER, users)

    def test_exits_run_on_the_ticks_quotes_and_the_hour_line(self):
        self.tick()
        self.tick(now=self.now + 30, px=0.95e-4)                         # -5 %: arms the scalp's stop
        self.tick(now=self.now + 60, px=0.955e-4)
        self.assertEqual(self.n("status='closed' AND profil='skalp' AND reason='stop'"), 1)
        live._ST["rep_h"] = 0
        out = self.tick(now=self.now + 90)
        line = next(x for x in out if x.startswith("veliki sjena (zamišljeni tradeovi"))
        self.assertIn("danas otvoreno 5 u 1 tokena, zatvoreno 1, sada otvorenih 4", line)

    def test_switched_off_and_an_error_never_costs_the_pass(self):
        with mock.patch.dict(os.environ, {"VEL_SJENA": "0"}):
            self.tick()
            self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='veliki_sjena'").fetchone()[0], 0)
            self.assertIn("isključena", sjena.line(self.lg, self.now))
        live._ST["bar15"] = {}
        with mock.patch.object(sjena, "band_of", side_effect=RuntimeError("x")):
            out = self.tick(toks=(101,), now=self.now + 31, px=0.95e-4)
        self.assertIn(PU, {r[0] for r in self.lg.execute("SELECT user FROM veliki_trades")}, out)


if __name__ == "__main__":
    unittest.main()
