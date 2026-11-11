"""10.11. ~21:30 (Jure): Grok autotrade behind grok_autotrade (default off, the owner switches it on). execute_trade
with require_approval=false executes at once only while it is on; Grok's own limits (per trade, per day, open
positions, day loss -> paused until midnight Zagreb); a fresh rug / liquidity check before every buy; sells of any
open position; the kill switch; client grok_auto in the log; the page block; MCP answers; Grok cannot switch it on.

    python3 -m unittest tests.test_grok_autotrade_offline
"""
import json
import os
import sys
import time
import unittest
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store  # noqa: E402
from trade import settings  # noqa: E402
from ui import grokauto, mcpapi, pravitrade  # noqa: E402
from tests.test_pozicije_izlaz_offline import Base, MINT  # noqa: E402

M2 = MINT[:-1] + "8"
M3 = MINT[:-1] + "9"
M4 = MINT[:-2] + "AB"
GOOD = (1.0, 30_000.0, None, 82_000.0, "HOPE", {"src": "dex"})


class Grok(Base):
    def setUp(self):
        super().setUp()
        self.mk = {}
        p = [mock.patch.object(copy, "market", lambda toks: {t: self.mk.get(t, GOOD) for t in toks}),
             mock.patch.object(copy, "_rugged", lambda *a: None),
             mock.patch.object(copy, "_concentration", lambda t: (None, "nepoznato")),
             mock.patch.object(grokauto, "TX_WAIT_S", 0.0),
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})]
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        settings.put(self.con, "max_sol_per_trade", 0.5)
        settings.put(self.con, "size_sol", 0.1)

    def ask(self, tok, amount, side="buy", reason="Grok: 3 calleri"):
        return mcpapi.trade_request({"token": tok, "side": side, "amount": amount, "require_approval": False,
                                     "reason": reason})

    def test_off_by_default_and_grok_cannot_switch_it_on(self):
        code, out = self.ask(MINT, 0.05)
        self.assertEqual((code, out["status"]), (403, "rejected"))
        self.assertIn("off", out["reason"])
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])
        # no MCP tool turns it on or changes its limits
        # (10.11.: the read-only work queue get_grok_tasks is allowed; no tool that writes may touch it)
        names = [t["name"] for t in mcpapi.TOOLS if not (t.get("annotations") or {}).get("readOnlyHint")]
        self.assertFalse([n for n in names if "grok" in n or "autotrade" in n])
        self.assertIn("err=", pravitrade.post("/pravi-trade/grokon", {}, "netko"))   # only the owner
        self.assertFalse(grokauto.state(self.con)["on"])
        # with approval it queues as before
        self.assertEqual(mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05})[0], 202)

    def test_buy_executes_logs_and_respects_per_trade_day_and_open_limits(self):
        self.assertIn("ok=", self.post("/pravi-trade/grokon", {}))
        code, out = self.ask(MINT, 0.1)
        self.assertEqual((code, out["status"], out["side"]), (200, "executed", "buy"))
        t = store.trades(self.lg, settings.LEAGUE_USER, "open")
        self.assertEqual(len(t), 1)
        src = self.lg.execute("SELECT source FROM trades WHERE id=?", (out["league_trade_id"],)).fetchone()[0]
        self.assertEqual(src, "Grok auto (MCP)")
        self.assertEqual(out["remaining_today"]["sol_today"], 0.2)
        log = grokauto.log_rows(self.con)
        self.assertEqual((log[0]["client"], log[0]["status"], log[0]["reason"]), ("grok_auto", "executed", "Grok: 3 calleri"))
        code, out = self.ask(M2, 0.2)                                                    # over the per-trade limit
        self.assertEqual((code, out["status"]), (400, "rejected"))
        self.assertIn("grok_max_sol_per_trade", out["reason"])
        self.assertEqual(self.ask(M2, 0.1)[1]["status"], "executed")
        self.assertEqual(self.ask(M3, 0.1)[1]["status"], "executed")                   # 0.3 SOL today
        code, out = self.ask(M4, 0.05)
        self.assertEqual(out["status"], "rejected")
        self.assertIn("grok_max_sol_per_day", out["reason"])
        settings.put(self.con, "grok_max_sol_per_day", 1.0)
        code, out = self.ask(M4, 0.05)                                                   # 3 open: the 4th token
        self.assertIn("grok_max_open", out["reason"])

    def test_fresh_safety_check_rejects_with_the_reason(self):
        self.post("/pravi-trade/grokon", {})
        self.mk[MINT] = (1.0, 2_000.0, None, 82_000.0, "X", {"src": "dex"})
        self.assertIn("premala likvidnost", self.ask(MINT, 0.05)[1]["reason"])
        self.mk[MINT] = (1.0, 0, None, 0, "X", {"src": "jup"})
        self.assertIn("bondani", self.ask(MINT, 0.05)[1]["reason"])
        self.mk[MINT] = GOOD
        with mock.patch.object(copy, "_rugged", lambda *a: {"text": "pao 95 %"}):
            self.assertIn("rugan", self.ask(MINT, 0.05)[1]["reason"])
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])

    def test_sell_any_open_position_any_share_even_when_paused(self):
        self.post("/pravi-trade/grokon", {})
        for _ in range(2):
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                             (MINT, int(time.time()), "dry", "open", 0.5))
        self.con.commit()
        s = dict(settings.raw(self.con)[grokauto.STATE_KEY], paused_until=int(time.time()) + 3600, pause_reason="test")
        settings.put(self.con, grokauto.STATE_KEY, s)
        code, out = self.ask(MINT, 1.0, side="sell")
        self.assertEqual((code, out["status"]), (200, "executed"))
        self.assertEqual(sorted(settings.raw(self.con)["sell_req"].values()), [1.0, 1.0])
        self.assertEqual(self.ask(MINT, 0.05)[1]["status"], "rejected")                 # buys wait for midnight

    def test_day_loss_pauses_until_midnight_and_the_kill_switch(self):
        self.post("/pravi-trade/grokon", {})
        code, out = self.ask(MINT, 0.1)
        lid = out["league_trade_id"]
        now = time.time()
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in, sol_back, closed_ts, league_id) "
                         "VALUES (?,?,?,?,?,?,?,?)", (MINT, int(now) - 60, "dry", "closed", 0.3, 0.14, int(now), lid))
        self.con.commit()
        self.assertTrue(grokauto.maybe_pause(self.con, now))                              # -0.16 <= -0.15
        st = grokauto.state(self.con, now)
        self.assertEqual((st["on"], st["active"]), (True, False))
        self.assertGreater(st["paused_until"], now)
        self.assertLessEqual(st["paused_until"] - now, 25 * 3600)
        self.assertIn("paused", self.ask(M2, 0.05)[1]["reason"])
        self.assertTrue(grokauto.state(self.con, st["paused_until"] + 1)["active"])       # next day again
        # kill switch
        self.assertIn("ok=", self.post("/pravi-trade/grokoff", {}))
        self.assertEqual(self.ask(M2, 0.05)[0], 403)
        self.assertEqual(grokauto.log_rows(self.con)[0]["status"], "off")

    def test_limits_are_the_owners_and_mcp_shows_state_and_what_is_left(self):
        loc = self.post("/pravi-trade/groklimits", {"grok_max_sol_per_trade": "0,05", "grok_max_open": "2"})
        self.assertIn("ok=", loc)
        self.assertIn("err=", self.post("/pravi-trade/groklimits", {"grok_max_sol_per_day": "50"}))
        lim = grokauto.limits(self.con)
        self.assertEqual((lim["grok_max_sol_per_trade"], lim["grok_max_open"]), (0.05, 2))
        port = mcpapi.portfolio()
        self.assertEqual(port["grok_autotrade"]["on"], False)
        self.assertEqual(port["grok_autotrade"]["remaining_today"]["open_slots"], 2)
        from ui import mcpdata
        with mock.patch.object(mcpdata, "_ro", side_effect=lambda n: settings.connect() if n == "trade" else None):
            cfg = mcpdata.scoring_config()
        self.assertEqual(cfg["grok_autotrade"]["limits"]["grok_max_open"], 2)

    def test_page_block_with_label_and_kill_button_only_while_on(self):
        _, body = pravitrade.page({}, "Jure")
        self.assertNotIn("Ugasi Grok autotrade", body)
        self.assertIn("Uključi Grok autotrade", body)
        self.post("/pravi-trade/grokon", {})
        self.ask(MINT, 0.1)
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Ugasi Grok autotrade", body)
        self.assertIn("<span class=ap-tag>Grok auto</span> kupnja", body)
        self.assertLess(body.index("id=pozicije"), body.index("id=grok-auto"))
        self.assertNotIn("Ugasi Grok autotrade", pravitrade.page({}, "netko")[1])
        self.assertEqual(pravitrade._who("Grok auto (MCP)"), "Grok auto")

    def test_telegram_notice_after_an_autotrade_when_configured(self):
        self.post("/pravi-trade/grokon", {})
        sent = []
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}), \
                mock.patch.object(grokauto.urllib.request, "urlopen", lambda url, data, timeout: sent.append(data) or
                                  type("R", (), {"read": lambda self: b""})()), \
                mock.patch.object(grokauto.threading, "Thread",
                                  lambda target, daemon: type("T", (), {"start": lambda self: target()})()):
            self.ask(MINT, 0.1)
        self.assertTrue(sent and b"KUPNJA" in unquote(sent[0].decode()).encode())


if __name__ == "__main__":
    unittest.main()
