"""11.11. noćni popravci (Jure): stale Grok trade requests (keyed by the positions a sell was about; the brief shows
only pending ones unless include_closed; a one-time cleanup; the 5-min tidy runs even when the sync fails), Grok's
predictions (intake, MemeSonar's EV-implied probability, scoring after 1 h / 4 h / 24 h on synthetic minute candles,
the night's capped GeckoTerminal fill, the calibration in the brief), the night batch's health (start, duration,
calls processed, Helius, errors; the alert when it has not finished by 04:30 Zagreb), exit plans on the real account
for Grok autotrade positions behind the owner switch exit_plan_live, and range breakouts (entry_ready, status
breakout, never a range entry candidate). (The caller weights applied on arrival: tests/test_mcpdata_offline; the
EV gate of get_trade_candidates: tests/test_kandidati_offline EvGate.) Temp dirs only, no network.

    python3 -m unittest tests.test_popravci_1111_offline
"""
import json
import os
import sqlite3
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from events import brief, health, night, outcomes, predictions, remeasure, sources, store  # noqa: E402
from league import auto, exitplan, store as lstore  # noqa: E402
from rangedca import data as rdata, view as rview  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import mcpapi  # noqa: E402
from tests.test_events_offline import Env, zagreb  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base as TradeBase, MINT  # noqa: E402

NOW = int(time.time())
H = 3600
TOK = "Pred" + "p" * 36 + "pump"
TOK2 = "Dump" + "d" * 36 + "pump"
TOK3 = "Gtcn" + "g" * 36 + "pump"
LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
QUIET = {"log": lambda *a: None}


# ---------- 2. stale trade requests -----------------------------------------------------------------------------------
class Requests(Env):
    def setUp(self):
        super().setUp()
        self.tc = executor.connect(self.p["trade"])
        # the sell g1794342901001 was about position 1 (closed); a new position 2 in the same token opened since
        self.tc.execute("INSERT INTO positions (id, token, opened_ts, mode, status, sol_in) VALUES (1, ?, ?, 'live', "
                        "'closed', 0.1)", (TOK, NOW - 3000))
        self.tc.execute("INSERT INTO positions (id, token, opened_ts, mode, status, sol_in) VALUES (2, ?, ?, 'live', "
                        "'open', 0.1)", (TOK, NOW - 60))
        self.tc.commit()

    def tearDown(self):
        self.tc.close()
        super().tearDown()

    def test_a_sell_is_keyed_by_its_positions_and_the_brief_shows_only_pending(self):
        settings.put(self.tc, "mcp_requests", [
            {"id": "g1794342901001", "ts": NOW - 300, "token": TOK, "side": "sell", "amount": 1, "status": "pending"},
            {"id": "g2", "ts": NOW - 30, "token": TOK, "side": "sell", "amount": 0.5, "status": "pending"},
            {"id": "g3", "ts": NOW - 3000, "token": TOK2, "side": "buy", "amount": 0.05, "status": "rejected"}])
        # g1794342901001 was made before position 2 opened: its own position is closed, the new one is another one
        view = {r["id"]: r["status"] for r in mcpapi.requests_view(self.tc, NOW)}
        self.assertEqual(view, {"g1794342901001": "obsolete", "g2": "pending", "g3": "rejected"})
        self.assertEqual([r["id"] for r in mcpapi.pending(self.tc, NOW)], ["g2"])   # never approvable
        shown, hidden = brief.requests_part(NOW)
        self.assertEqual(([r["id"] for r in shown], hidden), (["g2"], 2))
        shown, hidden = brief.requests_part(NOW, include_closed=True)
        self.assertEqual((len(shown), hidden), (3, 0))
        self.assertFalse(mcpapi.sell_positions_open({"token": TOK, "ts": NOW - 300}, {TOK: [NOW - 60]}))
        self.assertTrue(mcpapi.sell_positions_open({"token": TOK, "ts": NOW - 300}, {TOK}))   # a plain set still works

    def test_one_time_cleanup_and_the_tick_tidies_even_when_the_sync_fails(self):
        settings.put(self.tc, "mcp_requests", [
            {"id": "old", "ts": NOW - 86400, "token": TOK2, "side": "buy", "amount": 0.1, "status": "pending"}])
        self.assertEqual(mcpapi.cleanup_requests_once(self.tc, NOW), 1)
        self.assertEqual(settings.raw(self.tc)["mcp_requests"][0]["status"], "expired")
        self.assertEqual(mcpapi.cleanup_requests_once(self.tc, NOW), 0)                 # once
        settings.put(self.tc, "mcp_requests", [
            {"id": "g9", "ts": NOW - 100, "token": TOK, "side": "sell", "amount": 1, "status": "pending",
             "positions": [1]}])
        with mock.patch.object(sources, "sync", side_effect=RuntimeError("sync pao")):
            with self.assertRaises(RuntimeError):
                night.tick(NOW, **QUIET)
        self.assertEqual(settings.raw(self.tc)["mcp_requests"][0]["status"], "obsolete")


# ---------- 4. the night batch's health ---------------------------------------------------------------------------------
class NightHealth(Env):
    def test_the_report_holds_start_duration_calls_helius_errors_and_the_brief_shows_them(self):
        t = zagreb(2026, 11, 12, 3, 5)
        store.kv_put(self.econ, "backfill", {"done": 1})
        with mock.patch.object(outcomes, "compute", lambda econ, now, log=print: {"ok": 30, "nedostupno": 4}), \
                mock.patch.object(remeasure, "run", lambda econ, now, log=print, force=False: {"calls": 12, "requests": 5}), \
                mock.patch.object(outcomes, "scores", side_effect=RuntimeError("boom")), \
                mock.patch.object(night, "step_groups", lambda now, cap, log=print: {"ran": False, "credits": 0}), \
                mock.patch.object(outcomes, "early_wallets", lambda *a, **k: {}), \
                mock.patch.object(night, "helius_used", lambda *a: 120.0):
            rep = night.run(t, econ=self.econ, **QUIET)
        self.assertEqual(rep["calls_processed"], {"outcomes": 34, "remeasured": 12, "total": 46})
        self.assertIn("scores", rep["errors"])
        self.assertEqual(rep["helius_credits"], 120.0)
        self.assertGreaterEqual(rep["finished_ts"], rep["started_ts"])
        self.assertIn("predictions", rep["steps"])
        self.assertEqual(store.kv_get(self.econ, "night_start")["day"], "2026-11-12")
        h = brief.health_part(self.econ, zagreb(2026, 11, 12, 9))
        ln = h["last_night"]
        self.assertEqual((ln["status"], ln["calls_processed"]["total"], ln["day"]), ("errors", 46, "2026-11-12"))
        self.assertIn("scores", ln["errors"])
        self.assertIsNotNone(ln["duration_s"])
        self.assertIsNotNone(ln["started_ts"])

    def test_alert_when_not_finished_by_0430(self):
        self.assertIsNone(night.late_alert(self.econ, zagreb(2026, 11, 12, 5)))       # never ran: nothing to compare
        self.assertIsNone(brief.health_part(self.econ, zagreb(2026, 11, 12, 5))["last_night"])
        store.kv_put(self.econ, "night_day", "2026-11-11")
        self.assertIsNone(night.late_alert(self.econ, zagreb(2026, 11, 12, 4, 29)))
        self.assertIn("nije ni počela", night.late_alert(self.econ, zagreb(2026, 11, 12, 4, 31))["title"])
        store.kv_put(self.econ, "night_start", {"ts": zagreb(2026, 11, 12, 3, 2), "day": "2026-11-12"})
        self.econ.commit()
        self.assertIn("počela je u 03:02", night.late_alert(self.econ, zagreb(2026, 11, 12, 4, 31))["title"])
        from usage import meter
        with mock.patch.object(sources, "sync", lambda *a, **k: {}), mock.patch.object(health, "check", lambda *a, **k: []), \
                mock.patch.object(meter, "DB", self.p["usage"]):
            r = night.tick(zagreb(2026, 11, 12, 4, 35), **QUIET)
            self.assertEqual(r["night_late"]["day"], "2026-11-12")
            self.assertIsNone(night.tick(zagreb(2026, 11, 12, 4, 40), **QUIET)["night_late"])   # once a day
        uc = sqlite3.connect(self.p["usage"])
        self.assertTrue(uc.execute("SELECT COUNT(*) FROM alerts WHERE key = 'events:night:late'").fetchone()[0])
        uc.close()
        econ = store.connect()
        try:
            h = brief.health_part(econ, zagreb(2026, 11, 12, 4, 45))
        finally:
            econ.close()
        self.assertEqual(h["last_night"]["status"], "not_finished_by_0430")
        self.assertTrue(any(a.get("type") == "night" for a in h["alerts"]))
        store.kv_put(self.econ, "night_day", "2026-11-12")                              # done at last
        self.assertIsNone(night.late_alert(self.econ, zagreb(2026, 11, 12, 5)))


# ---------- 3. Grok's predictions ------------------------------------------------------------------------------------------
def candles(t0, waypoints):
    """1-minute (ts, o, h, l, c, v) through (minute, price) waypoints."""
    out, prev = [], None
    for (m0, p0), (m1, p1) in zip(waypoints, waypoints[1:]):
        for m in range(m0, m1):
            px = p0 + (p1 - p0) * (m - m0) / (m1 - m0)
            o = prev if prev is not None else px
            out.append((t0 + m * 60, o, max(o, px), min(o, px), px, 100.0))
            prev = px
    return out


class Predictions(Env):
    T0 = NOW - NOW % 60 - 30 * H

    def setUp(self):
        super().setUp()
        d = self.tmp.name
        self.env2 = mock.patch.dict(os.environ, {"RANGE_DB": os.path.join(d, "range.db"),
                                                 "RANGE_HYPE_DB": os.path.join(d, "hype_pulse.db")})
        self.env2.start()
        self.tc = executor.connect(self.p["trade"])
        self.flag("shadow")
        self.rows = [{"token": TOK, "ev_pct": 5.0, "n_samples": 40}]

    def tearDown(self):
        self.tc.close()
        settings._FLAG_CACHE.clear()
        self.env2.stop()
        super().tearDown()

    def flag(self, m):
        settings.put(self.tc, "flag:grok_predictions", {"mode": m, "since": NOW, "who": "Jure"})
        settings._FLAG_CACHE.clear()

    def args(self, tok=TOK, **kw):
        a = {"token": tok, "ts": self.T0, "mcap": 120_000, "strategy": "momentum", "p_tp": 0.6, "tp_pct": 30,
             "sl_pct": 20, "p_up10_1h": 0.7, "p_up20_1h": 0.5, "p_up50_1h": 0.1, "p_up10_4h": 0.8, "p_up20_4h": 0.6,
             "p_up50_4h": 0.2, "p_up10_24h": 0.85, "p_up20_24h": 0.65, "p_up50_24h": 0.3, "p_drop30_first": 0.2,
             "verdict": "runner", "reasons": ["3 KOL-a", "rast autora"]}
        a.update(kw)
        return a

    def submit(self, **kw):
        return predictions.submit(self.args(**kw), "grok", now=self.T0 + 30, econ=self.econ, tcon=self.tc,
                                  rows_fn=lambda: self.rows)

    def minute_db(self, tok, cs):
        con = sqlite3.connect(self.p["minute"])
        con.execute("CREATE TABLE IF NOT EXISTS call_candles (token TEXT PRIMARY KEY, data BLOB)")
        con.execute("INSERT OR REPLACE INTO call_candles VALUES (?, ?)", (tok, rdata.pack(cs)))
        con.commit()
        con.close()

    def test_intake_rules_and_memesonars_probability(self):
        self.flag("off")
        with self.assertRaisesRegex(ValueError, "switched off"):
            self.submit()
        self.flag("shadow")
        for kw, msg in (({"mcap": 20_000}, "30k"), ({"ts": self.T0 - 3600}, "older"), ({"strategy": "x"}, "strategy"),
                        ({"p_up20_1h": 0.8}, "must not grow"), ({"p_up50_24h": 0.05}, "must not fall"),
                        ({"p_tp": 1.4}, "p_tp"), ({"verdict": "kupi"}, "verdict"), ({"token": "abc"}, "token")):
            with self.assertRaisesRegex(ValueError, msg):
                self.submit(**kw)
        out = self.submit()
        self.assertEqual(out["status"], "stored")
        # EV-implied p at +30 / -20: (0.05 + 0.02 + 0.20) / 0.50
        self.assertEqual(out["memesonar"]["p_tp"], 0.54)
        self.assertEqual(out["score_after"]["1h"], self.T0 + H + predictions.GRACE_S)
        row = self.econ.execute("SELECT p_up, reasons, ms_n, key_id FROM grok_predictions WHERE id=?", (out["id"],)).fetchone()
        self.assertEqual(json.loads(row[0])["4h"], {"up10": 0.8, "up20": 0.6, "up50": 0.2})
        self.assertEqual((row[1], row[2], row[3]), ("3 KOL-a; rast autora", 40, "grok"))
        self.assertIsNone(self.submit(token=TOK2)["memesonar"]["p_tp"])                # not a candidate now
        self.assertEqual(predictions.implied_p(-50, 10, 10), 0.0)                      # clipped
        # the MCP tool: listed as a write tool, refuses with an error, never touches autotrade
        names = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertFalse(names["submit_grok_prediction"]["annotations"]["readOnlyHint"])
        with mock.patch.object(predictions, "_kandidati_rows", lambda: self.rows):
            d, err = mcpapi._tool("submit_grok_prediction", {"token": TOK, "mcap": 1}, "grok")
        self.assertTrue(err)
        self.assertIn("error", d)

    def test_scored_after_each_horizon_from_the_minute_data_and_the_calibration(self):
        t0 = self.T0
        # TOK: +30 % at ~35 min (TP), then down to -30 % by 3 h; TOK2: sparse price ticks, -20 % first
        self.minute_db(TOK, candles(t0 - 300, [(0, 1.0), (5, 1.0), (40, 1.35), (65, 1.2), (185, 0.7), (1500, 0.9)]))
        rows = [store.row("price_tick", t0 + k * 600, TOK2, "dexscreener", None, None, 100_000, {"p": 1.0 - 0.02 * k},
                          key=f"pt{k}") for k in range(0, 150)]
        store.insert(self.econ, rows)
        a = self.submit()["id"]
        b = self.submit(token=TOK2, p_tp=0.3)["id"]
        c = self.submit(token=TOK3, p_tp=0.5)["id"]                                     # no data at all
        self.assertEqual(predictions.score_due(self.econ, t0 + H), 0)                   # not due yet
        n = predictions.score_due(self.econ, t0 + H + predictions.GRACE_S + 60)
        self.assertEqual(n, 2)
        r = dict(zip(("scores", "tp_first", "entry_px"), self.econ.execute(
            "SELECT scores, tp_first, entry_px FROM grok_predictions WHERE id=?", (a,)).fetchone()))
        s1 = json.loads(r["scores"])["1h"]
        self.assertEqual((s1["status"], s1["first"], s1["up10"], s1["up20"], s1["up50"]), ("ok", "tp", True, True, False))
        self.assertAlmostEqual(s1["max_gain_pct"], 35.0, delta=0.5)
        self.assertEqual(r["tp_first"], 1)                                              # decided within the hour
        self.assertAlmostEqual(r["entry_px"], 1.0)
        later = t0 + 25 * H
        predictions.score_due(self.econ, later)
        sa = json.loads(self.econ.execute("SELECT scores FROM grok_predictions WHERE id=?", (a,)).fetchone()[0])
        self.assertEqual(sa["4h"]["first"], "tp")
        self.assertAlmostEqual(sa["4h"]["max_loss_pct"], -30.0, delta=0.5)
        drop, done = self.econ.execute("SELECT drop30_first, done FROM grok_predictions WHERE id=?", (a,)).fetchone()
        self.assertEqual((drop, done), (0, 1))                                          # +20 % came before -30 %
        tb, sb = self.econ.execute("SELECT tp_first, scores FROM grok_predictions WHERE id=?", (b,)).fetchone()
        self.assertEqual(tb, 0)
        sb = json.loads(sb)
        self.assertEqual((sb["1h"]["first"], sb["4h"]["first"]), ("none", "sl"))     # -2 % per 10 min: -20 % at 100 min
        self.assertIsNone(self.econ.execute("SELECT scores FROM grok_predictions WHERE id=?", (c,)).fetchone()[0])
        # the brief: what was scored since `since`, and the calibration, Grok's and MemeSonar's
        part = predictions.brief_part(self.econ, t0, later)
        self.assertEqual({x["id"] for x in part["items"]}, {a, b})
        self.assertEqual(part["pending"], 1)
        cal = part["calibration"]
        g = {x["bucket"]: x for x in cal["grok"]}
        self.assertEqual((g["0.6-0.8"]["n"], g["0.6-0.8"]["predicted_pct"], g["0.6-0.8"]["actual_pct"]), (1, 60.0, 100.0))
        self.assertEqual((g["0.2-0.4"]["n"], g["0.2-0.4"]["actual_pct"]), (1, 0.0))
        m = {x["bucket"]: x for x in cal["memesonar"]}
        self.assertEqual((m["0.4-0.6"]["n"], m["0.4-0.6"]["predicted_pct"]), (1, 54.0))
        self.assertEqual(cal["brier"]["grok_p_tp"]["n"], 2)
        self.assertEqual(cal["brier"]["grok_p_up20_1h"]["n"], 2)
        self.assertIsNone(predictions.brief_part(self.econ, later + 1, later)["items"] or None)

    def test_the_night_fills_from_geckoterminal_within_the_shared_cap(self):
        t0 = self.T0
        c = self.submit(token=TOK3, p_tp=0.5)["id"]
        later = t0 + 25 * H
        self.assertEqual(predictions.score_due(self.econ, later), 0)                    # waits for the night
        asked = []

        def fetch(pool, end, limit, agg=1):
            asked.append((pool, agg))
            cs = candles(t0 - 600, [(0, 1.0), (70, 1.0), (130, 0.75), (1600, 0.8)])
            return [x for x in cs if x[0] % (60 * agg) == 0 and x[0] <= end]
        with mock.patch.object(remeasure, "cap_left", lambda econ, now, cap=None: 3):
            out = predictions.night(self.econ, later, log=lambda *a: None, fetch=fetch,
                                    fetch_dex=lambda toks: {TOK3: ("POOL3", 1e9)})
        self.assertEqual((out["requests"], out["scored"]), (1, 1))
        self.assertEqual(asked, [("POOL3", 5)])                                         # one 5-minute request for 24 h
        self.assertEqual(remeasure.used(self.econ, later), 1)                           # the remeasure step's counter
        tp_first, scores = self.econ.execute("SELECT tp_first, scores FROM grok_predictions WHERE id=?", (c,)).fetchone()
        self.assertEqual(tp_first, 0)
        self.assertEqual(json.loads(scores)["24h"]["first"], "sl")
        with mock.patch.object(remeasure, "cap_left", lambda econ, now, cap=None: 0):
            self.submit(token=TOK, p_tp=0.5)
            self.assertEqual(predictions.night(self.econ, later + 30 * H, log=lambda *a: None, fetch=fetch,
                                               fetch_dex=lambda t: {})["requests"], 0)
        # 30 h after its end a horizon without data is unavailable, never guessed
        predictions.score_due(self.econ, later + 60 * H)
        sc = json.loads(self.econ.execute("SELECT scores FROM grok_predictions WHERE token=? ORDER BY id DESC",
                                          (TOK,)).fetchone()[0])
        self.assertEqual(sc["24h"]["status"], "unavailable")


# ---------- 5. exit plans on the real account for Grok autotrade positions ------------------------------------------------
class ExitPlanLive(TradeBase):
    def setUp(self):
        super().setUp()
        exitplan._LAST.clear()
        exitplan.ensure(self.lg)
        self.mode("paper")
        settings.put(self.con, "sl_default", 30)
        p = mock.patch.object(exitplan, "paused", lambda: bool(settings.raw(self.con).get("exit_plans_paused")))
        p.start()
        self.addCleanup(p.stop)
        from ui import grokauto
        self.grok = grokauto
        grokauto.set_on(self.con, True, "Jure")

    def tearDown(self):
        settings._FLAG_CACHE.clear()
        super().tearDown()

    def mode(self, m, name="exit_plans"):
        settings.put(self.con, f"flag:{name}", {"mode": m, "since": int(time.time())})
        settings._FLAG_CACHE.clear()

    def lot(self, src="Grok auto (MCP)"):
        tid = lstore.buy(self.lg, LU, MINT, "GTA", 30, 1.0, 100_000, src, None, 50_000.0, allow_open=True)
        auto.set_auto(self.lg, LU, tid, "tpsl", "+15%", "-30%")
        return tid

    def mk(self, px):
        return lambda toks: {t: (px, 100_000.0, None, 50_000.0 * px) for t in toks}

    def qty(self):
        return sum(r[0] for r in self.lg.execute("SELECT qty FROM trades WHERE user=? AND token=? AND status='open'",
                                                 (LU, MINT)))

    def test_gta_logged_only_under_paper_executes_live_with_the_switch(self):
        self.lot()
        plan = {"take_profits": [{"at_pct": 10, "sell_share": 1}], "reason": "GTA van na +10 %"}
        exitplan.set_plan(self.lg, MINT, plan, 30)
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())                  # yesterday: only logged ...
        v = mcpapi._plans_for([MINT], {})[MINT]
        self.assertEqual((v["execution"]["mode"], v["execution"]["executes"]), ("paper", False))
        q0 = self.qty()
        done = exitplan.run_once(self.lg, self.mk(1.12), time.time())
        self.assertEqual([(d[0], d[2]) for d in done], [(LU, "tp1")])
        self.assertEqual(self.qty(), q0)
        self.assertEqual(exitplan.events(self.lg)[0]["mode"], "sjena")
        # the owner switch: live without a backtest (it only sells)
        settings.set_flag(self.con, "exit_plan_live", "live", "Jure")
        self.assertIsNone(settings.live_refusal(self.con, "exit_plan_live"))
        exitplan.set_plan(self.lg, MINT, plan, 30)                                       # a fresh plan (tp1 fired)
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), {MINT})                  # the plan owns the exit ...
        self.assertEqual(auto.fast_once(self.lg, self.mk(1.2), LU), [])                  # ... not the default TP
        v = mcpapi._plans_for([MINT], {})[MINT]
        self.assertEqual((v["execution"]["mode"], v["execution"]["executes"]), ("live", True))
        self.assertIn("exit_plan_live", v["execution"]["why"])
        done = exitplan.run_once(self.lg, self.mk(1.12), time.time())
        self.assertEqual([(d[0], d[2]) for d in done], [(LU, "tp1")])
        self.assertEqual(self.qty(), 0)                                                  # sold on the real account
        ev = exitplan.events(self.lg)[0]
        self.assertEqual((ev["mode"], ev["note"]), ("izvršeno", "exit_plan_live"))

    def test_only_grok_positions_and_only_while_grok_autotrade_is_on(self):
        settings.set_flag(self.con, "exit_plan_live", "live", "Jure")
        self.lot()
        self.lot(src="ručno (pravi trade)")                                              # a mixed position
        exitplan.set_plan(self.lg, MINT, {"stop": {"at_pct": -20}}, 30)
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())
        lots = exitplan._lots(self.lg, LU, MINT)
        ex = exitplan.execution(LU, lots)
        self.assertEqual(ex["mode"], "paper")
        self.assertIn("exit_plan_live vrijedi samo", ex["why"])
        self.lg.execute("UPDATE trades SET source='Grok auto (MCP)' WHERE user=? AND token=?", (LU, MINT))
        self.lg.commit()
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), {MINT})
        self.grok.set_on(self.con, False, "Jure")                                        # the kill switch
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())
        self.assertFalse(exitplan.execution(LU, exitplan._lots(self.lg, LU, MINT))["executes"])
        # exit_plans off and the switch on: a Grok position still runs live, everything else is untouched
        self.grok.set_on(self.con, True, "Jure")
        self.mode("off")
        done = exitplan.run_once(self.lg, self.mk(0.75), time.time())
        self.assertEqual([(d[0], d[2]) for d in done], [(LU, "stop")])
        settings.put(self.con, "exit_plans_paused", True)                               # the owner's pause wins
        self.assertEqual(exitplan.in_force_tokens(self.lg, LU), set())

    def test_mcp_answers_say_live_or_paper(self):
        self.lot()
        d, err = mcpapi._tool("set_exit_plan", {"token_address": MINT, "plan": {"stop": {"at_pct": -20}}}, kid="grok")
        self.assertFalse(err, d)
        self.assertEqual(d["execution"][LU]["mode"], "paper")
        self.assertEqual(d["exit_plan_live"], "off")
        self.assertIn("exit_plan_live", settings.FLAGS)
        names_ = list(settings.FLAGS)   # 11.11.: later flags (G19 event_tokens, G20 range_market, G21 proposals) come after it
        self.assertEqual(names_[names_.index("grok_ev_gate") + 1], "exit_plan_live")
        self.assertEqual(settings.FLAGS["exit_plan_live"][0], "G18")
        names = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertIn("exit_plan_live", names["set_exit_plan"]["description"])
        self.assertIn("execution", names["get_portfolio_status"]["description"])


# ---------- 6. range breakouts ---------------------------------------------------------------------------------------------
S = 1e-6


class RangeBreakout(unittest.TestCase):
    def rng(self, pos, price=52.0):
        now = int(time.time())
        z = {"range_low_low": 51.0 * S, "range_low_top": 53.0 * S, "range_high_low": 95.0 * S, "range_high_top": 100.0 * S,
             "range_high": 97.5 * S, "range_low": 52.0 * S,
             "mc": {"range_low_low": 51_000, "range_low_top": 53_000, "range_high_low": 95_000, "range_high_top": 100_000}}
        mm = {"ch_5m": 0.01, "buy_share_5m": 0.6, "vol_ratio": 0.8, "supply": 1e9, "price": price * S, "vol_h1": 30_000}
        return {"ts": now, "mts": now, "active": True, "status": "aktivan", "score": 0.8, "pos_pct": pos, "zones": z,
                "metrics": mm, "symbol": "RNG", "state": {}, "components": {}}

    def test_entry_ready_and_breakout(self):
        ok = rview.one(MINT, self.rng(2.0))
        self.assertEqual((ok["status"], ok["entry_ready"]), ("aktivan", True))
        mid = rview.one(MINT, self.rng(50.0, price=75.0))
        self.assertEqual((mid["status"], mid["entry_ready"]), ("aktivan", False))      # inside, but not at the bottom
        brk = rview.one(MINT, self.rng(138.0, price=118.0))
        self.assertEqual((brk["status"], brk["entry_ready"], brk["range_status"]), ("breakout", False, "aktivan"))
        self.assertIn("probijen gore", brk["entry_now"])
        other = "X" * 43 + "pump"
        rs = {MINT: self.rng(2.0), other: self.rng(138.0, price=118.0)}
        with mock.patch.object(rdata, "read_ranges", lambda **k: rs), \
                mock.patch.object(rview, "positions", lambda tokens=None: {"open": [], "closed": []}), \
                mock.patch.object(rview.gate, "proof", lambda: {"n": 0, "ev_pct": None, "wins": 0}), \
                mock.patch.object(rview.gate, "refusal", lambda: "premalo rundi"):
            d = rview.candidates()
            self.assertEqual([c["token"] for c in d["candidates"]], [MINT])
            self.assertEqual([c["token"] for c in d["breakouts"]], [other])
            b = brief.range_part()
            self.assertEqual([(c["token"], c["entry_ready"]) for c in b["candidates"]], [(MINT, True)])
            self.assertEqual(b["candidates"][0]["range_low_low_mc"], 51_000)
            self.assertEqual(b["breakouts"][0]["status"], "breakout")
            from ui import kandidati
            self.assertEqual(list(kandidati.Sources().ranges(time.time())), [MINT])     # not a range source either


if __name__ == "__main__":
    unittest.main()
