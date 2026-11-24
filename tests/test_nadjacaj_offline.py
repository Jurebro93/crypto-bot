"""11.11. (owner, doslovno): „Ako ja ručno prilikom kupovine postavim drugačiji stop loss nego što je zadan, onda znači da
to želim napraviti samo za tu kupovinu. I tada ručno uvijek nadjačava ono što je zapisano programski.“ Zatim: „I ne samo
za to, nego za količinu kupljenoga. Može izaći upozorenje, box na kojem piše upozorenje, ali ako se složim, ručno uvijek
nadjačava sve ostalo.“ And later: „Mogu se kupovati tokeni ispod 30.000 market capa uz dovoljno dobar razlog.“

  * the owner's own buy over SOFT limits (stake per trade, open positions, the day's loss stop, his per-token cap, the
    swap's cost, his reserve, ...) answers one warning with every reason and writes nothing; with override=1 it goes
    through, one log line, the demo trade marked (settings manual_override) and the real lot too (positions.override);
  * run_trade mirrors that buy into the REAL swap past the same SOFT limits (gate_buy, the swap's cost cap): without
    the mark the swap would be blocked while the page said "poslana";
  * HARD reasons hold with override=1: kill switch, wallet balance, rug, no price; and the Autopilot not live = no
    real money;
  * MC under $30k: SOFT only for the owner's own buy and only with his typed reason (>= 10 characters); Grok's buys,
    approved Grok requests, copies and every automatic buy never;
  * Grok autotrade and an approved request ignore override in the form; nobody but the owner overrides;
  * DCA and buy orders at a market cap carry the limits confirmed when they were set, and only those;
  * the warning box (server and fetch answer) and its signature.
No network.

    python3 -m unittest tests.test_nadjacaj_offline
"""
import io
import json
import os
import sys
import time
import unittest
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, exitplan, store  # noqa: E402
from trade import executor, jupiter, settings, wallet  # noqa: E402
from ui import grokauto, mcpapi, pravitrade  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, LIVE_ROW, MINT  # noqa: E402
from tests.test_trade_offline import CFG, FakeJup  # noqa: E402

LU = settings.LEAGUE_USER
OTHER = MINT[:-4] + "abcd"
REASON = "poznati caller zove, volumen raste, likvidnost drži"


class OBase(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeJup()
        self._jup = (jupiter.order, jupiter.execute, executor.STOP_FILE)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute
        executor.STOP_FILE = os.path.join(self.tmp.name, "STOP")
        for k in ("TRADE_LIVE", "SOLANA_PRIVATE_KEY"):
            os.environ.pop(k, None)
        self.log = ""

    def tearDown(self):
        jupiter.order, jupiter.execute, executor.STOP_FILE = self._jup
        settings._FLAG_CACHE.clear()
        super().tearDown()

    def buy(self, path="/pravi-trade/buy", user="Jure", **kw):
        form = {"token": MINT, "sol": "0,3", "exit": "tpsl", "tp": "30%", "sl": ""}
        form.update(kw)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            loc = unquote(pravitrade.post(path, form, user))
        self.log = out.getvalue()
        return loc

    def nothing_written(self):
        self.assertEqual(store.trades(self.lg, LU, "open"), [])
        raw = settings.raw(self.con)
        self.assertFalse(raw.get("manual_size"))
        self.assertFalse(raw.get("manual_override"))

    def mirror(self, now=None, **cfg):
        c = settings.merged(dict(CFG, sell_check=False, **cfg), self.con)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            run_trade.follow_league_once(self.con, c, since=0, now=now or time.time(), quiet=True)
        self.log = out.getvalue()

    def real(self):
        return self.con.execute("SELECT mode, status, sol_in, reason, override FROM positions ORDER BY id").fetchall()

    def other_open(self, mode="dry"):   # one open position of another token: max_open 1 is reached
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (OTHER, "OTH", int(time.time()) - 60, mode, "open", "copy KOL x",
                                                        0.05, 1000, 1000))
        self.con.commit()

    def lost_today(self, sol=0.2, mode="dry"):   # a closed position today that lost `sol`: the day's loss stop
        now = int(time.time())
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in, sol_back, closed_ts) VALUES "
                         "(?,?,?,?,?,?,?)", (OTHER[:-1] + "z", now - 120, mode, "closed", sol + 0.05, 0.05, now - 60))
        self.con.commit()

    def mc(self, v):
        from ui import league as uleague, prijedlog
        uleague.market = lambda toks: {t: (v / 82_000, 1e6, None, v) for t in toks}
        prijedlog.live_market = lambda toks, fetch=None: {t: {**LIVE_ROW, "price": v / 82_000, "mcap": v} for t in toks}


class SoftWarning(OBase):
    def test_every_soft_reason_at_once_nothing_written(self):
        settings.put(self.con, "max_open", 1)
        settings.put(self.con, "max_loss_day", 0.1)
        settings.put(self.con, "dca_cap_owner", True)
        settings.put(self.con, "owner_token_cap", 0.2)
        self.other_open()
        self.lost_today()
        loc = self.buy()
        self.assertIn("warn=", loc)
        self.assertNotIn("err=", loc)
        self.nothing_written()
        ans = pravitrade.fetch_answer(loc)
        self.assertEqual(ans["title"], "Upozorenje: ova kupnja prelazi tvoje limite")
        w = "\n".join(ans["warn"])
        self.assertIn("ulog 0.3 SOL je iznad tvog limita 0.1 SOL po tradeu", w)
        self.assertIn("1 otvorenih pozicija, najviše 1", w)
        self.assertIn("dnevni gubitak -0.200 SOL, granica -0.1 SOL", w)
        self.assertIn("u tokenu bi bilo 0.300 SOL (otvoreno 0.000 + 0.3), najviše 0.2 SOL po tokenu", w)
        self.assertEqual(len(ans["warn"]), 4)
        self.assertFalse(ans["need_reason"])
        self.assertIn("Kupnja HOPE", ans["what"])
        self.assertIn("čeka potvrdu (upozorenje)", self.log)

    def test_override_buys_logs_marks_and_run_trade_mirrors_past_the_limits(self):
        settings.put(self.con, "max_open", 1)
        self.other_open()
        loc = self.buy(override="1")
        self.assertIn("ok=", loc)
        self.assertIn("Uz tvoje potvrđeno nadjačavanje limita (2)", loc)
        lines = [ln for ln in self.log.splitlines() if "uz potvrđeno nadjačavanje" in ln]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("pravi trade: kupnja HOPE uz potvrđeno nadjačavanje: ulog 0.3 SOL"))
        self.assertIn("1 otvorenih pozicija", lines[0])
        (t,) = store.trades(self.lg, LU, "open")
        raw = settings.raw(self.con)
        self.assertEqual(raw["manual_size"][str(t["id"])], 0.3)
        mark = raw["manual_override"][str(t["id"])]
        self.assertEqual(sorted(mark["keys"]), ["max_open", "stake"])
        self.assertEqual(mark["who"], "Jure")
        self.mirror(max_open=1)
        (_o, (mode, status, sol_in, _why, ov)) = self.real()
        self.assertEqual((mode, status, sol_in), ("dry", "open", 0.3))
        self.assertIn("ulog 0.3 SOL je iznad tvog limita 0.1", ov)
        self.assertIn("uz potvrđeno nadjačavanje", self.log)

    def test_without_the_mark_run_trade_would_block_the_same_buy(self):
        """The case the mark exists for: the page said "poslana", the real swap was blocked by the stake limit."""
        self.assertIn("ok=", self.buy(override="1"))
        settings.put(self.con, "manual_override", {})
        self.mirror()
        ((mode, status, sol_in, why, ov),) = self.real()
        self.assertEqual(status, "blocked")
        self.assertIn("0.3 SOL iznad limita 0.1", why)
        self.assertIsNone(ov)

    def test_within_every_limit_nothing_changes(self):
        loc = self.buy(sol="0,05")
        self.assertIn("ok=", loc)
        self.assertNotIn("nadjačavanje", loc)
        self.assertNotIn("manual_override", settings.raw(self.con))
        self.mirror()
        self.assertEqual([r[:3] for r in self.real()], [("dry", "open", 0.05)])
        self.assertIsNone(self.real()[0][4])

    def test_the_autopilot_off_means_no_real_money_override_or_not(self):
        settings.put(self.con, "on", False)
        self.assertIn("ok=", self.buy(override="1"))
        self.mirror()
        self.assertEqual(self.real()[0][:2], ("dry", "open"))
        self.assertEqual(self.fake.executed, [])   # quoted, never sent


class Hard(OBase):
    def test_kill_switch_refuses_with_override_on_the_page_and_in_run_trade(self):
        open(executor.STOP_FILE, "w").close()
        loc = self.buy(override="1")
        self.assertIn("err=", loc)
        self.assertIn("kill switch", loc)
        self.nothing_written()
        os.remove(executor.STOP_FILE)
        self.assertIn("ok=", self.buy(override="1"))
        open(executor.STOP_FILE, "w").close()
        self.mirror()
        ((_m, status, _s, why, _ov),) = self.real()
        self.assertEqual((status, why), ("blocked", "kill switch (trade/STOP)"))

    def test_rug_stays_hard_even_with_override_and_a_reason(self):
        from rugfilter import collapse
        collapse.check = lambda *a, **k: {"text": "pao 95 %"}
        loc = self.buy(override="1", reason=REASON)
        self.assertIn("err=", loc)
        self.assertIn("rugan", loc)
        self.nothing_written()
        self.assertIn("rug", executor.HARD_RULES)

    def test_no_price_is_hard(self):
        from ui import league as uleague
        uleague.market = lambda toks: {}
        loc = self.buy(override="1")
        self.assertIn("err=", loc)
        self.assertIn("nema cijene", loc)
        self.nothing_written()

    def test_gate_kinds(self):
        cfg = dict(CFG, max_loss_day=0.1, max_open=1, min_sol_reserve=0.05)
        self.other_open("live")
        self.lost_today(mode="live")
        checks = list(executor.buy_checks(self.con, cfg, 0.3, time.time(), True, balance=0.34, token=MINT, add=True,
                                          manual=True))
        self.assertEqual([(k, key) for k, key, _t in checks],
                         [("soft", "stake"), ("soft", "day_loss"), ("soft", "max_open"), ("soft", "reserve")])
        # override: only with manual; a balance under the stake + fees + selling fees is HARD
        g = lambda **k: executor.gate_buy(self.con, cfg, 0.3, time.time(), True, token=MINT, add=True, **k)  # noqa
        self.assertIsNone(g(balance=0.34, manual=True, override=True))
        self.assertIn("iznad limita", g(balance=0.34, manual=True))
        self.assertIn("iznad limita", g(balance=0.34, manual=False, override=True))   # never for an automatic buy
        self.assertIn("premalo SOL-a", g(balance=0.2, manual=True, override=True))
        open(executor.STOP_FILE, "w").close()
        self.assertEqual(g(balance=9, manual=True, override=True), "kill switch (trade/STOP)")

    def test_sell_check_cost_lines_soft_honeypot_hard(self):
        passed = []
        with mock.patch.object(jupiter, "order", lambda i, o, a, taker=None, route="v2": {
                "outAmount": str(a * 1000) if i == jupiter.SOL else str(int(a / 1000 * 0.8))}):
            self.assertIn("gubi 20.0%", executor.sell_check(MINT, 0.1, 6))
            self.assertIsNone(executor.sell_check(MINT, 0.1, 6, override=passed))
        self.assertIn("gubi 20.0%", passed[0])
        with mock.patch.object(jupiter, "order", lambda i, o, a, taker=None, route="v2": {
                "outAmount": str(a * 1000) if i == jupiter.SOL else "0"}):
            self.assertIn("honeypot", executor.sell_check(MINT, 0.1, 6, override=[]))


class Live(OBase):
    """The real account: switch on, TRADE_LIVE=1, a key (all faked): the overridden buy becomes a SENT swap."""

    def setUp(self):
        super().setUp()
        self._w = (wallet.sol_balance, wallet.sign, wallet.address, wallet.can_sign, wallet.token_raw_balance)
        self.bal = {"sol": 5.0}
        wallet.sol_balance = lambda addr: self.bal["sol"]
        wallet.sign = lambda tx, kp=None: "SIGNED"
        wallet.address = lambda: "ME"
        wallet.can_sign = lambda: True
        wallet.token_raw_balance = lambda owner, mint: 0
        os.environ["TRADE_LIVE"] = "1"
        settings.put(self.con, "on", True)
        self.fake.cost = 8.0   # the quote costs 8 %: over max_cost_pct 6 (a SOFT limit too)

        def execute(signed, rid, route="v2"):   # landed; the amounts come from the quote
            self.fake.executed.append(rid)
            return {"status": "Success", "signature": "SIG", "code": 0}
        jupiter.execute = execute

    def tearDown(self):
        (wallet.sol_balance, wallet.sign, wallet.address, wallet.can_sign, wallet.token_raw_balance) = self._w
        os.environ.pop("TRADE_LIVE", None)
        super().tearDown()

    def test_the_overridden_buy_is_a_real_swap_past_stake_and_cost(self):
        self.assertIn("warn=", self.buy())
        self.nothing_written()
        self.assertIn("ok=", self.buy(override="1"))
        self.mirror(use_pump=False)
        ((mode, status, sol_in, _why, ov),) = self.real()
        self.assertEqual((mode, status, sol_in), ("live", "open", 0.3))
        self.assertTrue(self.fake.executed)                      # signed and sent
        self.assertIn("ulog 0.3 SOL je iznad tvog limita 0.1", ov)
        self.assertIn("LIVE KUPNJA HOPE 0.300 SOL", self.log)
        self.assertIn("uz potvrđeno nadjačavanje: 0.3 SOL iznad limita 0.1; trošak 8.0% > 6%", self.log)

    def test_without_the_mark_the_real_swap_is_blocked(self):
        self.assertIn("ok=", self.buy(override="1"))
        settings.put(self.con, "manual_override", {})
        self.mirror(use_pump=False)
        self.assertEqual(self.real()[0][1], "blocked")
        self.assertEqual(self.fake.executed, [])

    def test_too_little_sol_is_hard_on_the_page_and_in_run_trade(self):
        self.bal["sol"] = 0.1
        loc = self.buy(override="1")
        self.assertIn("err=", loc)
        self.assertIn("premalo SOL-a", loc)
        self.nothing_written()
        self.bal["sol"] = 5.0
        self.assertIn("ok=", self.buy(override="1"))
        self.bal["sol"] = 0.1                                       # spent elsewhere before the mirror
        self.mirror(use_pump=False)
        ((_m, status, _s, why, _ov),) = self.real()
        self.assertEqual(status, "blocked")
        self.assertIn("premalo SOL-a", why)
        self.assertEqual(self.fake.executed, [])


class Under30k(OBase):
    def setUp(self):
        super().setUp()
        self.mc(20_000.0)

    def test_needs_the_warning_and_a_reason(self):
        loc = self.buy(sol="0,05")
        self.assertIn("warn=", loc)
        ans = pravitrade.fetch_answer(loc)
        self.assertTrue(ans["need_reason"])
        self.assertEqual(ans["reason_min"], 10)
        self.assertIn("MC $20,000 je ispod 30k", ans["warn"][0])
        self.nothing_written()
        for bad in ({}, {"reason": "kratko"}):                 # no reason / under 10 characters: the warning again
            loc = self.buy(sol="0,05", override="1", **bad)
            self.assertIn("warn=", loc)
            self.assertIn("Upiši razlog", pravitrade.fetch_answer(loc)["note"])
            self.nothing_written()
        loc = self.buy(sol="0,05", override="1", reason=REASON)
        self.assertIn("ok=", loc)
        self.assertIn(f"pravi trade: kupnja HOPE ispod 30k MC ($20,000) uz potvrđeno nadjačavanje, razlog: {REASON}",
                      self.log)
        (t,) = store.trades(self.lg, LU, "open")
        mark = settings.raw(self.con)["manual_override"][str(t["id"])]
        self.assertEqual((mark["keys"], mark["reason"], mark["mc"]), (["mc30k"], REASON, 20_000.0))
        self.mirror()
        ((_m, status, sol_in, _why, ov),) = self.real()
        self.assertEqual((status, sol_in), ("open", 0.05))
        self.assertIn(f"razlog: {REASON}", ov)                      # on the real lot: Povijest shows it
        self.con.execute("UPDATE positions SET status='closed', closed_ts=?, sol_back=0.06", (int(time.time()),))
        self.con.commit()
        from ui import apterm
        hist = apterm.povijest_html(self.con, settings.merged(dict(CFG), self.con), True, time.time())
        self.assertIn("nadjačano: MC $20,000 je ispod 30k", hist)

    def test_run_trade_needs_the_mc30k_mark_with_its_reason(self):
        self.assertIn("ok=", self.buy(sol="0,05", override="1", reason=REASON))
        (t,) = store.trades(self.lg, LU, "open")
        marks = settings.raw(self.con)["manual_override"]
        marks[str(t["id"])]["reason"] = ""
        settings.put(self.con, "manual_override", marks)
        self.mirror()
        self.assertIn("ispod 30k", self.real()[0][3])

    def test_putting_the_rule_back_into_hard_rules_refuses_everywhere(self):
        with mock.patch.object(executor, "HARD_RULES", frozenset({"mc30k", "rug"})):
            loc = self.buy(sol="0,05", override="1", reason=REASON)
            self.assertIn("err=", loc)
            self.assertIn("ispod 30k", loc)
        self.assertIn("ok=", self.buy(sol="0,05", override="1", reason=REASON))
        with mock.patch.object(executor, "HARD_RULES", frozenset({"mc30k", "rug"})):
            self.mirror()
        self.assertIn("ispod 30k", self.real()[0][3])

    def test_copies_grok_and_automatic_buys_never_under_30k(self):
        now = int(time.time())
        rows = {}
        for src in ("copy KOL ansem", grokauto.SRC, exitplan.APPROVED_SRC, "range lot 1"):
            tid = store.buy(self.lg, LU, MINT, "HOPE", 25, 20_000 / 82_000, 1e6, src, None, 20_000.0, allow_open=True)
            self.lg.execute("UPDATE trades SET opened_ts=?, follow_id=? WHERE id=?",
                            (now - 10, 7 if src.startswith("copy") else None, tid))
            rows[tid] = src
        self.lg.commit()
        # forged marks (the page never writes them for these): ignored by run_trade all the same
        settings.put(self.con, "manual_size", {str(t): 0.05 for t, s in rows.items() if not s.startswith("range")})
        settings.put(self.con, "manual_override", {str(t): {"why": ["x"], "keys": ["mc30k", "stake"], "reason": REASON}
                                                   for t in rows})
        self.mirror(now=now)
        got = self.con.execute("SELECT league_id, status, reason FROM positions").fetchall()
        self.assertEqual(len(got), 4)
        for lid, status, why in got:
            self.assertEqual(status, "blocked", rows[lid])
            self.assertIn("ispod 30k", why, rows[lid])

    def test_grok_buys_on_the_page_never_under_30k(self):
        for src in (grokauto.SRC, exitplan.APPROVED_SRC):
            with self.assertRaises(ValueError) as e, mock.patch("sys.stdout", io.StringIO()):
                pravitrade._post_buy(self.lg, self.con, {"token": MINT, "sol": "0.05", "exit": "tpsl", "tp": "30%",
                                                         "sl": "", "override": "1", "reason": REASON}, "jure", src=src)
            self.assertNotIsInstance(e.exception, pravitrade.SoftLimits)
            self.assertIn("ispod 30k", str(e.exception))
        self.nothing_written()


class GrokAndOthers(OBase):
    """Grok autotrade and an approved Grok request: override in the form (or the MCP body) changes nothing."""

    def setUp(self):
        super().setUp()
        good = (1.0, 30_000.0, None, 82_000.0, "HOPE", {"src": "dex"})
        for p in (mock.patch.object(copy, "market", lambda toks: {t: good for t in toks}),
                  mock.patch.object(copy, "_rugged", lambda *a: None),
                  mock.patch.object(copy, "_concentration", lambda t: (None, "nepoznato")),
                  mock.patch.object(grokauto, "TX_WAIT_S", 0.0),
                  mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})):
            p.start()
            self.addCleanup(p.stop)
        settings.put(self.con, "max_open", 1)
        self.other_open()

    def test_grok_autotrade_keeps_the_owners_limits_hard(self):
        self.assertIn("ok=", self.buy(path="/pravi-trade/grokon"))
        with mock.patch("sys.stdout", io.StringIO()):
            code, out = mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05, "require_approval": False,
                                              "reason": "x", "override": "1"})
        self.assertEqual(out["status"], "rejected")
        self.assertIn("1 otvorenih pozicija", out["reason"])
        self.nothing_written()
        with self.assertRaises(ValueError) as e, mock.patch("sys.stdout", io.StringIO()):
            pravitrade._post_buy(self.lg, self.con, {"token": MINT, "sol": "0.3", "exit": "tpsl", "tp": "30%", "sl": "",
                                                     "override": "1"}, settings.owner(), src=grokauto.SRC)
        self.assertNotIsInstance(e.exception, pravitrade.SoftLimits)
        self.assertIn("iznad limita", str(e.exception))
        self.nothing_written()

    def test_an_approved_request_with_override_in_the_form_is_refused(self):
        with mock.patch("sys.stdout", io.StringIO()):
            code, out = mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05, "reason": "x"})
        self.assertEqual(code, 202)
        loc = self.buy(path="/pravi-trade/mcpok", id=out["id"], override="1", reason=REASON)
        self.assertIn("err=", loc)
        self.assertIn("1 otvorenih pozicija", loc)
        self.nothing_written()

    def test_nobody_but_the_owner_overrides(self):
        loc = self.buy(user="netko", override="1")
        self.assertIn("err=", loc)
        self.assertIn("samo vlasnik", loc)
        self.nothing_written()
        with self.assertRaises(ValueError) as e, mock.patch("sys.stdout", io.StringIO()):
            pravitrade._post_buy(self.lg, self.con, {"token": MINT, "sol": "0.3", "exit": "tpsl", "tp": "30%", "sl": "",
                                                     "override": "1"}, "netko")
        self.assertNotIsInstance(e.exception, pravitrade.SoftLimits)
        self.nothing_written()
        self.assertFalse(pravitrade._can_override("netko"))
        self.assertTrue(pravitrade._can_override("Jure", "ručno: prijedlog range"))
        self.assertFalse(pravitrade._can_override("Jure", exitplan.APPROVED_SRC))

    def test_no_mcp_tool_takes_override(self):
        for t in mcpapi.TOOLS:
            props = (t.get("inputSchema") or {}).get("properties") or {}
            self.assertNotIn("override", props, t["name"])
            self.assertNotIn("reason_30k", props, t["name"])


class Orders(OBase):
    """DCA and buy orders at a market cap: the warning when they are set, the confirmed limits (only those) when
    they buy."""

    def _position(self):
        self.assertIn("ok=", self.buy(sol="0,05"))
        (t,) = store.trades(self.lg, LU, "open")
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                         "qty_raw, qty_left) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (t["id"], MINT, "HOPE", int(time.time()) - 60, "dry", "open", "ručno (pravi trade)", 0.05,
                          1000, 1000))
        self.con.commit()

    def test_dca_over_the_stake_limit(self):
        self._position()
        loc = self.buy(path="/pravi-trade/dca", lvl="$50k", sol="0,3")
        self.assertIn("warn=", loc)
        self.assertEqual(pravitrade.fetch_answer(loc)["what"], "DCA dokup HOPE (So11…1117) za 0,3 SOL kad MC padne na $50k")
        self.assertFalse(settings.raw(self.con).get("dca_orders"))
        loc = self.buy(path="/pravi-trade/dca", lvl="$50k", sol="0,3", override="1")
        self.assertIn("ok=", loc)
        (o,) = settings.raw(self.con)["dca_orders"]
        self.assertEqual(o["override"], ["stake"])
        with mock.patch("sys.stdout", io.StringIO()) as out:
            done = pravitrade.dca_once(self.con, live_fn=lambda t: {MINT: {"mcap": 49_000.0}})
        self.assertIn("dokupljeno 0.3 SOL", done[0][1])
        self.assertIn("pravi trade: kupnja HOPE uz potvrđeno nadjačavanje: ulog 0.3 SOL", out.getvalue())
        lots = store.trades(self.lg, LU, "open")
        self.assertEqual(len(lots), 2)
        newest = max(t["id"] for t in lots)
        self.assertEqual(settings.raw(self.con)["manual_override"][str(newest)]["keys"], ["stake"])

    def test_dca_a_new_limit_at_the_level_is_not_overridden(self):
        self._position()
        self.assertIn("ok=", self.buy(path="/pravi-trade/dca", lvl="$50k", sol="0,3", override="1"))
        settings.put(self.con, "max_loss_day", 0.1)
        self.lost_today()                                         # the day's loss stop since he set it
        with mock.patch("sys.stdout", io.StringIO()):
            done = pravitrade.dca_once(self.con, live_fn=lambda t: {MINT: {"mcap": 49_000.0}})
        self.assertIn("nije prošao: nalog nije potvrđen za ovaj limit: dnevni gubitak", done[0][1])
        self.assertEqual(len(store.trades(self.lg, LU, "open")), 1)

    def test_buy_order_at_a_market_cap_under_30k_with_a_reason(self):
        self.mc(90_000.0)
        loc = self.buy(at="$25k", sol="0,05")
        self.assertIn("warn=", loc)
        self.assertTrue(pravitrade.fetch_answer(loc)["need_reason"])
        self.assertIn("ok=", self.buy(at="$25k", sol="0,3", override="1", reason=REASON))
        (o,) = settings.raw(self.con)["buy_orders"]
        self.assertEqual((o["override"], o["reason"]), (["mc30k", "stake"], REASON))
        self.mc(24_000.0)
        with mock.patch("sys.stdout", io.StringIO()) as out:
            done = pravitrade.limit_once(self.con, live_fn=lambda t: {MINT: {"mcap": 24_000.0}})
        self.assertIn("kupljeno 0.3 SOL", done[0][1])
        self.assertIn(f"ispod 30k MC ($24,000) uz potvrđeno nadjačavanje, razlog: {REASON}", out.getvalue())
        self.mirror()
        ((_m, status, sol_in, _w, ov),) = self.real()
        self.assertEqual((status, sol_in), ("open", 0.3))
        self.assertIn(REASON, ov)


class Box(OBase):
    def test_the_box_on_the_page_its_form_and_a_foreign_link(self):
        settings.put(self.con, "max_open", 1)
        self.other_open()
        loc = self.buy(chart_mint=MINT)
        qs = {"warn": loc.split("warn=", 1)[1].split("#")[0]}
        html = pravitrade.warn_box(qs, "Jure")
        self.assertIn("Upozorenje: ova kupnja prelazi tvoje limite", html)
        self.assertIn("<li>1 otvorenih pozicija, najviše 1 (Pravila → Limiti)</li>", html)
        self.assertIn('action="/pravi-trade/buy"', html)
        self.assertIn("<input type=hidden name=override value=1>", html)
        self.assertIn('<input type=hidden name="sol" value="0,3">', html)
        self.assertIn('<input type=hidden name="chart_mint"', html)
        self.assertIn(">Kupi svejedno</button>", html)
        self.assertIn(">Odustani</a>", html)
        self.assertIn("confirm(", html)
        self.assertNotIn("textarea", html)
        self.assertEqual(pravitrade.warn_box(qs, "netko"), "")
        bad = {"warn": qs["warn"][:-3] + "abc"}
        self.assertNotIn("override", pravitrade.warn_box(bad, "Jure"))
        self.assertIn("isteklo", pravitrade.warn_box(bad, "Jure"))
        with mock.patch.object(time, "time", lambda: 10 ** 10):
            self.assertIsNone(pravitrade.warn_data(qs["warn"]))
        _, page = pravitrade.page(qs, "Jure")
        self.assertIn("id=ap-warn", page)

    def test_the_box_asks_for_the_reason_under_30k(self):
        self.mc(20_000.0)
        loc = self.buy(sol="0,05")
        html = pravitrade.warn_box({"warn": loc.split("warn=", 1)[1].split("#")[0]}, "Jure")
        self.assertIn("Razlog kupnje ispod 30k MC", html)
        self.assertIn("<textarea name=reason required minlength=10", html)
        self.assertIn("b.disabled=r.value.trim().length<n", html)   # "Kupi svejedno" waits for the reason


if __name__ == "__main__":
    unittest.main()
