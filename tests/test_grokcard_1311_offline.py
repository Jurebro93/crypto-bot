"""13.11. (Jure, a phone screenshot of the Grok auto block: "Zasto je zapelo. Mogu li se pozicije groka jasnije
prikazat"; 5qaP…pump refused at 11:36 and 11:56 UTC with only "rug check: pao (topcheck)", Grok's X evidence came at
11:57 and it never asked again; the block showed 11:56 while his phone said 13:44 CET).

1. A rug RISK refusal names the concrete findings (the topcheck row's failed checks, RugCheck's danger risks), the
   MCP answer in English says the order (evidence FIRST, then the retry within 30 min at most half of
   grok_max_sol_per_trade), the page gets a short Croatian text; Grok's evidence on a refused token answers whether
   the buy may now pass. The rule itself is unchanged.
2. Zagreb time on every row of the block (a fixed UTC moment renders as UTC+1 in winter, UTC+2 in summer) and in the
   terminal's other lists.
3. The Grok card: open positions (a tap loads the chart: data-sel, entry / now MC, size, PnL, the exit with
   break-even after TP1, live / paper, rounds today), the rounds closed today, the attempts grouped by token with
   Grok's long reason folded under "više".

    python3 -m unittest tests.test_grokcard_1311_offline
"""
import datetime
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, exitplan, store  # noqa: E402
from trade import settings  # noqa: E402
from ui import apterm, grokauto, grokpoz, mcpapi, pravitrade  # noqa: E402
from tests.test_grok_autotrade_offline import GOOD, M2, M3  # noqa: E402
from tests.test_pozicije_izlaz_offline import LIVE_ROW, Base, MINT  # noqa: E402

PAO = "rug check: pao (topcheck)"
LP = "LP zaključan ili spaljen samo 5%: likvidnost se može izvući"
TOP10 = "top 10 holdera drži 72% (bez poolova)"
LONG = ("Range scalp Max: kratki fitilj ispod dna (1,55M), kupci se vraćaju; ulaz 0,15 SOL, TP +18 %, SL -9 %, "
        "momentum na X raste, dva velika računa ga spominju")


def tc_row():
    """A topcheck.db row whose verdict is 'pao' on risk checks only (mint / freeze are fine: no hard rug)."""
    return {"verdict": "pao", "symbol": "MAX",
            "safety": {"verdict": "pao", "fails": [LP, TOP10], "warns": [],
                       "checks": {"mint": ["ok", "mint authority ugašen"], "freeze": ["ok", "freeze authority ugašen"],
                                  "lp": ["fail", LP], "holderi": ["fail", TOP10], "dev": ["ok", "dev ne drži velik udio"]}},
            "rc": {"top10": 72.0, "lp_locked": 5.0, "danger": ["Large Amount of LP Unlocked"]}}


def utc(*a):
    return datetime.datetime(*a, tzinfo=datetime.timezone.utc).timestamp()


class Card(Base):
    def setUp(self):
        super().setUp()   # as tests/test_grok_autotrade_offline.Grok, with a topcheck 'pao' on the risky tokens
        self.risky = set()
        tables = ({MINT: tc_row(), M3: tc_row()}, {})
        for p in (mock.patch.object(copy, "market", lambda toks: {t: GOOD for t in toks}),
                  mock.patch.object(copy, "_rugged", lambda *a: None),
                  mock.patch.object(copy, "_concentration",
                                    lambda t: (PAO, "top10 72%") if t in self.risky else (None, "nepoznato")),
                  mock.patch.object(grokauto, "TX_WAIT_S", 0.0),
                  mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}),
                  mock.patch("scan.filters.rug_tables", lambda: tables),
                  mock.patch("rugfilter.archive.kinds", lambda *a, **k: {})):
            p.start()
            self.addCleanup(p.stop)
        settings.put(self.con, "max_sol_per_trade", 0.5)
        settings.put(self.con, "size_sol", 0.1)
        grokpoz._FACTS.clear()
        self.addCleanup(grokpoz._FACTS.clear)
        settings.put(self.con, "grok_max_sol_per_trade", 0.15)   # the owner's limit in the screenshot: half = 0.075
        self.assertIn("ok=", self.post("/pravi-trade/grokon", {}))

    def ask(self, tok, amount, side="buy", reason="Grok: 3 calleri"):
        return mcpapi.trade_request({"token": tok, "side": side, "amount": amount, "require_approval": False,
                                     "reason": reason})

    def opinion(self, tok, verdict="kupi"):
        return mcpapi._tool("submit_signal_opinion", {"token": tok, "verdict": verdict, "confidence": 0.8,
                                                      "interpretation": "dva velika računa ga zovu"}, "k")[0]

    # ---- 1. the refusal -------------------------------------------------------------------------------------------

    def test_rug_risk_refusal_names_the_findings_and_the_order_of_the_steps(self):
        self.risky.add(MINT)
        code, out = self.ask(MINT, 0.075, reason=LONG)
        self.assertEqual((code, out["status"]), (409, "rejected"))
        en = out["reason"]
        self.assertIn("rug check (topcheck) failed: LP locked or burned only 5%: the liquidity can be pulled; "
                      "the top 10 holders hold 72% (pools excluded); RugCheck danger: Large Amount of LP Unlocked", en)
        self.assertNotIn("pao (topcheck)", en)                                   # never the bare verdict again
        self.assertLess(en.index("FIRST"), en.index("THEN"))
        self.assertIn("submit_x_features", en)
        self.assertIn("submit_signal_opinion with verdict kupi", en)
        self.assertIn("retry execute_trade within 30 min with amount at most 0.075 SOL", en)
        self.assertEqual(out["next"]["max_amount_sol"], 0.075)
        row = grokauto.log_rows(self.con, 1)[0]
        self.assertEqual(row["why_hr"], f"rug provjera (topcheck): {LP}; {TOP10}; RugCheck upozorava: Large Amount of "
                                        "LP Unlocked. Grok smije kupiti samo uz svjež dokaz (X značajke ili mišljenje "
                                        "„kupi”) iz zadnjih 30 min i najviše 0,075 SOL.")
        self.assertEqual((row["rug_risk"], row["sym"]), ([PAO], "HOPE"))
        self.assertNotIn("next", row)
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])

    def test_with_evidence_too_big_says_the_size_then_it_buys_at_half(self):
        self.risky.add(MINT)
        self.ask(MINT, 0.15)
        d = self.opinion(MINT)                                 # the evidence answers that the retry may now pass
        self.assertEqual((d["autotrade_retry"]["may_retry"], d["autotrade_retry"]["max_amount_sol"]), (True, 0.075))
        self.assertIn("retry execute_trade", d["autotrade_retry"]["note"])
        code, out = self.ask(MINT, 0.15)
        self.assertEqual((code, out["status"]), (400, "rejected"))
        self.assertIn("retry execute_trade now with amount at most 0.075 SOL (you asked 0.15)", out["reason"])
        self.assertIn("najviše 0,075 SOL", grokauto.log_rows(self.con, 1)[0]["why_hr"])
        self.assertEqual(self.ask(MINT, 0.075)[1]["status"], "executed")      # the rule itself is unchanged

    def test_evidence_against_or_no_refusal_gives_no_false_hint(self):
        self.risky.add(MINT)
        self.assertNotIn("autotrade_retry", self.opinion(M2))   # no refusal of M2: nothing to say
        self.ask(MINT, 0.075)
        d = self.opinion(MINT, "preskoči")
        self.assertFalse(d["autotrade_retry"]["may_retry"])
        self.post("/pravi-trade/grokoff", {})
        self.assertNotIn("autotrade_retry", self.opinion(MINT))   # autotrade off: no hint

    def test_a_refusal_logged_before_13_11_is_croatian_on_the_page_with_the_findings(self):
        old = {"ts": int(time.time()), "side": "buy", "token": MINT, "amount": 0.15, "status": "rejected",
               "reason": LONG, "why": (f"safety check failed: {PAO} (a rug risk rating: fresh evidence of yours from the "
                                       "last 30 min can override it at half size: submit_x_features ...)")}
        hr = grokauto.why_hr(old, ({MINT: tc_row()}, {}), 0.075)
        self.assertTrue(hr.startswith(f"rug provjera (topcheck): {LP}; {TOP10}"), hr)
        self.assertIn("najviše 0,075 SOL", hr)
        self.assertEqual(grokauto.why_hr({"why": "day limit: 0.3 SOL spent today, at most 0.3 (grok_max_sol_per_day)"}),
                         "dnevni limit: danas već 0,3 SOL, najviše 0,3 SOL na dan")

    # ---- 2. Zagreb time -------------------------------------------------------------------------------------------

    def test_zagreb_time_whatever_zone_the_server_runs_in(self):
        tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"   # Render
        time.tzset()
        try:
            winter, summer = utc(2026, 11, 13, 11, 56, 31), utc(2026, 7, 1, 10, 0)
            self.assertEqual(pravitrade.zg_time(winter, winter), "12:56")              # CET, UTC+1
            self.assertEqual(pravitrade.zg_time(summer, summer), "12:00")              # CEST, UTC+2
            self.assertEqual(pravitrade.zg_time(winter, winter + 86400), "13.11. 12:56")   # another day: its date
            self.assertEqual(apterm._dmhm(winter), "13.11. 12:56")
            row = {"ts": int(winter), "side": "buy", "token": MINT, "amount": 0.15, "status": "rejected",
                   "why_hr": "test"}
            html = pravitrade._grok_rows([row], winter)
            self.assertIn("<span class=mut>12:56</span>", html)
            self.assertNotIn("11:56", html)
        finally:
            if tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = tz
            time.tzset()

    # ---- 3. the Grok card: Grok's positions on top, one collapsed line each ------------------------------------------

    def scenario(self, now):
        """An open Grok position (with a plan: break-even after TP1, and Grok's opinion), a round closed today,
        refusals on M3, and a live quote of the open one in the shared cache."""
        code, out = self.ask(MINT, 0.1, reason="momentum, tri callera")
        self.assertEqual(out["status"], "executed", out)
        tid = out["league_trade_id"]
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                         "qty_raw, qty_left, sol_back) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (tid, MINT, "HOPE", int(now) - 300, "live", "open", grokauto.SRC, 0.1, 1000, 1000, 0.0))
        cur = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                               "qty_left, sol_back, closed_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (M2, "WIF", int(now) - 40, "live", "closed", grokauto.SRC, 0.1, 1000, 0, 0.12, int(now) - 5))
        for side, why in (("buy", grokauto.SRC), ("sell", "auto TP +30%")):
            self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, status, reason, fee_lamports) "
                             "VALUES (?,?,?,?,?,?,?,?)", (int(now) - 10, cur.lastrowid, M2, side, "live", "ok", why, 5000))
        self.con.commit()
        exitplan.set_plan(self.lg, MINT, {"take_profits": [{"at_pct": 15, "sell_share": 0.5}], "stop": {"at_pct": -12},
                                          "breakeven_after_tp1": True, "reason": "Grok"}, 60)
        self.opinion(MINT)
        self.risky.add(M3)
        self.ask(M3, 0.15, reason=LONG)
        self.ask(M3, 0.075, reason=LONG)
        live = dict(LIVE_ROW, mcap=90_200.0)
        pravitrade._LIVE_CACHE[(MINT,)] = (time.time(), {MINT: live})

    def test_grok_positions_on_top_one_collapsed_line_that_opens_the_why(self):
        now = time.time()
        self.scenario(now)
        html = pravitrade._grok_auto_live(self.con, True, None, now)
        # the positions come first in the card, before the limits and the folded lists
        self.assertLess(html.index("Grokove pozicije"), html.index("Danas kupio"))
        # (a) the limits in plain words, under the positions
        self.assertIn("Danas kupio <b>0,1 od 0,3 SOL</b> · otvoreno <b>1 od 3</b>", html)
        self.assertIn("po kupnji najviše <b>0,15 SOL</b> (uz rug rizik i svjež dokaz 0,075)", html)
        row = html[html.index('<details class="apx-gp'):html.index("</details>", html.index('<details class="apx-gp'))]
        self.assertTrue(row.startswith('<details class="apx-gp" id=gp-'))                 # closed until tapped
        summ = row[:row.index("</summary>")]
        # the one line: token (a tap loads the chart), live, entry MC, PnL (live through data-key), the exit in words
        self.assertIn(f'data-sel="{MINT}"', summ)
        self.assertIn("apx-badge live", summ)
        self.assertIn('title="Ulazni MC">ulaz $82.0k', summ)
        self.assertIn("data-f=pnl>+10,0", summ)
        self.assertIn("SL −12 % · TP +15 % · BE nakon TP1", summ)
        self.assertIn(f'data-key="{MINT}:live"', row)
        # opened: the position, Grok's thesis, what he sent, what MemeSonar sees (each marked)
        body = row[row.index("</summary>"):]
        self.assertIn("<span>Sada (MC)</span><b class=n><span data-f=mc>$90.2k</span>", body)
        self.assertIn('<span>Krugovi danas</span><b class=n>1 od 3</b>', body)
        self.assertIn("<h4>Grokova teza</h4>", body)
        self.assertIn("momentum, tri callera", body)
        self.assertIn("<b>mišljenje</b>", body)
        self.assertIn("kupi (80 %): dva velika računa ga zovu", body)
        self.assertIn("<b>plan izlaza</b>", body)
        self.assertIn("nakon TP1 stop na break-even", body)
        self.assertIn("postavio Grok (set_exit_plan)", body)
        self.assertIn('<li class="apx-gf dn"><b>proturječi</b> · rug provjera (topcheck): pala: ' + LP, body)
        self.assertIn('<li class="apx-gf up"><b>potvrđuje</b> · kupci / prodavači: 50 kupnji i 30 prodaja (sat)', body)
        self.assertIn('<li class="apx-gf "><b>neutralno</b> · likvidnost i promet:', body)
        self.assertIn('data-edit="ed-', body)                                            # to the row's SL/TP editor
        # (c) the rounds closed today and (d) the attempts by token: folded, one line each until opened
        closed = html[html.index("Danas zatvoreno"):html.index("Pokušaji (24 h)")]
        self.assertIn(f'data-sel="{M2}"', closed)
        self.assertIn("+0,0200\u00a0SOL", closed)
        self.assertIn('data-l="Izlaz">TP<', closed)
        tries = html[html.index("Pokušaji (24 h)"):html.index("Svi pokušaji redom")]
        self.assertIn("zadnji", tries[:tries.index("</summary>")])
        self.assertEqual(tries.count(f'data-sel="{M3}"'), 1)
        self.assertIn('data-l="Ranije">1 pokušaj', tries)
        self.assertIn("Odbijeno: rug provjera (topcheck): LP zaključan ili spaljen samo 5%", tries)
        i = tries.index(LONG[:40])
        self.assertGreater(i, tries.rindex("<summary>više</summary>", 0, i))     # under "više", never inline
        self.assertNotIn(LONG[:40], tries[:tries.index("<summary>više</summary>")])
        self.assertIn('<details class="apx-more apx-glog"><summary>Svi pokušaji redom (4)</summary>', html)
        self.assertIn("Ugasi Grok autotrade", html)

    def test_grok_positions_stay_on_top_while_autotrade_is_off(self):
        now = time.time()
        self.scenario(now)
        self.post("/pravi-trade/grokoff", {})
        _, body = pravitrade.page({}, "Jure")
        top = body[:body.index("id=pozicije")]
        self.assertIn("autotrade isključen", top)
        self.assertIn('<details class="apx-gp" id=gp-', top)
        self.assertNotIn("Ugasi Grok autotrade", top)
        self.assertLess(body.index("Grokove pozicije"), body.index("id=apx-chartbox"))   # above the chart

    def test_terminal_page_carries_the_card_above_the_tables_with_its_positions(self):
        now = time.time()
        self.scenario(now)
        _, body = pravitrade.page({}, "Jure")
        card = body[body.index("id=grok-auto"):body.index("id=pozicije")]
        self.assertIn(f'data-sel="{MINT}"', card)
        self.assertIn("Odbijeno: rug provjera (topcheck)", card)
        self.assertNotIn("Grok auto", pravitrade.page({}, "netko")[1].split("id=pozicije")[0])   # owner only
        self.assertEqual(apterm._grok_kind(["ručno: Grok odobreno (MCP)"]), "approved")
        self.assertIsNone(apterm._grok_kind(["copy KOL x"]))

    def test_empty_card_says_so(self):
        html = pravitrade._grok_auto_live(self.con, True, [], time.time())
        self.assertIn("Grok sada nema otvorenih pozicija.", html)
        self.assertIn("još nema zatvorenih krugova.", html)
        self.assertIn("zadnja 24 h bez pokušaja.", html)

    def test_exit_in_a_few_words(self):
        plan = {"plan": {"stop": {"kind": "pct", "v": -30.0}, "trailing": {"activate_pct": 15, "trail_pct": 8.0},
                         "take_profits": [{"kind": "pct", "v": 15.0, "sell_share": 0.5},
                                          {"kind": "mc", "v": 250_000.0, "sell_share": 1.0}],
                         "breakeven_after_tp1": True}}
        self.assertEqual(grokpoz.exit_short({}, plan), "SL −30 % · TP1 +15 % · TP2 MC $250k · trailing 8 % · BE nakon TP1")
        self.assertEqual(grokpoz.exit_short({"sl_pct": -60.0, "tp_pct": 15.0}), "SL −60\u00a0% · TP +15\u00a0%")
        self.assertEqual(grokpoz.exit_short({}), "bez TP/SL-a")


class Reload(unittest.TestCase):
    """13.11. (Jure: "Svaki put kada osvježim stranicu autopilota na mobitelu, ona me centrira dolje na graf"): the
    address a form sends back (#pozicije, #poz-12, #kupi-odmah) is used once and dropped from the URL; a reload opens
    at the top. (Checked in Chromium at 390 px as well: #pozicije -> 2686 px down once, every reload -> 0.)"""

    def test_the_hash_is_one_shot_and_a_reload_opens_at_the_top(self):
        js = open(os.path.join(apterm.STATIC_DIR, "ap.js"), encoding="utf-8").read()
        sh = js[js.index("function scrollHash()"):js.index("function scrollHash()") + 200]
        self.assertIn("const h = S.hash;", sh)                                   # never the URL's hash again
        self.assertIn("S.hash = NAV === 'reload' ? '' :", js)                     # a reload ignores an old one
        self.assertIn("history.replaceState(history.state, '', location.pathname + location.search)", js)
        self.assertIn("history.scrollRestoration = 'manual'", js)
        self.assertNotIn("!location.hash) showTab(t)", js)


if __name__ == "__main__":
    unittest.main()
