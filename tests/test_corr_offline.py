"""Korelacije on synthetic data: KOL clusters, wallet <-> account links, one-owner wallet groups, pump factors,
active now, AI fallback / mocked Claude, follow import into wallets.db, page render."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corr import ai, analyze, store  # noqa: E402

T0 = 1793390000
C = analyze.cfg()


def call(h, tok, ts, max24=None, pre2h=0.0, views=100):
    return {"handle": h, "token": tok, "ts": ts, "max24": max24, "r1h": None, "pre2h": pre2h, "views": views,
            "followers": 1000, "url": "", "symbol": tok[:4].upper(), "src": "x"}


def synthetic():
    """Accounts a, b, c call 6 tokens together within minutes (a first); 30 other accounts call random tokens alone.
    Wallet W1 buys 10 min before every call of a and sells after; wallets G1, G2 share a funder and co-buy."""
    calls, trades = [], []
    for i in range(6):
        tok = f"grp{i}"
        t = T0 + i * 7200
        calls += [call("a", tok, t, 1.5), call("b", tok, t + 120, 1.5), call("c", tok, t + 300, 1.5)]
        trades += [("W1", tok, t - 600, "buy", 1.0), ("W1", tok, t + 900, "sell", 2.0)]
        trades += [("G1", tok, t - 3000, "buy", 0.5), ("G2", tok, t - 3000, "buy", 0.5)]
    for j in range(300):     # the rest of the market: many accounts, each calling a few tokens alone
        calls.append(call(f"solo{j % 60}", f"tok{j}", T0 + j * 1000, 0.1 if j % 3 else 1.2))
        trades.append(("SNIPER", f"tok{j}", T0 + j * 1000 - 60, "buy", 0.1))
    for j in range(30):
        calls.append(call("a", f"atok{j}", T0 + 400000 + j * 5000, 0.2))
    return calls, trades


class Clusters(unittest.TestCase):
    def test_cluster_found(self):
        calls, _ = synthetic()
        n, pairs = analyze.pair_stats(calls, C)
        self.assertEqual(pairs[("a", "b")]["n"], 6)
        cls = analyze.clusters_from_pairs(pairs, C)
        self.assertEqual([sorted(x) for x in cls], [["a", "b", "c"]])
        d = analyze.describe_cluster(cls[0], calls, pairs, C)
        self.assertEqual(d["leader"], "a")
        self.assertEqual(d["tokens"], 6)
        self.assertEqual(d["hit_together"], 1.0)
        self.assertLess(d["hit_solo"], 0.1)
        self.assertLessEqual(d["spread_min"], 5)
        self.assertGreaterEqual(d["score"], 60)

    def test_big_component_is_split(self):
        calls = []
        for g in range(2):      # two tight trios, glued together by account x that joins some calls of both
            for i in range(5):
                t = T0 + i * 9000 + g * 100000
                for k, h in enumerate(f"g{g}{x}" for x in range(3)):
                    calls.append(call(h, f"t{g}{i}", t + k * 60))
                if i < 3:
                    calls.append(call("x", f"t{g}{i}", t + 600))
        c = dict(C, max_cluster=3, min_lift=0)
        _, pairs = analyze.pair_stats(calls, c)
        self.assertEqual(sorted(sorted(x) for x in analyze.clusters_from_pairs(pairs, c)),
                         [["g00", "g01", "g02"], ["g10", "g11", "g12"]])


class Wallets(unittest.TestCase):
    def test_links_and_snipers(self):
        calls, trades = synthetic()
        links = analyze.wallet_links(calls, trades, C)
        w1a = [x for x in links if x["wallet"] == "W1" and x["handle"] == "a"]
        self.assertEqual(w1a[0]["tokens"], 6)
        self.assertEqual(w1a[0]["sold_into"], 6)
        self.assertAlmostEqual(w1a[0]["lead_min"], 10)
        self.assertFalse([x for x in links if x["wallet"] == "SNIPER"])   # one buy per account: no repeated link

    def test_owner_groups(self):
        calls, trades = synthetic()
        cob = analyze.cobuy_edges(trades, C)
        self.assertIn(("G1", "G2", 6), cob)
        groups = analyze.owner_groups([("F", "G1"), ("F", "G2"), ("CEX", "X1")] + [("CEX", f"x{i}") for i in range(40)],
                                      [], cob, set(), trades, [], {}, {}, C)
        self.assertEqual(groups[0]["wallets"], ["F", "G1", "G2"])
        self.assertEqual(groups[0]["shared_tokens"], 6)
        self.assertFalse([g for g in groups if "CEX" in g["wallets"]])   # exchange-like funder ignored


class Factors(unittest.TestCase):
    def test_factors_and_active(self):
        calls, trades = synthetic()
        _, pairs = analyze.pair_stats(calls, C)
        cls = [analyze.describe_cluster(m, calls, pairs, C) for m in analyze.clusters_from_pairs(pairs, C)]
        f = analyze.pump_factors(calls, cls, [], [], {}, C)
        row = next(x for x in f["factors"] if x["factor"] == "2+ člana iste KOL grupe")
        self.assertEqual(row["hit_yes"], 1.0)
        self.assertGreater(row["lift"], 3)
        now = T0 + 5 * 7200 + 600
        act = analyze.active_now(calls, cls, [], trades, C, now)
        self.assertEqual(act[0]["token"], "grp5")


def make_dbs(d):
    calls, trades = synthetic()
    kol = sqlite3.connect(os.path.join(d, "kol.db"))
    kol.executescript("CREATE TABLE calls (tweet_id, token, handle, ts, url, text, followers, likes, retweets, views, kind,"
                      " match, source, symbol, first_by_kol, first_overall, p0, mcap0, pre2h, r1h, r6h, r24h, max24,"
                      " vol_before, vol_after, vol_lift, rug, complete, measured_ts);"
                      "CREATE TABLE tokens (token, symbol); CREATE TABLE insiders (wallet, token, call_ts, bought_ts,"
                      " sold_ts, sol_in, sol_out);")
    for i, x in enumerate(calls):
        kol.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind, max24, pre2h, views) VALUES (?,?,?,?,?,?,?,?)",
                    (str(i), x["token"], x["handle"], x["ts"], "call", x["max24"], x["pre2h"], x["views"]))
    kol.commit()
    kol.close()
    from wallets import store as wstore
    w = wstore.connect(os.path.join(d, "wallets.db"))
    for wl, m, ts, k, sol in trades:
        w.execute("INSERT INTO wallet_trades VALUES (?,?,?,?,?,?,?)", (wl, f"s{ts}{wl}{m}", ts, m, 1, sol, k))
    for g in ("G1", "G2"):
        wstore.observe(w, g, "grp0", "rug", "holder", extra={"funder": "F"})
    w.commit()
    w.close()
    return {"kol": os.path.join(d, "kol.db"), "wallets": os.path.join(d, "wallets.db"),
            "rug": os.path.join(d, "rug.db"), "hype": os.path.join(d, "hype.db")}


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.dbs = make_dbs(self.d)
        self.corr = os.path.join(self.d, "corr.db")

    def test_build_ai_follow_page(self):
        snap = analyze.build(self.dbs["kol"], self.dbs["wallets"], self.dbs["rug"], self.dbs["hype"], C, T0 + 50000)
        self.assertEqual(snap["clusters"][0]["members"], ["a", "b", "c"])
        self.assertIn("W1", snap["clusters"][0]["wallets"])
        self.assertTrue(any(g["wallets"][:3] == ["F", "G1", "G2"] for g in snap["groups"]))
        json.dumps(snap)
        # no key -> rule lines
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            out, model, cost = ai.interpret(snap)
        self.assertEqual(model, "pravila")
        self.assertTrue(out["grupe"])
        # mocked Claude
        reply = {"naslov": "N", "zakljucci": ["z"], "grupe": [{"id": snap["clusters"][0]["id"], "ime": "Trojka",
                 "tumacenje": "t", "povjerenje": "visoko", "pratiti": True, "kako_iskoristiti": "k"}],
                 "signali": [], "sada": [], "upozorenja": [], "sto_jos": []}
        resp = types.SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                     content=[types.SimpleNamespace(type="text", text=json.dumps(reply))],
                                     usage=types.SimpleNamespace(input_tokens=10000, output_tokens=1000))
        fake = types.ModuleType("anthropic")
        fake.BadRequestError = type("BadRequestError", (Exception,), {})
        client = mock.MagicMock()
        client.beta.messages.create.return_value = resp
        fake.Anthropic = mock.MagicMock(return_value=client)
        with mock.patch.dict(sys.modules, {"anthropic": fake}), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}):
            out, model, cost = ai.interpret(snap)
        self.assertEqual(out["grupe"][0]["ime"], "Trojka")
        self.assertAlmostEqual(cost, 0.06)
        kw = client.beta.messages.create.call_args.kwargs
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        # store + follow + wallets import + page
        con = store.connect(self.corr)
        store.save(con, snap, analyze.digest(snap), T0 + 50000)
        store.save_ai(con, analyze.digest(snap), model, out, cost, T0 + 50000)
        store.set_follow(con, analyze.follow_list(snap, out, C), T0 + 50000)
        con.close()
        fol = store.followed(self.corr)
        self.assertIn(snap["clusters"][0]["id"], [f["id"] for f in fol])
        from wallets import store as wstore
        w = wstore.connect(self.dbs["wallets"])
        with mock.patch.object(store, "DB", self.corr):
            n = wstore.import_corr(w)
        if any(f["kind"] == "wallets" for f in fol):
            self.assertGreater(n, 0)
            labels = json.loads(w.execute("SELECT labels FROM wallets WHERE wallet='G1'").fetchone()[0])
            self.assertIn("grupa", labels)
        with mock.patch.object(store, "DB", self.corr):
            from ui import corrpage
            title, html = corrpage.page({})
        self.assertIn("Trojka", html)
        self.assertIn("Aktivno sada", html)
        self.assertNotIn("run_corr", html)

    def test_empty_page(self):
        with mock.patch.object(store, "DB", os.path.join(self.d, "none.db")):
            from ui import corrpage
            title, html = corrpage.page({})
        self.assertIn("Prva analiza", html)


if __name__ == "__main__":
    unittest.main()
