"""Usklađenje novčanika i knjige tradeova (trade/uskladi.py), 16.11. (vlasnik: "krenuo sam sa jednom Solanom, piše da
je 1.37 trenutno, a čini mi se da se brojevi ne poklapaju").

A synthetic ledger in a temp trade.db, no network: one deposit, a token bought three times (three lots), two losers,
one open position, one buy that failed on the chain. Checked: the parts add up to the wallet's PnL; a difference is
said with its size; the result per token sums the lots; the share of the best token; the rent of empty token accounts;
the result of a span is net of deposits and equals the total PnL when the span covers the whole history; the thinned
line starts at the money put in; the opening deposit can be booked as verified on the chain.

    python3 -m unittest tests.test_uskladi_offline -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade import equity, executor, settings, uskladi, wallet  # noqa: E402

NOW = 1_800_000_000
L = equity.LAMPORTS
RENT = int(0.002 * L)
FEE = int(0.0001 * L)


def _no_network(*a, **k):
    raise AssertionError("test je posegnuo za mrežom")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "trade.db")
        self._saved = (settings.DB, equity._pairs, equity._usd_eur_fetch, equity._sol_balance, equity._usdc_balance,
                       wallet.token_decimals)
        settings.DB = self.path
        equity._pairs = equity._usd_eur_fetch = equity._sol_balance = equity._usdc_balance = _no_network
        wallet.token_decimals = _no_network
        equity._CACHE.clear()
        self.con = executor.connect(self.path)
        self.sol = 0.0        # what the ledger says the wallet holds
        self.t = NOW

    def tearDown(self):
        (settings.DB, equity._pairs, equity._usd_eur_fetch, equity._sol_balance, equity._usdc_balance,
         wallet.token_decimals) = self._saved
        equity._CACHE.clear()
        self.con.close()
        self.tmp.cleanup()

    def snap(self, sol, prices=None, dt=600):
        self.t += dt
        out = equity.snapshot(self.con, now=self.t, force=True, addr="ADDR", balance=lambda a: sol, usdc=lambda a: 0.0,
                              market=lambda mints: (prices or {}, 150.0),
                              rates=lambda t: {"sol_usd": 150.0, "usd_eur": 0.9}, decimals=lambda m: 6)
        self.assertIsNotNone(out)
        return out

    def order(self, pid, token, side, a_in=0, a_out=0, fee=FEE, status="ok", sig="sig", error=None):
        self.t += 1
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, amount_in, amount_out, status, "
                         "fee_lamports, signature, error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (self.t, pid, token, side, "live", a_in, a_out, status, fee, sig, error))
        self.con.commit()
        self.sol += equity._delta(side, status, a_in, a_out, fee, sig)

    def lot(self, token, sol_in=0.1, back=None, rent=True, reclaim=False, status=None, qty=1_000_000_000):
        """One real lot through the ledger: the buy (fee, and the token account's deposit when rent), the sale when
        `back` is given (fee), the deposit back when reclaim. Returns the position id."""
        fee_buy = FEE + (RENT if rent else 0)
        fees = fee_buy / L
        self.t += 1
        cur = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                               "qty_left, sol_back, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,0,?)",
                               (token, token, self.t, "live", "open", "test", sol_in, qty, qty, fees))
        pid = cur.lastrowid
        self.order(pid, token, "buy", a_in=int(sol_in * L), a_out=qty, fee=fee_buy)
        if back is not None:
            self.order(pid, token, "sell", a_in=qty, a_out=int(back * L))
            fees += FEE / L
            if reclaim:
                self.order(pid, token, "rent", a_out=RENT, fee=-RENT)
                fees -= RENT / L
            self.con.execute("UPDATE positions SET status='closed', closed_ts=?, qty_left=0, sol_back=?, fees_sol=? "
                             "WHERE id=?", (self.t, back, fees, pid))
        if status:
            self.con.execute("UPDATE positions SET status=? WHERE id=?", (status, pid))
        self.con.commit()
        return pid

    def ledger(self):
        """Deposit 1 SOL, then: HOPE three lots (+), RUG and DOG one each (-), OPEN still held, one failed buy."""
        self.sol = 1.0
        self.snap(1.0)                                                   # the opening deposit
        self.lot("HOPE", back=0.30)
        self.lot("HOPE", back=0.25, rent=False)
        self.lot("HOPE", back=0.20, rent=False, reclaim=True)            # the last lot closes the token account
        self.lot("RUG", back=0.01)
        self.lot("DOG", back=0.06)
        self.lot("OPEN")
        self.t += 1
        cur = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                               "qty_left, sol_back, fees_sol) VALUES ('BAD','BAD',?,'live','failed','greška',0,0,0,0,?)",
                               (self.t, 5 * FEE / L))
        self.order(cur.lastrowid, "BAD", "buy", fee=5 * FEE, status="failed")
        self.con.commit()


class Zbroj(Base):
    def test_parts_add_up_to_the_wallets_pnl(self):
        self.ledger()
        self.snap(self.sol, prices={"OPEN": (0.00012, None)})            # 1000 tokens x 0.00012 SOL = 0.12 SOL
        r = uskladi.report(self.con, now=self.t)
        self.assertTrue(r["have"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["text"], "Brojevi se slažu ✓")
        w = r["wallet"]
        self.assertAlmostEqual(w["value_sol"], w["free_sol"] + w["pos_sol"])
        self.assertAlmostEqual(w["pnl_sol"], w["value_sol"] - 1.0)
        self.assertAlmostEqual(w["deposits_sol"], 1.0)
        self.assertEqual((r["closed"]["n"], r["closed"]["wins"], r["open"]["n"]), (5, 3, 1))
        # HOPE 0.1978 + 0.1498 + 0.1018 = 0.4494, RUG -0.0922, DOG -0.0422
        self.assertAlmostEqual(r["closed"]["pnl_sol"], 0.4494 - 0.0922 - 0.0422, places=6)
        self.assertAlmostEqual(r["open"]["pnl_sol"], 0.12 - 0.1 - 0.0021, places=6)
        self.assertAlmostEqual(r["failed_sol"], -0.0005, places=6)
        self.assertAlmostEqual(r["diff_sol"], 0.0, places=6)
        *parts, total = r["lines"]
        self.assertEqual(total[0], "Ukupni PnL novčanika (vrijednost − uplate)")
        self.assertAlmostEqual(sum(v for _, v in parts), total[1], places=6)
        self.assertAlmostEqual(total[1], w["pnl_sol"], places=6)
        self.assertEqual([lab for lab, _ in parts], ["Zatvorene pozicije (5)", "Otvorene pozicije (1), po cijeni sada",
                                                     "Naknade neuspjelih pokušaja"])
        self.assertAlmostEqual(r["ledger"]["gap_sol"], 0.0, places=6)    # orders and positions tell the same story

    def test_a_difference_is_said_with_its_size(self):
        """The wallet holds more than the ledger explains (fees booked from estimates): under FLOW_MIN_SOL a snapshot
        it is no deposit, so it shows as PnL the positions do not explain."""
        self.ledger()
        for extra in (0.015, 0.030, 0.045):
            self.snap(self.sol + extra, prices={"OPEN": (0.00012, None)})
        r = uskladi.report(self.con, now=self.t)
        self.assertFalse(r["ok"])
        self.assertTrue(r["wallet"]["sum_ok"])                           # the wallet itself still adds up
        self.assertAlmostEqual(r["wallet"]["deposits_sol"], 1.0)         # nothing was booked as a deposit
        self.assertAlmostEqual(r["diff_sol"], 0.045, places=6)
        self.assertEqual(r["text"], "Novčanik se slaže ✓ · knjiga tradeova je niža za 0,045 SOL")
        labels = [lab for lab, _ in r["lines"]]
        self.assertIn("Razlika knjige i novčanika", labels)
        self.assertAlmostEqual(sum(v for _, v in r["lines"][:-1]), r["lines"][-1][1], places=6)
        self.assertTrue(any("procjena iz Jupiterove ponude" in n for n in r["notes"]))

    def test_no_measured_value_is_said_not_raised(self):
        r = uskladi.safe_report(self.con, now=NOW)
        self.assertFalse(r["have"])
        self.assertIn("još nije izmjerena", r["why"])
        self.assertIn("još nije izmjerena", uskladi.text_report(r))


class PoTokenu(Base):
    def test_lots_of_one_token_are_summed_and_the_best_tokens_share_is_said(self):
        self.ledger()
        self.snap(self.sol, prices={"OPEN": (0.00012, None)})
        r = uskladi.report(self.con, now=self.t)
        bt = r["by_token"]
        self.assertEqual((bt["n"], bt["plus"], bt["rest_n"]), (3, 1, 2))  # HOPE, RUG, DOG; OPEN is not closed
        self.assertEqual(bt["best"]["symbol"], "HOPE")
        self.assertAlmostEqual(bt["best"]["pnl_sol"], 0.4494, places=6)
        self.assertEqual((bt["best"]["lots"], bt["best"]["buys"], bt["best"]["sells"]), (3, 3, 3))
        self.assertAlmostEqual(bt["rest_sol"], -0.0922 - 0.0422, places=6)
        self.assertEqual(bt["worst"]["symbol"], "RUG")
        self.assertAlmostEqual(bt["sum_sol"], r["closed"]["pnl_sol"], places=6)
        # per trade (one lot) the best is one HOPE lot, far below the token's sum
        self.assertEqual(r["closed"]["best"]["symbol"], "HOPE")
        self.assertAlmostEqual(r["closed"]["best"]["pnl"], 0.1978, places=6)
        self.assertEqual(r["closed"]["worst"]["symbol"], "RUG")
        txt = uskladi.text_report(r)
        self.assertIn("najbolji HOPE +0.4494 (3 kupnji, 3 prodaja); svi ostali zajedno -0.1344", txt)

    def test_a_token_with_a_lot_still_open_is_not_a_closed_token(self):
        self.sol = 1.0
        self.snap(1.0)
        self.lot("HOPE", back=0.3)
        self.lot("HOPE", rent=False)                                     # bought again, still held
        self.snap(self.sol, prices={"HOPE": (0.0001, None)})
        r = uskladi.report(self.con, now=self.t)
        self.assertEqual(r["by_token"]["n"], 0)
        self.assertIsNone(r["by_token"]["best"])
        self.assertEqual(r["tokens"][0]["open"], True)
        self.assertEqual(r["rent"]["n"], 0)                              # its account is in use


class Depoziti(Base):
    def test_empty_token_accounts_are_counted_from_the_ledger(self):
        self.ledger()
        self.snap(self.sol, prices={"OPEN": (0.00012, None)})
        r = uskladi.report(self.con, now=self.t)
        # RUG and DOG were sold and never closed; HOPE's account was closed after its last lot; OPEN is in use
        self.assertEqual(r["rent"], {"n": 2, "sol": round(2 * uskladi.RENT_SOL, 6)})
        self.assertIn("Prazni token računi (procjena iz knjige): 2", uskladi.text_report(r))

    def test_bought_again_after_the_account_was_closed_counts_again(self):
        self.sol = 1.0
        self.snap(1.0)
        self.lot("HOPE", back=0.2, reclaim=True)
        self.assertEqual(uskladi.report(self.con, now=self.t)["rent"]["n"], 0)
        self.lot("HOPE", back=0.2)                                       # a new account, sold, not closed
        self.assertEqual(uskladi.report(self.con, now=self.t)["rent"]["n"], 1)

    def test_a_lot_closed_without_a_recorded_sale_is_named(self):
        self.sol = 1.0
        self.snap(1.0)
        pid = self.lot("HOPE")
        self.con.execute("UPDATE positions SET status='closed', closed_ts=?, qty_left=0 WHERE id=?", (self.t, pid))
        self.con.commit()
        self.snap(self.sol + 0.015)                                      # the SOL of the hand sale, under the flow limit
        r = uskladi.report(self.con, now=self.t)
        self.assertTrue(any("bez zabilježene prodaje" in n and "0,100 SOL" in n for n in r["notes"]), r["notes"])


class Razdoblje(Base):
    def test_span_over_the_whole_history_is_the_total_pnl(self):
        self.ledger()
        self.snap(self.sol, prices={"OPEN": (0.00012, None)})
        r = uskladi.report(self.con, now=self.t)
        p = uskladi.period(self.con, 30, now=self.t)
        self.assertTrue(p["whole"])
        self.assertEqual(p["base_sol"], 0.0)
        self.assertAlmostEqual(p["result_sol"], r["wallet"]["pnl_sol"], places=9)

    def test_a_deposit_inside_the_span_is_not_profit(self):
        self.sol = 1.0
        self.snap(1.0)
        self.lot("HOPE", back=0.3)
        self.snap(self.sol)
        self.sol += 2.0                                                  # the owner sends 2 SOL more
        self.snap(self.sol)
        p = uskladi.period(self.con, 30, now=self.t)
        s = equity.summary(self.con, self.t)
        self.assertAlmostEqual(s["net_in_sol"], 3.0)
        self.assertAlmostEqual(p["result_sol"], 0.3 - 0.1 - 0.0022, places=6)
        self.assertAlmostEqual(p["result_sol"], s["pnl_sol"], places=9)

    def test_span_shorter_than_the_history_subtracts_the_pnl_before_it(self):
        self.sol = 1.0
        self.snap(1.0)
        self.lot("HOPE", back=0.3)                                       # +0.1978 long ago
        self.snap(self.sol)
        self.t += 40 * 86400
        self.lot("DOG", back=0.06)                                       # -0.0422 in the last days
        self.snap(self.sol)
        p = uskladi.period(self.con, 30, now=self.t)
        self.assertFalse(p["whole"])
        self.assertAlmostEqual(p["base_sol"], 0.1978, places=6)
        self.assertAlmostEqual(p["result_sol"], -0.0422, places=6)
        self.assertAlmostEqual(uskladi.period(self.con, 90, now=self.t)["result_sol"], 0.1978 - 0.0422, places=6)

    def test_thinned_line_starts_at_the_money_put_in(self):
        """The real wallet 16.11.: the first slice of the thinned line ended 9 minutes and -0,026 SOL after the deposit,
        so "promjena vrijednosti u 30 d" read +0,353 beside a total PnL of +0,327."""
        self.sol = 1.0
        self.snap(1.0, dt=0)
        self.lot("RUG", back=0.01)                                       # the first minutes lose 0.0922
        for _ in range(60):
            self.snap(self.sol, dt=300)
        thin = equity.series(self.con, max_points=10)
        full = equity.series(self.con, max_points=1000)
        self.assertLessEqual(len(thin), 10)
        self.assertEqual(thin[0]["ts"], full[0]["ts"])
        self.assertAlmostEqual(thin[0]["value_sol"], 1.0)
        self.assertAlmostEqual(thin[0]["pnl_sol"], 0.0)
        self.assertAlmostEqual(thin[0]["flow_sol"], 1.0)
        self.assertAlmostEqual(sum(p["flow_sol"] for p in thin), 1.0)   # the deposit is on the line once
        self.assertEqual(thin[-1]["ts"], full[-1]["ts"])
        self.assertAlmostEqual(thin[-1]["value_sol"] - thin[0]["value_sol"], thin[-1]["pnl_sol"], places=9)


class Uplata(Base):
    def test_opening_deposit_booked_as_verified_on_the_chain(self):
        self.sol = 1.045
        self.snap(1.045)
        self.lot("HOPE", back=0.3)
        self.snap(self.sol)
        before = uskladi.report(self.con, now=self.t)["wallet"]
        old, new = uskladi.set_opening(self.con, 1.0435, who="Jure", now=self.t)
        self.assertAlmostEqual(old, 1.045)
        after = uskladi.report(self.con, now=self.t)["wallet"]
        self.assertAlmostEqual(after["deposits_sol"], 1.0435)
        self.assertAlmostEqual(after["pnl_sol"], before["pnl_sol"] + 0.0015, places=9)
        self.assertAlmostEqual(after["value_sol"], before["value_sol"])  # the wallet itself did not change
        fix = settings.raw(self.con)["equity_opening_fix"]
        self.assertAlmostEqual(fix["old"], 1.045)
        self.assertAlmostEqual(fix["new"], 1.0435)
        for bad in ("0", "-1", "abc"):
            with self.assertRaises(ValueError):
                uskladi.set_opening(self.con, bad)


if __name__ == "__main__":
    unittest.main()
