"""15.11. (vlasnik: "Makro tržište je jako bitno: prati kretanje volumena najpoznatijih platformi i trendove";
veliki/makro.py), offline on synthetic platform volumes:

  - the platforms (pump.fun, PumpSwap, Raydium, Meteora, Orca, the trading apps, Solana DEX) and their 24 h volume
    against the 7-day average; the meme platforms summed (Orca and the prop AMMs left out)
  - the regime: risk_off (BTC free fall / the platforms -25 % / the midcaps -35 % / the sector -12 %), risk_on (the
    platforms +10 %, the midcaps +5 %, BTC not falling), neutral; unknown = neutral
  - market.db first (no new call), DefiLlama directly only when market.db is stale; the hour's row in midcap.db
    makro_h and current(); the daily regimes of the past from market.db daily (no look-ahead)

    python3 -m unittest tests.test_veliki_makro_offline
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veliki import makro, midcap  # noqa: E402

D, H = 86400, 3600
NOW = 1_790_000_000 // H * H


def rows(k=1.0, orca=1.0):
    """(slug, grp, vol24, vol7d): each meme platform's 24 h = k x its 7-day daily average."""
    base = {"pump.fun": ("launchpad", 90e6), "pumpswap": ("dex", 150e6), "raydium-amm": ("dex", 100e6),
            "raydium-cpmm": ("dex", 30e6), "meteora-dlmm": ("dex", 150e6), "axiom": ("terminal", 20e6),
            "gmgn": ("terminal", 6e6), "orca-dex": ("dex", 300e6), "humidifi": ("dex", 500e6)}
    out = []
    for slug, (g, avg) in base.items():
        kk = orca if slug in ("orca-dex", "humidifi") else k
        out.append((slug, g, avg * kk, avg * 7))
    out.append(("all:dex", "dex", 1.5e9, 1.5e9 * 7))
    return out


class Regime(unittest.TestCase):
    def test_platforms(self):
        pl = makro.platforms(rows(1.2, orca=0.5))
        for k in ("pump.fun", "PumpSwap", "Raydium", "Meteora", "Orca", "trading appovi", "Solana DEX"):
            self.assertIn(k, pl)
        self.assertAlmostEqual(pl["Raydium"]["v24"], 130e6 * 1.2)
        self.assertAlmostEqual(pl["meme"]["chg"], 0.2)               # Orca / prop AMMs out of the meme sum
        self.assertAlmostEqual(pl["Orca"]["chg"], -0.5)

    def test_regime_states(self):
        self.assertEqual(makro.regime(0.2, 0.1, "normalno", 0.01, -1.0)[0], "risk_on")
        self.assertEqual(makro.regime(0.2, None, "normalno")[0], "risk_on")          # midcaps unknown
        self.assertEqual(makro.regime(0.2, 0.0, "normalno")[0], "neutral")           # midcaps not rising
        self.assertEqual(makro.regime(0.2, 0.1, "normalno", -0.05)[0], "neutral")    # BTC -5 % in 24 h
        self.assertEqual(makro.regime(0.2, 0.1, "slobodan_pad")[0], "risk_off")
        self.assertEqual(makro.regime(-0.3, -0.25, "normalno")[0], "risk_off")
        self.assertEqual(makro.regime(-0.3, 0.1, "normalno")[0], "neutral")          # the midcaps still hold
        self.assertEqual(makro.regime(0.0, -0.4, "normalno")[0], "risk_off")
        self.assertEqual(makro.regime(0.0, 0.0, "normalno", None, -15.0)[0], "risk_off")
        self.assertEqual(makro.regime(None)[0], "neutral")

    def test_market_db_first_then_defillama_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            mpath = os.path.join(d, "market.db")
            from market import store as mstore
            con = mstore.connect(mpath)
            for slug, g, v24, v7 in rows(1.3):
                con.execute("INSERT INTO platforms VALUES (?,?,?,?)", (slug, slug, "x", g))
                con.execute("INSERT INTO snap VALUES (?,?,?,?)", (NOW - H, slug, v24, v7))
            con.commit()
            con.close()
            calls = []
            with mock.patch.dict(makro.FETCH, {"overview": lambda: calls.append(1) or {"protocols": []},
                                               "sector": lambda: [{"id": "solana-meme-coins", "market_cap": 2.1e9,
                                                                   "volume_24h": 5e8,
                                                                   "market_cap_change_24h": 1.0}]}), \
                    mock.patch.object(makro, "_btc", lambda now: ("normalno", 0.01)):
                s = makro.snapshot(None, NOW, mpath)
                self.assertEqual(calls, [])
                self.assertEqual(s["src"], "market.db")
                self.assertEqual(s["regime"], "risk_on")
                s2 = makro.snapshot(None, NOW + 5 * H, mpath)                   # market.db stale: one direct call
                self.assertEqual(calls, [1])
                self.assertEqual(s2["regime"], "neutral")
                mdb = os.path.join(d, "midcap.db")
                mc = midcap.connect(mdb)
                lines = []
                makro.refresh(mc, NOW, lines.append, mpath)
                mc.close()
                self.assertTrue(lines[0].startswith("makro platforme: pump.fun 24 h $"), lines)
                self.assertIn("režim risk_on", lines[0])
                self.assertIn("Solana meme sektor", lines[0])
                self.assertEqual(makro.current(NOW + 60, mdb)["regime"], "risk_on")
                self.assertIsNone(makro.current(NOW + 5 * H, mdb))             # too old: unknown

    def test_midcap_volume_against_own_week(self):
        with tempfile.TemporaryDirectory() as d:
            mc = midcap.connect(os.path.join(d, "midcap.db"))
            for i in range(6):
                mc.execute("INSERT INTO tokens (mint, id, member, trend) VALUES (?,?,1,?)", (f"m{i}", i, 1 if i else None))
                for k in range(48):
                    mc.execute("INSERT INTO snap (id, ts, px, v24) VALUES (?,?,?,?)", (i, NOW - k * H, 1.0, 1e6))
                mc.execute("UPDATE snap SET v24=? WHERE id=? AND ts=?", (3e5, i, NOW))
            m = makro.midcaps(mc, NOW)
            mc.close()
            self.assertEqual(m["n"], 6)
            self.assertLess(m["chg"], -0.6)
            self.assertEqual(m["trending"], 5)
            self.assertEqual(makro.regime(0.0, m["chg"])[0], "risk_off")

    def test_daily_regimes_no_look_ahead(self):
        with tempfile.TemporaryDirectory() as d:
            mpath = os.path.join(d, "market.db")
            from market import store as mstore
            con = mstore.connect(mpath)
            con.execute("INSERT INTO platforms VALUES ('pumpswap','PumpSwap','Dexs','dex')")
            day0 = NOW // D * D - 30 * D
            for k in range(30):
                v = 100e6 if k < 20 else (200e6 if k < 25 else 40e6)
                con.execute("INSERT INTO daily VALUES (?,?,?)", (day0 + k * D, "pumpswap", v))
            con.commit()
            con.close()
            reg = makro.daily_regimes({}, None, mpath)
            self.assertEqual(reg[(day0 + 21 * D) // D], "risk_on")        # day 20's volume known on day 21
            self.assertEqual(reg[(day0 + 20 * D) // D], "neutral")        # not yet on day 20 itself
            self.assertEqual(reg[(day0 + 27 * D) // D], "risk_off")


if __name__ == "__main__":
    unittest.main()
