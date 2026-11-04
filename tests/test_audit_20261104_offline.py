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


if __name__ == "__main__":
    unittest.main()
