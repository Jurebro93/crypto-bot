"""5.11.: graduated pump.fun tokens (kol/graduates.py) and their place in the mass shadow book."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kol import graduates, store as kstore  # noqa: E402

NOW = 1_800_000_000
WBTC = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"


def _pool(tok, name, fdv, created="2026-10-20T10:00:00Z"):
    return {"attributes": {"name": name, "fdv_usd": fdv, "volume_usd": {"h24": 1000}, "pool_created_at": created, "address": "P" + tok},
            "relationships": {"base_token": {"data": {"id": f"solana_{tok}"}}}}


class Graduates(unittest.TestCase):
    def test_fetch_collect_and_history_points(self):
        pages = {("h24_tx_count_desc", 1): {"data": [_pool("G1", "G1 / SOL", 500000), _pool(WBTC, "WBTC / SOL", 9e9), _pool("TINY", "T / SOL", 5000)]},
                 ("h24_tx_count_desc", 2): {"data": [_pool("G2", "G2 / SOL", 80000)]},
                 ("h24_volume_usd_desc", 1): {"data": [_pool("G1", "G1 / SOL", 500000), _pool("G3", "G3 / SOL", 60000)]}}
        rows = graduates.fetch(get=lambda url, p: pages.get((p["sort"], p["page"]), {"data": []}), pages=3,
                               sorts=("h24_tx_count_desc", "h24_volume_usd_desc"))
        self.assertEqual([r["token"] for r in rows], ["G1", WBTC, "TINY", "G2", "G3"])
        con = kstore.connect(os.path.join(tempfile.mkdtemp(), "kol.db"))
        self.assertEqual(graduates.collect(con, now=NOW, rows=rows), 3)                 # no WBTC, no tiny FDV
        self.assertEqual(graduates.collect(con, now=NOW, rows=rows), 0)                 # seen again, not new
        self.assertEqual(con.execute("SELECT seen FROM graduates WHERE token='G1'").fetchone()[0], 2)
        self.assertEqual({t for t, *_ in graduates.tokens(con)}, {"G1", "G2", "G3"})
        from learn import masovno
        sdb = os.path.join(tempfile.mkdtemp(), "shadow.db")
        scon = masovno.connect(sdb)
        kpath = con.execute("PRAGMA database_list").fetchone()[2]
        con.close()
        n = masovno.history(scon, NOW, kol_db=kpath, wallets_db="/nonexistent.db")
        self.assertEqual(n, 3)
        self.assertEqual({r[0] for r in scon.execute("SELECT point FROM points")}, {"povijest_bondao"})
        scon.close()


if __name__ == "__main__":
    unittest.main()
