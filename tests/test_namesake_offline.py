"""Istoimeni tokeni: a small meme with a CEX-listed ticker is flagged, same-size namesakes are not. No network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import namesake  # noqa: E402

SMALL = "GhBPHgnNF99EThYxt4bxUfPX1hCPyAS72RCBgLjLpump"
BIG = "AjR7sWEE2RoyWtdQ3CaeuwvvWtV9JEuYJMeFDXRK1g3D"


def _pair(addr, sym, mc, chain="solana", name=None, liq=5e6):
    return {"chainId": chain, "baseToken": {"address": addr, "symbol": sym, "name": name or sym}, "marketCap": mc,
            "liquidity": {"usd": liq}, "url": f"https://dexscreener.com/{chain}/{addr}"}


class Namesake(unittest.TestCase):
    def setUp(self):
        namesake._CACHE.clear()

    def test_filip_aria(self):
        pairs = [_pair(SMALL, "ARIA", 74_000), _pair(BIG, "ARIA", 114e6, name="AriaAI"),
                 _pair("x", "ARIA", 125e6, chain="ethereum"), _pair("y", "ARIAX", 50e6)]
        hit = namesake.check(SMALL, "ARIA", 74_000, pairs=pairs)
        self.assertEqual(hit["token"], BIG)            # the Solana one, not the Ethereum one, not ARIAX
        self.assertEqual(hit["name"], "AriaAI")
        self.assertIn("kupio si kopiju", namesake.text(hit, "ARIA", 74_000))
        self.assertIn("AjR7…1g3D", namesake.text(hit, "ARIA", 74_000))

    def test_no_flag_for_peers_or_self(self):
        pairs = [_pair(SMALL, "DOG", 60_000), _pair("z", "DOG", 300_000)]   # 5x bigger but tiny: not a mix-up
        self.assertIsNone(namesake.check(SMALL, "DOG", 60_000, pairs=pairs))
        self.assertIsNone(namesake.check(BIG, "ARIA", 114e6, pairs=[_pair(BIG, "ARIA", 114e6)]))  # itself
        self.assertIsNone(namesake.check(SMALL, "", 1000, pairs=[]))

    def test_jure_useless(self):
        """5.11.: the real USELESS ($126M) was called a copy of a dead pair reporting MC $120,984M. Never again."""
        real, fake = "Dz9mQ9NzkBRWEEXrD1b2rj6vQ6XqBhcJa7rjZ5rbonk", "5m9sfake"
        pairs = [_pair(real, "USELESS", 126.77e6, name="Useless Coin"),
                 _pair(fake, "USELESS", 120_984e6, name="USELESS COIN", liq=800)]
        self.assertIsNone(namesake.check(real, "USELESS", 126.77e6, pairs=pairs))   # a $126M buy is no mix-up
        # even a small buy is not warned about a fake pool: no liquidity, absurd cap
        self.assertIsNone(namesake.check(SMALL, "USELESS", 60_000, pairs=[_pair(fake, "USELESS", 120_984e6, liq=800)]))
        self.assertIsNone(namesake.check(SMALL, "USELESS", 60_000, pairs=[_pair(fake, "USELESS", 120_984e6, liq=5e6)]))
        self.assertIsNotNone(namesake.check(SMALL, "USELESS", 60_000, pairs=[_pair(real, "USELESS", 126.77e6)]))

    def test_network_error_is_quiet(self):
        namesake._pairs = lambda s: (_ for _ in ()).throw(RuntimeError("down"))
        self.assertIsNone(namesake.check(SMALL, "ARIA", 74_000))


if __name__ == "__main__":
    unittest.main()


class CustomAmount(unittest.TestCase):
    def test_buy_forms_take_any_amount(self):
        from ui import quickbuy
        box = quickbuy.token_box("Dz9mQ9NzkBRWEEXrD1b2rj6vQ6XqBhcJa7rjZ5rbonk", "USELESS")
        self.assertIn('name=size type=number', box)          # free amount with suggestions, not a fixed dropdown
        self.assertIn("<datalist id=qb-stakes>", box)
        top = quickbuy.top_buy("Jure")
        self.assertIn("name=size_custom", top)
