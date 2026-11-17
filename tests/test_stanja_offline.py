"""stanja/: the registry of state machines, the drift check against the source, the board of the state now (17.11.).

Offline: a temporary trade.db; no network; nothing of the real databases is read.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stanja import ploca, provjera, registar  # noqa: E402
from trade import executor, settings  # noqa: E402


class Registry(unittest.TestCase):
    def test_keys_are_unique_and_every_machine_is_complete(self):
        keys = [m.key for m in registar.MACHINES]
        self.assertEqual(len(keys), len(set(keys)))
        for m in registar.MACHINES:
            self.assertIn(m.area, registar.AREAS, m.key)
            self.assertTrue(m.title and m.store and m.states, m.key)
            for a, b, _what in m.moves:
                for st in (a, b):
                    self.assertTrue(st in ("*", "-") or st in m.states, f"{m.key}: prijelaz spominje nepoznato stanje {st}")
            for lab in m.states.values():
                self.assertTrue(lab and lab == lab.strip(), m.key)

    def test_the_registry_matches_the_code(self):
        """A literal the code writes for a declared state column must be declared; a declared state must still be
        mentioned by the code. When this fails: declare the new state in stanja/registar.py (with its Croatian word
        and what moves it), or remove the one the code no longer has."""
        self.assertEqual(provjera.drift(registar.MACHINES), [])

    def test_a_new_undeclared_state_is_caught(self):
        src = os.path.join(tempfile.mkdtemp(), "x.py")
        with open(src, "w", encoding="utf-8") as f:
            f.write('con.execute("UPDATE t SET status=\'open\' WHERE status IN (\'pending\', \'zombie\')")\n'
                    'if r["status"] == "closed":\n    pass\n')
        self.assertEqual(provjera.found(src, "status"), {"open", "pending", "zombie", "closed"})
        m = registar.M("t", "T", "novac", "t.status", {"open": "o", "closed": "z", "pending": "p", "gone": "g"},
                       scan=((src, "status"),))
        self.assertEqual(provjera.drift([m]), [("t", "mrtvo", "gone", src), ("t", "nedeklarirano", "zombie", src)])

    def test_machines_that_share_a_column_are_checked_together(self):
        pos, order = registar.BY_KEY["position"], registar.BY_KEY["order"]
        both = set(pos.states) | set(order.states) | order.extra
        self.assertTrue(provjera.found("trade/executor.py", "status") <= both)

    def test_labels_and_exit_words(self):
        self.assertEqual(registar.label("position", "pending"), "kupnja u tijeku")
        self.assertEqual(registar.label("position", "nema"), "nema")
        self.assertEqual(registar.label("nema_stroja", "x"), "x")
        self.assertEqual(registar.exit_key("veliki", "trail"), "trailing")
        self.assertEqual(registar.exit_key("momentum", "trailing"), "trailing")
        self.assertEqual(registar.exit_key("veliki", "be"), registar.exit_key("rangedca", "breakeven"))
        self.assertEqual(registar.exit_key("rangedca", "odustajanje: raspon probijen"), "gave_up")
        self.assertEqual(registar.exit_key("konsenzus", "sl"), "stop")
        self.assertEqual(registar.exit_key("nepoznato", None), "other")
        for mod, d in registar.EXIT_MAP.items():
            self.assertTrue(set(d.values()) <= set(registar.EXITS), mod)

    def test_veliki_exit_literals_are_all_mapped(self):
        from veliki import rule
        self.assertTrue(set(rule.REASON_HR) <= set(registar.EXIT_MAP["veliki"]) | {"kraj"},
                        set(rule.REASON_HR) - set(registar.EXIT_MAP["veliki"]))

    def test_describe(self):
        d = registar.describe(key="grok_autotrade")
        self.assertEqual(d["count"], 1)
        self.assertEqual([s["state"] for s in d["machines"][0]["states"]], ["<off>", "<on>", "<paused>"])
        self.assertEqual(registar.describe(area="novac")["count"], sum(1 for m in registar.MACHINES if m.area == "novac"))
        json.dumps(registar.describe())


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "trade.db")
        self.con = executor.connect(self.db)
        self.con.execute(settings.SCHEMA)
        self.now = 1_800_000_000

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def put(self, k, v, ts=None, who="Jure"):
        self.con.execute("INSERT OR REPLACE INTO settings VALUES (?,?,?,?)", (k, json.dumps(v), ts or self.now - 3600, who))
        self.con.commit()

    def board(self, env=None):
        with mock.patch("veliki.makro.current", return_value=None), \
                mock.patch("veliki.live.btc_state", return_value={"state": "normalno", "why": "mirno", "known": True,
                                                                  "last_end": self.now - 600}):
            return {r["key"]: r for r in ploca.now(self.now, trade_db=self.db, env=env or {})}

    def test_everything_off_by_default(self):
        b = self.board()
        self.assertEqual(b["autopilot_switch"]["state"], "<off>")
        self.assertEqual(b["grok_autotrade"]["state"], "<off>")
        self.assertEqual(b["mcp_access"]["state"], "<off>")
        self.assertEqual(b["exit_plans_pause"]["state"], "<running>")
        self.assertEqual(b["sell_all"]["state"], "<idle>")
        self.assertEqual(b["bot_heartbeat"]["state"], "<never>")
        self.assertEqual(b["day_loss_stop"]["state"], "<allowed>")
        self.assertEqual(b["btc_regime"]["label"], "normalno")
        self.assertEqual(b["macro_regime"]["state"], "?")
        for r in b.values():
            self.assertTrue(r["label"] and r["title"], r["key"])

    def test_grok_autotrade_says_who_and_since_and_the_pause(self):
        self.put("grok_autotrade", {"on": False, "since": self.now - 200000, "who": "Jure", "paused_until": None})
        r = self.board()["grok_autotrade"]
        self.assertEqual((r["state"], r["label"], r["since"], r["who"]), ("<off>", "ugašen", self.now - 200000, "Jure"))
        self.put("grok_autotrade", {"on": True, "since": self.now - 50, "who": "Jure", "paused_until": self.now + 900,
                                    "pause_reason": "dnevni gubitak"})
        self.put("grok_max_sol_per_day", 1)
        r = self.board()["grok_autotrade"]
        self.assertEqual(r["state"], "<paused>")
        self.assertIn("dnevni gubitak", r["detail"])
        self.assertIn("max_sol_per_day 1", r["detail"])
        self.put("grok_autotrade", {"on": True, "since": self.now - 50, "who": "Jure", "paused_until": self.now - 5})
        self.assertEqual(self.board()["grok_autotrade"]["state"], "<on>")   # an expired pause is no pause

    def test_the_mcp_key_is_never_shown_only_when_it_was_made(self):
        self.put("mcp_key", "ms_tajna_vrijednost", ts=self.now - 77)
        r = self.board()["mcp_access"]
        self.assertEqual((r["state"], r["since"]), ("<on>", self.now - 77))
        self.assertNotIn("ms_tajna", json.dumps(self.board()))
        r = self.board(env={"MCP_API_KEY": "drugi"})["mcp_access"]
        self.assertEqual(r["state"], "<on>")
        self.assertIn("Renderu", r["detail"])
        self.assertNotIn("drugi", json.dumps(r))

    def test_autopilot_real_switches_and_flags(self):
        self.put("on", True)
        with mock.patch.object(executor, "armed", return_value=False):
            self.assertEqual(self.board()["autopilot_switch"]["state"], "<dry>")
        with mock.patch.object(executor, "armed", return_value=True):
            self.assertEqual(self.board()["autopilot_switch"]["state"], "<live>")
        self.put("flag:pravi_novac_veliki", {"mode": "live", "since": self.now - 9, "who": "Jure"})
        self.put("flag:pravi_novac_sve", {"mode": "paper", "since": self.now - 8, "who": "Jure"})
        b = self.board()
        self.assertEqual(b["real_money_switch:midcap raspon"]["state"], "live")
        self.assertEqual(b["real_money_switch:sve strategije"]["state"], "off")
        self.assertIn("isključeno", b["real_money_switch:sve strategije"]["detail"])
        self.assertIn("pravi_novac_veliki", b["flag"]["detail"])

    def test_heartbeat_sell_all_pause_and_proof(self):
        self.put("heartbeat", self.now - 30)
        self.put("sell_all", self.now - 100)
        self.put("exit_plans_paused", True)
        self.put("veliki_dokaz", "nalog_vlasnika")
        b = self.board()
        self.assertEqual(b["bot_heartbeat"]["state"], "<alive>")
        self.assertEqual(b["sell_all"]["state"], "<running>")
        self.assertEqual(b["exit_plans_pause"]["state"], "<paused>")
        self.assertEqual(b["veliki_proof"]["label"], "nalog vlasnika (bez čekanja dokaza)")
        self.put("heartbeat", self.now - 500)
        self.assertEqual(self.board()["bot_heartbeat"]["state"], "<silent>")

    def test_an_unreadable_database_gives_unknown_rows_not_an_error(self):
        b = {r["key"]: r for r in ploca.now(self.now, trade_db=os.path.join(self.tmp.name, "nema.db"), env={})}
        self.assertEqual(b["grok_autotrade"]["state"], "?")
        self.assertEqual(b["grok_autotrade"]["label"], "nepoznato")
        self.assertIn("trade.db", b["grok_autotrade"]["detail"])
        self.assertEqual(b["kill_switch"]["state"], "<clear>")

    def test_text_and_mcp(self):
        self.put("grok_autotrade", {"on": False, "since": 1_799_000_000, "who": "Jure"})
        with mock.patch("veliki.makro.current", return_value=None):
            lines = ploca.text(ploca.now(self.now, trade_db=self.db, env={}))
        self.assertTrue(any(l.startswith("Grok autotrade: ugašen · od ") and l.endswith("limiti: zadani") for l in lines), lines)
        with mock.patch.object(ploca, "now", return_value=[]):
            d = ploca.mcp({"key": "position"})
        self.assertEqual(d["definitions"]["count"], 1)
        with mock.patch.object(ploca, "now", return_value=[]):
            self.assertNotIn("definitions", ploca.mcp({}))


class Page(unittest.TestCase):
    ROWS = [{"key": "grok_autotrade", "title": "Grok autotrade", "area": "novac", "state": "<off>", "label": "ugašen",
             "since": 1_799_000_000, "who": "Jure", "detail": "limiti: zadani",
             "changes": ["<off> → <on>: vlasnik: prekidač „Grok autotrade”"], "caveats": ["Grok ga ne može sam uključiti."]},
            {"key": "kill_switch", "title": "Kill switch <b>", "area": "novac", "state": "<active>",
             "label": "aktivan: svaka kupnja je blokirana", "since": None, "who": None, "detail": None, "changes": [],
             "caveats": []}]

    def test_board_rows_say_state_since_who_and_what_changes_it(self):
        from ui import stanje
        html = stanje.board_html(self.ROWS)
        for txt in ("Grok autotrade", "ugašen", "od 03.01. 19:13", "Jure", "limiti: zadani", "Što ga mijenja i na što paziti",
                    "Grok ga ne može sam uključiti.", 'data-state="&lt;off&gt;"', "Kill switch &lt;b&gt;", "aktivan",
                    "svaka kupnja je blokirana"):
            self.assertIn(txt, html, txt)
        self.assertNotIn("<b>Kill switch <b>", html)
        self.assertEqual(stanje._tone("kill_switch", "<active>"), "bad")
        self.assertEqual(stanje._tone("sell_all", "<running>"), "bad")
        self.assertEqual(stanje._tone("exit_plans_pause", "<running>"), "good")
        self.assertEqual(stanje._tone("real_money_switch:midcap raspon", "live"), "good")

    def test_the_dictionary_lists_every_machine_and_the_owner_only_sees_the_page(self):
        from ui import stanje
        d = stanje.dictionary_html()
        for m in registar.MACHINES:
            self.assertIn(stanje.esc(m.title), d, m.key)
        self.assertIn("<code>pending</code>", d)
        self.assertNotIn("<code>&lt;", d)                      # a derived state has no literal to show
        with mock.patch.object(ploca, "now", return_value=self.ROWS):
            _t, html = stanje.page({}, settings.owner())
            _t2, other = stanje.page({}, "netko")
        self.assertIn("Rječnik stanja", html)
        self.assertIn('href="/pravi-trade"', html)
        self.assertIn("vidi samo vlasnik", other)
        self.assertNotIn("Grok autotrade", other)

    def test_roles_route_link_and_tool(self):
        from league import roles
        from ui import mcpapi
        self.assertEqual(roles.deny_get("/stanje", "osnovni"), "admin")
        self.assertEqual(roles.deny_get("/stanje", "prijatelj"), "admin")
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run_ui.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index('if path == "/stanje":')
        self.assertIn("tsettings.is_owner(self.user)", src[i:i + 900])     # the server refuses everybody but the owner
        self.assertIn("403", src[i:i + 900])
        tools = {t["name"]: t for t in mcpapi.TOOLS}
        self.assertTrue(tools["get_system_state"]["annotations"]["readOnlyHint"])
        with mock.patch.object(ploca, "now", return_value=self.ROWS):
            d, err = mcpapi._tool("get_system_state", {"area": "odobrenja"})
        self.assertFalse(err)
        self.assertEqual(d["board"][0]["key"], "grok_autotrade")
        self.assertEqual({m["area"] for m in d["definitions"]["machines"]}, {"odobrenja"})


class Guards(unittest.TestCase):
    def test_a_decided_request_is_not_rewritten_by_a_late_reject(self):
        from ui import mcpapi
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tcon = settings.connect(os.path.join(tmp.name, "trade.db"))
        self.addCleanup(tcon.close)
        settings.put(tcon, "mcp_requests", [{"id": "a", "status": "approved"}, {"id": "b", "status": "pending"}], "t")
        self.assertIsNone(mcpapi.decide(tcon, "a", "rejected", "vlasnik odbio", only_from=("pending",)))
        self.assertEqual(mcpapi.decide(tcon, "b", "rejected", "vlasnik odbio", only_from=("pending",))["status"], "rejected")
        self.assertEqual([r["status"] for r in settings.raw(tcon)["mcp_requests"]], ["approved", "rejected"])
        self.assertEqual(mcpapi.decide(tcon, "a", "failed", "x")["status"], "failed")     # without only_from: as before
        self.assertIsNone(mcpapi.decide(tcon, "nema", "rejected", only_from=("pending",)))

    def test_closing_a_strategy_trade_touches_only_an_open_row(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for path, table in (("veliki/live.py", "veliki_trades"), ("oscilator/live.py", "oscilator_trades")):
            with open(os.path.join(root, path), encoding="utf-8") as f:
                src = f.read()
            i = src.index(f"UPDATE {table} SET status='closed'")
            self.assertIn("WHERE id=? AND status='open'", src[i:i + 400], path)


if __name__ == "__main__":
    unittest.main()
