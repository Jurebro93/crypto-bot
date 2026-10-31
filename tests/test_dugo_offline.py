"""Dugoročni i oživljeni tokeni: candle features, recovery episodes, percentile score, similarity to the reference
tokens, the guarded learner, the daily ranking, the demo book and the page - all offline on synthetic candles."""
import json
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dugo import features, learn, run, score as sc, store  # noqa: E402
from learn import weights as lw  # noqa: E402

D = 86400
NOW = 1793361600
TODAY = NOW // D * D


def series(n, start=1.0, drift=0.0, vol=0.05, seed=1, ref=None, beta=1.0, dips=()):
    """n daily candles ending today. ref: {day: close} to follow with `beta`; dips: [(day_index, -0.6)]."""
    rnd = random.Random(seed)
    out, p = [], start
    days = [TODAY - (n - 1 - i) * D for i in range(n)]
    for i, d in enumerate(days):
        r = drift + rnd.gauss(0, vol)
        if ref and d in ref and d - D in ref:
            r += beta * math.log(ref[d] / ref[d - D])
        for at, sz in dips:
            if i == at:
                r += math.log(1 + sz)
        p *= math.exp(r)
        out.append((d, p, p * 1.03, p * 0.97, p, 100000.0))
    return out


class Features(unittest.TestCase):
    def test_episodes(self):
        closes = [10, 12, 6, 5, 9, 10, 4, 4.5]     # dip 12->5 recovers to 9 (>50%), dip 10->4 does not
        self.assertEqual(features.episodes(closes), (2, 1))

    def test_compute_and_beta(self):
        btc = {c[0]: c[4] for c in series(200, 100, 0.002, 0.03, seed=7)}
        tok = series(200, 1, 0, 0.01, seed=3, ref=btc, beta=2.0)
        f = features.compute(tok, btc=btc)
        self.assertGreater(f["korelacija_btc"], 0.8)
        self.assertAlmostEqual(f["beta_btc"], 2.0, delta=0.4)
        self.assertGreater(f["starost_d"], 199)
        self.assertLessEqual(f["pad_od_vrha"], 0)
        self.assertIsNone(features.compute(tok[:5]))

    def test_no_lookahead(self):
        tok = series(120, seed=4)
        a = features.compute(tok[:80])
        b = features.compute(tok[:80] + [(t, 1e6, 1e6, 1e6, 1e6, 1e9) for t, *_ in tok[80:]][:0])
        self.assertEqual(a, b)
        self.assertAlmostEqual(features.forward(tok, tok[50][0], 30), tok[80][4] / tok[50][4] - 1)


class Score(unittest.TestCase):
    def test_percentile_and_sign(self):
        feats = {"a": {"x": 1, "y": 9}, "b": {"x": 2, "y": 5}, "c": {"x": 3, "y": 1}}
        s = sc.score(feats, {"x": 1.0, "y": -1.0})
        self.assertEqual(max(s, key=lambda m: s[m][0]), "c")
        self.assertEqual(s["c"][0], 100.0)
        self.assertEqual(sc.score({"a": {}}, {"x": 1.0})["a"][0], 50.0)   # missing = middle

    def test_similarity(self):
        base = {c: 0.0 for c in sc.PROFILE}
        feats = {"ref": dict(base), "near": {**base, "volatilnost": 0.1}, "far": {c: 5.0 for c in sc.PROFILE},
                 "mid": {c: 2.0 for c in sc.PROFILE}}
        sim = sc.similarity(feats, ["ref"])
        self.assertGreater(sim["near"], sim["mid"])
        self.assertGreater(sim["mid"], sim["far"])
        self.assertEqual(sc.similarity(feats, ["missing"]), {})

    def test_eligible(self):
        cfg = run.config()
        f = {"starost_d": 100, "pad_od_vrha": -0.7, "od_dna_30d": 0.5}
        self.assertTrue(sc.eligible("dugorocni", f, 2e5, 5e6, cfg))
        self.assertFalse(sc.eligible("dugorocni", {**f, "starost_d": 10}, 2e5, 5e6, cfg))
        self.assertTrue(sc.eligible("budjenje", f, 5e4, 1e6, cfg))
        self.assertFalse(sc.eligible("budjenje", {**f, "pad_od_vrha": -0.1}, 5e4, 1e6, cfg))

    def test_why(self):
        t = sc.why({"oporavaka": 0.5, "likvidnost": 0.3, "volatilnost": -0.4}, {})
        self.assertIn("oporav", t)
        self.assertIn("slabije", t)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = lw.LEARNED_DIR
        lw.LEARNED_DIR = self.tmp
        self.con = store.connect(os.path.join(self.tmp, "dugo.db"))
        self.cfg = run.config()
        sol = series(300, 100, 0.001, 0.03, seed=11)
        self.cfg["temelj"] = {"SOL": "SOL"}
        self.cfg["uzori"] = {"FART": "FART"}
        store.put_candles(self.con, "SOL", [c[:5] + (1e8,) for c in sol])
        solref = {c[0]: c[4] for c in sol}
        self.con.executemany("INSERT INTO ref VALUES ('SOL',?,?)", list(solref.items()))
        self.con.executemany("INSERT INTO ref VALUES ('BTC',?,?)", list(solref.items()))
        toks = {"FART": dict(beta=1.5, dips=[(100, -0.6), (200, -0.5)]), "GOOD": dict(beta=1.4, dips=[(120, -0.5)]),
                "MEH": dict(beta=0.2), "DEAD": dict(beta=1.0), "WAKE": dict(beta=1.0, dips=[(150, -0.85)], drift=0.0)}
        for i, (m, kw) in enumerate(toks.items()):
            cs = series(300, 1, kw.pop("drift", 0.0), 0.04, seed=20 + i, ref=solref, **kw)
            if m == "WAKE":
                cs = cs[:-25] + [(d, p * 1.6, p * 1.7, p * 1.5, p * 1.6, 3e5) for d, p, *_ in cs[-25:]]
            store.put_candles(self.con, m, cs)
            self.con.execute("""INSERT INTO tokens (mint, symbol, source, first_seen, last_dex, liquidity, mcap, vol24,
                buys24, sells24, ch24, candles_ts, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (m, m, "test", NOW, NOW, 5e5, 2e7, 1e6, 600, 400, -80 if m == "DEAD" else 2, NOW, NOW - 300 * D))
        self.con.commit()

    def tearDown(self):
        lw.LEARNED_DIR = self._old
        self.con.close()

    def test_rank_book_and_page(self):
        out = run.rank(self.con, self.cfg, NOW)
        dug = [m for m, _ in out["dugorocni"]]
        self.assertNotIn("DEAD", dug)            # -80% in a day = dead, never listed
        self.assertNotIn("SOL", dug)             # benchmark, not a pick
        self.assertIn("GOOD", dug)
        self.assertEqual(self.con.execute("SELECT status FROM tokens WHERE mint='DEAD'").fetchone()[0], "mrtav")
        run.book(self.con, self.cfg, NOW)
        n = self.con.execute("SELECT COUNT(*) FROM book WHERE exit_ts IS NULL").fetchone()[0]
        self.assertGreater(n, 0)
        run.book(self.con, self.cfg, NOW + 3600)     # same week: no second batch
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM book").fetchone()[0], n)
        self.con.commit()
        from ui import dugo as page
        store.DB = os.path.join(self.tmp, "dugo.db")
        try:
            orig = run.config
            run.config = lambda: self.cfg
            title, body = page.page({})
        finally:
            run.config = orig
        self.assertEqual(title, "Dugoročni")
        self.assertIn("Dugoročni kandidati", body)
        self.assertIn("GOOD", body)
        for jargon in ("dugo.db", "run_dugo", "python3"):
            self.assertNotIn(jargon, body)

    def test_learn_guard(self):
        self.cfg["ucenje"]["min_uzoraka"] = 10 ** 6
        r = learn.fit(self.con, self.cfg, "dugorocni", NOW)
        self.assertEqual(r["applied"], 0)
        self.assertIn("premalo", r["note"])
        self.assertFalse(os.path.exists(learn.path()))
        self.cfg["ucenje"]["min_uzoraka"] = 5
        r = learn.fit(self.con, self.cfg, "dugorocni", NOW)
        self.assertGreater(r["n"], 5)
        self.assertIn(r["applied"], (0, 1))
        if r["applied"]:
            L = learn.load_learned()
            self.assertIn("prev", L)
            step = max(abs(L["dugorocni"][c] - self.cfg["tezine"]["dugorocni"][c]) for c in L["dugorocni"])
            self.assertLess(step, 1.0)


class Seed(unittest.TestCase):
    def test_import_once(self):
        con = store.connect(os.path.join(tempfile.mkdtemp(), "dugo.db"))
        n = store.import_seed(con, now=NOW)
        self.assertGreater(n, 50)
        self.assertGreater(con.execute("SELECT COUNT(DISTINCT mint) FROM candles").fetchone()[0], 50)
        self.assertGreater(len(store.ref(con, "SOL")), 100)
        self.assertGreater(len(store.ref(con, "BTC")), 300)
        self.assertEqual(store.import_seed(con, now=NOW), 0)      # second time: nothing
        con.close()


if __name__ == "__main__":
    unittest.main()
