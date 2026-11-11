"""10.11. (Jure): "moram vidjeti na koliko market capa je bot kupio otvorenu poziciju", "gore glavni kredit se nije
pomakao nakon kupovine", "default stop loss treba biti na minus 60 %, a to moram na stranici Autopilota kao
administrator moći promijeniti", "za neke tokene bi stavio take profit 30 %, a ne samo 15 %".

- trade.settings: sl_default (60 unless the owner picks another of SL_CHOICES under "Pravila", POST /pravi-trade/sl)
- league/copy.default_sl: the Autopilot account gets the owner's stop at each entry, players keep DEFAULT_SL;
  adopt_default_sl: the old stored default ("-20%") on the Autopilot's follows becomes "" once
- open positions: entry MC and the exit rule of the demo trade behind them; POST /pravi-trade/exit changes TP/SL
- the header: free SOL, the part in positions and the snapshot's clock time under the big number

    python3 -m unittest tests.test_pozicije_izlaz_offline
"""
import json
import os
import sys
import tempfile
import time
import unittest
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_trade  # noqa: E402
from league import copy, store  # noqa: E402
from trade import executor, settings  # noqa: E402

MINT = "So11111111111111111111111111111111111111112"[:-1] + "7"
LIVE_ROW = {"price": 1.0, "liq": 1e6, "mcap": 82_000.0, "vol_h1": 20_000.0, "vol_h24": 1e5, "txns_h1": 80, "buys_h1": 50,
            "txns_h24": 900, "vol_m5": 900.0, "txns_m5": 6, "ch_m5": 1.0, "ch_h1": 3.0, "ch_h24": 10.0}


class Base(unittest.TestCase):
    def setUp(self):
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, uleague.market, collapse.check,
                       uleague._symbol, prijedlog.live_market, os.environ.get("TRADE_OWNER"))
        run_trade.LEAGUE_DB = store.DB = os.path.join(d, "league.db")
        run_trade.DB = settings.DB = os.path.join(d, "trade.db")
        self.con = executor.connect(settings.DB)
        self.lg = store.connect(store.DB)
        copy.ensure(self.lg)
        copy._ADOPTED.clear()
        from ui import pravitrade
        pravitrade._LIVE_CACHE.clear()   # the live MC is shared per token set across the process
        pravitrade._LIVE_FAIL.clear()
        os.environ["TRADE_OWNER"] = "Jure"
        uleague.market = lambda toks: {t: (1.0, 1e6, None, 82_000.0) for t in toks}
        collapse.check = lambda *a, **k: None
        uleague._symbol = lambda t: "HOPE"
        prijedlog.live_market = lambda toks, fetch=None: {t: dict(LIVE_ROW) for t in toks}

    def tearDown(self):
        from rugfilter import collapse
        from ui import league as uleague, prijedlog
        (run_trade.LEAGUE_DB, run_trade.DB, settings.DB, store.DB, uleague.market, collapse.check,
         uleague._symbol, prijedlog.live_market, owner) = self._saved
        if owner is None:
            os.environ.pop("TRADE_OWNER", None)
        else:
            os.environ["TRADE_OWNER"] = owner
        copy._ADOPTED.clear()
        self.con.close()
        self.lg.close()
        self.tmp.cleanup()

    def post(self, path, form):
        from ui import pravitrade
        return pravitrade.post(path, form, "Jure")


class DefaultStop(Base):
    def test_default_is_minus_60_and_the_owner_changes_it(self):
        cfg = settings.merged(executor.load_config(), self.con)
        self.assertEqual(cfg["sl_default"], 60)
        self.assertEqual(copy.default_sl(settings.LEAGUE_USER), "-60%")
        self.assertEqual(copy.default_sl("igrac"), copy.DEFAULT_SL)              # players keep -20 %
        loc = self.post("/pravi-trade/sl", {"sl": "40"})
        self.assertIn("ok=", loc)
        self.assertEqual(settings.merged(executor.load_config(), self.con)["sl_default"], 40)
        self.assertEqual(copy.default_sl(settings.LEAGUE_USER), "-40%")
        loc = self.post("/pravi-trade/sl", {"sl": "33"})
        self.assertIn("err=", loc)
        self.assertEqual(settings.merged(executor.load_config(), self.con)["sl_default"], 40)
        from ui import pravitrade
        loc = pravitrade.post("/pravi-trade/sl", {"sl": "20"}, "netko")         # only the owner
        self.assertIn("err=", loc)
        self.assertEqual(copy.default_sl(settings.LEAGUE_USER), "-40%")

    def test_card_under_pravila_shows_the_choice(self):
        from ui import pravitrade
        cfg = settings.merged(executor.load_config(), self.con)
        card = pravitrade._sl_card(cfg, True)
        self.assertIn("sada −60 %", card)
        self.assertIn("<button class=ap-go>−60 %</button>", card)
        self.assertEqual(card.count("action=/pravi-trade/sl"), len(settings.SL_CHOICES))
        self.assertNotIn("<form", pravitrade._sl_card(cfg, False))              # an invited viewer only reads it

    def test_manual_buy_without_a_stop_gets_the_owners_default(self):
        self.post("/pravi-trade/sl", {"sl": "50"})
        loc = self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,02", "exit": "tpsl", "tp": "30%", "sl": ""})
        self.assertIn("ok=", loc)
        (t,) = store.trades(self.lg, settings.LEAGUE_USER, "open")
        a = json.loads(t["auto"])
        self.assertEqual((a["tp"], a["sl"]), ("+30%", "-50%"))

    def test_old_stored_default_on_the_autopilot_follows_becomes_the_owners_default_once(self):
        au = settings.LEAGUE_USER
        f1 = copy.follow(self.lg, au, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")       # the old stored default
        f2 = copy.follow(self.lg, au, "kol", "murad", "", 25, 5, "tpsl", "15%", "-35%")       # typed by the owner
        f3 = copy.follow(self.lg, "igrac", "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")  # a player
        self.assertEqual(copy.adopt_default_sl(self.lg), 1)
        ex = {f["id"]: f["exit"] for f in copy.follows(self.lg, active=None)}
        self.assertEqual((ex[f1]["sl"], ex[f2]["sl"], ex[f3]["sl"]), ("", "-35%", "-20%"))
        # once per database: a "-20%" the owner types later is his and stays
        copy.follow(self.lg, au, "kol", "ansem", "", 25, 5, "tpsl", "15%", "-20%")
        copy._ADOPTED.clear()
        self.assertEqual(copy.adopt_default_sl(self.lg), 0)
        self.assertEqual(next(f for f in copy.follows(self.lg, au) if f["target"] == "ansem")["exit"]["sl"], "-20%")


class Positions(Base):
    def _bought(self, **form):
        base = {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "15%", "sl": ""}
        base.update(form)
        loc = self.post("/pravi-trade/buy", base)
        self.assertIn("ok=", loc)
        (t,) = store.trades(self.lg, settings.LEAGUE_USER, "open")
        cur = self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                               "qty_raw, qty_left) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (t["id"], MINT, "HOPE", int(time.time()) - 120, "live", "open", "ručno (pravi trade)",
                                0.15, 1000, 1000))
        self.con.commit()
        return cur.lastrowid, t["id"]

    def test_open_position_says_entry_mc_and_its_exit(self):
        from ui import pravitrade
        pid, _ = self._bought()
        cfg = settings.merged(executor.load_config(), self.con)
        inner, meta, has_open = pravitrade.positions_inner(self.con, False, True, {}, cfg)
        self.assertTrue(has_open)
        self.assertIn("ulaz MC $82.0k", inner)                       # the closed row
        self.assertRegex(inner, r"1\. ulaz \d\d:\d\d na MC <b>\$82\.0k</b> \(<b>0,0\xa0%</b>\)")   # inside, bold entry MC
        self.assertRegex(inner, r"MC sada <b>\$82\.0k</b> · osvježeno <b>\d\d:\d\d:\d\d</b>")   # the quote's clock time
        self.assertIn("Ulaz na MC <b>$82.0k</b>", inner)
        self.assertIn("<b>TP/SL</b> · TP +15 % · SL −60 %", inner)          # 10.11.: under "Otvoreni nalozi"
        self.assertIn("Otvoreni nalozi · 1", inner)
        self.assertIn("<button class=ap-sellall aria-label=\"Prodaj sve\">Prodaj sve</button>", inner)
        self.assertIn("action=/pravi-trade/exit", inner)
        self.assertIn('name=sl value="-60%"', inner)                 # the quick TP buttons keep the stop
        self.assertIn("TP +30 %", inner)
        viewer, _, _ = pravitrade.positions_inner(self.con, True, False, {}, cfg)
        self.assertIn("ulaz MC $82.0k", viewer)
        self.assertNotIn("/pravi-trade/exit", viewer)                # only the owner changes the exit

    def test_owner_sets_tp_30_and_keeps_the_stop(self):
        pid, lid = self._bought()
        loc = self.post("/pravi-trade/exit", {"id": str(pid), "tp": "30%", "sl": "-60%"})
        self.assertIn("ok=", loc)
        self.assertIn("TP +30 % · SL −60 %", unquote(loc))
        a = json.loads(self.lg.execute("SELECT auto FROM trades WHERE id=?", (lid,)).fetchone()[0])
        self.assertEqual((a["mode"], a["tp"], a["sl"]), ("tpsl", "+30%", "-60%"))
        self.assertAlmostEqual(a["tp_px"], 1.3)
        # an empty stop = the default stop; a typo is refused and changes nothing
        self.post("/pravi-trade/sl", {"sl": "50"})
        loc = self.post("/pravi-trade/exit", {"id": str(pid), "tp": "$200k", "sl": ""})
        self.assertIn("ok=", loc)
        a = json.loads(self.lg.execute("SELECT auto FROM trades WHERE id=?", (lid,)).fetchone()[0])
        self.assertEqual((a["tp"], a["sl"]), ("MC $200,000", "-50%"))
        loc = self.post("/pravi-trade/exit", {"id": str(pid), "tp": "abc", "sl": ""})
        self.assertIn("err=", loc)
        self.assertEqual(json.loads(self.lg.execute("SELECT auto FROM trades WHERE id=?", (lid,)).fetchone()[0])["tp"],
                         "MC $200,000")

    def test_copy_keeps_its_effective_entry_base(self):
        pid, lid = self._bought()
        self.lg.execute("UPDATE trades SET entry_eff=1.1, auto=? WHERE id=?",
                        (json.dumps({"mode": "tpsl", "tp": "+15%", "sl": "-60%", "tp_px": 1.265, "sl_px": 0.44,
                                     "from_eff": True, "until": int(time.time()) + 600}), lid))
        self.lg.commit()
        self.assertIn("ok=", self.post("/pravi-trade/exit", {"id": str(pid), "tp": "30%", "sl": "-60%"}))
        a = json.loads(self.lg.execute("SELECT auto FROM trades WHERE id=?", (lid,)).fetchone()[0])
        self.assertTrue(a["from_eff"])
        self.assertAlmostEqual(a["tp_px"], 1.1 * 1.3)
        self.assertNotIn("until", a)                                  # the owner's rule replaces a data exit's hour

    def test_closed_or_unknown_position_is_refused(self):
        pid, lid = self._bought()
        self.lg.execute("UPDATE trades SET status='closed' WHERE id=?", (lid,))
        self.lg.commit()
        loc = self.post("/pravi-trade/exit", {"id": str(pid), "tp": "30%", "sl": ""})
        self.assertIn("err=", loc)
        self.assertIn("nije otvorena", unquote(loc))
        self.assertIn("err=", self.post("/pravi-trade/exit", {"id": "999", "tp": "30%", "sl": ""}))


def pravitrade_gate(tcon, sol):
    from ui import pravitrade
    return pravitrade._gate_now(tcon, sol, MINT)


class LimitBuy(Base):
    """10.11. (Jure: "buy order na određenom market capu i odmah TP i SL: sad je 90k, kupi ako dođe na 50k, od 50k
    TP i SL"): a waiting buy order, bought when the market cap is at its level, with the exit counted from there."""

    def setUp(self):
        super().setUp()
        from ui import league as uleague, prijedlog
        self.mc = {"v": 90_000.0}
        uleague.market = lambda toks: {t: (self.mc["v"] / 82_000, 1e6, None, self.mc["v"]) for t in toks}
        prijedlog.live_market = lambda toks, fetch=None: {
            t: {**LIVE_ROW, "price": self.mc["v"] / 82_000, "mcap": self.mc["v"]} for t in toks}

    def live(self, toks):
        return {t: {"mcap": self.mc["v"]} for t in toks}

    def order(self, **kw):
        form = {"token": MINT, "sol": "0,05", "at": "$50k", "exit": "tpsl", "tp": "30%", "sl": "-20%", **kw}
        return unquote(self.post("/pravi-trade/buy", form))

    def test_an_order_waits_then_buys_at_the_level_with_tp_sl_from_there(self):
        from ui import pravitrade
        loc = self.order()
        self.assertIn("ok=", loc)
        self.assertIn("kad MC padne na $50,000", loc)
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])      # nothing bought at 90k
        self.assertEqual(len(settings.raw(self.con)["buy_orders"]), 1)
        _, body = pravitrade.page({}, "Jure")
        # 11.11. (ui/apterm): the waiting order is a row of the tab "Otvoreni nalozi", with its Otkaži (same route)
        self.assertIn("<b id=apx-nord>1</b>", body)
        self.assertIn(">Limit kupnja<", body)
        self.assertIn("action=/pravi-trade/limitdel", body)
        self.assertEqual(pravitrade.limit_once(self.con, live_fn=self.live), [])       # still 90k: waits
        self.mc["v"] = 49_000.0
        done = pravitrade.limit_once(self.con, live_fn=self.live)
        self.assertIn("kupljeno 0.05 SOL na MC $49,000", done[0][1])
        lots = store.trades(self.lg, settings.LEAGUE_USER, "open")
        self.assertEqual(len(lots), 1)
        a = json.loads(lots[0]["auto"])
        self.assertEqual((a["tp_in"], a["sl_in"]), ("30%", "-20%"))
        self.assertAlmostEqual(a["tp_px"] / lots[0]["entry_px"], 1.3, places=6)          # +30 % from the 49k entry
        self.assertAlmostEqual(a["sl_px"] / lots[0]["entry_px"], 0.8, places=6)
        self.assertEqual(settings.raw(self.con)["buy_orders"], [])                       # bought once, then gone

    def test_the_level_already_reached_buys_now_and_typos_show_at_once(self):
        self.mc["v"] = 48_000.0
        self.assertIn("ok=", self.order())
        self.assertEqual(len(store.trades(self.lg, settings.LEAGUE_USER, "open")), 1)
        self.mc["v"] = 90_000.0
        self.assertIn("ispod 30k", self.order(at="$20k"))
        self.assertIn("TP mora biti iznad", self.order(tp="$40k"))
        self.assertIn("err=", self.order(at="bilo kad"))

    def test_a_fall_straight_through_the_level_is_not_bought_and_orders_lapse(self):
        from ui import pravitrade
        self.order()
        self.order(at="-40%")                                                          # 90k - 40 % = 54k
        orders = settings.raw(self.con)["buy_orders"]
        self.assertAlmostEqual(orders[1]["mc"], 54_000, places=0)
        self.mc["v"] = 30_500.0                                                        # -39 % under 50k, -44 % under 54k
        done = pravitrade.limit_once(self.con, live_fn=self.live)
        self.assertEqual(len(done), 2)
        self.assertTrue(all("nije kupljeno" in t for _, t in done))
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])
        self.mc["v"] = 90_000.0
        self.order()
        later = time.time() + pravitrade.LIMIT_HOURS * 3600 + 5
        self.assertIn("istekao", pravitrade.limit_once(self.con, now=later, live_fn=self.live)[0][1])

    def test_cancel(self):
        self.order()
        oid = settings.raw(self.con)["buy_orders"][0]["id"]
        self.assertIn("otkazan", unquote(self.post("/pravi-trade/limitdel", {"id": str(oid)})))
        self.assertEqual(settings.raw(self.con)["buy_orders"], [])


class AddToPosition(Base):
    """10.11. (Jure: "ako unesem adresu istog tokena koji je već u poziciji, pozicija se podeblja; nadopišu se dva
    ulaza: prvi ulaz na toliko market capa (PnL), drugi ulaz ..."): a manual buy of a held token is one more lot."""

    def setUp(self):
        super().setUp()
        from tests.test_trade_offline import FakeJup
        from trade import jupiter
        self.fake = FakeJup()
        self._jup = (jupiter.order, jupiter.execute)
        jupiter.order, jupiter.execute = self.fake.order, self.fake.execute

    def tearDown(self):
        from trade import jupiter
        jupiter.order, jupiter.execute = self._jup
        super().tearDown()

    def mirror(self, now):
        from tests.test_trade_offline import CFG
        cfg = settings.merged(dict(CFG, sell_check=False), self.con)
        run_trade.follow_league_once(self.con, cfg, since=0, now=now, quiet=True)

    def test_the_owners_buy_is_not_held_by_the_day_spend_limit_the_copies_are(self):
        """10.11. (Jure: "piše da je kupovina prošla, a nema pozicije" -> "makni limit"): the owner's own buys pass
        the day's spending limit (on the page and in run_trade); the Autopilot's copies keep it."""
        from tests.test_trade_offline import CFG
        settings.put(self.con, "max_sol_per_day", 0.08, "Jure")
        for _ in range(2):
            self.assertIn("ok=", self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "30%", "sl": ""}))
            self.mirror(time.time())
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0], 2)
        cfg = settings.merged(dict(CFG), self.con)
        # 10.11. (Jure: "Dnevni limit ... Ovo nema smisla"): his buys do not use up the copies' limit either
        self.assertIsNone(executor.gate_buy(self.con, cfg, 0.05, time.time(), False, token="X"))
        self.assertIsNone(executor.gate_buy(self.con, cfg, 0.05, time.time(), False, token="X", manual=True))
        self.assertIsNone(pravitrade_gate(self.con, 0.05))

    def test_a_limit_that_still_holds_is_said_on_the_page_before_anything_is_written(self):
        settings.put(self.con, "max_open", 1, "Jure")
        self.assertIn("ok=", self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "30%", "sl": ""}))
        self.mirror(time.time())
        other = MINT[:-4] + "abcd"
        loc = unquote(self.post("/pravi-trade/buy", {"token": other, "sol": "0,05", "exit": "tpsl", "tp": "30%", "sl": ""}))
        self.assertIn("err=", loc)
        self.assertIn("kupnja nije poslana", loc)
        self.assertEqual(len(store.trades(self.lg, settings.LEAGUE_USER, "open")), 1)   # no demo lot without a real one

    def test_second_buy_of_a_held_token_is_a_second_lot_with_the_same_exit(self):
        from ui import league as uleague, prijedlog
        self.assertIn("ok=", self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "30%", "sl": ""}))
        self.mirror(time.time())
        # the price ran from $82k to $100k: the owner buys again
        uleague.market = lambda toks: {t: (100 / 82, 1e6, None, 100_000.0) for t in toks}
        prijedlog.live_market = lambda toks, fetch=None: {t: {**LIVE_ROW, "price": 100 / 82, "mcap": 100_000.0} for t in toks}
        loc = self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,04", "exit": "tpsl", "tp": "15%", "sl": ""})
        self.assertIn("ok=", loc)
        self.assertIn("Dokupnja", unquote(loc))
        lots = store.trades(self.lg, settings.LEAGUE_USER, "open")
        self.assertEqual(len(lots), 2)
        a = {t["entry_mcap"]: json.loads(t["auto"]) for t in lots}
        # 10.11. (Jure: "prosječan ulaz, na to take profit, zatvori cijelu poziciju"): the position's +30 % (not the
        # form's 15 %) from the average entry weighted by SOL (0,05 at $82k + 0,04 at $100k = $89.1k), the same level
        # on both lots, so both close at once
        avg_mc = 0.09 / (0.05 / 82_000 + 0.04 / 100_000)
        for r in a.values():
            self.assertEqual((r["tp_in"], r["sl_in"]), ("30%", "-60%"))
            self.assertAlmostEqual(r["grp"]["avg_mc"], avg_mc, places=3)
            self.assertIn("od prosjeka", r["tp"])
        self.assertAlmostEqual(a[82_000.0]["tp_px"], a[100_000.0]["tp_px"])
        self.assertAlmostEqual(a[82_000.0]["tp_px"] * 82_000.0 / 1.0, avg_mc * 1.3, places=3)   # entry_px 1.0 at $82k
        self.mirror(time.time() + 2)
        pos = self.con.execute("SELECT token, status, sol_in, league_id FROM positions ORDER BY id").fetchall()
        self.assertEqual([(p[0], p[1]) for p in pos], [(MINT, "open"), (MINT, "open")])   # two real lots, no "već postoji"
        self.assertAlmostEqual(sum(p[2] for p in pos), 0.09)
        # one row: both entries with their MC and the move since (MC now $100k)
        from ui import pravitrade
        cfg = settings.merged(executor.load_config(), self.con)
        inner, meta, _ = pravitrade.positions_inner(self.con, False, True, {}, cfg)
        self.assertEqual(inner.count("<details class=ap-it id=poz-"), 1)
        self.assertTrue(meta.startswith("1"))
        self.assertIn("2 ulaza · ulaz MC $82.0k, $100.0k", inner)
        self.assertRegex(inner, r'1\. ulaz \d\d:\d\d na MC <b>\$82\.0k</b> \(<b class="pos">\+22,0\xa0%</b>\) · 0,050\xa0SOL')
        self.assertRegex(inner, r"2\. ulaz \d\d:\d\d na MC <b>\$100\.0k</b> \(<b>0,0\xa0%</b>\) · 0,040\xa0SOL")
        self.assertIn("Prosječni ulaz na MC <b>$89.1k</b>", inner)
        self.assertIn('PnL <b class="pos ap-pnl-v">+12,2\xa0%</b>', inner)
        ids = ",".join(str(p) for (p,) in self.con.execute("SELECT id FROM positions ORDER BY id"))
        self.assertIn(f"name=id value={ids}>", inner)                     # sell buttons: every lot
        # the exit form changes both lots: one level from the average entry
        pid0 = int(ids.split(",")[0])
        self.assertIn("ok=", self.post("/pravi-trade/exit", {"id": str(pid0), "tp": "50%", "sl": "-40%"}))
        pxs = set()
        for t in store.trades(self.lg, settings.LEAGUE_USER, "open"):
            a = json.loads(t["auto"])
            self.assertEqual((a["tp_in"], a["sl_in"]), ("50%", "-40%"))
            pxs.add(round(a["tp_px"], 9))
            self.assertAlmostEqual(a["tp_px"] * 82_000.0, avg_mc * 1.5, places=3)
        self.assertEqual(len(pxs), 1)
        # "Prodaj 50 %" asks every lot
        self.assertIn("ok=", self.post("/pravi-trade/sell", {"id": ids, "frac": "0.5"}))
        self.assertEqual(set(settings.raw(self.con)["sell_req"]), set(ids.split(",")))

    def test_a_copy_never_doubles_a_held_token_and_max_open_counts_tokens(self):
        from tests.test_trade_offline import CFG
        now = time.time()
        for i, tok in enumerate(("A" * 43, "A" * 43, "B" * 43)):
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                             (tok, int(now), "dry", "open", 0.01))
        self.con.commit()
        cfg = dict(settings.merged(dict(CFG), self.con), max_open=2, max_sol_per_day=5)
        self.assertIn("već postoji", executor.gate_buy(self.con, cfg, 0.01, now, False, token="A" * 43))
        self.assertIsNone(executor.gate_buy(self.con, cfg, 0.01, now, False, token="A" * 43, add=True))   # a lot
        self.assertIn("2 otvorenih", executor.gate_buy(self.con, cfg, 0.01, now, False, token="C" * 43))  # tokens, not lots


class FastExit(Base):
    """10.11. (Jure: "TP +40 % od ulaza 84k, graf dotakao 117k i malo preko, prodaja se nije dogodila"): the
    Autopilot's TP/SL are checked every second by league/auto.fast_once, apart from the 20-s pass over all players."""

    def test_tp_touch_sells_at_once_and_only_the_autopilot_account(self):
        from league import auto
        self.assertIn("ok=", self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "40%", "sl": ""}))
        player = store.buy(self.lg, "igrac", MINT, "HOPE", 25, 1.0, 1e6, "ručno", None, 82_000.0)
        auto.set_auto(self.lg, "igrac", player, "tpsl", "40%", "-60%")
        under = lambda toks: {t: (1.39, 1e6, None, 82_000.0 * 1.39) for t in toks}
        self.assertEqual(auto.fast_once(self.lg, under, settings.LEAGUE_USER), [])
        self.assertEqual(auto.fast_once.last, (1, 1))
        touch = lambda toks: {t: (1.401, 1e6, None, 82_000.0 * 1.401) for t in toks}
        done = auto.fast_once(self.lg, touch, settings.LEAGUE_USER)
        self.assertEqual(len(done), 1)
        self.assertIn("auto TP +40%", done[0][2])
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])
        self.assertEqual(len(store.trades(self.lg, "igrac", "open")), 1)       # players stay on the 20-s pass
        self.assertEqual(auto.fast_once(self.lg, touch, settings.LEAGUE_USER), [])   # nothing twice

    def test_no_dexscreener_price_falls_back_to_jupiter(self):
        from league import auto
        from ui import paper
        self.assertIn("ok=", self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "40%", "sl": ""}))
        saved = paper.jup_prices
        paper.jup_prices = lambda mints: {m: (0.39, 5e4) for m in mints}     # -61 %: under the -60 % stop
        try:
            done = auto.fast_once(self.lg, lambda toks: {}, settings.LEAGUE_USER)
        finally:
            paper.jup_prices = saved
        self.assertEqual(len(done), 1)
        self.assertIn("auto SL -60%", done[0][2])


class FollowExit(Base):
    """10.11. (Jure: "za svakog influencera mogu odabrati poseban take profit ili stop loss; to isto može biti u
    pop-upu"): a follow's own TP / SL for its new entries (and, ticked, its open positions)."""

    def test_owner_sets_a_follows_tp_and_sl_and_entries_use_it(self):
        from ui import pravitrade
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "smart", "", "",
                          max_mcap=800_000)
        loc = self.post("/pravi-trade/followexit", {"id": str(fid), "tp": "30%", "sl": ""})
        self.assertIn("ok=", loc)
        self.assertIn(f"#prati-{fid}", loc)
        f = next(x for x in copy.follows(self.lg, settings.LEAGUE_USER) if x["id"] == fid)
        self.assertEqual((f["exit"]["mode"], f["exit"]["tp"], f["exit"]["sl"], f["exit"]["max_mcap"]),
                         ("tpsl", "30%", "", 800_000))                     # entry conditions stay
        self.assertIn("err=", self.post("/pravi-trade/followexit", {"id": str(fid), "tp": "abc", "sl": ""}))
        html = pravitrade._follows(self.lg, True, settings.raw(self.con))
        self.assertIn("action=/pravi-trade/followexit", html)
        self.assertIn("Izlaz za ovo praćenje", html)
        self.assertIn("<button class=ap-go>TP +30 %</button>", html)
        self.assertNotIn("followexit", pravitrade._follows(self.lg, False, settings.raw(self.con)))   # owner only

    def test_ticked_box_also_moves_the_follows_open_positions(self):
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "", 25, 5, "tpsl", "15%", "")
        tid = store.buy(self.lg, settings.LEAGUE_USER, MINT, "HOPE", 25, 1.0, 1e6, "copy KOL ansem", None, 82_000.0)
        self.lg.execute("UPDATE trades SET follow_id=? WHERE id=?", (fid, tid))
        self.lg.commit()
        self.assertIn("ok=", self.post("/pravi-trade/followexit", {"id": str(fid), "tp": "50%", "sl": "-30%", "open": "1"}))
        a = json.loads(self.lg.execute("SELECT auto FROM trades WHERE id=?", (tid,)).fetchone()[0])
        self.assertEqual((a["tp"], a["sl"]), ("+50%", "-30%"))

    def test_follow_button_carries_tp_and_sl(self):
        from ui import pravitrade
        btn = pravitrade._follow_btn("kol", "ansem", "", set(), True)
        self.assertIn("name=exit value=tpsl", btn)
        self.assertIn('name=tp placeholder="TP zadano"', btn)
        loc = self.post("/pravi-trade/follow", {"kind": "kol", "target": "ansem", "per_day": "5", "exit": "tpsl",
                                                "tp": "40%", "sl": "-25%"})
        self.assertIn("ok=", loc)
        f = copy.follows(self.lg, settings.LEAGUE_USER)[0]
        self.assertEqual((f["exit"]["tp"], f["exit"]["sl"]), ("40%", "-25%"))
        self.assertIn("promijeni TP/SL", pravitrade._follow_btn("kol", "ansem", "", {("kol", "ansem")}, True))


class ManualDca(Base):
    """10.11. (Jure: "DCA ide ručno, granice se postavljaju ručno"): the owner sets a level and an amount on an open
    position; when the live MC touches the level the bot buys once into the same position."""

    def _open_position(self):
        self.assertIn("ok=", self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "30%", "sl": ""}))
        (t,) = store.trades(self.lg, settings.LEAGUE_USER, "open")
        self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, reason, sol_in, "
                         "qty_raw, qty_left) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (t["id"], MINT, "HOPE", int(time.time()) - 60, "dry", "open", "ručno (pravi trade)", 0.05, 1000, 1000))
        self.con.commit()

    def test_order_by_mc_or_percent_buys_once_when_touched(self):
        from ui import pravitrade
        self._open_position()
        self.assertIn("ok=", self.post("/pravi-trade/dca", {"token": MINT, "lvl": "-20%", "sol": "0,04"}))   # 82k -> 65.6k
        self.assertIn("ok=", self.post("/pravi-trade/dca", {"token": MINT, "lvl": "$50k", "sol": "0,03"}))
        orders = settings.raw(self.con)["dca_orders"]
        self.assertEqual([round(o["mc"]) for o in orders], [65_600, 50_000])
        self.assertIn("err=", self.post("/pravi-trade/dca", {"token": MINT, "lvl": "$90k", "sol": "0,04"}))   # above MC now
        self.assertIn("err=", self.post("/pravi-trade/dca", {"token": MINT, "lvl": "$20k", "sol": "0,04"}))   # under 30k
        cfg = settings.merged(executor.load_config(), self.con)
        inner, _, _ = pravitrade.positions_inner(self.con, False, True, {}, cfg)
        self.assertIn("<summary>DCA dokup · 2</summary>", inner)
        self.assertIn("Otvoreni nalozi · 3", inner)                              # TP/SL + two DCA orders
        self.assertIn("<b>DCA dokup</b> 0,040\xa0SOL na MC <b>$65.6k</b>", inner)
        self.assertIn("<button class=ap-cancel>Otkaži</button>", inner)
        bought = []
        buy = lambda con, tcon, form, user: bought.append(form)
        self.assertEqual(pravitrade.dca_once(self.con, live_fn=lambda t: {MINT: {"mcap": 70_000.0}}, buy_fn=buy), [])
        done = pravitrade.dca_once(self.con, live_fn=lambda t: {MINT: {"mcap": 65_000.0}}, buy_fn=buy)
        self.assertEqual(len(done), 1)                                         # only the -20 % order
        self.assertEqual((bought[0]["token"], bought[0]["sol"]), (MINT, "0.04"))
        self.assertEqual([round(o["mc"]) for o in settings.raw(self.con)["dca_orders"]], [50_000])
        self.assertIn("dokupljeno 0.04 SOL", settings.raw(self.con)["dca_log"][0]["text"])

    def test_closed_position_drops_its_orders_and_owner_removes_one(self):
        from ui import pravitrade
        self._open_position()
        self.assertIn("ok=", self.post("/pravi-trade/dca", {"token": MINT, "lvl": "$60k", "sol": "0,04"}))
        oid = settings.raw(self.con)["dca_orders"][0]["id"]
        self.assertIn("ok=", self.post("/pravi-trade/dcadel", {"id": str(oid)}))
        self.assertEqual(settings.raw(self.con)["dca_orders"], [])
        self.assertIn("ok=", self.post("/pravi-trade/dca", {"token": MINT, "lvl": "$60k", "sol": "0,04"}))
        self.con.execute("UPDATE positions SET status='closed'")
        self.con.commit()
        done = pravitrade.dca_once(self.con, live_fn=lambda t: {}, buy_fn=lambda *a: None)
        self.assertIn("zatvorena", done[0][1])
        self.assertEqual(settings.raw(self.con)["dca_orders"], [])

    def test_the_real_dokup_goes_through_the_manual_buy(self):
        from ui import pravitrade, prijedlog, league as uleague
        self._open_position()
        self.assertIn("ok=", self.post("/pravi-trade/dca", {"token": MINT, "lvl": "$70k", "sol": "0,04"}))
        uleague.market = lambda toks: {t: (69 / 82, 1e6, None, 69_000.0) for t in toks}
        prijedlog.live_market = lambda toks, fetch=None: {t: {**LIVE_ROW, "price": 69 / 82, "mcap": 69_000.0} for t in toks}
        done = pravitrade.dca_once(self.con, live_fn=lambda t: {MINT: {"mcap": 69_000.0}})
        self.assertIn("dokupljeno", done[0][1])
        self.assertEqual(len(store.trades(self.lg, settings.LEAGUE_USER, "open")), 2)   # one more lot


class RememberedExit(Base):
    """10.11. (Jure: "kad se postavi izlaz, neka ostane zapamćen za sljedeću narudžbu, a ne da se uvijek vraća na
    default"): the last TP / SL used prefill the buy forms; a position bought on a follow's signal hands a changed
    exit to that follow."""

    def test_last_manual_exit_prefills_the_next_order(self):
        from ui import pravitrade
        self.assertIn("ok=", self.post("/pravi-trade/buy", {"token": MINT, "sol": "0,05", "exit": "tpsl", "tp": "60%", "sl": "-50%"}))
        cfg = settings.merged(executor.load_config(), self.con)
        self.assertEqual(pravitrade._last_exit(cfg), ("60%", "-50%"))
        card = pravitrade._buy_now_card(cfg, True)
        self.assertIn('name=tp value="60%"', card)
        self.assertIn('name=sl value="-50%"', card)
        self.assertIn('class="ap-buy ap-wide">Kupi', card)
        self.assertIn("value=60%", pravitrade._buy_form(MINT, cfg, "tpsl", True))

    def test_exit_changed_on_a_copied_position_is_kept_for_that_follow(self):
        fid = copy.follow(self.lg, settings.LEAGUE_USER, "kol", "ansem", "ansem", 25, 5, "tpsl", "15%", "")
        tid = store.buy(self.lg, settings.LEAGUE_USER, MINT, "HOPE", 25, 1.0, 1e6, "copy KOL ansem", None, 82_000.0)
        self.lg.execute("UPDATE trades SET follow_id=? WHERE id=?", (fid, tid))
        self.lg.commit()
        cur = self.con.execute("INSERT INTO positions (league_id, token, symbol, opened_ts, mode, status, sol_in) "
                               "VALUES (?,?,?,?,?,?,?)", (tid, MINT, "HOPE", int(time.time()), "dry", "open", 0.05))
        self.con.commit()
        loc = self.post("/pravi-trade/exit", {"id": str(cur.lastrowid), "tp": "60%", "sl": "-60%"})
        self.assertIn("Zapamćeno i za sljedeće ulaze od ansem", unquote(loc))
        f = next(x for x in copy.follows(self.lg, settings.LEAGUE_USER) if x["id"] == fid)
        self.assertEqual((f["exit"]["tp"], f["exit"]["sl"]), ("60%", "-60%"))
        self.assertEqual(settings.raw(self.con)["last_exit"], {"tp": "60%", "sl": "-60%"})

    def test_toast_shows_the_forms_answer(self):
        from ui import pravitrade
        _, body = pravitrade.page({"err": "granica nije ispod sadašnjeg MC-a"}, "Jure")
        self.assertIn('class="ap-toast bad" role=alert', body)
        self.assertIn("granica nije ispod sadašnjeg MC-a", body)
        _, body = pravitrade.page({"ok": "DCA: dokup postavljen"}, "Jure")
        self.assertIn('class="ap-toast ok" role=status', body)


class McpQueue(Base):
    """10.11. (MCP server MemeSonar za Groka): /api/mcp/* needs Bearer MCP_API_KEY; execute_trade only queues a
    request; the owner approves (it goes through his manual buy / sell) or rejects it on the Autopilot page."""

    def setUp(self):
        super().setUp()
        self._key = os.environ.get("MCP_API_KEY")
        os.environ["MCP_API_KEY"] = "k-test"

    def tearDown(self):
        if self._key is None:
            os.environ.pop("MCP_API_KEY", None)
        else:
            os.environ["MCP_API_KEY"] = self._key
        super().tearDown()

    def test_key_is_required_and_off_without_it(self):
        from ui import mcpapi
        self.assertTrue(mcpapi.authorized("Bearer k-test"))
        self.assertFalse(mcpapi.authorized("Bearer nope"))
        self.assertFalse(mcpapi.authorized(None))
        os.environ.pop("MCP_API_KEY")
        self.assertIsNone(mcpapi.authorized("Bearer k-test"))            # no key on Render: the API does not exist

    def test_trade_request_waits_and_the_owner_approves_a_buy(self):
        from ui import mcpapi, pravitrade
        code, out = mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05, "require_approval": True,
                                          "reason": "Grok: 3 calleri u 5 min"})
        self.assertEqual((code, out["status"]), (202, "pending_approval"))
        self.assertEqual(store.trades(self.lg, settings.LEAGUE_USER, "open"), [])   # nothing bought yet
        # 10.11.: without approval only while the owner has grok_autotrade on (ui/grokauto); off by default -> 403
        self.assertEqual(mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05, "require_approval": False})[0], 403)
        self.assertEqual(mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 9})[0], 400)    # over the limit
        self.assertEqual(mcpapi.trade_request({"token": MINT, "side": "sell", "amount": 0.5})[0], 400)  # nothing open
        _, body = pravitrade.page({}, "Jure")
        self.assertIn("Zahtjevi s Groka · 1", body)
        self.assertIn("Grok: 3 calleri u 5 min", body)
        self.assertNotIn("Zahtjevi s Groka", pravitrade.page({}, "netko")[1])
        loc = self.post("/pravi-trade/mcpok", {"id": out["id"]})
        self.assertIn("ok=", loc)
        self.assertEqual(len(store.trades(self.lg, settings.LEAGUE_USER, "open")), 1)   # through the manual buy
        self.assertEqual(mcpapi.pending(self.con), [])
        self.assertIn("err=", self.post("/pravi-trade/mcpok", {"id": out["id"]}))       # never twice

    def test_owner_rejects_and_a_sell_request_asks_every_lot(self):
        from ui import mcpapi
        _, out = mcpapi.trade_request({"token": MINT, "side": "buy", "amount": 0.05})
        self.assertIn("ok=", self.post("/pravi-trade/mcpno", {"id": out["id"]}))
        self.assertEqual(mcpapi.pending(self.con), [])
        for _ in range(2):
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, sol_in) VALUES (?,?,?,?,?)",
                             (MINT, int(time.time()), "dry", "open", 0.05))
        self.con.commit()
        _, out = mcpapi.trade_request({"token": MINT, "side": "sell", "amount": 0.5})
        self.assertIn("ok=", self.post("/pravi-trade/mcpok", {"id": out["id"]}))
        self.assertEqual(sorted(settings.raw(self.con)["sell_req"].values()), [0.5, 0.5])

    def test_api_answers_json(self):
        from ui import mcpapi
        code, text = mcpapi.answer("/api/mcp/token", {"address": "nije-adresa"})
        self.assertEqual(code, 400)
        self.assertIn("Solana", text)
        self.assertEqual(mcpapi.answer("/api/mcp/nema", {})[0], 404)
        code, text = mcpapi.answer("/api/mcp/token", {"address": MINT})
        self.assertEqual(code, 200)
        self.assertIn('"market_cap_usd": 82000.0', text)
        code, text = mcpapi.answer("/api/mcp/portfolio", {})
        self.assertEqual(code, 200)
        self.assertIn('"open_positions": []', text)


class McpHosted(Base):
    """10.11. (Jure: "napravi mcp key, ne znam raditi s pip install"): the app serves MCP at /mcp; the owner makes the
    key on the Autopilot page (settings mcp_key); Grok needs only the address and the key."""

    def setUp(self):
        super().setUp()
        self._key = os.environ.pop("MCP_API_KEY", None)

    def tearDown(self):
        if self._key is not None:
            os.environ["MCP_API_KEY"] = self._key
        super().tearDown()

    def test_owner_makes_the_key_and_the_page_shows_it_only_to_him(self):
        from ui import mcpapi, pravitrade
        self.assertIsNone(mcpapi.authorized("Bearer x"))                       # no key yet: the endpoint is off
        _, body = pravitrade.page({"sve": "1"}, "Jure")   # 11.11.: the Grok row is under Postavke (lazy)
        self.assertIn("Napravi MCP ključ", body)
        self.assertIn("ok=", self.post("/pravi-trade/mcpkey", {}))
        k = settings.raw(self.con)["mcp_key"]
        self.assertTrue(k.startswith("ms_") and len(k) > 40)
        self.assertTrue(mcpapi.authorized(f"Bearer {k}"))
        self.assertNotIn(k, pravitrade.page({}, "Jure")[1])                   # 11.11.: never in the first HTML
        _, body = pravitrade.page({"sve": "1"}, "Jure")
        self.assertIn(f'value="{k}"', body)
        self.assertIn("https://app.memesonar.app/mcp", body)
        settings.put(self.con, "invited", ["gost"], "Jure")
        self.assertNotIn(k, pravitrade.page({"sve": "1"}, "gost")[1])
        from ui import apterm
        self.assertNotIn(k, apterm.lazy("ostalo", "gost"))
        self.assertIn("ok=", self.post("/pravi-trade/mcpkey", {}))             # a new key: the old one stops
        self.assertFalse(mcpapi.authorized(f"Bearer {k}"))
        self.assertIn("ok=", self.post("/pravi-trade/mcpkeyoff", {}))
        self.assertIsNone(mcpapi.authorized("Bearer anything"))

    def test_json_rpc_initialize_list_call_and_notifications(self):
        from ui import mcpapi
        code, out = mcpapi.rpc(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                                      "clientInfo": {"name": "grok", "version": "1"}}}).encode())
        r = json.loads(out)["result"]
        self.assertEqual((code, r["protocolVersion"], r["serverInfo"]["name"]), (200, "2025-03-26", "MemeSonar"))
        self.assertEqual(mcpapi.rpc(b'{"jsonrpc":"2.0","method":"notifications/initialized"}'), (202, ""))
        tools = json.loads(mcpapi.rpc(b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}')[1])["result"]["tools"]
        self.assertEqual([t["name"] for t in tools][:4],
                         ["get_market_signals", "get_token_details", "get_portfolio_status", "execute_trade"])
        self.assertIn("get_caller_leaderboard", [t["name"] for t in tools])   # 10.11.: the analysis tools follow
        self.assertTrue(tools[3]["annotations"]["destructiveHint"])
        call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "get_token_details", "arguments": {"token_address": MINT}}}
        res = json.loads(mcpapi.rpc(json.dumps(call).encode())[1])["result"]
        self.assertFalse(res["isError"])
        self.assertEqual(res["structuredContent"]["market"]["market_cap_usd"], 82000.0)
        call["params"] = {"name": "execute_trade", "arguments": {"token_address": MINT, "amount": 0.05, "side": "buy",
                                                                  "require_approval": False}}
        self.assertTrue(json.loads(mcpapi.rpc(json.dumps(call).encode())[1])["result"]["isError"])
        bad = json.loads(mcpapi.rpc(b'{"jsonrpc":"2.0","id":4,"method":"nope"}')[1])
        self.assertEqual(bad["error"]["code"], -32601)
        self.assertEqual(json.loads(mcpapi.rpc(b"{not json")[1])["error"]["code"], -32700)


class Header(unittest.TestCase):
    def test_split_line_says_free_sol_positions_and_the_snapshot_time(self):
        from ui import pravitrade
        ts = 1794310000
        html = pravitrade._split_html({"sol": 1.85, "tokens_sol": 0.15, "last_ts": ts})
        self.assertIn("slobodno 1,850 SOL · u pozicijama 0,150 SOL · stanje u ", html)
        import datetime as dt
        import zoneinfo
        self.assertIn(dt.datetime.fromtimestamp(ts, zoneinfo.ZoneInfo("Europe/Zagreb")).strftime("%H:%M"), html)
        self.assertEqual(pravitrade._split_html({}), "")


if __name__ == "__main__":
    unittest.main()
