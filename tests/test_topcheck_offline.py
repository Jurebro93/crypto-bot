"""Svježa provjera preporučenih tokena: stanje tržišta, rug check, spremište (offline, bez mreže)."""
import os
import tempfile
import time
import unittest

from topcheck import safety, state, store


def pair(m5=None, h1=None, h6=None, h24=None, buys=10, sells=10):
    return {"priceChange": {k: v for k, v in (("m5", m5), ("h1", h1), ("h6", h6), ("h24", h24)) if v is not None},
            "txns": {"h1": {"buys": buys, "sells": sells}}}


def rc(**kw):
    base = {"token": {"supply": 1_000_000_000_000, "decimals": 6},
            "mintAuthority": None, "freezeAuthority": None, "rugged": False, "launchpad": None,
            "knownAccounts": {"POOLOWNER": {"type": "AMM", "name": "Raydium"}},
            "markets": [{"pubkey": "M1", "lp": {"lpLockedPct": 100, "quoteUSD": 5000, "baseUSD": 5000},
                         "liquidityAAccount": {"owner": "POOLOWNER"}, "liquidityBAccount": {"owner": "POOLOWNER"}}],
            "topHolders": [{"address": "A0", "owner": "POOLOWNER", "pct": 40}]
            + [{"address": f"A{i}", "owner": f"W{i}", "pct": 2, "insider": False} for i in range(1, 15)],
            "creatorBalance": 0, "transferFee": {"pct": 0}, "token_extensions": None, "risks": []}
    base.update(kw)
    return base


class State(unittest.TestCase):
    def test_pump(self):
        self.assertEqual(state.classify(pair(m5=15, h1=5))["state"], "pumpa")
        self.assertEqual(state.classify(pair(h1=45))["state"], "pumpa")
        self.assertEqual(state.classify(pair(h6=120, h1=2))["state"], "pumpa")
        self.assertIn("Ne kupuj", state.classify(pair(h1=45))["advice"])

    def test_dip_recovering(self):
        s = state.classify(pair(m5=1, h1=6, h6=-35, h24=-40, buys=80, sells=50))
        self.assertEqual(s["state"], "oporavak")

    def test_dip_still_falling(self):
        self.assertEqual(state.classify(pair(m5=-4, h1=-8, h6=-35, buys=20, sells=60))["state"], "pada")
        self.assertEqual(state.classify(pair(h1=-20))["state"], "pada")

    def test_stable_and_missing(self):
        self.assertEqual(state.classify(pair(m5=0.5, h1=2, h6=-5, h24=10))["state"], "stabilno")
        self.assertIsNone(state.classify(None))
        self.assertIsNone(state.classify({"priceChange": {}}))


class Safety(unittest.TestCase):
    def test_clean_token_passes_and_pools_excluded(self):
        s = safety.summarize_rc(rc())
        self.assertEqual(s["top10"], 20.0)   # the 40% pool account is not a holder
        self.assertEqual(s["lp_locked"], 100.0)
        j = safety.judge("X", s, {"ok": True, "ratio": 0.97})
        self.assertEqual(j["verdict"], "prolazi", j)

    def test_authorities_fail(self):
        j = safety.judge("X", safety.summarize_rc(rc(mintAuthority="DEV", freezeAuthority="DEV")))
        self.assertEqual(j["verdict"], "pao")
        self.assertEqual(len(j["fails"]), 2)

    def test_pumpfun_suffix_ignores_authority(self):
        j = safety.judge("Xpump", safety.summarize_rc(rc(mintAuthority="CURVE")), {"ok": True, "ratio": 0.9})
        self.assertNotEqual(j["verdict"], "pao")

    def test_lp_unlocked(self):
        m = [{"pubkey": "M", "lp": {"lpLockedPct": 3, "quoteUSD": 1, "baseUSD": 1}}]
        self.assertEqual(safety.judge("X", safety.summarize_rc(rc(markets=m)))["checks"]["lp"][0], "fail")
        m = [{"pubkey": "M", "lp": {"lpLockedPct": 50, "quoteUSD": 1, "baseUSD": 1}}]
        self.assertEqual(safety.judge("X", safety.summarize_rc(rc(markets=m)))["verdict"], "oprez")

    def test_launchpad_lp_ok(self):
        m = [{"pubkey": "M", "lp": {"lpLockedPct": 100}}]
        j = safety.judge("Xpump", safety.summarize_rc(rc(markets=m, launchpad={"name": "Pump.Fun"})), {"ok": True, "ratio": 0.95})
        self.assertEqual(j["checks"]["lp"][0], "ok")

    def test_whales_and_dev(self):
        holders = [{"address": f"A{i}", "owner": f"W{i}", "pct": 9} for i in range(10)]
        self.assertEqual(safety.judge("X", safety.summarize_rc(rc(topHolders=holders)))["checks"]["holderi"][0], "fail")
        j = safety.judge("X", safety.summarize_rc(rc(creatorBalance=300_000_000_000)))
        self.assertEqual(j["checks"]["dev"][0], "fail")

    def test_honeypot(self):
        j = safety.judge("X", safety.summarize_rc(rc(transferFee={"pct": 25})))
        self.assertEqual(j["verdict"], "pao")
        self.assertIn("honeypot", j["checks"]["honeypot"][1])
        j = safety.judge("X", safety.summarize_rc(rc()), {"ok": True, "ratio": 0.2})
        self.assertEqual(j["verdict"], "pao")
        j = safety.judge("X", safety.summarize_rc(rc()), {"ok": False, "err": "nema rute"})
        self.assertEqual(j["verdict"], "oprez")

    def test_sell_test(self):
        s = safety.sell_test({"outAmount": "100", "_usd_out": 24.0, "priceImpactPct": "0.01"}, 25)
        self.assertEqual((s["ok"], s["ratio"], s["impact"]), (True, 0.96, 1.0))
        self.assertFalse(safety.sell_test({"error": "COULD_NOT_FIND_ANY_ROUTE"}, 25)["ok"])
        self.assertIsNone(safety.sell_test(None, 25)["ok"])

    def test_full_rug_filter(self):
        s = safety.summarize_rc(rc())
        full = {"verdict": "ODBAČEN", "data": {"hard_fails": ["serijski kreator: 26 tokena, živih 1"]}}
        self.assertEqual(safety.judge("X", s, {"ok": True, "ratio": 1}, full)["verdict"], "pao")
        # bonding curve: DexScreener shows no liquidity, that alone is not a rug
        lp = safety.summarize_rc(rc(launchpad={"name": "Pump.Fun"}))
        full = {"verdict": "ODBAČEN", "data": {"hard_fails": ["likvidnost samo $0"]}}
        self.assertNotEqual(safety.judge("Xpump", lp, {"ok": True, "ratio": 1}, full)["verdict"], "pao")

    def test_partial_report_and_extra_pools(self):
        self.assertIsNone(safety.summarize_rc(rc(markets=[]))["top10"])   # pool cannot be told from a whale
        whale = [{"address": "CURVE_ACC", "owner": "CURVE", "pct": 95}] + \
            [{"address": f"A{i}", "owner": f"W{i}", "pct": 0.5} for i in range(10)]
        s = safety.summarize_rc(rc(topHolders=whale, knownAccounts={"CURVE": {"type": "LAUNCHPAD"}}))
        self.assertEqual(s["top10"], 5.0)
        s = safety.summarize_rc(rc(topHolders=whale, knownAccounts={}), extra_pools=["CURVE"])
        self.assertEqual(s["top10"], 5.0)
        s = safety.summarize_rc(rc(topHolders=whale, knownAccounts={"CURVE": {"type": "CREATOR"}}))
        self.assertGreater(s["top10"], 60)

    def test_no_data(self):
        self.assertEqual(safety.judge("X", None)["verdict"], "nepoznato")
        self.assertIsNone(safety.summarize_rc(None))


class RoundTrip(unittest.TestCase):
    def test_sell_quote_round_trip_and_busy(self):
        import run_top
        calls = []

        def fake(params):
            calls.append(params)
            if params["inputMint"] == run_top.WSOL:
                return {"outAmount": "5000"}
            return {"outAmount": str(int(params_lamports[0] * 0.04)), "priceImpactPct": "0.001"}
        params_lamports = [int(run_top.SELL_USD / 200 * 1e9)]
        orig = run_top._jup
        run_top._jup = fake
        try:
            q = run_top.sell_quote("MINT", 200)
            self.assertEqual(calls[1]["amount"], 5000)       # sells exactly what the buy quote gave
            self.assertEqual(safety.sell_test(q, run_top.SELL_USD)["ratio"], 0.04)
            run_top._jup = lambda p: {"error": "no route"}
            self.assertIn("error", run_top.sell_quote("MINT", 200))
            self.assertIsNone(run_top.sell_quote("MINT", None))

            def busy(p):
                raise run_top.JupiterBusy()
            run_top._jup = busy
            with self.assertRaises(run_top.JupiterBusy):
                run_top.sell_quote("MINT", 200)
        finally:
            run_top._jup = orig


class RugCheckBackoff(unittest.TestCase):
    def test_rc_due(self):
        import run_top
        now = 1_000_000
        self.assertTrue(run_top.rc_due({}, now))
        self.assertFalse(run_top.rc_due({"rc_json": "{}", "rc_ts": now - 60}, now))
        self.assertTrue(run_top.rc_due({"rc_json": "{}", "rc_ts": now - 3600}, now))
        self.assertFalse(run_top.rc_due({"rc_fail": 1, "rc_fail_ts": now - 120}, now))     # 5 min after 1st failure
        self.assertTrue(run_top.rc_due({"rc_fail": 1, "rc_fail_ts": now - 301}, now))
        self.assertFalse(run_top.rc_due({"rc_fail": 3, "rc_fail_ts": now - 900}, now))     # 20 min after 3rd
        self.assertFalse(run_top.rc_due({"rc_fail": 9, "rc_fail_ts": now - 7000}, now))    # capped at 120 min
        self.assertTrue(run_top.rc_due({"rc_fail": 9, "rc_fail_ts": now - 7300}, now))

    def test_light_summary(self):
        light = safety.summarize_light({"tokenProgram": "Tokenkeg", "lpLockedPct": 0, "score": 1, "risks": [
            {"name": "Freeze Authority still enabled", "level": "danger"}]})
        self.assertTrue(light["light"] and light["freeze_auth"])
        self.assertIsNone(light["top10"])
        j = safety.judge("X", light, {"ok": True, "ratio": 0.98})
        self.assertEqual(j["verdict"], "pao")
        clean = safety.summarize_light({"lpLockedPct": 0, "risks": []})
        j = safety.judge("Xpump", clean, {"ok": True, "ratio": 0.98})
        self.assertEqual(j["checks"]["lp"][0], "ok")     # pump.fun curve, light summary has no launchpad field
        self.assertNotEqual(j["verdict"], "pao")
        self.assertIsNone(safety.summarize_light({"error": "x"}))

    def test_refusals_stop_the_pass(self):
        import run_top
        from ui import overview
        calls = []

        def refused(mint, pool=None):
            calls.append(mint)
            return None, True
        orig = (run_top.rugcheck, run_top.best_pairs, run_top.sell_quote, run_top.full_check, overview.watch_tokens)
        with tempfile.TemporaryDirectory() as d:
            store_db = store.DB
            store.DB = os.path.join(d, "t.db")
            try:
                run_top.rugcheck, run_top.best_pairs = refused, (lambda m: {})
                run_top.sell_quote = lambda m, s: None
                run_top.full_check = lambda con, m, now: None
                overview.watch_tokens = lambda n=None, **k: [f"M{i}" for i in range(6)]
                run_top.pass_once()
                self.assertEqual(len(calls), 2)            # two refusals, then no more RugCheck this pass
                got = store.read_all()
                self.assertEqual(got["M0"]["rc_fail"], 1)
                self.assertEqual(got["M0"]["verdict"], "nepoznato")
                calls.clear()
                run_top.pass_once()
                self.assertEqual(calls[:1], ["M2"])        # M0/M1 back off, the rest get their turn
            finally:
                store.DB = store_db
                (run_top.rugcheck, run_top.best_pairs, run_top.sell_quote, run_top.full_check,
                 overview.watch_tokens) = orig


class Store(unittest.TestCase):
    def test_roundtrip_unrank_budget(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.db")
            con = store.connect(p)
            store.put(con, {"token": "A", "rank": 1, "ts": int(time.time()), "verdict": "pao",
                            "state_json": '{"state": "pumpa"}', "safety_json": '{"fails": ["x"]}'})
            store.put(con, {"token": "B", "rank": 2, "ts": int(time.time())})
            store.unrank(con, ["A"])
            self.assertTrue(store.budget_take(con, "2026-11-02", 1))
            self.assertFalse(store.budget_take(con, "2026-11-02", 1))
            con.commit()
            con.close()
            got = store.read_all(p)
            self.assertEqual(got["A"]["state"]["state"], "pumpa")
            self.assertEqual(got["A"]["safety"]["fails"], ["x"])
            self.assertIsNone(got["B"]["rank"])
            self.assertEqual(store.read_all(os.path.join(d, "none.db")), {})


class Ui(unittest.TestCase):
    def test_cells(self):
        from ui import topcheckui as t
        top = {"ts": time.time() - 60, "verdict": "oprez",
               "state": state.classify(pair(h1=45)),
               "safety": {"fails": [], "warns": ["top 10 holdera drži 40%"], "oks": [],
                          "checks": {"holderi": ["warn", "top 10 holdera drži 40%"]}}}
        self.assertIn("Pumpa", t.badges(top))
        self.assertIn("oprez", t.rug_badge(top))
        html, srt, cls = t.advice_cell(top)
        self.assertIn("Ne kupuj", html)
        self.assertIn("Oprez", html)
        self.assertEqual(cls, "wrap")
        self.assertIn("prvih 20", t.advice_cell(None)[0])
        self.assertIn("Top 10 holdera", t.token_box(top))
        self.assertEqual(t.token_box(None), "")


if __name__ == "__main__":
    unittest.main()
