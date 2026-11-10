"""10.11. (Grok MCP audit 9): sells in hype.db chain_trades had sol NULL (get_wallet_history showed "sol": null).

Root cause: kol/chainwatch.parse wrote every webhook sell with sol None; it summed only the SOL a wallet spent. The
writer now keeps the SOL the wallet got (accountData, else wSOL / native transfers to it), and wallets/solfill.py
fills the rows written before, once per signature from getTransaction (no network here: the RPC is faked).
"""
import datetime as dt
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from kol import chainwatch
from ops import cpuguard, heavy
from wallets import solfill

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
W = "Wa11et1111111111111111111111111111111111111"
CA = "Tok1111111111111111111111111111111111111pump"
CB = "TokB111111111111111111111111111111111111pump"
WSOL = chainwatch.SOL
NOW = int(dt.datetime(2026, 11, 11, 1, 30, tzinfo=dt.timezone.utc).timestamp())   # 02:30 Zagreb


def rpc_tx(sig, pre, post, tokens=(), err=None, wallet=W):
    """A jsonParsed getTransaction result: the wallet's lamports before/after at index 0 and its token balances
    [(mint, raw before or None, raw after or None, decimals)] (None: the account did not exist / was closed)."""
    keys = [{"pubkey": wallet, "signer": True, "writable": True, "source": "transaction"},
            {"pubkey": "CURVE", "signer": False, "writable": True, "source": "transaction"},
            {"pubkey": "POOLx", "signer": False, "writable": True, "source": "lookupTable"}]
    pre_t, post_t = [], []
    for i, (mint, a, b, dec) in enumerate(tokens):
        if a is not None:
            pre_t.append({"accountIndex": 3 + i, "mint": mint, "owner": wallet,
                          "uiTokenAmount": {"amount": str(a), "decimals": dec}})
        if b is not None:
            post_t.append({"accountIndex": 3 + i, "mint": mint, "owner": wallet,
                           "uiTokenAmount": {"amount": str(b), "decimals": dec}})
    return {"blockTime": NOW - 600, "slot": 1, "version": 0,
            "transaction": {"signatures": [sig], "message": {"accountKeys": keys}},
            "meta": {"err": err, "fee": 5000, "preBalances": [pre, 9_000_000_000, 1], "postBalances": [post, 8_000_000_000, 1],
                     "preTokenBalances": pre_t, "postTokenBalances": post_t}}


# pump.fun bonding-curve sale: the curve pays the wallet directly (no system transfer, no wSOL): only the balances show it
PUMP_SELL = rpc_tx("SIG_PUMP", 1_000_000_000, 1_734_561_000, [(CA, 5_000_000_000_000, None, 6)])
# AMM sale settled in wSOL that stays in the wallet's wSOL account: lamports go down by the fee, wSOL up
WSOL_SELL = rpc_tx("SIG_WSOL", 2_000_000_000, 1_999_995_000,
                   [(CA, 7_000_000, 0, 6), (WSOL, 100_000_000, 1_312_345_678, 9)])


class Db:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "hype.db")
        con = sqlite3.connect(self.path)
        chainwatch._create(con)
        con.commit()
        con.close()

    def add(self, *rows):
        con = sqlite3.connect(self.path)
        con.executemany("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", rows)
        con.commit()
        con.close()

    def sol(self, sig, mint=CA):
        con = sqlite3.connect(self.path)
        try:
            return con.execute("SELECT sol FROM chain_trades WHERE sig=? AND mint=?", (sig, mint)).fetchone()[0]
        finally:
            con.close()

    def q(self, sql, args=()):
        con = sqlite3.connect(self.path)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()


class FakeRpc:
    def __init__(self, txs, fail=()):
        self.txs, self.fail, self.calls = txs, set(fail), []

    def __call__(self, sig):
        self.calls.append(sig)
        if sig in self.fail:
            raise RuntimeError("Helius getTransaction: timeout")
        return self.txs.get(sig)


def quiet(*a, **k):
    pass


class Backfill(unittest.TestCase):
    def setUp(self):
        self.db = Db()

    def run_once(self, rpc, **kw):
        kw.setdefault("force", True)
        return solfill.run(self.db.path, fetch=rpc, now=kw.pop("now", NOW), log=quiet, **kw)

    def test_sale_amount_from_the_wallet_balance(self):
        self.db.add(("SIG_PUMP", W, CA, "sell", NOW - 600, None))
        rpc = FakeRpc({"SIG_PUMP": PUMP_SELL})
        out = self.run_once(rpc)
        self.assertEqual(self.db.sol("SIG_PUMP"), 0.7346)   # (1.734561 - 1.0) SOL, positive like a buy's
        self.assertEqual((out["calls"], out["filled"], out["pending"]), (1, 1, 0))
        self.assertEqual(rpc.calls, ["SIG_PUMP"])

    def test_sale_settled_in_wsol(self):
        self.db.add(("SIG_WSOL", W, CA, "sell", NOW - 600, None))
        self.run_once(FakeRpc({"SIG_WSOL": WSOL_SELL}))
        self.assertEqual(self.db.sol("SIG_WSOL"), 1.2123)   # -0.000005 SOL fee + 1.212345678 wSOL in

    def test_sol_change_reads_the_wallet_index_and_wsol(self):
        self.assertAlmostEqual(solfill.sol_change(PUMP_SELL, W), 0.734561, places=9)
        self.assertAlmostEqual(solfill.sol_change(WSOL_SELL, W), 1.212340678, places=9)
        self.assertIsNone(solfill.sol_change(PUMP_SELL, "SOMEONE_ELSE"))
        self.assertIsNone(solfill.sol_change(rpc_tx("X", 1, 2, err={"InstructionError": [0, "Custom"]}), W))
        tx = rpc_tx("X", 1_000_000_000, 1_500_000_000)
        tx["transaction"]["message"]["accountKeys"] = [W, "CURVE", "POOLx"]   # plain string keys work too
        self.assertAlmostEqual(solfill.sol_change(tx, W), 0.5)

    def test_unknown_rows_are_left_alone(self):
        self.db.add(("SIG_GONE", W, CA, "sell", NOW - 100, None),                       # the node does not know it
                    ("SIG_FAIL", W, CA, "sell", NOW - 200, None),                       # failed transaction
                    ("SIG_T2T", W, CA, "sell", NOW - 300, None), ("SIG_T2T", W, CB, "buy", NOW - 300, 0.0),
                    ("SIG_USDC", W, CA, "sell", NOW - 400, None),                       # sold for a stable: no SOL in
                    ("SIG_NOMOVE", W, CA, "sell", NOW - 500, None),                     # token did not leave the wallet
                    (None, W, CA, "sell", NOW - 50, None), ("", W, CB, "sell", NOW - 50, None),   # no signature
                    ("SIG_BUY", W, CB, "buy", NOW - 60, 0.42))                          # already has its amount
        rpc = FakeRpc({"SIG_FAIL": rpc_tx("SIG_FAIL", 10**9, 10**9 - 5000, [(CA, 10, 0, 6)], err={"x": 1}),
                       "SIG_USDC": rpc_tx("SIG_USDC", 10**9, 10**9 - 5000, [(CA, 10, 0, 6)]),
                       "SIG_NOMOVE": rpc_tx("SIG_NOMOVE", 10**9, 2 * 10**9, [(CA, 10, 10, 6)])})
        out = self.run_once(rpc)
        for sig in ("SIG_GONE", "SIG_FAIL", "SIG_T2T", "SIG_USDC", "SIG_NOMOVE"):
            self.assertIsNone(self.db.sol(sig), sig)
        self.assertEqual(self.db.sol("SIG_T2T", CB), 0.0)
        self.assertEqual(self.db.sol("SIG_BUY", CB), 0.42)
        self.assertEqual(len(self.db.q("SELECT * FROM chain_trades WHERE sig IS NULL OR sig = ''")), 2)
        self.assertNotIn("SIG_T2T", rpc.calls)   # token-for-token is known from our own rows: no paid call
        self.assertEqual(sorted(rpc.calls), ["SIG_FAIL", "SIG_GONE", "SIG_NOMOVE", "SIG_USDC"])
        why = dict(self.db.q("SELECT sig, why FROM chain_solfill"))
        self.assertEqual(why["SIG_T2T"], "zamjena token za token")
        self.assertEqual(why["SIG_GONE"], "transakcija nije pronađena")
        self.assertEqual(why["SIG_USDC"], "bez SOL-a u transakciji")
        self.assertEqual((out["filled"], out["left"], out["pending"]), (0, 5, 0))
        rpc.calls.clear()
        self.run_once(rpc, now=NOW + 86400)   # the next night: nothing is paid for twice
        self.assertEqual(rpc.calls, [])

    def test_one_call_per_signature_and_a_split_for_two_tokens(self):
        tx = rpc_tx("SIG_TWO", 1_000_000_000, 2_000_000_000, [(CA, 10, 0, 6), (CB, 20, 0, 6)])
        self.db.add(("SIG_TWO", W, CA, "sell", NOW - 10, None), ("SIG_TWO", W, CB, "sell", NOW - 10, None))
        rpc = FakeRpc({"SIG_TWO": tx})
        self.run_once(rpc)
        self.assertEqual(rpc.calls, ["SIG_TWO"])
        self.assertEqual((self.db.sol("SIG_TWO", CA), self.db.sol("SIG_TWO", CB)), (0.5, 0.5))

    def test_rpc_errors_are_not_marked_and_three_in_a_row_stop_the_pass(self):
        sigs = [f"SIG_E{i}" for i in range(5)]
        self.db.add(*[(s, W, CA, "sell", NOW - i, None) for i, s in enumerate(sigs)])
        rpc = FakeRpc({}, fail=sigs)
        out = self.run_once(rpc)
        self.assertEqual(len(rpc.calls), solfill.MAX_ERRORS)
        self.assertEqual(out["errors"], solfill.MAX_ERRORS)
        self.assertEqual(self.db.q("SELECT COUNT(*) FROM chain_solfill"), [(0,)])   # tried again next night
        self.assertEqual(out["pending"], 5)

    def test_night_budget_holds_across_restarts(self):
        self.db.add(*[(f"SIG_{i}", W, CA, "sell", NOW - 10 - i, None) for i in range(3)])
        rpc = FakeRpc({f"SIG_{i}": rpc_tx(f"SIG_{i}", 10**9, 2 * 10**9, [(CA, 10, 0, 6)]) for i in range(3)})
        with mock.patch.object(solfill, "MAX_NIGHT", 2):
            self.assertEqual(self.run_once(rpc)["calls"], 2)
            self.assertEqual(self.run_once(rpc, now=NOW + 3600)["calls"], 0)   # a deploy at 03:30: budget spent
            self.assertEqual(rpc.calls, ["SIG_0", "SIG_1"])                    # newest first
            self.assertEqual(self.run_once(rpc, now=NOW + 86400)["calls"], 1)  # the next night
        self.assertEqual(self.db.sol("SIG_2"), 1.0)
        self.assertEqual(sorted(self.db.q("SELECT night, calls FROM chain_solfill_runs")),
                         [("2026-11-11", 2), ("2026-11-12", 1)])
        self.assertEqual(self.run_once(FakeRpc({}), max_calls=0)["calls"], 0)

    def test_only_in_the_night_window(self):
        self.db.add(("SIG_PUMP", W, CA, "sell", NOW - 600, None))
        rpc = FakeRpc({"SIG_PUMP": PUMP_SELL})
        with mock.patch.object(heavy, "night_now", return_value=False):
            out = solfill.run(self.db.path, fetch=rpc, now=NOW, log=quiet)
        self.assertEqual((out["calls"], rpc.calls), (0, []))
        self.assertIsNone(self.db.sol("SIG_PUMP"))
        with mock.patch.object(heavy, "night_now", return_value=True):
            solfill.run(self.db.path, fetch=rpc, now=NOW, log=quiet)
        self.assertEqual(self.db.sol("SIG_PUMP"), 0.7346)

    def test_dry_run_only_counts(self):
        self.db.add(("SIG_PUMP", W, CA, "sell", NOW - 600, None))
        rpc = FakeRpc({"SIG_PUMP": PUMP_SELL})
        out = solfill.run(self.db.path, fetch=rpc, now=NOW, log=quiet, dry=True)
        self.assertEqual((out["pending"], rpc.calls), (1, []))

    def test_no_chain_table_yet(self):
        path = os.path.join(tempfile.mkdtemp(), "hype.db")
        sqlite3.connect(path).close()
        self.assertEqual(solfill.run(path, fetch=FakeRpc({}), now=NOW, log=quiet, force=True)["calls"], 0)
        self.assertEqual(solfill.run(os.path.join(tempfile.mkdtemp(), "none.db"), fetch=FakeRpc({}), force=True)["calls"], 0)

    def test_the_real_fetch_asks_getTransaction_jsonParsed_v0_once(self):
        from wallets import rpc
        with mock.patch.object(rpc, "_rpc", return_value=(PUMP_SELL, False)) as call:
            self.assertIs(solfill.fetch_tx("SIG_PUMP"), PUMP_SELL)
        method, params = call.call_args[0][:2]
        self.assertEqual(method, "getTransaction")
        self.assertEqual(params[0], "SIG_PUMP")
        self.assertEqual(params[1]["encoding"], "jsonParsed")
        self.assertEqual(params[1]["maxSupportedTransactionVersion"], 0)

    def test_without_helius_key_the_command_does_nothing(self):
        with mock.patch.dict(os.environ, {"HELIUS_API_KEY": ""}), mock.patch.object(solfill, "run") as r, \
                mock.patch("builtins.print"):
            self.assertEqual(solfill.main([]), 0)
        r.assert_not_called()


# ---------- the writer (Helius enhanced webhook -> chain_trades) --------------------------------------------------

def hook_sell(**over):
    """A Helius enhanced SWAP of a pump.fun sale as the webhook delivers it: the wallet gives the token; the curve pays
    it directly, so no native transfer goes TO the wallet (only its tip goes out); accountData shows the SOL."""
    tx = {"type": "SWAP", "source": "PUMP_FUN", "signature": "SIG_PUMP", "timestamp": NOW - 600, "feePayer": W,
          "fee": 5000,
          "nativeTransfers": [{"fromUserAccount": W, "toUserAccount": "JitoTip", "amount": 100_000}],
          "tokenTransfers": [{"fromUserAccount": W, "toUserAccount": "CURVE", "fromTokenAccount": "ATA",
                              "toTokenAccount": "CURVE_ATA", "tokenAmount": 5_000_000.0, "mint": CA}],
          "accountData": [
              {"account": W, "nativeBalanceChange": 734_561_000, "tokenBalanceChanges": []},
              {"account": "CURVE", "nativeBalanceChange": -735_000_000, "tokenBalanceChanges": []},
              {"account": "ATA", "nativeBalanceChange": 0, "tokenBalanceChanges": [
                  {"userAccount": W, "tokenAccount": "ATA", "mint": CA,
                   "rawTokenAmount": {"tokenAmount": "-5000000000000", "decimals": 6}}]}]}
    tx.update(over)
    return tx


class Writer(unittest.TestCase):
    def test_sale_keeps_the_sol_from_account_data(self):
        self.assertEqual(chainwatch.parse([hook_sell()]), [("SIG_PUMP", W, CA, "sell", NOW - 600, 0.7346)])

    def test_writer_and_backfill_give_the_same_number(self):
        self.assertAlmostEqual(chainwatch.net_sol(hook_sell(), W), solfill.sol_change(PUMP_SELL, W), places=9)

    def test_wsol_in_account_data(self):
        tx = hook_sell(accountData=[
            {"account": W, "nativeBalanceChange": -5000, "tokenBalanceChanges": []},
            {"account": "WSOL_ATA", "nativeBalanceChange": 1_212_345_678, "tokenBalanceChanges": [
                {"userAccount": W, "tokenAccount": "WSOL_ATA", "mint": WSOL,
                 "rawTokenAmount": {"tokenAmount": "1212345678", "decimals": 9}}]}])
        self.assertEqual(chainwatch.parse([tx])[0][5], 1.2123)

    def test_without_account_data_the_transfers_to_the_wallet(self):
        wsol = hook_sell(accountData=None, tokenTransfers=hook_sell()["tokenTransfers"] + [
            {"fromUserAccount": "POOL", "toUserAccount": W, "tokenAmount": 0.8123, "mint": WSOL}])
        self.assertEqual(chainwatch.parse([wsol])[0][5], 0.8123)
        native = hook_sell(accountData=None, nativeTransfers=[
            {"fromUserAccount": "CURVE", "toUserAccount": W, "amount": 456_700_000},
            {"fromUserAccount": W, "toUserAccount": "JitoTip", "amount": 100_000}])
        self.assertEqual(chainwatch.parse([native])[0][5], 0.4567)

    def test_payload_without_sol_keeps_none(self):
        self.assertIsNone(chainwatch.parse([hook_sell(accountData=None)])[0][5])       # only a tip went out
        lost = hook_sell(accountData=[{"account": W, "nativeBalanceChange": -5000, "tokenBalanceChanges": []}])
        self.assertIsNone(chainwatch.parse([lost])[0][5])                             # sold for a stable, say

    def test_token_for_token_sale_keeps_none_and_buys_are_unchanged(self):
        t2t = hook_sell(tokenTransfers=hook_sell()["tokenTransfers"] + [
            {"fromUserAccount": "POOL", "toUserAccount": W, "tokenAmount": 9.0, "mint": CB}])
        rows = {r[3]: r for r in chainwatch.parse([t2t])}
        self.assertIsNone(rows["sell"][5])
        buy = {"feePayer": W, "signature": "S1", "timestamp": 100, "tokenTransfers": [
            {"mint": WSOL, "fromUserAccount": W, "toUserAccount": "P", "tokenAmount": 1.5},
            {"mint": CA, "fromUserAccount": "P", "toUserAccount": W, "tokenAmount": 1e6}],
            "accountData": [{"account": W, "nativeBalanceChange": -1_500_005_000}]}
        self.assertEqual(chainwatch.parse([buy]), [("S1", W, CA, "buy", 100, 1.5)])

    def test_an_odd_field_keeps_the_row_without_an_amount(self):
        odd = hook_sell(accountData=[{"account": W, "nativeBalanceChange": "n/a"}])
        self.assertEqual(chainwatch.parse([odd]), [("SIG_PUMP", W, CA, "sell", NOW - 600, None)])

    def test_two_tokens_sold_in_one_transaction_split_the_sol(self):
        tx = hook_sell(tokenTransfers=hook_sell()["tokenTransfers"] + [
            {"fromUserAccount": W, "toUserAccount": "POOL", "tokenAmount": 3.0, "mint": CB}])
        self.assertEqual([r[5] for r in chainwatch.parse([tx])], [0.3673, 0.3673])

    def test_ingest_writes_the_sale_amount(self):
        db = Db()
        from league import copy
        with mock.patch.object(copy, "wake"):
            self.assertEqual(chainwatch.ingest([hook_sell()], db.path), 1)
        self.assertEqual(db.sol("SIG_PUMP"), 0.7346)
        rpc = FakeRpc({"SIG_PUMP": PUMP_SELL})
        solfill.run(db.path, fetch=rpc, now=NOW, log=quiet, force=True)
        self.assertEqual(rpc.calls, [])   # nothing left for the backfill to pay for


class Scheduling(unittest.TestCase):
    def test_start_sh_runs_it_in_the_night_window(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            sh = f.read()
        line = next(ln for ln in sh.splitlines() if "wallets.solfill" in ln and not ln.lstrip().startswith("#"))
        self.assertIn("python3 -m ops.heavy --night -m wallets.solfill", line)
        self.assertRegex(line, r"sleep \d+; done \) &$")
        subprocess.run(["bash", "-n", os.path.join(ROOT, "start.sh")], check=True)
        self.assertEqual(cpuguard.classify(["python3", "-m", "wallets.solfill"])[:2], ("solfill", cpuguard.JOBS))
        self.assertEqual(cpuguard.classify(["python3", "-m", "ops.heavy", "--night", "-m", "wallets.solfill"])[0], "heavy")

    def test_night_window_is_the_claude_md_one(self):
        if not os.environ.get("HEAVY_NIGHT"):   # CLAUDE.md: heavy jobs 01-06 (Zagreb), the default of ops/heavy
            self.assertEqual(heavy.night_hours(), (1, 6))
            self.assertTrue(re.fullmatch(r"0?1-0?6", heavy.NIGHT))
        self.assertEqual(solfill._night_key(NOW), "2026-11-11")
        self.assertEqual(solfill._night_key(NOW - 2 * 3600), "2026-11-11")   # 23:30 UTC on 10.11. = 00:30 in Zagreb
        self.assertEqual(solfill._night_key(NOW - 3 * 3600), "2026-11-10")   # 23:30 in Zagreb: the evening before


if __name__ == "__main__":
    unittest.main()
