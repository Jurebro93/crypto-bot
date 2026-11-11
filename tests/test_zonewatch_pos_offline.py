"""11.11. (Jure, odluke vlasnika): zonewatch alarms on the REAL account's open positions on their OWN levels (event
position_level: sl_near within 3 % above a stop, sl_hit always, tp_hit and dca_hit once per crossing; the lots' TP/SL,
Smart sell, an exit plan in force, DCA and buy orders), independent of any range; manual positions included, the demo
account never; the payload's position block (lots, qty, average entry, PnL % / USD / SOL); what the executors did
within the second (a sale at a stop or target, a DCA buy, a plan's take profit) alarmed as filled, never twice; and
ONE range_off when rangedca switches off the range of a held token, with each reason. No network.

    python3 -m unittest tests.test_zonewatch_pos_offline
"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from events import store as estore  # noqa: E402
from trade import settings  # noqa: E402
from zonewatch import job, notify, positions, prices, store, view, zones  # noqa: E402

MINT = "PosA111111111111111111111111111111111pump"
MINT2 = "PosB111111111111111111111111111111111pump"
DEMO = "PosD111111111111111111111111111111111pump"
NOW = 1794384000   # 2026-11-11 08:00 UTC
URL = "https://hooks.example.test/v1/routines/rt_SECRETPATH123/trigger"
KEY = "sk-SUPERSECRETKEY-abc123"
TPSL = {"mode": "tpsl", "tp_px": 1.5e-4, "sl_px": 0.8e-4, "tp": "+50%", "sl": "-20%"}   # entry 1e-4 = MC 100k


def _reset_events():
    with estore._LOCK:
        estore._Q.clear()
        if estore._STATE.get("con") is not None:
            try:
                estore._STATE["con"].close()
            except sqlite3.Error:
                pass
        estore._STATE.update(con=None, con_path=None, path=None, exists_at=0.0, exists=False, fails=0)
    estore._TIGHT.update(at=0.0, val=False)


def snap(mc, t, sym="TST"):
    return {"ts": t, "mcap": mc, "price": mc / 1e9, "liq": 40_000.0, "vol_m5": 2000.0, "vol_h1": 30_000.0,
            "buys_m5": 7, "sells_m5": 3, "buys_h1": 60, "sells_h1": 40, "src": "pulse", "symbol": sym}


def pair(tok, mcap, sym="TST"):
    return {"chainId": "solana", "baseToken": {"address": tok, "symbol": sym}, "priceUsd": str(mcap / 1e9),
            "marketCap": mcap, "dexId": "pumpswap", "pairAddress": "Pool" + tok[:6], "liquidity": {"usd": 40_000.0},
            "volume": {"m5": 2000.0, "h1": 30_000.0}, "txns": {"m5": {"buys": 7, "sells": 3}, "h1": {"buys": 60, "sells": 40}},
            "priceChange": {"m5": -1.0}}


class Opener:
    def __init__(self, answers=None):
        self.answers, self.reqs = list(answers or []), []

    def __call__(self, req, timeout):
        self.reqs.append({"headers": {k.lower(): v for k, v in req.header_items()}, "body": req.data})
        a = self.answers.pop(0) if self.answers else 200
        if a >= 300:
            raise urllib.error.HTTPError(req.full_url, a, "x", {}, io.BytesIO(b""))
        return a, {}


class Base(unittest.TestCase):
    def setUp(self):
        from league import store as lstore
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        env = {"ZONEWATCH_DB": os.path.join(d, "zonewatch.db"), "RANGE_DB": os.path.join(d, "range.db"),
               "RANGE_HYPE_DB": os.path.join(d, "hype.db"), "EVENTS_DB": os.path.join(d, "events.db")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("GROKBOT_WEBHOOK_URL", "GROKBOT_WEBHOOK_KEY", "GROKBOT_WEBHOOK_AUTH"):
            os.environ.pop(k, None)
        self._sdb = settings.DB
        settings.DB = os.path.join(d, "trade.db")
        settings._FLAG_CACHE.clear()
        self.tcon = settings.connect()
        self.addCleanup(self._restore)
        self.league = os.path.join(d, "league.db")
        p = mock.patch.object(lstore, "DB", self.league)
        p.start()
        self.addCleanup(p.stop)
        lstore.connect(self.league).close()
        _reset_events()
        self.addCleanup(_reset_events)
        prices._RUG.clear()
        job._SAID.clear()
        self.con = store.connect()
        self.addCleanup(self.con.close)

    def _restore(self):
        self.tcon.close()
        settings.DB = self._sdb
        settings._FLAG_CACHE.clear()

    def flag(self, name, m):
        settings.put(self.tcon, f"flag:{name}", {"mode": m, "since": NOW})
        settings._FLAG_CACHE.clear()

    def lot(self, tok=MINT, user=None, entry_px=1e-4, qty=None, size=50.0, source="ručno (pravi trade)", auto=None,
            auto_state=None, symbol="TST", opened=NOW - 600):
        from league import store as lstore
        c = lstore.connect(self.league)
        cur = c.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, qty, "
                        "source, entry_mcap, auto, auto_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (user or settings.LEAGUE_USER, tok, symbol, opened, "open", size, entry_px, entry_px,
                         qty if qty is not None else size / entry_px, source, entry_px * 1e9,
                         json.dumps(auto) if auto else None, json.dumps(auto_state) if auto_state else None))
        c.commit()
        lid = cur.lastrowid
        c.close()
        return lid

    def league_con(self):
        from league import store as lstore
        c = lstore.connect(self.league)
        self.addCleanup(c.close)
        return c

    def run_at(self, mc, t, mint=MINT, more=None):
        """One position pass at market cap mc for `mint` (and more {mint: mc}): (levels alarmed, debounced, payloads)."""
        pos = job.load_positions(t, log=lambda s: None)
        snaps = {mint: snap(mc, t)}
        for m, v in (more or {}).items():
            snaps[m] = snap(v, t)
        out, deb = job.evaluate_positions(self.con, pos, snaps, t, rug_fn=lambda *a: "ok", uniq_fn=lambda *a: 42)
        return [p["level"] for p in out], deb, out


# ---------------------------------------------------------------------------------------------------------------------
class Levels(Base):
    def test_sl_near_at_3_pct_once_in_30_min_and_sl_hit_always_at_most_once_a_minute(self):
        self.lot(auto=TPSL)                                                     # SL 80k, near band <= 82.4k
        seq = [(100_000, 0, []), (83_000, 30, []), (82_300, 60, ["sl_near"]), (82_000, 90, []),
               (85_000, 120, []),                                               # out of the band (> 82.4k x 1.005)
               (82_300, 150, "deb"),                                            # again within 30 min: held back
               (79_000, 180, ["sl_hit"]), (81_000, 210, []),
               (79_500, 220, "deb"),                                            # 40 s after the last sl_hit
               (81_000, 230, []), (79_500, 250, ["sl_hit"]),                    # 70 s later: always
               (90_000, 2000, []), (82_000, 2030, ["sl_near"])]                 # 30 min after the first sl_near
        for mc, dt_, want in seq:
            got, deb, _ = self.run_at(mc, NOW + dt_)
            if want == "deb":
                self.assertEqual((got, deb), ([], 1), (mc, dt_))
            else:
                self.assertEqual(got, want, (mc, dt_))

    def test_a_drop_straight_through_the_stop_is_one_sl_hit_and_first_sight_alarms(self):
        self.lot(auto=TPSL)
        self.assertEqual(self.run_at(100_000, NOW)[0], [])
        self.assertEqual(self.run_at(78_000, NOW + 30)[0], ["sl_hit"])          # no sl_near in the same pass
        # a position first seen already near its stop / under it: one alarm (initial)
        self.lot(tok=MINT2, auto=TPSL)
        got, _, out = self.run_at(100_000, NOW + 60, more={MINT2: 81_500})
        self.assertEqual(got, ["sl_near"])
        self.assertTrue(out[0]["initial"])
        self.assertEqual(out[0]["mint"], MINT2)

    def test_tp_hit_and_dca_hit_once_per_crossing_with_hysteresis(self):
        self.lot(auto=dict(TPSL, sl_px=0.7e-4))                                 # TP 150k, SL 70k
        settings.put(self.tcon, "dca_orders", [{"id": 7, "token": MINT, "sym": "TST", "mc": 90_000.0, "sol": 0.1,
                                                "txt": "$90k", "made": NOW}])
        seq = [(120_000, 0, []), (151_000, 30, ["tp_hit"]), (149_500, 60, []),   # 149.5k: inside the 0.5 % hysteresis
               (152_000, 90, []), (148_000, 120, []), (151_000, 150, ["tp_hit"]),
               (100_000, 180, []), (89_000, 210, ["dca_hit"]), (89_500, 240, []), (92_000, 270, []),
               (89_000, 330, ["dca_hit"])]
        for mc, dt_, want in seq:
            self.assertEqual(self.run_at(mc, NOW + dt_)[0], want, (mc, dt_))
        # a DCA order first seen above the price (it never crossed): no alarm
        self.lot(tok=MINT2, auto=dict(TPSL, sl_px=0.5e-4))
        settings.put(self.tcon, "dca_orders", [{"id": 8, "token": MINT2, "sym": "B", "mc": 90_000.0, "sol": 0.1}])
        self.assertEqual(self.run_at(100_000, NOW + 400, more={MINT2: 85_000})[0], [])

    def test_no_range_needed_and_dexscreener_within_the_cap(self):
        """No range.db at all: a full pass prices the position (one DexScreener batch) and alarms on its own stop."""
        self.flag("zonewatch", "shadow")
        self.lot(auto=TPSL)
        asked, op = [], Opener()
        res = job.pass_once(now=NOW, fetch=lambda toks: asked.append(list(toks)) or [pair(MINT, 82_000)],
                            cfg=notify.Config(URL, KEY), opener=op, sleep=lambda s: None, log=lambda s: None,
                            rug_fn=lambda *a: "ok", uniq_fn=lambda *a: None, flag="shadow")
        self.assertFalse(os.path.exists(os.environ["RANGE_DB"]))
        self.assertEqual(asked, [[MINT]])
        self.assertEqual((res["positions"], res["position_alerts"], res["zones"]), (1, 1, 0))
        (body,) = [b for b in (json.loads(r["body"]) for r in op.reqs) if b["event"] != "test"]   # + the probe
        self.assertEqual((body["event"], body["level"], body["source"]), ("position_level", "sl_near", "position"))
        self.assertLessEqual(store.day_used(self.con, "dex", NOW), prices.MAX_REQ_PASS)
        # a second pass 30 s later with a fresh number from the stored snapshot: no request, nothing new
        store.kv_put(self.con, "cold", {})
        self.con.execute("UPDATE px SET ts=?", (NOW + 25,))
        self.con.commit()
        res = job.pass_once(now=NOW + 30, fetch=lambda toks: self.fail("fetched"), cfg=notify.Config(URL, KEY),
                            opener=op, sleep=lambda s: None, log=lambda s: None, rug_fn=lambda *a: "ok",
                            uniq_fn=lambda *a: None, flag="shadow")
        self.assertEqual((res["asked"], res["position_alerts"]), (0, 0))

    def test_smart_sell_levels(self):
        cfg = {"sl": -0.3, "tp": [[0.5, 0.5], [1.0, 0.25]], "trail": 0.2, "trail_after": 0.4, "fee": 0.01}
        st = {"cfg": cfg, "pos": {"entry_px": 1e-4, "tp_done": 1, "peak": 0.6, "open": True, "left": 0.5,
                                  "opened_ts": NOW - 600}}
        lid = self.lot(auto={"mode": "smart"}, auto_state=st)
        (p,) = positions.load(NOW)
        lv = {x["name"]: x for x in p["levels"]}
        self.assertEqual(set(lv), {"smart_trail", "smart_tp"})                   # tp_done 1: no first stop any more
        self.assertAlmostEqual(lv["smart_trail"]["price"], 1e-4 * 1.6 * 0.8)
        self.assertTrue(lv["smart_trail"]["trailing"])
        self.assertAlmostEqual(lv["smart_tp"]["price"], 2e-4)
        self.assertEqual(lv["smart_tp"]["key"], f"smart_tp:{lid}")
        # before the first take profit: Smart sell's own stop at -30 %
        c = self.league_con()
        c.execute("UPDATE trades SET auto_state=? WHERE id=?", (json.dumps({"cfg": cfg, "pos": dict(st["pos"], tp_done=0,
                                                                                                     peak=0.1)}), lid))
        c.commit()
        (p,) = positions.load(NOW)
        self.assertEqual({x["name"]: round(x["mcap"]) for x in p["levels"]}, {"smart_sl": 70_000, "smart_tp": 150_000})


# ---------------------------------------------------------------------------------------------------------------------
class PlanWins(Base):
    def plan(self, stop_px=0.9e-4):
        from league import exitplan
        c = self.league_con()
        exitplan.ensure(c)
        plan = {"take_profits": [{"kind": "pct", "v": 50.0, "sell_share": 0.5}, {"kind": "mc", "v": 200_000.0,
                                                                                 "sell_share": 0.5}],
                "trailing": {"activate_pct": 30.0, "trail_pct": 20.0}, "stop": {"kind": "pct", "v": -10.0}, "reason": "x"}
        u = settings.LEAGUE_USER
        state = {"stop_px": {u: stop_px}, "sold": {u: 0.5}, "fired": {u: [0]}, "peak_px": {u: 1.4e-4},
                 "trail_peak_px": {u: 1.4e-4}, "base_qty": {u: 500_000}}
        cur = c.execute("INSERT INTO exit_plans (token, created_ts, client, reason, plan, status, state) VALUES "
                        "(?,?,?,?,?,?,?)", (MINT, NOW - 300, "mcp", "x", json.dumps(plan), "active", json.dumps(state)))
        c.commit()
        return cur.lastrowid

    def test_plan_in_force_replaces_the_lots_own_levels(self):
        self.lot(auto=TPSL)
        pid = self.plan()
        self.flag("exit_plans", "live")
        (p,) = positions.load(NOW)
        self.assertEqual((p["plan_id"], p["plan_in_force"]), (pid, True))
        lv = {x["key"]: x for x in p["levels"]}
        self.assertEqual(set(lv), {"plan_stop", "plan_tp2", "plan_trailing"})   # tp1 fired; no lot sl / tp
        self.assertEqual(round(lv["plan_stop"]["mcap"]), 90_000)
        self.assertEqual(round(lv["plan_tp2"]["mcap"]), 200_000)
        self.assertEqual(round(lv["plan_trailing"]["mcap"]), 112_000)           # peak 140k x (1 - 20 %)
        # the trailing stop alarms as a stop: near at <= 112k x 1.03, hit at <= 112k
        got, _, out = self.run_at(115_000, NOW)
        self.assertEqual(got, ["sl_near"])
        self.assertEqual((out[0]["level_key"], out[0]["level_kind"], out[0]["level_src"]),
                         ("plan_trailing", "trailing", "plan"))
        self.assertEqual(self.run_at(111_000, NOW + 30)[0], ["sl_hit"])
        # exit_plans off: the plan does not sell, so the lots' own SL / TP are watched again
        self.flag("exit_plans", "off")
        (p,) = positions.load(NOW + 60)
        self.assertEqual((p["plan_id"], p["plan_in_force"]), (pid, False))
        self.assertEqual({x["name"] for x in p["levels"]}, {"sl", "tp"})
        # paper: the plan runs on the demo account only, the real account keeps its own levels
        self.flag("exit_plans", "paper")
        (p,) = positions.load(NOW + 60)
        self.assertFalse(p["plan_in_force"])


# ---------------------------------------------------------------------------------------------------------------------
class WhosePositions(Base):
    def test_manual_grok_and_approved_included_demo_excluded(self):
        self.lot(source="ručno (pravi trade)", auto=TPSL)
        self.lot(source="Grok auto (MCP)", auto=TPSL)
        self.lot(tok=MINT2, source="ručno: Grok odobreno (MCP)", auto=TPSL)
        self.lot(tok=DEMO, user=settings.PAPER_USER, source="paper", auto=TPSL)  # the demo account
        pos = {p["mint"]: p for p in positions.load(NOW)}
        self.assertEqual(set(pos), {MINT, MINT2})
        self.assertEqual(pos[MINT]["sources"], ["Grok auto", "ručno"])
        self.assertEqual(pos[MINT2]["sources"], ["odobreno"])
        self.assertEqual(len([x for x in pos[MINT]["levels"] if x["kind"] == "sl"]), 1)   # the same stop: one level
        got, _, out = self.run_at(100_000, NOW, more={DEMO: 79_000, MINT2: 100_000})
        got, _, out = self.run_at(79_000, NOW + 30, more={DEMO: 70_000, MINT2: 79_000})
        self.assertEqual(sorted((p["mint"], p["level"]) for p in out), [(MINT, "sl_hit"), (MINT2, "sl_hit")])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM alerts WHERE mint=?", (DEMO,)).fetchone()[0], 0)
        # a token no longer held: its levels' states go, a new position starts afresh
        c = self.league_con()
        c.execute("UPDATE trades SET status='closed' WHERE token=?", (MINT2,))
        c.commit()
        self.run_at(80_000, NOW + 60)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM zone_state WHERE mint=? AND source='position'",
                                          (MINT2,)).fetchone()[0], 0)


# ---------------------------------------------------------------------------------------------------------------------
class Payload(Base):
    def test_owner_fields_level_and_position_block_with_pnl(self):
        from trade import executor
        l1 = self.lot(entry_px=1e-4, size=50.0, auto=dict(TPSL, sl_px=0.7e-4))
        l2 = self.lot(entry_px=0.8e-4, size=50.0, auto=dict(TPSL, sl_px=0.7e-4), source="Grok auto (MCP)")
        ec = executor.connect(settings.DB)
        ec.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, sol_in, qty_raw, qty_left, league_id) "
                   "VALUES (?,?,?,?,?,?,?,?,?)", (MINT, "TST", NOW - 600, "live", "open", 0.3, 1000, 1000, l1))
        ec.execute("CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, sol REAL, usdc REAL, tokens_sol REAL, "
                   "sol_usd REAL, usd_eur REAL, flow_sol REAL DEFAULT 0, src TEXT DEFAULT 'live')")
        ec.execute("INSERT INTO equity (ts, sol_usd) VALUES (?, ?)", (NOW - 60, 200.0))
        ec.commit()
        ec.close()
        self.run_at(100_000, NOW)
        got, _, out = self.run_at(72_000, NOW + 30)
        self.assertEqual(got, ["sl_near"])
        p = out[0]
        for k in notify.OWNER_FIELDS + ("id", "event"):
            self.assertIn(k, p)
        self.assertEqual((p["event"], p["level"], p["zone_type"], p["zone_lo"], p["zone_hi"], p["source"]),
                         ("position_level", "sl_near", "position_sl", 70_000.0, 70_000.0, "position"))
        self.assertEqual((p["level_mcap"], p["level_key"], p["level_name"], p["level_kind"], p["level_src"]),
                         (70_000.0, f"sl:{l1}", "sl", "sl", "auto"))
        self.assertAlmostEqual(p["level_price"], 0.7e-4)
        self.assertEqual((p["mcap"], p["rug_risk"], p["uniq_traders_1h"], p["buy_share_5m"]), (72_000, "ok", 42, 0.7))
        self.assertEqual(p["distance_pct"], -2.78)                               # the stop 2.78 % under the price
        b = p["position"]
        self.assertEqual((b["lots"], b["lot_ids"], b["account"], b["sources"]),
                         (2, [l1, l2], settings.LEAGUE_USER, ["Grok auto", "ručno"]))
        self.assertAlmostEqual(b["qty"], 1_125_000)
        self.assertAlmostEqual(b["avg_entry_price"], 100 / 1_125_000)            # $100 for 1.125M tokens
        self.assertEqual(round(b["avg_entry_mcap"]), 88_889)
        self.assertEqual(b["pnl_pct"], -19.0)                                    # 72k vs 88.9k
        self.assertEqual(b["pnl_usd"], -19.0)                                    # 1.125M x 72e-6 - $100
        self.assertEqual(b["pnl_sol"], -0.109)                                   # 0.3 x -28 % + (-$5 / $200)
        self.assertEqual(b["pnl_sol_src"], "mješovito")
        # the stored body is what is posted, and get_armed_zones lists the position with its levels
        row = self.con.execute("SELECT event, zone_type, source, payload FROM alerts WHERE id=?", (p["id"],)).fetchone()
        self.assertEqual(row[:3], ("position_level", "position_sl", "position"))
        self.assertEqual(json.loads(row[3])["position"]["pnl_sol"], -0.109)
        self.con.execute("INSERT OR REPLACE INTO px VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (MINT, NOW + 40, 72e-6, 72_000, 40_000, 0, 0, 0, 0, 0, 0, "TST", "dexscreener"))
        self.con.commit()
        g = view.armed_zones(now=NOW + 45)
        (gp,) = g["positions"]
        self.assertEqual((gp["mint"], gp["mcap_now"], gp["position"]["pnl_pct"]), (MINT, 72_000, -19.0))
        lv = {x["level_key"]: x for x in gp["levels"]}
        self.assertEqual((lv[f"sl:{l1}"]["state"], lv[f"sl:{l1}"]["near"], lv[f"sl:{l1}"]["distance_pct"]),
                         ("not_hit", True, -2.78))
        self.assertIn("sl_near", lv[f"sl:{l1}"]["last_alert"])
        self.assertIn("demo", g["positions_note"])
        b = view.brief_part(NOW + 45)
        self.assertEqual((b["positions"]["positions"], b["position_alerts_24h"], b["range_off_24h"]),
                         (1, {"sl_near": 1}, 0))
        self.assertEqual(b["positions"]["levels_by_kind"], {"sl": 1, "tp": 1})   # the lots share stop and target

    def test_delivery_stops_first_and_no_secret_in_the_body(self):
        self.lot(auto=TPSL)
        self.run_at(100_000, NOW)
        notify.post_alert({"mint": MINT2, "zone_type": "dca", "event": "zone_enter", "ts": NOW}, con=self.con,
                          cfg=notify.Config(URL, KEY), flag="off")   # an older alarm (stored, flag off)
        self.con.execute("UPDATE alerts SET status='pending'")
        self.run_at(79_000, NOW + 30)
        op = Opener()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            job.deliver_pending(self.con, NOW + 31, notify.Config(URL, KEY), "shadow", op, lambda s: None)
        evs = [json.loads(r["body"])["event"] for r in op.reqs]
        self.assertEqual(evs, ["position_level", "zone_enter"])                  # the stop first
        for r in op.reqs:
            self.assertNotIn(KEY.encode(), r["body"])
        self.assertNotIn("SECRETPATH", out.getvalue())


# ---------------------------------------------------------------------------------------------------------------------
class Fills(Base):
    def test_a_sale_at_the_stop_between_passes_is_sl_hit_filled(self):
        from league import store as lstore
        lid = self.lot(auto=TPSL)
        self.assertEqual(self.run_at(100_000, NOW)[0], [])
        c = self.league_con()
        lstore.sell(c, settings.LEAGUE_USER, lid, 0.79e-4, 40_000, "auto SL -20%", mcap=79_000, exit_rule="sl")
        got, _, out = self.run_at(85_000, NOW + 30)   # the position is gone before a pass saw the price at the stop
        self.assertEqual(got, ["sl_hit"])
        p = out[0]
        self.assertEqual((p["filled"], p["level_key"], p["level_mcap"], p["mcap"]), (True, f"sl:{lid}", 80_000.0, 79_000))
        self.assertEqual((p["fill"]["ok"], p["fill"]["lots"], p["position"]["lots"]), (True, [lid], 1))
        self.assertEqual(p["position"]["pnl_pct"], -21.0)                         # at the fill price
        self.assertEqual(self.run_at(85_000, NOW + 60)[0], [])                     # once

    def test_a_crossing_then_its_sale_is_one_alarm(self):
        from league import store as lstore
        lid = self.lot(auto=TPSL)
        self.run_at(100_000, NOW)
        self.assertEqual(self.run_at(79_500, NOW + 30)[0], ["sl_hit"])
        lstore.sell(self.league_con(), settings.LEAGUE_USER, lid, 0.79e-4, 40_000, "auto SL -20%", exit_rule="sl")
        self.assertEqual(self.run_at(79_000, NOW + 60)[:2], ([], 1))

    def test_dca_buy_plan_take_profit_and_smart_take_profit(self):
        from league import exitplan
        cfg = {"sl": -0.3, "tp": [[0.5, 0.5], [1.0, 0.25]], "trail": 0.2, "trail_after": 0.4, "fee": 0.01}
        st = {"cfg": cfg, "pos": {"entry_px": 1e-4, "tp_done": 0, "peak": 0.1, "open": True, "left": 1.0}}
        self.lot(auto=TPSL)
        smart = self.lot(tok=MINT2, auto={"mode": "smart"}, auto_state=st)
        settings.put(self.tcon, "dca_orders", [{"id": 7, "token": MINT, "sym": "TST", "mc": 90_000.0, "sol": 0.1},
                                               {"id": 9, "token": MINT, "sym": "TST", "mc": 85_000.0, "sol": 0.1}])
        c = self.league_con()
        exitplan.ensure(c)
        old = (NOW - 99, 1, settings.LEAGUE_USER, MINT, "tp1", 1.5e-4, 150_000, 0.5, 10.0, "izvršeno", 0, "")
        c.execute("INSERT INTO exit_events (ts, plan_id, user, token, trigger, price, mcap, share, pnl_usd, mode, stale, "
                  "note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", old)                  # before the first pass: no backlog
        c.commit()
        settings.put(self.tcon, "dca_log", [{"ts": NOW - 50, "token": MINT, "text": "DCA TST: dokupljeno 0.1 SOL na MC "
                                                                                    "$88,000 (granica $90,000)"}])
        self.assertEqual(self.run_at(100_000, NOW, more={MINT2: 120_000})[0], [])
        # the executors act within the second: DCA order 7 bought, a plan take profit, Smart sell's first target
        settings.put(self.tcon, "dca_orders", [{"id": 9, "token": MINT, "sym": "TST", "mc": 85_000.0, "sol": 0.1}])
        settings.put(self.tcon, "dca_log", [{"ts": NOW + 10, "token": MINT, "text": "DCA TST: dokupljeno 0.1 SOL na MC "
                                                                                     "$89,500 (granica $90,000)"},
                                            {"ts": NOW - 50, "token": MINT, "text": "staro"}])
        c.execute("INSERT INTO exit_events (ts, plan_id, user, token, trigger, price, mcap, share, pnl_usd, mode, stale, "
                  "note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (NOW + 12, 1, settings.LEAGUE_USER, MINT, "tp2", 1.6e-4, 160_000, 0.5, 10.0, "izvršeno", 0, ""))
        c.execute("INSERT INTO exit_events (ts, plan_id, user, token, trigger, price, mcap, share, pnl_usd, mode, stale, "
                  "note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (NOW + 13, 1, settings.LEAGUE_USER, MINT, "stop", 0.9e-4, 90_000, 0.5, None, "sjena", 0, ""))
        c.execute("UPDATE trades SET auto_state=? WHERE id=?",
                  (json.dumps({"cfg": cfg, "pos": dict(st["pos"], tp_done=1, peak=0.55, left=0.5)}), smart))
        c.commit()
        got, _, out = self.run_at(100_000, NOW + 30, more={MINT2: 140_000})
        by = {(p["mint"], p["level"], p["level_key"]): p for p in out}
        self.assertEqual(set(by), {(MINT, "dca_hit", "dca:7"), (MINT, "tp_hit", "plan_tp2"),
                                   (MINT2, "tp_hit", f"smart_tp:{smart}")})     # the shadow stop is not a sale
        d = by[(MINT, "dca_hit", "dca:7")]
        self.assertEqual((d["filled"], d["level_mcap"], d["mcap"], d["fill"]["ok"]), (True, 90_000.0, 89_500, True))
        self.assertEqual(by[(MINT, "tp_hit", "plan_tp2")]["mcap"], 160_000)
        self.assertEqual(round(by[(MINT2, "tp_hit", f"smart_tp:{smart}")]["level_mcap"]), 150_000)
        self.assertEqual(self.run_at(100_000, NOW + 60, more={MINT2: 140_000})[0], [])   # each once


# ---------------------------------------------------------------------------------------------------------------------
class RangeOff(Base):
    def save(self, tok, t, active=True, status="aktivan", why=""):
        from rangedca import data
        rc = data.connect()
        res = {"ts": t, "status": status, "active": active, "why": why, "score": 0.8, "pos_pct": 40.0, "span_h": 9.5,
               "zones": {"range_low_low": 60e-6, "range_low_top": 66e-6, "range_high_low": 95e-6, "range_high_top": 100e-6,
                         "range_low": 63e-6, "range_high": 97e-6,
                         "mc": {"range_low_low": 60_000, "range_low_top": 66_000, "range_high_low": 95_000,
                                "range_high_top": 100_000}},
               "metrics": {"price": 80e-6, "mcap": 80_000, "supply": 1e9}, "source": "signal"}
        data.save_range(rc, tok, res, {}, tok[:4])
        rc.commit()
        rc.close()

    def step(self, t):
        logs = []
        with mock.patch.object(store, "_entry_ready", lambda now: set()):
            store.sync_range(self.con, t, log=logs.append)
        pos = job.load_positions(t, log=logs.append)
        out = job.range_off(self.con, pos, {MINT: snap(80_000, t)}, t, rug_fn=lambda *a: "ok", uniq_fn=lambda *a: None,
                            log=logs.append)
        return out

    def test_one_alarm_per_deactivation_with_each_reason(self):
        self.lot()                                                              # held, no TP/SL of its own
        cases = [("probijen gore", "cijena iznad range_high_top × 1,15", "break_up"),
                 ("probijen dolje", "cijena ispod range_low_low × 0,92", "break_down"),
                 ("slab volumen", "volumen 1 h $900, treba $5,000", "weak_volume"),
                 ("isključen", "volumen zadnjeg sata pao ispod pola prosjeka 6 h", "weak_volume"),
                 ("isključen", "dva niža dna zaredom (svako ispod prethodnog × 0,97)", "break_down"),
                 ("isključen", "raspon probijen dolje 2 puta u 24 h", "break_down"),
                 ("nema raspona", "manje od 2 vrha unutar ±8 %", "other")]
        t = NOW
        for i, (status, why, key) in enumerate(cases):
            self.save(MINT, t)
            self.assertEqual(self.step(t + 30), [], status)                     # active: zones, no alarm
            self.save(MINT, t + 300, active=False, status=status, why=why)
            out = self.step(t + 330)
            self.assertEqual(len(out), 1, status)
            p = out[0]
            self.assertEqual((p["event"], p["reason_key"], p["reason"], p["range_status"], p["mint"]),
                             ("range_off", key, f"{status}: {why}", status, MINT))
            self.assertEqual((p["zone_version"], p["computed_ts"], p["window_h"]), (i + 1, t, 9.5))
            self.assertEqual((p["zone_lo"], p["zone_hi"], p["last_zones"]["stop"]), (60_000.0, 100_000.0, [51_000.0] * 2))
            self.assertEqual((p["position"]["account"], p["position"]["lots"]), (settings.LEAGUE_USER, 1))
            for k in notify.OWNER_FIELDS:
                self.assertIn(k, p)
            self.assertEqual(self.step(t + 360), [], status)                    # once per deactivation
            self.assertEqual(self.step(t + 700), [], status)
            t += 1000                                                           # active again: re-armed
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM alerts WHERE event='range_off'").fetchone()[0], len(cases))
        self.assertEqual(view.brief_part(t)["range_off_24h"], len(cases))

    def test_not_held_or_closed_before_or_still_active_is_no_alarm(self):
        lid = self.lot()
        self.save(MINT2, NOW)                                                   # a range zone of a token not held
        store.upsert(self.con, MINT2, "bottom", 60_000, 66_000, "x", "range", "range", NOW + 900, NOW)
        self.save(MINT, NOW)
        self.step(NOW + 30)
        self.save(MINT2, NOW + 300, active=False, status="probijen gore", why="x")
        from league import store as lstore
        lstore.sell(self.league_con(), settings.LEAGUE_USER, lid, 0.8e-4, 40_000, "ručno")   # sold first
        self.save(MINT, NOW + 300, active=False, status="probijen dolje", why="x")
        self.assertEqual(self.step(NOW + 330), [])
        self.assertEqual(job.range_reason("raspon bez zona u MC iznad 30k"), (None, "raspon bez zona u MC iznad 30k"))
        self.assertEqual(job.range_reason("raspon zastario: zadnji izračun prije 20 min (probijen gore)")[0], "other")


# ---------------------------------------------------------------------------------------------------------------------
class Pure(unittest.TestCase):
    def test_level_zones_and_debounce(self):
        self.assertEqual(zones.SL_NEAR, 0.03)
        (sl, f1, e1), (near, f2, e2) = zones.level_zones("sl", 80_000)
        self.assertEqual((sl["hi"], e1, f1, round(near["hi"]), e2, f2), (80_000, "sl_hit", True, 82_400, "sl_near", True))
        ((tp, f3, e3),) = zones.level_zones("tp", 150_000)
        self.assertEqual((tp["zone_type"], e3, f3), ("top", "tp_hit", False))
        self.assertEqual(zones.level_debounce_s("sl_near"), 1800)
        self.assertEqual([zones.level_debounce_s(x) for x in ("sl_hit", "tp_hit", "dca_hit")], [60, 60, 60])
        # tp / dca: no alarm on the first observation (no crossing), a stop: yes
        self.assertFalse(zones.level_step(tp, None, 151_000, NOW, False)[1])
        self.assertTrue(zones.level_step(sl, None, 79_000, NOW, True)[1])
        self.assertIn("position_level", zones.EVENTS)
        self.assertIn("range_off", zones.EVENTS)


if __name__ == "__main__":
    unittest.main()
