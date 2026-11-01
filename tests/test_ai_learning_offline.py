"""AI post reader (learn/postai.py) and AI detective + hypotheses (learn/detektiv.py) with a fake Anthropic client."""
import json
import os
import random
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import champion, detektiv, gbm, postai, shadow, weights  # noqa: E402

NOW = 1_800_000_000
DAY = 86400


def ns(**kw):
    return types.SimpleNamespace(**kw)


class FakeBatches:
    def __init__(self, label):
        self.label, self.sent = label, {}

    def create(self, requests):
        bid = f"b{len(self.sent)}"
        self.sent[bid] = requests
        return ns(id=bid)

    def retrieve(self, bid):
        return ns(processing_status="ended")

    def results(self, bid):
        for r in self.sent[bid]:
            text = r["params"]["messages"][0]["content"]
            out = self.label(text)
            msg = ns(content=[ns(type="text", text=json.dumps(out))], usage=ns(input_tokens=500, output_tokens=60),
                     model="claude-haiku-5-5", stop_reason="end_turn")
            yield ns(custom_id=r["custom_id"], result=ns(type="succeeded", message=msg))


def label(text):
    t = text.lower()
    kind = "warning" if "rug" in t else "ad" if "#ad" in t else "call"
    return {"kind": kind, "paid_promo": "#ad" in t, "conviction": 5 if "all in" in t else 2,
            "already_bought": "bought" in t, "narrative": "cat"}


def make_sources(tmp):
    import sqlite3
    kdb, tdb = os.path.join(tmp, "kol.db"), os.path.join(tmp, "tg.db")
    k = sqlite3.connect(kdb)
    k.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, text TEXT)")
    k.executemany("INSERT INTO calls VALUES (?,?,?,?,?)", [
        ("1", "TOK", "alice", NOW - 3600, "all in on $CAT, bought"), ("2", "TOK", "bob", NOW - 1800, "this is a rug, avoid"),
        ("3", "OTH", "carl", NOW - 600, "#ad new listing")])
    k.commit()
    k.close()
    t = sqlite3.connect(tdb)
    t.execute("CREATE TABLE posts (channel TEXT, post INTEGER, ts INTEGER, seen_ts INTEGER, text TEXT, cas TEXT, "
              "tickers TEXT, views INTEGER, fwd_from TEXT, source TEXT)")
    t.execute("INSERT INTO posts VALUES ('calls', 7, ?, ?, 'send it', 'TOK', '', 0, NULL, 'web')", (NOW - 900, NOW))
    t.commit()
    t.close()
    return kdb, tdb


class PostAI(unittest.TestCase):
    def test_batch_roundtrip_features_and_cost(self):
        tmp = tempfile.mkdtemp()
        kdb, tdb = make_sources(tmp)
        db = os.path.join(tmp, "ai.db")
        con = postai.connect(db)
        client = ns(messages=ns(batches=FakeBatches(label)))
        cfg = {**postai.DEFAULT}
        self.assertEqual(postai.submit(con, client, NOW, cfg, kdb, tdb), 4)
        self.assertEqual(postai.submit(con, client, NOW, cfg, kdb, tdb), 0)  # in flight: never sent twice
        self.assertEqual(postai.collect(con, client, NOW), 4)
        self.assertEqual(postai.submit(con, client, NOW, cfg, kdb, tdb), 0)  # labelled: never sent again
        f = postai.features("TOK", NOW, con=con)
        self.assertAlmostEqual(f["ai_poziv"], 2 / 3)  # alice + tg call; bob warned
        self.assertEqual(f["ai_upozorenje"], 1.0)
        self.assertEqual(f["ai_kupio"], 1.0)
        self.assertEqual(f["ai_uvjerenje"], 1.0)
        self.assertEqual(postai.features("TOK", NOW - 3700, con=con), {})  # nothing written before then
        con.close()
        sp = postai.spend(30, NOW, db)
        self.assertEqual(sp["posts"], 4)
        self.assertAlmostEqual(sp["usd"], round(4 * (500 * 0.10 + 60 * 0.50) / 1e6 * 0.5, 2))


class FakeClaude:
    def __init__(self, out):
        self.out = out
        self.beta = ns(messages=ns(create=self._create))
        self.messages = ns(create=self._create)

    def _create(self, **kw):
        self.kw = kw
        return ns(content=[ns(type="text", text=json.dumps(self.out))], usage=ns(input_tokens=20000, output_tokens=2000),
                  model="claude-opus-5-5", stop_reason="end_turn")


def fill(path, start, days, per_day=100, seed=4):
    rnd = random.Random(seed)
    con = shadow.connect(path)
    for d in range(days):
        for i in range(per_day):
            ts = int(start + d * DAY + i * (DAY // per_day))
            kp = rnd.random()
            ret = (0.35 if kp > 0.6 else -0.12) + rnd.uniform(-0.05, 0.05)
            con.execute("INSERT INTO points (id, token, symbol, point, ts, klasa, sess, price, liq, mcap, score, kupljeno, "
                        "features, status, ret, max2_ret, min_ret, hit, rug) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'gotovo',?,?,?,?,0)",
                        (f"p{d}_{i}", f"T{d}_{i}", "S", "mc100k", ts, "moonshot", "us", 1.0, 3e4, 1e5, 50, 0,
                         json.dumps({"kol_x": kp, "fresh": rnd.random()}), ret, ret, -0.1, int(ret >= 0.1)))
    con.commit()
    con.close()


class Detective(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        weights.LEARNED_DIR = os.path.join(self.tmp, "learned")
        self.ai = os.path.join(self.tmp, "ai.db")
        self.sdb = os.path.join(self.tmp, "shadow.db")
        self._db = postai.DB
        postai.DB = self.ai
        detektiv._PASSED["ts"] = 0

    def tearDown(self):
        postai.DB = self._db
        detektiv._PASSED["ts"] = 0

    def test_idea_to_hypothesis_to_signal(self):
        fill(self.sdb, NOW - 10 * DAY, 10)
        detektiv.add_idea("KOL poziv iznad 0.6 je dobar", path=self.ai, now=NOW - 9 * DAY)
        out = {"hipoteze": [
            {"naslov": "Jak KOL poziv", "objasnjenje": "x", "tocka": "mc100k", "iz_ideje": 1,
             "uvjeti": [{"signal": "kol_x", "op": ">=", "vrijednost": "0.6"}]},
            {"naslov": "Svjež token", "objasnjenje": "y", "tocka": "sve", "iz_ideje": 0,
             "uvjeti": [{"signal": "fresh", "op": ">=", "vrijednost": "0.5"}]},
            {"naslov": "Izmišljen signal", "objasnjenje": "z", "tocka": "sve", "iz_ideje": 0,
             "uvjeti": [{"signal": "ne_postoji", "op": ">=", "vrijednost": "1"}]}]}
        note = detektiv.propose(self.ai, now=NOW - 9 * DAY + 3600, shadow_path=self.sdb, client=FakeClaude(out))
        self.assertIn("novih hipoteza 2", note)  # the unknown signal is dropped
        ov = detektiv.overview(self.ai, now=NOW)
        self.assertEqual(ov["by"], {"testira se": 2})
        res = dict(detektiv.evaluate(detektiv.connect(self.ai), now=NOW, shadow_path=self.sdb))
        self.assertEqual(sorted(res.values()), ["prošla", "testira se"])  # fresh is noise: still open (or later fails)
        detektiv._PASSED["ts"] = 0
        ps = detektiv.passed(self.ai, now=NOW)
        self.assertEqual(len(ps), 1)
        x = gbm.context({"features": {"kol_x": 0.9}, "point": "mc100k"})
        self.assertEqual(x[f"h_{ps[0]['id']}"], 1.0)
        self.assertNotIn(f"h_{ps[0]['id']}", gbm.context({"features": {"kol_x": 0.9}}, hyps=False))
        self.assertEqual(champion.strip_ai({"features": {"ai_poziv": 1, "kol_x": 1, "h_1": 1}})["features"], {"kol_x": 1})


if __name__ == "__main__":
    unittest.main()
