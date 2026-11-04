"""Regression tests from the 4.11.2026 audit spec (MemeSonar objedinjena specifikacija, ch. 18): T16 and up,
plus the T01-T15 cases that touch code changed for it. No network, no real wallet."""
import ast
import glob
import os
import subprocess
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from trade import executor, jupiter  # noqa: E402

NOW = 1_800_000_000
CFG = {"mode": "dry", "size_sol": 0.05, "max_sol_per_trade": 0.1, "max_sol_per_day": 5, "max_open": 5,
       "min_sol_reserve": 0.05, "max_cost_pct": 6, "max_signal_age_s": 180, "poll_s": 5, "max_loss_day": 0.15}


class T16PythonVersions(unittest.TestCase):
    def test_every_file_parses_on_older_pythons(self):
        """PEP 701 f-strings (3.12+) broke the UI on 3.10/3.11 (audit §3). Checked with every older python3.x
        found on this machine; skipped when none is installed."""
        olds = [p for v in ("3.10", "3.11") for p in [shutil.which(f"python{v}")] if p]
        if not olds:
            self.skipTest("no python3.10/3.11 here")
        files = [f for f in glob.glob(os.path.join(HERE, "**", "*.py"), recursive=True) if "/." not in f]
        code = ("import ast,sys\nbad=[]\nfor f in sys.argv[1:]:\n try: ast.parse(open(f,encoding='utf-8').read())\n"
                " except SyntaxError as e: bad.append(f'{f}:{e.lineno}')\nprint('\\n'.join(bad))")
        for py in olds:
            out = subprocess.run([py, "-c", code, *files], capture_output=True, text=True, timeout=300)
            self.assertEqual(out.stdout.strip(), "", f"{py}: {out.stdout}")

    def test_render_pins_313(self):
        self.assertIn("value: 3.13", open(os.path.join(HERE, "render.yaml")).read())


class TradeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (jupiter.order, jupiter.execute, executor.STOP_FILE)
        executor.STOP_FILE = os.path.join(self.tmp.name, "STOP")
        jupiter.order = lambda i, o, a, taker=None, route="v2": {
            "inAmount": str(a), "outAmount": str(a * 1000 if i == jupiter.SOL else a // 1000), "requestId": "rq",
            "inUsdValue": 100, "outUsdValue": 99, "transaction": "dHg=", "error": None}
        self.con = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        jupiter.order, jupiter.execute, executor.STOP_FILE = self.saved
        self.con.close()
        self.tmp.cleanup()


class T22DuplicateMint(TradeBase):
    def test_auto_and_manual_follow_same_mint_is_one_position(self):
        a = executor.buy(self.con, CFG, "MINT", now=NOW, reason="auto", league_id=1)
        b = executor.buy(self.con, CFG, "MINT", now=NOW + 5, reason="ručno", league_id=2)
        self.assertEqual(a["status"], "open")
        self.assertEqual(b["status"], "blocked")
        self.assertIn("već postoji", b["error"])
        n = self.con.execute("SELECT COUNT(*) FROM positions WHERE token='MINT' AND status='open'").fetchone()[0]
        self.assertEqual(n, 1)


class T23KillSwitchAndSell(TradeBase):
    def test_stop_blocks_buys_but_not_sells(self):
        pos = executor.buy(self.con, CFG, "M", now=NOW)
        open(executor.STOP_FILE, "w").close()
        self.assertIn("kill switch", executor.buy(self.con, CFG, "N", now=NOW)["error"])
        r = executor.sell(self.con, {**CFG, "on": False}, pos["id"], close=True, now=NOW + 60)
        self.assertEqual(r["status"], "dry")
        st = self.con.execute("SELECT status FROM positions WHERE id=?", (pos["id"],)).fetchone()[0]
        self.assertEqual(st, "closed")


class T24DayLoss(TradeBase):
    def test_failed_fees_count_and_midnight_is_zagreb(self):
        start = executor._day_start(NOW, "Europe/Zagreb")
        import datetime
        from zoneinfo import ZoneInfo
        d = datetime.datetime.fromtimestamp(start, ZoneInfo("Europe/Zagreb"))
        self.assertEqual((d.hour, d.minute), (0, 0))
        # a closed live position lost 0.1 SOL, and two failed tries cost 0.06 SOL in fees today
        self.con.execute("INSERT INTO positions (token, mode, status, sol_in, sol_back, opened_ts, closed_ts, qty_raw, "
                         "qty_left) VALUES ('A','live','closed',0.2,0.1,?,?,0,0)", (NOW - 60, NOW - 30))
        for _ in range(2):
            self.con.execute("INSERT INTO orders (ts, token, side, mode, status, fee_lamports) "
                             "VALUES (?, 'B', 'buy', 'live', 'failed', 30000000)", (NOW - 10,))
        self.assertAlmostEqual(executor.day_pnl(self.con, NOW, "live"), -0.16)
        why = executor.gate_buy(self.con, {**CFG}, 0.05, NOW, True, balance=10)
        self.assertIn("dnevni gubitak", why)
        # the next Zagreb day starts clean
        self.assertIsNone(executor.gate_buy(self.con, CFG, 0.05, start + 86400 + 60, True, balance=10))


class C09Attempts(TradeBase):
    def test_fees_of_all_attempts_are_kept(self):
        tries = iter([{"status": "failed", "retry": True, "error": "x", "fee_lamports": 10, "signature": "S1",
                       "amount_in": 5},
                      {"status": "ok", "fee_lamports": 20, "signature": "S2", "amount_in": 5, "amount_out": 7}])
        saved = executor._jup
        executor._jup = lambda *a, **k: dict(next(tries))
        try:
            res = executor.swap(jupiter.SOL, "M", 5, True, routes=("v2", "ultra"))
        finally:
            executor._jup = saved
        self.assertEqual(res["fee_total"], 30)
        self.assertEqual([a["signature"] for a in res["attempts"]], ["S1", "S2"])
        executor._log(self.con, NOW, 1, "M", "buy", "live", res, "test")
        rows = self.con.execute("SELECT signature, fee_lamports FROM orders ORDER BY id").fetchall()
        self.assertEqual(rows, [("S1", 10), ("S2", 20)])

    def test_intent_written_before_send_and_reconciled(self):
        seen = {}

        def swap(*a, **k):   # what the db holds while the swap is "in flight"
            seen["st"] = self.con.execute("SELECT status FROM positions").fetchone()[0]
            raise SystemExit("process killed mid-swap")
        saved = executor.swap
        executor.swap = swap
        try:
            with self.assertRaises(SystemExit):
                executor.buy(self.con, CFG, "M", now=NOW)
        finally:
            executor.swap = saved
        self.assertEqual(seen["st"], "pending")
        self.con.execute("UPDATE positions SET mode='live'")
        self.assertEqual(executor.reconcile_pending(self.con, now=NOW + 120, balance_of=lambda t: 1234), 1)
        st, q = self.con.execute("SELECT status, qty_left FROM positions").fetchone()
        self.assertEqual((st, q), ("open", 1234))


class Locks(unittest.TestCase):
    def test_follow_paper_and_simianx_stay_off(self):
        from trade import settings
        con = settings.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        settings.put(con, "follow_paper", True)
        settings.put(con, "simianx", True)
        cfg = settings.merged(dict(CFG), con)
        self.assertFalse(cfg["follow_paper"])
        self.assertFalse(cfg["simianx"])
        self.assertFalse(settings.simianx_on(con))
        self.assertEqual(executor.load_config()["max_loss_day"], 0.15)


class T25Webhook(unittest.TestCase):
    def test_chain_hook_needs_header_and_ignores_query_key(self):
        import io
        import run_ui
        from kol import store
        os.environ["DATA_DIR"] = tempfile.mkdtemp()
        os.environ.pop("KOL_HOOK_KEY", None)
        key = store.chain_key()
        self.assertTrue(key)
        self.assertNotEqual(store.hook_key(), __import__("hashlib").sha256(b"kol-hook:" + os.environ.get(
            "UI_PASSWORD", "").encode()).hexdigest()[:32])

        class H:   # just enough of the request handler
            def __init__(self, headers):
                self.headers, self.code, self.rfile = headers, None, io.BytesIO(b"[]")

            def send_response(self, c):
                self.code = c

            def end_headers(self):
                pass
        from urllib.parse import urlsplit
        h = H({"Content-Length": "2"})
        run_ui.Handler._chain_hook(h, urlsplit(f"/hook/chain?key={key}"))
        self.assertEqual(h.code, 401)
        h = H({"Content-Length": "2", "Authorization": "wrong"})
        run_ui.Handler._chain_hook(h, urlsplit("/hook/chain"))
        self.assertEqual(h.code, 401)


class AdminStrip(unittest.TestCase):
    def test_admin_parts_removed(self):
        from ui import admstrip
        html = "<nav><a href=/a>A</a><div class='g adm-only'><a href=/sustav>S</a><div>x</div></div></nav>" \
               "<details class=adm-only><summary>log</summary><pre>secret</pre></details><p>ok</p>"
        out = admstrip.strip(html)
        self.assertNotIn("sustav", out)
        self.assertNotIn("secret", out)
        self.assertIn("<p>ok</p>", out)


class C01WalletCostBasis(unittest.TestCase):
    def test_rebuy_does_not_change_booked_sale(self):
        from wallets import pnl
        rows = [{"ts": 1, "mint": "M", "kind": "buy", "tokens": 1, "sol": -1},
                {"ts": 2, "mint": "M", "kind": "sell", "tokens": -1, "sol": 2},
                {"ts": 3, "mint": "M", "kind": "buy", "tokens": 1, "sol": -10}]
        p = pnl.positions(rows, {"M": 10})["M"]
        self.assertAlmostEqual(p["realized"], 1)
        self.assertAlmostEqual(p["unrealized"], 0)
        self.assertAlmostEqual(p["cost_left"], 10)
        before = pnl.positions(rows[:2], {"M": 10})["M"]["realized"]
        self.assertAlmostEqual(before, p["realized"])          # T02/T13 shape: the later buy changed nothing

    def test_partial_sale_books_once(self):
        from wallets import pnl
        rows = [{"ts": 1, "mint": "M", "kind": "buy", "tokens": 10, "sol": -1},
                {"ts": 2, "mint": "M", "kind": "sell", "tokens": -5, "sol": 1}]
        p = pnl.positions(rows, {"M": 0.1})["M"]
        self.assertAlmostEqual(p["realized"], 0.5)
        self.assertAlmostEqual(p["remaining"], 5)
        self.assertAlmostEqual(p["cost_left"], 0.5)
        self.assertEqual(p["status"], "open")


class C02UnknownPrice(unittest.TestCase):
    def test_empty_feed_is_unknown_not_dead(self):
        from wallets import pnl

        class Empty:
            def tokens(self, chain, mints):
                return []
        prices, sol = pnl.prices_sol(["M"], Empty())
        self.assertEqual(prices, {})
        self.assertIsNone(sol)
        rows = [{"ts": 1, "mint": "M", "kind": "buy", "tokens": 10, "sol": -1}]
        p = pnl.positions(rows, prices)["M"]
        self.assertEqual((p["status"], p["price_status"]), ("open", "unknown"))
        self.assertEqual(pnl.positions(rows, {"M": 0})["M"]["status"], "closed")   # confirmed dead pool


class C03HistoricalRate(unittest.TestCase):
    def test_stable_leg_uses_rate_of_that_day(self):
        from wallets import rpc
        usdc = next(iter(rpc.STABLES))
        tx = {"blockTime": 86400 * 3 + 5, "transaction": {"signatures": ["S"], "message": {"accountKeys": ["W"]}},
              "meta": {"preBalances": [0], "postBalances": [0],
                       "preTokenBalances": [{"owner": "W", "mint": usdc, "uiTokenAmount": {"amount": "200000000", "decimals": 6}}],
                       "postTokenBalances": [{"owner": "W", "mint": "M", "uiTokenAmount": {"amount": "5", "decimals": 0}}]}}
        rows = rpc.parse(tx, "W", sol_usd=lambda ts: 200.0)
        self.assertAlmostEqual(rows[0]["sol"], -1.0)
        self.assertEqual(rows[0]["fx"], "hist")
        self.assertEqual(rpc.parse(tx, "W", sol_usd=lambda ts: None)[0]["fx"], "approx")


class T20Beta(unittest.TestCase):
    def test_identical_series_beta_one(self):
        import statistics as st
        a = [0.01 if i % 2 else -0.008 for i in range(30)]
        vb = st.variance(a)
        self.assertAlmostEqual(st.covariance(a, a) / vb, 1.0)
        src = open(os.path.join(HERE, "dugo", "features.py")).read()
        self.assertNotIn("st.pvariance(b)", src)


class T21PartialDay(unittest.TestCase):
    def test_fully_reported_quiet_day_is_kept(self):
        from market import collect
        D = collect.D
        tot = {(i * D, "all:dex"): 100.0 for i in range(7)}
        tot[(7 * D, "all:dex")] = 50.0
        counts = {i * D: 40 for i in range(8)}
        self.assertIsNone(collect.partial_day(tot, counts=counts))
        self.assertEqual(collect.anomaly_day(tot), 7 * D)          # flagged, not dropped
        counts[7 * D] = 20                                          # half the protocols missing: really partial
        self.assertEqual(collect.partial_day(tot, counts=counts), 7 * D)


class T17AsOf(unittest.TestCase):
    def test_rug_check_after_decision_is_ignored(self):
        import sqlite3
        from learn import confmodel
        db = os.path.join(tempfile.mkdtemp(), "rug.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE rug_reports (mint TEXT, checked_at INTEGER, verdict TEXT)")
        con.execute("INSERT INTO rug_reports VALUES ('M', 1100, 'PROLAZI')")
        con.commit()
        con.close()
        saved = confmodel.RUG_DB
        confmodel.RUG_DB = db
        try:
            self.assertEqual(confmodel._rug_verdicts({"M": 1000}), {})          # SAFE only after the signal
            self.assertEqual(confmodel._rug_verdicts({"M": 1200}), {"M": "PROLAZI"})
        finally:
            confmodel.RUG_DB = saved

    def test_ai_classified_later_and_brag(self):
        import sqlite3
        from learn import postai
        con = sqlite3.connect(":memory:")
        con.executescript(postai.SCHEMA)
        con.execute("INSERT INTO posts_ai (src, post_id, ts, kind, paid_promo, conviction, already_bought, classified_at) "
                    "VALUES ('x','1',900,'call',0,5,1,2000)")
        con.execute("INSERT INTO post_tokens VALUES ('x','1','M',900)")
        self.assertEqual(postai.features("M", 1000, con=con), {})               # classified only at 2000
        self.assertEqual(postai.features("M", 2100, con=con)["ai_poziv"], 1 / 3)
        con.execute("UPDATE posts_ai SET kind='brag'")
        f = postai.features("M", 2100, con=con)
        self.assertEqual((f["ai_poziv"], f["ai_kupio"]), (0.0, 0.0))            # a brag is not a buy call
        self.assertGreater(f["ai_brag"], 0)

    def test_shadow_liquidity_is_as_of_event(self):
        src = open(os.path.join(HERE, "learn", "shadow.py")).read()
        self.assertIn("WHERE token=? AND ts<=? ORDER BY ts DESC", src)


class T18TimeSplit(unittest.TestCase):
    def test_no_val_row_in_train_and_label_window_purged(self):
        from learn import split
        rows = [{"ts": i * 3600} for i in range(100)]
        train, val = split.by_time(rows, val_share=0.3, horizon_s=24 * 3600)
        self.assertTrue(max(r["ts"] for r in train) + 24 * 3600 <= min(r["ts"] for r in val))
        self.assertFalse({id(r) for r in train} & {id(r) for r in val})

    def test_gbm_bins_from_train_only(self):
        import random
        from learn import gbm
        rnd = random.Random(3)
        rows = [{"x": {"a": rnd.random() if i < 400 else 1000 + rnd.random()}, "y": rnd.random() < .5, "ts": i * 600}
                for i in range(500)]
        m = gbm.train(rows, {"min_rows": 100, "purge_s": 0})
        if m:   # the validation-only values (1000+) must not shape the bins
            self.assertTrue(all(e < 2 for e in m["edges"]["a"]))


class T19PromotionIsNotTrading(unittest.TestCase):
    def test_better_but_still_losing(self):
        from learn import champion
        c = {"model": {"n": 400, "mean": -0.05, "mean_trim": -0.06}, "tezine": {"n": 400, "mean": -0.15,
             "mean_trim": -0.16}, "razlika": (0.02, 0.15), "model_range": (-0.08, -0.02)}
        self.assertTrue(champion.wins(c))
        ok, why = champion.trade_ok(c)
        self.assertFalse(ok)
        self.assertIn("ne trgujemo", why)


if __name__ == "__main__":
    unittest.main()
