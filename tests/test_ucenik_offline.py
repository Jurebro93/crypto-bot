"""18.11. (vlasnik: "želim da demo što prije bude profitabilan"; then "Odmah želim da pravi novac krene raditi"),
veliki/ucenik.py, offline (no network; the real buy and sell are stubs):

  - the demo account "učenik": no model or a stale one = no entry and a line that says so; an entry only when the
    stored model predicts the best profile above +1 % net; the chosen profile's levels are the shadow book's for the
    same candidate; one position a token, MAX_OPEN, the cooldown; exits at the target / the stop / the time limit on
    the NEXT quote with the real cost booked; the day rule's exits never touch it; never the rule's account, never
    real money while the owner's switch is off; kept out of the rule's reports; VEL_UCENIK=0; the hour's line and the
    verdict thresholds
  - real money (owner switch pravi_novac_nauceno): off = the real buy is never called (three places refuse it);
    on = one real buy per entry at exactly 0.1 SOL through the mirror and executor.buy, only past every gate of a
    real midcap entry; a refusal is logged, stored and not retried; a buy the executor refuses closes the twin
    without a result; exits at the same levels, after a restart too, plus a rug; the switch is the owner's only
  - the owner's order of 18.11. (once): pravi_novac_nauceno on, pravi_novac_veliki off, nothing else; the day rule's
    open real position keeps its exits; a later tap is never overwritten
  - the real-money result by strategy since 15.11. (trade/executor.strategy_result)

    python3 -m unittest tests.test_ucenik_offline
"""
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_pravi_novac_sve_offline import LU, PU, tok  # noqa: E402
import tests.test_veliki_intra_offline as _it  # noqa: E402  (the module, so its own tests are not collected here)
from trade import executor, jupiter, settings  # noqa: E402
from veliki import intra, live, nauceno, rule, sjena, ucenik  # noqa: E402

M15, calm15 = _it.M15, _it.calm15
XU = ucenik.USER
H, D = 3600, 86400
SW = settings.NAUCENO_SWITCH


class _Base(_it.Live):
    """The fixtures of the intraday live tests without their tests."""


for _n in [n for n in dir(_it.Live) if n.startswith("test_")]:
    setattr(_Base, _n, None)


class Fix(_Base):
    def setUp(self):
        super().setUp()
        self.sig.stop()                                                   # the real intra.signal decides
        self.px = 1.0e-4                                                  # 33 % of the zone: the day rule refuses
        for p in (mock.patch.object(live, "bars_intra", lambda t, now: (calm15(now, self.px), [])),
                  mock.patch.dict(os.environ, {"VEL_ISTRAZIVAC": "0"})):
            p.start()
            self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")
        sjena.reset()
        self.addCleanup(sjena.reset)
        nauceno._MODEL.clear()
        self.addCleanup(nauceno._MODEL.clear)
        ucenik._PEND.clear()
        ucenik._BOUGHT.clear()
        self.ndb = os.path.join(self.tmp.name, "nauceno.db")              # next to midcap.db: nauceno.db_path()

    def model(self, skalp=0.03, age_h=1.0, **other):
        """A stored model whose only knowledge is each profile's mean: skalp predicts `skalp`, the rest a loss."""
        m = nauceno.Model()
        base = {"skalp": skalp, "kratko": -0.01, "uski": -0.02, "pravilo": -0.03, "siroko": -0.04, **other}
        m.tot = {p: [1000, 1000 * v] for p, v in base.items()}
        con = nauceno.connect(self.ndb)
        con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)",
                    (nauceno.KV_MODEL, json.dumps(m.dump(int(self.now - age_h * H), 5000, 30))))
        con.commit()
        con.close()
        nauceno._MODEL.clear()

    def again(self, wipe=False):
        """The same bar may be offered once more (a test seam: the bar, the universe poll and the hourly lines)."""
        live._ST["bar15"], live._ST["univ_q"], live._ST["said"] = {}, 0, {}
        if wipe:
            live.ensure(self.lg)
            for t in ("veliki_trades", "trades", "veliki_ucenik"):
                if self.lg.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
                    self.lg.execute(f"DELETE FROM {t}")
            self.lg.commit()

    def tick(self, toks=(100,), now=None, px=None):
        want = {tok(i) for i in toks}
        return live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in want], px or self.px), now=now or self.now,
                         force=True)

    def rows(self, user=XU):
        cur = self.lg.execute("SELECT * FROM veliki_trades WHERE user=? ORDER BY id", (user,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def n_real_path(self):
        """Everything a real buy would leave behind: league trades of the real / the rule's account, trade.db rows."""
        return (self.lg.execute("SELECT COUNT(*) FROM trades WHERE user IN (?, ?)", (LU, PU)).fetchone()[0],
                self.con.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
                self.con.execute("SELECT COUNT(*) FROM orders").fetchone()[0], len(self.swaps))


class Demo(Fix):
    def test_no_model_or_a_stale_one_is_no_entry_and_the_line_says_so(self):
        out = self.tick()
        self.assertEqual(self.rows(), [], out)
        self.assertIn("BEZ NOVIH ULAZA: model učenja još nije spremljen", ucenik.line(self.lg, self.now))
        self.model(age_h=25)
        self.again()
        self.tick()
        self.assertEqual(self.rows(), [])
        ln = ucenik.line(self.lg, self.now)
        self.assertIn("BEZ NOVIH ULAZA: model učenja je stariji od 24 h (zadnji ", ln)
        self.assertEqual(ln.count("BEZ NOVIH ULAZA"), 1)

    def test_entry_only_above_the_threshold(self):
        self.model(skalp=ucenik.THR)                                      # exactly +1 %: not above it
        self.tick()
        self.assertEqual(self.rows(), [])
        self.model(skalp=0.0101)
        self.again()
        out = self.tick()
        r = self.rows()
        self.assertEqual([(x["token"], x["varijanta"], x["kind"], x["size_sol"], x["status"]) for x in r],
                         [(tok(100), "nauceno:skalp", "intra", live.INTRA_DEMO_SOL, "open")], out)
        self.assertTrue(any(x.startswith("veliki naučeno ulaz [skalp] MID 0.1 SOL") for x in out), out)
        self.assertNotIn("BEZ NOVIH ULAZA", ucenik.line(self.lg, self.now))
        pred, prof, facts, mts = self.lg.execute("SELECT pred, profil, facts, model_ts FROM veliki_ucenik WHERE id=?",
                                                 (r[0]["id"],)).fetchone()
        self.assertAlmostEqual(pred, 0.0101)                               # stored, to split the result by band later
        self.assertEqual((prof, mts), ("skalp", int(self.now - H)))
        self.assertEqual(set(json.loads(facts)), set(nauceno.FEATS))

    def test_the_best_profile_and_its_levels_are_the_shadow_books(self):
        self.model(skalp=0.02, siroko=0.05)                               # the wide exit predicts more: it is taken
        self.tick()
        r = self.rows()[0]
        self.assertEqual(r["varijanta"], "nauceno:siroko")
        tp, stop, rt, entry = self.lg.execute("SELECT tp_px, stop_px, rt, entry_px FROM veliki_sjena WHERE token=? AND "
                                              "profil='siroko'", (tok(100),)).fetchone()
        self.assertEqual((r["tp_px"], r["stop_px"], r["rt"], r["entry_px"]), (tp, stop, rt, entry))
        self.assertGreaterEqual(r["rt"], 0.03)                            # the real round trip, never under the floor
        self.assertAlmostEqual(r["stop_px"] / r["entry_px"], 0.80)
        self.assertAlmostEqual(rule.net_ret(r["entry_px"], r["tp_px"], r["rt"]), 0.20)   # +20 % NET at the target
        self.assertEqual(r["time_h"], sjena.MAX_H)

    def test_one_position_a_token_max_open_and_the_cooldown(self):
        self.model()
        with mock.patch.object(ucenik, "MAX_OPEN", 1):
            self.tick((31, 100))
            self.assertEqual(len(self.rows()), 1)                         # the second token: the account is full
        first = self.rows()[0]
        self.tick((31, 100), now=self.now + M15 + 5)                      # the next bar: the held token is not doubled
        self.assertEqual(sorted(x["token"] for x in self.rows()), sorted({first["token"], tok(31), tok(100)} & {
            tok(31), tok(100)}))
        self.assertEqual(len(self.rows()), 2)
        rid = first["id"]
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=-0.07, pnl_usd=-1.0, reason='stop' "
                        "WHERE id=?", (int(self.now + M15 + 60), rid))
        self.lg.execute("UPDATE trades SET status='closed' WHERE id=?", (first["trade_id"],))
        self.lg.commit()
        self.tick((31, 100), now=self.now + 2 * M15 + 5)                  # 15 min after the exit: still cooling down
        self.assertEqual(len(self.rows()), 2)
        self.tick((31, 100), now=self.now + M15 + 60 + intra.COOLDOWN_S + M15)
        self.assertEqual(len(self.rows()), 3)

    def exit_at(self, px, t=30):
        self.model()
        self.tick()
        r = self.rows()[0]
        out = self.tick(now=self.now + t, px=px(r))                       # the level is crossed: armed, nothing sold
        self.assertEqual(self.rows()[0]["status"], "open", out)
        return r

    def test_target_is_filled_at_the_next_quote_with_the_real_cost(self):
        r = self.exit_at(lambda r: r["tp_px"] * 1.02)
        out = self.tick(now=self.now + 60, px=r["tp_px"] * 1.01)
        c = self.rows()[0]
        self.assertEqual((c["status"], c["reason"]), ("closed", "tp"), out)
        self.assertAlmostEqual(c["exit_px"], r["tp_px"] * 1.01)           # the fill quote, not the one that crossed
        self.assertAlmostEqual(c["ret"], c["exit_px"] / c["entry_px"] * (1 - c["rt"]) - 1)
        self.assertGreater(c["ret"], 0.03)
        self.assertAlmostEqual(c["pnl_usd"], c["ret"] * c["size_usd"])
        self.assertTrue(any(x.startswith("veliki naučeno izlaz [skalp] MID: cilj") for x in out), out)
        self.assertEqual(self.lg.execute("SELECT status FROM trades WHERE id=?", (c["trade_id"],)).fetchone()[0], "closed")

    def test_a_spike_that_comes_back_books_what_the_next_quote_pays(self):
        r = self.exit_at(lambda r: r["tp_px"] * 1.3)
        self.tick(now=self.now + 60, px=r["entry_px"])                     # the next quote is back at the entry
        c = self.rows()[0]
        self.assertEqual((c["status"], c["reason"]), ("closed", "tp"))
        self.assertAlmostEqual(c["ret"], -c["rt"])                         # the cost, not the wick

    def test_stop_and_the_days_rule_exits_never_touch_it(self):
        self.model(skalp=0.0, siroko=0.05)                                # +20 % / -20 %: room for the day rule's moves
        self.tick()
        r = self.rows()[0]
        # +5 % net held for a minute would move the day rule's stop to the entry; here nothing moves
        up = r["entry_px"] * 1.10
        self.assertGreater(up, r["be_px"] * 1.05)
        for t in (20, 60, 100):
            self.tick(now=self.now + t, px=up)
        self.assertEqual((self.rows()[0]["stop_px"], self.rows()[0]["status"]), (r["stop_px"], "open"))
        self.tick(now=self.now + 130, px=r["entry_px"] * 1.01)            # back under "break-even": still open
        self.tick(now=self.now + 150, px=r["entry_px"] * 1.01)
        self.assertEqual(self.rows()[0]["status"], "open")
        self.tick(now=self.now + 180, px=r["stop_px"] * 0.99)
        out = self.tick(now=self.now + 210, px=r["stop_px"] * 0.97)
        c = self.rows()[0]
        self.assertEqual((c["status"], c["reason"]), ("closed", "stop"), out)
        self.assertAlmostEqual(c["ret"], 0.80 * 0.97 * (1 - c["rt"]) - 1)

    def test_time_limit(self):
        self.model()
        self.tick()
        self.tick(now=self.now + sjena.MAX_H * H - 60)
        self.assertEqual(self.rows()[0]["status"], "open")
        out = self.tick(now=self.now + sjena.MAX_H * H + 5)
        c = self.rows()[0]
        self.assertEqual((c["status"], c["reason"]), ("closed", "time"), out)
        self.assertAlmostEqual(c["ret"], -c["rt"])

    def test_levels_are_in_the_row_so_a_restart_loses_nothing(self):
        r = self.exit_at(lambda r: r["tp_px"] * 1.02)
        ucenik._PEND.clear()                                              # the process restarted: the armed exit is gone
        live._ST["q"] = {}
        self.tick(now=self.now + 60, px=r["tp_px"] * 1.02)                # the next quote arms it again
        out = self.tick(now=self.now + 90, px=r["tp_px"] * 1.02)
        self.assertEqual(self.rows()[0]["reason"], "tp", out)

    def test_never_the_rules_account_never_real_money(self):
        self.model()
        from veliki import gate
        with mock.patch.object(gate, "real_refusal", lambda *a, **k: "prekidač pravi_novac_veliki je isključen"), \
                self._prio():
            out = self.tick((31, 100))
        self.assertEqual({r["token"] for r in self.rows()}, {tok(31), tok(100)}, out)
        self.assertEqual({r[0] for r in self.lg.execute("SELECT DISTINCT user FROM veliki_trades")}, {XU})
        self.mirror()                                                     # run_trade's pass: nothing of ours to mirror
        self.assertEqual(self.n_real_path(), (0, 0, 0, 0))
        self.assertFalse(any("PRAVI NOVAC" in x for x in out), out)

    def test_the_rule_may_hold_the_same_token_on_its_own_account(self):
        self.model()
        self.px = 0.95e-4                                                 # the bottom 25 %, calm: the rule enters too
        out = self.tick()
        self.assertEqual({(r[0], r[1]) for r in self.lg.execute("SELECT user, varijanta FROM veliki_trades")},
                         {(PU, None), (XU, "nauceno:skalp")}, out)
        rid = self.rows()[0]["id"]                                        # the učenik's exit does not cool the rule down
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=0.03, pnl_usd=0.4 WHERE id=?",
                        (int(self.now + 30), rid))
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=0.1, pnl_usd=1.0 WHERE user=?",
                        (int(self.now - 2 * H), PU))
        self.lg.execute("UPDATE trades SET status='closed'")
        self.lg.commit()
        self.tick(now=self.now + M15 + 5)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=?", (PU,)).fetchone()[0], 2)

    def test_kept_out_of_the_rules_reports_and_the_hour_line(self):
        from report import midcap as rmid
        self.model()
        self.tick()
        self.lg.execute("UPDATE veliki_trades SET status='closed', closed_ts=?, ret=0.031, pnl_usd=0.47, reason='tp' "
                        "WHERE user=?", (int(self.now + 60), XU))
        self.lg.commit()
        self.assertEqual(live.demo_stats(self.lg)["n"], 0)                # gate.demo_proof reads PAPER_USER only
        self.assertEqual(rmid.vrows(self.lg, closed_only=True), [])
        self.assertEqual(rmid.vrows(self.lg, since=0), [])
        self.assertIn("otvoreno 0 danas", live.report_line(self.lg, self.now + 120))
        ln = ucenik.line(self.lg, self.now + 120)
        self.assertEqual(ln, "veliki naučeno (demo): pravilo od 18.11.: ulaz samo uz prognozu iznad +1 %; otvoreno 0; "
                             "zatvoreno 1 (1 token-dana), prosjek po token-danu +3.1%, pogodak 100%, zbroj +0.47 $; "
                             "presuda nakon 21 dana ili 60 token-dana: još se mjeri")
        live._ST["rep_h"] = 0
        out = self.tick(now=self.now + 130)
        self.assertEqual(sum(1 for x in out if x.startswith("veliki naučeno (demo): pravilo od 18.11.")), 1, out)

    def test_switched_off_by_env(self):
        self.model()
        with mock.patch.dict(os.environ, {"VEL_UCENIK": "0"}):
            self.tick()
            self.assertEqual(self.rows(), [])
            self.assertEqual(ucenik.line(self.lg, self.now), "veliki naučeno (demo): isključen (VEL_UCENIK=0)")

    def test_an_error_never_costs_the_rules_pass(self):
        self.model()
        self.px = 0.95e-4
        with mock.patch.object(nauceno, "predict_best", side_effect=RuntimeError("x")):
            out = self.tick()
        self.assertEqual([r[0] for r in self.lg.execute("SELECT user FROM veliki_trades")], [PU], out)
        self.assertTrue(any("veliki naučeno: ulaz nije uspio (RuntimeError" in x for x in out), out)

    def test_mcp_block(self):
        self.model()
        self.tick()
        d = sjena.mcp({})["learned"]["demo"]
        self.assertEqual((d["account"], d["threshold"], d["open"], d["verdict"], d["model_ok"]),
                         (XU, 0.01, 1, "mjeri", True))
        self.assertEqual((d["real_money"]["switch"], d["real_money"]["on"]), ("pravi_novac_nauceno", False))
        self.assertTrue(d["line"].startswith("veliki naučeno (demo): pravilo od 18.11."))


class Verdict(Fix):
    def closed(self, n_tokens, days, ret, spread=0.0, t0=None):
        """n_tokens x days closed rows of the account, one a token-day; ret +- spread."""
        live.ensure(self.lg)
        t0 = t0 if t0 is not None else int(self.now) - days * D
        for d in range(days):
            for k in range(n_tokens):
                x = ret + (spread if (k + d) % 2 else -spread)
                self.lg.execute("INSERT INTO veliki_trades (user, token, opened_ts, closed_ts, status, ret, pnl_usd, "
                                "varijanta, kind) VALUES (?,?,?,?,?,?,?,?,?)",
                                (XU, f"T{k}", t0 + d * D + 600, t0 + d * D + 900, "closed", x, x * 15.0, "nauceno:skalp",
                                 "intra"))
        self.lg.commit()

    def v(self, now=None):
        s = ucenik.stats(self.lg, now or self.now)
        return s["verdict"], s

    def test_before_both_thresholds_it_only_measures(self):
        self.closed(5, 10, 0.05, 0.01)                                    # 50 token-days in 10 days, a clear plus
        verdict, s = self.v()
        self.assertEqual((verdict, s["closed"]["clusters"]), ("mjeri", 50))
        self.assertGreater(s["closed"]["lo"], 0)
        self.assertIn("presuda nakon 21 dana ili 60 token-dana: još se mjeri", ucenik.line(self.lg, self.now))

    def test_sixty_token_days_decide(self):
        self.closed(6, 10, 0.05, 0.01)                                    # 60 token-days
        self.assertEqual(self.v()[0], "kandidat")
        ln = ucenik.line(self.lg, self.now)
        self.assertIn("zatvoreno 60 (60 token-dana), prosjek po token-danu +5.0%, raspon 90 % [+4.8%; +5.2%], pogodak "
                      "100%, zbroj +45.00 $; presuda nakon 21 dana ili 60 token-dana: KANDIDAT (donja granica iznad nule)",
                      ln)

    def test_no_plus_and_an_interval_across_zero(self):
        self.closed(6, 10, -0.02, 0.01)
        self.assertEqual(self.v()[0], "nema_plusa")
        self.lg.execute("DELETE FROM veliki_trades")
        self.closed(6, 10, 0.002, 0.05)                                   # a mean above zero, the low end under it
        verdict, s = self.v()
        self.assertEqual(verdict, "nema_plusa")
        self.assertGreater(s["closed"]["ev"], 0)
        self.assertLess(s["closed"]["lo"], 0)
        self.assertIn("presuda nakon 21 dana ili 60 token-dana: nema plusa", ucenik.line(self.lg, self.now))

    def test_twenty_one_days_decide_with_fewer_token_days(self):
        self.closed(2, 5, 0.05, 0.01, t0=int(self.now) - 21 * D - 700)    # 10 token-days, the first entry 21 d ago
        self.assertEqual(self.v()[0], "kandidat")
        self.assertEqual(self.v(now=self.now - D)[0], "mjeri")            # a day earlier: not yet

    def test_token_days_not_trades_and_the_bands(self):
        self.closed(1, 1, 0.05)
        for i in range(3):                                                # three more trades of the same token-day
            self.lg.execute("INSERT INTO veliki_trades (user, token, opened_ts, closed_ts, status, ret, pnl_usd, "
                            "varijanta) VALUES (?,?,?,?,?,?,?,?)", (XU, "T0", int(self.now) - D + 700 + i, int(self.now),
                                                                    "closed", 0.01, 0.15, "nauceno:kratko"))
        self.lg.execute(ucenik.SCHEMA)
        ids = [r[0] for r in self.lg.execute("SELECT id FROM veliki_trades ORDER BY id")]
        for rid, pred in zip(ids, (0.015, 0.025, 0.035, 0.05)):
            self.lg.execute("INSERT INTO veliki_ucenik (id, pred) VALUES (?, ?)", (rid, pred))
        self.lg.commit()
        s = ucenik.stats(self.lg, self.now)
        self.assertEqual((s["closed"]["n"], s["closed"]["clusters"]), (4, 1))
        self.assertIsNone(s["closed"]["lo"])                              # one token-day: no interval
        self.assertEqual({k: v["n"] for k, v in s["by_profile"].items()}, {"skalp": 1, "kratko": 3})
        self.assertEqual({k: v["n"] for k, v in s["by_band"].items()}, {"+1 do +2 %": 1, "+2 do +3 %": 1, "iznad +3 %": 2})


class Real(Fix):
    """The owner's switch pravi_novac_nauceno. tok(31) is on the veliki list (age >= 15 d, liquidity $2M, MC $50M)."""

    def setUp(self):
        super().setUp()
        self.model()
        self.sells = []
        p = self._prio()
        p.start()
        self.addCleanup(p.stop)

    def on(self):
        self.flag(SW, "live")

    def stub_sell(self):
        def sell(con, cfg, position_id, frac=1.0, close=False, now=None, reason="", **kw):
            self.sells.append({"pos": position_id, "close": close, "reason": reason})
            return {"status": "ok", "amount_out": 1, "amount_in": 1}
        p = mock.patch.object(executor, "sell", sell)
        p.start()
        self.addCleanup(p.stop)

    def twin(self):
        r = self.rows(LU)
        return r[0] if r else None

    def test_the_switch_is_off_by_default_and_only_the_owner_turns_it_on(self):
        self.assertEqual(settings.flag(SW, con=self.con), "off")
        self.assertIn(SW, settings.OWNER_SWITCHES)
        for who in ("Grok", "vijeće", "", "autopilot-nauceno"):
            with self.assertRaises(ValueError):
                settings.set_flag(self.con, SW, "live", who)
        self.assertEqual(settings.flag(SW, con=self.con), "off")
        settings.set_flag(self.con, SW, "live", "Jure")
        self.assertEqual(settings.flag(SW, con=self.con), "live")
        from vijece import odluka
        for pc in ({"key": SW, "to": "live"}, {"flag": SW, "mode": "live"}, {"key": "flag", "name": SW, "to": "off"}):
            self.assertEqual(odluka.klasa(pc), "pravi_novac", pc)         # the council never applies it

    def test_off_the_real_buy_is_never_reached(self):
        out = self.tick((31,))
        self.assertEqual(len(self.rows()), 1, out)                        # the demo twin opens
        self.mirror()
        self.assertEqual(self.n_real_path(), (0, 0, 0, 0))                # no league trade, no position, no order, no swap
        self.assertIsNone(self.lg.execute("SELECT real FROM veliki_ucenik").fetchone()[0])
        # and if such a trade existed all the same, the mirror and the executor each refuse it by themselves
        self.demo(tok(32), executor.NAUCENO_SRC + " [skalp], prognoza +3.0% neto", mcap=5e7)
        self.mirror()
        st, reason = self.con.execute("SELECT status, reason FROM positions WHERE token=?", (tok(32),)).fetchone()
        self.assertEqual(st, "blocked")
        self.assertIn("pravi_novac_nauceno je isključen", reason)
        r = executor.buy(self.con, self.cfg, tok(33), "T", now=self.now, reason=executor.NAUCENO_SRC + " [skalp]",
                         size_sol=0.1)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("pravi_novac_nauceno je isključen", r["error"])
        self.assertEqual(self.swaps, [])

    def test_the_days_rule_switch_does_not_open_it_and_is_not_needed(self):
        settings.set_flag(self.con, "pravi_novac_veliki", "live", "Jure")  # the day rule's switch alone: no twin
        settings._FLAG_CACHE.clear()
        self.tick((31,))
        self.assertIsNone(self.twin())
        self.demo(tok(32), executor.NAUCENO_SRC + " [skalp]", mcap=5e7)
        self.mirror()
        self.assertEqual(self.swaps, [])
        self.assertEqual(self.con.execute("SELECT status FROM positions WHERE token=?", (tok(32),)).fetchone()[0], "blocked")

    def test_on_one_real_buy_per_entry_at_exactly_a_tenth_of_a_sol(self):
        self.on()                                                         # pravi_novac_veliki stays off
        out = self.tick((31,))
        d, t = self.rows()[0], self.twin()
        self.assertTrue(t, out)
        self.assertEqual((t["varijanta"], t["kind"], t["size_sol"], t["link_id"]), ("nauceno:skalp", "intra", 0.1, d["id"]))
        self.assertEqual((t["tp_px"], t["stop_px"], t["entry_px"], t["rt"], t["time_h"]),
                         (d["tp_px"], d["stop_px"], d["entry_px"], d["rt"], d["time_h"]))   # the demo twin's levels
        self.assertEqual((t["wide_px"], t["tight_ts"], t["half_frac"], t["trail"]), (None, None, 0.0, 0.0))
        src = self.lg.execute("SELECT source, auto FROM trades WHERE id=?", (t["trade_id"],)).fetchone()
        self.assertTrue(src[0].startswith("veliki: naučeno [skalp]"), src)
        self.assertIsNone(src[1])                                         # no TP/SL rule of the league sells it
        self.assertTrue(any(x.startswith("veliki naučeno PRAVI NOVAC: kupnja [skalp] BIG 0.1 SOL") for x in out), out)
        self.assertEqual(self.swaps, [])                                  # nothing is bought here: the mirror buys
        self.mirror()
        self.assertEqual([(s["token"], s["lamports"], s["live"]) for s in self.swaps], [(tok(31), 100_000_000, True)])
        self.mirror()
        self.tick((31,), now=self.now + 20)
        self.mirror()
        self.assertEqual(len(self.swaps), 1)                              # once per entry, never again
        st, mode, reason, sol_in = self.con.execute("SELECT status, mode, reason, sol_in FROM positions").fetchone()
        self.assertEqual((st, mode, sol_in), ("open", "live", 0.1))
        self.assertEqual(executor.strategy_label(reason), "naučeno")
        self.assertEqual(self.twin()["status"], "open")                   # bought: the twin stays
        self.assertIn(f"pravi blizanac #{t['id']}", self.lg.execute("SELECT real FROM veliki_ucenik WHERE id=?",
                                                                    (d["id"],)).fetchone()[0])

    def test_the_stake_is_never_above_a_tenth_whatever_the_midcap_stake_is(self):
        self.on()
        from veliki import gate
        with mock.patch.object(gate, "real_caps", lambda cfg=None: {**gate.REAL, "size_sol": 0.5}), \
                mock.patch.object(executor, "AUTO_VELIKI_SOL", 0.5):
            self.tick((31,))
            self.assertEqual(self.twin()["size_sol"], 0.1)
            self.mirror()
        self.assertEqual([s["lamports"] for s in self.swaps], [100_000_000])

    def refused(self, why, toks=(31,), patches=()):
        self.on()
        ps = [mock.patch.object(o, n, v) for o, n, v in patches]
        for p in ps:
            p.start()
        try:
            out = self.tick(toks)
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(len(self.rows()), len(toks), out)                # the demo twin opens all the same
        self.assertIsNone(self.twin(), out)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades WHERE user=?", (LU,)).fetchone()[0], 0)
        line = [x for x in out if x.startswith("veliki naučeno PRAVI NOVAC")]
        self.assertEqual(len(line), len(toks), out)                       # logged once per entry, with the reason
        self.assertIn(why, line[0])
        self.assertIn("ne pokušava se ponovno", line[0])
        self.assertIn(why, self.lg.execute("SELECT real FROM veliki_ucenik ORDER BY id").fetchone()[0])
        n = len(self.rows())
        self.tick(toks, now=self.now + M15 + 5)                           # the next bar: the same candidate is not retried
        self.assertEqual((len(self.rows()), self.twin()), (n, None))
        self.mirror()
        self.assertEqual(self.swaps, [])
        return out

    def test_gate_autopilot_off_or_no_key(self):
        self.refused("Autopilot je isključen ili ključ nije postavljen", patches=[(executor, "is_live", lambda cfg: False)])

    def test_gate_kill_switch(self):
        open(executor.STOP_FILE, "w").close()
        self.refused("kill switch")

    def test_gate_sell_all_in_progress(self):
        settings.put(self.con, "sell_all", 1, "Jure")
        self.refused("Prodaj sve")

    def test_gate_token_not_on_the_veliki_list(self):
        self.refused("nije na velikoj listi", toks=(100,))

    def test_gate_known_risk_and_a_bad_dip(self):
        from veliki import prioritet
        base = {"mint": tok(31), "symbol": "BIG", "score": 1.0, "parts": {}, "facts": {}}
        for extra, why in (({"risk": "top 10 holdera 60 %"}, "top 10 holdera 60 %"),
                           ({"block": "tim prodaje"}, "tim prodaje"),
                           ({"dip": {"kind": "los", "why": "hack"}}, "pad iz lošeg razloga")):
            with self.subTest(why=why):
                self.again(wipe=True)
                self.refused(why, patches=[(prioritet, "cached", lambda *a, **k: {tok(31): {**base, **extra}})])

    def test_gate_no_priority_row_liquidity_and_market_cap(self):
        from veliki import prioritet, universe
        self.refused("prioritet (holderi, sigurnost) još nije izračunat", patches=[(prioritet, "cached", lambda *a, **k: {})])
        for name, val, why in (("REAL_MIN_LIQ", 5e6, "likvidnost"), ("MIN_MCAP", 1e8, "MC $50.0M izvan")):
            with self.subTest(why=why):
                self.again(wipe=True)
                self.refused(why, patches=[(universe, name, val)])

    def test_gate_the_real_account_already_holds_the_token_and_the_shared_caps(self):
        self.on()
        self.demo(tok(31), "ručno", mcap=5e7, sl=None)                    # the real account holds it (any strategy)
        out = self.tick((31,))
        self.assertIsNone(self.twin())
        self.assertTrue(any("račun već drži token" in x for x in out), out)
        self.again(wipe=True)
        for i in range(5):                                                # the midcap caps count the day rule's rows too
            self.lg.execute("INSERT INTO veliki_trades (user, token, status, opened_ts, kind, size_usd, entry_px, stop_px) "
                            "VALUES (?,?,?,?,?,?,?,?)", (LU, f"D{i}", "open", int(self.now) - 60, "intra", 15.0, 1.0, 0.8))
        self.lg.commit()
        out = self.tick((31,))
        self.assertEqual([r for r in self.rows(LU) if r["varijanta"]], [])
        self.assertTrue(any("već 5 otvorenih (strop 5)" in x for x in out), out)
        self.assertEqual(len(self.rows()), 1)

    def test_a_buy_the_executor_refuses_is_logged_dropped_and_never_retried(self):
        self.on()
        self.live_rows(5, reason="copy KOL x", status="open")             # the real account is full (every strategy)
        self.tick((31,))
        t = self.twin()
        self.assertTrue(t)                                                # opened here: the executor is asked on the buy
        self.mirror()
        self.assertEqual(self.swaps, [])
        st, reason = self.con.execute("SELECT status, reason FROM positions WHERE league_id=?", (t["trade_id"],)).fetchone()
        self.assertEqual(st, "blocked")
        self.assertIn("max_open", reason)
        out = self.tick((31,), now=self.now + 20)
        c = self.twin()
        self.assertEqual((c["status"], c["reason"], c["ret"], c["pnl_usd"]), ("closed", "odbijeno", None, None), out)
        self.assertIn("max_open", c["exit_why"])
        self.assertEqual(self.lg.execute("SELECT status FROM trades WHERE id=?", (t["trade_id"],)).fetchone()[0], "closed")
        line = [x for x in out if x.startswith("veliki naučeno PRAVI NOVAC BIG: kupnja nije izvršena")]
        self.assertEqual(len(line), 1, out)
        self.assertIn("max_open", line[0])
        self.assertEqual(self.rows()[0]["status"], "open")                # the demo twin goes on: demo and real compare
        self.assertIn("odbijeno na izvršenju", self.lg.execute("SELECT real FROM veliki_ucenik WHERE id=?",
                                                               (self.rows()[0]["id"],)).fetchone()[0])
        self.mirror()
        self.tick((31,), now=self.now + M15 + 5)
        self.mirror()
        self.assertEqual((self.swaps, len(self.rows(LU))), ([], 1))       # never retried
        self.assertEqual(ucenik.real_stats(self.lg, self.now + 60)["closed"]["n"], 0)   # and counted nowhere

    def test_a_twin_the_mirror_never_took_is_dropped(self):
        self.on()
        self.tick((31,))
        self.tick((31,), now=self.now + 60)
        self.assertEqual(self.twin()["status"], "open")                   # run_trade may still be on its way
        out = self.tick((31,), now=self.now + ucenik.NO_BUY_S + 5)
        self.assertEqual(self.twin()["reason"], "odbijeno", out)
        self.assertTrue(any("proces pravog trgovanja nije preuzeo ulaz" in x for x in out), out)

    def bought(self):
        self.on()
        self.stub_sell()
        self.tick((31,))
        self.mirror()
        self.assertEqual(len(self.swaps), 1)
        return self.twin()

    def test_real_exit_at_the_target_sells_through_the_mirror(self):
        t = self.bought()
        self.tick((31,), now=self.now + 30, px=t["tp_px"] * 1.01)
        self.mirror()
        self.assertEqual(self.sells, [])                                  # armed only: nothing sold yet
        out = self.tick((31,), now=self.now + 60, px=t["tp_px"] * 1.01)
        d, c = self.rows()[0], self.twin()
        self.assertEqual((c["status"], c["reason"], d["status"], d["reason"]), ("closed", "tp", "closed", "tp"), out)
        self.assertAlmostEqual(c["ret"], d["ret"])                        # the same levels, the same quotes
        self.assertTrue(any(x.startswith("veliki naučeno PRAVI NOVAC izlaz [skalp] BIG: cilj") for x in out), out)
        self.mirror()
        self.assertEqual([(s["close"], s["reason"]) for s in self.sells], [(True, "veliki: cilj")])
        self.assertEqual(self.sells[0]["pos"], self.con.execute("SELECT id FROM positions").fetchone()[0])

    def test_real_exit_at_the_stop_after_a_restart_and_never_the_days_rule(self):
        self.model(skalp=0.0, siroko=0.05)                                # +20 % / -20 %
        t = self.bought()
        up = t["entry_px"] * 1.10                                         # +5 % net and more, held: the day rule would
        self.assertGreater(up, t["be_px"] * 1.05)                         # move the stop to the entry
        for dt in (20, 60, 100):
            self.tick((31,), now=self.now + dt, px=up)
        self.tick((31,), now=self.now + 130, px=t["entry_px"] * 1.01)     # under that "break-even": nothing sells
        self.tick((31,), now=self.now + 150, px=t["entry_px"] * 1.01)
        self.assertEqual((self.twin()["stop_px"], self.twin()["status"]), (t["stop_px"], "open"))
        self.assertEqual((self.twin()["wide_px"], self.twin()["tight_ts"]), (None, None))
        ucenik._PEND.clear()                                              # a deploy: nothing in memory survives
        ucenik._BOUGHT.clear()
        live._ST["q"] = {}
        self.tick((31,), now=self.now + 200, px=t["stop_px"] * 0.99)
        out = self.tick((31,), now=self.now + 230, px=t["stop_px"] * 0.98)
        c = self.twin()
        self.assertEqual((c["status"], c["reason"]), ("closed", "stop"), out)
        self.mirror()
        self.assertEqual([(s["close"], s["reason"]) for s in self.sells], [(True, "veliki: stop")])

    def test_real_exit_at_the_time_limit_and_with_the_switch_off_again(self):
        self.bought()
        self.flag(SW, "off")                                              # the owner turns it off: exits go on
        out = self.tick((31,), now=self.now + sjena.MAX_H * H + 5)
        self.assertEqual((self.twin()["reason"], self.rows()[0]["reason"]), ("time", "time"), out)
        self.mirror()
        self.assertEqual(len(self.sells), 1)

    def test_switched_off_again_no_new_twin_and_the_demo_goes_on(self):
        self.on()
        self.tick((31,))
        self.assertTrue(self.twin())
        self.flag(SW, "off")
        self.again(wipe=True)
        out = self.tick((31,))
        self.assertEqual((len(self.rows()), self.twin()), (1, None), out)

    def test_a_rug_closes_the_real_twin_only(self):
        from league import copy as lcopy
        self.bought()
        with mock.patch.object(lcopy, "_rugged", lambda *a, **k: {"text": "pool povučen"}):
            out = self.tick((31,), now=self.now + 30)
        self.assertEqual((self.twin()["status"], self.twin()["reason"]), ("closed", "rug"), out)
        self.assertEqual(self.rows()[0]["status"], "open")                # the demo twin stays the registered rule
        self.mirror()
        self.assertEqual(len(self.sells), 1)

    def test_the_rules_lines_do_not_count_the_twin_and_the_own_line_does(self):
        from report import midcap as rmid
        self.bought()
        self.assertIn("pravi: otvoreno 0 danas (0 sada otvorenih)", live.report_line(self.lg, self.now + 10))
        self.assertEqual(rmid.vrows(self.lg, since=0), [])
        self.assertIn("; pravi novac (prekidač uključen): otvoreno 1; zatvoreno 0", ucenik.line(self.lg, self.now + 10))
        res = executor.strategy_result(self.con, since=0)
        self.assertEqual((res["by"]["naučeno"]["open"], res["by"]["naučeno"]["closed"]), (1, 0))


class OwnerOrder(Fix):
    """The owner's order of 18.11., once and CONDITIONAL on the learner's purged result: the learned rule's real switch
    on and the day rule's off only when the corrected test confirms the +1 % threshold; nothing else is touched."""
    GOOD = {"n": 111, "clusters": 71, "ev": 0.049, "ev_trade": 0.04, "hit": 0.6, "lo": 0.017, "hi": 0.082}

    def setUp(self):
        super().setUp()
        from ui import assistnotes
        assistnotes._NAUCENO_SAID["ceka"] = False

    def result(self, purge=True, **st):
        return {"ts": int(self.now) - 600, **({"purge": True} if purge else {}),
                "variants": {"thr": {"0.01": {**self.GOOD, **st}, "0.02": self.GOOD}}}

    def order(self, result=None, **st):
        """One pass of the order; by default the corrected test confirms."""
        from ui import assistnotes
        done = assistnotes.owner_nauceno_real(self.con, result=self.result(**st) if result is None else result)
        settings._FLAG_CACHE.clear()
        return done

    def modes(self):
        st = settings.flag_state(self.con)
        return st[SW]["mode"], st["pravi_novac_veliki"]["mode"]

    def said(self, pr):
        return [c.args[0] for c in pr.call_args_list]

    def no_real_entry(self):
        """With the switch as the order left it, the učenik's entry stays demo only and nothing reaches a real buy."""
        self.model()
        with self._prio():
            out = self.tick((31,))
        self.assertEqual(len(self.rows()), 1, out)
        self.assertEqual(self.rows(LU), [])
        self.mirror()
        self.assertEqual(self.n_real_path(), (0, 0, 0, 0))

    def test_no_purged_result_yet_it_waits_and_says_so_once(self):
        from ui import assistnotes
        settings.set_flag(self.con, "pravi_novac_veliki", "live", "Jure")
        before = settings.raw(self.con)
        with mock.patch("builtins.print") as pr:
            self.assertFalse(self.order(result={}))                        # no result at all
            self.assertFalse(self.order(result=self.result(purge=False)))  # the leaky version's result, however good
            self.assertFalse(self.order(result={**self.result(), "purge": "da"}))   # only the marker True counts
            with mock.patch("veliki.nauceno.latest", lambda: self.result(purge=False)):
                self.assertFalse(assistnotes.owner_nauceno_real(self.con))  # read from the learner's store: the same
        self.assertEqual(self.said(pr), ["pravi trade: nalog vlasnika (pravi novac na naučeno pravilo) čeka ispravljeni "
                                         "rezultat učenja"])
        self.assertEqual(settings.raw(self.con), before)                   # nothing written, nothing switched
        self.assertEqual(self.modes(), ("off", "live"))
        self.assertTrue(self.order())                                      # the purged result arrives: it acts
        self.assertEqual(self.modes(), ("live", "off"))

    def test_the_purged_test_does_not_confirm_nothing_is_switched_and_it_never_fires_later(self):
        from ui import assistnotes
        settings.set_flag(self.con, "pravi_novac_veliki", "live", "Jure")
        for st in ({"lo": -0.004, "hi": 0.03, "ev": 0.013}, {"clusters": 29, "n": 40}, {"n": 0, "clusters": 0, "ev": None,
                                                                                         "lo": None, "hi": None}):
            with self.subTest(st=st):
                self.con.execute("DELETE FROM settings WHERE k=?", (assistnotes.NAUCENO_REAL_KEY,))
                self.con.commit()
                before = settings.raw(self.con)
                with mock.patch("builtins.print") as pr:
                    self.assertTrue(self.order(**st))                      # decided: no further pass
                said = self.said(pr)
                self.assertEqual(len(said), 1, said)
                self.assertTrue(said[0].startswith("pravi trade: nalog vlasnika NIJE izvršen: ispravljeni test ne "
                                                   "potvrđuje plus uz prag +1 % (prognoza iznad +1 %: n="), said)
                self.assertTrue(said[0].endswith("; pravi novac ostaje na dosadašnjem pravilu dok vlasnik ne odluči"))
                after = settings.raw(self.con)
                self.assertEqual({k for k in after if before.get(k) != after[k]}, {assistnotes.NAUCENO_REAL_KEY})
                self.assertEqual(after[assistnotes.NAUCENO_REAL_KEY]["ishod"], "ceka_vlasnika")
                self.assertEqual(self.modes(), ("off", "live"))            # real money stays where it was
        with mock.patch("builtins.print") as pr:
            self.assertTrue(self.order())                                  # a confirming result later: parked stays parked
        self.assertEqual((self.said(pr), self.modes()), ([], ("off", "live")))
        self.no_real_entry()
        settings.set_flag(self.con, SW, "live", "Jure")                    # the owner can still turn it on by hand
        self.assertEqual(settings.flag(SW, con=self.con), "live")

    def test_the_exact_lines_of_the_three_branches(self):
        settings.set_flag(self.con, "pravi_novac_veliki", "live", "Jure")
        with mock.patch("builtins.print") as pr:
            self.order(result={})
            self.order(lo=-0.004, hi=0.03, ev=0.013)
        self.assertEqual(self.said(pr), [
            "pravi trade: nalog vlasnika (pravi novac na naučeno pravilo) čeka ispravljeni rezultat učenja",
            "pravi trade: nalog vlasnika NIJE izvršen: ispravljeni test ne potvrđuje plus uz prag +1 % (prognoza iznad "
            "+1 %: n=111 (71 token-dana), prosjek po token-danu +1.3 %, raspon 90 % [-0.4; +3.0]; uvjet: najmanje 30 "
            "token-dana i donja granica iznad nule); pravi novac ostaje na dosadašnjem pravilu dok vlasnik ne odluči"])
        from ui import assistnotes
        self.con.execute("DELETE FROM settings WHERE k=?", (assistnotes.NAUCENO_REAL_KEY,))
        self.con.commit()
        with mock.patch("builtins.print") as pr:
            self.order()
        self.assertEqual(self.said(pr), [
            "pravi trade: nalog vlasnika 18.11.: pravi_novac_nauceno: off → live (vlasnik u chatu 18.11.: pravi novac "
            "odmah na naučeno pravilo)",
            "pravi trade: nalog vlasnika 18.11.: pravi_novac_veliki: live → off (vlasnik u chatu 18.11.: pravi novac "
            "odmah na naučeno pravilo)",
            "pravi trade: nalog vlasnika izvršen: ispravljeni test potvrđuje (prognoza iznad +1 %: n=111 (71 "
            "token-dana), prosjek po token-danu +4.9 %, raspon 90 % [+1.7; +8.2]; uvjet: najmanje 30 token-dana i donja "
            "granica iznad nule); pravi_novac_nauceno: off → live; pravi_novac_veliki: live → off; stropovi, ulog, kill "
            "switch, Grok autotrade i ostale strategije nisu dirani; otvorene prave pozicije dnevnog pravila ostaju "
            "otvorene i zadržavaju izlaze"])

    def test_while_it_waits_no_real_entry_of_the_ucenik_can_happen(self):
        self.assertFalse(self.order(result={}))
        self.no_real_entry()

    def test_both_switches_once_with_a_line_each_and_nothing_else(self):
        from stanja import ploca
        from ui import assistnotes, grokauto
        settings.set_flag(self.con, "pravi_novac_veliki", "live", "Jure", now=1_700_000_000)
        grokauto.set_on(self.con, False, "Jure")
        before = settings.raw(self.con)
        with mock.patch("builtins.print") as pr:
            self.assertTrue(self.order())
        said = self.said(pr)
        for one in ("pravi_novac_nauceno: off → live", "pravi_novac_veliki: live → off"):
            self.assertEqual(sum(1 for x in said if one in x and assistnotes.NAUCENO_REAL_WHY in x), 1, said)
        self.assertEqual(sum(1 for x in said if x.startswith("pravi trade: nalog vlasnika izvršen: ispravljeni test "
                                                             "potvrđuje (prognoza iznad +1 %: n=111 (71 token-dana)")), 1)
        self.assertEqual(self.modes(), ("live", "off"))
        st = settings.flag_state(self.con)
        self.assertGreater(st[SW]["since"], 1_700_000_000)                # both carry the time of the order
        self.assertGreater(st["pravi_novac_veliki"]["since"], 1_700_000_000)
        self.assertEqual(st[SW]["who"], settings.owner())
        after = settings.raw(self.con)
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        self.assertEqual(changed, {f"flag:{SW}", "flag:pravi_novac_veliki", "applied_log", assistnotes.NAUCENO_REAL_KEY,
                                   "owner_flag_once:pravi_novac_veliki:live"})
        self.assertEqual(assistnotes.NAUCENO_REAL_KEY, "owner_once:pravi_novac_nauceno_1811")
        self.assertEqual(after[assistnotes.NAUCENO_REAL_KEY]["ishod"], "izvrseno")
        self.assertEqual(after[assistnotes.NAUCENO_REAL_KEY]["promjene"],
                         ["pravi_novac_nauceno: off → live", "pravi_novac_veliki: live → off"])
        self.assertFalse(grokauto.state(self.con)["on"])                  # Grok autotrade, caps, kill switch: untouched
        self.assertEqual(settings.flag(settings.SWITCH_ALL, con=self.con), "off")
        log = after["applied_log"][:2]
        self.assertEqual({(x["key"], x["old"], x["new"]) for x in log},
                         {(f"flag:{SW}", "off", "live"), ("flag:pravi_novac_veliki", "live", "off")})
        board = {r["key"]: r for r in ploca.now(trade_db=settings.DB, env={})}
        new, old = board["real_money_switch:naučeno pravilo (model učenja)"], board["real_money_switch:midcap raspon"]
        self.assertEqual((new["state"], old["state"]), ("live", "off"))
        self.assertEqual((new["since"], old["since"]), (st[SW]["since"], st["pravi_novac_veliki"]["since"]))
        self.assertEqual(new["who"], settings.owner())

    def test_it_runs_once_and_a_later_tap_of_the_owner_stays(self):
        from ui import assistnotes
        self.order()
        with mock.patch("builtins.print") as pr:
            self.assertTrue(self.order())
        self.assertEqual(self.said(pr), [])
        settings.set_flag(self.con, SW, "off", "Jure")                    # he changes his mind on both
        settings.set_flag(self.con, "pravi_novac_veliki", "live", "Jure")
        self.assertTrue(self.order())
        assistnotes.owner_flag_orders(self.con)                           # nor does an older order replay over it
        settings._FLAG_CACHE.clear()
        self.assertEqual(self.modes(), ("off", "live"))

    def test_the_older_order_of_15_11_is_not_replayed_over_it_on_a_new_database(self):
        from ui import assistnotes
        self.order()
        assistnotes.owner_flag_orders(self.con)
        settings._FLAG_CACHE.clear()
        self.assertEqual(self.modes(), ("live", "off"))

    def test_the_days_rule_open_real_position_keeps_its_exits_and_only_new_entries_stop(self):
        settings.set_flag(self.con, "pravi_novac_veliki", "live", "Jure")
        settings.put(self.con, "veliki_dokaz", "nalog_vlasnika", "Jure")  # his order of 15.11.: no wait for the proof
        settings._FLAG_CACHE.clear()
        self.px = 0.95e-4                                                 # the day rule's own entry, demo and real
        with self._prio():
            out = self.tick((31,))
            rows = {r[0]: r[1] for r in self.lg.execute("SELECT user, id FROM veliki_trades")}
            self.assertEqual(set(rows), {PU, LU}, out)
            self.mirror()
            self.assertEqual(len(self.swaps), 1)                          # the day rule's real position is bought
            before = (self.rows(LU)[0], self.con.execute("SELECT status, qty_left FROM positions").fetchall(),
                      self.lg.execute("SELECT status FROM trades WHERE user=?", (LU,)).fetchall())
            self.order()
            self.assertEqual(self.modes(), ("live", "off"))
            self.mirror()
            self.tick((31,), now=self.now + 20)
            self.mirror()
            # nothing was sold, closed or orphaned by the order: the position is as it was and still managed
            self.assertEqual((self.rows(LU)[0], self.con.execute("SELECT status, qty_left FROM positions").fetchall(),
                              self.lg.execute("SELECT status FROM trades WHERE user=?", (LU,)).fetchall()), before)
            self.assertEqual(len(self.swaps), 1)
            sells = []
            with mock.patch.object(executor, "sell", lambda con, cfg, pid, frac=1.0, close=False, **k: sells.append(
                    (pid, close)) or {"status": "ok", "amount_out": 1}):
                tp = before[0]["tp_px"]
                out = self.tick((31,), now=self.now + 60, px=tp * 1.01)   # its own target: sold by its own exit logic
                self.assertEqual(self.rows(LU)[0]["status"], "closed", out)
                self.assertEqual(self.rows(LU)[0]["reason"], "tp")
                self.mirror()
            self.assertEqual(sells, [(self.con.execute("SELECT id FROM positions").fetchone()[0], True)])
            # the day rule goes on in the demo, with no new real entry
            self.lg.execute("UPDATE veliki_trades SET closed_ts=? WHERE status='closed'", (int(self.now - 2 * H),))
            self.lg.commit()
            self.again()
            n_real = self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=?", (LU,)).fetchone()[0]
            out = self.tick((31,), now=self.now + M15 + 5)
            self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=?", (LU,)).fetchone()[0],
                             n_real, out)
            self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE user=? AND status='open'",
                                             (PU,)).fetchone()[0], 1, out)
            self.mirror()
            self.assertEqual(len(self.swaps), 1)

    def test_after_the_order_the_learned_rule_buys_with_real_money(self):
        self.order()
        self.model()
        with self._prio():
            out = self.tick((31,))
        self.assertEqual([r["varijanta"] for r in self.rows(LU)], ["nauceno:skalp"], out)
        self.mirror()
        self.assertEqual([(s["token"], s["lamports"]) for s in self.swaps], [(tok(31), 100_000_000)])

    def test_the_once_block_calls_it_before_the_state_lines(self):
        with open(os.path.join(ROOT, "ui", "pravitrade.py"), encoding="utf-8") as f:
            src = f.read()
        a, b = src.index("assistnotes.owner_nauceno_real(con)"), src.index('print("stanje: " + line[:600]')
        self.assertLess(src.index("if not once:"), a)
        self.assertLess(a, b)
        self.assertEqual(src.count("n_left = not assistnotes.owner_nauceno_real(con)"), 2)   # and again every minute
        self.assertIn("if n_left and time.time() >= n_next:", src)


class ByStrategy(Fix):
    """trade/executor.strategy_result: the real-money result by strategy since 15.11. (read-only)."""

    def pos(self, reason, status, sol_in=0.1, sol_back=0.0, fees=0.0, opened=None, mode="live"):
        self.con.execute("INSERT INTO positions (token, opened_ts, closed_ts, mode, status, sol_in, sol_back, fees_sol, "
                         "reason) VALUES (?,?,?,?,?,?,?,?,?)",
                         ("T", int(opened or executor.STRATEGY_SINCE + 3600), None if status == "open" else
                          int(executor.STRATEGY_SINCE + 7200), mode, status, sol_in, sol_back, fees, reason))
        self.con.commit()

    def test_since_is_the_fifteenth_of_november_utc(self):
        import calendar
        self.assertEqual(executor.STRATEGY_SINCE, calendar.timegm((2026, 11, 15, 0, 0, 0)))

    def test_per_strategy_closed_sum_mean_and_open(self):
        self.pos("veliki: dnevna zona 1-2 (20%), cilj +10.0%", "closed", 0.1, 0.112, 0.002)     # +0.010 SOL, +10 %
        self.pos("veliki: dnevna zona 1-2 (20%), cilj +10.0%", "closed", 0.1, 0.078, 0.002)     # -0.024 SOL, -24 %
        self.pos("veliki: dnevna zona 1-2 (20%), cilj +10.0%", "open", 0.1)
        self.pos("veliki: podrška 1-2, cilj +15.0%", "closed", 0.1, 0.095, 0.0)
        self.pos("veliki: DCA BIG 0.1 SOL (pad)", "open", 0.1)
        self.pos("veliki: naučeno [skalp], prognoza +2.1% neto", "closed", 0.1, 0.104, 0.001)
        self.pos("copy KOL ansem", "closed", 0.05, 0.06, 0.0)
        self.pos("Grok auto (MCP)", "open", 0.1)
        self.pos("ručno: brza kupnja", "closed", 0.2, 0.1, 0.0)
        self.pos("veliki: dnevna zona", "closed", 0.1, 5.0, 0.0, opened=executor.STRATEGY_SINCE - 10)   # before 15.11.
        self.pos("veliki: dnevna zona", "closed", 0.1, 5.0, 0.0, mode="dry")                           # a probe
        self.pos("max_open: 5 otvorenih", "blocked", 0.0)                                               # never bought
        res = executor.strategy_result(self.con)
        by = res["by"]
        self.assertEqual(set(by), {"veliki dnevni raspon", "veliki raspon 7 d", "veliki DCA lot", "naučeno", "kopiranje",
                                   "grok", "ručno"})
        d = by["veliki dnevni raspon"]
        self.assertEqual((d["closed"], d["open"], d["wins"]), (2, 1, 1))
        self.assertAlmostEqual(d["sol"], -0.014)
        self.assertAlmostEqual(d["ret"], -0.07)
        self.assertAlmostEqual(d["open_sol"], 0.1)
        self.assertAlmostEqual(by["naučeno"]["ret"], 0.03)
        self.assertEqual((by["grok"]["closed"], by["grok"]["ret"], by["grok"]["open"]), (0, None, 1))
        self.assertEqual((res["total"]["closed"], res["total"]["open"]), (6, 3))
        self.assertAlmostEqual(res["total"]["sol"], -0.014 - 0.005 + 0.003 + 0.01 - 0.1)
        line = executor.strategy_line(res)
        self.assertTrue(line.startswith("pravi novac po strategiji od 15.11.: veliki dnevni raspon n=2, zbroj -0.014 SOL, "
                                        "prosjek -7.0%, otvoreno 1 (0.10 SOL); "), line)
        self.assertIn("naučeno n=1, zbroj +0.003 SOL, prosjek +3.0%, otvoreno 0", line)
        self.assertIn("grok n=0, zbroj +0.000 SOL, prosjek —, otvoreno 1 (0.10 SOL)", line)
        self.assertIn("UKUPNO n=6, zbroj -0.106 SOL", line)

    def test_empty_and_read_only(self):
        self.assertEqual(executor.strategy_line(executor.strategy_result(self.con)),
                         "pravi novac po strategiji od 15.11.: još nema pravih pozicija")
        import sqlite3
        ro = sqlite3.connect(f"file:{settings.DB}?mode=ro", uri=True)
        try:
            self.assertEqual(executor.strategy_result(ro)["by"], {})      # SELECTs only: a read-only connection is enough
        finally:
            ro.close()

    def test_the_trade_loop_prints_it_at_the_start_and_once_a_day(self):
        import run_trade
        self.pos("copy KOL ansem", "closed", 0.05, 0.06, 0.0)
        run_trade._strategy_log.update(day=None, hour=None)
        with mock.patch("builtins.print") as pr:
            run_trade._strategy_summary(self.con, self.cfg, now=self.now)
            run_trade._strategy_summary(self.con, self.cfg, now=self.now + 60)
            run_trade._strategy_summary(self.con, self.cfg, now=self.now + 2 * H)
            run_trade._strategy_summary(self.con, self.cfg, now=self.now + 2 * D)
        said = [c.args[0] for c in pr.call_args_list]
        self.assertEqual(len(said), 2, said)                              # the start, then the next day
        self.assertTrue(all(x.startswith("pravi novac po strategiji od 15.11.: kopiranje n=1, zbroj +0.010 SOL, prosjek "
                                         "+20.0%, otvoreno 0") for x in said), said)


if __name__ == "__main__":
    unittest.main()
