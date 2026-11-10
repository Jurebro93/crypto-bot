"""10.11. (Grok MCP audit): the outside analyst's audit of the MCP answers, one test per finding, on the small
databases of tests/test_mcpdata_offline.Base plus what each finding needs. No network.

    1  dry trades: entry / exit market cap, run-up and score from the fallbacks (copy_log, minute.db, supply, paper)
    2  the exit rule that fired (exit_rule column, else the note) and the follow's exit mode + the stop that applied
    4  blocked / failed real positions listed with their reason and the demo trade they mirror
    5  caller leaderboard ranked by the EV lower bound, min_measured, hit_rate labelled the 24 h wick
    6  caller history: symbol from tokens, max/min 1 h from stored minute candles, price 24 h from snapshots, statuses
       + kol/backfill_calls.py (night, capped)
    7  token history followers from kols (case-insensitive) / tg channels
    8  wallet buys: linked handle from kol_ids, score from the linked caller
    10 X features: submit_x_features / get_x_features (flag, validation, rate limit, insert only)

    python3 -m unittest tests.test_grok_mcp_audit_offline
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
from tests.test_mcpdata_offline import NOW, TOK, W1, Base  # noqa: E402
from trade import settings  # noqa: E402

TOK3 = "Spsc" + "z" * 36 + "pump"
TOK4 = "Dddd" + "q" * 36 + "pump"
TOK5 = "Eeee" + "r" * 36 + "pump"
TOK6 = "Ffff" + "s" * 36 + "pump"
TOK7 = "Gggg" + "t" * 36 + "pump"
W3 = "J6TD" + "p" * 40
W4 = "F8Wt" + "k" * 40
TOKENS_SQL = ("CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, symbol TEXT, name TEXT, pair TEXT, supply REAL, "
              "created_ts INTEGER, liquidity REAL, tries INTEGER DEFAULT 0, updated INTEGER)")


def _exec(path, *sql):
    con = sqlite3.connect(path)
    for s in sql:
        if isinstance(s, tuple):
            con.execute(*s)
        else:
            con.execute(s)
    con.commit()
    con.close()


class Audit(Base):
    def setUp(self):
        super().setUp()
        from ui import mcpdata
        self._env2 = {k: os.environ.get(k) for k in ("PAPER_DB", "XFEAT_DB")}
        d = self.tmp.name
        os.environ["PAPER_DB"] = os.path.join(d, "paper.db")
        os.environ["XFEAT_DB"] = os.path.join(d, "xfeat.db")
        self.kol, self.minute = os.environ["KOL_DB"], os.environ["MINUTE_DB"]
        self.hype, self.wallets = os.environ["HYPE_DB"], os.environ["WALLET_DB"]
        # the production schema has these columns (kol/store.MIGRATE); the base fixture is older
        _exec(self.kol, TOKENS_SQL, "ALTER TABLE calls ADD COLUMN complete INTEGER DEFAULT 0",
              "ALTER TABLE calls ADD COLUMN measured_ts INTEGER", "ALTER TABLE calls ADD COLUMN bad TEXT",
              "ALTER TABLE calls ADD COLUMN msrc TEXT")
        _exec(self.minute, "ALTER TABLE call_path ADD COLUMN bad TEXT",
              "CREATE TABLE call_candles (token TEXT PRIMARY KEY, first_ts INTEGER, last_ts INTEGER, n INTEGER, "
              "data BLOB, full INTEGER DEFAULT 0, updated INTEGER)")
        mcpdata._CACHE.clear()

    def tearDown(self):
        for k, v in self._env2.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def call(self, name, args, key="k1"):
        from ui import mcpapi
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        res = json.loads(mcpapi.rpc(body.encode(), key)[1])["result"]
        return res["structuredContent"], res["isError"]

    def add_call(self, handle, tid, tok, ts, mcap0=None, p0=None, r1h=None, r24h=None, max24=None, followers=0,
                 symbol=None, kind="call", measured_ts=None, complete=0):
        _exec(self.kol, ("INSERT INTO calls (tweet_id, token, handle, ts, url, kind, symbol, p0, mcap0, r1h, r24h, max24, "
                         "rug, followers, complete, measured_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)",
                         (tid, tok, handle, ts, f"https://x.com/{handle}/status/{tid}", kind, symbol, p0, mcap0, r1h,
                          r24h, max24, followers, complete, measured_ts)))


# ---------- 1, 2: a dry trade under a smart profile ------------------------------------------------------------------

class DryTrade(Audit):
    def setUp(self):
        super().setUp()
        self.entry = NOW - 5000
        self.fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "murad", "murad", 25, 5, "smart")
        self.tid = store.buy(self.lg, settings.LEAGUE_USER, TOK3, "SPSC", 25, 0.000084, 50_000, f"copy KOL murad")
        # league/copy books a copy with score NULL and (when DexScreener had no market cap) entry_mcap NULL
        self.lg.execute("UPDATE trades SET follow_id=?, status='closed', closed_ts=?, exit_px=?, note=?, pnl_usd=?, "
                        "auto=?, auto_state=?, entry_mcap=NULL WHERE id=?",
                        (self.fid, NOW - 4000, 0.0000697, "auto: stop_loss", -4.3, json.dumps({"mode": "smart"}),
                         json.dumps({"cfg": {"sl": -0.35, "sl_delay_min": 5}, "pos": {}}), self.tid))
        self.lg.execute("INSERT INTO copy_log VALUES (?,?,?,?,?,?,?,?,?)",
                        (self.fid, TOK3, "buy", self.entry - 40, self.entry - 30, "SPSC", "ulaz",
                         "kupljeno za $25 na MC $84,000, 0 min 40 s nakon poziva, koncentracija: nepoznato", self.tid))
        self.lg.commit()
        self.pid = self.con.execute(
            "INSERT INTO positions (league_id, token, symbol, opened_ts, closed_ts, mode, status, reason, sol_in, sol_back, "
            "fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.tid, TOK3, "SPSC", self.entry, NOW - 3990, "dry", "closed", "copy KOL murad", 0.1, 0.083, 0.001)).lastrowid
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, status, reason) VALUES (?,?,?,?,?,?,?)",
                         (NOW - 3990, self.pid, TOK3, "sell", "dry", "dry", "auto: stop_loss"))
        self.con.commit()
        # the first call was never measured by kol/measure (mcap0 NULL); the minute check has its market cap
        self.add_call("murad", "m1", TOK3, self.entry - 40, mcap0=None)
        _exec(self.minute, ("INSERT INTO call_path (tweet_id, token, handle, ts, entry, mcap_e, hi60, lo60, r60) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", ("m1", TOK3, "murad", self.entry - 40, 0.00006, 60_000, 0.2,
                                                           -0.3, -0.1)))
        # murad's minute record BEFORE the entry: 3 tokens, 2 clean +10 % hits, 1 stop first; one after it (ignored)
        for i, (t10, sl, ts) in enumerate(((4, None, self.entry - 86400), (7, 30, self.entry - 2 * 86400),
                                           (None, 3, self.entry - 3 * 86400), (2, None, self.entry + 600))):
            _exec(self.minute, ("INSERT INTO call_path (tweet_id, token, handle, ts, entry, t10, sl_min) VALUES (?,?,?,?,?,?,?)",
                                (f"h{i}", f"tok{i}" + "a" * 36, "murad", ts, 1.0, t10, sl)))
        _exec(self.kol, ("INSERT INTO tokens (token, symbol, pair, supply) VALUES (?,?,?,?)", (TOK3, "SPSC", "pool3", 1e9)))
        # an influencer's wallet bought before the entry; the wallet scorer has not reached it (not in wallets.db)
        _exec(self.hype, ("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", ("s33", W3, TOK3, "buy", self.entry - 300, 1.2)))
        _exec(self.kol, ("INSERT INTO kol_ids VALUES (?,?,?,?,?,?,?)", (W3, "Pain", "https://x.com/PainCrypt0", None, 3.0, 5, 2)),
              ("INSERT INTO kols VALUES (?,?,?,?,?,?,0)", ("paincrypt0", "Pain", 41_000, 66.0, 1.0, "{}")))

    def trade(self, **kw):
        from ui import mcpdata
        return next(r for r in mcpdata.autopilot_trades(**kw)["rows"] if r["token"] == TOK3)

    def test_1_dry_trade_has_market_caps_runup_and_score(self):
        t = self.trade()
        self.assertEqual((t["mode"], t["status"], t["kind"]), ("dry", "closed", "position"))
        self.assertEqual((t["entry_market_cap"], t["entry_market_cap_source"]), (84_000, "copy_log"))
        self.assertEqual((t["exit_market_cap"], t["exit_market_cap_source"]), (69_700, "exit_price_x_supply"))
        sig = t["signals"]
        self.assertEqual((sig["first_call_market_cap"], sig["first_call_market_cap_source"]), (60_000, "minute"))
        self.assertEqual((sig["runup_from_first_call"], sig["runup_source"]), (0.4, "entry_mcap/minute"))
        self.assertEqual(sig["first_call_handle"], "murad")
        b = sig["follow_stats_before_entry"]
        self.assertEqual((b["n"], b["hit10"], b["stop_first"]), (3, 0.6667, 0.3333))   # the call after the entry is out
        self.assertEqual(sig["score_source"], "caller_pick_score_before_entry")
        self.assertAlmostEqual(sig["score_at_entry"], b["pick_score"])
        self.assertAlmostEqual(t["pnl_sol"], -0.018)

    def test_2_exit_rule_from_the_note_and_the_smart_stop(self):
        out = self.trade()
        self.assertEqual((out["exit_reason"], out["exit_rule_source"], out["exit_detail"]),
                         ("smart_sl", "demo_note", "stop_loss"))   # was "smart sell" next to "auto: stop_loss"
        pol = out["exit_policy"]
        self.assertEqual((pol["follow_exit_mode"], pol["trade_rule"], pol["stop_applied_pct"], pol["smart_sl_delay_min"]),
                         ("smart", "smart", -35.0, 5))
        self.assertIn("smart profile stop -35 %", pol["stop_applied"])
        from ui import mcpdata
        self.assertEqual(mcpdata.autopilot_trades()["account_sl_default_pct"], -60)   # not the -35 % that applied

    def test_2_exit_rule_column_and_stored_runup_win_when_present(self):
        have = {r[1] for r in self.lg.execute("PRAGMA table_info(trades)")}   # league/store may have added them
        for col, typ in (("runup", "REAL"), ("call_mcap", "REAL"), ("exit_rule", "TEXT")):
            if col not in have:
                self.lg.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
        self.lg.execute("UPDATE trades SET exit_rule='smart_trail', runup=0.12, call_mcap=75000, score=64, "
                        "entry_mcap=84000, exit_mcap=70000 WHERE id=?", (self.tid,))
        self.lg.commit()
        t = self.trade()
        self.assertEqual((t["exit_reason"], t["exit_rule_source"]), ("smart_trail", "exit_rule"))
        self.assertEqual((t["entry_market_cap_source"], t["exit_market_cap"]), ("demo_trade", 70_000))
        sig = t["signals"]
        self.assertEqual((sig["runup_from_first_call"], sig["runup_source"]), (0.12, "demo_trade"))
        self.assertEqual((sig["first_call_market_cap"], sig["first_call_market_cap_source"]), (75_000, "demo_trade"))
        self.assertEqual((sig["score_at_entry"], sig["score_source"]), (64.0, "demo_trade"))

    def test_2_tpsl_policy_names_its_stop_and_deadline(self):
        from ui import mcpdata
        self.lg.execute("UPDATE trades SET auto=? WHERE token=?", (json.dumps(
            {"mode": "tpsl", "tp": "+40%", "sl": "-60%", "tp_px": 1.4, "sl_px": 0.4, "until": NOW - 3600}), TOK))
        self.lg.commit()
        t = next(r for r in mcpdata.autopilot_trades()["rows"] if r["token"] == TOK)
        pol = t["exit_policy"]
        self.assertEqual((pol["follow_exit_mode"], pol["trade_rule"], pol["tp"], pol["stop_applied_pct"],
                          pol["hold_until_ts"]), ("tpsl", "tpsl", "+40%", -60.0, NOW - 3600))
        self.assertEqual(t["signals"]["follow"]["exit_mode"], "tpsl")

    def test_2_the_owners_button_on_the_real_position_is_manual(self):
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, status, reason) VALUES (?,?,?,?,?,?,?)",
                         (NOW - 3980, self.pid, TOK3, "sell", "dry", "dry", "prodaj sve (gumb)"))
        self.con.commit()
        t = self.trade()
        self.assertEqual((t["exit_reason"], t["exit_rule_source"]), ("manual", "real_order"))

    def test_2_exit_kind_words(self):
        from ui import mcpdata
        cases = {"auto TP +40%": "tp", "auto SL -60%": "sl", "auto SL $40k": "sl",
                 "auto vrijeme (ni TP ni SL u izmjerenom roku)": "time", "auto: stop_loss": "smart_sl",
                 "auto: take_profit_2x": "smart_tp", "auto: smart_sell_eksplozija": "smart_tp",
                 "auto: trailing": "smart_trail", "auto: moonbag_trailing": "smart_trail", "auto: breakeven": "smart_trail",
                 "auto: stale": "smart_other", "auto: time": "smart_other", "auto: rug": "rug", "stop_loss": "smart_sl",
                 "copy: ansem je prodao": "wallet_sold", "prodaj sve (gumb)": "manual", "ručna prodaja (gumb)": "manual",
                 "rekt: token bez cijene (rug ili mrtav), vrijedi $0": "rug", "rekt: račun pao na nulu": "manual",
                 "otpisano: nema cijene": "rug", "": None, None: None}
        for note, want in cases.items():
            self.assertEqual(mcpdata._exit_kind(note), want, note)
        self.assertEqual(mcpdata._exit_kind("auto: stop_loss", "sl"), "sl")        # the column wins
        self.assertEqual(mcpdata._exit_kind("auto TP +40%", "nonsense"), "tp")      # an unknown value does not

    def test_8_wallet_buy_of_an_influencer_wallet_has_handle_and_score(self):
        w = self.trade()["signals"]["wallet_buys_last_hour"]
        self.assertEqual(len(w), 1)
        self.assertEqual((w[0]["wallet"], w[0]["linked_handle"], w[0]["kind"]), (W3, "PainCrypt0", "influencer"))
        self.assertEqual((w[0]["tier"], w[0]["score"], w[0]["score_source"]), (None, 66.0, "linked_kol_call_power"))
        from ui import mcpdata
        lb = {r["wallet"]: r for r in mcpdata.wallet_leaderboard()["rows"]}
        self.assertEqual((lb[W3]["linked_handle"], lb[W3]["score"]), ("PainCrypt0", 66.0))
        self.assertEqual((lb[W1]["score"], lb[W1]["score_source"]), (50.0, "wallets"))   # a scored wallet keeps its own
        h = mcpdata.wallet_history(W3)
        self.assertEqual((h["linked_handle"], h["score"], h["kind"]), ("PainCrypt0", 66.0, "influencer"))

    def test_paper_follow_position_reads_paper_db(self):
        from ui import mcpdata
        _exec(os.environ["PAPER_DB"],
              "CREATE TABLE trades (id INTEGER PRIMARY KEY, token TEXT, symbol TEXT, opened_ts INTEGER, closed_ts INTEGER, "
              "status TEXT, exit_reason TEXT, size_usd REAL, entry_px REAL, entry_eff REAL, pnl_usd REAL, ret REAL, "
              "max_ret REAL, min_ret REAL, state TEXT, config TEXT)",
              "CREATE TABLE candidates (token TEXT PRIMARY KEY, symbol TEXT, first_ts INTEGER, origin TEXT, sources TEXT, "
              "score REAL, features TEXT, price REAL, liquidity REAL, mcap REAL, decision TEXT, reason TEXT, "
              "rug_verdict TEXT, rug_score REAL, rug_flags TEXT, trade_id INTEGER, url TEXT)",
              ("INSERT INTO trades (id, token, status, exit_reason) VALUES (77, ?, 'closed', 'trailing')", (TOK5,)),
              ("INSERT INTO candidates (token, score, mcap, trade_id) VALUES (?, 71.5, 120000, 77)", (TOK5,)))
        self.con.execute("INSERT INTO positions (paper_id, token, symbol, opened_ts, closed_ts, mode, status, reason, "
                         "sol_in, sol_back, fees_sol) VALUES (77,?,?,?,?,?,?,?,?,?,?)",
                         (TOK5, "PAP", NOW - 9000, NOW - 8000, "dry", "closed", "paper #77", 0.1, 0.12, 0.001))
        self.con.commit()
        t = next(r for r in mcpdata.autopilot_trades()["rows"] if r["token"] == TOK5)
        self.assertEqual((t["entry_market_cap"], t["entry_market_cap_source"]), (120_000, "paper"))
        self.assertEqual((t["exit_reason"], t["exit_rule_source"]), ("smart_trail", "paper"))
        self.assertEqual((t["signals"]["score_at_entry"], t["signals"]["score_source"]), (71.5, "paper_candidate"))


# ---------- 4: refused real positions --------------------------------------------------------------------------------

class Refused(Audit):
    def setUp(self):
        super().setUp()
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "0xMarko77", "0xMarko77", 25, 5, "tpsl", "30%", "")
        self.tid = store.buy(self.lg, settings.LEAGUE_USER, TOK6, "HOPE", 25, 0.0001, 50_000, "copy KOL 0xMarko77",
                             None, 95_000)
        self.lg.execute("UPDATE trades SET follow_id=? WHERE id=?", (fid, self.tid))
        self.lg.commit()
        why = ("praćenje bez dokaza u demu (zatvorenih 3, dobitnih 1, PnL -12 $; treba 10+ zatvorenih, PnL > 0 i 40%+ "
               "dobitnih)")
        self.blocked = self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason) "
                                        "VALUES (?,?,?,?,?,?,?)", (self.tid, TOK6, "HOPE", NOW - 1500, "live", "blocked",
                                                                   why)).lastrowid
        self.failed = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in) "
                                       "VALUES (?,?,?,?,?,?,0)", (TOK7, "FAIL", NOW - 1400, "live", "failed",
                                                                  "namjera zapisana, šaljem")).lastrowid
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, status, error) VALUES (?,?,?,?,?,?,?)",
                         (NOW - 1400, self.failed, TOK7, "buy", "live", "failed", "Jupiter: slippage prekoračen"))
        self.con.commit()

    def test_4_blocked_and_failed_positions_are_listed_with_the_reason(self):
        from ui import mcpdata
        out = mcpdata.autopilot_trades()
        by = {r["trade_id"]: r for r in out["rows"]}
        b = by[self.blocked]
        self.assertEqual((b["kind"], b["status"], b["mode"], b["token"]), ("refused", "blocked", "live", TOK6))
        self.assertIn("bez dokaza u demu", b["block_reason"])
        self.assertEqual((b["demo_trade"]["league_trade_id"], b["demo_trade"]["status"]), (self.tid, "open"))
        self.assertEqual(b["entry_market_cap"], 95_000)
        self.assertEqual(b["signals"]["follow"]["target"], "0xMarko77")
        self.assertIsNone(b["pnl_sol"])
        self.assertEqual(by[self.failed]["block_reason"], "Jupiter: slippage prekoračen")   # orders.error
        self.assertEqual([r["trade_id"] for r in mcpdata.autopilot_trades(status="blocked")["rows"]], [self.blocked])
        self.assertEqual(mcpdata.autopilot_trades(status="failed")["total"], 1)
        self.assertEqual(mcpdata.autopilot_trades(status="closed")["total"], 1)        # the base fixture's trade
        self.assertNotIn(self.blocked, [r["trade_id"] for r in mcpdata.unreviewed_trades()["rows"]])
        real = mcpdata.token_history(TOK6)["autopilot_real_positions"]
        self.assertIn("bez dokaza u demu", real[0]["block_reason"])
        res, err = self.call("get_autopilot_trades", {"status": "blocked"})
        self.assertFalse(err)
        self.assertEqual(res["rows"][0]["trade_id"], self.blocked)

    def test_4_demo_only_trades_on_request(self):
        from ui import mcpdata
        lone = store.buy(self.lg, settings.LEAGUE_USER, TOK4, "LONE", 25, 0.0002, 60_000, "ručno (pravi trade)", None, 70_000)
        n = mcpdata.autopilot_trades()["total"]
        out = mcpdata.autopilot_trades(include_demo_only=True)
        self.assertEqual(out["total"], n + 1)
        d = next(r for r in out["rows"] if r["kind"] == "demo_only")
        self.assertEqual((d["trade_id"], d["league_trade_id"], d["mode"], d["entry_market_cap"]), (None, lone, "demo", 70_000))


# ---------- 5: leaderboard -------------------------------------------------------------------------------------------

class Leaderboard(Audit):
    def setUp(self):
        super().setUp()
        for i in range(12):   # wick hunter: the 24 h high always reached +60 %, the 1 h result is -50 %
            self.add_call("goatgems", f"g{i}", f"goat{i:02d}" + "g" * 34, NOW - 86400 * 2 - i * 600, mcap0=80_000,
                          p0=0.001, r1h=-0.5, r24h=-0.9, max24=0.6)
        for i in range(12):   # steady: +8 / +12 % an hour after the call, no wick
            self.add_call("steady", f"s{i}", f"stdy{i:02d}" + "s" * 34, NOW - 86400 * 2 - i * 600, mcap0=80_000,
                          p0=0.001, r1h=0.08 if i % 2 else 0.12, r24h=0.1, max24=0.2)
        for i in range(12):   # small sample after the 30k rule: 7 of 12 calls were under $30k at the call
            self.add_call("tiny", f"t{i}", f"tiny{i:02d}" + "t" * 34, NOW - 86400 * 2 - i * 600,
                          mcap0=10_000 if i < 7 else 80_000, p0=0.001, r1h=0.5, r24h=0.5, max24=0.9)
        # minute check for steady: 10 of 12 clean +10 % hits
        for i in range(12):
            _exec(self.minute, ("INSERT INTO call_path (tweet_id, token, handle, ts, entry, r60, t10, sl_min) "
                                "VALUES (?,?,?,?,?,?,?,?)", (f"s{i}", f"stdy{i:02d}" + "s" * 34, "steady",
                                                             NOW - 86400 * 2 - i * 600, 0.001, 0.1,
                                                             3 if i < 10 else None, None if i < 10 else 5)))

    def test_5_default_rank_is_the_ev_lower_bound(self):
        from ui import mcpdata
        out = mcpdata.caller_leaderboard()
        self.assertEqual((out["sort"], out["min_measured"]), ("ev_lower", 10))
        self.assertEqual([r["handle"] for r in out["rows"]], ["steady", "goatgems"])   # tiny has 5 tradable calls
        goat, steady = out["rows"][1], out["rows"][0]
        self.assertEqual(goat["hit_rate"], 1.0)                                     # the wick says "always a hit"
        self.assertEqual((goat["ev_n"], goat["median_r1h_after_cost"], goat["ev_lower"]), (12, -0.52, -0.52))
        self.assertGreater(steady["ev_lower"], 0)
        self.assertAlmostEqual(steady["mean_r1h_after_cost"], 0.1 - 0.02)          # minute r60 0.1 - 2 % cost
        self.assertEqual((steady["minute_n"], steady["hit10_clean"]), (12, 0.8333))
        self.assertAlmostEqual(steady["hit10_wilson_low"], round(mcpdata.wilson_low(10, 12), 4))
        self.assertLess(steady["hit10_wilson_low"], steady["hit10_clean"])
        self.assertIn("WICK", out["definitions"]["hit_rate"])
        tiny = next(r for r in mcpdata.caller_leaderboard(min_measured=0, limit=500)["rows"] if r["handle"] == "tiny")
        self.assertEqual((tiny["calls"], tiny["ev_n"]), (12, 5))
        self.assertEqual(mcpdata.caller_leaderboard(min_measured=5, sort="median_r1h_after_cost")["rows"][0]["handle"],
                         "tiny")
        self.assertEqual(mcpdata.caller_leaderboard(sort="hit_rate")["rows"][0]["handle"], "goatgems")
        res, err = self.call("get_caller_leaderboard", {"min_measured": 0, "limit": 500})
        self.assertFalse(err)
        self.assertGreaterEqual(res["total"], 5)

    def test_5_tool_description_labels_the_wick(self):
        from ui import mcpapi
        d = next(t for t in mcpapi.TOOLS if t["name"] == "get_caller_leaderboard")
        self.assertIn("NOT tradable", d["description"])
        self.assertIn("min_measured", d["inputSchema"]["properties"])


# ---------- 6, 7: caller and token history ---------------------------------------------------------------------------

class History(Audit):
    def setUp(self):
        super().setUp()
        from kol import minute
        self.t_a = (NOW - 3 * 86400) // 60 * 60 + 20   # within 30 days, no call_path row, candles stored
        self.t_c = NOW - 2 * 86400                      # never measured; DexScreener snapshots exist
        self.add_call("ddddddd8a", "d1", TOK4, self.t_a, mcap0=90_000, p0=1.0)
        self.add_call("ddddddd8a", "d2", TOK5, self.t_c)
        self.add_call("ddddddd8a", "d3", TOK6, NOW - 5 * 86400, mcap0=20_000, p0=0.0001, r24h=-0.5,
                      measured_ts=NOW - 4 * 86400, complete=1)
        self.add_call("ddddddd8a", "d4", TOK7, NOW - 40 * 86400, mcap0=55_000, p0=0.0003, r1h=0.1, r24h=0.2,
                      measured_ts=NOW - 39 * 86400, complete=1)
        _exec(self.kol, ("INSERT INTO tokens (token, symbol, pair, supply) VALUES (?,?,?,?)", (TOK4, "DDD", "pool4", 1e9)),
              ("INSERT INTO tokens (token, symbol, pair, supply) VALUES (?,?,?,?)", (TOK6, "SIX", "pool6", 1e9)),
              ("INSERT INTO tokens (token, symbol, pair, supply) VALUES (?,?,?,?)", (TOK7, "SVN", "pool7", 1e9)),
              ("INSERT INTO snaps VALUES (?,?,?,?,?,?)", (TOK5, self.t_c + 300, 0.002, 1000, 20_000, 40_000)),
              ("INSERT INTO snaps VALUES (?,?,?,?,?,?)", (TOK5, self.t_c + 86400 + 100, 0.003, 500, 20_000, 60_000)))
        _exec(self.hype, ("INSERT INTO rug_archive (token, symbol, archived_ts) VALUES (?,?,?)", (TOK5, "FIVE", NOW)))
        m0 = self.t_a - self.t_a % 60
        candles = []
        for k in range(0, 61):
            o, h, lo, c = 1.0, 1.0, 1.0, 1.0
            if k == 10:
                h, c = 1.5, 1.2
            if k == 20:
                lo = 0.9
            candles.append((m0 + k * 60, o, h, lo, c, 100.0))
        _exec(self.minute, ("INSERT INTO call_candles VALUES (?,?,?,?,?,?,?)",
                            (TOK4, candles[0][0], candles[-1][0], len(candles), minute._pack(candles), 1, NOW)))

    def test_6_caller_history_fills_from_tokens_candles_and_snapshots(self):
        from ui import mcpdata
        out = mcpdata.caller_history("ddddddd8a")
        rows = {r["token"]: r for r in out["rows"]}
        a = rows[TOK4]
        self.assertEqual(a["symbol"], "DDD")                                       # kol.db tokens, calls.symbol empty
        self.assertEqual((a["max_1h"], a["min_1h"], a["max_1h_source"], a["minute_status"]),
                         (0.5, -0.1, "minute_candles", "measured"))
        self.assertEqual((a["change_1h"], a["change_1h_source"]), (0.0, "minute_candles"))
        c = rows[TOK5]
        self.assertEqual(c["symbol"], "FIVE")                                      # hype.db rug_archive
        self.assertEqual((c["price_at_call"], c["price_at_call_source"]), (0.002, "snapshots"))
        self.assertEqual((c["price_24h"], c["price_24h_source"], c["change_24h"]), (0.003, "snapshots", 0.5))
        self.assertEqual(c["measure_status"], "never_measured")
        self.assertEqual(c["minute_status"], "no_pair")
        d = rows[TOK6]
        self.assertEqual((d["minute_status"], d["measure_status"], d["price_24h"]), ("under_30k", "measured", 0.00005))
        e = rows[TOK7]
        self.assertEqual((e["minute_status"], e["change_1h_source"]), ("older_than_30d", "calls"))
        self.assertIn("minute_status", out["definitions"]["max_1h/min_1h"])
        mine = mcpdata.caller_history("ddddddd8a")["rows"]
        self.assertEqual(sum(1 for r in mine if r["symbol"]), 4)

    def test_7_token_history_followers_from_kols_and_tg(self):
        from ui import mcpdata
        self.add_call("0xMarko77", "x1", TOK, NOW - 6000, followers=0)
        self.add_call("tg:beta", "tg:beta/9", TOK, NOW - 5900, followers=0)
        _exec(self.kol, ("INSERT INTO kols VALUES (?,?,?,?,?,?,0)", ("0xmarko77", "Marko", 2863, 40.0, 1.0, "{}")))
        _exec(os.environ["TG_DB"], "CREATE TABLE channels (name TEXT PRIMARY KEY, title TEXT, subs INTEGER)",
              ("INSERT INTO channels VALUES ('beta', 'Beta', 777)",))
        calls = {c["handle"]: c for c in mcpdata.token_history(TOK)["calls"]}
        self.assertEqual((calls["0xMarko77"]["followers"], calls["0xMarko77"]["followers_source"]), (2863, "kols"))
        self.assertEqual(calls["0xMarko77"]["followers_at_call"], 0)
        self.assertEqual((calls["tg:beta"]["followers"], calls["tg:beta"]["followers_source"]), (777, "tg_channels"))
        self.assertEqual((calls["ansem"]["followers"], calls["ansem"]["followers_source"]), (500_000, "call"))
        lb = {r["handle"]: r for r in mcpdata.caller_leaderboard(min_measured=0, limit=500)["rows"]}
        self.assertEqual(lb["0xmarko77"]["followers"], calls["0xMarko77"]["followers"])


# ---------- 6: the night backfill of never-measured calls ------------------------------------------------------------

class Backfill(unittest.TestCase):
    def setUp(self):
        from kol import store as kstore
        self.tmp = tempfile.TemporaryDirectory()
        self.con = kstore.connect(os.path.join(self.tmp.name, "kol.db"))
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kol", "config.json")) as f:
            self.cfg = json.load(f)
        self.now = 1_794_200_000
        old = self.now - 30 * 3600
        rows = [("o1", "OLDx" + "a" * 36, "caller", old, "call"),          # never measured: due
                ("o2", "OLDy" + "b" * 36, "caller", old - 3600, "call"),   # never measured: due
                ("y1", "YNGx" + "c" * 36, "caller", self.now - 3600, "call"),   # young: kol/measure's queue
                ("w1", "WALx" + "d" * 36, "w:abc", old, "buy"),            # a wallet swap: never scored
                ("b1", "BOTx" + "e" * 36, "alertbot", old, "call")]        # an alert bot
        for tid, tok, h, ts, kind in rows:
            self.con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES (?,?,?,?,?)", (tid, tok, h, ts, kind))
            self.con.execute("INSERT INTO tokens (token, symbol, pair, supply, tries) VALUES (?,?,?,?,0)",
                             (tok, tok[:4], "pool" + tok[:4], 1e9))
        self.con.execute("INSERT INTO kols (handle, bot) VALUES ('alertbot', 1)")
        self.con.commit()
        self.asked = []

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def fetch(self, pool, start, end):
        self.asked.append(pool)
        out, ts = [], int(start) // 300 * 300
        while ts <= end:
            out.append((ts, 0.0001, 0.00012, 0.00009, 0.0001 if ts < start + 3 * 3600 else 0.0002, 50.0))
            ts += 300
        return out

    def test_due_picks_old_unmeasured_real_calls_only(self):
        from kol import backfill_calls
        toks = backfill_calls.due(self.con, self.now, 10)
        self.assertEqual([t[:4] for t in toks], ["OLDx", "OLDy"])
        self.assertEqual(backfill_calls.waiting(self.con, self.now), 3)   # the bot's call is counted, never measured

    def test_run_measures_within_the_caps_and_only_at_night(self):
        from kol import backfill_calls
        noon = 1_794_222_000   # 12:00 Zagreb; self.now is 05:53 Zagreb, inside the night window
        self.assertFalse(backfill_calls.run(5, con=self.con, cfg=self.cfg, now=noon, fetch=self.fetch, log=lambda *_: None)["ran"])
        self.assertEqual(self.asked, [])
        out = backfill_calls.run(1, con=self.con, cfg=self.cfg, now=self.now, fetch=self.fetch, log=lambda *_: None)
        self.assertEqual((out["ran"], out["requests"], out["calls"]), (True, 1, 1))
        self.assertEqual(self.asked, ["poolOLDx"])                             # newest first, budget 1
        p0, r24, mts = self.con.execute("SELECT p0, r24h, measured_ts FROM calls WHERE tweet_id='o1'").fetchone()
        self.assertEqual(p0, 0.0001)
        self.assertIsNotNone(r24)
        self.assertEqual(mts, self.now)
        self.assertEqual(backfill_calls.night_used(self.con, self.now), 1)
        saved = backfill_calls.NIGHT_CAP
        backfill_calls.NIGHT_CAP = 1
        try:
            out = backfill_calls.run(5, con=self.con, cfg=self.cfg, now=self.now, fetch=self.fetch, force=True,
                                     log=lambda *_: None)
            self.assertFalse(out["ran"])
            self.assertIn("strop", out["why"])
        finally:
            backfill_calls.NIGHT_CAP = saved


# ---------- 10: X features ---------------------------------------------------------------------------------------------

class XFeatures(Audit):
    def flag(self, mode):
        settings.put(self.con, "flag:x_features_ingest", {"mode": mode, "since": NOW, "who": "Jure"}, "Jure")

    def test_10_refused_while_the_flag_is_off(self):
        out, err = self.call("submit_x_features", {"subject": TOK, "features": {"ca_posts_1h": 3}, "ts_asof": NOW})
        self.assertTrue(err)
        self.assertIn("x_features_ingest", out["error"])
        self.assertFalse(os.path.exists(os.environ["XFEAT_DB"]))

    def test_10_insert_only_point_in_time_and_read_back(self):
        from ui import xfeat
        self.flag("shadow")
        hour = (NOW - 7200) // 3600 * 3600
        out, err = self.call("submit_x_features", {"subject": TOK, "subject_kind": "token", "ts_asof": hour + 3600,
                                                   "features": {"ca_posts_1h": 12, "ca_posts_hour_ts": hour}})
        self.assertFalse(err, out)
        self.assertEqual((out["status"], out["backfill"]), ("stored", False))
        self.assertLessEqual(abs(out["ts_observed"] - int(time.time())), 5)      # stamped by the server
        self.assertFalse(self.call("submit_x_features", {"subject": TOK, "ts_asof": hour + 3600,
                                                         "features": {"ca_posts_1h": 13, "ca_posts_hour_ts": hour}})[1])
        old = hour - 30 * 3600
        bad, err = self.call("submit_x_features", {"subject": TOK, "ts_asof": old, "features": {"ca_posts_1h": 1}})
        self.assertTrue(err)
        self.assertIn("backfill", bad["error"])
        self.assertFalse(self.call("submit_x_features", {"subject": TOK, "ts_asof": old, "backfill": True,
                                                         "features": {"ca_posts_1h": 1, "ca_posts_hour_ts": old - 3600}})[1])
        got, err = self.call("get_x_features", {"subject": TOK})
        self.assertFalse(err)
        self.assertEqual(got["total"], 3)                                         # both rows of the hour kept
        self.assertEqual([r["features"]["ca_posts_1h"] for r in got["rows"]], [13, 12, 1])
        self.assertEqual([r["backfill"] for r in got["rows"]], [False, False, True])
        self.assertTrue(got["rows"][0]["source"].startswith("mcp:"))
        self.assertEqual(self.call("get_x_features", {"subject": TOK, "since": hour})[0]["total"], 2)
        con = sqlite3.connect(os.environ["XFEAT_DB"])
        cols = [r[1] for r in con.execute("PRAGMA table_info(x_features)")]
        con.close()
        self.assertEqual(cols, ["id", "subject_kind", "subject", "ts_observed", "ts_asof", "features", "source",
                                "backfill", "created"])
        self.assertEqual(xfeat.read("@Ansem", "handle")["total"], 0)

    def test_10_validation_and_rate_limit(self):
        from ui import xfeat
        self.flag("paper")
        for args in ({"subject": "short", "ts_asof": NOW, "features": {"a": 1}},
                     {"subject": TOK, "ts_asof": NOW, "features": {}},
                     {"subject": TOK, "ts_asof": NOW, "features": "not json"},
                     {"subject": TOK, "ts_asof": NOW, "features": {"ca_posts_1h": -1}},
                     {"subject": TOK, "ts_asof": NOW, "features": {"ca_posts_1h": 1.5}},
                     {"subject": TOK, "ts_asof": NOW, "features": {"x" * 65: 1}},
                     {"subject": TOK, "ts_asof": NOW, "features": {"blob": "x" * 20_001}},
                     {"subject": TOK, "ts_asof": NOW + 3600, "features": {"a": 1}},
                     {"subject": TOK, "features": {"a": 1}},
                     {"subject": TOK, "subject_kind": "planet", "ts_asof": NOW, "features": {"a": 1}}):
            out, err = self.call("submit_x_features", args)
            self.assertTrue(err, args)
        self.assertFalse(self.call("submit_x_features", {"subject": "@Ansem", "subject_kind": "handle", "ts_asof": NOW,
                                                         "features": {"posts_1h": 4}})[1])
        self.assertEqual(xfeat.read("ansem", "handle")["total"], 1)
        saved = xfeat.RATE_PER_HOUR
        xfeat.RATE_PER_HOUR = 2
        try:
            self.assertFalse(self.call("submit_x_features", {"subject": TOK, "ts_asof": NOW, "features": {"a": 1}})[1])
            out, err = self.call("submit_x_features", {"subject": TOK, "ts_asof": NOW, "features": {"a": 1}})
            self.assertTrue(err)
            self.assertIn("rate limit", out["error"])
            self.assertFalse(self.call("submit_x_features", {"subject": TOK, "ts_asof": NOW, "features": {"a": 1}},
                                       key="k2")[1])
        finally:
            xfeat.RATE_PER_HOUR = saved

    def test_10_tools_listed_and_the_trade_lock_unchanged(self):
        from ui import mcpapi
        names = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(names["get_x_features"]["annotations"]["readOnlyHint"])
        self.assertFalse(names["submit_x_features"]["annotations"]["destructiveHint"])
        self.assertIn("ca_posts_1h", names["submit_x_features"]["description"])
        self.assertEqual(names["submit_x_features"]["inputSchema"]["required"], ["subject", "features", "ts_asof"])
        out, err = self.call("execute_trade", {"token_address": TOK, "amount": 0.05, "side": "buy",
                                               "require_approval": False})
        self.assertTrue(err)                                                     # never without the owner
        self.assertEqual(mcpapi.trade_request({"token": TOK, "side": "buy", "amount": 0.05,
                                               "require_approval": False})[0], 400)


if __name__ == "__main__":
    unittest.main()
