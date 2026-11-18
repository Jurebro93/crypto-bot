"""18.11. (vlasnik: "Twitter API kredite koristiš za ove mid-capove ... tko agresivno gura ... velike influencere
koji imaju veliku moć poziva"), veliki/moc.py, offline (synthetic posts and candles, a fake X search):

  - a mention: a cashtag of exactly one of our tokens or its mint; generic and ambiguous symbols are not ours
  - the outcome is the move after the post MINUS the token's own average move; the same account + token within 6 h
    counts once; the push counts every post
  - the ranking needs enough token-days and sorts by the interval's low
  - the paid sweep: one search per token, saved once, its own day cap, never twice within a week, stops on an error
  - run(): the stored result, the line, the MCP tool

    python3 -m unittest tests.test_moc_offline
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tests.test_veliki_replay_offline as _rp  # noqa: E402  (the module, so its tests are not collected here)
from veliki import moc  # noqa: E402

D, H, M15 = 86400, 3600, 900
NOW = _rp.NOW
A, B, C = "MintA" + "a" * 39, "MintB" + "b" * 39, "MintC" + "c" * 39
TOKS = [{"mint": A, "symbol": "ALFA"}, {"mint": B, "symbol": "beta"}, {"mint": C, "symbol": "SOL"},
        {"mint": "MintD" + "d" * 39, "symbol": "DUP"}, {"mint": "MintE" + "e" * 39, "symbol": "DUP"}]


def post(i, handle, ts, text, **kw):
    return {"id": str(i), "handle": handle, "ts": ts, "text": text, "likes": kw.get("likes", 10), "views": 100,
            "followers": kw.get("followers", 50_000)}


def flat_then_jump(t0, n=400, jump_at=None, jump=0.10, px=1.0):
    """15m bars: flat, and from bar jump_at on the price is `jump` higher."""
    out = []
    for i in range(n):
        p = px * (1 + jump) if jump_at is not None and i >= jump_at else px
        out.append((t0 + i * M15, p, p, p, p, 1.0))
    return out


class Mentions(unittest.TestCase):
    def test_only_our_unambiguous_symbols_and_mints(self):
        symmap, names = moc.symbols(TOKS)
        self.assertEqual(symmap, {"ALFA": A, "BETA": B})           # SOL is generic, DUP names two tokens
        self.assertEqual(names[B], "beta")
        ps = [post(1, "@big", 100, "loading $alfa here"), post(2, "big", 200, "$ALFAX is not it, nor $SOL"),
              post(3, "ca", 300, f"ape {B} now"), post(4, "x", 400, "no token at all, just words and more words here"),
              post(5, "two", 500, f"$BETA and {B} and $Alfa")]
        ms = moc.mentions_of(ps, symmap, set(names))
        self.assertEqual([(m["handle"], m["token"], m["how"]) for m in ms],
                         [("big", A, "ticker"), ("ca", B, "ca"), ("two", B, "ca"), ("two", A, "ticker")])

    def test_first_only_and_push(self):
        ms = [{"handle": "Big", "token": A, "ts": t} for t in (0, 3600, 5 * H, 7 * H, 2 * D, 2 * D + 60)]
        ms.append({"handle": "big", "token": B, "ts": 10})
        self.assertEqual([m["ts"] for m in moc.first_only(ms) if m["token"] == A], [0, 7 * H, 2 * D])
        self.assertEqual(moc.push_of(ms)["big"], (6, A))            # every post counts for the push


class Outcome(unittest.TestCase):
    def test_excess_is_the_move_minus_the_tokens_own_average(self):
        t0 = NOW - 10 * D
        p = moc.Prices(flat_then_jump(t0, jump_at=200))
        self.assertGreater(p.base["24h"], 0)                        # one jump in the window lifts the token's average
        ex = p.excess(t0 + 199 * M15 + 60)                          # posted in the bar before the jump
        self.assertAlmostEqual(ex["1h"], 0.10 - p.base["1h"], places=9)
        self.assertEqual(set(ex), {"1h", "4h", "24h"})
        self.assertAlmostEqual(p.excess(t0 + 201 * M15)["4h"], -p.base["4h"], places=9)   # after the jump: nothing left
        self.assertEqual(p.excess(t0 - 5 * D), {})                  # before our candles
        self.assertEqual(set(p.excess(t0 + 398 * M15)), set())      # too close to the end for any horizon

    def test_ranking_needs_enough_token_days_and_sorts_by_the_low(self):
        t0 = NOW - 30 * D
        bars = []
        for d in range(30):                                          # +2 % every day at 12:00, flat otherwise
            for i in range(96):
                px = (1.02 ** d) * (1.02 if i >= 48 else 1.0)
                bars.append((t0 + d * D + i * M15, px, px, px, px, 1.0))
        prices = {A: moc.Prices(bars), B: moc.Prices(bars)}
        ms = []
        for d in range(12):                                          # "early" posts an hour before the move, on 12 days
            ms.append({"handle": "early", "token": A, "ts": t0 + d * D + 47 * M15, "likes": 5, "followers": 900_000})
        for d in range(12):                                          # "late" posts right after it
            ms.append({"handle": "late", "token": B, "ts": t0 + d * D + 49 * M15, "likes": 5, "followers": 10})
        for d in range(3):                                           # too few token-days to be ranked
            ms.append({"handle": "few", "token": A, "ts": t0 + d * D + 47 * M15, "likes": 5, "followers": 1})
        res = moc.rank(ms, prices, {A: "ALFA", B: "BETA"})
        self.assertEqual([r["handle"] for r in res["top"]], ["early", "late"])
        e, l = res["top"]
        self.assertGreater(e["x1h"], 0.015)                          # he was before the move
        self.assertLess(l["x1h"], 0)                                 # he was after it
        self.assertEqual((e["clusters"], e["tokens"], e["followers"], e["push"]), (12, 1, 900_000, 7))
        self.assertEqual(res["ranked_n"], 2)
        self.assertEqual(res["accounts"], 3)
        self.assertEqual(res["tokens"][0]["top"][0]["handle"], "early")
        self.assertIn("@early", moc.line({**res, "ts": 1}))


class Sweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.con = moc.connect(os.path.join(self.tmp.name, "moc.db"))
        self.addCleanup(self.con.close)
        self.calls = []

    def get(self, q, cursor):
        self.calls.append(q)
        return {"tweets": [{"id": f"{len(self.calls)}-{i}", "createdAt": NOW - 3600, "text": "$ALFA send it",
                            "likeCount": 40, "viewCount": 9000, "author": {"userName": f"acc{i}", "followers": 1000 * i}}
                           for i in range(3)], "has_next_page": False}

    def test_one_search_per_token_saved_once_and_not_again_within_a_week(self):
        symmap, _n = moc.symbols(TOKS[:2])
        r = moc.sweep(self.con, TOKS[:2], symmap, NOW, get=self.get)
        self.assertEqual((r["searched"], r["posts"], r["stopped"]), (2, 6, None))
        self.assertAlmostEqual(r["usd"], 2 * 3 * 0.00015, places=6)
        self.assertIn(f"($ALFA OR {A}) min_faves:25 -filter:replies since_time:{NOW - 30 * D}", self.calls[0])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 6)
        again = moc.sweep(self.con, TOKS[:2], symmap, NOW + 3 * D, get=self.get)
        self.assertEqual(again["searched"], 0)                       # searched 3 days ago: not due
        later = moc.sweep(self.con, TOKS[:2], symmap, NOW + 8 * D, get=self.get)
        self.assertEqual(later["searched"], 2)

    def test_the_day_cap_and_an_error_stop_it_and_no_key_is_no_spend(self):
        symmap, _n = moc.symbols(TOKS[:2])
        r = moc.sweep(self.con, TOKS[:2], symmap, NOW - 30 * D, get=self.get, run_tokens=1)
        self.assertEqual((r["searched"], r["left"], r["stopped"]), (1, 1, "ostatak u sljedećem prolazu"))
        r = moc.sweep(self.con, TOKS[:2], symmap, NOW, get=self.get, day_usd=0.0004)
        self.assertEqual(r["searched"], 1)
        self.assertIn("dnevni strop", r["stopped"])

        def boom(q, cursor):
            raise OSError("HTTP Error 402: Payment Required")
        r = moc.sweep(self.con, TOKS[:2], symmap, NOW + 8 * D, get=boom)
        self.assertEqual(r["searched"], 0)
        self.assertIn("402", r["stopped"])
        from kol import twapi
        with mock.patch.object(twapi, "key", lambda: None):
            self.assertEqual(moc.sweep(self.con, TOKS[:2], symmap, NOW + 20 * D)["stopped"], "nema ključa")


class Run(unittest.TestCase):
    def test_free_posts_paid_posts_result_line_and_tool(self):
        from makroinf import store as mstore
        from ui import mcpapi
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mpath, xpath, path = (os.path.join(tmp.name, n) for n in ("midcap.db", "makroinf.db", "moc.db"))
        _rp.make_db(mpath, n_tok=4, days=20)
        sym, mint = "TOK0", _rp.mint(0)
        xc = mstore.connect(xpath)
        xc.execute("INSERT INTO accounts (handle, followers, status) VALUES ('macro1', 250000, 'aktivan')")
        for d in range(10):
            xc.execute("INSERT INTO tweets (id, handle, ts, text, likes, views) VALUES (?,?,?,?,?,?)",
                       (f"f{d}", "macro1", NOW - (15 - d) * D, f"still buying ${sym}", 99, 5000))
        xc.execute("INSERT INTO tweets (id, handle, ts, text, likes, views) VALUES ('n1','macro1',?,?,1,1)",
                   (NOW - D, "nothing about tokens"))
        xc.commit()
        xc.close()

        def get(q, cursor):
            return {"tweets": [{"id": "p" + q[:12], "createdAt": NOW - 2 * D, "text": f"{mint} looks ready",
                                "likeCount": 80, "viewCount": 1, "author": {"userName": "whale", "followers": 700000}}],
                    "has_next_page": False}
        lines = []
        res = moc.run(NOW, lines.append, path, mpath, xpath, get=get)
        self.assertEqual(res["free_posts"], 10)
        self.assertEqual(res["sweep"]["searched"], 4)
        self.assertGreaterEqual(res["mentions"], 11)
        self.assertEqual(res["tokens"][0]["symbol"], sym)
        self.assertIn("macro1", {r["handle"] for r in res["top"]})  # 10 token-days: ranked
        self.assertNotIn("whale", {r["handle"] for r in res["top"]})  # one post: named, not ranked
        self.assertTrue(lines[-1].startswith("moć poziva: "), lines)
        self.assertIn("pretraga X-a: 4 tokena (još 0 na redu)", lines[-1])
        with mock.patch.dict(os.environ, {"MOC_DB": path}):
            d, err = mcpapi._tool("get_call_power", {"limit": 5})
        self.assertFalse(err)
        self.assertEqual(d["mentions"], res["mentions"])
        self.assertIn("statistics", d["read_me"])
        self.assertTrue({t["name"]: t for t in mcpapi.TOOLS}["get_call_power"]["annotations"]["readOnlyHint"])
        self.assertEqual(moc.run(NOW, lines.append, path, os.path.join(tmp.name, "nema.db")), {})
        self.assertEqual(moc.latest(os.path.join(tmp.name, "x.db")), {})


if __name__ == "__main__":
    unittest.main()
