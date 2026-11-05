"""Strategy comparison on synthetic sources and prices: each of the five $1000 accounts buys only from its own source,
late signals and caps are respected, the shared exit rules close trades, the account value adds up, Mix needs two
groups, the random control is rate-limited, and the page and report render."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strat import run, signals, store  # noqa: E402

A = "HgxEGTZ1Epb64RrYqcuHkqb1gGWWnF5WcPTCDWzApump"
B = "8uBobWMhu6hRUn4jaA4kjcgWCjTxgHwHJtPgBePXpump"
C = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
T0 = 1793390000

EX = {"fee": 0.01, "sl": -0.35, "tp": [[1.0, 0.5], [3.0, 0.25]], "breakeven_after_tp": True, "trail_after": 0.5,
      "trail": 0.3, "max_hold_h": 24, "rug_liq": 0.2}


class FakeSources:
    def __init__(self):
        self.data = {"novcanici": [], "kol": [], "alat": [], "scored": []}

    def read(self, now, window_s):
        return {k: [e for e in v if e[1] <= now] for k, v in self.data.items()}


class Strat(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "strat.db")
        self.cfg = run.load_config()
        for st in self.cfg["strategies"]:   # the live top-ups (5.11.) would shift every account value below
            st.pop("topups", None)
        # the mechanics are tested with every strategy live; freezing has its own test
        self.cfg["strategies"] = [{k: v for k, v in s.items() if k != "frozen"} for s in self.cfg["strategies"]]
        self.src = FakeSources()
        self.px = {A: 1.0, B: 1.0, C: 1.0}

    def mk(self, toks):
        return {t: (self.px[t], 50000, self.px[t] * 1e6, "SYM", "https://dexscreener.com/x") for t in toks
                if t in self.px}

    def step(self, now):
        return run.step(now=now, cfg=self.cfg, path=self.db, market_fn=self.mk, sources=self.src, ex=EX, quiet=True)

    def rows(self, where="status IN ('open','closed')"):
        con = store.connect(self.db)
        try:
            return store.rows(con, where)
        finally:
            con.close()

    def test_each_strategy_buys_from_its_source(self):
        self.step(T0)
        self.src.data["novcanici"] = [(A, T0 + 30, "novčanik @x", 0)]
        self.src.data["kol"] = [(B, T0 + 30, "kolB", 50)]
        self.src.data["alat"] = [(C, T0 + 30, "demo bot kupio (ocjena)", 1)]
        r = self.step(T0 + 60)
        self.assertEqual(r["entered"], 3)
        got = {(p["strat"], p["token"]) for p in self.rows()}
        # price 1.0 x 1e6 supply = $1M market cap: only the large-cap band of the tool's picks buys it
        self.assertEqual(got, {("top_novcanici", A), ("kol", B), ("alat_veliki", C)})
        for p in self.rows():
            self.assertEqual(p["size_usd"], self.cfg["size_usd"])

    def test_frozen_strategy_takes_no_new_entries(self):
        # 5.11. popodne: Top novčanici unfrozen and topped up (strat/config.json "topups"), the freeze flag still works
        live = [s for s in run.load_config()["strategies"] if s["key"] == "top_novcanici"][0]
        self.assertFalse(live.get("frozen"))
        self.assertEqual(sum(t["usd"] for t in live["topups"]), 1000)
        for s in self.cfg["strategies"]:
            if s["key"] == "top_novcanici":
                s["frozen"], s["frozen_why"] = True, "test"
        self.step(T0)
        self.src.data["novcanici"] = [(A, T0 + 30, "novčanik @x", 0)]
        self.src.data["kol"] = [(B, T0 + 30, "kolB", 50)]
        self.step(T0 + 60)
        self.assertEqual({p["strat"] for p in self.rows()}, {"kol"})
        con = store.connect(self.db)
        try:
            st = {x["key"]: x["status"] for x in run.summary(con, self.cfg, EX)}
        finally:
            con.close()
        self.assertEqual(st["top_novcanici"][0], "zamrznuto")

    def test_late_signal_and_before_start_skipped(self):
        self.step(T0)
        self.src.data["kol"] = [(A, T0 - 100, "old", 50), (B, T0 + 10, "late", 50)]
        self.step(T0 + 10 + self.cfg["max_delay_min"] * 60 + 5)
        self.assertEqual(self.rows(), [])

    def test_hourly_cap(self):
        self.step(T0)
        toks = [A[:-6] + f"{i:02d}pump" for i in range(self.cfg["per_hour"] + 3)]
        for t in toks:
            self.px[t] = 1.0
        self.src.data["novcanici"] = [(t, T0 + 30, "w", 0) for t in toks]
        self.step(T0 + 60)
        self.assertEqual(len(self.rows()), self.cfg["per_hour"])

    def test_topup_raises_the_account_and_the_return_is_on_the_total(self):
        for s in self.cfg["strategies"]:
            if s["key"] == "kol":
                s["topups"] = [{"ts": T0, "usd": 1000, "why": "test"}]
        self.step(T0)
        con = store.connect(self.db)
        try:
            acc = run.accounts(con, self.cfg)
            summ = {x["key"]: x for x in run.summary(con, self.cfg, EX)}
        finally:
            con.close()
        self.assertEqual((acc["kol"]["cash"], acc["kol"]["topup"]), (2000, 1000))
        self.assertAlmostEqual(summ["kol"]["ret"], 0.0)
        self.assertEqual(acc["top_novcanici"]["topup"], 0)

    def test_no_cash_limit_keeps_buying(self):
        """Nicholas 4.11.: strategies trade on after their $1000 is spent (cash_limit false), always the full stake."""
        self.cfg = {**self.cfg, "bankroll_usd": 60, "cash_limit": False}
        self.step(T0)
        toks = [A[:-6] + f"{i:02d}pump" for i in range(3)]
        for t in toks:
            self.px[t] = 1.0
        self.src.data["novcanici"] = [(t, T0 + 30, "w", 0) for t in toks]
        self.step(T0 + 60)
        self.step(T0 + 120)
        r = self.rows()
        self.assertEqual(len(r), 3)
        self.assertTrue(all(p["size_usd"] == self.cfg["size_usd"] for p in r))
        self.cfg["cash_limit"] = True   # the old rule: stops when the account has no money
        self.d2 = tempfile.mkdtemp()
        self.db = os.path.join(self.d2, "strat.db")
        self.step(T0)
        self.step(T0 + 60)
        self.step(T0 + 120)
        self.assertLess(len(self.rows()), 3)

    def test_exit_rules_and_account_value(self):
        self.step(T0)
        self.src.data["kol"] = [(A, T0 + 30, "kolA", 50)]
        self.step(T0 + 60)
        self.px[A] = 0.5          # -50%: stop loss
        self.step(T0 + 120)
        p = self.rows()[0]
        self.assertEqual(p["status"], "closed")
        self.assertEqual(p["exit_reason"], "stop_loss")
        self.assertLess(p["pnl_usd"], -20)
        con = store.connect(self.db)
        try:
            acc = run.accounts(con, self.cfg, ex=EX)
            summ = {s["key"]: s for s in run.summary(con, self.cfg, EX)}
        finally:
            con.close()
        self.assertAlmostEqual(acc["kol"]["value"], 1000 + p["pnl_usd"], places=2)
        self.assertAlmostEqual(acc["kol"]["cash"], acc["kol"]["value"], places=2)
        self.assertEqual(acc["top_novcanici"]["value"], 1000)
        self.assertEqual(summ["kol"]["closed"], 1)
        self.assertEqual(summ["kol"]["hit"], 0)

    def test_take_profit_win_and_open_marking(self):
        self.step(T0)
        self.src.data["alat"] = [(A, T0 + 30, "demo", 1)]
        self.step(T0 + 60)
        self.px[A] = 2.2          # +120%: half sold at +100%
        self.step(T0 + 120)
        p = self.rows()[0]
        self.assertEqual(p["status"], "open")
        self.assertTrue(p["state"]["fills"])
        con = store.connect(self.db)
        try:
            a = run.accounts(con, self.cfg, ex=EX)["alat_veliki"]
        finally:
            con.close()
        self.assertGreater(a["value"], 1040)
        self.assertGreater(a["cash"], 950)   # stake back from the take profit

    def test_fake_pool_and_low_liquidity_skipped(self):
        self.step(T0)
        self.src.data["kol"] = [(A, T0 + 30, "k", 50)]

        def mk(toks):
            return {t: (1.0, 2e6, 1e6, "SYM", "u") for t in toks}   # liquidity above market cap
        run.step(now=T0 + 60, cfg=self.cfg, path=self.db, market_fn=mk, sources=self.src, ex=EX, quiet=True)
        s = self.rows("status='skip'")
        self.assertEqual(s[0]["close_reason"], "lažni pool")

    def test_pair_gone_for_hours_is_a_rug(self):
        self.step(T0)
        self.src.data["kol"] = [(A, T0 + 30, "k", 50)]
        self.step(T0 + 60)
        del self.px[A]
        self.step(T0 + 120)
        self.assertEqual(self.rows()[0]["status"], "open")
        self.step(T0 + 120 + self.cfg["missing_h"] * 3600 + 60)
        p = self.rows()[0]
        self.assertEqual(p["status"], "closed")
        self.assertLess(p["pnl_usd"], -49)

    def test_mix_needs_two_groups(self):
        src = {"novcanici": [(A, T0, "w", 0)], "kol": [(A, T0 + 600, "k", 50), (B, T0, "k", 50)],
               "alat": [], "scored": [(B, T0 + 7200, "ocjena 80", 80), (C, T0, "ocjena 10", 10)]}
        m = signals.mix(src, 50, 3600)
        self.assertEqual([(t, ts) for t, ts, _, _ in m], [(A, T0 + 600)])   # B: too far apart, C: one group

    def test_random_control_rate_limited(self):
        src = {"scored": [(A, T0, "x", 1), (B, T0, "x", 1)]}
        self.assertEqual(len(signals.random_pick(src, T0 + 10, 0, 1800, seed=1)), 1)
        self.assertEqual(signals.random_pick(src, T0 + 10, T0, 1800), [])

    def test_sources_read_filters_bots_and_konv(self):
        kol = os.path.join(self.d, "kol.db")
        con = sqlite3.connect(kol)
        con.executescript("CREATE TABLE kols (handle TEXT, score REAL, bot INTEGER, stats TEXT);"
                          "CREATE TABLE kol_ids (wallet TEXT, twitter TEXT, name TEXT);"
                          "CREATE TABLE calls (token TEXT, ts INTEGER, handle TEXT, kind TEXT, source TEXT);")
        con.execute("""INSERT INTO kols VALUES ('good', 70, 0, '{}'), ('spam', 10, 1, NULL),
                       ('new', 40, 0, '{"trial": true}')""")
        con.execute("INSERT INTO kol_ids VALUES ('W1', 'whale', NULL)")
        con.executemany("INSERT INTO calls VALUES (?,?,?,'call','x')", [(A, T0, "good"), (B, T0, "spam"), (C, T0, "new")])
        con.commit()
        con.close()
        hype = os.path.join(self.d, "hype.db")
        con = sqlite3.connect(hype)
        con.executescript("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER);"
                          "CREATE TABLE hype_signals (token TEXT, ts INTEGER, score REAL);"
                          "CREATE TABLE kol_mentions (handle TEXT, ca TEXT, ts INTEGER);")
        con.execute("INSERT INTO chain_trades VALUES ('s', 'W1', ?, 'buy', ?)", (C, T0))
        con.execute("INSERT INTO chain_trades VALUES ('s2', 'W1', ?, 'sell', ?)", (A, T0))
        con.commit()
        con.close()
        paper = os.path.join(self.d, "paper.db")
        con = sqlite3.connect(paper)
        con.execute("CREATE TABLE trades (token TEXT, opened_ts INTEGER, config TEXT)")
        con.execute("INSERT INTO trades VALUES (?, ?, ?)", (A, T0, json.dumps({"entry_mode": "konv"})))
        con.execute("INSERT INTO trades VALUES (?, ?, ?)", (B, T0, json.dumps({"entry_mode": "explore"})))
        con.commit()
        con.close()
        s = signals.Sources(kol_db=kol, tg_db=os.path.join(self.d, "none.db"), hype_db=hype, paper_db=paper)
        out = s.read(T0 + 60, 3600)
        self.assertEqual([e[0] for e in out["kol"]], [A])
        self.assertEqual([(e[0], e[2]) for e in out["novcanici"]], [(C, "novčanik @whale")])
        self.assertEqual([e[0] for e in out["alat"]], [B])

    def test_page_and_report(self):
        self.step(T0)
        self.src.data["kol"] = [(A, T0 + 30, "kolA", 50)]
        self.src.data["novcanici"] = [(B, T0 + 30, "w", 0)]
        self.step(T0 + 60)
        self.step(T0 + 60 + 16 * 60)
        self.px[A] = 0.5
        self.step(T0 + 60 + 32 * 60)
        old = store.DB
        store.DB = self.db
        from ui import strategije
        orig = run.exit_rules
        run.exit_rules = lambda now: EX
        try:
            title, body = strategije.page({})
            rep = strategije.report_data(T0 + 3000)
        finally:
            store.DB = old
            run.exit_rules = orig
        self.assertEqual(title, "Usporedba strategija")
        for s in self.cfg["strategies"]:
            self.assertIn(s["name"], body)
        self.assertIn("<svg", body)
        self.assertEqual(len(rep), 9)   # 5 + insajderi + ozbiljan projekt + sumnjivi socijali + veliki račun (5.11.)
        self.assertEqual(rep[-1]["key"], "kol")      # the stopped-out account is last
        from report import ai, collect, render
        os.environ["REPORT_DB_DIR"] = tempfile.mkdtemp()
        try:
            d = collect.collect(T0 + 3000)
        finally:
            del os.environ["REPORT_DB_DIR"]
        d["strategije"] = rep
        html = render.render(d, ai.fallback(d), "pravila")
        self.assertIn("Usporedba strategija", html)
        self.assertIn("/strategije", html)


class TopWalletsAndBands(unittest.TestCase):
    """Nicholas 4.11.: copy only the top proven wallets, tool's picks split by market cap."""

    def test_wallet_ranking(self):
        cfg = {**run.load_config(), "novcanici_top": 1, "novcanici_min_n": 3}
        cfg["strategies"] = [{k: v for k, v in st.items() if k != "topups"} for st in cfg["strategies"]]
        cfg["strategies"] = [{k: v for k, v in s.items() if k != "frozen"} for s in cfg["strategies"]]  # live here
        con = store.connect(":memory:")
        for i, (who, ret) in enumerate([("novčanik @good", 0.5)] * 3 + [("novčanik @ok", 0.1)] * 3 +
                                       [("novčanik @bad", -0.3)] * 3 + [("novčanik @new", -0.5)]):
            con.execute("INSERT INTO positions (strat, token, why, status, ret, pnl_usd) VALUES "
                        "('novcanici', ?, ?, 'closed', ?, ?)", (f"T{i}", who, ret, ret * 50))
        top, out = run.wallets_allowed(con, cfg, history=[])
        self.assertEqual(top, {"novčanik @good"})
        self.assertEqual(out, {"novčanik @ok", "novčanik @bad"})   # measured, not top: no longer copied
        src = {"novcanici": [(A, T0, "novčanik @bad", 0), (B, T0, "novčanik @new", 0), (C, T0, "novčanik @good", 0)]}
        w = run.wanted(src, cfg, T0, 0, out, top)["top_novcanici"]
        self.assertEqual([e[0] for e in w], [C])      # 5.11.: only allowed wallets; @new waits for history or copies
        # history (own trades) lets a wallet in, a proven-bad copy record keeps it out, and a stale buy is skipped
        top2, out2 = run.wallets_allowed(con, cfg, history=["novčanik @hist", "novčanik @bad"])
        self.assertEqual(top2, {"novčanik @good", "novčanik @hist"})
        src2 = {"novcanici": [(A, T0 - 600, "novčanik @hist", 0), (B, T0 - 30, "novčanik @hist", 0), (C, T0, "novčanik @bad", 0)]}
        w2 = run.wanted(src2, cfg, T0, 0, out2, top2)["top_novcanici"]
        self.assertEqual([e[0] for e in w2], [B])     # 10 min old buy is too late (novcanici_max_delay_s 120)
        rows = [{"wallet": "H" * 44, "copy_score": 70, "labels": [],
                 "stats": {"closed": 40, "closed_pnl_sol": 12.0, "win_rate": 0.6, "median_hold_min": 30, "last_trade_days": 0.5, "top_trade_share": 0.2}},
                {"wallet": "L" * 44, "copy_score": 70, "labels": [],
                 "stats": {"closed": 5, "closed_pnl_sol": 1.0, "win_rate": 0.6, "median_hold_min": 30, "last_trade_days": 0.5, "top_trade_share": 0.2}}]
        self.assertEqual(run.history_wallets(cfg, rows=rows, names={}), ["novčanik HHHHHH…"])   # 5 closed: not yet

    def test_bands(self):
        cfg = run.load_config()
        self.assertTrue(run.band_of(cfg, "alat_mali", 150_000))
        self.assertFalse(run.band_of(cfg, "alat_mali", 250_000))
        self.assertTrue(run.band_of(cfg, "alat_srednji", 250_000))
        self.assertTrue(run.band_of(cfg, "alat_veliki", 3e6))
        self.assertTrue(run.band_of(cfg, "kol", 3e6))
        self.assertNotIn("mix", run.keys(cfg))
        self.assertIn("kontrola", run.keys(cfg))       # audit 4.11. R6: the random control is the baseline


if __name__ == "__main__":
    unittest.main()
