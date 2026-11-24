"""16.11. (vlasnik: "mid capovi od 2, 3 do 200 milijuna ... dosta ovise o kretanju makrotržišta i Bitcoinu. Bitcoin je
čini se pronašao svoje dno, pa bi imalo smisla očekivati da će volumen na meme platformama sada krenuti lagano prema
gore. Tako da prema tome treba graditi strategiju"), offline:

  - veliki/odziv: the token's answer to BTC's up hours (hit, beta_up, beta_dn, score), None without evidence, the order
  - veliki/makro.recovery: BTC holds its bottom AND the meme platforms' volume rose on two consecutive readings; every
    missing piece says why; risk_off is never a recovery; the trade's label (tag) carries the influencers' mood, which
    decides nothing
  - veliki/live: while the recovery holds the candidates go in the order of the answer to BTC, the trade stores the
    label, the demo's caps x1.5, the REAL caps do not move; the hour's refusal line keeps the whole reason
  - report/midcap.by_regime: the closed trades by the label of their entry
  - makroinf/xapi: one HTTP 402 of twitterapi.io (credits spent) pauses every makroinf call for 30 min, said once

    python3 -m unittest tests.test_oporavak_offline
"""
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from report import midcap as rmid, render  # noqa: E402
from tests import test_veliki_intra_offline as base  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, PU, tok  # noqa: E402
from veliki import live, makro, odziv, prioritet  # noqa: E402

H, D = 3600, 86400
T = 1_790_000_000 // D * D


def btc_series(n=72):
    """BTC hourly closes: +0.6 % every 3rd hour, -0.6 % every 3rd, flat the rest."""
    out, px = {}, 80_000.0
    for k in range(n):
        px *= 1.006 if k % 3 == 0 else 0.994 if k % 3 == 1 else 1.0
        out[T - (n - k) * H] = px
    return out


def token_series(btc, up, dn):
    """A token moving up x BTC's hour on the up hours and dn x on the down hours."""
    ts = sorted(btc)
    out, px = {ts[0]: 1.0}, 1.0
    for a, b in zip(ts, ts[1:]):
        r = btc[b] / btc[a] - 1
        px *= 1 + (up * r if r > 0 else dn * r)
        out[b] = px
    return out


def snap(ts, chg, st="normalno", b24=0.01, regime="neutral"):
    return {"ts": ts, "platforms": {"meme": {"chg": chg}}, "btc_state": st, "btc24": b24, "regime": regime}


class Odziv(unittest.TestCase):
    def test_responsive_token_scores_above_a_laggard(self):
        btc = btc_series()
        fast = odziv.btc_up(token_series(btc, 3.0, 1.0), btc, T)
        slow = odziv.btc_up(token_series(btc, 0.2, 2.0), btc, T)
        self.assertEqual(fast["hit"], 1.0)
        self.assertAlmostEqual(fast["beta_up"], 3.0, places=1)
        self.assertAlmostEqual(fast["beta_dn"], 1.0, places=1)
        self.assertGreater(fast["score"], 2.5)
        self.assertLess(slow["score"], 0.0)                     # falls harder with BTC than it rises: a penalty
        self.assertIn("odziv na rast BTC-a +3.0x", odziv.text(fast))

    def test_too_few_up_hours_is_unknown(self):
        btc = btc_series(12)
        self.assertIsNone(odziv.btc_up(token_series(btc, 3.0, 1.0), btc, T))
        self.assertEqual(odziv.text(None), "odziv na BTC nepoznat")

    def test_one_candle_is_winsorized(self):
        btc = btc_series()
        tk = token_series(btc, 1.0, 1.0)
        last = max(tk)
        tk[last] = tk[last] * 5                                # one +400 % hour
        r = odziv.btc_up(tk, btc, T)
        self.assertLess(r["beta_up"], 3.0)

    def test_order_measured_first_then_given_order(self):
        pr = {"a": {"btc_up": {"score": 0.5}}, "b": {"btc_up": {"score": 2.0}}, "c": {}}
        self.assertEqual(odziv.order(["c", "a", "d", "b"], pr), ["b", "a", "c", "d"])

    def test_closes_reads_candles_and_pairs(self):
        self.assertEqual(odziv.closes([(T + 5, 1, 2, 0.5, 1.5, 9)]), {T + H: 1.5})   # a candle's close is at start + 1 h
        self.assertEqual(odziv.closes([(T, 80_000.0)]), {T: 80_000.0})               # a point price stays at its time

    def test_all_of_compares_the_same_hour_and_skips_the_running_candle(self):
        import sqlite3
        btc = btc_series()
        tk = token_series(btc, 2.0, 1.0)                      # {time: price at that time}
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE tokens (mint TEXT, member INTEGER); CREATE TABLE c1h (token TEXT, ts INTEGER, "
                          "o REAL, h REAL, l REAL, c REAL, v REAL); INSERT INTO tokens VALUES ('m', 1);")
        for t, px in tk.items():                              # the candle that CLOSES at t starts at t - 1 h
            con.execute("INSERT INTO c1h VALUES ('m', ?, ?, ?, ?, ?, 1)", (t - H, px, px, px, px))
        last = max(tk)
        con.execute("INSERT INTO c1h VALUES ('m', ?, 9, 9, 9, 9, 1)", (last,))   # still running at `last`: ignored
        r = odziv.all_of(con, sorted(btc.items()), last)["m"]
        self.assertEqual(r["hit"], 1.0)
        self.assertAlmostEqual(r["beta_up"], 2.0, places=1)


class Recovery(unittest.TestCase):
    def hist(self, r6=-0.10, r12=-0.14, st="dno_se_potvrduje"):
        return [snap(T - 30 * H, -0.2, st), snap(T - 12 * H, r12), snap(T - 6 * H, r6)]

    def test_btc_holds_and_volume_rises_twice(self):
        ok, why, p = makro.recovery(snap(T, -0.05), self.hist(), T)
        self.assertTrue(ok, why)
        self.assertEqual(p, {"btc_ok": True, "vol_ok": True, "readings": [-0.05, -0.1, -0.14]})
        self.assertIn("BTC drži dno", why)
        self.assertIn("raste", why)

    def test_bottom_right_now_counts(self):
        ok, _why, _p = makro.recovery(snap(T, -0.05, "dno_se_potvrduje"), self.hist(st="normalno"), T)
        self.assertTrue(ok)

    def test_no_recent_bottom(self):
        ok, why, p = makro.recovery(snap(T, -0.05), self.hist(st="normalno"), T)
        self.assertFalse(ok)
        self.assertFalse(p["btc_ok"])
        self.assertIn("bez nedavnog dna", why)

    def test_btc_falling_or_free_fall(self):
        ok, why, _p = makro.recovery(snap(T, -0.05, b24=-0.03), self.hist(), T)
        self.assertFalse(ok)
        self.assertIn("pada", why)
        ok, why, _p = makro.recovery(snap(T, -0.05, "slobodan_pad"), self.hist(), T)
        self.assertFalse(ok)
        self.assertIn("slobodan pad", why)

    def test_volume_must_rise_on_both_readings(self):
        ok, why, p = makro.recovery(snap(T, -0.05), self.hist(r6=-0.16), T)       # 12 h ago was higher than 6 h ago
        self.assertFalse(ok)
        self.assertTrue(p["btc_ok"])
        self.assertIn("ne raste dva očitanja zaredom", why)
        ok, why, _p = makro.recovery(snap(T, -0.05), self.hist(r6=-0.055, r12=-0.06), T)
        self.assertFalse(ok)
        self.assertIn("preslabo", why)
        ok, why, _p = makro.recovery(snap(T, -0.22), self.hist(r6=-0.30, r12=-0.40), T)
        self.assertFalse(ok)
        self.assertIn("duboko ispod prosjeka", why)

    def test_missing_readings_say_so(self):
        ok, why, _p = makro.recovery(snap(T, -0.05), [snap(T - 30 * H, -0.2, "dno_se_potvrduje")], T)
        self.assertFalse(ok)
        self.assertIn("premalo očitanja (1 od 3)", why)

    def test_label_and_risk_off(self):
        s = dict(snap(T, 0.0), oporavak={"ok": True, "why": "x"})
        self.assertTrue(makro.is_recovery(s))
        self.assertEqual(makro.tag(s, "blago_bik"), "oporavak/blago_bik")
        self.assertEqual(makro.tag(s), "oporavak")
        off = dict(s, regime="risk_off")
        self.assertFalse(makro.is_recovery(off))
        self.assertEqual(makro.tag(off, "jasno_bik"), "risk_off/jasno_bik")
        self.assertEqual(makro.tag(snap(T, 0.0, regime="risk_on")), "risk_on")
        self.assertIsNone(makro.tag(None))

    def test_refresh_stores_the_recovery_and_logs_it(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.executescript(makro.SCHEMA)
        for h in self.hist():
            con.execute("INSERT INTO makro_h VALUES (?,?,?)", (h["ts"], "neutral", json.dumps(h)))
        said = []
        with mock.patch.object(makro, "snapshot", lambda c, now, mp=None: dict(snap(T, -0.05), why="w", src="test")), \
                mock.patch.object(makro, "mood_now", lambda now=None: "jasno_bik"):
            s = makro.refresh(con, T, said.append)
        self.assertTrue(s["oporavak"]["ok"])
        self.assertEqual(s["oporavak"]["mood"], "jasno_bik")
        self.assertIn("oporavak DA", said[0])
        self.assertIn("influenceri 7 d: jasno bik", said[0])
        row = json.loads(con.execute("SELECT data FROM makro_h WHERE ts=?", (T // H * H,)).fetchone()[0])
        self.assertTrue(row["oporavak"]["ok"])


class RecoveryLive(base.Live):
    def _go(self, rec):
        s = dict(snap(self.now, 0.0), why="test")
        if rec:
            s["oporavak"] = {"ok": True, "why": "BTC drži dno; volumen raste"}
        pr = {tok(31): {"mint": tok(31), "symbol": "BIG", "score": 90.0, "parts": {"trend": 30.0}},
              tok(100): {"mint": tok(100), "symbol": "MID", "score": 10.0, "parts": {"trend": 5.0},
                         "btc_up": {"score": 2.4, "hit": 0.8, "beta_up": 3.0, "beta_dn": 1.0, "n_up": 20, "n_dn": 9}}}
        for obj, name, val in ((makro, "current", lambda now=None, path=None, max_age_s=0: s),
                               (makro, "mood_now", lambda now=None: "blago_bik"),
                               (prioritet, "cached", lambda path=None: pr)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")
        out = live.tick(self.lg, lambda ts: self.mk([t for t in ts if t in (tok(31), tok(100))]), now=self.now,
                        force=True)
        rows = self.lg.execute("SELECT token, makro, prio FROM veliki_trades WHERE user=? ORDER BY id", (PU,)).fetchall()
        return out, rows

    def test_recovery_orders_by_the_answer_to_btc_and_labels_the_trade(self):
        out, rows = self._go(True)
        self.assertEqual([r[0] for r in rows], [tok(100), tok(31)], out)       # the responsive one first
        self.assertEqual({r[1] for r in rows}, {"oporavak/blago_bik"})
        self.assertEqual(json.loads(rows[0][2])["btc_up"]["score"], 2.4)
        self.assertTrue(any(x.startswith("veliki oporavak: DA") for x in out), out)
        self.assertEqual(live.caps(PU, kind="intra")["max_open"], int(live.INTRA_MAX_OPEN * 1.5))
        real = live.caps(LU, kind="intra")
        from veliki import gate
        self.assertEqual((real["size_sol"], real["max_open"]), (gate.real_caps()["size_sol"],
                                                                gate.real_caps()["max_open"]))

    def test_without_recovery_the_priority_order_and_the_plain_label(self):
        out, rows = self._go(False)
        self.assertEqual([r[0] for r in rows], [tok(31), tok(100)], out)
        self.assertEqual({r[1] for r in rows}, {"neutral/blago_bik"})
        self.assertEqual(live.caps(PU, kind="intra")["max_open"], live.INTRA_MAX_OPEN)

    def test_entry_asks_the_exits_question_first(self):
        # 16.11. (production: Dz9mQ9 bought three times, each sold 9-11 s later for a reason known before the buy)
        bad = {tok(100): "prijenos na burzu gate (depozit za prodaju)"}
        p = mock.patch.object(live, "_holderi_bad", lambda t, now: bad.get(t))
        p.start()
        self.addCleanup(p.stop)
        out, rows = self._go(False)
        self.assertEqual([r[0] for r in rows], [tok(31)], out)             # the token the exit would sell is not bought
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE token=?", (tok(100),)).fetchone()[0],
                         0)
        self.assertTrue(any("izlaz bi odmah prodao" in x and "depozit za prodaju" in x for x in out), out)
        self.assertIn("izlaz bi odmah prodao", live.refusal_line())
        # nothing bought now is sold on the next tick for a reason
        out2 = live.tick(self.lg, lambda ts: self.mk(ts), now=self.now + 11, force=True)
        self.assertFalse(any("razlog pada postao loš" in x for x in out2), out2)
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM veliki_trades WHERE status='open'").fetchone()[0], 1)

    def test_intraday_position_takes_no_dca_lot(self):
        row = {"id": 1, "user": PU, "token": tok(100), "symbol": "MID", "kind": "intra", "lots": 1, "half_px": None,
               "stop_px": 0.5e-4, "zone": "{}"}
        cfg = {"dca": 0.10, "dca_mode": "pct"}
        q = (0.85e-4, 2_000_000.0)
        self.assertEqual(live.dca(self.lg, row, q, {"first": 1.0e-4}, self.now, cfg, {}), [])
        self.assertEqual(self.lg.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_refusal_line_keeps_the_reason(self):
        live._ST["ref"] = {}
        for w in ("dnevni: nije u donjih 25% zone", "dnevni: nije u donjih 25% zone",
                  "dnevni: raspon preuzak (5.2%)", "dnevni: raspon preuzak (7.9%)",
                  "dnevni ulaz: dnevni limit: potrošeno 0.700 od 0.3 SOL", "7 d: nije na podršci"):
            live._refused(w)
        line = live.refusal_line()
        self.assertIn("dnevni: nije u donjih N% zone 2", line)
        self.assertIn("dnevni: raspon preuzak 2", line)
        self.assertIn("potrošeno N od N SOL 1", line)
        self.assertIn("N d: nije na podršci 1", line)


for _n in [n for n in dir(base.Live) if n.startswith("test_")]:   # the base's own tests run in their own module
    setattr(RecoveryLive, _n, None)


class Btc:
    """A BTC stub for live.btc_state: the state and the 4 h change the test sets."""

    def __init__(self):
        self.state, self.ch4 = "normalno", 0.002

    def regime(self, t, vol=None):
        return self.state, "test"

    def chg(self, t, hours=4):
        return self.ch4

    def known(self, t):
        return True

    def last_end(self, t):
        return None


class OwnerStop(base.Live):
    """16.11. popodne (vlasnik: "uži stop loss ... samo ako Bitcoin napravi neki movement prema dolje ... Trade-ovi
    trebaju biti otvoreni duže"; his answers: wide stop -20 %, BTC -1.5 % in 4 h, 5 positions x 0.2 SOL)."""

    def setUp(self):
        super().setUp()
        self.btc = Btc()
        for obj, name, val in ((live, "btc_state", lambda now=None: {
                "known": True, "crash": self.btc.state == "slobodan_pad", "crash_obj": self.btc, "last_end": None,
                "state": self.btc.state, "why": "test"}),
                (makro, "current", lambda now=None, path=None, max_age_s=0: dict(snap(self.now, 0.0), why="test")),
                (makro, "mood_now", lambda now=None: None)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.flag("veliki_range", "paper")

    def _enter(self, px=1.0e-4):
        out = live.tick(self.lg, lambda ts: self.mk([t for t in ts if t == tok(100)], px), now=self.now, force=True)
        r = self.lg.execute("SELECT id, entry_px, stop_px, wide_px, tight_ts, size_sol, be_px FROM veliki_trades WHERE "
                            "user=? AND token=?", (PU, tok(100))).fetchone()
        self.assertIsNotNone(r, out)
        return r

    def _row(self, rid):
        return self.lg.execute("SELECT status, reason, stop_px, wide_px, tight_ts FROM veliki_trades WHERE id=?",
                               (rid,)).fetchone()

    def _tick(self, px, dt):
        return live.tick(self.lg, lambda ts: self.mk(ts, px), now=self.now + dt, force=True)

    def test_calm_btc_only_the_wide_stop_and_the_owners_stake(self):
        rid, entry, stop, wide, tight, size, _be = self._enter()
        self.assertAlmostEqual(stop / entry, 0.80, places=6)
        self.assertEqual((wide, tight, size), (stop, None, 0.1))
        from veliki import gate
        self.assertEqual((gate.real_caps({})["size_sol"], gate.real_caps({})["max_open"]), (0.1, 5))
        out = self._tick(entry * 0.90, 60)                       # -10 % of noise: still open, nothing tightened
        st = self._row(rid)
        self.assertEqual((st[0], st[4]), ("open", None), out)
        out = self._tick(entry * 0.79, 120)                      # the token's own collapse: the wide stop
        self.assertEqual(self._row(rid)[:2], ("closed", "stop"), out)

    def test_btc_falls_tight_stop_then_calm_restores_the_wide_one(self):
        rid, entry, stop, _w, _t, _s, be = self._enter()
        self.btc.ch4 = -0.02                                     # BTC -2 % over 4 h
        out = self._tick(entry * 0.97, 60)
        st = self._row(rid)
        self.assertEqual(st[0], "open", out)
        self.assertAlmostEqual(st[2], entry * 0.97 * 0.96)       # 4 % under the price of that moment
        self.assertAlmostEqual(st[3], stop)                      # the stop it replaced is remembered
        self.assertEqual(st[4], int(self.now + 60))
        self.assertTrue(any("BTC -2.0% u 4 h, uži stop" in x for x in out), out)
        out = self._tick(entry * 0.95, 120)                      # set once an episode: not moved again
        self.assertAlmostEqual(self._row(rid)[2], entry * 0.97 * 0.96)
        self.btc.ch4 = -0.004                                    # BTC calm again
        out = self._tick(entry * 0.95, 180)
        st = self._row(rid)
        self.assertEqual((st[0], st[4]), ("open", None), out)
        self.assertAlmostEqual(st[2], stop)                      # back to the wide stop
        self.assertTrue(any("stop natrag na" in x for x in out), out)

    def test_btc_falls_while_in_profit_the_stop_goes_to_break_even(self):
        rid, entry, _stop, _w, _t, _s, be = self._enter()
        self.btc.ch4 = -0.02          # (a free fall with the position >= +1 % net sells at once: rule.reasoned_exit)
        out = self._tick(be * 1.01, 60)
        st = self._row(rid)
        self.assertEqual(st[0], "open", out)
        self.assertAlmostEqual(st[2], be)
        self.assertTrue(any("na ulaz" in x for x in out), out)
        out = self._tick(be * 0.99, 120)                         # falls through break-even: out at about zero
        self.assertEqual(self._row(rid)[:2], ("closed", "be"), out)

    def test_tight_stop_is_hit_while_btc_falls(self):
        rid, entry, _stop, _w, _t, _s, _be = self._enter()
        self.btc.ch4 = -0.016
        self._tick(entry * 0.98, 60)
        out = self._tick(entry * 0.98 * 0.95, 120)
        self.assertEqual(self._row(rid)[:2], ("closed", "stop"), out)

    def test_btc_already_falling_at_the_entry(self):
        self.btc.ch4 = -0.03
        rid, entry, stop, wide, tight, _s, _be = self._enter()
        self.assertAlmostEqual(stop / entry, 0.96, places=6)
        self.assertAlmostEqual(wide / entry, 0.80, places=6)
        self.assertEqual(tight, int(self.now))

    def test_open_positions_get_the_wide_stop_once(self):
        rid, entry, _stop, _w, _t, _s, _be = self._enter()
        self.lg.execute("UPDATE veliki_trades SET stop_px=?, wide_px=NULL WHERE id=?", (entry * 0.94, rid))   # the old stop
        self.lg.execute("DELETE FROM veliki_once WHERE k='wide_stop_1611'")
        self.lg.commit()
        with mock.patch("builtins.print"):
            out = live.owner_wide_once(self.lg, self.now)
        self.assertIn("široki stop -20 % za 1 otvorenih", out[0])
        self.assertAlmostEqual(self._row(rid)[2], entry * 0.80)
        self.lg.execute("UPDATE veliki_trades SET stop_px=? WHERE id=?", (entry * 0.94, rid))
        self.lg.commit()
        self.assertEqual(live.owner_wide_once(self.lg, self.now), [])           # once
        self.assertAlmostEqual(self._row(rid)[2], entry * 0.94)

    def test_one_spiky_quote_does_not_arm_or_fire_break_even(self):
        # 16.11. (production, 7GCihg twice: one quote 8 % above the next armed break-even, the next quote closed the
        # position at -3.6 % / -5.2 %)
        rid, entry, stop, _w, _t, _s, be = self._enter()
        out = self._tick(be * 1.06, 10)                          # one quote at +6 % net
        self.assertAlmostEqual(self._row(rid)[2], stop)          # the stop did not move
        out = self._tick(be * 0.98, 20)                          # the next quote is back under break-even
        self.assertEqual(self._row(rid)[0], "open", out)         # nothing sold: the wide stop holds
        self.assertAlmostEqual(self._row(rid)[2], stop)
        # +5 % that HOLDS for 30 s arms it
        self._tick(be * 1.06, 100)
        self._tick(be * 1.055, 115)
        self.assertAlmostEqual(self._row(rid)[2], stop)
        out = self._tick(be * 1.06, 131)
        self.assertAlmostEqual(self._row(rid)[2], be)
        self.assertTrue(any("+5 % neto, stop na ulaz" in x for x in out), out)
        # armed: one quote under break-even waits for the next one
        out = self._tick(be * 0.97, 140)
        self.assertEqual(self._row(rid)[0], "open", out)
        out = self._tick(be * 1.01, 150)                         # it was an outlier: still open
        self.assertEqual(self._row(rid)[0], "open", out)
        self._tick(be * 0.99, 160)
        out = self._tick(be * 0.99, 171)                         # two quotes under it, 10 s apart: out
        self.assertEqual(self._row(rid)[:2], ("closed", "be"), out)

    def test_btc_down_rule(self):
        from veliki import rule
        b = Btc()
        self.assertEqual(rule.btc_down(b, 0)[0], False)
        b.ch4 = -0.015
        self.assertEqual(rule.btc_down(b, 0), (True, "BTC -1.5% u 4 h"))
        b.ch4, b.state = 0.01, "slobodan_pad"
        self.assertEqual(rule.btc_down(b, 0), (True, "BTC u slobodnom padu"))
        b.ch4, b.state = None, "normalno"
        self.assertEqual(rule.btc_down(b, 0)[0], False)                         # unknown is not "down"
        self.assertAlmostEqual(rule.wide_stop(1.0), 0.80)
        self.assertAlmostEqual(rule.tight_stop(1.0, 1.03), 0.96)
        self.assertAlmostEqual(rule.tight_stop(1.05, 1.03), 1.03)


for _n in [n for n in dir(base.Live) if n.startswith("test_")]:
    setattr(OwnerStop, _n, None)


class Report(unittest.TestCase):
    def test_by_regime_groups_and_mood_and_answer(self):
        u = {"demo": "d", "pravi": "p"}
        hi = json.dumps({"btc_up": {"score": 2.0}})
        lo = json.dumps({"btc_up": {"score": 0.3}})
        rows = [
            {"user": "d", "status": "closed", "ret": 0.10, "pnl_usd": 1.5, "closed_ts": T, "makro": "oporavak/jasno_bik", "prio": hi},
            {"user": "d", "status": "closed", "ret": -0.04, "pnl_usd": -0.6, "closed_ts": T, "makro": "oporavak/neizvjesno", "prio": lo},
            {"user": "d", "status": "closed", "ret": 0.02, "pnl_usd": 0.3, "closed_ts": T, "makro": "neutral", "prio": None},
            {"user": "d", "status": "closed", "ret": 0.02, "pnl_usd": 0.3, "closed_ts": T, "makro": None, "prio": None},
            {"user": "d", "status": "closed", "ret": 0.5, "pnl_usd": 9.0, "closed_ts": T - 30 * D, "makro": "oporavak"},
            {"user": "d", "status": "open", "ret": None, "makro": "oporavak"},
            {"user": "p", "status": "closed", "ret": 0.08, "pnl_usd": 1.2, "closed_ts": T, "makro": "risk_on/blago_bik"},
        ]
        out = rmid.by_regime(rows, u, T - 7 * D)
        got = {(r["racun"], r["rezim"]): (r["n"], r["zbroj"]) for r in out}
        self.assertEqual(got[("demo", "oporavak")], (2, 0.9))
        self.assertEqual(got[("demo", "oporavak, influenceri bikovski")], (1, 1.5))
        self.assertEqual(got[("demo", "oporavak, influenceri nisu bikovski")], (1, -0.6))
        self.assertEqual(got[("demo", "oporavak, odziv na BTC jak")], (1, 1.5))
        self.assertEqual(got[("demo", "oporavak, odziv na BTC slab")], (1, -0.6))
        self.assertEqual(got[("demo", "neutral")], (1, 0.3))
        self.assertEqual(got[("demo", "bez oznake")], (1, 0.3))
        self.assertEqual(got[("pravi", "risk_on")], (1, 1.2))
        self.assertEqual(out[0]["rezim"], "oporavak")                     # the recovery's rows first
        items = render.regime_items(out)
        self.assertTrue(items[0].startswith("Demo, oporavak: 2 zatvorenih"), items[0])
        self.assertTrue(any("Pravi, risk-on" in x for x in items), items)


class NoCredit(unittest.TestCase):
    """16.11.: twitterapi.io answered 402 from 05:45 UTC and the discovery kept probing: one 402 pauses every call."""

    def setUp(self):
        from makroinf import xapi
        self.x = xapi
        xapi.reset()
        self.addCleanup(xapi.reset)

    def test_402_pauses_every_call_and_other_errors_pass_through(self):
        import urllib.error
        calls = []

        def get(url, params):
            calls.append(url)
            raise urllib.error.HTTPError(url, 402, "Payment Required", None, None)
        with mock.patch("builtins.print") as said:
            with self.assertRaises(self.x.NoCredit):
                self.x._call(get, "u", {})
        self.assertIn("krediti potrošeni", said.call_args[0][0])
        self.assertTrue(self.x.no_credit())
        self.assertTrue(issubclass(self.x.NoCredit, self.x.CapReached))     # the callers stop cleanly on CapReached
        with self.assertRaises(self.x.NoCredit):                             # the next call never reaches the network
            self.x.user(None, "a", "faza", {}, get=get)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.x.no_credit(self.x._NC["until"] + 1))          # after the pause the next try asks again
        self.x.reset()

        def boom(url, params):
            raise urllib.error.HTTPError(url, 500, "Server Error", None, None)
        with self.assertRaises(urllib.error.HTTPError):
            self.x._call(boom, "u", {})
        self.assertFalse(self.x.no_credit())


if __name__ == "__main__":
    unittest.main()
