"""10.11.: the read-only analysis tools of the MemeSonar MCP endpoint (ui/mcpdata.py), one test per tool, on small
databases in a temp dir: kol.db, minute.db, wallets.db, hype.db, rug.db, topcheck.db, corr.db, league.db, trade.db.
Every tool pages (limit 1..500, offset, next_offset), answers unix seconds and writes nothing except
submit_caller_weights (assistant_suggestions, status pending).

    python3 -m unittest tests.test_mcpdata_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store  # noqa: E402
from trade import executor, settings  # noqa: E402

NOW = int(time.time())
TOK = "Hope" + "x" * 36 + "pump"
TOK2 = "Bonk" + "y" * 36 + "pump"
W1, W2 = "W" * 44, "V" * 44
ENV = ("KOL_DB", "HYPE_DB", "TG_DB", "WALLET_DB", "RUG_DB", "TOPCHECK_DB", "CORR_DB", "MINUTE_DB", "TRADE_OWNER")


def _db(path, sql, rows=()):
    con = sqlite3.connect(path)
    con.executescript(sql)
    for q, args in rows:
        con.execute(q, args)
    con.commit()
    con.close()


class Base(unittest.TestCase):
    def setUp(self):
        from ui import mcpdata
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._env = {k: os.environ.get(k) for k in ENV}
        self._saved = (settings.DB, store.DB)
        p = {k: os.path.join(d, f"{k}.db") for k in ("kol", "hype", "tg", "wallets", "rug", "topcheck", "corr", "minute")}
        os.environ.update(KOL_DB=p["kol"], HYPE_DB=p["hype"], TG_DB=p["tg"], WALLET_DB=p["wallets"], RUG_DB=p["rug"],
                          TOPCHECK_DB=p["topcheck"], CORR_DB=p["corr"], MINUTE_DB=p["minute"], TRADE_OWNER="Jure")
        settings.DB = os.path.join(d, "trade.db")
        store.DB = os.path.join(d, "league.db")
        mcpdata._CACHE.clear()
        calls = [  # handle, tweet, token, ts, kind, p0, mcap0, r1h, r24h, max24, rug, followers
            ("ansem", "t1", TOK, NOW - 7200, "call", 0.001, 50_000, 0.3, 1.5, 2.0, 0, 500_000),
            ("ansem", "t2", TOK2, NOW - 3600, "call", 0.002, 80_000, -0.2, -0.95, 0.1, 1, 500_000),
            ("murad", "t3", TOK, NOW - 7000, "call", 0.0011, 55_000, 0.2, 1.2, 1.1, 0, 20_000),
            ("tg:alpha", "tg:alpha/1", TOK, NOW - 6900, "call", 0.0012, 60_000, 0.1, 0.4, 0.6, 0, 3_000),
            ("murad", "b1", TOK, NOW - 6000, "brag", None, None, None, None, None, 0, 20_000),
            ("murad", "b2", TOK2, NOW - 5000, "brag", None, None, None, None, None, 0, 20_000),
            ("murad", "b3", TOK2, NOW - 4000, "brag", None, None, None, None, None, 0, 20_000),
        ]
        _db(p["kol"], """CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, url TEXT, kind TEXT,
              symbol TEXT, p0 REAL, mcap0 REAL, r1h REAL, r24h REAL, max24 REAL, rug INTEGER, followers INTEGER);
            CREATE TABLE kols (handle TEXT PRIMARY KEY, name TEXT, followers INTEGER, score REAL, power_rel REAL,
              stats TEXT, bot INTEGER DEFAULT 0);
            CREATE TABLE kol_ids (wallet TEXT PRIMARY KEY, name TEXT, twitter TEXT, telegram TEXT, pnl REAL, wins INTEGER,
              losses INTEGER);
            CREATE TABLE snaps (token TEXT, ts INTEGER, price REAL, vol_h1 REAL, liq REAL, mcap REAL);""",
            [("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (tw, tok, h, ts, f"https://x.com/{h}/status/{tw}", kind, "HOPE", p0, mc, r1, r24, mx, rug, fol))
             for h, tw, tok, ts, kind, p0, mc, r1, r24, mx, rug, fol in calls]
            + [("INSERT INTO kols VALUES (?,?,?,?,?,?,0)", ("ansem", "Ansem", 500_000, 72.0, 0.4, "{}")),
               ("INSERT INTO kols VALUES (?,?,?,?,?,?,0)", ("murad", "Murad", 20_000, 55.0, 2.1, "{}")),
               ("INSERT INTO kol_ids VALUES (?,?,?,?,?,?,?)", (W1, "Ansem", "ansem", None, 12.5, 30, 10)),
               ("INSERT INTO snaps VALUES (?,?,?,?,?,?)", (TOK, NOW - 7100, 0.0011, 1000, 20_000, 55_000))])
        _db(p["minute"], """CREATE TABLE call_path (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, entry REAL,
              lag_s INTEGER, mcap_e REAL, hi15 REAL, hi30 REAL, hi60 REAL, lo60 REAL, r60 REAL, t5 INTEGER, t10 INTEGER,
              t15 INTEGER, t20 INTEGER, t30 INTEGER, sl_min INTEGER);""",
            [("INSERT INTO call_path (tweet_id, token, handle, ts, entry, mcap_e, hi15, hi60, lo60, r60, t10, t15, sl_min) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ("t1", TOK, "ansem", NOW - 7200, 0.001, 50_000, 0.4, 0.8, -0.1, 0.3, 4, 6, None))])
        _db(p["wallets"], """CREATE TABLE wallets (wallet TEXT PRIMARY KEY, tier TEXT, score REAL, copy_score REAL,
              stats TEXT, labels TEXT, last_tx_ts INTEGER);
            CREATE TABLE wallet_trades (wallet TEXT, sig TEXT, ts INTEGER, mint TEXT, tokens REAL, sol REAL, kind TEXT);""",
            [("INSERT INTO wallets VALUES (?,?,?,?,?,?,?)", (W1, "B", 50.0, 40.0, json.dumps(
                {"realized_sol": 12.5, "unrealized_sol": 1.0, "win_rate": 0.6, "median_hold_min": 42, "style": "swing"}),
                "[]", NOW - 100)),
             ("INSERT INTO wallets VALUES (?,?,?,?,?,?,?)", (W2, "A", 70.0, 65.0, json.dumps(
                 {"realized_sol": 30.0, "win_rate": 0.7}), "[]", NOW - 50)),
             ("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", (W1, "s1", NOW - 7300, TOK, 1e6, 0.5, "buy")),
             ("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", (W1, "s2", NOW - 3000, TOK, 1e6, 1.4, "sell"))])
        _db(p["hype"], """CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);
            CREATE TABLE live_trades (sig TEXT, mint TEXT, wallet TEXT, side TEXT, sol REAL, tokens REAL, price_sol REAL,
              mcap_sol REAL, pool TEXT, ts INTEGER, balance_after REAL);
            CREATE TABLE hype_snapshots (token TEXT, ts INTEGER, price REAL, mcap REAL, liquidity REAL);
            CREATE TABLE rug_archive (token TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, last_ts INTEGER,
              archived_ts INTEGER, klasa TEXT, kind TEXT, reason TEXT, peak_mcap REAL, last_mcap REAL, peak_liq REAL,
              last_liq REAL, pad REAL, entry REAL, removed INTEGER);""",
            [("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", ("s1", W1, TOK, "buy", NOW - 7300, 0.5)),
             ("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", ("s9", W1, TOK2, "buy", NOW - 100, 0.2)),
             ("INSERT INTO live_trades VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("s9", TOK2, W1, "buy", 0.2, 5e5, 1e-7, 400.0, "p", NOW - 100, 0)),
             ("INSERT INTO hype_snapshots VALUES (?,?,?,?,?)", (TOK, NOW - 7000, 0.0012, 60_000, 21_000)),
             ("INSERT INTO rug_archive (token, archived_ts, kind, reason, peak_mcap, last_mcap) VALUES (?,?,?,?,?,?)",
              (TOK2, NOW - 1000, "rug", "lp pulled", 90_000, 2_000))])
        _db(p["rug"], """CREATE TABLE rug_reports (mint TEXT, checked_at INTEGER, symbol TEXT, verdict TEXT, score REAL,
              wash_score REAL, bundle_pct REAL, sniper_pct REAL, cluster_pct REAL, top10_pct REAL, dev TEXT, data TEXT);""",
            [("INSERT INTO rug_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (TOK, NOW - 7100, "HOPE", "PROLAZI", 82, 0, 3, 2, 1, 18, "ok", "{}"))])
        _db(p["topcheck"], """CREATE TABLE top_check (token TEXT PRIMARY KEY, symbol TEXT, rank INTEGER, ts INTEGER,
              price REAL, mcap REAL, liq REAL, state TEXT, state_json TEXT, verdict TEXT, safety_json TEXT, rc_json TEXT,
              rc_ts INTEGER);""",
            [("INSERT INTO top_check (token, ts, mcap, liq, verdict, rc_ts) VALUES (?,?,?,?,?,?)",
              (TOK, NOW - 600, 90_000, 25_000, "prolazi", NOW - 900))])
        _db(p["corr"], """CREATE TABLE snapshots (ts INTEGER PRIMARY KEY, hash TEXT, data TEXT);
            CREATE TABLE ai (ts INTEGER, model TEXT, data TEXT, cost REAL);""",
            [("INSERT INTO snapshots VALUES (?,?,?)", (NOW - 3600, "h", json.dumps(
                {"groups": [{"id": "g1", "wallets": [W1, W2], "handles": ["ansem"], "tokens": [TOK], "why": "same funder",
                             "score": 7}],
                 "clusters": [{"id": "c1", "members": ["ansem", "murad"], "wallets": [W1], "tokens": 4, "score": 5}]})))])
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "ansem", 25, 5, "tpsl", "40%", "")
        t1 = store.buy(self.lg, settings.LEAGUE_USER, TOK, "HOPE", 25, 1.0, 1e6, "copy KOL ansem", 61.0, 50_000)
        self.lg.execute("UPDATE trades SET follow_id=?, status='closed', closed_ts=?, exit_mcap=?, note=?, pnl_usd=? WHERE id=?",
                        (fid, NOW - 3000, 70_000, "auto TP +40%", 9.5, t1))
        self.lg.execute("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                        (fid, TOK, "buy", NOW - 7200, NOW - 7190, "HOPE", "ulaz", "kupljeno na MC $50k", t1))
        self.lg.commit()
        self.con = executor.connect(settings.DB)
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, closed_ts, mode, status, reason, sol_in, "
                         "sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (t1, TOK, "HOPE", NOW - 7185, NOW - 2990, "live", "closed", "copy KOL ansem", 0.15, 0.21, 0.002))
        self.con.commit()

    def tearDown(self):
        settings.DB, store.DB = self._saved
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()


class Tools(Base):
    def test_1_caller_leaderboard(self):
        from ui import mcpdata
        out = mcpdata.caller_leaderboard(limit=2)
        self.assertEqual((out["limit"], out["offset"], out["total"], out["next_offset"]), (2, 0, 3, 2))
        top = out["rows"][0]
        self.assertEqual((top["handle"], top["platform"], top["calls"], top["call_power"]), ("ansem", "x", 2, 72.0))
        self.assertEqual((top["hit_rate"], top["x2_share"], top["rug_count"]), (0.5, 0.5, 1))
        self.assertEqual(top["avg_r24h"], 0.275)
        self.assertEqual(top["median_r1h"], 0.05)
        self.assertEqual(top["avg_mcap_at_call"], 65_000)
        self.assertEqual((top["first_call_ts"], top["last_call_ts"]), (NOW - 7200, NOW - 3600))
        self.assertTrue(top["big_name"])
        murad = next(r for r in mcpdata.caller_leaderboard(limit=500)["rows"] if r["handle"] == "murad")
        self.assertTrue(murad["rising_star"] and murad["bragger"])
        tg = mcpdata.caller_leaderboard(platform="telegram")["rows"]
        self.assertEqual([r["handle"] for r in tg], ["tg:alpha"])
        self.assertEqual([r["handle"] for r in mcpdata.caller_leaderboard(min_calls=2)["rows"]], ["ansem"])
        self.assertEqual(mcpdata.caller_leaderboard(sort="x2_share", limit=1)["rows"][0]["handle"], "murad")
        self.assertEqual(mcpdata.caller_leaderboard(limit=9999)["limit"], 500)

    def test_2_caller_history(self):
        from ui import mcpdata
        out = mcpdata.caller_history("@ansem", "x")
        self.assertEqual(out["total"], 2)
        old = out["rows"][1]
        self.assertEqual((old["token"], old["call_ts"], old["market_cap_at_call"]), (TOK, NOW - 7200, 50_000))
        self.assertEqual((old["max_1h"], old["min_1h"], old["max_24h"]), (0.8, -0.1, 2.0))
        self.assertAlmostEqual(old["price_1h"], 0.0013)
        self.assertEqual((old["other_callers_15m_before"], old["other_callers_15m_after"]), (0, 2))
        self.assertTrue(out["rows"][0]["rug"])
        page = mcpdata.caller_history("ansem", "x", limit=1, offset=1)
        self.assertEqual((len(page["rows"]), page.get("next_offset")), (1, None))
        self.assertEqual(mcpdata.caller_history("alpha", "telegram")["total"], 1)
        self.assertEqual(mcpdata.caller_history("ansem", since_ts=NOW - 4000)["total"], 1)

    def test_3_token_history(self):
        from ui import mcpdata
        out = mcpdata.token_history(TOK)
        self.assertEqual([c["handle"] for c in out["calls"]], ["ansem", "murad", "tg:alpha", "murad"])
        self.assertEqual([p["ts"] for p in out["price_series"]], [NOW - 7100, NOW - 7000])
        self.assertEqual(out["rug_checks"][0]["verdict"], "PROLAZI")
        self.assertEqual(out["top_check"]["verdict"], "prolazi")
        self.assertEqual(out["autopilot_demo_trades"][0]["exit_note"], "auto TP +40%")
        self.assertEqual(out["autopilot_real_positions"][0]["sol_back"], 0.21)
        self.assertEqual(mcpdata.token_history(TOK2)["rug_archive"]["reason"], "lp pulled")
        self.assertIn("error", mcpdata.token_history("x"))

    def test_4_wallet_leaderboard_and_history(self):
        from ui import mcpdata
        out = mcpdata.wallet_leaderboard()
        self.assertEqual([r["wallet"] for r in out["rows"]], [W2, W1])
        w1 = out["rows"][1]
        self.assertEqual((w1["kind"], w1["linked_handle"], w1["realized_pnl_sol"], w1["median_hold_min"]),
                         ("influencer", "ansem", 12.5, 42.0))
        self.assertEqual([r["wallet"] for r in mcpdata.wallet_leaderboard(kind="smart")["rows"]], [W2])
        h = mcpdata.wallet_history(W1)
        self.assertEqual([r["sig"] for r in h["rows"]], ["s9", "s2", "s1"])        # newest first, deduplicated
        self.assertEqual(h["rows"][0]["market_cap_sol"], 400.0)
        self.assertEqual((h["linked_handle"], h["tier"]), ("ansem", "B"))
        self.assertIn("error", mcpdata.wallet_history("short"))

    def test_5_wallet_clusters(self):
        from ui import mcpdata
        out = mcpdata.wallet_clusters()
        self.assertEqual(out["snapshot_ts"], NOW - 3600)
        self.assertEqual(out["wallet_groups"][0]["wallets"], [W1, W2])
        self.assertEqual(out["wallet_groups"][0]["tokens"], [TOK])
        self.assertEqual(out["caller_clusters"][0]["callers"], ["ansem", "murad"])

    def test_6_autopilot_trades(self):
        from ui import mcpdata
        out = mcpdata.autopilot_trades()
        t = out["rows"][0]
        self.assertEqual((t["token"], t["status"], t["exit_reason"], t["entry_market_cap"], t["exit_market_cap"]),
                         (TOK, "closed", "TP", 50_000, 70_000))
        self.assertAlmostEqual(t["pnl_sol"], 0.058)
        sig = t["signals"]
        self.assertEqual(sig["follow"]["target"], "ansem")
        self.assertEqual(sig["signal_ts"], NOW - 7200)
        self.assertEqual(sig["score_at_entry"], 61.0)
        self.assertEqual([c["handle"] for c in sig["callers_last_hour"]], ["ansem"])   # murad and alpha came after the entry
        self.assertEqual(sig["callers_last_hour"][0]["call_power"], 72.0)
        self.assertEqual(sig["rug_check"]["verdict"], "PROLAZI")
        self.assertEqual(sig["call_path"]["hi60"], 0.8)                        # the triggering call's minute path
        self.assertEqual(sig["runup_from_first_call"], 0.0)                   # entered at the first call's 50k
        self.assertEqual(sig["wallet_buys_last_hour"][0]["tier"], "B")
        self.assertEqual(mcpdata.autopilot_trades(since_ts=NOW)["total"], 0)
        self.assertEqual(mcpdata.autopilot_trades(status="open")["total"], 0)

    def test_7_scoring_config(self):
        from ui import mcpdata
        out = mcpdata.scoring_config()
        self.assertIn("weights", out["caller_score"])
        self.assertEqual(out["autopilot_settings"]["sl_default"], 60)
        self.assertEqual(out["real_money_proof_gate"], {"closed": 10, "win_rate": 0.4})
        self.assertEqual(out["copy_filters"]["min_mcap"], 30_000)
        text = json.dumps(out)
        for secret in ("mcp_key", "wallet_pub", "PRIVATE"):
            self.assertNotIn(secret, text)

    def test_8_submit_caller_weights_waits_for_the_owner(self):
        from ui import mcpdata, pravitrade
        from ui import assistnotes
        out = mcpdata.submit_caller_weights([{"handle": "@ansem", "platform": "x", "weight": 1.5, "reason": "x2 rate"},
                                             {"handle": "alpha", "platform": "telegram", "weight": 0}])
        self.assertEqual((out["stored"], out["status"]), (2, "novo"))
        rows, total = assistnotes.notes(self.con, "novo", "suggestion")
        self.assertEqual({(r["proposed_change"]["caller"], r["proposed_change"]["weight"]) for r in rows},
                         {("ansem", 1.5), ("tg:alpha", 0.0)})
        self.assertIn("error", mcpdata.submit_caller_weights([{"handle": "x", "weight": 3}]))
        self.assertIn("error", mcpdata.submit_caller_weights([]))
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Prijedlozi asistenta", body)
        self.assertIn("težina callera ansem (x) → 1.5", body)
        loc = pravitrade.post("/pravi-trade/asapply", {"id": str(next(r["id"] for r in rows
                                                                       if r["proposed_change"]["caller"] == "ansem"))}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(settings.raw(self.con)["caller_weights"], {"ansem": 1.5})
        self.assertEqual(assistnotes.notes(self.con, "novo", "suggestion")[1], 1)

    def test_tools_are_listed_and_read_only_ones_are_marked(self):
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        for n in ("get_caller_leaderboard", "get_caller_history", "get_token_history", "get_wallet_leaderboard",
                  "get_wallet_history", "get_wallet_clusters", "get_autopilot_trades", "get_scoring_config"):
            self.assertTrue(names[n]["annotations"]["readOnlyHint"], n)
            self.assertIn("description", names[n])
        self.assertFalse(names["submit_caller_weights"]["annotations"]["destructiveHint"])
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "get_caller_leaderboard", "arguments": {"limit": 1}}}
        res = json.loads(mcpapi.rpc(json.dumps(call).encode())[1])["result"]
        self.assertFalse(res["isError"])
        self.assertEqual(res["structuredContent"]["limit"], 1)
        self.assertLess(len(json.dumps(res)), 20_000)                    # reasonable size


if __name__ == "__main__":
    unittest.main()


class AssistantNotes(Base):
    """10.11.: the assistant writes notes (trade_review, signal_opinion, suggestion, daily_summary) that only the
    owner turns into a change; Primijeni applies only the allow-listed keys and logs old -> new."""

    def call(self, name, args, key="k1"):
        from ui import mcpapi
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        res = json.loads(mcpapi.rpc(body.encode(), key)[1])["result"]
        return res["structuredContent"], res["isError"]

    def pid(self):
        return self.con.execute("SELECT id FROM positions ORDER BY id LIMIT 1").fetchone()[0]

    def test_write_tools_insert_notes_only_and_validate(self):
        from ui import assistnotes
        out, err = self.call("submit_trade_review", {"position_id": self.pid(), "verdict": "dobar", "confidence": 0.8,
                                                     "interpretation": "TP pogođen u 50 min", "improvement": "isti TP",
                                                     "evidence": {"pnl_sol": 0.058}})
        self.assertFalse(err)
        self.assertEqual(out["status"], "novo")
        out, err = self.call("submit_signal_opinion", {"token": TOK, "verdict": "preskoči", "confidence": 0.6,
                                                       "interpretation": "top10 drži 40 %"})
        self.assertFalse(err)
        self.assertFalse(self.call("submit_suggestion", {"title": "Stop -40", "interpretation": "stopovi -60 prekasni",
                                                         "proposed_change": {"key": "sl_default", "from": 60, "to": 40}})[1])
        self.assertFalse(self.call("submit_daily_summary", {"title": "Utorak", "interpretation": "2 trejda, +0,06 SOL"})[1])
        rows, total = assistnotes.notes(self.con)
        self.assertEqual(total, 4)
        self.assertEqual(rows[-1]["evidence"], {"pnl_sol": 0.058})
        # validation: wrong verdict, confidence, unknown position, too long text, not-JSON evidence
        for args in ({"position_id": self.pid(), "verdict": "super", "interpretation": "x"},
                     {"position_id": self.pid(), "verdict": "dobar", "confidence": 2, "interpretation": "x"},
                     {"position_id": 99999, "verdict": "dobar", "interpretation": "x"},
                     {"position_id": self.pid(), "verdict": "dobar", "interpretation": "x" * 4001},
                     {"position_id": self.pid(), "verdict": "dobar"}):
            out, err = self.call("submit_trade_review", args)
            self.assertTrue(err, args)
        self.assertTrue(self.call("submit_suggestion", {"title": "x", "interpretation": "y", "evidence": "nije json"})[1])
        self.assertEqual(assistnotes.notes(self.con)[1], 4)                # nothing stored by a refused call
        # nothing else changed
        self.assertNotIn("sl_default", settings.raw(self.con))

    def test_rate_limit_per_key(self):
        from ui import assistnotes
        saved = assistnotes.RATE_PER_HOUR
        assistnotes.RATE_PER_HOUR = 3
        try:
            for _ in range(3):
                self.assertFalse(self.call("submit_daily_summary", {"title": "t", "interpretation": "i"})[1])
            out, err = self.call("submit_daily_summary", {"title": "t", "interpretation": "i"})
            self.assertTrue(err)
            self.assertIn("rate limit", out["error"])
            self.assertFalse(self.call("submit_daily_summary", {"title": "t", "interpretation": "i"}, key="k2")[1])
        finally:
            assistnotes.RATE_PER_HOUR = saved

    def test_unreviewed_trades_and_notes_listing(self):
        out, _ = self.call("get_unreviewed_trades", {})
        self.assertEqual([r["trade_id"] for r in out["rows"]], [self.pid()])
        self.call("submit_trade_review", {"position_id": self.pid(), "verdict": "loš", "interpretation": "kasni ulaz"})
        self.assertEqual(self.call("get_unreviewed_trades", {})[0]["rows"], [])
        notes, _ = self.call("get_assistant_notes", {"kind": "trade_review"})
        self.assertEqual((notes["total"], notes["rows"][0]["verdict"]), (1, "loš"))

    def test_apply_allowlist_logs_and_refuses_the_rest(self):
        from ui import assistnotes
        con = self.con

        def sug(pc):
            return self.call("submit_suggestion", {"title": "t", "interpretation": "i", "proposed_change": pc})[0]["id"]
        st, words = assistnotes.apply(con, sug({"key": "sl_default", "from": 60, "to": 40}))
        self.assertEqual((st, settings.merged(executor.load_config(), con)["sl_default"]), ("primijenjeno", 40))
        self.assertEqual(settings.raw(con)["applied_log"][0], {**settings.raw(con)["applied_log"][0],
                                                               "key": "sl_default", "old": 60, "new": 40})
        self.assertEqual(assistnotes.apply(con, sug({"key": "tp_default", "to": 30}))[0], "primijenjeno")
        self.assertEqual(assistnotes.apply(con, sug({"key": "size_sol", "to": 0.05}))[0], "primijenjeno")
        self.assertEqual(assistnotes.apply(con, sug({"key": "max_open", "to": 7}))[0], "primijenjeno")
        assistnotes.apply(con, sug({"key": "auto_skip", "to": [["kol", "spammer"]]}))
        self.assertIn(["kol", "spammer"], settings.raw(con)["auto_skip"])
        assistnotes.apply(con, sug({"key": "copy.max_delay_min", "to": 5}))
        self.assertEqual(settings.raw(con)["copy_cfg"], {"max_delay_min": 5.0})
        self.assertEqual(copy.apply_cfg_overrides()["max_delay_min"], 5)
        copy.CFG.clear()
        copy.CFG.update(copy._BASE_CFG)
        # refused: under the 30k rule, an SL that is not a choice, a stale "from"
        for pc in ({"key": "copy.min_mcap", "to": 10_000}, {"key": "sl_default", "to": 33},
                   {"key": "tp_default", "from": 15, "to": 50}):
            with self.assertRaises(ValueError):
                assistnotes.apply(con, sug(pc))
        # not on the list: only marked accepted, nothing changed
        before = dict(settings.raw(con))
        st, words = assistnotes.apply(con, sug({"key": "max_sol_per_day", "to": 50}))
        self.assertEqual(st, "prihvaćeno")
        self.assertEqual(settings.raw(con).get("max_sol_per_day"), before.get("max_sol_per_day"))
        st, _ = assistnotes.apply(con, sug({"file": "ui/autopilot.py", "key": "WILSON_Z", "to": 2.0}))
        self.assertEqual(st, "prihvaćeno")

    def test_routes_and_page(self):
        from ui import assistnotes, mcpapi, pravitrade
        self.call("submit_trade_review", {"position_id": self.pid(), "verdict": "dobar", "confidence": 0.9,
                                          "interpretation": "Lijep TP", "improvement": "isto"})
        self.call("submit_daily_summary", {"title": "Sažetak utorka", "interpretation": "Dobar dan."})
        n1 = self.call("submit_suggestion", {"title": "TP 30", "interpretation": "više", "evidence": {"n": 12},
                                             "proposed_change": {"key": "tp_default", "from": 15, "to": 30}})[0]["id"]
        n2 = self.call("submit_suggestion", {"title": "Drugo", "interpretation": "x"})[0]["id"]
        n3 = self.call("submit_suggestion", {"title": "Treće", "interpretation": "y"})[0]["id"]
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Sažetak utorka", body)                                   # the newest summary at the top
        self.assertIn("Prijedlozi asistenta", body)
        self.assertIn("tp_default: 15 → 30", body)
        self.assertIn("formaction=/pravi-trade/asapply", body)
        self.assertIn("Grok: dobar", body)                                      # the closed trade's review
        self.assertIn("Lijep TP", body)
        settings.put(self.con, "invited", ["gost"], "Jure")
        guest = pravitrade.page({}, "gost")[1]
        self.assertNotIn("Prijedlozi asistenta", guest)
        self.assertNotIn("Sažetak utorka", guest)
        self.assertIn("ok=", pravitrade.post("/pravi-trade/asapply", {"id": str(n1), "note": "ok"}, "Jure"))
        self.assertEqual(settings.merged(executor.load_config(), self.con)["tp_default"], 30)
        self.assertIn("ok=", pravitrade.post("/pravi-trade/asok", {"id": str(n2), "note": "ručno"}, "Jure"))
        self.assertIn("ok=", pravitrade.post("/pravi-trade/asno", {"id": str(n3), "note": "ne"}, "Jure"))
        st = {r["id"]: (r["status"], r["owner_note"]) for r in assistnotes.notes(self.con)[0]}
        self.assertEqual(st[n1], ("primijenjeno", "ok"))
        self.assertEqual(st[n2], ("prihvaćeno", "ručno"))
        self.assertEqual(st[n3], ("odbijeno", "ne"))
        self.assertIn("err=", pravitrade.post("/pravi-trade/asno", {"id": str(n3)}, "Jure"))   # decided already
        self.assertIn("err=", pravitrade.post("/pravi-trade/asok", {"id": str(n2)}, "gost"))   # owner only
        # an opinion appears on a request that waits for approval
        os.environ["MCP_API_KEY"] = "k"
        try:
            mcpapi.trade_request({"token": TOK, "side": "buy", "amount": 0.05})
            self.call("submit_signal_opinion", {"token": TOK, "verdict": "preskoči", "interpretation": "Kasno."})
            self.assertIn("Grok: preskoči", pravitrade.page({}, "Jure")[1])
        finally:
            os.environ.pop("MCP_API_KEY", None)
