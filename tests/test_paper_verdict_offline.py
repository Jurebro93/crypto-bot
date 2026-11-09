"""Nicholas 4.11.: short Demo trading page (which strategy earns / near zero / how to fix it), clickable loss reasons,
market-cap bands measured separately, no tiny fresh tokens, and the new "aktivni" source (older tokens with the most
buys and sells, GeckoTerminal).

    python3 -m unittest tests.test_paper_verdict_offline
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import weights  # noqa: E402
from paper import aktivni, arms, rules, store  # noqa: E402
from ui import paperverdict  # noqa: E402

NOW = 1_793_800_000
PUMP = "Ab1pump"


def pool(mint, age_d, buys, sells, buyers, mcap, liq, price=0.001, h1=(100, 100), ch1="5"):
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - age_d * 86400))
    return {"attributes": {"name": f"{mint[:4]} / SOL", "address": "pool" + mint, "pool_created_at": created,
                           "transactions": {"h24": {"buys": buys, "sells": sells, "buyers": buyers},
                                            "h1": {"buys": h1[0], "sells": h1[1]}, "h6": {"buys": 1, "sells": 1}},
                           "market_cap_usd": str(mcap), "reserve_in_usd": str(liq), "base_token_price_usd": str(price),
                           "price_change_percentage": {"h1": ch1, "h24": "20"}},
            "relationships": {"base_token": {"data": {"id": "solana_" + mint}}}}


class Aktivni(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._ld, weights.LEARNED_DIR = weights.LEARNED_DIR, self.tmp

    def tearDown(self):
        weights.LEARNED_DIR = self._ld

    def test_only_older_busy_real_tokens(self):
        pools = [pool("OLDpump", 10, 3000, 2000, 900, 400_000, 60_000),          # taken
                 pool("NEWpump", 1, 9000, 9000, 4000, 300_000, 50_000),          # too young
                 pool("TINYpump", 8, 3000, 3000, 900, 12_000, 15_000),           # too small
                 pool("BOTSpump", 9, 30000, 30000, 4, 900_000, 90_000),          # 4 buyers: bot volume
                 pool("So11111111111111111111111111111111111111112", 900, 9e4, 9e4, 9000, 1e9, 1e7),
                 pool("STOCKxyz", 40, 5000, 5000, 900, 600_000, 80_000, price=230)]  # tokenised stock
        st = aktivni.refresh({}, now=NOW, get=lambda p: {"data": pools if "page=1&" in p else []}, force=True)
        self.assertEqual([t["mint"] for t in st["tokens"]], ["OLDpump"])
        self.assertEqual(st["tokens"][0]["tx24"], 5000)
        self.assertIn("mlađi od 3 dana", st["skipped"])
        self.assertIn("premalo različitih kupaca (botovski volumen)", st["skipped"])
        # stored and served while fresh, empty once older than 2 x refresh
        self.assertIn("OLDpump", aktivni.wanted({}, NOW + 3600))
        self.assertEqual(aktivni.wanted({}, NOW + 13 * 3600), {})

    def test_oldest_pool_gives_age_busiest_gives_activity(self):
        rows = aktivni.parse([pool("Xpump", 20, 100, 100, 50, 1e5, 2e4), pool("Xpump", 1, 4000, 4000, 900, 1e5, 2e4)], NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tx24"], 8000)
        self.assertGreater(rows[0]["age_d"], 19)

    def test_gecko_down_keeps_old_list(self):
        aktivni._save({"ts": NOW - 7 * 3600, "tokens": [{"mint": "A", "tx24": 3000}]})
        st = aktivni.refresh({}, now=NOW, get=lambda p: {})
        self.assertEqual(st["tokens"][0]["mint"], "A")
        self.assertFalse(aktivni.due(st, aktivni.config({}), NOW + 60))

    def test_live_check_skips_pumps_and_dead_tokens(self):
        c = aktivni.config({})
        ok = {"txns": {"h1": {"buys": 150, "sells": 100}, "h24": {"buys": 2400, "sells": 2400}}, "priceChange": {"h1": 8}}
        self.assertIsNone(aktivni.live_check(ok, c))
        pumped = dict(ok, priceChange={"h1": 80})
        self.assertIn("kasni ulaz", aktivni.live_check(pumped, c))
        dead = dict(ok, txns={"h1": {"buys": 10, "sells": 10}, "h24": {"buys": 2400, "sells": 2400}})
        self.assertIn("aktivnost pala", aktivni.live_check(dead, c))
        self.assertTrue(aktivni.live_check(None, c))


class Gate(unittest.TestCase):
    def test_tiny_token_refused(self):
        why = rules.gate(PUMP, 0.000005, 12_000, 5_000, None, {}, {})
        self.assertIn("market cap", why)
        self.assertIsNone(rules.gate(PUMP, 0.00005, 12_000, 50_000, None, {}, {}))


def closed(con, mode, ret, mcap, exit_reason="stop_loss", max_ret=0.0, ts=NOW - 3600):
    tid = store.open_trade(con, "T%d" % con.execute("SELECT COUNT(*) FROM trades").fetchone()[0], "S",
                           {"opened_ts": ts - 600, "size_usd": 20, "entry_px": 1, "entry_eff": 1},
                           {"entry_mode": mode, "arm": f"{mode}|eu"}, mcap)
    con.execute("UPDATE trades SET status='closed', closed_ts=?, ret=?, pnl_usd=?, exit_reason=?, max_ret=?, "
                "min_ret=-0.3 WHERE id=?", (ts, ret, 20 * ret, exit_reason, max_ret, tid))


class Bands(unittest.TestCase):
    def test_band_names_and_stats(self):
        self.assertEqual(arms.mc_band(10_000), "mc ispod 50k $")
        self.assertEqual(arms.mc_band(120_000), "mc 50–200k $")
        self.assertEqual(arms.mc_band(500_000), "mc 200k–1M $")
        self.assertEqual(arms.mc_band(3e6), "mc preko 1M $")
        con = store.connect(":memory:")
        for _ in range(4):
            closed(con, "explore", -0.3, 20_000)
        closed(con, "explore", 0.5, 300_000)
        st = arms.stats(con)
        self.assertEqual(st["mc ispod 50k $"], [0, 4])
        self.assertEqual(st["mc 200k–1M $"], [1.5, 0])


class Page(unittest.TestCase):
    def trades(self):
        con = store.connect(":memory:")
        con.row_factory = sqlite3.Row
        for i in range(12):   # mc100k: earns, mostly on 200k-1M
            closed(con, "mc100k", 0.4 if i % 3 else -0.2, 300_000, "trailing" if i % 3 else "stop_loss")
        for i in range(12):   # explore: loses, late entries on tiny tokens
            closed(con, "explore", -0.3, 30_000, "stop_loss", 0.01)
        for i in range(10):   # kol3: near zero
            closed(con, "kol3", 0.02 if i % 2 else -0.03, 120_000, "time")
        closed(con, "core", -0.1, 80_000, "rucno")   # manual sale: never counted
        rows = [dict(r) for r in con.execute("SELECT * FROM trades")]
        for r in rows:
            r["state"] = json.loads(r["state"] or "{}")
        return rows

    def test_verdicts_bands_and_reasons(self):
        h = paperverdict.top_html(self.trades(), now=NOW)
        self.assertIn("U plusu: Prvi prelazak 100k $.", h)
        self.assertIn("Bez najboljeg tradea", h)
        self.assertIn("Blizu nule: 3+ KOL-a u 15 min.", h)
        self.assertIn("gubi", h)
        self.assertIn("kasni ulaz", h.lower())
        self.assertIn("<details class=pv-r>", h)
        self.assertIn("Što znači:", h)
        self.assertIn("200k–1M $", h)
        self.assertIn("Aktivni stariji tokeni", h)   # new strategy shown even before its first trade
        self.assertNotIn("Glavni (visoka ocjena)", h)  # only a manual sale: not the bot's result

    def test_every_loss_reason_has_an_explanation(self):
        for er, mx in (("rug", 0), ("kol_prodaje", 0), ("time", 0), ("stop_loss", 0), ("stop_loss", 0.3),
                       ("stop_loss", 0.1), ("trailing", 0.2)):
            self.assertIn(arms.loss_reason(er, mx, -0.3, -0.1), paperverdict.REASONS)

    def test_empty(self):
        self.assertEqual(paperverdict.top_html([]), "")


class AktivniEntry(unittest.TestCase):
    """A listed older token is bought once as entry mode 'aktivni'; one that just pumped is not (kasni ulaz)."""

    def setUp(self):
        import run_paper
        from paper import sim
        self.rp, self.sim = run_paper, sim
        self.tmp = tempfile.mkdtemp()
        self._ld, weights.LEARNED_DIR = weights.LEARNED_DIR, self.tmp
        self.saved = {k: getattr(run_paper, k) for k in ("DB", "HYPE_DB", "HERE", "market", "rug_verdict", "notify",
                                                          "t0_check")}
        self.saved_live = aktivni.live_pairs
        run_paper.DB = os.path.join(self.tmp, "paper.db")
        run_paper.HYPE_DB = os.path.join(self.tmp, "hype.db")
        run_paper.HERE = self.tmp
        self.now = time.time()
        mk = {"OKpump": (0.0004, 60_000, 400_000, None), "HOTpump": (0.0004, 60_000, 400_000, None)}
        run_paper.market = lambda toks: {t: mk[t] for t in toks if t in mk}
        run_paper.rug_verdict = lambda con, t, cfg, now, paid=True: (None, None, [])
        run_paper.notify = lambda *a, **k: None
        run_paper.t0_check = lambda t, now: "prolaz"
        live = {"txns": {"h1": {"buys": 150, "sells": 100}, "h24": {"buys": 2400, "sells": 2400}}}
        aktivni.live_pairs = lambda mints: {"OKpump": dict(live, priceChange={"h1": 5}),
                                            "HOTpump": dict(live, priceChange={"h1": 90})}
        aktivni._save({"ts": int(self.now), "tokens": [
            {"mint": m, "symbol": m[:3], "age_d": 9, "tx24": 4800, "buyers24": 900} for m in ("OKpump", "HOTpump")]})

    def tearDown(self):
        weights.LEARNED_DIR = self._ld
        aktivni.live_pairs = self.saved_live
        for k, v in self.saved.items():
            setattr(self.rp, k, v)

    def test_entry(self):
        cfg = {**self.sim.load_config(), "explore": {"enabled": False}, "konv": {"enabled": False},
               "rules": {"ab": {"enabled": False}, "kol3": {"enabled": False}}}
        opened = self.rp.intake(cfg, now=self.now, quiet=True)
        self.assertEqual([c["token"] for c in opened], ["OKpump"])
        self.assertIn("aktivan stariji token", opened[0]["reason"])
        con = store.connect(self.rp.DB)
        self.assertEqual(json.loads(con.execute("SELECT config FROM trades").fetchone()[0])["entry_mode"], "aktivni")
        why = con.execute("SELECT reason FROM candidates WHERE token='HOTpump'").fetchone()[0]
        self.assertIn("kasni ulaz", why)
        self.assertEqual(self.rp.intake(cfg, now=self.now + 60, quiet=True), [])  # once a day per token
        con.close()

    def test_no_entry_while_paused_after_stop_losses(self):
        """9.11. JENSEN: after 3 stop losses in 48 h the token waits 32 h, whatever trigger wants it."""
        cfg = {**self.sim.load_config(), "explore": {"enabled": False}, "konv": {"enabled": False},
               "rules": {"ab": {"enabled": False}, "kol3": {"enabled": False}}}
        con = store.connect(self.rp.DB)
        for h in (40, 30, 25):
            tid = store.open_trade(con, "OKpump", "OK", {"opened_ts": self.now - h * 3600 - 600, "size_usd": 20,
                                                          "entry_px": 1, "entry_eff": 1}, {"entry_mode": "aktivni"})
            con.execute("UPDATE trades SET status='closed', closed_ts=?, exit_reason='stop_loss', ret=-0.3 WHERE id=?",
                        (self.now - h * 3600, tid))
        con.commit()
        con.close()
        self.assertEqual(self.rp.intake(cfg, now=self.now, quiet=True), [])


if __name__ == "__main__":
    unittest.main()
