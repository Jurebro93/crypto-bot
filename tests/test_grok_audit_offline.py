"""10.11.2026 (Grok MCP audit of the production data, findings 1-5):

1. every demo trade carries, at OPEN and CLOSE, what the MCP API reads: runup, call_mcap, exit_rule (new columns,
   names and values are a contract with ui/mcpdata) and score (was NULL on every copy);
2. "auto: stop_loss" at -17 % with sl_default 60 is a Smart sell profile's own stop: exit_rule 'smart_sl';
3. flag runup_default: KOL / crew copies skip a token more than 10 % above its FIRST call (kol.db calls.p0, unknown =
   skip), and run_trade holds the real swap to the call's price + 10 %;
4. flag stop_grace: a proven follow's copy keeps its stop asleep for 3 minutes unless a rug flag fires;
5. flag caller_ev_rank: influencers ranked on point-in-time stats (kol/pit.py) by the lower bound of the EV.
Every flag: off = the old behaviour, shadow = logged in shadow_decisions, paper = the paper account, live = both
Autopilot accounts, never a player.

    python3 -m unittest tests.test_grok_audit_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from kol import minute, pit, store as kstore  # noqa: E402
from league import auto, copy, flags, store  # noqa: E402
from trade import executor, jupiter, settings  # noqa: E402

NOW = int(time.time())
TOK = "Grok1111111111111111111111111111111111pump"
TOK2 = "Grok2222222222222222222222222222222222pump"
AU, PU = settings.LEAGUE_USER, settings.PAPER_USER


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.envs = {k: os.environ.get(k) for k in ("KOL_DB", "HYPE_DB", "TG_DB", "MINUTE_DB", "WALLET_DB",
                                                    "TRADE_OWNER")}
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, copy._rugged, jupiter.order)
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.paths = {"kol": os.path.join(d, "kol.db"), "hype": os.path.join(d, "hype.db"),
                      "tg": os.path.join(d, "tg.db")}
        os.environ.update(KOL_DB=self.paths["kol"], HYPE_DB=self.paths["hype"], TG_DB=self.paths["tg"],
                          MINUTE_DB=os.path.join(d, "minute.db"), WALLET_DB=os.path.join(d, "wallets.db"),
                          TRADE_OWNER="Jure")
        settings._FLAG_CACHE.clear()
        copy._ADOPTED.clear()
        copy._rugged = lambda tok, mcap, liq: None
        auto._RUG_SEEN.clear()
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        self.k = kstore.connect(self.paths["kol"])
        self.k.execute("INSERT INTO kols (handle, score) VALUES ('goodkol', 72.5)")
        self.k.commit()

    def tearDown(self):
        (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, copy._rugged, jupiter.order) = self._saved
        for k, v in self.envs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings._FLAG_CACHE.clear()
        copy._ADOPTED.clear()
        for c in (self.con, self.lg, self.k):
            c.close()
        self.tmp.cleanup()

    def flag(self, name, mode):
        settings.put(self.con, f"flag:{name}", {"mode": mode, "since": NOW, "who": "test"})
        settings._FLAG_CACHE.clear()

    def call(self, tid, handle, ts, token=TOK, p0=None, mcap0=None):
        self.k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, p0, mcap0) VALUES (?,?,?,?,'call',?,?)",
                       (tid, token, handle, ts, p0, mcap0))
        self.k.commit()

    def follow(self, user="pravi", target="goodkol", **kw):
        user = AU if user == "pravi" else user
        args = dict(tp="50%", sl="-25%")
        args.update(kw)
        fid = copy.follow(self.lg, user, "kol", target, "", 25, 10, "tpsl", args["tp"], args["sl"])
        self.lg.execute("UPDATE follows SET created=?", (NOW - 3600,))
        self.lg.commit()
        return fid

    def market(self, price, m5=None):
        return lambda toks: {t: (price, 500_000, None, price * 1e6, "GRK", {"m5": m5, "h1": None}) for t in toks}

    def run_copy(self, price, m5=None):
        return copy.run_once(self.lg, self.market(price, m5), NOW, self.paths)

    def logged(self, user=AU):
        return {r["token"]: (r["action"], r["note"]) for r in copy.log(self.lg, user=user)}

    def shadows(self, name):
        return flags.shadow_rows(self.lg, name)


# ---------- 1 + 2: data columns ---------------------------------------------------------------------------------------

class DataColumns(Base):
    def test_the_columns_exist_and_old_closes_get_their_rule_from_the_note(self):
        cols = {r[1] for r in self.lg.execute("PRAGMA table_info(trades)")}
        self.assertTrue({"runup", "call_mcap", "exit_rule", "score"} <= cols)
        notes = {"auto: stop_loss": "smart_sl", "auto SL -60%": "sl", "auto TP +15%": "tp",
                 "auto vrijeme (ni TP ni SL u izmjerenom roku)": "time", "copy: Trader je prodao": "wallet_sold",
                 "": "manual", "auto: take_profit_1x": "smart_tp", "auto: trailing": "smart_trail",
                 "auto: stale": "smart_other", "auto: rug": "rug", "djelomična prodaja 50%": "manual"}
        for i, note in enumerate(notes):
            self.lg.execute("INSERT INTO trades (id, user, token, status, note, exit_px, size_usd) "
                            "VALUES (?, 'x', ?, 'closed', ?, 1.0, 25)", (100 + i, TOK, note))
        self.lg.execute("INSERT INTO trades (id, user, token, status, note, exit_px, size_usd) "
                        "VALUES (374, ?, ?, 'closed', 'auto: stop_loss', 0.83, 25)", (AU, TOK))
        self.lg.execute("INSERT INTO trades (id, user, token, status, note, exit_px, size_usd) "
                        "VALUES (375, 'x', ?, 'closed', 'otpisano: nema cijene', 0, 25)", (TOK,))
        self.lg.commit()
        store._backfill_exit_rule(self.lg)
        got = dict(self.lg.execute("SELECT note, exit_rule FROM trades WHERE id BETWEEN 100 AND 199"))
        self.assertEqual(got, notes)
        # finding 2: trade 374 SPSC was closed by the Smart sell profile's own stop (sl_default only exists on TP/SL)
        self.assertEqual(self.lg.execute("SELECT exit_rule FROM trades WHERE id=374").fetchone()[0], "smart_sl")
        self.assertEqual(self.lg.execute("SELECT exit_rule FROM trades WHERE id=375").fetchone()[0], "rug")
        self.assertTrue(set(notes.values()) <= set(store.EXIT_RULES))

    def test_a_copy_carries_score_runup_and_the_calls_mc_and_the_close_fills_what_was_unknown(self):
        self.call("first", "early", NOW - 3600, p0=1.0, mcap0=1e6)
        self.call("sig", "goodkol", NOW - 5)                     # the copied call: not measured yet
        self.follow()
        self.assertEqual(len(self.run_copy(1.08)), 1)
        t = store.trades(self.lg, AU, "open")[0]
        self.assertEqual(t["score"], 72.5)                      # kols.score of the copied account
        self.assertAlmostEqual(t["runup"], 0.08)                # entry 1.08 / first call's p0 1.0 - 1
        self.assertIsNone(t["call_mcap"])
        self.assertIsNone(t["exit_rule"])
        self.k.execute("UPDATE calls SET p0=1.05, mcap0=1.05e6 WHERE tweet_id='sig'")   # the KOL round measured it
        self.k.commit()
        self.assertEqual(len(auto.fast_once(self.lg, lambda toks: {x: (2.0, 5e5, None, 2e6) for x in toks}, AU)), 1)
        t = store.trades(self.lg, AU, "closed")[0]
        self.assertEqual((t["exit_rule"], t["call_mcap"]), ("tp", 1.05e6))
        self.assertAlmostEqual(t["runup"], 0.08)                # what was known at the entry stays

    def test_an_unmeasured_first_call_is_null_not_a_guess(self):
        self.call("first", "goodkol", NOW - 5)
        self.follow(user="Ivan")
        self.run_copy(1.5)
        t = store.trades(self.lg, "Ivan", "open")[0]
        self.assertIsNone(t["runup"])
        self.assertEqual(t["score"], 72.5)

    def test_stop_time_wallet_manual_partial_and_write_off_rules(self):
        tid = store.buy(self.lg, "Ivan", TOK, "G", 25, 1.0, 5e5)
        auto.set_auto(self.lg, "Ivan", tid, "tpsl", "50%", "-20%")
        auto.run_once(self.lg, lambda toks: {x: (0.7, 5e5, None, 7e5) for x in toks}, NOW)
        tid2 = store.buy(self.lg, "Ivan", TOK2, "G", 25, 1.0, 5e5)
        auto.set_auto(self.lg, "Ivan", tid2, "tpsl", "50%", "-20%", hold_s=60)
        auto.run_once(self.lg, lambda toks: {x: (1.0, 5e5, None, 1e6) for x in toks}, time.time() + 120)
        rules = dict(self.lg.execute("SELECT id, exit_rule FROM trades"))
        self.assertEqual((rules[tid], rules[tid2]), ("sl", "time"))
        t3 = store.buy(self.lg, "Ivan", TOK, "G", 25, 1.0, 5e5)
        pnl, whole = store.sell_partial(self.lg, "Ivan", t3, 0.5, 1.2, 5e5)
        self.assertFalse(whole)
        part = self.lg.execute("SELECT exit_rule FROM trades WHERE status='closed' AND note LIKE 'djelomična%'").fetchone()
        self.assertEqual(part[0], "manual")
        store.sell(self.lg, "Ivan", t3, 0, 0, "otpisano: nema cijene")
        self.assertEqual(self.lg.execute("SELECT exit_rule FROM trades WHERE id=?", (t3,)).fetchone()[0], "rug")

    def test_a_wallet_copy_that_mirrors_his_sale_is_wallet_sold(self):
        w = "W" * 44
        h = sqlite3.connect(self.paths["hype"])
        h.executescript("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL);")
        h.execute("INSERT INTO chain_trades VALUES ('s1', ?, ?, 'buy', ?, 1.0)", (w, TOK, NOW - 5))
        h.commit()
        copy.follow(self.lg, "Panda", "wallet", w, "Trader", 30, 5, "mirror")
        copy.run_once(self.lg, self.market(1.0), NOW, self.paths)
        h.execute("INSERT INTO chain_trades VALUES ('s2', ?, ?, 'sell', ?, NULL)", (w, TOK, NOW + 30))
        h.commit()
        h.close()
        copy.run_once(self.lg, self.market(1.2), NOW + 40, self.paths)
        self.assertEqual(store.trades(self.lg, "Panda", "closed")[0]["exit_rule"], "wallet_sold")

    def test_a_smart_profiles_own_stop_is_smart_sl(self):
        from paper import sim
        tid = store.buy(self.lg, AU, TOK, "SPSC", 25, 1.0, 5e5, "copy KOL x", None, 1.81e5)
        auto.set_auto(self.lg, AU, tid, "smart")
        cfg = dict(sim.load_config(learned=False), sl=-0.15, sl_delay_min=None)
        pos = sim.open_position(1.0, 5e5, NOW - 60, 25, cfg)
        self.lg.execute("UPDATE trades SET auto_state=? WHERE id=?", (json.dumps({"cfg": cfg, "pos": pos}), tid))
        self.lg.commit()
        done = auto.run_once(self.lg, lambda toks: {x: (0.83, 5e5, None, 1.5e5) for x in toks}, NOW)
        self.assertIn("stop_loss", done[0][2])
        t = store.trades(self.lg, AU, "closed")[0]
        self.assertEqual((t["note"], t["exit_rule"]), ("auto: stop_loss", "smart_sl"))

    def test_an_autopilot_manual_buy_gets_its_runup_from_the_first_call(self):
        self.call("first", "early", NOW - 3600, p0=0.5, mcap0=5e5)
        tid = store.buy(self.lg, AU, TOK, "G", 25, 0.6, 5e5, "ručno (pravi trade)", None, 6e5)
        self.assertAlmostEqual(self.lg.execute("SELECT runup FROM trades WHERE id=?", (tid,)).fetchone()[0], 0.2)
        pid = store.buy(self.lg, "Ivan", TOK2, "G", 25, 0.6, 5e5)
        self.assertIsNone(self.lg.execute("SELECT runup FROM trades WHERE id=?", (pid,)).fetchone()[0])


# ---------- 3: runup_default ------------------------------------------------------------------------------------------

class RunupDefault(Base):
    def setUp(self):
        super().setUp()
        self.call("first", "early", NOW - 3600, p0=1.0, mcap0=1e6)
        self.call("sig", "goodkol", NOW - 5)

    def test_off_is_the_old_rule_and_reads_no_first_call(self):
        fid = self.follow()
        self.assertNotIn("max_runup", copy.follows(self.lg, AU)[0]["exit"])
        reads = []
        saved = copy.first_call
        copy.first_call = lambda *a, **k: reads.append(a) or saved(*a, **k)
        try:
            self.assertEqual(len(self.run_copy(1.5, m5=40)), 1)      # +50 % over the first call: still entered
        finally:
            copy.first_call = saved
        self.assertEqual(len(reads), 1)                               # once, for the trade's data, not for the gate
        self.assertEqual(self.shadows("runup_default"), [])
        self.assertEqual(self.logged()[TOK][0], "ulaz")
        self.assertIsNotNone(fid)

    def test_shadow_enters_as_before_and_logs_the_skip(self):
        self.flag("runup_default", "shadow")
        self.follow()
        self.assertEqual(len(self.run_copy(1.5)), 1)
        (row,) = self.shadows("runup_default")
        self.assertEqual((row[3], row[4], row[5]), (TOK, "ulaz", "preskočeno"))
        self.assertAlmostEqual(json.loads(row[6])["runup"], 0.5)

    def test_live_skips_above_ten_percent_and_unknown_and_enters_below(self):
        self.flag("runup_default", "live")
        self.follow()
        self.assertIn("max_runup", copy.follows(self.lg, AU)[0]["exit"])          # follow() writes the flag's cap
        self.assertIn("od prvog poziva (zastavica)", copy.describe_exit(copy.follows(self.lg, AU)[0]["exit"]))
        self.assertEqual(self.run_copy(1.5), [])
        act, note = self.logged()[TOK]
        self.assertEqual(act, "preskočeno")
        self.assertIn("+50% iznad prvog poziva (early", note)
        # an unknown first-call price is a skip, logged in copy_log
        self.call("sig2", "goodkol", NOW - 4, token=TOK2)
        self.assertEqual(self.run_copy(1.05), [])
        self.assertIn("nepoznat", self.logged()[TOK2][1])

    def test_live_enters_within_ten_percent(self):
        self.flag("runup_default", "live")
        self.follow()
        self.assertEqual(len(self.run_copy(1.08)), 1)

    def test_players_never_and_paper_only_on_the_paper_account(self):
        self.flag("runup_default", "live")
        self.follow(user="Ivan")
        self.assertNotIn("max_runup", copy.follows(self.lg, "Ivan")[0]["exit"])
        self.assertEqual(len(self.run_copy(1.5)), 1)
        self.flag("runup_default", "paper")
        self.lg.execute("DELETE FROM trades")
        self.lg.execute("DELETE FROM copy_log")
        self.lg.execute("UPDATE follows SET active=0")
        self.lg.commit()
        self.follow()                       # the Autopilot's follow; the paper account gets a copy of it
        self.run_copy(1.5)
        self.assertEqual(len(store.trades(self.lg, AU, "open")), 1)            # live account: old rule
        self.assertEqual(store.trades(self.lg, PU, "open"), [])                # paper account: new rule
        self.assertIn("iznad prvog poziva", self.logged(PU)[TOK][1])
        self.assertEqual(len(self.shadows("runup_default")), 1)                # and the live account's shadow line

    def test_the_flags_cap_is_ignored_once_the_flag_is_off(self):
        self.flag("runup_default", "live")
        self.follow()
        self.flag("runup_default", "off")
        self.assertEqual(len(self.run_copy(1.5, m5=40)), 1)                    # an owner's cap would skip on m5 40 %


class RealLimit(Base):
    def setUp(self):
        super().setUp()
        self.cfg = {**settings.merged(executor.load_config(), self.con), "max_signal_age_s": 600, "sell_check": False}
        self.asked = []

    def demo(self, runup=0.05, entry=1.05, source="copy KOL goodkol"):
        fid = self.follow()
        cur = self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, "
                              "qty, source, follow_id, runup) VALUES (?,?,?,?,'open',25,?,?,20,?,?,?)",
                              (AU, TOK, "GRK", NOW, entry, entry * 1.02, source, fid, runup))
        self.lg.execute("INSERT INTO copy_log VALUES (?,?,'buy',?,?,'GRK','ulaz','x',?)", (fid, TOK, NOW - 2, NOW, cur.lastrowid))
        self.lg.commit()

    def quote(self, px):
        """A Jupiter order for the stake that pays px USD per token (pump.fun mint: 6 decimals)."""
        def order(i, o, a, taker=None, route="v2"):
            self.asked.append(route)
            usd = a / 1e9 * 200.0
            return {"inAmount": str(a), "outAmount": str(int(usd / px * 1e6)), "inUsdValue": usd, "outUsdValue": usd * 0.99}
        jupiter.order = order

    def mirror(self):
        run_trade.follow_league_once(self.con, self.cfg, NOW - 60, now=NOW + 1, quiet=True)
        return self.con.execute("SELECT status, reason FROM positions").fetchone()

    def test_live_blocks_a_swap_above_the_call_plus_ten_percent(self):
        self.flag("runup_default", "live")
        self.demo()                                  # call price 1.05 / 1.05 = 1.00 -> limit 1.10
        self.quote(1.2)
        st, why = self.mirror()
        self.assertEqual(st, "blocked")
        self.assertIn("limit cijene poziva", why)
        self.assertIn("+20% iznad prvog poziva", why)
        self.assertNotIn("pump", self.asked)          # PumpPortal swaps without a quote: never under a limit

    def test_live_buys_under_the_limit(self):
        self.flag("runup_default", "live")
        self.demo()
        self.quote(1.06)
        self.assertEqual(self.mirror()[0], "open")

    def test_live_without_a_known_runup_is_no_buy(self):
        self.flag("runup_default", "live")
        self.demo(runup=None)
        self.quote(1.0)
        st, why = self.mirror()
        self.assertEqual(st, "blocked")
        self.assertIn("nepoznat", why)
        self.assertEqual(self.asked, [])

    def test_off_and_shadow_buy_as_before_and_a_wallet_copy_is_never_limited(self):
        for mode in ("off", "shadow", "paper"):
            self.flag("runup_default", mode)
            self.assertEqual(run_trade._call_limit(self.lg, {"source": "copy KOL x", "id": 1}), (None, None))
        self.flag("runup_default", "live")
        self.assertEqual(run_trade._call_limit(self.lg, {"source": "copy wallet x", "id": 1}), (None, None))
        self.flag("runup_default", "off")
        self.demo()
        self.quote(5.0)                               # far above the call: the old behaviour does not look
        self.assertEqual(self.mirror()[0], "open")


# ---------- 4: stop_grace ---------------------------------------------------------------------------------------------

class StopGrace(Base):
    def setUp(self):
        super().setUp()
        self.call("sig", "goodkol", NOW - 5, p0=1.0, mcap0=1e6)

    def prove(self, fid, n=10, wins=6):
        for i in range(n):
            self.lg.execute("INSERT INTO trades (user, token, status, pnl_usd, size_usd, follow_id) "
                            "VALUES (?, ?, 'closed', ?, 25, ?)", (AU, f"P{i}", 5.0 if i < wins else -2.0, fid))
        self.lg.commit()

    def enter(self, mode="live", proven=True, user="pravi"):
        self.flag("stop_grace", mode)
        fid = self.follow(user=user)
        if proven:
            self.prove(fid)
        self.run_copy(1.0)
        u = AU if user == "pravi" else user
        (t,) = store.trades(self.lg, u, "open")
        return t, json.loads(t["auto"])

    def fast(self, price, liq=500_000, user=AU, now=None):
        return auto.fast_once(self.lg, lambda toks: {x: (price, liq, None, price * 1e6) for x in toks}, user, now=now)

    def test_the_flag_is_on_the_list_with_a_croatian_label(self):
        self.assertIn("stop_grace", settings.FLAGS)
        self.assertIn("bez stopa", settings.FLAGS["stop_grace"][1])
        self.assertEqual(copy.PROOF, run_trade.PROOF)

    def test_proof_is_run_trades_bar(self):
        fid = self.follow()
        self.prove(fid, n=9)
        self.assertFalse(copy.proven(self.lg, fid, AU))
        self.prove(fid, n=1, wins=1)
        self.assertTrue(copy.proven(self.lg, fid, AU))
        fid2 = self.follow(target="otherkol")
        self.prove(fid2, n=10, wins=3)                # 30 % winners
        self.assertFalse(copy.proven(self.lg, fid2, AU))

    def test_live_holds_the_stop_for_three_minutes(self):
        t, a = self.enter()
        self.assertEqual(a["grace_until"], t["opened_ts"] + copy.GRACE_S)
        self.assertIn("stop miruje", self.logged()[TOK][1])
        self.assertEqual(self.fast(0.7), [])                                   # -30 %: under the -25 % stop, held
        self.assertEqual(len(store.trades(self.lg, AU, "open")), 1)
        done = self.fast(0.7, now=t["opened_ts"] + copy.GRACE_S + 1)          # after the grace: the stop fires
        self.assertIn("SL", done[0][2])
        self.assertEqual(store.trades(self.lg, AU, "closed")[0]["exit_rule"], "sl")

    def test_tp_fires_inside_the_grace(self):
        self.enter()
        self.assertIn("TP", self.fast(1.6)[0][2])

    def test_a_rug_flag_ends_the_grace(self):
        self.enter()
        self.fast(0.45)                                                         # under half of the entry
        self.assertEqual(store.trades(self.lg, AU, "closed")[0]["exit_rule"], "rug")

    def test_a_pool_that_collapsed_ends_the_grace(self):
        self.enter()
        self.assertEqual(self.fast(0.7, liq=50_000)[0][0], AU)                 # liquidity under a fifth of the entry
        self.assertEqual(store.trades(self.lg, AU, "closed")[0]["exit_rule"], "rug")

    def test_rugfilter_collapse_ends_the_grace(self):
        self.enter()
        copy._rugged = lambda tok, mcap, liq: {"text": "pao 75 % s vrha"}
        self.assertEqual(len(self.fast(0.7)), 1)

    def test_an_unproven_follow_gets_no_grace(self):
        _, a = self.enter(proven=False)
        self.assertNotIn("grace_until", a)

    def test_off_stores_nothing(self):
        _, a = self.enter(mode="off")
        self.assertNotIn("grace_until", a)
        self.assertEqual(len(self.fast(0.7)), 1)

    def test_shadow_stops_as_before_and_logs_what_the_grace_would_hold(self):
        _, a = self.enter(mode="shadow")
        self.assertIn("grace_until", a)
        self.assertNotIn("stop miruje", self.logged()[TOK][1])
        self.assertEqual(len(self.fast(0.7)), 1)                               # the stop fires
        (row,) = self.shadows("stop_grace")
        self.assertEqual((row[4], row[5]), ("stop", "drži (grace)"))

    def test_a_flag_switched_off_after_the_entry_changes_nothing(self):
        self.enter()
        self.flag("stop_grace", "off")
        self.assertEqual(len(self.fast(0.7)), 1)
        self.assertEqual(self.shadows("stop_grace"), [])

    def test_paper_holds_on_the_paper_account_and_logs_for_the_live_one(self):
        self.flag("stop_grace", "paper")
        fid = self.follow()
        self.prove(fid)
        self.run_copy(1.0)
        pt = store.trades(self.lg, PU, "open")
        self.assertEqual(len(pt), 1)                                            # judged on the follow it copies
        self.assertIn("grace_until", json.loads(pt[0]["auto"]))
        done = auto.fast_once(self.lg, lambda toks: {x: (0.7, 5e5, None, 7e5) for x in toks}, (AU, PU))
        self.assertEqual([u for u, _, _ in done], [AU])
        self.assertEqual(len(store.trades(self.lg, PU, "open")), 1)
        self.assertEqual(len(self.shadows("stop_grace")), 1)

    def test_players_never(self):
        self.flag("stop_grace", "live")
        fid = copy.follow(self.lg, "Ivan", "kol", "goodkol", "", 25, 10, "tpsl", "50%", "-20%")
        self.lg.execute("UPDATE follows SET created=?", (NOW - 3600,))
        self.lg.commit()
        self.prove(fid)
        self.run_copy(1.0)
        self.assertNotIn("grace_until", json.loads(store.trades(self.lg, "Ivan", "open")[0]["auto"]))

    def test_a_smart_profiles_stop_is_held_too(self):
        from paper import sim
        self.flag("stop_grace", "live")
        tid = store.buy(self.lg, AU, TOK, "G", 25, 1.0, 5e5, "copy KOL x")
        self.lg.execute("UPDATE trades SET auto=? WHERE id=?",
                        (json.dumps({"mode": "smart", "grace_until": NOW + 120, "grace_liq": 5e5}), tid))
        cfg = dict(sim.load_config(learned=False), sl=-0.15, sl_delay_min=None)
        st = json.dumps({"cfg": cfg, "pos": sim.open_position(1.0, 5e5, NOW - 30, 25, cfg)})
        self.lg.execute("UPDATE trades SET auto_state=? WHERE id=?", (st, tid))
        self.lg.commit()
        mk = lambda toks: {x: (0.83, 5e5, None, 8.3e5) for x in toks}   # noqa: E731
        self.assertEqual(auto.run_once(self.lg, mk, NOW), [])
        self.assertEqual(self.lg.execute("SELECT auto_state FROM trades WHERE id=?", (tid,)).fetchone()[0], st)
        self.assertIn("stop_loss", auto.run_once(self.lg, mk, NOW + 121)[0][2])
        self.assertEqual(store.trades(self.lg, AU, "closed")[0]["exit_rule"], "smart_sl")


# ---------- 5: caller_ev_rank -----------------------------------------------------------------------------------------

WIN = {"u": {"10": 2, "15": 3, "20": 5, "30": 8, "50": 20}, "d": {}, "v": 2}
LOSS = {"u": {}, "d": {"10": 1, "15": 1, "20": 2, "25": 2, "30": 2, "40": 3, "50": 4, "60": 5}, "v": 2}


class CallerEvRank(Base):
    def setUp(self):
        super().setUp()
        self.mc = minute.connect(os.environ["MINUTE_DB"])
        self.t0 = NOW - NOW % 60
        self.i = 0

    def tearDown(self):
        self.mc.close()
        super().tearDown()

    def put(self, handle, win, ts, token=None):
        self.i += 1
        lv = WIN if win else LOSS
        self.mc.execute("INSERT INTO call_path (tweet_id, token, handle, ts, entry, lag_s, lo60, r60, t10, sl_min, "
                        "first_caller, measured_ts) VALUES (?,?,?,?,1.0,10,?,?,?,?,1,?)",
                        (str(self.i), token or f"T{self.i}", handle, ts, -0.05 if win else -0.65, 0.2 if win else -0.6,
                         2 if win else None, None if win else 2, ts + 4000))
        self.mc.execute("INSERT INTO call_lv VALUES (?,?,?,?)", (str(self.i), token or f"T{self.i}", ts, json.dumps(lv)))
        self.mc.commit()

    def history(self, handle, pattern, start=None):
        for j, ch in enumerate(pattern):
            self.put(handle, ch == "W", (start or self.t0 - 5 * 86400) + j * 3000)

    def test_only_calls_whose_hour_closed_before_t0_count(self):
        self.history("good", "WWWWWWWWWWWW")
        before = pit.stats_at("good", self.t0, self.mc, 14, 15, 60)
        self.assertEqual(before["n"], 12)
        self.put("good", False, self.t0 - 1800)        # posted before t0, its hour still open
        self.put("good", False, self.t0 + 600)         # the future
        self.assertEqual(pit.stats_at("good", self.t0, self.mc, 14, 15, 60), before)
        self.assertEqual(pit.stats_at("good", self.t0 + 7200, self.mc, 14, 15, 60)["n"], 14)

    def test_ev_bound_ranks_and_ten_calls_are_needed(self):
        self.history("good", "WWWWWWWWLWWW")
        self.history("bad", "LLLLWLLLLLLL")
        self.put("Kirodev7", True, self.t0 - 2 * 86400)
        stats = pit.all_stats(self.mc, self.t0, 14, 15, 60)
        ranked = autopilot_rank(stats)
        self.assertEqual(list(ranked), ["good"])
        s = ranked["good"]
        self.assertEqual((s["rank"], s["mjera"]), ("ev", "minutna"))
        self.assertAlmostEqual(s["score"], stats["good"]["ev_lo"])
        self.assertLess(s["score"], stats["good"]["ev"])

    def test_a_future_call_never_changes_a_past_rank(self):
        self.history("good", "WWWWWWWWLWWW")
        self.history("ok", "WWWWWWWLLWWWW", start=self.t0 - 4 * 86400)
        before = autopilot_rank(pit.all_stats(self.mc, self.t0, 14, 15, 60))
        for k in range(15):                            # a run of losses after t0, and one still in its hour
            self.put("good", False, self.t0 + 100 + k * 60)
        self.put("ok", True, self.t0 - 600)
        after = autopilot_rank(pit.all_stats(self.mc, self.t0, 14, 15, 60))
        self.assertEqual({h: s["score"] for h, s in after.items()}, {h: s["score"] for h, s in before.items()})

    def test_kol_recs_under_the_flag_reads_no_24h_wick(self):
        from ui import autopilot, copytrade
        self.history("good", "WWWWWWWWLWWW")
        self.k.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24) VALUES ('w', 'X', 'wick', ?, "
                       "'call', 9.0)", (self.t0 - 3 * 86400,))
        self.k.commit()
        saved = copytrade.kol_rows
        copytrade.kol_rows = lambda *a, **k: [{"handle": h, "live": True} for h in ("good", "wick")]
        autopilot.clear()
        try:
            rows = autopilot.kol_recs(now=self.t0, ev=True)[14]
            self.assertEqual([r["handle"] for r in rows], ["good"])
            self.assertIn("donja granica", rows[0]["why"])
            self.assertNotIn("24 h", rows[0]["why"])
            self.flag("caller_ev_rank", "off")
            self.assertEqual(autopilot.ev_flag(), (False, False))
            self.flag("caller_ev_rank", "live")
            self.assertEqual(autopilot.ev_flag(), (True, False))
            self.flag("caller_ev_rank", "shadow")
            self.assertEqual(autopilot.ev_flag(), (False, True))
        finally:
            copytrade.kol_rows = saved
            autopilot.clear()


def autopilot_rank(stats):
    from ui import autopilot
    return autopilot.kol_rank({}, {}, stats)


class CallerEvRankSync(Base):
    def setUp(self):
        super().setUp()
        from ui import autopilot
        self.ap = autopilot
        st_old = {"hit": 0.5, "n": 4, "mjera": "minutna", "score": 0.5}
        st_new = {"n": 12, "mjera": "minutna", "rank": "ev", "score": 3.0, "pit": {"n": 12, "ev": 9.0, "ev_lo": 3.0}}
        self.recs = {False: [{"handle": "kirodev7", "live": True, "why": "stari", "s": st_old}],
                     True: [{"handle": "good", "live": True, "why": "EV", "s": st_new}]}
        self._ap = (autopilot.kol_recs, autopilot.wallet_recs, autopilot.proven_wallets)
        autopilot.kol_recs = lambda now=None, ev=None: {14: self.recs[bool(ev)]}
        autopilot.wallet_recs = lambda now=None: {14: []}
        autopilot.proven_wallets = lambda: []
        settings.put(self.con, "auto_pick", True)
        settings.put(self.con, "auto_days", 14)
        settings.put(self.con, "auto_n", 1)

    def tearDown(self):
        self.ap.kol_recs, self.ap.wallet_recs, self.ap.proven_wallets = self._ap
        super().tearDown()

    def picked(self):
        return {f["target"] for f in copy.follows(self.lg, AU) if f["kind"] == "kol"}

    def test_off_picks_by_the_old_rank_and_logs_nothing(self):
        self.ap.sync_follows(self.lg, self.con, force=True)
        self.assertEqual(self.picked(), {"kirodev7"})
        self.assertEqual(self.shadows("caller_ev_rank"), [])

    def test_live_picks_by_the_ev_rank(self):
        self.flag("caller_ev_rank", "live")
        self.ap.sync_follows(self.lg, self.con, force=True)
        self.assertEqual(self.picked(), {"good"})

    def test_shadow_picks_by_the_old_rank_and_logs_the_difference(self):
        self.flag("caller_ev_rank", "shadow")
        self.ap.sync_follows(self.lg, self.con, force=True)
        self.assertEqual(self.picked(), {"kirodev7"})
        got = {(r[3], r[4], r[5]) for r in self.shadows("caller_ev_rank")}
        self.assertEqual(got, {("good", "ne prati", "prati"), ("kirodev7", "prati", "ne prati")})


if __name__ == "__main__":
    unittest.main()
