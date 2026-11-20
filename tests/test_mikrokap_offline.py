"""15.11. (vlasnik: "Od sada nema smisla, čak ni u demu, tradati ove mikrokapove tražeći 10 %. Oni mogu biti moonshot
samo ako vidimo ogromnu bazu na društvenim mrežama i puno influencera koji ga zovu ... Inače sada tradamo samo
mid-capove: 5M-150M $"): the microcap gate trade/capgate on every automatic entry path, offline.

  - switch off (mikrokap_blokada not live): the old behaviour; on: an automatic entry needs MC >= 5M, MC unknown no
  - every entry path refuses MC < 5M and lets MC >= 5M through: league/copy (the Autopilot's accounts only), fast path,
    konsenzus, oscilator, momentum, proposals, range lots, the classic demo bot's gate, the strat comparison accounts,
    Grok autotrade's safety check, run_trade's mirror and executor.buy_checks (a HARD reason on the real account)
  - the owner's manual buy is never gated
  - the moonshot exception: demo only, needs 4+ DISTINCT callers (a corr cluster counts once; bots, paid shillers and
    shill networks do not count), X momentum >= 1 with growing organic authors, liquidity >= 50k, top10 <= 45 %; half
    the stake, the source tagged "moonshot", measured on its own; the flag mikrokap_moonshot off = no exception
  - a refusal is logged once per token and day; the daily counter line; the owner order turns the gate on, last

    python3 -m unittest tests.test_mikrokap_offline
"""
import io
import json
import os
import sqlite3
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_trade  # noqa: E402
from fast import paper as fpaper  # noqa: E402
from konsenzus import live as klive, research as R  # noqa: E402
from league import auto, copy, store  # noqa: E402
from momentum import trade as mtrade  # noqa: E402
from oscilator import live as olive  # noqa: E402
from tests.test_konsenzus_offline import SPEC  # noqa: E402
from tests.test_pravi_novac_sve_offline import LU, PU, P, SwitchBase, tok  # noqa: E402
from trade import capgate, executor, settings  # noqa: E402

SMALL = (P, 50_000.0, None, 100_000.0, "SML", {"m5": 1.0})           # MC $100k: a microcap
BIG = (P * 60, 400_000.0, None, 6_000_000.0, "BIG", {"m5": 1.0})       # MC $6M: a mid-cap


class GateBase(SwitchBase):
    def setUp(self):
        super().setUp()
        capgate._SAID.clear()
        capgate._MOON.clear()
        capgate._GROUPS.update(ts=0.0, g=None)
        capgate._EXCL.update(ts=0.0, key=None, v=None)
        capgate._DAY["day"] = None
        self.out = io.StringIO()
        p = mock.patch("builtins.print", lambda *a, **k: self.out.write(" ".join(str(x) for x in a) + "\n"))
        p.start()
        self.addCleanup(p.stop)
        self.gate_on()

    def gate_on(self, on=True):
        settings.set_flag(self.con, capgate.FLAG, "live" if on else "off", "Jure")
        settings._FLAG_CACHE.clear()

    def no_moon(self):
        settings.set_flag(self.con, capgate.MOON_FLAG, "off", "Jure")
        settings._FLAG_CACHE.clear()

    def trades(self, user, token):
        return self.lg.execute("SELECT source, size_usd FROM trades WHERE user=? AND token=?", (user, token)).fetchall()


class Gate(GateBase):
    def test_switch_off_is_the_old_behaviour(self):
        self.gate_on(False)
        self.assertEqual(capgate.allow_entry(tok(1), 100_000, "x", PU, self.now), (True, None))
        self.assertEqual(capgate.allow_entry(tok(1), None, "x", PU, self.now), (True, None))

    def test_on_refuses_under_5m_and_unknown_allows_5m_and_more(self):
        self.no_moon()
        ok, why = capgate.allow_entry(tok(2), 1_200_000, "copy KOL a", PU, self.now)
        self.assertFalse(ok)
        self.assertTrue(why.startswith("MC ispod 5M (mikrokap): MC $1,200,000"))
        self.assertFalse(capgate.allow_entry(tok(3), None, "x", PU, self.now)[0])
        self.assertEqual(capgate.allow_entry(tok(4), 5_000_000, "x", PU, self.now), (True, None))
        self.assertEqual(capgate.allow_entry(tok(4), 80_000_000, "x", LU, self.now), (True, None))

    def test_manual_owner_buy_is_never_gated(self):
        self.assertEqual(capgate.allow_entry(tok(5), 50_000, "ručno", LU, self.now, {"manual": True}), (True, None))

    def test_refusal_logged_once_per_token_and_day_and_the_day_counter(self):
        self.no_moon()
        for _ in range(3):
            capgate.allow_entry(tok(6), 200_000, "fast path", PU, self.now, {"symbol": "ABC"})
        capgate._SAID.clear()   # another process: the trade.db row says it was already logged
        capgate.allow_entry(tok(6), 200_000, "fast path", PU, self.now, {"symbol": "ABC"})
        capgate.allow_entry(tok(7), 300_000, "range", LU, self.now)
        lines = [x for x in self.out.getvalue().splitlines() if x.startswith("mikrokap: odbijen ulaz")]
        self.assertEqual(len(lines), 2)
        self.assertIn("ABC (fast path, autopilot-paper): MC ispod 5M (mikrokap)", lines[0])
        self.assertEqual(capgate.counts(self.now)["refused"], 2)
        self.assertIsNone(capgate.day_tick(self.now))            # the first call only remembers the day
        line = capgate.day_tick(self.now + 86400)                 # the next Zagreb day: the closed day's counter
        self.assertRegex(line, r"^mikrokap \d+\.\d+\.: odbijeno 2 ulaza ispod 5M, moonshot iznimki 0$")

    def test_start_line(self):
        txt = capgate.start_line(log=None)
        self.assertTrue(txt.startswith("mikrokap blokada: automatski ulazi samo MC ≥ 5M $ (iznimka moonshot"))
        self.gate_on(False)
        self.assertIn("ISKLJUČENA", capgate.start_line(log=None))

    def test_config_only_tightens_the_moonshot(self):
        p = os.path.join(self.tmp.name, "config.json")
        with open(p, "w") as f:
            json.dump({"mikrokap": {"min_mc": 3_000_000, "moon_min_callers": 2, "moon_min_liq": 80_000,
                                    "moon_top10_max": 90, "moon_window_h": 3}}, f)
        c = capgate.cfg(p)
        self.assertEqual(c["min_mc"], 3_000_000)          # the owner's band may move
        self.assertEqual(c["moon_min_callers"], 4)        # never looser
        self.assertEqual(c["moon_min_liq"], 80_000)       # stricter: yes
        self.assertEqual(c["moon_top10_max"], 45.0)
        self.assertEqual(c["moon_window_h"], 3)


class Moonshot(GateBase):
    """The exception's data on temporary databases (kol.db, tg.db, xfeat.db, topcheck.db, early.db)."""

    def setUp(self):
        super().setUp()
        d = self.tmp.name
        self.p = {k: os.path.join(d, f"{k}.db") for k in ("kol", "tg", "xfeat", "topcheck", "early", "rug", "hype")}
        k = sqlite3.connect(self.p["kol"])
        k.executescript("CREATE TABLE calls (tweet_id TEXT, token TEXT, handle TEXT, ts INTEGER, kind TEXT);"
                        "CREATE TABLE kols (handle TEXT PRIMARY KEY, bot INTEGER);")
        k.execute("INSERT INTO kols VALUES ('alertbot', 1)")
        k.commit()
        k.close()
        t = sqlite3.connect(self.p["tg"])
        t.execute("CREATE TABLE posts (channel TEXT, post INTEGER, ts INTEGER, cas TEXT, fwd_from TEXT)")
        t.commit()
        t.close()
        x = sqlite3.connect(self.p["xfeat"])
        x.execute("CREATE TABLE x_momentum (id INTEGER PRIMARY KEY, token TEXT, ts INTEGER, score REAL, organic15 "
                  "INTEGER, organic_prev60 INTEGER)")
        x.commit()
        x.close()
        tc = sqlite3.connect(self.p["topcheck"])
        tc.execute("CREATE TABLE top_check (token TEXT PRIMARY KEY, rc_json TEXT)")
        tc.commit()
        tc.close()
        e = sqlite3.connect(self.p["early"])
        e.execute("CREATE TABLE preshill_networks (id INTEGER, members TEXT, shill INTEGER)")
        e.execute("INSERT INTO preshill_networks VALUES (1, ?, 1)", (json.dumps(["shillnet1"]),))
        e.commit()
        e.close()
        self.grp = R.Groups()
        self.grp.join(["clustera", "clusterb"])     # one corr cluster: counts once
        self.tok = tok(20)

    def call(self, handle, age_min=30, kind="call"):
        k = sqlite3.connect(self.p["kol"])
        k.execute("INSERT INTO calls VALUES (?,?,?,?,?)", (f"{handle}{age_min}", self.tok, handle,
                                                           int(self.now - age_min * 60), kind))
        k.commit()
        k.close()

    def tg(self, channel, fwd=None):
        t = sqlite3.connect(self.p["tg"])
        t.execute("INSERT INTO posts VALUES (?,?,?,?,?)", (channel, 1, int(self.now - 600), f"x,{self.tok}", fwd))
        t.commit()
        t.close()

    def xm(self, score=1.4, organic=6, prev=4, age_min=10):
        x = sqlite3.connect(self.p["xfeat"])
        x.execute("INSERT INTO x_momentum (token, ts, score, organic15, organic_prev60) VALUES (?,?,?,?,?)",
                  (self.tok, int(self.now - age_min * 60), score, organic, prev))
        x.commit()
        x.close()

    def top10(self, pct):
        tc = sqlite3.connect(self.p["topcheck"])
        tc.execute("INSERT OR REPLACE INTO top_check VALUES (?, ?)", (self.tok, json.dumps({"top10": pct})))
        tc.commit()
        tc.close()

    def strong(self):
        for h in ("clustera", "clusterb", "solo1", "alertbot", "cryptoprolegend", "shillnet1", "w:WALLETX"):
            self.call(h)   # 2 clustered (= 1), 1 solo, a bot, a paid shiller (kol/shillers.json), a shill network
        self.call("gemx")   # 19.11.: an X caller (a Telegram channel no longer counts, kol/tgout.py)
        self.tg("gemchannel")
        self.tg("fwdchannel", fwd="other")   # a forward is no call
        self.call("solo2")
        self.xm()
        self.top10(30.0)

    def allow(self, account=PU, mcap=900_000, liq=80_000, **kw):
        ctx = dict({"liq": liq, "paths": self.p, "groups": self.grp}, **kw)
        return capgate.allow_entry(self.tok, mcap, "copy KOL a", account, self.now, ctx)

    def test_strong_social_base_passes_on_the_demo_account(self):
        self.strong()
        ok, why = self.allow()
        self.assertTrue(ok, why)
        self.assertTrue(capgate.is_moon(why))
        self.assertIn("4 neovisnih callera", why)
        self.assertIn("mikrokap: MOONSHOT iznimka", self.out.getvalue())
        self.assertEqual(capgate.counts(self.now)["moon"], 1)

    def test_clustered_and_bot_callers_do_not_make_four(self):
        for h in ("clustera", "clusterb", "solo1", "alertbot", "cryptoprolegend", "shillnet1"):
            self.call(h)
        self.call("gemx")   # 19.11.: an X caller (a Telegram channel no longer counts, kol/tgout.py)
        self.tg("gemchannel")
        self.xm()
        self.top10(30.0)
        ok, why = self.allow()
        self.assertFalse(ok)
        self.assertIn("3 neovisnih callera", why)
        self.assertIn("3 botova / shillera ne broji", why)

    def test_old_calls_outside_the_window_do_not_count(self):
        self.strong()
        k = sqlite3.connect(self.p["kol"])
        k.execute("UPDATE calls SET ts=? WHERE handle='solo2'", (int(self.now - 7 * 3600),))
        k.commit()
        k.close()
        self.assertFalse(self.allow()[0])

    def test_momentum_and_organic_growth_are_required(self):
        self.strong()
        x = sqlite3.connect(self.p["xfeat"])
        x.execute("UPDATE x_momentum SET score=0.6")
        x.commit()
        x.close()
        ok, why = self.allow()
        self.assertFalse(ok)
        self.assertIn("X momentum 0,60 < 1", why)
        x = sqlite3.connect(self.p["xfeat"])
        x.execute("UPDATE x_momentum SET score=1.0, organic15=1, organic_prev60=0")   # one author against none
        x.commit()
        x.close()
        ok, why = self.allow()
        self.assertFalse(ok)
        self.assertIn("organskih autora 1", why)
        x = sqlite3.connect(self.p["xfeat"])
        x.execute("DELETE FROM x_momentum")
        x.commit()
        x.close()
        self.xm(age_min=200)   # stale
        self.assertIn("nema svježeg X momentuma", self.allow()[1])

    def test_liquidity_and_holders_are_required(self):
        self.strong()
        self.assertIn("likvidnost $40,000 < $50,000", self.allow(liq=40_000)[1])
        self.assertIn("likvidnost", self.allow(liq=None)[1])
        self.top10(62.0)
        self.assertIn("top10 holdera 62 % > 45 %", self.allow()[1])
        tc = sqlite3.connect(self.p["topcheck"])
        tc.execute("DELETE FROM top_check")
        tc.commit()
        tc.close()
        self.assertIn("top10 holdera nepoznat", self.allow()[1])

    def test_never_on_the_real_account_never_under_30k_never_with_the_flag_off(self):
        self.strong()
        ok, why = self.allow(account=LU)
        self.assertFalse(ok)
        self.assertIn("pravi račun: moonshot iznimka samo u demu", why)
        self.assertIn("MC ispod 30k", self.allow(mcap=20_000)[1])
        self.assertIn("nije bondan", self.allow(bonded=False)[1])
        self.assertIn("strategija bez moonshot", self.allow(moonshot=False)[1])
        self.no_moon()
        self.assertIn("moonshot iznimka isključena", self.allow()[1])
        with self.assertRaises(ValueError):   # never live: no switch lets a moonshot use real money
            settings.set_flag(self.con, capgate.MOON_FLAG, "live", "Jure")

    def test_check_tags_and_halves_the_moonshot(self):
        reason = "moonshot: 4 neovisnih callera"
        with mock.patch.object(capgate, "allow_entry", lambda *a, **k: (True, reason)):
            why, src, size = capgate.check(self.tok, 900_000, "copy KOL a", PU, 20.0, self.now, sol=150.0)
            self.assertIsNone(why)
            self.assertEqual(src, "copy KOL a · moonshot")
            self.assertEqual(size, 7.5)   # half of $20 = $10, at most 0.05 SOL = $7.5
            why, src, size = capgate.check(self.tok, 900_000, "fast path", PU, 0.2, self.now, unit="sol")
            self.assertEqual((src, size), ("fast path · moonshot", 0.05))
            self.assertEqual(capgate.check(self.tok, 900_000, "x", PU, 0.06, self.now, unit="sol")[2], 0.03)

    def test_moonshot_measured_as_its_own_strategy(self):
        t1 = store.buy(self.lg, PU, tok(21), "M1", 10, P, 50_000, "copy KOL a · moonshot", None, 900_000)
        store.buy(self.lg, PU, tok(22), "M2", 10, P, 50_000, "konsenzus S1 · moonshot", None, 900_000)
        store.buy(self.lg, PU, tok(23), "N", 10, P, 50_000, "copy KOL a", None, 6_000_000)
        store.sell(self.lg, PU, t1, P * 1.5, 50_000)
        st = capgate.moon_stats(self.lg)
        self.assertEqual((st["n"], st["open"], st["closed"]), (2, 1, 1))
        self.assertGreater(st["ev_pct"], 40)      # +50 % less the 1 % a side and the pool impact
        self.assertLess(st["ev_pct"], 50)


class Paths(GateBase):
    """Each automatic entry path: MC < 5M refused, MC >= 5M allowed (moonshot off so nothing reads social data)."""

    def setUp(self):
        super().setUp()
        self.no_moon()

    def test_league_copy_gates_the_autopilot_accounts_only(self):
        ed = mock.patch.object(copy, "entry_data", lambda *a, **k: {"score": None, "runup": None, "call_mcap": None})
        ed.start()
        self.addCleanup(ed.stop)
        for user in (PU, LU, "ana"):
            fid = copy.follow(self.lg, user, "wallet", "W" * 44, "kit", 25, 50, "mirror")
            f = [x for x in copy.follows(self.lg, user) if x["id"] == fid][0]
            mk = {tok(30): SMALL, tok(31): BIG}
            copy._enter(self.lg, auto, mk, [(f, tok(30), "buy", int(self.now) - 5), (f, tok(31), "buy",
                                                                                      int(self.now) - 5)], int(self.now))
            small, big = self.trades(user, tok(30)), self.trades(user, tok(31))
            self.assertEqual(len(big), 1, user)
            if user == "ana":   # another player's copy: not the bot's trading, not held
                self.assertEqual(len(small), 1)
            else:
                self.assertEqual(small, [], user)
                note = self.lg.execute("SELECT note FROM copy_log WHERE token=? AND action='preskočeno' AND "
                                       "follow_id=?", (tok(30), fid)).fetchone()[0]
                self.assertIn("MC ispod 5M (mikrokap)", note)

    def test_league_copy_switch_off_old_behaviour(self):
        self.gate_on(False)
        ed = mock.patch.object(copy, "entry_data", lambda *a, **k: {"score": None, "runup": None, "call_mcap": None})
        ed.start()
        self.addCleanup(ed.stop)
        fid = copy.follow(self.lg, PU, "wallet", "W" * 44, "kit", 25, 50, "mirror")
        f = [x for x in copy.follows(self.lg, PU) if x["id"] == fid][0]
        copy._enter(self.lg, auto, {tok(32): SMALL}, [(f, tok(32), "buy", int(self.now) - 5)], int(self.now))
        self.assertEqual(len(self.trades(PU, tok(32))), 1)

    def test_league_copy_moonshot_half_stake_and_tag(self):
        settings.set_flag(self.con, capgate.MOON_FLAG, "paper", "Jure")
        settings._FLAG_CACHE.clear()
        ed = mock.patch.object(copy, "entry_data", lambda *a, **k: {"score": None, "runup": None, "call_mcap": None})
        ed.start()
        self.addCleanup(ed.stop)
        fid = copy.follow(self.lg, PU, "wallet", "W" * 44, "kit", 20, 50, "mirror")
        f = [x for x in copy.follows(self.lg, PU) if x["id"] == fid][0]
        with mock.patch.object(capgate, "social", lambda *a, **k: (True, "4 neovisnih callera", {})), \
                mock.patch.object(copy, "_sol_usd", lambda: 150.0):
            copy._enter(self.lg, auto, {tok(33): SMALL}, [(f, tok(33), "buy", int(self.now) - 5)], int(self.now))
        (src, size), = self.trades(PU, tok(33))
        self.assertTrue(src.endswith(" · moonshot"), src)
        self.assertAlmostEqual(size, 7.5)   # half of $20, at most 0.05 SOL x $150

    def test_fast_path(self):
        fpaper.ensure(self.lg)
        lim = {"max_open": 5, "max_sol_per_day": 5.0}
        for i, (mq, ok) in enumerate(((SMALL, False), (BIG, True))):
            s = {"id": 60 + i, "token": tok(60 + i), "decision": "BUY_PAPER", "size_sol": 0.05, "price0": mq[0],
                 "kind": "insider", "source_label": "X", "source_id": "W" * 44, "sig_ts": int(self.now)}
            text, why = fpaper.enter(self.lg, s, PU, False, mq, lim, 100.0, int(self.now),
                                     path=os.path.join(self.tmp.name, "nofast.db"))
            if ok:
                self.assertIsNone(why)
                self.assertTrue(text)
            else:
                self.assertIn("MC ispod 5M (mikrokap)", why)

    def test_konsenzus(self):
        klive.ensure(self.lg)
        for i, (mq, ok) in enumerate(((SMALL, False), (BIG, True))):
            text, why = klive.enter(self.lg, SPEC, PU, tok(70 + i), int(self.now) - 10, "a", mq, int(self.now), 150.0)
            self.assertEqual(bool(text), ok, why)
            if not ok:
                self.assertIn("MC ispod 5M (mikrokap)", why)

    def test_oscilator(self):
        olive.ensure(self.lg)
        for i, (mq, ok) in enumerate(((SMALL, False), (BIG, True))):
            text, why = olive.enter(self.lg, PU, tok(80 + i), mq, int(self.now), 150.0, "dno raspona")
            self.assertEqual(bool(text), ok, why)
            if not ok:
                self.assertIn("MC ispod 5M (mikrokap)", why)

    def test_momentum(self):
        from momentum import rules as mrules   # its own band ends at 3M: widened here to see the gate alone
        mb = mock.patch.dict(mrules.RULES, {"mcap_max": 200_000_000})
        mb.start()
        self.addCleanup(mb.stop)
        self.flag("momentum_scalp", "paper")
        lim = {"size_sol": 0.1, "max_sol_per_day": 5.0, "max_open": 5, "dca_token_cap": 0.3}
        for i, (mq, ok) in enumerate(((SMALL, False), (BIG, True))):
            t = tok(90 + i)
            sig = {t: {"id": 90 + i, "token": t, "ts": int(self.now), "price": mq[0], "symbol": "MOM",
                       "features": {"ch_m5": 10.0}}}
            with mock.patch.dict(os.environ, {"MOMENTUM_DB": os.path.join(self.tmp.name, "momentum.db")}):
                done = mtrade.run_once(self.lg, lambda toks, mq=mq: {x: mq for x in toks}, int(self.now), sig, lim,
                                       100.0)
            self.assertEqual(bool([u for u, _ in done if u == PU]), ok)

    def test_range_lots(self):
        from rangedca import trade as rtrade
        self.assertIn("MC ispod 5M (mikrokap)", rtrade._mikrokap(tok(100), 300_000, PU, self.now, 50_000, SMALL, None))
        self.assertIsNone(rtrade._mikrokap(tok(101), 6_000_000, PU, self.now, 400_000, BIG, None))
        self.assertIn("MC ispod 5M (mikrokap)", rtrade._mikrokap(tok(102), 300_000, LU, self.now, 50_000, SMALL, {}))

    def test_proposals(self):
        from proposals import paper as ppaper, store as pstore, view as pview
        ppath = os.path.join(self.tmp.name, "proposals.db")
        penv = mock.patch.dict(os.environ, {"PROPOSALS_DB": ppath})
        penv.start()
        self.addCleanup(penv.stop)
        ppaper._LAST.clear()
        pview.clear()
        now = int(self.now)

        def seed(token, mc):
            st = {"momentum": {"valid": True, "ev_pct": 5.0, "expires_ts": now + 900, "p_tp": 0.7}}
            r = {"token": token, "symbol": "PRP", "strategy": "momentum", "sources": ["momentum"], "n_independent": 1,
                 "ev_pct": 5.0, "p_tp": 0.7, "n": 100, "ci90": [0.6, 0.8], "tp_pct": 20.0, "sl_pct": 12.0,
                 "cost_pct": 3.0, "size_sol": 0.15, "why": "Zato.", "risks": [], "strategies": st,
                 "entry_zone": {"mcap_low": mc * 0.98, "mcap_high": mc * 1.04}, "mcap0": mc,
                 "exits_mcap": {"tp": [mc * 1.2], "tp_share": [1.0], "sl": mc * 0.88},
                 "exit_plan": {"take_profits": [{"at_pct": 20.0, "sell_share": 1.0}], "stop": {"at_pct": -12.0}},
                 "buy": {"tp": "20%", "sl": "-12%", "sol": 0.15, "hold_s": 2700}, "market": {"market_cap_usd": mc},
                 "expires_ts": now + 900, "price0": 1.0, "liq0": 60_000}
            con = pstore.connect(ppath)
            pstore.insert(con, r, now)
            con.commit()
            con.close()
        self.flag("proposals", "paper")
        seed(tok(110), 82_000)
        seed(tok(111), 6_000_000)
        mk = {tok(110): (1.0, 60_000.0, None, 82_000.0), tok(111): (1.0, 400_000.0, None, 6_000_000.0)}
        ppaper.run_once(self.lg, lambda toks: {t: mk[t] for t in toks if t in mk}, now, sol=200.0)
        self.assertEqual(self.trades(PU, tok(110)), [])
        self.assertEqual(len(self.trades(PU, tok(111))), 1)

    def test_classic_demo_bot_gate(self):
        from paper import rules
        self.assertIn("MC ispod 5M (mikrokap)", rules.gate(tok(120), 1e-4, 60_000, 100_000, "prolaz", None, None))
        why = rules.gate(tok(121), 1e-4, 400_000, 6_000_000, "prolaz", None, None)
        self.assertFalse(why and "mikrokap" in why)
        self.gate_on(False)
        why = rules.gate(tok(120), 1e-4, 60_000, 100_000, "prolaz", None, None)
        self.assertFalse(why and "mikrokap" in why)

    def test_strat_comparison_accounts(self):
        from strat import run as srun
        self.assertIn("MC ispod 5M (mikrokap)", srun._mikrokap(tok(130), 200_000, "kol", self.now, 50_000))
        self.assertIn("MC nepoznat", srun._mikrokap(tok(130), 0, "kol", self.now, 50_000))
        self.assertIsNone(srun._mikrokap(tok(131), 7_000_000, "kol", self.now, 400_000))

    def test_grok_autotrade_safety(self):
        from ui import grokauto
        why, _risk = grokauto.safety_ex(tok(140), lambda toks: {t: SMALL for t in toks})
        self.assertIn("MC ispod 5M (mikrokap)", why)
        why, _risk = grokauto.safety_ex(tok(141), lambda toks: {t: BIG for t in toks})
        self.assertFalse(why and "mikrokap" in why)

    def test_real_account_hard_reason_in_buy_checks(self):
        got = list(executor.buy_checks(self.con, self.cfg, 0.1, self.now, True, balance=5.0, token=tok(150),
                                       mcap=300_000))
        self.assertEqual(got[0][:2], (executor.HARD, "mikrokap"))
        self.assertTrue(got[0][2].startswith("MC ispod 5M (mikrokap)"))
        self.assertIn("MC ispod 5M (mikrokap)", self.gate(token=tok(150), mcap=300_000))
        self.assertIsNone(self.gate(token=tok(151), mcap=6_000_000))
        # the owner's own manual buy: never held (not even with his override in play)
        self.assertIsNone(self.gate(token=tok(152), mcap=300_000, manual=True))
        self.assertIsNone(self.gate(token=tok(152), mcap=300_000, manual=True, override=True))
        # an override never passes it on an automatic buy (HARD)
        self.assertIn("mikrokap", self.gate(token=tok(153), mcap=300_000, override=True))
        self.gate_on(False)
        self.assertIsNone(self.gate(token=tok(150), mcap=300_000))

    def test_run_trade_mirror_refuses_an_automatic_real_buy_under_5m(self):
        self.switch(True)
        self.demo(tok(160), "prijedlog: momentum", mcap=300_000)
        self.mirror()
        st = self.pos(tok(160))
        self.assertEqual(st[0], "blocked")
        self.assertIn("MC ispod 5M (mikrokap)", st[2])
        self.assertEqual(self.swaps, [])

    def test_run_trade_mirror_lets_5m_through(self):
        self.switch(True)
        self.quote["row"] = BIG
        self.demo(tok(161), "prijedlog: momentum", mcap=6_000_000)
        self.mirror()
        self.assertEqual(self.pos(tok(161))[:2], ("open", "live"))

    def test_run_trade_owner_manual_buy_not_gated(self):
        tid = self.demo(tok(162), "ručno (pravi trade)", mcap=300_000, sl=None)
        settings.put(self.con, "manual_size", {str(tid): 0.05})
        self.cfg = settings.merged(executor.load_config(), self.con)
        self.cfg["on"] = True
        self.mirror()
        st = self.pos(tok(162))
        self.assertFalse(st and "mikrokap" in (st[2] or ""), st)
        self.assertIsNone(run_trade._mikrokap({"token": tok(163), "entry_mcap": 6_000_000, "source": "x",
                                               "symbol": "S"}, self.now))


class Orders(GateBase):
    def test_owner_order_last_turns_the_gate_on_once(self):
        from ui import assistnotes
        # 15.11.: the big tokens' order (veliki_range -> paper) came after it
        mine = tuple(o for o in assistnotes.OWNER_FLAG_ORDERS if o[0] == "mikrokap_blokada")
        self.assertEqual([o[:2] for o in mine], [("mikrokap_blokada", "live")])
        self.assertNotIn(capgate.MOON_FLAG, [n for n, _m, _w in assistnotes.OWNER_FLAG_ORDERS])
        self.gate_on(False)
        self.con.execute("DELETE FROM settings WHERE k=?", (f"flag:{capgate.FLAG}",))
        self.con.commit()
        with mock.patch.object(assistnotes, "OWNER_FLAG_ORDERS", mine):
            self.assertEqual(assistnotes.owner_flag_orders(self.con), ["zastavica mikrokap_blokada: off → live"])
            settings.set_flag(self.con, capgate.FLAG, "off", "Jure")    # the owner turns it off later
            self.assertEqual(assistnotes.owner_flag_orders(self.con), [])   # it stays off
        settings._FLAG_CACHE.clear()
        self.assertFalse(capgate.on())
        self.assertEqual(settings.flag(capgate.MOON_FLAG, self.con), "paper")   # default: the demo exception on
        self.assertIn(capgate.FLAG, settings.OWNER_SWITCHES)
        self.assertIn(capgate.MOON_FLAG, settings.NEVER_LIVE)
        self.assertIn(capgate.MOON_FLAG, settings.PROFILE_FLAGS)
        self.assertFalse(settings.any_paper(self.con))   # the moonshot's paper never makes the paper account follow

    def test_page_row_in_prekidaci(self):
        from ui import apterm
        h = apterm.mikrokap_html(self.con, True, self.now)
        self.assertIn("Mikrokap blokada", h)
        self.assertIn("automatski ulazi samo MC ≥ 5M $", h)
        self.assertIn("name=name value=mikrokap_blokada", h)
        self.assertIn("name=name value=mikrokap_moonshot", h)
        self.assertIn("moonshot demo dosad", h)
        rest = apterm.owner_switches_html(self.con, True)
        self.assertNotIn("value=mikrokap_blokada", rest)
        self.assertNotIn("name=name", apterm.mikrokap_html(self.con, False, self.now))   # a viewer: no form


if __name__ == "__main__":
    unittest.main()
