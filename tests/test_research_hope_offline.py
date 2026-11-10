"""10.11. (Jure, Hope): research/hope.py reads the curve and pool transactions (fake Helius here) and our databases,
and writes per wallet: first buy (time, venue, market cap), SOL in/out, first/last sell, phase, tier, linked account;
the calls before Marko; the file and the MCP tool get_research. Read only: no database is written."""
import base64
import gzip
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import hope, store  # noqa: E402

M = hope.MINT
MIGR = 1794304916
A, B, C, K = "WalA" + "1" * 40, "WalB" + "2" * 40, "WalC" + "3" * 40, "Kol1" + "4" * 40


def tx(sig, ts, signer, tok_pre, tok_post, lam_pre, lam_post, slot=None):
    return {"slot": slot or ts, "blockTime": ts,
            "transaction": {"signatures": [sig], "message": {"accountKeys": [{"pubkey": signer}, {"pubkey": "x"}]}},
            "meta": {"preBalances": [lam_pre, 0], "postBalances": [lam_post, 0],
                     "preTokenBalances": [{"mint": M, "owner": signer, "uiTokenAmount": {"uiAmount": tok_pre}}],
                     "postTokenBalances": [{"mint": M, "owner": signer, "uiTokenAmount": {"uiAmount": tok_post}}]}}


CURVE_TXS = [
    tx("s1", MIGR - 3600, A, 0, 10_000_000, 5_000_000_000, 4_000_000_000, slot=100),     # A buys 10M for 1 SOL
    tx("s2", MIGR - 3600, B, 0, 5_000_000, 3_000_000_000, 2_500_000_000, slot=100),      # B same slot
    tx("s3", MIGR - 1800, C, 0, 5_000_000, 3_000_000_000, 2_400_000_000, slot=200),
]
D1, D2 = "Dst1" + "5" * 40, "Dst2" + "6" * 40
BUNDLE = tx("s6", MIGR - 600, K, 0, 0, 20_000_000_000, 18_000_000_000, slot=300)    # K pays 2 SOL ...
BUNDLE["meta"]["postTokenBalances"] += [{"mint": M, "owner": D1, "uiTokenAmount": {"uiAmount": 4_000_000}},
                                        {"mint": M, "owner": D2, "uiTokenAmount": {"uiAmount": 4_000_000}}]
CURVE_TXS.append(BUNDLE)                                                                 # ... tokens go to D1, D2
POOL_TXS = [
    tx("s4", MIGR + 600, A, 10_000_000, 0, 4_000_000_000, 7_000_000_000),               # A sells all for 3 SOL
    tx("s5", MIGR + 4000, K, 0, 1_000_000, 9_000_000_000, 8_000_000_000),               # K buys after Marko
]


def fake_post(method, params):
    if method == "getTransactionsForAddress":
        addr, opts = params
        data = CURVE_TXS if addr == hope.CURVE else POOL_TXS
        if opts.get("paginationToken"):
            return {"data": []}
        return {"data": data, "paginationToken": None}
    if method == "getTokenLargestAccounts":
        return {"value": [{"address": "acc1", "uiAmount": 5_000_000}]}
    if method == "getMultipleAccounts":
        return {"value": [{"data": {"parsed": {"info": {"owner": C}}}}]}
    raise AssertionError(method)


class Hope(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        kdb, wdb, hdb = (os.path.join(self.d, n) for n in ("kol.db", "wallets.db", "hype.db"))
        k = sqlite3.connect(kdb)
        k.execute("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT, source TEXT, "
                  "mcap0 REAL, followers INTEGER, url TEXT, text TEXT)")
        k.executemany("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?)", [
            ("1", M, "early1", MIGR + 300, "call", "x", 45_000, 900, "u", "t"),
            ("2", M, "0xMarko77", MIGR + 3000, "call", "x", 90_000, 20_000, "u", "t"),
            ("3", "other", "x", MIGR, "call", "x", 1, 1, "u", "t")])
        k.execute("CREATE TABLE kols (handle TEXT, followers INTEGER)")
        k.execute("CREATE TABLE kol_ids (wallet TEXT PRIMARY KEY, name TEXT, twitter TEXT, telegram TEXT, source TEXT)")
        k.execute("INSERT INTO kol_ids VALUES (?,?,?,?,?)", (A, "Early", "early1", None, "kolscan"))
        k.commit()
        k.close()
        w = sqlite3.connect(wdb)
        w.execute("CREATE TABLE wallets (wallet TEXT PRIMARY KEY, tier TEXT, score REAL)")
        w.execute("INSERT INTO wallets VALUES (?,?,?)", (C, "A", 71.0))
        w.commit()
        w.close()
        h = sqlite3.connect(hdb)
        h.execute("CREATE TABLE chain_trades (sig TEXT, wallet TEXT, mint TEXT, side TEXT, ts INTEGER, sol REAL)")
        h.commit()
        h.close()
        self.paths = (kdb, wdb, hdb)
        self.before = {p: os.path.getmtime(p) for p in self.paths}
        os.environ["DATA_DIR"] = self.d

    def tearDown(self):
        os.environ.pop("DATA_DIR", None)

    def run_it(self):
        lines = []
        with mock.patch.object(hope, "_paths", return_value=self.paths), \
                mock.patch.object(hope, "sol_usd", return_value=150.0):
            res = hope.run(log=lines.append, post=fake_post)
        return res, lines

    def test_wallets_calls_links_and_files(self):
        res, lines = self.run_it()
        W = {w["wallet"]: w for w in res["wallets"]}
        a = W[A]
        self.assertEqual((a["first_buy_venue"], a["sol_in"], a["sol_out"], a["net_tok"]), ("curve", 1.0, 3.0, 0))
        self.assertEqual(a["pnl_sol"], 2.0)
        self.assertEqual(a["first_sell_ts"], MIGR + 600)
        self.assertEqual(a["phase"], "punjenje krivulje (prije migracije)")
        self.assertEqual(a["first_buy_mc"], round(1.0 / 10_000_000 * 1e9 * 150))      # 15 000 $
        self.assertEqual(a["x_or_tg"]["x"], "early1")
        self.assertEqual(W[C]["tier"], "A")
        self.assertEqual(W[K]["phase"], "nakon Marka")
        self.assertEqual([c["handle"] for c in res["calls_before_marko"]], ["early1"])
        self.assertEqual(res["marko_call"]["mcap0"], 90_000)
        self.assertEqual(res["caller_trades"]["early1"][0]["sol_out"], 3.0)
        self.assertEqual(res["bundles_first_buy_same_slot"], {})            # 2 in slot 100 is below the 3 threshold
        self.assertEqual(res["holders_top20"][0]["owner"], C)
        # the files, the summary in the log and the compact blob that decodes
        self.assertTrue(os.path.exists(os.path.join(self.d, "research", hope.NAME + ".json")))
        self.assertTrue(any("Faze prve kupnje" in s for s in lines))
        chunks = [s.split(" ", 2)[2] for s in lines if s.startswith("RESEARCH-HOPE ")]
        blob = json.loads(gzip.decompress(base64.b64decode("".join(chunks))))
        self.assertEqual(blob["wallets_total"], 6)
        self.assertEqual({r[0] for r in blob["wrows"]}, {A, B, C, K, D1, D2})
        # bought for others: the payer and the two receivers are linked
        self.assertEqual(sorted(W[K]["sent_to"]), sorted([D1, D2]))
        self.assertEqual((W[D1]["received_from"], W[D1]["net_tok"], W[D1]["phase"]),
                         ([K], 4_000_000, "samo primio tokene (nije kupio)"))
        # read only: our databases are untouched
        self.assertEqual(self.before, {p: os.path.getmtime(p) for p in self.paths})

    def test_mcp_get_research(self):
        self.run_it()
        from ui import mcpapi
        d, err = mcpapi._tool("get_research", {})
        self.assertFalse(err)
        self.assertEqual(d["reports"][0]["name"], hope.NAME)
        d, err = mcpapi._tool("get_research", {"name": hope.NAME})
        self.assertFalse(err)
        self.assertIn("summary_md", d)
        self.assertEqual(d["n_wallets"], 6)
        d, _ = mcpapi._tool("get_research", {"name": hope.NAME, "part": "wallets", "sort": "pnl_sol", "limit": 1})
        self.assertEqual((d["total"], d["rows"][0]["wallet"]), (6, A))
        d, err = mcpapi._tool("get_research", {"name": "../etc"})
        self.assertTrue(err)
        self.assertIn("get_research", [t["name"] for t in mcpapi.TOOLS])

    def test_main_runs_once(self):
        with mock.patch.dict(os.environ, {"HELIUS_API_KEY": "k"}), mock.patch.object(hope, "run") as run:
            self.assertEqual(hope.main([]), 0)
            self.assertEqual(hope.main([]), 0)
        self.assertEqual(run.call_count, 1)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HELIUS_API_KEY", None)
            self.assertEqual(hope.main(["--force"]), 1)


if __name__ == "__main__":
    unittest.main()
