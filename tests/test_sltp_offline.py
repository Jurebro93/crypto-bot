"""The Autopilot's "Uredi SL-TP", "Što kupiti" Kupi and the buy panel's Token field (11.11., Jure):

  * "nemam nigdje button spremi ... samo Kupi 0,15": the open position's SL / TP editor (ui/apterm.sltp_html) in its
    row and in the panel's "Tvoja pozicija", prefilled with the TP / SL as stored, one "Spremi SL/TP" on the route it
    always had (POST /pravi-trade/exit); run_ui answers a fetch of it with JSON, the first view is built anew after it;
  * "neka prepopulira sve stavke": every Kupi in "Što kupiti" (proposals and the tool's live picks, main list and the
    folded blocks) fills token, SOL, TP, SL, trailing and the exit "moj TP/SL"; a proposal without its buy form takes
    its exit levels; a live pick takes the fast path's exit (trade/edge rule E);
  * "da nisam krivo pastao adresu": GET /pravi-trade/api/token names the address in the Token field from the shared
    DexScreener cache (found / not found / DexScreener down);
  * owner's rule "Kupi mora koristiti isključivo mint iz polja": a buy of another token than the chart's (chart_mint)
    is refused without confirm_mismatch=1, before anything is written; the buy is always the field's token.
No network: the live numbers go into ui/pravitrade's shared cache by hand.

    python3 -m unittest tests.test_sltp_offline
"""
import html as _html
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

from league import copy  # noqa: E402
from tests.test_apterm_offline import LIVE_T, NOW, PAPER_T, Env, market  # noqa: E402
from tests import test_pozicije_izlaz_offline as tpi  # noqa: E402
from trade import settings  # noqa: E402
from ui import apterm, pravitrade  # noqa: E402

_WAKE = mock.patch.object(copy, "WAKE", os.path.join(tempfile.mkdtemp(), ".copy_wake"))
OTHER = "Bxue111111111111111111111111111111111111pump"


def setUpModule():
    _WAKE.start()


def tearDownModule():
    _WAKE.stop()


def pks(html):
    """The payload of every row's own Kupi in "Što kupiti" (the button in the row's .apx-act)."""
    return [json.loads(_html.unescape(m)) for m in
            re.findall(r'<span class=apx-act><button type=button class="apx-b buy" data-pk="([^"]+)">Kupi</button>', html)]


def prop(pid, tok, n, buy=None, ex=None, size=0.5, **row):
    return {"id": pid, "token": tok, "symbol": f"P{pid}", "strategy": "range", "sources": ["range"], "ev_pct": 5.0,
            "p_tp": 0.6, "size_sol": size, "expires_ts": NOW + 1800, "status": "novo",
            "row": {"n": n, "entry_zone": {"mcap_low": 1, "mcap_high": 2}, **({"buy": buy} if buy else {}),
                    "exits_mcap": ex or {}, **row}}


class StoKupiti(Env):
    def html(self, props, live):
        from proposals import view
        from ui import zivo
        cfg = pravitrade._cfg(self.con)
        with mock.patch.object(apterm, "_proposals", lambda owner, now: (props, [], [], "paper")), \
                mock.patch.object(zivo, "rows", lambda now=None, **k: live), \
                mock.patch.object(view, "_row_inner", lambda p, esc: ""):
            return apterm.kupiti_html(self.con, cfg, True, NOW), cfg

    def test_every_row_fills_token_sol_tp_sl_trailing_and_tpsl(self):
        def fast(dec, ev, n, state="done"):
            return {"state": state, "decision": dec, "label": "x", "ev_pct": ev, "p": 0.6, "n": n, "origin": "source"}
        props = [prop(1, "P1".ljust(44, "1"), 40, {"tp": "$160k", "sl": "$95k"}, {"tp": [160_000], "sl": 95_000, "trailing_pct": 12}),
                 prop(2, "P2".ljust(44, "1"), 22, None, {"tp": [69_000], "sl": 54_000, "trailing_pct": 8}),   # an older row
                 prop(3, "P3".ljust(44, "1"), 4, {"tp": "15%", "sl": "-10%"}, {"trailing_pct": 8})]          # n < 10: folded
        live = [{"token": "L1".ljust(44, "1"), "symbol": "L1", "fast": fast("BUY_PAPER", 4.0, 12), "live": {"mcap": 9e4}},
                {"token": "L2".ljust(44, "1"), "symbol": "L2", "fast": fast(None, None, 0, "pending"), "live": {}}]
        html, cfg = self.html(props, live)
        got = {p["sym"]: p for p in pks(html)}
        self.assertEqual(sorted(got), ["L1", "L2", "P1", "P2", "P3"])          # main list and both folded blocks
        self.assertNotIn("U panel", html)
        self.assertNotIn("data-fill", html)
        for p in got.values():
            self.assertTrue(p["tp"] and p["sl"] and p["trail"], p)
            self.assertEqual(p["exit"], "tpsl")
            self.assertLessEqual(float(p["sol"]), cfg["max_sol_per_trade"])   # capped by the per-trade limit
        self.assertEqual((got["P1"]["tp"], got["P1"]["sl"], got["P1"]["trail"], got["P1"]["id"]), ("$160k", "$95k", 12, 1))
        self.assertEqual((got["P2"]["tp"], got["P2"]["sl"]), ("$69k", "$54k"))   # no buy form: its exit levels
        for s in ("L1", "L2"):   # the fast path's exit, no proposal id (an ordinary buy)
            self.assertEqual((got[s]["tp"], got[s]["sl"], got[s]["trail"], got[s]["kind"]), ("15%", "-10%", 8.0, "alat"))
            self.assertNotIn("id", got[s])
            self.assertIn("Ručna kupnja postavlja samo TP/SL", got[s]["plan"])
        self.assertIn("(KUPI)", got["L1"]["plan"])

    def test_proposal_fill_falls_back_to_the_exit_levels(self):
        self.assertEqual(apterm.proposal_fill(prop(1, "T" * 44, 40, None, {"tp": [1_250_000], "sl": 900_000}), 0.1)
                         ["tp"], "$1.250m")
        f = apterm.proposal_fill(prop(1, "T" * 44, 40, None, None, tp_pct=25.0, sl_pct=12.5), 0.1)
        self.assertEqual((f["tp"], f["sl"], f["sol"]), ("25%", "-12.5%", "0.1"))
        f = apterm.proposal_fill(prop(1, "T" * 44, 40, None, None), 0.1)
        self.assertEqual((f["tp"], f["sl"]), ("", ""))                       # nothing to derive: the panel's defaults

    def test_the_kupi_under_details_uses_the_rows_payload(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("main = row && $(':scope > .apx-act [data-pk]', row)", js)
        self.assertIn("if (go) go.focus({ preventScroll: true });", js)     # the panel's Kupi ready at once
        self.assertIn("c.classList.toggle('on', !!tp && nLvl(c.dataset.tp || c.dataset.etp) === tp)", js)


class Editor(Env):
    def page(self, qs=None):
        return pravitrade.page(qs or {}, "Jure")[1]

    def test_row_editor_is_prefilled_with_one_save_button(self):
        self.seed()
        body = self.page()
        pid = re.search(r'id=poz-(\d+) data-key="' + LIVE_T, body).group(1)
        self.assertIn(f'data-edit="ed-{pid}" aria-controls=ed-{pid} aria-expanded=false>Uredi SL-TP</button>', body)
        ed = body.split(f"id=ed-{pid} hidden>", 1)[1].split("<h4>DCA dokup", 1)[0]
        self.assertIn("SL / TP · LIVE", ed)
        self.assertIn('action=/pravi-trade/exit class="apx-f apx-sltp" data-sltp data-base="340000.0"', ed)
        self.assertIn(f"<input type=hidden name=id value={pid}>", ed)
        self.assertIn('<input name=tp value="30%"', ed)                      # as stored (percent of the entry)
        self.assertIn('<input name=sl value="-40%"', ed)
        self.assertIn("<button class=apx-go data-save>Spremi SL/TP</button>", ed)
        self.assertIn("data-edit-close>Odustani</button>", ed)
        self.assertEqual(ed.count("data-etp="), 4)                           # +15/+30/+50/+100: they only fill
        self.assertNotIn("data-tp=", ed)                                     # (data-tp would write the buy panel)
        self.assertEqual(ed.count("<form"), 1)                               # no chip posts by itself any more

    def test_panel_card_of_the_selected_position_and_the_new_buy_note(self):
        self.seed()
        body = self.page({"m": LIVE_T})
        pid = re.search(r'id=poz-(\d+) data-key="' + LIVE_T, body).group(1)
        card = body.split("id=apx-mypos", 1)[1].split('<div class=apx-wal>', 1)[0]
        for k in ("Tvoja pozicija", "Ulaz (MC)", "$340.0k", "Sada (MC)", "$412.0k", "PnL", "SL", "−40 %", "TP",
                  f"data-edit=pe-{pid}", f'id=pe-{pid} hidden><form method=post action=/pravi-trade/exit',
                  "Spremi SL/TP", f'data-key="{LIVE_T}:live"'):
            self.assertIn(k, card)
        self.assertIn(f"TP/SL ovdje vrijede samo za <b>novu kupnju</b>. Za otvorenu poziciju: <button type=button "
                      f"class=apx-lnk data-edit=pe-{pid}>Uredi SL-TP pozicije LIVE</button>", body)
        self.assertLess(body.index("id=apx-mypos"), body.index("id=apx-buy"))   # on top of the panel
        # a token without a position: an empty box a refresh can fill, and the note points to the table
        body = self.page({"m": OTHER})
        self.assertIn("<div class=apx-mypos id=apx-mypos hidden></div>", body)
        self.assertIn("Za otvorenu poziciju: „Uredi SL-TP” u tablici Pozicije.", body)
        # the JSON's side panel (what a refresh swaps in) carries the same card
        side = json.loads(apterm.first_json("Jure", LIVE_T, with_html=True))["html"]["side"]
        self.assertIn("Tvoja pozicija", side)

    def test_save_answers_a_fetch_with_json_and_the_next_first_view_is_fresh(self):
        self.seed()
        import run_ui
        pid = json.loads(apterm.first_json("Jure", LIVE_T))["positions"][0]["pid"]
        self.assertEqual(json.loads(apterm.first_json("Jure", LIVE_T))["positions"][0]["tp"], "30%")   # cached now

        def post(path, form, fetch):
            body = "&".join(f"{k}={v}" for k, v in form.items()).encode()
            h = run_ui.Handler.__new__(run_ui.Handler)
            h.path, h.rfile, h.wfile, h.user, h.role, h.who = path, io.BytesIO(body), io.BytesIO(), "Jure", "admin", "Jure"
            h.headers = {"Content-Length": str(len(body)), "Host": "x", **({"X-Apx-Fetch": "1"} if fetch else {})}
            h.status, h.hdrs, h.sent = [], [], []
            h.send_response = lambda code, msg=None: h.status.append(code)
            h.send_header = lambda k, v: h.hdrs.append((k, v))
            h.end_headers = lambda: None
            h._send = lambda code, body=b"", ctype="text/html", gz=None, translated=False: h.sent.append((code, body, ctype))
            with mock.patch.object(run_ui, "AUTH", False):
                h.do_POST()
            return h

        h = post("/pravi-trade/exit", {"id": pid, "tp": "60%25", "sl": "%2485k"}, fetch=True)
        code, raw, ctype = h.sent[0]
        self.assertEqual((code, ctype), (200, "application/json"))
        to = json.loads(raw)["to"]
        self.assertTrue(to.startswith("/pravi-trade?ok="), to)
        self.assertTrue(to.endswith(f"#poz-{pid}"))
        p = json.loads(apterm.first_json("Jure", LIVE_T))["positions"][0]   # not the 3-s cached view
        self.assertEqual((p["tp"], p["sl"]), ("60%", "$85k"))
        h = post("/pravi-trade/exit", {"id": pid, "tp": "abc"}, fetch=True)   # an error: in the JSON, not a redirect
        self.assertIn("err=", json.loads(h.sent[0][1])["to"])
        h = post("/pravi-trade/exit", {"id": pid, "tp": "50%25"}, fetch=False)   # the plain form: the redirect as before
        self.assertEqual(h.status, [303])
        self.assertTrue(dict(h.hdrs)["Location"].endswith(f"#poz-{pid}"))

    def test_the_tables_wait_while_an_editor_is_open(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("const busy = el => el.contains(document.activeElement) || !!$('.apx-edit:not([hidden])', el) || pressed(el);", js)
        self.assertIn("if (pos && !busy(pos)) { keepOpen(pos, () => { pos.innerHTML = j.html.pos; }); S.stale = 0; }", js)
        self.assertIn("headers: { 'X-Apx-Fetch': '1' }", js)
        self.assertIn("f.elements.tp.focus({ preventScroll: true })", js)


class TokenInfo(Env):
    def put(self, tok, **extra):
        with pravitrade._LOCK:
            pravitrade._LIVE_CACHE[(tok,)] = (time.time(), {tok: {**market(310_000.0), **extra}})

    def test_names_an_address_from_the_shared_cache_without_a_request(self):
        self.put(OTHER, symbol="BLUE", name="BlueBlueBlue", created_ms=(NOW - 5 * 3600) * 1000)
        with mock.patch.object(pravitrade, "_live_cached", side_effect=AssertionError("a request")):
            d = apterm.token_info("Jure", f"  {OTHER} ", now=NOW)
        self.assertEqual({k: d[k] for k in ("mint", "found", "sym", "name", "mcap", "liq", "age_s")},
                         {"mint": OTHER, "found": True, "sym": "BLUE", "name": "BlueBlueBlue", "mcap": 310_000.0,
                          "liq": 60_000.0, "age_s": 5 * 3600})
        self.assertIsNone(apterm.token_info("Nepoznat", OTHER))               # the page's access

    def test_not_found_dexscreener_down_a_pair_link_and_no_address(self):
        from ui import prijedlog
        with mock.patch.object(prijedlog, "live_market", lambda toks, fetch=None: {}), \
                mock.patch.object(apterm, "_pair_token", lambda a: None):
            d = apterm.token_info("Jure", OTHER, now=NOW)
        self.assertEqual((d["found"], d["mint"]), (False, OTHER))
        pravitrade._LIVE_FAIL.clear()
        with pravitrade._LOCK:
            pravitrade._LIVE_CACHE.clear()
        with mock.patch.object(prijedlog, "live_market", lambda toks, fetch=None: None):
            self.assertIsNone(apterm.token_info("Jure", OTHER, now=NOW + 100)["found"])   # unknown, not "not found"
        pravitrade._LIVE_FAIL.clear()
        pair = "Pair111111111111111111111111111111111111pump"
        rows = {OTHER: {**market(310_000.0), "symbol": "BLUE", "name": "Blue", "created_ms": None}}
        with mock.patch.object(prijedlog, "live_market", lambda toks, fetch=None: {t: rows[t] for t in toks if t in rows}), \
                mock.patch.object(apterm, "_pair_token", lambda a: OTHER if a == pair else None):
            d = apterm.token_info("Jure", f"https://dexscreener.com/solana/{pair}", now=NOW + 200)
        self.assertEqual((d["found"], d["mint"], d["sym"], d["age_s"]), (True, OTHER, "BLUE", None))
        d = apterm.token_info("Jure", "nije adresa", now=NOW)
        self.assertEqual((d["found"], d["mint"]), (False, None))

    def test_the_route_and_the_live_rows_carry_the_name(self):
        from ui import prijedlog
        pairs = [{"baseToken": {"address": OTHER, "symbol": "BLUE", "name": "BlueBlueBlue"}, "priceUsd": "0.0003",
                  "liquidity": {"usd": 60000}, "marketCap": 310000, "pairCreatedAt": 1_700_000_000_000}]
        lv = prijedlog.live_market([OTHER], fetch=lambda toks: pairs)[OTHER]
        self.assertEqual((lv["symbol"], lv["name"], lv["created_ms"]), ("BLUE", "BlueBlueBlue", 1_700_000_000_000))
        self.put(OTHER, symbol="BLUE", name="BlueBlueBlue", created_ms=None)
        import run_ui
        h = run_ui.Handler.__new__(run_ui.Handler)
        h.path, h.headers, h.wfile, h.user, h.role = f"/pravi-trade/api/token?q={OTHER}", {}, io.BytesIO(), "Jure", "admin"
        h.send_response = h.send_header = lambda *a: None
        h.end_headers = lambda: None
        h.sent = []
        h._send = lambda code, body=b"", ctype="text/html", gz=None, translated=False: h.sent.append((code, body, ctype))
        with mock.patch.object(run_ui, "AUTH", False):
            h.do_GET()
        self.assertEqual(h.sent[0][0], 200)
        self.assertEqual(json.loads(h.sent[0][1])["sym"], "BLUE")

    def test_the_kupi_button_names_the_fields_token(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertNotIn("${symNow()}`.trim(); }", js.split("function label()", 1)[1].split("const fs", 1)[0])
        self.assertIn("b.disabled = s.st !== 'ok';", js)
        self.assertIn("wait: '(provjeravam adresu…)'", js)
        self.assertIn("'Token nije pronađen — provjeri adresu.'", js)
        self.assertIn("}, now ? 0 : 300);", js)                              # 300 ms after typing / pasting
        body = pravitrade.page({}, "Jure")[1]
        self.assertIn("<p class=apx-tokline data-tokline aria-live=polite></p>", body)
        self.assertIn('onsubmit="return window.apBuyOk ? apBuyOk(this) : confirm(', body)
        self.assertIn('<input type=hidden name=chart_mint value="', body)
        self.assertIn('<p class="apx-mismatch dn" data-mismatch role=alert hidden></p>', body)


class ChartGuard(tpi.Base):
    """A buy from the Autopilot's form names the chart's token (chart_mint): another token only with
    confirm_mismatch=1; the buy is the field's token; refused before anything is written."""
    CHART = "Cha1111111111111111111111111111111111111pump"

    def trades(self):
        return [tuple(r) for r in self.lg.execute("SELECT token FROM trades WHERE status='open'")]

    def test_another_token_than_the_chart_needs_its_confirmation(self):
        form = {"token": tpi.MINT, "sol": "0,05", "exit": "tpsl", "tp": "30%", "sl": "", "chart_mint": self.CHART}
        loc = self.post("/pravi-trade/buy", dict(form))
        self.assertIn("err=", loc)
        from urllib.parse import unquote
        self.assertIn(f"adresa u polju ({tpi.MINT[:4]}…{tpi.MINT[-4:]}) nije token na grafu (Cha1…pump); potvrdi kupnju "
                      "tog tokena", unquote(loc))
        self.assertEqual(self.trades(), [])                                  # nothing written
        self.assertIn("err=", self.post("/pravi-trade/buy", dict(form, at="$50k")))   # nor a buy order at a MC
        self.assertEqual(settings.raw(self.con).get("buy_orders") or [], [])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            loc = self.post("/pravi-trade/buy", dict(form, confirm_mismatch="1"))
        self.assertIn("ok=", loc)
        self.assertEqual(self.trades(), [(tpi.MINT,)])                       # the field's token, never the chart's
        self.assertIn(f"uz potvrđenu razliku od grafa {self.CHART}", out.getvalue())

    def test_without_chart_mint_or_with_the_same_token_nothing_changes(self):
        base = {"token": tpi.MINT, "sol": "0,05", "exit": "tpsl", "tp": "30%", "sl": ""}
        self.assertIn("ok=", self.post("/pravi-trade/buy", dict(base)))      # an older page, MCP: as before
        self.assertIn("ok=", self.post("/pravi-trade/buy", dict(base, chart_mint=tpi.MINT)))
        self.assertIn("ok=", self.post("/pravi-trade/buy", dict(base, chart_mint="nije-adresa")))
        # a DexScreener link that resolves to the chart's own token: no question
        from ui import real
        link = "https://dexscreener.com/solana/Pair111111111111111111111111111111111111pump"
        with mock.patch.object(real, "resolve", lambda t: (tpi.MINT, 82_000.0, "HOPE")):
            self.assertIn("ok=", self.post("/pravi-trade/buy", dict(base, token=link, chart_mint=tpi.MINT)))
        self.assertEqual(len(self.trades()), 4)


if __name__ == "__main__":
    unittest.main()
