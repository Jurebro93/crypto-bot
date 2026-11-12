"""12.11. popodne (owner, točke 1 i 4): the range job's 5-minute numbers and range compute after a late / lost cycle
(deploy #156 at 13:34 CET: no pass for ~6 min, every candidate "5-minutni podaci nisu svježi"), and the rug archive.

  - one late cycle (numbers 6 min old): entry_ready decided by the real rules, the real reason shown plus a staleness
    note; the automatic buy (trade gate, 5 min) waits for fresh numbers
  - numbers past the readiness limit (9 min): not entry_ready, but entry_now still leads with the real reason (zone,
    score, breakout); the owner's pin likewise
  - after a gap the job catches up at once (full detection, gap logged); start.sh starts it 30 s after a start and
    schedules by deadline
  - a fetch raising HTTPError 502 (signal poll, market pass) or one token's error never ends the pass
  - rug-archive tokens: never entry_ready, never bought (lot 1 / lot 2 / reclaim guard), never armed in zonewatch
    (range zones, arm_zone; zones already armed end), never polled by the range job, off the market list
No network.

    python3 -m unittest tests.test_range_svjezina_1211_offline
"""
import io
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rangedca import data, market, owner, trade, view  # noqa: E402
from rugfilter import archive  # noqa: E402
from tests.test_range_dca_offline import MINT, PU, S, TradeBase, tri  # noqa: E402
from tests.test_zonewatch_offline import Base as ZBase, NOW as ZNOW  # noqa: E402
from zonewatch import store as zstore  # noqa: E402

OTHER = "B" * 43 + "pump"


def _err502(*_a, **_k):
    raise urllib.error.HTTPError("https://api.dexscreener.com/tokens/v1/solana", 502, "Bad Gateway", {}, None)


def archived(*toks):
    """rugfilter/archive patched: these tokens are in the rug archive (kind rug)."""
    s = frozenset(toks)
    return mock.patch.multiple(archive, blocked=lambda *a, **k: s, kinds=lambda *a, **k: {t: "rug" for t in s})


class Late(TradeBase):
    """The readiness view (get_range_candidates rows) against the trade gate."""

    def row(self, r, now=None):
        return view.one(MINT, r, now or self.now)

    def test_one_late_cycle_keeps_the_real_rules_and_adds_a_note(self):
        r = self.rng()
        r["mts"] = self.now - 360                                              # 6 min: one lost cycle (a restart)
        x = self.row(r)
        self.assertTrue(x["entry_ready"], x["entry_now"])                      # the real rules decide
        self.assertTrue(x["entry_now"].startswith("ulaz bi prošao"), x["entry_now"])
        self.assertIn("5-minutni podaci stari 6.0 min", x["entry_now"])       # ... and the note says how old
        f = x["freshness"]
        self.assertEqual((f["numbers_age_s"], f["ready_limit_s"], f["trade_limit_s"], f["trade_gate_fresh"]),
                         (360, 540, 300, False))
        # the price at 60 % of the range: the real reason first, the note after it
        far = self.rng(price=75 * S)
        far["mts"] = self.now - 360
        y = self.row(far)
        self.assertFalse(y["entry_ready"])
        self.assertTrue(y["entry_now"].startswith("cijena na"), y["entry_now"])
        self.assertIn("5-minutni podaci stari", y["entry_now"])
        # fresh numbers: no note at all
        z = self.row(self.rng())
        self.assertIsNone(z["freshness"]["note"])
        self.assertEqual(z["entry_now"], "ulaz bi prošao (uz provjeru ruga i limite)")

    def test_the_trade_gate_keeps_a_hard_five_minutes(self):
        self.mode("paper")
        stale = self.rng()
        stale["mts"] = self.now - 360
        why = trade.entry_view(stale, 52 * S, self.now)
        self.assertEqual(why, "5-minutni podaci nisu svježi (stari 6.0 min, granica 5 min)")
        self.assertEqual(self.enter(rng=stale), [])                            # no automatic buy on 6-min numbers
        self.assertEqual(self.lots(PU), [])
        late = self.rng()
        late["ts"] = self.now
        late["mts"] = self.now - 270                                           # 4.5 min: inside the 5-min gate
        self.assertIsNone(trade.entry_view(late, 52 * S, self.now))
        self.assertEqual([u for u, _ in self.enter(rng=late)], [PU])
        # a real reason and stale numbers: both said, the real one first
        far = self.rng(price=75 * S)
        far["mts"] = self.now - 360
        w = trade.entry_view(far, 75 * S, self.now)
        self.assertTrue(w.startswith("cijena na"), w)
        self.assertIn("5-minutni podaci nisu svježi", w)

    def test_past_the_readiness_limit_the_real_reason_still_leads(self):
        old = self.rng(price=75 * S)
        old["mts"] = self.now - 600                                            # 10 min
        x = self.row(old)
        self.assertFalse(x["entry_ready"])
        self.assertTrue(x["entry_now"].startswith("cijena na"), x["entry_now"])
        self.assertIn("5-minutni podaci nisu svježi (stari 10.0 min, granica 9 min)", x["entry_now"])
        self.assertEqual(x["entry_now"].count("nisu svježi"), 1)               # said once
        inzone = self.rng()
        inzone["mts"] = self.now - 600
        y = self.row(inzone)
        self.assertFalse(y["entry_ready"])
        self.assertEqual(y["entry_now"].count("nisu svježi"), 1, y["entry_now"])
        # a breakout keeps "probijen gore" and gets the note
        brk = self.rng(price=120 * S)
        brk["pos_pct"], brk["mts"] = 140.0, self.now - 600
        z = self.row(brk)
        self.assertTrue(z["entry_now"].startswith("probijen gore"), z["entry_now"])
        self.assertIn("nisu svježi", z["entry_now"])
        # a low score: the score is the reason, not the age
        low = self.rng(score=0.5)
        low["mts"] = self.now - 600
        self.assertTrue(self.row(low)["entry_now"].startswith("ocjena raspona 0.50"))

    def test_the_owners_pin_keeps_its_real_reason(self):
        r = self.rng(price=75 * S, mcap=75_000)
        r["mts"] = self.now - 600
        r["pin_vol"] = {"holds": True}
        ready, why, det = owner.pin_check(r, {"zones_mc": None}, self.now)
        self.assertFalse(ready)
        self.assertTrue(why.startswith("cijena na"), why)                      # the zone rule, not only the age
        self.assertIn("nisu svježi", why)
        self.assertIn("stale", det)
        r2 = self.rng(price=52 * S, mcap=52_000)
        r2["pin_vol"], r2["mts"] = {"holds": True}, self.now - 360            # 6 min: inside the pin's 9 min
        self.assertEqual(owner.pin_check(r2, {"zones_mc": None}, self.now)[:2], (True, None))


class Job(TradeBase):
    """run_range.once: catch-up after a gap, a 502 never ends the pass."""

    def setUp(self):
        super().setUp()
        self.mode("paper")
        self.logs = []

    def pair(self, tok, px):
        return {"baseToken": {"address": tok, "symbol": "RNG"}, "priceUsd": str(px), "marketCap": px * 1e9,
                "dexId": "pumpswap", "pairAddress": "Pool" + tok[:8], "liquidity": {"usd": 25_000},
                "volume": {"m5": 5000, "h1": 60_000, "h6": 360_000},
                "txns": {"m5": {"buys": 6, "sells": 4}, "h1": {"buys": 60, "sells": 40}}, "priceChange": {"m5": 1.0}}

    def fetch(self, toks):
        last = tri(self.now - 12 * 3600 + 60 - self.now % 60, hours=12)[-1]
        self.asked.append(list(toks))
        return [self.pair(t, last[4]) for t in toks]

    def gt(self, pool, start, end):
        return [c[:6] for c in tri(end - 12 * 3600 + 60, hours=12)]

    def first(self, extra=(MINT,)):
        import run_range
        self.asked = []
        out = run_range.once(now=self.now, log=self.logs.append, fetch=self.fetch, gt_fetch=self.gt,
                             post=lambda *a: {}, extra=list(extra))
        self.assertIn("aktivnih", out)
        return run_range

    def test_after_a_gap_the_job_catches_up_at_once(self):
        rr = self.first()
        con = data.connect()
        self.addCleanup(con.close)
        self.assertEqual(data.kv_get(con, "last_pass"), self.now)
        rr.once(now=self.now + 60, log=self.logs.append, fetch=self.fetch, gt_fetch=self.gt, extra=[MINT])
        self.assertEqual(data.kv_get(con, "last_detect"), self.now)           # between detections: numbers only
        self.assertFalse(any("rupa" in s for s in self.logs))
        # a deploy: no pass for 6 min; the next one detects at once and says so
        t = self.now + 60 + 360
        rr.once(now=t, log=self.logs.append, fetch=self.fetch, gt_fetch=self.gt, extra=[MINT])
        self.assertEqual(data.kv_get(con, "last_detect"), t)
        r, _st = data.load_range(con, MINT)
        self.assertEqual((r["ts"], r["mts"]), (t, t))
        gap = [s for s in self.logs if "rupa" in s]
        self.assertEqual(len(gap), 1, self.logs)
        self.assertIn("rupa od 360 s", gap[0])
        self.assertIn("puni izračun raspona", gap[0])

    def test_start_sh_starts_the_job_early_and_schedules_by_deadline(self):
        with open(os.path.join(ROOT, "start.sh"), encoding="utf-8") as f:
            line = next(ln for ln in f if "run_range.py once" in ln)
        self.assertIn('sleep "${RANGE_FIRST_S:-30}"', line)                    # was a fixed 270 s
        self.assertIn("r0=$(date +%s)", line)                                  # the period counts from the start
        self.assertIn("${RANGE_EVERY_S:-60} - $(date +%s) + r0", line)

    def test_a_502_from_the_signal_poll_never_ends_the_pass(self):
        rr = self.first()
        with redirect_stdout(io.StringIO()) as out:
            text = rr.once(now=self.now + 60, log=self.logs.append, fetch=_err502, gt_fetch=self.gt, extra=[MINT])
        self.assertIn("aktivnih 1", text)
        self.assertIn("DexScreener nije odgovorio (HTTPError)", out.getvalue())
        con = data.connect()
        self.addCleanup(con.close)
        self.assertEqual(data.load_range(con, MINT)[0]["mts"], self.now + 60)  # numbers renewed from what range.db has
        with redirect_stdout(io.StringIO()):                                   # a full detection on a 502 too
            rr.once(now=self.now + 300, log=self.logs.append, fetch=_err502, gt_fetch=self.gt, extra=[MINT])
        self.assertEqual(data.kv_get(con, "last_detect"), self.now + 300)
        self.assertEqual(data.load_range(con, MINT)[0]["ts"], self.now + 300)

    def test_a_failing_market_pass_or_token_costs_only_itself(self):
        rr = self.first(extra=(MINT, OTHER))
        self.mode("paper", "range_market")
        con = data.connect()
        self.addCleanup(con.close)
        market.ensure(con)
        con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched) VALUES (?,?,?,?,?,1)",
                    (OTHER, "gt", "market", self.now, self.now))
        con.commit()
        real_load = data.load_range

        def load_range(c, tok):
            if tok == OTHER:
                raise urllib.error.HTTPError("x", 502, "Bad Gateway", {}, None)
            return real_load(c, tok)
        with mock.patch.object(market, "pass_once", side_effect=RuntimeError("overload")), \
                mock.patch.object(data, "load_range", load_range):
            text = rr.once(now=self.now + 60, log=self.logs.append, fetch=self.fetch, gt_fetch=self.gt,
                           extra=[MINT])
        self.assertIn("kandidata", text)
        self.assertTrue(any("range tržište: prolaz nije uspio (RuntimeError" in s for s in self.logs), self.logs)
        self.assertTrue(any("1 tokena nije izračunato" in s for s in self.logs), self.logs)
        self.assertEqual(data.load_range(con, MINT)[0]["mts"], self.now + 60)  # the other token is computed
        self.assertEqual(data.kv_get(con, "last_pass"), self.now + 60)

    def test_the_market_net_raising_502_is_no_snapshot_only(self):
        con = data.connect()
        self.addCleanup(con.close)
        market.ensure(con)

        class Net:
            def pairs(self, tokens, deadline=None):
                _err502()

            def lists(self):
                return []

            def gt_pools(self, n_req=None):
                return []

            def birdeye_list(self):
                return None
        con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched, liq) VALUES (?,?,?,?,?,1,?)",
                    (OTHER, "gt", "market", self.now, self.now, 30_000.0))
        data.kv_put(con, "mkt_lists_ts", self.now + 10 ** 6)                   # discovery lists / GT rounds not due
        data.kv_put(con, "mkt_gt_ts", self.now + 10 ** 6)
        con.commit()
        logs = []
        with redirect_stdout(io.StringIO()), \
                mock.patch.multiple(market, _meter=lambda *a, **k: None, from_graduates=lambda c, n: 0,
                                    from_scanner=lambda c, n, scan_db=None: 0,
                                    from_migrations=lambda c, n, hype_db=None: 0):
            out = market.pass_once(con, self.now, Net(), log=logs.append, pulse=set(), event_on=False)
        # a 502 is no answer, not "no price": the token stays watched (it was taken off for 3 days before 12.11.)
        self.assertIn(OTHER, out["tokens"])
        self.assertEqual(out["stats"]["unanswered"], 1)
        self.assertEqual(con.execute("SELECT watched, last_snap FROM mkt WHERE token=?", (OTHER,)).fetchone(), (1, None))
        self.assertTrue(any("nije odgovorio za 1 tokena" in s for s in logs), logs)

    def test_fetch_pairs_fast_says_which_batches_were_answered(self):
        from dexscreener import client
        toks = [f"T{i:02d}" + "x" * 40 for i in range(45)]
        calls = []

        def live(chain, batch, ttl=None):
            calls.append(batch)
            if len(calls) == 2:
                _err502()
            return [{"baseToken": {"address": t}} for t in batch]
        with mock.patch.object(client, "tokens_live", live):
            got = data.fetch_pairs_fast(toks)
        self.assertEqual(len(calls), 2)
        self.assertEqual(got.answered, set(toks[:30]))                         # the second batch (502) is unknown
        self.assertEqual(len(got), 30)


class RugArchive(TradeBase):
    """12.11. (owner, točka 4): tokens in the rug archive are never traded, never entry-ready, never polled."""

    def test_never_bought_and_never_entry_ready(self):
        self.mode("paper")
        with archived(MINT), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.enter(), [])
            x = view.one(MINT, self.rng(), self.now, pin={"zones_mc": None})
            g = trade._guards(MINT, (52 * S, 25_000.0, None, 52_000.0))       # lot 1, lot 2 and reclaim all ask it
        self.assertIn("arhivi rugova", g)
        self.assertEqual(self.lots(PU), [])
        self.assertIn("ulaz blokiran, token je u arhivi rugova (rug)", out.getvalue())
        self.assertFalse(x["entry_ready"])
        self.assertFalse(x["pin_ready"])
        self.assertTrue(x["entry_now"].startswith("token je u arhivi rugova (rug)"), x["entry_now"])
        self.assertIn("ne trguje", x["rug_archive"])
        # out of the archive (recovered): the same range trades again
        self.assertEqual([u for u, _ in self.enter()], [PU])

    def test_the_range_job_does_not_poll_them_and_the_market_list_drops_them(self):
        self.mode("paper")
        import run_range
        asked, logs = [], []
        with archived(MINT):
            run_range.once(now=self.now, log=logs.append, fetch=lambda t: asked.append(list(t)) or [],
                           gt_fetch=lambda *a: None, extra=[MINT, OTHER])
        self.assertEqual(asked, [[OTHER]])
        self.assertTrue(any("iz arhive rugova preskočeno" in s for s in logs), logs)
        con = data.connect()
        self.addCleanup(con.close)
        market.ensure(con)
        con.execute("INSERT INTO mkt (token, via, src, first_seen, next_ts, watched) VALUES (?,?,?,?,?,1)",
                    (MINT, "gt", "market", self.now, self.now))
        self.assertEqual(market.drop_archived(con, self.now, {MINT}, open_toks=(), log=logs.append), [MINT])
        self.assertEqual(con.execute("SELECT watched, why FROM mkt WHERE token=?", (MINT,)).fetchone(),
                         (0, market.ARCHIVE_WHY))
        con.execute("UPDATE mkt SET watched=1 WHERE token=?", (MINT,))
        self.assertEqual(market.drop_archived(con, self.now, {MINT}, open_toks={MINT}, log=logs.append), [])


class RugArchiveZones(ZBase):
    """zonewatch never arms a rug-archive token: no range zones, arm_zone refuses, zones in force end."""

    def save(self, tok):
        rc = data.connect()
        res = {"ts": ZNOW, "status": "aktivan", "active": True, "score": 0.8, "pos_pct": 5.0,
               "zones": {"range_low_low": 60e-6, "range_low_top": 66e-6, "range_high_low": 95e-6, "range_high_top": 100e-6,
                         "range_low": 63e-6, "range_high": 97e-6,
                         "mc": {"range_low_low": 60_000, "range_low_top": 66_000, "range_high_low": 95_000,
                                "range_high_top": 100_000}},
               "metrics": {"price": 62e-6, "mcap": 62_000, "supply": 1e9}, "source": "signal"}
        data.save_range(rc, tok, res, {}, tok[:4])
        rc.commit()
        rc.close()

    def test_never_armed(self):
        a, b = "A" * 43, "C" * 43
        self.save(a)
        self.save(b)
        zstore.arm(a, "custom", 70_000, 80_000, ttl_h=1, now=ZNOW, con=self.con)   # armed before it was archived
        logs = []
        with archived(a), redirect_stdout(io.StringIO()) as out, \
                mock.patch.object(zstore, "_entry_ready", lambda now: {a, b}), \
                mock.patch.object(zstore, "_open_lot1_mc", lambda: {a: 64_000}), \
                mock.patch.object(zstore, "position_tokens", lambda now: {a}):
            toks, _n = zstore.sync_range(self.con, ZNOW + 60, log=logs.append)
            with self.assertRaises(ValueError) as ctx:
                zstore.arm(a, "bottom", 60_000, 66_000, now=ZNOW + 61, con=self.con)
        self.assertEqual(toks, 1)
        live = {(m, src) for m, src in self.con.execute("SELECT mint, source FROM armed_zones WHERE expires_at > ?",
                                                        (ZNOW + 60,))}
        self.assertEqual({m for m, _ in live}, {b})                            # a: no range zones, its custom one ended
        self.assertIn("arhivi rugova", str(ctx.exception))
        self.assertIn("odbijen", out.getvalue())
        self.assertTrue(any("razoružana" in s and "arhivi rugova" in s for s in logs), logs)
        self.assertIn("arhivi rugova", zstore.kv_get(self.con, "range_why")[a])
        self.assertTrue(any(a[:6] in s and "arhivi rugova" in s for s in logs if "bez zona" in s), logs)

    def test_entry_ready_uses_the_readiness_limit(self):
        from rangedca import trade as rtrade
        a = "A" * 43
        self.save(a)
        rc = data.connect()
        r, st = data.load_range(rc, a)
        r.update(mts=ZNOW + 400 - 360, metrics={"price": 61e-6, "mcap": 61_000, "supply": 1e9, "ch_5m": 0.01,
                                                "buy_share_5m": 0.6, "vol_ratio": 0.9})
        data.save_range(rc, a, r, st, "AAAA")
        rc.commit()
        rc.close()
        self.assertEqual(rtrade.METRICS_READY_S, 540)
        self.assertEqual(zstore._entry_ready(ZNOW + 400), {a})                # 6-min numbers keep its zones
        self.assertEqual(zstore._entry_ready(ZNOW + 40 + 600), set())          # 10 min: not entry-ready


if __name__ == "__main__":
    unittest.main()
