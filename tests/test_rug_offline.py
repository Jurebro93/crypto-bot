"""Rug filter rules on synthetic transactions (no network).

    python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rugfilter import analysis as A  # noqa: E402
from rugfilter.score import score  # noqa: E402

MINT, CURVE, DEV = "MINTpump", "CURVE", "DEV"
SUPPLY = 1_000_000_000


def tx(sig, slot, ts, payer, transfers, typ="SWAP", native=()):
    return {"signature": sig, "slot": slot, "timestamp": ts, "feePayer": payer, "type": typ,
            "tokenTransfers": [{"mint": MINT, "fromUserAccount": a, "toUserAccount": b, "tokenAmount": amt}
                               for a, b, amt in transfers],
            "nativeTransfers": [{"fromUserAccount": a, "toUserAccount": b, "amount": lam} for a, b, lam in native]}


def launch_txs():
    txs = [tx("c", 100, 1000, DEV, [(CURVE, DEV, 50_000_000)], typ="CREATE")]
    # bundle: 3 wallets in the creation slot, 10% each
    txs += [tx(f"b{i}", 100, 1000, f"B{i}", [(CURVE, f"B{i}", 100_000_000)]) for i in range(3)]
    # snipers: 2 wallets 5 slots later
    txs += [tx(f"s{i}", 105, 1002, f"S{i}", [(CURVE, f"S{i}", 20_000_000)]) for i in range(2)]
    # organic buyer much later
    txs += [tx("late", 500, 1200, "L", [(CURVE, "L", 1_000_000)])]
    return txs


class Launch(unittest.TestCase):
    def test_bundle_snipers_dev(self):
        pools = {CURVE}
        L = A.launch(launch_txs(), MINT, SUPPLY, pools)
        self.assertEqual(L["dev"], DEV)
        self.assertEqual(L["dev_initial_pct"], 5.0)
        self.assertEqual((L["bundle_wallets"], L["bundle_pct"]), (3, 30.0))
        self.assertEqual((L["sniper_wallets"], L["sniper_pct"]), (2, 4.0))
        self.assertEqual(L["first_buyers"][:3], ["B0", "B1", "B2"])

    def test_curve_found_from_create(self):
        self.assertEqual(A.curve_accounts(launch_txs()[0], MINT), {CURVE})

    def test_pool_detection_without_hint(self):
        txs = [tx(f"t{i}", i, i, f"W{i}", [(f"W{i}", "POOL", 10)]) for i in range(20)]
        self.assertIn("POOL", A.detect_pools(txs, MINT))

    def test_dev_moving_tokens_is_not_a_sell(self):
        txs = launch_txs() + [tx("mv", 600, 1300, DEV, [(DEV, "HIDDEN", 30_000_000)], typ="TRANSFER"),
                              tx("sl", 601, 1301, DEV, [(DEV, CURVE, 20_000_000)])]
        sold, moved = A.dev_sold([txs], MINT, DEV, {CURVE})
        self.assertEqual((sold, moved), (20_000_000, 30_000_000))


class Wallets(unittest.TestCase):
    def test_funder_and_clusters(self):
        def first(w, funder):
            return [tx("f" + w, 1, 900, funder, [], typ="TRANSFER", native=[(funder, w, 2_000_000_000)])]
        profiles = [A.wallet_profile(w, first(w, "BOSS")) for w in ("B0", "B1", "B2")]
        profiles += [A.wallet_profile("S0", first("S0", "CEX")), A.wallet_profile("S1", first("S1", "CEX"))]
        profiles += [A.wallet_profile("X", first("X", DEV))]
        self.assertEqual(profiles[0]["funder"], "BOSS")
        groups = A.clusters(profiles, DEV, hubs={"CEX"})
        flat = [sorted(g) for g in groups]
        self.assertIn(["B0", "B1", "B2"], flat)
        self.assertTrue(any(DEV in g and "X" in g for g in groups))
        self.assertFalse(any("S0" in g for g in groups))  # exchange funding links nobody
        best = A.cluster_share(groups, {"B0": 10, "B1": 8, "B2": 9}, {})
        self.assertEqual(best["holding_pct"], 27)

    def test_fresh(self):
        self.assertTrue(A.is_fresh({"first_ts": 1000}, 1000 + 3600))
        self.assertFalse(A.is_fresh({"first_ts": 1000}, 1000 + 10 * 86400))


class Volume(unittest.TestCase):
    def test_wash_vs_organic(self):
        # two bots ping-pong the same size every 10 s
        wash = []
        for i in range(60):
            w = f"BOT{i % 2}"
            side = "buy" if i % 4 < 2 else "sell"
            wash.append({"wallet": w, "side": side, "amount": 1000.0, "ts": i * 10})
        organic = [{"wallet": f"U{i}", "side": "buy" if i % 3 else "sell", "amount": 100 + i * 37.0, "ts": i * 7 + (i % 5)}
                   for i in range(60)]
        vw, vo = A.volume_quality(wash), A.volume_quality(organic)
        self.assertGreater(A.wash_score(vw), 60)
        self.assertLess(A.wash_score(vo), 20)
        self.assertEqual(vw["round_trip_volume_pct"], 100.0)


class Score(unittest.TestCase):
    def base(self):
        return {"authorities": {}, "rugcheck": {"insider_pct": 0}, "launch": {"bundle_pct": 2, "bundle_wallets": 1,
                "sniper_pct": 3, "sniper_wallets": 2, "dev_initial_pct": 3}, "dev": {"tokens_created": 1,
                "tokens_alive": 1, "hold_pct": 1, "sold_pct": 0, "moved_pct": 0}, "cluster": {"wallets": [],
                "holding_pct": 0, "early_pct": 0}, "holders": {"top10_pct": 20}, "wash_score": 5,
                "volume": {"trades": 100, "wallets": 80}, "market": {"liquidity": 50_000, "vol_24h": 100_000}}

    def test_clean_passes(self):
        self.assertEqual(score(self.base())["verdict"], "PROLAZI")

    def test_hard_fails(self):
        for patch in ({"authorities": {"mintAuthority": "abcdefgh"}},
                      {"launch": {"bundle_pct": 30, "bundle_wallets": 5}},
                      {"dev": {"tokens_created": 40, "tokens_alive": 1}},
                      {"cluster": {"wallets": ["a", "b"], "holding_pct": 30, "early_pct": 0}},
                      {"wash_score": 80},
                      {"market": {"liquidity": 1000}}):
            r = {**self.base(), **patch}
            self.assertEqual(score(r)["verdict"], "ODBAČEN", patch)


if __name__ == "__main__":
    unittest.main()
