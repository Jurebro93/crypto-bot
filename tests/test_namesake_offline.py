"""Istoimeni tokeni: a small meme with a CEX-listed ticker is flagged, same-size namesakes are not. No network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import namesake  # noqa: E402

SMALL = "GhBPHgnNF99EThYxt4bxUfPX1hCPyAS72RCBgLjLpump"
BIG = "AjR7sWEE2RoyWtdQ3CaeuwvvWtV9JEuYJMeFDXRK1g3D"


def _pair(addr, sym, mc, chain="solana", name=None):
    return {"chainId": chain, "baseToken": {"address": addr, "symbol": sym, "name": name or sym}, "marketCap": mc,
            "url": f"https://dexscreener.com/{chain}/{addr}"}


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

    def test_network_error_is_quiet(self):
        namesake._pairs = lambda s: (_ for _ in ()).throw(RuntimeError("down"))
        self.assertIsNone(namesake.check(SMALL, "ARIA", 74_000))


if __name__ == "__main__":
    unittest.main()
