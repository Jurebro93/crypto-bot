"""11.11. (Jure: "živi kandidati alata: za svakog odmah fast_check i procjena EV-a, nikad 'nije izmjeren'"), offline.

Covers: the lag from the source's entry (DOPE: -10 % from the wallet's buy is "jeftinije od njega" while his sale is
not seen, "izlazi" and a PRESKOČI once it is), the market-cap band (4CxjZy at $14M: PRESKOČI "MC $14.0M izvan raspona
(30k–5M)" even with RugCheck down), P from the source's sample or, with n < 10, from its strategy's prior with the label
"procjena, n izvora < 10", the EV with its Wilson 90 % interval, the convergence trigger (kol.db converge -> one
fast_check of the pseudo-source "konvergencija") and the live list's own triggers (callers, the tool's pick), "nije
izmjeren" never rendered in "Što kupiti" (in progress / CHECK_FAILED with the failing check / KUPI with EV, PRESKOČI
left out), KUPI -> a proposals row of strategy "fast", PRESKOČI -> the skip journal with its reason, numbers and the
"propušteno" outcome (+20 % within 60 min), and paper mode: KUPI labels map onto the demo account with the fast exit.

    python3 -m unittest tests.test_zivi_ev_offline -v
"""
import os
import re
import sqlite3
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fast import checks, decide, estimate, live as flive, outcomes, paper, sources, store, worker  # noqa: E402
from tests.test_fast_offline import (Env, PU, LU, REPLAY_TS, SOL_USD, TOK, W_HODL, addr, good_net,  # noqa: E402
                                     rc_report)
from trade import edge  # noqa: E402

DOPE_ENTRY = 1e-7 * SOL_USD          # the HODL replay's own swap: 1.5 SOL for 15M tokens at $150


def esc(s):
    from ui import pravitrade
    return pravitrade.esc(s)


# ---------- the lag (DOPE) -------------------------------------------------------------------------------------------

class Lag(Env):
    def test_ten_percent_under_his_entry_without_his_sale_is_a_cheaper_entry(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        self.run_worker(good_net(price=DOPE_ENTRY * 0.9), self.clock(REPLAY_TS + 1.1))
        r = self.row()
        pv = r["checks"]["res"]["price"]["values"]
        self.assertAlmostEqual(pv["from_entry_pct"], -10.0, places=1)
        self.assertEqual((pv["lag_txt"], pv["src_sold"]), ("jeftinije od njega", None))
        self.assertEqual(r["checks"]["res"]["price"]["status"], "ok")
        self.assertIn("−10,0 % od kupnje novčanika (jeftinije od njega)".replace("−", "-"), r["checks"]["res"]["price"]["text"])
        self.assertEqual(r["checks"]["lag"], {"pct": -10.0, "txt": "jeftinije od njega", "sold": False})
        v = flive.lookup([TOK], REPLAY_TS + 2, self.fp)[TOK]
        self.assertEqual((v["state"], v["lag_txt"], v["lag_pct"]), ("done", "jeftinije od njega", -10.0))
        self.assertIn("−10,0 % od ulaza: jeftinije od njega", flive.short(v))

    def test_his_sale_after_the_buy_is_izlazi_and_a_preskoci(self):
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        con = sqlite3.connect(self.hp)
        con.execute("INSERT INTO chain_trades VALUES (?,?,?,?,?,?)", ("sig-sell", W_HODL, TOK, "sell", REPLAY_TS + 30, 1.3))
        con.commit()
        con.close()
        self.run_worker(good_net(price=DOPE_ENTRY * 0.9), self.clock(REPLAY_TS + 31))
        r = self.row()
        self.assertEqual((r["decision"], r["checks"]["key"]), ("SKIP", "price"))
        self.assertTrue(r["reason"].startswith("cijena: izvor izlazi (prodaja viđena 30 s nakon signala"), r["reason"])
        self.assertIn("cijena -10,0 % od kupnje novčanika", r["reason"])
        pv = r["checks"]["res"]["price"]["values"]
        self.assertEqual(pv["lag_txt"], "izlazi")
        v = flive.lookup([TOK], REPLAY_TS + 32, self.fp)[TOK]
        self.assertEqual((v["label"], v["lag_txt"]), ("PRESKOČI", "izlazi"))

    def test_the_lag_of_a_call_is_from_its_market_cap(self):
        sig = {"id": 1, "token": TOK, "source_id": "caller1", "kind": "influencer", "sig_ts": REPLAY_TS,
               "entry_mcap": 250_000.0}
        res, _d, _q = checks.run_all(sig, good_net(mcap=300_000), REPLAY_TS + 2, 0.1, checks.Cache())
        pv = res["price"]["values"]
        self.assertAlmostEqual(pv["from_entry_pct"], 20.0, places=1)
        self.assertEqual((pv["lag_txt"], pv["entry_src"]), ("skuplje od poziva", "MC u trenutku signala"))
        self.assertIn("od poziva", res["price"]["text"])


# ---------- the market-cap band (4CxjZy) -----------------------------------------------------------------------------

class Band(Env):
    def test_14m_is_preskoci_out_of_band_even_with_rugcheck_down(self):
        self.assertEqual(checks.band_text(), "30k–5M")
        self.assertEqual((checks.CFG["mcap_min"], checks.CFG["mcap_max"]), (30_000, 5_000_000))
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        net = good_net(mcap=14_000_000, liq=900_000)
        net.rc[TOK] = RuntimeError("RugCheck HTTP 429")                   # an API error elsewhere does not matter
        self.run_worker(net, self.clock(REPLAY_TS + 1.2))
        r = self.row()
        self.assertEqual((r["decision"], r["status"]), ("SKIP", "done"))   # decided, not a CHECK_FAILED retry
        self.assertTrue(r["reason"].startswith("cijena: MC $14.0M izvan raspona (30k–5M)"), r["reason"])
        self.assertEqual(r["checks"]["res"]["rug"]["status"], "error")
        self.assertEqual(flive.lookup([TOK], REPLAY_TS + 3, self.fp)[TOK]["label"], "PRESKOČI")

    def test_under_30k_is_out_of_band_too(self):
        c = {k: {"status": "ok", "text": k, "values": {}} for k in decide.ORDER}
        c["price"] = {"status": "fail", "text": "cijena: MC $25k izvan raspona (30k–5M); ispod 30k se ne analizira",
                      "values": {"band": "out", "cost_pct": 2.1}}
        c["rug"] = {"status": "error", "text": "rug: RugCheck timeout", "values": {}}
        d = decide.decide(c, {"kind": "wallet_follow", "n": 0})
        self.assertEqual((d["decision"], d["label"], d["key"]), ("SKIP", "PRESKOČI", "price"))
        self.assertIn("ispod 30k", d["reason"])


# ---------- P, its prior and the interval ------------------------------------------------------------------------------

class Prior(unittest.TestCase):
    def test_n_under_10_takes_the_strategy_prior_with_its_label(self):
        pri = estimate.priors({"wallet_follow": (5, 10)}, {"rang_wallet": (130, 200), "bench": (60, 150)})
        w = pri["wallet_follow"]                     # fast.db n=10 < 20: the proven wallets' closed tokens (rang)
        self.assertEqual((w["p"], w["n"], w["strategy"]), (0.65, 200, "kupnje dokazanih novčanika"))
        self.assertEqual((pri["influencer"]["p"], pri["influencer"]["strategy"]), (0.4, "pozivi influencera"))
        self.assertEqual(pri["convergence"]["p"], estimate.NO_EDGE)          # nothing measured: no edge, 48 %
        self.assertAlmostEqual(estimate.NO_EDGE, decide.PRIOR)
        q = {"kind": "wallet_follow", "hits": 2, "n": 3, "rang": {"wins": 4, "n": 6}}
        smp = estimate.sample("wallet_follow", q, src_rate=(1, 2))
        self.assertEqual((smp["hits"], smp["n"]), (4, 6))                    # the biggest sample under 10
        est = estimate.estimate(smp, w, 1.0, 0.021)
        self.assertEqual(est["origin"], "prior: kupnje dokazanih novčanika")
        self.assertEqual(est["label"], "procjena, n izvora < 10")
        self.assertAlmostEqual(est["p"], (4 + 10 * 0.65) / 16, places=4)
        # n >= 10 of the source's own fast.db outcomes: the source, no label
        smp = estimate.sample("wallet_follow", q, src_rate=(9, 12))
        self.assertEqual((smp["n"], smp["from"].startswith("fast.db ishodi izvora")), (12, True))
        est = estimate.estimate(smp, w, 1.0, 0.021)
        self.assertEqual((est["origin"], est["label"]), ("source", None))
        # a caller: the +15/-10/45 bench first
        smp = estimate.sample("influencer", {"hits": 1, "n": 2, "bench": {"hits": 8, "n": 14}}, None)
        self.assertEqual((smp["hits"], smp["n"]), (8, 14))
        # the fast.db rate of the kind wins once it has 20 outcomes
        pri = estimate.priors({"wallet_follow": (13, 20)}, {"rang_wallet": (130, 200)})
        self.assertEqual((pri["wallet_follow"]["p"], pri["wallet_follow"]["n"]), (0.65, 20))
        self.assertTrue(pri["wallet_follow"]["src"].startswith("fast.db ishodi (wallet_follow)"))

    def test_ev_with_its_90_percent_interval(self):
        prior = {"p": 0.48, "n": 0, "strategy": "bez prednosti"}
        est = estimate.estimate({"hits": 9, "n": 12}, prior, 1.0, 0.021)
        lo, hi = estimate.wilson(9 + 10 * 0.48, 22)
        self.assertAlmostEqual(est["p_lo"], round(lo, 4))
        self.assertAlmostEqual(est["p_hi"], round(hi, 4))
        self.assertLess(est["ev_lo"], est["ev"])
        self.assertLess(est["ev"], est["ev_hi"])
        self.assertAlmostEqual(est["ev_lo"], edge.ev(est["p_lo"], 0.15, 0.10, 0.021), places=4)
        self.assertAlmostEqual(est["ev_hi"] - est["ev_lo"], (est["p_hi"] - est["p_lo"]) * 0.25, places=4)
        # the modifiers scale P and its interval
        late = estimate.estimate({"hits": 9, "n": 12}, prior, 0.7, 0.021)
        self.assertAlmostEqual(late["p"], round(est["p0"] * 0.7, 4), places=4)
        self.assertAlmostEqual(late["p_hi"], round(hi * 0.7, 4), places=4)
        # decide stores it and says it
        c = {k: {"status": "ok", "text": k, "values": {}} for k in decide.ORDER}
        c["price"]["values"] = {"cost_pct": 2.1, "liq": 60_000, "sol_usd": 150.0}
        d = decide.decide(c, {"kind": "wallet_follow", "hits": 9, "n": 12, "closed": 12, "proof": False,
                              "proof_why": "x"})
        self.assertEqual((d["decision"], d["label"]), ("BUY_PAPER", "KUPI (paper)"))
        self.assertEqual((d["est"]["origin"], d["est"]["n"]), ("source", 12))
        self.assertLess(d["est"]["ev_lo_pct"], d["ev_pct"])
        self.assertLess(d["ev_pct"], d["est"]["ev_hi_pct"])
        self.assertIn("90 %:", d["reason"])
        self.assertIn("P 63 % (n=12, izvor)", d["reason"])

    def test_paper_needs_ev_above_zero_and_live_eligible_needs_the_proof(self):
        c = {k: {"status": "ok", "text": k, "values": {}} for k in decide.ORDER}
        c["price"]["values"] = {"cost_pct": 2.1, "liq": 60_000, "sol_usd": 150.0}
        pri = {"wallet_follow": {"p": 0.65, "n": 200, "hits": 130, "strategy": "kupnje dokazanih novčanika",
                                 "src": "rang"}}
        d = decide.decide(c, {"kind": "wallet_follow", "hits": 0, "n": 0, "closed": 0}, priors=pri)
        self.assertEqual((d["decision"], d["label"], d["key"]), ("BUY_PAPER", "KUPI (paper)", "explore"))
        self.assertIn("procjena, n izvora < 10: paper ulog 0,05 SOL", d["reason"])
        self.assertIn("prior: kupnje dokazanih novčanika", d["reason"])
        d = decide.decide(c, {"kind": "wallet_follow", "hits": 0, "n": 0, "closed": 0})   # no prior: no edge
        self.assertEqual(d["decision"], "SKIP")
        self.assertLessEqual(d["ev_pct"], 0)
        d = decide.decide(c, {"kind": "wallet_follow", "hits": 11, "n": 12, "closed": 12, "proof": True})
        self.assertEqual((d["decision"], d["label"]), ("BUY_LIVE", "KUPI (live-eligible)"))


# ---------- the convergence trigger and the live list's own triggers --------------------------------------------------

class Triggers(Env):
    def kol(self, tok, ts, first, updated, mcap0=250_000.0):
        from kol import store as kstore
        kc = kstore.connect(self.kp)
        kc.execute("INSERT OR REPLACE INTO converge (token, ts, first_ts, score, n_x, n_tg, n_chain, n_other, platforms, "
                   "handles, mcap0, dev_selling, kol_selling, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (tok, ts, first, 64.0, 2, 1, 1, 0, '["x","tg","chain"]', '["a","b"]', None, 0, 0, updated))
        kc.execute("INSERT OR REPLACE INTO calls (tweet_id, token, handle, ts, kind, source, mcap0) VALUES (?,?,?,?,?,?,?)",
                   ("t1", tok, "caller1", first, "call", "x", mcap0))
        kc.commit()
        kc.close()

    def test_a_convergence_is_enqueued_once_and_checked(self):
        t2 = addr(31, "", "pump")
        self.kol(t2, REPLAY_TS, REPLAY_TS - 300, REPLAY_TS + 1)
        self.assertIn(sources.CONVERGENCE, sources.lookup(self.fc, [sources.CONVERGENCE]))   # a followed pseudo-source
        w = worker.Worker(self.fp, good_net(t2), log=lambda s: None, now_fn=lambda: REPLAY_TS + 2)
        paths = {"hype": self.hp, "kol": self.kp, "tg": ""}
        self.assertEqual(w.scan(self.fc, REPLAY_TS + 2, paths), 1)
        r = self.row()
        self.assertEqual((r["token"], r["kind"], r["source_id"], r["via"]), (t2, "convergence", "konvergencija", "converge"))
        self.assertEqual(r["entry_mcap"], 250_000.0)                       # the first measured call since it began
        self.assertEqual(w.scan(self.fc, REPLAY_TS + 3, paths), 0)        # the cursor: not again
        self.kol(t2, REPLAY_TS + 60, REPLAY_TS - 300, REPLAY_TS + 61)      # re-saved within 10 min: deduped
        self.assertEqual(w.scan(self.fc, REPLAY_TS + 62, paths), 0)
        net = good_net(t2, mcap=300_000)
        self.run_worker(net, self.clock(REPLAY_TS + 63))
        r = self.row(r["id"])
        self.assertIn(r["decision"], ("SKIP", "BUY_PAPER"))
        self.assertEqual(r["checks"]["res"]["price"]["values"]["lag_txt"], "skuplje od signala")
        self.assertTrue(r["checks"]["est"]["origin"].startswith("prior: "))

    def test_every_live_row_gets_a_check_and_says_provjera_u_tijeku(self):
        t1, t2, t3 = (addr(40 + i, "", "pump") for i in range(3))
        now = REPLAY_TS + 100
        rows = [{"token": t1, "src": "zovu", "callers10": ["nobody"], "smart10": 0, "age_s": 60,
                 "live": {"price": 1e-5}},
                {"token": t2, "src": "konvergencija", "ts0": now - 100, "mcap0": 200_000.0, "callers10": [],
                 "smart10": 0, "live": {"price": 2e-5}},
                {"token": t3, "src": "alat", "callers10": [], "smart10": 0, "live": {"price": 3e-5}}]
        with mock.patch.object(flive, "_call_times", lambda n, toks: {(t1, "nobody"): now - 60}):
            flive.attach(rows, now, self.fp)
        got = {r["token"]: (r["kind"], r["source_id"], r["sig_ts"])
               for r in store.read(store.ro(self.fp), "1=1", (), limit=10)}
        self.assertEqual(got[t1], ("influencer", "nobody", now - 60))       # a caller the hooks do not follow
        self.assertEqual(got[t2][:2], ("convergence", "konvergencija"))
        self.assertEqual(got[t3], ("tool", "alat", now))                     # the tool's own pick, as it is listed
        for r in rows:
            self.assertEqual(r["fast"]["label"], "provjera u tijeku")
            self.assertNotIn("nije izmjeren", flive.short(r["fast"]))
        with mock.patch.object(flive, "_call_times", lambda n, toks: {(t1, "nobody"): now - 60}):
            flive.attach(rows, now + 1, self.fp)                             # nothing queued twice
        self.assertEqual(self.fc.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 3)

    def test_flag_off_says_so_and_queues_nothing(self):
        settings_off(self)
        rows = [{"token": addr(50, "", "pump"), "src": "alat", "callers10": [], "smart10": 0, "live": {}}]
        flive.attach(rows, REPLAY_TS + 5, self.fp)
        self.assertEqual(rows[0]["fast"]["state"], "off")
        self.assertIn("fast_path: off", rows[0]["fast"]["label"])
        self.assertEqual(self.fc.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)


def settings_off(t):
    from trade import settings
    settings.put(t.tc, "flag:fast_path", {"mode": "off", "since": 0, "who": "Jure"})
    settings._FLAG_CACHE.clear()


# ---------- "nije izmjeren" never rendered --------------------------------------------------------------------------------

def verdict(tok, **kw):
    v = {"state": "done", "token": tok, "decision": "BUY_PAPER", "label": "KUPI (paper)", "ev_pct": 2.4,
         "ev_lo_pct": -1.9, "ev_hi_pct": 6.8, "p": 0.6, "n": 3, "origin": "prior: kupnje dokazanih novčanika",
         "n_label": "procjena, n izvora < 10", "lag_pct": -10.0, "lag_txt": "jeftinije od njega", "reason": "x"}
    v.update(kw)
    return v


class NeverUnmeasured(Env):
    def zrow(self, tok, fast=None, src="zovu"):
        r = {"token": tok, "symbol": tok[:4], "src": src, "live": {"mcap": 300_000, "price": 1e-5, "ch_m5": 3.0,
                                                                   "ch_h1": 9.0}, "reasons": ["novi pozivatelj"]}
        if fast is not None:
            r["fast"] = fast
        return r

    def test_sto_kupiti_shows_the_ev_or_the_state_never_nije_izmjeren(self):
        from ui import apterm, pravitrade
        a, b, c, d, e = (addr(60 + i, "", "pump") for i in range(5))
        zr = [self.zrow(a, verdict(a)),
              self.zrow(b, {"state": "pending", "token": b, "label": "provjera u tijeku", "decision": None}),
              self.zrow(c, {"state": "failed", "token": c, "label": "CHECK_FAILED", "decision": "CHECK_FAILED",
                            "reason": "rug: RugCheck HTTP 429"}),
              self.zrow(d, verdict(d, decision="SKIP", label="PRESKOČI", reason="holderi: top10 62 % > 45 %")),
              self.zrow(e)]                                                  # no verdict at all yet
        cfg = pravitrade._cfg(self.tc)
        with mock.patch.object(apterm, "_proposals", lambda owner, now: ([], [], [], "shadow")), \
                mock.patch("ui.zivo.rows", lambda now=None, **k: zr):
            html = apterm.kupiti_html(self.tc, cfg, True, REPLAY_TS)
        self.assertNotIn("nije izmjeren", html)
        self.assertIn("+2,4 %", html)                                        # KUPI: the EV ...
        self.assertIn("−1,9 do +6,8 %", html)                                # ... its 90 % interval
        self.assertIn("KUPI (paper)", html)
        self.assertIn("procjena, n izvora &lt; 10", html)
        self.assertIn("jeftinije od njega", html)
        self.assertIn("provjera u tijeku", html)
        self.assertIn("CHECK_FAILED: rug: RugCheck HTTP 429", html)
        self.assertNotIn(d, html)                                            # a PRESKOČI goes to the skip journal
        self.assertLess(html.index(a[:4]), html.index(b[:4]))                # a KUPI sorts by its EV per minute

    def test_zivo_rows_carry_the_verdict_and_a_preskoci_is_no_pick(self):
        from ui import zivo
        from tests.test_zivo_offline import NOW, A, B, live
        cands = [{"token": A, "symbol": "AAA", "src": "zovu", "ts0": NOW - 300, "mcap0": 100_000, "why": ["zovu"]},
                 {"token": B, "symbol": "BBB", "src": "zovu", "ts0": NOW - 300, "mcap0": 150_000, "why": ["zovu"]}]
        fv = {A: verdict(A, decision="SKIP", label="PRESKOČI", reason="cijena: MC $14.0M izvan raspona (30k–5M)"),
              B: verdict(B)}
        rs = zivo.rows(NOW, cands=cands, live={A: live(), B: live(mcap=150_000)}, callers={A: ["ansem"], B: ["kolb"]},
                       smart={}, mstats={}, chances={}, fastv=fv)
        got = {r["token"]: r for r in rs}
        self.assertEqual(set(got), {A, B})
        self.assertFalse(got[A]["pick"])
        self.assertEqual(got[A]["why_not"], "fast_check PRESKOČI: cijena: MC $14.0M izvan raspona (30k–5M)")
        self.assertTrue(got[B]["pick"])
        self.assertEqual(got[B]["fast"]["label"], "KUPI (paper)")
        self.assertEqual([r["token"] for r in rs], [B, A])                  # the PRESKOČI after the picks


# ---------- KUPI -> proposals, PRESKOČI -> the skip journal ------------------------------------------------------------

class KupiToProposals(unittest.TestCase):
    def test_a_kupi_is_a_fast_proposal_in_sto_kupiti(self):
        from proposals import build, strategies
        from tests.test_kandidati_offline import NOW, live
        from tests.test_prijedlozi_offline import PSources
        t = addr(70, "", "pump")
        S = PSources()
        S.mk[t] = live(mcap=300_000, liq=40_000)
        fr = verdict(t, decided_ts=NOW - 60, sig_ts=NOW - 65, p0=0.6, p_lo=0.42, p_hi=0.76, p_mult=1.0,
                     kind="wallet_follow", source="HODL", source_id=W_HODL, mcap0=300_000.0, symbol="FST", id=5)
        S.fast_rows = lambda now: {t: fr}
        rows, near, _m = build.build(NOW, S)
        got = {r["token"]: r for r in rows}
        self.assertIn(t, got, near)
        r = got[t]
        self.assertEqual((r["strategy"], r["sources"]), ("fast", ["fast"]))
        self.assertEqual(strategies.HR["fast"], "fast check")
        self.assertGreater(r["ev_pct"], 0)
        st = r["strategies"]["fast"]
        self.assertEqual((st["n"], st["ci90"]), (3, [0.42, 0.76]))
        self.assertIn("procjena, n izvora < 10", st["p_from"])
        self.assertIn("novčanik", r["why"])
        self.assertIn("jeftinije od njega", r["why"])
        self.assertEqual(r["exit_plan"]["stop"], {"at_pct": -10.0})      # the signal exit = fast/paper.PLAN
        self.assertEqual(r["exit_plan"]["time_stop"]["after_min"], 45)
        # a price already 10 %+ over the check's market cap: no longer valid
        S.mk[t] = live(mcap=340_000, liq=40_000)
        rows, near, _m = build.build(NOW, S)
        self.assertNotIn(t, {x["token"] for x in rows})
        # a PRESKOČI is never a proposal
        self.assertIsNone(strategies.fast_ev(dict(fr, decision="SKIP"), 300_000, NOW))


class SkipJournal(Env):
    def test_a_preskoci_is_in_the_journal_with_its_reason_numbers_and_outcome(self):
        from ui import pravitrade
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        net = good_net()
        net.rc[TOK] = rc_report(top=(20, 12, 8, 6, 5, 4, 3, 2, 1, 1))     # top 10 = 62 %
        t0 = REPLAY_TS + 1.1
        self.run_worker(net, self.clock(t0))
        r = self.row()
        self.assertEqual(r["decision"], "SKIP")
        rows = flive.skip_rows(t0 + 5, self.fp)
        self.assertEqual(len(rows), 1)
        html = flive.skip_html(rows, esc, t0 + 5)
        self.assertIn("holderi: top10 62 % &gt; 45 %", html)
        self.assertIn("EV ", html)                                           # the fast_check's numbers
        self.assertIn("P ", html)
        self.assertIn("mjeri se", html)
        # +25 % within the hour: propušteno (fast/outcomes, +20 % within 60 min; 12.11.: on >= 3 price points, else
        # nepouzdano)
        fc = store.connect(self.fp)
        outcomes.put_px(fc, TOK, r["price0"] * 1.05, None, r["decided_ts"] + 300)
        outcomes.put_px(fc, TOK, r["price0"] * 1.25, None, r["decided_ts"] + 600)
        outcomes.put_px(fc, TOK, r["price0"] * 1.10, None, r["decided_ts"] + 900)
        outcomes.measure(fc, r["decided_ts"] + outcomes.HORIZON_S + outcomes.GRACE_S + 1)
        fc.commit()
        fc.close()
        now = r["decided_ts"] + 3910
        rows = flive.skip_rows(now, self.fp)
        self.assertEqual(flive.skip_verdict(rows[0], now)["word"], "propušteno")
        html = flive.skip_html(rows, esc, now)
        self.assertIn("propušteno 1", html)
        # the owner's Preskočeni box carries it; an invited viewer's does not
        with pravitrade._LOCK:
            pravitrade._SK.update(ts=0.0, key=None, html=None, rows=None)
        box = pravitrade.skip_box(self.tc, pravitrade._cfg(self.tc), now, owner=True)
        self.assertIn("Fast check: preskočeni", box)
        self.assertIn("holderi: top10 62 % &gt; 45 %", box)
        self.assertNotIn("Fast check: preskočeni", pravitrade.skip_box(self.tc, pravitrade._cfg(self.tc), now,
                                                                         owner=False))


# ---------- paper mode -------------------------------------------------------------------------------------------------

class PaperMode(Env):
    def test_kupi_labels_map_onto_the_demo_account_with_the_fast_exit(self):
        from league import exitplan
        self.assertEqual(estimate.label("BUY_PAPER"), "KUPI (paper)")
        self.assertEqual(estimate.label("BUY_LIVE"), "KUPI (live-eligible)")
        self.assertEqual(estimate.label("SKIP"), "PRESKOČI")
        self.assertEqual(paper._route({"decision": "BUY_PAPER"}, "paper"), (PU, False))
        self.assertEqual(paper._route({"decision": "BUY_LIVE", "follow_id": self.fid, "kind": "wallet_follow"}, "paper"),
                         (PU, False))                                        # live-eligible is only a label in paper
        self.ingest(REPLAY_TS, REPLAY_TS + 1)
        self.run_worker(good_net(), self.clock(REPLAY_TS + 1.1))
        self.assertEqual(self.row()["checks"]["label"], "KUPI (paper)")
        got = paper.run_once(self.lg, self.market_fn(), now=REPLAY_TS + 3, path=self.fp, sol=SOL_USD, lim=self.lim)
        self.assertEqual(got[0][0], PU)
        p = exitplan.active(self.lg, TOK)
        self.assertEqual((p["plan"]["stop"], p["plan"]["time_stop"]["after_min"]), ({"kind": "pct", "v": -10.0}, 45.0))
        self.assertIsNone(self.lg.execute("SELECT 1 FROM trades WHERE user=? AND token=?", (LU, TOK)).fetchone())


def _src(f):
    with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
        return fh.read()


class Wiring(unittest.TestCase):
    def test_nije_izmjeren_is_gone_from_the_live_lists(self):
        from proposals import strategies
        for f in ("ui/apterm.py", "ui/zivo.py", "fast/live.py"):
            self.assertNotIn("<small>nije izmjeren", _src(f), f)
        self.assertNotIn('"EV nije izmjeren', _src("ui/kandidati.py"))
        self.assertIn("fast", strategies.STRATEGIES)
        self.assertTrue(re.search(r"FAST_MC_MAX", _src("fast/checks.py")))


if __name__ == "__main__":
    unittest.main()
