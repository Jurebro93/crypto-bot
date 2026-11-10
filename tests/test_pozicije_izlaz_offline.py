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
        self.assertIn("ulaz na MC $82.0k", inner)                    # inside
        self.assertIn("Izlaz: TP +15 % · SL −60 %", inner)
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
        self.assertIn("zatvoren", unquote(loc))
        self.assertIn("err=", self.post("/pravi-trade/exit", {"id": "999", "tp": "30%", "sl": ""}))


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
