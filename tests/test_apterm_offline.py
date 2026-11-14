"""The Autopilot as a trading terminal (11.11., Jure: "brzo, pregledno, svježe, na svakom uređaju"; ui/apterm.py):
the aggregated first view, owner-only rendering, the order panel posting to the routes and field names it always
had, the lazy parts kept out of the first HTML, empty settings sections greyed at the bottom, the paper badge and
live-first order, the SSE stream (headers, heartbeat, the bounded number of streams), the freshness badge, the cost
estimate, the chart's candles and zones, and the static files' cache headers. No network: the live numbers are put
into ui/pravitrade's shared cache by hand; trade.equity / trade.aplog are the fakes of tests/test_apui_offline.py.

    python3 -m unittest tests.test_apterm_offline
"""
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from league import copy, store  # noqa: E402
from tests.test_apui_offline import SUMMARY, Base, fake_aplog, fake_equity, history  # noqa: E402
from trade import settings  # noqa: E402
from ui import apterm, pravitrade  # noqa: E402

NOW = int(time.time())
LIVE_T = "Live111111111111111111111111111111111111pump"
PAPER_T = "Papr111111111111111111111111111111111111pump"
_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))


def setUpModule():
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


def market(mcap, liq=60_000.0, price=None):
    price = price or mcap / 1e9
    return {"price": price, "mcap": mcap, "liq": liq, "vol_h1": 40_000.0, "ch_m5": 3.5, "ch_h1": -2.0, "ch_h24": 140.0,
            "w": {"m5": {"buys": 18, "sells": 9}}}


class Env(Base):
    def setUp(self):
        super().setUp()
        apterm.reset()
        self.mods(fake_equity(history(), SUMMARY), fake_aplog())
        self.addCleanup(apterm.reset)
        with pravitrade._LOCK:
            self._live = dict(pravitrade._LIVE_CACHE)
            pravitrade._LIVE_CACHE.clear()
        self.addCleanup(self._restore_live)

    def _restore_live(self):
        with pravitrade._LOCK:
            pravitrade._LIVE_CACHE.clear()
            pravitrade._LIVE_CACHE.update(self._live)

    def live(self, **marks):
        """The shared DexScreener cache as the refresher would have filled it."""
        with pravitrade._LOCK:
            pravitrade._LIVE_CACHE[tuple(sorted(marks))] = (time.time(), {t: market(v) for t, v in marks.items()})

    def demo(self, tok, sym, mcap, rule):
        return self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, source, entry_px, "
                               "entry_eff, entry_mcap, qty, auto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (settings.LEAGUE_USER, tok, sym, NOW - 600, "open", 25, "ručno", mcap / 1e9, mcap / 1e9,
                                mcap, 25.0, json.dumps(rule))).lastrowid

    def seed(self):
        """A live position with its demo side (TP +30 % / SL -40 % from $340k), a paper one with Smart sell, a DCA
        order, a buy order at a market cap, and one closed live trade today."""
        lid = self.demo(LIVE_T, "LIVE", 340_000.0, {"mode": "tpsl", "tp": "+30%", "sl": "-40%", "tp_in": "30%",
                                                     "sl_in": "-40%"})
        pid_demo = self.demo(PAPER_T, "PAPR", 250_000.0, {"mode": "smart"})
        self.lg.commit()
        # the paper one is opened later: newest first would put it on top, live-first must not
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                         "qty_left, league_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (LIVE_T, "LIVE", NOW - 3600, "live", "open", "ručno (pravi trade)", 0.15, 1000, 1000, lid))
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                         "qty_left, league_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (PAPER_T, "PAPR", NOW - 60, "dry", "open", "copy KOL ansem", 0.1, 1000, 500, pid_demo))
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                         "qty_left, sol_back, closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("Clos111111111111111111111111111111111111pump", "CLOS", NOW - 7200, "live", "closed",
                          "copy KOL ansem", 0.1, 1000, 0, 0.13, NOW - 60, 0.002))
        self.con.commit()
        settings.put(self.con, "dca_orders", [{"id": 111, "token": LIVE_T, "sym": "LIVE", "mc": 280_000.0, "sol": 0.05,
                                               "txt": "$280k"}])
        settings.put(self.con, "buy_orders", [{"id": 222, "token": PAPER_T, "sym": "PAPR", "mc": 150_000.0, "sol": 0.1,
                                               "exit": "tpsl", "tp": "40%", "sl": "-30%", "until": NOW + 3600}])
        self.live(**{LIVE_T: 412_000.0, PAPER_T: 268_000.0})


class FirstView(Env):
    def test_the_aggregated_first_view_shape(self):
        self.seed()
        d = json.loads(apterm.first_json("Jure", ""))
        self.assertEqual(d["v"], 1)
        for k in ("ts", "owner", "on", "live", "m", "data_ts", "positions", "orders", "header", "panel", "sig"):
            self.assertIn(k, d)
        self.assertFalse(any(k.startswith("_") for k in d))                   # cfg and rules stay on the server
        self.assertTrue(d["owner"])
        self.assertEqual(d["m"], LIVE_T)                                       # opens on the newest live position
        live, paper = d["positions"]
        self.assertEqual((live["mode"], live["paper"], paper["paper"]), ("live", False, True))
        self.assertEqual(live["avg_mc"], 340_000.0)
        self.assertEqual(live["mc_now"], 412_000.0)
        self.assertAlmostEqual(live["pnl_pct"], (412 / 340 - 1) * 100, places=2)
        self.assertAlmostEqual(live["pnl_sol"], 0.15 * (412 / 340) - 0.15, places=5)
        self.assertEqual((live["tp_pct"], live["tp_mc"]), (30.0, 442_000.0))   # TP +30 % of the entry, as MC too
        self.assertEqual((live["sl_pct"], live["sl_mc"]), (-40.0, 204_000.0))
        self.assertEqual(live["src"], "ručno")
        self.assertEqual((paper["held"], paper["src"], paper["smart"]), (0.5, "auto", True))
        kinds = sorted(o["kind"] for o in d["orders"])
        self.assertEqual(kinds, ["dca", "limit", "sl", "smart", "tp"])
        dca = next(o for o in d["orders"] if o["kind"] == "dca")
        self.assertEqual((dca["cancel"], dca["id"], dca["mc"]), ("/pravi-trade/dcadel", "111", 280_000.0))
        h = d["header"]
        self.assertEqual((h["mint"], h["mcap"], h["buys_m5"], h["sells_m5"], h["bs_m5"]), (LIVE_T, 412_000.0, 18, 9, 2.0))
        p = d["panel"]
        for k in ("balance_sol", "auto_today", "max_day", "size_sol", "max_trade", "fee_side", "tp_last", "sl_default"):
            self.assertIn(k, p)
        self.assertEqual(p["balance_sol"], SUMMARY["sol"])
        self.assertEqual(p["value_sol"], SUMMARY["value_sol"])
        self.assertIsNone(apterm.first_json("Nepoznat"))                      # the page's access
        # a token without a position: the header takes the symbol of the row it was tapped on (?s=), sanitised
        other = "Mochi11111111111111111111111111111111111pump"
        h = json.loads(apterm.first_json("Jure", other, sym="MOCHI<b>"))["header"]
        self.assertEqual((h["mint"], h["sym"]), (other, "MOCHIb"))
        self.assertEqual(json.loads(apterm.first_json("Jure", LIVE_T, sym="X"))["header"]["sym"], "LIVE")   # position wins

    def test_one_build_per_ttl_and_a_fresh_one_after_a_form(self):
        self.seed()
        calls = []
        real = apterm.positions_data
        with mock.patch.object(apterm, "positions_data", lambda *a, **k: calls.append(1) or real(*a, **k)):
            apterm.first_view("Jure")
            apterm.first_view("Jure")
            self.assertEqual(len(calls), 1)                                   # cached FIRST_TTL_S
            pravitrade.page({"ok": "Prodaja poslana"}, "Jure")
            self.assertEqual(len(calls), 2)                                   # right after a form: built anew

    def test_the_page_never_waits_for_dexscreener(self):
        self.seed()
        with pravitrade._LOCK:
            pravitrade._LIVE_CACHE.clear()
        from ui import prijedlog
        with mock.patch.object(prijedlog, "live_market", side_effect=AssertionError("fetched in the request")):
            _, body = pravitrade.page({}, "Jure")
        self.assertIn("čekam cijenu", body)                                   # the first tick fills it


class OwnerOnly(Env):
    def test_owner_gets_the_panel_and_the_actions_viewer_only_looks(self):
        self.seed()
        _, own = pravitrade.page({}, "Jure")
        for k in ("id=kupi-odmah", "action=/pravi-trade/buy", "action=/pravi-trade/sell", "Zatvori 50 %",
                  "Zatvori 100 %", "Uredi SL-TP", "action=/pravi-trade/exit", "action=/pravi-trade/dcadel",
                  "action=/pravi-trade/limitdel", "/pravi-trade/switch", "data-sheet=sell"):
            self.assertIn(k, own, k)
        _, guest = pravitrade.page({"sve": "1"}, "Ivan")
        for k in ("id=kupi-odmah", "action=/pravi-trade/", "Zatvori 50", "Zatvori 100", "Uredi SL-TP", "data-pk=", ">Otkaži<",
                  "data-sheet=sell"):
            self.assertNotIn(k, guest, k)
        self.assertIn("Trguje samo vlasnik", guest)
        self.assertIn(f"https://jup.ag/swap/SOL-{LIVE_T}", guest)            # "Kupi i ti" from his own wallet
        self.assertIn("LIVE", guest)                                          # he sees the positions
        self.assertIn("samo za pozvane", pravitrade.page({}, "Nepoznat")[1])

    def test_the_real_money_switch_is_on_the_terminal_page(self):
        """14.11. (owner: "Ne vidim prekidač"): the box of pravi_novac_sve on /pravi-trade itself, not only ?stari=1."""
        self.seed()
        _, own = pravitrade.page({}, "Jure")
        self.assertIn("id=fl-pravi-novac", own)
        self.assertIn("Uključi pravi novac za sve strategije", own)
        self.assertLess(own.index("id=apx-chart"), own.index("id=prekidaci"))   # 14.11.: the switches at the bottom
        self.assertLess(own.index("id=prekidaci"), own.index("id=apx-ostalo"))
        self.assertIn("name=name value=pravi_novac_sve", own)
        _, guest = pravitrade.page({"sve": "1"}, "Ivan")
        self.assertIn("id=fl-pravi-novac", guest)                              # the state, no button
        self.assertNotIn("Uključi pravi novac za sve strategije", guest)

    def test_lazy_parts_and_api_refuse_strangers(self):
        for name in ("kupiti", "pratimo", "povijest", "ostalo"):
            self.assertIsNone(apterm.lazy(name, "Nepoznat"))
        self.assertEqual(apterm.lazy("nista", "Jure"), "")
        self.assertIsNone(apterm.tick_json("Nepoznat"))
        self.assertIsNone(apterm.candles_data("Nepoznat", LIVE_T))
        self.assertIsNone(apterm.pnl_days("Nepoznat"))


def forms(html):
    """[(action, {field names})] of every POST form in the HTML."""
    out = []
    for m in re.finditer(r"<form method=post action=(\S+?)[ >](.*?)</form>", html, re.S):
        names = set(re.findall(r"name=\"?([a-z_]+)", m.group(2)))
        out.append((m.group(1), names))
    return out


class SameRoutes(Env):
    """The panel only fills fields: every form posts to the route and the field names it always had."""

    def test_forms_post_to_the_unchanged_routes_with_the_same_fields(self):
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        got = forms(body)
        acts = {a for a, _n in got}
        self.assertLessEqual({"/pravi-trade/buy", "/pravi-trade/sell", "/pravi-trade/exit", "/pravi-trade/dca",
                              "/pravi-trade/dcadel", "/pravi-trade/limitdel", "/pravi-trade/switch"}, acts)
        known = {"/pravi-trade/buy", "/pravi-trade/sell", "/pravi-trade/exit", "/pravi-trade/dca", "/pravi-trade/dcadel",
                 "/pravi-trade/limitdel", "/pravi-trade/switch", "/pravi-trade/sellall",
                 "/pravi-trade/flag",   # 14.11.: the existing flag route, for the switch pravi_novac_sve's box
                 # 14.11.: "Prekidači" on the main view: the routes these switches always had (Grok autotrade and its
                 # limits from Postavke, the exit plans' kill switch from Otvoreni nalozi, Grok's requests)
                 "/pravi-trade/grokon", "/pravi-trade/grokoff", "/pravi-trade/groklimits", "/pravi-trade/exitpause",
                 "/pravi-trade/exitresume", "/pravi-trade/mcpok", "/pravi-trade/mcpno"}
        self.assertEqual(acts - known, set())                               # no new POST route
        buy = next(n for a, n in got if a == "/pravi-trade/buy")
        # prijedlog is added by Kupi on a proposal; 11.11. (noc/sltp) chart_mint + confirm_mismatch: the chart's token,
        # a buy of another token only when confirmed (pravitrade._chart_guard); 11.11. (plan uz kupnju): trail + time
        self.assertEqual(buy, {"token", "sol", "at", "tp", "sl", "exit", "chart_mint", "confirm_mismatch", "trail", "time"})
        for a, n in got:
            if a == "/pravi-trade/sell":
                self.assertEqual(n, {"id", "frac"})
            if a == "/pravi-trade/dca":
                self.assertEqual(n, {"token", "lvl", "sol"})
            if a in ("/pravi-trade/dcadel", "/pravi-trade/limitdel"):
                self.assertEqual(n, {"id"})
            if a == "/pravi-trade/exit":
                self.assertLessEqual(n, {"id", "tp", "sl"})
        for fr in ("0.25", "0.5", "1"):                                    # 25 / 50 / 100 % in the sell tab
            self.assertIn(f'name=frac value="{fr}"', body)
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("h.name = 'prijedlog'", js)                          # Kupi on a proposal: the same hidden field
        self.assertNotIn(".submit()", js.split("// ---- the order panel ----")[1])   # nothing posts by itself

    def test_the_sell_buttons_make_the_same_sell_request(self):
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        ids = re.search(r'action=/pravi-trade/sell onsubmit="[^"]*"><input type=hidden name=id value="([0-9,]+)">', body)
        pid = ids.group(1)
        loc = pravitrade.post("/pravi-trade/sell", {"id": pid, "frac": "0.25"}, "Jure")
        self.assertIn("ok=", loc)
        self.assertEqual(settings.raw(self.con)["sell_req"], {pid: 0.25})
        apterm.reset()
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("prodaja 25\u00a0% u tijeku", body)                  # the row says it, no second button
        self.assertIn(">Prodaja<", body)                                    # and the orders tab lists it

    def test_kupi_on_a_proposal_carries_the_fields_of_the_old_card(self):
        p = {"id": 7, "token": LIVE_T, "symbol": "LIVE", "strategy": "range", "sources": ["range"], "ev_pct": 6.0,
             "p_tp": 0.6, "size_sol": 0.5, "expires_ts": NOW + 1800,
             "row": {"buy": {"tp": "25%", "sl": "-20%"}, "entry_zone": {"mcap_low": 1, "mcap_high": 2}, "n": 40,
                     "exits_mcap": {"time_min": 30, "trailing_pct": 8}}}
        cfg = pravitrade._cfg(self.con)
        with mock.patch.object(apterm, "_proposals", lambda owner, now: ([p], [], [], "shadow")), \
                mock.patch("ui.zivo.rows", lambda now=None, **k: []):
            html = apterm.kupiti_html(self.con, cfg, True, NOW)
        pk = json.loads(re.search(r'data-pk="([^"]+)"', html).group(1).replace("&quot;", '"'))
        self.assertEqual({k: pk[k] for k in ("id", "token", "tp", "sl")}, {"id": 7, "token": LIVE_T, "tp": "25%", "sl": "-20%"})
        self.assertLessEqual(float(pk["sol"]), cfg["max_sol_per_trade"])   # size capped by the per-trade limit
        self.assertEqual(pk["trail"], 8)
        self.assertIn("0,200 %/min", html)                                 # EV per minute: 6 % over 30 min


class Lazy(Env):
    def test_lazy_parts_are_not_built_for_the_first_html(self):
        self.seed()

        def boom(*a, **k):
            raise AssertionError("built for the first HTML")
        with mock.patch.object(apterm, "kupiti_html", boom), mock.patch.object(apterm, "pratimo_html", boom), \
                mock.patch.object(apterm, "povijest_html", boom), mock.patch.object(apterm, "ostalo_html", boom), \
                mock.patch.object(pravitrade, "dnevnik_fragment", boom):
            _, body = pravitrade.page({}, "Jure")
        for src in ("/pravi-trade/l/kupiti", "/pravi-trade/l/pratimo", "/pravi-trade/l/povijest", "/pravi-trade/l/ostalo",
                    "/pravi-trade/dnevnik"):
            self.assertRegex(body, f'data-x-src="?{src}')
        self.assertIn("class=apx-skel", body)                              # skeletons instead of empty blocks
        self.assertNotIn("Postavljanje walleta", body)
        _, full = pravitrade.page({"sve": "1"}, "Jure")                    # no JavaScript: everything in the page
        for k in ("Nema prijedloga s EV &gt; 0", "Postavljanje walleta", "Danas uživo", "id=apx-ostalo open"):
            self.assertIn(k, full)
        # nobody followed, no event, no pre-shill wallet: those cards are in the page but hidden, empty (no title)
        for cid in ("pratimo", "apx-eventi", "apx-preshill"):
            self.assertRegex(full, rf'id={cid} data-x-src="?/pravi-trade/l/\w+"? data-x-every=\d+ data-hide-empty hidden>'
                                   r'</section>')
        self.assertNotIn(">Koga pratimo <", full)
        self.assertIn('<a href="/pravi-trade?sve=1">', body)               # the link for a browser without JS

    def test_history_has_the_days_pnl_on_top_live_first_and_pages(self):
        self.seed()
        html = apterm.lazy("povijest", "Jure")
        self.assertIn("Danas uživo", html)
        self.assertIn("+0,0280 SOL", html)                            # 0.13 - 0.1 - 0.002
        self.assertNotIn("Starije", html)                                   # one page only
        for i in range(25):
            self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, sol_in, sol_back, "
                             "closed_ts) VALUES (?,?,?,?,?,?,?,?)", (f"T{i}", f"S{i}", NOW - 9000 - i, "dry", "closed",
                                                                    0.1, 0.09, NOW - 8000 - i))
        self.con.commit()
        html = apterm.lazy("povijest", "Jure")
        self.assertIn('data-page="/pravi-trade/l/povijest?p=2"', html)
        self.assertLess(html.index("CLOS"), html.index("S0"))             # live first
        self.assertIn("← Novije", apterm.lazy("povijest", "Jure", {"p": "2"}))


class EmptySections(Env):
    def test_empty_meta_words(self):
        row = '<details class=ap-sec><summary><div class="ms-row"><div class="ms-m"><div class="ms-t">X</div>' \
              '<div class="ms-s">{}</div></div></div></summary></details>'
        for meta, empty in (("0 pozvanih", True), ("0 novčanika", True), ("isključen", True), ("nema podataka", True),
                            ("3 pozvanih", False), ("ulog 0,1 SOL", False), ("10 aktivnih tema", False)):
            self.assertEqual(apterm.empty_meta(row.format(meta)), empty, meta)
        self.assertFalse(apterm.empty_meta("<p>bez retka</p>"))

    def test_settings_always_empty_diagnostics_never(self):
        # 11.11. (Jure: "prikazuj samo ono što ima zaključak ili nešto radi"): a setting keeps its row (it is the
        # switch), an empty diagnostic is not rendered at all; no grey "Bez sadržaja" group any more
        html = apterm.lazy("ostalo", "Jure")
        self.assertNotIn("class=apx-dim", html)
        self.assertNotIn("Bez sadržaja", html)
        for k in (">Pravila<", ">Uredi praćenja<", ">Grok (MCP)<", "Tko vidi stranicu", "Kako je zaštićeno"):
            self.assertIn(k, html, k)
        self.assertNotIn(">Koga prati<", html)                              # one list ("Koga pratimo"), not two
        self.assertNotIn("id=ev-znacajke", html)                           # no report: the section is left out
        for name in ("eventi", "preshill"):                                # main-view cards: "" while empty (200)
            self.assertEqual(apterm.lazy(name, "Jure"), "")
            self.assertIn(name, apterm.LAZY)


class LiveFirst(Env):
    def test_paper_badge_grey_and_live_always_first(self):
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        pos = body[body.index("id=pozicije"):body.index("id=nalozi")]
        self.assertLess(pos.index(LIVE_T), pos.index(PAPER_T))            # live first, although opened earlier
        self.assertLess(pos.index("Probno (paper)"), pos.index(PAPER_T))   # a divider before the paper ones
        self.assertIn('<span class="apx-badge live">uživo</span>', pos)
        self.assertIn('<span class="apx-badge paper">paper</span>', pos)
        self.assertRegex(pos, r'<details class="apx-pos apx-pr is-paper"[^>]*data-tok="' + PAPER_T)   # 14.11.: a row
        # grey (11.11.: the site's soft grey with a thin line, like the rest of memesonar.app)
        self.assertIn(".apx-badge.paper{background:var(--soft);color:var(--mut);box-shadow:inset 0 0 0 1px var(--line)}",
                      apterm.CSS)
        # green / red only for up / buy / TP and down / sell / SL
        self.assertIn('<span class="n apx-pnl up" data-l="PnL" data-f=pnl>', pos)
        self.assertIn('<span class="n dn" data-l="SL">', pos)
        self.assertIn('<span class="n up" data-l="TP">', pos)


class HandlerMixin:
    def _get(self, path, user="Jure"):
        import run_ui
        h = run_ui.Handler.__new__(run_ui.Handler)
        h.path, h.headers, h.wfile, h.user, h.role = path, {"Accept-Encoding": "gzip"}, io.BytesIO(), user, "admin"
        h.status, h.hdrs = [], []
        h.send_response = lambda code, msg=None: h.status.append(code)
        h.send_header = lambda k, v: h.hdrs.append((k, v))
        h.end_headers = lambda: None
        h.sent = []
        h._send = lambda code, body=b"", ctype="text/html", gz=None, translated=False: h.sent.append((code, body, ctype))
        with mock.patch.object(run_ui, "AUTH", False):
            h.do_GET()
        return h


class Stream(HandlerMixin, Env):
    def test_stream_sends_ticks_on_change_heartbeats_and_ends(self):
        clock = {"t": 1000.0}
        ticks = iter([{"ts": 1, "data_ts": 10, "tok": {"A": {"mcap": 1}}, "sig": "s"}] * 3
                     + [{"ts": 9, "data_ts": 11, "tok": {"A": {"mcap": 2}}, "sig": "s"}] * 50)

        def sleep(s):
            clock["t"] += s
        out = list(apterm.stream("A", clock=lambda: clock["t"], sleep=sleep, max_s=40, every=2, hb_s=5,
                                 tick_fn=lambda m: next(ticks)))
        text = b"".join(out).decode()
        self.assertTrue(text.startswith("retry: 5000\n\n"))
        self.assertEqual(text.count("event: tick\n"), 2)                   # only when the data changed
        self.assertGreaterEqual(text.count("event: hb\n"), 3)              # a heartbeat when nothing changed for 5 s
        self.assertTrue(text.endswith("event: bye\ndata: {}\n\n"))        # the browser reconnects
        first = json.loads(text.split("event: tick\ndata: ")[1].split("\n")[0])
        self.assertEqual(first["tok"]["A"]["mcap"], 1)

    def test_sse_route_headers_slots_and_access(self):
        with mock.patch.object(apterm, "STREAM_MAX_S", 0):                 # one retry hint and "bye", then it ends
            h = self._get("/pravi-trade/api/stream?m=" + LIVE_T)
        self.assertEqual(h.status, [200])
        hd = dict(h.hdrs)
        self.assertEqual(hd["Content-Type"], "text/event-stream; charset=utf-8")
        self.assertEqual(hd["Cache-Control"], "no-store")
        self.assertEqual(hd["X-Accel-Buffering"], "no")
        self.assertNotIn("Content-Encoding", hd)                           # never gzipped
        self.assertIn(b"retry: 5000", h.wfile.getvalue())
        self.assertIn(b"event: bye", h.wfile.getvalue())
        self.assertTrue(apterm.stream_slot())                              # the slot came back
        apterm.stream_release()
        self.assertEqual(self._get("/pravi-trade/api/stream", "Nepoznat").sent[0][0], 403)
        taken = 0
        while apterm.stream_slot():                                        # every slot busy: 503, the page polls
            taken += 1
        try:
            self.assertEqual(taken, apterm.STREAM_MAX)
            h = self._get("/pravi-trade/api/stream")
            self.assertEqual(h.status, [503])
            self.assertIn(("Retry-After", str(apterm.POLL_S)), h.hdrs)
        finally:
            for _ in range(taken):
                apterm.stream_release()

    def test_a_closed_tab_frees_its_stream_at_once(self):
        import socket
        import run_ui
        a, b = socket.socketpair()
        try:
            self.assertFalse(run_ui._peer_gone(a))                         # open, nothing sent: alive
            b.close()
            self.assertTrue(run_ui._peer_gone(a))                          # the browser left
        finally:
            a.close()
        self.assertTrue(run_ui._peer_gone(None))
        checks = iter([True, True, False])
        clock = {"t": 0.0}
        out = list(apterm.stream("A", clock=lambda: clock["t"], sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
                                 max_s=100, every=2, hb_s=50, alive=lambda: next(checks),
                                 tick_fn=lambda m: {"ts": 1, "data_ts": 1, "tok": {}, "sig": "s"}))
        self.assertEqual(len(out), 2)                                      # retry + one tick, then it stops
        self.assertNotIn(b"bye", b"".join(out))

    def test_one_shared_tick_for_every_viewer(self):
        self.seed()
        calls = []
        with mock.patch.object(pravitrade, "_live_cached", lambda key, now, **k: calls.append(key) or
                               {t: market(100_000.0) for t in key}):
            a = apterm.tick(LIVE_T, now=NOW)
            b = apterm.tick(LIVE_T, now=NOW + 1)                           # inside TICK_S: the same dict
            self.assertIs(a, b)
            self.assertEqual(len(calls), 1)
            apterm.tick("", now=NOW + 3)
            self.assertEqual(len(calls), 2)
            js = json.loads(apterm.tick_json("Jure", LIVE_T))
        self.assertEqual(set(a["tok"]), {LIVE_T, PAPER_T})
        self.assertEqual(set(a["tok"][LIVE_T]), {"mcap", "price", "liq", "vol_h1", "ch_m5", "ch_h1", "ch_h24", "buys_m5",
                                                 "sells_m5"})
        self.assertIn("sig", a)
        self.assertIn("tok", js)


class Freshness(unittest.TestCase):
    def test_words_and_the_yellow_badge_after_60_s(self):
        self.assertEqual(apterm.freshness(1000, now=1012), ("ažurirano prije 12 s", False))
        self.assertEqual(apterm.freshness(1000, now=1060), ("ažurirano prije 1 min", False))
        self.assertEqual(apterm.freshness(1000, now=1061), ("ažurirano prije 1 min", True))
        self.assertEqual(apterm.freshness(1000, now=1000 + 7200), ("ažurirano prije 2 h", True))
        self.assertEqual(apterm.freshness(None), ("nema podataka", True))
        self.assertEqual(apterm.age_badge(1000, now=1005), '<span class="apx-age" data-ts="1000">ažurirano prije 5 s</span>')
        self.assertIn('class="apx-age old"', apterm.age_badge(1000, now=1100))
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        # the browser counts the same way (11.11.: a block with its own cadence, the wallet's 5-min snapshots, sets its own)
        self.assertIn("el.classList.toggle('old', a > (+el.dataset.stale || 60))", js)

    def test_cost_estimate_is_trade_cost(self):
        from trade import cost
        c = apterm.cost_pct(1000, 100_000, fee_side=0.01)
        imp = 1000 / (50_000 + 1000)                                        # size / (liq/2 + size)
        self.assertAlmostEqual(c["slip_pct"], round(200 * imp, 3))
        self.assertAlmostEqual(c["buy_slip_pct"], round(100 * imp, 3))
        self.assertAlmostEqual(c["cost_pct"], round(100 * cost.round_trip(1000, 100_000, 0.01), 3))   # the one model
        self.assertAlmostEqual(c["cost_pct"], round(2 + 200 * imp, 3))     # 2 x 1 % fee + 2 x impact
        self.assertFalse(c["warn"])                                         # 1,96 % buy slippage: under SLIP_MAX
        self.assertTrue(apterm.cost_pct(1200, 100_000, 0.01)["warn"])       # 2,3 %: above 2 % (rule C)
        self.assertFalse(apterm.cost_pct(100, 1_000_000)["warn"])
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("const imp = usd / (liq / 2 + usd)", js)              # the browser: the same formula
        self.assertIn("2 * (P.fee_side || 0) * 100", js)
        self.assertIsNone(apterm.cost_pct(0, 1000))
        self.assertIsNone(apterm.cost_pct(10, None))


class Candles(Env):
    def setUp(self):
        super().setUp()
        self.rdb = os.path.join(self.tmp.name, "range.db")
        self.env2 = mock.patch.dict(os.environ, {"RANGE_DB": self.rdb, "RANGE_HYPE_DB": os.path.join(self.tmp.name, "h.db")})
        self.env2.start()
        self.addCleanup(self.env2.stop)

    def test_candles_lines_and_zones_in_market_cap_and_price(self):
        from rangedca import data as rdata
        self.seed()
        rc = rdata.connect(self.rdb)
        rows = [(LIVE_T, NOW - i * 60, (300_000 + i * 100) / 1e9, 300_000 + i * 100, 60_000.0, 9000.0, 90_000.0, None,
                 10, 5, 100, 50, None) for i in range(120)]
        rc.executemany("INSERT INTO snaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        zones = {"range_low_low": 0.000302, "range_low_top": 0.000322, "range_high_low": 0.000405,
                 "range_high_top": 0.000428, "mc": {"range_low_low": 302_000, "range_low_top": 322_000,
                                                    "range_high_low": 405_000, "range_high_top": 428_000}}
        rdata.save_range(rc, LIVE_T, {"ts": NOW - 60, "status": "aktivan", "active": True, "zones": zones,
                                      "metrics": {"supply": 1e9}}, {})
        rc.commit()
        rc.close()
        c = apterm.candles_data("Jure", LIVE_T, "5m", "mc", now=NOW)
        self.assertEqual(c["unit"], "mc")
        self.assertTrue(24 <= len(c["candles"]) <= 26)                    # two hours of minutes in 5-min candles
        self.assertEqual(set(c["candles"][0]), {"time", "open", "high", "low", "close"})
        self.assertEqual(c["candles"], sorted(c["candles"], key=lambda x: x["time"]))
        self.assertTrue(all(x["time"] % 300 == 0 for x in c["candles"]))
        lines = {ln["kind"]: ln["value"] for ln in c["lines"]}
        self.assertEqual(lines, {"entry": 340_000.0, "sl": 204_000.0, "tp": 442_000.0, "dca": 280_000.0})
        bands = {b["kind"]: (b["lo"], b["hi"]) for b in c["zones"]["bands"]}
        self.assertEqual(bands["bottom"], (302_000, 322_000))
        self.assertEqual(bands["top"], (405_000, 428_000))
        self.assertAlmostEqual(bands["dca"][0], 302_000 * 0.92)          # the DCA band under the bottom (floor_x)
        self.assertEqual(c["zones"]["computed_ts"], NOW - 60)
        p = apterm.candles_data("Jure", LIVE_T, "1h", "price", now=NOW)
        self.assertEqual(p["unit"], "price")
        self.assertAlmostEqual({ln["kind"]: ln["value"] for ln in p["lines"]}["entry"], 340_000.0 / (412_000.0 / 0.000412))
        self.assertEqual(apterm.candles_data("Jure", "nije-adresa"), {"error": "nije adresa tokena"})
        empty = apterm.candles_data("Jure", PAPER_T, "5m", "mc", now=NOW)   # nothing stored: [] and no zones
        self.assertEqual((empty["candles"], empty["zones"]), ([], None))
        # 11.11. (the tooltip): each candle's volume in USD, aligned with the candles (None where none is known)
        self.assertEqual(len(c["vol"]), len(c["candles"]))
        self.assertTrue(any(v for v in c["vol"]))
        self.assertTrue(all(v is None or v >= 0 for v in c["vol"]))
        self.assertEqual(empty["vol"], [])

    def test_bucket_volume(self):
        vols = []
        out = apterm.bucket([(600, 1, 2, 1, 2, 10.0), (660, 2, 3, 2, 3, None), (900, 3, 3, 3, 3, 5.0), (960, 3, 4, 3, 4, None)],
                            300, 1.0, vols)
        self.assertEqual([b["time"] for b in out], [600, 900])
        self.assertEqual(vols, [10.0, 5.0])
        vols = []
        apterm.bucket([(600, 1, 1, 1, 1, None)], 300, 1.0, vols)
        self.assertEqual(vols, [None])                                     # no volume known: None, not 0
        self.assertEqual(apterm.bucket([(600, 1, 1, 1, 1)], 300), [{"time": 600, "open": 1.0, "high": 1.0, "low": 1.0,
                                                                     "close": 1.0}])


class PnlDays(HandlerMixin, Env):
    """11.11. (Jure: "po danima profit and loss"): GET /pravi-trade/api/pnl-days, read-only, live and paper apart."""

    def days(self):
        from trade import executor
        d0 = executor._day_start(NOW, "Europe/Zagreb")          # today's midnight in Zagreb
        d1 = executor._day_start(d0 - 1, "Europe/Zagreb")      # yesterday's
        return d0, d1, max(d0 + 1, NOW - 30)

    def closed(self, mode, sin, back, fee, ts, sym="T"):
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                         "sol_back, closed_ts, fees_sol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (sym + "1" * (44 - len(sym)), sym, ts - 600, mode, "closed", "ručno", sin, 1000, 0, back, ts, fee))

    def demo_closed(self, size, pnl, ts, sym="D", user=None, status="closed"):
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, ret, source) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", (user or settings.LEAGUE_USER, sym + "2" * (44 - len(sym)), sym,
                                                         ts - 600, ts if status == "closed" else None, status, size, pnl,
                                                         pnl / size, "copy"))

    def test_live_by_day_sums_win_rate_fees_and_the_day_rate(self):
        d0, d1, today = self.days()
        self.closed("live", 0.1, 0.13, 0.002, today, "WIN")       # +0,028 SOL, +28 %
        self.closed("live", 0.1, 0.08, 0.001, today, "LOSS")      # -0,021 SOL, -21 %
        self.closed("live", 0.2, 0.25, 0.003, d1 + 3600, "Y")     # yesterday: +0,047 SOL
        self.closed("dry", 0.1, 0.5, 0.0, today, "DRY")           # paper position: not in "live"
        self.closed("live", 0.1, 0.5, 0.0, d0 - 40 * 86400, "OLD")   # outside the 30 days
        # yesterday's wallet snapshots: SOL at 140 and 160 $ (average 150); today none: today's rate (200)
        self.con.executemany("INSERT INTO equity (ts, sol, usdc, tokens_sol, sol_usd, usd_eur, flow_sol, src) "
                             "VALUES (?,?,?,?,?,?,?,?)", [(d1 + 600, 1, 0, 0, 140.0, 0.9, 0, "live"),
                                                         (d1 + 7200, 1, 0, 0, 160.0, 0.9, 0, "live")])
        self.con.commit()
        with mock.patch.object(apterm, "_sol_usd", lambda tcon: 200.0):
            d = apterm.pnl_days("Jure", "live", 30, now=NOW)
        rows = d["rows"]
        self.assertEqual((d["mode"], d["days"], d["native"], d["fees_known"], len(rows)), ("live", 30, "sol", True, 30))
        self.assertEqual([r["day"] for r in rows], sorted(r["day"] for r in rows))   # oldest first, every day
        import datetime
        from zoneinfo import ZoneInfo
        self.assertEqual(rows[-1]["day"], datetime.datetime.fromtimestamp(NOW, ZoneInfo("Europe/Zagreb")).date().isoformat())
        t, y = rows[-1], rows[-2]
        self.assertEqual((t["n"], t["wins"], t["win_rate"]), (2, 1, 50.0))
        self.assertAlmostEqual(t["pnl_sol"], 0.007)
        self.assertAlmostEqual(t["fees_sol"], 0.003)
        self.assertAlmostEqual(t["pnl_usd"], 1.4)                  # today's rate
        self.assertTrue(t["rate_now"])
        self.assertEqual((t["best"]["sym"], t["best"]["pct"], t["worst"]["sym"], t["worst"]["pct"]), ("WIN", 28.0, "LOSS", -21.0))
        self.assertEqual((y["n"], y["win_rate"], y["rate"], y["rate_now"]), (1, 100.0, 150.0, False))
        self.assertAlmostEqual(y["pnl_usd"], 0.047 * 150, places=2)  # yesterday's average rate
        self.assertAlmostEqual(t["cum_sol"], 0.054)
        self.assertTrue(all(r["n"] == 0 and r["best"] is None for r in rows[:-2]))   # the dry and the old one are out
        tot = d["total"]
        self.assertEqual((tot["n"], tot["wins"], tot["win_rate"], tot["days_plus"], tot["days_minus"]), (3, 2, 66.7, 2, 0))
        self.assertAlmostEqual(tot["pnl_sol"], 0.054)
        self.assertAlmostEqual(tot["fees_sol"], 0.006)
        self.assertEqual(tot["best"]["sym"], "WIN")
        self.assertEqual(tot["worst"]["sym"], "LOSS")

    def test_paper_comes_from_the_demo_account_in_usd(self):
        d0, d1, today = self.days()
        self.demo_closed(25, 5.0, today, "UP")                    # +20 %
        self.demo_closed(25, -2.5, today, "DOWN")                 # -10 %
        self.demo_closed(20, 10.0, d1 - 2 * 86400 + 7200, "OLDER")
        self.demo_closed(25, 99.0, today, "OTHER", user="Ivan")   # another player: not the Autopilot's
        self.demo_closed(25, 0.0, today, "OPEN", status="open")
        self.lg.commit()
        self.closed("live", 0.1, 0.2, 0.001, today, "LIVE")      # live stays out of paper
        self.con.commit()
        with mock.patch.object(apterm, "_sol_usd", lambda tcon: 200.0):
            d = apterm.pnl_days("Jure", "paper", 7, now=NOW)
            live = apterm.pnl_days("Jure", "live", 7, now=NOW)
        self.assertEqual((d["native"], d["fees_known"], len(d["rows"])), ("usd", False, 7))
        t = d["rows"][-1]
        self.assertEqual((t["n"], t["wins"], t["win_rate"], t["pnl_usd"], t["fees_sol"]), (2, 1, 50.0, 2.5, None))
        self.assertAlmostEqual(t["pnl_sol"], 2.5 / 200)
        self.assertEqual((t["best"]["sym"], t["best"]["pct"], t["worst"]["pct"]), ("UP", 20.0, -10.0))
        self.assertEqual((d["total"]["n"], d["total"]["pnl_usd"]), (3, 12.5))
        self.assertEqual((live["total"]["n"], live["rows"][-1]["best"]["sym"]), (1, "LIVE"))

    def test_cache_parameters_and_route(self):
        d0, d1, today = self.days()
        self.closed("live", 0.1, 0.13, 0.002, today)
        self.con.commit()
        with mock.patch.object(apterm, "_sol_usd", lambda tcon: 200.0):
            a = apterm.pnl_days("Jure", "live", 30, now=NOW)
            self.assertIs(apterm.pnl_days("Jure", "live", 30, now=NOW + 1), a)          # cached PNL_TTL_S
            self.assertIsNot(apterm.pnl_days("Jure", "live", 30, now=NOW + apterm.PNL_TTL_S + 1), a)
            self.assertEqual(apterm.pnl_days("Jure", "x", "13", now=NOW)["mode"], "live")   # unknown: live, 30 days
            self.assertEqual(apterm.pnl_days("Jure", "live", "13", now=NOW)["days"], 30)
            self.assertEqual(len(apterm.pnl_days("Jure", "paper", "90", now=NOW)["rows"]), 90)
            h = self._get("/pravi-trade/api/pnl-days?m=paper&d=7")
            self.assertEqual((h.sent[0][0], h.sent[0][2]), (200, "application/json"))
            self.assertEqual(json.loads(h.sent[0][1])["mode"], "paper")
            self.assertEqual(self._get("/pravi-trade/api/pnl-days", "Nepoznat").sent[0][0], 403)
        with mock.patch.object(pravitrade, "_league_ro", lambda: None):                 # no league.db: no paper rows
            apterm.reset()
            self.assertEqual(apterm.pnl_days("Jure", "paper", 7, now=NOW)["total"]["n"], 0)


class BrandAndTooltip(Env):
    """11.11. (Jure): the page in the site's colours (not a black exchange terminal), the colour rule, the tooltip and
    the keyboard on both charts, the PnL block on top of "Povijest"."""

    def test_brand_tokens_light_and_the_colour_rule(self):
        css = apterm.CSS
        for dark in ("#0b0e14", "#16c784", "#ea3943", "#f0b90b", "color-scheme:dark", "prefers-color-scheme"):
            self.assertNotIn(dark, css)                         # the site is always light: so is this page
        self.assertNotRegex(css, r"--(bg|soft|card|fg|mut|line|acc|good|bad|warn):")   # the site's tokens, not its own
        self.assertIn("--up:var(--good);--dn:var(--bad)", css)
        self.assertIn(".apx .apx-tabs button.on{color:var(--fg);font-weight:650;border-bottom-color:var(--acc)}", css)
        # green / red only on up / down, buy / sell, TP / SL (and the sell fraction chips of the sell form)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
            if re.search(r"var\(--(up|dn|good|bad)\)", body) and ":root" not in sel:   # :root defines the aliases
                for one in sel.split(","):
                    self.assertRegex(one, r"\.(up|dn|buy|sell)\b|sellall|ap-buy|input:checked", one)
        # cancel / refuse / kill switches and status dots are not red or green on this page
        self.assertIn(".apx .ap button.ap-cancel,.apx .ap button.ap-stop{color:var(--fg)", css)
        self.assertIn(".apx .ms-dot.good,", css)
        tip = re.search(r"\.apx-tip\{[^}]*\}", css).group(0)
        self.assertGreaterEqual(int(re.search(r"font-size:(\d+)px", tip).group(1)), 13)   # readable

    def test_chart_markup_tooltip_and_keyboard_hooks(self):
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        self.assertRegex(body, r'<div id=apx-chart class=apx-chart data-m="[^"]+" tabindex=0 role=img')
        self.assertIn("strelice lijevo i desno", body)
        self.assertNotIn("class=apx-leg", body)                # the small legend row above the chart is gone
        self.assertIn("TradingView Lightweight Charts™</a> · Copyright (c) 2025 TradingView, Inc.", body)   # attribution
        # PnL by day lives in the "Portfelj" card (one place, not also in "Povijest")
        port = body[body.index("id=apx-port"):body.index("id=kupiti")]   # 14.11.: under Pozicije
        for k in ("data-pm=live class=on", "data-pm=paper", "data-pv=val class=on", "data-pv=days", "data-pu=sol class=on",
                  "data-pu=usd", "data-pd=7", "data-pd=30 class=on", "data-pd=90", "id=apx-pchart tabindex=0"):
            self.assertIn(k, port)
        self.assertNotIn("data-pm=", body[body.index("id=povijest"):body.index("id=dnevnik")])
        self.assertIn("<div id=apx-hist data-x-src=/pravi-trade/l/povijest>", body)
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        for k in ("subscribeCrosshairMove", "subscribeClick", "setCrosshairPosition", "'ArrowLeft'", "'ArrowRight'",
                  "'apx-tip'", "/pravi-trade/api/pnl-days?", "/pravi-trade/api/portfelj?", "addHistogramSeries",
                  "addLineSeries", "addAreaSeries", "attributionLogo: true", "getComputedStyle(document.documentElement)",
                  "$('#apx-hist')"):
            self.assertIn(k, js)
        self.assertIn("x = y > H - 42 ? 54 : 8", js)             # zone labels start right of the TradingView logo
        self.assertNotRegex(js, r"#(6d8cff|b48cff|16c784|ea3943|151b26|1d2431)")   # no terminal colours left
        self.assertIn("<button class=apx-b>Otkaži</button>", body)   # cancelling an order is no sale: not red
        self.assertNotIn('class="apx-b sell">Otkaži', body)


class Static(HandlerMixin, Env):
    def test_static_files_cache_for_a_year_by_content_hash(self):
        raw, gz, ctype, ver = apterm.static_asset("ap.js")
        h = self._get(f"/pravi-trade/static/ap.js?v={ver}")
        hd = dict(h.hdrs)
        self.assertEqual(h.status, [200])
        self.assertEqual(hd["Cache-Control"], "private, max-age=31536000, immutable")
        self.assertEqual(hd["Content-Encoding"], "gzip")
        self.assertEqual(hd["ETag"], f'"{ver}"')
        self.assertEqual(h.wfile.getvalue(), gz)
        self.assertEqual(dict(self._get("/pravi-trade/static/ap.js?v=stari").hdrs)["Cache-Control"], "no-cache")
        self.assertEqual(self._get("/pravi-trade/static/../run_ui.py").sent[0][0], 404)
        lwc = apterm.static_asset(apterm.LWC_FILE)
        self.assertTrue(lwc[0].startswith(b"/*!\n * @license\n * TradingView Lightweight Charts"))   # pinned, licensed
        self.assertTrue(os.path.isfile(os.path.join(apterm.STATIC_DIR, "LICENSE-lightweight-charts.txt")))
        self.assertIn(f"/pravi-trade/static/{apterm.LWC_FILE}?v={lwc[3]}", pravitrade.page({}, "Jure")[1])

    def test_api_routes(self):
        h = self._get("/pravi-trade/api/first")
        self.assertEqual(h.sent[0][0], 200)
        self.assertEqual(h.sent[0][2], "application/json")
        self.assertEqual(json.loads(h.sent[0][1])["v"], 1)
        self.assertIn("html", json.loads(self._get("/pravi-trade/api/first?html=1").sent[0][1]))
        self.assertEqual(self._get("/pravi-trade/api/first", "Nepoznat").sent[0][0], 403)
        self.assertEqual(self._get("/pravi-trade/l/ostalo").sent[0][0], 200)
        self.assertEqual(self._get("/pravi-trade/l/nista").sent[0][0], 404)
        with mock.patch.object(apterm, "kupiti_html", side_effect=RuntimeError("x")), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(self._get("/pravi-trade/l/kupiti").sent[0][:2], (500, b""))   # the block greys, no text


class Portfelj(HandlerMixin, Env):
    """11.11. (Jure: "nestao je graf profit and loss cjelokupnog portfelja: koliko trenutno imamo"): the "Portfelj"
    card under the token's chart, always shown, live and paper apart (GET /pravi-trade/api/portfelj)."""

    def test_the_card_is_on_the_main_view_with_the_live_numbers(self):
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        # 14.11. (Jure: "na vrhu ... graf, brza kupovina i pozicije"): under the tables, still in the first view
        at = [body.index(k) for k in ("id=apx-chartbox", "id=kupi-odmah", "class=apx-tabs", "id=pozicije", "id=apx-port",
                                      "id=kupiti")]
        self.assertEqual(at, sorted(at))
        port = body[body.index("id=apx-port"):body.index("id=kupiti")]
        for k in ("<h2 class=apx-h2 data-sec=\"\">Portfelj</h2>", ">Ukupno<", ">Slobodno<", ">U pozicijama<", ">Danas<",
                  ">Ukupni PnL<", "1,815", "1,772", "0,043", "+3,7"):     # SUMMARY of tests/test_apui_offline
            self.assertIn(k, port, k)
        self.assertNotIn("id=vrijednost", body)                           # the old chart under the settings: gone
        _, guest = pravitrade.page({}, "Ivan")
        self.assertIn("id=apx-port", guest)                               # a viewer sees it too

    def test_live_and_paper_apart(self):
        self.seed()
        lg = self.lg
        now = time.time()
        lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, ret, source) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", (settings.LEAGUE_USER, "A" * 44, "AAA", now - 7200, now - 3600, "closed",
                                                    25.0, 5.0, 0.2, "copy"))
        lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, ret, source) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", (settings.LEAGUE_USER, "B" * 44, "BBB", now - 7200, now - 1800, "closed",
                                                    25.0, -2.0, -0.08, "copy"))
        lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, ret, source) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", ("Ivan", "C" * 44, "CCC", now - 7200, now - 1800, "closed", 25.0, 50.0,
                                                    2.0, "ručno"))
        lg.commit()
        with mock.patch.object(apterm, "_sol_usd", lambda tcon: 200.0):
            live = apterm.portfelj("Jure", "live", 7, now=NOW)
            paper = apterm.portfelj("Jure", "paper", 7, now=NOW)
        k = live["kpi"]
        self.assertEqual((k["value_sol"], k["free_sol"], k["pos_sol"], k["total_sol"], k["total_pct"]),
                         (1.815, 1.772, 0.043, 0.065, 3.71))
        self.assertEqual(k["pos_n"], 1)                                   # the live position (the paper one is apart)
        self.assertAlmostEqual(k["today_sol"], 0.03 - 0.002 + 0.002, places=6)   # the closed live trade of the seed
        self.assertTrue(live["series"])                                   # the value line from trade/equity
        self.assertTrue(all(p["t"] >= NOW - 7 * 86400 for p in live["series"]))
        self.assertEqual(set(live["series"][0]), {"t", "v", "u", "pnl", "flow"})
        p = paper["kpi"]
        self.assertIsNone(p["free_sol"])                                  # the demo account has no "free" amount
        self.assertEqual((p["realized_usd"], p["today_usd"], p["pos_n"]), (3.0, 3.0, 2))
        self.assertEqual([(s["sym"], s["u"]) for s in paper["series"]], [("AAA", 5.0), ("BBB", 3.0)])   # running sum
        self.assertAlmostEqual(paper["series"][-1]["v"], 3.0 / 200)
        self.assertIs(apterm.portfelj("Jure", "live", 7, now=NOW + 1), live)   # cached PORT_TTL_S
        self.assertIsNone(apterm.portfelj("Nepoznat"))
        h = self._get("/pravi-trade/api/portfelj?m=paper&d=7")
        self.assertEqual((h.sent[0][0], h.sent[0][2]), (200, "application/json"))
        self.assertEqual(self._get("/pravi-trade/api/portfelj", "Nepoznat").sent[0][0], 403)


class OnlyConclusions(HandlerMixin, Env):
    """11.11. (Jure: "prikazuj samo ono što ima zaključak ili nešto radi")."""

    def follow(self, kind, target, closed_trades, wins=0):
        fid = copy.follow(self.lg, settings.LEAGUE_USER, kind, target, "", 25, 5, "tpsl", "15%", "-20%")
        for i in range(closed_trades):
            pnl = 2.0 if i < wins else -1.0
            self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd, ret, "
                            "source, follow_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (settings.LEAGUE_USER, f"T{fid}{i}".ljust(44, "1"), "T", NOW - 9000, NOW - 8000, "closed", 25.0,
                             pnl, pnl / 25, f"copy {target}", fid))
        self.lg.commit()
        return fid

    def test_follows_under_ten_closed_are_folded(self):
        self.follow("wallet", "W" * 44, 12, wins=7)      # representative
        self.follow("wallet", "V" * 44, 3, wins=1)       # n < 10
        self.follow("wallet", "U" * 44, 0)
        self.follow("kol", "ansem", 2, wins=2)           # n < 10: the only influencer
        html = apterm.lazy("pratimo", "Jure")
        main, wait = html.split("<details class=apx-skoro>", 1)
        nb = " "
        self.assertIn(f"58{nb}%", main.split("id=pr-i")[0])               # 7 of 12: a conclusion, in the list
        self.assertIn("U procjeni: 2 walleta (n &lt; 10)", html)
        self.assertIn("U procjeni: 1 influencer (n &lt; 10)", html)
        self.assertNotIn(f"33{nb}%", html)                                 # 1 of 3: no hit rate shown at all
        self.assertNotIn(f"100{nb}%", html)                                # 2 of 2: neither
        self.assertIn("u procjeni</small>", html)
        self.assertNotIn("id=pratim", html)                                # the forms are under "Postavke"
        self.assertEqual(html.count("data-sub="), 2)                       # Walleti, Influenceri; no empty Tokeni tab
        self.assertIn("data-x-src=/pravi-trade/zovu data-x-every=15 data-hide-empty", html)   # the feed: only with calls
        self.assertIn("<div class=apx-feed data-hide-wrap hidden>", html)

    def test_nobody_followed_is_no_card(self):
        self.assertEqual(apterm.lazy("pratimo", "Jure"), "")
        self.assertEqual(self._get_status("/pravi-trade/l/pratimo"), 200)    # empty is an answer, not a 404
        self.assertEqual(self._get_status("/pravi-trade/l/nista"), 404)

    def _get_status(self, path):
        return self._get(path).sent[0][0]

    def test_proposals_one_line_when_empty_and_n_under_ten_folded(self):
        from proposals import strategies   # noqa: F401 - the module kupiti_html reads
        with mock.patch.object(apterm, "_proposals", lambda owner, now: ([], [], [], "paper")):
            html = apterm.lazy("kupiti", "Jure")
        self.assertTrue(html.startswith("<p class=apx-one id=prijedlozi-trade>Nema prijedloga s EV &gt; 0 · zadnja provjera "))
        self.assertNotIn("<h2", html)                                      # no title, no rest of the block
        self.assertNotIn("prikaži skoro", html)

        def prop(pid, n, ev):
            return {"id": pid, "token": f"P{pid}".ljust(44, "1"), "symbol": f"P{pid}", "strategy": "momentum",
                    "sources": [], "ev_pct": ev, "p_tp": 0.5, "size_sol": 0.1, "expires_ts": NOW + 600,
                    "row": {"n": n, "entry_zone": {}, "buy": {"tp": "+20%", "sl": "-20%"}}}
        from proposals import view
        with mock.patch.object(apterm, "_proposals", lambda owner, now: ([prop(1, 40, 3.0), prop(2, 4, 9.0)], [], [], "paper")), \
                mock.patch.object(view, "_row_inner", lambda p, esc: ""), \
                mock.patch.object(view, "entry_state", lambda p, now: {"state": "čeka ulaz"}, create=True):
            html = apterm.lazy("kupiti", "Jure")
        self.assertIn("Što kupiti <span class=apx-cnt>1</span>", html)   # only the one measured on 10+ outcomes
        main = html.split("<details", 1)[0]
        self.assertIn("id=pr-1", main)
        self.assertNotIn("id=pr-2", main)
        self.assertIn("U procjeni: 1 prijedlog (n &lt; 10)", html)

    def test_near_misses_with_blocks_render(self):
        """11.11.: proposals/build gives a near miss's blocks as [{"key", "text"}]; "prikaži skoro" joined them as text
        and the whole Što kupiti card fell (TypeError) as soon as one proposal and one blocked near miss stood."""
        from proposals import view
        prop = {"id": 1, "token": "P1".ljust(44, "1"), "symbol": "P1", "strategy": "momentum", "sources": [],
                "ev_pct": 3.0, "p_tp": 0.5, "size_sol": 0.1, "expires_ts": NOW + 600,
                "row": {"n": 40, "entry_zone": {}, "buy": {"tp": "+20%", "sl": "-20%"}}}
        near = [{"token": "N1".ljust(44, "1"), "symbol": "BLOK", "strategies": ["range"], "ev_pct": 4.0,
                 "why": "likvidnost ispod $15k", "blocks": [{"key": "liq", "text": "likvidnost ispod $15k"},
                                                             {"key": "vol", "text": "volumen 1 h < 5k <x>"}]},
                {"token": "N2".ljust(44, "1"), "symbol": "EVNEG", "strategies": ["momentum"], "ev_pct": -1.0,
                 "why": "EV -1,0 % nakon troška", "blocks": []},
                {"token": "N3".ljust(44, "1"), "symbol": "STARO", "strategies": [], "why": "stari zapis",
                 "blocks": ["već tekst"]}]
        with mock.patch.object(apterm, "_proposals", lambda owner, now: ([prop], near, [], "paper")), \
                mock.patch.object(view, "_row_inner", lambda p, esc: ""), \
                mock.patch.object(view, "entry_state", lambda p, now: {"state": "čeka ulaz"}, create=True), \
                mock.patch("builtins.print"):
            html = apterm.lazy("kupiti", "Jure")
        self.assertIn("id=pr-1", html)
        self.assertIn("prikaži skoro (3)", html)
        self.assertIn("likvidnost ispod $15k; volumen 1 h &lt; 5k &lt;x&gt;", html)   # the texts, escaped
        self.assertIn("EV -1,0 % nakon troška", html)                              # no blocks: the why
        self.assertIn("već tekst", html)                                           # an old row of plain strings
        self.assertNotIn("{'key'", html)

    def test_paper_pnl_under_ten_closed_is_no_conclusion(self):
        self.assertEqual(apterm._kpi_cells({"total_sol": 0.1, "total_usd": 16.0, "n_closed": 4}, "paper")[-1][2],
                         "u procjeni: 4 zatvorenih (n < 10)")
        self.assertNotIn("u procjeni", apterm._kpi_cells({"total_sol": 0.1, "total_usd": 16.0, "n_closed": 12},
                                                         "paper")[-1][2])
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("t.n < 10 ? 'u procjeni'", js)                       # PnL by day: no win rate under 10
        self.assertIn("(k.n_closed || 0) < 10", js)

    def test_hidden_cards_keep_asking_and_show_themselves(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        for k in ("const hides = el => el.dataset.hideEmpty !== undefined", "wrapOf(el).hidden = empty",
                  "(hides(el) || (shown(el) && inView(el)))", "if (hides(el)) wrapOf(el).hidden = true", "}, 5000);",
                  "el.dataset.slow"):
            self.assertIn(k, js)
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        self.assertIn('data-slow="Prijedlozi još nisu stigli · pokušavam ponovno"', body)   # always there: says so
        for k in ("id=apx-chartbox", "id=apx-port", "id=pozicije", "id=nalozi", "id=kupi-odmah", "id=kupiti"):
            self.assertIn(k, body)                                         # always shown, also without data
        self.assertIn('<h2 data-sec="">Postavke</h2>', body)               # one closed "Postavke" at the bottom
        self.assertEqual(body.count("<details class=apx-acc"), 1)


class ColumnHelpAndRanges(Candles):
    """11.11. (Jure): an info button on every column; "Koga pratimo / Tokeni" in the order of buying priority with
    the place in the range said in words, the entry state, DexScreener and Solscan."""

    def rng(self, rc, tok, sym, score, pos, ts=None, status="aktivan", active=True, state=None):
        from rangedca import data as rdata
        lo, hi = 100_000 / 1e9, 200_000 / 1e9   # low 100k, top 200k (MC = price x 1e9)
        z = {"range_low_low": lo, "range_low_top": lo * 1.1, "range_high_low": hi * 0.9, "range_high_top": hi}
        px = lo + pos / 100 * (hi - lo)
        rdata.save_range(rc, tok, {"ts": ts or NOW - 60, "status": status, "active": active, "score": score,
                                   "pos_pct": pos, "zones": z, "metrics": {"price": px, "mcap": px * 1e9, "supply": 1e9}},
                         state or {}, sym)

    def test_every_column_has_its_info_button(self):
        self.seed()
        _, body = pravitrade.page({"sve": "1"}, "Jure")
        heads = re.findall(r'<div class="apx-(?:tr|krow)[^"]*apx-th[^"]*">(.*?)</div>', body)
        self.assertGreaterEqual(len(heads), 3)                             # positions, orders, history (+ proposals…)
        for h in heads:
            for cell in re.findall(r"<span(?: class=n)?>(.*?)</span>(?=<span|$)", h):
                if cell and not cell.startswith("<span"):
                    self.assertIn('class="tip apx-i" tabindex=0 role=button', cell, cell)
        self.assertNotIn("aria-hidden=true><span>Token", body)             # the titles are real now (focusable help)
        for k in ("Ukupno", "Slobodno", "U pozicijama", "Danas", "Ukupni PnL"):   # the Portfelj numbers
            self.assertIn(f'<span>{k}<span class="tip apx-i" tabindex=0 role=button aria-label="Što znači: {k}"', body)
        self.assertEqual(json.loads(re.search(r"<script type=application/json id=apx-first>(.*?)</script>", body).group(1))
                         ["help"]["win rate"], apterm.COL_HELP["win rate"])   # PnL by day: the same words in ap.js
        self.assertIn("Range kupuje samo pri dnu (donja zona, ~0–15 % / bottom zona), a prodaje u gornjoj zoni.",
                      apterm.COL_HELP["U rasponu"])
        css = apterm.CSS
        self.assertIn(".apx-tr.apx-th,.apx-krow.apx-th{display:flex;flex-wrap:wrap", css)   # phone: one wrapping line

    def test_range_tokens_by_buying_priority_with_entry_words_and_links(self):
        from rangedca import data as rdata
        rc = rdata.connect(self.rdb)
        a, b, c, d, e = ("A" * 40 + "pump", "B" * 40 + "pump", "C" * 40 + "pump", "D" * 40 + "pump", "E" * 40 + "pump")
        self.rng(rc, a, "VRH", 0.95, 93)                 # top zone: no
        self.rng(rc, b, "SREDINA", 0.9, 67)              # waits for the bottom, far
        self.rng(rc, c, "BLIZU", 0.75, 30)               # waits for the bottom, near: before SREDINA despite its score
        self.rng(rc, d, "DNO", 0.72, 10)                 # in the entry zone
        self.rng(rc, e, "PROBOJ", 0.99, 130)             # breakout: last
        rc.commit()
        rc.close()
        with mock.patch("rangedca.view.one", lambda tok, r, now, *a, **k: {
                "entry_ready": tok == d, "entry_now": "ulaz bi prošao" if tok == d else "čeka",
                "status": "breakout" if (r.get("pos_pct") or 0) > 100 else r.get("status")}):
            html = apterm._watch_tokens(NOW)
        order = [html.index(s) for s in (">DNO<", ">BLIZU<", ">SREDINA<")]
        self.assertEqual(order, sorted(order))                             # ready, then the nearest to the bottom
        self.assertLess(html.index(">SREDINA<"), html.index(">VRH<"))     # the top zone and breakouts last
        self.assertLess(html.index(">SREDINA<"), html.index(">PROBOJ<"))
        nb = " "
        self.assertIn(f'<span class="n apx-ulaz up" data-l="Ulaz" title="ulaz bi prošao">spreman</span>', html)
        self.assertRegex(html, rf"čeka dno \(−\d+{nb}%\)")
        self.assertIn(">ne (vrh)<", html)
        self.assertIn(">ne (breakout)<", html)
        self.assertIn(f'10{nb}%<small class="up">u zoni ulaza</small>', html)
        self.assertIn(f'67{nb}%<small class="">sredina</small>', html)
        self.assertIn(f'93{nb}%<small class="dn">blizu vrha – ne kupuj</small>', html)
        self.assertIn(f'href="https://dexscreener.com/solana/{d}" target=_blank rel=noopener', html)
        self.assertIn(f'href="https://solscan.io/token/{d}" target=_blank rel=noopener', html)
        self.assertIn('aria-label="Što znači: Ulaz"', html)

    def test_live_candidates_need_kupi_ev_and_ten_sources(self):
        def fast(dec, ev, n, state="done"):
            return {"state": state, "decision": dec, "label": "KUPI (paper)" if dec else "provjera u tijeku",
                    "ev_pct": ev, "ev_lo_pct": None, "ev_hi_pct": None, "p": 0.6, "n": n, "origin": "source"}
        rows = [{"token": "L1".ljust(44, "1"), "symbol": "L1", "fast": fast("BUY_PAPER", 4.0, 12)},
                {"token": "L2".ljust(44, "1"), "symbol": "L2", "fast": fast("BUY_PAPER", 4.0, 3)},     # n < 10
                {"token": "L3".ljust(44, "1"), "symbol": "L3", "fast": fast("BUY_PAPER", -1.0, 30)},   # EV <= 0
                {"token": "L4".ljust(44, "1"), "symbol": "L4", "fast": fast(None, None, 0, "pending")},
                {"token": "L5".ljust(44, "1"), "symbol": "L5", "fast": fast("SKIP", 6.0, 30)}]          # PRESKOČI
        from ui import zivo
        with mock.patch.object(apterm, "_proposals", lambda owner, now: ([], [], [], "paper")), \
                mock.patch.object(zivo, "rows", lambda now: rows):
            html = apterm.lazy("kupiti", "Jure")
        main = html.split("<details", 1)[0]
        self.assertIn(">L1<", main)                                        # KUPI, EV > 0, 12 sources: in the list
        self.assertNotIn(">L5<", html)                                     # a PRESKOČI goes to "Preskočeni" (fast/live)
        for s in ("L2", "L3", "L4"):
            self.assertNotIn(f">{s}<", main)
            self.assertIn(f">{s}<", html)                                  # folded, not lost
        self.assertIn("Živi kandidati alata: provjera u tijeku ili n izvora &lt; 10 (3)", html)
        self.assertNotIn("nije izmjeren", html)

    def test_a_part_is_asked_again_when_the_tab_comes_back(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        for k in ("document.addEventListener('visibilitychange', wake)", "addEventListener('pageshow'",
                  "el._retry = setTimeout(() => { el._retry = 0; loadBox(el); }, 10000)",
                  "Osvježavanje nije uspjelo (mreža ili poslužitelj); pokušavam ponovno.",
                  "if (window.apPatch(el, h) === false) setTimeout(() => loadBox(el), 3000)"):
            self.assertIn(k, js)


class CardsOpenAtOnce(Env):
    """11.11. (Jure: "klikom na zatvorene kartice ne otvaraju se iz prvoga, kao da je lag; tako je za sve kartice")."""

    def test_nothing_shifts_or_closes_under_a_tap(self):
        from ui import secnav
        self.assertNotIn("document.addEventListener('click',later)", secnav.JS)   # no chip rebuild on every click
        self.assertIn("new MutationObserver(ms=>{for(const m of ms)if(!mine(m.target)", secnav.JS)
        self.assertIn("requestIdleCallback", secnav.JS)
        self.assertIn("const carry=(o,n)=>", pravitrade.PATCH_JS)         # a swapped part keeps its open boxes
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("rootMargin: '1200px'", js)                         # the parts load well before the finger
        for k in ("function warmBoxes()", "'touchstart', pf", "'pointerenter', pf", "function keepOpen(el, swap)",
                  "keepOpen(pos,", "keepOpen(ord,"):
            self.assertIn(k, js)
        self.assertIn(".apx-lz,.apx-pane,#apx-hist{overflow-anchor:none}", apterm.CSS)
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        box = body[body.index("id=apx-ostalo"):]
        self.assertIn("Učitavam postavke…", box)                          # an opened box says so at once


if __name__ == "__main__":
    unittest.main()
