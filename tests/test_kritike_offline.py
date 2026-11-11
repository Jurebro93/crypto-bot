"""Grok's accepted critiques the bot could not apply by itself (11.11., notes #54 #74 #77 #85 #92 #96 #105), offline:

  1  get_market_signals: rug_verdict + runup_x on every row, risk / hard and 4x+ rows hidden (include_hidden lists
     them); the scanner's own run-up cap from its first sighting as bonded (scan/market.runup_why)
  2  topcheck: bot / wash volume (DAKITTY-like and DacityCoin-2-like data) is 'oprez' or worse with the reason
  3  wallets/hygiene: idle 24 h+, bot / sniper / bundler and bot-like wallets leave the copy and webhook lists
  4  ui/zivo: a live row 4x+ over the first call is marked not a pick

    python3 -m unittest tests.test_kritike_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan import market, store as sstore  # noqa: E402
from topcheck import safety  # noqa: E402
from ui import kandidati, mcpapi, zivo  # noqa: E402
from wallets import hygiene, store as wstore  # noqa: E402

NOW = 1_795_000_000
H, D = 3600, 86400
X, Y, Z = ("4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi", "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
           "CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8")


def live(mcap, ch_h1=5.0):
    return {"price": 0.001, "mcap": float(mcap), "liq": 60_000.0, "vol_h1": 20_000.0, "txns_h1": 200, "buys_h1": 120,
            "ch_m5": 1.0, "ch_h1": ch_h1, "ch_h24": 30.0, "vol_m5": 2000.0, "txns_m5": 12}


# ---------- 1. signal feed hygiene ----------------------------------------------------------------------------------

class SignalHygiene(unittest.TestCase):
    """X fails the rug filter (VISOK RIZIK), Y is 6x over its first call, Z is clean."""

    def setUp(self):
        zivo._FIRST.clear()
        rug = {X: {"verdict": "VISOK RIZIK", "score": 38, "data": {"flags": ["snajperi drže 30 %"]}}}
        self.patches = [
            mock.patch("ui.mcpapi._rug_inputs", return_value=(({}, rug), frozenset())),
            mock.patch("ui.zivo.first_calls", return_value={Y: (NOW - 2 * H, 50_000.0)}),
            mock.patch("rugfilter.collapse.peaks", return_value={}),
            mock.patch("ui.mcpapi._group_signals", return_value=[]),
            mock.patch("scan.store.on", return_value=False),
            mock.patch("ui.pravitrade.gather_callers", return_value=[
                (X, [("kola", "x", NOW - 300)], NOW - 300, NOW - 300, "XXX", live(200_000)),
                (Y, [("kolb", "x", NOW - 200)], NOW - 200, NOW - 200, "YYY", live(300_000)),
                (Z, [("kolc", "x", NOW - 100)], NOW - 100, NOW - 100, "ZZZ", live(90_000))])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_rug_and_late_rows_are_hidden_by_default(self):
        d = mcpapi.signals(NOW)
        self.assertEqual([r["token"] for r in d["signals"]], [Z])
        self.assertEqual(d["hidden_count"], 2)
        self.assertNotIn("hidden", d)
        z = d["signals"][0]
        for k in ("rug_verdict", "rug_reasons", "runup_x", "runup_from", "first_signal_mcap_usd"):
            self.assertIn(k, z)
        self.assertEqual(z["runup_x"], 1.05)                                   # no first call: 1 + the 1 h change
        self.assertIn("1 h", z["runup_from"])

    def test_include_hidden_lists_them_with_the_reason(self):
        d = mcpapi.signals(NOW, include_hidden=True)
        hid = {r["token"]: r for r in d["hidden"]}
        self.assertEqual(set(hid), {X, Y})
        self.assertEqual(hid[X]["rug_verdict"], "risk")
        self.assertIn("rug filter: visok rizik", hid[X]["hidden_reasons"][0])
        self.assertEqual((hid[Y]["runup_x"], hid[Y]["first_signal_mcap_usd"]), (6.0, 50_000))
        self.assertIn("kasno: već 6.0× (MC prvog signala; granica 4×)", hid[Y]["hidden_reasons"][0])
        code, body = mcpapi.answer("/api/mcp/signals", {"include_hidden": "true"})
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(body)["hidden"]), 2)
        code, body = mcpapi.answer("/api/mcp/signals", {})
        self.assertNotIn("hidden", json.loads(body))
        d, err = mcpapi._tool("get_market_signals", {"include_hidden": True})
        self.assertFalse(err)
        self.assertEqual(len(d["hidden"]), 2)
        schema = {t["name"]: t for t in mcpapi.TOOLS}["get_market_signals"]["inputSchema"]["properties"]
        self.assertEqual(schema["include_hidden"]["type"], "boolean")

    def test_a_broken_read_never_hides_a_row(self):
        with mock.patch("ui.kandidati.rug_view", side_effect=RuntimeError("x")):
            d = mcpapi.signals(NOW)
        self.assertEqual(len(d["signals"]), 3)
        self.assertIsNone(d["signals"][0]["rug_verdict"])

    def test_the_scanners_first_bonded_sighting_counts_as_the_first_signal(self):
        rows = [{"token": Z, "market": mcpapi._market_row(live(500_000))}]
        vis, hid = mcpapi._hygiene(rows, NOW, {Z: {"mcap_first": 100_000, "mcap_first_ts": NOW - 3 * H}}, cached=False)
        self.assertEqual((vis, hid[0]["runup_x"]), ([], 5.0))
        old = mcpapi._hygiene([{"token": Z, "market": mcpapi._market_row(live(500_000))}], NOW,
                              {Z: {"mcap_first": 100_000, "mcap_first_ts": NOW - 2 * D}}, cached=False)
        self.assertEqual(len(old[0]), 1)                                       # an anchor older than 24 h is no signal

    def test_the_same_cap_everywhere(self):
        self.assertEqual(mcpapi.RUNUP_HIDE_X, kandidati.RUNUP_MAX_X)
        self.assertEqual(zivo.RUNUP_MAX_X, kandidati.RUNUP_MAX_X)
        self.assertEqual(sstore.DEFAULT["runup_max_x"], kandidati.RUNUP_MAX_X)


class ScannerRunupCap(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "scan.db")
        self.con = sstore.connect(self.path)
        self.cfg = sstore.config()
        self.con.execute("INSERT INTO cand (token, first_seen, last_seen, checked_ts) VALUES (?,?,?,?)",
                         (X, NOW - 5 * H, NOW - 5 * H, NOW - 5 * H))

    def tearDown(self):
        self.con.close()

    def m(self, mcap, curve=False):
        return {"token": X, "symbol": "XXX", "price": 0.001, "mcap": mcap, "liq": mcap * 0.15, "vol_h1": 80_000,
                "txns_h1": 400, "buys_h1": 250, "curve": curve, "src": "dexscreener"}

    def test_an_old_scan_db_gets_the_columns(self):
        p = os.path.join(tempfile.mkdtemp(), "old.db")
        c = sqlite3.connect(p)
        c.executescript(sstore.SCHEMA)                                         # the tables as they shipped before 11.11.
        self.assertNotIn("mcap_first", {r[1] for r in c.execute("PRAGMA table_info(cand)")})
        c.close()
        c = sstore.connect(p)
        cols = {r[1] for r in c.execute("PRAGMA table_info(cand)")}
        c.close()
        self.assertTrue({"mcap_first", "mcap_first_ts"} <= cols)

    def test_anchor_on_the_first_bonded_sighting_only(self):
        self.assertFalse(market.anchor_first(self.con, X, self.m(15_000, True), "final_stretch", NOW - 4 * H, self.cfg))
        self.assertTrue(market.anchor_first(self.con, X, self.m(70_000), "migrated", NOW - 3 * H, self.cfg))
        self.assertFalse(market.anchor_first(self.con, X, self.m(90_000), "migrated", NOW - 2 * H, self.cfg))
        self.assertEqual(market.first_seen(self.con, X, NOW, self.cfg), (70_000.0, NOW - 3 * H))
        self.assertIsNone(market.first_seen(self.con, X, NOW + 2 * D, self.cfg))   # outside the 24 h window
        self.assertTrue(market.anchor_first(self.con, X, self.m(400_000), "migrated", NOW + 2 * D, self.cfg))

    @mock.patch("league.copy._rugged", return_value=None)
    def test_4x_over_the_first_sighting_is_a_tag_not_a_fail(self, _r):
        # 11.11. (owner's rule B): the scanner marks a 4x+ run-up, the decision applies P x 0.7 / size x 0.5
        market.anchor_first(self.con, X, self.m(70_000), "migrated", NOW - 3 * H, self.cfg)
        ctx = market.Ctx(self.con, None, self.cfg, NOW, {})
        ctx.trades = mock.Mock(return_value=[])
        ctx.facts = mock.Mock(return_value=None)
        res = market.check(self.m(300_000), self.cfg, ctx, has_signal=True)
        self.assertNotIn("kasno", res["why"] or "")
        self.assertNotIn("kasno", res["why_sig"] or "")                       # a caller signal is not refused either
        self.assertIn("runup", res.get("tags") or [])
        self.assertTrue(any("kasno: već 4.3× od prvog viđenja skenera" in r for r in res["reasons"]))
        res = market.check(self.m(250_000), self.cfg, ctx, has_signal=True)    # 3.6x: no mark
        self.assertNotIn("runup", res.get("tags") or [])
        off = dict(self.cfg, runup_max_x=0)
        self.assertIsNone(market.runup_why(self.m(900_000), "migrated", off, ctx))


# ---------- 2. topcheck: bot / wash volume --------------------------------------------------------------------------

def pair(b1, s1, v1, b24, s24, v24, liq=30_000.0):
    return {"txns": {"h1": {"buys": b1, "sells": s1}, "h24": {"buys": b24, "sells": s24}},
            "volume": {"h1": v1, "h24": v24}, "liquidity": {"usd": liq}, "priceChange": {"h1": 4.0}}


def clean_rc():
    return {"mint_auth": None, "freeze_auth": None, "rugged": False, "launchpad": None, "lp_locked": 100.0,
            "has_market": True, "top10": 18.0, "insiders": 0, "dev_pct": 0.0, "creator_tokens": 0, "holders": 900,
            "fee": 0, "perm_delegate": False, "non_transferable": False, "transfer_hook": False,
            "frozen_default": False, "danger": [], "decimals": 6, "supply": 1e15}


def wash_trades(wallets=8, rounds=20):
    """DAKITTY-like: a few wallets buy and sell the same 0.5 SOL every 30 s."""
    out = []
    for w in range(wallets):
        for i in range(rounds):
            ts = NOW - 3000 + w + i * 60
            out += [{"side": "buy", "wallet": f"BOT{w}", "amount": 0.5, "ts": ts},
                    {"side": "sell", "wallet": f"BOT{w}", "amount": 0.5, "ts": ts + 30}]
    return out


def organic_trades(n=150):
    return [{"side": "buy" if i % 3 else "sell", "wallet": f"W{i}", "amount": 0.05 + (i * 37 % 100) / 50,
             "ts": NOW - 3500 + i * 23 + (i * i % 17)} for i in range(n)]


class TopcheckVolume(unittest.TestCase):
    def test_dakitty_like_wash_trades_fail(self):
        j = safety.judge("DAKITTYx", clean_rc(), {"ok": True, "ratio": 0.97},
                         pair=pair(160, 160, 16_000, 2000, 2000, 160_000), trades=wash_trades())
        self.assertEqual(j["verdict"], "pao", j)
        st, txt = j["checks"]["volumen"]
        self.assertEqual(st, "fail")
        self.assertIn("volumen lažan: wash", txt)

    def test_dakitty_like_pair_without_trades_is_oprez(self):
        # buys and sells equal within 1 % in the hour and the day, on many transactions
        j = safety.judge("DAKITTYx", clean_rc(), {"ok": True, "ratio": 0.97},
                         pair=pair(1502, 1498, 60_000, 15_010, 14_990, 600_000, liq=40_000))
        self.assertEqual(j["verdict"], "oprez", j)
        self.assertIn("kupnje i prodaje gotovo jednake", j["checks"]["volumen"][1])

    def test_dacitycoin2_like_micro_prints_and_turnover_are_oprez(self):
        micro = safety.judge("DACITY2x", clean_rc(), {"ok": True, "ratio": 0.97},
                             pair=pair(2600, 1400, 9_000, 30_000, 10_000, 120_000))
        self.assertEqual(micro["verdict"], "oprez")
        self.assertIn("prosječno $2.25 po transakciji", micro["checks"]["volumen"][1])
        spin = safety.judge("DACITY2x", clean_rc(), {"ok": True, "ratio": 0.97},
                            pair=pair(300, 200, 900_000, 3000, 2000, 2_000_000))
        self.assertIn("promet sata 30× likvidnosti", spin["checks"]["volumen"][1])
        # 12 wallets make 140 trades in the hour: under the wash line, but a few wallets churn it
        trades = [{"side": "buy" if i % 2 else "sell", "wallet": f"W{i % 12}", "amount": 0.05 + (i * 37 % 101) / 50,
                   "ts": NOW - 3500 + (i * 7919) % 3400} for i in range(140)]
        from rugfilter import analysis
        self.assertLess(analysis.wash_score(analysis.volume_quality(trades)), safety.WASH_WARN)
        few = safety.judge("DACITY2x", clean_rc(), {"ok": True, "ratio": 0.97}, trades=trades)
        self.assertEqual(few["verdict"], "oprez")
        self.assertIn("volumen vrti nekoliko novčanika: 12 različitih na 140 tradeova", few["checks"]["volumen"][1])

    def test_organic_volume_passes_and_no_data_changes_nothing(self):
        j = safety.judge("ORGx", clean_rc(), {"ok": True, "ratio": 0.97},
                         pair=pair(400, 250, 60_000, 4200, 3100, 700_000, liq=40_000), trades=organic_trades())
        self.assertEqual(j["verdict"], "prolazi", j)
        self.assertEqual(j["checks"]["volumen"][0], "ok")
        self.assertNotIn("volumen", safety.judge("ORGx", clean_rc(), {"ok": True, "ratio": 0.97})["checks"])

    def test_the_full_rug_filters_wash_score_counts(self):
        full = {"verdict": "PROLAZI", "data": {"hard_fails": [], "flags": [], "wash_score": 72}}
        j = safety.judge("Xw", clean_rc(), {"ok": True, "ratio": 0.97}, full)
        self.assertEqual(j["verdict"], "pao")
        import run_top
        self.assertEqual(run_top._full_data({"wash_score": 41})["wash_score"], 41)

    def test_run_top_reads_the_last_hour_of_pumpportal_trades(self):
        import run_top
        hc = sqlite3.connect(":memory:")
        hc.execute("CREATE TABLE live_trades (sig TEXT, mint TEXT, wallet TEXT, side TEXT, sol REAL, tokens REAL, "
                   "price_sol REAL, mcap_sol REAL, pool TEXT, ts INTEGER, balance_after REAL)")
        hc.executemany("INSERT INTO live_trades (sig, mint, wallet, side, sol, ts) VALUES (?,?,?,?,?,?)",
                       [("a", X, "W1", "buy", 0.4, NOW - 100), ("b", X, "W2", "sell", 0.3, NOW - 7200),
                        ("c", Y, "W3", "buy", 1.0, NOW - 50)])
        try:
            self.assertEqual(run_top.live_trades(hc, X, NOW),
                             [{"side": "buy", "wallet": "W1", "amount": 0.4, "ts": NOW - 100}])
        finally:
            hc.close()
        self.assertEqual(run_top.live_trades(None, X, NOW), [])


# ---------- 3. wallet hygiene ---------------------------------------------------------------------------------------

def wallet_db(tmp, rows):
    """rows: (wallet, tier, copy_score, score, labels, stats, last_tx_ts)"""
    path = os.path.join(tmp, "wallets.db")
    con = wstore.connect(path)
    for w, tier, cs, sc, lab, st, last in rows:
        con.execute("INSERT INTO wallets (wallet, tier, copy_score, score, labels, stats, last_tx_ts) VALUES (?,?,?,?,?,?,?)",
                    (w, tier, cs, sc, json.dumps(lab), json.dumps(st), last))
    con.commit()
    con.close()
    return path


GOOD = {"trades_per_day": 6, "median_hold_min": 45, "style": "swing"}
WROWS = [("ACTIVE", "A", 80, 70, [], GOOD, NOW - 2 * H),
         ("IDLE", "A", 75, 70, [], GOOD, NOW - 30 * H),
         ("BACKONCHAIN", "B", 70, 60, [], GOOD, NOW - 40 * H),
         ("SNIPER", "S", 0, 90, ["sniper"], {"trades_per_day": 40, "median_hold_min": 3, "style": "sniper"}, NOW - H),
         ("BUSY", "A", 65, 60, [], {"trades_per_day": 450, "median_hold_min": 20}, NOW - H),
         ("FLIPPER", "B", 60, 55, [], {"trades_per_day": 30, "median_hold_min": 0.2}, NOW - H),
         ("STATBOT", "S", 0, 80, [], {"bot": True, "style": "bot", "trades_per_day": 150}, NOW - H),
         ("NOTIME", "B", 50, 50, [], GOOD, None)]


class WalletHygiene(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wdb = wallet_db(self.tmp, WROWS)
        self.hdb = os.path.join(self.tmp, "hype.db")
        hc = sqlite3.connect(self.hdb)
        hc.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL)")
        hc.execute("INSERT INTO chain_trades VALUES ('s', 'BACKONCHAIN', 'M', 'buy', ?, 1.0)", (NOW - H,))
        hc.commit()
        hc.close()

    def test_only_removes_and_keeps_the_order(self):
        logs = []
        ws = [w for w, *_ in WROWS] + ["UNKNOWN"]
        kept, out = hygiene.screen({"copy": ws, "other": ["IDLE", "ACTIVE"]}, "test", now=NOW, wallet_db=self.wdb,
                                   hype_db=self.hdb, log=logs.append)
        self.assertEqual(kept["copy"], ["ACTIVE", "BACKONCHAIN", "NOTIME", "UNKNOWN"])   # unknown facts are kept
        self.assertEqual(kept["other"], ["ACTIVE"])
        self.assertEqual(set(out), {"IDLE", "SNIPER", "BUSY", "FLIPPER", "STATBOT"})
        self.assertIn("neaktivan 30 h", out["IDLE"])
        self.assertEqual(out["SNIPER"], "oznaka sniper")                      # tier S does not protect it
        self.assertIn("450 tradeova dnevno", out["BUSY"])
        self.assertIn("medijan držanja 12 s", out["FLIPPER"])
        self.assertEqual(len(logs), 1)
        self.assertIn("izbačeno 5 od 9 novčanika", logs[0])
        self.assertTrue(set(kept["copy"]) <= set(ws))                         # never adds

    def test_config_values(self):
        p = os.path.join(self.tmp, "config.json")
        with open(p, "w") as f:
            json.dump({"copy_hygiene": {"max_idle_h": 48, "bogus": 1}}, f)
        r = hygiene.rule(p)
        self.assertEqual((r["max_idle_h"], r["max_tpd"], r["min_hold_s"]), (48.0, 200, 30))
        self.assertNotIn("bogus", r)
        kept, _ = hygiene.screen({"w": ["IDLE"]}, "t", now=NOW, wallet_db=self.wdb, hype_db=self.hdb, r=r, log=None)
        self.assertEqual(kept["w"], ["IDLE"])
        self.assertEqual(hygiene.rule(os.path.join(self.tmp, "none.json")), hygiene.DEFAULT)

    def test_webhook_groups_lose_idle_and_s_tier_bots(self):
        from kol import chainwatch, idents, store as kstore
        kcon = kstore.connect(os.path.join(self.tmp, "kol.db"))
        idents.save(kcon, [{"wallet": f"ID{i}", "name": f"k{i}", "twitter": None, "telegram": None, "pnl": 1,
                            "wins": 1, "losses": 0, "rank": i} for i in range(10)], "kolscan")
        cfg = {"max_wallets": 10, "share": {"ids": 0.3, "copy": 0.5, "signal": 0.2, "insajderi": 0.0}, "min_copy": 35}
        with mock.patch.dict(os.environ, {"HYPE_DB": self.hdb}):
            got = chainwatch.wanted(kcon, cfg, wallet_db=self.wdb, now=NOW)
        kcon.close()
        self.assertIn("ACTIVE", got)
        self.assertIn("BACKONCHAIN", got)                                      # its webhook buy an hour ago counts
        for w in ("IDLE", "SNIPER", "STATBOT", "BUSY", "FLIPPER"):
            self.assertNotIn(w, got)
        self.assertEqual(len(got), 10)                                        # freed slots go to the leaderboard

    def test_autopilot_wallet_pick_skips_them(self):
        from ui import autopilot
        rows = [{"wallet": w, "name": "", "why": "x", "s": {"score": 1}} for w in ("IDLE", "SNIPER", "ACTIVE", "BUSY")]
        with mock.patch.object(wstore, "DB", self.wdb), mock.patch.dict(os.environ, {"HYPE_DB": self.hdb}), \
                mock.patch("ui.autopilot.proven_wallets", return_value=rows[:2]), \
                mock.patch("ui.autopilot.wallet_recs", return_value={14: rows[2:]}), \
                mock.patch("ui.autopilot.kol_recs", return_value={}), \
                mock.patch("wallets.hygiene.time.time", return_value=NOW):
            got = autopilot.auto_targets(14, 3)
        self.assertEqual([t for k, t, _l, _w in got if k == "wallet"], ["ACTIVE"])


# ---------- 4. the live list after a pump ---------------------------------------------------------------------------

class ZivoRunup(unittest.TestCase):
    def setUp(self):
        zivo._FIRST.clear()

    def test_4x_over_the_first_call_is_a_tagged_pick(self):
        cands = [{"token": X, "symbol": "LATE", "src": "zovu", "ts0": NOW - 120, "mcap0": 240_000, "why": ["zovu"]},
                 {"token": Y, "symbol": "OK", "src": "zovu", "ts0": NOW - 600, "mcap0": 90_000, "why": ["zovu"]}]
        lv = {X: live(240_000), Y: live(90_000)}
        rs = zivo.rows(NOW, cands=cands, live=lv, callers={X: ["ansem"], Y: ["kolb"]}, smart={X: 2}, mstats={},
                       chances={}, firsts={X: (NOW - 3 * H, 50_000.0), Y: (NOW - H, 60_000.0)})
        self.assertEqual([r["token"] for r in rs], [Y, X])                    # the late one goes last, however hot
        late, ok = rs[1], rs[0]
        self.assertTrue(late["pick"])                                         # 11.11. (rule B): a tag, not a block
        self.assertEqual(late["tags"], ["kasno"])
        self.assertEqual(late["runup"]["x"], 4.8)
        self.assertIn("kasno: već 4.8× od prvog poziva", late["tag"])
        self.assertIsNone(late["why_not"])
        self.assertTrue(ok["pick"])
        self.assertEqual(ok["runup"]["x"], 1.5)
        plain = zivo.rows(NOW, cands=cands[1:], live=lv, callers={Y: ["kolb"]}, smart={}, mstats={}, chances={})
        self.assertTrue(plain[0]["pick"])                                     # no first call known: no mark
        self.assertIsNone(plain[0]["runup"])

    def test_first_calls_read_the_first_measured_call_of_the_day_once_a_minute(self):
        from kol import store as kstore
        path = os.path.join(tempfile.mkdtemp(), "kol.db")
        kc = kstore.connect(path)
        kc.executemany("INSERT INTO calls (tweet_id, token, handle, ts, kind, mcap0) VALUES (?,?,?,?,?,?)",
                       [("1", X, "a", NOW - 2 * D, "call", 10_000), ("2", X, "b", NOW - 5 * H, "call", None),
                        ("3", X, "c", NOW - 4 * H, "call", 40_000), ("4", X, "d", NOW - H, "call", 90_000),
                        ("5", Y, "e", NOW - H, "buy", 5_000)])
        kc.commit()
        kc.close()
        self.assertEqual(zivo.first_calls(NOW, [X, Y], kol_db=path), {X: (NOW - 4 * H, 40_000.0)})
        os.remove(path)
        self.assertEqual(zivo.first_calls(NOW + 30, [X], kol_db=path), {X: (NOW - 4 * H, 40_000.0)})   # cached
        self.assertEqual(zivo.first_calls(NOW + 90, [X], kol_db=path), {})

    def test_the_copy_gate_measures_from_the_first_call(self):
        from league import copy as lcopy
        self.assertAlmostEqual(lcopy.runup_from_first(X, 0.0005, first={"p0": 0.0001}), 4.0)
        self.assertIsNone(lcopy.runup_from_first(X, 0.0005, first={"p0": None}))


if __name__ == "__main__":
    unittest.main()
