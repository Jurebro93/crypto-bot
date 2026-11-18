"""18.11. (vlasnik: „Smiješ.” na pitanje smije li se trošak izmjeriti jednim pravim krugom pri 0,3 i 0,5 SOL):
trade/mjerenje.py, the one-time measurement of the real round-trip cost at 0.1, 0.3 and 0.5 SOL.

The real trade/executor.buy and trade/executor.sell run against a temporary trade.db; only the swap itself, the wallet,
Jupiter's quote of the sell check, the list, the quotes and the clock are fakes. No network, no key, no real wallet.

    python3 -m unittest tests.test_mjerenje_offline
"""
import inspect
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_trade  # noqa: E402
from critic import data as cdata  # noqa: E402
from trade import cost, executor, jupiter, mjerenje, settings, wallet  # noqa: E402
from vijece import smjer  # noqa: E402

A = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"   # the deepest pool that qualifies
B = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2"
C = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC3"
RENT = 2_039_280
FEE_K, PRIO_K = 2_120_000, 70_000     # the buy: signature + priority + the new token account's deposit
FEE_P, PRIO_P = 260_000, 250_000      # the sale
T0 = 1_795_000_000.0


class Baza(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.con = executor.connect(os.path.join(self.tmp.name, "trade.db"))
        self.addCleanup(self.con.close)
        settings.put(self.con, "on", True, "vlasnik")
        self.t = T0
        self.bal = 3.0
        self.live = True
        self.swaps = []
        self.sell_plan = []      # what the next sales answer ("ok" when empty)
        self.buy_plan = []
        self.route_back = True   # the sell check's quote of the way back
        self.held_raw = {}       # token -> raw units in the fake wallet
        self.lista = [{"mint": A, "symbol": "AAA"}, {"mint": B, "symbol": "BBB"}, {"mint": C, "symbol": "CCC"}]
        self.kv = {A: self.q(4_400_000, 900_000, 1.0, "AAA"), B: self.q(9_000_000, 300_000, 2.0, "BBB"),
                   C: self.q(1_500_000, 5_000_000, 3.0, "CCC")}
        self.mid_after_buy = 0.995   # the price falls 0.5 % between the two fills
        self.buy_calls = []
        real_buy = executor.buy

        def buy(*a, **k):
            self.buy_calls.append(k)
            return real_buy(*a, **k)

        def order(inp, out, amount, taker=None, route="v2", slippage_bps=None):
            if inp != jupiter.SOL and not self.route_back:
                return {"error": "No route found"}
            rate = 0.01 if inp == jupiter.SOL else 99.9
            return {"inAmount": str(amount), "outAmount": str(int(amount * rate)), "inUsdValue": 100, "outUsdValue": 99.9}
        patches = [(executor, "swap", self.swap), (executor, "buy", buy), (executor, "is_live", lambda cfg: self.live),
                   (executor, "armed", lambda: True), (executor, "STOP_FILE", os.path.join(self.tmp.name, "STOP")),
                   (wallet, "sol_balance", lambda addr: self.bal), (wallet, "address", lambda: "ADDR"),
                   (wallet, "token_raw_balance", lambda addr, tok: self.held_raw.get(tok, 0)),
                   (wallet, "_keypair", lambda: None), (wallet, "close_empty", lambda kp, tok: RENT),
                   (jupiter, "order", order), (mjerenje, "lista", lambda: list(self.lista)),
                   (mjerenje, "kotacije", self.kotacije), (mjerenje, "_sat", lambda: self.t),
                   (mjerenje, "_REKAO", {"iskljuceno": False, "greska": 0.0})]
        for obj, name, val in patches:
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {}, clear=False)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("MJERENJE_TROSKA", None)
        self.out = []

    def q(self, liq, vol, px, sym, age=0, **kw):
        return {"cijena": px, "likvidnost": float(liq), "volumen24": float(vol), "mcap": 80e6, "simbol": sym,
                "sumnjivo": None, "age": age, **kw}

    def kotacije(self, mints):
        return {m: dict(self.kv[m], ts=self.t - self.kv[m].get("age", 0)) for m in mints if m in self.kv}

    def swap(self, inp, out, amount, live, max_cost_pct=None, routes=executor.ROUTES, limit=None, slippage_bps=None):
        buying = inp == jupiter.SOL
        tok = out if buying else inp
        # rule 2: when a buy goes out, no other measurement position is open (its own row is still 'pending')
        self.swaps.append({"buy": buying, "token": tok, "amount": amount, "live": live, "cap": max_cost_pct,
                           "open": len([r for r in mjerenje.otvorene(self.con) if r[2]])})
        plan = (self.buy_plan if buying else self.sell_plan)
        ans = plan.pop(0) if plan else "ok"
        if callable(ans):
            ans = ans()
        if isinstance(ans, BaseException):
            raise ans
        if isinstance(ans, dict):
            return {"amount_in": amount, "attempts": [], "tried": [], "fee_total": 0, **ans}
        if buying:
            units = amount // 100   # 0.3 SOL -> 3,000,000 raw units
            self.held_raw[tok] = self.held_raw.get(tok, 0) + units
            self.kv[tok] = dict(self.kv[tok], cijena=self.kv[tok]["cijena"] * self.mid_after_buy)
            return {"status": "ok", "amount_in": amount, "amount_out": units, "cost_pct": 0.21, "fee_lamports": FEE_K,
                    "prio_lamports": PRIO_K, "impact_pct": 0.02, "attempts": [], "tried": [], "fee_total": FEE_K,
                    "signature": "SIGK", "route": "v2"}
        self.held_raw[tok] = self.held_raw.get(tok, 0) - amount
        return {"status": "ok", "amount_in": amount, "amount_out": int(amount * 100 * 0.992), "cost_pct": 0.3,
                "fee_lamports": FEE_P, "prio_lamports": PRIO_P, "impact_pct": 0.02, "attempts": [], "tried": [],
                "fee_total": FEE_P, "signature": "SIGP", "route": "v2"}

    def cfg(self):
        return settings.merged(executor.load_config(), self.con)

    def korak(self, dt=0.0, **kw):
        self.t += dt
        lines = mjerenje.korak(self.con, self.cfg(), now=self.t, **kw)
        self.out += lines
        return lines

    def st(self):
        return mjerenje.citaj(self.con)[0]

    def krug(self):
        """One stake: the buy pass and, a second later, the sale pass."""
        a = self.korak()
        return a + self.korak(1)

    def sve(self):
        self.krug()
        self.korak(mjerenje.PAUZA_S)
        self.korak(1)
        self.korak(mjerenje.PAUZA_S)
        self.korak(1)

    def postavke(self):
        return {k: v for k, v in self.con.execute("SELECT k, v FROM settings") if k != mjerenje.KLJUC}

    def kupnje(self):
        return [s for s in self.swaps if s["buy"]]

    def prodaje(self):
        return [s for s in self.swaps if not s["buy"]]


class SretanPut(Baza):
    def test_tri_uloga_redom_i_racun_rucno(self):
        prije = self.postavke()
        self.sve()
        st = self.st()
        self.assertEqual(st["status"], "gotovo")
        self.assertEqual([s["amount"] for s in self.kupnje()], [100_000_000, 300_000_000, 500_000_000])
        self.assertEqual([s["amount"] for s in self.prodaje()], [1_000_000, 3_000_000, 5_000_000])   # the WHOLE lot
        self.assertEqual({s["token"] for s in self.swaps}, {A})
        self.assertEqual(self.postavke(), prije)   # rule 4: no setting, cap, flag or switch changed
        r = st["rezultati"][1]
        # 0.3 SOL by hand: spent 0.3 + 0.00212 fees; back 0.2976 - 0.00026 fees + 0.00203928 deposit
        self.assertAlmostEqual(r["potroseno"], 0.30212, places=9)
        self.assertAlmostEqual(r["vraceno"], 0.29937928, places=9)
        self.assertAlmostEqual(r["krug_pct"], 0.00274072 / 0.3 * 100, places=3)          # 0.9136 %
        self.assertAlmostEqual(r["mreza_pct"], 0.00034072 / 0.3 * 100, places=3)         # 0.1136 %
        self.assertAlmostEqual(r["utjecaj_pct"], (0.02 * 0.3 + 0.02 * 0.2976) / 0.3, places=3)   # 0.0398 %
        self.assertAlmostEqual(r["pomak_pct"], 0.5, places=3)                            # the price fell 0.5 %
        self.assertAlmostEqual(r["naknade_pct"], 0.9136 - 0.1136 - 0.0398 - 0.5, places=3)   # 0.2602 %
        self.assertAlmostEqual(r["mreza_pct"] + r["naknade_pct"] + r["utjecaj_pct"] + r["pomak_pct"], r["krug_pct"], places=3)
        self.assertAlmostEqual(r["bez_pomaka_pct"], r["krug_pct"] - 0.5, places=3)
        self.assertEqual((r["tokena_kupljeno"], r["tokena_prodano"]), (3_000_000, 3_000_000))
        self.assertEqual((r["kupnja"]["naknada_lamports"], r["kupnja"]["prioritet_lamports"]), (FEE_K, PRIO_K))
        self.assertEqual((r["prodaja"]["naknada_lamports"], r["prodaja"]["prioritet_lamports"]), (FEE_P, PRIO_P))
        self.assertEqual((r["kupnja"]["utjecaj_pct"], r["prodaja"]["utjecaj_pct"]), (0.02, 0.02))
        self.assertEqual(r["depozit_vracen_lamports"], RENT)
        self.assertEqual(r["sekundi"], 1.0)
        self.assertAlmostEqual(r["kupnja"]["mid"] * 0.995, r["prodaja"]["mid"])
        self.assertEqual(r["mid_u"], "USD")
        # 0.1 and 0.5 SOL: the same lamports of fees are a bigger / smaller share
        self.assertAlmostEqual(st["rezultati"][0]["krug_pct"], 1.14072, places=3)
        self.assertAlmostEqual(st["rezultati"][2]["krug_pct"], 0.868144, places=3)
        self.assertIn("mjerenje troška: 0,3 SOL na AAA (likvidnost 4,4M $): potrošeno 0,30212 SOL, vraćeno 0,29938 SOL, "
                      "krug 0,91 % (mreža 0,11 %, naknade poola i rute 0,26 %, utjecaj 0,04 %, pomak cijene 0,50 %), 1 s",
                      self.out)
        self.assertEqual(self.out[-1], "mjerenje troška: krug pri 0,1 / 0,3 / 0,5 SOL: 1,1 % / 0,9 % / 0,9 % "
                                       "(bez pomaka cijene: 0,6 % / 0,4 % / 0,4 %)")

    def test_pauza_izmedu_uloga(self):
        self.krug()
        self.assertEqual(self.korak(mjerenje.PAUZA_S - 2), [])
        self.assertEqual(len(self.kupnje()), 1)
        self.korak(2)
        self.assertEqual(len(self.kupnje()), 2)

    def test_samo_jednom(self):
        self.sve()
        n = len(self.swaps)
        for dt in (1, 60, 3600, 90_000):
            self.assertEqual(self.korak(dt), [])
        self.assertEqual(len(self.swaps), n)
        self.assertEqual(len(self.kupnje()), 3)

    def test_rastavi_bez_kotiranog_utjecaja_i_bez_cijene(self):
        r = mjerenje.rastavi(0.5, 0.5, 100_000, 0.49, 100_000, 0)
        self.assertAlmostEqual(r["krug_pct"], (0.5001 - 0.4899) / 0.5 * 100, places=4)   # 2.04 %
        self.assertAlmostEqual(r["mreza_pct"], 0.04, places=4)
        self.assertIsNone(r["utjecaj_pct"])
        self.assertIsNone(r["pomak_pct"])
        self.assertIsNone(r["bez_pomaka_pct"])
        self.assertAlmostEqual(r["naknade_pct"], 2.0, places=4)   # everything else stays in "naknade"
        line = mjerenje.redak({**r, "ulog": 0.5, "simbol": "X", "likvidnost": 2.5e6, "sekundi": 3, "kupnja": {}})
        self.assertIn("naknade poola i rute s utjecajem 2,00 %", line)
        self.assertIn("pomak cijene nepoznat", line)
        up = mjerenje.rastavi(0.1, 0.1, 0, 0.101, 0, 0, mid_k=1.0, mid_p=1.02)   # the price rose: not booked as a gain
        self.assertAlmostEqual(up["pomak_pct"], -2.0, places=4)
        self.assertAlmostEqual(up["bez_pomaka_pct"], 1.0, places=4)


class Pravilo1Uvjeti(Baza):
    def odbijeno(self, dio):
        lines = self.korak()
        self.assertEqual(self.swaps, [])
        self.assertEqual(len(lines), 1)
        self.assertIn("bez kupnje", lines[0])
        self.assertIn(dio, lines[0])
        self.assertEqual(self.st()["status"], "ceka")
        self.assertEqual(self.korak(mjerenje.PONOVI_S - 5), [])   # at most once every 30 min
        self.assertEqual(self.swaps, [])

    def test_autopilot_nije_uzivo(self):
        self.live = False
        self.odbijeno("Autopilot nije uključen uživo")
        self.live = True
        self.korak(5)
        self.assertEqual(len(self.kupnje()), 1)

    def test_kill_switch(self):
        open(executor.STOP_FILE, "w").close()
        self.odbijeno("kill switch")
        os.remove(executor.STOP_FILE)
        self.korak(5)
        self.assertEqual(len(self.kupnje()), 1)

    def test_prodaj_sve_u_tijeku(self):
        settings.put(self.con, "sell_all", int(self.t), "vlasnik")
        self.odbijeno("Prodaj sve")

    def test_stanje_ispod_poda_plus_ulog_plus_rezerva(self):
        self.bal = 1.149   # 1 + 0.1 + 0.05 = 1.15
        self.odbijeno("stanje 1,1490 SOL, treba 1,15")
        self.bal = 1.15
        self.korak(5)
        self.assertEqual(len(self.kupnje()), 1)

    def test_veci_ulog_treba_vece_stanje(self):
        self.bal = 1.3   # enough for 0.1, not for 0.3 (1.35)
        self.krug()
        self.assertEqual(len(self.kupnje()), 1)
        lines = self.korak(mjerenje.PAUZA_S)
        self.assertIn("0,3 SOL: bez kupnje: stanje 1,3000 SOL, treba 1,35", lines[0])
        self.assertEqual(len(self.kupnje()), 1)

    def test_vlasnikov_visi_pod_vrijedi(self):
        self.assertAlmostEqual(mjerenje.potrebno({"min_equity_sol": 2.0}, 0.5), 2.55)
        self.assertAlmostEqual(mjerenje.potrebno({"min_equity_sol": 0.2}, 0.5), 1.55)   # never under 1 SOL

    def test_stanje_necitljivo(self):
        with mock.patch.object(wallet, "sol_balance", side_effect=RuntimeError("RPC")):
            lines = self.korak()
        self.assertIn("stanje novčanika se ne može pročitati", lines[0])
        self.assertEqual(self.swaps, [])

    def test_odustaje_nakon_24_h(self):
        self.live = False
        self.korak()
        lines = self.korak(mjerenje.ROK_S + 1)
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertIn("nisu se stekli u 24 h", lines[0])
        self.live = True
        self.assertEqual(self.korak(3600), [])
        self.assertEqual(self.swaps, [])

    def test_petlja_staje_nema_nove_kupnje(self):
        self.assertEqual(self.korak(stani=True), [])
        self.assertEqual(self.swaps, [])
        self.korak()               # the buy
        self.korak(1, stani=True)  # a sale still goes out while stopping
        self.assertEqual(len(self.prodaje()), 1)


class Pravilo2JedanUlog(Baza):
    def test_jedan_ulog_u_riziku_i_najvise_tri(self):
        self.sve()
        self.assertEqual([s["open"] for s in self.kupnje()], [0, 0, 0])   # nothing of ours open when a buy goes out
        self.assertEqual(len(self.kupnje()), 3)
        self.assertEqual(mjerenje.kupljeno(self.con), 3)
        self.assertEqual(mjerenje.otvorene(self.con), [])

    def test_otvorena_pozicija_mjerenja_zaustavlja_kupnju(self):
        self.krug()
        self.con.execute("INSERT INTO positions (token, symbol, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                         "sol_back) VALUES (?,?,?,?,?,?,?,?,?,0)", (A, "AAA", int(self.t), "live", "open",
                                                                   "mjerenje troška: 0,1 SOL", 0.1, 5, 5))
        self.con.commit()
        lines = self.korak(mjerenje.PAUZA_S)
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertEqual(len(self.kupnje()), 1)
        self.assertTrue(any("je još otvorena prije sljedeće kupnje" in ln for ln in lines))
        self.assertTrue(any("otvoreno ostaje: pozicija #" in ln for ln in lines))

    def test_knjiga_i_zapis_se_moraju_slagati(self):
        self.krug()
        self.con.execute("INSERT INTO orders (ts, position_id, token, side, mode, status, reason) VALUES (?,?,?,?,?,?,?)",
                         (int(self.t), 99, A, "buy", "live", "ok", "mjerenje troška: 0,3 SOL"))
        self.con.commit()
        self.korak(mjerenje.PAUZA_S)
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertIn("2 ispunjenih kupnji mjerenja, a završenih uloga 1", self.st()["razlog"])
        self.assertEqual(len(self.kupnje()), 1)

    def test_drugi_proces_pomakne_zapis_nema_kupnje(self):
        self.korak(0, stani=True)   # the record exists ("ceka"), nothing bought

        def drugi(addr):   # another process moves the record while this pass is checking
            st, _raw = mjerenje.citaj(self.con)
            st["sljedeci_ts"] = 1
            settings.put(self.con, mjerenje.KLJUC, st, "drugi")
            return self.bal
        with mock.patch.object(wallet, "sol_balance", drugi):
            lines = self.korak()
        self.assertEqual(self.swaps, [])
        self.assertIn("promijenio drugi proces", lines[-1])

    def test_dva_koraka_ne_kupuju_dvaput_isti_ulog(self):
        self.korak()
        self.assertEqual(self.st()["status"], "prodaja")
        self.sell_plan = [{"status": "failed", "retry": True, "error": "nema rute"}]
        self.korak(1)
        self.assertEqual(len(self.kupnje()), 1)   # the state is "prodaja": no pass buys


class Pravilo3Prodaja(Baza):
    PAD = {"status": "failed", "retry": True, "error": "cijena se pomaknula"}

    def test_prodaja_ne_prolazi_tri_pokusaja_pa_odustaje(self):
        self.sell_plan = [dict(self.PAD), dict(self.PAD), dict(self.PAD)]
        self.korak()
        self.korak(1)             # try 1
        self.korak(1)             # the executor's own backoff (5 s): "wait", not a try
        self.assertEqual(len(self.prodaje()), 1)
        self.korak(6)             # try 2
        self.korak(11)            # try 3 -> given up
        st = self.st()
        self.assertEqual(len(self.prodaje()), 3)
        self.assertEqual(st["status"], "odustalo")
        self.assertEqual(st["rezultati"], [])
        self.assertEqual(st["otvoreno"][0]["tokena"], 1_000_000)
        pid = st["otvoreno"][0]["pozicija"]
        self.assertTrue(any(f"otvoreno ostaje: pozicija #{pid} AAA, 1000000 jedinica tokena, uloženo 0,1000 SOL" in ln
                            for ln in self.out))
        for dt in (30, 600, 4000):   # no loop, no next stake
            self.assertEqual(self.korak(dt), [])
        self.assertEqual(len(self.prodaje()), 3)
        self.assertEqual(len(self.kupnje()), 1)

    def test_prodaja_nepotvrdena_u_120_s(self):
        self.sell_plan = [dict(self.PAD)]
        self.korak()
        self.korak(1)
        lines = self.korak(mjerenje.PRODAJA_ROK_S + 1)
        self.assertEqual(len(self.prodaje()), 1)   # no further try after the window
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertIn("nije potvrđena u 120 s", lines[0])

    def test_prodaja_potvrdena_prekasno_ne_kupuje_sljedeci_ulog(self):
        def spora():
            self.t += 130
            return "ok"
        self.sell_plan = [spora]
        self.korak()
        self.korak(1)
        st = self.st()
        self.assertEqual(st["status"], "odustalo")
        self.assertEqual(len(st["rezultati"]), 1)   # the stake is measured (it is real), the next is not bought
        self.assertEqual(mjerenje.otvorene(self.con), [])
        self.assertEqual(self.korak(600), [])
        self.assertEqual(len(self.kupnje()), 1)
        self.assertTrue(self.out[-1].endswith("(nepotpuno)"))

    def test_greska_u_prodaji_ne_vrti_petlju(self):
        self.korak()
        zvano = []

        def puca(*a, **k):
            zvano.append(1)
            raise RuntimeError("RPC ne odgovara")
        with mock.patch.object(executor, "sell", puca):
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    self.korak(1)
            lines = self.korak(1)        # the fourth pass does not call the sale again
            self.assertEqual(self.korak(1), [])
        self.assertEqual(len(zvano), 3)
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertIn("nije potvrđena nakon 3 pokušaja", lines[0])
        self.assertTrue(any("otvoreno ostaje: pozicija #" in ln for ln in lines))

    def test_pozicija_je_obicna_prava_pozicija_koju_aplikacija_prodaje(self):
        self.sell_plan = [dict(self.PAD), dict(self.PAD), dict(self.PAD)]
        self.korak()
        self.korak(1)
        self.korak(6)
        self.korak(11)
        pid = self.st()["otvoreno"][0]["pozicija"]
        row = self.con.execute("SELECT mode, status, reason, league_id, qty_left FROM positions WHERE id=?", (pid,)).fetchone()
        self.assertEqual(row, ("live", "open", "mjerenje troška: 0,1 SOL", None, 1_000_000))
        # the owner's page: the sell button of one position (settings sell_req -> run_trade.sell_requests_once)
        settings.put(self.con, "sell_req", {str(pid): 1.0}, "vlasnik")
        with mock.patch.object(run_trade, "notify", lambda t: None):
            run_trade.sell_requests_once(self.con, self.cfg(), now=self.t + 700, quiet=True)
        self.assertEqual(self.con.execute("SELECT status FROM positions WHERE id=?", (pid,)).fetchone()[0], "closed")

    def test_prodaj_sve_prodaje_i_poziciju_mjerenja(self):
        self.sell_plan = [dict(self.PAD), dict(self.PAD), dict(self.PAD)]
        self.korak()
        self.korak(1)
        self.korak(6)
        self.korak(11)
        pid = self.st()["otvoreno"][0]["pozicija"]
        settings.put(self.con, "sell_all", int(self.t), "vlasnik")
        with mock.patch.object(run_trade, "notify", lambda t: None), mock.patch.dict(run_trade._sell_all_try, {"ts": 0}):
            run_trade.sell_all_once(self.con, self.cfg(), now=self.t + 700, quiet=True)
        self.assertEqual(self.con.execute("SELECT status FROM positions WHERE id=?", (pid,)).fetchone()[0], "closed")

    def test_redovno_upravljanje_zatvori_prije_prodaje(self):
        self.korak()
        pid = self.st()["pozicija"]
        executor.sell(self.con, self.cfg(), pid, close=True, now=self.t, reason="prodaj sve (gumb)")
        n = len(self.prodaje())
        lines = self.korak(1)
        self.assertEqual(len(self.prodaje()), n)
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertIn("zatvorilo ju je redovno upravljanje", lines[0])


class Pravilo4Nadjacavanje(Baza):
    def test_veci_ulozi_idu_rucnim_nadjacavanjem_s_razlogom(self):
        prije = self.postavke()
        caps = (dict(executor.AUTO_HARD_CAPS), executor.AUTO_VELIKI_SOL, dict(executor.LIVE_CAPS), dict(executor.SWITCH_CAPS))
        self.sve()
        self.assertEqual([k["override"] for k in self.buy_calls], [None, mjerenje.NADJACAVANJE, mjerenje.NADJACAVANJE])
        self.assertTrue(all(k["manual"] is True for k in self.buy_calls))
        self.assertEqual([k["reason"] for k in self.buy_calls],
                         ["mjerenje troška: 0,1 SOL", "mjerenje troška: 0,3 SOL", "mjerenje troška: 0,5 SOL"])
        rows = self.con.execute("SELECT sol_in, override, reason FROM positions WHERE status='closed' ORDER BY id").fetchall()
        self.assertEqual([r[1] for r in rows], [None, "vlasnik odobrio mjerenje troška 18.11.",
                                                "vlasnik odobrio mjerenje troška 18.11."])
        self.assertTrue(all(r[2].startswith("mjerenje troška") for r in rows))
        log = [ln for ln in self.out if "kupujem" in ln]
        self.assertIn("unutar limita uloga, bez nadjačavanja", log[0])
        for ln in log[1:]:
            self.assertIn("ručnim nadjačavanjem limita uloga, razlog: vlasnik odobrio mjerenje troška 18.11.", ln)
        self.assertEqual(self.postavke(), prije)
        self.assertEqual((dict(executor.AUTO_HARD_CAPS), executor.AUTO_VELIKI_SOL, dict(executor.LIVE_CAPS),
                          dict(executor.SWITCH_CAPS)), caps)
        self.assertEqual(self.cfg()["max_sol_per_trade"], 0.1)

    def test_modul_ne_pise_nijedan_drugi_kljuc(self):
        src = inspect.getsource(mjerenje)
        self.assertNotIn("settings.put", src)
        self.assertNotIn("set_flag", src)
        self.assertEqual(src.count("INTO settings"), 1)
        self.assertEqual(src.count("UPDATE settings"), 1)
        for bad in ("from league", "import league", "jupiter.order(", "jupiter.execute(", "wallet.sign", "executor.swap(",
                    "executor._jup(", "pumpportal", "urllib"):
            self.assertNotIn(bad, src.split('"""', 2)[2])   # no swap code and no demo row of its own

    def test_drugi_limit_ne_nadjacava_nego_ceka(self):
        cfg = executor.load_config()
        for i in range(int(cfg["max_open"])):   # the owner's max_open is reached by other positions
            self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, "
                             "sol_back) VALUES (?,?,?,?,?,?,?,?,0)", (f"T{i}", int(self.t), "live", "open", "copy KOL x",
                                                                     0.1, 5, 5))
        self.con.commit()
        lines = self.korak()
        self.assertEqual(self.swaps, [])
        self.assertIn("provjera kupnje", lines[0])
        self.assertEqual(self.st()["status"], "ceka")


class Pravilo5Kupnja(Baza):
    def test_odbijena_kupnja_zavrsava_mjerenje(self):
        self.route_back = False   # the executor's sell check: no way back = HARD
        lines = self.korak()
        st = self.st()
        self.assertEqual(st["status"], "odustalo")
        self.assertIn("izvršitelj je odbio kupnju 0,1 SOL", st["razlog"])
        self.assertEqual(self.swaps, [])
        self.assertTrue(any("nijedna pozicija mjerenja nije otvorena" in ln for ln in lines))
        self.route_back = True
        self.assertEqual(self.korak(3600), [])
        self.assertEqual(self.swaps, [])

    def test_pala_kupnja_se_ponavlja_najvise_jednom(self):
        pad = {"status": "failed", "retry": True, "error": "nalog je istekao prije slanja"}
        self.buy_plan = [dict(pad), dict(pad)]
        self.korak()
        self.assertEqual(self.st()["status"], "ceka")
        self.assertEqual(self.korak(mjerenje.PAUZA_S - 1), [])
        self.korak(1)
        self.assertEqual(len(self.kupnje()), 2)
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertEqual(self.korak(3600), [])
        self.assertEqual(len(self.kupnje()), 2)

    def test_pala_pa_prosla(self):
        self.buy_plan = [{"status": "failed", "retry": True, "error": "nalog je istekao prije slanja"}]
        self.korak()
        self.korak(mjerenje.PAUZA_S)
        self.assertEqual(self.st()["status"], "prodaja")
        self.korak(1)
        self.assertEqual(len(self.st()["rezultati"]), 1)

    def test_nesiguran_ishod_se_ne_ponavlja(self):
        self.buy_plan = [{"status": "failed", "retry": False, "error": "Jupiter nije potvrdio swap; provjeri wallet na Solscanu"}]
        lines = self.korak()
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertTrue(any("ishod swapa nije siguran" in ln for ln in lines))
        self.assertEqual(self.korak(600), [])
        self.assertEqual(len(self.kupnje()), 1)

    def test_trosak_iznad_granice_bez_nadjacavanja_odbija(self):
        self.buy_plan = [{"status": "blocked", "error": "trošak 9% > 6%", "cost_pct": 9.0}]
        self.korak()
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertEqual(self.swaps[0]["cap"], self.cfg()["max_cost_pct"])   # 0.1 SOL keeps the owner's cost cap


class Pravilo6NijeStrategija(Baza):
    def test_ne_broji_se_u_stropove_ni_u_stop_gubitka_a_broji_u_pnl_novcanika(self):
        self.sve()
        now, tz = self.t, "Europe/Zagreb"
        self.assertEqual(executor.auto_buys(self.con, now, "live", tz), 0)
        self.assertEqual(executor.auto_spent(self.con, now, "live", tz), 0)
        self.assertEqual(executor.veliki_buys(self.con, now, "live", tz), 0)
        puni = executor.day_pnl(self.con, now, "live", tz)
        self.assertLess(puni, -0.008)                                                  # real: in the wallet's day
        self.assertAlmostEqual(executor.day_pnl(self.con, now, "live", tz, strategije=True), 0.0, places=9)
        # a strategy's own loss still counts; the measurement on top does not push it over the global stop
        self.con.execute("INSERT INTO positions (token, opened_ts, closed_ts, mode, status, reason, sol_in, sol_back, qty_raw, "
                         "qty_left) VALUES ('X', ?, ?, 'live', 'closed', 'veliki: raspon', 0.6, 0.105, 1, 0)",
                         (int(now), int(now)))
        self.con.commit()
        self.assertLessEqual(executor.day_pnl(self.con, now, "live", tz), -0.5)
        self.assertAlmostEqual(executor.day_pnl(self.con, now, "live", tz, strategije=True), -0.495, places=9)
        self.assertEqual(executor.auto_hard(self.con, 0.1, now, tz), [])
        st = executor.switch_status(self.con, now, self.cfg(), tz)
        self.assertFalse(st["stopped"])
        self.assertEqual(st["buys"], 1)                      # the strategy's one buy, none of the measurement's
        self.assertLessEqual(st["pnl"], -0.5)                # what the wallet really made today
        self.assertEqual(st["by"]["mjerenje"]["buys"], 3)    # told apart, in no strategy's row
        self.assertEqual(set(st["by"]), {"mjerenje", "veliki"})

    def test_neuspjela_kupnja_mjerenja_ne_tereti_strategije(self):
        self.buy_plan = [{"status": "failed", "retry": False, "error": "greška", "fee_lamports": 9000,
                          "attempts": [{"status": "failed", "fee_lamports": 9000, "route": "v2"}], "fee_total": 9000}]
        self.korak()
        self.assertAlmostEqual(executor.day_pnl(self.con, self.t, "live"), -9000 / 1e9, places=12)
        self.assertEqual(executor.day_pnl(self.con, self.t, "live", strategije=True), 0)

    def test_strategy_of_i_kriticar_ga_ne_vide_kao_strategiju(self):
        self.sve()
        self.assertEqual(executor.strategy_of("mjerenje troška: 0,3 SOL"), "mjerenje")
        self.assertTrue(executor.is_mjerenje("mjerenje troška: prodaja"))
        self.assertFalse(executor.is_mjerenje("veliki: raspon"))
        self.con.execute("INSERT INTO positions (token, opened_ts, closed_ts, mode, status, reason, sol_in, sol_back, qty_raw, "
                         "qty_left) VALUES ('X', ?, ?, 'live', 'closed', 'veliki: raspon', 0.1, 0.11, 1, 0)",
                         (int(self.t), int(self.t)))
        self.con.commit()
        stats = cdata.strategy_stats(self.con, now=self.t + 1, lpath=os.path.join(self.tmp.name, "nema.db"), detail=False)
        self.assertEqual(set(stats), {"veliki"})

    def test_model_troska_ne_cita_naloge_mjerenja(self):
        self.sve()
        self.assertIn(executor.MJERENJE_SRC, cost.CALIB_SQL)
        self.assertEqual(self.con.execute(cost.CALIB_SQL, (cost.CALIB_N,)).fetchall(), [])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM orders WHERE cost_pct IS NOT NULL").fetchone()[0], 6)
        from veliki import replay
        self.assertNotIn("mjerenje", inspect.getsource(replay))   # RT_FLOOR and the replay are not touched

    def test_nema_demo_retka(self):
        self.sve()
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM positions WHERE league_id IS NOT NULL OR paper_id IS NOT "
                                          "NULL").fetchone()[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "league.db")))


class Pravilo7Env(Baza):
    def test_iskljuceno_envom(self):
        os.environ["MJERENJE_TROSKA"] = "0"
        self.assertEqual(self.korak(), ["mjerenje troška: isključeno (MJERENJE_TROSKA=0)"])
        self.assertEqual(self.korak(60), [])
        self.assertEqual(self.swaps, [])
        self.assertIsNone(self.st())
        self.assertNotIn(mjerenje.KLJUC, settings.raw(self.con))
        os.environ["MJERENJE_TROSKA"] = "1"
        self.korak()
        self.assertEqual(len(self.kupnje()), 1)


class Restart(Baza):
    def test_kupljeno_a_neprodano_prodaje_jednom_pa_nastavlja(self):
        self.korak()
        with mock.patch.object(mjerenje, "PROCES", "novi-proces"):
            lines = self.korak(45)
            self.assertIn("nakon restarta", lines[0])
            self.assertEqual(len(self.prodaje()), 1)
            self.assertEqual(len(self.st()["rezultati"]), 1)
            self.assertEqual(self.st()["status"], "ceka")

    def test_kupljeno_a_neprodano_prodaja_padne_nema_drugog_pokusaja(self):
        self.korak()
        self.sell_plan = [{"status": "failed", "retry": True, "error": "nema rute"}]
        with mock.patch.object(mjerenje, "PROCES", "novi-proces"):
            self.korak(45)
            self.assertEqual(self.st()["status"], "odustalo")
            self.assertEqual(self.korak(30), [])
        self.assertEqual(len(self.prodaje()), 1)
        self.assertEqual(len(self.kupnje()), 1)
        self.assertEqual(len(mjerenje.otvorene(self.con)), 1)

    def test_prekid_usred_kupnje_nikad_ne_kupuje_ponovno_naslijepo(self):
        self.buy_plan = [RuntimeError("proces ugašen usred swapa")]
        with self.assertRaises(RuntimeError):
            self.korak()
        self.assertEqual(self.st()["status"], "kupnja")   # written before the swap
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchall(), [("pending",)])
        with mock.patch.object(mjerenje, "PROCES", "novi-proces"):
            self.assertEqual(self.korak(40), [])              # still 'pending': waits for reconcile_pending, buys nothing
            self.assertEqual(len(self.kupnje()), 1)
            executor.reconcile_pending(self.con, now=self.t + 61, balance_of=lambda t: 1_000_000)   # the swap had landed
            self.held_raw[A] = 1_000_000
            lines = self.korak(62)
            self.assertIn("nakon restarta: kupnja 0,1 SOL je u knjizi", lines[0])
            self.assertEqual(self.st()["status"], "prodaja")
            self.korak(1)                                     # the one sale
        st = self.st()
        self.assertEqual(len(self.prodaje()), 1)
        self.assertEqual(len(self.kupnje()), 1)
        self.assertEqual(st["status"], "odustalo")            # sold, but the buy's amounts were never booked
        self.assertIn("nije izmjeren", st["razlog"])
        self.assertEqual(self.con.execute("SELECT status FROM positions").fetchall(), [("closed",)])

    def test_prekid_usred_kupnje_swap_nije_prosao(self):
        self.buy_plan = [RuntimeError("proces ugašen")]
        with self.assertRaises(RuntimeError):
            self.korak()
        executor.reconcile_pending(self.con, now=self.t + 61, balance_of=lambda t: 0)   # nothing in the wallet
        lines = self.korak(62)
        self.assertEqual(self.st()["status"], "odustalo")
        self.assertIn("ne ponavljam je naslijepo", lines[0])
        self.assertEqual(len(self.kupnje()), 1)

    def test_prekid_prije_slanja_jedan_novi_pokusaj(self):
        with mock.patch.object(executor, "buy", side_effect=RuntimeError("ugašen prije slanja")):
            with self.assertRaises(RuntimeError):
                self.korak()
        self.assertEqual(self.st()["status"], "kupnja")
        self.assertEqual(self.swaps, [])
        lines = self.korak(5)
        self.assertIn("prekinuta prije slanja", lines[0])
        self.assertEqual(self.swaps, [])               # this pass only moves the state
        self.korak(mjerenje.PAUZA_S)
        self.assertEqual(len(self.kupnje()), 1)
        self.assertEqual(self.st()["status"], "prodaja")

    def test_greska_koraka_ne_rusi_petlju(self):
        with mock.patch.object(mjerenje, "korak", side_effect=RuntimeError("x")), mock.patch("builtins.print") as pr:
            self.assertEqual(run_trade._mjerenje_once(self.con, self.cfg()), [])
            self.assertEqual(run_trade._mjerenje_once(self.con, self.cfg()), [])
        self.assertEqual(pr.call_count, 1)   # one line a minute
        self.assertIn("_mjerenje_once(con, cfg)", inspect.getsource(run_trade.cmd_follow))


class IzborTokena(Baza):
    def test_najdublji_pool_koji_zadovoljava(self):
        self.korak()
        self.assertEqual(self.st()["token"], {"mint": A, "simbol": "AAA"})   # B: volume too low, C: liquidity too low

    def test_volumen_likvidnost_starost_i_drzani(self):
        self.kv[B]["volumen24"] = 600_000
        tok, _q, _why = mjerenje.izbor(self.con, self.t)
        self.assertEqual(tok["mint"], B)                      # now the deepest (9M) qualifies
        self.kv[B]["age"] = 61
        self.assertEqual(mjerenje.izbor(self.con, self.t)[0]["mint"], A)   # a stale quote is out
        self.kv[B]["age"] = 59
        self.assertEqual(mjerenje.izbor(self.con, self.t)[0]["mint"], B)
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, sol_back) "
                         "VALUES (?,?,?,?,?,?,?,?,0)", (B, int(self.t), "live", "open", "veliki: raspon", 0.1, 5, 5))
        self.con.commit()
        self.assertEqual(mjerenje.izbor(self.con, self.t)[0]["mint"], A)   # held by an open real position
        self.kv[A]["likvidnost"] = 1_999_999
        tok, _q, why = mjerenje.izbor(self.con, self.t)
        self.assertIsNone(tok)
        for dio in ("nijedan od 3 tokena liste veliki", "likvidnost ispod 2M $: 2", "u otvorenoj pravoj poziciji: 1"):
            self.assertIn(dio, why)

    def test_probna_pozicija_ne_drzi_token(self):
        self.con.execute("INSERT INTO positions (token, opened_ts, mode, status, reason, sol_in, qty_raw, qty_left, sol_back) "
                         "VALUES (?,?,?,?,?,?,?,?,0)", (A, int(self.t), "dry", "open", "copy KOL x", 0.1, 5, 5))
        self.con.commit()
        self.assertEqual(mjerenje.izbor(self.con, self.t)[0]["mint"], A)

    def test_nijedan_ne_zadovoljava_pa_kasnije(self):
        self.kv[A]["volumen24"] = 100_000
        lines = self.korak()
        self.assertIn("bez kupnje: nijedan od 3 tokena liste veliki ne zadovoljava", lines[0])
        self.assertEqual(self.korak(mjerenje.PONOVI_S - 1), [])
        self.kv[A]["volumen24"] = 900_000
        self.korak(1)
        self.assertEqual(len(self.kupnje()), 1)

    def test_prazna_lista_i_kotacije_bez_odgovora(self):
        self.lista = []
        self.assertIn("lista veliki je prazna", self.korak()[0])
        self.lista = [{"mint": A, "symbol": "AAA"}]
        with mock.patch.object(mjerenje, "kotacije", side_effect=OSError("timeout")):
            self.assertIn("kotacije nisu dostupne (OSError)", self.korak(mjerenje.PONOVI_S)[0])
        self.assertEqual(self.swaps, [])

    def test_isti_token_za_sva_tri_uloga(self):
        self.krug()
        self.kv[B]["volumen24"] = 600_000   # a deeper one qualifies later: the token stays
        self.korak(mjerenje.PAUZA_S)
        self.assertEqual({s["token"] for s in self.swaps}, {A})
        self.assertEqual(len(self.kupnje()), 2)

    def test_token_izgubi_uvjet_izmedu_uloga_ceka(self):
        self.krug()
        self.kv[A]["likvidnost"] = 1_000_000
        lines = self.korak(mjerenje.PAUZA_S)
        self.assertIn("0,3 SOL: bez kupnje: AAA: likvidnost ispod 2M $", lines[0])
        self.assertEqual(len(self.kupnje()), 1)

    def test_kotacije_iz_dexscreenera(self):
        pairs = [{"baseToken": {"address": A, "symbol": "AAA"}, "priceUsd": "0.5", "liquidity": {"usd": 3e6},
                  "volume": {"h24": 400_000}, "marketCap": 9e7},
                 {"baseToken": {"address": A, "symbol": "AAA"}, "priceUsd": "0.51", "liquidity": {"usd": 1e6},
                  "volume": {"h24": 200_000}},
                 {"baseToken": {"address": "DRUGI"}, "priceUsd": "9", "liquidity": {"usd": 9e9}, "volume": {"h24": 9e9}}]
        from dexscreener import client
        self.addCleanup(mock.patch.stopall)
        mock.patch.stopall()
        with mock.patch.object(client, "tokens_live", lambda chain, mints, ttl=None: pairs), \
                mock.patch.object(mjerenje, "_sat", lambda: 77.0):
            kv = mjerenje.kotacije([A])
        self.assertEqual(kv, {A: {"cijena": 0.5, "cijena_sol": None, "likvidnost": 3e6, "volumen24": 600_000.0, "mcap": 9e7,
                                  "simbol": "AAA", "sumnjivo": None, "ts": 77.0}})
        pairs[0].update(quoteToken={"address": mjerenje.SOL}, priceNative="0.0025")
        with mock.patch.object(client, "tokens_live", lambda chain, mints, ttl=None: pairs):
            self.assertEqual(mjerenje.kotacije([A])[A]["cijena_sol"], 0.0025)
        self.assertEqual(mjerenje.SOL, jupiter.SOL)

    def test_pomak_u_sol_kad_je_par_u_sol(self):
        # USD says -0.5 %, the pair's own SOL price says -1 % (SOL/USD moved meanwhile): the round trip is in SOL
        self.kv[A]["cijena_sol"] = 0.004
        real = self.swap

        def swap(inp, out, amount, live, *a, **k):
            r = real(inp, out, amount, live, *a, **k)
            if inp == jupiter.SOL:
                self.kv[A]["cijena_sol"] = 0.00396
            return r
        with mock.patch.object(executor, "swap", swap):
            self.krug()
        r = self.st()["rezultati"][0]
        self.assertEqual(r["mid_u"], "SOL")
        self.assertAlmostEqual(r["pomak_pct"], 1.0, places=3)


class Vijece(Baza):
    def test_smjer_cita_spremljeni_rezultat(self):
        self.assertIn(("Izmjeren trošak kruga po ulogu", smjer._mjerenje), smjer.IZVORI)
        self.assertIsNone(smjer._mjerenje(self.t, self.con))
        self.assertIsNone(smjer._mjerenje(self.t, None))
        self.sve()
        txt = smjer._mjerenje(self.t, self.con)
        self.assertIn("krug pri 0,1 / 0,3 / 0,5 SOL: 1,1 % / 0,9 % / 0,9 %", txt)
        self.assertIn("sva tri uloga izmjerena", txt)
        self.assertNotIn(A, txt)   # no address in the brief
        self.assertEqual(json.loads(self.con.execute("SELECT v FROM settings WHERE k=?", (mjerenje.KLJUC,)).fetchone()[0])
                         ["status"], "gotovo")

    def test_necitljiv_zapis_nikad_ne_trguje(self):
        for bad in ('"nešto drugo"', "[1, 2]", '{"bez": "statusa"}'):
            self.con.execute("INSERT OR REPLACE INTO settings (k, v, ts, who) VALUES (?,?,?,?)", (mjerenje.KLJUC, bad, 1, "x"))
            self.con.commit()
            self.assertEqual(self.korak(60), [])
            self.assertEqual(mjerenje.citaj(self.con)[0]["status"], "odustalo")
        self.assertEqual(self.swaps, [])


if __name__ == "__main__":
    unittest.main()
