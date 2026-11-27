"""The Autopilot page after the owner's report of 16.11. ("Kliknem na ovu otvorenu poziciju GTA V6 da mi otvori gore
graf. On mi otvori graf nekog tokena koji se zove Umbra"; the rows were named "Ce2gx9" and "PRVT6T", SL and TP showed
"–", a real-money row said "samo paper"; then: "piše da je Umbra 7 miliona, na DexScreeneru 13 milijuna; zašto pozicije
nisu u real timeu"):

  names      veliki/symbols: the quote, midcap.db, the veliki list, the page's live row, the prefix only last; the entry
             (veliki/live.enter with the 4-field quote run_ui.py really passes) stores the real symbol
  fix-up     symbols.fix: only a symbol equal to its mint's first six characters is replaced, in league.db trades and
             veliki_trades and trade.db positions and exit_fills; nothing else changes; a second run does nothing
  rows       every row of Pozicije is tied to its mint (data-tok = its name button's data-sel), the selected one is
             marked; a name that is only the start of the address is written as an address
  SL / TP    a midcap position shows the strategy's stop and target with "pravilo" and the stop's state in words;
             the page writes nothing into veliki_trades
  note       no "samo paper" on a real position; who sells it and by which rule; the demo's own sentence
  critic     the payload carries the strategy's stop and target
  FDV, age   FDV beside MC when it differs by more than 5 %; "cijena prije 2 s" / "cijena kasni 40 s"
  browser    a tap on a row loads that row's token above at 390 and 860 px (tests/apaudit_playwright.js)

    python3 -m unittest tests.test_apaudit_offline
"""
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.autopilot_staro import setUpModule, tearDownModule  # noqa: E402,F401   # 27.11.: tests the removed Autopilot (AUTOPILOT_OFF=0)

from tests import test_veliki_intra_offline as vi  # noqa: E402
from tests.test_apterm_offline import Env  # noqa: E402
from trade import executor, settings  # noqa: E402
from ui import apterm, pravitrade  # noqa: E402
from veliki import live as vlive, midcap, store as vstore, symbols, view as vview  # noqa: E402

NOW = int(time.time())
LU, PU = settings.LEAGUE_USER, settings.PAPER_USER
UMBRA = "PRVT6TkQ8sVn3FrUd2D9xs2zqDBsa3GbMJMwCQsgmeta"     # stored as "PRVT6T", midcap.db: UMBRA
GTA6 = "GTA6xPm4QhV7dT1cYw9uJbR3nK8sLfE2aZoH5iBvpump"      # stored as "GTA6" (a mint that starts with its symbol)
TROLL = "Ce2gx9KsM4vTq7WdR1pYhJ8nB3aLfU6cZoE5iXwVpump"     # stored as "Ce2gx9", midcap.db also the prefix, list: TROLL
NONAME = "Dz9mQ9Rk5tWv2YbN7cJ4hG8sLfE1aZoH6iBvXpQdpump"    # stored as "Dz9mQ9", nobody knows its symbol
MANUAL = "Manu111111111111111111111111111111111111pump"    # the owner's own buy, no rule behind it


class Dbs(Env):
    """Env (temp trade.db / league.db, the shared live cache) + midcap.db and veliki.db with the tokens' real symbols."""

    def setUp(self):
        super().setUp()
        d = self.tmp.name
        p = mock.patch.dict(os.environ, {"MIDCAP_DB": os.path.join(d, "midcap.db"), "VELIKI_DB": os.path.join(d, "veliki.db")})
        p.start()
        self.addCleanup(p.stop)
        symbols.reset()
        self.addCleanup(symbols.reset)
        vstore.reset_cache()
        mc = midcap.connect()
        for i, (mint, sym) in enumerate(((UMBRA, "UMBRA"), (GTA6, "GTA6"), (TROLL, TROLL[:6]))):
            mc.execute("INSERT INTO tokens (mint, id, symbol, member) VALUES (?,?,?,1)", (mint, i + 1, sym))
        mc.commit()
        mc.close()
        vc = vstore.connect()
        vstore.save_list(vc, [{"mint": TROLL, "symbol": "TROLL", "name": "Troll"}, {"mint": NONAME, "symbol": NONAME[:6]}], NOW)
        vc.close()
        vlive.ensure(self.lg)
        self.lg.commit()

    def veliki(self, tok, stored, entry, stop, tp, mcap, user=LU, mode="live", kind="intra", ago=600, **cols):
        """One open midcap trade as veliki/live.enter and run_trade.py leave it: the league trade without an auto rule,
        its veliki_trades row, the position that mirrors it. Returns (league trade id, position id)."""
        why = f"veliki: dnevna zona, cilj {tp / entry - 1:+.1%}, stop {stop / entry - 1:+.0%}, BTC normalno"
        tid = self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd, entry_px, entry_eff, "
                              "qty, source, entry_mcap) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                              (user, tok, stored, NOW - ago, "open", 17.0, entry, entry, 17.0 / entry, why, mcap)).lastrowid
        row = {"user": user, "token": tok, "symbol": stored, "opened_ts": NOW - ago, "trade_id": tid, "size_sol": 0.1,
               "size_usd": 17.0, "entry_px": entry, "tp_px": tp, "stop_px": stop, "rt": 0.012, "drt": 0.012, "liq": 1e6,
               "mcap": mcap, "status": "open", "kind": kind, "be_px": entry * 1.012, "first_px": entry, "lots": 1,
               "trail": 0.05, "half_frac": 0.5, **cols}
        self.lg.execute(f"INSERT INTO veliki_trades ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                        list(row.values()))
        self.lg.commit()
        pid = self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                               "qty_left, league_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (tok, stored, NOW - ago, mode, "open", why, 0.1, 1000, 1000, tid)).lastrowid
        self.con.commit()
        return tid, pid

    def three(self):
        """The owner's screenshot: three real midcap positions (wide stop, tight stop, stop at the entry)."""
        e = 0.962
        self.veliki(UMBRA, UMBRA[:6], e, e * 0.80, e * 1.112, 96_200_000.0, wide_px=e * 0.80, ago=300)
        e = 0.01204
        self.veliki(GTA6, "GTA6", e, 0.01124, e * 1.112, 12_040_000.0, wide_px=e * 0.80, tight_ts=NOW - 900, ago=3600)
        e = 0.0478
        self.veliki(TROLL, TROLL[:6], e, e * 1.012, e * 1.112, 47_800_000.0, wide_px=e * 1.012, ago=7200)
        self.live(**{UMBRA: 94_120_000.0, GTA6: 11_820_000.0, TROLL: 50_700_000.0})

    def real(self):
        """The Autopilot is live (switch + key) and panel plans run on the real account, as in production."""
        settings.put(self.con, "on", True)
        settings.put(self.con, "flag:exit_plan_live", {"mode": "live", "since": NOW})
        settings._FLAG_CACHE.clear()
        self.addCleanup(settings._FLAG_CACHE.clear)
        p = mock.patch.object(executor, "is_live", lambda cfg: True)
        p.start()
        self.addCleanup(p.stop)

    def view(self, mint=""):
        apterm.forget_first()
        return apterm.first_view("Jure", mint, fresh=True)

    def rows(self, html):
        """{mint: the row's HTML} of Pozicije."""
        out = {}
        for part in html.split("<details class=\"apx-pos")[1:]:
            part = part.split("</details>")[0]
            out[re.search(r'data-tok="([^"]+)"', part).group(1)] = part
        return out


# ---------- names ----------------------------------------------------------------------------------------------------

class Names(Dbs):
    def test_what_counts_as_a_name(self):
        self.assertTrue(symbols.is_prefix("PRVT6T", UMBRA))
        self.assertTrue(symbols.is_prefix("", UMBRA))
        self.assertTrue(symbols.is_prefix(None, UMBRA))
        self.assertFalse(symbols.is_prefix("UMBRA", UMBRA))
        self.assertFalse(symbols.is_prefix("GTA6", GTA6))            # a mint that starts with its own symbol: a name
        self.assertFalse(symbols.is_prefix("prvt6t", UMBRA))         # not the mint's own letters
        self.assertEqual(symbols.clean("  Umbra  Privacy ", UMBRA), "Umbra Privacy")
        self.assertIsNone(symbols.clean("PRVT6T", UMBRA))
        self.assertEqual(len(symbols.clean("X" * 60, UMBRA)), symbols.MAX_LEN)

    def test_the_order_of_the_sources(self):
        self.assertEqual(symbols.resolve(UMBRA, "UMB"), "UMB")                   # the quote first
        self.assertEqual(symbols.resolve(UMBRA, None), "UMBRA")                  # midcap.db
        self.assertEqual(symbols.resolve(UMBRA, UMBRA[:6]), "UMBRA")             # a quote that carries the prefix: no name
        self.assertEqual(symbols.resolve(TROLL), "TROLL")                        # midcap.db holds the prefix: the list
        self.assertIsNone(symbols.resolve(NONAME))                               # the list holds the prefix too
        self.assertEqual(symbols.known([UMBRA, TROLL, NONAME, MANUAL]), {UMBRA: "UMBRA", TROLL: "TROLL"})
        symbols.learn(NONAME, NONAME[:6])                                        # the page saw only the prefix: nothing
        self.assertIsNone(symbols.resolve(NONAME))
        symbols.learn(NONAME, "DZ")                                              # DexScreener's symbol on a live row
        self.assertEqual(symbols.resolve(NONAME), "DZ")
        symbols.learn(UMBRA, "OTHER")                                            # the databases win over the page
        self.assertEqual(symbols.resolve(UMBRA), "UMBRA")

    def test_the_name_on_a_page(self):
        self.assertEqual(symbols.name(UMBRA, "PRVT6T"), ("UMBRA", False))
        self.assertEqual(symbols.name(GTA6, "GTA6"), ("GTA6", False))            # the stored symbol when it is one
        self.assertEqual(symbols.name(MANUAL, "MANU"), ("MANU", False))
        self.assertEqual(symbols.name(NONAME, NONAME[:6]), ("Dz9mQ9…", True))    # an address, said so
        self.assertEqual(symbols.name(NONAME, None), ("Dz9mQ9…", True))

    def test_missing_databases_are_no_error(self):
        os.remove(os.environ["MIDCAP_DB"])
        os.remove(os.environ["VELIKI_DB"])
        symbols.reset()
        self.assertEqual(symbols.known([UMBRA]), {})
        self.assertEqual(symbols.name(UMBRA, "PRVT6T"), ("PRVT6T…", True))

    def test_the_market_run_ui_passes_has_no_symbol(self):
        """The cause: league/auto.fast_loop gets ui/paper.market, whose quote is (price, liquidity, url, mcap)."""
        import inspect
        import run_ui
        from ui import paper
        src = inspect.getsource(run_ui.main)
        self.assertIn("from ui.paper import market", src)
        self.assertIn("auto.fast_loop, args=(market,)", src)
        pair = {"baseToken": {"address": UMBRA, "symbol": "UMBRA"}, "priceUsd": "0.94", "liquidity": {"usd": 2e6},
                "marketCap": 9.4e7, "url": "u"}
        with mock.patch.object(paper, "live_pairs", lambda mints: [pair]):
            q = paper.market([UMBRA])[UMBRA]
        self.assertEqual(len(q), 4)                                              # no fifth field: no symbol
        self.assertEqual(vlive._sym(UMBRA, q), "UMBRA")                          # the entry's name: midcap.db
        self.assertEqual(vlive._sym(UMBRA, q + ("UMB", {})), "UMB")              # a quote with a symbol: that one
        self.assertEqual(vlive._sym(NONAME, q), NONAME[:6])                      # nobody knows it: the prefix, stored


class Entry(vi.Live):
    """veliki/live.enter through a tick, with the 4-field quote of production: the trade carries the real symbol."""

    def setUp(self):
        super().setUp()
        symbols.reset()
        self.addCleanup(symbols.reset)

    def mk4(self, toks, px=1.0e-4):
        return {t: (px, 2_000_000.0, "https://dexscreener.com/solana/raydium", 5e7) for t in toks}

    def test_the_trade_gets_the_symbol_of_the_list_and_of_the_collector(self):
        self.flag("veliki_range", "paper")
        big, mid = vi.tok(31), vi.tok(100)
        out = vlive.tick(self.lg, lambda ts: self.mk4([t for t in ts if t in (big, mid)]), now=self.now, force=True)
        got = dict(self.lg.execute("SELECT token, symbol FROM veliki_trades"))
        self.assertEqual(got, {big: "BIG", mid: "M0"}, out)                      # veliki.db list, midcap.db tokens
        self.assertEqual(dict(self.lg.execute("SELECT token, symbol FROM trades WHERE status='open'")), got)
        self.assertTrue(any("veliki demo ulaz BIG (dnevni raspon)" in x for x in out), out)
        self.assertFalse(any(big[:6] in x or mid[:6] in x for x in out), out)    # the log lines name it too


for _name in dir(vi.Live):   # only this module's own test of the fixture runs here
    if _name.startswith("test_") and _name not in Entry.__dict__:
        setattr(Entry, _name, None)


# ---------- the one-time repair --------------------------------------------------------------------------------------

class FixUp(Dbs):
    def dump(self):
        out = {}
        for con, tables in ((self.lg, ("trades", "veliki_trades")), (self.con, ("positions", "exit_fills"))):
            for t in tables:
                cur = con.execute(f"SELECT * FROM {t} ORDER BY id")
                cols = [d[0] for d in cur.description]
                out[t] = [dict(zip(cols, r)) for r in cur]
        return out

    def seed(self):
        self.three()
        self.veliki(NONAME, NONAME[:6], 0.006, 0.0048, 0.0067, 6e6, ago=9000)            # nobody can name it
        self.veliki(MANUAL, "MANU", 0.01, 0.008, 0.011, 1e7, user=PU, mode="dry")          # a proper symbol
        # a closed row and a sale's fill under the prefix, and one whose 6 letters are NOT its mint's
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, closed_ts, status, size_usd, pnl_usd) "
                        "VALUES (?,?,?,?,?,?,?,?)", (LU, UMBRA, "PRVT6T", NOW - 9000, NOW - 8000, "closed", 17.0, 1.25))
        self.lg.execute("INSERT INTO trades (user, token, symbol, opened_ts, status, size_usd) VALUES (?,?,?,?,?,?)",
                        (LU, UMBRA, "ABCDEF", NOW - 50, "closed", 17.0))
        self.lg.commit()
        self.con.execute("INSERT INTO exit_fills (ts, position_id, token, symbol, trigger, level_px, status) "
                         "VALUES (?,?,?,?,?,?,?)", (NOW - 8000, 1, UMBRA, "PRVT6T", "sl", 0.77, "ok"))
        self.con.commit()

    def test_only_a_prefix_symbol_is_replaced_and_nothing_else_changes(self):
        self.seed()
        before = self.dump()
        got = symbols.fix(self.lg, self.con)
        self.assertEqual(got, {"league.trades": 3, "league.veliki_trades": 2, "trade.positions": 2, "trade.exit_fills": 1})
        after = self.dump()
        want = {UMBRA: "UMBRA", TROLL: "TROLL"}
        for table, rows in before.items():
            self.assertEqual(len(rows), len(after[table]), table)
            for old, new in zip(rows, after[table]):
                tok, sym = old["token"], old["symbol"]
                exp = want[tok] if tok in want and sym == tok[:6] else sym
                self.assertEqual(new["symbol"], exp, (table, old["id"]))
                self.assertEqual({k: v for k, v in new.items() if k != "symbol"},
                                 {k: v for k, v in old.items() if k != "symbol"}, (table, old["id"]))   # nothing else
        syms = {r["symbol"] for t in after.values() for r in t}
        self.assertIn(NONAME[:6], syms)                                          # never a guessed name
        self.assertIn("ABCDEF", syms)                                            # six letters that are not the mint's
        self.assertIn("GTA6", syms)
        self.assertIn("MANU", syms)
        self.assertEqual(symbols.fix(self.lg, self.con), {})                     # a second run: nothing to do
        self.assertEqual(self.dump(), after)

    def test_a_name_learned_later_is_repaired_then(self):
        self.seed()
        symbols.fix(self.lg, self.con)
        symbols.learn(NONAME, "DZ")                                              # the page saw it on DexScreener
        self.assertEqual(symbols.fix(self.lg, self.con),
                         {"league.trades": 1, "league.veliki_trades": 1, "trade.positions": 1})
        self.assertEqual(self.con.execute("SELECT symbol FROM positions WHERE token=?", (NONAME,)).fetchone()[0], "DZ")

    def test_fix_once_runs_at_the_first_pass_then_hourly_and_can_be_switched_off(self):
        self.seed()
        said = []
        with mock.patch.dict(os.environ, {"AP_SYMBOL_FIX": "0"}):
            self.assertEqual(symbols.fix_once(self.lg, NOW, log=said.append), {})
        self.assertEqual(self.con.execute("SELECT symbol FROM positions WHERE token=?", (UMBRA,)).fetchone()[0], "PRVT6T")
        got = symbols.fix_once(self.lg, NOW, log=said.append)
        self.assertEqual(got["trade.positions"], 2)
        self.assertEqual(len(said), 1)
        self.assertIn("nazivi tokena: popravljen simbol", said[0])
        self.lg.execute("UPDATE trades SET symbol='PRVT6T' WHERE token=?", (UMBRA,))
        self.lg.commit()
        self.assertEqual(symbols.fix_once(self.lg, NOW + 600, log=said.append), {})          # not before the hour is out
        self.assertEqual(symbols.fix_once(self.lg, NOW + 3601, log=said.append), {"league.trades": 3})
        with mock.patch.object(symbols, "fix", side_effect=RuntimeError("x")):               # never raises
            self.assertEqual(symbols.fix_once(self.lg, NOW + 9000, log=said.append), {})
        self.assertIn("popravak nije uspio", said[-1])

    def test_the_tick_calls_it(self):
        import inspect
        self.assertIn("symbols.fix_once(con, now)", inspect.getsource(vlive.tick))


# ---------- the rows --------------------------------------------------------------------------------------------------

class Rows(Dbs):
    def test_names_on_read_before_any_repair(self):
        self.three()
        self.veliki(NONAME, NONAME[:6], 0.006, 0.0048, 0.0067, 6e6, ago=9000)
        d = self.view()
        got = {p["token"]: (p["sym"], p["sym_addr"]) for p in d["positions"]}
        self.assertEqual(got, {UMBRA: ("UMBRA", False), GTA6: ("GTA6", False), TROLL: ("TROLL", False),
                               NONAME: ("Dz9mQ9…", True)})
        self.assertEqual(self.con.execute("SELECT symbol FROM positions WHERE token=?", (UMBRA,)).fetchone()[0], "PRVT6T")
        html = apterm.positions_html(d)
        rows = self.rows(html)
        self.assertIn(f'data-sel="{UMBRA}" data-sym="UMBRA" title="Prikaži na grafu" translate=no>UMBRA</button>', rows[UMBRA])
        # nobody knows the symbol: an address, marked, and no name is sent on with the tap
        self.assertIn(f'<button type=button class="apx-tok apx-addr" data-sel="{NONAME}" data-sym="" translate=no', rows[NONAME])
        self.assertIn(">Dz9mQ9…</button>", rows[NONAME])
        self.assertNotIn(">PRVT6T<", html)
        self.assertNotIn(">Ce2gx9<", html)
        # the orders and the header name it the same way
        self.assertEqual({o["sym"] for o in d["orders"] if o["token"] == TROLL}, {"TROLL"})
        self.assertEqual(self.view(TROLL)["header"]["sym"], "TROLL")
        self.assertEqual(self.view(NONAME)["header"]["sym"], "Dz9m…pump")        # the address, as before
        # the row's own text sent as a name must not become one
        h = json.loads(apterm.first_json("Jure", NONAME, sym=NONAME[:6]))["header"]
        self.assertEqual(h["sym"], "Dz9m…pump")

    def test_a_live_row_names_a_token_the_databases_do_not_know(self):
        self.veliki(MANUAL, MANUAL[:6], 0.01, 0.008, 0.011, 1e7)
        with pravitrade._LOCK:
            pravitrade._LIVE_CACHE[(MANUAL,)] = (time.time(), {MANUAL: {"mcap": 1e7, "price": 0.01, "symbol": "HANDY"}})
        (p,) = self.view()["positions"]
        self.assertEqual((p["sym"], p["sym_addr"]), ("HANDY", False))
        self.assertEqual(symbols.fix(self.lg, self.con),
                         {"league.trades": 1, "league.veliki_trades": 1, "trade.positions": 1})   # and it is stored then

    def test_every_row_is_tied_to_its_mint_and_the_selected_one_is_marked(self):
        self.three()
        d = self.view()
        self.assertEqual(d["m"], UMBRA)                                          # the newest live position
        html = apterm.positions_html(d)
        rows = self.rows(html)
        self.assertEqual(list(rows), [UMBRA, GTA6, TROLL])                       # newest first
        pids = {p["token"]: p["pid"] for p in d["positions"]}
        for tok, row in rows.items():
            self.assertEqual(set(re.findall(r'data-sel="([^"]+)"', row)), {tok}, tok)       # name + "Prikaži graf ↑"
            self.assertEqual(len(re.findall(r'data-sel="', row)), 2, tok)
            self.assertIn(f"id=poz-{pids[tok]} ", row)
            self.assertIn(f'data-key="{tok}:live"', row)
            self.assertIn('<span class=apx-onchart>na grafu</span>', row)
            self.assertEqual(" is-sel" in row.split(">", 1)[0], tok == UMBRA, tok)
            self.assertIn(f'name=id value="{pids[tok]}"', row)                   # its own Zatvori 50 % / 100 %
        # another token picked: its row is the marked one, and the panel's sale form is its own
        d = self.view(TROLL)
        rows = self.rows(apterm.positions_html(d))
        self.assertEqual([t for t, r in rows.items() if " is-sel" in r.split(">", 1)[0]], [TROLL])
        side = apterm.panel_html(d, next(p for p in d["positions"] if p["token"] == TROLL))
        self.assertIn(f'name=token required value="{TROLL}"', side)
        self.assertIn(f'<input type=hidden name=id value="{pids[TROLL]}">', side.split("id=apx-sell", 1)[1])
        self.assertIn("Prodaj 50 % TROLL", side)
        hdr = apterm._hdr_html(d["header"], time.time())
        self.assertIn(f'data-mint="{TROLL}"', hdr)
        self.assertIn(f'href="https://dexscreener.com/solana/{TROLL}"', hdr)

    def test_two_tokens_with_one_symbol_stay_apart(self):
        other = "GTA6zzzz" + "1" * 32 + "pump"
        self.veliki(GTA6, "GTA6", 0.012, 0.0096, 0.0133, 1.2e7, ago=100)
        self.veliki(other, "GTA6", 0.5, 0.4, 0.55, 5e7, ago=200)
        d = self.view(other)
        self.assertEqual(d["m"], other)
        rows = self.rows(apterm.positions_html(d))
        self.assertEqual([t for t, r in rows.items() if " is-sel" in r.split(">", 1)[0]], [other])
        self.assertIn(f'data-sel="{other}"', rows[other])
        self.assertNotIn(GTA6, rows[other])
        self.assertIn(f'data-mint="{other}"', apterm._hdr_html(d["header"], time.time()))

    def test_the_browser_side_loads_the_rows_token_by_its_mint(self):
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        # a tap on the row's line picks the row's own mint; the refresh drops an answer for a token picked before
        self.assertIn("if ((b = g('details.apx-pos > summary')) && !g('button,a,input,select,textarea,label,.apx-i'))", js)
        self.assertIn("if (MINT_RE.test(row.dataset.tok || '')) selectToken(row.dataset.tok,", js)
        self.assertIn("const m0 = S.m;", js)
        self.assertIn("if (S.m !== m0) { S.again = S.again || 1; return; }", js)
        self.assertIn("d.classList.toggle('is-sel', !!S.m && d.dataset.tok === S.m)", js)
        self.assertIn("selFallback(m, sym);", js)


# ---------- SL / TP of a strategy's position, the note ----------------------------------------------------------------

class StrategyExit(Dbs):
    def test_the_states_in_words(self):
        e = 1.0
        base = {"entry_px": e, "first_px": e, "tp_px": 1.112, "be_px": 1.012, "kind": "intra", "trail": 0.05}
        x = vview.exit_state({**base, "stop_px": 0.80, "wide_px": 0.80})
        self.assertEqual((x["state"], x["words"], x["sl_pct"], x["tp_pct"]), ("wide", "široki stop −20 %", -20.0, 11.2))
        self.assertEqual(x["summary"], "široki stop −20 % · cilj +11,2 %")
        x = vview.exit_state({**base, "stop_px": 0.93, "wide_px": 0.80, "tight_ts": NOW})
        self.assertEqual((x["state"], x["words"], x["sl_pct"]), ("tight", "uži stop (BTC pada)", -7.0))
        x = vview.exit_state({**base, "stop_px": 1.012, "wide_px": 1.012})
        self.assertEqual((x["state"], x["words"]), ("be", "stop na ulazu"))
        x = vview.exit_state({**base, "stop_px": 1.012, "tight_ts": NOW})           # a BTC episode above break-even
        self.assertEqual(x["words"], "stop na ulazu")
        x = vview.exit_state({**base, "kind": "range", "stop_px": 0.80})
        self.assertEqual((x["state"], x["words"], x["name"]), ("stop", "stop −20 %", "midcap raspon 7 d"))
        self.assertIsNone(vview.exit_state({"entry_px": None}))
        self.assertEqual(vview._hr_px(0.7696), "$0,7696")
        self.assertEqual(vview._hr_px(0.0000612), "$0,0000612")
        self.assertEqual(vview._hr_pct(-20.0, 1), "−20 %")
        self.assertEqual(vview._hr_pct(11.24, 1), "+11,2 %")

    def test_the_cells_show_the_rule_and_nothing_is_written(self):
        self.three()
        self.real()
        before = self.lg.execute("SELECT * FROM veliki_trades ORDER BY id").fetchall()
        d = self.view()
        pos = {p["token"]: p for p in d["positions"]}
        u = pos[UMBRA]
        self.assertEqual((u["sl_pct"], u["sl_mc"], u["tp_pct"]), (-20.0, 76_960_000.0, 11.2))
        self.assertAlmostEqual(u["tp_mc"], 96_200_000.0 * 1.112, delta=1)
        self.assertEqual((u["strat"]["state"], u["strat"]["name"], u["strat_cells"]), ("wide", "midcap dnevni raspon", True))
        self.assertEqual((u["tp"], u["sl"]), ("", ""))                           # the editor's own fields stay empty
        self.assertEqual(pos[GTA6]["strat"]["words"], "uži stop (BTC pada)")
        self.assertEqual(pos[TROLL]["strat"]["words"], "stop na ulazu")
        rows = self.rows(apterm.positions_html(d))
        row = rows[UMBRA]
        sl = row.split('data-l="SL">', 1)[1].split("</span>", 1)[0]
        self.assertEqual(re.sub(r"<[^>]+>", "|", sl), "−20 %|$0,7696||široki stop −20 %||pravilo|")
        tp = row.split('data-l="TP">', 1)[1].split("</span>", 1)[0]
        self.assertEqual(re.sub(r"<[^>]+>", "|", tp), "+11,2 %|$1,0697||pravilo|")
        self.assertIn('<span class=apx-px>pravilo: široki stop −20 % · cilj +11,2 %</span>', row)   # the phone's line
        self.assertIn("uži stop (BTC pada)", rows[GTA6].split('data-l="SL">', 1)[1].split("</span>", 1)[0])
        self.assertIn("stop na ulazu", rows[TROLL].split('data-l="SL">', 1)[1].split("</span>", 1)[0])
        self.assertNotIn(">–</span><span class=\"n up\" data-l=\"TP\">–", row)
        self.assertIn("program · midcap raspon", row)                            # who opened it, by name
        # Otvoreni nalozi: listed as the strategy's, with no "Uredi"; the chart's lines say whose they are
        ords = [o for o in d["orders"] if o["token"] == UMBRA]
        self.assertEqual([(o["kind"], o["status"], o.get("rule")) for o in ords],
                         [("tp", "pravilo strategije", True), ("sl", "široki stop −20 %", True)])
        oh = apterm.orders_html(d)
        self.assertNotIn("data-edit=", oh)
        self.assertIn("midcap dnevni raspon", oh)
        with mock.patch.object(apterm, "_series", lambda m, h, now: ([], None)), \
                mock.patch.object(apterm, "_fill_state", lambda *a, **k: None), \
                mock.patch.object(apterm, "_zones", lambda m: None):
            lines = apterm.candles_data("Jure", UMBRA)["lines"]
        self.assertEqual([ln["label"] for ln in lines], ["Ulaz", "SL (pravilo)", "TP (pravilo)"])
        self.assertEqual(self.lg.execute("SELECT * FROM veliki_trades ORDER BY id").fetchall(), before)   # read-only

    def test_the_owners_own_tp_sl_stay_in_the_cells_and_the_rule_is_still_named(self):
        tid, _pid = self.veliki(UMBRA, "UMBRA", 0.962, 0.7696, 1.0697, 96_200_000.0, wide_px=0.7696)
        self.lg.execute("UPDATE trades SET auto=? WHERE id=?",
                        (json.dumps({"mode": "tpsl", "tp": "+30%", "sl": "-10%", "tp_in": "30%", "sl_in": "-10%"}), tid))
        self.lg.commit()
        self.real()
        (p,) = self.view()["positions"]
        self.assertEqual((p["sl_pct"], p["tp_pct"], p["strat_cells"]), (-10.0, 30.0, False))
        row = apterm._pos_row(p, True, {}, None)
        self.assertNotIn("apx-rule", row.split("</summary>")[0])
        self.assertIn("Izlaz vodi strategija midcap dnevni raspon", row)
        self.assertIn("Uz to vrijedi i tvoj TP/SL iz stupaca", row)

    def test_the_note_of_a_real_and_of_a_demo_position(self):
        self.three()
        self.veliki(MANUAL, "DEMO", 0.01, 0.008, 0.0111, 1e7, user=LU, mode="dry", wide_px=0.008, ago=50_000)
        # a real position with nothing behind it (an old manual buy) and a demo manual one with TP / SL
        t1 = self.demo("Real111111111111111111111111111111111111pump", "REAL", 300_000.0, None)
        t2 = self.demo("Demo111111111111111111111111111111111111pump", "DEMO2", 300_000.0,
                       {"mode": "tpsl", "tp": "+30%", "sl": "-40%", "tp_in": "30%", "sl_in": "-40%"})
        self.lg.commit()
        for tok, sym, mode, lid in (("Real111111111111111111111111111111111111pump", "REAL", "live", t1),
                                    ("Demo111111111111111111111111111111111111pump", "DEMO2", "dry", t2)):
            self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, "
                             "qty_left, league_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (tok, sym, NOW - 99_000, mode, "open", "ručno (pravi trade)", 0.1, 1000, 1000, lid))
        self.con.commit()
        self.real()
        d = self.view()
        html = apterm.positions_html(d)
        rows = self.rows(html)
        live_rows = [r for t, r in rows.items() if '<span class="apx-badge live">' in r]
        self.assertEqual(len(live_rows), 4)
        for r in live_rows:
            self.assertNotIn("samo paper", r)                                    # never on real money
        note = rows[UMBRA].split('data-plan=strategija>', 1)[1].split("</div>", 1)[0]
        self.assertEqual(note, "Izlaz vodi strategija midcap dnevni raspon (program), pravim novcem: prodaje na cilju "
                               "+11,2 % ($1,0697) cijelu poziciju (kad cijelo tržište raste samo pola, ostatak prati "
                               "vrh) ili na stopu −20 % ($0,7696). Sada: BTC je miran, pa vrijedi samo široki stop; "
                               "ako BTC padne 1,5 % u 4 h, stop ide 4 % ispod cijene, a na +5 % neto ide na ulaz. Razine "
                               "postavlja pravilo strategije; ovdje se samo čitaju.")
        self.assertIn('class="apx-plan strat live" data-plan=strategija', rows[UMBRA])
        self.assertIn("Sada: BTC pada, pa je stop uži", rows[GTA6])
        self.assertIn("ili na stopu na ulazu ($0,04837). Sada: stop je na ulazu", rows[TROLL])
        demo = rows[MANUAL]
        self.assertIn('class="apx-plan strat" data-plan=strategija>Demo pozicija, bez pravog novca. Izlaz vodi strategija '
                      'midcap dnevni raspon (program): prodaje na cilju', demo)
        self.assertNotIn("pravim novcem", demo)
        real = rows["Real111111111111111111111111111111111111pump"]
        self.assertIn("<b>pravi novac · plan izlaza nije aktivan</b> · pozicija nema ni plan izlaza ni TP/SL: prodaje se "
                      "samo ručno", real)
        self.assertIn("<b>samo paper</b> · pozicija je demo (paper): bez pravog novca",
                      rows["Demo111111111111111111111111111111111111pump"])
        # the panel's "Tvoja pozicija" of the picked token says the same
        d = self.view(GTA6)
        mine = apterm._mypos_html(next(p for p in d["positions"] if p["token"] == GTA6), {})
        self.assertIn("Izlaz vodi strategija midcap dnevni raspon (program), pravim novcem", mine)
        self.assertIn("uži stop (BTC pada)", mine)
        self.assertNotIn("samo paper", mine)
        # the editor of such a position says the rule goes on selling
        ed = apterm.sltp_html(next(p for p in d["positions"] if p["token"] == GTA6), {})
        self.assertIn("poziciju već prodaje pravilo strategije midcap dnevni raspon", ed)

    def test_no_follow_warning_while_a_strategy_buys(self):
        cfg = pravitrade._cfg(self.con)
        self.assertIn("Bot nikoga ne prati", pravitrade._warnings(self.con, cfg, self.lg))
        settings.put(self.con, "flag:pravi_novac_veliki", {"mode": "live", "since": NOW})
        self.assertNotIn("Bot nikoga ne prati", pravitrade._warnings(self.con, cfg, self.lg))

    def test_history_and_log_name_the_strategy(self):
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, closed_ts, mode, status, reason, sol_in, "
                         "qty_raw, qty_left, sol_back) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (UMBRA, "UMBRA", NOW - 900, NOW - 60, "live", "closed", "veliki: dnevna zona, cilj +11.2%", 0.1,
                          1000, 0, 0.108))
        self.con.commit()
        html = apterm.povijest_html(self.con, pravitrade._cfg(self.con), True, time.time())
        self.assertIn('<span data-l="Izvor">program · midcap raspon<small>', html)
        self.assertEqual(pravitrade._skip_src("veliki: dnevna zona 0.93-1.09"), "midcap raspon: dnevna zona 0.93-1.09")
        self.assertEqual(pravitrade._skip_src("copy KOL ansem"), "copy KOL ansem")


class Critic(Dbs):
    def test_the_payload_carries_the_strategys_stop_and_target(self):
        from critic import prompts, trades as ctrades
        self.three()
        self.real()
        d = self.view()
        live = {t: {"mcap": p["mc_now"], "price": p["mc_now"] / 1e8, "liq": 1e6} for t, p in
                ((p["token"], p) for p in d["positions"])}
        with mock.patch.object(ctrades, "path_summary", lambda *a, **k: {}), \
                mock.patch.object(ctrades, "_rug", lambda *a, **k: None):
            items = ctrades.build_items(self.con, d["positions"], live, 170.0, time.time(), {}, {})
        by = {it["simbol"]: it for it, _row in items}
        self.assertEqual(set(by), {"UMBRA", "GTA6", "TROLL"})                    # by name, not "PRVT6T"
        pl = by["UMBRA"]["plan_izlaza"]
        self.assertEqual((pl["sl_pct"], pl["tp_pct"]), (-20.0, 11.2))            # no longer "no TP, the plan is empty"
        rule = pl["pravilo_strategije"]
        self.assertEqual((rule["strategija"], rule["stanje_stopa"], rule["sl_pct"], rule["tp_pct"]),
                         ("midcap dnevni raspon", "široki stop −20 %", -20.0, 11.2))
        self.assertAlmostEqual(rule["sl_cijena"], 0.7696)
        self.assertEqual(by["GTA6"]["plan_izlaza"]["pravilo_strategije"]["stanje_stopa"], "uži stop (BTC pada)")
        self.assertIn("pravilo_strategije", prompts.OPEN_TRADES)
        self.assertIsNone(ctrades._strategy_rule({"strat": None}))


# ---------- FDV beside MC, the age of the price -----------------------------------------------------------------------

class FdvAndAge(Dbs):
    def test_the_live_row_keeps_the_fdv(self):
        from ui import prijedlog
        pair = {"baseToken": {"address": UMBRA, "symbol": "UMBRA"}, "priceUsd": "0.0679", "liquidity": {"usd": 2e6},
                "marketCap": 6_790_000, "fdv": 13_400_000}
        lv = prijedlog.live_market([UMBRA], fetch=lambda toks: [pair])[UMBRA]
        self.assertEqual((lv["mcap"], lv["fdv"]), (6_790_000.0, 13_400_000.0))
        self.assertIsNone(prijedlog.live_market([UMBRA], fetch=lambda toks: [{**pair, "fdv": None}])[UMBRA]["fdv"])

    def test_fdv_only_when_it_differs_by_more_than_5_percent(self):
        self.assertEqual(apterm.fdv_of({"mcap": 6.79e6, "fdv": 13.4e6}), 13.4e6)
        self.assertIsNone(apterm.fdv_of({"mcap": 6.79e6, "fdv": 7.0e6}))         # 3 %: one number is enough
        self.assertIsNone(apterm.fdv_of({"mcap": 6.79e6, "fdv": None}))
        self.assertIsNone(apterm.fdv_of({"mcap": None, "fdv": 1.0}))
        self.assertIsNone(apterm.fdv_of(None))
        html = apterm.fdv_html(13.4e6)
        self.assertIn("FDV $13.40M", html)
        self.assertIn('title="DexScreener u zaglavlju često pokazuje FDV (sva ponuda); mi računamo po ponudi u optjecaju"', html)
        self.assertIn('data-tip="DexScreener u zaglavlju često pokazuje FDV', html)       # the tap tooltip
        self.assertEqual(apterm.fdv_html(None), '<small class=apx-fdv data-f=fdv hidden></small>')

    def test_the_header_and_the_position_show_mc_and_fdv(self):
        self.three()
        with pravitrade._LOCK:
            key = next(iter(pravitrade._LIVE_CACHE))
            pravitrade._LIVE_CACHE[key][1][UMBRA]["fdv"] = 185_416_400.0
            pravitrade._LIVE_CACHE[key][1][GTA6]["fdv"] = 11_900_000.0          # 0.7 % above its MC: not shown
        d = self.view()
        self.assertEqual(d["header"]["fdv"], 185_416_400.0)
        hdr = apterm._hdr_html(d["header"], time.time())
        self.assertIn('<b data-f=mcap>$94.12M</b><small class=apx-fdv data-f=fdv title=', hdr)
        self.assertIn(">FDV $185.42M<span", hdr)
        pos = {p["token"]: p for p in d["positions"]}
        self.assertEqual((pos[UMBRA]["fdv_now"], pos[GTA6]["fdv_now"]), (185_416_400.0, None))
        rows = self.rows(apterm.positions_html(d))
        self.assertIn('<span data-f=mc>$94.12M</span><small class=apx-fdv data-f=fdv title=', rows[UMBRA])
        self.assertIn(">FDV $185.42M<span", rows[UMBRA])
        self.assertIn('<span data-f=mc>$11.82M</span><small class=apx-fdv data-f=fdv hidden></small>', rows[GTA6])
        self.assertIn(">FDV $185.42M<span", apterm._mypos_html(pos[UMBRA], {}))
        # the tick carries it, so the browser keeps it fresh
        with mock.patch.object(pravitrade, "_live_cached", lambda toks, now, **k: pravitrade._LIVE_CACHE[key][1]):
            apterm.reset()
            t = apterm.tick(UMBRA)
        self.assertEqual(t["tok"][UMBRA]["fdv"], 185_416_400.0)
        self.assertNotIn("fdv", t["tok"][GTA6])
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("setFdv(h, lv)", js)
        self.assertIn("setFdv(row, lv)", js)

    def test_the_age_of_the_positions_price(self):
        self.assertEqual(apterm.price_age(1000, now=1002), ("cijena prije 2 s", False))
        self.assertEqual(apterm.price_age(1000, now=1015), ("cijena prije 15 s", False))
        self.assertEqual(apterm.price_age(1000, now=1016), ("cijena kasni 16 s", True))
        self.assertEqual(apterm.price_age(1000, now=1000 + 240), ("cijena kasni 4 min", True))
        self.assertEqual(apterm.price_age(None), ("nema cijene", True))
        fresh = apterm.price_badge(1000, now=1002)
        self.assertIn('<span class="apx-age apx-live-age" data-ts="1000" data-price=1 data-stale=15 ', fresh)
        self.assertIn(">cijena prije 2 s</span>", fresh)
        late = apterm.price_badge(1000, now=1040)
        self.assertIn('class="apx-age apx-live-age old"', late)                  # the yellow badge, not only paler
        self.assertIn(">cijena kasni 40 s</span>", late)
        self.three()
        d = self.view()
        self.assertIsNotNone(d["data_ts"])
        html = apterm.positions_html(d)
        self.assertTrue(html.startswith('<div class=apx-pxage><span class="apx-age apx-live-age" '), html[:80])
        self.assertRegex(html[:400], r">cijena prije \d s</span>")
        _, body = pravitrade.page({}, "Jure")
        tabs = body.split("<div class=apx-tabs", 1)[1].split("</div>", 1)[0]
        self.assertRegex(tabs, r'data-price=1 data-stale=15 [^>]*>cijena prije \d s</span>')
        js = apterm.static_asset("ap.js")[0].decode("utf-8")
        self.assertIn("if (el.dataset.price) el.textContent = (late ? 'cijena kasni ' : 'cijena prije ') + w;", js)
        self.assertIn("for (const el of $$('.apx-live-age')) el.dataset.ts = t.data_ts;", js)   # the tick renews it
        with open(os.path.join(apterm.STATIC_DIR, "ap.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn("@media(max-width:700px){.apx-pxage{display:block}}", css)


# ---------- the browser: a tap on a row loads that row's token above ----------------------------------------------------

def _have_playwright():
    if not shutil.which("node"):
        return False
    try:
        r = subprocess.run(["node", "-e", "const {chromium}=require('playwright');"
                            "process.exit(require('fs').existsSync(chromium.executablePath())?0:1)"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class _Page(http.server.BaseHTTPRequestHandler):
    """The page, its static files and the three answers ap.js asks for (first, tick, token), from this process."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/pravi-trade":
                from ui.html import page as layout
                return self._out(200, layout(*pravitrade.page(qs, "Jure"), "/pravi-trade"), "text/html")
            if u.path.startswith("/pravi-trade/static/"):
                a = apterm.static_asset(u.path[len("/pravi-trade/static/"):])
                if a:
                    return self._out(200, a[0], a[2])
            if u.path == "/pravi-trade/api/first":
                return self._out(200, apterm.first_json("Jure", qs.get("m", ""), with_html=qs.get("html") == "1",
                                                        sym=qs.get("s", "")), "application/json")
            if u.path == "/pravi-trade/api/tick":
                with pravitrade._LOCK:
                    rows = {}
                    for _ts, data in pravitrade._LIVE_CACHE.values():
                        rows.update(data or {})
                tok = {t: {"mcap": lv.get("mcap"), "price": lv.get("price")} for t, lv in rows.items()}
                return self._out(200, json.dumps({"ts": int(time.time()), "data_ts": int(time.time()), "tok": tok,
                                                  "sig": "isti"}), "application/json")
            if u.path == "/pravi-trade/api/token":
                m = qs.get("q", "")
                sym = symbols.known([m]).get(m, "")
                return self._out(200, json.dumps({"q": m, "mint": m, "found": True, "sym": sym, "name": sym, "mcap": 1e7,
                                                  "liq": 1e6, "age_s": 86400}), "application/json")
            if u.path == "/pravi-trade/api/candles":
                return self._out(200, json.dumps({"mint": qs.get("m"), "tf": "5m", "unit": "mc", "ts": int(time.time()),
                                                  "data_ts": None, "candles": [], "vol": [], "supply": None, "lines": [],
                                                  "zones": None, "zones_mc": None, "first_ts": None, "born": None,
                                                  "fill": None, "young": None}), "application/json")
        except Exception as e:  # noqa: BLE001 - the browser test reports the page's state, not a server trace
            return self._out(500, f"{type(e).__name__}: {e}", "text/plain")
        return self._out(404, "", "text/plain")

    def _out(self, code, body, ctype):
        body = body if isinstance(body, bytes) else (body or "").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(_have_playwright(), "node + playwright + chromium")
class Browser(Dbs):
    """The real ap.js at 390 px and 860 px: a tap on a row's line loads that row's token above (header, DexScreener
    link, chart, Token field and Kupi, the sale form), a late refresh and a lost answer never leave another token's
    parts there, nothing is wider than the screen. Screenshots go to APAUDIT_SHOTS (default: a temporary folder)."""

    def test_a_tap_on_a_row_loads_that_rows_token(self):
        self.three()
        self.real()
        with pravitrade._LOCK:   # the live rows stay "fresh" for the whole run (no request is ever made)
            key = next(iter(pravitrade._LIVE_CACHE))
            pravitrade._LIVE_CACHE[key] = (time.time() + 600, pravitrade._LIVE_CACHE[key][1])
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Page)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        out = os.environ.get("APAUDIT_SHOTS") or self.tmp.name
        os.makedirs(out, exist_ok=True)
        js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apaudit_playwright.js")
        r = subprocess.run(["node", js, f"http://127.0.0.1:{srv.server_address[1]}", out],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:] + r.stdout[-2000:])
        rep = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(rep["errors"], [])
        names = {UMBRA: "UMBRA", GTA6: "GTA6", TROLL: "TROLL"}
        pids = dict(self.con.execute("SELECT token, id FROM positions"))
        for w in ("390", "860"):
            v = rep[w]
            self.assertEqual([(x["tok"], x["sel"], x["name"], x["addr"]) for x in v["rows"]],
                             [(t, t, names[t], False) for t in (UMBRA, GTA6, TROLL)], w)
            self.assertTrue(all(x["rowH"] >= 44 for x in v["rows"]), (w, v["rows"]))         # the row is the tap target
            self.assertEqual((v["start"]["mint"], v["start"]["sel"]), (UMBRA, [UMBRA]), w)   # opens on the newest
            self.assertEqual([t["row"] for t in v["taps"]], [TROLL, GTA6, UMBRA], w)
            for t in v["taps"]:
                tok, top = t["row"], t["top"]
                self.assertTrue(t["open"], (w, tok))                                         # the row still opens
                self.assertEqual((top["mint"], top["dex"], top["chart"], top["token"], top["m"]),
                                 (tok, tok, tok, tok, tok), (w, names[tok], top))
                self.assertEqual(top["hdr"], names[tok], (w, top))
                self.assertEqual(top["sel"], [tok], (w, top))                                # "na grafu" on that row only
                self.assertEqual(top["sellIds"], str(pids[tok]), (w, top))                   # the sale form is its own
                self.assertIn(names[tok], top["buy"], (w, top))
                self.assertIn(names[tok], top["sell"], (w, top))
            g = v["tograf"]                                                                   # "Prikaži graf ↑"
            self.assertEqual((g["top"]["mint"], g["top"]["chart"], g["top"]["sel"]), (GTA6, GTA6, [GTA6]), w)
            self.assertLess(abs(g["hdrTop"]), h_view(w), (w, g))                             # the header is on screen
            race = v["race"]                                                                  # a late refresh for GTA6
            self.assertGreaterEqual(race["held"], 1, w)
            self.assertEqual((race["top"]["mint"], race["top"]["chart"], race["top"]["token"], race["top"]["sellIds"],
                              race["top"]["sel"]), (UMBRA, UMBRA, UMBRA, str(pids[UMBRA]), [UMBRA]), (w, race))
            down = v["down"]                                                                  # no answer for the pick
            self.assertEqual((down["mint"], down["dex"], down["chart"], down["token"], down["hdr"], down["sel"]),
                             (GTA6, GTA6, GTA6, GTA6, "GTA6", [GTA6]), (w, down))
            self.assertIsNone(down["sellIds"], (w, down))                                    # not UMBRA's sale form
            for state in ("overflow", "overflowOpen"):
                m = v[state]
                self.assertLessEqual(m["scroll"], m["vw"], (w, state, m))
                self.assertEqual(m["wide"], [], (w, state, m))


def h_view(w):
    return 844 if w == "390" else 1000


if __name__ == "__main__":
    unittest.main()
