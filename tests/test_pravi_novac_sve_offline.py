"""14.11. (owner: "Ja sada ne govorim o demu, ja sad govorim o pravim tradovima i pravom novcu ... nema više demo ...
idemo s pravim novcem"; his caps: 0,1 SOL po tradeu, dnevni gubitak 0,5 SOL, sve strategije, najviše 10 otvorenih, 100
tradeova dnevno): the owner switch trade/settings "pravi_novac_sve".

Off (default): every strategy path exactly as before (the demo proofs decide real money, LIVE_CAPS hold). On: every
automatic strategy in paper / live trades the real account without the demo proofs, within trade/executor.SWITCH_CAPS;
the hard rules still refuse (kill switch, rug archive, < 30k, the pump.fun curve, the reserve, a duplicate token, the
swap cost); every real position has a server-side stop (league/exitplan SWITCH_SRC); Grok's limits and the owner's
manual buys are unchanged. No network: the swap, the wallet, Jupiter and DexScreener are fakes.

    python3 -m unittest tests.test_pravi_novac_sve_offline
"""
import json
import os
import sqlite3
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_trade  # noqa: E402
from fast import paper as fpaper  # noqa: E402
from kol import precall as pc  # noqa: E402
from league import auto, copy, exitplan, store  # noqa: E402
from momentum import gate as mgate, trade as mtrade  # noqa: E402
from proposals import paper as ppaper, store as pstore, view as pview  # noqa: E402
from tests.test_pozicije_izlaz_offline import MINT, Base  # noqa: E402
from trade import executor, jupiter, settings, wallet  # noqa: E402
from ui import grokauto  # noqa: E402

LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
SW = settings.SWITCH_ALL
P = 1e-4   # price: MC = P x 1e9 = $100k
REAL_SWAP = executor.swap


def tok(i):
    return MINT[:-3] + f"{i:03d}"


class FakeJup:
    """Jupiter quotes for sell_check (a clean round trip) and for the swap's own quote (cost in USD)."""

    def __init__(self, cost=1.0):
        self.cost = cost

    def order(self, inp, out, amount, taker=None, route="v2", slippage_bps=None):
        rate = 1000 if inp == jupiter.SOL else 1 / 1000
        return {"inAmount": str(amount), "outAmount": str(int(amount * rate)), "requestId": "rq", "inUsdValue": 100,
                "outUsdValue": 100 - self.cost, "transaction": "dHg=", "error": None}


class SwitchBase(Base):
    def setUp(self):
        super().setUp()
        self.now = time.time()
        self.swaps = []
        self.lines = []
        self.fj = FakeJup()

        def swap(inp, out, amount, live, max_cost_pct=None, routes=executor.ROUTES, limit=None, slippage_bps=None):
            self.swaps.append({"token": out, "lamports": amount, "live": live, "cap": max_cost_pct})
            return {"status": "ok", "amount_in": amount, "amount_out": 1000, "cost_pct": 1.23, "fee_lamports": 5000,
                    "attempts": [], "tried": [], "fee_total": 5000, "signature": "SIG"}
        quote = {"row": (P, 50_000.0, None, 100_000.0, "SYM", {"m5": 1.0})}
        self.quote = quote
        patches = [(executor, "swap", swap), (executor, "is_live", lambda cfg: True),
                   (executor, "STOP_FILE", os.path.join(self.tmp.name, "STOP")),
                   (wallet, "sol_balance", lambda addr: 5.0), (wallet, "address", lambda: "ADDR"),
                   (jupiter, "order", self.fj.order), (run_trade, "notify", self.lines.append),
                   (run_trade, "_switch_market", lambda toks: {t: quote["row"] for t in toks}),
                   (copy, "_rugged", lambda *a, **k: None), (copy, "_concentration", lambda t: (None, "nepoznato")),
                   (copy, "wake", lambda: None)]
        for obj, name, val in patches:
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        from rugfilter import archive
        p = mock.patch.object(archive, "blocked", lambda *a, **k: frozenset())
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(settings._FLAG_CACHE.clear)
        settings._FLAG_CACHE.clear()
        exitplan._SWEEP["ts"] = 0.0
        mgate._CACHE.update(at=0.0, path=None, val=None)
        self.cfg = settings.merged(executor.load_config(), self.con)

    def switch(self, on=True):
        settings.set_flag(self.con, SW, "live" if on else "off", "Jure")
        settings._FLAG_CACHE.clear()

    def flag(self, name, m):
        settings.put(self.con, f"flag:{name}", {"mode": m, "since": int(self.now)})
        settings._FLAG_CACHE.clear()

    def demo(self, token, source, mcap=100_000.0, follow_id=None, sl="-30%", age=30):
        tid = store.buy(self.lg, LU, token, "SYM", 25, P, 50_000, source, None, mcap)
        self.lg.execute("UPDATE trades SET opened_ts=?, follow_id=? WHERE id=?", (int(self.now - age), follow_id, tid))
        self.lg.commit()
        if sl:
            auto.set_auto(self.lg, LU, tid, "tpsl", "15%", sl)
        return tid

    def mirror(self):
        run_trade.follow_league_once(self.con, self.cfg, since=0, now=self.now, quiet=True)

    def pos(self, token):
        r = self.con.execute("SELECT status, mode, reason, sol_in FROM positions WHERE token=? ORDER BY id DESC",
                             (token,)).fetchone()
        return tuple(r) if r else None

    def live_rows(self, n, reason="copy KOL x", status="open", sol_in=0.1, sol_back=0.0, closed=None, opened=None):
        for i in range(n):
            self.con.execute("INSERT INTO positions (token, opened_ts, closed_ts, mode, status, sol_in, sol_back, reason) "
                             "VALUES (?,?,?,?,?,?,?,?)", (f"R{status}{i}{reason[:3]}", int(opened or self.now - 60),
                                                         closed, "live", status, sol_in, sol_back, reason))
        self.con.commit()

    def gate(self, size=0.1, balance=5.0, **kw):
        return executor.gate_buy(self.con, self.cfg, size, self.now, True, balance=balance, **kw)


# ---------- the switch itself -----------------------------------------------------------------------------------------

class TheSwitch(SwitchBase):
    def test_default_off_an_owner_switch_only_the_owner_turns_it_on(self):
        self.assertFalse(settings.pravi_novac_sve(con=self.con))
        self.assertIn(SW, settings.FLAGS)
        self.assertIn(SW, settings.OWNER_SWITCHES)
        self.assertNotIn(SW, settings.NEVER_LIVE)
        for who in ("asistent (Primijeni)", "Jure (chat 10.11.)", "bot", ""):
            with self.assertRaisesRegex(ValueError, "samo vlasnik"):
                settings.set_flag(self.con, SW, "live", who)
        self.assertFalse(settings.pravi_novac_sve(con=self.con))
        from ui import assistnotes
        self.assertNotIn(SW, [n for n, _m, _w in assistnotes.OWNER_FLAG_ORDERS])   # never turned on by a chat order
        from ui import pravitrade
        self.assertIn("err=", pravitrade.post("/pravi-trade/flag", {"name": SW, "mode": "live"}, "netko"))
        self.assertIn("ok=", self.post("/pravi-trade/flag", {"name": SW, "mode": "live"}))   # the owner's tap
        settings._FLAG_CACHE.clear()
        self.assertTrue(settings.pravi_novac_sve(con=self.con))
        self.assertTrue(settings.pravi_novac_sve())                     # read-only, the other processes' way
        self.assertIn("ok=", self.post("/pravi-trade/flag", {"name": SW, "mode": "off"}))
        settings._FLAG_CACHE.clear()
        self.assertFalse(settings.pravi_novac_sve())

    def test_the_warning_box_on_the_page(self):
        from ui import pravitrade
        html = pravitrade._switch_box(self.con, self.cfg, True)
        for part in ("isključeno", "pravim novcem", "negativnim izmjerenim EV-om", "momentum −6 %",
                     "insider_copy −2 %", "confluence −17 %", "0,1 SOL</b> po kupnji", "10 otvorenih",
                     "100 automatskih kupnji", "−0,5 SOL", "arhiva rugova", "samo bondani", "Uključi pravi novac",
                     f"value={SW}", "value=live", "Wallet za 10"):
            self.assertIn(part, html)
        self.assertNotIn("<form", pravitrade._switch_box(self.con, self.cfg, False))   # a viewer: no button
        self.switch(True)
        html = pravitrade._switch_box(self.con, self.cfg, True)
        self.assertIn("UKLJUČENO", html)
        self.assertIn("Isključi pravi novac", html)
        self.assertIn("value=off", html)


# ---------- the caps ------------------------------------------------------------------------------------------------------

class Caps(SwitchBase):
    def test_off_the_live_caps_exactly_as_before(self):
        self.assertEqual(executor.LIVE_CAPS, {"max_sol_per_trade": 0.1, "max_sol_per_day": 0.3, "max_open": 3,
                                              "max_loss_day": 0.15})
        self.assertIn("iznad limita 0.1", self.gate(0.2))
        self.assertNotIn("pravi_novac_sve", self.gate(0.2))
        self.live_rows(3, opened=executor._day_start(self.now) - 600)     # opened yesterday: not today's spend
        self.assertEqual(self.gate(), "3 otvorenih pozicija")              # LIVE_CAPS max_open 3
        self.live_rows(3, status="closed", sol_back=0.1, closed=int(self.now - 30))
        self.assertIn("dnevni limit automatskih kupnji: potrošeno 0.300 od 0.3 SOL", self.gate())

    def test_on_per_trade_and_the_stake(self):
        self.switch(True)
        why = self.gate(0.2)
        self.assertIn("strop pravi_novac_sve max_sol_per_trade", why)
        self.assertIsNone(self.gate(0.1))
        r = executor.buy(self.con, self.cfg, tok(1), "A", now=self.now, size_sol=0.3, reason="copy KOL x")
        self.assertEqual(r["status"], "open")
        self.assertEqual(self.swaps[-1]["lamports"], 100_000_000)        # cut to 0.1 SOL
        r = executor.buy(self.con, self.cfg, tok(2), "B", now=self.now, reason="momentum scalp")
        self.assertEqual(self.swaps[-1]["lamports"], 100_000_000)        # the switch's stake, not the page's
        self.assertEqual(self.swaps[-1]["cap"], self.cfg["max_cost_pct"])  # the cost cap stays the owner's

    def test_on_ten_open_all_strategies_together(self):
        self.switch(True)
        y = executor._day_start(self.now) - 600
        self.live_rows(3, opened=y)
        self.assertIsNone(self.gate())                                     # LIVE_CAPS' 3 no longer binds
        self.live_rows(6, reason="ručno (pravi trade)", opened=y)          # the owner's lots count in the 10 too
        self.assertIsNone(self.gate())
        self.live_rows(1, reason="momentum scalp", opened=y)
        why = self.gate()
        self.assertIn("strop pravi_novac_sve max_open: 10 otvorenih pravih pozicija", why)
        self.switch(False)
        self.assertEqual(self.gate(), "10 otvorenih pozicija")             # off: the old line, the old cap

    def test_on_100_buys_a_day_the_owners_own_apart(self):
        self.switch(True)
        self.live_rows(99, status="closed", sol_back=0.1, closed=int(self.now - 30))
        self.live_rows(5, reason="ručno (pravi trade)", status="closed", sol_back=0.1, closed=int(self.now - 30))
        self.assertIsNone(self.gate())
        self.live_rows(1, reason="fast path buy_paper: x", status="closed", sol_back=0.1, closed=int(self.now - 30))
        why = self.gate()
        self.assertIn("strop pravi_novac_sve max_buys_day: danas već 100 automatskih pravih kupnji od 100", why)
        self.assertEqual(executor.auto_buys(self.con, self.now), 100)

    def test_on_the_day_loss_stop_until_the_next_zagreb_day(self):
        self.switch(True)
        start = executor._day_start(self.now)
        self.live_rows(4, status="closed", sol_in=0.2, sol_back=0.0, closed=start - 60, opened=start - 600)  # yesterday
        self.assertIsNone(self.gate())
        self.live_rows(1, status="closed", sol_in=0.3, sol_back=0.05, closed=int(self.now - 30))
        self.assertIsNone(self.gate())                                     # -0.25 SOL today
        self.live_rows(1, reason="momentum scalp", status="closed", sol_in=0.3, sol_back=0.05,
                       closed=int(self.now - 20))
        why = self.gate()                                                  # -0.50 SOL: stop
        self.assertIn("strop pravi_novac_sve max_loss_day", why)
        self.assertIn("do sljedećeg dana (Zagreb)", why)
        self.assertIsNone(executor.gate_buy(self.con, self.cfg, 0.1, start + 86400 + 60, True, balance=5.0))

    def test_on_the_day_turnover_11_sol(self):
        self.switch(True)
        self.live_rows(49, status="closed", sol_in=0.22, sol_back=0.22, closed=int(self.now - 30))
        self.assertIsNone(self.gate())
        self.live_rows(1, status="closed", sol_in=0.22, sol_back=0.22, closed=int(self.now - 30))
        self.assertIn("strop pravi_novac_sve max_sol_per_day", self.gate())

    def test_config_json_holds_them_and_may_only_lower_them(self):
        cfg = executor.load_config()
        self.assertEqual(cfg["pravi_novac_sve"], {"size_sol": 0.1, "max_sol_per_trade": 0.1, "max_open": 10,
                                                  "max_buys_day": 100, "max_loss_day": 0.5, "max_sol_per_day": 11.0})
        self.assertIn("14.11.", cfg["_pravi_novac_sve"])
        self.assertEqual(executor.switch_caps(cfg), executor.SWITCH_CAPS)
        low = executor.switch_caps({"pravi_novac_sve": {"max_open": 50, "max_buys_day": 20, "max_loss_day": "x"}})
        self.assertEqual((low["max_open"], low["max_buys_day"], low["max_loss_day"]), (10, 20, 0.5))
        # the old fields the demo strategies and the switch-off real money read are untouched
        self.assertEqual((cfg["size_sol"], cfg["max_open"], cfg["max_sol_per_day"], cfg["max_loss_day"], cfg["mode"]),
                         (0.1, 5, 1.0, 0.4, "dry"))
        self.assertNotIn("ne dokaže prednost", cfg["_nicholas_5_11"])

    def test_the_owners_manual_buy_and_grok_are_unchanged(self):
        self.live_rows(4)
        cfg = {**self.cfg, "max_sol_per_trade": 0.5, "max_open": 50}
        off = list(executor.buy_checks(self.con, cfg, 0.5, self.now, True, balance=5.0, token=tok(9), manual=True))
        self.switch(True)
        on = list(executor.buy_checks(self.con, cfg, 0.5, self.now, True, balance=5.0, token=tok(9), manual=True))
        self.assertEqual(on, off)
        self.assertEqual(on, [])                                           # 0.5 SOL: his own settings, not 0.1
        r = executor.buy(self.con, cfg, tok(9), "M", now=self.now, size_sol=0.5, reason="ručno (pravi trade)",
                         manual=True)
        self.assertEqual((r["status"], self.swaps[-1]["lamports"]), ("open", 500_000_000))
        self.assertEqual({k: v[0] for k, v in grokauto.LIMITS.items()},
                         {"grok_max_sol_per_trade": 0.1, "grok_max_sol_per_day": 0.3, "grok_max_open": 3,
                          "grok_max_loss_day": 0.15, "max_round_trips_per_token_day": 3})
        self.assertEqual(executor.LIVE_CAPS, {k.replace("grok_", ""): v[0] for k, v in grokauto.LIMITS.items()
                                              if k.startswith("grok_")})

    def test_the_day_summary_line(self):
        self.switch(True)
        self.live_rows(2, reason="momentum scalp")
        self.live_rows(1, reason="copy KOL x", status="closed", sol_in=0.1, sol_back=0.07, closed=int(self.now - 10))
        st = executor.switch_status(self.con, self.now, self.cfg)
        self.assertEqual((st["buys"], st["open"], st["on"]), (3, 2, True))
        line = executor.switch_line(st)
        self.assertIn("PRAVI NOVAC danas: kupnji 3/100, otvoreno 2/10, ostvareno -0,030 SOL (stop -0,5 SOL), "
                      "potrošeno 0,30/11 SOL | po strategiji: momentum_scalp: kupnji 2, otvoreno 2", line)
        self.assertIn("kopiranje: kupnji 1, otvoreno 0, -0,030 SOL", line)
        self.assertIn("pravi_novac_sve UKLJUČEN: stropovi 0.1 SOL po tradeu, najviše 10 otvorenih, 100 kupnji dnevno",
                      run_trade.limits_line(self.con, self.cfg))


# ---------- the hard rules ----------------------------------------------------------------------------------------------

class Hard(SwitchBase):
    def setUp(self):
        super().setUp()
        self.switch(True)

    def test_kill_switch_reserve_and_a_duplicate_token(self):
        open(executor.STOP_FILE, "w").close()
        self.assertEqual(self.gate(), "kill switch (trade/STOP)")
        os.remove(executor.STOP_FILE)
        self.assertIn("bez tvoje rezerve", self.gate(balance=0.12))        # the owner's min_sol_reserve
        self.assertIn("premalo SOL-a", self.gate(balance=0.05))           # the fees themselves (HARD)
        self.live_rows(1)
        dup = self.con.execute("SELECT token FROM positions").fetchone()[0]
        self.assertIn("već postoji otvorena pozicija", self.gate(token=dup))

    def test_the_swap_cost_cap(self):
        # the real swap: Jupiter's own quote says 12 % cost, nothing is signed
        for obj, name, val in ((executor, "swap", REAL_SWAP), (jupiter, "order", FakeJup(cost=12).order)):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        signed = []
        p = mock.patch.object(wallet, "sign", lambda tx: signed.append(tx) or "S")
        p.start()
        self.addCleanup(p.stop)
        r = executor.buy(self.con, self.cfg, tok(3), "C", now=self.now, reason="copy KOL x")
        self.assertEqual(r["status"], "blocked")
        self.assertIn("trošak", r["error"])
        self.assertEqual(signed, [])

    def test_rug_archive_under_30k_the_curve_liquidity_and_no_quote(self):
        from rugfilter import archive
        self.demo(tok(10), "copy KOL a")
        with mock.patch.object(archive, "blocked", lambda *a, **k: frozenset({tok(10)})):
            self.mirror()
        self.assertIn("arhivi rugova", self.pos(tok(10))[2])
        self.demo(tok(11), "copy KOL b", mcap=None)
        self.demo(tok(12), "copy KOL c", mcap=25_000.0)
        self.mirror()
        self.assertIn("MC nepoznat", self.pos(tok(11))[2])
        self.assertIn("ispod 30k", self.pos(tok(12))[2])
        self.quote["row"] = (P, 50_000.0, None, 100_000.0, "SYM", {"src": "jup"})   # Jupiter only: on the curve
        self.demo(tok(13), "copy KOL d")
        self.mirror()
        self.assertIn("pump.fun krivulji", self.pos(tok(13))[2])
        self.quote["row"] = (P, 9_000.0, None, 100_000.0, "SYM", {"m5": 1.0})
        self.demo(tok(14), "copy KOL e")
        self.mirror()
        self.assertIn("likvidnost $9,000 ispod $15k", self.pos(tok(14))[2])
        self.quote["row"] = (P, 50_000.0, None, 20_000.0, "SYM", {"m5": 1.0})          # the live MC under 30k
        self.demo(tok(15), "copy KOL f")
        self.mirror()
        self.assertIn("ispod 30k", self.pos(tok(15))[2])
        self.quote["row"] = None                                                         # DexScreener silent
        self.demo(tok(16), "copy KOL g", age=5)
        self.mirror()
        self.assertIsNone(self.pos(tok(16)))                                             # waits for a quote
        self.now += 30
        self.mirror()
        self.assertIn("nema žive cijene", self.pos(tok(16))[2])
        self.assertEqual(self.swaps, [])
        self.assertTrue(any("odbijeno (tvrdo pravilo)" in x for x in self.lines))

    def test_no_real_position_without_a_server_side_stop(self):
        fid = copy.follow(self.lg, LU, "wallet", "W" * 44, "insajder prije poziva WWWW…", 25, 5, "mirror")
        t = tok(20)
        self.demo(t, "copy wallet insajder prije poziva WWWW…", follow_id=fid, sl=None, age=6)   # "mirror": no SL
        self.mirror()
        self.assertIsNone(self.pos(t))                                     # waits: its stop is not written yet
        self.assertEqual(exitplan.ensure_switch_stops(self.lg, every=0), [t])   # the sweep (dashboard process)
        p = exitplan.active(self.lg, t)
        self.assertTrue(p["client"].startswith(exitplan.SWITCH_SRC))
        self.assertEqual(p["plan"]["stop"], {"kind": "pct", "v": -30.0})   # -min(30, sl_default 60)
        self.mirror()
        self.assertEqual(self.pos(t)[:2], ("open", "live"))
        self.assertTrue(any(x.startswith("PRAVI NOVAC: insider_copy kupuje SYM 0.100 SOL (procjena troška 1.2 %)")
                            for x in self.lines), self.lines)
        t2 = tok(21)   # no stop at all and the wait is over: refused, never bought
        self.demo(t2, "copy KOL bez stopa", sl=None, age=60)
        self.mirror()
        self.assertIn("bez server-side stopa", self.pos(t2)[2])


# ---------- every strategy path, off and on -------------------------------------------------------------------------

class Paths(SwitchBase):
    def test_copy_following_needs_the_demo_proof_off_and_not_on(self):
        fid = copy.follow(self.lg, LU, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-30%")
        self.demo(tok(30), "copy KOL ansem", follow_id=fid)
        self.mirror()
        self.assertEqual(self.pos(tok(30))[0], "blocked")
        self.assertIn("bez dokaza u demu", self.pos(tok(30))[2])
        self.assertEqual(self.swaps, [])
        self.switch(True)
        self.demo(tok(31), "copy KOL ansem", follow_id=fid)
        self.mirror()
        self.assertEqual(self.pos(tok(31))[:2], ("open", "live"))
        self.assertEqual([s["token"] for s in self.swaps], [tok(31)])
        self.assertIn("PRAVI NOVAC: kopiranje kupuje SYM 0.100 SOL (procjena troška 1.2 %)", self.lines)

    def test_momentum_off_the_gate_on_the_real_account(self):
        mtrade.ensure(self.lg)
        tid = self.demo(tok(32), mtrade.SRC, sl=None)
        self.lg.execute("INSERT INTO momentum_trades (user, token, opened_ts, status, trade_id, size_usd, state) "
                        "VALUES (?,?,?,?,?,?,?)", (LU, tok(32), int(self.now), "open", tid, 10.0, "{}"))
        self.lg.commit()
        self.mirror()
        self.assertIn("momentum_scalp: tek 0", self.pos(tok(32))[2])      # off: the 50-trade gate
        self.flag("momentum_scalp", "paper")
        self.assertEqual(mtrade.roles("paper", self.now), ([PU], [LU]))
        self.switch(True)
        self.assertEqual(mtrade.roles("paper", self.now), ([LU, PU], []))
        self.assertEqual(mtrade.roles("live", self.now)[0][0], LU)       # live without the proof: the real account too
        tid = self.demo(tok(33), mtrade.SRC, sl=None)
        self.lg.execute("INSERT INTO momentum_trades (user, token, opened_ts, status, trade_id, size_usd, state) "
                        "VALUES (?,?,?,?,?,?,?)", (LU, tok(33), int(self.now), "open", tid, 10.0, "{}"))
        self.lg.commit()
        self.mirror()
        self.assertEqual(self.pos(tok(33))[:2], ("open", "live"))
        self.assertIn("PRAVI NOVAC: momentum_scalp kupuje SYM 0.100 SOL (procjena troška 1.2 %)", self.lines)

    def test_momentum_entry_on_the_real_account_gets_its_stop(self):
        self.flag("momentum_scalp", "paper")
        self.switch(True)
        sig = {tok(34): {"id": 7, "token": tok(34), "ts": int(self.now), "price": P, "symbol": "MOM",
                         "features": {"ch_m5": 10.0}}}
        mk = lambda toks: {t: (P, 50_000.0, None, 100_000.0, "MOM", {"m5": 10.0}) for t in toks}   # noqa: E731
        lim = {"size_sol": 0.1, "max_sol_per_day": 1.0, "max_open": 5, "dca_token_cap": 0.3}
        with mock.patch.dict(os.environ, {"MOMENTUM_DB": os.path.join(self.tmp.name, "momentum.db")}):
            done = mtrade.run_once(self.lg, mk, int(self.now), sig, lim, 100.0)
        self.assertEqual(sorted(u for u, _ in done), sorted([LU, PU]))
        p = exitplan.active(self.lg, tok(34))
        self.assertTrue(p["client"].startswith(exitplan.SWITCH_SRC))
        self.assertEqual(p["plan"]["accounts"], [LU])

    def test_fast_path_routes(self):
        s = {"decision": "BUY_PAPER", "follow_id": 5, "kind": "wallet_follow"}
        self.assertEqual(fpaper._route(s, "paper"), (PU, False))
        self.assertEqual(fpaper._route(dict(s, decision="BUY_LIVE"), "live"), (LU, True))
        self.assertEqual(fpaper._route(dict(s, follow_id=None), "live"), (PU, False))
        self.assertEqual(fpaper._route(s, "paper", True), (LU, True))     # on: the copy path, no proof
        self.assertEqual(fpaper._route(dict(s, follow_id=None, kind="insider"), "paper", True), (LU, False))
        self.assertIsNone(fpaper._route(s, "shadow", True))               # shadow never trades

    def test_fast_path_entry_on_the_real_account_and_its_plan(self):
        fpaper.ensure(self.lg)
        s = {"id": 41, "token": tok(40), "decision": "BUY_PAPER", "size_sol": 0.05, "price0": P, "kind": "insider",
             "source_label": "X", "source_id": "W" * 44, "sig_ts": int(self.now)}
        mq = (P, 50_000.0, None, 100_000.0, "FST", {"m5": 1.0})
        text, why = fpaper.enter(self.lg, s, LU, False, mq, {"max_open": 5, "max_sol_per_day": 1.0}, 100.0,
                                 int(self.now), path=os.path.join(self.tmp.name, "nofast.db"), switch=True)
        self.assertIsNone(why)
        self.assertIn("pravi račun, pravi_novac_sve", text)
        t = self.lg.execute("SELECT source FROM trades WHERE user=? AND token=?", (LU, tok(40))).fetchone()
        self.assertEqual(t[0], "fast path buy_paper: X")
        self.assertEqual(executor.strategy_of(t[0]), "fast_path")
        p = exitplan.active(self.lg, tok(40))
        self.assertEqual(p["client"], f"{exitplan.SWITCH_SRC} fast #41")
        self.assertTrue(exitplan.execution(LU, exitplan._lots(self.lg, LU, tok(40)), plan=p)["executes"])
        self.switch(True)
        self.mirror()
        self.assertEqual(self.pos(tok(40))[:2], ("open", "live"))

    def test_insider_copy_follows_on_the_real_account_only_with_the_switch(self):
        ec = pc.connect(os.path.join(self.tmp.name, "early.db"))
        self.addCleanup(ec.close)
        p = {"hype_db": os.path.join(self.tmp.name, "none_hype.db"), "league_db": store.DB, "trade_db": settings.DB,
             "early_db": os.path.join(self.tmp.name, "early.db")}
        ins = "I" * 44
        users = lambda: sorted(u for (u,) in self.lg.execute(   # noqa: E731
            "SELECT user FROM follows WHERE kind='wallet' AND target=? AND active=1", (ins,)))
        with mock.patch.object(pc, "copy_set", lambda *a, **k: [(ins, 1.0)]):
            pc.copy_step(ec, p, pc.config(), int(self.now), "paper")
            self.assertEqual(users(), [PU])                                 # off: the demo account only
            self.switch(True)
            pc.copy_step(ec, p, pc.config(), int(self.now) + 60, "paper")
            self.assertEqual(users(), sorted([LU, PU]))                     # on: the real account follows too
            self.switch(False)
            pc.copy_step(ec, p, pc.config(), int(self.now) + 120, "paper")
            self.assertEqual(users(), [PU])                                 # off again: its follow stops
        label = self.lg.execute("SELECT label FROM follows WHERE user=? AND target=?", (LU, ins)).fetchone()[0]
        self.assertEqual(executor.strategy_of(f"copy wallet {label}"), "insider_copy")

    def test_the_copy_rankings_proof_part_is_bypassed_its_pool_rule_is_not(self):
        f = {"kind": "wallet", "target": "W" * 44, "user": LU}
        from wallets import rang
        with mock.patch.object(rang, "gate", lambda k, t: (False, "nije dokazan: 3 zatvorenih tokena u 30 dana")):
            self.assertIn("nije dokazan", copy._rang_gate(f))
            self.switch(True)
            self.assertIsNone(copy._rang_gate(f))
        with mock.patch.object(rang, "gate", lambda k, t: (False, "nije kopirljivo: likvidnost na ulazu")):
            self.assertIn("nije kopirljivo", copy._rang_gate(f))

    def test_proposals_off_the_demo_account_on_the_real_one(self):
        ppath = os.path.join(self.tmp.name, "proposals.db")
        penv = mock.patch.dict(os.environ, {"PROPOSALS_DB": ppath})
        penv.start()
        self.addCleanup(penv.stop)
        ppaper._LAST.clear()
        pview.clear()
        now = int(self.now)

        def seed(token, strat="momentum"):
            st = {strat: {"valid": True, "ev_pct": 5.0, "expires_ts": now + 900, "p_tp": 0.7}}
            r = {"token": token, "symbol": "PRP", "strategy": strat, "sources": [strat], "n_independent": 1,
                 "ev_pct": 5.0, "p_tp": 0.7, "n": 100, "ci90": [0.6, 0.8], "tp_pct": 20.0, "sl_pct": 12.0,
                 "cost_pct": 3.0, "size_sol": 0.15, "why": "Zato.", "risks": [], "strategies": st,
                 "entry_zone": {"mcap_low": 80_000, "mcap_high": 85_000}, "mcap0": 82_000,
                 "exits_mcap": {"tp": [98_400], "tp_share": [1.0], "sl": 72_160},
                 "exit_plan": {"take_profits": [{"at_pct": 20.0, "sell_share": 1.0}], "stop": {"at_pct": -12.0}},
                 "buy": {"tp": "20%", "sl": "-12%", "sol": 0.15, "hold_s": 2700}, "market": {"market_cap_usd": 82_000},
                 "expires_ts": now + 900, "price0": 1.0, "liq0": 60_000}
            con = pstore.connect(ppath)
            pid = pstore.insert(con, r, now)
            con.commit()
            con.close()
            return pid
        mk = lambda toks: {t: (1.0, 60_000.0, None, 82_000.0) for t in toks}   # noqa: E731
        self.flag("proposals", "paper")
        seed(tok(50))
        done = ppaper.run_once(self.lg, mk, now, sol=200.0)
        self.assertEqual([u for u, _ in done], [PU])                      # off: the demo account
        self.switch(True)
        ppaper._LAST.clear()
        seed(tok(51))
        seed(tok(52), strat="grok")                                       # Grok's own numbers: never by themselves
        done = ppaper.run_once(self.lg, mk, now + 30, sol=200.0)
        self.assertEqual([u for u, _ in done], [LU, LU])                  # the demo's earlier one too: no demo now
        self.assertIn("pravi račun, pravi_novac_sve", done[0][1])
        self.assertEqual(sorted(t for (t,) in self.lg.execute("SELECT token FROM trades WHERE user=?", (LU,))),
                         [tok(50), tok(51)])
        t = self.lg.execute("SELECT source FROM trades WHERE user=? AND token=?", (LU, tok(51))).fetchone()
        self.assertEqual(t[0], "prijedlog: momentum")
        self.assertEqual(executor.strategy_of(t[0]), "proposals")
        self.assertIsNone(self.lg.execute("SELECT 1 FROM trades WHERE token=?", (tok(52),)).fetchone())
        p = exitplan.active(self.lg, tok(51))
        self.assertEqual(p["client"].split(" ")[0], exitplan.SWITCH_SRC)
        self.assertEqual(p["plan"]["accounts"], [LU])

    def test_range_lot_mirror_with_its_rounds_stop(self):
        from rangedca import trade as rtrade
        rtrade.ensure(self.lg)
        self.switch(True)
        tid = self.demo(tok(60), "range lot 1", sl=None)
        self.lg.execute("INSERT INTO range_rounds (user, token, opened_ts, status, lot1_id, levels) VALUES (?,?,?,?,?,?)",
                        (LU, tok(60), int(self.now), "open", tid, json.dumps({"stop_px": P * 0.85})))
        self.lg.commit()
        from trade import equity
        with mock.patch.object(equity, "rates", lambda: {"sol_usd": 200.0}):
            self.mirror()
        self.assertEqual(self.pos(tok(60))[:2], ("open", "live"))
        self.assertEqual(self.swaps[-1]["lamports"], 100_000_000)
        self.assertIn("PRAVI NOVAC: range_dca kupuje SYM 0.100 SOL (procjena troška 1.2 %)", self.lines)

    def test_x_call_scalp_grok_simianx_and_the_old_paper_trader_stay_out(self):
        self.switch(True)
        self.assertIn("x_call_scalp", settings.NEVER_LIVE)
        self.assertIn("nikad", settings.live_refusal(self.con, "x_call_scalp"))
        self.assertIn("follow_paper", settings.LOCKED)
        self.assertIn("simianx", settings.LOCKED)
        self.assertFalse(settings.merged(executor.load_config(), self.con)["follow_paper"])
        self.demo(tok(70), grokauto.SRC, age=30)                          # a Grok buy the page never booked
        self.mirror()
        self.assertIn("Grokova kupnja", self.pos(tok(70))[2])
        self.assertEqual(self.swaps, [])

    def test_the_owners_manual_buy_under_the_switch(self):
        self.switch(True)
        tid = self.demo(tok(71), "ručno (pravi trade)", mcap=None)       # his own: no hard re-check, his stake
        cfg = {**self.cfg, "manual_size": {str(tid): 0.05}}
        run_trade.follow_league_once(self.con, cfg, since=0, now=self.now, quiet=True)
        self.assertEqual(self.pos(tok(71))[:2], ("open", "live"))
        self.assertEqual(self.swaps[-1]["lamports"], 50_000_000)
        self.assertFalse(any(x.startswith("PRAVI NOVAC:") for x in self.lines))


# ---------- the exit plans of the switch ---------------------------------------------------------------------------------

class Stops(SwitchBase):
    def test_the_protective_stop_its_level_and_who_gets_one(self):
        self.switch(True)
        self.demo(tok(80), "copy KOL a", sl="-20%")
        self.demo(tok(81), "copy KOL b", sl="-75%")                      # looser than sl_default 60: held at -60
        self.demo(tok(82), "ručno (pravi trade)", sl=None)               # the owner's own: his exits
        self.demo(tok(83), mtrade.SRC, sl=None)
        got = exitplan.ensure_switch_stops(self.lg, every=0)
        self.assertEqual(sorted(got), sorted([tok(80), tok(81), tok(83)]))
        stops = {t: exitplan.active(self.lg, t)["plan"]["stop"]["v"] for t in got}
        self.assertAlmostEqual(stops[tok(80)], -20.0, places=1)
        self.assertEqual((stops[tok(81)], stops[tok(83)]), (-60.0, -30.0))
        self.assertIsNone(exitplan.active(self.lg, tok(82)))
        self.assertEqual(exitplan.ensure_switch_stops(self.lg, every=0), [])   # once: one plan per token

    def test_off_no_sweep_and_the_plan_executes_on_the_real_account_and_outlives_the_switch(self):
        self.demo(tok(84), "copy KOL a", sl=None)
        self.assertEqual(exitplan.ensure_switch_stops(self.lg, every=0), [])   # off: nothing new
        self.switch(True)
        self.assertEqual(exitplan.ensure_switch_stops(self.lg, every=0), [tok(84)])
        lots = exitplan._lots(self.lg, LU, tok(84))
        p = exitplan.active(self.lg, tok(84))
        ex = exitplan.execution(LU, lots, plan=p)
        self.assertEqual((ex["mode"], ex["executes"]), ("live", True))
        self.assertNotIn(tok(84), exitplan.in_force_tokens(self.lg, LU))   # only adds: the lot's own exits stay
        self.switch(False)                                                 # switched off: the stop still holds
        self.flag("exit_plans", "off")
        self.flag(exitplan.LIVE_FLAG, "off")
        market = lambda toks: {t: (P * 0.6, 50_000.0, None, 60_000.0) for t in toks}   # noqa: E731
        with mock.patch.object(exitplan, "fresh_prices", lambda toks, now: {}):
            done = exitplan.run_once(self.lg, market, now=self.now + 5)
        self.assertEqual([(u, t, tr) for u, t, tr, _x in done], [(LU, tok(84), "stop")])
        self.assertEqual(exitplan._lots(self.lg, LU, tok(84)), [])

    def test_a_real_account_copy_gets_its_stop_before_its_ulaz_row(self):
        fid = copy.follow(self.lg, LU, "wallet", "W" * 44, "kit", 25, 5, "mirror")
        f = [x for x in copy.follows(self.lg, LU) if x["id"] == fid][0]
        mk = {t: (P, 50_000.0, None, 100_000.0, "CPY", {"m5": 1.0}) for t in (tok(90), tok(91))}
        ed = mock.patch.object(copy, "entry_data", lambda *a, **k: {"score": None, "runup": None, "call_mcap": None})
        ed.start()
        self.addCleanup(ed.stop)
        copy._enter(self.lg, auto, mk, [(f, tok(90), "buy", int(self.now) - 5)], int(self.now))
        self.assertIsNotNone(self.lg.execute("SELECT 1 FROM trades WHERE user=? AND token=?", (LU, tok(90))).fetchone())
        self.assertIsNone(exitplan.active(self.lg, tok(90)))              # off: the hook adds nothing
        self.switch(True)
        copy._enter(self.lg, auto, mk, [(f, tok(91), "buy", int(self.now) - 5)], int(self.now))
        p = exitplan.active(self.lg, tok(91))
        self.assertTrue(p["client"].startswith(exitplan.SWITCH_SRC))
        note = self.lg.execute("SELECT note FROM copy_log WHERE token=? AND action='ulaz'", (tok(91),)).fetchone()[0]
        self.assertIn("zaštitni stop (pravi_novac_sve)", note)

    def test_without_switch_plans_the_executor_stays_quiet_when_off(self):
        self.flag("exit_plans", "off")
        self.flag(exitplan.LIVE_FLAG, "off")
        self.demo(tok(85), "copy KOL a")
        exitplan.set_plan(self.lg, tok(85), {"stop": {"at_pct": -20}}, 60, client="mcp")
        market = lambda toks: {t: (P * 0.5, 50_000.0, None, 50_000.0) for t in toks}   # noqa: E731
        self.assertEqual(exitplan.run_once(self.lg, market, now=self.now + 5), [])   # as before: off is off


if __name__ == "__main__":
    unittest.main()
