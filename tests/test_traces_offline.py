"""5.11.: suspicious transfers around influencers (kol/traces.py) from Helius TRANSFER events."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import chainwatch, store as kstore, traces  # noqa: E402

NOW = 1_800_000_000
KOL, OTHER, DEV = "K" * 44, "O" * 44, "D" * 44
MINT = "M" * 44


def _tx(sig, src, dst, mint, amount, ts, native=None):
    tx = {"type": "TRANSFER", "signature": sig, "timestamp": ts,
          "tokenTransfers": [{"fromUserAccount": src, "toUserAccount": dst, "mint": mint, "tokenAmount": amount}] if mint else []}
    if native:
        tx["nativeTransfers"] = [{"fromUserAccount": src, "toUserAccount": dst, "amount": int(native * 1e9)}]
    return tx


class Traces(unittest.TestCase):
    def test_parse_rules_flags_and_page(self):
        tmp = tempfile.mkdtemp()
        hype = os.path.join(tmp, "hype.db")
        events = [_tx("s1", DEV, KOL, MINT, 30_000_000, NOW - 7200),          # dev sends 3 % of supply to a KOL
                  _tx("s2", KOL, OTHER, None, 0, NOW - 3600, native=2.0),      # SOL between two tracked wallets
                  _tx("s3", DEV, "X" * 44, MINT, 1_000, NOW - 3000),           # nobody tracked: ignored
                  {"type": "SWAP", "signature": "s4", "timestamp": NOW, "feePayer": KOL, "tokenTransfers": []}]
        n = chainwatch.ingest(events, hype)
        self.assertEqual(n, 3)   # every transfer Helius delivers is stored (it only sends tracked wallets anyway)
        self.assertEqual(sorted(r[0] for r in chainwatch.parse_transfers(events, {KOL, OTHER})), ["s1", "s2"])
        con = kstore.connect(os.path.join(tmp, "kol.db"))
        from kol import idents
        idents.save(con, [{"wallet": KOL, "name": "kolguy", "twitter": "kolguy", "telegram": None, "pnl": 1, "wins": 1, "losses": 0, "rank": 1},
                          {"wallet": OTHER, "name": "crew", "twitter": None, "telegram": None, "pnl": 1, "wins": 1, "losses": 0, "rank": 2}], "kolscan")
        con.execute("INSERT INTO tokens (token, supply) VALUES (?, 1000000000)", (MINT,))
        con.execute("INSERT INTO calls (tweet_id, token, handle, ts, kind) VALUES ('t1', ?, 'kolguy', ?, 'call')", (MINT, NOW - 1800))
        con.commit()
        self.assertEqual(traces.run(con, hype, now=NOW), 3)                 # veza, supply, primio_pa_zvao
        self.assertEqual(traces.run(con, hype, now=NOW), 0)                 # idempotent
        kinds = sorted(r[0] for r in traces.for_handle(con, "kolguy"))
        self.assertEqual(kinds, ["primio_pa_zvao", "supply", "veza"])
        rec = [r for r in traces.for_handle(con, "kolguy") if r[0] == "primio_pa_zvao"][0]
        self.assertEqual(json.loads(rec[6])["minutes_to_call"], 90)
        self.assertAlmostEqual(rec[4], 3.0)
        flags = traces.token_flags(os.path.join(tmp, "kol.db"), [MINT, "ZZZ"], NOW - 86400)
        self.assertEqual(flags[MINT]["primio_pa_zvao"], 1)
        html = traces.html(con, "kolguy")
        self.assertIn("primio tokene, pa ih zvao", html)
        self.assertIn("3.0 % supplya", html)
        from ui import confidence
        lo, parts = confidence.score(hype=60, features={"primio_supply": 1.0}, mcap=250_000)
        hi, _ = confidence.score(hype=60, features={}, mcap=250_000)
        self.assertEqual(hi - lo, 10)
        con.close()


if __name__ == "__main__":
    unittest.main()
