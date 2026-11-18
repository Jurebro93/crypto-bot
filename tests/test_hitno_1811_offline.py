"""Urgent fixes from the audit of 18.11. (real money): nobody registers or logs in as one of the tool's own accounts
(the real-money mirror account above all), and a Jupiter order that needs a second signer is signed in our slot instead
of raising out of the whole real-money pass. No network."""
import base64
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy as _copy  # noqa: E402
from league import members, store  # noqa: E402
from trade import executor, jupiter, settings, wallet  # noqa: E402

_WAKE = mock.patch.object(_copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))
PW = "tajna12tajna"


def setUpModule():
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


class BotNames(unittest.TestCase):
    def setUp(self):
        self._db = store.DB
        store.DB = os.path.join(tempfile.mkdtemp(), "league.db")
        os.environ.pop("UI_ADMINS", None)

    def tearDown(self):
        store.DB = self._db

    def test_the_tools_accounts_cannot_be_registered(self):
        con = members.connect()
        tok = members.standing(con, "Jure")
        for name in (settings.LEAGUE_USER, "Pravi-Trade", settings.PAPER_USER, "autopilot-istrazivac",
                     "AUTOPILOT-NAUCENO", "autopilot-novi", "pravi-nesto"):
            with self.assertRaises(ValueError, msg=name):
                members.register(con, tok, name, PW, PW)
            self.assertTrue(members.reserved(name), name)
        self.assertEqual(members.register(con, tok, "Marko", PW, PW), "Marko")       # a player's name still works
        self.assertFalse(members.reserved("Marko"))
        self.assertFalse(members.reserved("pravila"))                                # only the prefix with the dash
        con.close()

    def test_a_row_registered_before_the_fix_cannot_log_in(self):
        con = members.connect()
        tok = members.standing(con, "Jure")
        with mock.patch.object(members, "reserved", return_value=False):             # as the code was before 18.11.
            self.assertEqual(members.register(con, tok, settings.LEAGUE_USER, PW, PW), settings.LEAGUE_USER)
            self.assertEqual(members.verify(settings.LEAGUE_USER, PW), settings.LEAGUE_USER)
        con.close()
        self.assertIsNone(members.verify(settings.LEAGUE_USER, PW))
        self.assertIsNone(members.verify("PRAVI-TRADE", PW))

    def test_no_session_as_the_real_money_account(self):
        import run_ui
        con = members.connect()
        tok = members.standing(con, "Jure")
        with mock.patch.object(members, "reserved", return_value=False):
            members.register(con, tok, settings.LEAGUE_USER, PW, PW)
            members.register(con, tok, "Marko", PW, PW)
        con.close()
        with mock.patch("league.profiles.session_ok", return_value=True):
            self.assertEqual(run_ui.cookie_user(run_ui.make_cookie("Marko")), (True, "Marko"))
            self.assertEqual(run_ui.cookie_user(run_ui.make_cookie(settings.LEAGUE_USER)), (False, None))


def _two_signer(payer, signers):
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import MessageV0
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solders.transaction import VersionedTransaction
    prog = Pubkey.from_string("11111111111111111111111111111111")
    metas = [AccountMeta(k.pubkey(), True, True) for k in signers]
    msg = MessageV0.try_compile(payer.pubkey(), [Instruction(prog, b"\x00", metas)], [], Hash.default())
    n = msg.header.num_required_signatures
    return base64.b64encode(bytes(VersionedTransaction.populate(msg, [Signature.default()] * n))).decode(), n


class Signing(unittest.TestCase):
    def setUp(self):
        try:
            from solders.keypair import Keypair
        except ImportError:
            self.skipTest("solders nije instaliran")
        self.taker, self.maker = Keypair(), Keypair()

    def _check(self, b64, n):
        from solders.message import to_bytes_versioned
        from solders.signature import Signature
        from solders.transaction import VersionedTransaction
        out = VersionedTransaction.from_bytes(base64.b64decode(wallet.sign(b64, self.taker)))
        keys = list(out.message.account_keys)[:n]
        i = keys.index(self.taker.pubkey())
        self.assertTrue(out.signatures[i].verify(self.taker.pubkey(), to_bytes_versioned(out.message)))
        return [s == Signature.default() for j, s in enumerate(out.signatures) if j != i]

    def test_one_signer_as_before(self):
        b64, n = _two_signer(self.taker, [self.taker])
        self.assertEqual(n, 1)
        self.assertEqual(self._check(b64, n), [])

    def test_a_second_signer_no_longer_raises_and_its_slot_is_left_alone(self):
        for payer, signers in ((self.taker, [self.taker, self.maker]),      # a maker co-signs, we pay the fee
                               (self.maker, [self.maker, self.taker])):     # somebody else pays the fee
            b64, n = _two_signer(payer, signers)
            self.assertEqual(n, 2)
            self.assertEqual(self._check(b64, n), [True])                   # the other slot is as it was received

    def test_the_other_partys_signature_is_kept(self):
        from solders.message import to_bytes_versioned
        from solders.transaction import VersionedTransaction
        b64, n = _two_signer(self.maker, [self.maker, self.taker])
        tx = VersionedTransaction.from_bytes(base64.b64decode(b64))
        sigs = list(tx.signatures)
        sigs[0] = self.maker.sign_message(to_bytes_versioned(tx.message))    # the maker signed first
        b64 = base64.b64encode(bytes(VersionedTransaction.populate(tx.message, sigs))).decode()
        out = VersionedTransaction.from_bytes(base64.b64decode(wallet.sign(b64, self.taker)))
        self.assertEqual(out.signatures[0], sigs[0])
        self.assertTrue(all(out.verify_with_results()))                      # both signatures valid: ready to send

    def test_an_order_we_are_not_a_signer_of_is_refused_in_words(self):
        from solders.keypair import Keypair
        other = Keypair()
        b64, _n = _two_signer(self.maker, [self.maker, other])
        with self.assertRaises(RuntimeError) as e:
            wallet.sign(b64, self.taker)
        self.assertIn("nije među potpisnicima", str(e.exception))


class SwapNeverRaisesOnSigning(unittest.TestCase):
    ORDER = {"inAmount": "100000000", "outAmount": "5000", "transaction": "AAAA", "requestId": "r1"}

    def test_a_signing_error_is_a_failed_try_with_a_retry_and_nothing_is_sent(self):
        with mock.patch.object(jupiter, "order", return_value=dict(self.ORDER)), \
                mock.patch.object(wallet, "address", return_value="WALLET"), \
                mock.patch.object(wallet, "token_raw_balance", return_value=0), \
                mock.patch.object(wallet, "sign", side_effect=RuntimeError("not enough signers")), \
                mock.patch.object(jupiter, "execute", side_effect=AssertionError("ništa se ne šalje")):
            res = executor._jup("v2", jupiter.SOL, "MINT", 100_000_000, True, None)
        self.assertEqual(res["status"], "failed")
        self.assertTrue(res["retry"])                        # the next route may go out in the same pass
        self.assertIn("nalog nije potpisan", res["error"])
        self.assertIn("not enough signers", res["error"])
        self.assertEqual(res["amount_in"], 100_000_000)

    def test_a_signed_order_goes_out_as_before(self):
        sent = []
        with mock.patch.object(jupiter, "order", return_value=dict(self.ORDER)), \
                mock.patch.object(wallet, "address", return_value="WALLET"), \
                mock.patch.object(wallet, "token_raw_balance", return_value=0), \
                mock.patch.object(wallet, "sign", return_value="SIGNED"), \
                mock.patch.object(jupiter, "execute",
                                  side_effect=lambda tx, rid, route=None: sent.append((tx, rid)) or
                                  {"status": "Success", "signature": "SIG", "outputAmountResult": "5000"}):
            res = executor._jup("v2", jupiter.SOL, "MINT", 100_000_000, True, None)
        self.assertEqual(sent, [("SIGNED", "r1")])
        self.assertEqual(res["status"], "ok")


class Token2022Deposit(unittest.TestCase):
    """The deposit of a Token-2022 token account comes back too (the program id in the list was a typo)."""

    def test_the_program_ids_are_the_real_ones(self):
        import re
        self.assertEqual(wallet.TOKEN_PROGRAMS, {"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                                 "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"})
        # the same id the rest of the tool uses for Token-2022: no second spelling anywhere in the code
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        seen = set()
        for d, _dirs, files in os.walk(root):
            if "/tests" in d or "/." in d or "__pycache__" in d:
                continue
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(d, f), encoding="utf-8") as fh:
                        seen |= set(re.findall(r"Tokenz[1-9A-HJ-NP-Za-km-z]{30,44}", fh.read()))
        self.assertEqual(seen, {wallet.TOKEN_2022_PROGRAM})

    def test_an_empty_token_2022_account_is_closed(self):
        try:
            from solders.hash import Hash
            from solders.keypair import Keypair
            from solders.transaction import VersionedTransaction
        except ImportError:
            self.skipTest("solders nije instaliran")
        kp, acc = Keypair(), str(Keypair().pubkey())
        sent = []

        def rpc(method, params):
            if method == "getBalance":
                return {"value": 2_074_080}
            if method == "getLatestBlockhash":
                return {"value": {"blockhash": str(Hash.default())}}
            raise AssertionError(method)
        for prog, expect in ((wallet.TOKEN_2022_PROGRAM, 2_074_080), (wallet.TOKEN_PROGRAM, 2_074_080),
                             ("NekiDrugiProgram1111111111111111111111111111", 0)):
            sent.clear()
            info = {}
            with mock.patch.object(wallet, "token_accounts", return_value=[(acc, 0, 6, prog)]), \
                    mock.patch.object(wallet, "rpc", side_effect=rpc), \
                    mock.patch.object(wallet, "send", side_effect=lambda tx: sent.append(tx) or "SIG"), \
                    mock.patch.object(wallet, "confirmed", return_value=True):
                self.assertEqual(wallet.close_empty(kp, "MINT", wait_s=1, info=info), expect, prog)
            self.assertEqual(len(sent), 1 if expect else 0)
            if expect:
                tx = VersionedTransaction.from_bytes(base64.b64decode(sent[0]))
                ix = tx.message.instructions[0]
                self.assertEqual(str(tx.message.account_keys[ix.program_id_index]), prog)   # sent to the account's program
                self.assertEqual(bytes(ix.data), bytes([9]))                                 # CloseAccount
                self.assertEqual(info, {"lamports": expect, "sig": "SIG"})

    def test_an_account_with_tokens_is_never_closed(self):
        with mock.patch.object(wallet, "token_accounts", return_value=[("ACC", 5, 6, wallet.TOKEN_2022_PROGRAM)]), \
                mock.patch.object(wallet, "send", side_effect=AssertionError("ništa se ne šalje")):
            try:
                from solders.keypair import Keypair
            except ImportError:
                self.skipTest("solders nije instaliran")
            self.assertEqual(wallet.close_empty(Keypair(), "MINT"), 0)


class RentSweep(unittest.TestCase):
    """The token-account deposit that did not come back after a sale is asked for again by the trade loop."""
    NOW = 1_800_000_000

    def setUp(self):
        self.con = executor.connect(os.path.join(tempfile.mkdtemp(), "trade.db"))
        executor._RENT["ts"] = 0
        self.closed = []
        p = mock.patch.object(wallet, "_keypair", return_value="KP")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.con.close)

    def pos(self, token, status="closed", closed_ago=120, mode="live", sol_in=0.1):
        cur = self.con.execute(
            "INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, sol_back, "
            "closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (token, token[:4], self.NOW - 3600, mode, status, "veliki: dnevna zona", sol_in, 1000, 0, 0.097,
             self.NOW - closed_ago if status == "closed" else None, 0.003))
        self.con.commit()
        return cur.lastrowid

    def sweep(self, now=None, got=2_039_280, accounts="empty", sent=0):
        """accounts: "empty" (one account, no tokens), "none" (the account is gone), or a raw amount left on it."""
        def close_empty(kp, mint, wait_s=30, info=None):
            self.closed.append((mint, wait_s))
            if sent and info is not None:
                info.update(lamports=sent, sig="SIG")
            return got
        accs = [] if accounts == "none" else [("ACC", 0 if accounts == "empty" else accounts, 6, "PROG")]
        with mock.patch.object(wallet, "close_empty", side_effect=close_empty), \
                mock.patch.object(wallet, "token_accounts", return_value=accs), \
                mock.patch.object(wallet, "address", return_value="WALLET"), mock.patch("builtins.print") as pr:
            out = executor.rent_sweep(self.con, now or self.NOW)
        self.said = " | ".join(str(c[0][0]) for c in pr.call_args_list)
        return out

    def test_the_reason_is_said_and_a_hopeless_case_is_not_tried_again(self):
        self.pos("GONETOKN")
        self.assertEqual(self.sweep(accounts="none"), 0)
        self.assertIn("više ne postoji", self.said)                  # closed earlier: the deposit did come back
        self.assertEqual(self.closed, [])
        self.assertIsNone(self.sweep(self.NOW + 61, accounts="none"))
        self.pos("DUSTTOKN")
        self.assertEqual(self.sweep(self.NOW + 122, accounts=37), 0)
        self.assertIn("ostatak od 37 jedinica", self.said)           # not empty: the deposit stays locked
        self.assertIsNone(self.sweep(self.NOW + 183, accounts=37))
        self.assertEqual(self.closed, [])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE side='rent'").fetchone()[0], 0)

    def test_a_close_confirmed_after_the_wait_is_booked_on_the_next_pass(self):
        pid = self.pos("LATETOKN")
        self.assertEqual(self.sweep(got=0, sent=2_039_280), 0)       # sent, not confirmed in the short wait
        self.assertIn("zatvaranje je poslano", self.said)
        self.assertEqual(self.sweep(self.NOW + 61, accounts="none"), 2_039_280)   # the account is gone: it landed
        self.assertIn("potvrđeno naknadno", self.said)
        self.assertAlmostEqual(self.fees(pid), 0.003 - 0.00203928, places=8)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE side='rent'").fetchone()[0], 1)
        self.assertIsNone(self.sweep(self.NOW + 122, accounts="none"))

    def fees(self, pid):
        return self.con.execute("SELECT fees_sol FROM positions WHERE id=?", (pid,)).fetchone()[0]

    def test_the_deposit_of_a_closed_position_comes_back_and_is_booked_once(self):
        pid = self.pos("TOKENAAA")
        self.assertEqual(self.sweep(), 2_039_280)
        self.assertEqual(self.closed, [("TOKENAAA", executor.RENT_SWEEP_WAIT_S)])
        self.assertAlmostEqual(self.fees(pid), 0.003 - 0.00203928, places=8)
        row = self.con.execute("SELECT side, mode, status, amount_out, fee_lamports FROM orders WHERE position_id=?",
                               (pid,)).fetchone()
        self.assertEqual(row, ("rent", "live", "ok", 2_039_280, -2_039_280))
        self.assertIsNone(self.sweep(self.NOW + 30))                 # at most once a minute
        self.assertIsNone(self.sweep(self.NOW + 120))                # booked: nothing left to ask for
        self.assertEqual(len(self.closed), 1)

    def test_not_yet_is_tried_three_times_then_left(self):
        self.pos("TOKENBBB")
        for k in range(5):
            self.sweep(self.NOW + 61 * k, got=0)
        self.assertEqual(len(self.closed), executor.RENT_SWEEP_TRIES)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE side='rent'").fetchone()[0], 0)

    def test_what_it_leaves_alone(self):
        self.pos("OPENTOKN", status="closed")
        self.pos("OPENTOKN", status="open")                          # a lot of the token is open: its account is in use
        self.pos("FRESHTOK", closed_ago=5)                           # closed seconds ago: the in-line refund's turn
        self.pos("OLDTOKEN", closed_ago=8 * 86400)                   # older than the window
        self.pos("DRYTOKEN", mode="dry")                             # no real account
        self.assertIsNone(self.sweep())
        self.assertEqual(self.closed, [])

    def test_one_account_a_token_and_an_error_never_leaves_the_step(self):
        self.pos("TWICETOK", closed_ago=4000)
        new = self.pos("TWICETOK", closed_ago=200)
        self.assertEqual(self.sweep(), 2_039_280)
        self.assertEqual(self.con.execute("SELECT position_id FROM orders WHERE side='rent'").fetchone()[0], new)
        self.assertIsNone(self.sweep(self.NOW + 61))                 # the older position of the same token: refunded since
        self.pos("ERRTOKEN")
        with mock.patch.object(wallet, "token_accounts", side_effect=RuntimeError("RPC")), \
                mock.patch.object(wallet, "address", return_value="WALLET"), mock.patch("builtins.print"):
            self.assertEqual(executor.rent_sweep(self.con, self.NOW + 200), 0)


if __name__ == "__main__":
    unittest.main()
