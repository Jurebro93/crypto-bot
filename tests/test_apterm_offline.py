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

    def test_lazy_parts_and_api_refuse_strangers(self):
        for name in ("kupiti", "pratimo", "povijest", "ostalo"):
            self.assertIsNone(apterm.lazy(name, "Nepoznat"))
        self.assertEqual(apterm.lazy("nista", "Jure"), "")
        self.assertIsNone(apterm.tick_json("Nepoznat"))
        self.assertIsNone(apterm.candles_data("Nepoznat", LIVE_T))


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
                 "/pravi-trade/limitdel", "/pravi-trade/switch", "/pravi-trade/sellall"}
        self.assertEqual(acts - known, set())                               # no new POST route
        buy = next(n for a, n in got if a == "/pravi-trade/buy")
        self.assertEqual(buy, {"token", "sol", "at", "tp", "sl", "exit"})   # prijedlog is added by Kupi on a proposal
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
        for k in ("Što kupiti", "Koga pratimo", "Postavljanje walleta", "Danas uživo", "id=apx-ostalo open"):
            self.assertIn(k, full)
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

    def test_settings_put_empty_sections_grey_at_the_bottom(self):
        html = apterm.lazy("ostalo", "Jure")
        dim = html.index("class=apx-dim")
        self.assertGreater(html.index(">Grok (MCP)<"), dim)               # "isključen": grey, at the bottom
        self.assertLess(html.index("Tko vidi stranicu"), dim)             # "1 pozvanih": in the list
        self.assertLess(html.index(">Pravila<"), dim)
        self.assertLess(html.index("Kako je zaštićeno"), dim)
        self.assertNotIn("id=ev-znacajke", html)                           # no report: the section is left out


class LiveFirst(Env):
    def test_paper_badge_grey_and_live_always_first(self):
        self.seed()
        _, body = pravitrade.page({}, "Jure")
        pos = body[body.index("id=pozicije"):body.index("id=nalozi")]
        self.assertLess(pos.index(LIVE_T), pos.index(PAPER_T))            # live first, although opened earlier
        self.assertLess(pos.index("Probno (paper)"), pos.index(PAPER_T))   # a divider before the paper ones
        self.assertIn('<span class="apx-badge live">uživo</span>', pos)
        self.assertIn('<span class="apx-badge paper">paper</span>', pos)
        self.assertRegex(pos, r'class="apx-tr apx-pos is-paper"[^>]*data-tok="' + PAPER_T)
        self.assertIn(".apx-badge.paper{background:var(--line2);color:var(--mut)}", apterm.CSS)   # grey
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
        self.assertIn("el.classList.toggle('old', a > 60)", js)           # the browser counts the same way

    def test_cost_estimate_formula(self):
        from league import store as lstore
        c = apterm.cost_pct(1000, 100_000)
        slip = 2 * 1000 / (50_000 + 1000) * 100                             # 2 x size / (liq/2 + size)
        self.assertAlmostEqual(c["slip_pct"], round(slip, 3))
        self.assertAlmostEqual(c["cost_pct"], round(2 * lstore.FEE * 100 + slip, 3))   # + 2 x fee per side
        self.assertTrue(c["warn"])                                          # 3,9 % slippage: above 2 %
        self.assertFalse(apterm.cost_pct(400, 100_000)["warn"])            # 1,6 %: no warning
        self.assertFalse(apterm.cost_pct(100, 1_000_000)["warn"])
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


if __name__ == "__main__":
    unittest.main()
