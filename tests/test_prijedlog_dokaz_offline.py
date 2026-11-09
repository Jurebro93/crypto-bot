"""9.11. (Jure, RIPTRUMP): "token kojeg alat preporuči mora biti tu s razlogom uz tezu iz podataka". A pick needs a
live market this hour and comes with its thesis; otherwise the box says why nothing passes. The event organic score
no longer rewards a dead old token."""
import math
import os
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dexscreener import match  # noqa: E402
from ui import prijedlog  # noqa: E402

T = "GhBPHgnNF99EThYxt4bxUfPX1hCPyAS72RCBgLjLpump"
T2 = "ANLEpx1hMMGJ2vHwENrVhH1gkysDNwf5p4uNKJxGpump"
NOW = time.time()
ALIVE = {"price": 0.001, "liq": 60_000.0, "mcap": 160_000.0, "vol_h1": 5_000.0, "vol_h24": 40_000.0, "txns_h1": 40,
         "buys_h1": 25, "txns_h24": 400, "ch_h1": 6.0, "ch_h24": 15.0}
DEAD = {"price": 0.0001339, "liq": 31_396.0, "mcap": 133_982.0, "vol_h1": 0.0, "vol_h24": 2_014.0, "txns_h1": 0,
        "buys_h1": 0, "txns_h24": 21, "ch_h1": 0.0, "ch_h24": -3.24}


def row(token, conf=70, mcap=150_000, age=600, sym="X"):
    return {"token": token, "symbol": sym, "conf": conf, "mcap": mcap, "last_seen": NOW - age, "hard": False,
            "collapse": False, "rug": {"verdict": "OPREZ"}, "sansa": 50, "hype": 10, "features": {}, "det": {},
            "conf_parts": [(5, "KOL pozvao"), (3, "volumen raste"), (-2, "mali TG"), (-4, "dev prodao 5 %")], "checks": [],
            "events": []}


class LiveGate(unittest.TestCase):
    def test_dead_token_is_never_a_pick_and_the_box_says_why(self):
        ch = {"100–300k": (0.3, 20)}
        picks, near, note = prijedlog.token_picks_ex(NOW, rows=[row(T2, sym="RIPTRUMP")], status={}, ch=ch, live={T2: DEAD})
        self.assertEqual(picks, [])
        self.assertEqual(len(near), 1)
        self.assertIn("0 transakcija u zadnjem satu", near[0][1])
        html = prijedlog.box("tokeni", rows=[row(T2, sym="RIPTRUMP")], live={T2: DEAD})
        self.assertIn("nijedan token ne prolazi sve provjere", html)
        self.assertIn("ne kupuj", html)
        self.assertIn("RIPTRUMP", html)
        self.assertNotIn("vjerojatnost", html)   # not offered as a buy at any grade

    def test_live_check_failure_means_no_pick(self):
        picks, near, note = prijedlog.token_picks_ex(NOW, rows=[row(T)], status={}, ch={}, live=None,
                                                     ) if False else prijedlog.token_picks_ex(
            NOW, rows=[row(T)], status={}, ch={}, live={})   # empty live map: token not in it -> no pair
        self.assertEqual(picks, [])
        self.assertIn("nema živog para", near[0][1])
        saved = prijedlog.live_market
        prijedlog.live_market = lambda toks: None            # DexScreener down
        try:
            picks, near, note = prijedlog.token_picks_ex(NOW, rows=[row(T)], status={}, ch={})
        finally:
            prijedlog.live_market = saved
        self.assertEqual((picks, near), ([], []))
        self.assertIn("nije uspjela", note)
        self.assertIn("ništa ne predlažem", prijedlog._near_html([], note))

    def test_alive_reasons(self):
        self.assertIsNone(prijedlog.alive(ALIVE))
        self.assertIn("transakcija", prijedlog.alive({**ALIVE, "txns_h1": 3}))
        self.assertIn("volumen", prijedlog.alive({**ALIVE, "vol_h1": 200.0}))
        self.assertIn("likvidnost", prijedlog.alive({**ALIVE, "liq": 9_000.0}))
        self.assertIn("pada: -34 %", prijedlog.alive({**ALIVE, "ch_h1": -34.0}))   # CATPAD 9.11. 13:05
        self.assertIsNone(prijedlog.alive({**ALIVE, "ch_h1": -12.0}))

    def test_pick_carries_live_numbers_history_and_thesis(self):
        from ui import data
        hp = os.path.join(tempfile.mkdtemp(), "hype.db")
        con = sqlite3.connect(hp)
        from ui import prijedlog_log
        con.execute(prijedlog_log.SCHEMA)
        con.execute("INSERT INTO prijedlog_log (token, day, ts, kind, razina, mcap0, conf, hit, stop_first, labelled_ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (T, "2026-11-07", int(NOW) - 2 * 86400, "tokeni", "visoka", 90_000, 60, 1, 0, int(NOW) - 86400))
        con.commit()
        con.close()
        saved = data.HYPE_DB
        data.HYPE_DB = hp
        try:
            picks = prijedlog.token_picks(NOW, rows=[row(T)], status={}, ch={"100–300k": (0.3, 20)}, live={T: ALIVE})
        finally:
            data.HYPE_DB = saved
        self.assertEqual(len(picks), 1)
        p = picks[0]
        self.assertEqual(p["mcap0"], 160_000.0)           # the live market cap, not the stale one
        self.assertEqual(p["live"]["txns_h1"], 40)
        self.assertEqual(p["history"]["suggested"], 1)
        self.assertEqual(p["history"]["sugg_hit"], 1)
        th = p["thesis"]
        self.assertIn("Teza:", th)
        self.assertIn("40 transakcija i $5,000 volumena", th)
        self.assertIn("0.1× likvidnosti", th)
        self.assertIn("već predložen 1×: 1× +15 % prije stopa", th)
        self.assertIn("Protiv: rug filter: OPREZ; mali TG", th)
        ok_row = {**row(T), "rug": {"verdict": "PROLAZI"}}
        p2 = prijedlog.token_picks(NOW, rows=[ok_row], status={}, ch={"100–300k": (0.3, 20)}, live={T: ALIVE})[0]
        self.assertNotIn("rug filter", p2["thesis"])                       # a pass is never listed against
        html = prijedlog._item(p)
        self.assertIn("Teza:", html)

    def test_live_market_parses_dexscreener_pairs(self):
        pairs = [{"baseToken": {"address": T}, "priceUsd": "0.002", "liquidity": {"usd": 50000}, "marketCap": 200000,
                  "volume": {"h1": 1234.5, "h24": 9999}, "txns": {"h1": {"buys": 7, "sells": 5}, "h24": {"buys": 70, "sells": 50}},
                  "priceChange": {"h1": 3.2, "h24": -1.0}},
                 {"baseToken": {"address": T}, "priceUsd": "0.002", "liquidity": {"usd": 500}, "marketCap": 200000}]   # shallower pair
        lv = prijedlog.live_market([T], fetch=lambda toks: pairs)
        self.assertEqual((lv[T]["txns_h1"], lv[T]["vol_h1"], lv[T]["liq"], lv[T]["ch_h1"]), (12, 1234.5, 50000.0, 3.2))
        self.assertIsNone(prijedlog.live_market([T], fetch=lambda toks: (_ for _ in ()).throw(OSError("down"))))

    def test_organic_score_no_longer_rewards_a_dead_token(self):
        dead = {"age_h": 219 * 24, "liquidity": 31_396, "vol_24h": 2_014, "buys_24h": 11, "sells_24h": 10, "socials": 1, "website": 1}
        live = {**dead, "vol_24h": 150_000, "buys_24h": 900, "sells_24h": 700}
        self.assertLess(match.organic_score(dead), 40)
        self.assertGreater(match.organic_score(live), match.organic_score(dead) + 20)
        from ui import explain
        pts = {n: p for n, p, *_ in explain.organic(dead)}
        self.assertLess(pts["Volumen 24h"], 3)
        self.assertEqual(pts["Omjer kupnji"], 0)         # 21 transactions say nothing about buyers vs sellers
        self.assertAlmostEqual(sum(p for _, p, *_ in explain.organic(dead)), match.organic_score(dead), places=0)


if __name__ == "__main__":
    unittest.main()
